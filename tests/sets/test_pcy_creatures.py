"""Prophecy creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: untapped lands and untap steps ---
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_duel():
    """Two seats, seat 0 active, mana costs off — ends on its own game name."""
    w1g4_game = _W1G4Game(
        players=[_W1G4PlayerState(name="W1G4-A"), _W1G4PlayerState(name="W1G4-B")]
    )
    w1g4_game.enforce_mana_costs = False
    w1g4_game.active_player_index = 0
    return w1g4_game


def _w1g4_put(game, seat, card, *, tapped=False):
    """*card* onto *seat*'s battlefield through the real entry, able to attack.

    The sickness stamp is written *after* the entry, which rewrites it.
    """
    w1g4_perm = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, w1g4_perm, None)
    w1g4_perm.metadata["summoning_sickness_turn"] = -99
    w1g4_perm.tapped = tapped
    return w1g4_perm


def _w1g4_tap_out(game, seat, lands):
    """Tap each of *lands* for mana as *seat* would, then let SBAs run."""
    for w1g4_land in lands:
        assert game.tap_land_for_mana(
            seat, w1g4_land.card.name, "R", permanent_id=w1g4_land.permanent_id
        )
    game.check_state_based_actions()
    return [w1g4_land.tapped for w1g4_land in lands]


@_w1g4_pytest.mark.parametrize(
    "name, printed, bonus",
    [("Scoria Cat", (3, 3), (3, 3)), ("Spur Grappler", (2, 1), (2, 1))],
)
def test_w1g4_the_bonus_holds_only_while_you_control_no_untapped_lands(
    set_pool, name, printed, bonus
):
    """"…gets +N/+N as long as you control **no** untapped lands." The "no" is a
    count of zero, not a presence test — read as presence the clause is its own
    negation, which is why the table refused it until it carried a count. The
    opponent's untapped land is not "you control", and untapping one of your
    own switches the bonus off at the next state-based check (CR 611.3a)."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    body = _w1g4_put(game, 0, pcy[name])
    lands = [_w1g4_put(game, 0, lea["Mountain"]) for _ in range(2)]
    _w1g4_put(game, 1, lea["Forest"])
    game.check_state_based_actions()
    assert (body.effective_power, body.effective_toughness) == printed

    assert _w1g4_tap_out(game, 0, lands) == [True, True]
    assert (body.effective_power, body.effective_toughness) == (
        printed[0] + bonus[0], printed[1] + bonus[1]
    )

    game.become_untapped(lands[0])
    game.check_state_based_actions()
    assert (body.effective_power, body.effective_toughness) == printed


def test_w1g4_fen_stalker_has_fear_only_once_its_lands_are_tapped(set_pool):
    """Fear (CR 702.36) granted by the same condition: with a Swamp untapped a
    green creature may block the Stalker; tapped out, only a black one may."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    stalker = _w1g4_put(game, 0, pcy["Fen Stalker"])
    swamp = _w1g4_put(game, 0, lea["Swamp"])
    bear = _w1g4_put(game, 1, lea["Grizzly Bears"])
    zombies = _w1g4_put(game, 1, lea["Scathe Zombies"])
    game.check_state_based_actions()
    assert not game._has_keyword(stalker, "fear")
    assert game._can_block_attacker(bear, stalker)

    _w1g4_tap_out(game, 0, [swamp])
    assert game._has_keyword(stalker, "fear")
    assert not game._can_block_attacker(bear, stalker)
    assert game._can_block_attacker(zombies, stalker)


def test_w1g4_vintara_snapper_is_untargetable_only_while_tapped_out(set_pool):
    """Shroud (CR 702.18) by the same condition, asked where it matters: the
    Bolt is refused at announcement while the Forest is tapped and kills the
    Turtle once its controller leaves a land up."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    snapper = _w1g4_put(game, 1, pcy["Vintara Snapper"])
    forest = _w1g4_put(game, 1, lea["Forest"], tapped=True)
    game.check_state_based_actions()
    game.players[0].hand.append(lea["Lightning Bolt"])
    refused = game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=1,
        target_permanent_ids=[snapper.permanent_id],
    )
    assert not refused.supported
    assert game.is_on_battlefield(snapper)
    assert "Vintara Snapper is an illegal target for Lightning Bolt" in game.log

    game.become_untapped(forest)
    game.check_state_based_actions()
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=1,
        target_permanent_ids=[snapper.permanent_id],
    ).supported
    _w1g4_resolve(game)
    assert not game.is_on_battlefield(snapper)


@_w1g4_pytest.mark.parametrize("name", ["Branded Brawlers", "Veteran Brawlers"])
def test_w1g4_brawlers_attack_into_a_tapped_out_defender(set_pool, name):
    """"Can't attack if defending player controls an untapped land." Asked at
    the real declaration: refused while the defender's Forest is up, allowed
    once it is tapped."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    brawlers = _w1g4_put(game, 0, pcy[name])
    forest = _w1g4_put(game, 1, lea["Forest"])
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"

    ok, why = game.declare_attackers(0, [0])
    assert not ok and "cannot attack" in why
    forest.tapped = True
    assert game.declare_attackers(0, [0])[0]
    assert brawlers.tapped and game.combat_attackers == {0: 1}


@_w1g4_pytest.mark.parametrize("name", ["Branded Brawlers", "Veteran Brawlers"])
def test_w1g4_brawlers_block_only_with_your_own_lands_tapped(set_pool, name):
    """"Can't block if **you** control an untapped land" — the blocker's own
    controller's board, re-asked at the declaration (CR 509.1b). The attacker's
    untapped land is not the question."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    _w1g4_put(game, 0, lea["Grizzly Bears"])
    _w1g4_put(game, 0, lea["Mountain"])
    _w1g4_put(game, 1, pcy[name])
    mountain = _w1g4_put(game, 1, lea["Mountain"])
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.current_step = "declare_blockers"

    ok, _why = game.declare_blockers(1, {0: 0})
    assert not ok
    mountain.tapped = True
    assert game.declare_blockers(1, {0: 0})[0]


def test_w1g4_mungha_wurm_caps_only_its_controllers_untap_step(set_pool):
    """"**You** can't untap more than one land during **your** untap step." Winter
    Orb's cap narrowed to one seat (CR 109.5): the Wurm's controller untaps one
    land and the opponent untaps all three."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    _w1g4_put(game, 0, pcy["Mungha Wurm"])
    mine = [_w1g4_put(game, 0, lea["Forest"], tapped=True) for _ in range(3)]
    theirs = [_w1g4_put(game, 1, lea["Island"], tapped=True) for _ in range(3)]

    assert game.get_untap_land_selection_options(0)["max_count"] == 1
    assert game.get_untap_land_selection_options(1) is None
    game.resolve_untap_step(0)
    assert sorted(land.tapped for land in mine) == [False, True, True]

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert [land.tapped for land in theirs] == [False, False, False]
