"""ODY W1G6 — a cost the grammar admits and the charger did not read.

Three findings, each a cost clause with **two readers** (``grammar/costs.py``
admits the line; ``oracle.parse_activated_ability_cost`` charges it) that
disagreed in the direction that never crashes — an ability cheaper than the
card:

* "Sacrifice two lands **and this artifact**" (Sandstone Deadfall, the
  ingest's red guard) was charged **nothing**: the conjoined tail reached the
  noun parser as part of the phrase and the whole phrase was refused.
* The same shape under "exile" (Zombie Assassin) refused in the grammar.
* "**Exile this card from your hand**: Add {G}." (Elvish Spirit Guide, shipped
  since Alliances) compiled with no cost at all, found by teaching
  ``test_every_admitted_cost_clause_is_charged`` to compare the source's own
  clause: on the battlefield the Guide made {G} for free as often as asked,
  and in a hand — where the card says the ability is — it could not be
  activated.

Every test here uses an invented card or asserts the shape, so nothing passes
against a table keyed by a card's name.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.activation_zones import BATTLEFIELD, HAND, ability_functions_from
from engine.grammar import GrammarError, parse_line
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, parse_activated_ability_cost


def _card(name, type_line, text, **raw):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, **raw},
    )


def _game(mine=(), hand=(), yard=()):
    permanents = [Permanent(card=card) for card in mine]
    for permanent in permanents:
        permanent.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=permanents, hand=list(hand),
                    graveyard=list(yard), life=20),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


_LAND = _card("Test Plot", "Land", "")
_SPELL = _card("Test Scrap", "Sorcery", "")


# -- "<n things> and this <permanent>" ----------------------------------------

@pytest.mark.parametrize(
    "clause, flag, chosen, count",
    [
        ("{T}, Sacrifice two lands and this artifact", "sacrifice_self",
         ("sacrifice_filter", {"type_filter": "land"}), ("sacrifice_count", 2)),
        ("Sacrifice a land and this artifact", "sacrifice_self",
         ("sacrifice_filter", {"type_filter": "land"}), ("sacrifice_count", 1)),
        ("{1}, Exile two cards from your graveyard and this creature", "exile_self",
         ("exile_filter", {}), ("exile_count", 2)),
        ("Exile a creature card from your graveyard and this enchantment", "exile_self",
         ("exile_filter", {"type_filter": "creature"}), ("exile_count", 1)),
    ],
)
def test_a_chosen_cost_and_the_source_under_one_verb_charges_both(
    clause, flag, chosen, count
):
    line = f"{clause}: Draw a card."
    parse_line(line)  # the grammar admits it…
    cost = parse_activated_ability_cost(line)  # …and the charger reads all of it
    assert getattr(cost, flag) is True
    assert getattr(cost, chosen[0]) == chosen[1]
    assert getattr(cost, count[0]) == count[1]


def test_a_second_chosen_exile_after_the_first_is_refused_not_dropped():
    # Only the source may follow the "and": a second chosen exile has no field
    # to be charged from, so the words stay unconsumed and the line refuses.
    with pytest.raises(GrammarError):
        parse_line(
            "Exile two cards from your graveyard and a creature you control: "
            "Draw a card."
        )


def test_the_source_first_spelling_keeps_its_own_reader():
    # Kyscu Drake's "Sacrifice this creature and a creature named …": the
    # conjoined-tail reader must not take it.
    cost = parse_activated_ability_cost(
        "{G}, Sacrifice this creature and a creature named Spitting Drake: "
        "Draw a card."
    )
    assert cost.sacrifice_self
    assert cost.sacrifice_filter is not None
    assert cost.sacrifice_filter.get("type_filter") == "creature"
    assert cost.sacrifice_count == 1


def test_an_invented_three_object_cost_is_paid_in_full_or_not_at_all():
    snare = _card(
        "Test Snare", "Artifact",
        "Sacrifice two lands and this artifact: You gain 3 life.",
    )
    game = _game(mine=[snare, _LAND, _LAND, _LAND])
    used = game.activate_permanent_ability(0, "Test Snare")
    assert used.supported, used.details
    assert [p.card.name for p in game.controlled_by(0)] == ["Test Plot"]
    assert game.players[0].life == 23

    short = _game(mine=[snare, _LAND])
    refused = short.activate_permanent_ability(0, "Test Snare")
    assert not refused.supported
    assert len(list(short.controlled_by(0))) == 2 and short.players[0].life == 20


def test_a_source_that_answers_the_chosen_phrase_cannot_pay_for_itself():
    # "Sacrifice two lands and this land": the source is its own entry, so two
    # *other* lands are owed — a board of the source and one more cannot pay.
    quarry = _card(
        "Test Quarry", "Land",
        "Sacrifice two lands and this land: You gain 3 life.",
    )
    game = _game(mine=[quarry, _LAND])
    refused = game.activate_permanent_ability(0, "Test Quarry")
    assert not refused.supported
    assert len(list(game.controlled_by(0))) == 2

    game = _game(mine=[quarry, _LAND, _LAND])
    used = game.activate_permanent_ability(0, "Test Quarry")
    assert used.supported, used.details
    assert not list(game.controlled_by(0))


# -- "Exile this card from your hand" -------------------------------------------

_GUIDE_TEXT = "Exile this card from your hand: Add {G}."


def test_exile_this_card_from_your_hand_is_a_cost_and_a_zone():
    guide = _card("Test Guide", "Creature — Elf Spirit", _GUIDE_TEXT, power="2", toughness="2")
    ability = compile_card_oracle(guide).activated_abilities[0]
    assert ability.cost.exile_self and ability.cost.exile_zone == "hand"
    assert ability_functions_from(ability) == HAND


def test_exiling_a_permanent_is_still_a_battlefield_ability():
    relic = _card("Test Relic", "Artifact", "Exile this artifact: You gain 3 life.")
    ability = compile_card_oracle(relic).activated_abilities[0]
    assert ability.cost.exile_self and ability.cost.exile_zone == "battlefield"
    assert ability_functions_from(ability) == BATTLEFIELD

    # …and so is one that exiles a *chosen* card from a hand.
    bloom = _card("Test Bloom", "Enchantment", "Exile a card from your hand: Add {G}{G}.")
    ability = compile_card_oracle(bloom).activated_abilities[0]
    assert not ability.cost.exile_self
    assert ability_functions_from(ability) == BATTLEFIELD


def test_the_guide_makes_no_mana_on_the_battlefield_and_one_from_a_hand():
    guide = _card("Test Guide", "Creature — Elf Spirit", _GUIDE_TEXT, power="2", toughness="2")
    game = _game(mine=[guide], hand=[guide, guide])

    refused = game.activate_permanent_ability(0, "Test Guide")
    assert not refused.supported
    assert not any(game.players[0].mana_pool.values())

    made = game.activate_from_hand(0, "Test Guide")
    assert made.supported, made.details
    # A mana ability: it never touched the stack (CR 605.3b)…
    assert not game.stack
    assert game.players[0].mana_pool["G"] == 1
    # …exactly one of the two copies in hand paid for it, into exile, and
    # nothing was discarded.
    assert [card.name for card in game.players[0].hand] == ["Test Guide"]
    assert [card.name for card in game.players[0].exile] == ["Test Guide"]
    assert not game.players[0].graveyard
    assert [p.card.name for p in game.controlled_by(0)] == ["Test Guide"]


def test_the_shipped_guide_reads_the_same_way(catalog_by_name):
    guide = catalog_by_name["Elvish Spirit Guide"]
    ability = compile_card_oracle(guide).activated_abilities[0]
    assert ability.cost.exile_self and ability_functions_from(ability) == HAND


# -- a mill cost, and what it makes of the ability ----------------------------

def test_a_mill_cost_is_read_by_both_readers_and_refused_past_the_noun():
    line = "{T}, Mill two cards: Draw a card."
    parse_line(line)
    assert parse_activated_ability_cost(line).mill_cards == 2
    assert parse_activated_ability_cost("{T}, Mill a card: Add {C}.").mill_cards == 1
    # "Mill a card from target player's library" is not this cost.
    with pytest.raises(GrammarError):
        parse_line("{T}, Mill a card from target player's library: Add {C}.")


def test_only_a_loyalty_cost_or_a_mill_cost_takes_an_ability_out_of_cr_605_1a(
    all_compiled_abilities,
):
    """``is_mana_ability`` asks the *effect* (CR 605.1a) and, of the cost, two
    things only: a loyalty cost, and — on Millikin's ruling of 2026-08-05 — a
    mill. Over every activated ability in both manifest roles, the answer for
    the ability differs from the answer for its bare instruction on exactly
    those. A third reason appearing here is a reading somebody added without
    saying which rule it was."""
    from engine.mana_payment import is_mana_ability

    differing = [
        (name, ability)
        for name, ability in all_compiled_abilities
        if is_mana_ability(ability) != is_mana_ability(ability.instruction)
    ]
    assert len(all_compiled_abilities) > 2000, len(all_compiled_abilities)
    assert differing, "Chandra, Heart of Fire's loyalty mana ability is in the pool"
    for name, ability in differing:
        assert not is_mana_ability(ability), name
        assert ability.cost.is_loyalty or ability.cost.mill_cards, name


@pytest.fixture(scope="module")
def all_compiled_abilities():
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.faces import compilation_units

    seen, found = set(), []
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        if card.name in seen:
            continue
        seen.add(card.name)
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        found.extend(
            (card.name, ability) for ability in program.activated_abilities
            if ability.instruction is not None
        )
    return found


# -- a look that bins the rest is a move out of a library ---------------------

def test_the_rest_of_a_look_reaches_the_graveyard_from_the_library(catalog_by_name):
    """"Look at the top two cards of your library. Put one of them into your
    hand and the other into your graveyard." (Waker of Waves.) The unchosen
    card left a library, and the graveyard seam was not told so — so a watcher
    of "put into your graveyard from your library" never saw it. Asked with an
    invented watcher carrying that printed condition."""
    watcher = _card(
        "Test Archivist", "Enchantment",
        "Whenever a land card is put into your graveyard from your library, "
        "you gain 2 life.",
    )
    waker = catalog_by_name["Waker of Waves"]
    forest, bolt = catalog_by_name["Forest"], catalog_by_name["Lightning Bolt"]
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[Permanent(card=watcher)], hand=[waker],
            # Both looked-at cards are lands, so whichever is kept the other
            # one is a land card reaching the graveyard from the library.
            library=[forest, forest, bolt], life=20,
        ),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)

    activated = game.activate_from_hand(0, "Waker of Waves")
    assert activated.supported, activated.details
    for _ in range(6):
        if game.stack:
            game.resolve_top_of_stack()
        if not game.stack and not game.pending_choices:
            break
        game.auto_resolve_pending_choices()

    # One Forest is in hand; the other went to the graveyard from the library,
    # beside the Waker — which was *discarded* there, and is no land.
    binned = [c.name for c in game.players[0].graveyard if c.name != "Waker of Waves"]
    assert binned == ["Forest"]
    assert [c.name for c in game.players[0].hand] == ["Forest"]
    assert game.players[0].life == 22
