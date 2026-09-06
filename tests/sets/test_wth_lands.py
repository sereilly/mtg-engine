"""Weatherlight lands.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W2G1: costs charged and permissions granted ---
from engine import Game, PlayerState
from engine.cast_timing import casts_at_instant_speed, expire_end_of_turn
from engine.models import Permanent


def _w2g1_two_seats():
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.turn = 3
    return game, p1, p2


def test_winding_canyons_gives_creature_spells_flash_timing(
    set_pool, catalog_by_name
):
    """"{2}, {T}: You may cast creature spells this turn as though they had
    flash." (CR 702.8a through CR 611.1.)

    The line compiled to an ability part with no instruction, so the land read
    supported — its mana ability is enough — while the ability it is played for
    did nothing at all. The grant is state rather than text, so no reading of
    the *card* can see it: both timing gates ask
    ``cast_timing.casts_at_instant_speed``, which is why it is the one place
    the board is consulted.
    """
    pool = set_pool("WTH")
    game, p1, _p2 = _w2g1_two_seats()
    p1.battlefield.append(Permanent(card=pool["Winding Canyons"]))
    bears = catalog_by_name["Grizzly Bears"]

    game.active_player_index = 1
    assert not casts_at_instant_speed(bears, game, 0)

    game.active_player_index = 0
    result = game.activate_permanent_ability(
        0, "Winding Canyons", ability_index=1
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result.details

    game.active_player_index = 1
    assert casts_at_instant_speed(bears, game, 0), "on the opponent's turn"
    assert not casts_at_instant_speed(bears, game, 1), "and only for the granter"


def test_winding_canyons_covers_only_the_type_it_names(set_pool, catalog_by_name):
    """"**Creature** spells", so an artifact keeps sorcery timing. A grant that
    dropped the union would be a strictly different card — every spell in the
    seat's hand castable on anyone's turn."""
    pool = set_pool("WTH")
    game, p1, _p2 = _w2g1_two_seats()
    p1.battlefield.append(Permanent(card=pool["Winding Canyons"]))
    game.activate_permanent_ability(0, "Winding Canyons", ability_index=1)
    while game.stack:
        game.resolve_top_of_stack()

    assert casts_at_instant_speed(catalog_by_name["Grizzly Bears"], game, 0)
    assert not casts_at_instant_speed(catalog_by_name["Black Lotus"], game, 0)


def test_winding_canyons_grant_ends_at_cleanup(set_pool, catalog_by_name):
    """CR 514.2: "this turn" ends at the cleanup step, beside the zone
    permissions swept there. A grant that outlived its turn would make every
    later turn's creatures instant-speed off one activation."""
    pool = set_pool("WTH")
    game, p1, _p2 = _w2g1_two_seats()
    p1.battlefield.append(Permanent(card=pool["Winding Canyons"]))
    game.activate_permanent_ability(0, "Winding Canyons", ability_index=1)
    while game.stack:
        game.resolve_top_of_stack()
    assert casts_at_instant_speed(catalog_by_name["Grizzly Bears"], game, 0)

    expire_end_of_turn(game)

    assert not casts_at_instant_speed(catalog_by_name["Grizzly Bears"], game, 0)
