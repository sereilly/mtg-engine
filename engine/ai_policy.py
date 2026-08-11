from __future__ import annotations

from dataclasses import dataclass
import re

from .ai_valuation import (
    SPELL_TYPES,
    cards_drawn_by_controller,
    cards_drawn_by_target,
    counters_a_spell,
    destroyed_permanent_filter,
    is_mana_ability,
    mana_ability_amount,
    returns_creature_to_hand,
)
from .cost_modifiers import spell_cost_tax
from .classifier import classify_card
from .game import Game
from .handlers._common import permanent_matches_filter
from .mixins.stack import aura_enchant_noun, permanent_matches_enchant_noun
from .auras import aura_restriction_active
from .models import CardDefinition, Permanent, PlayerState
from .oracle import OracleInstruction, compile_card_oracle
from .oracle_types import x_spend_color_from_text
from .search_filters import search_matches
from .targeting import derive_cast_spec

_MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")


@dataclass(frozen=True)
class CastAction:
    card_name: str
    target_player_index: int
    x_value: int | None
    land_tap_indices: tuple[int, ...]
    score: float
    hand_index: int
    # One chosen permanent, or several for a spell that names "up to N target"
    # objects. The same shape ``queue_from_hand`` and the stack already speak, so
    # the executors in web/game_flow.py forward it unchanged.
    target_permanent_index: int | list[int] | None = None


@dataclass(frozen=True)
class ActivationAction:
    permanent_name: str
    permanent_index: int
    target_player_index: int
    land_tap_indices: tuple[int, ...]
    score: float


def choose_attack_target(game: Game, player_index: int) -> int:
    """MVP multiplayer opponent-choice heuristic: attack/target whichever living
    opponent has the least life, tying broken by lowest seat index (deterministic
    for tests/seeded simulations). Intentionally simple — no board-state or
    threat-assessment awareness; deeper multiplayer AI tactics are future work.
    In a 2-player game this is always just the other seat."""
    opponents = game.opponents_of(player_index)
    if not opponents:
        return player_index
    return min(opponents, key=lambda idx: (game.players[idx].life, idx))


def choose_cast_action(game: Game, player_index: int) -> CastAction | None:
    player = game.players[player_index]

    best: CastAction | None = None
    for hand_index, card in enumerate(player.hand):
        if (
            card.primary_type == "land"
            and game.enforce_mana_costs
            and not game._may_play_another_land(player_index)
        ):
            continue
        if not _can_cast_with_targets(game, player_index, card):
            continue

        # X first: an X-draw spell's target choice depends on how many cards it
        # would draw (a spell that empties your own library is aimed elsewhere),
        # so the value has to exist before the target is picked.
        x_value = _pick_x_value(game, player, card)
        if x_value == 0:
            continue
        target = _choose_target_for_spell(card, player_index, game, x_value)
        target_permanent_index: int | list[int] | None = None
        if aura_enchant_noun(card) is not None:
            aura_choice = _choose_aura_target(game, player_index, card)
            if aura_choice is None:
                continue  # Aura spells require a legal target (Rule 115.1b)
            target, target_permanent_index = aura_choice
        else:
            several = _choose_several_targets(game, player_index, card)
            if several is not None:
                target, target_permanent_index = several
        tap_indices: tuple[int, ...] = ()

        if game.enforce_mana_costs and card.primary_type != "land":
            required = game._parse_mana_cost(
                card.mana_cost,
                x_value=x_value,
                extra_generic=_extra_generic_tax(game, card),
                x_color=x_spend_color_from_text(card.oracle_text),
            )
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

        # A mana ability is activated to *pay* for something (_plan_taps_for_cost
        # arranges that), never for its own sake: mana added here empties at the
        # end of the step, and Black Lotus sacrifices itself to add it. The set
        # this replaced named two instruction kinds that no longer exist, so the
        # skip had silently stopped happening — see MANA_ABILITY_KINDS.
        if is_mana_ability(ability.instruction):
            continue

        # A cost paid in permanents or cards is a trade this policy cannot
        # price: Atog's "+2/+2 until end of turn" is worth an artifact only
        # sometimes, and the score below reads the *effect* alone. Skipping is
        # the honest floor — the alternative is an AI that eats its own board
        # every main phase for a pump that wears off. Derived from the compiled
        # cost, so it reaches every card printed this way and names none.
        if ability.cost.sacrifice_type or ability.cost.discard_cards:
            continue

        target = _choose_target_for_instruction(ability.instruction, player_index, game)
        if ability.instruction.kind == "grant_banding_to_target":
            # Banding grants go to the controller's own creatures.
            target = player_index
            target_creatures = [
        perm for perm in game.controlled_by(player_index) if perm.card.primary_type == "creature"
    ]
            if not target_creatures:
                continue

        land_taps: tuple[int, ...] = ()
        required = dict(ability.cost.mana)
        if game.enforce_mana_costs and any(required.values()):
            plan = _plan_taps_for_cost(player, required)
            if plan is None:
                continue
            land_taps = tuple(plan)

        score = _score_activation(game, player_index, ability.instruction, target)
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


def legal_attackers(game: Game, attacking_player_index: int, against: int | None = None) -> list[int]:
    """Return battlefield indices of every creature that may legally attack this
    turn — untapped, not summoning sick, and allowed to attack an opponent.

    When ``against`` is given, mirrors the original single-opponent behavior
    (legal against that one specific opponent). When omitted, returns creatures
    legal against ANY living opponent."""
    player = game.players[attacking_player_index]
    opponents = [against] if against is not None else game.opponents_of(attacking_player_index)
    return [
        idx
        for idx, perm in enumerate(player.battlefield)
        if perm.card.primary_type == "creature"
        and not perm.tapped
        and not game._is_summoning_sick(perm)
        and any(game.can_attack(perm, opp) for opp in opponents)
    ]


def choose_attackers(game: Game, attacking_player_index: int) -> list[int]:
    """Return indices of creatures that should attack this turn.

    MVP multiplayer behavior: picks one opponent (``choose_attack_target``) and
    decides, for each legal attacker, whether to send it at that opponent —
    splitting one attack across multiple opponents is a documented stretch goal,
    not implemented here."""
    player = game.players[attacking_player_index]
    opponent_index = choose_attack_target(game, attacking_player_index)
    opponent = game.players[opponent_index]

    legal_attackers_list = legal_attackers(game, attacking_player_index, against=opponent_index)
    if not legal_attackers_list:
        return []

    # Creatures that must attack if able (Siren's Call, Lure-style "attacks each
    # combat if able", etc.) are non-negotiable: declare_attackers rejects any
    # declaration that omits them, so they must be in the result regardless of
    # the profitability heuristic below.
    forced = [idx for idx in legal_attackers_list if game._must_attack_if_able(player.battlefield[idx])]

    # A creature enchanted with Lure ("All creatures able to block it do so") is
    # only worth attacking with if it actually gets declared. Treat it as forced
    # so the AI doesn't decline to attack with it (which would skip the defender's
    # block step entirely from the human's perspective).
    for idx in legal_attackers_list:
        if idx not in forced and aura_restriction_active(
            player.battlefield[idx], "must_be_blocked_by_all_able"
        ):
            forced.append(idx)

    opponent_blockers = [
        perm
        for perm in game.controlled_by(opponent)
        if perm.card.primary_type == "creature" and not perm.tapped
    ]
    if not opponent_blockers:
        return legal_attackers_list

    chosen = list(forced)
    for idx in legal_attackers_list:
        if idx in chosen:
            continue
        attacker = player.battlefield[idx]
        best_defender_score = max(
            _score_block_pair(blocker, attacker) for blocker in opponent_blockers
        )
        # Attack when the best possible block is not clearly profitable for the opponent.
        if best_defender_score <= _permanent_value(attacker):
            chosen.append(idx)

    # Go all-in when lethal is on the table.
    if sum(player.battlefield[i].effective_power for i in legal_attackers_list) >= opponent.life:
        return legal_attackers_list

    return sorted(chosen)


def choose_combat_blockers(game: Game, defending_player_index: int) -> dict[int, int | list[int]]:
    combat = game.get_combat_state()
    if game.current_turn_phase != "combat" or game.current_step != "declare_blockers":
        return {}
    if defending_player_index not in game.combat_defending_players():
        return {}

    active_index = game.active_player_index
    # CR 802.4a: this defender may only block attackers aimed at them.
    attackers = [
        int(item["attacker_index"])
        for item in combat.get("attackers", [])
        if item.get("defending_player_index") == defending_player_index
    ]
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
    menace_attackers: set[int] = set()
    for blocker_idx in available_blockers:
        blocker = defender.battlefield[blocker_idx]
        for attacker_idx in attackers:
            if attacker_idx < 0 or attacker_idx >= len(attacker_player.battlefield):
                continue
            attacker = attacker_player.battlefield[attacker_idx]
            if game._has_keyword(attacker, "menace"):
                menace_attackers.add(attacker_idx)
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

    # Blaze of Glory: a creature marked "blocks each attacking creature this
    # turn if able" must be assigned every attacker it can legally block —
    # declare_blockers rejects anything less.
    for blocker_idx in available_blockers:
        blocker = defender.battlefield[blocker_idx]
        if not blocker.metadata.get("must_block_all_until_eot"):
            continue
        must = [
            attacker_idx
            for attacker_idx in attackers
            if 0 <= attacker_idx < len(attacker_player.battlefield)
            and game._can_block_attacker(blocker, attacker_player.battlefield[attacker_idx])
        ]
        if must:
            assignments[blocker_idx] = must

    # Menace (CR 702.111b): declare_blockers refuses an assignment that puts
    # exactly one blocker on a menace attacker, so the AI declines those blocks
    # rather than submitting a declaration that bounces. Ganging up is a
    # valuation question for another day; not blocking is always legal.
    menace_counts: dict[int, int] = {}
    for assigned in assignments.values():
        for attacker_idx in assigned if isinstance(assigned, list) else [assigned]:
            menace_counts[attacker_idx] = menace_counts.get(attacker_idx, 0) + 1
    for attacker_idx, count in menace_counts.items():
        if count != 1 or attacker_idx not in menace_attackers:
            continue
        for blocker_idx in list(assignments):
            assigned = assignments[blocker_idx]
            if isinstance(assigned, list):
                remaining = [a for a in assigned if a != attacker_idx]
                if remaining:
                    assignments[blocker_idx] = remaining
                else:
                    del assignments[blocker_idx]
            elif assigned == attacker_idx:
                del assignments[blocker_idx]

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
            required = game._parse_mana_cost(
                card.mana_cost,
                x_value=x_value,
                extra_generic=_extra_generic_tax(game, card),
                x_color=x_spend_color_from_text(card.oracle_text),
            )
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


def choose_search_card(
    game: Game, player_index: int, data: dict
) -> tuple[str, int] | None:
    """Pick the ``(zone, index)`` of the best card a search may find, or None to
    fail to find (CR 701.19b).

    Both the zones and the restriction come from the armed choice rather than
    from a second reading of the card: the AI is then offered exactly the cards
    a human seat is offered, and ``search_matches`` is the only thing deciding
    what is findable. An AI that filtered differently would be a second opinion
    about what the effect finds — the same bug class as a second parse.
    """
    player = game.players[player_index]
    best: tuple[str, int] | None = None
    best_score = float("-inf")
    for zone in tuple(data.get("zones", ("library",))):
        cards = player.library if zone == "library" else player.graveyard
        for index, card in enumerate(cards):
            if not search_matches(card, data):
                continue
            score = _score_tutor_choice(game, player_index, card)
            if best is None or score > best_score:
                best = (zone, index)
                best_score = score
    return best


def choose_search_library_index(game: Game, player_index: int, card_type: str = "any") -> int | None:
    """Pick the library index of the best card to tutor for (e.g. Demonic Tutor).

    Returns None when no library card matches card_type (fail to find). The
    library-only view of ``choose_search_card``, kept because a caller that only
    ever searches a library should not have to spell out a zone list."""
    found = choose_search_card(game, player_index, {"card_type": card_type})
    return None if found is None else found[1]


def choose_reorder_library_order(
    game: Game, caster_index: int, target_index: int, top_count: int
) -> list[int]:
    """Decide how to rearrange the top cards of a library (e.g. Natural Selection).

    Returns a permutation of ``range(top_count)`` where element 0 is the original
    index of the card that should end up on top (the next card drawn).

    When reordering our own library we surface the most valuable card first so we
    draw it next; when reordering an opponent's library we bury their best cards by
    putting the least valuable one on top.
    """
    target = game.players[target_index]
    top = target.library[:top_count]

    # Score each card from the library owner's perspective — how good drawing it
    # would be for them.
    scored = [
        (index, _score_tutor_choice(game, target_index, card))
        for index, card in enumerate(top)
    ]
    surface_best_first = caster_index == target_index
    scored.sort(key=lambda item: item[1], reverse=surface_best_first)
    return [index for index, _ in scored]


def choose_scry_arrangement(
    game: Game, caster_index: int, top_count: int
) -> tuple[list[int], int]:
    """Decide a scry (CR 701.22a): the arrangement, and how many go to the bottom.

    Returns ``(card_order, bottom_count)`` in the shape ``_resolve_scry`` takes —
    a permutation of ``range(top_count)`` reading top-first, and how many of its
    trailing entries go to the bottom.

    Scored by ``_score_tutor_choice`` unchanged, because "how good would drawing
    this be for me" is exactly the scry question and a second scoring function
    would be a second opinion about the same thing. A card scoring below zero is
    worse than an unknown card, so those go to the bottom; the rest are ordered
    best-first so the best one is drawn next. Deterministic given the library,
    which the AI-behaviour regression tests require.
    """
    caster = game.players[caster_index]
    scored = [
        (index, _score_tutor_choice(game, caster_index, card))
        for index, card in enumerate(caster.library[:top_count])
    ]
    kept = sorted((s for s in scored if s[1] >= 0.0), key=lambda item: item[1], reverse=True)
    bottomed = sorted((s for s in scored if s[1] < 0.0), key=lambda item: item[1], reverse=True)
    return [index for index, _ in kept] + [index for index, _ in bottomed], len(bottomed)


def _score_tutor_choice(game: Game, player_index: int, card: CardDefinition) -> float:
    player = game.players[player_index]
    opponent_index = choose_attack_target(game, player_index)
    opponent = game.players[opponent_index]

    # Cards the engine cannot cast would strand in hand.
    if not classify_card(card).supported:
        return -50.0

    x_value = _pick_x_value(game, player, card)
    target = _choose_target_for_spell(card, player_index, game, x_value)
    score = _score_cast(game, player_index, card, target, x_value)

    lands_available = sum(
        1 for perm in game.controlled_by(player) if perm.card.primary_type == "land"
    ) + sum(
        1 for hand_card in player.hand if hand_card.primary_type == "land"
    )
    if card.primary_type == "land":
        # Lands are only worth tutoring when mana-screwed.
        if lands_available < 3:
            score += 4.0 - lands_available
        else:
            score -= 4.0
    elif game.enforce_mana_costs:
        pool = _preview_pool_with_all_untapped_lands(game, player)
        required = game._parse_mana_cost(
            card.mana_cost,
            x_value=x_value if x_value is not None else 0,
            extra_generic=_extra_generic_tax(game, card),
            x_color=x_spend_color_from_text(card.oracle_text),
        )
        if _can_pay_cost(pool, required, player.can_spend_white_as_red):
            score += 3.0  # castable as soon as it reaches hand
        else:
            available = sum(pool.values())
            score -= min(5.0, max(0.0, float(card.cmc) - available))

    # A tutored burn spell that closes the game outranks everything else.
    damage = _extract_damage(card)
    if target == opponent_index and 0 < opponent.life <= damage:
        score += 15.0

    return score


def _stack_response_bonus(game: Game, caster_index: int, card: CardDefinition, target_index: int) -> float:
    if not game.stack:
        return 0.0

    top = game.stack[-1]
    if top.caster_index == caster_index:
        # Avoid spending reaction cards while responding to our own stack item.
        return -0.5

    lowered = card.oracle_text.lower()
    bonus = 0.0

    # Countering is only worth holding up against a spell this card may legally
    # be aimed at, which is why the profile carries the colour restriction
    # rather than the caller assuming there is none.
    counter = counters_a_spell(card)
    if counter is not None and counter.can_counter(top.card):
        bonus += 6.0

    if top.target_player_index == caster_index:
        if "prevent" in lowered and "damage" in lowered:
            bonus += 2.5
        if "gain" in lowered and "life" in lowered:
            bonus += 1.5

    if _extract_damage(card) > 0 and target_index == choose_attack_target(game, caster_index):
        bonus += 1.0

    # Removal is worth a little in response. The probes here used to be
    # ``"disenchant" in lowered or "unsummon" in lowered`` — a card's *name*
    # looked for inside its own oracle text, which no card in the pool contains,
    # so both were dead and only the generic "destroy" ever fired.
    if "destroy" in lowered or destroyed_permanent_filter(card) is not None or returns_creature_to_hand(card):
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
    """Whether *card* has a legal target for the effect it carries out **as it
    is cast**.

    Only a spell does; see ``ai_valuation.SPELL_TYPES``. A permanent's
    instruction list mirrors its *abilities*, which choose their own targets on
    activation — so reading it here would refuse to cast Flying Carpet while the
    AI controls no creature, and refuse Pyramids while the opponent controls no
    enchantment, for permanents that are perfectly castable and simply have
    nothing to point at yet. That is the same misreading ``SPELL_TYPES`` exists
    to prevent one module over, and ``targeting.derive_cast_spec`` guards with
    the same gate for the UI's benefit.
    """
    if card.primary_type not in SPELL_TYPES:
        return True

    opponent = game.players[choose_attack_target(game, caster_index)]
    caster = game.players[caster_index]

    program = compile_card_oracle(card)
    for instruction in program.instructions:
        kind = instruction.kind

        if kind == "bounce_target_creature":
            return any(
                perm.card.primary_type == "creature" for perm in game.controlled_by(opponent)
            )

        if kind == "destroy_target_permanent":
            type_filter = instruction.payload.get("type_filter")
            color_filter = instruction.payload.get("color_filter")
            if type_filter or color_filter:
                text = card.oracle_text.lower()
                if "target artifact or enchantment" in text:
                    return any(
                        perm.card.primary_type in {"artifact", "enchantment"}
                        for perm in game.controlled_by(opponent)
                    )
                return any(
                    (not type_filter or perm.card.primary_type == type_filter)
                    and (not color_filter or color_filter in perm.card.colors)
                    for perm in game.controlled_by(opponent)
                )

        if kind in {"pump_target_creature_until_eot", "grant_regeneration_to_target_creature",
                    "grant_target_flying_until_eot", "berserk_pump"}:
            return any(
                perm.card.primary_type == "creature" for perm in game.controlled_by(caster)
            )

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
    target_player_index = choose_attack_target(game, caster_index) if harmful else caster_index
    for permanent_index, permanent in enumerate(game.players[target_player_index].battlefield):
        if permanent_matches_enchant_noun(permanent, noun):
            return target_player_index, permanent_index
    return None


def _choose_several_targets(
    game: Game, caster_index: int, card: CardDefinition
) -> tuple[int, list[int]] | None:
    """Pick ``(seat, [permanent_index, …])`` for a spell naming "up to N target"
    objects, or None when the card names no such choice.

    Which cards this reaches is *derived*, never a list of names: the compiled
    program carries the maximum (``engine/targeting.py``'s ``max_targets``), so a
    card printed with the same template is covered the day it is ingested. The
    cheap derivation is asked first and the expensive enumeration only when it
    says yes, because this runs for every card in hand on every AI decision.

    Taking the maximum is the whole policy, and it is a policy rather than a
    rule: "up to N" may legally choose fewer, but every printed card carrying
    this template gives a benefit per target, so more is better. A card that
    ever wants fewer needs a valuation, not a special case here.
    """
    spec = derive_cast_spec(card, compile_card_oracle(card))
    maximum = (spec or {}).get("max_targets")
    if not isinstance(maximum, int) or maximum <= 1:
        return None
    legal = game.cast_target_spec(caster_index, card).get("valid_targets") or []
    # One seat's worth: the index list is positional on a single battlefield
    # (`target_player_index` names whose), so a cross-seat spread would need the
    # divided carrier instead. Prefer the caster's own seat, which is what every
    # card carrying this template so far targets.
    by_seat: dict[int, list[int]] = {}
    for entry in legal:
        if entry.get("kind") != "permanent":
            continue
        by_seat.setdefault(int(entry["seat"]), []).append(int(entry["index"]))
    if not by_seat:
        return None
    seat = caster_index if caster_index in by_seat else min(by_seat)
    return seat, by_seat[seat][:maximum]


def _choose_target_for_spell(
    card: CardDefinition, caster_index: int, game: Game, x_value: int | None = None
) -> int:
    self_score = _score_spell_target(card, caster_index, caster_index, game, x_value)
    opponent_index = choose_attack_target(game, caster_index)
    opp_score = _score_spell_target(card, caster_index, opponent_index, game, x_value)
    if self_score >= opp_score:
        return caster_index
    return opponent_index


def _score_spell_target(
    card: CardDefinition,
    caster_index: int,
    target_index: int,
    game: Game,
    x_value: int | None = None,
) -> float:
    caster = game.players[caster_index]
    target = game.players[target_index]
    text = card.oracle_text.lower()

    score = 0.0
    if "draw" in text:
        if target_index == caster_index:
            # Drawing more cards than the library holds is a loss by CR 704.5b on
            # the next draw; redirect to the opponent instead. How many cards the
            # spell draws is read off the compiled instruction, so "Target player
            # draws X cards" is covered at the X the caster picked and not only
            # the one card printed "three".
            drawn = cards_drawn_by_target(card, x_value)
            if drawn is not None and len(caster.library) <= drawn:
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
    if damage == 0:
        # X-damage spells (Disintegrate, Fireball, …) parse to amount 'x', so the
        # literal extractor reads 0. Estimate the damage from the most X the caster
        # can pay; without this the spell registers as dealing no damage and the
        # tie-break below points it at the caster's own face.
        damage = _estimate_x_damage(game, caster, card)
    if damage > 0:
        if target_index != caster_index:
            score += 4.0
            if target.life <= damage:
                score += 10.0
            score += (20 - target.life) * 0.05
        else:
            score -= 6.0

    # Interaction aimed at a player's board, valued by what that board offers.
    # Both used to be one card name each; the two templates they stood for are
    # printed on nine cards in this pool alone, and the seven that were not
    # named aimed themselves at the AI's own permanents.
    if returns_creature_to_hand(card):
        if target_index == caster_index:
            return -50.0
        creatures = [perm for perm in game.controlled_by(target) if perm.is_creature]
        return 2.0 + max((perm.effective_power for perm in creatures), default=0)

    destroy_filter = destroyed_permanent_filter(card)
    if destroy_filter is not None:
        if target_index == caster_index:
            return -50.0
        # The engine's own matcher, so the AI counts exactly the permanents it
        # would be allowed to choose. An unfiltered "destroy target permanent"
        # carries an empty filter and matches them all.
        destroyable = [
            perm for perm in game.controlled_by(target)
            if permanent_matches_filter(perm, destroy_filter)
        ]
        return 2.0 + len(destroyable) * 1.5

    if "target opponent" in text:
        score += 3.0 if target_index != caster_index else -10.0
    if "target player" in text and "draw" not in text and damage == 0 and "gain" not in text:
        score += 0.5 if target_index != caster_index else 0.0

    if card.primary_type == "creature" and target_index == caster_index:
        score += 1.0

    # 2-player-specific nudge: don't bother if the (only) other player already
    # lost. Not generalized for 3+ players — no single well-defined "other".
    if len(game.players) == 2:
        other = game.players[1 - target_index]
        if other.life <= 0:
            score -= 1.0

    return score


def _score_cast(game: Game, caster_index: int, card: CardDefinition, target_index: int, x_value: int | None) -> float:
    caster = game.players[caster_index]
    opponent_index = choose_attack_target(game, caster_index)
    opponent = game.players[opponent_index]

    if card.primary_type == "land":
        untapped_lands = sum(
            1
            for perm in game.controlled_by(caster)
            if perm.card.primary_type == "land" and not perm.tapped
        )
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

    score += _score_spell_target(card, caster_index, target_index, game, x_value)

    if x_value is not None:
        score += min(4.0, x_value * 0.6)

    # Card advantage: the cards this spell draws, less the one spent casting it.
    # The weight is tuning; which cards it applies to is not, and it used to be
    # a flat +8.0 for one name — worth exactly 4.0 per net card at the three
    # that name draws, and nothing at all to every other draw spell.
    drawn = cards_drawn_by_target(card, x_value)
    if drawn is not None:
        score += 4.0 * (drawn - 1)
        # Never self-target a draw that outruns the library: CR 704.5b on the
        # next draw step.
        if target_index == caster_index and len(caster.library) <= drawn:
            return -100.0

    # Burn that closes the game outranks everything. The threshold used to read
    # ``card.name == "Lightning Bolt" and opponent.life <= 3`` — which is that
    # card's damage spelled out, so any other lethal burn spell got nothing.
    damage = _extract_damage(card) or _estimate_x_damage(game, caster, card)
    if damage > 0 and target_index == opponent_index and opponent.life <= damage:
        score += 12.0

    # A mana source is worth playing early when there is something to spend the
    # mana on, and worth nothing at all when mana costs are not enforced. True
    # of every Mox, Sol Ring and Basalt Monolith here; only Black Lotus was named.
    if mana_ability_amount(card) is not None:
        if game.enforce_mana_costs:
            hand_nonlands = sum(1 for hand_card in caster.hand if hand_card.primary_type != "land")
            score += 2.0 if hand_nonlands >= 2 else 0.5
        else:
            score -= 2.0

    return score


def _score_activation(
    game: Game,
    player_index: int,
    instruction: OracleInstruction,
    target_index: int,
) -> float:
    """Score one activated ability. The *source permanent* is deliberately not a
    parameter: the last thing that read it asked for its name, and everything an
    activation is worth is in the instruction it puts on the stack."""
    score = 1.0

    if instruction.kind == "deal_damage":
        amount = int(instruction.payload.get("amount", 1) or 1)
        target_player = game.players[target_index]
        effective_damage = max(0, amount - target_player.damage_prevention_pool)
        if effective_damage == 0:
            return -10.0
        score += 5.0 + effective_damage
        if target_index == choose_attack_target(game, player_index) and target_player.life <= effective_damage:
            score += 10.0
    elif instruction.kind == "draw_target_cards":
        score += 5.0 if target_index == player_index else 0.0
    elif is_mana_ability(instruction):
        score += 2.5
    elif instruction.kind == "grant_banding_to_target":
        score += 0.5
    else:
        score += 1.5

    # Drawing more cards than the library holds loses the game (CR 704.5b). This
    # was ``permanent.card.name == "Jayemdae Tome" and not library`` — that card's
    # one-card draw spelled out, so Jandor's Ring drew the AI to death.
    drawn = cards_drawn_by_controller(instruction)
    if drawn is not None and len(game.players[player_index].library) < drawn:
        return -100.0

    return score


def _choose_target_for_instruction(instruction: OracleInstruction, caster_index: int, game: Game) -> int:
    if is_mana_ability(instruction):
        # Mana goes to its controller's pool; the ability has no other target.
        return caster_index
    if instruction.kind in {"draw_target_cards", "gain_life", "prevent_damage"}:
        return caster_index
    # "deal_damage"/"destroy_target"/etc., and the fallback for any other
    # proactive effect: target an opponent (MVP heuristic, see
    # choose_attack_target — lowest life among living opponents).
    return choose_attack_target(game, caster_index)


def _estimate_x_damage(game: Game, caster: PlayerState, card: CardDefinition) -> int:
    """Estimate the damage an X-damage spell would deal, based on the most X the
    caster can currently pay for. Returns 0 for spells that don't deal X damage."""
    program = compile_card_oracle(card)
    deals_x_damage = any(
        instruction.kind == "deal_damage"
        and str(instruction.payload.get("amount")).lower() == "x"
        for instruction in program.instructions
    )
    if not deals_x_damage:
        return 0
    return _max_affordable_x(game, caster, card)


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
    # caster_index doesn't affect any registered cost modifier today (Gloom
    # taxes by the card's own color); 0 is a safe placeholder.
    tax, _names = spell_cost_tax(game, 0, card)
    return tax


def _pick_x_value(game: Game, player: PlayerState, card: CardDefinition) -> int | None:
    if "{X}" not in card.mana_cost.upper():
        return None

    max_x = _max_affordable_x(game, player, card)
    return max_x


def _max_affordable_x(game: Game, player: PlayerState, card: CardDefinition) -> int:
    pool = _preview_pool_with_all_untapped_lands(game, player)
    extra_tax = _extra_generic_tax(game, card)

    x_color = x_spend_color_from_text(card.oracle_text)
    for x_value in range(15, -1, -1):
        required = game._parse_mana_cost(card.mana_cost, x_value=x_value, extra_generic=extra_tax, x_color=x_color)
        if _can_pay_cost(pool, required, player.can_spend_white_as_red):
            return x_value
    return 0


def _preview_pool_with_all_untapped_lands(game: Game, player: PlayerState) -> dict[str, int]:
    pool = {symbol: player.mana_pool.get(symbol, 0) for symbol in _MANA_SYMBOLS}
    for permanent in game.controlled_by(player):
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

    # Layer 4 already knows which basic land types this permanent currently
    # has, printed or granted by a type-changing effect.
    symbols = permanent.basic_land_mana
    return symbols[0] if symbols else "C"
