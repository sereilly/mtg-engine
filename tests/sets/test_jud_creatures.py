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
#
# Abilities that function from a graveyard (CR 113.6b): the five Incarnations
# ("As long as this card is in your graveyard and you control a <basic>,
# creatures you control have <keyword>.") and Genesis's upkeep trigger. Each
# Incarnation is driven through the rule its keyword is about — haste through
# the attack declaration, trample and first strike through combat damage,
# swampwalk and flying through the block declaration — because a granted word
# nothing reads is a card that compiles and does nothing.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import declare_attack as _w1g1_declare_attack
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_table(set_pool, *, interactive=(), enforce=False):
    """Two seats on seat 0's first main phase, libraries to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G1Game(players=[
        _W1G1PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g1_put(game, card, seat, *, sick=False):
    """*card* onto *seat*'s battlefield through the entry seam."""
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g1_bury(game, seat, card):
    """*card* into *seat*'s graveyard through the zone seam, and the board's
    statics recomputed as every resolution does."""
    assert game.put_card_into_graveyard(seat, card)
    game._settle()


def _w1g1_bolt(game, set_pool, seat, permanent):
    """Lightning Bolt *permanent*, cast and resolved through the real path."""
    game.players[seat].hand.append(set_pool("LEA")["Lightning Bolt"])
    cast = game.queue_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[permanent.permanent_id]
    )
    assert cast.supported, game.log[-3:]
    _w1g1_resolve_stack(game)
    # CR 704.3: the lethal damage is a state-based action, checked as a
    # player would next receive priority.
    game._settle()


def _w1g1_can_attack(game, seat, permanent) -> bool:
    """Whether *permanent* may attack the other seat right now — the attack
    legality the declaration asks, which is the reader of haste (CR 302.6)."""
    return bool(game.can_attack(permanent, 1 - seat))


def test_w1g1_anger_dying_gives_its_owners_creatures_haste(set_pool):
    """Anger dies to a Lightning Bolt with a Mountain on its owner's side: from
    then on the owner's freshly cast Grizzly Bears may attack this turn — and
    the opponent's, also fresh, may not."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    anger = _w1g1_put(game, jud["Anger"], 0)
    _w1g1_put(game, lea["Mountain"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0, sick=True)
    theirs = _w1g1_put(game, lea["Grizzly Bears"], 1, sick=True)

    # CR 113.6b: on the battlefield the graveyard ability does nothing.
    assert anger.has_keyword("haste")
    assert not bears.has_keyword("haste")
    assert not _w1g1_can_attack(game, 0, bears)

    _w1g1_bolt(game, set_pool, 0, anger)

    assert "Anger" in [card.name for card in game.players[0].graveyard]
    assert bears.has_keyword("haste")
    assert _w1g1_can_attack(game, 0, bears)
    assert not theirs.has_keyword("haste")
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [
        slot for slot, perm in enumerate(game.players[0].battlefield) if perm is bears
    ], defending_player_index=1)
    assert ok, why


def test_w1g1_anger_counts_only_a_mountain_its_owner_controls(set_pool):
    """"…and **you** control a Mountain": the graveyard's owner (CR 108.4a).
    The opponent's Mountain is not one; gaining one switches the grant on and
    losing the last one switches it off again (CR 611.3a)."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_put(game, lea["Mountain"], 1)
    _w1g1_bury(game, 0, jud["Anger"])
    assert not bears.has_keyword("haste")

    mountain = _w1g1_put(game, lea["Mountain"], 0)
    game._settle()
    assert bears.has_keyword("haste")

    game.sacrifice_permanent(mountain)
    game._settle()
    assert not bears.has_keyword("haste")


@_w1g1_pytest.mark.parametrize("road", ["returned to hand", "exiled"])
def test_w1g1_anger_leaving_its_graveyard_ends_the_grant(set_pool, road):
    """Raise Dead brings it back to hand, Coffin Purge exiles it: either way
    the card is no longer where its ability functions, and the creature loses
    haste on that resolution."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    _w1g1_put(game, lea["Mountain"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_bury(game, 0, jud["Anger"])
    assert bears.has_keyword("haste")

    if road == "returned to hand":
        game.players[0].hand.append(lea["Raise Dead"])
        cast = game.queue_from_hand(0, "Raise Dead")
    else:
        game.players[0].hand.append(set_pool("ODY")["Coffin Purge"])
        cast = game.queue_from_hand(0, "Coffin Purge")
    assert cast.supported, game.log[-3:]
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g1_resolve_stack(game)

    zone = game.players[0].hand if road == "returned to hand" else game.players[0].exile
    assert "Anger" in [card.name for card in zone], game.log[-4:]
    assert "Anger" not in [card.name for card in game.players[0].graveyard]
    assert not bears.has_keyword("haste")


def test_w1g1_two_angers_each_grant_and_one_leaving_leaves_the_other(set_pool):
    """Two copies in one pile are two sources (one ability per card in the
    zone). Exiling the top one leaves the bottom one granting."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    _w1g1_put(game, lea["Mountain"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_bury(game, 0, jud["Anger"])
    _w1g1_bury(game, 0, jud["Anger"])

    game.players[0].graveyard.pop()
    game._settle()
    assert [card.name for card in game.players[0].graveyard] == ["Anger"]
    assert bears.has_keyword("haste")

    game.players[0].graveyard.pop()
    game._settle()
    assert not bears.has_keyword("haste")


def test_w1g1_brawn_gives_trample_and_the_excess_reaches_the_player(set_pool):
    """Brawn in the graveyard with a Forest: a blocked Craw Wurm (6/4) assigns
    lethal damage to the Grizzly Bears blocking it and the other four to the
    defending player (CR 702.19b)."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    _w1g1_put(game, lea["Forest"], 0)
    _w1g1_put(game, lea["Craw Wurm"], 0)
    _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_bury(game, 0, jud["Brawn"])

    _w1g1_declare_attack(game, 0, blocks={0: 1})
    game.advance_combat_phase()
    _w1g1_resolve_stack(game)
    game._settle()

    assert game.players[1].life == 16, game.log[-6:]
    assert "Grizzly Bears" in [card.name for card in game.players[1].graveyard]


def test_w1g1_brawn_with_no_forest_grants_nothing(set_pool):
    """The same fight with the Forest missing: the Wurm is blocked and
    nothing reaches the player."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    _w1g1_put(game, lea["Craw Wurm"], 0)
    _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_bury(game, 0, jud["Brawn"])

    _w1g1_declare_attack(game, 0, blocks={0: 0})
    game.advance_combat_phase()
    _w1g1_resolve_stack(game)
    game._settle()

    assert game.players[1].life == 20, game.log[-6:]


@_w1g1_pytest.mark.parametrize("buried", [True, False])
def test_w1g1_filth_gives_swampwalk_against_a_defender_with_a_swamp(set_pool, buried):
    """Filth in the graveyard with its owner's Swamp: the attacking Grizzly
    Bears has swampwalk, so a defender controlling a Swamp cannot block it
    (CR 702.14c). The same board without Filth there blocks freely, which is
    what says the refusal is the walk's."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_put(game, lea["Swamp"], 0)
    _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_put(game, lea["Swamp"], 1)
    if buried:
        _w1g1_bury(game, 0, jud["Filth"])
    assert bears.has_keyword("swampwalk") is buried

    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0})
    assert ok is not buried, why


def test_w1g1_valor_gives_first_strike_and_the_attacker_survives(set_pool):
    """Valor in the graveyard with a Plains: two Grizzly Bears trade blows,
    and the one with first strike deals its damage first (CR 702.7b) — the
    blocker dies before it can strike back."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    _w1g1_put(game, lea["Plains"], 0)
    mine = _w1g1_put(game, lea["Grizzly Bears"], 0)
    _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_bury(game, 0, jud["Valor"])
    assert mine.has_keyword("first strike")

    _w1g1_declare_attack(game, 0, blocks={0: 1})
    for _ in range(3):
        game.advance_combat_phase()
        _w1g1_resolve_stack(game)
        game._settle()

    assert "Grizzly Bears" in [card.name for card in game.players[1].graveyard]
    assert game.is_on_battlefield(mine), game.log[-6:]
    assert int(mine.metadata.get("damage", 0) or 0) == 0


def test_w1g1_wonder_gives_flying_so_only_reach_blocks(set_pool):
    """Wonder in the graveyard with an Island: the attacking Grizzly Bears
    flies — a Grizzly Bears cannot block it, a Giant Spider (reach) can."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    for blocker, allowed in (("Grizzly Bears", False), ("Giant Spider", True)):
        game = _w1g1_table(set_pool)
        _w1g1_put(game, lea["Grizzly Bears"], 0)
        _w1g1_put(game, lea["Island"], 0)
        _w1g1_put(game, lea[blocker], 1)
        _w1g1_bury(game, 0, jud["Wonder"])

        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, why = game.declare_attackers(0, [0], defending_player_index=1)
        assert ok, why
        game.advance_combat_phase()
        ok, why = game.declare_blockers(1, {0: 0})
        assert ok is allowed, (blocker, why)


# -- Genesis ------------------------------------------------------------------


def _w1g1_genesis_table(set_pool, *, interactive=(), forests=3):
    """Genesis in seat 0's graveyard between a Grizzly Bears and a Forest,
    with *forests* untapped Forests to pay {2}{G} from and costs enforced."""
    lea = set_pool("LEA")
    game = _w1g1_table(set_pool, interactive=interactive, enforce=True)
    lands = [_w1g1_put(game, lea["Forest"], 0) for _ in range(forests)]
    game.players[0].graveyard = [
        lea["Grizzly Bears"], set_pool("JUD")["Genesis"], lea["Forest"],
    ]
    return game, lands


def test_w1g1_genesis_pays_and_returns_a_creature_card_at_its_owners_upkeep(set_pool):
    """"At the beginning of your upkeep, if this creature is in your
    graveyard, you may pay {2}{G}. If you do, return target creature card from
    your graveyard to your hand." The trigger works from the graveyard, names
    its target as it goes on the stack (CR 603.3d) and pays at resolution."""
    game, lands = _w1g1_genesis_table(set_pool)

    game.resolve_upkeep(0)
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]
    assert [card.name for card in game.players[0].graveyard] == ["Genesis", "Forest"]
    assert all(land.tapped for land in lands)
    assert "Genesis: targets Grizzly Bears in P0's graveyard" in game.log


def test_w1g1_genesis_may_target_itself(set_pool):
    """Genesis is a creature card in its owner's graveyard, so the picker
    offers it beside the Grizzly Bears (and not the Forest); named, it
    returns itself."""
    game, lands = _w1g1_genesis_table(set_pool, interactive={0})
    game.resolve_upkeep(0)

    (choice,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert [entry["name"] for entry in choice.data["targets"]] == [
        "Grizzly Bears", "Genesis",
    ]
    assert game.confirm_trigger_target(0, seat=0, graveyard_index=1)
    _w1g1_resolve_stack(game)
    (offer,) = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert offer.data["cost"] == {"G": 1, "generic": 2}
    assert game.confirm_optional_pay(0, "Genesis", accept=True)
    _w1g1_resolve_stack(game)

    assert [card.name for card in game.players[0].hand] == ["Genesis"]
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears", "Forest"]
    assert all(land.tapped for land in lands)


def test_w1g1_genesis_declined_pays_nothing_and_returns_nothing(set_pool):
    game, lands = _w1g1_genesis_table(set_pool, interactive={0})
    game.resolve_upkeep(0)
    assert game.confirm_trigger_target(0, seat=0, graveyard_index=0)
    _w1g1_resolve_stack(game)
    assert game.confirm_optional_pay(0, "Genesis", accept=False)
    _w1g1_resolve_stack(game)

    assert game.players[0].hand == []
    assert [card.name for card in game.players[0].graveyard] == [
        "Grizzly Bears", "Genesis", "Forest",
    ]
    assert not any(land.tapped for land in lands)


def test_w1g1_genesis_leaving_the_graveyard_in_response_stops_the_trigger(set_pool):
    """CR 603.4: the intervening "if this creature is in your graveyard" is
    asked again on resolution. Exiled in response, Genesis asks nothing and
    nothing is paid."""
    game, lands = _w1g1_genesis_table(set_pool, interactive={0})
    game.resolve_upkeep(0)
    assert game.confirm_trigger_target(0, seat=0, graveyard_index=0)
    graveyard = game.players[0].graveyard
    game.players[0].exile.append(graveyard.pop(1))
    _w1g1_resolve_stack(game)

    assert not [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert game.players[0].hand == []
    assert not any(land.tapped for land in lands)


def test_w1g1_genesis_does_nothing_on_an_opponents_upkeep(set_pool):
    """"**your** upkeep": the graveyard owner's."""
    game, lands = _w1g1_genesis_table(set_pool)
    game.resolve_upkeep(1)
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert game.players[0].hand == []
    assert not any(land.tapped for land in lands)

# -- Glory (drive list: supported on arrival) ----------------------------------


def test_w1g1_glory_from_the_graveyard_gives_protection_from_the_colour_named(set_pool):
    """"{2}{W}: Choose a color. Creatures you control gain protection from the
    chosen color until end of turn. Activate only if this card is in your
    graveyard." Activated from the graveyard, the colour is asked as the
    ability resolves (CR 608.2d), and the protection it names stops a
    Lightning Bolt aimed at the creature (CR 702.16b). On the battlefield the
    ability is refused for not functioning there (CR 113.6b)."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g1_table(set_pool, interactive={0})
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    game.players[0].graveyard.append(jud["Glory"])

    assert game.activate_from_graveyard(0, "Glory", ability_index=0).supported
    game.resolve_top_of_stack()
    (owed,) = [c for c in game.pending_choices if c.kind == "color_choice"]
    assert game.confirm_color_choice(0, "R")
    _w1g1_resolve_stack(game)
    game._settle()

    game.players[1].hand.append(lea["Lightning Bolt"])
    bolt = game.queue_from_hand(1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    assert not bolt.supported, bolt.details

    on_board = _w1g1_table(set_pool)
    _w1g1_put(on_board, jud["Glory"], 0)
    refused = on_board.queue_permanent_ability(0, "Glory", ability_index=0)
    assert not refused.supported and "graveyard" in refused.details

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
#
# Cards in a graveyard as targets. Nantuko Tracer's entry trigger targets a
# card in any graveyard and bottoms it into its owner's library (CR 404.1:
# the pile a card is in is its owner's).

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_tracer_game(set_pool, *, interactive, mine=("Swamp",),
                      theirs=("Grizzly Bears", "Terror")):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", hand=[jud["Nantuko Tracer"]],
            graveyard=[lea[name] for name in mine], library=[lea["Forest"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[name] for name in theirs],
            library=[lea["Island"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def test_w1g3_nantuko_tracer_bottoms_an_opponents_card_into_their_library(set_pool):
    game = _w1g3_tracer_game(set_pool, interactive=True)
    assert game.queue_from_hand(0, "Nantuko Tracer").supported
    game.resolve_top_of_stack(pause_for_choices=True)          # the creature

    # CR 603.3d: the target is chosen as the trigger is put on the stack, out
    # of every graveyard (the Tracer's own controller's included).
    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert {(t["seat"], t["name"]) for t in asked.data["targets"]} == {
        (0, "Swamp"), (1, "Grizzly Bears"), (1, "Terror"),
    }
    assert game.confirm_trigger_target(0, seat=1, graveyard_index=1)

    # "You may": asked as it resolves (CR 608.2d).
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)
    _w1g3_resolve(game)

    victim = game.players[1]
    assert [c.name for c in victim.graveyard] == ["Grizzly Bears"]
    assert victim.library[-1].name == "Terror" and len(victim.library) == 6
    assert [c.name for c in game.players[0].graveyard] == ["Swamp"]
    assert len(game.players[0].library) == 5


def test_w1g3_nantuko_tracer_bottoms_its_controllers_own_card_into_their_library(set_pool):
    game = _w1g3_tracer_game(set_pool, interactive=True)
    assert game.queue_from_hand(0, "Nantuko Tracer").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_trigger_target(0, seat=0, graveyard_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g3_resolve(game)

    assert game.players[0].graveyard == []
    assert game.players[0].library[-1].name == "Swamp"
    assert len(game.players[1].library) == 5


def test_w1g3_nantuko_tracer_declined_or_whose_card_left_moves_nothing(set_pool):
    declined = _w1g3_tracer_game(set_pool, interactive=True)
    assert declined.queue_from_hand(0, "Nantuko Tracer").supported
    declined.resolve_top_of_stack(pause_for_choices=True)
    assert declined.confirm_trigger_target(0, seat=1, graveyard_index=0)
    declined.resolve_top_of_stack(pause_for_choices=True)
    assert declined.confirm_optional_pay(0, accept=False)
    _w1g3_resolve(declined)
    assert [c.name for c in declined.players[1].graveyard] == ["Grizzly Bears", "Terror"]
    assert len(declined.players[1].library) == 5

    # CR 608.2b: the named card leaves in response, and the trigger does
    # nothing — it does not bottom the card that slid into its slot.
    left = _w1g3_tracer_game(set_pool, interactive=True)
    assert left.queue_from_hand(0, "Nantuko Tracer").supported
    left.resolve_top_of_stack(pause_for_choices=True)
    assert left.confirm_trigger_target(0, seat=1, graveyard_index=0)
    victim = left.players[1]
    victim.exile.append(victim.graveyard.pop(0))           # the Bears, in response
    _w1g3_resolve(left)
    left.auto_resolve_pending_choices()
    assert [c.name for c in victim.graveyard] == ["Terror"]
    assert len(victim.library) == 5


def test_w1g3_nantuko_tracer_under_an_ai_seat_names_and_bottoms_a_card(set_pool):
    game = _w1g3_tracer_game(set_pool, interactive=False, mine=())
    assert game.queue_from_hand(0, "Nantuko Tracer").supported
    _w1g3_resolve(game)
    game.auto_resolve_pending_choices()

    victim = game.players[1]
    assert len(victim.graveyard) == 1 and len(victim.library) == 6
    assert victim.library[-1].name in ("Grizzly Bears", "Terror")

    # With every graveyard empty the trigger has no target and is removed
    # (CR 603.3d); the creature still resolves.
    empty = _w1g3_tracer_game(set_pool, interactive=False, mine=(), theirs=())
    assert empty.queue_from_hand(0, "Nantuko Tracer").supported
    _w1g3_resolve(empty)
    empty.auto_resolve_pending_choices()
    assert any(p.card.name == "Nantuko Tracer" for p in empty.controlled_by(0))
    assert empty.pending_choices == [] and empty.stack == []


# Selfless Exorcist: the exiled card is the source of the damage (CR 120.2),
# and its power is the one it has in exile — printed, or what its
# characteristic-defining ability says (CR 604.3, 113.6a; ruling 2013-04-15).

from engine.models import Permanent as _w1g3_Permanent


def _w1g3_exorcist_game(set_pool, theirs, *, mine=("Grizzly Bears",)):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    pool = {**lea, **set_pool("ICE"), **jud}
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", graveyard=[pool[name] for name in mine],
            library=[lea["Plains"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[pool[name] for name in theirs],
            library=[lea["Island"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    exorcist = _w1g3_Permanent(card=jud["Selfless Exorcist"])
    game._put_permanent_onto_battlefield(0, exorcist, None)
    exorcist.tapped = False
    exorcist.metadata["summoning_sickness_turn"] = -99
    _w1g3_resolve(game)
    return game, exorcist


def _w1g3_exorcise(game, slot, seat=1):
    result = game.activate_permanent_ability(
        0, "Selfless Exorcist", target_player_index=seat, target_permanent_index=slot,
    )
    assert result.supported, result.details
    _w1g3_resolve(game)


def test_w1g3_selfless_exorcist_offers_creature_cards_in_every_graveyard(set_pool):
    game, _exorcist = _w1g3_exorcist_game(set_pool, ("Swamp", "Hill Giant", "Craw Wurm"))
    spec = game.activation_target_spec(0, 0)
    assert {(t["seat"], t["name"]) for t in spec["valid_targets"]} == {
        (0, "Grizzly Bears"), (1, "Hill Giant"), (1, "Craw Wurm"),
    }
    # A land card is not a creature card, and the announcement says so.
    assert not game.activate_permanent_ability(
        0, "Selfless Exorcist", target_player_index=1, target_permanent_index=0,
    ).supported


def test_w1g3_selfless_exorcist_takes_the_exiled_cards_power_in_damage(set_pool):
    game, exorcist = _w1g3_exorcist_game(set_pool, ("Swamp", "Hill Giant", "Craw Wurm"))
    _w1g3_exorcise(game, 1)                                   # Hill Giant, 3/3

    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]
    assert game.is_on_battlefield(exorcist) and exorcist.damage_marked == 3
    assert "Hill Giant deals 3 damage to Selfless Exorcist" in game.log


def test_w1g3_selfless_exorcist_dies_to_a_bigger_card(set_pool):
    game, exorcist = _w1g3_exorcist_game(set_pool, ("Swamp", "Hill Giant", "Craw Wurm"))
    _w1g3_exorcise(game, 2)                                   # Craw Wurm, 6/4

    assert [c.name for c in game.players[1].exile] == ["Craw Wurm"]
    assert not game.is_on_battlefield(exorcist)
    assert "Selfless Exorcist" in [c.name for c in game.players[0].graveyard]


def test_w1g3_selfless_exorcist_reads_a_characteristic_defined_power_in_exile(set_pool):
    """Lhurgoyf's power is the number of creature cards in all graveyards, in
    exile as anywhere (CR 604.3): with Lhurgoyf exiled that is the Bears, the
    Giant and the Wurm — 3, not the 0 a printed "*" reads as."""
    game, exorcist = _w1g3_exorcist_game(set_pool, ("Lhurgoyf", "Hill Giant", "Craw Wurm"))
    _w1g3_exorcise(game, 0)

    assert [c.name for c in game.players[1].exile] == ["Lhurgoyf"]
    assert exorcist.damage_marked == 3
    assert game.card_power_outside_battlefield(game.players[1].exile[0], 1) == 3


def test_w1g3_selfless_exorcist_whose_card_left_in_response_does_nothing(set_pool):
    """CR 608.2b: its one target gone, the ability does not resolve — nothing
    is exiled and no damage is dealt."""
    game, exorcist = _w1g3_exorcist_game(set_pool, ("Swamp", "Hill Giant", "Craw Wurm"))
    result = game.queue_permanent_ability(
        0, "Selfless Exorcist", target_player_index=1, target_permanent_index=2,
    )
    assert result.supported, result.details
    victim = game.players[1]
    victim.library.append(victim.graveyard.pop(2))           # the Wurm, in response
    _w1g3_resolve(game)

    assert victim.exile == [] and exorcist.damage_marked == 0
    assert game.is_on_battlefield(exorcist)


# The Advocates: "{T}: Return N target cards from an opponent's graveyard to
# their hand. <a second targeted sentence>." One announcement (CR 602.2b
# through 601.2c): a roles walk with one graveyard role per printed card — all
# out of one opponent's pile, each after the one before it — and the second
# target's role.

from engine.keywords import grant_keyword as _w1g3_grant_keyword

_W1G3_THEIRS = ("Swamp", "Hill Giant", "Terror", "Craw Wurm")


def _w1g3_advocate_game(set_pool, name, *, mine=("Grizzly Bears",),
                        theirs=_W1G3_THEIRS, their_board=(), third=None):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    seats = [
        _w1g3_PlayerState(
            name="P0", graveyard=[lea[n] for n in mine], library=[lea["Plains"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[n] for n in theirs], library=[lea["Island"]] * 5,
        ),
    ]
    if third is not None:
        seats.append(_w1g3_PlayerState(
            name="P2", graveyard=[lea[n] for n in third], library=[lea["Island"]] * 5,
        ))
    game = _w1g3_Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    advocate = _w1g3_Permanent(card=jud[name])
    game._put_permanent_onto_battlefield(0, advocate, None)
    advocate.tapped = False
    advocate.metadata["summoning_sickness_turn"] = -99
    board = []
    for other in their_board:
        permanent = _w1g3_Permanent(card=lea[other])
        game._put_permanent_onto_battlefield(1, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        board.append(permanent)
    _w1g3_resolve(game)
    return game, advocate, board


def _w1g3_announcements(tree, prefix=()):
    """Every complete announcement the roles walk offers, as tuples of
    ``(kind, seat, index)``."""
    for node in tree:
        here = prefix + ((node["kind"], node["seat"], node["index"]),)
        if node.get("next"):
            yield from _w1g3_announcements(node["next"], here)
        else:
            yield here


def _w1g3_refs(*picks):
    """The wire's ``target_role_refs``: ``(seat, index)`` for a card in a
    graveyard, a ``Permanent`` for a permanent."""
    return [
        {"permanent_id": pick.permanent_id} if isinstance(pick, _w1g3_Permanent)
        else {"graveyard_seat": pick[0], "graveyard_index": pick[1]}
        for pick in picks
    ]


def _w1g3_names(cards):
    return [card.name for card in cards]


def test_w1g3_nullmage_advocate_announces_two_cards_of_one_opponents_pile_and_a_permanent(set_pool):
    game, _advocate, (icy,) = _w1g3_advocate_game(
        set_pool, "Nullmage Advocate", their_board=("Icy Manipulator",),
    )
    spec = game.activation_target_spec(0, 0)
    assert spec["kind"] == "roles"
    assert [role["role"] for role in spec["roles"]] == [
        "first card", "second card", "artifact_or_enchantment",
    ]
    offered = set(_w1g3_announcements(spec["valid_targets"]))
    # Every pair of P1's four cards once (CR 115.3; the walk takes them in pile
    # order), never a card of the activator's own, and the Icy as the third.
    icy_slot = ("permanent", 1, game.battlefield_index_of(icy))
    assert offered == {
        (("graveyard", 1, a), ("graveyard", 1, b), icy_slot)
        for a in range(4) for b in range(a + 1, 4)
    }

    result = game.activate_permanent_ability(
        0, "Nullmage Advocate", target_role_refs=_w1g3_refs((1, 1), (1, 3), icy),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    victim = game.players[1]
    assert sorted(_w1g3_names(victim.hand)) == ["Craw Wurm", "Hill Giant"]
    assert _w1g3_names(victim.graveyard) == ["Swamp", "Terror", "Icy Manipulator"]
    assert not game.is_on_battlefield(icy)
    assert _w1g3_names(game.players[0].hand) == []


def test_w1g3_nullmage_advocate_needs_two_cards_in_a_single_opponents_graveyard(set_pool):
    """The 2004-10-04 ruling: "You can't activate this ability unless a single
    opponent has at least two cards in their graveyard to target." One card
    each in two opponents' piles is not two cards in one."""
    lone, advocate, _ = _w1g3_advocate_game(
        set_pool, "Nullmage Advocate", theirs=("Swamp",), third=("Island",),
        their_board=("Icy Manipulator",),
    )
    assert lone.activation_target_spec(0, 0)["valid_targets"] == []
    refused = lone.activate_permanent_ability(
        0, "Nullmage Advocate",
        target_role_refs=_w1g3_refs((1, 0), (2, 0), lone.permanent_by_id(
            next(p.permanent_id for p in lone.controlled_by(1))
        )),
    )
    assert not refused.supported
    assert not advocate.tapped and lone.stack == []

    # Two in the third seat's pile: only that pile is offered.
    two, _advocate, _ = _w1g3_advocate_game(
        set_pool, "Nullmage Advocate", theirs=("Swamp",), third=("Island", "Plains"),
        their_board=("Icy Manipulator",),
    )
    offered = set(_w1g3_announcements(two.activation_target_spec(0, 0)["valid_targets"]))
    assert {(path[0][1], path[1][1]) for path in offered} == {(2, 2)}


def test_w1g3_forcemage_advocate_returns_one_card_and_counters_a_creature(set_pool):
    game, advocate, _ = _w1g3_advocate_game(set_pool, "Forcemage Advocate")
    spec = game.activation_target_spec(0, 0)
    assert [role["role"] for role in spec["roles"]] == ["card", "creature"]
    # Its own Grizzly Bears card is not an opponent's.
    assert all(path[0][1] == 1 for path in _w1g3_announcements(spec["valid_targets"]))

    result = game.activate_permanent_ability(
        0, "Forcemage Advocate", target_role_refs=_w1g3_refs((1, 2), advocate),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    assert _w1g3_names(game.players[1].hand) == ["Terror"]
    assert (advocate.effective_power, advocate.effective_toughness) == (3, 2)


def test_w1g3_pulsemage_advocate_returns_three_and_reanimates_your_creature_card(set_pool):
    game, _advocate, _ = _w1g3_advocate_game(set_pool, "Pulsemage Advocate")
    spec = game.activation_target_spec(0, 0)
    assert [role["role"] for role in spec["roles"]] == [
        "first card", "second card", "third card", "creature card",
    ]
    assert len(list(_w1g3_announcements(spec["valid_targets"]))) == 4   # C(4, 3) × 1

    result = game.activate_permanent_ability(
        0, "Pulsemage Advocate",
        target_role_refs=_w1g3_refs((1, 0), (1, 2), (1, 3), (0, 0)),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    assert sorted(_w1g3_names(game.players[1].hand)) == ["Craw Wurm", "Swamp", "Terror"]
    assert _w1g3_names(game.players[1].graveyard) == ["Hill Giant"]
    assert [p.card.name for p in game.controlled_by(0)] == [
        "Pulsemage Advocate", "Grizzly Bears",
    ]


def test_w1g3_pulsemage_advocate_needs_a_creature_card_of_your_own(set_pool):
    """The 2004-10-04 ruling: "…and you have a creature card in your graveyard
    to target." Three of the opponent's cards are not enough alone."""
    game, advocate, _ = _w1g3_advocate_game(
        set_pool, "Pulsemage Advocate", mine=("Forest",),
    )
    assert game.activation_target_spec(0, 0)["valid_targets"] == []
    assert not game.activate_permanent_ability(
        0, "Pulsemage Advocate",
        target_role_refs=_w1g3_refs((1, 0), (1, 1), (1, 2), (0, 0)),
    ).supported
    assert not advocate.tapped


def _w1g3_spurnmage_in_combat(set_pool):
    """P1 attacks with a Grizzly Bears into P0's Spurnmage Advocate."""
    game, advocate, (bears,) = _w1g3_advocate_game(
        set_pool, "Spurnmage Advocate", their_board=("Grizzly Bears",),
    )
    declare_attack = __import__("tests.helpers", fromlist=["declare_attack"]).declare_attack
    declare_attack(game, 1)
    assert bears.attacking
    return game, advocate, bears


def test_w1g3_spurnmage_advocate_destroys_the_attacker_and_returns_two_cards(set_pool):
    game, _advocate, bears = _w1g3_spurnmage_in_combat(set_pool)
    result = game.activate_permanent_ability(
        0, "Spurnmage Advocate", target_role_refs=_w1g3_refs((1, 0), (1, 1), bears),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    assert sorted(_w1g3_names(game.players[1].hand)) == ["Hill Giant", "Swamp"]
    assert not game.is_on_battlefield(bears)


def test_w1g3_spurnmage_advocate_still_destroys_with_both_cards_gone(set_pool):
    """The 2004-10-04 ruling: "The ability is not countered if both cards are
    missing from the graveyard on resolution and the creature target is
    there." CR 608.2b removes it only when *every* target is illegal."""
    game, _advocate, bears = _w1g3_spurnmage_in_combat(set_pool)
    assert game.queue_permanent_ability(
        0, "Spurnmage Advocate", target_role_refs=_w1g3_refs((1, 0), (1, 1), bears),
    ).supported
    victim = game.players[1]
    victim.exile.extend([victim.graveyard.pop(1), victim.graveyard.pop(0)])
    _w1g3_resolve(game)

    assert not game.is_on_battlefield(bears)
    assert victim.hand == []
    assert _w1g3_names(victim.graveyard) == ["Terror", "Craw Wurm", "Grizzly Bears"]


def test_w1g3_spurnmage_advocate_spares_a_creature_given_shroud_but_returns_the_cards(set_pool):
    """CR 608.2b's last sentence: the illegal target is not affected and the
    rest of the ability still happens."""
    game, _advocate, bears = _w1g3_spurnmage_in_combat(set_pool)
    assert game.queue_permanent_ability(
        0, "Spurnmage Advocate", target_role_refs=_w1g3_refs((1, 2), (1, 3), bears),
    ).supported
    _w1g3_grant_keyword(bears, "shroud")
    _w1g3_resolve(game)

    assert game.is_on_battlefield(bears)
    assert sorted(_w1g3_names(game.players[1].hand)) == ["Craw Wurm", "Terror"]


def test_w1g3_spurnmage_advocate_with_every_target_gone_does_nothing(set_pool):
    game, _advocate, bears = _w1g3_spurnmage_in_combat(set_pool)
    assert game.queue_permanent_ability(
        0, "Spurnmage Advocate", target_role_refs=_w1g3_refs((1, 0), (1, 1), bears),
    ).supported
    victim = game.players[1]
    victim.exile.extend([victim.graveyard.pop(1), victim.graveyard.pop(0)])
    _w1g3_grant_keyword(bears, "shroud")
    _w1g3_resolve(game)

    assert any("every target is illegal" in line for line in game.log), game.log[-4:]
    assert game.is_on_battlefield(bears) and victim.hand == []


def test_w1g3_an_advocate_card_that_left_its_pile_is_not_replaced(set_pool):
    """One card of two gone in response: the other still returns, and the
    card that slid into the departed card's slot is not taken in its place."""
    game, _advocate, (icy,) = _w1g3_advocate_game(
        set_pool, "Nullmage Advocate", their_board=("Icy Manipulator",),
    )
    assert game.queue_permanent_ability(
        0, "Nullmage Advocate", target_role_refs=_w1g3_refs((1, 1), (1, 2), icy),
    ).supported
    victim = game.players[1]
    victim.exile.append(victim.graveyard.pop(1))          # Hill Giant, in response
    _w1g3_resolve(game)

    assert _w1g3_names(victim.hand) == ["Terror"]
    assert _w1g3_names(victim.graveyard) == ["Swamp", "Craw Wurm", "Icy Manipulator"]


# Shieldmage Advocate: "…Prevent all damage that would be dealt to any target
# this turn by a source of your choice." The second role is CR 115.4's union —
# a player or a permanent — and the source is CR 609.7a's choice beside the
# roles (``requires_source``), named on the activation's source fields.

from engine.handlers._common import apply_damage_to_creature as _w1g3_damage_creature


def _w1g3_shieldmage(set_pool):
    return _w1g3_advocate_game(
        set_pool, "Shieldmage Advocate", their_board=("Grizzly Bears", "Hill Giant"),
    )


def test_w1g3_shieldmage_advocate_offers_a_card_and_any_target_and_asks_for_a_source(set_pool):
    game, advocate, (bears, giant) = _w1g3_shieldmage(set_pool)
    spec = game.activation_target_spec(0, 0)
    assert [role["role"] for role in spec["roles"]] == ["card", "any target"]
    assert spec["requires_source"]
    assert {(t["seat"], t["name"]) for t in spec["source_targets"]} >= {
        (1, "Grizzly Bears"), (1, "Hill Giant"),
    }
    second = {
        (node["kind"], node["seat"], node.get("index"))
        for node in spec["valid_targets"][0]["next"]
    }
    # Both players and every creature: "any target" (CR 115.4).
    assert second == {
        ("player", 0, None), ("player", 1, None),
        ("permanent", 0, game.battlefield_index_of(advocate)),
        ("permanent", 1, game.battlefield_index_of(bears)),
        ("permanent", 1, game.battlefield_index_of(giant)),
    }


def test_w1g3_shieldmage_advocate_shields_its_controller_from_the_chosen_source(set_pool):
    game, _advocate, (bears, giant) = _w1g3_shieldmage(set_pool)
    result = game.activate_permanent_ability(
        0, "Shieldmage Advocate",
        target_role_refs=[{"graveyard_seat": 1, "graveyard_index": 1}, {"seat": 0}],
        source_seat=1, source_permanent_index=game.battlefield_index_of(bears),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    assert _w1g3_names(game.players[1].hand) == ["Hill Giant"]
    me = game.players[0]
    game._deal_damage_to_player(me, 2, source=bears)
    game._deal_damage_to_player(me, 2, source=bears)        # all of it, all turn
    assert me.life == 20
    game._deal_damage_to_player(me, 3, source=giant)        # another source
    assert me.life == 17
    assert game.players[1].life == 20


def test_w1g3_shieldmage_advocate_shields_a_creature_and_only_from_its_source(set_pool):
    game, advocate, (bears, giant) = _w1g3_shieldmage(set_pool)
    result = game.activate_permanent_ability(
        0, "Shieldmage Advocate",
        target_role_refs=_w1g3_refs((1, 0), advocate),
        source_seat=1, source_permanent_index=game.battlefield_index_of(giant),
    )
    assert result.supported, result.details
    _w1g3_resolve(game)

    _w1g3_damage_creature(game, advocate, 3, giant)
    assert advocate.damage_marked == 0
    _w1g3_damage_creature(game, advocate, 2, bears)
    assert advocate.damage_marked == 2
    # The player beside it is not shielded: the shield is around what was named.
    game._deal_damage_to_player(game.players[0], 3, source=giant)
    assert game.players[0].life == 17


def test_w1g3_shieldmage_advocate_still_shields_with_its_card_gone(set_pool):
    """CR 608.2b: one of two targets illegal, the ability still resolves —
    the card is not returned and the shield is still armed."""
    game, _advocate, (bears, _giant) = _w1g3_shieldmage(set_pool)
    assert game.queue_permanent_ability(
        0, "Shieldmage Advocate",
        target_role_refs=[{"graveyard_seat": 1, "graveyard_index": 2}, {"seat": 0}],
        source_seat=1, source_permanent_index=game.battlefield_index_of(bears),
    ).supported
    victim = game.players[1]
    victim.exile.append(victim.graveyard.pop(2))           # Terror, in response
    _w1g3_resolve(game)

    assert victim.hand == []
    game._deal_damage_to_player(game.players[0], 2, source=bears)
    assert game.players[0].life == 20

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
#
# The Nightmares: an entry exile linked to leaving (CR 607.2a, 610.3). Each
# card is cast through the real path and its leaving half driven by Swords to
# Plowshares; each is also killed with its entry trigger on the stack, where
# the leave trigger resolves first and returns nothing and the entry trigger
# then exiles for good (the Worldgorger Dragon / Wormfang Drake rulings,
# 2022-12-08).

import pytest as _w1g4_pytest

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.linked_exile import linked_entries as _w1g4_linked_entries
from engine.models import Permanent as _W1G4Permanent
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_card(set_pool, name):
    for code in ("JUD", "LEA", "ODY", "TOR", "ICE"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g4_game(set_pool, *, hand=(), opp_hand=(), interactive=()):
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    p0 = _W1G4PlayerState(
        name="P0", hand=[card(n) for n in hand], library=[card("Island")] * 5,
    )
    p1 = _W1G4PlayerState(
        name="P1", hand=[card(n) for n in opp_hand], library=[card("Forest")] * 5,
    )
    game = _W1G4Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g4_put(game, set_pool, seat, name):
    permanent = _W1G4Permanent(card=_w1g4_card(set_pool, name))
    permanent.metadata["summoning_sickness_turn"] = -5
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g4_resolve_stack(game)
    return permanent


def _w1g4_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g4_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def _w1g4_drain(game):
    for _ in range(6):
        _w1g4_resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _w1g4_swords(game, set_pool, victim):
    """Exile *victim* with Swords to Plowshares, dealt into seat 0's hand here
    so a test's hand is only the cards it is about."""
    game.players[0].hand.append(set_pool("LEA")["Swords to Plowshares"])
    result = game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=game.controller_index_of(victim),
        target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, game.log[-5:]
    _w1g4_drain(game)


# --- Wormfang Newt / Turtle: "exile a land you control" --------------------


@_w1g4_pytest.mark.parametrize("name", ["Wormfang Newt", "Wormfang Turtle"])
def test_w1g4_a_land_nightmare_exiles_a_land_and_gives_it_back_untapped(set_pool, name):
    game = _w1g4_game(set_pool, hand=[name])
    plains = _w1g4_put(game, set_pool, 0, "Plains")
    _w1g4_put(game, set_pool, 0, "Island")
    _w1g4_put(game, set_pool, 1, "Forest")
    plains.tapped = True
    game.cast_from_hand(0, name)
    _w1g4_drain(game)

    # One of *its controller's* lands, chosen as the trigger resolved: the
    # opponent's Forest is never a candidate.
    p0 = game.players[0]
    assert [c.name for c in p0.exile] == ["Plains"], game.log[-6:]
    assert _w1g4_names(game, 0) == sorted(["Island", name])
    assert _w1g4_names(game, 1) == ["Forest"]
    nightmare = _w1g4_named(game, 0, name)
    assert [e["card"].name for e in _w1g4_linked_entries(nightmare)] == ["Plains"]

    _w1g4_swords(game, set_pool, nightmare)

    # "Return the exiled card to the battlefield under its owner's control" —
    # a new object (CR 400.7): untapped, and not the permanent that left.
    returned = _w1g4_named(game, 0, "Plains")
    assert returned is not plains and not returned.tapped
    assert [c.name for c in p0.exile] == [name]


def test_w1g4_wormfang_newt_asks_its_controller_which_land(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Newt"], interactive=(0,))
    plains = _w1g4_put(game, set_pool, 0, "Plains")
    island = _w1g4_put(game, set_pool, 0, "Island")
    _w1g4_put(game, set_pool, 1, "Forest")
    game.queue_from_hand(0, "Wormfang Newt")
    game.resolve_top_of_stack()  # the creature spell
    game.resolve_top_of_stack()  # its entry trigger, which stops to ask

    choice = game.waiting_prompt()
    assert choice is not None and choice.kind == "permanent_choice"
    assert choice.player_index == 0
    # Only lands its controller controls: not the Newt, not the Forest.
    assert {p.card.name for p in game.live_permanent_choices(choice)} == {
        "Plains", "Island",
    }
    assert game.confirm_permanent_choice(0, island.permanent_id)
    _w1g4_drain(game)

    assert [c.name for c in game.players[0].exile] == ["Island"]
    assert game.is_on_battlefield(plains)


def test_w1g4_wormfang_newt_with_no_land_exiles_nothing(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Newt"])
    _w1g4_put(game, set_pool, 1, "Forest")
    game.cast_from_hand(0, "Wormfang Newt")
    _w1g4_drain(game)

    assert game.players[0].exile == [] and game.players[1].exile == []
    assert _w1g4_names(game, 1) == ["Forest"]
    assert "Wormfang Newt: there is no permanent it could choose" in game.log


def test_w1g4_wormfang_newt_killed_in_response_exiles_its_land_for_good(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Newt"])
    _w1g4_put(game, set_pool, 0, "Plains")
    game.queue_from_hand(0, "Wormfang Newt")
    game.resolve_top_of_stack()
    newt = _w1g4_named(game, 0, "Wormfang Newt")
    assert game.stack, "the entry trigger is a stack object (CR 603.3)"

    _w1g4_swords(game, set_pool, newt)

    # The leave trigger resolved first and found nothing; the entry trigger
    # then exiled the Plains, and nothing is left that will return it.
    assert sorted(c.name for c in game.players[0].exile) == ["Plains", "Wormfang Newt"]
    assert _w1g4_names(game, 0) == []


# --- Wormfang Drake: "sacrifice it unless you exile a creature you control
# other than this creature" -------------------------------------------------


def test_w1g4_wormfang_drake_exiles_a_creature_and_returns_it_when_it_leaves(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"])
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    game.cast_from_hand(0, "Wormfang Drake")
    _w1g4_drain(game)

    # A seat nobody asks pays the toll: the Bears go, the Drake stays.
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"], game.log[-6:]
    drake = _w1g4_named(game, 0, "Wormfang Drake")
    assert [e["card"].name for e in _w1g4_linked_entries(drake)] == ["Grizzly Bears"]

    _w1g4_swords(game, set_pool, drake)

    returned = _w1g4_named(game, 0, "Grizzly Bears")
    assert returned is not bears
    assert [c.name for c in game.players[0].exile] == ["Wormfang Drake"]


def test_w1g4_wormfang_drake_alone_is_sacrificed_without_an_offer(set_pool):
    # "If you don't control any other creatures as the enters-the-battlefield
    # ability resolves, you must sacrifice Wormfang Drake." (2022-12-08.) An
    # interactive seat, so an offer — had one been made — would be left owed.
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"], interactive=(0,))
    _w1g4_put(game, set_pool, 1, "Grizzly Bears")
    game.queue_from_hand(0, "Wormfang Drake")
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()

    assert not game.pending_choices
    assert [c.name for c in game.players[0].graveyard] == ["Wormfang Drake"]
    # The opponent's creature was never a price the Drake's controller pays.
    assert _w1g4_names(game, 1) == ["Grizzly Bears"]


@_w1g4_pytest.mark.parametrize("accept", [True, False])
def test_w1g4_wormfang_drake_offers_its_controller_the_price(set_pool, accept):
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"], interactive=(0,))
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    game.queue_from_hand(0, "Wormfang Drake")
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()
    assert game.waiting_prompt().kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=accept)
    if accept:
        # Which creature is the next question, and only the Bears answer it:
        # "other than this creature".
        choice = game.waiting_prompt()
        assert choice.kind == "permanent_choice"
        assert [p.card.name for p in game.live_permanent_choices(choice)] == [
            "Grizzly Bears",
        ]
        assert game.confirm_permanent_choice(0, bears.permanent_id)
    _w1g4_drain(game)

    if accept:
        assert _w1g4_names(game, 0) == ["Wormfang Drake"]
        assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    else:
        assert _w1g4_names(game, 0) == ["Grizzly Bears"]
        assert [c.name for c in game.players[0].graveyard] == ["Wormfang Drake"]


def test_w1g4_wormfang_drake_killed_in_response_exiles_the_price_for_good(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Drake"])
    _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    game.queue_from_hand(0, "Wormfang Drake")
    game.resolve_top_of_stack()
    drake = _w1g4_named(game, 0, "Wormfang Drake")
    assert game.stack

    _w1g4_swords(game, set_pool, drake)

    # "If you exile a creature you control, it will be exiled indefinitely.
    # Wormfang Drake won't return it." (2022-12-08.)
    assert sorted(c.name for c in game.players[0].exile) == [
        "Grizzly Bears", "Wormfang Drake",
    ]
    assert _w1g4_names(game, 0) == []


# --- Wormfang Crab: "an opponent chooses a permanent you control other than
# this creature and exiles it" ----------------------------------------------


def test_w1g4_wormfang_crab_s_opponent_picks_from_the_crab_controller_s_board(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Crab"], interactive=(1,))
    _w1g4_put(game, set_pool, 0, "Plains")
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    _w1g4_put(game, set_pool, 1, "Forest")
    game.queue_from_hand(0, "Wormfang Crab")
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()

    choice = game.waiting_prompt()
    assert choice is not None and choice.kind == "permanent_choice"
    # The *opponent* is asked, about the Crab controller's permanents other
    # than the Crab — never their own Forest.
    assert choice.player_index == 1
    assert {p.card.name for p in game.live_permanent_choices(choice)} == {
        "Plains", "Grizzly Bears",
    }
    assert game.confirm_permanent_choice(1, bears.permanent_id)
    _w1g4_drain(game)

    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    crab = _w1g4_named(game, 0, "Wormfang Crab")
    assert [e["card"].name for e in _w1g4_linked_entries(crab)] == ["Grizzly Bears"]

    _w1g4_swords(game, set_pool, crab)

    assert _w1g4_names(game, 0) == ["Grizzly Bears", "Plains"]
    assert [c.name for c in game.players[0].exile] == ["Wormfang Crab"]


def test_w1g4_wormfang_crab_s_exiled_token_ceases_to_exist(set_pool):
    # CR 111.7: a token that leaves the battlefield ceases to exist, so there
    # is no card in exile for "return the exiled card" to name. The handler
    # behind the Crab (``exile_recorded_permanent``, Cannibalize's) used to
    # append the token's card to its owner's exile like any other card.
    from engine.tokens import make_token_card

    game = _w1g4_game(set_pool, hand=["Wormfang Crab"], interactive=(1,))
    token = _W1G4Permanent(card=make_token_card("Saproling", 1, 1, "Creature — Saproling"))
    token.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(0, token, None)
    game.queue_from_hand(0, "Wormfang Crab")
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()
    assert game.confirm_permanent_choice(1, token.permanent_id)
    _w1g4_drain(game)

    crab = _w1g4_named(game, 0, "Wormfang Crab")
    assert not game.is_on_battlefield(token)
    assert game.players[0].exile == []
    assert _w1g4_linked_entries(crab) == ()

    _w1g4_swords(game, set_pool, crab)
    assert _w1g4_names(game, 0) == []


def test_w1g4_wormfang_crab_alone_exiles_nothing(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Crab"])
    _w1g4_put(game, set_pool, 1, "Forest")
    game.cast_from_hand(0, "Wormfang Crab")
    _w1g4_drain(game)

    assert _w1g4_names(game, 0) == ["Wormfang Crab"]
    assert _w1g4_names(game, 1) == ["Forest"]
    assert game.players[0].exile == [] and game.players[1].exile == []


# --- Worldgorger Dragon: "exile all other permanents you control" ----------


def _w1g4_gorger_board(set_pool, *, opp_creatures=(), interactive=()):
    from engine.aura_attachment import attach_aura

    game = _w1g4_game(set_pool, hand=["Worldgorger Dragon"], interactive=interactive)
    _w1g4_put(game, set_pool, 0, "Plains")
    bears = _w1g4_put(game, set_pool, 0, "Grizzly Bears")
    aura = _w1g4_put(game, set_pool, 0, "Holy Strength")
    attach_aura(aura, bears)
    for name in opp_creatures:
        _w1g4_put(game, set_pool, 1, name)
    _w1g4_put(game, set_pool, 1, "Forest")
    return game


def _w1g4_aura_host(game, name):
    aura = next(p for p in game.all_permanents() if p.card.name == name)
    host = aura.metadata.get("attached_to")
    return None if host is None else host.card.name


def test_w1g4_worldgorger_dragon_exiles_only_its_controller_s_other_permanents(set_pool):
    game = _w1g4_gorger_board(set_pool, opp_creatures=["Hill Giant"])
    game.cast_from_hand(0, "Worldgorger Dragon")
    _w1g4_drain(game)

    assert _w1g4_names(game, 0) == ["Worldgorger Dragon"]
    assert _w1g4_names(game, 1) == ["Forest", "Hill Giant"]
    dragon = _w1g4_named(game, 0, "Worldgorger Dragon")
    assert sorted(e["card"].name for e in _w1g4_linked_entries(dragon)) == [
        "Grizzly Bears", "Holy Strength", "Plains",
    ]

    _w1g4_swords(game, set_pool, dragon)

    assert _w1g4_names(game, 0) == ["Grizzly Bears", "Holy Strength", "Plains"]
    # The Aura may not enchant the Bears, which enter at the same time; the
    # Hill Giant was already there and is the one legal host — an opponent's
    # permanent, which the ruling allows (2022-12-08).
    assert _w1g4_aura_host(game, "Holy Strength") == "Hill Giant"
    assert game.players[0].exile == [game.players[0].exile[0]]
    assert game.players[0].exile[0].name == "Worldgorger Dragon"


def test_w1g4_worldgorger_dragon_leaves_an_aura_with_no_host_in_exile(set_pool):
    game = _w1g4_gorger_board(set_pool)
    game.cast_from_hand(0, "Worldgorger Dragon")
    _w1g4_drain(game)
    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Worldgorger Dragon"))

    # "If the Aura can't legally be attached to anything, it stays exiled."
    assert _w1g4_names(game, 0) == ["Grizzly Bears", "Plains"]
    assert sorted(c.name for c in game.players[0].exile) == [
        "Holy Strength", "Worldgorger Dragon",
    ]
    # Not binned by CR 704.5m as an unattached Aura: it never entered.
    assert [c.name for c in game.players[0].graveyard] == ["Swords to Plowshares"]


def test_w1g4_worldgorger_dragon_asks_where_a_returning_aura_goes(set_pool):
    game = _w1g4_gorger_board(
        set_pool, opp_creatures=["Hill Giant", "Gray Ogre"], interactive=(0,),
    )
    game.cast_from_hand(0, "Worldgorger Dragon")
    _w1g4_drain(game)
    dragon = _w1g4_named(game, 0, "Worldgorger Dragon")
    game.players[0].hand.append(set_pool("LEA")["Swords to Plowshares"])
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[dragon.permanent_id],
    )
    game.resolve_top_of_stack()  # Swords; the leave trigger goes on the stack
    game.resolve_top_of_stack()  # the leave trigger, which stops to ask

    choice = game.waiting_prompt()
    assert choice is not None and choice.kind == "permanent_choice"
    assert {p.card.name for p in game.live_permanent_choices(choice)} == {
        "Hill Giant", "Gray Ogre",
    }
    # Nothing has returned while the question is owed: the cards enter together.
    assert _w1g4_names(game, 0) == []
    ogre = _w1g4_named(game, 1, "Gray Ogre")
    assert game.confirm_permanent_choice(0, ogre.permanent_id)
    _w1g4_drain(game)

    assert _w1g4_names(game, 0) == ["Grizzly Bears", "Holy Strength", "Plains"]
    assert _w1g4_aura_host(game, "Holy Strength") == "Gray Ogre"


def test_w1g4_worldgorger_dragon_killed_in_response_exiles_for_good(set_pool):
    game = _w1g4_gorger_board(set_pool, opp_creatures=["Hill Giant"])
    game.queue_from_hand(0, "Worldgorger Dragon")
    game.resolve_top_of_stack()
    dragon = _w1g4_named(game, 0, "Worldgorger Dragon")
    assert game.stack

    _w1g4_swords(game, set_pool, dragon)

    # "It won't return anything. Then the enters-the-battlefield ability will
    # exile all other permanents you control indefinitely." (2022-12-08.)
    assert _w1g4_names(game, 0) == []
    assert sorted(c.name for c in game.players[0].exile) == [
        "Grizzly Bears", "Holy Strength", "Plains", "Worldgorger Dragon",
    ]
    assert _w1g4_names(game, 1) == ["Forest", "Hill Giant"]


# --- Soulgorger Orgg: "you lose all but 1 life" / "you gain life equal to the
# life you lost when it entered" (CR 607.1) ---------------------------------


def _w1g4_terror(game, set_pool, victim):
    """Destroy *victim* with Terror (cast by seat 1, so no life of seat 0's
    moves with it)."""
    game.players[1].hand.append(set_pool("LEA")["Terror"])
    result = game.queue_from_hand(
        1, "Terror", target_player_index=game.controller_index_of(victim),
        target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, game.log[-5:]
    _w1g4_drain(game)


def test_w1g4_soulgorger_orgg_takes_all_but_1_life_and_gives_it_back(set_pool):
    game = _w1g4_game(set_pool, hand=["Soulgorger Orgg"])
    p0 = game.players[0]
    game.cast_from_hand(0, "Soulgorger Orgg")
    _w1g4_drain(game)
    assert p0.life == 1, game.log[-4:]

    # The number is the one the entry took, not a recount: life gained since
    # is kept, and the 19 comes back on top of it.
    game._gain_life(p0, 5, "test")
    assert p0.life == 6
    _w1g4_terror(game, set_pool, _w1g4_named(game, 0, "Soulgorger Orgg"))

    assert p0.life == 25
    assert [c.name for c in p0.graveyard] == ["Soulgorger Orgg"]


def test_w1g4_soulgorger_orgg_at_1_life_takes_nothing_and_returns_nothing(set_pool):
    game = _w1g4_game(set_pool, hand=["Soulgorger Orgg"])
    p0 = game.players[0]
    p0.life = 1
    game.cast_from_hand(0, "Soulgorger Orgg")
    _w1g4_drain(game)
    assert p0.life == 1

    _w1g4_terror(game, set_pool, _w1g4_named(game, 0, "Soulgorger Orgg"))
    assert p0.life == 1


def test_w1g4_soulgorger_orgg_killed_in_response_keeps_the_life_lost(set_pool):
    game = _w1g4_game(set_pool, hand=["Soulgorger Orgg"])
    p0 = game.players[0]
    game.queue_from_hand(0, "Soulgorger Orgg")
    game.resolve_top_of_stack()
    orgg = _w1g4_named(game, 0, "Soulgorger Orgg")
    assert game.stack and p0.life == 20

    _w1g4_terror(game, set_pool, orgg)

    # The leave trigger resolved first, with nothing noted to give back; the
    # entry trigger then took all but 1, and nothing is left to return it.
    assert p0.life == 1


def test_w1g4_a_returned_soulgorger_orgg_is_a_new_object_with_no_note(set_pool):
    # CR 400.7: the Orgg that comes back remembers nothing. Two of them on one
    # battlefield each give back only what their own entry took.
    game = _w1g4_game(set_pool, hand=["Soulgorger Orgg", "Soulgorger Orgg"])
    p0 = game.players[0]
    game.cast_from_hand(0, "Soulgorger Orgg")
    _w1g4_drain(game)
    first = _w1g4_named(game, 0, "Soulgorger Orgg")
    game._gain_life(p0, 9, "test")  # 10
    game.cast_from_hand(0, "Soulgorger Orgg")
    _w1g4_drain(game)
    assert p0.life == 1
    second = next(
        p for p in game.controlled_by(0)
        if p.card.name == "Soulgorger Orgg" and p is not first
    )

    _w1g4_terror(game, set_pool, second)
    assert p0.life == 10
    _w1g4_terror(game, set_pool, first)
    assert p0.life == 29


# --- Sutured Ghoul: "As this creature enters, exile any number of creature
# cards from your graveyard. / …power is equal to the total power of the
# exiled cards …" (CR 614.1c, 604.3, 607.2b) --------------------------------


def _w1g4_ghoul_game(set_pool, graveyard, *, interactive=(), opp_graveyard=()):
    game = _w1g4_game(set_pool, hand=["Sutured Ghoul"], interactive=interactive)
    game.players[0].graveyard = [_w1g4_card(set_pool, n) for n in graveyard]
    game.players[1].graveyard = [_w1g4_card(set_pool, n) for n in opp_graveyard]
    return game


def _w1g4_pt(perm):
    return (perm.effective_power, perm.effective_toughness)


def test_w1g4_sutured_ghoul_is_the_sum_of_the_creature_cards_it_exiles(set_pool):
    game = _w1g4_ghoul_game(
        set_pool, ["Grizzly Bears", "Lightning Bolt", "Hill Giant"],
    )
    game.cast_from_hand(0, "Sutured Ghoul")
    _w1g4_drain(game)

    p0 = game.players[0]
    ghoul = _w1g4_named(game, 0, "Sutured Ghoul")
    # A seat nobody asks exiles every creature card, and only creature cards.
    assert sorted(c.name for c in p0.exile) == ["Grizzly Bears", "Hill Giant"]
    assert [c.name for c in p0.graveyard] == ["Lightning Bolt"]
    assert _w1g4_pt(ghoul) == (5, 5)
    assert sorted(e["card"].name for e in _w1g4_linked_entries(ghoul)) == [
        "Grizzly Bears", "Hill Giant",
    ]


def test_w1g4_sutured_ghoul_asks_which_cards_and_any_number_includes_some(set_pool):
    game = _w1g4_ghoul_game(
        set_pool, ["Grizzly Bears", "Hill Giant", "Lightning Bolt"], interactive=(0,),
    )
    game.queue_from_hand(0, "Sutured Ghoul")
    game.resolve_top_of_stack()

    choice = game.waiting_prompt()
    assert choice is not None and choice.kind == "entry_exile"
    # The creature cards only: slot 0 and slot 1, never the Bolt.
    assert game._entry_exile_candidates(choice) == [0, 1]
    # More picks than there are candidates is refused, and the prompt stays.
    assert not game.resolve_pending_choice(
        "entry_exile", 0,
        picks=[{"index": 0, "counter": None}, {"index": 1, "counter": None},
               {"index": 2, "counter": None}],
    )
    assert game.resolve_pending_choice(
        "entry_exile", 0, picks=[{"index": 1, "counter": None}],
    )
    _w1g4_drain(game)

    ghoul = _w1g4_named(game, 0, "Sutured Ghoul")
    assert [c.name for c in game.players[0].exile] == ["Hill Giant"]
    assert _w1g4_pt(ghoul) == (3, 3)


def test_w1g4_sutured_ghoul_exiling_nothing_is_a_0_0_that_dies(set_pool):
    game = _w1g4_ghoul_game(set_pool, ["Grizzly Bears"], interactive=(0,))
    game.queue_from_hand(0, "Sutured Ghoul")
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("entry_exile", 0, picks=[])
    _w1g4_drain(game)
    game.check_state_based_actions()

    p0 = game.players[0]
    assert _w1g4_names(game, 0) == []
    assert sorted(c.name for c in p0.graveyard) == ["Grizzly Bears", "Sutured Ghoul"]


def test_w1g4_sutured_ghoul_with_an_empty_graveyard_asks_nothing(set_pool):
    game = _w1g4_ghoul_game(set_pool, ["Lightning Bolt"], interactive=(0,))
    game.queue_from_hand(0, "Sutured Ghoul")
    game.resolve_top_of_stack()

    assert not game.pending_choices
    game.check_state_based_actions()
    assert [c.name for c in game.players[0].graveyard] == [
        "Lightning Bolt", "Sutured Ghoul",
    ]


def test_w1g4_sutured_ghoul_counts_an_exiled_cards_cda_as_it_changes(set_pool):
    # "If Dungrove Elder is exiled this way, its power and toughness while it's
    # in exile are equal to the number of Forests you control, and Sutured
    # Ghoul's power and toughness will change as [that] number … changes."
    # (2011-09-22.) Lhurgoyf in exile counts the creature cards in all
    # graveyards: one in the opponent's at first.
    game = _w1g4_ghoul_game(
        set_pool, ["Grizzly Bears", "Lhurgoyf"], opp_graveyard=["Hill Giant"],
    )
    game.cast_from_hand(0, "Sutured Ghoul")
    _w1g4_drain(game)
    ghoul = _w1g4_named(game, 0, "Sutured Ghoul")
    # Bears 2/2 + Lhurgoyf 1/2 (one creature card in a graveyard).
    assert _w1g4_pt(ghoul) == (3, 4)

    game.players[1].graveyard.append(_w1g4_card(set_pool, "Gray Ogre"))
    game._recompute_continuous_effects()
    assert _w1g4_pt(ghoul) == (4, 5)


def test_w1g4_sutured_ghoul_leaving_leaves_its_cards_in_exile(set_pool):
    game = _w1g4_ghoul_game(set_pool, ["Grizzly Bears", "Hill Giant"])
    game.cast_from_hand(0, "Sutured Ghoul")
    _w1g4_drain(game)
    p0 = game.players[0]
    life_before = p0.life
    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Sutured Ghoul"))

    # Nothing prints a return: the cards stay exiled beside it. Swords reads
    # the Ghoul's power as it left (5), last-known information.
    assert sorted(c.name for c in p0.exile) == [
        "Grizzly Bears", "Hill Giant", "Sutured Ghoul",
    ]
    assert p0.life == life_before + 5


# --- The drive list: supported on arrival, given a game --------------------


def _w1g4_next_actives(game, count):
    seats = []
    for _ in range(count):
        seats.append(game.start_next_turn())
        _w1g4_drain(game)
    return seats


def test_w1g4_wormfang_manta_that_stays_skips_its_controller_s_next_turn(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Manta"])
    game.start_turn(0)
    game.cast_from_hand(0, "Wormfang Manta")
    _w1g4_drain(game)

    assert _w1g4_next_actives(game, 4) == [1, 1, 0, 1]


def test_w1g4_wormfang_manta_gone_the_same_turn_skips_the_extra_turn(set_pool):
    # CR 614.10: "skip your next turn" replaces the next turn its player would
    # take, and CR 500.7 puts the extra turn directly after this one — so the
    # skip eats the extra turn and the opponent plays next. It used to take the
    # extra turn at once and skip the controller's next *normal* turn: the same
    # count of turns, one of them moved ahead of the opponent's.
    game = _w1g4_game(set_pool, hand=["Wormfang Manta"])
    game.start_turn(0)
    game.cast_from_hand(0, "Wormfang Manta")
    _w1g4_drain(game)
    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Wormfang Manta"))

    assert _w1g4_next_actives(game, 4) == [1, 0, 1, 0]
    assert "P0 skips the extra turn (CR 614.10)" in game.log


def test_w1g4_wormfang_manta_gone_after_the_skip_gives_an_extra_turn(set_pool):
    game = _w1g4_game(set_pool, hand=["Wormfang Manta"])
    game.start_turn(0)
    game.cast_from_hand(0, "Wormfang Manta")
    _w1g4_drain(game)
    assert _w1g4_next_actives(game, 2) == [1, 1]  # P0's turn was skipped

    # During the opponent's turn: "you take an extra turn after this one".
    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Wormfang Manta"))
    assert _w1g4_next_actives(game, 3) == [0, 0, 1]


def test_w1g4_wormfang_behemoth_holds_its_controller_s_hand_until_it_leaves(set_pool):
    game = _w1g4_game(
        set_pool, hand=["Wormfang Behemoth", "Grizzly Bears", "Lightning Bolt"],
    )
    game.cast_from_hand(0, "Wormfang Behemoth")
    _w1g4_drain(game)
    p0 = game.players[0]
    assert p0.hand == []
    assert sorted(c.name for c in p0.exile) == ["Grizzly Bears", "Lightning Bolt"]

    _w1g4_swords(game, set_pool, _w1g4_named(game, 0, "Wormfang Behemoth"))

    assert sorted(c.name for c in p0.hand) == ["Grizzly Bears", "Lightning Bolt"]
    assert [c.name for c in p0.exile] == ["Wormfang Behemoth"]


def test_w1g4_anurid_brushhopper_comes_back_out_of_exile_at_the_end_step(set_pool):
    # Supported on arrival and never seen to work: the delayed return looked
    # for the card on the battlefield and in the graveyards, logged "no longer
    # in a graveyard", and left the Brushhopper in exile for good.
    game = _w1g4_game(
        set_pool, hand=["Grizzly Bears", "Lightning Bolt", "Hill Giant"],
    )
    game.start_turn(0)
    hopper = _w1g4_put(game, set_pool, 0, "Anurid Brushhopper")
    hopper.tapped = True
    hopper.damage_marked = 2
    result = game.activate_permanent_ability(0, "Anurid Brushhopper")
    assert result.supported, result.details
    _w1g4_drain(game)

    p0 = game.players[0]
    assert len(p0.hand) == 1 and len(p0.graveyard) == 2
    assert [c.name for c in p0.exile] == ["Anurid Brushhopper"]

    game.resolve_end_step(0)
    _w1g4_drain(game)

    back = _w1g4_named(game, 0, "Anurid Brushhopper")
    # A new object (CR 400.7): untapped, no damage, a fresh id.
    assert back is not hopper and not back.tapped and back.damage_marked == 0
    assert p0.exile == []


def test_w1g4_anurid_brushhopper_needs_two_cards_to_discard(set_pool):
    game = _w1g4_game(set_pool, hand=["Grizzly Bears"])
    game.start_turn(0)
    _w1g4_put(game, set_pool, 0, "Anurid Brushhopper")
    result = game.activate_permanent_ability(0, "Anurid Brushhopper")

    assert not result.supported
    assert _w1g4_names(game, 0) == ["Anurid Brushhopper"]
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]

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
