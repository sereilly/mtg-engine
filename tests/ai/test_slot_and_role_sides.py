"""Pool-wide: which board an AI seat aims each slot / role of a spell at.

A spell that names **several** object targets comes in two shapes — one
instruction with a count above one ("Put two target lands on top of their
owners' libraries") and a roles announcement spent a step at a time ("Return
target creature to its owner's hand. Then return another target creature…").
The one-target chooser has had a derived side since NEM
(``ai_valuation.instruction_target_side``); these two shapes each had less:

* the several-target chooser read a table that restated four kinds of that
  reading and lagged the rest, so **Plow Under, Panic Attack, Jagged
  Lightning, Volcanic Salvo, Sick and Tired and Deadshot** named the caster's
  own board (PLS W1G2);
* the roles chooser took the first legal chain, and the first board in seat
  order is the caster's own, so **Withdraw** returned its caster's creatures,
  **Fumarole** and **Plague Spores** destroyed its creature and land, **Lunge**
  and **Shower of Sparks** burned its creature, and **Rushing River** and
  **Falling Timber** inherited the template (PLS W1G1).

The census below is the whole class, cast by the AI onto a mirrored board. It
is validated backwards — on the tree before the fix it names thirteen
announcements, the nine cards above among them — and carries floors, so a
derivation that drifts to an empty population fails rather than passes.
"""

from __future__ import annotations

from itertools import product

import pytest

from engine import Game, PlayerState
from engine.ai_policy import _OFFERS_ANNOUNCED, _cast_candidate, _cast_candidate_announcing
from engine.ai_valuation import (_PRINTED_SEATS, _several_target_instruction,
                                 cast_offers, instruction_target_side,
                                 role_target_sides, several_target_slot_sides)
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import (derive_cast_spec, instructions_as_announced,
                              payload_own_role, role_is_seat, spec_roles)
from tests.helpers import resolve_stack

#: Spells whose cast names several object targets, both manifest roles.
_EXAMINED_FLOOR = 40
#: …of which this many announcements have a slot the one-target reading
#: classifies, which is the population the assertion is actually about.
_CLASSIFIED_FLOOR = 30

_BOARD = ("Grizzly Bears", "Hill Giant", "Serra Angel", "Wall of Wood", "Forest",
          "Mountain", "Island", "Sol Ring", "Mox Pearl", "Castle", "Crusade")
_GRAVE = ("Grizzly Bears", "Hill Giant", "Lightning Bolt", "Sol Ring", "Forest")


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


def _w2g5_put(game, pool, seat, name) -> Permanent:
    permanent = Permanent(card=pool[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w2g5_mirrored(pool, card) -> Game:
    """The same permanents on both seats and the same cards in both
    graveyards, so nothing but the policy distinguishes the two boards."""
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("AI", library=[forest] * 30, hand=[card]),
        PlayerState("Other", library=[forest] * 30, hand=[forest, forest]),
    ])
    game.enforce_mana_costs = False
    for seat in (0, 1):
        for name in _BOARD:
            _w2g5_put(game, pool, seat, name)
        game.players[seat].graveyard.extend(pool[name] for name in _GRAVE)
    game.auto_resolve_pending_choices()
    return game


def _w2g5_leaves(instructions):
    for instruction in instructions:
        payload = instruction.payload or {}
        for key in ("steps", "then", "else", "action", "otherwise"):
            nested = payload.get(key)
            if isinstance(nested, (list, tuple)):
                yield from _w2g5_leaves(nested)
        if isinstance(payload.get("targets"), dict):
            yield instruction


def _w2g5_slot_delta(instruction, position) -> str | None:
    slots = tuple((instruction.payload or {}).get("slots") or ())
    if position >= len(slots):
        return None
    delta = sum(
        value for value in (slots[position].get("power"), slots[position].get("toughness"))
        if isinstance(value, int)
    )
    return "opponent" if delta < 0 else "you" if delta > 0 else None


def _w2g5_classifier_sides(card, program, offers) -> list:
    """One entry per announced slot, by the **one-target** reading of the step
    that spends it: the slot's printed controller, the slot's own P/T numbers,
    then ``instruction_target_side``. ``"seat"`` for a player role, None where
    that reading has no answer (a positional slot of a kind whose slots differ,
    a graveyard card)."""
    spec = derive_cast_spec(card, program, optional_cost_payments=offers)
    run = instructions_as_announced(card, program, offers or {})
    steps = list(_w2g5_leaves(run))
    roles = spec_roles(spec)
    if roles:
        sides: list = []
        for position, role in enumerate(roles):
            name = role.get("role")
            if role_is_seat(role):
                sides.append("seat")
                continue
            found = set()
            for step in steps:
                targets = step.payload["targets"]
                if targets.get("kind") != "roles":
                    if name == f"slot_{position}" and targets.get("filters"):
                        described = targets["filters"][position] or {}
                        found.add(
                            _PRINTED_SEATS.get(described.get("controller"))
                            or _w2g5_slot_delta(step, position)
                        )
                    continue
                entry = next(
                    (r for r in targets.get("roles") or () if r.get("role") == name), None
                )
                own = payload_own_role(step.payload) or step.payload.get("subject_role")
                if entry is None or own not in (None, name):
                    continue
                if any(key.endswith("_role") for key in entry):
                    continue
                found.add(
                    _PRINTED_SEATS.get((entry.get("filter") or {}).get("controller"))
                    or instruction_target_side(step)
                )
            found -= {None}
            sides.append(
                "opponent" if "opponent" in found else "you" if "you" in found else None
            )
        return sides
    several = _several_target_instruction(program, run)
    if several is None:
        return []
    targets = several.payload["targets"]
    if targets.get("kind") != "object":
        return []
    count = targets.get("count")
    count = count if isinstance(count, int) else 1
    filters = targets.get("filters") or [targets.get("filter") or {}] * count
    return [
        _PRINTED_SEATS.get((filters[position] or {}).get("controller"))
        or _w2g5_slot_delta(several, position)
        or (None if several.payload.get("slots") else instruction_target_side(several))
        for position in range(count)
    ]


def _w2g5_announcements(card) -> list:
    offers = cast_offers(card)
    if not offers:
        return [None]
    keys = [offer.key for offer in offers]
    return [
        {key: 1 for key, taken in zip(keys, counts) if taken}
        for counts in product((1, 0), repeat=len(keys))
    ]


def _w2g5_named_seats(game, action) -> list:
    if action.target_permanent_ids:
        return [
            "seat" if value is None
            else game.controller_index_of(game.permanent_by_id(value))
            for value in action.target_permanent_ids
        ]
    if isinstance(action.target_permanent_index, list):
        return [action.target_player_index] * len(action.target_permanent_index)
    return []


def test_w2g5_every_slot_and_role_is_aimed_at_the_side_its_step_wants(pool):
    """The census. For every supported instant or sorcery whose cast names
    several object targets, under every answer to CR 601.2b it could give: the
    seat of each permanent the AI names, against the side the one-target
    classifier gives the step that spends that slot."""
    examined: set[str] = set()
    classified = 0
    wrong = []
    for name, card in sorted(pool.items()):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for offers in _w2g5_announcements(card):
            sides = _w2g5_classifier_sides(card, program, offers)
            if len(sides) < 2 and not (sides and offers is not None):
                continue
            examined.add(name)
            game = _w2g5_mirrored(pool, card)
            token = _OFFERS_ANNOUNCED.set(offers)
            try:
                action = _cast_candidate_announcing(game, 0, card, 0, offers=offers)
            finally:
                _OFFERS_ANNOUNCED.reset(token)
            if action is None:
                continue
            named = _w2g5_named_seats(game, action)
            judged = False
            for position, seat in enumerate(named):
                want = sides[position] if position < len(sides) else None
                if want not in ("you", "opponent") or seat == "seat":
                    continue
                judged = True
                if (seat == 0) != (want == "you"):
                    wrong.append((name, offers, position, want, named))
            classified += judged
    assert wrong == [], wrong
    assert len(examined) >= _EXAMINED_FLOOR, sorted(examined)
    assert classified >= _CLASSIFIED_FLOOR, classified
    # The cards the census was written to find, so a census that stops reaching
    # them is a failure and not a quieter pass.
    assert {
        "Plow Under", "Panic Attack", "Jagged Lightning", "Volcanic Salvo",
        "Sick and Tired", "Deadshot", "Withdraw", "Fumarole", "Plague Spores",
        "Lunge", "Shower of Sparks", "Kor Chant", "Legerdemain", "Undo",
    } <= examined


@pytest.mark.parametrize("name,sides", [
    ("Plow Under", ("opponent", "opponent")),
    ("Panic Attack", ("opponent", "opponent", "opponent")),
    ("Jagged Lightning", ("opponent", "opponent")),
    ("Volcanic Salvo", ("opponent", "opponent")),
    ("Sick and Tired", ("opponent", "opponent")),
    # Slot 0 is tapped by the sentence in front of the bite, slot 1 is bitten.
    ("Deadshot", ("opponent", "opponent")),
    # The chooser records; the steps after it sacrifice and return, or exile.
    ("Barrin's Spite", ("opponent", "opponent")),
    ("Cannibalize", ("opponent", "opponent")),
    # Gifts keep the caster's board, graveyard cards keep no board at all.
    ("Symbiosis", ("you", "you")),
    ("Hope and Glory", ("you", "you")),
    ("Death's Duet", (None, None)),
    # Per-slot numbers still outrank the kind.
    ("Rookie Mistake", ("you", "opponent")),
])
def test_w2g5_a_several_target_slot_reads_the_one_target_classifier(pool, name, sides):
    assert several_target_slot_sides(compile_card_oracle(pool[name])) == sides


@pytest.mark.parametrize("name,offers,sides", [
    ("Withdraw", None, ("opponent", "opponent")),
    ("Fumarole", None, ("opponent", "opponent")),
    ("Plague Spores", None, ("opponent", "opponent")),
    ("Lunge", None, ("opponent", None)),
    ("Rushing River", {"sacrifice a land": 1}, ("opponent", "opponent")),
    ("Falling Timber", {"sacrifice a land": 1}, ("opponent", "opponent")),
    # Positional roles are the several-target instruction's own slots.
    ("Kor Chant", None, ("you", "opponent")),
    ("Legerdemain", None, ("you", "opponent")),
    ("Hunter's Edge", None, ("you", "opponent")),
    # A role its instruction only refers to, and one a relation already pins.
    ("Glyph of Delusion", None, (None, None)),
    # An unkicked cast announces no roles at all.
    ("Rushing River", {}, ()),
])
def test_w2g5_a_role_reads_the_step_that_spends_it(pool, name, offers, sides):
    assert role_target_sides(pool[name], offers) == sides


def _w2g5_cast(game, action):
    result = game.cast_from_hand(
        0, action.card_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
        optional_cost_payments=action.optional_cost_payments,
    )
    assert result.supported, result
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    return result


def _w2g5_names(game, seat) -> list:
    return sorted(p.card.name for p in game.controlled_by(seat) if p.is_creature)


def test_w2g5_plow_under_takes_the_opponents_lands(pool):
    """The several-target half, played out: two of the *other* seat's lands go
    on top of their library and the caster keeps all of its own."""
    game = _w2g5_mirrored(pool, pool["Plow Under"])
    action = _cast_candidate(game, 0, pool["Plow Under"], 0)
    _w2g5_cast(game, action)
    lands = lambda seat: sum(p.has_type("land") for p in game.controlled_by(seat))
    assert (lands(0), lands(1)) == (3, 1)
    assert len(game.players[0].library) == 30
    assert len(game.players[1].library) == 32
    assert sorted(c.name for c in game.players[1].library[:2]) == ["Forest", "Mountain"]


def test_w2g5_fumarole_destroys_the_opponents_creature_and_land(pool):
    """The roles half: one instruction acting on every role. The caster pays
    its 3 life and loses nothing else."""
    game = _w2g5_mirrored(pool, pool["Fumarole"])
    mine = [p.permanent_id for p in game.controlled_by(0)]
    action = _cast_candidate(game, 0, pool["Fumarole"], 0)
    _w2g5_cast(game, action)
    assert [p.permanent_id for p in game.controlled_by(0)] == mine
    assert game.players[0].life == 17
    assert sorted(c.name for c in game.players[1].graveyard[len(_GRAVE):]) == [
        "Forest", "Grizzly Bears",
    ]


def test_w2g5_deadshot_taps_one_opposing_creature_to_shoot_another(pool):
    game = _w2g5_mirrored(pool, pool["Deadshot"])
    mine = [(p.permanent_id, p.tapped) for p in game.controlled_by(0)]
    action = _cast_candidate(game, 0, pool["Deadshot"], 0)
    _w2g5_cast(game, action)
    assert [(p.permanent_id, p.tapped) for p in game.controlled_by(0)] == mine
    assert any(p.tapped and p.is_creature for p in game.controlled_by(1))


def test_w2g5_an_unkicked_roles_spell_is_aimed_like_the_one_target_spell_it_is(pool):
    """Rushing River unkicked names one permanent, through the single-target
    chooser — whose side read only object descriptions, so the roles-stamped
    step had none and the caster's own Grizzly Bears went back to its hand."""
    game = _w2g5_mirrored(pool, pool["Rushing River"])
    token = _OFFERS_ANNOUNCED.set({})
    try:
        action = _cast_candidate_announcing(game, 0, pool["Rushing River"], 0, offers={})
    finally:
        _OFFERS_ANNOUNCED.reset(token)
    assert action is not None and action.target_player_index == 1
    before = _w2g5_names(game, 0)
    _w2g5_cast(game, action)
    assert _w2g5_names(game, 0) == before
    assert "Grizzly Bears" in [c.name for c in game.players[1].hand]


def test_w2g5_a_denial_with_nothing_opposing_to_name_is_not_cast(pool):
    """A side with no legal target is no announcement at all: the fallback
    took "one seat's worth" from the caster's own board, so an "up to three"
    denial with no opposing creature kept the caster's own from blocking, and
    a roles denial took the caster's creatures because they were the only
    chain."""
    forest = pool["Forest"]
    for name in ("Panic Attack", "Withdraw", "Jagged Lightning"):
        game = Game(players=[
            PlayerState("AI", library=[forest] * 30, hand=[pool[name]]),
            PlayerState("Other", library=[forest] * 30),
        ])
        game.enforce_mana_costs = False
        for creature in ("Grizzly Bears", "Hill Giant", "Serra Angel"):
            _w2g5_put(game, pool, 0, creature)
        assert _cast_candidate(game, 0, pool[name], 0) is None, name


def test_w2g5_an_exact_count_the_opponent_cannot_fill_is_not_under_announced(pool):
    """CR 601.2c: "two target lands" names two. With one opposing land the AI
    named that one, an announcement of the wrong length."""
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("AI", library=[forest] * 30, hand=[pool["Plow Under"]]),
        PlayerState("Other", library=[forest] * 30),
    ])
    game.enforce_mana_costs = False
    for _ in range(3):
        _w2g5_put(game, pool, 0, "Forest")
    _w2g5_put(game, pool, 1, "Forest")
    assert _cast_candidate(game, 0, pool["Plow Under"], 0) is None
