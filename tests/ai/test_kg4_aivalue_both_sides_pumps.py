"""A global pump over every player's creatures reaches both sides (kg4 aivalue).

``ai_valuation.reaches_both_sides`` is what makes the main-phase ability
chooser rehearse an effect instead of scoring it flat (2.5 for any "other"
effect, read as aimed at the activator's own side). It read a sweep's seat off
its noun phrase (``swept_filter``), and a global pump carries none: its seat
word is the payload key ``all`` — "All creatures get -1/-0" (Bone Flute) is
``all: True``, "Creatures you control get +1/+1" is ``all: False`` — and in
other kinds the same key is a quantity ("sacrifice **all** creatures you
control"). So every both-sides global pump read as aimed: Bone Flute, Fyndhorn
Pollen and Thran Weaponry were activated in their controller's main phase with
every creature they reached on the other side of the table.

Validated backwards: with ``pumps_every_seat`` answering False (the base,
``313bd09d``), the census finds Bone Flute, Fyndhorn Pollen and Thran
Weaponry proposed where they reach only the opponent's creatures, and Bone
Flute's and Fyndhorn Pollen's -1/-0 proposed where they reach only the AI's
own attackers.
"""

from __future__ import annotations

from unittest import mock

import pytest

from engine import ai_valuation
from engine.ai_abilities import choose_activation_action
from engine.ai_valuation import (
    ALL_MEANS_EVERY_MATCH_KINDS,
    ALL_MEANS_EVERY_SEAT_KINDS,
    _effect_steps,
    reaches_both_sides,
)
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from engine.tokens import make_token_card
from tests.helpers import _nosick, resolve_stack


def _pool() -> dict:
    cards = load_cards(manifest_set_paths(include_measured=True))
    return {card.name: card for card in compilation_units(cards)}


def _walk(instruction):
    """Every instruction under *instruction*, wrappers and modes opened."""
    yield instruction
    payload = instruction.payload or {}
    for key in ("steps", "then", "else", "action", "otherwise", "effect"):
        nested = payload.get(key)
        if isinstance(nested, (list, tuple)):
            for child in nested:
                if hasattr(child, "kind"):
                    yield from _walk(child)
    for mode in payload.get("modes") or ():
        child = mode.get("instruction") if isinstance(mode, dict) else None
        if child is not None:
            yield from _walk(child)


def _programs(pool):
    for card in pool.values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        roots = [*program.instructions]
        roots += [a.instruction for a in program.activated_abilities if a.instruction]
        roots += [t.instruction for t in program.triggered_abilities if t.instruction]
        yield card, roots


def test_every_kind_carrying_all_is_read_one_way_or_the_other():
    """The key ``all`` is a seat word in some kinds and a quantity in others,
    and the payload cannot say which: every kind in the pool (both manifest
    roles) whose payload carries it is named in exactly one of the two
    tables, so a new kind cannot be read the wrong way unasked."""
    carrying: dict[str, set] = {}
    for card, roots in _programs(_pool()):
        for root in roots:
            for step in _walk(root):
                if "all" in (step.payload or {}):
                    carrying.setdefault(step.kind, set()).add(card.name)
    assert not ALL_MEANS_EVERY_SEAT_KINDS & ALL_MEANS_EVERY_MATCH_KINDS
    unread = set(carrying) - ALL_MEANS_EVERY_SEAT_KINDS - ALL_MEANS_EVERY_MATCH_KINDS
    assert unread == set(), {kind: sorted(carrying[kind])[:5] for kind in unread}
    # Floor: how much the census read.
    assert len(carrying.get("buff_creatures_global", ())) >= 60, carrying.keys()
    assert ALL_MEANS_EVERY_SEAT_KINDS <= set(carrying)


def _table(own, other) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    pool = _pool()
    for seat, cards in ((0, own), (1, other)):
        for card in cards:
            game.players[seat].battlefield.append(_nosick(Permanent(card=card)))
        game.players[seat].library = [pool["Island"]] * 10
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(0)
    return game


@pytest.mark.parametrize("name, kind", [
    ("Bone Flute", "buff_creatures_global"),
    ("Thran Weaponry", "buff_creatures_global_while_source_tapped"),
])
def test_all_in_a_global_pump_is_every_players_creatures(name, kind):
    """The seat reading, asked of the engine: each kind in
    ``ALL_MEANS_EVERY_SEAT_KINDS``, activated for real, changes a creature on
    each side of the table."""
    pool = _pool()
    bears = pool["Grizzly Bears"]
    game = _table([pool[name], bears], [bears])
    source = game.players[0].battlefield[0]
    ability = usable_activated_abilities(compile_card_oracle(source.card))[0]
    assert any(step.kind == kind for step in _effect_steps(ability.instruction))
    result = game.queue_permanent_ability(0, name, permanent_index=0)
    assert result.supported, result.details
    resolve_stack(game)
    mine, theirs = game.players[0].battlefield[1], game.players[1].battlefield[0]
    assert (mine.effective_power, mine.effective_toughness) != (2, 2), game.log[-5:]
    assert (theirs.effective_power, theirs.effective_toughness) != (2, 2), game.log[-5:]


def test_a_global_pump_with_a_seat_in_it_is_still_aimed():
    """"Creatures your opponents control get -2/-2" (Massacre Wurm) and
    "Creatures target player controls get +1/+1" (Day) carry ``all`` and a
    seat beside it; "creatures you control" carries ``all: False``."""
    seated, own_side = [], []
    for card, roots in _programs(_pool()):
        for root in roots:
            for step in _walk(root):
                payload = step.payload or {}
                if step.kind not in ALL_MEANS_EVERY_SEAT_KINDS:
                    continue
                if payload.get("all") and (payload.get("opponents_only") or payload.get("controller")):
                    seated.append(card.name)
                    assert not ai_valuation.pumps_every_seat(step), card.name
                elif payload.get("all") is False:
                    own_side.append(card.name)
                    assert not ai_valuation.pumps_every_seat(step), card.name
    assert {"Massacre Wurm", "Day"} <= set(seated), seated
    assert len(own_side) >= 20, own_side


# --- the AI's main phase ------------------------------------------------------


def _reached_token(step):
    """A 2/2 creature token the pump *step* reaches by a person's reading of
    its narrowing (its creature types and colour)."""
    payload = step.payload or {}
    subtypes = [word.title() for word in payload.get("subtypes") or ()] or ["Bear"]
    color = payload.get("color")
    return make_token_card(
        f"{' '.join(subtypes)} Token", 2, 2, f"Creature — {' '.join(subtypes)}",
        colors=(color,) if color else (),
    )


def _both_sides_pumps(pool) -> list:
    """``(card, ability index, pump step)`` for every usable activated ability
    of a supported card, both manifest roles, whose effect is a global pump
    over every player's creatures with a narrowing a person can read off the
    payload (creature types, colour) — no chosen word, no combat role, no
    relation to a host — and whose cost the chooser prices (no permanent or
    card given up, which it skips whatever the effect: Goblin Soothsayer,
    Orc General)."""
    rows = []
    for name, card in sorted(pool.items()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None or ability.cost.sacrifice_filter is not None:
                continue
            if ability.cost.discard_cards:
                continue
            pumps = [
                step for step in _effect_steps(ability.instruction)
                if step.kind in ALL_MEANS_EVERY_SEAT_KINDS
                and (step.payload or {}).get("all") is True
                and not (step.payload or {}).get("opponents_only")
                and not (step.payload or {}).get("controller")
            ]
            if not pumps:
                continue
            payload = pumps[0].payload
            if any(payload.get(key) for key in (
                "subtype_filter_from", "attacking_only", "blocking_only", "filter",
            )):
                continue
            rows.append((card, index, pumps[0]))
    return rows


def _reaches_its_source(card, step) -> bool:
    payload = step.payload or {}
    type_line = (card.type_line or "").lower()
    if payload.get("exclude_self") or "creature" not in type_line:
        return False
    subtypes = {word.lower() for word in payload.get("subtypes") or ()}
    printed = set(type_line.replace("—", " ").split())
    if subtypes and not subtypes & printed:
        return False
    color = payload.get("color")
    return not color or color in (card.colors or ())


def _proposes(game: Game, name: str, index: int) -> bool:
    action = choose_activation_action(game, 0)
    return (
        action is not None and action.permanent_name == name
        and (action.ability_index or 0) == index
    )


def _main_phase_census(pool) -> dict:
    found = {"examined": [], "for_the_opponent": [], "own_shrunk": [], "own_pumped": []}
    for card, index, step in _both_sides_pumps(pool):
        if _reaches_its_source(card, step):
            continue  # its own body is in the fight it pumps (Bladewing the Risen)
        found["examined"].append(card.name)
        reached = _reached_token(step)
        # Every creature it reaches is the opponent's, and the AI has nothing
        # the pump could help in a fight.
        if _proposes(_table([card], [reached] * 3), card.name, index):
            found["for_the_opponent"].append(card.name)
        # Every creature it reaches is the AI's, untapped and able to attack
        # into an empty board.
        own = _proposes(_table([card, *[reached] * 3], []), card.name, index)
        shrinks = sum(
            value for value in (step.payload.get("power"), step.payload.get("toughness"))
            if isinstance(value, int) and not isinstance(value, bool)
        ) < 0
        if own and shrinks:
            found["own_shrunk"].append(card.name)
        elif own:
            found["own_pumped"].append(card.name)
    return found


def test_no_both_sides_pump_is_activated_where_it_helps_only_the_other_side():
    found = _main_phase_census(_pool())
    assert found["for_the_opponent"] == [], found
    assert found["own_shrunk"] == [], found
    # Floors: how much the census examined, and that the gate is not a ban.
    assert len(found["examined"]) >= 3, found
    assert {"Bone Flute", "Thran Weaponry"} <= set(found["examined"]), found
    assert "Thran Weaponry" in found["own_pumped"], found


def test_without_the_seat_reading_the_census_finds_what_the_base_did():
    """Backwards: ``all`` unread, as on 313bd09d."""
    with mock.patch.object(ai_valuation, "pumps_every_seat", lambda step: False):
        found = _main_phase_census(_pool())
    assert {"Bone Flute", "Fyndhorn Pollen", "Thran Weaponry"} <= set(
        found["for_the_opponent"]
    ), found
    assert {"Bone Flute", "Fyndhorn Pollen"} <= set(found["own_shrunk"]), found


def test_reaches_both_sides_reads_the_pool_s_both_sides_pumps():
    rows = _both_sides_pumps(_pool())
    for card, index, _step in rows:
        ability = usable_activated_abilities(compile_card_oracle(card))[index]
        assert reaches_both_sides(ability.instruction), card.name
