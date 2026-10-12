"""Odyssey enchantments.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_table(set_pool, hand=(), mana=None):
    """A two-seat game with mana costs enforced; *hand* names Odyssey cards
    (or Alpha ones) in seat 0's hand."""
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[ody[name] if name in ody else lea[name] for name in hand],
        ),
        _W1G1PlayerState("Opponent", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    return game  # _w1g1_table (enchantments)


def _w1g1_put(game, set_pool, seat, name):
    """*name* (Odyssey first, then Alpha) onto *seat*'s battlefield, able to
    act this turn."""
    ody = set_pool("ODY")
    card = ody[name] if name in ody else set_pool("LEA")[name]
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (enchantments)


def _w1g1_graveyard(game, set_pool, seat, count):
    """Give *seat* exactly *count* cards in its graveyard, then let the
    state-based sweep recompute (CR 611.3a)."""
    game.players[seat].graveyard[:] = [set_pool("LEA")["Forest"]] * count
    game.check_state_based_actions()  # _w1g1_graveyard (enchantments)


def _w1g1_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


def _w1g1_enchant(game, name, host):
    """Cast the Aura *name* from seat 0's hand onto *host* and resolve it."""
    result = game.cast_from_hand(0, name, target_permanent_ids=[host.permanent_id])
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    (aura,) = [p for p in game.all_permanents() if p.card.name == name]
    assert aura.metadata.get("attached_to") is host
    return aura  # _w1g1_enchant (enchantments)


def test_w1g1_kamahls_desire_counts_the_graveyard_of_whoever_controls_the_aura(
    set_pool,
):
    """"Enchanted creature has first strike. Threshold — Enchanted creature
    gets +3/+0 as long as there are seven or more cards in your graveyard."
    Cast on an *opponent's* creature: first strike at once, and the +3/+0
    follows the Aura's controller's graveyard (CR 109.5) — seven cards in the
    creature's controller's graveyard do nothing."""
    assert _w1g1_compile(set_pool("ODY")["Kamahl's Desire"]).supported
    game = _w1g1_table(set_pool, ["Kamahl's Desire"], {"R": 2})
    theirs = _w1g1_put(game, set_pool, 1, "Grizzly Bears")
    _w1g1_enchant(game, "Kamahl's Desire", theirs)
    assert game._has_keyword(theirs, "first strike") and _w1g1_pt(theirs) == (2, 2)

    _w1g1_graveyard(game, set_pool, 1, 7)
    assert _w1g1_pt(theirs) == (2, 2)

    _w1g1_graveyard(game, set_pool, 1, 0)
    _w1g1_graveyard(game, set_pool, 0, 7)
    assert _w1g1_pt(theirs) == (5, 2)

    _w1g1_graveyard(game, set_pool, 0, 6)
    assert _w1g1_pt(theirs) == (2, 2) and game._has_keyword(theirs, "first strike")


def test_w1g1_aboshans_desire_adds_shroud_to_flying_only_with_threshold(set_pool):
    """"Enchanted creature has flying. Threshold — Enchanted creature has
    shroud as long as there are seven or more cards in your graveyard." Flying
    is unconditional; shroud comes and goes with the count, and while it is
    there a spell aimed at the creature is refused with nothing paid."""
    assert _w1g1_compile(set_pool("ODY")["Aboshan's Desire"]).supported
    game = _w1g1_table(
        set_pool, ["Aboshan's Desire", "Lightning Bolt"], {"U": 1, "R": 1},
    )
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
    _w1g1_enchant(game, "Aboshan's Desire", bears)
    assert game._has_keyword(bears, "flying") and not game._has_keyword(bears, "shroud")

    _w1g1_graveyard(game, set_pool, 0, 7)
    assert game._has_keyword(bears, "flying") and game._has_keyword(bears, "shroud")
    refused = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    )
    assert not refused.supported
    assert game.players[0].mana_pool["R"] == 1, "nothing was paid for the refused cast"

    _w1g1_graveyard(game, set_pool, 0, 6)
    assert game._has_keyword(bears, "flying") and not game._has_keyword(bears, "shroud")
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported

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

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
