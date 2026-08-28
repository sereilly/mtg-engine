"""The AI must not propose a cast the engine will refuse.

Not a rules failure — the cast gate declines before any mana is spent (CR
601.2c), so nothing is lost and nothing crashes. It is a *silent* failure, and
it repeats: ``choose_cast_action`` re-proposes the same card the next turn and
the next, so a seat holding one does nothing for the rest of the game. Four
shapes of it were live, all found the day the simulator started dealing whole
sets instead of one eight-card list, and none was reachable before that.

The fix in each case was to ask the gate the cast path already asks rather than
to add another arm to ``_can_cast_with_targets``' if-chain — the chain is what
let them through, since every instruction kind it does not name fell out of the
bottom as "castable".
"""

from __future__ import annotations

import pytest

from engine.ai_policy import choose_cast_action
from engine.auras import attach_aura
from engine.game import Game
from engine.models import Permanent, PlayerState


def _board(hand, own=(), opposing=()):
    p1 = PlayerState(name="P1", hand=list(hand))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.turn = 5
    for card in own:
        perm = Permanent(card=card)
        p1.battlefield.append(perm)
        game._initialize_permanent_state(perm, 0, None)
    for card in opposing:
        perm = Permanent(card=card)
        p2.battlefield.append(perm)
        game._initialize_permanent_state(perm, 1, None)
    return game, p1, p2


def _proposes(game, name):
    action = choose_cast_action(game, 0)
    return action is not None and action.card_name == name


def test_it_declines_a_spell_whose_kind_the_if_chain_never_named(catalog_by_name):
    """Deathlace ("target spell or permanent becomes black") lowers to
    ``recolor_target_from_text``, a kind with no arm, so it was proposed every
    turn against an empty board and refused every turn."""
    game, _p1, _p2 = _board([catalog_by_name["Deathlace"]])
    assert not _proposes(game, "Deathlace")


def test_it_casts_that_same_spell_once_there_is_a_target(catalog_by_name):
    """The other half — a gate that refuses everything is not a fix."""
    game, _p1, _p2 = _board(
        [catalog_by_name["Deathlace"]], opposing=[catalog_by_name["Grizzly Bears"]]
    )
    assert _proposes(game, "Deathlace")


def test_it_reads_a_narrowing_the_arm_ignores(catalog_by_name):
    """Tunnel destroys target **Wall**. Its arm reads ``type_filter`` alone,
    sees "creature", and answers yes to any creature at all; ``wall_only`` is
    the narrowing only the engine's own enumeration applies."""
    game, _p1, _p2 = _board(
        [catalog_by_name["Tunnel"]], opposing=[catalog_by_name["Grizzly Bears"]]
    )
    assert not _proposes(game, "Tunnel")


def test_it_casts_that_spell_when_the_narrowing_is_satisfied(catalog_by_name):
    game, _p1, _p2 = _board(
        [catalog_by_name["Tunnel"]], opposing=[catalog_by_name["Wall of Stone"]]
    )
    assert _proposes(game, "Tunnel")


def test_it_declines_an_aura_whose_target_has_protection(catalog_by_name):
    """CR 702.16b. The Aura picker asked ``forbidden_target`` and stopped
    there, so a white Aura was aimed at a creature wearing White Ward — chosen,
    refused, chosen again."""
    game, p1, _p2 = _board(
        [catalog_by_name["Lance"]], own=[catalog_by_name["Benalish Hero"]]
    )
    ward = Permanent(card=catalog_by_name["White Ward"])
    p1.battlefield.append(ward)
    game._initialize_permanent_state(ward, 0, None)
    attach_aura(ward, p1.battlefield[0])

    assert not _proposes(game, "Lance")


def test_it_declines_a_spell_its_printed_timing_forbids(catalog_by_name):
    """Siren's Call is castable "only during an opponent's turn", and this
    headless loop only ever offers the active player a cast, so it can never be
    legal — it was proposed on ten consecutive turns."""
    game, _p1, _p2 = _board([catalog_by_name["Siren's Call"]])
    assert not _proposes(game, "Siren's Call")


def test_it_declines_a_card_a_lockout_bans(catalog_by_name):
    """City in a Bottle: "Players can't cast Arabian Nights cards." Not a
    targeting question at all, and the same failure."""
    game, _p1, p2 = _board(
        [catalog_by_name["Brass Man"]], opposing=[catalog_by_name["City in a Bottle"]]
    )
    assert not _proposes(game, "Brass Man")


@pytest.mark.parametrize("code", ("LEA", "ARN", "ATQ", "3ED", "LEG", "DRK", "4ED", "M21"))
def test_a_batch_over_every_set_proposes_no_refused_cast(code, set_cards):
    """The end-to-end statement, and the one that would catch a fifth shape.

    ``refused_casts`` counts casts the engine declined for a rules reason; the
    AI should never produce one, because it can ask every gate the cast path
    asks before it commits the turn.
    """
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    report = run_ai_simulation(
        cards_path=manifest_set_path(code), games=2, seed=99, max_turns=12
    )
    assert not report.refused_casts, dict(report.refused_casts)
    # And the run has to have *done* something: a batch where nobody could pay
    # for anything produces no refusals either, and would pass the line above
    # while proving nothing.
    assert report.interaction_count > 0
    assert not report.issues, [i.message for i in report.issues]
