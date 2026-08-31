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

    # The helper takes the permanent, not a seat and a slot: it no longer
    # resolves a target of its own, so there is no index to go stale under it.
    assert game._bounce_target_creature(creature)

    assert all(card.name != "Stolen Bear" for card in p1.hand)
    assert any(card.name == "Stolen Bear" for card in p2.hand)


# ---------------------------------------------------------------------------
# 400.2 / 401.5 / 701.20a — playing with a hidden zone revealed
# ---------------------------------------------------------------------------


@pytest.mark.cr("701.20a", "400.2")
def test_701_20a_hands_revealed_shows_every_hand_to_every_player():
    """"Players play with their hands revealed." — revealing shows the card to
    *all* players (CR 701.20a), while the hand stays a hidden zone by
    classification (CR 400.2: "even if all the cards in one such zone happen
    to be revealed"). The predicate is derived from the battlefield, so the
    effect starts and stops with its source and no stored flag can go stale."""
    from engine.revealed_hands import hand_revealed_to

    source = Permanent(card=_mk_card(
        "Open Books", "Enchantment", "Players play with their hands revealed."
    ))
    p1 = PlayerState(name="P1", battlefield=[source])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    for owner in (0, 1):
        for viewer in (0, 1):
            assert hand_revealed_to(game, owner, viewer)

    game.remove_from_battlefield(source)
    assert not hand_revealed_to(game, 0, 1)
    assert not hand_revealed_to(game, 1, 0)


@pytest.mark.cr("401.5", "701.20a")
def test_401_5_players_scoped_top_reveal_covers_every_library():
    """"Players play with the top card of their libraries revealed." reveals
    *everyone's* top card from whichever battlefield the source stands on —
    unlike the own-scoped "Play with the top card of your library revealed.",
    which CR 401.5 also covers and which reaches its controller alone."""
    from engine.library_top import top_is_public

    everyone = Permanent(card=_mk_card(
        "Open Skies", "Enchantment",
        "Players play with the top card of their libraries revealed.",
    ))
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", battlefield=[everyone])
    game = Game(players=[p1, p2])

    assert top_is_public(game, 0)
    assert top_is_public(game, 1)

    game.remove_from_battlefield(everyone)
    assert not top_is_public(game, 0)
    assert not top_is_public(game, 1)

    own_only = Permanent(card=_mk_card(
        "Peeker", "Enchantment", "Play with the top card of your library revealed."
    ))
    p1.battlefield.append(own_only)
    assert top_is_public(game, 0)
    assert not top_is_public(game, 1), (
        "the own-scoped wording must not widen to the other player's library"
    )


# ---------------------------------------------------------------------------
# 402.3 — you may look at your own hand, count anyone's, and read no one else's
# ---------------------------------------------------------------------------


@pytest.mark.cr("402.3", "400.2")
def test_402_3_a_player_sees_their_own_hand_and_only_the_count_of_another():
    """"A player can't look at the cards in another player's hand but may count
    those cards at any time."

    Both halves are one payload, built per viewer: the owner's own seat gets
    card faces, every other viewer gets an opaque placeholder per position, and
    ``hand_count`` is truthful for everyone. The count is what makes the
    placeholders load-bearing rather than an omission — a hidden hand still has
    to be countable, so it cannot simply be left out of the payload."""
    from web.serialization import _serialize_player

    p1 = PlayerState(name="P1", hand=[
        _mk_card("Ancestral Recall", "Instant"),
        _mk_card("Black Lotus", "Artifact"),
        _mk_card("Time Walk", "Sorcery"),
    ])
    p2 = PlayerState(name="P2", hand=[_mk_card("Counterspell", "Instant")])
    game = Game(players=[p1, p2])

    own_view = _serialize_player(p1, 0, 0, game)
    opponent_view = _serialize_player(p1, 1, 0, game)

    assert [entry["name"] for entry in own_view["hand"]] == [
        "Ancestral Recall", "Black Lotus", "Time Walk",
    ]
    # Not a single card name reaches the other seat...
    assert opponent_view["hand"] == ["<hidden>"] * 3
    # ...and yet both agree on how many there are.
    assert own_view["hand_count"] == opponent_view["hand_count"] == 3


@pytest.mark.cr("402.3")
def test_402_3_the_count_another_player_may_take_tracks_the_hand():
    """"…may count those cards **at any time**": the count is a live read of the
    zone, not a number snapshotted when the hand was last visible. Drawing and
    discarding both move it for the opponent's view."""
    from web.serialization import _serialize_player

    p1 = PlayerState(name="P1", library=_library(["A", "B"]), hand=[_mk_card("C", "Instant")])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert _serialize_player(p1, 1, 0, game)["hand_count"] == 1

    game._draw_with_replacements(p1, 2)
    opponent_view = _serialize_player(p1, 1, 0, game)
    assert opponent_view["hand_count"] == 3
    assert opponent_view["hand"] == ["<hidden>"] * 3

    p1.graveyard.append(p1.hand.pop())
    assert _serialize_player(p1, 1, 0, game)["hand_count"] == 2


@pytest.mark.cr("402.3", "400.2")
def test_402_3_a_spectator_may_not_look_at_anyones_hand_either():
    """The rule says "another player's hand", not "an opponent's" — a viewer
    who holds no seat is not the owner of any hand, so every hand is closed to
    them. Asserted because the seat comparison is ``viewer_seat == seat`` and a
    seatless viewer is ``None``, which is exactly the value a sloppy check
    reads as "not an opponent"."""
    from web.serialization import _serialize_player

    p1 = PlayerState(name="P1", hand=[_mk_card("Ancestral Recall", "Instant")])
    p2 = PlayerState(name="P2", hand=[_mk_card("Counterspell", "Instant")])
    game = Game(players=[p1, p2])

    for seat, player in enumerate((p1, p2)):
        view = _serialize_player(player, None, seat, game)
        assert view["hand"] == ["<hidden>"]
        assert view["hand_count"] == 1


# ---------------------------------------------------------------------------
# Hand back onto the library — Brainstorm, Stunted Growth
# ---------------------------------------------------------------------------


def _hand_to_library_game(hand: list[str], library: list[str]) -> Game:
    p1 = PlayerState(
        name="P1",
        hand=[_mk_card(name, "Instant") for name in hand],
        library=_library(library),
        life=20,
    )
    p2 = PlayerState(name="P2", library=_library(["L1", "L2"]), life=20)
    game = Game(players=[p1, p2])
    game.interactive_seats = {0, 1}
    return game


@pytest.mark.cr("401.1", "402.1")
def test_401_1_cards_put_back_land_on_top_in_the_order_chosen():
    """"…on top of your library **in any order**." The first card named is the
    first one the player will draw, so the order the answer gives is the order
    the library ends up in — sorting the answer would silently take the choice
    the card offers away."""
    game = _hand_to_library_game(["A", "B", "C"], ["X", "Y"])
    game.arm_pending_choice("hand_to_library", 0, count=2)

    assert game.confirm_hand_to_library(0, [2, 0]) is True

    assert [c.name for c in game.players[0].hand] == ["B"]
    assert [c.name for c in game.players[0].library[:4]] == ["C", "A", "X", "Y"]


@pytest.mark.cr("402.1")
def test_402_1_only_one_copy_of_a_repeated_card_leaves_the_hand():
    """A hand is a list of card *definitions* and a deck repeats one object per
    copy, so an identity filter over it removes every copy while the caller puts
    exactly one somewhere. ``take_card_from_hand`` is the seam that makes it one,
    and this is the shape that finds it: two copies in hand, one named."""
    game = _hand_to_library_game(["A", "A", "B"], ["X"])
    # The deck builder repeats one object per copy; the fixture must too, or the
    # test passes against the broken version.
    game.players[0].hand[1] = game.players[0].hand[0]
    game.arm_pending_choice("hand_to_library", 0, count=1)

    assert game.confirm_hand_to_library(0, [0]) is True

    assert sorted(c.name for c in game.players[0].hand) == ["A", "B"]
    assert [c.name for c in game.players[0].library[:2]] == ["A", "X"]


@pytest.mark.cr("608.2")
def test_608_2_an_answer_that_names_too_few_cards_is_refused():
    """The prompt is owed until it is answered in full. Accepting a short answer
    would resume the steps behind it against a decision nobody made."""
    game = _hand_to_library_game(["A", "B", "C"], ["X"])
    game.arm_pending_choice("hand_to_library", 0, count=2)

    assert game.confirm_hand_to_library(0, [0]) is False
    assert game.pending_choice_of("hand_to_library", 0) is not None
    assert len(game.players[0].hand) == 3


@pytest.mark.cr("608.2")
def test_608_2_a_non_interactive_seat_answers_with_the_default():
    """An AI seat queues the prompt and the auto-resolver drains it; a prompt
    left owed would wedge every later resumable loop, because this kind
    suspends."""
    game = _hand_to_library_game(["A", "B", "C"], ["X"])
    game.interactive_seats = set()
    game.arm_pending_choice("hand_to_library", 0, count=2)
    game.auto_resolve_pending_choices()

    assert game.pending_choices == []
    assert [c.name for c in game.players[0].hand] == ["C"]
    assert [c.name for c in game.players[0].library[:2]] == ["A", "B"]


# ---------------------------------------------------------------------------
# CR 401.4 — cards put into a library at one position are arranged by the owner
# ---------------------------------------------------------------------------


def _look_top_game(library: list[str]) -> Game:
    p1 = PlayerState(
        name="P1", library=[_mk_card(n, "Artifact") for n in library], life=20
    )
    return Game(players=[p1, PlayerState(name="P2", life=20)], interactive_seats={0})


@pytest.mark.cr("401.4")
def test_401_4_the_rest_going_on_top_is_arranged_by_their_owner():
    """"…and the rest on top of your library in any order." (Diabolic Vision.)

    On the *bottom* the arrangement is unobservable and the resolver has always
    just laid the cards down. On top it is the next N draws, so CR 401.4's "may
    arrange them in any order" has to actually be asked — a second prompt,
    armed by answering the first, inside the one resolution.
    """
    game = _look_top_game(["A", "B", "C", "D", "E", "F"])
    game.arm_pending_choice(
        "look_top_pick", 0,
        top_count=5, amount=5, card_name="Diabolic Vision",
        filter={}, filters=(), optional=False,
        rest_order="any", rest_destination="library_top",
    )

    assert game.confirm_look_top_pick(0, 1) is True

    assert [c.name for c in game.players[0].hand] == ["B"]
    assert game.pending_choice_of("reorder_library", 0) is not None
    assert [c.name for c in game.players[0].library] == ["A", "C", "D", "E", "F"]

    assert game.confirm_reorder_library(0, [3, 2, 1, 0]) is True
    assert [c.name for c in game.players[0].library] == ["E", "D", "C", "A", "F"]


@pytest.mark.cr("401.4")
def test_401_4_the_rest_going_to_the_bottom_is_not_asked_about():
    """The same clause one word over, and no prompt: nothing in the game can
    observe the order of cards put on the bottom, so asking would be a decision
    with no consequence. The destination is what decides, which is why it is
    read off the card rather than defaulted."""
    game = _look_top_game(["A", "B", "C", "D"])
    game.arm_pending_choice(
        "look_top_pick", 0,
        top_count=3, amount=3, card_name="See the Truth",
        filter={}, filters=(), optional=False,
        rest_order="any", rest_destination="library_bottom",
    )

    assert game.confirm_look_top_pick(0, 0) is True

    assert game.pending_choices == []
    assert [c.name for c in game.players[0].library] == ["D", "B", "C"]


@pytest.mark.cr("401.4")
def test_401_4_a_single_card_going_back_on_top_is_no_arrangement_at_all():
    """One card has one order, so no prompt is armed — the resolution finishes
    rather than waiting on a decision with a single legal answer."""
    game = _look_top_game(["A", "B", "C"])
    game.arm_pending_choice(
        "look_top_pick", 0,
        top_count=2, amount=2, card_name="Diabolic Vision",
        filter={}, filters=(), optional=False,
        rest_order="any", rest_destination="library_top",
    )

    assert game.confirm_look_top_pick(0, 0) is True

    assert game.pending_choices == []
    assert [c.name for c in game.players[0].library] == ["B", "C"]
