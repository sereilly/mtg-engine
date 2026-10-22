"""A **value** chosen as an effect resolves: a number, a colour, a card type, a
creature type.

Each of these sentences produces a value and no effect of its own, and what
reads the value back is a separate sentence on the card — a
characteristic-defining ability (Shapeshifter's number), a static shield
(Chromatic Armor's colour), the next sentence of the same ability (Teferi's
Realm's card type) — so the value is recorded where that reader looks: on the
permanent, or in the resolution's scratchpad. The reading side is
``_chosen.py`` (a chosen word turned into filter keys); the card-name twin of
these handlers is ``naming.py``. Every choice goes on the pending-choice queue,
so an interactive seat is asked and every other seat takes a default the
handler computes.

Split out of ``control_flow.py`` at the 2,000-line cap's split round. They sat
beside the coin flip there, for the reason their docstrings give — a flip is a
value too — and the flip stayed, because the conditionals branch on it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..oracle_types import (CHOSEN_CARD_TYPE_THIS_WAY, CHOSEN_COLOR_THIS_WAY,
                            CHOSEN_NUMBER_THIS_WAY, SECRET_NUMBERS_BY_SEAT)
from ._chosen import CHOSEN_CARD_TYPE
from .offers import _offered_seats
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _most_telling_mana_value(game: Game, seat: int, low: int, high) -> int:
    """The number a seat that is not asked names for a spell's "choose a
    number": the mana value borne by the most nonland permanents its opponents
    control, net of its own, within the printed range. Ties go to the larger
    number; a board that offers nothing names the floor.

    A stated policy over public information (CR 400.2 — the battlefield),
    deliberately blind to hands: a number chosen by reading one would be the
    seat looking at hidden cards.
    """
    tally: dict[int, int] = {}
    for controller, permanent in game.permanents_with_controller():
        if permanent.has_type("land"):
            continue
        value = int(getattr(permanent.effective_card, "cmc", 0) or 0)
        if value < low or (high is not None and value > high):
            continue
        tally[value] = tally.get(value, 0) + (-1 if controller == seat else 1)
    if not tally:
        return low
    return max(tally, key=lambda value: (tally[value], value))


@effect_handler("choose_number")
def choose_number(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose a number between 0 and 7." (Shapeshifter.)

    Beside the coin flip for the same reason: it produces a *value* and no
    effect of its own, and what reads the value is a separate sentence on the
    card. The value is recorded on the permanent rather than in this
    resolution's scratchpad, because the sentence that reads it back is a
    characteristic-defining ability (CR 604.3) that keeps asking long after this
    resolution is over.

    The choice goes on the pending-choice queue, so an interactive controller is
    asked and every other seat takes the default the queue's resolver applies —
    which for a "you may" upkeep is *not changing the number*, the honest
    reading of declining the offer.

    **And into the resolution's scratchpad as well**, because a permanent is not
    the only kind of reader. "Choose a number greater than 0 and a color. …If
    that opponent reveals exactly **the chosen number** of cards of the chosen
    color, you draw a card." (Scrying Glass.) That reader is a later step of
    *this* resolution and asks once, so the permanent's standing answer is the
    wrong record for it twice over: the number this activation asked for is not
    necessarily the number the last one did, and the question is over before a
    permanent can be consulted again. Both records are written by this one step
    — the same discipline the colour handler below states — because a step that
    wrote only one of them would leave the other reader with nothing and no
    error, which is the shape this repo keeps finding.

    ``maximum`` may be None, which is a printed range with no ceiling ("greater
    than 0", CR 107.1) and not a missing bound. It travels as None to the prompt
    and to its resolver rather than being repaired into a number here: an
    invented ceiling is an answer the card would have accepted and the prompt
    would refuse.
    """
    permanent = context.source_permanent
    low = int(instruction.payload.get("minimum", 0))
    printed_high = instruction.payload.get("maximum")
    high = None if printed_high is None else int(printed_high)
    ceiling = instruction.payload.get("maximum_from_count")
    if ceiling is not None:
        # "Discard **any number** of cards at random." (Rites of Initiation.)
        # A number with no printed range: its ceiling is a count only the
        # resolution knows (the cards in the chooser's hand), and its reader is
        # the next step of this same resolution — so it is recorded in the
        # scratchpad alone, whatever the source is. A permanent's standing
        # ``chosen_number`` is a different record with a different reader, and
        # an ability printing this sentence must not overwrite it.
        if context.caster not in game.players:
            game.log.append(f"{context.card.name}: nobody to choose a number")
            return True, "resolved"
        seat = game.players.index(context.caster)
        from ._amounts import count_from_payload

        high = max(low, count_from_payload(game, context, dict(ceiling), instruction))
        # The policy for a seat nobody asks is the whole offer — the one
        # ``_default_discard`` states for the chosen form of this same
        # sentence ("discard any number of cards"), so the two spellings of
        # one decision default alike.
        context.results[CHOSEN_NUMBER_THIS_WAY] = high
        if high <= low:
            # One legal answer is not a choice, so nobody is asked.
            return True, "resolved"
        game.arm_pending_choice(
            "number_choice", seat,
            card_name=context.card.name if context.card is not None else "",
            permanent=None, minimum=low, maximum=high, default_number=high,
            result_key=CHOSEN_NUMBER_THIS_WAY, _context=context,
        )
        return True, "resolved"
    if permanent is None:
        # "Choose a number. Destroy all artifacts and creatures with mana value
        # equal to that number." (Void.) A *spell* choosing a number: there is
        # no permanent to keep a standing answer on and nothing reads one — the
        # only reader is a later step of this same resolution, which asks the
        # scratchpad. The same prompt, the same record, and the default a seat
        # that is not asked takes is the number that names the most of what the
        # other players control and the least of its own.
        if context.caster not in game.players:
            game.log.append(f"{context.card.name}: nobody to choose a number")
            return True, "resolved"
        seat = game.players.index(context.caster)
        default = _most_telling_mana_value(game, seat, low, high)
        # …unless the number is not a mana value at all. "Flip a coin **that
        # many times** or until you lose a flip" (Squee's Revenge): what the
        # value is for is the sentence behind the choice, read off the compiled
        # program where every such question is, and the length a seat nobody
        # asks takes is a weight beside it.
        from ..ai_prompt_readers import (FLIP_RUN_LENGTH,
                                         chosen_number_bounds_flip_run)

        if context.card is not None and chosen_number_bounds_flip_run(
            context.card, instruction
        ):
            default = max(low, FLIP_RUN_LENGTH if high is None else min(high, FLIP_RUN_LENGTH))
        context.results[CHOSEN_NUMBER_THIS_WAY] = default
        game.arm_pending_choice(
            "number_choice", seat,
            card_name=context.card.name if context.card is not None else "",
            permanent=None, minimum=low, maximum=high, default_number=default,
            result_key=CHOSEN_NUMBER_THIS_WAY, _context=context,
        )
        return True, "resolved"
    seat = game.controller_index_of(permanent)
    if seat is None:
        return True, "resolved"
    default = int(permanent.metadata.get("chosen_number", low))
    # Stamped **before** the prompt is armed, the discipline every other choice
    # in this file follows: a headless or AI seat is never blocked and the step
    # behind this always has a number to spend.
    context.results[CHOSEN_NUMBER_THIS_WAY] = default
    game.arm_pending_choice(
        "number_choice", seat,
        card_name=permanent.card.name, permanent=permanent,
        minimum=low, maximum=high,
        default_number=default,
        result_key=CHOSEN_NUMBER_THIS_WAY, _context=context,
    )
    return True, "resolved"


@effect_handler("secretly_choose_numbers")
def secretly_choose_numbers(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player hides at least one item, then all players reveal them
    simultaneously." (Goblin Game.)

    ``choose_number``'s value once per seat, with the one thing that handler
    cannot give it: **no seat's answer exists for anybody else until every
    seat has one.** One ``secret_number`` prompt per seat, armed together in
    turn order (CR 101.4); the prompt's resolver writes
    ``SECRET_NUMBERS_BY_SEAT`` and says nothing, and the answer that completes
    the map is what logs the reveal — one line, every number at once. CR 101.4b
    is the default this card's words set aside: ordinarily "a player knows the
    choices made by the previous players when making their choice", and
    "hides … reveal them simultaneously" is the sentence saying these are not
    known.

    Nothing is stamped before the prompts are armed, which is the opposite of
    the discipline ``choose_number`` states and for a reason: a provisional
    number is a number, and the sentences behind this one would lose life by
    it if anything let them run early. A seat nobody asks is answered where
    the prompt is armed (``default_at_arm``) by ``ai_prompts.choose_secret_number``,
    which reads life totals and never this map — so a seat the engine plays
    commits before any other answer exists and cannot be told one.

    The sentences behind this one wait for the last answer: the kind
    suspends, so the losses run once and against the whole map (CR 608.2).
    """
    low = max(0, int(instruction.payload.get("minimum", 0)))
    who = str(instruction.payload.get("who", "each_player"))
    seats = _offered_seats(game, who, context)
    card_name = context.card.name if context.card is not None else "Effect"
    # A fresh map per resolution: a copy of the spell, or the same ability
    # resolving twice, must not complete itself on the last one's answers.
    context.results[SECRET_NUMBERS_BY_SEAT] = {}
    if not seats:
        return True, "resolved"
    game.log.append(
        f"{card_name}: each {'opponent' if who == 'each_opponent' else 'player'} "
        f"secretly chooses a number of at least {low}"
    )
    for seat in seats:
        game.arm_pending_choice(
            "secret_number", seat,
            card_name=card_name, minimum=low, seats=list(seats),
            record=SECRET_NUMBERS_BY_SEAT, _results=context.results,
        )
    return True, "resolved"


@effect_handler("choose_color")
def choose_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose a color." (Chromatic Armor's activated ability.)

    Beside ``choose_number`` above and for the same reason: the sentence
    produces a *value* and no effect of its own, and what reads it back is a
    separate sentence on the card — here the Aura's static shield, which
    answers to "sources of the last chosen color". So the colour is recorded on
    the permanent rather than in this resolution's scratchpad, and "last" is
    what overwriting means.

    The same metadata key CR 614.1c's entry-state version writes: a card may
    print both (this one does), and two keys would be a permanent with two
    chosen colours and a shield reading whichever one its author remembered.

    Its **own prompt** rather than that version's, though, for the reason
    ``choose_card_type`` beside it states one characteristic over: a choice made
    while an ability resolves may be read back by a later step of the *same*
    resolution, so it has to hold that resolution open until it is answered.
    ``enter_choice`` does not suspend and must not start — its readers are
    continuous effects that re-read the record on every recompute, so a late
    answer there really does take effect. This one is ``color_choice``, and the
    two cards already in the pool lose nothing by the move: Chromatic Armor's
    choose is the last step of its ability, and Hall of Gemstone's mana swap
    follows the permanent rather than snapshotting its answer.

    **And the answer is recorded in the resolution's scratchpad as well**, which
    is what the second kind of reader asks. "…If that opponent reveals exactly
    the chosen number of cards of **the chosen color**, you draw a card."
    (Scrying Glass.) That reader runs once, inside this resolution, and asking a
    permanent for its standing answer would be asking about whichever activation
    last set it. One step writes both records, because a step that wrote only
    one of them would leave the other reader with nothing and no error.

    A deterministic default is stamped first — the colour of the opposing object
    on the stack this choice is answering (``ai_prompt_readers.threatening_color``),
    and failing one the colour the chooser's opponents hold most of among
    nontoken permanents, the policy the entry state applies — so a headless or
    AI seat is never blocked and never left with a colour nobody controls,
    which is a legal choice no player would make.
    """
    permanent = context.source_permanent
    card_name = getattr(context.card, "name", "an effect")
    chooser = instruction.payload.get("chooser")
    records_on = permanent
    # "Choose a color **of a permanent you control**." (Meteor Crater.) The
    # sentence narrows *which* colours may be named, so the set is computed
    # once the choosing seat is known (``_offered_colors`` below) and every
    # exit after that is held to it: an announced colour outside it is not an
    # answer, the default is one of its members, and the prompt offers nothing
    # else. None is CR 105.1's five.
    among = instruction.payload.get("among")
    offered: "tuple[str, ...] | None" = None
    if permanent is None or chooser == "you":
        # "Choose a color. X target creatures gain protection from the chosen
        # color until end of turn." (Prismatic Boon.) / "…gains protection from
        # **the color of your choice**" (Mother of Runes, Feat of Resistance —
        # the step ``_chosen_color_prelude`` puts in front of the grant.)
        # CR 109.5's "you": the controller of this spell or ability, which for
        # an activated one is the player who activated it rather than whoever
        # controls the permanent now.
        #
        # **Asked**, here, while the effect is applied (CR 608.2d). Both of
        # these used to read the colour off the announcement —
        # ``choices["new_color"]``, the wire field an any-colour *mana* ability
        # names its colour on — which CR 601.2b–c and 602.2b do not announce:
        # an interactive seat was never asked, an announcement without one did
        # nothing, and the player had to name the colour before the opponent
        # responded rather than after.
        #
        # The answer goes to this resolution's scratchpad alone. A spell has no
        # permanent to hold a standing record, and "the color of your choice" on
        # a permanent names a colour for this resolution's grant, not for a
        # continuous ability of the permanent's own (Chromatic Armor's shield is
        # what ``chosen_color`` is for) — a standing record would be a second,
        # staler answer, which is Wishmonger's reason below.
        if context.caster not in game.players:
            game.log.append(f"{card_name}: nobody to choose a colour")
            return True, "resolved"
        seat = game.players.index(context.caster)
        records_on = None
    else:
        seat = game.controller_index_of(permanent)
        # **A mana ability's choice is answered by its activation** (CR 605.3b).
        # "{T}: Choose a color. Add one mana of that color unless any player pays
        # {1}." (Rhystic Cave.) The ability resolves the moment it is activated, so
        # the colour its activator named with the activation *is* the choice CR
        # 608.2d asks for — the same channel every other colour a mana ability
        # makes already arrives on (``choices["new_color"]``, read by the "any
        # color", "{B} or {R}" and combination branches of ``add_mana_from_text``).
        # Stamped as ``color`` by the two sites that run a mana ability inline
        # (``mana_payment.answer_color_choices``), and only onto a choice the
        # controller makes, so nothing on the stack path is ever pre-answered.
        #
        # Without it the activator's named colour was ignored and the prompt's
        # deterministic default — the colour the *opponents* hold most of — was the
        # mana: an invented "{T}: Choose a color. Add one mana of the chosen
        # color." land asked for {R} made {W}.
        if among is not None and seat is not None:
            offered = _offered_colors(game, among, seat, permanent)
        announced = instruction.payload.get("color")
        if announced and not chooser and (
            offered is None
            or game._normalize_mana_color(str(announced)) in offered
        ):
            named = game._normalize_mana_color(str(announced))
            permanent.metadata["chosen_color"] = named
            context.results[CHOSEN_COLOR_THIS_WAY] = named
            game.log.append(
                f"{card_name}: {game.players[seat].name} chose {named}"
                if seat is not None else f"{card_name}: {named} chosen"
            )
            return True, "resolved"
    if chooser == "event_subject_player":
        # "At the beginning of each player's upkeep, **that player** chooses a
        # color." (Hall of Gemstone.) The seat the fire site froze (CR 603.10),
        # which is a different player every turn and never the enchantment's
        # controller except on their own turn. No record means the words named
        # nobody, and nothing is asked — the same rule every other reading of
        # this key follows, and the safe one.
        recorded = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(recorded, int) or not (0 <= recorded < len(game.players)):
            game.log.append(f"{card_name}: no recorded player to choose a colour")
            return True, "resolved"
        seat = recorded
    # "Target creature gains protection from the color of **its controller's**
    # choice until end of turn." (Wishmonger.) The third seat this sentence can
    # name, and the one that is not on either end of the ability: not the seat
    # that activated it — which is the ability's own controller and what "you"
    # would mean (CR 602.2a, CR 109.5) — and not the controller of the permanent
    # the ability is on, who under CR 602.2's "unless the object specifically
    # says otherwise" need not be the activator at all. The creature's
    # controller is asked, and CR 608.2d puts the question inside this
    # resolution — which is why the grant
    # is the *step behind* this one rather than a handler that arms its own
    # prompt: a prompt that suspends is answered after the handler that armed it
    # has returned.
    #
    # Through the same reader the grant resolves its own target with, over the
    # same ``targets`` description the lowering copies onto both steps: two
    # readings of one announcement is how a chooser and a grantee come apart.
    if chooser == "target_controller":
        from ._targets import resolve_target_permanent
        from .keywords import granted_target_legal

        chosen = resolve_target_permanent(
            game, context,
            predicate=granted_target_legal(game, instruction, context),
        )
        if chosen is None:
            game.log.append(f"{card_name}: no creature was chosen to choose a colour")
            return True, "resolved"
        seat = game.controller_index_of(chosen)
        # And **nothing standing is recorded**. ``chosen_color`` on a permanent
        # is the colour that permanent's own continuous ability keeps asking
        # about (Chromatic Armor's shield, Hall of Gemstone's mana swap); this
        # card has no such ability, and the source it would otherwise be written
        # on is the granting creature rather than the one being protected. The
        # scratchpad key below is the whole of the answer, and the step behind
        # it is its only reader.
        records_on = None
    if seat is None:
        return True, "resolved"
    if among is not None:
        if offered is None:
            offered = _offered_colors(game, among, seat, permanent)
        if not offered:
            # No permanent the phrase names has a colour, so there is no colour
            # to choose (CR 105.2c: colourless is the absence of one) and the
            # sentence behind this adds nothing. The slot is written **empty**
            # rather than left alone: "that color" must not read a colour some
            # earlier resolution of the same context chose.
            context.results[CHOSEN_COLOR_THIS_WAY] = None
            game.log.append(f"{card_name}: there is no color to choose")
            return True, "resolved"
        if len(offered) == 1:
            # One colour on offer is not a question (CR 608.2d asks for a
            # choice only where there is one to make).
            if records_on is not None:
                records_on.metadata["chosen_color"] = offered[0]
            context.results[CHOSEN_COLOR_THIS_WAY] = offered[0]
            game.log.append(
                f"{card_name}: {game.players[seat].name} chose {offered[0]}"
            )
            return True, "resolved"
    from ..ai_prompt_readers import (color_most_worth_sweeping,
                                     threatening_color)

    default_color = None
    if offered is None:
        # "Destroy all enchantments **of the color of your choice**" (Root
        # Greevil; Wash Out; Dromar, the Banisher): the colour is for the
        # sweep behind this step, so the default is the colour that sweep is
        # worth most in — what it would take from the other seats, less what
        # it would take from this one. The board-wide count below named the
        # colour of an opposing army and destroyed no enchantment.
        source = context.source_permanent
        default_color = color_most_worth_sweeping(
            game, seat, getattr(source, "effective_card", None) or context.card
        ) or threatening_color(game, seat)
    if offered is not None:
        # The first colour on offer, in WUBRG order: a deterministic member of
        # the set, where the unnarrowed default below is a colour the
        # *opponents* hold — which this sentence may not let anyone name.
        default_color = offered[0]
    if default_color is None:
        counts: dict[str, int] = {}
        for other in range(len(game.players)):
            if other == seat or game.players[other].lost:
                continue
            for perm in game.controlled_by(other):
                if perm.metadata.get("is_token"):
                    continue
                for color in game._effective_colors(perm):
                    counts[color] = counts.get(color, 0) + 1
        default_color = max(sorted(counts), key=lambda c: counts[c]) if counts else "W"
    if records_on is not None:
        records_on.metadata["chosen_color"] = default_color
    context.results[CHOSEN_COLOR_THIS_WAY] = default_color
    game.arm_color_choice(
        seat,
        card_name=card_name, permanent=records_on,
        result_key=CHOSEN_COLOR_THIS_WAY, context=context,
        default=default_color,
        colors=offered,
    )
    game.log.append(f"{card_name}: {game.players[seat].name} chooses a color")
    return True, "resolved"


@effect_handler("recall_chosen_color")
def recall_chosen_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…protection from **the chosen color**" where no sentence of the effect
    chose one: the colour the ability's source chose as it entered
    (CR 614.1c), copied into the slot ``choose_color`` writes so the step
    behind reads one record whichever way the colour came.

    "Sacrifice this Aura: Target creature gains protection from the chosen
    color until end of turn." (Floating Shield.) The Aura is sacrificed to pay
    for the ability, so by resolution it is in a graveyard and the colour is
    read off it **as it last existed** on the battlefield (CR 608.2h, 113.7a)
    — the ``Permanent`` the activation recorded as its source, whose entry
    record leaving the battlefield does not erase.

    Written **empty** where the source has no record (it never entered, or
    its text asks nothing as it enters), for ``choose_color``'s reason: the
    reader behind must not find a colour an earlier resolution of the same
    context chose, and protection from a colour nobody named is a protection
    the card never gave.
    """
    from ..entry_choices import CHOSEN_COLOR_KEY

    source = context.source_permanent
    chosen = (getattr(source, "metadata", None) or {}).get(CHOSEN_COLOR_KEY)
    context.results[CHOSEN_COLOR_THIS_WAY] = chosen or None
    if not chosen:
        game.log.append(
            f"{getattr(context.card, 'name', 'An effect')}: its source chose no color"
        )
    return True, "resolved"


def _offered_colors(game: Game, among: dict, seat: int, source) -> tuple[str, ...]:
    """The colours a narrowed "choose a color of <permanents>" offers *seat*.

    ``object_colors.colors_among_described`` — the layers' colours over the set
    the one subject matcher admits — so the handler, the payment planner and
    the client's colour picker (``mana_could_produce.ability_colors_on_offer``)
    are one reading of the phrase.
    """
    from ..object_colors import colors_among_described

    return colors_among_described(game, among, observer=seat, source=source)


@effect_handler("choose_card_type")
def choose_card_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"At the beginning of each player's upkeep, that player chooses artifact,
    creature, land, or non-Aura enchantment." (Teferi's Realm.)

    ``choose_color``'s sibling one characteristic over, and written the same
    way for the same reasons: the sentence produces a value and no effect, the
    value is recorded on the ability's own source (which is where the next
    sentence of the same ability looks for it), and a deterministic default is
    stamped **first** so a headless or AI seat is never blocked.

    The default is the option that would phase out the most of the *chooser's
    opponents'* nontoken permanents — a real answer rather than the first item,
    because the first item is a choice no player would make when a better one is
    on the list, and the card is one a seat faces every upkeep.

    The options come from the printed sentence rather than from the card-type
    catalog: the prompt is bounded by what the card offered, and a player who
    could answer "instant" would name a type no permanent has.
    """
    permanent = context.source_permanent
    card_name = getattr(context.card, "name", "an effect")
    options = [str(word) for word in (instruction.payload.get("options") or ())]
    if not options:
        game.log.append(f"{card_name}: no options were printed to choose from")
        return True, "resolved"
    if permanent is None:
        # "Choose artifact, creature, or land. Tap all untapped permanents of
        # the chosen type…" (Turnabout.) A **spell**'s choice, which has no
        # permanent to be recorded on and needs none: the sentence that reads it
        # back is the next step of this same resolution, and CR 608.2d puts both
        # of them in it. The word goes to the resolution scratchpad — the
        # channel ``choose_creature_type`` and ``choose_color`` already use for
        # the identical question one characteristic over.
        #
        # The default is stamped **before** the prompt is armed, exactly as the
        # permanent branch below stamps its own: a headless or AI seat is never
        # blocked, and the sweep behind this always has an answer to spend.
        if context.caster not in game.players:
            game.log.append(f"{card_name}: nobody to choose a type")
            return True, "resolved"
        seat = game.players.index(context.caster)
        default = _fewest_own_permanents_type(game, seat, options)
        context.results[CHOSEN_CARD_TYPE_THIS_WAY] = default
        game.arm_pending_choice(
            "card_type_choice", seat,
            card_name=card_name, options=list(options),
            default_card_type=default,
            result_key=CHOSEN_CARD_TYPE_THIS_WAY, _context=context,
        )
        game.log.append(
            f"{card_name}: {game.players[seat].name} chooses a type "
            f"({', '.join(options)})"
        )
        return True, "resolved"
    seat = game.controller_index_of(permanent)
    if instruction.payload.get("chooser") == "event_subject_player":
        # The seat the fire site froze (CR 603.10) — a different player every
        # upkeep, and never the enchantment's controller except on their own
        # turn. No record means the words named nobody and nothing is asked,
        # which is the rule every other reading of this key follows.
        recorded = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(recorded, int) or not (0 <= recorded < len(game.players)):
            game.log.append(f"{card_name}: no recorded player to choose a type")
            return True, "resolved"
        seat = recorded
    if seat is None:
        return True, "resolved"
    default = _fewest_own_permanents_type(game, seat, options)
    permanent.metadata[CHOSEN_CARD_TYPE] = default
    game.arm_pending_choice(
        "card_type_choice", seat,
        card_name=permanent.card.name, permanent=permanent,
        options=list(options), default_card_type=default,
    )
    game.log.append(
        f"{card_name}: {game.players[seat].name} chooses a type "
        f"({', '.join(options)})"
    )
    return True, "resolved"


@effect_handler("choose_creature_type")
def choose_creature_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Destroy all creatures **of the creature type of your choice**."
    (Extinction.)

    ``choose_card_type``'s sibling one catalog over, with one difference that
    changes where the answer goes: this card is a **sorcery**, so there is no
    source permanent to record on and no permanent for a later turn to read.
    The word lives in the resolution scratchpad and is spent by the next step of
    the same sentence, which is what ``result_key`` names.

    The default is stamped **first**, so a headless or AI seat is never blocked
    and the sweep behind this always has an answer. It is a real one rather than
    the first catalog entry: the type that kills the most of the chooser's
    opponents' creatures and the fewest of their own, which is the choice a
    player would make. ``None`` when no creature is on the battlefield at all —
    and the sweep reads that as destroying nothing, never as destroying
    everything.
    """
    key = str(instruction.payload["result_key"])
    context.results[key] = None
    card_name = getattr(context.card, "name", "an effect")
    if context.caster not in game.players:
        game.log.append(f"{card_name}: nobody to choose a creature type")
        return True, "resolved"
    seat = game.players.index(context.caster)
    # "Choose a creature type **other than Wall**." (Unnatural Selection.) The
    # printed exclusion, applied to all three places a type can come from: the
    # default stamped here, the list the prompt offers and the answer the
    # resolver accepts (``arm_creature_type_choice`` carries it to the last
    # two). Absent for every other card, whose default and prompt are
    # byte-identical to what they were.
    excluded = tuple(
        str(word).strip().lower()
        for word in (instruction.payload.get("excluded") or ())
    )
    default = _best_creature_type_to_sweep(game, seat, excluded=excluded)
    context.results[key] = default
    game.arm_creature_type_choice(
        seat, card_name=card_name, result_key=key, context=context,
        default=default, excluded=excluded,
    )
    game.log.append(
        f"{card_name}: {game.players[seat].name} chooses a creature type"
        + (f" other than {', '.join(word.title() for word in excluded)}" if excluded else "")
    )
    return True, "resolved"


def _best_creature_type_to_sweep(
    game: Game, seat: int, excluded: tuple[str, ...] = (),
) -> str | None:
    """The creature type a sweep would most like to name, from *seat*'s side.

    The type maximising (opponents' creatures of it − own creatures of it), ties
    broken by the alphabetically first word, which keeps the answer
    deterministic — the property the AI-simulation regressions depend on.

    Only types actually on the battlefield are considered, and ``None`` comes
    back when there are none. Naming a type nothing has would be an answer that
    reads as a choice and destroys nothing; ``None`` says outright that no
    choice was made, which is what the sweep behind this checks.

    The subtypes are read through the CR 613 accessor, so a creature Artificial
    Evolution or an animated land has become a Zombie counts as one.

    *excluded* is a printed "other than <type>": a word in it is never the
    answer, so the default is one the resolver would accept. Only **creature**
    types are scored — an animated Forest's "forest" is a subtype of the
    permanent and no answer to "choose a creature type".
    """
    from ..grammar.vocabulary import CREATURE_TYPES
    from ..layer_bridge import computed_types

    scores: dict[str, int] = {}
    for owner, perm in game.permanents_with_controller():
        if not perm.is_creature:
            continue
        for subtype in computed_types(perm)[1]:
            word = str(subtype).lower()
            if word in excluded or word not in CREATURE_TYPES:
                continue
            scores[word] = scores.get(word, 0) + (-1 if owner == seat else 1)
    if not scores:
        return None
    return max(sorted(scores), key=lambda word: scores[word])


def _fewest_own_permanents_type(game: Game, seat: int, options: list[str]) -> str:
    """The offered option that costs *seat* least and their opponents most.

    Teferi's Realm phases out **every** nontoken permanent of the chosen type,
    the chooser's included, so the choice is a real one: the option maximising
    (opponents' permanents − own permanents). Ties keep the printed order, which
    keeps the answer deterministic — the property the AI-simulation regressions
    depend on.
    """
    from ..subject_filters import subject_matches
    from ._chosen import chosen_card_type_filter

    best, best_score = options[0], None
    for word in options:
        described = chosen_card_type_filter(word)
        if described is None:
            continue
        described = {**described, "nontoken": True}
        score = 0
        for other in range(len(game.players)):
            if game.players[other].lost:
                continue
            hit = sum(
                1 for perm in game.controlled_by(other)
                if subject_matches(game, perm, described, observer=other)
            )
            score += -hit if other == seat else hit
        if best_score is None or score > best_score:
            best, best_score = word, score
    return best
