"""Apocalypse artifacts (artifact creatures included).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.card_loader import manifest_set_path as _w1g1_manifest_set_path
from engine.cast_costs import KICKED as _W1G1_KICKED
from engine.cast_costs import additional_costs as _w1g1_additional_costs
from engine.models import Permanent as _W1G1Permanent
from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import resolve_stack as _w1g1_resolve_stack

# --- Emblazoned Golem --------------------------------------------------------
# "Kicker {X}. Spend only colored mana on X. No more than one mana of each
# color may be spent this way. If this creature was kicked, it enters with X
# +1/+1 counters on it."  {2}, a 1/2.

_W1G1_GOLEM = "Emblazoned Golem"


def _w1g1_duel(set_pool, pool, *, enforce=True, board=()):
    """Seat 0 holds an Emblazoned Golem with *pool* floating and *board* (cards)
    already on its battlefield. Mana is charged unless *enforce* is False."""
    forest = set_pool("LEA")["Forest"]
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            "Caster", library=[forest] * 10, hand=[set_pool("APC")[_W1G1_GOLEM]]
        ),
        _W1G1PlayerState("Bystander", library=[forest] * 10),
    ])
    game.enforce_mana_costs = enforce
    for card in board:
        game._put_permanent_onto_battlefield(0, _W1G1Permanent(card=card), None)
    game.players[0].mana_pool.update(pool)
    return game  # _w1g1_duel


def _w1g1_cast(game, x_value=None, *, kick=True):
    """Announce the Golem — kicked for *x_value* unless *kick* is False —
    resolve it, and return ``(result, the Golem or None)``."""
    result = game.cast_from_hand(
        0, _W1G1_GOLEM,
        optional_cost_payments={"{X}": 1} if kick else None, x_value=x_value,
    )
    if result.supported:
        _w1g1_resolve_stack(game)
    golem = next(
        (p for p in game.controlled_by(0) if p.card.name == _W1G1_GOLEM), None
    )
    return result, golem  # _w1g1_cast


def _w1g1_left(game) -> dict:
    return {
        symbol: count for symbol, count in game.players[0].mana_pool.items() if count
    }  # _w1g1_left


def test_w1g1_emblazoned_golem_compiles_with_its_x_restricted(set_pool):
    """Supported, and the restriction is *on the offer*: every reader that
    prices the kicker holds the flag that says its X is one mana per colour."""
    card = set_pool("APC")[_W1G1_GOLEM]
    assert _w1g1_compile(card).supported
    (cost,) = _w1g1_additional_costs(card)
    (offer,) = cost.optional_mana
    assert (offer.symbols, offer.x_count, offer.x_one_of_each_color) == ("{X}", 1, True)
    assert offer.x_colorings(0) == ((),)
    assert len(offer.x_colorings(2)) == 10 and len(offer.x_colorings(5)) == 1
    assert offer.x_colorings(6) == ()


@_w1g1_pytest.mark.parametrize("pool,x_value,left", [
    # three colours for X = 3, the two colourless for the {2}
    ({"W": 2, "U": 1, "B": 1, "R": 1, "G": 1, "C": 2}, 3, {"W": 1, "R": 1, "G": 1}),
    # all five colours, once each, and the {2} from colourless
    ({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1, "C": 2}, 5, {}),
    # one colour pays X = 1 and the generic {2} as well
    ({"W": 5}, 1, {"W": 2}),
    ({"W": 2, "U": 2}, 2, {}),
])
def test_w1g1_a_kicked_emblazoned_golem_enters_with_x_counters(set_pool, pool, x_value, left):
    """X is paid with one mana of each of X colours on top of the {2}, and the
    Golem enters with X +1/+1 counters: a 1/2 plus X."""
    game = _w1g1_duel(set_pool, pool)
    result, golem = _w1g1_cast(game, x_value)

    assert result.supported, result.details
    assert (golem.effective_power, golem.effective_toughness) == (1 + x_value, 2 + x_value)
    assert int(golem.metadata.get("plus_counters", 0) or 0) == x_value
    assert golem.metadata.get(_W1G1_KICKED)
    assert _w1g1_left(game) == left
    assert f"Caster kicked {_W1G1_GOLEM} (X={x_value})" in game.log


@_w1g1_pytest.mark.parametrize("pool,x_value", [
    # five white mana is one colour: X = 2 needs two
    ({"W": 5}, 2),
    # colourless mana is not coloured mana
    ({"C": 8}, 1),
    ({"C": 7, "R": 1}, 2),
    # all five colours for X, and then nothing left for the {2}
    ({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1}, 5),
])
def test_w1g1_an_x_the_colors_cannot_pay_is_refused_with_nothing_spent(set_pool, pool, x_value):
    """"Spend only colored mana on X. No more than one mana of each color may
    be spent this way." A pool rich enough in *mana* and too poor in *colours*
    does not cast the kicked Golem, and a refused cast spends nothing."""
    game = _w1g1_duel(set_pool, pool)
    result, golem = _w1g1_cast(game, x_value)

    assert not result.supported
    assert golem is None
    assert _w1g1_left(game) == pool
    assert [card.name for card in game.players[0].hand] == [_W1G1_GOLEM]


@_w1g1_pytest.mark.parametrize("enforce", [True, False])
def test_w1g1_x_above_five_is_refused_whether_or_not_mana_is_charged(set_pool, enforce):
    """There are five colours, so no X above five can be paid one mana of
    each. That bounds the announcement itself — refused before any cost, and
    in a game that waives mana too, where nothing else would stop it."""
    rich = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}
    game = _w1g1_duel(set_pool, rich, enforce=enforce)
    result, golem = _w1g1_cast(game, 6)
    assert not result.supported and golem is None
    assert "no more than one mana of each color" in result.details
    assert _w1g1_left(game) == rich

    game = _w1g1_duel(set_pool, rich, enforce=enforce)
    result, golem = _w1g1_cast(game, 5)
    assert result.supported
    assert (golem.effective_power, golem.effective_toughness) == (6, 7)


def test_w1g1_an_unkicked_emblazoned_golem_is_a_one_two_for_two(set_pool):
    """The kicker declined: {2}, a 1/2, no counters — and an X sent along with
    a declined kicker is not an X (CR 601.2b), so it buys nothing."""
    for stray_x in (None, 3):
        game = _w1g1_duel(set_pool, {"W": 2, "U": 2})
        result, golem = _w1g1_cast(game, stray_x, kick=False)
        assert result.supported
        assert (golem.effective_power, golem.effective_toughness) == (1, 2)
        assert int(golem.metadata.get("plus_counters", 0) or 0) == 0
        assert not golem.metadata.get(_W1G1_KICKED)
        assert _w1g1_left(game) == {"U": 2}


def test_w1g1_an_emblazoned_golem_nothing_cast_has_no_counters(set_pool):
    """Put onto the battlefield without being cast: not kicked, no X, a 1/2."""
    game = _w1g1_duel(set_pool, {})
    golem = _W1G1Permanent(card=set_pool("APC")[_W1G1_GOLEM])
    game._put_permanent_onto_battlefield(0, golem, None)
    assert (golem.effective_power, golem.effective_toughness) == (1, 2)


def test_w1g1_the_restriction_reads_the_manas_real_color_under_celestial_dawn(set_pool):
    """CR 609.4b: spending mana "as though it were mana of any color" "doesn't
    change what mana was actually spent". Under Celestial Dawn five white mana
    could pay five different coloured *pips* — and is still one colour of
    mana, so it pays X = 1 and not X = 2. A green mana beside the white is a
    second colour and does: Celestial Dawn lets it pay only generic costs, and
    X is one."""
    dawn = set_pool("MIR")["Celestial Dawn"]

    game = _w1g1_duel(set_pool, {"W": 5}, board=[dawn])
    result, golem = _w1g1_cast(game, 2)
    assert not result.supported and golem is None
    assert _w1g1_left(game) == {"W": 5}

    game = _w1g1_duel(set_pool, {"W": 5}, board=[dawn])
    result, golem = _w1g1_cast(game, 1)
    assert result.supported and golem.effective_power == 2

    game = _w1g1_duel(set_pool, {"W": 1, "G": 3}, board=[dawn])
    result, golem = _w1g1_cast(game, 2)
    assert result.supported, result.details
    assert golem.effective_power == 3 and _w1g1_left(game) == {}


def test_w1g1_colorless_mana_is_not_colored_even_under_chromatic_orrery(set_pool):
    """"You may spend mana as though it were mana of any color." lets {C} pay a
    coloured pip; it does not make {C} coloured mana. Eight colourless pays no
    X at all, and a lone red among it pays X = 1 and not X = 2."""
    orrery = set_pool("M21")["Chromatic Orrery"]

    game = _w1g1_duel(set_pool, {"C": 8}, board=[orrery])
    assert not _w1g1_cast(game, 1)[0].supported

    game = _w1g1_duel(set_pool, {"C": 7, "R": 1}, board=[orrery])
    assert not _w1g1_cast(game, 2)[0].supported

    game = _w1g1_duel(set_pool, {"C": 7, "R": 1}, board=[orrery])
    result, golem = _w1g1_cast(game, 1)
    assert result.supported and golem.effective_power == 2
    assert _w1g1_left(game) == {"C": 5}


def test_w1g1_the_golems_x_box_is_capped_by_the_colors_the_board_can_make(set_pool):
    """The picker's ceiling is the payment's own: with a white and a blue mana
    and two colourless, the kicker can be taken and X goes up to 2 — not to the
    4 a count of mana would give. Four lands of one colour cap it at 1."""
    card = set_pool("APC")[_W1G1_GOLEM]
    game = _w1g1_duel(set_pool, {"W": 1, "U": 1, "C": 2})
    (offer,) = game.cast_cost_offers(0, card)
    assert (offer["label"], offer["symbols"], offer["max_times"]) == ("kicker", "{X}", 1)
    spec = game.cast_target_spec(0, card, optional_cost_payments={"{X}": 1})
    assert spec["announces_x"] and spec["max_x"] == 2
    assert not game.cast_target_spec(0, card).get("announces_x")

    plains = set_pool("LEA")["Plains"]
    game = _w1g1_duel(set_pool, {}, board=[plains] * 4)
    spec = game.cast_target_spec(0, card, optional_cost_payments={"{X}": 1})
    assert spec["max_x"] == 1


def test_w1g1_the_ai_kicks_emblazoned_golem_for_the_colors_it_has():
    """Pinned into both decks of six simulated games: it is cast, it is kicked
    for an X the seat's lands can colour, and it is never refused. (The floors
    sit under today's four casts and three kicks.)"""
    from engine.ai_simulator import run_ai_simulation

    report = run_ai_simulation(
        [_w1g1_manifest_set_path("APC", include_measured=True)],
        games=6, seed=1337, max_turns=18, required_cards=[_W1G1_GOLEM],
    )
    assert report.games_completed == 6
    cast = [l for l in report.log_lines if f" cast {_W1G1_GOLEM} -> resolved" in l]
    kicked = [l for l in report.log_lines if f" kicked {_W1G1_GOLEM} (X=" in l]
    assert len(cast) >= 2, cast
    assert len(kicked) >= 1, kicked
    for line in kicked:
        assert 1 <= int(line.rsplit("(X=", 1)[1].rstrip(")")) <= 5, line
    assert [k for k in report.refused_casts if k.split(":")[0] == _W1G1_GOLEM] == []
    assert [i.message for i in report.issues if _W1G1_GOLEM in i.message] == []
    w1g1_golem_left_nothing_owing = not report.steps_left_owing
    assert w1g1_golem_left_nothing_owing, report.steps_left_owing

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
