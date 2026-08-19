"""Tests for Magic: The Gathering Comprehensive Rules Section 504.

Covers:
  504.1 — The active player draws a card as a turn-based action, and effects
          may add to what that step draws

These pin the *derivation* of the symmetric bonus-draw template from oracle
text (engine/draw_step_modifiers.py), which replaced a name-keyed entry. The
point of the change is that a card the engine has never seen works as long as
it uses the printed template, so these use invented card names — a test naming
Howling Mine could pass against a lookup keyed by "Howling Mine". The real card
is covered by the set suite.
"""

import pytest

from engine.draw_step_modifiers import draw_step_bonus_for


@pytest.mark.cr("504.1")
def test_504_1_symmetric_bonus_draw_is_derived_from_its_template():
    """"At the beginning of each player's draw step, that player draws an
    additional card." — the Howling Mine family, without the untapped clause."""
    bonus = draw_step_bonus_for(
        "At the beginning of each player's draw step, that player draws an additional card."
    )

    assert bonus is not None
    assert (bonus.count, bonus.requires_untapped) == (1, False)


@pytest.mark.cr("504.1")
def test_504_1_untapped_qualifier_is_recognized():
    """Howling Mine's own wording gates the bonus on the source being
    untapped, so tapping it turns the bonus off."""
    bonus = draw_step_bonus_for(
        "At the beginning of each player's draw step, if this artifact is "
        "untapped, that player draws an additional card."
    )

    assert (bonus.count, bonus.requires_untapped) == (1, True)


@pytest.mark.cr("504.1")
def test_504_1_bonus_size_is_read_from_the_text():
    """A card printed with a larger bonus needs no registration — the count
    comes from the wording, not from a per-card table."""
    bonus = draw_step_bonus_for(
        "At the beginning of each player's draw step, that player draws two additional cards."
    )

    assert bonus.count == 2


@pytest.mark.cr("504.1")
def test_504_1_asymmetric_and_unrelated_draw_text_grants_no_bonus():
    """The template is specifically the symmetric "each player" one. A bonus
    that applies to a single player, or text that merely mentions the draw
    step, must not be read as one — the draw step adds this to *every*
    player's draw."""
    for text in (
        "At the beginning of your draw step, you draw an additional card.",
        "At the beginning of each opponent's draw step, that player draws an additional card.",
        "If you would draw a card during your draw step, instead you may skip that draw.",
        "At the beginning of each player's draw step, that player loses 1 life.",
        "Draw a card.",
        "",
    ):
        assert draw_step_bonus_for(text) is None, text


# ---------------------------------------------------------------------------
# 504.2 / 603.3 — the step's triggered abilities
# ---------------------------------------------------------------------------
#
# Invented cards again, and for the same reason: the point is that the *scope*
# a card prints decides who fires, so a test naming Mana Vault or Armageddon
# Clock could pass against anything keyed to those names.

from engine import Game, PlayerState  # noqa: E402
from engine.models import CardDefinition, Permanent  # noqa: E402


def _clock(name: str, text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line="Artifact",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Artifact"},
    )


def _two_seat_game(*permanents_for_seat_zero: Permanent) -> tuple[Game, PlayerState, PlayerState]:
    p1 = PlayerState(name="P1", battlefield=list(permanents_for_seat_zero), library=[])
    p2 = PlayerState(name="P2", library=[])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.turn = 3  # past CR 103.8a's first-turn draw skip
    game._sync_control()
    return game, p1, p2


@pytest.mark.cr("504.2", "603.3")
def test_504_2_a_draw_step_trigger_reaches_the_stack_and_resolves():
    """"At the beginning of your draw step, …" had no dispatcher at all: the
    step drew a card and opened priority, and any trigger the compiler produced
    for it sat in the program unfired."""
    game, p1, _p2 = _two_seat_game(Permanent(card=_clock(
        "Dawn Toll", "At the beginning of your draw step, it deals 1 damage to you."
    )))

    game.resolve_draw_step(0)

    assert p1.life == 19


@pytest.mark.cr("504.2", "603.4")
def test_603_4_a_draw_step_trigger_with_an_intervening_if_checks_it():
    """The gate is checked as the trigger would fire, so the state at the start
    of the step is what decides — not the state at resolution alone."""
    text = "At the beginning of your draw step, if this artifact is tapped, it deals 1 damage to you."
    tapped = Permanent(card=_clock("Toll of Rust", text), tapped=True)
    game, p1, _p2 = _two_seat_game(tapped)
    game.resolve_draw_step(0)
    assert p1.life == 19

    untapped = Permanent(card=_clock("Toll of Rust", text))
    game, p1, _p2 = _two_seat_game(untapped)
    game.resolve_draw_step(0)
    assert p1.life == 20


@pytest.mark.cr("504.2", "603.3")
def test_504_2_your_draw_step_and_each_players_draw_step_are_different_scopes():
    """The narrowing is the whole difference between the two conditions: "your"
    fires only on its controller's step, "each player's" on everyone's. One
    kind for both would make the dispatcher guess, which is the mistake the end
    step made until a card printed the other wording."""
    yours = Permanent(card=_clock(
        "Dawn Toll", "At the beginning of your draw step, it deals 1 damage to you."
    ))
    game, p1, p2 = _two_seat_game(yours)

    game.active_player_index = 1
    game.resolve_draw_step(1)

    assert (p1.life, p2.life) == (20, 20), "the opponent's draw step is not 'your' draw step"
