"""Every CR 616.1 candidate's label is one short line saying what it does.

The label is the option CR 616.1e's ``effect_order`` prompt shows the affected
player, and the effect the log names when it asks. Both registries cut it from
the registration's docstring at its first colon, so it was whatever the
docstring's author happened to write before one. Measured on the base (the
kg/damage census, 94 candidates): three showed a paragraph — the plain "prevent
the next N damage" pool (Healing Salve, Samite Healer), so most real
contentions put one in front of a player; Pentagram of the Ages' sourceless
charge; Infernal Darkness' land-mana substitution — one showed its function
name (Argothian Treefolk's source-type blanket), and two different shields
showed the same sentence ("The same shield cast without recording a chosen
source"), so the player could not tell them apart.

``@prevention_effect`` takes ``label=`` now and requires it; since kg4
``@replacement_effect`` requires it too — the docstring fallback made most
options an exemplar card's name — and both require ``sources=``, what the
option names beside the label (``tests/rules/test_kg4_logs_effect_order_sources.py``).
``effect_ordering.option_label`` is the one rule both hold a label to.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from engine import PlayerState
from engine.damage_events import damage_candidates  # noqa: F401  (registers both halves)
from engine.effect_ordering import OPTION_LABEL_LIMIT, option_label
from engine.game import Game
from engine.models import Permanent
from engine.prevention.registry import PREVENTION_EFFECTS, prevention_effect, shield_candidates
from engine.replacements import REPLACEMENTS, replacement_effect
from tests.helpers import _mk_creature_card


def _short_line(label: str, key: str) -> bool:
    return bool(label) and "\n" not in label and len(label) <= OPTION_LABEL_LIMIT and label != key


def test_every_candidate_shows_one_short_line():
    prevention = shield_candidates()
    replacements = [(kind, c) for kind, entries in REPLACEMENTS.items() for c in entries]
    # A floor on what was examined: the two registries hold 37 shields and 57
    # replacements at the kg round.
    assert len(prevention) >= 35 and len(replacements) >= 50, (len(prevention), len(replacements))

    bad = [("prevention", c.key, c.label) for c in prevention if not _short_line(c.label, c.key)]
    bad += [(kind, c.key, c.label) for kind, c in replacements if not _short_line(c.label, c.key)]
    assert not bad, f"effect_order options that are not one short line: {bad}"


def test_two_options_one_player_may_be_asked_between_are_never_worded_alike():
    """A prompt's options come from one event's contenders: the shields, and a
    damage event's replacements beside them (``damage_events``). Two with one
    wording are a choice the player cannot read."""
    labels = [c.label for c in shield_candidates()]
    assert len(labels) == len(set(labels)), sorted(l for l in labels if labels.count(l) > 1)
    for kind, entries in REPLACEMENTS.items():
        names = [c.label for c in entries]
        if kind.startswith("damage_to_"):
            names += labels
        assert len(names) == len(set(names)), (kind, sorted(n for n in names if names.count(n) > 1))


def test_a_shield_must_name_its_option_and_name_it_in_one_line():
    count = len(PREVENTION_EFFECTS)
    with pytest.raises(TypeError):
        prevention_effect(9_999, applies=lambda game, event: False)(lambda game, event: None)
    with pytest.raises(ValueError, match="one line"):
        prevention_effect(
            9_999, applies=lambda game, event: False,
            sources=lambda game, event: [],
            label="Prevent the damage.\nThen read this whole paragraph.",
        )(lambda game, event: None)
    assert len(PREVENTION_EFFECTS) == count, "a refused registration is not added"


def test_a_replacement_must_name_its_option_whatever_its_docstring_says():
    def _wordy(game, payload):
        """"If a land is tapped for mana, it produces {B} instead of any other
        type." (A docstring that opens with a quotation and no colon.)"""

    kind = "_kg_kinds_label_probe"
    try:
        with pytest.raises(TypeError):
            replacement_effect(
                kind, 1, applies=lambda game, payload: False,
                sources=lambda game, payload: [],
            )(_wordy)
        with pytest.raises(ValueError, match="one line"):
            replacement_effect(
                kind, 3, applies=lambda game, payload: False,
                sources=lambda game, payload: [], label="Two\nlines",
            )(_wordy)
        replacement_effect(
            kind, 2, applies=lambda game, payload: False, label="A short option",
            sources=lambda game, payload: [],
        )(_wordy)
        assert [c.label for c in REPLACEMENTS[kind]] == ["A short option"]
    finally:
        REPLACEMENTS.pop(kind, None)
    assert option_label("  Prevent the next N damage  ", key="k") == "Prevent the next N damage"


def test_the_prompt_a_player_is_asked_shows_the_labels():
    """Driven: a Circle-of-Protection shield and a prevention pool both apply
    to one red source's damage to an interactive seat (CR 616.1e), and the
    prompt — and the log line that announces it — offer the two one-line
    labels, the pool's among them rather than its docstring paragraph."""
    red = Permanent(card=replace(_mk_creature_card("Red Ogre", 3, 3), colors=("R",)))
    p1 = PlayerState(name="P1", life=20)
    p1.color_prevention_shields = ["R"]
    p1.damage_prevention_pool = 5
    game = Game(players=[p1, PlayerState(name="P2", battlefield=[red])])
    game.interactive_seats = {0}

    def hit():
        return game._deal_damage_to_player(p1, 3, red, restart=hit)

    hit()
    prompt = game.pending_choices_of("effect_order", 0)
    assert len(prompt) == 1
    options = prompt[0].data["options"]
    assert options == [
        "Prevent the next damage from a source of the shield's color",
        "Prevent the next N damage",
    ], options
    assert any(
        "must choose which effect applies first (Prevent the next damage from a "
        "source of the shield's color, Prevent the next N damage)" in line
        for line in game.log
    ), game.log

    game.resolve_pending_choice(
        "effect_order", 0, option_index=options.index("Prevent the next N damage")
    )
    assert p1.damage_prevention_pool == 2 and p1.color_prevention_shields == ["R"]
    assert p1.life == 20
