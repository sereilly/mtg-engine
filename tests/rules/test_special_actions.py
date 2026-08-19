"""Comprehensive Rules Section 116 — Special Actions.

A special action is something a player *does* with priority that never uses the
stack, so nothing can respond to it and no ability sees a spell being cast. Of
the twelve CR 116.2 lists, this engine implements exactly one: 116.2a, playing
a land. The others (turning a face-down creature face up, suspend, foretell,
companion, …) belong to mechanics outside the Alpha-through-M21 pool.

The interesting assertions are all *negative* — no stack item, no cast record —
because that is the entire difference between playing a land and casting a
spell, and the two go through the same engine entry point. CR 305.2's
once-per-turn count is covered from the land side in
``test_land_play_allowance.py``; here it is cited as what makes the action a
special action rather than a spell.
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _card(name: str, type_line: str, oracle_text: str = "") -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "2", "2"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=("G",) if "Land" in type_line else (),
        raw=raw,
    )


def _forest(name: str = "Forest") -> CardDefinition:
    return _card(name, "Basic Land — Forest", "({T}: Add {G}.)")


def _game_with_hand(*cards: CardDefinition) -> tuple[Game, PlayerState]:
    p1 = PlayerState(name="P1", hand=list(cards))
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1


# ---------------------------------------------------------------------------
# 116.1 — special actions don't use the stack
# ---------------------------------------------------------------------------

@pytest.mark.cr("116.1", "116.2a")
def test_116_1_playing_a_land_never_touches_the_stack():
    """Playing a land is a special action, so it uses no stack.

    ``queue_from_hand`` is the "leave it on the stack" API and still reports
    the land *resolved*: the land branch puts the permanent onto the
    battlefield directly and never reaches ``_stack_push``.
    """
    game, p1 = _game_with_hand(_forest())

    result = game.queue_from_hand(0, "Forest")

    assert result.details == "resolved"
    assert game.stack == []
    assert [perm.card.name for perm in p1.battlefield] == ["Forest"]


@pytest.mark.cr("116.1")
def test_116_1_a_spell_by_contrast_does_use_the_stack():
    """The same entry point, the other answer — this is what pins the previous
    test to CR 116.1 rather than to an implementation detail of land handling."""
    game, p1 = _game_with_hand(_card("Grizzly Bears", "Creature — Bear"))

    result = game.queue_from_hand(0, "Grizzly Bears")

    assert result.details == "queued"
    assert len(game.stack) == 1
    assert p1.battlefield == []


@pytest.mark.cr("116.1", "116.2a")
def test_116_1_playing_a_land_is_not_casting_a_spell():
    """Nothing that watches for a spell being cast sees a land played.

    CR 116.1 keeps the special action off the stack; the consequence tested
    here is that the land is never recorded as a spell cast, which is what
    "whenever you cast" abilities and prowess read.
    """
    game, p1 = _game_with_hand(_forest(), _card("Grizzly Bears", "Creature — Bear"))

    game.queue_from_hand(0, "Forest")
    assert p1.spells_cast_this_turn == []

    game.queue_from_hand(0, "Grizzly Bears")
    assert [card.name for card in p1.spells_cast_this_turn] == ["Grizzly Bears"]


@pytest.mark.cr("116.1")
def test_116_1_a_land_play_cannot_be_responded_to():
    """Nothing can be put on the stack in response, because there is no window:
    the land is already on the battlefield when the action finishes, so an
    opponent never sees an object to respond to."""
    game, p1 = _game_with_hand(_forest())

    game.queue_from_hand(0, "Forest")

    assert game.stack == []
    assert game.is_on_battlefield(p1.battlefield[0])


# ---------------------------------------------------------------------------
# 116.2a — playing a land, and its once-per-turn default
# ---------------------------------------------------------------------------

@pytest.mark.cr("116.2a", "305.1")
def test_116_2a_the_land_goes_to_the_battlefield_from_the_zone_it_was_in():
    """To play a land is to put it onto the battlefield from the zone it was in
    — it leaves the hand and arrives in play in one action, with no
    intermediate zone."""
    game, p1 = _game_with_hand(_forest())

    game.queue_from_hand(0, "Forest")

    assert p1.hand == []
    assert p1.graveyard == []
    assert len(p1.battlefield) == 1
    assert p1.battlefield[0].card.name == "Forest"


@pytest.mark.cr("116.2a", "305.2")
def test_116_2a_only_once_during_each_of_their_turns_by_default():
    """"By default, a player can take this action only once during each of
    their turns." The count is the engine's, so it only binds when cost
    enforcement is on."""
    game, p1 = _game_with_hand(_forest("Forest 1"), _forest("Forest 2"))
    game.enforce_mana_costs = True

    assert game.cast_from_hand(0, "Forest 1").supported is True
    second = game.cast_from_hand(0, "Forest 2")

    assert second.supported is False
    assert second.details == "already played a land this turn"
    assert len(p1.battlefield) == 1


@pytest.mark.cr("116.2a", "305.2")
def test_116_2a_the_allowance_resets_on_the_players_next_turn():
    """The default is once per *their* turn, so the count is per-turn state and
    a new turn restores the action."""
    game, p1 = _game_with_hand(_forest("Forest 1"), _forest("Forest 2"))
    game.enforce_mana_costs = True
    game.cast_from_hand(0, "Forest 1")
    assert game.cast_from_hand(0, "Forest 2").supported is False

    game.start_turn(1)
    game.start_turn(0)

    assert game.cast_from_hand(0, "Forest 2").supported is True
    assert len(p1.battlefield) == 2
