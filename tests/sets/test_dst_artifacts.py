"""Darksteel artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Equipment: the granted "{T}, Unattach ~:" abilities, Whispersilk Cloak's
# reversed compound, Shield of Kaldra's named indestructible, and the drive
# list (the Swords, Skullclamp, Specter's Shroud, Nemesis Mask). Every test
# equips through the real equip ability (CR 702.6a) and reads the board after
# `settle`.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.equipment import equipped_creature as _w1g2_equipped
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import declare_attack as _w1g2_declare_attack
from tests.helpers import drive_combat as _w1g2_drive_combat
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, interactive=(), enforce=False, life=20):
    """Two seats on seat 0's first main phase, libraries to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", life=life, library=[island] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat, *, sick=False):
    """*card* onto *seat*'s battlefield through the entry seam."""
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_equip(game, seat, equipment, creature):
    """Activate *equipment*'s equip ability at *creature* and resolve it."""
    result = game.activate_permanent_ability(
        seat,
        equipment.card.name,
        permanent_index=game.battlefield_index_of(equipment),
        target_permanent_ids=[creature.permanent_id],
    )
    assert result.supported, (result, game.log[-4:])
    _w1g2_settle(game)
    assert _w1g2_equipped(equipment) is creature, game.log[-4:]
    return result


def test_w1g2_whispersilk_cloak_unblockable_and_shroud(set_pool):
    """"Equipped creature can't be blocked and has shroud." Both halves of the
    one line: no blocker may be declared (CR 509.1b), and no spell may target
    the creature — its controller's included (CR 702.18a). Moved off, the
    creature is blockable and targetable again."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    cloak = _w1g2_put(game, dst["Whispersilk Cloak"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    wall = _w1g2_put(game, lea["Wall of Stone"], 1)
    _w1g2_equip(game, 0, cloak, bears)
    assert bears.has_keyword("shroud")

    game.players[0].hand = [lea["Lightning Bolt"]]
    refused = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported
    assert bears in game.controlled_by(0)

    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(bears)], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(1, {game.battlefield_index_of(wall): 0})
    assert not ok
    ok, why = game.declare_blockers(1, {})
    assert ok, why
    _w1g2_drive_combat(game)
    assert game.players[1].life == 18

    # Off the creature, both halves end (CR 611.3b).
    game._set_phase_and_step("postcombat_main", "main")
    ogre = _w1g2_put(game, lea["Gray Ogre"], 0)
    _w1g2_equip(game, 0, cloak, ogre)
    assert not bears.has_keyword("shroud")
    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert bears not in game.controlled_by(0)


def test_w1g2_shield_of_kaldra_makes_the_named_equipment_indestructible(set_pool):
    """"Equipment named Sword of Kaldra, Shield of Kaldra, and Helm of Kaldra
    have indestructible." Every name on the list, whoever controls it (the
    sentence names no controller), and nothing off it; and "Equipped creature
    has indestructible" on the creature it equips."""
    dst, mrd, lea = set_pool("DST"), set_pool("MRD"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    shield = _w1g2_put(game, dst["Shield of Kaldra"], 0)
    sword = _w1g2_put(game, mrd["Sword of Kaldra"], 1)
    scimitar = _w1g2_put(game, mrd["Leonin Scimitar"], 1)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    assert shield.has_keyword("indestructible")
    assert sword.has_keyword("indestructible")
    assert not scimitar.has_keyword("indestructible")
    assert not bears.has_keyword("indestructible")

    game.players[0].hand = [lea["Shatter"], lea["Shatter"], lea["Shatter"]]
    for victim in (sword, shield, scimitar):
        result = game.cast_from_hand(0, "Shatter", target_permanent_ids=[victim.permanent_id])
        assert result.supported, result
        _w1g2_settle(game)
    assert sword in game.controlled_by(1)
    assert shield in game.controlled_by(0)
    assert scimitar not in game.controlled_by(1)

    _w1g2_equip(game, 0, shield, bears)
    assert bears.has_keyword("indestructible")
    game.players[0].hand = [lea["Terror"]]
    result = game.cast_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert bears in game.controlled_by(0)

    # The Shield leaving takes the Sword's indestructible with it (CR 611.3b).
    game.remove_from_battlefield(shield)
    _w1g2_settle(game)
    assert not sword.has_keyword("indestructible")


def _w1g2_granted(game, host):
    """The host's compiled activated abilities (its effective card's)."""
    from engine.oracle import compile_card_oracle

    return compile_card_oracle(host.effective_card).activated_abilities


def _w1g2_use(game, seat, host, *, queue=False, **kwargs):
    """Activate *host*'s granted ability (its only one)."""
    activate = game.queue_permanent_ability if queue else game.activate_permanent_ability
    return activate(
        seat, host.card.name, permanent_index=game.battlefield_index_of(host),
        ability_index=0, **kwargs,
    )


def test_w1g2_heartseeker_grants_destroy_and_unattaches_as_its_cost(set_pool):
    """'Equipped creature gets +2/+1 and has "{T}, Unattach Heartseeker:
    Destroy target creature."' The ability is the creature's (2004-12-01: the
    equipped creature's controller activates it, and it can target a creature
    with protection from artifacts); "Unattach Heartseeker" moves the
    Equipment off and leaves it on the battlefield (CR 701.3d) as the cost is
    paid, so the +2/+1 is gone before the ability resolves — and the ability,
    once activated, resolves however the Equipment moves after (CR 113.7a)."""
    from engine.targeting import derive_activation_spec

    dst, mrd, lea = set_pool("DST"), set_pool("MRD"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    heart = _w1g2_put(game, dst["Heartseeker"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    ogre = _w1g2_put(game, lea["Gray Ogre"], 0)
    chosen = _w1g2_put(game, mrd["Tel-Jilad Chosen"], 1)
    assert _w1g2_granted(game, bears) == ()
    _w1g2_equip(game, 0, heart, bears)
    assert (bears.effective_power, bears.effective_toughness) == (4, 3)
    (granted,) = _w1g2_granted(game, bears)
    assert granted.cost.requires_tap
    assert granted.cost.unattach_granter_id == heart.permanent_id
    assert derive_activation_spec(granted) == {"kind": "creature"}

    result = _w1g2_use(game, 0, bears, queue=True, target_permanent_ids=[chosen.permanent_id])
    assert result.supported, result
    # The cost is paid: tapped, unattached, the bonus gone, Heartseeker still here.
    assert bears.tapped
    assert _w1g2_equipped(heart) is None
    assert heart in game.controlled_by(0)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert _w1g2_granted(game, bears) == ()
    # In response the Heartseeker goes onto the Ogre; the ability still resolves.
    from engine.equipment import attach_equipment

    attach_equipment(game, heart, ogre)
    _w1g2_settle(game)
    assert chosen not in game.controlled_by(1)
    assert "Grizzly Bears destroyed Tel-Jilad Chosen" in game.log
    assert (ogre.effective_power, ogre.effective_toughness) == (4, 3)


def test_w1g2_heartseeker_on_an_artifact_creature_cannot_target_protection(set_pool):
    """The ruling's parenthesis: an *artifact* creature's ability is a source
    a creature with protection from artifacts can't be targeted by
    (CR 702.16b) — refused before any cost is paid."""
    dst, mrd, lea = set_pool("DST"), set_pool("MRD"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    heart = _w1g2_put(game, dst["Heartseeker"], 0)
    golem = _w1g2_put(game, lea["Obsianus Golem"], 0)
    chosen = _w1g2_put(game, mrd["Tel-Jilad Chosen"], 1)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 1)
    _w1g2_equip(game, 0, heart, golem)
    refused = _w1g2_use(game, 0, golem, target_permanent_ids=[chosen.permanent_id])
    assert not refused.supported
    assert _w1g2_equipped(heart) is golem and not golem.tapped
    result = _w1g2_use(game, 0, golem, target_permanent_ids=[bears.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert bears not in game.controlled_by(1)
    assert _w1g2_equipped(heart) is None


def test_w1g2_leonin_bola_taps_a_creature_whoever_controls_the_bola(set_pool):
    """'Equipped creature has "{T}, Unattach Leonin Bola: Tap target
    creature."' 2004-12-01: "It doesn't matter who controls Leonin Bola" —
    the opponent takes the Bola, the Bears still has the ability, and its cost
    unattaches the opponent's Equipment. A summoning-sick host cannot pay {T}
    (CR 602.5a)."""
    from engine.control import change_control

    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    bola = _w1g2_put(game, dst["Leonin Bola"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    fresh = _w1g2_put(game, lea["Gray Ogre"], 0, sick=True)
    angel = _w1g2_put(game, lea["Serra Angel"], 1)
    _w1g2_equip(game, 0, bola, fresh)
    refused = _w1g2_use(game, 0, fresh, target_permanent_ids=[angel.permanent_id])
    assert not refused.supported
    assert _w1g2_equipped(bola) is fresh and not angel.tapped

    _w1g2_equip(game, 0, bola, bears)
    change_control(bola, 1, source=angel)
    game._sync_control()
    _w1g2_settle(game)
    assert bola in game.controlled_by(1) and _w1g2_equipped(bola) is bears
    result = _w1g2_use(game, 0, bears, target_permanent_ids=[angel.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert angel.tapped and bears.tapped
    assert _w1g2_equipped(bola) is None and bola in game.controlled_by(1)
    assert _w1g2_granted(game, bears) == ()


def test_w1g2_surestrike_trident_first_strike_and_power_to_a_player(set_pool):
    """'Equipped creature has first strike and "{T}, Unattach Surestrike
    Trident: This creature deals damage equal to its power to target player or
    planeswalker."' Both halves of the one line; the damage is the creature's
    power as the ability resolves, and the creature is its source."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    trident = _w1g2_put(game, dst["Surestrike Trident"], 0)
    ogre = _w1g2_put(game, lea["Gray Ogre"], 0)
    _w1g2_equip(game, 0, trident, ogre)
    assert ogre.has_keyword("first strike")
    result = _w1g2_use(game, 0, ogre, target_player_index=1)
    assert result.supported, result
    _w1g2_settle(game)
    assert game.players[1].life == 18
    assert not ogre.has_keyword("first strike")
    assert _w1g2_equipped(trident) is None


# --- the drive list: Darksteel Equipment supported on arrival -------------


def _w1g2_attack(game, attacker, *, blocks=None):
    """*attacker* attacks seat 1 alone; *blocks* maps blockers to it."""
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    slot = game.battlefield_index_of(attacker)
    ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    return slot


def test_w1g2_skullclamp_kills_a_one_toughness_creature_and_draws_two(set_pool):
    """"Equipped creature gets +1/-1. Whenever equipped creature dies, draw two
    cards." On a 1/1 the -1 kills it (CR 704.5f) and the trigger draws two;
    on a 2/2 it is a 3/1."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    clamp = _w1g2_put(game, dst["Skullclamp"], 0)
    elves = _w1g2_put(game, lea["Llanowar Elves"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    hand = len(game.players[0].hand)
    game.activate_permanent_ability(
        0, clamp.card.name, permanent_index=game.battlefield_index_of(clamp),
        target_permanent_ids=[elves.permanent_id],
    )
    _w1g2_settle(game)
    assert elves not in game.controlled_by(0)
    assert len(game.players[0].hand) == hand + 2
    _w1g2_equip(game, 0, clamp, bears)
    assert (bears.effective_power, bears.effective_toughness) == (3, 1)


def test_w1g2_specters_shroud_discards_on_combat_damage(set_pool):
    """"Equipped creature gets +1/+0. Whenever equipped creature deals combat
    damage to a player, that player discards a card." """
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    shroud = _w1g2_put(game, dst["Specter's Shroud"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    game.players[1].hand = [lea["Island"]]
    _w1g2_equip(game, 0, shroud, bears)
    _w1g2_declare_attack(game, 0)
    _w1g2_drive_combat(game)
    assert game.players[1].life == 17
    assert game.players[1].hand == [] and [c.name for c in game.players[1].graveyard] == ["Island"]


def test_w1g2_the_swords_protection_and_combat_triggers(set_pool):
    """Sword of Fire and Ice: +2/+2, protection from red and from blue (a Bolt
    and an Unsummon can't target it, a Terror can), and on combat damage 2
    damage to any target and a card. Sword of Light and Shadow: protection
    from white and from black, 3 life and a creature card back."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    fire = _w1g2_put(game, dst["Sword of Fire and Ice"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    _w1g2_equip(game, 0, fire, bears)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)
    game.players[1].hand = [lea["Lightning Bolt"], lea["Unsummon"]]
    game.active_player_index = 1
    for name in ("Lightning Bolt", "Unsummon"):
        assert not game.cast_from_hand(1, name, target_permanent_ids=[bears.permanent_id]).supported
    hand = len(game.players[0].hand)
    _w1g2_declare_attack(game, 0)
    _w1g2_drive_combat(game)
    assert game.players[1].life == 20 - 4 - 2
    assert len(game.players[0].hand) == hand + 1

    game = _w1g2_table(set_pool)
    light = _w1g2_put(game, dst["Sword of Light and Shadow"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    game.players[0].graveyard = [lea["Hill Giant"]]
    _w1g2_equip(game, 0, light, bears)
    game.players[1].hand = [lea["Terror"], lea["Swords to Plowshares"]]
    game.active_player_index = 1
    for name in ("Terror", "Swords to Plowshares"):
        assert not game.cast_from_hand(1, name, target_permanent_ids=[bears.permanent_id]).supported
    _w1g2_declare_attack(game, 0)
    _w1g2_drive_combat(game)
    assert game.players[1].life == 16
    assert game.players[0].life == 23
    assert [c.name for c in game.players[0].hand][-1:] == ["Hill Giant"]


def test_w1g2_vulshok_morningstar_and_nemesis_mask(set_pool):
    """Vulshok Morningstar: +2/+2. Nemesis Mask: "All creatures able to block
    equipped creature do so" — a declaration leaving an able blocker out is
    illegal (CR 509.1c), the one with both is accepted."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 0)
    mask = _w1g2_put(game, dst["Nemesis Mask"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    wall = _w1g2_put(game, lea["Wall of Stone"], 1)
    giant = _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_equip(game, 0, star, bears)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)
    _w1g2_equip(game, 0, mask, bears)
    slot = _w1g2_attack(game, bears)
    ok, _ = game.declare_blockers(1, {})
    assert not ok
    ok, _ = game.declare_blockers(1, {game.battlefield_index_of(wall): slot})
    assert not ok
    ok, why = game.declare_blockers(1, {
        game.battlefield_index_of(wall): slot, game.battlefield_index_of(giant): slot,
    })
    assert ok, why

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
