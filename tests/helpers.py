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


def resolve_stack(game, *, limit: int = 200) -> int:
    """Resolve every object on *game*'s stack and settle the decisions it arms.

    **Use this instead of ``while game.stack: game.resolve_top_of_stack()``.**
    That loop is a latent hang, and the hang is the engine being correct.
    CR 608.2 says a resolution is not over until its last instruction is done and
    CR 117.3b says nobody receives priority until then, so an object that stopped
    to ask an interactive seat something stays on the stack and
    ``resolve_top_of_stack`` reports False for it. The bare loop then spins on a
    stack that never empties: no failure, no output, the whole suite wedged on
    one test. It costs nothing until a card in the test's pool starts asking
    something — which is why such a loop survives review, and why one of them
    stopped a run the day a trigger began announcing a target.

    Decisions are settled through the registry's own default path
    (``auto_resolve_pending_choices``, and the CR 614 replacement queue beside
    it) — the same answers an AI or headless seat takes — so a test written with
    this helper sees what a non-interactive game would have done. That happens
    **whether or not anything is left on the stack**, because the hazard is the
    resolution being unfinished rather than the stack being non-empty: a prompt
    still owed means steps behind it have not run, and a test that asserts on the
    board there is reading a half-applied effect. A test that means to *inspect*
    a prompt should resolve by hand instead; this helper's job is to finish.

    ``kinds`` is deliberately not offered. Drain order is load-bearing only where
    a default consumes randomness (a library search shuffles), and a test that
    needs that ordering wants the engine call itself rather than a helper hiding
    which kinds it drained.

    Returns the number of stack objects resolved. Raises rather than looping
    forever when nothing can progress — a prompt nothing defaults is a bug in the
    registry, and this names what is owed instead of timing the run out.
    """
    resolved = 0
    for _ in range(limit):
        before = (
            len(game.stack),
            len(game.pending_choices),
            len(game.pending_replacement_choices),
        )
        if game.stack and game.resolve_top_of_stack():
            resolved += 1
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
        after = (
            len(game.stack),
            len(game.pending_choices),
            len(game.pending_replacement_choices),
        )
        if not game.stack and not game.pending_choices:
            return resolved
        if after == before:
            raise AssertionError(
                f"the stack stopped moving with {len(game.stack)} object(s) on "
                f"it and nothing that could be answered: waiting on "
                f"{game.waiting_prompt()!r}, owed "
                f"{[c.kind for c in game.pending_choices]}"
            )
    raise AssertionError(
        f"the stack did not drain in {limit} iterations; {len(game.stack)} "
        f"object(s) left, owed {[c.kind for c in game.pending_choices]}"
    )


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
