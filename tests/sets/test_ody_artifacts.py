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


from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_duel(set_pool, *, hand0=(), hand1=(), bf0=(), bf1=(), costs=False):
    """A two-seat game built from card names (Odyssey first, then Alpha),
    both seats interactive so an offer is a prompt, nobody summoning-sick."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name=f"P{seat}", life=20, hand=[pool[n] for n in hand],
            library=[pool["Forest"]] * 10,
        )
        for seat, hand in enumerate((hand0, hand1))
    ])
    game.enforce_mana_costs = costs
    game.interactive_seats = {0, 1}
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            permanent = _w1g9_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game  # _w1g9_duel (artifacts)


def _w1g9_stack(game):
    return [
        (item.card.name,
         "ability" if item.is_ability else "copy" if item.is_copy else "spell")
        for item in game.stack
    ]


# --- Mirari ----------------------------------------------------------------

def test_mirari_copies_the_instant_its_controller_pays_three_for(set_pool):
    """"Whenever you cast an instant or sorcery spell, you may pay {3}. If you
    do, copy that spell. You may choose new targets for the copy." The trigger
    took its {3} and copied nothing: its cast event froze no spell."""
    game = _w1g9_duel(
        set_pool, hand0=["Lightning Bolt"], bf0=["Mirari"], costs=True,
    )
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert _w1g9_stack(game) == [("Lightning Bolt", "spell"), ("Mirari", "ability")]
    game.resolve_top_of_stack(pause_for_choices=True)
    offer = game.pending_choices[0]
    assert (offer.kind, offer.player_index, offer.data["cost"]) == (
        "optional_pay", 0, {"generic": 3},
    )
    assert game.confirm_optional_pay(0, accept=True)
    # "You may choose new targets for the copy": asked of Mirari's controller,
    # with the trigger held on the stack until it is answered (CR 608.2).
    retarget = game.pending_choice_of("copy_spell_target")
    assert retarget is not None and retarget.player_index == 0
    game.take_choice_default(retarget)  # decline: the copy keeps its target
    assert _w1g9_stack(game) == [
        ("Lightning Bolt", "spell"), ("Lightning Bolt", "copy"),
    ], "one copy, and a copy is not cast: no second trigger"
    assert sum(game.players[0].mana_pool.values()) == 0
    _w1g9_resolve_stack(game)
    assert game.players[1].life == 14
    assert [c.name for c in game.players[0].graveyard] == ["Lightning Bolt"]


def test_mirari_copies_nothing_for_a_controller_who_declines_or_cannot_pay(set_pool):
    for mana, accept in (({"R": 1, "C": 3}, False), ({"R": 1}, True)):
        game = _w1g9_duel(
            set_pool, hand0=["Lightning Bolt"], bf0=["Mirari"], costs=True,
        )
        game.players[0].mana_pool.update(mana)
        assert game.queue_from_hand(
            0, "Lightning Bolt", target_player_index=1
        ).supported
        game.resolve_top_of_stack(pause_for_choices=True)
        if game.pending_choices:
            game.confirm_optional_pay(0, accept=accept)
        assert _w1g9_stack(game) == [("Lightning Bolt", "spell")]
        _w1g9_resolve_stack(game)
        assert game.players[1].life == 17


def test_mirari_watches_only_its_controllers_instants_and_sorceries(set_pool):
    game = _w1g9_duel(
        set_pool, hand0=["Grizzly Bears", "Crusade", "Stream of Life"],
        hand1=["Lightning Bolt"], bf0=["Mirari"],
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert _w1g9_stack(game) == [("Lightning Bolt", "spell")], "an opponent's"
    _w1g9_resolve_stack(game)
    for name in ("Grizzly Bears", "Crusade"):
        assert game.queue_from_hand(0, name).supported
        assert _w1g9_stack(game) == [(name, "spell")], "not an instant or sorcery"
        _w1g9_resolve_stack(game)
    assert game.queue_from_hand(
        0, "Stream of Life", target_player_index=0, x_value=2
    ).supported
    assert _w1g9_stack(game) == [("Stream of Life", "spell"), ("Mirari", "ability")]


def test_mirari_copies_the_x_and_the_creature_a_spell_was_aimed_at(set_pool):
    """CR 707.10: the copy has the original's decisions - the creature named
    by id (the wire's spelling, which the copy used to lose for the seat) and
    the value of X."""
    game = _w1g9_duel(
        set_pool, hand0=["Lightning Bolt", "Stream of Life"], bf0=["Mirari"],
        bf1=["Craw Wurm", "Craw Wurm"],
    )
    game.players[0].mana_pool.update({"C": 6})
    _, second = [p for p in game.controlled_by(1)]
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[second.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g9_resolve_stack(game)
    assert second.damage_marked == 6 and game.players[1].life == 20

    assert game.queue_from_hand(
        0, "Stream of Life", target_player_index=0, x_value=4
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g9_resolve_stack(game)
    assert game.players[0].life == 28

# ==== end W1G9 ======================================================
