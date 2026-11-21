"""Betrayers of Kamigawa artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), interactive=(), library=20):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * library,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_put(game, card, seat=0):
    permanent = _W1G7Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g7_named(game, name):
    return [perm for perm in game.all_permanents() if perm.card.name == name]


def test_w1g7_orb_of_dreams_taps_every_entering_permanent_but_itself(set_pool):
    """Permanents enter tapped. CR 614.12: the replacement comes from the Orb
    only for what is already on the battlefield — its example is Orb of
    Dreams entering untapped. Then a played land, a creature spell, the
    tokens a spell creates and an opponent's creature all enter tapped, and so
    does a second Orb (the first one's effect reaches it)."""
    bok, lea, chk = set_pool("BOK"), set_pool("LEA"), set_pool("CHK")
    game = _w1g7_table(
        set_pool,
        hand=[bok["Orb of Dreams"], lea["Forest"], lea["Grizzly Bears"], bok["Orb of Dreams"]],
    )
    assert game.cast_from_hand(0, "Orb of Dreams").supported
    _w1g7_settle(game)
    (orb,) = _w1g7_named(game, "Orb of Dreams")
    assert not orb.tapped
    assert game.cast_from_hand(0, "Forest").supported
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g7_settle(game)
    assert _w1g7_named(game, "Forest")[0].tapped
    assert _w1g7_named(game, "Grizzly Bears")[0].tapped
    # A token is a permanent too, and so is the opponent's creature.
    _w1g7_put(game, chk["Kami of the Hunt"], seat=1)
    assert _w1g7_named(game, "Kami of the Hunt")[0].tapped
    assert game.cast_from_hand(0, "Orb of Dreams").supported
    _w1g7_settle(game)
    assert sorted(perm.tapped for perm in _w1g7_named(game, "Orb of Dreams")) == [False, True]


def test_w1g7_orb_of_dreams_taps_tokens(set_pool):
    """A token a spell creates enters tapped under the Orb (every road onto
    the battlefield passes the one entry seam)."""
    bok, mrd = set_pool("BOK"), set_pool("MRD")
    game = _w1g7_table(set_pool, hand=[mrd["Raise the Alarm"]])
    _w1g7_put(game, bok["Orb of Dreams"])
    assert game.cast_from_hand(0, "Raise the Alarm").supported
    _w1g7_settle(game)
    soldiers = _w1g7_named(game, "Soldier Token")
    assert len(soldiers) == 2 and all(perm.tapped for perm in soldiers)


def test_w1g7_mirror_gallery_switches_the_legend_rule_off_while_it_stays(set_pool):
    """The "legend rule" doesn't apply. Two Ishi-Ishi under one controller stay
    while the Gallery is on the battlefield, with nothing asked; the first
    state-based check after it leaves applies the rule again (its 2005-02-01
    ruling), and a seat nobody asks keeps one."""
    bok = set_pool("BOK")
    game = _w1g7_table(set_pool)
    gallery = _w1g7_put(game, bok["Mirror Gallery"])
    first = _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    second = _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    game.check_state_based_actions()
    _w1g7_settle(game)
    assert game.is_on_battlefield(first) and game.is_on_battlefield(second)
    assert not any("704.5j" in line for line in game.log)
    game.remove_from_battlefield(gallery)
    game._permanent_to_graveyard(game.players[0], gallery)
    game.check_state_based_actions()
    _w1g7_settle(game)
    assert len(_w1g7_named(game, "Ishi-Ishi, Akki Crackshot")) == 1
    assert "Ishi-Ishi, Akki Crackshot put into graveyard (704.5j: legend rule)" in game.log


def test_w1g7_mirror_gallery_withdraws_and_restores_a_persons_legend_rule_prompt(set_pool):
    """At a seat a person sits at the rule asks which to keep (CR 704.5j). A
    Gallery arriving while that prompt is owed drops it — the group is no
    group while the rule doesn't apply — and nothing leaves; when the Gallery
    goes the prompt is armed again and the answer is what stays."""
    bok = set_pool("BOK")
    game = _w1g7_table(set_pool, interactive=(0,))
    first = _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    second = _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    game.check_state_based_actions()
    owed = [c for c in game.pending_choices if c.kind == "legend_rule"]
    assert len(owed) == 1
    assert owed[0].data["candidates"] == [first.permanent_id, second.permanent_id]
    gallery = _w1g7_put(game, bok["Mirror Gallery"])
    game.check_state_based_actions()
    assert not [c for c in game.pending_choices if c.kind == "legend_rule"]
    assert game.is_on_battlefield(first) and game.is_on_battlefield(second)
    game.remove_from_battlefield(gallery)
    game._permanent_to_graveyard(game.players[0], gallery)
    game.check_state_based_actions()
    assert [c.kind for c in game.pending_choices] == ["legend_rule"]
    assert game.resolve_pending_choice("legend_rule", 0, permanent_id=second.permanent_id)
    assert game.is_on_battlefield(second) and not game.is_on_battlefield(first)


def test_w1g7_two_hokori_under_mirror_gallery_untap_two_lands(set_pool):
    """Hokori, Dust Drinker's 2005-02-01 ruling: "If there are two Hokori on
    the battlefield (for example, if Mirror Gallery is on the battlefield),
    each player untaps two lands they control at the beginning of their
    upkeep." Both legends stay under the Gallery, no land untaps in the untap
    step, and each Hokori's upkeep trigger untaps one."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(set_pool)
    _w1g7_put(game, bok["Mirror Gallery"])
    _w1g7_put(game, bok["Hokori, Dust Drinker"])
    _w1g7_put(game, bok["Hokori, Dust Drinker"])
    forests = [_w1g7_put(game, lea["Forest"]) for _ in range(3)]
    game.check_state_based_actions()
    _w1g7_settle(game)
    assert len(_w1g7_named(game, "Hokori, Dust Drinker")) == 2
    for forest in forests:
        forest.tapped = True
    game.resolve_cleanup_step(0)
    game.start_turn(1)
    _w1g7_settle(game)
    game.resolve_cleanup_step(1)
    game.start_turn(0)
    _w1g7_settle(game)
    assert sorted(forest.tapped for forest in forests) == [False, False, True]

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
