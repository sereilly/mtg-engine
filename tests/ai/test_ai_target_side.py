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
