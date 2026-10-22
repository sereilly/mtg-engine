"""Destroying a permanent is one event, whichever of the engine's paths performs
it — and the event says who caused it (``engine/destruction_events.py``).

Odyssey's Karmic Justice — "Whenever a spell or ability an opponent controls
destroys a noncreature permanent you control, you may destroy target permanent
that opponent controls" — asks a question no board can answer afterwards: a
destroyed artifact, a sacrificed one and one a state-based action put there are
the same card in the same graveyard, and CR 701.8b says only the first was
destroyed. So the destruction is announced where it is decided, with the seat
CR 109.5 gives the spell or ability that did it.

**The census.** Every printed sentence with the word "destroy" in both manifest
roles (CR 701.8b: "an effect that uses the word 'destroy'") is driven the way a
game drives it, and every departure for a graveyard is classified by *where it
came from* — never by what the engine announced:

=====================  ==================================================
through a destroy seam  a destruction, caused by the resolving object's seat
…under ``704.5g/h``     a destruction, caused by no spell or ability
…under ``704.5f/i/m``   "put into its owner's graveyard": not a destruction
``sacrifice_permanent`` CR 701.21a: not a destruction
anything else           round the seam — named, and each one has to be read
=====================  ==================================================

On the tree before the seam it read **999 destructions, 0 announced**, with two
sites round the seam: Chaos Orb, which destroyed indestructible permanents and
ignored regeneration, and Kudzu. On this tree: 0 unannounced, 0 with the wrong
cause, and an opponent's watcher triggered for every one of the destructions it
should see and for none it should not. It is **validated backwards** below —
the announcement is switched off, and then the cause — and it carries floors,
because a census that examined nothing reads exactly like one that found
nothing.

The watcher is an invented card with Karmic Justice's condition under another
name and the widest noun phrase the sentence can carry, so nothing here can
pass against a table keyed by a card name.
"""

from __future__ import annotations

import ast
import random
import sys
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine import destruction_events
from engine import events as events_module
from engine import faces
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.destruction_events import (DELAYED_CAUSE_SUFFIX,
                                       NO_SPELL_OR_ABILITY,
                                       PERMANENT_DESTROYED)
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack
from tests.source_index import python_files, source_tree


# ---------------------------------------------------------------------------
# Fixtures: the pool, the bait and the watcher
# ---------------------------------------------------------------------------

_WATCHER_TEXT = (
    "Whenever a spell or ability an opponent controls destroys a permanent "
    "you control, you gain 1 life."
)


def _plain(name, type_line, text="", *, power=None, toughness=None, colors=(),
           keywords=()) -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=tuple(colors), color_identity=tuple(colors), keywords=tuple(keywords),
        produced_mana=(), raw=raw,
    )


def _watcher(seat: int) -> CardDefinition:
    return _plain(f"Test Watcher {seat}", "Enchantment", _WATCHER_TEXT)


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
    """One plain permanent of each printed type, a Wall, a black creature and
    every basic land — so most "destroy target …" phrases find something on
    either side, and nothing on the board has an ability of its own to put
    between a destruction and its announcement."""
    return [
        _plain("Bait Creature", "Creature - Human Soldier", power=2, toughness=2),
        _plain("Bait Black Creature", "Creature - Zombie", power=2, toughness=2, colors=("B",)),
        _plain("Bait Wall", "Creature - Wall", power=0, toughness=4),
        _plain("Bait Artifact", "Artifact"),
        _plain("Bait Enchantment", "Enchantment"),
        _plain("Bait Land", "Land"),
        _plain("Bait Artifact Creature", "Artifact Creature - Golem", power=3, toughness=3),
    ] + [by_name[name] for name in ("Forest", "Island", "Swamp", "Mountain", "Plains")]


def _fresh(card) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _board(by_name, *, source_card=None, hand=(), interactive=False):
    """A mirrored two-seat board with a watcher on each side, seat 0 to act."""
    yard = [by_name[n] for n in ("Grizzly Bears", "Sol Ring", "Lightning Bolt", "Forest", "Crusade")]
    source = _fresh(source_card) if source_card is not None else None
    mine = ([source] if source is not None else []) + [_fresh(c) for c in _bait(by_name)]
    theirs = [_fresh(c) for c in _bait(by_name)]
    game = Game(players=[
        PlayerState(name="P0", hand=list(hand), battlefield=mine + [_fresh(_watcher(0))],
                    life=20, graveyard=list(yard), library=[by_name["Forest"]] * 12),
        PlayerState(name="P1", battlefield=theirs + [_fresh(_watcher(1))],
                    life=20, graveyard=list(yard), library=[by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0, 1}
    # No ``start_turn``: a fresh game is already seat 0's main phase with an
    # empty stack, and an untap, an upkeep and a draw step would cost a third
    # of the census to let a source's own upkeep trigger act before anything
    # was measured.
    return game, source


# ---------------------------------------------------------------------------
# The recorder: every departure for a graveyard, and every announcement
# ---------------------------------------------------------------------------

#: The frames that *are* the two destroy seams.
_SEAM_FRAMES = ("_do_destroy", "_destroy_swept_permanents")

#: The state-based predicates handed to the sweep seam, by what CR 704.5 says
#: of each. A predicate on neither list is a state-based move this census has
#: not been told about, and fails it.
_SBA_DESTROYS = frozenset({"_lethally_damaged"})                 # 704.5g / 704.5h
_SBA_PUTS = frozenset({
    "_zero_toughness",      # 704.5f
    "_zero_loyalty",        # 704.5i
    "_illegally_attached",  # 704.5m
    "_saga_done",           # 704.5s — a sacrifice
})
#: …and the end step's delayed sacrifice, which rides the same sweep.
_DELAYED_SACRIFICES = frozenset({"_delayed_eot_sacrifice"})


class _Recorder:
    """Watches one game: ``Game._permanent_to_graveyard`` with the Python frames
    above it (which seam, which state-based predicate, which caller), the
    instruction running at the time, and every ``permanent_destroyed`` event
    the bus collected with the triggers it found."""

    def __init__(self) -> None:
        self.departures: list[dict] = []
        self.announced: list[tuple] = []
        self.fired: Counter = Counter()
        self._kinds: list[str] = []

    def __enter__(self) -> "_Recorder":
        rec = self
        self._ptg = Game._permanent_to_graveyard
        self._execute = Game._execute_oracle_instruction
        self._collect = events_module.collect

        def to_graveyard(game, player, permanent):
            via = predicate = site = None
            in_sba = False
            seat = game.controller_index_of(permanent)
            frame, caller = sys._getframe(1), None
            for _ in range(60):
                if frame is None:
                    break
                name = frame.f_code.co_name
                caller = caller or name
                if seat is None and name == "_destroy_target_permanent":
                    # The single-permanent seam removes before it moves.
                    seat = frame.f_locals.get("target_player_index")
                if (
                    via is not None and site is None
                    and name not in _SEAM_FRAMES
                    and name != "_destroy_target_permanent"
                ):
                    site = (frame.f_code.co_filename.replace("\\", "/").split("/")[-1], name)
                if via is None and name in _SEAM_FRAMES:
                    via = name
                    if name == "_destroy_swept_permanents":
                        predicate = getattr(frame.f_locals.get("matches"), "__name__", None)
                if name == "check_state_based_actions":
                    in_sba = True
                frame = frame.f_back
            rec.departures.append({
                "permanent_id": permanent.permanent_id,
                "name": permanent.card.name,
                "seat": seat,
                "sacrificed": bool(permanent.metadata.get("was_sacrificed")),
                "via": via,
                "caller": via or caller,
                "predicate": predicate,
                "site": site,
                "in_sba": in_sba,
                "kind": rec._kinds[-1] if rec._kinds else None,
            })
            return rec._ptg(game, player, permanent)

        def execute(game, instruction, context):
            rec._kinds.append(instruction.kind)
            try:
                return rec._execute(game, instruction, context)
            finally:
                rec._kinds.pop()

        def collect(game, event):
            found = rec._collect(game, event)
            if event.kind == PERMANENT_DESTROYED:
                subject_id = getattr(event.subject, "permanent_id", None)
                rec.announced.append((subject_id, event.payload.get("cause_seat")))
                rec.fired[subject_id] += len(found)
            return found

        Game._permanent_to_graveyard = to_graveyard
        Game._execute_oracle_instruction = execute
        events_module.collect = collect
        return self

    def __exit__(self, *exc) -> None:
        Game._permanent_to_graveyard = self._ptg
        Game._execute_oracle_instruction = self._execute
        events_module.collect = self._collect

    def rows(self, label: str) -> list[dict]:
        causes: dict = {}
        for permanent_id, cause in self.announced:
            causes.setdefault(permanent_id, []).append(cause)
        return [
            {
                **departure,
                "case": label,
                "class": _classify(departure),
                "causes": causes.get(departure["permanent_id"], []),
                "fired": self.fired.get(departure["permanent_id"], 0),
            }
            for departure in self.departures
        ]


def _classify(departure: dict) -> str:
    """What CR 701.8b says a departure is, from where it came."""
    if departure["sacrificed"]:
        return "sacrifice"
    via, predicate = departure["via"], departure["predicate"]
    if via == "_do_destroy":
        return "destroy"
    if via == "_destroy_swept_permanents":
        if departure["in_sba"]:
            if predicate in _SBA_DESTROYS:
                return "destroy_sba"
            if predicate in _SBA_PUTS:
                return "put"
            return f"unknown_sba:{predicate}"
        if predicate in _DELAYED_SACRIFICES:
            return "sacrifice"
        return "destroy"
    return f"round:{departure['caller']}"


# ---------------------------------------------------------------------------
# Driving the pool
# ---------------------------------------------------------------------------


def _first_pick(game, spec, source=None):
    """The first offered target as announcement keywords — a permanent on the
    other side first, so a destruction has an opponent to watch it."""
    entries = sorted(
        spec.get("valid_targets") or [],
        key=lambda entry: 0 if entry.get("seat") == 1 else 1,
    )
    for entry in entries:
        kind = entry.get("kind")
        if kind == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            if permanent is None or permanent is source:
                continue
            if permanent.card.name.startswith("Test Watcher"):
                continue
            return {"target_permanent_ids": [permanent.permanent_id]}
        if kind == "player":
            return {"target_player_index": entry["seat"]}
        if kind == "graveyard":
            return {
                "target_player_index": entry["seat"],
                "target_permanent_index": entry["index"],
            }
        if kind == "stack" and isinstance(entry.get("stack_index"), int):
            return {"target_stack_index": len(game.stack) - 1 - entry["stack_index"]}
    return {}


def _play_out(game) -> None:
    """Resolve everything the announcement started, answer what it asks the way
    a default seat does, and take the game through the two steps a delayed
    destruction waits for (CR 511, CR 513)."""
    def drain() -> None:
        unchecked = True
        for _ in range(60):
            moved = False
            if game.stack and game.resolve_top_of_stack(
                pause_for_choices=bool(game.interactive_seats)
            ):
                moved = True
            before = (len(game.pending_choices), len(game.pending_replacement_choices))
            game.auto_resolve_pending_choices()
            game.auto_resolve_pending_replacement_choices()
            if before != (len(game.pending_choices), len(game.pending_replacement_choices)):
                moved = True
            # CR 704.3: checked when a player would receive priority — once
            # after anything has happened. It is most of what this census
            # costs, so it is not checked again while nothing has.
            unchecked = unchecked or moved
            if unchecked:
                unchecked = False
                if game.check_state_based_actions():
                    moved = True
            if not moved:
                return

    drain()
    # The two steps a delayed destruction waits for, when something is waiting.
    if any(
        isinstance(key, str) and key in _DELAYED_KEYS
        for permanent in game.all_permanents()
        for key in permanent.metadata
    ):
        game._resolve_end_of_combat_destruction()
        drain()
        game.resolve_end_step(game.active_player_index)
        drain()


#: Every mark a turn step acts on for a delayed destruction — and the delayed
#: sacrifice beside them, which leaves by the same sweep and must not be
#: announced.
_DELAYED_KEYS = frozenset({
    "destroy_at_end_of_combat", "destroy_at_next_end_step",
    "destroy_if_did_not_attack_eot", "destroy_if_attacked_eot",
    "destroy_if_did_not_attack_on_seat_turn", "sacrifice_at_next_end_step",
})


def _says_destroy(text) -> bool:
    return "destroy" in (text or "").lower()


def _drive(by_name, unit, how, *, interactive, mode=None, ability_index=None, trig=None):
    """One printed "destroy" sentence, driven; its departures as rows, or None
    when the announcement was refused or the source did not survive setup."""
    random.seed(0)
    if how == "cast":
        game, source = _board(by_name, hand=[faces.whole_card(unit)], interactive=interactive)
    else:
        game, source = _board(by_name, source_card=unit, interactive=interactive)
        if game.controller_index_of(source) != 0:
            return None
    label = f"{how}:{faces.unit_label(unit)}"
    with _Recorder() as rec:
        if how == "cast":
            keywords = {} if mode is None else {"mode_index": mode}
            spec = game.cast_target_spec(0, unit, **keywords)
            keywords.update(_first_pick(game, spec))
            if "{X}" in (unit.mana_cost or ""):
                keywords["x_value"] = 2
            if not game.queue_from_hand(0, unit.name, **keywords).supported:
                return None
        elif how == "activate":
            spec = game.activation_target_spec(
                0, game.battlefield_index_of(source), ability_index=ability_index,
            )
            result = game.queue_permanent_ability(
                0, unit.name, ability_index=ability_index, **_first_pick(game, spec, source),
            )
            if not result.supported:
                return None
        else:
            # A trigger has no announcement a census can make for it, so it is
            # put on the stack with an event context naming the other side's
            # bait — the one driver here that is not the real path, which is
            # why every seam call site is also given a game of its own below.
            victim = next(p for p in game.controlled_by(1) if p.card.name == "Bait Creature")
            wants_that = "that" in (trig.source_line or "").lower()
            game._enqueue_triggered_ability(
                controller_index=0, source_permanent=source,
                instruction=trig.instruction, effect_kind=trig.effect_kind,
                ability_text=trig.source_line,
                target_permanent_id=victim.permanent_id if wants_that else None,
                trigger_context={
                    "event_subject_permanent_id": victim.permanent_id,
                    "event_subject_name": victim.card.name,
                    "event_subject_controller": 1,
                    "event_subject_player": 1,
                    "defending_player_index": 1,
                    "trigger_defending_player_index": 1,
                    "bound_permanent_id": victim.permanent_id,
                    "combat_opponents": [victim],
                    "blocked_permanent_ids": [victim.permanent_id],
                },
            )
        _play_out(game)
    return rec.rows(label)


def _sweep(pool, by_name, *, interactive: bool, only=None) -> tuple[list[dict], Counter]:
    rows: list[dict] = []
    driven: Counter = Counter()
    for unit in faces.compilation_units(pool):
        if only is not None and unit.name not in only:
            continue
        if not _says_destroy(unit.oracle_text):
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        cases = []
        if unit.primary_type in ("instant", "sorcery"):
            modes = (
                [index for index, mode in enumerate(program.modes) if mode.supported]
                if program.modes else [None]
            )
            cases += [("cast", {"mode": mode}) for mode in modes]
        else:
            cases += [
                ("activate", {"ability_index": index})
                for index, ability in enumerate(usable_activated_abilities(program))
                if ability.instruction is not None
            ]
            cases += [
                ("trigger", {"trig": trig})
                for trig in program.triggered_abilities
                if trig.instruction is not None and _says_destroy(trig.source_line)
            ]
        for how, arguments in cases:
            found = _drive(by_name, unit, how, interactive=interactive, **arguments)
            if found is None:
                driven[f"{how}:refused"] += 1
                continue
            driven[how] += 1
            rows.extend(found)
    return rows, driven


#: Destructions still round the seam, by the function that performs them:
#: **none**. Kudzu's old handler was the one entry while this file was written
#: beside the branch that deleted it (the card compiles onto
#: ``destroy_event_subject`` now, which is the seam); it was removed at the
#: merge that brought the two together. Nothing may join this set.
_ROUND_THE_SEAM_UNTIL_W1G8: frozenset[str] = frozenset()


def _faults(rows: list[dict]) -> dict[str, list]:
    """Everything a census row can be wrong about, by name."""
    destroyed = [row for row in rows if row["class"] in ("destroy", "destroy_sba")]
    faults: dict[str, list] = {
        "a destruction nothing announced": [
            (row["case"], row["name"]) for row in destroyed if not row["causes"]
        ],
        "a destruction announced more than once": [
            (row["case"], row["name"]) for row in destroyed if len(row["causes"]) > 1
        ],
        # Every driven object is seat 0's, so CR 109.5's answer is seat 0 for
        # whatever it destroys — and nobody, for what a state-based action did.
        "a destruction with the wrong cause": [
            (row["case"], row["name"], row["causes"]) for row in destroyed
            if row["causes"] and row["causes"] != (
                [0] if row["class"] == "destroy" else [None]
            )
        ],
        "an opponent's watcher that did not trigger exactly once": [
            (row["case"], row["name"], row["fired"]) for row in destroyed
            if row["class"] == "destroy" and row["seat"] == 1 and row["fired"] != 1
        ],
        "a watcher that triggered for its own side's or nobody's destruction": [
            (row["case"], row["name"], row["fired"]) for row in destroyed
            if (row["class"] == "destroy_sba" or row["seat"] == 0) and row["fired"]
        ],
        "a move that is not a destruction, announced as one": [
            (row["case"], row["name"], row["class"]) for row in rows
            if row["class"] in ("sacrifice", "put") and row["causes"]
        ],
        "a move to a graveyard this census cannot classify": [
            (row["case"], row["name"], row["class"]) for row in rows
            if row["class"].startswith("unknown_sba")
            or (
                row["class"].startswith("round:")
                and row["class"][len("round:"):] not in _ROUND_THE_SEAM_UNTIL_W1G8
                and row["class"][len("round:"):] not in _NOT_DESTRUCTIONS_BY_CALLER
            )
        ],
    }
    return {name: found for name, found in faults.items() if found}


#: The functions that move a permanent to a graveyard **outside** the destroy
#: seams, each with why it is not CR 701.8's destruction. The static guard at
#: the bottom of this file holds the engine to exactly this list; the census
#: reads it to tell a move it has been told about from one it has not.
_NOT_DESTRUCTIONS_BY_CALLER: dict[str, str] = {
    "sacrifice_permanent":
        "CR 701.21a — the one sacrifice transition",
    "sacrifice_permanents":
        "CR 701.21a — the same transition for a set that leaves in one event "
        "(Cataclysm's rest, every seat's together)",
    # The sweep's body; `check_state_based_actions` is its CR 603.3b window
    # since round 4.
    "_check_state_based_actions":
        "CR 704.5j legend rule, 704.5k world rule, 704.5m / 702.16c an Aura "
        "that may no longer be where it is, 704.5z the Role rule: each is "
        "'put into its owner's graveyard'",
    "_remove_aura_effects":
        "Animate Dead: 'that creature's controller sacrifices it' (CR 701.21a), "
        "reached without the sacrifice transition",
    "sacrifice_expansion_permanents":
        "Golgothian Sylex: '…is sacrificed by its controller' (CR 701.21a), "
        "reached without the sacrifice transition",
    "take_permanent_in_ownership_exchange":
        "CR 701.12 — an exchange of ownership puts the card in a graveyard",
    "put_self_into_zone":
        "'Put it into your graveyard' — a move, and the card's own word for it",
}

#: Floors, set well inside what the pool measures today (see the report this
#: file's census prints with ``-s``) so an ordinary ingest does not move them
#: and a census that stopped destroying anything cannot pass.
_DESTRUCTION_FLOOR = 400
_WATCHED_FLOOR = 250
_CASE_FLOOR = 300


@pytest.fixture(scope="module")
def census(pool, by_name):
    """The whole-pool sweep, run once per mode per process — two tests read
    the headless one."""
    done: dict = {}

    def run(interactive: bool):
        if interactive not in done:
            done[interactive] = _sweep(pool, by_name, interactive=interactive)
        return done[interactive]

    return run


@pytest.mark.parametrize("interactive", [False, True], ids=["headless", "interactive"])
def test_every_destruction_in_the_pool_is_announced_with_its_cause(census, interactive):
    """The census, over both manifest roles and both ways a table is driven.

    The interactive half is not a repeat: a prompt answered there is answered
    from outside the resolution that armed it, which is exactly where "the
    seat resolving right now" stops being an answer — the discard seam lost
    its cause on that road in seven places.
    """
    rows, driven = census(interactive)
    faults = _faults(rows)
    assert not faults, {name: (len(found), found[:8]) for name, found in faults.items()}

    destroyed = [row for row in rows if row["class"] in ("destroy", "destroy_sba")]
    watched = [row for row in destroyed if row["class"] == "destroy" and row["seat"] == 1]
    assert sum(driven[how] for how in ("cast", "activate", "trigger")) >= _CASE_FLOOR, driven
    assert len(destroyed) >= _DESTRUCTION_FLOOR, len(destroyed)
    assert len(watched) >= _WATCHED_FLOOR, len(watched)
    # Both seams, and both kinds of object that reach them.
    assert {row["via"] for row in destroyed} == set(_SEAM_FRAMES)
    assert driven["cast"] and driven["activate"] and driven["trigger"], driven


# --- validated backwards ----------------------------------------------------------

#: A slice of the pool for the backward runs — a targeted destroy, three sweeps
#: that reach the seam three ways, an activated one and two triggered ones.
_BACKWARD_SLICE = frozenset({
    "Disenchant", "Wrath of God", "Armageddon", "Purify", "Nevinyrral's Disk",
    "Royal Assassin", "Uktabi Orangutan", "Thicket Basilisk", "Vindicate",
})


def test_the_census_sees_a_seam_that_stopped_announcing(pool, by_name, monkeypatch):
    """The tree before the seam, reproduced: with the announcement gone the
    census must name every destruction it drives."""
    rows, _ = _sweep(pool, by_name, interactive=False, only=_BACKWARD_SLICE)
    assert not _faults(rows)
    destroyed = [row for row in rows if row["class"] == "destroy"]
    assert len(destroyed) >= 40

    monkeypatch.setattr(destruction_events, "announce_destroyed", lambda *a, **k: None)
    import engine.mixins.effects as effects_module
    import engine.mixins.helpers as helpers_module
    monkeypatch.setattr(effects_module, "announce_destroyed", lambda *a, **k: None)
    monkeypatch.setattr(helpers_module, "announce_destroyed", lambda *a, **k: None)

    silent, _ = _sweep(pool, by_name, interactive=False, only=_BACKWARD_SLICE)
    faults = _faults(silent)
    unannounced = faults.get("a destruction nothing announced", [])
    assert len(unannounced) == len([r for r in silent if r["class"] == "destroy"]) >= 40
    assert "an opponent's watcher that did not trigger exactly once" in faults


def test_the_census_sees_a_destruction_that_lost_its_cause(pool, by_name, monkeypatch):
    """…and with the cause switched off — every destruction announced as
    nobody's — it must name them all, and the watcher must go silent."""
    monkeypatch.setattr(destruction_events, "cause_seat", lambda game, cause=None: None)
    rows, _ = _sweep(pool, by_name, interactive=False, only=_BACKWARD_SLICE)
    faults = _faults(rows)
    destroyed = [row for row in rows if row["class"] == "destroy"]
    assert len(faults.get("a destruction with the wrong cause", [])) == len(destroyed) >= 40
    assert all(row["fired"] == 0 for row in destroyed)


def test_the_census_sees_a_cause_read_off_the_wrong_seat(pool, by_name, monkeypatch):
    """…and with every destruction blamed on seat 1, the watchers trigger for
    exactly the wrong half of the board."""
    monkeypatch.setattr(destruction_events, "cause_seat", lambda game, cause=None: 1)
    rows, _ = _sweep(pool, by_name, interactive=False, only=_BACKWARD_SLICE)
    faults = _faults(rows)
    assert "a destruction with the wrong cause" in faults
    assert "a watcher that triggered for its own side's or nobody's destruction" in faults
    assert "an opponent's watcher that did not trigger exactly once" in faults


# ---------------------------------------------------------------------------
# Every seam call site, given a game of its own
# ---------------------------------------------------------------------------
#
# The pool census reaches most of the engine's destroy sites and cannot reach
# all of them: a delayed destruction's mark is set by one player's ability and
# carried out by a turn step, an upkeep effect runs outside the instruction
# dispatch, and an Aura's trigger needs something to be attached to. Each of
# those is driven here by the cards that print it, and the last test in this
# section holds the two lists — sites in the source, sites a game reached —
# equal.


def _duel(by_name, *, interactive=(), seats: int = 2) -> Game:
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Forest"]] * 12)
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _put(game, by_name, seat: int, card) -> Permanent:
    perm = _fresh(by_name[card] if isinstance(card, str) else card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _settle(game) -> None:
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_replacement_choices()
    resolve_stack(game)


def _announcements(rec: _Recorder, permanent: Permanent) -> list:
    return [cause for subject_id, cause in rec.announced if subject_id == permanent.permanent_id]


def _scenario_end_of_combat(by_name) -> tuple[_Recorder, dict]:
    """Thicket Basilisk (seat 1) blocks seat 0's attacker: "destroy that
    creature at end of combat". The destruction happens in a turn step, a
    whole priority round after the trigger that set it up resolved — and the
    delayed ability is its creator's (CR 603.7e), so seat 1 destroyed it."""
    # 1/6, so the Basilisk's 2 damage does not kill it first: what destroys it
    # has to be the delayed ability, not CR 704.5g.
    attacker = _fresh(_plain("Test Attacker", "Creature - Human", power=1, toughness=6))
    basilisk = _fresh(by_name["Thicket Basilisk"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[attacker, _fresh(_watcher(0))]),
        PlayerState(name="P1", battlefield=[basilisk, _fresh(_watcher(1))]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    with _Recorder() as rec:
        for _ in range(4):
            game.advance_combat_phase()
            resolve_stack(game)
    return rec, {"game": game, "victim": attacker, "cause": 1, "watcher_seat": 0}


def _scenario_end_step_berserk(by_name) -> tuple[_Recorder, dict]:
    """Berserk, cast by seat 1 on seat 0's creature: "At the beginning of the
    next end step, destroy that creature if it attacked this turn."""
    game = _duel(by_name)
    victim = _put(game, by_name, 0, "Grizzly Bears")
    _put(game, by_name, 0, _watcher(0))
    game.players[1].hand.append(by_name["Berserk"])
    assert game.queue_from_hand(
        1, "Berserk", target_permanent_ids=[victim.permanent_id]
    ).supported
    resolve_stack(game)
    victim.metadata["attacked_this_turn"] = True
    with _Recorder() as rec:
        game.resolve_end_step(0)
        _settle(game)
    return rec, {"game": game, "victim": victim, "cause": 1, "watcher_seat": 0}


def _scenario_end_step_own_ability(by_name) -> tuple[_Recorder, dict]:
    """Rocket Launcher: "Destroy this artifact at the beginning of the next end
    step." Its controller's own ability destroys it — a cause, and not an
    opponent's."""
    game = _duel(by_name)
    launcher = _put(game, by_name, 0, "Rocket Launcher")
    _put(game, by_name, 0, _watcher(0))
    _put(game, by_name, 1, _watcher(1))
    game.active_player_index = 0
    result = game.queue_permanent_ability(0, "Rocket Launcher", target_player_index=1)
    assert result.supported, result.details
    resolve_stack(game)
    with _Recorder() as rec:
        game.resolve_end_step(0)
        _settle(game)
    return rec, {"game": game, "victim": launcher, "cause": 0, "watcher_seat": None}


def _scenario_upkeep(by_name) -> tuple[_Recorder, dict]:
    """Cosmic Horror: "At the beginning of your upkeep, destroy this creature
    unless you pay {3}{B}{B}{B}." An upkeep effect runs outside the instruction
    dispatch, so its seat is said by the caller."""
    horror = _fresh(by_name["Cosmic Horror"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[horror, _fresh(_watcher(0))]),
        PlayerState(name="P1", battlefield=[_fresh(_watcher(1))]),
    ])
    with _Recorder() as rec:
        game.resolve_upkeep(0)
        game._settle()
    return rec, {"game": game, "victim": horror, "cause": 0, "watcher_seat": None}


def _scenario_aura_leaves(by_name) -> tuple[_Recorder, dict]:
    """Parallax Dementia: "When this Aura leaves the battlefield, destroy
    enchanted creature." Seat 1's Aura on seat 0's creature."""
    game = _duel(by_name)
    host = _put(game, by_name, 0, "Grizzly Bears")
    _put(game, by_name, 0, _watcher(0))
    aura = _put(game, by_name, 1, "Parallax Dementia")
    attach_aura(aura, host)
    resolve_stack(game)
    with _Recorder() as rec:
        game.remove_from_battlefield(aura)
        game._permanent_to_graveyard(game.players[1], aura)
        _settle(game)
    return rec, {"game": game, "victim": host, "cause": 1, "watcher_seat": 0}


def _scenario_cleansing(by_name, *, interactive: bool) -> tuple[_Recorder, dict]:
    """Cleansing, cast by seat 1: "For each land, destroy that land unless any
    player pays 1 life." With human seats each verdict is reached from a
    prompt's answer, when nothing is resolving any more."""
    game = _duel(by_name, interactive=(0, 1) if interactive else ())
    land = _put(game, by_name, 0, "Island")
    _put(game, by_name, 0, _watcher(0))
    _put(game, by_name, 1, "Forest")
    game.players[1].hand.append(by_name["Cleansing"])
    game.active_player_index = 1
    with _Recorder() as rec:
        assert game.queue_from_hand(1, "Cleansing").supported
        game.resolve_top_of_stack(pause_for_choices=interactive)
        for _ in range(12):
            offer = next(
                (c for c in game.pending_choices if c.kind == "pay_life_to_save"), None
            )
            if offer is None:
                break
            assert game.resolve_pending_choice(
                "pay_life_to_save", offer.player_index, accept=False
            )
        _settle(game)
    return rec, {"game": game, "victim": land, "cause": 1, "watcher_seat": 0}


def _scenario_piles(by_name, *, interactive: bool) -> tuple[_Recorder, dict]:
    """Do or Die, cast by seat 1 on seat 0: "Separate all creatures target
    player controls into two piles. Destroy all creatures in the pile of that
    player's choice."""
    game = _duel(by_name, interactive=(0, 1) if interactive else ())
    # Two, so neither pile is empty and whichever the default seat gives up
    # holds a creature.
    creatures = [_put(game, by_name, 0, "Grizzly Bears") for _ in range(2)]
    _put(game, by_name, 0, _watcher(0))
    game.players[1].hand.append(by_name["Do or Die"])
    game.active_player_index = 1
    with _Recorder() as rec:
        assert game.queue_from_hand(1, "Do or Die", target_player_index=0).supported
        game.resolve_top_of_stack(pause_for_choices=interactive)
        for _ in range(6):
            if not game.pending_choices:
                break
            game.auto_resolve_pending_choices()
        _settle(game)
    (victim,) = [perm for perm in creatures if not game.is_on_battlefield(perm)]
    return rec, {"game": game, "victim": victim, "cause": 1, "watcher_seat": 0}


def _scenario_exchange(by_name) -> tuple[_Recorder, dict]:
    """Gauntlets of Chaos, seat 1's: "…If those permanents are exchanged this
    way, destroy all Auras attached to them." Seat 0's Aura on its own
    artifact."""
    game = _duel(by_name)
    gauntlets = _put(game, by_name, 1, "Gauntlets of Chaos")
    theirs = _put(game, by_name, 1, "Sol Ring")
    mine = _put(game, by_name, 0, "Mox Pearl")
    aura = _put(game, by_name, 0, _plain(
        "Test Wrapping", "Enchantment - Aura", "Enchant artifact", keywords=("Enchant",),
    ))
    attach_aura(aura, mine)
    _put(game, by_name, 0, _watcher(0))
    game.active_player_index = 1
    with _Recorder() as rec:
        result = game.activate_permanent_ability(
            1, "Gauntlets of Chaos", target_player_index=1,
            target_permanent_ids=[theirs.permanent_id, mine.permanent_id],
        )
        assert result.supported, result.details
        game._settle()
    del gauntlets
    return rec, {"game": game, "victim": aura, "cause": 1, "watcher_seat": 0}


def _scenario_delayed_agent(by_name) -> tuple[_Recorder, dict]:
    """Acidic Dagger, seat 0's, on seat 0's attacker: "Whenever target creature
    deals combat damage to a non-Wall creature this turn, destroy that
    non-Wall creature." Seat 1's blocker is destroyed by a delayed ability
    seat 0 controls."""
    dagger = _fresh(by_name["Acidic Dagger"])
    attacker = _fresh(_plain("Test Ogre", "Creature - Ogre", power=3, toughness=3))
    blocker = _fresh(_plain("Test Bear", "Creature - Bear", power=2, toughness=5))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[dagger, attacker, _fresh(_watcher(0))]),
        PlayerState(name="P1", battlefield=[blocker, _fresh(_watcher(1))]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [1])[0]
    game.advance_combat_phase()
    game.activate_permanent_ability(
        0, "Acidic Dagger", target_player_index=0, target_permanent_index=1
    )
    game.resolve_stack()
    assert game.declare_blockers(1, {0: 1})[0]
    with _Recorder() as rec:
        game.resolve_stack()
        for _ in range(3):
            game.advance_combat_phase()
            game.resolve_stack()
    return rec, {"game": game, "victim": blocker, "cause": 0, "watcher_seat": 1}


def _scenario_bound_permanent(by_name) -> tuple[_Recorder, dict]:
    """War Barge, seat 1's, aimed at seat 0's creature: "When this artifact
    leaves the battlefield this turn, destroy that creature." A delayed
    ability on the stack, controlled by whoever activated the Barge
    (CR 603.7e)."""
    game = _duel(by_name)
    victim = _put(game, by_name, 0, "Grizzly Bears")
    _put(game, by_name, 0, _watcher(0))
    barge = _put(game, by_name, 1, "War Barge")
    game.active_player_index = 1
    assert game.queue_permanent_ability(
        1, "War Barge", target_permanent_ids=[victim.permanent_id]
    ).supported
    resolve_stack(game)
    with _Recorder() as rec:
        game.remove_from_battlefield(barge)
        game._permanent_to_graveyard(game.players[1], barge)
        _settle(game)
    return rec, {"game": game, "victim": victim, "cause": 1, "watcher_seat": 0}


_SCENARIOS = {
    "a delayed ability's bound creature": _scenario_bound_permanent,
    "end of combat": _scenario_end_of_combat,
    "end step, an opponent's spell": _scenario_end_step_berserk,
    "end step, its own ability": _scenario_end_step_own_ability,
    "upkeep effect": _scenario_upkeep,
    "an Aura's leave trigger": _scenario_aura_leaves,
    # Answered, because that is the half that matters and the only one that
    # destroys: a default seat pays the life.
    "a resumable loop, answered": lambda by_name: _scenario_cleansing(by_name, interactive=True),
    "piles, headless": lambda by_name: _scenario_piles(by_name, interactive=False),
    "piles, answered": lambda by_name: _scenario_piles(by_name, interactive=True),
    "an exchange's Auras": _scenario_exchange,
    "a delayed ability's agent": _scenario_delayed_agent,
}


@pytest.mark.parametrize("name", sorted(_SCENARIOS))
def test_a_destruction_outside_an_effect_handler_names_who_did_it(by_name, name):
    """Each of these destroys when ``Game.resolving_seats`` is empty, or holds
    somebody else — a turn step, an upkeep effect, a prompt's answer. The
    cause is the seat CR 109.5 (or CR 603.7d–e, for a delayed ability) gives
    the spell or ability, and the opponent's watcher answers to exactly that.
    """
    rec, facts = _SCENARIOS[name](by_name)
    game, victim = facts["game"], facts["victim"]

    assert not game.is_on_battlefield(victim), game.log
    assert _announcements(rec, victim) == [facts["cause"]], (name, rec.announced, game.log)
    fired = rec.fired[victim.permanent_id]
    assert fired == (1 if facts["watcher_seat"] is not None else 0), (name, game.log)
    if facts["watcher_seat"] is not None:
        assert game.players[facts["watcher_seat"]].life == 21, game.log
    assert not game.destruction.held and not game.destruction.holds


def _seam_call_sites() -> set[tuple[str, str]]:
    """Every ``(file, function)`` in ``engine/`` that calls a destroy seam."""
    sites = set()
    for path in python_files("engine"):
        for function in _functions(source_tree(path)):
            for node in _own_nodes(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("_destroy_swept_permanents", "_destroy_target_permanent")
                ):
                    sites.add((path.name, function.name))
    return sites


def _functions(tree) -> list:
    return [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _own_nodes(function):
    """The nodes of *function*'s own body — not those of a function defined
    inside it, which is a different frame and so a different call site."""
    pending = list(ast.iter_child_nodes(function))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        pending.extend(ast.iter_child_nodes(node))


def test_every_seam_call_site_in_the_engine_was_reached_by_a_game(census, by_name):
    """The floor that is not a number: the destroy seams are called from a
    known set of functions, and each one of them destroyed something in a
    game driven here — the pool census for most, a scenario for the rest. A
    new call site that nothing drives fails this before it can be the eighth
    way round the cause."""
    reached = set()
    rows, _ = census(False)
    reached |= {row["site"] for row in rows if row["site"]}
    for name in sorted(_SCENARIOS):
        rec, _facts = _SCENARIOS[name](by_name)
        reached |= {row["site"] for row in rec.rows(name) if row["site"]}

    in_source = _seam_call_sites()
    assert len(in_source) >= 18, sorted(in_source)
    assert in_source - reached == set(), sorted(in_source - reached)


# ---------------------------------------------------------------------------
# What is not a destruction
# ---------------------------------------------------------------------------


def _watching_duel(by_name) -> Game:
    game = _duel(by_name)
    _put(game, by_name, 0, _watcher(0))
    _put(game, by_name, 1, _watcher(1))
    return game


def test_a_state_based_destruction_is_announced_with_no_cause(by_name):
    """CR 704.5g. Seat 1's Lightning Bolt deals the damage; a state-based
    action destroys. It *is* a destruction (CR 701.8b names it), so it is
    announced — and by no spell or ability, so a watcher of one is silent."""
    game = _watching_duel(by_name)
    bears = _put(game, by_name, 0, "Grizzly Bears")
    game.players[1].hand.append(by_name["Lightning Bolt"])
    with _Recorder() as rec:
        assert game.queue_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
        ).supported
        _settle(game)
        game.check_state_based_actions()
        _settle(game)

    assert not game.is_on_battlefield(bears)
    assert _announcements(rec, bears) == [None]
    assert rec.fired[bears.permanent_id] == 0
    assert [p.life for p in game.players] == [20, 20]


def test_a_state_based_destruction_inside_a_resolution_still_has_no_cause(by_name):
    """The sweep is checked while an instruction is running here — which is
    when "whatever is resolving" would have been somebody. The caller says
    nobody, so nobody it is."""
    game = _watching_duel(by_name)
    bears = _put(game, by_name, 0, "Grizzly Bears")
    bears.damage_marked = 5
    game.resolving_seats.append(1)
    try:
        with _Recorder() as rec:
            game.check_state_based_actions()
    finally:
        game.resolving_seats.pop()
    destruction_events.destruction_finished(game)

    assert not game.is_on_battlefield(bears)
    assert _announcements(rec, bears) == [None]
    assert rec.fired[bears.permanent_id] == 0


@pytest.mark.parametrize("move", ["zero toughness", "an Aura with nothing to enchant", "sacrifice"])
def test_a_move_to_the_graveyard_that_is_not_a_destruction_is_not_announced(by_name, move):
    """CR 701.8b: "If a permanent is put into its owner's graveyard for any
    other reason, it hasn't been 'destroyed.'" Two of these leave through the
    very sweep the destructions use, which is why its callers say which they
    are."""
    game = _watching_duel(by_name)
    bears = _put(game, by_name, 0, "Grizzly Bears")
    with _Recorder() as rec:
        if move == "zero toughness":
            victim = bears
            bears.toughness_bonus = -2
            game.check_state_based_actions()
        elif move == "an Aura with nothing to enchant":
            victim = _put(game, by_name, 0, _plain(
                "Test Shroud", "Enchantment - Aura", "Enchant creature", keywords=("Enchant",),
            ))
            attach_aura(victim, bears)
            game.remove_from_battlefield(bears)
            game.check_state_based_actions()
        else:
            victim = bears
            game.resolving_seats.append(1)       # an opponent's effect made them
            try:
                assert game.sacrifice_permanent(bears) is bears
            finally:
                game.resolving_seats.pop()
        _settle(game)

    assert not game.is_on_battlefield(victim), game.log
    assert victim.card.name in [c.name for c in game.players[0].graveyard]
    assert rec.announced == []
    assert [p.life for p in game.players] == [20, 20]


def test_a_delayed_sacrifice_rides_the_destroy_sweep_and_is_not_one(by_name):
    """"Sacrifice it at the beginning of the next end step" leaves through the
    end step's sweep beside the destructions; CR 701.21a."""
    game = _watching_duel(by_name)
    bears = _put(game, by_name, 0, "Grizzly Bears")
    bears.metadata["sacrifice_at_next_end_step"] = True
    with _Recorder() as rec:
        game.resolve_end_step(0)
        _settle(game)

    assert not game.is_on_battlefield(bears)
    assert rec.announced == []


@pytest.mark.parametrize("protection", ["indestructible", "regeneration"])
@pytest.mark.parametrize("road", [
    "a targeted destroy", "a sweep", "end of combat", "the end step", "Chaos Orb",
])
def test_a_replaced_destruction_is_not_a_destruction_on_any_road(by_name, road, protection):
    """CR 702.12b and CR 701.8c, asked of every road to the seam. Two of the
    five were wrong before this file existed: the end-of-combat sweep passed
    ``respect_indestructible=False``, so a Basilisk's block destroyed an
    indestructible creature, and Chaos Orb moved what it touched to the
    graveyard without asking either question."""
    game = _watching_duel(by_name)
    card = _plain(
        "Test Stalwart", "Creature - Giant", power=4, toughness=4,
        keywords=("Indestructible",) if protection == "indestructible" else (),
    )
    victim = _put(game, by_name, 0, card)
    if protection == "regeneration":
        victim.regeneration_shield = 1
    game.resolving_seats.append(1)               # an opponent's effect, each time
    try:
        with _Recorder() as rec:
            if road == "a targeted destroy":
                assert game._destroy_target_permanent(
                    game.players[0], target_permanent_index=game.battlefield_index_of(victim),
                ) is None
            elif road == "a sweep":
                assert game._destroy_swept_permanents(
                    game.players[0], lambda perm: perm is victim
                ) == []
            elif road == "end of combat":
                destruction_events.mark_delayed_destruction(
                    game, victim, "destroy_at_end_of_combat"
                )
                game._resolve_end_of_combat_destruction()
            elif road == "the end step":
                destruction_events.mark_delayed_destruction(
                    game, victim, "destroy_at_next_end_step"
                )
                game.resolve_end_step(0)
            else:
                orb = _put(game, by_name, 1, "Chaos Orb")
                import engine.handlers.destruction as destruction_handlers

                real = destruction_handlers.flip_lands_on
                destruction_handlers.flip_lands_on = lambda candidates, maximum: [
                    entry for entry in candidates if entry[1] is victim
                ]
                try:
                    game.active_player_index = 1
                    assert game.activate_permanent_ability(1, "Chaos Orb").supported
                    game._settle()
                finally:
                    destruction_handlers.flip_lands_on = real
                assert not game.is_on_battlefield(orb)
    finally:
        game.resolving_seats.pop()
    destruction_events.destruction_finished(game)
    _settle(game)

    assert game.is_on_battlefield(victim), game.log
    assert _announcements(rec, victim) == []
    assert game.players[0].life == 20


def test_chaos_orb_announces_what_it_destroys_and_its_own_destruction(by_name):
    """"…destroy all nontoken permanents it touches. Then destroy this
    artifact." Both were a bare removal: nothing watching a destruction heard
    of either."""
    game = _watching_duel(by_name)
    victim = _put(game, by_name, 0, "Sol Ring")
    orb = _put(game, by_name, 1, "Chaos Orb")
    import engine.handlers.destruction as destruction_handlers

    real = destruction_handlers.flip_lands_on
    destruction_handlers.flip_lands_on = lambda candidates, maximum: [
        entry for entry in candidates if entry[1] is victim
    ]
    try:
        game.active_player_index = 1
        with _Recorder() as rec:
            assert game.activate_permanent_ability(1, "Chaos Orb").supported
            game._settle()
    finally:
        destruction_handlers.flip_lands_on = real

    assert not game.is_on_battlefield(victim) and not game.is_on_battlefield(orb)
    assert _announcements(rec, victim) == [1]
    assert _announcements(rec, orb) == [1]
    assert [p.life for p in game.players] == [21, 20]   # seat 0's watcher, once


# ---------------------------------------------------------------------------
# The triggers wait for the resolution that destroyed (CR 603.3b)
# ---------------------------------------------------------------------------


def test_a_destroy_trigger_is_not_on_the_stack_until_the_sweep_has_finished(by_name):
    """Seat 0 is swept first and its watcher's ability targets — so put on the
    stack as its own permanent went, it would be choosing among seat 1's
    artifacts that the same Shatterstorm is about to destroy. It waits, and
    chooses off the board the whole spell left."""
    game = _duel(by_name)
    avenger = _put(game, by_name, 0, _plain(
        "Test Avenger", "Enchantment",
        "Whenever a spell or ability an opponent controls destroys an artifact "
        "you control, destroy target permanent that opponent controls.",
    ))
    _put(game, by_name, 0, "Sol Ring")
    doomed = _put(game, by_name, 1, "Mox Pearl")
    survivor = _put(game, by_name, 1, "Island")
    game.players[1].hand.append(by_name["Shatterstorm"])
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Shatterstorm").supported

    seen: list = []
    real = Game._enqueue_triggered_ability

    def spy(self, **event):
        if event.get("source_permanent") is avenger:
            seen.append(self.is_on_battlefield(doomed))
        return real(self, **event)

    Game._enqueue_triggered_ability = spy
    try:
        game.resolve_top_of_stack()
    finally:
        Game._enqueue_triggered_ability = real

    assert seen == [False], "the trigger went on the stack mid-sweep"
    (trigger,) = [item for item in game.stack if item.is_ability]
    assert trigger.target_permanent_id == survivor.permanent_id
    _settle(game)
    assert not game.is_on_battlefield(survivor)


def test_a_resolution_that_stops_to_ask_keeps_its_destroy_triggers_waiting(by_name):
    """An object held on a prompt is still resolving (CR 608.2), so what it has
    destroyed so far triggers nothing onto the stack until its last answer."""
    game = _duel(by_name, interactive=(0, 1))
    _put(game, by_name, 0, _watcher(0))
    island = _put(game, by_name, 0, "Island")
    forest = _put(game, by_name, 0, "Forest")
    game.players[1].hand.append(by_name["Cleansing"])
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Cleansing").supported
    assert game.resolve_top_of_stack(pause_for_choices=True)

    watching = lambda: [i for i in game.stack if i.is_ability]  # noqa: E731
    declined = 0
    while any(c.kind == "pay_life_to_save" for c in game.pending_choices):
        offer = next(c for c in game.pending_choices if c.kind == "pay_life_to_save")
        still_asking = game.is_on_battlefield(island) or game.is_on_battlefield(forest)
        assert not (watching() and still_asking), "a trigger went on the stack mid-effect"
        assert game.resolve_pending_choice("pay_life_to_save", offer.player_index, accept=False)
        declined += 1
    assert declined >= 4

    assert not game.is_on_battlefield(island) and not game.is_on_battlefield(forest)
    assert len(watching()) == 2
    assert game.destruction.held == [] and game.destruction.holds == 0


# ---------------------------------------------------------------------------
# The guards that keep the seam the only way
# ---------------------------------------------------------------------------


def _calls(attribute: str) -> set[tuple[str, str]]:
    found = set()
    for path in python_files("engine"):
        for function in _functions(source_tree(path)):
            for node in _own_nodes(function):
                if isinstance(node, ast.Call) and (
                    (isinstance(node.func, ast.Attribute) and node.func.attr == attribute)
                    or (isinstance(node.func, ast.Name) and node.func.id == attribute)
                ):
                    found.add((path.name, function.name))
    return found


def test_only_the_two_destroy_seams_announce_a_destruction():
    assert _calls("announce_destroyed") == {
        ("effects.py", "_do_destroy"),
        ("helpers.py", "_destroy_swept_permanents"),
    }


def test_every_other_road_to_a_graveyard_is_one_this_file_has_read():
    """A permanent reaches a graveyard through ``_permanent_to_graveyard``, and
    a caller of that which is not a destroy seam is making a move that is
    either not a destruction — and then says so here, with its rule — or is a
    destruction nothing will announce. Chaos Orb and Kudzu were the second
    kind; the discard seam found seven."""
    expected = {
        ("effects.py", "_do_destroy"),
        ("helpers.py", "_destroy_swept_permanents"),
        ("helpers.py", "_permanent_to_graveyard"),    # its own docstring names it
    }
    callers = _calls("_permanent_to_graveyard")
    by_function = {function for _path, function in callers}
    unread = {
        site for site in callers - expected
        if site[1] not in _NOT_DESTRUCTIONS_BY_CALLER
        and site[1] not in _ROUND_THE_SEAM_UNTIL_W1G8
    }
    assert not unread, (
        f"a move to a graveyard outside the destroy seams: {sorted(unread)} — "
        "destroy through `_destroy_swept_permanents`, or name it and its rule "
        "in _NOT_DESTRUCTIONS_BY_CALLER"
    )
    stale = set(_NOT_DESTRUCTIONS_BY_CALLER) - by_function
    assert not stale, f"no longer a caller, so no longer an excuse: {sorted(stale)}"


def test_a_seam_call_outside_an_effect_handler_says_who_caused_it():
    """Inside ``engine/handlers/`` the default is right: the handler runs under
    ``_execute_oracle_instruction``, which is what knows the seat. Everywhere
    else — a turn step, a state-based action, an upkeep effect, a prompt's
    answer — "whatever is resolving" is nobody or somebody else, so the call
    has to pass ``cause=``."""
    silent = []
    for path in python_files("engine"):
        if "handlers" in path.parts:
            continue
        for node in ast.walk(source_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("_destroy_swept_permanents", "_destroy_target_permanent")
                and not any(keyword.arg == "cause" for keyword in node.keywords)
            ):
                silent.append(f"{path.name}:{node.lineno}")
    assert not silent, silent


#: The marks a delayed destruction is waiting under. ``mark_delayed_destruction``
#: is their one writer, because it is what records whose delayed ability it is.
_DELAYED_MARKS = frozenset({
    "destroy_at_end_of_combat", "destroy_at_next_end_step",
    "destroy_if_did_not_attack_eot", "destroy_if_attacked_eot",
})
_DELAYED_MARK_NAMES = frozenset({"DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY"})


def test_a_delayed_destruction_mark_is_written_only_with_its_cause():
    """A mark set by ``metadata[...] = True`` is a destruction nobody caused,
    or one blamed on whoever set the mark before it."""
    direct = []
    for path in python_files("engine"):
        if path.name == "destruction_events.py":
            continue
        for node in ast.walk(source_tree(path)):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                key = target.slice
                if (
                    isinstance(key, ast.Constant) and key.value in _DELAYED_MARKS
                ) or (isinstance(key, ast.Name) and key.id in _DELAYED_MARK_NAMES):
                    direct.append(f"{path.name}:{node.lineno}")
    assert not direct, direct


def test_a_delayed_mark_records_the_seat_that_set_it(by_name):
    game = _duel(by_name)
    bears = _put(game, by_name, 0, "Grizzly Bears")
    game.resolving_seats.append(1)
    try:
        destruction_events.mark_delayed_destruction(game, bears, "destroy_at_next_end_step")
    finally:
        game.resolving_seats.pop()
    assert bears.metadata["destroy_at_next_end_step"] is True
    assert bears.metadata["destroy_at_next_end_step" + DELAYED_CAUSE_SUFFIX] == 1
    assert destruction_events.delayed_destruction_cause(bears, "destroy_at_next_end_step") == 1
    # …and one nothing was resolving for is nobody's, not a stale seat.
    destruction_events.mark_delayed_destruction(game, bears, "destroy_at_next_end_step")
    assert destruction_events.delayed_destruction_cause(
        bears, "destroy_at_next_end_step"
    ) is NO_SPELL_OR_ABILITY
