"""Pool-wide: every Aura ability whose effect lands on the creature it enchants
is used for the side it helps, and every such Aura is cast on that side (SCG
Phase 5, AI-1).

Pemmin's Aura went on a person's Krosan Warchief and the AI then paid {U} to
untap the person's creature. Two questions, each asked of every member of its
class over both manifest roles:

* **the activation** — an Aura's ability whose every step acts on its host
  ("Enchanted creature …"), with the Aura on the AI's board and its host on
  either board: the own-board chooser's per-ability gate
  (``ai_abilities._activation_candidate``) never proposes it for the host on
  the other side from the one the step helps;
* **the cast** — an "Enchant creature" Aura whose host abilities all help one
  side, with a creature on each board: the cast chooser puts it on that side.

The side each step helps is **a person's reading, written here**
(``_READ``), so the policy is not checked against its own tables. Each is run
backwards too: with the gate taken out (as on 43a45e81) and with the harmful
markers read as substrings (as on 43a45e81), the census finds what Phase 5
saw.
"""
from __future__ import annotations

import re
from unittest import mock

import pytest

from engine import ai_abilities, ai_targets
from engine.ai_abilities import _activation_candidate
from engine.ai_policy import choose_cast_action
from engine.ai_target_sides import HOST_KINDS, _acts_on_the_host
from engine.ai_weighed_cast import _effect_steps
from engine.aura_attachment import attach_aura
from engine.mixins.stack import aura_enchant_noun
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick


def _pool() -> dict:
    cards = load_cards(manifest_set_paths(include_measured=True))
    return {card.name: card for card in compilation_units(cards)}


def _sign(step) -> "str | None":
    payload = step.payload or {}
    total = sum(
        value for value in (payload.get("power"), payload.get("toughness"))
        if isinstance(value, int) and not isinstance(value, bool)
    )
    counter = payload.get("counter")
    if isinstance(counter, str):
        total += sum(int(part) for part in re.findall(r"[+-]\d+", counter))
    return "you" if total >= 0 else "opponent"


#: A person's reading of what each host step does for the host's controller.
#: A bounce, a phase-out, a recolour and a type change are either side's, by
#: the moment, and are not read.
_READ = {
    "untap_enchanted_creature": lambda step: "you",
    "grant_enchanted_keyword_until_eot": lambda step: "you",
    "grant_regeneration_to_enchanted_creature": lambda step: "you",
    "grant_prevention_shield": lambda step: "you",
    "grant_whole_prevention_shield": lambda step: "you",
    "tap_enchanted_creature": lambda step: "opponent",
    "attached_cant_block_until_eot": lambda step: "opponent",
    "pump_enchanted_creature": _sign,
    "add_pt_counters_to_attached": _sign,
}


def _person_side(instruction) -> "str | None":
    """The side the person's reading gives an ability whose every step acts
    on its host, or None (a step acting elsewhere, or one not read)."""
    steps = [step for step in _effect_steps(instruction) if step.kind != "choose_creature_type"]
    if not steps:
        return None
    sides = set()
    for step in steps:
        payload = step.payload or {}
        on_host = not isinstance(payload.get("targets"), dict) and (
            any(word in step.kind for word in ("enchanted", "equipped", "attached"))
            or payload.get("to_attached")
        )
        if not on_host or step.kind not in _READ:
            return None
        sides.add(_READ[step.kind](step))
    return "opponent" if "opponent" in sides else "you"


def _host_abilities(pool) -> list:
    """``(card, ability index, ability, side)`` for every usable ability of a
    supported Aura that the person's reading gives a side."""
    rows = []
    for name, card in sorted(pool.items()):
        if "Aura" not in (card.type_line or ""):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None:
                continue
            side = _person_side(ability.instruction)
            if side is not None:
                rows.append((card, index, ability, side))
    return rows


def _board(pool, aura, host_seat: int) -> Game:
    bears = pool["Grizzly Bears"]
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.players[0].battlefield = [_nosick(Permanent(card=aura)), _nosick(Permanent(card=bears))]
    game.players[1].battlefield = [_nosick(Permanent(card=bears))]
    for player in game.players:
        player.library = [pool["Island"]] * 10
    host = game.players[host_seat].battlefield[-1]
    attach_aura(game.players[0].battlefield[0], host)
    game._recompute_continuous_effects()
    game.start_turn(0)
    for _ in range(6):
        if game.current_turn_phase == "precombat_main":
            break
        game._close_current_priority_step()
    host.tapped = True  # so an untap moves something
    return game


def _activation_census(pool) -> dict:
    found = {"examined": [], "right_side": [], "wrong_side": []}
    for card, index, ability, side in _host_abilities(pool):
        found["examined"].append((card.name, index))
        for host_seat in (0, 1):
            game = _board(pool, card, host_seat)
            aura = game.players[0].battlefield[0]
            usable = game.usable_abilities_of(aura)
            if index >= len(usable):
                continue
            candidate = _activation_candidate(
                game, 0, 0, aura, usable[index], None if index == 0 else index,
            )
            if candidate is None:
                continue
            helps = (host_seat == 0) == (side == "you")
            found["right_side" if helps else "wrong_side"].append((card.name, index, host_seat))
    return found


def test_no_host_ability_is_activated_for_the_other_side():
    found = _activation_census(_pool())
    assert found["wrong_side"] == [], found["wrong_side"]
    # Floors: how much the census examined, and that the gate is not a ban.
    assert len(found["examined"]) >= 30, found["examined"]
    assert len(found["right_side"]) >= 15, found["right_side"]
    assert ("Pemmin's Aura", 0) in found["examined"]


@pytest.mark.full
def test_without_the_gate_the_census_finds_what_phase_five_saw():
    """Backwards: ``_host_refusal`` taken out, as on 43a45e81."""
    with mock.patch.object(ai_abilities, "_host_refusal", lambda *args: False):
        found = _activation_census(_pool())
    wrong = {name for name, _index, _seat in found["wrong_side"]}
    assert len(found["wrong_side"]) >= 12, found["wrong_side"]
    assert {"Pemmin's Aura", "Instill Energy", "Manacles of Decay"} <= wrong, wrong


def _cast_census(pool) -> dict:
    found = {"examined": [], "cast": [], "wrong_side": []}
    sides_by_aura: dict = {}
    for card, _index, _ability, side in _host_abilities(pool):
        sides_by_aura.setdefault(card.name, (card, set()))[1].add(side)
    bears = pool["Grizzly Bears"]
    for name, (card, sides) in sorted(sides_by_aura.items()):
        if len(sides) != 1 or aura_enchant_noun(card) != "creature":
            continue  # its abilities disagree, or its enchant word names a seat
        (side,) = sides
        found["examined"].append(name)
        game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
        game.enforce_mana_costs = False
        game.interactive_seats = set()
        game.players[0].battlefield = [_nosick(Permanent(card=bears))]
        game.players[1].battlefield = [_nosick(Permanent(card=bears))]
        game.players[0].hand = [card]
        game._sync_control()
        action = choose_cast_action(game, 0)
        if action is None or action.card_name != name:
            continue
        found["cast"].append(name)
        if (action.target_player_index == 0) != (side == "you"):
            found["wrong_side"].append((name, side, action.target_player_index))
    return found


def test_every_host_ability_aura_is_cast_on_the_side_its_abilities_help():
    found = _cast_census(_pool())
    assert found["wrong_side"] == [], found["wrong_side"]
    assert len(found["examined"]) >= 25, found["examined"]
    assert len(found["cast"]) >= 25, found["cast"]
    assert {"Pemmin's Aura", "Instill Energy", "Firebreathing"} <= set(found["cast"])


def test_with_the_markers_read_as_substrings_the_cast_census_finds_pemmins_aura():
    """Backwards: the harmful markers matched anywhere in the text, as on
    43a45e81 — "tap enchanted" inside "Untap enchanted creature"."""
    markers = ("gets -", "doesn't untap", "tap enchanted", "you control enchanted",
               "can't attack", "can't block")

    def substring_reading(card):
        text = (card.oracle_text or "").lower()
        return any(marker in text for marker in markers) or (
            ai_targets._HARMFUL_AURA_PATTERN.search(text) is not None
        )

    with mock.patch.object(ai_targets, "_aura_harms_its_host", substring_reading):
        found = _cast_census(_pool())
    wrong = {name for name, _side, _seat in found["wrong_side"]}
    assert {"Pemmin's Aura", "Instill Energy"} <= wrong, found["wrong_side"]


def test_every_step_an_activated_ability_aims_at_its_host_is_one_the_side_reader_reads():
    """The table behind ``host_effect_side`` against the pool: every step of
    an activated ability, both manifest roles, that names its source's host
    (a kind spelling "enchanted", "equipped" or "attached", or a payload
    pointed at it) and no target of its own is one ``_acts_on_the_host``
    reads — so a new host kind cannot be activated for either side unasked."""
    unread, seen = set(), set()
    for card in _pool().values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for ability in usable_activated_abilities(program):
            if ability.instruction is None:
                continue
            for step in _effect_steps(ability.instruction):
                payload = step.payload or {}
                if isinstance(payload.get("targets"), dict):
                    continue
                names_host = (
                    any(word in step.kind for word in ("enchanted", "equipped", "attached"))
                    or payload.get("to_attached")
                )
                if not names_host:
                    continue
                seen.add(step.kind)
                if not _acts_on_the_host(step):
                    unread.add(step.kind)
    assert unread == set(), sorted(unread)
    assert len(seen) >= 10, sorted(seen)
    assert seen - {"grant_prevention_shield", "grant_whole_prevention_shield"} <= HOST_KINDS


# --- the targeted twin: an untap aimed at something untapped ------------------

_TARGET_UNTAPS = frozenset({"untap_target_permanent", "untap_target_land"})


def _untap_census(pool) -> dict:
    """Every non-Aura permanent whose first usable ability only untaps its
    target(s), on the AI's board with a creature, an artifact and a land
    beside it, twice: everything untapped, and everything but the source
    tapped. Each proposal's target is read."""
    found = {"examined": [], "moved_nothing": [], "untapped_something": 0}
    for name, card in sorted(pool.items()):
        if card.primary_type in ("instant", "sorcery") or "Aura" in (card.type_line or ""):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        usable = usable_activated_abilities(program)
        if not usable or usable[0].instruction is None:
            continue
        steps = _effect_steps(usable[0].instruction)
        if not steps or not all(step.kind in _TARGET_UNTAPS for step in steps):
            continue
        found["examined"].append(name)
        for tapped in (False, True):
            game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
            game.enforce_mana_costs = False
            game.interactive_seats = set()
            beside = (pool["Grizzly Bears"], pool["Ornithopter"], pool["Forest"])
            game.players[0].battlefield = [_nosick(Permanent(card=c)) for c in (card, *beside)]
            game.players[1].battlefield = [_nosick(Permanent(card=pool["Grizzly Bears"]))]
            if tapped:
                for permanent in game.players[0].battlefield[1:]:
                    permanent.tapped = True
            game._sync_control()
            action = ai_abilities.choose_activation_action(game, 0)
            if action is None or action.permanent_index != 0 or action.target_permanent_index is None:
                continue
            slots = action.target_permanent_index
            for slot in slots if isinstance(slots, list) else [slots]:
                target = game.permanent_at(action.target_player_index, slot)
                if target is None or not target.tapped or target is game.players[0].battlefield[0]:
                    found["moved_nothing"].append((name, tapped, getattr(target, "card", None) and target.card.name))
                else:
                    found["untapped_something"] += 1
    return found


def test_no_untap_is_aimed_at_a_permanent_that_is_untapped():
    found = _untap_census(_pool())
    assert found["moved_nothing"] == [], found["moved_nothing"]
    assert len(found["examined"]) >= 8, found["examined"]
    assert found["untapped_something"] >= 5, found


@pytest.mark.full
def test_without_the_tapped_filter_the_untaps_move_nothing():
    """Backwards: every candidate kept, tapped or not, as on 43a45e81."""
    with mock.patch.object(ai_abilities, "_untaps_only", lambda instruction: False):
        found = _untap_census(_pool())
    names = {name for name, _tapped, _target in found["moved_nothing"]}
    assert {"Seeker of Skybreak", "Jandor's Saddlebags", "Voltaic Key"} <= names, found["moved_nothing"]
