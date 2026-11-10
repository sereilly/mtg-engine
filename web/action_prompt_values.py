"""Handlers that answer the prompts answered with a value: a colour, a type, a
word, a body, a number, a payment or a yes.

One handler per kind of prompt, split as the renderers are (its renderer is in
``web/prompt_values.py``): "as this enters, choose ..." and the other colour,
type, body and word choices, how many and how much (a bid, a secret number,
"any amount", a draw up to N), mana paid from the board, the "you may pay"
offers, another flip or another round of a repeated process, whether a
commander goes to the command zone (CR 903.9), the CR 614 replacement offers
(a draw replaced, damage redirected, a discard put elsewhere or paid as an
entry's toll) and CR 616.1e's choice of which effect applies first.

Each one validates the client's answer against the prompt the engine armed
(never against the live board - CR 611.2c/603.12 fixed those sets when the
effect began) and hands it to the engine's confirm entry point.
"""

from __future__ import annotations

from fastapi import HTTPException
from engine.text_changes import LAND_TYPE_WORDS
from .action_registry import action_handler


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

@action_handler("entry_discard_toll_confirm")
def _action_entry_discard_toll_confirm(session, req, seat_type):
    # Mox Diamond: "you may discard a land card instead" of the entry.
    if not any(
        e["player_index"] == req.seat
        for e in session.game.pending_entry_discard_tolls
    ):
        raise HTTPException(status_code=400, detail="no entry discard choice pending for you")
    # No index is the decline, which is a real answer here rather than a missing
    # one - the offer's last option.
    if not session.game.confirm_entry_discard_toll(req.seat, req.hand_index):
        raise HTTPException(status_code=400, detail="invalid entry discard choice")

@action_handler("draw_becomes_counter_confirm")
def _action_draw_becomes_counter_confirm(session, req, seat_type):
    # Pursuit of Knowledge: "you may put a study counter on this enchantment
    # instead" of drawing.
    if not any(
        e["player_index"] == req.seat
        for e in session.game.pending_draw_becomes_counters
    ):
        raise HTTPException(status_code=400, detail="no counter-instead-of-draw choice pending for you")
    if req.take_the_counter is None:
        raise HTTPException(status_code=400, detail="take_the_counter (true/false) is required")
    ok = session.game.confirm_draw_becomes_counter(
        req.seat, take_the_counter=bool(req.take_the_counter)
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid counter-instead-of-draw choice")

@action_handler("reveal_until_kind_draw_confirm")
def _action_reveal_until_kind_draw_confirm(session, req, seat_type):
    # Abundance: "you may instead choose land or nonland and reveal cards from
    # the top of your library until you reveal a card of the chosen kind."
    pending = [
        e
        for e in session.game.pending_reveal_until_kind_draws
        if e["player_index"] == req.seat
    ]
    if not pending:
        raise HTTPException(
            status_code=400, detail="no reveal-until choice pending for you"
        )
    if req.option_index is None:
        raise HTTPException(status_code=400, detail="option_index is required")
    option = int(req.option_index)
    if not 0 <= option < len(pending[0]["options"]):
        raise HTTPException(status_code=400, detail="option_index is out of range")
    if not session.game.confirm_reveal_until_kind_draw(req.seat, option):
        raise HTTPException(status_code=400, detail="invalid reveal-until choice")

@action_handler("skip_draw_confirm")
def _action_skip_draw_confirm(session, req, seat_type):
    # Obstinate Familiar: "If you would draw a card, you may skip that draw
    # instead." Answered by index into the offered options, the Abundance
    # offer's shape: 0 draws the card, 1 skips the draw.
    pending = [
        e for e in session.game.pending_skip_draws if e["player_index"] == req.seat
    ]
    if not pending:
        raise HTTPException(status_code=400, detail="no skip-the-draw choice pending for you")
    if req.option_index is None:
        raise HTTPException(status_code=400, detail="option_index is required")
    option = int(req.option_index)
    if not 0 <= option < len(pending[0]["options"]):
        raise HTTPException(status_code=400, detail="option_index is out of range")
    if not session.game.confirm_skip_draw(req.seat, skip=option == 1):
        raise HTTPException(status_code=400, detail="invalid skip-the-draw choice")

@action_handler("pile_top_draw_confirm")
def _action_pile_top_draw_confirm(session, req, seat_type):
    # Parallel Thoughts: "If you would draw a card, you may instead put the top
    # card of the pile you exiled into your hand." Answered by index into the
    # offered options, Obstinate Familiar's shape: 0 draws the card, 1 takes
    # the pile's top card (from an empty pile, the skipped draw).
    pending = [
        e for e in session.game.pending_pile_top_draws if e["player_index"] == req.seat
    ]
    if not pending:
        raise HTTPException(status_code=400, detail="no pile-instead-of-draw choice pending for you")
    if req.option_index is None:
        raise HTTPException(status_code=400, detail="option_index is required")
    option = int(req.option_index)
    if not 0 <= option < len(pending[0]["options"]):
        raise HTTPException(status_code=400, detail="option_index is out of range")
    if not session.game.confirm_pile_top_draw(req.seat, take_from_pile=option == 1):
        raise HTTPException(status_code=400, detail="invalid pile-instead-of-draw choice")

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
        # prompt on screen with no explanation. An accept of a price the board
        # cannot be made to pay as it stands arrives here too, where it used
        # to be carried out as a decline: the engine taps only free land
        # abilities for a payer, so the seat taps what else it has and answers
        # again (CR 605.3a) -- `Game.seat_answers_for_itself`.
        raise HTTPException(
            status_code=400,
            detail=(
                "that payment option can't be paid — tap for the mana "
                "first, or decline"
            ),
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

@action_handler("mana_color_choice_confirm")
def _action_mana_color_choice_confirm(session, req, seat_type):
    # "Add N mana of any one color" resolving with nobody having named one.
    # The engine re-checks the symbol against the colours the clause offered,
    # so a stale or invented answer is refused rather than clamped.
    if req.mana_color is None:
        raise HTTPException(status_code=400, detail="mana_color is required")
    if not session.game.confirm_mana_color_choice(req.seat, req.mana_color):
        raise HTTPException(status_code=400, detail="that colour is not on offer")

@action_handler("land_type_confirm")
def _action_land_type_confirm(session, req, seat_type):
    # Phantasmal Terrain: the controller picks the enchanted land's basic type.
    if not req.land_type:
        raise HTTPException(status_code=400, detail="land_type is required")
    ok = session.game.confirm_land_type(req.seat, req.land_type)
    if not ok:
        raise HTTPException(status_code=400, detail="no land-type choice pending for you")

@action_handler("land_type_swap_confirm")
def _action_land_type_swap_confirm(session, req, seat_type):
    # Vision Charm: the ordered pair, as two free strings.
    #
    # Not the five-way `land_type` Literal for either half, and not the
    # colour-coded pair Illusionary Terrain's prompt uses: *which* catalog each
    # half draws from is the printed adjective's business, and this card asks
    # for any land type and then a basic one. An encoding that could only carry
    # the five basics would refuse Desert on the half that may name it, and the
    # engine checks each answer against the catalog the sentence named anyway.
    if not req.chosen_land_type or not req.second_land_type:
        raise HTTPException(
            status_code=400,
            detail="chosen_land_type (first chosen type) and second_land_type are required",
        )
    if not session.game.confirm_land_type_swap(
        req.seat, req.chosen_land_type, req.second_land_type
    ):
        raise HTTPException(
            status_code=400, detail="no land-type swap pending for you"
        )

@action_handler("card_type_choice_confirm")
def _action_card_type_choice_confirm(session, req, seat_type):
    # Teferi's Realm: the upkeep's player names one of the types the card
    # printed. The word travels as itself rather than as one of the five
    # colour-encoded basics — the legal answers are a *sentence's* list and
    # include "non-Aura enchantment", which no catalog encoding has a slot for.
    if not req.card_type:
        raise HTTPException(status_code=400, detail="card_type is required")
    if not session.game.confirm_card_type_choice(req.seat, req.card_type):
        raise HTTPException(
            status_code=400, detail="no card-type choice pending for you"
        )

@action_handler("creature_type_choice_confirm")
def _action_creature_type_choice_confirm(session, req, seat_type):
    # Extinction: the spell's controller names one creature type (CR 608.2d) and
    # the sweep in the same sentence destroys every creature of it. The word
    # travels as itself and is checked against CR 205.3m's catalog by the
    # resolver, which is the same list the prompt offered.
    if not req.creature_type:
        raise HTTPException(status_code=400, detail="creature_type is required")
    if not session.game.confirm_creature_type_choice(req.seat, req.creature_type):
        raise HTTPException(
            status_code=400, detail="no creature-type choice pending for you"
        )

@action_handler("color_choice_confirm")
def _action_color_choice_confirm(session, req, seat_type):
    # "Choose a color." made at resolution (CR 608.2d) — the colour travels on
    # the same `mana_color` field every other colour answer in this API uses,
    # and is checked against CR 105.1's five by the resolver, which is the list
    # the prompt offered.
    if not req.mana_color:
        raise HTTPException(status_code=400, detail="mana_color is required")
    if not session.game.confirm_color_choice(req.seat, req.mana_color):
        raise HTTPException(
            status_code=400, detail="no color choice pending for you"
        )

@action_handler("confirm_mana_payment")
def _action_confirm_mana_payment(session, req, seat_type):
    # Power Sink: the targeted spell's controller pays {X} to keep their spell,
    # or declines and it is countered. They tap lands to fill their pool first.
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept (true/false) is required")
    owed = session.game.pending_choice_of("mana_payment", req.seat)
    if owed is None:
        raise HTTPException(status_code=400, detail="no mana payment pending for you")
    ok = session.game.confirm_mana_payment(req.seat, bool(req.accept))
    if not ok:
        # "Pay" that cannot be collected is refused, never read as a decline
        # (CR 608.2d, CR 118.3): the prompt is still owed, and the payer may
        # tap whatever makes mana — the engine taps only free land abilities
        # for them (CR 605.3a, 118.3c) — and answer again, or decline.
        raise HTTPException(
            status_code=400,
            detail=(
                "you can't pay that from your mana pool and untapped lands — "
                "tap for the mana first, or decline"
            ),
        )

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

@action_handler("ignore_coin_confirm")
def _action_ignore_coin_confirm(session, req, seat_type):
    # Krark's Thumb: which of a flip's coins the flipper keeps, by index into
    # the prompt's two options (Abundance's shape): 0 keeps the win (heads),
    # 1 the loss (tails). Only the flipper owes it.
    pending = session.game.pending_choice_of("ignore_coin", req.seat)
    if pending is None:
        raise HTTPException(status_code=400, detail="no coin to keep is pending for you")
    if req.option_index is None:
        raise HTTPException(status_code=400, detail="option_index is required")
    option = int(req.option_index)
    if option not in (0, 1):
        raise HTTPException(status_code=400, detail="option_index is out of range")
    if not session.game.confirm_ignore_coin(req.seat, option == 0):
        raise HTTPException(status_code=400, detail="invalid coin to keep")

@action_handler("guess_named_card_confirm")
def _action_guess_named_card_confirm(session, req, seat_type):
    # Liar's Pendulum: the targeted seat guesses whether a card with the
    # chosen name is in the holder's hand. Only that seat may answer, and the
    # answer is a yes or a no — an absent ``accept`` is neither, so it is
    # refused rather than read as one.
    pending = session.game.pending_choice_of("guess_named_card", req.seat)
    if pending is None:
        raise HTTPException(status_code=400, detail="no guess is pending for you")
    if req.accept is None:
        raise HTTPException(
            status_code=400, detail="accept is required (true: it is in that hand)"
        )
    if not session.game.confirm_guess_named_card(req.seat, bool(req.accept)):
        raise HTTPException(status_code=400, detail="invalid guess")

@action_handler("repeat_process_confirm")
def _action_repeat_process_confirm(session, req, seat_type):
    # Forbidden Ritual: the spell's controller says whether the printed process
    # runs again. Only that seat may answer — the offer is made to one player,
    # and it is the player who has to pay for the next round.
    pending = next(
        (c for c in session.game.pending_choices_of("repeat_process")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no repeated process pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not session.game.confirm_repeat_process(req.seat, req.accept is not False):
        raise HTTPException(status_code=400, detail="invalid repeat answer")

@action_handler("text_change_vocabulary_confirm")
def _action_text_change_vocabulary_confirm(session, req, seat_type):
    # Mind Bend: a colour word, or a basic land type. The engine re-checks the
    # answer against the list it offered, so a client cannot ask for a swap of a
    # word the permanent does not have.
    pending = next(
        (c for c in session.game.pending_choices_of("text_change_vocabulary")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no text change choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.text_change_mode is None:
        raise HTTPException(status_code=400, detail="text_change_mode is required")
    if not session.game.confirm_text_change_vocabulary(
        req.seat, req.text_change_mode
    ):
        raise HTTPException(status_code=400, detail="invalid text change choice")


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

@action_handler("graveyard_return_draw_confirm")
def _action_graveyard_return_draw_confirm(session, req, seat_type):
    # Forbidden Crypt: the draw was replaced by a return from the graveyard and
    # the player picks which card comes back (hand_index = position in their
    # graveyard). Answered through the generic replacement-choice resolver
    # rather than a bespoke ``confirm_`` method - the two above predate it.
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index is required")
    if not session.game.resolve_replacement_choice(
        req.seat, req.hand_index, kind="return_from_graveyard_instead_of_draw"
    ):
        raise HTTPException(status_code=400, detail="invalid card choice")


@action_handler("opponent_library_draw_confirm")
def _action_opponent_library_draw_confirm(session, req, seat_type):
    # Shared Fate: the drawer names which opponent's top card is exiled in
    # place of the draw (option_index = position in the offered options).
    # Through the generic replacement-choice resolver, as Forbidden Crypt's.
    if req.option_index is None:
        raise HTTPException(status_code=400, detail="option_index is required")
    if not session.game.resolve_replacement_choice(
        req.seat, int(req.option_index), kind="opponent_library_draw"
    ):
        raise HTTPException(status_code=400, detail="invalid opponent choice")


@action_handler("enter_choice_confirm")
def _action_enter_choice_confirm(session, req, seat_type):
    # Black Vise / Jihad: the controller confirms the "as this enters"
    # choice — an opponent (target_seat) and, for Jihad, a color (mana_color).
    # **The seat's own prompt, not the oldest of the kind.** Null Chamber arms
    # two at once — "you and an opponent each choose a card name" — and reading
    # the queue head would have let the first chooser answer and refused the
    # second with "no enter choice is pending for you", leaving the enchantment
    # holding half its record forever. The engine's own resolver has always
    # looked the seat's prompt up; this preamble did not, and the two
    # disagreeing is what makes a prompt unanswerable.
    choice = session.game.pending_choice_of("enter_choice", req.seat)
    if choice is None:
        raise HTTPException(status_code=400, detail="no enter choice is pending for you")
    pending = choice.data
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
    # "…choose a land type." (Shimmer.) A third shape of this prompt that
    # names no seat. The word travels as itself for the creature type's
    # reason: CR 205.3i's catalog has no five-way encoding to borrow once the
    # nonbasic types are in it, and the engine checks it against the same
    # vocabulary the prompt offered.
    if pending.get("needs_land_type"):
        if not req.chosen_land_type:
            raise HTTPException(
                status_code=400, detail="chosen_land_type is required"
            )
        if not session.game.confirm_enter_choice(
            req.seat, land_type=req.chosen_land_type
        ):
            raise HTTPException(status_code=400, detail="invalid enter choice")
        return
    if pending.get("needs_creature_type"):
        if not req.creature_type:
            raise HTTPException(
                status_code=400, detail="creature_type is required"
            )
        # "…choose a color **and** a creature type." (Volrath's Laboratory.)
        # One prompt with two answers, so the color travels with the type —
        # the engine reads it only where the prompt asked for one. Sent alone,
        # the type was recorded and the color the player picked was dropped.
        if not session.game.confirm_enter_choice(
            req.seat, creature_type=req.creature_type,
            mana_color=req.mana_color if pending.get("needs_color") else None,
        ):
            raise HTTPException(status_code=400, detail="invalid enter choice")
        return
    # "…choose a card name." (Runed Halo; Null Chamber asks two seats for one
    # each.) The fourth shape that names no seat — and the shape the client
    # could not answer at all until now, because this chain fell straight
    # through to the `target_seat` check below and refused it.
    #
    # CR 201.2 bounds the choice by nothing, so any string is accepted here and
    # the one restriction the card prints (not a basic land card name) is
    # checked by the engine, beside the record it writes.
    #
    # …and only where no seat is asked for beside it: "choose an opponent **and**
    # a card name" (Booby Trap) is one prompt with two answers, so it falls
    # through to the pair below, which sends both. The engine's resolver draws
    # the same line in the same place and for the same reason.
    if pending.get("needs_card_name") and not pending.get("opponents"):
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")
        if not session.game.confirm_enter_choice(req.seat, card_name=req.card_name):
            raise HTTPException(status_code=400, detail="invalid enter choice")
        return
    if req.target_seat is None:
        raise HTTPException(status_code=400, detail="target_seat is required")
    if pending.get("needs_card_name") and not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    if not session.game.confirm_enter_choice(
        req.seat, req.target_seat, req.mana_color, req.card_name,
    ):
        raise HTTPException(status_code=400, detail="invalid enter choice")

@action_handler("number_choice_confirm")
def _action_number_choice_confirm(session, req, seat_type):
    # Shapeshifter: "choose a number between 0 and 7", as it enters and again
    # at each of its controller's upkeeps.
    if req.number is None:
        raise HTTPException(status_code=400, detail="number is required")
    if not session.game.confirm_number_choice(req.seat, req.number):
        raise HTTPException(status_code=400, detail="no number choice is pending for you")

@action_handler("secret_number_confirm")
def _action_secret_number_confirm(session, req, seat_type):
    # Goblin Game: "each player hides at least one item" — this seat's number,
    # on the same ``number`` field every other numbered prompt uses. The engine
    # refuses one below the printed floor and holds the prompt; it records the
    # answer and says nothing, to this seat or any other, until every seat
    # asked has answered. Two messages, because "nothing is owed by you" and
    # "that number is not allowed" are different mistakes: the gate lets this
    # action through for every seat while any seat still owes the prompt.
    if session.game.pending_choice_of("secret_number", req.seat) is None:
        raise HTTPException(
            status_code=400, detail="no hidden number is pending for you"
        )
    if req.number is None:
        raise HTTPException(status_code=400, detail="number is required")
    if not session.game.confirm_secret_number(req.seat, req.number):
        raise HTTPException(
            status_code=400, detail="that number is below the least you may choose"
        )

@action_handler("bid_life_confirm")
def _action_bid_life_confirm(session, req, seat_type):
    # Illicit Auction: the seat tops the standing bid. Zero is not an answer
    # here -- the offer is to *top* the high bid, and declining is the separate
    # `bid_life_pass` below, so an absent number is a malformed bid rather than
    # a pass.
    if req.number is None:
        raise HTTPException(status_code=400, detail="number is required")
    if not session.game.confirm_bid_life(req.seat, req.number):
        raise HTTPException(
            status_code=400, detail="no bid of that size is pending for you"
        )


@action_handler("bid_life_pass")
def _action_bid_life_pass(session, req, seat_type):
    # The printed "may": declining the auction is an answer, and the round
    # cannot move on until every seat has given one.
    if not session.game.confirm_bid_life(req.seat, None):
        raise HTTPException(
            status_code=400, detail="no bidding is pending for you"
        )


@action_handler("draw_up_to_confirm")
def _action_draw_up_to_confirm(session, req, seat_type):
    # Truce: "each player may draw up to two cards" — the answer is how many.
    # Zero is a legal answer and the whole point of the card, so an absent
    # number is a missing answer rather than a decline.
    if req.number is None:
        raise HTTPException(status_code=400, detail="number is required")
    if not session.game.confirm_draw_up_to(req.seat, req.number):
        raise HTTPException(status_code=400, detail="no draw choice is pending for you")

@action_handler("pay_any_amount_confirm")
def _action_pay_any_amount_confirm(session, req, seat_type):
    # Liege of the Hollows: "each player may pay any amount of mana" — the
    # answer is how much, on the same ``number`` field every other numbered
    # prompt uses. Zero is a legal answer and is what the printed "may" means,
    # so an absent number is a missing answer rather than a decline. The engine
    # re-checks it against the seat's pool and untapped lands and *rejects* an
    # answer the board cannot cover, so the prompt's ceiling is a hint.
    if req.number is None:
        raise HTTPException(status_code=400, detail="number is required")
    if not session.game.confirm_pay_any_amount(req.seat, req.number):
        raise HTTPException(
            status_code=400, detail="no mana payment is pending for you"
        )


@action_handler("body_choice_confirm")
def _action_body_choice_confirm(session, req, seat_type):
    # Primal Clay: the controller picks which printed body the creature
    # entered as (hand_index = position in the offered options).
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index (body option index) is required")
    if not session.game.confirm_enter_body_choice(req.seat, req.hand_index):
        raise HTTPException(status_code=400, detail="no body choice is pending for you")

@action_handler("effect_order_confirm")
def _action_effect_order_confirm(session, req, seat_type):
    # CR 616.1e: the affected player picks which of the effects contending
    # over one event applies first. Answering re-runs the event, so this
    # returns with the draw made or the damage dealt.
    if not session.game.resolve_pending_choice(
        "effect_order", req.seat, option_index=int(req.option_index or 0)
    ):
        raise HTTPException(status_code=400, detail="no effect order pending for you")
