"""Tests for Magic: The Gathering Comprehensive Rules 407 — Ante.

One test file per rule sentence of CR 407, plus the rules elsewhere in the CR
that only exist because of ante: the ante zone itself (400.1, 400.2), ownership
mattering (108.3), and a departing player's anted cards staying in the game
(800.4n).

Two of CR 407.3's three clauses are enforced at deck construction rather than
during play ("players can't include these cards in their decks or sideboards"),
so the web deck-legality validator and the game-setup endpoint are exercised
here alongside the engine — the rule is one rule, and splitting its tests across
files would hide half of it.
"""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from engine import Game, PlayerState
from engine.ante import ante_card_names, is_ante_card
from engine.models import Permanent
from web.app import _deck_summary
from web.deck_builder import build_random_deck
from web.deck_legality import validate_deck

from tests.helpers import CARDS_BY_NAME as _C, _game, _mk_card, _nosick, client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The word "ante" on its own (not "enchanted", "granted", ...) — used to find
# every card in the pool that talks about the ante zone.
_ANTE_WORD_RE = re.compile(r"\bantes?d?\b")

_ANTE_CARD_NAMES = ("Contract from Below", "Darkpact", "Demonic Attorney")


def _plain(name: str):
    """A vanilla card with no rules text, for filling libraries."""
    return _mk_card(name, "Instant", "")


def _library(size: int, prefix: str = "Card"):
    return [_plain(f"{prefix}{i}") for i in range(size)]


def _ante_game(*, libraries: int = 20, players: int = 2) -> Game:
    game = Game(
        players=[
            PlayerState(name=f"P{i + 1}", library=_library(libraries, f"P{i + 1}Card"))
            for i in range(players)
        ],
        playing_for_ante=True,
    )
    game.enforce_mana_costs = False
    return game


def _inline_deck(*extra: dict) -> list[dict]:
    """A 40-card personal deck sent inline on the create-session request."""
    filler = 40 - sum(int(e["count"]) for e in extra)
    return [*extra, {"name": "Island", "count": filler}]


def _create_session(deck: list[dict] | None = None, *, playing_for_ante: bool = False):
    body = {
        "mode": "human_vs_ai",
        "host_name": "Host",
        "host_colors": 2,
        "guest_colors": 2,
        "seed": 40701,
        "playing_for_ante": playing_for_ante,
    }
    if deck is not None:
        body["host_deck_cards"] = deck
    return client.post("/api/sessions", json=body)


# ---------------------------------------------------------------------------
# 400.1 / 400.2 — the ante zone
# ---------------------------------------------------------------------------


@pytest.mark.cr("400.1")
def test_400_1_the_ante_zone_exists():
    """"Some older cards also use the ante zone" — every player has one, empty
    until something is anted (400.1)."""
    game = _ante_game()
    assert all(player.ante == [] for player in game.players)


@pytest.mark.cr("400.1", "400.3")
def test_400_1_an_anted_card_is_in_the_ante_and_no_other_zone():
    """A card that moves to the ante zone is in exactly one zone (400.1)."""
    game = _ante_game()
    game.deal_opening_hands(0)
    p1 = game.players[0]
    anted = p1.ante[0]
    assert len(p1.ante) == 1
    assert not any(c is anted for c in p1.library)
    assert not any(c is anted for c in p1.hand)
    assert not any(c is anted for c in p1.graveyard)


@pytest.mark.cr("400.2")
def test_400_2_the_ante_is_a_public_zone():
    """"Graveyard, battlefield, stack, exile, ante, and command are public
    zones" — every player's ante is serialized to every viewer, unlike the
    hidden hand/sideboard (400.2)."""
    sid = _create_session(playing_for_ante=True).json()["session_id"]
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    # Seat 0 sees seat 1's ante contents (a hidden zone would be blanked).
    assert len(state["players"][1]["ante"]) == 1
    assert state["players"][1]["ante"][0]["name"]


# ---------------------------------------------------------------------------
# 407.1 — playing for ante is an optional variation
# ---------------------------------------------------------------------------


@pytest.mark.cr("407.1")
def test_407_1_a_game_is_not_played_for_ante_by_default():
    """"Playing Magic games for ante is now considered an optional variation"
    — so it is off unless it is turned on (407.1)."""
    game = _game(PlayerState(name="P1"), PlayerState(name="P2"))
    assert game.playing_for_ante is False


@pytest.mark.cr("407.1", "407.2")
def test_407_1_nothing_is_anted_when_not_playing_for_ante():
    """Without the variation, the start-of-game ante of 407.2 doesn't happen."""
    game = _game(
        PlayerState(name="P1", library=_library(20)),
        PlayerState(name="P2", library=_library(20)),
    )
    game.deal_opening_hands(0)
    assert [p.ante for p in game.players] == [[], []]
    assert all(len(p.library) == 13 for p in game.players)


@pytest.mark.cr("407.1")
def test_407_1_a_hosted_session_defaults_to_no_ante():
    """The "Playing for ante" game-setup option defaults to off (407.1)."""
    payload = _create_session().json()
    assert payload["state"]["playing_for_ante"] is False
    assert all(p["ante"] == [] for p in payload["state"]["players"])


@pytest.mark.cr("407.1")
def test_407_1_a_host_can_play_for_ante():
    """Ticking the option puts the game into the ante variation (407.1)."""
    payload = _create_session(playing_for_ante=True).json()
    assert payload["state"]["playing_for_ante"] is True


# ---------------------------------------------------------------------------
# 407.2 — the start-of-game ante
# ---------------------------------------------------------------------------


@pytest.mark.cr("407.2")
def test_407_2_each_player_antes_one_card_from_their_deck():
    """"Each player puts one random card from their deck into the ante zone"
    (407.2)."""
    game = _ante_game(players=3)
    game.deal_opening_hands(0)
    assert [len(p.ante) for p in game.players] == [1, 1, 1]


@pytest.mark.cr("407.2")
def test_407_2_the_anted_card_comes_out_of_the_deck():
    """The ante card leaves the library — 20 cards become 1 anted, 7 drawn,
    12 left (407.2)."""
    game = _ante_game()
    game.deal_opening_hands(0)
    p1 = game.players[0]
    assert (len(p1.ante), len(p1.hand), len(p1.library)) == (1, 7, 12)


@pytest.mark.cr("407.2")
def test_407_2_the_ante_happens_before_any_cards_are_drawn():
    """"...after determining which player goes first but before players draw
    any cards": with the shuffle stubbed out, the anted card is the one at the
    top of the deck and the opening hand is the seven cards behind it (407.2)."""
    game = _ante_game()
    with patch("random.shuffle", lambda _seq: None), patch("random.randrange", return_value=0):
        game.deal_opening_hands(0)
    p1 = game.players[0]
    assert [c.name for c in p1.ante] == ["P1Card0"]
    assert [c.name for c in p1.hand] == [f"P1Card{i}" for i in range(1, 8)]


@pytest.mark.cr("407.2")
def test_407_2_the_ante_is_logged_before_the_opening_hands():
    """The ante precedes the draw in the game log, matching the order 407.2
    prescribes."""
    game = _ante_game()
    game.deal_opening_hands(0)
    antes = [i for i, line in enumerate(game.log) if "antes" in line]
    draws = [i for i, line in enumerate(game.log) if "opening hand" in line]
    assert antes and draws and max(antes) < min(draws)


@pytest.mark.cr("407.2")
def test_407_2_a_player_with_no_deck_antes_nothing():
    """A player with an empty library has no card to ante; the game still
    starts (407.2)."""
    game = Game(
        players=[PlayerState(name="P1", library=_library(20)), PlayerState(name="P2")],
        playing_for_ante=True,
    )
    game.deal_opening_hands(0)
    assert len(game.players[0].ante) == 1
    assert game.players[1].ante == []


@pytest.mark.cr("407.2")
def test_407_2_cards_in_the_ante_may_be_examined_by_any_player():
    """"Cards in the ante zone may be examined by any player at any time" —
    the engine's view of the zone is not filtered by who is asking (407.2)."""
    game = _ante_game(players=3)
    game.deal_opening_hands(0)
    seen = game.cards_in_ante()
    assert [seat for seat, _card in seen] == [0, 1, 2]
    assert all(card is not None for _seat, card in seen)


@pytest.mark.cr("407.2")
def test_407_2_the_winner_becomes_the_owner_of_the_whole_ante():
    """"At the end of the game, the winner becomes the owner of all the cards
    in the ante zone" (407.2)."""
    game = _ante_game()
    game.deal_opening_hands(0)
    anted_names = {p.ante[0].name for p in game.players}
    game.players[1].life = 0
    game.check_state_based_actions()
    assert {c.name for c in game.players[0].ante} == anted_names
    assert game.players[1].ante == []


@pytest.mark.cr("407.2", "104.3a")
def test_407_2_a_concession_hands_the_ante_to_the_survivor():
    """A conceded game is over, so its ante is settled too (407.2)."""
    game = _ante_game()
    game.deal_opening_hands(0)
    game.concede(0)
    assert len(game.players[1].ante) == 2
    assert game.players[0].ante == []


@pytest.mark.cr("407.2")
def test_407_2_the_ante_is_awarded_only_once():
    """Re-checking a finished game doesn't move anything a second time — the
    winner already owns it (407.2)."""
    game = _ante_game()
    game.deal_opening_hands(0)
    game.players[1].life = 0
    game.check_state_based_actions()
    game.check_state_based_actions()
    assert len(game.players[0].ante) == 2


@pytest.mark.cr("407.2")
def test_407_2_the_ante_is_not_awarded_while_the_game_continues():
    """The transfer happens at the *end* of the game, not before it (407.2)."""
    game = _ante_game()
    game.deal_opening_hands(0)
    game.players[1].life = 1
    game.check_state_based_actions()
    assert len(game.players[0].ante) == 1
    assert len(game.players[1].ante) == 1


@pytest.mark.cr("407.2", "104.4a")
def test_407_2_a_draw_has_no_winner_to_take_the_ante():
    """With no winner there is nobody to become the owner of the ante (407.2,
    104.4a)."""
    game = _ante_game()
    game.deal_opening_hands(0)
    for player in game.players:
        player.life = 0
    game.check_state_based_actions()
    assert game.is_draw is True
    assert [len(p.ante) for p in game.players] == [1, 1]


@pytest.mark.cr("407.2")
def test_407_2_nothing_is_transferred_when_not_playing_for_ante():
    """A card sitting in the ante zone of a game that isn't played for ante
    (an engine-level setup) is not handed over — the rule is part of the
    variation (407.1, 407.2)."""
    game = _game(
        PlayerState(name="P1", library=_library(5)),
        PlayerState(name="P2", library=_library(5), ante=[_plain("Relic")]),
    )
    game.players[1].life = 0
    game.check_state_based_actions()
    assert game.players[0].ante == []
    assert [c.name for c in game.players[1].ante] == ["Relic"]


@pytest.mark.cr("407.2")
def test_407_2_the_web_layer_settles_the_ante_when_the_game_ends():
    """The served game state of a finished ante game shows the winner owning
    the ante (407.2)."""
    sid = _create_session(playing_for_ante=True).json()["session_id"]
    client.post(f"/api/sessions/{sid}/action", json={"action": "concede", "seat": 1})
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["status"] == "finished"
    assert len(state["players"][0]["ante"]) == 2
    assert state["players"][1]["ante"] == []


# ---------------------------------------------------------------------------
# 407.3 — the cards that may touch the ante zone
# ---------------------------------------------------------------------------


@pytest.mark.cr("407.3")
def test_407_3_the_ante_cards_are_identified_by_their_own_text(arn_by_name):
    """"A few cards have the text 'Remove this card from your deck before
    playing if you're not playing for ante.'" — that line, not a card-name
    list, is what marks them (407.3)."""
    for name in _ANTE_CARD_NAMES:
        assert is_ante_card(_C[name]) is True, name
    assert is_ante_card(arn_by_name["Jeweled Bird"]) is True
    assert is_ante_card(_C["Black Lotus"]) is False


@pytest.mark.cr("407.3")
def test_407_3_only_those_cards_touch_the_ante_zone(all_cards, arn_cards):
    """"These are the only cards that can add or remove cards from the ante
    zone or change a card's owner" — no other card in the pool so much as
    mentions the ante (407.3)."""
    offenders = [
        card.name
        for card in [*all_cards, *arn_cards]
        if _ANTE_WORD_RE.search((card.oracle_text or "").lower()) and not is_ante_card(card)
    ]
    assert offenders == []


@pytest.mark.cr("407.3")
def test_407_3_an_ante_card_may_not_be_in_a_deck_when_not_playing_for_ante():
    """"When not playing for ante, players can't include these cards in their
    decks" (407.3)."""
    result = validate_deck(
        [{"name": "Contract from Below", "count": 4}, {"name": "Swamp", "count": 56}],
        "premodern",
        _catalog_by_name(),
    )
    assert result["legal"] is False
    assert result["ante_names"] == ["Contract from Below"]
    assert any("played for ante" in problem for problem in result["problems"])


@pytest.mark.cr("407.3")
def test_407_3_the_same_deck_is_legal_in_a_game_played_for_ante():
    """The restriction is conditional on the game — with ante on, the card is
    fine (407.3)."""
    result = validate_deck(
        [{"name": "Contract from Below", "count": 4}, {"name": "Swamp", "count": 56}],
        "casual",
        _catalog_by_name(),
        playing_for_ante=True,
    )
    assert result["ante_names"] == ["Contract from Below"]
    assert result["legal"] is True


@pytest.mark.cr("407.3")
def test_407_3_the_restriction_is_not_a_format_rule():
    """407.3 holds even in a format with no banlist at all — Casual skips every
    other legality check but not this one."""
    result = validate_deck(
        [{"name": "Darkpact", "count": 1}], "casual", _catalog_by_name(),
    )
    assert result["legal"] is False
    assert result["illegal_names"] == ["Darkpact"]


@pytest.mark.cr("407.3")
def test_407_3_an_ante_card_may_not_be_in_a_sideboard_either():
    """"...in their decks or sideboards" (407.3)."""
    result = validate_deck(
        [{"name": "Swamp", "count": 60}],
        "premodern",
        _catalog_by_name(),
        sideboard=[{"name": "Demonic Attorney", "count": 1}],
    )
    assert result["legal"] is False
    assert result["ante_names"] == ["Demonic Attorney"]


@pytest.mark.cr("407.3")
def test_407_3_a_deck_summary_names_its_ante_cards():
    """The deck list the game-setup pickers read reports which cards make a
    deck ante-only (407.3)."""
    summary = _deck_summary({
        "id": "ante-deck",
        "name": "Ante",
        "format": "casual",
        "cards": [{"name": "Darkpact", "count": 4}, {"name": "Swamp", "count": 56}],
    })
    assert summary["ante_names"] == ["Darkpact"]


@pytest.mark.cr("407.3")
def test_407_3_a_deck_without_ante_cards_is_unaffected():
    summary = _deck_summary({
        "id": "plain-deck",
        "name": "Plain",
        "format": "casual",
        "cards": [{"name": "Swamp", "count": 60}],
    })
    assert summary["ante_names"] == []
    assert summary["legality"]["legal"] is True


@pytest.mark.cr("407.3")
def test_407_3_a_game_cannot_be_started_with_an_ante_deck_without_ante():
    """The deck can't be *chosen* for a game that isn't played for ante — the
    setup request is refused (407.3)."""
    response = _create_session(_inline_deck({"name": "Contract from Below", "count": 4}))
    assert response.status_code == 400
    assert "Contract from Below" in response.json()["detail"]
    assert "ante" in response.json()["detail"]


@pytest.mark.cr("407.3")
def test_407_3_the_same_deck_is_accepted_for_an_ante_game():
    response = _create_session(
        _inline_deck({"name": "Contract from Below", "count": 4}), playing_for_ante=True,
    )
    assert response.status_code == 200
    sid = response.json()["session_id"]
    from web.app import store

    library = store.get(sid).game.players[0].library
    assert sum(1 for c in library if c.name == "Contract from Below") >= 1


@pytest.mark.cr("407.3")
def test_407_3_a_sideboard_ante_card_is_refused_at_setup():
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai",
        "host_name": "Host",
        "host_colors": 2,
        "guest_colors": 2,
        "seed": 40702,
        "host_deck_cards": _inline_deck(),
        "host_deck_sideboard": [{"name": "Jeweled Bird", "count": 1}],
    })
    assert response.status_code == 400
    assert "Jeweled Bird" in response.json()["detail"]


@pytest.mark.cr("407.3")
def test_407_3_a_random_deck_leaves_the_ante_cards_out():
    """A deck built at random for a non-ante game can't contain them (407.3)."""
    from web.app import CARD_CATALOG

    for seed in range(8):
        deck, _colors = build_random_deck(CARD_CATALOG, color_count=5, seed=seed)
        assert ante_card_names(deck) == []


@pytest.mark.cr("407.3")
def test_407_3_a_random_ante_deck_may_include_them():
    """The same builder may use them when the game *is* played for ante — the
    pool is only filtered by the rule, not by taste (407.3)."""
    from web.app import CARD_CATALOG
    from web.deck_builder import _card_map, _eligible_nonlands

    pool = _eligible_nonlands(_card_map(CARD_CATALOG), {"B"}, True)
    assert "Contract from Below" in {c.name for c in pool}


@pytest.mark.cr("407.3")
def test_407_3_an_ante_card_cannot_be_brought_in_from_outside_the_game():
    """"...and these cards can't be brought into the game from outside the
    game" — Ring of Ma'rûf's replaced draw doesn't offer one (407.3)."""
    p1 = PlayerState(
        name="P1",
        library=_library(5),
        sideboard=[_C["Contract from Below"], _C["Black Lotus"]],
    )
    game = _game(p1, PlayerState(name="P2", library=_library(5)))
    game.outside_game_draw_replacements = {0}
    game._draw_with_replacements(p1, 1)
    assert [c.name for c in p1.hand] == ["Black Lotus"]
    assert [c.name for c in p1.sideboard] == ["Contract from Below"]


@pytest.mark.cr("407.3")
def test_407_3_an_ante_game_may_bring_one_in_from_outside_the_game():
    p1 = PlayerState(
        name="P1",
        library=_library(5),
        sideboard=[_C["Contract from Below"], _C["Black Lotus"]],
    )
    game = _game(p1, PlayerState(name="P2", library=_library(5)))
    game.playing_for_ante = True
    game.outside_game_draw_replacements = {0}
    game._draw_with_replacements(p1, 1)
    assert [c.name for c in p1.hand] == ["Contract from Below"]


@pytest.mark.cr("407.3")
def test_407_3_the_choice_offered_to_a_player_hides_the_ante_card():
    """An interactive player is shown only the cards they may actually take,
    and their pick resolves against that filtered list (407.3)."""
    p1 = PlayerState(
        name="P1",
        library=_library(5),
        sideboard=[_C["Contract from Below"], _C["Black Lotus"], _C["Healing Salve"]],
    )
    game = _game(p1, PlayerState(name="P2", library=_library(5)))
    game.interactive_seats = {0}
    game.outside_game_draw_replacements = {0}
    game._draw_with_replacements(p1, 1)
    assert game.pending_outside_game_draw["card_names"] == ["Black Lotus", "Healing Salve"]
    assert game.confirm_outside_game_draw(0, 1) is True
    assert [c.name for c in p1.hand] == ["Healing Salve"]
    assert [c.name for c in p1.sideboard] == ["Contract from Below", "Black Lotus"]


# ---------------------------------------------------------------------------
# 407.4 — anting an object
# ---------------------------------------------------------------------------


@pytest.mark.cr("407.4")
def test_407_4_anting_moves_the_object_out_of_the_zone_it_was_in():
    """"To ante an object is to put that object into the ante zone from
    whichever zone it's currently in" — Contract from Below antes off the top
    of the library (407.4)."""
    p1 = PlayerState(
        name="P1",
        hand=[_C["Contract from Below"]],
        library=[_C["Black Lotus"], *_library(8)],
    )
    game = _game(p1, PlayerState(name="P2"))
    assert game.cast_from_hand(0, "Contract from Below").supported
    assert [c.name for c in p1.ante] == ["Black Lotus"]
    assert not any(c.name == "Black Lotus" for c in p1.library)


@pytest.mark.cr("407.4")
def test_407_4_each_player_antes_their_own_card():
    """Demonic Attorney antes from each library into that library owner's ante
    — the owner is the player doing the anting (407.4)."""
    p1 = PlayerState(name="P1", hand=[_C["Demonic Attorney"]], library=[_plain("Mine")])
    p2 = PlayerState(name="P2", library=[_plain("Theirs")])
    game = _game(p1, p2)
    assert game.cast_from_hand(0, "Demonic Attorney").supported
    assert [c.name for c in p1.ante] == ["Mine"]
    assert [c.name for c in p2.ante] == ["Theirs"]


@pytest.mark.cr("407.4")
def test_407_4_the_owner_can_ante_their_own_permanent(arn_by_name):
    """Jeweled Bird antes itself for the player who owns it (407.4)."""
    bird = _nosick(Permanent(card=arn_by_name["Jeweled Bird"]))
    p1 = PlayerState(name="P1", battlefield=[bird], library=[_plain("Top")])
    game = _game(p1, PlayerState(name="P2"))
    assert game.queue_permanent_ability(0, "Jeweled Bird", permanent_index=0).supported
    while game.stack:
        game.resolve_top_of_stack()
    assert [c.name for c in p1.ante] == ["Jeweled Bird"]
    assert p1.battlefield == []


@pytest.mark.cr("407.4")
def test_407_4_only_the_owner_can_ante_an_object(arn_by_name):
    """"The owner of an object is the only player who can ante that object" —
    a Jeweled Bird activated by the player who stole it antes nothing, so its
    "if you do" rider does nothing either (407.4)."""
    bird = _nosick(Permanent(card=arn_by_name["Jeweled Bird"]))
    # Controlled by P2, still owned by P1 (a stolen permanent, CR 108.3).
    bird.metadata["owner_player_index"] = 0
    p1 = PlayerState(name="P1")
    p2 = PlayerState(
        name="P2", battlefield=[bird], ante=[_plain("Stake")], library=[_plain("Top")],
    )
    game = _game(p1, p2)
    assert game.queue_permanent_ability(1, "Jeweled Bird", permanent_index=0).supported
    while game.stack:
        game.resolve_top_of_stack()
    assert any(p is bird for p in p2.battlefield)
    assert p1.ante == []
    # The rider is skipped wholesale: nothing binned, nothing drawn.
    assert [c.name for c in p2.ante] == ["Stake"]
    assert p2.graveyard == []
    assert p2.hand == []


@pytest.mark.cr("407.4")
def test_407_4_anting_records_the_card_under_its_owner():
    """``ante_object`` puts the card in the named owner's ante, which is how
    ownership of anted cards is modeled (407.4)."""
    game = _ante_game()
    card = _plain("Relic")
    assert game.ante_object(1, card) is True
    assert game.players[0].ante == []
    assert [c.name for c in game.players[1].ante] == ["Relic"]


@pytest.mark.cr("407.4")
def test_407_4_a_non_owner_is_refused_by_the_ante_check():
    game = _ante_game()
    assert game.can_ante(0, 0) is True
    assert game.can_ante(1, 0) is False
    # A token (no owner among the players) can't be anted by anyone.
    assert game.can_ante(0, None) is False


# ---------------------------------------------------------------------------
# 108.3 — ownership matters only for ante
# ---------------------------------------------------------------------------


@pytest.mark.cr("108.3", "407.2")
def test_108_3_an_anted_card_stays_with_the_player_who_started_with_it():
    """"The owner of a card in the game is the player who started the game with
    it in their deck" — each player's ante holds their own cards until the game
    ends (108.3)."""
    game = _ante_game()
    with patch("random.shuffle", lambda _seq: None), patch("random.randrange", return_value=0):
        game.deal_opening_hands(0)
    assert [c.name for c in game.players[0].ante] == ["P1Card0"]
    assert [c.name for c in game.players[1].ante] == ["P2Card0"]


@pytest.mark.cr("108.3", "407.2")
def test_108_3_winning_the_game_changes_the_owner_of_the_anted_cards():
    """Ownership is otherwise irrelevant to the game rules "except for the
    rules for ante" — winning transfers it (108.3, 407.2)."""
    game = _ante_game()
    with patch("random.shuffle", lambda _seq: None), patch("random.randrange", return_value=0):
        game.deal_opening_hands(0)
    game.players[1].life = 0
    game.check_state_based_actions()
    assert {c.name for c in game.players[0].ante} == {"P1Card0", "P2Card0"}


# ---------------------------------------------------------------------------
# 800.4n — a player leaving the game
# ---------------------------------------------------------------------------


@pytest.mark.cr("800.4n")
def test_800_4n_a_departing_players_anted_cards_stay_in_the_game():
    """"When a player leaves the game, objects that player owns in the ante zone
    do not leave the game. This is an exception to rule 800.4a" (800.4n)."""
    game = _ante_game(players=3)
    game.deal_opening_hands(0)
    doomed = game.players[2]
    doomed.battlefield = [Permanent(card=_mk_card("Bear", "Creature - Bear", ""))]
    anted = doomed.ante[0].name
    doomed.life = 0
    game.check_state_based_actions()
    assert doomed.lost is True
    # 800.4a took their permanent; 800.4n spared their ante.
    assert doomed.battlefield == []
    assert [c.name for c in doomed.ante] == [anted]


@pytest.mark.cr("800.4n", "407.2")
def test_800_4n_the_eventual_winner_takes_the_departed_players_ante():
    """The cards that stayed behind are part of what the winner ends up owning
    (800.4n, 407.2)."""
    game = _ante_game(players=3)
    game.deal_opening_hands(0)
    game.players[2].life = 0
    game.check_state_based_actions()
    game.players[1].life = 0
    game.check_state_based_actions()
    assert len(game.players[0].ante) == 3
    assert game.players[1].ante == []
    assert game.players[2].ante == []


def _catalog_by_name():
    from web.app import CATALOG_BY_NAME

    return CATALOG_BY_NAME


@pytest.mark.cr("407.3")
def test_407_3_the_deck_instruction_is_claimed_on_a_creature_too():
    """The line is not an ability: it functions at deck construction, where
    ``is_ante_card`` and the deck validator implement it in full. The spell path
    has claimed it since ante was built, but the creature path had not — so
    Tempest Efreet reported "text too complex" for the one line on it the engine
    handles completely, hiding its real blocker behind a solved one."""
    from engine.ante import ANTE_DECK_TEXT, is_ante_deck_line
    from engine.models import CardDefinition
    from engine.oracle import compile_card_oracle

    assert is_ante_deck_line(ANTE_DECK_TEXT)
    assert not is_ante_deck_line("remove this card from your deck")

    card = CardDefinition(
        name="Anted Bear", mana_cost="{1}{G}", cmc=2.0,
        type_line="Creature — Bear",
        oracle_text=(
            "Remove this card from your deck before playing if you're not "
            "playing for ante."
        ),
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Anted Bear", "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
    )

    assert compile_card_oracle(card).supported
    assert is_ante_card(card), "the claim and the deck bar read one constant"
