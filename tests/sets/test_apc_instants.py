"""Apocalypse instants.

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

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

from engine import Game as _w1g3i_Game, PlayerState as _w1g3i_Player
from engine.game_types import CardDefinition as _w1g3i_CardDefinition
from engine.models import Permanent as _w1g3i_Permanent
from tests.helpers import resolve_stack as _w1g3i_resolve_stack


def _w1g3i_card(name, type_line, power="2", toughness="2"):
    return _w1g3i_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": power, "toughness": toughness},
    )  # W1G3 instants: a typed card


def _w1g3i_bolt_game(set_pool, *, theirs=(), interactive=()):
    """Prophetic Bolt in seat 0's hand over a five-card library."""
    board1 = [_w1g3i_Permanent(card=card) for card in theirs]
    library = [_w1g3i_card(f"Card {n}", "Land") for n in range(1, 6)]
    game = _w1g3i_Game(players=[
        _w1g3i_Player(
            name="P0", hand=[set_pool("APC")["Prophetic Bolt"]], library=library,
        ),
        _w1g3i_Player(name="P1", battlefield=board1),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game, board1  # W1G3 instants: the Bolt's game


def test_w1g3_prophetic_bolt_offers_any_target_and_refuses_what_is_not_one(set_pool):
    """"Prophetic Bolt deals 4 damage to any target." The picker offers both
    players and the creature (CR 115.4) and not the artifact beside it; naming
    the artifact is refused at announcement with the card still in hand."""
    game, theirs = _w1g3i_bolt_game(set_pool, theirs=[
        _w1g3i_card("A Bear", "Creature — Bear"),
        _w1g3i_card("A Rock", "Artifact"),
    ])
    bear, rock = theirs
    bolt = set_pool("APC")["Prophetic Bolt"]

    spec = game.cast_target_spec(0, bolt)
    assert spec["requires_target"]
    offered = {
        (t["kind"], t.get("name", t["seat"])) for t in spec["valid_targets"]
    }
    assert offered == {("player", 0), ("player", 1), ("permanent", "A Bear")}

    refused = game.cast_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[rock.permanent_id],
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].hand] == ["Prophetic Bolt"]
    assert game.players[1].life == 20 and game.is_on_battlefield(rock)


def test_w1g3_prophetic_bolt_kills_the_creature_then_digs_four(set_pool):
    """"…deals 4 damage to any target. Look at the top four cards of your
    library. Put one of those cards into your hand and the rest on the bottom
    of your library in any order."

    A 2/4 takes the four; the caster looks at four — the spell held on the
    stack while it chooses (CR 608.2) — keeps the one it picks, and the other
    three go under the fifth card. The fifth is not an answer: it was never
    looked at. The creature dies when the spell has finished and not before.

    The rest go down **as they lay, unasked**. That is the look-and-pick
    family's standing convention, shared with Impulse and held by
    ``test_401_4_the_rest_going_to_the_bottom_is_not_asked_about``; the
    recruiters in this set do ask (``offer_library_bottom_order``), and the
    wave reported the difference rather than settling it from one side."""
    game, theirs = _w1g3i_bolt_game(
        set_pool, theirs=[_w1g3i_card("A Bear", "Creature — Bear", "2", "4")],
        interactive={0},
    )
    bear, = theirs
    me = game.players[0]

    assert game.cast_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[bear.permanent_id],
    ).supported

    # Mid-resolution: the damage is marked and the Bear is still there, because
    # state-based actions wait for the spell to finish (CR 704.3).
    assert bear.damage_marked == 4 and game.is_on_battlefield(bear), game.log
    assert [item.card.name for item in game.stack] == ["Prophetic Bolt"]
    assert game.waiting_prompt().kind == "look_top_pick"
    assert not game.confirm_look_top_pick(0, 4), "the fifth card was never looked at"

    assert game.confirm_look_top_pick(0, 2)
    game._settle()

    assert not game.is_on_battlefield(bear), game.log
    assert [c.name for c in game.players[1].graveyard] == ["A Bear"]
    assert [c.name for c in me.hand] == ["Card 3"]
    assert [c.name for c in me.library] == ["Card 5", "Card 1", "Card 2", "Card 4"]
    assert game.stack == [] and game.pending_choices == []
    assert [c.name for c in me.graveyard] == ["Prophetic Bolt"]


def test_w1g3_prophetic_bolt_at_a_player_with_nobody_to_ask(set_pool):
    """The same spell headless: four to the face, the first card looked at is
    kept (the stated default) and the rest go down as they lay."""
    game, _ = _w1g3i_bolt_game(set_pool)
    me = game.players[0]

    assert game.cast_from_hand(0, "Prophetic Bolt", target_player_index=1).supported
    game.auto_resolve_pending_choices()
    game._settle()

    assert game.players[1].life == 16 and me.life == 20
    assert [c.name for c in me.hand] == ["Card 1"]
    assert [c.name for c in me.library] == ["Card 5", "Card 2", "Card 3", "Card 4"]
    assert game.pending_choices == []
    assert [c.name for c in me.graveyard] == ["Prophetic Bolt"]


def test_w1g3_prophetic_bolt_whose_target_left_does_nothing_at_all(set_pool):
    """CR 608.2b: with its only target gone the spell is removed from the
    stack and none of it happens — the look is the rule's *second* sentence,
    not a consolation. The library is exactly as it was."""
    game, theirs = _w1g3i_bolt_game(
        set_pool, theirs=[_w1g3i_card("A Bear", "Creature — Bear")],
    )
    bear, = theirs
    me = game.players[0]

    assert game.queue_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[bear.permanent_id],
    ).supported
    game.remove_from_battlefield(bear)
    _w1g3i_resolve_stack(game)

    assert me.hand == [] and game.pending_choices == []
    assert [c.name for c in me.library] == [f"Card {n}" for n in range(1, 6)]
    assert [c.name for c in me.graveyard] == ["Prophetic Bolt"]
    assert game.players[1].life == 20

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
