"""Champions of Kamigawa instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
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
#
# "Counter target Spirit or Arcane spell." (Hisoka's Defiance) — a subtype
# union with the head noun "spell", read into the ``any_classes`` the
# counter, its picker and the stack enumeration test.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.legality import cast_spec_of as _w1g4_cast_spec
from engine.models import PlayerState as _W1G4PlayerState
from tests.helpers import settle as _w1g4_settle


def _w1g4_table(set_pool, *, hand=(), opponent_hand=()):
    lea = set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(1)
    _w1g4_settle(game)
    return game


@_w1g4_pytest.mark.parametrize("code, name", [
    ("CHK", "Reach Through Mists"),    # Instant — Arcane
    ("CHK", "Kami of the Hunt"),       # Creature — Spirit
])
def test_w1g4_hisokas_defiance_counters_a_spirit_or_arcane_spell(set_pool, code, name):
    """Bob casts it on his turn; Alice counters it, and it goes to his
    graveyard without resolving (no card drawn, no Kami on the battlefield)."""
    chk = set_pool("CHK")
    game = _w1g4_table(
        set_pool, hand=[chk["Hisoka's Defiance"]], opponent_hand=[set_pool(code)[name]],
    )
    assert game.queue_from_hand(1, name).supported
    hand_before = len(game.players[1].hand)
    assert game.queue_from_hand(0, "Hisoka's Defiance", target_stack_index=0).supported
    _w1g4_settle(game)
    assert name in [card.name for card in game.players[1].graveyard], game.log
    assert not list(game.controlled_by(1))
    assert len(game.players[1].hand) == hand_before


def test_w1g4_hisokas_defiance_offers_only_spirit_and_arcane_spells(set_pool):
    """The picker over a stack of an Arcane instant, a Spirit creature spell
    and a Grizzly Bears spell names the first two and never the Bears — and a
    cast aimed at the Bears is refused."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_table(
        set_pool, hand=[chk["Hisoka's Defiance"]],
        opponent_hand=[chk["Reach Through Mists"], chk["Kami of the Hunt"],
                       lea["Grizzly Bears"]],
    )
    for name in ("Reach Through Mists", "Kami of the Hunt", "Grizzly Bears"):
        assert game.queue_from_hand(1, name).supported
    defiance = chk["Hisoka's Defiance"]
    offered = game._enumerate_targets(0, defiance, _w1g4_cast_spec(defiance), for_cast=True)
    assert sorted(o["name"] for o in offered) == ["Kami of the Hunt", "Reach Through Mists"]
    # ``target_stack_index`` indexes the stack bottom-first: 2 is the Bears.
    assert not game.queue_from_hand(0, "Hisoka's Defiance", target_stack_index=2).supported
    assert [item.card.name for item in game.stack][-1] == "Grizzly Bears"


# "You may change any targets of target Arcane spell." (Sideswipe, CR 115.7c.)


def _w1g4_put(game, seat, card):
    from engine.models import Permanent

    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g4_glacial_ray_at_alice(set_pool, *, interactive):
    """Bob's turn: Bob's Glacial Ray (Instant — Arcane, 2 damage to any
    target) aimed at Alice's Grizzly Bears, Sideswipe in Alice's hand."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_table(
        set_pool, hand=[chk["Sideswipe"]], opponent_hand=[chk["Glacial Ray"]],
    )
    game.interactive_seats = {0} if interactive else set()
    mine = _w1g4_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g4_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        1, "Glacial Ray", target_permanent_ids=[mine.permanent_id],
    ).supported
    return game, mine, theirs


def _w1g4_retarget_to(permanent):
    def answer(game, choice):
        options = choice.data["options"]
        index = next(
            i for i, option in enumerate(options)
            if option.get("permanent_id") == permanent.permanent_id
        )
        assert game.confirm_retarget_choice(choice.player_index, index)
    return answer


def _w1g4_keep(game, choice):
    assert choice.data["options"][0]["kind"] == "keep"
    assert game.confirm_retarget_choice(choice.player_index, 0)


@_w1g4_pytest.mark.parametrize("moved", [True, False])
def test_w1g4_sideswipe_changes_an_arcane_spells_target_or_keeps_it(set_pool, moved):
    """Alice re-aims the Ray at Bob's Bears, or keeps its target: the prompt
    offers "keep" first (CR 115.7c: any number of targets, none included)."""
    game, mine, theirs = _w1g4_glacial_ray_at_alice(set_pool, interactive=True)
    assert game.queue_from_hand(0, "Sideswipe", target_stack_index=0).supported
    _w1g4_settle(game, answers={
        "retarget_choice": _w1g4_retarget_to(theirs) if moved else _w1g4_keep,
    })
    assert game.is_on_battlefield(mine) is moved, game.log
    assert game.is_on_battlefield(theirs) is (not moved)


def test_w1g4_sideswipe_from_a_seat_nobody_asks_moves_the_ray_off_its_own_bears(set_pool):
    """A seat nobody asks takes the measured answer: the Ray no longer kills
    Alice's own Bears."""
    game, mine, _theirs = _w1g4_glacial_ray_at_alice(set_pool, interactive=False)
    assert game.queue_from_hand(0, "Sideswipe", target_stack_index=0).supported
    _w1g4_settle(game)
    assert game.is_on_battlefield(mine), game.log
    assert any("changed Glacial Ray's target" in line for line in game.log)


def test_w1g4_sideswipe_moves_any_number_of_several_targets(set_pool):
    """Unearthly Blizzard ("Up to three target creatures can't block this
    turn", Arcane) aimed at Alice's Bears and Hill Giant: Alice moves the
    first onto her Serra Angel and keeps the second (CR 115.7c), and the
    second slot is not offered the Angel the first now names (CR 115.3)."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_table(
        set_pool, hand=[chk["Sideswipe"]], opponent_hand=[chk["Unearthly Blizzard"]],
    )
    game.interactive_seats = {0}
    bears, giant, angel = (
        _w1g4_put(game, 0, lea[name]) for name in ("Grizzly Bears", "Hill Giant", "Serra Angel")
    )
    attacker = _w1g4_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        1, "Unearthly Blizzard", target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    ).supported
    assert game.queue_from_hand(0, "Sideswipe", target_stack_index=0).supported
    first = _w1g4_settle(game, defaults=False)
    assert first.kind == "retarget_choice"
    _w1g4_retarget_to(angel)(game, first)
    second = _w1g4_settle(game, defaults=False)
    assert angel.permanent_id not in [o.get("permanent_id") for o in second.data["options"]]
    _w1g4_keep(game, second)
    _w1g4_settle(game)
    assert game._can_block_attacker(bears, attacker), game.log
    assert not game._can_block_attacker(giant, attacker)
    assert not game._can_block_attacker(angel, attacker)


def test_w1g4_sideswipe_targets_only_an_arcane_spell(set_pool):
    """Giant Growth is an instant but not Arcane: Sideswipe has nothing to
    target and the cast is refused."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_table(
        set_pool, hand=[chk["Sideswipe"]], opponent_hand=[lea["Giant Growth"]],
    )
    theirs = _w1g4_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        1, "Giant Growth", target_permanent_ids=[theirs.permanent_id],
    ).supported
    sideswipe = chk["Sideswipe"]
    assert not game._enumerate_targets(0, sideswipe, _w1g4_cast_spec(sideswipe), for_cast=True)
    assert not game.queue_from_hand(0, "Sideswipe", target_stack_index=0).supported

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================
