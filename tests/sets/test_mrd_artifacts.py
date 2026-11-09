"""Mirrodin artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_game(set_pool, mine=(), hand=(), theirs=(), their_hand=(), interactive=(),
               library=None):
    pool = set_pool("MRD")
    other = set_pool("LEA")

    def card(name):
        return pool[name] if name in pool else other[name]

    p1 = _w1g7_PlayerState(
        name="P1",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in mine],
        hand=[card(n) for n in hand],
        library=[card(n) for n in library] if library is not None else [other["Island"]] * 10,
    )
    p2 = _w1g7_PlayerState(
        name="P2",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in theirs],
        hand=[card(n) for n in their_hand], library=[other["Island"]] * 10,
    )
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _w1g7_settle(game):
    _w1g7_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g7_resolve(game)


def _w1g7_named(player, name):
    return next(p for p in player.battlefield if p.card.name == name)


def test_w1g7_serum_tank_counts_its_own_entry_and_every_other_artifact(set_pool):
    """"Whenever this artifact **or another artifact** enters, put a charge
    counter on this artifact." The union row read "this creature or" alone, so
    the line matched nothing and the Tank shipped "supported" on its draw line
    with no way to get a counter. Its own entry counts, another artifact counts,
    an opponent's artifact counts, a nonartifact creature does not — and the
    counter pays the draw."""
    game, p1, _p2 = _w1g7_game(
        set_pool, hand=["Serum Tank", "Ornithopter", "Grizzly Bears"],
        their_hand=["Ornithopter"],
    )
    game.cast_from_hand(0, "Serum Tank")
    _w1g7_settle(game)
    tank = _w1g7_named(p1, "Serum Tank")
    assert tank.metadata.get("charge_counters") == 1
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 2
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 3
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 3

    _w1g7_nosick(tank)
    hand_before = len(p1.hand)
    result = game.activate_permanent_ability(
        0, "Serum Tank", permanent_index=game.battlefield_index_of(tank),
    )
    assert result.supported, result.details
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 2
    assert len(p1.hand) == hand_before + 1


def _w1g7_open_main(game, seat, *, before_main=None):
    """Step *seat*'s turn to its first main phase and return each pool, emptied
    first. *before_main* runs after the untap step (a tap in upkeep)."""
    for player in game.players:
        for symbol in list(player.mana_pool):
            player.mana_pool[symbol] = 0
    game.start_turn(seat)
    if before_main is not None:
        before_main()
    while game.current_turn_phase != "precombat_main":
        game.advance_phase()
    _w1g7_settle(game)
    return [
        {sym: n for sym, n in player.mana_pool.items() if n}
        for player in game.players
    ]


def test_w1g7_blinkmoth_urn_pays_each_player_for_their_own_artifacts(set_pool):
    """"At the beginning of **each player's** first main phase, if this
    artifact is untapped, **that player** adds {C} for each artifact **they**
    control." The trigger, the frozen seat and the intervening-if all shipped
    (Eladamri's Vineyard, Farsight-style "if this artifact is untapped"); the
    count behind the mana did not. The Urn counts itself for its controller,
    and the opponent's turn counts the opponent's board."""
    game, _p1, p2 = _w1g7_game(
        set_pool, mine=["Blinkmoth Urn", "Ornithopter", "Ornithopter"],
        theirs=["Ornithopter"],
    )
    assert _w1g7_open_main(game, 0) == [{"C": 3}, {}], game.log
    assert _w1g7_open_main(game, 1) == [{}, {"C": 1}], game.log
    p2.battlefield.append(_w1g7_Permanent(card=set_pool("MRD")["Ornithopter"]))
    game._settle()
    assert _w1g7_open_main(game, 1) == [{}, {"C": 2}], "counted at resolution"


def test_w1g7_blinkmoth_urn_tapped_pays_nobody(set_pool):
    """The intervening "if" (CR 603.4): tapped as the main phase begins, the
    Urn does not trigger — on the opponent's turn its controller's untap step
    has not come round."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Blinkmoth Urn", "Ornithopter"], theirs=["Ornithopter"],
    )
    urn = _w1g7_named(p1, "Blinkmoth Urn")
    urn.tapped = True
    assert _w1g7_open_main(game, 1) == [{}, {}], game.log
    assert _w1g7_open_main(game, 0) == [{"C": 2}, {}], "untapped in its untap step"


def test_w1g7_blinkmoth_urn_tapped_in_response_pays_nothing(set_pool):
    """CR 603.4 asks the intervening "if" again on resolution: an Urn tapped
    while its trigger waits on the stack adds nothing."""
    game, p1, _p2 = _w1g7_game(set_pool, mine=["Blinkmoth Urn", "Ornithopter"])
    urn = _w1g7_named(p1, "Blinkmoth Urn")
    game.start_turn(0)
    while game.current_turn_phase != "precombat_main":
        game.advance_phase()
    assert any(item.card.name == "Blinkmoth Urn" for item in game.stack), game.log
    urn.tapped = True
    _w1g7_settle(game)
    assert not any(p1.mana_pool.values()), game.log

def test_w1g7_sculpting_steel_enters_as_a_copy_of_the_chosen_artifact(set_pool):
    """"You may have this artifact enter as a copy of any artifact on the
    battlefield." Clone's and Copy Artifact's sentences were two literals, and
    "this artifact … any artifact" was neither. Aimed at the opponent's Serum
    Tank over my Ornithopter, it is a Serum Tank — under my control, with the
    Tank's own entry trigger counting its arrival (CR 707.5) and the original
    Tank counting it too. The picker offers artifacts, optionally."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    pool = set_pool("MRD")
    steel_card = pool["Sculpting Steel"]
    assert derive_cast_spec(steel_card, compile_card_oracle(steel_card)) == {
        "kind": "artifact", "optional": True,
    }

    game, p1, p2 = _w1g7_game(
        set_pool, mine=["Ornithopter"], hand=["Sculpting Steel"], theirs=["Serum Tank"],
    )
    their_tank = p2.battlefield[0]
    assert game.cast_from_hand(
        0, "Sculpting Steel", target_permanent_ids=[their_tank.permanent_id]
    ).supported
    _w1g7_settle(game)
    steel = next(p for p in p1.battlefield if p.card.name == "Sculpting Steel")
    assert steel.effective_card.name == "Serum Tank"
    assert steel.has_type("artifact") and not steel.is_creature
    assert steel.metadata.get("charge_counters") == 1, game.log
    assert their_tank.metadata.get("charge_counters") == 1, "another artifact entered"


def test_w1g7_sculpting_steel_with_nothing_to_copy_is_itself(set_pool):
    game, p1, _p2 = _w1g7_game(set_pool, hand=["Sculpting Steel", "Grizzly Bears"])
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert game.cast_from_hand(0, "Sculpting Steel").supported
    _w1g7_settle(game)
    steel = next(p for p in p1.battlefield if p.card.name == "Sculpting Steel")
    assert steel.effective_card.name == "Sculpting Steel", "a creature is not an artifact"

# ==== end W1G7 ======================================================
