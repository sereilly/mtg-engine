"""Ninjutsu — CR 702.49, Betrayers of Kamigawa's keyword.

"Ninjutsu is an activated ability that functions only while the card with
ninjutsu is in a player's hand. 'Ninjutsu [cost]' means '[Cost], Reveal this
card from your hand, Return an unblocked attacking creature you control to its
owner's hand: Put this card onto the battlefield from your hand tapped and
attacking.'" (CR 702.49a) — so ``engine/ninjutsu.py`` rewrites the printed line
into that sentence, and everything downstream reads an ordinary hand ability:
a reveal cost that keeps the card in the hand (CR 702.49b), a chosen return
cost, and an entry attacking (CR 508.4) what the returned creature attacked
(CR 702.49c).

"Unblocked" is CR 509.1h's status, which no attacker has until blockers are
declared — the 2021-03-19 ruling: "The ninjutsu ability can be activated only
after blockers have been declared. Before then, attacking creatures are
neither blocked nor unblocked." The clock is
``Game.blockers_have_been_declared``, read by every "unblocked" — so Mirror
Strike's "target unblocked creature" is held to it too.

The Ninja is an **invented** card wherever the keyword is the subject — it must
work on anything printing it — and the shipped pool's cards are witnesses
(Righteous Cause's attack trigger, Basri Ket as the planeswalker attacked,
Mirror Strike). Betrayers' eight Ninjas are driven in
``tests/sets/test_bok_creatures.py``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.activation_zones import BATTLEFIELD, HAND
from engine.models import CardDefinition, Permanent, PlayerState
from engine.ninjutsu import NINJUTSU_RULES_TEXT, expand_ninjutsu_line
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import _mk_creature_card, _nosick, settle


def _ninja(name="Test Shinobi", cost="{1}{U}", power="3", toughness="1", extra=""):
    lines = [
        f"Ninjutsu {cost} ({cost}, Return an unblocked attacker you control to "
        "hand: Put this card onto the battlefield from your hand tapped and "
        "attacking.)"
    ]
    if extra:
        lines.append(extra)
    raw = {"name": name, "type_line": "Creature — Human Ninja",
           "power": power, "toughness": toughness}
    return CardDefinition(
        name=name, mana_cost="{3}{U}", cmc=4.0, type_line="Creature — Human Ninja",
        oracle_text="\n".join(lines), colors=("U",), color_identity=("U",),
        keywords=(), produced_mana=(), raw=raw,
    )


def _table(*, runners=1, theirs=(), mine=(), hand=None):
    """A Ninja in P1's hand, *runners* 2/2s and *mine* on P1's side, *theirs*
    on P2's — P1's combat about to declare attackers."""
    runner_perms = [
        _nosick(Permanent(card=_mk_creature_card(f"Runner {i}", 2, 2)))
        for i in range(runners)
    ]
    others = [_nosick(Permanent(card=c)) for c in mine]
    defenders = [_nosick(Permanent(card=c)) for c in theirs]
    game = Game(players=[
        PlayerState(name="P1", hand=list(hand) if hand is not None else [_ninja()],
                    battlefield=runner_perms + others, life=20),
        PlayerState(name="P2", battlefield=defenders, life=20,
                    library=[_mk_creature_card("Filler", 1, 1)] * 5),
    ])
    game.enforce_mana_costs = False
    game._settle()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    return game, runner_perms, defenders


def _attack_and_declare_no_blocks(game, slots, **kwargs):
    assert game.declare_attackers(0, slots, defending_player_index=1, **kwargs)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {})[0]


def _on_board(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


@pytest.mark.cr("702.49a", "113.6j")
def test_ninjutsu_is_its_rules_text_and_a_hand_ability():
    """CR 702.49a's sentence, word for word, and an ability that functions
    only from a hand: offered there, never on the battlefield (CR 113.6j — a
    card on the battlefield is in no hand to be revealed from)."""
    assert expand_ninjutsu_line("Ninjutsu {2}{B} (reminder.)") == (
        NINJUTSU_RULES_TEXT.format(cost="{2}{B}")
    )
    program = compile_card_oracle(_ninja())
    assert program.supported, program.reason
    assert len(usable_activated_abilities(program, zone=HAND)) == 1
    assert usable_activated_abilities(program, zone=BATTLEFIELD) == []


@pytest.mark.cr("702.49a", "509.1h")
def test_ninjutsu_is_unpayable_before_blockers_are_declared():
    """Declared, the Runner is attacking but neither blocked nor unblocked
    (CR 509.1h), so the cost has nothing to return and the activation is
    refused with nothing paid; once the empty declaration is locked in, the
    same Runner pays."""
    game, runners, _ = _table()
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    refused = game.activate_from_hand(0, "Test Shinobi")
    assert not refused.supported
    assert "return" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Test Shinobi"]
    assert _on_board(game, 0, "Runner 0") is runners[0]

    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {})[0]
    assert game.activate_from_hand(0, "Test Shinobi").supported


@pytest.mark.cr("509.1h", "601.2h")
def test_only_an_unblocked_attacker_pays_the_return():
    """A blocked attacker is no "unblocked attacking creature": named, the
    activation is refused (CR 601.2h — a named payment that cannot be made is
    no payment), and with only blocked attackers there is nothing to name."""
    wall = _mk_creature_card("Wall", 0, 4)
    game, runners, defenders = _table(runners=2, theirs=[wall])
    assert game.declare_attackers(0, [0, 1], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: 0})[0]
    assert runners[0].blocked and not runners[1].blocked

    named = game.activate_from_hand(
        0, "Test Shinobi", cost_permanent_ids=[runners[0].permanent_id],
    )
    assert not named.supported
    assert _on_board(game, 0, "Runner 0") is runners[0]
    assert game.activate_from_hand(
        0, "Test Shinobi", cost_permanent_ids=[runners[1].permanent_id],
    ).supported
    assert sorted(c.name for c in game.players[0].hand) == ["Runner 1", "Test Shinobi"]

    game2, runners2, _ = _table(runners=1, theirs=[wall])
    assert game2.declare_attackers(0, [0], defending_player_index=1)[0]
    game2._set_phase_and_step("combat", "declare_blockers")
    assert game2.declare_blockers(1, {0: 0})[0]
    assert not game2.activate_from_hand(0, "Test Shinobi").supported


@pytest.mark.cr("702.49a", "702.49b", "508.4d")
def test_the_ninja_enters_tapped_attacking_and_unblocked_and_deals_its_damage():
    """The cost returns the Runner and reveals the card, which stays in the
    hand until the ability resolves (CR 702.49b); then it is on the
    battlefield tapped, attacking P2 and unblocked (CR 508.4d), and its 3
    combat damage is dealt where the Runner's 2 would have been."""
    game, runners, _ = _table()
    _attack_and_declare_no_blocks(game, [0])
    reveals_before = len(game.reveal_events)
    assert game.activate_from_hand(0, "Test Shinobi").supported
    assert sorted(c.name for c in game.players[0].hand) == ["Runner 0", "Test Shinobi"]
    assert game.reveal_events[-1]["cards"] == ["Test Shinobi"]
    assert len(game.reveal_events) == reveals_before + 1
    settle(game)
    ninja = _on_board(game, 0, "Test Shinobi")
    assert ninja is not None and ninja.tapped and ninja.attacking
    assert not ninja.blocked and ninja.defending_player_index == 1
    assert [c.name for c in game.players[0].hand] == ["Runner 0"]

    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    settle(game)
    assert game.players[1].life == 17


@pytest.mark.cr("702.49c", "508.1b", "306.8")
def test_the_ninja_attacks_the_planeswalker_the_returned_creature_attacked(set_pool):
    """CR 702.49c: "enters the battlefield attacking the same player,
    planeswalker, or battle as the creature that was returned" — a Runner
    sent at P2's Basri Ket is swapped, and the Ninja's 3 is dealt to Basri,
    not to P2."""
    game, runners, _ = _table()
    basri = Permanent(card=set_pool("M21")["Basri Ket"])
    game._put_permanent_onto_battlefield(1, basri, None)
    assert basri.metadata.get("loyalty_counters") == 3
    _attack_and_declare_no_blocks(
        game, [0], attacker_planeswalker_ids={0: basri.permanent_id},
    )
    assert game.activate_from_hand(0, "Test Shinobi").supported
    settle(game)
    ninja = _on_board(game, 0, "Test Shinobi")
    slot = game.battlefield_index_of(ninja)
    assert game.combat_attacked_planeswalkers.get(slot) == basri.permanent_id
    assert game.combat_attackers.get(slot) == 1

    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    settle(game)
    # Three damage to a three-loyalty walker (CR 306.8, 704.5i): Basri is
    # gone, and P2 took none of it.
    assert game.players[1].life == 20
    assert not any(p is basri for p in game.controlled_by(1))


@pytest.mark.cr("508.4")
def test_the_ninja_was_never_declared_so_no_attack_trigger_fires(set_pool):
    """CR 508.4: a creature put onto the battlefield attacking is "attacking"
    but never "attacked". Righteous Cause gains P1 a life for the Runner's
    declaration and none for the Ninja's entry (the 2021-03-19 ruling)."""
    game, runners, _ = _table(mine=[set_pool("ONS")["Righteous Cause"]])
    _attack_and_declare_no_blocks(game, [0])
    settle(game)
    assert game.players[0].life == 21
    assert game.activate_from_hand(0, "Test Shinobi").supported
    settle(game)
    assert _on_board(game, 0, "Test Shinobi").attacking
    assert game.players[0].life == 21


@pytest.mark.cr("400.7", "702.49a", "601.2h")
def test_a_ninja_that_left_the_hand_does_not_enter_and_the_cost_stays_paid():
    """"If it leaves your hand before then, it won't enter the battlefield at
    all" (2021-03-19): discarded in response, the card is a new object in the
    graveyard (CR 400.7) and the ability puts nothing anywhere — while the
    Runner, returned as a cost (CR 601.2h), stays returned."""
    game, runners, _ = _table()
    _attack_and_declare_no_blocks(game, [0])
    assert game.activate_from_hand(0, "Test Shinobi").supported
    card = next(c for c in game.players[0].hand if c.name == "Test Shinobi")
    assert game.take_card_from_hand(game.players[0], card)
    game._discard_card(game.players[0], card)
    settle(game)
    assert _on_board(game, 0, "Test Shinobi") is None
    assert [c.name for c in game.players[0].graveyard] == ["Test Shinobi"]
    assert [c.name for c in game.players[0].hand] == ["Runner 0"]


@pytest.mark.cr("510.4", "702.49a")
def test_activated_in_the_first_strike_step_the_ninja_deals_regular_damage(set_pool):
    """"If a creature in combat has first strike or double strike, you can
    activate the ninjutsu ability during the first-strike combat damage step.
    The Ninja will deal combat damage during the regular combat damage step"
    (2021-03-19): White Knight deals its 2 first, is swapped, and the Ninja's 3
    arrives with the Runner's 2 in the second step (CR 510.4)."""
    game, runners, _ = _table(mine=[set_pool("LEA")["White Knight"]])
    knight = _on_board(game, 0, "White Knight")
    _attack_and_declare_no_blocks(game, [0, 1])
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    settle(game)
    assert game.combat_first_strike_done and game.players[1].life == 18
    assert game.activate_from_hand(
        0, "Test Shinobi", cost_permanent_ids=[knight.permanent_id],
    ).supported
    settle(game)
    game.resolve_combat_damage(0)
    settle(game)
    assert game.players[1].life == 18 - 3 - 2


@pytest.mark.cr("509.1h")
def test_mirror_strike_names_no_unblocked_creature_before_blockers_are_declared(set_pool):
    """The clock ninjutsu reads is every "unblocked"'s: "target unblocked
    creature" (Mirror Strike) offers no attacker in the declare attackers
    step — nothing is unblocked yet (CR 509.1h) — and the same attacker once
    the empty declaration is made."""
    strike = set_pool("PCY")["Mirror Strike"]
    game, runners, _ = _table(hand=[])
    game.players[1].hand.append(strike)
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    spec = game.cast_target_spec(1, strike)
    assert [t["name"] for t in spec.get("valid_targets", [])] == []
    assert not game.cast_from_hand(
        1, "Mirror Strike", target_permanent_ids=[runners[0].permanent_id],
    ).supported

    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {})[0]
    spec = game.cast_target_spec(1, strike)
    assert [t["name"] for t in spec["valid_targets"]] == ["Runner 0"]
