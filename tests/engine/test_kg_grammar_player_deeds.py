"""Round kg/grammar: "who <did X>" has one spelling, and a narrowing on a
chosen seat is either enforced by the picker or refused.

"…to target player **who attacked this turn**" (Fire and Brimstone), "…to
target opponent **previously dealt damage by it**" (Diseased Vermin), "…each
player **who tapped a land for mana this turn** sacrifices a land … each player
**who sacrificed a Plains this way**" (Desolation). Four printed clauses, one
question — which seats the sentence is about, narrowed by what they did — and
until this round two spellings of it: the first two were flags on
``ast.PlayerRef`` read by one branch each of ``_targets_payload``, the second two
an ``ast.PlayerDeed`` read through ``lowering/_common``'s table. A flag set on a
kind its branch did not read was dropped: "target **opponent** who attacked
this turn" and "target **player** previously dealt damage by it" compiled
supported with the narrowing gone, and the picker offered every seat.

Now every clause is a ``PlayerDeed`` on ``PlayerRef.did`` and one table
(``handlers/_filters.PLAYER_DEEDS``) says, per kind, what the clause names and
whether the seat can answer it **while a target is chosen** (CR 601.2c) or only
inside the resolution that wrote the record. The picker, the CR 608.2b re-check
that reuses its list, and the seat loops of the two handlers all ask
``seat_did``; a resolution-only deed on a chosen seat refuses.

The census reads the whole pool in both manifest roles, and asserts a floor on
what it found. Validated backwards on the base commit (``c42aec75``): the
flag census names Fire and Brimstone and Diseased Vermin, and every invented
card below either compiled with its narrowing dropped or failed to parse.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.damage_events import deal_damage
from engine.grammar import compile_line
from engine.handlers._filters import PLAYER_DEEDS, seat_did
from engine.models import Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle, compiled_units
from engine.oracle_types import OracleInstruction
from engine.targeting import derive_activation_spec, derive_cast_spec
from tests.helpers import _mk_card, resolve_stack

#: The two flags the clauses used to be spelled as, on a player target.
_RETIRED_FLAGS = ("attacked_this_turn", "damaged_by_source")
_PLAYER_TARGET_KINDS = ("player", "player_or_planeswalker")

#: Printed phrase -> the deed kind it must compile to. The text half of the
#: census: a phrase found here and not in the program is a dropped narrowing.
_PRINTED = (
    (re.compile(r"\b(?:players?|opponents?) who attacked this turn\b", re.I),
     "attacked_this_turn"),
    (re.compile(r"\b(?:players?|opponents?) previously dealt damage by it\b", re.I),
     "dealt_damage_by_source"),
    (re.compile(
        r"\b(?:players?|opponents?) who tapped a land for mana this turn\b", re.I
    ), "tapped_land_for_mana_this_turn"),
    (re.compile(r"\b(?:players?|opponents?) who sacrificed [\w ]+? this way\b", re.I),
     "sacrificed_this_way"),
    # "…each player who didn't discard a creature card this way" (Strongarm
    # Tactics, ONS): both polarities read the one record.
    (re.compile(
        r"\b(?:players?|opponents?) who (?:discarded|didn't discard) [\w ]+? "
        r"this way\b", re.I,
    ), "discarded_this_way"),
    # "Each player whose coin comes up tails sacrifices a creature of their
    # choice." (Goblin Assassin, LGN.) Anchored at a sentence's start: Mana
    # Clash's "…deals 1 damage **to** each player whose coin comes up tails" is
    # read whole by its own paragraph production (``coin_flip_damage_loop``,
    # whose two coins are flipped inside it), never as a seat deed.
    (re.compile(
        r"(?:^|\. )each player whose coin comes up tails\b", re.I | re.M,
    ), "coin_came_up_tails"),
)


def _walk(value):
    if isinstance(value, OracleInstruction):
        yield value.payload
        for inner in value.payload.values():
            yield from _walk(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _walk(inner)
    elif isinstance(value, dict):
        yield value
        for inner in value.values():
            yield from _walk(inner)


def _program_dicts(program):
    yield from _walk(list(program.instructions))
    for ability in list(program.triggered_abilities) + list(program.activated_abilities):
        yield from _walk(getattr(ability, "instruction", None))


def _is_player_target(described) -> bool:
    return (
        isinstance(described, dict)
        and described.get("kind") in _PLAYER_TARGET_KINDS
        and "quantifier" in described
    )


@pytest.fixture(scope="module")
def deed_census():
    """``[(card name, printed kinds, [(seat, deed payload)], retired flags)]``
    for every supported compilation unit of the pool that prints a deed or
    compiles one."""
    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    rows = []
    for card, program in compiled_units(sorted(pool.values(), key=lambda c: c.name)):
        text = card.oracle_text or ""
        printed = Counter(
            kind for pattern, kind in _PRINTED for _ in pattern.finditer(text)
        )
        if not program.supported:
            continue
        deeds, flags = [], []
        for described in _program_dicts(program):
            if _is_player_target(described):
                flags.extend(flag for flag in _RETIRED_FLAGS if flag in described)
                if described.get("did"):
                    deeds.append(("target", described["did"]))
            for key, seat in (("recipient_did", "recipients"), ("who_did", "payers")):
                if described.get(key):
                    deeds.append((seat, described[key]))
        if printed or deeds or flags:
            rows.append((card.name, printed, deeds, flags))
    return rows


def test_the_census_found_every_kind_the_pool_prints(deed_census):
    """The floor: a census that matched nothing would pass every test below."""
    printed = Counter()
    for _name, kinds, _deeds, _flags in deed_census:
        printed.update(kinds)
    assert set(printed) == set(PLAYER_DEEDS), printed
    assert sum(printed.values()) >= 4
    assert len({name for name, *_ in deed_census}) >= 3


def test_no_seat_narrowing_is_spelled_as_a_flag(deed_census):
    """One spelling: a player target carries its clause as ``did``. On the base
    commit this named Fire and Brimstone and Diseased Vermin."""
    flagged = {name: flags for name, _k, _d, flags in deed_census if flags}
    assert flagged == {}


def test_every_printed_deed_reaches_a_payload(deed_census):
    """Each printed clause of a supported card is in its program, with a kind
    the one reader answers — never parsed and dropped."""
    missing = {}
    unknown = {}
    for name, printed, deeds, _flags in deed_census:
        compiled = Counter(deed["kind"] for _seat, deed in deeds)
        short = printed - compiled
        if short:
            missing[name] = dict(short)
        strays = {deed["kind"] for _seat, deed in deeds} - set(PLAYER_DEEDS)
        if strays:
            unknown[name] = strays
    assert missing == {}
    assert unknown == {}


def test_a_deed_on_a_chosen_seat_is_one_the_picker_can_answer(deed_census):
    """A chosen seat's clause is enforced while the target is chosen (CR 601.2c)
    or nowhere, so every one that compiled is answerable then."""
    on_targets = [
        (name, deed) for name, _k, deeds, _f in deed_census
        for seat, deed in deeds if seat == "target"
    ]
    assert {name for name, _deed in on_targets} >= {
        "Fire and Brimstone", "Diseased Vermin",
    }
    assert all(PLAYER_DEEDS[deed["kind"]].at_announcement for _n, deed in on_targets)


# ---------------------------------------------------------------------------
# Invented cards: each shape the parse now reaches, in a game
# ---------------------------------------------------------------------------


def _table(seats: int = 3) -> Game:
    game = Game(players=[PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)])
    game.enforce_mana_costs = False
    return game


def _offered(game, card, spec, *, source=None) -> list[int]:
    return sorted(
        entry["seat"]
        for entry in game._enumerate_targets(
            0, card, spec, for_cast=source is None,
            source_permanent=source, ability_source=source,
        )
        if entry.get("kind") == "player"
    )


def test_target_opponent_who_attacked_this_turn_narrows_the_picker():
    """On the base commit the flag was read only on "target **player**", so
    this compiled supported and the picker offered both opponents."""
    card = _mk_card("Invented Brimstone", "{R}", "Instant",
                    "This spell deals 3 damage to target opponent who attacked this turn.")
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    game = _table()
    game.players[0].hand = [card]
    game.players[1].attacked_this_turn = True
    game.players[0].attacked_this_turn = True

    assert _offered(game, card, derive_cast_spec(card, program)) == [1], (
        "an opponent who attacked; not the caster, who is no opponent"
    )
    refused = game.cast_from_hand(0, card.name, target_player_index=2)
    assert not refused.supported, "seat 3 did not attack"
    cast = game.cast_from_hand(0, card.name, target_player_index=1)
    assert cast.supported, cast.details
    resolve_stack(game)
    assert [p.life for p in game.players] == [20, 17, 20], game.log


def test_target_player_previously_dealt_damage_by_it_narrows_the_picker():
    """The record is on the ability's source. On the base commit the flag was
    read only on "target **opponent**", so every seat was offered."""
    card = _mk_card(
        "Invented Vermin", "{B}", "Creature — Rat",
        "{T}: This creature deals 1 damage to target player previously dealt damage by it.",
    )
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    game = _table()
    rat = Permanent(card=card)
    rat.summoning_sick = False
    rat.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield = [rat]
    game._sync_control()
    (ability,) = program.activated_abilities
    spec = derive_activation_spec(ability)

    assert _offered(game, card, spec, source=rat) == []
    deal_damage(game, {"recipient": game.players[2], "amount": 1, "source": rat})
    assert _offered(game, card, spec, source=rat) == [2]

    refused = game.activate_permanent_ability(0, card.name, target_player_index=1)
    assert not refused.supported, "seat 2 was never dealt damage by it"
    activated = game.activate_permanent_ability(0, card.name, target_player_index=2)
    assert activated.supported, activated.details
    resolve_stack(game)
    assert game.players[2].life == 19 and game.players[1].life == 20, game.log


def test_a_seat_record_is_answered_at_announcement_too():
    """"Who tapped a land for mana this turn" is a seat's own per-turn record,
    readable while a target is chosen — the same kind of fact as "who attacked
    this turn", so a chosen seat may carry it. On the base commit the clause
    was read only for "each player", and this line did not parse."""
    card = _mk_card("Invented Desolation", "{B}", "Instant",
                    "This spell deals 2 damage to target player who tapped a land for mana this turn.")
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    game = _table()
    game.players[2].tapped_land_for_mana_this_turn = True

    assert _offered(game, card, derive_cast_spec(card, program)) == [2]


def test_a_record_of_this_resolution_cannot_narrow_a_chosen_seat():
    """"Who sacrificed a Plains **this way**" has no answer until the
    resolution has sacrificed something, so no picker can enforce it (CR
    601.2c): the line refuses, by name, rather than offering every seat."""
    card = _mk_card("Invented Desolation II", "{B}", "Instant",
                    "This spell deals 2 damage to target player who sacrificed a Plains this way.")
    program = compile_card_oracle(card)

    assert not program.supported
    refusal = compile_line(card.oracle_text, card_name=card.name)
    assert not refusal.instructions
    assert "announcement" in (refusal.lowering_error or ""), refusal


def test_a_chosen_sacrificer_with_a_deed_refuses():
    """The forced-sacrifice lowering hands its seat to the kind table, which
    describes no narrowing — so a chosen payer's clause has no picker to reach.
    On the base commit this compiled supported: every player was offered, and
    the handler then asked a non-tapper to sacrifice nothing."""
    card = _mk_card("Invented Sacrifice", "{B}", "Sorcery",
                    "Target player who tapped a land for mana this turn sacrifices a land.")
    program = compile_card_oracle(card)

    assert not program.supported
    refusal = compile_line(card.oracle_text, card_name=card.name)
    assert not refusal.instructions
    assert "chosen seat" in (refusal.lowering_error or ""), refusal


def test_each_opponent_who_attacked_this_turn_is_the_only_one_damaged():
    """A seat *set* narrowed by a deed is answered by the handler's loop
    through the same reader the picker asks. On the base commit the clause was
    read only after the "this way" and "tapped a land" spellings, and this line
    did not parse."""
    card = _mk_card("Invented Reprisal", "{R}", "Instant",
                    "This spell deals 2 damage to each opponent who attacked this turn.")
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    game = _table()
    game.players[0].hand = [card]
    game.players[0].attacked_this_turn = True
    game.players[2].attacked_this_turn = True

    cast = game.cast_from_hand(0, card.name)
    assert cast.supported, cast.details
    resolve_stack(game)

    assert [p.life for p in game.players] == [20, 20, 18], game.log


def test_seat_did_fails_closed():
    """An unknown kind, and a source record asked with no source, admit nobody:
    an unenforceable narrowing offered as satisfied is the silent direction."""
    game = _table()
    game.players[1].attacked_this_turn = True

    assert seat_did(game, 1, {"kind": "attacked_this_turn"})
    assert not seat_did(game, 1, {"kind": "no_such_record"})
    assert not seat_did(game, 1, {"kind": "dealt_damage_by_source"}, source=None)
    assert not seat_did(
        game, 1, {"kind": "sacrificed_this_way", "filter": {}}, results=None
    )


# ---------------------------------------------------------------------------
# The two shipped cards, driven
# ---------------------------------------------------------------------------


def _shipped(name: str):
    for path in manifest_set_paths():
        for card in load_cards(path):
            if card.name == name:
                return card
    raise LookupError(name)


def test_diseased_vermin_asks_an_interactive_seat_only_about_the_seat_it_hurt():
    """Three seats, one of them hurt: the trigger's prompt lists that seat
    alone, and the answer is where the damage goes."""
    vermin_card = _shipped("Diseased Vermin")
    game = _table()
    game.interactive_seats = {0}
    game.active_player_index = 0
    vermin = Permanent(card=vermin_card)
    vermin.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield = [vermin]
    game._sync_control()
    deal_damage(game, {"recipient": game.players[2], "amount": 1, "source": vermin})
    add_counters(vermin, "infection", 2)
    upkeep = [
        ability for ability in compile_card_oracle(vermin_card).triggered_abilities
        if ability.condition.kind == "upkeep_self"
    ][0]
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=vermin, card=vermin_card,
        instruction=upkeep.instruction, effect_kind=upkeep.effect_kind,
    )

    (offer,) = game.pending_choices
    assert offer.kind == "trigger_target"
    assert [(t["kind"], t["seat"]) for t in offer.data["targets"]] == [("player", 2)]
    assert game.confirm_trigger_target(0, seat=2)
    game.resolve_stack(pause_for_choices=True)

    assert [p.life for p in game.players] == [20, 20, 18], game.log


def test_fire_and_brimstone_is_refused_at_a_seat_that_did_not_attack():
    """The shipped card's picker after the fold: the attacker is offered, the
    bystander is refused before anything is paid, and the damage lands."""
    brimstone = _shipped("Fire and Brimstone")
    game = _table()
    game.players[0].hand = [brimstone, brimstone]
    game.players[2].attacked_this_turn = True

    assert _offered(game, brimstone, derive_cast_spec(
        brimstone, compile_card_oracle(brimstone)
    )) == [2]
    refused = game.cast_from_hand(0, brimstone.name, target_player_index=1)
    assert not refused.supported
    assert len(game.players[0].hand) == 2, "nothing was cast"
    cast = game.cast_from_hand(0, brimstone.name, target_player_index=2)
    assert cast.supported, cast.details
    resolve_stack(game)

    assert [p.life for p in game.players] == [16, 20, 16], game.log
