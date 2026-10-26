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
from engine.card_loader import load_cards, manifest_set_paths
from engine.targeting import derive_instruction_spec, spec_roles
from tests.helpers import resolve_stack

#: Floors, because a sweep that reaches nothing passes. On the day: 28 units
#: (11 spells, 10 activated abilities, 7 triggered), every one driven.
_MIN_UNITS = 26
_MIN_TRIGGERS_DECLINED = 6
#: "Up to" units whose announcement also owes a target, across both manifest
#: roles: one on the day (Cruel Revival).
_MIN_OWED = 1

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


@pytest.fixture(scope="module")
def _both_roles_pool():
    """Shipped **and** measured cards, first printing winning — for the
    owed-target arm alone, whose one card (Cruel Revival) was in a measured
    set when the arm was written: asked of the shipped pool it examined
    nothing until the promotion, and a floor could not be held."""
    pool: dict = {}
    for unit in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
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


def _target_quantifiers(value) -> set:
    """Every printed quantifier (``target``, ``up_to``, …) of a ``targets``
    description under *value*, walked as :func:`_target_is_up_to` walks."""
    found: set = set()
    if isinstance(value, dict):
        targets = value.get("targets")
        if isinstance(targets, dict) and targets.get("quantifier"):
            found.add(targets["quantifier"])
        for nested in value.values():
            found |= _target_quantifiers(nested)
    elif isinstance(value, (list, tuple)):
        for entry in value:
            found |= _target_quantifiers(entry)
    elif getattr(value, "payload", None) is not None:
        found |= _target_quantifiers(value.payload)
    return found


def _owes_a_target_beside(card, where, step) -> bool:
    """Whether the unit's announcement **owes** a printed "target" beside its
    "up to" — a second instance of the word that may not be answered with
    nobody (CR 601.2c).

    "Destroy target non-Zombie creature. It can't be regenerated. Return up to
    one target Zombie card from your graveyard to your hand." (Cruel Revival,
    the first such unit, at Onslaught's promotion rehearsal.) This census asks
    whether an announcement naming nobody changes nothing, and that is not an
    announcement such a spell can make: on the walled table it is rightly not
    cast at all, and a bare cast beside legal targets is answered — or refused
    — by the owed slot. What it *can* be asked is the same question of the
    "up to" slot alone: the owed target named, nobody in the other
    (:func:`test_an_up_to_beside_an_owed_target_names_nobody_in_its_own_slot`).
    Read off the printed quantifiers, so the arm sees the shape whether or not
    the lowering made the two slots one roles announcement; of a modal spell,
    per mode, since only one mode is announced (CR 700.2)."""
    if where != "spell":
        return {"target", "up_to"} <= _target_quantifiers((step,))
    program = compile_card_oracle(card)
    announcements = (
        [(mode.instruction,) for mode in program.modes if mode.instruction is not None]
        if program.modes else [tuple(program.instructions)]
    )
    return any(
        {"target", "up_to"} <= _target_quantifiers(instructions)
        for instructions in announcements
    )


def _up_to_bait(card, where, step) -> list:
    """A card the unit's "up to" slot may name **in a graveyard**, when the
    printed slot narrows by a creature type the fixed piles do not hold —
    "up to one target **Zombie** card from your graveyard" — read off the
    up-to step's own payload (``graveyard_subtypes``), so the slot the census
    holds to nobody has something it could have named."""
    instructions = (
        compile_card_oracle(card).instructions if where == "spell" else (step,)
    )
    wanted: list[str] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            targets = value.get("targets")
            if isinstance(targets, dict) and targets.get("quantifier") == "up_to":
                for subtype in value.get("graveyard_subtypes") or ():
                    if subtype not in wanted:
                        wanted.append(subtype)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, (list, tuple)):
            for entry in value:
                walk(entry)
        elif getattr(value, "payload", None) is not None:
            walk(value.payload)

    walk(tuple(instructions))
    return [
        _fixture(f"Open {subtype.title()} Card", f"Creature — {subtype.title()}", shroud=False)
        for subtype in wanted
    ]


def _table(
    pool, card, *, open_board: bool, interactive=(), in_hand: bool = False,
    bait=(),
) -> Game:
    yard = _YARD if open_board else ()
    game = Game(players=[
        PlayerState("A", library=[pool[n] for n in _LIBRARY],
                    hand=[card] if in_hand else [],
                    graveyard=[pool[n] for n in yard] + list(bait)),
        PlayerState("B", library=[pool[n] for n in _LIBRARY],
                    graveyard=[pool[n] for n in yard] + list(bait)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat in (0, 1):
        for fixture in _WALLED + (_OPEN if open_board else []):
            game._put_permanent_onto_battlefield(seat, Permanent(card=fixture), None)
    return game


def _snapshot(game, source_card, named=()):
    """Everything an effect could have changed, bar the source itself — and
    bar the permanents *named* for an owed target, whose effect is the
    announcement's to have (:func:`_owes_a_target_beside`)."""
    board = {}
    for seat, perm in game.permanents_with_controller():
        if perm.card is source_card or perm.permanent_id in named:
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

#: The quantity a pushed trigger's firing event froze, for a ceiling counted
#: off the event ("up to that many", ``x_from_trigger``).
_EVENT_QUANTITY = 3


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
    # The seats a real fire site freezes (CR 603.10): the defending player
    # for an attack trigger, "that player" for a damage trigger.
    context = {
        "defending_player_index": 1, "event_subject_player": 1,
        "trigger_defending_player_index": 1,
    }
    # And the number one freezes, where the ceiling is the event's: "return
    # **up to that many** target permanents that player controls" (Cephalid
    # Constable) is as many as the damage dealt, read off the context key the
    # instruction names (``x_from_trigger``). Pushed without it, the ceiling
    # is zero, the ability names nobody without asking (as a real event of no
    # quantity would), and this census's question - may an *asked* seat answer
    # nobody - is never put to it. Three, so the prompt is a several-target
    # one, as a pumped Constable's is.
    targets = (step.payload or {}).get("targets")
    quantity_key = targets.get("x_from_trigger") if isinstance(targets, dict) else None
    if quantity_key:
        context[quantity_key] = _EVENT_QUANTITY
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=source, instruction=step,
        effect_kind="triggered_" + step.kind, ability_text=ability.source_line,
        trigger_context=context,
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
    """The walled table: nobody is the only announcement, on every unit —
    but a unit that **owes** a target beside its "up to"
    (:func:`_owes_a_target_beside`), which has no announcement naming nobody
    to make; its "up to" is held to nobody by the owed-target test below."""
    units = _units(_pool)
    owing = [unit for unit in units if _owes_a_target_beside(unit[0], unit[1], unit[3])]
    examined = 0
    findings: list[str] = []
    for unit in units:
        card, where = unit[0], unit[1]
        label = f"{card.name} [{where}]"
        if unit in owing:
            continue
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
    assert examined == len(units) - len(owing)


def test_a_bare_up_to_announcement_beside_legal_targets_changes_nothing(_pool):
    """The open table, for the two announcements that arrive with the action:
    an activation and a cast naming nothing have named nobody (CR 602.2b,
    CR 601.2c) — legal targets being available does not make the engine's
    scan the announcer's choice."""
    examined = 0
    findings: list[str] = []
    for unit in _units(_pool):
        card, where = unit[0], unit[1]
        if where == "trigger" or _owes_a_target_beside(card, where, unit[3]):
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


def _role_ref(game, entry) -> "dict | None":
    """The wire's role address for one picker entry."""
    if entry.get("kind") == "permanent":
        return {"permanent_id": game.permanent_id_of(
            game.permanent_at(entry["seat"], entry["index"])
        )}
    if entry.get("kind") == "graveyard":
        return {"graveyard_seat": entry["seat"], "graveyard_index": entry["index"]}
    if entry.get("kind") == "player":
        return {"seat": entry["seat"]}
    return None


def _announce_the_owed_target(game, card) -> "tuple[bool, set]":
    """Cast *card* naming its **owed** target — the picker's first legal entry
    for each mandatory slot, in role order — and nobody for its "up to".
    ``(accepted, ids named)``."""
    from engine.target_roles import OPTIONAL_ROLE

    picker = game.cast_target_spec(0, card, optional_cost_payments={})
    roles = spec_roles(picker)
    options = picker.get("valid_targets") or []
    if not options:
        return False, set()
    if not roles:
        # One owed slot and an "up to" the announcement has no slot for:
        # the shape before the lowering made the two one roles announcement.
        ref = _role_ref(game, options[0])
        named = {ref["permanent_id"]} if ref and "permanent_id" in ref else set()
        accepted = game.queue_from_hand(
            0, card.name, target_permanent_ids=sorted(named),
        ).supported
        return accepted, named
    refs: list[dict] = []
    level = 0
    while options and level < len(roles) and not roles[level].get(OPTIONAL_ROLE):
        ref = _role_ref(game, options[0])
        if ref is None:
            return False, set()
        refs.append(ref)
        options = options[0].get("next") or []
        level += 1
    named = {ref["permanent_id"] for ref in refs if "permanent_id" in ref}
    return game.queue_from_hand(0, card.name, target_role_refs=refs).supported, named


def test_an_up_to_beside_an_owed_target_names_nobody_in_its_own_slot(_both_roles_pool):
    """The census's question asked of the one slot it is about, for a unit
    whose announcement also **owes** a target (:func:`_owes_a_target_beside`):
    the owed target named, nobody for the "up to" — and nothing but the owed
    target's own effect happens, with a card the "up to" could have named in
    reach (:func:`_up_to_bait`).

    Cruel Revival: "Destroy target non-Zombie creature. … Return up to one
    target Zombie card from your graveyard to your hand." Validated backwards:
    on the tree before its two slots were one roles announcement
    (``lowering/_roles._object_then_graveyard_card_roles``), the "up to" was
    never announced, the return scanned the graveyard at resolution, and this
    reads "named nobody for its 'up to' and changed [['Open Zombie Card'] left
    seat 0's graveyard]".
    """
    pool = _both_roles_pool
    examined = 0
    findings: list[str] = []
    for unit in _units(pool):
        card, where, _position, step, _ability = unit
        if not _owes_a_target_beside(card, where, step):
            continue
        label = f"{card.name} [{where}]"
        if where != "spell" or compile_card_oracle(card).modes:
            findings.append(f"{label}: an owed target beside an 'up to' this arm does not drive")
            continue
        bait = _up_to_bait(card, where, step)
        game = _table(pool, card, open_board=True, in_hand=True, bait=bait)
        accepted, named = _announce_the_owed_target(game, card)
        if not accepted:
            findings.append(f"{label}: naming its owed target and nobody else was refused")
            continue
        examined += 1
        before = _snapshot(game, card, named)
        _drain(game)
        changed = _changed(before, _snapshot(game, card, named))
        if changed:
            findings.append(f"{label}: named nobody for its 'up to' and changed {changed}")

    assert examined >= _MIN_OWED, f"only {examined} owed-target units driven"
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
        if where != "trigger" or _owes_a_target_beside(card, where, step):
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
