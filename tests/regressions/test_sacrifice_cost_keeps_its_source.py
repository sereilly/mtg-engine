"""A "Sacrifice <noun phrase>:" activation cost paid by a seat that names no
victim keeps the ability's **own source** for last.

"Sacrifice a creature: This creature gets +2/+2 until end of turn" (Nantuko
Husk) may legally be paid with the Husk itself — "a creature" does not exclude
it (CR 602.2b through 601.2h) — and then the ability does nothing. The default
pick (``DeathsMixin.default_sacrifice_pick``) ranked a seat's permanents by
"loses the game", then power, then ``permanent_id``, so on a power tie the
older permanent went, which is usually the source: it was on the battlefield
before the creature it was meant to eat. Every one of the pool's 45 examinable
"Sacrifice a <noun>:" abilities whose source can pay its own cost fed the
source to itself beside an equal creature (found by W1G13 beside Onslaught's
Nantuko Husk; Phyrexian Ghoul, Fallen Angel and Cateran Overlord ship).

The default now ranks the ability's source after everything but a death that
loses the game (``sacrifice_preference_key``'s *paying_for*). A seat that
wants the source gone names it, and that is honoured; a source that is the
only candidate still pays.

The census drives the real activation path over both manifest roles, with the
source on the battlefield first and an exact copy of it beside (equal power,
and every characteristic a filter reads), and reads the first permanent the
**cost** sacrificed — never the board afterwards, which an effect (Dust Bowl
naming itself) or a trigger (Marjhan without an Island) can also empty.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.mixins.deaths import DeathsMixin
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, _mk_creature_card, resolve_stack

#: How many activations the census must examine. 45 at the time of writing
#: (both manifest roles); a census that examined nothing would pass.
_CENSUS_FLOOR = 40


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _census_board(pool, card, cost, step):
    """Seat 0 with *card* first and its copy beside, seat 1 with something for
    a target to name (a creature, an enchantment, a land), and the second half
    of a conjoined sacrifice on seat 0's side."""
    players = [PlayerState(name="P"), PlayerState(name="Q")]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_step = step
    source = _put(game, 0, card)
    _put(game, 0, card)
    for extra in (
        _mk_creature_card("Q Bear", 2, 2),
        _mk_card("Q Charm", "Enchantment"),
        pool["Plains"],
    ):
        _put(game, 1, extra)
    players[0].graveyard.append(_mk_creature_card("P Dead Bear", 2, 2))
    if cost.sacrifice_also_filter is not None:
        for swamp in ("Swamp", "Snow-Covered Swamp"):
            if swamp in pool:
                _put(game, 0, pool[swamp])
    game._sync_control()
    game.stack.clear()
    game.pending_choices.clear()
    return game, source


def _first_cost_victim(game, name, index):
    """Activate and return the first permanent sacrificed (the cost is paid
    before the ability resolves), or None when the activation was refused."""
    sacrificed: list = []
    original = game.sacrifice_permanent

    def spy(permanent, *args, **kwargs):
        sacrificed.append(permanent)
        return original(permanent, *args, **kwargs)

    game.sacrifice_permanent = spy
    result = game.activate_permanent_ability(0, name, ability_index=index)
    if not result.supported or not sacrificed:
        return None
    return sacrificed[0]


def _census() -> tuple[int, list[str]]:
    """(examined, the abilities whose cost took their own source)."""
    pool: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        pool.setdefault(card.name, card)
    examined = 0
    offenders: list[str] = []
    for name, card in sorted(pool.items()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(program.activated_abilities):
            cost = ability.cost
            if not ability.supported or cost is None or cost.sacrifice_filter is None:
                continue
            if cost.sacrifice_self or cost.sacrifice_count not in (1, None):
                continue
            victim = None
            for step in ("precombat_main", "upkeep"):
                game, source = _census_board(pool, card, cost, step)
                if not game.is_on_battlefield(source):
                    break
                candidates = game._sacrifice_cost_candidates(cost, 0, source)
                if not any(c is source for c in candidates) or len(candidates) < 2:
                    break
                victim = _first_cost_victim(game, name, index)
                if victim is not None:
                    break
            if victim is None:
                continue
            examined += 1
            if victim is source:
                offenders.append(f"{name}: {ability.source_line}")
    return examined, offenders


def test_no_sacrifice_cost_default_takes_its_own_source_beside_an_equal():
    examined, offenders = _census()
    assert examined >= _CENSUS_FLOOR, examined
    assert offenders == []


def _old_default(candidates, *, paying_for=None):
    """The default before the fix: *paying_for* was not an argument."""
    return min(
        candidates, key=lambda permanent: DeathsMixin.sacrifice_preference_key(permanent),
    )


def test_the_census_names_the_defect_with_the_old_default_restored(monkeypatch):
    """Backwards: the census is only worth its zero if it names the defect on a
    tree that has it."""
    monkeypatch.setattr(Game, "default_sacrifice_pick", staticmethod(_old_default))
    examined, offenders = _census()
    assert examined >= _CENSUS_FLOOR, examined
    assert len(offenders) >= _CENSUS_FLOOR, offenders
    assert any(row.startswith("Nantuko Husk:") for row in offenders)


def _table(*cards):
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    permanents = [_put(game, 0, card) for card in cards]
    game._sync_control()
    return game, permanents


def test_nantuko_husk_eats_the_creature_beside_it_not_itself(set_pool):
    """"Sacrifice a creature: This creature gets +2/+2 until end of turn."
    Beside a 2/2 of equal power, a seat naming no victim gives up the 2/2 and
    the Husk is 4/4; with the Husk alone it is the only payment there is."""
    husk_card = set_pool("ONS")["Nantuko Husk"]
    game, (husk, bear) = _table(husk_card, _mk_creature_card("Equal Bear", 2, 2))
    alice = game.players[0]
    assert game.activate_permanent_ability(0, "Nantuko Husk").supported
    resolve_stack(game)
    assert [card.name for card in alice.graveyard] == ["Equal Bear"]
    assert game.is_on_battlefield(husk)
    assert (husk.effective_power, husk.effective_toughness) == (4, 4)

    assert game.activate_permanent_ability(0, "Nantuko Husk").supported
    resolve_stack(game)
    assert not game.is_on_battlefield(husk)
    assert [card.name for card in alice.graveyard] == ["Equal Bear", "Nantuko Husk"]


def test_a_seat_that_names_the_source_sacrifices_the_source(set_pool):
    """The default is a default: naming the Husk pays with the Husk."""
    husk_card = set_pool("ONS")["Nantuko Husk"]
    game, (husk, bear) = _table(husk_card, _mk_creature_card("Equal Bear", 2, 2))
    assert game.activate_permanent_ability(
        0, "Nantuko Husk", cost_permanent_ids=[husk.permanent_id],
    ).supported
    resolve_stack(game)
    assert not game.is_on_battlefield(husk)
    assert game.is_on_battlefield(bear)


def test_a_counted_sacrifice_cost_offers_the_source_last():
    """"Sacrifice two creatures: Draw a card." on a creature (an invented card
    — nothing printed lets the source answer a counted cost today, but the
    shape is one line away): the default fills the count from the others."""
    glutton = _mk_creature_card(
        "Pit Glutton", 2, 2, "Sacrifice two creatures: Draw a card.",
    )
    game, (source, first, second) = _table(
        glutton, _mk_creature_card("A", 2, 2), _mk_creature_card("B", 2, 2),
    )
    alice = game.players[0]
    alice.library = [_mk_creature_card("Drawn", 1, 1)] * 2
    assert game.activate_permanent_ability(0, "Pit Glutton").supported
    resolve_stack(game)
    assert sorted(card.name for card in alice.graveyard) == ["A", "B"]
    assert game.is_on_battlefield(source)
    assert [card.name for card in alice.hand] == ["Drawn"]


def test_a_game_losing_death_still_ranks_before_the_source():
    """The one thing the source is not kept behind: a permanent whose death
    loses the game (Lich beside the Aura paying for its own ability)."""
    game, (aura, lich) = _table(
        _mk_card("Paying Aura", "Enchantment", "{W}, Sacrifice an enchantment: You gain 1 life."),
        _mk_card(
            "Doom Pact", "Enchantment",
            "When this enchantment is put into a graveyard from the battlefield, you lose the game.",
        ),
    )
    assert game.default_sacrifice_pick([aura, lich], paying_for=aura) is aura
    assert game.default_sacrifice_pick([lich, aura], paying_for=lich) is aura


@pytest.mark.parametrize("paying_for_index", [None, 0, 1])
def test_without_a_source_the_order_is_unchanged(paying_for_index):
    """*paying_for* None leaves every other caller's order exactly as it was:
    the smallest, then the older."""
    game, (small, big) = _table(
        _mk_creature_card("Small", 1, 1), _mk_creature_card("Big", 4, 4),
    )
    source = None if paying_for_index is None else [small, big][paying_for_index]
    expected = big if source is small else small
    assert game.default_sacrifice_pick([big, small], paying_for=source) is expected
