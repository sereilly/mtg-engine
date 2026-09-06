"""Weatherlight enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G1: the top of a graveyard as a cost ---

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str) -> CardDefinition:
    """A vanilla card to stack a graveyard with."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _w1g1_game(battlefield, graveyard):
    """A game whose active seat holds *battlefield* and *graveyard*.

    The graveyard is given bottom-first, the list order CR 404.1 produces: a
    card put into a graveyard goes on top, so the last element is the top card.
    """
    for perm in battlefield:
        perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(battlefield),
                    graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def test_alms_pays_with_the_top_card_whatever_it_is(set_pool):
    """"{1}, Exile the top card of your graveyard: Prevent the next 1 damage
    that would be dealt to target creature this turn."

    The *unnarrowed* half of the family: no characteristic is named, so the top
    card pays whatever it is — a land included. That is the difference between
    this and Necratog's "top **creature** card", and the reason the filter is
    optional rather than defaulted.
    """
    alms = Permanent(card=set_pool("WTH")["Alms"])
    bear = Permanent(card=_w1g1_card("Target Bear", "Creature — Bear"))
    game = _w1g1_game([alms, bear], [
        _w1g1_card("Deep Bear", "Creature — Bear"),
        _w1g1_card("Top Land", "Land"),
    ])
    me = game.players[0]
    result = game.activate_permanent_ability(
        0, "Alms", target_player_index=0, target_permanent_index=1
    )
    assert result.supported, result.details
    assert [card.name for card in me.exile] == ["Top Land"], (
        "the top card paid, not the topmost creature card"
    )
    assert [card.name for card in me.graveyard] == ["Deep Bear"]
    game.resolve_top_of_stack()
    assert bear.damage_prevention_pool == 1, "the shield reached the target"


def test_alms_cannot_be_activated_on_an_empty_graveyard(set_pool):
    """CR 118.3 again, for the unnarrowed spelling: an empty pile has no top
    card, so the ability is unactivatable rather than free."""
    alms = Permanent(card=set_pool("WTH")["Alms"])
    bear = Permanent(card=_w1g1_card("Target Bear", "Creature — Bear"))
    game = _w1g1_game([alms, bear], [])
    result = game.activate_permanent_ability(
        0, "Alms", target_player_index=0, target_permanent_index=1
    )
    assert not result.supported
    assert not game.stack, "the ability never reached the stack"


def test_natures_kiss_pumps_the_enchanted_creature_off_the_graveyard(set_pool):
    """"{1}, Exile the top card of your graveyard: Enchanted creature gets
    +1/+1 until end of turn." The same cost on an Aura, so the payment and the
    attachment are two independent facts about one activation.
    """
    host = Permanent(card=_w1g1_card("Host Bear", "Creature — Bear"))
    kiss = Permanent(card=set_pool("WTH")["Nature's Kiss"])
    game = _w1g1_game([host, kiss], [_w1g1_card("Top Land", "Land")])
    attach_aura(kiss, host)
    me = game.players[0]
    result = game.activate_permanent_ability(0, "Nature's Kiss")
    assert result.supported, result.details
    assert [card.name for card in me.exile] == ["Top Land"]
    game.resolve_top_of_stack()
    assert (host.effective_power, host.effective_toughness) == (3, 3)
