"""Tests for Magic: The Gathering Comprehensive Rules Section 4 — Zones.

Covers CR 400 (General), 401 (Library), 402 (Hand), 403 (Battlefield),
404 (Graveyard), 406 (Exile), and the drawing rules of CR 121 that describe
moving the top card of the library to the hand. CR 405 (Stack) is covered
elsewhere.
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_card(name: str, type_line: str, oracle_text: str = "", produced_mana: tuple[str, ...] = ()) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = "2"
        raw["toughness"] = "2"
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=produced_mana,
        raw=raw,
    )


def _mk_creature(name: str, power: int = 2, toughness: int = 2, oracle_text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test", "power": str(power), "toughness": str(toughness)},
    )


def _library(names: list[str]) -> list[CardDefinition]:
    return [_mk_card(name, "Instant") for name in names]


# ---------------------------------------------------------------------------
# Rule 400 — General
# ---------------------------------------------------------------------------


@pytest.mark.cr("400.1")
def test_400_1_each_player_has_own_library_hand_and_graveyard():
    """400.1: Each player has their own library, hand, and graveyard; the stack
    is a single zone shared by all players."""
    p1 = PlayerState(name="P1", library=_library(["A"]))
    p2 = PlayerState(name="P2", library=_library(["B"]))
    game = Game(players=[p1, p2])

    # Per-player zones exist and are distinct objects per player.
    for zone in ("library", "hand", "graveyard"):
        assert isinstance(getattr(p1, zone), list)
        assert isinstance(getattr(p2, zone), list)
        assert getattr(p1, zone) is not getattr(p2, zone)
    # The stack is one shared zone on the game, not per player.
    assert isinstance(game.stack, list)


@pytest.mark.cr("400.1")
def test_400_1_zone_contents_are_independent_per_player():
    """400.1: Putting a card in one player's per-player zone does not affect
    another player's corresponding zone."""
    p1 = PlayerState(name="P1", library=_library(["A", "B"]))
    p2 = PlayerState(name="P2", library=_library(["C"]))
    Game(players=[p1, p2])

    p1.draw(1)

    assert len(p1.hand) == 1
    assert len(p2.hand) == 0
    assert len(p2.library) == 1


@pytest.mark.cr("400.3", "404.1")
def test_400_3_destroyed_creature_goes_to_its_owners_graveyard():
    """400.3 / 404.1: A destroyed creature is put into its owner's graveyard,
    not the graveyard of the player whose spell destroyed it."""
    terror = _mk_card("Terror", "Instant", "Destroy target creature.")
    creature = _mk_creature("Doomed Bear")
    p1 = PlayerState(name="P1", hand=[terror])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

    assert [c.name for c in p2.graveyard] == ["Doomed Bear"]
    assert all(c.name != "Doomed Bear" for c in p1.graveyard)


@pytest.mark.cr("400.3", "402.1")
def test_400_3_bounced_creature_returns_to_its_owners_hand():
    """400.3 / 402.1: A creature returned "to its owner's hand" goes to that
    player's hand — cards can be put into a hand by effects, not only draws."""
    unsummon = _mk_card("Unsummon", "Instant", "Return target creature to its owner's hand.")
    creature = _mk_creature("Bounced Bear")
    p1 = PlayerState(name="P1", hand=[unsummon])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Unsummon", target_player_index=1, target_permanent_index=0)

    assert len(p2.battlefield) == 0
    assert [c.name for c in p2.hand] == ["Bounced Bear"]
    assert all(c.name != "Bounced Bear" for c in p1.hand)


@pytest.mark.cr("400.7", "403.4")
def test_400_7_creature_recast_after_bounce_is_a_new_object():
    """400.7 / 403.4: An object that changes zones becomes a new object. A
    tapped, damaged, pumped creature that is bounced and recast re-enters the
    battlefield as a fresh permanent with none of its previous state."""
    unsummon = _mk_card("Unsummon", "Instant", "Return target creature to its owner's hand.")
    creature = _mk_creature("Memory Bear", 2, 4)
    original = Permanent(card=creature, tapped=True, power_bonus=2, toughness_bonus=2, damage_marked=3)
    p1 = PlayerState(name="P1", hand=[unsummon])
    p2 = PlayerState(name="P2", battlefield=[original])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Unsummon", target_player_index=1, target_permanent_index=0)
    assert [c.name for c in p2.hand] == ["Memory Bear"]

    game.cast_from_hand(1, "Memory Bear")

    assert len(p2.battlefield) == 1
    recast = p2.battlefield[0]
    assert recast is not original
    assert recast.tapped is False
    assert recast.power_bonus == 0
    assert recast.toughness_bonus == 0
    assert recast.damage_marked == 0


@pytest.mark.cr("400.7", "403.4")
def test_400_7_creature_returning_from_temporary_exile_is_a_new_object():
    """400.7 / 403.4: A creature exiled "until end of turn" returns to the
    battlefield as a new object — untapped and without its earlier P/T bonus."""
    banish = _mk_card("Banish", "Instant", "Exile target creature until end of turn.")
    creature = _mk_creature("Blinking Bear")
    original = Permanent(card=creature, tapped=True, power_bonus=3)
    p1 = PlayerState(name="P1", hand=[banish])
    p2 = PlayerState(name="P2", battlefield=[original])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Banish", target_player_index=1, target_permanent_index=0)
    assert [c.name for c in p2.exile] == ["Blinking Bear"]

    game.resolve_cleanup_step(0)

    assert p2.exile == []
    assert len(p2.battlefield) == 1
    returned = p2.battlefield[0]
    assert returned is not original
    assert returned.tapped is False
    assert returned.power_bonus == 0


# ---------------------------------------------------------------------------
# Rule 401 — Library
# ---------------------------------------------------------------------------


@pytest.mark.cr("400.5", "401.2")
def test_401_2_drawing_does_not_change_the_order_of_the_remaining_library():
    """400.5 / 401.2: The order of a library can't be changed except when a
    rule or effect allows it — drawing removes only the top card and leaves
    the rest of the library in its existing order."""
    p1 = PlayerState(name="P1", library=_library(["A", "B", "C", "D", "E"]))
    p2 = PlayerState(name="P2")
    Game(players=[p1, p2])

    p1.draw(2)

    assert [c.name for c in p1.library] == ["C", "D", "E"]


# ---------------------------------------------------------------------------
# Rule 402 — Hand
# ---------------------------------------------------------------------------


@pytest.mark.cr("402.1")
def test_402_1_hand_holds_drawn_cards():
    """402.1: The hand is where a player holds cards that have been drawn; at
    the beginning of the game each player draws seven cards into it."""
    p1 = PlayerState(name="P1", library=_library([f"C{i}" for i in range(20)]))
    p2 = PlayerState(name="P2", library=_library([f"D{i}" for i in range(20)]))
    game = Game(players=[p1, p2])

    game.deal_opening_hands(0)

    assert len(p1.hand) == 7
    assert len(p2.hand) == 7
    # A later draw also goes to the hand.
    p1.draw(1)
    assert len(p1.hand) == 8


@pytest.mark.cr("402.2", "514.1")
def test_402_2_cleanup_discards_down_to_maximum_hand_size():
    """402.2 / 514.1: A player with more than seven cards in hand discards
    down to seven as part of their cleanup step."""
    p1 = PlayerState(name="P1", hand=_library([f"C{i}" for i in range(10)]))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_cleanup_step(0)

    assert len(p1.hand) == 7
    assert len(p1.graveyard) == 3


@pytest.mark.cr("402.2")
def test_402_2_no_discard_at_or_below_maximum_hand_size():
    """402.2: A player at or below the maximum hand size discards nothing."""
    p1 = PlayerState(name="P1", hand=_library([f"C{i}" for i in range(7)]))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_cleanup_step(0)

    assert len(p1.hand) == 7
    assert len(p1.graveyard) == 0


@pytest.mark.cr("402.2", "514.1")
def test_402_2_player_chooses_which_excess_cards_to_discard():
    """402.2 / 514.1: The player discards excess cards of their choice."""
    p1 = PlayerState(name="P1", hand=_library(["A", "B", "C", "D", "E", "F", "G", "H", "I"]))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_cleanup_step(0, discard_hand_indices=[0, 8])

    assert [c.name for c in p1.hand] == ["B", "C", "D", "E", "F", "G", "H"]
    assert sorted(c.name for c in p1.graveyard) == ["A", "I"]


@pytest.mark.cr("402.2")
def test_402_2_effect_can_remove_maximum_hand_size():
    """402.2: An effect can set a player's maximum hand size to unlimited
    (e.g. Library of Leng); that player discards nothing at cleanup."""
    p1 = PlayerState(name="P1", hand=_library([f"C{i}" for i in range(10)]), has_no_max_hand_size=True)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_cleanup_step(0)

    assert len(p1.hand) == 10
    assert len(p1.graveyard) == 0


@pytest.mark.cr("402.2", "514.1")
def test_402_2_only_the_active_player_discards_in_their_cleanup_step():
    """402.2 / 514.1: The discard to maximum hand size happens as part of a
    player's own cleanup step; another player's cleanup does not force it."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", hand=_library([f"C{i}" for i in range(9)]))
    game = Game(players=[p1, p2])

    game.resolve_cleanup_step(0)  # P1's cleanup, not P2's

    assert len(p2.hand) == 9
    assert len(p2.graveyard) == 0


# ---------------------------------------------------------------------------
# Rule 403 — Battlefield
# ---------------------------------------------------------------------------


@pytest.mark.cr("403.1")
def test_403_1_battlefield_starts_out_empty():
    """403.1: The battlefield starts out empty."""
    p1 = PlayerState(name="P1", library=_library(["A"]))
    p2 = PlayerState(name="P2", library=_library(["B"]))
    Game(players=[p1, p2])

    assert p1.battlefield == []
    assert p2.battlefield == []


@pytest.mark.cr("403.1", "403.3")
def test_403_3_resolved_permanent_cards_become_permanents_on_the_battlefield():
    """403.1 / 403.3: Permanent cards that resolve (a creature) or are played
    (a land) end up on the battlefield, and every object there is a permanent."""
    creature = _mk_creature("Field Bear")
    forest = _mk_card("Forest", "Basic Land — Forest", produced_mana=("G",))
    p1 = PlayerState(name="P1", hand=[creature, forest])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Field Bear")
    game.cast_from_hand(0, "Forest")

    assert p1.hand == []
    assert [perm.card.name for perm in p1.battlefield] == ["Field Bear", "Forest"]
    assert all(isinstance(perm, Permanent) for perm in p1.battlefield)


@pytest.mark.cr("403.3", "404.1")
def test_403_3_instants_never_remain_on_the_battlefield():
    """403.3 / 404.1: An instant is not a permanent — after it finishes
    resolving it is put into its owner's graveyard, never onto the battlefield."""
    terror = _mk_card("Terror", "Instant", "Destroy target creature.")
    creature = _mk_creature("Victim Bear")
    p1 = PlayerState(name="P1", hand=[terror])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

    assert all(perm.card.name != "Terror" for perm in p1.battlefield)
    assert [c.name for c in p1.graveyard] == ["Terror"]


# ---------------------------------------------------------------------------
# Rule 404 — Graveyard
# ---------------------------------------------------------------------------


@pytest.mark.cr("404.1")
def test_404_1_graveyards_start_out_empty():
    """404.1: Each player's graveyard starts out empty."""
    p1 = PlayerState(name="P1", library=_library(["A"]))
    p2 = PlayerState(name="P2", library=_library(["B"]))
    Game(players=[p1, p2])

    assert p1.graveyard == []
    assert p2.graveyard == []


@pytest.mark.cr("404.1")
def test_404_1_cards_are_put_on_top_of_the_graveyard():
    """404.1: Objects put into a graveyard go on top of it — the most recently
    destroyed creature sits above the earlier one (the engine keeps the top of
    the graveyard at the end of the list)."""
    terrors = [
        _mk_card("Terror", "Instant", "Destroy target creature."),
        _mk_card("Terror", "Instant", "Destroy target creature."),
    ]
    first = _mk_creature("First Bear")
    second = _mk_creature("Second Bear")
    p1 = PlayerState(name="P1", hand=terrors)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=first), Permanent(card=second)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)
    game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

    assert [c.name for c in p2.graveyard] == ["First Bear", "Second Bear"]
    assert p2.graveyard[-1].name == "Second Bear"  # most recent on top


# ---------------------------------------------------------------------------
# Rule 406 — Exile
# ---------------------------------------------------------------------------


@pytest.mark.cr("406.2")
def test_406_2_exiled_creature_is_put_into_the_exile_zone(cards):
    """406.2: To exile an object is to put it into the exile zone from
    whatever zone it's in — Swords to Plowshares moves the creature from the
    battlefield to exile, not to the graveyard."""
    creature = _mk_creature("Plowed Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[cards["Swords to Plowshares"]])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

    assert p2.battlefield == []
    assert [c.name for c in p2.exile] == ["Plowed Bear"]
    assert p2.graveyard == []


@pytest.mark.cr("406.1")
def test_406_1_some_effects_exile_only_temporarily():
    """406.1: The exile zone is a holding area; some spells exile an object
    only temporarily — a creature exiled until end of turn waits in exile and
    returns to the battlefield when the turn ends."""
    banish = _mk_card("Banish", "Instant", "Exile target creature until end of turn.")
    creature = _mk_creature("Held Bear")
    p1 = PlayerState(name="P1", hand=[banish])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Banish", target_player_index=1, target_permanent_index=0)

    # Held in exile: on no battlefield, in no graveyard.
    assert p2.battlefield == []
    assert [c.name for c in p2.exile] == ["Held Bear"]
    assert p2.graveyard == []

    game.resolve_cleanup_step(0)

    assert p2.exile == []
    assert [perm.card.name for perm in p2.battlefield] == ["Held Bear"]


# ---------------------------------------------------------------------------
# Rule 121 — Drawing a Card
# ---------------------------------------------------------------------------


@pytest.mark.cr("121.1")
def test_121_1_drawing_puts_the_top_card_of_the_library_into_the_hand():
    """121.1: A player draws a card by putting the top card of their library
    into their hand."""
    p1 = PlayerState(name="P1", library=_library(["Top", "Middle", "Bottom"]))
    p2 = PlayerState(name="P2")
    Game(players=[p1, p2])

    drawn = p1.draw(1)

    assert drawn == 1
    assert [c.name for c in p1.hand] == ["Top"]
    assert [c.name for c in p1.library] == ["Middle", "Bottom"]


@pytest.mark.cr("121.1", "121.2")
def test_121_2_multiple_draws_are_performed_one_at_a_time():
    """121.2: An instruction to draw multiple cards is performed as that many
    individual draws — each takes the current top card, so the hand receives
    the cards in library order."""
    p1 = PlayerState(name="P1", library=_library(["A", "B", "C", "D"]))
    p2 = PlayerState(name="P2")
    Game(players=[p1, p2])

    drawn = p1.draw(3)

    assert drawn == 3
    assert [c.name for c in p1.hand] == ["A", "B", "C"]
    assert [c.name for c in p1.library] == ["D"]


@pytest.mark.cr("121.1")
def test_121_1_draw_effect_of_a_spell_draws_from_the_top():
    """121.1: Drawing may also happen as the effect of a spell; those draws
    also take the top card(s) of the library."""
    ancestral = _mk_card("Ancestral Study", "Instant", "Target player draws three cards.")
    p1 = PlayerState(name="P1", hand=[ancestral], library=_library(["A", "B", "C", "D"]))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Ancestral Study", target_player_index=0)

    assert [c.name for c in p1.hand] == ["A", "B", "C"]
    assert [c.name for c in p1.library] == ["D"]


# ---------------------------------------------------------------------------
# 400.3 — a stolen permanent's card leaves to its OWNER's zone
# ---------------------------------------------------------------------------


def _steal_setup():
    """P1 controls a thief source that stole P2's creature (Control Magic
    shape, recorded as a CR 613 layer-2 contribution from the thief)."""
    creature = Permanent(card=_mk_creature("Stolen Bear"))
    thief = Permanent(card=_mk_card("Thief Aura", "Enchantment - Aura", "You control enchanted creature."))
    p1 = PlayerState(name="P1", battlefield=[thief])
    p2 = PlayerState(name="P2", battlefield=[creature])
    game = Game(players=[p1, p2])
    assert game.take_control(creature, p1, source=thief)
    assert any(p is creature for p in p1.battlefield)  # now controlled by P1
    return game, p1, p2, creature


@pytest.mark.cr("400.3")
def test_400_3_stolen_creature_dies_into_owners_graveyard():
    """A stolen creature that dies goes to its owner's graveyard, not its
    current controller's (400.3)."""
    game, p1, p2, creature = _steal_setup()

    game._mark_damage_on_permanent(creature, 10, source=None)
    game.check_state_based_actions()

    assert creature not in p1.battlefield
    assert all(card.name != "Stolen Bear" for card in p1.graveyard)
    assert any(card.name == "Stolen Bear" for card in p2.graveyard)


@pytest.mark.cr("400.3")
def test_400_3_stolen_creature_bounces_to_owners_hand():
    """A stolen creature returned to hand goes to its owner's hand (400.3)."""
    game, p1, p2, creature = _steal_setup()
    index = p1.battlefield.index(creature)

    assert game._bounce_target_creature(p1, index)

    assert all(card.name != "Stolen Bear" for card in p1.hand)
    assert any(card.name == "Stolen Bear" for card in p2.hand)
