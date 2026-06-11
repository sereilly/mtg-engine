from __future__ import annotations

from dataclasses import dataclass
import re

from .game import Game
from .mixins.stack_casting import aura_enchant_noun, permanent_matches_enchant_noun
from .models import CardDefinition, Permanent, PlayerState
from .oracle import OracleInstruction, compile_card_oracle

_MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")


@dataclass(frozen=True)
class CastAction:
    card_name: str
    target_player_index: int
    x_value: int | None
    land_tap_indices: tuple[int, ...]
    score: float
    hand_index: int
    target_permanent_index: int | None = None


@dataclass(frozen=True)
class ActivationAction:
    permanent_name: str
    permanent_index: int
    target_player_index: int
    land_tap_indices: tuple[int, ...]
    score: float


def choose_cast_action(game: Game, player_index: int) -> CastAction | None:
    player = game.players[player_index]
    opponent = game.players[1 - player_index]

    best: CastAction | None = None
    for hand_index, card in enumerate(player.hand):
        if (
            card.primary_type == "land"
            and game.enforce_mana_costs
            and game.lands_played_this_turn.get(player_index, 0) >= 1
            and game._fastbond_count(player_index) <= 0
        ):
            continue
        if not _can_cast_with_targets(game, player_index, card):
            continue

        target = _choose_target_for_spell(card, player_index, game)
        target_permanent_index: int | None = None
        if aura_enchant_noun(card) is not None:
            aura_choice = _choose_aura_target(game, player_index, card)
            if aura_choice is None:
                continue  # Aura spells require a legal target (Rule 115.1b)
            target, target_permanent_index = aura_choice
        x_value = _pick_x_value(game, player, card)
        if x_value == 0:
            continue
        tap_indices: tuple[int, ...] = ()

        if game.enforce_mana_costs and card.primary_type != "land":
            required = game._parse_mana_cost(card.mana_cost, x_value=x_value, extra_generic=_extra_generic_tax(game, card))
            plan = _plan_taps_for_cost(player, required)
            if plan is None:
                continue
            tap_indices = tuple(plan)

        score = _score_cast(game, player_index, card, target, x_value)
        candidate = CastAction(
            card_name=card.name,
            target_player_index=target,
            x_value=x_value,
            land_tap_indices=tap_indices,
            score=score,
            hand_index=hand_index,
            target_permanent_index=target_permanent_index,
        )
        if _is_better_cast(candidate, best):
            best = candidate

    return best


def choose_activation_action(game: Game, player_index: int) -> ActivationAction | None:
    player = game.players[player_index]

    best: ActivationAction | None = None
    for permanent_index, permanent in enumerate(player.battlefield):
        if permanent.tapped or permanent.card.primary_type == "land":
            continue
        if game._is_summoning_sick(permanent):
            continue

        program = compile_card_oracle(permanent.card)
        ability = next((item for item in program.activated_abilities if item.supported and item.instruction is not None), None)
        if ability is None or ability.instruction is None:
            continue

        if ability.instruction.kind in {"add_mana", "black_lotus_add_mana"}:
            continue

        target = _choose_target_for_instruction(ability.instruction, player_index, game)
        if ability.instruction.kind == "grant_banding_to_target":
            target_creatures = [perm for perm in game.players[target].battlefield if perm.card.primary_type == "creature"]
            if not target_creatures:
                continue

        land_taps: tuple[int, ...] = ()
        required = dict(ability.cost.mana)
        if game.enforce_mana_costs and any(required.values()):
            plan = _plan_taps_for_cost(player, required)
            if plan is None:
                continue
            land_taps = tuple(plan)

        score = _score_activation(game, player_index, permanent, ability.instruction, target)
        if score <= 0.0:
            continue
        candidate = ActivationAction(
            permanent_name=permanent.card.name,
            permanent_index=permanent_index,
            target_player_index=target,
            land_tap_indices=land_taps,
            score=score,
        )
        if best is None or candidate.score > best.score:
            best = candidate

    return best


def choose_attackers(game: Game, attacking_player_index: int) -> list[int]:
    """Return indices of creatures that should attack this turn."""
    player = game.players[attacking_player_index]
    opponent_index = 1 - attacking_player_index
    opponent = game.players[opponent_index]

    legal_attackers = [
        idx
        for idx, perm in enumerate(player.battlefield)
        if perm.card.primary_type == "creature"
        and not perm.tapped
        and not game._is_summoning_sick(perm)
        and game.can_attack(perm, opponent_index)
    ]
    if not legal_attackers:
        return []

    opponent_blockers = [
        perm
        for perm in opponent.battlefield
        if perm.card.primary_type == "creature" and not perm.tapped
    ]
    if not opponent_blockers:
        return legal_attackers

    chosen = []
    for idx in legal_attackers:
        attacker = player.battlefield[idx]
        best_defender_score = max(
            _score_block_pair(blocker, attacker) for blocker in opponent_blockers
        )
        # Attack when the best possible block is not clearly profitable for the opponent.
        if best_defender_score <= _permanent_value(attacker):
            chosen.append(idx)

    # Go all-in when lethal is on the table.
    if sum(player.battlefield[i].effective_power for i in legal_attackers) >= opponent.life:
        return legal_attackers

    return chosen


def choose_combat_blockers(game: Game, defending_player_index: int) -> dict[int, int]:
    combat = game.get_combat_state()
    if game.current_turn_phase != "combat" or game.current_step != "declare_blockers":
        return {}
    if combat.get("defending_player_index") != defending_player_index:
        return {}

    active_index = game.active_player_index
    attackers = [int(item["attacker_index"]) for item in combat.get("attackers", [])]
    if not attackers:
        return {}

    defender = game.players[defending_player_index]
    attacker_player = game.players[active_index]

    available_blockers = [
        idx
        for idx, blocker in enumerate(defender.battlefield)
        if blocker.card.primary_type == "creature" and not blocker.tapped
    ]
    if not available_blockers:
        return {}

    legal_pairs: list[tuple[int, int, float]] = []
    for blocker_idx in available_blockers:
        blocker = defender.battlefield[blocker_idx]
        for attacker_idx in attackers:
            if attacker_idx < 0 or attacker_idx >= len(attacker_player.battlefield):
                continue
            attacker = attacker_player.battlefield[attacker_idx]
            if not game._can_block_attacker(blocker, attacker):
                continue
            legal_pairs.append((blocker_idx, attacker_idx, _score_block_pair(blocker, attacker)))

    if not legal_pairs:
        return {}

    assignments: dict[int, int] = {}
    used_blockers: set[int] = set()

    # Priority 1: prevent lethal where possible.
    incoming = _estimated_incoming_player_damage(game, defending_player_index)
    life = defender.life
    if incoming >= life:
        for blocker_idx, attacker_idx, _ in sorted(legal_pairs, key=lambda item: _estimated_damage_prevented(game, defending_player_index, item[1], item[0]), reverse=True):
            if blocker_idx in used_blockers:
                continue
            prevented = _estimated_damage_prevented(game, defending_player_index, attacker_idx, blocker_idx)
            if prevented <= 0:
                continue
            assignments[blocker_idx] = attacker_idx
            used_blockers.add(blocker_idx)
            incoming -= prevented
            if incoming < life:
                break

    # Priority 2: maximize favorable trades.
    for blocker_idx, attacker_idx, _ in sorted(legal_pairs, key=lambda item: item[2], reverse=True):
        if blocker_idx in used_blockers:
            continue
        if blocker_idx in assignments:
            continue
        assignments[blocker_idx] = attacker_idx
        used_blockers.add(blocker_idx)

    return assignments


def choose_combat_instant_cast_action(game: Game, player_index: int) -> CastAction | None:
    player = game.players[player_index]

    best: CastAction | None = None
    for hand_index, card in enumerate(player.hand):
        if card.primary_type != "instant":
            continue
        if not _can_cast_with_targets(game, player_index, card):
            continue

        target = _choose_target_for_spell(card, player_index, game)
        x_value = _pick_x_value(game, player, card)
        if x_value == 0:
            continue
        tap_indices: tuple[int, ...] = ()

        if game.enforce_mana_costs:
            required = game._parse_mana_cost(card.mana_cost, x_value=x_value, extra_generic=_extra_generic_tax(game, card))
            plan = _plan_taps_for_cost(player, required)
            if plan is None:
                continue
            tap_indices = tuple(plan)

        score = _score_cast(game, player_index, card, target, x_value)
        # During declare blockers, prefer combat-relevant instants.
        if game.current_turn_phase == "combat" and game.current_step == "declare_blockers":
            lowered = card.oracle_text.lower()
            if "damage" in lowered or "destroy" in lowered or "prevent" in lowered or "tap" in lowered:
                score += 2.0
        score += _stack_response_bonus(game, player_index, card, target)
        if score < 2.0:
            continue

        candidate = CastAction(
            card_name=card.name,
            target_player_index=target,
            x_value=x_value,
            land_tap_indices=tap_indices,
            score=score,
            hand_index=hand_index,
        )
        if _is_better_cast(candidate, best):
            best = candidate

    return best


def _stack_response_bonus(game: Game, caster_index: int, card: CardDefinition, target_index: int) -> float:
    if not game.stack:
        return 0.0

    top = game.stack[-1]
    if top.caster_index == caster_index:
        # Avoid spending reaction cards while responding to our own stack item.
        return -0.5

    lowered = card.oracle_text.lower()
    bonus = 0.0

    if "counter target spell" in lowered or card.name == "Counterspell":
        bonus += 6.0

    if top.target_player_index == caster_index:
        if "prevent" in lowered and "damage" in lowered:
            bonus += 2.5
        if "gain" in lowered and "life" in lowered:
            bonus += 1.5

    if _extract_damage(card) > 0 and target_index == 1 - caster_index:
        bonus += 1.0

    if "destroy" in lowered or "disenchant" in lowered or "unsummon" in lowered:
        bonus += 0.75

    return bonus


def _is_better_cast(candidate: CastAction, current: CastAction | None) -> bool:
    if current is None:
        return True
    if candidate.score > current.score:
        return True
    if candidate.score < current.score:
        return False
    return candidate.hand_index < current.hand_index


def _permanent_value(permanent: Permanent) -> float:
    return permanent.effective_power * 1.4 + permanent.effective_toughness * 1.1 + float(permanent.card.cmc)


def _score_block_pair(blocker: Permanent, attacker: Permanent) -> float:
    blocker_kills = blocker.effective_power >= attacker.effective_toughness
    attacker_kills = attacker.effective_power >= blocker.effective_toughness

    attacker_value = _permanent_value(attacker)
    blocker_value = _permanent_value(blocker)

    score = 0.0
    if blocker_kills and not attacker_kills:
        score += attacker_value + 4.0
    elif blocker_kills and attacker_kills:
        score += attacker_value - blocker_value * 0.6 + 2.0
    elif not blocker_kills and attacker_kills:
        score -= blocker_value + 2.0
    else:
        score += min(attacker.effective_power, blocker.effective_toughness) * 0.5

    # Prefer blocking higher impact attackers.
    score += attacker.effective_power * 0.3 + attacker.effective_toughness * 0.2
    return score


def _estimated_damage_prevented(game: Game, defending_player_index: int, attacker_idx: int, blocker_idx: int) -> int:
    attacker = game.players[game.active_player_index].battlefield[attacker_idx]
    blocker = game.players[defending_player_index].battlefield[blocker_idx]
    power = max(0, attacker.effective_power)
    if game._has_keyword(attacker, "trample"):
        return min(power, max(0, blocker.effective_toughness - blocker.damage_marked))
    return power


def _estimated_incoming_player_damage(game: Game, defending_player_index: int) -> int:
    combat = game.get_combat_state()
    total = 0
    for item in combat.get("attackers", []):
        if item.get("defending_player_index") != defending_player_index:
            continue
        attacker_idx = int(item.get("attacker_index", -1))
        if attacker_idx < 0 or attacker_idx >= len(game.players[game.active_player_index].battlefield):
            continue
        attacker = game.players[game.active_player_index].battlefield[attacker_idx]
        total += max(0, attacker.effective_power)
    return total


def _can_cast_with_targets(game: Game, caster_index: int, card: CardDefinition) -> bool:
    opponent = game.players[1 - caster_index]
    caster = game.players[caster_index]

    program = compile_card_oracle(card)
    for instruction in program.instructions:
        kind = instruction.kind

        if kind == "bounce_target_creature":
            return any(perm.card.primary_type == "creature" for perm in opponent.battlefield)

        if kind == "destroy_target_permanent":
            type_filter = instruction.payload.get("type_filter")
            color_filter = instruction.payload.get("color_filter")
            if type_filter or color_filter:
                text = card.oracle_text.lower()
                if "target artifact or enchantment" in text:
                    return any(perm.card.primary_type in {"artifact", "enchantment"} for perm in opponent.battlefield)
                return any(
                    (not type_filter or perm.card.primary_type == type_filter)
                    and (not color_filter or color_filter in perm.card.colors)
                    for perm in opponent.battlefield
                )

        if kind in {"pump_target_creature_until_eot", "grant_regeneration_to_target_creature",
                    "grant_target_flying_until_eot", "berserk_pump"}:
            return any(perm.card.primary_type == "creature" for perm in caster.battlefield)

    return True


def _choose_aura_target(game: Game, caster_index: int, card: CardDefinition) -> tuple[int, int] | None:
    """Pick (player_index, permanent_index) for an Aura's enchant target.

    Harmful auras go on an opponent's permanent, beneficial ones on the caster's.
    Returns None when the preferred player has no legal target — the Aura is
    unplayable this turn rather than cast onto a permanent that helps the enemy.
    """
    noun = aura_enchant_noun(card)
    if noun is None:
        return None
    text = card.oracle_text.lower()
    harmful = any(
        marker in text
        for marker in (
            "gets -",
            "doesn't untap",
            "tap enchanted",
            "you control enchanted",
            "can't attack",
            "can't block",
        )
    )
    target_player_index = (1 - caster_index) if harmful else caster_index
    for permanent_index, permanent in enumerate(game.players[target_player_index].battlefield):
        if permanent_matches_enchant_noun(permanent, noun):
            return target_player_index, permanent_index
    return None


def _choose_target_for_spell(card: CardDefinition, caster_index: int, game: Game) -> int:
    self_score = _score_spell_target(card, caster_index, caster_index, game)
    opponent_index = 1 - caster_index
    opp_score = _score_spell_target(card, caster_index, opponent_index, game)
    if self_score >= opp_score:
        return caster_index
    return opponent_index


def _score_spell_target(card: CardDefinition, caster_index: int, target_index: int, game: Game) -> float:
    caster = game.players[caster_index]
    target = game.players[target_index]
    other = game.players[1 - target_index]
    text = card.oracle_text.lower()

    score = 0.0
    if "draw" in text:
        if target_index == caster_index:
            # Targeting self when library has <= 3 cards would exhaust it and cause a
            # loss via rule 704.5b on the next draw step; redirect to the opponent instead.
            if card.name == "Ancestral Recall" and len(caster.library) <= 3:
                score -= 100.0
            else:
                score += 5.0
        else:
            score += 0.5
    if "gain" in text and "life" in text:
        if target_index == caster_index:
            # Scale score with how much life has been lost from the 20-life starting total.
            # At full life (20+) the gain is worthless; pressure grows as life drops.
            life_lost = max(0, 20 - caster.life)
            score += life_lost * 0.15
        else:
            score -= 2.0

    damage = _extract_damage(card)
    if damage > 0:
        if target_index != caster_index:
            score += 4.0
            if target.life <= damage:
                score += 10.0
            score += (20 - target.life) * 0.05
        else:
            score -= 6.0

    if card.name == "Unsummon":
        if target_index == caster_index:
            return -50.0
        creatures = [perm for perm in target.battlefield if perm.card.primary_type == "creature"]
        return 2.0 + max((perm.effective_power for perm in creatures), default=0)

    if card.name == "Disenchant":
        if target_index == caster_index:
            return -50.0
        artifacts_or_enchantments = [
            perm
            for perm in target.battlefield
            if perm.card.primary_type in {"artifact", "enchantment"}
        ]
        return 2.0 + len(artifacts_or_enchantments) * 1.5

    if "target opponent" in text:
        score += 3.0 if target_index != caster_index else -10.0
    if "target player" in text and "draw" not in text and damage == 0 and "gain" not in text:
        score += 0.5 if target_index != caster_index else 0.0

    if card.primary_type == "creature" and target_index == caster_index:
        score += 1.0

    if other.life <= 0:
        score -= 1.0

    return score


def _score_cast(game: Game, caster_index: int, card: CardDefinition, target_index: int, x_value: int | None) -> float:
    caster = game.players[caster_index]
    opponent = game.players[1 - caster_index]

    if card.primary_type == "land":
        untapped_lands = sum(1 for perm in caster.battlefield if perm.card.primary_type == "land" and not perm.tapped)
        return 1.0 if untapped_lands < 4 else 0.2

    score = 1.5
    if card.primary_type in {"instant", "sorcery"}:
        score += 2.0
    if card.primary_type == "creature":
        score += 1.2
        score += _creature_stat(card, "power") * 0.7
        score += _creature_stat(card, "toughness") * 0.4
    if card.primary_type in {"artifact", "enchantment"}:
        score += 0.8

    score += _score_spell_target(card, caster_index, target_index, game)

    if x_value is not None:
        score += min(4.0, x_value * 0.6)

    if card.name == "Ancestral Recall":
        score += 8.0
        # Never self-target when 3 or fewer library cards remain — drawing 3 leaves library
        # at 0, causing a 704.5b loss on the next draw step.
        if target_index == caster_index and len(caster.library) <= 3:
            return -100.0
    elif card.name == "Lightning Bolt" and target_index == 1 - caster_index and opponent.life <= 3:
        score += 12.0
    elif card.name == "Black Lotus":
        if game.enforce_mana_costs:
            hand_nonlands = sum(1 for hand_card in caster.hand if hand_card.primary_type != "land")
            score += 2.0 if hand_nonlands >= 2 else 0.5
        else:
            # Mana costs not enforced — Black Lotus provides no benefit, make it unattractive
            score -= 2.0

    return score


def _score_activation(
    game: Game,
    player_index: int,
    permanent: Permanent,
    instruction: OracleInstruction,
    target_index: int,
) -> float:
    score = 1.0
    opponent = game.players[1 - player_index]

    if instruction.kind == "deal_damage":
        amount = int(instruction.payload.get("amount", 1) or 1)
        target_player = game.players[target_index]
        effective_damage = max(0, amount - target_player.damage_prevention_pool)
        if effective_damage == 0:
            return -10.0
        score += 5.0 + effective_damage
        if target_index == 1 - player_index and target_player.life <= effective_damage:
            score += 10.0
    elif instruction.kind == "draw_target_cards":
        score += 5.0 if target_index == player_index else 0.0
    elif instruction.kind in {"add_mana", "black_lotus_add_mana"}:
        score += 2.5
    elif instruction.kind == "grant_banding_to_target":
        score += 0.5
    else:
        score += 1.5

    if permanent.card.name == "Jayemdae Tome" and not game.players[player_index].library:
        return -100.0

    return score


def _choose_target_for_instruction(instruction: OracleInstruction, caster_index: int, game: Game) -> int:
    if instruction.kind in {"draw_target_cards", "gain_life", "prevent_damage", "black_lotus_add_mana"}:
        return caster_index
    if instruction.kind in {"deal_damage", "destroy_target", "bounce_target", "target_player_loses_life"}:
        return 1 - caster_index

    # Fallback: prefer opponent for proactive effects.
    return 1 - caster_index


def _extract_damage(card: CardDefinition) -> int:
    program = compile_card_oracle(card)
    for instruction in program.instructions:
        if instruction.kind == "deal_damage":
            amount = instruction.payload.get("amount")
            if isinstance(amount, int):
                return amount
    match = re.search(r"deals? (\d+) damage", card.oracle_text.lower())
    if match:
        return int(match.group(1))
    return 0


def _creature_stat(card: CardDefinition, key: str) -> int:
    raw_value = str(card.raw.get(key, "0"))
    return int(raw_value) if raw_value.isdigit() else 0


def _extra_generic_tax(game: Game, card: CardDefinition) -> int:
    if "W" not in card.colors:
        return 0
    has_gloom = any(
        perm.card.name == "Gloom"
        for player in game.players
        for perm in player.battlefield
    )
    return 3 if has_gloom else 0


def _pick_x_value(game: Game, player: PlayerState, card: CardDefinition) -> int | None:
    if "{X}" not in card.mana_cost.upper():
        return None

    max_x = _max_affordable_x(game, player, card)
    return max_x


def _max_affordable_x(game: Game, player: PlayerState, card: CardDefinition) -> int:
    pool = _preview_pool_with_all_untapped_lands(player)
    extra_tax = _extra_generic_tax(game, card)

    for x_value in range(15, -1, -1):
        required = game._parse_mana_cost(card.mana_cost, x_value=x_value, extra_generic=extra_tax)
        if _can_pay_cost(pool, required, player.can_spend_white_as_red):
            return x_value
    return 0


def _preview_pool_with_all_untapped_lands(player: PlayerState) -> dict[str, int]:
    pool = {symbol: player.mana_pool.get(symbol, 0) for symbol in _MANA_SYMBOLS}
    for permanent in player.battlefield:
        if permanent.card.primary_type != "land" or permanent.tapped:
            continue
        symbol = _land_symbol(permanent)
        pool[symbol] = pool.get(symbol, 0) + 1
    return pool


def _plan_taps_for_cost(player: PlayerState, required: dict[str, int]) -> list[int] | None:
    pool = {symbol: player.mana_pool.get(symbol, 0) for symbol in _MANA_SYMBOLS}
    untapped_lands = [
        (index, _land_symbol(permanent))
        for index, permanent in enumerate(player.battlefield)
        if permanent.card.primary_type == "land" and not permanent.tapped
    ]

    if _can_pay_cost(pool, required, player.can_spend_white_as_red):
        return []

    chosen: list[int] = []
    remaining = list(untapped_lands)

    for symbol in _MANA_SYMBOLS:
        need = max(0, required.get(symbol, 0) - pool.get(symbol, 0))
        while need > 0:
            match_idx = next((idx for idx, (_, produced) in enumerate(remaining) if produced == symbol), None)
            if match_idx is None:
                break
            land_index, produced = remaining.pop(match_idx)
            chosen.append(land_index)
            pool[produced] = pool.get(produced, 0) + 1
            need -= 1

    while remaining and not _can_pay_cost(pool, required, player.can_spend_white_as_red):
        best_idx = 0
        best_benefit = -1
        for idx, (_, produced) in enumerate(remaining):
            benefit = 2 if pool.get(produced, 0) < required.get(produced, 0) else 1
            if produced == "C" and required.get("generic", 0) == 0:
                benefit = 0
            if benefit > best_benefit:
                best_benefit = benefit
                best_idx = idx
        land_index, produced = remaining.pop(best_idx)
        chosen.append(land_index)
        pool[produced] = pool.get(produced, 0) + 1

    if not _can_pay_cost(pool, required, player.can_spend_white_as_red):
        return None

    return chosen


def _can_pay_cost(pool: dict[str, int], required: dict[str, int], can_spend_white_as_red: bool) -> bool:
    if pool.get("W", 0) < required.get("W", 0):
        return False
    if pool.get("U", 0) < required.get("U", 0):
        return False
    if pool.get("B", 0) < required.get("B", 0):
        return False
    if pool.get("G", 0) < required.get("G", 0):
        return False
    if pool.get("C", 0) < required.get("C", 0):
        return False

    available_red = pool.get("R", 0)
    if can_spend_white_as_red:
        available_red += pool.get("W", 0)
    if available_red < required.get("R", 0):
        return False

    temp = {symbol: pool.get(symbol, 0) for symbol in _MANA_SYMBOLS}
    temp["W"] -= required.get("W", 0)
    temp["U"] -= required.get("U", 0)
    temp["B"] -= required.get("B", 0)
    temp["G"] -= required.get("G", 0)
    temp["C"] -= required.get("C", 0)

    red_to_pay = required.get("R", 0)
    from_red = min(temp.get("R", 0), red_to_pay)
    temp["R"] -= from_red
    red_to_pay -= from_red
    if red_to_pay > 0:
        if not can_spend_white_as_red:
            return False
        if temp.get("W", 0) < red_to_pay:
            return False
        temp["W"] -= red_to_pay

    generic = required.get("generic", 0)
    if generic <= 0:
        return True

    available_generic = sum(max(0, temp.get(symbol, 0)) for symbol in ("C", "W", "U", "B", "R", "G"))
    return available_generic >= generic


def _land_symbol(permanent: Permanent) -> str:
    if permanent.card.produced_mana:
        return permanent.card.produced_mana[0]

    land_types = [str(permanent.metadata.get("land_type_override", "")).lower(), permanent.card.type_line.lower()]
    if any("plains" in value for value in land_types):
        return "W"
    if any("island" in value for value in land_types):
        return "U"
    if any("swamp" in value for value in land_types):
        return "B"
    if any("mountain" in value for value in land_types):
        return "R"
    if any("forest" in value for value in land_types):
        return "G"
    return "C"
