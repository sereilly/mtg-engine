"""Every "up to N target …" in the pool, announced naming nobody.

CR 601.2c lets an announcement that prints "up to" choose **zero** targets, and
CR 115.6 says what that makes the object: not targeted. So the effect has
nothing to act on. This engine kept the first half and not the second: the
object went on the stack with empty target fields, and the scan under every
single-target handler (``handlers/_targets.pick_target_permanent``) read "no
target recorded" as "find one". With nothing on the table but a creature the
ability could not legally name, Barrin, Tolarian Archmage and Roaming
Ghostlight returned it to its owner's hand, Feline Sovereign destroyed it, and
the +1 of Basri Ket, of Basri, Devoted Paladin and of Garruk, Unleashed put
its counter or its +3/+3 on it.

Every unit the pool prints is driven here on two tables:

* **walled** — everything the phrase could describe has shroud, so the picker
  offers nothing and nobody is the *only* announcement there is;
* **open** — legal targets stand beside the shrouded ones, and the
  announcement names nobody anyway: a bare activation, a bare cast, and a
  triggered ability whose controller is asked and answers with none.

What is asserted is that the announcement was really made (the object reached
the stack and stayed there, which for a trigger is CR 603.3d not removing it),
that the table really was walled (the picker's own list is empty), and that
nothing but the source changed: no permanent tapped, moved, damaged, resized
or countered, and no card left a graveyard.

Validated backwards: with ``oracle_types.named_no_target`` answering False the
walled table names exactly the six above.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.cast_costs import kicker_costs
from engine.faces import compilation_units
from engine.legality import targeting_instruction
from engine.mixins.stack.trigger_targets import _target_is_up_to
from engine.models import CardDefinition, Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle
from engine.oracle_types import NAMED_NO_TARGET
from engine.targeting import derive_instruction_spec
from tests.helpers import resolve_stack

#: Floors, because a sweep that reaches nothing passes. On the day: 28 units
#: (11 spells, 10 activated abilities, 7 triggered), every one driven.
_MIN_UNITS = 26
_MIN_TRIGGERS_DECLINED = 6

_LIBRARY = (
    "Forest", "Craw Wurm", "Plains", "Counterspell", "Mox Pearl", "Swamp",
    "Mountain", "Island", "Serra Angel", "Terror",
) * 3
_YARD = ("Hill Giant", "Lightning Bolt", "Ornithopter", "Holy Strength", "Swamp", "Grizzly Bears")


def _fixture(name: str, type_line: str, *, shroud: bool) -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power="3", toughness="3")
    return CardDefinition(
        name=name, mana_cost="{3}", cmc=3.0, type_line=type_line,
        oracle_text="Shroud" if shroud else "", colors=(), color_identity=(),
        keywords=("Shroud",) if shroud else (), produced_mana=(), raw=raw,
    )


_TYPES = (
    ("Golem", "Artifact Creature — Golem"), ("Beast", "Creature — Beast"),
    ("Relic", "Artifact"), ("Shrine", "Enchantment"), ("Field", "Land"),
)
_WALLED = [_fixture(f"Walled {name}", line, shroud=True) for name, line in _TYPES]
_OPEN = [_fixture(f"Open {name}", line, shroud=False) for name, line in _TYPES]


@pytest.fixture(scope="module")
def _pool(catalog):
    pool: dict = {}
    for unit in compilation_units(catalog):
        pool.setdefault(unit.name, unit)
    return pool


def _units(pool) -> list:
    """``(card, where, position, instruction, ability)`` for every supported
    "up to" in the pool: a spell, an activated ability, a triggered one."""
    found = []
    for card in sorted(pool.values(), key=lambda c: c.name):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if card.primary_type in ("instant", "sorcery"):
            if any(_target_is_up_to(step.payload) for step in program.instructions):
                found.append((card, "spell", 0, None, None))
            continue
        for position, ability in enumerate(program.activated_abilities):
            step = ability.instruction
            if step is not None and ability.supported and _target_is_up_to(step.payload):
                found.append((card, "activated", position, step, ability))
        for position, trigger in enumerate(program.triggered_abilities):
            step = trigger.instruction
            if step is not None and trigger.supported and _target_is_up_to(step.payload):
                found.append((card, "trigger", position, step, trigger))
    return found


def _table(pool, card, *, open_board: bool, interactive=(), in_hand: bool = False) -> Game:
    yard = _YARD if open_board else ()
    game = Game(players=[
        PlayerState("A", library=[pool[n] for n in _LIBRARY],
                    hand=[card] if in_hand else [], graveyard=[pool[n] for n in yard]),
        PlayerState("B", library=[pool[n] for n in _LIBRARY],
                    graveyard=[pool[n] for n in yard]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat in (0, 1):
        for fixture in _WALLED + (_OPEN if open_board else []):
            game._put_permanent_onto_battlefield(seat, Permanent(card=fixture), None)
    return game


def _snapshot(game, source_card):
    """Everything an effect could have changed, bar the source itself."""
    board = {}
    for seat, perm in game.permanents_with_controller():
        if perm.card is source_card:
            continue
        board[perm.permanent_id] = (
            perm.card.name, seat, perm.tapped, perm.damage_marked,
            perm.effective_power if perm.is_creature else None,
            perm.effective_toughness if perm.is_creature else None,
            tuple(sorted(
                (key, str(value)) for key, value in perm.metadata.items()
                if any(word in key for word in ("counter", "cant", "prevent", "untap")) and value
            )),
        )
    yards = tuple(
        tuple(c.name for c in player.graveyard if c is not source_card)
        for player in game.players
    )
    return board, yards


def _changed(before, after) -> list[str]:
    found = [
        f"{state[0]} (seat {state[1]})"
        for permanent_id, state in before[0].items()
        if after[0].get(permanent_id) != state
    ]
    for seat, (was, now) in enumerate(zip(before[1], after[1])):
        gone = [name for name in was if name not in now]
        if gone:
            found.append(f"{gone} left seat {seat}'s graveyard")
    return found


def _drain(game) -> None:
    for _ in range(6):
        resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _is_entry(trigger) -> bool:
    return trigger.condition.kind == "enters_battlefield"


def _stage(game, card, where, ability):
    """The unit's source, on the battlefield and able to act — or None for a
    spell and for an entry trigger, whose source is the announcement."""
    if where == "spell" or (where == "trigger" and _is_entry(ability)):
        return None
    source = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, source, None)
    _drain(game)
    source.metadata.pop("summoning_sickness_turn", None)
    # "…where X is the number of verse counters" (the Urza's Saga verse cycle)
    # and a loyalty cost: enough of both that the ability can be announced.
    add_counters(source, "verse", 3)
    if card.primary_type == "planeswalker":
        add_counters(source, "loyalty", 6)
    if where == "activated" and ability is not None:
        _meet_a_counted_pile(game, source, ability)
    return source


#: How deep a pile the census will build to meet a printed restriction.
_DEEPEST_PILE = 20


def _meet_a_counted_pile(game, source, ability) -> None:
    """Grow the activator's graveyard until the ability's own printed
    restriction stops refusing it, if a deeper pile is what it asks for.

    "Threshold — {T}: Untap up to three target lands. Activate only if there
    are seven or more cards in your graveyard." (Krosan Restorer, Torment.)
    Neither table holds seven, so the activation was refused by CR 602.5 —
    its targets were never asked — and the census reported a bare
    announcement refused. Asked of the engine's own gate
    (``activation_prohibitions.activation_prohibition``, the one the
    activation path refuses with), never of the number printed: a card at a
    time until that gate says yes, so "seven" is the card's to say and any
    other counted pile is met the same way. A restriction no pile meets
    ("only during your upkeep") is left exactly as it was, the cards taken
    back out, and the unit is refused and reported as before.
    """
    from engine.activation_prohibitions import activation_prohibition

    yard = game.players[0].graveyard
    added = 0
    refusal = activation_prohibition(game, 0, source, ability)
    while (
        refusal is not None and refusal.kind == "printed_restriction"
        and added < _DEEPEST_PILE
    ):
        yard.append(_fixture(f"Pile Card {added}", "Instant", shroud=False))
        added += 1
        refusal = activation_prohibition(game, 0, source, ability)
    if refusal is not None and added:
        del yard[-added:]


def _announce(game, card, where, position, step, ability, source) -> bool:
    """Announce the unit **naming nobody**; True if the engine accepted it."""
    if where == "spell":
        return game.queue_from_hand(0, card.name).supported
    if where == "activated":
        return game.queue_permanent_ability(
            0, card.name, permanent_index=game.battlefield_index_of(source),
            ability_index=position, x_value=3,
        ).supported
    if _is_entry(ability):
        kickers = kicker_costs(card.oracle_text or "")
        if kickers:
            # "…if it was kicked with its {2}{U} kicker" (Nightscape
            # Battlemage): the trigger exists only for a kicked cast — and
            # only *that* kicker is paid, so the card's other kicked trigger
            # ("destroy target land") is not on the stack beside this one.
            gate = step.payload.get("intervening_if") or {}
            paid = [gate["kicker"]] if gate.get("kicker") else list(kickers)
            game.players[0].hand.append(card)
            return game.queue_from_hand(
                0, card.name, optional_cost_payments={key: 1 for key in paid},
            ).supported
        game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
        return True
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=source, instruction=step,
        effect_kind="triggered_" + step.kind, ability_text=ability.source_line,
        # The seats a real fire site freezes (CR 603.10): the defending player
        # for an attack trigger, "that player" for a damage trigger.
        trigger_context={
            "defending_player_index": 1, "event_subject_player": 1,
            "trigger_defending_player_index": 1,
        },
    )
    return True


def _picker_offers(game, card, where, step, source) -> list:
    """The announcement's own list of legal targets, as the picker reads it."""
    if where == "spell":
        return list(game.cast_target_spec(0, card, optional_cost_payments={}).get("valid_targets") or ())
    spec = dict(derive_instruction_spec([step]) or {})
    if where == "trigger":
        spec.update(defending_player_index=1, that_player_index=1)
    return game._enumerate_targets(
        0, card, spec, for_cast=False,
        ability_instruction=targeting_instruction(step) if where == "activated" else step,
        source_permanent=source, ability_source=source, triggered=(where == "trigger"),
    )


def _unit_object(game, card, step):
    """The stack object the announcement produced, or None."""
    for item in reversed(game.stack):
        if item.card is card and (step is None or item.ability_instruction is step):
            return item
    return None


def _drive(pool, unit, *, open_board: bool):
    """Announce *unit* naming nobody on one table. Returns
    ``(what changed, picker entries other than the source, the stack object)``
    — the object None when the announcement never produced one.

    The controller is a seat that is **asked**, so a triggered ability with
    anything on offer arms its prompt and is answered with nobody; one with
    nothing on offer is pushed with nobody named and no prompt at all. Either
    way the announcement is the same one, which is the point of driving both
    through here. (A seat nobody asks takes the prompt's default, which names
    a legal target — the simulator's road, and not this census's question.)
    """
    card, where, position, step, ability = unit
    game = _table(
        pool, card, open_board=open_board, in_hand=(where == "spell"), interactive={0},
    )
    source = _stage(game, card, where, ability)
    # The unit's own source is a legal target for some of these — Cho-Arrim
    # Bruiser may tap itself, and a verse enchantment is still on the
    # battlefield when its targets are chosen (CR 601.2c precedes the
    # sacrifice, CR 601.2h). It is left out of the count and out of the
    # snapshot alike: what this asks about is everything else.
    offered = [
        entry for entry in _picker_offers(game, card, where, step, source)
        if not (
            entry.get("kind") == "permanent" and source is not None
            and game.permanent_at(entry["seat"], entry["index"]) is source
        )
    ]
    before = _snapshot(game, card)
    if not _announce(game, card, where, position, step, ability, source):
        return None, offered, None
    if where == "trigger" and _is_entry(ability):
        # A cast permanent has to resolve before its entry trigger exists.
        for _ in range(4):
            if _unit_object(game, card, step) is not None or not game.stack:
                break
            game.resolve_top_of_stack()
    item = _unit_object(game, card, step if where != "spell" else None)
    for prompt in list(game.pending_choices_of("trigger_target")):
        if prompt.data.get("_trigger_item") is item:
            assert prompt.data.get("up_to"), f"{card.name}: the prompt cannot be answered with nobody"
            assert game.confirm_trigger_target(0, permanent_ids=[]), card.name
    _drain(game)
    return _changed(before, _snapshot(game, card)), offered, item


def test_an_up_to_with_nothing_legal_to_name_changes_nothing(_pool):
    """The walled table: nobody is the only announcement, on every unit."""
    units = _units(_pool)
    examined = 0
    findings: list[str] = []
    for unit in units:
        card, where = unit[0], unit[1]
        label = f"{card.name} [{where}]"
        changed, offered, item = _drive(_pool, unit, open_board=False)
        if offered:
            findings.append(f"{label}: the table is not walled — the picker offers {len(offered)}")
            continue
        if item is None:
            # CR 603.3d removes a trigger with no legal *choice*; zero targets
            # is a choice an "up to" can make, so it must be on the stack.
            findings.append(f"{label}: naming nobody never reached the stack")
            continue
        examined += 1
        if where != "spell" and not item.choices.get(NAMED_NO_TARGET):
            findings.append(f"{label}: the object does not record that it named nobody")
        if changed:
            findings.append(f"{label}: named nobody and changed {changed}")

    assert len(units) >= _MIN_UNITS, f"only {len(units)} \"up to\" units found"
    assert not findings, "\n".join(findings)
    assert examined == len(units)


def test_a_bare_up_to_announcement_beside_legal_targets_changes_nothing(_pool):
    """The open table, for the two announcements that arrive with the action:
    an activation and a cast naming nothing have named nobody (CR 602.2b,
    CR 601.2c) — legal targets being available does not make the engine's
    scan the announcer's choice."""
    examined = 0
    findings: list[str] = []
    for unit in _units(_pool):
        card, where = unit[0], unit[1]
        if where == "trigger":
            continue
        changed, offered, item = _drive(_pool, unit, open_board=True)
        label = f"{card.name} [{where}]"
        if item is None:
            findings.append(f"{label}: a bare announcement was refused")
            continue
        if not offered:
            findings.append(f"{label}: the open table offers it nothing")
            continue
        examined += 1
        if changed:
            findings.append(f"{label}: named nobody and changed {changed}")

    assert examined >= 20, f"only {examined} bare announcements driven"
    assert not findings, "\n".join(findings)


def test_a_seat_asked_for_an_up_to_target_may_answer_nobody(_pool):
    """The open table, for the announcement that is *asked*: a triggered
    ability's controller is offered its legal targets, the prompt says zero is
    an answer, and the answer is taken — nothing changes, the prompt is gone
    and the ability resolves."""
    declined = 0
    findings: list[str] = []
    for unit in _units(_pool):
        card, where, position, step, ability = unit
        if where != "trigger":
            continue
        label = card.name
        game = _table(_pool, card, open_board=True, interactive={0})
        source = _stage(game, card, where, ability)
        before = _snapshot(game, card)
        assert _announce(game, card, where, position, step, ability, source), label
        for _ in range(4):
            if game.pending_choices_of("trigger_target") or not game.stack:
                break
            game.resolve_top_of_stack()
        # This unit's prompt, by the instruction it was armed for: a card
        # kicked both ways puts a second trigger on the stack beside it, and
        # that one ("destroy target land") owes its target.
        prompts = [
            prompt for prompt in game.pending_choices_of("trigger_target")
            if prompt.data["_trigger_item"].ability_instruction is step
        ]
        if not prompts:
            findings.append(f"{label}: no target was asked for beside legal targets")
            continue
        prompt = prompts[0]
        if not prompt.data.get("up_to"):
            findings.append(f"{label}: the prompt does not say nobody is an answer")
            continue
        item = prompt.data["_trigger_item"]
        if not game.confirm_trigger_target(0, permanent_ids=[]):
            findings.append(f"{label}: answering nobody was refused")
            continue
        declined += 1
        if game.pending_choices_of("trigger_target"):
            findings.append(f"{label}: the prompt is still owed after the answer")
        if not item.choices.get(NAMED_NO_TARGET) or item.target_permanent_id is not None:
            findings.append(f"{label}: the answer was not recorded on the object")
        if not any(waiting is item for waiting in game.stack):
            findings.append(f"{label}: the ability left the stack instead of resolving")
        _drain(game)
        changed = _changed(before, _snapshot(game, card))
        if changed:
            findings.append(f"{label}: named nobody and changed {changed}")

    assert declined >= _MIN_TRIGGERS_DECLINED, f"only {declined} prompts declined"
    assert not findings, "\n".join(findings)


def test_a_target_that_is_owed_cannot_be_answered_with_nobody(_pool):
    """The answer is an "up to"'s alone. Man-o'-War's "return target creature"
    owes its target (CR 603.3d), so an empty answer is refused and the prompt
    stays owed — otherwise the new answer would be a way to skip any trigger."""
    card = _pool["Man-o'-War"]
    game = _table(_pool, card, open_board=True, interactive={0})
    game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
    prompt = next(iter(game.pending_choices_of("trigger_target")))

    assert not prompt.data.get("up_to")
    assert game.confirm_trigger_target(0, permanent_ids=[]) is False
    assert list(game.pending_choices_of("trigger_target")) == [prompt]
    assert not prompt.data["_trigger_item"].choices.get(NAMED_NO_TARGET)


def test_naming_a_target_still_acts(_pool):
    """The control: the record is written for *nobody* and for nothing else.
    Basri Ket's +1 aimed at a creature puts its counter there, and Roaming
    Ghostlight's trigger answered with a creature returns it."""
    basri = _pool["Basri Ket"]
    game = _table(_pool, basri, open_board=True)
    walker = _stage(game, basri, "activated", None)
    beast = next(p for p in game.controlled_by(0) if p.card.name == "Open Beast")
    assert game.queue_permanent_ability(
        0, "Basri Ket", permanent_index=game.battlefield_index_of(walker),
        ability_index=0, target_permanent_ids=[beast.permanent_id],
    ).supported
    assert not game.stack[-1].choices.get(NAMED_NO_TARGET)
    _drain(game)
    assert beast.effective_power == 4 and beast.effective_toughness == 4

    ghost = _pool["Roaming Ghostlight"]
    game = _table(_pool, ghost, open_board=True, interactive={0})
    game._put_permanent_onto_battlefield(0, Permanent(card=ghost), None)
    victim = next(p for p in game.controlled_by(1) if p.card.name == "Open Beast")
    assert game.confirm_trigger_target(0, permanent_id=victim.permanent_id)
    _drain(game)
    assert not game.is_on_battlefield(victim)
    assert [c.name for c in game.players[1].hand] == ["Open Beast"]


def test_gilded_drake_with_nobody_to_exchange_with_is_sacrificed(_pool):
    """"…exchange control of this creature and up to one target creature an
    opponent controls. If you don't or can't make an exchange, sacrifice this
    creature." Naming nobody is not the whole ability doing nothing: the
    sentence behind the target still runs, and the shrouded creature across
    the table is not what it exchanges with."""
    drake = _pool["Gilded Drake"]
    game = _table(_pool, drake, open_board=False)
    theirs = [p for p in game.controlled_by(1)]
    source = Permanent(card=drake)
    game._put_permanent_onto_battlefield(0, source, None)
    _drain(game)

    assert not game.is_on_battlefield(source)
    assert [c.name for c in game.players[0].graveyard] == ["Gilded Drake"]
    assert all(game.controller_index_of(p) == 1 for p in theirs)
