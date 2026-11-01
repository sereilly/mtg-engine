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

from engine.faces import compilation_units
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
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
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
    payload written before the hand spelling existed says). A tree that names
    no move at all is the battlefield, for the same reason.
    """
    found = _destination_in(instruction)
    return "battlefield" if found is None else found


def _destination_in(instruction) -> str | None:
    """The zone the first *move* in this tree names, or None if it names none.

    None is a real answer and not a default: "you may **discard a card**. If you
    do, return this card to your hand" (Gigapede, ONS) puts its price ahead of
    its move in the ``may``'s ``action``, and a walk that answered
    "battlefield" for every leaf read the discard as the destination and failed
    a card that had arrived in the hand it prints.
    """
    if instruction is None:
        return None
    payload = instruction.payload or {}
    if instruction.kind == "return_self_from_graveyard":
        return str(payload.get("to") or "battlefield")
    # "…you may pay {2}{G}. If you do, return **target creature card** from
    # your graveyard to your hand." (Genesis, JUD.) The first graveyard
    # trigger here whose effect moves a *target* rather than its own source —
    # it says where it functions in its intervening-if (CR 113.6b), as Death
    # Spark does. On this guard's board the card is the only creature card in
    # its graveyard, so the target the trigger names as it goes on the stack
    # (CR 603.3d, the picker's first entry for a seat nobody asks) is itself,
    # and it lands in the hand the kind names.
    if instruction.kind == "return_creature_from_graveyard_to_hand":
        return "hand"
    for key in ("steps", "action", "then", "effect", "otherwise"):
        for step in payload.get(key) or ():
            found = _destination_in(step)
            if found is not None:
                return found
    return None


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
    if kind == "self_only_card_of_type_in_graveyard":
        # Nothing to arm: the card is the *only* thing in this graveyard, which
        # is exactly what the clause asks (Nether Spirit). Named rather than
        # left to the fall-through below, because "this guard cannot arm it yet"
        # and "it is already true" are different answers and only one of them is
        # a pass.
        return
    if kind == "self_in_graveyard_with_cards_above":
        filler = _pool()[_FILLER[str(gate.get("card_type", "creature"))]]
        for _ in range(int(gate.get("count", 1))):
            player.graveyard.append(filler)
        return
    raise AssertionError(f"{card.name}: this guard cannot arm {kind!r} yet")


def _arm_offered_price(game: Game, seat: int, card, instruction, pool) -> None:
    """Give the graveyard what the trigger's own offer charges, when the price
    is cards out of it.

    "…you may exile a black creature card other than this card from your
    graveyard. If you do, return this card to the battlefield." (Ichorid.) The
    basics above cover a *mana* price; an *action* price paid out of the same
    graveyard is a pile with nothing it names in it, and the offer is then
    rightly never made — so the guard would read a working card as one that
    never fired. Read off the offer's own payload through the predicate the
    pick asks (``graveyard_card_matches``), and never the card itself, which
    "other than this card" would leave out anyway.
    """
    from engine.handlers._filters import graveyard_card_matches

    payload = instruction.payload or {}
    if instruction.kind != "may":
        return
    for step in payload.get("action") or ():
        price = step.payload or {}
        if step.kind == "discard_controller_cards":
            # "…you may **discard a card**. If you do, return this card to
            # your hand." (Gigapede, ONS.) The hand twin of the pile below: an
            # empty hand has nothing to discard and the offer is rightly never
            # made (``offers`` asks the hand before offering). The card that
            # pays is the first in the pool the price's own filter admits.
            from engine.handlers._filters import _card_matches_filter

            described = dict(price.get("filter") or {})
            fodder = next(
                candidate for candidate in pool.values()
                if candidate is not card
                and _card_matches_filter(candidate, described, game=game, owner=seat)
            )
            amount = price.get("amount", 1)
            game.players[seat].hand.extend(
                [fodder] * (amount if isinstance(amount, int) else 1)
            )
            continue
        if step.kind != "exile_cards_from_graveyard" or price.get("graveyard_owner") != "you":
            continue
        fodder = next(
            candidate for candidate in pool.values()
            if candidate is not card and graveyard_card_matches(price, candidate)
        )
        game.players[seat].graveyard[:0] = [fodder] * int(price.get("count", 1))


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
        # *asked* rather than defaulted: the non-interactive default taps a
        # land for an optional gift only when nothing else would spend it
        # (`ai_prompts.optional_pay_may_tap_lands`), which is a policy question
        # and not the one this guard asks.
        #
        # **Two of each**, since Pyre Zombie (INV): its price is {1}{B}{B}, and
        # one of each basic covers any generic cost and no cost that names a
        # colour twice — the offer was declined out of hand and the guard read
        # a working card as one that never fired.
        #
        # **Three of each**, since Ghastly Remains (LGN): {B}{B}{B}, the same
        # miss one pip further — two Swamps cannot pay it, the offer is
        # rightly never made, and the guard read a working card as one that
        # never fired.
        for basic in ("Plains", "Island", "Swamp", "Mountain", "Forest") * 3:
            p1.battlefield.append(Permanent(card=pool[basic]))
        game._sync_control()
        game.interactive_seats = {0}

        gate = (trig.instruction.payload or {}).get("intervening_if")
        if gate is not None:
            _arm(game, 0, card, gate)
        _arm_offered_price(game, 0, card, trig.instruction, pool)

        _run_step(game, 0, trig.condition.kind, card)
        # A trigger that prints a target names it as it goes on the stack
        # (CR 603.3d), and this seat is interactive, so it is asked (Genesis's
        # "return target creature card from your graveyard"). Answered by the
        # prompt's own default — which card it names is not this guard's
        # question, and on this board the only candidate is the card itself.
        game.auto_resolve_pending_choices(kinds=("trigger_target",))
        game._settle()
        # Take every offer the trigger made. "You may" is the card's own word on
        # all three subjects, so an unanswered prompt is the ability suspended
        # rather than the ability declining.
        while any(c.kind == "optional_pay" for c in game.pending_choices):
            assert game.confirm_optional_pay(0, card.name, accept=True), (
                f"{card.name}: its own offer could not be accepted"
            )
            # The offer's price, where it is a pick out of the graveyard
            # (Ichorid's exile) or out of the hand (Gigapede's discard),
            # answered by the pick's own default: which card pays is not this
            # guard's question.
            game.auto_resolve_pending_choices(kinds=("graveyard_exile_pick", "discard"))
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
