"""Judgment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

import pytest as _w1g2_pytest

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.pt import add_plus1_counters as _w1g2_add_plus1_counters
from tests.helpers import (_nosick as _w1g2_nosick,
                           declare_attack as _w1g2_declare_attack,
                           resolve_stack as _w1g2_resolve_stack)


#: Every Phantom, with the counters its entry line prints.
_W1G2_PHANTOMS = (
    ("Phantom Centaur", 3),
    ("Phantom Flock", 3),
    ("Phantom Nantuko", 2),
    ("Phantom Nishoba", 7),
    ("Phantom Nomad", 2),
    ("Phantom Tiger", 2),
)


def _w1g2_table(set_pool, catalog_by_name, *, interactive=()):
    """Two seats with libraries, mana off, a card lookup over Judgment first
    and the shipped pool second."""
    jud = set_pool("JUD")

    def card(name):
        return jud[name] if name in jud else catalog_by_name[name]

    island = catalog_by_name["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="Alice", library=[island] * 10),
        _W1G2PlayerState(name="Bob", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g2_card = card
    return game


def _w1g2_put(game, seat, name, counters=0):
    """*name* onto *seat*'s battlefield through the one entry path, awake, with
    *counters* +1/+1 counters on top of whatever its entry gives it."""
    permanent = _W1G2Permanent(card=game._w1g2_card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g2_resolve_stack(game)
    if counters:
        _w1g2_add_plus1_counters(permanent, counters)
    _w1g2_nosick(permanent)
    return permanent


def _w1g2_counters(permanent) -> int:
    return int(permanent.metadata.get("plus_counters", 0))


def _w1g2_bolt(game, caster_seat, permanent, name="Lightning Bolt"):
    """*caster_seat* casts *name* at *permanent* and the stack resolves."""
    game.players[caster_seat].hand.append(game._w1g2_card(name))
    result = game.cast_from_hand(
        caster_seat, name,
        target_player_index=game.controller_index_of(permanent),
        target_permanent_ids=[permanent.permanent_id],
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    game._settle()


@_w1g2_pytest.mark.parametrize(("name", "entering"), _W1G2_PHANTOMS)
def test_w1g2_a_phantom_enters_with_its_counters_and_pays_one_to_shrug_off_a_bolt(
    set_pool, catalog_by_name, name, entering,
):
    """"This creature enters with N +1/+1 counters on it." / "If damage would
    be dealt to this creature, prevent that damage. Remove a +1/+1 counter from
    this creature." Cast through the real path, then bolted: the three damage
    never arrives, one counter pays for it, and the creature lives."""
    game = _w1g2_table(set_pool, catalog_by_name)
    game.players[0].hand.append(game._w1g2_card(name))
    result = game.cast_from_hand(0, name)
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    phantom = next(p for p in game.controlled_by(0) if p.card.name == name)
    assert _w1g2_counters(phantom) == entering

    _w1g2_bolt(game, 1, phantom)

    assert game.is_on_battlefield(phantom)
    assert phantom.damage_marked == 0
    assert _w1g2_counters(phantom) == entering - 1
    assert any(
        f"{name} prevented 3 damage (removed a +1/+1 counter)" in line
        for line in game.log
    ), game.log[-6:]


def test_w1g2_a_phantom_blocked_by_two_creatures_pays_one_counter(
    set_pool, catalog_by_name,
):
    """"If this creature would be dealt damage from multiple sources at the
    same time (say, because it's blocked by multiple creatures), all of the
    damage is prevented and only one +1/+1 counter is removed." (2022-12-08.)
    CR 510.2 deals the two blockers' damage at once; the engine runs one event
    per source, and the counter is paid once for the pair."""
    game = _w1g2_table(set_pool, catalog_by_name)
    tiger = _w1g2_put(game, 0, "Phantom Tiger")
    assert _w1g2_counters(tiger) == 2
    _w1g2_put(game, 1, "Grizzly Bears")
    _w1g2_put(game, 1, "Grizzly Bears")
    _w1g2_declare_attack(game, 0, blocks={0: 0, 1: 0})
    game.advance_combat_phase()
    ok, why = game.resolve_all_combat_damage(0, attacker_damage={0: {0: 2, 1: 1}})
    assert ok, why
    game._settle()

    assert game.is_on_battlefield(tiger) and tiger.damage_marked == 0
    assert _w1g2_counters(tiger) == 1, "one counter for the simultaneous pair"
    assert sum("Phantom Tiger prevented 2 damage" in line for line in game.log) == 2
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]


def test_w1g2_a_first_strike_step_and_a_regular_step_are_two_dealings(
    set_pool, catalog_by_name,
):
    """CR 510.4: a first striker's damage is its own combat damage step, so a
    Phantom blocked by a first striker and an ordinary creature is dealt damage
    twice, not at the same time — two counters, one per step. What makes the
    first test's single counter right is the step, not the combat."""
    game = _w1g2_table(set_pool, catalog_by_name)
    centaur = _w1g2_put(game, 0, "Phantom Centaur")
    assert _w1g2_counters(centaur) == 3
    _w1g2_put(game, 1, "White Knight")
    _w1g2_put(game, 1, "Grizzly Bears")
    _w1g2_declare_attack(game, 0, blocks={0: 0, 1: 0})
    game.advance_combat_phase()
    ok, why = game.resolve_all_combat_damage(0, attacker_damage={0: {0: 3, 1: 2}})
    assert ok, why
    game._settle()

    assert game.is_on_battlefield(centaur) and centaur.damage_marked == 0
    assert _w1g2_counters(centaur) == 1, "one counter per combat damage step"


def test_w1g2_a_phantom_with_no_counters_left_still_prevents(
    set_pool, catalog_by_name,
):
    """"If this creature has no +1/+1 counters on it (but is still on the
    battlefield because something else is raising its toughness), damage that
    would be dealt to it is still prevented." (2022-12-08.) Giant Growth holds
    a counterless Phantom Nomad up, and a bolt does nothing to it."""
    game = _w1g2_table(set_pool, catalog_by_name)
    nomad = _w1g2_put(game, 0, "Phantom Nomad")
    game.players[0].hand.append(game._w1g2_card("Giant Growth"))
    assert game.cast_from_hand(
        0, "Giant Growth", target_player_index=0,
        target_permanent_ids=[nomad.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    _w1g2_bolt(game, 1, nomad)
    _w1g2_bolt(game, 1, nomad)
    assert _w1g2_counters(nomad) == 0
    _w1g2_bolt(game, 1, nomad)

    assert game.is_on_battlefield(nomad)
    assert nomad.damage_marked == 0
    assert (nomad.effective_power, nomad.effective_toughness) == (3, 3)
    assert "Phantom Nomad prevented 3 damage (no +1/+1 counter to remove)" in game.log


def test_w1g2_unpreventable_damage_is_dealt_and_still_costs_a_counter(
    set_pool, catalog_by_name,
):
    """"If damage that would be dealt to this creature can't be prevented, the
    damage is dealt and a +1/+1 counter is removed from this creature."
    (2022-12-08; CR 615.12.) Flaring Pain first, then a bolt: the Tiger takes
    the three, loses a counter for it, and dies at 2/1."""
    game = _w1g2_table(set_pool, catalog_by_name)
    tiger = _w1g2_put(game, 0, "Phantom Tiger")
    game.players[1].hand.append(game._w1g2_card("Flaring Pain"))
    assert game.cast_from_hand(1, "Flaring Pain").supported
    _w1g2_resolve_stack(game)

    _w1g2_bolt(game, 1, tiger)

    assert not game.is_on_battlefield(tiger)
    assert "Phantom Tiger" in [c.name for c in game.players[0].graveyard]
    assert any(
        "3 damage to Phantom Tiger can't be prevented (removed a +1/+1 counter)"
        in line for line in game.log
    )
    assert "Lightning Bolt dealt 3 damage to Phantom Tiger" in game.log


def test_w1g2_phantom_centaur_takes_protection_first_by_default(
    set_pool, catalog_by_name,
):
    """"If this card is going to take damage from a black source, you can
    choose to apply Protection from Black's damage prevention ability prior to
    applying this card's built-in ability. This means you don't have to remove
    a counter." (Phantom Centaur, 2004-10-04.) Pestilence is a black source; a
    seat nobody asks takes protection first (CR 616.1e's default) and keeps
    its counters, while the green Phantom beside it pays."""
    game = _w1g2_table(set_pool, catalog_by_name)
    centaur = _w1g2_put(game, 0, "Phantom Centaur")
    tiger = _w1g2_put(game, 0, "Phantom Tiger")
    pestilence = _w1g2_put(game, 1, "Pestilence")
    result = game.activate_permanent_ability(1, "Pestilence")
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    game._settle()

    assert game.is_on_battlefield(pestilence)
    assert _w1g2_counters(centaur) == 3, "protection prevented it; no counter"
    assert _w1g2_counters(tiger) == 1
    assert game.players[0].life == 19 and game.players[1].life == 19


def test_w1g2_phantom_centaurs_controller_may_choose_the_counter_instead(
    set_pool, catalog_by_name,
):
    """The same contention put to a seat that is asked (CR 616.1e), on the
    road that asks: Phantom Centaur blocks a black attacker (protection from
    black stops it being *blocked by* black creatures, not blocking them).
    Protection and the Phantom's own prevention both apply to the Zombies'
    damage; choosing the Phantom's spends a counter protection would have
    saved. Both answers are legal; the point is that the question is asked and
    the answer honoured."""
    game = _w1g2_table(set_pool, catalog_by_name, interactive={0})
    centaur = _w1g2_put(game, 0, "Phantom Centaur")
    zombies = _w1g2_put(game, 1, "Scathe Zombies")
    _w1g2_declare_attack(game, 1, blocks={0: 0})
    game.advance_combat_phase()
    game.resolve_all_combat_damage(1)
    choice = game.pending_choice_of("effect_order")
    assert choice is not None and choice.player_index == 0
    labels = [str(option) for option in choice.data["options"]]
    assert len(labels) == 2
    pick = next(i for i, label in enumerate(labels) if "remove a counter" in label)
    assert game.resolve_pending_choice("effect_order", 0, option_index=pick)
    game._settle()

    assert _w1g2_counters(centaur) == 2
    assert centaur.damage_marked == 0
    assert not game.is_on_battlefield(zombies), "the Centaur's 5 killed it"


def test_w1g2_phantom_nishoba_gains_life_for_the_damage_it_deals(
    set_pool, catalog_by_name,
):
    """"Whenever this creature deals damage, you gain that much life." Seven
    counters on a 0/0 trampler: unblocked, it deals 7 and its controller gains
    7 — the trigger reads the damage dealt, whichever player took it."""
    game = _w1g2_table(set_pool, catalog_by_name)
    nishoba = _w1g2_put(game, 0, "Phantom Nishoba")
    assert (nishoba.effective_power, nishoba.effective_toughness) == (7, 7)
    _w1g2_declare_attack(game, 0)
    game.advance_combat_phase()
    ok, why = game.resolve_all_combat_damage(0)
    assert ok, why
    _w1g2_resolve_stack(game)

    assert game.players[1].life == 13
    assert game.players[0].life == 27


def test_w1g2_phantom_nantuko_taps_to_grow_back(set_pool, catalog_by_name):
    """"{T}: Put a +1/+1 counter on this creature." The counter the shield
    spends is the counter the Nantuko makes."""
    game = _w1g2_table(set_pool, catalog_by_name)
    nantuko = _w1g2_put(game, 0, "Phantom Nantuko")
    _w1g2_bolt(game, 1, nantuko)
    assert _w1g2_counters(nantuko) == 1
    result = game.activate_permanent_ability(0, "Phantom Nantuko")
    assert result.supported, result.details
    _w1g2_resolve_stack(game)

    assert nantuko.tapped
    assert _w1g2_counters(nantuko) == 2


def test_w1g2_a_phantom_that_loses_its_abilities_has_no_shield(
    set_pool, catalog_by_name,
):
    """The shield is read off the effective card (CR 613 layer 6): a Phantom
    under Humble ("loses all abilities and has base power and toughness 0/1")
    is a 2/3 with two counters, and a bolt is damage marked like any other."""
    game = _w1g2_table(set_pool, catalog_by_name)
    nomad = _w1g2_put(game, 0, "Phantom Nomad")
    _w1g2_bolt(game, 1, nomad, name="Humble")
    assert (nomad.effective_power, nomad.effective_toughness) == (2, 3)
    _w1g2_bolt(game, 1, nomad)

    assert not game.is_on_battlefield(nomad)
    assert _w1g2_counters(nomad) == 2, "no shield, so no counter was spent"

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
