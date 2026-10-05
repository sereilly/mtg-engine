"""The "change the target or targets" prompt, as the client is handed it.

Psychic Battle's choice rides the ``retarget_choice`` prompt Deflection has
always used — same action, same field, same renderer — with three things in
its option list that prompt never carried before: "leave the targets as they
are" (the card says *may*), a **spell** (a counterspell re-aimed at another
spell) and a **card in a graveyard** (a Raise Dead re-aimed at another card).

The engine keeps the descriptor each option stands for on the option itself,
under private keys, so the answer is the very object that was offered. What
this file holds is the other half of that arrangement: none of it reaches the
wire. The payload is the three public fields the client has always read, it
serialises, and it is shown to the seat that owes the answer — which is the
player who revealed the bigger card, not the trigger's controller.
"""

from __future__ import annotations

import json

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent

from tests.helpers import _nosick, resolve_stack
from web.prompts import PromptContext, render_prompts


def _card(name, type_line, text="", cmc=0, power=None, toughness=None):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost="", cmc=float(cmc), type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=raw,
    )


_ARBITER = _card(
    "Test Arbiter", "Enchantment",
    "Whenever a player chooses one or more targets, each player reveals the "
    "top card of their library. The player who reveals the card with the "
    "greatest mana value may change the target or targets. If two or more "
    "cards are tied for greatest, the target or targets remain unchanged. "
    "Changing targets this way doesn't trigger abilities of permanents named "
    "Test Arbiter.",
)
_SHOCK = _card("Test Shock", "Instant", "Test Shock deals 2 damage to any target.", 1)
_GROWTH = _card("Test Growth", "Instant", "Target creature gets +3/+3 until end of turn.", 1)
_COUNTER = _card("Test Counter", "Instant", "Counter target spell.", 2)
_RAISE = _card("Test Raise", "Sorcery", "Return target creature card from your graveyard to your hand.", 1)
_BEAR = _card("Test Bear", "Creature — Bear", "", 2, 2, 2)
_OGRE = _card("Test Ogre", "Creature — Ogre", "", 3, 3, 3)
_LAND = _card("Test Land", "Land")
_SIX = _card("Test Six", "Sorcery", "Draw a card.", 6)


def _table(*, hands, boards=((), ()), yards=((), ()), tops=(_LAND, _SIX)):
    """Seat 0 controls the Arbiter; seat 1 reveals the bigger card and is asked."""
    players = []
    for seat in range(2):
        battlefield = [_nosick(Permanent(card=card)) for card in boards[seat]]
        if seat == 0:
            battlefield.append(_nosick(Permanent(card=_ARBITER)))
        players.append(PlayerState(
            name=f"P{seat}", life=20, hand=list(hands[seat]), battlefield=battlefield,
            graveyard=list(yards[seat]), library=[tops[seat]] * 6,
        ))
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    resolve_stack(game)
    return game


def _payload(game, viewer):
    ctx = PromptContext(
        game=game, viewer_seat=viewer,
        serialize_card=lambda card: {"name": card.name},
        seat_type=lambda seat: "human",
    )
    return render_prompts(ctx)["retarget_choice"]


def test_the_prompt_is_shown_to_the_seat_that_revealed_the_bigger_card():
    game = _table(hands=([_SHOCK], []), boards=((_BEAR,), (_BEAR,)))
    theirs = next(p for p in game.controlled_by(game.players[1]))
    assert game.cast_from_hand(0, "Test Shock", target_permanent_ids=[theirs.permanent_id]).supported

    asked, bystander = _payload(game, 1), _payload(game, 0)

    assert asked is not None and asked["card_name"] == "Test Arbiter"
    assert "Test Shock" in asked["prompt"]
    # Declining first, then every other legal target of "any target".
    assert [option["kind"] for option in asked["options"]] == [
        "keep", "player", "player", "permanent",
    ]
    assert [option["index"] for option in asked["options"]] == [0, 1, 2, 3]
    # The trigger's controller is not the one choosing. The prompt is public —
    # what a spell targets is announced in the open — so the other seat may see
    # the question, and what matters is who may answer it.
    assert game.pending_choice_of("retarget_choice").player_index == 1
    assert not game.confirm_retarget_choice(0, 1)
    assert bystander is None or bystander["options"] == asked["options"]


def test_the_payload_is_three_public_fields_and_serialises():
    """A counterspell with a second spell to go to, and a Raise Dead with a
    second card: the two option kinds this prompt gained. Nothing of the
    engine's own descriptor — a ``StackItem``, a ``GraveyardTarget`` — is on
    the wire."""
    game = _table(
        hands=([_SHOCK, _GROWTH], [_COUNTER]), boards=((_BEAR,), (_BEAR,)),
        tops=(_SIX, _LAND),
    )
    bear = next(p for p in game.controlled_by(game.players[0]) if p.card is _BEAR)
    # Seat 0 reveals the bigger card here, and keeps both its own spells aimed.
    assert game.queue_from_hand(0, "Test Shock", target_player_index=1).supported
    game._settle()
    assert game.confirm_retarget_choice(0, 0)
    assert game.queue_from_hand(0, "Test Growth", target_permanent_ids=[bear.permanent_id]).supported
    game._settle()
    assert game.confirm_retarget_choice(0, 0)
    assert game.queue_from_hand(1, "Test Counter", target_stack_index=1).supported
    game._settle()

    payload = _payload(game, 0)

    assert [(option["kind"], option["name"]) for option in payload["options"]] == [
        ("keep", "Leave the targets as they are"), ("stack", "Test Shock"),
    ]
    assert all(set(option) == {"index", "name", "kind"} for option in payload["options"])
    assert json.loads(json.dumps(payload)) == payload

    game = _table(hands=([_RAISE], []), yards=((_BEAR, _OGRE), ()))
    assert game.cast_from_hand(0, "Test Raise", target_player_index=0, target_permanent_index=0).supported

    payload = _payload(game, 1)

    assert [(option["kind"], option["name"]) for option in payload["options"]] == [
        ("keep", "Leave the targets as they are"),
        ("graveyard", "Test Ogre in P0's graveyard"),
    ]
    assert json.loads(json.dumps(payload)) == payload
