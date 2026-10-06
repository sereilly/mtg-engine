"""CR 601.2h, through CR 602.2b: a cost that cannot be paid **as announced**
makes the activation illegal. It is not a different activation.

An activation that chooses what it pays with — "Sacrifice a creature", "Tap
two untapped Spirits you control", "Return a Forest you control to its owner's
hand", "Untap a tapped land an opponent controls", "Put a -1/-1 counter on a
creature you control", "Exile a creature you control" — carries that choice
with the action (CR 601.2b). Every one of those cost blocks in
``_activate_onto_stack`` honoured a named permanent "where it is legal" and
otherwise took its own default pick. For a seat that named nothing that is the
headless convention. For a seat that *named something* it is a substitution:
Ertai, the Corrupted ("{U}, {T}, Sacrifice a creature or enchantment: Counter
target spell"), told to sacrifice a Sol Ring, sacrificed **Ertai**.

``AbilityActivationMixin._named_cost_refusal`` is the one check, over the
union of the candidate lists those blocks build. The sweep below names, for
every ability in the pool with such a cost, one permanent its own cost picker
does **not** offer — and requires the activation to be refused with the board
untouched — and one it does, which must be the permanent that pays.

Measured on the tree before this file (157 abilities in the pool carry such a
cost; 118 reach the payment on the sweep's board): **118 of 118** accepted the
unoffered permanent and paid with another. 0 here. The other direction found
two: "Exile a creature you control" (City of Shadows, Food Chain) read the
slot channel alone, so a creature named by id was not read at all.

**Validated backwards**: with the check switched off the sweep names Atog,
Goblin Bombardment and Opposition again — a sacrifice and a tap cost.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compiled_units
from engine.targeting import derive_activation_spec, usable_activated_abilities
from tests.helpers import _nosick, resolve_stack

_BAIT = (
    "Grizzly Bears", "Black Knight", "Ornithopter", "Sol Ring", "Crusade",
    "Island", "Forest", "Swamp", "Goblin Balloon Brigade", "Thallid",
)

#: The cost-picker flags ``targeting.COST_PICKER_FLAGS`` whose answer is a
#: permanent on the battlefield (a discard or a library-top cost names a card
#: in hand, which has its own refusal already).
_PERMANENT_COST_FLAGS = (
    "sacrifice_cost", "tap_cost", "return_cost", "untap_cost",
    "put_counter_cost", "remove_counter_cost", "exile_cost",
)


@pytest.fixture(scope="module")
def _catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def _by_name(_catalog):
    return {card.name: card for card in _catalog}


def _cost_pickers(spec: dict) -> list[dict]:
    """Every cost picker *spec* carries: the spec itself when it is one, the
    ``cost_spec`` beside a real target, and each chained ``more_costs``."""
    top = spec.get("cost_spec") or spec
    pickers = [top, *(top.get("more_costs") or ())]
    return [
        picker for picker in pickers
        if any(picker.get(flag) for flag in _PERMANENT_COST_FLAGS)
        and picker.get("kind") not in ("hand_card", "graveyard_creature")
    ]


def _chosen_cost_abilities(catalog, only=None):
    for card, program in compiled_units(catalog):
        if not program.supported or (only is not None and card.name not in only):
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            spec = derive_activation_spec(ability)
            if spec is not None and _cost_pickers(spec):
                yield card, index


def _board(card, by_name):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 8)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    source = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, source, None)
    _nosick(source)
    for seat in (0, 1):
        for name in _BAIT:
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
        # One tapped land a side, for "untap a tapped land" and so that "tap
        # an untapped …" has something it may not be paid with.
        tapped = Permanent(card=by_name["Mountain"])
        game._put_permanent_onto_battlefield(seat, tapped, None)
        tapped.tapped = True
        game.players[seat].hand.extend([by_name["Island"], by_name["Grizzly Bears"]])
        game.players[seat].graveyard.extend(
            [by_name["Grizzly Bears"], by_name["Lightning Bolt"]]
        )
    return game, source


def _offered(game, source, index) -> set[int]:
    """The ids every cost picker of *source*'s ability offers."""
    spec = game.activation_target_spec(
        game.controller_index_of(source), game.battlefield_index_of(source),
        ability_index=index,
    )
    ids: set[int] = set()
    for picker in _cost_pickers(spec):
        for entry in picker.get("valid_targets") or ():
            if entry.get("kind") != "permanent":
                continue
            permanent = game.permanent_at(entry["seat"], entry["index"])
            if permanent is not None:
                ids.add(permanent.permanent_id)
    return ids


def _state(game) -> tuple:
    return (
        tuple(
            (permanent.permanent_id, permanent.tapped,
             tuple(sorted((k, repr(v)) for k, v in permanent.metadata.items()
                          if "counter" in k)))
            for permanent in game.all_permanents()
        ),
        tuple(len(player.hand) for player in game.players),
        tuple(len(player.graveyard) for player in game.players),
        tuple(player.life for player in game.players),
        len(game.stack),
    )


def _paid_with(game, permanent, tapped_before, counters_before) -> bool:
    """Whether *permanent* is what a cost acted on: it left, or its tapped
    state or its counters moved."""
    if not game.is_on_battlefield(permanent):
        return True
    counters = {k: v for k, v in permanent.metadata.items() if "counter" in k}
    return permanent.tapped != tapped_before or counters != counters_before


def _sweep(catalog, by_name, only=None):
    """``(examined, substituted, honoured, ignored)``.

    *substituted*: an unoffered permanent was named and the activation went
    ahead. *ignored*: an offered permanent was named, the activation went
    ahead, and something else paid."""
    examined = honoured = 0
    substituted: list[tuple] = []
    ignored: list[tuple] = []
    for card, index in _chosen_cost_abilities(catalog, only):
        game, source = _board(card, by_name)
        if not game.is_on_battlefield(source):
            continue
        offered = _offered(game, source, index)
        slot = game.battlefield_index_of(source)
        unoffered = next(
            (
                permanent for permanent in game.all_permanents()
                if permanent.permanent_id not in offered and permanent is not source
            ),
            None,
        )
        if unoffered is not None:
            before = _state(game)
            result = game.queue_permanent_ability(
                0, card.name, permanent_index=slot, ability_index=index,
                cost_permanent_ids=[unoffered.permanent_id], x_value=1,
            )
            if result.supported:
                examined += 1
                substituted.append((f"{card.name}[{index}]", unoffered.card.name))
            elif "cannot pay its cost" in result.details:
                examined += 1
                assert _state(game) == before, (card.name, result.details)

        if not offered:
            continue
        game, source = _board(card, by_name)
        offered = _offered(game, source, index)
        # The last offered permanent rather than the first: the first is the
        # likeliest default pick, and a named payment that happens to be the
        # default proves nothing about whether naming it was read.
        named = next(
            (
                permanent for permanent in reversed(list(game.all_permanents()))
                if permanent.permanent_id in offered
            ),
            None,
        )
        if named is None:
            continue
        tapped_before = named.tapped
        counters_before = {k: v for k, v in named.metadata.items() if "counter" in k}
        result = game.queue_permanent_ability(
            0, card.name, permanent_index=game.battlefield_index_of(source),
            ability_index=index, cost_permanent_ids=[named.permanent_id], x_value=1,
        )
        if not result.supported:
            continue    # a target or a timing it does not have on this board
        if _paid_with(game, named, tapped_before, counters_before):
            honoured += 1
        else:
            ignored.append((f"{card.name}[{index}]", named.card.name))
    return examined, substituted, honoured, ignored


def test_no_named_cost_permanent_is_replaced_by_the_default_pick(_catalog, _by_name):
    examined, substituted, honoured, ignored = _sweep(_catalog, _by_name)

    assert examined >= 100, f"only {examined} unoffered payments examined"
    assert honoured >= 80, f"only {honoured} offered payments examined"
    assert substituted == [], (
        "CR 601.2h: activated naming a permanent that cannot pay, and paid "
        f"with another: {substituted[:20]}"
    )
    assert ignored == [], (
        f"named a permanent the cost picker offers, and another paid: {ignored[:20]}"
    )


def test_the_sweep_finds_the_substitution_with_the_check_switched_off(
    _catalog, _by_name, monkeypatch
):
    # Not Ertai: its ability also owes a spell on the stack, which this
    # sweep's board does not hold, so it is refused before any cost is read.
    # The card tests below drive it with one.
    only = frozenset({"Atog", "Goblin Bombardment", "Opposition"})
    assert _sweep(_catalog, _by_name, only=only)[1] == []

    monkeypatch.setattr(
        Game, "_named_cost_refusal", lambda self, *args, **kwargs: None
    )
    _examined, substituted, _honoured, _ignored = _sweep(_catalog, _by_name, only=only)

    assert {label for label, _named in substituted} == {
        "Atog[0]", "Goblin Bombardment[0]", "Opposition[0]",
    }


def _table(by_name, mine=(), theirs=()):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 8)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    rows = []
    for seat, names in enumerate((mine, theirs)):
        row = []
        for name in names:
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_nosick(permanent))
        rows.append(row)
    return game, rows[0], rows[1]


def test_ertai_told_to_sacrifice_a_sol_ring_is_refused_and_sacrifices_nothing(_by_name):
    """"{U}, {T}, Sacrifice a creature or enchantment: Counter target spell."
    A Sol Ring is neither. Named as the payment it used to be dropped, and the
    default pick — the smallest creature the payer has, which was Ertai — went
    to the graveyard instead."""
    game, (ertai, ring), _ = _table(_by_name, ["Ertai, the Corrupted", "Sol Ring"])
    game.players[1].hand.append(_by_name["Grizzly Bears"])
    assert game.queue_from_hand(1, "Grizzly Bears").supported

    refused = game.queue_permanent_ability(
        0, "Ertai, the Corrupted", target_stack_index=0,
        cost_permanent_ids=[ring.permanent_id],
    )

    assert not refused.supported
    assert refused.details == "Ertai, the Corrupted: Sol Ring cannot pay its cost"
    assert game.is_on_battlefield(ertai) and not ertai.tapped
    assert game.is_on_battlefield(ring)
    assert len(game.stack) == 1 and game.players[0].graveyard == []


def test_ertai_still_takes_the_default_when_nothing_is_named(_by_name):
    """The other half, and half the test corpus: a payment the caller did not
    name is the engine's deterministic pick, exactly as before."""
    game, (ertai, crusade), _ = _table(_by_name, ["Ertai, the Corrupted", "Crusade"])
    game.players[1].hand.append(_by_name["Grizzly Bears"])
    assert game.queue_from_hand(1, "Grizzly Bears").supported

    result = game.queue_permanent_ability(
        0, "Ertai, the Corrupted", target_stack_index=0,
    )
    resolve_stack(game)

    assert result.supported and ertai.tapped
    assert not game.is_on_battlefield(crusade) and game.is_on_battlefield(ertai)
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_a_slot_names_a_cost_permanent_as_plainly_as_an_id(_by_name):
    """``cost_permanent_index`` is the same announcement on the other channel:
    a slot on the payer's battlefield holding something that cannot pay."""
    game, (ertai, ring, bears), _ = _table(
        _by_name, ["Ertai, the Corrupted", "Sol Ring", "Grizzly Bears"],
    )
    game.players[1].hand.append(_by_name["Grizzly Bears"])
    assert game.queue_from_hand(1, "Grizzly Bears").supported

    refused = game.queue_permanent_ability(
        0, "Ertai, the Corrupted", target_stack_index=0, cost_permanent_index=1,
    )

    assert not refused.supported and "Sol Ring cannot pay" in refused.details
    assert all(game.is_on_battlefield(perm) for perm in (ertai, ring, bears))

    paid = game.queue_permanent_ability(
        0, "Ertai, the Corrupted", target_stack_index=0, cost_permanent_index=2,
    )

    assert paid.supported and not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(ertai)


def test_a_tapped_creature_cannot_be_named_to_pay_a_tap_cost(_by_name):
    """"Tap an untapped creature you control: Tap target artifact, creature,
    or land." (Opposition.) A creature already tapped is not a payment
    (CR 107.5 says as much of {T}); named, it was skipped and another creature
    tapped."""
    game, (opposition, tapped, fresh), (island,) = _table(
        _by_name, ["Opposition", "Grizzly Bears", "Grizzly Bears"], ["Island"],
    )
    tapped.tapped = True

    refused = game.queue_permanent_ability(
        0, "Opposition", target_permanent_ids=[island.permanent_id],
        cost_permanent_ids=[tapped.permanent_id],
    )

    assert not refused.supported
    assert refused.details == "Opposition: Grizzly Bears cannot pay its cost"
    assert not fresh.tapped and not island.tapped and game.stack == []


def test_an_opponents_permanent_cannot_be_named_as_a_sacrifice(_by_name):
    """A sacrifice is of a permanent the payer controls (CR 701.21a)."""
    game, (bombardment, mine), (theirs,) = _table(
        _by_name, ["Goblin Bombardment", "Grizzly Bears"], ["Grizzly Bears"],
    )

    refused = game.queue_permanent_ability(
        0, "Goblin Bombardment", target_player_index=1,
        cost_permanent_ids=[theirs.permanent_id],
    )

    assert not refused.supported
    assert game.is_on_battlefield(mine) and game.is_on_battlefield(theirs)
    assert game.players[1].life == 20 and game.stack == []


def test_a_card_that_does_not_answer_an_exile_cost_cannot_be_named(_by_name):
    """"Exile a creature card from your graveyard: …" (Necropolis). The object
    is a card in a pile, named by slot; a slot holding a Lightning Bolt is not
    a payment, and it used to be replaced by the first creature card."""
    game, (necropolis,), _ = _table(_by_name, ["Necropolis"])
    game.players[0].graveyard.extend(
        [_by_name["Lightning Bolt"], _by_name["Grizzly Bears"]]
    )

    refused = game.queue_permanent_ability(0, "Necropolis", cost_permanent_index=0)

    assert not refused.supported
    assert [card.name for card in game.players[0].graveyard] == [
        "Lightning Bolt", "Grizzly Bears",
    ]

    paid = game.queue_permanent_ability(0, "Necropolis", cost_permanent_index=1)

    assert paid.supported
    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt"]


def test_an_ability_activated_from_a_graveyard_makes_the_same_refusal(_by_name):
    """"Sacrifice a snow land: Return this card from your graveyard to your
    hand." (Whiteout.) The same announcement made for a card in a graveyard
    (CR 113.6m): a Forest that is not snow cannot pay, and naming it used to
    sacrifice the snow land beside it."""
    game, (forest, snow), _ = _table(_by_name, ["Forest", "Snow-Covered Forest"])
    game.players[0].graveyard.append(_by_name["Whiteout"])

    refused = game.activate_from_graveyard(
        0, "Whiteout", cost_permanent_id=forest.permanent_id,
    )

    assert not refused.supported
    assert refused.details == "Whiteout: Forest cannot pay its cost"
    assert game.is_on_battlefield(snow) and game.is_on_battlefield(forest)
    assert [card.name for card in game.players[0].graveyard] == ["Whiteout"]

    paid = game.activate_from_graveyard(
        0, "Whiteout", cost_permanent_id=snow.permanent_id,
    )
    resolve_stack(game)

    assert paid.supported and not game.is_on_battlefield(snow)
    assert [card.name for card in game.players[0].hand] == ["Whiteout"]
