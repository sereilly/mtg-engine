"""The instant-speed cast chooser builds its casts with the main phase's
builder (kg5 ``aicast``).

``ai_policy.choose_combat_instant_cast_action`` — the answer the simulator and
the web AI seat give to priority in a response, in combat and at another
seat's end step — had a builder of its own (``_combat_instant_candidate``), a
thinner copy of ``ai_casts._announced_candidate``: it planned without
``_paying_for``, built no optional or alternative cost, no life-X size, no
second target, no X fixed by its target, never looked in the command zone,
and lacked the printed-timing, additional-cost, last-life-point and entry
give-back gates. It now asks ``ai_casts._priced_candidate(speed="instant")``,
and the speed changes only how the finished cast is read
(``ai_scoring.read_at_instant_speed``, ``held_at_instant_speed``,
``ai_cast_score.kept_above_the_floor``).

Each board below is driven through the real chooser and its executor
(``cast_chosen_instant``) and read off the board afterwards. On the base tree
(59f133e63) every one of them but the flash Aura cast nothing, or cast the
lesser spell — the Aura's host was named the same by the old builder's
one-object chooser, and is held here as the drive the round asked for.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine.ai_cast_explain import explain_cast
from engine.ai_policy import (
    cast_chosen_instant,
    choose_combat_instant_cast_action,
    holds_an_instant_it_could_pay_for,
)
from engine.commander import COMMANDER
from engine.models import Permanent
from tests.helpers import _nosick, declare_attack, drive_combat, settle

ME, OPP = 0, 1
ROOT = Path(__file__).resolve().parents[2]


def _table(by_name, hand=(), mine=(), theirs=(), *, life=20, opp_life=20, variant=None):
    """Two seats, mana enforced, the permanents untapped and not sick."""
    kwargs = {"commander_variant": variant} if variant is not None else {}
    game = Game(players=[
        PlayerState("A", hand=[by_name[name] for name in hand],
                    library=[by_name["Island"]] * 10),
        PlayerState("B", library=[by_name["Forest"]] * 10),
    ], **kwargs)
    game.enforce_mana_costs = True
    for seat, names in ((ME, mine), (OPP, theirs)):
        for name in names:
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game.players[ME].life = life
    game.players[OPP].life = opp_life
    game.turn = 3
    game._sync_control()
    return game


def _opponents_end_step(game):
    game.active_player_index = OPP
    game._set_phase_and_step("ending", "end")


def _opponent_casts(game, by_name, name):
    """The opponent's spell on the stack in its own main phase, paid from a
    pool handed to it for the purpose."""
    game.active_player_index = OPP
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.players[OPP].hand.append(by_name[name])
    for symbol in "WUBRGC":
        game.players[OPP].mana_pool[symbol] = 9
    result = game.queue_from_hand(OPP, name)
    game.players[OPP].mana_pool.clear()
    assert result.supported, result.details


def _cast_what_it_chooses(game):
    action = choose_combat_instant_cast_action(game, ME)
    assert action is not None, "the instant-speed chooser cast nothing"
    _card, result = cast_chosen_instant(game, ME, action)
    assert result.supported, result.details
    return action


def _names(cards):
    return sorted(card.name for card in cards)


def _on(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


def test_force_of_will_is_cast_by_its_alternative_cost_in_response(catalog_by_name):
    """No Island untapped: Force of Will is weighed by its alternative cost
    (CR 118.9) — a blue card exiled and a life paid — and the Serra Angel it
    answers never arrives. The cheap pre-question says so too."""
    game = _table(catalog_by_name, ["Force of Will", "Brainstorm"])
    _opponent_casts(game, catalog_by_name, "Serra Angel")
    assert holds_an_instant_it_could_pay_for(game, ME)

    action = _cast_what_it_chooses(game)
    settle(game)

    assert action.alternative_cost and not action.land_tap_indices
    assert _on(game, OPP, "Serra Angel") is None
    assert "Serra Angel" in _names(game.players[OPP].graveyard)
    assert _names(game.players[ME].graveyard) == ["Force of Will"]
    assert _names(game.players[ME].exile) == ["Brainstorm"]
    assert game.players[ME].life == 19


def test_a_kicked_instant_saves_the_blocker_in_the_declare_blockers_step(catalog_by_name):
    """Explosive Growth on a Grizzly Bears blocking a Craw Wurm: unkicked
    (+2/+2) the Bears trade, kicked (+5/+5, CR 702.33) they live. Seven
    Forests pay the kicker, and the kicked cast is the one made."""
    game = _table(catalog_by_name, ["Explosive Growth"],
                  ["Grizzly Bears"] + ["Forest"] * 7, ["Craw Wurm"])
    declare_attack(game, OPP, blocks={0: 0})

    action = _cast_what_it_chooses(game)
    settle(game)
    drive_combat(game, through="combat_damage")

    assert action.optional_cost_payments == {"{5}": 1}
    assert _on(game, ME, "Grizzly Bears") is not None
    assert _on(game, OPP, "Craw Wurm") is None
    assert "Craw Wurm" in _names(game.players[OPP].graveyard)


def test_an_instant_with_two_targets_names_both(catalog_by_name):
    """"Destroy two target nonblack creatures" at the opponent's end step:
    both are named (CR 601.2c), both die, and the caster pays its 5 life.
    The old builder asked the one-object question and held the card."""
    game = _table(catalog_by_name, ["Reckless Spite"], ["Swamp"] * 3,
                  ["Grizzly Bears", "Hill Giant"])
    _opponents_end_step(game)

    _cast_what_it_chooses(game)
    settle(game)

    assert _on(game, OPP, "Grizzly Bears") is None
    assert _on(game, OPP, "Hill Giant") is None
    assert game.players[ME].life == 15


def test_a_flash_aura_goes_onto_the_blocker_in_combat(catalog_by_name):
    """Armor of Thorns, cast as though it had flash, on the Grizzly Bears
    blocking a Hill Giant: a 4/4 kills the Giant and lives."""
    game = _table(catalog_by_name, ["Armor of Thorns"],
                  ["Grizzly Bears", "Forest", "Forest"], ["Hill Giant"])
    declare_attack(game, OPP, blocks={0: 0})

    _cast_what_it_chooses(game)
    settle(game)
    bears = _on(game, ME, "Grizzly Bears")
    armor = _on(game, ME, "Armor of Thorns")
    assert armor is not None and armor.metadata.get("attached_to") is bears
    drive_combat(game, through="combat_damage")

    assert _on(game, ME, "Grizzly Bears") is bears
    assert _on(game, OPP, "Hill Giant") is None


def test_an_instant_is_paid_for_by_a_sacrifice_for_mana_source(catalog_by_name):
    """Lotus Petal and no land: the plan is told what it pays for
    (``ai_payment._paying_for``), so the Petal counts toward a Lightning Bolt
    at the opponent's end step and is sacrificed to cast it."""
    game = _table(catalog_by_name, ["Lightning Bolt"], ["Lotus Petal"], ["Grizzly Bears"])
    _opponents_end_step(game)
    assert holds_an_instant_it_could_pay_for(game, ME)

    _cast_what_it_chooses(game)
    settle(game)

    assert _on(game, OPP, "Grizzly Bears") is None
    assert _on(game, ME, "Lotus Petal") is None
    assert _names(game.players[ME].graveyard) == ["Lightning Bolt", "Lotus Petal"]


def test_mishras_workshop_pays_for_a_flash_artifact(catalog_by_name):
    """"Spend this mana only to cast artifact spells" (CR 106.6): the
    Workshop's mana pays for Leonin Bladetrap, flashed in at the opponent's
    end step, once the plan knows the spell it is for."""
    game = _table(catalog_by_name, ["Leonin Bladetrap"], ["Mishra's Workshop"])
    _opponents_end_step(game)
    assert holds_an_instant_it_could_pay_for(game, ME)

    _cast_what_it_chooses(game)
    settle(game)

    assert _on(game, ME, "Leonin Bladetrap") is not None
    assert _on(game, ME, "Mishra's Workshop").tapped


def test_fling_names_the_creature_it_is_about_to_lose(catalog_by_name):
    """A Terror at this seat's Hill Giant, answered with Fling: the
    sacrifice that pays for it is named (``ai_casts._cast_naming_its_sacrifice``)
    — the doomed Giant, whose 3 power is the damage, not the engine's default
    (the smallest power first: the Llanowar Elves, 1 damage and a creature
    lost besides). The Terror has nothing left to destroy."""
    game = _table(catalog_by_name, ["Fling"],
                  ["Hill Giant", "Llanowar Elves", "Mountain", "Mountain"], ["Hill Giant"])
    giant = _on(game, ME, "Hill Giant")
    game.active_player_index = OPP
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.players[OPP].hand.append(catalog_by_name["Terror"])
    game.players[OPP].mana_pool.update({"B": 2})
    result = game.queue_from_hand(
        OPP, "Terror", target_player_index=ME, target_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details

    action = _cast_what_it_chooses(game)
    settle(game)

    assert action.cost_permanent_ids == [giant.permanent_id]
    assert _on(game, ME, "Llanowar Elves") is not None
    assert _names(game.players[ME].graveyard) == ["Fling", "Hill Giant"]
    assert "Terror" in _names(game.players[OPP].graveyard)
    assert game.players[OPP].life == 17 or _on(game, OPP, "Hill Giant") is None


def test_the_x_a_target_fixes_is_announced(catalog_by_name):
    """Spell Blast at a Grizzly Bears: "with mana value X" makes X 2, not the
    most five Islands pay (which the cast gate refuses)."""
    game = _table(catalog_by_name, ["Spell Blast"], ["Island"] * 5)
    _opponent_casts(game, catalog_by_name, "Grizzly Bears")

    action = _cast_what_it_chooses(game)
    settle(game)

    assert action.x_value == 2
    assert _on(game, OPP, "Grizzly Bears") is None
    assert "Grizzly Bears" in _names(game.players[OPP].graveyard)
    assert sum(1 for p in game.controlled_by(ME) if p.tapped) == 3


def test_a_kicked_counterspell_reaches_a_four_drop(catalog_by_name):
    """Prohibit counters a spell of mana value 2 or less, 4 or less if kicked:
    against a Hill Giant only the kicked cast does anything, and it is made."""
    game = _table(catalog_by_name, ["Prohibit"], ["Island"] * 4)
    _opponent_casts(game, catalog_by_name, "Hill Giant")

    action = _cast_what_it_chooses(game)
    settle(game)

    assert action.optional_cost_payments == {"{2}": 1}
    assert _on(game, OPP, "Hill Giant") is None
    assert "Hill Giant" in _names(game.players[OPP].graveyard)


def test_a_buyback_at_an_end_step_spends_no_mana_a_sorcery_wants(catalog_by_name):
    """Capsize at the opponent's end step beside a Time Walk: the sorcery
    cannot be cast now and the Islands untap before it can, so the buyback is
    spare and the Capsize comes back to hand."""
    game = _table(catalog_by_name, ["Capsize", "Time Walk"], ["Island"] * 6, ["Serra Angel"])
    _opponents_end_step(game)

    action = _cast_what_it_chooses(game)
    settle(game)

    assert action.optional_cost_payments == {"{3}": 1}
    assert _on(game, OPP, "Serra Angel") is None
    assert "Serra Angel" in _names(game.players[OPP].hand)
    assert _names(game.players[ME].hand) == ["Capsize", "Time Walk"]


def test_a_flash_commander_is_cast_from_the_command_zone(catalog_by_name):
    """CR 903.8 at instant speed: Niambi, Esteemed Speaker has flash, and the
    instant-speed chooser walks the command zone as the main phase's does."""
    game = _table(catalog_by_name, (), ["Plains", "Island"], variant=COMMANDER)
    niambi = catalog_by_name["Niambi, Esteemed Speaker"]
    game.designate_commander(ME, niambi)
    game.players[ME].command_zone.append(niambi)
    _opponents_end_step(game)

    action = _cast_what_it_chooses(game)
    settle(game)

    assert action.from_zone == "command"
    assert _on(game, ME, "Niambi, Esteemed Speaker") is not None
    assert game.players[ME].command_zone == []


@pytest.mark.parametrize("hand, mine, life, stack, gate", [
    (["Berserk"], ["Grizzly Bears", "Forest"], 20, None, "printed timing"),
    (["Fling"], ["Mountain", "Mountain"], 20, None, "additional cost cannot be paid"),
    (["Fleetfoot Panther"], ["Forest", "Plains", "Plains"], 20, None, "gives back more"),
    (["Withering Boon"], ["Swamp", "Swamp"], 3, "Serra Angel", "last point"),
])
def test_the_main_builders_gates_answer_at_instant_speed(
    catalog_by_name, hand, mine, life, stack, gate,
):
    """Each gate the main builder asks before it rehearses now answers at
    instant speed too, by its own reason — on the base each card was weighed
    to a rehearsal the engine refused or that ended its caster's game."""
    game = _table(catalog_by_name, hand, mine, ["Hill Giant"], life=life)
    if stack is None:
        _opponents_end_step(game)
    else:
        _opponent_casts(game, catalog_by_name, stack)

    explanation = explain_cast(game, ME, catalog_by_name[hand[0]], speed="instant")

    assert explanation.decision is None
    (candidate,) = explanation.candidates
    assert candidate.rehearsal is None
    assert gate in (candidate.dropped or ""), candidate.dropped


def test_the_instant_speed_chooser_builds_no_cast_of_its_own():
    """``ai_policy`` builds no ``CastAction`` and asks no rehearsal: its
    instant-speed chooser hands every offer to ``ai_casts._priced_candidate``
    at ``speed="instant"``, the builder the main phase asks. A second builder
    is how this one came to lack every variant the first one had."""
    tree = ast.parse((ROOT / "engine" / "ai_policy.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    named = {getattr(call.func, "id", None) or getattr(call.func, "attr", None) for call in calls}
    assert "CastAction" not in named
    assert "_rehearse_announcement" not in named
    chooser = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "choose_combat_instant_cast_action"
    )
    asked = [
        call for call in ast.walk(chooser)
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_priced_candidate"
    ]
    assert asked and all(
        any(k.arg == "speed" and getattr(k.value, "value", None) == "instant" for k in call.keywords)
        for call in asked
    )
