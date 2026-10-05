from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
import random

from .ai_combat import run_ai_combat_phase
from .ai_policy import (choose_activation_action, choose_cast_action,
                        choose_foreign_activation_action,
                        choose_hand_activation_action, choose_land_drop,
                        spell_being_cast, tap_planned_lands)
from .card_loader import load_cards
from .faces import whole_card
from .game import Game
from .search_filters import card_has_type
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
    #: The attack-side twin of the above, and it could not exist until this
    #: simulator had a combat phase: a declaration the engine refuses costs
    #: nothing and breaks no rule, so it fails no assertion — the seat just does
    #: not attack, and proposes the same illegal set again next turn. A non-zero
    #: count means the AI is choosing sets a restriction forbids; a *silent*
    #: one (even the fallback refused) is an issue rather than a count, because
    #: that seat attacks with nobody for the rest of the game.
    refused_attacks: Counter[str] = field(default_factory=Counter)
    #: The block-side twin, and the last of the three declarations this report
    #: can be silent about. `declare_ai_blockers` fell back to `{}` exactly the
    #: way the attack side did before that counter existed, and nothing above it
    #: could tell "the defender chose not to block" from "the defender's whole
    #: declaration was refused": both read as zero blockers. A non-zero count
    #: means the AI is choosing block maps a CR 509.1b restriction forbids; a
    #: *silent* one (even the empty declaration refused) is an issue rather than
    #: a count, because that seat blocks with nobody for the rest of the game.
    refused_blocks: Counter[str] = field(default_factory=Counter)
    #: The activation-side twin of ``refused_casts``, and the one this report
    #: never had: an activation the engine declines spends nothing and breaks
    #: no rule, and the AI proposes it again next turn. NEM's wave 2 found 80 of
    #: them across one ten-game run each of USG, TMP and MMQ by reading the
    #: log by hand — Serra's Hymn announced with no division, Rootwater Diver
    #: and Groundskeeper aimed at an empty graveyard — while every number this
    #: report printed read clean.
    refused_activations: Counter[str] = field(default_factory=Counter)
    #: How much combat actually happened. Reported for the reason
    #: `interaction_count` is: "no illegal interactions" over a run where nobody
    #: ever attacked is a true statement about nothing, and that was every run
    #: this script produced before combat existed here.
    attacks_declared: int = 0
    attackers_declared: int = 0
    blockers_declared: int = 0
    #: See `ai_combat.CombatOutcome`: the multi-blocked / banding splits, not
    #: every combat that dealt damage.
    manual_damage_splits: int = 0
    #: How many ending phases actually ran (CR 512-514), for the reason the
    #: combat counts above exist. Until PCY's wave 2 this loop went main ->
    #: combat -> next seat, so no simulated turn had ever ended: every "until
    #: end of turn" pump and shield lasted the whole game, marked damage was
    #: never removed (CR 514.2), no "at the beginning of the end step" trigger
    #: fired (CR 513.1a) and no hand was ever discarded down to its maximum
    #: (CR 514.1). Zero here is the fourth omission of the "it plays a whole
    #: turn" class coming back.
    end_steps: int = 0
    cleanup_steps: int = 0
    #: Cards the active player discarded to maximum hand size in cleanup
    #: (CR 514.1) — a number that could only ever have read zero before.
    cleanup_discards: int = 0
    #: Abilities activated on a permanent another seat controls (CR 602.1b,
    #: "Any player may activate this ability"). Zero in every run before
    #: `ai_policy.choose_foreign_activation_action` existed, because every
    #: chooser walked the seat's own battlefield.
    foreign_activations: int = 0
    #: Lands played (CR 305.1), by the land-drop pass rather than as the
    #: turn's one cast. **Not** counted in ``interaction_count``: a land play is
    #: a special action that uses no stack (CR 116.2a), and a run whose only
    #: actions were land drops cast nothing — which is what that count's zero
    #: exists to say. Until PCY's wave 3 a land *was* the turn's cast, so a
    #: seat that played one cast nothing else that turn, and every number this
    #: report printed was over games in which no mana cost was ever paid.
    lands_played: int = 0
    #: Step changes that left something owed behind them, by what and where:
    #: ``"upkeep -> draw: optional_pay (Elfhame Sanctuary)"``. **The sixth
    #: omission of the "it plays a whole turn" class, and the first that is not
    #: a missing phase**: every step ran, in order, and a decision one of them
    #: asked for was taken two steps later. An upkeep trigger's "you may search
    #: your library … If you do, you skip your draw step this turn" was answered
    #: after the draw, so the skip was armed and never spent; Mirri's Guile
    #: arranged the top three after the turn's card had been drawn off them;
    #: a combat trigger's "you may" was taken once combat was over. The run
    #: completed, the interaction count was non-zero and the issue list was
    #: empty — and here the *log* read right too, because each line was there,
    #: in the wrong order.
    #:
    #: Counted by the game itself at the one line every step change passes
    #: through (``_SimulatedGame._set_phase_and_step``), never by this module's
    #: own walk, because the walk is what was wrong. Zero is the claim that no
    #: step of any simulated turn ended around an unanswered question (CR 608.2,
    #: CR 500.2); ``simulate_ai_games.py`` exits 1 on anything else.
    steps_left_owing: Counter[str] = field(default_factory=Counter)
    #: Turns that were **extra** turns (CR 500.7) — Time Walk's, Time Warp's,
    #: Final Fortune's. Zero in every run before INV's wave 2, and not because
    #: no seat cast one: the loop alternated the two seats itself, so an extra
    #: turn was queued by the spell and never taken, and "you skip your next
    #: turn" (Meditate, Chronatog) skipped nothing. The seventh omission of
    #: the class, found by counting the queue at the end of four games with
    #: Time Walk pinned: five resolved, five still queued.
    extra_turns_taken: int = 0
    #: How many step changes that count was taken over. A zero above means
    #: something only beside a number here: an instrument that looked at
    #: nothing reports nothing owed.
    step_changes: int = 0

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
    # "Choose a card name." (Foreshadow.) Appended for the reason the entries
    # above are — the position cannot change an existing seed — and it
    # suspends, so a seat left owing it would wedge every later resumable loop.
    "choose_card_name",
    # "Each player may draw up to two cards" (Truce). Appended for the reason
    # the four above are — the position cannot change an existing seed — and it
    # suspends, so a seat left owing it would wedge every later resumable loop.
    # A simulated HML deck really can arm it, and on *every* seat at once.
    "draw_up_to",
    # "Exile any number of cards from your hand face down." (Scroll Rack.)
    # Appended for the reason every entry above it is — the position cannot
    # change an existing seed — and it suspends, because the sentence behind it
    # puts *that many* cards from the library into the hand. A simulated TMP
    # deck really can arm it.
    "exile_hand_pile_choice",
    # "Starting with you, each player chooses one of the exiled cards and
    # puts it onto the battlefield tapped under their control." (Thieves'
    # Auction.) Appended for the reason every entry above it is — the
    # position cannot change an existing seed — and it suspends hardest of
    # any of them: the whole of the rest of the resolution is other seats
    # picking out of the pile this answer shortens, so a seat left owing it
    # would wedge the round-robin and every later resumable loop with it.
    "exiled_pile_claim",
)


def _resolve_pending_choices(game: Game) -> None:
    """Answer every prompt the table is owed, with each kind's own default.

    The named kinds first and in their fixed order, which is what a seed
    reproduces. **Then everything else that is queued.** The list above was
    also the *whole* of what this answered, and the guard beside it only asks
    that the suspending kinds are on it — so a kind that holds priority without
    suspending was simply never answered, for the life of the game. Phantasmal
    Terrain's "As this Aura enters, choose a basic land type"
    (``land_type_choice``) sat queued 26 times in a ten-game Invasion run; the
    Aura was on the battlefield and changed no land. The web layer's AI seat
    has never had this hole, because ``web/prompts.auto_resolve_ai_prompts`` is
    generic over the queue; this is now the same statement.

    It is also `Game.prompt_driver` for a simulated game — see
    `run_ai_simulation` — so the engine calls it between one stack object and
    the next rather than this module remembering to after each step.
    """
    game.auto_resolve_pending_choices(kinds=_SIMULATED_CHOICES)
    if game.pending_choices:
        game.auto_resolve_pending_choices()


class _SimulatedGame(Game):
    """A `Game` that counts what each step leaves owed as the next one begins.

    The honesty check for `SimulationReport.steps_left_owing`, and a subclass
    rather than a field on `Game` because it is the simulator's instrument: the
    engine has nothing to do with the answer. `_set_phase_and_step` is the line
    every way into a step already passes through, so the count cannot be
    walked around by a driver that orders its own calls differently — which is
    the failure it exists to see.

    Two things can be owed. A **prompt** the game is waiting on
    (`Game.waiting_prompt`: the kinds that hold priority, so a notification
    such as a revealed hand is not one), from any step. And an **object still
    on the stack**, from a step that has a priority window — the untap step has
    none (CR 502.4: a trigger from it waits for the upkeep) and neither,
    ordinarily, has cleanup (CR 514.3), so a stack carried out of those is the
    rules working.
    """

    def _set_phase_and_step(self, phase: str, step: str) -> None:
        leaving = self.current_step
        if leaving and leaving != step:
            self._steps_left_owing["_examined"] += 1
            for what in _owed_when_leaving(self, leaving):
                self._steps_left_owing[f"{leaving} -> {step}: {what}"] += 1
        super()._set_phase_and_step(phase, step)

    @property
    def _steps_left_owing(self) -> Counter[str]:
        return self.__dict__.setdefault("_w2g6_steps_left_owing", Counter())


def _owed_when_leaving(game: Game, leaving_step: str) -> list[str]:
    """What *leaving_step* is ending around — see `_SimulatedGame`."""
    owed: list[str] = []
    if game.pending_choices or game.pending_replacement_choices:
        waiting = game.waiting_prompt()
        if waiting is not None:
            source = waiting.data.get("card_name") or waiting.data.get("source_name")
            owed.append(f"{waiting.kind}" + (f" ({source})" if source else ""))
    if game.stack and game._receives_priority(leaving_step):
        owed.append(f"{game.stack[-1].card.name} on the stack")
    return owed


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
            # By the *whole* card's name (CR 709.2: it is one card): a split
            # card's spell is its half, under the half's name, and counting
            # that would read a suspended Assault as an Assault // Battery
            # vanishing and an "Assault" appearing. Every other zone holds the
            # whole card, so a half found *there* — a card that left the stack
            # without becoming whole again (CR 709.4) — is counted under the
            # half's name and is reported as exactly that leak.
            counter[whole_card(item.card).name] += 1
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

    # **Both life checks read the per-turn records, not the life total**, and
    # that is the second time this oracle has lied rather than the engine: the
    # cast is a window other permanents act in too. "Whenever a player casts a
    # red spell, you may pay {1}. If you do, you gain 1 life" (Iron Star) gained
    # the Bolt's target a life in the same window, so the total fell by 2 and
    # the check said the Bolt dealt 2 — LEB's and 2ED's default seeded runs
    # exited 1 on it, and Ivory Cup did the same to Healing Salve in 6ED's.
    # Damage dealt and life gained are counted separately by the engine
    # (`damage_taken_this_turn`, `life_gained_this_turn`), so each check reads
    # the one its card prints. The damage is still compared exactly — nothing
    # else in these pools deals damage to the Bolt's target as it is cast — and
    # the gain as a floor, because a cast trigger adding life on top is the
    # very thing that fooled it.
    if card.name == "Lightning Bolt":
        base_damage = 3
        if before_target.combat_damage_cap_one_charges > 0 and base_damage > 1:
            base_damage = 1
        expected_damage = max(0, base_damage - before_target.damage_prevention_pool)
        actual_damage = (
            after_target.damage_taken_this_turn - before_target.damage_taken_this_turn
        )
        if actual_damage != expected_damage:
            return "Lightning Bolt damage did not match prevention/cap effects"

    if card.name == "Ancestral Recall":
        hand_delta = len(after_target.hand) - len(before_target.hand)
        cast_offset = 1 if target_index == caster_index else 0
        drawn = hand_delta + cast_offset
        if drawn != min(3, len(before_target.library)):
            return "Ancestral Recall did not draw expected cards"

    if card.name == "Healing Salve":
        life_gain = after_target.life_gained_this_turn - before_target.life_gained_this_turn
        prevention_gain = after_target.damage_prevention_pool - before_target.damage_prevention_pool
        if life_gain < 3 and prevention_gain != 3:
            return "Healing Salve did not apply expected life-gain or prevention mode"
    # CR 205.2b: a card has **every** type its line names, so Ornithopter is an
    # artifact card *and* a creature card. Both checks below used
    # ``card.primary_type``, which picks one of them by the order of a list --
    # and the Disenchant one was therefore wrong for every artifact creature on
    # the board, which is the class ``search_filters.card_has_type`` exists to
    # end. It reported a **false** issue at Mercadian Masques' Phase 5: Toymaker
    # ("Artifact Creature -- Spellshaper") answers "creature" to
    # ``primary_type``, so the destroyed permanent was in neither count and the
    # total looked unchanged. The engine had destroyed exactly the right
    # permanent; only the honesty check was lying, in the direction that costs
    # an investigation rather than a game.
    #
    # Unsummon's twin was right **by accident** -- no land creature exists in
    # this pool, so "creature" is always ``primary_type``'s answer for one --
    # and it is routed through the same function anyway, so the next reader of
    # this pair does not have to work out which of the two was safe.
    if card.name == "Unsummon" and any(
        card_has_type(perm.card, "creature") for perm in before_target.battlefield
    ):
        creature_before = sum(
            1 for perm in before_target.battlefield if card_has_type(perm.card, "creature")
        )
        creature_after = sum(
            1 for perm in after_target.battlefield if card_has_type(perm.card, "creature")
        )
        if creature_after != creature_before - 1:
            return "Unsummon did not remove one target creature"

    def _artifact_or_enchantment(perm) -> bool:
        return card_has_type(perm.card, "artifact") or card_has_type(perm.card, "enchantment")

    if card.name == "Disenchant" and any(
        _artifact_or_enchantment(perm) for perm in before_target.battlefield
    ):
        ae_before = sum(1 for perm in before_target.battlefield if _artifact_or_enchantment(perm))
        ae_after = sum(1 for perm in after_target.battlefield if _artifact_or_enchantment(perm))
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
        # What `_assert_expected` reads instead of the life total — see there.
        damage_taken_this_turn=player.damage_taken_this_turn,
        life_gained_this_turn=player.life_gained_this_turn,
    )


def _snap(game: Game) -> tuple[PlayerState, PlayerState]:
    return (_clone_player(game, game.players[0]), _clone_player(game, game.players[1]))


def _execute_foreign_activation(
    game: Game, active: int, action, report: SimulationReport,
    game_index: int, turn: int,
) -> None:
    """Carry out `ai_policy.choose_foreign_activation_action`'s choice.

    The activator pays (CR 602.1a) from its own lands, so the taps are on
    *active*'s board; the permanent is on ``action.source_controller_index``'s,
    which is what ``activate_permanent_ability`` counts ``permanent_index``
    into when it is given that seat.
    """
    tap_planned_lands(game, active, action)
    result = game.activate_permanent_ability(
        active,
        action.permanent_name,
        target_player_index=action.target_player_index,
        permanent_index=action.permanent_index,
        target_permanent_index=action.target_permanent_index,
        target_role_refs=action.target_role_refs,
        ability_index=action.ability_index,
        source_controller_index=action.source_controller_index,
    )
    _resolve_pending_choices(game)
    report.interaction_count += 1
    report.foreign_activations += 1
    owner = game.players[action.source_controller_index].name
    report.log_lines.append(
        f"G{game_index} T{turn} {game.players[active].name} "
        f"activate {owner}'s {action.permanent_name} -> {result.details}"
    )
    if not result.supported:
        report.refused_activations[
            f"{action.permanent_name} ({owner}'s): {result.details}"
        ] += 1


#: Bounds on the main phase's two repeated passes. A turn has one land drop
#: plus whatever an allowance adds (CR 305.2) — Fastbond's "any number" is
#: bounded by the hand, and this by a number no real hand reaches, so a land
#: that returns itself to hand on entering cannot loop. Casts are bounded by
#: the mana the seat has, and this by a number a turn's mana does not reach
#: in a limited deck, so a spell that untaps lands or returns itself cannot.
_MAX_LAND_DROPS = 8
_MAX_CASTS_PER_MAIN_PHASE = 8


def _play_land_drops(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """The turn's land drops (CR 305.1/305.2), before anything is cast.

    **Their own pass, and first**, because a land was the turn's one *cast*
    until PCY's wave 3: ``choose_cast_action`` scored a land 1.0 and every
    spell at least 1.5, so a seat that played a land cast nothing else that
    turn and a seat holding a spell kept its land in hand. That was invisible
    for as long as this simulator ignored mana costs — a spell cost nothing,
    so the land lost every comparison it should have won. How many drops the
    turn has is `Game._may_play_another_land`'s answer (asked inside
    `ai_policy.choose_land_drop`), the one every land-drop gate asks, so an
    additional-land effect gives the seat its extra plays here too.

    A refused play is counted with the refused casts and ends the pass: the
    chooser asks the cast path's own gates, so a refusal is a policy bug to
    surface rather than a land to retry.
    """
    seat_name = game.players[active].name
    for _ in range(_MAX_LAND_DROPS):
        if game.is_game_over():
            return
        action = choose_land_drop(game, active)
        if action is None:
            return
        land = game.players[active].hand[action.hand_index]
        result = game.cast_from_hand(
            active, land.name, target_player_index=action.target_player_index,
        )
        _resolve_pending_choices(game)
        report.log_lines.append(
            f"G{game_index} T{turn} {seat_name} play {land.name} -> {result.details}"
        )
        if not result.supported:
            report.refused_casts[f"{land.name}: {result.details}"] += 1
            return
        report.lands_played += 1


def _play_one_cast(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> bool:
    """Cast what `ai_policy.choose_cast_action` proposes, paying for it.

    True when a spell was cast and accepted, so the caller may ask for another;
    False when nothing was proposed or the cast was refused — a refusal is not
    retried, because the policy would propose the same card again.
    """
    active_player = game.players[active]
    cast_action = choose_cast_action(game, active)
    if cast_action is None:
        return False
    # `hand_index` indexes the zone `from_zone` names. The simulator's games
    # are ordinary duels, so today this is always the hand — but the executor
    # reads the field rather than assuming it, or a commander game run through
    # here would cast the wrong card.
    cast_zone = (
        active_player.command_zone
        if cast_action.from_zone == "command"
        else active_player.hand
    )
    # The spell, not the zone's card: a split card is cast as the half the
    # policy scored (CR 709.3), and every line below — the cast, the log, the
    # support check, the effect audit — is about that half.
    card_to_cast = spell_being_cast(cast_zone, cast_action)

    # The payment: the planned lands tapped into the pool, each for the colour
    # the plan counted on (`ai_policy.tap_planned_lands`, the web AI seat's
    # executor too); the cast below spends it.
    tap_planned_lands(game, active, cast_action)

    before = _snap(game)
    # Forward the *whole* choice. Dropping the permanent target was invisible
    # while the decklist was eight cards that target a player or nothing: an
    # Aura reaches `cast_from_hand` with no index and is refused ("Evil
    # Presence requires a target", CR 601.2c/115.1b), and the AI had already
    # picked a legal land for it.
    result = game.cast_from_hand(
        active,
        card_to_cast.name,
        target_player_index=cast_action.target_player_index,
        target_permanent_index=cast_action.target_permanent_index,
        target_permanent_ids=cast_action.target_permanent_ids,
        x_value=cast_action.x_value,
        from_zone=cast_action.from_zone,
        # CR 118.9. Forwarded like every other announcement on the action:
        # dropped here, the cast would fall back to a mana cost the policy has
        # already established this seat cannot pay, and be refused.
        alternative_cost=cast_action.alternative_cost,
        # CR 601.2d, forwarded for exactly that reason: the division is part of
        # the announcement, and a cast that drops it is refused now that the
        # gate asks for one.
        divided_targets=cast_action.divided_targets,
        # CR 601.2b's optional costs (a kicker), forwarded for the same reason:
        # the plan above tapped the lands for them, and a cast that drops the
        # announcement pays the printed cost and leaves the rest in the pool.
        optional_cost_payments=cast_action.optional_cost_payments,
    )
    _resolve_pending_choices(game)
    after = _snap(game)
    report.interaction_count += 1
    report.log_lines.append(
        f"G{game_index} T{turn} {active_player.name} cast {card_to_cast.name} -> {result.details}"
    )
    if not result.supported:
        # Two different things wore one message. `supported` on a cast result
        # means "the cast went through", so a spell declined for want of a
        # legal target, for a printed timing clause or by City in a Bottle was
        # reported as an *unsupported card* — which the pool has none of. Ask
        # the compiler, which is what that word actually means.
        if not compile_card_oracle(card_to_cast).supported:
            report.issues.append(InteractionIssue(
                game_index, turn,
                f"Unsupported card cast in simulation: {card_to_cast.name}",
            ))
        else:
            report.refused_casts[f"{card_to_cast.name}: {result.details}"] += 1
        # The oracle below is about what a spell *did*, and a refused one did
        # nothing — asked anyway, it reported a refused Unsummon as "did not
        # remove one target creature", an issue out of a cast that broke no
        # rule. Unreachable while every cast was free; one refusal for want of
        # mana made it a false exit 1 (5ED's run, once costs were enforced).
        return False
    expectation_error = _assert_expected(
        card_to_cast, before, after, active, cast_action.target_player_index,
    )
    if expectation_error:
        report.issues.append(InteractionIssue(game_index, turn, expectation_error))
    return True


def _play_casts(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """Cast spells until the seat proposes nothing it can pay for.

    **More than one**, now that each one is paid for: a cast was the turn's one
    action while mana was free, which cost nothing to model and was no less
    true than the free mana itself. With costs enforced, one spell per turn is
    a seat that taps two of its six lands and passes holding a hand of
    two-drops — and the deck builder deals the cheapest spells it can, so that
    was most turns of most games. Each cast plans against the lands the last
    one left untapped, so the loop ends when the mana does.

    The land-drop pass is asked again after every cast, because a spell can
    grant a drop the turn did not have when the pass first ran ("You may play
    any number of lands on each of your turns", Fastbond; Summer Bloom) — and
    a drop left there was taken by the cast chooser instead, as a "cast", which
    is the land-as-the-turn's-action shape this pass exists to end.
    """
    for _ in range(_MAX_CASTS_PER_MAIN_PHASE):
        if game.is_game_over():
            return
        if not _play_one_cast(game, active, report, game_index, turn):
            return
        _play_land_drops(game, active, report, game_index, turn)


def _play_activations(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """One ability on the seat's own battlefield, one from its hand and one on
    another seat's battlefield, each planned against the lands the casts left
    untapped and paid for the same way."""
    active_player = game.players[active]
    activation_action = None if game.is_game_over() else choose_activation_action(game, active)
    if activation_action is not None:
        tap_planned_lands(game, active, activation_action)
        result = game.activate_permanent_ability(
            active,
            activation_action.permanent_name,
            target_player_index=activation_action.target_player_index,
            permanent_index=activation_action.permanent_index,
            target_permanent_index=activation_action.target_permanent_index,
            target_role_refs=activation_action.target_role_refs,
        )
        _resolve_pending_choices(game)
        report.interaction_count += 1
        report.log_lines.append(
            f"G{game_index} T{turn} {active_player.name} "
            f"activate {activation_action.permanent_name} -> {result.details}"
        )
        if not result.supported:
            report.refused_activations[
                f"{activation_action.permanent_name}: {result.details}"
            ] += 1

    # An ability activated from the seat's **hand** (CR 113.6j) — cycling. A
    # separate pass rather than a branch above, because `activate_from_hand`
    # takes neither a permanent nor a target; after the battlefield pass, so
    # the lands it plans against are the ones nothing else wanted.
    hand_activation = (
        None if game.is_game_over()
        else choose_hand_activation_action(game, active)
    )
    if hand_activation is not None:
        tap_planned_lands(game, active, hand_activation)
        result = game.activate_from_hand(
            active,
            hand_activation.card_name,
            ability_index=hand_activation.ability_index,
            hand_index=hand_activation.hand_index,
        )
        _resolve_pending_choices(game)
        report.interaction_count += 1
        report.log_lines.append(
            f"G{game_index} T{turn} {active_player.name} "
            f"activate {hand_activation.card_name} from hand "
            f"-> {result.details}"
        )
        if not result.supported:
            report.refused_activations[
                f"{hand_activation.card_name} (from hand): {result.details}"
            ] += 1

    # An ability on a permanent **another seat controls** that this seat may
    # activate (CR 602.1b, "Any player may activate this ability"). Last of the
    # main-phase passes, so it spends only mana nothing of the seat's own
    # wanted. No simulated seat had ever done this: every chooser walked its
    # own board.
    foreign_activation = (
        None if game.is_game_over()
        else choose_foreign_activation_action(game, active)
    )
    if foreign_activation is not None:
        _execute_foreign_activation(
            game, active, foreign_activation, report, game_index, turn,
        )


def _play_combat_phase(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """One combat phase through `ai_combat.run_ai_combat_phase`, recorded.

    A function rather than the inline block it was, because a turn can now
    reach a combat phase from two places: the turn's own, and one CR 500.8 adds
    after the postcombat main phase (Relentless Assault), which the ending-phase
    walk below enters through the turn's plan.
    """
    combat = run_ai_combat_phase(game, active)
    report.attacks_declared += combat.attacks_declared
    report.attackers_declared += combat.attackers
    report.blockers_declared += combat.blockers
    report.manual_damage_splits += combat.manual_damage_splits
    for seat_name, why in combat.refused_attacks:
        report.refused_attacks[f"{seat_name}: {why}"] += 1
    for seat_name, why in combat.silent_attacks:
        report.issues.append(InteractionIssue(
            game_index, turn,
            f"{seat_name} attacked with nobody: even the "
            f"every-legal-attacker fallback was refused ({why})",
        ))
    for seat_name, why in combat.refused_blocks:
        report.refused_blocks[f"{seat_name}: {why}"] += 1
    for seat_name, why in combat.silent_blocks:
        report.issues.append(InteractionIssue(
            game_index, turn,
            f"{seat_name} blocked with nobody: even the empty "
            f"declaration was refused ({why})",
        ))
    _resolve_pending_choices(game)


#: Bounds on the two loops below. Generous: a turn has five phases plus
#: whatever CR 500.8 adds, and a step's stack is drained in one pass unless a
#: drained choice put something new on it.
_MAX_REMAINING_PHASES = 12
_MAX_DRAIN_PASSES = 8


def _drain_step(game: Game) -> None:
    """Resolve a step's stack and the prompts it armed, until neither moves.

    `_resolve_priority_window` stops at an object whose resolution is held for
    an answer (CR 608.2) and the simulator answers afterwards, so one pass can
    leave the rest of the step's triggers waiting behind the one that asked.
    In a main phase the cast that follows drains them; nothing follows an end
    step but cleanup, so they would otherwise resolve a turn late, in the next
    turn's upkeep.
    """
    for _ in range(_MAX_DRAIN_PASSES):
        game._resolve_priority_window()
        _resolve_pending_choices(game)
        if not game.stack:
            return


def _play_rest_of_turn(
    game: Game, active: int, report: SimulationReport, game_index: int, turn: int
) -> None:
    """Everything after the turn's first combat phase: the postcombat main
    phase, any phase CR 500.8 added, and the ending phase (CR 512-514).

    The **fourth** omission of the "it plays a whole turn" class, after
    `begin_turn_bookkeeping`, the precombat main phase and combat, and it
    failed the way all three did: the run completed, the interaction count was
    non-zero and the issue list was empty. What was missing was every end of
    every turn. W1G1 counted ``resolve_end_step`` = 0 and
    ``resolve_cleanup_step`` = 0 over three LEA games; W1G2 watched a Snag cast
    on turn 4 still preventing damage on turn 18. Every "until end of turn"
    effect in every simulated game was permanent, marked damage accumulated
    across turns, no end-step trigger ever fired and no hand was ever
    discarded down to its maximum.

    **The walk is the engine's, not this function's.** Which phase comes next
    is `Game.enter_next_turn_phase`, the seam the web layer's phase rail goes
    through — so an extra combat phase (Relentless Assault) is entered and
    fought rather than skipped, and the ending phase is entered by the same
    call that would enter anything else. What this function supplies is only
    what the engine waits for a *player* to do: close a main phase nobody is
    casting in, fight a combat phase, and walk the end step's priority window
    to cleanup, which is the web layer's ``step == "end"`` branch
    (``close_end_step`` then ``resolve_cleanup_step``) for a seat nobody asks.

    Cleanup's discard is the engine's own non-interactive default, the same
    one an AI seat gets in the web app (``defer_discard_selection`` is only
    ever set for a human), so a simulated game and an unattended web game
    discard the same cards.
    """
    for _ in range(_MAX_REMAINING_PHASES):
        if game.is_game_over():
            return
        phase = game.current_turn_phase
        if phase == "ending":
            break
        if phase == "combat":
            # Still inside a combat phase the driver could not finish: a prompt
            # it does not answer is outstanding, or a resolution is suspended.
            # `run_ai_combat_phase` left the phase where it stood rather than
            # forcing it, and so does this — the turn ends unfinished, as every
            # turn did before this function existed, rather than re-entering a
            # combat that has already declared.
            return
        # A main phase. The simulator casts in the precombat one only, so this
        # is the postcombat one or an extra one: nothing is done in it, its
        # priority window (and any "each of your main phases" trigger the entry
        # announced) is drained, and the turn's plan says what follows.
        game._close_current_priority_step()
        _resolve_pending_choices(game)
        entered = game.enter_next_turn_phase(phase)
        if entered is None:
            return
        if entered == "combat":
            # CR 500.8's "additional combat phase" (Relentless Assault),
            # entered by the plan and fought like the turn's own.
            _play_combat_phase(game, active, report, game_index, turn)
    else:
        return

    if game.is_game_over():
        return
    # CR 513: `enter_turn_phase("ending")` ran `resolve_end_step`, which put the
    # "at the beginning of the end step" triggers on the stack and opened the
    # active player's priority window. Both players pass (the simulator holds
    # no instant-speed play), so the window is the stack draining.
    _drain_step(game)
    report.end_steps += 1
    if game.is_game_over():
        return
    game.close_end_step()
    # CR 514: discard to hand size, then CR 514.2's "until end of turn" ends
    # and damage is removed.
    hand_before = len(game.players[active].hand)
    game.resolve_cleanup_step(active)
    _drain_step(game)
    report.cleanup_steps += 1
    report.cleanup_discards += max(0, hand_before - len(game.players[active].hand))


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
        # CR 601.2f-h and 602.2b: a spell or an ability is paid for. This read
        # `Game(players=[p1, p2])`, and `enforce_mana_costs` defaults to False,
        # so in every simulated game this project ever ran nothing cost
        # anything: a seat cast a six-drop on its first turn with no land, and
        # the land drop was the turn's one action rather than the thing that
        # pays for the rest (W2G3's census: 32 of LEA's 82 nonland casts, 62
        # of M21's 78 and 75 of TMP's 94 cost more than the caster's lands).
        # The fifth omission of the "it plays a whole turn" class, and the
        # same shape: the run completed, the interaction count was non-zero
        # and the issue list was empty. The web app's games have always
        # enforced costs (`web/session_store.py`); now these do too, and the
        # AI pays through the same seam its web seat does — the policy plans
        # the taps, `tap_planned_lands` fills the pool, the cast spends it.
        #
        # `prompt_driver` is the sixth, and the reason is in
        # `SimulationReport.steps_left_owing`: the engine asks for this table's
        # answers where it is owed them, instead of this loop draining the
        # queue wherever it happens to stand.
        game = _SimulatedGame(
            players=[p1, p2], enforce_mana_costs=True,
            prompt_driver=_resolve_pending_choices,
        )
        starting_player = game.select_starting_player()
        game.deal_opening_hands(starting_player)
        for i in range(len(game.players)):
            game.keep_hand(i)

        initial_cards = _zone_counter(game)
        log_cursor = 0
        report.log_lines.append(f"=== Game {game_index} ===")

        # `game.turn` starts at 1 and `start_next_turn` increments it before
        # each turn, so it is reset to 0 for the first increment to land on 1.
        game.turn = 0
        # Seat 0 takes the first turn, as it always has here. The engine works
        # out whose turn is next from whose turn it was (CR 500.7 keeps the
        # rotation's place across extra turns), so the seat "before" the first
        # one is the last.
        game.active_player_index = len(game.players) - 1

        # *max_turns* is rounds, as it always was: two turns each. An extra
        # turn is one of them, so a game with Time Walk in it still ends.
        for half_turn in range(2 * max_turns):
            turn = half_turn // 2 + 1
            # **Whose turn comes next is `Game.start_next_turn`'s answer.**
            # This read ``for active in (0, 1)``, the last piece of the turn
            # structure the loop still decided for itself, and so no simulated
            # game had ever taken an extra turn or skipped one: Time Walk put
            # its turn on `extra_turn_queue` and the loop walked past it. Nine
            # shipped cards add or skip a turn.
            #
            # It is also the beginning phase and the entry into the main
            # phase — `Game.start_turn`, the engine's own walk, called rather
            # than copied. See the notes below.
            active = game.start_next_turn()
            report.extra_turns_taken += bool(game.current_turn_is_extra)
            active_player = game.players[active]
            opponent = game.players[1 - active]

            # This loop open-coded all of that, and each piece left out was
            # invisible in the same way: the run completes, the interaction
            # count is non-zero and the issue list is empty.
            #
            # * `begin_turn_bookkeeping` was missing first, which froze
            #   every per-seat-turn record in every AI game:
            #   `seat_turn_counts` is written in exactly one place, so
            #   Wiitigo's "since your last upkeep" read False forever,
            #   Giant Turtle, Goblin Rock Sled and Tangle Kelp never saw
            #   "attacked during your last turn", and Wall of Dust and
            #   Oracle en-Vec never saw "during its controller's next
            #   turn". Found by W1G2 while building echo.
            # * Then the main-phase *entry* (CR 505): the loop went
            #   draw -> cast, so no `main_phase_first` /
            #   `main_phase_each_yours` trigger had ever fired in an AI
            #   game — Sanctum of Fruitful Harvest, Eladamri's Vineyard,
            #   Carpet of Flowers.
            # * And the sixth of the class is not a missing call at all:
            #   upkeep then draw, with the *answer* to what the upkeep
            #   asked taken after both. See
            #   `SimulationReport.steps_left_owing`; the fix is the
            #   `prompt_driver` this game was built with, so each of these
            #   steps answers its own prompts inside its own priority
            #   window, in the engine's order rather than this loop's.
            #
            # What follows the beginning phase is the turn plan's answer
            # (`enter_next_turn_phase`, inside `start_turn`), not a phase
            # named here.
            #
            # The drain is the half `_close_or_defer_step` does for every
            # other step and `_enter_main_phase` does not, because a main
            # phase is not closed before the active player acts in it: the
            # entry opens a priority window, and the triggers it announced
            # have to resolve before the cast below sees the board.
            game._resolve_priority_window()
            _resolve_pending_choices(game)

            # The main phase's passes, in the order a player takes them:
            # the land drop, then casts paid for out of the lands, then
            # the activations, each planned against what is still
            # untapped. See `_play_land_drops` and `_play_casts`.
            _play_land_drops(game, active, report, game_index, turn)
            _play_casts(game, active, report, game_index, turn)
            _play_activations(game, active, report, game_index, turn)

            # CR 506-511, the half of a turn this loop did not have. It went
            # main phase -> cast -> activate -> next seat, so no simulated
            # game had ever declared an attacker, declared a block or run a
            # combat damage step — which is why `refused_attacks` below could
            # not have been measured before, and why "run the sim" was never
            # an end-to-end check for combat work however green it came back.
            #
            # The same shape as the two omissions above it and found the same
            # way: the run completes, the interaction count is non-zero and
            # the issue list is empty, so nothing fails. What is absent is
            # every creature that ever attacked, and the only proof is to
            # count the log lines that are not there.
            #
            # Driven through `engine/ai_combat.py`, which the web layer's AI
            # attack declaration also goes through — a refused declaration is
            # silent, and a second copy of that fallback chain would be a
            # second place for the silence to live.
            if not game.is_game_over():
                _play_combat_phase(game, active, report, game_index, turn)

            # CR 512-514, the half of a turn this loop still did not have
            # after combat arrived: the postcombat main phase, anything
            # CR 500.8 added, and the ending phase. See `_play_rest_of_turn`.
            if not game.is_game_over():
                _play_rest_of_turn(game, active, report, game_index, turn)

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

        owing = Counter(game._steps_left_owing)
        report.step_changes += owing.pop("_examined", 0)
        report.steps_left_owing.update(owing)
        report.games_completed += 1
        report.log_lines.append(
            f"RESULT G{game_index}: {game.players[0].name}={game.players[0].life}, {game.players[1].name}={game.players[1].life}"
        )
        report.log_lines.append("")

    return report