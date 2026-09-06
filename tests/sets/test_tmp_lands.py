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


# --- W2G3: Reflecting Pool and CR 106.7's "could produce" ---

from engine import Game, PlayerState
from engine.models import Permanent


def _w2g3l_game(mine, theirs=()):
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=c) for c in mine])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=c) for c in theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2


def _tap_the_pool(game, player, index=0):
    for permanent in player.battlefield:
        permanent.tapped = False
    result = game.activate_permanent_ability(
        0, "Reflecting Pool", permanent_index=index
    )
    game._settle()
    return result, {sym: n for sym, n in player.mana_pool.items() if n}


def test_reflecting_pool_alone_produces_nothing(set_pool):
    """"{T}: Add one mana of any type that a land you control could produce."

    The trap, and it is in the ingested data rather than in the sentence:
    Scryfall records Reflecting Pool's own ``produced_mana`` as all five
    colours, so the obvious union over "lands you control" reads the Pool
    itself and taps for anything. CR 106.7 says the opposite — "if that
    permanent wouldn't produce any mana under these conditions, or no type of
    mana can be defined this way, there's no type of mana it could produce" —
    and the rule's own example is a board of nothing but these cards.
    """
    game, p1, _ = _w2g3l_game([set_pool("TMP")["Reflecting Pool"]])

    result, pool = _tap_the_pool(game, p1)

    assert result.supported, result.details
    assert pool == {}, game.log


def test_two_reflecting_pools_still_produce_nothing(set_pool):
    """CR 106.7's example spelled with the card this pool actually has: two
    derived producers reading each other define no type."""
    pools = [set_pool("TMP")["Reflecting Pool"]] * 2
    game, p1, _ = _w2g3l_game(pools)

    _, produced = _tap_the_pool(game, p1)

    assert produced == {}


def test_reflecting_pool_copies_a_land_you_control(set_pool, catalog_by_name):
    """One Forest is the whole of what it can offer."""
    game, p1, _ = _w2g3l_game(
        [set_pool("TMP")["Reflecting Pool"], catalog_by_name["Forest"]]
    )

    _, produced = _tap_the_pool(game, p1)

    assert produced == {"G": 1}, game.log


def test_reflecting_pool_ignores_an_opponents_lands(set_pool, catalog_by_name):
    """"a land **you control**" — the narrowing, and the direction it must not
    be dropped in: read as any land, the Pool would tap for whatever the board
    across the table can make."""
    game, p1, _ = _w2g3l_game(
        [set_pool("TMP")["Reflecting Pool"]], [catalog_by_name["Forest"]]
    )

    _, produced = _tap_the_pool(game, p1)

    assert produced == {}, game.log


def test_fellwar_stone_stops_reading_a_reflecting_pool_as_five_colours(
    set_pool, catalog_by_name
):
    """The already-supported card this one silently broke.

    Fellwar Stone asks the same CR 106.7 question of the other board, and it
    answered it by scanning Scryfall's ``produced_mana`` — right for every land
    that says what it makes, wrong for one that derives it. Reflecting Pool is
    the first such land in this pool, so an opponent's lone Pool would have made
    the Stone tap for any colour. Both cards read one implementation of the rule
    now.
    """
    game, p1, _ = _w2g3l_game(
        [catalog_by_name["Fellwar Stone"]], [set_pool("TMP")["Reflecting Pool"]]
    )
    for permanent in p1.battlefield:
        permanent.tapped = False

    game.activate_permanent_ability(0, "Fellwar Stone", permanent_index=0)
    game._settle()

    assert {sym: n for sym, n in p1.mana_pool.items() if n} == {}, game.log


def test_fellwar_stone_still_copies_an_ordinary_land(catalog_by_name):
    """And the regression control: the Stone's own card, unchanged."""
    game, p1, _ = _w2g3l_game(
        [catalog_by_name["Fellwar Stone"]], [catalog_by_name["Forest"]]
    )
    for permanent in p1.battlefield:
        permanent.tapped = False

    game.activate_permanent_ability(0, "Fellwar Stone", permanent_index=0)
    game._settle()

    assert {sym: n for sym, n in p1.mana_pool.items() if n} == {"G": 1}, game.log
