"""A refused cast's "insufficient mana" says what taxed it: a census over every
spell tax the pool prints.

A cast prices itself before it pays (CR 601.2f), and each tax it meets is
announced as it is gathered ("Memory Lapse is taxed by Kaervek's Torch"). Round
kg2 made a refused cast the actor's alone (CR 733.1, ``engine/refusals.py``):
every line the attempt wrote is taken back with it, the tax line included — so
the caster read only "insufficient mana for Memory Lapse", with nothing to say
why the cost was {2} more than the card prints, while the web's payment-plan
preview showed the whole price. The tax now rides the refusal's own reason
(``refusals.noting``): "insufficient mana for Memory Lapse (costs {2} more:
Kaervek's Torch)", and the shared log still hears nothing.

**The census.** Every permanent in the shipped pool that prints a cost
increase is put on the opponent's battlefield, and a handful of cheap probe
spells (one per colour, a creature, an artifact) is asked whether the engine
taxes it (``spell_cost_tax`` / ``spell_symbol_tax`` — the cast path's own
readers). Each taxed pair is cast from a pool holding exactly the printed
cost: the cast must be refused for mana, its reason must name every taxing
card, and ``game.log`` must be as it was. Run backwards
(``test_the_census_names_a_reason_without_its_tax``) with the notes switched
off, every row fails.
"""
from __future__ import annotations

from unittest import mock

import pytest

import engine.mixins.stack.pool_payment as pool_payment
from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.cost_modifiers import spell_cost_tax, spell_symbol_tax
from engine.faces import compilation_units
from engine.mana_payment import mana_cost_from_symbols
from engine.models import Permanent

_CARDS = {card.name: card for card in load_catalog()}

#: Cheap spells that need no target beyond a player: one per colour, a
#: creature of each colour, an artifact, an enchantment.
PROBES = (
    "Dark Ritual", "Lightning Bolt", "Healing Salve", "Ancestral Recall",
    "Giant Growth", "Savannah Lions", "Llanowar Elves", "Grizzly Bears",
    "Sol Ring", "Bad Moon", "Merfolk of the Pearl Trident", "Raging Goblin",
    "Tranquility", "Crusade", "Fastbond",
)

_INSTANTS = {"Dark Ritual", "Lightning Bolt", "Healing Salve", "Ancestral Recall", "Giant Growth"}

_TARGETS_A_PLAYER = {"Lightning Bolt", "Healing Salve", "Ancestral Recall"}


def _board(taxer, probe, side: int, active: int) -> Game:
    game = Game(players=[
        PlayerState(name="P1", hand=[probe], library=[_CARDS["Island"]] * 5),
        PlayerState(name="P2", library=[_CARDS["Island"]] * 5),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.players[0].battlefield = [Permanent(card=_CARDS["Grizzly Bears"])]
    game.players[side].battlefield.append(Permanent(card=taxer))
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = active
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game._recompute_continuous_effects()
    return game


def _taxers() -> list:
    return sorted(
        (
            card for card in compilation_units(_CARDS.values())
            if card.primary_type not in ("instant", "sorcery")
            and "more to cast" in (card.oracle_text or "").lower()
        ),
        key=lambda card: card.name,
    )


def _cast(game, probe):
    kwargs = {}
    if probe.name in _TARGETS_A_PLAYER:
        kwargs["target_player_index"] = 1
    if probe.name == "Giant Growth":
        kwargs["target_player_index"] = 0
        kwargs["target_permanent_ids"] = [game.players[0].battlefield[0].permanent_id]
    return game.cast_from_hand(0, probe.name, **kwargs)


def _rows():
    """``(taxer, probe name, taxer's seat, active seat)``: the taxer on either
    side ("spells your opponents cast", "… you cast"), and an instant cast on
    the other seat's turn as well ("except during its controller's turn",
    Defense Grid)."""
    for taxer in _taxers():
        for name in PROBES:
            for side in (1, 0):
                for active in (0, 1):
                    if active == 0 or name in _INSTANTS:
                        yield taxer, name, side, active


def _census() -> dict:
    found = {"rows": 0, "taxers": set(), "wrong": []}
    for taxer, name, side, active in _rows():
        probe = _CARDS[name]
        game = _board(taxer, probe, side, active)
        generic, generic_names = spell_cost_tax(game, 0, probe)
        pips, pip_names = spell_symbol_tax(game, 0, probe)
        if not generic and not pips:
            continue
        names = sorted(set(generic_names) | set(pip_names))
        printed = mana_cost_from_symbols(probe.mana_cost) or {}
        pool = game.players[0].mana_pool
        for symbol, amount in printed.items():
            key = "C" if symbol == "generic" else symbol
            pool[key] = pool.get(key, 0) + amount
        if active:
            game.start_priority_window(0)
        before = list(game.log)
        result = _cast(game, probe)
        found["rows"] += 1
        found["taxers"].add(taxer.name)
        if result.supported or "insufficient mana" not in (result.details or ""):
            found["wrong"].append((taxer.name, name, "not refused for mana", result.details))
            continue
        missing = [n for n in names if n not in result.details]
        if missing or "more" not in result.details:
            found["wrong"].append((taxer.name, name, missing, result.details))
        if game.log != before:
            found["wrong"].append((taxer.name, name, "log moved", game.log[len(before):]))
    return found


@pytest.fixture(scope="module")
def census():
    return _census()


def test_a_refused_taxed_cast_names_what_taxed_it(census):
    assert census["wrong"] == [], census["wrong"][:10]


def test_the_census_examined_enough(census):
    """172 taxed rows over 17 taxers (Pursued Whale's tax is scoped to what
    the spell targets, the entry board's shape below)."""
    assert census["rows"] >= 150, census["rows"]
    assert len(census["taxers"]) >= 16, sorted(census["taxers"])


def test_the_census_names_a_reason_without_its_tax():
    """Backwards: with the notes switched off — the reason as kg2 left it —
    every taxed row reads "insufficient mana" and nothing more."""
    with mock.patch.object(pool_payment, "noting", lambda details, notes: details):
        found = _census()
    assert len(found["wrong"]) == found["rows"] >= 150, (len(found["wrong"]), found["rows"])


def test_the_entry_board_memory_lapse_against_kaervek_s_torch():
    """The entry's own words: Memory Lapse aimed at a Kaervek's Torch on the
    stack, one mana short of the {2} the Torch adds. The reason names the
    Torch and the tax; the log the other seat reads names neither."""
    game = Game(players=[
        PlayerState(name="P1", hand=[_CARDS["Kaervek's Torch"]], library=[_CARDS["Island"]] * 5),
        PlayerState(name="P2", hand=[_CARDS["Memory Lapse"]], library=[_CARDS["Island"]] * 5),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = True
    game.players[0].mana_pool["R"] = 5
    game.players[1].mana_pool.update({"U": 1, "C": 2})
    game.queue_from_hand(0, "Kaervek's Torch", target_player_index=1, x_value=2)
    before = list(game.log)

    answer = game.cast_from_hand(1, "Memory Lapse", target_stack_index=0)

    assert not answer.supported
    assert answer.details == (
        "insufficient mana for Memory Lapse (costs {2} more: Kaervek's Torch)"
    ), answer.details
    assert game.log == before
    pool = game.players[1].mana_pool
    assert (pool.get("U"), pool.get("C")) == (1, 2), pool


def test_a_refused_taxed_activation_names_what_taxed_it():
    """The activation path's twin (CR 602.2b through 601.2f): Gloom's
    "Activated abilities of white enchantments cost {3} more to activate"
    on an ability paid from a pool holding only its printed cost."""
    game = Game(players=[
        PlayerState(name="P1", library=[_CARDS["Island"]] * 5),
        PlayerState(name="P2", library=[_CARDS["Island"]] * 5),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = True
    game.players[0].battlefield = [Permanent(card=_CARDS["Circle of Protection: Red"])]
    game.players[1].battlefield = [Permanent(card=_CARDS["Gloom"])]
    game._recompute_continuous_effects()
    game.players[0].mana_pool["C"] = 1
    before = list(game.log)

    result = game.activate_permanent_ability(0, "Circle of Protection: Red", permanent_index=0)

    assert not result.supported
    assert result.details.startswith("insufficient mana to activate Circle of Protection: Red")
    assert "costs {3} more: Gloom" in result.details, result.details
    assert game.log == before
