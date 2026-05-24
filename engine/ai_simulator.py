from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import random

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


def _choose_target_index(card_name: str, caster_index: int) -> int:
    if card_name in {"Ancestral Recall", "Healing Salve"}:
        return caster_index
    return 1 - caster_index


def _can_cast(game: Game, caster_index: int, card: CardDefinition) -> bool:
    opponent = game.players[1 - caster_index]
    if card.name == "Unsummon":
        return any(perm.card.primary_type == "creature" for perm in opponent.battlefield)
    if card.name == "Disenchant":
        return any(perm.card.primary_type in {"artifact", "enchantment"} for perm in opponent.battlefield)
    return True


def _pick_castable(game: Game, player_index: int) -> CardDefinition | None:
    player = game.players[player_index]
    nonlands = [card for card in player.hand if card.primary_type != "land"]
    lands = [card for card in player.hand if card.primary_type == "land"]

    for card in nonlands:
        if _can_cast(game, player_index, card):
            return card
    if lands:
        return lands[0]
    return None


def _activate_if_available(game: Game, player_index: int, turn_log: list[str]) -> int:
    player = game.players[player_index]
    activated = 0
    for permanent in player.battlefield:
        if permanent.tapped:
            continue
        if permanent.card.name == "Prodigal Sorcerer":
            result = game.activate_permanent_ability(player_index, permanent.card.name, target_player_index=1 - player_index)
            turn_log.append(f"activate {permanent.card.name} -> {result.details}")
            return 1
        if permanent.card.name == "Jayemdae Tome" and player.library:
            result = game.activate_permanent_ability(player_index, permanent.card.name, target_player_index=player_index)
            turn_log.append(f"activate {permanent.card.name} -> {result.details}")
            return 1
        if permanent.card.name == "Black Lotus":
            result = game.activate_permanent_ability(player_index, permanent.card.name, target_player_index=player_index)
            turn_log.append(f"activate {permanent.card.name} -> {result.details}")
            return 1
    return activated


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

    for game_index in range(1, games + 1):
        p1 = PlayerState(name=f"AI-A-{game_index}", library=_build_deck(cards, rng.randint(1, 1_000_000)))
        p2 = PlayerState(name=f"AI-B-{game_index}", library=_build_deck(cards, rng.randint(1, 1_000_000)))
        p1.draw(7)
        p2.draw(7)
        game = Game(players=[p1, p2])

        initial_counters = [_zone_counter(p1), _zone_counter(p2)]
        log_cursor = 0
        report.log_lines.append(f"=== Game {game_index} ===")

        for turn in range(1, max_turns + 1):
            for active in (0, 1):
                active_player = game.players[active]
                opponent = game.players[1 - active]

                game.resolve_untap_step(active)
                game.resolve_upkeep(active)
                game.resolve_draw_step(active)

                card_to_cast = _pick_castable(game, active)
                if card_to_cast is not None:
                    target_index = _choose_target_index(card_to_cast.name, active)
                    before = _snap(game)
                    result = game.cast_from_hand(active, card_to_cast.name, target_player_index=target_index)
                    after = _snap(game)
                    report.interaction_count += 1
                    report.log_lines.append(
                        f"G{game_index} T{turn} {active_player.name} cast {card_to_cast.name} -> {result.details}"
                    )
                    if not result.supported:
                        report.issues.append(
                            InteractionIssue(game_index, turn, f"Unsupported card cast in simulation: {card_to_cast.name}")
                        )
                    expectation_error = _assert_expected(card_to_cast, before, after, active, target_index)
                    if expectation_error:
                        report.issues.append(InteractionIssue(game_index, turn, expectation_error))

                turn_log: list[str] = []
                _activate_if_available(game, active, turn_log)
                for entry in turn_log:
                    report.interaction_count += 1
                    report.log_lines.append(f"G{game_index} T{turn} {active_player.name} {entry}")

                new_logs = game.log[log_cursor:]
                report.log_lines.extend(f"  {line}" for line in new_logs)
                log_cursor = len(game.log)

                for idx, player in enumerate(game.players):
                    if _zone_counter(player) != initial_counters[idx]:
                        report.issues.append(
                            InteractionIssue(game_index, turn, f"Zone conservation failed for {player.name}")
                        )

                if active_player.life <= 0 or opponent.life <= 0:
                    break

            if game.players[0].life <= 0 or game.players[1].life <= 0:
                break

        report.games_completed += 1
        report.log_lines.append(
            f"RESULT G{game_index}: {game.players[0].name}={game.players[0].life}, {game.players[1].name}={game.players[1].life}"
        )
        report.log_lines.append("")

    return report