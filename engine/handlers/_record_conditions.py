"""What a condition payload means when it asks what already **happened**.

The second of the three families ``control_flow.evaluate_condition`` hands a
kind to, and the handler twin of ``engine/grammar/lowering/_record_conditions.py``,
which produces exactly these kinds. Each is answered by reading a **record**:
the resolution's scratchpad ("if you do", "this way", the coin, the bid, the
counted number), the stack object's announcement (a kicker, an additional
cost), a stamp a permanent carries (where it entered from, how it was cast), or
the turn's history (``turn_state``, ``damage_ledger`` and the per-turn
ledgers). Never by looking at the board again: the record is what says which
event *this* sentence asks about, and a second look asks about whatever is
there by then.

Split out of ``control_flow.py`` at the 2,000-line cap's split round with the
two families beside it — ``_conditions`` says why the chain divides. The one
reader it shares with the board half is ``_conditions._compare_count``, the
printed comparison of a counted number. It registers no handler, hence the
underscore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..damage_deaths import DAMAGED_BY_SOURCE_DIED
from ..oracle_types import (BIDDING_WINNER, CHOSEN_COLOR_THIS_WAY,
                            CHOSEN_NUMBER_THIS_WAY, REVEALED_HAND_CARDS,
                            REVEALED_TOP_CARDS_BY_SEAT, MILLED_THIS_WAY,
                            DISCARDED_THIS_WAY, PROCESS_ROUNDS_SO_FAR)
from ..turn_state import started_the_turn
from ._conditions import _compare_count
from ._filters import _card_matches_filter, permanent_matches_filter

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


def evaluate_record_condition(
    game: Game, context: OracleExecutionContext, payload: dict,
    kind: str | None,
) -> object:
    """A condition answered by reading a **record** of something already done,
    or ``NotImplemented`` when *kind* is not one of them.

    Asked by ``control_flow.evaluate_condition``, which has already read
    *kind* off *payload*.
    """

    if kind == "additional_cost_paid":
        # "**If this spell's additional cost was paid**, …" (Undergrowth.)
        # CR 601.2b's optional additional cost, asked at resolution about an
        # announcement made while the spell was being cast. The mana pool that
        # paid it emptied at the end of that step (CR 500.5), so the count the
        # casting path recorded on the stack item is the only record there is —
        # and a resolution with no record answers False, which is what
        # declining the offer means.
        paid = (context.choices or {}).get("additional_costs_paid") or {}
        wanted = payload.get("symbols")
        if wanted is None:
            return any(int(times or 0) > 0 for times in paid.values())
        return int(paid.get(str(wanted), 0) or 0) > 0

    if kind == "was_kicked":
        # "If **this spell was kicked**" / "if **it was kicked**" / "if this
        # creature **wasn't kicked**" (CR 702.33d). One question with two places
        # the answer is kept, picked by what is asking:
        #
        # * a **permanent**'s ability (an entry trigger, Skizzik's end-step
        #   trigger) reads the stamp ``resolution._resolve_card`` left on the
        #   permanent that spell became -- the stack item is long gone, and a
        #   permanent nothing cast has no stamp, which is the rule's answer;
        # * a **spell** resolving reads its own stack record.
        #
        # Both come from ``cast_costs.kicked``, the reader keyed by the offer
        # the kicker rewrite produced.
        #
        # "…kicked **with its {1}{G} kicker**" (the Battlemages, CR 702.33f) is
        # the same question about one of the card's two kicker costs
        # (CR 702.33b): ``kicker`` is that cost's recorded key, and the two
        # places answer it the same way -- the permanent off
        # ``KICKED_WITH``, the tuple of keys ``_resolve_card`` stamped beside
        # the flag, and the spell off its own record through
        # ``cast_costs.kicked_with``. A permanent stamped by nothing (not cast,
        # CR 400.7) was kicked with none of them.
        from ..cast_costs import KICKED, KICKED_WITH, kicked, kicked_with

        wanted = payload.get("kicker")
        source = context.source_permanent
        if source is not None:
            if wanted is None:
                answer = bool(source.metadata.get(KICKED))
            else:
                answer = str(wanted) in tuple(
                    source.metadata.get(KICKED_WITH) or ()
                )
        elif context.card is None:
            answer = False
        elif wanted is None:
            answer = kicked(context.card, context.choices)
        else:
            answer = kicked_with(context.card, context.choices, str(wanted))
        return answer != bool(payload.get("negated"))

    if kind == "target_was_kicked":
        # "Counter target spell **if it was kicked**." (Ertai's Trickery.)
        # CR 702.33d's fact about *another* spell: the one this effect targets,
        # which the lowering settled off the branch this guards -- the
        # ``target_is_color`` arrangement, read through the same half of the
        # context a counter reads (``context.stack_target``).
        #
        # Asked of that spell's own stack record through ``cast_costs.kicked``,
        # so it is any of its kicker costs (a Battlemage that paid only its
        # second is a kicked spell) and never an unrelated optional cost: a
        # bought-back Capsize was not kicked. A spell that has left the stack
        # answers no to both polarities, for the reason the colour clause
        # gives -- the negated reading must not say yes about nothing.
        from ..cast_costs import kicked, kicked_with

        chosen = context.stack_target
        if (
            payload.get("target") != "spell"
            or chosen is None
            or chosen not in game.stack
            or chosen.card is None
        ):
            return False
        wanted = payload.get("kicker")
        answer = (
            kicked(chosen.card, chosen.choices) if wanted is None
            else kicked_with(chosen.card, chosen.choices, str(wanted))
        )
        return answer != bool(payload.get("negated"))

    if kind == "destroyed_target_was":
        # "Destroy target land. **If that land was a snow land**, …" (Icequake,
        # Thermokarst.) The permanent the destroy in front of this chose,
        # recorded by that handler *before* it destroyed anything — CR 608.2h's
        # last-known information, because by now the land is a card in a
        # graveyard and has no characteristics to ask about at all.
        #
        # Asked through the one matcher, with no observer and no source: the
        # question is about the object itself, and the lowering refuses any
        # narrowing that would need either.
        from ..subject_filters import subject_matches

        victim = context.results.get("destroyed_target")
        if victim is None:
            # The spell resolved with its target gone (CR 608.2b leaves a
            # legal-target check to the resolution). Nothing was destroyed, so
            # the clause asking what it was is False rather than a guess.
            return False
        return subject_matches(game, victim, payload.get("filter") or {})

    if kind == "revealed_card_is":
        # "If it's a creature or land card" (Track Down). Reads the card an
        # earlier step of this same resolution revealed, never the library:
        # the branch below this one draws, and a re-read would then be asking
        # about whichever card the draw uncovered.
        revealed = context.results.get("revealed_card")
        if revealed is None:
            return False
        wanted = [str(t) for t in (payload.get("card_types") or ())]
        line = (revealed.type_line or "").lower()
        # "If it's a **nonland** card" (Wand of Denial). The printed exclusion,
        # asked before the union below because it is the whole of what these
        # phrases say: "nonland card" names no type at all, so a reader that
        # needed one answered False for every card and the clause was a gate
        # nothing could pass.
        excluded = [str(t) for t in (payload.get("excluded_types") or ())]
        if excluded and any(t in line for t in excluded):
            return bool(payload.get("negated"))
        if not wanted:
            # An exclusion on its own is satisfied by anything the exclusion
            # did not name, which is what "nonland card" means.
            answer = bool(excluded)
            return (not answer) if payload.get("negated") else answer
        matches = [t for t in wanted if t in line]
        # "creature **or** land card" is a union; "artifact creature" is one
        # object that is both. The same distinction `type_match` draws
        # everywhere else, carried here so the two cannot disagree.
        if payload.get("type_match") == "all":
            answer = len(matches) == len(wanted)
        else:
            answer = bool(matches)
        # "If it **isn't** a land card" (Wand of Ith) — the same reading turned
        # over at the end, after the union rule above has been applied, because
        # negating each type separately would ask a different question.
        return (not answer) if payload.get("negated") else answer

    # "Exile it. **If you do**, create a … token." (Archfiend's Vessel.) Whether
    # the step before this one actually took place, read from the record that
    # step wrote. An absent record is False, which is the honest reading: the
    # handler writes it only on the path where the action happened.
    # "if it entered from your graveyard or you cast it from your graveyard"
    # (Archfiend's Vessel). Two records, because they are two events: the entry
    # seam stamps where the permanent came from, and the cast stamps the zone
    # the spell was cast from. A permanent that entered any other way answers
    # False, which is the reading that leaves the Vessel a plain 1/1.
    if kind == "entered_from":
        source = context.source_permanent
        if source is None:
            return False
        wanted = payload.get("zone")
        if source.metadata.get("entered_from_zone") == wanted:
            return True
        return bool(payload.get("or_cast")) and (
            source.metadata.get("cast_from_zone") == wanted
        )

    if kind == "cast_from":
        # "When this creature enters, if you cast it from your hand, …"
        # (Hypnox, CR 603.4.) The cast record alone: stamped only by the entry
        # road that resolves a permanent *spell*, so a reanimated or blinked
        # permanent has none and answers False. "You" needs no seat check of
        # its own: the stamp is the source's, and the trigger's controller is
        # the player who controlled the permanent the spell became.
        source = context.source_permanent
        if source is None:
            return False
        return source.metadata.get("cast_from_zone") == payload.get("zone")

    if kind == "sacrificed_this_way_matches":
        # "If you sacrifice a **snow** Forest this way, …" (Gargantuan Gorilla),
        # "…an **Island** this way, …" (Serendib Djinn). The narrowed reading of
        # "if you do": the sacrifice happened and the branch still runs only if
        # what went matches the tighter phrase.
        #
        # Against the **cards** the sacrifice recorded, never the board: what
        # went is in a graveyard by now and is a different object (CR 400.7),
        # and a board read would answer about whatever is still there. An empty
        # record is False — an offer declined, or a mandatory sacrifice that
        # could not be paid, is not a sacrifice of anything.
        given = list(context.results.get(payload.get("key")) or ())
        described = payload.get("filter") or {}
        return any(_card_matches_filter(card, described) for card in given)

    if kind == "exiled_this_way_share_a_name":
        # "…unless **it has the same name as another card exiled this way**" /
        # "…until **you exile two cards with the same name**" (Tainted Pact).
        # CR 201.2a over the cards this effect has exiled so far: the step in
        # front of the clause wrote this round's, and a repeated process files
        # the rounds before it under ``PROCESS_ROUNDS_SO_FAR``. By *position*
        # (``cards_sharing_a_name``), because "another" cannot be asked by
        # identity — two copies of a card in a library are one object.
        from ..counted_names import cards_sharing_a_name

        earlier = list(
            (context.results.get(PROCESS_ROUNDS_SO_FAR) or {}).get("exiled_cards")
            or ()
        )
        latest = list(context.results.get("exiled_cards") or ())
        sharing = cards_sharing_a_name(earlier + latest)
        if payload.get("of_latest"):
            return any(index >= len(earlier) for index in sharing)
        return bool(sharing)

    if kind == "it_happened":
        happened = bool(context.results.get(payload.get("key")))
        # "If you **can't**" (Cocoon) is the same record read the other way. An
        # absent record is "it did not happen", which is also the honest answer
        # when the recording step itself could not run — an Aura that left
        # before its upkeep trigger resolved removed nothing (CR 608.2b), so
        # the can't-branch is exactly what should run.
        return not happened if payload.get("negated") else happened

    if kind == "counted_number":
        # "**If the number** is odd, …" (Chaos Moon.) The number the count in
        # front of this recorded, never a second count of the board: the two
        # branches are one question asked once, and re-counting here would let a
        # board that changed between them answer both or neither.
        #
        # An absent record is False for either parity rather than a guess — the
        # lowering refuses a back-reference with no count in front of it, so
        # this is unreachable from a compiled card.
        if "counted_number" not in context.results:
            return False
        return _compare_count(
            int(context.results["counted_number"]), str(payload.get("op", "")), None
        )

    if kind == "won_bidding":
        # "If **you** win the bidding, …" (Mages' Contest.) The auction wrote
        # the seat its high bid stood for; "you" is the resolving seat
        # (CR 109.5). An absent record is False rather than a guess — the
        # auction did not run (its spell's controller was gone), so nobody won.
        winner = context.results.get(BIDDING_WINNER)
        return winner is not None and winner == game.players.index(context.caster)

    if kind == "coin_flip":
        # CR 705.2. The flip recorded its result; asking again would flip a
        # second coin, so a card printing both branches could win *and* lose.
        # An absent record is False for either branch rather than a guess — the
        # grammar refuses to lower a flip condition with no flip in front of it,
        # so this is unreachable from a compiled card.
        if "coin_flip" not in context.results:
            return False
        return bool(context.results["coin_flip"]) is bool(payload.get("won", True))

    if kind == "started_turn_state":
        # "If this creature started the turn untapped" (Rasputin Dreamweaver).
        # The board cannot answer this at an upkeep — the untap step has already
        # run — so the untap step records it before untapping anything
        # (`phases/untap_step.py`), and this reads that record. A permanent with
        # no record for the current turn did not start it: it entered part-way
        # through, which is False either way round and never a guess.
        source = context.source_permanent
        if source is None:
            return False
        value = started_the_turn(source, payload.get("state") or "", game.turn)
        if value is None:
            # It was not on the battlefield when the turn began, so it started
            # the turn neither way and both spellings of the clause are false.
            return False
        return (not value) if payload.get("negated") else value

    if kind == "exiled_card_was":
        # "If it was a creature card" (Scavenging Ooze). The card is in exile by
        # now, and CR 400.7 makes that a new object, so the only honest source
        # is the record the exiling step wrote (CR 608.2h). No record means
        # nothing was exiled — False, not a guess at a pile this effect did not
        # fill.
        cards = context.results.get("exiled_cards") or []
        # The printed type *line*, not the primary type: an Ornithopter is an
        # artifact creature card and CR 205.2 says it is a creature card too.
        wanted = tuple(payload.get("card_types") or ())
        return bool(cards) and all(
            any(name in card.type_line.lower() for name in wanted) for card in cards
        )

    if kind == "shared_color_milled_this_way":
        # "**If two cards that share a color were milled this way**, repeat
        # this process." (Grindstone.) The record the mill in front of this
        # wrote, never the graveyard: a graveyard holds whatever else has gone
        # there, and the words say "this way".
        #
        # A *shared* colour, so a colourless card can never satisfy it however
        # many are milled — Grindstone's famous stop. The test is over every
        # subset of the printed size, which for two is "some colour appears in
        # at least two of them"; written as a count per colour rather than as
        # pairs, because the printed number is a field and pairs would only
        # answer for two.
        from collections import Counter

        wanted = max(2, int(payload.get("count", 2) or 2))
        milled = tuple(context.results.get(MILLED_THIS_WAY) or ())
        if len(milled) < wanted:
            return False
        counts: Counter = Counter()
        for card in milled:
            for color in getattr(card, "colors", ()) or ():
                counts[color] += 1
        return any(seen >= wanted for seen in counts.values())

    if kind == "revealed_chosen_color_count":
        # "**If that opponent reveals exactly the chosen number of cards of the
        # chosen color**, you draw a card." (Scrying Glass.) Three records, all
        # written by earlier steps of this same resolution: the number a seat
        # named, the colour they named beside it, and the hand the reveal showed.
        #
        # The **record**, never the hand as it stands now. "Reveals" is what the
        # step in front of this one did, and by the time a longer card asked the
        # question the hand could have changed — the same rule every "this way"
        # test above follows.
        #
        # An absent record is not zero. With no reveal at all the count is not
        # "no cards of that colour", it is a question that was never asked, and
        # answering it False is the only honest reading — otherwise a chosen
        # number of zero would draw a card off a reveal that never happened.
        # (The lowering refuses the clause without all three producers, so this
        # is the belt to that braces.)
        wanted = context.results.get(CHOSEN_NUMBER_THIS_WAY)
        color = context.results.get(CHOSEN_COLOR_THIS_WAY)
        revealed = context.results.get(REVEALED_HAND_CARDS)
        if wanted is None or not color or revealed is None:
            return False
        # Whose cards these are, for the colour read: CR 105 is answered for an
        # object outside the battlefield by ``object_colors.card_colors``, which
        # needs the owner because a board-wide static can recolour a hand
        # (Celestial Dawn). The seat is the one the reveal named — the same
        # ``context.target`` that handler read — and never the printed noun
        # phrase, which restates it.
        owner = context.target if context.target is not None else context.caster
        described = {"color_filter": str(color)}
        count = sum(
            1 for card in revealed
            if _card_matches_filter(card, described, game=game, owner=owner)
        )
        return _compare_count(count, str(payload.get("op", "eq")), int(wanted))

    if kind == "revealed_card_has_chosen_name":
        # "**If that card has the chosen name**, this artifact deals 2 damage
        # to any target." (Cursed Scroll.) The two records an earlier step of
        # this same resolution wrote: the name a seat chose, and the one card a
        # random reveal turned up.
        #
        # Compared on printed names through the same ``name_key`` the milled
        # question below uses, so "Æther Vial" and "Aether Vial" are one card
        # in both places. A card in a hand is not a permanent and cannot be
        # copying anything (CR 707.2), so the printed name is the only name it
        # has. An empty name matches nothing and an empty hand revealed
        # nothing, and both are False rather than an error.
        from ..search_filters import name_key

        named = str(context.results.get("chosen_card_name") or "").strip()
        revealed = context.results.get("revealed_card")
        if not named or revealed is None:
            return False
        return name_key(revealed.name) == name_key(named)

    if kind == "chosen_name_milled_this_way":
        # "**If a card with the chosen name was milled this way**, you draw a
        # card." (Foreshadow.) Two records, both written by earlier steps of
        # this same resolution — the name a seat chose, and the cards a mill
        # actually put into a graveyard. Never a read of the pile: a graveyard
        # holds whatever else has gone there, and the words say "this way".
        #
        # Compared against each card's own printed name, because nothing in a
        # library is a permanent and nothing there can be copying anything
        # (CR 707.2). An empty name matches nothing, which is the honest
        # answer for a seat that named nothing.
        from ..search_filters import name_key

        named = str(context.results.get("chosen_card_name") or "").strip()
        if not named:
            return False
        wanted = name_key(named)
        return any(
            name_key(card.name) == wanted
            for card in (context.results.get(MILLED_THIS_WAY) or ())
        )

    if kind == "milled_this_way":
        # "If one or more creature cards were put into that graveyard this
        # way." (Helm of Obedience.) The record the loop wrote, not the
        # graveyard: the pile also holds cards this effect never touched, and
        # the sentence asks about the ones it did. No record means the loop
        # never ran, which is False rather than a guess at a pile it did not
        # fill — the same rule ``exiled_card_was`` states above.
        #
        # ``any``, not ``all``: the printed floor is "one or more", where the
        # exiled-card test one branch up asks about a set the sentence in front
        # of it defined in full.
        cards = context.results.get(MILLED_THIS_WAY) or []
        wanted = tuple(payload.get("card_types") or ())
        return any(
            any(name in card.type_line.lower() for name in wanted)
            for card in cards
        )

    if kind == "target_is_type":
        # "Untap target Griffin. **If it's a creature**, it gets +1/+1 until
        # end of turn." (Griffin Canyon.) The type twin of the colour clause
        # above, asked of the same object through the same resolver so the
        # branch and the effect beside it cannot disagree about which permanent
        # the pronoun meant.
        #
        # CR 613 answers it, not the printed type line: a Griffin land animated
        # into a creature is one, and a creature that has stopped being one is
        # not — which is the whole reason the card prints the question at all,
        # since "target Griffin" is a phrase a non-creature can satisfy.
        #
        # CR 608.2c: read while the instruction is followed, not when the target
        # was chosen. An object that is gone answers no to both readings — the
        # same call the two clauses either side of this one make.
        from ._targets import resolve_target_permanent

        target = resolve_target_permanent(
            game, context,
            predicate=lambda perm: True,
            fallback_players=(),
            fallback_on_invalid_choice=False,
        )
        if target is None:
            return False
        wanted = [str(t) for t in (payload.get("card_types") or ())]
        if not wanted:
            return False
        matches = [t for t in wanted if target.has_type(t)]
        # "artifact creature" is one object that is both; "creature or land" is
        # a union. The same distinction `type_match` draws everywhere else.
        if payload.get("type_match") == "all":
            answer = len(matches) == len(wanted)
        else:
            answer = bool(matches)
        return (not answer) if payload.get("negated") else answer

    if kind == "target_card_shares_type_with_cost_card":
        # "Return target card from your graveyard to your hand **if it shares
        # a card type with the card exiled this way**." (Holistic Wisdom.) Two
        # cards and no permanent: the target is the graveyard slot the
        # activation announced (the handler beside this reads the same one),
        # and the other is what the ability's own cost ate, off the payment
        # path's record (CR 608.2h). Compared by **printed** card types
        # (CR 205.2a; a card in a zone has no computed ones, CR 613.1), any one
        # in common answering — an Artifact Creature shares with an artifact
        # and with a creature both.
        #
        # No target or no record answers False: there is then nothing "it"
        # names, and the return this guards must not happen.
        from ..layer_bridge import printed_shape

        slot = context.target_permanent_index
        pile = context.caster.graveyard
        if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < len(pile):
            return False
        recorded = (context.choices or {}).get(str(payload.get("channel")))
        if recorded is None:
            return False
        paid = recorded if isinstance(recorded, (list, tuple)) else (recorded,)
        target_types = printed_shape(pile[slot])[0]
        return any(
            target_types & printed_shape(getattr(entry, "card", entry))[0]
            for entry in paid
        )

    if kind == "cost_object_was":
        # "…**if the exiled creature was a Thrull**" (Soul Exchange). The object
        # the *cost* ate (CR 601.2b / 602.2b), which left its zone before the
        # spell or ability was ever on the stack — so the only honest source is
        # the record the payment path kept (CR 608.2h), on the same channel
        # every other reader of a cost's spoils uses.
        #
        # The channels carry two shapes and both are answered: the cast and
        # activation sacrifice records hold a `Permanent`, whose *effective*
        # types are what CR 608.2h remembers, and the graveyard exile holds a
        # `CardDefinition`, which has no computed characteristics at all
        # (CR 613.1). Nothing recorded is False, which is also what the words
        # say: no creature was exiled, so the exiled creature was not a Thrull.
        from ..models import Permanent

        paid = (context.choices or {}).get(str(payload.get("channel")))
        if paid is None:
            return False
        described = payload.get("filter") or {}
        if isinstance(paid, Permanent):
            return permanent_matches_filter(paid, described)
        return _card_matches_filter(paid, described)

    if kind == "discarded_this_way":
        # "If you discard a creature card this way" (Aether Rift). The record
        # the discard in front of it wrote, not the graveyard: the pile also
        # holds cards this effect never touched. The printed type *line*, as
        # the two readers beside this one ask it — CR 608.2h's last-known
        # information about a card that was in a hand a moment ago.
        cards = context.results.get(DISCARDED_THIS_WAY) or []
        wanted = tuple(payload.get("card_types") or ())
        match = all if payload.get("type_match") == "all" else any
        return any(
            match(name in card.type_line.lower() for name in wanted)
            for card in cards
        )

    if kind == "discarded_card_was":
        # "If the discarded card was a land card" (Land's Edge). The card is in
        # a graveyard by the time this is asked and CR 400.7 makes that a new
        # object, so the only honest source is the record the *cost payment*
        # wrote (CR 608.2h) — the same last-known-information channel the
        # sacrifice cost already rides. No record means the ability discarded
        # nothing, which is False rather than a guess.
        cards = context.choices.get("discarded_for_cost") or []
        # The printed type *line*, exactly as the exile twin above reads it: an
        # artifact land is a land card (CR 205.2), and `primary_type` would say
        # otherwise.
        wanted = tuple(payload.get("card_types") or ())
        return bool(cards) and all(
            any(name in card.type_line.lower() for name in wanted) for card in cards
        )

    if kind == "destroyed_this_way":
        # "…**if that creature was destroyed this way**" (Infinite Authority).
        # Two records meet here and neither can answer alone: the scratchpad the
        # creating effect froze (CR 608.2h) says which creature the earlier step
        # marked, and the game's end-of-combat sweep says which permanents it
        # actually destroyed. Absence from the second is regeneration, a
        # creature that left first, or a mark that was never set — all of which
        # the card treats the same way.
        marked = (context.trigger_context or {}).get(payload.get("key")) or {}
        victim_ids = marked.get("victim_ids") or ()
        destroyed = set(game.destroyed_at_end_of_combat_this_turn)
        return any(victim_id in destroyed for victim_id in victim_ids)
    if kind == DAMAGED_BY_SOURCE_DIED:
        # "…if a creature dealt damage by this creature this turn died"
        # (Krovikan Vampire). The ledger the source carries, not the game-wide
        # death counter beside it: the counter cannot say *which* creature died
        # or who damaged it, and reading it here would fire this trigger on
        # every end step of every game with a trade in it.
        from ..damage_deaths import creatures_it_damaged_that_died

        return bool(creatures_it_damaged_that_died(context.source_permanent))
    if kind == "died_this_turn":
        return int(getattr(game, "creatures_died_this_turn", 0) or 0) > 0

    if kind == "had_plus1_counter":
        # "if it had a +1/+1 counter on it" (Basri's Lieutenant). The creature
        # is already in the graveyard by the time this resolves, so the only
        # legal source is the last-known information the fire site recorded
        # (CR 603.10). No record means nothing observed the death — False,
        # rather than a guess at a board that no longer holds the answer.
        return bool((context.trigger_context or {}).get("had_plus1_counter"))

    if kind == "had_named_counter":
        # "…exile it **if it had a death counter on it**" (Bogardan Phoenix).
        # The named-counter twin of the clause above, and last-known information
        # for its reason: the Phoenix is in a graveyard by the time this
        # resolves, and a graveyard card carries no counters. No record means
        # nothing observed the death — False, rather than a guess at a board
        # that no longer holds the answer, which for this card is the reading
        # that brings it back rather than the one that exiles it forever.
        frozen = (context.trigger_context or {}).get("dead_counters") or {}
        return int(frozen.get(str(payload.get("counter", "")), 0) or 0) > 0

    if kind == "source_ability_activations":
        # "If this ability has been activated four or more times this turn, …"
        # (Farrelite Priest, Initiates of the Ebon Hand.) The ledger the
        # activation path stamps on the permanent, read through its own module
        # so this question and CR 602.5's refusal count the same activations.
        #
        # The activation that is resolving has already been counted — the stamp
        # goes on once every cost and guard has passed — so the fourth use is
        # the one that sees four, which is what the card says.
        from ..activation_tallies import activations_this_turn

        source = context.source_permanent
        if source is None:
            # The permanent left between activation and resolution (CR 400.7
            # makes anything that comes back a different object), so there is
            # no ledger to read and no creature the clause could be about.
            return False
        used = activations_this_turn(game, source)
        wanted = int(payload.get("count", 0))
        if str(payload.get("comparison", "at_least")) == "exactly":
            return used == wanted
        return used >= wanted

    if kind == "mana_added_with_this_ability":
        # "…**if you haven't added mana with this ability this turn**, …"
        # (Carpet of Flowers.) CR 603.4 asks this twice — once as the trigger
        # would fire and once as it resolves — and the note it reads is written
        # by ``add_mana_from_text`` at the one moment mana is actually added, so
        # the two checks read the same fact and a trigger that added mana in the
        # precombat main phase does not fire again in the postcombat one.
        #
        # A source that has left the battlefield (CR 400.7) has no note, and the
        # negated clause therefore reads **true** — which is the card: an
        # enchantment that is gone adds nothing, and the ability is removed from
        # the stack for having no source long before this matters.
        from ..mana_ability_records import added_mana_this_turn

        added = added_mana_this_turn(
            game, context.source_permanent, str(payload.get("record", ""))
        )
        return (not added) if payload.get("negated", True) else added

    if kind == "creatures_attacked_this_turn":
        # "…**if no creatures attacked this turn**" (Keldon Twilight). CR
        # 603.4's intervening-if, read off the per-seat record the
        # declare-attackers step stamps (``PlayerState.attacked_this_turn``,
        # CR 508.1) and never off the board: an attacker that has died, left
        # or untapped since is still a creature that attacked this turn, and
        # reading the creatures would forget exactly that one.
        #
        # Every seat is asked, because the sentence names none — in a
        # multiplayer game a creature another player attacked *with* during
        # this turn is still one that attacked (CR 508.1 makes only the active
        # player an attacker, so in practice this is that seat's stamp; asking
        # all of them is what keeps it true if that ever stops being so).
        attacked = any(player.attacked_this_turn for player in game.players)
        return (not attacked) if payload.get("negated") else attacked

    if kind == "returned_to_hand_this_turn":
        # "a permanent was put into your hand from the battlefield this turn"
        # (Barrin). "Your" is the ability's controller; the bounce paths feed
        # the per-seat counter.
        seat = game.players.index(context.caster)
        return int(game.permanents_to_hand_this_turn.get(seat, 0)) > 0

    if kind == "attacked_or_blocked_this_combat":
        # "…if this creature attacked or blocked this combat" (the Clockwork
        # cycle, Kjeldoran Home Guard). **Read off the trigger's context, never
        # the board.** The end-of-combat step announces this batch and then
        # sweeps the combat record before the priority window that resolves it,
        # so by CR 603.4's second check "blocked this combat" is already gone
        # — a board read here would answer False for every blocker and the
        # ability would do nothing on exactly half the cards that print it.
        # The fire site freezes the answer (CR 603.10), which is the same
        # discipline it already takes with ``combat_opponents``.
        #
        # A missing key means this condition was asked under some other trigger,
        # where nothing froze an answer: False, which is the direction that does
        # nothing rather than the one that acts on a guess.
        return bool(
            (context.trigger_context or {}).get("attacked_or_blocked_this_combat")
        )

    if kind == "came_under_your_control_this_turn":
        # "…if this creature didn't attack **or come under your control this
        # turn**" (Mad Dog). CR 302.6's own record, read through the predicate
        # summoning sickness asks: a permanent not controlled continuously
        # since its controller's turn began came under that control during it —
        # by entering or by changing hands, which Erg Raiders' ruling says are
        # both "coming under your control". The lowering admits the clause only
        # under a trigger of the controller's own turn, which is when that
        # reading holds.
        #
        # A source that has left answers False for the *positive* clause — the
        # direction CR 603.4 takes for an intervening-if it cannot check — so
        # the negated one is what answers True and lets a "sacrifice it" find
        # nothing to sacrifice.
        source = context.source_permanent
        came = (
            source is not None
            and game.is_on_battlefield(source)
            and not game._controlled_since_turn_start(source)
        )
        return (not came) if payload.get("negated") else came

    if kind == "came_under_your_control_since_your_last_upkeep":
        # CR 702.30a's intervening-if — echo's whole condition, and the reason
        # an echo creature pays once and never again. Read off the record the
        # upkeep step writes, for the block clause below's reason: the moment it
        # asks about may have been an opponent's turn ago and nothing on the
        # board records when a permanent changed hands.
        #
        # "Your" is the ability's controller (CR 109.5), which is also the seat
        # the record names — a permanent under a thief's control has seen the
        # thief's upkeeps, and its old controller's window holds nothing about
        # it. A missing source answers False, the direction that stops the
        # ability rather than the one that sacrifices on a guess.
        from ..turn_state import came_under_control_since_seats_last_upkeep

        source = context.source_permanent
        if source is None or context.caster not in game.players:
            return False
        return came_under_control_since_seats_last_upkeep(
            game, source, game.players.index(context.caster)
        )

    if kind == "in_a_block_since_your_last_upkeep":
        # "…if it has blocked or been blocked since your last upkeep" (Wiitigo).
        # A window that outlives every per-turn combat record, so the
        # declare-blockers step stamps a seat-turn ordinal on both sides of each
        # declared block and `turn_state` does the arithmetic.
        #
        # "Your" is the ability's controller (CR 109.5), which is also the seat
        # the stamp has to name: a creature that blocked under a thief blocked
        # during the thief's turn, and its own controller's window is empty.
        from ..turn_state import in_a_block_since_seats_last_upkeep

        source = context.source_permanent
        if source is None or context.caster not in game.players:
            return False
        return in_a_block_since_seats_last_upkeep(
            game, source, game.players.index(context.caster)
        )

    if kind == "dealt_damage_this_turn":
        # "if this creature dealt damage to an opponent this turn" (Whirling
        # Dervish). Answered from the record the damage seam keeps on the
        # source permanent, because nothing on the board can be read for it
        # — the damaged player's life total says only what the whole turn did
        # to them. An absent record means this permanent damaged nobody, which
        # is the reading that leaves the Dervish uncountered.
        source = context.source_permanent
        if source is None:
            return False
        seats = source.metadata.get("dealt_damage_to_seats_this_turn") or []
        who = payload.get("who", "a player")
        if who == "a player":
            return bool(seats)
        controller_seat = game.players.index(context.caster)
        if who == "you":
            return controller_seat in seats
        return any(seat != controller_seat for seat in seats)

    if kind == "seat_cast_spell_this_turn":
        # "At the beginning of each player's end step, **if that player didn't
        # cast a spell this turn**, this enchantment deals 2 damage to that
        # player." (Impatience.) CR 603.4's intervening-if, read off the
        # per-seat per-turn record the casting path writes
        # (`PlayerState.spells_cast_this_turn`) and the turn boundary clears —
        # never off the board, because a resolved spell has left the stack and a
        # permanent that entered from a cast is indistinguishable from one that
        # was reanimated.
        #
        # Whose record is payload. "That player" is the seat the firing event
        # named, frozen into the trigger's context by the end step (CR 603.10)
        # under the same key the damage's own recipient reads — so the condition
        # and the effect can never be about two different players, which on this
        # card is the whole of what it does.
        seats: list[int] = []
        who = payload.get("who")
        if who == "that_player":
            frozen = (context.trigger_context or {}).get("event_subject_player")
            if not isinstance(frozen, int):
                # The words name a seat nothing recorded. Reported unmet rather
                # than guessed, exactly as the ledger clause below does: the
                # lowering is what keeps this clause off an event that freezes
                # no seat, and answering either way here would make Impatience
                # fire on every end step or on none.
                return False
            seats = [frozen]
        elif who == "an_opponent":
            if context.caster not in game.players:
                return False
            seats = list(game.opponents_of(game.players.index(context.caster)))
        else:
            if context.caster not in game.players:
                return False
            seats = [game.players.index(context.caster)]
        if not seats:
            return False
        cast = any(
            bool(game.players[seat].spells_cast_this_turn)
            for seat in seats
            if 0 <= seat < len(game.players)
        )
        return (not cast) if payload.get("negated") else cast

    if kind == "all_revealed_top_cards_are":
        # "…**if all cards revealed this way are creature cards**…" (Game
        # Preserve.) The per-seat map the reveal in front of this wrote
        # (CR 608.2h), never a re-read of the libraries: CR 701.20a moved
        # nothing, so a second look would find the same cards only until
        # something else touched a deck — and would say nothing about which of
        # them this sentence is about.
        #
        # **An empty record is False**, which is ``all_of``'s rule above and
        # its reason: a universal over nothing is vacuously true, and answering
        # true here would run the effect behind it over an empty set. It is
        # also the honest reading of the card — with every library empty
        # nothing was revealed, so there is nothing to put onto the
        # battlefield.
        from ..graveyard_order import is_printed_type

        revealed = context.results.get(REVEALED_TOP_CARDS_BY_SEAT) or {}
        wanted = str(payload.get("card_type", "creature"))
        return bool(revealed) and all(
            is_printed_type(card, wanted) for card in revealed.values()
        )

    if kind == "seat_played_land_this_turn":
        # "At the beginning of your end step, **if you didn't play a land this
        # turn**, you may draw a card." (Mercadian Atlas.) CR 603.4's
        # intervening-if, read off the per-seat per-turn tally the land-play
        # path writes (``Game.lands_played_this_turn``, bumped in
        # ``mixins/stack/resolution.py`` and cleared by ``turn_management``) —
        # never off the board, because by the end step a land played this turn
        # is an ordinary permanent and says nothing about how it got there.
        #
        # Whose tally is payload, exactly as the cast record above: "you" is the
        # ability's controller (CR 109.5, ``context.caster`` for a triggered
        # ability as much as for a spell) and "that player" the seat the firing
        # event named. A seat the words name and nothing recorded answers False
        # rather than guessing, which is that clause's rule and its reason.
        who = payload.get("who")
        if who == "that_player":
            seat = (context.trigger_context or {}).get("event_subject_player")
            if not isinstance(seat, int):
                return False
        elif who == "an_opponent":
            if context.caster not in game.players:
                return False
            seats = list(game.opponents_of(game.players.index(context.caster)))
            played = any(
                int(game.lands_played_this_turn.get(other, 0) or 0) > 0
                for other in seats
            )
            return (not played) if payload.get("negated") else played
        else:
            if context.caster not in game.players:
                return False
            seat = game.players.index(context.caster)
        if not (0 <= seat < len(game.players)):
            return False
        played = int(game.lands_played_this_turn.get(seat, 0) or 0) > 0
        return (not played) if payload.get("negated") else played

    if kind == "seat_dealt_damage_this_turn":
        # "…unless **one of their opponents was dealt damage this turn**"
        # (Antagonism). The turn's damage ledger, never a read of a life total:
        # a life total is the turn's *net*, so a player dealt 4 who then gained
        # 4 has been dealt damage and has lost no life, and the card asks about
        # the damage.
        #
        # Whose opponents is payload. "Their" is the seat the firing event was
        # about — frozen into the trigger's context (CR 603.10) by the end step,
        # under the same key the damage recipient beside it reads, so the
        # condition and the effect can never be about two different players.
        from ..damage_ledger import damage_dealt_to_seat

        if context.caster not in game.players:
            return False
        seat = game.players.index(context.caster)
        if payload.get("opponents_of") == "that_player":
            frozen = (context.trigger_context or {}).get("event_subject_player")
            if not isinstance(frozen, int):
                # The words name a seat nothing recorded. Answering False would
                # let Antagonism fire on every end step; answering True would
                # silence it for ever. Refusing to answer is neither: the
                # condition is reported as unmet, and the lowering is what keeps
                # the clause off an event that freezes no seat.
                return False
            seat = frozen
        return any(
            damage_dealt_to_seat(game, opponent) > 0
            for opponent in game.opponents_of(seat)
        )

    if kind == "life_gained_this_turn":
        # Per player, because the counter is: "you" is the ability's
        # controller, which is context.caster for a triggered ability too.
        who = payload.get("who", "you")
        players = (
            [context.caster] if who == "you"
            else [p for p in game.players if p is not context.caster]
        )
        wanted = int(payload.get("amount", 0))
        return any(
            int(getattr(p, "life_gained_this_turn", 0) or 0) >= wanted
            for p in players
        )

    # Not a kind of this family: ``control_flow.evaluate_condition`` asks the
    # next one, and answers False when none of them claims it.
    return NotImplemented
