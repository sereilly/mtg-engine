"""CR 509.1c, the maximisation: requirements obeyed against the most obeyable.

    509.1c … If the number of requirements that are being obeyed is fewer than
    the maximum possible number of requirements that could be obeyed without
    disobeying any restrictions, the declaration of blockers is illegal. If a
    creature can't block unless a player pays a cost, that player is not
    required to pay that cost, even if blocking with that creature would
    increase the number of requirements being obeyed. …

Each test plays the cards: the requirement is armed the way the card arms it
(Provoke cast, Trumpeting Armodon activated, Lure cast onto the attacker), the
attack is declared, and the defending player — an interactive seat — declares.
The board-by-board census over every channel is
``tests/regressions/test_kg_blocks_requirement_census.py``; these are the
rule's own sentences, one each.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_combat import CombatOutcome, declare_ai_blockers
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _mk_creature_card, _nosick, resolve_stack


_CATALOG: dict = {}


def _card(name):
    if not _CATALOG:
        _CATALOG.update({card.name: card for card in load_catalog()})
    return _CATALOG[name]


def _game(mine, theirs, *, hand=(), interactive=True) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=[_nosick(p) for p in mine], hand=list(hand)),
        PlayerState(name="P2", battlefield=[_nosick(p) for p in theirs]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {1} if interactive else set()
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _to_blockers(game, attackers):
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, why = game.declare_attackers(0, attackers, 1)
    assert ok, why
    resolve_stack(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"


def _accepted(make, declaration) -> bool:
    game = make()
    return game.declare_blockers(1, declaration)[0]


@pytest.mark.cr("509.1c", "702.111b")
def test_the_rules_own_example_blocks_a_menace_attacker_with_both_creatures():
    """CR 509.1c's example, word for word: "the player must block with both
    creatures. Having only the first creature block violates the restriction
    created by menace … Having neither creature block fulfills the restriction
    but not the requirement." The second creature has no requirement of its
    own and is drafted anyway — the maximum is one requirement, and only a
    declaration with both creatures in it reaches it."""
    def make():
        game = _game(
            [Permanent(card=_mk_creature_card("Menace Brute", 3, 3, "Menace"))],
            [Permanent(card=_card("Watchdog")), Permanent(card=_mk_creature_card("Bear", 2, 2))],
        )
        _to_blockers(game, [0])
        return game

    game = make()
    ok, why = game.declare_blockers(1, {})
    assert not ok and why == "Watchdog blocks each combat if able", why
    assert not _accepted(make, {0: [0]}), "menace: the Watchdog alone"
    assert not _accepted(make, {1: [0]}), "menace, and the requirement"
    game = make()
    assert game.declare_blockers(1, {0: [0], 1: [0]})[0], game.log
    assert game.combat_blockers == {1: {0: [0], 1: [0]}}


@pytest.mark.cr("509.1c", "509.1b")
def test_three_watchdogs_under_caverns_of_despair_block_with_any_two():
    """The board that had no legal declaration: each two-Watchdog declaration
    left a third that "could block", and the three-Watchdog one broke the cap.
    The cap is a restriction, so the maximum is two requirements, and every
    declaration obeying two is legal — the refusal says so, because "Watchdog
    blocks each combat if able" read alone beside a Caverns is a riddle."""
    def make():
        game = _game(
            [Permanent(card=_mk_creature_card("Raider", 2, 2))],
            [Permanent(card=_card("Watchdog")) for _ in range(3)],
        )
        game.players[0].battlefield.append(Permanent(card=_card("Caverns of Despair")))
        game._sync_control()
        _to_blockers(game, [0])
        return game

    for pair in ((0, 1), (0, 2), (1, 2)):
        assert _accepted(make, {slot: [0] for slot in pair}), pair
    game = make()
    ok, why = game.declare_blockers(1, {0: [0]})
    assert not ok
    assert why == (
        "Watchdog blocks each combat if able (this declaration obeys 1 of the 2 "
        "blocking requirements that can be obeyed together)"
    ), why
    ok, why = make().declare_blockers(1, {0: [0], 1: [0], 2: [0]})
    assert not ok and "no more than 2" in why, why


@pytest.mark.cr("509.1c")
def test_provoke_and_dueling_grounds_leave_the_choice_of_which_creature_blocks():
    """Provoke, cast: "That creature blocks this turn if able." Two creatures
    provoked under Dueling Grounds' "No more than one creature can block each
    combat" — one requirement can be obeyed, by either of them, and a
    declaration obeying none is the illegal one."""
    provoke = _card("Provoke")

    def make():
        game = _game(
            [Permanent(card=_mk_creature_card("Raider", 2, 2))],
            [Permanent(card=_mk_creature_card("Guard A", 2, 2)),
             Permanent(card=_mk_creature_card("Guard B", 2, 2))],
            hand=[provoke, provoke],
        )
        for slot in (0, 1):
            assert game.cast_from_hand(
                0, "Provoke", target_player_index=1, target_permanent_index=slot,
            ).supported
            resolve_stack(game)
        game.players[0].battlefield.append(Permanent(card=_card("Dueling Grounds")))
        game._sync_control()
        _to_blockers(game, [0])
        return game

    assert not _accepted(make, {})
    assert _accepted(make, {0: [0]})
    assert _accepted(make, {1: [0]})
    assert not _accepted(make, {0: [0], 1: [0]}), "Dueling Grounds"


@pytest.mark.cr("509.1c")
def test_lure_compels_a_block_of_the_lured_creature_not_of_another():
    """Lure, cast onto the attacker: "All creatures able to block enchanted
    creature do so." The requirement is to block *that* creature, so a block
    of the other attacker obeys nothing — it used to pass, because the check
    asked only whether the compelled creature was blocking anything."""
    lure = _card("Lure")

    def make():
        game = _game(
            [Permanent(card=_mk_creature_card("Lured", 2, 2)),
             Permanent(card=_mk_creature_card("Raider", 2, 2))],
            [Permanent(card=_mk_creature_card("Bear", 2, 2))],
            hand=[lure],
        )
        assert game.cast_from_hand(
            0, "Lure", target_player_index=0, target_permanent_index=0,
        ).supported
        resolve_stack(game)
        _to_blockers(game, [0, 1])
        return game

    game = make()
    ok, why = game.declare_blockers(1, {0: [1]})
    assert not ok and why == "Bear must block Lured due to Lure", why
    assert _accepted(make, {0: [0]})


@pytest.mark.cr("509.1c")
def test_two_armodon_activations_under_dueling_grounds_ask_for_one_block():
    """Trumpeting Armodon, activated twice at two creatures: "Target creature
    blocks this creature this turn if able." Dueling Grounds lets one block,
    so either named creature obeys the maximum and neither is required to be
    the one."""
    armodon = _card("Trumpeting Armodon")

    def make():
        game = _game(
            [Permanent(card=armodon)],
            [Permanent(card=_mk_creature_card("Wall A", 0, 4)),
             Permanent(card=_mk_creature_card("Wall B", 0, 4))],
        )
        game.advance_combat_phase()
        game.advance_combat_phase()
        assert game.declare_attackers(0, [0], 1)[0]
        for slot in (0, 1):
            assert game.activate_permanent_ability(
                0, "Trumpeting Armodon", ability_index=0,
                target_player_index=1, target_permanent_index=slot,
            ).supported
            resolve_stack(game)
        game.players[0].battlefield.append(Permanent(card=_card("Dueling Grounds")))
        game._sync_control()
        game.advance_combat_phase()
        assert game.current_step == "declare_blockers"
        return game

    game = make()
    ok, why = game.declare_blockers(1, {})
    assert not ok and "must block Trumpeting Armodon this turn if able" in why, why
    assert _accepted(make, {0: [0]})
    assert _accepted(make, {1: [0]})


@pytest.mark.cr("509.1c")
def test_a_creature_owing_a_cost_is_never_drafted_to_obey_another_requirement():
    """The cost clause reaches the *helper* too. A Watchdog facing a 3-power
    menace attacker can obey its requirement only beside a second blocker, and
    the only other creature is Hipparion — "can't block creatures with power 3
    or greater unless you pay {1}". The player is "not required to pay that
    cost, even if blocking with that creature would increase the number of
    requirements being obeyed", so the maximum is none, declaring nothing is
    legal, and paying for both to block is legal as well."""
    def make():
        game = _game(
            [Permanent(card=_mk_creature_card("Menace Ogre", 4, 3, "Menace"))],
            [Permanent(card=_card("Watchdog")), Permanent(card=_card("Hipparion")),
             Permanent(card=_card("Plains"))],
        )
        _to_blockers(game, [0])
        return game

    # The Watchdog's anthem leaves the Ogre at 3 power, Hipparion's threshold.
    game = make()
    assert game.players[0].battlefield[0].effective_power == 3
    assert game.declare_blockers(1, {})[0], game.log
    game = make()
    assert game.declare_blockers(1, {0: [0], 1: [0]})[0], game.log
    assert game.players[1].battlefield[2].tapped, "the Plains paid Hipparion's {1}"


@pytest.mark.cr("509.1c", "802.4b")
def test_each_defending_player_is_held_to_their_own_maximum():
    """CR 802.4b: a defending player's blocks are judged with every other
    player's blockers ignored — so under one Caverns of Despair each defender
    may block with two, and each is held to the requirements on their own
    creatures alone."""
    p1 = PlayerState(name="P1", battlefield=[
        _nosick(Permanent(card=_mk_creature_card("Raider A", 2, 2))),
        _nosick(Permanent(card=_mk_creature_card("Raider B", 2, 2))),
        Permanent(card=_card("Caverns of Despair")),
    ])
    p2 = PlayerState(name="P2", battlefield=[
        _nosick(Permanent(card=_card("Watchdog"))) for _ in range(3)
    ])
    p3 = PlayerState(name="P3", battlefield=[_nosick(Permanent(card=_card("Watchdog")))])
    # CR 103.8a skips the first draw only in a two-player game.
    for player in (p1, p2, p3):
        player.library = [_mk_creature_card("Filler", 1, 1) for _ in range(5)]
    game = Game(players=[p1, p2, p3])
    game.enforce_mana_costs = False
    game.interactive_seats = {1, 2}
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1], attacker_targets={0: 1, 1: 2})[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"

    assert not game.declare_blockers(1, {0: [0]})[0]
    assert game.declare_blockers(1, {0: [0], 2: [0]})[0], game.log
    assert not game.declare_blockers(2, {})[0]
    assert game.declare_blockers(2, {0: [1]})[0], game.log


@pytest.mark.cr("509.1c")
def test_the_ai_declares_the_maximum_and_keeps_its_own_choice_where_it_can():
    """The AI's half: under Caverns of Despair with three Watchdogs and a Bear
    it would rather block with, the cap leaves two blocks, and the maximum
    says both go to Watchdogs. Its first declaration is accepted — nothing
    refused, nothing fallen back to."""
    game = _game(
        [Permanent(card=_mk_creature_card("Raider", 2, 2))],
        [*(Permanent(card=_card("Watchdog")) for _ in range(3)),
         Permanent(card=_mk_creature_card("Bear", 3, 3))],
        interactive=False,
    )
    game.players[0].battlefield.append(Permanent(card=_card("Caverns of Despair")))
    game._sync_control()
    _to_blockers(game, [0])
    outcome = CombatOutcome()
    assert declare_ai_blockers(game, 1, outcome=outcome)
    assert outcome.refused_blocks == [] and outcome.silent_blocks == []
    declared = game.combat_blockers.get(1, {})
    assert len(declared) == 2
    assert all(
        game.players[1].battlefield[slot].card.name == "Watchdog" for slot in declared
    ), declared
