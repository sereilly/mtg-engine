"""Activations with nothing to gain, and a grant aimed at the wrong board.

* Riptide Mangler ("{1}{U}: This creature's base power becomes equal to target
  creature's power"): the AI re-activated it every main phase at 1 -> 1 (W1G7's
  seeded run), and copied its own biggest creature rather than an opponent's
  greater one. The rewrite is rehearsed (``ai_abilities._sets_only_what_its_
  source_is``) and has no side (``ai_target_sides._NO_SIDE_KINDS``).
* Musician ("{1}: Put a music counter on target creature. If it doesn't have
  "At the beginning of your upkeep, destroy this creature unless you pay {1}
  for each music counter on it," it gains that ability."): the grant read
  "you", so the AI taxed its own creature. A granted trigger that takes its
  holder off the battlefield is a burden (``ai_target_sides._grants_a_burden``).
"""

from __future__ import annotations

from engine.ai_abilities import choose_activation_action
from engine.ai_target_sides import ability_denies_its_target, ability_target_side
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card, _mk_creature_card, _nosick, resolve_stack


def _table(mine, theirs):
    """Seat 0 (active, in its main phase) holds *mine*, seat 1 *theirs*;
    costs unenforced."""
    p0 = PlayerState(name="P0", battlefield=[_nosick(Permanent(card=c)) for c in mine])
    p1 = PlayerState(name="P1", battlefield=[_nosick(Permanent(card=c)) for c in theirs])
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_phase = "main"
    return game


def _activate(game, action):
    result = game.queue_permanent_ability(
        0, action.permanent_name,
        target_player_index=action.target_player_index,
        permanent_index=action.permanent_index,
        target_permanent_index=action.target_permanent_index,
        ability_index=action.ability_index,
    )
    assert result.supported, result.details
    resolve_stack(game)


def test_riptide_mangler_copies_the_greatest_power_on_either_board(set_pool):
    """The Mangler (0/3) beside its controller's 2/2, facing a 6/4: it takes
    the 6 — an opponent's creature, whose power it only reads."""
    mangler_card = set_pool("LGN")["Riptide Mangler"]
    game = _table(
        [mangler_card, _mk_creature_card("Bear", 2, 2)],
        [_mk_creature_card("Wurm", 6, 4)],
    )
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Riptide Mangler"
    target = game.permanent_at(action.target_player_index, action.target_permanent_index)
    assert target is not None and target.card.name == "Wurm"
    _activate(game, action)
    mangler = next(p for p in game.controlled_by(0) if p.card.name == "Riptide Mangler")
    assert (mangler.effective_power, mangler.effective_toughness) == (6, 3)


def test_riptide_mangler_is_not_activated_for_a_change_of_nothing(set_pool):
    """W1G7's seeded game: the only creature to copy is its controller's 1/1.
    The first activation makes the Mangler 1/3; the second would make it 1/3
    again, and is not proposed."""
    mangler_card = set_pool("LGN")["Riptide Mangler"]
    game = _table([mangler_card, _mk_creature_card("Elf", 1, 1)], [])
    first = choose_activation_action(game, 0)
    assert first is not None and first.permanent_name == "Riptide Mangler"
    _activate(game, first)
    mangler = next(p for p in game.controlled_by(0) if p.card.name == "Riptide Mangler")
    assert mangler.effective_power == 1
    mangler.tapped = False
    again = choose_activation_action(game, 0)
    assert again is None or again.permanent_name != "Riptide Mangler", again


def test_musicians_grant_reads_as_a_burden(set_pool):
    (ability,) = [
        a for a in compile_card_oracle(set_pool("ICE")["Musician"]).activated_abilities
        if "music counter" in (a.source_line or "")
    ]
    assert ability_target_side(ability.instruction) == "opponent"
    assert ability_denies_its_target(ability.instruction)


def test_musician_puts_its_music_on_an_opponents_creature(set_pool):
    """With a Bear on each side, the AI's Musician names the opponent's —
    which then owes the upkeep the grant gives it."""
    pool = set_pool("ICE")
    game = _table([pool["Musician"], pool["Balduvian Bears"]], [pool["Balduvian Bears"]])
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Musician"
    assert action.target_player_index == 1
    _activate(game, action)
    (theirs,) = list(game.controlled_by(1))
    (mine,) = [p for p in game.controlled_by(0) if p.card.name == "Balduvian Bears"]
    assert counters_on(theirs, "music") == 1
    assert counters_on(mine, "music") == 0
    assert "destroy this creature unless you pay" in theirs.effective_card.oracle_text.lower()


def test_a_granted_self_removal_trigger_is_a_burden():
    """The reading is the compiler's own triggered-line front end, so a
    sacrifice spelled with no toll — or behind one — reads the same, and a
    trigger that helps its holder does not."""
    def instruction(quoted):
        card = _mk_card(
            "Grant Probe", "Creature — Human Wizard",
            f'{{1}}: Target creature gains "{quoted}" until end of turn.',
            power=1, toughness=1,
        )
        (ability,) = compile_card_oracle(card).activated_abilities
        return ability.instruction

    for burden in (
        "At the beginning of your upkeep, sacrifice this creature",
        "At the beginning of your upkeep, sacrifice this creature unless you pay {2}",
    ):
        assert ability_target_side(instruction(burden)) == "opponent", burden
    gift = instruction("At the beginning of your upkeep, put a +1/+1 counter on this creature")
    assert ability_target_side(gift) != "opponent"
