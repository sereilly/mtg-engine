"""A trigger that declares it functions from the graveyard must fire from one.

`tests/engine/test_trigger_dispatchers.py` asks its question per *condition
kind*, and cannot see this gap: Silversmote Ghoul's condition is
``end_step_self``, which has had a dispatcher since round 68 — over battlefields.
Measured while building round 76: with the grammar, the lowering and the handler
in place but the graveyard scan omitted, the card **compiled supported, the full
suite passed, and all five `--check` gates passed, while the ability never once
fired.** That is round 58's `draws_card` failure on a new axis.

So this guard asks the question behaviourally instead of comparing two lists: it
puts the card in a graveyard, arms its condition, runs the step, and looks at
what happened. CR 113.6m is the rule being enforced — an ability whose effect
moves its own source out of a zone functions from that zone, and nowhere else —
and CR 113.6b beside it, for the cards that say where they function in an
intervening-if rather than in the effect ("if this card is in your graveyard
with a creature card directly above it": Death Spark, Krovikan Horror).

**Three things are read off the card rather than assumed**, because the guard
found its second, third and fourth subjects the day Alliances was ingested and
every one of them differed from Silversmote Ghoul in a different place: which
step announces it, what its intervening-if wants armed, and which zone it moves
the card to. A guard that assumed any of the three would have skipped the cards
it exists to catch — or, worse, failed them for arriving in the right place.
"""

from __future__ import annotations

from engine import Game
from engine.card_loader import load_cards, manifest_set_paths
from engine.events import FUNCTIONS_FROM
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle

#: A vanilla creature and a vanilla land, for arming a graveyard-position
#: condition. By name out of the pool rather than invented, so what
#: ``printed_shape`` reads is a real printed type line.
_FILLER = {"creature": "Grizzly Bears", "land": "Forest", "artifact": "Black Lotus"}


def _pool():
    return {card.name: card for card in load_cards(manifest_set_paths(include_measured=True))}


def _graveyard_functioning_triggers():
    """Every (card, trigger) in the whole pool declaring it works from a graveyard.

    Over the manifest including measured sets, deliberately. The shipped pool has
    no such card yet, so a shipped-only fixture would make this guard vacuous on
    the very day it was written — which is the failure it exists to prevent.
    """
    for card in load_cards(manifest_set_paths(include_measured=True)):
        for trig in compile_card_oracle(card).triggered_abilities:
            if not trig.supported or trig.instruction is None:
                continue
            if (trig.instruction.payload or {}).get(FUNCTIONS_FROM) == "graveyard":
                yield card, trig


def _destination(instruction) -> str:
    """Which zone this trigger's effect moves the card to.

    Read off the instruction tree rather than assumed, because the effect may be
    wrapped: Krovikan Horror's return sits inside a ``may`` and Death Spark's
    inside a ``may``'s "if you do". ``return_self_from_graveyard`` says where it
    lands in its own payload (absent means the battlefield, which is what every
    payload written before the hand spelling existed says).
    """
    if instruction is None:
        return "battlefield"
    payload = instruction.payload or {}
    if instruction.kind == "return_self_from_graveyard":
        return str(payload.get("to") or "battlefield")
    for key in ("steps", "action", "then", "effect", "otherwise"):
        for step in payload.get(key) or ():
            found = _destination(step)
            if found is not None:
                return found
    return "battlefield"


def _arm(game: Game, seat: int, card, gate: dict) -> None:
    """Make this trigger's intervening-if true.

    Only the shapes the pool actually prints; an unknown one fails loudly rather
    than being silently treated as satisfied — a guard that armed nothing and
    then found nothing had happened would pass for the wrong reason.
    """
    player = game.players[seat]
    kind = gate["kind"]
    if kind == "life_gained_this_turn":
        player.life_gained_this_turn = int(gate.get("amount", 1))
        return
    if kind == "self_in_graveyard_with_cards_above":
        filler = _pool()[_FILLER[str(gate.get("card_type", "creature"))]]
        for _ in range(int(gate.get("count", 1))):
            player.graveyard.append(filler)
        return
    raise AssertionError(f"{card.name}: this guard cannot arm {kind!r} yet")


def _run_step(game: Game, seat: int, condition_kind: str, card) -> None:
    """Run the step this trigger names — the announcement being tested."""
    if condition_kind in ("end_step_self", "end_step"):
        game.resolve_end_step(seat)
    elif condition_kind in ("upkeep_self", "upkeep_each"):
        game.resolve_upkeep(seat)
    else:
        raise AssertionError(
            f"{card.name}: this guard does not know which step announces "
            f"{condition_kind!r}"
        )


def test_the_pool_has_at_least_one_such_trigger():
    """The guard below is a loop over a generated set, so it passes trivially if
    the set is empty. This is what says it is not."""
    assert list(_graveyard_functioning_triggers())


def test_every_graveyard_functioning_trigger_reaches_its_zone():
    """Put it in a graveyard, satisfy its condition, run its step, and look."""
    pool = _pool()
    for card, trig in _graveyard_functioning_triggers():
        p1 = PlayerState(name="P1", graveyard=[card])
        game = Game(players=[p1, PlayerState(name="P2")])
        game.enforce_mana_costs = False
        game.start_turn(0)
        # An offer with a printed price ("you may pay {1}", Death Spark) is
        # declined out of hand when the seat cannot pay, and the ability then
        # does nothing — which is a pass this guard must not accept. Five basics
        # cover any small cost, and the seat is interactive so the offer is
        # *asked* rather than defaulted: the non-interactive default deliberately
        # never taps a land for an optional cost.
        for basic in ("Plains", "Island", "Swamp", "Mountain", "Forest"):
            p1.battlefield.append(Permanent(card=pool[basic]))
        game._sync_control()
        game.interactive_seats = {0}

        gate = (trig.instruction.payload or {}).get("intervening_if")
        if gate is not None:
            _arm(game, 0, card, gate)

        _run_step(game, 0, trig.condition.kind, card)
        game._settle()
        # Take every offer the trigger made. "You may" is the card's own word on
        # all three subjects, so an unanswered prompt is the ability suspended
        # rather than the ability declining.
        while any(c.kind == "optional_pay" for c in game.pending_choices):
            assert game.confirm_optional_pay(0, card.name, accept=True), (
                f"{card.name}: its own offer could not be accepted"
            )
            game._settle()

        zone = _destination(trig.instruction)
        landed = (
            [p.card for p in p1.battlefield] if zone == "battlefield" else p1.hand
        )
        assert any(held is card for held in landed), (
            f"{card.name}: declares {FUNCTIONS_FROM}='graveyard' under "
            f"{trig.condition.kind!r} and nothing fired it from a graveyard "
            f"into the {zone}"
        )
        assert all(held is not card for held in p1.graveyard), (
            f"{card.name}: left a copy behind in the graveyard"
        )
