"""CR 118.9d: what a cast still owes when its mana cost is not what is paid.

    "If an alternative cost is being paid to cast a spell, any additional
    costs, cost increases, and cost reductions that affect that spell are
    applied to that alternative cost. (See rule 601.2f.)"

CR 601.2f builds the total the same way whichever cost it starts from: "the
mana cost or alternative cost (as determined in rule 601.2b), plus all
additional costs and cost increases, and minus all cost reductions". And CR
118.9 names both spellings of an alternative cost — "You may [action] rather
than pay [this object's] mana cost" and "You may cast [this object] without
paying its mana cost" — so a waiver is one too.

The cast path charged that total only when the alternative cost was itself
paid in mana (flashback, CR 702.34a). A pitched card, a life payment, a
sacrifice and a waiver each skipped the mana payment *whole*, and with it
every increase in force and the mana of every optional cost the caster had
announced. Measured on the tree before the fix (the W1G3 census this file
began as, re-run on the W2G1 base):

* **43 of 43** castable cards printing an alternative cost were cast for it
  under Sphere of Resistance with an empty pool;
* **61 of 73** buyback and kicker cards were cast under a waiver, the offer
  announced, with an empty pool; Capsize came back to hand off a Dream Halls
  discard with its {3} unpaid, and Aluren walked a creature past the Sphere.

Each census below casts three ways — untaxed (the population: a card this
board cannot cast at all says nothing), taxed with an empty pool (the cast
must be refused and must have cost nothing), and taxed with exactly the mana
owed floating (it must be cast and the pool must be empty afterwards) — and
carries a floor on how many cards reached the second and third.

The pool is both manifest roles.
"""
from __future__ import annotations

from functools import lru_cache

import pytest

from engine import Game, PlayerState
from engine.alternative_costs import alternative_costs
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import buyback_cost, kicker_costs
from engine.cast_permissions import grant_permission
from engine.faces import compilation_units, whole_card
from engine.mana_payment import mana_cost_from_symbols
from engine.models import Permanent
from engine.oracle import compile_card_oracle

# The board a card is cast from: something of every colour to pitch, lands of
# every type to sacrifice or return, creatures to tap or sacrifice.
_BAIT_HAND = (
    "Grizzly Bears", "Prodigal Sorcerer", "Black Knight", "Mons's Goblin Raiders",
    "White Knight", "Forest", "Island", "Swamp", "Mountain", "Plains",
)
_BAIT_BOARD = (
    "Forest", "Forest", "Island", "Island", "Swamp", "Swamp", "Mountain",
    "Mountain", "Plains", "Plains", "Grizzly Bears", "Grizzly Bears", "Sol Ring",
)
_TAX = "Sphere of Resistance"


@lru_cache(maxsize=None)
def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


def _units() -> list:
    """Every card and every face of a multi-face card, supported ones only."""
    return sorted(
        (
            unit for unit in compilation_units(_pool().values())
            if compile_card_oracle(unit).supported
        ),
        key=lambda unit: unit.name,
    )


def _held(unit):
    """The card a hand holds for *unit*: itself, or the split card it is half of."""
    return whole_card(unit) if unit.face_of is not None else unit


def _float(player, required: dict) -> None:
    """Put exactly *required* in *player*'s pool, generic as colourless."""
    pool = {symbol: 0 for symbol in "WUBRGC"}
    for symbol, count in required.items():
        pool["C" if symbol == "generic" else symbol] += int(count)
    player.mana_pool.update(pool)


def _board(unit, *, taxed: bool) -> Game:
    by_name = _pool()
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = True
    for name in _BAIT_BOARD:
        for seat in (0, 1):
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game.players[0].hand.extend([_held(unit)] + [by_name[n] for n in _BAIT_HAND] * 2)
    game.players[1].hand.extend(by_name[n] for n in _BAIT_HAND)
    for seat in (0, 1):
        game.players[seat].graveyard.extend(
            by_name[n] for n in ("Grizzly Bears", "Black Knight", "Black Knight", "Black Knight")
        )
        game.players[seat].library.extend([by_name["Forest"]] * 10)
    if taxed:
        game._put_permanent_onto_battlefield(1, Permanent(card=by_name[_TAX]), None)
    return game


def _announce(game, unit, **spec_kwargs) -> dict:
    """The first target the card's own picker offers, as cast keywords."""
    spec = game.cast_target_spec(0, unit, **spec_kwargs)
    if spec.get("kind") == "stack" or spec.get("also_stack"):
        # Seat 1 puts a Giant Growth on the stack for a counterspell to name.
        game.enforce_mana_costs = False
        game.players[1].hand.append(_pool()["Giant Growth"])
        bears = next(p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears")
        game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
        game.enforce_mana_costs = True
        spec = game.cast_target_spec(0, unit, **spec_kwargs)
    if spec.get("kind") == "divided":
        return {"divided_targets": [(1, None, int(spec.get("division_total") or 1))]}
    for entry in spec.get("valid_targets") or []:
        kind = entry.get("kind")
        if kind == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            return {
                "target_permanent_ids": [permanent.permanent_id],
                "target_player_index": entry["seat"],
            }
        if kind == "player":
            return {"target_player_index": entry["seat"]}
        if kind == "graveyard":
            return {
                "target_player_index": entry["seat"],
                "target_permanent_index": entry["index"],
            }
        if kind == "stack":
            return {"target_stack_index": len(game.stack) - 1 - entry["stack_index"]}
    return {}


def _what_was_spent(game) -> tuple:
    """Everything a cost could have taken from seat 0."""
    player = game.players[0]
    return (
        player.life, len(player.hand), len(player.graveyard), len(player.exile),
        tuple((perm.permanent_id, perm.tapped) for perm in game.controlled_by(0)),
        tuple(sorted(player.mana_pool.items())), game.players[1].life,
    )


# ---------------------------------------------------------------------------
# A printed alternative cost that is not mana
# ---------------------------------------------------------------------------

def _cast_for_alternative(unit, *, taxed: bool, floating: dict | None = None):
    game = _board(unit, taxed=taxed)
    try:
        announcement = _announce(game, unit)
    except Exception as error:  # noqa: BLE001 - a board that cannot announce it
        return game, None, f"announce: {error}", None
    if floating:
        _float(game.players[0], floating)
    before = _what_was_spent(game)
    result = game.queue_from_hand(0, unit.name, alternative_cost=True, **announcement)
    return game, result.supported, result.details, before


@pytest.mark.cr("118.9d", "601.2f")
def test_a_cost_increase_is_charged_on_an_alternative_cost_that_is_not_mana():
    population = [unit for unit in _units() if alternative_costs(unit)]
    castable, free_under_tax, charged_for_nothing, refused_when_paid, kept_change = (
        [], [], [], [], []
    )
    for unit in population:
        _game, cast, _details, _before = _cast_for_alternative(unit, taxed=False)
        if not cast:
            continue
        castable.append(unit.name)

        game, cast, details, before = _cast_for_alternative(unit, taxed=True)
        if cast:
            free_under_tax.append(unit.name)
        elif "CR 118.9d" not in (details or "") or _what_was_spent(game) != before:
            # Refused for the right reason and with nothing spent (CR 601.2e).
            charged_for_nothing.append(f"{unit.name}: {details}")

        game, cast, details, _before = _cast_for_alternative(
            unit, taxed=True, floating={"generic": 1},
        )
        if not cast:
            refused_when_paid.append(f"{unit.name}: {details}")
        elif any(game.players[0].mana_pool.values()):
            kept_change.append(unit.name)

    assert not free_under_tax, (
        f"cast for an alternative cost under {_TAX} with an empty pool: "
        f"{free_under_tax}"
    )
    assert not charged_for_nothing, charged_for_nothing
    assert not refused_when_paid, refused_when_paid
    assert not kept_change, kept_change
    # Measured: 51 supported cards print one and 43 are castable on this board.
    assert len(population) >= 51, len(population)
    assert len(castable) >= 43, sorted(set(c.name for c in population) - set(castable))


@pytest.mark.cr("118.9d")
def test_a_cost_reduction_is_applied_to_what_an_alternative_cost_still_owes():
    """CR 601.2f: increases, then reductions — over the alternative cost too.
    Force of Will under a Sphere and a Sapphire Medallion ("Blue spells you
    cast cost {1} less to cast") owes its card, its life and no mana."""
    by_name = _pool()
    game = _board(by_name["Force of Will"], taxed=True)
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Sapphire Medallion"]), None
    )
    announcement = _announce(game, by_name["Force of Will"])
    assert game.alternative_cost_mana(0, by_name["Force of Will"]) == {
        symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C", "generic")
    }
    result = game.queue_from_hand(
        0, "Force of Will", alternative_cost=True, **announcement,
    )
    assert result.supported, result.details


@pytest.mark.cr("118.9d", "702.27a")
def test_a_buyback_announced_beside_a_granted_alternative_cost_is_paid_for():
    """Dream Halls: "…that player may discard a card that shares a color with
    that spell." The discard replaces Capsize's {1}{U}{U} and nothing else:
    the {3} of a buyback the caster announced is an additional cost."""
    by_name = _pool()

    def cast(floating: dict | None):
        game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
        game.enforce_mana_costs = True
        game._put_permanent_onto_battlefield(0, Permanent(card=by_name["Dream Halls"]), None)
        bears = Permanent(card=by_name["Grizzly Bears"])
        game._put_permanent_onto_battlefield(1, bears, None)
        game.players[0].hand.extend([by_name["Capsize"], by_name["Prodigal Sorcerer"]])
        if floating:
            _float(game.players[0], floating)
        result = game.cast_from_hand(
            0, "Capsize", alternative_cost=True, optional_cost_payments={"{3}": 1},
            target_permanent_ids=[bears.permanent_id], target_player_index=1,
        )
        return game, result

    game, result = cast(None)
    assert not result.supported and "CR 118.9d" in result.details, result.details
    assert "{3}" in result.details
    # Nothing was discarded for a cast that was not made (CR 601.2e).
    assert [card.name for card in game.players[0].hand] == ["Capsize", "Prodigal Sorcerer"]

    game, result = cast({"generic": 3})
    assert result.supported, result.details
    assert [card.name for card in game.players[0].hand] == ["Capsize"]
    assert not any(game.players[0].mana_pool.values())


# ---------------------------------------------------------------------------
# A waiver: "without paying its mana cost"
# ---------------------------------------------------------------------------

def _waiver_board(unit, *, taxed: bool = False) -> tuple:
    by_name = _pool()
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = True
    bears = Permanent(card=by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    if taxed:
        game._put_permanent_onto_battlefield(1, Permanent(card=by_name[_TAX]), None)
    game.players[0].hand.append(_held(unit))
    grant_permission(
        game, player_index=0, zone="hand", mode="cast", cards=None, free=True,
        duration="end_of_turn", source_name="Test Waiver",
    )
    return game, bears


def _mana_offers(unit) -> list[str]:
    """The optional costs *unit* prints that are mana and nothing else, with
    no X — a buyback or a kicker whose whole price can be floated."""
    text = unit.oracle_text or ""
    keys = [buyback_cost(text)] if buyback_cost(text) else list(kicker_costs(text))
    return [
        key for key in keys
        if key and key.startswith("{") and "X" not in key.upper()
        and mana_cost_from_symbols(key)
    ]


def _cast_under_waiver(unit, key: str, *, paid: bool):
    game, _bears = _waiver_board(unit)
    offers = {key: 1}
    try:
        announcement = _announce(game, unit, optional_cost_payments=offers)
        if paid:
            _float(game.players[0], mana_cost_from_symbols(key))
        result = game.queue_from_hand(
            0, unit.name, optional_cost_payments=offers, **announcement,
        )
    except Exception as error:  # noqa: BLE001 - a board that cannot announce it
        return game, None, f"announce: {error}"
    return game, result.supported, result.details


@pytest.mark.cr("118.9d", "702.33a", "702.27a")
def test_an_announced_kicker_or_buyback_is_charged_under_a_waiver():
    population = [(unit, keys[0]) for unit in _units() if (keys := _mana_offers(unit))]
    paid_for, free, refused_wrongly, kept_change = [], [], [], []
    for unit, key in population:
        game, cast, details = _cast_under_waiver(unit, key, paid=True)
        if not cast:
            continue  # this board cannot cast it kicked at any price
        paid_for.append(unit.name)
        if any(game.players[0].mana_pool.values()):
            kept_change.append(f"{unit.name} ({key})")

        game, cast, details = _cast_under_waiver(unit, key, paid=False)
        if cast:
            free.append(f"{unit.name} ({key})")
        elif "CR 118.9d" not in (details or "") or key not in details:
            refused_wrongly.append(f"{unit.name}: {details}")

    assert not free, f"cast under a waiver with the offer's mana unpaid: {free}"
    assert not refused_wrongly, refused_wrongly
    assert not kept_change, kept_change
    # Measured: 73 buyback and kicker cards print a plain mana offer; 61 are
    # castable, kicked, on this board (the rest have nothing to target).
    assert len(population) >= 73, len(population)
    assert len(paid_for) >= 61, len(paid_for)


@pytest.mark.cr("118.9d")
def test_a_waiver_does_not_waive_a_cost_increase():
    """Aluren: "Any player may cast creature spells with mana value 3 or less
    without paying their mana costs". Sphere of Resistance still asks for {1}."""
    by_name = _pool()

    def cast(waiver: str, floating: dict | None):
        game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
        game.enforce_mana_costs = True
        game._put_permanent_onto_battlefield(1, Permanent(card=by_name[_TAX]), None)
        if waiver == "Aluren":
            game._put_permanent_onto_battlefield(0, Permanent(card=by_name["Aluren"]), None)
        else:
            grant_permission(
                game, player_index=0, zone="hand", mode="cast", cards=None,
                free=True, duration="end_of_turn", source_name="Test Waiver",
            )
        game.players[0].hand.append(by_name["Grizzly Bears"])
        if floating:
            _float(game.players[0], floating)
        return game, game.queue_from_hand(0, "Grizzly Bears")

    for waiver in ("Aluren", "granted"):
        game, result = cast(waiver, None)
        assert not result.supported and "CR 118.9d" in result.details, (
            waiver, result.details,
        )
        assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]

        game, result = cast(waiver, {"generic": 1})
        assert result.supported, (waiver, result.details)
        assert not any(game.players[0].mana_pool.values())
        assert any("without paying its mana cost" in line for line in game.log)


@pytest.mark.cr("118.9d", "107.3b")
def test_a_waived_x_spell_is_still_x_zero_and_still_taxed():
    by_name = _pool()
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = True
    game._put_permanent_onto_battlefield(1, Permanent(card=by_name[_TAX]), None)
    grant_permission(
        game, player_index=0, zone="hand", mode="cast", cards=None, free=True,
        duration="end_of_turn", source_name="Test Waiver",
    )
    game.players[0].hand.append(by_name["Fireball"])
    _float(game.players[0], {"generic": 1})
    result = game.queue_from_hand(
        0, "Fireball", target_player_index=1, use_free_permission=True, x_value=5,
    )
    assert result.supported, result.details
    assert game.stack[-1].x_value == 0
    assert not any(game.players[0].mana_pool.values())
