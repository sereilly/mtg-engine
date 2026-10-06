"""An AI seat chooses the mode of a "Choose one —" spell (CR 601.2b, CR 700.2a).

The engine has judged a modal spell against the mode it announces since
Planeshift; the AI was the one reader with no mode. Its cast named none, the
engine resolved the first bullet, and so Crosis's Charm only ever bounced, Hull
Breach only ever destroyed an artifact, Reign of Chaos — two bullets, both of
them a pair of targets — was never cast at all, and a Charm whose first bullet
had nothing to point at was a card the seat held while its second would have
won the game. 34 of the pool's 88 modes were reachable.

These are the behaviours, card by card: the board, the hand and the life
totals after the cast. ``test_ai_mode_chooser_census.py`` is the same question
asked of every mode in the pool.
"""
from __future__ import annotations

import ast
from collections import Counter
from dataclasses import fields
from pathlib import Path

import pytest

from engine import ai_simulator
from engine.ai_policy import (
    CastAction,
    cast_announcement,
    choose_cast_action,
    choose_combat_instant_cast_action,
    spell_being_cast,
)
from engine.ai_valuation import (
    caster_chooses_a_mode,
    considering_mode,
    instruction_target_side,
    mode_considered,
    spell_target_side,
    spell_text,
)
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, _mk_creature_card, _nosick, resolve_stack


def _duel(hand=(), mine=(), theirs=(), my_graveyard=(), library=()):
    forest = _mk_card(name="Forest", type_line="Basic Land - Forest")
    ai = PlayerState(
        name="AI", hand=list(hand), graveyard=list(my_graveyard),
        battlefield=[_nosick(Permanent(card=c)) for c in mine],
        library=list(library) or [forest] * 5,
    )
    opp = PlayerState(
        name="Opp", battlefield=[_nosick(Permanent(card=c)) for c in theirs],
        library=[forest] * 5,
    )
    game = Game(players=[ai, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


def _cast(game, action):
    """Make *action*'s announcement the way every executor does, and resolve."""
    spell = spell_being_cast(game.players[0].hand, action)
    result = game.queue_from_hand(0, spell.name, **cast_announcement(action))
    assert result.supported, result.details
    chosen = game.stack[-1].chosen_mode_index
    resolve_stack(game)
    return chosen


def _names(cards):
    return sorted(card.name for card in cards)


RELIC = _mk_card(name="Their Relic", type_line="Artifact")
SHRINE = _mk_card(name="Their Shrine", type_line="Enchantment")
WALL = _mk_card(name="Their Wall", type_line="Creature - Wall", power=0, toughness=4)
BLACK = _mk_card(
    name="Their Ghoul", type_line="Creature - Zombie", colors=("B",), power=0, toughness=4,
)
RED = _mk_card(
    name="Their Goblin", type_line="Creature - Goblin", colors=("R",), power=2, toughness=2,
)


# --- One card, three boards: each asks for a different bullet ------------------


def test_crosis_charm_destroys_the_artifact_when_that_is_what_the_board_holds(catalog_by_name):
    """It "only ever bounced": mode 0 is "return target permanent to its
    owner's hand", and a cast naming no mode is mode 0."""
    game = _duel(hand=[catalog_by_name["Crosis's Charm"]], theirs=[RELIC])

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 2
    assert _cast(game, action) == 2
    assert _names(game.players[1].graveyard) == ["Their Relic"], "destroyed, not returned"
    assert game.players[1].hand == []


def test_crosis_charm_destroys_a_nonblack_creature(catalog_by_name):
    game = _duel(hand=[catalog_by_name["Crosis's Charm"]], theirs=[WALL])

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 1
    assert _cast(game, action) == 1
    assert _names(game.players[1].graveyard) == ["Their Wall"]


def test_crosis_charm_bounces_the_creature_its_kill_mode_may_not_name(catalog_by_name):
    """"Destroy target **nonblack** creature": against a black one the kill
    has no legal announcement, so the bounce is the mode — the engine's list
    of announceable modes is the population the policy weighs."""
    card = catalog_by_name["Crosis's Charm"]
    game = _duel(hand=[card], theirs=[BLACK])
    assert game.announceable_modes(0, card) == [0]

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 0
    _cast(game, action)
    assert _names(game.players[1].hand) == ["Their Ghoul"]
    assert game.players[1].graveyard == []


def test_a_charm_with_no_announceable_mode_is_not_proposed(catalog_by_name):
    """CR 700.2a: a mode that cannot choose legal targets cannot be chosen,
    and with every bullet targeted an empty board leaves none."""
    card = catalog_by_name["Crosis's Charm"]
    game = _duel(hand=[card])

    assert game.announceable_modes(0, card) == []
    assert choose_cast_action(game, 0) is None


# --- The card that was uncastable while a later bullet won the game -----------


def test_a_later_bullet_is_cast_when_the_first_has_nothing_to_point_at(catalog_by_name):
    """Darigaaz's Charm: "Return target creature card from your graveyard to
    your hand" with an empty graveyard made the whole card uncastable to an AI
    seat — and "deals 3 damage to any target" was lethal."""
    card = catalog_by_name["Darigaaz's Charm"]
    game = _duel(hand=[card])
    game.players[1].life = 3
    assert 0 not in game.announceable_modes(0, card)

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 1
    assert action.target_player_index == 1
    _cast(game, action)
    assert game.players[1].life == 0
    assert game.players[0].life == 20


def test_blue_elemental_blast_destroys_a_red_permanent_in_the_main_phase(catalog_by_name):
    """Its first bullet counters a red spell, so with an empty stack the card
    was offered every turn and refused every turn until the policy learnt to
    hold it — and then it was held whatever red permanent sat across the
    table."""
    card = catalog_by_name["Blue Elemental Blast"]
    game = _duel(hand=[card], theirs=[RED])

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 1
    assert _cast(game, action) == 1
    assert _names(game.players[1].graveyard) == ["Their Goblin"]

    held = _duel(hand=[card], theirs=[WALL])
    assert choose_cast_action(held, 0) is None, "nothing red to counter or destroy"


# --- Roles: a bullet that names two targets ------------------------------------


def test_hull_breach_takes_both_when_both_are_there(catalog_by_name):
    """"Destroy target artifact" / "Destroy target enchantment" / "Destroy
    target artifact and target enchantment": the third is a roles
    announcement, which the policy could not walk for a modal card at all —
    the game's spec for one asked with no mode is "modal"."""
    card = catalog_by_name["Hull Breach"]
    game = _duel(hand=[card], theirs=[RELIC, SHRINE])

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 2
    assert _cast(game, action) == 2
    assert _names(game.players[1].graveyard) == ["Their Relic", "Their Shrine"]


def test_hull_breach_takes_the_enchantment_when_that_is_all_there_is(catalog_by_name):
    game = _duel(hand=[catalog_by_name["Hull Breach"]], theirs=[SHRINE, WALL])

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 1
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Shrine"]
    assert _names(p.card for p in game.players[1].battlefield) == ["Their Wall"]


def test_reign_of_chaos_is_cast_at_all(catalog_by_name):
    """Both bullets are a pair of targets, so no mode of it was ever
    announced by an AI seat."""
    plains = catalog_by_name["Plains"]
    knight = _mk_card(
        name="Their Knight", type_line="Creature - Knight", colors=("W",), power=2, toughness=2,
    )
    game = _duel(hand=[catalog_by_name["Reign of Chaos"]], theirs=[plains, knight])

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 0
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Plains", "Their Knight"]


# --- Each bullet is aimed where its own effect wants ----------------------------


def test_a_bullet_that_could_only_hurt_its_caster_loses_to_one_that_helps(catalog_by_name):
    """Chaos Charm with only the caster's own creature on the table: "deals 1
    damage to target creature" has a legal target and the wrong one, "gains
    haste" has the right one."""
    mine = _mk_creature_card("Own Bear", 2, 2)
    card = catalog_by_name["Chaos Charm"]
    game = _duel(hand=[card], mine=[mine])
    assert game.announceable_modes(0, card) == [1, 2]

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 2
    bear = game.permanent_by_id(action.target_permanent_ids[0])
    assert bear.card is mine
    game.queue_from_hand(0, card.name, **cast_announcement(action))
    resolve_stack(game)
    assert game._has_keyword(bear, "haste")
    assert bear.damage_marked == 0


def test_a_wall_is_destroyed_rather_than_pinged(catalog_by_name):
    """"Chaos Charm deals 1 damage to target creature" scored as burn to a
    player's face and outranked "Destroy target Wall" at a Wall."""
    game = _duel(hand=[catalog_by_name["Chaos Charm"]], theirs=[WALL])

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index == 0
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Wall"]


def test_the_template_needs_no_name():
    """An invented card printing the same head: nothing here is keyed to a
    Charm."""
    probe = _mk_card(
        name="Probe Charm", mana_cost="{R}", type_line="Instant",
        oracle_text=(
            "Choose one —\n"
            "• Destroy target artifact.\n"
            "• Target creature gains haste until end of turn."
        ),
    )
    program = compile_card_oracle(probe)
    assert program.supported and len(program.modes) == 2
    assert caster_chooses_a_mode(probe)

    game = _duel(hand=[probe], theirs=[RELIC])
    action = choose_cast_action(game, 0)
    assert action is not None and action.mode_index == 0
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Relic"]

    mine = _mk_creature_card("Own Bear", 2, 2)
    game = _duel(hand=[probe], mine=[mine], theirs=[_mk_creature_card("Their Bear", 2, 2)])
    action = choose_cast_action(game, 0)
    assert action is not None and action.mode_index == 1
    assert game.permanent_by_id(action.target_permanent_ids[0]).card is mine


# --- "Choose one or more —" ----------------------------------------------------


def test_sublime_epiphany_takes_every_mode_worth_casting(catalog_by_name):
    """One cost, every bullet with something to do: the opposing creature goes
    back to its owner's hand, the caster's own is copied, and a card is drawn.
    Named one mode at a time this was six mana for a cantrip."""
    mine = _mk_creature_card("Own Bear", 2, 2)
    theirs = _mk_creature_card("Their Bear", 2, 2)
    spare = _mk_card(name="Spare Card", type_line="Sorcery")
    game = _duel(
        hand=[catalog_by_name["Sublime Epiphany"]], mine=[mine], theirs=[theirs],
        library=[spare] * 3,
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.mode_index is None
    assert [choice["index"] for choice in action.mode_choices] == [2, 3, 4]
    spell = spell_being_cast(game.players[0].hand, action)
    result = game.queue_from_hand(0, spell.name, **cast_announcement(action))
    assert result.supported, result.details
    assert [mode.index for mode in game.stack[-1].chosen_modes] == [2, 3, 4]
    resolve_stack(game)

    assert _names(game.players[1].hand) == ["Their Bear"]
    assert game.players[1].battlefield == []
    assert _names(p.card for p in game.players[0].battlefield) == ["Own Bear", "Own Bear"]
    assert _names(game.players[0].hand) == ["Spare Card"]


def test_a_choose_one_spell_is_never_handed_two_modes(catalog_by_name):
    """Only the "or more" head may take several (CR 601.2b): Crosis's Charm
    with a creature *and* an artifact to hit names one bullet."""
    game = _duel(hand=[catalog_by_name["Crosis's Charm"]], theirs=[RELIC, WALL])

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.mode_choices is None and action.mode_index in (0, 1, 2)


# --- The other caster: a mode an opponent chooses (CR 700.2e) ------------------


def test_a_mode_an_opponent_chooses_is_still_announced_with_none(catalog_by_name):
    """Fatal Lore, Misfortune, Library of Lat-Nam: the caster picks no mode,
    the engine refuses a cast that names one, and the opponent's seat answers
    as it always has."""
    for name in ("Fatal Lore", "Misfortune", "Library of Lat-Nam"):
        card = catalog_by_name[name]
        assert compile_card_oracle(card).mode_chooser is not None
        assert not caster_chooses_a_mode(card)
        game = _duel(hand=[card], mine=[_mk_creature_card("Own Bear", 2, 2)],
                     theirs=[_mk_creature_card("Their Bear", 2, 2)])

        action = choose_cast_action(game, 0)

        assert action is not None, name
        assert action.mode_index is None and action.mode_choices is None, name
        result = game.cast_from_hand(0, card.name, **cast_announcement(action))
        assert result.supported, (name, result.details)
        assert game.stack == []
        assert game.pending_choices == [], name


# --- The instant-speed window ----------------------------------------------------


def _opponent_casts(game, spell):
    game.start_turn(1)
    game._close_current_priority_step()
    game.players[1].hand.append(spell)
    queued = game.queue_from_hand(1, spell.name)
    assert queued.supported, queued.details


def test_dromars_charm_counters_a_spell_in_response(catalog_by_name):
    """"Counter target spell" is its second bullet, and the one moment it can
    be announced is with a spell on the stack — the web AI's priority
    response, which asked for mode 0 ("You gain 5 life") like everything
    else."""
    threat = _mk_card(
        name="Their Dragon", mana_cost="", type_line="Creature - Dragon", power=5, toughness=5,
    )
    card = catalog_by_name["Dromar's Charm"]
    game = _duel(hand=[card])
    _opponent_casts(game, threat)

    action = choose_combat_instant_cast_action(game, 0)

    assert action is not None and action.mode_index == 1
    result = game.queue_from_hand(0, card.name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    assert _names(game.players[1].graveyard) == ["Their Dragon"]
    assert game.players[1].battlefield == []
    assert game.players[0].life == 20, "countered, not five life gained"


def test_blue_elemental_blast_still_counters_a_red_spell(catalog_by_name):
    """Mode 0 in the window it was always cast in: weighing every mode must
    not cost the one that already worked."""
    goblin = _mk_card(
        name="Their Raider", mana_cost="", type_line="Creature - Goblin",
        colors=("R",), power=2, toughness=2,
    )
    card = catalog_by_name["Blue Elemental Blast"]
    game = _duel(hand=[card])
    _opponent_casts(game, goblin)

    action = choose_combat_instant_cast_action(game, 0)

    assert action is not None and action.mode_index == 0
    result = game.queue_from_hand(0, card.name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    assert _names(game.players[1].graveyard) == ["Their Raider"]


def test_a_blast_is_not_spent_on_a_spell_of_the_wrong_colour(catalog_by_name):
    """"Counter target spell **if it's blue**" may be announced at any spell
    (that is Pyroblast against Red Elemental Blast) and counters only a blue
    one. The priority response announced it at whatever was on top — before
    the mode chooser and after it."""
    card = catalog_by_name["Pyroblast"]
    raider = _mk_card(
        name="Their Raider", mana_cost="", type_line="Creature - Goblin",
        colors=("R",), power=2, toughness=2,
    )
    game = _duel(hand=[card])
    _opponent_casts(game, raider)
    assert 0 in game.announceable_modes(0, card), "a legal announcement all the same"

    assert choose_combat_instant_cast_action(game, 0) is None


def test_a_blast_names_the_spell_it_would_counter(catalog_by_name):
    """Two spells waiting, the blue one underneath: the cast names *it*
    (`CastAction.target_stack_index`), where a cast naming nothing is answered
    with the spell on top."""
    card = catalog_by_name["Pyroblast"]
    merfolk = _mk_card(
        name="Their Merfolk", mana_cost="", type_line="Creature - Merfolk",
        colors=("U",), power=1, toughness=1,
    )
    raider = _mk_card(
        name="Their Raider", mana_cost="", type_line="Creature - Goblin",
        colors=("R",), power=2, toughness=2,
    )
    game = _duel(hand=[card])
    _opponent_casts(game, merfolk)
    game.players[1].hand.append(raider)
    assert game.queue_from_hand(1, raider.name).supported
    assert [item.card.name for item in game.stack] == ["Their Merfolk", "Their Raider"]

    action = choose_combat_instant_cast_action(game, 0)

    assert action is not None and action.mode_index == 0
    assert action.target_stack_index == 0
    result = game.queue_from_hand(0, card.name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    assert _names(game.players[1].graveyard) == ["Their Merfolk"]
    assert _names(p.card for p in game.players[1].battlefield) == ["Their Raider"]


# --- The executors -----------------------------------------------------------------

#: `CastAction` fields that are not part of the announcement: which card and
#: where it is (the executor's `spell_being_cast` reads them), the score, and
#: the payment plan (`tap_planned_lands`).
_NOT_ANNOUNCED = {
    "card_name", "hand_index", "score", "land_tap_indices", "land_tap_colors",
}


def test_every_announcement_a_cast_action_carries_reaches_the_cast():
    """`cast_announcement` is the one place a `CastAction` becomes a cast, so
    a field added to the action is forwarded by every executor or is named
    above as not an announcement. The mode is the field that made this one
    function: dropped by an executor it is not refused, it is cast as the
    first bullet."""
    action = CastAction(
        card_name="Probe", target_player_index=1, x_value=3, land_tap_indices=(),
        score=1.0, hand_index=0, target_permanent_index=2, target_permanent_ids=[7],
        from_zone="command", alternative_cost=True, divided_targets=[(1, None, 3)],
        optional_cost_payments={"{1}{R}": 2}, mode_index=2,
        mode_choices=[{"index": 1}], target_stack_index=3,
    )
    announced = cast_announcement(action)

    carried = {field.name for field in fields(CastAction)} - _NOT_ANNOUNCED
    assert set(announced) == carried
    for name in carried:
        assert announced[name] == getattr(action, name), name


def test_the_executors_all_make_the_whole_announcement():
    """The simulator and the web layer's four cast sites call the engine with
    ``**cast_announcement(...)`` and spell out no target of their own — a
    keyword written at one site is a keyword missing from another."""
    root = Path(__file__).resolve().parents[2]
    found = 0
    for relative in ("engine/ai_simulator.py", "web/game_flow.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("cast_from_hand", "queue_from_hand")
            ):
                continue
            spelled = {keyword.arg for keyword in node.keywords if keyword.arg}
            splatted = [
                keyword.value for keyword in node.keywords if keyword.arg is None
            ]
            if spelled == {"target_player_index"} and not splatted:
                continue  # a land drop: a special action, no announcement
            found += 1
            assert not spelled, (relative, node.lineno, sorted(spelled))
            assert len(splatted) == 1 and isinstance(splatted[0], ast.Call), (
                relative, node.lineno,
            )
            assert getattr(splatted[0].func, "id", None) == "cast_announcement", (
                relative, node.lineno,
            )
    assert found == 5, f"expected the five AI cast sites, found {found}"


def test_the_simulator_casts_the_chosen_mode_and_counts_it(catalog_by_name):
    """The executor forwards the mode, the log names it, and the report
    counts it — every modal cast was mode 0 before, and the run read clean."""
    game = _duel(hand=[catalog_by_name["Crosis's Charm"]], theirs=[RELIC])
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )

    assert ai_simulator._play_one_cast(game, 0, report, 1, 1) is True

    assert _names(game.players[1].graveyard) == ["Their Relic"]
    assert report.modal_casts == Counter({2: 1})
    assert report.refused_casts == Counter() and report.issues == []
    assert report.log_lines == [
        "G1 T1 AI cast Crosis's Charm -> resolved [mode 2: Destroy target artifact]"
    ]


def test_a_spell_with_no_mode_logs_as_it_always_did(catalog_by_name):
    game = _duel(hand=[catalog_by_name["Shatter"]], theirs=[RELIC])
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )

    assert ai_simulator._play_one_cast(game, 0, report, 1, 1) is True

    assert report.log_lines == ["G1 T1 AI cast Shatter -> resolved"]
    assert report.modal_casts == Counter()


# --- The seam: no chooser can read mode 0 by leaving a keyword out ----------------

#: Engine questions about a cast that take the announced mode. A call to one
#: of them from `ai_policy` without ``mode_index=`` is asking about mode 0.
_MODE_QUESTIONS = {
    "derive_cast_spec", "cast_target_slot", "instructions_as_announced",
    "cast_target_spec", "no_legal_cast_target_refusal", "announced_cast_x",
    "cast_target_refusal", "cast_stack_target_refusal", "_enumerate_targets",
    "_validate_cast_targets",
}


def test_every_cast_question_the_policy_asks_names_the_mode():
    """The mode being weighed is one context variable read at two seams
    (`ai_valuation._spell_instructions`, `ai_policy._announced_mode`). This
    holds the second: every call in the policy to an engine question that
    takes a mode passes it. An ability's or an entry trigger's enumeration
    (``ability_instruction=``, ``for_cast=False``) has no mode to pass."""
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "engine" / "ai_policy.py").read_text(encoding="utf-8"))
    asked = 0
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in _MODE_QUESTIONS:
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        if "ability_instruction" in keywords:
            continue
        for_cast = keywords.get("for_cast")
        if name == "_enumerate_targets" and not (
            isinstance(for_cast, ast.Constant) and for_cast.value is True
        ):
            continue
        asked += 1
        if "mode_index" not in keywords:
            missing.append(f"engine/ai_policy.py:{node.lineno}: {name}(…) names no mode")
    assert not missing, "\n".join(missing)
    assert asked >= 12, f"the scan found only {asked} calls — it is reading nothing"


def test_the_policy_reads_a_spells_steps_through_the_mode_seam():
    """…and the first: nothing in the policy walks ``program.instructions``
    for itself, which for a modal card is mode 0's."""
    root = Path(__file__).resolve().parents[2]
    source = (root / "engine" / "ai_policy.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    reads = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "instructions"
        and isinstance(node.value, ast.Name) and node.value.id == "program"
    ]
    assert reads == [], f"program.instructions read at lines {reads}"


def _modal_population():
    seen = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        if card.name not in seen and caster_chooses_a_mode(card):
            if compile_card_oracle(card).supported:
                seen[card.name] = card
    return [seen[name] for name in sorted(seen)]


def test_the_valuation_readers_answer_for_the_mode_being_weighed():
    """Pool-wide: under ``considering_mode`` a card's side is the weighed
    bullet's own, and its text is that bullet's. Outside it, and for any other
    card, both read as they always did."""
    population = _modal_population()
    assert len(population) >= 34
    examined = differing = 0
    for card in population:
        program = compile_card_oracle(card)
        whole = (card.oracle_text or "").lower()
        assert spell_text(card) == whole and mode_considered(card) is None
        for index, mode in enumerate(program.modes):
            if mode.instruction is None:
                continue
            examined += 1
            with considering_mode(card, index):
                assert mode_considered(card) == index
                assert spell_text(card) == mode.label.lower()
                side = spell_target_side(card)
                # Another card is never read "in mode N" of this one.
                for other in population:
                    if other is not card:
                        assert mode_considered(other) is None
                        break
            targets = (mode.instruction.payload or {}).get("targets")
            if isinstance(targets, dict) and targets.get("kind") == "object":
                assert side == instruction_target_side(mode.instruction), (card.name, index)
            if side != spell_target_side(card):
                differing += 1
        assert mode_considered(card) is None
    assert examined >= 88
    assert differing >= 20, "the modes of a Charm do not all want one side"


# --- Whole games -------------------------------------------------------------------

_PLANESHIFT_MODAL = (
    "Crosis's Charm", "Darigaaz's Charm", "Dromar's Charm", "Rith's Charm",
    "Treva's Charm", "Hull Breach",
)


def _planeshift_games(games: int):
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    return run_ai_simulation(
        [manifest_set_path("PLS")], games=games, seed=1337, max_turns=24,
        required_cards=_PLANESHIFT_MODAL,
    )


@pytest.mark.slow
def test_whole_games_with_planeshifts_modal_spells_pinned():
    """The seeded Planeshift run deals two-colour decks, so its three-colour
    Charms are almost never cast and the run cannot show a mode. Pinned into
    both decks of six games they are cast in every position: 47 modes named,
    26 of them not the first bullet, none refused. (Floors well under what
    the seed gives, so another card's play does not move them.)"""
    report = _planeshift_games(6)

    assert report.games_completed == 6
    assert report.issues == [], [issue.message for issue in report.issues]
    assert not report.steps_left_owing, dict(report.steps_left_owing)
    refused = [
        key for key in report.refused_casts
        if key.split(":")[0] in _PLANESHIFT_MODAL
    ]
    assert refused == []
    later = sum(count for mode, count in report.modal_casts.items() if mode)
    assert sum(report.modal_casts.values()) >= 25, dict(report.modal_casts)
    assert later >= 10, dict(report.modal_casts)
    assert {1, 2} <= set(report.modal_casts), dict(report.modal_casts)
    named = [line for line in report.log_lines if " cast Hull Breach -> resolved" in line]
    assert any("[mode 2: " in line for line in named), named


@pytest.mark.slow
def test_a_seed_still_reproduces_a_run_in_which_modes_are_chosen():
    """Determinism: equal modes keep printed order and nothing in the choice
    iterates an unordered collection, so a seed is still a run."""
    first, second = _planeshift_games(2), _planeshift_games(2)

    assert first.log_lines == second.log_lines
    assert first.modal_casts == second.modal_casts
    assert sum(first.modal_casts.values()) >= 5
