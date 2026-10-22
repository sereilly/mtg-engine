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
weights stay in the policy. Heuristics are tuning, and a tuning constant is
not a correctness claim — but *which cards a constant applies to* is, and that
is what lives here.

**A family of modules, and this is its front door.** What is left here is
what a card does that no other reader needs first: what it draws, bounces,
destroys or counters, its mana abilities (``planned_mana_yield``,
``mana_ability_amount``), what an ability does to its own source
(``harms_its_own_source``, ``foreign_activation_use``), its hand-pick and
entry readers, and the optional costs a cast may take (``cast_offers``). The
rest is one subject a module:

* ``ai_weighed_cast`` — the floor: the cast being weighed (its mode, the
  permission it is cast under), the casts a seat may weigh beyond its hand,
  and the walkers every reader opens a program with;
* ``ai_target_sides`` — which side of the table a target, a seat, a slot or
  a role belongs on;
* ``ai_rehearsal`` — **the one measure**: what a seat's position is worth and
  what one cast does to it, found by carrying the cast out on a scratch copy
  of the game. It is in this family and not beside the weights because two
  readers have to agree on it — the cast policy, which predicts with it, and
  the mode census, which measures with it — and because it is the same move
  as everything else here: the compiled program read for what it does, this
  time by running it;
* ``ai_prompt_readers`` — what a choice the rules leave to a player does (an
  offer's price, a toll's branches, a chosen colour, name, number or pile).

The same split is why ``ai_prompt_readers.offered_action_is_a_payment`` is in
this family rather than in ``engine/mixins/stack/choices/`` beside the
default that reads it. "This offer's price comes out of the taker's own
permanents, hand, library or life" is a claim about what a card *does*, true
of every card printing the sentence; "and therefore a seat nobody asked
refuses it" is the stated policy, and that stays with the other stated
policies in ``_default_optional_pay``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CardDefinition
from .oracle import OracleInstruction, compile_card_oracle
from .ai_weighed_cast import (
    SPELL_TYPES,
    _spell_instructions,
    _first,
    _effect_steps,
)


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
    (``cast_targets.entry_trigger_instructions``) rather than by naming the gate,
    so any condition the kicked view comes to understand is covered here too.
    Empty for an instant or sorcery, whose bought half is a step of its own
    resolution and is read off the cast spec.
    """
    from .cast_targets import entry_trigger_instructions

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

    ``guard`` is the condition an ``if_then`` around that sentence asks, when
    there is one: "…then put that card onto the battlefield **if it has the
    same name as a permanent**" (Retraced Image). A pick the guard refuses
    enters nothing, so the picks it admits are the gift.
    """
    def visit(instructions, guard):
        for instruction in instructions:
            payload = instruction.payload or {}
            if (
                instruction.kind == "put_chosen_hand_cards_onto_battlefield"
                and str(payload.get("cards_from")) == str(result_key)
            ):
                return {
                    "card_filter": dict(payload.get("card_filter") or {}),
                    "superlative": dict(payload.get("superlative") or {}),
                    "guard": guard,
                }
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)):
                    found = visit(nested, (
                        payload.get("condition")
                        if instruction.kind == "if_then" and key == "then"
                        else guard
                    ))
                    if found is not None:
                        return found
        return None

    program = compile_card_oracle(card)
    return visit([
        *program.instructions,
        *(a.instruction for a in program.activated_abilities if a.instruction is not None),
        *(t.instruction for t in program.triggered_abilities if t.instruction is not None),
    ], None)


def spell_hand_pick_entry_filters(card: CardDefinition) -> tuple[dict, ...]:
    """For each "choose a card in your hand" step of *card*'s spell program
    whose pick the program then puts onto the battlefield for its owner
    (:func:`hand_pick_entry_consumer`), the noun phrase a pick must answer to
    get there.

    A caster holding no such card gets nothing from the spell, and Stronghold
    Gambit's "each player" makes it worse than nothing: the opponent's pick is
    the only one that can enter. Asked before the cast for that reason.
    """
    return tuple(entry["card_filter"] for entry in spell_hand_pick_entries(card))


def spell_hand_pick_entries(card: CardDefinition) -> tuple[dict, ...]:
    """:func:`spell_hand_pick_entry_filters` whole: each such pick's
    :func:`hand_pick_entry_consumer` answer, with the record the pick writes
    under (``result_key``) beside it.

    The pick is a "choose a card in your hand" step **or a reveal of one**
    ("Reveal a card in your hand, then put that card onto the battlefield if
    it has the same name as a permanent", Retraced Image) — one prompt, two
    printed verbs. A consumer's ``guard`` is read against the record the pick
    writes, so a caller asks it of a held card by handing that card in under
    ``result_key``.
    """
    entries: list[dict] = []

    def walk(instructions) -> None:
        for instruction in instructions:
            payload = instruction.payload or {}
            if instruction.kind in ("choose_cards_in_hand", "reveal_cards_from_hand"):
                key = str(payload.get("result_key") or "chosen_hand_cards")
                consumer = hand_pick_entry_consumer(card, key)
                if consumer is not None:
                    entries.append({**consumer, "result_key": key})
            for key in ("steps", "then", "else", "action", "otherwise"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)):
                    walk(nested)

    walk(_spell_instructions(card))
    return tuple(entries)


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


def offer_buys_a_drawback_to_its_source(steps) -> bool:
    """Whether everything an offer's accept branch buys, past the action the
    seat is asked to take, acts against the ability's own source.

    The drawback a card prints when it lets *anybody* buy something off it:
    "any player may exile a card from their graveyard. If a player does,
    **this creature assigns no combat damage this turn**" (Carrion Rats),
    "…If a player does, **put this creature on top of its owner's library**"
    (Argothian Wurm). Read through the two sets
    :func:`harms_its_own_source` already reads — a removal or a hamper of the
    source — plus the one hamper only an offer prints, the combat-damage mark,
    and only on the source itself: on the permanent an Aura is attached to
    (Cloak of Confusion), or one a delay bound, it carries a ``subject`` and is
    somebody else's creature.

    *steps* is the branch as ``_offer_to_seat`` builds it — the offered action
    first, then what follows from taking it (:func:`offered_action_is_a_payment`
    reads the same order).
    """
    rest = [step for step in steps if getattr(step, "kind", None)][1:]
    drawbacks = (
        SOURCE_REMOVAL_KINDS | SOURCE_HAMPER_KINDS
        | {"assign_no_combat_damage_until_eot"}
    )
    return bool(rest) and all(
        step.kind in drawbacks and not (step.payload or {}).get("subject")
        for step in rest
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
    for a land (`ai_mana_sources._land_tap_options`), asked of
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


#: The search destination that puts what it finds on top of the searching
#: player's library ("…then shuffle and put that card on top").
LIBRARY_TOP = "library_top"


def library_top_setups(card: CardDefinition, x_value: "int | None" = None) -> tuple:
    """The searches a cast of *card* makes that put what they find **on top of
    its caster's own library**, as ``(payload, count)`` — ``count`` the
    number of cards the search puts there (X read as *x_value*), or None for
    "any number of".

    "Search your library for a card, then shuffle and put that card on top"
    (Vampiric Tutor, Mystical Tutor, Insidious Dreams' X cards, Scouting
    Trek's basic lands): the cards stay in the library, so a rehearsal of the
    cast reads no standing change — a hand, a life total and a board are what
    a standing counts, and the order of a library is none of them. What the
    cast bought is the next draws, chosen. Derived from the compiled program
    (``search_library`` with every destination the top of the library), so it
    names no card. Empty for a permanent, whose cast is not rehearsed.
    """
    found = []
    for instruction in _spell_instructions(card):
        for step in _effect_steps(instruction):
            if step.kind != "search_library":
                continue
            payload = step.payload or {}
            places = list(payload.get("destinations") or ()) or [payload.get("destination")]
            if not places or any(place != LIBRARY_TOP for place in places):
                continue
            if "library" not in tuple(payload.get("zones") or ("library",)):
                continue
            # "…and exile the rest" (Doomsday) is not a setup but a library
            # cut down to the finds: what it changes is every draw after them.
            if payload.get("exile_rest"):
                continue
            count = payload.get("count", 1)
            if count == "x":
                count = max(0, int(x_value or 0))
            elif count == "any":
                count = None
            elif not isinstance(count, int):
                continue
            found.append((payload, count))
    return tuple(found)


__all__ = [
    "MANA_ABILITY_KINDS",
    "SOURCE_HAMPER_KINDS",
    "SOURCE_REMOVAL_KINDS",
    "SOURCE_RETURN_KINDS",
    "CounterProfile",
    "ManaYield",
    "cards_drawn_by_controller",
    "cards_drawn_by_target",
    "caster_sacrifice_steps",
    "counters_a_spell",
    "destroyed_permanent_filter",
    "is_mana_ability",
    "mana_ability_amount",
    "foreign_activation_use",
    "library_top_setups",
    "hand_entry_steps",
    "harms_its_own_source",
    "hand_pick_entry_consumer",
    "offer_buys_a_drawback_to_its_source",
    "planned_mana_yield",
    "returns_creature_to_hand",
    "source_toughness_change",
    "spell_hand_pick_entries",
    "spell_hand_pick_entry_filters",
]
