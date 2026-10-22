"""Census: a target that changed controller in response is still the target.

CR 608.2b judges a target, as the object resolves, against the object's own
description: "target creature" is still a target creature on another
battlefield, and "target creature **an opponent controls**" is not one once
its caster controls it. Nothing in the rule makes a change of controller
illegal by itself.

This engine records an announced permanent twice — its id, and the seat whose
battlefield it stood on (``target_player_index``) — and at resolution looked
the id up **on that seat** (``handlers/_targets.pick_target_permanent``'s step
0, ``bare_announcements.announced_slots``). So a target that had changed hands
was "not there": Boomerang cast at the opponent's Grizzly Bears, with control
of the Bears taken in response, logged "nothing was returned"; Unsummon "No
creature to return"; Terror "its target is gone (608.2b)", of a creature that
had gone nowhere. A triggered ability whose target was chosen read the slot
beside the id on the old battlefield instead, and hit whatever had slid into
it: Nekrataal named the Grizzly Bears and destroyed the Hill Giant.

Measured on ``e67196d6``, the whole pool (this module run as a script on an
export of that tree):

* casts and activations — 1,828 cases, 1,761 whose description still admits
  the permanent under its new controller and 67 whose does not: **1,417
  missed it**, 195 changed a permanent nobody named, and 6 more hit it and
  charged the wrong player ("…deals 5 minus X damage to **that creature's
  controller**", Liquid Fire, charged the old one; Essence Vortex and Blazing
  Salvo asked the old one to pay);
* triggered abilities whose own picker chose the target — 150 cases, 141
  admitted and 9 not: **111 missed it and 100 hit a bystander**, because a
  trigger reads the slot beside the id on the old battlefield;
* none acted on a permanent its description no longer admitted: the CR 608.2b
  gates already removed those.

All of it is 0 now, over the whole pool.

The seat is settled from the id again as the object resolves now, where the
gate judged the target still legal (``LegalityMixin.
resettle_announced_target_seats``): every reader — the id step, the slot
channel, "its controller" off ``context.target`` — then reads the battlefield
the target is on.

**The oracle is a twin table.** For each announcement and each direction the
same board is built twice. On one the object is announced naming the
permanent and control of it changes *in response*; on the twin control
changes first and the object is then announced naming it.

* The twin **accepts** the announcement: the description admits the permanent
  under its new controller. Resolved, the two tables must agree about what the
  **resolution** did — to the named permanent, to every other permanent and to
  every player. What each resolution changed is compared, not where each table
  ends: the costs were paid on two different boards (a tap cost of "two
  untapped creatures you control" taps a different pair when the target is
  not one of them), and a difference a cost made is not one the resolution
  made.
* The twin **refuses** it: the description does not admit it (a controller
  word, most often). Then the resolution must leave the named permanent as it
  was and touch no other permanent but its own source.

**Randomness is reseeded at each step both tables take**, because the module
RNG is shared and the twin is announced between the other table's build and
its resolution. Without it Cursed Scroll reveals a different card and
Pyromancy discards one with a different mana value on the two tables, and
both read as a missed target and a bystander; an oracle comparing where each
table *ends* also charges the seven "discard a card at random" costs (Coral
Helm, Stormbind, Mage il-Vec, …) to the engine. Measured both ways on the
fixed tree: with the reseeding switched off that oracle reproduces the
earlier draft's 14 "differs" and 4 "missed" exactly, and with it on both are
0.

**A case whose own cost took the permanent it named is set aside**
(``paid_with_the_target``, 5 in the pool): "Sacrifice an enchantment: Destroy
target enchantment" sacrifices the target while its activator controls it and
the source once it does not, so the two tables differ by a payment, not by
the change of hands.

Every announcement in the pool that owes one target and can name a permanent
(the population ``test_bare_announcement_census`` sweeps), and every
non-modal triggered ability whose printed line chooses a target and whose own
picker asks for it (the population ``test_targeted_trigger_census`` sweeps),
in both directions: the opponent's permanent taken by the announcer, and the
announcer's own taken by the opponent. A sample of each each run, by a hash
of the label; ``python -m tests.regressions.test_target_changed_controller_census``
runs all of it and prints the tallies.
"""

from __future__ import annotations

import random
import zlib
from collections import Counter

import pytest

from engine import faces
from engine.control import change_control
from engine.modal_triggers import modal_trigger_modes
from engine.oracle import compile_card_oracle
from engine.stack_targets import names_a_target

from .test_bare_announcement_census import (
    _announce, _finish, _labels, _past_the_id_floor, _picker, _rows, _state, _table,
)

#: One announcement in this many, each run.
_SAMPLE = 10
#: One triggered ability in this many, each run.
_TRIGGER_SAMPLE = 3


#: What gives control away in response. One object, so the contribution it
#: records spells the same on both tables.
class _Thief:
    def __repr__(self) -> str:
        return "<a control change made in response>"


_THIEF = _Thief()


def _sampled(label: str, share: int) -> bool:
    return zlib.crc32(label.encode("utf-8")) % share == 0


def _reseed() -> None:
    random.seed(4242)


def _take(game, permanent, seat) -> None:
    change_control(permanent, seat, source=_THIEF)
    game._sync_control()
    game._recompute_continuous_effects()


def _resolve(game) -> None:
    _reseed()
    _finish(game)


def _first_offered(game, side, card, source, which, seat):
    """The label-able permanent the picker offers first on *seat*, or None."""
    for entry in _picker(game, side, card, source, which):
        if entry.get("kind") != "permanent" or entry.get("seat") != seat:
            continue
        permanent = game.permanent_at(game.players[entry["seat"]], entry["index"])
        if permanent is not None and permanent is not source:
            return permanent
    return None


def _changes(before, after) -> tuple:
    """What a resolution did, read off two ``_state`` snapshots of one table:
    ``({label: its new state}, [per seat: (life, hand, library, shields)
    moved by], [per seat: the cards its graveyard gained and lost])``."""
    permanents = {
        key: after[0][key] for key in after[0] if after[0][key] != before[0][key]
    }
    players = [
        tuple(now - then for now, then in zip(after_seat, before_seat))
        for after_seat, before_seat in zip(after[1], before[1])
    ]
    graveyards = [
        (
            sorted((Counter(now) - Counter(then)).elements()),
            sorted((Counter(then) - Counter(now)).elements()),
        )
        for now, then in zip(after[2], before[2])
    ]
    return permanents, players, graveyards


def _new_tally() -> dict:
    return {
        "cases": 0, "admitted": 0, "not_admitted": 0, "rows": 0,
        "missed": [], "bystander": [], "acted_on_inadmissible": [], "differs": [],
        "refused_by_description": [], "paid_with_the_target": [],
    }


def _judge(found, where, key, source_key, admitted, did, wanted) -> None:
    """Score one resolved case. *did* is what the resolution changed on the
    table where control changed in response; *wanted* is what it changed on
    the twin (None where the twin refused the announcement)."""
    found["cases"] += 1
    if admitted:
        found["admitted"] += 1
        if did[0].get(key) != wanted[0].get(key):
            found["missed"].append(where)
        strays = sorted(
            other for other in set(did[0]) | set(wanted[0])
            if other != key and did[0].get(other) != wanted[0].get(other)
        )
        if strays:
            found["bystander"].append((where, strays[:3]))
        if did[0] == wanted[0] and did[1:] != wanted[1:]:
            found["differs"].append(where)
        return
    found["not_admitted"] += 1
    found["refused_by_description"].append(where)
    if key in did[0]:
        found["acted_on_inadmissible"].append(where)
    strays = sorted(other for other in did[0] if other not in (key, source_key))
    if strays:
        found["bystander"].append((where, strays[:3]))


def sweep(catalog, by_name, *, sample: bool = True, only=None) -> dict:
    """Casts and activations."""
    found = _new_tally()
    _past_the_id_floor()
    for side, label, card, which, kind in _rows(catalog, only):
        if sample and only is None and not _sampled(label, _SAMPLE):
            continue
        build = lambda: _table(  # noqa: E731 - one board, built several times
            card, by_name, as_source=side == "act", masked=False,
        )
        examined_row = False
        for from_seat, to_seat in ((1, 0), (0, 1)):
            game, source = build()
            if side == "act" and not game.is_on_battlefield(source):
                break
            labelled = _labels(game)
            named = _first_offered(game, side, card, source, which, from_seat)
            if named is None:
                continue
            key = next(k for k, perm in labelled.items() if perm is named)
            source_key = next(
                (k for k, perm in labelled.items() if perm is source), None
            )

            # The twin: control changes first, and then the announcement.
            twin, twin_source = build()
            twin_labels = _labels(twin)
            twin_named = twin_labels[key]
            _take(twin, twin_named, to_seat)
            _reseed()
            admitted = _announce(
                twin, side, card, twin_source, which,
                target_permanent_ids=[twin_named.permanent_id],
            ).supported

            _reseed()
            result = _announce(
                game, side, card, source, which, target_permanent_ids=[named.permanent_id],
            )
            if not result.supported:
                continue    # a cost the table cannot pay, a timing gate
            where = f"{label} [{kind}] {key} taken by seat {to_seat}"
            if not game.is_on_battlefield(named) or (
                admitted and not twin.is_on_battlefield(twin_named)
            ):
                # The announcement's own cost took the permanent it named, on
                # one table and not the other ("Sacrifice an enchantment:
                # Destroy target enchantment", Arenson's Aura, sacrifices the
                # target while the activator controls it and the source once
                # it does not). The costs were paid on two different boards;
                # the case is about the payment, not the change of hands.
                found["paid_with_the_target"].append(where)
                continue
            _take(game, named, to_seat)
            before = _state(game, labelled)
            _resolve(game)
            did = _changes(before, _state(game, labelled))
            wanted = None
            if admitted:
                twin_before = _state(twin, twin_labels)
                _resolve(twin)
                wanted = _changes(twin_before, _state(twin, twin_labels))
            examined_row = True
            _judge(found, where, key, source_key, admitted, did, wanted)
        found["rows"] += examined_row
    return found


# ---------------------------------------------------------------------------
# Triggered abilities whose target was chosen (CR 603.3d)
# ---------------------------------------------------------------------------


def _trigger_rows(catalog, only=None):
    """``(label, card, trig)`` for every supported non-modal triggered ability
    whose printed line chooses a target."""
    units = [face for card in catalog for face in (faces.face_cards(card) or [card])]
    for card in sorted(units, key=lambda entry: entry.name):
        if only is not None and card.name not in only:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, trig in enumerate(program.triggered_abilities):
            if not trig.supported or trig.instruction is None:
                continue
            if modal_trigger_modes(trig.instruction) or not names_a_target(trig.source_line):
                continue
            yield f"{card.name}#{index}", card, trig


def _trigger_table(card, by_name):
    """The census table with *card* entered for seat 0 and whatever it did as
    it entered resolved — or None where it did not stay."""
    game, source = _table(card, by_name, as_source=True, masked=False)
    if source is None or not game.is_on_battlefield(source):
        return None, None
    _finish(game)
    if not game.is_on_battlefield(source):
        return None, None
    return game, source


def _put_trigger(game, source, trig):
    """Put *trig* on the stack for its source's controller, with that seat
    asked to choose its target. The ``trigger_target`` prompt, or None where
    the ability asked nothing (it was removed for want of a legal target, its
    fire site would bind one, or its picker makes no choice)."""
    game.interactive_seats = {0, 1}
    _reseed()
    game._enqueue_triggered_ability(
        controller_index=game.controller_index_of(source),
        source_permanent=source, instruction=trig.instruction,
        effect_kind=trig.effect_kind, ability_text=trig.source_line,
    )
    return next(
        (choice for choice in game.pending_choices if choice.kind == "trigger_target"),
        None,
    )


def _offered_ids(choice) -> list:
    return [
        target.get("permanent_id")
        for target in (choice.data.get("targets") or ())
        if target.get("kind", "permanent") == "permanent"
    ]


def sweep_triggers(catalog, by_name, *, sample: bool = True, only=None) -> dict:
    """Triggered abilities whose own picker chose their target."""
    found = _new_tally()
    _past_the_id_floor()
    for label, card, trig in _trigger_rows(catalog, only):
        if sample and only is None and not _sampled(label, _TRIGGER_SAMPLE):
            continue
        examined_row = False
        for from_seat, to_seat in ((1, 0), (0, 1)):
            game, source = _trigger_table(card, by_name)
            if game is None:
                break
            asked = _put_trigger(game, source, trig)
            if asked is None:
                game.interactive_seats = set()
                break
            labelled = _labels(game)
            ids = {perm.permanent_id: key for key, perm in labelled.items()}
            named = next(
                (
                    game.permanent_by_id(permanent_id)
                    for permanent_id in _offered_ids(asked)
                    if permanent_id in ids
                    and game.permanent_by_id(permanent_id) is not source
                    and game.controller_index_of(game.permanent_by_id(permanent_id))
                    == from_seat
                ),
                None,
            )
            if named is None:
                continue
            key = ids[named.permanent_id]
            source_key = ids.get(source.permanent_id)

            # The twin: control changes first, and then the trigger chooses.
            twin, twin_source = _trigger_table(card, by_name)
            twin_labels = _labels(twin)
            twin_named = twin_labels[key]
            _take(twin, twin_named, to_seat)
            twin_asked = _put_trigger(twin, twin_source, trig)
            admitted = bool(
                twin_asked is not None
                and twin_named.permanent_id in _offered_ids(twin_asked)
                and twin.confirm_trigger_target(
                    twin_asked.player_index, permanent_id=twin_named.permanent_id,
                )
            )
            twin.interactive_seats = set()

            if not game.confirm_trigger_target(asked.player_index, permanent_id=named.permanent_id):
                game.interactive_seats = set()
                continue
            game.interactive_seats = set()
            _take(game, named, to_seat)
            before = _state(game, labelled)
            _resolve(game)
            did = _changes(before, _state(game, labelled))
            wanted = None
            if admitted:
                twin_before = _state(twin, twin_labels)
                _resolve(twin)
                wanted = _changes(twin_before, _state(twin, twin_labels))
            examined_row = True
            _judge(
                found, f"{label} {key} taken by seat {to_seat}",
                key, source_key, admitted, did, wanted,
            )
        found["rows"] += examined_row
    return found


@pytest.fixture(scope="module")
def _catalog():
    from engine.card_loader import load_catalog

    return load_catalog()


@pytest.fixture(scope="module")
def _by_name(_catalog):
    return {card.name: card for card in _catalog}


def _assert_clean(found) -> None:
    assert found["missed"] == [], (
        "CR 608.2b: still a legal target under its new controller, and not "
        f"acted on as it would have been ({len(found['missed'])}): {found['missed'][:16]}"
    )
    assert found["acted_on_inadmissible"] == [], (
        "acted on a permanent its description no longer admits "
        f"({len(found['acted_on_inadmissible'])}): {found['acted_on_inadmissible'][:16]}"
    )
    assert found["bystander"] == [], (
        f"changed a permanent nobody named ({len(found['bystander'])}): "
        f"{found['bystander'][:16]}"
    )
    assert found["differs"] == [], (
        "the named permanent was hit as it would have been and a player was "
        f"not ({len(found['differs'])}): {found['differs'][:16]}"
    )


#: The sampled run's floors (October 2026: 197 cases, 189 admitted and 8 not
#: of the announcements; 50, 45 and 5 of the triggers). A filter that stopped
#: reaching the population would pass every assertion below over nothing.
_MIN_CASES = 170
_MIN_ADMITTED = 160
_MIN_NOT_ADMITTED = 6
_MIN_TRIGGER_CASES = 42
_MIN_TRIGGER_ADMITTED = 38
_MIN_TRIGGER_NOT_ADMITTED = 4


def test_a_target_that_changed_controller_is_found_or_refused_by_its_description(
    _catalog, _by_name,
):
    found = sweep(_catalog, _by_name)

    assert found["cases"] >= _MIN_CASES, found["cases"]
    assert found["admitted"] >= _MIN_ADMITTED, found["admitted"]
    assert found["not_admitted"] >= _MIN_NOT_ADMITTED, found["not_admitted"]
    _assert_clean(found)


def test_a_chosen_trigger_target_that_changed_controller_is_still_its_target(
    _catalog, _by_name,
):
    found = sweep_triggers(_catalog, _by_name)

    assert found["cases"] >= _MIN_TRIGGER_CASES, found["cases"]
    assert found["admitted"] >= _MIN_TRIGGER_ADMITTED, found["admitted"]
    assert found["not_admitted"] >= _MIN_TRIGGER_NOT_ADMITTED, found["not_admitted"]
    _assert_clean(found)


#: What the census named on ``e67196d6``: spells that missed their target
#: (one returns, one destroys) and an activation whose ability prints a second
#: target; a spell that hit its creature and charged "that creature's
#: controller" to the seat it was announced on; and the trigger that hit a
#: bystander instead.
_KNOWN_MISSED = frozenset({"Boomerang", "Terror", "Unsummon", "Cuombajj Witches"})
_KNOWN_DIFFERS = frozenset({"Liquid Fire"})
_KNOWN = _KNOWN_MISSED | _KNOWN_DIFFERS
_KNOWN_TRIGGERS = frozenset({"Nekrataal"})


def test_the_sweep_finds_the_defect_on_the_tree_as_it_was(
    _catalog, _by_name, monkeypatch,
):
    """Backwards: with the seat left where the announcement put it, the same
    sweeps name the cards the census named on ``e67196d6``."""
    from engine.legality_resolution import ResolutionTargetsMixin

    clean = sweep(_catalog, _by_name, only=_KNOWN)
    clean_triggers = sweep_triggers(_catalog, _by_name, only=_KNOWN_TRIGGERS)
    assert clean["admitted"] >= 2 * len(_KNOWN) - 2, clean
    assert clean_triggers["admitted"] >= 2, clean_triggers
    _assert_clean(clean)
    _assert_clean(clean_triggers)

    monkeypatch.setattr(
        ResolutionTargetsMixin, "resettle_announced_target_seats", lambda self, item: 0,
    )
    found = sweep(_catalog, _by_name, only=_KNOWN)
    found_triggers = sweep_triggers(_catalog, _by_name, only=_KNOWN_TRIGGERS)

    def cards(entries) -> set:
        return {
            (entry if isinstance(entry, str) else entry[0]).split(" [")[0].split("[")[0].split("#")[0]
            for entry in entries
        }

    assert cards(found["missed"]) >= _KNOWN_MISSED, found["missed"]
    assert cards(found["differs"]) >= _KNOWN_DIFFERS, found["differs"]
    assert cards(found_triggers["missed"]) >= _KNOWN_TRIGGERS, found_triggers["missed"]
    # Nekrataal destroyed the creature that slid into its target's old slot.
    assert cards(found_triggers["bystander"]) >= _KNOWN_TRIGGERS, found_triggers["bystander"]


def _print(name, tally) -> None:
    print(name, {k: (v if isinstance(v, int) else len(v)) for k, v in tally.items()})
    for part in ("missed", "acted_on_inadmissible", "bystander", "differs"):
        print(" ", part, tally[part][:60])
    print("  refused_by_description", tally["refused_by_description"])
    print("  paid_with_the_target", tally["paid_with_the_target"])


if __name__ == "__main__":  # pragma: no cover - the whole pool, by hand
    import sys
    import time

    from engine.card_loader import load_catalog

    pool = load_catalog()
    by_name = {card.name: card for card in pool}
    sampled = "--sample" in sys.argv
    if "--triggers-only" not in sys.argv:
        started = time.time()
        _print("announcements", sweep(pool, by_name, sample=sampled))
        print("  seconds", round(time.time() - started, 1))
    if "--announcements-only" not in sys.argv:
        started = time.time()
        _print("triggers", sweep_triggers(pool, by_name, sample=sampled))
        print("  seconds", round(time.time() - started, 1))
