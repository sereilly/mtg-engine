"""An instant naming several **roles** is announced role by role at instant
speed too.

``ai_policy.choose_cast_action`` (the main-phase chooser) has answered a roles
spell through ``_choose_role_targets`` since Glyph of Delusion. The
instant-speed chooser (``choose_combat_instant_cast_action`` — the declare-
blockers window and the web AI's priority response) asked only the one-object
question, which a roles spell answers "not mine", so it proposed the card with
no targets at all:

    Shower of Sparks, an opposing Grizzly Bears, any instant-speed window
      -> proposed with a seat and nothing else,
         refused "Shower of Sparks requires 2 targets",
         proposed again at the next window.

Nothing is spent by a refused cast (CR 601.2c), which is why it was silent;
the seat simply never cast the card at instant speed. Five shipped instants are
roles as printed and two more when kicked. Found driving Apocalypse's
Suffocating Blast, whose spell role makes this the only chooser that ever sees
a legal announcement of it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, ai_policy
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, spec_roles

#: The shipped instants whose printed announcement is roles, with a board each
#: can be announced on. ``blocked`` marks the one whose second role is settled
#: by a block that happened this turn.
_ROLES_INSTANTS = ("Lunge", "Shower of Sparks", "Withdraw")


@pytest.fixture(scope="module")
def _by_name():
    return {card.name: card for card in load_catalog()}


def _response_window(by_name, name):
    """Seat 0 holds *name* in seat 1's turn, a creature on each board."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    for seat, creature in ((0, "Hill Giant"), (1, "Grizzly Bears"), (1, "Scryb Sprites")):
        permanent = Permanent(card=by_name[creature])
        permanent.metadata["summoning_sickness_turn"] = -99
        game.players[seat].battlefield.append(permanent)
    game._sync_control()
    game.active_player_index = 1
    game.players[0].hand = [by_name[name]]
    return game


@pytest.mark.parametrize("name", _ROLES_INSTANTS)
def test_these_are_roles_instants(_by_name, name):
    card = _by_name[name]
    assert card.primary_type == "instant"
    assert spec_roles(derive_cast_spec(card, compile_card_oracle(card)))


@pytest.mark.parametrize("name", _ROLES_INSTANTS)
def test_the_instant_chooser_proposes_a_roles_instant_the_engine_takes(_by_name, name):
    """Whatever it proposes for a roles instant names one target per role, and
    the cast gate accepts the announcement."""
    game = _response_window(_by_name, name)

    action = ai_policy.choose_combat_instant_cast_action(game, 0)

    assert action is not None and action.card_name == name
    announced = ai_policy.cast_announcement(action)
    assert len(announced["target_permanent_ids"]) == 2
    result = game.queue_from_hand(0, name, **announced)
    assert result.supported, result.details


def test_the_proposal_was_bare_before_the_chooser_asked_for_roles(_by_name, monkeypatch):
    """The backwards half: with the roles question taken away, Shower of Sparks
    is proposed naming no permanent and the engine refuses it for the count."""
    monkeypatch.setattr(ai_policy, "_choose_role_targets", lambda *args, **kwargs: None)
    game = _response_window(_by_name, "Shower of Sparks")

    action = ai_policy.choose_combat_instant_cast_action(game, 0)

    assert action is not None
    announced = ai_policy.cast_announcement(action)
    assert announced["target_permanent_ids"] is None
    refused = game.queue_from_hand(0, "Shower of Sparks", **announced)
    assert not refused.supported and "requires 2 targets" in refused.details
