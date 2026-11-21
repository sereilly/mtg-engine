"""Betrayers of Kamigawa enchantments, Auras included.

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


def _w1g7_named(game, name, seat=None):
    return [
        perm for perm in game.all_permanents()
        if perm.card.name == name
        and (seat is None or game.controller_index_of(perm) == seat)
    ]


def test_w1g7_in_the_web_of_war_gives_an_entering_creature_haste_it_attacks_with(set_pool):
    """Whenever a creature you control enters, it gets +2/+0 and gains haste
    until end of turn. "It" is the entering creature (the id the entry froze),
    not the enchantment: a Grizzly Bears cast under it is a 4/2 with haste and
    is declared as an attacker the turn it arrived. An opponent's creature is
    not "a creature you control", and the bonus ends in the cleanup step."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(set_pool, hand=[bok["In the Web of War"], lea["Grizzly Bears"]])
    assert game.cast_from_hand(0, "In the Web of War").supported
    _w1g7_settle(game)
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g7_settle(game)
    (bears,) = _w1g7_named(game, "Grizzly Bears", seat=0)
    assert (bears.effective_power, bears.effective_toughness) == (4, 2)
    assert game._has_keyword(bears, "haste")
    assert "Grizzly Bears gains haste until end of turn (In the Web of War)" in game.log
    # The opponent's creature entering triggers nothing.
    _w1g7_put(game, lea["Grizzly Bears"], seat=1)
    _w1g7_settle(game)
    (theirs,) = _w1g7_named(game, "Grizzly Bears", seat=1)
    assert theirs.effective_power == 2 and not game._has_keyword(theirs, "haste")
    # Haste is what lets the summoning-sick Bears attack this turn.
    game._set_phase_and_step("combat", "declare_attackers")
    slot = game.battlefield_index_of(bears)
    ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
    assert ok, why
    game.resolve_cleanup_step(0)
    assert bears.effective_power == 2 and not game._has_keyword(bears, "haste")


def test_w1g7_clash_of_realities_gives_entering_creatures_their_entry_trigger(set_pool):
    """All Spirits have "When this permanent enters, you may have it deal 3
    damage to target non-Spirit creature." / Non-Spirit creatures have "…to
    target Spirit creature." The ability exists as the creature enters (the
    card's 2005-02-01 ruling: "Clash of Realities's abilities apply as each
    creature enters and gives them an 'enters' ability"), so a Spirit cast
    under it shoots a non-Spirit and a non-Spirit shoots a Spirit — and the
    damage is the entering creature's, not the enchantment's (it says "have
    it deal")."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g7_table(set_pool, hand=[chk["Kami of the Hunt"], lea["Grizzly Bears"]])
    _w1g7_put(game, bok["Clash of Realities"])
    their_bears = _w1g7_put(game, lea["Grizzly Bears"], seat=1)
    assert game.cast_from_hand(0, "Kami of the Hunt").supported
    _w1g7_settle(game)
    assert "Kami of the Hunt dealt 3 damage to Grizzly Bears" in game.log
    assert not game.is_on_battlefield(their_bears)
    (my_kami,) = _w1g7_named(game, "Kami of the Hunt", seat=0)
    their_kami = _w1g7_put(game, chk["Kami of the Hunt"], seat=1)
    _w1g7_settle(game)
    # The opponent's Spirit entered too; its only non-Spirit target would be
    # nothing at all (mine is a Spirit), so its trigger had no legal target.
    assert game.is_on_battlefield(my_kami)
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g7_settle(game)
    assert not game.is_on_battlefield(their_kami)
    assert "Grizzly Bears dealt 3 damage to Kami of the Hunt" in game.log


def test_w1g7_clash_of_realities_asks_a_person_for_the_target_and_the_may(set_pool):
    """At a seat a person sits at the granted trigger asks its target as it
    goes on the stack (CR 603.3d) and the "you may" as it resolves; the answers
    are what happens — the second of two Bears is the one shot, and declining
    the may shoots nothing."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g7_table(
        set_pool, hand=[chk["Kami of the Hunt"], chk["Kami of the Hunt"]], interactive=(0,),
    )
    _w1g7_put(game, bok["Clash of Realities"])
    first = _w1g7_put(game, lea["Grizzly Bears"], seat=1)
    second = _w1g7_put(game, lea["Grizzly Bears"], seat=1)
    asked = []

    def pick_second(game, choice):
        asked.append(choice.kind)
        offered = [t["permanent_id"] for t in choice.data["targets"]]
        assert offered == [first.permanent_id, second.permanent_id]
        assert game.resolve_pending_choice(choice.kind, 0, permanent_id=second.permanent_id)

    def accept(game, choice):
        asked.append(choice.kind)
        assert game.resolve_pending_choice(choice.kind, 0, accept=True, option=None)

    assert game.cast_from_hand(0, "Kami of the Hunt").supported
    _w1g7_settle(game, answers={"trigger_target": pick_second, "optional_pay": accept})
    assert asked == ["trigger_target", "optional_pay"]
    assert game.is_on_battlefield(first) and not game.is_on_battlefield(second)

    def decline(game, choice):
        assert game.resolve_pending_choice(choice.kind, 0, accept=False, option=None)

    assert game.cast_from_hand(0, "Kami of the Hunt").supported
    _w1g7_settle(game, answers={"optional_pay": decline})
    assert game.is_on_battlefield(first) and first.damage_marked == 0


def test_w1g7_clash_of_realities_a_seat_nobody_asks_declines_to_shoot_its_own(set_pool):
    """The target is mandatory while one exists (CR 603.3d), so a seat whose
    only non-Spirit creature is its own names it — and the "may" is the
    card's answer to that board: a seat nobody asks declines rather than have
    its new Spirit shoot its own Bears."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g7_table(set_pool, hand=[chk["Kami of the Hunt"]])
    _w1g7_put(game, bok["Clash of Realities"])
    bears = _w1g7_put(game, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Kami of the Hunt").supported
    _w1g7_settle(game)
    assert game.is_on_battlefield(bears) and bears.damage_marked == 0
    assert "P0 declined Kami of the Hunt (it would harm their own permanent)" in game.log

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
