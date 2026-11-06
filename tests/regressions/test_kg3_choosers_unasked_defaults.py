"""What a seat nobody asks answers (``engine/pending_choices.py``'s third
part): the census of every registered prompt kind's default, classified as
by-worth or by-position, and the three Onslaught's W2G5 measured picking by
position where the program says what the pick is worth.

* **Strongarm Tactics** ("Each player discards a card. Then each player who
  didn't discard a creature card this way loses 4 life."): the discard default
  took a seat's first card and it lost 4 life holding a creature card in 5 of
  12 discards. The sentence behind tests which card went
  (``ai_prompt_readers.discard_spares_a_penalty``), so the card sparing the
  penalty goes first (``ai_prompts.order_discard``) — on the inline path a
  seat nobody asks takes and on the queued prompt's default alike.
* **Risky Move** ("choose a creature you control and an opponent. Flip a
  coin. If you lose the flip, that opponent gains control of that
  creature"): the permanent-choice default took board order and risked a
  Butcher Orgg over a Festering Goblin. A pick taken from the seat choosing
  it (a control change now counts as taken,
  ``ai_prompt_readers._TAKEN_FROM_ITS_CONTROLLER``) gives up the cheapest by
  ``permanent_worth`` — the mirror of Wormfang Crab's dearest.
* **Meddle** ("change that spell's target to another creature"): the forced
  re-aim's default already went to the side the effect cuts
  (``_retarget_preferred_seats``) and then took board order; it now takes the
  dearest permanent there (``_dearest_permanents_first``).

Validated backwards: on the tree before the fix each board fails — the seat
loses 4 life, the Orgg is chosen, the Llanowar Elves are destroyed.
"""

from __future__ import annotations

import random

from engine import Game, PlayerState
from engine.models import Permanent
from engine.pending_choices import CHOICE_SPECS
from tests.helpers import _mk_creature_card, resolve_stack

import engine.mixins.stack.choices.table  # noqa: F401  (registers every kind)

#: Every registered prompt kind's default, read and classified (kg3):
#:
#: * ``worth`` — ranks the options by what they are worth to the seat (a
#:   rehearsal, ``permanent_worth``, an AI reader, or mana value / power as the
#:   ranking every card answers);
#: * ``stated`` — a policy with no ranking among options to make: yes or no,
#:   the whole offer, a number, a value stamped when the prompt was armed;
#: * ``preference`` — the first option in board / hand order, behind a
#:   preference the program reads (a shared colour, a card the sentence tests,
#:   a pick taken away);
#: * ``position`` — the first option(s) in board, hand, seat or printed order
#:   with nothing weighed. Each is a default still owed a reading by worth.
_DEFAULTS: dict[str, str] = {
    "aggregate_sacrifice": "worth",       # greatest power first, up to the total
    "balance": "position",                # the last slots of hand / board
    "bid_life": "stated",                 # no bid
    "body_choice": "stated",              # stamped at arm
    "card_type_choice": "stated",         # stamped at arm
    "cast_choice": "position",            # Backdraft: the first spell
    "choose_card_name": "stated",         # stamped at arm
    "choose_cards_in_hand": "preference", # hand order behind an entry consumer
    "color_choice": "stated",             # stamped at arm
    "color_set_choice": "stated",         # stamped at arm
    "commander_zone_change": "stated",    # a CR 614 replacement's default
    "copy_spell_target": "worth",
    "counter_distribution": "worth",      # all onto its own greatest-power creature
    "creature_type_choice": "stated",     # stamped at arm
    "discard": "preference",              # hand order behind the tested card
    "discard_unless_pay_life": "stated",  # pay while it is not the whole life
    "draw_becomes_counter": "stated",
    "draw_up_to": "stated",               # the whole offer
    "effect_order": "position",           # CR 616.1: the first effect
    "enter_choice": "stated",             # stamped at arm
    "entry_discard_toll": "stated",
    "entry_exile": "worth",               # least mana value
    "entry_reveal": "stated",             # every candidate
    "exile_from_hand_choice": "worth",    # least mana value
    "exile_hand_pile_choice": "stated",   # the whole offer
    "exiled_pile_claim": "worth",         # greatest mana value
    "exiled_card_return": "worth",        # greatest ``permanent_worth`` (Dimensional Breach)
    "face_down_cast": "position",         # Illusionary Mask: the first creature
    "face_down_look": "stated",           # a dismissal
    "flip_again": "stated",               # no
    "graveyard_exile_pick": "worth",      # graveyard denial / price orders
    "graveyard_pick_for_price": "worth",  # least mana value
    "graveyard_pile_choice": "worth",
    "hand_reveal": "stated",              # a dismissal
    "hand_to_library": "position",        # the first cards in hand
    "keep_permanents": "worth",
    "lamp_draw": "stated",
    "land_type_choice": "stated",         # stamped at arm
    "land_type_swap": "stated",           # stamped at arm
    "leng_discard": "stated",
    "library_cycle_offer": "stated",      # no
    "library_end_choice": "stated",       # top
    "library_pile_split": "position",     # the first half
    "linked_exile_return": "position",    # the first card
    "look_top_pick": "preference",        # first, or greatest mana value when recorded
    "loyalty_recipient": "worth",         # fewest loyalty counters
    "madness_cast": "worth",              # ``_madness.default_madness_offer``
    "mana_color_choice": "stated",        # stamped at arm
    "mana_payment": "stated",             # pay if able
    "modal_mode_targets": "position",     # Fatal Lore's caster: the first two
    "mode_choice": "worth",               # rehearsed (``choose_trigger_mode``)
    "name_and_random_reveal": "stated",   # stamped at arm
    "name_and_strip": "stated",
    "name_then_consult": "stated",
    "name_then_reveal_top": "stated",
    "number_choice": "stated",
    "opponent_damage": "worth",           # the biggest creature it kills
    "opponent_mode_choice": "position",   # the first printed mode
    "opponent_picks_revealed": "worth",   # mana value, by fate
    "optional_damage_redirect": "stated",
    "optional_pay": "worth",              # toll and trade readers
    "order_triggers": "stated",           # the fire sites' order
    "outside_game_draw": "stated",
    "outside_game_pick": "worth",
    "pay_any_amount": "worth",
    "pay_life_to_save": "stated",
    "permanent_choice": "preference",     # board order behind program reads, worth on a taken pick
    "permanent_set_choice": "preference",
    "pile_choice": "worth",               # ``piles.default_pile_choice``
    "pile_exile_choice": "worth",         # the smaller pile
    "pile_search": "position",            # the first card
    "pile_split": "worth",                # the most even split by value
    "pile_top_draw": "stated",            # the pile while it holds a card
    "player_choice": "position",          # the first seat offered
    "put_from_hand_choice": "position",   # the first card
    "reflexive_target": "position",       # the first permanent offered
    "reorder_library": "worth",
    "repeat_process": "stated",           # no
    "retarget_choice": "worth",           # the effect's side, dearest first
    "return_from_graveyard_instead_of_draw": "stated",
    "reveal_until_kind_draw": "stated",
    "revealed_draw_buyout": "stated",     # no
    "revealed_hand_pick": "worth",        # greatest mana value
    "sacrifice": "worth",                 # ``default_sacrifice_pick``
    "scry": "worth",
    "search_destination": "stated",       # as found
    "search_exile_cards": "worth",
    "search_library": "worth",
    "secret_number": "worth",
    "skip_draw": "stated",
    "tap_any_number": "stated",           # the whole offer
    "target_group_order": "stated",       # the slot order, as before the prompt
    "text_change_vocabulary": "position", # the first word
    "trigger_target": "worth",            # the trigger's side
    "untap_up_to": "position",            # board order, as many as affordable
    "word_of_command": "position",        # the first card in the hand
}


def test_every_prompt_kind_s_default_is_classified():
    """A new prompt kind says what its default weighs, or this fails; a
    by-position default fixed moves its row. The population is the registry
    itself, so it cannot be smaller than what is registered."""
    assert len(CHOICE_SPECS) >= 90
    assert set(_DEFAULTS) == set(CHOICE_SPECS), (
        sorted(set(CHOICE_SPECS) - set(_DEFAULTS)),
        sorted(set(_DEFAULTS) - set(CHOICE_SPECS)),
    )
    assert set(_DEFAULTS.values()) <= {"worth", "stated", "preference", "position"}


# -- Strongarm Tactics --------------------------------------------------------


def _strongarm_table(set_pool, *, interactive=()) -> Game:
    ons = set_pool("ONS")
    plains = ons["Plains"]
    game = Game(players=[
        PlayerState(name="Caster", library=[plains] * 10),
        PlayerState(name="Rival", library=[plains] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    for seat in (0, 1):
        game.players[seat].hand = [plains, _mk_creature_card(f"Beast{seat}", 3, 3)]
    game.players[0].hand.insert(0, ons["Strongarm Tactics"])
    return game


def test_a_seat_nobody_asks_discards_the_card_that_spares_the_penalty(set_pool):
    game = _strongarm_table(set_pool)
    assert game.cast_from_hand(0, "Strongarm Tactics").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [game.players[seat].life for seat in (0, 1)] == [20, 20], game.log[-8:]
    for seat in (0, 1):
        assert [card.name for card in game.players[seat].hand] == ["Plains"]


def test_a_drained_discard_prompt_takes_the_same_card(set_pool):
    """The queued prompt's own default (``_default_discard``) — an interactive
    seat answered for, the path a timed-out seat or a test's drain takes."""
    game = _strongarm_table(set_pool, interactive=(1,))
    assert game.cast_from_hand(0, "Strongarm Tactics").supported
    assert any(c.kind == "discard" and c.player_index == 1 for c in game.pending_choices)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert game.players[1].life == 20, game.log[-8:]
    assert [card.name for card in game.players[1].hand] == ["Plains"]


def test_a_seat_with_no_creature_card_still_discards(set_pool):
    game = _strongarm_table(set_pool)
    game.players[1].hand = [set_pool("ONS")["Plains"], set_pool("ONS")["Island"]]
    assert game.cast_from_hand(0, "Strongarm Tactics").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert game.players[1].life == 16
    assert len(game.players[1].hand) == 1


# -- Risky Move -------------------------------------------------------------


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_risky_move_risks_the_cheapest_creature(set_pool):
    ons = set_pool("ONS")
    random.seed(3)
    game = Game(players=[
        PlayerState(name="A", library=[ons["Forest"]] * 10),
        PlayerState(name="B", library=[ons["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    # Board order would name the Orgg first.
    _put(game, 0, ons["Butcher Orgg"])
    _put(game, 0, ons["Festering Goblin"])
    _put(game, 1, ons["Risky Move"])
    resolve_stack(game)
    game.active_player_index = 1
    game.start_turn(0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    chose = [line for line in game.log if line.startswith("Risky Move: chose")]
    assert chose == ["Risky Move: chose Festering Goblin"], game.log[-10:]


# -- Meddle -----------------------------------------------------------------


def test_meddle_re_aims_a_removal_spell_at_the_dearest_creature(catalog_by_name):
    game = Game(players=[
        PlayerState(name="A", library=[catalog_by_name["Island"]] * 10),
        PlayerState(name="B", library=[catalog_by_name["Swamp"]] * 10),
    ])
    game.enforce_mana_costs = False
    mine = _put(game, 0, catalog_by_name["Grizzly Bears"])
    # Board order would name the Elves first.
    _put(game, 1, catalog_by_name["Llanowar Elves"])
    _put(game, 1, catalog_by_name["Craw Wurm"])
    resolve_stack(game)
    game.players[1].hand.append(catalog_by_name["Terror"])
    game.players[0].hand.append(catalog_by_name["Meddle"])
    assert game.queue_from_hand(
        1, "Terror", target_permanent_ids=[mine.permanent_id]
    ).supported
    assert game.queue_from_hand(0, "Meddle", target_stack_index=0).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Llanowar Elves"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
