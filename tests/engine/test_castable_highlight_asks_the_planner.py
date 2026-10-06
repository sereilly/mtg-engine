"""The castable highlight says "payable" exactly when the board can pay.

``web/state_view`` summed every untapped land's every listed colour into a
"potential pool", so a land offering two colours was two mana whenever a cost
wanted both: Craw Wurm ({4}{G}{G}) over three Tropical Islands glowed and the
cast was refused. It asks ``engine.board_payment.board_can_pay`` now — an exact
matching (``mana_payment.plan_payment``) of the cost's pips to the mana in the
pool and the mana each land's tap would add, with what a tap makes read off the
tap seam instead of off the printed ``produced_mana`` summary.

This is the census that says so, in **both** directions, over every supported
land in either manifest role, alone and in a pair, against a colourless
sorcery of every cost of one to three symbols the land could be asked for
(its listed symbols, generic, and one symbol it does not list):

* OVER  — the card glows and no tapping can pay for it (the measured defect);
* UNDER — some tapping pays for it and the card is dark (what a stricter
  check introduces: a land that makes two mana a tap, counted as one).

The truth is found the long way and owes nothing to the reader under test:
every combination of (tap-alone mana ability, colour asked for) per land is
tapped through ``Game.tap_land_for_mana``, and the cast path's own payment is
asked of the pool that leaves.

Before the fix (``census_highlight.py`` in the W2G3 scratch directory, the same
matrix): 3,543 of 14,626 pairs OVER on 99 of 199 lands, 59 UNDER on 5.
"""
from __future__ import annotations

import copy
import itertools
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.restricted_mana import CAST, PaymentPurpose
from engine.targeting import usable_activated_abilities
from web.app import app, store
from web.state_view import _compute_playable_hand_indices

client = TestClient(app)
_SYMBOLS = ("W", "U", "B", "R", "G", "C")

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)


@pytest.fixture(scope="module")
def session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4243,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return store.get(sid)


def _w2g3_cost_card(cost: tuple[str, ...]) -> CardDefinition:
    """A colourless sorcery that costs *cost* and needs no target — so the
    only question a board answers about it is whether it can be paid for."""
    generic = sum(1 for symbol in cost if symbol == "1")
    printed = (f"{{{generic}}}" if generic else "") + "".join(
        f"{{{symbol}}}" for symbol in cost if symbol != "1"
    )
    return CardDefinition(
        name="Cost " + printed, mana_cost=printed, cmc=float(len(cost)),
        type_line="Sorcery", oracle_text="You gain 1 life.", colors=(),
        color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Cost " + printed, "type_line": "Sorcery"},
    )


def _w2g3_costs_for(land: CardDefinition) -> list[CardDefinition]:
    symbols = sorted({str(s).upper() for s in (land.produced_mana or ())} | {"1"})
    control = next((s for s in _SYMBOLS if s not in symbols), None)
    if control is not None:
        symbols.append(control)
    costs: list[tuple[str, ...]] = []
    for size in (1, 2, 3):
        costs.extend(itertools.combinations_with_replacement(symbols, size))
    costs.extend([("1",) * 4, ("1",) * 5, ("1",) * 6])
    return [_w2g3_cost_card(cost) for cost in costs]


def _w2g3_lands() -> list[str]:
    return sorted(
        card.name for card in compilation_units(_POOL.values())
        if card.face_of is None and card.primary_type == "land"
        and compile_card_oracle(card).supported
    )


def _w2g3_board(session, names, hand) -> Game:
    library = [_POOL["Grizzly Bears"]] * 10
    game = Game(players=[
        PlayerState(name="Host", library=list(library)),
        PlayerState(name="Guest", library=list(library)),
    ])
    game.enforce_mana_costs = True
    game.players[0].battlefield = [Permanent(card=_POOL[name]) for name in names]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    game.players[0].hand = list(hand)
    game.turn = 3
    session.game = game
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return game


def _w2g3_tap_options(game: Game, permanent: Permanent) -> list[tuple]:
    """Every (mana ability, colour) a seat may ask the tap seam for."""
    indices: list = [None]
    usable = usable_activated_abilities(
        compile_card_oracle(game.playable_card_of(permanent))
    )
    for index, ability in enumerate(usable):
        if is_tap_alone_mana_ability(ability) and (
            game.land_mana_tap_refusal(permanent, index) is None
        ):
            indices.append(index)
    return [(index, color) for index in indices for color in _SYMBOLS]


def _w2g3_payable(session, names, cards) -> set[str]:
    """The cost cards some way of tapping *names* pays for — found by tapping
    every combination through the seam and asking the cast path's payment."""
    probe = _w2g3_board(session, names, [])
    options = [_w2g3_tap_options(probe, perm) for perm in probe.controlled_by(0)]
    payable: set[str] = set()
    seen: set[str] = set()
    for combo in itertools.product(*options):
        game = _w2g3_board(session, names, [])
        player = game.players[0]
        try:
            for perm, (index, color) in zip(list(game.controlled_by(0)), combo):
                game.tap_land_for_mana(
                    0, perm.card.name, color,
                    permanent_id=perm.permanent_id, ability_index=index,
                )
        except ValueError:
            # An any-colour land asked for {C}: not a request the seam accepts.
            continue
        state = repr((sorted(player.mana_pool.items()), sorted(
            (key, sorted(bucket.items())) for key, bucket in player.restricted_mana.items()
        )))
        if state in seen:
            continue
        seen.add(state)
        for card in cards:
            if card.name in payable:
                continue
            pools = (dict(player.mana_pool), copy.deepcopy(player.restricted_mana))
            if game._pay_mana_cost(
                player, game._parse_mana_cost(card.mana_cost, x_value=0),
                purpose=PaymentPurpose(CAST, card=card),
            ):
                payable.add(card.name)
            player.mana_pool, player.restricted_mana = pools[0], pools[1]
    return payable


#: The census is cut into slices so a parallel run spreads it; every land is
#: in exactly one.
_SLICES = 4


@pytest.mark.parametrize("part", range(_SLICES))
def test_w2g3_the_highlight_glows_exactly_what_the_lands_can_pay(session, part):
    names = _w2g3_lands()[part::_SLICES]
    payable_pairs = 0
    over: Counter = Counter()
    under: Counter = Counter()
    for name in names:
        cards = _w2g3_costs_for(_POOL[name])
        for board in ([name], [name, name]):
            _w2g3_board(session, board, cards)
            glowing = {cards[i].name for i in _compute_playable_hand_indices(session, 0)}
            payable = _w2g3_payable(session, board, cards)
            payable_pairs += len(payable)
            for card in cards:
                if card.name in glowing and card.name not in payable:
                    over[f"{len(board)}x {name}"] += 1
                if card.name in payable and card.name not in glowing:
                    under[f"{len(board)}x {name}"] += 1
    assert not over, f"glows over a cost no tapping pays: {dict(over)}"
    assert not under, f"dark over a cost the lands can pay: {dict(under)}"
    # A truth that finds nothing payable would agree with a highlight that
    # never glows. Measured: 1,856 payable pairs in all, about a quarter a slice.
    assert payable_pairs >= 380, payable_pairs


def test_w2g3_the_census_reaches_the_lands_it_is_about():
    """The floors on what the slices above examine. Measured: 199 lands, 86 of
    them listing more than one symbol, 14,626 (board, cost) pairs."""
    names = _w2g3_lands()
    multi = [name for name in names if len(set(_POOL[name].produced_mana or ())) > 1]
    pairs = sum(2 * len(_w2g3_costs_for(_POOL[name])) for name in names)
    assert len(names) >= 199, len(names)
    assert len(multi) >= 86, len(multi)
    assert {"Tropical Island", "City of Brass", "Adarkar Wastes", "Ancient Tomb",
            "Coral Atoll", "Lotus Vale", "Mishra's Workshop"} <= set(names)
    assert pairs >= 14000, pairs
    assert sorted(
        name for part in range(_SLICES) for name in names[part::_SLICES]
    ) == names
