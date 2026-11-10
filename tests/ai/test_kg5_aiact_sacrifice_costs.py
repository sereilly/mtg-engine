"""An ability whose cost sacrifices a permanent is weighed, not declined (kg5 aiact).

The main-phase chooser (``ai_abilities._activation_candidate``) declined every
cost with a sacrifice in it before anything was weighed — "a trade this policy
cannot price" — so 173 non-mana abilities in both manifest roles were never
activated by an AI seat: the Known gaps' four sacrifice-cost both-sides pumps
(Goblin Soothsayer, Orc General, Goblin Lookout, Squirrel Wrangler), and
Mirrodin's "activated sacrifice twins", Bosh and the thirteen others whose
effect reads what the sacrifice ate ("damage equal to the sacrificed
artifact's mana value"), among them.

A cost that sacrifices a printed number of permanents is now priced by
rehearsal with the whole cost paid (``ai_activation_rehearsal.
_sacrifice_priced_activation``): the victim named (``ActivationAction.
cost_permanent_ids``) — the cheapest to lose, or one per distinct reading
where the effect is measured by it (``ai_sacrifice_victims.
activation_sacrifice_choices``) — and read through the fight before a combat.
A land the seat needs is paid only for the game itself
(``eats_a_land_it_needs``, ``DECIDES_THE_GAME``).

Validated backwards: on the base the census below finds no ability reaching
the weighing (the gate declined all 173), and every board here proposes
nothing.
"""

from __future__ import annotations

import pytest

from engine import ai_abilities
from engine.ai_abilities import _abilities_weighed, choose_activation_action
from engine.ai_simulator import SimulationReport, _play_activations
from engine.ai_valuation import is_mana_ability
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import declare_attack, drive_combat, stock_libraries


def _board(mine=(), theirs=(), *, their_life: int = 20):
    """The AI's precombat main phase, costs enforced, nothing summoning sick."""
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    stock_libraries(game)
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
    game.players[1].life = their_life
    return game


def _activate(game):
    """The simulator's own main-phase activation pass; returns its report."""
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _play_activations(game, 0, report, 1, 1)
    assert not report.refused_activations, report.refused_activations
    return report


def _names(cards):
    return sorted(card.name for card in cards)


def test_goblin_lookout_pays_a_goblin_for_the_attack_that_is_lethal(set_pool):
    """"{T}, Sacrifice a Goblin: Goblin creatures get +2/+0 until end of
    turn." Three 1/1 Goblins and the Lookout against 6 life: attacking with
    all four deals 4; tapping the Lookout and paying one Goblin leaves two
    3/1s, which deal 6. The Goblin paid is a Raging Goblin, never the
    Lookout itself, and the attack that follows is lethal."""
    lea, goblin = set_pool("LEA"), set_pool("EXO")["Raging Goblin"]
    game = _board(
        mine=[set_pool("LGN")["Goblin Lookout"], goblin, goblin, goblin,
              lea["Mountain"], lea["Mountain"]],
        their_life=6,
    )
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Goblin Lookout"
    _activate(game)
    assert _names(game.players[0].graveyard) == ["Raging Goblin"]
    declare_attack(game, 0)
    drive_combat(game)
    assert game.players[1].life <= 0


def test_goblin_lookout_pays_nothing_where_no_attack_is_lethal(set_pool):
    """The same board against 20 life: two points more of damage are not
    worth a Goblin, and the pump wears off — nothing is proposed."""
    lea, goblin = set_pool("LEA"), set_pool("EXO")["Raging Goblin"]
    game = _board(
        mine=[set_pool("LGN")["Goblin Lookout"], goblin, goblin, goblin,
              lea["Mountain"], lea["Mountain"]],
        their_life=20,
    )
    assert choose_activation_action(game, 0) is None


def test_goblin_soothsayer_pumps_the_red_attackers_into_lethal(set_pool):
    """"{R}, {T}, Sacrifice a Goblin: Red creatures get +1/+1 until end of
    turn." — every red creature, both sides'. Four 1/1 Goblins and the
    Soothsayer against 6: five 1/1s deal 5; three 2/2s deal 6."""
    lea, goblin = set_pool("LEA"), set_pool("EXO")["Raging Goblin"]
    game = _board(
        mine=[set_pool("MIR")["Goblin Soothsayer"], goblin, goblin, goblin, goblin,
              lea["Mountain"], lea["Mountain"]],
        their_life=6,
    )
    _activate(game)
    assert _names(game.players[0].graveyard) == ["Raging Goblin"]
    declare_attack(game, 0)
    drive_combat(game)
    assert game.players[1].life <= 0


def test_goblin_soothsayer_does_not_pump_a_bigger_red_board_across_the_table(set_pool):
    """The pump reaches both sides: against an opponent whose red blockers
    it grows as much as the AI's attackers, and at a life total no attack
    reaches, a Goblin paid for it is a Goblin given away."""
    lea, goblin = set_pool("LEA"), set_pool("EXO")["Raging Goblin"]
    game = _board(
        mine=[set_pool("MIR")["Goblin Soothsayer"], goblin, goblin,
              lea["Mountain"], lea["Mountain"]],
        theirs=[lea["Ironclaw Orcs"], lea["Ironclaw Orcs"], lea["Ironclaw Orcs"]],
    )
    assert choose_activation_action(game, 0) is None


def test_orc_general_pays_its_goblin_for_the_orcs(set_pool):
    """"{T}, Sacrifice another Orc or Goblin: Other Orc creatures get +1/+1
    until end of turn." Four 2/2 Orcs, a 1/1 Goblin and the General against
    12: all six attack for 11; with the General tapped and the Goblin paid,
    four 3/3 Orcs deal 12. The cheapest permanent the cost admits is the
    Goblin."""
    lea = set_pool("LEA")
    orcs = [lea["Ironclaw Orcs"]] * 4
    game = _board(
        mine=[set_pool("DRK")["Orc General"], *orcs, lea["Mons's Goblin Raiders"],
              lea["Mountain"]],
        their_life=12,
    )
    _activate(game)
    assert _names(game.players[0].graveyard) == ["Mons's Goblin Raiders"]
    declare_attack(game, 0)
    drive_combat(game)
    assert game.players[1].life <= 0


def test_squirrel_wrangler_makes_squirrels_with_a_spare_land_only(set_pool):
    """"{1}{G}, Sacrifice a land: Create two 1/1 green Squirrel creature
    tokens." The standing prices two 1/1s above a land, so on four Forests
    the Wrangler ate one every turn; a land out of the six a seat needs is
    paid only where it decides the game. On nine Forests the land is spare
    and the Squirrels are made."""
    lea, wrangler = set_pool("LEA"), set_pool("PCY")["Squirrel Wrangler"]
    short = _board(mine=[wrangler, *[lea["Forest"]] * 4])
    assert choose_activation_action(short, 0) is None

    rich = _board(mine=[wrangler, *[lea["Forest"]] * 9])
    _activate(rich)
    assert _names(rich.players[0].graveyard) == ["Forest"]
    squirrels = [p for p in rich.players[0].battlefield if p.card.name.startswith("Squirrel")
                 and p.metadata.get("is_token")]
    assert len(squirrels) == 2


def test_bosh_flings_the_artifact_whose_mana_value_is_lethal(set_pool):
    """"{3}{R}, Sacrifice an artifact: Bosh deals damage equal to the
    sacrificed artifact's mana value to any target." With an Ornithopter (0)
    and a Juggernaut (4) beside it against 4 life, the engine's default pick
    — the smallest — would fling the Ornithopter for nothing. The victim is
    weighed per reading: the Juggernaut's 4 ends the game, and so would Bosh
    itself (an artifact, 8), which costs the seat more."""
    lea = set_pool("LEA")
    game = _board(
        mine=[set_pool("MRD")["Bosh, Iron Golem"], lea["Juggernaut"],
              set_pool("ATQ")["Ornithopter"], *[lea["Mountain"]] * 4],
        their_life=4,
    )
    juggernaut = next(p for p in game.players[0].battlefield if p.card.name == "Juggernaut")
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Bosh, Iron Golem"
    assert action.cost_permanent_ids == [juggernaut.permanent_id]
    _activate(game)
    assert _names(game.players[0].graveyard) == ["Juggernaut"]
    assert game.players[1].life <= 0


def test_bosh_flings_nothing_for_damage_that_decides_nothing(set_pool):
    """At 20 life four damage is not worth a four-mana artifact."""
    lea = set_pool("LEA")
    game = _board(
        mine=[set_pool("MRD")["Bosh, Iron Golem"], lea["Juggernaut"],
              *[lea["Mountain"]] * 4],
    )
    assert choose_activation_action(game, 0) is None


#: Permanents put beside each sacrifice-cost ability in the census, so that
#: most printed nouns ("a Goblin", "an artifact", "a land", "a white
#: creature", "an enchantment", "a Swamp") have something to eat.
_FODDER = (
    ("LEA", "Grizzly Bears"), ("EXO", "Raging Goblin"), ("LEA", "Ironclaw Orcs"),
    ("ATQ", "Ornithopter"), ("LEA", "Savannah Lions"), ("LEA", "Merfolk of the Pearl Trident"),
    ("LEA", "Bad Moon"), ("LEA", "Samite Healer"), ("ATQ", "Atog"),
    ("LEA", "Plains"), ("LEA", "Island"), ("LEA", "Swamp"), ("LEA", "Mountain"),
    ("LEA", "Forest"),
)


def test_every_sacrifice_cost_reaches_the_weighing(set_pool, monkeypatch):
    """Census over both manifest roles: every supported non-mana ability
    whose cost sacrifices a printed number of permanents, on a board holding
    something of most printed nouns and lands of every colour, either
    reaches the sacrifice weighing (``_sacrifice_priced_activation``) or is
    stopped by a gate that names something other than the sacrifice — and a
    floor of them reach it. On the base none did."""
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.faces import compilation_units

    reached = set()

    def spy(game, seat, permanent, ability, candidate, *, at_instant_speed=False):
        reached.add((permanent.card.name, ability.source_line))
        return None

    monkeypatch.setattr(ai_abilities, "_sacrifice_priced_activation", spy)
    fodder = [set_pool(code)[name] for code, name in _FODDER]
    lands = [card for card in fodder if card.primary_type == "land"]
    weighed = 0
    from engine.oracle import compile_card_oracle
    from engine.targeting import usable_activated_abilities

    def sacrifices(card) -> bool:
        program = compile_card_oracle(card)
        return program.supported and any(
            ability.cost.sacrifice_filter is not None
            for ability in usable_activated_abilities(program)
        )

    pool = compilation_units(load_cards(manifest_set_paths(include_measured=True)))
    for card in (card for card in pool if sacrifices(card)):
        game = _board(mine=[card, *fodder, *lands, *lands])
        source = game.players[0].battlefield[0]
        if game.lost_abilities_refusal(source) is not None:
            continue
        for ability_index, ability in _abilities_weighed(game, source):
            cost = ability.cost
            if cost.sacrifice_filter is None or not isinstance(cost.sacrifice_count, int):
                continue
            if ability.instruction is None or is_mana_ability(ability.instruction):
                continue
            weighed += 1
            ai_abilities._activation_candidate(
                game, 0, 0, source, ability, ability_index,
            )
    # 171 weighed and 113 reaching it when this was written; the rest stop
    # at a printed timing, a target or a noun nothing here matches.
    assert weighed >= 160, weighed
    assert len(reached) >= 105, (len(reached), weighed)
    assert {
        "Goblin Soothsayer", "Orc General", "Goblin Lookout", "Squirrel Wrangler",
        "Bosh, Iron Golem",
    } <= {name for name, _line in reached}
