"""CR 702.24a's ability printed longhand, and the two records it needs.

Alliances prints the cumulative-upkeep template three ways that the keyword
line does not cover, and each one is a *rule* rather than a card:

* the ability written out with a counter of the card's own choosing
  (Phantasmal Sphere's ``+1/+1``, Rogue Skycaptain's ``wage``), in both of
  CR 118.12a's spellings;
* a [cost] whose whole content is something an **opponent** does (Varchild's
  War-Riders), which the payer spends nothing on and still may decline;
* a **seated** step skip (Ivory Gargoyle), because CR 500.7's step belongs to a
  turn and a turn belongs to a player.

Written with invented cards wherever the rule allows one, so that what is
verified is the template rather than the printing — a test naming only the real
card would pass against a version that had baked its numbers in.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.cumulative_upkeep import cumulative_upkeep_cost, scaled_cost
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle, normalize_creature_line
from engine.upkeep_costs import upkeep_cost_from_phrase

_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _creature(name: str, text: str, *, power: int = 2, toughness: int = 2):
    return CardDefinition(
        name=name, mana_cost="{1}{R}", cmc=2.0,
        type_line="Creature — Human Warrior", oracle_text=text,
        colors=("R",), color_identity=("R",), keywords=(), produced_mana=(),
        raw={
            "name": name, "type_line": "Creature — Human Warrior",
            "power": str(power), "toughness": str(toughness),
        },
    )


def _duel(perms=(), *, interactive=None):
    p1 = PlayerState(name="P1", battlefield=list(perms))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    if interactive is not None:
        game.interactive_seats = set(interactive)
    return game, p1, p2


def _on_board(card) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _settle(game):
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game._settle()


@pytest.mark.cr("702.24a", "118.12a")
def test_both_printed_spellings_of_the_keywords_definition_are_one_ability():
    """CR 118.12a: "[do something] unless [a player does something else]" means
    "[a player may do something else]. If they don't, [do something]." So the
    two word orders are one sentence and must compile to one instruction — a
    reader per spelling would be free to disagree about the escalation, which
    is the whole content of the paragraph."""
    unless = _creature(
        "Toll Warden",
        "At the beginning of your upkeep, put a toll counter on this creature, "
        "then sacrifice this creature unless you pay {2} for each toll counter "
        "on it.",
    )
    may_not = _creature(
        "Toll Herald",
        "At the beginning of your upkeep, put a toll counter on this creature. "
        "You may pay {2} for each toll counter on it. If you don't, remove all "
        "toll counters from this creature and an opponent gains control of it.",
    )
    first = compile_card_oracle(unless).triggered_abilities[0].instruction
    second = compile_card_oracle(may_not).triggered_abilities[0].instruction
    assert first.payload["per_counter"] == "toll"
    assert second.payload["per_counter"] == "toll"
    assert first.payload["mana"] == second.payload["mana"] == {"generic": 2}
    assert first.kind != second.kind, "the consequences differ, the toll does not"


@pytest.mark.cr("702.24a")
def test_the_longhand_ability_escalates_exactly_as_the_keyword_does():
    """"…for each age counter on it" is the same arithmetic whichever way the
    ability arrived, so both go through ``scaled_cost``."""
    keyword = cumulative_upkeep_cost("cumulative upkeep {2}")
    longhand = compile_card_oracle(
        _creature(
            "Toll Warden",
            "At the beginning of your upkeep, put a toll counter on this "
            "creature, then sacrifice this creature unless you pay {2} for "
            "each toll counter on it.",
        )
    ).triggered_abilities[0].instruction
    for counters in (1, 2, 5):
        assert scaled_cost(longhand, counters).mana == {
            symbol: amount * counters for symbol, amount in keyword.mana.items()
        }


@pytest.mark.cr("122.1a", "702.24a")
def test_a_pt_counter_toll_grows_the_creature_it_taxes():
    """The counter CR 702.24a names has no rules meaning; a card may print one
    that does. A ``+1/+1`` toll therefore charges more *and* makes the creature
    bigger, through the one counter write (``named_counters.add_counters``)."""
    warden = _on_board(
        _creature(
            "Growing Warden",
            "At the beginning of your upkeep, put a +1/+1 counter on this "
            "creature, then sacrifice this creature unless you pay {1} for "
            "each +1/+1 counter on it.",
            power=1, toughness=1,
        )
    )
    lands = [_on_board(_LEA["Mountain"]) for _ in range(6)]
    game, _p1, _p2 = _duel([warden] + lands, interactive={0})

    game.resolve_upkeep(0, human_choices={"Growing Warden": True})
    _settle(game)
    assert counters_on(warden, "+1/+1") == 1
    assert (warden.effective_power, warden.effective_toughness) == (2, 2)


@pytest.mark.cr("702.24a", "118.3")
def test_an_opponents_action_is_a_cost_the_payer_spends_nothing_on():
    """CR 702.24a admits *any* cost. "Have an opponent create a token" is one
    whose whole content happens on somebody else's side: it is always payable
    while an opponent lives, and CR 118.3's "fully or not at all" is what makes
    a game with none unable to pay it."""
    cost = upkeep_cost_from_phrase(
        "have an opponent create a 1/1 red Survivor creature token"
    )
    assert cost is not None
    assert cost.opponent_tokens == 1
    assert not cost.mana and not cost.life and not cost.sacrifices

    riders = _on_board(_creature("Toll Rider", "Cumulative upkeep—Have an opponent create a 1/1 red Survivor creature token."))
    game, p1, p2 = _duel([riders])
    assert game.can_pay_upkeep_cost(p1, cost)
    p2.lost = True
    assert not game.can_pay_upkeep_cost(p1, cost), "nobody to have do it"


@pytest.mark.cr("702.24a")
def test_the_opponent_token_cost_reads_the_grammars_own_token_spec():
    """The clause after "have an opponent" is an ordinary printed effect
    sentence, so it is read by the grammar rather than by a pattern beside the
    cost — one reader of "1/1 red Survivor creature token", and a differently
    printed token is data."""
    cost = upkeep_cost_from_phrase(
        "have an opponent create two 3/3 white Angel creature tokens with flying"
    )
    assert cost is not None
    assert cost.opponent_tokens == 2
    assert cost.opponent_token["power"] == 3
    assert cost.opponent_token["colors"] == ("W",)
    assert cost.opponent_token["keywords"] == ("Flying",)
    assert upkeep_cost_from_phrase("have an opponent draw a card") is None


@pytest.mark.cr("702.24a")
def test_the_opponent_token_cost_scales_with_the_age_counters():
    """CR 702.24a's "for each age counter" is about the whole cost, so the third
    upkeep hands over three tokens."""
    line = normalize_creature_line(
        "Cumulative upkeep—Have an opponent create a 1/1 red Survivor creature "
        "token."
    )
    cost = cumulative_upkeep_cost(line)
    instruction = compile_card_oracle(
        _creature(
            "Toll Rider",
            "Cumulative upkeep—Have an opponent create a 1/1 red Survivor "
            "creature token.",
        )
    ).triggered_abilities[0].instruction
    assert scaled_cost(instruction, 3).opponent_tokens == 3
    assert scaled_cost(instruction, 3).opponent_token == cost.opponent_token


@pytest.mark.cr("614.10", "500.7")
def test_a_skip_is_seated_and_waits_for_that_players_own_step():
    """CR 614.10a: a skip waits for the *next* occurrence. Which occurrences
    count is the seat's — "you skip your next draw step" is not "the next draw
    step anyone takes" — so an opponent's draw step in between neither consumes
    the record nor is eaten by it."""
    game, p1, p2 = _duel([])
    p1.library = [_LEA["Plains"]] * 5
    p2.library = [_LEA["Island"]] * 5
    game.turn = 3
    game.skip_next_step("draw", seat=0)

    game.resolve_draw_step(1)
    assert len(p2.hand) == 1, "the opponent's step is untouched"
    assert game.skip_step_counts == {(0, "draw"): 1}

    game.resolve_draw_step(0)
    assert p1.hand == [], "and the named seat's is the one that is skipped"
    assert game.skip_step_counts == {}

    game.resolve_draw_step(0)
    assert len(p1.hand) == 1, "one occurrence, not a standing effect"


@pytest.mark.cr("614.10")
def test_an_unseated_skip_still_eats_the_next_such_step():
    """The bare key is every caller written before the seat existed, and it must
    keep meaning what it meant: whoever's step comes next."""
    game, p1, p2 = _duel([])
    p1.library = [_LEA["Plains"]] * 5
    p2.library = [_LEA["Island"]] * 5
    game.turn = 3
    game.skip_next_step("draw")

    game.resolve_draw_step(1)
    assert p2.hand == []
    assert game.skip_step_counts == {}


@pytest.mark.cr("400.3", "603.7")
def test_a_delayed_self_return_lands_under_the_owners_seat():
    """CR 400.3 said out loud. The seat is read off ``base_controller_index``
    (the seat the permanent entered under), so a creature that changed hands
    before it died still goes home."""
    from engine.control import base_controller

    gargoyle = _on_board(
        _creature(
            "Homing Gargoyle",
            "When this creature dies, return it to the battlefield under its "
            "owner's control at the beginning of the next end step.",
        )
    )
    game, p1, p2 = _duel([gargoyle])
    thief = _on_board(_LEA["Control Magic"])
    game.take_control(gargoyle, 1, source=thief)
    assert base_controller(gargoyle) == 0

    game.sacrifice_permanent(gargoyle)
    _settle(game)
    game.resolve_end_step(0)
    _settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Homing Gargoyle"]
    assert p2.battlefield == []
