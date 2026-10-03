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

# --- W1G3: activation costs ---
# The five spellshapers ("<mana>, {T}, Discard two cards: …"), and the costs
# paid with permanents: Copper-Leaf Angel's "Sacrifice X lands", Jeweled
# Spirit's "Sacrifice two lands", Keldon Battlewagon's "Tap an untapped creature
# you control" read back as "the power of the creature tapped this way".

import random as _w1g3_random

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec

from tests.helpers import resolve_stack


def _w1g3_game(mine, theirs=(), *, hand=(), their_hand=(), interactive=()):
    """Seat 0 holds *mine* and *hand*, seat 1 *theirs* and *their_hand*; turn 0
    begun, mana not enforced, nothing summoning sick. Returns the game and the
    two permanent lists in the order given."""
    me = [Permanent(card=card) for card in mine]
    them = [Permanent(card=card) for card in theirs]
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(me), hand=list(hand)),
        PlayerState(name="P1", battlefield=list(them), hand=list(their_hand)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in (*me, *them):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, me, them


def _w1g3_spec(set_pool, name):
    """The activation picker spec of *name*'s first ability."""
    (ability,) = compile_card_oracle(set_pool("PCY")[name]).activated_abilities
    return derive_activation_spec(ability)


def test_w1g3_latulla_discards_two_identical_cards_and_deals_x(set_pool):
    """"{X}{R}, {T}, Discard two cards: Latulla deals X damage to any target."

    Two copies of one card in a hand are one ``CardDefinition`` object, so the
    payment is collected by position: the second Bears is a second card, not
    the first one seen twice.
    """
    lea = set_pool("LEA")
    bears = lea["Grizzly Bears"]
    game, (latulla,), _ = _w1g3_game(
        [set_pool("PCY")["Latulla, Keldon Overseer"]], hand=[bears, bears],
    )
    result = game.queue_permanent_ability(
        0, "Latulla, Keldon Overseer", target_player_index=1, x_value=3,
    )
    assert result.supported, result.details
    resolve_stack(game)

    p0, p1 = game.players
    assert p0.hand == [] and [c.name for c in p0.graveyard] == ["Grizzly Bears"] * 2
    assert latulla.tapped
    assert p1.life == 17


def test_w1g3_latulla_with_one_card_is_refused_before_anything_is_paid(set_pool):
    """CR 601.2h via 602.2b: one card is no payment of a two-card cost, and the
    refusal comes before the {T}, the mana or the one card is spent."""
    lea = set_pool("LEA")
    game, (latulla,), _ = _w1g3_game(
        [set_pool("PCY")["Latulla, Keldon Overseer"]], hand=[lea["Grizzly Bears"]],
    )
    result = game.queue_permanent_ability(
        0, "Latulla, Keldon Overseer", target_player_index=1, x_value=3,
    )
    assert not result.supported
    assert "not enough cards" in result.details
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert not latulla.tapped and game.players[1].life == 20


def test_w1g3_greel_makes_target_player_discard_x_at_random(set_pool):
    """"{X}{B}, {T}, Discard two cards: Target player discards X cards at
    random." The payer's named card is honoured, the second is the next one in
    hand, and the target loses exactly X."""
    lea = set_pool("LEA")
    bears, bolt = lea["Grizzly Bears"], lea["Lightning Bolt"]
    _w1g3_random.seed(4)
    game, _, _ = _w1g3_game(
        [set_pool("PCY")["Greel, Mind Raker"]],
        hand=[bears, bolt, lea["Hill Giant"]], their_hand=[bolt, bolt, bears],
    )
    result = game.queue_permanent_ability(
        0, "Greel, Mind Raker", target_player_index=1, x_value=2, cost_hand_index=1,
    )
    assert result.supported, result.details
    resolve_stack(game)

    p0, p1 = game.players
    assert [c.name for c in p0.graveyard] == ["Lightning Bolt", "Grizzly Bears"]
    assert [c.name for c in p0.hand] == ["Hill Giant"]
    assert len(p1.hand) == 1 and len(p1.graveyard) == 2
    assert "P1 discarded 2 cards at random" in game.log


def test_w1g3_alexi_returns_x_targets_from_both_battlefields(set_pool):
    """"Return X target creatures to their owners' hands." The picker asks for
    X and then that many creatures, and each goes to its own owner's hand."""
    lea = set_pool("LEA")
    spec = _w1g3_spec(set_pool, "Alexi, Zephyr Mage")
    assert spec["kind"] == "creature" and spec["x_targets"]
    assert spec["cost_spec"]["discard_cost"] and spec["cost_spec"]["count"] == 2

    game, (_, giant), (angel,) = _w1g3_game(
        [set_pool("PCY")["Alexi, Zephyr Mage"], lea["Hill Giant"]],
        [lea["Serra Angel"]], hand=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    result = game.queue_permanent_ability(
        0, "Alexi, Zephyr Mage", x_value=2,
        target_permanent_ids=[giant.permanent_id, angel.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)

    p0, p1 = game.players
    assert [c.name for c in p0.hand] == ["Hill Giant"]
    assert [c.name for c in p1.hand] == ["Serra Angel"]
    assert [p.card.name for p in p0.battlefield] == ["Alexi, Zephyr Mage"]


def test_w1g3_alexi_cannot_name_more_targets_than_its_x(set_pool):
    """CR 601.2c fixes the number of targets from the X announced at 601.2b.
    The handler returns every slot it is handed, so the count is enforced at
    the announcement — with nothing paid."""
    lea = set_pool("LEA")
    game, (alexi,), theirs = _w1g3_game(
        [set_pool("PCY")["Alexi, Zephyr Mage"]],
        [lea["Grizzly Bears"], lea["Hill Giant"]],
        hand=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    result = game.queue_permanent_ability(
        0, "Alexi, Zephyr Mage", target_player_index=1, x_value=1,
        target_permanent_ids=[perm.permanent_id for perm in theirs],
    )
    assert not result.supported and "too many targets" in result.details
    assert len(game.players[0].hand) == 2 and not alexi.tapped
    assert len(game.players[1].battlefield) == 2


def test_w1g3_jolrael_animates_only_the_target_players_lands(set_pool):
    """"All lands target player controls become 3/3 creatures until end of
    turn. They're still lands." The seat is announced (the picker asks for a
    player), the sweep reads it, and cleanup ends it."""
    lea = set_pool("LEA")
    forest = lea["Forest"]
    spec = _w1g3_spec(set_pool, "Jolrael, Empress of Beasts")
    assert spec["kind"] == "player"

    game, (_, my_forest), (f1, f2, bears) = _w1g3_game(
        [set_pool("PCY")["Jolrael, Empress of Beasts"], forest],
        [forest, forest, lea["Grizzly Bears"]],
        hand=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    result = game.queue_permanent_ability(
        0, "Jolrael, Empress of Beasts", target_player_index=1,
    )
    assert result.supported, result.details
    resolve_stack(game)

    for land in (f1, f2):
        assert land.is_creature and land.has_type("land")
        assert (land.effective_power, land.effective_toughness) == (3, 3)
    assert not my_forest.is_creature, "the activator's own land is not swept"
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

    game.resolve_cleanup_step(0)
    assert not f1.is_creature and f1.has_type("land")


def test_w1g3_mageta_destroys_every_other_creature_through_regeneration(set_pool):
    """"Destroy all creatures except for Mageta. Those creatures can't be
    regenerated." The exemption is the source itself, and a regeneration
    shield already up does not save a Drudge Skeletons."""
    lea = set_pool("LEA")
    game, (mageta, bears), (skeletons, giant) = _w1g3_game(
        [set_pool("PCY")["Mageta the Lion"], lea["Grizzly Bears"]],
        [lea["Drudge Skeletons"], lea["Hill Giant"]],
        hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
    )
    shield = game.queue_permanent_ability(1, "Drudge Skeletons")
    assert shield.supported, shield.details
    resolve_stack(game)

    result = game.queue_permanent_ability(0, "Mageta the Lion")
    assert result.supported, result.details
    resolve_stack(game)

    assert [p.card.name for p in game.players[0].battlefield] == ["Mageta the Lion"]
    assert game.players[1].battlefield == []
    assert {c.name for c in game.players[1].graveyard} == {
        "Drudge Skeletons", "Hill Giant",
    }


def test_w1g3_copper_leaf_angel_sacrifices_x_lands_for_x_counters(set_pool):
    """"{T}, Sacrifice X lands: Put X +1/+1 counters on this creature." The X
    announced is both the payment and the effect; a named land is honoured."""
    spec = _w1g3_spec(set_pool, "Copper-Leaf Angel")
    assert spec["sacrifice_cost"] and spec["kind"] == "land" and spec["announces_x"]
    forest = set_pool("LEA")["Forest"]
    game, (angel, f1, f2, f3), _ = _w1g3_game(
        [set_pool("PCY")["Copper-Leaf Angel"], forest, forest, forest],
    )
    result = game.queue_permanent_ability(
        0, "Copper-Leaf Angel", x_value=2, cost_permanent_ids=[f3.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert not game.is_on_battlefield(f3), "the named land paid"
    assert sum(game.is_on_battlefield(land) for land in (f1, f2)) == 1
    assert [c.name for c in game.players[0].graveyard] == ["Forest", "Forest"]
    assert (angel.effective_power, angel.effective_toughness) == (4, 4)
    assert angel.tapped


def test_w1g3_copper_leaf_angel_refuses_an_x_the_board_cannot_pay(set_pool):
    """An X larger than the lands there are is an announcement that cannot be
    paid (CR 601.2h) — refused, never clamped, and nothing is spent."""
    forest = set_pool("LEA")["Forest"]
    game, (angel, *_lands), _ = _w1g3_game(
        [set_pool("PCY")["Copper-Leaf Angel"], forest, forest],
    )
    result = game.queue_permanent_ability(0, "Copper-Leaf Angel", x_value=3)
    assert not result.supported and "fewer than the 3 announced" in result.details
    assert len(game.players[0].battlefield) == 3 and not angel.tapped


def test_w1g3_jeweled_spirit_gains_protection_from_artifacts_or_a_colour(set_pool):
    """"Sacrifice two lands: This creature gains protection from artifacts or
    from the color of your choice until end of turn." Two protection abilities,
    one chosen; the colour rides the activation like Knight of Dawn's."""
    lea = set_pool("LEA")
    lands = [lea["Forest"], lea["Mountain"], lea["Forest"]]

    game, (spirit, *_), _ = _w1g3_game([set_pool("PCY")["Jeweled Spirit"], *lands])
    result = game.queue_permanent_ability(0, "Jeweled Spirit")
    assert result.supported, result.details
    resolve_stack(game)
    assert game._protection_qualities(spirit) == {("card_type", "artifact")}
    assert len(game.players[0].battlefield) == 2, "two lands paid"

    game, (spirit, *_), _ = _w1g3_game(
        [set_pool("PCY")["Jeweled Spirit"], *lands], interactive={0},
    )
    result = game.queue_permanent_ability(0, "Jeweled Spirit", mana_color="R")
    assert result.supported, result.details
    # "…artifacts **or** from the color…" is not modal (CR 700.2), so the
    # alternative is asked at resolution (CR 608.2d), not at activation.
    assert game.pending_choice_of("mode_choice", 0) is None
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    resolve_stack(game)
    assert game._protection_qualities(spirit) == {("color", "R")}

    game.resolve_cleanup_step(0)
    assert game._protection_qualities(spirit) == set()


def test_w1g3_jeweled_spirit_with_one_land_is_refused(set_pool):
    lea = set_pool("LEA")
    game, (spirit, forest), _ = _w1g3_game(
        [set_pool("PCY")["Jeweled Spirit"], lea["Forest"]],
    )
    result = game.queue_permanent_ability(0, "Jeweled Spirit")
    assert not result.supported
    assert game.is_on_battlefield(forest)
    assert game._protection_qualities(spirit) == set()


def test_w1g3_keldon_battlewagon_gets_the_tapped_creatures_power(set_pool):
    """"Tap an untapped creature you control: This creature gets +X/+0 until
    end of turn, where X is the power of the creature tapped this way." The
    record of what the cost tapped, read at resolution."""
    lea = set_pool("LEA")
    game, (wagon, giant, bears), _ = _w1g3_game(
        [set_pool("PCY")["Keldon Battlewagon"], lea["Hill Giant"], lea["Grizzly Bears"]],
    )
    result = game.queue_permanent_ability(
        0, "Keldon Battlewagon", cost_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert giant.tapped and not bears.tapped
    assert (wagon.effective_power, wagon.effective_toughness) == (3, 3)

    result = game.queue_permanent_ability(
        0, "Keldon Battlewagon", cost_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert (wagon.effective_power, wagon.effective_toughness) == (5, 3)

    game.resolve_cleanup_step(0)
    assert wagon.effective_power == 0


def test_w1g3_keldon_battlewagon_cannot_block(set_pool):
    lea = set_pool("LEA")
    game, (bears,), (wagon,) = _w1g3_game(
        [lea["Grizzly Bears"]], [set_pool("PCY")["Keldon Battlewagon"]],
    )
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert not game._can_block_attacker(wagon, bears)
    assert not game.declare_blockers(1, {0: 0})[0]


def test_w1g3_keldon_battlewagon_is_sacrificed_at_end_of_combat(set_pool):
    """"When this creature attacks, sacrifice it at end of combat." — a
    delayed trigger the attack arms, which fires at the end of combat step."""
    game, (wagon,), _ = _w1g3_game([set_pool("PCY")["Keldon Battlewagon"]])
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    resolve_stack(game)
    present_through: list[str] = []
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        if game.is_on_battlefield(wagon):
            present_through.append(game.current_step)
        game.advance_combat_phase()
        resolve_stack(game)
    assert "end_of_combat" in present_through, present_through
    assert game.players[1].life == 20, "a 0-power attacker deals nothing"
    assert not game.is_on_battlefield(wagon)
    assert [c.name for c in game.players[0].graveyard] == ["Keldon Battlewagon"]

# --- W1G2: spell costs ---
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack

#: The five Avatars, each with the colour of its two printed pips, a board on
#: which its fronted condition holds, and the nearest board on which it does
#: not. The near misses are the point: six lands, 4 life, a lead of three, one
#: card in hand, nine creature cards — every one is the threshold minus one, so
#: a reading that is off by one passes the "met" half and fails here.
_W1G2_AVATARS = (
    ("Avatar of Fury", "R",
     {"theirs": ("Mountain",) * 7}, {"theirs": ("Mountain",) * 6}),
    ("Avatar of Hope", "W", {"life": 3}, {"life": 4}),
    ("Avatar of Might", "G",
     {"theirs": ("Grizzly Bears",) * 4},
     {"theirs": ("Grizzly Bears",) * 4, "mine": ("Grizzly Bears",)}),
    ("Avatar of Will", "U", {}, {"their_hand": ("Island",)}),
    ("Avatar of Woe", "B",
     {"my_grave": ("Grizzly Bears",) * 5, "their_grave": ("Grizzly Bears",) * 5},
     {"my_grave": ("Grizzly Bears",) * 5,
      "their_grave": ("Grizzly Bears",) * 4 + ("Island",)}),
)


def _w1g2_avatar_game(set_pool, avatar, *, life=20, mine=(), theirs=(),
                      their_hand=(), my_grave=(), their_grave=(), seats=2):
    """A duel (or a free-for-all of *seats*) with *avatar* in P1's hand, mana
    enforced and P1's pool empty — so a cast succeeds only if the reduction
    took off all six generic."""
    lea = set_pool("LEA")
    players = [
        _W1G2PlayerState(name="P1", life=life, hand=[set_pool("PCY")[avatar]]),
        _W1G2PlayerState(name="P2", hand=[lea[n] for n in their_hand]),
    ] + [_W1G2PlayerState(name=f"P{n}") for n in range(3, seats + 1)]
    players[0].graveyard.extend(lea[n] for n in my_grave)
    players[1].graveyard.extend(lea[n] for n in their_grave)
    game = _W1G2Game(players=players)
    for name in mine:
        game._put_permanent_onto_battlefield(0, _W1G2Permanent(card=lea[name]), None)
    for name in theirs:
        game._put_permanent_onto_battlefield(1, _W1G2Permanent(card=lea[name]), None)
    game.start_turn(0)
    game.enforce_mana_costs = True
    return game


@_w1g2_pytest.mark.parametrize(
    "avatar,color,met,unmet", _W1G2_AVATARS, ids=[a[0] for a in _W1G2_AVATARS]
)
def test_w1g2_avatar_costs_six_less_exactly_when_its_condition_holds(
    set_pool, avatar, color, met, unmet,
):
    """"If <condition>, this spell costs {6} less to cast." (CR 601.2f.)

    Driven through the real cast with two pips of the Avatar's colour in the
    pool and nothing else: met, the spell resolves and the pool is spent;
    unmet, the cast is refused for want of mana and nothing moves — the card is
    still in hand and the two pips are still in the pool. The condition is the
    grammar's own reading of the fronted clause, answered by the evaluator every
    intervening-if uses, so a wording the grammar cannot read refuses the line
    and the card stays unsupported rather than reading as unconditional.
    """
    program = _w1g2_compile(set_pool("PCY")[avatar])
    assert program.supported, program.reason

    game = _w1g2_avatar_game(set_pool, avatar, **met)
    game.players[0].mana_pool[color] = 2
    result = game.cast_from_hand(0, avatar)
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    assert any(p.card.name == avatar for p in game.players[0].battlefield), game.log
    assert game.players[0].mana_pool[color] == 0

    game = _w1g2_avatar_game(set_pool, avatar, **unmet)
    game.players[0].mana_pool[color] = 2
    result = game.cast_from_hand(0, avatar)
    assert not result.supported
    assert "insufficient mana" in result.details, result.details
    assert [c.name for c in game.players[0].hand] == [avatar]
    assert game.players[0].mana_pool[color] == 2


@_w1g2_pytest.mark.parametrize(
    "avatar,color,met,unmet", _W1G2_AVATARS, ids=[a[0] for a in _W1G2_AVATARS]
)
def test_w1g2_the_ai_prices_the_avatar_at_the_reduced_cost(
    set_pool, avatar, color, met, unmet,
):
    """The AI's affordability read asks the same ``cost_reduction_for_cast``
    the cast does — priced at {6}{X}{X} on a board where the card costs {X}{X},
    the AI would never propose the cast; priced cheap where it is not, it would
    propose a cast the rules refuse every turn."""
    from engine.ai_policy import _cost_for

    for board, generic in ((met, 0), (unmet, 6)):
        game = _w1g2_avatar_game(set_pool, avatar, **board)
        cost = _cost_for(game, game.players[0], set_pool("PCY")[avatar], None)
        assert cost.get("generic", 0) == generic, (board, cost)
        assert cost.get(color) == 2, cost


def test_w1g2_an_opponent_is_one_opponent_at_a_free_for_all_table(set_pool):
    """"If **an** opponent controls seven or more lands" is an existential over
    seats: one opponent must hold the count. Two opponents with four lands each
    hold eight between them and neither holds seven — pooled, the Avatar would
    be {6} cheaper on a board the card does not name.
    """
    from engine.cost_modifiers import cost_reduction_for_cast

    pcy = set_pool("PCY")
    game = _w1g2_avatar_game(set_pool, "Avatar of Fury", seats=3)
    for seat in (1, 2):
        for _ in range(4):
            game._put_permanent_onto_battlefield(
                seat, _W1G2Permanent(card=set_pool("LEA")["Mountain"]), None
            )
    assert cost_reduction_for_cast(game, 0, pcy["Avatar of Fury"])[0].generic == 0
    for _ in range(3):
        game._put_permanent_onto_battlefield(
            2, _W1G2Permanent(card=set_pool("LEA")["Mountain"]), None
        )
    assert cost_reduction_for_cast(game, 0, pcy["Avatar of Fury"])[0].generic == 6


def test_w1g2_avatar_of_will_asks_each_opponent_for_an_empty_hand(set_pool):
    """"If an opponent has no cards in hand" — the same existential, asked of
    hands. The word used to resolve to the evaluator's *target* seat, which a
    cast-time cost does not have; at a three-seat table one empty hand is
    enough and a hand-holding opponent beside it changes nothing."""
    from engine.cost_modifiers import cost_reduction_for_cast

    lea = set_pool("LEA")
    game = _w1g2_avatar_game(
        set_pool, "Avatar of Will", their_hand=("Island",), seats=3
    )
    will = set_pool("PCY")["Avatar of Will"]
    assert cost_reduction_for_cast(game, 0, will)[0].generic == 6, "P3 is empty"
    game.players[2].hand.append(lea["Island"])
    assert cost_reduction_for_cast(game, 0, will)[0].generic == 0
    game.players[1].hand.clear()
    assert cost_reduction_for_cast(game, 0, will)[0].generic == 6


def test_w1g2_avatar_of_might_needs_one_opponent_four_ahead(set_pool):
    """"…controls **at least four more** creatures than you." The margin is the
    printed number, read by the reader the seat comparison "at least two fewer"
    already uses, and it is a lead over *your* count: four Bears against your
    none qualifies, four against your one does not, and two opponents' Bears are
    never added together."""
    from engine.cost_modifiers import cost_reduction_for_cast

    bear = set_pool("LEA")["Grizzly Bears"]
    might = set_pool("PCY")["Avatar of Might"]
    game = _w1g2_avatar_game(set_pool, "Avatar of Might", seats=3)
    for seat, count in ((1, 3), (2, 3)):
        for _ in range(count):
            game._put_permanent_onto_battlefield(seat, _W1G2Permanent(card=bear), None)
    assert cost_reduction_for_cast(game, 0, might)[0].generic == 0, "3 and 3"
    game._put_permanent_onto_battlefield(2, _W1G2Permanent(card=bear), None)
    assert cost_reduction_for_cast(game, 0, might)[0].generic == 6, "a lead of 4"
    game._put_permanent_onto_battlefield(0, _W1G2Permanent(card=bear), None)
    assert cost_reduction_for_cast(game, 0, might)[0].generic == 0, "a lead of 3"


def test_w1g2_avatar_of_woe_counts_creature_cards_in_every_graveyard(set_pool):
    """"…ten or more creature cards **total in all graveyards**." Every pile,
    summed — "total" is the reading the count's ``owner: "all"`` already has —
    and *creature* cards only: a land card in a graveyard is not one of the
    ten."""
    from engine.cost_modifiers import cost_reduction_for_cast

    lea = set_pool("LEA")
    woe = set_pool("PCY")["Avatar of Woe"]
    game = _w1g2_avatar_game(
        set_pool, "Avatar of Woe", my_grave=("Grizzly Bears",) * 9,
        their_grave=("Island",) * 4,
    )
    assert cost_reduction_for_cast(game, 0, woe)[0].generic == 0
    game.players[1].graveyard.append(lea["Grizzly Bears"])
    assert cost_reduction_for_cast(game, 0, woe)[0].generic == 6


def test_w1g2_avatar_of_hope_blocks_any_number_of_creatures(set_pool):
    """Avatar of Hope's other line — Wall of Glare's permission, which the
    block-permission table already read; the card was unsupported for its cost
    line alone. Three attackers rather than two, so a grant of one additional
    block cannot pass."""
    bear = set_pool("LEA")["Grizzly Bears"]
    hope = _W1G2Permanent(card=set_pool("PCY")["Avatar of Hope"])
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="P1", battlefield=[_W1G2Permanent(card=bear) for _ in range(3)]),
        _W1G2PlayerState(name="P2", battlefield=[hope]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    declared, why = game.declare_attackers(0, [0, 1, 2], 1)
    assert declared, why
    game.advance_combat_phase()

    blocked, why = game.declare_blockers(1, {0: [0, 1, 2]})
    assert blocked, why


def test_w1g2_a_trailing_and_a_fronted_condition_together_refuse(set_pool):
    """One sentence, two conditions — a conjunction no reader here was asked
    to read, and either half alone is a cheaper spell than the card. The line
    refuses rather than keeping one."""
    from engine.cost_modifiers import self_cost_reduction

    assert self_cost_reduction(
        "If you have 3 or less life, this spell costs {6} less to cast if an "
        "opponent has no cards in hand."
    ) is None
    # …and a fronted condition the grammar cannot read refuses too.
    assert self_cost_reduction(
        "If the moon is full, this spell costs {6} less to cast."
    ) is None
    # …as does one it reads but a spell being cast cannot ask (CR 601.2f has no
    # trigger to have frozen "that player").
    assert self_cost_reduction(
        "If that player has no cards in hand, this spell costs {6} less to cast."
    ) is None


def test_w1g2_defense_of_the_heart_counts_one_opponents_creatures(set_pool):
    """"At the beginning of your upkeep, if **an opponent** controls three or
    more creatures, …" — the shipped card the existential above fixed. The
    evaluator pooled every opponent's board, so at a three-seat table two
    opponents with two creatures each fired it; a duel cannot tell the readings
    apart, which is how it shipped.
    """
    from engine.game_types import OracleExecutionContext
    from engine.handlers.control_flow import evaluate_condition

    ulg = set_pool("ULG")
    bear = set_pool("LEA")["Grizzly Bears"]
    defense = ulg["Defense of the Heart"]
    gate = next(
        trig.instruction.payload["intervening_if"]
        for trig in _w1g2_compile(defense).triggered_abilities
        if trig.instruction is not None
        and "intervening_if" in trig.instruction.payload
    )
    game = _W1G2Game(players=[_W1G2PlayerState(name=f"P{n}") for n in (1, 2, 3)])
    for seat in (1, 2):
        for _ in range(2):
            game._put_permanent_onto_battlefield(seat, _W1G2Permanent(card=bear), None)
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=defense,
    )
    assert not evaluate_condition(game, context, gate), "2 + 2 is not one opponent's 3"
    game._put_permanent_onto_battlefield(2, _W1G2Permanent(card=bear), None)
    assert evaluate_condition(game, context, gate)


def test_w1g2_tithe_compares_the_targeted_opponent_only(set_pool):
    """"If **target opponent** controls more lands than you, you may search
    your library for an additional Plains card." (Tithe.) The lead comparison
    the Avatar of Might margin rides on answered over *any* opponent whatever
    the seat word said, so at a three-seat table Tithe aimed at an opponent
    with fewer lands still found its second Plains because somebody else had
    more. The picker announces the opponent (``derive_cast_spec`` asks for a
    player, opponents only), so the comparison is with that seat.
    """
    from engine.game_types import OracleExecutionContext
    from engine.handlers.control_flow import evaluate_condition

    tithe = set_pool("VIS")["Tithe"]
    steps = _w1g2_compile(tithe).instructions[0].payload["steps"]
    gate = next(step for step in steps if step.kind == "if_then").payload["condition"]
    assert gate["who"] == "target_opponent"

    land = set_pool("LEA")["Plains"]
    game = _W1G2Game(players=[_W1G2PlayerState(name=f"P{n}") for n in (1, 2, 3)])
    for seat, count in ((0, 1), (1, 0), (2, 5)):
        for _ in range(count):
            game._put_permanent_onto_battlefield(seat, _W1G2Permanent(card=land), None)

    def asked_of(seat):
        return evaluate_condition(game, OracleExecutionContext(
            caster=game.players[0], target=game.players[seat], card=tithe,
        ), gate)

    assert not asked_of(1), "P2 has fewer lands; P3's five are not the target's"
    assert asked_of(2)

# --- W1G5: prevention and odd ones ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_blocked_by(set_pool, defender_name, attacker_names, blocks):
    """Seat 1 attacks seat 0 with *attacker_names* (LEA); seat 0's
    *defender_name* (PCY) blocks per *blocks* ({blocker slot: attacker slot});
    stopped in the declare-blockers step. W1G5's own."""
    lea = set_pool("LEA")
    defender = _W1G5Permanent(card=set_pool("PCY")[defender_name])
    attackers = [_W1G5Permanent(card=lea[n]) for n in attacker_names]
    me = _W1G5PlayerState(name="W1G5-A", battlefield=[defender])
    them = _W1G5PlayerState(name="W1G5-B", battlefield=list(attackers))
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    for perm in (defender, *attackers):
        perm.metadata["summoning_sickness_turn"] = -99
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, list(range(len(attackers))))[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, dict(blocks))[0]
    assert game.current_step == "declare_blockers"
    return game, me, them, defender, attackers


def _w1g5_finish_the_combat(game):
    for _ in range(6):
        if game.current_turn_phase == "postcombat_main":
            return
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)


def test_w1g5_shield_dancer_turns_the_attackers_damage_on_itself(set_pool):
    """"{2}{W}: The next time target attacking creature would deal combat damage
    to this creature this turn, that creature deals that damage to itself
    instead."

    Hill Giant attacks into the blocking Dancer; with the ability on the Giant,
    its 3 combat damage is dealt to the Giant (CR 614.9 — by the Giant, in
    full) and the Dancer's 1 lands too, so the Giant dies and the 1/3 Dancer is
    untouched. The picker offers attacking creatures only.
    """
    game, _me, them, dancer, (giant,) = _w1g5_blocked_by(
        set_pool, "Shield Dancer", ["Hill Giant"], {0: 0},
    )
    spec = game.activation_target_spec(0, 0, 0)
    assert [t["name"] for t in spec["valid_targets"]] == ["Hill Giant"]
    assert game.activate_permanent_ability(
        0, "Shield Dancer", target_player_index=1,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    _w1g5_finish_the_combat(game)

    assert [c.name for c in them.graveyard] == ["Hill Giant"]
    assert game.is_on_battlefield(dancer) and dancer.damage_marked == 0


def test_w1g5_shield_dancer_moves_one_instance_from_that_creature_only(set_pool):
    """"The next time" is one instance, and only the announced creature's: a
    second attacker blocked by nothing deals its damage to the player as usual,
    and the record does not reach it."""
    game, me, them, dancer, (giant, bears) = _w1g5_blocked_by(
        set_pool, "Shield Dancer", ["Hill Giant", "Grizzly Bears"], {0: 0},
    )
    assert game.activate_permanent_ability(
        0, "Shield Dancer", target_player_index=1,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    _w1g5_finish_the_combat(game)
    assert me.life == 18, "the unblocked Bears still connect"
    assert [c.name for c in them.graveyard] == ["Hill Giant"]


def _w1g5_glitter_table(set_pool, name, bolts):
    """*name* (PCY) on seat 0; seat 1 to act in its main phase holding *bolts*
    Lightning Bolts. W1G5's own."""
    lea = set_pool("LEA")
    cat = _W1G5Permanent(card=set_pool("PCY")[name])
    me = _W1G5PlayerState(name="W1G5-A", battlefield=[cat])
    them = _W1G5PlayerState(name="W1G5-B", hand=[lea["Lightning Bolt"]] * bolts)
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game._settle()
    game.active_player_index = 1
    game.current_turn_phase = "precombat_main"
    return game, me, them, cat


def _w1g5_bolt(game, cat):
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[cat.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)


def test_w1g5_glittering_lion_shield_comes_off_when_anyone_pays(set_pool):
    """"Prevent all damage that would be dealt to this creature. / {3}: Until
    end of turn, this creature loses "Prevent all damage that would be dealt to
    this creature." Any player may activate this ability."

    The opponent's first Bolt is prevented whole. The opponent then activates
    it (CR 602.1b: the text says which players may) and pays the {3} from
    **their own** pool (CR 602.1a), the Lion loses the line (CR 613.1f) and the
    second Bolt kills it.
    """
    game, me, them, lion = _w1g5_glitter_table(set_pool, "Glittering Lion", 2)
    _w1g5_bolt(game, lion)
    assert game.is_on_battlefield(lion) and lion.damage_marked == 0

    game.enforce_mana_costs = True
    them.mana_pool["R"] = 3
    assert game.activate_permanent_ability(
        1, "Glittering Lion", ability_index=0, source_controller_index=0,
    ).supported
    assert them.mana_pool["R"] == 0, "the activator pays"
    _w1g5_resolve_stack(game)
    game.enforce_mana_costs = False

    _w1g5_bolt(game, lion)
    assert not game.is_on_battlefield(lion)
    assert [c.name for c in me.graveyard] == ["Glittering Lion"]


def test_w1g5_glittering_lynx_gets_its_shield_back_at_cleanup(set_pool):
    """"Until end of turn" is the removal's whole lifetime: after the cleanup
    step (CR 514.2) the Lynx says the line again and the next Bolt is
    prevented. The activated ability itself is never what is lost."""
    game, _me, _them, lynx = _w1g5_glitter_table(set_pool, "Glittering Lynx", 1)
    assert game.activate_permanent_ability(
        1, "Glittering Lynx", ability_index=0, source_controller_index=0,
    ).supported
    _w1g5_resolve_stack(game)
    shield = "prevent all damage that would be dealt to this creature."
    assert shield not in lynx.effective_card.oracle_text.lower().splitlines()

    game.resolve_cleanup_step(1)
    assert shield in lynx.effective_card.oracle_text.lower().splitlines()
    game.start_turn(1)
    game._close_current_priority_step()
    game.active_player_index = 1
    game.current_turn_phase = "precombat_main"
    _w1g5_bolt(game, lynx)
    assert game.is_on_battlefield(lynx) and lynx.damage_marked == 0
# end of the W1G5 creatures block

# --- W1G6: tokens, zones and triggers ---
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.tokens import make_token_card as _w1g6_make_token_card
from tests.helpers import _mk_card as _w1g6_mk_card, resolve_stack as _w1g6_resolve


def _w1g6_permanent(game, seat, card, *, token=False):
    perm = _W1G6Permanent(card=card)
    if token:
        perm.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g6_two_seat_game(**p1_zones):
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0"), _W1G6PlayerState(name="P1", **p1_zones),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    return game  # _w1g6_two_seat_game


def _w1g6_tuck_test(set_pool, informer_name, subtype):
    pcy = set_pool("PCY")
    library_top = _w1g6_mk_card("Library Top", "Sorcery")
    game = _w1g6_two_seat_game(library=[library_top])
    informer = _w1g6_permanent(game, 0, pcy[informer_name])
    victim = _w1g6_permanent(
        game, 1, _w1g6_mk_card(f"Hired {subtype}", f"Creature — Human {subtype}")
    )
    token = _w1g6_permanent(game, 1, _w1g6_make_token_card(
        f"{subtype} Token", 1, 1, f"Creature — {subtype}"), token=True)
    bystander = _w1g6_permanent(game, 1, _w1g6_mk_card("Bear", "Creature — Bear"))

    # "nontoken" and the creature type are both the picker's answer, so a
    # token of the type and a creature of another type are refused before any
    # cost is paid.
    for refused in (token, bystander):
        result = game.activate_permanent_ability(
            0, informer_name, target_permanent_ids=[refused.permanent_id]
        )
        assert not result.supported, refused.card.name
    assert not game.stack

    result = game.activate_permanent_ability(
        0, informer_name, target_permanent_ids=[victim.permanent_id]
    )
    assert result.supported, result.details
    _w1g6_resolve(game)

    assert not game.is_on_battlefield(victim)
    # The bottom, not the top: the card on top stays where it was.
    assert [c.name for c in game.players[1].library] == [
        "Library Top", f"Hired {subtype}",
    ]
    assert game.is_on_battlefield(token) and game.is_on_battlefield(bystander)
    assert game.is_on_battlefield(informer)
    assert any("on the bottom of" in line for line in game.log)


def test_w1g6_mercenary_informer_bottoms_a_nontoken_mercenary(set_pool):
    """"{2}{W}: Put target nontoken Mercenary on the bottom of its owner's
    library." The owner's library, the bottom end, and only a nontoken
    Mercenary is a legal target."""
    _w1g6_tuck_test(set_pool, "Mercenary Informer", "Mercenary")


def test_w1g6_rebel_informer_bottoms_a_nontoken_rebel(set_pool):
    """"{3}: Put target nontoken Rebel on the bottom of its owner's library.\""""
    _w1g6_tuck_test(set_pool, "Rebel Informer", "Rebel")


def test_w1g6_thresher_beast_makes_the_defending_player_sacrifice_a_land(set_pool):
    """"Whenever this creature becomes blocked, defending player sacrifices a
    land of their choice." The defending seat sacrifices — not the attacker,
    who also controls a land — and only once it is blocked."""
    pcy = set_pool("PCY")
    game = _w1g6_two_seat_game()
    beast = _w1g6_permanent(game, 0, pcy["Thresher Beast"])
    my_land = _w1g6_permanent(game, 0, _w1g6_mk_card("Forest", "Basic Land — Forest"))
    blocker = _w1g6_permanent(game, 1, _w1g6_mk_card("Bear", "Creature — Bear"))
    for name in ("Mountain", "Island"):
        _w1g6_permanent(game, 1, _w1g6_mk_card(name, f"Basic Land — {name}"))

    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [game.players[0].battlefield.index(beast)])[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert len([p for p in game.controlled_by(1) if p.card.type_line.startswith("Basic")]) == 2
    assert game.declare_blockers(1, {game.players[1].battlefield.index(blocker): 0})[0]
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()

    their_lands = [p.card.name for p in game.controlled_by(1) if p.card.name != "Bear"]
    assert len(their_lands) == 1, their_lands
    assert len(game.players[1].graveyard) == 1
    assert game.players[1].graveyard[0].name in ("Mountain", "Island")
    assert game.is_on_battlefield(my_land)
    assert not game.players[0].graveyard


def test_w1g6_keldon_firebombers_leaves_each_player_three_lands(set_pool):
    """"When this creature enters, each player sacrifices all lands they
    control except for three." Five lands become three for one seat; a seat
    with two keeps both; nonland permanents are untouched."""
    firebombers = set_pool("PCY")["Keldon Firebombers"]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", hand=[firebombers]), _W1G6PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    names = ("Plains", "Island", "Swamp", "Mountain", "Forest")
    mine = [_w1g6_permanent(game, 0, _w1g6_mk_card(n, f"Basic Land — {n}")) for n in names]
    theirs = [_w1g6_permanent(game, 1, _w1g6_mk_card(n, f"Basic Land — {n}")) for n in names[:2]]
    bear = _w1g6_permanent(game, 1, _w1g6_mk_card("Bear", "Creature — Bear"))

    assert game.cast_from_hand(0, "Keldon Firebombers").supported
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)

    assert sum(game.is_on_battlefield(p) for p in mine) == 3
    assert len(game.players[0].graveyard) == 2
    assert all(game.is_on_battlefield(p) for p in theirs)
    assert game.is_on_battlefield(bear)
    assert any(p.card.name == "Keldon Firebombers" for p in game.controlled_by(0))


# --- W2G1: tolls, part two ---
from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from engine.models import Permanent as _W2G1Permanent
from tests.helpers import _mk_card as _w2g1_mk_card, resolve_stack as _w2g1_resolve


def _w2g1_charmer_combat(set_pool, *, charmer_seat: int, p1_islands: int = 0):
    """Death Charmer and a 0/5 Wall on opposite sides, one combat to blocks.

    The Charmer attacks when it is seat 0's and blocks when it is seat 1's;
    either way it deals combat damage to the Wall, whose controller is the
    seat the toll and the loss both belong to."""
    island = set_pool("LEA")["Island"]
    game = _W2G1Game(players=[
        _W2G1PlayerState(name="P0"),
        _W2G1PlayerState(
            name="P1", battlefield=[_W2G1Permanent(card=island) for _ in range(p1_islands)],
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    charmer = _W2G1Permanent(card=set_pool("PCY")["Death Charmer"])
    game._put_permanent_onto_battlefield(charmer_seat, charmer, None)
    charmer.metadata["summoning_sickness_turn"] = -99
    other = _W2G1Permanent(card=_w2g1_mk_card(
        "Stone Wall", "Creature — Wall", power=0 if charmer_seat == 0 else 1,
        toughness=5,
    ))
    game._put_permanent_onto_battlefield(1 - charmer_seat, other, None)
    other.metadata["summoning_sickness_turn"] = -99
    attacker, blocker = (charmer, other) if charmer_seat == 0 else (other, charmer)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(
        0, [game.players[0].battlefield.index(attacker)]
    )[0]
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {game.players[1].battlefield.index(blocker): 0}
    )[0]
    return game, other  # _w2g1_charmer_combat


def _w2g1_to_combat_damage(game, *, answer=None):
    for _ in range(4):
        game.advance_combat_phase()
        _w2g1_resolve(game)
        if answer is not None and game.pending_choices:
            seat, accept = answer
            assert [c.player_index for c in game.pending_choices] == [seat]
            assert game.confirm_optional_pay(seat, accept=accept)
            answer = None
        game.auto_resolve_pending_choices()
        _w2g1_resolve(game)
    return answer  # _w2g1_to_combat_damage: None once the offer was answered


def test_w2g1_death_charmer_drains_the_damaged_creatures_controller(set_pool):
    """"Whenever this creature deals combat damage to a creature, that
    creature's controller loses 2 life unless they pay {2}." The Wall's
    controller cannot pay, so **they** lose 2 — not the Charmer's controller,
    who is the other end of the same damage event."""
    game, _wall = _w2g1_charmer_combat(set_pool, charmer_seat=0)
    _w2g1_to_combat_damage(game)

    assert (game.players[0].life, game.players[1].life) == (20, 18)
    assert any("P1 lost 2 life" in line for line in game.log), game.log[-6:]


def test_w2g1_death_charmer_toll_is_paid_by_the_damaged_creatures_controller(set_pool):
    """The same seat is offered the {2}: paying it taps two of their Islands
    and nobody loses life."""
    game, _wall = _w2g1_charmer_combat(set_pool, charmer_seat=0, p1_islands=2)
    assert _w2g1_to_combat_damage(game, answer=(1, True)) is None, "no offer made"

    assert (game.players[0].life, game.players[1].life) == (20, 20)
    assert sum(1 for p in game.controlled_by(1) if p.tapped) == 2


def test_w2g1_death_charmer_blocking_drains_the_attackers_controller(set_pool):
    """Blocking, the creature it damages is the attacker — so the active
    player, who controls it, loses the life, and the Charmer's controller
    (the defender) does not."""
    game, _attacker = _w2g1_charmer_combat(set_pool, charmer_seat=1)
    _w2g1_to_combat_damage(game)

    assert (game.players[0].life, game.players[1].life) == (18, 20)


# --- W2G4: cost choices ---
# CR 601.2h through CR 602.2b, and CR 508.1h / 509.1d: every choice inside a
# cost is the payer's. Wave 1 landed these cards with the second card of
# "Discard two cards", Hollow Warrior's tapped creature and Keldon
# Battlewagon's picker all made by the engine's default for a human seat; the
# shipped cards of the same shapes are in tests/rules/test_cost_choices.py.
import pytest as _w2g4_pytest

from engine import Game as _W2G4Game
from engine import PlayerState as _W2G4PlayerState
from engine.models import Permanent as _W2G4Permanent
from tests.helpers import resolve_stack as _w2g4_resolve


def _w2g4_table(mine, theirs=(), *, hand=()):
    """Seat 0 holds *mine* and *hand*, seat 1 *theirs*; seat 0's turn, mana
    off, nothing summoning sick. Returns the game and both permanent lists."""
    w2g4_me = [_W2G4Permanent(card=card) for card in mine]
    w2g4_them = [_W2G4Permanent(card=card) for card in theirs]
    w2g4_game = _W2G4Game(players=[
        _W2G4PlayerState(name="W2G4-A", battlefield=list(w2g4_me), hand=list(hand)),
        _W2G4PlayerState(name="W2G4-B", battlefield=list(w2g4_them)),
    ])
    w2g4_game.enforce_mana_costs = False
    for w2g4_perm in (*w2g4_me, *w2g4_them):
        w2g4_perm.metadata["summoning_sickness_turn"] = -99
    w2g4_game.start_turn(0)
    w2g4_game._close_current_priority_step()
    return w2g4_game, w2g4_me, w2g4_them


def test_w2g4_latulla_discards_exactly_the_two_cards_named(set_pool):
    """"Discard two cards" is two choices. The first rides ``cost_hand_index``
    and the second ``cost_other_hand_indices``; the default would have binned
    the first two cards in hand, and the payer named the second and fourth."""
    lea = set_pool("LEA")
    hand = [lea["Grizzly Bears"], lea["Forest"], lea["Hill Giant"], lea["Island"]]
    game, (latulla,), _ = _w2g4_table(
        [set_pool("PCY")["Latulla, Keldon Overseer"]], hand=hand,
    )
    result = game.queue_permanent_ability(
        0, "Latulla, Keldon Overseer", target_player_index=1, x_value=2,
        cost_hand_index=1, cost_other_hand_indices=[3],
    )
    assert result.supported, result.details
    _w2g4_resolve(game)

    p0, p1 = game.players
    assert sorted(c.name for c in p0.graveyard) == ["Forest", "Island"]
    assert [c.name for c in p0.hand] == ["Grizzly Bears", "Hill Giant"]
    assert latulla.tapped and p1.life == 18


@_w2g4_pytest.mark.parametrize(
    "first,others,refusal",
    [
        (1, [1], "each named once"),
        (0, [1, 2], "each named once"),
        (0, [9], "no card at hand position 9"),
    ],
)
def test_w2g4_latulla_refuses_a_bad_second_card_before_anything_is_paid(
    set_pool, first, others, refusal,
):
    """A second card named twice, a third card for a two-card cost, a position
    off the end of the hand: each is a payment that cannot be made as named,
    so the activation is refused with the tap, the mana and the hand intact."""
    lea = set_pool("LEA")
    hand = [lea["Grizzly Bears"], lea["Forest"], lea["Hill Giant"]]
    game, (latulla,), _ = _w2g4_table(
        [set_pool("PCY")["Latulla, Keldon Overseer"]], hand=hand,
    )
    result = game.queue_permanent_ability(
        0, "Latulla, Keldon Overseer", target_player_index=1, x_value=2,
        cost_hand_index=first, cost_other_hand_indices=others,
    )
    assert not result.supported and refusal in result.details
    assert len(game.players[0].hand) == 3 and not game.players[0].graveyard
    assert not latulla.tapped and game.players[1].life == 20


def test_w2g4_the_spellshapers_picker_asks_for_two_cards(set_pool):
    """The count the client's discard prompt reads to collect two cards rather
    than one, for every spellshaper whose cost prints "two"."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    pcy = set_pool("PCY")
    for name in (
        "Alexi, Zephyr Mage", "Greel, Mind Raker", "Jolrael, Empress of Beasts",
        "Latulla, Keldon Overseer", "Mageta the Lion",
    ):
        (ability,) = compile_card_oracle(pcy[name]).activated_abilities
        spec = derive_activation_spec(ability)
        # Beside a target, or the whole announcement when there is none
        # (Mageta's "Destroy all creatures except for Mageta").
        cost = spec.get("cost_spec") or spec
        assert cost["discard_cost"] is True and cost["count"] == 2, name


def test_w2g4_keldon_battlewagon_offers_its_tap_cost_and_taps_the_pick(set_pool):
    """The picker a human answers: a ``tap_cost`` over the untapped creatures
    the controller has — the Battlewagon itself among them, since nothing
    prints "another" — and the creature named is the one tapped, whose power
    is what the Battlewagon gets."""
    lea = set_pool("LEA")
    game, (wagon, bears, giant, ogre), _ = _w2g4_table([
        set_pool("PCY")["Keldon Battlewagon"], lea["Grizzly Bears"],
        lea["Hill Giant"], lea["Hill Giant"],
    ])
    ogre.tapped = True
    spec = game.activation_target_spec(0, 0)
    assert spec["tap_cost"] is True and spec["count"] == 1
    assert [t["name"] for t in spec["valid_targets"]] == [
        "Keldon Battlewagon", "Grizzly Bears", "Hill Giant",
    ]

    result = game.queue_permanent_ability(
        0, "Keldon Battlewagon", cost_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details
    _w2g4_resolve(game)
    assert giant.tapped and not bears.tapped and not wagon.tapped
    assert wagon.effective_power == 3


def test_w2g4_copper_leaf_angel_sacrifices_the_lands_named_for_x(set_pool):
    """The client announces X as the number of lands it names, so the two
    always agree: two named Forests, X = 2, and the unnamed one stays."""
    forest = set_pool("LEA")["Forest"]
    game, (angel, f1, f2, f3), _ = _w2g4_table(
        [set_pool("PCY")["Copper-Leaf Angel"], forest, forest, forest],
    )
    result = game.queue_permanent_ability(
        0, "Copper-Leaf Angel", x_value=2,
        cost_permanent_ids=[f1.permanent_id, f3.permanent_id],
    )
    assert result.supported, result.details
    _w2g4_resolve(game)
    assert game.is_on_battlefield(f2)
    assert not game.is_on_battlefield(f1) and not game.is_on_battlefield(f3)
    assert (angel.effective_power, angel.effective_toughness) == (4, 4)


def test_w2g4_hollow_warrior_taps_the_creature_its_controller_names(set_pool):
    """CR 508.1h: which creature the attack taps is the attacking player's.
    The default taps the least valuable spare (the Bears); the player named
    the Giant, and the Giant is what taps."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game, (warrior, bears, giant), _ = _w2g4_table(
        [pcy["Hollow Warrior"], lea["Grizzly Bears"], lea["Hill Giant"]],
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    (choice,) = game.declaration_cost_choices(warrior, "attack")
    assert choice["verb"] == "tap"
    assert choice["candidate_ids"] == [bears.permanent_id, giant.permanent_id]

    ok, why = game.declare_attackers(0, [0], cost_permanent_ids=[giant.permanent_id])
    assert ok, why
    assert warrior.attacking and giant.tapped and not bears.tapped
    assert "W2G4-A tapped Hill Giant to attack" in game.log


def test_w2g4_hollow_warrior_refuses_to_tap_a_creature_being_declared(set_pool):
    """Naming the other attacker is naming a creature "declared as an
    attacking creature this combat" — the printed exclusion — so the
    declaration is refused rather than paid with somebody else."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game, (warrior, bears, giant), _ = _w2g4_table(
        [pcy["Hollow Warrior"], lea["Grizzly Bears"], lea["Hill Giant"]],
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    ok, why = game.declare_attackers(0, [0, 1], cost_permanent_ids=[bears.permanent_id])
    assert not ok and "Grizzly Bears cannot pay" in why
    assert not any(perm.tapped for perm in (warrior, bears, giant))


def test_w2g4_hollow_warrior_blocks_by_tapping_the_creature_named(set_pool):
    """CR 509.1d, the defender's half: the block taps the creature the
    defending player named rather than the default's."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game, (attacker,), (warrior, zombies, giant) = _w2g4_table(
        [lea["Grizzly Bears"]],
        [pcy["Hollow Warrior"], lea["Scathe Zombies"], lea["Hill Giant"]],
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.current_step = "declare_blockers"
    ok, why = game.declare_blockers(1, {0: 0}, cost_permanent_ids=[giant.permanent_id])
    assert ok, why
    assert giant.tapped and not zombies.tapped and not warrior.tapped
    assert "W2G4-B tapped Hill Giant to block" in game.log
