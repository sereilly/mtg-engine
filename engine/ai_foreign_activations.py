"""Which ability an AI seat activates on a permanent **another seat
controls** (CR 602.1b: "Any player may activate this ability").

The chooser in ``ai_abilities`` walks the seat's own board, so for the life
of this engine no AI seat ever paid to use an opponent's Volrath's Dungeon,
Ribbon Snake or Task Mage Assembly — 23 shipped and 11 PCY cards printing a
permission that admits a seat other than the controller (W1G5's census).
The engine has let any player activate them since `activation_permissions`
existed; this is the policy half.

**Which of them a seat wants is read off the compiled program**
(`ai_valuation.foreign_activation_use`): a drawback printed for an opponent
to pay for — an effect that removes, returns or shrinks its own source — is
the reason to pay, and an "aimed" ability is the activator's own in every
respect but where it is printed (CR 113.8), so it is targeted and scored as
``ai_abilities.choose_activation_action`` would score it on this seat's
board (the seat it names is ``ai_abilities._choose_target_for_instruction``'s).

A module of its own rather than a second chooser in ``ai_abilities``,
because the two read one program in opposite directions
(:func:`choose_foreign_activation_action`); beside it are the hand's
(``ai_hand_activations``, CR 113.6j) and the graveyard's
(``ai_graveyard_activations``, CR 113.6b).
"""

from __future__ import annotations

from .ai_target_sides import ability_denies_its_target, ability_target_side
from .ai_valuation import (
    foreign_activation_use,
    is_mana_ability,
    source_toughness_change,
)
from .activation_permissions import activation_permission_denial
from .activation_restrictions import activation_denial, global_activation_ban
from .game import Game
from .models import Permanent, PlayerState
from .targeting import derive_activation_spec
from .ai_payment import _plan_land_taps
from .ai_actions import ActivationAction
from .ai_scoring import _permanent_value, _score_activation
from .ai_declarations import legal_attackers
from .ai_abilities import _choose_target_for_instruction
from .ai_player_control import plays_for_another


#: Life a seat keeps back when it pays life to use an opponent's ability.
#: "Pay 5 life: Destroy this enchantment" (Volrath's Dungeon) is removal
#: bought with life, and a seat this low spends its life staying alive.
FOREIGN_ACTIVATION_LIFE_RESERVE = 10
#: Taking an opponent's permanent off the battlefield, before what the
#: permanent itself is worth (`_permanent_value`).
FOREIGN_REMOVAL_SCORE = 3.0
#: Killing an opponent's creature with its own printed drawback.
FOREIGN_KILL_SCORE = 5.0

#: The board-target kinds a foreign "aimed" ability is chosen for. A graveyard
#: or stack target is left alone: "Return target creature card from a
#: graveyard to its owner's hand" (Endbringer's Revel) needs a pick of *whose*
#: card this policy does not make for its own copy either, and a stack target
#: has nothing to aim at in the main phase this runs in.
_FOREIGN_OBJECT_KINDS = frozenset({"creature", "artifact", "land", "permanent", "planeswalker"})


def _plain_activation_cost(cost) -> bool:
    """Whether *cost* is mana and a fixed amount of life, and nothing else.

    Every other cost a foreign ability could print — a tap, a sacrifice, a
    discard, a counter, an alternative ("Pay 2 life or {2}", Tidal Control) —
    is a trade or a choice this chooser cannot price. Asked as "equal to a
    bare cost with the same mana" rather than field by field, so a cost field
    added later is declined until someone decides otherwise.
    """
    from dataclasses import replace

    from .activated_ability_cost import ActivatedAbilityCost

    try:
        return replace(cost, pay_life=0) == ActivatedAbilityCost(mana=dict(cost.mana))
    except (TypeError, ValueError):
        return False


def choose_foreign_activation_action(
    game: Game, player_index: int
) -> ActivationAction | None:
    """The best ability this seat may activate on a permanent **another seat
    controls** (CR 602.1b), or None.

    A separate chooser from ``ai_abilities.choose_activation_action`` because the two
    read one program in opposite directions: an effect that removes or hampers
    its own source is a loss to the source's controller (which that chooser now
    skips) and the whole point to anyone else. What the effect is for is
    `ai_valuation.foreign_activation_use`:

    * **removes_source** is wanted whenever it is affordable — mana from the
      board, life only above :data:`FOREIGN_ACTIVATION_LIFE_RESERVE`;
    * **shrinks_source** is wanted only when the shrink kills the creature
      outright, the one hamper that needs nothing lined up behind it;
    * **aimed** is the activator's own ability in every respect but where it
      is printed (CR 113.8), so it is targeted and scored exactly as
      ``ai_abilities.choose_activation_action`` would score it on this seat's
      board.

    Every gate the engine will ask is asked first, so a proposal is not a
    refused activation every turn: the permission (`activation_permission_
    denial`), the printed timing ("only as a sorcery", "only during their
    turn", `activation_restrictions.activation_denial`), a board-wide ban, and
    CR 602.2b's target gate.
    """
    # CR 723.5: a seat another player decides for plays nothing
    # optional for itself (``ai_player_control``'s measured policy).
    if plays_for_another(game, player_index):
        return None
    from .activation_permissions import card_widens_activation

    player = game.players[player_index]
    best: ActivationAction | None = None
    for source_seat, permanent in game.permanents_with_controller():
        if source_seat == player_index or game.players[source_seat].lost:
            continue
        if not card_widens_activation(permanent.effective_card):
            continue
        permanent_index = game.battlefield_index_of(permanent)
        if permanent_index is None:
            continue
        if global_activation_ban(game, permanent):
            continue
        # ``usable_abilities_of``: empty for a permanent that lost its
        # abilities — "loses all abilities", which this asked inline, and a
        # land whose type was set (CR 305.7), which it did not.
        for ability_index, ability in enumerate(game.usable_abilities_of(permanent)):
            candidate = _foreign_activation_candidate(
                game, player_index, player, source_seat, permanent,
                permanent_index, ability_index, ability,
            )
            if candidate is not None and (best is None or candidate.score > best.score):
                best = candidate
    return best


def _foreign_activation_candidate(
    game: Game, player_index: int, player: PlayerState, source_seat: int,
    permanent: Permanent, permanent_index: int, ability_index: int, ability,
) -> ActivationAction | None:
    """One ability on another seat's *permanent*, as an action — or None."""
    instruction = ability.instruction
    if instruction is None or not ability.supported or is_mana_ability(instruction):
        return None
    line = ability.source_line or ""
    if activation_permission_denial(game, player_index, permanent, line):
        return None
    if activation_denial(game, player_index, permanent, line):
        return None
    if not _plain_activation_cost(ability.cost):
        return None
    life_cost = int(ability.cost.pay_life or 0)
    if life_cost and player.life - life_cost < FOREIGN_ACTIVATION_LIFE_RESERVE:
        return None

    use = foreign_activation_use(ability)
    target = source_seat
    target_permanent_index: int | None = None
    if use == "removes_source":
        score = FOREIGN_REMOVAL_SCORE + _permanent_value(permanent)
    elif use == "returns_source":
        # The owner plays it again, so this is tempo rather than removal:
        # worth it when recasting costs them at least what bouncing cost us,
        # or when the permanent is an untapped creature standing in front of
        # an attack this seat can make this turn. Without the second clause a
        # {4} bounce of a three-mana wall is never worth it; without the
        # first, a seat with nobody to attack with bounced it every turn and
        # its owner recast it every turn (PCY's Quicksilver Wall, measured).
        paid = sum(int(value or 0) for value in ability.cost.mana.values())
        clears_a_blocker = (
            permanent.is_creature and not permanent.tapped
            and bool(legal_attackers(game, player_index, against=source_seat))
        )
        if float(permanent.card.cmc or 0) < paid and not clears_a_blocker:
            return None
        score = FOREIGN_REMOVAL_SCORE + float(permanent.card.cmc or 0)
    elif use == "shrinks_source":
        change = source_toughness_change(instruction) or 0
        if not permanent.is_creature or (
            permanent.effective_toughness + change > permanent.damage_marked
        ):
            return None
        score = FOREIGN_KILL_SCORE + _permanent_value(permanent)
    elif use == "aimed":
        spec = derive_activation_spec(ability) or {}
        described = ((instruction.payload or {}).get("targets") or {}).get("filter") or {}
        if described.get("controller") is not None:
            # "Target creature **you control**": the enumeration below runs
            # from the source's seat, so a printed seat would be read as the
            # wrong player's. Declined rather than mis-aimed.
            return None
        if spec.get("kind") == "player":
            target = _choose_target_for_instruction(instruction, player_index, game)
        elif spec.get("kind") in _FOREIGN_OBJECT_KINDS:
            legal = game.activation_target_spec(
                source_seat, permanent_index, ability_index=ability_index,
            ).get("valid_targets") or []
            perms = [t for t in legal if t.get("kind") == "permanent"]
            # Read step by step, so a sequence's grant is aimed by the grant
            # (`ai_target_sides.ability_target_side`), and **only** a side the
            # program states: an object effect with none is a coin flip
            # between the two boards, and on another seat's ability the wrong
            # board is a gift paid for.
            side = ability_target_side(instruction)
            if side == "you":
                # Asked of the step that names the target, for the reason
                # the side is: a wrapper denies nothing.
                if ability_denies_its_target(instruction):
                    return None
                perms = [t for t in perms if t["seat"] == player_index]
            elif side == "opponent":
                perms = [t for t in perms if t["seat"] != player_index]
            else:
                return None
            if not perms:
                return None

            def _power(t):
                perm = game.permanent_at(t["seat"], t["index"])
                return perm.effective_power if perm is not None else 0

            chosen = max(perms, key=_power)
            target = chosen["seat"]
            target_permanent_index = chosen["index"]
        else:
            return None
        score = _score_activation(game, player_index, instruction, target)
    else:
        return None

    if game.activation_target_refusal(
        player_index, permanent, ability,
        target_player_index=target,
        target_permanent_index=target_permanent_index,
    ) is not None:
        return None
    if game.activation_target_requirement_refusal(
        player_index, permanent, ability,
        target_player_index=target,
        target_permanent_index=target_permanent_index,
    ) is not None:
        # An opponent's Flagbearer demands a target this announcement does not
        # name. Not proposed: the gate would refuse it with nothing paid.
        return None

    land_taps: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()
    required = dict(ability.cost.mana)
    if game.enforce_mana_costs and any(required.values()):
        plan = _plan_land_taps(game, player, required)
        if plan is None:
            return None
        land_taps, tap_colors = plan
    if score <= 0.0:
        return None
    return ActivationAction(
        permanent_name=permanent.card.name,
        permanent_index=permanent_index,
        target_player_index=target,
        land_tap_indices=land_taps,
        score=score,
        target_permanent_index=target_permanent_index,
        land_tap_colors=tap_colors,
        source_controller_index=source_seat,
        ability_index=ability_index,
    )
