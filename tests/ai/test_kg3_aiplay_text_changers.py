"""The text changers an AI seat casts (kg3 `aiplay`, part 1): the words, and
the spell half of "target spell or permanent".

**The defect.** A text change announces its two words with the cast
(``queue_from_hand``'s ``old_color`` / ``new_color``) and no AI module
supplied them, so an AI seat casting Sleight of Mind, Magical Hack, Crystal
Spray, Alter Reality, Mind Bend or Whim of Volrath rewrote nothing — and its
rehearsal, reading a cast that changed nothing, never proposed one. And the
one-object chooser answered "target spell or permanent" from its permanent
half alone, so no text change and no Lace was ever aimed at a spell.

**The fix** (`engine/ai_text_changes.py`): every object the engine offers is
weighed with each pair of words it could name there — a spell's by
rehearsal (the copy resolves the stack), a permanent's by what its words are
aimed at (a Circle's colour, a landwalk: what the *other* side has of the
word), the best few rehearsed with it; a Lace weighs its permanent against
each spell. Each test drives a `_SimulatedGame` built the way
`run_ai_simulation` builds one and reads the board and the log.
"""
from __future__ import annotations

import pytest

from engine import ai_simulator
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import (cast_chosen_instant, choose_cast_action,
                              choose_combat_instant_cast_action)
from engine.ai_text_changes import (AIMED_WORTH, aimed_worth,
                                    announced_text_change_mode)
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent, PlayerState
from engine.text_changes import current_text_card
from tests.helpers import _nosick, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}

#: The census floor: the shipped spells whose text change announces its
#: words at the cast (Sleight of Mind, Magical Hack, Crystal Spray, Alter
#: Reality, Mind Bend, Whim of Volrath).
_ANNOUNCED_FLOOR = 6


def _announced_text_changers() -> list[str]:
    return sorted({
        unit.name for unit in compilation_units(load_catalog())
        if announced_text_change_mode(unit) is not None
    })


def _table(*, boards=((), ()), hands=((), ()), active=0):
    """A two-seat table as `run_ai_simulation` builds one — mana enforced,
    both drivers set — in *active*'s precombat main phase."""
    players = [
        PlayerState(
            name=name, hand=[_CARDS[card] for card in hand],
            library=[_CARDS["Forest"]] * 8,
        )
        for name, hand in zip(("AI-A", "AI-B"), hands)
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = active
    for seat, board in enumerate(boards):
        for name in board:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _on(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


def _cast(game, seat, action):
    action = tap_planned_lands(game, seat, action)
    result = game.cast_from_hand(seat, action.card_name, **cast_announcement(action))
    assert result.supported, result
    resolve_stack(game)


#: The two boards a word is worth changing on: an opposing Circle of
#: Protection: Red facing the caster's red creatures (a colour word), and
#: the caster's swampwalker facing a defender with Islands and no Swamp (a
#: land type).
_CIRCLE_BOARD = (
    ("Island", "Island", "Island", "Hill Giant", "Hill Giant", "Mons's Goblin Raiders"),
    ("Circle of Protection: Red", "Plains", "Plains"),
)
_LANDWALK_BOARD = (
    ("Island", "Island", "Island", "Swamp", "Bog Wraith"),
    ("Island", "Island", "Grizzly Bears"),
)


def test_the_census_finds_every_spell_whose_cast_announces_its_words():
    found = _announced_text_changers()
    assert len(found) >= _ANNOUNCED_FLOOR, found
    for name in ("Sleight of Mind", "Magical Hack", "Crystal Spray", "Alter Reality"):
        assert name in found


@pytest.mark.parametrize("name", _announced_text_changers())
def test_each_announced_text_change_is_cast_naming_words_that_pay(name):
    """Every such spell, on the board its vocabulary pays on, is proposed
    naming two words, and its resolution rewrites them: the Circle no longer
    names red, or the Wraith walks Islands."""
    colour = announced_text_change_mode(_CARDS[name]) != "land_type"
    game = _table(boards=_CIRCLE_BOARD if colour else _LANDWALK_BOARD, hands=((name,), ()))
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == name, action
    assert action.old_color and action.new_color
    _cast(game, 0, action)
    if colour:
        circle = _on(game, 1, "Circle of Protection: Red")
        text = current_text_card(circle).oracle_text.lower()
        assert " red source" not in text, text
        assert any("changed red text" in line for line in game.log), game.log[-6:]
    else:
        wraith = _on(game, 0, "Bog Wraith")
        assert "islandwalk" in current_text_card(wraith).oracle_text.lower()
        assert any("changed Swamp to Island" in line for line in game.log), game.log[-6:]


def test_a_word_aimed_at_nothing_is_not_rewritten():
    """The opposing Circle names red and the caster has nothing red: there
    is nothing worth a card to rewrite, and the Sleight stays in hand."""
    game = _table(
        boards=(("Island", "Grizzly Bears"), ("Circle of Protection: Red", "Plains")),
        hands=(("Sleight of Mind",), ()),
    )
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Sleight of Mind", action


def test_sleight_of_mind_rewrites_the_spell_that_would_kill_its_creature():
    """CR 608.2b through a text change: the opponent's Terror ("destroy
    target nonartifact, nonblack creature") is aimed at the caster's
    Savannah Lions; Sleight of Mind named on the Terror turns "nonblack" into
    "nonwhite", and the rules counter the Terror over the white creature."""
    game = _table(
        boards=(("Island", "Savannah Lions"), ("Swamp", "Swamp")),
        hands=(("Sleight of Mind",), ("Terror",)),
        active=1,
    )
    lions = _on(game, 0, "Savannah Lions")
    game.players[1].mana_pool["B"] = 2
    assert game.queue_from_hand(
        1, "Terror", target_player_index=0, target_permanent_ids=[lions.permanent_id],
    ).supported
    action = choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Sleight of Mind", action
    assert action.target_stack_index == 0
    assert (action.old_color, action.new_color) == ("B", "W")
    cast_chosen_instant(game, 0, action)
    resolve_stack(game)
    assert _on(game, 0, "Savannah Lions") is not None
    assert any("Terror" in card.name for card in game.players[1].graveyard)
    assert any("changed black text to white on Terror" in line for line in game.log), game.log[-8:]


def test_a_lace_is_aimed_at_the_spell_when_that_does_more():
    """The stack half of the union for a spell that changes no words: the
    caster's Lightning Bolt is met by a Hydroblast ("counter target spell if
    it's red"). Purelace on the Bolt makes it white, the Hydroblast's
    condition fails as it resolves, and the Bolt kills the Bears."""
    game = _table(
        boards=(("Plains", "Mountain"), ("Island", "Grizzly Bears")),
        hands=(("Purelace", "Lightning Bolt"), ("Hydroblast",)),
    )
    bears = _on(game, 1, "Grizzly Bears")
    game.players[0].mana_pool["R"] = 1
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    game.players[1].mana_pool["U"] = 1
    assert game.queue_from_hand(
        1, "Hydroblast", target_player_index=0, target_stack_index=0,
    ).supported
    action = choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Purelace", action
    assert action.target_stack_index == 0
    cast_chosen_instant(game, 0, action)
    resolve_stack(game)
    assert "Lightning Bolt (on the stack) became white" in game.log
    assert "Lightning Bolt dealt 3 damage to Grizzly Bears" in game.log


def test_a_land_rewritten_into_what_a_landwalk_reaches_is_worth_the_walk():
    """The land's own type is a word too: the caster's Bog Wraith walks
    Swamps, the defender has one Island and no Swamp, so that Island
    rewritten to a Swamp is one land the swampwalk now reaches."""
    game = _table(boards=(("Bog Wraith",), ("Island",)))
    island = _on(game, 1, "Island")
    assert aimed_worth(game, 0, island, "land_type", "U", "B") == pytest.approx(AIMED_WORTH)
    assert aimed_worth(game, 0, island, "land_type", "U", "G") == pytest.approx(0.0)


_PINNED = ("Sleight of Mind", "Magical Hack", "Crystal Spray", "Alter Reality", "Artificial Evolution")


@pytest.mark.full
def test_seeded_games_cast_each_text_changer_to_effect():
    """The five "target spell or permanent" text changers pinned into every
    deck of three seeded games: each rewrites a word at least once (its
    "<card> changed …" line), and no rehearsal of any of them raised."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    report = run_ai_simulation(
        [manifest_set_path(code) for code in ("LEA", "INV", "TOR", "ONS")],
        games=3, seed=614, max_turns=12, required_cards=_PINNED,
    )
    assert report.games_completed == 3
    assert not report.rehearsals_raised
    for name in _PINNED:
        assert any(f"{name} changed" in line for line in report.log_lines), name


def test_a_word_about_its_controller_s_own_side_reaches_that_side():
    """"Activate only if you control a Swamp" (Tainted Field) is about what
    its controller has; a Circle's "a red source of your choice" is aimed at
    the other side, "your choice" notwithstanding."""
    from engine.ai_text_changes import AIMED, OWN, rules_words

    assert ("land_type", "B", OWN) in rules_words(_CARDS["Tainted Field"])
    assert rules_words(_CARDS["Circle of Protection: Red"]) == {("color_word", "R", AIMED)}
    assert ("land_type", "B", AIMED) in rules_words(_CARDS["Bog Wraith"])
