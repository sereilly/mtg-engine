"""An activated ability's text change asks its two words from a browser.

"{T}: Change the text of target white enchantment you control that doesn't
have cumulative upkeep by replacing all instances of one color word with
another." (Balduvian Shaman.) The activation announces both words (CR 612
through CR 602.2b) on the activate action's ``old_color`` / ``mana_color`` —
the engine takes them (``Game.queue_permanent_ability``) and the AI sends them
(``ai_actions.activation_announcement``) — but the client asked none: the
target was picked and the activation went out naming no word, and the ability
resolved changing nothing.

The wire now carries ``ability_text_change`` per ability
(``web/offers.ability_text_change_offer``: the mode
``ai_text_changes.ability_text_change_mode`` reads, and the words each object's
text writes now), and the activation's target prompt asks the "from" word among
the target's words and then the "to" word, as the cast path does.

Backwards on the base: no ``ability_text_change`` on the wire, and the client
sends the activation as soon as the target is clicked.
"""
from __future__ import annotations

import re
import shutil

import pytest

from engine import faces
from engine.ai_text_changes import ability_text_change_mode
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from engine.text_changes import current_text_card
from tests.helpers import app_js_function_body, client, resolve_stack, run_app_js
from web.app import store

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)


def _table(mine, theirs=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 6120,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    for player in game.players:
        player.hand.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    placed = {}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.setdefault(name, permanent)
    resolve_stack(game)
    game.pending_choices.clear()
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game, placed


def _mine(sid, permanent):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return next(p for p in state["players"][0]["battlefield"] if p.get("id") == permanent.permanent_id)


def _text_changing_abilities() -> list[str]:
    return sorted({
        unit.name for unit in faces.compilation_units(_CATALOG)
        if any(
            ability_text_change_mode(ability.instruction) is not None
            for ability in usable_activated_abilities(compile_card_oracle(unit))
        )
    })


def test_every_ability_that_announces_words_carries_them():
    """The census: each shipped ability whose activation announces a text
    change's words is offered them on the wire, per ability."""
    names = _text_changing_abilities()
    assert len(names) >= 1 and "Balduvian Shaman" in names, names
    for name in names:
        sid, game, placed = _table([name, "Circle of Protection: Red"])
        payload = _mine(sid, placed[name])
        offers = payload.get("ability_text_change")
        assert isinstance(offers, list) and any(offers), name
        circle = placed["Circle of Protection: Red"]
        offer = next(entry for entry in offers if entry)
        assert offer["words"][str(circle.permanent_id)] == ["R"], (name, offer)


def test_the_shaman_s_words_are_the_target_s_and_the_activation_takes_them():
    sid, game, placed = _table(["Balduvian Shaman", "Circle of Protection: Red", "Forest"])
    shaman, circle = placed["Balduvian Shaman"], placed["Circle of Protection: Red"]
    (offer,) = _mine(sid, shaman)["ability_text_change"]
    assert offer["mode"] == "color_word"
    assert offer["words"][str(circle.permanent_id)] == ["R"]
    # A permanent writing no colour word is offered none.
    assert str(placed["Forest"].permanent_id) not in offer["words"]
    # Nothing announces words on a permanent with no such ability.
    assert "ability_text_change" not in _mine(sid, circle)

    index = next(i for i, p in enumerate(game.players[0].battlefield) if p is circle)
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": shaman.permanent_id,
        "target_seat": 0, "target_permanent_index": index,
        "old_color": "R", "mana_color": "B",
    })
    assert response.status_code == 200, response.text
    resolve_stack(game)
    text = current_text_card(circle).oracle_text.lower()
    assert "black source" in text and "red source" not in text, text
    assert any("changed red text to black" in line for line in game.log), game.log[-6:]


@needs_node
def test_the_client_offers_the_target_s_words_for_the_ability():
    sid, game, placed = _table(["Balduvian Shaman", "Circle of Protection: Red"])
    shaman = _mine(sid, placed["Balduvian Shaman"])
    circle = placed["Circle of Protection: Red"]
    asked = run_app_js(
        ["activationTextChange", "textChangeWordOptions", "castTextChange", "textChangeNoun"],
        "const offer = activationTextChange(INPUT.card);"
        " return { cast: castTextChange(INPUT.card),"
        " noun: textChangeNoun(offer.mode),"
        " words: textChangeWordOptions(INPUT.card, { permanentId: INPUT.circle }, offer).map((o) => o.symbol) };",
        {"card": shaman, "circle": circle.permanent_id},
        prelude=(
            'const MANA_COLOR_OPTIONS = [{symbol: "W", label: "White"}, {symbol: "U", label: "Blue"},'
            ' {symbol: "B", label: "Black"}, {symbol: "R", label: "Red"}, {symbol: "G", label: "Green"}];'
        ),
    )
    # Casting the Shaman names nothing; its ability names the Circle's red.
    assert asked == {"cast": None, "noun": "color word", "words": ["R"]}


def test_the_activation_asks_the_words_after_the_target():
    body = app_js_function_body("resolvePendingCastTarget")
    branch = body[body.index('if (pending.castAction === "activate") {'):]
    asked = branch.index("activationTextChange(pending.card)")
    assert asked < branch.index("sendAction(activateBody)")
    assert re.search(r'kind: "cast",\s*activation: true,\s*step: "from"', branch)
    resolve = app_js_function_body("resolvePendingManaColor")
    assert "if (pending.activation) {" in resolve
    assert re.search(r"old_color: pending\.fromColor,\s*mana_color: manaColor", resolve)
