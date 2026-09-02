"""The AI casts its commander from the command zone (CR 903.8).

`ai_policy.choose_cast_action` read the hand and nothing else, so an AI seat's
commander sat in the command zone for the whole game and Commander-vs-AI was a
handicap match. The castability read is `ai_valuation.castable_commanders` —
the engine's own seam (`may_cast_from_command_zone`, `commander_tax`), so the
AI is offered exactly the casts the browser badges for a human seat — and the
weight (`COMMAND_ZONE_CAST_BONUS`) lives in `ai_policy` like every other one.

Every commander seam is inert unless `Game.commander_variant` is set, and so is
this policy: the ordinary-duel tests below are the claim that nothing changed
for a game that is not a Commander game.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_policy import choose_cast_action
from engine.ai_valuation import castable_commanders
from engine.commander import BRAWL, COMMANDER
from engine.models import Permanent

COMMANDER_NAME = "Gadrak, the Crown-Scourge"  # {2}{R} legendary dragon


def _commander_game(set_pool, *, mountains: int, variant: str = COMMANDER) -> Game:
    """A Commander game whose seat 0 has its commander in the command zone and
    *mountains* untapped Mountains on the battlefield, mana costs enforced."""
    pool = set_pool("M21")
    gadrak = pool[COMMANDER_NAME]
    p1 = PlayerState(
        name="AI",
        battlefield=[Permanent(card=pool["Mountain"]) for _ in range(mountains)],
    )
    p2 = PlayerState(name="B")
    game = Game(players=[p1, p2], commander_variant=variant)
    game.enforce_mana_costs = True
    game._sync_control()
    game.designate_commander(0, gadrak)
    p1.command_zone.append(gadrak)
    return game


# --- the valuation read (ai_valuation.castable_commanders) -------------------


def test_castable_commanders_names_the_commander_and_its_tax(set_pool):
    game = _commander_game(set_pool, mountains=3)
    gadrak = game.players[0].command_zone[0]

    assert castable_commanders(game, 0) == ((0, gadrak, 0),)

    game.record_commander_cast(0, gadrak)
    assert castable_commanders(game, 0) == ((0, gadrak, 2),)


def test_castable_commanders_is_empty_outside_a_commander_game(set_pool):
    """An ordinary duel never reads the command zone — even a card someone put
    there is not castable, because CR 903.8 is not in effect."""
    pool = set_pool("M21")
    p1 = PlayerState(name="AI")
    game = Game(players=[p1, PlayerState(name="B")])
    p1.command_zone.append(pool[COMMANDER_NAME])

    assert castable_commanders(game, 0) == ()


def test_castable_commanders_only_names_the_seats_own_commander(set_pool):
    """CR 903.8: "a player may cast a commander **they own**". Another card in
    the zone, or an opponent's commander, is not on offer."""
    game = _commander_game(set_pool, mountains=3)
    stray = set_pool("M21")["Mountain"]
    game.players[0].command_zone.append(stray)

    offered = castable_commanders(game, 0)
    assert [card.name for _i, card, _t in offered] == [COMMANDER_NAME]


# --- the policy (ai_policy.choose_cast_action) -------------------------------


def test_the_ai_proposes_casting_its_commander_from_the_command_zone(set_pool):
    game = _commander_game(set_pool, mountains=3)

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == COMMANDER_NAME
    assert action.from_zone == "command"
    assert action.hand_index == 0  # index into the command zone
    assert len(action.land_tap_indices) == 3  # {2}{R}, no tax yet


def test_the_proposed_commander_cast_resolves_onto_the_battlefield(set_pool):
    """The whole loop: the policy's action, executed exactly as the executors
    execute it, puts the commander onto the battlefield and counts the cast
    (CR 903.8's "each previous time")."""
    game = _commander_game(set_pool, mountains=3)
    p1 = game.players[0]

    action = choose_cast_action(game, 0)
    assert action is not None and action.from_zone == "command"
    for permanent_index in action.land_tap_indices:
        permanent = p1.battlefield[permanent_index]
        game.tap_land_for_mana(0, permanent.card.name, permanent_index=permanent_index)
    result = game.cast_from_hand(
        0,
        action.card_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
        x_value=action.x_value,
        from_zone=action.from_zone,
    )

    assert result.supported, result.details
    assert any(
        perm.card.name == COMMANDER_NAME for perm in game.controlled_by(0)
    ), game.log
    assert p1.command_zone == []
    assert p1.commander_casts.get(COMMANDER_NAME) == 1


def test_the_commander_tax_is_part_of_what_the_ai_can_afford(set_pool):
    """CR 903.8: {2} more for each previous cast from the zone. Three Mountains
    cover {2}{R} once; after one cast the same board cannot cover {4}{R}, and
    the AI proposes nothing rather than a cast the engine would refuse."""
    game = _commander_game(set_pool, mountains=3)
    gadrak = game.players[0].command_zone[0]
    game.record_commander_cast(0, gadrak)

    assert choose_cast_action(game, 0) is None


def test_the_taxed_recast_is_proposed_once_the_board_can_pay_it(set_pool):
    game = _commander_game(set_pool, mountains=5)
    gadrak = game.players[0].command_zone[0]
    game.record_commander_cast(0, gadrak)

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == COMMANDER_NAME
    assert action.from_zone == "command"
    assert len(action.land_tap_indices) == 5  # {2}{R} plus the {2} tax


def test_brawl_reads_the_same_seam(set_pool):
    game = _commander_game(set_pool, mountains=3, variant=BRAWL)

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == COMMANDER_NAME
    assert action.from_zone == "command"


# --- an ordinary duel is untouched -------------------------------------------


def test_an_ordinary_duel_never_proposes_a_command_zone_cast(set_pool):
    """A card sitting in the zone of a non-Commander game is not castable
    (CR 903.8 is not in effect), and the policy proposes nothing for it."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="AI",
        battlefield=[Permanent(card=pool["Mountain"]) for _ in range(3)],
    )
    game = Game(players=[p1, PlayerState(name="B")])
    game.enforce_mana_costs = True
    game._sync_control()
    p1.command_zone.append(pool[COMMANDER_NAME])

    assert choose_cast_action(game, 0) is None


def test_a_hand_cast_in_a_duel_still_comes_from_the_hand(set_pool):
    """The `from_zone` field defaults to "hand" for every action the policy
    has always proposed, so the executors' zone read changes nothing."""
    pool = set_pool("M21")
    p1 = PlayerState(name="AI", hand=[pool[COMMANDER_NAME]])
    game = Game(players=[p1, PlayerState(name="B")])

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.from_zone == "hand"
    assert action.card_name == COMMANDER_NAME
