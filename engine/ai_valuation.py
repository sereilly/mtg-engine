"""What a card does, in the terms the AI's heuristics ask about.

``ai_policy`` scores a card by asking a handful of questions — how many cards
does this make its target draw, does it return a creature to hand, what does it
destroy, does it counter a spell, is it a mana source — and every one of them
used to be answered by comparing ``card.name`` against a literal. That is the
whitelist shape this codebase keeps finding, one layer up from the rules engine:
the answers are derivable from the **compiled program**, so a functionally
identical card under any other name gets the same valuation and the ~26,000
cards still to come need no entries.

The measured decay, in the current pool, before this module existed:

* ``card.name == "Disenchant"`` aimed a targeted destroy at the opponent.
  Shatter, Terror, Stone Rain and Desert Twister print the same template, were
  not in the whitelist, and the AI **targeted itself** with all four — Shatter
  resolved onto the AI's own Howling Mine.
* ``card.name == "Ancestral Recall"`` kept the AI from decking itself. Braingeyser
  is "Target player draws X cards"; with two cards left the AI cast it at
  itself for X=2 and emptied its own library (CR 704.5b on the next draw).
* ``"counter target spell" in text or card.name == "Counterspell"`` — the name
  half is dead (Counterspell's text *is* that sentence) and the text half misses
  every counterspell whose wording differs, including both Elemental Blasts.

Nothing here re-reads oracle text: every derivation goes through
``compile_card_oracle``, so the AI's opinion of a card and the engine's execution
of it cannot disagree about what the card does.

**Scope.** These describe a spell's or an ability's *effect*, not its value; the
weights stay in ``ai_policy``. Heuristics are tuning, and a tuning constant is
not a correctness claim — but *which cards a constant applies to* is, and that
is what lives here.

The same split is why ``offered_action_is_a_payment`` is here rather than in
``engine/mixins/stack/choices.py`` beside the default that reads it. "This
offer's price comes out of the taker's own permanents, hand, library or life"
is a claim about what a card *does*, true of every card printing the sentence;
"and therefore a seat nobody asked refuses it" is the stated policy, and that
stays with the other stated policies in ``_default_optional_pay``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CardDefinition
from .oracle import OracleInstruction, compile_card_oracle
from .oracle_types import cost_target_count

# Card types whose *resolution* carries out ``OracleProgram.instructions``.
#
# A permanent's activated ability is mirrored into ``instructions`` as well as
# into ``activated_abilities`` — Royal Assassin's "{T}: Destroy target creature"
# compiles to ``instructions=['destroy_target_permanent']`` — so reading that
# list unguarded would value a creature *in hand* as a removal spell and aim it
# at an opponent it cannot touch until it has been on the battlefield a turn.
SPELL_TYPES = frozenset({"instant", "sorcery"})

# Instruction kinds that add mana to their controller's pool (CR 605.1a).
#
# Spelled out rather than probed for, and guarded: the set this replaced was
# ``{"add_mana", "black_lotus_add_mana"}``, and **neither kind existed any more**.
# Both had been renamed out from under it, so the check that was meant to stop
# the AI idly tapping its mana rocks silently stopped firing, and the AI
# sacrificed Black Lotus for mana it had no way to spend.
# ``tests/ai/test_ai_valuation.py`` holds every kind named here to a registered
# ``EFFECT_HANDLERS`` entry, so the next rename fails loudly instead.
MANA_ABILITY_KINDS = frozenset({"add_mana_from_text", "sacrifice_self_for_mana"})


@dataclass(frozen=True)
class CounterProfile:
    """A "counter target spell" effect, and what it may be aimed at.

    ``color`` is the mana symbol the countered spell must have (Red Elemental
    Blast counters blue), or None when any spell is a legal target. It is a
    field rather than an assumption because a colourless reading would have the
    AI hold up Red Elemental Blast against a green spell — the generalisation
    that looks free and plays worse than the whitelist it replaced.
    """

    color: str | None = None

    def can_counter(self, card: CardDefinition) -> bool:
        return self.color is None or self.color in (card.colors or ())


def _spell_instructions(card: CardDefinition) -> tuple[OracleInstruction, ...]:
    """The instructions resolving *card* **as a spell** carries out.

    Empty for a permanent card; see ``SPELL_TYPES``.
    """
    if card.primary_type not in SPELL_TYPES:
        return ()
    return tuple(compile_card_oracle(card).instructions)


def _first(card: CardDefinition, kind: str) -> OracleInstruction | None:
    return next((item for item in _spell_instructions(card) if item.kind == kind), None)


def cards_drawn_by_target(card: CardDefinition, x_value: int | None = None) -> int | None:
    """How many cards resolving *card* makes its **target** draw, or None.

    None means "this spell does not draw for its target" *or* "it draws a
    variable number and none was chosen yet" — the two cases the caller treats
    identically, because both leave the deck-out check unanswerable. A caller
    that has picked an X passes it: Braingeyser draws X, and the AI must not
    aim it at a library it would empty any more than it may aim Ancestral
    Recall there.
    """
    instruction = _first(card, "draw_target_cards")
    if instruction is None:
        return None
    amount = instruction.payload.get("amount")
    if isinstance(amount, int):
        return amount
    if str(amount).lower() == "x":
        return x_value
    return None


def spell_makes_its_target_lose_life(card: CardDefinition) -> bool:
    """Whether resolving *card* makes its **target player** lose life.

    "Target player loses 4 life and you gain 4 life." (Soul Feast.) The spell
    scorer's text probes saw "gain … life" and nothing that read "loses", so the
    caster's own seat won the score and the AI drained itself — a wash on its
    own life total and a card spent. Read off the compiled program, wrappers
    opened (Rhystic Syphon's loss sits on a toll's declined branch), and only
    where the loss lands on the target rather than on a named seat.
    """
    def walk(instructions) -> bool:
        for instruction in instructions:
            payload = getattr(instruction, "payload", None) or {}
            if instruction.kind == "target_loses_life" and payload.get("recipient") is None:
                return True
            for key in ("steps", "then", "else", "action", "otherwise", "unpaid"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)) and walk(nested):
                    return True
        return False

    return walk(_spell_instructions(card))


def cards_drawn_by_controller(instruction: OracleInstruction) -> int | None:
    """How many cards *instruction* makes its controller draw, or None.

    Takes an instruction rather than a card because its caller is scoring one
    *activated ability* of a permanent already on the battlefield.
    """
    if instruction.kind != "draw_controller_cards":
        return None
    amount = instruction.payload.get("amount")
    return amount if isinstance(amount, int) else None


def returns_creature_to_hand(card: CardDefinition) -> bool:
    """Whether resolving *card* returns a target creature to its owner's hand."""
    return _first(card, "bounce_target_creature") is not None


def destroyed_permanent_filter(card: CardDefinition) -> dict | None:
    """The target filter of *card*'s targeted destroy, or None if it has none.

    The payload is the same filter dict ``permanent_matches_filter`` reads, so
    the AI counts exactly the permanents the engine would let it choose — no
    second opinion about what "target artifact or enchantment" means. An
    unfiltered destroy (Desert Twister) returns an empty dict, which matches
    every permanent; None is reserved for "this spell destroys nothing".
    """
    instruction = _first(card, "destroy_target_permanent")
    if instruction is None:
        return None
    return dict(instruction.payload)


def counters_a_spell(card: CardDefinition) -> CounterProfile | None:
    """The counter effect resolving *card* has, or None."""
    instruction = _first(card, "counter_top_stack_spell")
    if instruction is None:
        return None
    return CounterProfile(color=instruction.payload.get("color_filter"))


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
    wrappers opened (``sequence``, ``if_then``, ``may``)."""
    found: list[OracleInstruction] = []

    def walk(instructions) -> None:
        for instruction in instructions:
            targets = (instruction.payload or {}).get("targets")
            if isinstance(targets, dict) and targets.get("kind") == "object":
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
    ``ai_policy._choose_target_for_spell`` had no case for: its score is a
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


def entry_trigger_target_side(card: CardDefinition) -> str | None:
    """Whose permanent a **permanent** spell's enters-the-battlefield trigger
    should be aimed at — "you", "opponent" or None.

    This engine names an entry trigger's target as the permanent is cast
    (``targeting._cast_target_spec``: "a standing approximation"), so the cast
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


#: The printed controller narrowings a target's noun phrase can carry, as sides.
_PRINTED_SEATS = {"you": "you", "not_you": "opponent", "opponent": "opponent"}


def hand_entry_steps(instruction: OracleInstruction) -> tuple[dict, ...]:
    """The payload of every "put a … card from **your** hand onto the
    battlefield" step *instruction* carries, wrappers opened (a "you may"
    included).

    The whole effect of such an ability is the card it puts in, so with no card
    the printed noun admits in the controller's hand its resolution is nothing:
    Belbe's Portal paid {3} every turn of a simulated game to log "has no card
    Belbe's Portal could put onto the battlefield". Which cards a step admits is
    the engine's own ``put_from_hand_candidates``; this only finds the steps.
    """
    found: list[dict] = []

    def walk(step) -> None:
        payload = getattr(step, "payload", None) or {}
        if step.kind == "put_chosen_card_from_hand_onto_battlefield" and payload.get(
            "whose"
        ) in (None, "you"):
            found.append(dict(payload))
        for key in ("steps", "then", "else", "action", "otherwise"):
            nested = payload.get(key)
            if isinstance(nested, (list, tuple)):
                for inner in nested:
                    walk(inner)

    if instruction is not None:
        walk(instruction)
    return tuple(found)


def hand_pick_entry_consumer(card: CardDefinition, result_key: str) -> dict | None:
    """What *card*'s program does with a hand pick recorded under
    *result_key*, when what it does is put the picked cards **onto the
    battlefield for their owner** — the printed noun phrase that admits a pick
    and the superlative that decides between the picks — or None.

    "Each player chooses a card in their hand. … The owner of each creature
    card revealed this way with the lowest mana value puts it onto the
    battlefield." (Stronghold Gambit.) A pick that the next sentence turns into
    a free permanent is a gift to the picker, and the picks that receive it are
    the ones this answer describes; the stated default took the first card in
    hand order and revealed a land or an artifact as often as a creature.
    """
    for instruction in _walk_program(compile_card_oracle(card)):
        payload = instruction.payload or {}
        if (
            instruction.kind == "put_chosen_hand_cards_onto_battlefield"
            and str(payload.get("cards_from")) == str(result_key)
        ):
            return {
                "card_filter": dict(payload.get("card_filter") or {}),
                "superlative": dict(payload.get("superlative") or {}),
            }
    return None


def spell_hand_pick_entry_filters(card: CardDefinition) -> tuple[dict, ...]:
    """For each "choose a card in your hand" step of *card*'s spell program
    whose pick the program then puts onto the battlefield for its owner
    (:func:`hand_pick_entry_consumer`), the noun phrase a pick must answer to
    get there.

    A caster holding no such card gets nothing from the spell, and Stronghold
    Gambit's "each player" makes it worse than nothing: the opponent's pick is
    the only one that can enter. Asked before the cast for that reason.
    """
    filters: list[dict] = []

    def walk(instructions) -> None:
        for instruction in instructions:
            payload = instruction.payload or {}
            if instruction.kind == "choose_cards_in_hand":
                consumer = hand_pick_entry_consumer(
                    card, str(payload.get("result_key") or "chosen_hand_cards")
                )
                if consumer is not None:
                    filters.append(consumer["card_filter"])
            for key in ("steps", "then", "else", "action", "otherwise"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)):
                    walk(nested)

    walk(_spell_instructions(card))
    return tuple(filters)


def _reads_chosen_creature_type(value) -> bool:
    """Whether a payload, at any depth, names "the chosen type" (CR 614.1c's
    entry record), by the ``chosen_creature_type`` key or the token's
    ``from_chosen`` list."""
    if isinstance(value, dict):
        if value.get("chosen_creature_type"):
            return True
        if "creature_type" in tuple(value.get("from_chosen") or ()):
            return True
        return any(_reads_chosen_creature_type(inner) for inner in value.values())
    if isinstance(value, (list, tuple)):
        return any(_reads_chosen_creature_type(inner) for inner in value)
    if isinstance(value, OracleInstruction):
        return _reads_chosen_creature_type(value.payload)
    return False


def chosen_creature_type_side(card: CardDefinition) -> str | None:
    """Whose creatures *card*'s "choose a creature type" should name — "you",
    "opponent", or None when nothing it prints says.

    The entry default read the **opponents'** board for every such card, which
    is right for the ones that hose the type and backwards for the ones that
    feed it. W1G5 watched Belbe's Portal pay {3} every turn to put a creature of
    the opponent's type out of a hand that held none. The answer is in what the
    card does with the word:

    * a P/T change to the type, by its sign ("All creatures of the chosen type
      get -1/-1", Engineered Plague);
    * something put onto the battlefield **for its controller** that the type
      describes — a card from the controller's own hand (Belbe's Portal), a
      token the card creates (Volrath's Laboratory);
    * the two derivation tables that read "of the chosen type" on lines the
      compiled program does not carry: an untap lock is a denial (An-Zerrin
      Ruins), a cost reduction a gift (Urza's Incubator) and a cost increase a
      tax.

    Readings that disagree, or none at all (Conspiracy, whose type is about the
    controller's creatures *becoming* it), are None and keep the standing
    default.
    """
    from .cost_modifiers import cost_modifiers_for
    from .untap_restrictions import untap_restriction_for

    sides: set[str] = set()
    for instruction in _walk_program(compile_card_oracle(card)):
        payload = instruction.payload or {}
        if not _reads_chosen_creature_type(payload):
            continue
        if instruction.kind == "lord_buff":
            total = sum(
                value for value in (payload.get("power"), payload.get("toughness"))
                if isinstance(value, int) and not isinstance(value, bool)
            )
            if total:
                sides.add("you" if total > 0 else "opponent")
        elif instruction.kind == "create_token":
            sides.add("you")
        elif instruction.kind == "put_chosen_card_from_hand_onto_battlefield" and (
            payload.get("whose") in (None, "you")
        ):
            sides.add("you")
    text = card.oracle_text or ""
    restriction = untap_restriction_for(text)
    if restriction is not None and _reads_chosen_creature_type(
        getattr(restriction, "blocked", None)
    ):
        sides.add("opponent")
    for modifier in cost_modifiers_for(text):
        if modifier.chosen_creature_type:
            sides.add("you" if modifier.reduces else "opponent")
    return next(iter(sides)) if len(sides) == 1 else None


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


def caster_sacrifice_steps(card: CardDefinition) -> tuple[dict, ...]:
    """The payload of every step in which *card*'s caster **sacrifices** as part
    of the spell's effect — not a cost (CR 601.2b), a printed instruction
    ("Sacrifice a creature. Rupture deals damage equal to that creature's
    power…"). Each carries the printed ``filter`` and, for "sacrifice **any
    number of** …", ``any_number``.

    CR 701.21a: a player sacrifices only what they control, and an effect that
    has its controller sacrifice something they do not have does nothing — and
    every such spell in the pool keys the rest of itself to the sacrifice ("that
    creature's power", "if you do", "for each permanent sacrificed this way").
    So a board with nothing matching is a resolution that does nothing, which is
    the question the AI asks before casting. Steps scoped to another player
    (``who``: "each_player", "target_opponent") are not the caster's.
    """
    found: list[dict] = []

    def walk(instructions) -> None:
        for instruction in instructions:
            payload = instruction.payload or {}
            if instruction.kind == "sacrifice_matching_permanent" and payload.get(
                "who"
            ) in (None, "you", "caster"):
                found.append({
                    "filter": dict(payload.get("filter") or {}),
                    "any_number": bool(payload.get("any_number")),
                })
            for key in ("steps", "then", "else", "action", "otherwise"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)):
                    walk(nested)

    walk(_spell_instructions(card))
    return tuple(found)


#: Instruction kinds whose whole effect is that the player performing them
#: **pays** — CR 118.3's list of what a cost can be, restricted to the ones the
#: rules define as done to oneself, which is why no payload has to be consulted
#: to know whose resources are spent:
#:
#: * CR 701.21a — "A player can't sacrifice ... something that's a permanent
#:   they don't control": a sacrifice is always of your own permanent;
#: * CR 701.9a — a discard moves a card "from its **owner's** hand";
#: * CR 118.3b — life is subtracted from the paying player's own life total;
#: * CR 407.4 — "the owner of an object is the only player who can ante that
#:   object", and CR 407.2 hands the ante zone to the winner, so it is the one
#:   price on this list a player does not get back at end of game;
#: * CR 701.13a — an exile, here out of the offered seat's own hand or off its
#:   own battlefield, which is what the two kinds below name.
#:
#: A kind, never a card: "you may sacrifice a creature" is one price whoever
#: prints it, so the eight cards in the pool that print it and every card still
#: to come are classified by construction. Held to live handler kinds by
#: ``tests/engine/test_optional_offer_defaults.py``, which is the guard
#: ``MANA_ABILITY_KINDS`` above wants for the same reason: a rename that
#: emptied this set would silently restore the always-accept default.
SELF_PAYMENT_KINDS = frozenset({
    "sacrifice_matching_permanent",
    "sacrifice_self",
    "sacrifice_attached_permanent",
    "discard_controller_cards",
    "pay_life",
    "ante_top_card",
    "exile_chosen_card_from_hand",
    # "You may **exile all cards from your hand** face down." (Duplicity.) The
    # pile spelling of the row above, and a price for exactly its reason: the
    # cards come out of the offered seat's own hand. Without it the offer read
    # as free — the cost is lowered *into* the offered action, where the
    # affordability test cannot find it — and a headless seat would exile its
    # whole hand every upkeep, which is the failure this set is written to
    # catch.
    "exile_hand_pile",
    "exile_any_number_of_own_tokens",
})


def payload_reference(step) -> str:
    """The printed player reference a step aimed at a *named* seat names.

    ``who`` where the lowering wrote one ("defending player discards three
    cards", Mindstab Thrull) and "target" where it did not — an absent key is
    the handler reading ``context.target``, which is the seat the sentence
    chose. One reader, because the answer decides whether a step is a price and
    a second spelling would price the same sentence two ways.
    """
    return str((getattr(step, "payload", None) or {}).get("who") or "target")


def _step_is_a_payment(step, self_recipients: frozenset[str]) -> bool:
    kind = getattr(step, "kind", None)
    if kind in SELF_PAYMENT_KINDS:
        return True
    if kind == "deal_damage":
        # "…**or have this enchantment deal 5 damage to that player**" (Worms
        # of the Earth). Damage is a price only when the player taking the
        # offer is the one dealt it, which the payload cannot say on its own —
        # the recipient is a printed reference ("caster", "target_player") that
        # the resolution binds. So the caller resolves those references to
        # seats and passes in the ones that name the offered seat; Goblin
        # Arsonist's "you may have it deal 1 damage to any target" names no
        # player recipient at all and is a gift.
        return step.payload.get("recipient") in self_recipients
    if kind == "discard_target_cards":
        # "…unless that player **discards a card**" (Forbidden Ritual). A
        # discard out of the offered seat's own hand is a price, and this kind
        # is how the grammar lowers one aimed at a *named* seat —
        # ``discard_controller_cards`` in the set above is the same deed
        # aimed at "you". Which seat it is cannot be read off the payload
        # alone, exactly as it cannot for damage above: the discarder is a
        # printed reference the resolution binds, absent meaning the target the
        # sentence chose. So the caller's resolved set answers it, and a
        # sentence making somebody *else* discard stays what it is — a gift.
        return str(payload_reference(step)) in self_recipients
    if kind == "choose_one":
        # "…sacrifice a creature **or** discard a creature card" (Crypt
        # Lurker). CR 601.2b lets the payer pick, so the offer is a price only
        # when *every* alternative left on it is one — an offer with a way out
        # that costs nothing is not a price. The modes read here are the ones
        # ``_narrow_to_takeable_actions`` left, so a mode the seat could not
        # take is not counted against it.
        modes = tuple(step.payload.get("modes") or ())
        chosen = [
            mode["instruction"]
            for mode in modes
            if isinstance(mode, dict) and mode.get("instruction") is not None
        ]
        return bool(chosen) and all(
            _step_is_a_payment(instruction, self_recipients)
            for instruction in chosen
        )
    return False


def offered_action_is_a_payment(steps, self_recipients=()) -> bool:
    """Whether taking this offer spends the offered seat's **own** resources.

    *steps* is the offer's accept branch as the compiled program holds it, and
    the leading step is the one the printed sentence offers: the grammar splits
    "You may **A**. If you do, B." into ``action`` and ``then``, and
    ``handlers/control_flow._offer_to_seat`` concatenates them in that order. So
    A is what the seat is being asked to *do* and B is what follows from it —
    which is the whole difference between Sylvan Library ("you may **draw two
    additional cards**. If you do, … pay 4 life or put the card back") and
    Crypt Lurker ("you may **sacrifice a creature or discard a creature card**.
    If you do, draw a card"). Reading the branch as a whole would call both of
    them payments, and reading it as a whole *backwards* would call both gifts.

    *self_recipients* is the set of printed player references that resolve to
    the offered seat, for the one kind whose answer depends on it.
    """
    leading = next((step for step in steps if getattr(step, "kind", None)), None)
    if leading is None:
        return False
    return _step_is_a_payment(leading, frozenset(self_recipients))


#: The alternatives whose whole effect is to give one permanent a keyword, or
#: take one away, and whose recipient a resolution context names: the source
#: itself, or the object the ability was announced with (CR 602.2b).
_GRANTS_TO_SOURCE = frozenset({"grant_self_keyword_until_eot", "grant_self_flying_until_eot"})
_GRANTS_TO_TARGET = frozenset({"grant_target_keyword_until_eot", "grant_target_flying_until_eot"})
_REMOVES_FROM_TARGET = frozenset({"remove_target_keyword_until_eot"})


def offered_alternative_changes_nothing(game, instruction, context) -> bool:
    """Whether taking this alternative of a CR 608.2d choice would leave the
    board exactly as it is.

    The choice is made *while the effect is applied*, so the board it is made
    on is the one the opponent's response left — which is the whole point of
    asking then rather than at activation, and what makes a better default
    than printed order possible. "Target creature loses first strike **or**
    swampwalk" (Urborg) aimed at a swampwalker, or "loses your choice of
    flying, first strike, or trample" (Walking Sponge) aimed at a trampler,
    takes nothing if the first printed word is taken; "this creature gains
    flying, first strike, or trample" (Flowstone Sculpture) on a creature that
    already flies grants nothing.

    Answered for one shape only — a keyword given or taken — because that is
    the one whose effect is fully read off the board. Every other alternative
    answers False, which leaves the caller's printed-order policy exactly as it
    was.
    """
    kind = getattr(instruction, "kind", None)
    payload = getattr(instruction, "payload", None) or {}
    if kind in _GRANTS_TO_SOURCE:
        recipient = getattr(context, "source_permanent", None)
    elif kind in _GRANTS_TO_TARGET or kind in _REMOVES_FROM_TARGET:
        announced = getattr(context, "target_permanent_id", None)
        if isinstance(announced, list):
            announced = announced[0] if len(announced) == 1 else None
        recipient = game.permanent_by_id(announced) if isinstance(announced, int) else None
    else:
        return False
    if recipient is None or not game.is_on_battlefield(recipient):
        return False
    keywords = tuple(payload.get("keywords") or ())
    if not keywords and kind.endswith("_flying_until_eot"):
        keywords = ("flying",)
    if not keywords:
        return False
    held = [bool(game._has_keyword(recipient, keyword)) for keyword in keywords]
    if kind in _REMOVES_FROM_TARGET:
        return not any(held)
    return all(held)


def threatening_color(game, seat: int) -> str | None:
    """The colour of the opposing object a colour chosen *now* is answering,
    or None when nothing on the stack is one.

    "The color of your choice" is named while the effect is applied (CR
    608.2d), which is after every response has resolved and with the stack
    beneath it still waiting — so when Mother of Runes resolves in answer to a
    Lightning Bolt, the Bolt is the topmost object under it, and red is the
    colour whose protection makes the Bolt's target illegal (CR 702.16b). That
    is the whole of the derivation: the topmost object on the stack an opponent
    of *seat* controls, and the first of its colours in CR 105.1's order.
    Through ``_stack_item_colors``, so a spell a Lace recoloured answers as the
    colour it now is, and an ability answers as its source's colour — the
    colour CR 702.16e's damage prevention asks about.

    Nothing on the stack names no colour, and the caller falls back to its own
    board-wide policy.
    """
    for item in reversed(getattr(game, "stack", ()) or ()):
        controller = getattr(item, "caster_index", None)
        if controller is None or controller == seat:
            continue
        colors = set(game._stack_item_colors(item))
        for color in ("W", "U", "B", "R", "G"):
            if color in colors:
                return color
    return None


@dataclass(frozen=True)
class TollLoss:
    """What one branch of a *toll* takes from the offered seat, as resources.

    A toll is an offer with a printed penalty for refusing ("…unless you pay 2
    life", "…deals 2 damage to that player unless they sacrifice that
    artifact"), so both of its branches are losses and the seat's answer is
    whichever loss is smaller. This is the loss as the compiled program states
    it — counts of resources, with the permanents resolved to the very objects
    the engine's own deterministic picks would give up — and pricing those
    resources against each other is the weights' job in ``ai_policy``
    (`_toll_loss_price`), which is the same split as every other derivation
    here.
    """

    life: int = 0
    #: Cards leaving the seat's hand or (for an ante) its library for good.
    cards: int = 0
    #: Cards milled off the seat's own library — a loss, but a far smaller one.
    milled: int = 0
    #: The permanents this branch takes off the seat's battlefield: the source
    #: itself, the attached host, or the engine's own default sacrifice picks.
    permanents: tuple = ()
    #: Whether the branch taps the source permanent (a turn's use, not a card).
    taps_source: bool = False

    def plus_life(self, amount: int) -> "TollLoss":
        return TollLoss(
            life=self.life + amount, cards=self.cards, milled=self.milled,
            permanents=self.permanents, taps_source=self.taps_source,
        )


def toll_branch_loss(
    game, player_index: int, steps, self_recipients=(), source_permanent=None
) -> TollLoss | None:
    """The loss running *steps* costs seat *player_index*, or None when a step's
    loss is not derivable from the compiled program.

    None is a refusal, not a zero: a branch containing any step this cannot
    price ("counter that spell", "creatures able to block it do so") makes the
    whole branch unpriceable, and the caller keeps the standing policy — pay
    tolls — rather than comparing a number to a guess.

    The permanents are resolved to the engine's own answers so the valuation
    and the execution cannot disagree about what is given up:
    ``_sacrifice_candidate_indices`` is what a forced sacrifice may take and
    ``default_sacrifice_pick``'s ordering is which one a seat nobody asked
    gives, exactly as ``destroyed_permanent_filter`` above reuses the engine's
    filter matcher instead of holding a second opinion.

    *self_recipients* is the same set ``offered_action_is_a_payment`` takes,
    resolved by the caller, for the steps whose payload names a printed player
    reference (``deal_damage``, a self-mill).
    """
    from .handlers._common import attached_host

    player = game.players[player_index]
    recipients = frozenset(self_recipients)
    life = 0
    cards = 0
    milled = 0
    permanents: list = []
    taps_source = False
    for step in steps:
        kind = getattr(step, "kind", None)
        payload = getattr(step, "payload", None) or {}
        if kind == "pay_life":
            amount = payload.get("amount")
            if not isinstance(amount, int):
                return None
            life += amount
        elif kind == "deal_damage":
            amount = payload.get("amount")
            if not isinstance(amount, int) or payload.get("recipient") not in recipients:
                return None
            life += amount
        elif kind in ("sacrifice_self", "destroy_self"):
            if source_permanent is None or not game.is_on_battlefield(source_permanent):
                return None
            permanents.append(source_permanent)
        elif kind in ("sacrifice_attached_permanent", "destroy_attached_permanent"):
            host = attached_host(game, source_permanent)
            if host is None:
                return None
            permanents.append(host)
        elif kind == "sacrifice_matching_permanent":
            count = int(payload.get("count", 1) or 1)
            exclude = source_permanent if payload.get("exclude_self") else None
            # Indices resolved through the seam (`permanent_at`), never by
            # subscripting the battlefield here — the slot is the engine's to
            # interpret (tests/engine/test_control_reads.py).
            candidates = [
                permanent
                for index in game._sacrifice_candidate_indices(
                    player, dict(payload.get("filter") or {}), exclude
                )
                for permanent in (game.permanent_at(player, index),)
                if permanent is not None
            ]
            if len(candidates) < count:
                return None
            candidates.sort(key=game.sacrifice_preference_key)
            permanents.extend(candidates[:count])
        elif kind == "discard_controller_cards":
            amount = payload.get("amount")
            if not isinstance(amount, int):
                return None
            cards += amount
        elif kind == "ante_top_card":
            cards += 1
        elif kind == "mill_target_player":
            amount = payload.get("amount")
            if not isinstance(amount, int) or payload.get("recipient") not in recipients:
                return None
            milled += amount
        elif kind == "tap_self":
            taps_source = True
        else:
            return None
    return TollLoss(
        life=life, cards=cards, milled=milled,
        permanents=tuple(permanents), taps_source=taps_source,
    )


def castable_commanders(game, player_index: int):
    """Each ``(zone_index, card, tax)`` the seat may cast from its command zone
    right now — CR 903.8's grant, with CR 903.8's tax beside it.

    Asked of the engine's own commander seam (``may_cast_from_command_zone``,
    ``commander_tax``) rather than derived a second time, so the AI is offered
    exactly the casts the browser's zone badge offers a human seat
    (``cast_permissions.playable_from_zones``) and the tax it must price is the
    one the cast path will charge. Empty outside a Commander game — the zone is
    empty and the seam answers False — so an ordinary duel never reads it.
    """
    player = game.players[player_index]
    return tuple(
        (index, card, game.commander_tax(player_index, card))
        for index, card in enumerate(player.command_zone)
        if game.may_cast_from_command_zone(player_index, card)
    )


def entry_sacrifice_is_unavoidable(game, seat: int, card: CardDefinition) -> bool:
    """Whether *card*, entering under *seat* now, would be sacrificed by its own
    entry trigger because the price to keep it cannot be met.

    "When this land enters, sacrifice it unless you return a non-Lair land you
    control to its owner's hand." (the five Lairs; Visions' Karoo cycle prints
    the same sentence about an untapped basic.) Played with no such land on the
    battlefield the card goes straight to the graveyard and the turn's land
    drop goes with it — a legal play no player makes, and one the land-drop
    chooser made on turn one whenever such a land added a colour the hand
    wanted.

    Read off the compiled program, so it is a claim about the *shape* and not
    a list of ten names: an enters-the-battlefield trigger that is an offer
    whose declined branch sacrifices the source and whose accepted branch
    opens by having the controller choose at least N of their own permanents.
    The candidates are counted through ``subject_matches`` with the seat as
    observer — the handler's own reading of the phrase — so "non-Lair", "an
    untapped Plains" and whatever the next cycle prints are payload.

    False for every other shape, including a price this cannot count: an
    answer of "unavoidable" keeps a card in hand, so it is given only where
    the count is certain.
    """
    from .subject_filters import subject_matches

    for trigger in compile_card_oracle(card).triggered_abilities:
        instruction = trigger.instruction
        if (
            trigger.condition.kind != "enters_battlefield"
            or instruction is None
            or instruction.kind != "may"
            or instruction.payload.get("actor") != "you"
        ):
            continue
        declined = instruction.payload.get("otherwise") or ()
        if [step.kind for step in declined] != ["sacrifice_self"]:
            continue
        action = instruction.payload.get("action") or ()
        if not action or action[0].kind != "choose_permanents":
            continue
        asked = action[0].payload or {}
        if asked.get("chooser") != "you" or asked.get("controlled_by") != "chooser":
            continue
        needed = int(asked.get("at_least", 0) or 0)
        if needed <= 0:
            continue
        described = asked.get("filter") or {}
        available = sum(
            1
            for permanent in game.controlled_by(seat)
            if subject_matches(game, permanent, described, observer=seat)
        )
        if available < needed:
            return True
    return False


def is_mana_ability(instruction: OracleInstruction) -> bool:
    """Whether *instruction* adds mana to its controller's pool."""
    return instruction.kind in MANA_ABILITY_KINDS


def mana_ability_symbols(instruction: OracleInstruction | None) -> frozenset[str]:
    """Every symbol one mana ability can put in its controller's pool, read off
    its add-mana steps with the wrappers opened — "{T}: Add {U} or {B}. This
    land deals 1 damage to you." is a ``sequence`` whose first step is a
    ``pips_choice`` — or empty for an instruction that adds no mana.

    Asked by the AI's tap executor to choose **which** of a land's mana
    abilities to run for the colour its plan counted on: a painland's first
    ability makes {C}, and the tap seam runs the first one unless told
    otherwise, so a plan that counted a Karplusan Forest as {G} tapped it for
    {C} and the spell it was paying for was refused.
    """
    if instruction is None:
        return frozenset()
    found: set[str] = set()
    for step in _effect_steps(instruction):
        payload = step.payload or {}
        if payload.get("any_color"):
            found.update("WUBRG")
        for key in ("pips", "pips_choice"):
            found.update(symbol for symbol, _count in payload.get(key) or ())
        for alternative in payload.get("pips_alternatives") or ():
            found.update(symbol for symbol, _count in alternative)
        found.update(
            symbol for symbol in payload.get("combination") or ()
            if isinstance(symbol, str)
        )
    return frozenset(found)


def mana_ability_amount(card: CardDefinition) -> int | None:
    """Mana one activation of *card*'s mana ability adds, or None if it has none.

    This is what "Black Lotus is worth casting" was standing in for: a permanent
    whose value *is* mana is worth nothing when mana costs are not enforced, and
    worth playing early when there is something to spend it on. True of every
    Mox, Sol Ring and Basalt Monolith in the pool, none of which were named.
    """
    for ability in compile_card_oracle(card).activated_abilities:
        instruction = ability.instruction
        if instruction is None or not is_mana_ability(instruction):
            continue
        # Three payload shapes: a pip list ("Add {C}{C}"), the any-colour count
        # ("Add three mana of any one color"), and the legacy fused handler's
        # bare ``amount``. The any-colour count may be "x" or a spec, which is
        # not a number this valuation can have — 1 is the honest floor there,
        # since the ability does produce mana.
        pips = instruction.payload.get("pips")
        if pips:
            return sum(int(count) for _symbol, count in pips)
        # "Add {B} or {R}": one of the alternatives, so the ability is worth
        # the best single option, never the sum of them.
        pips_choice = instruction.payload.get("pips_choice")
        if pips_choice:
            return max(int(count) for _symbol, count in pips_choice)
        # "Add {U} or {C}{U}" (Adarkar Unicorn): a choice between written-out
        # *runs*, so each alternative is a pip list of its own and the ability
        # is worth the largest run — the same "best single option" reading as
        # ``pips_choice``, and the choice the headless default actually takes
        # (handlers/mana._pick_mana_alternative: no mana burn, so more of the
        # same is never worse).
        pips_alternatives = instruction.payload.get("pips_alternatives")
        if pips_alternatives:
            return max(
                sum(int(count) for _symbol, count in alternative)
                for alternative in pips_alternatives
            )
        any_count = instruction.payload.get("any_color_count")
        if isinstance(any_count, int):
            return any_count
        amount = instruction.payload.get("amount")
        if isinstance(amount, int):
            return amount
        return 1
    return None


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


def divided_shape(program) -> DividedShape | None:
    """*program*'s divided step described, or None when it divides nothing."""
    from .divided_damage import CHOSEN, divided_instruction
    from .grammar.lowering.categories import INSTRUCTION_CATEGORIES
    from .pt import pt_counter_deltas

    instruction = divided_instruction(program.instructions)
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
    return DividedShape(
        side=side,
        thresholded=category == "damage",
        whole_board=(
            described.get("division") != CHOSEN
            and bool((described.get("filter") or {}).get("controller"))
        ),
    )


def _several_target_instruction(program):
    """The one instruction in *program* whose description names several targets."""

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

    return walk(program.instructions)


# Which board a slot wants when the slot's own payload carries no number to read
# the answer off. Keyed by *instruction kind* — a claim about what the effect
# does, derived from the compiled program exactly as the P/T-delta branch below
# is, and never about which card printed it. A kind absent here keeps "no
# preference", which is the answer every card before this one gave.
#
# Tapping is the first entry: it is a denial, so every slot of a several-target
# tap wants an opponent's permanent, and the caster's own board is the one place
# the effect is never worth casting. Without this, `_choose_several_targets`'s
# single-seat fallback taps the caster's own creatures — round 65's bug arriving
# through a different effect family.
_SLOT_DISPOSITION: dict[str, str] = {
    "tap_target_permanent": "opponent",
    # Destruction is the same claim one family over: a destroy is a denial, so
    # every slot of a several-target destroy wants an opponent's permanent. A
    # preference, exactly as the tap above is -- `_choose_several_targets` still
    # falls back to a single seat's worth when no opponent holds a legal target,
    # which for a destroy is the caster's own board and a weak play rather than
    # an illegal one. What the entry buys is that the AI stops preferring its
    # own permanents when the opponent has some.
    #
    # No shipped card reaches this: every several-target destroy in the pool is
    # either a sweep (no targets) or announces its count off an X (which this
    # chooser declines), so the entry arrived with Primitive Justice, whose
    # count comes off a CR 601.2b payment and whose bare "target artifact" names
    # no side at all.
    "destroy_target_permanent": "opponent",
    # And exile, which is the same denial one zone over. This entry is
    # about two *shipped* cards rather than about the round that found
    # it: Dust to Dust and Ashes to Ashes are the pool's only
    # several-target exiles, both name a bare noun with no side in it,
    # and both had the AI removing its own permanents. A card that
    # exiles the caster's own ("exile two target creatures **you
    # control**") never reaches this: the controller branch above
    # answers first, off the printed noun phrase.
    "exile_target_permanent": "opponent",
}


def several_target_slot_sides(program) -> tuple[str | None, ...]:
    """Which board each slot of a several-target spell should be picked from.

    Derived, never named: the compiled program says which slots are restricted by
    controller and, where they are not, whether the slot's own effect is a
    benefit or a penalty. Rookie Mistake's two slots are both a bare "target
    creature", so only the sign of the P/T delta distinguishes "the one I pump"
    from "the one I shrink" — and a chooser reading neither puts both on the
    caster's own board.

    Returns one entry per slot: "you", "opponent", or None for no preference. A
    uniform answer means the existing single-seat policy is exactly right, and
    `_choose_several_targets` keeps it.
    """
    instruction = _several_target_instruction(program)
    if instruction is None:
        return ()
    targets = instruction.payload.get("targets") or {}
    count = targets.get("count")
    if isinstance(count, dict):
        # An announcement sized by a CR 601.2b optional additional cost. This
        # policy takes no such offer -- "may" is declined by default and nothing
        # values one -- so the number of slots is the base count alone, which is
        # the same reading `_choose_several_targets` makes when it asks how many
        # targets to name.
        count = cost_target_count(count, {}) or 0
    if not isinstance(count, int) or count < 1:
        return ()
    filters = targets.get("filters") or [targets.get("filter") or {}] * count
    slots = tuple(instruction.payload.get("slots") or ())
    sides: list[str | None] = []
    for index in range(count):
        described = filters[index] if index < len(filters) else {}
        controller = described.get("controller")
        if controller == "you":
            sides.append("you")
            continue
        if controller in ("not_you", "opponent"):
            sides.append("opponent")
            continue
        disposition = _SLOT_DISPOSITION.get(instruction.kind)
        if disposition is not None:
            sides.append(disposition)
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
        sides.append(None)
    return tuple(sides)


#: Instruction kinds that read back a pile something else exiled. A search whose
#: finds one of these reaches is a search whose cards **come back**, and taking
#: the maximum costs the searcher nothing; a search with none of them behind it
#: spends its own library for good.
#:
#: Derived from the compiled program rather than named per card, which is the
#: rule for anything that decides which cards a policy reaches. Erring towards
#: "it comes back" is deliberate: that is the older behaviour, so a kind left
#: off this list changes nothing until somebody notices, where a kind wrongly on
#: it would make a card cheaper than it is.
_EXILED_PILE_READERS = frozenset({
    # "You may cast them this turn." (Chandra, Heart of Fire's -9.)
    "grant_cast_permission",
    "cast_from_exiled_with",
    # "At the beginning of your next upkeep, put those cards into your hand."
    # (Foresight.) The delayed ability is where the return lives, and its own
    # effect is a payload this scan does not open — which is the erring above:
    # a delayed trigger that did something else would read as a return.
    "create_delayed_trigger",
    # The linked-pile readers (Mangara's Tome, Knowledge Vault, Cold Storage).
    "put_exiled_pile_top_into_hand",
    "put_exiled_with_source",
    "put_exiled_pile_on_library",
})


def exiled_search_pile_comes_back(card: CardDefinition) -> bool:
    """Whether anything on *card* reads back what its exile-search found.

    The question a headless seat needs before answering "search your library
    for any number of X, exile them": Foresight, Mangara's Tome and Chandra's
    -9 all hand the cards back and taking the maximum costs nothing, while Mana
    Severance exiles them for good and taking the maximum empties the seat's
    own library of lands. The stated default was written for the first three
    and reasoned from them ("the cards come back castable"), which is a fact
    about those cards rather than about the sentence.

    Program-derived and name-free: a card printing a new "search and exile"
    with a return behind it is covered the day it lands, and one without is
    answered correctly without anybody adding it to a list.

    ``face_down_pile`` counts on its own — that is CR 610.3's recorded pile, and
    a pile the card bothered to record is one it means to read.
    """
    program = compile_card_oracle(card)
    for instruction in _walk_program(program):
        if instruction.kind in _EXILED_PILE_READERS:
            return True
        if instruction.kind == "search_and_exile_matching" and instruction.payload.get(
            "face_down_pile"
        ):
            return True
    return False


# --- What an activated ability does to the permanent it is printed on --------
#
# CR 602.1b lets an ability's own text say who may activate it ("Any player may
# activate this ability"), and CR 113.8 makes whoever activated it the
# ability's controller — so its "you", its targets and its costs are the
# activator's. The one thing that does **not** move with the activator is the
# permanent the ability is printed on. That is why these abilities exist at
# all: "This creature loses flying until end of turn" (Ribbon Snake), "Destroy
# this enchantment" (Volrath's Dungeon), "Return this creature to its owner's
# hand" (Quicksilver Wall) are drawbacks printed for an *opponent* to pay for.
#
# So one reading answers two questions in opposite directions. Asked by the
# source's controller, an effect that removes or hampers its own source is a
# loss, and the activation chooser was paying for it every main phase — 2.5 for
# "anything else", so it bounced its own Quicksilver Wall for {4}, stripped its
# own Ribbon Snake's flying and paid 5 life to destroy its own Volrath's
# Dungeon. Asked by any other seat, the same effect is the reason to pay.

#: Kinds whose effect takes the ability's own source off the battlefield and
#: does not bring it back: destroyed, exiled, sacrificed, returned to a hand,
#: put into a library.
SOURCE_REMOVAL_KINDS = frozenset({
    "destroy_self",
    "exile_self",
    "sacrifice_self",
    "return_source_card_to_owners_hand",
    "put_source_card_on_library_top",
    "shuffle_source_card_into_library",
})

#: The removals the source's owner gets back: a card returned to a hand or put
#: on top of a library is a turn of tempo, not a permanent gone.
SOURCE_RETURN_KINDS = frozenset({
    "return_source_card_to_owners_hand",
    "put_source_card_on_library_top",
})

#: Kinds whose effect takes something away from the source and gives it
#: nothing: a keyword or a printed line lost (Ribbon Snake, Glittering Lion),
#: regeneration denied (Clergy of the Holy Nimbus), the source tapped (Deep
#: Spawn's shroud costs it its untap), the source phased out for the turn.
SOURCE_HAMPER_KINDS = frozenset({
    "remove_self_keyword",
    "remove_self_ability_text",
    "deny_regeneration_to_self",
    "tap_self",
    "phase_out_self",
})

#: Payload flags that point a step's effect at the ability's own source
#: ("prevent the next 1 damage … to this creature", Mercenaries' "the next time
#: this creature would deal damage").
_SOURCE_PAYLOAD_FLAGS = ("to_self", "to_source", "from_source")


def _effect_steps(instruction: OracleInstruction) -> tuple[OracleInstruction, ...]:
    """*instruction*'s leaf steps, wrappers (``sequence``, ``if_then``,
    ``may``) opened and themselves left out."""
    found: list[OracleInstruction] = []

    def walk(item) -> None:
        payload = getattr(item, "payload", None) or {}
        nested = [
            payload.get(key)
            for key in ("steps", "then", "else", "action", "otherwise", "effect")
            if isinstance(payload.get(key), (list, tuple))
        ]
        if not nested:
            found.append(item)
            return
        for group in nested:
            for child in group:
                if hasattr(child, "kind"):
                    walk(child)

    walk(instruction)
    return tuple(found)


def _acts_on_source(step: OracleInstruction) -> bool:
    """Whether one step's effect lands on the ability's own source.

    The kind vocabulary is verb_object, and ``self`` / ``source`` is its word
    for the permanent the ability is printed on (``pump_self``,
    ``return_source_card_to_owners_hand``, ``grant_self_keyword_until_eot``) —
    80 kinds in the table, all spelled that way. A kind that reached the
    source some other way would read as not touching it, so every caller below
    *declines* on a yes and uses this only to rule a step in, never out.
    """
    kind = str(getattr(step, "kind", "") or "")
    if kind in SOURCE_REMOVAL_KINDS or kind in SOURCE_HAMPER_KINDS:
        return True
    if {"self", "source"} & set(kind.split("_")):
        return True
    payload = getattr(step, "payload", None) or {}
    return any(payload.get(flag) for flag in _SOURCE_PAYLOAD_FLAGS)


def harms_its_own_source(instruction: OracleInstruction | None) -> bool:
    """Whether any step of an ability's effect removes or hampers the permanent
    the ability is printed on.

    Asked by the activation chooser for its own seat's permanents, where the
    answer is a reason **not** to activate: a self-bounce, a self-destruction
    or a lost keyword is a rescue or a drawback, and a main-phase chooser with
    no response window has nothing to rescue. 59 abilities on 58 cards print
    one across both manifest roles, 10 of them on cards any player may
    activate; of the 45 non-Aura permanents whose *first* ability is one — the
    ability that chooser reads — it proposed 30 before this existed.
    """
    if instruction is None:
        return False
    return any(
        step.kind in SOURCE_REMOVAL_KINDS or step.kind in SOURCE_HAMPER_KINDS
        for step in _effect_steps(instruction)
    )


def source_toughness_change(instruction: OracleInstruction | None) -> int | None:
    """The toughness change an effect makes to its own source, when that is the
    whole of the effect — every step a ``pump_self`` with printed numbers — or
    None. "This creature gets -1/-1 until end of turn" (Flailing Soldier) is
    -1; a trade that shrinks the source *and* gives it flying is None, because
    the flying is half of what the ability is for.
    """
    if instruction is None:
        return None
    total = 0
    for step in _effect_steps(instruction):
        if step.kind != "pump_self":
            return None
        toughness = (step.payload or {}).get("toughness")
        if not isinstance(toughness, int) or isinstance(toughness, bool):
            return None
        total += toughness
    return total


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


def source_becomes_an_aura(instruction: OracleInstruction | None) -> bool:
    """Whether *instruction* turns the permanent it is printed on into an Aura
    and attaches it ("This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature." — the
    Licids).

    Such an ability's target is the Aura's host, so which board it belongs on
    is what the *Aura* does to its host — the card's other text, which no step
    of this program reads — and not the attach step, which reads "you" because
    an Equipment's attach does.
    """
    if instruction is None:
        return False
    return any(step.kind == "become_aura_with_enchant" for step in _effect_steps(instruction))


def foreign_activation_use(ability) -> str | None:
    """What activating *ability* is for, to a seat that does **not** control
    the permanent it is printed on — or None when it is for nothing that seat
    can count on.

    * ``"removes_source"`` — the whole effect takes the source off its
      controller's battlefield for good (Volrath's Dungeon, Aether Storm).
      Removal of an opponent's permanent, bought with the activation cost.
    * ``"returns_source"`` — the same, to a hand or the top of a library
      (Quicksilver Wall), so the owner plays it again: tempo, worth it when it
      costs the owner more to recast than it cost to bounce, or when it clears
      a blocker the activator is about to attack past.
    * ``"shrinks_source"`` — the whole effect lowers the source's toughness
      (the Flailing creatures' "-1/-1"). Worth it only when that is lethal,
      which the policy asks of the live permanent.
    * ``"aimed"`` — the effect never touches its source and names a target,
      which the activator chooses (CR 113.8): Task Mage Assembly's 1 damage,
      Scandalmonger's discard, Endbringer's Revel's graveyard return. It is
      the same ability whichever seat holds the permanent, so it is worth what
      it would be worth on the activator's own board.

    Everything else is declined, and the reasons are the policy:

    * a *hamper* that is not lethal on its own — "loses flying" (Ribbon
      Snake), "loses 'Prevent all damage …'" (Glittering Lion), "can't be
      regenerated" (Clergy of the Holy Nimbus) — is worth paying for only with
      something lined up to cash it in this turn, and this chooser has one
      activation in a main phase and no combat plan to read;
    * a *gift* to the source ("+1/+1", Flailing Soldier's other ability)
      helps the permanent's controller;
    * an untargeted effect on everyone (Squallmonger's 1 damage to each
      player) or one about the source's own damage (Mercenaries) is not the
      activator's to aim, and its value is the board's, not the seat's.
    """
    instruction = getattr(ability, "instruction", None)
    if instruction is None:
        return None
    steps = _effect_steps(instruction)
    if not steps:
        return None
    if all(step.kind in SOURCE_REMOVAL_KINDS for step in steps):
        if any(step.kind in SOURCE_RETURN_KINDS for step in steps):
            return "returns_source"
        return "removes_source"
    change = source_toughness_change(instruction)
    if change is not None and change < 0:
        return "shrinks_source"
    if any(_acts_on_source(step) for step in steps):
        return None
    from .targeting import derive_activation_spec

    spec = derive_activation_spec(ability) or {}
    if spec.get("kind") in (None, "none", "hand_card") or spec.get(
        "sacrifice_cost"
    ) or spec.get("discard_cost"):
        return None
    return "aimed"


# --- "Choose a card name": where the name will be looked for ----------------

#: The steps that read a chosen name against cards of the **chooser's own**,
#: and the zone each one looks in. A player built their own deck, so what
#: their library still holds is theirs to work out (CR 401.2 hides which card
#: is where), and they see their own hand outright — so for these the name
#: worth choosing is one of their own cards.
_OWN_ZONE_NAME_READERS = {
    "reveal_top_sorting_by_chosen_name": "library",
    "reveal_random_card_from_hand": "hand",
}


def chosen_name_own_zone(card: CardDefinition, instruction) -> str | None:
    """The chooser's own zone *instruction*'s "choose a card name" is then
    looked for in — ``"library"``, ``"hand"`` — or None when it is looked for
    somewhere else (Foreshadow mills an opponent) or nowhere this can see.

    Read off the steps **behind** the choice in the sequence that holds it,
    found by identity in the card's compiled program: the choice is a step
    that produces a value, and what the value is for is the next sentence.
    Wood Sage and Desperate Research reveal the top of *your* library; Cursed
    Scroll reveals a card from *your* hand.
    """
    program = compile_card_oracle(card)
    roots = [
        *program.instructions,
        *(ability.instruction for ability in program.activated_abilities),
        *(ability.instruction for ability in program.triggered_abilities),
    ]

    def search(step) -> str | None:
        if step is None:
            return None
        payload = getattr(step, "payload", None) or {}
        for key in ("steps", "then", "else", "action", "otherwise"):
            nested = payload.get(key)
            if not isinstance(nested, (list, tuple)):
                continue
            for position, inner in enumerate(nested):
                if inner is instruction:
                    for later in nested[position + 1:]:
                        zone = _OWN_ZONE_NAME_READERS.get(later.kind)
                        if zone is None:
                            continue
                        if (later.payload or {}).get("revealer", "you") != "you":
                            return None
                        return zone
                    return None
                found = search(inner)
                if found is not None:
                    return found
        return None

    for root in roots:
        found = search(root)
        if found is not None:
            return found
    return None


# --- CR 601.2b: the optional additional costs a cast may take ---------------
#
# What an offer *buys*, as the four things an optional cost in this pool can
# buy. Derived from the compiled program and from the two readers a
# resolution itself asks (`cast_costs.buyback_paid`, `cast_costs.kicked`) —
# never from the keyword's printed name, so a card worded as the rules text of
# either is read the same way.

#: The spell's own card comes back to its owner's hand as it resolves
#: (CR 702.27a). The payment buys *the next cast*, not this one.
OFFER_RETURNS_SPELL = "returns_spell"
#: The spell is kicked (CR 702.33d): some part of the program asks `was_kicked`.
OFFER_KICKS = "kicked"
#: Each payment adds to what the spell does — the program reads this offer's
#: *count* ("for each additional {1}{R} you paid", "an additional 3 life for
#: each additional {1}{G} you paid").
OFFER_ADDS = "more_effect"
#: The spell does something *different* when paid, and which is better depends
#: on the board (Undergrowth's paid Fog spares red creatures — the caster's and
#: everybody else's).
OFFER_ALTERS = "other_effect"


@dataclass(frozen=True)
class CastOffer:
    """One optional additional cost a cast of a card may take (CR 601.2b).

    ``key`` is what the announcement is keyed by (``optional_cost_payments``),
    read off the same table the cast path charges from. Exactly one of ``mana``
    (a run of symbols folded into the spell's mana payment) and ``price`` (a
    sacrifice, a discard, life — "Buyback—Sacrifice a land") is set.
    """

    key: str
    buys: str
    repeatable: bool = False
    mana: object | None = None
    price: object | None = None
    #: The zone this offer belongs to a cast from, or None for every zone
    #: (`AdditionalCost.from_zone`).
    from_zone: str | None = None


def _payload_names(value, key: str) -> bool:
    """Whether *key* appears anywhere under *value* — as a dict key (``per_cost:
    {key: 1}``) or as a value (``repeat_from_cost: key``)."""
    if isinstance(value, str):
        return value == key
    if isinstance(value, dict):
        return any(
            name == key or _payload_names(inner, key) for name, inner in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_payload_names(inner, key) for inner in value)
    payload = getattr(value, "payload", None)
    return isinstance(payload, dict) and _payload_names(payload, key)


def _what_an_offer_buys(card: CardDefinition, key: str) -> str:
    from .cast_costs import buyback_paid, kicked

    record = {"additional_costs_paid": {key: 1}}
    if buyback_paid(card, record):
        return OFFER_RETURNS_SPELL
    if kicked(card, record):
        return OFFER_KICKS
    program = compile_card_oracle(card)
    if _payload_names(tuple(program.instructions), key):
        return OFFER_ADDS
    return OFFER_ALTERS


def cast_offers(card: CardDefinition) -> tuple[CastOffer, ...]:
    """Every optional additional cost casting *card* offers, with what it buys.

    Empty for all but a few dozen cards. Read from ``cast_costs.
    additional_costs`` — the table ``queue_from_hand`` announces, gates and
    charges from — so an offer the policy takes is one the cast path knows by
    the same key.
    """
    from .cast_costs import additional_costs

    offers: list[CastOffer] = []
    for cost in additional_costs(card):
        for offer in cost.optional_mana:
            offers.append(CastOffer(
                key=offer.symbols,
                buys=_what_an_offer_buys(card, offer.symbols),
                repeatable=offer.repeatable,
                mana=offer,
                from_zone=cost.from_zone,
            ))
        if cost.optional_key is not None:
            offers.append(CastOffer(
                key=cost.optional_key,
                buys=_what_an_offer_buys(card, cost.optional_key),
                price=cost,
                from_zone=cost.from_zone,
            ))
    return tuple(offers)


def _walk_program(program):
    """Every instruction on a program, wrappers opened."""
    def walk(instructions):
        for instruction in instructions:
            yield instruction
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = (instruction.payload or {}).get(key)
                if isinstance(nested, (list, tuple)):
                    yield from walk(nested)

    yield from walk(program.instructions)
    for ability in program.activated_abilities:
        if ability.instruction is not None:
            yield from walk([ability.instruction])
    for trigger in program.triggered_abilities:
        if trigger.instruction is not None:
            yield from walk([trigger.instruction])


__all__ = [
    "MANA_ABILITY_KINDS",
    "SELF_PAYMENT_KINDS",
    "SOURCE_HAMPER_KINDS",
    "SOURCE_REMOVAL_KINDS",
    "SOURCE_RETURN_KINDS",
    "SPELL_TYPES",
    "CounterProfile",
    "DividedShape",
    "TollLoss",
    "ability_target_side",
    "cards_drawn_by_controller",
    "cards_drawn_by_target",
    "caster_sacrifice_steps",
    "castable_commanders",
    "chosen_creature_type_side",
    "counters_a_spell",
    "denies_its_target",
    "destroyed_permanent_filter",
    "divided_shape",
    "is_mana_ability",
    "mana_ability_amount",
    "exiled_search_pile_comes_back",
    "foreign_activation_use",
    "hand_entry_steps",
    "harms_its_own_source",
    "hand_pick_entry_consumer",
    "instruction_target_side",
    "offered_action_is_a_payment",
    "returns_creature_to_hand",
    "several_target_slot_sides",
    "source_toughness_change",
    "spell_denies_its_own_target",
    "spell_hand_pick_entry_filters",
    "spell_target_side",
    "toll_branch_loss",
]
