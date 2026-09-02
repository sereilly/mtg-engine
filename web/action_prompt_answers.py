"""Handlers that answer a pending prompt: pickers, confirms, and declines.

Each one validates the client's answer against the prompt the engine armed
(never against the live board - CR 611.2c/603.12 fixed those sets when the
effect began) and hands it to the engine's confirm entry point.
"""

from __future__ import annotations

from fastapi import HTTPException
from engine.text_changes import LAND_TYPE_WORDS
from .action_registry import action_handler
from .turn_steps import _begin_turn, _start_next_turn


@action_handler("search_library_confirm")
def _action_search_library_confirm(session, req, seat_type):
    pending = session.game.pending_search_library
    if pending is None:
        raise HTTPException(status_code=400, detail="no library search pending")
    if req.seat != pending["caster_index"]:
        raise HTTPException(status_code=400, detail="not your library search")
    # A counted search ("up to two basic land cards") is answered whole: every
    # find in one pick list. The engine validates the set together — zones,
    # restriction, no card twice — so a bad combination is a refused answer.
    if req.search_picks is not None:
        picks = [
            {"zone": pick.zone, "index": pick.index} for pick in req.search_picks
        ]
        ok = session.game.confirm_search_library_picks(req.seat, picks)
        if not ok:
            raise HTTPException(status_code=400, detail="invalid search picks")
        return
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index (library card index) is required")
    # Which zone the index addresses. The engine checks it against the zones
    # the search was armed with, so naming the graveyard on a library-only
    # search is a rejected answer rather than a widened effect.
    zone = req.search_zone or "library"
    if zone not in {"library", "graveyard"}:
        raise HTTPException(status_code=400, detail="unknown search zone")
    ok = session.game.confirm_search_library(req.seat, req.hand_index, zone)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid library card index")

@action_handler("search_library_decline")
def _action_search_library_decline(session, req, seat_type):
    pending = session.game.pending_search_library
    if pending is None:
        raise HTTPException(status_code=400, detail="no library search pending")
    if req.seat != pending["caster_index"]:
        raise HTTPException(status_code=400, detail="not your library search")
    # Failing to find is legal (CR 701.19b) and is the only answer available
    # when nothing in the searched zones matches the restriction.
    session.game.decline_search_library(req.seat)

@action_handler("search_destination_confirm")
def _action_search_destination_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("search_destination")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no destination choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.search_assignments is None:
        raise HTTPException(status_code=400, detail="search_assignments is required")
    # One printed-slot index per found card, distinct — the engine re-checks
    # the mapping, so a stale or doubled slot is a refused answer.
    ok = session.game.confirm_search_destination(req.seat, req.search_assignments)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid destination assignment")

@action_handler("look_top_pick_confirm")
def _action_look_top_pick_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("look_top_pick")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no look choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index (looked-at card index) is required")
    ok = session.game.confirm_look_top_pick(req.seat, req.hand_index)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid card index")

@action_handler("name_and_strip_confirm")
def _action_name_and_strip_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("name_and_strip")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no name choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    ok = session.game.confirm_name_and_strip(req.seat, req.card_name)
    if not ok:
        raise HTTPException(
            status_code=400, detail="a basic land's name cannot be chosen"
        )

@action_handler("name_and_random_reveal_confirm")
def _action_name_and_random_reveal_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("name_and_random_reveal")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no name choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    session.game.confirm_name_and_random_reveal(req.seat, req.card_name)

@action_handler("name_then_reveal_top_confirm")
def _action_name_then_reveal_top_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("name_then_reveal_top")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no name choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    if not session.game.confirm_name_then_reveal_top(req.seat, req.card_name):
        raise HTTPException(status_code=400, detail="the name could not be applied")

@action_handler("graveyard_pick_for_price_confirm")
def _action_graveyard_pick_for_price_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("graveyard_pick_for_price")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no graveyard pick pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.graveyard_index is None:
        raise HTTPException(status_code=400, detail="graveyard_index is required")
    if not session.game.confirm_graveyard_pick_for_price(
        req.seat, req.graveyard_index
    ):
        raise HTTPException(status_code=400, detail="that card cannot be chosen")


@action_handler("name_then_consult_confirm")
def _action_name_then_consult_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("name_then_consult")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no name choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    if not session.game.confirm_name_then_consult(req.seat, req.card_name):
        raise HTTPException(status_code=400, detail="the name could not be applied")


@action_handler("trigger_target_confirm")
def _action_trigger_target_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("trigger_target")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no trigger target pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.target_permanent_id is None:
        raise HTTPException(status_code=400, detail="target_permanent_id is required")
    # Checked against the list the prompt offered, not against the board:
    # CR 603.3d chose the targets as the ability went on the stack.
    ok = session.game.confirm_trigger_target(req.seat, req.target_permanent_id)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid target")

@action_handler("reflexive_target_confirm")
def _action_reflexive_target_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("reflexive_target")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no reflexive target pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.target_permanent_id is None:
        raise HTTPException(status_code=400, detail="target_permanent_id is required")
    # Checked against the list the prompt offered, not against the board:
    # CR 603.12's ability chose its targets when it was created.
    ok = session.game.confirm_reflexive_target(req.seat, req.target_permanent_id)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid target")

@action_handler("copy_spell_target_confirm")
def _action_copy_spell_target_confirm(session, req, seat_type):
    """CR 707.10: the copy's controller re-aiming it, by stable id or by seat.

    "Any target" is a player *or* a permanent (CR 115.4), so this answer carries
    either — and both are checked back against the list the prompt offered, so a
    client that invents a candidate is refused rather than obeyed.
    """
    pending = next(
        (c for c in session.game.pending_choices_of("copy_spell_target")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no copy target pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.target_permanent_id is None and req.target_seat is None:
        raise HTTPException(
            status_code=400, detail="target_permanent_id or target_seat is required"
        )
    ok = session.game.confirm_copy_spell_target(
        req.seat,
        permanent_id=req.target_permanent_id,
        target_seat=req.target_seat,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid target")


@action_handler("permanent_choice_confirm")
def _action_permanent_choice_confirm(session, req, seat_type):
    # The general "a permanent chosen as the spell resolves" prompt. Answered by
    # stable id and re-checked by the engine against the live candidate rule, so
    # a client that offers a whole battlefield cannot widen the choice.
    pending = next(
        (c for c in session.game.pending_choices_of("permanent_choice")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no permanent choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.target_permanent_id is None and not pending.data.get("optional"):
        raise HTTPException(status_code=400, detail="target_permanent_id is required")
    # A missing id is a *decline*, and only where the card printed one
    # (Takklemaggot's "If they don't"). The engine re-checks the same flag, so a
    # client that omits the id on a mandatory choice is refused there too.
    if not session.game.confirm_permanent_choice(req.seat, req.target_permanent_id):
        raise HTTPException(status_code=400, detail="invalid permanent choice")

@action_handler("permanent_set_choice_confirm")
def _action_permanent_set_choice_confirm(session, req, seat_type):
    # The plural of the prompt above: several permanents chosen as the effect
    # resolves, by stable id, re-checked by the engine against the same live
    # candidate rule and against the printed ceiling.
    pending = next(
        (c for c in session.game.pending_choices_of("permanent_set_choice")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no permanent choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    # An empty list is legal — "up to two" includes none. The engine refuses a
    # list that is too long or names something it did not offer, so a client
    # cannot widen the choice by sending more.
    if not session.game.confirm_permanent_set_choice(
        req.seat, req.target_permanent_ids or []
    ):
        raise HTTPException(status_code=400, detail="invalid permanent selection")

@action_handler("tap_any_number_confirm")
def _action_tap_any_number_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("tap_any_number")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no tap choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    # An empty list is legal: "any number" includes none, and the card says
    # "you **may**". The engine re-checks every id against the same list the
    # prompt offered, so a stale pick is refused rather than silently
    # dropped.
    ok = session.game.confirm_tap_any_number(req.seat, req.target_permanent_ids or [])
    if not ok:
        raise HTTPException(status_code=400, detail="invalid tap selection")

@action_handler("untap_up_to_confirm")
def _action_untap_up_to_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("untap_up_to")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no untap choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    # An empty list is legal — "up to" includes zero (CR 601.2c's cousin
    # on resolution); the ids ride the same field every other action uses.
    ok = session.game.confirm_untap_up_to(req.seat, req.target_permanent_ids or [])
    if not ok:
        raise HTTPException(status_code=400, detail="invalid untap selection")

@action_handler("search_exile_confirm")
def _action_search_exile_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("search_exile_cards")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no exile search pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your search")
    picks = [
        {"zone": pick.zone, "index": pick.index}
        for pick in (req.search_picks or [])
    ]
    # An empty list is the fail-to-find (CR 701.23b): "any number" includes
    # zero, so no separate decline action exists.
    ok = session.game.confirm_search_exile(req.seat, picks)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid search picks")

@action_handler("reorder_library_confirm")
def _action_reorder_library_confirm(session, req, seat_type):
    pending = session.game.pending_reorder_library
    if pending is None:
        raise HTTPException(status_code=400, detail="no library reorder pending")
    if req.seat != pending["caster_index"]:
        raise HTTPException(status_code=400, detail="not your library reorder")
    if req.card_order is None:
        raise HTTPException(status_code=400, detail="card_order is required")
    ok = session.game.confirm_reorder_library(req.seat, req.card_order, shuffle=bool(req.shuffle))
    if not ok:
        raise HTTPException(status_code=400, detail="invalid card order")

@action_handler("scry_confirm")
def _action_scry_confirm(session, req, seat_type):
    pending = session.game.pending_scry
    if pending is None:
        raise HTTPException(status_code=400, detail="no scry pending")
    if req.seat != pending["caster_index"]:
        raise HTTPException(status_code=400, detail="not your scry")
    if req.card_order is None or req.bottom_count is None:
        raise HTTPException(status_code=400, detail="card_order and bottom_count are required")
    ok = session.game.confirm_scry(req.seat, req.card_order, req.bottom_count)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid scry arrangement")

@action_handler("revealed_hand_pick_confirm")
def _action_revealed_hand_pick_confirm(session, req, seat_type):
    pending = next(iter(session.game.pending_choices_of("revealed_hand_pick")), None)
    if pending is None:
        raise HTTPException(status_code=400, detail="no revealed-hand choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index is required")
    ok = session.game.confirm_revealed_hand_pick(req.seat, req.hand_index)
    if not ok:
        raise HTTPException(status_code=400, detail="that card cannot be chosen")

@action_handler("discard_confirm")
def _action_discard_confirm(session, req, seat_type):
    pending = session.game.pending_discard
    if pending is None:
        raise HTTPException(status_code=400, detail="no discard pending")
    if req.seat != pending["player_index"]:
        raise HTTPException(status_code=400, detail="not your discard")
    if not req.discard_indices:
        raise HTTPException(status_code=400, detail="discard_indices is required")
    ok = session.game.confirm_discard(
        req.seat, list(req.discard_indices), to_library=bool(req.to_library)
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid discard selection")

@action_handler("hand_to_library_confirm")
def _action_hand_to_library_confirm(session, req, seat_type):
    # Brainstorm, Stunted Growth: which cards go back and in what order. The
    # order of `hand_indices` is the order the card gives ("in any order"), so
    # it is passed through rather than sorted — sorting it would silently take
    # the choice the card offers away.
    if req.hand_indices is None:
        raise HTTPException(status_code=400, detail="hand_indices is required")
    ok = session.game.confirm_hand_to_library(req.seat, list(req.hand_indices))
    if not ok:
        raise HTTPException(status_code=400, detail="invalid card selection")

@action_handler("commander_zone_change_confirm")
def _action_commander_zone_change_confirm(session, req, seat_type):
    # CR 903.9: the owner chooses the command zone, or lets the commander go
    # where it was headed.
    if not any(
        e["player_index"] == req.seat
        for e in session.game.pending_commander_zone_changes
    ):
        raise HTTPException(status_code=400, detail="no commander zone choice pending for you")
    if req.to_command_zone is None:
        raise HTTPException(status_code=400, detail="to_command_zone (true/false) is required")
    ok = session.game.confirm_commander_zone_change(
        req.seat, to_command_zone=bool(req.to_command_zone)
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid commander zone choice")

@action_handler("leng_discard_confirm")
def _action_leng_discard_confirm(session, req, seat_type):
    # Library of Leng: choose where an already-discarded card goes — top of
    # library (the optional replacement) or graveyard.
    if not any(
        e["player_index"] == req.seat for e in session.game.pending_leng_discards
    ):
        raise HTTPException(status_code=400, detail="no Library of Leng choice pending for you")
    ok = session.game.confirm_leng_discard(req.seat, to_library=bool(req.to_library))
    if not ok:
        raise HTTPException(status_code=400, detail="invalid Library of Leng choice")

@action_handler("optional_damage_redirect_confirm")
def _action_optional_damage_redirect_confirm(session, req, seat_type):
    # Blood of the Martyr: "you may have that damage dealt to you instead."
    if not any(
        e["player_index"] == req.seat
        for e in session.game.pending_optional_damage_redirects
    ):
        raise HTTPException(status_code=400, detail="no damage redirect choice pending for you")
    if req.take_the_damage is None:
        raise HTTPException(status_code=400, detail="take_the_damage (true/false) is required")
    ok = session.game.confirm_optional_damage_redirect(
        req.seat, take_the_damage=bool(req.take_the_damage)
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid damage redirect choice")

@action_handler("resolve_optional_pay")
def _action_resolve_optional_pay(session, req, seat_type):
    # Color rods (Wooden Sphere, …): "you may pay {1}. If you do, gain life."
    if not any(
        e["player_index"] == req.seat for e in session.game.pending_optional_pays
    ):
        raise HTTPException(status_code=400, detail="no optional pay pending for you")
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept (true/false) is required")
    ok = session.game.confirm_optional_pay(
        req.seat, card_name=req.card_name, accept=bool(req.accept),
        # Which printed cost, for an offer whose options buy different things
        # (Winter's Chill). None everywhere else, which is every other card:
        # there the alternatives cover one consequence and the engine says which
        # it spends.
        option=req.pay_option,
    )
    if not ok:
        # The offer is still owed -- the engine rejected the answer rather than
        # consuming it (CR 601.2b: a player chooses among the options they are
        # able to take). Saying so beats a silent no-op that leaves the same
        # prompt on screen with no explanation.
        raise HTTPException(
            status_code=400, detail="that payment option can't be paid",
        )

@action_handler("pay_life_to_save_confirm")
def _action_pay_life_to_save_confirm(session, req, seat_type):
    # Cleansing: "For each land, destroy that land unless any player pays 1
    # life." One offer at a time, so the answer is just accept/decline.
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept (true/false) is required")
    ok = session.game.confirm_pay_life_to_save(req.seat, bool(req.accept))
    if not ok:
        raise HTTPException(status_code=400, detail="no pay-to-save offer pending for you")

@action_handler("color_set_choice_confirm")
def _action_color_set_choice_confirm(session, req, seat_type):
    # Shyft: "become the color or colors of your choice."
    if not req.mana_colors:
        raise HTTPException(status_code=400, detail="mana_colors is required")
    ok = session.game.confirm_color_set_choice(req.seat, list(req.mana_colors))
    if not ok:
        raise HTTPException(status_code=400, detail="that colour choice is not open")

@action_handler("revealed_draw_buyout_confirm")
def _action_revealed_draw_buyout_confirm(session, req, seat_type):
    # Zur's Weirding: "Then any other player may pay 2 life." One offer at a
    # time, so the answer is just accept/decline.
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept (true/false) is required")
    ok = session.game.confirm_revealed_draw_buyout(req.seat, bool(req.accept))
    if not ok:
        raise HTTPException(
            status_code=400, detail="no revealed-card offer pending for you"
        )

@action_handler("land_type_confirm")
def _action_land_type_confirm(session, req, seat_type):
    # Phantasmal Terrain: the controller picks the enchanted land's basic type.
    if not req.land_type:
        raise HTTPException(status_code=400, detail="land_type is required")
    ok = session.game.confirm_land_type(req.seat, req.land_type)
    if not ok:
        raise HTTPException(status_code=400, detail="no land-type choice pending for you")

@action_handler("confirm_mana_payment")
def _action_confirm_mana_payment(session, req, seat_type):
    # Power Sink: the targeted spell's controller pays {X} to keep their spell,
    # or declines and it is countered. They tap lands to fill their pool first.
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept (true/false) is required")
    ok = session.game.confirm_mana_payment(req.seat, bool(req.accept))
    if not ok:
        raise HTTPException(status_code=400, detail="no mana payment pending for you")

@action_handler("kudzu_reattach_confirm")
def _action_kudzu_reattach_confirm(session, req, seat_type):
    # Kudzu: the controller picks which land to re-enchant (battlefield index).
    if req.target_permanent_index is None:
        raise HTTPException(status_code=400, detail="target_permanent_index is required")
    ok = session.game.confirm_kudzu_reattach(req.seat, req.target_permanent_index)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid Kudzu reattach selection")

@action_handler("flip_again_confirm")
def _action_flip_again_confirm(session, req, seat_type):
    # Game of Chaos: the player the last flip favoured says whether it happens
    # again, at double the stake. Only that seat may answer — the offer is made
    # to one player and the other has just lost the round.
    pending = next(
        (c for c in session.game.pending_choices_of("flip_again")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no coin flip pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not session.game.confirm_flip_again(req.seat, req.accept is not False):
        raise HTTPException(status_code=400, detail="invalid coin-flip answer")

@action_handler("exile_from_hand_confirm")
def _action_exile_from_hand_confirm(session, req, seat_type):
    # Ice Cauldron: the seat picks a card in its hand to exile under the
    # artifact, or declines (accept=False / no hand_index). Declining is always
    # an answer here — the sentence says "you may" — and the engine re-checks
    # the pick against the same candidate rule the prompt was drawn from, so a
    # client offering a whole hand cannot widen the choice.
    pending = next(
        (c for c in session.game.pending_choices_of("exile_from_hand_choice")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no card exile pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    hand_index = None if req.accept is False else req.hand_index
    if not session.game.confirm_exile_from_hand_choice(req.seat, hand_index):
        raise HTTPException(status_code=400, detail="invalid card choice")

@action_handler("put_from_hand_confirm")
def _action_put_from_hand_confirm(session, req, seat_type):
    # Eureka: the offered seat picks a card in its hand to put onto the
    # battlefield, or declines (accept=False / no hand_index). The engine
    # re-checks the pick against the same candidate rule the prompt was drawn
    # from, so a client offering a whole hand cannot widen the choice — and it
    # refuses a decline the sentence never offered.
    pending = next(
        (c for c in session.game.pending_choices_of("put_from_hand_choice")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no card choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    hand_index = None if req.accept is False else req.hand_index
    if hand_index is None and req.accept is not False:
        raise HTTPException(status_code=400, detail="hand_index is required")
    if not session.game.confirm_put_from_hand_choice(req.seat, hand_index):
        raise HTTPException(status_code=400, detail="invalid card choice")

@action_handler("choose_cards_in_hand_confirm")
def _action_choose_cards_in_hand_confirm(session, req, seat_type):
    # Sylvan Library: the seat picks which of its eligible cards the next step
    # acts on. The engine re-checks the picks against the same candidate rule
    # the prompt was drawn from, so a client sending a whole hand cannot widen
    # the choice — and it refuses a short answer, because the sentence names a
    # number and a partial pick is not one of its outcomes.
    pending = next(
        (c for c in session.game.pending_choices_of("choose_cards_in_hand")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no hand choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.hand_indices is None:
        raise HTTPException(status_code=400, detail="hand_indices is required")
    if not session.game.confirm_choose_cards_in_hand(req.seat, req.hand_indices):
        raise HTTPException(status_code=400, detail="invalid card choice")


@action_handler("graveyard_exile_confirm")
def _action_graveyard_exile_confirm(session, req, seat_type):
    # Rysorian Badger: the seat picks which cards in the defending player's
    # graveyard to exile. The engine re-checks the picks against the same
    # candidate rule the prompt was drawn from, so a client sending the whole
    # pile cannot widen the choice — and the empty answer is legal here,
    # because the sentence says "up to".
    pending = next(
        (c for c in session.game.pending_choices_of("graveyard_exile_pick")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no graveyard choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.graveyard_indices is None:
        raise HTTPException(status_code=400, detail="graveyard_indices is required")
    if not session.game.confirm_graveyard_exile_pick(
        req.seat, req.graveyard_indices
    ):
        raise HTTPException(status_code=400, detail="invalid card choice")


@action_handler("face_down_cast_confirm")
def _action_face_down_cast_confirm(session, req, seat_type):
    # Illusionary Mask: the controller picks a hand creature to cast face down,
    # or declines (accept=False / no hand_index).
    if req.accept is False:
        hand_index = -1
    elif req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index is required")
    else:
        hand_index = req.hand_index
    ok = session.game.confirm_face_down_cast(req.seat, hand_index)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid face-down cast selection")

@action_handler("time_vault_skip")
def _action_time_vault_skip(session, req, seat_type):
    # Time Vault: skip the turn you are beginning to untap the artifact.
    if req.seat != session.current_turn or not session.time_vault_pending:
        raise HTTPException(status_code=400, detail="no Time Vault skip is pending for you")
    name = req.card_name or (session.time_vault_pending[0] if session.time_vault_pending else None)
    if not name or not session.game.untap_for_skip(req.seat, name):
        raise HTTPException(status_code=400, detail="cannot skip to untap that permanent")
    session.time_vault_resolved_turn = session.game.turn
    session.time_vault_pending = []
    _start_next_turn(session)  # the skipped player's turn does not run

@action_handler("time_vault_decline")
def _action_time_vault_decline(session, req, seat_type):
    # Decline the skip and take the turn normally.
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    session.time_vault_resolved_turn = session.game.turn
    session.time_vault_pending = []
    _begin_turn(session, req.seat, defer_untap_selection=True)

@action_handler("lamp_draw_confirm")
def _action_lamp_draw_confirm(session, req, seat_type):
    # Aladdin's Lamp: the player picks which of the revealed top cards to
    # draw (hand_index = position in the revealed list).
    pending = session.game.pending_lamp_draw
    if pending is None or pending.get("player_index") != req.seat:
        raise HTTPException(status_code=400, detail="no Aladdin's Lamp draw is pending for you")
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index is required")
    if not session.game.confirm_lamp_draw(req.seat, req.hand_index):
        raise HTTPException(status_code=400, detail="invalid card choice")

@action_handler("outside_game_draw_confirm")
def _action_outside_game_draw_confirm(session, req, seat_type):
    # Ring of Ma'rûf: the player picks which card they own from outside the
    # game to put into their hand (hand_index = position in the sideboard).
    pending = session.game.pending_outside_game_draw
    if pending is None or pending.get("player_index") != req.seat:
        raise HTTPException(status_code=400, detail="no outside-the-game choice is pending for you")
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index is required")
    if not session.game.confirm_outside_game_draw(req.seat, req.hand_index):
        raise HTTPException(status_code=400, detail="invalid card choice")

@action_handler("opponent_damage_choose")
def _action_opponent_damage_choose(session, req, seat_type):
    # Cuombajj Witches: the opposing chooser picks any target for the second
    # damage packet — a player face (target_permanent_index omitted) or a
    # creature on target_seat's battlefield.
    pending = session.game.pending_opponent_damage
    if pending is None or pending.get("chooser_index") != req.seat:
        raise HTTPException(status_code=400, detail="no opponent damage choice is pending for you")
    if req.target_seat is None or not (0 <= req.target_seat < len(session.game.players)):
        raise HTTPException(status_code=400, detail="target_seat is required")
    if not session.game.confirm_opponent_damage_choice(
        req.seat, req.target_seat, req.target_permanent_index
    ):
        raise HTTPException(status_code=400, detail="failed to resolve the damage choice")

@action_handler("enter_choice_confirm")
def _action_enter_choice_confirm(session, req, seat_type):
    # Black Vise / Jihad: the controller confirms the "as this enters"
    # choice — an opponent (target_seat) and, for Jihad, a color (mana_color).
    pending = session.game.pending_enter_choice
    if pending is None or pending.get("controller_index") != req.seat:
        raise HTTPException(status_code=400, detail="no enter choice is pending for you")
    # "…choose two basic land types." (Illusionary Terrain.) The one shape of
    # this prompt that names no seat at all, so `target_seat` is not required
    # for it; the pair arrives as the two colour fields the text-change spells
    # already use, where a basic land type is addressed by its colour
    # (W=plains, U=island, B=swamp, R=mountain, G=forest) — `old_color` is the
    # first chosen type and `mana_color` the second, and the order is the whole
    # of what the static reads.
    if pending.get("needs_land_types"):
        words = LAND_TYPE_WORDS
        pair = [words.get(req.old_color or ""), words.get(req.mana_color or "")]
        if not all(pair):
            raise HTTPException(
                status_code=400,
                detail="old_color (first chosen type) and mana_color (second) are required",
            )
        if not session.game.confirm_enter_choice(req.seat, land_types=pair):
            raise HTTPException(status_code=400, detail="invalid enter choice")
        return
    # "…choose a creature type." (An-Zerrin Ruins.) The other shape of this
    # prompt that names no seat, so `target_seat` is not required for it
    # either. The word travels as itself rather than as a colour: CR 205.3m's
    # catalog has no five-way encoding to borrow, and the engine checks it
    # against the same vocabulary the prompt offered.
    if pending.get("needs_creature_type"):
        if not req.creature_type:
            raise HTTPException(
                status_code=400, detail="creature_type is required"
            )
        if not session.game.confirm_enter_choice(
            req.seat, creature_type=req.creature_type
        ):
            raise HTTPException(status_code=400, detail="invalid enter choice")
        return
    if req.target_seat is None:
        raise HTTPException(status_code=400, detail="target_seat is required")
    if not session.game.confirm_enter_choice(req.seat, req.target_seat, req.mana_color):
        raise HTTPException(status_code=400, detail="invalid enter choice")

@action_handler("number_choice_confirm")
def _action_number_choice_confirm(session, req, seat_type):
    # Shapeshifter: "choose a number between 0 and 7", as it enters and again
    # at each of its controller's upkeeps.
    if req.number is None:
        raise HTTPException(status_code=400, detail="number is required")
    if not session.game.confirm_number_choice(req.seat, req.number):
        raise HTTPException(status_code=400, detail="no number choice is pending for you")

@action_handler("body_choice_confirm")
def _action_body_choice_confirm(session, req, seat_type):
    # Primal Clay: the controller picks which printed body the creature
    # entered as (hand_index = position in the offered options).
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index (body option index) is required")
    if not session.game.confirm_enter_body_choice(req.seat, req.hand_index):
        raise HTTPException(status_code=400, detail="no body choice is pending for you")

@action_handler("entry_exile_confirm")
def _action_entry_exile_confirm(session, req, seat_type):
    # Frankenstein's Monster: the entry cost ("exile X creature cards from your
    # graveyard") and the counter each exiled card buys, in one answer - they
    # are one decision made as the permanent enters (CR 614.1c), and sending
    # them apart would leave the creature on the battlefield at a size nobody
    # chose. The engine re-checks every index against the graveyard positions
    # the printed noun phrase admits, so the prompt's list is a hint.
    if req.entry_exile_picks is None:
        raise HTTPException(status_code=400, detail="entry_exile_picks is required")
    picks = [
        {"index": pick.index, "counter": pick.counter}
        for pick in req.entry_exile_picks
    ]
    if not session.game.resolve_pending_choice("entry_exile", req.seat, picks=picks):
        raise HTTPException(
            status_code=400,
            detail=(
                "no entry exile is pending for you, or those cards and counters "
                "are not the ones offered"
            ),
        )

@action_handler("mode_choice_confirm")
def _action_mode_choice_confirm(session, req, seat_type):
    # A modal ability (Relic Bind, Trufflesnout, Elder Gargaroth): the
    # controller picks a mode (hand_index = position in the offered list) and,
    # for a mode that targets, that mode's target in the same answer - CR
    # 700.2b and CR 601.2c make them one announcement, so sending them apart
    # would leave the ability on the stack half-announced.
    #
    # The target is named by stable id for an object and by seat for a player,
    # and the engine matches it against the very list this prompt offered.
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index (mode index) is required")
    target = None
    if req.target_permanent_id is not None or req.target_seat is not None:
        target = {"permanent_id": req.target_permanent_id, "seat": req.target_seat}
    if not session.game.resolve_pending_choice(
        "mode_choice", req.seat, mode_index=req.hand_index, target=target
    ):
        raise HTTPException(
            status_code=400,
            detail="no mode choice is pending for you, or that mode and target are not offered",
        )

@action_handler("loyalty_recipient_confirm")
def _action_loyalty_recipient_confirm(session, req, seat_type):
    # Liliana's Scrounger: which planeswalker the loyalty counter lands on.
    # Answered by stable id — the engine re-checks it against the live
    # candidate set — never by battlefield slot.
    if req.target_permanent_id is None:
        raise HTTPException(status_code=400, detail="target_permanent_id is required")
    if not session.game.confirm_loyalty_recipient(req.seat, req.target_permanent_id):
        raise HTTPException(status_code=400, detail="invalid loyalty-counter recipient")

@action_handler("least_power_choice_confirm")
def _action_least_power_choice_confirm(session, req, seat_type):
    # Drop of Honey: the controller picks which of the creatures tied for
    # least power is destroyed (target_seat + target_permanent_index).
    pending = session.game.pending_least_power_choice
    if pending is None or pending.get("controller_index") != req.seat:
        raise HTTPException(status_code=400, detail="no least-power choice is pending for you")
    if req.target_seat is None or req.target_permanent_index is None:
        raise HTTPException(status_code=400, detail="target_seat and target_permanent_index are required")
    if not session.game.confirm_least_power_choice(
        req.seat, req.target_seat, req.target_permanent_index
    ):
        raise HTTPException(status_code=400, detail="invalid creature choice")

@action_handler("player_choice_confirm")
def _action_player_choice_confirm(session, req, seat_type):
    # Backdraft: "Choose a player who cast one or more sorcery spells this
    # turn." The engine re-checks the seat against the offered list, so a stale
    # answer is refused rather than applied to whoever now sits there.
    if req.chosen_seat is None:
        raise HTTPException(status_code=400, detail="chosen_seat is required")
    if not session.game.confirm_player_choice(req.seat, req.chosen_seat):
        raise HTTPException(status_code=400, detail="invalid player choice")

@action_handler("cast_choice_confirm")
def _action_cast_choice_confirm(session, req, seat_type):
    # Backdraft: which of the offered spells "one of those" names, by its
    # position in the turn's cast ledger.
    if req.cast_index is None:
        raise HTTPException(status_code=400, detail="cast_index is required")
    if not session.game.confirm_cast_choice(req.seat, req.cast_index):
        raise HTTPException(status_code=400, detail="invalid spell choice")

@action_handler("retarget_choice_confirm")
def _action_retarget_choice_confirm(session, req, seat_type):
    # Deflection: which legal target replaces the one the spell announced, by
    # its position in the offered list. The engine re-checks that position
    # against the candidates that are *still* legal (CR 115.7a), so an answer
    # naming a creature that has since died is refused rather than applied to
    # whatever slid into its place.
    if req.target_index is None:
        raise HTTPException(status_code=400, detail="target_index is required")
    if not session.game.confirm_retarget_choice(req.seat, req.target_index):
        raise HTTPException(status_code=400, detail="invalid target choice")

@action_handler("word_of_command_confirm")
def _action_word_of_command_confirm(session, req, seat_type):
    # Word of Command: the caster records the card the target must play
    # (accept=False / no hand_index declines). The spell stays on the stack
    # and finishes resolving when priority is next released.
    if req.accept is False:
        hand_index = -1
    elif req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index is required")
    else:
        hand_index = req.hand_index
    ok = session.game.confirm_word_of_command(req.seat, hand_index, defer_resolution=True)
    if not ok:
        raise HTTPException(status_code=400, detail="no Word of Command pending for you")

@action_handler("balance_confirm")
def _action_balance_confirm(session, req, seat_type):
    pending = session.game.pending_balance
    if pending is None or req.seat not in pending["plans"]:
        raise HTTPException(status_code=400, detail="no balance choice pending for you")
    ok = session.game.confirm_balance(
        req.seat,
        land_indices=req.land_indices or [],
        creature_indices=req.creature_indices or [],
        hand_indices=req.discard_indices or [],
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid balance selection (wrong number of cards)")

@action_handler("sacrifice_confirm")
def _action_sacrifice_confirm(session, req, seat_type):
    pending = session.game.pending_sacrifice
    if pending is None or req.seat != pending["player_index"]:
        raise HTTPException(status_code=400, detail="no sacrifice pending for you")
    # A beginning phase this sacrifice paused resumes from the action tail in
    # web/actions.py, along with every other prompt's — the resume used to live
    # here, which is why a phase paused on any other decision stayed paused.
    ok = session.game.confirm_sacrifice(req.seat, list(req.sacrifice_indices or []))
    if not ok:
        raise HTTPException(status_code=400, detail="invalid sacrifice selection")

@action_handler("effect_order_confirm")
def _action_effect_order_confirm(session, req, seat_type):
    # CR 616.1e: the affected player picks which of the effects contending
    # over one event applies first. Answering re-runs the event, so this
    # returns with the draw made or the damage dealt.
    if not session.game.resolve_pending_choice(
        "effect_order", req.seat, option_index=int(req.option_index or 0)
    ):
        raise HTTPException(status_code=400, detail="no effect order pending for you")

@action_handler("dismiss_hand_reveal")
def _action_dismiss_hand_reveal(session, req, seat_type):
    session.game.dismiss_hand_reveal(req.seat)
