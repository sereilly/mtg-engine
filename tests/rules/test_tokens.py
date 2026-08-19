"""Comprehensive Rules Section 111 — Tokens.

A token is a marker for a permanent no card represents, which is why every rule
here is really about the boundary between the token and the ``CardDefinition``
the engine builds to stand in for it. That stand-in is a convenience of the
implementation, and CR 111.7 is the rule that stops it leaking: off the
battlefield the token ceases to exist, so the stand-in must not arrive in a
hand, a library or a graveyard as a playable card.

CR 111.7's graveyard half is also covered from the 704 side
(``test_state_based_actions.py``) and the sacrifice side
(``test_sacrifice.py``); the hand and library halves are covered here.
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.tokens import PREDEFINED_TOKENS, default_token_name, is_token_card, make_token_card


def _duel() -> tuple[Game, PlayerState, PlayerState]:
    p1, p2 = PlayerState(name="P1"), PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def _token_on_battlefield(game: Game, seat: int, name: str = "Soldier Token",
                          power: int = 1, toughness: int = 1) -> Permanent:
    card = make_token_card(name, power, toughness, "Creature — Soldier")
    token = Permanent(card=card, metadata={"is_token": True})
    game.players[seat].battlefield.append(token)
    game._sync_control()
    return token


# ---------------------------------------------------------------------------
# 111.1 / 111.2 — what a token is, and whose it is
# ---------------------------------------------------------------------------

@pytest.mark.cr("111.1")
def test_111_1_a_token_is_a_permanent_no_card_represents():
    """A token is a marker representing a permanent not represented by a card.

    So it is a real permanent on the battlefield — it has characteristics and
    answers the control seam — while no card of it exists in any other zone.
    """
    game, p1, _ = _duel()
    token = _token_on_battlefield(game, 0)

    assert game.is_on_battlefield(token)
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    assert token.is_creature
    assert p1.library == [] and p1.hand == [] and p1.graveyard == []


@pytest.mark.cr("111.2")
def test_111_2_the_creating_player_owns_and_controls_the_token():
    """The player who creates a token is its owner; it enters under their control."""
    game, _p1, _p2 = _duel()
    token = _token_on_battlefield(game, 1)

    assert game.owner_index_of(token) == 1
    assert game.controller_index_of(token) == 1
    assert game.controls(1, token)


# ---------------------------------------------------------------------------
# 111.4 — the token's name
# ---------------------------------------------------------------------------

@pytest.mark.cr("111.4")
def test_111_4_an_unnamed_token_is_named_for_its_subtypes():
    """With no name specified, the token's name is its subtype(s) plus "Token"."""
    assert default_token_name(["soldier"]) == "Soldier Token"
    assert default_token_name(["dwarf", "berserker"]) == "Dwarf Berserker Token"


@pytest.mark.cr("111.4")
def test_111_4_a_specified_name_is_kept():
    """When the creating effect names the token, that name is used as printed —
    The Hive's "Wasp", not "Insect Token"."""
    card = make_token_card("Wasp", 1, 1, "Artifact Creature — Insect")

    assert card.name == "Wasp"


# ---------------------------------------------------------------------------
# 111.7 — a token off the battlefield ceases to exist
# ---------------------------------------------------------------------------

@pytest.mark.cr("111.7", "704.5d")
def test_111_7_a_bounced_token_ceases_to_exist_instead_of_reaching_hand():
    """A token returned to its owner's hand ceases to exist.

    The permanent is gone by the time the card reaches the zone seam, so the
    flag has to travel on the stand-in card — otherwise the token arrives in
    hand as a castable card, which is the bug this pins.
    """
    game, p1, _ = _duel()
    token = _token_on_battlefield(game, 0)

    arrived = game.put_card_into_hand(p1, token.card)
    game.remove_from_battlefield(token)
    game.check_state_based_actions()

    assert arrived is False
    assert p1.hand == []
    assert not game.is_on_battlefield(token)


@pytest.mark.cr("111.7", "704.5d")
def test_111_7_a_tucked_token_does_not_reach_the_library():
    """Same rule for a library: a token put into a library ceases to exist."""
    game, p1, _ = _duel()
    token = _token_on_battlefield(game, 0)

    arrived = game.put_card_into_library(p1, token.card, position="top")
    game.remove_from_battlefield(token)
    game.check_state_based_actions()

    assert arrived is False
    assert p1.library == []


@pytest.mark.cr("111.7", "704.5d")
def test_111_7_the_state_based_action_sweeps_a_token_that_reached_a_zone():
    """The sweep is the backstop under the zone seams.

    A path that moved the stand-in card without going through
    ``put_card_into_hand`` would leak a token into a hand; 704.5d is what
    catches it, so the sweep is tested by putting one there directly.
    """
    game, p1, _ = _duel()
    token_card = make_token_card("Zombie Token", 2, 2, "Creature — Zombie")
    p1.hand.append(token_card)
    p1.graveyard.append(token_card)

    game.check_state_based_actions()

    assert p1.hand == []
    assert p1.graveyard == []


@pytest.mark.cr("111.7")
def test_111_7_a_real_card_is_untouched_by_the_sweep():
    """The sweep must key on being a token, not on anything a real card shares —
    an ordinary card in hand or graveyard stays exactly where it is."""
    game, p1, _ = _duel()
    real = CardDefinition(
        name="Grizzly Bears", mana_cost="{1}{G}", cmc=2.0,
        type_line="Creature — Bear", oracle_text="", colors=("G",),
        color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Grizzly Bears", "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
    )
    p1.hand.append(real)
    p1.graveyard.append(real)

    game.check_state_based_actions()

    assert p1.hand == [real]
    assert p1.graveyard == [real]
    assert is_token_card(real) is False


# ---------------------------------------------------------------------------
# 111.10 — predefined tokens
# ---------------------------------------------------------------------------

@pytest.mark.cr("111.10")
def test_111_10_the_predefined_treasure_token_carries_its_defined_characteristics():
    """A predefined token is created with the characteristics the CR defines for
    it, not with anything the creating card has to spell out."""
    treasure = PREDEFINED_TOKENS["treasure"]

    assert treasure["name"] == "Treasure Token"
    assert treasure["type_line"] == "Artifact — Treasure"
    assert "Add one mana of any color" in treasure["oracle_text"]


@pytest.mark.cr("111.10", "208.1")
def test_111_10_a_noncreature_token_has_no_power_or_toughness():
    """CR 208.1 gives P/T only to creatures, so a Treasure has none at all —
    "none" rather than 0/0, which would die to a state-based action the moment
    anything animated it."""
    card = make_token_card("Treasure Token", None, None, "Artifact — Treasure")

    assert card.power is None
    assert card.toughness is None
