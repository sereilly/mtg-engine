"""A **look** and the library's top: a pile shown to one player, or to nobody.

The handler twin of ``engine/grammar/lowering/library.py``. The top cards of a
library looked at and then put back in an order (Sage Owl, Tahngarth's Glare),
picked from (See the Truth), exiled from at random (Orcish Librarian), cycled
(Lim-Dul's Vault), split into piles (Phyrexian Portal) or sent to the bottom
(Coral Fighters); a hand looked at, Word of Command's among them; and a card
moved onto the top or off it with nobody choosing — Guiding Spirit's creature
card off a graveyard, and Scroll Rack's "put that many cards from the top of
your library into your hand", which is not a draw.

Split out of ``zones.py`` at the 2,000-line cap's split round. A **reveal** (the
public half, CR 701.20a) is ``reveal.py``'s; a scry and a surveil are
``cards.py``'s, beside the draw and the mill.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..models import PlayerState
from ._amounts import resolve_amount
from ._filters import _card_matches_filter
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("reorder_target_library_top")
def reorder_target_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    caster_index = game.players.index(caster)
    target_index = game.players.index(target)
    # The printed number, which the lowering has always carried and this read
    # as a literal 3 — true of both cards that printed the sentence (Natural
    # Selection, Portent) and of the third (Tahngarth's Glare), so no game has
    # played differently; a fourth card printing "the top five" would have
    # looked at three.
    top_count = min(int(instruction.payload.get("amount", 3)), len(target.library))
    # "You may have that player shuffle" (Natural Selection) lets the caster
    # optionally shuffle the target's library after reordering. Read off the
    # instruction, not the card: a handler that re-reads oracle text is a second
    # reading of a sentence the compiler already read, and the two drift.
    may_shuffle = bool(instruction.payload.get("may_shuffle"))
    game.arm_pending_choice(
        "reorder_library", caster_index,
        target_index=target_index, top_count=top_count, may_shuffle=may_shuffle,
    )
    game.log.append(f"{caster.name} is looking at the top {top_count} cards of {target.name}'s library")
    return True, "pending_reorder_library"


@effect_handler("reorder_own_library_top")
def reorder_own_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Look at the top four cards of your library, then put them back in any
    order." (Sage Owl.)

    ``reorder_target_library_top`` over the looker's **own** pile, and its own
    kind rather than that one with a seat swapped: that kind is registered in
    ``engine/targeting.py`` as targeting a player, so a trigger lowered onto it
    would go on the stack asking for a target Sage Owl never offers.

    One seat answers and one library is rearranged, and they are the same
    player by construction — the printed possessive says so — which is why
    neither is read off a target. How many cards is payload, where the printed
    sentence put it; the library being shorter is not an error (CR 609.3's "as
    many as you can"), and with fewer than two cards there is no order left to
    choose, so nothing is asked.
    """
    caster = context.caster
    seat = game.players.index(caster)
    top_count = min(
        resolve_amount(instruction.payload.get("amount", 0), context.x_value),
        len(caster.library),
    )
    if top_count < 2:
        game.log.append(
            f"{caster.name} has no order left to choose ({context.card.name})"
        )
        return True, "resolved"
    game.arm_pending_choice(
        "reorder_library", seat,
        target_index=seat, top_count=top_count, may_shuffle=False,
    )
    game.log.append(
        f"{caster.name} is looking at the top {top_count} cards of their library"
    )
    return True, "pending_reorder_library"


@effect_handler("target_reorders_caster_library_top")
def target_reorders_caster_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"**That player** looks at the top three cards of your library, then puts
    them back in any order." (Tahngarth's Glare.)

    ``reorder_target_library_top`` with both seats the other way round: the
    player the sentence in front chose **answers**, and the pile rearranged is
    the resolving player's own. Two questions the prompt already keeps apart —
    who is asked (``player_index``) and whose library (``target_index``) — so
    it is that prompt with its seats swapped and not a second one.

    The looker is the resolution's own target, read where "that player loses 2
    life" reads it. With none there — the target gone illegal is caught above
    every instruction (CR 608.2b), so this is a line with no player in front of
    it — nobody looks, which is the direction that hands no one a look the card
    did not give them.

    A short library is CR 609.3's "as many as you can" — and **one** card is
    still a look. ``reorder_own_library_top`` asks nothing below two, because
    there a player is looking at their own pile and only the order is at stake;
    here the looker is somebody else, and what the top card *is* is information
    the sentence gives them whether or not there is anything to rearrange. So
    the prompt is raised for one card, as the targeted look beside this raises
    it, and only an empty library shows nothing.
    """
    looker = context.target
    owner = context.caster
    if not isinstance(looker, PlayerState):
        game.log.append(
            f"{context.card.name}: no player was chosen to look"
        )
        return True, "resolved"
    top_count = min(
        resolve_amount(instruction.payload.get("amount", 0), context.x_value),
        len(owner.library),
    )
    if top_count < 1:
        game.log.append(
            f"{owner.name} has no cards for {looker.name} to look at "
            f"({context.card.name})"
        )
        return True, "resolved"
    owner_index = game.players.index(owner)
    game.arm_pending_choice(
        "reorder_library", game.players.index(looker),
        target_index=owner_index, top_count=top_count, may_shuffle=False,
    )
    game.log.append(
        f"{looker.name} is looking at the top {top_count} cards of "
        f"{owner.name}'s library"
    )
    return True, "pending_reorder_library"


@effect_handler("graveyard_top_to_library")
def graveyard_top_to_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If the top card of target player's graveyard is a creature card, put
    that card on top of that player's library." (Guiding Spirit.)

    The printed "if" is performed here rather than as a condition over this
    step, because both halves name the same card: the top of the graveyard is
    read once, tested, and moved. Split into an ``if_then`` the test would ask
    about one card and the move would go and find the top again — the same card
    today and a different one the moment anything at all happens between them.

    **The top of a graveyard is the last card put into it**, which this engine
    keeps as the *end* of the list: every path that bins a card appends. So the
    read is ``[-1]``, and getting that backwards would move the oldest card in
    the pile — a card that plays, reports supported and does the wrong thing.

    Through ``Game.put_card_into_library``, the one seam every "put this card
    into a library" goes through (CR 903.9b has no single fire site).
    """
    target = context.target
    if target is None:
        return False, "no target player"
    if not target.graveyard:
        game.log.append(f"{context.card.name}: {target.name}'s graveyard is empty")
        return True, "resolved"
    top = target.graveyard[-1]
    described = instruction.payload.get("filter") or {}
    if described and not _card_matches_filter(
        top, described, game=game, owner=target
    ):
        game.log.append(
            f"{context.card.name}: {top.name} is not what the ability names"
        )
        return True, "resolved"
    # Popped by index rather than by ``remove``: two copies of a card in a deck
    # are the same immutable ``CardDefinition``, so a value comparison would
    # take whichever entry came first.
    target.graveyard.pop(len(target.graveyard) - 1)
    game.put_card_into_library(target, top, "top")
    game.log.append(
        f"{context.card.name}: {top.name} goes on top of {target.name}'s library"
    )
    return True, "resolved"


@effect_handler("look_at_target_library_top")
def look_at_target_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Look at the top five cards of target player's library. You may then
    have that player shuffle that library." (Visions.)

    The same prompt ``reorder_target_library_top`` above raises, with the
    rearranging switched off — the two cards look at the same pile and offer
    the same shuffle, and Visions simply never gets to put the cards back in an
    order of its choosing. ``may_reorder`` is enforced in
    ``Game._resolve_reorder_library`` rather than only in the UI: a permission
    the client alone honours is a rule nothing enforces.

    How many cards and whether the shuffle is offered are read off the payload,
    where the sentence put them.
    """
    caster = context.caster
    target = context.target
    if target is None:
        return False, "no target player"
    top_count = min(
        resolve_amount(instruction.payload.get("amount", 0), context.x_value),
        len(target.library),
    )
    # "Look at the top card of target player's library. **If it's a nonland
    # card**, …" (Wand of Denial.) The sentences behind a look name the card it
    # turned up, and this is the only step that can say which one that is —
    # by the time they run the resolution has suspended on the prompt and come
    # back. Under the key every "is it a …?" clause in this engine already
    # reads: a look and a reveal differ in *who sees* the card (CR 701.20 shows
    # it to everybody), and the pronoun behind either names the same object.
    #
    # Only the single-card look records one, because "it" is unambiguous only
    # there — a look at five cards names no single card at all. The prompt this
    # arms cannot reorder or shuffle, so the card recorded here is still the
    # card on top when the sentences behind it run.
    if top_count == 1 and target.library:
        context.results["revealed_card"] = target.library[0]
    game.arm_pending_choice(
        "reorder_library", game.players.index(caster),
        target_index=game.players.index(target),
        top_count=top_count,
        may_shuffle=bool(instruction.payload.get("may_shuffle")),
        may_reorder=False,
    )
    game.log.append(
        f"{caster.name} is looking at the top {top_count} cards of {target.name}'s library"
    )
    return True, "pending_reorder_library"


@effect_handler("peek_hand_and_force_play")
def peek_hand_and_force_play(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Word of Command: the caster looks at the target's hand and chooses a card
    for that player to play. Arms a pending choice resolved by
    confirm_word_of_command (which plays the chosen card as the target). Also
    surfaces the revealed hand so the UI can show it to the caster."""
    target = context.target
    caster = context.caster
    card = context.card
    if not target.hand:
        game.log.append(f"{card.name}: {target.name} has no cards to play")
        return True, "resolved"
    caster_index = game.players.index(caster)
    target_index = game.players.index(target)
    game.arm_pending_choice(
        "word_of_command", caster_index,
        target_index=target_index, card_name=card.name,
        hand=[c.name for c in target.hand],
    )
    game.log.append(f"{card.name}: {caster.name} looks at {target.name}'s hand to choose a card to force")
    return True, "resolved"


@effect_handler("look_at_target_hand")
def look_at_target_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    viewer = context.caster
    card = context.card
    # ``who: "defending_player"`` names CR 506.2's seat, frozen into the
    # trigger's context by the combat fire site (Port Inspector) — nobody
    # targeted it, so ``context.target`` for this trigger is whatever the
    # resolution was already carrying, which on a becomes-blocked trigger is the
    # *blocker*'s controller by coincidence and the viewer's own seat as soon as
    # the coincidence stops holding. The same key the two discards beside this
    # handler read for the same printed phrase.
    if instruction.payload.get("who") == "defending_player":
        seat = (context.trigger_context or {}).get("trigger_defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            # The attacker can leave combat before this resolves, and a seat
            # nobody recorded is not a hand to show.
            return True, "resolved"
        target = game.players[seat]
    # Record the reveal so the UI can show the viewer the actual cards in the
    # target player's hand (Glasses of Urza). The viewer is the ability's
    # controller; the target is the player whose hand is looked at.
    viewer_index = game.players.index(viewer)
    # Only the most recent reveal is shown, so a second look replaces the first
    # rather than queueing behind it.
    game.clear_pending_choices("hand_reveal", viewer_index)
    # "…**a card at random** in target player's hand" (Urza's Bauble): one card,
    # picked by nobody. Through the module RNG the rest of the engine seeds, so
    # a given seed replays the look exactly. An empty hand shows nothing rather
    # than failing — CR 608.2 does as much as it can.
    if instruction.payload.get("random_card"):
        shown = (
            [random.choice(target.hand).name] if target.hand else []
        )
    else:
        shown = [c.name for c in target.hand]
    game.arm_pending_choice(
        "hand_reveal", viewer_index,
        target_index=game.players.index(target),
        card_names=shown,
    )
    game.log.append(
        f"{card.name}: {viewer.name} looked at "
        + (
            f"{len(shown)} card(s) at random in {target.name}'s hand"
            if instruction.payload.get("random_card")
            else f"{target.name}'s hand ({len(shown)} cards)"
        )
    )
    return True, "resolved"


@effect_handler("separate_library_top_into_piles")
def separate_library_top_into_piles(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Phyrexian Portal, all three of its sentences.

    Three decisions by two seats, so the handler does nothing but hand the
    first of them to the right player: the opponent divides, knowing what is in
    the piles, and the controller chooses and searches without knowing. Each
    later decision is armed by answering the one before it, which keeps the
    whole procedure inside one resolution (CR 608.2, CR 117.3b).

    The ten cards come **out of the library** here and travel on the prompts.
    They are going to exile, to a hand and back into a shuffled library, so
    there is no arrangement of the library that could hold them meanwhile - and
    the alternative, leaving them in place and addressing them by index, is an
    index into a zone the next answer changes.
    """
    caster = context.caster
    splitter = context.target
    if splitter is None or splitter is caster:
        # "Target **opponent**" - the picker enforces it, and a resolution that
        # somehow arrived without one divides nothing rather than handing the
        # caster their own library face down.
        game.log.append(f"{context.card.name}: no opponent to divide the piles")
        return True, "resolved"
    count = resolve_amount(instruction.payload.get("count", 0), context.x_value)
    taken = caster.library[:count]
    if not taken:
        game.log.append(f"{caster.name} has no cards to divide")
        return True, "resolved"
    del caster.library[:count]
    game.arm_pending_choice(
        "library_pile_split", game.players.index(splitter),
        card_name=context.card.name if context.card is not None else "",
        owner_index=game.players.index(caster),
        _cards=list(taken),
        _source_permanent=context.source_permanent,
    )
    return True, "resolved"


@effect_handler("look_top_cycle_and_stack")
def look_top_cycle_and_stack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Lim-Dul's Vault, all three of its sentences (CR 701.24).

    The whole effect is one offer asked over and over, so the handler does
    almost nothing: it announces the first look and arms the offer. Every
    iteration after that is a prompt armed by *answering* the one before it,
    which is how a chain of decisions stays inside one resolution (CR 608.2,
    CR 117.3b) - the ability stays on the stack until the last answer, and the
    shuffle that ends the card happens on the answer that declines.

    Nothing is moved here. "Look at the top five cards" changes no zone; what
    it changes is what one player knows, and the cards it names are simply the
    top of the library at the moment each offer is answered.
    """
    caster = context.caster
    seat = game.players.index(caster)
    count = resolve_amount(instruction.payload.get("count", 0), context.x_value)
    life_cost = resolve_amount(instruction.payload.get("life_cost", 0), context.x_value)
    looked = min(count, len(caster.library))
    game.log.append(
        f"{caster.name} looks at the top {looked} card(s) of their library"
    )
    game.arm_pending_choice(
        "library_cycle_offer", seat,
        card_name=context.card.name if context.card is not None else "",
        count=int(count),
        life_cost=int(life_cost),
    )
    return True, "resolved"


@effect_handler("look_at_library_top_then_bottom")
def look_at_library_top_then_bottom(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Look at the top card of defending player's library. You may put that
    card on the bottom of that player's library." (Coral Fighters.)

    The same decision a scry is — look at the top N and choose which of them go
    to the bottom — over somebody else's pile, so it arms the same prompt with
    ``library_index`` naming whose library it is. Not *called* a scry: the card
    prints no keyword (CR 701.22 arrived long after Mirage) and the pile is not
    the chooser's, and the instruction says what the sentence says.

    Modelled as a choice for the scry handler's stated reason: leaving the card
    on top is a legal outcome and never a legal implementation, because the
    decision is the whole effect.

    Whose library is CR 506.2's defending player, read off what the combat fire
    site froze — the same key ``discard_target_cards`` reads for the seat its
    own untargeted sentence names. No record means the attacker left combat
    before this resolved, and a seat nobody wrote down is not a library to look
    through.
    """
    caster = context.caster
    seat = None
    if instruction.payload.get("who") == "defending_player":
        recorded = (context.trigger_context or {}).get("trigger_defending_player_index")
        seat = recorded if isinstance(recorded, int) else None
    elif context.target is not None:
        seat = game.players.index(context.target)
    if seat is None or not (0 <= seat < len(game.players)):
        game.log.append(f"{context.card.name}: no recorded player, no library to look at")
        return True, "resolved"
    owner = game.players[seat]
    amount = resolve_amount(instruction.payload.get("amount", 1) or 1, context.x_value)
    top_count = min(amount, len(owner.library))
    if top_count <= 0:
        game.log.append(f"{context.card.name}: {owner.name}'s library is empty")
        return True, "resolved"
    game.arm_pending_choice(
        "scry", game.players.index(caster),
        top_count=top_count, amount=amount, card_name=context.card.name,
        library_index=seat,
    )
    game.log.append(
        f"{caster.name} is looking at the top {top_count} of {owner.name}'s library"
    )
    return True, "pending_scry"


@effect_handler("put_library_top_into_hand")
def put_library_top_into_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put that many cards from the top of your library into your hand."
    (Scroll Rack.)

    **Not a draw**, and that is the whole of why it is its own handler.
    CR 121.1 defines a draw as putting the top card of a library into a hand,
    but an effect that spells those words instead of saying "draw" is not one
    (CR 121.5): no "whenever you draw a card" trigger sees it, and no draw
    replacement applies. Routed through ``_draw_with_replacements`` this card
    would ring every draw trigger on the board and be stopped by every draw
    replacement, which is a different card.

    Through ``put_card_into_hand``, the CR 903.9b seam every card reaching a
    hand goes through — a draw is the *only* thing this differs from.

    Fewer cards than asked for is an ordinary board: CR 704.5b's loss fires on
    an attempted **draw** from an empty library, and this is not one, so a short
    library simply gives what it has.
    """
    caster = context.caster
    amount = resolve_amount(instruction.payload.get("amount", 0) or 0, context.x_value)
    recorded = instruction.payload.get("amount_from")
    if recorded is not None:
        amount = int(context.results.get(recorded) or 0)
    taken = caster.library[:max(int(amount), 0)]
    if not taken:
        game.log.append(f"{caster.name} puts no cards into their hand")
        return True, "resolved"
    del caster.library[:len(taken)]
    for card in taken:
        game.put_card_into_hand(caster, card)
    game.log.append(
        f"{caster.name} put {len(taken)} card(s) from the top of their library "
        "into their hand"
    )
    return True, "resolved"


def _merged_pick_filter(filters: tuple) -> dict:
    """One payload for the single-alternative case, empty otherwise.

    ``live_look_top_candidates`` OR's a tuple of alternatives; this keeps the
    older single-filter key meaningful for a caller that reads it, and returns
    nothing when the phrase named several — where no single dict can stand for
    the union without narrowing it.
    """
    return dict(filters[0]) if len(filters) == 1 else {}


@effect_handler("look_top_pick_to_hand")
def look_top_pick_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """See the Truth: look at the top N, put one into your hand and the rest
    on the bottom in any order — unless the spell was cast from anywhere other
    than the hand, in which case every looked-at card goes to the hand and
    there is nothing to choose. ``context.cast_from_zone`` is the field the
    permission-seam round added for exactly this sentence."""
    payload = instruction.payload
    # Whose library. "Target player looks at the top three cards of **their**
    # library" (Ashnod's Cylix) names a seat the activation chose, and the
    # looker and the pile are the same player by construction — the possessive
    # says so — so one lookup answers both. Every other card in this family
    # prints "your library", which is the ability's own controller and the key
    # is absent. A named looker the ability never chose does nothing at all:
    # looking at a library the card did not name would be worse than the
    # ability fizzling, and the pile is hidden, so nobody would see it.
    if payload.get("looker") == "target_player":
        if context.target not in game.players:
            game.log.append(f"{context.card.name}: no player chosen")
            return True, "resolved"
        caster = context.target
    else:
        caster = context.caster
    # "Look at the top X cards of **target opponent's** library. Exile one of
    # those cards…" (Sealed Fate.) The pile is the chosen player's and every
    # decision about it is the caster's — the one shape ``looker`` cannot say,
    # because there one seat answers both questions. A named pile the spell
    # never chose does nothing at all, for ``looker``'s reason: reading the
    # wrong library is worse than the spell fizzling, and the pile is hidden,
    # so nobody would see it.
    chooser = caster
    if payload.get("pile_owner") == "damaged_player":
        # "…**that player** reveals the top two cards of their library."
        # (Balshan Beguiler.) The seat the damage event froze (CR 603.10), off
        # the key every damage announcement stamps — never ``context.target``,
        # which for a trigger that chose nothing is whatever the resolution
        # happened to be carrying. No record, no pile.
        seat = (context.trigger_context or {}).get("defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{context.card.name}: no recorded player, no library")
            return True, "resolved"
        caster = game.players[seat]
    elif payload.get("pile_owner") is not None:
        if context.target not in game.players:
            game.log.append(f"{context.card.name}: no player chosen")
            return True, "resolved"
        caster = context.target
    # "Look at **that many** cards" (Garruk's Harbinger): the number the firing
    # event carried, frozen by the fire site. An absent record looks at nothing
    # rather than falling back to a count the card never printed.
    from_trigger = payload.get("amount_from_trigger")
    if from_trigger is not None:
        amount = max(0, int((context.trigger_context or {}).get(from_trigger, 0)))
    else:
        amount = resolve_amount(payload.get("amount", 0), context.x_value)
    top_count = min(amount, len(caster.library))
    # Written before anything can end the step early: a pick that takes no
    # card (an empty library) took a card with no mana value, and the gain
    # behind it reads zero rather than whatever an earlier step left.
    if payload.get("record_pick"):
        context.results[str(payload["record_pick"])] = 0
    if top_count <= 0:
        game.log.append(f"{caster.name} has no cards to look at")
        return True, "resolved"
    if payload.get("all_to_hand_if_cast_elsewhere") and context.cast_from_zone != "hand":
        taken = [caster.library.pop(0) for _ in range(top_count)]
        caster.hand.extend(taken)
        game.log.append(
            f"{context.card.name} was cast from the {context.cast_from_zone}: "
            f"{caster.name} puts all {top_count} looked-at cards into their hand"
        )
        return True, "resolved"
    caster_index = game.players.index(caster)
    chooser_index = game.players.index(chooser)
    # "**Reveal** a number of cards from the top of your library …" (Eye of
    # Yawgmoth.) CR 701.20a shows the pile to every player, which is the whole
    # difference from the looks this handler otherwise performs (CR 701.20e) —
    # so it is recorded and logged by name, before the pick moves any of them.
    if payload.get("revealed"):
        shown = [card.name for card in caster.library[:top_count]]
        game.record_reveal(caster_index, shown)
        game.log.append(f"{caster.name} reveals {', '.join(shown)}")
    # The narrowing, the optionality and the order the rest go back in all ride
    # the prompt, so what is offered, what an answer is checked against and what
    # a non-interactive seat takes are one rule (``live_look_top_candidates``).
    game.arm_pending_choice(
        "look_top_pick", chooser_index,
        # Whose library is looked through, when that is not the seat answering.
        # Absent for every card but Sealed Fate, so those prompts carry exactly
        # the data they always did.
        **({"pile_index": caster_index} if chooser_index != caster_index else {}),
        top_count=top_count, amount=amount, card_name=context.card.name,
        filter=_merged_pick_filter(payload.get("filters") or ()),
        filters=tuple(payload.get("filters") or ()),
        optional=bool(payload.get("optional")),
        rest_order=payload.get("rest_order", "any"),
        rest_destination=payload.get("rest_destination", "library_bottom"),
        pick_destination=payload.get("pick_destination", "hand"),
        # Whether the pile was shown to the table above (CR 701.20a), which is
        # what lets the answer's log line name the card that was kept. Absent
        # for a look, so those prompts carry exactly the data they always did.
        **({"revealed": True} if payload.get("revealed") else {}),
        # "Put **two** of them into your hand" (Ancestral Memories): how many
        # picks are still owed. One is every other card in the family, and the
        # answer path re-arms the prompt while more are owed — see
        # `_resolve_look_top_pick`.
        remaining=max(1, int(payload.get("pick_count", 1))),
        # "…You gain life equal to that card's mana value." (Reviving Vapors.)
        # Where the answer writes the taken card's mana value, for the step of
        # this same resolution that reads it. Absent for every other printing.
        **(
            {"_record_pick": (context, str(payload["record_pick"]))}
            if payload.get("record_pick") else {}
        ),
    )
    game.log.append(
        f"{chooser.name} is looking at the top {top_count} cards of "
        + ("their library" if chooser is caster else f"{caster.name}'s library")
    )
    return True, "pending_look_top_pick"


@effect_handler("look_top_exile_random")
def look_top_exile_random(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Orcish Librarian: "Look at the top eight cards of your library. Exile
    four of them at random, then put the rest on top of your library in any
    order."

    Nothing here is a decision until the last clause. The exile is at random —
    ``random.sample`` over the module RNG ``run_ai_simulation`` seeds, so a
    seed replays a run exactly — and the rest going back **on top** is the
    order the player chooses, asked through the ``reorder_library`` prompt this
    shares with ``look_top_pick_to_hand``'s top-destination tail.

    A library shorter than the card's number is not an error: CR 609.3-style
    "as many as you can" is the general rule for a count over a zone, so what is
    there is what is looked at and the exile is capped to it.
    """
    caster = context.caster
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    top_count = min(amount, len(caster.library))
    if top_count <= 0:
        game.log.append(f"{caster.name} has no cards to look at")
        return True, "resolved"
    exile_count = min(
        resolve_amount(instruction.payload.get("exile_count", 0), context.x_value),
        top_count,
    )
    looked = caster.library[:top_count]
    del caster.library[:top_count]
    exiled_slots = set(random.sample(range(top_count), exile_count))
    rest = [card for index, card in enumerate(looked) if index not in exiled_slots]
    for index in sorted(exiled_slots):
        caster.exile.append(looked[index])
    caster.library[:0] = rest
    game.log.append(
        f"{caster.name} looked at the top {top_count} cards and exiled "
        f"{exile_count} at random"
    )
    if len(rest) > 1:
        seat = game.seat_index(caster)
        game.arm_pending_choice(
            "reorder_library", seat,
            target_index=seat, top_count=len(rest), may_shuffle=False,
        )
        return True, "pending_reorder_library"
    return True, "resolved"
