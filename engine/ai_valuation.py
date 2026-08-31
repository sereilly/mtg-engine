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
_OWN_CATEGORIES = frozenset({"pump", "counters", "regeneration", "evasion", "attachments", "characteristics"})


def activation_target_side(instruction: OracleInstruction) -> str | None:
    """"opponent" / "you" / None — whose permanent an object-targeted activated
    ability should be aimed at, derived from ``INSTRUCTION_CATEGORIES``."""
    from .grammar.lowering.categories import INSTRUCTION_CATEGORIES

    category = INSTRUCTION_CATEGORIES.get(getattr(instruction, "kind", None))
    if category in _OPPONENT_CATEGORIES:
        return "opponent"
    if category in _OWN_CATEGORIES:
        return "you"
    return None


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
    "exile_any_number_of_own_tokens",
})


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


def is_mana_ability(instruction: OracleInstruction) -> bool:
    """Whether *instruction* adds mana to its controller's pool."""
    return instruction.kind in MANA_ABILITY_KINDS


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
        any_count = instruction.payload.get("any_color_count")
        if isinstance(any_count, int):
            return any_count
        amount = instruction.payload.get("amount")
        if isinstance(amount, int):
            return amount
        return 1
    return None


def _several_target_instruction(program):
    """The one instruction in *program* whose description names several targets."""

    def walk(instructions):
        for instruction in instructions:
            targets = instruction.payload.get("targets")
            if (
                isinstance(targets, dict)
                and isinstance(targets.get("count"), int)
                and targets["count"] > 1
            ):
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
    if not isinstance(count, int) or count <= 1:
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


__all__ = [
    "MANA_ABILITY_KINDS",
    "SELF_PAYMENT_KINDS",
    "SPELL_TYPES",
    "CounterProfile",
    "cards_drawn_by_controller",
    "cards_drawn_by_target",
    "counters_a_spell",
    "destroyed_permanent_filter",
    "is_mana_ability",
    "mana_ability_amount",
    "offered_action_is_a_payment",
    "returns_creature_to_hand",
    "several_target_slot_sides",
]
