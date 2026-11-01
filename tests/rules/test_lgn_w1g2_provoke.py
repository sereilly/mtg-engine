"""Provoke (CR 702.39), the keyword and the triggered ability it is.

"Provoke" means "Whenever this creature attacks, you may choose to have target
creature defending player controls block this creature this combat if able. If
you do, untap that creature." (CR 702.39a.) Every clause is a separate thing an
engine can get wrong, and this file holds one test per clause:

* the trigger and its target, chosen as it is put on the stack (CR 603.3d), out
  of the creatures of the player *this* creature attacks (CR 802.2a);
* the "may", answered as it resolves — declined, nothing happens;
* the untap and the requirement, which CR 509.1c counts with every other
  requirement and which binds only a creature *able* to block;
* "this combat" — the requirement ends with the combat (CR 511.3), so a second
  combat phase in the same turn (CR 500.8) is not compelled;
* CR 702.39b, two instances, two triggers — through a lord's grant, because
  that is how a creature comes to have two (Hunter Sliver).

The card-by-card tests are in ``tests/sets/test_lgn_creatures.py`` (W1G2).
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.combat_permissions import MUST_BLOCK_ATTACKERS_THIS_COMBAT
from engine.game import Game
from engine.models import CardDefinition, Permanent

from tests.helpers import _mk_creature_card, _nosick, resolve_stack


def _sliver(name: str = "Test Sliver", power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Sliver",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Sliver",
             "power": str(power), "toughness": str(toughness)},
    )


def _table(attackers, defenders, *, seats=2, interactive=(), tapped=(), defender_seat=1):
    """Attackers on seat 0 (no summoning sickness), defenders on
    *defender_seat*, the turn at seat 0's declare-attackers step."""
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[_mk_creature_card("Filler", 1, 1)] * 3)
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    mine = []
    for card in attackers:
        perm = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, perm, None)
        _nosick(perm)
        mine.append(perm)
    theirs = []
    for index, (seat, card) in enumerate(defenders):
        perm = Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, perm, None)
        perm.tapped = index in tapped
        theirs.append(perm)
    resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game, mine, theirs


def _settle(game) -> None:
    """Resolve the stack and answer what a seat nobody asks would answer."""
    for _ in range(10):
        resolve_stack(game)
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices()


@pytest.mark.cr("702.39a", "603.3d", "509.1c")
def test_provoke_untaps_its_target_and_makes_it_block_this_creature(set_pool):
    """Goblin Grappler attacks; its controller names the tapped Wall, takes
    the "may", and the Wall is untapped and owes the Grappler a block. A
    declaration leaving it home is refused, and so is one where it blocks
    nothing but a creature beside it does: the requirement names the pair."""
    grappler = set_pool("LGN")["Goblin Grappler"]
    game, (attacker,), (bear, wall) = _table(
        [grappler],
        [(1, _mk_creature_card("Bear", 2, 2)), (1, _mk_creature_card("Wall", 0, 4))],
        interactive=(0, 1), tapped=(1,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    choice = next(c for c in game.pending_choices if c.kind == "trigger_target")
    assert {t["name"] for t in choice.data["targets"]} == {"Bear", "Wall"}
    assert game.resolve_pending_choice("trigger_target", 0, permanent_id=wall.permanent_id)
    assert game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    resolve_stack(game)

    assert not wall.tapped, "If you do, untap that creature."
    assert wall.metadata[MUST_BLOCK_ATTACKERS_THIS_COMBAT] == [attacker.permanent_id]
    assert "Wall blocks Goblin Grappler this combat if able" in game.log
    game.advance_combat_phase()
    assert game.declare_blockers(1, {}) == (
        False, "Wall must block Goblin Grappler this combat if able"
    )
    assert game.declare_blockers(1, {0: 0})[0] is False
    assert game.declare_blockers(1, {1: 0})[0], game.log


@pytest.mark.cr("702.39a")
def test_declining_provoke_leaves_the_target_tapped_and_free(set_pool):
    """"You may choose": declined, the creature stays tapped and owes nothing,
    so not blocking at all is a legal declaration."""
    grappler = set_pool("LGN")["Goblin Grappler"]
    game, _mine, (wall,) = _table(
        [grappler], [(1, _mk_creature_card("Wall", 0, 4))],
        interactive=(0, 1), tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    assert game.resolve_pending_choice("trigger_target", 0, permanent_id=wall.permanent_id)
    assert game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    resolve_stack(game)

    assert wall.tapped
    assert not wall.metadata.get(MUST_BLOCK_ATTACKERS_THIS_COMBAT)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0], game.log


@pytest.mark.cr("802.2a", "603.3d")
def test_provoke_names_a_creature_of_the_player_this_creature_attacks(set_pool):
    """Three seats: the Grappler attacks seat 2, so "defending player" is
    seat 2 (CR 802.2a) and seat 1's creatures are not offered."""
    grappler = set_pool("LGN")["Goblin Grappler"]
    game, _mine, (bystander, defender) = _table(
        [grappler],
        [(1, _mk_creature_card("Bystander", 2, 2)), (2, _mk_creature_card("Defender", 2, 2))],
        seats=3, interactive=(0,),
    )
    assert game.declare_attackers(0, [0], attacker_targets={0: 2})[0], game.log
    choice = next(c for c in game.pending_choices if c.kind == "trigger_target")
    assert [t["name"] for t in choice.data["targets"]] == ["Defender"]
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_id=bystander.permanent_id
    ) is False, "a creature the picker never offered is refused"


@pytest.mark.cr("509.1c", "702.9b")
def test_a_provoked_creature_that_cannot_block_this_creature_is_not_compelled(set_pool):
    """CR 509.1c counts only requirements that can be obeyed without breaking
    a restriction: provoked by a flier it cannot block, the creature is
    untapped and owes the block, and staying home is still legal."""
    talon = set_pool("LGN")["Swooping Talon"]
    game, (attacker,), (bear,) = _table(
        [talon], [(1, _mk_creature_card("Bear", 2, 2))], tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    # A seat nobody asks would decline a block that cannot happen, so the
    # "may" is answered here as a player taking it anyway would.
    resolve_stack(game)
    offer = next(c for c in game.pending_choices if c.kind == "optional_pay")
    assert game.resolve_pending_choice("optional_pay", offer.player_index, accept=True)
    _settle(game)

    assert not bear.tapped
    assert bear.metadata[MUST_BLOCK_ATTACKERS_THIS_COMBAT] == [attacker.permanent_id]
    game.advance_combat_phase()
    assert game.block_requirements(1), "the requirement is still listed"
    assert game.declare_blockers(1, {})[0], "…and nothing can obey it"


@pytest.mark.cr("702.39a", "511.3", "500.8")
def test_the_requirement_lasts_this_combat_and_not_the_next(set_pool):
    """"…block this creature **this combat** if able." Relentless Assault
    adds a second combat phase (CR 500.8). The Wall that was provoked in the
    first owes nothing in the second: the mark ended with the first combat."""
    pool = set_pool("LGN")
    assault = set_pool("VIS")["Relentless Assault"]
    game, (attacker,), (wall,) = _table(
        [pool["Goblin Grappler"]], [(1, _mk_creature_card("Wall", 0, 4))],
        interactive=(0, 1), tapped=(0,),
    )
    game.players[0].hand.append(assault)
    assert game.declare_attackers(0, [0], 1)[0]
    assert game.resolve_pending_choice("trigger_target", 0, permanent_id=wall.permanent_id)
    assert game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    resolve_stack(game)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    for _ in range(12):
        if game.current_turn_phase != "combat":
            break
        game.advance_combat_phase()
    assert game.current_turn_phase == "postcombat_main"
    assert MUST_BLOCK_ATTACKERS_THIS_COMBAT not in wall.metadata

    assert game.cast_from_hand(0, "Relentless Assault").supported
    resolve_stack(game)
    assert game.enter_next_turn_phase() == "combat"
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    assert game.declare_attackers(0, [0], 1)[0], game.log
    assert game.resolve_pending_choice("trigger_target", 0, permanent_id=wall.permanent_id)
    assert game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    resolve_stack(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert game.declare_blockers(1, {})[0], "the first combat's requirement is over"


@pytest.mark.cr("702.39b", "613.1f")
def test_two_instances_of_provoke_trigger_separately(set_pool):
    """Two Hunter Slivers each grant provoke, so a Sliver attacking under both
    has two instances and puts two abilities on the stack (CR 702.39b) — the
    lord's grant is a grant of the line, once per lord."""
    hunter = set_pool("LGN")["Hunter Sliver"]
    game, (_h1, _h2, sliver), _theirs = _table(
        [hunter, hunter, _sliver()], [(1, _mk_creature_card("Bear", 2, 2))],
    )
    game.check_state_based_actions()
    assert game.declare_attackers(0, [2], 1)[0]
    provokes = [item for item in game.stack if item.ability_text == "provoke"]
    assert len(provokes) == 2
    assert all(item.source_permanent is sliver for item in provokes)


@pytest.mark.cr("509.1c", "702.39b")
def test_two_provoke_requirements_outweigh_one_lure(set_pool):
    """A creature owed a block by two provokes (two instances aimed at it)
    and by one requirement elsewhere obeys the side carrying more of them:
    CR 509.1c counts requirements, and two effects are two."""
    hunter = set_pool("LGN")["Hunter Sliver"]
    game, (_h1, _h2, sliver, other), (bear,) = _table(
        [hunter, hunter, _sliver(), _mk_creature_card("Other", 2, 2)],
        [(1, _mk_creature_card("Bear", 2, 2))],
        interactive=(0, 1),
    )
    game.check_state_based_actions()
    assert game.declare_attackers(0, [2, 3], 1)[0]
    for _ in range(2):
        assert game.resolve_pending_choice("trigger_target", 0, permanent_id=bear.permanent_id)
    for _ in range(2):
        assert game.resolve_top_of_stack()
        assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    resolve_stack(game)
    assert bear.metadata[MUST_BLOCK_ATTACKERS_THIS_COMBAT] == [sliver.permanent_id] * 2
    # One requirement toward the other attacker as well (Trumpeting
    # Armodon's mark, the turn-long twin).
    from engine.combat_permissions import MUST_BLOCK_ATTACKERS_UNTIL_EOT

    bear.metadata[MUST_BLOCK_ATTACKERS_UNTIL_EOT] = [other.permanent_id]
    game.advance_combat_phase()
    assert len(game.block_requirements(1)) == 3
    assert game.declare_blockers(1, {0: 3})[0] is False
    assert game.declare_blockers(1, {0: 2})[0], game.log
