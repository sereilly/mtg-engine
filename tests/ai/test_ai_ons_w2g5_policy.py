"""The AI pile ONS's wave 1 measured in seeded games and left (ONS W2G5).

Each section is one piece of policy, with the board that shows it and, where
the shape reaches past Onslaught, the pool-wide reading.

* **An activation that gives up its own source, or comes back at its own
  activator, is rehearsed** (`ai_abilities._gives_up_its_source`,
  `ai_valuation.reaches_both_sides`). Crown of Vigor was cast and sacrificed in
  the same main phase — a lasting +1/+1 traded for a fleeting one with nothing
  able to attack — and Shepherd of Rot drained both players from any position,
  its controller's losing one included: both were scored a flat 2.5.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.aura_attachment import attach_aura
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w2g5_card(set_pool, name):
    ons = set_pool("ONS")
    return ons[name] if name in ons else set_pool("LEA")[name]


def _w2g5_board(set_pool, mine, theirs=(), *, hand=(), life=(20, 20), sick=()):
    """Seat 0 in its own precombat main phase with *mine* (ONS names first,
    then Alpha's), costs enforced; seat 1 with *theirs*. Nothing is summoning
    sick except the names in *sick*."""
    def card(name):
        return _w2g5_card(set_pool, name)

    game = Game(players=[
        PlayerState(
            name="A", battlefield=[Permanent(card=card(n)) for n in mine],
            hand=[card(n) for n in hand], library=[card("Island")] * 10,
            life=life[0],
        ),
        PlayerState(
            name="B", battlefield=[Permanent(card=card(n)) for n in theirs],
            library=[card("Island")] * 10, life=life[1],
        ),
    ], enforce_mana_costs=True)
    game.interactive_seats = set()
    game.start_turn(0)
    game._sync_control()
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = (
            game.turn if permanent.card.name in sick else -99
        )
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _w2g5_crowned(set_pool, theirs=(), *, life=20, sick=()):
    """Two Grizzly Bears, the first wearing Crown of Vigor, against *theirs*
    at *life*."""
    game = _w2g5_board(
        set_pool, ["Grizzly Bears", "Grizzly Bears", "Forest"], theirs,
        life=(20, life), sick=sick,
    )
    bears = next(iter(game.controlled_by(0)))
    crown = Permanent(card=_w2g5_card(set_pool, "Crown of Vigor"))
    game.players[0].battlefield.append(crown)
    game._sync_control()
    attach_aura(crown, bears)
    crown.metadata["summoning_sickness_turn"] = -99
    return game, crown


@pytest.mark.parametrize("sick", [(), ("Grizzly Bears",)])
def test_w2g5_a_crown_is_not_sacrificed_for_a_point_nothing_needs(set_pool, sick):
    """At twenty life across an empty board the sacrifice buys one damage this
    turn for the +1/+1 the Aura gives every turn — and with the Bears unable
    to attack, nothing at all. The Crown stays on."""
    game, _crown = _w2g5_crowned(set_pool, sick=sick)
    assert choose_activation_action(game, 0) is None


def test_w2g5_a_crown_is_sacrificed_when_it_is_the_lethal_point(set_pool):
    """At six life the Crown's +1/+1 to both Bears (they share a type) is the
    sixth damage: the rehearsal fights the combat, sees the game end, and the
    sacrifice is proposed — and carried out it pumps both."""
    game, crown = _w2g5_crowned(set_pool, life=6)
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Crown of Vigor"
    assert game.activate_permanent_ability(
        0, action.permanent_name, permanent_index=action.permanent_index,
    ).supported
    resolve_stack(game)
    assert crown not in game.players[0].battlefield
    assert sorted(
        (p.effective_power, p.effective_toughness)
        for p in game.controlled_by(0) if p.is_creature
    ) == [(3, 3), (3, 3)]


@pytest.mark.parametrize(("life", "activated"), [
    ((20, 20), False),  # level: a point each is nothing gained
    ((5, 20), False),   # behind: the race is the opponent's
    ((20, 5), True),    # ahead: the last points are the dear ones
])
def test_w2g5_shepherd_of_rot_drains_only_from_ahead(set_pool, life, activated):
    """Two Zombies on the table, so each player loses two. Worth it only to the
    seat whose two points are worth less than the opponent's
    (`ai_rehearsal.life_worth` is concave)."""
    game = _w2g5_board(
        set_pool, ["Shepherd of Rot", "Gluttonous Zombie", "Swamp"], ["Grizzly Bears"],
        life=life,
    )
    action = choose_activation_action(game, 0)
    assert (action is not None and action.permanent_name == "Shepherd of Rot") is activated


# ==== Riptide Entrancer: a priced trade, weighed ==============================
#
# "Whenever this creature deals combat damage to a player, you may sacrifice it.
# If you do, gain control of target creature that player controls." The
# optional-pay default's "make no trades" declined it every time it connected
# (nine declines in one seeded ONS game, W1G10's report); its two halves are
# permanents a standing prices (`ai_prompt_readers.offer_trade`'s
# ``("source", "target_permanent")``, weighed by
# `ai_prompts.offer_trade_is_worth_taking`).


def _w2g5_entrancer_connects(set_pool, theirs):
    from engine.ai_combat import run_ai_combat_phase

    game = _w2g5_board(set_pool, ["Riptide Entrancer", "Island"], theirs)
    game.prompt_driver = lambda played: played.auto_resolve_pending_choices()
    for permanent in game.controlled_by(1):
        permanent.tapped = True  # nothing to block with
    run_ai_combat_phase(game, 0)
    game._resolve_priority_window()
    game.auto_resolve_pending_choices()
    return game


def test_w2g5_riptide_entrancer_is_sacrificed_for_the_creature_it_targets(set_pool):
    """A 1/1 that has connected is traded for the Hill Giant across the table:
    the Entrancer is in its owner's graveyard and the Giant is seat 0's."""
    game = _w2g5_entrancer_connects(set_pool, ["Hill Giant"])
    assert any("Riptide Entrancer: targets Hill Giant" in line for line in game.log)
    assert [p.card.name for p in game.controlled_by(0) if p.is_creature] == ["Hill Giant"]
    assert [card.name for card in game.players[0].graveyard] == ["Riptide Entrancer"]
    assert not any(p.is_creature for p in game.controlled_by(1))


def test_w2g5_thalakos_deceiver_takes_the_same_trade(set_pool):
    """Stronghold's "Whenever this creature attacks and isn't blocked, you may
    sacrifice it. If you do, gain control of target creature." — the one other
    card the reader names, and the same weighing: unblocked, the Deceiver is
    traded for the Hill Giant rather than for the seat's own Bears."""
    from engine.ai_combat import run_ai_combat_phase

    game = _w2g5_board(set_pool, ["Island"], ["Hill Giant"])
    deceiver = Permanent(card=set_pool("STH")["Thalakos Deceiver"])
    game.players[0].battlefield.insert(0, deceiver)
    game._sync_control()
    deceiver.metadata["summoning_sickness_turn"] = -99
    game.prompt_driver = lambda played: played.auto_resolve_pending_choices()
    for permanent in game.controlled_by(1):
        permanent.tapped = True
    run_ai_combat_phase(game, 0)
    game._resolve_priority_window()
    game.auto_resolve_pending_choices()
    assert [p.card.name for p in game.controlled_by(0) if p.is_creature] == ["Hill Giant"]
    assert [card.name for card in game.players[0].graveyard] == ["Thalakos Deceiver"]


# ==== Birchlore Rangers: a mana ability paid by tapping other permanents ======
#
# "Tap two untapped Elves you control: Add one mana of any color." The payment
# planner counted a land, a {T} source and a self-sacrifice, and never a cost
# paid in other permanents (`ai_mana_sources.tap_cost_mana_activations`), so no
# AI seat ever used the Rangers' mana; the castable highlight did not count it
# either (`board_payment.board_can_pay(nonland_sources=True)`).


def _w2g5_rangers_board(set_pool, *, hand=("Wirewood Savage",)):
    """A Forest and a Llanowar Elves (two mana by themselves), Birchlore
    Rangers, and an Elvish Warrior that arrived this turn."""
    return _w2g5_board(
        set_pool, ["Forest", "Birchlore Rangers", "Elvish Warrior", "Llanowar Elves"],
        ["Grizzly Bears"], hand=hand, sick=("Elvish Warrior",),
    )


def test_w2g5_the_plan_counts_a_mana_paid_by_tapping_two_elves(set_pool):
    """{2}{G} over two mana of its own and the Rangers: the plan reaches the
    Rangers last, once — and {G}{G}{G}{G} is still more than the board makes."""
    from engine.ai_payment import _plan_land_taps

    game = _w2g5_rangers_board(set_pool)
    player = game.players[0]
    rangers_slot = next(
        slot for slot, p in enumerate(game.controlled_by(0)) if p.card.name == "Birchlore Rangers"
    )
    slots, _colours = _plan_land_taps(game, player, {"generic": 2, "G": 1})
    assert sorted(slots) == sorted([0, 3, rangers_slot])
    assert _plan_land_taps(game, player, {"G": 4}) is None


def test_w2g5_the_rangers_tap_the_elves_the_seat_misses_least(set_pool):
    """Cast for real: the Savage resolves, paid by the Forest, the Llanowar
    Elves' own mana and one Rangers activation that tapped the summoning-sick
    Warrior (it could not attack this turn) and the Rangers itself — never the
    Llanowar Elves, which is a mana of its own."""
    from engine.ai_payment import tap_planned_lands
    from engine.ai_policy import choose_cast_action

    game = _w2g5_rangers_board(set_pool)
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Wirewood Savage"
    action = tap_planned_lands(game, 0, action)
    assert game.cast_from_hand(0, action.card_name).supported
    resolve_stack(game)
    assert any(
        "Birchlore Rangers: tapped Elvish Warrior, Birchlore Rangers to pay its cost" in line
        for line in game.log
    )
    assert all(p.tapped for p in game.controlled_by(0) if p.card.name != "Wirewood Savage")
    assert "Wirewood Savage" in [p.card.name for p in game.controlled_by(0)]
    assert not any(game.players[0].mana_pool.values())


def test_w2g5_the_highlight_counts_the_rangers(set_pool):
    """The castable highlight's question (CR 601.2g: what the player could
    activate) over the same board: three mana, not two — and still not four."""
    from engine.board_payment import board_can_pay

    game = _w2g5_rangers_board(set_pool)
    assert board_can_pay(game, 0, {"generic": 2, "G": 1}, nonland_sources=True)
    assert not board_can_pay(game, 0, {"generic": 3, "G": 1}, nonland_sources=True)
    # The automatic payment's own question (lands only) is unchanged.
    assert not board_can_pay(game, 0, {"generic": 1, "G": 1})


def test_w2g5_the_rangers_never_tap_the_creature_an_ability_is_paid_for(set_pool):
    """An ability's own source is kept out of the cost that pays for it: with
    the Warrior as the source being paid for, the Rangers have one other Elf
    (themselves) and no pair to tap."""
    from engine.ai_mana_sources import tap_cost_mana_activations

    game = _w2g5_rangers_board(set_pool)
    warrior = next(p for p in game.controlled_by(0) if p.card.name == "Elvish Warrior")
    assert [
        [p.card.name for p in activation.tapped]
        for activation in tap_cost_mana_activations(game, 0)
    ] == [["Elvish Warrior", "Birchlore Rangers"]]
    assert tap_cost_mana_activations(game, 0, paying_for=warrior) == []


# ==== Cycling: what a cycle sets off is weighed ===============================
#
# "Cycling {2}{R}. When you cycle this card, you may have it deal 1 damage to
# each creature." (Slice and Dice.) `choose_hand_activation_action` scored the
# draw and nothing the cycle triggered, so the seat cycled it for the card
# whatever the sweep did to its own board (ONS W1G3). Each hand activation is
# now carried out on a copy (`ai_abilities._rehearse_hand_activation`).


@pytest.mark.parametrize(("mine", "theirs", "hand", "cycled"), [
    # The sweep kills two of the seat's own 1-toughness creatures and one of
    # the opponent's: not cycled.
    (["Goblin Balloon Brigade", "Mons's Goblin Raiders"], ["Scryb Sprites"],
     ["Slice and Dice"], None),
    # ...and with a plain cycler beside it, that is the card cycled instead.
    (["Goblin Balloon Brigade", "Mons's Goblin Raiders"], ["Scryb Sprites"],
     ["Lonely Sandbar", "Slice and Dice"], "Lonely Sandbar"),
    # The sweep kills two of the opponent's and none of the seat's: the
    # cycle that does it outranks the plain one held before it in hand.
    (["Hill Giant"], ["Scryb Sprites", "Mons's Goblin Raiders"],
     ["Lonely Sandbar", "Slice and Dice"], "Slice and Dice"),
])
def test_w2g5_a_cycle_is_weighed_by_what_it_sets_off(set_pool, mine, theirs, hand, cycled):
    from engine.ai_abilities import choose_hand_activation_action

    game = _w2g5_board(
        set_pool, ["Mountain", "Mountain", "Mountain", "Island", *mine], theirs, hand=hand,
    )
    action = choose_hand_activation_action(game, 0)
    assert (None if action is None else action.card_name) == cycled


def test_w2g5_the_weighed_cycle_is_carried_out(set_pool):
    """The proposal executed the simulator's way: the Sprites and the Raiders
    die, the Giant lives, the seat draws its card."""
    from engine.ai_abilities import choose_hand_activation_action
    from engine.ai_payment import tap_planned_lands

    game = _w2g5_board(
        set_pool, ["Mountain", "Mountain", "Mountain", "Hill Giant"],
        ["Scryb Sprites", "Mons's Goblin Raiders"], hand=["Slice and Dice"],
    )
    game.prompt_driver = lambda played: played.auto_resolve_pending_choices()
    action = tap_planned_lands(game, 0, choose_hand_activation_action(game, 0))
    assert game.activate_from_hand(
        0, action.card_name, ability_index=action.ability_index, hand_index=action.hand_index,
    ).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert not any(p.is_creature for p in game.controlled_by(1))
    assert [p.card.name for p in game.controlled_by(0) if p.is_creature] == ["Hill Giant"]
    assert [card.name for card in game.players[0].hand] == ["Island"]


# ==== An {X} in an activation cost, sized by rehearsal ========================
#
# "{X}{G}{G}: This creature deals X damage to each creature with flying."
# (Silklash Spider.) The activation chooser declined every ability with {X} in
# its cost — it announced no X, and the engine read none as zero — so no AI
# seat ever activated the Spider (ONS W1G12). An X that sizes only the effect
# is now announced: each X the board can pay is rehearsed and the best taken
# (`ai_abilities._sized_x_activation`).


@pytest.mark.parametrize(("mine", "theirs", "x_value"), [
    # Six Forests: X=4 kills the Air Elemental as well as the Sprites.
    (["Forest"] * 6, ["Scryb Sprites", "Air Elemental"], 4),
    # Three Forests: X=1 is all there is, and it kills the Sprites.
    (["Forest"] * 3, ["Scryb Sprites"], 1),
    # A Sprite on each side: every X kills one of each, which is nothing.
    (["Forest"] * 6 + ["Scryb Sprites"], ["Scryb Sprites"], None),
    # No flier anywhere: nothing to deal damage to.
    (["Forest"] * 6, ["Grizzly Bears"], None),
])
def test_w2g5_silklash_spider_pays_the_x_that_clears_the_sky(set_pool, mine, theirs, x_value):
    game = _w2g5_board(set_pool, ["Silklash Spider", *mine], theirs)
    action = choose_activation_action(game, 0)
    assert (None if action is None else action.x_value) == x_value


def test_w2g5_the_sized_activation_is_carried_out(set_pool):
    """The simulator's executor, with the announced X: both fliers die, and
    the six Forests are the X=4 and the {G}{G}."""
    from engine import ai_simulator

    game = _w2g5_board(
        set_pool, ["Silklash Spider", *["Forest"] * 6], ["Scryb Sprites", "Air Elemental"],
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    ai_simulator._play_activations(game, 0, report, 1, 1)
    assert not report.refused_activations
    assert not any(p.is_creature for p in game.controlled_by(1))
    assert all(p.tapped for p in game.controlled_by(0) if p.has_type("land"))
