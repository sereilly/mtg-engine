"""The castable answer counts what a seat could tap, not only its lands.

``engine.board_payment.board_can_pay`` was "lands only, by decision", and it
counted a land's tap as the land's own mana and nothing the tap set off. So:

* a card payable with a **Sol Ring**, a Mox or a Llanowar Elves was dark —
  while the AI had tapped exactly those sources since Planeshift, and cast the
  spell the same board showed a human as uncastable;
* a **Mana Flare** ("…adds one additional mana of any type that land
  produced"), a Gauntlet of Might, a Vernal Bloom, an Overabundance or a
  Winter's Night doubled what a land's tap made and the answer counted one;
* past five lands that each make "N mana of any **one** color" the colours
  stopped being enumerated and every such land was read as its first option
  — all white — which refused every payment that wanted another colour.

The decision the first of those reverses is argued in the module's docstring:
"castable" is CR 601.2g's question, what the player is *able* to pay with the
mana abilities they could activate, and the highlight passes
``nonland_sources=True`` for it. The default is unchanged, so a caller planning
an automatic payment still gets lands.

**The census** is `test_castable_highlight_asks_the_planner.py`'s, extended to
the sources that one does not reach. The truth is found the long way: every
combination of (source, tap-alone mana ability, colour asked) is tapped — a
land through the seam, a non-land through the activation path — and a real
cast is tried against the pool that leaves. Measured over the pool before the
fix: all 64 non-land tap-alone sources, alone and beside a Forest, 5,730
(board, cost) pairs, 607 of them payable and dark on 112 of the 128 boards;
and 72 boards of a land under one of the six adders, 2,628 pairs, 227 payable
and dark on 35. None glowed unpayable, before or after. The committed run
samples both.

Not counted, by decision, and named in ``engine/board_payment.py``: a mana
ability that costs more than the tap (a filter land, a storage land, a Black
Lotus's sacrifice).
"""
from __future__ import annotations

import itertools
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine import board_payment
from engine.board_payment import board_can_pay
from engine.card_loader import load_catalog
from engine.land_mana_swaps import production_snapshot
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.restricted_mana import CAST, PaymentPurpose

_POOL = {card.name: card for card in load_catalog()}
_SYMBOLS = ("W", "U", "B", "R", "G", "C")

#: One non-land source per shape the reader tells apart: fixed pips ({C}{C}),
#: one colour, a creature's, a choice of two, any colour, a board-narrowed
#: "could produce", a colour chosen on entry, restricted mana, and two whose
#: ability carries a rider or a count.
_SOURCES = (
    "Sol Ring", "Mox Emerald", "Llanowar Elves", "Bloodstone Cameo",
    "Birds of Paradise", "Fellwar Stone", "Elves of Deep Shadow",
    "Soldevi Machinist", "Priest of Titania", "Thran Dynamo",
)

_ADDERS = ("Mana Flare", "Gauntlet of Might", "Vernal Bloom", "Overabundance",
           "Winter's Night")
_LANDS_UNDER_ADDERS = ("Forest", "Mountain", "Tropical Island", "Mishra's Factory")


def _cost_card(cost: tuple[str, ...]) -> CardDefinition:
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


def _fresh(names, others=()):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[_POOL["Grizzly Bears"]] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 3
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    sources = []
    # The board first, then the sources: an Overlaid Terrain sacrifices the
    # lands that were there when it arrived.
    for index, name in enumerate([*others, *names]):
        permanent = Permanent(card=_POOL[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
        if index >= len(others):
            sources.append(permanent)
    game.auto_resolve_pending_choices()
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return game, sources


def _tap_options(game, permanent):
    usable = game.usable_abilities_of(permanent)
    if permanent.has_type("land"):
        indices = [None] + [
            index for index, ability in enumerate(usable)
            if is_tap_alone_mana_ability(ability)
            and game.land_mana_tap_refusal(permanent, index) is None
        ]
    else:
        indices = [
            index for index, ability in enumerate(usable)
            if is_tap_alone_mana_ability(ability)
        ]
    return [(index, color) for index in indices for color in _SYMBOLS] + [("skip", None)]


def _tap(game, permanent, option) -> None:
    index, color = option
    if index == "skip":
        return
    try:
        if permanent.has_type("land"):
            game.tap_land_for_mana(
                0, permanent.card.name, color,
                permanent_id=permanent.permanent_id, ability_index=index,
            )
        else:
            game.queue_permanent_ability(
                0, permanent.card.name,
                permanent_index=game.battlefield_index_of(permanent),
                ability_index=index, mana_color=color if color != "C" else None,
            )
    except ValueError:
        # An any-colour ability asked for {C}: not a colour it can name.
        pass


def _pool_state(player) -> str:
    return repr(sorted(
        (str(key), sorted(bucket.items()))
        for key, bucket in production_snapshot(player).items()
    ))


def _really_payable(names, others, cards) -> set[str]:
    probe, sources = _fresh(names, others)
    options = [_tap_options(probe, permanent) for permanent in sources]
    payable: set[str] = set()
    seen: set[str] = set()
    for combo in itertools.product(*options):
        game, sources = _fresh(names, others)
        for permanent, option in zip(sources, combo):
            _tap(game, permanent, option)
        state = _pool_state(game.players[0])
        if state in seen:
            continue
        seen.add(state)
        for card in cards:
            if card.name in payable:
                continue
            trial, trial_sources = _fresh(names, others)
            for permanent, option in zip(trial_sources, combo):
                _tap(trial, permanent, option)
            trial.players[0].hand = [card]
            if trial.cast_from_hand(0, card.name).supported:
                payable.add(card.name)
    return payable


def _costs_for(names) -> list[CardDefinition]:
    symbols = set()
    for name in names:
        symbols |= {symbol.upper() for symbol in (_POOL[name].produced_mana or ())}
    symbols = sorted(symbols | {"1"})
    control = next((symbol for symbol in _SYMBOLS if symbol not in symbols), None)
    if control is not None:
        symbols.append(control)
    costs = []
    for size in (1, 2):
        costs.extend(itertools.combinations_with_replacement(symbols, size))
    costs.extend([("1",) * 3, ("1",) * 4])
    return [_cost_card(cost) for cost in costs]


def _census(boards):
    counts: Counter = Counter()
    over, under = [], []
    for names, others in boards:
        cards = _costs_for(names)
        real = _really_payable(names, others, cards)
        counts["boards"] += 1
        for card in cards:
            counts["pairs"] += 1
            game, _sources = _fresh(names, others)
            said = board_can_pay(
                game, 0, game._parse_mana_cost(card.mana_cost, x_value=0),
                purpose=PaymentPurpose(CAST, card=card), nonland_sources=True,
            )
            if said and card.name not in real:
                over.append((names, others, card.name))
            if not said and card.name in real:
                under.append((names, others, card.name))
    return counts, over, under


def _source_boards():
    return [((name,), ()) for name in _SOURCES] + [
        ((name, "Forest"), ()) for name in _SOURCES[:3]
    ]


def _adder_boards():
    return [
        ((land,), (adder,)) for adder in _ADDERS for land in _LANDS_UNDER_ADDERS[:2]
    ] + [((land,), ("Mana Flare",)) for land in _LANDS_UNDER_ADDERS[2:]]


def test_the_answer_is_exact_over_non_land_sources():
    counts, over, under = _census(_source_boards())

    assert counts["boards"] >= 13 and counts["pairs"] >= 150, counts
    assert over == [], f"glows over a cost no tapping pays: {over[:12]}"
    assert under == [], f"dark over a cost some tapping pays: {under[:12]}"


def test_the_answer_is_exact_over_what_a_tap_sets_off():
    counts, over, under = _census(_adder_boards())

    assert counts["boards"] >= 12 and counts["pairs"] >= 100, counts
    assert over == [], f"glows over a cost no tapping pays: {over[:12]}"
    assert under == [], f"dark over a cost some tapping pays: {under[:12]}"


def test_the_census_names_a_reader_that_counts_lands_alone(monkeypatch):
    """Backwards: no non-land source and no triggered mana, which is the
    answer as it was."""
    monkeypatch.setattr(board_payment, "source_tap_yields", lambda *args, **kw: [])
    monkeypatch.setattr(
        board_payment, "_with_triggered_mana",
        lambda game, land, found, purpose: found,
    )

    _counts, over, under = _census(_source_boards()[:4])
    assert over == []
    assert (("Sol Ring",), (), "Cost {2}") in under
    assert (("Llanowar Elves",), (), "Cost {G}") in under

    _counts, over, under = _census(_adder_boards()[:2])
    assert over == []
    assert (("Forest",), ("Mana Flare",), "Cost {G}{G}") in under


# --- what the door refuses, the count leaves out ----------------------------


def _pays(names, cost, *, others=(), arm=None, nonland=True) -> bool:
    game, sources = _fresh(names, others)
    if arm is not None:
        arm(game, sources)
    return board_can_pay(game, 0, dict(cost), nonland_sources=nonland)


def test_the_default_still_counts_lands_alone():
    """The signature a planner of an *automatic* payment calls is unchanged."""
    assert not _pays(("Sol Ring",), {"generic": 2}, nonland=False)
    assert _pays(("Sol Ring",), {"generic": 2})
    assert _pays(("Forest", "Forest"), {"generic": 2}, nonland=False)


def test_a_summoning_sick_creature_is_not_mana():
    def sicken(game, sources):
        sources[0].metadata["summoning_sickness_turn"] = game.turn

    assert _pays(("Llanowar Elves",), {"G": 1})
    assert not _pays(("Llanowar Elves",), {"G": 1}, arm=sicken)
    # An artifact has no such rule (CR 602.5a names creatures).
    assert _pays(("Sol Ring",), {"generic": 2}, arm=sicken)


@pytest.mark.parametrize("source,cost,ban", [
    ("Sol Ring", {"generic": 2}, "Null Rod"),
    ("Llanowar Elves", {"G": 1}, "Cursed Totem"),
    ("Sol Ring", {"generic": 2}, "Titania's Song"),
])
def test_a_source_the_door_refuses_is_not_mana(source, cost, ban):
    """One predicate for the door and the count
    (``activation_prohibitions.activation_prohibition``, and the permanent's
    own list for an ability it has lost)."""
    assert _pays((source,), cost)
    assert not _pays((source,), cost, others=(ban,))

    game, (permanent,) = _fresh((source,), (ban,))
    result = game.queue_permanent_ability(
        0, source, permanent_index=game.battlefield_index_of(permanent),
        ability_index=0,
    )
    assert not result.supported


def test_a_tapped_source_and_a_mana_ability_that_costs_more_are_not_mana():
    def tap(game, sources):
        sources[0].tapped = True

    assert not _pays(("Sol Ring",), {"generic": 1}, arm=tap)
    # "{T}, Sacrifice this artifact: Add three mana of any one color."
    assert not _pays(("Black Lotus",), {"generic": 1})


def test_six_lands_of_any_one_color_pay_a_colour_that_is_not_white():
    """"Lands you control have '{T}: Add two mana of any one color.'" Six of
    them are 15,625 colour assignments written out five ways each — past the
    cap, where each was read as its first option, {W}{W}."""
    lands = ("Forest",) * 6
    for cost in ({"G": 12}, {"U": 2, "B": 2, "R": 2, "G": 2, "W": 2, "generic": 2}):
        assert _pays(lands, cost, others=("Overlaid Terrain",), nonland=False), cost
    # Two mana of any **one** colour: one land is not {G}{U}.
    assert not _pays(("Forest",), {"G": 1, "U": 1}, others=("Overlaid Terrain",))
    assert not _pays(lands, {"G": 13}, others=("Overlaid Terrain",))
