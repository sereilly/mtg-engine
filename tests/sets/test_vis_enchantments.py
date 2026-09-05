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


def _w1g4_artifact(name: str, cmc: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{%d}" % cmc, cmc=float(cmc), type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name},
    )


def test_corrosion_rusts_then_destroys_what_the_rust_has_caught(set_pool):
    """"At the beginning of your upkeep, put a rust counter on each artifact
    target opponent controls. Then destroy each artifact with mana value less
    than or equal to the number of rust counters on it."

    Both halves used to be one instruction-less trigger. The destroy's bound is
    a characteristic of the *same object* the sweep is testing, which is what
    makes it a filter key rather than an amount - and CR's own reading is that a
    mana-value-0 artifact qualifies with no counters at all, which is why the
    sweep is not narrowed to the targeted opponent's board.
    """
    from engine.named_counters import counters_on

    game = _w1g4_game()
    game.players[0].battlefield.append(
        Permanent(card=set_pool("VIS")["Corrosion"])
    )
    # Corrosion's other upkeep trigger is its cumulative upkeep, and a seat that
    # cannot pay it sacrifices the enchantment in the same step - which then
    # fires the leaves-the-battlefield trigger and clears the counters this test
    # is about. One untapped land is the whole fixture.
    game.players[0].battlefield.append(Permanent(card=CardDefinition(
        name="Swamp", mana_cost="", cmc=0.0, type_line="Basic Land - Swamp",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("B",), raw={"name": "Swamp"},
    )))
    one = Permanent(card=_w1g4_artifact("One", 1))
    two = Permanent(card=_w1g4_artifact("Two", 2))
    game.players[1].battlefield.extend([one, two])
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    game.resolve_upkeep(0, defer_priority=True)
    _w1g4_drain(game)

    # One rust counter each: the {1} artifact is caught, the {2} one is not yet.
    assert [p.card.name for p in game.players[1].battlefield] == ["Two"]
    assert counters_on(two, "rust") == 1
    assert [c.name for c in game.players[1].graveyard] == ["One"]


def test_corrosion_takes_its_rust_with_it_when_it_leaves(set_pool):
    """"When this enchantment leaves the battlefield, remove all rust counters
    from all permanents." - the second instruction-less part, and a sweep over a
    described set rather than the ability's own source (which by then is gone)."""
    from engine.named_counters import add_counters, counters_on

    game = _w1g4_game()
    corrosion = Permanent(card=set_pool("VIS")["Corrosion"])
    game.players[0].battlefield.append(corrosion)
    rusted = Permanent(card=_w1g4_artifact("Big", 6))
    game.players[1].battlefield.append(rusted)
    add_counters(rusted, "rust", 3)
    game.begin_turn_bookkeeping(0)

    game.remove_from_battlefield(corrosion)
    _w1g4_drain(game)

    assert counters_on(rusted, "rust") == 0
    assert game.is_on_battlefield(rusted), "the counters go, the artifact stays"


def test_rowen_reveals_the_first_draw_and_pays_for_a_land(set_pool):
    """"Reveal the first card you draw each turn. Whenever you reveal a basic
    land card this way, draw a card."

    One printed paragraph holding a static ability and a triggered one, so the
    compiler had to be taught to split it - gated on the first sentence being a
    static the engine already implements, because the pool holds two *spells*
    whose second sentence opens the same way and is a delayed ability their
    first sentence creates.

    Both directions are asserted: the reveal happens either way (it is not
    conditional), and only a basic land pays the extra card.
    """
    pool = set_pool("VIS")
    plains = CardDefinition(
        name="Plains", mana_cost="", cmc=0.0, type_line="Basic Land - Plains",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("W",), raw={"name": "Plains"},
    )
    ogre = _w1g4_creature("Ogre", "Creature - Ogre")

    def _draw_step(top):
        game = Game(players=[
            PlayerState(name="P0", library=[top] + [ogre] * 5),
            PlayerState(name="P1", library=[ogre] * 5),
        ])
        game.enforce_mana_costs = False
        game.players[0].battlefield.append(Permanent(card=pool["Rowen"]))
        game.turn = 2
        game.begin_turn_bookkeeping(0)
        game.active_player_index = 0
        game.resolve_draw_step(0, defer_priority=True)
        _w1g4_drain(game)
        return game

    game = _draw_step(plains)
    assert [event["cards"] for event in game.reveal_events] == [["Plains"]]
    assert len(game.players[0].hand) == 2, "the basic land bought a second card"

    game = _draw_step(ogre)
    assert [event["cards"] for event in game.reveal_events] == [["Ogre"]]
    assert len(game.players[0].hand) == 1


def test_rowen_does_not_fire_on_an_opponents_first_draw(set_pool):
    """"**You** reveal" is the ability's controller (CR 109.5), and the static
    half is their reveal too - the seat is what the announcement carries."""
    plains = CardDefinition(
        name="Plains", mana_cost="", cmc=0.0, type_line="Basic Land - Plains",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("W",), raw={"name": "Plains"},
    )
    game = Game(players=[
        PlayerState(name="P0", library=[plains] * 5),
        PlayerState(name="P1", library=[plains] * 5),
    ])
    game.enforce_mana_costs = False
    game.players[0].battlefield.append(Permanent(card=set_pool("VIS")["Rowen"]))
    game.turn = 2
    game.begin_turn_bookkeeping(1)
    game.active_player_index = 1

    game.resolve_draw_step(1, defer_priority=True)
    _w1g4_drain(game)

    assert game.reveal_events == []
    assert len(game.players[1].hand) == 1
