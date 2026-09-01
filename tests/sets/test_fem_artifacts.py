"""Per-card tests for Fallen Empires' artifacts.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations


# --- G2: self-clocks, delayed self-sacrifice and card-flow order ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent


def _g2_lea():
    return {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _g2_artifact_game(card, *, hand, library, opponent_hand=()):
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    player = PlayerState(
        name="P1", battlefield=[permanent], hand=list(hand), library=list(library)
    )
    opponent = PlayerState(name="P2", hand=list(opponent_hand))
    game = Game(players=[player, opponent])
    game.enforce_mana_costs = False
    game._settle()
    return game, player, opponent, permanent


def _g2_use(game, name):
    result = game.activate_permanent_ability(0, name, permanent_index=0)
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return result


def test_conch_horn_draws_two_then_puts_one_back_on_top(set_pool):
    """"{1}, {T}, Sacrifice this artifact: Draw two cards, then put a card from
    your hand on top of your library."

    The order is the card. Drawing first is what makes the choice worth
    anything, and the card put back is one *chosen* from the hand -- so the
    hand is up one card, the library is down one, and the chosen card is on
    top. No "in any order" is printed because one card has none to give.
    """
    lea = _g2_lea()
    game, player, _opponent, horn = _g2_artifact_game(
        set_pool("FEM")["Conch Horn"],
        hand=[lea["Black Lotus"]],
        library=[lea["Mountain"], lea["Forest"], lea["Island"]],
    )

    result = _g2_use(game, "Conch Horn")

    assert result.supported, result.details
    assert sorted(card.name for card in player.hand) == [
        "Black Lotus", "Forest", "Mountain",
    ]
    assert [c.kind for c in game.pending_choices] == ["hand_to_library"]

    lotus_slot = [card.name for card in player.hand].index("Black Lotus")
    assert game.confirm_hand_to_library(0, [lotus_slot]) is True
    game._settle()

    assert sorted(card.name for card in player.hand) == ["Forest", "Mountain"]
    assert player.library[0].name == "Black Lotus"
    assert len(player.library) == 2


def test_conch_horn_is_sacrificed_as_a_cost_and_still_resolves(set_pool):
    """"Sacrifice this artifact" is part of the activation cost (CR 601.2h), so
    the Horn is in the graveyard before its ability resolves -- and the ability
    resolves anyway."""
    lea = _g2_lea()
    game, player, _opponent, _horn = _g2_artifact_game(
        set_pool("FEM")["Conch Horn"],
        hand=[lea["Black Lotus"]],
        library=[lea["Mountain"], lea["Forest"], lea["Island"]],
    )

    _g2_use(game, "Conch Horn")

    assert [p.card.name for p in player.battlefield] == []
    assert "Conch Horn" in [card.name for card in player.graveyard]
    assert len(player.hand) == 3


def test_ring_of_renewal_discards_its_own_controllers_card_at_random(set_pool):
    """"{5}, {T}: Discard a card at random, then draw two cards."

    The sentence names no target, so CR 608.2's unwritten subject is the
    ability's controller -- and the *sampling* discard handler reads a targeted
    seat by default, which for an activation nobody targeted with is the
    opponent. The opponent's hand is the assertion that matters here.
    """
    lea = _g2_lea()
    game, player, opponent, ring = _g2_artifact_game(
        set_pool("FEM")["Ring of Renewal"],
        hand=[lea["Black Lotus"]],
        library=[lea["Mountain"], lea["Forest"], lea["Island"]],
        opponent_hand=[lea["Healing Salve"], lea["Ancestral Recall"]],
    )

    result = _g2_use(game, "Ring of Renewal")

    assert result.supported, result.details
    assert [card.name for card in player.graveyard] == ["Black Lotus"]
    assert sorted(card.name for card in opponent.hand) == [
        "Ancestral Recall", "Healing Salve",
    ]
    assert opponent.graveyard == []
    assert ring.tapped is True


def test_ring_of_renewal_discards_before_it_draws(set_pool):
    """"Discard a card at random, **then** draw two cards." The order decides
    which cards the sample could have taken: run the other way round, a card
    just drawn could be pitched, which is a different card.

    With exactly one card in hand the sample has one candidate, so the discard
    is knowable -- and the two drawn cards are still in hand afterwards.
    """
    lea = _g2_lea()
    game, player, _opponent, _ring = _g2_artifact_game(
        set_pool("FEM")["Ring of Renewal"],
        hand=[lea["Black Lotus"]],
        library=[lea["Mountain"], lea["Forest"], lea["Island"]],
    )

    _g2_use(game, "Ring of Renewal")

    assert [card.name for card in player.graveyard] == ["Black Lotus"]
    assert sorted(card.name for card in player.hand) == ["Forest", "Mountain"]
    assert len(player.library) == 1


# --- G3: combat triggers, block restrictions and damage substitution ---
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, usable_activated_abilities


def _g3_delif_board(set_pool, artifact_name):
    """The named artifact beside a 3/2 attacker, with combat ready to walk.

    Seat 0 is interactive so the offer Delif's Cone owes queues rather than
    taking its default — which is also what makes combat wait for it
    (CR 608.2).
    """
    pool = set_pool("FEM")
    artifact = Permanent(card=pool[artifact_name])
    attacker = Permanent(card=pool["Brassclaw Orcs"])   # 3/2
    game = Game(players=[
        PlayerState(name="P0", life=20, battlefield=[artifact, attacker]),
        PlayerState(name="P1", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._settle()
    game.start_turn(0)
    for perm in (artifact, attacker):
        perm.metadata["summoning_sickness_turn"] = -99
    return game, artifact, attacker


def _g3_delif_attack_unblocked(game, attacker):
    """Attack with *attacker* and walk to the moment blocks lock — CR 509.1h,
    where "attacks and isn't blocked" is announced.

    The slot is found by identity rather than written down: Delif's Cone is
    sacrificed to pay for its own ability, and everything behind it on the
    battlefield renumbers the moment it leaves.
    """
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    slot = game.battlefield_index_of(attacker)
    assert game.declare_attackers(0, [slot])[0]
    game._settle()
    game.advance_combat_phase()   # declare blockers
    game.advance_combat_phase()   # blocks lock; the delayed ability fires
    game._settle()
    for _ in range(len(game.stack) + 8):
        if not game.stack or not game.resolve_top_of_stack():
            break
    game._settle()


def _g3_delif_finish_combat(game):
    for _ in range(len(list(game._phase_steps("combat"))) + 1):
        if game.current_turn_phase != "combat":
            break
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        game._settle()
        if (game.current_turn_phase, game.current_step) == before:
            break
    game.check_state_based_actions()


def test_g3_delifs_cone_offers_a_creature_you_control(set_pool):
    """The opener chooses its own target, so the *ability* has to describe one.

    Asserted on its own because the failure is silent everywhere else: with no
    ``targets`` description the picker asks for nothing, the arming handler
    binds nothing, and the ability creates no delayed trigger at all — while
    the card still compiles supported.
    """
    program = compile_card_oracle(set_pool("FEM")["Delif's Cone"])
    abilities = usable_activated_abilities(program)

    assert len(abilities) == 1
    assert derive_activation_spec(abilities[0]) == {
        "kind": "creature", "own_only": True,
    }


def test_g3_delifs_cone_trades_the_attackers_damage_for_life(set_pool):
    """"{T}, Sacrifice this artifact: This turn, when target creature you
    control attacks and isn't blocked, you may gain life equal to its power. If
    you do, it assigns no combat damage this turn."

    Three things at once, and the defending player's life is what proves the
    last of them: the delayed ability is created with the creature it targeted
    bound to it (CR 603.7c), the life gained is *that creature's* power rather
    than the Cone's, and the attacker then assigns nothing — which nothing
    prevents and no shield records, so the untouched 20 is the only evidence.
    """
    game, cone, attacker = _g3_delif_board(set_pool, "Delif's Cone")

    result = game.activate_permanent_ability(
        0, "Delif's Cone", target_player_index=0, target_permanent_index=1,
    )
    game._settle()
    assert result.supported, result.details
    assert not game.is_on_battlefield(cone), "the Cone is sacrificed to pay"
    assert [e.bound_permanent_id for e in game.delayed_triggers] == [
        attacker.permanent_id
    ], game.log

    _g3_delif_attack_unblocked(game, attacker)
    assert game.confirm_optional_pay(0, "Delif's Cone", accept=True), game.log
    _g3_delif_finish_combat(game)

    assert game.players[0].life == 23, game.log
    assert game.players[1].life == 20, game.log


def test_g3_declining_the_cone_lets_the_damage_through(set_pool):
    """"If you do" — the other half. No life gained, so the rider never runs
    and the 3/2 connects for three."""
    game, cone, attacker = _g3_delif_board(set_pool, "Delif's Cone")

    assert game.activate_permanent_ability(
        0, "Delif's Cone", target_player_index=0, target_permanent_index=1,
    ).supported
    game._settle()

    _g3_delif_attack_unblocked(game, attacker)
    assert game.confirm_optional_pay(0, "Delif's Cone", accept=False), game.log
    _g3_delif_finish_combat(game)

    assert game.players[0].life == 20
    assert game.players[1].life == 17, game.log


def test_g3_delifs_cube_banks_a_counter_instead_of_connecting(set_pool):
    """"{2}, {T}: This turn, when target creature you control attacks and isn't
    blocked, it assigns no combat damage this turn **and you put a cube counter
    on this artifact**."

    The two halves name two different permanents, and that is the whole test:
    "it" is the creature the opener targeted (CR 603.7c) and "this artifact" is
    the Cube that armed the ability (CR 603.7d) — which is still on the
    battlefield, unlike the Cone's, so reading either one as the other is
    observable. The counter is what the card's *other* ability spends.
    """
    game, cube, attacker = _g3_delif_board(set_pool, "Delif's Cube")

    assert game.activate_permanent_ability(
        0, "Delif's Cube", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    ).supported
    game._settle()

    _g3_delif_attack_unblocked(game, attacker)
    _g3_delif_finish_combat(game)

    assert game.players[1].life == 20, game.log
    assert counters_on(cube, "cube") == 1, game.log
    assert counters_on(attacker, "cube") == 0, (
        "\"this artifact\" is the Cube, never the creature the event was about"
    )
