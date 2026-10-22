"""A permanent spell targets nothing — for everything that asks.

CR 115.1 lists what is targeted: an instant or sorcery spell (a), an Aura
spell (b), an activated ability (c), a triggered ability (d). A creature spell
is none of them. This engine *names* an entry trigger's target as the
permanent is cast, so the spell carries that name in the fields a targeted
spell uses, and ``tests/engine/test_permanent_spell_announces_nothing_census``
holds the half of the consequence that is an **announcement**: nothing
"becomes the target" of a creature spell.

This is the other half: everything that **reads** what a spell on the stack
targets. There were four readers and each read the fields:

* ``targeting.single_spell_target`` — "target spell with a single target"
  (Deflection, Misdirection, Meddle, Rebound, Reflecting Mirror, Silver
  Wyvern): the picker offered a Man-o'-War spell, and a change rewrote what
  its trigger would later take as announced;
* ``targeting.spell_targets`` — "casts a spell that targets you or a creature
  you control" (Reparations): a card drawn for a creature spell;
* ``handlers/stack._spell_targets_matching`` — "counter target spell that
  targets a creature" (Confound, Intervene, Mistfolk, Diplomatic Escort,
  Vigilant Martyr, Teferi's Response): a Man-o'-War countered for a target it
  does not have;
* ``targeting.stack_object_target_spec`` — the spec a change enumerates by.

Driven for every non-Aura permanent in the pool whose cast names something
for its entry trigger — a permanent, a player or a graveyard card — against
**every card in the pool whose picker asks what a stack object targets**
(found by the spec keys, not listed).

Validated backwards in this file: with
``stack_targets.permanent_spell_targets_nothing`` answering False, every one
of the four readers is named.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState, stack_targets
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import (
    derive_activation_spec, derive_cast_spec,
    single_player_target, single_spell_target, spell_targets,
    stack_object_target_spec,
)
from engine.cast_targets import cast_announced_entry_trigger
from tests.helpers import resolve_stack

#: Floors, because a sweep that reaches nothing passes. 52 permanents, 14
#: watchers and 75 casts on the day.
_MIN_PERMANENTS = 45
_MIN_WATCHERS = 12
_MIN_CASTS = 60

_BOARD = (
    "Grizzly Bears", "Black Knight", "White Knight", "Forest", "Island", "Sol Ring",
    "Circle of Protection: Red", "Ornithopter", "Serra Angel", "Hill Giant", "Wall of Wood",
)
_GRAVEYARD = ("Grizzly Bears", "Hill Giant", "Counterspell", "Sol Ring")

#: The spec keys under which a picker narrows a stack object by **what it
#: targets**. A card whose cast or activation spec carries one is a watcher.
_WATCHING_KEYS = ("stack_single_target", "stack_targets_filter", "stack_targets_source")


@pytest.fixture(scope="module")
def _pool(catalog):
    pool: dict = {}
    for unit in compilation_units(catalog):
        pool.setdefault(unit.name, unit)
    return pool


def _watches(spec) -> bool:
    return bool(spec) and any(
        spec.get(key) for key in spec if key.startswith(_WATCHING_KEYS)
    )


@pytest.fixture(scope="module")
def _watchers(_pool) -> tuple[list, list]:
    """``(cast, activated)``: every supported card whose own picker asks what
    a stack object targets — the instants by their cast spec, the permanents
    as ``(card, ability index)``."""
    cast, activated = [], []
    for card in sorted(_pool.values(), key=lambda c: c.name):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if card.primary_type in ("instant", "sorcery"):
            if _watches(derive_cast_spec(card, program)):
                cast.append(card)
            continue
        for index, ability in enumerate(program.activated_abilities):
            if _watches(derive_activation_spec(ability)):
                activated.append((card, index))
    return cast, activated


def _table(pool, card, watchers) -> Game:
    """Seat A holds *card*; seat B holds every watcher — the instants in hand,
    the permanents on the battlefield beside a Reparations."""
    cast, activated = watchers
    game = Game(players=[
        PlayerState("A", library=[pool["Forest"]] * 12, hand=[card]),
        PlayerState("B", library=[pool["Forest"]] * 12, hand=list(cast)),
    ])
    game.enforce_mana_costs = False
    for seat in (0, 1):
        for name in _BOARD:
            game._put_permanent_onto_battlefield(seat, Permanent(card=pool[name]), None)
        game.players[seat].graveyard.extend(pool[name] for name in _GRAVEYARD)
    for watcher, _index in activated:
        game._put_permanent_onto_battlefield(1, Permanent(card=watcher), None)
    game._put_permanent_onto_battlefield(1, Permanent(card=pool["Reparations"]), None)
    return game


def _names_to_try(game, offered) -> list[dict]:
    """One entry per thing a watcher could be narrowing on: seat B's Mistfolk
    and Silver Wyvern ("this creature"), its first land, enchantment and
    artifact, seat B itself, and a graveyard card."""
    picks: list[dict] = []

    def take(entry):
        if entry is not None and entry not in picks:
            picks.append(entry)

    permanents = [entry for entry in offered if entry.get("kind") == "permanent"]
    theirs = [entry for entry in permanents if entry.get("seat") == 1]

    def first(test):
        for entry in theirs:
            permanent = game.permanent_at(entry["seat"], entry["index"])
            if permanent is not None and test(permanent):
                return entry
        return None

    take(first(lambda p: p.card.name == "Mistfolk"))
    take(first(lambda p: p.card.name == "Silver Wyvern"))
    take(first(lambda p: p.has_type("land")))
    take(first(lambda p: p.has_type("enchantment") and not p.is_creature))
    take(first(lambda p: p.has_type("artifact") and not p.is_creature))
    if permanents and not any(entry.get("kind") == "permanent" for entry in picks):
        take((theirs or permanents)[0])
    players = [entry for entry in offered if entry.get("kind") == "player"]
    take(next((entry for entry in players if entry.get("seat") == 1), players[0] if players else None))
    take(next((entry for entry in offered if entry.get("kind") == "graveyard"), None))
    return picks


def _announcement(game, entry) -> dict:
    if entry["kind"] == "permanent":
        permanent = game.permanent_at(entry["seat"], entry["index"])
        return {"target_permanent_ids": [permanent.permanent_id]}
    if entry["kind"] == "player":
        return {"target_player_index": entry["seat"]}
    return {"target_player_index": entry["seat"], "target_permanent_index": entry["index"]}


@pytest.fixture(scope="module")
def _units(_pool, _watchers) -> list:
    """Each supported non-Aura permanent whose cast names something for its
    entry trigger, with the names to try."""
    found = []
    for card in sorted(_pool.values(), key=lambda c: c.name):
        if card.primary_type in ("instant", "sorcery", "land") or "Aura" in card.type_line:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if cast_announced_entry_trigger(card, program, optional_cost_payments={}) is None:
            continue
        game = _table(_pool, card, _watchers)
        picks = _names_to_try(game, game.cast_target_spec(0, card).get("valid_targets") or ())
        if picks:
            found.append((card, picks))
    return found


def _offers(game, entries, spell) -> bool:
    """Whether a picker's *entries* include the stack object *spell*."""
    depth = len(game.stack)
    for entry in entries or ():
        index = entry.get("stack_index")
        if entry.get("kind") == "stack" and isinstance(index, int) and 0 <= depth - 1 - index < depth:
            if game.stack[depth - 1 - index] is spell:
                return True
    return False


def _watcher_offers(game, watchers, spell) -> list[str]:
    """The watchers whose own picker offers *spell*, by name."""
    cast, activated = watchers
    offering = []
    for card in cast:
        if _offers(game, game.cast_target_spec(1, card).get("valid_targets"), spell):
            offering.append(card.name)
    for card, ability_index in activated:
        source = next(p for p in game.controlled_by(1) if p.card is card)
        spec = game.activation_target_spec(1, game.battlefield_index_of(source), ability_index)
        if _offers(game, spec.get("valid_targets"), spell):
            offering.append(card.name)
    return offering


def _census(pool, units, watchers) -> tuple[Counter, list[str], int]:
    """Cast every unit at every name to try; ``(findings per reader, lines,
    casts examined)``."""
    findings: Counter = Counter()
    lines: list[str] = []
    examined = 0

    def note(reader, card, entry, detail=""):
        findings[reader] += 1
        lines.append(f"{reader}: {card.name} naming a {entry['kind']} {detail}".rstrip())

    for card, picks in units:
        for entry in picks:
            game = _table(pool, card, watchers)
            hand = len(game.players[1].hand)
            assert game.queue_from_hand(0, card.name, **_announcement(game, entry)).supported, (
                card.name, entry,
            )
            spell = next(item for item in game.stack if not item.is_ability and item.card is card)
            examined += 1

            if single_spell_target(game, spell) is not None:
                note("single_spell_target", card, entry)
            if single_player_target(game, spell) is not None:
                note("single_player_target", card, entry)
            if spell_targets(game, spell) != ((), ()):
                note("spell_targets", card, entry)
            if stack_object_target_spec(spell) is not None:
                note("stack_object_target_spec", card, entry)
            if stack_targets.chosen_targets(game, spell) != ():
                note("chosen_targets", card, entry)
            if not isinstance(stack_targets.change_slots(game, spell), str):
                note("change_slots", card, entry)
            offering = _watcher_offers(game, watchers, spell)
            if offering:
                note("a picker", card, entry, f"is offered by {', '.join(offering)}")
            if (
                any(item.is_ability and item.card.name == "Reparations" for item in game.stack)
                or len(game.players[1].hand) != hand
            ):
                note("Reparations", card, entry, "triggered")
    return findings, lines, examined


def test_no_reader_finds_a_target_on_a_permanent_spell(_pool, _units, _watchers):
    cast, activated = _watchers
    assert len(cast) + len(activated) >= _MIN_WATCHERS, (cast, activated)
    assert len(_units) >= _MIN_PERMANENTS, len(_units)

    findings, lines, examined = _census(_pool, _units, _watchers)

    assert examined >= _MIN_CASTS, examined
    assert not findings, f"{dict(findings)}\n" + "\n".join(lines[:60])


def test_the_census_sees_a_reader_that_trusts_the_fields(_pool, _units, _watchers, monkeypatch):
    """Backwards: with the one predicate answering False — a permanent spell
    read as the fields it carries — the readers, the pickers and Reparations
    are each named. One unit in four, which is enough to name them all."""
    monkeypatch.setattr(stack_targets, "permanent_spell_targets_nothing", lambda item: False)

    findings, lines, examined = _census(_pool, _units[::4], _watchers)

    assert examined >= _MIN_CASTS // 5, examined
    for reader in (
        "single_spell_target", "single_player_target", "spell_targets",
        "stack_object_target_spec", "a picker", "Reparations",
    ):
        # Two, not three: the stride sample is one unit in four of a pool that
        # grew by two sets after this was measured, and it names each reader
        # at least twice.
        assert findings[reader] >= 2, (reader, dict(findings))
    offered_by = " ".join(line for line in lines if line.startswith("a picker"))
    for name in ("Deflection", "Meddle", "Confound", "Mistfolk", "Rebound", "Silver Wyvern"):
        assert name in offered_by, name


def test_the_watchers_do_offer_an_instant_aimed_the_same_way(_pool, _watchers):
    """The control: the pickers this census asks are not simply empty. An
    Unsummon cast at seat B's Mistfolk is a spell with a single target, that
    targets a creature, that targets a permanent B controls — and is offered
    by every watcher those words belong to."""
    unsummon = _pool["Unsummon"]
    game = _table(_pool, unsummon, _watchers)
    mistfolk = next(p for p in game.controlled_by(1) if p.card.name == "Mistfolk")
    assert game.queue_from_hand(
        0, "Unsummon", target_permanent_ids=[mistfolk.permanent_id],
    ).supported
    spell = next(item for item in game.stack if not item.is_ability and item.card is unsummon)

    offering = set(_watcher_offers(game, _watchers, spell))

    assert {
        "Avoid Fate", "Confound", "Deflection", "Diplomatic Escort", "Intervene",
        "Meddle", "Misdirection", "Mistfolk", "Ring of Immortals",
    } <= offering, offering
    assert single_spell_target(game, spell) == {
        "kind": "permanent", "permanent_id": mistfolk.permanent_id,
    }
    assert spell_targets(game, spell) == ((), (mistfolk.permanent_id,))


# -- the cards ---------------------------------------------------------------


def _stack_index(game, item) -> int:
    """Where *item* sits in ``game.stack``, by identity (a stack item compares
    by value)."""
    return next(index for index, other in enumerate(game.stack) if other is item)


def _duel(pool, hand_a=(), hand_b=()) -> Game:
    game = Game(players=[
        PlayerState("A", library=[pool["Forest"]] * 12, hand=list(hand_a)),
        PlayerState("B", library=[pool["Forest"]] * 12, hand=list(hand_b)),
    ])
    game.enforce_mana_costs = False
    return game


def test_deflection_cannot_be_cast_at_a_creature_spell(_pool):
    """"Change the target of target spell with a single target." A Man-o'-War
    cast naming a Grizzly Bears is a spell with no targets (CR 115.1): the
    Deflection is refused with nothing spent, and the Bears is still what the
    trigger returns."""
    game = _duel(_pool, hand_a=[_pool["Man-o'-War"]], hand_b=[_pool["Deflection"]])
    bears = Permanent(card=_pool["Grizzly Bears"])
    giant = Permanent(card=_pool["Hill Giant"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game._put_permanent_onto_battlefield(0, giant, None)

    assert game.queue_from_hand(
        0, "Man-o'-War", target_permanent_ids=[bears.permanent_id],
    ).supported
    spell = game.stack[-1]
    assert not _offers(game, game.cast_target_spec(1, _pool["Deflection"]).get("valid_targets"), spell)

    refused = game.queue_from_hand(1, "Deflection", target_stack_index=_stack_index(game, spell))

    assert not refused.supported
    assert [card.name for card in game.players[1].hand] == ["Deflection"]
    assert [item.card.name for item in game.stack] == ["Man-o'-War"]
    resolve_stack(game)
    assert not game.is_on_battlefield(bears) and game.is_on_battlefield(giant)
    assert [card.name for card in game.players[1].hand] == ["Deflection", "Grizzly Bears"]


def test_deflection_still_changes_an_instants_target(_pool):
    """The same table with an Unsummon: one target, changed to the caster's
    own Hill Giant."""
    game = _duel(_pool, hand_a=[_pool["Unsummon"]], hand_b=[_pool["Deflection"]])
    bears = Permanent(card=_pool["Grizzly Bears"])
    giant = Permanent(card=_pool["Hill Giant"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game._put_permanent_onto_battlefield(0, giant, None)

    assert game.queue_from_hand(
        0, "Unsummon", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.queue_from_hand(
        1, "Deflection", target_stack_index=_stack_index(game, game.stack[-1]),
    ).supported
    resolve_stack(game)

    assert game.is_on_battlefield(bears) and not game.is_on_battlefield(giant)


def test_reparations_does_not_trigger_for_a_creature_spell(_pool):
    """"Whenever an opponent casts a spell that targets you or a creature you
    control, you may draw a card." A Man-o'-War naming the Reparations
    player's Bears is not such a spell and nothing triggers — not at the cast
    and not when the Bears is returned; an Unsummon is one."""
    for name, triggers in (("Man-o'-War", False), ("Unsummon", True)):
        game = _duel(_pool, hand_a=[_pool[name]])
        game._put_permanent_onto_battlefield(1, Permanent(card=_pool["Reparations"]), None)
        bears = Permanent(card=_pool["Grizzly Bears"])
        game._put_permanent_onto_battlefield(1, bears, None)

        assert game.queue_from_hand(
            0, name, target_permanent_ids=[bears.permanent_id],
        ).supported
        waiting = [item.card.name for item in game.stack if item.is_ability]
        resolve_stack(game)

        assert waiting == (["Reparations"] if triggers else []), name
        assert not game.is_on_battlefield(bears), name
        assert any("Reparations ability resolved" in line for line in game.log) is triggers, name


def test_confound_cannot_counter_a_creature_spell_for_its_triggers_target(_pool):
    """"Counter target spell that targets a creature." A Nekrataal naming a
    Grizzly Bears targets nothing; the Terror beside it does."""
    for name, offered in (("Nekrataal", False), ("Terror", True)):
        game = _duel(_pool, hand_a=[_pool[name]], hand_b=[_pool["Confound"]])
        bears = Permanent(card=_pool["Grizzly Bears"])
        game._put_permanent_onto_battlefield(1, bears, None)

        assert game.queue_from_hand(
            0, name, target_permanent_ids=[bears.permanent_id],
        ).supported
        spell = game.stack[-1]
        result = game.queue_from_hand(1, "Confound", target_stack_index=_stack_index(game, spell))

        assert result.supported is offered, name
        resolve_stack(game)
        assert game.is_on_battlefield(bears) is offered, name
        assert ("Confound" in [card.name for card in game.players[1].hand]) is (not offered), name
