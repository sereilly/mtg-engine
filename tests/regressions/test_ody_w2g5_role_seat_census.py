"""Census: a roles announcement one of whose roles is a **player**.

CR 601.2c: "The player announces their choice of an appropriate object or
player for each target the spell requires." A *roles* announcement names
several targets of different kinds in one go (``targeting.ROLES_TARGET_KIND``),
and a stack object had one field meaning "the player this targets"
(``target_player_index``). So every reader of a role's seat filled every
player slot from that one field — which nobody could see, because no card
named two players: Cultural Exchange ("…creatures **target player** controls …
creatures **another target player** controls") is the first in the pool, and it
did not compile.

Two things were measured on the tree before the change, and both are pinned
here at zero:

* **The five readers of a role's seat**, asked about an announcement naming
  seats 2 and 0 in a three-seat game: the activation stamper kept one seat, the
  cast gate's reader had no per-slot argument and filled both slots from one,
  ``stack_targets`` read one seat for both roles, ``resolve_role_player``
  refused a second seat role outright, and the wire translated every seat ref
  onto one scalar (the last won). 5 of 5 could not carry two seats.
* **A player named for a role never became the target of anything**
  (CR 603.2): ``_announce_targeted_player`` asked whether the spec's kind was a
  player kind, and "roles" is not one. 30 of 30 offered announcements across
  the pool's seven roles objects with a player role — Donate, Last Stand,
  Lunge, Shower of Sparks, Soldevi Heretic, Planeswalker's Scorn and Favor —
  announced no player. Rayne's controller, Donated a permanent, drew no card.

The pool sweep is the announcement's own statement, over four tables (a plain
one, one where each seat in turn has shroud, a three-seat one with a player
gone): every assignment of seats to an object's player roles is accepted
exactly when the object's own picker offers it, an accepted one is read back
role for role by ``stack_targets.chosen_targets``, each named player becomes
the target exactly once, and the per-role seat list (``targeting.ROLE_SEATS``)
is recorded exactly where there are two or more seats to record.

``tests/engine/test_player_target_census.py`` makes the first of those
statements for every one-target and divided announcement and **skips roles**
(its ``_PLAYER_KINDS``), as ``test_player_target_resolution_census.py`` and
the cast sweep in ``test_stack_targets.py`` do; this is the population those
three leave out. The floors are what stop a later filter from making the
sweep pass by examining nothing.
"""

from __future__ import annotations

import inspect
import itertools

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext, StackItem
from engine.handlers import _common
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import announcement_targets, chosen_targets
from engine.targeting import (ROLE_SEATS, derive_activation_spec,
                              derive_cast_spec, recorded_role_seats,
                              role_is_seat, spec_roles,
                              usable_activated_abilities)
from engine.target_descriptions import roles_spec
from tests.engine.test_player_target_census import SCENARIOS, kickers, table

# Five casts and three abilities; 26 tables with a legal chain, 34 offered and
# 38 unoffered assignments (October 2026). Floors, not equalities.
_MIN_CAST_UNITS = 5
_MIN_ABILITIES = 3
_MIN_TABLES = 24
_MIN_OFFERED = 30
_MIN_UNOFFERED = 30
_MIN_TWO_SEAT_ANNOUNCEMENTS = 4


# --------------------------------------------------------------------------
# The five readers
# --------------------------------------------------------------------------

_TWO_SEATS = {
    "kind": "roles",
    "roles": [
        {"role": "player", "kind": "player"},
        {"role": "another player", "kind": "player", "distinct": True},
    ],
}
_NAMED = [2, 0]


class _Probe:
    name = "Probe"
    oracle_text = ""
    type_line = "Sorcery"
    primary_type = "sorcery"


def _three_seats() -> Game:
    return Game(players=[PlayerState(name=f"P{seat}") for seat in range(3)])


def test_the_stamper_keeps_every_seat_and_puts_the_first_on_the_scalar():
    game = _three_seats()

    ids, indices, stamps, seat, seats = game._role_announcement_stamps(
        [{"seat": 2}, {"seat": 0}]
    )

    assert (ids, indices, stamps) == ([None, None], [None, None], [None, None])
    assert seat == 2
    assert seats == _NAMED


def test_the_stamper_records_no_list_for_one_seat():
    """The list exists only where the scalar cannot say it, so every roles
    announcement the pool held before two players were named is unchanged."""
    game = _three_seats()

    *_rest, seat, seats = game._role_announcement_stamps([{"seat": 1}, {}])

    assert seat == 1
    assert seats is None


def test_the_cast_gate_fills_each_player_slot_from_its_own_seat():
    game = _three_seats()
    roles = spec_roles(roles_spec(_TWO_SEATS))

    named = game._named_role_targets(
        1, 2, None, [None, None], roles, None, role_seats=_NAMED,
    )

    assert [game.players.index(player) for player in named] == _NAMED


def test_the_cast_gate_without_the_list_reads_one_seat_for_both():
    """…which the walk's CR 115.3 distinctness then refuses: the legacy
    spelling cannot announce two players, and says so rather than guessing."""
    game = _three_seats()
    roles = spec_roles(roles_spec(_TWO_SEATS))

    named = game._named_role_targets(1, 2, None, [None, None], roles, None)

    assert [game.players.index(player) for player in named] == [2, 2]


def _two_seat_item(seats) -> StackItem:
    return StackItem(
        card=_Probe(), caster_index=1, target_player_index=2,
        target_permanent_index=None, x_value=None,
        target_permanent_id=[None, None], choices={ROLE_SEATS: list(seats)},
    )


def test_the_stack_reader_reads_each_role_s_own_seat():
    game = _three_seats()
    item = _two_seat_item(_NAMED)
    spec = roles_spec(_TWO_SEATS)

    read = announcement_targets(game, item, spec, item)

    assert [(target.position, target.seat) for target in read] == [(0, 2), (1, 0)]


def test_a_blanked_seat_slot_reads_as_nobody_not_as_the_scalar():
    """CR 608.2b's blank: ``None`` in the list names nobody, and the scalar
    beside it — which still holds seat 2 — must not answer for the slot."""
    game = _three_seats()
    item = _two_seat_item([None, 0])
    spec = roles_spec(_TWO_SEATS)

    read = announcement_targets(game, item, spec, item)

    assert [(target.position, target.seat) for target in read] == [(1, 0)]


def test_the_resolution_reads_each_role_s_own_seat():
    game = _three_seats()
    context = OracleExecutionContext(
        caster=game.players[1], target=game.players[2], card=_Probe(),
        target_permanent_id=[None, None], choices={ROLE_SEATS: list(_NAMED)},
    )
    payload = {"targets": _TWO_SEATS}

    resolved = [
        _common.resolve_role_player(game, context, payload, role["role"])
        for role in _TWO_SEATS["roles"]
    ]

    assert resolved == _NAMED


def test_the_resolution_still_refuses_two_seat_roles_announced_on_one_scalar():
    """The refusal ``resolve_role_player`` has always made, kept for the one
    case it was written for: two player roles and no per-role record."""
    game = _three_seats()
    context = OracleExecutionContext(
        caster=game.players[1], target=game.players[2], card=_Probe(),
        target_permanent_id=[None, None],
    )
    payload = {"targets": _TWO_SEATS}

    assert [
        _common.resolve_role_player(game, context, payload, role["role"])
        for role in _TWO_SEATS["roles"]
    ] == [None, None]


def test_the_wire_forwards_the_role_refs_rather_than_one_seat():
    """Read as text: the boundary used to translate every seat ref onto
    ``target_seat``, so the second overwrote the first."""
    from web import action_helpers

    source = inspect.getsource(action_helpers._queue_spell_from_request)

    assert "target_role_refs=role_refs" in source
    assert "target = ref.seat" not in source


# --------------------------------------------------------------------------
# The pool
# --------------------------------------------------------------------------


def _chains(options, depth, prefix=()) -> list:
    """Every complete chain of the picker's walk, one option per role."""
    found = []
    for option in options or ():
        chain = prefix + (option,)
        if len(chain) == depth:
            found.append(chain)
        else:
            found.extend(_chains(option.get("next"), depth, chain))
    return found


def _ref(game, option) -> dict:
    kind = option.get("kind")
    if kind == "player":
        return {"seat": option["seat"]}
    if kind == "permanent":
        permanent = game.permanent_at(option["seat"], option["index"])
        return {"permanent_id": permanent.permanent_id}
    assert kind == "graveyard", option
    return {"graveyard_seat": option["seat"], "graveyard_index": option["index"]}


class _Sweep:
    def __init__(self) -> None:
        self.tables = self.offered = self.unoffered = self.two_seat = 0
        self.wrong: list[str] = []

    def run(self, label, build, picker, announce, spied) -> bool:
        """One object over the four tables; whether any table had a chain."""
        reached = False
        for scenario in SCENARIOS:
            probe, handle = build(scenario)
            if probe is None:
                continue
            roles = spec_roles(picker(probe, handle))
            seat_slots = [slot for slot, role in enumerate(roles) if role_is_seat(role)]
            if not seat_slots:
                continue
            seats_only = len(seat_slots) == len(roles)
            if not _chains(picker(probe, handle).get("valid_targets"), len(roles)):
                if not seats_only:
                    # No chain to borrow the other roles' objects from.
                    continue
            else:
                reached = True
                self.tables += 1
            for assignment in itertools.product(
                range(len(probe.players)), repeat=len(seat_slots)
            ):
                game, handle = build(scenario)
                legal = _chains(picker(game, handle).get("valid_targets"), len(roles))
                matching = [
                    chain for chain in legal
                    if all(chain[slot].get("kind") == "player" for slot in seat_slots)
                    and tuple(chain[slot]["seat"] for slot in seat_slots) == assignment
                ]
                base = (matching or legal or [()])[0]
                refs = [_ref(game, option) for option in base] or [None] * len(roles)
                for slot, seat in zip(seat_slots, assignment):
                    refs[slot] = {"seat": seat}
                del spied[:]
                before = len(game.stack)
                result = announce(game, handle, refs)
                where = f"{label} [{scenario}] seats {assignment}"
                if not matching:
                    self.unoffered += 1
                    if result.supported:
                        self.wrong.append(f"accepted an unoffered seat: {where}")
                    continue
                self.offered += 1
                if not result.supported or len(game.stack) <= before:
                    self.wrong.append(f"refused an offered chain: {where}: {result.details}")
                    continue
                item = game.stack[before]
                read = [
                    (
                        target.position, target.kind,
                        target.seat if target.kind == "player" else target.permanent_id,
                    )
                    for target in (chosen_targets(game, item) or ())
                    if target.kind in ("player", "permanent")
                ]
                named = [
                    (position, "player", ref["seat"]) if "seat" in ref
                    else (position, "permanent", ref["permanent_id"])
                    for position, ref in enumerate(refs)
                    if "seat" in ref or "permanent_id" in ref
                ]
                if read != named:
                    self.wrong.append(f"read back {read}, named {named}: {where}")
                if sorted(spied) != sorted(assignment):
                    self.wrong.append(
                        f"players {sorted(assignment)} became the target "
                        f"{sorted(spied)}: {where}"
                    )
                recorded = recorded_role_seats(item)
                if len(seat_slots) > 1:
                    self.two_seat += 1
                    expected = [None] * len(roles)
                    for slot, seat in zip(seat_slots, assignment):
                        expected[slot] = seat
                    if recorded != expected:
                        self.wrong.append(f"recorded {recorded}, named {expected}: {where}")
                elif recorded is not None:
                    self.wrong.append(f"one seat role recorded a list {recorded}: {where}")
        return reached


@pytest.fixture
def targeted_seats(monkeypatch):
    """Every seat ``self_becomes_target`` is announced for, as it happens.

    ``Game._announce_targeted_player`` imports ``emit`` when it runs, so the
    module attribute is the seam; everything else it is handed goes through
    untouched.
    """
    import engine.events as events

    seen: list[int] = []
    real = events.emit

    def spy(game, kind, *args, **payload):
        if kind == "self_becomes_target" and payload.get("targeted_seat") is not None:
            seen.append(payload["targeted_seat"])
        return real(game, kind, *args, **payload)

    monkeypatch.setattr(events, "emit", spy)
    return seen


def test_every_roles_announcement_with_a_player_is_held_to_its_picker_and_read_back(
    targeted_seats,
):
    sweep = _Sweep()
    cast_units = abilities = 0

    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if card.primary_type in ("instant", "sorcery"):
            # A modal spell's roles are per mode and none names a player.
            if program.modes or not any(
                role_is_seat(role)
                for role in spec_roles(derive_cast_spec(card, program))
            ):
                continue
            cast_units += 1
            sweep.run(
                f"cast:{card.name}",
                lambda scenario, card=card: (table(scenario, card), card),
                lambda game, card: game.cast_target_spec(
                    0, card, optional_cost_payments=kickers(game, card),
                ),
                lambda game, card, refs: game.queue_from_hand(
                    0, card.name, target_role_refs=refs,
                ),
                targeted_seats,
            )
            continue
        for ability_index, ability in enumerate(usable_activated_abilities(program)):
            if not any(
                role_is_seat(role)
                for role in spec_roles(derive_activation_spec(ability))
            ):
                continue

            def build(scenario, card=card):
                game = table(scenario)
                source = Permanent(card=card)
                game._put_permanent_onto_battlefield(0, source, None)
                source.metadata["summoning_sickness_turn"] = -99
                return game, source

            reached = sweep.run(
                f"act:{card.name}#{ability_index}",
                build,
                lambda game, source, index=ability_index: game.activation_target_spec(
                    0, game.battlefield_index_of(source), index,
                ),
                lambda game, source, refs, index=ability_index: game.queue_permanent_ability(
                    0, source.card.name,
                    permanent_index=game.battlefield_index_of(source),
                    ability_index=index, target_role_refs=refs, x_value=1,
                ),
                targeted_seats,
            )
            abilities += reached

    assert cast_units >= _MIN_CAST_UNITS, cast_units
    assert abilities >= _MIN_ABILITIES, abilities
    assert sweep.tables >= _MIN_TABLES, sweep.tables
    assert sweep.offered >= _MIN_OFFERED, sweep.offered
    assert sweep.unoffered >= _MIN_UNOFFERED, sweep.unoffered
    assert sweep.two_seat >= _MIN_TWO_SEAT_ANNOUNCEMENTS, sweep.two_seat
    assert not sweep.wrong, (len(sweep.wrong), sweep.wrong[:20])
