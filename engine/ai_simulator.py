from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
import random

from .ai_policy import choose_activation_action, choose_cast_action
from .card_loader import load_cards
from .game import Game
from .oracle import compile_card_oracle
from .models import CardDefinition, Permanent, PlayerState


@dataclass
class InteractionIssue:
    game_index: int
    turn: int
    message: str


@dataclass
class SimulationReport:
    games_requested: int
    games_completed: int
    interaction_count: int
    issues: list[InteractionIssue] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    #: Casts the engine declined for a rules reason, by the reason it gave.
    #: **Not** issues: a spell refused for want of a legal target is the cast
    #: gate working (CR 601.2c), and nothing is spent. They are counted because
    #: the AI re-proposes the same card the next turn, so a large number here is
    #: a seat doing nothing all game — which no other number in this report
    #: shows.
    refused_casts: Counter[str] = field(default_factory=Counter)

    @property
    def ok(self) -> bool:
        return not self.issues


# The prompts a headless simulation answers for itself, in the order it answers
# them. Naming the kinds rather than draining the whole queue keeps the order
# fixed: a library search consumes randomness, so which prompt is answered first
# is part of what a seed reproduces.
#
# Every kind registered ``suspends`` has to appear here, and that is a stronger
# requirement than "otherwise its prompt sits unanswered": a suspending prompt
# holds ``game.effect_suspended``, so leaving one owed would stop the *next*
# resumable loop anywhere in the game after one step. ``effect_order`` is the
# one exception and does not need draining — a non-interactive seat is answered
# with the default before it is ever queued (engine/replacements.py). Held by
# tests/ai/test_ai_simulator.py.
_SIMULATED_CHOICES = (
    "search_library", "search_exile_cards", "scry", "reorder_library", "discard",
    "balance", "optional_pay", "untap_up_to", "look_top_pick",
    # Appended rather than inserted: no deck the simulator builds arms this
    # one today, so the position cannot change an existing seed, and a
    # blocking prompt left owed would freeze the seat that owes it.
    "revealed_hand_pick",
    # A counted search's "which found card goes where" — consumes no
    # randomness (the shuffle was the search's), but it suspends, so leaving
    # one owed would wedge every later resumable loop.
    "search_destination",
    # "Choose a number" (Shapeshifter) and "remove any number of counters"
    # (Tetravus). Appended for the same reason as the two above: no deck the
    # simulator builds arms one today, so the position cannot change an
    # existing seed — and the counter form suspends.
    "number_choice",
    # "Put two cards from your hand on top of your library" (Brainstorm,
    # Stunted Growth). Appended, and this one a simulated deck really can arm —
    # it suspends, so a seat left owing it would wedge every later resumable
    # loop, which is what the guard beside this list checks for.
    "hand_to_library",
    # "Target opponent chooses a card in your graveyard" (Forgotten Lore).
    # Appended for the reason the three above are: no seed builds a deck that
    # arms it today, so the position cannot change an existing run - and it
    # suspends, because the sentence after it reads the pick and the round
    # after that may not choose it again.
    "graveyard_pick_for_price",
)


def _resolve_pending_choices(game: Game) -> None:
    game.auto_resolve_pending_choices(kinds=_SIMULATED_CHOICES)


def _find(cards: dict[str, CardDefinition], name: str) -> CardDefinition:
    if name not in cards:
        # Named the pool "LEA data" back when the path was hardcoded; the pool
        # is now whichever set the caller chose, and a set that lacks a card
        # this decklist needs has to say which card rather than which set file.
        raise ValueError(f"the card pool has no {name!r}, which the simulator's deck needs")
    return cards[name]


# CR 100.2b's limited deck: 40 cards minimum, built from one product plus basic
# land cards. 17 lands to 23 spells is the ratio limited play settled on, and it
# is what makes the AI cast anything — a deck drawn uniformly from a set is
# mostly spells it cannot pay for.
LIMITED_DECK_SIZE = 40
LIMITED_LAND_COUNT = 17

_BASIC_LAND_TYPES = ("Plains", "Island", "Swamp", "Mountain", "Forest")

# Colour a basic land taps for, by its subtype (CR 305.6). Used to pick a mana
# base for the colours a deck actually plays, not to *define* the land — the
# card definitions come from the pool like every other card.
_BASIC_LAND_COLORS = {
    "Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G",
}

_basic_land_cache: dict[str, CardDefinition] | None = None


def _is_land(card: CardDefinition) -> bool:
    return "land" in (card.type_line or "").lower()


def _basic_land_pool(cards: dict[str, CardDefinition]) -> dict[str, CardDefinition]:
    """The five basics, preferring *cards*' own printings.

    CR 100.2b builds a limited deck from "this product **and basic land
    cards**", so basics are not part of the set being tested — which is what
    makes the rest of this work at all. Antiquities, Legends and The Dark print
    no basic land between them, and a deck of their coloured spells with their
    own lands casts nothing: the run would report no illegal interactions over
    games where nothing was ever paid for. Where the set does print them (a base
    set, 4ED) its own copies are used, so the deck is that set's cards.

    The fallback reads the manifest through ``card_loader``'s helpers rather
    than inventing five ``CardDefinition``s, because a synthesized basic is card
    data nobody ingested and it would drift from the printed one silently.
    """
    from_pool = {
        subtype: cards[subtype] for subtype in _BASIC_LAND_TYPES if subtype in cards
    }
    if len(from_pool) == len(_BASIC_LAND_TYPES):
        return from_pool

    global _basic_land_cache
    if _basic_land_cache is None:
        from .card_loader import manifest_set_paths

        found: dict[str, CardDefinition] = {}
        for path in manifest_set_paths():
            for card in load_cards(str(path)):
                if card.name in _BASIC_LAND_TYPES and card.name not in found:
                    found[card.name] = card
            if len(found) == len(_BASIC_LAND_TYPES):
                break
        _basic_land_cache = found
    return {**_basic_land_cache, **from_pool}


def _castable_colors(card: CardDefinition) -> frozenset[str]:
    """The colours a deck must produce to cast this card.

    ``color_identity`` rather than ``colors``: a card's activated abilities cost
    mana too, and a deck that can cast Prodigal Sorcerer but never untap-tap it
    is not exercising the card.
    """
    return frozenset(card.color_identity or ())


def _choose_colors(
    spells: list[CardDefinition], rng: random.Random, count: int = 2
) -> frozenset[str]:
    """Pick the deck's colours by weight of what the pool actually prints.

    Weighted rather than uniform so a set's shape decides its decks: Antiquities
    is almost entirely artifacts and lands in colourless decks that cast their
    whole pool, while a base set spreads across all five.
    """
    weights = Counter(color for spell in spells for color in _castable_colors(spell))
    if not weights:
        return frozenset()
    population = sorted(weights)
    chosen: set[str] = set()
    for _ in range(min(count, len(population))):
        remaining = [color for color in population if color not in chosen]
        picks = rng.choices(remaining, weights=[weights[c] for c in remaining], k=1)
        chosen.add(picks[0])
    return frozenset(chosen)


def build_limited_deck(
    cards: dict[str, CardDefinition],
    seed: int,
    *,
    size: int = LIMITED_DECK_SIZE,
    land_count: int = LIMITED_LAND_COUNT,
    required: Sequence[str] = (),
) -> list[CardDefinition]:
    """A random, deterministic limited deck out of *cards*.

    Singleton spells rather than playsets: the simulator exists to find bad
    interactions across a set, so 23 different cards per deck is 23 times the
    coverage of the four-of decklist this replaced — which played eight cards
    and could only be built from a base set.

    *required* names cards the deck must contain, for a regression test that
    needs its subject in play. Everything else is drawn at random from what the
    chosen colours can cast, cheapest-weighted so the AI can actually pay.
    """
    rng = random.Random(seed)

    pinned = [_find(cards, name) for name in required]
    basics = _basic_land_pool(cards)
    pool = [card for card in cards.values() if card.name not in basics]

    spells = [card for card in pool if not _is_land(card)]
    colors = _choose_colors(spells, rng) | frozenset(
        color for card in pinned for color in _castable_colors(card)
    )

    playable = [
        card for card in spells
        if _castable_colors(card) <= colors and card not in pinned
    ]
    # Cheap cards first, with a random tiebreak: a deck of six-drops is a deck
    # the AI never casts, and a run that casts nothing reports a clean sweep
    # over games that never happened.
    rng.shuffle(playable)
    playable.sort(key=lambda card: card.cmc or 0)
    spell_count = max(0, size - land_count)
    chosen_spells = (pinned + playable)[:spell_count]

    nonbasic = [
        card for card in pool
        if _is_land(card) and set(card.produced_mana or ()) & (colors | {"C"})
    ]
    rng.shuffle(nonbasic)
    deck_lands = nonbasic[: max(0, land_count // 4)]

    wanted = sorted(colors) or ["C"]
    for index in range(land_count - len(deck_lands)):
        color = wanted[index % len(wanted)]
        subtype = next(
            (name for name, c in _BASIC_LAND_COLORS.items() if c == color), "Wastes"
        )
        if subtype in basics:
            deck_lands.append(basics[subtype])
        elif basics:
            deck_lands.append(basics[sorted(basics)[index % len(basics)]])

    deck = chosen_spells + deck_lands
    rng.shuffle(deck)
    return deck


def _zone_counter(game: Game) -> Counter[str]:
    """Every card in the game, by name — the whole board, not one seat's.

    Two corrections, both of which only a deck built from a whole set can
    reach. **Every zone counts**: this read library, hand, graveyard and
    battlefield, which were all the zones the old eight-card decklist could put
    a card in. Feldon's Cane exiles itself to shuffle a graveyard back and
    Contract from Below antes the top card, so both looked like a card
    vanishing from the game — a false alarm, reported dozens of times per run.

    And the count is **global rather than per seat**, because a card legally
    changing hands is not a leak: Old Man of the Sea takes control of a
    creature and Contract from Below antes into another player's zone, either
    of which fails a per-seat comparison while nothing is wrong. What is left
    is the invariant actually worth asserting — a card may move anywhere, and
    may not stop existing or start existing twice.
    """
    counter: Counter[str] = Counter()
    already: set[int] = set()
    for player in game.players:
        for zone in (
            player.library, player.hand, player.graveyard,
            player.exile, player.ante, player.command_zone,
        ):
            for card in zone:
                counter[card.name] += 1
        for permanent in player.phased_out:
            already.add(id(permanent))
            if not permanent.metadata.get("is_token"):
                counter[permanent.card.name] += 1
    for _seat, permanent in game.permanents_with_controller():
        already.add(id(permanent))
        # Ignore generated tokens in zone conservation checks.
        if permanent.metadata.get("is_token"):
            continue
        counter[permanent.card.name] += 1
    # A spell or ability mid-resolution is still a card in the game. The check
    # runs after the pending-choice drain, so this is normally empty — but a
    # prompt that suspends leaves its object here, and counting it stops that
    # from reading as a disappearance.
    for item in game.stack:
        # An *ability* on the stack is not a card (CR 113.7) and its `card` is
        # the source permanent's, which is counted on the battlefield already —
        # so counting it duplicates the permanent. `ability_instruction` is the
        # discriminator `StackItem` actually carries; there is no `is_ability`,
        # and asking for one with a default quietly counted every ability.
        if item.ability_instruction is None and item.card is not None:
            counter[item.card.name] += 1
    # And a permanent another permanent is *holding*. Oubliette's scoped
    # exile-and-return keeps the creature it removed as a live ``Permanent`` on
    # its own metadata rather than in any zone list, so the creature is in the
    # game and in none of the lists above — it read as a card vanishing on the
    # turn Oubliette landed and as one appearing on the turn it left.
    #
    # Only the keys that mean *held out of play*, which is a narrower rule than
    # "any permanent reachable from metadata" and had to be. Permanents are
    # stored in metadata for several unrelated jobs: `attached_auras` points at
    # things that are on the battlefield already (counting those made every Aura
    # in play a phantom extra card) and `damaged_by_sources_this_turn` points at
    # a source that has since died (counting that resurrected a sacrificed
    # artifact for one turn). Neither is a zone. The prefix below is the shape
    # Oubliette's hook writes, and a new hook that holds a permanent off-zone has
    # to be added here — it will announce itself as a phantom missing card
    # rather than passing quietly, which is the failure direction to want.
    for held in _held_out_of_play(game):
        if id(held) not in already and not held.metadata.get("is_token"):
            already.add(id(held))
            counter[held.card.name] += 1
    return counter


#: Metadata keys under which a permanent is *kept out of every zone* while
#: another permanent holds it. Oubliette's scoped exile-and-return is the only
#: one today (`engine/card_hooks.py::_oubliette_leaves`); it stores the removed
#: creature and its attachments on the Oubliette itself, so they belong to no
#: player's list and are still very much in the game.
_HELD_OUT_OF_PLAY_PREFIX = "phased_out"


def _held_out_of_play(game: Game) -> list[Permanent]:
    """Every ``Permanent`` another permanent is holding outside all zones.

    One level deep, in the shapes the hook stores: the permanent itself, or a
    list of ``(seat, permanent)`` pairs.
    """
    found: list[Permanent] = []

    def collect(value) -> None:
        if isinstance(value, Permanent):
            found.append(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, Permanent):
                    found.append(item)
                elif isinstance(item, (list, tuple)):
                    found.extend(x for x in item if isinstance(x, Permanent))

    for _seat, permanent in game.permanents_with_controller():
        for key, value in permanent.metadata.items():
            if str(key).startswith(_HELD_OUT_OF_PLAY_PREFIX):
                collect(value)
    return found


def _assert_expected(
    card: CardDefinition,
    before: tuple[PlayerState, PlayerState],
    after: tuple[PlayerState, PlayerState],
    caster_index: int,
    target_index: int,
) -> str | None:
    """What each card of the decklist above is expected to have done.

    **These card names stay.** The engine's standing rule is that names live only
    in ``card_hooks.py``, and ``ai_policy``'s valuations were derived out for
    exactly that reason — but this is a *test oracle*, and a test oracle derived
    from the system under test asserts nothing. Measured: compile Lightning Bolt
    with its damage mis-parsed as 1, cast it, and the printed expectation below
    fires ("damage did not match prevention/cap effects") while the same check
    reading ``deal_damage``'s payload expects 1, sees 1, and passes. The numbers
    here are read off the printed card by a human on purpose; that independence
    is the whole value of the check.

    The decay this *is* exposed to is the decklist moving out from under it — an
    expectation for a card ``_build_deck`` no longer plays stops firing with
    nothing failing. ``tests/ai/test_ai_simulator.py`` holds the two in step.
    """
    before_target = before[target_index]
    after_target = after[target_index]

    if card.name == "Lightning Bolt":
        base_damage = 3
        if before_target.combat_damage_cap_one_charges > 0 and base_damage > 1:
            base_damage = 1
        expected_damage = max(0, base_damage - before_target.damage_prevention_pool)
        actual_damage = before_target.life - after_target.life
        if actual_damage != expected_damage:
            return "Lightning Bolt damage did not match prevention/cap effects"

    if card.name == "Ancestral Recall":
        hand_delta = len(after_target.hand) - len(before_target.hand)
        cast_offset = 1 if target_index == caster_index else 0
        drawn = hand_delta + cast_offset
        if drawn != min(3, len(before_target.library)):
            return "Ancestral Recall did not draw expected cards"

    if card.name == "Healing Salve":
        life_gain = after_target.life - before_target.life
        prevention_gain = after_target.damage_prevention_pool - before_target.damage_prevention_pool
        if life_gain != 3 and prevention_gain != 3:
            return "Healing Salve did not apply expected life-gain or prevention mode"
    if card.name == "Unsummon" and any(perm.card.primary_type == "creature" for perm in before_target.battlefield):
        creature_before = sum(1 for perm in before_target.battlefield if perm.card.primary_type == "creature")
        creature_after = sum(1 for perm in after_target.battlefield if perm.card.primary_type == "creature")
        if creature_after != creature_before - 1:
            return "Unsummon did not remove one target creature"
    if card.name == "Disenchant" and any(
        perm.card.primary_type in {"artifact", "enchantment"} for perm in before_target.battlefield
    ):
        ae_before = sum(1 for perm in before_target.battlefield if perm.card.primary_type in {"artifact", "enchantment"})
        ae_after = sum(1 for perm in after_target.battlefield if perm.card.primary_type in {"artifact", "enchantment"})
        if ae_after != ae_before - 1:
            return "Disenchant did not destroy one target artifact or enchantment"

    return None


def _clone_player(game: Game, player: PlayerState) -> PlayerState:
    return PlayerState(
        name=player.name,
        life=player.life,
        hand=list(player.hand),
        library=list(player.library),
        battlefield=[
            Permanent(
                card=perm.card,
                tapped=perm.tapped,
                power_bonus=perm.power_bonus,
                toughness_bonus=perm.toughness_bonus,
                regeneration_shield=perm.regeneration_shield,
                metadata=dict(perm.metadata),
            )
            for perm in game.controlled_by(player)
        ],
        graveyard=list(player.graveyard),
        mana_pool=dict(player.mana_pool),
        damage_prevention_pool=player.damage_prevention_pool,
        combat_damage_cap_one_charges=player.combat_damage_cap_one_charges,
        has_no_max_hand_size=player.has_no_max_hand_size,
        can_spend_white_as_red=player.can_spend_white_as_red,
    )


def _snap(game: Game) -> tuple[PlayerState, PlayerState]:
    return (_clone_player(game, game.players[0]), _clone_player(game, game.players[1]))


def run_ai_simulation(
    cards_path: Path | Sequence[Path],
    games: int = 10,
    seed: int = 1337,
    max_turns: int = 18,
    required_cards: Sequence[str] = (),
) -> SimulationReport:
    """Play *games* AI-vs-AI games out of whichever pool *cards_path* names.

    Each seat gets its own random limited deck from that pool, so the set under
    test is the set being played. *required_cards* pins names into both decks —
    for a regression test whose subject has to reach the battlefield to be
    regressed.
    """
    cards = {card.name: card for card in load_cards(cards_path)}
    report = SimulationReport(games_requested=games, games_completed=0, interaction_count=0)
    rng = random.Random(seed)
    # The engine's coin flips, opening-hand shuffles, and random effects use the
    # module-level RNG. Seed it so the simulation is fully reproducible — the
    # deck-construction rng above only covers deck ordering.
    random.seed(seed)

    for game_index in range(1, games + 1):
        p1 = PlayerState(
            name=f"AI-A-{game_index}",
            library=build_limited_deck(
                cards, rng.randint(1, 1_000_000), required=required_cards
            ),
        )
        p2 = PlayerState(
            name=f"AI-B-{game_index}",
            library=build_limited_deck(
                cards, rng.randint(1, 1_000_000), required=required_cards
            ),
        )
        game = Game(players=[p1, p2])
        starting_player = game.select_starting_player()
        game.deal_opening_hands(starting_player)
        for i in range(len(game.players)):
            game.keep_hand(i)

        initial_cards = _zone_counter(game)
        log_cursor = 0
        report.log_lines.append(f"=== Game {game_index} ===")

        # game.turn starts at 1 but is never incremented by the manual step calls
        # below. Reset to 0 so the pre-loop increment lands on 1 for the very
        # first half-turn and advances correctly for every subsequent half-turn,
        # allowing summoning-sickness to clear after a creature's first full turn.
        game.turn = 0

        for turn in range(1, max_turns + 1):
            for active in (0, 1):
                game.turn += 1
                active_player = game.players[active]
                opponent = game.players[1 - active]

                game.resolve_untap_step(active)
                game.resolve_upkeep(active)
                game.resolve_draw_step(active)

                cast_action = choose_cast_action(game, active)
                if cast_action is not None:
                    card_to_cast = game.players[active].hand[cast_action.hand_index]

                    for permanent_index in cast_action.land_tap_indices:
                        permanent = game.players[active].battlefield[permanent_index]
                        game.tap_land_for_mana(active, permanent.card.name, permanent_index=permanent_index)

                    before = _snap(game)
                    # Forward the *whole* choice. Dropping the permanent target
                    # was invisible while the decklist was eight cards that
                    # target a player or nothing: an Aura reaches
                    # `cast_from_hand` with no index and is refused ("Evil
                    # Presence requires a target", CR 601.2c/115.1b), and the AI
                    # had already picked a legal land for it.
                    result = game.cast_from_hand(
                        active,
                        card_to_cast.name,
                        target_player_index=cast_action.target_player_index,
                        target_permanent_index=cast_action.target_permanent_index,
                        target_permanent_ids=cast_action.target_permanent_ids,
                        x_value=cast_action.x_value,
                    )
                    _resolve_pending_choices(game)
                    after = _snap(game)
                    report.interaction_count += 1
                    report.log_lines.append(
                        f"G{game_index} T{turn} {active_player.name} cast {card_to_cast.name} -> {result.details}"
                    )
                    if not result.supported:
                        # Two different things wore one message. `supported` on
                        # a cast result means "the cast went through", so a
                        # spell declined for want of a legal target, for a
                        # printed timing clause or by City in a Bottle was
                        # reported as an *unsupported card* — which the pool has
                        # none of. Ask the compiler, which is what that word
                        # actually means.
                        if not compile_card_oracle(card_to_cast).supported:
                            report.issues.append(InteractionIssue(
                                game_index, turn,
                                f"Unsupported card cast in simulation: {card_to_cast.name}",
                            ))
                        else:
                            report.refused_casts[
                                f"{card_to_cast.name}: {result.details}"
                            ] += 1
                    expectation_error = _assert_expected(
                        card_to_cast,
                        before,
                        after,
                        active,
                        cast_action.target_player_index,
                    )
                    if expectation_error:
                        report.issues.append(InteractionIssue(game_index, turn, expectation_error))

                activation_action = None if game.is_game_over() else choose_activation_action(game, active)
                if activation_action is not None:
                    for permanent_index in activation_action.land_tap_indices:
                        permanent = game.players[active].battlefield[permanent_index]
                        game.tap_land_for_mana(active, permanent.card.name, permanent_index=permanent_index)

                    result = game.activate_permanent_ability(
                        active,
                        activation_action.permanent_name,
                        target_player_index=activation_action.target_player_index,
                        permanent_index=activation_action.permanent_index,
                        target_permanent_index=activation_action.target_permanent_index,
                    )
                    _resolve_pending_choices(game)
                    report.interaction_count += 1
                    report.log_lines.append(
                        f"G{game_index} T{turn} {active_player.name} "
                        f"activate {activation_action.permanent_name} -> {result.details}"
                    )

                new_logs = game.log[log_cursor:]
                report.log_lines.extend(f"  {line}" for line in new_logs)
                log_cursor = len(game.log)

                current = _zone_counter(game)
                if current != initial_cards:
                    lost = initial_cards - current
                    gained = current - initial_cards
                    report.issues.append(
                        InteractionIssue(
                            game_index, turn,
                            "Zone conservation failed: "
                            f"missing {dict(lost) or '{}'}, extra {dict(gained) or '{}'}",
                        )
                    )
                    # Re-baseline, or one leak reports itself on every later
                    # turn of the game and buries whatever comes next.
                    initial_cards = current

                if active_player.life <= 0 or opponent.life <= 0 or active_player.lost or opponent.lost:
                    break

            if game.players[0].life <= 0 or game.players[1].life <= 0 or game.players[0].lost or game.players[1].lost:
                break

        report.games_completed += 1
        report.log_lines.append(
            f"RESULT G{game_index}: {game.players[0].name}={game.players[0].life}, {game.players[1].name}={game.players[1].life}"
        )
        report.log_lines.append("")

    return report