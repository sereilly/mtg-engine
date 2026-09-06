"""Regression: "Sacrifice this **Aura**" is a cost, and nothing charged it.

`engine/oracle.parse_activated_ability_cost` read a card's reference to itself
in a cost through three hand-written regexes, each with its own alternation of
nouns — and every one of them listed **card types only**:
`artifact|creature|enchantment|permanent|land|token`. `Aura` and `Equipment` are
*subtypes* (CR 205.3h), so a line reading "Sacrifice this Aura:" matched none of
them and `sacrifice_self` came back False.

The failure is entirely in the player's favour and entirely silent. Nothing
crashed. No card read unsupported. `support_report.py` counted both cards, the
hollow-line census found nothing (the ability produces a real instruction), and
`parse_coverage.py` claimed the whole line. What actually happened at a table is
that **Thrull Retainer and Carapace regenerated the creature they enchant every
turn, for free, for as long as the game lasted** — an ability that works more
often than the card allows, which is this repo's standing definition of a
restriction nothing enforces.

Both are shipped cards, and the class was found from a *measured* one: Coils of
the Medusa prints the same cost, and its Weatherlight round had to read the cost
parser to know why. Four more Weatherlight Auras print it too (Phantom Wings,
Fire Whip, Briar Shield, Kithkin Armor).

The fix is the one this codebase keeps arriving at: the noun list is not spelled
here at all. `_SELF_COST_NOUNS` is derived from `engine/grammar/readers`'
`_SELF_NOUNS` — the grammar's one reading of what a card calls itself, which has
had `aura` and `equipment` in it all along — minus `card` and `spell`, neither of
which is a permanent. A second copy of a vocabulary goes stale exactly the way a
second copy of a registry does.

These tests are written to fail on the old code: each activates the ability once
and asserts the Aura is **gone**, which an uncharged cost leaves on the
battlefield while reporting the ability resolved.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, parse_activated_ability_cost


def _host() -> CardDefinition:
    return CardDefinition(
        name="Host", mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": "Host", "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def _enchanted(card: CardDefinition) -> tuple[Game, Permanent, Permanent]:
    host = Permanent(card=_host())
    host.summoning_sick = False
    aura = Permanent(card=card)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[host, aura]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    game.start_turn(0)
    game._close_current_priority_step()
    return game, host, aura


@pytest.mark.parametrize(
    "noun", ["artifact", "aura", "creature", "enchantment", "equipment",
             "land", "permanent", "token"],
)
def test_every_self_noun_a_card_can_print_is_charged_as_a_cost(noun):
    """One case per noun the grammar already knows a card calls itself by.

    Parametrized rather than asserted as a set comparison, because comparing two
    lists is something a second copy would also pass — what this asks is whether
    the *parser* charges the clause, one printed spelling at a time.
    """
    cost = parse_activated_ability_cost(f"sacrifice this {noun}: draw a card")
    assert cost.sacrifice_self, f"'sacrifice this {noun}' charged nothing"


@pytest.mark.parametrize("noun", ["card", "spell"])
def test_a_noun_that_is_not_a_permanent_is_not_a_self_sacrifice(noun):
    """The other direction, which the derivation must not widen into.

    Neither a card nor a spell is a permanent, so neither can be sacrificed as
    *this object* — and a regex that admitted them would read "sacrifice this
    card" as the source leaving the battlefield.
    """
    cost = parse_activated_ability_cost(f"sacrifice this {noun}: draw a card")
    assert not cost.sacrifice_self


@pytest.mark.parametrize("name", ["Thrull Retainer", "Carapace"])
def test_a_shipped_aura_that_sacrifices_itself_actually_leaves(catalog_by_name, name):
    """"Sacrifice this Aura: Regenerate enchanted creature."

    The assertion is the Aura's *absence* after one activation. A compiled
    `sacrifice_self` flag on its own would not catch this — what went wrong is
    that the ability could be activated again, and again, with the Aura still on
    the battlefield: free regeneration every turn from a card printed to give it
    once.
    """
    card = catalog_by_name[name]
    program = compile_card_oracle(card)
    (ability,) = program.activated_abilities
    assert ability.cost.sacrifice_self, ability.source_line

    game, host, aura = _enchanted(card)
    result = game.activate_permanent_ability(0, name)
    assert result.supported, result
    for _ in range(20):
        if not game.stack:
            break
        game.resolve_top_of_stack()
    game._settle()

    assert not game.is_on_battlefield(aura), game.log
    assert [c.name for c in game.players[0].graveyard] == [name], game.log
    with pytest.raises(ValueError):
        game.activate_permanent_ability(0, name)
