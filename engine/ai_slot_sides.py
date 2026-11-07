"""Which board each target of an announcement that names **several** belongs
on — slot by slot, role by role — and what a divided spell divides.

``ai_target_sides`` answers for one target: what an instruction does to the
object or the player it names. An announcement naming several asks that
question once per target, of the step that spends it, and two targets of one
instruction can belong on two sides (an exchange of control, a redirect, a
keyword moved from one creature to another):

* a several-target instruction, slot by slot
  (:func:`several_target_slot_sides`);
* a roles announcement, role by role — a spell's
  (:func:`role_target_sides`) and an activated ability's
  (:func:`ability_role_target_sides`) — and a loop over an announcement's
  roles (:func:`announced_roles_loop_side`);
* a divided spell's shares (:func:`divided_shape`).

Each reading ends in the one-target reading (``ai_target_sides._effect_side``,
``_PRINTED_SEATS``, ``activation_target_side``), so a kind classified there
is classified here; what this module adds is which step spends which target.
The policy's choosers ask these (``ai_targets``, ``ai_divisions``,
``ai_abilities``) and choose among the engine's own candidates; nothing here
names a permanent.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CardDefinition
from .oracle import OracleInstruction, compile_card_oracle
from .oracle_types import cost_target_count
from .ai_target_sides import (
    _PRINTED_SEATS,
    _effect_side,
    _pt_delta_sign,
    _seat_step_side,
    activation_target_side,
)
from .ai_weighed_cast import mode_considered


@dataclass(frozen=True)
class DividedShape:
    """What a divided spell (CR 601.2d) divides, in the terms the AI asks about.

    Three facts, all read off the compiled program, because "which cards does
    this reach" is this module's question and the answer must not be a list of
    names: the division is announced as the spell is cast, so a policy that
    guessed would announce Contagion's ``-2/-1`` counters onto its own
    creatures and Bounty of the Hunt's ``+1/+1`` onto the opponent's.
    """

    #: Whose permanents the shares should land on — "you", "opponent", or None
    #: for no preference. Derived from the *sign* of a placed counter where the
    #: instruction places one, and otherwise from the effect's category, which
    #: is the same reading ``ai_target_sides.activation_target_side`` makes.
    side: str | None = None
    #: Whether a share too small to matter is wasted. True for damage, which is
    #: measured against a toughness: four damage split one apiece over four
    #: creatures kills none of them, while four +1/+1 counters split the same
    #: way are four counters either way. It is a fact about the effect, not a
    #: policy — what the AI *does* about it is stated in ``ai_policy``.
    thresholded: bool = False
    #: Whether the card names a whole board rather than offering a choice —
    #: an evenly-divided description whose filter names a controller. Dwarven
    #: Catapult ("…among **all creatures target opponent controls**") was the
    #: printing; since round kg it lowers to the sweep it is — the opponent the
    #: one target, the creatures a set — so no division in the pool sets this.
    #: Read as an evenly-divided description whose filter names a controller:
    #: an evenly-divided spell's caster announces no shares, so the target list
    #: is the only choice it has, and a filter bounding that list to one
    #: player's board is the card making it.
    whole_board: bool = False
    #: One side per printed target, for the division whose targets are **not
    #: interchangeable** — "The next X damage that would be dealt to target
    #: creature, planeswalker, or player this turn is dealt to **another**
    #: target … instead" (Captain's Maneuver): entry 0 is spared and entry 1
    #: takes what it was spared. Empty for every other division in the pool,
    #: whose targets all receive the same thing and so share :attr:`side`.
    #:
    #: Read off ``_SLOT_ROLE_SIDES``, the table the several-target channel
    #: already answers "what does this kind do to each slot" from (Kor Chant is
    #: this sentence with a chosen source), and only where the description
    #: prints exactly that many targets. With one side for both ends the policy
    #: announced two opposing objects: it shielded an opponent and sent the
    #: damage to another thing of theirs.
    slot_sides: tuple[str | None, ...] = ()


def divided_shape(program, instructions=None) -> DividedShape | None:
    """*program*'s divided step described, or None when it divides nothing.

    *instructions* is the program as one particular cast will run it
    (``targeting.instructions_as_announced``), for a caller that has CR 601.2b's
    answer in hand: a card whose divided step sits under a ``was_kicked`` arm
    (Magma Burst, Pollen Remedy) divides for one announcement and not for
    another, and its card-wide reading finds nothing. None reads the program's
    own steps, which is every caller asking about the card.
    """
    from .divided_damage import CHOSEN, divided_instruction
    from .grammar.lowering.categories import INSTRUCTION_CATEGORIES
    from .pt import pt_counter_deltas

    instruction = divided_instruction(
        program.instructions if instructions is None else instructions
    )
    if instruction is None:
        return None
    described = instruction.payload.get("targets") or {}
    category = INSTRUCTION_CATEGORIES.get(instruction.kind)
    side = None
    deltas = pt_counter_deltas(str(instruction.payload.get("counter") or ""))
    if deltas is not None:
        # The sign, exactly as `several_target_slot_sides` reads a slot's P/T
        # delta below: "+1/+1" is a gift and "-2/-1" is removal, and the two
        # compile to one instruction kind whose category ("counters") is right
        # about the family and silent about the side.
        side = "you" if sum(deltas) > 0 else "opponent" if sum(deltas) < 0 else None
    else:
        side = activation_target_side(instruction)
    slot_sides = _SLOT_ROLE_SIDES.get(instruction.kind, ())
    if described.get("target_count") != len(slot_sides):
        slot_sides = ()
    return DividedShape(
        side=side,
        thresholded=category == "damage",
        whole_board=(
            described.get("division") != CHOSEN
            and bool((described.get("filter") or {}).get("controller"))
        ),
        slot_sides=slot_sides,
    )


def _several_target_instruction(program, instructions=None):
    """The one instruction in *program* whose description names several targets.

    *instructions* is the program as one particular cast will run it
    (``targeting.instructions_as_announced``), for a caller holding CR 601.2b's
    answer; None reads the program's own steps.
    """

    def walk(instructions):
        for instruction in instructions:
            targets = instruction.payload.get("targets")
            count = targets.get("count") if isinstance(targets, dict) else None
            # A ``dict`` count is an announcement sized by a CR 601.2b optional
            # additional cost (Primitive Justice). It qualifies whatever its
            # base is, where a printed number has to exceed one: a *one*-target
            # announcement the caster must make explicitly still needs a side
            # picked for it, because the several-target handlers have no
            # resolution-time fallback to a board scan the way the single-target
            # ones do.
            if isinstance(count, dict) or (isinstance(count, int) and count > 1):
                return instruction
            for key in ("steps", "then", "else", "action"):
                nested = instruction.payload.get(key)
                if isinstance(nested, (list, tuple)):
                    found = walk(nested)
                    if found is not None:
                        return found
        return None

    return walk(program.instructions if instructions is None else instructions)


#: What a several-target instruction does to **each** of its slots, for the
#: kinds whose slots are not interchangeable and whose payload carries no
#: number to read the difference off (``pump_targets_until_eot`` carries its
#: ``slots``). One entry per slot, "you" / "opponent" / None for a slot the
#: effect only *refers* to.
#:
#: Keyed by instruction kind — a claim about what the compiled effect does to
#: the object in each position, never about which card printed it — and it is
#: the reason the homogeneous fallback below could not simply be
#: ``instruction_target_side`` for everything: the kind-level reading gives one
#: side for the whole instruction, and these give two.
_SLOT_ROLE_SIDES: dict[str, tuple[str | None, ...]] = {
    # "It deals damage equal to its power to **another target creature**"
    # (Deadshot). Slot 1 is the creature damaged; slot 0 only deals it, and
    # whichever board supplies the dealer the damage lands the same.
    "target_bites_target": (None, "opponent"),
    # "All damage that would be dealt this turn to target creature you control
    # … is dealt to **another target creature** instead" (Kor Chant). Slot 0 is
    # spared, slot 1 takes what it was spared.
    "redirect_chosen_source_damage_between_targets_until_eot": ("you", "opponent"),
    # "Exchange control of target artifact or creature and **another target
    # permanent**" (Legerdemain). One is given and one is taken; two of the
    # caster's own is an exchange of nothing.
    "exchange_control_of_targets": ("you", "opponent"),
    # "Target creature with the chosen ability **loses it** and another target
    # creature **gains it**" (Phyrexian Splicer). Slot 0 is robbed, slot 1 is
    # given what it had.
    "move_chosen_keyword_between_targets": ("opponent", "you"),
    # "The next X damage that would be dealt to target creature, planeswalker,
    # or player this turn is dealt to **another target** creature,
    # planeswalker, or player instead" (Captain's Maneuver). Kor Chant's two
    # ends without the chosen source, announced on the divided channel
    # (``target_count: 2``) rather than the several-target one — so it is
    # :func:`divided_shape` that reads this row, as ``DividedShape.slot_sides``.
    "redirect_next_damage_between_targets_until_eot": ("you", "opponent"),
}

#: Steps that act on a recorded group (``permanents_from``) and whose category
#: is filed by where the object goes rather than by what that does to it: an
#: exile and a return to hand are ``zones`` beside every other card movement.
_RECORDED_DENIAL_KINDS = frozenset({
    "exile_recorded_permanent",
    "return_recorded_permanents_to_hand",
})


def _recorded_group_side(program, chooser, instructions=None) -> str | None:
    """Which board a "Choose two target creatures controlled by the same
    player" announcement (``choose_target_permanents``) belongs on: the side of
    the steps that go on to act on what it recorded, the denial winning.

    The chooser itself does nothing to its targets — it records them — so no
    reading of its own kind has an answer: "Their controller chooses and
    sacrifices one of them. Return the other to its owner's hand." (Barrin's
    Spite) is two denials on the group, and "Exile one of those creatures and
    put two +1/+1 counters on the other" (Cannibalize) is a removal and a gift,
    which is ``ai_target_sides.spell_target_side``'s rule over again: one
    hampering step makes the target the opponent's.
    """

    def siblings(steps):
        steps = tuple(steps or ())
        for position, step in enumerate(steps):
            if step is chooser:
                return steps[position + 1:]
            for key in ("steps", "then", "else", "action"):
                nested = (step.payload or {}).get(key)
                if isinstance(nested, (list, tuple)):
                    found = siblings(nested)
                    if found is not None:
                        return found
        return None

    later = siblings(program.instructions if instructions is None else instructions)
    sides: set[str] = set()
    for step in later or ():
        if not (step.payload or {}).get("permanents_from"):
            continue
        if step.kind in _RECORDED_DENIAL_KINDS:
            sides.add("opponent")
            continue
        sign = _pt_delta_sign(step)
        side = ("you" if sign > 0 else "opponent") if sign else activation_target_side(step)
        if side is not None:
            sides.add(side)
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


def _bare_sibling_side(program, instruction, instructions=None) -> str | None:
    """The side of the steps printed **before** a several-target instruction in
    the same sentence run that name no target of their own — the legacy shape
    for "the target", which is the announcement's first.

    "**Tap target creature.** It deals damage equal to its power to another
    target creature." (Deadshot.) The bite's own kind says nothing about the
    creature that deals it; the tap in front of it does, and it is a denial.
    """

    def earlier(steps):
        steps = tuple(steps or ())
        for position, step in enumerate(steps):
            if step is instruction:
                return steps[:position]
            for key in ("steps", "then", "else", "action"):
                nested = (step.payload or {}).get(key)
                if isinstance(nested, (list, tuple)):
                    found = earlier(nested)
                    if found is not None:
                        return found
        return None

    sides = {
        _effect_side(step)
        for step in earlier(program.instructions if instructions is None else instructions) or ()
        if not isinstance((step.payload or {}).get("targets"), dict)
    } - {None}
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


def several_target_slot_sides(program, instructions=None) -> tuple[str | None, ...]:
    """Which board each slot of a several-target spell should be picked from.

    Derived, never named: the compiled program says which slots are restricted by
    controller and, where they are not, whether the slot's own effect is a
    benefit or a penalty. Rookie Mistake's two slots are both a bare "target
    creature", so only the sign of the P/T delta distinguishes "the one I pump"
    from "the one I shrink" — and a chooser reading neither puts both on the
    caster's own board.

    Four readings, most specific first, each about **the step that spends the
    slot**:

    * the slot's own printed controller ("target creature **you control**");
    * the slot's own numbers (``slots``, a per-slot P/T delta);
    * a kind whose slots are not interchangeable (``_SLOT_ROLE_SIDES``), and a
      "choose two target creatures" whose effect is the steps after it
      (:func:`_recorded_group_side`);
    * otherwise every slot gets the same effect, and what that effect does to
      its target is exactly the question
      ``ai_target_sides.instruction_target_side`` answers for a one-target
      spell.

    **The last one used to be a table of its own** (``_SLOT_DISPOSITION``: tap,
    destroy, exile, return to hand, each added by the round that found the AI
    aiming it at its own board), and a table that restates another one lags
    it. Plow Under put two of its caster's lands on top of their library,
    Panic Attack kept three of its own creatures from blocking, Jagged
    Lightning and Volcanic Salvo burned the caster's creatures and Sick and
    Tired shrank them — every one a kind the one-target reading had already
    classified as a denial.

    Returns one entry per slot: "you", "opponent", or None for no preference.
    *instructions* is the program as one particular cast will run it
    (``targeting.instructions_as_announced``); None reads the program's own.
    """
    instruction = _several_target_instruction(program, instructions)
    if instruction is None:
        return ()
    targets = instruction.payload.get("targets") or {}
    count = targets.get("count")
    if isinstance(count, dict):
        # An announcement sized by a CR 601.2b optional additional cost: the
        # base count, which is the floor of what any announcement names. Every
        # slot of such an instruction gets one effect, so a caller that names
        # more reads the last entry for the rest.
        count = cost_target_count(count, {}) or 0
    if not isinstance(count, int) or count < 1:
        return ()
    filters = targets.get("filters") or [targets.get("filter") or {}] * count
    slots = tuple(instruction.payload.get("slots") or ())
    per_slot = _SLOT_ROLE_SIDES.get(instruction.kind)
    if instruction.kind == "choose_target_permanents":
        shared = _recorded_group_side(program, instruction, instructions)
    elif per_slot is None and not slots and targets.get("kind") == "object":
        # Only an object on a battlefield has a board to be picked from: a
        # several-target *graveyard* return names cards, and whose pile they
        # come from is the printed phrase's business.
        shared = _effect_side(instruction)
    elif (
        instruction.kind == "exile_cards_from_graveyard"
        and instruction.payload.get("graveyard_owner") == "chosen"
    ):
        # …with one exception, the one printing that leaves the pile to the
        # chooser: "Exile up to three target cards from **a single**
        # graveyard" (Ebony Charm, Rapid Decay, Decompose). Taking cards out
        # of a graveyard is a denial, and the fallback's own-pile-first would
        # empty the caster's.
        shared = "opponent"
    else:
        shared = None
    sides: list[str | None] = []
    for index in range(count):
        described = filters[index] if index < len(filters) else {}
        controller = described.get("controller")
        if controller in _PRINTED_SEATS:
            sides.append(_PRINTED_SEATS[controller])
            continue
        if index < len(slots):
            slot = slots[index]
            delta = sum(
                value
                for value in (slot.get("power"), slot.get("toughness"))
                if isinstance(value, int)
            )
            sides.append("opponent" if delta < 0 else ("you" if delta > 0 else None))
            continue
        if per_slot is not None:
            sides.append(per_slot[index] if index < len(per_slot) else None)
            continue
        sides.append(shared)
    if per_slot is not None and sides and sides[0] is None:
        sides[0] = _bare_sibling_side(program, instruction, instructions)
    return tuple(sides)


def role_target_sides(
    card: CardDefinition, optional_cost_payments: dict | None = None
) -> tuple[str | None, ...]:
    """Which board each **role** of a roles announcement should be picked from
    — one entry per role of the cast's spec, in role order: "you", "opponent",
    or None for no preference (and for a role whose object is a seat).

    :func:`several_target_slot_sides` for the other shape a several-target
    announcement comes in. A roles spell is announced together and *spent* a
    step at a time ("Return target creature to its owner's hand. Then return
    **another target creature** … unless its controller pays {1}", Withdraw),
    and ``ai_target_sides.spell_target_side`` reads only a step whose
    ``targets`` is an object description — so a roles spell had no side at all, the chooser took
    the first legal chain, and the first board in seat order is the caster's
    own. Withdraw returned two of its caster's creatures; Rushing River and
    Falling Timber inherit the template; Fumarole and Plague Spores destroyed
    their caster's own creature and land; Lunge and Shower of Sparks burned
    their caster's own creature.

    Read off the step that spends each role — the one whose ``targets.role``
    names it, or every roles step that names none of its own (one instruction
    acting on every role: "Destroy target creature **and** target land") —
    through the reading a one-target spell gets, the denial winning where two
    steps spend one role. Three roles keep None:

    * a **seat** (``role_is_seat``) — the cast's own seat choice answers it;
    * a role the instruction only refers to (``subject_role`` names another);
    * a role with a **dependency** ("that target Wall blocked this turn"): the
      relation already decides which board it can be on.

    A positional role (``slot_N``, a several-target instruction whose slots
    print different restrictions) is that instruction's own slot.

    *optional_cost_payments* is CR 601.2b's answer for the cast being built: a
    kicked Rushing River announces two roles and an unkicked one none.
    """
    from .targeting import (derive_cast_spec, instructions_as_announced,
                            spec_roles)
    from .target_roles import payload_own_role, role_dependency, role_is_seat

    program = compile_card_oracle(card)
    # ...and CR 601.2b's other answer, the mode being weighed
    # (:func:`ai_weighed_cast.considering_mode`): Hull Breach's third bullet is a roles
    # announcement and its first two are not, and Reign of Chaos is two roles
    # announcements over different pairs.
    mode_index = mode_considered(card)
    roles = spec_roles(
        derive_cast_spec(
            card, program, optional_cost_payments=optional_cost_payments,
            mode_index=mode_index,
        )
    )
    if not roles:
        return ()
    run = instructions_as_announced(
        card, program, optional_cost_payments or {}, mode_index=mode_index,
    )
    slot_sides = several_target_slot_sides(program, run)
    return _sides_of_roles(roles, run, slot_sides)


def ability_role_target_sides(card: CardDefinition, ability) -> tuple[str | None, ...]:
    """:func:`role_target_sides` for an **activated ability**'s roles — one
    entry per role of ``targeting.derive_activation_spec(ability)``.

    The same derivation over the other place a roles announcement comes from
    (CR 602.2b sends an ability's targets through CR 601.2c): the roles are
    the ability's own and the run is its one instruction. The activation
    chooser took a single side for the whole chain, so "target creature with
    the chosen ability loses it and **another target creature** gains it"
    (Phyrexian Splicer) named two of the activator's own creatures.
    """
    from .targeting import derive_activation_spec, spec_roles

    roles = spec_roles(derive_activation_spec(ability))
    if not roles or ability.instruction is None:
        return ()
    run = (ability.instruction,)
    return _sides_of_roles(
        roles, run, several_target_slot_sides(compile_card_oracle(card), run)
    )


def announced_roles_loop_side(card: CardDefinition) -> str | None:
    """The side every role of a loop over an announcement's roles is picked
    from — "Choose any number of target players or planeswalkers. For each of
    them, … deals damage … to that player or planeswalker" (Kaboom!) — read off
    what the loop's body does to its object (``ai_target_sides._effect_side``,
    the denial winning); None for a card with no such loop.

    The roles are seat-or-permanent unions, which :func:`_sides_of_roles`
    leaves sideless (a seat role's side is ``_preferred_role_option``'s), and
    the body spends no role by name — the loop scopes it — so neither reading
    above can see that every one of these targets is hit.
    """
    for instruction in compile_card_oracle(card).instructions:
        payload = instruction.payload or {}
        iterator = payload.get("iterator") or {}
        if instruction.kind != "for_each":
            continue
        if iterator.get("players") == "any_number_of_target_players":
            # "**Any number of target players** each gain life …" (Reward the
            # Faithful) / "… each discard …" (Cabal Conditioning). Every role is
            # a seat, the caster's included, and the body is done *to* each
            # one — so the side is the seat reading of what it does: a gift
            # names the caster, a denial the opponents. Read as sideless, the
            # walk took the caster's own seat first (it is first in seat order
            # whenever the caster is seat 0, and the only one when it is the
            # last seat): Cabal Conditioning made its caster discard, or was
            # never cast. Wheel and Deal's chain names only opponents and has
            # no side to choose.
            sides = {
                _seat_step_side(step) for step in payload.get("effect") or ()
            } - {None}
            return "opponent" if "opponent" in sides else "you" if "you" in sides else None
        if not iterator.get("announced_roles"):
            continue
        sides = {_effect_side(step) for step in payload.get("effect") or ()} - {None}
        return "opponent" if "opponent" in sides else "you" if "you" in sides else None
    return None
def _sides_of_roles(roles, run, slot_sides) -> tuple[str | None, ...]:
    """The side each of *roles* is picked from, read off the steps of *run*
    that spend it — the body :func:`role_target_sides` and
    :func:`ability_role_target_sides` share."""
    from .target_roles import payload_own_role, role_dependency, role_is_seat

    spenders: list[OracleInstruction] = []

    def walk(instructions) -> None:
        for instruction in instructions:
            payload = instruction.payload or {}
            targets = payload.get("targets")
            if isinstance(targets, dict) and targets.get("kind") == "roles":
                spenders.append(instruction)
            for key in ("steps", "then", "else", "action", "otherwise"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)):
                    walk(nested)

    walk(run)
    sides: list[str | None] = []
    for position, role in enumerate(roles):
        name = role.get("role")
        if role_is_seat(role):
            sides.append(None)
            continue
        if isinstance(name, str) and name == f"slot_{position}":
            sides.append(slot_sides[position] if position < len(slot_sides) else None)
            continue
        found: set[str] = set()
        for step in spenders:
            payload = step.payload or {}
            entry = next(
                (
                    described for described in payload["targets"].get("roles") or ()
                    if isinstance(described, dict) and described.get("role") == name
                ),
                None,
            )
            if entry is None or role_dependency(entry)[0] is not None:
                continue
            acted_on = payload_own_role(payload) or payload.get("subject_role")
            if acted_on is not None and acted_on != name:
                continue
            side = _PRINTED_SEATS.get(
                (entry.get("filter") or {}).get("controller")
            ) or _effect_side(step)
            if side is not None:
                found.add(side)
        sides.append(
            "opponent" if "opponent" in found else "you" if "you" in found else None
        )
    return tuple(sides)


__all__ = [
    "DividedShape",
    "ability_role_target_sides",
    "announced_roles_loop_side",
    "divided_shape",
    "role_target_sides",
    "several_target_slot_sides",
]
