"""What object a resolving ability deals its damage **as** — CR 120.7.

CR 608.2h states the rule in one sentence: "If an ability states that an object
does something, it's the object as it exists — or as it most recently existed —
that does it, **not the ability**." CR 120.7 then makes that object the source
of the damage, and CR 113.7a is why the ability outliving its source changes
nothing.

Twelve call sites in ``engine/handlers/damage.py`` passed ``context.card``
instead: the card *as printed*, one immutable object per card, handed out once
per copy by the deck builder, shared by every copy in the process and controlled
by nobody. Nothing crashed and no ability went missing — the damage was dealt,
in the right amount, to the right permanents. What was wrong is everything that
asks the source *what it is*: lifelink (CR 702.15b) reads a keyword off it, the
damage ledger records it by id, a "deals damage" trigger compares it by
identity, and the source's own record of what it has damaged hangs on it.

Twenty shipped permanents reached those sites, across four handlers.

Every test here is behavioural rather than a claim about a compiled program:
``oracle_diff`` is blind to this change by construction, because no program
moved.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from engine import PlayerState
from engine.damage_events import DAMAGED_THIS_GAME
from engine.game import Game
from engine.models import Permanent

from tests.helpers import _mk_creature_card, _nosick, resolve_stack


def _w3g5_lifelinking(card):
    """*card* as printed, plus lifelink — the instrument most tests below use.

    A granted keyword is the cheapest observable for "which object dealt this":
    CR 702.15b reads it off the *source*, and ``lifelink_life_gained`` answers 0
    for anything with no ``has_keyword`` at all, which is every
    ``CardDefinition``. So the life total says which object the engine handed to
    the damage seam.
    """
    return replace(card, keywords=tuple(card.keywords) + ("lifelink",))


def _w3g5_ready(card):
    return Permanent(card=card)


def _w3g5_board(dealer, victims=(("Bear", 2, 2),), allies=()):
    """A two-seat board where every permanent *entered* rather than being
    dropped into a battlefield list.

    That matters here and not only for tidiness: ``base_controller_index`` is
    stamped on entry (CR 613.1's starting point) and is the only way to answer
    "whose was it" for a source that has since left — which is precisely
    Shard Phoenix's case below.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    p1, p2 = game.players
    game._put_permanent_onto_battlefield(0, dealer, None)
    _nosick(dealer)
    for ally in allies:
        game._put_permanent_onto_battlefield(0, Permanent(card=_mk_creature_card(*ally)), None)
    for victim in victims:
        game._put_permanent_onto_battlefield(1, Permanent(card=_mk_creature_card(*victim)), None)
    resolve_stack(game)
    game.log.clear()
    game.damage_ledger.clear()
    return game, p1, p2


@pytest.mark.cr("120.7", "702.15b")
def test_an_activated_sweep_deals_as_the_permanent_so_lifelink_gains(set_pool):
    """Subterranean Spirit: "{T}: This creature deals 1 damage to each creature
    without flying."

    Two creatures are dealt to — the opponent's Bear and the Spirit itself,
    which the printed line does not exclude — so a lifelinking Spirit gains 2.
    Dealing as the printed card gained nothing at all, because a card has no
    keywords to read.
    """
    spirit = _w3g5_ready(_w3g5_lifelinking(set_pool("MIR")["Subterranean Spirit"]))
    game, p1, p2 = _w3g5_board(spirit)
    before = p1.life

    assert game.activate_permanent_ability(0, "Subterranean Spirit").supported
    resolve_stack(game)

    assert p2.battlefield[0].damage_marked == 1
    assert spirit.damage_marked == 1
    assert p1.life == before + 2


@pytest.mark.cr("120.7")
def test_the_damage_ledger_records_the_permanent_not_the_card(set_pool):
    """The engine's own record of who dealt what (``engine/damage_ledger.py``).

    ``source_permanent_id`` is ``getattr(source, "permanent_id", None)``, so a
    card-sourced event recorded None for every point one of these swept — which
    is the same hole "a source you control" and "damage dealt by a creature"
    read through.
    """
    spirit = _w3g5_ready(set_pool("MIR")["Subterranean Spirit"])
    game, _p1, _p2 = _w3g5_board(spirit)

    game.activate_permanent_ability(0, "Subterranean Spirit")
    resolve_stack(game)

    entries = game.damage_ledger.entries
    assert entries, "the sweep recorded something"
    assert {entry.source_name for entry in entries} == {"Subterranean Spirit"}
    assert {entry.source_permanent_id for entry in entries} == {spirit.permanent_id}


@pytest.mark.cr("120.7", "109.5")
def test_a_sorcery_still_deals_as_its_printed_card(set_pool):
    """The other half of the same rule, and the reason the fix is a *fallback*
    rather than a replacement: a **spell** is its own source (CR 109.5) and has
    no permanent, which is exactly what ``source_permanent is None`` says.

    Pyroclasm's ledger entry names the card and no permanent, before the change
    and after it.
    """
    pool = set_pool("ICE")
    p1 = PlayerState(name="P1", hand=[pool["Pyroclasm"]])
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=_mk_creature_card("Bear", 2, 2))]
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Pyroclasm")
    resolve_stack(game)

    entry = game.damage_ledger.entries[-1]
    assert entry.source_name == "Pyroclasm"
    assert entry.source_permanent_id is None


@pytest.mark.cr("120.7", "603.2")
def test_an_upkeep_trigger_sweeps_as_the_creature_whose_ability_it_is(set_pool):
    """Cinder Giant: "At the beginning of your upkeep, this creature deals 2
    damage to each other creature you control."

    A triggered ability, so the object that "does something" is the permanent
    the trigger fired from — which is what makes the Giant's own record of what
    it has damaged exist at all (``DAMAGED_THIS_GAME``, the record The Fallen
    reads).
    """
    giant = _w3g5_ready(set_pool("WTH")["Cinder Giant"])
    game, _p1, _p2 = _w3g5_board(giant, victims=(), allies=[("Pal", 3, 3)])

    game.resolve_upkeep(0)
    resolve_stack(game)

    record = giant.metadata.get(DAMAGED_THIS_GAME) or {}
    assert record.get("permanents"), "the Giant remembers what it burned"
    assert game.damage_ledger.entries[-1].source_permanent_id == giant.permanent_id


@pytest.mark.cr("120.7", "608.2h", "702.15b")
def test_a_source_sacrificed_to_pay_for_its_own_ability_still_deals_as_itself(set_pool):
    """Shard Phoenix: "Sacrifice this creature: It deals 2 damage to each
    creature without flying."

    The source is gone before the ability resolves, which is CR 608.2h's last
    known information — the detached ``Permanent``, not the printed card. The
    life gained says the keyword was still read off it.
    """
    phoenix = _w3g5_ready(_w3g5_lifelinking(set_pool("STH")["Shard Phoenix"]))
    game, p1, p2 = _w3g5_board(phoenix, victims=[("Ox", 3, 3)])
    before = p1.life

    assert game.activate_permanent_ability(
        0, "Shard Phoenix", ability_index=0
    ).supported
    resolve_stack(game)

    assert p2.battlefield[0].damage_marked == 2
    assert p1.life == before + 2
    assert game.damage_ledger.entries[-1].source_permanent_id == phoenix.permanent_id


@pytest.mark.cr("120.7", "702.15b")
def test_the_creature_and_player_sweep_deals_as_the_permanent_too(set_pool):
    """Pestilence: "{B}: This enchantment deals 1 damage to each creature and
    each player."

    A different handler from the one this round was briefed on
    (``deal_damage_each_creature_and_player``, shared with Earthquake and
    Hurricane), reached by seven more shipped permanents. Three events —
    both faces and the Bear — so a lifelinking Pestilence gains 3 while its
    controller takes 1.
    """
    pestilence = _w3g5_ready(_w3g5_lifelinking(set_pool("LEA")["Pestilence"]))
    game, p1, p2 = _w3g5_board(pestilence)
    before = p1.life

    assert game.activate_permanent_ability(0, "Pestilence").supported
    resolve_stack(game)

    assert p1.life == before - 1 + 3, "one point taken, three gained"
    assert p2.life == 19


@pytest.mark.cr("120.7")
def test_the_flying_sweep_deals_as_the_permanent(set_pool):
    """Whirling Catapult's is ``hurricane_damage`` — the third of the four
    handlers this round routed, reached by a printed sentence that shares
    Pestilence's sweep underneath.
    """
    catapult = _w3g5_ready(set_pool("ALL")["Whirling Catapult"])
    game, p1, p2 = _w3g5_board(catapult, victims=[("Flier", 2, 2)])
    p2.battlefield[0].card = replace(p2.battlefield[0].card, keywords=("flying",))
    p1.library = [set_pool("ALL")["Carrier Pigeons"]] * 2

    assert game.activate_permanent_ability(0, "Whirling Catapult").supported
    resolve_stack(game)

    entries = game.damage_ledger.entries
    assert entries, "the Catapult dealt something"
    assert {entry.source_permanent_id for entry in entries} == {catapult.permanent_id}
