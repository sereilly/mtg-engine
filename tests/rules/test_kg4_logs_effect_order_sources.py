"""CR 616.1e's ``effect_order`` option names its effect *and* its source.

"The affected object's controller … or the affected player chooses one to
apply" (CR 616.1), and a person chooses between effects by where each comes
from. The option was the registration's label alone, and 56 of the 96 labels
were the docstring's first words — an exemplar card ("Lich", "Jade Monolith",
"Disintegrate-style", "CR 614.9") whatever printed the sentence — so two
effects that do one thing read the same and one read as a card that was not
on the board.

Every registration in both registries now takes ``label=`` (what the effect
does) and ``sources=`` (what generates it for this event), both required, and
``order_prompt_asker`` — the one ask site, which a damage event's prevention
shields reach through ``damage_events`` as its replacements do — writes the
option "<effect> (<source>)" (``effect_ordering.option_text``).
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.effect_ordering import option_text, source_name, source_names
from engine.face_down import face_down_card
from engine.models import Permanent
from engine.prevention.registry import PREVENTION_EFFECTS, prevention_effect
from engine.replacements import REPLACEMENTS, replacement_effect
from engine.shields import add_shield, make_color_shield, make_numeric_pool
from tests.helpers import _mk_creature_card, _nosick
from web.prompt_registry import PromptContext
from web.prompt_values import _effect_order

_C = {card.name: card for card in load_catalog()}


def _registrations():
    return (
        [(kind, c) for kind, entries in REPLACEMENTS.items() for c in entries]
        + [("damage", c) for c in PREVENTION_EFFECTS]
    )


@pytest.mark.cr("616.1", "616.1e")
def test_every_registration_says_what_it_does_and_what_generates_it():
    """By construction, and asserted over the corpus that acts: every
    registration of both registries carries a label that is not an exemplar
    card's name and a ``sources`` reader. A floor on what was examined."""
    rows = _registrations()
    assert len(rows) >= 90, len(rows)
    names = {card.name for card in load_catalog()}
    missing = [(kind, c.key) for kind, c in rows if not callable(c.sources)]
    assert not missing, missing
    exemplar = [(kind, c.key, c.label) for kind, c in rows if c.label in names]
    assert not exemplar, exemplar
    citation = [(kind, c.key, c.label) for kind, c in rows if c.label.startswith("CR ")]
    assert not citation, citation


@pytest.mark.cr("616.1e")
def test_a_registration_that_names_no_source_or_no_effect_is_refused():
    kind = "_kg4_logs_probe"
    try:
        with pytest.raises(TypeError):
            replacement_effect(kind, 1, applies=lambda g, e: False, label="Probe")(
                lambda g, e: None
            )
        with pytest.raises(TypeError):
            replacement_effect(kind, 2, applies=lambda g, e: False, sources=lambda g, e: [])(
                lambda g, e: None
            )
        assert kind not in REPLACEMENTS or not REPLACEMENTS[kind]
    finally:
        REPLACEMENTS.pop(kind, None)
    count = len(PREVENTION_EFFECTS)
    with pytest.raises(TypeError):
        prevention_effect(9_998, applies=lambda g, e: False, label="Probe")(lambda g, e: None)
    assert len(PREVENTION_EFFECTS) == count


def _life_table(mine=(), theirs=()):
    p1 = PlayerState(
        name="P1", life=10, library=[_C["Forest"]] * 5,
        battlefield=[_nosick(Permanent(card=_C[n])) for n in mine],
    )
    p2 = PlayerState(
        name="P2", library=[_C["Forest"]] * 5,
        battlefield=[_nosick(Permanent(card=_C[n])) for n in theirs],
    )
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}
    return game, p1


@pytest.mark.cr("616.1", "616.1e")
def test_lich_beside_sulfuric_vortex_names_both_cards():
    """Two replacements over one life gain (CR 616.1; ``replacements.life_gain``):
    Lich's "draw that many cards instead" and Sulfuric Vortex's "gains no life
    instead". The option for Lich used to read "Lich" — a card's name for an
    effect — and the Vortex's "Gain no life instead", with no card at all."""
    game, p1 = _life_table(mine=["Lich"], theirs=["Sulfuric Vortex"])
    game._gain_life(p1, 3, source_name="Stream of Life")

    owed = game.pending_choices_of("effect_order", 0)
    assert len(owed) == 1
    options = owed[0].data["options"]
    assert options == [
        "Draw that many cards instead (Lich)",
        "Gain no life instead (Sulfuric Vortex)",
    ], options
    assert any(
        "P1 must choose which effect applies first (Draw that many cards instead "
        "(Lich), Gain no life instead (Sulfuric Vortex))" in line
        for line in game.log
    ), game.log[-3:]
    # What the person is served.
    ctx = PromptContext(
        game=game, viewer_seat=0, serialize_card=lambda card: {"name": card.name},
        seat_type=lambda seat: "human",
    )
    assert _effect_order(ctx, owed)["options"] == options

    assert game.resolve_pending_choice("effect_order", 0, option_index=1)
    assert "P1 applies Gain no life instead (Sulfuric Vortex) first" in game.log
    assert any(
        line.endswith("gains no life instead (Sulfuric Vortex)") for line in game.log
    ), game.log[-3:]
    assert p1.life == 10 and p1.hand == []


@pytest.mark.cr("616.1e")
def test_the_other_answer_draws_and_names_the_card_that_drew():
    game, p1 = _life_table(mine=["Lich"], theirs=["Sulfuric Vortex"])
    game._gain_life(p1, 2)
    assert game.resolve_pending_choice("effect_order", 0, option_index=0)
    assert "P1 applies Draw that many cards instead (Lich) first" in game.log
    assert any(line.endswith("drew 2 card(s) instead (Lich)") for line in game.log), game.log[-3:]
    assert len(p1.hand) == 2 and p1.life == 10


@pytest.mark.cr("616.1e")
def test_one_effect_printed_twice_names_its_card_once():
    """Two Sulfuric Vortexes are one contender (``_gain_no_life_instead``'s
    reason), and the option names the card once rather than counting it."""
    game, p1 = _life_table(mine=["Lich", "Sulfuric Vortex"], theirs=["Sulfuric Vortex"])
    game._gain_life(p1, 1)
    options = game.pending_choices_of("effect_order", 0)[0].data["options"]
    assert options[1] == "Gain no life instead (Sulfuric Vortex)", options


@pytest.mark.cr("616.1", "615.7")
def test_two_shields_from_two_cards_name_their_cards():
    """A damage event's prevention half reaches the same ask site
    (``damage_events.deal_damage`` → ``order_prompt_asker``): a Circle's shield
    and a prevention pool each name the card that granted them
    (``Shield.source_name``), read by ``prevention.shields._granted_by``."""
    red = Permanent(card=replace(_mk_creature_card("Red Ogre", 3, 3), colors=("R",)))
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p1, PlayerState(name="P2", battlefield=[red])])
    game.interactive_seats = {0}
    add_shield(p1, make_color_shield(("R",), "Circle of Protection: Red"))
    add_shield(p1, make_numeric_pool(5, "Healing Salve"))

    def hit():
        return game._deal_damage_to_player(p1, 3, red, restart=hit)

    hit()
    owed = game.pending_choices_of("effect_order", 0)
    assert len(owed) == 1
    assert owed[0].data["options"] == [
        "Prevent the next damage from a source of the shield's color "
        "(Circle of Protection: Red)",
        "Prevent the next N damage (Healing Salve)",
    ], owed[0].data["options"]
    assert game.resolve_pending_choice("effect_order", 0, option_index=1)
    assert p1.life == 20
    assert "P1 applies Prevent the next N damage (Healing Salve) first" in game.log


@pytest.mark.cr("616.1", "616.1e")
def test_a_multiplier_beside_a_shield_names_the_permanent_that_multiplies():
    """A replacement and a prevention shield over one damage event: Furnace of
    Rath's option was "Fiery Emancipation" — the card its docstring opened
    with — when no Fiery Emancipation was in play."""
    red = Permanent(card=replace(_mk_creature_card("Red Ogre", 3, 3), colors=("R",)))
    furnace = _nosick(Permanent(card=_C["Furnace of Rath"]))
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p1, PlayerState(name="P2", battlefield=[red, furnace])])
    game.interactive_seats = {0}
    add_shield(p1, make_numeric_pool(2, "Healing Salve"))

    def hit():
        return game._deal_damage_to_player(p1, 2, red, restart=hit)

    hit()
    options = game.pending_choices_of("effect_order", 0)[0].data["options"]
    assert "It deals a multiple of that damage instead (Furnace of Rath)" in options, options
    assert "Prevent the next N damage (Healing Salve)" in options, options
    assert not any("Fiery Emancipation" in option for option in options)


@pytest.mark.cr("708.2")
def test_a_face_down_source_is_named_as_every_seat_sees_it():
    """CR 708.2: a face-down permanent's characteristics are the blank 2/2's,
    and ``Permanent.card`` *is* that blank while hidden — so a source that is
    face down is named as everybody sees it, never by the card behind it."""
    hidden = Permanent(card=face_down_card(_C["Grizzly Bears"]))
    assert source_name(hidden) != "Grizzly Bears"
    assert source_name(hidden) == hidden.card.name
    assert source_names([hidden, hidden, "Healing Salve", None]) == [
        hidden.card.name, "Healing Salve",
    ]


@pytest.mark.cr("616.1e")
def test_an_effect_whose_record_keeps_no_card_shows_its_label_alone():
    """A source reader that finds nothing — here a permanent carrying no
    would-die marker at all, so Disintegrate's reader has no name to read
    (``zone_changes.recorded_name``) — leaves the option as the label, never
    "Label ()"."""
    for kind, candidate in _registrations():
        if candidate.key == "_exile_instead_of_dying":
            bears = Permanent(card=_C["Grizzly Bears"])
            game = Game(players=[PlayerState(name="P1", battlefield=[bears]), PlayerState(name="P2")])
            text = option_text(game, {"permanent": bears, "player": game.players[0]}, candidate)
            assert text == candidate.label
            break
    else:  # pragma: no cover - the registration is in the pool
        pytest.fail("no would_die exile registration")
