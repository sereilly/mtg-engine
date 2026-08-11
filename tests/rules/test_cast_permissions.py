"""Casting and playing cards from somewhere other than the hand (CR 601.3),
through the permission seam in ``engine/cast_permissions.py``.

The rules split cleanly: the *permission* is CR 601.3 (a player can begin to
cast a spell only if a rule or effect allows it), a land played from another
zone still consumes the land drop (CR 305.1–305.2), a cast "without paying its
mana cost" locks {X} at 0 (CR 107.3b), a grant's duration follows CR 611.2a
(stated duration, or end of game bounded by the card staying the object it was,
CR 400.7), and the printed "if that spell would be put into your graveyard,
exile it instead" rider is a replacement (CR 614.1a) that follows the spell
whether it resolves or is countered.
"""

import pytest

from engine import Game, PlayerState
from engine.cast_permissions import grant_permission, permission_for
from engine.models import CardDefinition


def _mk_card(
    name: str,
    type_line: str = "Instant",
    oracle_text: str = "Draw a card.",
    mana_cost: str = "{R}",
    colors: tuple[str, ...] = ("R",),
) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=1.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw={},
    )


def _game(p1_kwargs: dict | None = None, p2_kwargs: dict | None = None) -> Game:
    return Game(players=[
        PlayerState(name="P1", **(p1_kwargs or {})),
        PlayerState(name="P2", **(p2_kwargs or {})),
    ])


@pytest.mark.cr("601.3")
def test_601_3_casting_from_the_graveyard_needs_an_effect():
    """Without a permission effect, a card in the graveyard cannot be cast —
    and the refusal names the rule rather than crashing or quietly casting."""
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell], "library": [_mk_card("Filler")]})
    result = game.cast_from_hand(0, "Test Draw", from_zone="graveyard")
    assert not result.supported
    assert "601.3" in result.details
    assert spell in game.players[0].graveyard


@pytest.mark.cr("601.3")
def test_601_3_a_permission_effect_opens_the_zone_and_is_consumed():
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell], "library": [_mk_card("Filler")]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration=None, source_name="Test Grant",
    )
    result = game.cast_from_hand(0, "Test Draw", from_zone="graveyard")
    assert result.supported, result.details
    # The spell resolved: it drew a card and went to the graveyard afterwards
    # (CR 608.2n), and the one-card grant is spent.
    assert len(game.players[0].hand) == 1
    assert not game.cast_permissions
    assert game.cast_from_hand(0, "Test Draw", from_zone="graveyard").supported is False


@pytest.mark.cr("601.3")
def test_601_3_an_opponents_grant_is_not_yours():
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell]})
    grant_permission(
        game, player_index=1, zone="graveyard", mode="cast",
        cards=[spell], duration=None, source_name="Test Grant",
    )
    assert permission_for(game, 0, spell, "graveyard") is None


@pytest.mark.cr("400.7")
def test_400_7_the_permission_dies_when_the_card_leaves_the_zone():
    """A grant names its cards by identity; a card that left the zone is a new
    object, so the permission does not follow it and does not resurrect a
    look-alike that arrives later."""
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration=None, source_name="Test Grant",
    )
    assert permission_for(game, 0, spell, "graveyard") is not None
    game.players[0].graveyard.remove(spell)
    assert permission_for(game, 0, spell, "graveyard") is None


@pytest.mark.cr("305.1", "305.2a", "305.2b")
def test_305_2_a_land_played_from_exile_consumes_the_land_drop():
    land = _mk_card(
        "Test Peak", type_line="Basic Land — Mountain",
        oracle_text="{T}: Add {R}.", mana_cost="", colors=(),
    )
    second = _mk_card(
        "Test Peak", type_line="Basic Land — Mountain",
        oracle_text="{T}: Add {R}.", mana_cost="", colors=(),
    )
    game = _game({"exile": [land], "hand": [second]})
    game.enforce_mana_costs = True
    grant_permission(
        game, player_index=0, zone="exile", mode="play",
        cards=[land], duration="end_of_turn", source_name="Test Grant",
    )
    result = game.cast_from_hand(0, "Test Peak", from_zone="exile")
    assert result.supported, result.details
    assert any(perm.card is land for perm in game.players[0].battlefield)
    # CR 305.2b: the drop is spent — the hand copy is refused this turn.
    refused = game.cast_from_hand(0, "Test Peak")
    assert not refused.supported


@pytest.mark.cr("305.1")
def test_305_1_a_cast_grant_does_not_play_a_land():
    """A land is played, never cast, so a "you may cast" permission does not
    reach it — the grant's mode has to say "play"."""
    land = _mk_card(
        "Test Peak", type_line="Basic Land — Mountain",
        oracle_text="{T}: Add {R}.", mana_cost="", colors=(),
    )
    game = _game({"exile": [land]})
    grant_permission(
        game, player_index=0, zone="exile", mode="cast",
        cards=[land], duration="end_of_turn", source_name="Test Grant",
    )
    assert permission_for(game, 0, land, "exile", as_land=True) is None
    result = game.cast_from_hand(0, "Test Peak", from_zone="exile")
    assert not result.supported


@pytest.mark.cr("107.3b", "118.9")
def test_107_3b_a_free_cast_locks_x_at_zero():
    blaze = _mk_card(
        "Test Blaze", oracle_text="Test Blaze deals X damage to any target.",
        mana_cost="{X}{R}", type_line="Sorcery",
    )
    game = _game({"hand": [blaze]})
    game.enforce_mana_costs = True
    grant_permission(
        game, player_index=0, zone="hand", mode="cast", cards=None,
        free=True, duration="end_of_turn", source_name="Test Waiver",
    )
    # An empty mana pool would refuse this cast outright; the waiver casts it
    # and the only legal choice for X is 0.
    result = game.queue_from_hand(0, "Test Blaze", use_free_permission=True)
    assert result.supported, result.details
    assert game.stack and game.stack[-1].x_value == 0
    assert game.stack[-1].cast_from_zone == "hand"


@pytest.mark.cr("611.2a", "514.2")
def test_611_2a_a_stated_duration_ends_at_cleanup_an_unstated_one_does_not():
    spell = _mk_card("Test Draw")
    other = _mk_card("Test Draw Two")
    game = _game({"graveyard": [spell, other]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration="end_of_turn", source_name="Turn Grant",
    )
    lasting = grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[other], duration=None, source_name="Lasting Grant",
    )
    game.resolve_cleanup_step(0)
    assert permission_for(game, 0, spell, "graveyard") is None
    assert permission_for(game, 0, other, "graveyard") is lasting


@pytest.mark.cr("614.1a", "608.2n")
def test_614_1a_the_exile_instead_rider_follows_the_resolving_spell():
    spell = _mk_card("Test Draw")
    game = _game({"graveyard": [spell], "library": [_mk_card("Filler")]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration=None, exile_instead=True,
        source_name="Test Grant",
    )
    result = game.cast_from_hand(0, "Test Draw", from_zone="graveyard")
    assert result.supported, result.details
    assert spell in game.players[0].exile
    assert spell not in game.players[0].graveyard


@pytest.mark.cr("614.1a")
def test_614_1a_the_rider_also_follows_a_countered_spell():
    """"Would be put into your graveyard" is not "resolves": a countered spell
    is bound the same way, so the rider has to ride the stack object rather
    than the resolution path."""
    spell = _mk_card("Test Draw")
    counter = _mk_card(
        "Test Veto", oracle_text="Counter target spell.",
        mana_cost="{U}{U}", colors=("U",),
    )
    game = _game({"graveyard": [spell]}, {"hand": [counter]})
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration=None, exile_instead=True,
        source_name="Test Grant",
    )
    queued = game.queue_from_hand(0, "Test Draw", from_zone="graveyard")
    assert queued.supported, queued.details
    countered = game.cast_from_hand(1, "Test Veto")
    assert countered.supported, countered.details
    assert spell in game.players[0].exile
    assert spell not in game.players[0].graveyard
