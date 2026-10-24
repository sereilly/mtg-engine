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
