"""Tests for Magic: The Gathering Comprehensive Rules Sections 614 and 701.9.

Covers:
  614.1  — Replacement effects watch for an event and replace it
  614.6  — A replaced event never happens
  701.9a — Discarding moves a card from hand to graveyard...
  701.9c — ...unless an effect puts it into a hidden zone instead

These exercise engine/replacement_choices.py, the channel that lets a
replacement effect which is optional ("you *may*") or offers a choice suspend
its event until the affected player answers. The card-level behavior of Library
of Leng, Aladdin's Lamp and Ring of Ma'rûf lives in the set and regression
suites; this file pins the mechanism, including that registering a brand-new
interactive replacement takes no change to Game, the web layer, or any core
file.
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.replacement_choices import (
    CHOICE_RESOLVERS,
    ReplacementChoice,
    offer_replacement_choice,
    replacement_choice,
)
from engine.replacements import REPLACEMENTS, ReplacementOutcome, replacement_effect


def _card(name: str, type_line: str = "Sorcery", oracle_text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


_LENG_TEXT = (
    "If an effect causes you to discard a card, discard it, but you may put it "
    "on top of your library instead of into your graveyard."
)


def _leng_game(interactive: bool) -> tuple[Game, PlayerState]:
    leng = Permanent(card=_card("Leng-alike", "Artifact", _LENG_TEXT))
    p1 = PlayerState(name="P1", battlefield=[leng])
    game = Game(players=[p1, PlayerState(name="P2")])
    if interactive:
        game.interactive_seats = {0}
    return game, p1


# ---------------------------------------------------------------------------
# Suspending an event on a choice
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.9c", "614.6")
def test_701_9c_a_suspended_discard_leaves_the_card_in_no_zone():
    """The card has left the hand and where it lands is still undecided, so
    until the choice is answered it must be in neither graveyard nor library —
    a card that reached the graveyard "provisionally" could be seen there by a
    graveyard-counting effect and then leave again."""
    game, p1 = _leng_game(interactive=True)
    bears = _card("Bears", "Creature — Bear")

    game._discard_card(p1, bears)

    assert len(game.pending_replacement_choices) == 1
    assert bears not in p1.graveyard
    assert bears not in p1.library


@pytest.mark.cr("701.9c")
def test_701_9c_answering_the_choice_applies_the_replacement():
    game, p1 = _leng_game(interactive=True)
    bears = _card("Bears", "Creature — Bear")
    game._discard_card(p1, bears)

    assert game.resolve_replacement_choice(0, 0) is True

    assert p1.library[0] is bears
    assert game.pending_replacement_choices == []


@pytest.mark.cr("701.9a")
def test_701_9a_declining_the_optional_replacement_uses_the_default_result():
    """The replacement is optional, so the chooser may let the discard resolve
    normally into the graveyard."""
    game, p1 = _leng_game(interactive=True)
    bears = _card("Bears", "Creature — Bear")
    game._discard_card(p1, bears)

    assert game.resolve_replacement_choice(0, 1) is True

    assert bears in p1.graveyard
    assert bears not in p1.library


@pytest.mark.cr("701.9c")
def test_701_9c_a_non_interactive_seat_takes_the_default_immediately():
    """AI and headless play never queue a prompt — the same resolver runs at
    once, so both paths share one completion path."""
    game, p1 = _leng_game(interactive=False)
    bears = _card("Bears", "Creature — Bear")

    game._discard_card(p1, bears)

    assert game.pending_replacement_choices == []
    assert p1.library[0] is bears


@pytest.mark.cr("614.1")
def test_614_1_choices_queue_one_per_event_and_resolve_oldest_first():
    """Several forced discards each get their own choice; answering resolves
    them in the order they were offered."""
    game, p1 = _leng_game(interactive=True)
    first, second = _card("First"), _card("Second")

    game._discard_card(p1, first)
    game._discard_card(p1, second)
    assert len(game.pending_replacement_choices) == 2

    game.resolve_replacement_choice(0, 1)  # graveyard for the oldest
    assert first in p1.graveyard
    assert len(game.pending_replacement_choices) == 1

    game.resolve_replacement_choice(0, 0)  # top of library for the newest
    assert p1.library[0] is second


# ---------------------------------------------------------------------------
# Rejecting answers that don't fit
# ---------------------------------------------------------------------------

@pytest.mark.cr("614.1")
def test_614_1_a_stale_or_malformed_answer_is_rejected():
    """A client answering a choice that isn't queued, an option outside the
    offered range, or another seat's choice must be refused rather than applied
    to whatever happens to be waiting."""
    game, p1 = _leng_game(interactive=True)
    bears = _card("Bears")
    game._discard_card(p1, bears)

    assert game.resolve_replacement_choice(0, 5) is False, "option out of range"
    assert game.resolve_replacement_choice(1, 0) is False, "another seat's choice"
    assert game.resolve_replacement_choice(0, 0, kind="lamp_draw") is False, "wrong kind"
    assert len(game.pending_replacement_choices) == 1, "the choice is still waiting"

    assert game.resolve_replacement_choice(0, 0, kind="leng_discard") is True
    assert game.resolve_replacement_choice(0, 0) is False, "nothing left to answer"


@pytest.mark.cr("614.1")
def test_614_1_auto_resolve_drains_every_queued_choice():
    """The safety net for a seat that stops being interactive takes each
    choice's default until none are left."""
    game, p1 = _leng_game(interactive=True)
    for name in ("A", "B", "C"):
        game._discard_card(p1, _card(name))
    assert len(game.pending_replacement_choices) == 3

    game.auto_resolve_pending_replacement_choices()

    assert game.pending_replacement_choices == []
    assert [c.name for c in p1.library] == ["C", "B", "A"]
    assert p1.graveyard == []


# ---------------------------------------------------------------------------
# The mechanism is genuinely open
# ---------------------------------------------------------------------------

@pytest.mark.cr("614.1")
def test_614_1_a_new_interactive_replacement_needs_only_two_registrations():
    """The point of the channel: supporting a card whose replacement asks the
    player something takes an interceptor and a resolver — no Game field, no
    confirm method, no web plumbing. This registers one at runtime and drives
    it through the generic entry points.
    """
    text = "if you would discard a card, you may exile it instead"

    @replacement_effect(
        "discard",
        99,
        applies=lambda game, payload: game._player_controls_text(payload["player"], text),
    )
    def _exile_instead(game, payload):
        player = payload["player"]
        offer_replacement_choice(
            game,
            ReplacementChoice(
                kind="_test_exile_discard",
                player_index=game.players.index(player),
                options=("exile", "graveyard"),
                default_option=0,
                data={"card": payload["card"]},
            ),
        )
        return ReplacementOutcome(replaced=True)

    @replacement_choice("_test_exile_discard")
    def _resolve_exile(game, choice, option_index):
        player = game.players[choice.player_index]
        card = choice.data["card"]
        (player.exile if option_index == 0 else player.graveyard).append(card)
        return 0

    try:
        source = Permanent(card=_card("Exiler", "Artifact", text.capitalize() + "."))
        p1 = PlayerState(name="P1", battlefield=[source])
        game = Game(players=[p1, PlayerState(name="P2")])
        game.interactive_seats = {0}
        bears = _card("Bears")

        game._discard_card(p1, bears)
        assert game.pending_replacement_choices[0].kind == "_test_exile_discard"
        assert bears not in p1.graveyard

        assert game.resolve_replacement_choice(0, 0) is True
        assert bears in p1.exile
    finally:
        REPLACEMENTS["discard"] = [
            c for c in REPLACEMENTS["discard"] if c.key != "_exile_instead"
        ]
        del CHOICE_RESOLVERS["_test_exile_discard"]


@pytest.mark.cr("614.1")
def test_614_1_two_resolvers_for_one_kind_is_rejected_at_registration():
    """Which resolver applies a choice must not depend on import order — the
    loser would fail silently."""
    with pytest.raises(ValueError, match="already resolved by"):
        replacement_choice("leng_discard")(lambda game, choice, option_index: 0)
