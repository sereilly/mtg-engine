"""Shipped offers that Odyssey's W1G8 cards stood on and found wrong.

Three defects, each in the machinery an "unless" is made of rather than in a
card, each found by driving an Odyssey card through it and each reproduced on
the tree before its fix:

* **A counter on a permanent that has left** (Junk Golem). The takeability
  gate for "remove a counter from this" asked how many counters the source
  *object* carries, and a permanent in a graveyard still carries them in
  memory. CR 122.2: they are not retained.
* **An offer about a stack object, answered after that object resolved**
  (Molten Influence). A headless resolution pops its object and the queue is
  drained when the stack is empty, so a paid Imprison countered an ability that
  had already happened.
* **A lethal toll, paid** (Blazing Salvo). "Pay tolls" paid any price whose
  penalty the valuation could not price — including one that cost the game.

No compiled program moves for any of them, so `oracle_diff` is blind here and
these are the instrument.
"""

from __future__ import annotations

import pytest

from engine.auras import attach_aura
from engine.named_counters import add_counters
from tests.sets import ody_w1g8_helpers as w1g8


# --- a counter on a permanent that has left ----------------------------------

@pytest.mark.parametrize("interactive", [(), (0,)])
def test_magmasaur_destroyed_in_response_cannot_buy_off_its_damage(
    set_pool, interactive
):
    """"You may remove a +1/+1 counter from this creature. If you don't,
    sacrifice this creature and it deals damage equal to the number of +1/+1
    counters on it to each creature without flying and each player."

    With Magmasaur gone the removal is an action nobody can take, so "if you
    don't" applies (CR 118.12) and the damage is its last known five
    (CR 608.2h). It used to be offered, accepted over a card in a graveyard,
    and the damage never happened.
    """
    game = w1g8.table(set_pool, interactive=interactive)
    saur = w1g8.put(game, set_pool, 0, "Magmasaur")
    game.active_player_index = 0
    game.resolve_upkeep(0, defer_priority=True)

    w1g8.leave(game, saur)
    w1g8.settle(game)

    assert w1g8.owed(game) == []
    assert [player.life for player in game.players] == [15, 15]


def test_magmasaur_on_the_battlefield_is_still_offered_its_counter(set_pool):
    game = w1g8.table(set_pool, interactive=(0,))
    saur = w1g8.put(game, set_pool, 0, "Magmasaur")
    game.active_player_index = 0
    game.resolve_upkeep(0)

    assert w1g8.owed(game) == [("optional_pay", 0)]
    assert game.confirm_optional_pay(0, accept=True)
    w1g8.settle(game)
    assert w1g8.pt(saur) == (4, 4)
    assert [player.life for player in game.players] == [20, 20]


def test_living_artifact_destroyed_in_response_pays_out_no_life(set_pool):
    """"You may remove a vitality counter from this Aura. If you do, you gain
    1 life." An Aura that left with its trigger on the stack has no counter
    to remove, so nothing is offered and no life is gained."""
    game = w1g8.table(set_pool)
    rock = w1g8.put(game, set_pool, 0, "Sol Ring")
    aura = w1g8.put(game, set_pool, 0, "Living Artifact")
    attach_aura(aura, rock)
    add_counters(aura, "vitality", 3)
    game.active_player_index = 0
    game.resolve_upkeep(0, defer_priority=True)

    w1g8.leave(game, aura)
    w1g8.settle(game)

    assert game.players[0].life == 20
    assert not any("Removed a vitality counter" in line for line in game.log)


# --- an offer about a stack object -------------------------------------------

def test_imprison_paid_headless_counters_the_ability_before_it_resolves(set_pool):
    """"…you may pay {1}. If you do, counter that ability." With no
    interactive seat the payment used to be collected after the stack had
    emptied: the {1} was spent, the Sorcerer pinged anyway, and the log said
    the ability was no longer on the stack."""
    game = w1g8.table(set_pool)
    game.start_turn(1)
    tim = w1g8.put(game, set_pool, 1, "Prodigal Sorcerer")
    aura = w1g8.put(game, set_pool, 0, "Imprison")
    attach_aura(aura, tim)
    game.players[0].mana_pool["C"] = 1

    used = game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0)
    w1g8.settle(game)

    assert used.supported, used.details
    assert game.players[0].life == 20, "the countered ability dealt no damage"
    assert game.players[0].mana_pool["C"] == 0
    assert any("Imprison countered" in line for line in game.log)
    assert game.is_on_battlefield(aura)


def test_an_offer_about_a_stack_object_still_waits_for_an_interactive_seat(set_pool):
    """The other half: where a seat is being asked, the resolution is held
    open and nothing is answered on its behalf."""
    game = w1g8.table(set_pool, interactive=(0,))
    game.start_turn(1)
    tim = w1g8.put(game, set_pool, 1, "Prodigal Sorcerer")
    aura = w1g8.put(game, set_pool, 0, "Imprison")
    attach_aura(aura, tim)
    game.players[0].mana_pool["C"] = 1

    game.queue_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert w1g8.owed(game) == [("optional_pay", 0)]
    assert [item.card.name for item in game.stack] == [
        "Prodigal Sorcerer", "Imprison",
    ], "both wait: the ability under the offer cannot resolve first"
    assert game.players[0].life == 20


# --- Erg Raiders, without its hook ---------------------------------------------

def test_erg_raiders_compiles_from_the_grammar_and_spares_a_thief_for_a_turn(set_pool):
    """Mad Dog's "or come under your control this turn" is the clause Erg
    Raiders prints as "unless it came under your control this turn", so the
    card's name-keyed line and its handler are retired: it is two conditions
    the grammar reads. Driven across a control change, which the hook's own
    tests never made."""
    from engine.card_hooks import CARD_LINE_INSTRUCTIONS
    from engine.control import change_control
    from engine.oracle import compile_card_oracle

    assert "Erg Raiders" not in CARD_LINE_INSTRUCTIONS
    program = compile_card_oracle(set_pool("ARN")["Erg Raiders"])
    assert program.supported
    assert program.triggered_abilities[0].instruction.kind == "if_then"

    game = w1g8.table(set_pool)
    raiders = w1g8.put(game, set_pool, 0, set_pool("ARN")["Erg Raiders"])

    def end_of_turn(seat):
        game.turn += 1
        game.start_turn(seat)
        if seat == 1 and game.controller_index_of(raiders) == 0:
            change_control(raiders, 1, source="a test's theft")
            game._sync_control()
        game.resolve_end_step(seat)
        w1g8.settle(game)
        return [player.life for player in game.players]

    assert end_of_turn(0) == [18, 20], "it sat out its controller's turn"
    assert end_of_turn(1) == [18, 20], "stolen this turn: no damage to the thief"
    assert end_of_turn(0) == [18, 20], "not its old controller's any more"
    assert end_of_turn(1) == [18, 18], "the thief's next idle turn"


# --- Kudzu, without its hook ---------------------------------------------------

def _kudzu(set_pool, own_other_land, opposing_land):
    game = w1g8.table(set_pool)
    forest = w1g8.put(game, set_pool, 1, "Forest")
    kudzu = w1g8.put(game, set_pool, 0, "Kudzu")
    attach_aura(kudzu, forest)
    if own_other_land:
        w1g8.put(game, set_pool, 1, "Swamp")
    if opposing_land:
        w1g8.put(game, set_pool, 0, "Mountain")
    game.start_turn(1)
    assert game.tap_land_for_mana(1, "Forest", permanent_id=forest.permanent_id)
    w1g8.settle(game)
    host = kudzu.metadata.get("attached_to")
    return game, kudzu, (None if host is None else host.card.name)


def test_kudzu_compiles_from_the_grammar_and_may_cross_the_table(set_pool):
    """"That land's controller may attach this Aura to a land of their
    choice." Kudzu's 2004-10-04 ruling: "You can move it to any other player's
    land whenever you get to move it." Its hook's own prompt offered the
    chooser's own lands alone; the composed program offers every land the Aura
    could enchant, and a seat nobody asks takes somebody else's first."""
    from engine.card_hooks import CARD_LINE_INSTRUCTIONS
    from engine.oracle import compile_card_oracle

    assert "Kudzu" not in CARD_LINE_INSTRUCTIONS
    kinds = [
        step.kind for step in compile_card_oracle(
            set_pool("LEA")["Kudzu"]
        ).triggered_abilities[0].instruction.payload["steps"]
    ]
    assert kinds == [
        "destroy_attached_permanent", "choose_permanent", "attach_source_to_target",
    ]

    game, kudzu, host = _kudzu(set_pool, own_other_land=True, opposing_land=True)
    assert host == "Mountain"
    game, kudzu, host = _kudzu(set_pool, own_other_land=False, opposing_land=True)
    assert host == "Mountain", "it used to stay where it was, on nothing"


def test_kudzu_with_no_land_to_move_to_is_put_in_the_graveyard(set_pool):
    """CR 704.5m. The hook kept the Aura out of that sweep while its prompt was
    owed by deleting its attachment record — and with no land to offer, armed
    no prompt, so the record stayed deleted and Kudzu sat on the battlefield
    attached to nothing for the rest of the game."""
    game, kudzu, host = _kudzu(set_pool, own_other_land=False, opposing_land=False)

    assert not game.is_on_battlefield(kudzu)
    assert w1g8.pile(game, 0) == ["Kudzu"]


# --- a lethal toll -------------------------------------------------------------

def test_toll_valuation_prices_the_spells_own_target(set_pool):
    """`toll_branch_loss` with the offer's context: damage that kills the
    offered seat's creature is that creature, damage that does not is
    nothing, and somebody else's creature is nothing either."""
    from engine.ai_valuation import TollLoss, toll_branch_loss
    from engine.game_types import OracleExecutionContext
    from engine.oracle import compile_card_oracle

    penalty = compile_card_oracle(
        set_pool("ODY")["Blazing Salvo"]
    ).instructions[0].payload["otherwise"]
    game = w1g8.table(set_pool)
    giant = w1g8.put(game, set_pool, 1, "Hill Giant")
    dragon = w1g8.put(game, set_pool, 1, "Shivan Dragon")

    def loss(seat, creature):
        context = OracleExecutionContext(
            caster=game.players[0], target=game.players[1],
            card=set_pool("ODY")["Blazing Salvo"],
            target_permanent_id=[creature.permanent_id],
        )
        return toll_branch_loss(game, seat, penalty, (), None, context)

    assert loss(1, giant) == TollLoss(permanents=(giant,))
    assert loss(1, dragon) == TollLoss()
    assert loss(0, giant) == TollLoss(), "not this seat's creature to lose"
    assert toll_branch_loss(game, 1, penalty) is None, "no context, no price"
