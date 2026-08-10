"""Regression tests for the twenty-third batch — CR 613 layer 2 (control).

One cluster, found by wiring the layer rather than by playing:

- **Two control effects on one permanent, ended out of order, handed it to a
  player nothing gave control to.** Control used to be stored *by doing*: the
  thief remembered the seat the permanent came from, and ending the effect
  moved it back to that seat. With Steal Artifact and then Aladdin on the same
  artifact, destroying the Aura first and losing Aladdin second sent the
  artifact to the Aura's controller — who by then controlled nothing that gave
  them the artifact, and who was not its owner either.

  A control change is a recorded contribution now (``engine/control.py``,
  layer 2 via ``engine/layer_bridge.py``), so ending one is *the absence of a
  contribution*: whatever is left applies, in CR 613.7 timestamp order, and if
  nothing is left the permanent returns to the seat it entered under.

- The same storage change fixes CR 108.3 ownership for a twice-stolen
  permanent. The owner used to be read off the thief (``stolen_owner_index``),
  so a second theft overwrote the first one's answer and a dying permanent
  could go to the wrong graveyard.
"""
from __future__ import annotations

import pytest

from engine import PlayerState
from engine.models import CardDefinition, Permanent
from tests.helpers import _game, _nosick
from tests.helpers import CARDS_BY_NAME as _C


def _plain_artifact(name: str = "Test Artifact") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line="Artifact", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Artifact"},
    )


class TestTwoControlEffectsOnOnePermanent:
    def _board(self, arn_by_name):
        """P0 owns an artifact and an Aladdin; P1 holds a Steal Artifact."""
        artifact = Permanent(card=_plain_artifact())
        aladdin = _nosick(Permanent(card=arn_by_name["Aladdin"]))
        p0 = PlayerState(name="P0", battlefield=[artifact, aladdin])
        p1 = PlayerState(name="P1", hand=[_C["Steal Artifact"]])
        game = _game(p0, p1)
        return game, p0, p1, artifact, aladdin

    def _steal_then_take_back(self, arn_by_name):
        game, p0, p1, artifact, aladdin = self._board(arn_by_name)

        assert game.cast_from_hand(
            1, "Steal Artifact", target_player_index=0, target_permanent_index=0
        ).supported
        assert game.controller_index_of(artifact) == 1
        aura = next(p for p in game.controlled_by(1) if p.card.name == "Steal Artifact")

        assert game.activate_permanent_ability(
            0, "Aladdin",
            target_player_index=1,
            target_permanent_index=next(
                i for i, p in enumerate(p1.battlefield) if p is artifact
            ),
        ).supported
        assert game.controller_index_of(artifact) == 0
        return game, p0, p1, artifact, aladdin, aura

    def _destroy(self, game, permanent):
        seat = game.controller_index_of(permanent)
        player = game.players[seat]
        player.battlefield = [p for p in player.battlefield if p is not permanent]
        game._permanent_to_graveyard(player, permanent)
        game.check_state_based_actions()

    def test_losing_both_sources_returns_the_artifact_to_its_owner(self, arn_by_name):
        """The bug. Ending the Aura's effect first and Aladdin's second left the
        artifact with the Aura's controller, who no longer had anything giving
        it to them."""
        game, p0, p1, artifact, aladdin, aura = self._steal_then_take_back(arn_by_name)

        self._destroy(game, aura)
        assert game.controller_index_of(artifact) == 0

        self._destroy(game, aladdin)
        assert game.controller_index_of(artifact) == 0
        assert [p for p in game.controlled_by(0) if p is artifact]

    def test_losing_only_the_newer_source_hands_it_back_to_the_older(self, arn_by_name):
        """Aladdin leaving while Steal Artifact is still attached returns the
        artifact to the Aura's controller — because the Aura's contribution is
        still there, not because anyone remembered a seat."""
        game, p0, p1, artifact, aladdin, aura = self._steal_then_take_back(arn_by_name)

        self._destroy(game, aladdin)
        assert game.controller_index_of(artifact) == 1

    def test_the_owner_is_still_the_owner_after_two_thefts(self, arn_by_name):
        """CR 108.3 / 400.3: ownership is the seat the permanent entered under,
        which two thefts in a row must not overwrite."""
        game, p0, p1, artifact, aladdin, aura = self._steal_then_take_back(arn_by_name)
        assert game.owner_index_of(artifact) == 0


@pytest.mark.parametrize("give_back", [True, False])
def test_a_control_change_marks_summoning_sickness_in_both_directions(give_back):
    """CR 302.6 used to be stamped by each control path separately; it is
    stamped once now, where the permanent actually changes hands."""
    bear = _nosick(Permanent(card=_C["Grizzly Bears"]))
    thief = _nosick(Permanent(card=_C["Grizzly Bears"]))
    p0 = PlayerState(name="P0", battlefield=[bear])
    p1 = PlayerState(name="P1", battlefield=[thief])
    game = _game(p0, p1)
    game.turn = 5

    assert game.take_control(bear, 1, source=thief)
    assert game._is_summoning_sick(bear) is True

    if give_back:
        bear.metadata["summoning_sickness_turn"] = -99
        game.end_control_changes_from(thief)
        assert game.controller_index_of(bear) == 0
        assert game._is_summoning_sick(bear) is True
