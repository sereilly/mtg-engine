"""Regression: a copy of a spell that chose several modes performs every one.

CR 707.10: a copy "copies both the characteristics of the spell … and all
decisions made for it, including modes, targets"; CR 700.2g: "A copy of a
modal spell or ability copies the mode(s) chosen for it." ``_copy_of_spell``
carried the original's ``chosen_modes``, and the stack's copy arm then
resolved ``chosen_mode_index`` alone — the first chosen mode. A Forked
Sublime Epiphany that bounced a creature and drew a card only bounced; a
Forked entwined One Dozen Eyes (Mirrodin, CR 702.42) made its Beast and none
of its Insects. Found by MRD W1G4 driving entwine's copies.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_M21 = {c.name: c for c in load_cards(manifest_set_path("M21"))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def test_a_forked_sublime_epiphany_performs_every_chosen_mode():
    bear = Permanent(card=_LEA["Grizzly Bears"])
    giant = Permanent(card=_LEA["Hill Giant"])
    game = Game(players=[
        PlayerState("A", hand=[_M21["Sublime Epiphany"], _LEA["Fork"]],
                    library=[_LEA["Forest"]] * 10),
        PlayerState("B", library=[_LEA["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in (bear, giant):
        game._put_permanent_onto_battlefield(1, permanent, None)
    game.start_turn(0)
    game._settle()
    queued = game.queue_from_hand(
        0, "Sublime Epiphany",
        mode_choices=[
            {"index": 2, "target_player_index": 1, "target_permanent_index": 0},
            {"index": 4, "target_player_index": 0},
        ],
    )
    assert queued.supported, queued.details
    forked = game.queue_from_hand(0, "Fork", target_stack_index=0)
    assert forked.supported, forked.details
    resolve_stack(game)
    # The copy bounced the creature the original named (it was still there
    # for the copy, which resolved first) and drew; the original then found
    # its target gone and drew.
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"], game.log
    assert len(game.players[0].hand) == 2, game.log
