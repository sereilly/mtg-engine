"""Which board an AI aims a one-target spell or ability at, and whether it casts
a spell whose resolution would do nothing.

Measured at Nemesis' wave 1 and re-derived in wave 2: ``_score_spell_target``
is a handful of text probes, so every spell outside them scored the caster and
the opponent equally and the tie went to the caster. "Target creature can't
attack or block this turn" kept the AI's own creature home, Crumble destroyed
its own artifact, Shrink shrank its own attacker and Topple exiled its own
biggest creature. The side is now derived from the compiled program
(``ai_valuation.spell_target_side`` / ``instruction_target_side``), so most of
these tests use an *invented* card printing the template: a name-free
derivation answers it the same as the printed one.

The second half is "would this resolution do anything": a one-object spell
names its permanent out of the engine's enumeration on the side it wants, or
is not cast; a spell that has its caster sacrifice what the board lacks is not
cast.
"""
from __future__ import annotations

from engine.ai_policy import (
    _choose_target_for_spell,
    choose_activation_action,
    choose_cast_action,
    legal_attackers,
)
from engine.ai_valuation import instruction_target_side, spell_target_side
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, spec_roles
from tests.helpers import _mk_card, _mk_creature_card, _nosick, resolve_stack


def _duel(hand=(), mine=(), theirs=()):
    p1 = PlayerState(name="AI", hand=list(hand), battlefield=[_nosick(Permanent(card=c)) for c in mine])
    p2 = PlayerState(name="Opp", battlefield=[_nosick(Permanent(card=c)) for c in theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


def _instant(name, text):
    return _mk_card(name=name, mana_cost="{W}", type_line="Instant", oracle_text=text)


# --- Item 1: a restriction is aimed at the opponent's board --------------------


def test_a_cant_attack_or_block_spell_is_aimed_at_the_opponents_creature():
    spell = _instant("Sidestep Probe", "Target creature can't attack or block this turn.")
    assert compile_card_oracle(spell).supported
    mine = _mk_creature_card("Own Bear", 2, 2)
    theirs = _mk_creature_card("Their Bear", 2, 2)
    game = _duel(hand=[spell], mine=[mine], theirs=[theirs])

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Sidestep Probe"
    assert action.target_player_index == 1
    named = game.permanent_by_id(action.target_permanent_ids[0])
    assert named.card is theirs, "the restriction names the opponent's creature"
    result = game.cast_from_hand(
        0, action.card_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
    )
    assert result.supported, result.details
    resolve_stack(game)
    game.start_turn(0)
    assert legal_attackers(game, 0), "the AI's own creature can still attack"


def test_a_restriction_with_only_own_creatures_to_name_is_not_cast():
    spell = _instant("Sidestep Probe", "Target creature can't attack or block this turn.")
    game = _duel(hand=[spell], mine=[_mk_creature_card("Own Bear", 2, 2)])

    action = choose_cast_action(game, 0)

    assert action is None or action.card_name != "Sidestep Probe"


def test_a_shrink_is_aimed_at_the_opponent_and_a_pump_at_the_caster():
    shrink = _instant("Wither Probe", "Target creature gets -3/-0 until end of turn.")
    pump = _instant("Swell Probe", "Target creature gets +3/+3 until end of turn.")
    game = _duel(
        mine=[_mk_creature_card("Own Bear", 2, 2)],
        theirs=[_mk_creature_card("Their Bear", 2, 2)],
    )
    assert _choose_target_for_spell(shrink, 0, game) == 1
    assert _choose_target_for_spell(pump, 0, game) == 0


def test_a_destroy_inside_a_sequence_is_aimed_at_the_opponent():
    """``destroyed_permanent_filter`` reads a top-level destroy only, so a
    destroy behind a second sentence scored nothing and tied — Crumble destroyed
    the AI's own artifact."""
    spell = _instant(
        "Rust Probe",
        "Destroy target artifact. That artifact's controller gains 3 life.",
    )
    assert compile_card_oracle(spell).supported
    rock = _mk_card(name="Plain Rock", mana_cost="{1}", type_line="Artifact")
    game = _duel(hand=[spell], mine=[rock], theirs=[rock])

    action = choose_cast_action(game, 0)

    assert action is not None and action.target_player_index == 1
    game.cast_from_hand(
        0, action.card_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
    )
    resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Plain Rock"]
    assert [p.card.name for p in game.controlled_by(1)] == []


def test_a_printed_seat_on_the_target_outranks_the_effect():
    """"Target creature **you control**" names the side itself."""
    spell = _instant("Ward Probe", "Target creature you control can't be blocked this turn.")
    for instruction in compile_card_oracle(spell).instructions:
        assert instruction_target_side(instruction) == "you"
    assert spell_target_side(spell) == "you"


def test_every_single_target_denial_in_the_pool_is_aimed_at_the_opponent(catalog):
    """The pool-wide half. The oracle here is the test's own list of denial
    kinds, written independently of ``ai_valuation``'s tables, so the check
    is not the derivation asked about itself: a one-object spell whose every
    targeted step is one of these, on a board where both seats hold one of
    everything, must be aimed at the opponent.

    Validated backwards: on the tree before this change the same loop examined
    112 shipped spells and found the AI's own seat for 56 of them (Crumble,
    Exile, Erase, Last Breath, Disempower, Gravebind, Humble, Panic, …; a few,
    such as Dust to Dust, are several-target spells whose *permanents*
    ``_choose_several_targets`` already moved, but whose seat was still the
    caster's).
    """
    denials = {
        "destroy_target_permanent", "exile_target_permanent",
        "target_cant_attack_until_eot", "target_cant_block_until_eot",
        "tap_target_permanent", "gain_control_of_target",
        "put_target_on_library_top", "deny_regeneration_to_target",
        "remove_target_abilities_until_eot", "prevent_damage_by_target_until_eot",
    }
    by_name = {card.name: card for card in catalog}
    board = ["Grizzly Bears", "Ornithopter", "Howling Mine", "Forest", "Plains"]

    def walk(instructions):
        for instruction in instructions:
            yield instruction
            for key in ("steps", "then", "else", "action", "otherwise"):
                nested = (instruction.payload or {}).get(key)
                if isinstance(nested, (list, tuple)):
                    yield from walk(nested)

    examined, self_aimed = [], []
    for card in catalog:
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        spec = derive_cast_spec(card, program)
        if not program.supported or not isinstance(spec, dict):
            continue
        if spec.get("kind") in ("none", "modal", "player") or spec_roles(spec):
            continue
        targeted = [
            step for step in walk(program.instructions)
            if ((step.payload or {}).get("targets") or {}).get("kind") == "object"
        ]
        if not targeted or any(step.kind not in denials for step in targeted):
            continue
        if any(
            ((step.payload.get("targets") or {}).get("filter") or {}).get("controller")
            for step in targeted
        ):
            continue
        game = _duel(
            mine=[by_name[n] for n in board], theirs=[by_name[n] for n in board],
        )
        examined.append(card.name)
        if _choose_target_for_spell(card, 0, game) != 1:
            self_aimed.append(card.name)
    assert not self_aimed, self_aimed
    assert len(examined) >= 100, len(examined)


def test_every_kind_the_side_tables_name_is_one_something_dispatches():
    """The tables are keyed by instruction kind, so a rename empties them in
    silence and every card printing that template goes back to the tie — the
    way ``MANA_ABILITY_KINDS`` once named two kinds that no longer existed."""
    import engine.ai_valuation as valuation
    from engine.handlers import EFFECT_HANDLERS

    named = (
        valuation._OWN_KINDS | valuation._OPPONENT_KINDS
        | valuation._NO_SIDE_KINDS | valuation._PT_DELTA_KINDS
    )
    missing = sorted(named - set(EFFECT_HANDLERS))
    assert not missing, missing


# --- Item 2: a spell whose resolution would do nothing ------------------------


def test_topple_is_not_cast_when_the_greatest_creature_is_the_casters(set_pool):
    nem = set_pool("NEM")
    big, small = _mk_creature_card("Big", 4, 4), _mk_creature_card("Small", 2, 2)

    game = _duel(hand=[nem["Topple"]], mine=[big], theirs=[small])
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Topple"

    game = _duel(hand=[nem["Topple"]], mine=[small], theirs=[big])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Topple"
    game.cast_from_hand(
        0, "Topple", target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
    )
    resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Big"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Small"]


def test_sivvis_valor_names_the_creature_it_spares(set_pool):
    """A redirect off a target has no board scan to fall into: cast naming only
    a seat, it resolved "its target is gone"."""
    nem = set_pool("NEM")
    mine = _mk_creature_card("Own Bear", 2, 2)
    game = _duel(hand=[nem["Sivvi's Valor"]], mine=[mine], theirs=[_mk_creature_card("Foe", 3, 3)])

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Sivvi's Valor"
    assert action.target_player_index == 0
    assert game.permanent_by_id(action.target_permanent_ids[0]).card is mine
    game.cast_from_hand(
        0, action.card_name, target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
    )
    resolve_stack(game)
    assert any("dealt to AI instead" in line for line in game.log), game.log[-4:]
    assert not any("its target is gone" in line for line in game.log)


def test_rupture_is_not_cast_with_nothing_to_sacrifice(set_pool):
    nem = set_pool("NEM")
    game = _duel(hand=[nem["Rupture"]], theirs=[_mk_creature_card("Foe", 3, 3)])
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Rupture"

    game = _duel(hand=[nem["Rupture"]], mine=[_mk_creature_card("Fodder", 3, 3)])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Rupture"


def test_an_any_number_sacrifice_spell_is_not_cast_by_a_seat_that_gives_up_none():
    """"Sacrifice any number of permanents. You gain 2 life for each permanent
    sacrificed this way." A seat nobody asks sacrifices none (the stated policy
    in ``_resolve_sacrifice_inline``), so the spell would resolve for zero —
    measured at MMQ, where Renounce did exactly that."""
    spell = _mk_card(
        name="Offering Probe", mana_cost="{1}{W}", type_line="Sorcery",
        oracle_text="Sacrifice any number of permanents. You gain 2 life for each permanent sacrificed this way.",
    )
    assert compile_card_oracle(spell).supported
    game = _duel(hand=[spell], mine=[_mk_creature_card("Fodder", 1, 1)])
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Offering Probe"


# --- The activation side of item 1 --------------------------------------------


def _activator(text):
    card = _mk_card(
        name="Stunner Probe", mana_cost="{1}", type_line="Creature — Wizard",
        oracle_text=text,
    )
    assert compile_card_oracle(card).supported, text
    return card


def test_an_activated_restriction_never_falls_back_to_the_activators_own_creature():
    """The chooser used to keep the wanted side "or any legal permanent" — so a
    "can't block" with no opposing creature landed on its own."""
    stunner = _activator("{T}: Target creature can't block this turn.")
    game = _duel(mine=[stunner, _mk_creature_card("Own Bear", 2, 2)])
    action = choose_activation_action(game, 0)
    assert action is None, action

    theirs = _mk_creature_card("Their Bear", 2, 2)
    game = _duel(mine=[stunner, _mk_creature_card("Own Bear", 2, 2)], theirs=[theirs])
    action = choose_activation_action(game, 0)
    assert action is not None and action.target_player_index == 1
    assert game.permanent_at(1, action.target_permanent_index).card is theirs


def test_a_denial_its_own_words_aim_at_the_activator_is_not_activated():
    """"{B}: Destroy target artifact, creature, or land you control." (Rats of
    Rath's template.) The chooser found the only legal target — its own — and
    destroyed it, because the wanted side fell back to "any legal permanent"."""
    rats = _activator("{B}: Destroy target artifact, creature, or land you control.")
    game = _duel(
        mine=[rats, _mk_creature_card("Own Bear", 2, 2)],
        theirs=[_mk_creature_card("Their Bear", 2, 2)],
    )
    assert choose_activation_action(game, 0) is None


def test_the_simulator_counts_a_refused_activation(monkeypatch):
    """``SimulationReport.refused_activations``: the activation-side twin of
    ``refused_casts``, wired by having every proposed activation refused.
    Before it existed the 80 refusals NEM's wave 2 found were visible only by
    reading the log."""
    import engine.ai_simulator as simulator
    from engine.ai_policy import ActivationAction
    from engine.card_loader import manifest_set_path
    from engine.game_types import SimulationResult

    def propose(game, seat):
        return ActivationAction(
            permanent_name="Probe Engine", permanent_index=0,
            target_player_index=seat, land_tap_indices=(), score=1.0,
        )

    def refuse(self, *args, **kwargs):
        return SimulationResult("Probe Engine", False, "unsupported", "refused for the test")

    monkeypatch.setattr(simulator, "choose_activation_action", propose)
    monkeypatch.setattr(simulator.Game, "activate_permanent_ability", refuse)
    report = simulator.run_ai_simulation(
        manifest_set_path("LEA"), games=1, seed=7, max_turns=2,
    )
    assert report.refused_activations == {
        "Probe Engine: refused for the test": 4
    }, report.refused_activations


def test_an_activation_with_no_legal_graveyard_target_is_not_proposed(set_pool):
    """"{1}{G}: Return target basic land card from your graveyard to your hand"
    (Groundskeeper) with an empty graveyard: refused by the engine with nothing
    paid, and proposed again every turn — 15 refusals in one MMQ run."""
    keeper = set_pool("MMQ")["Groundskeeper"]
    game = _duel(mine=[keeper])
    assert choose_activation_action(game, 0) is None


def test_a_drain_is_aimed_at_the_opponent_not_the_caster(set_pool):
    """"Target player loses 4 life and you gain 4 life." (Soul Feast.) The
    score's "gain … life" probe preferred the caster and nothing read the
    *loss*, so the AI drained itself: a wash on its own life total and a card
    spent. The loss is read off the compiled program, wrappers opened — Rhystic
    Syphon's sits on a toll's declined branch — and an invented card printing
    the template answers the same way."""
    invented = _mk_card(
        "Invented Drain", "{3}{B}", "Sorcery",
        "Target player loses 3 life and you gain 3 life.",
    )
    for card in (
        set_pool("UDS")["Soul Feast"], set_pool("PCY")["Rhystic Syphon"], invented,
    ):
        game = Game(players=[PlayerState(name="AI", life=12), PlayerState(name="Opp")])
        assert _choose_target_for_spell(card, 0, game) == 1, card.name


def test_a_loss_that_pays_for_a_draw_keeps_the_draw_probes_answer(set_pool):
    """Peer into the Abyss: the target also *draws*, so the life loss is the
    price of the cards and the draw probe still decides — the caster."""
    game = Game(players=[PlayerState(name="AI", life=12), PlayerState(name="Opp")])
    assert _choose_target_for_spell(set_pool("M21")["Peer into the Abyss"], 0, game) == 0


# --- W3G4: an own-seat ability is aimed by the step that targets ---------------
#
# `choose_activation_action` asked `instruction_target_side` of the top-level
# instruction, and a ``sequence`` / ``may`` wrapper has no side — so a two-step
# ability fell back to "the biggest creature on either board". W2G3 measured 87
# such abilities statically; driven, with a creature of each size on each board,
# 47 shipped abilities were aimed at the wrong seat on one board or the other.

import re as _w3g4_re

from engine.ai_simulator import SimulationReport as _W3g4Report
from engine.ai_simulator import _play_activations as _w3g4_play_activations
from engine.ai_simulator import _play_one_cast as _w3g4_play_one_cast
from engine.ai_valuation import source_becomes_an_aura as _w3g4_becomes_aura
from engine.handlers._common import attached_host as _w3g4_attached_host
from engine.mixins.stack import aura_enchant_noun as _w3g4_enchant_noun
from engine.named_counters import add_counters as _w3g4_add_counters
from engine.targeting import derive_activation_spec as _w3g4_activation_spec
from engine.targeting import usable_activated_abilities as _w3g4_usable


def _w3g4_board(mine=(), theirs=(), hand=()):
    """A main phase of the AI's, costs enforced, nothing summoning sick."""
    game = Game(players=[PlayerState(name="AI", hand=list(hand)), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for seat, group in ((0, mine), (1, theirs)):
        for card in group:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game


def _w3g4_report():
    return _W3g4Report(games_requested=1, games_completed=0, interaction_count=0)


def _w3g4_on_board(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def test_bullwhip_pings_the_opponents_creature_not_the_biggest_on_either_board(set_pool):
    """"{2}, {T}: This artifact deals 1 damage to target creature. That creature
    attacks this turn if able." — a damage step and a forced attack, so a
    ``sequence``. Read as one instruction it had no side, and the AI's own
    Craw Wurm, the biggest creature on either board, took the damage. Driven
    through the simulator's own executor, which pays the {2} from the lands."""
    lea = set_pool("LEA")
    game = _w3g4_board(
        mine=[set_pool("STH")["Bullwhip"], lea["Craw Wurm"], lea["Mountain"], lea["Mountain"]],
        theirs=[_mk_creature_card("Their Squire", 1, 1)],
    )
    report = _w3g4_report()

    _w3g4_play_activations(game, 0, report, 1, 1)

    assert report.log_lines == ["G1 T1 AI activate Bullwhip -> resolved"], report.log_lines
    assert [card.name for card in game.players[1].graveyard] == ["Their Squire"]
    assert _w3g4_on_board(game, "Craw Wurm").damage_marked == 0
    assert all(p.tapped for p in game.controlled_by(0) if p.card.name == "Mountain")


def test_power_matrix_pumps_the_ais_own_creature(set_pool):
    """"{T}: Target creature gets +1/+1 and gains flying, first strike, and
    trample until end of turn." — a pump and a grant. The fallback gave them
    to the opponent's Craw Wurm."""
    game = _w3g4_board(
        mine=[set_pool("MMQ")["Power Matrix"], _mk_creature_card("Own Bear", 2, 2)],
        theirs=[set_pool("LEA")["Craw Wurm"]],
    )

    _w3g4_play_activations(game, 0, _w3g4_report(), 1, 1)

    bear, wurm = _w3g4_on_board(game, "Own Bear"), _w3g4_on_board(game, "Craw Wurm")
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    assert game._has_keyword(bear, "flying") and game._has_keyword(bear, "trample")
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)
    assert not game._has_keyword(wurm, "flying")


def test_a_licid_is_attached_where_its_aura_belongs(set_pool):
    """"This creature loses this ability and becomes an Aura enchantment with
    enchant creature. Attach it to target creature." The attach step reads
    "you" for an Equipment's reason, so the Licid is aimed as the Aura it
    becomes would be cast: Calming Licid's "can't attack" on the opponent's
    creature, Gliding Licid's flying on the AI's own — each against a board
    whose biggest creature is on the other side."""
    lea, sth = set_pool("LEA"), set_pool("STH")
    calming = _w3g4_board(
        mine=[sth["Calming Licid"], lea["Plains"], lea["Craw Wurm"]],
        theirs=[_mk_creature_card("Their Squire", 1, 1)],
    )
    gliding = _w3g4_board(
        mine=[sth["Gliding Licid"], lea["Island"], _mk_creature_card("Own Bear", 2, 2)],
        theirs=[lea["Craw Wurm"]],
    )
    for game, licid, wanted in (
        (calming, "Calming Licid", ("Their Squire", 1)),
        (gliding, "Gliding Licid", ("Own Bear", 0)),
    ):
        _w3g4_play_activations(game, 0, _w3g4_report(), 1, 1)
        host = _w3g4_attached_host(game, _w3g4_on_board(game, licid))
        assert host is not None, licid
        assert (host.card.name, game.controller_index_of(host)) == wanted, licid
    assert not legal_attackers(calming, 1), "the enchanted creature can still attack"


def test_an_x_cost_ability_is_not_proposed_and_a_defined_x_does_not_crash(set_pool):
    """Two shapes the score below the side read used to ``int("x")`` on:
    Crimson Hellkite's "{X}, {T}: … X damage" (the chooser announces no X, so
    it is a tap for nothing and is not proposed), and Torture Chamber's
    "…damage equal to the number of pain counters removed this way" (a
    defined X, scored at the floor and aimed at the opponent). Either one,
    untapped in a main phase, raised out of the chooser and killed the run."""
    lea = set_pool("LEA")
    hellkite = _w3g4_board(
        mine=[set_pool("MIR")["Crimson Hellkite"]] + [lea["Mountain"]] * 4,
        theirs=[_mk_creature_card("Their Bear", 2, 2)],
    )
    assert choose_activation_action(hellkite, 0) is None

    chamber = _w3g4_board(
        mine=[set_pool("TMP")["Torture Chamber"], lea["Mountain"]],
        theirs=[_mk_creature_card("Their Bear", 2, 2)],
    )
    _w3g4_add_counters(_w3g4_on_board(chamber, "Torture Chamber"), "pain", 2)
    _w3g4_play_activations(chamber, 0, _w3g4_report(), 1, 1)
    assert [card.name for card in chamber.players[1].graveyard] == ["Their Bear"]


#: The Licids whose Aura text, read by a person, is a cost to the enchanted
#: creature or its controller — the rest grant a keyword or a regeneration.
_W3G4_HARMFUL_LICIDS = frozenset({
    "Calming Licid", "Convulsing Licid", "Dominating Licid",
    "Leeching Licid", "Stinging Licid",
})


def _w3g4_step_side(instruction):
    """The side the targeting steps state, read here independently of the
    policy: each step's own leaf reading, a denial winning."""
    steps, stack = [], [instruction]
    while stack:
        item = stack.pop()
        nested = [
            child for key in ("steps", "then", "else", "action", "otherwise", "effect")
            for child in ((item.payload or {}).get(key) or ())
            if hasattr(child, "kind")
        ]
        if nested:
            stack.extend(nested)
        elif isinstance((item.payload or {}).get("targets"), dict):
            steps.append(item)
    sides = {instruction_target_side(step) for step in steps} - {None}
    return "opponent" if "opponent" in sides else "you" if "you" in sides else None


def test_no_wrapped_own_ability_in_the_pool_is_aimed_at_the_wrong_seat(catalog, set_pool):
    """Pool-wide, both manifest roles: every card whose first usable ability
    names an object target through a wrapper, on the AI's board twice — once
    with the opponent holding the biggest creature, once with the AI — must be
    aimed at the seat its targeting steps state (a Licid at the seat its Aura
    belongs on). Validated backwards: on the tree before this change the same
    walk named 47 shipped abilities aimed at the wrong seat (Bullwhip,
    Serrated Biskelion, Power Matrix, Wishmonger, every Licid, …).
    """
    cards = {card.name: card for card in catalog}
    cards.update(set_pool("PCY"))
    lea = set_pool("LEA")
    small, big = lea["Grizzly Bears"], lea["Craw Wurm"]
    small_artifact = set_pool("ATQ")["Ornithopter"]
    examined, proposed, wrong = [], 0, []
    for name, card in sorted(cards.items()):
        if card.primary_type in ("instant", "sorcery", "land") or "Aura" in (card.type_line or ""):
            continue
        usable = _w3g4_usable(compile_card_oracle(card))
        if not usable or usable[0].instruction is None:
            continue
        ability = usable[0]
        spec = _w3g4_activation_spec(ability) or {}
        if spec.get("kind") not in {"creature", "artifact", "land", "permanent"}:
            continue
        if spec.get("sacrifice_cost") or spec.get("discard_cost"):
            continue
        if instruction_target_side(ability.instruction) is not None:
            continue  # not wrapped: the reading this fixed never applied
        if _w3g4_becomes_aura(ability.instruction):
            side = "opponent" if name in _W3G4_HARMFUL_LICIDS else "you"
        else:
            side = _w3g4_step_side(ability.instruction)
        if side is None:
            continue
        examined.append(name)
        for own_big in (False, True):
            game = _w3g4_board(
                mine=[card, big if own_big else small, small_artifact],
                theirs=[small if own_big else big, small_artifact],
            )
            game.enforce_mana_costs = False
            action = choose_activation_action(game, 0)
            if action is None or action.permanent_name != name or action.target_permanent_index is None:
                continue
            proposed += 1
            if action.target_player_index != (0 if side == "you" else 1):
                wrong.append((name, side, "own biggest" if own_big else "opponent's biggest"))

    assert len(examined) >= 60, examined
    assert proposed >= 60, proposed
    assert {"Bullwhip", "Power Matrix", "Wishmonger", "Calming Licid"} <= set(examined)
    assert wrong == [], wrong


#: A person's reading of an Aura whose effect is a price charged to its host's
#: controller — written here, not imported, so the policy's markers are not
#: checked against themselves.
_W3G4_PRICE_TO_HOSTS_CONTROLLER = _w3g4_re.compile(
    r"deals? (?:\d+|x|that much) damage to (?:that player|that \w+'s controller)"
    r"|(?:that player|its controller) loses (?:\d+ )?life"
)


def test_an_aura_that_charges_its_hosts_controller_is_cast_on_an_opponent(catalog, set_pool):
    """"At the beginning of the upkeep of enchanted creature's controller, this
    Aura deals 1 damage to that player." (Wanderlust.) None of the AI's harmful
    markers read a damage clause, so it cast every Aura of this shape on its
    **own** permanent and took the damage itself each upkeep. Pool-wide, with
    a host of every kind on both boards; validated backwards: 21 of the 22
    examined went on the caster's own permanent before this change."""
    cards = {card.name: card for card in catalog}
    cards.update(set_pool("PCY"))
    hosts = [cards[name] for name in ("Grizzly Bears", "Mountain", "Ornithopter", "Castle")]
    examined, cast, wrong = [], 0, []
    for name, card in sorted(cards.items()):
        if _w3g4_enchant_noun(card) is None or not compile_card_oracle(card).supported:
            continue
        if not _W3G4_PRICE_TO_HOSTS_CONTROLLER.search((card.oracle_text or "").lower()):
            continue
        examined.append(name)
        game = _w3g4_board(mine=hosts, theirs=hosts, hand=[card])
        game.enforce_mana_costs = False
        action = choose_cast_action(game, 0)
        if action is None:
            continue
        cast += 1
        if action.target_player_index != 1:
            wrong.append(name)

    assert len(examined) >= 20, examined
    assert cast >= 18, cast
    assert {"Wanderlust", "Psychic Venom", "Warp Artifact"} <= set(examined)
    assert wrong == [], wrong


def test_wanderlust_cast_by_the_simulator_hurts_the_opponent_at_their_upkeep(set_pool):
    """The Rock Hydra test for the reading above: cast through the simulator's
    executor (paid from three Forests), then the opponent's upkeep."""
    lea = set_pool("LEA")
    game = _w3g4_board(
        mine=[lea["Forest"]] * 3 + [_mk_creature_card("Own Bear", 2, 2)],
        theirs=[_mk_creature_card("Their Bear", 2, 2)],
        hand=[lea["Wanderlust"]],
    )
    assert _w3g4_play_one_cast(game, 0, _w3g4_report(), 1, 1)
    host = _w3g4_attached_host(game, _w3g4_on_board(game, "Wanderlust"))
    assert (host.card.name, game.controller_index_of(host)) == ("Their Bear", 1)

    game.turn = 6
    game.begin_turn_bookkeeping(1)
    game.resolve_untap_step(1)
    game.resolve_upkeep(1)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert (game.players[0].life, game.players[1].life) == (20, 19)
