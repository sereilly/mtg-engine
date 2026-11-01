"""The AI's two provoke decisions (``engine/ai_compelled_blocks.py``) and a
seeded Legions game that makes them.

Provoke's target is chosen as the trigger is put on the stack (CR 603.3d) and
its "may" is answered as it resolves, so a seat nobody asks makes two choices
about one pair: which creature, and whether. Both are read off the fight the
pair would have — first strike in its own step, deathtouch, indestructible —
and off the compiled program rather than the keyword.
"""

from __future__ import annotations

from engine.ai_compelled_blocks import (best_compelled_blocker,
                                        compelled_block_worth,
                                        compels_a_block_on_source,
                                        fight_outcome)
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.game import Game
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.provoke import provoke_instruction

from tests.helpers import _mk_creature_card


def _creature(name, power, toughness, text=""):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text=text, colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _board(attacker_card, *blocker_cards):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    attacker = Permanent(card=attacker_card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    blockers = []
    for card in blocker_cards:
        perm = Permanent(card=card)
        game._put_permanent_onto_battlefield(1, perm, None)
        blockers.append(perm)
    game.check_state_based_actions()
    return game, attacker, blockers


def test_a_provoke_trigger_and_a_printed_compulsion_read_the_same():
    """The reader is the program, not the word: provoke's instruction and a
    printed "Target creature blocks this creature this turn if able" both
    compel their target to block their source; an untap alone does not."""
    assert compels_a_block_on_source(provoke_instruction())
    armodon = _creature(
        "Armodon Test", 3, 3, "{1}{G}: Target creature blocks this creature this turn if able."
    )
    ability = compile_card_oracle(armodon).activated_abilities[0]
    assert compels_a_block_on_source(ability.instruction)
    untapper = _creature(
        "Untap Test", 1, 1, "Whenever this creature attacks, untap target creature."
    )
    trigger = compile_card_oracle(untapper).triggered_abilities[0]
    assert not compels_a_block_on_source(trigger.instruction)


def test_the_fight_is_read_in_its_two_steps():
    """CR 510.4: a first striker that kills its blocker is never struck back;
    without first strike the two trade; deathtouch is lethal at one point
    (CR 702.2c); indestructible survives anything."""
    game, tracker, (bear,) = _board(
        _creature("Striker", 2, 2, "First strike"), _mk_creature_card("Bear", 2, 2),
    )
    assert fight_outcome(game, tracker, bear) == (True, False)
    game, plain, (bear,) = _board(_mk_creature_card("Plain", 2, 2), _mk_creature_card("Bear", 2, 2))
    assert fight_outcome(game, plain, bear) == (True, True)
    game, plain, (asp,) = _board(
        _mk_creature_card("Plain", 4, 4), _creature("Asp", 1, 1, "Deathtouch"),
    )
    assert fight_outcome(game, plain, asp) == (True, True)
    game, plain, (wall,) = _board(
        _mk_creature_card("Plain", 9, 9), _creature("Hard Wall", 0, 1, "Indestructible"),
    )
    assert fight_outcome(game, plain, wall) == (False, False)


def test_the_target_is_the_creature_the_attacker_gains_most_from_fighting():
    """A 3/3 attacker over a 0/4 it cannot hurt, a 3/3 it trades with and a
    2/2 it kills and survives: the 2/2. A creature it cannot block at all
    (no flying against a flier) is worth less than nothing — it is untapped
    to block somebody else."""
    game, ogre, (wall, twin, bear) = _board(
        _mk_creature_card("Ogre", 3, 3),
        _mk_creature_card("Wall", 0, 4), _mk_creature_card("Twin", 3, 3),
        _mk_creature_card("Bear", 2, 2),
    )
    assert best_compelled_blocker(game, ogre, [wall, twin, bear]) is bear
    assert compelled_block_worth(game, ogre, wall) < 0
    game, bird, (bear,) = _board(_creature("Bird", 2, 2, "Flying"), _mk_creature_card("Bear", 1, 1))
    assert compelled_block_worth(game, bird, bear) < 0


def test_a_seeded_legions_game_provokes_and_the_defender_obeys():
    """The provoke cards pinned into both decks: the run completes, at least
    one provoke is taken (a requirement written to the log) and at least one
    is declined, no rehearsal raised, and no block declaration was refused —
    the defending AI obeyed every requirement it was handed. Floors, never
    counts."""
    report = run_ai_simulation(
        manifest_set_path("LGN", include_measured=True), games=3, seed=1337,
        required_cards=[
            "Goblin Grappler", "Lowland Tracker", "Krosan Vorine", "Hunter Sliver",
            "Brontotherium", "Deftblade Elite", "Swooping Talon", "Crested Craghorn",
        ],
    )
    assert report.games_completed == 3
    assert any("this combat if able" in line for line in report.log_lines)
    assert any("the block it compels is not worth having" in line for line in report.log_lines)
    assert not report.rehearsals_raised
    assert not report.refused_blocks
