"""Comprehensive Rules facts MMQ's step-boundary-trigger round established.

The per-card tests live in ``tests/sets/test_mmq_*.py``. What is here is the
*rule* each of them turns on, asserted with a citation so
``scripts/rules_progress.py`` can count it: which seat a trigger's words name,
when a CR 603.4 gate is checked, whose control a card put onto the battlefield
enters under, and when a computed cost is counted.
"""

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_path
from engine.game_types import OracleExecutionContext
from engine.handlers.control_flow import evaluate_condition
from engine.models import CardDefinition, Permanent
from engine.pt import add_pt_modifier
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


MMQ = {card.name: card for card in load_cards(manifest_set_path("MMQ", include_measured=True))}


def _g4r_card(name, type_line, power=None, toughness=None):
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name}, power=power, toughness=toughness,
    )


def _g4r_game():
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def _g4r_drain(game):
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()


@pytest.mark.cr("603.4")
def test_603_4_a_false_intervening_if_never_reaches_the_stack():
    """"At the beginning of your end step, **if you didn't play a land this
    turn**, you may draw a card." (Mercadian Atlas.)

    CR 603.4: the ability triggers *only if* the condition is true when the
    event occurs. So a turn with a land drop puts nothing on the stack at all —
    which is a different thing from an ability that resolves and does nothing:
    it holds no priority, cannot be countered, and nothing in response sees it.
    """
    game, p1, _p2 = _g4r_game()
    p1.battlefield.append(Permanent(card=MMQ["Mercadian Atlas"]))
    p1.library = [_g4r_card("top", "Basic Land — Forest")]
    game._sync_control()
    game.active_player_index = 0
    game.lands_played_this_turn[0] = 1
    game.resolve_end_step(0)

    assert game.stack == []
    _g4r_drain(game)
    assert p1.hand == []


@pytest.mark.cr("603.4", "113.6b")
def test_113_6b_the_gate_is_where_nether_spirit_says_it_works_from_a_graveyard():
    """"…**if this card is the only creature card in your graveyard**, you may
    return this card to the battlefield." (Nether Spirit.)

    CR 113.6b — an ability that states which zones it functions in functions
    only from those zones — and this clause is the whole of that statement:
    the effect behind it prints no source zone at all. So the condition is what
    makes the graveyard scan find the card, and the compiled program has to
    carry the claim rather than the sentence carrying it.
    """
    program = compile_card_oracle(MMQ["Nether Spirit"])
    trigger = program.triggered_abilities[0]
    assert trigger.instruction.payload["functions_from"] == "graveyard"
    gate = trigger.instruction.payload["intervening_if"]
    assert gate["kind"] == "self_only_card_of_type_in_graveyard"
    assert gate["functions_from"] == "graveyard"


@pytest.mark.cr("603.4")
def test_603_4_the_graveyard_census_is_re_asked_as_it_resolves():
    """The same condition, evaluated directly: CR 603.4 checks it again as the
    ability resolves, so a creature card that reached the graveyard in between
    stops the return."""
    game, p1, _p2 = _g4r_game()
    spirit = MMQ["Nether Spirit"]
    gate = {"kind": "self_only_card_of_type_in_graveyard", "card_type": "creature"}

    p1.graveyard = [spirit]
    context = OracleExecutionContext(caster=p1, target=p1, card=spirit)
    assert evaluate_condition(game, context, gate)

    p1.graveyard.append(_g4r_card("Latecomer", "Creature — Bear", "1", "1"))
    assert not evaluate_condition(game, context, gate)


@pytest.mark.cr("601.2c", "603.3d")
def test_601_2c_a_printed_of_their_choice_moves_the_pick_off_the_controller():
    """"At the beginning of each player's upkeep, that player may put a +1/+1
    counter on target creature **of their choice**." (Ley Line.)

    CR 601.2c has "the player" announce a target, and CR 603.3d makes that the
    triggered ability's controller — *unless the ability says otherwise*, which
    is exactly what these three words do. The engine's answer is the seat the
    firing event froze, carried as the prompt's ``chooser``.
    """
    program = compile_card_oracle(MMQ["Ley Line"])
    offer = program.triggered_abilities[0].instruction
    assert offer.payload["actor"] == "event_subject_player"
    pick = offer.payload["action"][0]
    assert pick.kind == "choose_permanent"
    assert pick.payload["chooser"] == "event_subject_player"


@pytest.mark.cr("603.10")
def test_603_10_an_end_step_aura_names_the_hosts_controller():
    """"At the beginning of the end step of enchanted creature's controller,
    this Aura deals 2 damage to **that player**…" (Insubordination.)

    CR 603.10: the ability's controller and the seat its condition names need
    not be the same player, and the seat exists only on the event the fire site
    announced. Read off the source instead, the Aura would burn its own
    controller — the card is printed to go on an opponent's creature.
    """
    game, p1, p2 = _g4r_game()
    victim = _nosick(Permanent(card=_g4r_card("Victim", "Creature — Bear", "2", "2")))
    p2.battlefield.append(victim)
    aura = Permanent(card=MMQ["Insubordination"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, victim)

    game.active_player_index = 1
    game.resolve_end_step(1)
    _g4r_drain(game)

    assert (p1.life, p2.life) == (20, 18)


@pytest.mark.cr("613.1")
def test_613_1_unnatural_hunger_reads_the_hosts_power_as_it_resolves():
    """"…deals damage equal to **that creature's power**…" (Unnatural Hunger.)

    Power is computed (CR 613), so the number is a live read of the attached
    permanent at resolution rather than anything the trigger froze — a creature
    pumped between the two deals the number it has by then.
    """
    game, p1, p2 = _g4r_game()
    host = _nosick(Permanent(card=_g4r_card("Host", "Creature — Bear", "2", "2")))
    p2.battlefield.append(host)
    aura = Permanent(card=MMQ["Unnatural Hunger"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, host)
    add_pt_modifier(host, 3, 0)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _g4r_drain(game)

    assert p2.life == 15


@pytest.mark.cr("608.2d")
def test_608_2d_an_offer_nobody_can_take_is_not_offered():
    """"…unless they sacrifice **another** creature of their choice."
    (Unnatural Hunger.)

    CR 608.2d: "a player can't choose an option that's illegal or impossible",
    and the rule's own example is a sacrifice offered to a player with no
    creature. "Another" is measured against the *enchanted* creature — an Aura
    is not a creature, so the source exclusion rules out nothing — which is what
    makes the lone host an impossible option and the damage the outcome.
    """
    game, p1, p2 = _g4r_game()
    host = _nosick(Permanent(card=_g4r_card("Host", "Creature — Bear", "3", "3")))
    p2.battlefield.append(host)
    aura = Permanent(card=MMQ["Unnatural Hunger"])
    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, host)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _g4r_drain(game)

    assert p2.life == 17
    assert [perm.card.name for perm in p2.battlefield] == ["Host"]


@pytest.mark.cr("110.2a", "701.20a")
def test_110_2a_game_preserve_puts_each_card_under_its_own_owner():
    """"Each player reveals the top card of their library. If all cards
    revealed this way are creature cards, put those cards onto the battlefield
    **under their owners' control**." (Game Preserve.)

    Two rules in one sentence. CR 701.20a: revealing shows a card and moves it
    nowhere, so each card is still on top of its own library when the second
    sentence runs — which is why the reveal has to record *which* seat each came
    from. CR 110.2a: the effect would otherwise put every card under the
    ability controller's control, and "under their owners' control" is the
    "unless the effect states otherwise" half of that rule.
    """
    game, p1, p2 = _g4r_game()
    p1.battlefield.append(Permanent(card=MMQ["Game Preserve"]))
    p1.library = [_g4r_card("Mine", "Creature — Bear", "2", "2")]
    p2.library = [_g4r_card("Theirs", "Creature — Bear", "2", "2")]
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4r_drain(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Game Preserve", "Mine"]
    assert [perm.card.name for perm in p2.battlefield] == ["Theirs"]


@pytest.mark.cr("608.2")
def test_608_2_a_scaling_toll_is_counted_when_the_ability_resolves():
    """"…unless you pay {1} **for each card in your hand**." (Extravagant
    Spirit, Megatherium.)

    CR 608.2: the resolution is where the effect's own numbers are taken, so
    the price is the hand as it stands then. Asserted through the offer itself:
    the same instruction charges 2 against a two-card hand and 1 against a
    one-card hand, with nothing about the compiled program changing.
    """
    from engine.handlers.control_flow import _offer_to_seat

    program = compile_card_oracle(MMQ["Megatherium"])
    offer = program.triggered_abilities[0].instruction

    charged = []
    for hand_size in (1, 2):
        game, p1, _p2 = _g4r_game()
        source = Permanent(card=MMQ["Megatherium"])
        p1.battlefield.append(source)
        p1.hand = [_g4r_card(f"h{i}", "Basic Land — Forest") for i in range(hand_size)]
        p1.mana_pool["G"] = 5
        game._sync_control()
        _offer_to_seat(
            game, offer,
            OracleExecutionContext(
                caster=p1, target=p1, card=source.card, source_permanent=source,
            ),
            0,
        )
        game.auto_resolve_pending_choices()
        charged.append(5 - p1.mana_pool["G"])

    assert charged == [1, 2]
