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
  :func:`entry_trigger_seat_side`).

Several targets and roles, slot by slot — two sides for one instruction
where the program prints two — and what a divided spell divides are
``ai_slot_sides``'s, which asks this module's one-target reading of the step
that spends each target.

The policy's choosers ask these and choose among the engine's own candidates
(``ai_targets``, ``ai_slot_targets``); nothing here names a permanent.
"""

from __future__ import annotations

from functools import lru_cache

from .models import CardDefinition
from .oracle import OracleInstruction, compile_card_oracle
from .oracle_types import compilation_cache
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
    # "All creatures able to block target creature this turn do so."
    # (Bloodscent.) A Lure for the turn: the creature it is put on is the
    # caster's attacker, whose blockers are all made to meet it.
    "force_all_able_to_block_target_until_eot",
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
    # …and the same untap aimed at the permanent its source is attached to:
    # "{U}: Untap enchanted creature." (Pemmin's Aura, Instill Energy,
    # Nature's Chosen.) The ``tapping`` category read it "opponent", so an
    # AI seat holding the Aura on a person's creature untapped it for them
    # (SCG Phase 5, `host_effect_side`).
    "untap_enchanted_creature",
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
    # …and its host twin: "{R}: Enchanted creature can't block this turn."
    # (Manacles of Decay.) ``combat_restrictions`` has no side to give.
    "attached_cant_block_until_eot",
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
    # ...and the delayed steal bound to the target: "You gain control of
    # that creature if it regenerates this way" (Debt of Loyalty).
    "gain_control_of_bound_permanent",
    "steal_target_linked_to_source",
    "bid_life_for_control",
    # Removal one zone over from destroy: exile, the library, the hand.
    "exile_target_permanent",
    "exile_until_leaves_or_untaps",
    # ...and the exile spent on a target an earlier step recorded: "Exile
    # one of those creatures and put two +1/+1 counters on the other"
    # (Cannibalize), where the counters are the price and the exile the point.
    "exile_recorded_permanent",
    # …and the same removal spelled as phasing: "target creature phases out
    # until this enchantment leaves the battlefield" (Oubliette). The kind has
    # no category to answer for it.
    "phase_out_target_creature_until_source_leaves",
    "put_target_on_library_top",
    "shuffle_target_permanent_into_library",
    "bounce_target_creature",
    # CR 708.2a: "Turn target creature with a morph ability face down"
    # (Backslide) makes the creature a 2/2 whose owner must pay its morph
    # cost again — a setback, where ``characteristics`` reads a gift. Onslaught
    # prints no "when turned face up" trigger that would make one's own the
    # target (those are Legions').
    "turn_target_face_down",
    # CR 708.5: "Look at target face-down creature" (Aven Soulgazer) tells its
    # controller nothing about their own face-down creatures, which they may
    # look at already; the look is for an opponent's.
    "look_at_target_face_down",
    # "…move a +1/+1 counter **from target creature** onto this creature"
    # (Arcbound Fiend). Categorised ``counters`` beside the placements, which
    # is the family and the opposite side: the target is the one the counter
    # comes *off*.
    "move_counter_to_self",
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
#: it did before any of this was derived. "This creature's base power becomes
#: equal to target creature's power" (Riptide Mangler; Sentinel, Sworn
#: Defender) reads its target and changes only its source: the pump category
#: made it "you", so the Mangler copied its controller's own biggest power
#: and never an opponent's greater one — and Sentinel's and Sworn Defender's
#: targets, the creatures fighting them, were never on that side at all.
_NO_SIDE_KINDS = frozenset({
    "destroy_all_matching",
    "set_source_base_pt_from_target",
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
    # The host twins (`host_effect_side`): "{B}: Enchanted creature gets
    # -1/-1 until end of turn" (Manacles of Decay) is Shrink on the host, and
    # the ``pump`` category read it as Giant Growth.
    "pump_enchanted_creature",
    "add_pt_counters_to_attached",
})


def _pt_delta_sign(instruction: OracleInstruction) -> int:
    """+1 / -1 / 0: whether the P/T change *instruction* makes is a gift or a
    penalty, read off its own payload.

    The sign is what decides the side for the P/T families, whose category
    (``pump``, ``counters``) is right about the family and silent about the
    direction: "Target creature gets +3/+3" (Giant Growth) and "…gets -5/-0"
    (Shrink) are one instruction kind. Four payload spellings: printed numbers,
    an X with its ``*_negative`` flag, a repetition with its sign inside it
    (``{"times_x": n}``), and a counter's own "+1/+1" / "-1/-0".

    The repetition is how "-1/-1 **for each** artifact you control"
    (Irradiate) and a negated variable ("-X/-X", Chill Haunting) lower
    (``grammar/lowering/_common._signed``, ``_amounts._per_each_amount``):
    the sign rides in the amount so every resolver applies it. Unread here,
    both summed to nothing and fell through to the ``pump`` category's "you"
    — an AI seat shrank its own creature with its twin opposite a legal
    target (the idle-cast census's own goal, at Mirrodin's promotion).
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
        elif isinstance(value, dict) and isinstance(value.get("times_x"), int):
            total += (value["times_x"] > 0) - (value["times_x"] < 0)
        elif value == "x":
            # A bare X is positive unless a flag says otherwise: the lowering
            # that writes the repetition above for "-X" writes the letter for
            # "+X" (`_signed`), so -X/+X (Belbe's Armor) sums to the trade it
            # is rather than to a shrink.
            total += -1 if payload.get(f"{key}_negative") else 1
        elif value is not None and payload.get(f"{key}_negative") is not None:
            total += -1 if payload.get(f"{key}_negative") else 1
    counter = payload.get("counter")
    if isinstance(counter, str):
        deltas = pt_counter_deltas(counter)
        if deltas is not None:
            total += sum(deltas)
    return (total > 0) - (total < 0)


#: The targeted kinds whose ``power`` / ``toughness`` payload **sets** the
#: target's base P/T (CR 613.4b) to a printed number: "Until end of turn,
#: target creature has base power 1 or base toughness 1" (Vhati il-Dal),
#: "…has base power and toughness 0/2" (Sorceress Queen), "Target creature
#: with flying has base power 0" (Island of Wak-Wak). The target carries no
#: ``targets`` payload: the kind is the target.
_BASE_PT_SET_KINDS = frozenset({"set_base_pt_target_until_eot"})

#: The base power and toughness a rewrite to printed numbers is weighed
#: against (:func:`_base_pt_set_sign`): a 2/2. A chooser aims at the largest
#: creature on the side it is told, so a rewrite to less than this erases
#: most of what it lands on and is a penalty, one to more is a gift. A tuning
#: weight, not a rule: every rewrite in both manifest roles prints 0, 1 or 2.
BASE_PT_REFERENCE = 2


def _base_pt_set_sign(instruction: OracleInstruction) -> int:
    """+1 / -1 / 0: whether a base P/T **rewrite** (:data:`_BASE_PT_SET_KINDS`)
    to printed numbers gives its target more than :data:`BASE_PT_REFERENCE` or
    less, summed over the characteristics it sets — 0 for any other kind, an
    X, or a rewrite to the reference itself.

    The category read every one as ``pump`` — "you" — so Vhati il-Dal shrank
    its controller's biggest creature, Sorceress Queen made the AI's own best
    creature a 0/2 and Island of Wak-Wak zeroed its own flier (kg5)."""
    if instruction.kind not in _BASE_PT_SET_KINDS:
        return 0
    payload = instruction.payload or {}
    total = 0
    for key in ("power", "toughness"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total += (value > BASE_PT_REFERENCE) - (value < BASE_PT_REFERENCE)
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
    if instruction.kind in _BASE_PT_SET_KINDS:
        # The rewrite carries its noun phrase's seat on the payload itself:
        # "target creature **you control** gains flying and has base
        # toughness 1" (Chariot of the Sun), "target creature **you cast this
        # turn**" (Cycle of Life) — the activator's own either way.
        payload = instruction.payload or {}
        described = {
            "controller": "you" if payload.get("cast_by_you_this_turn")
            else payload.get("controller"),
        }
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
    sign = _pt_delta_sign(instruction) or _base_pt_set_sign(instruction)
    if sign:
        return "you" if sign > 0 else "opponent"
    if _silences_its_object(instruction):
        return "opponent"
    if _grants_a_burden(instruction):
        return "opponent"
    return activation_target_side(instruction)


def _grants_a_burden(instruction: OracleInstruction) -> bool:
    """Whether *instruction* grants its object a quoted ability that **hampers
    the object holding it** — so the object should be an opponent's.

    "Until end of turn, target creature gains "This creature can't attack or
    block unless its controller pays {1} for each Cleric on the battlefield.""
    (Whipgrass Entangler.) The kind (``grant_target_ability_text``) is a
    grant, and its category reads every grant as a gift — so the AI paid
    {1}{W} each turn to tax its own creature. What the grant *does* is the
    quoted line, and two families of line are burdens on their holder, each
    asked of the reader that enforces it: a combat restriction on its own
    attacking or blocking (``combat_restrictions.combat_restriction_for`` —
    "can't attack", "can't block", their tolls; not "can't be blocked", which
    is evasion), and an untap restriction on itself
    (``untap_restrictions.self_untap_line``: Glyph of Delusion's "This
    creature doesn't untap during your untap step if it has a glyph counter on
    it"). A grant of anything else keeps its category's reading.

    **And a triggered ability that takes its holder off the battlefield**
    (:func:`_trigger_removes_its_holder`): "If it doesn't have "At the
    beginning of your upkeep, destroy this creature unless you pay {1} for
    each music counter on it," it gains that ability." (Musician) — read
    "you", so the AI put the music on its own creature.
    """
    if getattr(instruction, "kind", None) != "grant_target_ability_text":
        return False
    from .combat_restrictions import combat_restriction_for
    from .self_reference import _restriction_line
    from .untap_restrictions import self_untap_line

    for text in (instruction.payload or {}).get("abilities") or ():
        restriction = combat_restriction_for(_restriction_line(str(text), None))
        if restriction is not None and any(
            kind.startswith(("cant_attack", "cant_block"))
            for kind in (restriction.kind, *restriction.also_kinds)
        ):
            return True
        if self_untap_line(str(text)) is not None:
            return True
        if _trigger_removes_its_holder(str(text)):
            return True
    return False


#: What a granted trigger compiles to when it takes the permanent holding it
#: off the battlefield: the self-removals (``ai_valuation.SOURCE_REMOVAL_KINDS``)
#: and the upkeep tolls whose price unpaid is the holder itself ("destroy this
#: creature unless you pay …", as ``grammar/lowering/tolls`` lowers it).
_HOLDER_TOLL_KINDS = frozenset({
    "upkeep_pay_or_destroy_self",
    "upkeep_pay_or_sacrifice_self",
})


@compilation_cache
@lru_cache(maxsize=None)
def _trigger_removes_its_holder(text: str) -> bool:
    """Whether the quoted line *text* is a triggered ability (read by the
    compiler's own triggered-line front end) any step of whose effect
    destroys, sacrifices, exiles or bounces its own holder, or charges it as
    the price of an upkeep toll."""
    from .ability_lines import _parse_triggered_ability
    from .ai_valuation import SOURCE_REMOVAL_KINDS

    parsed = _parse_triggered_ability(text)
    if parsed is None or parsed.instruction is None:
        return False
    return any(
        step.kind in SOURCE_REMOVAL_KINDS or step.kind in _HOLDER_TOLL_KINDS
        for step in _effect_steps(parsed.instruction)
    )


def _silences_its_object(instruction: OracleInstruction) -> bool:
    """Whether *instruction* is a combat shield on **both** ends of the event:
    "Prevent all combat damage that would be dealt to **and dealt by** that
    creature this turn" (Foxfire, Maze of Ith; "those creatures", Energy Arc).

    Its kind is the recipient shield (``prevention``, read as a gift), and the
    ``to_and_by`` payload key adds the other end: a creature that deals no
    combat damage, which is ``prevent_damage_by_target_until_eot``'s denial in
    ``_OPPONENT_KINDS``. Where a shield and a denial meet on one object the
    denial wins, :func:`spell_target_side`'s rule; a printed seat still
    outranks it ("…by target creature **you control**", Cephalid Illusionist),
    because :func:`instruction_target_side` asks the noun phrase first.

    …and the whole-instance shield keyed on the **target as the source** ("The
    next time target creature would deal damage this turn, prevent that
    damage", Awe Strike): its kind is the gift shield, and ``source_from:
    "target"`` makes the object the one whose damage is stopped — measured in
    seeded games aimed at the AI's own attacker, preventing its own damage to
    the opponent.
    """
    payload = instruction.payload or {}
    if instruction.kind == "grant_whole_prevention_shield":
        return payload.get("source_from") == "target"
    return (
        instruction.kind == "prevent_damage_to_target_until_eot"
        and bool(payload.get("to_and_by"))
    )


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
    if kind in _OPPONENT_KINDS or _grants_a_burden(instruction):
        return True
    return INSTRUCTION_CATEGORIES.get(kind) in ("destruction", "tapping")


#: Kinds that, printed with no target of their own after a step that named
#: one, are spent on **that** object — so what they do to it is part of whose
#: it should be. "Untap target attacking creature. Prevent all combat damage
#: that would be dealt to and dealt by that creature this turn." (Foxfire;
#: "those creatures", Energy Arc, through the record the untap wrote.) The
#: handler resolves the pronoun to the target the sentence in front named
#: (``handlers/prevention.prevent_damage_to_target_until_eot``). Read alone,
#: the untap made both spells "you" (``_OWN_KINDS``): an AI seat aimed Energy
#: Arc at its own creature with the opposing twin measuring four times as
#: much, and could cast Foxfire only at its own attacker.
_SPENT_ON_THE_EARLIER_TARGET = frozenset({"prevent_damage_to_target_until_eot"})


def _spent_on_the_earlier_target(instruction: OracleInstruction) -> "OracleInstruction | None":
    """The step to read, for a step with no target of its own printed after
    one that named one, when it acts on **that** object — or None.

    Three ways the pool says so: a kind listed in
    ``_SPENT_ON_THE_EARLIER_TARGET``; a step that acts on the permanents an
    earlier step recorded (``permanents_from``: "Untap target creature and
    gain control of it until end of turn", Threaten, whose steal reads the
    untap's record); and a delayed trigger bound to the target
    (``binds_target``: "Regenerate target creature. You gain control of that
    creature if it regenerates this way", Debt of Loyalty), read as the
    instruction it will carry out. Read alone, the untap and the haste made
    Threaten "you", and the regeneration made Debt of Loyalty "you": an AI
    seat cast each at its own creature, or held it, with the opposing one
    measuring two to four times as much (the combat-trick and idle
    censuses, kg3).
    """
    payload = instruction.payload or {}
    if instruction.kind in _SPENT_ON_THE_EARLIER_TARGET or payload.get("permanents_from"):
        return instruction
    delayed = payload.get("instruction")
    if payload.get("binds_target") and hasattr(delayed, "kind"):
        return delayed
    return None


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

    **And a step spent on the object an earlier step named**
    (:func:`_spent_on_the_earlier_target`, with no target of its own): the
    shield in "Untap target attacking creature. Prevent all combat damage …
    dealt to and dealt by that creature" is about the same creature the untap
    is, and so are Threaten's steal and Debt of Loyalty's delayed one.
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
            elif (
                found and targets is None
                and not payload.get("on_source")
                and (spent := _spent_on_the_earlier_target(instruction)) is not None
            ):
                found.append(spent)
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
    if _bins_flashback_cards(instruction):
        return True
    return activation_target_side(instruction) == "you"


def _bins_flashback_cards(instruction: OracleInstruction) -> bool:
    """Whether *instruction* searches the named player's library for cards
    **with flashback** and puts them into that player's graveyard ("Search
    target player's library for up to three cards with flashback and put them
    into that player's graveyard", Quiet Speculation).

    A gift to that player, whatever a standing reads: a card with flashback in
    a graveyard is a spell its owner may cast from there (CR 702.34a), so the
    finds are cards gained rather than cards lost — and aimed at an opponent
    the search hands them three spells. Read off the payload (the search's
    destination and its restriction), never a name, so any printing of the
    sentence is aimed the same way.
    """
    if instruction.kind != "search_library":
        return False
    payload = instruction.payload or {}
    restrictions = payload.get("restrictions") or {}
    return (
        payload.get("destination") == "graveyard"
        and restrictions.get("with_keyword") == "flashback"
    )


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
#:
#: Controlling a player's next turn is the third (Mindslaver, CR 723): its
#: family is ``turns``, beside the extra turn that is a gift, and an AI
#: controlling its own seat does nothing at all (CR 723.9).
_SEAT_DENIAL_KINDS = frozenset({
    "discard_target_cards", "target_loses_life", "control_player_next_turn",
})

#: The spec kinds whose candidates include a player's face
#: (``trigger_targets._CHOOSABLE_TRIGGER_PLAYER_KINDS``, the picker's own set).
_SEAT_SPEC_KINDS = frozenset({"player", "player_or_planeswalker", "any"})



def ability_seat_side(instruction: OracleInstruction | None) -> str | None:
    """Whose **seat** an effect that names a player — or "any target" — should
    name: "you", "opponent", or None when the compiled program does not say.

    :func:`ability_target_side` is the question for an object; this is the one
    for a face. The policy answered it with a list of three instruction kinds
    (``ai_activation_targets._choose_target_for_instruction``), two of which no handler has —
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
        else:
            sides.add(_seat_step_side(step))
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


def _seat_step_side(step: OracleInstruction) -> str | None:
    """What one step does to the **player** it is about, as a side: a gift
    names the caster, a denial an opponent, anything else the family reading
    (:func:`ability_seat_side`'s per-step rule)."""
    if step.kind in _SEAT_GIFT_KINDS:
        return "you"
    if step.kind in _SEAT_DENIAL_KINDS:
        return "opponent"
    return _effect_side(step)


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


def sweep_a_named_counter_spares(
    card: CardDefinition, instruction: OracleInstruction | None
) -> "tuple[str, dict] | None":
    """``(counter, swept)`` when *instruction* puts a named counter on its
    target that **this same card's** sweep spares — *swept* the sweep's own
    filter, the counter set aside — or None.

    "{4}, {T}: Put a fate counter on target permanent. / {5}, {T}, Sacrifice
    this artifact: Destroy each nonland permanent **without a fate counter on
    it** …" (Oblivion Stone.) :func:`named_counter_marks_for_harm`'s question
    the other way round: what the counter means is what the card's other line
    does with it (CR 122.1), and here that is a shelter. So it belongs on the
    activator's own permanent, on one the sweep would take, and on one that
    has none yet — a second fate counter shelters nothing more, and an AI
    seat stacked three on one Grizzly Bears while its Stone never swept.
    """
    if instruction is None:
        return None
    placed = {
        str((step.payload or {}).get("counter"))
        for step in _effect_steps(instruction)
        if step.kind == "add_named_counter_to_target"
        and isinstance((step.payload or {}).get("targets"), dict)
    }
    if not placed:
        return None
    for ability in compile_card_oracle(card).activated_abilities:
        for step in _effect_steps(ability.instruction) if ability.instruction else ():
            payload = step.payload or {}
            spared = payload.get("without_named_counter")
            if step.kind == "destroy_all_matching" and str(spared) in placed:
                swept = {
                    key: value for key, value in payload.items()
                    if key != "without_named_counter"
                }
                return str(spared), swept
    return None


def sweeps_what_its_counter_shelters(
    card: CardDefinition, instruction: OracleInstruction | None
) -> bool:
    """Whether *instruction* is the sweep :func:`sweep_a_named_counter_spares`
    reads from the other side: it destroys everything **without** a named
    counter that another ability of this same card puts on a target (Oblivion
    Stone's "{5}, {T}, Sacrifice this artifact: Destroy each nonland permanent
    without a fate counter on it")."""
    if instruction is None:
        return False
    spared = {
        str((step.payload or {}).get("without_named_counter"))
        for step in _effect_steps(instruction)
        if step.kind == "destroy_all_matching"
        and (step.payload or {}).get("without_named_counter")
    }
    return bool(spared) and any(
        (sheltered := sweep_a_named_counter_spares(card, ability.instruction)) is not None
        and sheltered[0] in spared
        for ability in compile_card_oracle(card).activated_abilities
    )


def _side_steps(instruction: OracleInstruction) -> tuple[OracleInstruction, ...]:
    """*instruction*'s leaf steps (``_effect_steps``) with every ``choose_one``
    **opened into its modes** ("loses flying, first strike, or trample",
    Walking Sponge): whichever is chosen lands on the object, where the
    wrapper itself names nothing and has no side."""
    found: list[OracleInstruction] = []
    for step in _effect_steps(instruction):
        if step.kind == "choose_one":
            modes = [
                mode.get("instruction")
                for mode in (step.payload or {}).get("modes") or ()
                if isinstance(mode, dict) and mode.get("instruction") is not None
            ]
            if modes:
                for mode in modes:
                    found.extend(_side_steps(mode))
                continue
        found.append(step)
    return tuple(found)


def _pt_trade(step: OracleInstruction) -> bool:
    """Whether *step* raises one half of a P/T and lowers the other by printed
    numbers ("+1/-1"): a gift on a big body, removal on an X/1, so its sign
    (:func:`_pt_delta_sign`, a sum) says neither."""
    payload = step.payload or {}
    power, toughness = payload.get("power"), payload.get("toughness")
    return (
        step.kind in _PT_DELTA_KINDS
        and all(type(value) is int for value in (power, toughness))
        and power * toughness < 0
    )


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

    Nor a ``choose_one`` until kg4 (:func:`_side_steps`): Walking Sponge's
    "loses flying, first strike, or trample" hit its own Serra Angel.
    """
    if instruction is None:
        return None
    # A step names its target in a ``targets`` payload — or *is* one: a base
    # P/T rewrite (:data:`_BASE_PT_SET_KINDS`) carries none, so Vhati il-Dal's
    # two modes were read as naming nothing and its ability had no side.
    steps = [
        step for step in _side_steps(instruction)
        if isinstance((step.payload or {}).get("targets"), dict)
        or step.kind in _BASE_PT_SET_KINDS
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
        step for step in _side_steps(instruction)
        if isinstance((step.payload or {}).get("targets"), dict)
    ] or [instruction]
    return any(denies_its_target(step) for step in steps)


#: The steps that act on **the permanent their source is attached to** —
#: "enchanted creature", "equipped creature" (CR 301.5f reads the two alike) —
#: and on nothing else: what an Aura's own ability does to its host. Each
#: handler finds that permanent through ``handlers._targets.attached_host``;
#: `tests/ai/test_scg_p5_host_ability_census.py` holds this table to every
#: such step an activated ability in the pool compiles to.
HOST_KINDS = frozenset({
    "pump_enchanted_creature",
    "grant_enchanted_keyword_until_eot",
    "grant_regeneration_to_enchanted_creature",
    "untap_enchanted_creature",
    "tap_enchanted_creature",
    "add_pt_counters_to_attached",
    "attached_cant_block_until_eot",
    "return_attached_permanent_to_hand",
    "phase_out_enchanted",
    "recolor_enchanted_chosen_color",
    "set_enchanted_creature_type",
})

#: …and the shared kinds a payload key points at the host instead of at a
#: target: "Prevent the next 1 damage that would be dealt to enchanted
#: creature this turn" (Fylgja), "The next time a source of your choice would
#: deal damage to enchanted creature this turn, prevent that damage" (Kithkin
#: Armor).
_HOST_PAYLOAD_KEYS = ("to_attached",)

#: Steps that only choose the word a host step after them reads ("…becomes
#: the creature type of your choice", Mistform Mask): no object, no side.
_HOST_CHOICE_KINDS = frozenset({"choose_creature_type"})


def _acts_on_the_host(step: OracleInstruction) -> bool:
    payload = step.payload or {}
    if isinstance(payload.get("targets"), dict):
        return False
    return step.kind in HOST_KINDS or any(payload.get(key) for key in _HOST_PAYLOAD_KEYS)


def host_effect_side(instruction: OracleInstruction | None) -> str | None:
    """Whose permanent an ability's **host** should be for the ability to be
    worth its controller's mana — "you", "opponent", or None — when every
    step of its effect acts on the permanent its source is attached to
    (:data:`HOST_KINDS`); None for every other ability.

    An Aura's controller activates its abilities (CR 602.2), and what they
    do lands on whatever creature it enchants, whoever controls that. The
    own-board chooser had no question for it: Pemmin's Aura on a person's
    Krosan Warchief, "{U}: Untap enchanted creature", was proposed every main
    phase, and once untapped the person's attacker so that it could block
    (SCG Phase 5, smoke game 1). Read step by step with
    :func:`_effect_side`, the one reading a targeted step gets, the denial
    winning where steps differ — :func:`ability_target_side`'s rule. A step
    that names a target of its own ("Enchanted creature deals 1 damage to
    target creature with flying", Dizzying Gaze) is about that target, so an
    ability printing one has no host side here.

    A ``choose_one`` is read through its modes (:func:`_side_steps`), and an
    effect worth what the host's body makes it
    (:func:`host_effect_by_the_moment`) has no side here.
    """
    if instruction is None or host_effect_by_the_moment(instruction):
        return None
    steps = _host_steps(instruction)
    if steps is None:
        return None
    sides = {_effect_side(step) for step in steps} - {None}
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


def _host_steps(instruction: OracleInstruction) -> "tuple | None":
    """*instruction*'s steps (modes opened, a type choice left out) when every
    one acts on its source's host (:func:`_acts_on_the_host`), else None."""
    steps = tuple(
        step for step in _side_steps(instruction)
        if step.kind not in _HOST_CHOICE_KINDS
    )
    if not steps or not all(_acts_on_the_host(step) for step in steps):
        return None
    return steps


def host_effect_by_the_moment(instruction: OracleInstruction | None) -> bool:
    """Whether an ability whose whole effect lands on its source's host is
    worth activating on one host and not another **by what the host is** —
    some step a P/T trade (:func:`_pt_trade`), or modes that read on
    different sides. Pemmin's Aura's "+1/-1 or -1/+1" and Flowstone Blade's
    "+1/-1" kill an opponent's X/1 and their controller's own; read as a
    gift by its category, Flowstone Blade was refused on the first and
    activated on its controller's Llanowar Elves, which it killed (kg4). The
    activation chooser rehearses such an ability
    (``ai_abilities._activation_candidate``)."""
    if instruction is None:
        return False
    steps = _host_steps(instruction)
    if steps is None:
        return False
    if any(_pt_trade(step) for step in steps):
        return True
    return len({_effect_side(step) for step in steps} - {None}) > 1


#: Steps of an attachment's ability that take its host away from the host's
#: controller: "When enchanted land becomes tapped, destroy it" (Kudzu,
#: Blight), "sacrifice that creature" (Lingering Death), "that spell or
#: ability's controller gains control of that creature" (Fractured Loyalty).
HOST_LOSING_KINDS = frozenset({
    "destroy_attached_permanent",
    "sacrifice_attached_permanent",
    "give_control_of_attached_to_player",
})


def host_trigger_side(instruction: OracleInstruction | None) -> str | None:
    """Whose permanent a **triggered** ability's host should be — "you",
    "opponent", or None — read off the steps that land on the permanent its
    source is attached to (:data:`HOST_KINDS`, and :data:`HOST_LOSING_KINDS`
    as the denial they are), wrappers and modes opened, the other steps of
    the ability (Kudzu's "That land's controller may attach this Aura to a
    land of their choice") left out; the denial wins where steps differ.

    :func:`host_effect_side` asks it of an activated ability, whose every
    step must land on the host because the Aura's controller pays for it. A
    trigger is paid for by nobody: its host steps are what the Aura does to
    whatever it enchants, which is the question an Aura's cast-target chooser
    asks (``ai_targets._aura_harms_its_host``)."""
    if instruction is None:
        return None
    sides = {
        "opponent" if step.kind in HOST_LOSING_KINDS else _effect_side(step)
        for step in _side_steps(instruction)
        if step.kind in HOST_LOSING_KINDS or _acts_on_the_host(step)
    } - {None}
    if "opponent" in sides:
        return "opponent"
    return "you" if "you" in sides else None


#: The step that taps **or** untaps its target, which way being the state the
#: target is in (Twiddle's toggle).
_TOGGLE_KINDS = frozenset({"tap_or_untap_target"})


def toggles_its_target(instruction: OracleInstruction | None) -> bool:
    """Whether *instruction* — wrappers opened ("you may pay {1}{U}. If you do,
    you may tap or untap target permanent", Telekinetic Bonds) — taps or
    untaps its target, whichever it is not.

    The one family in ``_NO_SIDE_KINDS`` whose side is not a seat but a
    **state**: tapping an opponent's untapped creature and untapping one's own
    tapped one are both the point of it, and the other two answers are the
    same effect turned against the chooser. So no seat describes it, and a
    seat nobody asked took the first permanent offered — Telekinetic Bonds
    paid {1}{U} to tap itself.
    """
    if instruction is None:
        return False
    return any(step.kind in _TOGGLE_KINDS for step in _effect_steps(instruction))


def toggle_target_order(game, chooser: int, permanents: list) -> list:
    """*permanents* in the order a toggle is best aimed by *chooser*: an
    opponent's untapped creature (the largest first — an attacker or a
    blocker taken out of the turn), then one of its own tapped creatures,
    then an opponent's untapped land, then one of its own tapped lands, then
    everything else — the toggles that help the other side — in the order
    offered."""

    def rank(permanent) -> tuple:
        mine = game.controller_index_of(permanent) == chooser
        creature = bool(permanent.is_creature)
        power = permanent.effective_power if creature else 0
        if not mine and not permanent.tapped:
            return (0 if creature else 2, -power)
        if mine and permanent.tapped:
            return (1 if creature else 3, -power)
        return (4, 0)

    return sorted(permanents, key=rank)


def toll_effect_side(instruction: OracleInstruction | None) -> str | None:
    """The side of the effect a **toll** imposes on its target — "<effect>
    unless its controller pays {N}" — read off the branch the toll guards,
    or None for any other shape.

    "Return target creature to its owner's hand unless its controller pays
    {1}." (Crystal Shard, Erratic Portal.) It compiles to an offer to the
    target's controller (``may``, actor ``controller``) whose unpaid branch is
    the bounce — and that bounce prints no ``targets`` payload, so every step
    reader above had nothing to read and the chooser aimed at the largest
    creature on either board: an AI seat bounced its own and then paid its
    own toll. The penalty is the effect; its family says whose creature it is
    for."""
    if instruction is None or instruction.kind != "may":
        return None
    payload = instruction.payload or {}
    if payload.get("actor") != "controller" or not payload.get("otherwise"):
        return None
    sides = {
        activation_target_side(step)
        for branch in payload["otherwise"]
        for step in (branch, *_effect_steps(branch))
    } - {None}
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


#: The steps that untap their target and do nothing else to it. An untap is a
#: second use of a permanent that has been used (``_OWN_KINDS``), so its worth
#: is a **state** as well as a seat: an untapped target gains nothing.
UNTAP_TARGET_KINDS = frozenset({"untap_target_permanent", "untap_target_land"})


def untaps_its_target(instruction: OracleInstruction | None) -> bool:
    """Whether every step of *instruction* — wrappers opened ("you may pay
    {3}. If you do, untap target permanent", the Mirage Talismans) — untaps
    its target (:data:`UNTAP_TARGET_KINDS`).

    Every step, so an untap that is half of something else is not this:
    provoke's "untap target creature … and it blocks this creature if able"
    is aimed by the fight it compels (``ai_compelled_blocks``), and Soldevi
    Golem's "If you do, untap this creature" by the source it frees."""
    if instruction is None:
        return False
    steps = _effect_steps(instruction)
    return bool(steps) and all(step.kind in UNTAP_TARGET_KINDS for step in steps)


def untap_target_order(permanents: list) -> list:
    """The **tapped** permanents of *permanents*, in the order an untap is
    best aimed: creatures first, the largest first (an attacker or a blocker
    given back to the turn), then every other permanent but a land, then the
    lands — a land untapped is one mana back, and the untaps that print a
    price ask more than that. Stable within a rank, so equal candidates keep
    the order they were offered in. Empty when nothing offered is tapped:
    there the untap is worth nothing wherever it is aimed."""

    def rank(permanent) -> tuple:
        if permanent.is_creature:
            return (0, -permanent.effective_power)
        return (2 if permanent.has_type("land") else 1, 0)

    return sorted((permanent for permanent in permanents if permanent.tapped), key=rank)


def counter_moved_off_target(instruction: OracleInstruction | None) -> str | None:
    """The kind of counter *instruction* moves **off** its target onto its
    source ("…you may move a +1/+1 counter from target creature onto this
    creature", Arcbound Fiend), every step and wrapper opened, or None.

    A move is worth what the target holds: CR 122.5 makes it nothing at all
    when the target has no such counter (:func:`counter_holder_order`)."""
    if instruction is None:
        return None
    steps = _effect_steps(instruction)
    if not steps or any(step.kind != "move_counter_to_self" for step in steps):
        return None
    kinds = {str((step.payload or {}).get("counter", "+1/+1")) for step in steps}
    return kinds.pop() if len(kinds) == 1 else None


def counter_holder_order(permanents: list, kind: str) -> list:
    """The permanents of *permanents* holding a *kind* counter, the most
    first — empty when none does, where a move is worth nothing wherever it
    is aimed. Stable within a count, so equal candidates keep their order."""
    from .named_counters import counters_on

    return sorted(
        (permanent for permanent in permanents if counters_on(permanent, kind) > 0),
        key=lambda permanent: -counters_on(permanent, kind),
    )


def shields_its_target(instruction: OracleInstruction | None) -> bool:
    """Whether every step of *instruction*, wrappers opened, is a shield
    (``ai_valuation.SHIELD_KINDS``: a regeneration, a prevention) — "When
    Daru Mender is turned face up, regenerate target creature." A shield is
    worth what it saves, so where it is aimed is a question of **threat** as
    well as of seat (:func:`shield_target_order`)."""
    from .ai_valuation import SHIELD_KINDS

    if instruction is None:
        return False
    steps = _effect_steps(instruction)
    return bool(steps) and all(step.kind in SHIELD_KINDS for step in steps)


def shield_target_order(game, chooser: int, permanents: list) -> list:
    """*permanents* in the order a shield is best aimed for *chooser*: one an
    object on the stack another seat controls is aimed at first (the
    Lightning Bolt at the Grizzly Bears the regeneration saves —
    ``stack_targets.chosen_targets``), then a creature in combat, then the
    dearest (``ai_standing.permanent_worth``), stable. The first candidate
    on the wanted side was whichever came first on the battlefield: Daru
    Mender, turned face up in answer to the Bolt, regenerated itself."""
    from .ai_standing import permanent_worth
    from .stack_targets import chosen_targets

    threatened: set = set()
    for item in getattr(game, "stack", ()) or ():
        if getattr(item, "caster_index", None) == chooser:
            continue
        for target in chosen_targets(game, item) or ():
            if target.kind == "permanent":
                threatened.add(target.permanent_id)

    def rank(permanent) -> tuple:
        fighting = bool(getattr(permanent, "attacking", False) or getattr(permanent, "is_blocking", False))
        return (
            permanent.permanent_id not in threatened, not fighting,
            -permanent_worth(permanent, now=False),
        )

    return sorted(permanents, key=rank)


def damage_dealt_to_its_target(item) -> "int | None":
    """The fixed damage a spell or ability on the stack deals its one target
    ("Lightning Bolt deals 3 damage to any target"), or None — several damage
    steps, an X, a division."""
    instruction = getattr(item, "ability_instruction", None)
    if instruction is not None:
        instructions = (instruction,)
    elif getattr(item, "card", None) is not None:
        # The spell as its text now reads (a text change rewrites it, CR 612).
        from .text_changes import spell_text_card

        instructions = compile_card_oracle(spell_text_card(item)).instructions
    else:
        return None
    amounts = [
        (step.payload or {}).get("amount")
        for each in instructions
        for step in _effect_steps(each)
        if step.kind == "deal_damage"
    ]
    if len(amounts) != 1:
        return None
    amount = amounts[0]
    return amount if isinstance(amount, int) and not isinstance(amount, bool) else None


def damage_target_worth(game, seat: "int | None", permanent, amount: int) -> float:
    """What *amount* damage at one target is worth against whoever takes it:
    a face, the life it takes (``ai_standing.life_worth``); a creature, its
    worth where the damage destroys it (lethal, and nothing it has survives
    destruction — ``ai_compelled_blocks.survives_destruction``) and nothing
    where it does not — the damage is gone at the cleanup step (CR 514.2)."""
    from .ai_compelled_blocks import survives_destruction
    from .ai_standing import life_worth, permanent_worth

    if permanent is None:
        if seat is None or not 0 <= seat < len(game.players):
            return 0.0
        life = game.players[seat].life
        return life_worth(life) - life_worth(life - amount)
    if not permanent.is_creature:
        return 0.0
    lethal = max(1, permanent.effective_toughness - permanent.damage_marked)
    if amount >= lethal and survives_destruction(game, permanent) is None:
        return permanent_worth(permanent, now=False)
    return 0.0


__all__ = [
    "HOST_LOSING_KINDS",
    "UNTAP_TARGET_KINDS",
    "ability_target_side",
    "cast_helps_the_player_it_names",
    "denies_its_target",
    "host_trigger_side",
    "named_counter_marks_for_harm",
    "instruction_target_side",
    "spell_denies_its_own_target",
    "spell_target_side",
    "sweep_a_named_counter_spares",
    "sweeps_what_its_counter_shelters",
    "toggle_target_order",
    "toll_effect_side",
    "toggles_its_target",
    "untap_target_order",
    "shield_target_order",
    "shields_its_target",
    "damage_dealt_to_its_target",
    "damage_target_worth",
    "untaps_its_target",
]


# -- Which opponent a count is taken on ---------------------------------------
#
# "…equal to the number of creatures you control in excess of the number of
# creatures **target opponent** controls" (Superior Numbers); "…where X is the
# number of black permanents **target opponent** controls" (Reap); "…add X
# mana …, where X is the number of Islands **target opponent** controls"
# (Carpet of Flowers). The seat is a target the caster chooses (CR 601.2c /
# 603.3d), and the only thing it changes is a number: which side of the table
# it belongs on is settled by the printed word ("opponent"), and which
# opponent is a **valuation** — the one the count comes out largest on. Read
# off the compiled program, so every card printing the template is aimed the
# day it is ingested.

#: The count ``owner`` words that name a seat the sentence targets — the
#: lowering's ``count_spec`` lift (``grammar/lowering/_amounts``).
_COUNTED_TARGET_OWNERS = frozenset({"target_opponent", "target_player"})

#: Where a step beneath a wrapper sits, for the walk below.
_COUNT_STEP_KEYS = ("steps", "action", "then", "else", "otherwise")


def _counts_a_target_seat(spec) -> bool:
    """Whether a count spec — or a count subtracted from it — is taken on a
    seat the sentence targets."""
    if not isinstance(spec, dict):
        return False
    return spec.get("owner") in _COUNTED_TARGET_OWNERS or _counts_a_target_seat(
        spec.get("minus")
    )


#: The payload keys a count spec rides under: an amount defined by one
#: (``x_from_count``) and a printed amount multiplied by one (``per_each``:
#: "you gain 2 life **for each** black and/or red creature target opponent
#: controls", Honorable Scout).
_COUNT_KEYS = ("x_from_count", "per_each")

#: The payload keys naming who an effect **acts on**. A step whose recipient
#: is the targeted seat itself ("target player draws a card for each basic
#: land type among lands they control", Allied Strategies) does not count on
#: the seat beside acting on it — it acts on it, which side of the table the
#: effect is good for decides, and a count-only valuation would hand an
#: opponent the cards.
_RECIPIENT_KEYS = ("recipient", "who")


def _seat_count_spec(instructions) -> "dict | None":
    """The first count under *instructions* that is taken on a targeted seat
    **and only counted there**, or None."""
    for instruction in instructions or ():
        payload = getattr(instruction, "payload", None) or {}
        acted_on = any(
            payload.get(key) in _COUNTED_TARGET_OWNERS for key in _RECIPIENT_KEYS
        )
        for count_key in _COUNT_KEYS:
            spec = payload.get(count_key)
            if _counts_a_target_seat(spec):
                return None if acted_on else spec
        for key in _COUNT_STEP_KEYS:
            nested = payload.get(key)
            if isinstance(nested, (list, tuple)):
                found = _seat_count_spec(nested)
                if found is not None:
                    return found
    return None


def _as_counted_on_the_target(spec: dict) -> dict:
    """*spec* with every half read off ``context.target``: the announcement's
    role binding (``target_roles.COUNTED_SEAT_ROLE``) dropped, which is the
    question this asks — what would the count be *if* this seat were named."""
    from .target_roles import COUNTED_SEAT_ROLE

    unbound = {key: value for key, value in spec.items() if key != COUNTED_SEAT_ROLE}
    if isinstance(spec.get("minus"), dict):
        unbound["minus"] = _as_counted_on_the_target(spec["minus"])
    return unbound


def counted_target_seat_amount(
    game, chooser: int, instructions, seat: int, card: CardDefinition | None = None,
) -> "int | None":
    """The amount *instructions*' targeted-seat count comes to if *seat* is
    the seat named — the damage, the cards, the mana — or None where nothing
    under them counts on a targeted seat.

    Through ``handlers/_amounts.count_from_payload``, the evaluator the
    resolution itself uses, so the number weighed is the number spent. A
    ``per_each`` count is the multiplier, which orders the seats the way the
    product does.
    """
    spec = _seat_count_spec(instructions)
    if spec is None or not 0 <= seat < len(game.players):
        return None
    from .game_types import OracleExecutionContext
    from .handlers._amounts import count_from_payload

    context = OracleExecutionContext(
        caster=game.players[chooser], target=game.players[seat], card=card,
    )
    return int(count_from_payload(game, context, _as_counted_on_the_target(spec)))


def best_counted_target_seat(
    game, chooser: int, instructions, seats, card: CardDefinition | None = None,
) -> "int | None":
    """Of *seats* — the legal answers, in the picker's order — the one the
    targeted-seat count under *instructions* is largest on; None where
    nothing there counts on a targeted seat. Ties keep the picker's order.

    Largest, because every printing counts what the effect is *sized* by: the
    damage dealt, the cards returned, the mana added. A count subtracted from
    another is already folded in (the difference is what is weighed), so the
    opponent with the fewest creatures is Superior Numbers' best.
    """
    best: "int | None" = None
    best_amount: "int | None" = None
    for seat in seats:
        amount = counted_target_seat_amount(game, chooser, instructions, seat, card)
        if amount is None:
            return None
        if best_amount is None or amount > best_amount:
            best, best_amount = seat, amount
    return best
