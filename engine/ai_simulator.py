from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import random

from .ai_policy import choose_activation_action, choose_cast_action, choose_search_library_index
from .card_loader import load_cards
from .game import Game
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

    @property
    def ok(self) -> bool:
        return not self.issues


def _resolve_pending_search(game: Game) -> None:
    pending = game.pending_search_library
    if pending is None:
        return
    choice = choose_search_library_index(game, pending["caster_index"], card_type=pending.get("card_type", "any"))
    if choice is None:
        random.shuffle(game.players[pending["caster_index"]].library)
        game.pending_search_library = None
    else:
        game.confirm_search_library(pending["caster_index"], choice)


def _find(cards: dict[str, CardDefinition], name: str) -> CardDefinition:
    if name not in cards:
        raise ValueError(f"Missing required card in LEA data: {name}")
    return cards[name]


def _build_deck(cards: dict[str, CardDefinition], seed: int) -> list[CardDefinition]:
    names = [
        "Island",
        "Island",
        "Island",
        "Island",
        "Island",
        "Island",
        "Island",
        "Island",
        "Mountain",
        "Mountain",
        "Mountain",
        "Mountain",
        "Mountain",
        "Mountain",
        "Lightning Bolt",
        "Lightning Bolt",
        "Lightning Bolt",
        "Lightning Bolt",
        "Ancestral Recall",
        "Ancestral Recall",
        "Healing Salve",
        "Healing Salve",
        "Unsummon",
        "Unsummon",
        "Disenchant",
        "Disenchant",
        "Black Lotus",
        "Black Lotus",
        "Jayemdae Tome",
        "Jayemdae Tome",
        "Prodigal Sorcerer",
        "Prodigal Sorcerer",
        "Howling Mine",
        "Howling Mine",
        "Grizzly Bears",
        "Grizzly Bears",
    ]
    deck = [_find(cards, name) for name in names]
    random.Random(seed).shuffle(deck)
    return deck


def _zone_counter(player: PlayerState) -> Counter[str]:
    counter: Counter[str] = Counter()
    for card in player.library:
        counter[card.name] += 1
    for card in player.hand:
        counter[card.name] += 1
    for card in player.graveyard:
        counter[card.name] += 1
    for permanent in player.battlefield:
        # Ignore generated tokens in zone conservation checks.
        if permanent.card.name in {"Wasp"}:
            continue
        counter[permanent.card.name] += 1
    return counter


def _assert_expected(
    card: CardDefinition,
    before: tuple[PlayerState, PlayerState],
    after: tuple[PlayerState, PlayerState],
    caster_index: int,
    target_index: int,
) -> str | None:
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


def _clone_player(player: PlayerState) -> PlayerState:
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
            for perm in player.battlefield
        ],
        graveyard=list(player.graveyard),
        mana_pool=dict(player.mana_pool),
        damage_prevention_pool=player.damage_prevention_pool,
        combat_damage_cap_one_charges=player.combat_damage_cap_one_charges,
        has_no_max_hand_size=player.has_no_max_hand_size,
        can_spend_white_as_red=player.can_spend_white_as_red,
    )


def _snap(game: Game) -> tuple[PlayerState, PlayerState]:
    return (_clone_player(game.players[0]), _clone_player(game.players[1]))


def run_ai_simulation(cards_path: Path, games: int = 10, seed: int = 1337, max_turns: int = 18) -> SimulationReport:
    cards = {card.name: card for card in load_cards(cards_path)}
    report = SimulationReport(games_requested=games, games_completed=0, interaction_count=0)
    rng = random.Random(seed)
    # The engine's coin flips, opening-hand shuffles, and random effects use the
    # module-level RNG. Seed it so the simulation is fully reproducible — the
    # deck-construction rng above only covers deck ordering.
    random.seed(seed)

    for game_index in range(1, games + 1):
        p1 = PlayerState(name=f"AI-A-{game_index}", library=_build_deck(cards, rng.randint(1, 1_000_000)))
        p2 = PlayerState(name=f"AI-B-{game_index}", library=_build_deck(cards, rng.randint(1, 1_000_000)))
        game = Game(players=[p1, p2])
        starting_player = game.select_starting_player()
        game.deal_opening_hands(starting_player)
        for i in range(len(game.players)):
            game.keep_hand(i)

        initial_counters = [_zone_counter(p1), _zone_counter(p2)]
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
                    result = game.cast_from_hand(
                        active,
                        card_to_cast.name,
                        target_player_index=cast_action.target_player_index,
                        x_value=cast_action.x_value,
                    )
                    _resolve_pending_search(game)
                    after = _snap(game)
                    report.interaction_count += 1
                    report.log_lines.append(
                        f"G{game_index} T{turn} {active_player.name} cast {card_to_cast.name} -> {result.details}"
                    )
                    if not result.supported:
                        report.issues.append(
                            InteractionIssue(game_index, turn, f"Unsupported card cast in simulation: {card_to_cast.name}")
                        )
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
                    )
                    _resolve_pending_search(game)
                    report.interaction_count += 1
                    report.log_lines.append(
                        f"G{game_index} T{turn} {active_player.name} "
                        f"activate {activation_action.permanent_name} -> {result.details}"
                    )

                new_logs = game.log[log_cursor:]
                report.log_lines.extend(f"  {line}" for line in new_logs)
                log_cursor = len(game.log)

                for idx, player in enumerate(game.players):
                    if _zone_counter(player) != initial_counters[idx]:
                        report.issues.append(
                            InteractionIssue(game_index, turn, f"Zone conservation failed for {player.name}")
                        )

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