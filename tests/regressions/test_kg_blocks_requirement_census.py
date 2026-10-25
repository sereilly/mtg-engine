"""Round kg/blocks: CR 509.1c's maximisation, censused over every requirement
channel against every restriction channel the pool can put on a board.

    509.1c … If the number of requirements that are being obeyed is fewer than
    the maximum possible number of requirements that could be obeyed without
    disobeying any restrictions, the declaration of blockers is illegal. If a
    creature can't block unless a player pays a cost, that player is not
    required to pay that cost …

Each scenario is a small board, the requirements on it written out **by hand**
— the census's own reading of the rule, never the engine's enumeration — and
every declaration the board allows is put to ``declare_blockers``. The answer
expected for each is computed here: a declaration is legal when it disobeys no
restriction (asked of the engine's CR 509.1b predicates, which are not what is
under test) and obeys at least as many of the written requirements as the best
declaration that disobeys none and pays no cost. The engine must accept exactly
those, refuse every other one, and its AI must propose one of them.

Backwards: on the tree before this round (``c42aec75``) the gate is wrong on
seventeen of the thirty-five boards and the AI on sixteen. Three ways: no legal
declaration at all (three Watchdogs under Caverns of Despair — none of the
eight accepted — and a Lured Stalking Tiger, Invasion Plans beside a lone Okk);
a declaration under the maximum accepted (CR 509.1c's own example, the menace
attacker, where "neither blocks" was taken; a Lured attacker's blocker blocking
the *other* attacker); and two requirements weighed as one (two Lures on one
attacker, a Lure on Marble Priest whose printed narrowing hid the Aura's).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import pytest

from engine import Game, PlayerState
from engine.ai_combat import CombatOutcome, declare_ai_blockers
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.combat_permissions import (CAN_BLOCK_ANY_NUMBER_UNTIL_EOT,
                                       MUST_BLOCK_ALL_UNTIL_EOT,
                                       MUST_BLOCK_ATTACKERS_UNTIL_EOT,
                                       MUST_BLOCK_UNTIL_EOT)
from engine.models import Permanent
from tests.helpers import _mk_card, _mk_creature_card, _nosick


_CATALOG: dict = {}


def _card(name):
    if not _CATALOG:
        _CATALOG.update({card.name: card for card in load_catalog()})
    return _CATALOG[name]


def _bear(name="Bear", power=2, toughness=2, text=""):
    return _mk_creature_card(name, power, toughness, text)


def _wall():
    return _mk_card("Test Wall", "Creature — Wall", "Defender", power=0, toughness=4)


@dataclass
class Scenario:
    """One board. Slots are battlefield order on each side: the attackers first
    on P1's (then its Auras, then its other permanents), the blockers on P2's."""

    name: str
    attackers: list
    blockers: list
    #: Other permanents on P1's battlefield (Caverns of Despair, Heat Wave).
    attacker_side: list = field(default_factory=list)
    #: (aura card, attacker slot) — attached to that attacker, owned by P1.
    auras: list = field(default_factory=list)
    #: (blocker slot, key, value); a callable value is handed the game.
    marks: list = field(default_factory=list)
    #: Cards in P1's graveyard — seven is threshold (Stone-Tongue Basilisk,
    #: Seton's Desire), whose Lure is granted only while it holds.
    graveyard: int = 0
    #: The requirements CR 509.1c counts on this board, with multiplicity:
    #: (blocker slot or None, attacker slot or None).
    requirements: list = field(default_factory=list)
    #: Whether the maximum here is below the number of requirements — the
    #: boards an addition test gets wrong. Asserted, so a scenario that stops
    #: exercising the maximisation says so.
    trade_off: bool = False


def _owed(*attacker_slots):
    def mark(game):
        return [game.players[0].battlefield[slot].permanent_id for slot in attacker_slots]
    return mark


def _scenarios() -> list[Scenario]:
    watchdog = _card("Watchdog")
    caverns = _card("Caverns of Despair")
    dueling = _card("Dueling Grounds")
    plans = _card("Invasion Plans")
    lure = _card("Lure")
    menace = _bear("Menace Brute", 3, 3, "Menace")
    flier = _bear("Sky Raider", 2, 2, "Flying")
    return [
        Scenario(
            "three Watchdogs under Caverns of Despair",
            [_bear("Raider")], [watchdog, watchdog, watchdog], [caverns],
            requirements=[(0, None), (1, None), (2, None)], trade_off=True,
        ),
        Scenario(
            "two Watchdogs, two attackers, Dueling Grounds",
            [_bear("Raider A"), _bear("Raider B")], [watchdog, watchdog], [dueling],
            requirements=[(0, None), (1, None)], trade_off=True,
        ),
        Scenario(
            "CR 509.1c's example: a menace attacker, a Watchdog and a vanilla creature",
            [menace], [watchdog, _bear()],
            requirements=[(0, None)],
        ),
        Scenario(
            "a menace attacker and a lone Watchdog",
            [menace], [watchdog],
            requirements=[(0, None)], trade_off=True,
        ),
        Scenario(
            "Gorilla Berserkers against a Watchdog and two vanilla creatures",
            [_card("Gorilla Berserkers")], [watchdog, _bear("Bear A"), _bear("Bear B")],
            requirements=[(0, None)],
        ),
        Scenario(
            "Gorilla Berserkers against a Watchdog and one vanilla creature",
            [_card("Gorilla Berserkers")], [watchdog, _bear()],
            requirements=[(0, None)], trade_off=True,
        ),
        Scenario(
            "Lure on Stalking Tiger, three able blockers",
            [_card("Stalking Tiger")], [_bear("Bear A"), _bear("Bear B"), _bear("Bear C")],
            auras=[(lure, 0)],
            requirements=[(0, 0), (1, 0), (2, 0)], trade_off=True,
        ),
        Scenario(
            "Lure on one of two attackers: blocking the other disobeys it",
            [_bear("Lured"), _bear("Raider")], [_bear("Bear A"), _bear("Bear B")],
            auras=[(lure, 0)],
            requirements=[(0, 0), (1, 0)],
        ),
        Scenario(
            "two Lured attackers and Two-Headed Giant of Foriys",
            [_bear("Lured A"), _bear("Lured B")], [_card("Two-Headed Giant of Foriys")],
            auras=[(lure, 0), (lure, 1)],
            requirements=[(0, 0), (0, 1)],
        ),
        Scenario(
            "two Lures on one attacker outweigh one Lure on another",
            [_bear("Twice Lured"), _bear("Once Lured")], [_bear()],
            auras=[(lure, 0), (lure, 0), (lure, 1)],
            requirements=[(0, 0), (0, 0), (0, 1)], trade_off=True,
        ),
        Scenario(
            "Lure on Marble Priest: the printed line compels the Wall, the Aura everybody",
            [_card("Marble Priest")], [_wall(), _bear()],
            auras=[(lure, 0)],
            requirements=[(0, 0), (0, 0), (1, 0)],
        ),
        Scenario(
            "Lure on a menace attacker with one able blocker",
            [menace], [_bear()], auras=[(lure, 0)],
            requirements=[(0, 0)], trade_off=True,
        ),
        Scenario(
            "Lure on a menace attacker with two able blockers",
            [menace], [_bear("Bear A"), _bear("Bear B")], auras=[(lure, 0)],
            requirements=[(0, 0), (1, 0)],
        ),
        Scenario(
            "Elvish Bard under Caverns of Despair, three able blockers",
            [_card("Elvish Bard")], [_bear("Bear A"), _bear("Bear B"), _bear("Bear C")],
            [caverns],
            requirements=[(0, 0), (1, 0), (2, 0)], trade_off=True,
        ),
        Scenario(
            "Stone-Tongue Basilisk at threshold under Caverns of Despair",
            [_card("Stone-Tongue Basilisk")],
            [_bear("Bear A"), _bear("Bear B"), _bear("Bear C")], [caverns],
            graveyard=7,
            requirements=[(0, 0), (1, 0), (2, 0)], trade_off=True,
        ),
        Scenario(
            "Stone-Tongue Basilisk short of threshold compels nobody",
            [_card("Stone-Tongue Basilisk")], [_bear("Bear A"), _bear("Bear B")],
            graveyard=6,
        ),
        Scenario(
            "Seton's Desire at threshold on Stalking Tiger",
            [_card("Stalking Tiger")], [_bear("Bear A"), _bear("Bear B")],
            auras=[(_card("Seton's Desire"), 0)], graveyard=7,
            requirements=[(0, 0), (1, 0)], trade_off=True,
        ),
        Scenario(
            "Talruum Piper compels only the flier",
            [_card("Talruum Piper")], [_bear("Sky Bear", 1, 1, "Flying"), _bear()],
            requirements=[(0, 0)],
        ),
        Scenario(
            "Canopy Stalker: one blocker is enough",
            [_card("Canopy Stalker")], [_bear("Bear A"), _bear("Bear B")],
            requirements=[(None, 0)],
        ),
        Scenario(
            "Canopy Stalker under Familiar Ground: no more than one may block it",
            [_card("Canopy Stalker")], [_bear("Bear A"), _bear("Bear B")],
            [_card("Familiar Ground")],
            requirements=[(None, 0)],
        ),
        Scenario(
            "Canopy Stalker and a Watchdog under Dueling Grounds",
            [_card("Canopy Stalker"), _bear("Raider")], [watchdog, _bear()], [dueling],
            requirements=[(None, 0), (0, None)],
        ),
        Scenario(
            "Invasion Plans and a lone Okk",
            [_bear("Raider")], [_card("Okk")], [plans],
            requirements=[(0, None)], trade_off=True,
        ),
        Scenario(
            "Invasion Plans, Okk and a bigger creature",
            [_bear("Raider")], [_card("Okk"), _bear("Giant", 6, 6)], [plans],
            requirements=[(0, None), (1, None)],
        ),
        Scenario(
            "Invasion Plans, Orcish Conscripts and one other creature",
            [_bear("Raider")], [_card("Orcish Conscripts"), _bear()], [plans],
            requirements=[(0, None), (1, None)], trade_off=True,
        ),
        Scenario(
            "Invasion Plans and Mogg Flunkies beside another creature",
            [_bear("Raider")], [_card("Mogg Flunkies"), _bear()], [plans],
            requirements=[(0, None), (1, None)],
        ),
        Scenario(
            "a Watchdog under Invasion Plans outweighs a creature under it alone",
            [_bear("Raider")], [watchdog, _bear()], [plans, dueling],
            requirements=[(0, None), (0, None), (1, None)], trade_off=True,
        ),
        Scenario(
            "Provoke's mark on Hipparion against a 3-power attacker (a cost)",
            [_bear("Ogre", 3, 3)], [_card("Hipparion")],
            marks=[(0, MUST_BLOCK_UNTIL_EOT, True)],
            requirements=[(0, None)], trade_off=True,
        ),
        Scenario(
            "a Watchdog under Heat Wave owes life to block (a cost)",
            [_bear("Raider")], [watchdog], [_card("Heat Wave")],
            requirements=[(0, None)], trade_off=True,
        ),
        Scenario(
            "Provoke's mark on Hollow Warrior (a tap cost)",
            [_bear("Raider")], [_card("Hollow Warrior"), _bear()],
            marks=[(0, MUST_BLOCK_UNTIL_EOT, True)],
            requirements=[(0, None)], trade_off=True,
        ),
        Scenario(
            "Provoke's mark on a creature that can't block",
            [_bear("Raider")], [_bear("Coward", 2, 2, "This creature can't block.")],
            marks=[(0, MUST_BLOCK_UNTIL_EOT, True)],
            requirements=[(0, None)], trade_off=True,
        ),
        Scenario(
            "Provoke's mark on Cloud Sprite: only the flier can be blocked",
            [_bear("Raider"), flier], [_card("Cloud Sprite")],
            marks=[(0, MUST_BLOCK_UNTIL_EOT, True)],
            requirements=[(0, None)],
        ),
        Scenario(
            "Blaze of Glory beside Stalking Tiger and a second blocker",
            [_card("Stalking Tiger"), _bear("Raider")], [_bear("Hero"), _bear("Squire")],
            marks=[
                (0, MUST_BLOCK_ALL_UNTIL_EOT, True),
                (0, CAN_BLOCK_ANY_NUMBER_UNTIL_EOT, True),
            ],
            requirements=[(0, 0), (0, 1)],
        ),
        Scenario(
            "three creatures owing Trumpeting Armodon a block under Caverns of Despair",
            [_bear("Armodon")], [_bear("Bear A"), _bear("Bear B"), _bear("Bear C")],
            [caverns],
            marks=[(slot, MUST_BLOCK_ATTACKERS_UNTIL_EOT, _owed(0)) for slot in range(3)],
            requirements=[(0, 0), (1, 0), (2, 0)], trade_off=True,
        ),
        Scenario(
            "a block owed to a flier the creature cannot block",
            [flier, _bear("Raider")], [_bear()],
            marks=[(0, MUST_BLOCK_ATTACKERS_UNTIL_EOT, _owed(0))],
            requirements=[(0, 0)], trade_off=True,
        ),
        Scenario(
            "a block owed to one attacker and a Watchdog's requirement on one creature",
            [_bear("Armodon"), _bear("Raider")], [watchdog], [dueling],
            marks=[(0, MUST_BLOCK_ATTACKERS_UNTIL_EOT, _owed(0))],
            requirements=[(0, 0), (0, None)],
        ),
    ]


def _board(scenario: Scenario) -> Game:
    """A fresh game at the declare-blockers step, every attacker declared."""
    attackers = [_nosick(Permanent(card=card)) for card in scenario.attackers]
    blockers = [_nosick(Permanent(card=card)) for card in scenario.blockers]
    auras = [(Permanent(card=card), slot) for card, slot in scenario.auras]
    p1 = PlayerState(
        name="P1", battlefield=[*attackers, *(aura for aura, _ in auras)],
        graveyard=[_bear(f"Spent {i}", 1, 1) for i in range(scenario.graveyard)],
    )
    p2 = PlayerState(name="P2", battlefield=blockers)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}
    game._sync_control()
    for aura, slot in auras:
        attach_aura(aura, attackers[slot])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, why = game.declare_attackers(0, list(range(len(attackers))), 1)
    assert ok, (scenario.name, why)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", (scenario.name, game.log[-5:])
    # The board's other permanents arrive once the attack is declared, so a
    # cap that is also an attack cap (Dueling Grounds) does not shape the
    # attack, and an upkeep cost (Heat Wave's) is never asked.
    for card in scenario.attacker_side:
        p1.battlefield.append(Permanent(card=card))
    game._sync_control()
    for slot, key, value in scenario.marks:
        game.players[1].battlefield[slot].metadata[key] = (
            value(game) if callable(value) else value
        )
    return game


def _declarations(game: Game, scenario: Scenario):
    """Every declaration up to each creature's own block ceiling."""
    defender = game.players[1]
    attacker_slots = list(range(len(scenario.attackers)))
    per_blocker = []
    for blocker in defender.battlefield[: len(scenario.blockers)]:
        most = min(game._max_blocks_for(blocker), len(attacker_slots))
        per_blocker.append(
            [()] + [
                combo for size in range(1, most + 1)
                for combo in itertools.combinations(attacker_slots, size)
            ]
        )
    for choice in itertools.product(*per_blocker):
        yield {slot: list(option) for slot, option in enumerate(choice) if option}


def _restriction_legal(game: Game, declaration) -> bool:
    """CR 509.1b and the costs (CR 509.1d), asked of the engine's own
    predicates — the restriction half is not what this census tests."""
    defender = game.players[1]
    attackers = game.players[0]
    blockers = {slot: defender.battlefield[slot] for slot in declaration}
    resolved = {
        a: attackers.battlefield[a] for blocked in declaration.values() for a in blocked
    }
    counts: dict[int, int] = {}
    for slot, blocked in declaration.items():
        blocker = blockers[slot]
        if len(blocked) > game._max_blocks_for(blocker):
            return False
        for a in blocked:
            if not game._can_block_attacker(blocker, resolved[a]):
                return False
            counts[a] = counts.get(a, 0) + 1
    for a, count in counts.items():
        if count < game._minimum_blockers(resolved[a]):
            return False
        ceiling = game._maximum_blockers(resolved[a])
        if ceiling is not None and count > ceiling:
            return False
    if game.block_declaration_refusal(list(blockers.values())) is not None:
        return False
    life = game._block_declaration_life(declaration, blockers, resolved)
    if life and defender.life < life:
        return False
    total, plan = game._block_declaration_mana_plan(1, declaration, blockers, resolved)
    if total and plan is None:
        return False
    if game.declaration_tap_plan(1, list(blockers.values()), "block") is None:
        return False
    return True


def _cost_free(game: Game, declaration) -> bool:
    defender = game.players[1]
    attackers = game.players[0]
    return not any(
        game._owes_a_cost_to_block(defender.battlefield[slot], attackers.battlefield[a])
        for slot, blocked in declaration.items()
        for a in blocked
    )


def _obeyed(requirements, declaration) -> int:
    obeyed = 0
    for blocker, attacker in requirements:
        if blocker is None:
            obeyed += any(attacker in blocked for blocked in declaration.values())
        elif attacker is None:
            obeyed += bool(declaration.get(blocker))
        else:
            obeyed += attacker in (declaration.get(blocker) or ())
    return obeyed


def _expected(scenario: Scenario):
    """(every declaration, the legal ones, the maximum obeyable)."""
    probe = _board(scenario)
    declarations = list(_declarations(probe, scenario))
    restriction_legal = [d for d in declarations if _restriction_legal(probe, d)]
    maximum = max(
        _obeyed(scenario.requirements, d)
        for d in restriction_legal if _cost_free(probe, d)
    )
    legal = [
        d for d in restriction_legal
        if _obeyed(scenario.requirements, d) >= maximum
    ]
    return declarations, legal, maximum


def _key(declaration) -> tuple:
    return tuple(sorted(
        (int(slot), tuple(sorted(blocked if isinstance(blocked, list) else [blocked])))
        for slot, blocked in declaration.items()
    ))


SCENARIOS = _scenarios()


def test_the_census_examines_enough_to_mean_something():
    """The floors: how much the census below looks at. A sweep that examined
    nothing would pass as one that found nothing."""
    assert len(SCENARIOS) >= 35
    trade_offs = [s for s in SCENARIOS if s.trade_off]
    assert len(trade_offs) >= 15
    examined = 0
    for scenario in SCENARIOS:
        declarations, legal, maximum = _expected(scenario)
        examined += len(declarations)
        # Each scenario's label agrees with its board: a trade-off is a board
        # whose maximum is below its count of requirements.
        assert (maximum < len(scenario.requirements)) == scenario.trade_off, scenario.name
        assert legal, scenario.name
    assert examined >= 150


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_the_gate_accepts_exactly_the_declarations_that_obey_the_maximum(scenario):
    declarations, legal, maximum = _expected(scenario)
    legal_keys = {_key(d) for d in legal}
    wrong = []
    for declaration in declarations:
        game = _board(scenario)
        ok, why = game.declare_blockers(
            1, declaration, acting_index=game.block_chooser_index(1)
        )
        if ok != (_key(declaration) in legal_keys):
            wrong.append((declaration, ok, why))
        if ok:
            # Accepted means declared: the blocks the engine now holds are the
            # declaration it was handed.
            assert _key(game.combat_blockers.get(1, {})) == _key(declaration)
    assert not wrong, (scenario.name, maximum, wrong)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_the_ai_proposes_a_declaration_the_gate_accepts(scenario):
    """The AI's half: its first proposal is legal (nothing refused, nothing
    fallen back to), and what it declared obeys the maximum."""
    _declarations_, legal, _maximum = _expected(scenario)
    game = _board(scenario)
    game.interactive_seats = set()
    outcome = CombatOutcome()
    assert declare_ai_blockers(game, 1, outcome=outcome), (scenario.name, game.log[-4:])
    assert outcome.refused_blocks == [], (scenario.name, outcome.refused_blocks)
    assert outcome.silent_blocks == []
    assert _key(game.combat_blockers.get(1, {})) in {_key(d) for d in legal}, (
        scenario.name, game.combat_blockers
    )


def test_the_engine_counts_the_requirements_the_census_writes_down():
    """The enumeration agrees with the census's hand-written count on every
    board — so a channel the engine stopped reading shows here by name rather
    than as a maximum that happens to come out the same."""
    for scenario in SCENARIOS:
        game = _board(scenario)
        found = sorted(
            (r.blocker if r.blocker is not None else -1,
             r.attacker if r.attacker is not None else -1)
            for r in game.block_requirements(1)
        )
        written = sorted(
            (b if b is not None else -1, a if a is not None else -1)
            for b, a in scenario.requirements
        )
        assert found == written, scenario.name
