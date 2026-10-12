"""Odyssey artifacts.

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

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from engine.cost_modifiers import (cost_modifier_claims_line as _w1g3_claims_line,
                                   keyword_cost_modifiers as _w1g3_keyword_cost_modifiers)
from engine.mana_payment import mana_cost_from_symbols as _w1g3_mana_cost_from_symbols
from engine.models import (CardDefinition as _w1g3_CardDefinition,
                           Permanent as _w1g3_Permanent)
from engine.oracle import compile_card_oracle as _w1g3_compile

# Catalyst Stone: "Flashback costs you pay cost {2} less." / "Flashback costs
# your opponents pay cost {2} more." CR 601.2f over CR 702.34a's alternative
# cost (CR 118.9d) — a modifier that has no opinion about the spell, only
# about which cost is being paid for it and by whom.


def _w1g3_stone_game(set_pool, stones: int = 1, *, controller: int = 0) -> _w1g3_Game:
    game = _w1g3_Game(players=[_w1g3_PlayerState(name="P1"), _w1g3_PlayerState(name="P2")])
    game.enforce_mana_costs = True
    for _ in range(stones):
        game._put_permanent_onto_battlefield(
            controller, _w1g3_Permanent(card=set_pool("ODY")["Catalyst Stone"]), None
        )
    return game


def _w1g3_pay(player, cost: str) -> None:
    """Exactly *cost* in *player*'s pool, the generic part as colourless."""
    pool = {symbol: 0 for symbol in "WUBRGC"}
    for symbol, count in _w1g3_mana_cost_from_symbols(cost).items():
        pool["C" if symbol == "generic" else symbol] += count
    player.mana_pool.update(pool)


def _w1g3_flashback_costs(game, seat: int, card, cost: str, short: str | None = None) -> bool:
    """Whether *seat*'s flashback of *card* (aimed at the other seat) costs
    exactly *cost*: refused with *short* in the pool, cast with *cost* in it
    and nothing left over."""
    if not any(held is card for held in game.players[seat].graveyard):
        game.players[seat].graveyard.append(card)
    keywords = {"target_player_index": 1 - seat}
    if short is not None:
        _w1g3_pay(game.players[seat], short)
        if game.cast_from_hand(seat, card.name, from_zone="graveyard", **keywords).supported:
            return False
    _w1g3_pay(game.players[seat], cost)
    cast = game.cast_from_hand(seat, card.name, from_zone="graveyard", **keywords)
    return cast.supported and not any(game.players[seat].mana_pool.values())


def test_w1g3_catalyst_stone_compiles_on_both_of_its_lines(set_pool):
    stone = set_pool("ODY")["Catalyst Stone"]
    assert _w1g3_compile(stone).supported
    for line in stone.oracle_text.split("\n"):
        assert _w1g3_claims_line(line), line
    # A keyword whose cost nothing pays *as* that keyword's is not claimed, and
    # a permanent printing only that is not supported on the strength of it.
    unread = "Madness costs you pay cost {2} less."
    assert not _w1g3_claims_line(unread)
    assert not _w1g3_compile(_w1g3_CardDefinition(
        name="Test Stone", mana_cost="{2}", cmc=2.0, type_line="Artifact",
        oracle_text=unread, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={},
    )).supported


def test_w1g3_catalyst_stone_makes_its_controller_s_flashback_cheaper(set_pool):
    ody = set_pool("ODY")
    game = _w1g3_stone_game(set_pool)
    assert _w1g3_keyword_cost_modifiers(game, 0, "flashback") == (0, 2, ["Catalyst Stone"])
    # Firebolt prints Flashback {4}{R}.
    assert _w1g3_flashback_costs(game, 0, ody["Firebolt"], "{2}{R}", short="{1}{R}")
    assert game.players[1].life == 18
    assert any("flashback cost is changed by Catalyst Stone" in line for line in game.log)
    # Nothing else about a flashback card is cheaper: from a hand it costs
    # what it prints.
    game = _w1g3_stone_game(set_pool)
    game.players[0].hand.append(ody["Roar of the Wurm"])
    _w1g3_pay(game.players[0], "{5}{G}")
    assert not game.cast_from_hand(0, "Roar of the Wurm").supported
    _w1g3_pay(game.players[0], "{6}{G}")
    assert game.cast_from_hand(0, "Roar of the Wurm").supported


def test_w1g3_catalyst_stone_makes_an_opponent_s_flashback_dearer(set_pool):
    ody = set_pool("ODY")
    game = _w1g3_stone_game(set_pool)
    assert _w1g3_keyword_cost_modifiers(game, 1, "flashback") == (2, 0, ["Catalyst Stone"])
    assert _w1g3_flashback_costs(game, 1, ody["Firebolt"], "{6}{R}", short="{5}{R}")
    assert game.players[0].life == 18
    # "Your opponents" follows the Stone: under seat 1's control it is seat 0
    # that pays more and seat 1 that pays less.
    game = _w1g3_stone_game(set_pool, controller=1)
    assert _w1g3_flashback_costs(game, 0, ody["Firebolt"], "{6}{R}", short="{5}{R}")
    assert _w1g3_flashback_costs(game, 1, ody["Firebolt"], "{2}{R}", short="{1}{R}")


def test_w1g3_two_stones_add_up_and_a_reduction_stops_at_the_coloured_pips(set_pool):
    """CR 118.7a: a generic reduction touches only the generic component.
    Two Stones take {4} off Firebolt's {4}{R} and leave {R}; Volley of
    Boulders' flashback is six red pips and nothing else, so no number of
    Stones takes anything off it."""
    ody = set_pool("ODY")
    game = _w1g3_stone_game(set_pool, 2)
    assert _w1g3_flashback_costs(game, 0, ody["Firebolt"], "{R}")
    game = _w1g3_stone_game(set_pool, 2)
    assert _w1g3_flashback_costs(game, 1, ody["Firebolt"], "{8}{R}", short="{7}{R}")

    volley = ody["Volley of Boulders"]
    for stones in (1, 2):
        game = _w1g3_stone_game(set_pool, stones)
        game.players[0].graveyard.append(volley)
        _w1g3_pay(game.players[0], "{R}{R}{R}{R}{R}")
        assert not game.cast_from_hand(
            0, "Volley of Boulders", from_zone="graveyard", divided_targets=[(1, None, 6)],
        ).supported
        _w1g3_pay(game.players[0], "{R}{R}{R}{R}{R}{R}")
        assert game.cast_from_hand(
            0, "Volley of Boulders", from_zone="graveyard", divided_targets=[(1, None, 6)],
        ).supported
        assert game.players[1].life == 14


def test_w1g3_catalyst_stone_reads_the_cost_recoup_grants(set_pool):
    """A flashback cost an effect granted is a flashback cost: Recoup gives
    Wrath of God flashback {2}{W}{W}, and the Stone's controller pays {W}{W}."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g3_stone_game(set_pool)
    game.players[0].hand.append(ody["Recoup"])
    game.players[0].graveyard.append(lea["Wrath of God"])
    _w1g3_pay(game.players[0], "{1}{R}")
    assert game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=0).supported
    _w1g3_pay(game.players[0], "{W}")
    assert not game.cast_from_hand(0, "Wrath of God", from_zone="graveyard").supported
    _w1g3_pay(game.players[0], "{W}{W}")
    assert game.cast_from_hand(0, "Wrath of God", from_zone="graveyard").supported
    assert not any(game.players[0].mana_pool.values())

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

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
