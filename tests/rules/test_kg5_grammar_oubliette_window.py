"""Oubliette's line off its card hook: "phases out until this <self> leaves
the battlefield" and "Tap that creature as it phases in this way." are grammar.

Until kg5 the whole line was one ``CARD_LINE_INSTRUCTIONS`` entry, its handler
hard-wired to tap the creature as it came back and to take any creature. The
production in ``grammar/subject_verb`` now reads the window
(``readers.accept_until_source_leaves``, shared with the land-type window) and
the rider onto ``ast.PhaseOut``, lowered by
``lowering/phasing._lower_phase_out_until_source_leaves`` to the kind the hook
emitted, with the rider as the payload's ``tapped`` and the noun phrase as its
``targets``. So the window without the rider phases its creature back in
untapped, a card naming itself in the window is read, a narrowed target is
enforced, and every shape with no handler behind it refuses whole.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_hooks import CARD_LINE_INSTRUCTIONS
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import settle

_CARDS = {card.name: card for card in load_catalog()}


def _card(name: str, type_line: str, oracle_text: str) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "1", "1"
    return CardDefinition(
        name=name, mana_cost="{1}{W}", cmc=2.0, type_line=type_line,
        oracle_text=oracle_text, colors=("W",), color_identity=("W",),
        keywords=(), produced_mana=(), raw=raw,
        power=raw.get("power"), toughness=raw.get("toughness"),
    )


def _table() -> Game:
    game = Game(players=[
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 10) for i in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _set_down(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _cast(game: Game, seat: int, card: CardDefinition, target: Permanent):
    game.players[seat].hand.append(card)
    result = game.cast_from_hand(
        seat, card.name, target_player_index=game.controller_index_of(target),
        target_permanent_ids=[target.permanent_id],
    )
    settle(game)
    return result


def _named(game: Game, name: str) -> Permanent:
    return next(p for p in game.all_permanents() if p.card.name == name)


def _phased(game: Game, seat: int) -> list[str]:
    return [perm.card.name for perm in game.players[seat].phased_out]


@pytest.mark.cr("702.26b", "702.26c", "610.3")
def test_oubliette_is_read_by_the_grammar_and_its_creature_comes_back_tapped():
    assert "Oubliette" not in CARD_LINE_INSTRUCTIONS
    (ability,) = compile_card_oracle(_CARDS["Oubliette"]).triggered_abilities
    assert ability.instruction.payload["tapped"] is True

    game = _table()
    giant = _set_down(game, 1, "Hill Giant")
    assert _cast(game, 0, _CARDS["Oubliette"], giant).supported
    assert _phased(game, 1) == ["Hill Giant"]
    assert any("Oubliette phases Hill Giant out" in line for line in game.log)

    _cast(game, 1, _CARDS["Disenchant"], _named(game, "Oubliette"))
    assert game.is_on_battlefield(giant) and giant.tapped, game.log[-6:]
    assert _phased(game, 1) == []


@pytest.mark.cr("702.26c", "610.3")
def test_the_window_without_the_rider_phases_its_creature_back_in_untapped():
    """The rider is the payload, not the kind: the hook's handler tapped every
    creature it gave back, which this card does not print."""
    cell = _card(
        "Kg5 Cell", "Enchantment",
        "When this enchantment enters, target creature phases out until this "
        "enchantment leaves the battlefield.",
    )
    program = compile_card_oracle(cell)
    assert program.supported, program.reason
    assert program.triggered_abilities[0].instruction.payload["tapped"] is False

    game = _table()
    giant = _set_down(game, 1, "Hill Giant")
    assert _cast(game, 0, cell, giant).supported
    assert _phased(game, 1) == ["Hill Giant"]

    _cast(game, 1, _CARDS["Disenchant"], _named(game, "Kg5 Cell"))
    assert game.is_on_battlefield(giant)
    assert not giant.tapped, "nothing printed taps it"


@pytest.mark.cr("702.26c", "610.3")
def test_a_creature_naming_itself_in_the_window_gives_it_back_as_it_dies():
    """"…until Kg5 Warden leaves the battlefield": the card's own name, which
    the lexer collapses to one SELF token — the shared window reader takes
    it, as the land-type window already did."""
    warden = _card(
        "Kg5 Warden", "Creature — Soldier",
        "When Kg5 Warden enters, target creature phases out until Kg5 Warden "
        "leaves the battlefield. Tap that creature as it phases in this way.",
    )
    program = compile_card_oracle(warden)
    assert program.supported, program.reason

    game = _table()
    giant = _set_down(game, 1, "Hill Giant")
    assert _cast(game, 0, warden, giant).supported
    assert _phased(game, 1) == ["Hill Giant"]

    _cast(game, 1, _CARDS["Lightning Bolt"], _named(game, "Kg5 Warden"))
    assert not any(p.card.name == "Kg5 Warden" for p in game.all_permanents())
    assert game.is_on_battlefield(giant) and giant.tapped, game.log[-6:]


@pytest.mark.cr("702.26b", "115.1")
def test_a_narrowed_target_is_carried_and_enforced():
    """"Target creature **an opponent controls**": the noun phrase is the
    payload's ``targets``, so the picker offers the opponent's creatures alone
    and the handler re-asks the phrase. The hook's handler took any
    creature."""
    jailer = _card(
        "Kg5 Jailer", "Enchantment",
        "When this enchantment enters, target creature an opponent controls "
        "phases out until this enchantment leaves the battlefield.",
    )
    program = compile_card_oracle(jailer)
    assert program.supported, program.reason
    described = program.triggered_abilities[0].instruction.payload["targets"]["filter"]
    assert described.get("controller") == "opponent", described

    game = _table()
    own = _set_down(game, 0, "Grizzly Bears")
    giant = _set_down(game, 1, "Hill Giant")
    _cast(game, 0, jailer, own)
    assert game.is_on_battlefield(own), "the caster's own creature is no legal target"
    assert _phased(game, 0) == []

    game = _table()
    _set_down(game, 0, "Grizzly Bears")
    giant = _set_down(game, 1, "Hill Giant")
    assert _cast(game, 0, jailer, giant).supported
    assert _phased(game, 1) == ["Hill Giant"]


@pytest.mark.cr("702.26b")
@pytest.mark.parametrize("text", [
    # A sweep has no handler that binds its phase-in to the source.
    "When this enchantment enters, all creatures phase out until this "
    "enchantment leaves the battlefield.",
    # The kind is about a creature; another noun has no reading.
    "When this enchantment enters, target artifact phases out until this "
    "enchantment leaves the battlefield.",
    # The rider names "this way", which only the window is.
    "When this enchantment enters, target creature phases out. Tap that "
    "creature as it phases in this way.",
])
def test_a_shape_with_no_handler_behind_it_refuses_whole(text):
    program = compile_card_oracle(_card("Kg5 Oddity", "Enchantment", text))
    assert not program.supported, program
