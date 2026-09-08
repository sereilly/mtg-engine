"""Tests for Comprehensive Rules section 733 — Handling Illegal Actions.

CR 733.1 is the rule behind every refusal this engine returns: an action that
turns out to be illegal is *reversed entire*, "and any payments already made are
canceled. No abilities trigger and no effects apply as a result of an undone
action." CR 733.2 is its other half — the refusal is not a pass, so the player
keeps priority and may redo the action legally.

The engine obeys 733.1 mostly **by construction**: ``_activate_onto_stack`` and
``queue_from_hand`` check every cost where it is announced and pay it further
down, so a refusal from any of their forty returns has nothing to give back.
That is a design, not an observation, and this file is where it is observed —
the failure mode of a by-construction invariant is that some later branch pays
first and refuses second, which no guard in this repo would otherwise see.

One card does write before the activation is known to be legal (Phyrexian
Splicer's CR 601.2b chosen keyword, taken back by ``queue_permanent_ability``'s
reversal ledger). That card's own record is covered against its printed line in
``tests/sets/test_tmp_artifacts.py``; what is tested here is the rule rather
than the card.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The whole shipped pool: these tests are about the rule, and the three cards
# they use come from three different sets.
_POOL = {card.name: card for card in load_catalog()}


def _empty_pool() -> dict[str, int]:
    return {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}


def _perm(name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _game(*, hand: list[str] = (), battlefield: list[str] = ()) -> tuple:
    """A game with **mana costs enforced**, which is the point of the file.

    Every other rig in ``tests/rules`` turns enforcement off so a test can get
    to the behaviour it is about. Here the payment *is* the behaviour: a rule
    about payments being canceled cannot be observed in a game that never
    charges any.
    """
    permanents = [_perm(name) for name in battlefield]
    p1 = PlayerState(
        name="P1", hand=[_POOL[name] for name in hand], battlefield=permanents
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True
    game._settle()
    return game, p1, permanents


# ---------------------------------------------------------------------------
# Rule 733.1 — the action is reversed and payments are canceled
# ---------------------------------------------------------------------------


@pytest.mark.cr("733.1")
def test_a_cast_refused_for_want_of_a_target_spends_nothing():
    """Giant Growth with no creature anywhere: "If the action was casting a
    spell, the spell returns to the zone it came from."

    All three ledgers are checked, because a partial reversal is the shape this
    rule guards against — a spell that leaves the hand, or mana that leaves the
    pool, before the target gate refuses.
    """
    game, p1, _ = _game(hand=["Giant Growth"])
    p1.mana_pool = _empty_pool() | {"G": 3}

    result = game.queue_from_hand(0, "Giant Growth")

    assert not result.supported
    assert "no valid target" in result.details
    assert [card.name for card in p1.hand] == ["Giant Growth"]
    assert p1.mana_pool["G"] == 3, "mana was spent on an action that never happened"
    assert not game.stack


@pytest.mark.cr("733.1")
def test_an_activation_refused_for_want_of_a_target_pays_none_of_its_cost():
    """Silent Dart's cost is three payments — {4}, {T} and a sacrifice — and a
    refusal owes all three back.

    The card is the reason ``legality.activation_target_refusal`` exists as one
    gate asked before any cost: an ability with a mandatory object target it
    cannot fill used to be activated anyway and sent at the face.
    """
    game, p1, (dart,) = _game(battlefield=["Silent Dart"])
    p1.mana_pool = _empty_pool() | {"generic": 4}

    result = game.activate_permanent_ability(0, "Silent Dart")

    assert not result.supported
    assert not dart.tapped, "{T} was paid for an activation that was refused"
    assert p1.mana_pool["generic"] == 4
    assert [perm.card.name for perm in game.all_permanents()] == ["Silent Dart"], (
        "the sacrifice half of the cost was paid"
    )
    assert game.players[1].life == 20, "the refused ability dealt its damage anyway"


@pytest.mark.cr("733.1")
def test_no_ability_triggers_from_an_undone_cast():
    """"No abilities trigger ... as a result of an undone action."

    Spellshock watches every cast in the game. The refused announcement must be
    invisible to it — and the second half of the test is the control that makes
    the first half mean something: the *legal* cast does trigger it, so the
    silence above is the reversal rather than a trigger nobody wired up.
    """
    game, p1, _ = _game(hand=["Giant Growth"], battlefield=["Spellshock"])
    p1.mana_pool = _empty_pool() | {"G": 3}

    assert not game.queue_from_hand(0, "Giant Growth").supported
    assert not game.stack, "an undone cast put a trigger on the stack"

    bear = _perm("Grizzly Bears")
    p1.battlefield.append(bear)
    game._settle()
    assert game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[bear.permanent_id]
    ).supported
    assert len(game.stack) == 2, "Spellshock does not watch a legal cast either"


# ---------------------------------------------------------------------------
# Rule 733.2 — the player keeps priority and may take another action
# ---------------------------------------------------------------------------


@pytest.mark.cr("733.2")
def test_the_refused_player_keeps_priority():
    """"the player who had priority retains it and may take another action or
    pass."

    The pass count is asserted beside the seat because that is the way this
    could go wrong without moving the index: a refusal counted as a pass would
    resolve the top of the stack behind the player's back on the opponent's
    next pass.
    """
    game, p1, _ = _game(hand=["Giant Growth"])
    p1.mana_pool = _empty_pool() | {"G": 3}
    game.start_priority_window(0)
    assert game.has_priority(0)

    assert not game.queue_from_hand(0, "Giant Growth").supported

    assert game.priority_player_index == 0
    assert game.has_priority(0)
    assert game.priority_pass_count == 0, "a refused action was counted as a pass"


@pytest.mark.cr("733.2")
def test_the_player_may_redo_the_reversed_action_in_a_legal_way():
    """"The player may redo the reversed action in a legal way" — the same card,
    from the same hand, once a legal target exists."""
    game, p1, _ = _game(hand=["Giant Growth"])
    p1.mana_pool = _empty_pool() | {"G": 3}
    assert not game.queue_from_hand(0, "Giant Growth").supported

    bear = _perm("Grizzly Bears")
    p1.battlefield.append(bear)
    game._settle()

    result = game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[bear.permanent_id]
    )

    assert result.supported, result.details
    assert p1.hand == [], "the redone cast left the card in hand"
    assert p1.mana_pool["G"] == 2, "the redone cast was not charged"
    assert len(game.stack) == 1
