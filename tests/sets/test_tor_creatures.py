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

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, *, hand0=(), hand1=(), gy0=(), bf0=(), bf1=(),
                interactive=()):
    """A two-seat game with costs off, built from card names (TOR over LEA)."""
    pool = {**set_pool("LEA"), **set_pool("TOR")}
    seats = [
        _w1g2_PlayerState(
            name=f"P{seat}", life=20, hand=[pool[n] for n in hand],
            graveyard=[pool[n] for n in gy], library=[pool["Forest"]] * 10,
        )
        for seat, (hand, gy) in enumerate(((hand0, gy0), (hand1, ())))
    ]
    game = _w1g2_Game(players=seats)
    game.enforce_mana_costs = False
    for seat in interactive:
        game.interactive_seats.add(seat)
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g2_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g2_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g2_body(perm):
    return perm.effective_power, perm.effective_toughness


def _w1g2_set_graveyard(set_pool, game, seat, size):
    """Make *seat*'s graveyard *size* Forests and let the statics re-read it."""
    game.players[seat].graveyard[:] = [set_pool("LEA")["Forest"]] * size
    game._recompute_continuous_effects()


# --- Mystic Familiar: a threshold static that grants protection --------------

def test_mystic_familiar_has_protection_from_black_only_at_threshold(set_pool):
    """"Threshold — As long as there are seven or more cards in your
    graveyard, this creature gets +1/+1 and has protection from black." Both
    halves ride one condition, re-read on every ask (CR 611.3a): the black
    removal spell is offered the Familiar at six cards and not at seven."""
    game = _w1g2_table(
        set_pool, hand1=["Terror"], gy0=["Forest"] * 6, bf0=["Mystic Familiar"],
    )
    familiar = _w1g2_on_board(game, 0, "Mystic Familiar")

    def terror_offers():
        spec = game.cast_target_spec(1, game.players[1].hand[0])
        return [target["name"] for target in spec["valid_targets"]]

    assert _w1g2_body(familiar) == (1, 2)
    assert game._protection_qualities(familiar) == set()
    assert terror_offers() == ["Mystic Familiar"]

    _w1g2_set_graveyard(set_pool, game, 0, 7)
    assert _w1g2_body(familiar) == (2, 3)
    assert game._protection_qualities(familiar) == {("color", "B")}
    assert terror_offers() == []

    _w1g2_set_graveyard(set_pool, game, 0, 6)
    assert _w1g2_body(familiar) == (1, 2)
    assert game._protection_qualities(familiar) == set()


def test_mystic_familiar_s_protection_prevents_black_damage_at_threshold(set_pool):
    """CR 702.16e: damage from a black source is prevented — the protection is
    a real one, not a targeting flag."""
    from tests.helpers import _damage_dealt

    game = _w1g2_table(
        set_pool, gy0=["Forest"] * 7, bf0=["Mystic Familiar"],
        bf1=["Black Knight", "Grizzly Bears"],
    )
    familiar = _w1g2_on_board(game, 0, "Mystic Familiar")
    knight = _w1g2_on_board(game, 1, "Black Knight")
    bears = _w1g2_on_board(game, 1, "Grizzly Bears")
    assert _damage_dealt(game, familiar, 2, source=knight) == 0
    assert _damage_dealt(game, familiar, 2, source=bears) == 2


# --- Nantuko Blightcutter: a counted bonus under a threshold -----------------

def test_nantuko_blightcutter_counts_opponents_black_permanents_at_threshold(set_pool):
    """"…gets +1/+1 for each black permanent your opponents control as long as
    there are seven or more cards in your graveyard." Your own black
    permanents and an opponent's nonblack ones do not count; below threshold
    nothing does."""
    game = _w1g2_table(
        set_pool, gy0=["Forest"] * 6,
        bf0=["Nantuko Blightcutter", "Scathe Zombies"],
        bf1=["Scathe Zombies", "Black Knight", "Swamp", "Grizzly Bears"],
    )
    blightcutter = _w1g2_on_board(game, 0, "Nantuko Blightcutter")
    assert _w1g2_body(blightcutter) == (2, 2)

    _w1g2_set_graveyard(set_pool, game, 0, 7)
    assert _w1g2_body(blightcutter) == (4, 4)

    game.remove_from_battlefield(_w1g2_on_board(game, 1, "Black Knight"))
    game._recompute_continuous_effects()
    assert _w1g2_body(blightcutter) == (3, 3), "the count is taken on every refresh"

    _w1g2_set_graveyard(set_pool, game, 0, 6)
    assert _w1g2_body(blightcutter) == (2, 2)


def test_a_counted_conditional_bonus_refuses_an_otherwise_arm_and_a_second_delta():
    """The counted channel has no complement and one instruction cannot carry
    two deltas sized two ways — so either spelling refuses rather than
    dropping half the sentence."""
    from engine.oracle import compile_card_oracle
    from tests.helpers import _mk_card

    def supported(text):
        return compile_card_oracle(
            _mk_card("Counted Thing", "{2}{G}", "Creature — Insect", text, power=2, toughness=2)
        ).supported

    assert supported(
        "This creature gets +1/+1 for each black permanent your opponents "
        "control as long as there are seven or more cards in your graveyard."
    )
    assert not supported(
        "As long as there are seven or more cards in your graveyard, this "
        "creature gets +1/+1 for each black permanent your opponents control "
        "and has flying."
    )

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
