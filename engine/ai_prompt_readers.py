"""What a choice the rules leave to a player does, read off the compiled
program for the answer a seat nobody asks gives.

A prompt's default (``engine/pending_choices.py``) states a policy — take
gifts, pay tolls, make no trades — and a policy needs to know which choices
are gifts. Each reader here names the cards a default reaches by what their
program does, never by name, for the resolution path that arms the prompt
(``mixins/stack/choices``, ``handlers/zones``, ``handlers/control_flow``, the
cast and activation paths) or the policy's answer to it (``ai_prompts``):

* **a colour, a name, a number, a creature type** — the colour an opposing
  object threatens, the colour a sweep is worth naming, where a chosen name
  is looked for, the flip run a chosen number buys, whose creatures a chosen
  type names (:func:`chosen_creature_type_side`);
* **a pile** — whether what a search exiled comes back, all at once or a
  card a turn, and whether a pick is tested for a shared colour;
* **a graveyard card** — the pile an exile denies, the order denial and a
  cost's exile take cards in (:func:`graveyard_denial_order`,
  :func:`graveyard_price_order`), and whether an effect reads which cards its
  cost exiled;
* **a discard** — what the sentence behind it tests the discarded card for
  (:func:`discard_spares_a_penalty`, :func:`discard_pays_its_cause`).

What an **offer** costs and buys — a "you may", an "unless … pays", a toll's
two branches — is ``ai_offer_readers``'. The engine's resolution paths import
these from here, inside the function that asks.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CardDefinition
from .oracle import OracleInstruction, compile_card_oracle
from .ai_weighed_cast import _effect_steps, _walk_program
from .ai_standing import permanent_worth


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
            elif payload.get("keywords"):
                # "Creatures of the chosen type have **fear**." (Cover of
                # Darkness); "… have **shroud**." (Steely Resolve.) A keyword
                # granted with no P/T change is a gift to the type, so the
                # controller's own: aimed at the opponents' type, the
                # enchantment made *their* creatures unblockable and
                # untargetable.
                sides.add("you")
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
    # "{3}, {T}, **Sacrifice a creature of the chosen type**: …" (Doom
    # Cannon.) A cost is paid out of its payer's own permanents (CR 701.21a),
    # so a type named in one is the controller's own: aimed at the opponents'
    # type, the artifact could never be activated.
    for ability in compile_card_oracle(card).activated_abilities:
        cost = getattr(ability, "cost", None)
        if cost is not None and _reads_chosen_creature_type([
            getattr(cost, "sacrifice_filter", None),
            getattr(cost, "tap_filter", None),
            getattr(cost, "exile_filter", None),
            getattr(cost, "return_to_hand_filter", None),
            list(getattr(cost, "discard_filters", None) or ()),
        ]):
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


def _signed(value) -> int:
    """+1, -1 or 0 for a printed P/T amount: an int by its sign, a variable
    ("x", "-x") by its spelling."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return (value > 0) - (value < 0)
    if isinstance(value, str) and value:
        return -1 if value.startswith("-") else 1
    return 0


def resolution_creature_type_preference(
    card: CardDefinition,
) -> "tuple[str | None, str] | None":
    """Whose objects a creature type chosen **while the effect resolves**
    should name, and where they are counted — ``(side, zone)``, or None when
    nothing the card prints says.

    The resolution-time twin of :func:`chosen_creature_type_side` (which reads
    CR 614.1c's entry record), for CR 608.2d's choice — "of the creature type of
    your choice", "Choose a creature type.", "Each player chooses a creature
    type." The record is spent by a later step of the same effect, through
    ``subtype_filter_from`` (the word names the set) or
    ``exclude_subtypes_from`` (the word names the set spared), and what that
    step does says whose type to name (``value_choices.best_creature_type``
    reads *side*):

    * a pump to the type, by its sign (Defensive Maneuvers +0/+4, Tribal Unity
      +X/+X — the chooser's own; Outbreak's -1/-1 — the hoser default);
    * an untap of the type (Riptide Chronologist) — the chooser's own;
    * a sweep that spares the types named (Harsh Mercy) — the chooser's own;
    * every creature card of the type returned from each graveyard (Patriarch's
      Bidding) — the chooser's own, counted in the graveyards;
    * a revealed card tested for the type (Bloodline Shaman), and a run of
      reveals stopping on one (Riptide Shapeshifter) — the chooser's own
      library;
    * a gain of control of the type behind "more … than each other player"
      (Peer Pressure) — ``"majority"``;
    * the type **set** on the ability's own source or on its Aura's host ("{1}:
      This creature becomes the creature type of your choice until end of
      turn", the Mistforms; Mistform Mask) — ``"join"``: the chooser's own
      commonest type among its *other* creatures, the tribe its lords and
      chosen-type anthems pump, so the creature changing type does not vote
      for the type it already has;
    * the replacement word of a creature-type text change (Artificial
      Evolution) — the chooser's own: the rewritten lord or type line is about
      the chooser's tribe. (The word *replaced* is read off the target by its
      own step, ``written_on_target``.)

    Everything else that reads the word (a destroy, a tap, a discard, a forced
    attack) is a hoser, which is the default and needs no row.
    """
    from .oracle_types import (CHOSEN_CREATURE_TYPE_THIS_WAY,
                               CHOSEN_CREATURE_TYPES_THIS_WAY)

    records = (CHOSEN_CREATURE_TYPE_THIS_WAY, CHOSEN_CREATURE_TYPES_THIS_WAY)
    found: set[tuple[str | None, str]] = set()
    for instruction in _walk_program(compile_card_oracle(card)):
        payload = instruction.payload or {}
        if instruction.kind == "if_then":
            condition = payload.get("condition") or {}
            if (
                condition.get("kind") == "revealed_card_is"
                and condition.get("subtype_filter_from") in records
            ):
                found.add(("you", "library"))
            continue
        cards = payload.get("cards")
        if (
            instruction.kind == "shuffle_graveyard_into_library"
            and isinstance(cards, dict)
            and cards.get("subtype_filter_from") in records
        ):
            # "Choose a creature type. Shuffle all creature cards of that type
            # from your graveyard into your library." (Elvish Soultiller.) The
            # chooser's own cards come back to the deck — Patriarch's Bidding's
            # row below, one destination over, counted in the graveyards.
            found.add(("you", "graveyard"))
            continue
        described = payload.get("filter")
        reads = payload.get("subtype_filter_from") in records or (
            isinstance(described, dict)
            and described.get("subtype_filter_from") in records
        )
        if payload.get("exclude_subtypes_from") in records:
            found.add(("you", "battlefield"))
        elif not reads:
            continue
        elif instruction.kind == "buff_creatures_global":
            sign = _signed(payload.get("power")) + _signed(payload.get("toughness"))
            if sign > 0:
                found.add(("you", "battlefield"))
        elif instruction.kind == "untap_all_matching":
            found.add(("you", "battlefield"))
        elif instruction.kind == "gain_control_of_all_matching":
            found.add(("majority", "battlefield"))
        elif instruction.kind == "return_all_cards_from_graveyard":
            found.add(("you", "graveyard"))
        elif instruction.kind == "reveal_until_match":
            # "Choose a creature type. Reveal cards from the top of your
            # library until you reveal a creature card of that type. Put that
            # card onto the battlefield …" (Riptide Shapeshifter.) The run
            # digs the chooser's own library, so the word is its commonest
            # type there — Bloodline Shaman's reveal above, over a run.
            found.add(("you", "library"))
    for instruction in _walk_program(compile_card_oracle(card)):
        # A type *set* reads the word through ``subtype_from`` rather than as a
        # filter, so it is asked after the loop above and only of the two
        # subjects the chooser's own seat holds: a targeted set (Unnatural
        # Selection, Trickery Charm) may be aimed either way and keeps the
        # hoser default.
        if (
            instruction.kind in ("set_self_creature_type", "set_enchanted_creature_type")
            and (instruction.payload or {}).get("subtype_from") in records
        ):
            found.add(("join", "battlefield"))
        elif instruction.kind == "mark_text_modified" and (
            instruction.payload or {}
        ).get("new_type_from"):
            found.add(("you", "battlefield"))
    return next(iter(found)) if len(found) == 1 else None


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
        # "…exile them, then create **that many** 1/1 colorless Myr artifact
        # creature tokens." (Myr Incubator.) The pile is not handed back but
        # *paid for*, one token a card, which is the same reason to take the
        # maximum: a step that reads how many were exiled.
        if any(
            isinstance(value, dict) and value.get("amount_from") == "exiled_count"
            for value in instruction.payload.values()
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


#: The steps that take a recorded permanent away from whoever controls it —
#: out of play, not merely tapped or phased for a turn — or hand it to another
#: seat: "…that opponent gains control of that creature" (Risky Move), "gain
#: control of target creature of an opponent's choice they control"
#: (Preacher). A control change is the permanent leaving its controller's
#: side as surely as an exile is.
_TAKEN_FROM_ITS_CONTROLLER = frozenset({
    "exile_recorded_permanent",
    "sacrifice_recorded_permanent",
    "return_recorded_permanents_to_hand",
    "give_control_of_chosen_to_player",
    "steal_target_linked_to_source",
})


def linked_exile_returns_to_battlefield(card: CardDefinition) -> "str | None":
    """The card type *card*'s linked pile is put onto the battlefield as —
    ``""`` for any card, None when nothing on *card* puts it there.

    "Imprint — When this creature enters, you may exile a card from your hand
    face down. When this creature dies, turn the exiled card face up. **If
    it's a creature card, put it onto the battlefield under your control.**"
    (Summoner's Egg.) The exile from hand is a seat's own pick, and a seat
    nobody asks took the cheapest card in hand — a Lightning Bolt over a Craw
    Wurm, so the Egg hatched nothing. The pile is the payoff here, not a
    loss, and the card it should hold is the one the return would put onto
    the battlefield.

    Read off the compiled program (``put_exiled_with_source`` to the
    battlefield, and the ``card_type`` that narrows it), so no card is named.
    """
    for instruction in _walk_program(compile_card_oracle(card)):
        payload = instruction.payload or {}
        if (
            instruction.kind == "put_exiled_with_source"
            and payload.get("zone") == "battlefield"
        ):
            return str(payload.get("card_type") or "")
    return None


def pick_is_taken_from_its_controller(card: CardDefinition, result_key: str) -> bool:
    """Whether a later step of *card* takes the permanent a
    ``choose_permanent`` recorded under *result_key* away from its controller
    — exiles it, sacrifices it, returns it to its owner's hand.

    "When this creature enters, **an opponent chooses** a permanent you
    control other than this creature **and exiles it**." (Wormfang Crab.) The
    pick is the chooser's to make count against the permanents' controller,
    and a seat nobody asks took the first candidate in board order — the
    Crab's controller's first land, every time.

    Read off the compiled steps (the record each names, ``permanents_from``),
    so any card printing the shape is answered and no card is named.
    """

    def walk(instructions) -> bool:
        for instruction in instructions:
            payload = getattr(instruction, "payload", None) or {}
            if (
                getattr(instruction, "kind", None) in _TAKEN_FROM_ITS_CONTROLLER
                and payload.get("permanents_from") == result_key
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


# --- "Choose a card name": where the name will be looked for ----------------

#: The steps that read a chosen name against cards of the **chooser's own**,
#: and the zone each one looks in. A player built their own deck, so what
#: their library still holds is theirs to work out (CR 401.2 hides which card
#: is where), and they see their own hand outright — so for these the name
#: worth choosing is one of their own cards.
_OWN_ZONE_NAME_READERS = {
    "reveal_top_sorting_by_chosen_name": "library",
    "reveal_random_card_from_hand": "hand",
    # "…Target opponent guesses whether a card with that name is in **your
    # hand**." (Liar's Pendulum.) The name is guessed about against the
    # chooser's own hand, which the chooser sees.
    "guess_named_card_in_hand": "hand",
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


def secret_number_highest_pays(card: CardDefinition) -> bool:
    """Whether the numbers *card*'s players name in secret are paid for by
    **the highest** — "Each player with the highest number loses that much
    life." (Menacing Ogre.)

    Read off the compiled program: a loop over ``each_revealed_highest``, the
    seat set only that sentence names. Goblin Game's loss falls on everyone and
    its extra one on the *fewest*, which is the opposite incentive, so the two
    are told apart by which set a step loops over and never by a name.
    """
    return any(
        instruction.kind == "for_each"
        and ((instruction.payload or {}).get("iterator") or {}).get("players")
        == "each_revealed_highest"
        for instruction in _walk_program(compile_card_oracle(card))
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
    return _a_later_step_reads_the_name(card, instruction, _TARGET_LIBRARY_NAME_READERS)


#: The steps that read a chosen name against **the targeted player's hand**:
#: "Choose a nonland card name. Target player reveals their hand and discards
#: all cards with that name." (Cabal Therapy.) The name is chosen as the spell
#: resolves and before the reveal (ruling 2016-06-08), so the hand is hidden
#: when it is chosen.
_TARGET_HAND_NAME_READERS = frozenset({"discard_all_matching_cards"})


def chosen_name_is_read_off_the_targets_hand(card: CardDefinition, instruction) -> bool:
    """Whether *instruction*'s "choose a card name" is looked for in **the
    target player's hand** (Cabal Therapy) — :func:`chosen_name_is_read_off_the_targets_library`'s
    question one zone over, read the same way.

    An opponent's hand is a hidden zone (CR 400.2) and it is revealed only
    after the name is fixed, so the evidence a seat may name from is that
    player's graveyard — the public record of what their deck holds; a seat
    that aims the spell at itself sees its own hand outright.
    """
    return _a_later_step_reads_the_name(card, instruction, _TARGET_HAND_NAME_READERS)


def _a_later_step_reads_the_name(card: CardDefinition, instruction, readers) -> bool:
    """Whether a step of *readers*' kinds follows *instruction* in the sequence
    that holds it, found by identity in *card*'s compiled program."""
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
                        later.kind in readers for later in nested[position + 1:]
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


#: Instruction kinds that take a **targeted card out of a graveyard and out of
#: the game** — "Exile target card from a graveyard." (Coffin Purge, Cremate,
#: Headstone; Crypt Creeper's, Steamclaw's and Scavenging Ooze's abilities.)
#: Spelled out and held to registered handlers by
#: ``tests/ai/test_ai_graveyard_denial.py``, for :data:`ai_valuation.MANA_ABILITY_KINDS`'
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


def graveyard_price_order(game, owner_seat: int, slots) -> list:
    """*slots* — positions in *owner_seat*'s own graveyard that seat is giving
    up **as a price** — least valuable first.

    :func:`graveyard_denial_order` read the other way round, because it is the
    same question asked by the card's owner: a card its owner could still
    **cast from there** (flashback, CR 702.34a — printed, or granted by
    Recoup) is a spell that seat still holds, so it goes last. Among the rest,
    mana value, the one ranking every card in the pool answers (the reading
    Forgotten Lore's default gives the pile an opponent picks from): a land
    goes before a spell and a cheap spell before a dear one. Ties keep pile
    order, so a seed that met none of this replays as it did.

    For every pick out of a seat's own pile whose cards are a payment and not
    what the effect then reads: an offer's or a toll's price ("any player may
    exile a card from their graveyard", Carrion Rats; Gurzigost's "unless you
    put two cards from your graveyard on the bottom"), a replacement's (Nefarious
    Lich), an activation cost (Grim Lavamancer) and a spell's additional cost
    (Haunting Misery). The defaults took the pile in order, so the price was
    whatever sat at the bottom — a flashback spell as soon as a land.
    """
    from .flashback import has_flashback

    pile = game.players[owner_seat].graveyard

    def worth(slot) -> tuple:
        if not (isinstance(slot, int) and 0 <= slot < len(pile)):
            return (1, 0.0)
        card = pile[slot]
        castable = has_flashback(card, game=game, owner_seat=owner_seat)
        return (1 if castable else 0, float(getattr(card, "cmc", 0) or 0))

    return sorted(slots, key=worth)


#: The record keys through which an effect reads **which** cards its own cost
#: exiled: a characteristic of the exiled card ("put X +1/+1 counters, where X
#: is the exiled card's mana value", Necropolis) or a condition on it. The
#: count alone (``cost_exiled_count``, Painbringer) is not on the list — any
#: cards make the same count.
_COST_EXILE_READERS = frozenset({
    "cost_exile_characteristic", "exiled_for_cost", "exiled_set_for_cost",
})


def reads_what_its_cost_exiled(instructions) -> bool:
    """Whether a step of *instructions* reads which cards its own cost exiled
    — so the cards an exile cost takes are not a plain price and
    :func:`graveyard_price_order` must not choose them (the effect wants the
    dearest, not the cheapest)."""
    def mentions(value) -> bool:
        if isinstance(value, str):
            return value in _COST_EXILE_READERS
        if isinstance(value, dict):
            return any(
                key in _COST_EXILE_READERS or mentions(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(mentions(item) for item in value)
        payload = getattr(value, "payload", None)
        return isinstance(payload, dict) and mentions(payload)

    return mentions(tuple(instructions or ()))


def discard_spares_a_penalty(card: CardDefinition | None) -> "tuple[dict, bool] | None":
    """What a discard of *card*'s is **tested for** by the sentence behind it,
    or None: the card filter and whether the test is negated.

    "Each player discards a card. Then each player who **didn't discard a
    creature card this way** loses 4 life." (Strongarm Tactics.) The penalty
    is read off which card each seat discarded (``recipient_did``, a
    ``discarded_this_way`` deed), so the card a seat nobody asks gives up
    decides whether it pays it — and the discard default took its first
    card, losing 4 life holding a creature card in 5 of 12 discards
    (Onslaught's W2G5). Negated, a matching card spares the penalty; plain
    ("each player who discarded a creature card …"), a matching card is the
    one that incurs it.

    Read off the compiled steps, so any card printing the shape is answered
    and no card is named.
    """
    if card is None:
        return None
    program = compile_card_oracle(card)
    roots = (
        tuple(program.instructions)
        + tuple(a.instruction for a in program.activated_abilities if a.instruction is not None)
        + tuple(t.instruction for t in program.triggered_abilities if t.instruction is not None)
    )

    def walk(instructions):
        for instruction in instructions:
            payload = getattr(instruction, "payload", None) or {}
            deed = payload.get("recipient_did")
            if isinstance(deed, dict) and deed.get("kind") == "discarded_this_way":
                return dict(deed.get("filter") or {}), bool(deed.get("negated"))
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)):
                    found = walk(nested)
                    if found is not None:
                        return found
        return None

    return walk(roots)


#: The steps a "for each … card discarded this way" count pays to the
#: sentence's "you": life, cards.
_CAUSE_GAIN_KINDS = frozenset({"target_gains_life"})
_CAUSE_DRAW_KINDS = frozenset({"draw_cards", "draw_controller_cards"})


@dataclass(frozen=True)
class DiscardPayoff:
    """What a discard pays the seat that caused it, per card that passes the
    test (:func:`discard_pays_its_cause`): ``matches(card, game, owner)``
    tests a discarded card, and ``worth(game, cause_seat)`` is what one such
    card pays the cause on the standing's scale (``ai_standing``) — 0.0 for a
    payoff this does not price (an untap), which then only breaks ties."""

    matches: object
    worth: object


def discard_pays_its_cause(card: CardDefinition | None) -> "DiscardPayoff | None":
    """What *card*'s sentence pays its controller — the seat that caused the
    discard — for each discarded card that passes a test, or None, read off
    the compiled steps that test it.

    "Target player discards two cards. You gain 3 life for each land card
    discarded this way." (Gerrard's Verdict: a ``per_each`` over the
    ``discarded_this_way`` record on a gain for the caster — three life a
    land.) "…then discards a card. If that player discards an artifact card
    this way, untap this creature." (Lumengrid Augur: an ``if_then`` on the
    card's types, unpriced.) The discarder's choice decides the payoff
    (``ai_prompt_picks.discard_order``). :func:`discard_spares_a_penalty` is
    the same record read for a penalty on the discarder."""
    if card is None:
        return None
    from .ai_standing import CARD_WORTH, life_worth
    from .handlers._filters import _card_matches_filter

    program = compile_card_oracle(card)
    roots = (
        tuple(program.instructions)
        + tuple(a.instruction for a in program.activated_abilities if a.instruction is not None)
        + tuple(t.instruction for t in program.triggered_abilities if t.instruction is not None)
    )

    def counted(instruction, payload):
        described = dict(payload["per_each"].get("filter") or {})
        amount = payload.get("amount")
        amount = amount if isinstance(amount, int) and not isinstance(amount, bool) else 0

        def matches(discarded, game, owner) -> bool:
            return bool(_card_matches_filter(discarded, described, game=game, owner=owner))

        def worth(game, cause_seat: int) -> float:
            if instruction.kind in _CAUSE_DRAW_KINDS:
                return CARD_WORTH * amount
            life = game.players[cause_seat].life
            return life_worth(life + amount) - life_worth(life)

        return DiscardPayoff(matches, worth)

    def typed(condition):
        types = tuple(str(each).lower() for each in condition.get("card_types") or ())
        if not types:
            return None
        every = condition.get("type_match") == "all"

        def matches(discarded, game, owner) -> bool:
            printed = set((discarded.type_line or "").lower().split("—")[0].split())
            held = [kind in printed for kind in types]
            return all(held) if every else any(held)

        return DiscardPayoff(matches, lambda game, cause_seat: 0.0)

    def walk(instructions):
        for instruction in instructions:
            payload = getattr(instruction, "payload", None) or {}
            each = payload.get("per_each")
            if (
                isinstance(each, dict) and each.get("recorded_cards") == "discarded_this_way"
                and instruction.kind in _CAUSE_GAIN_KINDS | _CAUSE_DRAW_KINDS
                and payload.get("recipient") == "caster"
            ):
                return counted(instruction, payload)
            condition = payload.get("condition") or {}
            if instruction.kind == "if_then" and condition.get("kind") == "discarded_this_way":
                found = typed(condition)
                if found is not None:
                    return found
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)):
                    found = walk(nested)
                    if found is not None:
                        return found
        return None

    return walk(roots)


__all__ = [
    "GRAVEYARD_DENIAL_KINDS",
    "chosen_color_sweeps",
    "chosen_creature_type_side",
    "color_most_worth_sweeping",
    "chosen_name_is_read_off_the_targets_library",
    "denied_graveyard_pile",
    "DiscardPayoff",
    "discard_pays_its_cause",
    "discard_spares_a_penalty",
    "exiled_search_pile_comes_back",
    "exiled_search_pile_comes_back_one_at_a_time",
    "exiles_a_graveyard_target",
    "graveyard_denial_order",
    "graveyard_price_order",
    "linked_exile_returns_to_battlefield",
    "reads_what_its_cost_exiled",
    "pick_is_taken_from_its_controller",
    "pick_is_tested_for_a_shared_color",
]
