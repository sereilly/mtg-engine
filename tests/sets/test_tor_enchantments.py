"""Torment enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState  # noqa: E402
from engine.activation_prohibitions import activation_prohibition as _w1g6_activation_prohibition  # noqa: E402
from engine.board_payment import board_can_pay as _w1g6_board_can_pay  # noqa: E402
from engine.models import Permanent as _W1G6Permanent  # noqa: E402
from tests.helpers import _nosick as _w1g6_nosick, resolve_stack as _w1g6_resolve_stack  # noqa: E402


def _w1g6_touch_table(set_pool, catalog_by_name, theirs):
    """Seat 0 holds Stupefying Touch and a library; seat 1 has *theirs*."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", hand=[set_pool("TOR")["Stupefying Touch"]],
            library=[catalog_by_name["Island"]] * 3,
        ),
        _W1G6PlayerState(
            name="P2", battlefield=[
                _w1g6_nosick(_W1G6Permanent(card=catalog_by_name[name])) for name in theirs
            ],
        ),
    ])
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()
    return game


def _w1g6_touch(game, host) -> None:
    assert game.cast_from_hand(
        0, "Stupefying Touch",
        target_permanent_ids=[host.permanent_id], target_player_index=1,
    ).supported
    _w1g6_resolve_stack(game)


def test_w1g6_stupefying_touch_draws_and_shuts_off_the_creature_s_abilities(
    set_pool, catalog_by_name,
):
    """"Enchant creature / When this Aura enters, draw a card. / Enchanted
    creature's activated abilities can't be activated." A Prodigal Sorcerer
    under it cannot ping; its controller draws a card as it enters; when the
    Aura leaves, the Sorcerer pings again."""
    game = _w1g6_touch_table(set_pool, catalog_by_name, ["Prodigal Sorcerer"])
    sorcerer = game.players[1].battlefield[0]
    _w1g6_touch(game, sorcerer)
    assert [c.name for c in game.players[0].hand] == ["Island"], "the entry trigger drew"
    refused = game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0)
    assert not refused.supported and "can't be activated" in refused.details
    assert game.players[0].life == 20 and not sorcerer.tapped

    touch = next(p for p in game.controlled_by(0) if p.card.name == "Stupefying Touch")
    game.remove_from_battlefield(touch)
    assert game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 19


def test_w1g6_stupefying_touch_stops_mana_abilities_too(set_pool, catalog_by_name):
    """The card's ruling (2016-06-08): "Unlike many similar abilities,
    Stupefying Touch's last ability stops mana abilities from being
    activated." A Llanowar Elves under it adds nothing through the activation
    path, and the payment planner does not count it. A Forest that Living
    Lands has made a creature is a legal host too, and the land's own tap
    door refuses it as well — the second door to the same ability."""
    game = _w1g6_touch_table(set_pool, catalog_by_name, ["Llanowar Elves", "Forest"])
    elves = game.players[1].battlefield[0]
    game.enforce_mana_costs = True
    assert _w1g6_board_can_pay(game, 1, {"G": 2}, nonland_sources=True)
    game.enforce_mana_costs = False
    _w1g6_touch(game, elves)
    game.enforce_mana_costs = True
    mana = next(a for a in game.usable_abilities_of(elves))
    assert _w1g6_activation_prohibition(game, 1, elves, mana) is not None
    assert not _w1g6_board_can_pay(game, 1, {"G": 2}, nonland_sources=True)
    assert _w1g6_board_can_pay(game, 1, {"G": 1}, nonland_sources=True)
    refused = game.activate_permanent_ability(1, "Llanowar Elves")
    assert not refused.supported
    assert game.players[1].mana_pool["G"] == 0 and not elves.tapped

    game = _w1g6_touch_table(set_pool, catalog_by_name, ["Living Lands", "Forest", "Forest"])
    forest, other = game.players[1].battlefield[1:]
    assert forest.is_creature
    _w1g6_touch(game, forest)
    assert not game.tap_land_for_mana(1, "Forest", permanent_id=forest.permanent_id)
    assert game.players[1].mana_pool["G"] == 0 and not forest.tapped
    assert game.log[-1] == "Forest's activated abilities can't be activated"
    # The Forest beside it, unenchanted, taps as ever.
    assert game.tap_land_for_mana(1, "Forest", permanent_id=other.permanent_id)
    assert game.players[1].mana_pool["G"] == 1

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
