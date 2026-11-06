"""Scourge enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.linked_exile import linked_entries as _w1g7_linked_entries
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_perm(card):
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g7_game(mine=(), theirs=(), *, library=None, hand=(), their_hand=()):
    library = list(library) if library is not None else []
    me = _W1G7PlayerState(
        name="P0", battlefield=[_w1g7_perm(c) for c in mine],
        library=list(library), hand=list(hand), life=20,
    )
    them = _W1G7PlayerState(
        name="P1", battlefield=[_w1g7_perm(c) for c in theirs],
        library=list(library), hand=list(their_hand), life=20,
    )
    game = _W1G7Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    return game


def _w1g7_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Sulfuric Vortex -------------------------------------------------------
#
# "If a player would gain life, that player gains no life instead." A CR 614
# replacement (614.1a), not CR 119.7's "can't gain life": the gain is replaced
# by nothing, so nothing is recorded or announced — and beside Lich's own
# replacement the gaining player chooses which applies (CR 616.1e).


def test_w1g7_sulfuric_vortex_replaces_every_players_life_gain(set_pool):
    vortex = set_pool("SCG")["Sulfuric Vortex"]
    nectar = set_pool("7ED")["Sacred Nectar"]
    game = _w1g7_game(theirs=[vortex], hand=[nectar], their_hand=[nectar])
    me, them = game.players

    assert game.queue_from_hand(0, "Sacred Nectar").supported
    _w1g7_resolve_stack(game)
    # "A player": the opponent of the Vortex's controller…
    assert me.life == 20 and me.life_gained_this_turn == 0
    assert any(
        "P0 would gain 4 life from Sacred Nectar; gains no life instead (Sulfuric Vortex)"
        in line for line in game.log
    )
    # …and its controller alike.
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Sacred Nectar").supported
    _w1g7_resolve_stack(game)
    assert them.life == 20 and them.life_gained_this_turn == 0


def test_w1g7_sulfuric_vortex_deals_two_to_each_player_in_their_upkeep(set_pool):
    vortex = set_pool("SCG")["Sulfuric Vortex"]
    forest = set_pool("2ED")["Forest"]
    game = _w1g7_game(mine=[vortex], library=[forest] * 6)
    game.turn = 2
    game.start_turn(0)
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 18 and game.players[1].life == 20
    game.start_turn(1)
    _w1g7_resolve_stack(game)
    assert game.players[1].life == 18


def test_w1g7_sulfuric_vortex_beside_lich_a_seat_nobody_asks_draws(set_pool):
    """CR 616.1e's default: both replacements consume the gain and the gaining
    player would take Lich's cards over nothing. A ban (Forsaken Wastes, CR
    119.7) would stop Lich too — which is the difference the card's wording
    makes."""
    vortex = set_pool("SCG")["Sulfuric Vortex"]
    lich = set_pool("2ED")["Lich"]
    nectar = set_pool("7ED")["Sacred Nectar"]
    forest = set_pool("2ED")["Forest"]
    game = _w1g7_game(mine=[lich, vortex], library=[forest] * 8, hand=[nectar])
    me = game.players[0]
    assert game.queue_from_hand(0, "Sacred Nectar").supported
    _w1g7_resolve_stack(game)
    assert len(me.hand) == 4 and len(me.library) == 4
    assert me.life == 20 and me.life_gained_this_turn == 0


def test_w1g7_sulfuric_vortex_beside_lich_asks_the_gaining_player(set_pool):
    vortex = set_pool("SCG")["Sulfuric Vortex"]
    lich = set_pool("2ED")["Lich"]
    nectar = set_pool("7ED")["Sacred Nectar"]
    forest = set_pool("2ED")["Forest"]
    for pick, cards in (("Gain no life instead", 0), ("Lich", 4)):
        game = _w1g7_game(mine=[lich, vortex], library=[forest] * 8, hand=[nectar])
        game.interactive_seats = {0}
        me = game.players[0]
        assert game.queue_from_hand(0, "Sacred Nectar").supported
        game.resolve_top_of_stack()
        (asked,) = [c for c in game.pending_choices if c.kind == "effect_order"]
        assert asked.player_index == 0
        assert set(asked.data["options"]) == {"Lich", "Gain no life instead"}
        # Nothing has happened while the question is owed (CR 616.1).
        assert me.hand == [] and me.life == 20
        assert game.resolve_pending_choice(
            "effect_order", 0, option_index=asked.data["options"].index(pick)
        )
        _w1g7_resolve_stack(game)
        assert len(me.hand) == cards, pick
        assert me.life == 20 and me.life_gained_this_turn == 0
        assert not game.stack and not game.pending_choices


# --- Parallel Thoughts -------------------------------------------------------
#
# The entry trigger exiles seven cards in a face-down pile linked to the
# enchantment (CR 607.2a); "If you would draw a card, you may instead put the
# top card of the pile you exiled into your hand." Rulings (2004-10-04): fewer
# than seven exiles them all; an empty pile may still be "taken" from, which
# skips the draw; nobody may look at the face-down cards.


def _w1g7_thoughts_in_play(set_pool, library, *, interactive=False):
    thoughts = set_pool("SCG")["Parallel Thoughts"]
    game = _w1g7_game(library=library, hand=[thoughts])
    if interactive:
        game.interactive_seats = {0}
    assert game.queue_from_hand(0, "Parallel Thoughts").supported
    _w1g7_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, _w1g7_named(game, 0, "Parallel Thoughts")


def test_w1g7_parallel_thoughts_exiles_seven_face_down_and_hides_them(set_pool):
    pool = set_pool("2ED")
    library = [pool["Forest"]] * 4 + [pool["Hill Giant"]] * 6
    game, thoughts = _w1g7_thoughts_in_play(set_pool, library)
    me = game.players[0]
    pile = _w1g7_linked_entries(thoughts)
    assert len(pile) == 7 and all(entry.get("face_down") for entry in pile)
    assert len(me.exile) == 7 and len(me.library) == 3
    # game.log is every seat's: the find is a count, not a list of names.
    searched = [line for line in game.log if "searched library and exiled" in line]
    assert searched == ["P0 searched library and exiled 7 card(s) face down"]


def test_w1g7_parallel_thoughts_with_fewer_than_seven_exiles_them_all(set_pool):
    pool = set_pool("2ED")
    game, thoughts = _w1g7_thoughts_in_play(set_pool, [pool["Hill Giant"]] * 4)
    assert len(_w1g7_linked_entries(thoughts)) == 4
    assert game.players[0].library == []


def test_w1g7_parallel_thoughts_takes_the_pile_for_a_seat_nobody_asks(set_pool):
    pool = set_pool("2ED")
    library = [pool["Forest"]] * 3 + [pool["Hill Giant"]] * 7
    game, thoughts = _w1g7_thoughts_in_play(set_pool, library)
    me = game.players[0]
    library_before = list(me.library)
    pile_cards = [entry["card"] for entry in _w1g7_linked_entries(thoughts)]

    game.players[0].hand.append(set_pool("6ED")["Inspiration"])
    assert game.queue_from_hand(0, "Inspiration", target_player_index=0).supported
    _w1g7_resolve_stack(game)

    # Two draws replaced, one at a time (CR 121.2): the pile's top two came
    # to hand, the library is untouched, and neither was a draw.
    assert me.hand == pile_cards[:2]
    assert me.library == library_before
    assert len(_w1g7_linked_entries(thoughts)) == 5 and len(me.exile) == 5
    assert me.cards_drawn_this_turn == []
    took = [line for line in game.log if "goes from the exiled pile" in line]
    assert took == ["Parallel Thoughts: the top card goes from the exiled pile to P0's hand"] * 2


def test_w1g7_parallel_thoughts_asks_an_interactive_seat_each_draw(set_pool):
    pool = set_pool("2ED")
    library = [pool["Forest"]] * 3 + [pool["Hill Giant"]] * 7
    game, thoughts = _w1g7_thoughts_in_play(set_pool, library, interactive=True)
    me = game.players[0]
    pile_top = _w1g7_linked_entries(thoughts)[0]["card"]
    library_top = me.library[0]

    assert game._draw_with_replacements(me, 2) == 0
    (offer,) = game.pending_replacement_choices
    assert offer.kind == "pile_top_draw" and offer.player_index == 0
    # The offer names the pile, never the card in it.
    assert offer.options == (
        "draw the card", "put the top card of the exiled pile into your hand",
    )
    assert game.confirm_pile_top_draw(0, take_from_pile=True)
    # The second draw is its own offer, made once the first is decided.
    (second,) = game.pending_replacement_choices
    assert second.kind == "pile_top_draw"
    assert game.confirm_pile_top_draw(0, take_from_pile=False)
    assert game.pending_replacement_choices == []
    assert me.hand == [pile_top, library_top]
    assert me.cards_drawn_this_turn == [library_top]
    assert len(_w1g7_linked_entries(thoughts)) == 6


def test_w1g7_parallel_thoughts_empty_pile_skips_the_draw(set_pool):
    """"You can choose to take the top card from the pile (and not draw) even
    if there are no cards in the pile." A seat nobody asks does so only where
    the draw would come from an empty library."""
    pool = set_pool("2ED")
    thoughts = set_pool("SCG")["Parallel Thoughts"]
    # Asked: an empty pile, taken — nothing is drawn and nothing arrives.
    game = _w1g7_game(mine=[thoughts], library=[pool["Forest"]] * 3)
    game.interactive_seats = {0}
    me = game.players[0]
    game._draw_with_replacements(me, 1)
    (offer,) = game.pending_replacement_choices
    assert offer.options[1].endswith("(the pile is empty)")
    assert game.confirm_pile_top_draw(0, take_from_pile=True)
    assert me.hand == [] and len(me.library) == 3
    assert any("the exiled pile is empty" in line for line in game.log)
    # Not asked, a library to draw from: the draw.
    game = _w1g7_game(mine=[thoughts], library=[pool["Forest"]] * 3)
    game._draw_with_replacements(game.players[0], 1)
    assert game.players[0].hand == [pool["Forest"]]
    # Not asked, an empty library: the skip, and no loss (CR 704.5b).
    game = _w1g7_game(mine=[thoughts], library=[])
    game._draw_with_replacements(game.players[0], 1)
    game.check_state_based_actions()
    assert not game.players[0].lost


def test_w1g7_parallel_thoughts_contends_with_another_draw_replacement(set_pool):
    """CR 616.1e: beside Obstinate Familiar's optional skip, the drawing player
    chooses which applies first — and the declined one is offered after."""
    pool = set_pool("2ED")
    thoughts = _w1g7_perm(set_pool("SCG")["Parallel Thoughts"])
    familiar = set_pool("ODY")["Obstinate Familiar"]
    game = _w1g7_game(mine=[familiar], library=[pool["Forest"]] * 3)
    game.players[0].battlefield.append(thoughts)
    hill_giant = pool["Hill Giant"]
    game.players[0].exile.append(hill_giant)
    from engine.linked_exile import link_exiled_card

    link_exiled_card(thoughts, hill_giant, 0, face_down=True)
    game.interactive_seats = {0}
    me = game.players[0]
    game._draw_with_replacements(me, 1)
    (order,) = [c for c in game.pending_choices if c.kind == "effect_order"]
    pick = order.data["options"].index(
        "Put the top card of the exiled pile into your hand instead"
    )
    assert game.resolve_pending_choice("effect_order", 0, option_index=pick)
    assert game.confirm_pile_top_draw(0, take_from_pile=True)
    assert me.hand == [hill_giant] and len(me.library) == 3
    assert game.pending_replacement_choices == [] and game.pending_choices == []


# --- Upwelling --------------------------------------------------------------
#
# "Players don't lose unspent mana as steps and phases end." CR 500.5's
# emptying switched off while it is on the battlefield; ruling 2009-10-01:
# "once it leaves the battlefield, they have until the end of the current step
# (or phase) to use the mana before it disappears."


def test_w1g7_upwelling_keeps_every_players_mana_until_it_leaves(set_pool):
    upwelling = set_pool("SCG")["Upwelling"]
    pool = set_pool("2ED")
    disenchant = pool["Disenchant"]
    game = _w1g7_game(
        mine=[upwelling], library=[pool["Forest"]] * 8, their_hand=[disenchant],
    )
    game.turn = 2
    me, them = game.players
    me.mana_pool["G"] = 3
    them.mana_pool["R"] = 1
    # Through P0's end and cleanup steps and P1's whole beginning phase.
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    game.start_next_turn()
    assert game.active_player_index == 1
    assert me.mana_pool["G"] == 3 and them.mana_pool["R"] == 1

    # Gone in P1's main phase: the mana stays until that phase ends…
    assert game.queue_from_hand(
        1, "Disenchant",
        target_permanent_ids=[_w1g7_named(game, 0, "Upwelling").permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert [c.name for c in me.graveyard] == ["Upwelling"]
    assert me.mana_pool["G"] == 3
    # …and empties as it ends.
    game._on_step_or_phase_end("precombat_main", "precombat_main")
    assert me.mana_pool["G"] == 0 and them.mana_pool["R"] == 0


def test_w1g7_upwelling_mana_pays_for_a_spell_a_step_later(set_pool):
    upwelling = set_pool("SCG")["Upwelling"]
    pool = set_pool("2ED")
    game = _w1g7_game(mine=[upwelling], library=[pool["Forest"]] * 8,
                      hand=[pool["Grizzly Bears"]])
    game.enforce_mana_costs = True
    me = game.players[0]
    me.mana_pool["G"] = 2
    game._on_step_or_phase_end("precombat_main", "precombat_main")
    game._set_phase_and_step("postcombat_main", "postcombat_main")
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g7_resolve_stack(game)
    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0))
    assert me.mana_pool["G"] == 0

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
