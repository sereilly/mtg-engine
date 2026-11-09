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
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.cost_modifiers import cast_mana_charge as _w1g3_charge
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_find(set_pool, name):
    """*name* out of Mirrodin, else Alpha (a body or a basic) — pools kept
    separate and asked in that order."""
    for w1g3_code in ("MRD", "LEA"):
        w1g3_pool = set_pool(w1g3_code)
        if name in w1g3_pool:
            return w1g3_pool[name]
    raise KeyError(name)  # _w1g3_find


def _w1g3_table(set_pool, hand=(), mine=(), theirs=(), active=0):
    """A two-seat table with mana costs enforced — affinity changes a price,
    so nothing here is free — and every permanent past summoning sickness."""
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(
            name="W1G3-A", hand=[_w1g3_find(set_pool, n) for n in hand],
            library=[_w1g3_find(set_pool, "Island")] * 8,
        ),
        _W1G3PlayerState(
            name="W1G3-B", library=[_w1g3_find(set_pool, "Island")] * 8,
        ),
    ])
    w1g3_game.enforce_mana_costs = True
    w1g3_game.interactive_seats = set()
    w1g3_game.active_player_index = active
    w1g3_rows = []
    for w1g3_seat, w1g3_names in enumerate((mine, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_perm = _W1G3Permanent(card=_w1g3_find(set_pool, w1g3_name))
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    return w1g3_game, w1g3_rows[0], w1g3_rows[1]  # _w1g3_table


def _w1g3_tap(game, count, seat=0):
    """Tap *count* untapped lands *seat* controls for their first colour,
    through the real mana-ability entry point."""
    w1g3_tapped = 0
    for w1g3_land in list(game.controlled_by(seat)):
        if w1g3_tapped == count:
            break
        if w1g3_land.has_type("land") and not w1g3_land.tapped:
            w1g3_color = (w1g3_land.effective_produced_mana or ("C",))[0]
            assert game.tap_land_for_mana(
                seat, w1g3_land.card.name, w1g3_color,
                permanent_id=w1g3_land.permanent_id,
            ), game.log[-3:]
            w1g3_tapped += 1
    assert w1g3_tapped == count, f"only {w1g3_tapped} lands to tap"  # _w1g3_tap


def _w1g3_pool(game, seat=0):
    return sum(game.players[seat].mana_pool.values())  # _w1g3_pool


def _w1g3_on_board(game, name, seat=0):
    return [p for p in game.controlled_by(seat) if p.card.name == name]  # _w1g3_on_board


def test_w1g3_frogmite_reprices_as_artifacts_enter_and_leave(set_pool):
    """"Affinity for artifacts" (CR 702.41a: "This spell costs {1} less to cast
    for each artifact you control."). Printed {4}. Three artifact lands make it
    {1}, and one of them pays it — a tapped artifact is still an artifact. The
    first Frogmite is an artifact too, so the second costs {0} and is cast from
    an empty pool. Then an artifact land leaves, and the third Frogmite is back
    to {1}: refused with an empty pool, nothing spent, still in hand."""
    assert _w1g3_compile(set_pool("MRD")["Frogmite"]).supported
    frogmite = set_pool("MRD")["Frogmite"]
    game, mine, _theirs = _w1g3_table(
        set_pool, hand=["Frogmite", "Frogmite", "Frogmite"],
        mine=["Seat of the Synod"] * 3,
    )
    assert _w1g3_charge(game, 0, frogmite).get("generic") == 1
    _w1g3_tap(game, 1)
    cast = game.cast_from_hand(0, "Frogmite")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert _w1g3_pool(game) == 0 and len(_w1g3_on_board(game, "Frogmite")) == 1

    assert _w1g3_charge(game, 0, frogmite).get("generic") == 0
    cast = game.cast_from_hand(0, "Frogmite")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert len(_w1g3_on_board(game, "Frogmite")) == 2
    assert "Frogmite costs less to cast (Frogmite)" in game.log

    # Five artifacts; one leaves (CR 701.17a's sacrifice through the seam),
    # and with the other four Frogmite would still be free — so take two.
    game.sacrifice_permanents(mine[:2])
    assert len(_w1g3_on_board(game, "Seat of the Synod")) == 1
    assert _w1g3_charge(game, 0, frogmite).get("generic") == 1
    refused = game.cast_from_hand(0, "Frogmite")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Frogmite"]
    assert len(_w1g3_on_board(game, "Frogmite")) == 2


def test_w1g3_myr_enforcer_is_cast_for_what_its_artifacts_leave(set_pool):
    """Printed {7}: five artifact lands and a Frogmite are six artifacts, so
    it costs {1}; five lands' worth of artifacts alone would be {2}. An
    opponent's artifacts discount nothing — "you control" is the caster."""
    enforcer = set_pool("MRD")["Myr Enforcer"]
    game, _mine, _theirs = _w1g3_table(
        set_pool, hand=["Myr Enforcer"],
        mine=["Seat of the Synod"] * 5 + ["Frogmite"],
        theirs=["Seat of the Synod"] * 7,
    )
    assert _w1g3_charge(game, 0, enforcer).get("generic") == 1
    assert _w1g3_charge(game, 1, enforcer).get("generic") == 0
    _w1g3_tap(game, 1)
    cast = game.cast_from_hand(0, "Myr Enforcer")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    enforcer_perm = _w1g3_on_board(game, "Myr Enforcer")[0]
    assert (enforcer_perm.effective_power, enforcer_perm.effective_toughness) == (4, 4)
    assert _w1g3_pool(game) == 0


def test_w1g3_scale_and_tooth_flash_in_cheap_and_pump(set_pool):
    """Flash and affinity on one artifact: on the opponent's turn, with two
    artifact lands, Scale of Chiss-Goria costs {1} and Tooth of Chiss-Goria
    then costs {0} (Scale is the third artifact). Each taps at once — an
    artifact's {T} ability has no summoning sickness (CR 302.6 is about
    creatures) — for +0/+1 and +1/+0 on a creature."""
    game, _mine, theirs = _w1g3_table(
        set_pool, hand=["Scale of Chiss-Goria", "Tooth of Chiss-Goria"],
        mine=["Seat of the Synod"] * 2, theirs=["Grizzly Bears"], active=1,
    )
    bears = theirs[0]
    _w1g3_tap(game, 1)
    cast = game.cast_from_hand(0, "Scale of Chiss-Goria")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    cast = game.cast_from_hand(0, "Tooth of Chiss-Goria")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert _w1g3_pool(game) == 0
    for w1g3_name in ("Scale of Chiss-Goria", "Tooth of Chiss-Goria"):
        activated = game.activate_permanent_ability(
            0, w1g3_name, target_permanent_ids=[bears.permanent_id],
        )
        assert activated.supported, activated.details
        _w1g3_resolve(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)


def test_w1g3_every_reader_agrees_on_an_affinity_price(set_pool):
    """The price must agree everywhere it is read: the client's castable
    highlight and hand badge (``cast_mana_charge``), the AI's affordability
    read (``ai_payment._cost_for``) and the cast itself. With four artifact
    lands a {4} Frogmite is offered and is free; with none it is not offered
    off three Islands."""
    from fastapi.testclient import TestClient

    from engine.ai_payment import _cost_for
    from web.app import app, store

    client = TestClient(app)
    frogmite = set_pool("MRD")["Frogmite"]

    def offered(lands):
        response = client.post("/api/sessions", json={
            "mode": "human_vs_ai", "host_name": "W1G3", "host_colors": 2,
            "guest_colors": 2, "seed": 4103,
            "host_deck_cards": [{"name": "Island", "count": 40}],
            "guest_deck_cards": [{"name": "Island", "count": 40}],
        })
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]
        session = store.get(session_id)
        game = session.game
        session.pregame_phase = None
        session.current_turn = 0
        game.active_player_index = 0
        game.players[0].hand[:] = [frogmite]
        for name in lands:
            game._put_permanent_onto_battlefield(
                0, _W1G3Permanent(card=_w1g3_find(set_pool, name)), None
            )
        game.start_priority_window(0)
        state = client.get(
            f"/api/sessions/{session_id}/state", params={"seat": 0}
        ).json()
        return game, state["players"][0]["playable_hand_indices"]

    game, playable = offered(["Seat of the Synod"] * 4)
    assert playable == [0]
    assert _cost_for(game, game.players[0], frogmite, None)["generic"] == 0
    assert sum(_w1g3_charge(game, 0, frogmite).values()) == 0
    game, playable = offered(["Island"] * 3)
    assert playable == []
    assert _cost_for(game, game.players[0], frogmite, None)["generic"] == 4

# ==== end W1G3 ======================================================

# ==== end W1G3 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
