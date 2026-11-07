"""Pool census: every trigger on a declare-blockers outcome is on the stack
before the active player receives priority in that step (CR 509.2a).

CR 509.1h makes an attacker blocked or unblocked as blockers are declared,
CR 509.1i says the abilities that trigger on blockers being declared trigger
then, and CR 509.2a puts them — and everything else that triggered during
CR 509.1's process — on the stack **before the active player gets
priority**. CR 509.3g says which moment "Whenever [a creature] attacks and
isn't blocked" is about: it "triggers if no creatures are declared as
blockers for that creature".

The block halves ("blocks", "becomes blocked", "blocked by") were fired
inside ``declare_blockers``' own trigger window. The unblocked half was not:
it was fired by the declare-blockers step's *leaving* pass
(``combat_phase.advance_combat_phase``), after the step's priority — so on the
web the AI's and the person's declare-blockers priority came before it and
the step's window resolved it with nobody asked (CR 117.4); and where the
blocks locked with no declaration at all (a defender with no legal block,
auto-skipped) at a table with a person, the same call locked the blocks,
fired the trigger and resolved it in the window, with no priority given.

**The population is derived from the compiled programs**: every printed
trigger whose condition kind names a block (``attacks_unblocked``,
``creature_blocks``, ``creature_becomes_blocked``, ``…_blocks_or_blocked_by``,
the board-wide ``matching_creature_…`` rows). Each card is put where its
trigger answers — the attacker, the blocker, an Aura on either, a permanent
watching both — and each declaration road is driven through the engine's
own entry points: the defender declares no blocks, the defender blocks, and
the defender has no creature (the lock). Every row runs at a table nobody
sits at and at one where both seats are interactive.

A spy records, in order, every trigger of the card pushed onto the stack in
the declare blockers step, every moment a player is given priority there
once the blocks are locked, and every object that resolves. The invariant:
**no block-outcome trigger is pushed after that step's first priority, and
at a table with a person none resolves before it** (the web's priority
exchange is that table's: ``start_priority_window``; at a table nobody sits
at, the step's window is where priority would be).

Measured backwards on the base (``243f72df``), the tree before the fix: 75
late rows across all 27 ``attacks_unblocked`` cards (25 creatures, two Auras)
— the "declares no blocks" road at both tables (55 rows: pushed after the
priority ``declare_blockers`` gives), and the lock road at the interactive
table (20 rows: resolved by the leaving window with no priority given; the
headless lock road fired before its window and was not late). No row of any
other kind was late (145 of 163 cards fired, 350 rows); that half is
``full``-marked, as a guard that the two halves stay together.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura, is_aura_card
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.oracle import compiled_units
from tests.helpers import _mk_creature_card

_ACTIVE, _DEFENDER = 0, 1
_LANDS = ("Plains", "Island", "Swamp", "Mountain", "Forest")
_CATALOG = {card.name: card for card in load_catalog()}


def _block_outcome_population() -> list[tuple[CardDefinition, frozenset, frozenset]]:
    """(card, its block-outcome condition kinds, the printed lines carrying
    them) for every supported permanent whose compiled program triggers on a
    block, derived from the programs rather than from a list of names."""
    rows = []
    for card, program in compiled_units(load_catalog()):
        if not program.supported:
            continue
        triggers = [
            trig for trig in program.triggered_abilities
            if "block" in trig.condition.kind
        ]
        if not triggers:
            continue
        if not any(word in card.type_line for word in (
            "Creature", "Enchantment", "Artifact", "Land",
        )):
            continue
        rows.append((
            card,
            frozenset(trig.condition.kind for trig in triggers),
            frozenset(trig.source_line for trig in triggers),
        ))
    return rows


_POPULATION = _block_outcome_population()


def _vanilla(name: str, power: int, toughness: int, text: str = "") -> CardDefinition:
    return _mk_creature_card(name, power, toughness, text)


#: A blocker that can block a flier (reach) and nothing else about it.
_WALL = _vanilla("Census Wall", 0, 6, "Reach")
_RAIDER = _vanilla("Census Raider", 2, 2)
_FILLER = _vanilla("Census Filler", 1, 1)


def _permanent(card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _game(*, interactive: bool) -> Game:
    players = [PlayerState(name="A"), PlayerState(name="B")]
    for player in players:
        player.library = [_FILLER] * 12
        # "At the beginning of your upkeep, you may discard a card. If you
        # don't, sacrifice this creature" (Lim-Dûl's Paladin).
        player.hand = [_FILLER] * 3
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = _ACTIVE
    if interactive:
        game.interactive_seats = {_ACTIVE, _DEFENDER}
    return game


def _board(card, placement: str, road: str, *, interactive: bool, lands: bool):
    """A game set up so *card* sits where *placement* says, and the slots the
    road declares with: (game, attacker, blocker-or-None)."""
    game = _game(interactive=interactive)
    attacker_side = game.players[_ACTIVE].battlefield
    defender_side = game.players[_DEFENDER].battlefield
    blocker = None
    if placement == "attacker":
        attacker = _permanent(card)
        attacker_side.append(attacker)
    elif placement == "aura_on_attacker":
        attacker = _permanent(_RAIDER)
        aura = _permanent(card)
        attacker_side.extend([attacker, aura])
        attach_aura(aura, attacker)
    elif placement in ("watcher_active", "watcher_defender"):
        attacker = _permanent(_RAIDER)
        attacker_side.append(attacker)
        side = attacker_side if placement == "watcher_active" else defender_side
        side.append(_permanent(card))
    elif placement == "blocker":
        attacker = _permanent(_RAIDER)
        attacker_side.append(attacker)
        blocker = _permanent(card)
    elif placement == "aura_on_blocker":
        attacker = _permanent(_RAIDER)
        attacker_side.append(attacker)
        blocker = _permanent(_WALL)
        aura = _permanent(card)
        defender_side.append(aura)
        attach_aura(aura, blocker)
    else:  # pragma: no cover - the table below names every placement
        raise AssertionError(placement)
    if road != "lock" and blocker is None:
        blocker = _permanent(_WALL)
    if road != "lock":
        defender_side.insert(0, blocker)
    if lands:
        # "…can't attack unless defending player controls an Island" and
        # "When you control no Islands, sacrifice this creature" (Merchant
        # Ship): lands on both sides, for the cards whose attack needs them.
        for side in (attacker_side, defender_side):
            side.extend(_permanent(_CATALOG[name]) for name in _LANDS)
    game._sync_control()
    game._recompute_continuous_effects()
    return game, attacker, blocker


def _placements(card, kinds) -> list[str]:
    """Where the card's trigger can answer: the attacking or blocking creature
    itself, an Aura on either, or a permanent watching the combat."""
    if "Creature" in card.type_line:
        places = []
        if any(k for k in kinds if "block" in k and not k.endswith("_blocks")):
            places.append("attacker")
        if any(k in kinds for k in (
            "creature_blocks", "creature_blocks_or_blocked_by",
            "creature_attacks_or_blocks", "matching_creature_blocks",
            "matching_creature_attacks_or_blocks",
        )):
            places.append("blocker")
        if any(k.startswith("matching_") for k in kinds):
            places += ["watcher_active", "watcher_defender"]
        return places or ["attacker", "blocker"]
    if is_aura_card(card):
        return ["aura_on_attacker", "aura_on_blocker"]
    return ["watcher_active", "watcher_defender"]


def _roads(placement: str) -> list[str]:
    if placement in ("blocker", "aura_on_blocker"):
        return ["block"]
    return ["none", "block", "lock"]


class _Recorder:
    """The order of what happens in the declare blockers step: the card's
    block-outcome triggers pushed, priority given once the blocks are locked,
    and objects resolving."""

    def __init__(self, monkeypatch):
        self.events: list[tuple] = []
        self.on = False
        original_push = Game._stack_push
        original_start = Game.start_priority_window
        original_window = Game._resolve_priority_window
        original_offer = Game.offer_priority
        original_resolve = Game.resolve_top_of_stack
        recorder = self

        def _in_step(game) -> bool:
            return (
                recorder.on and game.current_turn_phase == "combat"
                and game.current_step == "declare_blockers"
            )

        def push(game, item=None, **kwargs):
            pushed = original_push(game, item, **kwargs)
            if pushed is not None and _in_step(game):
                recorder.events.append(("push", pushed))
            return pushed

        def start(game, starting_player_index=None):
            if _in_step(game) and game.combat_blockers_locked:
                recorder.events.append(("priority", "start_priority_window"))
            return original_start(game, starting_player_index)

        def window(game):
            if _in_step(game) and game.combat_blockers_locked:
                recorder.events.append(("priority", "_resolve_priority_window"))
            return original_window(game)

        def offer(game, first=None):
            if _in_step(game) and game.combat_blockers_locked:
                recorder.events.append(("priority", "offer_priority"))
            return original_offer(game, first)

        def resolve(game, pause_for_choices=False):
            top = game.stack[-1] if game.stack else None
            if top is not None and _in_step(game):
                recorder.events.append(("resolve", top))
            return original_resolve(game, pause_for_choices)

        monkeypatch.setattr(Game, "_stack_push", push)
        monkeypatch.setattr(Game, "start_priority_window", start)
        monkeypatch.setattr(Game, "_resolve_priority_window", window)
        monkeypatch.setattr(Game, "offer_priority", offer)
        monkeypatch.setattr(Game, "resolve_top_of_stack", resolve)


def _drain_prompts(game) -> None:
    game.auto_resolve_pending_choices()


def _to_declare_blockers(game, attacker) -> bool:
    game.start_turn(_ACTIVE)
    _drain_prompts(game)
    game._close_current_priority_step()
    for _ in range(4):
        if game.current_step == "declare_attackers":
            break
        game.advance_combat_phase()
        _drain_prompts(game)
    if game.current_step != "declare_attackers" or not game.is_on_battlefield(attacker):
        return False
    slot = game.battlefield_index_of(attacker)
    if not game.declare_attackers(_ACTIVE, [slot])[0]:
        return False
    for _ in range(8):
        _drain_prompts(game)
        if game.current_step != "declare_attackers":
            break
        game.advance_combat_phase()
    return game.current_step == "declare_blockers" and attacker.attacking


def _drive(card, placement, road, *, interactive, recorder) -> list[tuple] | None:
    """One row: the events of its declare blockers step, or None when the
    board could not reach the declaration it names."""
    for lands in (False, True):
        game, attacker, blocker = _board(
            card, placement, road, interactive=interactive, lands=lands,
        )
        if _to_declare_blockers(game, attacker):
            break
    else:
        return None
    recorder.events = []
    recorder.on = True
    try:
        if road == "lock":
            if game._has_any_legal_block(_DEFENDER):
                return None
            game.advance_combat_phase()
        else:
            attacker_slot = game.battlefield_index_of(attacker)
            blocker_slot = (
                game.battlefield_index_of(blocker) if blocker is not None else None
            )
            if attacker_slot is None or (road == "block" and blocker_slot is None):
                return None
            pairs = {blocker_slot: [attacker_slot]} if road == "block" else {}
            if not game.declare_blockers(_DEFENDER, pairs)[0]:
                return None
        for _ in range(8):
            if game.current_step != "declare_blockers" or game.is_game_over():
                break
            _drain_prompts(game)
            game.advance_combat_phase()
    finally:
        recorder.on = False
    return list(recorder.events)


def _late(events, lines, card_name, *, interactive) -> list[str]:
    """What in one row's events breaks CR 509.2a."""
    moments = (
        {"start_priority_window"} if interactive
        else {"start_priority_window", "_resolve_priority_window", "offer_priority"}
    )
    ours = lambda item: (  # noqa: E731
        item.card.name == card_name and (item.ability_text or "") in lines
    )
    faults = []
    given = False
    for kind, value in events:
        if kind == "priority" and value in moments:
            given = True
        elif kind == "push" and ours(value) and given:
            faults.append(f"pushed after priority: {value.ability_text!r}")
        elif kind == "resolve" and ours(value) and not given:
            faults.append(f"resolved before anybody had priority: {value.ability_text!r}")
    return faults


def _census(monkeypatch, population):
    recorder = _Recorder(monkeypatch)
    late: dict[str, list[str]] = defaultdict(list)
    fired_by_kind: Counter = Counter()
    fired_units: set[str] = set()
    rows_fired = 0
    for card, kinds, lines in population:
        unit_fired = False
        for placement in _placements(card, kinds):
            for road in _roads(placement):
                for interactive in (False, True):
                    events = _drive(
                        card, placement, road,
                        interactive=interactive, recorder=recorder,
                    )
                    if events is None:
                        continue
                    pushed = [
                        value for kind, value in events
                        if kind == "push" and value.card.name == card.name
                        and (value.ability_text or "") in lines
                    ]
                    if not pushed:
                        continue
                    rows_fired += 1
                    unit_fired = True
                    faults = _late(events, lines, card.name, interactive=interactive)
                    if faults:
                        table = "interactive" if interactive else "headless"
                        late[card.name].append(f"{placement}/{road}/{table}: {faults[0]}")
        if unit_fired:
            fired_units.add(card.name)
            for kind in kinds:
                fired_by_kind[kind] += 1
    return late, fired_by_kind, fired_units, rows_fired


def _unblocked(population):
    return [row for row in population if "attacks_unblocked" in row[1]]


@pytest.mark.cr("509.2a", "509.1h", "509.3g", "117.4")
def test_every_attacks_and_isnt_blocked_trigger_is_on_the_stack_before_the_steps_priority(monkeypatch):
    """The 27 printed "attacks and isn't blocked" triggers (the creature's own
    and an Aura's "enchanted creature …"), every road, both tables."""
    population = _unblocked(_POPULATION)
    late, by_kind, fired, rows = _census(monkeypatch, population)
    assert not late, "\n".join(f"{name}: {rows_}" for name, rows_ in sorted(late.items()))
    # Floors: the whole of the kind fired (27 cards, 110 rows when written),
    # on every road that reaches it.
    assert len(population) >= 27, len(population)
    assert len(fired) == len(population), sorted(
        card.name for card, _, _ in population if card.name not in fired
    )
    assert rows >= 4 * len(fired), rows


@pytest.mark.full
@pytest.mark.cr("509.2a", "509.1i", "509.3a", "509.3c")
def test_every_block_outcome_trigger_is_on_the_stack_before_the_steps_priority(monkeypatch):
    """The rest of the kinds — "blocks", "becomes blocked", "blocks or becomes
    blocked by", the board-wide rows — which were already fired inside the
    declaration's window. The census holds them to the same invariant so the
    two halves cannot drift apart again."""
    population = [row for row in _POPULATION if "attacks_unblocked" not in row[1]]
    late, by_kind, fired, rows = _census(monkeypatch, population)
    assert not late, "\n".join(f"{name}: {rows_}" for name, rows_ in sorted(late.items()))
    # 145 of the 163 cards fired when written; the rest narrow what blocks or
    # is blocked by colour or type ("becomes blocked by a Wall"), which the
    # census's plain creatures do not answer.
    assert len(fired) >= 140, (len(fired), by_kind)
    for kind in (
        "creature_blocks", "creature_becomes_blocked",
        "creature_blocks_or_blocked_by", "matching_creature_blocks",
        "matching_creature_becomes_blocked",
    ):
        assert by_kind[kind] >= 1, (kind, by_kind)
