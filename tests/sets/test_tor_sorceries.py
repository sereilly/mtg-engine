"""Torment sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
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
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState  # noqa: E402
from engine import ai_policy as _w1g6_ai_policy  # noqa: E402
from tests.helpers import resolve_stack as _w1g6_resolve_stack  # noqa: E402


def _w1g6_promise_table(set_pool, catalog_by_name, mine, theirs) -> _W1G6Game:
    """Seat 0 holds *mine* (TOR first), seat 1 holds *theirs*; libraries of
    Islands; mana off."""
    def card(name):
        return set_pool("TOR").get(name) or catalog_by_name[name]

    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", hand=[card(n) for n in mine],
                         library=[catalog_by_name["Island"]] * 5),
        _W1G6PlayerState(name="P2", hand=[card(n) for n in theirs],
                         library=[catalog_by_name["Island"]] * 5,
                         graveyard=[catalog_by_name["Island"]] * 3),
    ])
    game.enforce_mana_costs = False
    return game


def test_w1g6_overmaster_s_next_instant_cannot_be_countered_and_only_that_one(
    set_pool, catalog_by_name,
):
    """"The next instant or sorcery spell you cast this turn can't be
    countered. Draw a card." A creature spell cast in between is not what it
    names and is countered as usual; the next instant is protected from
    Counterspell (which resolves and does nothing — the Bolt still hits),
    and the instant after it is not."""
    game = _w1g6_promise_table(
        set_pool, catalog_by_name,
        ["Overmaster", "Grizzly Bears", "Lightning Bolt", "Lightning Bolt"],
        ["Counterspell"] * 3,
    )
    assert game.cast_from_hand(0, "Overmaster").supported
    _w1g6_resolve_stack(game)
    assert len(game.players[0].hand) == 4, "Overmaster drew a card"

    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    # The AI does not spend a counterspell on a spell it cannot counter.
    counterspell = game.players[1].hand[0]
    assert _w1g6_ai_policy._cast_candidate(game, 1, counterspell, 0) is None
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17
    assert any("can't be countered (Overmaster)" in line for line in game.log)

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert _w1g6_ai_policy._cast_candidate(game, 1, game.players[1].hand[0], 0) is not None
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17, "the second Bolt was countered"


def test_w1g6_overmaster_also_stops_a_counter_that_asks_for_a_payment(set_pool, catalog_by_name):
    """"Counter target spell unless its controller pays …" (Circular Logic)
    against the protected spell asks for nothing: CR 701.6a — a spell that
    can't be countered isn't, so there is no payment to offer."""
    game = _w1g6_promise_table(
        set_pool, catalog_by_name, ["Overmaster", "Lightning Bolt"], ["Circular Logic"],
    )
    assert game.cast_from_hand(0, "Overmaster").supported
    _w1g6_resolve_stack(game)
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.cast_from_hand(1, "Circular Logic", target_stack_index=0).supported
    assert not game.pending_choices
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17


def test_w1g6_insist_s_promise_is_for_creature_spells_and_ends_with_the_turn(
    set_pool, catalog_by_name,
):
    """"The next creature spell you cast this turn can't be countered." An
    instant cast in between is countered as usual; the creature is not. A
    promise nobody spent is gone at the next turn."""
    game = _w1g6_promise_table(
        set_pool, catalog_by_name,
        ["Insist", "Lightning Bolt", "Grizzly Bears"], ["Counterspell"] * 2,
    )
    assert game.cast_from_hand(0, "Insist").supported
    _w1g6_resolve_stack(game)
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 20
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(0)]

    game = _w1g6_promise_table(
        set_pool, catalog_by_name, ["Insist", "Grizzly Bears"], ["Counterspell"],
    )
    assert game.cast_from_hand(0, "Insist").supported
    _w1g6_resolve_stack(game)
    game.turn += 1
    game.start_turn(1)
    game.turn += 1
    game.start_turn(0)
    game.players[0].hand.append(catalog_by_name["Grizzly Bears"])
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]


def test_w1g6_a_copy_of_the_protected_spell_is_not_protected(set_pool, catalog_by_name):
    """CR 707.10: a copy is not cast, so it spends no promise, and the effect
    on the original is not a copiable value. Forked, the protected Bolt's copy
    is countered and the original is not."""
    game = _w1g6_promise_table(
        set_pool, catalog_by_name, ["Overmaster", "Lightning Bolt", "Fork"],
        ["Counterspell", "Counterspell"],
    )
    assert game.cast_from_hand(0, "Overmaster").supported
    _w1g6_resolve_stack(game)
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported
    game.resolve_top_of_stack()
    copy = game.stack[-1]
    assert copy.is_copy and copy.uncounterable_by is None
    # Engine (bottom-first) indices: 0 is the original, 1 the copy.
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=1).supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17, "the original hit, the copy was countered"
    assert any("countered Lightning Bolt (copy)" in line for line in game.log)

from engine.models import Permanent as _W1G6Permanent  # noqa: E402


def test_w1g6_chainer_s_edict_and_its_flashback(set_pool, catalog_by_name):
    """"Target player sacrifices a creature of their choice. Flashback
    {5}{B}{B}." Cast from hand, then flashed back: two creatures go, and the
    card ends in exile."""
    game = _w1g6_promise_table(set_pool, catalog_by_name, ["Chainer's Edict"], [])
    for name in ("Grizzly Bears", "Hill Giant"):
        game._put_permanent_onto_battlefield(
            1, _W1G6Permanent(card=catalog_by_name[name]), None
        )
    assert game.cast_from_hand(0, "Chainer's Edict", target_player_index=1).supported
    _w1g6_resolve_stack(game)
    assert len(list(game.controlled_by(1))) == 1
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"B": 2, "C": 5})
    assert game.cast_from_hand(
        0, "Chainer's Edict", target_player_index=1, from_zone="graveyard",
    ).supported
    _w1g6_resolve_stack(game)
    assert list(game.controlled_by(1)) == []
    assert [c.name for c in game.players[0].exile] == ["Chainer's Edict"]


def test_w1g6_acorn_harvest_and_crippling_fatigue_flash_back_for_mana_and_life(
    set_pool, catalog_by_name,
):
    """"Flashback--{1}{G}, Pay 3 life." / "Flashback--{1}{B}, Pay 3 life." The
    life is paid with the mana: two 1/1 green Squirrels for {1}{G} and 3
    life, and -2/-2 on a Hill Giant for {1}{B} and 3 more."""
    game = _w1g6_promise_table(set_pool, catalog_by_name, [], [])
    game.players[0].graveyard.extend(
        set_pool("TOR")[name] for name in ("Acorn Harvest", "Crippling Fatigue")
    )
    giant = _W1G6Permanent(card=catalog_by_name["Hill Giant"])
    game._put_permanent_onto_battlefield(1, giant, None)
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"G": 1, "C": 1})
    assert game.cast_from_hand(0, "Acorn Harvest", from_zone="graveyard").supported
    _w1g6_resolve_stack(game)
    squirrels = list(game.controlled_by(0))
    assert [(p.effective_power, p.effective_toughness) for p in squirrels] == [(1, 1), (1, 1)]
    assert all("G" in p.effective_colors for p in squirrels)
    assert game.players[0].life == 17
    game.players[0].mana_pool.update({"B": 1, "C": 1})
    assert game.cast_from_hand(
        0, "Crippling Fatigue", target_permanent_ids=[giant.permanent_id],
        target_player_index=1, from_zone="graveyard",
    ).supported
    _w1g6_resolve_stack(game)
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)
    assert game.players[0].life == 14
    assert sorted(c.name for c in game.players[0].exile) == ["Acorn Harvest", "Crippling Fatigue"]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
