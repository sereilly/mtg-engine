"""Odyssey sorceries, W2G7: Liquid Fire.

    As an additional cost to cast this spell, choose a number between 0 and 5.
    Liquid Fire deals X damage to target creature and 5 minus X damage to that
    creature's controller, where X is the chosen number.

Declined by wave 1 with its parts measured; this is the round that landed it.
Three things the engine did not have, each general:

* an additional cost that is a **choice of a number** (CR 601.2b). The number
  is the cast's announced X — "if the value of that variable is defined in the
  text of the spell by a choice that player would make later in the
  announcement …, that player makes that choice at this time" — so it rides
  the channel an announced X already has, and a range gate refuses a number the
  card does not offer before anything is spent;
* "…, where X is **the chosen number**" as a where-clause definition, refused
  on any card no cast of which chooses one;
* "**5 minus X**" as a printed amount (`resolve_amount`'s ``minus_x``), floored
  at zero (CR 107.1b).

In a file of the group's own, as the brief names: wave 2 has no section in
`test_ody_sorceries.py`.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import (cast_announcement, choose_cast_action,
                              tap_planned_lands)
from engine.cast_costs import additional_costs, cast_announces_x
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _table(set_pool, hand, *, enforce=False, opposing_hand=()):
    """Seat 0's precombat main phase, holding *hand* (cards, or Odyssey names)."""
    ody, lea = set_pool("ODY"), set_pool("LEA")

    def card(entry):
        return ody[entry] if isinstance(entry, str) else entry

    game = Game(players=[
        PlayerState("Caster", library=[lea["Mountain"]] * 10,
                    hand=[card(entry) for entry in hand]),
        PlayerState("Victim", library=[lea["Mountain"]] * 10,
                    hand=[card(entry) for entry in opposing_hand]),
    ])
    game.enforce_mana_costs = enforce
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _invented(name, text, *, mana_cost="{R}", type_line="Sorcery"):
    """A card nobody printed, to hold a sentence to its *behaviour*."""
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power="2", toughness="2")
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=1.0, type_line=type_line,
        oracle_text=text, colors=("R",), color_identity=("R",),
        keywords=(), produced_mana=(), raw=raw,
    )


def _cast(game, name, target=None, **announcement):
    if target is not None:
        announcement["target_permanent_ids"] = [target.permanent_id]
    return game.queue_from_hand(0, name, **announcement)


# -- the card ----------------------------------------------------------------


def test_liquid_fire_compiles_with_its_cost_and_both_halves(set_pool):
    card = set_pool("ODY")["Liquid Fire"]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    (cost,) = additional_costs(card)
    assert cost.choose_number == (0, 5)
    # CR 107.3a: the chosen number is an X the caster announces, though the
    # mana cost prints none.
    assert "{X}" not in card.mana_cost.upper()
    assert cast_announces_x(card)


@pytest.mark.parametrize("chosen", range(6))
def test_liquid_fire_splits_five_damage_by_the_chosen_number(set_pool, chosen):
    lea = set_pool("LEA")
    game = _table(set_pool, ["Liquid Fire"])
    # A 6/6, so no chosen number kills it and the marked damage can be read.
    wurm = _put(game, 1, lea["Craw Wurm"])
    life = game.players[1].life

    cast = _cast(game, "Liquid Fire", wurm, x_value=chosen)
    assert cast.supported, cast.details
    # CR 601.2b: the number is announced, and an opponent sees it before
    # deciding whether to respond — on the stack object and in the log.
    assert game.stack[-1].x_value == chosen
    assert f"Caster chose {chosen} for Liquid Fire" in game.log
    resolve_stack(game)

    assert wurm.damage_marked == chosen
    assert game.players[1].life == life - (5 - chosen)
    assert game.players[0].life == 20


def test_liquid_fire_with_no_number_announced_has_chosen_zero(set_pool):
    """An unmade CR 107.3a announcement reads as 0 everywhere in this engine,
    and 0 is a number the card offers: all five go to the controller."""
    lea = set_pool("LEA")
    game = _table(set_pool, ["Liquid Fire"])
    wurm = _put(game, 1, lea["Craw Wurm"])

    assert _cast(game, "Liquid Fire", wurm).supported
    resolve_stack(game)

    assert wurm.damage_marked == 0
    assert game.players[1].life == 15


@pytest.mark.parametrize("chosen", [6, 9, -1])
def test_a_number_outside_the_range_is_refused_with_nothing_spent(set_pool, chosen):
    lea = set_pool("LEA")
    game = _table(set_pool, ["Liquid Fire"], enforce=True)
    wurm = _put(game, 1, lea["Craw Wurm"])
    game.players[0].mana_pool["R"] = 6

    cast = _cast(game, "Liquid Fire", wurm, x_value=chosen)

    assert not cast.supported
    assert f"{chosen} is not a number between 0 and 5" in cast.details
    assert not game.stack
    assert [card.name for card in game.players[0].hand] == ["Liquid Fire"]
    assert game.players[0].mana_pool["R"] == 6
    assert wurm.damage_marked == 0 and game.players[1].life == 20


@pytest.mark.parametrize("chosen", [0, 5])
def test_the_chosen_number_costs_no_mana(set_pool, chosen):
    """{4}{R}{R} whatever is chosen: nothing that prices an X may read this one."""
    lea = set_pool("LEA")
    game = _table(set_pool, ["Liquid Fire"], enforce=True)
    wurm = _put(game, 1, lea["Craw Wurm"])
    game.players[0].mana_pool["R"] = 11

    assert _cast(game, "Liquid Fire", wurm, x_value=chosen).supported
    assert game.players[0].mana_pool["R"] == 5
    # …and a spell on the stack has the mana value its mana cost gives it
    # (CR 202.3b counts an X only where the mana cost prints one).
    from engine.targeting import stack_object_mana_value

    assert stack_object_mana_value(game.stack[-1]) == 6

    # Six mana is the whole price, so five is not enough at any number.
    poor = _table(set_pool, ["Liquid Fire"], enforce=True)
    other = _put(poor, 1, lea["Craw Wurm"])
    poor.players[0].mana_pool["R"] = 5
    assert not _cast(poor, "Liquid Fire", other, x_value=chosen).supported
    assert poor.players[0].mana_pool["R"] == 5


def test_liquid_fire_names_a_creature_and_nothing_else(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool, ["Liquid Fire"])
    assert not _cast(game, "Liquid Fire", x_value=3).supported  # nothing to name

    forest = _put(game, 1, lea["Forest"])
    assert not _cast(game, "Liquid Fire", forest, x_value=3).supported
    # A player is not a target of this spell: only the creature is (the
    # controller is whoever controls it, and is never chosen).
    assert not game.queue_from_hand(
        0, "Liquid Fire", target_player_index=1, x_value=3
    ).supported
    assert game.players[1].life == 20 and not game.stack


def test_its_own_creature_makes_its_caster_the_controller(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool, ["Liquid Fire"])
    wurm = _put(game, 0, lea["Craw Wurm"])

    assert _cast(game, "Liquid Fire", wurm, x_value=1).supported
    resolve_stack(game)

    assert wurm.damage_marked == 1
    assert [player.life for player in game.players] == [16, 20]


def test_a_creature_with_protection_from_red_cannot_be_named(set_pool):
    warded = _invented(
        "W2G7 Warded", "Protection from red", type_line="Creature — Probe",
    )
    game = _table(set_pool, ["Liquid Fire"])
    blacksmith = _put(game, 1, warded)

    cast = _cast(game, "Liquid Fire", blacksmith, x_value=0)

    assert not cast.supported and not game.stack
    assert game.players[1].life == 20


def test_protection_given_in_response_spares_the_controller_too(set_pool):
    """CR 608.2b: the creature is the spell's only target. Illegal as the spell
    resolves, the spell does not resolve — and "that creature's controller"
    takes nothing, however the five was split."""
    lea = set_pool("LEA")
    ward = _invented(
        "W2G7 Ward",
        "Target creature gains protection from red until end of turn.",
        mana_cost="{W}", type_line="Instant",
    )
    game = _table(set_pool, ["Liquid Fire"], opposing_hand=[ward])
    wurm = _put(game, 1, lea["Craw Wurm"])

    assert _cast(game, "Liquid Fire", wurm, x_value=0).supported
    assert game.queue_from_hand(
        1, ward.name, target_permanent_ids=[wurm.permanent_id]
    ).supported
    resolve_stack(game)

    assert wurm.damage_marked == 0
    assert game.players[1].life == 20
    assert any("every target is illegal" in line for line in game.log)


def test_a_creature_gone_by_resolution_takes_its_controllers_damage_with_it(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool, ["Liquid Fire"])
    wurm = _put(game, 1, lea["Craw Wurm"])

    assert _cast(game, "Liquid Fire", wurm, x_value=2).supported
    game.remove_from_battlefield(wurm)
    game._permanent_to_graveyard(game.players[1], wurm)
    resolve_stack(game)

    assert game.players[1].life == 20
    assert game.players[0].graveyard[-1].name == "Liquid Fire"


def test_a_copy_keeps_the_number_its_original_chose(set_pool):
    """A copy of a spell copies the choices made as it was cast, the value of X
    among them — so the copy is not asked again and splits the five the same
    way."""
    lea = set_pool("LEA")
    game = _table(set_pool, ["Liquid Fire", lea["Fork"]])
    wurm = _put(game, 1, lea["Craw Wurm"])

    assert _cast(game, "Liquid Fire", wurm, x_value=1).supported
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported
    resolve_stack(game)

    assert wurm.damage_marked == 2
    assert game.players[1].life == 20 - 4 - 4


# -- what a client and an AI seat are told ----------------------------------


def test_the_picker_is_told_to_ask_for_a_number_and_how_large(set_pool):
    lea = set_pool("LEA")
    card = set_pool("ODY")["Liquid Fire"]
    game = _table(set_pool, ["Liquid Fire"])
    wurm = _put(game, 1, lea["Craw Wurm"])

    spec = game.cast_target_spec(0, card)

    assert spec["kind"] == "creature"
    assert spec["announces_x"] is True
    assert spec["max_x"] == 5
    assert "min_x" not in spec  # the range starts where every X box does
    assert [
        (entry["seat"], entry["name"]) for entry in spec["valid_targets"]
    ] == [(1, wurm.card.name)]


def test_an_ai_seat_announces_a_number_the_card_offers(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool, ["Liquid Fire"], enforce=True)
    for _ in range(6):
        _put(game, 0, lea["Mountain"])
    giant = _put(game, 1, lea["Hill Giant"])

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Liquid Fire"
    assert 0 <= action.x_value <= 5
    tap_planned_lands(game, 0, action)
    cast = game.queue_from_hand(0, action.card_name, **cast_announcement(action))
    assert cast.supported, cast.details
    resolve_stack(game)
    game.check_state_based_actions()
    dealt_to_face = 20 - game.players[1].life
    assert dealt_to_face == 5 - action.x_value
    assert (giant not in game.controlled_by(1)) == (action.x_value >= 3)


# -- the sentences, on cards nobody printed ---------------------------------


def test_an_invented_range_with_a_floor_refuses_zero_and_reports_the_floor(set_pool):
    ember = _invented(
        "W2G7 Ember",
        "As an additional cost to cast this spell, choose a number between 1 "
        "and 3.\nW2G7 Ember deals X damage to any target, where X is the "
        "chosen number.",
    )
    assert compile_card_oracle(ember).supported

    outcomes = {}
    for chosen in (None, 0, 1, 2, 3, 4):
        game = _table(set_pool, [ember])
        announcement = {} if chosen is None else {"x_value": chosen}
        cast = game.queue_from_hand(0, ember.name, target_player_index=1, **announcement)
        resolve_stack(game)
        outcomes[chosen] = (cast.supported, 20 - game.players[1].life)

    assert outcomes == {
        None: (False, 0), 0: (False, 0),
        1: (True, 1), 2: (True, 2), 3: (True, 3),
        4: (False, 0),
    }
    spec = _table(set_pool, [ember]).cast_target_spec(0, ember)
    assert (spec["announces_x"], spec["min_x"], spec["max_x"]) == (True, 1, 3)


def test_a_printed_number_minus_x_is_floored_at_zero(set_pool):
    """CR 107.1b: a calculation that would determine the result of an effect
    and comes out negative is zero. Cast for more X than the printed number,
    the subtracted half deals nothing rather than healing."""
    lea = set_pool("LEA")
    slag = _invented(
        "W2G7 Slag",
        "W2G7 Slag deals X damage to target creature and 2 minus X damage to "
        "that creature's controller.",
        mana_cost="{X}{R}",
    )
    assert compile_card_oracle(slag).supported
    for chosen, to_face in ((0, 2), (1, 1), (2, 0), (4, 0)):
        game = _table(set_pool, [slag])
        wurm = _put(game, 1, lea["Craw Wurm"])
        assert _cast(game, slag.name, wurm, x_value=chosen).supported
        resolve_stack(game)
        assert wurm.damage_marked == chosen
        assert game.players[1].life == 20 - to_face


@pytest.mark.parametrize("text, type_line, reason", [
    # The words without the cost: an X nobody announces.
    (
        "W2G7 Probe deals X damage to any target, where X is the chosen number.",
        "Sorcery", "defines X as a number nothing chooses",
    ),
    # A number chosen as the spell *resolves* is not the cast's X.
    (
        "Choose a number between 0 and 5.\nW2G7 Probe deals X damage to any "
        "target, where X is the chosen number.",
        "Sorcery", "defines X as a number nothing chooses",
    ),
    # A permanent's ability has an X of its own.
    (
        "As an additional cost to cast this spell, choose a number between 0 "
        "and 5.\n{T}: This creature deals X damage to any target, where X is "
        "the chosen number.",
        "Creature — Probe", "defines X as a number nothing chooses",
    ),
    # The number beside a clause that prices an X: one letter, two meanings.
    (
        "As an additional cost to cast this spell, choose a number between 0 "
        "and 5 and pay X life.\nW2G7 Probe deals X damage to any target, "
        "where X is the chosen number.",
        "Sorcery", "printed cost nothing charges",
    ),
    # A range nobody can choose from, and one this table does not read.
    (
        "As an additional cost to cast this spell, choose a number between 5 "
        "and 0.\nDraw a card.",
        "Sorcery", "printed cost nothing charges",
    ),
    (
        "As an additional cost to cast this spell, choose a number between "
        "zero and five.\nDraw a card.",
        "Sorcery", "printed cost nothing charges",
    ),
])
def test_the_sentences_refuse_where_they_would_read_another_number(
    text, type_line, reason
):
    program = compile_card_oracle(_invented("W2G7 Probe", text, type_line=type_line))
    assert not program.supported
    assert program.reason.startswith(reason), program.reason


def test_a_chosen_number_beside_a_real_cost_charges_only_the_real_cost(set_pool):
    """"…choose a number between 0 and 5 and discard a card": one card is
    discarded whatever the number, because the number prices nothing."""
    lea = set_pool("LEA")
    probe = _invented(
        "W2G7 Kindling",
        "As an additional cost to cast this spell, choose a number between 0 "
        "and 5 and discard a card.\nW2G7 Kindling deals X damage to any "
        "target, where X is the chosen number.",
    )
    assert compile_card_oracle(probe).supported
    game = _table(set_pool, [probe, lea["Forest"], lea["Forest"], lea["Forest"]])

    cast = game.queue_from_hand(0, probe.name, target_player_index=1, x_value=3)
    assert cast.supported, cast.details
    resolve_stack(game)

    assert len(game.players[0].hand) == 2
    assert game.players[1].life == 17


def test_a_mana_cost_with_x_and_a_chosen_number_cannot_be_one_announcement(set_pool):
    """No card prints the pair. The compiler cannot see a mana cost, so the
    cast is where it refuses — before anything is spent."""
    probe = _invented(
        "W2G7 Twice",
        "As an additional cost to cast this spell, choose a number between 0 "
        "and 5.\nW2G7 Twice deals X damage to any target, where X is the "
        "chosen number.",
        mana_cost="{X}{R}",
    )
    game = _table(set_pool, [probe], enforce=True)
    game.players[0].mana_pool["R"] = 9

    cast = game.queue_from_hand(0, probe.name, target_player_index=1, x_value=2)

    assert not cast.supported and "can't be cast" in cast.details
    assert game.players[0].mana_pool["R"] == 9 and game.players[1].life == 20
