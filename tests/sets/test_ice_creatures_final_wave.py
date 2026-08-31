"""Ice Age (ICE) creature cards — the final wave.

ICE is a *measured* set, mid-implementation: cards land here with the round
that buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool
resolves through ``set_pool("ICE")`` even though the set is not shipped —
reading a card file is not shipping it. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

Rounds 1–41, the serial half, are in ``test_ice_creatures_early_rounds.py``:
the file passed the 2,600-line guard and README's next axis after the printed
type is a round boundary. Sections here are named for the wave and group that
bought them (``W<wave>G<group>``) rather than for a round, because the work
ran in parallel worktrees from that point on.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.


The file passed the 2,600-line guard twice. tests/sets/README.md's axis after
the printed type is a round boundary, and for this set that is a *wave*
boundary: the serial rounds 1-41 are in ``test_ice_creatures_early_rounds.py``,
waves 1-2 in ``test_ice_creatures.py``, and the final wave here.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.control import change_control
from engine.auras import attach_aura
from engine.cumulative_upkeep import cumulative_upkeep_cost
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from engine.pt import add_pt_modifier
from tests.helpers import _nosick

# --- W3G1: granted abilities in quotes ---
def _shaman_game(pool):
    """Bone Shaman for seat 0, a regenerating Bear for seat 1."""
    shaman = _nosick(Permanent(card=pool["Bone Shaman"]))
    victim = _nosick(Permanent(card=pool["Balduvian Bears"]))
    victim.regeneration_shield = True
    p1 = PlayerState(name="P1", battlefield=[shaman], life=20)
    p2 = PlayerState(name="P2", battlefield=[victim], life=20)
    game = Game(players=[p1, p2])
    game._settle()
    return game, shaman, victim


def _activate_shaman(game):
    game.players[0].mana_pool["B"] = 1
    result = game.activate_permanent_ability(0, "Bone Shaman")
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return result


def test_bone_shaman_grants_itself_the_no_regeneration_rider(set_pool):
    """"{B}: Until end of turn, this creature gains "Creatures dealt damage by
    this creature this turn can't be regenerated this turn.""

    A grant of a whole printed sentence (CR 113.3), and the sentence is a
    *static* one the damage seam reads off the damager — so the assertion is
    that a shielded creature Bone Shaman damages dies anyway (CR 701.19c).
    """
    pool = set_pool("ICE")
    game, shaman, victim = _shaman_game(pool)

    assert _activate_shaman(game).supported
    game._mark_damage_on_permanent(victim, 2, source=shaman)
    game.check_state_based_actions()

    assert victim not in list(game.controlled_by(game.players[1]))
    assert [card.name for card in game.players[1].graveyard] == ["Balduvian Bears"]


def test_bone_shaman_leaves_regeneration_alone_before_it_is_activated(set_pool):
    """The shield is the control: without the grant the same damage is survived,
    so the test above is measuring the granted ability and not the damage."""
    pool = set_pool("ICE")
    game, shaman, victim = _shaman_game(pool)

    game._mark_damage_on_permanent(victim, 2, source=shaman)
    game.check_state_based_actions()

    assert victim in list(game.controlled_by(game.players[1]))
    assert not victim.regeneration_shield


def test_bone_shaman_stops_denying_regeneration_when_the_grant_expires(set_pool):
    """"Until end of turn" — a duration dropped from a quoted grant would be a
    permanent ability nobody printed."""
    pool = set_pool("ICE")
    game, shaman, victim = _shaman_game(pool)
    _activate_shaman(game)
    game.resolve_cleanup_step(0)
    game._settle()
    # CR 514.2 ends the shield with the turn as well, so it is re-armed here:
    # what this test is about is the *grant* expiring, and a victim with nothing
    # to regenerate with would pass it whether or not the grant did.
    victim.regeneration_shield = True

    game._mark_damage_on_permanent(victim, 2, source=shaman)
    game.check_state_based_actions()

    assert victim in list(game.controlled_by(game.players[1]))


def _musician_game(pool, lands: int = 0):
    """Musician for seat 0, a Bear (and *lands* Forests) for seat 1."""
    musician = _nosick(Permanent(card=pool["Musician"]))
    bear = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[musician], life=20)
    p2 = PlayerState(
        name="P2",
        battlefield=[bear] + [Permanent(card=pool["Forest"]) for _ in range(lands)],
        life=20,
    )
    game = Game(players=[p1, p2])
    game._settle()
    return game, musician, bear


def _play_musician(game, musician):
    musician.tapped = False
    result = game.activate_permanent_ability(
        0, "Musician", target_player_index=1, target_permanent_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return result


def test_musician_grants_the_quoted_upkeep_ability_with_the_counter(set_pool):
    """"{T}: Put a music counter on target creature. If it doesn't have "At the
    beginning of your upkeep, destroy this creature unless you pay {1} for each
    music counter on it," it gains that ability."

    The grant and the counter are one activation, and the granted ability
    counts the counters this ability is putting there.
    """
    pool = set_pool("ICE")
    game, musician, bear = _musician_game(pool)

    assert _play_musician(game, musician).supported
    assert counters_on(bear, "music") == 1
    assert "destroy this creature unless you pay {1}" in (
        bear.effective_card.oracle_text
    )


def test_musician_does_not_grant_the_ability_a_second_time(set_pool):
    """"**If it doesn't have** …" — CR 611.2c lets a permanent hold one ability
    twice, so a dropped condition here would be two upkeep triggers asking for
    the same counters."""
    pool = set_pool("ICE")
    game, musician, bear = _musician_game(pool)

    _play_musician(game, musician)
    _play_musician(game, musician)

    assert counters_on(bear, "music") == 2
    text = bear.effective_card.oracle_text
    assert text.count("destroy this creature unless you pay {1}") == 1


def test_musicians_granted_upkeep_destroys_a_creature_that_cannot_pay(set_pool):
    """The grant is only done when the granted ability *fires*: two counters is
    {2}, and one Forest does not cover it."""
    pool = set_pool("ICE")
    game, musician, bear = _musician_game(pool, lands=1)
    _play_musician(game, musician)
    _play_musician(game, musician)

    game.start_turn(1)
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()

    assert bear not in list(game.controlled_by(game.players[1]))
    assert [card.name for card in game.players[1].graveyard] == ["Balduvian Bears"]


def test_musicians_granted_upkeep_scales_with_the_music_counters(set_pool):
    """"{1} **for each music counter on it**" — a multiplier dropped here would
    charge {1} for a creature carrying five counters."""
    pool = set_pool("ICE")
    game, musician, bear = _musician_game(pool, lands=2)
    _play_musician(game, musician)
    _play_musician(game, musician)

    game.start_turn(1)
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()

    assert bear in list(game.controlled_by(game.players[1]))
    assert not any(
        perm.card.name == "Forest" and not perm.tapped
        for perm in game.controlled_by(game.players[1])
    )


def _shaman_text_game(pool, target_name: str, *, opponents: bool = False):
    """Balduvian Shaman for seat 0, *target_name* for whichever seat is named."""
    shaman = _nosick(Permanent(card=pool["Balduvian Shaman"]))
    target = Permanent(card=pool[target_name])
    p1 = PlayerState(
        name="P1", battlefield=[shaman] + ([] if opponents else [target]), life=20
    )
    p2 = PlayerState(name="P2", battlefield=[target] if opponents else [], life=20)
    game = Game(players=[p1, p2])
    game._settle()
    return game, target


def _activate_balduvian_shaman(game, *, seat: int, index: int, swap=("B", "U")):
    result = game.activate_permanent_ability(
        0, "Balduvian Shaman",
        target_player_index=seat, target_permanent_index=index,
        old_color=swap[0], mana_color=swap[1],
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return result


def test_balduvian_shaman_swaps_a_color_word_and_grants_cumulative_upkeep(set_pool):
    """"{T}: Change the text of target white enchantment you control that
    doesn't have cumulative upkeep by replacing all instances of one color word
    with another. … That enchantment gains "Cumulative upkeep {1}.""

    CR 612.1's text change in layer 3 and CR 113.3's quoted grant in layer 6,
    on one target chosen once — so both halves are asserted off the
    enchantment's *effective* text, which is where each lands.
    """
    pool = set_pool("ICE")
    game, reclamation = _shaman_text_game(pool, "Reclamation")

    assert _activate_balduvian_shaman(game, seat=0, index=1).supported

    text = reclamation.effective_card.oracle_text
    assert text.startswith("Blue creatures can't attack")
    assert "black" not in text.lower()
    assert "Cumulative upkeep {1}" in text


def test_balduvian_shamans_grant_costs_the_enchantment_at_the_next_upkeep(set_pool):
    """The grant is only done when the granted ability fires: with no mana for
    the age counter's {1}, CR 702.24a sacrifices the enchantment."""
    pool = set_pool("ICE")
    game, reclamation = _shaman_text_game(pool, "Reclamation")
    _activate_balduvian_shaman(game, seat=0, index=1)

    game.resolve_upkeep(0)

    assert counters_on(reclamation, "age") == 1
    assert reclamation not in list(game.controlled_by(game.players[0]))
    assert [card.name for card in game.players[0].graveyard] == ["Reclamation"]


def test_balduvian_shaman_refuses_an_enchantment_that_already_has_the_keyword(set_pool):
    """"…**that doesn't have cumulative upkeep**". A dropped narrowing here is
    an ability that works more often than the card allows — and it would stack
    a second escalating cost on a permanent that already pays one."""
    pool = set_pool("ICE")
    game, cold_snap = _shaman_text_game(pool, "Cold Snap")

    result = _activate_balduvian_shaman(game, seat=0, index=1)

    assert not result.supported
    assert "Cumulative upkeep {1}" not in cold_snap.effective_card.oracle_text


def test_balduvian_shaman_refuses_an_enchantment_you_do_not_control(set_pool):
    """"…**you control**" — the other half of the printed narrowing, and the
    half CR 109.5 measures against the ability's controller."""
    pool = set_pool("ICE")
    game, theirs = _shaman_text_game(pool, "Reclamation", opponents=True)

    result = _activate_balduvian_shaman(game, seat=1, index=0)

    assert not result.supported
    assert theirs.effective_card.oracle_text.startswith("Black creatures can't attack")
# --- end W3G1 ---


# --- W3G4: coin flips, ante, noted mana ---
def _supplicant_board(set_pool, fodder_name, boost=0):
    """Freyalise Supplicant and one creature to feed it, on an untapped board."""
    pool = set_pool("ICE")
    supplicant = _nosick(Permanent(card=pool["Freyalise Supplicant"]))
    fodder = _nosick(Permanent(card=pool[fodder_name]))
    p0 = PlayerState(name="P0", battlefield=[supplicant, fodder], life=20)
    game = Game(players=[p0, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    if boost:
        add_pt_modifier(fodder, boost, 0)
    game._settle()
    return game, p0, game.players[1], supplicant, fodder


def test_freyalise_supplicant_deals_half_the_eaten_creatures_power(set_pool):
    """"{T}, Sacrifice a red or white creature: This creature deals damage to
    any target equal to **half the sacrificed creature's power, rounded down**."

    Two gaps in two layers. `parse_equal_to` already reads "the sacrificed
    creature's <characteristic>", but it hands a leading "half" to the quantity
    parser before it gets there — so a fraction *of* a payment channel had no
    reader at all. And the damage lowering had no branch for the channel, which
    the resolution-time evaluator answered only for a mana value.

    Balduvian Barbarians' 3 is the rounding: half of an odd power is one less,
    not one more.
    """
    game, _p0, p1, supplicant, _fodder = _supplicant_board(
        set_pool, "Balduvian Barbarians"
    )

    game.queue_permanent_ability(
        0, "Freyalise Supplicant",
        target_player_index=1, permanent_index=0, cost_permanent_index=1,
    )
    game._settle()

    assert p1.life == 19
    assert supplicant.tapped


def test_the_supplicant_halves_the_power_the_creature_last_had(set_pool):
    """CR 608.2h: the cost is paid before the ability is on the stack, so the
    number is last-known information — the creature's **effective** power,
    including a pump, not the printed one on its card. A reader off the card
    would call a boosted 3/2 a 3 and deal one damage less."""
    game, _p0, p1, _supplicant, _fodder = _supplicant_board(
        set_pool, "Balduvian Barbarians", boost=1
    )

    game.queue_permanent_ability(
        0, "Freyalise Supplicant",
        target_player_index=1, permanent_index=0, cost_permanent_index=1,
    )
    game._settle()

    assert p1.life == 18


def test_the_supplicant_will_not_eat_a_creature_of_the_wrong_color(set_pool):
    """"Sacrifice a **red or white** creature" is a cost, and a cost that cannot
    be paid is an ability that cannot be activated (CR 601.2h). Balduvian Bears
    is green, so nothing is sacrificed and nothing is dealt."""
    pool = set_pool("ICE")
    supplicant = _nosick(Permanent(card=pool["Freyalise Supplicant"]))
    bears = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p0 = PlayerState(name="P0", battlefield=[supplicant, bears], life=20)
    game = Game(players=[p0, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._settle()

    result = game.queue_permanent_ability(
        0, "Freyalise Supplicant",
        target_player_index=1, permanent_index=0, cost_permanent_index=1,
    )
    game._settle()

    assert not result.supported
    assert game.players[1].life == 20
    assert bears in p0.battlefield
    assert not supplicant.tapped
# --- end W3G4 ---


# --- W3G5: death triggers, control, computed characteristics ---
def _w3g5_settle(game):
    """Resolve everything the last action put on the stack, then settle."""
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()


# Infernal Denizen — "At the beginning of your upkeep, sacrifice two Swamps. If
# you can't, tap this creature, and an opponent may gain control of a creature
# you control of their choice for as long as this creature remains on the
# battlefield."


def _w3g5_denizen(set_pool, swamps: int):
    pool = set_pool("ICE")
    denizen = Permanent(card=pool["Infernal Denizen"])
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(
        name="P0",
        battlefield=[denizen, bears]
        + [Permanent(card=pool["Swamp"]) for _ in range(swamps)],
    )
    p1 = PlayerState(name="P1")
    game = Game(players=[p0, p1])
    game.active_player_index = 0
    return game, denizen, bears, p0, p1


def test_infernal_denizen_pays_its_upkeep_with_two_swamps(set_pool):
    game, denizen, bears, p0, _p1 = _w3g5_denizen(set_pool, swamps=2)

    game.resolve_upkeep(0)
    _w3g5_settle(game)

    assert not [p for p in game.controlled_by(0) if p.card.name == "Swamp"]
    assert not denizen.tapped, "the cost was paid, so the penalty never applies"
    assert game.controller_index_of(bears) == 0


def test_infernal_denizen_with_one_swamp_sacrifices_neither(set_pool):
    """CR 701.17b: the printed count is indivisible. A player with one of the
    two Swamps cannot sacrifice two, so nothing is sacrificed and the "if you
    can't" branch is what happens instead."""
    game, denizen, _bears, _p0, _p1 = _w3g5_denizen(set_pool, swamps=1)

    game.resolve_upkeep(0)
    _w3g5_settle(game)

    assert [p for p in game.controlled_by(0) if p.card.name == "Swamp"], (
        "one Swamp is not two, so it stays"
    )
    assert denizen.tapped


def test_infernal_denizen_hands_a_creature_to_the_opponent_who_picks_it(set_pool):
    """"An opponent may gain control of a creature you control of their choice."
    The pick and the offer are one decision made by one seat, and the seat that
    makes it is the seat that keeps the creature — not the Denizen's."""
    game, _denizen, _bears, _p0, _p1 = _w3g5_denizen(set_pool, swamps=0)

    game.resolve_upkeep(0)
    _w3g5_settle(game)

    stolen = list(game.controlled_by(1))
    assert stolen, "the opponent took something"
    assert all(game.owner_index_of(perm) == 0 for perm in stolen), (
        "control moved; ownership did not (CR 108.3)"
    )


def test_infernal_denizen_leaving_gives_the_creature_back(set_pool):
    """"…for as long as this creature remains on the battlefield" (CR 611.2b).
    The contribution is monitored, so the sweep ends it the moment the Denizen
    goes."""
    game, denizen, _bears, _p0, _p1 = _w3g5_denizen(set_pool, swamps=0)
    game.resolve_upkeep(0)
    _w3g5_settle(game)
    taken = [perm for perm in game.controlled_by(1) if perm is not denizen]

    game.remove_from_battlefield(denizen)
    game._settle()

    for perm in taken:
        assert game.controller_index_of(perm) == 0


# Lost Order of Jarkeld — "As this creature enters, choose an opponent." /
# "Lost Order of Jarkeld's power and toughness are each equal to 1 plus the
# number of creatures the chosen player controls."


def _w3g5_jarkeld(set_pool, opponent_creatures: int):
    pool = set_pool("ICE")
    p0 = PlayerState(name="P0", hand=[pool["Lost Order of Jarkeld"]])
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=pool["Balduvian Bears"]) for _ in range(opponent_creatures)
        ],
    )
    game = Game(players=[p0, p1])
    game.active_player_index = 0
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Lost Order of Jarkeld")
    _w3g5_settle(game)
    knight = next(
        perm for perm in game.controlled_by(0)
        if perm.card.name == "Lost Order of Jarkeld"
    )
    return game, knight, p0, p1


def test_lost_order_of_jarkeld_counts_the_chosen_players_creatures(set_pool):
    """CR 604.3: a characteristic-defining P/T, recomputed on every read. The
    printed 1+* is 1 plus what the seat chosen on entry controls."""
    game, knight, _p0, p1 = _w3g5_jarkeld(set_pool, opponent_creatures=2)

    assert knight.metadata["chosen_player_index"] == 1
    assert (knight.effective_power, knight.effective_toughness) == (3, 3)

    p1.battlefield.append(Permanent(card=set_pool("ICE")["Balduvian Bears"]))
    game._settle()
    assert (knight.effective_power, knight.effective_toughness) == (4, 4)


def test_lost_order_of_jarkeld_counts_what_the_chosen_player_controls(set_pool):
    """"Controls", not "owns": a creature the chosen player has lost control of
    is not one they control, so the count goes down when it is stolen."""
    game, knight, _p0, p1 = _w3g5_jarkeld(set_pool, opponent_creatures=2)
    assert knight.effective_power == 3

    change_control(p1.battlefield[0], 0, source=knight)
    game._sync_control()
    game._settle()

    assert (knight.effective_power, knight.effective_toughness) == (2, 2)


# Mistfolk — "{U}: Counter target spell that targets this creature."


def _w3g5_mistfolk(set_pool, aim_at_mistfolk: bool):
    pool = set_pool("ICE")
    mistfolk = Permanent(card=pool["Mistfolk"])
    theirs = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[mistfolk])
    p1 = PlayerState(name="P1", battlefield=[theirs], hand=[pool["Flare"]])
    game = Game(players=[p0, p1])
    game.start_turn(1)
    queued = game.queue_from_hand(
        1, "Flare",
        target_player_index=0 if aim_at_mistfolk else 1,
        target_permanent_index=0,
    )
    assert queued.supported, queued.details
    p0.mana_pool.update({"U": 1})
    return game, mistfolk, p0, p1


def test_mistfolk_counters_a_spell_aimed_at_itself(set_pool):
    game, _mistfolk, _p0, p1 = _w3g5_mistfolk(set_pool, aim_at_mistfolk=True)

    result = game.queue_permanent_ability(0, "Mistfolk", target_stack_index=0)
    game.resolve_stack()
    game._settle()

    assert result.supported, result.details
    assert not game.stack
    assert [card.name for card in p1.graveyard] == ["Flare"]


def test_mistfolk_refuses_to_activate_against_a_spell_aimed_elsewhere(set_pool):
    """CR 602.2b: the target is chosen as the ability is activated, so a stack
    with nothing it may counter refuses *before* the {U} is spent. The picker
    and the resolution ask one predicate, so they cannot disagree about which
    spell qualifies."""
    game, _mistfolk, p0, _p1 = _w3g5_mistfolk(set_pool, aim_at_mistfolk=False)

    result = game.queue_permanent_ability(0, "Mistfolk", target_stack_index=0)

    assert not result.supported
    assert p0.mana_pool.get("U", 0) == 1, "nothing was paid"


# Seraph — "Whenever a creature dealt damage by this creature this turn dies,
# put that card onto the battlefield under your control at the beginning of the
# next end step. Sacrifice the creature when you lose control of this creature."


def _w3g5_seraph(set_pool):
    pool = set_pool("ICE")
    seraph = Permanent(card=pool["Seraph"])
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[seraph])
    p1 = PlayerState(name="P1", battlefield=[bears])
    game = Game(players=[p0, p1])
    game.active_player_index = 0
    game._mark_damage_on_permanent(bears, 2, source=seraph)
    game._settle()
    _w3g5_settle(game)
    return game, seraph, p0, p1


def test_seraph_returns_what_it_killed_at_the_next_end_step(set_pool):
    """The trigger arms a delayed ability (CR 603.7) that remembers the dead
    card (CR 608.2h) — the end step it fires on records nothing itself."""
    game, _seraph, _p0, p1 = _w3g5_seraph(set_pool)

    assert [card.name for card in p1.graveyard] == ["Balduvian Bears"]
    assert [d.event for d in game.delayed_triggers] == ["next_end_step"]

    game.resolve_end_step(0)
    _w3g5_settle(game)

    assert "Balduvian Bears" in [p.card.name for p in game.controlled_by(0)]
    assert not p1.graveyard


def test_seraph_leaving_sacrifices_what_it_returned(set_pool):
    """"Sacrifice the creature when you lose control of this creature." The card
    goes to its **owner's** graveyard: control moved, ownership never did."""
    game, seraph, _p0, p1 = _w3g5_seraph(set_pool)
    game.resolve_end_step(0)
    _w3g5_settle(game)

    game.remove_from_battlefield(seraph)
    game._settle()

    assert "Balduvian Bears" not in [p.card.name for p in game.controlled_by(0)]
    assert [card.name for card in p1.graveyard] == ["Balduvian Bears"]


# Krovikan Vampire — Seraph's sentence with the trigger the other way round.


def _w3g5_krovikan(set_pool, kill: bool = True):
    pool = set_pool("ICE")
    vampire = Permanent(card=pool["Krovikan Vampire"])
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[vampire])
    p1 = PlayerState(name="P1", battlefield=[bears])
    game = Game(players=[p0, p1])
    game.active_player_index = 0
    if kill:
        game._mark_damage_on_permanent(bears, 2, source=vampire)
        game._settle()
        _w3g5_settle(game)
    return game, vampire, p0, p1


def test_krovikan_vampire_returns_what_it_killed_at_the_end_step(set_pool):
    """The intervening-if reads a ledger, because by the end step the creature
    is gone and the damage record it carried has gone with it."""
    game, vampire, _p0, p1 = _w3g5_krovikan(set_pool)

    assert [
        card.name
        for card in vampire.metadata["damaged_creatures_that_died_this_turn"]
    ] == ["Balduvian Bears"]

    game.resolve_end_step(0)
    _w3g5_settle(game)

    assert "Balduvian Bears" in [p.card.name for p in game.controlled_by(0)]
    assert not p1.graveyard


def test_krovikan_vampire_does_nothing_when_nothing_it_damaged_died(set_pool):
    """CR 603.4: a gated trigger whose condition is false does not trigger at
    all. The game-wide "a creature died" counter cannot answer this question,
    which is why the condition is its own."""
    game, _vampire, _p0, _p1 = _w3g5_krovikan(set_pool, kill=False)

    game.resolve_end_step(0)
    _w3g5_settle(game)

    assert [p.card.name for p in game.controlled_by(0)] == ["Krovikan Vampire"]


def test_krovikan_vampire_changing_hands_sacrifices_what_it_returned(set_pool):
    """"When **you** lose control of this creature" — the Vampire being stolen
    is exactly the case, and nothing has changed zones."""
    game, vampire, _p0, p1 = _w3g5_krovikan(set_pool)
    game.resolve_end_step(0)
    _w3g5_settle(game)
    assert "Balduvian Bears" in [p.card.name for p in game.controlled_by(0)]

    change_control(vampire, 1, source=object())
    game._sync_control()
    game._settle()

    assert "Balduvian Bears" not in [p.card.name for p in game.controlled_by(0)]
    assert [card.name for card in p1.graveyard] == ["Balduvian Bears"]


# Shyft — "At the beginning of your upkeep, you may have this creature become
# the color or colors of your choice. (This effect lasts indefinitely.)"


def _w3g5_shyft(set_pool, interactive=(), opponent=("Abyssal Specter",)):
    pool = set_pool("ICE")
    shyft = Permanent(card=pool["Shyft"])
    p0 = PlayerState(name="P0", battlefield=[shyft])
    p1 = PlayerState(
        name="P1", battlefield=[Permanent(card=pool[name]) for name in opponent]
    )
    game = Game(players=[p0, p1])
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    game.resolve_upkeep(0)
    for _ in range(6):
        if game.stack and not game.pending_choices:
            game.resolve_top_of_stack()
            continue
        break
    game._settle()
    return game, shyft


def test_shyft_takes_a_deterministic_colour_for_a_seat_nobody_asks(set_pool):
    """The stated default: the colour the opponents hold least of among
    nontoken permanents — a creature sharing a colour with the board is the one
    every colour-hoser reaches. Ties break on the printed WUBRG order, so a
    seeded run reproduces."""
    game, shyft = _w3g5_shyft(set_pool)

    game.auto_resolve_pending_choices()
    game._settle()

    assert not game.pending_choices
    assert game._effective_colors(shyft) == {"W"}, "the opponent's board is black"


def test_shyft_lets_an_interactive_seat_name_two_colours(set_pool):
    """CR 105.2: "the color **or colors**" offers a set, and a two-coloured
    object is one object of two colours. Layer 5 has taken a tuple since Dream
    Coat; what did not exist was a way for a player to name one."""
    game, shyft = _w3g5_shyft(set_pool, interactive=(0,))

    assert game.confirm_optional_pay(0, card_name="Shyft", accept=True)
    game._settle()
    assert [c.kind for c in game.pending_choices] == ["color_set_choice"]

    assert game.confirm_color_set_choice(0, ["W", "R"])
    game._settle()

    assert game._effective_colors(shyft) == {"W", "R"}


def test_shyft_declined_stays_the_colour_it_was_printed(set_pool):
    """"You **may**" — a declined offer changes nothing, and the creature is
    still the blue it was printed."""
    game, shyft = _w3g5_shyft(set_pool, interactive=(0,))

    assert game.confirm_optional_pay(0, card_name="Shyft", accept=False)
    game._settle()

    assert not game.pending_choices
    assert game._effective_colors(shyft) == {"U"}
# --- end W3G5 ---


# --- W3G2: combat control and attack requirements ---
def _w3g2_board(set_pool, *names, opponent=()):
    """A two-seat game with *names* under seat 0 and *opponent* under seat 1,
    every permanent able to act."""
    pool = set_pool("ICE")
    mine = [Permanent(card=pool[name]) for name in names]
    theirs = [Permanent(card=pool[name]) for name in opponent]
    game = Game(players=[
        PlayerState(name="P1", battlefield=mine, life=20),
        PlayerState(name="P2", battlefield=theirs, life=20),
    ])
    game.enforce_mana_costs = False
    game._settle()
    for perm in mine + theirs:
        _nosick(perm)
    return game, mine, theirs


def _w3g2_settle(game):
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()


def test_w3g2_goblin_ski_patrol_is_supported(set_pool):
    """Three sentences and every one of them had to land: an indefinite pump
    and keyword grant (CR 611.2b, no duration printed), the delayed sacrifice,
    and a lifetime activation cap."""
    program = compile_card_oracle(set_pool("ICE")["Goblin Ski Patrol"])

    assert program.supported


def test_w3g2_ski_patrol_needs_a_snow_mountain_to_activate(set_pool):
    """The refusing half. An ordinary Mountain is a Mountain and is not snow,
    so the clause is unmet and nothing happens — which is the direction an
    unenforced "Activate only if" gets wrong."""
    game, (patrol, _mountain), _ = _w3g2_board(
        set_pool, "Goblin Ski Patrol", "Mountain",
    )

    result = game.activate_permanent_ability(0, "Goblin Ski Patrol")

    assert not result.supported
    assert (patrol.effective_power, patrol.effective_toughness) == (1, 1)
    assert not patrol.has_keyword("flying")


def test_w3g2_ski_patrol_pumps_and_flies_off_a_snow_mountain(set_pool):
    """The permitting half, so the restriction is a gate rather than a wall."""
    game, (patrol, _snow), _ = _w3g2_board(
        set_pool, "Goblin Ski Patrol", "Snow-Covered Mountain",
    )

    result = game.activate_permanent_ability(0, "Goblin Ski Patrol")
    _w3g2_settle(game)

    assert result.supported
    assert (patrol.effective_power, patrol.effective_toughness) == (3, 1)
    assert patrol.has_keyword("flying")


def test_w3g2_ski_patrol_activates_once_and_never_again(set_pool):
    """"Activate only **once**" — not once each turn. The tally the engine
    already kept was turn-scoped, so a cap read off it would come back every
    untap step: the ability working more often than the card allows."""
    game, (patrol, _snow), _ = _w3g2_board(
        set_pool, "Goblin Ski Patrol", "Snow-Covered Mountain",
    )

    assert game.activate_permanent_ability(0, "Goblin Ski Patrol").supported
    _w3g2_settle(game)
    again = game.activate_permanent_ability(0, "Goblin Ski Patrol")

    assert not again.supported
    # …and still refused a turn later, which is the whole difference from
    # Dream Coat's clause.
    game.turn += 2
    assert not game.activate_permanent_ability(0, "Goblin Ski Patrol").supported
    assert patrol.effective_power == 3


def test_w3g2_ski_patrol_is_sacrificed_at_the_next_end_step(set_pool):
    """"Its controller sacrifices it at the beginning of the next end step."
    The pump lasting indefinitely is what the card prints; the creature not
    lasting is what makes the two readings agree at the table."""
    game, (patrol, _snow), _ = _w3g2_board(
        set_pool, "Goblin Ski Patrol", "Snow-Covered Mountain",
    )

    game.activate_permanent_ability(0, "Goblin Ski Patrol")
    _w3g2_settle(game)
    assert patrol.metadata["sacrifice_at_next_end_step"] is True

    game.resolve_end_step(0)

    assert "Goblin Ski Patrol" not in [
        perm.card.name for perm in game.controlled_by(game.players[0])
    ]


def test_w3g2_barbarian_guides_is_supported(set_pool):
    """The one gap was the last sentence: "Return **that creature**" is the
    same referent "Return **it**" already named, and the production read only
    the pronoun."""
    program = compile_card_oracle(set_pool("ICE")["Barbarian Guides"])

    assert program.supported


def test_w3g2_barbarian_guides_returns_its_target_at_the_end_step(set_pool):
    """The bounce is aimed at the creature the ability targeted, not at the
    Guides — which is what "that creature" says and what the source-referent
    reading would have got wrong."""
    game, (guides, bears), _ = _w3g2_board(
        set_pool, "Barbarian Guides", "Balduvian Bears",
    )

    result = game.activate_permanent_ability(
        0, "Barbarian Guides",
        target_player_index=0,
        permanent_index=game.battlefield_index_of(guides),
        target_permanent_index=game.battlefield_index_of(bears),
    )
    _w3g2_settle(game)

    assert result.supported
    assert bears.has_keyword("snow cavewalk")
    assert bears.metadata.get("bounce_at_next_end_step") is True
    assert not guides.metadata.get("bounce_at_next_end_step")

    game.resolve_end_step(0)

    assert "Balduvian Bears" in [c.name for c in game.players[0].hand]
    assert "Barbarian Guides" in [
        perm.card.name for perm in game.controlled_by(game.players[0])
    ]
def test_w3g2_chaos_lord_is_supported(set_pool):
    """Two lines, both required: the upkeep hand-over and the attack
    permission that exists because of it."""
    program = compile_card_oracle(set_pool("ICE")["Chaos Lord"])

    assert program.supported
    assert [
        (t.condition.kind, t.instruction.kind) for t in program.triggered_abilities
    ] == [("upkeep_self", "if_then")]


def _w3g2_chaos_upkeep(game):
    game.resolve_upkeep(game.active_player_index)
    _w3g2_settle(game)


def test_w3g2_chaos_lord_changes_hands_only_on_an_even_board(set_pool):
    """"…if the number of permanents is even." A parity, not a threshold —
    which is why the comparison had to be answered before the evaluator's
    absent-number default, whose reading is "at least one"."""
    game, (lord,), _ = _w3g2_board(set_pool, "Chaos Lord")
    game.start_turn(0)

    _w3g2_chaos_upkeep(game)
    assert game.controller_index_of(lord) == 0, "one permanent is an odd board"

    game.players[1].battlefield.append(Permanent(card=set_pool("ICE")["Balduvian Bears"]))
    game._settle()
    game.turn += 1
    game.start_turn(0)
    _w3g2_chaos_upkeep(game)

    assert game.controller_index_of(lord) == 1


def test_w3g2_chaos_lord_can_attack_after_changing_hands(set_pool):
    """The reason the permission is printed at all. CR 302.6 would stop the new
    controller attacking with a creature that came under their control this
    turn, and the hand-over happens in their upkeep — so without this the
    creature could never attack for anybody it was given to."""
    game, (lord,), _ = _w3g2_board(set_pool, "Chaos Lord")
    # A control change re-stamps the sickness record, which is exactly the
    # state this permission has to see through.
    lord.metadata["summoning_sickness_turn"] = game.turn

    assert game._is_summoning_sick(lord), "the control change made it sick"
    assert not game.entered_this_turn(lord)
    assert game.can_attack(lord, 1)


def test_w3g2_chaos_lord_still_cannot_attack_the_turn_it_arrives(set_pool):
    """The printed exception, and the half that only a separate record can
    answer: reading "entered this turn" off the summoning-sickness stamp would
    say yes because of the control change the card exists to cause, and the
    permission would never once apply."""
    from engine.enter_effects import ENTERED_BATTLEFIELD_TURN

    game, (lord,), _ = _w3g2_board(set_pool, "Chaos Lord")
    lord.metadata[ENTERED_BATTLEFIELD_TURN] = game.turn
    lord.metadata["summoning_sickness_turn"] = game.turn

    assert not game.can_attack(lord, 1)


def test_w3g2_the_permission_is_chaos_lords_and_not_every_creatures(set_pool):
    """The control: an ordinary summoning-sick creature beside it still cannot
    attack, so the permission is the printed line rather than a hole the
    change opened in CR 302.6."""
    game, (lord, bears), _ = _w3g2_board(
        set_pool, "Chaos Lord", "Balduvian Bears",
    )
    bears.metadata["summoning_sickness_turn"] = game.turn

    assert not game.can_attack(bears, 1)


def test_w3g2_a_permanent_records_the_turn_it_entered(set_pool):
    """The record itself, through the entry path rather than by hand: it is a
    plain fact about arrival and nothing rewrites it, which is what tells it
    apart from the summoning-sickness stamp beside it."""
    from engine.enter_effects import ENTERED_BATTLEFIELD_TURN

    game, (lord,), _ = _w3g2_board(set_pool, "Chaos Lord")
    arriving = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    game.players[0].battlefield.append(arriving)
    game._initialize_permanent_state(arriving, 0, 0)

    entered_at = arriving.metadata[ENTERED_BATTLEFIELD_TURN]
    assert entered_at == game.turn
    assert game.entered_this_turn(arriving)

    # The whole reason for a second record: a control change re-stamps the
    # sickness one and does not touch this.
    game.take_control(arriving, 1, source=lord)

    assert arriving.metadata["summoning_sickness_turn"] == game.turn
    assert arriving.metadata[ENTERED_BATTLEFIELD_TURN] == entered_at

    game.turn += 1

    assert not game.entered_this_turn(arriving)
# --- end W3G2 ---


# --- W4G2: blocker control ---
def _jarkeld_board(pool, second_attacker="Tor Giant", second_blocker="Brown Ouphe",
                   blocks=None):
    """Seat 0 attacks with two creatures; seat 1 blocks and controls Jarkeld.

    ``blocks`` is keyed by the **blocker's** slot, as ``declare_blockers``
    takes it; the default puts one blocker on each attacker, which is the board
    General Jarkeld's sentence is about.
    """
    attackers = [
        _nosick(Permanent(card=pool["Balduvian Bears"])),
        _nosick(Permanent(card=pool[second_attacker])),
    ]
    blockers = [
        _nosick(Permanent(card=pool["Balduvian Barbarians"])),
        _nosick(Permanent(card=pool[second_blocker])),
    ]
    jarkeld = _nosick(Permanent(card=pool["General Jarkeld"]))
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(attackers), life=20),
        PlayerState(name="P2", battlefield=[*blockers, jarkeld], life=20),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], 1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    ok, msg = game.declare_blockers(1, {0: 0, 1: 1} if blocks is None else blocks)
    assert ok, msg
    return game, attackers, blockers, jarkeld


def _swap(game, attackers, targets=(0, 1)):
    return game.activate_permanent_ability(
        1, "General Jarkeld", permanent_index=2,
        target_player_index=0,
        target_permanent_index=list(targets),
        target_permanent_ids=[attackers[i].permanent_id for i in targets],
    )


def test_general_jarkeld_compiles_as_one_paragraph(set_pool):
    """Two printed sentences and one effect: "those creatures" and "the other"
    are only supplied by the first, and the first on its own would announce two
    targets and do nothing with them."""
    program = compile_card_oracle(set_pool("ICE")["General Jarkeld"])

    assert program.supported
    ability = program.activated_abilities[0]
    assert ability.instruction.kind == "reassign_blockers_between_attackers"
    targets = ability.instruction.payload["targets"]
    assert targets["count"] == 2
    # Both printed narrowings survive to the payload. A phrase that parsed and
    # was dropped would let the ability move blockers off a creature the
    # sentence never named.
    assert targets["filter"]["attacking_only"] is True
    assert targets["filter"]["blocked_only"] is True


def test_general_jarkeld_trades_the_blockers_of_two_attackers(set_pool):
    """The mirror of Sorrow's Path: that card swaps what two blockers block,
    this one swaps who blocks two attackers."""
    pool = set_pool("ICE")
    game, attackers, blockers, _jarkeld = _jarkeld_board(pool)
    assert game.combat_blockers[1] == {0: [0], 1: [1]}

    result = _swap(game, attackers)

    assert result.supported, result.details
    assert game.combat_blockers[1] == {0: [1], 1: [0]}
    assert blockers[0].blocking_attacker_index == 1
    assert blockers[1].blocking_attacker_index == 0
    # CR 509.1h: nothing was removed from combat, so neither attacker ever
    # stopped being blocked.
    assert attackers[0].blocked and attackers[1].blocked


def test_general_jarkeld_refuses_a_trade_neither_blocker_could_have_made(set_pool):
    """"If each of those creatures could be blocked by all creatures that the
    other is blocked by" — one condition over the pair, asked of the same gate a
    real declaration passes. A ground creature cannot block the flier, so
    nothing moves."""
    pool = set_pool("ICE")
    game, attackers, blockers, _jarkeld = _jarkeld_board(
        pool, second_attacker="Silver Erne", second_blocker="Silver Erne",
    )
    before = {slot: list(atks) for slot, atks in game.combat_blockers[1].items()}

    result = _swap(game, attackers)

    assert result.supported, result.details
    assert game.combat_blockers[1] == before
    assert any("could not be blocked by each other's blockers" in line
               for line in game.log)


def test_general_jarkeld_cannot_name_an_unblocked_attacker(set_pool):
    """CR 602.2b/601.2c: "target **blocked** attacking creature" is checked
    before the cost is paid, so an unblocked attacker is not a legal choice and
    the tap is never spent."""
    pool = set_pool("ICE")
    game, attackers, _blockers, jarkeld = _jarkeld_board(pool, blocks={0: 0})
    assert not attackers[1].blocked

    result = _swap(game, attackers)

    assert not result.supported
    assert "no valid target" in result.details
    assert not jarkeld.tapped


def test_general_jarkeld_activates_only_in_the_declare_blockers_step(set_pool):
    """CR 602.5's printed restriction, read by the same table every other
    "Activate only during …" clause is."""
    pool = set_pool("ICE")
    game, attackers, _blockers, _jarkeld = _jarkeld_board(pool)
    game._set_phase_and_step("combat", "combat_damage")

    result = _swap(game, attackers)

    assert not result.supported
    assert "declare blockers step" in result.details
# --- end W4G2 ---
