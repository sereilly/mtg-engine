"""Searching (CR 701.23): a hidden pile looked through for what a sentence
describes.

The handler twin of ``engine/grammar/lowering/search.py``.
:func:`search_library` arms the one ``search_library`` prompt every library
search uses, with the restrictions only a resolution can answer resolved first
(:func:`_search_restrictions`). Beside it, the searches with more to them:
Transmute Artifact's sacrifice, search and optional payment
(:func:`transmute_by_sacrifice` and the "held" card it places), the strips that
search a player's zones for every card with a name and exile them (Lobotomy),
and Chandra, Heart of Fire's −9.

Split out of ``zones.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..faces import has_name
from ..models import Permanent
# The runtime class. The bare name is a TYPE_CHECKING-only import below, and
# the handlers here *build* instructions for an optional payment's branches.
from ..oracle_types import OracleInstruction as _OracleInstruction
from ..resumption import run_resumable
from ._targets import resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _search_restrictions(game: Game, payload: dict, context) -> dict:
    """The armed search's restrictions, with the ones only a resolution can
    answer resolved.

    ``named_from_target`` is "a card **with the same name as target nontoken
    creature**" (Mask of the Mimic): the name is the chosen target's, which is
    not knowable when the card compiles. It is turned into an ordinary ``named``
    here, so every seat answers the same search — the engine re-checking a
    pick, the AI choosing for itself and the web picker offering a list all read
    ``search_filters.search_matches`` and none of them has a target in hand.

    A target that is gone by resolution (CR 608.2b removes it) leaves the key in
    place and no name behind it, and ``search_matches`` then matches nothing:
    the search finds no card rather than every card, which is the direction a
    dropped narrowing must never fail in.
    """
    restrictions = dict(payload.get("restrictions") or {})
    # "…a creature card with mana value **X** or less" (Citanul Flute). CR
    # 601.2b fixed X when the activation cost was paid, so by now it is a
    # number — resolved here, once, because every seat that answers this search
    # reads the armed restrictions and none of them has the activation in hand.
    # A symbol left in the payload would reach ``search_matches``' comparison
    # and be compared against a card's mana value as a string.
    mana_value = restrictions.get("mana_value")
    if isinstance(mana_value, dict) and mana_value.get("value") == "x":
        restrictions["mana_value"] = {
            **mana_value, "value": max(0, int(context.x_value or 0)),
        }
    # "…a card **with the same name as that creature**" (Remembrance). The name
    # of the object the firing event was about, turned into an ordinary
    # ``named`` here for ``named_from_target``'s reason one branch down: every
    # seat that answers this search reads the armed restrictions, and none of
    # them has a trigger context in hand.
    #
    # Off ``dead_card`` rather than off ``dead_name``, because that is the
    # channel every fire site in ``BOUND_CARD_EVENTS`` writes — the graveyard
    # arrival records the card and no name at all. A record nothing wrote leaves
    # the key in place with no name behind it, and ``search_matches`` then
    # matches nothing: the search finds no card rather than every card, which is
    # the direction a dropped narrowing must never fail in.
    if restrictions.get("named_from_event"):
        recorded = (context.trigger_context or {}).get("dead_card")
        name = getattr(recorded, "name", None)
        if name is not None:
            restrictions["named"] = name
    # "…a card **with the same name as that card**" (Assembly Hall). The name of
    # a card an earlier step of *this same effect* turned face up, read out of
    # the resolution's own scratchpad under the key the lowering named — the
    # third referent this function resolves, and it goes through the same
    # ``named`` for the two above's reason: every seat that answers this search
    # reads the armed restrictions, and none of them has the scratchpad.
    #
    # The record is a list (a reveal may turn up several), and the name is the
    # first entry's: the sentence says "that **card**", singular, and the only
    # printing of it reveals exactly one. A record that is empty — nothing was
    # revealed, because the hand held no card the phrase admits — leaves the key
    # in place with no name behind it, and ``search_matches`` then matches
    # nothing: the search finds no card rather than every card.
    record_key = restrictions.get("named_from_record")
    if record_key:
        revealed = context.results.get(str(record_key)) or ()
        first = next(iter(revealed), None)
        name = getattr(first, "name", None)
        if name is not None:
            restrictions["named"] = name
    if not restrictions.get("named_from_target"):
        return restrictions
    # Through the seam every handler resolves a chosen permanent by, so the
    # name read here is the object the announcement named -- an index alone
    # renumbers the moment anything leaves the battlefield, and the sacrifice
    # this card charges as an additional cost has already left one.
    chosen = resolve_target_permanent(game, context)
    if chosen is not None:
        # The **effective** name (CR 707.2 puts name first among the copiable
        # values): "the same name as target creature" aimed at a Clone copying
        # Grizzly Bears is a search for Grizzly Bears. The printed face read
        # here made Mask of the Mimic and Pack Hunt search for "Clone".
        restrictions["named"] = chosen.effective_card.name
    return restrictions


@effect_handler("search_library")
def search_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    caster_index = game.players.index(caster)
    # The zones the search may look in and the restriction on what it may find
    # both travel to the choice, so every seat answers the same search: the
    # engine re-checks the answer against them, the AI picks within them, and
    # the web layer offers them. Defaulting to the library alone keeps a
    # payload written before the graveyard existed meaning what it meant.
    zones = tuple(instruction.payload.get("zones", ("library",)))
    # "…from **its owner's** graveyard … under the control of **that
    # creature's owner**." (Reincarnation.) Whose zone is looked in and whose
    # battlefield receives are two questions, and neither is "the seat that
    # chooses" — CR 608.2c makes the chooser the ability's controller. Both
    # ride as seats so the picker, the AI and the resolver read one answer;
    # absent, they default to the chooser, which is every other card.
    seats: dict[str, int] = {}
    for key, payload_key in (
        ("zone_seat", "zone_owner"), ("battlefield_seat", "battlefield_owner"),
    ):
        named = instruction.payload.get(payload_key)
        if named is None:
            continue
        # Two places a named seat can come from, asked in the order they are
        # decided. A loop over the objects an earlier step recorded resolves its
        # per-object records for the iteration in progress — Glyph of
        # Reincarnation's "the graveyard of the player who controlled that
        # creature the last time it became blocked by that Wall". Outside a loop
        # there is only the trigger's own captured context. One lookup rather
        # than a payload flag saying which to consult, because the two never
        # both answer: a loop binding exists only inside its loop.
        seat = context.iteration_seats.get(str(named))
        if seat is None:
            seat = (context.trigger_context or {}).get(str(named))
        if seat is None:
            # The trigger that would have recorded it did not: CR 603.10's
            # last-known information is simply absent, so the effect falls back
            # to its controller rather than guessing a seat.
            continue
        seats[key] = int(seat)
    # "Search **target player's** library …" (Jester's Cap, Jester's Mask). The
    # seat is the ability's own target rather than a record an earlier trigger
    # wrote, so it is asked here and not through the loop above — a chosen
    # target is not something the trigger context holds. Whose battlefield or
    # hand receives follows it by default (`search_filters.landing_seat`), which
    # is what makes "that player puts those cards into their hand" land in the
    # searched player's hand and not the searcher's.
    if instruction.payload.get("zone_owner_target") and context.target is not None:
        if context.target in game.players:
            seats["zone_seat"] = game.players.index(context.target)
    # "…put that card onto the battlefield **under your control**." (Bribery.)
    # CR 110.2a's controller, and the one seat neither of the two readings above
    # can supply: it is not a record a trigger wrote and it is not the seat whose
    # library was opened — it is the ability's own controller, which is exactly
    # the seat ``landing_seat`` stops defaulting to the moment ``zone_seat`` is
    # set. Read after that block for that reason: written the other way round,
    # the searched player's seat would overwrite it and the creature would enter
    # on the side it came from.
    if instruction.payload.get("battlefield_under_caster"):
        seats["battlefield_seat"] = caster_index
    # "…for **that many** cards" — the number an earlier step of this same
    # resolution recorded (Jester's Mask's emptied hand). Read here rather than
    # baked into the payload, because the count is a fact about the board.
    counted_from = instruction.payload.get("amount_from")
    printed_count = instruction.payload.get("count", 1)
    if counted_from is not None:
        count = max(0, int(context.results.get(counted_from, 0) or 0))
    elif printed_count == "any":
        # "…for **any number of** Goblin cards" (Goblin Recruiter). CR 701.23a:
        # a search looks at every card in the zone, so the only ceiling is how
        # many of them the phrase admits — counted here, where the zones and the
        # seat are known, rather than baked into a payload that would then be a
        # printed ceiling the card does not have.
        #
        # It is a ceiling on the *slots*, not a promise: `up_to` rides with it,
        # so finding fewer (none included) stays a legal answer.
        from ..search_filters import search_matches
        searched_seat_index = seats.get("zone_seat", caster_index)
        looked_in = game.players[searched_seat_index]
        pool = [
            card
            for zone_name in zones
            for card in (
                looked_in.library if zone_name == "library" else looked_in.graveyard
            )
        ]
        count = sum(
            1 for card in pool
            if search_matches(
                card, instruction.payload, game=game, owner=caster_index,
            )
        )
    elif printed_count == "x":
        # "…for up to **X** basic land cards" (New Frontiers): the X the spell
        # was cast with (CR 107.3a), read where every other X is.
        count = max(0, int(context.x_value or 0))
    else:
        count = int(printed_count)
    destinations = list(instruction.payload.get("destinations") or ())
    tapped = list(instruction.payload.get("tapped") or ())
    if not destinations and count > 1:
        # A search for several cards that all go to one place (Jester's Cap's
        # three exiles). The counted flow is driven by one entry per find, so
        # the list is built here where the number is known — Cultivate's
        # printing carries its own, because its finds go to different places.
        destinations = [instruction.payload.get("destination", "hand")] * count
        # …and one entry state per find, for the search whose number the card
        # did not print: "put them onto the battlefield **tapped**" says it
        # once for however many there are, and the counted flow reads a flag
        # per slot. A list the lowering sized (Cultivate) is left as printed.
        if not tapped and instruction.payload.get("enters_tapped"):
            tapped = [True] * count
    computed = counted_from is not None or printed_count == "x"
    # "…for X cards" at an X of zero (Insidious Dreams) is the same search for
    # no cards whether or not it printed "up to": the floor it carries
    # (CR 701.23d) is X, and X is nothing.
    if computed and count <= 0 and (
        instruction.payload.get("up_to") or printed_count == "x"
    ):
        # "…for **up to** X basic land cards" with X = 0 (New Frontiers), or
        # "up to that many" after nothing was discarded (Rites of Spring). A
        # search for up to no cards is still a search: the library is looked
        # through, nothing can be found, and the shuffle that ends it still
        # happens — CR 701.23c's situation ("that player may still search that
        # zone but can't find any cards"), and CR 701.23g lets a player take
        # an offered search whose finds are impossible. So it is the
        # fail-to-find without the prompt: there is no card a seat could name.
        searched = game.players[seats.get("zone_seat", caster_index)]
        if "library" in zones:
            random.shuffle(searched.library)
        whose = "their" if searched is caster else f"{searched.name}'s"
        ceiling = "up to " if instruction.payload.get("up_to") else ""
        game.log.append(
            f"{caster.name} searched {whose} library for {ceiling}0 cards and shuffled"
        )
        return True, "resolved"
    if counted_from is not None and count <= 0:
        game.log.append(
            f"{context.card.name}: nothing was recorded to search for"
        )
        return True, "resolved"
    game.arm_pending_choice(
        "search_library", caster_index,
        **seats,
        count=count,
        card_type=instruction.payload.get("card_type", "any"),
        zones=zones,
        restrictions=_search_restrictions(game, instruction.payload, context),
        destination=instruction.payload.get("destination", "hand"),
        # "…put one onto the battlefield tapped and the other into your hand"
        # (Cultivate): one entry per find, in the printed order. A counted
        # search is answered whole — every find in one pick list — and which
        # find fills which slot is then its own question, asked through the
        # `search_destination` prompt when the slots differ.
        destinations=destinations,
        tapped=tapped,
        # The searching card's name, for the prompts' labels — data, not
        # dispatch.
        card_name=context.card.name if context.card is not None else "",
        # The single-find spelling of the same fact, plus the conditional untap
        # rider that rides with it (Fabled Passage) — both belong to the search
        # rather than to a later sentence, because they are about the card it
        # finds.
        enters_tapped=bool(instruction.payload.get("enters_tapped")),
        untap_found_if=instruction.payload.get("untap_found_if"),
        up_to=bool(instruction.payload.get("up_to")),
        # "…and exile the rest." (Doomsday.) What happens to the searched piles
        # once the finds are out of them. It rides to the prompt like the zones
        # and the restriction do, because the seat that answers is the seat
        # whose zones are emptied and the answer is what says which cards
        # survive.
        exile_rest=bool(instruction.payload.get("exile_rest")),
        # "…, reveal it/those cards, …" (CR 701.20): the finds are shown to
        # every player, which the resolution records as one reveal event when
        # the search ends. A search that does not print the word shows nothing.
        reveal=bool(instruction.payload.get("reveal")),
        # The resolution's own scratchpad, so the search can write down what it
        # put onto the battlefield: "…put that card onto the battlefield, then
        # shuffle. **That Dragon** gains haste" (Zirilan of the Claw) names it,
        # and the search suspends on a prompt — by the time the sentence behind
        # it runs, the card is one permanent among many. Handed over here
        # because this is where the resolution and the prompt meet.
        record=context.results,
        # …and **under which key**, for a search whose finds are held rather
        # than placed (Intuition). Every other record this prompt writes is a
        # fact about the search itself and has one name; a held pile is a value
        # the *next sentence* reads, so the sentence that reads it is what names
        # the channel. Absent for every search written before this one.
        record_key=instruction.payload.get("record_key"),
    )
    # Whose zone, not the chooser's, because they are not always the same seat.
    searched = game.players[seats.get("zone_seat", caster_index)]
    game.log.append(
        f"{caster.name} is searching "
        + ("their " if searched is caster else f"{searched.name}'s ")
        + " and ".join(zones)
    )
    return True, "pending_search_library"


@effect_handler("place_held_card")
def place_held_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Put the card a "held" search found where a later step decided.

    Its own instruction kind because it is what the branches of Transmute
    Artifact's optional payment *are*: the `may` machinery runs instruction
    lists, so "put it onto the battlefield" and "put it into its owner's
    graveyard" have to be instructions rather than closures.
    """
    card = context.results.get("found_card")
    if card is None:
        return True, "resolved"
    context.results["found_card"] = None
    seat = game.players.index(context.caster)
    destination = str(instruction.payload.get("destination", "battlefield"))
    if destination == "battlefield":
        game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
        game.log.append(f"{card.name} enters the battlefield")
        return True, "resolved"
    # CR 400.3: a card put into a graveyard goes to its **owner's**, and the
    # only owner a library card can have is the player whose library it was.
    game.put_card_into_graveyard(seat, card, from_zone="library")
    game.log.append(f"{card.name} is put into its owner's graveyard")
    return True, "resolved"


@effect_handler("transmute_by_sacrifice")
def transmute_by_sacrifice(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Transmute Artifact's whole effect.

    Three decisions in a row, each one shaping the next: what to give up, what
    to look for, and — only when the find costs more than what went — whether to
    pay the difference. So the steps run through ``run_resumable``: the first two
    suspend on a prompt, and the work behind each is recorded rather than run
    against an answer nobody has given yet.

    Every piece is the engine's existing machinery. The sacrifice is the
    standing forced-sacrifice prompt, told to record what it took (CR 608.2h —
    by the time the comparison runs the artifact is a card in a graveyard, and a
    different object); the search is the standing library search with the find
    *held* rather than placed, because where it goes is the next step's
    decision; and the payment is the ordinary optional-pay entry whose accept
    and decline branches are the two placements the card prints.
    """
    caster = context.caster
    seat = game.players.index(caster)
    results = context.results

    def _sacrifice(_step) -> None:
        game.arm_forced_sacrifice(
            seat, 1,
            filter=dict(instruction.payload.get("sacrifice_filter") or {}),
            reason=context.card.name if context.card is not None else "Transmute",
            record=results,
        )

    def _search(_step) -> None:
        given = list(results.get("sacrificed_cards") or ())
        if not given:
            # "**If you do**" — nothing was given up, so nothing follows.
            game.log.append(f"{context.card.name}: nothing was sacrificed")
            return
        game.arm_pending_choice(
            "search_library", seat,
            count=1,
            card_type=(instruction.payload.get("search_filter") or {}).get(
                "type_filter", "any"
            ),
            zones=("library",),
            restrictions={},
            destination="held",
            destinations=[],
            tapped=[],
            card_name=context.card.name if context.card is not None else "",
            enters_tapped=False,
            untap_found_if=None,
            up_to=False,
            reveal=False,
            record=results,
        )

    def _place(_step) -> None:
        card = results.get("found_card")
        given = list(results.get("sacrificed_cards") or ())
        if card is None or not given:
            return
        paid_for = int(getattr(given[0], "cmc", 0) or 0)
        wanted = int(getattr(card, "cmc", 0) or 0)
        if wanted <= paid_for:
            game._execute_oracle_instruction(
                _OracleInstruction("place_held_card", "", {"destination": "battlefield"}),
                context,
            )
            return
        # "If it's greater, you may pay {X}, where X is the difference." The
        # number is the difference and nothing else, so it is computed here
        # rather than asked for — CR 107.3 lets a cost name a value the effect
        # fixes.
        difference = wanted - paid_for
        game.arm_pending_choice(
            "optional_pay", seat,
            card_name=context.card.name if context.card is not None else "",
            cost={"generic": difference},
            life=0,
            _source_permanent=context.source_permanent,
            _on_accept=(
                _OracleInstruction("place_held_card", "", {"destination": "battlefield"}),
            ),
            _on_decline=(
                _OracleInstruction("place_held_card", "", {"destination": "graveyard"}),
            ),
            _on_reflexive=(),
            _context=context,
            prompt=f"Pay {{{difference}}}?",
        )

    run_resumable(game, [_sacrifice, _search, _place], lambda step: step(None))
    return True, "resolved"


@effect_handler("strip_cards_with_chosen_name")
def strip_cards_with_chosen_name(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Search that player's graveyard, hand, and library for all cards with the
    same name as the chosen card and exile them. Then that player shuffles."
    (Lobotomy.)

    …and "Exile target nonblack creature. Search **its controller's** graveyard,
    hand, and library for all cards with the same name as **that creature** and
    exile them. Then that player shuffles." (Eradicate, Scour, Splinter, Sowing
    Salt; Quash prints it behind a counter.) One handler because it is one
    effect: three zones walked in the printed order, every copy of one name
    exiled, and the library shuffled at the end. What differs is only where the
    name and the seat are read from, which the lowering settles into two payload
    keys — see the branch below.

    The **decomposed** half of Necromentia's paragraph. That card fuses the
    naming, the strip and a token clause into one handler because its last
    sentence counts a pile only that handler holds; this one has nothing behind
    it, so the naming is the step in front and this is the strip alone — reading
    the name out of the resolution's scratchpad, which is where every "the
    chosen card" in this engine is written.

    CR 701.23c is about this card by name: with an empty hand nothing was
    chosen, so the quality is undefined, the searcher still searches and finds
    nothing. An unrecorded name is exactly that case and is **not** treated as
    "match everything" — the whole library would go to exile, which is the
    opposite of what an empty choice means.

    The zones are walked in the printed order and only the library is shuffled
    (CR 701.24): a graveyard is an open zone and a hand is its owner's, and
    randomising either would be a move the sentence does not describe.
    """
    # Which two records this sentence reads, or neither. Lobotomy names the
    # seat it searched outright and reads the name out of ``chosen_card_name``;
    # Eradicate and its four siblings name *both* off the step in front of them
    # — "its controller's" zones, "that creature's" name — and the lowering
    # says which pair, because only it knows what an exile, a destroy or a
    # counter leaves behind.
    name_record = instruction.payload.get("name_record")
    seat_record = instruction.payload.get("seat_record")
    names_record = instruction.payload.get("names_record")
    if names_record is not None:
        # "For each card exiled this way, search that player's library for all
        # cards with the same name as that card and exile them." (Haunting
        # Echoes.) The third place a name is read from, and the one that is a
        # *pile*: every card the sweep in front of this step exiled.
        return _strip_by_recorded_cards(
            game, instruction, context, str(names_record)
        )
    if name_record is not None:
        seat = context.results.get(seat_record)
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            # The step in front chose nothing — its target had left (CR 608.2b)
            # — so there is no object for "its controller" or "that creature" to
            # name and nothing to search. Not a search that finds everything:
            # an unrecorded seat would otherwise fall through to the resolving
            # spell's own target, which for these five is the permanent or the
            # spell rather than a player.
            game.log.append(
                f"{context.card.name}: nothing was chosen, so no zones are searched"
            )
            return True, "resolved"
        target = game.players[seat]
        named = str(context.results.get(name_record) or "").strip()
    else:
        target = context.target
        if target is None or target not in game.players:
            game.log.append(f"{context.card.name}: no player to search")
            return True, "resolved"
        named = str(context.results.get("chosen_card_name") or "").strip()
    zones = tuple(instruction.payload.get("zones") or ())
    if not named:
        # The pick chose nothing (an empty hand, or a hand of nothing but basic
        # lands). The search still happens and finds nothing, which CR 701.23c
        # spells out on this very card.
        game.log.append(
            f"{context.card.name}: nothing was chosen, so nothing is exiled"
        )
        if "library" in zones:
            random.shuffle(target.library)
        return True, "resolved"
    taken: list[str] = []
    for zone in zones:
        cards = getattr(target, zone, None)
        if cards is None:
            continue
        # ``has_name`` (CR 709.4a): "an object has the chosen name if one of
        # its names is the chosen name", and a split card in a hand, a library
        # or a graveyard has two.
        kept = [card for card in cards if not has_name(card, named)]
        found = [card for card in cards if has_name(card, named)]
        if found:
            cards[:] = kept
            target.exile.extend(found)
            taken.extend(card.name for card in found)
    if "library" in zones:
        random.shuffle(target.library)
    game.log.append(
        f"{target.name} lost {len(taken)} copies of {named} to "
        f"{context.card.name}"
    )
    return True, "resolved"


def _strip_by_recorded_cards(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext,
    record: str,
) -> tuple[bool, str]:
    """The strip by **every name a step of this effect recorded**.

    One walk of the zones for the whole pile, and one shuffle (CR 701.24): the
    cards that leave are those sharing a name with any recorded card
    (CR 201.2a — at least one name in common, so a split card matches by
    either half and both ways). The recorded cards themselves are already in
    exile; nothing here looks at them again but for their names.

    "That player" is the seat the sentence in front targeted, read off the
    resolution as the Lobotomy branch reads it. An empty record — the sweep
    exiled nothing — still searches and still shuffles: the search happened,
    and found no card it was looking for.

    Every card found is exiled. The card's ruling lets the searcher leave any
    number of them (CR 701.23b: a search for a stated quality need not find),
    and no strip in this engine offers that — the five Eradicate-family cards
    and Lobotomy take the whole set the same way.
    """
    from ..faces import card_names
    from ..search_filters import name_key

    target = context.target
    if target is None or target not in game.players:
        game.log.append(f"{context.card.name}: no player to search")
        return True, "resolved"
    wanted = {
        name_key(name)
        for recorded in (context.results.get(record) or ())
        for name in card_names(recorded)
    }
    wanted.discard("")
    zones = tuple(instruction.payload.get("zones") or ())
    taken: list = []
    for zone in zones:
        cards = getattr(target, zone, None)
        if cards is None or not wanted:
            continue
        slots = [
            index for index, card in enumerate(cards)
            if wanted & {name_key(name) for name in card_names(card)}
        ]
        if not slots:
            continue
        # By slot, never by value or identity: a library holds several copies
        # of a card as one object (idiom 11).
        found = [cards[index] for index in slots]
        cards[:] = [
            card for index, card in enumerate(cards) if index not in set(slots)
        ]
        target.exile.extend(found)
        taken.extend(found)
    if "library" in zones:
        random.shuffle(target.library)
    game.log.append(
        f"{context.card.name} exiled {len(taken)} card(s) from {target.name}'s "
        + " and ".join(zones)
        + (": " + ", ".join(card.name for card in taken) if taken else "")
    )
    return True, "resolved"


@effect_handler("search_and_exile_matching")
def search_and_exile_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Search your graveyard and library for any number of red instant and/or
    sorcery cards, exile them, then shuffle." (Chandra, Heart of Fire's −9.)

    Armed as a suspending choice: the picks decide what the *next* step of the
    same resolution ("You may cast them this turn.") has to permit, so the
    steps behind this one wait for the answer — the Opt lesson, applied here
    by registration rather than by hoping.
    """
    from ..ai_valuation import (exiled_search_pile_comes_back,
                                exiled_search_pile_comes_back_one_at_a_time)

    caster = context.caster
    caster_index = game.players.index(caster)
    zones = tuple(instruction.payload.get("zones") or ("graveyard", "library"))
    game.arm_pending_choice(
        "search_exile_cards", caster_index,
        zones=zones,
        card_types=tuple(instruction.payload.get("card_types") or ()),
        colors=tuple(instruction.payload.get("colors") or ()),
        # "…for **three** cards" (Foresight). A printed ceiling on the find,
        # absent for the "any number of" spelling — the resolver refuses a
        # longer answer and the non-interactive default trims to it.
        maximum=instruction.payload.get("maximum"),
        # "…exile them in a face-down pile, and shuffle that pile." (Mangara's
        # Tome.) Carried to the resolver rather than acted on here, because
        # nothing has been found yet: the pile is what the *answer* exiles, and
        # this handler only asks the question.
        face_down_pile=bool(instruction.payload.get("face_down_pile")),
        shuffle_pile=bool(instruction.payload.get("shuffle_pile")),
        # Whether anything on this card reads the pile back, which is what a
        # headless seat needs before it answers "any number". Derived from the
        # compiled program (``ai_valuation.exiled_search_pile_comes_back``) and
        # carried on the prompt, so the resolver's stated policy is read off the
        # card rather than off the three cards that policy was written for.
        comes_back=(
            exiled_search_pile_comes_back(context.card)
            if context.card is not None else True
        ),
        # …and whether it comes back **a card at a time, at a price** (Skyship
        # Weatherlight's "{4}, {T}: … put that card into its owner's hand"),
        # which is the difference between "take everything" and "take what a
        # game is long enough to buy back". The same derivation, the same
        # carrier, the same reason.
        comes_back_slowly=bool(
            context.card is not None
            and exiled_search_pile_comes_back_one_at_a_time(context.card)
        ),
        _context=context,
    )
    game.log.append(f"{caster.name} is searching their {' and '.join(zones)}")
    return True, "pending_search_exile"
