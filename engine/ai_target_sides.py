"""Which side of the table a target belongs on — an object's, a seat's, a
slot's, a role's — read off the compiled program.

"opponent" for an effect that hampers what it names, "you" for one that
helps it, None where the program does not say and the score decides.
**Per kind, never per card**: an instruction's category answers where it can
(``INSTRUCTION_CATEGORIES``), the kinds whose category cannot are named
(``_OWN_KINDS``, ``_OPPONENT_KINDS``, ``_NO_SIDE_KINDS``), and a P/T change
answers by its own sign (:func:`_pt_delta_sign`) — so an invented card
printing any of these templates is aimed correctly the day it is ingested.
This is where ``card.name == "Disenchant"`` went (``ai_valuation``'s
docstring has what it cost).

The same question for every announcement that names something:

* a spell's object target and the player it names
  (:func:`spell_target_side`, :func:`spell_seat_side`,
  :func:`spell_denies_its_own_target`), and whether that player is one the
  effect helps (:func:`cast_helps_the_player_it_names` — one derivation, read
  by the AI's tie-break and the web route's default seat alike);
* an activated ability's (:func:`activation_target_side`,
  :func:`ability_target_side`, :func:`ability_seat_side`), the counters it
  marks for harm, and whether it denies its target;
* a permanent spell's entry trigger (:func:`entry_trigger_target_side`,
  :func:`entry_trigger_seat_side`);
* several targets and roles, slot by slot (:func:`several_target_slot_sides`,
  :func:`role_target_sides`, :func:`ability_role_target_sides`) — two sides
  for one instruction where the program prints two — and what a divided
  spell divides (:func:`divided_shape`).

The policy's choosers ask these and choose among the engine's own candidates
(``ai_targets``); nothing here names a permanent.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CardDefinition
from .oracle import OracleInstruction, compile_card_oracle
from .oracle_types import cost_target_count
from .ai_weighed_cast import (
    SPELL_TYPES,
    mode_considered,
    _spell_instructions,
    _effect_steps,
)


#: The battlefield an object-targeted activated ability aims at, by the
#: instruction's migration category — so which cards a heuristic reaches stays
#: derived from the compiled program (CLAUDE.md's ai_valuation rule) rather than
#: named. "opponent" for removal/damage, "you" for the buffs a player puts on
#: their own creatures; None means no side preference (the picker/handler owns it).
_OPPONENT_CATEGORIES = frozenset({"damage", "destruction", "tapping", "counterspells"})
_OWN_CATEGORIES = frozenset({"pump", "counters", "regeneration", "evasion", "attachments", "characteristics",
                             # CR 615: a shield is a gift. It joined at
                             # Visions' promotion gate, where Remedy —
                             # the pool's only *divided* prevention
                             # spell — was the card that had no side to
                             # divide between. Aiming a prevention
                             # effect at an opponent's permanent is
                             # never what the card is for, so the
                             # category answers where it used to be
                             # silent, for all 57 cards that print one.
                             "prevention"})


#: Kinds whose category is right about the family and wrong about the side.
#: A CR 614.9 redirect is categorised ``damage`` because the damage is still
#: *dealt* — the whole distinction ``engine/damage_redirects.py`` exists for —
#: but a counted one moves damage **off** the permanent it names, so the seat
#: that wants to be named is the activating player's own. Aimed by the category
#: alone, Daughter of Autumn shields an opponent's white creature: the ability
#: resolves, the record is armed, and it protects the wrong board.
#:
#: Keyed on the instruction kind, which is a claim about the compiled program
#: rather than about a card, and narrow on purpose: the *other* redirects in the
#: pool name the source whose damage moves ("target attacking creature"), which
#: really is the opponent's.
_OWN_KINDS = frozenset({
    "redirect_next_damage_to_source_until_eot",
    # The same shape with the source chosen at resolution or left open: "All
    # damage that would be dealt to target creature this turn is dealt to you
    # instead" (Sivvi's Valor), "...to target creature this turn by a source of
    # your choice is dealt to this creature instead" (Oracle's Attendants). The
    # named creature is the one *spared*, so it is the caster's own; the
    # ``damage`` category had all three aimed at the opponent's board.
    "redirect_damage_off_target_until_eot",
    "redirect_chosen_source_damage_off_target_until_eot",
    # "Untap target permanent" is categorised ``tapping`` beside "tap target
    # permanent", which is the family and the opposite side: an untap is a
    # second use of something, and every card in the pool printing the bare
    # template (Jandor's Saddlebags, Candelabra of Tawnos, Ley Druid, Infuse)
    # means one of its controller's own.
    "untap_target_permanent",
    "untap_target_land",
})


#: Kinds whose effect on the object they target is a **denial** — the target is
#: worse off for it — and whose category is silent or wrong about that. Every
#: entry here had the AI aiming the effect at its own board, measured at NEM's
#: wave 2: "Target creature can't attack or block this turn" (Off Balance) had
#: no category answer at all, so the spell and every ability printing it took
#: the caster's seat on a score tie and the AI kept its own creature home.
#:
#: The question is "does this hamper its target", answered per *kind* — what the
#: compiled program does — and never per card, so an invented card printing any
#: of these templates is aimed correctly the day it is ingested.
_OPPONENT_KINDS = frozenset({
    # CR 506-509 combat restrictions on the named creature.
    "target_cant_attack_until_eot",
    "target_cant_block_until_eot",
    "target_cant_block_source_until_eot",
    "force_target_to_block_until_eot",
    "become_blocked",
    # CR 615 aimed at what the target deals rather than what it is dealt:
    # "Prevent all combat damage that would be dealt by target creature"
    # (Subdue, Warning, Lady Evangela). ``prevention`` called it a shield.
    "prevent_damage_by_target_until_eot",
    # A rider stripped off the target: "can't be regenerated" (Gravebind),
    # "loses all abilities" (Humble), "loses flying" (Radjan Spirit). The
    # ``regeneration`` / ``pump`` categories read them as the gifts they undo.
    "deny_regeneration_to_target",
    "remove_target_abilities_until_eot",
    "remove_target_keyword_until_eot",
    # CR 613 layer 2: taking a permanent is never aimed at one's own.
    "gain_control_of_target",
    "gain_control_until_eot",
    "steal_target_linked_to_source",
    "bid_life_for_control",
    # Removal one zone over from destroy: exile, the library, the hand.
    "exile_target_permanent",
    "exile_until_leaves_or_untaps",
    # …and the same removal spelled as phasing: "target creature phases out
    # until this enchantment leaves the battlefield" (Oubliette). The kind has
    # no category to answer for it.
    "phase_out_target_creature_until_source_leaves",
    "put_target_on_library_top",
    "shuffle_target_permanent_into_library",
    "bounce_target_creature",
})


def activation_target_side(instruction: OracleInstruction) -> str | None:
    """"opponent" / "you" / None — whose permanent an object-targeted activated
    ability should be aimed at, derived from ``INSTRUCTION_CATEGORIES`` and the
    kinds whose category cannot answer (``_OWN_KINDS``, ``_OPPONENT_KINDS``)."""
    from .grammar.lowering.categories import INSTRUCTION_CATEGORIES

    kind = getattr(instruction, "kind", None)
    if kind in _OWN_KINDS:
        return "you"
    if kind in _OPPONENT_KINDS:
        return "opponent"
    category = INSTRUCTION_CATEGORIES.get(kind)
    if category in _OPPONENT_CATEGORIES:
        return "opponent"
    if category in _OWN_CATEGORIES:
        return "you"
    return None


#: Targeted kinds whose category is about something *other* than the target,
#: so it must not decide the side. "Destroy all creatures blocked by target
#: Wall" (Glyph of Reincarnation) and "Tap all creatures blocking target
#: attacking creature" (Feint) name the caster's own creature as the reference
#: point for an effect on the opponent's; "tap or untap target permanent"
#: (Twiddle) is both directions at once. No preference: the score decides, as
#: it did before any of this was derived.
_NO_SIDE_KINDS = frozenset({
    "destroy_all_matching",
    "tap_creatures_blocking_target",
    "tap_or_untap_target",
})


#: The targeted kinds whose ``power`` / ``toughness`` / ``counter`` payload is a
#: **change** to the target's P/T. Named because the same keys mean a *base*
#: value elsewhere ("has base power and toughness 0/1", Humble), where a
#: positive number is no gift at all.
_PT_DELTA_KINDS = frozenset({
    "pump_target_creature_until_eot",
    "pump_targets_until_eot",
    "pump_target_while_source_tapped",
    "add_counter_to_target",
})


def _pt_delta_sign(instruction: OracleInstruction) -> int:
    """+1 / -1 / 0: whether the P/T change *instruction* makes is a gift or a
    penalty, read off its own payload.

    The sign is what decides the side for the P/T families, whose category
    (``pump``, ``counters``) is right about the family and silent about the
    direction: "Target creature gets +3/+3" (Giant Growth) and "…gets -5/-0"
    (Shrink) are one instruction kind. Three payload spellings: printed numbers,
    an X with its ``*_negative`` flag, and a counter's own "+1/+1" / "-1/-0".
    """
    from .pt import pt_counter_deltas

    if instruction.kind not in _PT_DELTA_KINDS:
        return 0
    payload = instruction.payload or {}
    total = 0
    for key in ("power", "toughness"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total += value
        elif value is not None and payload.get(f"{key}_negative") is not None:
            total += -1 if payload.get(f"{key}_negative") else 1
    counter = payload.get("counter")
    if isinstance(counter, str):
        deltas = pt_counter_deltas(counter)
        if deltas is not None:
            total += sum(deltas)
    return (total > 0) - (total < 0)


def instruction_target_side(instruction: OracleInstruction) -> str | None:
    """Whose permanent the object *instruction* targets should be — "you",
    "opponent", or None for no preference.

    Three readings, most specific first: the printed noun phrase's own
    controller ("target creature **you control**"), the sign of a P/T change
    (Giant Growth against Shrink), and then the kind/category reading
    :func:`activation_target_side` makes. One reader for a spell's targets and
    an ability's, because what an instruction does to its target does not depend
    on whether a spell or an ability produced it.
    """
    targets = (instruction.payload or {}).get("targets")
    described = targets.get("filter") if isinstance(targets, dict) else None
    controller = (described or {}).get("controller")
    if controller in _PRINTED_SEATS:
        return _PRINTED_SEATS[controller]
    return _effect_side(instruction)


def _effect_side(instruction: OracleInstruction) -> str | None:
    """:func:`instruction_target_side` without the printed noun phrase: what
    the effect itself does to the object it is given — the sign of a P/T
    change, then the kind/category reading.

    Split out for the callers that hold a description the top-level ``filter``
    does not speak for: one **slot** of a several-target instruction and one
    **role** of a roles announcement each print their own controller, and the
    shared ``filter`` beside them is the first slot's.
    """
    if instruction.kind in _NO_SIDE_KINDS:
        return None
    sign = _pt_delta_sign(instruction)
    if sign:
        return "you" if sign > 0 else "opponent"
    return activation_target_side(instruction)


def denies_its_target(instruction: OracleInstruction) -> bool:
    """Whether what *instruction* does to its object target leaves that object
    worse off — destroyed, exiled, returned, tapped, taken, restricted.

    Asked where the printed noun phrase has already put the target on the
    actor's **own** board ("Destroy target artifact, creature, or land you
    control", Rats of Rath; "Return target land you control to its owner's
    hand", Trade Routes). There the effect is a price the card charges for
    something else, or a rescue this policy has no way to time, and a seat
    that activates it for its own sake destroys its own permanent — which the
    activation chooser used to do, falling back to the only legal target.
    """
    from .grammar.lowering.categories import INSTRUCTION_CATEGORIES

    kind = getattr(instruction, "kind", None)
    if kind in _OWN_KINDS or kind in _NO_SIDE_KINDS:
        return False
    if kind in _OPPONENT_KINDS:
        return True
    return INSTRUCTION_CATEGORIES.get(kind) in ("destruction", "tapping")


def _spell_object_target_steps(card: CardDefinition) -> tuple[OracleInstruction, ...]:
    """Every step of *card*'s spell program that names an **object** target,
    wrappers opened (``sequence``, ``if_then``, ``may``).

    **A step of a roles announcement that spends an object role is one too.**
    This read only ``targets.kind == "object"``, so a sentence whose targets
    are announced together and spent a step at a time had no side: "Return
    target nonland permanent to its owner's hand. If this spell was kicked,
    return another target nonland permanent…" (Rushing River) is two
    roles-stamped steps, and cast unkicked it is a one-target spell whose
    target the score tie handed to the caster's own board. A step spending a
    **seat** role ("…and 2 damage to target player or planeswalker", Lunge) is
    left out: it says nothing about a permanent.
    """
    from .target_roles import SEAT_ROLE_KINDS, payload_own_role

    def spends_an_object_role(payload: dict, targets: dict) -> bool:
        own = payload_own_role(payload)
        return any(
            isinstance(role, dict)
            and role.get("kind") not in SEAT_ROLE_KINDS
            and own in (None, role.get("role"))
            for role in targets.get("roles") or ()
        )

    found: list[OracleInstruction] = []

    def walk(instructions) -> None:
        for instruction in instructions:
            payload = instruction.payload or {}
            targets = payload.get("targets")
            if isinstance(targets, dict) and (
                targets.get("kind") == "object"
                or (
                    targets.get("kind") == "roles"
                    and spends_an_object_role(payload, targets)
                )
            ):
                found.append(instruction)
            for key in ("steps", "then", "else", "action", "otherwise"):
                nested = (instruction.payload or {}).get(key)
                if isinstance(nested, (list, tuple)):
                    walk(nested)

    walk(_spell_instructions(card))
    return tuple(found)


def spell_target_side(card: CardDefinition) -> str | None:
    """Whose permanent *card*'s object target should be, as a spell — "you",
    "opponent", or None when its steps disagree or none has an answer.

    The spell-side twin of :func:`activation_target_side`, and the question
    ``ai_scoring._choose_target_for_spell`` had no case for: its score is a
    handful of text probes (draw, gain life, damage, destroy, bounce), so a
    spell outside them scored the caster and the opponent equally and the tie
    went to the caster. Off Balance kept the AI's own creature home, Crumble
    destroyed its own artifact and Shrink shrank its own attacker.

    Every object-targeting step is read through :func:`instruction_target_side`,
    and where they differ the **denial** wins. A printed seat on the noun phrase
    ("target creature an opponent controls") outranks both, because the
    enumeration enforces it anyway. Otherwise one hampering step makes the
    target the opponent's: Traitorous Greed takes the creature, untaps it and
    gives it haste, and the untap and the haste are what make the theft worth
    having, not a reason to steal one's own creature. The other way round — a
    gift with a printed drawback on its own target — is not a template this
    pool prints, and aiming a gift at the opponent is the cheaper mistake.
    """
    steps = _spell_object_target_steps(card)
    printed = {
        _PRINTED_SEATS.get(
            ((step.payload.get("targets") or {}).get("filter") or {}).get("controller")
        )
        for step in steps
    } - {None}
    if len(printed) == 1:
        return next(iter(printed))
    sides = {instruction_target_side(step) for step in steps} - {None}
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


#: Instruction kinds whose effect on the **player** they name is a gift, and
#: whose category cannot say so: cards drawn and life gained are filed under
#: ``zones`` and ``life`` beside the discards and the life lost, an untap of
#: everything a player controls under ``tapping`` (which reads as a denial),
#: and an extra turn under ``turns`` beside the steps a player is made to
#: skip. A shield needs no entry — ``prevention`` is a family that answers
#: (:func:`activation_target_side`). What the compiled program does rather
#: than what a card is called, so every printing of "target player draws N
#: cards" answers the same way. Held to live handler kinds by
#: ``tests/ai/test_ai_rehearsed_casts.py``.
#:
#: **One set, where there were two.** ``engine/targeting.py`` kept draws,
#: life and one shield for the web route's default seat; this module kept the
#: two untaps for the AI's tie-break and read everything else off a family —
#: so "untap all lands target player controls" (Early Harvest) was a gift to
#: an AI seat and defaulted to the opponent for a person, and "target player
#: draws" was a gift by list there and nobody's here
#: (``tests/regressions/test_named_player_gift_readers.py``: 23 of 178).
#: ``grant_extra_turn`` was in neither: "target player takes an extra turn
#: after this one" (Time Warp) went to the opponent on both roads.
_SEAT_GIFT_KINDS = frozenset({
    "draw_target_cards", "target_gains_life",
    "untap_all_matching", "untap_up_to_matching",
    "grant_extra_turn",
})

#: Kinds a family reading must not answer for when the object is a **player**:
#: "you and target player exchange control of the creature you each control
#: with the highest mana value" (Juxtapose) opens on a choice made off the
#: named player's board, which is filed with the attachments it was written
#: for. A choice is not something done to the player; what is done with it is
#: the next sentence's.
_SEAT_NO_SIDE_KINDS = frozenset({"choose_permanent"})


def _helps_the_player_it_names(instruction: OracleInstruction) -> bool:
    """Whether *instruction* — the step a cast's player target is described
    by — is a gift to that player: by its kind (``_SEAT_GIFT_KINDS``), or by
    its family where the family can speak about a player at all."""
    kind = instruction.kind
    if kind in _SEAT_GIFT_KINDS:
        return True
    if kind in _SEAT_DENIAL_KINDS or kind in _SEAT_NO_SIDE_KINDS:
        return False
    return activation_target_side(instruction) == "you"


def cast_helps_the_player_it_names(
    card: CardDefinition, program=None, *, mode_index: "int | None" = None,
) -> bool:
    """Whether the player a cast of *card* announces (CR 601.2c) is one its
    effect **helps** — "target player draws three cards", "target player gains
    X life", "prevent the next 3 damage that would be dealt to any target",
    "untap all lands target player controls".

    **The one derivation, for the two callers that must aim a cast at a seat
    with nothing else to go on**: the web route's default for a cast whose
    announcement named none (``web/action_helpers._default_target``), and the
    AI's tie-break between seats a rehearsal measures alike
    (:func:`spell_seat_side`). They were two, in two modules, and could
    disagree about the same card.

    Read off the slot the cast's own picker is derived from
    (``instruction_targets._first_described_slot``, through the mode the cast names),
    so the answer is about the target the announcement actually makes — one
    step, not every step the spell goes on to carry out, some of which are
    about somebody else ("…that player loses 5 life **and you gain 5
    life**"). False where the card prints "target **opponent**" — the caster
    is not a seat that phrase admits — where the first thing it describes is
    not a player, and for a permanent spell, whose own cast names nobody.
    """
    from .targeting import _first_described_slot, announced_mode_instructions

    if card.primary_type not in SPELL_TYPES:
        return False
    if program is None:
        program = compile_card_oracle(card)
    slot = _first_described_slot(announced_mode_instructions(program, mode_index))
    if slot is None:
        return False
    spec, instruction = slot
    if spec.get("kind") not in _SEAT_SPEC_KINDS or spec.get("opponents_only"):
        return False
    return _helps_the_player_it_names(instruction)


def spell_seat_side(card: CardDefinition) -> str:
    """Whose seat a spell that names a **player** is aimed at when nothing
    measures a difference between them — "you" or "opponent".

    The tie-break under ``ai_scoring._choose_target_for_spell``, which weighs
    each seat by rehearsing the cast at it. Most of what such a spell does
    shows in a standing (cards drawn or discarded, life, damage); what does
    not is nearly always done *to* somebody — a hand looked at, a library
    milled, lands tapped, a step skipped, a turn's casts forbidden — so the
    answer is the opponent, unless the player named is one the effect helps
    (:func:`cast_helps_the_player_it_names`, in the mode being weighed).
    Tied at the caster's own seat, "tap all lands target player controls"
    tapped the caster's; tied at the opponent's, "target player takes an
    extra turn" gave one away.
    """
    return (
        "you" if cast_helps_the_player_it_names(card, mode_index=mode_considered(card))
        else "opponent"
    )


def entry_trigger_target_side(card: CardDefinition) -> str | None:
    """Whose permanent a **permanent** spell's enters-the-battlefield trigger
    should be aimed at — "you", "opponent" or None.

    This engine names an entry trigger's target as the permanent is cast
    (``cast_targets._cast_target_spec``: "a standing approximation"), so the cast
    is where an AI seat chooses it — and :func:`spell_target_side` reads only
    what resolves *as a spell*, which for a creature is nothing. With no side
    the chooser took the caster's own board first: Nekrataal destroyed its
    controller's creature, Man-o'-War bounced one, Avalanche Riders took a
    land and Uktabi Orangutan an artifact — 18 of the 36 permanents in the
    pool that carry such a trigger, every one a denial.

    The reading is the one a seat nobody asks already gets when the trigger
    goes on the stack unnamed (``_default_trigger_target_side``):
    :func:`ability_target_side` step by step, then the top-level kind's family.
    One answer for the two moments the same target can be chosen at.
    """
    if card.primary_type in SPELL_TYPES:
        return None
    sides: set[str] = set()
    for ability in compile_card_oracle(card).triggered_abilities:
        if (
            not ability.supported
            or ability.instruction is None
            or ability.condition.kind != "enters_battlefield"
        ):
            continue
        side = ability_target_side(ability.instruction) or activation_target_side(
            ability.instruction
        )
        if side is not None:
            sides.add(side)
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


#: Kinds whose effect on the **player** they target is a denial and whose
#: category cannot say so: a discard is filed under ``zones`` beside every
#: other card movement, where "damage" and "tapping" already answer for theirs.
#:
#: A life *loss* is the second (Torment): "When this creature enters, target
#: player loses 6 life" (Laquatus's Champion, Soul Scourge) has no family that
#: says whose, so an AI casting either named its own seat and lost the life
#: itself. Only "loses" — the gain beside it is a gift (``_SEAT_GIFT_KINDS``).
_SEAT_DENIAL_KINDS = frozenset({"discard_target_cards", "target_loses_life"})

#: The spec kinds whose candidates include a player's face
#: (``trigger_targets._CHOOSABLE_TRIGGER_PLAYER_KINDS``, the picker's own set).
_SEAT_SPEC_KINDS = frozenset({"player", "player_or_planeswalker", "any"})



def ability_seat_side(instruction: OracleInstruction | None) -> str | None:
    """Whose **seat** an effect that names a player — or "any target" — should
    name: "you", "opponent", or None when the compiled program does not say.

    :func:`ability_target_side` is the question for an object; this is the one
    for a face. The policy answered it with a list of three instruction kinds
    (``ai_abilities._choose_target_for_instruction``), two of which no handler has —
    ``gain_life`` and ``prevent_damage`` are what those effects were called
    before the grammar lowered them to ``target_gains_life`` and
    ``grant_prevention_shield``. A kind name nothing compiles is a claim about
    the pool that expired: every "target player gains N life" ability (Mournful
    Zombie, Tonic Peddler) and every "prevent the next N damage that would be
    dealt to any target" one (Samite Healer and eighteen more) fell through to
    the default and was aimed at an opponent.

    Read step by step with the wrappers opened, over the steps whose target can
    be a player's face (``_SEAT_SPEC_KINDS``), the denial winning where steps
    differ — :func:`ability_target_side`'s rule. A printed "target
    **opponent**" is the card's own answer and comes first: "You draw a card
    and target opponent gains 3 life" (Armistice) names an opponent however
    much of a gift the life is.
    """
    if instruction is None:
        return None
    sides: set[str | None] = set()
    for step in _effect_steps(instruction):
        targets = (step.payload or {}).get("targets")
        if not isinstance(targets, dict) or targets.get("kind") not in _SEAT_SPEC_KINDS:
            continue
        if targets.get("opponents_only"):
            sides.add("opponent")
        elif step.kind in _SEAT_GIFT_KINDS:
            sides.add("you")
        elif step.kind in _SEAT_DENIAL_KINDS:
            sides.add("opponent")
        else:
            sides.add(_effect_side(step))
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


def entry_trigger_seat_side(
    card: CardDefinition, optional_cost_payments: dict | None = None
) -> str | None:
    """"opponent" when the **player** a permanent spell's cast names is one its
    entry trigger denies -- else None, for no preference.

    The seat half of :func:`entry_trigger_target_side`, and the same standing
    approximation: this engine names an entry trigger's target as the permanent
    is cast, so the cast's seat *is* the trigger's "target player". The spell
    scorer cannot read that -- its probes are about a spell's own text, and its
    tie-break gives a creature spell's seat to the caster -- so "When this
    creature enters, **target player discards two cards**" (Abyssal Horror)
    was aimed at the seat that cast it, and "tap all lands **target player**
    controls" (Gulf Squid) tapped its controller's own. Thunderscape
    Battlemage's {1}{B} kicker is the third printing of the first.

    Asked of the one trigger the cast's picker is derived from -- the first
    that describes a target, among those a cast announced with
    *optional_cost_payments* will fire (``cast_targets.entry_trigger_instructions``,
    CR 702.33g) -- so the answer is about the target the cast actually names.
    Only the denial is answered: a gift aimed by this rule could contradict the
    printed phrase ("target **opponent** draws two cards", Lord of
    Tresserhorn). What the phrase itself allows is the trigger's own target
    list, which the policy asks beside this (``ai_scoring._entry_trigger_seats``)
    — this reading said every non-denial "already lands where its card prints
    it", and seven did not (Torment's W2G3).
    """
    from .targeting import _first_described_slot
    from .cast_targets import entry_trigger_instructions

    if card.primary_type in SPELL_TYPES:
        return None
    slot = _first_described_slot(entry_trigger_instructions(
        card, compile_card_oracle(card),
        optional_cost_payments=optional_cost_payments,
    ))
    if slot is None:
        return None
    spec, instruction = slot
    if spec.get("kind") not in _SEAT_SPEC_KINDS:
        return None
    if (
        instruction.kind in _SEAT_DENIAL_KINDS
        or activation_target_side(instruction) == "opponent"
    ):
        return "opponent"
    return None


#: The printed controller narrowings a target's noun phrase can carry, as sides.
_PRINTED_SEATS = {"you": "you", "not_you": "opponent", "opponent": "opponent"}


def spell_denies_its_own_target(card: CardDefinition) -> bool:
    """Whether *card*, as a spell, prints a target on its caster's **own**
    board and then denies it (:func:`denies_its_target`) — "Return target
    permanent you control to its owner's hand" (Scapegoat), "Tap target
    untapped creature you control" (Energy Tap). The spell-side twin of the
    activation chooser's question, for the same reason."""
    return any(
        ((step.payload.get("targets") or {}).get("filter") or {}).get("controller")
        == "you"
        and denies_its_target(step)
        for step in _spell_object_target_steps(card)
    )


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
    #: is the same reading :func:`activation_target_side` makes one table up.
    side: str | None = None
    #: Whether a share too small to matter is wasted. True for damage, which is
    #: measured against a toughness: four damage split one apiece over four
    #: creatures kills none of them, while four +1/+1 counters split the same
    #: way are four counters either way. It is a fact about the effect, not a
    #: policy — what the AI *does* about it is stated in ``ai_policy``.
    thresholded: bool = False
    #: Whether the card names a whole board rather than offering a choice —
    #: "…among **all creatures target opponent controls**" (Dwarven Catapult).
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
    which is :func:`spell_target_side`'s rule over again: one hampering step
    makes the target the opponent's.
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
      its target is exactly the question :func:`instruction_target_side`
      answers for a one-target spell.

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
    and :func:`spell_target_side` reads only a step whose ``targets`` is an
    object description — so a roles spell had no side at all, the chooser took
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


def named_counter_marks_for_harm(
    card: CardDefinition, instruction: OracleInstruction | None
) -> bool:
    """Whether *instruction* puts a named counter on its target that **this
    same card's** state trigger then punishes.

    "{T}: Put a fuse counter on target creature." reads as a gift by its
    category — ``counters`` is an own-side category, because a +1/+1 counter is
    one — and the card's third line says what a fuse counter is for: "Whenever
    a creature has four or more fuse counters on it, … destroy it. That
    creature deals 4 damage to its controller." (Bomb Squad.) A named counter
    means nothing by itself (CR 122.1); what it means is whatever the card's
    other lines say about it, so this reads them: a state trigger watching
    other permanents for the same kind of counter, whose effect has a step the
    engine already files as hostile.

    Without it an AI seat holding Bomb Squad lit its own creature, blew it up,
    took the 4, and then started on Bomb Squad itself — every simulated game
    that dealt the card.
    """
    if instruction is None:
        return False
    placed = {
        str((step.payload or {}).get("counter"))
        for step in _effect_steps(instruction)
        if step.kind == "add_named_counter_to_target"
        and isinstance((step.payload or {}).get("targets"), dict)
    }
    if not placed:
        return False
    from .grammar.lowering.categories import INSTRUCTION_CATEGORIES
    from .state_triggers import WATCHED_COUNTER_THRESHOLD

    for trig in compile_card_oracle(card).triggered_abilities:
        if (
            trig.condition.kind != WATCHED_COUNTER_THRESHOLD
            or trig.instruction is None
            or str(trig.condition.payload.get("counter_kind")) not in placed
        ):
            continue
        if any(
            INSTRUCTION_CATEGORIES.get(step.kind) in _OPPONENT_CATEGORIES
            for step in _effect_steps(trig.instruction)
        ):
            return True
    return False


def ability_target_side(instruction: OracleInstruction | None) -> str | None:
    """Whose permanent an ability's object target should be — "you",
    "opponent", or None when no step answers — read step by step with the
    wrappers opened, the denial winning where steps differ.

    :func:`spell_target_side`'s rule, asked of one ability rather than a card.
    The top-level reading cannot see through a ``sequence``: "Target creature
    gains protection from the color of its controller's choice" (Wishmonger)
    is a colour choice and then a grant, and read as one instruction it has no
    side at all — so the chooser fell back to the biggest creature on either
    board and gave protection to an opponent's.
    """
    if instruction is None:
        return None
    steps = [
        step for step in _effect_steps(instruction)
        if isinstance((step.payload or {}).get("targets"), dict)
    ]
    sides = {instruction_target_side(step) for step in steps} - {None}
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


def ability_denies_its_target(instruction: OracleInstruction | None) -> bool:
    """:func:`denies_its_target` asked of the step that names the target,
    wrappers opened — the instruction itself when no step names one.

    :func:`ability_target_side`'s twin, and needed for its reason: "Destroy
    target artifact you control" read through a ``sequence`` is a wrapper, and
    a wrapper denies nothing, so the own-seat chooser that aims by the step
    would then activate the step against its own permanent.
    """
    if instruction is None:
        return False
    steps = [
        step for step in _effect_steps(instruction)
        if isinstance((step.payload or {}).get("targets"), dict)
    ] or [instruction]
    return any(denies_its_target(step) for step in steps)


__all__ = [
    "DividedShape",
    "ability_target_side",
    "cast_helps_the_player_it_names",
    "denies_its_target",
    "divided_shape",
    "named_counter_marks_for_harm",
    "instruction_target_side",
    "role_target_sides",
    "several_target_slot_sides",
    "spell_denies_its_own_target",
    "spell_target_side",
]
