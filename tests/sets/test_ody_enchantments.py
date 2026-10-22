"""Odyssey enchantments.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
# (moved whole to test_ody_enchantments_first_groups.py when this file reached its size cap)

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
# (moved whole to test_ody_enchantments_first_groups.py when this file reached its size cap)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
# (moved whole to test_ody_enchantments_later_groups.py when this file reached its size cap)

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
# (moved whole to test_ody_enchantments_later_groups.py when this file reached its size cap)

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

import pytest as _w1g7_pytest

from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import _mk_card as _w1g7_mk_card
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=(), interactive=()):
    """A two-seat game with costs off, built from card names (ODY over LEA).
    A seat in *interactive* is asked its decisions instead of defaulting."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    seats = [
        _w1g7_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g7_Game(players=seats)
    game.enforce_mana_costs = False
    for seat in interactive:
        game.interactive_seats.add(seat)
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g7_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g7_names(cards):
    return [card.name for card in cards]


def _w1g7_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g7_settle(game, limit=50):
    """Drain the stack and give every owed prompt its default answer."""
    for _ in range(limit):
        _w1g7_resolve_stack(game)
        if not game.pending_choices and not game.pending_replacement_choices:
            return
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
    raise AssertionError("the game did not settle")


# --- Think Tank: surveil (CR 701.25) ------------------------------------------

def test_think_tank_surveils_at_its_controllers_upkeep_and_the_card_may_go(
    set_pool,
):
    """"At the beginning of your upkeep, surveil 1." CR 701.25a: look at the
    top card, then put it into your graveyard or leave it on top. The ability
    stays on the stack until its controller has decided (CR 608.2)."""
    game = _w1g7_duel(
        set_pool, bf0=["Think Tank"], lib0=["Forest", "Grizzly Bears", "Island"],
        interactive=(0,),
    )
    game.resolve_upkeep(0)
    assert not game.resolve_top_of_stack(), "held: a decision is owed"
    (choice,) = game.pending_choices
    assert (choice.kind, choice.player_index) == ("scry", 0)
    assert choice.data["destination"] == "graveyard"
    assert choice.data["top_count"] == 1

    assert game.confirm_scry(0, [0], 1)
    assert _w1g7_names(game.players[0].graveyard) == ["Forest"]
    assert _w1g7_names(game.players[0].library) == ["Grizzly Bears", "Island"]
    assert game.players[0].hand == [], "a surveil draws nothing"
    assert not game.stack


def test_think_tank_may_leave_the_card_on_top(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Think Tank"], lib0=["Forest", "Grizzly Bears"],
        interactive=(0,),
    )
    game.resolve_upkeep(0)
    game.resolve_top_of_stack()
    assert game.confirm_scry(0, [0], 0)
    assert game.players[0].graveyard == []
    assert _w1g7_names(game.players[0].library) == ["Forest", "Grizzly Bears"]


def test_think_tank_is_silent_on_an_opponents_upkeep_and_over_an_empty_library(
    set_pool,
):
    """"Your upkeep" is its controller's; and a surveil with nothing to look
    at asks nothing and is not a draw (no CR 704.5b loss)."""
    game = _w1g7_duel(set_pool, bf0=["Think Tank"], lib0=["Forest"], lib1=["Island"])
    game.resolve_upkeep(1)
    _w1g7_settle(game)
    assert game.players[0].graveyard == [] and len(game.players[0].library) == 1

    empty = _w1g7_duel(set_pool, bf0=["Think Tank"], interactive=(0,))
    empty.resolve_upkeep(0)
    _w1g7_settle(empty)
    assert not empty.pending_choices
    assert not empty.players[0].lost


def test_think_tank_resolves_after_it_has_left_the_battlefield(set_pool):
    """The ability is independent of its source once on the stack (CR 113.7a)."""
    game = _w1g7_duel(
        set_pool, bf0=["Think Tank"], lib0=["Forest", "Island"], interactive=(0,),
    )
    game.resolve_upkeep(0)
    game.remove_from_battlefield(_w1g7_on_board(game, 0, "Think Tank"))
    game.resolve_top_of_stack()
    assert game.confirm_scry(0, [0], 1)
    assert _w1g7_names(game.players[0].graveyard) == ["Forest"]


def test_surveil_is_an_action_any_card_can_print(set_pool):
    """Built as the keyword action, not as the card: an invented "Surveil 3."
    sorcery looks at three, bins the two its controller names and keeps the
    third on top — and an answer that is not a permutation of what was looked
    at is refused with the prompt still owed."""
    look = _w1g7_mk_card("Deep Look", "{U}", "Sorcery", "Surveil 3.")
    assert _w1g7_compile(look).supported
    game = _w1g7_duel(
        set_pool, lib0=["Forest", "Grizzly Bears", "Island", "Swamp"],
        interactive=(0,),
    )
    game.players[0].hand.append(look)
    assert game.cast_from_hand(0, "Deep Look").supported
    assert not game.confirm_scry(0, [0, 0, 1], 1)
    assert not game.confirm_scry(0, [0, 1, 2], 4)
    assert game.pending_choices, "a refused answer leaves the prompt owed"

    # Keep the Bears; the Forest and the Island go to the graveyard.
    assert game.confirm_scry(0, [1, 0, 2], 2)
    assert _w1g7_names(game.players[0].library) == ["Grizzly Bears", "Swamp"]
    assert _w1g7_names(game.players[0].graveyard) == ["Forest", "Island", "Deep Look"]


def test_surveil_and_scry_are_two_actions_with_one_answer_shape(set_pool):
    """Scry sends the cards not kept to the bottom (CR 701.22a) where surveil
    sends them to the graveyard (CR 701.25a); the same answer means each."""
    scry = _w1g7_mk_card("Shallow Look", "{U}", "Sorcery", "Scry 2.")
    game = _w1g7_duel(
        set_pool, lib0=["Forest", "Grizzly Bears", "Island"], interactive=(0,),
    )
    game.players[0].hand.append(scry)
    assert game.cast_from_hand(0, "Shallow Look").supported
    assert game.pending_choices[0].data.get("destination") is None
    assert game.confirm_scry(0, [1, 0], 1)
    assert _w1g7_names(game.players[0].library) == ["Grizzly Bears", "Island", "Forest"]
    assert _w1g7_names(game.players[0].graveyard) == ["Shallow Look"]


@_w1g7_pytest.mark.parametrize("text", ["Surveil 2 cards.", "Surveil."])
def test_a_surveil_line_saying_more_or_less_is_refused(text):
    assert not _w1g7_compile(
        _w1g7_mk_card("Odd Look", "{U}", "Sorcery", text)
    ).supported


# --- Battle of Wits: an intervening "if" on a library count -------------------

def test_battle_of_wits_wins_with_two_hundred_cards_in_the_library(set_pool):
    game = _w1g7_duel(set_pool, bf0=["Battle of Wits"], lib0=["Forest"] * 200)
    game.resolve_upkeep(0)
    _w1g7_settle(game)
    assert game.players[1].lost and not game.players[0].lost


def test_battle_of_wits_does_not_trigger_one_card_short_or_on_another_upkeep(
    set_pool,
):
    """CR 603.4: the condition is checked as the ability would trigger, and a
    false one means it never does — no object reaches the stack."""
    game = _w1g7_duel(
        set_pool, bf0=["Battle of Wits"], lib0=["Forest"] * 199,
        lib1=["Forest"] * 250, interactive=(0, 1),
    )
    game.resolve_upkeep(0, defer_priority=True)
    assert not game.stack
    game.resolve_upkeep(1, defer_priority=True)
    assert not game.stack, "'your upkeep', and 'you have' is its controller"
    assert not any(player.lost for player in game.players)


def test_battle_of_wits_checks_the_library_again_as_it_resolves(set_pool):
    """CR 603.4's second half, and the card's own ruling (2012-07-01): "if you
    have fewer than 200 cards in your library when the ability resolves, the
    ability will do nothing"."""
    game = _w1g7_duel(
        set_pool, bf0=["Battle of Wits"], lib0=["Forest"] * 200,
        interactive=(0, 1),
    )
    game.resolve_upkeep(0, defer_priority=True)
    assert len(game.stack) == 1
    game.players[0].library.pop()
    _w1g7_settle(game)
    assert not any(player.lost for player in game.players)


def test_battle_of_wits_still_wins_if_it_leaves_in_response(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Battle of Wits"], lib0=["Forest"] * 200,
        interactive=(0, 1),
    )
    game.resolve_upkeep(0, defer_priority=True)
    game.remove_from_battlefield(_w1g7_on_board(game, 0, "Battle of Wits"))
    _w1g7_settle(game)
    assert game.players[1].lost


def test_a_pile_count_reads_the_subjects_own_pile_in_either_word_order():
    """"If you have 200 or more cards in your library" is the third word order
    of one question ("your library has ten or more cards in it"), and the
    possessive has to be the subject's own — a clause counting one player's
    pile on another's say-so is a different sentence."""
    def supported(clause):
        return _w1g7_compile(_w1g7_mk_card(
            "Pile Counter", "{1}", "Enchantment",
            f"At the beginning of your upkeep, if {clause}, you gain 1 life.",
        )).supported

    assert supported("you have three or more cards in your library")
    assert supported("your library has three or more cards in it")
    assert supported("you have three or more cards in your graveyard")
    assert not supported("you have three or more cards in their library")
    assert not supported("you have three or more cards in your sideboard")


# --- Zombie Infestation (compiled before this round; driven) ---------------------

def test_zombie_infestation_trades_two_cards_for_a_black_zombie(set_pool):
    """"Discard two cards: Create a 2/2 black Zombie creature token." Two
    cards, the two its controller names; one card cannot pay; and a pair of
    identical cards is two cards."""
    game = _w1g7_duel(
        set_pool, bf0=["Zombie Infestation"], hand0=["Forest", "Forest", "Island"],
    )
    assert game.activate_permanent_ability(
        0, "Zombie Infestation", cost_hand_index=0, cost_other_hand_indices=[2]
    ).supported
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].hand) == ["Forest"]
    assert sorted(_w1g7_names(game.players[0].graveyard)) == ["Forest", "Island"]
    tokens = [p for p in game.controlled_by(0) if p.is_creature]
    assert [(t.effective_power, t.effective_toughness) for t in tokens] == [(2, 2)]
    assert tokens[0].has_type("zombie") and list(tokens[0].effective_card.colors) == ["B"]

    short = _w1g7_duel(set_pool, bf0=["Zombie Infestation"], hand0=["Forest"])
    assert not short.activate_permanent_ability(0, "Zombie Infestation").supported
    assert _w1g7_names(short.players[0].hand) == ["Forest"]

    pair = _w1g7_duel(set_pool, bf0=["Zombie Infestation"], hand0=["Forest", "Forest"])
    assert pair.activate_permanent_ability(0, "Zombie Infestation").supported
    _w1g7_settle(pair)
    assert pair.players[0].hand == [] and len(pair.players[0].graveyard) == 2
    assert sum(1 for p in pair.controlled_by(0) if p.is_creature) == 1

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
import pytest as _w1g8_pytest

from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.sets import ody_w1g8_helpers as _w1g8


# --- Price of Glory ---------------------------------------------------------
# "Whenever a player taps a land for mana, if it's not that player's turn,
# destroy that land." An intervening-if (CR 603.4) about the seat the event
# named, and a destroy of the land the event was about. Resolved at the tap
# seam, like every non-mana trigger under this event (see Savage Firecat's
# note in `test_ody_creatures.py`).

def _w1g8_tap(game, seat, land):
    return game.tap_land_for_mana(seat, land.card.name, permanent_id=land.permanent_id)


@_w1g8_pytest.mark.parametrize("active", [0, 1])
def test_w1g8_price_of_glory_destroys_a_land_tapped_off_turn(set_pool, active):
    """Only the player whose turn it is taps safely — the enchantment's own
    controller included when the turn is somebody else's."""
    game = _w1g8.table(set_pool)
    _w1g8.put(game, set_pool, 0, "Price of Glory")
    lands = [
        _w1g8.put(game, set_pool, 0, "Mountain"),
        _w1g8.put(game, set_pool, 1, "Forest"),
    ]
    game.start_turn(active)
    idle = 1 - active

    assert _w1g8_tap(game, active, lands[active])
    assert game.is_on_battlefield(lands[active])

    assert _w1g8_tap(game, idle, lands[idle])
    assert not game.is_on_battlefield(lands[idle])
    assert _w1g8.pile(game, idle) == [lands[idle].card.name]
    symbol = "R" if idle == 0 else "G"
    assert game.players[idle].mana_pool[symbol] == 1, (
        "the mana was made before the land died (CR 605.3b)"
    )


def test_w1g8_two_prices_of_glory_destroy_one_land_once(set_pool):
    game = _w1g8.table(set_pool)
    _w1g8.put(game, set_pool, 0, "Price of Glory")
    _w1g8.put(game, set_pool, 1, "Price of Glory")
    forest = _w1g8.put(game, set_pool, 1, "Forest")
    game.start_turn(0)

    assert _w1g8_tap(game, 1, forest)

    assert _w1g8.pile(game, 1) == ["Forest"], "one card in the graveyard, not two"
    assert any("the permanent it named is gone" in line for line in game.log)


def test_w1g8_price_of_glory_spares_a_regenerating_land_and_ignores_other_taps(set_pool):
    """It says *destroy*: nothing here bypasses regeneration. And a land
    tapped for something other than mana is not this event at all."""
    game = _w1g8.table(set_pool)
    _w1g8.put(game, set_pool, 0, "Price of Glory")
    forest = _w1g8.put(game, set_pool, 1, "Forest")
    game.start_turn(0)

    game.become_tapped(forest)
    assert game.is_on_battlefield(forest)

    program = _w1g8_compile(set_pool("ODY")["Price of Glory"])
    assert "bypass_regeneration" not in program.triggered_abilities[0].instruction.payload


def test_w1g8_that_players_turn_needs_an_event_that_names_a_player():
    """The refusing gate's refusal test: "that player's turn" under an event
    that froze no player would be asked about the ability's controller."""
    from tests.helpers import _mk_card

    under_a_tap = _mk_card(
        "Probe Price", "Enchantment",
        "Whenever a player taps a land for mana, if it's that player's turn, "
        "destroy that land.",
    )
    under_an_attack = _mk_card(
        "Probe Price", "Creature — Dwarf",
        "Whenever this creature attacks, if it's not that player's turn, "
        "you gain 1 life.",
    )
    assert _w1g8_compile(under_a_tap).supported
    assert not _w1g8_compile(under_an_attack).supported


# --- Steam Vines ------------------------------------------------------------
# "When enchanted land becomes tapped, destroy it and this Aura deals 1 damage
# to that land's controller. That player attaches this Aura to a land of their
# choice." Kudzu's sentence with damage in it and no "may" — the second card of
# a shape Kudzu held a name-keyed hook for, so it is a production now and the
# hook is retired (`tests/regressions/test_ody_w1g8_shipped_cards.py`).
#
# The host is picked as the ability resolves, by the destroyed land's
# controller, among every land the Aura could enchant. The card's rulings:
# moving it "does not target the land" (2004-10-04); with no land to move to
# it goes to the graveyard (2005-08-01); and if the Aura left before its
# trigger resolved, the land is still destroyed and the damage dealt, but
# nothing brings it back (2004-10-04).

def _w1g8_vines(set_pool, interactive=(), lands=True):
    """Seat 0's Steam Vines on seat 1's Forest, on seat 1's turn."""
    from engine.aura_attachment import attach_aura

    game = _w1g8.table(set_pool, interactive=interactive)
    forest = _w1g8.put(game, set_pool, 1, "Forest")
    vines = _w1g8.put(game, set_pool, 0, "Steam Vines")
    attach_aura(vines, forest)
    mountain = _w1g8.put(game, set_pool, 0, "Mountain") if lands else None
    swamp = _w1g8.put(game, set_pool, 1, "Swamp") if lands else None
    game.start_turn(1)
    return game, vines, forest, mountain, swamp


def _w1g8_host(aura):
    host = aura.metadata.get("attached_to")
    return None if host is None else host.card.name


def test_w1g8_steam_vines_destroys_burns_and_moves_where_its_victim_says(set_pool):
    game, vines, forest, mountain, swamp = _w1g8_vines(set_pool, interactive=(0, 1))

    assert _w1g8_tap(game, 1, forest)
    assert [item.card.name for item in game.stack] == ["Steam Vines"], (
        "\"becomes tapped\" is not a mana ability: it uses the stack"
    )
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g8.pile(game, 1) == ["Forest"] and game.players[1].life == 19
    assert _w1g8.owed(game) == [("permanent_choice", 1)], "that land's controller chooses"
    assert game.is_on_battlefield(vines), "the Aura waits for its new land"

    assert not game.confirm_permanent_choice(1, None), "no \"may\": it must go somewhere"
    assert game.confirm_permanent_choice(1, mountain.permanent_id), (
        "any land, its own controller's included"
    )
    _w1g8.settle(game)
    assert _w1g8_host(vines) == "Mountain"

    # …and it is still Steam Vines on the land it moved to.
    game.turn += 1
    game.start_turn(0)
    assert _w1g8_tap(game, 0, mountain)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.players[0].life == 19 and _w1g8.pile(game, 0) == ["Mountain"]
    assert _w1g8.owed(game) == [("permanent_choice", 0)]


def test_w1g8_steam_vines_moved_by_a_seat_nobody_asks_goes_to_somebody_elses_land(
    set_pool,
):
    game, vines, forest, mountain, swamp = _w1g8_vines(set_pool)

    game.become_tapped(forest)      # tapped by anything, not only for mana
    _w1g8.settle(game)

    assert _w1g8_host(vines) == "Mountain", "not the chooser's own Swamp"


def test_w1g8_steam_vines_with_no_land_to_move_to_is_put_in_the_graveyard(set_pool):
    game, vines, forest, _, _ = _w1g8_vines(set_pool, lands=False)

    assert _w1g8_tap(game, 1, forest)
    _w1g8.settle(game)

    assert game.players[1].life == 19
    assert _w1g8.pile(game, 0) == ["Steam Vines"]


def test_w1g8_steam_vines_gone_in_response_still_destroys_and_burns(set_pool):
    game, vines, forest, mountain, swamp = _w1g8_vines(set_pool)

    assert _w1g8_tap(game, 1, forest)
    _w1g8.leave(game, vines)
    _w1g8.settle(game)

    assert _w1g8.pile(game, 1) == ["Forest"] and game.players[1].life == 19
    assert _w1g8.pile(game, 0) == ["Steam Vines"], "and it does not come back"
    assert _w1g8.names(game, 0) == ["Mountain"]


# --- driven: the four enchantments that compiled on the day of the ingest ---
# Each given a game through its whole text; this is what the game showed.

def _w1g8_dies(game, permanent):
    _w1g8.leave(game, permanent)
    _w1g8.settle(game)


def test_w1g8_battle_strain_burns_the_controller_of_each_blocker(set_pool):
    game = _w1g8.table(set_pool)
    _w1g8.put(game, set_pool, 0, "Battle Strain")
    giant = _w1g8.put(game, set_pool, 0, "Hill Giant")
    blockers = [
        _w1g8.put(game, set_pool, 1, name)
        for name in ("Grizzly Bears", "Llanowar Elves")
    ]
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    mine = list(game.controlled_by(0))
    assert game.declare_attackers(0, [mine.index(giant)])[0]
    game.advance_combat_phase()
    theirs = list(game.controlled_by(1))

    assert game.declare_blockers(
        1, {theirs.index(blocker): mine.index(giant) for blocker in blockers}
    )[0]
    _w1g8.settle(game)

    assert [player.life for player in game.players] == [20, 18], (
        "one trigger a blocker, each on the blocker's controller"
    )


def test_w1g8_burning_sands_costs_a_land_for_every_creature_that_dies(set_pool):
    game = _w1g8.table(set_pool)
    _w1g8.put(game, set_pool, 0, "Burning Sands")
    mine = _w1g8.put(game, set_pool, 0, "Llanowar Elves")
    _w1g8.put(game, set_pool, 0, "Mountain")
    theirs = _w1g8.put(game, set_pool, 1, "Grizzly Bears")
    _w1g8.put(game, set_pool, 1, "Forest")
    game.start_turn(0)

    _w1g8_dies(game, theirs)
    assert _w1g8.names(game, 1) == [], "that creature's controller, not the enchantment's"
    assert "Mountain" in _w1g8.names(game, 0)

    _w1g8_dies(game, mine)
    assert _w1g8.names(game, 0) == ["Burning Sands"]


def test_w1g8_magma_vein_spends_a_land_to_sweep_the_ground(set_pool):
    game = _w1g8.table(set_pool, enforce=True)
    _w1g8.put(game, set_pool, 0, "Magma Vein")
    mountain = _w1g8.put(game, set_pool, 0, "Mountain")
    _w1g8.put(game, set_pool, 1, "Llanowar Elves")
    _w1g8.put(game, set_pool, 1, "Birds of Paradise")
    game.start_turn(0)
    game.players[0].mana_pool["R"] = 2

    used = game.activate_permanent_ability(
        0, "Magma Vein", cost_permanent_ids=[mountain.permanent_id]
    )
    _w1g8.settle(game)
    assert used.supported, used.details
    assert _w1g8.names(game, 0) == ["Magma Vein"]
    assert _w1g8.names(game, 1) == ["Birds of Paradise"]

    without = game.activate_permanent_ability(0, "Magma Vein")
    assert not without.supported and game.players[0].mana_pool["R"] == 1


def test_w1g8_need_for_speed_trades_a_land_for_haste(set_pool):
    game = _w1g8.table(set_pool)
    _w1g8.put(game, set_pool, 0, "Need for Speed")
    mountain = _w1g8.put(game, set_pool, 0, "Mountain")
    bears = _w1g8.put(game, set_pool, 0, "Grizzly Bears")
    game.start_turn(0)
    bears.metadata["summoning_sickness_turn"] = game.turn
    assert game._is_summoning_sick(bears)

    used = game.activate_permanent_ability(
        0, "Need for Speed", target_permanent_ids=[bears.permanent_id],
        cost_permanent_ids=[mountain.permanent_id],
    )
    _w1g8.settle(game)
    assert used.supported, used.details
    assert not game._is_summoning_sick(bears)
    assert "Mountain" not in _w1g8.names(game, 0)

    again = game.activate_permanent_ability(
        0, "Need for Speed", target_permanent_ids=[bears.permanent_id]
    )
    assert not again.supported and "no land available" in again.details

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.


import pytest as _w1g9_pytest

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from engine.oracle import compile_card_oracle as _w1g9_compile
from tests.helpers import _mk_card as _w1g9_mk_card
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_table(set_pool, *, hands=((), ()), boards=((), ()), costs=False):
    """A game with one seat per entry of *hands*, built from card names
    (Odyssey first, then Alpha); ten Forests in each library."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name=f"P{seat}", life=20, hand=[pool[n] for n in hand],
            library=[pool["Forest"]] * 10,
        )
        for seat, hand in enumerate(hands)
    ])
    game.enforce_mana_costs = costs
    for seat, names in enumerate(boards):
        for name in names:
            permanent = _w1g9_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game  # _w1g9_table (enchantments)


def _w1g9_on(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g9_hand_sizes(game):
    return [len(player.hand) for player in game.players]


# --- Standstill -------------------------------------------------------------

def test_standstill_is_sacrificed_and_the_casters_opponents_draw_three(set_pool):
    """"When a player casts a spell, sacrifice this enchantment. If you do,
    each of that player's opponents draws three cards." An opponent blinks:
    Standstill's controller draws, and the spell still resolves."""
    game = _w1g9_table(
        set_pool, hands=((), ("Grizzly Bears",)), boards=(("Standstill",), ()),
    )
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g9_resolve_stack(game)
    assert _w1g9_hand_sizes(game) == [3, 0]
    assert [c.name for c in game.players[0].graveyard] == ["Standstill"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_standstill_pays_the_other_side_when_its_own_controller_casts(set_pool):
    game = _w1g9_table(
        set_pool, hands=(("Grizzly Bears",), ()), boards=(("Standstill",), ()),
    )
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g9_resolve_stack(game)
    assert _w1g9_hand_sizes(game) == [0, 3]


def test_standstill_draws_once_for_two_spells_cast_in_a_row(set_pool):
    """Two triggers, one Standstill: the later spell's trigger resolves first
    and its caster's opponent draws; the earlier one finds nothing left to
    sacrifice, and "if you do" is not done."""
    game = _w1g9_table(
        set_pool, hands=(("Lightning Bolt",), ("Lightning Bolt",)),
        boards=(("Standstill",), ()),
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_hand_sizes(game) == [0, 3]
    assert [p.life for p in game.players] == [17, 17]


def test_standstill_counts_opponents_from_the_caster_in_a_three_player_game(set_pool):
    game = _w1g9_table(
        set_pool, hands=((), ("Grizzly Bears",), ()),
        boards=(("Standstill",), (), ()),
    )
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g9_resolve_stack(game)
    assert _w1g9_hand_sizes(game) == [3, 0, 3]


@_w1g9_pytest.mark.parametrize("text, supported", [
    ("Whenever a player casts a spell, each of that player's opponents draws "
     "a card.", True),
    # No seat was frozen for the words to be measured from, and a verb with
    # no reader for the set: both refuse rather than act on somebody else.
    ("Whenever a creature attacks, each of that player's opponents draws a "
     "card.", False),
    ("Whenever a player casts a spell, each of that player's opponents loses "
     "1 life.", False),
])
def test_that_players_opponents_is_read_only_where_a_seat_was_frozen(text, supported):
    card = _w1g9_mk_card("Truce Probe", "{U}", "Enchantment", text)
    assert _w1g9_compile(card).supported is supported


# --- The enchantments that compiled on arrival, each given a game -----------

def test_still_life_is_a_centaur_until_end_of_turn_and_dies_like_one(set_pool):
    """"{G}{G}: This enchantment becomes a 4/3 Centaur creature in addition to
    its other types until end of turn." Layer 4 and 7b: an enchantment creature
    that 3 damage destroys, and an enchantment again at cleanup."""
    game = _w1g9_table(
        set_pool, hands=((), ("Lightning Bolt",)), boards=(("Still Life",), ()),
        costs=True,
    )
    still = _w1g9_on(game, 0, "Still Life")
    assert not game.activate_permanent_ability(0, "Still Life").supported
    game.players[0].mana_pool.update({"G": 2})
    assert game.activate_permanent_ability(0, "Still Life").supported
    _w1g9_resolve_stack(game)
    assert still.is_creature and still.has_type("centaur") and still.has_type("enchantment")
    assert (still.effective_power, still.effective_toughness) == (4, 3)
    game.resolve_cleanup_step(0)
    game._recompute_continuous_effects()
    assert not still.is_creature

    game.players[0].mana_pool.update({"G": 2})
    game.players[1].mana_pool.update({"R": 1})
    assert game.activate_permanent_ability(0, "Still Life").supported
    _w1g9_resolve_stack(game)
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[still.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    game.check_state_based_actions()
    assert [c.name for c in game.players[0].graveyard] == ["Still Life"]


def test_testament_of_faith_is_as_big_as_the_x_paid_for_it(set_pool):
    game = _w1g9_table(set_pool, boards=(("Testament of Faith",), ()), costs=True)
    testament = _w1g9_on(game, 0, "Testament of Faith")
    game.players[0].mana_pool.update({"W": 3})
    assert game.activate_permanent_ability(
        0, "Testament of Faith", x_value=3
    ).supported
    _w1g9_resolve_stack(game)
    assert (testament.effective_power, testament.effective_toughness) == (3, 3)
    assert testament.has_type("wall") and game._has_keyword(testament, "defender")
    assert sum(game.players[0].mana_pool.values()) == 0
    assert not game.activate_permanent_ability(
        0, "Testament of Faith", x_value=2
    ).supported, "nothing left to pay {2} with"


def test_unifying_theory_offers_the_caster_a_card_for_two(set_pool):
    """"Whenever a player casts a spell, that player may pay {2}. If the
    player does, they draw a card." Asked of whoever cast - an opponent too -
    and the card goes to the one who paid."""
    game = _w1g9_table(
        set_pool, hands=(("Grizzly Bears",), ("Grizzly Bears",)),
        boards=(("Unifying Theory",), ()), costs=True,
    )
    game.interactive_seats = {0, 1}
    for seat, accept in ((1, True), (0, False)):
        game.players[seat].mana_pool.update({"G": 4})
        assert game.queue_from_hand(seat, "Grizzly Bears").supported
        game.resolve_top_of_stack(pause_for_choices=True)
        offer = game.pending_choices[0]
        assert (offer.kind, offer.player_index) == ("optional_pay", seat)
        assert offer.data["cost"] == {"generic": 2}
        assert game.confirm_optional_pay(seat, accept=accept)
        assert len(game.players[seat].hand) == (1 if accept else 0)
        assert game.players[seat].mana_pool["G"] == (0 if accept else 2)
        _w1g9_resolve_stack(game)

# ==== end W1G9 ======================================================
