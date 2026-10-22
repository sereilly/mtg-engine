""""You may <action>. **If you do**, …" asks whether the action happened.

For most offers taking the offer *is* the doing: "you may sacrifice this
creature. If you do, destroy target creature" has nothing between the yes and
the sacrifice, and ``handlers/offers._action_is_takeable`` withdraws an
offer whose action has nothing to act on. One family is different. Where the
offered action is **a pick out of a hidden zone**, the yes is followed by a
second prompt — which card — and the seat may hold no eligible card or decline
the pick itself. The if-you-do branch ran anyway:

* **Forsaken City** — "you may exile a card from your hand. If you do, untap
  this land" untapped for a seat that accepted and then exiled nothing, and for
  a seat that accepted over an empty hand. The AI's pricing of that trade
  (``ai_policy.offer_trade_is_worth_taking``) refused it outright for this
  reason: taken by a seat nobody asks it was a free untap, because the pick
  defaulted to "no card".
* **Metathran Aerostat** — "you may put a creature card with mana value X from
  your hand onto the battlefield. If you do, return this creature to its
  owner's hand" returned the Aerostat to hand over a hand with no such card:
  {X}{U} to dodge anything, which is not the card.

The lowering names what "do" means for these offers (``then_if``), the handler
applies it as the accept branch runs, and the pick behind an accepted offer
now defaults to a card rather than to nothing.

The per-card halves are in each card's set file; this is the pool-wide census
and the invented card.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.faces import compilation_units
from engine.game_types import CardDefinition, OracleExecutionContext, Permanent
from engine.handlers import EFFECT_HANDLERS
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from tests.helpers import resolve_stack

#: The offered actions that arm a pick out of a hand.
_HAND_PICKS = {"exile_chosen_card_from_hand", "put_chosen_card_from_hand_onto_battlefield"}


def _card(name: str, type_line: str, text: str = "", *, cmc: float = 0.0, **raw):
    return CardDefinition(
        name=name, mana_cost="", cmc=cmc, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, **raw},
    )


def _instructions(value):
    if isinstance(value, OracleInstruction):
        yield value
        value = value.payload
    if isinstance(value, dict):
        value = tuple(value.values())
    if isinstance(value, (list, tuple)):
        for inner in value:
            yield from _instructions(inner)


def _hand_pick_offers(pool):
    """``(card, may)`` for every offer in *pool* whose action is one hand pick
    and whose accept branch has something behind it."""
    for card in compilation_units(pool):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        roots = [
            *program.instructions,
            *(mode.instruction for mode in program.modes),
            *(ability.instruction for ability in program.activated_abilities),
            *(ability.instruction for ability in program.triggered_abilities),
        ]
        seen: list[OracleInstruction] = []
        for step in _instructions(roots):
            if step.kind != "may" or any(step is found for found in seen):
                continue
            seen.append(step)
            action = tuple(step.payload.get("action") or ())
            if (
                len(action) == 1 and action[0].kind in _HAND_PICKS
                and step.payload.get("then")
            ):
                yield card, step


def _signature(game: Game):
    """Everything an if-you-do branch could have moved, and not the log."""
    return (
        [
            [(perm.card.name, perm.tapped) for perm in game.controlled_by(seat)]
            for seat in range(len(game.players))
        ],
        [[c.name for c in p.hand] for p in game.players],
        [[c.name for c in p.exile] for p in game.players],
        [[c.name for c in p.graveyard] for p in game.players],
        [p.life for p in game.players],
        len(game.delayed_triggers),
        len(getattr(game, "cast_permissions", ()) or ()),
    )


def _offer_on_a_board(card, step, *, hand):
    """*step* offered to seat 0 on a board holding its source (tapped) and
    *hand*, with the costs an offer may also print taken off: this census is
    about the action, and a cost nobody can pay would withdraw the offer."""
    game = Game(players=[PlayerState(name="A", hand=list(hand)), PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    source = None
    if card.primary_type not in ("instant", "sorcery"):
        source = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, source, None)
        game.pending_choices.clear()
        game.stack.clear()
        source.tapped = True
    free = OracleInstruction("may", "", {
        key: value for key, value in step.payload.items()
        if key not in ("cost", "cost_per", "cost_alternatives", "life_cost")
    })
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=card,
        source_permanent=source, x_value=2,
        trigger_context={"event_subject_player": 0},
    )
    before = _signature(game)
    EFFECT_HANDLERS["may"](game, free, context)
    return game, before


def _accept(game: Game) -> bool:
    offered = [c for c in game.pending_choices if c.kind == "optional_pay"]
    for choice in offered:
        assert game.confirm_optional_pay(choice.player_index, accept=True)
    return bool(offered)


def test_an_accepted_offer_with_nothing_to_pick_does_nothing(catalog):
    """The census, first half: every hand-pick offer in the pool, accepted by a
    seat whose hand holds **no eligible card**. Either the offer is not made or
    nothing follows from taking it.

    On the tree this was written against two did something: Forsaken City
    untapped and Metathran Aerostat returned to its owner's hand.
    """
    examined, moved = 0, []
    for card, step in _hand_pick_offers(catalog):
        examined += 1
        game, before = _offer_on_a_board(card, step, hand=())
        _accept(game)
        game.auto_resolve_pending_choices()
        if _signature(game) != before:
            moved.append(card.name)
    # Forsaken City, Metathran Aerostat and Flash on the tree this was written
    # against. (The four whose accept branch only *reads* the pick's record —
    # Ice Cauldron, Sneak Attack, Cauldron Dance, Surprise Deployment — are
    # folded into the offer after it is lowered and are safe by construction.)
    assert examined >= 3, examined
    assert moved == []


def test_a_pick_declined_after_the_offer_was_taken_buys_nothing(catalog):
    """The second half: the seat holds an eligible card, takes the offer, and
    then **declines the pick** where the prompt lets it. Yes-then-no is no."""
    examined, moved = 0, []
    filler = _card("Filler", "Artifact")
    for card, step in _hand_pick_offers(catalog):
        if step.payload["action"][0].kind != "exile_chosen_card_from_hand":
            continue  # the put-onto-the-battlefield pick has no Decline
        examined += 1
        game, before = _offer_on_a_board(card, step, hand=(filler,))
        assert _accept(game), card.name
        assert game.confirm_exile_from_hand_choice(0, None), card.name
        game.auto_resolve_pending_choices()
        if _signature(game) != before:
            moved.append(card.name)
    assert examined >= 1, examined
    assert moved == []


# -- an invented card: Forsaken City's sentence on a creature -------------------


def _sentry_at_upkeep(*, hand, interactive):
    sentry = _card(
        "Sleepy Sentry", "Creature — Wall",
        "This creature doesn't untap during your untap step.\n"
        "At the beginning of your upkeep, you may exile a card from your hand. "
        "If you do, untap this creature.",
        power="0", toughness="4",
    )
    program = compile_card_oracle(sentry)
    assert program.supported, program.reason
    game = Game(players=[
        PlayerState(name="P1", hand=list(hand), library=[_card("Deck", "Artifact")] * 3),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    perm = Permanent(card=sentry)
    game._put_permanent_onto_battlefield(0, perm, None)
    perm.tapped = True
    game.resolve_upkeep(0)
    if game.stack and not game.pending_choices:
        game.resolve_top_of_stack(pause_for_choices=True)
    return game, perm


def test_an_invented_card_untaps_only_for_a_card_actually_exiled():
    """Accept, then decline the pick: still tapped, hand intact. Accept, then
    exile: untapped, and the card is in exile."""
    spare = _card("Spare", "Artifact")
    game, sentry = _sentry_at_upkeep(hand=[spare], interactive={0})
    assert game.confirm_optional_pay(0, accept=True)
    assert sentry.tapped, "not before a card is exiled"
    assert game.confirm_exile_from_hand_choice(0, None)
    resolve_stack(game)
    assert sentry.tapped
    assert [c.name for c in game.players[0].hand] == ["Spare"]
    assert "Sleepy Sentry untapped" not in " ".join(game.log)

    game, sentry = _sentry_at_upkeep(hand=[spare], interactive={0})
    assert game.confirm_optional_pay(0, accept=True)
    assert game.confirm_exile_from_hand_choice(0, 0)
    resolve_stack(game)
    assert not sentry.tapped
    assert [c.name for c in game.players[0].exile] == ["Spare"]


def test_an_invented_card_makes_no_offer_over_an_empty_hand():
    """Nothing to exile is an offer never made, not one a seat can accept."""
    game, sentry = _sentry_at_upkeep(hand=[], interactive={0})
    resolve_stack(game)

    assert [c.kind for c in game.pending_choices] == []
    assert sentry.tapped


@pytest.mark.parametrize("hand, exiled", [
    (("Costly", "Cheap", "Middling"), "Cheap"),
    (("Cheap", "Also Cheap"), "Cheap"),
])
def test_the_pick_behind_a_taken_offer_defaults_to_the_cheapest_card(hand, exiled):
    """A seat nobody asks that has **taken** the offer exiles a card: the
    eligible one with the lowest mana value, the earliest of equals. It used to
    answer "no card" — after answering yes — and untap for free."""
    costs = {"Costly": 6.0, "Middling": 3.0, "Cheap": 1.0, "Also Cheap": 1.0}
    cards = [_card(name, "Artifact", cmc=costs[name]) for name in hand]
    game, sentry = _sentry_at_upkeep(hand=cards, interactive={0})

    assert game.confirm_optional_pay(0, accept=True)
    assert game.pending_choice_of("exile_from_hand_choice", 0) is not None
    # Through the registry's own default path, which is what resumes the
    # resolution the pick suspended.
    game.interactive_seats = set()
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert [c.name for c in game.players[0].exile] == [exiled]
    assert not sentry.tapped
    assert len(game.players[0].hand) == len(hand) - 1
