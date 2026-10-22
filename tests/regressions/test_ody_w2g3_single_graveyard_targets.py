"""Regression: several target cards in a graveyard were chosen at resolution.

Reported by Odyssey's wave 1 (W1G6, driven) and standing in the engine since
Mirage as a stated deviation: "Exile up to three target cards from a single
graveyard" (Ebony Charm's second mode, Rapid Decay, Decompose; Carrion
Beetles' and Famished Ghoul's activations) put its object on the stack naming
nothing and asked its controller *as it resolved* — which pile, then which
cards.

That is wrong and not a convention. The cards are targets (CR 115.1 — the
sentence says the word), chosen as the object is put on the stack (CR 601.2c,
and CR 602.2b for an ability), so an opponent responds knowing which cards
are named; CR 608.2b then judges each one, and a card that has left is not
made up for. Picked at resolution, the caster chose *after* the response —
exile the best card in response and Rapid Decay simply took the next three.
"Cards in graveyards can't be the targets of spells or abilities" (Ground
Seal) had nothing to refuse, either.

The fix is small because the machinery was all there, under another pile:
"exile X target creature cards from **your** graveyard" (Midnight Ritual) has
announced slots since Mercadian Masques. A graveyard announcement is one seat
and a list of slots in that seat's pile, so "a single graveyard" — a relation
across the targets — is held by the announcement's own shape once the seat is
named, and the gate requires that it is.

Four things here:

* the **text census**, both manifest roles: every printed spell line, mode and
  activated ability that names several target cards in a graveyard derives a
  graveyard picker. On the tree before the fix it names the five lines above
  and nothing else (``test_the_census_sees_the_old_derivation`` runs it that
  way round, so a census that had stopped seeing would fail);
* the **driven census** over those lines: announced, read back off
  ``stack_targets.chosen_targets``, a card exiled in response not replaced,
  and nothing asked at resolution;
* the gates, both ends, and the sweep the other way — the announcement gate
  turned off, and nothing the list did not offer is acted on;
* and the same words under a *triggered* ability, which were left chosen at
  resolution until Torment's second wave (W2G2, Gravegouger) and are
  announced as the ability is put on the stack now (CR 603.3d) — with the
  resolution prompts kept under a test of their own, over a payload that
  carries no target description, since no compiled card arms them any more.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle, expand_ability_lines
from engine.stack_targets import chosen_targets
from engine.targeting import (GRAVEYARD_TARGET_KIND,
                              derive_activation_spec, derive_cast_spec)
from engine.target_descriptions import SINGLE_GRAVEYARD
from tests.helpers import _mk_card, _mk_creature_card, resolve_stack

#: "…target [adjectives] cards from/in … graveyard", and the singular only
#: where the pile is "a single graveyard". The words between "target" and the
#: noun are the card's own narrowing ("basic land", "creature"), never another
#: object ("target player discards X cards … graveyards").
_SEVERAL_GRAVEYARD_TARGETS = re.compile(
    r"\btarget (?:(?!player|opponent|creatures\b)[a-z-]+ ){0,4}"
    r"(?:cards (?:from|in) [^.]*\bgraveyard|cards? from a single graveyard)",
    re.IGNORECASE,
)
_REMINDER = re.compile(r"\([^)]*\)")

#: The lines the census names on the tree before the fix — the wave-1
#: report's own five, as ``(card, where)``.
_PICKED_AT_RESOLUTION_BEFORE = {
    ("Carrion Beetles", "activated 0"),
    ("Decompose", "cast"),
    ("Ebony Charm", "mode 1"),
    ("Famished Ghoul", "activated 0"),
    ("Rapid Decay", "cast"),
}

#: A sweep that examined nothing looks exactly like one that found nothing.
_LINES_FLOOR = 7_500
_COUNTED_LINES_FLOOR = 20


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            cards.setdefault(card.name, card)
    return cards


def _counted_lines(pool):
    """``(card, where, text, spec)`` for every spell line, mode and activated
    ability that prints several target cards in a graveyard, and how many
    printed lines were read to find them."""
    rows, examined = [], 0
    for unit in compilation_units(list(pool.values())):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        text = expand_ability_lines(
            unit.oracle_text or "", card_name=unit.name,
            legendary=bool(getattr(unit, "is_legendary", False)),
        )
        lines = [_REMINDER.sub("", line).strip() for line in text.splitlines()]
        examined += len(lines)
        modes = list(program.modes or ())
        for index, mode in enumerate(modes):
            if _SEVERAL_GRAVEYARD_TARGETS.search(mode.label or ""):
                rows.append((
                    unit, f"mode {index}", mode.label,
                    derive_cast_spec(unit, program, mode_index=index),
                ))
        for index, ability in enumerate(program.activated_abilities):
            effect = (ability.source_line or "").split(":", 1)[-1]
            if _SEVERAL_GRAVEYARD_TARGETS.search(effect):
                rows.append((
                    unit, f"activated {index}", ability.source_line,
                    derive_activation_spec(ability),
                ))
        if unit.primary_type in ("instant", "sorcery") and not modes:
            for line in lines:
                if _SEVERAL_GRAVEYARD_TARGETS.search(line):
                    rows.append((unit, "cast", line, derive_cast_spec(unit, program)))
    return rows, examined


def _unannounced(rows) -> set:
    return {
        (unit.name, where) for unit, where, _text, spec in rows
        if spec is None or spec.get("kind") != GRAVEYARD_TARGET_KIND
    }


# ---------------------------------------------------------------------------
# The text census
# ---------------------------------------------------------------------------

def test_every_line_naming_several_graveyard_targets_announces_them(pool):
    rows, examined = _counted_lines(pool)

    assert examined >= _LINES_FLOOR, examined
    assert len(rows) >= _COUNTED_LINES_FLOOR, len(rows)
    # The known five are in the population, so "none unannounced" is a
    # statement about them and not about a regex that missed them.
    assert _PICKED_AT_RESOLUTION_BEFORE <= {(unit.name, where) for unit, where, *_ in rows}
    assert _unannounced(rows) == set()
    # "A single graveyard" is carried as the relation it is, on exactly the
    # lines that print it.
    printed = {
        (unit.name, where) for unit, where, text, _spec in rows
        if "a single graveyard" in text.lower()
    }
    flagged = {
        (unit.name, where) for unit, where, _text, spec in rows
        if spec.get(SINGLE_GRAVEYARD)
    }
    assert printed == flagged == _PICKED_AT_RESOLUTION_BEFORE


def test_the_census_sees_the_old_derivation(pool, monkeypatch):
    """Validated backwards: with the picker row answering as it did before
    the fix, the census names the five lines the wave-1 report named."""
    from engine import payload_target_specs

    announced = payload_target_specs._graveyard_exile_pile_spec

    def as_before(payload):
        if payload.get("graveyard_owner") != "you":
            return None
        return announced(payload)

    monkeypatch.setitem(
        payload_target_specs._KIND_TO_SPEC_FROM_PAYLOAD,
        "exile_cards_from_graveyard", as_before,
    )

    rows, _examined = _counted_lines(pool)

    assert _unannounced(rows) == _PICKED_AT_RESOLUTION_BEFORE


# ---------------------------------------------------------------------------
# The driven census: the five lines, in a game
# ---------------------------------------------------------------------------

_MINE = ("Grizzly Bears", "Forest", "Giant Growth")
_THEIRS = ("Swamp", "Hill Giant", "Terror", "Island", "Craw Wurm")


def _duel(pool, *, hand=(), battlefield=(), mine=_MINE, theirs=_THEIRS, cards=()):
    game = Game(players=[
        PlayerState(
            "Caster", library=[pool["Forest"]] * 6,
            hand=[pool[name] for name in hand] + list(cards),
        ),
        PlayerState("Victim", library=[pool["Forest"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.players[0].graveyard.extend(pool[name] for name in mine)
    game.players[1].graveyard.extend(pool[name] for name in theirs)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for name in battlefield:
        permanent = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.tapped = False
        permanent.metadata["summoning_sickness_turn"] = -99
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    # A person in each seat: what is asked of them, and when, is the subject.
    game.interactive_seats = {0, 1}
    return game


def _announce(game, pool, name, where, slots, seat=1):
    """Put the line on the stack naming *slots* of *seat*'s graveyard."""
    named = {"target_player_index": seat, "target_permanent_index": list(slots)}
    if seat is None:
        del named["target_player_index"]
    kind, _, index = where.partition(" ")
    if kind == "activated":
        return game.queue_permanent_ability(
            0, name, ability_index=int(index), **named
        )
    if kind == "mode":
        named["mode_index"] = int(index)
    return game.queue_from_hand(0, name, **named)


def _on_the_table(pool, name, where):
    if where.startswith("activated"):
        return _duel(pool, battlefield=[name])
    return _duel(pool, hand=[name])


def _spec(game, pool, name, where):
    kind, _, index = where.partition(" ")
    if kind == "activated":
        return game.activation_target_spec(0, 0, ability_index=int(index))
    if kind == "mode":
        return game.cast_target_spec(0, pool[name], mode_index=int(index))
    return game.cast_target_spec(0, pool[name])


def _names(cards) -> list:
    return [card.name for card in cards]


_FIVE = sorted(_PICKED_AT_RESOLUTION_BEFORE)


@pytest.mark.parametrize(("name", "where"), _FIVE)
def test_the_cards_are_announced_and_read_back_off_the_stack(pool, name, where):
    game = _on_the_table(pool, name, where)
    spec = _spec(game, pool, name, where)
    ceiling = spec["max_targets"]

    # Every pile is offered: the choice of graveyard is part of the choice.
    assert {target["seat"] for target in spec["valid_targets"]} == {0, 1}
    slots = [1, 2, 4][:ceiling]
    assert _announce(game, pool, name, where, slots).supported

    item = game.stack[-1]
    read_back = chosen_targets(game, item)
    assert [(target.kind, target.stamp.seat) for target in read_back] == [
        ("graveyard", 1)
    ] * len(slots)
    assert _names(target.stamp.card for target in read_back) == [
        _THEIRS[slot] for slot in slots
    ]


@pytest.mark.parametrize(("name", "where"), _FIVE)
def test_a_card_exiled_in_response_is_not_replaced(pool, name, where):
    """CR 608.2b's last sentence, and the whole reason the timing matters."""
    game = _on_the_table(pool, name, where)
    ceiling = _spec(game, pool, name, where)["max_targets"]
    slots = [1, 2, 4][:ceiling]
    assert _announce(game, pool, name, where, slots).supported
    victim = game.players[1]

    victim.exile.append(victim.graveyard.pop(1))          # Hill Giant, in response
    resolve_stack(game)

    # Nothing was asked, and nothing was taken in the Giant's place.
    assert game.pending_choices == []
    survivors = [_THEIRS[slot] for slot in slots if slot != 1]
    assert sorted(_names(victim.exile)) == sorted(["Hill Giant", *survivors])
    assert _names(victim.graveyard) == [
        card for index, card in enumerate(_THEIRS) if index not in slots
    ]
    # The other pile was never read.
    assert set(_MINE) <= set(_names(game.players[0].graveyard))


@pytest.mark.parametrize(("name", "where"), _FIVE)
def test_a_split_or_an_overlong_announcement_is_refused_with_nothing_paid(pool, name, where):
    game = _on_the_table(pool, name, where)
    ceiling = _spec(game, pool, name, where)["max_targets"]
    before = (_names(game.players[0].graveyard), len(list(game.all_permanents())))

    # Slots with no graveyard named: slot 0 could be either player's card.
    unnamed = _announce(game, pool, name, where, [0, 1], seat=None)
    assert not unnamed.supported and "name the graveyard" in unnamed.details
    # A slot only the *other* pile has: the caster's holds three cards.
    assert not _announce(game, pool, name, where, [0, 4], seat=0).supported
    # More than the printed ceiling.
    assert not _announce(
        game, pool, name, where, list(range(ceiling + 1)), seat=1
    ).supported
    # One card twice (CR 115.3).
    assert not _announce(game, pool, name, where, [2, 2], seat=1).supported

    assert game.stack == []
    assert before == (
        _names(game.players[0].graveyard), len(list(game.all_permanents()))
    ), "a refused announcement paid a cost"


@pytest.mark.parametrize(("name", "where"), _FIVE)
def test_naming_none_is_legal_and_exiles_nothing(pool, name, where):
    """"Up to" may name none (CR 601.2c). It resolves, does nothing, and is
    not handed a pick it did not announce."""
    game = _on_the_table(pool, name, where)

    assert _announce(game, pool, name, where, [], seat=None).supported
    assert not chosen_targets(game, game.stack[-1])
    resolve_stack(game)

    assert game.pending_choices == []
    assert _names(game.players[1].graveyard) == list(_THEIRS)
    assert game.players[0].exile == [] and game.players[1].exile == []


@pytest.mark.parametrize(("name", "where"), _FIVE)
def test_every_named_card_leaving_removes_the_object(pool, name, where):
    game = _on_the_table(pool, name, where)
    assert _announce(game, pool, name, where, [1, 2]).supported
    victim = game.players[1]

    victim.exile.append(victim.graveyard.pop(2))
    victim.exile.append(victim.graveyard.pop(1))
    resolve_stack(game)

    # One rule, two spellings: a spell's line and an activated ability's.
    assert any(
        "removed from the stack" in line and "(608.2b)" in line for line in game.log
    ), game.log[-3:]
    assert _names(victim.graveyard) == ["Swamp", "Island", "Craw Wurm"]
    assert sorted(_names(victim.exile)) == ["Hill Giant", "Terror"]


# ---------------------------------------------------------------------------
# Ground Seal, which now has something to refuse
# ---------------------------------------------------------------------------

def test_ground_seal_leaves_a_single_graveyard_spell_nothing_to_name(pool):
    game = _duel(pool, hand=["Decompose"], battlefield=["Ground Seal"])

    assert game.cast_target_spec(0, pool["Decompose"])["valid_targets"] == []
    assert not _announce(game, pool, "Decompose", "cast", [0]).supported
    # "Up to three" naming none is still a cast (CR 601.2c).
    assert _announce(game, pool, "Decompose", "cast", [], seat=None).supported


def test_ground_seal_arriving_in_response_spares_every_named_card(pool):
    game = _duel(pool, hand=["Decompose"])
    assert _announce(game, pool, "Decompose", "cast", [0, 1]).supported

    seal = Permanent(card=pool["Ground Seal"])
    game._put_permanent_onto_battlefield(1, seal, None)
    resolve_stack(game)

    assert _names(game.players[1].graveyard) == list(_THEIRS)
    assert game.players[1].exile == []


# ---------------------------------------------------------------------------
# Cast out of the pile it names (Recoup grants Decompose flashback)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("own_slot", [0, 2])
def test_a_flashed_back_spell_holds_its_slots_through_leaving_the_pile(pool, own_slot):
    """The spell is in the graveyard as its targets are counted and on the
    stack by the time they are read (CR 601.2a before CR 601.2c —
    ``targeting.CAST_FROM_GRAVEYARD``, W1G3). Several slots, named around the
    card being cast, have to come back as the cards that were named."""
    game = _duel(pool, hand=["Recoup"], mine=())
    caster = game.players[0]
    yard = ["Grizzly Bears", "Forest", "Giant Growth"]
    yard.insert(own_slot, "Decompose")
    caster.graveyard[:] = [pool[name] for name in yard]
    game.interactive_seats = set()
    assert game.cast_from_hand(
        0, "Recoup", target_player_index=0, target_permanent_index=own_slot,
    ).supported
    resolve_stack(game)

    spec = game.cast_target_spec(0, pool["Decompose"], from_zone="graveyard")
    mine = [target for target in spec["valid_targets"] if target["seat"] == 0]
    # The card being cast is not one of its own targets.
    assert "Decompose" not in [target["name"] for target in mine]
    named = [target for target in mine if target["name"] in ("Grizzly Bears", "Forest")]
    assert game.queue_from_hand(
        0, "Decompose", from_zone="graveyard", target_player_index=0,
        target_permanent_index=[target["index"] for target in named],
    ).supported
    assert _names(
        target.stamp.card for target in chosen_targets(game, game.stack[-1])
    ) == ["Grizzly Bears", "Forest"]
    resolve_stack(game)

    assert _names(caster.graveyard) == ["Giant Growth", "Recoup"]
    assert sorted(_names(caster.exile)) == ["Decompose", "Forest", "Grizzly Bears"]


# ---------------------------------------------------------------------------
# The sweep the other way: the gate off, and nothing unoffered is acted on
# ---------------------------------------------------------------------------

def test_with_the_announcement_gate_off_only_offered_cards_are_exiled(pool, monkeypatch):
    """The handler now trusts announced slots, so it is asked what it does
    with ones no list offered. "Exile up to two target **creature** cards
    from a single graveyard" is invented — the pool's five print no type —
    and named here at a land, at a slot past the pile, and at a real target."""
    picky = _mk_card(
        "Picky Scavenger", "{B}", "Instant",
        "Exile up to two target creature cards from a single graveyard.",
    )
    assert compile_card_oracle(picky).supported
    game = _duel(pool, cards=[picky])
    offered = {
        (target["seat"], target["index"])
        for target in game.cast_target_spec(0, picky)["valid_targets"]
    }
    assert offered == {(0, 0), (1, 1), (1, 4)}

    monkeypatch.setattr(Game, "cast_target_refusal", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        Game, "_validate_cast_targets", lambda *args, **kwargs: (True, "")
    )
    assert game.queue_from_hand(
        0, "Picky Scavenger", target_player_index=1, target_permanent_index=[0, 1],
    ).supported
    resolve_stack(game)

    # The Swamp at slot 0 was never offered and is still there.
    assert _names(game.players[1].exile) == ["Hill Giant"]
    assert "Swamp" in _names(game.players[1].graveyard)


# ---------------------------------------------------------------------------
# The AI names its slots
# ---------------------------------------------------------------------------

def test_an_ai_seat_names_an_opponents_cards_for_the_activation(pool):
    """An activation that names none is the legal "up to" announcement and
    exiles nothing, so a seat that names nothing pays {2}{B} and a tap for no
    effect. The chooser names the maximum out of one opponent's pile, and
    proposes nothing when no opponent has a card to take."""
    from engine.ai_abilities import choose_activation_action

    game = _duel(pool, battlefield=["Carrion Beetles"])
    game.interactive_seats = set()

    action = choose_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Carrion Beetles"
    assert (action.target_player_index, action.target_permanent_index) == (1, [0, 1, 2])
    assert game.activate_permanent_ability(
        0, action.permanent_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
    ).supported
    resolve_stack(game)
    assert _names(game.players[1].exile) == ["Swamp", "Hill Giant", "Terror"]
    assert game.players[0].exile == []

    # Only its own pile holds a card: nothing worth the mana.
    alone = _duel(pool, battlefield=["Carrion Beetles"], theirs=())
    alone.interactive_seats = set()
    assert choose_activation_action(alone, 0) is None


# ---------------------------------------------------------------------------
# What is left: the same words under a trigger
# ---------------------------------------------------------------------------

def test_a_triggered_ability_announces_its_single_graveyard_too(pool):
    """CR 603.3d: a triggered ability chooses its targets as it is put on the
    stack, and "up to two target cards from a single graveyard" are targets
    under a trigger as under a spell. Pinned the other way round until
    Torment's second wave — "pinned so the day a trigger can announce them,
    this fails and says so" — and that day was Gravegouger's (W2G2)."""
    watcher = _mk_creature_card(
        "Graveside Watcher", 2, 2,
        "When this creature enters, exile up to two target cards from a "
        "single graveyard.",
    )
    program = compile_card_oracle(watcher)
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    assert trigger.instruction.payload["targets"]["count"] == 2

    game = _duel(pool, cards=[watcher])
    assert game.queue_from_hand(0, "Graveside Watcher").supported
    game.resolve_top_of_stack(pause_for_choices=True)       # the creature

    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert asked.data["single_graveyard"] and asked.data["max_targets"] == 2
    assert game.confirm_trigger_target(0, seat=1, graveyard_indices=[1, 2])
    resolve_stack(game)

    assert sorted(_names(game.players[1].exile)) == ["Hill Giant", "Terror"]
    assert game.pending_choices == [] and game.stack == []


def test_a_pile_with_no_target_description_is_still_chosen_at_resolution(pool):
    """The handler's resolution-time branch — which pile, then which cards —
    for a "single graveyard" payload that carries no ``targets``
    description. No compiled card reaches it since triggers announce theirs,
    so it is driven over a hand-built instruction to keep the two prompts
    (``graveyard_pile_choice``, ``graveyard_exile_pick``) under a test."""
    from engine.game_types import OracleExecutionContext
    from engine.oracle_types import OracleInstruction

    game = _duel(pool)
    source = Permanent(card=pool["Craw Wurm"])
    game._put_permanent_onto_battlefield(0, source, None)
    instruction = OracleInstruction("exile_cards_from_graveyard", "", {
        "count": 2, "graveyard_owner": "chosen", "up_to": True, "any_card": True,
    })
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=source.card,
        source_permanent=source,
    )
    game._execute_oracle_instruction(instruction, context)

    assert [choice.kind for choice in game.pending_choices] == ["graveyard_pile_choice"]
    assert game.confirm_graveyard_pile_choice(0, 1)
    assert [choice.kind for choice in game.pending_choices] == ["graveyard_exile_pick"]
    assert game.confirm_graveyard_exile_pick(0, [1, 2])

    assert sorted(_names(game.players[1].exile)) == ["Hill Giant", "Terror"]
    assert game.pending_choices == []
