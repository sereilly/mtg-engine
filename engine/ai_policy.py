from __future__ import annotations

from dataclasses import dataclass
import re

from .ai_valuation import (
    SPELL_TYPES,
    cards_drawn_by_controller,
    cards_drawn_by_target,
    caster_sacrifice_steps,
    castable_commanders,
    counters_a_spell,
    denies_its_target,
    destroyed_permanent_filter,
    divided_shape,
    hand_entry_steps,
    instruction_target_side,
    is_mana_ability,
    mana_ability_amount,
    returns_creature_to_hand,
    several_target_slot_sides,
    spell_denies_its_own_target,
    spell_hand_pick_entry_filters,
    spell_target_side,
    TollLoss,
    toll_branch_loss,
)
from .activation_permissions import activation_permission_denial
from .auras import controller_cast_ban
from .cast_costs import cast_announces_x
from .cast_restrictions import global_cast_ban
from .legality import targeting_ban_refusal
from .cast_restrictions import check_cast_timing
from .cost_modifiers import (cost_reduction_for_cast, reduce_cost,
                             spell_cost_tax, spell_symbol_tax)
from .classifier import classify_card
from .game import Game
from .handlers._common import permanent_matches_filter
from .mixins.stack import (aura_enchant_noun, enchant_noun_seat,
                           permanent_matches_enchant_noun)
from .target_restrictions import forbidden_target
from .auras import aura_restriction_active
from .combat_permissions import MUST_BLOCK_ATTACKERS_UNTIL_EOT
from .models import CardDefinition, Permanent, PlayerState
from .oracle import OracleInstruction, compile_card_oracle
from .oracle_types import cost_target_count, x_spend_colors_from_text
from .search_filters import search_matches, searched_seat
from .subject_filters import subject_matches
from .activation_zones import HAND
from .targeting import (bounce_subject_filter, derive_activation_spec,
                        derive_cast_spec, spec_roles,
                        usable_activated_abilities)

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
    # The same choices as stable ids, when the slots do not all sit on one
    # battlefield. ``target_permanent_index`` is positional on
    # ``target_player_index``, so a two-board pick (Rookie Mistake's "target
    # creature … another target creature") cannot be expressed by it — the gap
    # round 40 closed on the wire, arriving here through the AI.
    target_permanent_ids: list[int] | None = None
    # Which zone ``hand_index`` indexes into, in the vocabulary the cast path
    # already speaks ("hand" / "command", `_cast_onto_stack`'s `from_zone`).
    # "command" is a commander cast (CR 903.8); every executor forwards it
    # unchanged, so an ordinary duel — where nothing but "hand" is ever
    # proposed — is untouched.
    from_zone: str = "hand"
    # CR 118.9: pay the spell's printed alternative cost rather than its mana
    # cost. False on every candidate this policy builds from a payable mana
    # cost, which is all of them but one shape — see `_alternative_cost_cast`.
    alternative_cost: bool = False
    # CR 601.2d's announcement, for a spell that divides damage or counters
    # among its targets: ``(seat, permanent index or None[, share])`` per
    # target, the same list the browser's division prompt sends. The field did
    # not exist, so **every** divided spell the AI cast announced no division at
    # all — Spoils of War, Contagion and Bounty of the Hunt resolved putting no
    # counters anywhere, and Pyrokinesis, Fire Covenant and Dwarven Catapult,
    # which name only creatures, dealt their damage to a player's face. See
    # `choose_divided_targets`.
    divided_targets: list[tuple] | None = None
    # The colour to ask each land in ``land_tap_indices`` for, position for
    # position (`_plan_land_taps`). The tap seam takes one
    # (`tap_land_for_mana(chosen_color=…)`) and every executor sent the default
    # "G", so a dual or a land under Harvest Mage made whatever that default
    # mapped to rather than what the plan had counted on. Empty means no
    # colour was planned, and an executor keeps the seam's default.
    land_tap_colors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActivationAction:
    permanent_name: str
    permanent_index: int
    target_player_index: int
    land_tap_indices: tuple[int, ...]
    score: float
    # The chosen permanent on `target_player_index`'s battlefield, for an
    # ability that targets one (an equip's creature). None for the abilities
    # whose handlers pick for themselves, which is every other one this policy
    # activates today.
    target_permanent_index: int | None = None
    # One chosen object per **role**, for an ability naming several targets of
    # different kinds (Goblin Welder's artifact and artifact card). The field
    # beside this one cannot carry them: they may sit on two battlefields, or —
    # here for the first time — in two different *zones*, which one seat and one
    # index cannot say. None for every other ability.
    target_role_refs: list[dict] | None = None
    # See `CastAction.land_tap_colors`.
    land_tap_colors: tuple[str, ...] = ()


@dataclass(frozen=True)
class HandActivationAction:
    """An ability activated from a card **in the seat's hand** (CR 113.6j).

    Cycling (CR 702.29a) is why this exists: 34 of Urza's Saga's cards compile
    to "[Cost], Discard this card: Draw a card.", and every one of them is a
    card an AI seat holds and never plays. A seat with no way to reach the hand
    is a seat doing nothing with a third of the set — the same shape a refused
    cast makes, but quieter, because nothing is even proposed.

    A separate action from :class:`ActivationAction` rather than a nullable
    field on it, because the two are executed by different engine entry points
    (``activate_from_hand`` takes no permanent, no target and no summoning
    sickness) and every existing reader of ``ActivationAction`` would have had
    to learn which shape it was holding.
    """

    card_name: str
    hand_index: int
    ability_index: int
    land_tap_indices: tuple[int, ...]
    score: float
    # See `CastAction.land_tap_colors`.
    land_tap_colors: tuple[str, ...] = ()


def planned_tap_color(action, position: int) -> str:
    """The colour an executor asks the *position*-th planned land for.

    The plan's own colour where it has one (``land_tap_colors``), and otherwise
    the tap seam's default, which is what every executor sent before the plan
    carried colours — so an action built without them taps exactly as it did.
    """
    colors = getattr(action, "land_tap_colors", ()) or ()
    return colors[position] if position < len(colors) else "G"


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


#: What casting from the command zone is worth over casting the same card from
#: hand: a net card. A command-zone cast spends nothing from hand — the
#: commander is CR 903.8's standing extra card — and `_score_cast` already
#: prices a net card at 4.0 (its draw weight), so the same number is used
#: rather than a second opinion about what a card is worth. The tax needs no
#: weight of its own: it is generic mana in the cost, so an unaffordable recast
#: is skipped by the tap planner exactly as any other unaffordable spell is.
COMMAND_ZONE_CAST_BONUS = 4.0


def choose_cast_action(game: Game, player_index: int) -> CastAction | None:
    best: CastAction | None = None
    for hand_index, card in enumerate(game.players[player_index].hand):
        candidate = _cast_candidate(game, player_index, card, hand_index)
        if candidate is not None and _is_better_cast(candidate, best):
            best = candidate

    # CR 903.8: the seat's commander is castable from the command zone, and an
    # AI seat that never read that zone sat its commander there for the whole
    # game. Which casts are on offer is `ai_valuation.castable_commanders` —
    # the engine's own seam, empty outside a Commander game — and the tax
    # arrives as extra generic in the cost, the same way the cast path charges
    # it, so affordability is judged against what will actually be paid.
    for zone_index, card, tax in castable_commanders(game, player_index):
        candidate = _cast_candidate(
            game, player_index, card, zone_index,
            from_zone="command", extra_generic=tax,
        )
        if candidate is not None and _is_better_cast(candidate, best):
            best = candidate

    return best


def _cast_candidate(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    *,
    from_zone: str = "hand",
    extra_generic: int = 0,
) -> CastAction | None:
    """The `CastAction` casting *card* from *from_zone* would be, or None when
    the cast is illegal, unaffordable or has nothing legal to point at.

    One body for the hand and the command zone (CR 903.8), because everything
    it checks is about the *card* and the board rather than about the zone:
    the zone contributes only where the executor finds the card (`from_zone`,
    `hand_index`) and what the cast additionally costs (*extra_generic*, the
    commander tax).
    """
    player = game.players[player_index]
    if (
        card.primary_type == "land"
        and game.enforce_mana_costs
        and not game._may_play_another_land(player_index)
    ):
        return None
    if not _can_cast_with_targets(game, player_index, card):
        return None
    # CR 601.2's printed timing gates ("Cast this spell only during an
    # opponent's turn…"), through the table the cast path itself reads.
    # Asked here for the same reason every other gate in this function is:
    # a cast the engine will refuse is a turn the AI spends on nothing, and
    # it re-proposes the same card the next turn and the next. Siren's Call
    # did exactly that for ten consecutive turns once the simulator started
    # dealing whole sets.
    if check_cast_timing(game, player_index, (card.oracle_text or "").lower()):
        return None

    # X first: an X-draw spell's target choice depends on how many cards it
    # would draw (a spell that empties your own library is aimed elsewhere),
    # so the value has to exist before the target is picked.
    x_value = _pick_x_value(game, player, card, extra_generic, hand_index=hand_index)
    if x_value == 0:
        return None

    # CR 601.2h's printed **additional** costs, asked of the engine's own gate
    # for the reason every gate above is asked here: the cast path refuses a
    # spell whose additional cost the board cannot pay, nothing is spent, and
    # the AI re-proposes the same card every turn — which is precisely what
    # `simulate_ai_games.py`'s `refused_casts` counts.
    #
    # Below the X pick, because one of those costs is measured in X (Fire
    # Covenant's "pay X life") and asking before the announcement would gate on
    # a number nobody had chosen — the same ordering the cast path itself makes,
    # and for the same reason.
    #
    # This gap predates the narrowed discard that surfaced it: Village Rites
    # with no creature to sacrifice had the same shape and was refused ten turns
    # running. What made it visible was Surge of Strength, whose "discard a red
    # or green card" became payable-or-not the moment the clause was read at all.
    if not _printed_costs_are_payable(
        game, player_index, card, hand_index, from_zone, x_value
    ):
        return None
    target = _choose_target_for_spell(card, player_index, game, x_value)
    target_permanent_index: int | list[int] | None = None
    target_permanent_ids: list[int] | None = None
    divided_targets: list[tuple] | None = None
    if aura_enchant_noun(card) is not None:
        aura_choice = _choose_aura_target(game, player_index, card)
        if aura_choice is None:
            return None  # Aura spells require a legal target (Rule 115.1b)
        target, target_permanent_index = aura_choice
    elif (divided := choose_divided_targets(game, player_index, card, x_value)) is not None:
        # CR 601.2d, and it is the *whole* target choice for a divided spell —
        # asked before the two choosers below rather than beside them, because
        # Contagion and Bounty of the Hunt print a target count and so reach
        # `_choose_several_targets`, which would put a second, unrelated list of
        # targets on the same cast. The division is what the handler reads.
        if not divided:
            # No lawful announcement exists (CR 601.2d wants one target or
            # more). Skipped rather than cast: the cast gate refuses it, and a
            # seat that re-proposes a refused card every turn is what
            # `simulate_ai_games.py`'s `refused_casts` counts.
            return None
        divided_targets = list(divided)
    else:
        roles = _choose_role_targets(game, player_index, card)
        if roles is not None:
            if roles == ():
                # A roles spell with no legal chain of targets. Skipped
                # rather than cast: CR 601.2c needs every role filled, and
                # the cast gate would refuse it — an AI turn spent on an
                # action the game then rejects.
                return None
            target, target_permanent_index, target_permanent_ids = roles
        else:
            several = _choose_several_targets(game, player_index, card)
            if several is not None:
                target, target_permanent_index, target_permanent_ids = several
            else:
                single = _choose_single_object_target(game, player_index, card, target)
                if single == ():
                    # The side the effect wants holds no legal target, so the
                    # cast would resolve doing nothing — or doing it to the
                    # caster's own permanent. Skipped rather than proposed.
                    return None
                if single is not None:
                    target, target_permanent_index, target_permanent_ids = single
    if not _caster_can_make_its_sacrifices(game, player_index, card):
        # "Sacrifice a creature. Rupture deals damage equal to that creature's
        # power…": with nothing to sacrifice the whole resolution is nothing.
        return None
    if not _caster_holds_a_hand_pick_entrant(game, player_index, card, hand_index):
        # "Each player chooses a card in their hand. … The owner of each
        # creature card revealed this way with the lowest mana value puts it
        # onto the battlefield." With no creature card of its own to pick, the
        # caster's Stronghold Gambit can only hand the opponent a free one.
        return None
    tap_indices: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()

    alternative_cost = False
    if game.enforce_mana_costs and card.primary_type != "land":
        required = _cost_for(game, player, card, x_value, extra_generic=extra_generic)
        plan = _plan_land_taps(game, player, required)
        if plan is None:
            # CR 118.9: the mana cost is not the only price. A spell whose
            # printed alternative cost this board *can* pay is castable right
            # now, and a seat that only ever asked the mana question sat on
            # Force of Will all game — the same "does nothing for the rest of
            # the game" shape `refused_casts` counts, one step earlier, where
            # nothing is even proposed.
            #
            # Asked only when the mana cost cannot be paid, which is the
            # conservative reading of CR 118.9b's "generally optional": paying a
            # life and exiling a card is a real price, and a seat that took it
            # while holding the mana would be spending two resources to save
            # none.
            if not _alternative_cost_is_payable(game, player_index, card, hand_index):
                return None
            alternative_cost = True
        else:
            tap_indices, tap_colors = plan

    score = _score_cast(game, player_index, card, target, x_value)
    if from_zone == "command":
        score += COMMAND_ZONE_CAST_BONUS
    return CastAction(
        card_name=card.name,
        target_player_index=target,
        x_value=x_value,
        land_tap_indices=tap_indices,
        score=score,
        hand_index=hand_index,
        target_permanent_index=target_permanent_index,
        target_permanent_ids=target_permanent_ids,
        from_zone=from_zone,
        alternative_cost=alternative_cost,
        divided_targets=divided_targets,
        land_tap_colors=tap_colors,
    )


def _printed_costs_are_payable(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    from_zone: str,
    x_value: int | None,
) -> bool:
    """Whether *card*'s printed additional costs (CR 601.2b) can be paid now.

    Asked of ``_unpayable_additional_cost`` rather than re-derived, for the
    reason :func:`_alternative_cost_is_payable` beside it gives: a policy that
    judged a cost by its own reading would propose casts the cast path then
    refuses. The gate is pure — it spends nothing and moves nothing — so asking
    it here cannot leave a half-paid cost behind.

    The costs are filtered by zone first, exactly as ``queue_from_hand`` filters
    them: a cost naming a zone is a price for casting from *that* zone, so a
    hand cast must not be gated on the graveyard price of the same card
    (Demonic Embrace).
    """
    from .cast_costs import additional_costs

    printed = tuple(
        cost for cost in additional_costs(card)
        if cost.from_zone is None or cost.from_zone == from_zone
    )
    if not printed:
        return True
    return game._unpayable_additional_cost(
        player_index, card, printed,
        spell_hand_index=hand_index if from_zone == "hand" else None,
        from_zone=from_zone,
        x_value=x_value,
    ) is None


def _alternative_cost_is_payable(
    game: Game, player_index: int, card: CardDefinition, hand_index: int
) -> bool:
    """Whether *card*'s printed alternative cost (CR 118.9) can be paid now.

    Asked of the engine's own gate rather than re-derived here, for the reason
    every other affordability question in this policy is: a policy that judged
    a cost by its own reading would propose casts the cast path then refuses,
    and `refused_casts` counts exactly that.

    The gate is a pure predicate over the board — it spends nothing and moves
    nothing — so asking it here costs a lookup and cannot leave a half-paid
    cost behind.
    """
    # Printed **and** granted (Dream Halls' board-wide offer), through the one
    # reader the cast path itself asks. A policy reading only the printed half
    # would be a second answer to "what may this be paid with", and the
    # direction it fails in is a seat that holds a castable spell all game --
    # which is the shape this function was written for in the first place.
    printed = game.applicable_alternative_costs(player_index, card)
    if len(printed) != 1:
        # None to take, or more than one and CR 118.9a lets only one be
        # applied — a choice this policy has no card to make and the cast path
        # refuses outright.
        return False
    return game._unpayable_alternative_cost(
        player_index, card, printed[0], spell_hand_index=hand_index,
    ) is None


def choose_activation_action(game: Game, player_index: int) -> ActivationAction | None:
    player = game.players[player_index]

    best: ActivationAction | None = None
    for permanent_index, permanent in enumerate(player.battlefield):
        if permanent.tapped or permanent.card.primary_type == "land":
            continue
        if game._is_summoning_sick(permanent):
            continue

        program = compile_card_oracle(permanent.card)
        # The shared reader, not a third copy of its predicate: it carries
        # CR 113.6's zone read, so a cycling creature's "{2}, Discard this card:
        # Draw a card." is not on this list at all. Open-coded, the policy
        # proposed it every main phase and the engine ran it — a free repeatable
        # draw for a card that was never discarded, on eight of Urza's Saga's
        # creatures. It is also the list `activation_target_spec` narrows by,
        # which the `ability_index=0` below already assumes.
        ability = next(iter(usable_activated_abilities(program)), None)
        if ability is None or ability.instruction is None:
            continue

        # A mana ability is activated to *pay* for something (_plan_land_taps
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
        if ability.cost.sacrifice_filter is not None or ability.cost.discard_cards:
            # A conjoined sacrifice ("a creature **and a Swamp**", Viscerid
            # Drone) is covered by the clause above rather than by a second
            # test: the charger never fills `sacrifice_also_filter` without
            # `sacrifice_filter`, so a second condition would be unreachable
            # and would read as a claim that it is not.
            continue

        # "Put a -1/-1 counter on a creature you control" (Wandering Mage). The
        # same trade one resource over, and the same reason the policy cannot
        # price it: the score below reads the *effect*, so a shield bought by
        # permanently shrinking a creature reads as free — and the AI would pay
        # it every main phase until its own board is gone. Derived from the
        # compiled cost, so it names no card.
        if ability.cost.put_counter_filter is not None:
            continue

        # "Remove a +1/+1 counter from a creature you control" (Spike Rogue).
        # The same trade in the opposite direction and the same reason the
        # policy cannot price it: the score below reads the *effect*, so moving
        # a counter from one creature to another reads as a free +1/+1 — and
        # the AI would shuttle its board's counters onto the Spike every main
        # phase for no net gain. Derived from the compiled cost, so it names no
        # card. The self-referring spelling is left alone: that one is priced by
        # the source's own counters, which the score does read.
        if ability.cost.remove_counter_filter is not None:
            continue

        # "Exile the top card of your library" (Royal Herbalist, Phyrexian
        # Devourer). The same floor one zone over, and the sharper case for it:
        # the resource spent is the seat's remaining turns (CR 704.5b — a player
        # who would draw from an empty library loses), which this policy has no
        # term for at all. Left in, a seat with two mana gains 1 life every turn
        # until it decks itself, which is a loss traded for nothing.
        if ability.cost.exile_top_of_library:
            continue

        # "Exile the top creature card of your graveyard" (Necratog, Zombie
        # Scavengers), "…the top card…" (Alms, Nature's Kiss). The same floor
        # one zone over, with a second reason the library cost does not have:
        # the cost **scans** the pile, so an activation the policy proposes
        # against a graveyard holding no matching card is refused with nothing
        # spent — and the policy would propose it again next turn, and every
        # turn after, which is the "a seat doing nothing all game" shape a
        # refused action makes. Derived from the compiled cost, so it names no
        # card.
        if ability.cost.exile_graveyard_position is not None:
            continue

        # CR 602.1a and its exceptions: a permanent whose printed permission
        # closes its ability to *its own controller* — "Only your opponents may
        # activate this ability" (Clergy of the Holy Nimbus), "Only the
        # controller of the enchanted creature…" (Merseine) — is an ability
        # this seat may not activate at all. Asked of the module that enforces
        # it rather than scored, so the answer is the engine's own; without it
        # the policy proposed the same refused activation every turn for the
        # whole game, which is the "a seat doing nothing all game" shape a
        # refused action makes.
        if activation_permission_denial(
            game, player_index, permanent, ability.source_line or ""
        ):
            continue

        # "Pay enchanted creature's mana cost" (Merseine). A cost the compiled
        # program cannot state — it is whatever the attached permanent's
        # printed cost is right now — so the tap planner below has nothing to
        # plan against. Skipping is the same honest floor the cost skips above
        # take, and it is derived from the compiled cost, so it names no card.
        if ability.cost.mana_from_attached:
            continue

        target = _choose_target_for_instruction(ability.instruction, player_index, game)
        # An equip ability (CR 702.6a): the creature is chosen here, because the
        # handler declines a target it was not given rather than scanning for
        # one (a misplaced Equipment is wrong in a way a fizzled pump is not).
        # Skipped entirely when nothing is worth equipping, so the AI does not
        # pay {1} every main phase to move a sword onto the creature it is
        # already on.
        target_permanent_index: int | None = None
        if ability.instruction.kind == "attach_source_to_target":
            target_permanent_index = _choose_equip_target(game, player_index, permanent)
            if target_permanent_index is None:
                continue
        if ability.instruction.kind == "grant_banding_to_target":
            # Banding grants go to the controller's own creatures.
            target = player_index
            target_creatures = [
                perm for perm in game.controlled_by(player_index) if perm.is_creature
            ]
            if not target_creatures:
                continue

        # An object-targeted ability (Silent Dart's "deal 3 to target creature",
        # a "destroy target …") must name a legal permanent, or the activation
        # is refused with nothing paid (CR 602.2b). Derive the target the way the
        # picker does and aim it by the effect's category; skip when nothing is
        # worth (or legal) to target, so the AI does not burn a turn on an
        # ability it cannot resolve.
        spec = derive_activation_spec(ability)
        # An ability naming several targets of *different* kinds, chosen in
        # dependency order (CR 602.2b reaches CR 601.2c). Asked before the
        # single-target block below, which has no arm for it: the kind is
        # "roles", so that block leaves the announcement empty and the ability
        # goes on the stack with no targets — an activation that resolves and
        # does nothing, which is the shape `refused_casts` exists to make
        # visible one step later.
        target_role_refs: list[dict] | None = None
        if spec_roles(spec):
            target_role_refs = _choose_activation_role_targets(
                game, player_index, permanent_index
            )
            if target_role_refs is None:
                # No legal chain. Skipped rather than proposed: CR 602.2b fills
                # every role or the activation is refused with nothing paid,
                # and the gate would refuse it.
                continue
        object_kinds = {"creature", "artifact", "land", "permanent", "planeswalker"}
        if (
            target_permanent_index is None
            and spec is not None
            and spec.get("kind") in object_kinds
            and not spec.get("sacrifice_cost")
            and not spec.get("discard_cost")
        ):
            # The AI activates the first usable ability (selected above), which
            # is usable_activated_abilities()[0] — the index activation_target_spec
            # narrows by.
            legal = game.activation_target_spec(
                player_index, permanent_index, ability_index=0,
            ).get("valid_targets") or []
            perms = [t for t in legal if t.get("kind") == "permanent"]
            if not perms:
                continue
            # Which board, from what the effect does to its target
            # (`ai_valuation.instruction_target_side`) — and **only** that
            # board. This fell back to "any legal permanent" when the wanted
            # side had none, which is how a destroy, a tap or a "can't block"
            # with no opposing target landed on the activator's own creature,
            # and a pump with no friendly one landed on an opponent's: an
            # activation that resolves and harms the seat that paid for it.
            side = instruction_target_side(ability.instruction)
            if side == "you" and denies_its_target(ability.instruction):
                # "Destroy target … you control" (Rats of Rath), "Return target
                # land you control to its owner's hand" (Trade Routes): the
                # printed seat is the activator's and the effect is a denial,
                # so activating it for its own sake only costs the seat a
                # permanent. Before this the fallback above aimed Rats of
                # Rath at whatever it found.
                continue
            if side == "you":
                perms = [t for t in perms if t["seat"] == player_index]
            elif side == "opponent":
                perms = [t for t in perms if t["seat"] != player_index]
            if not perms:
                continue
            def _power(t):
                perm = game.permanent_at(t["seat"], t["index"])
                return perm.effective_power if perm is not None else 0

            chosen = max(perms, key=_power)
            target = chosen["seat"]
            target_permanent_index = chosen["index"]

        # CR 601.2d asked of an ability: a divided announcement ("…divided as
        # you choose", Serra's Hymn) is one this chooser never makes, and the
        # engine refuses an activation announced without it — so proposing one
        # is a turn spent on a refusal, every turn. Then the engine's own
        # announcement gate (CR 602.2b/601.2c) over exactly what this policy is
        # about to announce: an ability whose only legal targets are cards in
        # an empty graveyard (Rootwater Diver, Groundskeeper) passed every
        # check above, because they look only at battlefield targets, and was
        # refused with nothing paid. Neither shows in `refused_casts`, which
        # counts casts; one ten-game run each of USG, TMP and MMQ logged 44
        # refused Serra's Hymn, 21 Rootwater Diver and 15 Groundskeeper
        # activations.
        if spec is not None and spec.get("kind") == "divided":
            continue
        # "{3}, {T}: You may put a creature card of the chosen type from your
        # hand onto the battlefield." With no such card in hand the ability's
        # whole effect is nothing, and the cost is still paid: Belbe's Portal
        # spent {3} every turn of NEM's simulation to log that it had no card.
        if not _hand_entry_has_a_card(game, player_index, permanent, ability.instruction):
            continue
        if game.activation_target_refusal(
            player_index, permanent, ability,
            target_player_index=target,
            target_permanent_index=target_permanent_index,
            target_role_refs=target_role_refs,
        ) is not None:
            continue

        land_taps: tuple[int, ...] = ()
        tap_colors: tuple[str, ...] = ()
        required = dict(ability.cost.mana)
        if game.enforce_mana_costs and any(required.values()):
            plan = _plan_land_taps(game, player, required)
            if plan is None:
                continue
            land_taps, tap_colors = plan

        score = _score_activation(game, player_index, ability.instruction, target)
        if score <= 0.0:
            continue
        candidate = ActivationAction(
            permanent_name=permanent.card.name,
            permanent_index=permanent_index,
            target_player_index=target,
            land_tap_indices=land_taps,
            score=score,
            target_permanent_index=target_permanent_index,
            target_role_refs=target_role_refs,
            land_tap_colors=tap_colors,
        )
        if best is None or candidate.score > best.score:
            best = candidate

    return best


def _choose_activation_role_targets(
    game: Game, player_index: int, permanent_index: int
) -> "list[dict] | None":
    """One object per **role** for an activated ability, or None when no legal
    chain exists.

    ``_choose_role_targets``' twin on the activation side, and it is a twin
    rather than a shared body for the reason the two specs are derived
    separately: a spell's roles come from the card and an ability's from *that
    ability* (CR 602.2b), so the walks start from different calls. What they
    share is the policy — take the first option at each level — and it is safe
    for that function's stated reason: a first choice that leaves a later role
    with nothing is not in the list ``_role_target_walk`` returns.

    The answer is in the wire's own shape (``target_role_refs``) because a role
    here may be a card in a graveyard, which has no permanent id to send.
    """
    options = game.activation_target_spec(
        player_index, permanent_index, ability_index=0,
    ).get("valid_targets") or []
    refs: list[dict] = []
    while options:
        pick = options[0]
        if pick.get("kind") == "graveyard":
            refs.append({
                "graveyard_seat": pick.get("seat"),
                "graveyard_index": pick.get("index"),
            })
        else:
            permanent = game.permanent_at(pick.get("seat"), pick.get("index"))
            permanent_id = game.permanent_id_of(permanent)
            if not isinstance(permanent_id, int):
                return None
            refs.append({"permanent_id": permanent_id})
        options = pick.get("next") or []
    return refs or None


def choose_hand_activation_action(
    game: Game, player_index: int
) -> HandActivationAction | None:
    """The best ability this seat can activate from its **hand**, or None.

    Cycling, and whatever else prints a cost payable only from a hand
    (CR 113.6j). Which abilities those are is not decided here — it is
    ``usable_activated_abilities(program, zone=HAND)``, the same reader
    ``Game.activate_from_hand`` gates on and the same one that keeps the ability
    off a permanent's list — so this policy names no card and no keyword.

    Called **after** the seat's cast for the turn, so the untapped lands the
    payment is planned against are the mana the cast did not want: a seat
    cycles with what is left over rather than instead of playing its spell.

    One action per call, like :func:`choose_activation_action`, and the tie-break
    is hand order — the seat cycles once a priority pass rather than emptying
    its hand in a loop, and a seeded run reproduces exactly.
    """
    player = game.players[player_index]
    best: HandActivationAction | None = None
    for hand_index, card in enumerate(player.hand):
        program = compile_card_oracle(card)
        from_hand = usable_activated_abilities(program, zone=HAND)
        if not from_hand:
            continue
        ability = from_hand[0]
        if ability.instruction is None:
            continue

        # A mana ability activated for its own sake empties at the end of the
        # step; the same floor `choose_activation_action` keeps one zone over.
        if is_mana_ability(ability.instruction):
            continue

        # Any cost beyond mana and the discard the zone read is derived from is
        # a trade this policy cannot price — the same honest floor the
        # battlefield loop takes, and derived from the compiled cost so it
        # names no card.
        cost = ability.cost
        if (
            cost.sacrifice_filter is not None
            or cost.discard_cards
            or cost.pay_life
            or cost.exile_top_of_library
        ):
            continue

        land_taps: tuple[int, ...] = ()
        # The cost as CR 601.2f computes it, through the same reader
        # ``Game.activate_from_hand`` charges: a Fluctuator on the board makes
        # a Cycling {2} free, and a policy pricing the printed cost would pass
        # over an ability the engine would let it take for nothing.
        from .mixins.stack.activation import hand_activation_cost

        tap_colors: tuple[str, ...] = ()
        required = hand_activation_cost(game, player_index, card, ability)[0]
        if game.enforce_mana_costs and any(required.values()):
            plan = _plan_land_taps(game, player, required)
            if plan is None:
                continue
            land_taps, tap_colors = plan

        # The seat is the target: nothing activatable from a hand in the pool
        # aims anywhere else, and an ability that did would be refused at
        # announcement rather than aimed by this policy.
        score = _score_activation(game, player_index, ability.instruction, player_index)
        if score <= 0.0:
            continue
        candidate = HandActivationAction(
            card_name=card.name,
            hand_index=hand_index,
            ability_index=0,
            land_tap_indices=land_taps,
            score=score,
            land_tap_colors=tap_colors,
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


def _legal_declaration(
    game: Game, attacking_player_index: int, chosen: list[int],
    *, against: int | None = None,
) -> list[int]:
    """*chosen*, pruned until the **declaration** itself is legal (CR 508.1c).

    `legal_attackers` above is a per-creature predicate, and a restriction can
    be about the set: "can only attack alone" (Errantry), "can't attack unless
    at least two other creatures attack" (Orcish Conscripts). Proposing a set
    that disobeys one is not a partial failure — `declare_attackers` refuses the
    **whole** declaration, so a Conscripts beside one Bear kept the Bear home
    too, and the seat attacked with nobody all game.

    The rule is asked of the engine rather than re-read here: a second copy in
    the AI would drift from the one the declaration enforces, and the direction
    it would drift is a seat that stops attacking for reasons the rules do not
    give. The engine names the offending permanent, which is what makes this a
    prune rather than a search — each pass drops exactly one creature, so it
    terminates.

    **Which one it names is the caller's business for a cap.** "No more than two
    creatures can attack" (Caverns of Despair, Crawlspace) is disobeyed by the
    set rather than by any member of it, so the engine names the *last* attacker
    in the list it was handed — a rule cannot say which creature the attacker
    would rather keep, and inventing an answer there would put AI valuation
    inside the rules engine. So the list is handed over weakest-last, and the
    surviving indices come back in their original order, which is what makes
    this a cap the AI attacks *under* rather than one it attacks *through*.

    *against* is the seat this declaration is aimed at, which the per-defender
    cap needs and the global one does not. It matters only at a table with more
    than two living players: with one opponent the engine fills it in, and with
    several it cannot guess, so a free-for-all declaration would be pruned
    against the global cap alone and then refused whole for the other.
    """
    # Through the seam (`permanent_at`), which is where an index becomes a
    # permanent: the AI carries slots because that is what the declaration takes,
    # and a raw `battlefield[i]` here would be a second place that has to be
    # right about what a slot means.
    pruned = [
        (idx, game.permanent_at(attacking_player_index, idx)) for idx in chosen
    ]
    pruned = [(idx, perm) for idx, perm in pruned if perm is not None]
    # Descending value, so the engine's "last one" is the one this seat can most
    # afford to leave home. Only the order of the *question* changes; the answer
    # is a set, and it is returned in the caller's order below.
    pruned.sort(key=lambda entry: -_permanent_value(entry[1]))
    while pruned:
        # **What the declaration costs is pruned against too, and it was not.**
        # CR 508.1g's costs are summed over the whole declaration
        # (`_declaration_mana_plan`, `_declaration_sacrifice_plan`), where
        # `legal_attackers` above can only ask "could this seat afford *this*
        # creature". So a seat with one land under a {1}-per-attacker toll
        # proposed three attackers, the declaration refused all three, and
        # `ai_combat`'s superset fallback — every legal attacker, the same
        # three — was refused for the same reason: the seat attacked with
        # nobody while it could plainly have attacked with one. Measured on
        # War Tax and true of every shipped card that prints a summed
        # declaration cost (Koskun Falls, Elephant Grass, Propaganda,
        # Brainwash, Leviathan, Flooded Woodlands, Reclamation).
        #
        # Asked of the engine's own planners rather than re-totalled here, for
        # the restriction loop's stated reason: a second copy would drift, and
        # the direction it drifts is a seat that stops attacking for reasons
        # the rules do not give. Weakest-last ordering means the creature
        # dropped is the one this seat can most afford to leave home, exactly
        # as it is for a cap.
        unaffordable = _unaffordable_attacker(
            game, attacking_player_index, [perm for _idx, perm in pruned], against
        )
        if unaffordable is not None:
            pruned = [
                (idx, perm) for idx, perm in pruned if perm is not unaffordable
            ]
            continue
        refusal = game.attack_declaration_refusal(
            [perm for _idx, perm in pruned],
            # Who this seat is aiming at, when the caller knows. Omitting it is
            # only safe at a table with one living opponent, where the engine
            # fills it in; `choose_attackers` picks a single target even in a
            # free-for-all, so a per-defender cap (Crawlspace) at *that* seat
            # would otherwise be invisible here and the whole declaration would
            # be refused again — the exact failure this prune exists to stop.
            defenders=(
                None if against is None
                else {perm.permanent_id: against for _idx, perm in pruned}
            ),
        )
        if refusal is None:
            break
        offender, _reason = refusal
        pruned = [(idx, perm) for idx, perm in pruned if perm is not offender]
    kept = {id(perm) for _idx, perm in pruned}
    return [idx for idx in chosen if id(game.permanent_at(attacking_player_index, idx)) in kept]


def _with_conditional_requirements(
    game: Game, attacking_player_index: int, chosen: list[int], legal: list[int]
) -> list[int]:
    """*chosen*, plus every legal attacker the set itself now **requires**.

    The mirror of :func:`_legal_declaration` one rule over. That one prunes
    until a restriction stops being disobeyed; this one adds until a
    *requirement* is obeyed — "If a creature you control attacks, this creature
    also attacks if able" (Ekundu Cyclops) is conditional on the rest of the
    declaration, so a set that was legal before a creature was added can stop
    being legal because of it.

    Asked of the engine rather than re-read here, for ``_legal_declaration``'s
    reason: a second copy of the rule in the AI drifts, and the direction it
    drifts is a seat whose whole declaration is refused and which therefore
    attacks with nobody all game.

    Terminates because each pass adds at least one creature out of a finite
    list, and a set that adds nothing is stable.
    """
    picked = list(chosen)
    while True:
        declared = [
            perm for perm in
            (game.permanent_at(attacking_player_index, idx) for idx in picked)
            if perm is not None
        ]
        added = [
            idx for idx in legal
            if idx not in picked
            and game._must_attack_beside(
                game.permanent_at(attacking_player_index, idx), declared
            )
        ]
        if not added:
            return picked
        picked.extend(added)


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
        return _legal_declaration(
            game, attacking_player_index, legal_attackers_list,
            against=opponent_index,
        )

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
    chosen = _with_conditional_requirements(
        game, attacking_player_index, chosen, legal_attackers_list
    )
    chosen = _legal_declaration(
        game, attacking_player_index, chosen, against=opponent_index
    )

    # Go all-in when lethal is on the table — through the same prune, because a
    # declaration that is refused deals no damage at all. This returned the raw
    # legal set, so under either attack cap the lethal swing was refused whole
    # and the seat attacked with nobody on the turn it could have won.
    if sum(player.battlefield[i].effective_power for i in legal_attackers_list) >= opponent.life:
        return _legal_declaration(
            game, attacking_player_index, legal_attackers_list,
            against=opponent_index,
        )

    return sorted(chosen)


def _legal_block_declaration(
    game: Game,
    defending_player_index: int,
    chosen: dict[int, int | list[int]],
) -> dict[int, int | list[int]]:
    """*chosen*, pruned until the **declaration** itself is legal (CR 509.1b).

    :func:`_legal_declaration` one step of combat over, and written from the
    identical defect. ``_can_block_attacker`` is a per-pair predicate, and a
    restriction can be about the set: "no more than two creatures can block each
    combat" (Caverns of Despair), "can't block unless at least two other
    creatures block" (Orcish Conscripts, and Mogg Flunkies' "can't block
    alone"), "can't block unless a creature with greater power also blocks"
    (Okk). Proposing a map that disobeys one is not a partial failure —
    ``declare_blockers`` refuses the **whole** declaration, so the defender
    blocked with nobody, this combat and every later one, in silence.

    The rule is asked of the engine rather than re-read here, for the attack
    side's reason exactly: a second copy in the AI would drift from the one the
    declaration enforces, and the direction it drifts is a seat that stops
    blocking for reasons the rules do not give. The engine names the offending
    permanent, which is what makes this a prune rather than a search — each pass
    drops exactly one blocker, so it terminates.

    A **map**, not a list, which is the one structural difference from the
    attack side: dropping the offender means dropping a key, and the attackers
    it was assigned go with it. Everything else about that blocker's assignment
    is left alone, because a partial block is a different declaration, not a
    smaller one.

    Only this seat's own map is pruned, and only against itself: CR 802.4b
    judges each defending player's blocks with every other player's blockers
    ignored, so a second defender declaring first cannot make this one's map
    illegal.

    Which blocker the engine names for a **cap** is this function's business,
    the way it is `_legal_declaration`'s: a cap is disobeyed by the set rather
    than by any member of it, so the engine names the *last* one it was handed.
    The list therefore goes over worst-block-last — scored by the same
    `_score_block_pair` that chose the blocks — which is what makes this a cap
    the AI blocks *under* rather than one it blocks *through*.
    """
    attacker_player = game.players[game.active_player_index]
    ordered: list[tuple[int, Permanent, float]] = []
    for blocker_idx, assigned in chosen.items():
        blocker = game.permanent_at(defending_player_index, blocker_idx)
        if blocker is None:
            continue
        attacker_indices = assigned if isinstance(assigned, list) else [assigned]
        attacker = next(
            (
                perm
                for perm in (
                    game.permanent_at(attacker_player, idx)
                    for idx in attacker_indices
                )
                if perm is not None
            ),
            None,
        )
        # The value of *the block*, not of the blocker: a cap forces the seat to
        # give one up, and the one to give up is the least useful block rather
        # than the smallest creature. With no attacker resolvable there is no
        # pair to score, so the creature's own value stands in.
        score = (
            _score_block_pair(blocker, attacker)
            if attacker is not None
            else _permanent_value(blocker)
        )
        ordered.append((blocker_idx, blocker, score))
    ordered.sort(key=lambda entry: -entry[2])

    while ordered:
        # What the declaration *costs*, pruned against for the attack side's
        # reason exactly: CR 509.1d totals the costs of every chosen blocker, so
        # a defender with one land under a {1}-per-blocker toll (War Cadence)
        # would propose two blocks, have the declaration refused whole, and fall
        # through `ai_combat`'s superset rung to blocking with nobody — while it
        # could plainly have blocked with one. True of every shipped card
        # printing a summed block cost too (Hipparion, Awesome Presence, and
        # Heat Wave's life half).
        unaffordable = _unaffordable_blocker(
            game, defending_player_index, attacker_player,
            {idx: chosen[idx] for idx, _perm, _score in ordered},
            {idx: perm for idx, perm, _score in ordered},
            [perm for _idx, perm, _score in ordered],
        )
        if unaffordable is not None:
            ordered = [
                entry for entry in ordered if entry[1] is not unaffordable
            ]
            continue
        refusal = game.block_declaration_refusal(
            [perm for _idx, perm, _score in ordered]
        )
        if refusal is None:
            break
        offender, _reason = refusal
        ordered = [
            entry for entry in ordered if entry[1] is not offender
        ]
    kept = {blocker_idx for blocker_idx, _perm, _score in ordered}
    return {
        blocker_idx: assigned
        for blocker_idx, assigned in chosen.items()
        if blocker_idx in kept
    }



def _unaffordable_attacker(game, seat, attackers, against):
    """The attacker to drop when this whole declaration cannot be paid for.

    None when it can. CR 508.1h locks in a *total* cost, so affordability is a
    property of the set rather than of any member — which means, exactly as for
    a cap, that no rule can say which creature to leave home. The weakest is
    last in the list this is handed, so naming it is the same policy the
    restriction prune already applies.

    Both halves of the cost are asked, because either can be the one that does
    not fit: mana (Koskun Falls, War Tax) and sacrifice (Flooded Woodlands,
    Leviathan). Asked of the engine's own planners, so what the AI believes it
    can afford and what the declaration will charge are one answer.
    """
    if not attackers:
        return None
    seats = None if against is None else [against] * len(attackers)
    total, plan = game._declaration_mana_plan(seat, list(attackers), seats)
    if total and plan is None:
        return attackers[-1]
    if game._declaration_sacrifice_plan(seat, list(attackers)) is None:
        return attackers[-1]
    return None



def _unaffordable_blocker(
    game, defender_seat, attacker_owner, assigned, blockers, ordered_perms
):
    """The blocker to drop when this whole block declaration cannot be paid for.

    None when it can. :func:`_unaffordable_attacker`'s twin one step of combat
    over, and every word of that docstring applies: CR 509.1d locks in a total,
    affordability is a property of the set, and no rule can say which block to
    give up — so the weakest, which is last in the list handed here, is named.

    Both currencies are asked, because either can be the one that does not fit:
    mana (Hipparion, Awesome Presence, War Cadence) and life (Heat Wave,
    CR 119.4). Through the engine's own planners, so what the AI believes it can
    afford and what the declaration will charge are one answer.
    """
    if not ordered_perms:
        return None
    plan_assignments = {
        idx: (list(a) if isinstance(a, list) else [a]) for idx, a in assigned.items()
    }
    resolved_attackers = {}
    for attacker_indices in plan_assignments.values():
        for attacker_idx in attacker_indices:
            perm = game.permanent_at(attacker_owner, attacker_idx)
            if perm is not None:
                resolved_attackers[attacker_idx] = perm
    life_owed = game._block_declaration_life(
        plan_assignments, blockers, resolved_attackers
    )
    if life_owed and game.players[defender_seat].life < life_owed:
        return ordered_perms[-1]
    total, plan = game._block_declaration_mana_plan(
        defender_seat, plan_assignments, blockers, resolved_attackers
    )
    if total and plan is None:
        return ordered_perms[-1]
    return None


def choose_combat_blockers(
    game: Game,
    defending_player_index: int,
    *,
    ignore_substitution: bool = False,
) -> dict[int, int | list[int]]:
    """The blocks an AI seat declares for *defending_player_index*.

    ``ignore_substitution`` asks for the defender's *own* best blocks even while
    another seat is choosing (see the Melee note below) — the fallback for when
    the empty declaration a substituted chooser wants is itself illegal, because
    a blocking requirement (Lure) compels a block. An illegal-but-preferred
    answer is no answer at all, and the alternative is the safety valve that
    wipes every seat's blocks.
    """
    combat = game.get_combat_state()
    if game.current_turn_phase != "combat" or game.current_step != "declare_blockers":
        return {}
    if defending_player_index not in game.combat_defending_players():
        return {}
    # "You choose which creatures block this combat and how those creatures
    # block." (Melee.) CR 509.1a's chooser is someone else, and the weights
    # below score a block for the *defender* — handed to an opponent making the
    # choice they would pick the blocks that best defend the seat they are
    # attacking. Every printing of this substitution is cast by the attacking
    # player, so the honest answer is the one the card is played for: block with
    # nothing. Asked of the seam rather than of the card, so a second printing
    # needs no weight here; if a requirement (Lure) makes the empty declaration
    # illegal, the caller falls back to the defender's own choice, which is at
    # least legal.
    chooser = game.block_chooser_index(defending_player_index)
    if (
        not ignore_substitution
        and chooser != defending_player_index
        and chooser in game.opponents_of(defending_player_index)
    ):
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
    # How many blockers each attacker needs at once, asked of the engine rather
    # than of the keyword: menace is the N=2 case of a printed template the
    # declaration gate reads through one helper (Gorilla Berserkers' "except by
    # three or more creatures"), and an AI that knew only the keyword would keep
    # submitting a declaration the gate bounces — which is a seat that declares
    # no blockers at all for the rest of the combat.
    minimum_blockers: dict[int, int] = {}
    for blocker_idx in available_blockers:
        blocker = defender.battlefield[blocker_idx]
        for attacker_idx in attackers:
            if attacker_idx < 0 or attacker_idx >= len(attacker_player.battlefield):
                continue
            attacker = attacker_player.battlefield[attacker_idx]
            minimum_blockers[attacker_idx] = game._minimum_blockers(attacker)
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

    # "Must be blocked if able" (Canopy Stalker): declare_blockers refuses a
    # declaration that leaves such an attacker unblocked while an able creature
    # stands by, so the AI assigns one — the cheapest still-free blocker, which
    # is a stated policy and not a valuation. Blocking is compulsory here, so
    # declining is not the safe fallback it is for menace below.
    for attacker_idx in attackers:
        attacker = game.permanent_at(attacker_player, attacker_idx)
        if attacker is None:
            continue
        if not any(
            i.kind == "must_be_blocked"
            for i in compile_card_oracle(attacker.effective_card).instructions
        ):
            continue
        if any(
            attacker_idx == assigned or (isinstance(assigned, list) and attacker_idx in assigned)
            for assigned in assignments.values()
        ):
            continue
        for blocker_idx in available_blockers:
            if blocker_idx in assignments:
                continue
            blocker = game.permanent_at(defender, blocker_idx)
            if blocker is not None and game._can_block_attacker(blocker, attacker):
                assignments[blocker_idx] = attacker_idx
                break

    # CR 509.1b's minimum-blocker restrictions (menace, and Gorilla Berserkers'
    # printed spelling of the same thing): declare_blockers refuses an
    # assignment that puts fewer than N blockers on such an attacker, so the AI
    # declines those blocks rather than submitting a declaration that bounces.
    # Ganging up is a valuation question for another day; not blocking is always
    # legal.
    menace_counts: dict[int, int] = {}
    for assigned in assignments.values():
        for attacker_idx in assigned if isinstance(assigned, list) else [assigned]:
            menace_counts[attacker_idx] = menace_counts.get(attacker_idx, 0) + 1
    for attacker_idx, count in menace_counts.items():
        if count >= minimum_blockers.get(attacker_idx, 1):
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

    # "Target creature blocks **this creature** this turn if able."
    # (Trumpeting Armodon.) The narrowed requirement: the mark on the blocker
    # names the attackers it owes a block to, by id. Assigned before the
    # unnarrowed Watchdog rule below, because obeying this one also obeys that
    # one — the reverse order would spend the creature on the wrong attacker
    # and leave the declaration illegal.
    for blocker_idx in available_blockers:
        if blocker_idx in assignments:
            continue
        blocker = game.permanent_at(defender, blocker_idx)
        if blocker is None:
            continue
        owed = blocker.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) or ()
        if not owed:
            continue
        for attacker_idx in attackers:
            attacker = game.permanent_at(attacker_player, attacker_idx)
            if attacker is None or attacker.permanent_id not in owed:
                continue
            if not game._can_block_attacker(blocker, attacker):
                continue
            joined = sum(
                1
                for assigned in assignments.values()
                if attacker_idx == assigned
                or (isinstance(assigned, list) and attacker_idx in assigned)
            )
            if joined + 1 < minimum_blockers.get(attacker_idx, 1):
                continue
            assignments[blocker_idx] = attacker_idx
            break

    # "This creature blocks each combat if able." (Watchdog.) CR 509.1c aimed
    # at the blocker: declare_blockers refuses a declaration that leaves such a
    # creature out while it could legally block something, so the AI assigns it
    # the first attacker it can block rather than submitting a declaration that
    # bounces every combat.
    #
    # **After the menace pruning above**, not before it: that loop strips
    # blocks that under-fill a minimum, and a compelled block stripped there
    # would leave the declaration illegal for the reason it was added. Which
    # is also why the minimum is checked here — CR 509.1c asks for the
    # requirement to be obeyed *without disobeying a restriction*, and joining
    # a menace attacker alone disobeys one.
    for blocker_idx in available_blockers:
        if blocker_idx in assignments:
            continue
        blocker = game.permanent_at(defender, blocker_idx)
        if blocker is None:
            continue
        if not any(
            i.kind == "must_block_each_combat"
            for i in compile_card_oracle(blocker.effective_card).instructions
        ):
            continue
        for attacker_idx in attackers:
            attacker = game.permanent_at(attacker_player, attacker_idx)
            if attacker is None or not game._can_block_attacker(blocker, attacker):
                continue
            joined = sum(
                1
                for assigned in assignments.values()
                if attacker_idx == assigned
                or (isinstance(assigned, list) and attacker_idx in assigned)
            )
            if joined + 1 < minimum_blockers.get(attacker_idx, 1):
                continue
            assignments[blocker_idx] = attacker_idx
            break

    # CR 509.1b's restrictions on the declaration as a whole, last — the mirror
    # of `_legal_declaration` at the tail of `choose_attackers`, and last for
    # its reason: every requirement above may still *add* a blocker, and a set
    # that was under the cap before one was added is not under it after.
    return _legal_block_declaration(game, defending_player_index, assignments)


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
        # CR 601.2d, for the same reason `_cast_candidate` asks it: Pyrokinesis
        # and Contagion are instants with an alternative cost, so this is the
        # chooser that offers them during combat — and a divided spell proposed
        # with no division is refused at announcement.
        divided = choose_divided_targets(game, player_index, card, x_value)
        if divided is not None and not divided:
            continue
        # The same "would the resolution do anything" questions the main-phase
        # chooser asks (`_cast_candidate`), for the same reasons: a one-object
        # spell names its permanent on the side the effect wants or is not
        # cast, and a spell that sacrifices what its caster lacks is not cast.
        target_permanent_index: int | None = None
        target_permanent_ids: list[int] | None = None
        if divided is None:
            single = _choose_single_object_target(game, player_index, card, target)
            if single == ():
                continue
            if single is not None:
                target, target_permanent_index, target_permanent_ids = single
        if not _caster_can_make_its_sacrifices(game, player_index, card):
            continue
        tap_indices: tuple[int, ...] = ()
        tap_colors: tuple[str, ...] = ()

        if game.enforce_mana_costs:
            required = _cost_for(game, player, card, x_value)
            plan = _plan_land_taps(game, player, required)
            if plan is None:
                continue
            tap_indices, tap_colors = plan

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
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            divided_targets=list(divided) if divided else None,
            land_tap_colors=tap_colors,
        )
        if _is_better_cast(candidate, best):
            best = candidate

    return best


def choose_search_card(
    game: Game, player_index: int, data: dict
) -> tuple[str, int] | None:
    """Pick the ``(zone, index)`` of the best card a search may find, or None to
    fail to find (CR 701.23b).

    Both the zones and the restriction come from the armed choice rather than
    from a second reading of the card: the AI is then offered exactly the cards
    a human seat is offered, and ``search_matches`` is the only thing deciding
    what is findable. An AI that filtered differently would be a second opinion
    about what the effect finds — the same bug class as a second parse.
    """
    picks = choose_search_cards(game, player_index, data, 1)
    if not picks:
        return None
    return picks[0]["zone"], picks[0]["index"]


def choose_search_cards(
    game: Game, player_index: int, data: dict, count: int
) -> list[dict]:
    """The counted search's answer: up to *count* distinct picks, best first,
    each ``{"zone": ..., "index": ...}`` the way the resolver reads them.

    A printed name is consumed by the find that used it, exactly as the
    resolver will consume it — an AI that kept offering a used name would
    submit an answer the engine then refuses, which is the fail-to-find.
    """
    from .search_filters import name_key

    # The zone the search looks in, which is not always the chooser's own —
    # see `searched_seat`. An AI reading its own graveyard for a card the
    # effect takes from someone else's would answer with an index the resolver
    # then refuses, which is the fail-to-find.
    player = game.players[searched_seat(data, player_index)]
    working = dict(data)
    picks: list[dict] = []
    taken: set[tuple[str, int]] = set()
    for _ in range(count):
        best: tuple[str, int] | None = None
        best_score = float("-inf")
        for zone in tuple(working.get("zones", ("library",))):
            cards = player.library if zone == "library" else player.graveyard
            for index, card in enumerate(cards):
                if (zone, index) in taken or not search_matches(card, working):
                    continue
                score = _score_tutor_choice(game, player_index, card)
                if best is None or score > best_score:
                    best = (zone, index)
                    best_score = score
        if best is None:
            break
        zone, index = best
        card = (player.library if zone == "library" else player.graveyard)[index]
        taken.add(best)
        picks.append({"zone": zone, "index": index})
        among = list((working.get("restrictions") or {}).get("named_among") or ())
        if among:
            working["restrictions"] = {
                **(working.get("restrictions") or {}),
                "named_among": [n for n in among if name_key(n) != name_key(card.name)],
            }
    return picks


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
    game: Game, caster_index: int, top_count: int,
    library_index: int | None = None,
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
    # Whose library is being looked through, which is not always the chooser's
    # (Coral Fighters looks at the defending player's). The score below asks
    # "how good would drawing this be **for its owner**", so over somebody
    # else's pile the answer is negated: a card that would help them is one to
    # bury, and keeping the scoring function and flipping its sign is what
    # stops this becoming a second opinion about the same question.
    owner_index = caster_index if library_index is None else int(library_index)
    sign = 1.0 if owner_index == caster_index else -1.0
    owner = game.players[owner_index]
    scored = [
        (index, sign * _score_tutor_choice(game, owner_index, card))
        for index, card in enumerate(owner.library[:top_count])
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
        required = _cost_for(game, player, card, x_value if x_value is not None else 0)
        if _plan_land_taps(game, player, required) is not None:
            score += 3.0  # castable as soon as it reaches hand
        else:
            available = sum(
                player.mana_pool.get(symbol, 0) for symbol in _MANA_SYMBOLS
            ) + sum(
                1 for permanent in game.controlled_by(player)
                if permanent.card.primary_type == "land" and not permanent.tapped
            )
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
    if game._set_lockout_banning_card(card) is not None:
        # "Players can't cast Arabian Nights cards" (City in a Bottle). Not a
        # targeting question, but the same failure: the cast path refuses and
        # the AI offers the card again next turn. Asked for every card, not
        # only a spell, because the lockout bans *playing* a land too.
        return False

    if controller_cast_ban(game, caster_index, card) is not None:
        # "Enchanted creature's controller can't cast creature spells."
        # (Brand of Ill Omen.) The same reason as the lockout above: the cast
        # path refuses, nothing is spent, and a seat that re-proposes the card
        # every turn does nothing for the rest of the game — which is exactly
        # what `simulate_ai_games.py`'s `refused_casts` counts.
        return False

    if targeting_ban_refusal(game, card) is not None:
        # "This turn and next turn, ... players and permanents can't be the
        # targets of spells or activated abilities." (Peace Talks, CR 113.3c.)
        # The fourth ban on this list and the newest, found by Phase 5's
        # simulation rather than by a test: thirty refused casts across eight
        # games, every one an Aura or a targeted spell offered while the ban
        # stood. Asked through the same predicate the cast path refuses with,
        # so the two cannot answer differently.
        return False

    if global_cast_ban(game, card) is not None:
        # "Creature spells can't be cast." (Aether Storm.) The seatless
        # spelling of the ban above, and on this list for the same reason: the
        # cast path refuses it, so a seat left proposing creatures under an
        # Aether Storm does nothing for the rest of the game.
        return False

    if card.primary_type not in SPELL_TYPES:
        return True

    # The engine's own enumeration, asked **before** the arms below. Those arms
    # are preferences as much as legality — "is there something on the
    # opponent's board worth destroying" — and each reads one or two payload
    # keys, so a narrowing the key does not carry is invisible to it: Tunnel
    # ("destroy target Wall") reads `type_filter == "creature"` and answers yes
    # to any creature at all, then the cast path checks `wall_only` and
    # refuses. Putting the engine's answer first can only ever skip *more*
    # casts, and only ones it can prove have no legal target.
    if _no_legal_cast_target(game, caster_index, card):
        return False

    opponent = game.players[choose_attack_target(game, caster_index)]
    caster = game.players[caster_index]

    program = compile_card_oracle(card)
    for instruction in program.instructions:
        kind = instruction.kind

        if kind == "bounce_target_creature":
            # What the bounce named is payload, not the word "creature":
            # Boomerang names any permanent and Flash Flood names a Mountain,
            # and a check keyed to one card's noun would have the AI hold a
            # Boomerang while the opponent's board was all lands. The same
            # reading the cast gate uses, tested with the same matcher.
            wanted = bounce_subject_filter(instruction.payload)
            return any(
                subject_matches(game, perm, wanted, observer=caster_index)
                for perm in game.controlled_by(opponent)
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
                    and (not color_filter or color_filter in perm.effective_colors)
                    for perm in game.controlled_by(opponent)
                )

        if kind in {"pump_target_creature_until_eot", "grant_regeneration_to_target_creature",
                    "grant_target_flying_until_eot", "berserk_pump"}:
            return any(
                perm.card.primary_type == "creature" for perm in game.controlled_by(caster)
            )

    return True


def _no_legal_cast_target(game: Game, caster_index: int, card: CardDefinition) -> bool:
    """Whether *card* names a mandatory target and the board offers none.

    The chain above is an if-chain over instruction kinds, so every kind it does
    not name fell out of the bottom as "castable" — and for a spell that
    *targets*, castable-with-no-target is a turn the AI spends on an action the
    engine then refuses. It does not lose the game or break a rule (the cast
    gate declines before any mana is spent, CR 601.2c), which is why nothing
    caught it: it is silent, and it repeats. The simulator's old eight-card
    decklist could not reach it because every card in it had an arm. Random
    decks reach it immediately — Deathlace and Thoughtlace (``spell_or
    _permanent``, a kind with no arm) were chosen, refused, and chosen again
    every turn of every game, so a seat holding one never did anything else.

    Rather than adding two more arms — the next unnamed kind would just repeat
    this — ask the enumeration the picker and the cast path already use. That
    is the same move ``activation_target_refusal`` made when it replaced the
    per-kind if-chain in ``activation.py``.
    """
    program = compile_card_oracle(card)
    # A modal spell is *not* excepted here, unlike in `cast_target_refusal`
    # where the caller may have chosen any mode. This policy names no mode, so
    # the spell is cast as mode 0 and mode 0's spec — which is what
    # `derive_cast_spec` returns — is exactly the question to ask. Blue
    # Elemental Blast's mode 0 counters a red spell, so an AI holding one with
    # an empty stack offered it every turn and was refused every turn.
    spec = derive_cast_spec(card, program)
    if spec is None or spec.get("kind") in ("none", "modal") or spec_roles(spec):
        # No spec, no target; roles are `_choose_role_targets`' question and it
        # already declines an unfillable chain.
        return False
    if _targets_are_optional(program):
        # "Up to one target" is castable with none (CR 601.2c).
        return False
    return not game._enumerate_targets(caster_index, card, spec, for_cast=True)


def _targets_are_optional(program) -> bool:
    """True when every ``targets`` quantifier the program carries is an "up to"."""
    quantifiers: list[str] = []

    def walk(instruction) -> None:
        if instruction is None:
            return
        payload = getattr(instruction, "payload", None) or {}
        targets = payload.get("targets")
        if isinstance(targets, dict) and "quantifier" in targets:
            quantifiers.append(targets.get("quantifier"))
        for step in payload.get("steps") or ():
            walk(step)

    for instruction in program.instructions:
        walk(instruction)
    return bool(quantifiers) and all(q == "up_to" for q in quantifiers)


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
    # "Enchant creature **you control**" (Cocoon): however "harmful" the text
    # reads, the clause forbids an opponent's permanent — the same gate the
    # cast path applies (CR 601.2c), asked here so the AI never spends a turn
    # on a cast the game then refuses.
    seat_clause = enchant_noun_seat(noun)
    if seat_clause == "you":
        target_player_index = caster_index
    elif seat_clause == "opponent" and target_player_index == caster_index:
        target_player_index = choose_attack_target(game, caster_index)
    for permanent_index, permanent in enumerate(game.players[target_player_index].battlefield):
        # The spell's own printed targeting restriction (CR 601.2c). Asked here
        # as well as at the cast, and through the same function: a choice only
        # the cast path refuses is an AI turn spent on an action the game then
        # rejects, and a human seat offered a target it cannot take.
        if forbidden_target(game, card, permanent, caster_index):
            continue
        # CR 702.16b: an Aura with a quality cannot be cast targeting a
        # permanent with protection from it. Asked through the cast path's own
        # function for the same reason `forbidden_target` is, one line up — and
        # it was missing, so the AI would pick a creature wearing White Ward for
        # a white Aura, be refused, and pick it again next turn. Invisible until
        # the simulator started building decks that contain both.
        if not game._can_be_targeted(permanent, card, caster_index=caster_index):
            continue
        if permanent_matches_enchant_noun(permanent, noun):
            return target_player_index, permanent_index
    return None


def _even_shares(total: int, count: int) -> list[int]:
    """*total* split *count* ways, remainder to the earliest.

    CR 601.2d wants every target to receive at least one, so the remainder is
    spread rather than dropped — the same starting division
    ``evenStartingDivision`` offers a human in the browser, which is where this
    arithmetic already lived.
    """
    base, left = divmod(total, count)
    return [base + (1 if index < left else 0) for index in range(count)]


def choose_divided_targets(
    game: Game, caster_index: int, card: CardDefinition, x_value: int | None = None
):
    """CR 601.2d's announcement for a divided spell: which targets, and each
    one's share.

    Returns None when *card* divides nothing — every other card in the pool —
    and ``()`` when it divides and no legal announcement exists, which is a
    refusal rather than an absence, the same way ``_choose_role_targets``
    answers: CR 601.2d needs one target or more, and the cast gate refuses a
    spell announced with none, so proposing it would be a turn spent on an
    action the game then rejects.

    **Which board the shares land on is derived, never named**:
    ``ai_valuation.divided_shape`` reads the sign of the counter the compiled
    program places, so Bounty of the Hunt's ``+1/+1`` goes on the caster's own
    creatures and Contagion's ``-2/-1`` on the opponent's, and a card printed
    tomorrow with either template is aimed correctly the day it is ingested.

    Three stated policies sit on top of that, and only the first is forced:

    * **Damage concentrates.** A share is measured against a toughness, so four
      damage split one apiece kills nothing; the whole total goes on the first
      candidate the enumeration offers, which is a player's face where the
      printed noun admits one. That is exactly what the engine's older
      single-target path already did for Fireball, so the four "any target"
      burn spells keep the play they had and gain only a lawful announcement.
    * **Counters spread**, as far as the total and the printed target count
      allow — every counter placed is a counter either way, and Contagion and
      Bounty of the Hunt print a target count precisely because spreading is
      the point of them.
    * **A whole-board division takes the whole board** — "…among all creatures
      target opponent controls" (Dwarven Catapult) chooses nothing, so every
      candidate on the named side is announced and the even split does the rest.
    """
    program = compile_card_oracle(card)
    shape = divided_shape(program)
    if shape is None:
        return None
    spec = game.cast_target_spec(caster_index, card)
    if spec.get("kind") != "divided":
        # A modal or otherwise re-derived spec that does not describe the
        # division. Nothing to announce, and the cast gate reads the same spec.
        return None
    total = _divided_announcement_total(spec, x_value)
    candidates = [
        entry for entry in (spec.get("valid_targets") or ())
        if _divided_candidate_seat(entry) is not None
    ]
    wanted = [
        entry for entry in candidates
        if shape.side is None
        or (_divided_candidate_seat(entry) == caster_index) == (shape.side == "you")
    ] or candidates
    if not wanted or total <= 0:
        # No legal target, or nothing to divide (Spoils of War with an empty
        # opponent graveyard defines X as 0). Either way there is no lawful
        # announcement, and CR 601.2e would return the game to before the cast.
        return ()
    # "…to **each of X targets**" (Firestorm) / "…and 3 damage to **a third
    # target**" (Cone of Flame). The card prints how many, so an announcement of
    # any other length is refused at the cast (CR 601.2c) — and a policy that
    # proposed one anyway would spend every turn on a cast the engine rejects,
    # which is exactly what ``refused_casts`` is the honesty check for. A board
    # too small to fill the count is no legal announcement at all, which is what
    # `()` means here.
    exact = _card_divided_target_count(spec, x_value)
    if exact is not None:
        return (
            [] if len(wanted) < exact
            else [(entry["seat"], entry.get("index")) for entry in wanted[:exact]]
        )
    if shape.whole_board:
        chosen = wanted
    elif shape.thresholded:
        chosen = wanted[:1]
    else:
        maximum = spec.get("max_targets")
        room = total if not isinstance(maximum, int) else min(maximum, total)
        chosen = wanted[:max(1, room)]
    shares = _even_shares(total, len(chosen))
    announced = spec.get("division") == "chosen"
    return [
        # A two-tuple where the card divides *evenly*: CR 601.2d asks for an
        # announcement only from a caster who chooses the division, and
        # `division_refusal` refuses shares announced for a spell that does not.
        (entry["seat"], entry.get("index")) if not announced
        else (entry["seat"], entry.get("index"), share)
        for entry, share in zip(chosen, shares)
    ]


def _card_divided_target_count(spec: dict, x_value: int | None) -> int | None:
    """How many targets a card-dictated division prints, or None.

    None for every divided spell whose count the caster chooses, which is every
    one in the pool before Weatherlight — so the caller may ask unconditionally.

    The two spellings the description carries: a printed number, and the string
    ``"x"`` for a count announced under CR 107.3a. The policy has just chosen
    that X, so it is the value passed in — the same number
    ``casting._card_divided_target_count`` will read off the announcement, which
    is what keeps the proposal and the gate counting the same thing.
    """
    printed = spec.get("divided_target_count")
    if isinstance(printed, bool) or printed is None:
        return None
    if isinstance(printed, int):
        return printed
    return max(0, int(x_value or 0)) if printed == "x" else None


def _divided_candidate_seat(entry) -> int | None:
    """The seat one enumerated divided target sits on, or None if the entry is
    neither a permanent nor a player's face."""
    if not isinstance(entry, dict) or entry.get("kind") not in ("permanent", "player"):
        return None
    seat = entry.get("seat")
    return seat if isinstance(seat, int) else None


def _divided_announcement_total(spec: dict, x_value: int | None) -> int:
    """How much a divided spell has to divide, once X is known.

    The browser's ``dividedDivisionTotal`` in the terms this side speaks: the
    printed amount where the card prints one, the game's number where the card
    defines its own X (CR 107.3c — Spoils of War counts a graveyard, and the
    caster never announces it), and otherwise whatever X the policy picked.
    """
    bonus = int(spec.get("division_x_bonus") or 0)
    if isinstance(spec.get("division_total"), int):
        return spec["division_total"] + bonus
    if isinstance(spec.get("defined_x"), int):
        return spec["defined_x"] + bonus
    return int(x_value or 0) + bonus


def _preferred_role_option(
    options: list[dict], caster_index: int, card: CardDefinition, game: Game
) -> dict:
    """Which of one role's legal answers this seat takes.

    The first, for every role whose object is on a battlefield — the policy
    :func:`_choose_role_targets` documents, safe because the walk has already
    dropped any first choice that leaves a later role with nothing.

    **A seat is the exception, and it is a valuation rather than a policy
    weight.** "Lunge deals 2 damage to target creature and 2 damage to target
    player or planeswalker" offers every living seat for its player role, and
    the caster's own is first in the list — so taking the first burned the
    caster for two. Which seat a spell wants is a question this module already
    answers for every one-target spell (:func:`_choose_target_for_spell`,
    scoring the caster against the seat the attack policy picks), and the roles
    walk is the same question about the same card: asking it here is one
    reader of one answer rather than a second rule about who to point a spell
    at.

    The preference is applied only when that seat is one the walk offered, so
    a role narrowed to "target **opponent**" is never widened by it — and the
    first option stays the answer whenever it is not.
    """
    if not options or options[0].get("kind") != "player":
        return options[0]
    wanted = _choose_target_for_spell(card, caster_index, game)
    return next(
        (option for option in options if option.get("seat") == wanted), options[0]
    )


def _choose_role_targets(
    game: Game, caster_index: int, card: CardDefinition
):
    """Pick one target per **role** for a spell naming several kinds of target.

    ``None`` when *card* names no roles at all — every other spell in the pool —
    and ``()`` when it names them and no legal chain exists, which is a refusal
    rather than an absence: CR 601.2c fills every role or the spell is not cast.

    The chain comes from ``cast_target_spec``, the same walk the browser's
    picker is handed, so the AI and a human seat are offered exactly the same
    choices. Taking the first option at each level is the whole policy, and it
    is safe *because* of what that walk already did: a first choice leaving a
    later role with nothing is not in the list. A card that ever wants a better
    chain wants a valuation in ``engine/ai_valuation.py``, derived from its
    compiled program, not a branch here.
    """
    if not spec_roles(derive_cast_spec(card, compile_card_oracle(card))):
        return None
    options = game.cast_target_spec(caster_index, card).get("valid_targets") or []
    picks: list[dict] = []
    while options:
        pick = _preferred_role_option(options, caster_index, card, game)
        picks.append(pick)
        options = pick.get("next") or []
    if not picks:
        return ()
    # A **player** role's answer is the seat itself (Donate's "target player"),
    # and it fills no slot in the positional id list — the seat travels on the
    # field every cast already carries, which is what the resolution reads back.
    # Held as ``None`` in both lists rather than dropped, because those lists
    # are positional in role order and a short one shifts every slot after it.
    ids = [
        None if pick.get("kind") == "player"
        else game.permanent_id_of(game.permanent_at(pick["seat"], pick["index"]))
        for pick in picks
    ]
    if not all(value is None or isinstance(value, int) for value in ids):
        return ()
    seats = [pick["seat"] for pick in picks if pick.get("kind") == "player"]
    if len(seats) > 1:
        # Two player roles would be one seat sent twice, which the resolution
        # refuses on the other side of the same fact. Skipped rather than cast.
        return ()
    # The seat is still sent for every other roles spell too, because every cast
    # carries one; the *ids* are what address the two boards a roles spell may
    # span (CR 400.7).
    seat = seats[0] if seats else picks[0]["seat"]
    indices = [
        None if pick.get("kind") == "player" else pick["index"] for pick in picks
    ]
    return seat, indices, ids


def _choose_several_targets(
    game: Game, caster_index: int, card: CardDefinition
) -> tuple[int, list[int], list[int] | None] | None:
    """Pick ``(seat, [permanent_index, …], [permanent_id, …] | None)`` for a spell
    naming several targets, or None when the card names no such choice.

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
    program = compile_card_oracle(card)
    spec = derive_cast_spec(card, program)
    maximum = (spec or {}).get("max_targets")
    # "Return **up to X** target cards from your graveyard to your hand, where X
    # is the number of black permanents target opponent controls **as you cast
    # this spell**." (Reap.) The count is a board count, so the card-only
    # derivation above cannot carry it — it reports ``x_targets``, "however many
    # the announced X pays for" — and a chooser that stopped there named no
    # targets at all, which is a spell that resolves every game and does
    # nothing. Asked of the game through the *same* reader the announcement gate
    # and the browser's picker use, so the AI never proposes a count CR 601.2c
    # then refuses.
    #
    # Derived, not name-keyed: any card printing the same tail is covered the
    # day it is ingested. A spell whose X the *caster* announces (Shattered
    # Crypt's {X} cost) has no answer here and keeps the behaviour it had.
    announced = (
        game.announced_cast_x(caster_index, card)
        if (spec or {}).get("x_targets") else None
    )
    if announced is not None:
        if announced < 1:
            # CR 601.2c: naming nothing is a legal announcement for an "up to"
            # spell, and it is what the caller does when this returns None — so
            # the honest answer at X=0 is "no several-target choice to make".
            return None
        maximum = announced
    elif not isinstance(maximum, int) or maximum <= 1:
        # "Destroy target artifact. For each additional {1}{R} you paid, destroy
        # **another** target artifact…" (Primitive Justice): the count is fixed
        # by an announcement (CR 601.2b) this policy does not make, since it
        # takes no optional additional cost -- so the number is the base alone,
        # and it can be one. One is still a number this chooser has to answer:
        # CR 601.2c refuses an announcement that names no target
        # (`legality.cast_target_refusal`), and a several-target handler has no
        # resolution-time board scan to fall into the way a single-target one
        # does. Without this the seat re-proposes the spell every turn and is
        # refused every turn, which is exactly what `refused_casts` counts.
        maximum = cost_target_count((spec or {}).get("cost_targets"), {}) or 0
        if maximum < 1:
            return None
    legal = game.cast_target_spec(caster_index, card).get("valid_targets") or []
    by_seat: dict[int, list[int]] = {}
    # A graveyard card is not a permanent and has no `permanent_id`; its slots
    # are indices into one player's graveyard, so they are collected under that
    # seat and sent as indices. Same stated policy - take the maximum - because
    # the per-target benefit argument is the same.
    wanted_kind = (
        "graveyard" if (spec or {}).get("kind") == "graveyard_creature" else "permanent"
    )
    for entry in legal:
        if entry.get("kind") != wanted_kind:
            continue
        by_seat.setdefault(int(entry["seat"]), []).append(int(entry["index"]))
    if not by_seat:
        return None

    # Which board each slot wants, derived from the compiled program rather than
    # from the card's name. A card whose slots all want the same thing — every
    # one printed before Rookie Mistake — takes the single-seat path below
    # unchanged, so this is byte-identical for Basri's Acolyte and Basri's Aegis.
    sides = several_target_slot_sides(program)
    if sides and len(set(sides)) > 1:
        picks: list[tuple[int, int]] = []
        for index in range(maximum):
            want = sides[index] if index < len(sides) else None
            if want == "you":
                order = [caster_index]
            elif want == "opponent":
                order = sorted(s for s in by_seat if s != caster_index)
            else:
                order = [caster_index] + sorted(s for s in by_seat if s != caster_index)
            chosen = next(
                (
                    (seat, slot)
                    for seat in order
                    for slot in by_seat.get(seat, [])
                    if (seat, slot) not in picks
                ),
                None,
            )
            if chosen is not None:
                picks.append(chosen)
        if picks:
            ids = []
            for seat, slot in picks:
                permanent = game.permanent_at(game.players[seat], slot)
                ids.append(None if permanent is None else permanent.permanent_id)
            if all(isinstance(value, int) for value in ids):
                # `target_player_index` still has to be a seat; the ids are what
                # actually address the two boards (CR 400.7), and `_stack_push`
                # respects supplied ids over a re-derivation from one seat.
                return picks[0][0], [slot for _, slot in picks], ids

    # A side every slot agrees on is still an answer, and the fallback below has
    # always assumed the caster's own board. Rookie Mistake needed slots that
    # *disagree*; a several-target tap has slots that agree on the opponent, and
    # reading only the disagreement left the AI tapping its own creatures. Still
    # one seat, so the ids stay unnecessary and every card whose slots agree on
    # "you" is byte-identical.
    if sides and set(sides) == {"opponent"}:
        opponents = sorted(seat for seat in by_seat if seat != caster_index)
        if opponents:
            return opponents[0], by_seat[opponents[0]][:maximum], None

    # One seat's worth: the index list is positional on a single battlefield
    # (`target_player_index` names whose), so a cross-seat spread needs the ids
    # above. Taking the maximum from the caster's own board is the whole policy
    # where no slot names a side: "up to N" may legally choose fewer, but every
    # card carrying that template gives a benefit per target, so more is better.
    seat = caster_index if caster_index in by_seat else min(by_seat)
    return seat, by_seat[seat][:maximum], None


#: Cast specs whose legal answers are not permanents on a battlefield — a
#: player, a spell, a card in a graveyard or a hand, a choice of modes. The
#: single-object chooser below has nothing to say about them.
_NOT_OBJECT_SPECS = frozenset({
    "none", "modal", "player", "stack", "graveyard_creature", "hand_card",
    "spell_or_permanent",
})


def _choose_single_object_target(
    game: Game, caster_index: int, card: CardDefinition, preferred_seat: int
):
    """Name the one permanent a one-object-target spell is cast at:
    ``(seat, index, [permanent_id])``, ``()`` when the side the effect wants
    holds no legal target, or None when *card* is not such a spell.

    The cast used to name a **seat** and leave the permanent to the handler's
    board scan — the headless convention, which W1G2 measured 156 of 182
    creature-targeting spells accepting. Two ways that resolved doing nothing,
    both measured in NEM's simulation: a handler with no scan to fall into
    (Sivvi's Valor: "its target is gone"), and a seat with no permanent the
    printed noun admits (Topple aimed at a seat whose creatures were not the
    greatest). Naming the permanent out of the engine's own enumeration — the
    list the browser's picker offers a human — answers both, and the first
    legal permanent on the seat is the one the scan would have taken.

    Which seat is ``ai_valuation.spell_target_side``: a side the effect wants
    with nothing legal on it is ``()``, because the alternative is aiming a
    denial at the caster's own board or a gift at an opponent's. With no side,
    *preferred_seat* (the score's choice) first and then any seat — a spell that
    can only do something on the other board is cast there rather than at
    nothing. A spec offering a **player** is left alone: "any target" damage is
    aimed at a face by the seat it already carries.
    """
    program = compile_card_oracle(card)
    spec = derive_cast_spec(card, program)
    if (
        not isinstance(spec, dict)
        or spec.get("kind") in _NOT_OBJECT_SPECS
        or spec_roles(spec)
        or _targets_are_optional(program)
    ):
        return None
    legal = game._enumerate_targets(caster_index, card, spec, for_cast=True)
    if not legal or any(entry.get("kind") != "permanent" for entry in legal):
        return None
    if spell_denies_its_own_target(card):
        # "Return target permanent you control to its owner's hand"
        # (Scapegoat): a denial the printed words aim at the caster's own
        # board, which this policy has no rescue to time it for.
        return ()
    side = spell_target_side(card)
    others = [seat for seat in range(len(game.players)) if seat != caster_index]
    if side == "you":
        order = [caster_index]
    elif side == "opponent":
        first = choose_attack_target(game, caster_index)
        order = [first] + [seat for seat in others if seat != first]
    else:
        order = [preferred_seat] + [
            seat for seat in [caster_index, *others] if seat != preferred_seat
        ]
    for seat in order:
        for entry in legal:
            if entry.get("seat") != seat:
                continue
            permanent_id = game.permanent_id_of(game.permanent_at(seat, entry["index"]))
            if isinstance(permanent_id, int):
                return seat, entry["index"], [permanent_id]
    return ()


def _caster_can_make_its_sacrifices(
    game: Game, caster_index: int, card: CardDefinition
) -> bool:
    """Whether every sacrifice *card*'s own effect has its caster make will
    give something up (``ai_valuation.caster_sacrifice_steps``).

    Asked of the engine's own candidate list — the one the sacrifice handler
    picks from — so the policy and the resolution cannot disagree about what
    "a creature" admits. "Sacrifice **any number of** …" is answered by the
    seat's own default, which is the stated policy in
    ``_resolve_sacrifice_inline``: a seat nobody asks gives up none. So this
    seat's Renounce, Reprocess or Landslide would sacrifice nothing and the
    rest of the spell, counting what went, would do nothing — measured at
    MMQ, where skipping a self-exiling Last Breath left Renounce as the cast
    and it resolved for zero.
    """
    player = game.players[caster_index]
    for step in caster_sacrifice_steps(card):
        if step["any_number"]:
            return False
        if not game._sacrifice_candidate_indices(player, step["filter"]):
            return False
    return True


def _caster_holds_a_hand_pick_entrant(
    game: Game, caster_index: int, card: CardDefinition, hand_index: int | None
) -> bool:
    """Whether the caster holds — besides *card* itself, which is on the stack
    by then (CR 601.2a) — a card the spell's own "choose a card in your hand"
    pick could put onto the battlefield
    (``ai_valuation.spell_hand_pick_entry_filters``).

    Through ``_card_matches_filter``, the matcher the entering step itself asks.
    """
    from .handlers._common import _card_matches_filter

    filters = spell_hand_pick_entry_filters(card)
    if not filters:
        return True
    player = game.players[caster_index]
    held = [c for slot, c in enumerate(player.hand) if slot != hand_index]
    return all(
        any(_card_matches_filter(c, wanted, game=game, owner=player) for c in held)
        for wanted in filters
    )


def _hand_entry_has_a_card(
    game: Game, player_index: int, source: Permanent, instruction
) -> bool:
    """Whether every "put a … card from your hand onto the battlefield" step of
    an ability (``ai_valuation.hand_entry_steps``) has a card to put.

    The candidates are the engine's own (``put_from_hand_candidates``), with
    "of the chosen type" resolved off the source the way the handler resolves
    it (``_resolve_chosen_subtype``), so the policy and the resolution cannot
    disagree about which cards the step admits.
    """
    from .handlers._common import _resolve_chosen_subtype
    from .handlers.zones import put_from_hand_candidates

    player = game.players[player_index]
    for payload in hand_entry_steps(instruction):
        described = _resolve_chosen_subtype(
            dict(payload.get("card_filter") or {}), source
        )
        if not put_from_hand_candidates(
            game, {**payload, "card_filter": described}, player
        ):
            return False
    return True


def _choose_target_for_spell(
    card: CardDefinition, caster_index: int, game: Game, x_value: int | None = None
) -> int:
    # Whose permanent the spell's object target should be, when the compiled
    # program says (`ai_valuation.spell_target_side`). Asked before the score,
    # because the score below is a handful of text probes and every spell
    # outside them tied the two seats — and the tie goes to the caster, so
    # "Target creature can't attack or block this turn" kept the AI's own
    # creature home. The side is a claim about what the effect does to its
    # target, never about which card printed it.
    side = spell_target_side(card)
    if side == "you":
        return caster_index
    if side == "opponent":
        return choose_attack_target(game, caster_index)
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


# --- What a toll's two losses are worth against each other -------------------
#
# The prices, in life-equivalents. Weights are tuning and belong here; *which
# resources a branch takes* is `ai_valuation.toll_branch_loss`'s derivation
# from the compiled program, and the permanents it hands back are the engine's
# own default picks, so the comparison prices exactly what would be given up.

#: A branch whose life cost meets or beats the seat's total. Never the smaller
#: loss against anything survivable, whatever the other side gives up.
_TOLL_LETHAL_PRICE = 1000.0
#: A card out of hand (a discard) or out of the game (an ante): the classic
#: two-for-one accounting — a card is worth about two life.
_TOLL_CARD_PRICE = 2.0
#: A card milled off the seat's own library: barely a loss at all, but not
#: nothing (CR 704.5b is somewhere down there).
_TOLL_MILL_PRICE = 0.25
#: What any permanent is worth just by being one — a card that reached the
#: battlefield — before `_permanent_value` adds its stats and cost. Without a
#: floor a Mox prices at 0.0 (no P/T, no cmc) and the seat gives it up to dodge
#: any damage at all.
_TOLL_PERMANENT_FLOOR = 2.5
#: Tapping the source: a turn's use of it, not the card.
_TOLL_TAP_PRICE = 1.0


def _toll_loss_price(game: Game, player_index: int, loss) -> float:
    """One branch's `ai_valuation.TollLoss`, priced in life-equivalents."""
    player = game.players[player_index]
    if loss.life and loss.life >= player.life:
        return _TOLL_LETHAL_PRICE
    price = float(loss.life)
    price += loss.cards * _TOLL_CARD_PRICE
    price += loss.milled * _TOLL_MILL_PRICE
    for permanent in loss.permanents:
        price += _TOLL_PERMANENT_FLOOR + _permanent_value(permanent)
    if loss.taps_source:
        price += _TOLL_TAP_PRICE
    return price


def toll_decline_is_smaller_loss(
    game: Game, player_index: int, entry: dict, self_recipients=()
) -> bool:
    """Whether taking this toll's printed penalty loses less than paying its
    price — the valuation behind **take gifts, pay tolls, make no trades**'
    middle word, for the seat nobody asked (`_default_optional_pay`).

    A *toll* is an offer with a printed decline consequence, so both answers
    are losses: "pay 2 life" against "sacrifice this enchantment" (Season of
    the Witch), "sacrifice that artifact" against "2 damage" (Curse Artifact).
    Both sides are derived from the compiled program by
    `ai_valuation.toll_branch_loss` and priced by the weights above; a side the
    program cannot price answers False, which keeps the standing policy — pay
    tolls — rather than comparing a number to a guess.

    Deliberately silent on a mana-priced toll: the default pays those out of
    floating mana and, since ``optional_pay_may_tap_lands``, out of untapped
    lands too — always, because a toll's other answer is a loss as well and
    the standing policy is to pay. Pricing a tapped land against the penalty
    is a weight nobody has measured a need for yet.

    *entry* is the armed `optional_pay` data and *self_recipients* the printed
    player references that resolve to the offered seat, both supplied by the
    resolution because only it knows them.
    """
    penalty_steps = tuple(entry.get("_on_decline") or ())
    legacy_damage = int(entry.get("damage", 0) or 0)
    if not penalty_steps and not legacy_damage:
        return False  # not a toll; the unpriced-trade policy owns free offers
    if (
        entry.get("cost")
        or entry.get("cost_alternatives")
        or entry.get("graded_options")
    ):
        return False  # mana-priced: the floating-mana policy stands
    source = entry.get("_source_permanent")
    paying = toll_branch_loss(
        game, player_index, tuple(entry.get("_on_accept") or ()),
        self_recipients, source,
    )
    if paying is None:
        return False
    life_cost = int(entry.get("life_cost", 0) or 0)
    if life_cost:
        paying = paying.plus_life(life_cost)
    declining = toll_branch_loss(
        game, player_index, penalty_steps, self_recipients, source
    )
    if declining is None:
        return False
    if legacy_damage:
        declining = declining.plus_life(legacy_damage)
    return _toll_loss_price(game, player_index, declining) < _toll_loss_price(
        game, player_index, paying
    )


def chained_toll_declined(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asked declines one link of an "unless **any
    player** pays" chain (`handlers/control_flow.unless_player_pays`).

    The chain asks every seat in turn, the effect's own controller included —
    and for that seat the standing policy, *pay tolls*, is backwards: Rhystic
    Tutor's caster paid {2} to stop its own search, and every rhystic spell
    the AI cast was countered by its own mana. Who a link's answer helps is
    whose effect it is, read off the compiled program:

    * the **unpaid** branch is what the controller cast the effect for, unless
      ``toll_branch_loss`` prices it as the controller's own loss (Icy
      Prison's "sacrifice this enchantment") — so the controller pays only to
      stop a loss, and every other seat pays only to stop a gain;
    * the **paid** branch (Rhystic Scrying's "if any player pays {2}, discard
      three cards") is the drawback the card prints, so its controller never
      buys it and every other seat does when it can afford to.

    False — the standing policy — for anything that is not a chain link.
    """
    links = tuple(entry.get("_on_decline") or ())
    if len(links) != 1 or getattr(links[0], "kind", None) != "unless_player_pays":
        return False
    caster = getattr(entry.get("_context"), "caster", None)
    if caster is None or caster not in game.players:
        return False
    controller = game.players.index(caster)
    unpaid = tuple(links[0].payload.get("unpaid") or ())
    if not unpaid:
        return player_index == controller
    loss = toll_branch_loss(
        game, controller, unpaid, {"caster"}, entry.get("_source_permanent")
    )
    unpaid_is_a_loss = loss is not None and loss != TollLoss()
    return (player_index == controller) != unpaid_is_a_loss


def optional_pay_may_tap_lands(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asked may tap its untapped lands to pay a
    mana-priced "you may pay" / "unless you pay" (`_default_optional_pay`).

    The policy that default states — **take gifts, pay tolls, make no trades** —
    had a mana half that read "never tap a land", and the offers this answers
    arrive where the pool is empty: an upkeep, a combat damage step, an
    opponent's turn. So every mana-priced toll was declined (Vaporous Djinn
    sacrificed itself with its two Islands untapped) and every mana-priced gift
    was refused (Rootwater Thief's {2}, Liliana's Devotee's {1}{B}). The
    plumbing to pay from lands was already there — ``_optional_pay_plan`` is a
    ``plan_payment`` over the untapped lands — and this is the weight that
    decides when to use it:

    * **A toll is always paid from the board when it can be.** Both answers
      are losses and the standing policy is to pay; refusing an affordable toll
      because the mana was in a land rather than in the pool was never the
      policy, only a consequence of where the pool happened to be.
    * **A gift is paid from lands only with mana nothing else will spend.** On
      another seat's turn the lands sit until this seat's untap step anyway. On
      the seat's own turn they are what it casts with, so a gift is taken only
      when no spell in hand could be cast with them now — the same question
      ``choose_cast_action`` answers, asked of the same candidates.
    * **And only a gift the seat's own object offers.** An offer another
      seat's spell makes this one ("that player may pay {R}{R}. If the player
      does, they may copy this spell", Chain Lightning) is priced by a card
      somebody else chose to cast, and what accepting does is left to defaults
      this policy cannot value — the copy keeps its original target, which is
      the payer's own creature. Those keep the floating-mana rule.
    """
    if entry.get("_on_decline") or int(entry.get("damage", 0) or 0) > 0:
        return True
    context = entry.get("_context")
    if getattr(context, "caster", None) is not game.players[player_index]:
        return False
    if game.active_player_index != player_index:
        return True
    return not any(
        card.primary_type != "land"
        and _cast_candidate(game, player_index, card, hand_index) is not None
        for hand_index, card in enumerate(game.players[player_index].hand)
    )


def order_hand_pick(
    game: Game, player_index: int, candidates, payload: dict, source_card
) -> list[int]:
    """*candidates* (hand slots) in the order a seat nobody asked should pick
    them for a "choose a card in your hand" (`_default_choose_cards_in_hand`).

    Unchanged — hand order, the stated default — unless the program behind the
    pick puts the picked card onto the battlefield for its owner
    (``ai_valuation.hand_pick_entry_consumer``). Then the cards that sentence
    admits come first, and among them the one at its superlative's extreme:
    "with the **lowest** mana value" enters only the lowest, so the cheapest
    admitted card is the pick that can win the comparison. Everything else
    keeps its hand order behind them.
    """
    from .ai_valuation import hand_pick_entry_consumer
    from .handlers._common import _card_matches_filter

    order = list(candidates)
    key = str((payload or {}).get("result_key") or "chosen_hand_cards")
    consumer = hand_pick_entry_consumer(source_card, key) if source_card else None
    if consumer is None:
        return order
    player = game.players[player_index]
    admitted = [
        slot for slot in order
        if _card_matches_filter(
            player.hand[slot], consumer["card_filter"], game=game, owner=player
        )
    ]
    superlative = consumer["superlative"]
    if superlative.get("characteristic") == "mana_value":
        sign = 1 if superlative.get("extreme") == "least" else -1
        admitted.sort(key=lambda slot: (sign * int(player.hand[slot].cmc or 0), slot))
    return admitted + [slot for slot in order if slot not in admitted]


def _choose_equip_target(game: Game, player_index: int, equipment) -> int | None:
    """The battlefield index of the creature *equipment* should be moved onto,
    or None when it is already on the best one (or there is none).

    The biggest creature that can attack — power first, then toughness — among
    the ones the Equipment may legally equip, asked of the same legality the
    engine enforces (``engine/equipment.py``) so the AI never activates an
    equip the engine then refuses. Summoning-sick creatures are not excluded:
    an Equipment moved onto one now is on it when it can attack next turn, and
    the +1/+1 blocks just as well meanwhile.
    """
    from .equipment import equip_refusal, equipped_creature

    player = game.players[player_index]
    candidates = [
        (idx, perm)
        for idx, perm in enumerate(player.battlefield)
        if perm.is_creature and equip_refusal(game, equipment, perm) is None
    ]
    if not candidates:
        return None
    best_index, best = max(
        candidates,
        key=lambda pair: (pair[1].effective_power, pair[1].effective_toughness, -pair[0]),
    )
    if equipped_creature(equipment) is best:
        return None
    return best_index


def _choose_target_for_instruction(instruction: OracleInstruction, caster_index: int, game: Game) -> int:
    if is_mana_ability(instruction):
        # Mana goes to its controller's pool; the ability has no other target.
        return caster_index
    if instruction.kind == "attach_source_to_target":
        # "Target creature you control" — the equip's creature is the
        # activator's own (CR 702.6a).
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


def _cost_for(
    game: Game,
    player: PlayerState,
    card: CardDefinition,
    x_value: int | None,
    extra_generic: int = 0,
) -> dict[str, int]:
    """What *player* actually pays for *card* — CR 601.2f, increases then
    reductions, through the same three functions the cast path calls.

    *extra_generic* is a generic surcharge the cast will carry that no
    registered modifier states — today the commander tax (CR 903.8), which the
    cast path adds to its own ``extra_generic_tax`` the same way. Zero for
    every hand cast.

    The seat is threaded rather than assumed. This used to pass 0 with a comment
    saying no registered modifier depended on it, which was true while every one
    of them was scoped by the *card's* colour; it stopped being true the moment
    a card printed "spells **you cast** cost {1} less", and a claim about the
    pool expires without anyone editing the comment. Identity, not
    ``players.index``: PlayerState is value-compared.
    """
    seat = next((i for i, seated in enumerate(game.players) if seated is player), 0)
    tax, _names = spell_cost_tax(game, seat, card)
    tax += max(0, extra_generic)
    # The coloured half of the same taxes (Derelor). Asked here too, because the
    # AI prices a spell to decide whether it can cast it — priced without the
    # pip it proposes a cast the rules then refuse, every turn, forever.
    pips, _pip_names = spell_symbol_tax(game, seat, card)
    reduction, _reducers = cost_reduction_for_cast(game, seat, card)
    # The best split of X among the colours the card allows, which is the one
    # the cast path will try first (`casting._x_color_allocations`). The AI is
    # sizing the cost, so it wants the payment that will actually be attempted;
    # a split the cast would not choose prices a different spell.
    allocation = game._x_color_allocations(
        x_spend_colors_from_text(card.oracle_text), max(0, x_value or 0)
    )[0]
    return reduce_cost(
        game._parse_mana_cost(
            card.mana_cost,
            x_value=x_value,
            extra_generic=tax,
            x_allocation=allocation,
            extra_pips=pips,
        ),
        reduction,
    )


def _pick_x_value(
    game: Game, player: PlayerState, card: CardDefinition,
    extra_generic: int = 0, hand_index: int | None = None,
) -> int | None:
    """The X this seat announces for *card* (CR 107.3a), or None where the card
    asks for none.

    **The mana cost is only one of the four places CR 107.3a names**, and this
    asked only that one. Fire Covenant ({1}{B}{R}, "pay X life"), Infernal
    Harvest ({1}{B}, "return X Swamps") and Haunting Misery ({1}{B}{B}, "exile
    X creature cards") print no {X} anywhere, so the AI announced nothing, the
    cast fell back to the 0 an unmade CR 107.3a announcement reads as here, and
    all three shipped spells resolved
    doing precisely nothing — legal, since 0 is a choice, and invisible to both
    honesty checks: the cast is not refused and it does interact. This is the
    same one-place-short reading ``cast_announces_x`` was written for on the
    browser's side of the question, so it is the same reader that answers it.

    The ceiling is not the mana pool for those: it is a life total or a board or
    a hand, and ``_additional_cost_x_ceiling`` is what
    ``_unpayable_additional_cost`` will measure the announcement against — asked
    here so the policy announces exactly what the cast will accept.

    *hand_index* is which copy is being cast, and it matters to the ceiling: the
    spell is on the stack before its costs are paid (CR 601.2a), so it cannot be
    one of the cards discarded for Firestorm's "discard X cards". Omitted by the
    two callers that are pricing a card rather than casting one, where an X one
    too high is a bound and not an announcement.
    """
    if "{X}" not in card.mana_cost.upper():
        if not cast_announces_x(card):
            return None
        seat = next(
            (i for i, seated in enumerate(game.players) if seated is player), 0
        )
        bound = game._additional_cost_x_ceiling(
            seat, card, from_zone="hand", spell_hand_index=hand_index,
        )
        return None if bound is None else bound

    max_x = _max_affordable_x(game, player, card, extra_generic)
    return max_x


def _max_affordable_x(
    game: Game, player: PlayerState, card: CardDefinition, extra_generic: int = 0
) -> int:
    # Through the tap planner rather than a summed preview pool: the preview
    # counted each land as one fixed symbol, so a dual or a swapped land could
    # only ever pay for the first colour it listed, and the X it sized was the
    # X a board of single-colour lands would afford.
    for x_value in range(15, -1, -1):
        required = _cost_for(game, player, card, x_value, extra_generic=extra_generic)
        if _plan_land_taps(game, player, required) is not None:
            return x_value
    return 0


def _plan_land_taps(
    game: Game, player: PlayerState, required: dict[str, int]
) -> tuple[tuple[int, ...], tuple[str, ...]] | None:
    """Which untapped lands to tap for *required*, and **which colour to ask
    each one for**: ``(slots, colours)`` in tap order, or None when the board
    cannot pay.

    What a land can make is the engine's answer, ``Game._land_payment_colors``
    — the hook the optional-pay planner and the client's colour prompt read —
    and not the printed summary's first symbol, which is what this read. That
    one symbol was wrong three ways, measured at NEM: under a seat-wide swap
    (Deep Water, Harvest Mage) a Forest makes {U} or a colour of the tapper's
    choice, so the plan tapped it for a {G} it would not make; a land carrying
    a granted ability (Overlaid Terrain's "{T}: Add two mana of any one
    color") was still the colour it was printed; and a dual land could only
    ever pay its first colour.

    The colour travels with the plan because the tap seam asks for one
    (``tap_land_for_mana``'s ``chosen_color``) and the executors sent the
    default "G" for every land — so a Taiga the plan counted as {R} made {G},
    and a land under Harvest Mage made green whatever the plan needed.

    The greedy order is the one this function always had, so a board of
    single-colour lands is planned exactly as before: a pip is matched first
    by lands whose **first** colour it is, in battlefield order, and only then
    by a land that lists it further along; the generic remainder takes each
    land at its first colour. **How much** a tap makes is
    :func:`_land_mana_amount` — two for a land under Overlaid Terrain, which
    this counted as one and so planned a two-land board as unable to cast
    anything costing three.
    """
    pool = {symbol: player.mana_pool.get(symbol, 0) for symbol in _MANA_SYMBOLS}
    untapped_lands = [
        (index, _land_symbols(game, permanent), _land_mana_amount(game, permanent))
        for index, permanent in enumerate(game.controlled_by(player))
        if permanent.card.primary_type == "land" and not permanent.tapped
    ]

    if _can_pay_cost(pool, required, player):
        return (), ()

    chosen: list[int] = []
    colors: list[str] = []
    remaining = list(untapped_lands)

    def take(position: int, symbol: str) -> None:
        land_index, _symbols, amount = remaining.pop(position)
        chosen.append(land_index)
        colors.append(symbol)
        pool[symbol] = pool.get(symbol, 0) + amount

    for symbol in _MANA_SYMBOLS:
        while required.get(symbol, 0) - pool.get(symbol, 0) > 0:
            match_idx = next(
                (idx for idx, (_, makes, _n) in enumerate(remaining) if makes[0] == symbol),
                None,
            )
            if match_idx is None:
                match_idx = next(
                    (idx for idx, (_, makes, _n) in enumerate(remaining) if symbol in makes),
                    None,
                )
            if match_idx is None:
                break
            take(match_idx, symbol)

    while remaining and not _can_pay_cost(pool, required, player):
        best_idx = 0
        best_benefit = -1
        for idx, (_, makes, _n) in enumerate(remaining):
            produced = makes[0]
            benefit = 2 if pool.get(produced, 0) < required.get(produced, 0) else 1
            if produced == "C" and required.get("generic", 0) == 0:
                benefit = 0
            if benefit > best_benefit:
                best_benefit = benefit
                best_idx = idx
        take(best_idx, remaining[best_idx][1][0])

    if not _can_pay_cost(pool, required, player):
        return None

    return tuple(chosen), tuple(colors)


def _can_pay_cost(
    pool: dict[str, int], required: dict[str, int], payer: PlayerState
) -> bool:
    """Whether *payer* could pay *required* out of *pool*.

    *pool* is a **preview** — the seat's floating mana plus whatever its
    untapped lands would make — so it is passed rather than read off the payer;
    the payer is here for the CR 609.4 spending permissions, which are facts
    about the seat rather than about the pool.

    Both permissions, from one argument. This took ``can_spend_white_as_red``
    as a bare bool, so the wider one beside it (Chromatic Orrery's "you may
    spend mana as though it were mana of any color") was simply not asked, and
    a seat with a colourless pool judged every coloured spell in its hand
    uncastable. Nothing breaks visibly when an AI under-reports what it can pay
    — it just never casts, which is the "a seat doing nothing all game" shape
    ``simulate_ai_games.py`` counts as a refused cast.
    """
    can_spend_white_as_red = payer.can_spend_white_as_red
    if payer.spends_mana_as_any_color:
        # Every unit pays a coloured pip and a {C} still wants colourless —
        # through the engine's own arithmetic, so the AI's answer and the
        # payment's cannot drift.
        from .mana_payment import fungible_colors_headroom

        return fungible_colors_headroom(pool, required) is not None
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


def _land_mana_amount(game: Game, permanent: Permanent) -> int:
    """How many mana one tap of *permanent* makes, as the planner counts it.

    The free mana ability the tap seam will run (``_land_mana_abilities``):
    its pip run ("{C}{C}", Ancient Tomb) or its any-colour count ("two mana of
    any one color", the ability Overlaid Terrain grants). One wherever that
    cannot be read off the payload — a basic, a choice between pips, an amount
    behind a condition — and one under a swap that replaces the amount ("…one
    mana of a color of your choice instead of any other type **and amount**",
    Harvest Mage). Restricted mana ("Spend this mana only to cast artifact
    spells") counts one as well: the planner cannot tell which costs it may
    pay, and one is what it always assumed.
    """
    from . import land_mana_swaps

    swapped = land_mana_swaps.swapped_production(game, permanent)
    if swapped is not None and swapped.replaces_amount:
        return 1
    free, _priced = game._land_mana_abilities(permanent)
    payload = (getattr(free, "payload", None) or {}) if free is not None else {}
    if not payload or payload.get("spend_only"):
        return 1
    pips = payload.get("pips")
    if pips:
        return max(1, sum(int(count) for _symbol, count in pips))
    any_count = payload.get("any_color_count")
    if isinstance(any_count, int) and not isinstance(any_count, bool):
        return max(1, any_count)
    return 1


def _land_symbols(game: Game, permanent: Permanent) -> tuple[str, ...]:
    """Every symbol tapping *permanent* for mana could put in the pool, the one
    it would make unasked first.

    ``Game._land_payment_colors`` — the engine's own answer, swaps and granted
    abilities included — and the basic land types layer 4 gives it where that
    is silent. "C" for a land that names neither, which is what this planner
    has always assumed of one.
    """
    symbols = tuple(game._land_payment_colors(permanent))
    if symbols:
        return symbols
    # Layer 4 already knows which basic land types this permanent currently
    # has, printed or granted by a type-changing effect.
    basic = tuple(permanent.basic_land_mana)
    return basic if basic else ("C",)
