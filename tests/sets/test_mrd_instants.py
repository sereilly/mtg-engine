"""Mirrodin instants.

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


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve


def test_w1g3_assert_authority_exiles_what_it_counters_at_its_affinity_price(set_pool):
    """"Affinity for artifacts" / "Counter target spell. If that spell is
    countered this way, exile it instead of putting it into its owner's
    graveyard." Printed {5}{U}{U}. On the opponent's turn, with five artifact
    lands, it costs {U}{U}: two of them pay, the opponent's Grizzly Bears is
    countered into exile (CR 614.1's replacement of CR 701.6a's graveyard),
    and Assert Authority goes to its caster's graveyard. Mana costs are
    enforced for both seats."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[mrd["Assert Authority"]]),
        _W1G3PlayerState(name="W1G3-B", hand=[lea["Grizzly Bears"]]),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 1
    for w1g3_seat, w1g3_name, w1g3_count in (
        (0, "Seat of the Synod", 5), (1, "Forest", 2),
    ):
        for _ in range(w1g3_count):
            w1g3_card = mrd[w1g3_name] if w1g3_name in mrd else lea[w1g3_name]
            game._put_permanent_onto_battlefield(
                w1g3_seat, _W1G3Permanent(card=w1g3_card), None
            )
    for w1g3_seat, w1g3_color, w1g3_count in ((1, "G", 2), (0, "U", 2)):
        w1g3_lands = [
            p for p in game.controlled_by(w1g3_seat) if p.has_type("land")
        ][:w1g3_count]
        for w1g3_land in w1g3_lands:
            assert game.tap_land_for_mana(
                w1g3_seat, w1g3_land.card.name, w1g3_color,
                permanent_id=w1g3_land.permanent_id,
            )
    game.queue_from_hand(1, "Grizzly Bears")
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]
    counter = game.cast_from_hand(0, "Assert Authority", target_stack_index=0)
    assert counter.supported, counter.details
    assert sum(game.players[0].mana_pool.values()) == 0
    _w1g3_resolve(game)

    assert not [p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == []
    assert [getattr(c, "name", c) for c in game.players[1].exile] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Assert Authority"]


def _w1g3_duel(set_pool, mine=(), theirs=(), hand=(), their_hand=()):
    """Costs not enforced; nobody interactive; seat 0's turn."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")

    def w1g3_card(name):
        return mrd[name] if name in mrd else lea[name]

    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[w1g3_card(n) for n in hand]),
        _W1G3PlayerState(name="W1G3-B", hand=[w1g3_card(n) for n in their_hand]),
    ])
    w1g3_game.enforce_mana_costs = False
    w1g3_game.interactive_seats = set()
    w1g3_game.active_player_index = 0
    w1g3_rows = []
    for w1g3_seat, w1g3_names in ((0, mine), (1, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_perm = _W1G3Permanent(card=w1g3_card(w1g3_name))
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    return w1g3_game, w1g3_rows[0], w1g3_rows[1]  # _w1g3_duel


def test_w1g3_irradiate_shrinks_by_its_casters_artifacts(set_pool):
    """"Target creature gets -1/-1 until end of turn for each artifact you
    control." Three artifacts of the caster's (the opponent's count for
    nothing) make a Craw Wurm 3/1."""
    game, _mine, theirs = _w1g3_duel(
        set_pool, mine=["Ornithopter", "Ornithopter", "Seat of the Synod"],
        theirs=["Craw Wurm", "Ornithopter"], hand=["Irradiate"],
    )
    wurm = theirs[0]
    cast = game.cast_from_hand(0, "Irradiate", target_permanent_ids=[wurm.permanent_id])
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert (wurm.effective_power, wurm.effective_toughness) == (3, 1)


def test_w1g3_override_with_no_artifacts_asks_for_nothing(set_pool):
    """"…unless its controller pays {1} for each artifact you control." With
    none, the toll is {0}, which is paid (CR 118.5: a cost of zero is paid by
    acknowledging it) — the spell resolves. Paid off a Cloudpost is in
    ``test_mrd_lands.py``."""
    game, _mine, _theirs = _w1g3_duel(
        set_pool, hand=["Grizzly Bears"], their_hand=["Override"],
    )
    game.queue_from_hand(0, "Grizzly Bears")
    cast = game.cast_from_hand(1, "Override", target_stack_index=0)
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert any("pays {0}" in line and "not countered" in line for line in game.log)


def test_w1g3_shrapnel_blast_needs_exactly_one_artifact(set_pool):
    """"As an additional cost to cast this spell, sacrifice an artifact." /
    "Shrapnel Blast deals 5 damage to any target." The named Ornithopter is
    sacrificed and 5 is dealt; with no artifact the spell cannot be cast
    (its ruling, 2014-07-18: "you can't cast it without sacrificing an
    artifact") and nothing happens."""
    game, mine, _theirs = _w1g3_duel(
        set_pool, mine=["Ornithopter", "Seat of the Synod"], hand=["Shrapnel Blast"],
    )
    ornithopter, land = mine
    cast = game.cast_from_hand(
        0, "Shrapnel Blast", target_player_index=1,
        cost_permanent_ids=[ornithopter.permanent_id],
    )
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert game.players[1].life == 15
    assert not game.is_on_battlefield(ornithopter) and game.is_on_battlefield(land)

    game, _mine, _theirs = _w1g3_duel(
        set_pool, mine=["Grizzly Bears"], hand=["Shrapnel Blast"],
    )
    refused = game.cast_from_hand(0, "Shrapnel Blast", target_player_index=1)
    assert not refused.supported and "no artifact to sacrifice" in refused.details
    assert game.players[1].life == 20
    assert [c.name for c in game.players[0].hand] == ["Shrapnel Blast"]

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
