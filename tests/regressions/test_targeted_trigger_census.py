"""Census: every targeted trigger, put on the stack and resolved.

How many triggered abilities that print a target reach their handler with no
target stamped, and what do they then act on? Asked of the whole pool on a
table with a shrouded and five protected creatures **first** on each
battlefield — where a handler's scan would look.

Measured (October 2026, all 176 non-modal triggers whose line prints a
target, enqueued from their source with no firing event):

* 117 are **stamped** as they go on the stack, and none carries a target its
  own list (``_trigger_target_candidates``) does not offer;
* 38 are **removed** for having no legal target (CR 603.3d);
* 21 are **bare** — exactly the names ``tests/engine/test_stack_targets.py``
  pins — and for every one of them the trigger has no list at all, which is
  why "stamp each from its picker's list" is not a fix this file can hold;
* and one **raised**: Soldevi Golem, out of its controller's upkeep
  (``test_untap_record_has_one_shape.py``). Nothing else in the suite
  resolved that trigger. That is the statement this file is kept for.

**What this drive cannot say.** It supplies no firing event, so a trigger
narrowed by "that player" or "defending player" has no seat here and is bare
for want of one. Fired for real those are stamped from their own list and
pass over a shrouded permanent — ``test_that_player_trigger_targets.py``
drives four of them. The eight with no list whatever the event (a target
another player chooses, a reflexive "when you do", a roles pair behind "if you
do", a card in a graveyard for "up to two") are named in the round's notes.

A third of the pool each run (one label in three, by its hash); the card that
raised is always among them, so the backwards check has something to find.
"""

from __future__ import annotations

import zlib

import pytest

from engine import faces
from engine.card_loader import load_catalog
from engine.modal_triggers import modal_trigger_modes
from engine.oracle import compile_card_oracle
from engine.stack_targets import chosen_targets, names_a_target

from .test_bare_announcement_census import _finish, _labels, _past_the_id_floor, _table

#: One label in this many.
_SAMPLE = 3
#: …and these whatever their hash: the trigger that raised.
_ALWAYS = frozenset({"Soldevi Golem#0"})

# 60 examined a run, of which 43 stamped, 9 removed and 8 bare (October 2026).
_MIN_EXAMINED = 48
_MIN_STAMPED = 34


def _sampled(label: str) -> bool:
    return label in _ALWAYS or zlib.crc32(label.encode("utf-8")) % _SAMPLE == 0


def _sweep(only=None) -> dict:
    catalog = load_catalog()
    by_name = {card.name: card for card in catalog}
    found = {"examined": 0, "stamped": 0, "removed": 0, "bare": [], "unoffered": [], "raised": []}
    _past_the_id_floor()
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
            label = f"{card.name}#{index}"
            if only is None and not _sampled(label):
                continue
            game, source = _table(card, by_name, as_source=True, masked=False)
            if source is None or not game.is_on_battlefield(source):
                continue
            _finish(game)   # whatever it did as it entered
            if not game.is_on_battlefield(source):
                continue
            found["examined"] += 1
            ids = {perm.permanent_id: key for key, perm in _labels(game).items()}
            depth = len(game.stack)
            try:
                game._enqueue_triggered_ability(
                    controller_index=game.controller_index_of(source),
                    source_permanent=source, instruction=trig.instruction,
                    effect_kind=trig.effect_kind, ability_text=trig.source_line,
                )
                if len(game.stack) <= depth:
                    found["removed"] += 1
                    continue
                item = game.stack[depth]
                targets = chosen_targets(game, item)
                offer = game._trigger_target_candidates(item, announced=True)
                if not targets:
                    found["bare"].append(label)
                else:
                    found["stamped"] += 1
                    if offer is not None:
                        offered = {
                            game.permanent_at(entry["seat"], entry["index"]).permanent_id
                            for entry in offer[2] if entry.get("kind") == "permanent"
                        }
                        for target in targets:
                            if target.kind == "permanent" and target.permanent_id not in offered:
                                found["unoffered"].append((label, ids.get(target.permanent_id)))
                _finish(game)
            except Exception as error:  # noqa: BLE001 - the finding is that it raised
                found["raised"].append((label, f"{type(error).__name__}: {error}"))
    return found


def test_every_targeted_trigger_resolves_and_none_is_stamped_off_its_own_list():
    found = _sweep()

    assert found["examined"] >= _MIN_EXAMINED, found["examined"]
    assert found["stamped"] >= _MIN_STAMPED, found["stamped"]
    assert found["raised"] == [], (
        f"a triggered ability raised while resolving: {found['raised']}"
    )
    assert found["unoffered"] == [], (
        "stamped with a target its own list does not offer (CR 603.3d): "
        f"{found['unoffered']}"
    )


def test_the_sweep_sees_a_trigger_that_raises(monkeypatch):
    """Backwards: the line that shipped, put back for the one card it broke."""
    from engine.handlers import EFFECT_HANDLERS

    def as_shipped(game, instruction, context):
        context.results.setdefault("untapped_permanents", []).append(
            context.source_permanent.permanent_id
        )
        return True, "resolved"

    monkeypatch.setitem(EFFECT_HANDLERS, "untap_self", as_shipped)

    found = _sweep(only={"Soldevi Golem"})

    assert [label for label, _error in found["raised"]] == ["Soldevi Golem#0"]
    assert "append" in found["raised"][0][1]
