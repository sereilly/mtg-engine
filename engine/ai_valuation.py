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

**One measure does live here**, at the bottom of the module: what a seat's
position is worth (``seat_standing``, ``permanent_worth``) and what one cast
does to it, found by carrying the cast out on a scratch copy of the game
(``rehearse``). It is here and not beside the weights because two readers have
to agree on it — the cast policy, which predicts with it, and the mode census,
which measures with it — and because it is the same move as everything above:
the compiled program read for what it does, this time by running it.

The same split is why ``offered_action_is_a_payment`` is here rather than in
``engine/mixins/stack/choices.py`` beside the default that reads it. "This
offer's price comes out of the taker's own permanents, hand, library or life"
is a claim about what a card *does*, true of every card printing the sentence;
"and therefore a seat nobody asked refuses it" is the stated policy, and that
stays with the other stated policies in ``_default_optional_pay``.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
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


#: The mode of a modal spell the policy is weighing right now (CR 601.2b,
#: CR 700.2a), as ``(card, mode index)`` -- or None, which is every moment no
#: modal spell is being weighed.
#:
#: **Why it is here and why it is a context variable.** "What does this spell
#: do?" is asked of a *card* by two dozen functions in this module and by every
#: cast chooser in ``ai_policy``, and for a "Choose one —" spell the answer is
#: a different one per mode: Crosis's Charm is a bounce, a kill or a Shatter.
#: Every one of those readers answered for **mode 0** -- the compiled program's
#: ``instructions`` *are* mode 0's -- so an AI seat cast every modal spell as
#: its first bullet, 34 of 88 modes, and held the card whenever that one bullet
#: had nothing to point at. A parameter would have had to be threaded through
#: every reader and remembered by every later one; this is one fact about one
#: candidate, set around the single call that builds it
#: (:func:`considering_mode`) and read at the two places a spell's steps come
#: from: :func:`_spell_instructions` here and ``ai_policy._announced_mode``
#: there. A reader that goes through either cannot forget the mode.
#:
#: Held **with the card**, so a question about some *other* card asked while
#: this one is being weighed (the spell on top of the stack, the rest of the
#: hand) is answered for that card as printed and never for "its mode 2".
_MODE_CONSIDERED: ContextVar["tuple[CardDefinition, int] | None"] = ContextVar(
    "ai_mode_considered", default=None
)


@contextmanager
def considering_mode(card: CardDefinition, mode_index: "int | None"):
    """Weigh *card* as cast in *mode_index* for the length of the block.

    None is "no mode named" -- a spell that is not modal, or one whose mode an
    opponent chooses (CR 700.2e) -- and reads exactly what every reader read
    before modes were weighed at all.
    """
    token = _MODE_CONSIDERED.set(None if mode_index is None else (card, mode_index))
    try:
        yield
    finally:
        _MODE_CONSIDERED.reset(token)


def mode_considered(card: CardDefinition) -> "int | None":
    """The mode *card* is being weighed in (:func:`considering_mode`), or None."""
    held = _MODE_CONSIDERED.get()
    if held is None:
        return None
    considered, mode_index = held
    return mode_index if considered is card or considered == card else None


def caster_chooses_a_mode(card: CardDefinition) -> bool:
    """Whether casting *card* means choosing one of its modes (CR 601.2b):
    an instant or sorcery printing a "Choose one —" head its **caster**
    answers. Not a spell whose mode an opponent picks (CR 700.2e: Fatal Lore,
    Misfortune, Library of Lat-Nam) -- that cast names no mode, by rule.

    The test ``web/state_view`` makes for the castable highlight, and the one
    ``Game.announceable_modes`` makes before listing anything.
    """
    if card.primary_type not in SPELL_TYPES:
        return False
    program = compile_card_oracle(card)
    return bool(program.modes) and program.mode_chooser is None


def spell_text(card: CardDefinition) -> str:
    """The lower-cased words *card* resolves as: the bullet being weighed for
    a modal spell (:func:`considering_mode`), its whole text otherwise.

    For the one weight in ``ai_policy`` that still probes a text — the
    tutor's reading of printed damage, `_extract_damage`. The cast scorer's
    probes ("draw", "gain … life", "target opponent"), which this was written
    for, are gone: a cast is scored by what a rehearsal of it measures.
    """
    mode_index = mode_considered(card)
    if mode_index is not None:
        modes = compile_card_oracle(card).modes
        if 0 <= mode_index < len(modes):
            return (modes[mode_index].label or "").lower()
    return (card.oracle_text or "").lower()


def _spell_instructions(card: CardDefinition) -> tuple[OracleInstruction, ...]:
    """The instructions resolving *card* **as a spell** carries out.

    Empty for a permanent card; see ``SPELL_TYPES``. For a modal spell being
    weighed in one of its modes (:func:`considering_mode`), that mode's own --
    through ``targeting.announced_mode_instructions``, the reader the cast
    gates and the resolution share, so what the policy values is the steps
    the announcement will run.
    """
    from .targeting import announced_mode_instructions

    if card.primary_type not in SPELL_TYPES:
        return ()
    return tuple(
        announced_mode_instructions(compile_card_oracle(card), mode_considered(card))
    )


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
    from .targeting import SEAT_ROLE_KINDS, payload_own_role

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
    (``targeting._first_described_slot``, through the mode the cast names),
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

    The tie-break under ``ai_policy._choose_target_for_spell``, which weighs
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


#: Kinds whose effect on the **player** they target is a denial and whose
#: category cannot say so: a discard is filed under ``zones`` beside every
#: other card movement, where "damage" and "tapping" already answer for theirs.
_SEAT_DENIAL_KINDS = frozenset({"discard_target_cards"})

#: The spec kinds whose candidates include a player's face
#: (``resolution._CHOOSABLE_TRIGGER_PLAYER_KINDS``, the picker's own set).
_SEAT_SPEC_KINDS = frozenset({"player", "player_or_planeswalker", "any"})



def ability_seat_side(instruction: OracleInstruction | None) -> str | None:
    """Whose **seat** an effect that names a player — or "any target" — should
    name: "you", "opponent", or None when the compiled program does not say.

    :func:`ability_target_side` is the question for an object; this is the one
    for a face. The policy answered it with a list of three instruction kinds
    (``_choose_target_for_instruction``), two of which no handler has —
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
    *optional_cost_payments* will fire (``targeting.entry_trigger_instructions``,
    CR 702.33g) -- so the answer is about the target the cast actually names.
    Only the denial is answered: a gift aimed by this rule could contradict the
    printed phrase ("target **opponent** draws two cards", Lord of
    Tresserhorn), and every seat-targeting entry trigger in the pool that is
    not a denial already lands where its card prints it.
    """
    from .targeting import _first_described_slot, entry_trigger_instructions

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


def entry_self_return_gate(card: CardDefinition) -> dict | None:
    """The choice a permanent's "When this enters, **return a <noun> you
    control to its owner's hand**" makes its controller make -- the
    ``choose_permanents`` payload -- or None when *card* prints no such
    trigger.

    Planeshift's gating ("return a red or green creature you control", ten
    creatures) and Shrieking Drake's unnarrowed original. The return is not
    optional and the permanent that asks is itself a legal answer, which is the
    whole of why a policy has to read it: cast onto a board with nothing else
    the noun admits, the creature returns **itself**, and the seat has spent
    its turn's mana to put a card back in its hand -- then does it again next
    turn, because nothing about the card in hand has changed. Measured over
    six simulated games with all ten pinned: 112 of 127 gating triggers
    returned the creature that had just been cast.

    Derived from the compiled shape rather than the keyword's name (it has
    none): an entry trigger that is exactly a forced pick from the controller's
    own board followed by the return of what was picked. "Sacrifice it
    **unless** you return …" (the Karoo lands, the Lairs) is a toll with a
    different top-level kind and is not this.
    """
    if card.primary_type in SPELL_TYPES:
        return None
    for ability in compile_card_oracle(card).triggered_abilities:
        instruction = ability.instruction
        if (
            not ability.supported
            or instruction is None
            or ability.condition.kind != "enters_battlefield"
            or instruction.kind != "sequence"
        ):
            continue
        steps = tuple((instruction.payload or {}).get("steps") or ())
        if len(steps) != 2:
            continue
        chosen, returned = (step.payload or {} for step in steps)
        if (
            steps[0].kind == "choose_permanents"
            and steps[1].kind == "return_recorded_permanents_to_hand"
            and chosen.get("chooser") == "you"
            and chosen.get("controlled_by") == "chooser"
            and int(chosen.get("at_least", 0) or 0) >= 1
            and returned.get("permanents_from") == chosen.get("result_key")
        ):
            return dict(chosen)
    return None


def entry_triggers_bought(
    card: CardDefinition, optional_cost_payments: dict | None
) -> tuple[OracleInstruction, ...]:
    """The entry-trigger instructions a permanent spell fires **because of**
    the optional costs in *optional_cost_payments* -- the triggers a cast that
    takes them fires and a cast that declines every offer does not.

    "When this creature enters, if it was kicked with its {2}{R} kicker,
    destroy target land." (Nightscape Battlemage.) What the {2}{R} *buys* is
    that one trigger, and whether it is worth the mana is a question about that
    trigger's own target -- which the cast's picker cannot answer for a second
    trigger, since it describes only the first.

    Derived as a difference of two readings of the compiled program
    (``targeting.entry_trigger_instructions``) rather than by naming the gate,
    so any condition the kicked view comes to understand is covered here too.
    Empty for an instant or sorcery, whose bought half is a step of its own
    resolution and is read off the cast spec.
    """
    from .targeting import entry_trigger_instructions

    if card.primary_type in SPELL_TYPES or not optional_cost_payments:
        return ()
    program = compile_card_oracle(card)
    taken = entry_trigger_instructions(
        card, program, optional_cost_payments=optional_cost_payments
    )
    declined = entry_trigger_instructions(card, program, optional_cost_payments={})
    return tuple(
        instruction for instruction in taken
        if not any(instruction is kept for kept in declined)
    )


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
    * cards of the type taken out of the controller's **own library** into
      their hand (Brass Herald's reveal) — a type the deck does not hold makes
      that sentence a four-card mill to the bottom;
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
        elif instruction.kind == "reveal_top_sorting_by_filter" and (
            # The caster's own pile only: "each player reveals …" hands every
            # seat its cards of the type, which says nothing about whose to
            # name.
            payload.get("whose") is None
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


@dataclass(frozen=True)
class OfferTrade:
    """A "You may A. If you do, B." offer whose two halves are a **price** the
    taker pays and a **purchase** it gets, each named in the terms a policy can
    weigh — see :func:`offer_trade`."""

    #: "card" — a card out of the taker's own hand; "draw" — the taker's own
    #: draw step.
    price: str
    #: "untap_source" — the offer's own source untaps; "land_card" — a land
    #: card searched out of the taker's library.
    purchase: str


#: Leading steps that take a card out of the taker's own hand.
_HAND_CARD_PRICE_KINDS = frozenset({"exile_chosen_card_from_hand"})


def offer_trade(steps) -> OfferTrade | None:
    """The trade an offer's accept branch makes, or None when it is not one of
    the two shapes this can price on both sides.

    *steps* is the branch as ``_offer_to_seat`` builds it: the offered action
    first, then what follows from taking it.

    The optional-pay default was two constants and each was wrong on one
    card. An offer whose **leading** step spends something is refused
    ("make no trades"), so Forsaken City's "you may exile a card from your
    hand. If you do, untap this land" was declined at every upkeep of every
    game — 122 offers and no untap in six simulated games — and the land was a
    mana once. An offer whose leading step is a gift is taken, so Elfhame
    Sanctuary's "you may search your library for a basic land card … If you
    do, **you skip your draw step this turn**" was taken at every upkeep: 56
    offers, 56 draw steps skipped, a seat that never drew again. The price is
    in the *consequence*, where a reader of the leading step does not look.

    Both are one question — what does it cost and what does it buy — and the
    answer depends on the board (a land is worth a draw to a seat short of
    them; a mana is worth a card to a seat about to discard one), so this names
    the two halves and `ai_policy.offer_trade_is_worth_taking` weighs them.
    """
    steps = [step for step in steps if getattr(step, "kind", None)]
    if len(steps) < 2:
        return None
    leading, rest = steps[0], steps[1:]
    if leading.kind in _HAND_CARD_PRICE_KINDS and all(
        step.kind == "untap_self" for step in rest
    ):
        return OfferTrade(price="card", purchase="untap_source")
    if (
        leading.kind == "search_library"
        and (leading.payload or {}).get("card_type") == "land"
        and all(
            step.kind == "skip_next_step"
            and (step.payload or {}).get("step") == "draw"
            and (step.payload or {}).get("seat") == "you"
            for step in rest
        )
    ):
        return OfferTrade(price="draw", purchase="land_card")
    return None


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


#: Board sweeps that read "the chosen color" off the resolution's scratchpad,
#: and where each keeps the noun phrase it sweeps: ``destroy_all_matching``
#: carries it as its own payload keys, ``return_all_matching`` under
#: ``filter``. Held to live handler kinds by ``tests/ai/test_ai_valuation.py``.
_COLOR_SWEEP_KINDS = {"destroy_all_matching": None, "return_all_matching": "filter"}
#: Payload keys of a sweep that are not part of the noun phrase.
_SWEEP_RIDERS = frozenset({"color_filter_from", "bypass_regeneration", "targets"})


def chosen_color_sweeps(card: CardDefinition) -> tuple[dict, ...]:
    """The noun phrase of every board sweep on *card* that is narrowed by "the
    color of your choice" — "Destroy all **enchantments** of the color of your
    choice" (Root Greevil), "Return all **permanents** of the color of your
    choice to their owners' hands" (Wash Out), "…all **creatures** of that
    color" (Dromar, the Banisher) — as the filter the sweep's own matcher
    reads, less the colour.

    What the choice is *for*, read off the step that spends it. The default
    colour was the one the opponents held most of among every permanent, so
    Root Greevil named the colour of an opposing army and destroyed no
    enchantment.
    """
    from .oracle_types import CHOSEN_COLOR_THIS_WAY

    sweeps: list[dict] = []
    for step in _walk_program(compile_card_oracle(card)):
        payload = step.payload or {}
        if (
            step.kind not in _COLOR_SWEEP_KINDS
            or payload.get("color_filter_from") != CHOSEN_COLOR_THIS_WAY
        ):
            continue
        nested = _COLOR_SWEEP_KINDS[step.kind]
        described = dict((payload.get(nested) if nested else {
            key: value for key, value in payload.items() if key not in _SWEEP_RIDERS
        }) or {})
        # Once each: a permanent's activated ability is on the program twice,
        # as the ability and mirrored into ``instructions``.
        if described not in sweeps:
            sweeps.append(described)
    return tuple(sweeps)


def color_most_worth_sweeping(game, seat: int, card: CardDefinition) -> str | None:
    """The colour *seat* should name for *card*'s "…of the color of your
    choice" sweep (:func:`chosen_color_sweeps`): the one whose sweep takes
    most from the other seats and least from its own, by
    :func:`permanent_worth` — or None when the card prints no such sweep, or
    no colour's sweep is worth more than nothing.

    Through ``subject_matches``, the matcher the sweep itself asks, with the
    colour read through CR 613's layer 5.
    """
    from .subject_filters import subject_matches

    sweeps = chosen_color_sweeps(card)
    if not sweeps:
        return None
    best, best_worth = None, 0.0
    for color in ("W", "U", "B", "R", "G"):
        worth = 0.0
        for controller, permanent in game.permanents_with_controller():
            if any(
                subject_matches(
                    game, permanent, {**described, "color_filter": color},
                    observer=seat,
                )
                for described in sweeps
            ):
                worth += permanent_worth(permanent) * (-1.0 if controller == seat else 1.0)
        if worth > best_worth + 1e-9:
            best, best_worth = color, worth
    return best


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


def _offer_target_permanent(game, context):
    """The one permanent the offer's resolution announced as its target, or
    None where it named none, named several, or the permanent has left."""
    named = getattr(context, "target_permanent_id", None)
    # One id, or the one-slot list an announcement made by id arrives as.
    if isinstance(named, (list, tuple)) and len(named) == 1:
        named = named[0]
    if not isinstance(named, int):
        return None
    return game.permanent_by_id(named)


def toll_branch_loss(
    game, player_index: int, steps, self_recipients=(), source_permanent=None,
    context=None,
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

    *context* is the resolution the offer sits inside, for the two penalties
    aimed at the **permanent the spell targeted** rather than at a seat or at
    the source: "deals 3 damage to target creature unless …" (Blazing Salvo)
    and "destroy target nonbasic land unless …" (Lava Blister). The loss is
    that permanent when the offered seat controls it and the step would take
    it — a creature the damage does not kill is no loss at all, and neither is
    somebody else's permanent. Without a context those steps stay unpriceable,
    which is what they were.
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
            if not isinstance(amount, int):
                return None
            if payload.get("recipient") in recipients:
                life += amount
                continue
            if payload.get("recipient") is not None or not payload.get("targets"):
                return None
            # Damage aimed at the announced permanent. Lethal to a creature
            # the seat controls is that creature gone; anything less is
            # nothing this valuation counts.
            victim = _offer_target_permanent(game, context)
            if victim is None or not victim.is_creature:
                return None
            if (
                game.controller_index_of(victim) == player_index
                and amount >= victim.effective_toughness - victim.damage_marked
            ):
                permanents.append(victim)
        elif kind == "destroy_target_permanent":
            victim = _offer_target_permanent(game, context)
            if victim is None:
                return None
            if game.controller_index_of(victim) == player_index:
                permanents.append(victim)
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


@dataclass(frozen=True)
class PermittedCast:
    """One cast a seat may make because an **effect** allows it (CR 601.3):
    a card outside its hand it may cast or play, or a card in its hand it may
    cast without paying its mana cost.

    What the policy needs to build a candidate that the cast path will accept,
    and none of it is derivable from the card alone:

    * **where the card is** — ``zone``, ``owner_seat`` and ``index``. The pile
      is the grantee's own on every grant but the cross-seat one (Grinning
      Totem leaves the card in the *searched* player's exile pile);
    * **what it is cast as** — ``spell``, the half for a split card (CR 709.3)
      and ``held`` itself otherwise;
    * **what the cast is charged** — ``permission``: its required alternative
      cost (CR 118.9b; flashback, CR 702.34a), its waiver, or neither;
    * **the announcement that selects that permission** — ``alternative_cost``,
      CR 601.2b's choice, in the cast path's own spelling. A card may be
      covered twice (a flashback card under Yawgmoth's Will) and those are two
      casts at two prices.
    """

    zone: str
    owner_seat: int
    index: int
    held: CardDefinition
    spell: CardDefinition
    permission: object
    alternative_cost: bool = False

    @property
    def cost(self):
        """The alternative cost the permission requires, or None."""
        return getattr(self.permission, "cost", None)

    @property
    def waives_mana_cost(self) -> bool:
        """Whether the cast is made "without paying its mana cost".

        A grant's ``free`` flag — and **every** permission over the hand,
        which is the cast path's own reading (``cast_permissions.permission_for``
        answers the hand zone for cost waivers alone, and ``_cast_onto_stack``
        takes whatever it answers as one)."""
        return self.cost is None and (
            bool(getattr(self.permission, "free", False)) or self.zone == "hand"
        )

    @property
    def expires(self) -> bool:
        """Whether the permission has a stated duration (CR 611.2a) — "until
        end of turn", "until your next turn" — as opposed to lasting for as
        long as the card stays where it is (flashback, a static ability of a
        permanent)."""
        return getattr(self.permission, "duration", None) is not None


def permitted_casts(game, player_index: int) -> "tuple[PermittedCast, ...]":
    """Every cast *player_index* may make from **outside its hand** right now
    (CR 601.3), one entry per spell and per price.

    The list is the engine's: ``cast_permissions.playable_from_zones``, the
    one the browser's zone badges are built from, so an AI seat is offered
    exactly the cards a human seat is. The command zone is left to
    :func:`castable_commanders` — CR 903.8 is a rule rather than a permission,
    and it carries a tax where these carry a price.

    **Which permission a cast will be made under is the cast path's answer,
    mirrored rather than re-decided.** ``_cast_onto_stack`` finds a card *by
    name*, in the caster's own pile first and then the others', and takes the
    first permission that covers it — the first that *requires an alternative
    cost* when the caster announced one (CR 601.2b, ``permission_for``'s
    ``costed``). So for each spell name in each zone:

    * the **bare** cast is the first covered copy in that scan order, under the
      first permission that answers for it — and a later copy is not offered
      again, because the cast could not reach it;
    * where that permission asks no alternative cost and another one does (a
      flashback card under Yawgmoth's Will, an opened graveyard), the cast
      **announcing an alternative cost** is offered beside it.

    Lands are included (``mode="play"``): the land-drop chooser reads them.
    """
    from .cast_permissions import permission_for, playable_from_zones
    from .faces import castable_faces

    found: list[PermittedCast] = []
    bare_seen: set[tuple[str, str]] = set()
    costed_seen: set[tuple[str, str]] = set()
    for entry in playable_from_zones(game, player_index):
        zone = entry["zone"]
        if zone == "command":
            continue
        owner = entry["owner_seat"]
        index = entry["index"]
        pile = getattr(game.players[owner], zone)
        if not 0 <= index < len(pile):
            continue
        held = pile[index]
        as_land = held.primary_type == "land"
        for spell in castable_faces(held):
            key = (zone, spell.name)
            first = permission_for(
                game, player_index, held, zone, as_land=as_land, spell=spell,
            )
            if first is None or first.zone_seat != owner:
                continue
            if key not in bare_seen:
                bare_seen.add(key)
                found.append(PermittedCast(
                    zone=zone, owner_seat=owner, index=index, held=held,
                    spell=spell, permission=first,
                    alternative_cost=first.cost is not None,
                ))
                if first.cost is not None:
                    costed_seen.add(key)
            if key in costed_seen:
                continue
            costed = permission_for(
                game, player_index, held, zone, as_land=as_land, spell=spell,
                costed=True,
            )
            if costed is None or costed.zone_seat != owner:
                continue
            costed_seen.add(key)
            found.append(PermittedCast(
                zone=zone, owner_seat=owner, index=index, held=held,
                spell=spell, permission=costed, alternative_cost=True,
            ))
    return tuple(found)


def hand_waiver(
    game, player_index: int, held: CardDefinition, spell: CardDefinition,
    hand_index: int,
) -> "PermittedCast | None":
    """The waiver a cast of *spell* out of *player_index*'s hand will be made
    under ("Any player may cast creature spells with mana value 3 or less
    without paying their mana costs", Aluren; "you may cast spells from your
    hand without paying their mana costs", Chandra, Flame's Catalyst), or None.

    The cast path's own default, mirrored: a cast that announces nothing takes
    a hand waiver whenever one covers the card, **except for an {X} spell** —
    a waived {X} is locked to 0 (CR 107.3b), so that one defaults to paying.
    Never a land, which is played rather than cast.
    """
    from .cast_permissions import permission_for

    if spell.primary_type == "land" or "{X}" in (spell.mana_cost or "").upper():
        return None
    permission = permission_for(game, player_index, held, "hand", spell=spell)
    if permission is None:
        return None
    return PermittedCast(
        zone="hand", owner_seat=player_index, index=hand_index, held=held,
        spell=spell, permission=permission,
    )


#: The permission the cast being weighed would be made under (CR 601.3), as a
#: :class:`PermittedCast` -- or None, which is every ordinary cast from hand.
#:
#: The zone's twin of :data:`_MODE_CONSIDERED`, a context variable for its
#: reason: *where a spell is cast from* and *what that cast is charged* are
#: asked by a dozen choosers underneath the candidate builder -- the spec (a
#: spell leaving a graveyard is not a card in it, CR 601.2a), the prohibitions
#: (a row may bind one zone), the price, the X -- and each took a card. Held
#: with the spell, by identity, so a question about another card asked while
#: this one is weighed is answered for a cast from hand.
_CAST_WEIGHED: ContextVar["PermittedCast | None"] = ContextVar(
    "ai_cast_weighed", default=None
)


@contextmanager
def casting_under(permitted: "PermittedCast | None"):
    """Weigh a cast as made under *permitted* for the length of the block.
    None is an ordinary cast from hand, which reads what every reader read
    before a seat could cast from anywhere else."""
    token = _CAST_WEIGHED.set(permitted)
    try:
        yield
    finally:
        _CAST_WEIGHED.reset(token)


def cast_weighed(card: CardDefinition) -> "PermittedCast | None":
    """The permission *card* is being weighed under (:func:`casting_under`),
    or None."""
    held = _CAST_WEIGHED.get()
    if held is None or held.spell is not card:
        return None
    return held


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


@dataclass(frozen=True)
class ManaYield:
    """What one activation of a mana ability puts in its controller's pool,
    where the ability's own payload says so — the terms a payment plan counts
    in. See :func:`planned_mana_yield`."""

    #: Every symbol the activation may be asked for, the one it makes unasked
    #: first. Empty when the board or the source decides (``board_narrowed``,
    #: ``from_chosen_color``) and the caller has to ask the game.
    symbols: tuple[str, ...] = ()
    #: How many mana of the asked symbol one activation makes.
    amount: int = 1
    #: A fixed run of two or more *different* symbols ("{U}{R}"), as
    #: ``((symbol, count), …)`` — made whole whichever symbol is asked for.
    run: tuple[tuple[str, int], ...] = ()
    #: "…of any color **that a land an opponent controls could produce**":
    #: which colours is the battlefield's answer
    #: (``mana_could_produce.ability_colors_on_offer``).
    board_narrowed: bool = False
    #: "Add one mana of **the chosen color**": the colour the source recorded
    #: as it entered.
    from_chosen_color: bool = False


#: The payload keys of an add-mana step this module can turn into a
#: :class:`ManaYield`. An **allow-list**, because the direction that matters is
#: the one where a key is added later: a step carrying anything else — a
#: restriction on what the mana may pay for (``spend_only``, CR 106.6), an
#: amount the board decides (``per_each``), a record another activation wrote
#: (``from_noted``), a split the seat chooses (``combination``) — is mana a
#: plan cannot count, and counting it anyway is a cast refused for
#: insufficient mana.
_PLANNABLE_MANA_KEYS = frozenset({
    "pips", "pips_choice", "any_color", "any_color_count", "any_color_from",
    "could_produce_lands", "from_chosen_color", "oracle_text",
})


def planned_mana_yield(instruction: OracleInstruction | None) -> ManaYield | None:
    """What a payment plan may count one activation of a mana ability as, or
    None when the payload alone cannot say.

    The non-land half of the question `board_payment.land_tap_yields` answers
    for a land (`ai_policy._land_tap_options`), asked of
    the compiled ability rather than of the tap seam's summary, because a
    non-land permanent has no summary path: "{T}: Add {C}{C}" (Sol Ring),
    "{T}: Add {B} or {R}" (the Cameos), "{T}: Add one mana of any color" (Birds
    of Paradise) and the board-narrowed "…that a land an opponent controls
    could produce" (Fellwar Stone) are the four shapes it reads.

    One rider is admitted beside the add-mana step: a fixed amount of damage to
    the ability's own controller ("This creature deals 1 damage to you", Elves
    of Deep Shadow) — the painlands' rider, which the land planner has always
    counted through. Any other second step ("Reveal any number of artifact
    cards in your hand", Metalworker) is a decision or an amount this cannot
    state.
    """
    if instruction is None:
        return None
    steps = _effect_steps(instruction)
    adders = [step for step in steps if step.kind == "add_mana_from_text"]
    if len(adders) != 1:
        return None
    for step in steps:
        if step is adders[0]:
            continue
        payload = step.payload or {}
        amount = payload.get("amount")
        if not (
            step.kind == "deal_damage"
            and payload.get("recipient") == "caster"
            and isinstance(amount, int) and not isinstance(amount, bool)
        ):
            return None
    payload = adders[0].payload or {}
    if not payload or set(payload) - _PLANNABLE_MANA_KEYS:
        return None
    if payload.get("from_chosen_color"):
        return ManaYield(from_chosen_color=True)
    pips = tuple((str(symbol), int(count)) for symbol, count in payload.get("pips") or ())
    if pips:
        if len({symbol for symbol, _count in pips}) >= 2:
            return ManaYield(symbols=tuple(symbol for symbol, _count in pips), run=pips)
        return ManaYield(
            symbols=(pips[0][0],), amount=max(1, sum(count for _symbol, count in pips))
        )
    choice = tuple((str(symbol), int(count)) for symbol, count in payload.get("pips_choice") or ())
    if choice:
        return ManaYield(
            symbols=tuple(symbol for symbol, _count in choice),
            # One number for whichever alternative is asked for; where the
            # printed counts differ, the smallest is what every answer makes.
            amount=max(1, min(count for _symbol, count in choice)),
        )
    if payload.get("any_color"):
        count = payload.get("any_color_count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return None
        if payload.get("any_color_from"):
            return ManaYield(amount=count, board_narrowed=True)
        return ManaYield(symbols=("W", "U", "B", "R", "G"), amount=count)
    return None


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
                            payload_own_role, role_dependency, role_is_seat,
                            spec_roles)

    program = compile_card_oracle(card)
    # ...and CR 601.2b's other answer, the mode being weighed
    # (:func:`considering_mode`): Hull Breach's third bullet is a roles
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
    from .targeting import payload_own_role, role_dependency, role_is_seat

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


def pick_is_tested_for_a_shared_color(card: CardDefinition, result_key: str) -> bool:
    """Whether a later step of *card* asks if its target **shares a color with**
    the permanent a ``choose_permanent`` recorded under *result_key*.

    "Choose a permanent you control. Prevent all combat damage target creature
    would deal this turn **if it shares a color with that permanent**." (Guard
    Dogs.) The pick is the whole of whether the ability does anything, and a
    seat nobody asks took the first candidate in board order — a land, which
    is colourless and shares a colour with nothing (CR 105.2c), so the ability
    resolved and prevented no damage in every simulated game.

    Read off the compiled condition (``target_shares_color_with_chosen`` and
    the record it names), so any card printing the relation is answered and no
    card is named.
    """

    def walk(instructions) -> bool:
        for instruction in instructions:
            payload = getattr(instruction, "payload", None) or {}
            condition = payload.get("condition")
            if (
                isinstance(condition, dict)
                and condition.get("kind") == "target_shares_color_with_chosen"
                and condition.get("permanent_from") == result_key
            ):
                return True
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)) and walk(nested):
                    return True
        return False

    program = compile_card_oracle(card)
    return (
        walk(program.instructions)
        or walk(a.instruction for a in program.activated_abilities if a.instruction is not None)
        or walk(t.instruction for t in program.triggered_abilities if t.instruction is not None)
    )


#: The pile readers that hand back **one card** per use.
_ONE_CARD_PILE_READERS = frozenset({
    "put_exiled_pile_top_into_hand",
    "put_exiled_with_source",
})


def exiled_search_pile_comes_back_one_at_a_time(card: CardDefinition) -> bool:
    """Whether the only thing on *card* that reads its exile-search's pile back
    is an **activated ability with a cost** that returns one card per use.

    "{4}, {T}: Choose a card at random that was exiled with Skyship
    Weatherlight. Put that card into its owner's hand." The pile comes back,
    so :func:`exiled_search_pile_comes_back` says yes and the headless default
    took everything "any number" admits — every artifact and creature in the
    seat's library, to be bought back one a turn at four mana each, at random.
    The cards a game will not last long enough to return are spent exactly as
    Mana Severance's are.

    Derived from where the reader sits in the compiled program, never from the
    card: a pile returned whole (Foresight's delayed draw, Chandra's "you may
    cast them this turn") has a reader outside any activated ability and
    answers False, and a search with a printed ceiling (Mangara's Tome's five)
    is bounded by its own card whatever this says.
    """
    program = compile_card_oracle(card)
    priced: list[OracleInstruction] = []
    for ability in program.activated_abilities:
        if ability.instruction is None:
            continue
        cost = ability.cost
        free = not (
            getattr(cost, "requires_tap", False)
            or any((getattr(cost, "mana", None) or {}).values())
        )
        for step in (ability.instruction, *_effect_steps(ability.instruction)):
            if step.kind in _ONE_CARD_PILE_READERS:
                if free or int((step.payload or {}).get("count", 1) or 1) != 1:
                    return False
                priced.append(step)
    if not priced:
        return False

    def reads_elsewhere(instructions) -> bool:
        for instruction in instructions:
            if instruction.kind in _EXILED_PILE_READERS:
                return True
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = (instruction.payload or {}).get(key)
                if isinstance(nested, (list, tuple)) and reads_elsewhere(nested):
                    return True
        return False

    # A program mirrors each activated ability into ``instructions``, so the
    # spell-side list is read with those mirrors taken out.
    mirrored = {id(step) for step in priced}
    own = [
        instruction for instruction in program.instructions
        if id(instruction) not in mirrored
        and not any(instruction is ability.instruction for ability in program.activated_abilities)
        and instruction.kind not in _ONE_CARD_PILE_READERS
    ]
    if reads_elsewhere(own):
        return False
    return not reads_elsewhere(
        trigger.instruction for trigger in program.triggered_abilities
        if trigger.instruction is not None
    )


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


#: How many flips a seat nobody asks takes when a chosen number is the length
#: of a run that stops at the first loss (Squee's Revenge: two cards for each
#: flip, if every flip is won). A weight. The expected draw is ``2n / 2**n`` —
#: one card at one flip *and* at two, less from three on — and two is the
#: larger prize at the same expectation.
FLIP_RUN_LENGTH = 2


def chosen_number_bounds_flip_run(card: CardDefinition, instruction) -> bool:
    """Whether the number *instruction* chooses is the length of a run of coin
    flips — "Choose a number. Flip a coin **that many times** or until you lose
    a flip…" (Squee's Revenge).

    Read off the steps **behind** the choice in the sequence that holds it, for
    ``chosen_name_own_zone``'s reason directly below: the choice is a step that
    produces a value, and what the value is for is the next sentence. The
    default every other chosen number takes counts mana values on the board
    (``_most_telling_mana_value``, Void's question), which for this card names
    zero flips on an empty board and a dozen on a full one.
    """
    program = compile_card_oracle(card)

    def follows(step) -> bool:
        payload = getattr(step, "payload", None) or {}
        for key in ("steps", "then", "else", "action", "otherwise"):
            nested = payload.get(key)
            if not isinstance(nested, (list, tuple)):
                continue
            for position, inner in enumerate(nested):
                if inner is instruction:
                    return any(
                        later.kind == "flip_coins_until_loss"
                        for later in nested[position + 1:]
                    )
                if follows(inner):
                    return True
        return False

    return any(
        follows(root)
        for root in (
            *program.instructions,
            *(ability.instruction for ability in program.activated_abilities),
            *(ability.instruction for ability in program.triggered_abilities),
        )
        if root is not None
    )


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


#: The steps that read a chosen name against a card off the top of **the
#: targeted player's** library: "Choose a card name, then target player mills
#: a card. If a card with the chosen name was milled this way…" (Predict;
#: Foreshadow says "target opponent"). Whose library that is, is settled by
#: the announcement, so this is half an answer and the game supplies the rest.
_TARGET_LIBRARY_NAME_READERS = frozenset({"mill_target_player"})


def chosen_name_is_read_off_the_targets_library(card: CardDefinition, instruction) -> bool:
    """Whether *instruction*'s "choose a card name" is looked for among cards
    milled from **the target player's** library — so that, when that player is
    the chooser, the name worth choosing is one of the chooser's own cards.

    :func:`chosen_name_own_zone`'s question one seat over, and read the same
    way: the steps behind the choice in the sequence that holds it, found by
    identity. A player built their own deck, so what their own library still
    holds is theirs to work out (CR 401.2 hides only *which card is where*) —
    and an **opponent's** library is a hidden zone outright (CR 400.2), which
    is why the answer for a milled opponent stays what it was: that seat's
    graveyard, the public evidence of what its deck holds.
    """
    program = compile_card_oracle(card)

    def search(step) -> bool:
        if step is None:
            return False
        payload = getattr(step, "payload", None) or {}
        for key in ("steps", "then", "else", "action", "otherwise"):
            nested = payload.get(key)
            if not isinstance(nested, (list, tuple)):
                continue
            for position, inner in enumerate(nested):
                if inner is instruction:
                    return any(
                        later.kind in _TARGET_LIBRARY_NAME_READERS
                        for later in nested[position + 1:]
                    )
                if search(inner):
                    return True
        return False

    return any(
        search(root)
        for root in (
            *program.instructions,
            *(ability.instruction for ability in program.activated_abilities),
            *(ability.instruction for ability in program.triggered_abilities),
        )
    )


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


# --- The measure: what a seat's position is worth -----------------------------
#
# **"Larger" is said here, once.** Which of two castable bullets takes the
# larger thing off the opposing board or adds the larger thing to its caster's
# own, which of two legal targets is the better one, whether a cast does
# anything at all — each is a comparison of two positions, and a comparison
# needs one unit. The unit is the life-equivalent the toll prices already use
# (``ai_policy._toll_loss_price``): a point of life near twenty is worth one.
# (Those prices are an older list in the same unit and put a card at two; the
# two lists answer different questions and nothing here reconciles them.)
#
# Two readers ask it, and that is why it lives in this module rather than
# beside the weights in ``ai_policy``: the policy, which *rehearses* a cast
# (:func:`rehearse`) and prices what it changed; and the mode census
# (``tests/ai/test_ai_mode_chooser_census.py``), which makes the cast for real
# on a board of its own and prices what that changed. Two prices from two
# functions would be a census asking the scorer whether the scorer is right.
#
# What it reads is the board as the layers compute it — never a card's text.

#: A card in hand: about four life. The old cast weight said the same thing in
#: another place ("worth exactly 4.0 per net card", `_score_cast`).
CARD_WORTH = 4.0
#: What any permanent is worth just by being one, before its stats and its
#: cost are added: the card it is. **Never less than that card in a hand**,
#: or returning a permanent to its owner's hand would measure as a gift to
#: its owner — which is what a floor of two and a half made of every bounce
#: aimed at something that had cost nothing. A Mox is worth a card.
PERMANENT_WORTH = CARD_WORTH
#: The same floor for a token, which is not a card: nothing was spent from a
#: hand to make it and nothing comes back if it leaves (CR 111.7). So a 2/2
#: destroyed outweighs a 2/2 token made, by the card that was under it.
TOKEN_WORTH = 1.5
#: A land on top of that: the card and the land drop it took.
LAND_WORTH = 1.5
#: How many lands a seat is counted as needing, and what one beyond them is
#: worth: half a life. The same six ``ai_policy.BUYBACK_PERMANENTS_KEPT``
#: keeps before a seat pays a buyback in lands — a seventh land is the one a
#: seat gives up for a card, and the one a Stone Rain is wasted on.
LANDS_WORTH_KEEPING = 6
SPARE_LAND_WORTH = 0.5
#: A creature's body, per point.
POWER_WORTH = 1.4
TOUGHNESS_WORTH = 1.1
#: An evasion ability, per point of the power it carries past a blocker.
EVASION_WORTH = 0.5
#: Any other combat keyword, flat.
COMBAT_KEYWORD_WORTH = 1.0
#: How much of a creature's body is missing while it is tapped: all of it —
#: it neither attacks nor blocks until it untaps, which is what a body is
#: for. A reading of the board **now** only; the card under it is still
#: there, and so is whatever it does without tapping.
TAPPED_SHARE = 1.0
#: How much a change that is gone by the end of the turn counts for against
#: one that is still there: a +3/+3 until end of turn is a quarter of a
#: +3/+3 counter, a creature phased out a quarter of a creature destroyed.
TEMPORARY_SHARE = 0.25
#: A seat that has lost, or will at its next draw.
LOST = 1000.0

_EVASION_KEYWORDS = frozenset({
    "flying", "fear", "shadow", "horsemanship", "menace", "landwalk",
    "swampwalk", "forestwalk", "islandwalk", "mountainwalk", "plainswalk",
    "desertwalk",
})
_COMBAT_KEYWORDS = frozenset({
    "first strike", "double strike", "trample", "vigilance", "lifelink",
    "deathtouch", "indestructible", "reach", "protection", "hexproof",
    "shroud", "banding", "flanking", "rampage",
})

#: Life is worth more the less of it there is: ``(up to this total, each
#: point)``, and the last rate for everything above the last tier. Three
#: damage is three at twenty life and six at five; five life gained at twenty
#: is two and a half, which is why it loses to a dead creature.
_LIFE_TIERS = ((5, 2.0), (10, 1.5), (20, 1.0))
_LIFE_ABOVE = 0.5


def life_worth(life: int) -> float:
    """What a life total is worth: concave, and ``-LOST`` at zero or less."""
    if life <= 0:
        return -LOST
    worth, floor = 0.0, 0
    for ceiling, rate in _LIFE_TIERS:
        if life <= floor:
            break
        worth += (min(life, ceiling) - floor) * rate
        floor = ceiling
    if life > floor:
        worth += (life - floor) * _LIFE_ABOVE
    return worth


def permanent_worth(permanent, *, now: bool = True) -> float:
    """What *permanent* is worth to whoever controls it.

    The floor every permanent has, what it cost, and for a creature its body
    and its keywords — all read through CR 613's accessors, so a creature
    under a +3/+3 is worth the 5/5 it currently is and one that lost flying
    is worth what is left.

    *now* is the board as it stands this instant: a tapped creature counts
    for less (``TAPPED_SHARE``). ``now=False`` is the reading for what will
    still be true once the turn's temporary effects are over, where a tap is
    not a difference.
    """
    from .layer_bridge import computed_abilities

    # What it cost, read as CR 613 reads it: a Clone is worth the mana value
    # of what it copies (CR 707.2).
    worth = (
        TOKEN_WORTH if permanent.metadata.get("is_token") else PERMANENT_WORTH
    ) + float(permanent.effective_card.cmc or 0)
    if permanent.has_type("land"):
        worth += LAND_WORTH
    if not permanent.is_creature:
        return worth
    power = max(0, permanent.effective_power)
    body = power * POWER_WORTH + max(0, permanent.effective_toughness) * TOUGHNESS_WORTH
    abilities = computed_abilities(permanent)
    body += power * EVASION_WORTH * len(_EVASION_KEYWORDS & abilities)
    body += COMBAT_KEYWORD_WORTH * len(_COMBAT_KEYWORDS & abilities)
    if now and permanent.tapped and not permanent.attacking:
        # An attacker is tapped because it is fighting: its body is in use,
        # not missing.
        body *= 1.0 - TAPPED_SHARE
    return worth + body


def seat_standing(game, seat: int, *, now: bool = True) -> float:
    """What *seat*'s position is worth: its life, the cards in its hand and
    the permanents it controls (:func:`permanent_worth`).

    A seat that has lost is ``-LOST``, and so — less by half, so that a real
    loss still ranks below it — is one with no library left to draw from
    (CR 704.5b on its next draw). ``now=False`` also counts what has phased
    out: CR 702.26 brings it back.
    """
    player = game.players[seat]
    if player.lost or player.life <= 0:
        return -LOST
    worth = life_worth(player.life) + CARD_WORTH * len(player.hand)
    if not player.library:
        worth -= LOST / 2
    lands = 0
    for permanent in game.controlled_by(seat):
        worth += permanent_worth(permanent, now=now)
        lands += bool(permanent.has_type("land"))
    if not now:
        for permanent in player.phased_out:
            worth += permanent_worth(permanent, now=False)
    # Each land beyond the ones a seat needs is worth `SPARE_LAND_WORTH`, not
    # a card and a land drop.
    worth -= max(0, lands - LANDS_WORTH_KEEPING) * (
        PERMANENT_WORTH + LAND_WORTH - SPARE_LAND_WORTH
    )
    return worth


def standing_swing(before: tuple, after: tuple, seat: int) -> float:
    """How far *seat* moved against the rest of the table between two
    readings (one standing per seat): its own change less every other
    seat's."""
    return sum(
        (after[index] - before[index]) * (1.0 if index == seat else -1.0)
        for index in range(len(before))
    )


def swing_worth(now: float, lasting: float) -> float:
    """One number for a change measured twice — as the board stood right
    after it (*now*) and with the turn's temporary effects over (*lasting*).

    What lasts counts in full; what is there now and gone by then counts for
    ``TEMPORARY_SHARE`` of itself. **This is what "larger" means**, for the
    policy choosing between two casts and for the census judging the choice.
    """
    return lasting + TEMPORARY_SHARE * (now - lasting)


def standings(game, *, now: bool = True) -> tuple:
    """:func:`seat_standing` for every seat, in seat order."""
    return tuple(
        seat_standing(game, seat, now=now) for seat in range(len(game.players))
    )


# --- Rehearsal: what a cast would do, asked of the engine ---------------------

#: What every cast changes whatever it does — the zones the spell itself moves
#: through (read separately), the mana that paid for it, the turn's count of
#: spells. Left in, a resolution that did nothing still reads as a change.
#: Mana the spell *makes* is read where it can be told from mana the spell
#: cost: across its resolution (:func:`_rehearse`).
_PLAYER_BOOKKEEPING = frozenset({
    "hand", "graveyard", "library", "exile", "mana_pool", "battlefield",
    "spells_cast_this_turn",
})
#: The same for the game's own fields: the table itself (read separately),
#: the log, the stack and who has priority, and the per-turn ledgers a cast
#: writes whether or not it does anything.
_GAME_BOOKKEEPING = frozenset({
    "players", "log", "stack", "priority_player_index", "priority_pass_count",
    "prompt_driver", "interactive_seats", "enforce_mana_costs",
    "resolving_seats", "resolving_stack_item", "pending_choices",
    "current_phase", "current_turn_phase", "current_step",
    # Read apart, by the names of the cards each permission covers
    # (`_permission_entries`), so that the one a cast spends can be told
    # apart from what the cast did.
    "cast_permissions",
    # "Did this seat cast a spell during its last turn" (Arboria, CR 506.3),
    # folded out of `spells_cast_this_turn` as the next turn begins — which
    # is where the end-of-turn reading is taken (`untap_for_the_next_turn`),
    # so every cast would read as having changed it.
    "last_own_turn_activity",
})

#: Rehearsals that **raised**, by what was being rehearsed and what the
#: engine raised: ``"Lightning Bolt: KeyError: 'amount' (damage.py:212 in
#: deal_damage)"`` -> how many times.
#:
#: A rehearsal that raises answers None, and a policy reads None as "this
#: could not be weighed" — which is right for a game somebody is playing (a
#: crash in a copy is not a crash in the game) and is also a **silence**:
#: before a cast was rehearsed, the same exception was raised by the real
#: cast and stopped a simulated run on the spot, which is how a
#: crash-on-cast card used to be found. So each one is written down here,
#: process-wide, and the simulator reads what its own run added
#: (``SimulationReport.rehearsals_raised``): a raised rehearsal is a crash
#: the game was spared, not a quiet "no". Nothing in the engine reads this
#: to decide anything.
REHEARSALS_RAISED: Counter = Counter()


def _note_raised(what: "str | None", raised: BaseException) -> None:
    """Write one raised rehearsal into ``REHEARSALS_RAISED``: what was being
    carried out, the exception, and the innermost frame it came from."""
    import os
    import traceback

    frames = traceback.extract_tb(raised.__traceback__)
    where = ""
    if frames:
        last = frames[-1]
        where = f" ({os.path.basename(last.filename)}:{last.lineno} in {last.name})"
    REHEARSALS_RAISED[
        f"{what or 'a rehearsal'}: {type(raised).__name__}: {raised}{where}"
    ] += 1


_REHEARSING: ContextVar[bool] = ContextVar("ai_rehearsing", default=False)
_DELIBERATION: ContextVar["dict | None"] = ContextVar("ai_deliberation", default=None)

#: How many passes the rehearsal gives a stack to empty and a combat to end.
_REHEARSAL_PASSES = 8
#: Under this, a swing is no swing: the standings are sums of floats.
_NO_SWING = 1e-9


@dataclass(frozen=True)
class Rehearsal:
    """What one cast did, carried out on a scratch copy of the game.

    ``accepted``
        the engine took the cast (False: it was refused, and ``refusal`` says
        why — a cast this policy must not propose);
    ``changed``
        the resolution changed anything at all on the table or in the turn's
        records, beyond the spell's own trip from hand to graveyard;
    ``now`` / ``lasting``
        the caster's :func:`standing_swing` against the same table with
        nothing cast — as the board stood right after the resolution, and
        with the turn's temporary effects over;
    ``swing``
        :func:`swing_worth` of the two;
    ``fleeting``
        everything it changed is **gone by the end of the turn**: no standing
        differs then and nothing on the table does (a pump that has worn off,
        a shield nothing hit, a Fog) — where a change no standing prices and
        that is still there (a permanent's colour, the order of a library) is
        not;
    ``made_mana``
        some of what it changed is mana in a pool, which is fleeting by
        nature and is not nothing: it is what the next cast is paid with;
    ``through_combat``
        the turn was run out **with its combat played** (:func:`rehearse`'s
        *through_combat*), and ``now`` is ``lasting``: what the cast was
        worth once the fight it was made before had been fought;
    ``combat_ahead``
        once the cast had resolved, the caster's turn still had a combat
        phase to come (:func:`_combat_ahead`) — the one a precombat cast is
        made before, or one the cast itself added;
    ``opened_a_cast``
        once it had resolved, the caster could cast something from outside
        its hand it could not before (CR 601.3: "you may play cards from your
        graveyard this turn") — fleeting like mana, and like mana not
        nothing: it is spent on a cast this rehearsal is not a rehearsal of.
    """

    accepted: bool
    changed: bool = False
    now: float = 0.0
    lasting: float = 0.0
    refusal: str = ""
    fleeting: bool = False
    made_mana: bool = False
    through_combat: bool = False
    combat_ahead: bool = False
    opened_a_cast: bool = False

    @property
    def swing(self) -> float:
        return swing_worth(self.now, self.lasting)


def rehearsing() -> bool:
    """Whether the code asking is running **inside** a rehearsal — on a
    scratch copy whose every prompt is being answered by default. A chooser
    reached from there (a default that asks the policy) must not rehearse
    again."""
    return _REHEARSING.get()


@contextmanager
def deliberating():
    """One decision's worth of rehearsals.

    Every candidate a chooser weighs is measured against the same table with
    nothing cast, and that reading costs a copy of the game — so it is taken
    once per decision and kept for the length of this block. Outside one,
    each rehearsal takes its own.
    """
    if _DELIBERATION.get() is not None:
        yield
        return
    token = _DELIBERATION.set({})
    try:
        yield
    finally:
        _DELIBERATION.reset(token)


def _every_card(game):
    """Every card object a zone of *game* holds. A `CardDefinition` is
    immutable and shared — a deck is one object per printing, repeated — so a
    scratch copy shares them too rather than copying a library card by card."""
    for player in game.players:
        for zone in (
            player.hand, player.library, player.graveyard, player.exile,
            getattr(player, "command_zone", ()) or (),
        ):
            yield from zone
        for permanent in player.phased_out:
            yield permanent.card
    for permanent in game.all_permanents():
        yield permanent.card
    for item in game.stack:
        card = getattr(item, "card", None)
        if card is not None:
            yield card


def mid_resolution(game) -> bool:
    """Whether *game* is part-way through carrying something out — an object
    resolving, a loop with steps still owed (``resume_stack``), a resolution
    held for an answer, a CR 616.1 choice outstanding.

    Such a table is not copied as it stands. What it owes is recorded as
    continuations — closures over the game they were made on — and a copy of
    one would run its remaining steps on the **original**. A policy asked in
    that moment gets no rehearsal and falls back to its stated default,
    unless what it is asking can be answered on a copy cut loose from the
    resolution (:func:`_detach`).
    """
    return bool(
        game.resume_stack
        or game.resolving_stack_item is not None
        or game.resolving_seats
        or held_for_an_answer(game)
    )


def held_for_an_answer(game) -> bool:
    """The part of :func:`mid_resolution` no copy can be cut loose from: a
    resolution **waiting on somebody** — a CR 616.1 choice outstanding, an
    object held on the stack for an interactive seat, a queued prompt that
    carries its own continuation. Each of those is a closure the copy would
    still be holding."""
    return bool(
        game.pending_replacement_choices
        or any(
            getattr(item, "finish_resolution", None) is not None
            or getattr(item, "resolution_held", False)
            for item in game.stack
        )
        or any(
            callable(value)
            for choice in game.pending_choices
            for value in choice.data.values()
        )
    )


def _detach(game, *, owing_nothing: bool = False) -> None:
    """Cut a scratch copy loose from the resolution its original is in the
    middle of: nothing is resolving on the copy and no loop has steps owed.

    For a question whose answer is its own stack object — the mode of a
    triggered ability, chosen as the ability is put on the stack (CR 603.3c)
    while the spell that caused it is still resolving. The copy never finishes
    that spell; what it carries out is the ability, in each mode, and the
    modes are compared with each other.

    *owing_nothing* goes further, for a question about **a card in the
    abstract** — what is this one worth to hold, asked by a search part-way
    through its own resolution: every prompt the copy was owed and every
    object held on its stack for an answer is dropped unanswered. Those are
    the continuations :func:`held_for_an_answer` refuses a copy over, and
    with nothing left to invoke them they are never run.
    """
    game.resolving_stack_item = None
    game.resolving_seats = []
    game.resume_stack = []
    if owing_nothing:
        game.pending_choices = []
        game.pending_replacement_choices = []
        game.stack = [
            item for item in game.stack
            if getattr(item, "finish_resolution", None) is None
            and not getattr(item, "resolution_held", False)
        ]


def scratch_copy(game):
    """A copy of *game* a cast can be carried out on with nothing reaching
    the original: every seat non-interactive, so each prompt takes its kind's
    default, as it does for a seat the engine plays.

    **When** a prompt is answered is the game's own arrangement and is left
    as it is: a table with a `prompt_driver` (the simulator's) answers each
    one as it is armed, a table without (a web game) once the stack has
    emptied — and a spell whose steps ask two things in a row comes out
    differently under the two. A copy that answered on a schedule of its own
    rehearsed a different cast from the one the executor then made.

    Mana is enforced on the copy exactly as it is on the game. What the
    rehearsed cast itself costs is the planner's question and whoever
    rehearses it supplies that mana (``ai_policy._rehearse_announcement``);
    everything else that is paid for on the way — "counter that spell unless
    its controller pays {3}", "that player may pay {2}{U}" — is paid out of
    what each seat really has, or the tax every such spell levies would be
    one anybody could afford and the spell would measure as nothing.

    The copy is `copy.deepcopy`, the one `engine/game_history.py` already
    takes for the web app's undo, with the card objects shared
    (:func:`_every_card`).
    """
    return scratch_copy_with(game, None)[0]


def scratch_copy_with(game, carried):
    """:func:`scratch_copy`, and *carried* copied **with** it: an object that
    refers into the game (a prompt holding its stack object) comes back
    referring into the copy."""
    import copy

    memo = {id(card): card for card in _every_card(game)}
    clone, carried = copy.deepcopy((game, carried), memo)
    clone.interactive_seats = set()
    return clone, carried


def _settle_scratch(game) -> None:
    """Empty the stack of a scratch copy, answering what each object asks —
    and check state-based actions (CR 704.3) once it is empty: a creature
    dealt lethal damage is on the battlefield until they are, and a reading
    taken before would count it as alive."""
    for _ in range(_REHEARSAL_PASSES):
        game._resolve_priority_window()
        game.auto_resolve_pending_choices()
        game.check_state_based_actions()
        if not game.stack and not game.pending_choices:
            return


def combat_is_still_to_come(game, seat: int) -> bool:
    """Whether *seat* is in a main phase of its own turn with nothing on the
    stack and a combat phase still to come this turn — the moment a cast is
    made **before** a fight, and the only one a rehearsal can play that
    fight out from (:func:`_combat_ahead`)."""
    return game.active_player_index == seat and _combat_ahead(game)


def _combat_ahead(game) -> bool:
    """Whether *game* is in a main phase with nothing on the stack and a
    combat phase in what is left of its turn's plan (CR 500.1; CR 500.8 adds
    one: "after this main phase, there is an additional combat phase",
    Relentless Assault). Read without planning the turn, which asking the
    game would do (``Game._remaining_turn_phases``)."""
    from .mixins._constants import phases_after

    if game.stack or game.pending_choices or game.is_game_over():
        return False
    if game.current_turn_phase not in ("precombat_main", "postcombat_main"):
        return False
    plan = getattr(game, "turn_phases_remaining", None)
    if plan is None:
        plan = phases_after(game.current_turn_phase)
    return "combat" in plan


def has_a_creature_to_fight_with(game, seat: int) -> bool:
    """Whether *seat* controls a creature at all. With none there is no
    attack to declare whatever is cast first — a spell that *makes* one has
    left something behind and is not asked about the fight — so the second
    reading would be the first, at the price of a combat on two copies."""
    return any(permanent.is_creature for permanent in game.controlled_by(seat))


def priced_by_the_fight(now: float, lasting: float, fleeting: bool) -> bool:
    """Whether a cast made before the turn's combat is one a reading with no
    combat in it cannot price: some of its good is gone by the end of the
    turn — all of it (*fleeting*), or more of it than is left (*now* above
    *lasting*). A removal spell, a draw, a discard are priced by what they
    leave.

    The policy asks it before reading a cast a second time with the fight
    fought (``ai_policy._weighed_through_the_fight``), and the censuses ask
    it of the casts they make for real — one definition of which casts the
    fight is part of the price of.
    """
    return bool(fleeting) or now > lasting + _NO_SWING


def run_out_the_turn(game, *, through_combat: bool = False) -> None:
    """Take *game* — a scratch copy (:func:`scratch_copy`) — to the end of
    its turn the way a rehearsal does: with its combat fought first if
    *through_combat* (the active seat's attack and the blocks declared by
    the policies that would declare them), then CR 514's cleanup. For a
    reader that makes a cast for real and wants it priced as a rehearsal
    would price it."""
    _run_out_the_turn(game, through_combat=through_combat)


def _fight_the_combat(game) -> None:
    """Play a scratch copy's combat phases from the main phase it is in: the
    active seat's attack, the blocks, the damage — each declared by the
    policy that would declare it in a game nobody is asked about
    (``ai_combat.run_ai_combat_phase``, the simulator's own driver) — and
    every further combat the turn's plan holds (CR 500.8), each entered the
    way the turn enters it.

    The one place a rehearsal lets something be *decided* on the way to the
    end of the turn, and it is asked for by name (:func:`rehearse`'s
    *through_combat*) on the cast and on the table it is measured against
    alike. What it buys is the difference a precombat cast makes to the
    fight: three more damage from a Giant Growth, none at all under the
    caster's own Fog.
    """
    from .ai_combat import run_ai_combat_phase

    for _ in range(_REHEARSAL_PASSES):
        if not _combat_ahead(game):
            return
        before = (game.current_turn_phase, repr(game.turn_phases_remaining))
        if game.current_turn_phase != "precombat_main":
            # A combat added after this main phase: entered through the
            # turn's own successor, so a skip of it (CR 500.11) is spent.
            if game.enter_next_turn_phase() != "combat":
                return
        run_ai_combat_phase(game, game.active_player_index)
        _settle_scratch(game)
        if (game.current_turn_phase, repr(game.turn_phases_remaining)) == before:
            return


def _run_out_the_turn(game, *, through_combat: bool = False) -> None:
    """Take a scratch copy to the end of its turn: a combat whose blocks are
    already declared deals its damage, the end step's triggers fire
    (CR 513.1: "at the beginning of the next end step" — a card exiled
    until then goes back to its owner's hand, a token made for the turn
    goes), then CR 514's cleanup ends every "until end of turn" effect and
    removes marked damage.

    Nothing is *decided* on the way — no attack is declared, no block made —
    so what is read afterwards is what the cast left, and not what a policy
    then did with it. *through_combat* is the exception, asked for by name:
    the turn's combat is fought first (:func:`_fight_the_combat`).
    """
    if through_combat:
        _fight_the_combat(game)
    for _ in range(_REHEARSAL_PASSES):
        if game.current_turn_phase != "combat" or game.is_game_over():
            break
        step = game.current_step
        game.advance_combat_phase()
        game.auto_resolve_pending_choices()
        if game.current_step == step:
            break
    if game.is_game_over():
        return
    if game.current_turn_phase != "ending" and not game.stack:
        game.resolve_end_step(game.active_player_index)
        _settle_scratch(game)
        if game.is_game_over():
            return
    game.resolve_cleanup_step(game.active_player_index)
    _settle_scratch(game)


def position_digest(game) -> dict:
    """Everything a resolution could have changed on *game*, in comparable
    pieces: per seat its hand and graveyard (by name), the size of its
    library, every other field it carries and each permanent it controls;
    then the game's own fields. The bookkeeping every cast writes is left
    out. Two tables built the same way (two scratch copies of one game)
    digest alike exactly when nothing a player could point at differs —
    see :func:`same_position` for the comparison across one cast.
    """
    seats = []
    for seat, player in enumerate(game.players):
        seats.append({
            "hand": sorted(card.name for card in player.hand),
            "graveyard": sorted(card.name for card in player.graveyard),
            # By name, as a graveyard is: a spell cast out of exile, or
            # exiled as it resolves (a flashback, CR 702.34a), is a trip to
            # be told apart from what the spell did (`same_position`).
            "exile": sorted(card.name for card in player.exile),
            # In order: a tutor that puts its find on top, or a spell that
            # arranges the next three draws, has changed something.
            "library": [card.name for card in player.library],
            "fields": {
                key: repr(value) for key, value in vars(player).items()
                if key not in _PLAYER_BOOKKEEPING
            },
            "battlefield": sorted(
                (
                    permanent.permanent_id, permanent.card.name,
                    repr(sorted(
                        (key, repr(value))
                        for key, value in vars(permanent).items() if key != "card"
                    )),
                    permanent.is_creature and permanent.effective_power,
                    permanent.is_creature and permanent.effective_toughness,
                )
                for permanent in game.controlled_by(seat)
            ),
        })
    return {
        "seats": seats,
        "game": {
            key: repr(_ledger_entries(value) if key == "damage_ledger" else value)
            for key, value in vars(game).items()
            if key not in _GAME_BOOKKEEPING
        },
        "permissions": _permission_entries(game),
    }


def _permission_entries(game) -> list:
    """Every standing permission to cast or play from outside a hand
    (CR 601.3, ``game.cast_permissions``) as ``(what it is, the names of the
    cards it covers)``: the names None for a grant over a whole zone, sorted
    otherwise — which is what one use of it is spent from
    (``cast_permissions.consume``)."""
    entries = []
    for permission in getattr(game, "cast_permissions", None) or ():
        cards = getattr(permission, "cards", None)
        rest = repr(sorted(
            (key, repr(value)) for key, value in vars(permission).items()
            if key != "cards"
        ))
        entries.append((
            rest, None if cards is None else sorted(card.name for card in cards),
        ))
    return sorted(entries, key=repr)


def _ledger_entries(ledger):
    """The damage a turn's ledger records, without the list of spells cast
    beside it — which every cast adds to whatever it does."""
    return getattr(ledger, "entries", ledger)


#: The zones of a seat a spell's own trip runs between, in the order the
#: end of it is looked for: where a resolved spell goes (a graveyard; exile,
#: for a flashback; a hand, bought back), then a library.
_SPELL_ZONES = ("graveyard", "exile", "hand", "library")


def same_position(
    untouched: dict, after: dict, *, spell_name: str | None = None,
    caster: int | None = None, spell_zone: str = "hand",
    spell_seat: int | None = None,
) -> bool:
    """Whether *after* — a :func:`position_digest` taken once *caster* has
    cast *spell_name* out of *spell_zone* and it has resolved — is
    *untouched* with nothing but the spell's own trip in between: from a
    hand to a graveyard, or under a permission (CR 601.3) from a graveyard
    to exile (a flashback), from exile or a library's top to a graveyard —
    in *spell_seat*'s zones where the pile is not the caster's own (a card in
    an opponent's exile goes to its owner's graveyard, CR 400.3)."""
    if not _same_fields(untouched["game"], after["game"]):
        return False
    permissions = list(untouched.get("permissions", ()))
    if spell_name is not None and spell_zone != "hand":
        # The use of the permission the cast was made under, spent as a hand
        # card is: one occurrence of the card out of the first grant that
        # names it, and the grant gone when it names nothing more.
        permissions = _spend_one_use(permissions, spell_name)
    if permissions != list(after.get("permissions", ())):
        return False
    trip_seat = caster if spell_seat is None else spell_seat
    for seat, (was, now) in enumerate(zip(untouched["seats"], after["seats"])):
        zones = {zone: list(now.get(zone, ())) for zone in _SPELL_ZONES}
        if seat == trip_seat and spell_name is not None and spell_zone in zones:
            _put_the_spell_back(was, zones, spell_name, spell_zone)
        if (
            any(zones[zone] != list(was.get(zone, ())) for zone in _SPELL_ZONES)
            or not _same_fields(was["fields"], now["fields"])
            or now["battlefield"] != was["battlefield"]
        ):
            return False
    return True


def _spend_one_use(entries: list, name: str) -> list:
    """*entries* (`_permission_entries`) with one use of a grant naming the
    card *name* spent, as ``cast_permissions.consume`` spends it."""
    spent = []
    done = False
    for rest, names in entries:
        if not done and names is not None and name in names:
            names = list(names)
            names.remove(name)
            done = True
            if not names:
                continue
        spent.append((rest, names))
    return sorted(spent, key=repr)


def _put_the_spell_back(was: dict, zones: dict, name: str, origin: str) -> None:
    """Undo, in *zones* (one seat's, read once a spell has resolved), the
    spell's own trip: back into *origin* as many copies as left it, and out
    of the zones that gained one — and nothing more, so a copy that was in a
    graveyard before the cast is not taken for the one that arrived. A spell
    bought back (CR 702.27a) never left its hand, and has no trip."""
    spent = list(was.get(origin, ())).count(name) - zones[origin].count(name)
    if spent <= 0:
        return
    if origin == "library":
        # Cast off the top (CR 601.3: Future Sight, Mystic Snake's hosts).
        zones["library"] = [name] * spent + zones["library"]
    else:
        zones[origin] = sorted([*zones[origin], *[name] * spent])
    for zone in _SPELL_ZONES:
        if zone == origin:
            continue
        arrived = zones[zone].count(name) - list(was.get(zone, ())).count(name)
        while arrived > 0 and spent > 0:
            zones[zone].remove(name)
            arrived -= 1
            spent -= 1


#: How an attribute nothing has written yet reads once something has cleared
#: it: a record the engine creates on first use and empties afterwards is not
#: a difference between a table that used it and one that never did.
_EMPTY_READINGS = frozenset({
    "None", "False", "0", "0.0", "''", "[]", "()", "{}", "set()", "frozenset()",
})


def _same_fields(was: dict, now: dict) -> bool:
    """Whether two ``{field: repr}`` readings agree, a field only one of them
    has counting as empty on the other."""
    for key in was.keys() | now.keys():
        if was.get(key, None) == now.get(key, None):
            continue
        if key in was and key in now:
            return False
        if (was.get(key) or now.get(key)) not in _EMPTY_READINGS:
            return False
    return True


def _measured(game, *, through_combat: bool = False) -> dict:
    """A scratch copy read twice: as it stands, then run out to the end of
    its turn (with its combat fought, if *through_combat*). The copy itself
    is kept beside the readings, for the one more that is taken only when it
    is needed (:func:`_lasting_digest`)."""
    reading = {
        "digest": position_digest(game),
        "now": standings(game, now=True),
    }
    _run_out_the_turn(game, through_combat=through_combat)
    reading["lasting"] = standings(game, now=False)
    reading["table"] = game
    return reading


def _lasting_digest(reading: dict) -> dict:
    """:func:`position_digest` of a measured copy **once its turn has run
    out** — read on first asking and kept. Whether anything a cast changed is
    still changed by then is a question only some casts raise (the ones no
    standing shows a lasting difference for), and a digest is not free.

    Read with the record of **what damage was dealt** left out
    (:func:`forget_damage_history`): by the end of the turn the damage
    itself is gone (CR 514.2), and what it did — a life lost, a creature
    dead — is in the table already. And as the next turn begins: the
    opponent's permanents as its untap step will leave them, and every
    "this turn" record that turn's bookkeeping resets reset
    (:func:`untap_for_the_next_turn`)."""
    if "lasting_digest" not in reading:
        forget_damage_history(reading["table"])
        untap_for_the_next_turn(reading["table"])
        reading["lasting_digest"] = position_digest(reading["table"])
    return reading["lasting_digest"]


def untap_for_the_next_turn(game) -> None:
    """Untap, on a scratch copy whose turn has run out, what the next turn's
    untap step untaps (CR 502.3): the permanents of the player that turn is
    for — in a two-player game with no extra turn to come, the active
    player's opponent.

    A tap of an opposing creature after the turn's fight was over, or before
    a fight it took no part in, was a change that lasted to the end of the
    turn and to nothing after it: Twiddle, Tidal Bore, Winter Blast, Chain
    Stasis cast at a creature with nothing left to block, at the base score.
    A permanent its untap step would *not* untap is told apart from one it
    would by what keeps it tapped, which is a record of its own ("doesn't
    untap during its controller's next untap step") or a static ability on
    the table; the first is still in the digest, and the second is the
    approximation, read as untapped. With more than two seats, or an extra
    turn queued (CR 500.7), the next untap step is not this one's to guess,
    and nothing is untapped.

    The same turn's **bookkeeping** is run too (``Game.begin_turn_bookkeeping``,
    the one both drivers call as a turn begins): every "this turn" record it
    resets — creatures that died, lands played, cards drawn — is a record of
    a turn that is over, and a token made for the turn and sacrificed at its
    end step "changed" how many creatures died this turn and nothing else
    (Tidal Wave, cast in its caster's own main phase).
    """
    if len(game.players) != 2 or getattr(game, "extra_turn_queue", None):
        return
    if game.is_game_over():
        return
    upcoming = 1 - game.active_player_index
    for permanent in game.controlled_by(upcoming):
        permanent.tapped = False
    game.begin_turn_bookkeeping(upcoming)


def forget_damage_history(game) -> None:
    """Drop, from a scratch copy whose turn has run out, the two records of
    damage that outlive the damage: the turn's ledger of who dealt what
    (``damage_ledger``, cleared at the next turn's start) and each source's
    "who have I damaged this game" (``damage_events.DAMAGED_THIS_GAME``).

    Left in, a fight that went differently by nothing anybody could point at
    was a change that lasted: the caster's own Fog in its main phase, under
    which its 2/2 attacked into a 0/4 Wall and dealt it nothing instead of
    two damage that cleanup would have removed, "changed" two records and was
    cast at the base score. The Fallen's "each opponent … it has dealt damage
    to this game" is the one reader of the second, and is the price.
    """
    from .damage_events import DAMAGED_THIS_GAME

    ledger = getattr(game, "damage_ledger", None)
    entries = getattr(ledger, "entries", None)
    if isinstance(entries, list):
        entries.clear()
    for permanent in [
        *game.all_permanents(),
        *(permanent for player in game.players for permanent in player.phased_out),
    ]:
        permanent.metadata.pop(DAMAGED_THIS_GAME, None)


def _rehearsal_seed(game) -> int:
    """The seed a rehearsal's own randomness runs on: a function of the
    position, so a seed still reproduces a run, and nothing to do with the
    game's real sequence — a coin flipped in a rehearsal is a sample, never a
    look at the flip to come."""
    return 7919 * int(getattr(game, "turn", 0) or 0) + len(game.log)


def _card_order(card) -> tuple:
    """Where a card sorts among the cards of a hidden zone: by what it is,
    never by where it was. Two cards that sort alike are the same card to
    anything a rehearsal reads (a deck is one object per printing, repeated)."""
    return (card.name, str(getattr(card, "oracle_id", "") or ""))


def conceal_from(game, seat: int) -> None:
    """Replace what *seat* cannot see on *game* — a scratch copy — with
    something it **could** be (CR 400.2: a library and a hand are hidden
    zones).

    A rehearsal carries a cast out, and a copy of the game is a copy of
    everything in it: the next card of every library, and every card in every
    other player's hand. Read as they stand, a rehearsed Duress knows whether
    there is a card for it to take and a rehearsed Brainstorm knows what it
    will draw — a decision made on what the seat was never shown.

    So, on the copy and before anything is cast on it:

    * **every library is put in a random order** — the seat's own included,
      since it knows what is in it and not where;
    * **each other player's hand is dealt again**, out of that player's hand
      and library pooled: the same number of cards, drawn from everything the
      seat cannot tell apart.

    Each pool is sorted by what the cards are (:func:`_card_order`) before it
    is shuffled, and the shuffle runs on the rehearsal's own seed
    (:func:`_rehearsal_seed`). That is what makes this **exactly** blind
    rather than roughly so: the redeal is a function of *which* cards are
    hidden and of nothing about *where* they are, so two games that differ
    only in which of them an opponent is holding rehearse the same cast the
    same way (``tests/ai/test_ai_hidden_information_census.py``). Shuffled
    from the order they stood in, a fixed permutation of the real hand and
    library would still have dealt the real hand back some of the time.

    **What the seat may see is left where it is**, through the two seams that
    say so for a viewer in the browser: a hand a standing effect reveals to
    it (``revealed_hands.hand_revealed_to`` — Telepathy, Revelation), and the
    top card of a library that is played revealed or that its owner may look
    at (``library_top.top_is_public`` / ``top_is_visible``) — and the top card
    of its own library an effect lets it **play** (CR 601.3: Conspicuous
    Snoop, Radha, Temporal Aperture), which the permission names to it; dealt
    away, a rehearsed cast of it was refused on every copy and a free cast off
    the top was never proposed.

    What this does not know is what the seat has *been shown and remembers*:
    a card it looked at with a Duress of its own two turns ago, one it
    bounced to that hand, the three it put back with a Brainstorm. Nothing in
    the engine keeps that record — a reveal is an event (``record_reveal``),
    not a standing fact about a card — so every such card is dealt back into
    the unknown. A seat holding a prompt keeps its hand as it is: the prompt
    may name cards in it by position.
    """
    import random

    from .library_top import top_is_public, top_is_visible
    from .revealed_hands import hand_revealed_to

    from .cast_permissions import playable_from_zones

    def playable_on_top(index) -> bool:
        return any(
            entry.get("zone") == "library" and entry.get("index") == 0
            for entry in playable_from_zones(game, index)
        )

    owing = {choice.player_index for choice in game.pending_choices}
    for index, player in enumerate(game.players):
        library = player.library
        seen_on_top = library[:1] if (
            (top_is_visible(game, index) or playable_on_top(index))
            if index == seat else top_is_public(game, index)
        ) else []
        hidden = library[len(seen_on_top):]
        deals_hand = (
            index != seat
            and index not in owing
            and not hand_revealed_to(game, index, seat)
        )
        if deals_hand:
            hidden = [*player.hand, *hidden]
        hidden.sort(key=_card_order)
        random.shuffle(hidden)
        if deals_hand:
            held = len(player.hand)
            player.hand[:] = hidden[:held]
            hidden = hidden[held:]
        library[:] = [*seen_on_top, *hidden]


def _scratch(game, carried, detach, seat):
    """One scratch copy set up for *seat*'s rehearsal: detached if asked
    (``True``, or ``"abstract"`` for :func:`_detach`'s *owing_nothing*), its
    randomness on the rehearsal's own seed and everything *seat* cannot see
    dealt again (:func:`conceal_from`)."""
    import random

    clone, carried = scratch_copy_with(game, carried)
    if detach:
        _detach(clone, owing_nothing=detach == "abstract")
    random.seed(_rehearsal_seed(game))
    conceal_from(clone, seat)
    return clone, carried


def _untouched(
    game, seat: int, *, carried=None, detach: bool = False, without=None,
    without_key=None, through_combat: bool = False,
) -> dict:
    """The table with nothing cast: whatever is on the stack resolves, and
    the turn runs out. What every candidate of one decision is measured
    against (:func:`deliberating`).

    *without* prepares that table when "nothing" has to be arranged, and
    *without_key* says which arrangement it is, for the reading to be kept
    under: a triggered ability whose mode is the question is taken off the
    copy's stack, since an ability with no mode chosen never resolves
    (CR 700.2b); a cast paid for by tapping lands is compared with a table on
    which those lands are tapped too, so that the payment is not mistaken for
    something the spell did.
    """
    cache = _DELIBERATION.get()
    # Per seat: the table with nothing cast is the table as *seat* can know
    # it, and two seats do not see the same one.
    slot = ("untouched", seat, id(carried), detach, without_key, through_combat)
    if cache is not None and slot in cache:
        return cache[slot]
    clone, carried = _scratch(game, carried, detach, seat)
    if without is not None:
        without(clone, carried)
    _settle_scratch(clone)
    could_cast = _casts_open(clone, seat)
    reading = _measured(clone, through_combat=through_combat)
    reading["could_cast"] = could_cast
    if cache is not None:
        cache[slot] = reading
    return reading


def _casts_open(game, seat: int) -> frozenset:
    """``(zone, spell)`` for every cast *seat* may make from outside its hand
    right now (:func:`permitted_casts`)."""
    return frozenset(
        (permitted.zone, permitted.spell.name) for permitted in permitted_casts(game, seat)
    )


def rehearse(
    game, seat: int, perform, *, spell_name: str | None = None,
    leaves_hand: bool = True, key=None, carried=None, detach: bool = False,
    without=None, without_key=None, label: str | None = None,
    through_combat: bool = False, spell_zone: str | None = None,
    spell_seat: int | None = None,
) -> "Rehearsal | None":
    """Carry *perform* out on a scratch copy of *game* and report what it did
    to *seat*'s position — or None when no rehearsal could be run.

    *perform* takes the copy and makes one cast on it exactly as an executor
    would (``ai_policy`` hands the announcement it is about to propose),
    returning the engine's result. The copy then resolves its stack with
    every prompt on its default, is read (:func:`position_digest`,
    :func:`standings`), is run out to the end of its turn and is read again.
    The same two readings of the table **with nothing cast** are what it is
    compared with.

    **Why a rehearsal and not a table of effect families.** The valuation
    this replaced was a set of probes on a card's text, and the obvious next
    step — a value per instruction kind — is the same list one layer down:
    the pool's instants and sorceries resolve 265 kinds, and a kind with no
    entry would score the flat number an unread word did. Carrying the
    compiled program out is the one reading that covers every kind there is
    and every kind still to come: a -2/-2 is weighed against its target's
    toughness because the engine applies it and the creature dies or does
    not; a destroy counts what it removes because that permanent is gone from
    the standing; a discard at an empty hand is worth nothing because nothing
    moved.

    **What it must not do is look ahead, or look at what is hidden.** On the
    copy every library is in a random order and every other player's hand is
    dealt again out of what *seat* cannot tell apart (:func:`conceal_from`),
    and its randomness is reseeded (:func:`_rehearsal_seed`) — so a draw, a
    discard that takes "a noncreature, nonland card", a search's shuffle or a
    coin flip in a rehearsal says what such a cast is *like*, never what the
    real one will turn up; the real game's random sequence is put back exactly
    as it was. What a rehearsal does see is what the seat sees: the table,
    its own hand, how many cards everybody else is holding.

    None rather than a guess when it cannot run: from inside another
    rehearsal (:func:`rehearsing`), on a table that is part-way through a
    resolution (:func:`mid_resolution`), or when the copy raises — a crash
    in a rehearsal is not a crash in the game, and is not nothing either:
    it is written into ``REHEARSALS_RAISED`` under *spell_name* (or *label*,
    for an answer that is not a cast), which a simulated run reports and
    fails on.

    *carried* is an object copied with the game and handed to *perform*
    beside the copy — the prompt being answered, which holds its own stack
    object. *detach* rehearses on a copy cut loose from a resolution the
    original is in the middle of (:func:`_detach`), for an answer that is its
    own stack object — or, as ``"abstract"``, on one that owes nothing at
    all, for a question about a card rather than about this moment; and
    *without* arranges the table "with nothing done" where that takes
    arranging (:func:`_untouched`).

    Asked once per *key* in a deliberation (:func:`deliberating`): a chooser
    that weighs a target and then builds the cast that names it is asking the
    same question twice, and a rehearsal costs a cast.

    *spell_zone* is the zone a spell cast **under a permission** is cast
    out of (CR 601.3: a graveyard, an exile, a library's top), whose trip
    out of it (in *spell_seat*'s zones, for a pile that is not the
    caster's) is the cast's own and not something it did — a flashback Fog
    that only exiled itself changed as little as one cast from a hand. A
    hand cast is *leaves_hand*'s, and a card the seat does not hold is
    neither: its arrival in a graveyard is read as a change.

    **No combat is fought on the way to the end of the turn** — unless
    *through_combat* asks for it, on the cast and on the table it is compared
    with alike (:func:`_fight_the_combat`). That is a second, dearer reading
    for the casts the first one cannot price: one made before the fight
    whose whole trace is over by the end of the turn (``Rehearsal.fleeting``),
    or whose good is. A pump was worth ``TEMPORARY_SHARE`` of the body it
    lent whether or not anything was then done with it, and a Fog cast in
    its caster's own main phase measured as nothing and was cast.
    """
    asked = dict(
        spell_name=spell_name, leaves_hand=leaves_hand, carried=carried,
        detach=detach, without=without, without_key=without_key, label=label,
        through_combat=through_combat, spell_zone=spell_zone,
        spell_seat=spell_seat,
    )
    cache = _DELIBERATION.get()
    if cache is None or key is None:
        return _rehearse(game, seat, perform, **asked)
    slot = ("rehearsal", key)
    if slot not in cache:
        cache[slot] = _rehearse(game, seat, perform, **asked)
    return cache[slot]


def _rehearse(
    game, seat: int, perform, *, spell_name: str | None = None,
    leaves_hand: bool = True, carried=None, detach: bool = False, without=None,
    without_key=None, label: str | None = None, through_combat: bool = False,
    spell_zone: str | None = None, spell_seat: int | None = None,
) -> "Rehearsal | None":
    """:func:`rehearse`, uncached."""
    import random

    if _REHEARSING.get():
        return None
    if held_for_an_answer(game) and detach != "abstract":
        return None
    if mid_resolution(game) and not detach:
        return None
    token = _REHEARSING.set(True)
    real_sequence = random.getstate()
    try:
        untouched = _untouched(
            game, seat, carried=carried, detach=detach, without=without,
            without_key=without_key, through_combat=through_combat,
        )
        clone, copied = _scratch(game, carried, detach, seat)
        result = perform(clone) if carried is None else perform(clone, copied)
        # Paid for, and not yet resolved: what is in each pool now is what
        # the cost left there. Mana that **appears** after this is the
        # spell's doing (a ritual is a cast), which the digest cannot say —
        # it leaves the pools out, since paying moves them too. Mana that
        # goes is not: "unless they pay {1}", paid, is a spell that did
        # nothing and cost a mana more.
        pools = [dict(player.mana_pool) for player in clone.players]
        if not getattr(result, "supported", False):
            return Rehearsal(
                accepted=False, refusal=str(getattr(result, "details", "") or ""),
            )
        _settle_scratch(clone)
        # Whether a fight is still to come once the cast has resolved — read
        # off the copy, because a cast can be what adds one.
        combat_ahead = clone.active_player_index == seat and _combat_ahead(clone)
        made_mana = any(
            int(amount or 0) > int(was.get(symbol, 0) or 0)
            for was, player in zip(pools, clone.players)
            for symbol, amount in player.mana_pool.items()
        )
        # A cast it opened, its own card aside: a flashback card cast from a
        # hand is a graveyard card its owner may cast, and that is the card
        # spent, not a cast gained.
        opened_a_cast = any(
            name != spell_name
            for _zone, name in _casts_open(clone, seat) - untouched["could_cast"]
        )
        reading = _measured(clone, through_combat=through_combat)
        now = standing_swing(untouched["now"], reading["now"], seat)
        lasting = standing_swing(untouched["lasting"], reading["lasting"], seat)
        # The zone the spell's own trip starts in: the hand it is spent from,
        # or the one a permission let it be cast out of; none for a card the
        # seat does not hold.
        zone = "hand" if leaves_hand else spell_zone
        returned = spell_name if zone is not None else None
        # Whether anything changed is read off the table, with the spell's own
        # trip taken out (`same_position`) — and before the card is accounted
        # for below, or a spell bought back with nothing else done would read
        # as a change worth a card.
        changed = made_mana or not same_position(
            untouched["digest"], reading["digest"], spell_name=returned, caster=seat,
            spell_zone=zone or "hand", spell_seat=spell_seat,
        )
        # Whether any of it is still there once the turn is over. Asked of
        # the table only where the standings leave it open — a lasting swing
        # is a lasting change — because the answer costs a digest of each
        # copy. "Leave it open" is a lasting swing of nothing but the spell's
        # own card: the card spent and nothing else, or (a spell bought back,
        # CR 702.27a) not even that. The table then says which it is — a
        # card drawn in place of the one spent is a hand that differs.
        fleeting = (
            changed
            and (
                abs(lasting) < _NO_SWING
                or (leaves_hand and abs(lasting + CARD_WORTH) < _NO_SWING)
            )
            and same_position(
                _lasting_digest(untouched), _lasting_digest(reading),
                spell_name=returned, caster=seat, spell_zone=zone or "hand",
                spell_seat=spell_seat,
            )
        )
        if leaves_hand:
            # The card a cast is made with is spent by every cast, so it is
            # not part of what this one did: it is given back. A spell that
            # comes back to the hand by itself (buyback, CR 702.27a) is then a
            # card to the good, which is what its price is weighed against.
            now += CARD_WORTH
            lasting += CARD_WORTH
        if through_combat:
            # Read once the fight is over: there is no "right after" to tell
            # from "at the end of the turn" that the fight has not passed
            # through, so the lasting reading is the measure.
            now = lasting
        return Rehearsal(
            accepted=True, changed=changed, now=now, lasting=lasting,
            fleeting=fleeting, made_mana=made_mana, through_combat=through_combat,
            combat_ahead=combat_ahead, opened_a_cast=opened_a_cast,
        )
    except Exception as raised:
        _note_raised(label or spell_name, raised)
        return None
    finally:
        random.setstate(real_sequence)
        _REHEARSING.reset(token)
#: Instruction kinds that take a **targeted card out of a graveyard and out of
#: the game** — "Exile target card from a graveyard." (Coffin Purge, Cremate,
#: Headstone; Crypt Creeper's, Steamclaw's and Scavenging Ooze's abilities.)
#: Spelled out and held to registered handlers by
#: ``tests/ai/test_ai_graveyard_denial.py``, for :data:`MANA_ABILITY_KINDS`'
#: reason: a kind renamed out from under a set like this stops matching in
#: silence.
#:
#: Denial, and so wanted from an **opponent's** pile: a card in a graveyard is
#: a resource for the seat that owns it (a flashback cast, a reanimation
#: target, a card toward threshold), and removing the caster's own is the
#: effect spent on itself. A kind that *returns* the card it names — to a
#: hand, to the battlefield — is not here: its printed phrase is almost always
#: "from your graveyard", and where it is not, either pile is a gain.
GRAVEYARD_DENIAL_KINDS = frozenset({"exile_target_graveyard_card"})


def exiles_a_graveyard_target(instructions) -> bool:
    """Whether a step of *instructions* (wrappers opened) is one of
    :data:`GRAVEYARD_DENIAL_KINDS` — the question the cast and activation
    choosers ask before naming whose graveyard a card is exiled from."""
    def walk(steps) -> bool:
        for step in steps or ():
            if getattr(step, "kind", None) in GRAVEYARD_DENIAL_KINDS:
                return True
            payload = getattr(step, "payload", None) or {}
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)) and walk(nested):
                    return True
        return False

    return walk(instructions)


def denied_graveyard_pile(player_index: int, piles) -> "int | None":
    """Which of *piles* (seats, in the order offered) a seat takes cards **out
    of the game** from: the first that is not its own, and its own only when
    there is no other. None for no pile at all.

    "Exile up to three target cards from **a single graveyard**" (Decompose,
    Rapid Decay, Ebony Charm; Carrion Beetles' and Famished Ghoul's abilities)
    leaves the pile to the chooser, and the default took the first in seat
    order — so the seat in chair 0 exiled its own graveyard and the seat in
    chair 1 its opponent's, the same card played two ways by where a player
    sat. See :data:`GRAVEYARD_DENIAL_KINDS` for why the opponent's.
    """
    piles = list(piles or ())
    if not piles:
        return None
    return next((seat for seat in piles if seat != player_index), piles[0])


def graveyard_denial_order(game, owner_seat: int, slots) -> list:
    """*slots* — positions in *owner_seat*'s graveyard a seat may exile — with
    the cards their owner could still **cast from there** first, each group
    in pile order.

    A card with flashback (CR 702.34a; printed, or granted by Recoup) is a
    spell its owner still holds; any other card in a graveyard is, to a seat
    removing "up to three", one card among equals. Asked of
    ``flashback.has_flashback`` with the game and the pile's seat, which is
    what sees a grant. A stable sort, so a pile holding none is exiled in the
    order it always was — and a seed that met none replays as it did.
    """
    from .flashback import has_flashback

    pile = game.players[owner_seat].graveyard
    return sorted(
        slots,
        key=lambda slot: 0 if (
            isinstance(slot, int) and 0 <= slot < len(pile)
            and has_flashback(pile[slot], game=game, owner_seat=owner_seat)
        ) else 1,
    )


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
    "CARD_WORTH",
    "GRAVEYARD_DENIAL_KINDS",
    "MANA_ABILITY_KINDS",
    "REHEARSALS_RAISED",
    "Rehearsal",
    "SELF_PAYMENT_KINDS",
    "SOURCE_HAMPER_KINDS",
    "SOURCE_REMOVAL_KINDS",
    "SOURCE_RETURN_KINDS",
    "SPELL_TYPES",
    "CounterProfile",
    "DividedShape",
    "ManaYield",
    "OfferTrade",
    "PermittedCast",
    "TollLoss",
    "ability_target_side",
    "cards_drawn_by_controller",
    "cards_drawn_by_target",
    "cast_weighed",
    "caster_sacrifice_steps",
    "cast_helps_the_player_it_names",
    "castable_commanders",
    "conceal_from",
    "chosen_color_sweeps",
    "casting_under",
    "chosen_creature_type_side",
    "color_most_worth_sweeping",
    "chosen_name_is_read_off_the_targets_library",
    "combat_is_still_to_come",
    "counters_a_spell",
    "denied_graveyard_pile",
    "denies_its_target",
    "destroyed_permanent_filter",
    "divided_shape",
    "is_mana_ability",
    "mana_ability_amount",
    "exiled_search_pile_comes_back",
    "exiled_search_pile_comes_back_one_at_a_time",
    "exiles_a_graveyard_target",
    "foreign_activation_use",
    "forget_damage_history",
    "untap_for_the_next_turn",
    "graveyard_denial_order",
    "hand_entry_steps",
    "hand_waiver",
    "harms_its_own_source",
    "named_counter_marks_for_harm",
    "has_a_creature_to_fight_with",
    "hand_pick_entry_consumer",
    "instruction_target_side",
    "offer_trade",
    "offered_action_is_a_payment",
    "permanent_worth",
    "position_digest",
    "priced_by_the_fight",
    "rehearse",
    "rehearsing",
    "seat_standing",
    "standing_swing",
    "standings",
    "swing_worth",
    "permitted_casts",
    "pick_is_tested_for_a_shared_color",
    "planned_mana_yield",
    "returns_creature_to_hand",
    "role_target_sides",
    "run_out_the_turn",
    "same_position",
    "scratch_copy",
    "several_target_slot_sides",
    "source_toughness_change",
    "spell_denies_its_own_target",
    "spell_hand_pick_entry_filters",
    "spell_target_side",
    "toll_branch_loss",
]
