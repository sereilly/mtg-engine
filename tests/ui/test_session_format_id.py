"""The session id names the format the session is played under.

A player joining a networked game has one thing in hand before they have asked
the server anything: the id (or the invite link carrying it). Encoding the
format there is what lets the Join screen state the format and filter the deck
list by it *at that moment* — the alternative, a lookup endpoint, cannot run
until the id is complete and correct, which is exactly when the player no
longer needs telling.

The id's random half is untouched, so its unguessability is unchanged. The two
characters in front of it are a code rather than the format's name, so an id
seen over a shoulder or in a chat log does not announce what is being played —
obfuscation, not secrecy: the codes ship to the browser with the card catalog,
since the Join screen has to decode an id it was handed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from web.app import app
from web.deck_legality import (
    DEFAULT_FORMAT,
    FORMATS,
    SESSION_CODE_LENGTH,
    format_from_session_id,
    session_id_prefix,
)
from web.runtime import store

client = TestClient(app)


def _create(**body) -> dict:
    payload = {"mode": "human_vs_human", "enable_pregame": True, **body}
    response = client.post("/api/sessions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# ── The encoding itself ─────────────────────────────────────────────────────

def test_every_format_round_trips_through_a_session_id():
    for fmt in FORMATS:
        sid = f"{session_id_prefix(fmt['key'])}hQ2v1sK9tWA"
        assert format_from_session_id(sid) == fmt["key"]


def test_a_session_id_with_no_code_names_no_format():
    """Not casual — the two are different answers."""
    assert format_from_session_id("hQ2v1sK9tWA") is None
    assert format_from_session_id("hQ2-1sK_tWA") is None


def test_an_unrecognized_code_names_no_format():
    assert format_from_session_id("aahQ2v1sK9tWA") is None
    assert format_from_session_id("") is None
    assert format_from_session_id(None) is None


def test_a_bare_code_names_no_session():
    """The code alone is a prefix, not an id — there is no session behind it."""
    for fmt in FORMATS:
        assert format_from_session_id(fmt["session_code"]) is None


def test_an_unknown_format_is_minted_as_the_default():
    assert session_id_prefix("pinochle") == session_id_prefix(DEFAULT_FORMAT)
    assert session_id_prefix(None) == session_id_prefix(DEFAULT_FORMAT)


# ── What the server mints ───────────────────────────────────────────────────

def test_a_hosted_session_is_minted_under_its_format():
    for key in ("casual", "commander", "brawl", "modern"):
        data = _create(format=key)
        assert format_from_session_id(data["session_id"]) == key
        assert data["state"]["format"] == key


def test_the_random_half_survives_the_prefix():
    """The code is added to the id, not carved out of it."""
    ids = {_create(format="commander")["session_id"] for _ in range(5)}
    assert len(ids) == 5
    for sid in ids:
        assert len(sid[SESSION_CODE_LENGTH:]) >= 11


def test_a_free_for_all_session_is_minted_the_same_way():
    seats = [{"name": f"P{i}", "is_ai": i != 0} for i in range(3)]
    data = _create(mode="free_for_all", seats=seats, format="brawl")
    assert format_from_session_id(data["session_id"]) == "brawl"
    assert data["state"]["format"] == "brawl"


def test_an_unknown_format_falls_back_rather_than_failing_the_request():
    data = _create(format="pinochle")
    assert format_from_session_id(data["session_id"]) == DEFAULT_FORMAT


# ── The format and the CR 903 variant cannot disagree ───────────────────────

def test_the_variant_is_the_one_the_format_names():
    """CR 903.1: the format decides the variant, so the id cannot lie about it.

    ``human_vs_ai`` rather than a lobby, because the variant reaches the *Game*
    when the pregame begins, and a lobby is still waiting for its guest.
    """
    data = _create(mode="human_vs_ai", format="commander")
    assert store.get(data["session_id"]).commander_variant == "commander"
    assert data["state"]["commander_variant"] == "commander"
    ordinary = _create(mode="human_vs_ai", format="modern")
    assert store.get(ordinary["session_id"]).commander_variant is None
    assert ordinary["state"]["commander_variant"] is None


def test_a_client_that_sends_only_the_variant_still_names_the_format():
    """``variant`` predates ``format``; a client sending only it is not casual.

    The two Commander formats are named for their variant, so the bare variant
    resolves to a format key — without which such a client would mint a
    ``casual.`` id for a Commander game and mislead everyone who joined it.
    """
    data = _create(mode="human_vs_ai", variant="commander")
    assert format_from_session_id(data["session_id"]) == "commander"
    assert store.get(data["session_id"]).commander_variant == "commander"
    assert data["state"]["format"] == "commander"


def test_a_client_that_sends_neither_is_casual():
    data = _create(mode="human_vs_ai")
    assert format_from_session_id(data["session_id"]) == DEFAULT_FORMAT
    assert store.get(data["session_id"]).commander_variant is None


# ── The id still works as an id ─────────────────────────────────────────────

def test_a_prefixed_id_routes_and_joins():
    data = _create(format="commander")
    sid = data["session_id"]
    joined = client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Guest"})
    assert joined.status_code == 200, joined.text
    assert joined.json()["seat"] == 1
    assert client.get(f"/api/sessions/{sid}/state?seat=0").status_code == 200


def test_the_join_url_carries_the_format_to_the_joining_player():
    data = _create(format="brawl")
    assert f"session={data['session_id']}" in data["join_url"]
    assert format_from_session_id(data["join_url"].split("session=")[1]) == "brawl"


# ── The codes themselves ────────────────────────────────────────────────────

def test_every_format_has_a_code_of_the_one_width():
    """Fixed width is what lets the random half follow with no separator."""
    for fmt in FORMATS:
        code = fmt.get("session_code")
        assert isinstance(code, str) and len(code) == SESSION_CODE_LENGTH, (
            f"format {fmt['key']!r} has no {SESSION_CODE_LENGTH}-character "
            "session_code, so its ids cannot be split by position"
        )


def test_no_two_formats_share_a_code():
    codes = [fmt["session_code"] for fmt in FORMATS]
    assert len(set(codes)) == len(codes), f"duplicate session codes in {codes}"


def test_a_code_does_not_spell_its_format():
    """The codes are arbitrary on purpose — that is the whole obfuscation.

    An abbreviation ("co" for Commander) would put the format back on the face
    of every id and join URL, which is what the code replaced. A new format
    that reaches for its own initials should pick something else instead.
    """
    for fmt in FORMATS:
        assert not fmt["key"].startswith(fmt["session_code"]), (
            f"format {fmt['key']!r} is coded {fmt['session_code']!r}, which "
            "reads as an abbreviation of it — pick unrelated characters"
        )
