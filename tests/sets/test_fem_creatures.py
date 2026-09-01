"""Per-card tests for Fallen Empires' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations


# --- G1: counters as named state ---
#
# The unifying machinery of this group is a **named counter as readable
# state**: putting them on, taking them off, counting them, and conditioning a
# static effect or a trigger on how many there are. The enchantment half of the
# same round (Tidal Influence, Tourach's Gate, Merseine) is in
# ``test_fem_enchantments.py``.

from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from tests.helpers import _nosick as _g1_nosick


def _g1_board(set_pool, *names, life=20, hand=(), opponents=()):
    """A two-seat game with *names* on seat 0's battlefield, in order.

    FEM cards by default; a ``(code, name)`` pair reaches another set's pool,
    which is how the fodder and the targets below are basics and vanilla bears
    rather than more of this set.
    """
    def _card(entry):
        return set_pool(entry[0])[entry[1]] if isinstance(entry, tuple) else set_pool("FEM")[entry]

    p0 = PlayerState(name="P0", life=life, hand=[_card(entry) for entry in hand])
    p1 = PlayerState(name="P1", life=life)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    made = []
    for entry in names:
        perm = Permanent(card=_card(entry))
        game._put_permanent_onto_battlefield(0, perm, None)
        made.append(perm)
    for entry in opponents:
        perm = Permanent(card=_card(entry))
        game._put_permanent_onto_battlefield(1, perm, None)
        made.append(perm)
    game._settle()
    game.active_player_index = 0
    return (game, p0, p1, *made)


def _g1_upkeep(game, seat=0):
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    game._settle()


# -- Homarid ---------------------------------------------------------------


def test_homarid_rides_its_tide_counters_up_and_back_to_zero(set_pool):
    """The whole printed cycle in one game, because the card *is* the cycle.

    It enters with one tide counter and gets -1/-1 while there is exactly one;
    a second counter is neither one nor three, so it is a plain 2/2; the third
    turns the penalty into a bonus; the fourth trips the CR 603.8 state trigger
    that empties it, and the tide starts again.
    """
    game, _p0, _p1, homarid = _g1_board(set_pool, "Homarid")

    assert counters_on(homarid, "tide") == 1, "it enters with one"
    assert (homarid.effective_power, homarid.effective_toughness) == (1, 1)

    _g1_upkeep(game)
    assert counters_on(homarid, "tide") == 2
    assert (homarid.effective_power, homarid.effective_toughness) == (2, 2), (
        "two is neither exactly one nor exactly three"
    )

    _g1_upkeep(game)
    assert counters_on(homarid, "tide") == 3
    assert (homarid.effective_power, homarid.effective_toughness) == (3, 3)

    _g1_upkeep(game)
    assert counters_on(homarid, "tide") == 0, "four or more empties it (CR 603.8)"
    assert (homarid.effective_power, homarid.effective_toughness) == (2, 2)

    _g1_upkeep(game)
    assert counters_on(homarid, "tide") == 1, "and the tide comes back in"
    assert (homarid.effective_power, homarid.effective_toughness) == (1, 1)


# -- Icatian Moneychanger --------------------------------------------------


def test_icatian_moneychanger_charges_three_life_on_arrival(set_pool):
    """"When this creature enters, it deals 3 damage to you" — and it enters
    with three credit counters, which is the loan it is charging for."""
    _game, p0, _p1, changer = _g1_board(set_pool, "Icatian Moneychanger")

    assert p0.life == 17
    assert counters_on(changer, "credit") == 3


def test_the_moneychanger_pays_back_one_life_per_credit_counter(set_pool):
    """"Sacrifice this creature: You gain 1 life for each credit counter on
    this creature."

    The counter count is read back off the permanent the *cost* has already
    eaten (CR 608.2h), so the life gained is the number that was there at
    activation and not zero.
    """
    game, p0, _p1, changer = _g1_board(set_pool, "Icatian Moneychanger")
    _g1_upkeep(game)
    assert counters_on(changer, "credit") == 4, "the upkeep adds one"

    before = p0.life
    result = game.activate_permanent_ability(0, "Icatian Moneychanger", ability_index=0)
    game._settle()

    assert result.supported, result.details
    assert p0.life == before + 4, "one life per credit counter, not one life"
    assert not game.is_on_battlefield(changer), "the cost sacrificed it"


def test_the_moneychanger_cannot_cash_out_outside_your_upkeep(set_pool):
    """"Activate only during your upkeep." An unenforced restriction is not a
    dead ability — it is one that works more often than the card allows."""
    game, p0, _p1, _changer = _g1_board(set_pool, "Icatian Moneychanger")
    game.current_turn_phase, game.current_step = "precombat_main", "main"

    result = game.activate_permanent_ability(0, "Icatian Moneychanger", ability_index=0)

    assert not result.supported
    assert "only during your upkeep" in result.details
    assert p0.life == 17, "nothing was gained and nothing was paid"


# -- Ebon Praetor ----------------------------------------------------------


def test_ebon_praetor_shrinks_itself_every_upkeep(set_pool):
    """"At the beginning of your upkeep, put a -2/-2 counter on this creature.\""""
    game, _p0, _p1, praetor = _g1_board(set_pool, "Ebon Praetor")
    assert (praetor.effective_power, praetor.effective_toughness) == (5, 5)

    _g1_upkeep(game)

    assert counters_on(praetor, "-2/-2") == 1
    assert (praetor.effective_power, praetor.effective_toughness) == (3, 3)


def test_feeding_the_praetor_a_thrull_also_grows_it(set_pool):
    """"If the sacrificed creature was a Thrull, put a +1/+0 counter on this
    creature."

    The effect reads back an object the *cost* consumed: by resolution the
    Thrull is a card in a graveyard, so the answer is the record the payment
    path wrote (CR 608.2h) rather than any read of the board.
    """
    game, _p0, _p1, praetor, thrull = _g1_board(
        set_pool, "Ebon Praetor", "Basal Thrull",
    )
    _g1_upkeep(game)

    result = game.activate_permanent_ability(
        0, "Ebon Praetor", ability_index=0,
        cost_permanent_ids=[game.permanent_id_of(thrull)],
    )
    game._settle()

    assert result.supported, result.details
    assert counters_on(praetor, "-2/-2") == 0, "the removal happened"
    assert counters_on(praetor, "+1/+0") == 1, "and the Thrull clause fired"
    assert (praetor.effective_power, praetor.effective_toughness) == (6, 5)


def test_feeding_the_praetor_anything_else_only_removes(set_pool):
    """The same activation with a non-Thrull: the removal still happens and the
    conditional half does not. A condition that answered True either way would
    be a card strictly better than the one printed."""
    game, _p0, _p1, praetor, bear = _g1_board(
        set_pool, "Ebon Praetor", ("LEA", "Grizzly Bears"),
    )
    _g1_upkeep(game)

    result = game.activate_permanent_ability(
        0, "Ebon Praetor", ability_index=0,
        cost_permanent_ids=[game.permanent_id_of(bear)],
    )
    game._settle()

    assert result.supported, result.details
    assert counters_on(praetor, "-2/-2") == 0
    assert counters_on(praetor, "+1/+0") == 0, "Grizzly Bears is not a Thrull"
    assert (praetor.effective_power, praetor.effective_toughness) == (5, 5)


def test_the_praetor_may_only_be_fed_once_each_turn(set_pool):
    """"Activate only during your upkeep **and only once each turn**." Two
    restrictions in one printed sentence, and both have to hold."""
    game, _p0, _p1, praetor, thrull, other = _g1_board(
        set_pool, "Ebon Praetor", "Basal Thrull", "Basal Thrull",
    )
    _g1_upkeep(game)
    game.activate_permanent_ability(
        0, "Ebon Praetor", ability_index=0,
        cost_permanent_ids=[game.permanent_id_of(thrull)],
    )
    game._settle()

    again = game.activate_permanent_ability(
        0, "Ebon Praetor", ability_index=0,
        cost_permanent_ids=[game.permanent_id_of(other)],
    )

    assert not again.supported
    assert "only once each turn" in again.details
    assert game.is_on_battlefield(other), "the second Thrull was not eaten"
    assert counters_on(praetor, "+1/+0") == 1


# -- Dwarven Armorer -------------------------------------------------------


def _g1_armorer_board(set_pool, interactive=()):
    game, _p0, _p1, smith, bear = _g1_board(
        set_pool, "Dwarven Armorer", ("LEA", "Grizzly Bears"),
        hand=[("LEA", "Mountain"), ("LEA", "Mountain")],
    )
    game.interactive_seats = set(interactive)
    _g1_nosick(smith)
    return game, smith, bear


def test_the_armorer_defaults_to_the_first_printed_counter(set_pool):
    """"Put a +0/+1 counter **or** a +1/+0 counter on target creature."

    A choice between two kinds is one placement, not two, and a seat that
    answers nothing takes the first printed alternative — the stated policy for
    every mode in this engine.
    """
    game, _smith, bear = _g1_armorer_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Dwarven Armorer", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert counters_on(bear, "+0/+1") == 1
    assert counters_on(bear, "+1/+0") == 0, "one of the two, never both"
    assert (bear.effective_power, bear.effective_toughness) == (2, 3)


def test_the_armorer_offers_the_other_counter_to_a_player(set_pool):
    """An interactive seat is asked, and its answer decides which kind lands —
    on the creature the *activation* named, not on whichever the prompt's own
    default picker would have found first."""
    game, smith, bear = _g1_armorer_board(set_pool, interactive={0})

    game.activate_permanent_ability(
        0, "Dwarven Armorer", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    (choice,) = game.pending_choices
    assert choice.kind == "mode_choice"
    assert choice.data["labels"] == ["a +0/+1 counter", "a +1/+0 counter"]

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    game._settle()

    assert counters_on(bear, "+1/+0") == 1
    assert (bear.effective_power, bear.effective_toughness) == (3, 2)
    assert counters_on(smith, "+1/+0") == 0, "the counter went to the target"


def test_the_armorer_charges_its_discard(set_pool):
    """{R}, {T}, **Discard a card** — the cost is collected, and the source
    taps. A cost nobody charges is an ability that works for free."""
    game, smith, _bear = _g1_armorer_board(set_pool)
    hand_before = len(game.players[0].hand)

    game.activate_permanent_ability(
        0, "Dwarven Armorer", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert len(game.players[0].hand) == hand_before - 1
    assert smith.tapped
