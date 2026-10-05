"""``engine/stack_targets.py`` over the whole pool: which targets did this stack
object choose, and does every way of choosing them announce it exactly once?

**Why a census and not a handful of cards.** "A player chose one or more
targets" has no single fire site in the rules — a spell (CR 601.2c), an
activated ability (CR 602.2b), a triggered ability (CR 603.3d) and a target
changed by an effect (CR 115.7) are all it — and a ``StackItem`` records an
announcement across several channels that also carry things that are *not*
targets: a sacrificed cost, a "source of your choice", the object a Clone
copies. So the two questions asked here are asked of every card that can be
put on the stack with a picker in front of it:

1. what the reader says an object chose is what the announcement named, and
   nothing when the announcement named a non-target;
2. a watcher of "whenever a player chooses one or more targets" is on the stack
   above the object exactly once when it chose, and not at all when it did not.

Both are **validated backwards** below — the sweep is re-run with the reader's
evidence switched off and with the announcement removed, and has to go red —
and both carry a floor on how many announcements they examined, because "no
wrong answers" over a sweep that examined none is a true statement about
nothing.

The watcher is an invented card carrying Psychic Battle's text under another
name, so nothing here can pass against a table keyed by a card name.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine import faces
from engine import stack_targets
from engine.models import CardDefinition, Permanent
from engine.modal_triggers import modal_trigger_modes
from engine.oracle import compile_card_oracle
from engine.stack_targets import (apply_target_change, change_options,
                                  change_slots, chosen_targets, names_a_target)
from engine.targeting import spec_is_a_cost, usable_activated_abilities

from tests.helpers import _mk_card, _nosick, resolve_stack


_WATCHER = CardDefinition(
    name="Test Arbiter", mana_cost="", cmc=0.0, type_line="Enchantment",
    oracle_text=(
        "Whenever a player chooses one or more targets, each player reveals "
        "the top card of their library. The player who reveals the card with "
        "the greatest mana value may change the target or targets. If two or "
        "more cards are tied for greatest, the target or targets remain "
        "unchanged. Changing targets this way doesn't trigger abilities of "
        "permanents named Test Arbiter."
    ),
    colors=(), color_identity=(), keywords=(), produced_mana=(),
    raw={"name": "Test Arbiter", "type_line": "Enchantment"},
)


def _pool() -> list:
    """Every card of both manifest roles, deduped — a measured set is exactly
    the population this reader must already be right about when it ships."""
    seen: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            seen.setdefault(card.oracle_id or card.name, card)
    return list(seen.values())


@pytest.fixture(scope="module")
def pool():
    return _pool()


@pytest.fixture(scope="module")
def by_name(pool):
    names: dict = {}
    for card in pool:
        names.setdefault(card.name, card)
    return names


def _bait(by_name) -> list:
    """One permanent of each printed type and each basic land, so most noun
    phrases find a target — plain cards, with no abilities to put their own
    triggers between the announcement and the answer."""
    return [
        _mk_card(name="Bait Creature", type_line="Creature - Human Soldier", power=2, toughness=2),
        _mk_card(name="Bait Artifact", type_line="Artifact"),
        _mk_card(name="Bait Enchantment", type_line="Enchantment"),
        _mk_card(name="Bait Land", type_line="Land"),
        _mk_card(name="Bait Artifact Creature", type_line="Artifact Creature - Golem", power=3, toughness=3),
    ] + [by_name[name] for name in ("Forest", "Island", "Swamp", "Mountain", "Plains")]


def _board(by_name, source_card=None, hand=()):
    """A mirrored two-seat board with a watcher on the far side.

    The mirror is :mod:`tests.regressions.test_announced_target_seat`'s: with
    one side empty a reader that ignored the announcement would still land on
    the right permanent. Each graveyard holds one card of each type, and both
    libraries hold lands, so the watcher's reveal always ties and it never
    changes anything it is only here to count.
    """
    yard = [by_name[name] for name in ("Grizzly Bears", "Sol Ring", "Lightning Bolt", "Forest", "Crusade")]
    source = _nosick(Permanent(card=source_card)) if source_card is not None else None
    mine = ([source] if source is not None else []) + [_nosick(Permanent(card=c)) for c in _bait(by_name)]
    theirs = [_nosick(Permanent(card=c)) for c in _bait(by_name)] + [_nosick(Permanent(card=_WATCHER))]
    game = Game(players=[
        PlayerState(name="P1", hand=list(hand), battlefield=mine, life=20,
                    graveyard=list(yard), library=[by_name["Forest"]] * 12),
        PlayerState(name="P2", battlefield=theirs, life=20,
                    graveyard=list(yard), library=[by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game, source


def _watching(game) -> list:
    return [item for item in game.stack if item.is_ability and item.card is _WATCHER]


def _put_a_spell_on_the_stack(game, by_name) -> None:
    """Seat 1 casts Giant Growth at its own bait creature, so a spell with a
    single target is there for a counterspell or a retarget to name — and the
    watcher's trigger for *that* choice resolves away before anything is
    counted."""
    game.players[1].hand.append(by_name["Giant Growth"])
    creature = next(p for p in game.controlled_by(game.players[1]) if p.card.name == "Bait Creature")
    game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[creature.permanent_id])
    while _watching(game):
        game.resolve_top_of_stack()


def _first_pick(game, spec, source=None):
    """The first offered target as announcement keywords, and what it names."""
    for entry in spec.get("valid_targets") or []:
        kind = entry.get("kind")
        if kind == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            if permanent is None or permanent is source:
                continue
            return {"target_permanent_ids": [permanent.permanent_id]}, ("permanent", permanent.permanent_id)
        if kind == "player":
            return {"target_player_index": entry["seat"]}, ("player", entry["seat"])
        if kind == "graveyard":
            return (
                {"target_player_index": entry["seat"], "target_permanent_index": entry["index"]},
                ("graveyard", None),
            )
        if kind == "stack" and isinstance(entry.get("stack_index"), int):
            # The picker counts from the top; the engine's argument from the bottom.
            index = len(game.stack) - 1 - entry["stack_index"]
            return {"target_stack_index": index}, ("stack", None)
    return None, None


def _names(named, targets) -> bool:
    for target in targets or ():
        if named[0] != target.kind:
            continue
        if named[0] == "permanent" and target.permanent_id != named[1]:
            continue
        if named[0] == "player" and target.seat != named[1]:
            continue
        return True
    return False


#: Spec flags under which the picker in front of an announcement is **not** a
#: target (CR 601.2b's cost, CR 609.7a's source, Clone's optional copy).
_NOT_A_TARGET_FLAGS = ("source_of_choice", "optional")

#: Pickers that are not targets and whose derived spec does not say so: the
#: Circles and Runes of Protection name "a source of your choice" through a
#: kind table that carries no ``source_of_choice`` flag, and two cards choose a
#: graveyard card their text never calls a target. The reader gets these right
#: on the printed-word half of its evidence; this list is here so that the
#: census knows what "right" is without asking the reader.
_UNFLAGGED_NON_TARGETS = frozenset({
    "cast:Harvest Wurm", "cast:Experimental Overload",
    "act:Circle of Protection: Green#0", "act:Circle of Protection: Artifacts#0",
    "act:Circle of Protection: Shadow#0", "act:Prismatic Circle#0",
    "act:Rune of Protection: Artifacts#0", "act:Rune of Protection: Green#0",
    "act:Rune of Protection: Lands#0", "act:Story Circle#0",
})


class _Sweep:
    """What one pass over the pool found."""

    def __init__(self) -> None:
        self.targeted = 0          # announced a target; read back; one trigger
        self.untargeted = 0        # announced none (or a non-target); read (); no trigger
        self.wrong: list[str] = []
        self.objects: list[tuple] = []   # (label, game, item) for the change census

    def judge(self, label, game, item, spec, named) -> None:
        targets = chosen_targets(game, item)
        watching = [
            trigger for trigger in _watching(game)
            if trigger.trigger_context[stack_targets.TARGETS_CHOSEN_ITEM] is item
        ]
        is_target = (
            named is not None
            and not spec_is_a_cost(spec)
            and not any(spec.get(flag) for flag in _NOT_A_TARGET_FLAGS)
            and label not in _UNFLAGGED_NON_TARGETS
        )
        if is_target:
            if not _names(named, targets):
                self.wrong.append(f"{label}: named {named}, read {targets}")
            elif len(watching) != 1:
                self.wrong.append(f"{label}: chose a target, {len(watching)} trigger(s)")
            else:
                self.targeted += 1
                self.objects.append((label, game, item))
            return
        if targets:
            self.wrong.append(f"{label}: named no target, read {targets}")
        elif watching:
            self.wrong.append(f"{label}: chose no target, {len(watching)} trigger(s)")
        else:
            self.untargeted += 1


def _sweep_casts(pool, by_name, only=None) -> _Sweep:
    sweep = _Sweep()
    for card in pool:
        for face in (faces.face_cards(card) or [card]):
            if only is not None and face.name not in only:
                continue
            if face.primary_type == "land":
                continue
            program = compile_card_oracle(face)
            # A modal spell's picker is per mode and is driven by hand in
            # tests/rules/test_target_choices.py.
            if not program.supported or program.modes:
                continue
            game, _ = _board(by_name, hand=[card])
            spec = game.cast_target_spec(0, face)
            if spec.get("kind") in ("stack", "spell_or_permanent") or spec.get("also_stack"):
                _put_a_spell_on_the_stack(game, by_name)
                spec = game.cast_target_spec(0, face)
            keywords, named = _first_pick(game, spec)
            before = len(game.stack)
            result = game.queue_from_hand(0, face.name, **(keywords or {}))
            if not result.supported or len(game.stack) <= before:
                continue
            item = game.stack[before]
            sweep.judge(f"cast:{face.name}", game, item, spec, named)
    return sweep


def _sweep_activations(pool, by_name, only=None) -> _Sweep:
    sweep = _Sweep()
    for card in pool:
        if only is not None and card.name not in only:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None:
                continue
            game, source = _board(by_name, card)
            if game.controller_index_of(source) != 0:
                continue
            slot = game.battlefield_index_of(source)
            spec = game.activation_target_spec(0, slot, ability_index=index)
            if spec.get("kind") in ("stack", "spell_or_permanent") or spec.get("also_stack"):
                _put_a_spell_on_the_stack(game, by_name)
                spec = game.activation_target_spec(0, slot, ability_index=index)
            keywords, named = _first_pick(game, spec, source)
            before = len(game.stack)
            result = game.queue_permanent_ability(
                0, card.name, ability_index=index, **(keywords or {})
            )
            # "queued" and nothing else: a mana ability resolves without ever
            # being a stack object, and there is then no announcement here.
            if not result.supported or result.details != "queued" or len(game.stack) <= before:
                continue
            item = game.stack[before]
            if not item.is_ability or item.source_permanent is not source:
                continue
            if spec.get("sacrifice_cost") or spec.get("discard_cost"):
                named = None
            sweep.judge(f"act:{card.name}#{index}", game, item, spec, named)
    return sweep


#: Every reason ``change_slots`` may give for offering no change. A reason not
#: on this list is a new refusal somebody added without saying what it costs.
_UNCHANGEABLE_REASONS = frozenset({
    "it uses the word \"target\" more than once",
    "its targets answer different descriptions",
    "its legal targets cannot be enumerated",
})


#: Floors and ceilings for the change census, per sweep. Set well inside what
#: the pool measures today for the reason every floor in this file is: an
#: ordinary ingest must not move them, and a census that stopped changing
#: anything must not pass.
#:
#: Measured at Invasion: of 858 targeted casts, 745 were changed and resolved,
#: 103 had no other legal target on the mirrored board, and 10 were refused —
#: every one for printing "target" twice (Deadshot, Drafna's Restoration, …).
#: Of 531 targeted activations: 479, 49 and 3.
_CAST_CHANGED_FLOOR = 600
_CAST_REFUSED_CEILING = 40
_ACTIVATION_CHANGED_FLOOR = 380
_ACTIVATION_REFUSED_CEILING = 20


def _change_every_object(objects) -> tuple[int, int, Counter, list]:
    """CR 115.7a over every targeted object a sweep drove.

    Where a complete change exists the first one is written and read back: the
    object then names exactly the picks — as many targets as before, none of
    them the target that slot had — and still resolves. Where the engine offers
    no change the reason is counted. Returns ``(changed, with nowhere else to
    point, refusals by reason, what went wrong)``.

    Inside the sweep's own test rather than a test of its own, so each sweep
    is built once: the objects are live games, and a second test reading them
    would rebuild the sweep on whichever worker it landed on.
    """
    changed, nowhere_to_go, refused, wrong = 0, 0, Counter(), []
    for label, game, item in objects:
        slots = change_slots(game, item)
        if isinstance(slots, str):
            refused[slots] += 1
            continue
        picks: list = []
        while len(picks) < len(slots):
            options = change_options(slots, picks)
            if not options:
                break
            picks.append(options[0])
        if len(picks) != len(slots):
            nowhere_to_go += 1
            continue
        before = chosen_targets(game, item)
        if not apply_target_change(game, item, slots, picks):
            wrong.append(f"{label}: an offered change was not written")
            continue
        after = chosen_targets(game, item)
        if len(after) != len(before) or not all(
            read.same_object(pick) for read, pick in zip(after, picks)
        ):
            wrong.append(f"{label}: wrote {picks}, read {after}")
            continue
        if any(read.same_object(old) for read, old in zip(after, before)):
            wrong.append(f"{label}: a slot kept its target through a change")
            continue
        try:
            resolve_stack(game)
        except Exception as exc:  # noqa: BLE001 - the census names it
            wrong.append(f"{label}: resolving after the change raised {type(exc).__name__}: {exc}")
            continue
        changed += 1
    return changed, nowhere_to_go, refused, wrong


def test_every_cast_reads_back_what_it_announced_and_triggers_once(pool, by_name):
    """CR 601.2c. Every non-modal spell in the pool, announced with the first
    target its own picker offers: the reader names that target, and the
    watcher is on the stack once. A spell with no picker, or whose picker is a
    cost, a chosen source or an optional copy, reads as choosing nothing and
    the watcher does not trigger.

    Then CR 115.7a over the same objects — see :func:`_change_every_object`.
    """
    sweep = _sweep_casts(pool, by_name)
    assert not sweep.wrong, (
        f"{len(sweep.wrong)} cast(s) misread: {sorted(sweep.wrong)[:12]}"
    )
    # The pool has ~860 targeted and ~3,400 untargeted casts this sweep can
    # drive. Floors well under that so an ordinary ingest does not move them,
    # and well over zero so a sweep that stops reaching the stack cannot pass.
    assert sweep.targeted > 700, sweep.targeted
    assert sweep.untargeted > 2500, sweep.untargeted

    changed, nowhere_to_go, refused, wrong = _change_every_object(sweep.objects)
    assert not wrong, f"{len(wrong)}: {sorted(wrong)[:12]}"
    assert set(refused) <= _UNCHANGEABLE_REASONS, set(refused) - _UNCHANGEABLE_REASONS
    assert changed > _CAST_CHANGED_FLOOR, (changed, nowhere_to_go, dict(refused))
    assert sum(refused.values()) < _CAST_REFUSED_CEILING, dict(refused)


def test_every_activation_reads_back_what_it_announced_and_triggers_once(pool, by_name):
    """CR 602.2b, the same sweep over every activated ability that becomes a
    stack object, and CR 115.7a over what it drove."""
    sweep = _sweep_activations(pool, by_name)
    assert not sweep.wrong, (
        f"{len(sweep.wrong)} activation(s) misread: {sorted(sweep.wrong)[:12]}"
    )
    assert sweep.targeted > 400, sweep.targeted
    assert sweep.untargeted > 450, sweep.untargeted

    changed, nowhere_to_go, refused, wrong = _change_every_object(sweep.objects)
    assert not wrong, f"{len(wrong)}: {sorted(wrong)[:12]}"
    assert set(refused) <= _UNCHANGEABLE_REASONS, set(refused) - _UNCHANGEABLE_REASONS
    assert changed > _ACTIVATION_CHANGED_FLOOR, (changed, nowhere_to_go, dict(refused))
    assert sum(refused.values()) < _ACTIVATION_REFUSED_CEILING, dict(refused)


# -- validated backwards --------------------------------------------------------

#: A chosen source on a spell (Reverse Damage) and on a Circle whose spec
#: carries no flag for it (Story Circle), a cost (Sacrifice) and an optional
#: copy (Clone) — and four ordinary targets.
_BACKWARDS = frozenset({
    "Sacrifice", "Reverse Damage", "Clone", "Story Circle",
    "Lightning Bolt", "Giant Growth", "Terror", "Prodigal Sorcerer",
})


def test_the_census_sees_a_reader_that_trusts_the_fields(pool, by_name, monkeypatch):
    """Switch off both halves of the reader's evidence — believe any derived
    picker, believe any line — and the census has to name the non-targets that
    then read as targets. If it stayed green here it could not have found the
    defect it exists for."""
    assert not _sweep_casts(pool, by_name, only=_BACKWARDS).wrong
    assert not _sweep_activations(pool, by_name, only=_BACKWARDS).wrong

    monkeypatch.setattr(
        stack_targets, "_spec_targets",
        lambda spec: bool(spec) and spec.get("kind") not in (None, "none", "modal", "hand_card"),
    )
    monkeypatch.setattr(stack_targets, "names_a_target", lambda text: True)
    monkeypatch.setattr(stack_targets, "_spell_names_a_target", lambda card: True)

    casts = "\n".join(_sweep_casts(pool, by_name, only=_BACKWARDS).wrong)
    activations = "\n".join(_sweep_activations(pool, by_name, only=_BACKWARDS).wrong)
    # A chosen source and a sacrificed creature both ride the target fields,
    # so a reader that trusts the fields calls each of them a target.
    assert "cast:Reverse Damage: named no target, read" in casts
    assert "cast:Sacrifice: named no target, read" in casts
    assert "act:Story Circle#0: named no target, read" in activations
    # …and the patched sweep goes red for those cards, not for every card.
    assert "cast:Lightning Bolt" not in casts and "act:Prodigal Sorcerer" not in activations


def test_the_census_sees_a_fire_site_that_stopped_announcing(pool, by_name, monkeypatch):
    """…and the other direction: with the announcement gone from the one seam,
    every targeted object reads correctly and triggers nothing, and the census
    says so."""
    monkeypatch.setattr(Game, "announce_targets_chosen", lambda self, item, **kwargs: 0)

    casts = _sweep_casts(pool, by_name, only=_BACKWARDS)
    activations = _sweep_activations(pool, by_name, only=_BACKWARDS)

    assert any("cast:Lightning Bolt: chose a target, 0 trigger(s)" in line for line in casts.wrong)
    assert any("act:Prodigal Sorcerer#0: chose a target, 0 trigger(s)" in line for line in activations.wrong)


# -- triggered abilities ---------------------------------------------------------

#: Triggered abilities that **print a target and do not come to have one as a
#: stack object** when enqueued with nothing but their source — CR 603.3d not
#: modelled for them. Three reasons, and each is this engine's own, measured
#: here rather than papered over:
#:
#: * a target in a **graveyard** or on the **stack** is not among the kinds
#:   ``_choose_trigger_targets`` picks for, so the handler finds one as the
#:   ability resolves (the entry triggers among them are announced with their
#:   creature when it is *cast*, which is where the watcher sees them);
#: * a phrase narrowed by a seat **the firing event names** ("that player
#:   controls", "that player chooses target player who…") has no seat in this
#:   context-free drive — a real fire site supplies it;
#: * the ability derives **no picker at all** (a reflexive ability, a target an
#:   opponent chooses, a roles announcement on a trigger).
#:
#: An ability in the first and third groups is invisible to "whenever a player
#: chooses one or more targets" and to "becomes the target of". This is a
#: ratchet in both directions: a new entry is a new card with the gap, and an
#: entry that starts announcing has to come off the list.
_UNANNOUNCED_TRIGGER_TARGETS = frozenset({
    # a graveyard card, found at resolution
    "Necromancy#0", "Sylvan Hierophant#0", "Gravedigger#0", "Treasure Hunter#0",
    "Scrivener#0", "Anarchist#0", "Cartographer#0", "Monk Idealist#0",
    "Diabolic Servitude#0", "Iridescent Drake#0", "Body Snatcher#1",
    "Junk Diver#0", "Strongarm Thug#0", "Shipwreck Dowser#0",
    "Reya Dawnbringer#0", "Crypt Angel#0", "Phyrexian Delver#0",
    # narrowed by a seat only the firing event knows
    "Heart of Bogardan#1", "Oath of Lieges#0", "Oath of Scholars#0",
    "Oath of Ghouls#0", "Oath of Mages#0", "Oath of Druids#0",
    "Soltari Visionary#0", "Pandemonium#0", "Somnophore#0", "Sigil of Sleep#0",
    "Caustic Wasps#0", "Latulla's Orders#0", "Chandra's Incinerator#0",
    "Feline Sovereign#0",
    # no picker derived
    "The Abyss#0", "Rysorian Badger#0", "Goblin Grenadiers#0",
    "Carpet of Flowers#0", "Erithizon#0", "Ley Line#0", "Tolarian Kraken#0",
})


def test_a_triggered_ability_that_prints_a_target_has_one_on_the_stack(pool, by_name):
    """CR 603.3d. Every supported triggered ability whose line prints a target
    is enqueued from its source on the mirrored board. It must then be on the
    stack **with** a target (chosen by the seat's default as it was pushed),
    or have been removed for having no legal one (CR 603.3c) — or be on the
    pinned list above."""
    targeted, removed, bare = 0, 0, set()
    untargeted_wrong = []
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, trig in enumerate(program.triggered_abilities):
            if not trig.supported or trig.instruction is None:
                continue
            modes = modal_trigger_modes(trig.instruction)
            printed = (
                any(names_a_target(mode.get("label")) for mode in modes)
                if modes else names_a_target(trig.source_line)
            )
            game, source = _board(by_name, card)
            if source is None or not game.is_on_battlefield(source):
                continue
            before = len(game.stack)
            game._enqueue_triggered_ability(
                controller_index=game.controller_index_of(source),
                source_permanent=source, instruction=trig.instruction,
                effect_kind=trig.effect_kind, ability_text=trig.source_line,
            )
            if len(game.stack) <= before:
                removed += printed
                continue
            item = game.stack[before]
            targets = chosen_targets(game, item)
            if not printed:
                if targets:
                    untargeted_wrong.append(f"{card.name}#{index}")
                continue
            if targets:
                targeted += 1
            else:
                bare.add(f"{card.name}#{index}")

    assert not untargeted_wrong, (
        "abilities printing no target read as targeted: " + ", ".join(sorted(untargeted_wrong)[:12])
    )
    assert bare == _UNANNOUNCED_TRIGGER_TARGETS, (
        f"new: {sorted(bare - _UNANNOUNCED_TRIGGER_TARGETS)}; "
        f"now announcing: {sorted(_UNANNOUNCED_TRIGGER_TARGETS - bare)}"
    )
    assert targeted > 85, targeted
    assert removed > 8, removed
