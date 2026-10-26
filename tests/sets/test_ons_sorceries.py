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

# --- W1G3: cycling triggers (CR 702.29c) and the cycling sorceries ----------
#
# The instants' section of `test_ons_instants.py` says how these are driven:
# cycle, resolve the trigger alone (the cycling ability is under it, so nothing
# is drawn yet), read the board, then let the draw resolve.
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import _mk_creature_card, resolve_stack


def _w1g3_table(set_pool, *hand, library=5):
    ons = set_pool("ONS")
    filler = ons["Plains"]
    alice = PlayerState(
        name="Alice", hand=[ons[name] for name in hand], library=[filler] * library,
    )
    bob = PlayerState(name="Bob", library=[filler] * library)
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    return game, alice, bob


def _w1g3_put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g3_cycle_and_resolve_trigger(game, name):
    assert game.activate_from_hand(0, name).supported
    assert game.stack[-1].ability_text.startswith("When you cycle this card")
    assert game.stack[-2].ability_text.endswith("Discard this card: Draw a card.")
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    if offer is not None:
        assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()
    assert len(game.stack) == 1, "the cycling ability is still waiting to draw"


def test_w1g3_dirge_of_dread_cycled_gives_one_creature_fear(set_pool):
    """"…you may have target creature gain fear until end of turn." — one
    creature, not the spell's "all creatures"."""
    game, alice, _bob = _w1g3_table(set_pool, "Dirge of Dread")
    mine = _w1g3_put(game, 0, _mk_creature_card("Bear", 2, 2))
    other = _w1g3_put(game, 1, _mk_creature_card("Wall", 0, 4))

    _w1g3_cycle_and_resolve_trigger(game, "Dirge of Dread")
    assert mine.has_keyword("fear")
    assert not other.has_keyword("fear")
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]
    game.resolve_cleanup_step(0)
    assert not mine.has_keyword("fear")


def test_w1g3_slice_and_dice_cycled_deals_1_to_each_creature(set_pool):
    """"…you may have it deal 1 damage to each creature." Both boards, the
    card in the graveyard as the source: the 1/1s die, the 2/2 lives."""
    game, alice, bob = _w1g3_table(set_pool, "Slice and Dice")
    small_mine = _w1g3_put(game, 0, _mk_creature_card("Mine", 1, 1))
    small_theirs = _w1g3_put(game, 1, _mk_creature_card("Theirs", 1, 1))
    big = _w1g3_put(game, 1, _mk_creature_card("Big", 2, 2))

    _w1g3_cycle_and_resolve_trigger(game, "Slice and Dice")
    game.check_state_based_actions()
    assert not game.is_on_battlefield(small_mine)
    assert not game.is_on_battlefield(small_theirs)
    assert game.is_on_battlefield(big) and big.damage_marked == 1
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


#: The Onslaught sorceries that print cycling and nothing triggering on it.
_W1G3_PLAIN_CYCLING_SORCERIES = {
    "Akroma's Vengeance": {"C": 3},
    "Essence Fracture": {"C": 2, "U": 1},
    "Lay Waste": {"C": 2},
}


@pytest.mark.parametrize("name", sorted(_W1G3_PLAIN_CYCLING_SORCERIES))
def test_w1g3_a_plain_cycling_sorcery_pays_its_cost_and_draws(set_pool, name):
    """Cycling is an activated ability (CR 702.29a), so a sorcery cycles with a
    spell on the stack — not at sorcery speed — and the spell's effect never
    happens."""
    card = set_pool("ONS")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert len(usable_activated_abilities(program, zone=HAND)) == 1

    game, alice, bob = _w1g3_table(set_pool, name)
    bear = _w1g3_put(game, 1, _mk_creature_card("Bear", 2, 2))
    bob.hand.append(set_pool("ONS")["Shock"])
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    game.enforce_mana_costs = True
    alice.mana_pool.update(_W1G3_PLAIN_CYCLING_SORCERIES[name])

    assert game.activate_from_hand(0, name).supported, "cycled in response"
    resolve_stack(game)
    assert not any(alice.mana_pool.values()), alice.mana_pool
    assert [c.name for c in alice.graveyard] == [name]
    assert [c.name for c in alice.hand] == ["Plains"]
    assert game.is_on_battlefield(bear)
    assert alice.life == 18, "the Shock under it resolved"

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

# --- W1G10: control and the stack, on sorceries ------------------------------
from engine import Game as _w1g10_Game
from engine.models import Permanent as _w1g10_Permanent
from engine.models import PlayerState as _w1g10_PlayerState
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_table(set_pool, seats: int = 3):
    game = _w1g10_Game(players=[
        _w1g10_PlayerState(
            name=f"P{seat + 1}", life=20,
            library=[set_pool("LEA")["Island"]] * 8,
        )
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def _w1g10_put(game, seat: int, card):
    perm = _w1g10_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def test_w1g10_insurrection_takes_every_creature_until_cleanup(set_pool):
    """"Untap all creatures and gain control of them until end of turn. They
    gain haste until end of turn." At three seats: every creature — the
    caster's own and an untapped one included (the 2004-10-04 ruling: "You
    untap all creatures, control all creatures, and give all creatures
    haste") — is untapped, the caster's, and hasty enough to attack the turn
    it arrived; the cleanup step hands each back."""
    game = _w1g10_table(set_pool)
    mine = _w1g10_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    tapped = _w1g10_put(game, 1, set_pool("LEA")["Hill Giant"])
    untapped = _w1g10_put(game, 2, set_pool("LEA")["Craw Wurm"])
    tapped.tapped = True
    game.players[0].hand.append(set_pool("ONS")["Insurrection"])
    assert game.queue_from_hand(0, "Insurrection").supported
    _w1g10_resolve_stack(game)

    for perm in (mine, tapped, untapped):
        assert game.controller_index_of(perm) == 0, game.log
        assert not perm.tapped
        assert game._has_keyword(perm, "haste"), perm.card.name

    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    slots = list(range(len(game.players[0].battlefield)))
    assert game.declare_attackers(0, slots, defending_player_index=1)[0]

    game.resolve_cleanup_step(0)
    assert game.controller_index_of(mine) == 0
    assert game.controller_index_of(tapped) == 1
    assert game.controller_index_of(untapped) == 2
    assert not game._has_keyword(tapped, "haste")

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# --- W1G13: each player, and graveyards --------------------------------------
#
# Driven at three seats wherever "each player" and "each opponent" could read
# differently from a duel: who is asked, in what order, and what each sees.
from engine import Game as _w1g13_Game
from engine.models import Permanent as _w1g13_Permanent
from engine.models import PlayerState as _w1g13_PlayerState

from tests.helpers import _mk_creature_card as _w1g13_creature
from tests.helpers import resolve_stack as _w1g13_resolve_stack


def _w1g13_table(set_pool, hands=None, *, interactive=(), seats=3):
    """A *seats*-player table, Alice active, each with a five-Plains library."""
    ons = set_pool("ONS")
    hands = hands or {}
    names = ["Alice", "Bob", "Cara", "Dan"][:seats]
    players = [
        _w1g13_PlayerState(
            name=name,
            hand=[ons[card] if isinstance(card, str) else card for card in hands.get(seat, ())],
            library=[ons["Plains"]] * 5,
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g13_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g13_put(game, seat, card):
    permanent = _w1g13_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g13_biorhythm_sets_each_life_total_to_that_seats_creatures(set_pool):
    """"Each player's life total becomes the number of creatures they control."
    Counted per seat on its own board: a loss for the seat above its count, a
    *gain* (CR 119.5) for the one below it — and the seat with no creatures
    goes to 0 and loses at the next state check (the 2004-10-04 ruling)."""
    game = _w1g13_table(set_pool, {0: ["Biorhythm"]})
    alice, bob, cara = game.players
    for name in ("A1", "A2"):
        _w1g13_put(game, 0, _w1g13_creature(name, 2, 2))
    for name in ("B1", "B2", "B3"):
        _w1g13_put(game, 1, _w1g13_creature(name, 2, 2))
    alice.life = 1
    gained: list = []
    original = game._gain_life

    def _spy(player, amount, *args, **kwargs):
        gained.append((player.name, amount))
        return original(player, amount, *args, **kwargs)

    game._gain_life = _spy
    assert game.cast_from_hand(0, "Biorhythm").supported
    _w1g13_resolve_stack(game)
    assert (alice.life, bob.life, cara.life) == (2, 3, 0)
    assert gained == [("Alice", 1)], "a total set higher is a life gain"
    game.check_state_based_actions()
    assert cara.lost and not alice.lost and not bob.lost


def _w1g13_discard(game, seat, hand_index):
    assert game.resolve_pending_choice(
        "discard", seat, hand_indices=[hand_index], to_library=False,
    )


def test_w1g13_syphon_mind_asks_each_other_player_in_turn_and_counts_them(set_pool):
    """"Each other player discards a card. You draw a card for each card
    discarded this way." At three seats both opponents discard, asked one at a
    time in APNAP order (CR 101.4): Cara is not asked until Bob has answered,
    and the draw waits for the last answer and counts both."""
    bear = _w1g13_creature("Bob's Bear", 2, 2)
    giant = _w1g13_creature("Cara's Giant", 3, 3)
    game = _w1g13_table(
        set_pool, {0: ["Syphon Mind"], 1: ["Shock", bear], 2: [giant]},
        interactive={1, 2},
    )
    alice, bob, cara = game.players
    assert game.cast_from_hand(0, "Syphon Mind").supported
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 1)]
    assert alice.hand == []
    _w1g13_discard(game, 1, 1)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 2)]
    assert alice.hand == [], "nothing is drawn while an opponent still owes"
    _w1g13_discard(game, 2, 0)
    _w1g13_resolve_stack(game)
    assert [c.name for c in bob.graveyard] == ["Bob's Bear"]
    assert [c.name for c in cara.graveyard] == ["Cara's Giant"]
    assert len(alice.hand) == 2
    assert alice.graveyard[-1].name == "Syphon Mind"


def test_w1g13_syphon_mind_draws_only_for_what_was_discarded(set_pool):
    """An opponent with an empty hand discards nothing, and the draw is the
    count of the cards that actually went — here one."""
    game = _w1g13_table(set_pool, {0: ["Syphon Mind"], 1: ["Shock"]})
    alice, bob, cara = game.players
    assert game.cast_from_hand(0, "Syphon Mind").supported
    _w1g13_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in bob.graveyard] == ["Shock"]
    assert cara.graveyard == []
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g13_strongarm_tactics_charges_each_seat_that_kept_its_creatures(set_pool):
    """"Each player discards a card. Then each player who didn't discard a
    creature card this way loses 4 life." The active player first (here a seat
    nobody asks, which discards its first card), Bob asked and answering with a
    creature card, and Cara — whose empty hand discarded nothing — counted as
    not having discarded one. The loss waits for Bob's answer."""
    giant = _w1g13_creature("Hill Giant", 3, 3)
    game = _w1g13_table(
        set_pool,
        {0: ["Strongarm Tactics", "Plains", _w1g13_creature("Bear", 2, 2)],
         1: ["Shock", giant]},
        interactive={1},
    )
    alice, bob, cara = game.players
    assert game.cast_from_hand(0, "Strongarm Tactics").supported
    assert [c.name for c in alice.graveyard] == ["Plains"], "Alice chose first"
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 1)]
    assert (alice.life, cara.life) == (20, 20), "no loss before the last answer"
    _w1g13_discard(game, 1, 1)
    _w1g13_resolve_stack(game)
    assert [c.name for c in bob.graveyard] == ["Hill Giant"]
    assert (alice.life, bob.life, cara.life) == (16, 20, 16)


def _w1g13_tokens(game, seat, name="Bear Token"):
    return [perm for perm in game.controlled_by(seat) if perm.card.name == name]


def test_w1g13_kamahls_summons_each_seat_reveals_in_turn_and_gets_its_bears(set_pool):
    """"Each player may reveal any number of creature cards from their hand.
    Then each player creates a 2/2 green Bear creature token for each card
    they revealed this way." Asked one seat at a time in APNAP order — Bob is
    asked only after Alice's reveal is public (CR 101.4b) — only creature
    cards are offered, a seat with none is not asked, and each seat's Bears
    are its own count."""
    game = _w1g13_table(
        set_pool,
        {0: ["Kamahl's Summons", _w1g13_creature("Alice's Bear", 2, 2), "Plains"],
         1: [_w1g13_creature("Giant", 3, 3), _w1g13_creature("Dragon", 5, 5), "Shock"],
         2: ["Plains"]},
        interactive={0, 1, 2},
    )
    alice, bob, cara = game.players
    assert game.cast_from_hand(0, "Kamahl's Summons").supported
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("choose_cards_in_hand", 0),
    ]
    offered = game.live_choose_cards_in_hand(game.pending_choices[0])
    assert [alice.hand[i].name for i in offered] == ["Alice's Bear"]
    assert game.confirm_choose_cards_in_hand(0, offered)
    assert game.reveal_events[-1]["seat"] == 0
    assert game.reveal_events[-1]["cards"] == ["Alice's Bear"]
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("choose_cards_in_hand", 1),
    ]
    offered = game.live_choose_cards_in_hand(game.pending_choices[0])
    assert [bob.hand[i].name for i in offered] == ["Giant", "Dragon"]
    assert game.confirm_choose_cards_in_hand(1, offered[:1])
    assert game.pending_choices == [], "Cara holds no creature card and is not asked"
    _w1g13_resolve_stack(game)
    assert len(_w1g13_tokens(game, 0)) == 1
    assert len(_w1g13_tokens(game, 1)) == 1
    assert _w1g13_tokens(game, 2) == []
    bear = _w1g13_tokens(game, 0)[0]
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert len(alice.hand) == 2 and len(bob.hand) == 3, "a reveal moves nothing"


def test_w1g13_kamahls_summons_a_seat_nobody_asks_reveals_every_creature(set_pool):
    """The stated default for "any number": every eligible card."""
    game = _w1g13_table(
        set_pool,
        {0: ["Kamahl's Summons"],
         1: [_w1g13_creature("Giant", 3, 3), _w1g13_creature("Dragon", 5, 5)]},
    )
    assert game.cast_from_hand(0, "Kamahl's Summons").supported
    _w1g13_resolve_stack(game)
    assert [len(_w1g13_tokens(game, seat)) for seat in range(3)] == [0, 2, 0]

# ==== end W1G13 ======================================================
