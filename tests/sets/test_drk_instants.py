"""Per-card tests for The Dark's instants.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# --- G2: auras and land statics (The Dark) ---


def _cast(game: Game, seat: int, name: str) -> None:
    game.enforce_mana_costs = False
    game.cast_from_hand(seat, name)
    game.resolve_top_of_stack()


def test_riptide_taps_only_the_blue_creatures(set_pool):
    """"Tap all blue creatures." The sweep's colour is payload the matcher
    tests through CR 613 layer 5, so it reaches every battlefield and stops at
    the colour boundary rather than at a controller one."""
    pool = set_pool("DRK")
    lea = set_pool("LEA")
    mine = Permanent(card=lea["Phantom Monster"])       # blue
    theirs = Permanent(card=lea["Air Elemental"])       # blue
    red = Permanent(card=lea["Hill Giant"])             # red
    p1 = PlayerState(name="P1", hand=[pool["Riptide"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs, red])
    game = Game(players=[p1, p2])

    _cast(game, 0, "Riptide")

    assert mine.tapped and theirs.tapped, game.log
    assert not red.tapped, "a red creature is not a blue creature"


def test_holy_light_shrinks_everything_that_is_not_white(set_pool):
    """"Nonwhite creatures get -1/-1 until end of turn." The exclusion is
    carried, not dropped: dropped, Holy Light would shrink the white team it is
    printed to spare. A colourless creature is nonwhite (CR 105.2c)."""
    pool = set_pool("DRK")
    lea = set_pool("LEA")
    atq = set_pool("ATQ")
    white = Permanent(card=lea["Savannah Lions"])       # 2/1 white
    red = Permanent(card=lea["Hill Giant"])             # 3/3 red
    artifact = Permanent(card=atq["Ornithopter"])      # colourless artifact creature
    p1 = PlayerState(name="P1", hand=[pool["Holy Light"]], battlefield=[white])
    p2 = PlayerState(name="P2", battlefield=[red, artifact])
    game = Game(players=[p1, p2])
    colourless_before = (artifact.effective_power, artifact.effective_toughness)

    _cast(game, 0, "Holy Light")

    assert (white.effective_power, white.effective_toughness) == (2, 1)
    assert (red.effective_power, red.effective_toughness) == (2, 2), game.log
    assert (artifact.effective_power, artifact.effective_toughness) == (
        colourless_before[0] - 1, colourless_before[1] - 1
    ), "a colourless creature is nonwhite (CR 105.2c)"
