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

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
#
# Guiltfeeder: "Whenever this creature attacks and isn't blocked, defending
# player loses 1 life for each card in their graveyard." The pile counted is
# the defending player's own (CR 506.2's seat, frozen by the declare-blockers
# fire site), never the attacker's.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_guiltfeeder_table(set_pool, catalog_by_name, graveyards):
    """One seat per entry of *graveyards* (how many Islands each holds), a
    Guiltfeeder on seat 0's battlefield, awake."""
    island = catalog_by_name["Island"]
    game = _W1G7Game(players=[
        _W1G7PlayerState(name=f"P{seat}", library=[island] * 10,
                         graveyard=[island] * count)
        for seat, count in enumerate(graveyards)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    feeder = _W1G7Permanent(card=set_pool("JUD")["Guiltfeeder"])
    game._put_permanent_onto_battlefield(0, feeder, None)
    _w1g7_resolve(game)
    _w1g7_nosick(feeder)
    return game, feeder


def _w1g7_attack(game, defender, blocks=None):
    """Seat 0 attacks *defender* with everything; *blocks* declared; then the
    declare-blockers step's priority window, where the trigger resolves."""
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [
        slot for slot, perm in enumerate(game.players[0].battlefield)
        if perm.is_creature
    ]
    ok, why = game.declare_attackers(0, slots, defending_player_index=defender)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(defender, dict(blocks or {}))
    assert ok, why
    _w1g7_resolve(game)
    game.advance_combat_phase()
    _w1g7_resolve(game)


def test_w1g7_guiltfeeder_unblocked_drains_the_defender_by_their_graveyard(
    set_pool, catalog_by_name,
):
    """Five cards in the defender's graveyard, three in the attacker's: the
    defender loses five as the trigger resolves, before the 0/4 deals its no
    combat damage, and the attacker loses nothing."""
    game, _feeder = _w1g7_guiltfeeder_table(set_pool, catalog_by_name, [3, 5])
    _w1g7_attack(game, 1)

    assert game.players[1].life == 15
    assert game.players[0].life == 20
    assert "Guiltfeeder: P1 lost 5 life (20 -> 15)" in game.log


def test_w1g7_guiltfeeder_blocked_does_nothing(set_pool, catalog_by_name):
    """Fear lets a black creature block it, and a blocked Guiltfeeder's
    trigger never fires."""
    game, _feeder = _w1g7_guiltfeeder_table(set_pool, catalog_by_name, [0, 5])
    knight = _W1G7Permanent(card=catalog_by_name["Black Knight"])
    game._put_permanent_onto_battlefield(1, knight, None)
    _w1g7_resolve(game)
    _w1g7_attack(game, 1, blocks={0: 0})

    assert game.players[1].life == 20
    assert not any("Guiltfeeder:" in line and "lost" in line for line in game.log)


def test_w1g7_guiltfeeder_counts_the_attacked_players_pile_at_a_table_of_three(
    set_pool, catalog_by_name,
):
    """Three seats, the Guiltfeeder attacking the third: it is that seat's
    graveyard (four cards) that is counted and that seat that loses — not the
    first opponent in seat order, whose graveyard holds nine."""
    game, _feeder = _w1g7_guiltfeeder_table(set_pool, catalog_by_name, [0, 9, 4])
    _w1g7_attack(game, 2)

    assert [p.life for p in game.players] == [20, 20, 16]


# Battlefield Scrounger: "Threshold — Put three cards from your graveyard on
# the bottom of your library: This creature gets +3/+3 until end of turn.
# Activate only once each turn and only if there are seven or more cards in
# your graveyard."

_W1G7_PILE = (
    "Island", "Grizzly Bears", "Lightning Bolt", "Hill Giant", "Swamp",
    "Forest", "Giant Growth", "Mountain",
)


def _w1g7_scrounger_table(set_pool, catalog_by_name, cards_in_graveyard):
    island = catalog_by_name["Island"]
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P0", library=[island] * 5,
            graveyard=[catalog_by_name[n] for n in _W1G7_PILE[:cards_in_graveyard]],
        ),
        _W1G7PlayerState(name="P1", library=[island] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    scrounger = _W1G7Permanent(card=set_pool("JUD")["Battlefield Scrounger"])
    game._put_permanent_onto_battlefield(0, scrounger, None)
    _w1g7_resolve(game)
    _w1g7_nosick(scrounger)
    return game, scrounger


def test_w1g7_scrounger_needs_threshold_before_its_cost_is_paid(
    set_pool, catalog_by_name,
):
    """Six cards: refused by the restriction with nothing moved (CR 602.5 — a
    player can't begin to activate an ability that's prohibited, so it is
    asked before the cost)."""
    game, scrounger = _w1g7_scrounger_table(set_pool, catalog_by_name, 6)
    result = game.activate_permanent_ability(0, "Battlefield Scrounger")

    assert not result.supported
    assert "seven or more cards in your graveyard" in result.details
    assert len(game.players[0].graveyard) == 6 and len(game.players[0].library) == 5
    assert scrounger.effective_power == 3


def test_w1g7_scrounger_pays_three_cards_and_resolves_below_threshold(
    set_pool, catalog_by_name,
):
    """Exactly seven: three go to the bottom of the library and the ability
    still resolves at four — the 2022-12-08 ruling ("If activating the ability
    causes that number to fall below seven, the ability still resolves as
    normal"). A seat that names nothing gives up its least valuable cards (the
    three lands), and the ability is then refused a second time this turn."""
    game, scrounger = _w1g7_scrounger_table(set_pool, catalog_by_name, 7)
    result = game.activate_permanent_ability(0, "Battlefield Scrounger")
    assert result.supported, result.details
    _w1g7_resolve(game)

    owner = game.players[0]
    assert (scrounger.effective_power, scrounger.effective_toughness) == (6, 6)
    assert len(owner.graveyard) == 4
    assert sorted(c.name for c in owner.library[5:]) == ["Forest", "Island", "Swamp"]
    again = game.activate_permanent_ability(0, "Battlefield Scrounger")
    assert not again.supported and "once each turn" in again.details


def test_w1g7_scrounger_named_cards_go_down_in_the_order_named(
    set_pool, catalog_by_name,
):
    """The payer names the three on ``cost_graveyard_indices``, and the order
    named is the order they reach the bottom (CR 401.4)."""
    game, _scrounger = _w1g7_scrounger_table(set_pool, catalog_by_name, 8)
    result = game.activate_permanent_ability(
        0, "Battlefield Scrounger", cost_graveyard_indices=[2, 0, 7],
    )
    assert result.supported, result.details

    owner = game.players[0]
    assert [c.name for c in owner.library[5:]] == ["Lightning Bolt", "Island", "Mountain"]
    assert "Lightning Bolt" not in [c.name for c in owner.graveyard]


@_w1g7_pytest.mark.parametrize(
    ("named", "why"),
    [
        ([2, 2, 7], "more than once"),
        ([1, 2, 3, 4], "4 were named"),
        ([9], "no card at graveyard position 9"),
    ],
)
def test_w1g7_scrounger_refuses_a_bad_naming_with_nothing_paid(
    set_pool, catalog_by_name, named, why,
):
    game, _scrounger = _w1g7_scrounger_table(set_pool, catalog_by_name, 8)
    result = game.activate_permanent_ability(
        0, "Battlefield Scrounger", cost_graveyard_indices=named,
    )

    assert not result.supported and why in result.details
    assert len(game.players[0].graveyard) == 8 and len(game.players[0].library) == 5


def test_w1g7_scrounger_picker_asks_for_three_of_its_own_graveyard(set_pool):
    """The cost is a payment, not a target (CR 601.2b): a picker over the
    payer's own pile, any card, three of them, answered on the cost field."""
    from engine.cost_pickers import spec_is_a_cost
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    card = set_pool("JUD")["Battlefield Scrounger"]
    (ability,) = compile_card_oracle(card).activated_abilities
    spec = derive_activation_spec(ability)
    assert spec == {
        "kind": "graveyard_creature", "own_graveyard_only": True,
        "any_card": True, "library_bottom_cost": True, "count": 3,
    }
    assert spec_is_a_cost(spec)


def test_w1g7_ancestors_chosen_gains_a_life_per_card_in_its_graveyard(
    set_pool, catalog_by_name,
):
    """Drive list: cast out of the hand with five cards in its controller's
    graveyard and three in the opponent's, its entry trigger gains five — its
    own pile, and not counting itself (it is on the battlefield)."""
    island = catalog_by_name["Island"]
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="P0", library=[island] * 5, graveyard=[island] * 5,
                         hand=[set_pool("JUD")["Ancestor's Chosen"]]),
        _W1G7PlayerState(name="P1", library=[island] * 5, graveyard=[island] * 3),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    assert game.cast_from_hand(0, "Ancestor's Chosen").supported
    _w1g7_resolve(game)

    assert [p.life for p in game.players] == [25, 20]

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
