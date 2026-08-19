"""Comprehensive Rules Section 114 — Emblems (and CR 408.2, the zone they live in).

An emblem is the one object in the game with abilities and nothing else: no
types, no mana cost, no colour, and no card behind it. The engine keeps one as
a dict on ``PlayerState.emblems`` — its command zone — carrying a detached
``Permanent`` whose card holds the granted text, which is what lets the ordinary
trigger machinery fire an ability that is not on the battlefield (CR 114.4).

Section 114 joined the tracked scope with M21: Liliana, Waker of the Dead and
Garruk, Unleashed both print "You get an emblem with …".
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _mk_card(name: str, type_line: str, oracle_text: str = "") -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "2", "2"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw=raw,
    )


def _emblem_maker(text: str) -> tuple[Game, PlayerState]:
    """Resolve a spell that grants an emblem, and return the game and its caster.

    A sorcery rather than an activated ability: every printed emblem-granter is
    a planeswalker's ultimate, and the quoted ability inside an activation cost
    line is not something the ability parser reads. The rules under test are
    about the emblem, not about what granted it.
    """
    source = _mk_card("Emblem Rite", "Sorcery", f'You get an emblem with "{text}"')
    p1 = PlayerState(name="P1", hand=[source])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Emblem Rite")
    return game, p1


# ---------------------------------------------------------------------------
# 114.1 / 408.2 — emblems are created in the command zone
# ---------------------------------------------------------------------------

@pytest.mark.cr("114.1", "408.2")
def test_114_1_an_emblem_is_created_in_the_command_zone():
    """"[Player] gets an emblem" puts it into that player's command zone.

    The engine's command zone for this purpose is ``PlayerState.emblems``, so
    the emblem is in no other zone: not the battlefield, not the graveyard.
    """
    game, p1 = _emblem_maker("Creatures you control get +1/+1.")

    assert len(p1.emblems) == 1
    assert p1.emblems[0]["oracle_text"] == "Creatures you control get +1/+1."
    assert not any(perm.card.name.endswith("Emblem") for perm in p1.battlefield)
    assert not any(card.name.endswith("Emblem") for card in p1.graveyard)


@pytest.mark.cr("114.2")
def test_114_2_the_emblem_belongs_to_the_player_the_effect_names():
    """"You get an emblem" gives it to the ability's controller, and to nobody
    else — the opponent's command zone stays empty."""
    game, p1 = _emblem_maker("At the beginning of your upkeep, draw a card.")
    p2 = game.players[1]

    assert len(p1.emblems) == 1
    assert p2.emblems == []


# ---------------------------------------------------------------------------
# 114.3 — an emblem has no characteristics but its abilities
# ---------------------------------------------------------------------------

@pytest.mark.cr("114.3")
def test_114_3_an_emblem_has_no_mana_cost_no_color_and_no_types():
    """An emblem has no characteristics other than its abilities. In particular
    it has no types, no mana cost and no colour — "Emblem" is not a card type,
    it is the only thing the stand-in card's type line can say."""
    game, p1 = _emblem_maker("Creatures you control have haste.")
    emblem_permanent = p1.emblems[0]["_permanent"]
    card = emblem_permanent.card

    assert card.mana_cost == ""
    assert card.cmc == 0.0
    assert card.colors == ()
    assert card.type_line == "Emblem"
    assert card.oracle_text == "Creatures you control have haste."


@pytest.mark.cr("114.3")
def test_114_3_the_emblem_records_the_card_that_created_it():
    """The emblem's name comes from its source (CR 114.3's "usually no name"
    is a display concern); what matters to the rules is that the ability text
    is the emblem's whole content, and the source is recorded beside it."""
    game, p1 = _emblem_maker("You have no maximum hand size.")

    assert p1.emblems[0]["source_name"] == "Emblem Rite"
    assert p1.emblems[0]["name"] == "Emblem Rite Emblem"


# ---------------------------------------------------------------------------
# 114.4 — abilities of emblems function in the command zone
# ---------------------------------------------------------------------------

@pytest.mark.cr("114.4")
def test_114_4_an_emblems_triggered_ability_is_visible_from_the_command_zone():
    """An emblem's abilities function where the emblem is.

    The engine reaches them through ``emblem_trigger_events``, which scans the
    ``emblems`` list for triggers the way the battlefield scan does — so the
    trigger is found without the emblem ever being a permanent in play.
    """
    from engine.events import emblem_trigger_events

    game, p1 = _emblem_maker("At the beginning of your upkeep, draw a card.")

    events = emblem_trigger_events(game, "upkeep_self", players=[p1])

    assert events, "the emblem's upkeep trigger was not seen in the command zone"
    assert all(event.get("source_permanent") is not None for event in events)


@pytest.mark.cr("114.5")
def test_114_5_an_emblem_is_neither_a_card_nor_a_permanent():
    """An emblem is not a permanent, so it is not on the battlefield and the
    control seam does not know it; and it is not a card, so it can never be in
    a library or a hand."""
    game, p1 = _emblem_maker("Creatures you control get +1/+1.")
    emblem_permanent = p1.emblems[0]["_permanent"]

    assert not game.is_on_battlefield(emblem_permanent)
    assert emblem_permanent not in [p for p in game.all_permanents()]
    assert p1.library == [] and p1.hand == []


# ---------------------------------------------------------------------------
# The printed path: a planeswalker's ultimate (M21)
# ---------------------------------------------------------------------------

@pytest.mark.cr("114.1", "114.2", "606.3")
def test_114_1_lilianas_ultimate_puts_a_real_emblem_in_the_command_zone(set_pool):
    """The rule as a card actually prints it.

    Liliana, Waker of the Dead's −7 is the pool's emblem-granter; activating it
    with enough loyalty is the whole printed path from a loyalty ability to an
    emblem in the command zone.
    """
    liliana = set_pool("M21")["Liliana, Waker of the Dead"]
    walker = Permanent(card=liliana, metadata={"loyalty_counters": 7})
    p1 = PlayerState(name="P1", battlefield=[walker])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)

    game.activate_permanent_ability(0, "Liliana, Waker of the Dead", ability_index=2)

    assert len(p1.emblems) == 1
    assert "onto the battlefield under your control" in p1.emblems[0]["oracle_text"]
