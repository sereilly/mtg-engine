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
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


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


# --- The drive list: threshold cards supported on arrival, given a game ------

import pytest as _w1g2_pytest  # noqa: E402

_W1G2_POSSESSED = (
    # (card, printed colour, a creature of the colour its ability names)
    ("Possessed Aven", "U", "Prodigal Sorcerer"),
    ("Possessed Centaur", "G", "Grizzly Bears"),
    ("Possessed Barbarian", "R", "Hill Giant"),
    ("Possessed Nomad", "W", "Savannah Lions"),
)


@_w1g2_pytest.mark.parametrize(
    "name, printed_color, victim", _W1G2_POSSESSED, ids=[r[0] for r in _W1G2_POSSESSED]
)
def test_the_possessed_are_black_bigger_and_armed_only_at_threshold(
    set_pool, name, printed_color, victim,
):
    """"…this creature gets +1/+1, is black, and has "{2}{B}, {T}: Destroy
    target <colour> creature."" — three layers (7c, 5, 6) on one condition.
    Below threshold the granted ability is not there to activate; at
    threshold its picker offers only the colour it names."""
    def board(graveyard_size):
        game = _w1g2_table(
            set_pool, gy0=["Forest"] * graveyard_size, bf0=[name],
            bf1=[victim, "Scathe Zombies"],
        )
        return game, _w1g2_on_board(game, 0, name)

    game, possessed = board(6)
    assert _w1g2_body(possessed) == (3, 3)
    assert game._effective_colors(possessed) == {printed_color}
    target = _w1g2_on_board(game, 1, victim)
    assert not game.activate_permanent_ability(
        0, name, target_permanent_ids=[target.permanent_id],
    ).supported
    assert _w1g2_on_board(game, 1, victim) is not None

    game, possessed = board(7)
    assert _w1g2_body(possessed) == (4, 4)
    assert game._effective_colors(possessed) == {"B"}
    slot = game.players[0].battlefield.index(possessed)
    assert [t["name"] for t in game.activation_target_spec(0, slot)["valid_targets"]] == [
        victim
    ]
    zombies = _w1g2_on_board(game, 1, "Scathe Zombies")
    assert not game.activate_permanent_ability(
        0, name, target_permanent_ids=[zombies.permanent_id],
    ).supported, "a black creature is not the colour the ability names"
    target = _w1g2_on_board(game, 1, victim)
    assert game.activate_permanent_ability(
        0, name, target_permanent_ids=[target.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_on_board(game, 1, victim) is None and possessed.tapped


@_w1g2_pytest.mark.parametrize("name, below, at", [
    ("Seton's Scout", (2, 1), (4, 3)),
    ("Nantuko Calmer", (2, 3), (3, 4)),
])
def test_a_threshold_size_bonus_follows_the_graveyard(set_pool, name, below, at):
    game = _w1g2_table(set_pool, gy0=["Forest"] * 6, bf0=[name])
    creature = _w1g2_on_board(game, 0, name)
    assert _w1g2_body(creature) == below
    _w1g2_set_graveyard(set_pool, game, 0, 7)
    assert _w1g2_body(creature) == at


def _w1g2_cast_at(set_pool, name, graveyard_size, *, bf1=("Grizzly Bears",)):
    game = _w1g2_table(
        set_pool, hand0=[name], gy0=["Forest"] * graveyard_size,
        bf0=["Savannah Lions"], bf1=bf1,
    )
    assert game.cast_from_hand(0, name).supported
    _w1g2_resolve_stack(game)
    return game


def test_a_granted_entry_trigger_is_there_only_if_threshold_holds_as_it_enters(set_pool):
    """"…this creature has "When this creature enters, …"" — the static
    applies as the creature enters (CR 614.12's moment), so with seven cards
    already in the graveyard the trigger fires, and with six it does not
    exist to fire. Four cards, four effects."""
    # Centaur Chieftain: creatures you control get +1/+1 and gain trample.
    quiet = _w1g2_cast_at(set_pool, "Centaur Chieftain", 6)
    assert _w1g2_body(_w1g2_on_board(quiet, 0, "Savannah Lions")) == (2, 1)
    loud = _w1g2_cast_at(set_pool, "Centaur Chieftain", 7)
    lions = _w1g2_on_board(loud, 0, "Savannah Lions")
    assert _w1g2_body(lions) == (3, 2) and loud._has_keyword(lions, "trample")
    assert _w1g2_body(_w1g2_on_board(loud, 1, "Grizzly Bears")) == (2, 2)

    # Pardic Arsonist: 3 damage to any target.
    assert [p.life for p in _w1g2_cast_at(set_pool, "Pardic Arsonist", 6).players] == [20, 20]
    assert [p.life for p in _w1g2_cast_at(set_pool, "Pardic Arsonist", 7).players] == [20, 17]

    # Teroh's Vanguard: creatures you control gain protection from black.
    quiet = _w1g2_cast_at(set_pool, "Teroh's Vanguard", 6)
    assert quiet._protection_qualities(_w1g2_on_board(quiet, 0, "Savannah Lions")) == set()
    loud = _w1g2_cast_at(set_pool, "Teroh's Vanguard", 7)
    assert loud._protection_qualities(_w1g2_on_board(loud, 0, "Savannah Lions")) == {
        ("color", "B")
    }

    # Gloomdrifter: nonblack creatures get -2/-2 — its own controller's too.
    quiet = _w1g2_cast_at(
        set_pool, "Gloomdrifter", 6, bf1=("Grizzly Bears", "Scathe Zombies"),
    )
    assert _w1g2_on_board(quiet, 0, "Savannah Lions") is not None
    loud = _w1g2_cast_at(
        set_pool, "Gloomdrifter", 7, bf1=("Grizzly Bears", "Scathe Zombies"),
    )
    assert _w1g2_on_board(loud, 0, "Savannah Lions") is None
    assert _w1g2_on_board(loud, 1, "Grizzly Bears") is None
    assert _w1g2_on_board(loud, 1, "Scathe Zombies") is not None
    assert _w1g2_body(_w1g2_on_board(loud, 0, "Gloomdrifter")) == (2, 2)


def test_boneshard_slasher_sacrifices_itself_when_targeted_at_threshold(set_pool):
    """"…gets +2/+2 and has "When this creature becomes the target of a spell
    or ability, sacrifice it."" — and the spell aimed at it then has no legal
    target (CR 608.2b)."""
    for size, survives in ((6, True), (7, False)):
        game = _w1g2_table(
            set_pool, hand1=["Lightning Bolt"], gy0=["Forest"] * size,
            bf0=["Boneshard Slasher"],
        )
        slasher = _w1g2_on_board(game, 0, "Boneshard Slasher")
        assert _w1g2_body(slasher) == ((1, 1) if survives else (3, 3))
        assert game.queue_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[slasher.permanent_id],
        ).supported
        _w1g2_resolve_stack(game)
        game.check_state_based_actions()
        # A 1/1 dies to the Bolt; the 3/3 is sacrificed before the Bolt lands.
        assert _w1g2_on_board(game, 0, "Boneshard Slasher") is None
        assert any("was sacrificed" in line for line in game.log) is not survives
        assert any("every target is illegal" in line for line in game.log) is not survives


def test_reborn_hero_may_come_back_only_if_it_died_at_threshold(set_pool):
    """CR 603.10a: a dies trigger looks back in time, so whether the Hero had
    the granted ability is asked of the board just before it died — six cards
    (then seven with the Hero itself) is no trigger; seven is."""
    for size, returns in ((6, False), (7, True)):
        game = _w1g2_table(
            set_pool, hand1=["Terror"], gy0=["Forest"] * size,
            bf0=["Reborn Hero", "Plains", "Plains"],
        )
        hero = _w1g2_on_board(game, 0, "Reborn Hero")
        assert game.cast_from_hand(
            1, "Terror", target_permanent_ids=[hero.permanent_id],
        ).supported
        _w1g2_resolve_stack(game)
        game.auto_resolve_pending_choices()
        _w1g2_resolve_stack(game)
        assert (_w1g2_on_board(game, 0, "Reborn Hero") is not None) is returns

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
