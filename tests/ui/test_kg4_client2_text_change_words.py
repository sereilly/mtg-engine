"""What a cast announces besides its targets is the server's answer.

Two client copies read the card's text for it:

* ``castRequiresManaColorChoice`` asked a mana colour while casting any card
  whose text outside an activated line said "any one color" / "one mana of
  any color" — right for Metamorphosis and Traitorous Greed, whose resolution
  adds the mana, and wrong for every permanent whose *trigger* does (Quirion
  Sentinel's entry, Carpet of Flowers, Fertile Ground, Sanctum of Fruitful
  Harvest, Gadrak): the colour sent with the cast was never read, and the
  trigger asked again. The wire now carries ``cast_mana``
  (``web/offers.cast_mana_offer``: what the spell's own resolution adds and
  whether its colour is chosen), instants and sorceries alone.
* ``cardRequiresCastColorChoice`` / ``landWordOptionsForTarget`` /
  ``landWordOptionsForSpell`` decided that a cast names two words by two
  phrases of its text — Balduvian Shaman, whose text change is an *activated*
  ability, asked two words as it was cast — and which vocabulary by
  "basic land type", so Mind Bend, Crystal Spray and Whim of Volrath (either
  vocabulary) offered land types alone and refused a target writing only a
  colour word; the land words were a substring read of the target. The wire
  now carries ``text_change`` (``web/offers.text_change_offer``): the mode the
  compiled program announces, and per permanent and per spell the words its
  text writes now (``text_changes.words_written``, whole words in every form
  the change rewrites).

The engine read "is the word written" by substring too
(``Game.live_text_change_vocabularies``, the land-type handler's "had no
effect"): "red" was written on 75 shipped cards that print "entered",
"required" or "declared" and no red at all, so a Mind Bend naming {R} rewrote
a word that was not there. Both now ask ``words_written``.

Backwards on the base: neither key is on the wire, and the substring census's
75 rows read "red" where the change's own pattern finds none.
"""
from __future__ import annotations

import shutil

import pytest

from engine import faces
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.text_changes import COLOR_WORD, COLOR_WORDS, LAND_WORD, words_written
from tests.helpers import client, resolve_stack, run_app_js
from web.app import store

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)


def _table(hand, *, battlefield=(), opponent=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4408,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
        player.hand = []
    for seat, names in ((0, battlefield), (1, opponent)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    resolve_stack(game)
    game.players[0].hand = [_CARDS[name] for name in hand]
    game._recompute_continuous_effects()
    game.stack.clear()
    game.pending_choices.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _hand(sid):
    payload = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return {card["name"]: card for card in payload["players"][0]["hand"]}, payload


# -- the mana a cast names ------------------------------------------------------

_ASKED_AT_CAST = ("Metamorphosis", "Traitorous Greed")
#: The five permanents the client asked a colour of as they were cast.
_TRIGGERED_MANA = (
    "Quirion Sentinel", "Carpet of Flowers", "Fertile Ground",
    "Sanctum of Fruitful Harvest", "Gadrak, the Crown-Scourge",
)


def test_only_a_spell_that_adds_the_mana_names_its_colour_as_it_is_cast():
    sid, _game = _table([*_ASKED_AT_CAST, *_TRIGGERED_MANA, "Dark Ritual"])
    hand, _payload = _hand(sid)
    for name in _ASKED_AT_CAST:
        assert hand[name]["cast_mana"] == {
            "symbols": ["W", "U", "B", "R", "G"], "choice": True,
        }, name
    for name in _TRIGGERED_MANA:
        assert "cast_mana" not in hand[name], name
    # A fixed output names nothing.
    assert hand["Dark Ritual"]["cast_mana"] == {"symbols": ["B"], "choice": False}


def test_every_card_in_the_pool_names_a_cast_colour_only_from_its_resolution():
    """The census: across the pool, a cast offer is made exactly for an
    instant or sorcery whose own steps add mana."""
    from web.offers import cast_mana_offer

    offered = [unit for unit in faces.compilation_units(_CATALOG) if cast_mana_offer(unit)]
    # A census that found nothing would look like one that found no defect.
    assert len(offered) >= 5, [unit.name for unit in offered]
    assert all(unit.primary_type in ("instant", "sorcery") for unit in offered)
    choosing = {unit.name for unit in offered if cast_mana_offer(unit)["choice"]}
    assert set(_ASKED_AT_CAST) <= choosing


@needs_node
def test_the_client_asks_the_colour_the_server_says_and_no_other():
    sid, _game = _table([*_ASKED_AT_CAST, *_TRIGGERED_MANA])
    hand, _payload = _hand(sid)
    asked = run_app_js(
        ["castManaColorOptions"],
        "return Object.fromEntries(Object.entries(INPUT).map(([name, card]) =>"
        " [name, (castManaColorOptions(card) || []).map((o) => o.symbol)]));",
        hand,
        prelude=(
            'const MANA_COLOR_OPTIONS = [{symbol: "W", label: "White"}, {symbol: "U", label: "Blue"},'
            ' {symbol: "B", label: "Black"}, {symbol: "R", label: "Red"}, {symbol: "G", label: "Green"}];'
        ),
    )
    for name in _ASKED_AT_CAST:
        assert asked[name] == ["W", "U", "B", "R", "G"], name
    for name in _TRIGGERED_MANA:
        assert asked[name] == [], name


# -- the words a text change names ----------------------------------------------

def test_a_text_change_cast_names_its_mode_and_each_object_s_words():
    sid, game = _table(
        ["Magical Hack", "Sleight of Mind", "Mind Bend", "Balduvian Shaman"],
        battlefield=["Island"], opponent=["Bog Wraith", "Nettling Imp", "White Knight"],
    )
    hand, _payload = _hand(sid)
    ids = {permanent.card.name: str(permanent.permanent_id) for permanent in game.all_permanents()}
    # Balduvian Shaman's change is its activated ability's: casting it names nothing.
    assert "text_change" not in hand["Balduvian Shaman"]

    hack = hand["Magical Hack"]["text_change"]
    assert hack["mode"] == "land_type"
    assert hack["words"][ids["Island"]] == ["U"]
    assert hack["words"][ids["Bog Wraith"]] == ["B"]   # swampwalk
    assert ids["Nettling Imp"] not in hack["words"]

    sleight = hand["Sleight of Mind"]["text_change"]
    assert sleight["mode"] == "color_word"
    assert sleight["words"][ids["White Knight"]] == ["B"]   # protection from black
    # "entered"/"declared": no colour word, though "red" is inside them.
    assert ids["Nettling Imp"] not in sleight["words"]

    bend = hand["Mind Bend"]["text_change"]
    assert bend["mode"] == "color_word_or_land_type"
    assert bend["words"][ids["White Knight"]] == ["B"]
    assert bend["words"][ids["Bog Wraith"]] == ["B"]


def test_a_spell_on_the_stack_offers_the_words_it_writes_now():
    sid, game = _table(["Magical Hack"], opponent=["Island"])
    session = store.get(sid)
    # A spell of the other seat's on the stack, its text naming two land types.
    game.players[1].hand = [_CARDS["Flashfires"]]
    game.active_player_index = 1
    session.current_turn = 1
    game.start_priority_window(1)
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 1, "action": "cast", "card_name": "Flashfires",
    })
    assert cast.status_code == 200, cast.text
    assert game.stack and game.stack[-1].card.name == "Flashfires"
    hand, payload = _hand(sid)
    words = hand["Magical Hack"]["text_change"]["stack_words"]
    assert payload["stack"][0]["card"]["name"] == "Flashfires"
    assert words["0"] == ["W"]  # "Destroy all Plains."


def test_mind_bend_aimed_at_a_colour_word_is_cast_with_it():
    """The defect's board: Mind Bend at White Knight, which writes "black" and
    no land type. The client refused it ("has no basic land type"); the words
    the server offers name black, and the cast the client then sends changes
    the protection."""
    sid, game = _table(["Mind Bend"], opponent=["White Knight"])
    knight = next(p for p in game.controlled_by(1) if p.card.name == "White Knight")
    hand, _payload = _hand(sid)
    assert hand["Mind Bend"]["text_change"]["words"][str(knight.permanent_id)] == ["B"]
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Mind Bend",
        "target_permanent_id": knight.permanent_id, "old_color": "B", "mana_color": "G",
    })
    assert cast.status_code == 200, cast.text
    resolve_stack(game)
    assert "protection from green" in knight.effective_card.oracle_text.lower()
    assert any("Mind Bend changed" in line for line in game.log), game.log[-5:]


def test_mind_bend_naming_red_at_a_card_that_only_says_entered_changes_nothing():
    """The engine's half: "red" inside "entered" is no word to replace, and
    the resolution says so rather than recording a change of nothing."""
    sid, game = _table(["Mind Bend"], opponent=["Nettling Imp"])
    imp = next(p for p in game.controlled_by(1) if p.card.name == "Nettling Imp")
    assert "red" in imp.effective_card.oracle_text.lower()  # "declared"
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Mind Bend",
        "target_permanent_id": imp.permanent_id, "old_color": "R", "mana_color": "G",
    })
    assert cast.status_code == 200, cast.text
    resolve_stack(game)
    assert any("had no effect" in line for line in game.log), game.log[-5:]
    assert not imp.metadata.get("text_modified")


def test_the_substring_census_the_engine_no_longer_reads():
    """Every pool card a substring test found a colour word on that the
    change's own pattern does not: the reading the vocabulary question and
    the client's options used to ask. A floor, not a count."""
    disagree = []
    for unit in faces.compilation_units(_CATALOG):
        written = " ".join((unit.type_line or "", unit.oracle_text or "", *(unit.keywords or ()))).lower()
        substring = {symbol for symbol, word in COLOR_WORDS.items() if word in written}
        if substring - set(words_written(unit, COLOR_WORD)):
            disagree.append(unit.name)
    assert len(disagree) >= 50, len(disagree)
    assert "Nettling Imp" in disagree
    # …and the land words agree both ways: no shipped card writes one inside
    # another word.
    assert words_written(_CARDS["Bog Wraith"], LAND_WORD) == ("B",)


@needs_node
def test_the_client_offers_the_server_s_words_for_the_target_it_names():
    sid, game = _table(["Mind Bend"], opponent=["White Knight", "Nettling Imp"])
    hand, _payload = _hand(sid)
    by_name = {p.card.name: p.permanent_id for p in game.all_permanents()}
    offered = run_app_js(
        ["castTextChange", "textChangeWordOptions", "textChangeNoun"],
        "return { knight: textChangeWordOptions(INPUT.card, { permanentId: INPUT.knight }).map((o) => o.symbol),"
        " imp: textChangeWordOptions(INPUT.card, { permanentId: INPUT.imp }).map((o) => o.symbol),"
        " noun: textChangeNoun(castTextChange(INPUT.card).mode) };",
        {"card": hand["Mind Bend"], "knight": by_name["White Knight"], "imp": by_name["Nettling Imp"]},
        prelude=(
            'const MANA_COLOR_OPTIONS = [{symbol: "W", label: "White"}, {symbol: "U", label: "Blue"},'
            ' {symbol: "B", label: "Black"}, {symbol: "R", label: "Red"}, {symbol: "G", label: "Green"}];'
        ),
    )
    assert offered == {"knight": ["B"], "imp": [], "noun": "color word or land type"}


def test_the_client_reads_no_card_text_for_what_a_cast_names():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    for deleted in (
        "function castRequiresManaColorChoice", "function nonActivatedOracleText",
        "function cardRequiresCastColorChoice", "function landWordOptionsForTarget",
        "function landWordOptionsForSpell", "/basic land type/.test",
    ):
        assert deleted not in source, deleted
