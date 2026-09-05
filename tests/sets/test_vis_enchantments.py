"""Visions enchantments.

Each group appends its own block with its own imports at the top of that block,
so a per-set merge is an append rather than a conflict (SET_PLAYBOOK.md).
"""


# --- W1G4: upkeep, end-step and per-player step triggers ---
import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g4_game() -> Game:
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    return game


def _w1g4_drain(game: Game) -> None:
    for _ in range(20):
        if not game.stack:
            return
        game.resolve_top_of_stack()
    raise AssertionError("the stack never drained")


def _w1g4_creature(name: str, type_line: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name}, power="2", toughness="2",
    )


def test_suleimans_legacy_destroys_a_djinn_that_enters_later(set_pool):
    """"Whenever a Djinn or Efreet enters, destroy it. It can't be regenerated."

    The second line, and until this round it compiled to no instruction at all -
    the enchantment reported supported on its *first* line and the trigger fired
    into nothing. "It" is the permanent the trigger's own event was about, which
    is what the entry transition now freezes; read as the ability's own source
    (which is what a bare pronoun means everywhere else) the enchantment would
    have destroyed itself.
    """
    game = _w1g4_game()
    legacy = Permanent(card=set_pool("VIS")["Suleiman's Legacy"])
    game.players[0].battlefield.append(legacy)
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    djinn = Permanent(card=_w1g4_creature("Bottled Djinn", "Creature - Djinn"))
    game._put_permanent_onto_battlefield(1, djinn, None)
    _w1g4_drain(game)

    assert [p.card.name for p in game.players[1].battlefield] == []
    assert [c.name for c in game.players[1].graveyard] == ["Bottled Djinn"]
    # The enchantment is still there: the pronoun named the enterer, not itself.
    assert game.is_on_battlefield(legacy)


def test_suleimans_legacy_leaves_a_creature_its_trigger_does_not_name(set_pool):
    """The narrowing is the trigger's own subject filter, and a trigger that
    fired on every entry would be a strictly different card."""
    game = _w1g4_game()
    game.players[0].battlefield.append(
        Permanent(card=set_pool("VIS")["Suleiman's Legacy"])
    )
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    bear = Permanent(card=_w1g4_creature("Grizzly", "Creature - Bear"))
    game._put_permanent_onto_battlefield(1, bear, None)
    _w1g4_drain(game)

    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly"]


def test_suleimans_legacy_carries_the_no_regeneration_rider(set_pool):
    """"It can't be regenerated" is the instruction's ``bypass_regeneration``,
    not a second reading of CR 701.19c - a rider parsed and dropped is a
    destroy a regeneration shield would survive."""
    program = compile_card_oracle(set_pool("VIS")["Suleiman's Legacy"])
    entering = next(
        trigger for trigger in program.triggered_abilities
        if trigger.condition.kind == "matching_permanent_enters"
    )

    assert entering.instruction is not None, "the trigger used to be hollow"
    assert entering.instruction.kind == "destroy_event_subject"
    assert entering.instruction.payload["bypass_regeneration"] is True


def test_a_bare_it_refuses_where_no_event_names_an_object():
    """The refusal side of the same production: "destroy it" is only a
    back-reference where the firing event froze one, and everywhere else the
    pronoun is the ability's own source."""
    from engine.grammar import lower_ability, parse_line
    from engine.grammar.errors import LoweringError

    # A trigger whose fire site freezes no object for the pronoun to name.
    node = parse_line("Whenever a land is tapped for mana, destroy it.")
    with pytest.raises(LoweringError):
        lower_ability(node)
