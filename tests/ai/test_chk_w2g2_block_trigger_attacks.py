"""The attack reads the fight a block would be, its block triggers included.

``choose_attackers`` asked the printed bodies whether the defender's best block
was profitable, so a creature whose own trigger wins the fight it would be
blocked into stayed home: Samurai Enforcers' bushido 2 (CR 702.45a) makes it a
6/6 the moment a Shivan Dragon blocks it, and the seat declined the attack the
blocks would have lost (CHK W1G2). The defender has read the fight through
``ai_compelled_blocks.fight_outcome`` since LGN; the attack now asks the same
(``ai_declarations._attack_block_score``). Chub Toad (shipped) is the same
shape without the keyword: "Whenever this creature blocks or becomes blocked,
it gets +2/+2 until end of turn."
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_declarations import choose_attackers
from engine.models import Permanent


def _w2g2_attack_choice(attacker_card, blocker_card) -> list[int]:
    attacker = Permanent(card=attacker_card)
    blocker = Permanent(card=blocker_card)
    for perm in (attacker, blocker):
        perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker], life=20),
        PlayerState(name="P2", battlefield=[blocker], life=20),
    ])
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    return choose_attackers(game, 0)


def test_samurai_enforcers_attacks_into_the_dragon_its_bushido_beats(set_pool):
    """4/4 bushido 2 against a 5/5: blocked, it is a 6/6 that kills the
    Dragon and lives."""
    chosen = _w2g2_attack_choice(
        set_pool("CHK")["Samurai Enforcers"], set_pool("LEA")["Shivan Dragon"],
    )
    assert chosen == [0]


def test_a_creature_whose_bushido_does_not_win_still_stays_home(set_pool):
    """Bushido 1 is not enough: Ronin Houndmaster (2/2 haste, bushido 1) is a
    3/3 blocked by a 5/5 Shivan Dragon and dies for nothing."""
    chosen = _w2g2_attack_choice(
        set_pool("CHK")["Ronin Houndmaster"], set_pool("LEA")["Shivan Dragon"],
    )
    assert chosen == []


def test_chub_toad_attacks_into_the_bears_its_trigger_beats(set_pool):
    """A 1/1 that is a 3/3 once blocked: the Bears' block kills nothing and
    loses the Bears."""
    chosen = _w2g2_attack_choice(
        set_pool("ICE")["Chub Toad"], set_pool("LEA")["Grizzly Bears"],
    )
    assert chosen == [0]


def test_a_first_striker_blocked_by_two_kills_the_one_that_would_kill_it(set_pool):
    """Kitsune Blademaster (2/2 first strike, bushido 1) blocked by a 1/1 and
    a 3/3 is a 3/3 first striker: its three damage on the 3/3 leaves only the
    1/1's one point coming back, and it lives. The engine's default division
    kills the 1/1 first and puts two on the 3/3, which then kills it; the AI's
    division is the one the defender's forecast (``_gang_kills``) expects."""
    from engine.ai_combat import choose_combat_damage_announcement
    from tests.helpers import _mk_creature_card, drive_combat

    blademaster = Permanent(card=set_pool("CHK")["Kitsune Blademaster"])
    small = Permanent(card=_mk_creature_card("Vanilla 1/1", 1, 1))
    big = Permanent(card=_mk_creature_card("Vanilla 3/3", 3, 3))
    for perm in (blademaster, small, big):
        perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[blademaster], life=20),
        PlayerState(name="P2", battlefield=[small, big], life=20),
    ])
    game._sync_control()
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0, 1: 0})
    assert ok, why
    for _ in range(4):
        try:
            drive_combat(game)
            break
        except AssertionError as stuck:
            if "combat damage assignment" not in str(stuck):
                raise
            ok, why = game.resolve_combat_damage(0, **choose_combat_damage_announcement(game))
            assert ok, why
    assert game.is_on_battlefield(blademaster), game.log[-10:]
    assert not game.is_on_battlefield(big)
    assert game.is_on_battlefield(small)
