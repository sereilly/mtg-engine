"""Census: no serializer tells another seat what a face-down object is.

CR 708.5: "At any time, you may look at a face-down spell you control on the
stack or a face-down permanent you control … You can't look at face-down
cards in any other zone or face-down spells or permanents controlled by
another player." And CR 708.2a makes the object, to everyone else, "a 2/2
face-down creature with no text, no name, no subtypes, and no mana cost".

The model (``engine/face_down.py``) is fail-closed by construction — a
face-down object's card *is* the blank 2/2 — so what this holds is that no
serializer reaches *past* the card to the one it hides, and that the log, which
is sent to every viewer, never names it while it is hidden.

**The table.** Seat 0 controls a face-down Krosan Colossus that has attacked,
been blocked and been dealt damage, and a face-down Exalted Angel spell on the
stack; seat 1 has cast Terror at the face-down Colossus in response. That is
every road a hidden card's name could take onto the wire this round: a
battlefield entry, a stack entry, a stack entry *targeting* the hidden object,
the special actions offered, and the log lines of a cast, an attack, a block
and damage.

**What is asked.** The whole state payload, as the opponent and as a spectator
sees it, holds none of the hidden cards' names, rules text or morph costs —
and as the controller sees it, holds all of them (CR 708.5's other half; it
is also what proves the table had something to hide). Each shared serializer
is then asked the same of the two objects directly.

**Validated backwards** (``test_the_census_can_tell``): the same table built
with the blank the Illusionary Mask used before this round — a 2/2 that kept
the hidden card's **name** — is reported by the census, naming the leak.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import (FACE_DOWN_CHARACTERISTICS, FACE_DOWN_NAME,
                              face_down_card, hidden_card_of)
from tests.helpers import declare_attack
from web.app import app, store
from web.serialization import (_serialize_card, _serialize_permanent,
                               _serialize_permanent_summary,
                               _serialize_stack_item, _stack_item_targets)
from web.state_view import build_state

client = TestClient(app)
_CATALOG = {card.name: card for card in load_catalog()}

#: What the two hidden cards would give away: names, a line of rules text each,
#: and their printed morph costs.
SECRETS = (
    "Krosan Colossus", "Exalted Angel",
    "you gain that much life", "{6}{G}{G}", "{2}{W}{W}",
)


def _leaky(card):
    """The blank Illusionary Mask built before this round: CR 708.2a's 2/2,
    **with the hidden card's name kept**."""
    return dataclasses.replace(
        FACE_DOWN_CHARACTERISTICS, name=card.name,
        raw={**FACE_DOWN_CHARACTERISTICS.raw, "name": card.name},
        face_down_of=card,
    )


def _table(ons, blank=face_down_card):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 11},
    ).json()
    session = store.get(created["session_id"])
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    p1, p2 = game.players
    p1.hand[:] = [ons["Krosan Colossus"], ons["Exalted Angel"]]
    p1.battlefield[:] = []
    p2.hand[:] = [_CATALOG["Terror"]]
    p2.battlefield[:] = []
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", "precombat_main"

    # The Colossus by the engine's own cast, resolved: a face-down permanent.
    assert game.queue_from_hand(0, "Krosan Colossus", alternative_cost=True).supported
    game.resolve_top_of_stack()
    (colossus,) = p1.battlefield
    # …that attacks, is blocked by a Llanowar Elves and is dealt damage.
    from engine.models import Permanent

    bears = Permanent(card=_CATALOG["Llanowar Elves"])
    p2.battlefield.append(bears)
    game._sync_control()
    if blank is not face_down_card:
        colossus.card = blank(hidden_card_of(colossus))
    declare_attack(game, 0, blocks={0: 0})
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
    # The Angel cast face down and left on the stack, and the opponent's
    # Terror aimed at the face-down Colossus above it.
    game.current_turn_phase, game.current_step = "postcombat_main", "postcombat_main"
    game.active_player_index = 0
    assert game.queue_from_hand(0, "Exalted Angel", alternative_cost=True).supported
    if blank is not face_down_card:
        game.stack[-1].card = blank(hidden_card_of(game.stack[-1]))
    assert game.queue_from_hand(
        1, "Terror", target_player_index=0,
        target_permanent_ids=[colossus.permanent_id],
    ).supported
    game.priority_player_index = 0
    return session, game, colossus


def _leaks(payload) -> list[str]:
    text = json.dumps(payload, default=str)
    return [secret for secret in SECRETS if secret in text]


def _census(session, game, colossus) -> dict:
    """Every leak the census finds, by where it was found."""
    angel = next(item for item in game.stack if hidden_card_of(item) is not None)
    terror = game.stack[-1]
    found: dict[str, list[str]] = {}
    for label, viewer in (("opponent", 1), ("spectator", None)):
        leaks = _leaks(build_state(session, viewer))
        if leaks:
            found[f"state as {label}"] = leaks
    for label, payload in (
        ("_serialize_permanent", _serialize_permanent(colossus, game)),
        ("_serialize_permanent_summary", _serialize_permanent_summary(colossus, game)),
        ("_serialize_card(permanent.card)", _serialize_card(colossus.card)),
        ("_serialize_stack_item(face-down spell)", _serialize_stack_item(angel, game)),
        ("_serialize_stack_item(spell targeting it)", _serialize_stack_item(terror, game)),
        ("_stack_item_targets", _stack_item_targets(terror, game)),
    ):
        leaks = _leaks(payload)
        if leaks:
            found[label] = leaks
    return found


@pytest.fixture
def ons(set_pool):
    return set_pool("ONS")


def test_no_serializer_names_a_face_down_object_to_another_seat(ons):
    session, game, colossus = _table(ons)
    opponent = build_state(session, 1)

    # The floor: the census looked at something.
    (entry,) = [p for p in opponent["players"][0]["battlefield"] if p["face_down"]]
    assert entry["name"] == FACE_DOWN_NAME
    assert (entry["power"], entry["toughness"]) == (2, 2)
    assert entry["colors"] == [] and entry["oracle_text"] == ""
    assert "hidden_card" not in entry
    stack = opponent["stack"]
    assert [s["face_down"] for s in stack] == [False, True]
    assert all("hidden_card" not in s for s in stack)
    assert stack[0]["target_permanent_name"] in (None, FACE_DOWN_NAME)
    log = opponent["log"]
    assert sum(FACE_DOWN_NAME in line for line in log) >= 4, log
    assert colossus.damage_marked >= 1, "the fight happened"
    assert not any(
        offer.get("permanent_id") == colossus.permanent_id
        for offer in opponent.get("special_actions", ())
    )

    assert _census(session, game, colossus) == {}


def test_the_controller_sees_what_it_hides(ons):
    """CR 708.5's other half — and the proof that the table had a secret."""
    session, game, colossus = _table(ons)
    mine = build_state(session, 0)
    (entry,) = [p for p in mine["players"][0]["battlefield"] if p["face_down"]]
    assert entry["hidden_card"]["name"] == "Krosan Colossus"
    assert entry["hidden_card"]["morph_cost"] == "{6}{G}{G}"
    assert (entry["hidden_card"]["power"], entry["hidden_card"]["toughness"]) == (9, 9)
    (spell,) = [s for s in mine["stack"] if s["face_down"]]
    assert spell["hidden_card"]["name"] == "Exalted Angel"
    assert set(_leaks(mine)) >= {"Krosan Colossus", "Exalted Angel", "{6}{G}{G}"}


def test_the_census_can_tell(ons):
    """Backwards: the Mask's old blank kept the name, and the census says so."""
    session, game, colossus = _table(ons, blank=_leaky)
    found = _census(session, game, colossus)
    assert "Krosan Colossus" in found.get("state as opponent", ()), found
    assert "Exalted Angel" in found.get("state as opponent", ()), found
    assert "Krosan Colossus" in found.get("_serialize_permanent", ()), found
    assert "Exalted Angel" in found.get("_serialize_stack_item(face-down spell)", ()), found
