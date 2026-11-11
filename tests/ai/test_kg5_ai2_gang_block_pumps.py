"""A gang block is forecast after the block's own triggers
(``ai_compelled_blocks.gang_block_pumps``).

``ai_declarations._gang_kills`` and ``_kills_back`` read the printed P/T of
every creature in a gang, and flanking — "Whenever this creature becomes
blocked by a creature without flanking, the blocking creature gets -1/-1"
(CR 702.25a) — shrinks **every** blocker in it: two 2/2s on a flanking 2/2
"killed" it, and a 2/1 beside them was counted though it dies before damage
(CR 704.5f). kg5's ``aivalue`` gave the one-on-one fight these pumps
(``block_pair_pumps``) and measured the gang as left.

The gang fires each trigger as ``phases/block_triggers`` does: an attacker's
bare "becomes blocked" once (CR 509.3c), its "becomes blocked by a creature …"
once per blocker the phrase admits (CR 509.3d), "one or more" once (CR
509.3e); each blocker's own "blocks", narrowed by what it blocks (Snarespinner's
"a creature with flying"); "for each creature blocking it" counts the gang,
"beyond the first" (Johtull Wurm) one less. The pair's reading is the
one-member case, and the last two were wrong there too.

The census fights, against the engine's combat, every shipped creature pumped
by its own block — as an attacker into gangs of vanilla blockers, and as a
blocker in a gang beside a vanilla 1/1 — and holds both forecasts to it.
Validated backwards: with the gang's pumps read as nothing (the base's
reading) 273 of the 691 fights' kills were forecast wrong and 351 forecast
fewer losses than the defender took.
"""

from __future__ import annotations

from functools import lru_cache
from itertools import combinations_with_replacement

import pytest

from engine import ai_declarations, faces
from engine.ai_combat import choose_combat_damage_announcement
from engine.ai_compelled_blocks import (_BLOCKED_PUMP_CONDITIONS, _plain_steps,
                                        gang_block_pumps)
from engine.ai_declarations import choose_combat_blockers
from engine.ai_standing import permanent_worth
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_creature_card, _nosick, drive_combat, stock_libraries

SIZES = ((1, 1), (2, 2), (3, 3), (2, 1), (1, 3))
GANGS = (*combinations_with_replacement(SIZES, 2), ((1, 1),) * 3, ((2, 2),) * 3)


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


@lru_cache(maxsize=None)
def _vanilla(power: int, toughness: int):
    return _mk_creature_card(f"Vanilla {power}/{toughness}", power, toughness)


def _pumped_by(conditions) -> list:
    found = []
    cards = sorted(_catalog().values(), key=lambda card: card.name)
    for unit in faces.compilation_units(cards):
        if "Creature" not in (unit.type_line or ""):
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        if any(
            trigger.condition.kind in conditions
            and any(step.kind in ("pump_self", "pump_block_pair") for step in _plain_steps(trigger.instruction))
            for trigger in program.triggered_abilities
        ):
            found.append(unit)
    return found


def _table(attacker_card, blocker_cards):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    stock_libraries(game)
    attacker = Permanent(card=attacker_card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    _nosick(attacker)
    members = []
    for card in blocker_cards:
        member = Permanent(card=card)
        game._put_permanent_onto_battlefield(1, member, None)
        members.append(_nosick(member))
    game.check_state_based_actions()
    return game, attacker, members


def _attack(game, attacker) -> bool:
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(0, [game.battlefield_index_of(attacker)], defending_player_index=1)
    if not ok:
        return False
    game.advance_combat_phase()
    return game.current_step == "declare_blockers"


def _finish_combat(game) -> None:
    """The engine's combat to its end, the attacker's division of its damage
    among a gang answered as the simulator answers it
    (``ai_combat.choose_combat_damage_announcement``)."""
    for _ in range(4):
        try:
            drive_combat(game)
            return
        except AssertionError as stuck:
            if "combat damage assignment" not in str(stuck):
                raise
            ok, why = game.resolve_combat_damage(0, **choose_combat_damage_announcement(game))
            assert ok, why


def _fought(attacker_card, blocker_cards):
    game, attacker, members = _table(attacker_card, blocker_cards)
    if not game.can_attack(attacker, 1) or not all(
        game._can_block_attacker(member, attacker) for member in members
    ):
        return None
    if not _attack(game, attacker) or not all(
        game.is_on_battlefield(permanent) for permanent in (attacker, *members)
    ):
        return None
    # Asked where the defender asks it: the attack declared and its own
    # triggers resolved, the blocks still to come.
    kills = ai_declarations._gang_kills(game, attacker, members)
    worth = {id(member): permanent_worth(member, now=False) for member in members}
    back = sum(worth[id(member)] for member in ai_declarations._kills_back(game, attacker, members))
    at = game.battlefield_index_of(attacker)
    ok, _why = game.declare_blockers(1, {game.battlefield_index_of(member): at for member in members})
    if not ok:
        return None
    _finish_combat(game)
    lost = sum(worth[id(member)] for member in members if not game.is_on_battlefield(member))
    return kills, not game.is_on_battlefield(attacker), back, lost


def test_every_gang_with_a_block_pump_is_forecast_as_the_engine_fights():
    """``_gang_kills`` is the engine's combat, and ``_kills_back`` — the
    defender's worst case, CR 510.1c leaving the division to the attacker —
    never forecasts less than the division the simulator makes took."""
    attackers = _pumped_by(_BLOCKED_PUMP_CONDITIONS)
    blockers = _pumped_by({"creature_blocks"})
    names = {card.name for card in (*attackers, *blockers)}
    assert len(attackers) >= 30 and len(blockers) >= 5, sorted(names)
    assert {"Femeref Knight", "Johtull Wurm", "Elvish Berserker", "Snarespinner"} <= names
    fought, wrong = 0, []
    fights = [(card, [_vanilla(*size) for size in gang]) for card in attackers for gang in GANGS]
    fights += [
        (_vanilla(*size), [card, _vanilla(1, 1)]) for card in blockers for size in SIZES
    ]
    for attacker_card, gang in fights:
        result = _fought(attacker_card, gang)
        if result is None:
            continue
        fought += 1
        kills, died, back, lost = result
        if kills != died or back + 1e-9 < lost:
            wrong.append((attacker_card.name, [card.name for card in gang], *result))
    assert fought >= 600, fought
    assert not wrong, wrong[:20]


def test_flanking_shrinks_every_creature_in_the_gang():
    """The reading itself: a flanker's -1/-1 lands on each blocker, Pygmy
    Troll's +1/+1 once per blocker, and a lone blocker reads as the pair."""
    game, knight, members = _table(_catalog()["Femeref Knight"], [_vanilla(2, 2), _vanilla(2, 1)])
    pumps = gang_block_pumps(game, knight, members)
    assert [pumps[id(member)] for member in members] == [(-1, -1), (-1, -1)]
    assert pumps[id(knight)] == (0, 0)
    game, troll, members = _table(_catalog()["Pygmy Troll"], [_vanilla(1, 1), _vanilla(1, 1)])
    assert gang_block_pumps(game, troll, members)[id(troll)] == (2, 2)
    assert gang_block_pumps(game, troll, members[:1])[id(troll)] == (1, 1)


@pytest.mark.parametrize("gang", [False, True])
def test_the_ai_does_not_gang_a_flanker_with_creatures_its_flanking_kills(gang):
    """A Femeref Knight (2/2, flanking) attacks into Grizzly Bears and
    Savannah Lions (2/1). Each alone loses, and together they deal the
    Knight 1: the Lions dies to flanking before damage and the Bears is a
    1/1. On the base the defender's chooser read them as 2/2 and 2/1, ganged
    the Knight and lost both for nothing; now it keeps them home and takes
    the 2. With a third, a Hill Giant (3/3, a 2/2 once flanked), the gang
    of Giant and Bears does kill it, and that block is still made."""
    names = ["Grizzly Bears", "Savannah Lions"] + (["Hill Giant"] if gang else [])
    game, knight, members = _table(_catalog()["Femeref Knight"], [_catalog()[n] for n in names])
    assert _attack(game, knight)
    blocks = choose_combat_blockers(game, 1)
    blockers = sorted(game.permanent_at(1, slot).card.name for slot in blocks)
    ok, why = game.declare_blockers(1, blocks)
    assert ok, why
    _finish_combat(game)
    standing = sorted(permanent.card.name for permanent in game.controlled_by(1))
    if not gang:
        assert blockers == [], game.log[-8:]
        assert standing == ["Grizzly Bears", "Savannah Lions"]
        assert game.players[1].life == 18
        assert game.is_on_battlefield(knight)
    else:
        assert "Savannah Lions" not in blockers, (blockers, game.log[-10:])
        assert "Hill Giant" in blockers, (blockers, game.log[-10:])
        assert not game.is_on_battlefield(knight), game.log[-10:]
        assert game.players[1].life == 20
