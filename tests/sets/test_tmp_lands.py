"""Tempest lands.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G5: Ghost Town's restriction and Stalking Stones' duration ---

from engine import Game, PlayerState
from engine.models import Permanent


def _w1g5_land_game(land_name, set_pool):
    land = Permanent(card=set_pool("TMP")[land_name])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[land]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()
    return game, land


def test_w1g5_ghost_town_refuses_to_bounce_itself_on_your_own_turn(set_pool):
    """"{0}: Return this land to its owner's hand. **Activate only if it's not
    your turn.**" (CR 602.5.)

    The failure a restriction guards against is not a crash and not a missing
    ability: it is an ability that works *more often than the card allows*.
    Both directions are asserted, because a row admitted without a predicate
    behind it passes the positive half alone.
    """
    game, town = _w1g5_land_game("Ghost Town", set_pool)
    game.active_player_index = 0

    result = game.activate_permanent_ability(0, "Ghost Town", ability_index=1)
    assert not result.supported, "an activation on your own turn is refused"
    assert town in game.controlled_by(0), "and nothing was paid"
    assert game.players[0].hand == []


def test_w1g5_ghost_town_bounces_itself_on_an_opponents_turn(set_pool):
    game, _town = _w1g5_land_game("Ghost Town", set_pool)
    game.active_player_index = 1

    result = game.activate_permanent_ability(0, "Ghost Town", ability_index=1)
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert [card.name for card in game.players[0].hand] == ["Ghost Town"], game.log
    assert list(game.controlled_by(0)) == []


def test_w1g5_stalking_stones_animation_outlives_the_cleanup_step(set_pool):
    """"{6}: This land becomes a 3/3 Elemental artifact creature that's still a
    land. (This effect lasts indefinitely.)"

    CR 611.2a: a continuous effect from a resolving ability with no stated
    duration lasts as long as the game does. The cleanup step is the whole
    assertion — the until-end-of-turn record its sibling writes is swept there,
    and a self-animation routed onto that kind would end the turn it started
    while reporting supported the entire time.

    The types are added, not replaced (CR 613 layer 4), which is what "that's
    still a land" means and why it needs no code of its own.
    """
    game, stones = _w1g5_land_game("Stalking Stones", set_pool)

    result = game.activate_permanent_ability(0, "Stalking Stones", ability_index=1)
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert stones.is_creature
    assert (stones.effective_power, stones.effective_toughness) == (3, 3)
    assert stones.has_type("land"), "still a land"
    assert stones.has_type("artifact")

    game.resolve_cleanup_step(0)

    assert stones.is_creature, "an indefinite animation is not swept at cleanup"
    assert (stones.effective_power, stones.effective_toughness) == (3, 3)
