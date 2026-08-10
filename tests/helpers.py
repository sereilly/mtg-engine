"""Shared test helpers.

Named ``helpers`` (no ``test_`` prefix) so pytest never collects it as a test
module. Import from here instead of copy-pasting these into each file.
"""
from pathlib import Path

from fastapi.testclient import TestClient

import web.app as web_app
import web.session_store as web_session_store
from web.app import app, store
from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import CardDefinition, Permanent

client = TestClient(app)

# Resolved through cards/manifest.json rather than spelled out, so the filename
# lives in one place — the registry every other reader already uses.
LEA_PATH = manifest_set_path("LEA")
# Loaded once per process; CardDefinition is immutable, so sharing is safe.
CARDS_BY_NAME = {c.name: c for c in load_cards(LEA_PATH)}


def _game(p1: PlayerState, p2: PlayerState) -> Game:
    """A two-player game with mana-cost enforcement off (the standard test rig)."""
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


def _nosick(perm: Permanent) -> Permanent:
    """Clear summoning sickness so the permanent can attack/tap immediately."""
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# Alias used by older test files.
_no_summoning_sickness = _nosick


def _mk_card(*args, **kwargs):
    # Flexible constructor to match various test helper signatures.
    # Supported forms:
    #  - _mk_card(name, type_line)
    #  - _mk_card(name, type_line, oracle_text)
    #  - _mk_card(name, mana_cost, type_line, oracle_text)
    #  - keyword args: name=..., mana_cost=..., type_line=..., oracle_text=..., colors=(), produced_mana=()
    name = kwargs.get("name")
    mana_cost = kwargs.get("mana_cost", "")
    type_line = kwargs.get("type_line", "")
    oracle_text = kwargs.get("oracle_text", "")
    produced_mana = kwargs.get("produced_mana", ())

    if args:
        if len(args) == 1:
            name = args[0]
        elif len(args) == 2:
            name, type_line = args
        elif len(args) == 3:
            name, type_line, oracle_text = args
        else:
            name, mana_cost, type_line, oracle_text = args[:4]

    colors = kwargs.get("colors", ())
    if isinstance(colors, list):
        colors = tuple(colors)

    if name is None:
        raise TypeError("_mk_card requires at least a name")

    raw = {"name": name, "type_line": type_line}
    # Default creature stats when not provided
    if "Creature" in type_line and "power" not in raw:
        raw["power"] = str(kwargs.get("power", 2))
        raw["toughness"] = str(kwargs.get("toughness", 2))

    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=1.0 if mana_cost else 0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=produced_mana,
        raw=raw,
    )


def _mk_creature_card(name: str, power: int, toughness: int, oracle_text: str = ""):
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test", "power": str(power), "toughness": str(toughness)},
    )


def _damage_dealt(game, recipient, amount: int, source=None, combat: bool = False) -> int:
    """Run one damage event through CR 120.4 and report the damage dealt.

    The real entry point (engine/damage_events.deal_damage), which is what makes
    this usable for shield tests: it applies every effect that modifies the
    event, but *applying the result* — losing life, marking damage — is the
    caller's job, so a test can read what survived the shields without a life
    total moving or a trigger firing.
    """
    from engine.damage_events import deal_damage

    return deal_damage(
        game,
        {"recipient": recipient, "amount": amount, "source": source, "combat": combat},
    ).dealt


def _get(all_cards, name: str):
    return next(card for card in all_cards if card.name == name)

def _pass_priority(session_id: str, seat: int):
    session = store.get(session_id)
    if seat == 1 and seat not in session.joined_seats and session.mode == "human_vs_human":
        client.post(f"/api/sessions/{session_id}/join", json={"guest_name": "Joiner"})
    return client.post(
        f"/api/sessions/{session_id}/action",
        json={"seat": seat, "action": "pass_priority"},
    )


def _resolve_top_stack(session_id: str, first_pass_seat: int):
    first = _pass_priority(session_id, first_pass_seat)
    assert first.status_code == 200
    second = _pass_priority(session_id, 1 - first_pass_seat)
    assert second.status_code == 200
    return second
