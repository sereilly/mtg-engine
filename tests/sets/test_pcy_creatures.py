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


def _w1g4_combat(game, step):
    """Put *game* in the named combat step; returns the step for the reader."""
    game.current_turn_phase, game.current_step = "combat", step
    return game.current_step


def test_w1g4_hollow_warrior_attacks_only_by_tapping_a_spare_creature(set_pool):
    """CR 508.1h: "tapping permanents" is a cost to attack. Alone, the Warrior
    cannot pay it and cannot attack; beside a creature that stays home, the
    declaration taps that creature — and a creature that is itself declared
    is "declared as an attacking creature" and cannot pay."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    warrior = _w1g4_put(game, 0, pcy["Hollow Warrior"])
    _w1g4_combat(game, "declare_attackers")
    assert not game.can_attack(warrior, 1)
    assert not game.declare_attackers(0, [0])[0]

    bear = _w1g4_put(game, 0, lea["Grizzly Bears"])
    assert game.can_attack(warrior, 1)
    ok, why = game.declare_attackers(0, [0, 1])
    assert not ok and "no untapped creature left to tap" in why
    assert not bear.tapped, "a refused declaration spends nothing"

    assert game.declare_attackers(0, [0])[0]
    assert warrior.tapped and bear.tapped
    assert game.combat_attackers == {0: 1}
    assert "W1G4-A tapped Grizzly Bears to attack" in game.log


def test_w1g4_two_hollow_warriors_need_two_spare_creatures(set_pool):
    """The cost is per Warrior and paid out of one board, so two Warriors
    beside one spare creature can each attack alone but not together — and a
    Warrior that stays home may be the creature the other one taps."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    first = _w1g4_put(game, 0, pcy["Hollow Warrior"])
    second = _w1g4_put(game, 0, pcy["Hollow Warrior"])
    spare = _w1g4_put(game, 0, lea["Grizzly Bears"])
    _w1g4_combat(game, "declare_attackers")
    assert game.attack_declaration_refusal([first, second]) is not None
    assert game.attack_declaration_refusal([first]) is None

    assert game.declare_attackers(0, [0])[0]
    assert first.tapped and (second.tapped or spare.tapped)
    assert not (second.tapped and spare.tapped), "one creature pays one cost"


def test_w1g4_hollow_warrior_blocks_only_by_tapping_a_creature_that_is_not(set_pool):
    """CR 509.1d's side of the same sentence: the defender taps a creature that
    is not blocking. Alone it cannot block; with a spare it blocks and the spare
    is tapped; declaring the spare as a blocker too leaves nothing to pay."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    attacker = _w1g4_put(game, 0, lea["Grizzly Bears"])
    warrior = _w1g4_put(game, 1, pcy["Hollow Warrior"])
    _w1g4_combat(game, "declare_attackers")
    assert game.declare_attackers(0, [0])[0]
    _w1g4_combat(game, "declare_blockers")
    assert not game._can_block_attacker(warrior, attacker)
    assert not game.declare_blockers(1, {0: 0})[0]

    spare = _w1g4_put(game, 1, lea["Scathe Zombies"])
    assert game._can_block_attacker(warrior, attacker)
    ok, why = game.declare_blockers(1, {0: 0, 1: 0})
    assert not ok and "no untapped creature left to tap" in why
    assert game.declare_blockers(1, {0: 0})[0]
    assert spare.tapped and not warrior.tapped
    assert "W1G4-B tapped Scathe Zombies to block" in game.log


def test_w1g4_lure_does_not_compel_a_hollow_warrior_to_pay(set_pool):
    """CR 509.1c's last clause: a player is not required to pay a cost to
    block, even to obey a requirement. Under Lure the defender may keep the
    Warrior home rather than tap a creature for it."""
    from engine.auras import attach_aura

    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_duel()
    lured = _w1g4_put(game, 0, lea["Grizzly Bears"])
    attach_aura(_w1g4_put(game, 0, lea["Lure"]), lured)
    warrior = _w1g4_put(game, 1, pcy["Hollow Warrior"])
    # Ironclaw Orcs can't block a 2-power attacker, so Lure does not reach it —
    # and it is untapped, so the Warrior *could* pay. CR 509.1c still excuses it.
    orcs = _w1g4_put(game, 1, lea["Ironclaw Orcs"])
    _w1g4_combat(game, "declare_attackers")
    assert game.declare_attackers(0, [0])[0]
    _w1g4_combat(game, "declare_blockers")
    assert game._can_block_attacker(warrior, lured)
    assert game.declare_blockers(1, {})[0]
    assert not orcs.tapped
