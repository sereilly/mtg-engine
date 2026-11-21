"""Betrayers of Kamigawa creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# Damage: redirection, prevention and per-player damage (CR 614.9, 615).
# Each test places the card, activates it through the engine's own entry
# point, deals the damage it is about and reads the board after `settle`.

import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle

_W1G5_SEATS = [
    _w1g5_pytest.param(set(), id="nobody-asked"),
    _w1g5_pytest.param({0, 1}, id="interactive"),
]


def _w1g5_table(set_pool, interactive=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G5Game(players=[
        _W1G5PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g5_settle(game)
    return game


def _w1g5_put(game, card, seat=0):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g5_activate(game, permanent, seat=0, **announce):
    result = game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **announce,
    )
    assert result.supported, (result, game.log[-6:])
    _w1g5_settle(game)
    return result


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_opal_eye_takes_the_next_damage_of_the_chosen_source(set_pool, interactive):
    """"{T}: The next time a source of your choice would deal damage this
    turn, that damage is dealt to Opal-Eye instead." The chosen Prodigal
    Sorcerer pings Opal-Eye's controller: the point lands on Opal-Eye and the
    player loses nothing (CR 614.9). The redirect is one instance — the
    second ping is dealt as aimed — and an unchosen source is never moved."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, interactive)
    opal = _w1g5_put(game, bok["Opal-Eye, Konda's Yojimbo"])
    sorcerer = _w1g5_put(game, lea["Prodigal Sorcerer"], seat=1)
    other = _w1g5_put(game, lea["Prodigal Sorcerer"], seat=1)
    _w1g5_activate(game, opal, ability_index=0,
                   target_permanent_ids=[sorcerer.permanent_id])
    assert opal.tapped
    # The other Sorcerer — the same card, a different object — is not the
    # source chosen (CR 609.7a names one object).
    _w1g5_activate(game, other, seat=1, target_player_index=0)
    assert game.players[0].life == 19 and opal.damage_marked == 0, game.log
    _w1g5_activate(game, sorcerer, seat=1, target_player_index=0)
    assert game.players[0].life == 19 and opal.damage_marked == 1, game.log
    assert any("is dealt to Opal-Eye" in line for line in game.log), game.log
    sorcerer.tapped = False
    _w1g5_activate(game, sorcerer, seat=1, target_player_index=0)
    assert game.players[0].life == 18 and opal.damage_marked == 1, game.log


def test_w1g5_opal_eye_gone_before_the_damage_moves_nothing(set_pool):
    """CR 614.9: a redirect whose new recipient has left the battlefield does
    nothing — the damage is dealt to its original recipient."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool)
    opal = _w1g5_put(game, bok["Opal-Eye, Konda's Yojimbo"])
    sorcerer = _w1g5_put(game, lea["Prodigal Sorcerer"], seat=1)
    _w1g5_activate(game, opal, ability_index=0,
                   target_permanent_ids=[sorcerer.permanent_id])
    game.sacrifice_permanent(opal)
    _w1g5_settle(game)
    _w1g5_activate(game, sorcerer, seat=1, target_player_index=0)
    assert game.players[0].life == 19, game.log


def test_w1g5_opal_eye_prevents_the_next_1_damage_to_itself(set_pool):
    """"{1}{W}: Prevent the next 1 damage that would be dealt to Opal-Eye
    this turn." Two activations shield two points; a Lightning Bolt's three
    leaves 1 marked."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, hand=[lea["Lightning Bolt"]])
    opal = _w1g5_put(game, bok["Opal-Eye, Konda's Yojimbo"])
    _w1g5_activate(game, opal, ability_index=1)
    _w1g5_activate(game, opal, ability_index=1)
    assert not opal.tapped
    result = game.cast_from_hand(0, "Lightning Bolt",
                                 target_permanent_ids=[opal.permanent_id])
    assert result.supported, result.details
    _w1g5_settle(game)
    assert opal.damage_marked == 1 and game.is_on_battlefield(opal), game.log


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_kitsune_palliator_shields_every_creature_and_player_once(
    set_pool, interactive,
):
    """"{T}: Prevent the next 1 damage that would be dealt to each creature
    and each player this turn." One shield on each creature and each player
    as it resolves: Pestilence's first activation is prevented everywhere,
    but a creature that entered afterwards has none (ruling 2005-02-01), and
    the second activation is dealt to everyone."""
    bok, lea, ed2 = set_pool("BOK"), set_pool("LEA"), set_pool("2ED")
    game = _w1g5_table(set_pool, interactive)
    palliator = _w1g5_put(game, bok["Kitsune Palliator"])
    bears = _w1g5_put(game, lea["Grizzly Bears"])
    pestilence = _w1g5_put(game, ed2["Pestilence"], seat=1)
    giant = _w1g5_put(game, lea["Hill Giant"], seat=1)
    _w1g5_activate(game, palliator)
    assert palliator.tapped
    late = _w1g5_put(game, lea["Grizzly Bears"], seat=1)
    _w1g5_activate(game, pestilence, seat=1)
    assert [p.life for p in game.players] == [20, 20], game.log
    assert [c.damage_marked for c in (palliator, bears, giant, late)] == [0, 0, 0, 1]
    _w1g5_activate(game, pestilence, seat=1)
    assert [p.life for p in game.players] == [19, 19], game.log
    assert [c.damage_marked for c in (palliator, bears, giant)] == [1, 1, 1]


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_heartless_hidetsugu_halves_each_life_total_rounded_down(
    set_pool, interactive,
):
    """"{T}: Heartless Hidetsugu deals damage to each player equal to half
    that player's life total, rounded down." Each seat's own total: 15 takes
    7 (rounded down) and 20 takes 10; at 1 life half is 0, and a seat dealt
    0 is dealt no damage (CR 120.8)."""
    bok = set_pool("BOK")
    game = _w1g5_table(set_pool, interactive)
    hidetsugu = _w1g5_put(game, bok["Heartless Hidetsugu"])
    game.players[1].life = 15
    _w1g5_activate(game, hidetsugu)
    assert [p.life for p in game.players] == [10, 8], game.log
    assert "Heartless Hidetsugu dealt 7 damage to P1" in game.log
    hidetsugu.tapped = False
    game.players[0].life = 1
    _w1g5_activate(game, hidetsugu)
    assert [p.life for p in game.players] == [1, 4], game.log


# The damage family's cards supported on arrival, each given a game.


def test_w1g5_split_tail_miko_shields_two_points_of_a_bolt(set_pool):
    """"{W}, {T}: Prevent the next 2 damage that would be dealt to any target
    this turn." On the Bears, a Lightning Bolt marks 1."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, opponent_hand=[lea["Lightning Bolt"]])
    miko = _w1g5_put(game, bok["Split-Tail Miko"])
    bears = _w1g5_put(game, lea["Grizzly Bears"])
    _w1g5_activate(game, miko, target_permanent_ids=[bears.permanent_id])
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_settle(game)
    assert bears.damage_marked == 1 and game.is_on_battlefield(bears), game.log


def test_w1g5_kami_of_false_hope_fogs_the_combat(set_pool):
    """"Sacrifice this creature: Prevent all combat damage that would be dealt
    this turn." Sacrificed after an attack is declared, the attacker deals
    nothing."""
    from tests.helpers import declare_attack, drive_combat

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool)
    kami = _w1g5_put(game, bok["Kami of False Hope"])
    _w1g5_put(game, lea["Hill Giant"], seat=1)
    declare_attack(game, 1)
    _w1g5_activate(game, kami)
    drive_combat(game)
    assert game.players[0].life == 20 and not game.is_on_battlefield(kami), game.log


def test_w1g5_damage_triggers_kami_of_the_honored_dead_and_shinka_gatekeeper(set_pool):
    """"Whenever this creature is dealt damage, you gain that much life."
    (Kami of the Honored Dead) and "Whenever this creature is dealt damage, it
    deals that much damage to you." (Shinka Gatekeeper.) A Bolt at each: the
    Kami's controller gains 3, the Gatekeeper's loses 3 — after it died, from
    the last it knew (CR 603.10)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, opponent_hand=[lea["Lightning Bolt"]] * 2)
    kami = _w1g5_put(game, bok["Kami of the Honored Dead"])
    gatekeeper = _w1g5_put(game, bok["Shinka Gatekeeper"])
    for victim in (kami, gatekeeper):
        assert game.cast_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[victim.permanent_id],
        ).supported
        _w1g5_settle(game)
    assert game.players[0].life == 20 + 3 - 3, game.log
    assert kami.damage_marked == 3 and not game.is_on_battlefield(gatekeeper)


def test_w1g5_frostling_and_takenos_cavalry_ping_creatures(set_pool):
    """"Sacrifice this creature: It deals 1 damage to target creature."
    (Frostling) kills a Llanowar Elves; "{T}: This creature deals 1 damage to
    target attacking or blocking Spirit." (Takeno's Cavalry) is refused at a
    Spirit that is not in combat and kills one that attacks."""
    from tests.helpers import declare_attack

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool)
    frostling = _w1g5_put(game, bok["Frostling"])
    elves = _w1g5_put(game, lea["Llanowar Elves"], seat=1)
    _w1g5_activate(game, frostling, target_permanent_ids=[elves.permanent_id])
    assert not game.is_on_battlefield(elves) and not game.is_on_battlefield(frostling)
    cavalry = _w1g5_put(game, bok["Takeno's Cavalry"])
    spirit = _w1g5_put(game, bok["Frostling"], seat=1)
    refused = game.activate_permanent_ability(
        0, cavalry.card.name, permanent_index=game.battlefield_index_of(cavalry),
        target_permanent_ids=[spirit.permanent_id],
    )
    assert not refused.supported and not cavalry.tapped
    declare_attack(game, 1)
    _w1g5_activate(game, cavalry, target_permanent_ids=[spirit.permanent_id])
    assert not game.is_on_battlefield(spirit), game.log


def test_w1g5_ronin_cliffrider_pings_each_defending_creature(set_pool):
    """"Whenever this creature attacks, you may have it deal 1 damage to each
    creature defending player controls." The Elves die, the Bears keep 1,
    and the attacker's own creature is untouched."""
    from tests.helpers import declare_attack, drive_combat

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool)
    _w1g5_put(game, bok["Ronin Cliffrider"])
    elves = _w1g5_put(game, lea["Llanowar Elves"], seat=1)
    bears = _w1g5_put(game, lea["Grizzly Bears"], seat=1)
    declare_attack(game, 0)
    drive_combat(game)
    assert not game.is_on_battlefield(elves) and bears.damage_marked == 1, game.log
    assert game.players[1].life == 18, game.log

# ==== end w1g5 ======================================================
