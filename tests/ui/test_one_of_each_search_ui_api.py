"""Web-API tests for a search that finds one card per printed description.

Guided Passage's shape, armed directly because a measured set's card cannot be
put in a web deck: an **opponent** chooses, out of the caster's library, a
creature card, a land card and a noncreature, nonland card, and the cards go to
the library owner's hand. What the client is sent and what the wire accepts are
pinned here; the engine half is `tests/engine/test_search_one_of_each.py`.

What these hold is the contract the dialog needs: the prompt reaches the seat
that chooses and nobody else, the cards it shows are the *other* seat's
library, the per-find descriptions ride beside the union `legal_indices` is,
and an answer that is not one card per description is a 400 with nothing moved.

Wave 1 could not touch the client, so the dialog offered two creatures and said
"your hand" to the opponent. Wave 2 built it — the descriptions as slots, a
second card for a filled one refused, the library and the destination worded
from the payload — and drove it in a browser; the tests from "Wave 2" down pin
what that needed from the wire and ratchet the client's side of it.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from web.app import app, store
from tests.helpers import LEA_PATH

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(LEA_PATH)}
_LIBRARY = ["Forest", "Hill Giant", "Grizzly Bears", "Sol Ring", "Clockwork Beast"]
_DESCRIBED = [
    {"card_type": "creature"},
    {"card_type": "land"},
    {"exclude_types": ["creature", "land"]},
]


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 909,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = []
    game.players[1].hand = []
    game.players[0].library = [_CARDS[name] for name in _LIBRARY]
    session.current_turn = 0
    game.active_player_index = 0
    game.arm_pending_choice(
        "search_library", 1,
        zone_seat=0, count=3, card_type="any", zones=("library",),
        restrictions={"one_of_each": [dict(slot) for slot in _DESCRIBED]},
        destination="hand", destinations=["hand"] * 3, tapped=[False] * 3,
        card_name="Guided Passage",
    )
    return sid, session, game


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _confirm(sid: str, seat: int, *indices: int):
    return client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": seat,
            "action": "search_library_confirm",
            "search_picks": [{"zone": "library", "index": i} for i in indices],
        },
    )


def test_the_choosing_seat_is_shown_the_other_seats_library_and_the_descriptions():
    sid, _session_obj, _game = _session()

    prompt = _state(sid, 1)["search_library"]
    assert prompt is not None
    assert prompt["caster_seat"] == 1
    assert [card["name"] for card in prompt["cards"]] == _LIBRARY
    assert prompt["legal_indices"] == [0, 1, 2, 3, 4], "every card fills some description"
    assert prompt["multi"] is True and prompt["max_picks"] == 3
    assert prompt["up_to"] is False, "nothing here is optional"
    # The descriptions in the engine's own words, each now also saying what to
    # call it and which cards answer it (wave 2 — see the tests at the bottom).
    assert [
        {key: value for key, value in slot.items() if key not in ("label", "legal_indices")}
        for slot in prompt["one_of_each"]
    ] == _DESCRIBED

    assert _state(sid, 0)["search_library"] is None, "the library's owner is not asked"


def test_an_answer_that_is_not_one_card_per_description_is_refused():
    sid, _session_obj, game = _session()

    for indices in ((1, 2, 0), (1, 0), (4, 0, 2)):
        refused = _confirm(sid, 1, *indices)
        assert refused.status_code == 400, indices
    assert _confirm(sid, 0, 1, 0, 3).status_code == 400, "not the owner's to answer"
    assert [card.name for card in game.players[0].library] == _LIBRARY
    assert _state(sid, 1)["search_library"] is not None, "still owed"


def test_the_answer_lands_in_the_library_owners_hand():
    sid, _session_obj, game = _session()

    accepted = _confirm(sid, 1, 4, 0, 3)
    assert accepted.status_code == 200, accepted.text

    assert [card.name for card in game.players[0].hand] == [
        "Clockwork Beast", "Forest", "Sol Ring",
    ]
    assert game.players[1].hand == []
    assert sorted(card.name for card in game.players[0].library) == [
        "Grizzly Bears", "Hill Giant",
    ]
    assert _state(sid, 1)["search_library"] is None


# ---------------------------------------------------------------------------
# Wave 2: what a dialog needs to show the descriptions as slots
# ---------------------------------------------------------------------------


def test_each_description_says_what_to_call_it_and_which_cards_answer_it():
    """The union ``legal_indices`` cannot say that two creatures are each legal
    and together a refusal. Per description: a label a player reads and the
    library indices that answer it, by the predicate the resolver assigns
    with."""
    sid, _session_obj, _game = _session()

    slots = _state(sid, 1)["search_library"]["one_of_each"]

    assert [slot["label"] for slot in slots] == [
        "a creature card", "a land card", "a noncreature, nonland card",
    ]
    # Forest, Hill Giant, Grizzly Bears, Sol Ring, Clockwork Beast.
    assert [slot["legal_indices"] for slot in slots] == [[1, 2, 4], [0], [3]]


def test_the_prompt_says_whose_library_it_is_and_how_many_are_owed():
    """Guided Passage's chooser is the *opponent*: the cards are the caster's
    and go to the caster's hand, so the dialog cannot say "your library" or
    "your hand" to the seat it is shown to. And nothing here is optional — the
    floor is one card per description the library can answer."""
    sid, _session_obj, _game = _session()

    prompt = _state(sid, 1)["search_library"]

    assert prompt["caster_seat"] == 1
    assert prompt["zone_seat"] == 0 and prompt["zone_owner_name"] == "Host"
    assert prompt["destination"] == "hand"
    assert prompt["min_picks"] == 3


def test_the_floor_is_what_the_library_can_answer():
    """A library with no land answers two of the three descriptions; the
    opponent owes two cards, and the prompt says two."""
    sid, _session_obj, game = _session()
    game.players[0].library = [
        card for card in game.players[0].library if card.name != "Forest"
    ]

    prompt = _state(sid, 1)["search_library"]

    assert prompt["min_picks"] == 2
    assert [slot["legal_indices"] for slot in prompt["one_of_each"]] == [[0, 1, 3], [], [2]]
    assert _confirm(sid, 1, 0).status_code == 400, "one card is short of the floor"
    assert _confirm(sid, 1, 0, 2).status_code == 200


def test_a_search_of_ones_own_library_names_no_other_owner():
    """Every other search: the zones are the chooser's own, and the two fields
    say so rather than being absent."""
    sid, _session_obj, game = _session()
    game.pending_choices.clear()
    game.arm_pending_choice(
        "search_library", 0,
        count=1, card_type="any", zones=("library",), destination="hand",
        card_name="Demonic Tutor",
    )

    prompt = _state(sid, 0)["search_library"]

    assert prompt["zone_seat"] == 0 and prompt["zone_owner_name"] == "Host"
    assert "one_of_each" not in prompt and "min_picks" not in prompt


def test_the_label_is_assembled_from_the_keys_the_predicate_honours():
    from web.prompts import search_slot_label

    assert search_slot_label({"card_type": "creature"}) == "a creature card"
    assert search_slot_label({"exclude_types": ["creature", "land"]}) == (
        "a noncreature, nonland card"
    )
    # Gaea's Balance: "a land card of each basic land type".
    assert search_slot_label(
        {"card_type": "land", "restrictions": {"subtypes": ["island"]}}
    ) == "an Island land card"
    assert search_slot_label(
        {"card_type": "land", "restrictions": {"supertypes": ["basic"]}}
    ) == "a basic land card"
    assert search_slot_label(
        {"card_type": ("instant", "sorcery"), "restrictions": {"any_colors": ["U"]}}
    ) == "a blue instant or sorcery card"
    assert search_slot_label(
        {"card_type": "any", "restrictions": {"mana_value": {"op": "le", "value": 2}}}
    ) == "a card with mana value 2 or less"


def test_the_dialog_shows_the_descriptions_as_slots_and_refuses_a_second_card():
    """The ratchet on what was driven in a browser: Gaea's Balance over a
    library holding two dual lands (Taiga moved from the Mountain slot to the
    Forest one when a Mountain was picked; a basic Forest was then refused),
    and Guided Passage with a human **opponent** choosing out of the host's
    library (a second creature refused, the confirm held at "2 of 3", the three
    cards landing in the host's hand)."""
    from tests.helpers import app_js_function_body

    dialog = app_js_function_body("renderSearchLibraryModal")
    # The slots come off the payload and the assignment decides a click.
    assert "info.one_of_each" in dialog
    assert "searchSlotAssignment(slots, wanted).size < wanted.length" in dialog
    assert "buildSlotRow()" in dialog
    # Whose library and whose hand, from the payload.
    assert "info.zone_seat === seat" in dialog and "info.zone_owner_name" in dialog
    assert "searchDestinationWords(oneDestination, info.enters_tapped, zoneOwnerName)" in dialog
    # The floor holds the confirm and withdraws "fail to find".
    assert "info.min_picks" in dialog
    assert "confirmBtn.disabled = n === 0 || n < minPicks" in dialog
    assert 'declineBtn.classList.toggle("hidden", minPicks > 0)' in dialog

    words = app_js_function_body("searchDestinationWords")
    assert "ownerName" in words

    # The assignment is an augmenting path over the server's per-slot indices,
    # never a second reading of the restriction.
    matching = app_js_function_body("searchSlotAssignment")
    assert "searchSlotAnswers(slot, key)" in matching and "place(holder.get(position), seen)" in matching
    answers = app_js_function_body("searchSlotAnswers")
    assert "slot.legal_graveyard_indices" in answers and "slot.legal_indices" in answers


def test_the_legal_list_is_asked_the_way_the_resolver_asks(set_pool):
    """A creature type a static gives cards *outside* the battlefield
    (Conspiracy: "…creature cards you own that aren't on the battlefield … are
    the chosen type") is part of what a search may find, and the resolver has
    read it since that card shipped. The payload's legal list asked the
    predicate without the game, so under a Conspiracy naming Goblin a "Goblin
    card" search showed nothing findable while every creature card was a legal
    answer. One question now, asked one way."""
    from engine.models import Permanent

    sid, _session_obj, game = _session()
    game.pending_choices.clear()

    def _goblin_search():
        game.pending_choices.clear()
        game.arm_pending_choice(
            "search_library", 0,
            count=1, card_type="creature", zones=("library",),
            restrictions={"subtypes": ["goblin"]}, destination="hand",
            card_name="A Goblin tutor",
        )
        return _state(sid, 0)["search_library"]["legal_indices"]

    assert _goblin_search() == [], "no Goblin card is printed in this library"

    conspiracy = Permanent(card=set_pool("MMQ")["Conspiracy"])
    game.players[0].battlefield.append(conspiracy)
    conspiracy.metadata["chosen_creature_type"] = "goblin"
    game._sync_control()

    # Hill Giant, Grizzly Bears, Clockwork Beast: every creature card is one.
    assert _goblin_search() == [1, 2, 4]
    taken = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "search_library_confirm", "hand_index": 1, "search_zone": "library"},
    )
    assert taken.status_code == 200, taken.text
    assert [card.name for card in game.players[0].hand] == ["Hill Giant"]
