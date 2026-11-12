"""What a card reveals out of a **hand** (CR 701.20a), and what the sentences
behind the reveal do with what it showed.

The bare reveal (Inquisition; Noxious Vapors' each player; Crosis's damaged
player); Duress's reveal-and-choose, with Mind Warp's look riding it as
``looked_at`` and Blackmail's revealer choosing first which cards to show —
every narrowing a new printing puts on "a … card from it" lands in
:func:`reveal_hand_and_choose` and on its prompt; Stromgald Spy's standing
reveal; and the card revealed at random together with what follows it: exile
it (Planeswalker's Mischief — which takes a card turned up off a library too,
the same pronoun on the same record), or have it discarded unless its owner
pays life (Wand of Ith, and Sirocco's one offer per card). Those read what the
reveal recorded — :data:`REVEALED_HAND_INDEX` among it, a slot, because two
copies of a card in a hand are one object — and stay beside the reveal that
writes it.

Split out of ``reveal.py`` at the pre-Fifth-Dawn split round, on the line that
module's docstring drew between its two halves; the reveals of a library's top
stayed there. The lowering side keeps both halves in one module,
``engine/grammar/lowering/reveal.py``, whose hand block this is the handler
twin of.
"""

from __future__ import annotations

import dataclasses
import random
from typing import TYPE_CHECKING

from ..linked_exile import until_leaves_has_ended
from ..oracle_types import REVEALED_HAND_CARDS, REVEALED_HAND_SEAT
# The runtime class. The bare name is a TYPE_CHECKING-only import below, and
# the handlers here *build* instructions for an optional payment's branches.
from ..oracle_types import OracleInstruction as _OracleInstruction
from ..revealed_hands import reveal_hand_while_present
from ..resumption import run_resumable
from ..search_filters import search_matches
from ._amounts import resolve_amount
from ._filters import _card_matches_filter
from ._targets import frozen_that_player_seat
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("reveal_hand")
def reveal_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target player reveals their hand." (CR 701.20 — Inquisition on its
    own, and the first half of Amnesia and Rag Man.)

    Its own step, so what happens to the revealed cards is the next
    instruction's business. The cards are *named*, because that is what
    "revealed" means here: a line saying only how many were held would leave
    the reveal indistinguishable from not revealing at all, and Inquisition's
    next sentence is sized by what is in that hand. Through ``record_reveal``, the one feed the web
    layer reads, rather than a log line alone: a reveal the client cannot show
    is a reveal the player has to take on trust, and Rag Man's at-random discard
    is exactly the effect where seeing the hand is the point.
    """
    # "**You** may reveal your hand …" (Manabond.) The printed word, read off
    # the payload rather than inferred from an empty ``context.target``: a
    # sentence is a sequence and by its second step the resolution may be
    # carrying a target an earlier step chose, so the inference would reveal
    # whichever hand that step happened to name. The same distinction
    # ``deal_damage`` records about its own recipient.
    if instruction.payload.get("who") == "each_player":
        # "**Each player** reveals their hand, …" (Noxious Vapors.) Every
        # living seat's, in APNAP order (CR 101.4) — one reveal apiece through
        # the same feed, and one record of everything shown: "revealed this
        # way" behind this step is all of it.
        from .offers import _offered_seats

        shown: list = []
        for seat in _offered_seats(game, "each_player", context):
            revealer = game.players[seat]
            shown.extend(revealer.hand)
            names = [held.name for held in revealer.hand]
            game.record_reveal(seat, names)
            game.log.append(
                f"{revealer.name} reveals their hand: "
                + (", ".join(names) or "(empty)")
            )
        context.results[REVEALED_HAND_CARDS] = shown
        return True, "resolved"
    if instruction.payload.get("who") == "you":
        victim = context.caster
    elif instruction.payload.get("who") == "damaged_player":
        # "…**that player** reveals their hand…" (Crosis, the Purger.) The seat
        # the damage froze (CR 603.10). No record means the words named nobody
        # and no hand is shown — never a fall back to the ability's controller,
        # whose hand is the one this must not open. An empty record is written
        # all the same, so the sentence behind this one counts nothing rather
        # than reading a back-reference with no producer.
        frozen = frozen_that_player_seat(game, context)
        if frozen is None:
            context.results[REVEALED_HAND_CARDS] = []
            game.log.append(f"{context.card.name}: no recorded player, no reveal")
            return True, "resolved"
        victim = game.players[frozen]
    else:
        victim = context.target if context.target is not None else context.caster
    seat = next(
        (i for i, seated in enumerate(game.players) if seated is victim), None
    )
    names = [held.name for held in victim.hand]
    # "**For each blue instant card revealed this way**, …" (Sirocco.) What was
    # shown, as cards rather than names: the sentence behind this one narrows by
    # colour and card type, and a list of names cannot be asked either. Written
    # even for an empty hand, because an absent key is a back-reference with no
    # producer — a different thing from a reveal that showed nothing.
    context.results[REVEALED_HAND_CARDS] = list(victim.hand)
    if seat is not None:
        game.record_reveal(seat, names)
        # Whose hand "it" is behind this step (Reversal of Fortune's "a card
        # in it") — see ``oracle_types.REVEALED_HAND_SEAT``.
        context.results[REVEALED_HAND_SEAT] = seat
    game.log.append(
        f"{victim.name} reveals their hand: " + (", ".join(names) or "(empty)")
    )
    return True, "resolved"


@effect_handler("reveal_hand_and_choose")
def reveal_hand_and_choose(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target opponent reveals their hand. You choose a noncreature, nonland
    card from it. That player discards that card." (Duress.)

    The first time one player chooses from *another* player's hidden zone. The
    reveal is what makes that legal (CR 701.20 — the hand is public information
    from here on), so it is logged rather than assumed, and the choice is queued
    on the **caster's** seat with the victim's as payload: every other pending
    choice in the engine is owed by the player it is about, and this one is not.

    Nothing is queued when no card in the hand answers the filter — a choice
    with no legal answer is not a choice, and leaving it queued would block the
    caster on a prompt they cannot satisfy.
    """
    card = context.card
    if instruction.payload.get("victim") == "event_subject_player":
        # "Look at **that player's** hand …" (Leshrac's Sigil). Nothing was
        # targeted, so the seat is the one the firing event froze (CR 603.10)
        # rather than whatever this resolution is carrying. An absent key is a
        # trigger nobody froze a seat for; the lowering's gate is what keeps
        # that from arriving, and reading nothing here is the right answer if
        # it ever does.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False, "no seat was frozen for 'that player'"
        victim = game.players[seat]
    elif instruction.payload.get("victim") == "damaged_player":
        # "Whenever this creature deals combat damage to a player, look at
        # **that player's** hand …" (Doomsday Specter.) The seat the damage
        # went to, on the key every damage fire site stamps — read narrowly,
        # for the branch above's reason: with none recorded the words named
        # nobody, and the fallback below is the ability's own controller,
        # whose hand is the one this must not open.
        seat = (context.trigger_context or {}).get("defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False, "no damaged player was frozen for 'that player'"
        victim = game.players[seat]
    else:
        victim = context.target if context.target is not None else context.caster
    victim_index = next(
        (i for i, seated in enumerate(game.players) if seated is victim), None
    )
    caster_index = next(
        (i for i, seated in enumerate(game.players) if seated is context.caster), None
    )
    if victim_index is None or caster_index is None:
        return True, "resolved"
    exclude_types = list(instruction.payload.get("exclude_types") or ())
    # "…a card **other than a basic land card** from it" (Lobotomy). The second
    # narrowing this picker can carry, and it travels beside the first for that
    # one's reason: what is offered and what an answer is checked against are
    # one predicate, and a restriction only the handler knew about would be a
    # client offering the whole hand.
    # "You choose **a creature card** from it." (Ostracize.) The positive form
    # of the same question, under the key ``search_matches`` already answers it
    # with — and it travels beside the other two for their reason: a type only
    # this handler knew about would be a client offering the whole hand.
    card_types = list(instruction.payload.get("card_types") or ())
    narrowing = {
        "exclude_types": exclude_types,
        "exclude_basic_lands": bool(
            instruction.payload.get("exclude_basic_lands")
        ),
    }
    if card_types:
        narrowing["card_type"] = tuple(card_types)
    # "a **nonbasic** land card" (Encroach). The third narrowing, carried for
    # the two above it's reason: an exclusion only this handler knew about is a
    # client offering the whole hand.
    excluded_supertypes = list(instruction.payload.get("exclude_supertypes") or ())
    if excluded_supertypes:
        narrowing["exclude_supertypes"] = excluded_supertypes
    # "Choose a color. … you choose a card **of that color** from it." (Addle.)
    # CR 608.2d's colour, read out of the scratchpad the choosing step wrote and
    # carried on the prompt beside the three narrowings above, for their reason.
    # **No colour means no card**: read as "no narrowing" the caster would be
    # choosing from the whole hand.
    any_colors: list[str] = []
    color_key = instruction.payload.get("color_filter_from")
    if color_key is not None:
        chosen_color = context.results.get(str(color_key))
        if not chosen_color:
            game.log.append(f"{card.name}: no colour was chosen, so no card is")
            return True, "resolved"
        any_colors = [str(chosen_color)]
        narrowing["restrictions"] = {"any_colors": any_colors}
    shows = instruction.payload.get("revealer_shows")
    if shows == "x":
        # "…that player reveals **X** cards from their hand and you choose one
        # of them." (Hollow Specter.) The X the sentence defined, taken now
        # (CR 608.2h). Zero is the ruling's case (2004-10-04): "X can be zero,
        # but then that player discards nothing."
        shows = resolve_amount("x", context.x_value)
        if shows <= 0:
            game.log.append(f"{card.name}: {victim.name} reveals no cards")
            return True, "resolved"
    if shows:
        return _reveal_shown_cards_and_choose(
            game, instruction, context, victim_index, caster_index,
            narrowing, int(shows),
        )
    legal = [
        index
        for index, held in enumerate(victim.hand)
        # The seat is handed over for CR 202.2 alone — a card's colour in a
        # hand is its printed one unless something on a board says otherwise.
        if search_matches(held, narrowing, game=game, owner=victim)
    ]
    # CR 701.20 makes a reveal public where CR 701.20e's look shows the chooser
    # alone, so the line says which happened rather than saying "revealed" for
    # both.
    looked_at = bool(instruction.payload.get("looked_at"))
    game.log.append(
        f"{victim.name}"
        + (
            f" showed their hand ({len(victim.hand)} card(s)) to {context.caster.name}"
            if looked_at
            else f" revealed their hand ({len(victim.hand)} card(s))"
        )
        + f" to {card.name}"
    )
    if (
        str(instruction.payload.get("fate", "discard")) == "exile_until_source_leaves"
        and until_leaves_has_ended(game, context.source_permanent)
    ):
        # Kitesail Freebooter's ruling (2020-06-23), which is CR 610.3b: "If
        # Kitesail Freebooter leaves the battlefield before its
        # enters-the-battlefield ability resolves, the opponent will reveal
        # their hand, but no card will be exiled." So the hand is shown, above,
        # and no pick is armed - an armed one could never be answered, since
        # the answer needs the permanent that would hold the card.
        game.log.append(
            f"{card.name} left the battlefield before its ability resolved, "
            "so no card is exiled"
        )
        return True, "resolved"
    if not legal:
        game.log.append(f"{card.name}: no card in that hand can be chosen")
        return True, "resolved"
    # "…choose **X** cards from it" (Mind Warp). Capped at what the hand holds:
    # CR 608.2 does as much as it can, and a prompt asking for a card that is
    # not there would never be answerable.
    wanted = min(
        resolve_amount(instruction.payload.get("count", 1), context.x_value),
        len(legal),
    )
    if wanted <= 0:
        game.log.append(f"{card.name}: no cards are chosen")
        return True, "resolved"
    game.arm_pending_choice(
        "revealed_hand_pick", caster_index,
        card_name=card.name,
        victim_index=victim_index,
        legal_indices=legal,
        remaining=wanted,
        # "…choose **up to** X cards from it" (Discordant Dirge). CR 601.2c's
        # ceiling, which is what lets the chooser stop before the number is
        # reached. Carried onto every prompt of the chain by
        # ``_rearm_revealed_hand_pick`` — the picks after the first are the same
        # printed choice, so the permission has to survive each answer.
        up_to=bool(instruction.payload.get("up_to")),
        # Carried so the picks after the first can recompute what is legal
        # against the hand as it then stands.
        exclude_types=exclude_types,
        exclude_basic_lands=narrowing["exclude_basic_lands"],
        card_types=card_types,
        exclude_supertypes=excluded_supertypes,
        any_colors=any_colors,
        fate=str(instruction.payload.get("fate", "discard")),
        # The resolution's own scratchpad. Every pick writes the chosen card's
        # name into it — the pick *is* a chosen card, whatever becomes of it —
        # so a later sentence naming "the chosen card" (Lobotomy's search) has
        # one place to read it from, and ``lowering/_records`` can declare the
        # record for the kind rather than for one of its fates.
        record=context.results,
        # "…until **this creature** leaves the battlefield" (Kitesail
        # Freebooter): the source holds the exiled card, so which permanent it
        # is has to reach the answer. By id, because the prompt outlives the
        # resolution that armed it.
        source_id=(
            context.source_permanent.permanent_id
            if context.source_permanent is not None else None
        ),
    )
    return True, "resolved"


#: The cards a revealer chose to show out of their hand (Blackmail), for the
#: pick among them that follows.
SHOWN_HAND_CARDS = "shown_hand_cards"


def _reveal_shown_cards_and_choose(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext,
    victim_index: int, caster_index: int, narrowing: dict, shows: int,
) -> tuple[bool, str]:
    """"Target player reveals three cards from their hand and you choose one
    of them. That player discards that card." (Blackmail.)

    Two decisions by two players, in the printed order. **The revealer picks
    what to show** — the subject of "reveals" performs it (CR 608.2c) — through
    the ordinary hand pick (``choose_cards_in_hand``, its ``reveal`` making the
    cards public as they are chosen, CR 701.20a); "if the player has less than
    3 cards, all of them are revealed" (the 2004-10-04 ruling) is CR 608.2's
    as-much-as-possible, so a hand of three or fewer is shown whole with
    nobody asked. **Then the chooser picks among exactly those cards**,
    through Duress's ``revealed_hand_pick``, its legal slots the shown ones —
    and ``shown_indices`` beside them, so the prompt renders the cards nobody
    revealed face down rather than publishing them.

    The two halves are one loop over the one revealing seat with the pick as
    its last step (``resumption.run_resumable``), so a revealer who has to be
    asked suspends the resolution and the answer brings the pick back.
    """
    card = context.card
    victim = game.players[victim_index]
    fate = str(instruction.payload.get("fate", "discard"))

    def pick() -> None:
        shown = list(context.results.get(SHOWN_HAND_CARDS) or ())
        # Hand slots by identity, one per shown card: two copies of a card in
        # a hand are one ``CardDefinition``, so a pair shown is two slots.
        slots: list[int] = []
        for held_card in shown:
            for index, held in enumerate(victim.hand):
                if held is held_card and index not in slots:
                    slots.append(index)
                    break
        legal = [
            index for index in slots
            if search_matches(victim.hand[index], narrowing, game=game, owner=victim)
        ]
        if not legal:
            game.log.append(f"{card.name}: no revealed card can be chosen")
            return
        game.arm_pending_choice(
            "revealed_hand_pick", caster_index,
            card_name=card.name,
            victim_index=victim_index,
            legal_indices=legal,
            shown_indices=slots,
            remaining=1,
            fate=fate,
            exclude_types=list(narrowing.get("exclude_types") or ()),
            exclude_basic_lands=bool(narrowing.get("exclude_basic_lands")),
            record=context.results,
            # CR 109.5: the spell's controller causes the discard, whichever
            # path armed the pick — straight through, or resumed by the
            # revealer's answer when nothing is resolving to stamp it.
            _cause_seat=caster_index,
            source_id=(
                context.source_permanent.permanent_id
                if context.source_permanent is not None else None
            ),
        )

    if len(victim.hand) <= shows:
        everything = list(victim.hand)
        context.results[SHOWN_HAND_CARDS] = everything
        names = [held.name for held in everything]
        if names:
            game.record_reveal(victim_index, names)
        game.log.append(
            f"{victim.name} reveals {', '.join(names) or 'no cards'} "
            f"({card.name})"
        )
        pick()
        return True, "resolved"

    shown_payload = {
        "card_filter": {},
        "count": shows,
        "reveal": True,
        "result_key": SHOWN_HAND_CARDS,
        # Read by ``ai_prompts.order_hand_pick``: the cards shown are the ones
        # an opponent then chooses among, so a seat nobody asks shows its
        # least costly.
        "shown_to_opponent": True,
    }
    run_resumable(
        game, [victim_index],
        lambda seat: game.arm_choose_cards_in_hand(seat, shown_payload, context),
        then=pick,
    )
    return True, "resolved"


@effect_handler("reveal_hand_while_source_present")
def reveal_hand_while_source_present(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Stromgald Spy: "…you may have defending player play with their hand
    revealed for as long as this creature remains on the battlefield."

    CR 701.20a: revealing shows the cards to every player, and the hand stays a
    hidden zone by classification (CR 400.2) — so nothing here moves a card, and
    the whole effect is a record the per-seat serialization reads.

    The record goes on the **source**, which is what implements the duration
    with no sweep: ``engine/revealed_hands.py`` scans the battlefield for it, a
    permanent that leaves stops being in the scan (CR 611.2b) and a returning
    one is a new object with no record (CR 400.7).

    The seat is CR 506.2's defender, frozen by the combat fire site rather than
    read off the board: this resolves in a priority window after the
    declaration, and an attacker that left combat in between would leave a board
    read naming nobody.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    seat = (context.trigger_context or {}).get("trigger_defending_player_index")
    if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
        game.log.append(f"{context.card.name}: no defending player was recorded")
        return True, "resolved"
    reveal_hand_while_present(source, seat)
    game.log.append(
        f"{context.card.name}: {game.players[seat].name} plays with their hand "
        f"revealed while {source.card.name} remains on the battlefield"
    )
    return True, "resolved"


#: The scratchpad key the random reveal writes beside ``revealed_card``: which
#: slot of the hand it named. The card object alone cannot answer that — two
#: copies of one card in a hand are literally the same object (idiom 11), so a
#: discard by value would take whichever one ``list.remove`` reached first.
REVEALED_HAND_INDEX = "revealed_card_hand_index"

#: Which of a revealed hand's cards *one* of Sirocco's offers is about. Private
#: to a single offer's branch context — the resolution's own scratchpad is
#: shared, and a key written into it per offer would leave every branch reading
#: whichever was armed last.
_DISCARDED_REVEALED_CARD = "discarded_revealed_card"

#: Whose ability is making the offered seat discard (CR 109.5), for the two
#: "…discards it unless they pay N life" branches below. They run under a
#: context whose ``caster`` has been swapped for the **paying** seat — which is
#: what lets one ``pay_life`` instruction charge whoever was offered it — so by
#: the time the declined branch discards, ``Game.resolving_seats`` names the
#: victim and "a spell or ability an opponent controls causes you to discard"
#: (Psychic Purge, Dodecapod) would read as the victim's own doing. Written
#: into the scratchpad the two contexts share, by the step that still knows.
_DISCARD_CAUSE_SEAT = "discard_cause_seat"


@effect_handler("reveal_random_card_from_hand")
def reveal_random_card_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target player reveals a card at random from their hand." (Wand of Ith.)

    CR 701.20 over one card nobody chose. Recorded under the same
    ``revealed_card`` key the library reveal writes, so the sentences behind it
    — "if it's a land card", "discards **it**" — read the one referent this
    engine has for a revealed card rather than a second one.

    The slot is recorded beside it, because the card object is not an identity
    in a hand: two copies of one card there are the same object, and a discard
    by value would take whichever the list reached first.

    An empty hand reveals nothing, which the condition behind it reads as False
    — a legal outcome, not an error.

    **Whose hand is stated when the sentence states it.** "…then reveal a card
    at random from **your** hand" (Cursed Scroll) is the effect's own
    controller, and the fallback below cannot answer it: ``context.target`` is
    the *ability's* target, which on that card is whoever the damage is aimed
    at. The fallback stays for the targeted printings, where the ability
    targets exactly the player the sentence names.
    """
    if instruction.payload.get("revealer") == "you":
        victim = context.caster
    else:
        victim = context.target if context.target is not None else context.caster
    if not victim.hand:
        game.log.append(f"{victim.name} has no cards in hand to reveal")
        # "…equal to **that card's mana value**" (Planeswalker's Mirth) about a
        # card nobody revealed: CR 107.2, "if anything needs to use a number
        # that can't be determined … it uses 0 instead". Written rather than
        # left absent because ``lowering/_records`` declares the record for the
        # kind, and so a stale number from an earlier step cannot answer.
        context.results["its_mana_value"] = 0
        return True, "resolved"
    index = random.randrange(len(victim.hand))
    card = victim.hand[index]
    context.results["revealed_card"] = card
    context.results[REVEALED_HAND_INDEX] = index
    # The printed mana value (CR 202.3): a card in a hand has no computed
    # characteristics (CR 613.1), and the number is frozen here because the
    # sentence behind this one cannot go and look — the hand is hidden and the
    # slot was nobody's choice (CR 608.2h).
    context.results["its_mana_value"] = int(card.cmc or 0)
    seat = next((i for i, seated in enumerate(game.players) if seated is victim), None)
    if seat is not None:
        game.record_reveal(seat, [card.name])
    game.log.append(f"{victim.name} reveals {card.name} at random from their hand")
    return True, "resolved"


@effect_handler("exile_revealed_card")
def exile_revealed_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…If it's an instant or sorcery card, **exile it**." (Planeswalker's
    Mischief.)

    "It" is the card the reveal in front of this step recorded, taken out of
    the hand it was shown from **by slot** — ``discard_revealed_card``'s rule
    and for its reason: a hand is the one zone where two copies of a card are
    one object, so the index resolved at reveal time is the only thing that
    names which of them was shown. A hand that has changed underneath exiles
    nothing rather than guessing.

    Into its **owner's** exile (CR 400.3), which is the revealing player's and
    not the ability's controller's, and recorded under the one ``exiled_cards``
    key every other exile writes — so "you may cast it … for as long as it
    remains exiled" and "if you haven't cast it, return it" read the referent
    this engine already has. The record is written even when nothing moves:
    ``lowering/_records`` declares it for the kind, and an absent key is a
    back-reference with no producer rather than an exile of nothing.

    Whose hand is ``reveal_random_card_from_hand``'s own answer, read the same
    way, so the two steps cannot name different players.

    **A card turned up from a library is the same pronoun**, and the record is
    the same key (``reveal.reveal_top_of_library`` writes ``revealed_card``
    too), so this kind answers for both zones rather than exiling nothing
    behind one of them: with no hand slot recorded the card is where
    ``reveal.bin_revealed_card`` looks for it, still on its owner's library.
    """
    context.results["exiled_cards"] = []
    card = context.results.get("revealed_card")
    if card is None:
        return True, "resolved"
    index = context.results.get(REVEALED_HAND_INDEX)
    if not isinstance(index, int):
        for owner in game.players:
            for slot, held in enumerate(owner.library):
                if held is card:
                    owner.library.pop(slot)
                    card = game.put_card_into_exile(owner, card)
                    context.results["exiled_cards"] = [card]
                    game.log.append(
                        f"{owner.name} exiles {card.name} from their library"
                    )
                    return True, "resolved"
        game.log.append(f"{context.card.name}: {card.name} has already moved")
        return True, "resolved"
    victim = context.target if context.target is not None else context.caster
    if not (0 <= index < len(victim.hand)) or victim.hand[index] is not card:
        game.log.append(f"{context.card.name}: {card.name} is no longer in hand")
        return True, "resolved"
    victim.hand.pop(index)
    card = game.put_card_into_exile(victim, card)
    context.results["exiled_cards"] = [card]
    game.log.append(f"{victim.name} exiles {card.name} from their hand")
    return True, "resolved"


@effect_handler("discard_revealed_card")
def discard_revealed_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The declined branch of "…discards it unless they pay N life".

    "It" is the card the reveal recorded, taken **by slot**: a hand is the one
    zone where two copies of a card are one object, so the index resolved at
    reveal time is the only thing that names which of them was shown.

    A hand that has changed underneath the prompt discards nothing rather than
    guessing — the card the sentence named is not there to discard.
    """
    victim = context.target if context.target is not None else context.caster
    card = context.results.get("revealed_card")
    index = context.results.get(REVEALED_HAND_INDEX)
    if card is None or not isinstance(index, int):
        return True, "resolved"
    if not (0 <= index < len(victim.hand)) or victim.hand[index] is not card:
        game.log.append(f"{context.card.name}: {card.name} is no longer in hand")
        return True, "resolved"
    victim.hand.pop(index)
    # Through the discard seam, never straight to the graveyard: a discard is
    # CR 701.9a's event whoever chose the card, so a replacement over it
    # (Library of Leng, Dodecapod) and every watcher of one (Megrim, Psychic
    # Purge) has to see this one too. It went by the graveyard seam alone until
    # Dodecapod was driven against it, and nothing watching a discard fired.
    game._discard_card(
        victim, card, cause_seat=context.results.get(_DISCARD_CAUSE_SEAT)
    )
    game.log.append(f"{victim.name} discards {card.name}")
    return True, "resolved"


@effect_handler("discard_revealed_unless_pay_life")
def discard_revealed_unless_pay_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"That player discards it unless they pay 1 life." / "…unless they pay
    life equal to its mana value." (Wand of Ith.)

    An offer to a seat that is not the ability's controller, on the same
    ``optional_pay`` queue every other offer uses — so the same three loops in
    ``web/prompts.py`` render it, gate the actions it blocks and answer it for
    an AI seat, and the ability stays on the stack until it is answered
    (CR 608.2, CR 117.3b).

    The *paying* seat is put on the branches' context rather than on the
    payment's payload: ``pay_life`` charges ``context.caster``, and replacing it
    here is what makes one payment instruction chargeable to whoever was
    offered it — the discard on the other branch reads the same context and so
    cannot come apart from it.

    CR 119.4: a player may pay life only with a life total at least the amount,
    so a seat that cannot pay is never offered the choice — it simply discards,
    which is what the sentence says happens when the cost is not paid.
    """
    from .life_and_game import can_pay_life

    victim = context.target if context.target is not None else context.caster
    seat = next((i for i, seated in enumerate(game.players) if seated is victim), None)
    card = context.results.get("revealed_card")
    if card is None or seat is None:
        return True, "resolved"
    printed = instruction.payload.get("life", 0)
    # "…life equal to **its** mana value" — a number nothing knows until the
    # card is revealed, so it is read here off the card the reveal recorded
    # rather than resolved at lowering.
    amount = int(card.cmc or 0) if printed == "revealed_mana_value" else int(printed)
    discard = (_OracleInstruction("discard_revealed_card", "", {}),)
    # Before the caster is swapped, while the resolving seat is still the
    # ability's own controller — see ``_DISCARD_CAUSE_SEAT``. The scratchpad is
    # shared with the paying context, so the declined branch reads it there.
    context.results[_DISCARD_CAUSE_SEAT] = game.discard_cause_seat()
    paying_context = dataclasses.replace(context, caster=victim)
    if not can_pay_life(victim, amount):
        game._execute_oracle_instruction(discard[0], paying_context)
        return True, "resolved"
    game.arm_pending_choice(
        "optional_pay", seat,
        card_name=context.card.name if context.card is not None else "",
        cost={},
        life=0,
        _source_permanent=context.source_permanent,
        _on_accept=(_OracleInstruction("pay_life", "", {"amount": amount}),),
        _on_decline=discard,
        _on_reflexive=(),
        _context=paying_context,
        prompt=f"Pay {amount} life to keep {card.name}?",
    )
    return True, "resolved"


@effect_handler("discard_revealed_matching_unless_pay_life")
def discard_revealed_matching_unless_pay_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"For each blue instant card revealed this way, that player discards that
    card unless they pay 4 life." (Sirocco.)

    The plural of ``discard_revealed_unless_pay_life``: one offer per card the
    reveal in front of this one showed that the printed phrase names, all on the
    same ``optional_pay`` queue, so the spell stays on the stack until the last
    is answered (CR 608.2, CR 117.3b) and ``web/prompts.py``'s three loops
    render, gate and default them exactly as they do a single one.

    **Each offer carries its own card**, in a *copy* of the resolution's
    scratchpad: ``results`` is one dict for the whole resolution, so writing the
    card into it per offer would leave every branch reading whichever was armed
    last. Nothing after this sentence reads the record, which is what makes the
    copy free.

    The discard names the card rather than a slot. Two copies of one card in a
    hand are the same Python object and the pile renumbers as cards leave, so
    the slot the reveal saw is stale by the second answer —
    ``Game.take_card_from_hand`` removes exactly one, by an index found through
    identity.

    CR 119.4: a player may pay life only with a life total at least the amount,
    so a seat that cannot pay is never offered the choice — it simply discards,
    which is what the sentence says happens when the cost is not paid.
    """
    from .life_and_game import can_pay_life

    victim = context.target if context.target is not None else context.caster
    seat = next((i for i, seated in enumerate(game.players) if seated is victim), None)
    revealed = context.results.get(REVEALED_HAND_CARDS)
    if seat is None or not revealed:
        return True, "resolved"
    described = dict(instruction.payload.get("filter") or {})
    amount = int(instruction.payload.get("life", 0))
    # Re-checked here rather than trusted from the lowering, for the reason
    # every other handler re-checks: the payload describes what the card said,
    # and this is the reader that decides which cards are offered.
    matching = [
        card for card in revealed
        if _card_matches_filter(card, described, game=game, owner=victim)
    ]
    # Read once, before any offer swaps the caster — see ``_DISCARD_CAUSE_SEAT``.
    cause_seat = game.discard_cause_seat()
    for card in matching:
        paying = dataclasses.replace(
            context, caster=victim,
            results={
                **context.results, _DISCARDED_REVEALED_CARD: card,
                _DISCARD_CAUSE_SEAT: cause_seat,
            },
        )
        discard = (
            _OracleInstruction("discard_bound_revealed_card", "", {}),
        )
        if not can_pay_life(victim, amount):
            game._execute_oracle_instruction(discard[0], paying)
            continue
        game.arm_pending_choice(
            "optional_pay", seat,
            card_name=context.card.name if context.card is not None else "",
            cost={},
            life=0,
            _source_permanent=context.source_permanent,
            _on_accept=(_OracleInstruction("pay_life", "", {"amount": amount}),),
            _on_decline=discard,
            _on_reflexive=(),
            _context=paying,
            prompt=f"Pay {amount} life to keep {card.name}?",
        )
    return True, "resolved"


@effect_handler("discard_bound_revealed_card")
def discard_bound_revealed_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The declined branch of one of Sirocco's offers.

    The card is named rather than pointed at by a slot, which is the whole
    difference from ``discard_revealed_card`` beside it: that one is about the
    single card a reveal showed and the slot is what says *which copy*, where
    this one is one of several offers whose answers arrive in any order and
    renumber the pile as they land. ``Game.take_card_from_hand`` removes exactly
    one, by an index found through identity — a hand is the one zone where two
    copies of a card are the same object, so a filter by identity would remove
    both.
    """
    victim = context.target if context.target is not None else context.caster
    card = context.results.get(_DISCARDED_REVEALED_CARD)
    if card is None:
        return True, "resolved"
    if not game.take_card_from_hand(victim, card):
        game.log.append(f"{context.card.name}: {card.name} is no longer in hand")
        return True, "resolved"
    # Through the discard seam, for ``discard_revealed_card``'s reason.
    game._discard_card(
        victim, card, cause_seat=context.results.get(_DISCARD_CAUSE_SEAT)
    )
    game.log.append(f"{victim.name} discards {card.name}")
    return True, "resolved"
