"""Mirrodin sorceries.

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
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from tests.helpers import resolve_stack as _w1g7_resolve


def _w1g7_wrench_mind(set_pool, their_hand, interactive=()):
    mrd, lea = set_pool("MRD"), set_pool("LEA")

    def card(name):
        return mrd[name] if name in mrd else lea[name]

    p1 = _w1g7_PlayerState(
        name="P1", hand=[mrd["Wrench Mind"]], library=[lea["Island"]] * 5,
    )
    p2 = _w1g7_PlayerState(
        name="P2", hand=[card(n) for n in their_hand], library=[lea["Island"]] * 5,
    )
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    assert game.cast_from_hand(0, "Wrench Mind", target_player_index=1).supported
    for _ in range(5):
        if not game.stack or game.pending_choices:
            break
        game.resolve_top_of_stack()
    return game, p2


def test_w1g7_wrench_mind_a_headless_target_pays_with_its_artifact(set_pool):
    """"Target player discards two cards unless they discard an artifact
    card." The "you" spelling (Thirst for Knowledge) shipped; the targeted
    player's discard refused any narrowing. One artifact card is the whole
    price, and the default pays it."""
    game, p2 = _w1g7_wrench_mind(set_pool, ["Ornithopter", "Island", "Mountain"])
    _w1g7_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g7_resolve(game)
    assert [c.name for c in p2.graveyard] == ["Ornithopter"], game.log
    assert sorted(c.name for c in p2.hand) == ["Island", "Mountain"]


def test_w1g7_wrench_mind_without_an_artifact_card_two_go(set_pool):
    """No artifact card in hand: the offer cannot be taken (CR 601.2h asks what
    a player is able to do) — the takeability check counted the whole hand, so
    a narrowed price would have been "paid" with nothing."""
    game, p2 = _w1g7_wrench_mind(
        set_pool, ["Grizzly Bears", "Island", "Mountain"], interactive=(1,),
    )
    assert game.pending_choice_of("optional_pay", 1) is None, "no offer to make"
    prompt = game.pending_choice_of("discard", 1)
    assert prompt is not None and prompt.data["count"] == 2
    assert game.resolve_pending_choice("discard", 1, hand_indices=[1, 2], to_library=False)
    _w1g7_resolve(game)
    assert [c.name for c in p2.hand] == ["Grizzly Bears"]
    assert len(p2.graveyard) == 2


def test_w1g7_wrench_mind_an_interactive_target_chooses(set_pool):
    """The target is asked; accepting offers only the artifact card, and
    declining asks for two of any."""
    game, p2 = _w1g7_wrench_mind(
        set_pool, ["Ornithopter", "Island", "Mountain"], interactive=(1,),
    )
    assert game.pending_choice_of("optional_pay", 1) is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 1, accept=True)
    prompt = game.pending_choice_of("discard", 1)
    assert prompt is not None and prompt.data["count"] == 1
    assert [p2.hand[i].name for i in game.live_discard_candidates(prompt)] == ["Ornithopter"]
    assert not game.resolve_pending_choice("discard", 1, hand_indices=[1], to_library=False), (
        "an Island is not an artifact card"
    )
    assert game.resolve_pending_choice("discard", 1, hand_indices=[0], to_library=False)
    _w1g7_resolve(game)
    assert [c.name for c in p2.graveyard] == ["Ornithopter"]

    game, p2 = _w1g7_wrench_mind(
        set_pool, ["Ornithopter", "Island", "Mountain"], interactive=(1,),
    )
    assert game.resolve_pending_choice("optional_pay", 1, accept=False)
    prompt = game.pending_choice_of("discard", 1)
    assert prompt is not None and prompt.data["count"] == 2
    assert len(game.live_discard_candidates(prompt)) == 3
    assert game.resolve_pending_choice("discard", 1, hand_indices=[1, 2], to_library=False)
    _w1g7_resolve(game)
    assert [c.name for c in p2.hand] == ["Ornithopter"]


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
