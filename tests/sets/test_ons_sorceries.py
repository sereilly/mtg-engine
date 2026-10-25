"""Onslaught sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
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

from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_card(name, subtype):
    return _w1g4_mk_card(name, "{2}", f"Creature - {subtype}", "")


def _w1g4_creature(name, subtype):
    return _W1G4Permanent(card=_w1g4_card(name, subtype))


def _w1g4_game(set_pool, spell, *, mine=(), theirs=(), my_yard=(), their_yard=(),
               interactive=(), active=0):
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", hand=[set_pool("ONS")[spell]], battlefield=list(mine),
            graveyard=list(my_yard),
        ),
        _W1G4PlayerState(
            name="P2", battlefield=list(theirs), graveyard=list(their_yard),
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = active
    return game


def _w1g4_board(game):
    return {
        seat: sorted(perm.card.name for perm in game.controlled_by(seat))
        for seat in range(len(game.players))
    }


# --- Peer Pressure ------------------------------------------------------------


def test_w1g4_peer_pressure_takes_every_creature_of_a_type_you_lead(set_pool):
    """"Choose a creature type. If you control more creatures of that type than
    each other player, you gain control of all creatures of that type."
    Three Goblins against two: every Goblin is the caster's, indefinitely
    (CR 611.2a), and the Elf beside them stays where it is."""
    game = _w1g4_game(
        set_pool, "Peer Pressure",
        mine=[_w1g4_creature(f"My Goblin {n}", "Goblin") for n in range(3)],
        theirs=[
            _w1g4_creature("Their Goblin A", "Goblin"),
            _w1g4_creature("Their Goblin B", "Goblin"),
            _w1g4_creature("Their Elf", "Elf"),
        ],
        interactive=[0],
    )
    assert game.cast_from_hand(0, "Peer Pressure").supported
    assert [c.kind for c in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g4_resolve_stack(game)

    assert _w1g4_board(game) == {
        0: ["My Goblin 0", "My Goblin 1", "My Goblin 2", "Their Goblin A",
            "Their Goblin B"],
        1: ["Their Elf"],
    }


def test_w1g4_peer_pressure_a_tie_is_not_more(set_pool):
    """"More … than each other player" is strict: two Goblins against two is no
    lead, so nothing changes hands."""
    game = _w1g4_game(
        set_pool, "Peer Pressure",
        mine=[_w1g4_creature("My Goblin A", "Goblin"), _w1g4_creature("My Goblin B", "Goblin")],
        theirs=[
            _w1g4_creature("Their Goblin A", "Goblin"),
            _w1g4_creature("Their Goblin B", "Goblin"),
        ],
        interactive=[0],
    )
    game.cast_from_hand(0, "Peer Pressure")
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g4_resolve_stack(game)

    assert _w1g4_board(game) == {
        0: ["My Goblin A", "My Goblin B"], 1: ["Their Goblin A", "Their Goblin B"],
    }


def test_w1g4_peer_pressure_counts_only_the_named_type(set_pool):
    """The comparison is over creatures *of that type*: a bigger board of
    other creatures is no lead. Naming Zombie with one Zombie against the
    opponent's two takes nothing, though the caster has more creatures."""
    game = _w1g4_game(
        set_pool, "Peer Pressure",
        mine=[_w1g4_creature("My Zombie", "Zombie")]
        + [_w1g4_creature(f"My Elf {n}", "Elf") for n in range(4)],
        theirs=[_w1g4_creature("Their Zombie A", "Zombie"), _w1g4_creature("Their Zombie B", "Zombie")],
        interactive=[0],
    )
    game.cast_from_hand(0, "Peer Pressure")
    assert game.confirm_creature_type_choice(0, "zombie")
    _w1g4_resolve_stack(game)

    assert _w1g4_board(game)[1] == ["Their Zombie A", "Their Zombie B"]


def test_w1g4_peer_pressure_default_names_the_lead_that_takes_the_most(set_pool):
    """A seat nobody asks names, among the types it strictly leads, the one the
    others hold the most of — here Elves (2 against 1) over the Zombies it
    trails in. Naming the opponents' commonest type, the sweep default, would
    take nothing."""
    game = _w1g4_game(
        set_pool, "Peer Pressure",
        mine=[_w1g4_creature("My Elf A", "Elf"), _w1g4_creature("My Elf B", "Elf")],
        theirs=[_w1g4_creature("Their Elf", "Elf")]
        + [_w1g4_creature(f"Their Zombie {n}", "Zombie") for n in range(3)],
    )
    game.cast_from_hand(0, "Peer Pressure")
    _w1g4_resolve_stack(game)

    assert "Their Elf" in _w1g4_board(game)[0]
    assert all("Zombie" not in name for name in _w1g4_board(game)[0])


# --- Harsh Mercy ----------------------------------------------------------------


def test_w1g4_harsh_mercy_asks_each_player_in_turn_order_and_spares_the_union(set_pool):
    """"Each player chooses a creature type. Destroy all creatures that aren't
    of a type chosen this way." CR 101.4: the active player chooses first, then
    the next in turn order — one prompt at a time, the second armed only once
    the first is answered and carrying it (CR 101.4b) — and the sweep runs once,
    after the last answer."""
    game = _w1g4_game(
        set_pool, "Harsh Mercy",
        mine=[_w1g4_creature("My Elf", "Elf"), _w1g4_creature("My Goblin", "Goblin")],
        theirs=[_w1g4_creature("Their Zombie", "Zombie"), _w1g4_creature("Their Bear", "Bear")],
        interactive=[0, 1],
    )
    assert game.cast_from_hand(0, "Harsh Mercy").supported
    owed = [(c.kind, c.player_index) for c in game.pending_choices]
    assert owed == [("creature_type_choice", 0)], "only the active player is asked first"

    assert game.confirm_creature_type_choice(0, "elf")
    assert [(c.player_index, c.data.get("chosen_so_far")) for c in game.pending_choices] == [
        (1, ["elf"])
    ]
    assert len(_w1g4_board(game)[0]) == 2, "nothing is destroyed before the last answer"

    assert game.confirm_creature_type_choice(1, "zombie")
    _w1g4_resolve_stack(game)
    assert _w1g4_board(game) == {0: ["My Elf"], 1: ["Their Zombie"]}


def test_w1g4_harsh_mercy_starts_with_the_active_player_not_the_caster(set_pool):
    """The order is APNAP's, not the caster's: on the opponent's turn (an
    instant-speed copy of the question, set up by making P2 active) P2 is asked
    first."""
    game = _w1g4_game(
        set_pool, "Harsh Mercy",
        mine=[_w1g4_creature("My Elf", "Elf")],
        theirs=[_w1g4_creature("Their Zombie", "Zombie")],
        interactive=[0, 1], active=1,
    )
    game.cast_from_hand(0, "Harsh Mercy")
    assert [c.player_index for c in game.pending_choices] == [1]


def test_w1g4_harsh_mercy_destroyed_creatures_cannot_be_regenerated(set_pool):
    """"They can't be regenerated." A regeneration shield on a creature of an
    unchosen type does not save it (CR 701.19c)."""
    regenerator = _w1g4_creature("Shielded Bear", "Bear")
    regenerator.regeneration_shield = 1
    game = _w1g4_game(
        set_pool, "Harsh Mercy",
        mine=[_w1g4_creature("My Elf", "Elf")], theirs=[regenerator],
        interactive=[0, 1],
    )
    game.cast_from_hand(0, "Harsh Mercy")
    assert game.confirm_creature_type_choice(0, "elf")
    assert game.confirm_creature_type_choice(1, "elf")
    _w1g4_resolve_stack(game)

    assert _w1g4_board(game) == {0: ["My Elf"], 1: []}


def test_w1g4_harsh_mercy_defaults_spare_each_seats_own_and_see_earlier_answers(set_pool):
    """Nobody asked: each seat names the type that saves the most of its own and
    the fewest of the others', counting what the seats before it already saved.
    P1's Elves (2) are worth more than its Goblin; P2's Zombies are its own,
    and the Goblins both sides hold die with nobody naming them."""
    game = _w1g4_game(
        set_pool, "Harsh Mercy",
        mine=[_w1g4_creature("My Elf A", "Elf"), _w1g4_creature("My Elf B", "Elf"),
              _w1g4_creature("My Goblin", "Goblin")],
        theirs=[_w1g4_creature("Their Zombie A", "Zombie"),
                _w1g4_creature("Their Zombie B", "Zombie"),
                _w1g4_creature("Their Goblin", "Goblin")],
    )
    game.cast_from_hand(0, "Harsh Mercy")
    _w1g4_resolve_stack(game)

    assert _w1g4_board(game) == {
        0: ["My Elf A", "My Elf B"], 1: ["Their Zombie A", "Their Zombie B"],
    }
    chose = [line for line in game.log if line.startswith("Harsh Mercy: P")]
    assert chose == [
        "Harsh Mercy: P1 chooses a creature type", "Harsh Mercy: P1 chose elf",
        "Harsh Mercy: P2 chooses a creature type", "Harsh Mercy: P2 chose zombie",
    ]


# --- Patriarch's Bidding --------------------------------------------------------


def test_w1g4_patriarchs_bidding_returns_every_chosen_type_from_each_graveyard(set_pool):
    """"Each player chooses a creature type. Each player returns all creature
    cards of a type chosen this way from their graveyard to the battlefield."
    The 2021-06-18 ruling: the active player chooses first, then each other
    player in turn order, and every creature card having one or more of the
    chosen types returns — so P2's Elf comes back on P1's choice, under its
    owner (CR 110.2a), and the unnamed Goblins stay."""
    game = _w1g4_game(
        set_pool, "Patriarch's Bidding",
        my_yard=[_w1g4_card("My Elf", "Elf"), _w1g4_card("My Goblin", "Goblin")],
        their_yard=[_w1g4_card("Their Zombie", "Zombie"), _w1g4_card("Their Elf", "Elf"),
                    _w1g4_card("Their Goblin", "Goblin")],
        interactive=[0, 1],
    )
    assert game.cast_from_hand(0, "Patriarch's Bidding").supported
    assert [c.player_index for c in game.pending_choices] == [0]
    assert game.confirm_creature_type_choice(0, "elf")
    assert [c.player_index for c in game.pending_choices] == [1]
    assert game.confirm_creature_type_choice(1, "zombie")
    _w1g4_resolve_stack(game)

    assert _w1g4_board(game) == {0: ["My Elf"], 1: ["Their Elf", "Their Zombie"]}
    assert [card.name for card in game.players[0].graveyard] == [
        "My Goblin", "Patriarch's Bidding",
    ]
    assert [card.name for card in game.players[1].graveyard] == ["Their Goblin"]


def test_w1g4_patriarchs_bidding_a_type_already_chosen_may_be_chosen_again(set_pool):
    """"Any player may choose a creature type that's already been chosen. Doing
    so won't affect which creature cards are returned." (2021-06-18.) The second
    seat is offered the whole catalog, the first answer included."""
    game = _w1g4_game(
        set_pool, "Patriarch's Bidding",
        my_yard=[_w1g4_card("My Elf", "Elf")],
        their_yard=[_w1g4_card("Their Goblin", "Goblin")],
        interactive=[0, 1],
    )
    game.cast_from_hand(0, "Patriarch's Bidding")
    assert game.confirm_creature_type_choice(0, "elf")
    assert game.confirm_creature_type_choice(1, "elf")
    _w1g4_resolve_stack(game)

    assert _w1g4_board(game) == {0: ["My Elf"], 1: []}


def test_w1g4_patriarchs_bidding_default_names_each_seats_own_graveyard_type(set_pool):
    """Nobody asked: each seat names the type most common among its *own*
    graveyard's creature cards, net of the others'. Counted in the graveyards,
    not on the battlefield, because that is where the sentence looks."""
    game = _w1g4_game(
        set_pool, "Patriarch's Bidding",
        mine=[_w1g4_creature("Board Goblin", "Goblin")],
        my_yard=[_w1g4_card("My Elf A", "Elf"), _w1g4_card("My Elf B", "Elf")],
        their_yard=[_w1g4_card("Their Zombie", "Zombie")],
    )
    game.cast_from_hand(0, "Patriarch's Bidding")
    _w1g4_resolve_stack(game)

    assert _w1g4_board(game) == {
        0: ["Board Goblin", "My Elf A", "My Elf B"], 1: ["Their Zombie"],
    }


def test_w1g4_each_player_choosing_compiles_to_one_step_per_record(set_pool):
    """The two sentences are two steps over one record: the each-player choice
    writes ``CHOSEN_CREATURE_TYPES_THIS_WAY`` and the sweep names it, as an
    exclusion (Harsh Mercy) or a union (Patriarch's Bidding)."""
    for name, key in (("Harsh Mercy", "exclude_subtypes_from"),
                      ("Patriarch's Bidding", "subtype_filter_from")):
        program = _w1g4_compile(set_pool("ONS")[name])
        assert program.supported, (name, program.reason)
        choose, sweep = program.instructions[0].payload["steps"]
        assert choose.kind == "each_player_chooses_creature_type"
        assert sweep.payload[key] == choose.payload["result_key"]


# --- Aphetto Dredging ------------------------------------------------------------


def test_w1g4_aphetto_dredging_refuses_rather_than_dropping_its_narrowing(set_pool):
    """"Return up to three target creature cards **of the creature type of your
    choice** from your graveyard to your hand." The type is announced before
    the targets (2004-10-04 ruling), which nothing here performs yet — and at
    ingest the phrase was dropped, so the spell returned any three creature
    cards while reporting supported. Refused, with the reason naming the
    narrowing, until the announcement exists."""
    program = _w1g4_compile(set_pool("ONS")["Aphetto Dredging"])
    assert not program.supported

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


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================
