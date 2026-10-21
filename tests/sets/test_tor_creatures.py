"""Torment creatures (legendary ones too).

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
from engine import ai_policy as _w1g6_ai_policy  # noqa: E402
from engine.cast_prohibitions import cast_prohibition as _w1g6_cast_prohibition  # noqa: E402
from engine.models import Permanent as _W1G6Permanent  # noqa: E402
from tests.helpers import _nosick as _w1g6_nosick, resolve_stack as _w1g6_resolve_stack  # noqa: E402


def _w1g6_llawan_table(set_pool, catalog_by_name):
    """Seat 0 holds Llawan; seat 1 has a blue creature, a green one and a
    blue-green one on the battlefield. Mana off."""
    llawan = set_pool("TOR")["Llawan, Cephalid Empress"]
    theirs = [
        _w1g6_nosick(_W1G6Permanent(card=catalog_by_name[name]))
        for name in ("Merfolk of the Pearl Trident", "Grizzly Bears", "Gaea's Skyfolk")
    ]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", hand=[llawan]),
        _W1G6PlayerState(name="P2", battlefield=theirs),
    ])
    game.enforce_mana_costs = False
    return game


def test_w1g6_llawan_bounces_the_blue_creatures_and_bans_the_blue_creature_spells(
    set_pool, catalog_by_name,
):
    """"When Llawan enters, return all blue creatures your opponents control to
    their owners' hands. Your opponents can't cast blue creature spells."

    The entry trigger takes the blue creatures and the gold one with blue in
    it (CR 105.2b), and leaves the green one. Then the ban: the opponent
    cannot cast the creatures it just got back — the engine refuses, the AI
    does not propose — but can cast a creature that is not blue, and Llawan's
    own controller casts blue creatures freely ("your opponents")."""
    game = _w1g6_llawan_table(set_pool, catalog_by_name)
    assert game.cast_from_hand(0, "Llawan, Cephalid Empress").supported
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert sorted(c.name for c in game.players[1].hand) == [
        "Gaea's Skyfolk", "Merfolk of the Pearl Trident",
    ]

    for name in ("Merfolk of the Pearl Trident", "Gaea's Skyfolk"):
        card = next(c for c in game.players[1].hand if c.name == name)
        found = _w1g6_cast_prohibition(game, 1, card)
        assert found is not None and found.source == "Llawan, Cephalid Empress", name
        assert not _w1g6_ai_policy._can_cast_with_targets(game, 1, card)
        refused = game.cast_from_hand(1, name)
        assert not refused.supported and "Llawan" in refused.details
        assert name in [c.name for c in game.players[1].hand]

    # A creature that is not blue is not a blue creature spell.
    game.players[1].hand.append(catalog_by_name["Grizzly Bears"])
    assert game.cast_from_hand(1, "Grizzly Bears").supported
    _w1g6_resolve_stack(game)
    # A blue spell that is not a creature spell is not one either.
    game.players[1].hand.append(catalog_by_name["Ancestral Recall"])
    assert game.cast_from_hand(1, "Ancestral Recall", target_player_index=1).supported
    _w1g6_resolve_stack(game)

    # Llawan's controller is not its opponent.
    game.players[0].hand.append(catalog_by_name["Merfolk of the Pearl Trident"])
    assert game.cast_from_hand(0, "Merfolk of the Pearl Trident").supported
    _w1g6_resolve_stack(game)
    assert "Merfolk of the Pearl Trident" in [p.card.name for p in game.controlled_by(0)]

    # Gone, Llawan bans nothing.
    llawan = next(p for p in game.controlled_by(0) if p.card.name.startswith("Llawan"))
    game.remove_from_battlefield(llawan)
    assert game.cast_from_hand(1, "Merfolk of the Pearl Trident").supported


def test_w1g6_llawan_binds_whoever_is_her_controller_s_opponent(set_pool, catalog_by_name):
    """The ban is relative to Llawan's *controller* (CR 109.5, CR 102.3): an
    opponent who takes her is freed and her owner is bound."""
    game = _w1g6_llawan_table(set_pool, catalog_by_name)
    llawan = _w1g6_nosick(_W1G6Permanent(card=set_pool("TOR")["Llawan, Cephalid Empress"]))
    game.players[1].battlefield.append(llawan)
    merfolk = catalog_by_name["Merfolk of the Pearl Trident"]
    assert _w1g6_cast_prohibition(game, 0, merfolk) is not None
    assert _w1g6_cast_prohibition(game, 1, merfolk) is None

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
