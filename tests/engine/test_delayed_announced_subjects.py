"""A delayed ability is about what its creating spell or ability announced.

CR 115.1a makes a *spell* targeted where its spell ability says "target", and
CR 601.2c picks that target as the spell is cast — so "**Target player** draws
a card at the beginning of the next turn's upkeep" (Sapphire Charm) names its
player a turn before anything is drawn, and the delayed ability the Charm
creates (CR 603.7) is *about* that player. It compiled to an entry about
nobody: the description sat on the delayed ability's own instruction, the cast
derived no picker at all, and as the ability fired it announced a target of its
own — which a non-interactive seat answers with its first opponent.

The census below asks the question of the whole pool, and the answer was three
other shipped cards behind the same seam:

* **Lodestone Bauble** ("**That player** draws a card at the beginning of the
  next turn's upkeep") — the lowering's own comment said the seat was "read off
  the resolution", and nothing read it: with the Bauble aimed at its
  controller's own graveyard an opponent drew.
* **Horn of Plenty** ("…**they** draw a card at the beginning of the next end
  step") — the Horn's controller cast, paid {1}, and an opponent drew.
* **Barreling Attack** ("When that creature becomes blocked this turn, **it**
  gets +1/+1 …") — the object half. The delayed ability chose a creature of its
  own as it fired, which with two creatures on the board was not the one the
  spell had named.

The per-card halves are in each card's own set file; this file is the
pool-wide census and the invented cards — the same printed sentences on cards
nobody shipped, because a fix that only works for the named card is a hook in
disguise.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.delayed_triggers import DelayedTrigger
from engine.faces import compilation_units
from engine.game_types import CardDefinition, Permanent, StackItem
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from engine.targeting import derive_cast_spec
from tests.helpers import resolve_stack


def _card(name: str, type_line: str, text: str = "", **raw) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, **raw},
    )


def _instructions(value):
    """Every instruction nested anywhere under *value*."""
    if isinstance(value, OracleInstruction):
        yield value
        value = value.payload
    if isinstance(value, dict):
        value = tuple(value.values())
    if isinstance(value, (list, tuple)):
        for inner in value:
            yield from _instructions(inner)


def _delays_of(card) -> list[OracleInstruction]:
    program = compile_card_oracle(card)
    if not program.supported:
        return []
    roots = [
        *program.instructions,
        *(mode.instruction for mode in program.modes),
        *(ability.instruction for ability in program.activated_abilities),
        *(ability.instruction for ability in program.triggered_abilities),
    ]
    found: list[OracleInstruction] = []
    for step in _instructions(roots):
        if step.kind == "create_delayed_trigger" and not any(step is seen for seen in found):
            found.append(step)
    return found


def _fired(game: Game, card, delay: OracleInstruction, about: Permanent) -> StackItem:
    """The stack object *delay*'s entry becomes when it fires, built the way
    ``handlers/board_misc.create_delayed_trigger`` arms it and
    ``delayed_triggers.fire_delayed_triggers`` announces it."""
    payload = delay.payload
    binds_object = any(payload.get(key) for key in (
        "binds_target", "binds_recorded", "binds_event_subject",
        "binds_block_pair", "binds_attached_host", "watches",
    ))
    entry = DelayedTrigger(
        controller_index=0,
        event=payload["event"],
        instruction=payload["instruction"],
        source_name=card.name, card=card,
        bound_permanent_id=about.permanent_id if binds_object else None,
        bound_as_target=bool(payload.get("bound_as_target")),
        bound_player_index=0 if payload.get("binds_player") else None,
    )
    event = entry.trigger_event(game=game)
    return StackItem(
        card=card, caster_index=0,
        target_player_index=event["target_player_index"],
        target_permanent_index=None,
        target_permanent_id=event["target_permanent_id"],
        x_value=None,
        ability_instruction=event["instruction"],
        ability_effect_kind=event["effect_kind"],
        trigger_context=event["trigger_context"],
    )


#: The delayed abilities that really do choose a target as they are put on the
#: stack (CR 603.3d): the *delayed ability's own* sentence prints one, and it
#: repeats, so no announcement made when it was created could be its answer.
_TARGETS_AS_IT_FIRES = {
    # "Until end of turn, whenever a creature you control attacks and isn't
    # blocked, you may choose to have it deal damage equal to its power to **a
    # target creature**."
    "Gaze of Pain",
}


def test_no_delayed_ability_chooses_what_its_creator_already_announced(catalog):
    """The census. Every delayed ability in the pool is built as it would fire
    and asked whether CR 603.3d has a target for it to choose.

    On the tree this was written against, three did: Gaze of Pain, which
    should, and Sapphire Charm and Barreling Attack, which had each already
    announced what they are about when they were cast.
    """
    examined = 0
    choosing = set()
    for card in compilation_units(catalog):
        for delay in _delays_of(card):
            game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
            game.interactive_seats = {0, 1}
            mine = Permanent(card=_card("Mine", "Creature — Bear", power="2", toughness="2"))
            game._put_permanent_onto_battlefield(0, mine, None)
            game._put_permanent_onto_battlefield(
                1, Permanent(card=_card("Theirs", "Creature — Bear", power="2", toughness="2")), None
            )
            examined += 1
            if game._trigger_target_candidates(_fired(game, card, delay, mine)) is not None:
                choosing.add(card.name)

    # The floor: 168 on the tree this was written against. A walk that stopped
    # reaching the nested entries would pass over nothing.
    assert examined >= 150, examined
    assert choosing == _TARGETS_AS_IT_FIRES, sorted(choosing ^ _TARGETS_AS_IT_FIRES)


def test_every_delayed_draw_for_a_named_player_binds_that_player(catalog):
    """The seat half of the census. A delayed "<player> draws" whose player is
    read off the resolution (no record, no loop seat, no "each") must carry a
    binding, or the firing resolution's default seat answers instead.

    Four in the pool, and three of them were unbound: Sapphire Charm, Lodestone
    Bauble and Horn of Plenty. (Soldevi Sentry's was bound already, by the
    ``choose_target_player`` step in front of it.)
    """
    unbound = []
    examined = 0
    for card in compilation_units(catalog):
        for delay in _delays_of(card):
            for step in _instructions(delay.payload["instruction"]):
                if step.kind != "draw_target_cards":
                    continue
                if any(key in step.payload for key in (
                    "recipient", "drawer_seat", "drawer_seat_record",
                )):
                    continue
                examined += 1
                if not delay.payload.get("binds_player"):
                    unbound.append(card.name)
    assert examined >= 4, examined
    assert unbound == []


# -- invented cards: the same sentences on cards nobody shipped -----------------


def _duel(*, hand=(), interactive=()):
    filler = _card("Filler", "Artifact")
    players = [
        PlayerState(name="P1", hand=list(hand), library=[filler] * 6),
        PlayerState(name="P2", library=[filler] * 6),
        PlayerState(name="P3", library=[filler] * 6),
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _owed(game):
    return [(choice.kind, choice.player_index) for choice in game.pending_choices]


@pytest.mark.parametrize("named", [0, 1, 2])
def test_an_invented_delayed_draw_goes_to_the_player_named_at_cast(named):
    """"Target player draws two cards at the beginning of the next end step."
    Not Sapphire Charm's mode, not its step and not its number — and at three
    seats, where "the first opponent" cannot be right twice."""
    spell = _card(
        "Slow Insight", "Instant",
        "Target player draws two cards at the beginning of the next end step.",
    )
    program = compile_card_oracle(spell)
    assert program.supported, program.reason
    assert derive_cast_spec(spell, program) == {"kind": "player"}

    game = _duel(hand=[spell], interactive={0, 1, 2})
    assert game.cast_from_hand(0, "Slow Insight", target_player_index=named).supported
    resolve_stack(game)
    assert [len(p.hand) for p in game.players] == [0, 0, 0], "nothing is drawn yet"

    from engine.delayed_triggers import fire_delayed_triggers

    assert fire_delayed_triggers(game, "next_end_step") == 1
    assert _owed(game) == [], "the delayed ability announces no target of its own"
    resolve_stack(game)

    drawn = [len(p.hand) for p in game.players]
    assert drawn == [2 if seat == named else 0 for seat in range(3)], game.log


def test_an_invented_delayed_life_loss_is_bound_the_same_way():
    """A different verb through the same seam: nothing here is about drawing."""
    spell = _card(
        "Slow Poison", "Sorcery",
        "Target player loses 2 life at the beginning of the next turn's upkeep.",
    )
    game = _duel(hand=[spell])
    assert game.cast_from_hand(0, "Slow Poison", target_player_index=0).supported
    resolve_stack(game)
    game.resolve_upkeep(1)
    resolve_stack(game)

    assert [p.life for p in game.players] == [18, 20, 20], game.log


def test_an_invented_activated_ability_announces_its_delayed_player():
    """CR 602.2b, the activated half: the picker is derived off the ability,
    and the player it names is the one the delayed ability reaches."""
    from engine.targeting import derive_activation_spec

    relic = _card(
        "Slow Relic", "Artifact",
        "{T}: Target player draws a card at the beginning of the next turn's upkeep.",
    )
    ability = compile_card_oracle(relic).activated_abilities[0]
    assert derive_activation_spec(ability) == {"kind": "player"}

    game = _duel()
    game._put_permanent_onto_battlefield(0, Permanent(card=relic), None)
    assert game.activate_permanent_ability(0, "Slow Relic", target_player_index=0).supported
    resolve_stack(game)
    game.resolve_upkeep(1)
    resolve_stack(game)

    assert [len(p.hand) for p in game.players] == [1, 0, 0], game.log


def test_a_repeating_delayed_ability_still_chooses_as_it_fires():
    """The control, and the reason the hoist asks for a one-shot delay: "until
    end of turn, whenever …, target player loses 1 life" triggers any number of
    times, so no single announcement at the cast could answer it. Its target is
    the delayed ability's own (CR 603.3d) and the spell announces none."""
    spell = _card(
        "Slow Fury", "Instant",
        "Until end of turn, whenever a creature you control attacks, "
        "target player loses 1 life.",
    )
    program = compile_card_oracle(spell)
    assert program.supported, program.reason
    assert derive_cast_spec(spell, program) is None

    delay = program.instructions[0]
    assert "targets" not in delay.payload and "binds_player" not in delay.payload
    assert delay.payload["instruction"].payload["targets"]["kind"] == "player"
