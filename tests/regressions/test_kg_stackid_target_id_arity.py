"""The chosen-target id channel has one shape, and every reader reads it.

``StackItem.target_permanent_id`` (and the ``ChosenMode``,
``OracleExecutionContext`` and ``StackAnnouncement`` copies of it) had two
arities: the cast and activation paths stamped the announced *list*, while an
announcement made by slot, a prompt's answer, a copy's new target and a
changed target each wrote a bare id. Readers answered for themselves —
``isinstance(ids, int)`` in some, "slot zero" or "exactly one" in others — so
the same choice played differently depending on how it was spelled. Two
shipped cards showed it:

* **Turn to Slag** ("…deals 5 damage to target creature. Destroy all
  Equipment attached to that creature.") announced by id destroyed none of
  the Equipment — ``destroy_all_matching`` asked ``permanent_by_id`` of the
  whole list;
* **Glyph of Reincarnation** announced by id found "the creature whose blocks
  it names is gone" and did nothing, by the same read.

Now the channel is None or a list of slots (``game_types.check_target_ids``,
asked of every write by every holder), and readers ask ``target_ids`` /
``single_chosen_id`` / ``first_target_id``. The census announces every
single-permanent-target spell and activated ability in a sample of the pool
at one permanent both ways — by id, and by seat and slot — and requires the
two games to end the same. Validated backwards: on the base tree the whole
pool (1,092 announcements with a target) differs at Turn to Slag alone.
"""
from __future__ import annotations

import ast
import dataclasses
import itertools
import random
from pathlib import Path

import pytest

from engine import Game, PlayerState, faces
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.game_types import ChosenMode, OracleExecutionContext, StackItem
from engine.legality import _activation_spec
from engine.mana_payment import is_mana_ability
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, usable_activated_abilities

from tests.helpers import stable_sample

#: One announcement in every STRIDE, by a digest of the card's name.
STRIDE = 4

#: Always in the sample: the card the base tree's census named.
_KNOWN = ("Turn to Slag",)

_POOL: dict = {}
for _card in faces.compilation_units(load_cards(manifest_set_paths(include_measured=True))):
    _POOL.setdefault(_card.name, _card)


def _mk(name, type_line, power=None, toughness=None, oracle="", colors=()):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw.update(power=str(power), toughness=str(toughness))
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=oracle,
        colors=tuple(colors), color_identity=(), keywords=(), produced_mana=(), raw=raw,
    )


#: A plain permanent of each type, a tapped creature, a flier, a Wall and an
#: Equipment on the first creature — on both sides, so a resolution that lost
#: its target and scanned for another has something to find.
_BAIT = (
    _mk("Bait Creature", "Creature - Human Soldier", 2, 2, colors=("W", "U", "B", "R", "G")),
    _mk("Bait Artifact", "Artifact"),
    _mk("Bait Enchantment", "Enchantment"),
    _mk("Bait Artifact Creature", "Artifact Creature - Golem", 3, 3),
    _mk("Bait Other Creature", "Creature - Elf Druid", 1, 4),
    _mk("Bait Flier", "Creature - Bird", 1, 1, oracle="Flying"),
    _mk("Bait Wall", "Creature - Wall", 0, 5, oracle="Defender"),
    _mk("Bait Tapped Creature", "Creature - Ogre", 3, 3),
    _mk("Bait Equipment", "Artifact - Equipment"),
) + tuple(_POOL[name] for name in ("Forest", "Island", "Swamp", "Mountain", "Plains"))


def _board(source_card=None, hand=()) -> Game:
    """A mirrored board, every global counter restarted so two games built the
    same way number their objects and effects the same way."""
    import engine.continuous as continuous
    import engine.models as models

    models._PERMANENT_IDS = itertools.count(1)
    continuous._TIMESTAMP = itertools.count(1)
    yard = [_POOL[name] for name in ("Grizzly Bears", "Sol Ring", "Forest")]
    mine = ([Permanent(card=source_card)] if source_card is not None else [])
    game = Game(players=[
        PlayerState(name="P1", life=20, graveyard=list(yard), library=[_POOL["Forest"]] * 12,
                    hand=list(hand), battlefield=mine + [Permanent(card=c) for c in _BAIT]),
        PlayerState(name="P2", life=20, graveyard=list(yard), library=[_POOL["Forest"]] * 12,
                    battlefield=[Permanent(card=c) for c in _BAIT]),
    ])
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    for seat in (0, 1):
        named = {p.card.name: p for p in game.controlled_by(seat)}
        named["Bait Tapped Creature"].tapped = True
        attach_aura(named["Bait Equipment"], named["Bait Creature"])
    game.check_state_based_actions()
    return game


def _fingerprint(game) -> dict:
    return {
        "players": [
            (p.life, sorted(c.name for c in p.hand), len(p.library),
             [c.name for c in p.graveyard], [c.name for c in p.exile])
            for p in game.players
        ],
        "permanents": sorted(
            repr((
                perm.permanent_id, perm.card.name, game.controller_index_of(perm),
                perm.tapped, perm.damage_marked,
                perm.effective_power if perm.is_creature else None,
                perm.effective_toughness if perm.is_creature else None,
                sorted((k, repr(v)) for k, v in perm.metadata.items()),
            ))
            for perm in game.all_permanents()
        ),
        "log": game.log[-12:],
    }


def _settle(game) -> None:
    for _ in range(80):
        if game.pending_choices:
            game.auto_resolve_pending_choices()
            game.auto_resolve_pending_replacement_choices()
            continue
        if not game.stack:
            return
        if not game.resolve_top_of_stack():
            game.auto_resolve_pending_choices()
            game.auto_resolve_pending_replacement_choices()


def _pick(game, entries, source=None):
    rows = []
    for entry in entries:
        if entry.get("kind") not in (None, "permanent") or entry.get("index") is None:
            continue
        permanent = game.permanent_at(entry["seat"], entry["index"])
        if permanent is None or permanent is source:
            continue
        rows.append((entry["seat"] != 1, permanent.card.name != "Bait Creature", len(rows), permanent))
    if not rows:
        return None
    rows.sort(key=lambda row: row[:3])
    return rows[0][3]


def _spelling(game, target, how) -> dict:
    if how == "id":
        return {"target_permanent_ids": [target.permanent_id]}
    return {
        "target_player_index": game.controller_index_of(target),
        "target_permanent_index": game.battlefield_index_of(target),
    }


def _spell(card, how):
    random.seed(11)
    game = _board(hand=[faces.whole_card(card)])
    target = _pick(game, game.cast_target_spec(0, card).get("valid_targets") or [])
    if target is None:
        return None
    keywords = _spelling(game, target, how)
    if "{X}" in (card.mana_cost or ""):
        keywords["x_value"] = 2
    result = game.queue_from_hand(0, card.name, **keywords)
    if not result.supported:
        return {"refused": result.details}
    _settle(game)
    return _fingerprint(game)


def _ability(card, index, how):
    random.seed(11)
    game = _board(source_card=card)
    source = game.players[0].battlefield[0]
    if game.controller_index_of(source) != 0:
        return None
    spec = game.activation_target_spec(0, game.battlefield_index_of(source), ability_index=index)
    target = _pick(game, spec.get("valid_targets") or [], source)
    if target is None:
        return None
    keywords = _spelling(game, target, how)
    if "{X}" in (usable_activated_abilities(compile_card_oracle(card))[index].source_line or ""):
        keywords["x_value"] = 1
    result = game.queue_permanent_ability(0, card.name, ability_index=index, **keywords)
    if not result.supported:
        return {"refused": result.details}
    _settle(game)
    return _fingerprint(game)


def _single_target(spec) -> bool:
    if not spec or spec.get("kind") in (None, "none", "modal", "hand_card", "player",
                                        "roles", "divided", "stack", "graveyard_card"):
        return False
    ceiling = spec.get("max_targets")
    if isinstance(ceiling, int) and ceiling >= 2:
        return False
    return not (spec.get("x_targets") or spec.get("unbounded_targets") or spec.get("division"))


def _announcements():
    for name in sorted(_POOL):
        if name not in _KNOWN and not stable_sample(name, STRIDE):
            continue
        card = _POOL[name]
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if card.primary_type in ("instant", "sorcery") and not program.modes:
            if _single_target(derive_cast_spec(card, program) or {}):
                yield name, lambda how, card=card: _spell(card, how)
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None or is_mana_ability(ability):
                continue
            spec, _ = _activation_spec([ability])
            if not _single_target(spec) or spec.get("source_of_choice") or spec.get("optional"):
                continue
            yield f"{name} ({index})", lambda how, card=card, index=index: _ability(card, index, how)


@pytest.mark.cr("601.2c", "602.2b", "400.7")
def test_a_single_target_announcement_resolves_the_same_by_slot_and_by_id():
    """The census: the same choice, spelled two ways, is the same game."""
    examined = 0
    differ = []
    for label, run in _announcements():
        by_id, by_slot = run("id"), run("slot")
        if by_id is None and by_slot is None:
            continue
        examined += 1
        if by_id != by_slot:
            differ.append(label)
    # A quarter of the 1,092 such announcements that name a target, and the
    # known card besides.
    assert examined >= 200, examined
    assert differ == [], differ


@pytest.mark.cr("608.2b", "400.7")
def test_turn_to_slag_named_by_id_destroys_the_equipment():
    """Announced by id, the Equipment on the creature it burned stayed put."""
    random.seed(11)
    game = _board(hand=[_POOL["Turn to Slag"]])
    victim = next(p for p in game.controlled_by(1) if p.card.name == "Bait Creature")
    assert game.queue_from_hand(0, "Turn to Slag", target_permanent_ids=[victim.permanent_id]).supported
    _settle(game)
    assert "Turn to Slag destroyed Bait Equipment" in game.log, game.log
    assert "Bait Equipment" in [card.name for card in game.players[1].graveyard]


@pytest.mark.cr("509.1h", "400.7")
def test_glyph_of_reincarnation_named_by_id_reads_its_walls_blocks(set_pool):
    """"Cast this spell only after combat. Destroy all creatures that were
    blocked by target Wall this turn. …" Named by id — the address CR 400.7
    makes stable, and the one the cast path stamps as a list — the Wall's
    blocks were never read."""
    wall = Permanent(card=_mk("Named Wall", "Creature - Wall", 0, 9, oracle="Defender"))
    other = Permanent(card=_mk("Other Wall", "Creature - Wall", 0, 9, oracle="Defender"))
    first = Permanent(card=_mk("Attacker One", "Creature - Bear", 2, 2))
    second = Permanent(card=_mk("Attacker Two", "Creature - Bear", 2, 2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[first, second]),
        PlayerState(name="P2", battlefield=[wall, other],
                    hand=[set_pool("LEG")["Glyph of Reincarnation"]]),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    game.declare_attackers(0, [0, 1])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0, 1: 1})
    game.advance_combat_phase()
    game.end_combat(step_already_started=True)
    game._settle()
    game.current_turn_phase = "postcombat_main"

    assert game.cast_from_hand(
        1, "Glyph of Reincarnation", target_permanent_ids=[wall.permanent_id],
    ).supported
    game._settle()

    assert [p.card.name for p in game.controlled_by(0)] == ["Attacker Two"], game.log


@pytest.mark.cr("400.7")
def test_no_holder_of_the_channel_takes_a_bare_id():
    """The guard that keeps the one shape: every holder refuses a write of the
    other arity as it happens — built, assigned or ``dataclasses.replace``d."""
    from engine.exiled_records import StackAnnouncement

    card = _POOL["Lightning Bolt"]
    with pytest.raises(TypeError):
        StackItem(card, 0, None, None, None, target_permanent_id=7)
    item = StackItem(card, 0, None, None, None, target_permanent_id=[7, None])
    with pytest.raises(TypeError):
        item.target_permanent_id = 7
    with pytest.raises(TypeError):
        item.target_permanent_id = (7,)
    item.target_permanent_id = None
    with pytest.raises(TypeError):
        ChosenMode(index=0, target_permanent_id=7)
    players = [PlayerState(name="A"), PlayerState(name="B")]
    context = OracleExecutionContext(
        caster=players[0], target=players[1], card=card, target_permanent_id=[7],
    )
    with pytest.raises(TypeError):
        dataclasses.replace(context, target_permanent_id=7)
    with pytest.raises(TypeError):
        StackAnnouncement(caster_index=0, target_permanent_id=7)


def test_no_reader_reasks_the_channels_arity():
    """No module under ``engine/`` or ``web/`` asks ``isinstance`` of the id
    channel, or hands the whole channel to ``permanent_by_id`` as though it
    were one id: the shape is settled where it is written, so a reader that
    tests it is a twelfth normalisation in waiting (or, for the second, the
    read that made Turn to Slag a no-op)."""
    root = Path(__file__).resolve().parents[2]
    offenders = []
    examined = 0

    def is_channel(node) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == "target_permanent_id":
            # ``req`` is the wire's ``GameActionRequest``: its field of this
            # name is one answer from a client, not the stack object's
            # channel, and ``web/actions`` resolves it once as an id.
            return not (isinstance(node.value, ast.Name) and node.value.id == "req")
        return (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "target_permanent_id"
        )

    for path in sorted([*root.joinpath("engine").rglob("*.py"), *root.joinpath("web").rglob("*.py")]):
        text = path.read_text(encoding="utf-8")
        if "target_permanent_id" not in text:
            continue
        examined += 1
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in ("isinstance", "permanent_by_id", "find_permanent_by_id") and is_channel(node.args[0]):
                offenders.append(f"{path.relative_to(root).as_posix()}:{node.lineno} {name}")
    assert examined >= 40, examined
    assert offenders == [], offenders
