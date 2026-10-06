"""The gating re-cast loop, measured where it was reported: in simulated games.

"When this creature enters, return a red or green creature you control to its
owner's hand" — Planeshift's gating, Shrieking Drake's unnarrowed original and
Natural Emergence's enchantment form. The entering permanent is itself a legal
answer, so cast onto a board with nothing else its noun admits it comes
straight back, and a seat that does not read that casts it again next turn.

Three wave-1 groups reported three different numbers for this because they
measured three different trees (W1G5 and W1G3: "Natural Emergence cast 15 times
in six games, Doomsday Specter returning itself on 102 of 112 casts, Sawtooth
Loon 138 of 147"; W1G2, on its own branch: "zero self-returns in 9 simulated
games"). Re-measured on the merged tree with all fourteen pinned, five at a
time, over 54 games: **132 casts, 0 self-returns, 0 returns of a dearer
permanent, and no seat casting one gater more than twice in a game** — W1G2's
derivation (``ai_valuation.entry_self_return_gate``, read by the cast gate and
the headless pick) covers the enchantment gater and the five gaters with a
second entry trigger, which were the ones most likely to have fallen between
the two fixes. The same census with that gate switched off counts 281
self-returns in 343 casts over 18 games, so it does name the defect.

``tests/ai/test_entry_trigger_choices.py`` holds the derivation card by card on
built boards. This file is the other half: the games themselves, on the three
cards the reports singled out.

**What the re-measurement did find is the loop's last form.** Two gaters of
*equal* cost whose nouns admit each other: Sawtooth Loon ({2}{W}{U}, "a white
or blue creature") and Doomsday Specter ({2}{U}{B}, "a blue or black
creature") are each a blue four-drop, so with nothing else on the board each
cast gives the other back and the seat exchanges them every turn. The gate
compared what goes back against what comes in with ``>``, which an even swap
passes. It is declined now only where the permanent given back is itself a
gate that admits the card being cast — an even swap for anything else develops
the board a turn later.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.ai_policy import _cast_candidate
from engine.ai_simulator import run_ai_simulation
from engine.ai_valuation import entry_self_return_gate
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.models import Permanent

#: The enchantment gater and the two with a second entry trigger the wave-1
#: reports counted by name.
_PINNED = ("Natural Emergence", "Doomsday Specter", "Sawtooth Loon")
#: Accepted casts of the pinned cards the run has to contain to mean anything.
#: Measured at 13 on the tree this was written on; a seed moved by a later AI
#: change may deal fewer, and three is still a run in which the gate was asked.
_CAST_FLOOR = 3


@pytest.mark.slow
def test_w2g5_no_simulated_seat_casts_a_gater_to_return_itself():
    """Six seeded Planeshift games with the three pinned into every deck: no
    pinned permanent returns itself, and no seat casts one of them more than
    twice in a game."""
    path = manifest_set_path("PLS", include_measured=True)
    gates = {
        card.name for card in load_cards([path])
        if entry_self_return_gate(card) is not None
    }
    assert set(_PINNED) <= gates, sorted(gates)

    report = run_ai_simulation(
        [path], games=6, seed=1337, max_turns=18, required_cards=_PINNED,
    )
    assert not report.issues, report.issues[:3]
    assert not report.steps_left_owing, report.steps_left_owing

    casts: Counter = Counter()
    self_returns = []
    for line in report.log_lines:
        cast = re.match(r"G(\d+) T\d+ (\S+) cast (.+?) -> resolved", line)
        if cast and cast.group(3) in _PINNED:
            casts[(cast.group(1), cast.group(2), cast.group(3))] += 1
        back = re.match(r"(.+?) returned (.+?) to hand$", line.strip())
        if back and back.group(1) in gates and back.group(1) == back.group(2):
            self_returns.append(line.strip())

    assert self_returns == []
    assert sum(casts.values()) >= _CAST_FLOOR, casts
    assert max(casts.values()) <= 2, casts.most_common(3)


def _w2g5_gate_board(hand_name, *others) -> tuple:
    pool: dict = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        pool.setdefault(card.name, card)
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("AI", library=[forest] * 30, hand=[pool[hand_name]]),
        PlayerState("Other", library=[forest] * 30),
    ])
    game.enforce_mana_costs = False
    for name in others:
        game._put_permanent_onto_battlefield(0, Permanent(card=pool[name]), None)
    return game, pool[hand_name]


def test_w2g5_two_equal_gaters_are_not_exchanged_for_each_other():
    """Sawtooth Loon beside nothing but a Doomsday Specter: the Specter is the
    only creature the Loon's gate admits, costs the same four mana, and is a
    gate that would give the Loon straight back. Not proposed, either way
    round."""
    game, loon = _w2g5_gate_board("Sawtooth Loon", "Doomsday Specter")
    assert _cast_candidate(game, 0, loon, 0) is None
    game, specter = _w2g5_gate_board("Doomsday Specter", "Sawtooth Loon")
    assert _cast_candidate(game, 0, specter, 0) is None


def test_w2g5_an_even_swap_for_a_creature_that_is_no_gate_is_still_cast():
    """…and beside a vanilla blue four-drop the same Loon is cast: the creature
    it gives back is recast next turn and returns nothing, so the board grows."""
    game, loon = _w2g5_gate_board("Sawtooth Loon", "Wishcoin Crab")
    action = _cast_candidate(game, 0, loon, 0)
    assert action is not None and action.card_name == "Sawtooth Loon"
    # …as it is with something cheaper to give back beside the other gater.
    game, loon = _w2g5_gate_board("Sawtooth Loon", "Doomsday Specter", "Merfolk of the Pearl Trident")
    assert _cast_candidate(game, 0, loon, 0) is not None
