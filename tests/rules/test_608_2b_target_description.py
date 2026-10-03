"""CR 608.2b re-checks a target's printed **description**, not just its presence.

"If the spell or ability specifies targets, it checks whether the targets are
still legal. A target that's no longer in the zone it was in when it was
targeted is illegal. Other changes to the game state may cause a target to no
longer be legal; for example, its characteristics may have changed …"

``legality.illegal_targets_refusal`` asked only the first half: is the target
still on the battlefield, and still targetable. A target that stayed but stopped
answering what the spell printed — "nonblack", "you control", "attacking",
"blocking", "creature" — was legal to it, so the spell resolved:

* the handler's own resolver usually declined the id, so the *targeted*
  sentence did nothing — and every sentence after it ran anyway (Sever Soul
  gained its life, Vendetta and Reckless Spite cost theirs, Dregs of Sorrow drew
  its card);
* where the handler did not re-check, the effect landed on the now-illegal
  target (Spinning Darkness dealt its damage to the black creature);
* and where the resolver declined the id and then **fell through to a scan**,
  the effect landed on a permanent nobody named (Ritual of the Machine stole
  the creature beside its recoloured target; Righteousness pumped a different
  blocker; Feat of Resistance shielded another of its caster's creatures).

The gate now asks the announcement's own question again —
``Game._described_cast_target_slots``, the enumeration ``cast_target_refusal``
checks a named target against — so CR 601.2c and CR 608.2b are one predicate.
Census (``scratch/w2g2/census_608.py``): 280 shipped-and-measured instants and
sorceries cast at a legal target, 305 (spell, change) pairs that made the
target illegal while leaving it on the battlefield and targetable. Pre-fix: 130
spells did something, 88 did nothing by luck of their handler, 0 were countered
by the rule. After: 218 countered by the rule, 0 acting, and no control run or
description-preserving change countered.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.control import change_control
from engine.layer_bridge import SET_CARD_TYPES
from engine.models import Permanent
from engine.pt import add_pt_modifier
from tests.helpers import resolve_stack

_GATE = "every target is illegal (608.2b)"


def _w2g2_perm(card) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w2g2_table(spell, *, mine=(), theirs=()):
    game = Game(players=[
        PlayerState(name="P0", hand=[spell], battlefield=list(mine)),
        PlayerState(name="P1", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _w2g2_cast(game, spell, *targets, **kwargs):
    queued = game.queue_from_hand(
        0, spell.name,
        target_player_index=game.controller_index_of(targets[0]),
        target_permanent_ids=[t.permanent_id for t in targets],
        **kwargs,
    )
    assert queued.supported, queued.details
    return queued


def _w2g2_countered(game, spell) -> bool:
    return (
        any(_GATE in line for line in game.log)
        and spell.name in [c.name for c in game.players[0].graveyard]
    )


@pytest.mark.cr("608.2b")
def test_sever_soul_whose_target_turned_black_is_countered_and_gains_nothing(catalog_by_name):
    """"Destroy target nonblack creature. It can't be regenerated. You gain
    life equal to its toughness." The life is part of a spell that has no
    legal target left, so it is never gained (CR 608.2b's own Sorin's Thirst
    example, the other way up)."""
    spell = catalog_by_name["Sever Soul"]
    named = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    game = _w2g2_table(spell, theirs=[named])
    _w2g2_cast(game, spell, named)

    named.metadata["color_override"] = ("B",)
    resolve_stack(game)

    assert game.is_on_battlefield(named)
    assert game.players[0].life == 20, game.log
    assert _w2g2_countered(game, spell), game.log


@pytest.mark.cr("608.2b")
def test_spinning_darkness_deals_no_damage_to_a_target_that_turned_black(catalog_by_name):
    """The handler-less half: the damage step never re-read "nonblack", so the
    now-illegal creature took 3 and the caster gained 3."""
    spell = catalog_by_name["Spinning Darkness"]
    named = _w2g2_perm(catalog_by_name["Hill Giant"])
    game = _w2g2_table(spell, theirs=[named])
    _w2g2_cast(game, spell, named)

    named.metadata["color_override"] = ("B",)
    resolve_stack(game)

    assert named.damage_marked == 0, game.log
    assert game.players[0].life == 20, game.log
    assert _w2g2_countered(game, spell), game.log


@pytest.mark.cr("608.2b", "601.2c")
def test_ritual_of_the_machine_steals_no_bystander_when_its_target_turns_black(catalog_by_name):
    """The fall-through: the steal's resolver refused the recoloured id and
    scanned on to the next creature on that battlefield. The additional cost
    stays paid — it was paid as the spell was cast (CR 601.2h)."""
    spell = catalog_by_name["Ritual of the Machine"]
    fodder = _w2g2_perm(catalog_by_name["Scathe Zombies"])
    named = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    bystander = _w2g2_perm(catalog_by_name["Hill Giant"])
    game = _w2g2_table(spell, mine=[fodder], theirs=[named, bystander])
    _w2g2_cast(game, spell, named)
    assert not game.is_on_battlefield(fodder), "the additional cost was paid"

    named.metadata["color_override"] = ("B",)
    resolve_stack(game)

    assert game.controller_index_of(named) == 1, game.log
    assert game.controller_index_of(bystander) == 1, "a creature nobody named was stolen"
    assert _w2g2_countered(game, spell), game.log


@pytest.mark.cr("608.2b")
def test_a_you_control_target_that_changed_hands_is_illegal(catalog_by_name):
    """"Target creature you control gains protection…" (Feat of Resistance)
    cast at the caster's own creature, which an opponent then takes. It is no
    longer a creature the caster controls; the spell does nothing — not to the
    target, and not to the caster's other creature the scan used to find."""
    spell = catalog_by_name["Feat of Resistance"]
    named = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    other = _w2g2_perm(catalog_by_name["Hill Giant"])
    game = _w2g2_table(spell, mine=[named, other])
    _w2g2_cast(game, spell, named)

    change_control(named, 1, source="test")
    game._sync_control()
    resolve_stack(game)

    assert (other.effective_power, named.effective_power) == (3, 2), game.log
    assert _w2g2_countered(game, spell), game.log


@pytest.mark.cr("608.2b")
def test_a_creature_target_that_stopped_being_a_creature_is_illegal(catalog_by_name):
    """The largest row of the census: "target creature" whose target became a
    non-creature permanent (an animated land that stopped, an Opal creature
    that turned back). Swords to Plowshares exiled nothing and gained nobody
    life only because its handler re-checked; the gate now says why."""
    spell = catalog_by_name["Swords to Plowshares"]
    named = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    bystander = _w2g2_perm(catalog_by_name["Hill Giant"])
    game = _w2g2_table(spell, theirs=[named, bystander])
    _w2g2_cast(game, spell, named)

    named.metadata[SET_CARD_TYPES] = {
        "card_types": ["enchantment"], "timestamp": 10**6, "source": "test",
    }
    resolve_stack(game)

    assert game.is_on_battlefield(named) and game.is_on_battlefield(bystander), game.log
    assert game.players[1].life == 20, game.log
    assert _w2g2_countered(game, spell), game.log


@pytest.mark.cr("608.2b")
def test_dregs_of_sorrow_whose_only_target_turned_black_draws_nothing(catalog_by_name):
    """"Destroy X target nonblack creatures. Draw X cards." With X = 1 and that
    one creature now black, there is no legal target and no draw."""
    spell = catalog_by_name["Dregs of Sorrow"]
    named = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    game = _w2g2_table(spell, theirs=[named])
    game.players[0].library = [catalog_by_name["Island"]] * 3
    _w2g2_cast(game, spell, named, x_value=1)

    named.metadata["color_override"] = ("B",)
    resolve_stack(game)

    assert len(game.players[0].hand) == 0, game.log
    assert len(game.players[0].library) == 3, game.log
    assert _w2g2_countered(game, spell), game.log


@pytest.mark.cr("608.2b")
def test_topple_whose_target_was_overtaken_is_countered_by_the_rule(set_pool):
    """Nemesis' Topple: "Exile target creature with the greatest power among
    creatures on the battlefield." W1G4 made the exile handler refuse an
    overtaken target; the rule that says so is the gate, which now counters the
    spell before the handler is reached."""
    spell = set_pool("NEM")["Topple"]
    target = _w2g2_perm(set_pool("LEA")["Serra Angel"])
    other = _w2g2_perm(set_pool("LEA")["Hill Giant"])
    game = _w2g2_table(spell, theirs=[target, other])
    _w2g2_cast(game, spell, target)

    add_pt_modifier(other, 3, 0)
    resolve_stack(game)

    assert game.is_on_battlefield(target) and game.is_on_battlefield(other)
    assert game.players[1].exile == []
    assert _w2g2_countered(game, spell), game.log


@pytest.mark.cr("608.2b")
def test_one_illegal_target_of_two_leaves_the_spell_resolving_for_the_other(catalog_by_name):
    """CR 608.2b's last sentences: the spell resolves while **any** target is
    legal, and the illegal one is not affected. "Destroy two target nonblack
    creatures. You lose 5 life." (Reckless Spite): one turns black, the other
    is destroyed, and the life is lost."""
    spell = catalog_by_name["Reckless Spite"]
    first = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    second = _w2g2_perm(catalog_by_name["Hill Giant"])
    game = _w2g2_table(spell, theirs=[first, second])
    _w2g2_cast(game, spell, first, second)

    first.metadata["color_override"] = ("B",)
    resolve_stack(game)

    assert game.is_on_battlefield(first), "the illegal target is left alone"
    assert not game.is_on_battlefield(second), game.log
    assert game.players[0].life == 15, game.log
    assert not any(_GATE in line for line in game.log), game.log


@pytest.mark.cr("608.2b")
def test_a_change_the_description_does_not_mention_leaves_the_target_legal(catalog_by_name):
    """The wrong-"yes" direction: a Terror target that became *tapped* or
    gained power is still a nonartifact, nonblack creature, and is destroyed
    exactly as before."""
    spell = catalog_by_name["Terror"]
    named = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    game = _w2g2_table(spell, theirs=[named])
    _w2g2_cast(game, spell, named)

    named.tapped = True
    add_pt_modifier(named, 3, 3)
    resolve_stack(game)

    assert not game.is_on_battlefield(named), game.log
    assert not any(_GATE in line for line in game.log), game.log


def _w2g2_refused(game, spell, target) -> bool:
    queued = game.queue_from_hand(
        0, spell.name, target_player_index=game.controller_index_of(target),
        target_permanent_ids=[target.permanent_id],
    )
    return not queued.supported and not game.stack


# The other end of the same predicate. CR 608.2b can only be as narrow as the
# description it re-asks, and for twenty shipped spells that description — the
# derived cast spec — was wider than the card: a head noun the permanent picker
# cannot name ("target enchantment", "artifact, creature, or land"), a P/T bound,
# "you don't control". Each was announceable at a target the card excludes
# (CR 601.2c), and so was never found illegal at resolution either.


@pytest.mark.cr("601.2c", "115.1a")
@pytest.mark.parametrize(("spell_name", "target_name", "seat"), [
    # "Destroy target enchantment. You gain 4 life." — cast at a creature it
    # destroyed nothing and gained the life.
    ("Serene Offering", "Hill Giant", 1),
    # "Destroy target artifact, creature, or land. Aftershock deals 3 damage to
    # you." — cast at an enchantment it dealt its caster 3 for nothing.
    ("Aftershock", "Bad Moon", 1),
    # "Exile target creature with power 2 or less. Its controller gains 4 life."
    ("Last Breath", "Hill Giant", 1),
    # "Untap target creature you don't control. That creature blocks this turn
    # if able. Draw a card." — at the caster's own creature it still drew.
    ("Provoke", "Grizzly Bears", 0),
])
def test_a_target_outside_the_printed_description_is_not_announceable(
    catalog_by_name, spell_name, target_name, seat,
):
    spell = catalog_by_name[spell_name]
    target = _w2g2_perm(catalog_by_name[target_name])
    boards = {0: [], 1: []}
    boards[seat].append(target)
    game = _w2g2_table(spell, mine=boards[0], theirs=boards[1])

    assert _w2g2_refused(game, spell, target), game.log
    assert game.players[0].life == 20 and spell in game.players[0].hand


@pytest.mark.cr("601.2c", "613.1d")
def test_a_creature_made_an_artifact_is_an_artifact_target(catalog_by_name):
    """"That creature becomes an artifact in addition to its other types."
    The picker read the printed type line, so a Bear made an artifact (Xenic
    Poltergeist, Ashnod's Transmogrant) was never a legal "target artifact"."""
    from engine.layer_bridge import GAINED_TYPES

    spell = catalog_by_name["Shatter"]
    bear = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    bear.metadata[GAINED_TYPES] = [{"card_types": ["artifact"], "source": "test"}]
    game = _w2g2_table(spell, theirs=[bear])

    _w2g2_cast(game, spell, bear)
    resolve_stack(game)

    assert not game.is_on_battlefield(bear), game.log


@pytest.mark.cr("608.2b", "613.1d")
def test_an_artifact_target_that_stopped_being_an_artifact_is_illegal(catalog_by_name):
    """The same layer-4 read at the other end: Crumble ("Destroy target
    artifact. It can't be regenerated. That artifact's controller gains life
    equal to its mana value.") whose target stopped being an artifact in
    response is countered, not resolved for its life."""
    spell = catalog_by_name["Crumble"]
    ring = _w2g2_perm(catalog_by_name["Sol Ring"])
    game = _w2g2_table(spell, theirs=[ring])
    _w2g2_cast(game, spell, ring)

    ring.metadata[SET_CARD_TYPES] = {
        "card_types": ["enchantment"], "timestamp": 10**6, "source": "test",
    }
    resolve_stack(game)

    assert game.is_on_battlefield(ring)
    assert game.players[1].life == 20, game.log
    assert _w2g2_countered(game, spell), game.log


@pytest.mark.cr("608.2b", "506.4")
def test_a_blocking_target_removed_from_combat_is_illegal(catalog_by_name):
    """"Target blocking creature gets +7/+7 until end of turn." (Righteousness.)
    A blocker removed from combat in response is no longer a blocking
    creature; the pump went to the *other* blocker on that side."""
    spell = catalog_by_name["Righteousness"]
    attacker_a = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    attacker_b = _w2g2_perm(catalog_by_name["Hill Giant"])
    blocker = _w2g2_perm(catalog_by_name["Grizzly Bears"])
    wall = _w2g2_perm(catalog_by_name["Wall of Stone"])
    game = Game(players=[
        PlayerState(name="P0", hand=[spell], battlefield=[blocker, wall]),
        PlayerState(name="P1", battlefield=[attacker_a, attacker_b]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0, 1], defending_player_index=0)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {0: 0, 1: 1})[0]
    _w2g2_cast(game, spell, blocker)

    game._remove_blocker_from_combat(0, game.battlefield_index_of(blocker))
    resolve_stack(game)

    assert blocker.effective_power == 2 and wall.effective_power == 0, game.log
    assert _w2g2_countered(game, spell), game.log
