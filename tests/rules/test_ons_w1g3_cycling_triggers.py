"""Cycling triggers — CR 702.29c's "when you cycle this card" and a
permanent's "whenever a player cycles a card".

Cycling is CR 702.29a's activated ability whose cost discards the card, and
the one seam that pays that cost (``CardActivationMixin._activate_from_hand``)
announces the cycle (``_announce_cycle``). Two conditions ride the one
announcement: the cycled card's own (``self_cycled``), which CR 702.29c has
"trigger from whatever zone the card winds up in after it's cycled", and a
permanent watching the table (``cycles_card``), narrowed by the printed seat.

What the rulings on every Onslaught card printing the trigger say (2022-12-08,
``scratch/ons/rulings/ons_rulings.txt``) is what these tests drive:

* "first the cycling ability goes on the stack, then the triggered ability
  goes on the stack on top of it. The triggered ability will resolve before
  you draw a card from the cycling ability."
* "If the triggered ability doesn't resolve (because, for example, it has been
  countered, or all of its targets have become illegal), the cycling ability
  will still resolve, and you'll draw a card."
* "You can cycle this card even if there are no legal targets for the
  triggered ability."

The fixtures are **invented** cards, so what is asserted is the rule on
anything printing it; the Onslaught cards are driven in ``tests/sets/``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from engine.activation_zones import HAND

from tests.helpers import _mk_creature_card, resolve_stack


def _card(name: str, type_line: str, *lines: str) -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "2", "2"
    text = "\n".join(lines)
    return CardDefinition(
        name=name, mana_cost="{1}{W}", cmc=2.0, type_line=type_line,
        oracle_text=text, colors=("W",), color_identity=("W",),
        keywords=("Cycling",) if "Cycling" in text else (),
        produced_mana=(), raw=raw,
    )


_CYCLING = "Cycling {2} ({2}, Discard this card: Draw a card.)"


def _self_cycler(name: str = "Cycled Hope") -> CardDefinition:
    """An instant whose cycle trigger needs no answer: "you gain 2 life"."""
    return _card(
        name, "Instant", "You gain 6 life.", _CYCLING,
        "When you cycle this card, you gain 2 life.",
    )


def _targeted_cycler() -> CardDefinition:
    """CR 702.29c's neighbour in the rules' own example (CR 115, "A sorcery
    card has the ability 'When you cycle this card, target creature gets
    -1/-1 until end of turn.'")."""
    return _card(
        "Cycled Shade", "Sorcery", "Destroy target creature.", _CYCLING,
        "When you cycle this card, target creature gets -1/-1 until end of turn.",
    )


def _plain_cycler(name: str = "Plain Cycler") -> CardDefinition:
    return _card(name, "Sorcery", "Draw two cards.", _CYCLING)


def _watcher(name: str, condition: str) -> CardDefinition:
    return _card(name, "Enchantment", f"{condition}, you gain 1 life.")


def _filler() -> CardDefinition:
    return CardDefinition(
        name="Filler", mana_cost="", cmc=0.0, type_line="Land",
        oracle_text="{T}: Add {W}.", colors=(), color_identity=(), keywords=(),
        produced_mana=("W",), raw={"name": "Filler", "type_line": "Land"},
    )


def _table(hand=(), opponent_hand=(), library: int = 5):
    alice = PlayerState(name="Alice", hand=list(hand), library=[_filler()] * library)
    bob = PlayerState(name="Bob", hand=list(opponent_hand), library=[_filler()] * library)
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    return game, alice, bob


def _put(game: Game, seat: int, card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _catalog():
    found = getattr(_catalog, "_cache", None)
    if found is None:
        found = {card.name: card for card in load_catalog()}
        _catalog._cache = found
    return found


# ---------------------------------------------------------------------------
# CR 702.29c — "when you cycle this card"
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.29c", "603.3")
def test_702_29c_the_cycled_cards_own_trigger_goes_on_the_stack_above_the_cycling_ability():
    """The trigger's source is the card in the graveyard, not a permanent, and
    the trigger is above the ability its own cost was paid for."""
    card = _self_cycler()
    game, alice, _bob = _table(hand=[card])

    assert game.activate_from_hand(0, card.name).supported
    assert [item.ability_text for item in game.stack] == [
        "{2}, Discard this card: Draw a card.",
        "When you cycle this card, you gain 2 life.",
    ]
    trigger = game.stack[-1]
    assert trigger.card is card and trigger.source_permanent is None
    assert trigger.caster_index == 0, "CR 603.3a/109.5: the card's owner controls it"
    assert alice.graveyard == [card] and alice.hand == []


@pytest.mark.cr("702.29c", "405.5")
def test_702_29c_the_trigger_resolves_before_the_cycling_draw():
    card = _self_cycler()
    game, alice, _bob = _table(hand=[card])
    assert game.activate_from_hand(0, card.name).supported

    assert game.resolve_top_of_stack()
    assert alice.life == 22, "the trigger resolved first"
    assert len(alice.library) == 5 and alice.hand == [], "and nothing was drawn yet"

    resolve_stack(game)
    assert len(alice.library) == 4 and [c.name for c in alice.hand] == ["Filler"]
    assert alice.life == 22, "the spell's own 6 life never happened"


@pytest.mark.cr("702.29c")
def test_702_29c_a_copy_already_in_the_graveyard_does_not_trigger():
    """The cycled card is the one asked — not every card in the zone it
    landed in, where a second copy was not cycled."""
    first, second = _self_cycler(), _self_cycler()
    game, alice, _bob = _table(hand=[first])
    alice.graveyard.append(second)

    assert game.activate_from_hand(0, first.name).supported
    triggers = [item for item in game.stack if item.ability_text.startswith("When")]
    assert len(triggers) == 1
    resolve_stack(game)
    assert alice.life == 22


@pytest.mark.cr("702.29c", "701.9a")
def test_702_29c_a_card_discarded_any_other_way_is_not_cycled():
    """CR 702.29c: "when you discard this card **to pay an activation cost of
    a cycling ability**". A forced discard moves the same card to the same
    graveyard and fires neither cycle trigger."""
    card = _self_cycler()
    game, alice, _bob = _table(hand=[card])
    _put(game, 0, _watcher("Cycle Watcher", "Whenever a player cycles a card"))

    game._discard_card(alice, alice.hand[0])
    resolve_stack(game)

    assert alice.graveyard == [card]
    assert alice.life == 20, game.log
    assert not any("cycled" in line for line in game.log)


@pytest.mark.cr("702.29c", "113.6j")
def test_702_29c_another_hand_ability_that_discards_its_card_is_not_cycling():
    """"{1}, Discard this card: Draw a card." printed as an ability rather than
    as the keyword (Waker of Waves' shape) pays the same cost and is not a
    cycling ability, so nothing that watches cycling sees it."""
    waker = _card(
        "Discard Draw", "Creature - Human", "{1}, Discard this card: Draw a card.",
    )
    game, alice, _bob = _table(hand=[waker])
    _put(game, 0, _watcher("Cycle Watcher", "Whenever a player cycles a card"))

    assert game.activate_from_hand(0, waker.name).supported
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Filler"], "the ability resolved"
    assert alice.life == 20, game.log


# ---------------------------------------------------------------------------
# "Whenever a player cycles a card"
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.29a", "701.9a")
def test_702_29a_cycling_is_discarding_so_a_discard_watcher_answers_it_once():
    """Cycling's cost *is* a discard (CR 702.29a), so "whenever a player
    discards a card" fires for a cycled card — once — beside the cycle
    watcher, also once."""
    card = _plain_cycler()
    game, alice, _bob = _table(hand=[card])
    _put(game, 0, _watcher("Cycle Watcher", "Whenever a player cycles a card"))
    _put(game, 0, _watcher("Discard Watcher", "Whenever a player discards a card"))

    assert game.activate_from_hand(0, card.name).supported
    names = [item.card.name for item in game.stack]
    assert names[0] == card.name
    assert sorted(names[1:]) == ["Cycle Watcher", "Discard Watcher"]
    resolve_stack(game)
    assert alice.life == 22


@pytest.mark.cr("603.2", "109.5")
@pytest.mark.parametrize(("cycler", "fires"), [
    (0, {"Any Cycle", "Own Cycle"}),
    (1, {"Any Cycle", "Opponent Cycle"}),
])
def test_603_2_the_printed_seat_narrows_whose_cycling_a_watcher_sees(cycler, fires):
    """"a player" is every seat, "you" the watcher's controller (CR 109.5),
    "an opponent" any other seat — one event, three narrowings."""
    game, alice, bob = _table(hand=[_plain_cycler("Alice Cycler")],
                              opponent_hand=[_plain_cycler("Bob Cycler")])
    _put(game, 0, _watcher("Any Cycle", "Whenever a player cycles a card"))
    _put(game, 0, _watcher("Own Cycle", "Whenever you cycle a card"))
    _put(game, 0, _watcher("Opponent Cycle", "Whenever an opponent cycles a card"))

    name = "Alice Cycler" if cycler == 0 else "Bob Cycler"
    assert game.activate_from_hand(cycler, name).supported
    fired = {item.card.name for item in game.stack[1:]}
    assert fired == fires
    resolve_stack(game)
    assert alice.life == 20 + len(fires)


@pytest.mark.cr("603.3b")
def test_603_3b_one_cycles_triggers_go_on_the_stack_active_player_first():
    """Bob is active; Alice cycles on his turn. Bob's watcher and Alice's own
    cycle trigger trigger on the one event, so Bob's goes on the stack first
    and Alice's resolves first."""
    card = _self_cycler()
    game, alice, bob = _table(hand=[card])
    game.active_player_index = 1
    _put(game, 1, _watcher("Bob's Watcher", "Whenever a player cycles a card"))

    assert game.activate_from_hand(0, card.name).supported
    assert [(item.card.name, item.caster_index) for item in game.stack] == [
        (card.name, 0), ("Bob's Watcher", 1), (card.name, 0),
    ]
    resolve_stack(game)
    assert (alice.life, bob.life) == (22, 21)


# ---------------------------------------------------------------------------
# Responding: the trigger and the cycling ability are separate objects
# ---------------------------------------------------------------------------


@pytest.mark.cr("603.3d", "702.29c")
def test_603_3d_a_card_cycles_with_no_legal_target_for_its_trigger():
    """"You can cycle this card even if there are no legal targets for the
    triggered ability." With no creature anywhere, the trigger is removed as
    it would be put on the stack and the draw still happens."""
    card = _targeted_cycler()
    game, alice, _bob = _table(hand=[card])

    assert game.activate_from_hand(0, card.name).supported
    assert [item.ability_text for item in game.stack] == [
        "{2}, Discard this card: Draw a card.",
    ]
    assert any("no legal target (603.3d)" in line for line in game.log)
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Filler"]


@pytest.mark.cr("608.2b", "702.29c")
def test_608_2b_a_cycle_trigger_whose_target_left_does_not_stop_the_draw():
    """Bob answers the trigger by Shocking its only target in response: the
    trigger has no legal target left as it resolves, and the cycling ability
    under it still draws."""
    card = _targeted_cycler()
    game, alice, bob = _table(hand=[card], opponent_hand=[_catalog()["Shock"]])
    victim = _put(game, 1, _mk_creature_card("Victim", 2, 2))

    assert game.activate_from_hand(0, card.name).supported
    assert game.stack[-1].target_permanent_id == [victim.permanent_id]
    assert game.queue_from_hand(
        1, "Shock", target_permanent_ids=[victim.permanent_id]
    ).supported
    assert game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert not game.is_on_battlefield(victim)

    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Filler"], "the cycling ability still drew"
    assert any("illegal" in line.lower() or "no longer" in line.lower()
               for line in game.log), game.log


@pytest.mark.cr("701.6a", "702.29c")
def test_701_6a_a_countered_cycle_trigger_does_not_stop_the_draw():
    """Sublime Epiphany's "Counter target activated or triggered ability" at
    the trigger (the engine's stack list is bottom-first, so it is index 1):
    no life, and the cycling ability still draws."""
    card = _self_cycler()
    epiphany = _catalog()["Sublime Epiphany"]
    game, alice, bob = _table(hand=[card], opponent_hand=[epiphany])
    assert game.activate_from_hand(0, card.name).supported

    countered = game.queue_from_hand(
        1, epiphany.name, mode_choices=[{"index": 1, "target_stack_index": 1}],
    )
    assert countered.supported, countered.details
    resolve_stack(game)

    assert alice.life == 20
    assert [c.name for c in alice.hand] == ["Filler"]
    assert any("countered Cycled Hope's triggered ability" in line for line in game.log)


@pytest.mark.cr("701.6a", "702.29c")
def test_701_6a_countering_the_cycling_ability_leaves_its_trigger():
    """Bind ("Counter target activated ability") at the cycling ability under
    the trigger: the trigger still resolves, and nobody draws off the cycle."""
    card = _self_cycler()
    bind = _catalog()["Bind"]
    game, alice, bob = _table(hand=[card], opponent_hand=[bind])
    assert game.activate_from_hand(0, card.name).supported

    assert game.queue_from_hand(1, bind.name, target_stack_index=0).supported
    resolve_stack(game)

    assert alice.life == 22
    assert alice.hand == [] and len(alice.library) == 5
    assert any("Bind countered Cycled Hope's activated ability" in line for line in game.log)


# ---------------------------------------------------------------------------
# CR 702.29b — the ability exists everywhere; the trigger asks about a cycle
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.29b", "113.6j")
def test_702_29b_a_permanent_printing_a_cycle_trigger_neither_cycles_nor_fires_on_the_battlefield():
    """A creature with cycling and "when you cycle this card" on the
    battlefield has no cycling ability to use there (CR 113.6j), and another
    card being cycled is not this one being cycled."""
    creature = _card(
        "Cycling Beast", "Creature - Beast", _CYCLING,
        "When you cycle this card, you gain 2 life.",
    )
    other = _plain_cycler()
    game, alice, _bob = _table(hand=[other])
    beast = _put(game, 0, creature)

    program = compile_card_oracle(creature)
    assert program.supported, program.reason
    assert usable_activated_abilities(program) == []
    assert len(usable_activated_abilities(program, zone=HAND)) == 1
    assert not game.activate_permanent_ability(0, creature.name).supported

    assert game.activate_from_hand(0, other.name).supported
    assert [item.card.name for item in game.stack] == [other.name]
    resolve_stack(game)
    assert alice.life == 20 and game.is_on_battlefield(beast)
