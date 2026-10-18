"""``engine/target_requirements.py`` over the whole pool: with an opposing
Flagbearer on the battlefield, what may every targeted cast and activation
announce?

"While an opponent is choosing targets as part of casting a spell they control
or activating an ability they control, that player must choose at least one
Flagbearer on the battlefield if able." One permanent with that sentence
changes what *every* targeted spell and activated ability in the pool may name,
so the question is asked of every one of them rather than of a handful.

**Measured before it was enforced** (Apocalypse wave 1, with the sentence on
the board and nothing reading it): of the announcements this sweep drives, 945
one-slot announcements could have named the Flagbearer — 267 instants and
sorceries, 265 Auras, 413 activated abilities — and **877 of them accepted a
target that was not one** (of the other 68, 66 were refused for reasons of
their own and two had nothing else to name); 74 more had several slots, a
division or roles and were not probed.

**And after**: 532 one-slot casts and 405 one-slot activations are bound (the
eight activations that left the count were never targets — a Circle's chosen
source, an "X target" at an X of zero), none accepts another target (526 and
403 refusals by the requirement, the rest having nothing else to name), and
523 and 350 announcements naming the Flagbearer are accepted. Of 68 + 13
announcements with several slots, 72 with no Flagbearer in them are refused
and 68 naming it beside something else are accepted. The same sweep is the
test below, and its invariants are the rule:

1. **Nothing the picker does not offer was bound.** Where the Flagbearer is
   not among an announcement's legal targets (the wrong type, a player-only
   spell, a card in a graveyard, a spell on the stack) the picker's list is the
   list it was — "if able".
2. **One slot: the list is the Flagbearers in it**, an announcement naming
   anything else is refused with nothing spent, and naming the Flagbearer is
   accepted and reads back as the target. An announcement naming nothing is
   given the first entry of that narrowed list — the Flagbearer
   (``bare_announcements``) — and reads it back too.
3. **Several slots, a division, roles: the list stays whole** and carries
   ``required_targets``; an announcement with no Flagbearer in it is refused,
   and one that names the Flagbearer *beside something else* is accepted.
4. **A permanent spell's entry-trigger picker is never narrowed** — a
   triggered ability "doesn't have to target a Flagbearer" (ruling,
   2016-06-08).

The bearer is an invented card carrying the sentence under another name, so
nothing here can pass against a table keyed by a card name, and "is it the
bearer" is asked of that card object, not of the engine's reading of a subtype.

**Validated backwards**: with the board reader switched off, and with only the
cast gate switched off, the sweep has to go red for the cards that then
mis-announce.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState, faces, target_requirements
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import chosen_targets
from engine.targeting import (ROLES_TARGET_KIND, derive_activation_spec,
                              derive_cast_spec, spec_is_a_cost,
                              usable_activated_abilities)

from tests.engine.test_stack_targets import _UNFLAGGED_NON_TARGETS
from tests.helpers import _mk_card, _nosick


_SENTENCE = (
    "While an opponent is choosing targets as part of casting a spell they "
    "control or activating an ability they control, that player must choose at "
    "least one Flagbearer on the battlefield if able."
)

_BEARER = _mk_card(
    name="Test Bannerman", type_line="Creature - Human Flagbearer",
    oracle_text=_SENTENCE, power=1, toughness=1,
)

_REFUSAL = "must be chosen as a target if able"

#: Derived kinds with no battlefield picker in front of the announcement.
_NO_PICKER = frozenset({None, "none", "modal", "faces", "hand_card"})


def _pool() -> list:
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
    return [
        _mk_card(name="Bait Creature", type_line="Creature - Human Soldier", power=2, toughness=2),
        _mk_card(name="Bait Artifact", type_line="Artifact"),
        _mk_card(name="Bait Enchantment", type_line="Enchantment"),
        _mk_card(name="Bait Land", type_line="Land"),
        _mk_card(name="Bait Artifact Creature", type_line="Artifact Creature - Golem", power=3, toughness=3),
    ] + [by_name[name] for name in ("Forest", "Island", "Swamp", "Mountain", "Plains")]


def _board(by_name, source_card=None, hand=()):
    """A mirrored two-seat board, the announcing seat's opponent holding the
    bearer. Mirrored for ``test_stack_targets``' reason: with one side empty a
    reader that ignored the announcement would still land on the right
    permanent."""
    yard = [by_name[name] for name in ("Grizzly Bears", "Sol Ring", "Lightning Bolt", "Forest", "Crusade")]
    source = _nosick(Permanent(card=source_card)) if source_card is not None else None
    mine = ([source] if source is not None else []) + [_nosick(Permanent(card=c)) for c in _bait(by_name)]
    theirs = [_nosick(Permanent(card=c)) for c in _bait(by_name)] + [_nosick(Permanent(card=_BEARER))]
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


def _put_a_spell_on_the_stack(game, by_name) -> None:
    game.players[1].hand.append(by_name["Giant Growth"])
    creature = next(p for p in game.controlled_by(1) if p.card.name == "Bait Creature")
    game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[creature.permanent_id])


def _flat(entries) -> list:
    """Every entry of an offer, a roles tree's nested ``next`` included."""
    found: list = []
    for entry in entries or ():
        found.append(entry)
        found.extend(_flat(entry.get("next")))
    return found


def _permanent(game, entry):
    if entry.get("kind") != "permanent":
        return None
    return game.permanent_at(entry["seat"], entry["index"])


def _is_bearer(game, entry) -> bool:
    permanent = _permanent(game, entry)
    return permanent is not None and permanent.card is _BEARER


def _names(game, entry) -> dict | None:
    """One offered entry as announcement keywords."""
    if entry.get("kind") == "permanent":
        return {"target_permanent_ids": [_permanent(game, entry).permanent_id]}
    if entry.get("kind") == "player":
        return {"target_player_index": entry["seat"]}
    return None


def _chains(game, entries, wanted: bool, prefix=()) -> list | None:
    """The first complete roles chain made only of permanents that does
    (*wanted*) or does not include the bearer, as ids."""
    for entry in entries or ():
        permanent = _permanent(game, entry)
        if permanent is None:
            continue
        chain = prefix + (permanent,)
        if entry.get("next"):
            found = _chains(game, entry["next"], wanted, chain)
            if found is not None:
                return found
            continue
        if any(p.card is _BEARER for p in chain) == wanted:
            return [p.permanent_id for p in chain]
    return None


class _Census:
    def __init__(self) -> None:
        self.counts: Counter = Counter()
        self.wrong: list[str] = []

    def judge(
        self, label, game, legal, offered, announce, source=None,
        bare_is_refused: bool = False,
    ) -> None:
        """One announcement. *legal* is the un-narrowed offer, *offered* the
        picker's, *announce* queues it with the given target keywords and
        returns ``(accepted, details, stack item)``. *bare_is_refused* is the
        cast side's extra probe: an announcement naming nothing at all —
        which is given the first entry of the narrowed list
        (``bare_announcements.default_cast_target``), so it is accepted naming
        the Flagbearer. (The keyword keeps its name for the activation sweep's
        callers; it has not meant "refused" since bare announcements were
        answered at the announcement.)"""
        counts, wrong = self.counts, self.wrong
        entries = legal.get("valid_targets") or []
        if (
            spec_is_a_cost(legal)
            or legal.get("source_of_choice") or legal.get("optional")
            # …and the pickers that are not targets and whose derived spec
            # does not say so (the Circles' and Runes' "a source of your
            # choice"): the list ``test_stack_targets`` pins, so "what is a
            # target" is one statement about the pool and not two.
            or label in _UNFLAGGED_NON_TARGETS
        ):
            # A payment, a chosen source, a copy: not a target, never bound.
            if offered.get("valid_targets") != entries or "required_targets" in offered:
                wrong.append(f"{label}: a picker that is not a target was narrowed")
            counts["not a target"] += 1
            return
        bearers = [entry for entry in _flat(entries) if _is_bearer(game, entry)]
        slots = legal.get("max_targets")
        if isinstance(slots, int) and slots <= 0:
            # "Up to X target permanents" at an X the board has fixed at zero
            # (Recantation with no verse counter): no target is chosen, so
            # nobody is able to choose a Flagbearer.
            bearers = []
        if not bearers:
            if offered.get("valid_targets") != entries or "required_targets" in offered:
                wrong.append(f"{label}: narrowed with no Flagbearer among its legal targets")
            counts["unbound"] += 1
            return
        bearer_id = _permanent(game, bearers[0]).permanent_id
        required = {entry.get("id") for entry in offered.get("required_targets") or ()}
        if bearer_id not in required:
            wrong.append(f"{label}: the Flagbearer is legal and the picker does not require it")
            return
        zone_before = (len(game.stack), len(game.players[0].hand))

        def refused(keywords, what) -> "bool | None":
            """Whether the requirement refused it — None once the game has
            been spoiled for the probes behind this one."""
            accepted, details, _item = announce(keywords)
            if accepted:
                wrong.append(f"{label}: accepted {what}")
                return None
            if (len(game.stack), len(game.players[0].hand)) != zone_before:
                wrong.append(f"{label}: refused {what} and something moved")
                return None
            return _REFUSAL in (details or "")

        def obeyed(keywords, bucket) -> None:
            accepted, _details, item = announce(keywords)
            if not accepted:
                counts[f"{bucket}: refused for its own reasons"] += 1
                return
            targets = chosen_targets(game, item) or ()
            if not any(
                t.kind == "permanent" and t.permanent_id == bearer_id for t in targets
            ):
                wrong.append(f"{label}: accepted naming the Flagbearer, read {targets}")
                return
            counts[f"{bucket}: accepted"] += 1

        others = [
            entry for entry in entries
            if entry.get("kind") in ("permanent", "player")
            and not _is_bearer(game, entry)
            and _permanent(game, entry) is not source
        ]
        if target_requirements.one_slot(legal):
            narrowed = [entry for entry in entries if _is_bearer(game, entry)]
            if offered.get("valid_targets") != narrowed:
                wrong.append(f"{label}: one slot, and the picker offers more than Flagbearers")
                return
            counts["one slot: bound"] += 1
            if others:
                answer = refused(_names(game, others[0]), "a target that is not a Flagbearer")
                if answer is None:
                    return
                counts["one slot: another target refused"] += answer
            obeyed(_names(game, bearers[0]), "one slot, the Flagbearer")
            if bare_is_refused:
                # Last, because an accepted cast spends the card: the announce
                # puts it back in hand for this probe.
                obeyed({}, "one slot, nothing named")
            return

        if offered.get("valid_targets") != entries:
            wrong.append(f"{label}: several slots, and the picker's list was narrowed")
            return
        counts["several slots: bound"] += 1
        kind = legal.get("kind")
        if kind == ROLES_TARGET_KIND:
            without = _chains(game, entries, wanted=False)
            mixed = _chains(game, entries, wanted=True)
            if without:
                answer = refused({"target_permanent_ids": without}, "roles with no Flagbearer")
                if answer is None:
                    return
                counts["several slots: none named refused"] += answer
            if mixed:
                obeyed({"target_permanent_ids": mixed}, "several slots, mixed")
            return
        if kind == "divided":
            if others and others[0].get("kind") == "permanent":
                entry = others[0]
                answer = refused(
                    {"divided_targets": [(entry["seat"], entry["index"])]},
                    "a division with no Flagbearer",
                )
                if answer is None:
                    return
                counts["several slots: none named refused"] += answer
            entry = bearers[0]
            obeyed({"divided_targets": [(entry["seat"], entry["index"])]}, "several slots, mixed")
            return
        ceiling = legal.get("max_targets")
        ceiling = ceiling if isinstance(ceiling, int) and ceiling > 1 else 2
        plain = [
            _permanent(game, entry).permanent_id for entry in others
            if entry.get("kind") == "permanent"
        ]
        if plain:
            answer = refused(
                {"target_permanent_ids": plain[:ceiling]}, "several targets, none a Flagbearer"
            )
            if answer is None:
                return
            counts["several slots: none named refused"] += answer
        obeyed(
            {"target_permanent_ids": [bearer_id, *plain[:ceiling - 1]]},
            "several slots, mixed",
        )


def _sweep_casts(pool, by_name, only=None) -> _Census:
    census = _Census()
    for card in pool:
        for face in (faces.face_cards(card) or [card]):
            if only is not None and face.name not in only:
                continue
            if face.primary_type == "land":
                continue
            program = compile_card_oracle(face)
            if not program.supported:
                continue
            if program.modes and program.mode_chooser is not None:
                continue
            for mode in (range(len(program.modes)) if program.modes else (None,)):
                derived = derive_cast_spec(face, program, mode_index=mode)
                if derived is None or derived.get("kind") in _NO_PICKER:
                    continue
                game, _ = _board(by_name, hand=[card])
                legal = game.cast_target_spec(0, face, mode_index=mode, requirements=False)
                if legal.get("kind") in ("stack", "spell_or_permanent") or legal.get("also_stack"):
                    _put_a_spell_on_the_stack(game, by_name)
                    legal = game.cast_target_spec(0, face, mode_index=mode, requirements=False)
                offered = game.cast_target_spec(0, face, mode_index=mode)
                label = f"cast:{face.name}" + ("" if mode is None else f"@{mode}")
                if not target_requirements.cast_is_bound(face):
                    # A permanent spell: the picker is its entry trigger's.
                    if offered != legal:
                        census.wrong.append(f"{label}: an entry trigger's picker was narrowed")
                    census.counts["entry trigger: never bound"] += 1
                    continue

                def announce(keywords, game=game, face=face, mode=mode, card=card):
                    if not any(held is card for held in game.players[0].hand):
                        game.players[0].hand.append(card)
                    before = len(game.stack)
                    extra = {} if mode is None else {"mode_index": mode}
                    result = game.queue_from_hand(0, face.name, **(keywords or {}), **extra)
                    accepted = bool(result.supported and len(game.stack) > before)
                    return accepted, result.details, game.stack[before] if accepted else None

                census.judge(label, game, legal, offered, announce, bare_is_refused=True)
    return census


def _sweep_activations(pool, by_name, only=None) -> _Census:
    census = _Census()
    units = [face for card in pool for face in (faces.face_cards(card) or [card])]
    for card in units:
        if only is not None and card.name not in only:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None:
                continue
            derived = derive_activation_spec(ability)
            if derived is None or derived.get("kind") in _NO_PICKER:
                continue
            game, source = _board(by_name, card)
            if game.controller_index_of(source) != 0:
                continue
            slot = game.battlefield_index_of(source)
            legal = game.activation_offer(0, source, ability)
            if legal.get("kind") in ("stack", "spell_or_permanent") or legal.get("also_stack"):
                continue
            offered = game.activation_target_spec(0, slot, ability_index=index)

            def announce(keywords, game=game, card=card, index=index, source=source):
                before = len(game.stack)
                result = game.queue_permanent_ability(
                    0, card.name, ability_index=index, **(keywords or {})
                )
                accepted = bool(
                    result.supported and result.details == "queued"
                    and len(game.stack) > before
                )
                return accepted, result.details, game.stack[before] if accepted else None

            census.judge(f"act:{card.name}#{index}", game, legal, offered, announce, source)
    return census


def test_every_cast_is_held_to_a_flagbearer_on_the_other_side(pool, by_name):
    """CR 601.2c under Standard Bearer's sentence, over every instant, sorcery
    and Aura in the pool, mode by mode — and every permanent spell's entry
    trigger picker, which is never bound."""
    census = _sweep_casts(pool, by_name)
    assert not census.wrong, f"{len(census.wrong)}: {sorted(census.wrong)[:12]}"
    counts = census.counts
    # Floors well inside what the pool measures (see the module docstring), so
    # an ordinary ingest does not move them and a sweep that stopped reaching
    # the gate cannot pass.
    assert counts["one slot: bound"] > 430, dict(counts)
    assert counts["one slot: another target refused"] > 400, dict(counts)
    # The instants and sorceries alone: an Aura cast naming nothing is refused
    # a gate earlier, for want of anything to enchant. The rest name the
    # Flagbearer the narrowed picker offers first.
    assert counts["one slot, nothing named: accepted"] > 200, dict(counts)
    assert counts["one slot, the Flagbearer: accepted"] > 400, dict(counts)
    assert counts["unbound"] > 250, dict(counts)
    assert counts["several slots: bound"] > 40, dict(counts)
    assert counts["several slots: none named refused"] > 20, dict(counts)
    assert counts["several slots, mixed: accepted"] > 20, dict(counts)
    assert counts["entry trigger: never bound"] > 40, dict(counts)


def test_every_activation_is_held_to_a_flagbearer_on_the_other_side(pool, by_name):
    """CR 602.2b, the same sweep over every activated ability with a picker."""
    census = _sweep_activations(pool, by_name)
    assert not census.wrong, f"{len(census.wrong)}: {sorted(census.wrong)[:12]}"
    counts = census.counts
    assert counts["one slot: bound"] > 330, dict(counts)
    assert counts["one slot: another target refused"] > 280, dict(counts)
    assert counts["one slot, the Flagbearer: accepted"] > 280, dict(counts)
    assert counts["unbound"] > 200, dict(counts)


# -- validated backwards --------------------------------------------------------

_BACKWARDS = frozenset({
    "Lightning Bolt", "Terror", "Giant Growth", "Pacifism", "Fireball",
    "Prodigal Sorcerer", "Royal Assassin", "Nekrataal", "Wrath of God",
})


def test_the_census_sees_a_board_nobody_reads(pool, by_name, monkeypatch):
    """With the board reader answering "no requirement", the pickers stop
    narrowing and both gates stop refusing — and the census names it, for the
    cards the Flagbearer binds and not for the ones it does not."""
    assert not _sweep_casts(pool, by_name, only=_BACKWARDS).wrong
    assert not _sweep_activations(pool, by_name, only=_BACKWARDS).wrong

    monkeypatch.setattr(target_requirements, "requirements_binding", lambda game, chooser: [])

    casts = "\n".join(_sweep_casts(pool, by_name, only=_BACKWARDS).wrong)
    activations = "\n".join(_sweep_activations(pool, by_name, only=_BACKWARDS).wrong)
    for name in ("Lightning Bolt", "Terror", "Giant Growth", "Pacifism"):
        assert f"cast:{name}: the Flagbearer is legal and the picker does not require it" in casts
    assert "act:Prodigal Sorcerer#0: the Flagbearer is legal" in activations
    assert "Nekrataal" not in casts and "Wrath of God" not in casts


def test_the_census_sees_a_cast_gate_that_stopped_asking(pool, by_name, monkeypatch):
    """…and with the picker still narrowing but the cast gate gone, the list
    is right and the announcement is not held to it."""
    monkeypatch.setattr(
        Game, "cast_target_requirement_refusal", lambda self, *args, **kwargs: None
    )
    casts = "\n".join(_sweep_casts(pool, by_name, only=_BACKWARDS).wrong)
    assert "cast:Lightning Bolt: accepted a target that is not a Flagbearer" in casts
    assert "cast:Terror: accepted a target that is not a Flagbearer" in casts
    assert "Nekrataal" not in casts
