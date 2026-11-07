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
        "Harsh Mercy: P1 chooses a creature type", "Harsh Mercy: P1 chose Elf",
        "Harsh Mercy: P2 chooses a creature type", "Harsh Mercy: P2 chose Zombie",
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
# Refused here until the cast-time announcement existed; it does now (W2G1),
# and the card's tests are in W2G1's section below, which drives the type
# before the targets through the picker, the cast gates and the resolution.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# "Share a creature type" (CR 205.3m) — Endemic Plague: the relation measured
# against the creature the cast's own cost sacrificed, as it last existed on
# the battlefield (CR 608.2h).

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    for code in ("ONS", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g6_duel(set_pool, *, hand=(), interactive=()):
    me = _W1G6PlayerState(
        name="Me", hand=[_w1g6_card(set_pool, n) for n in hand],
        library=[_w1g6_card(set_pool, "Swamp")] * 6,
    )
    opp = _W1G6PlayerState(name="Opp", library=[_w1g6_card(set_pool, "Forest")] * 6)
    game = _W1G6Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g6_put(game, set_pool, seat, name):
    perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def test_w1g6_endemic_plague_destroys_every_creature_sharing_a_type_with_the_sacrificed_one(set_pool):
    """"As an additional cost to cast this spell, sacrifice a creature. Destroy
    all creatures that share a creature type with the sacrificed creature."
    The Elf Warrior paid for it: the Elf Druid shares Elf and the Goblin
    Warrior shares Warrior — on either side of the table — and the Human
    Soldier, the Bear and the Elemental share nothing, so they stay."""
    game = _w1g6_duel(set_pool, hand=["Endemic Plague"])
    paid = _w1g6_put(game, set_pool, 0, "Elvish Warrior")
    elf = _w1g6_put(game, set_pool, 0, "Wirewood Elf")
    human = _w1g6_put(game, set_pool, 0, "Glory Seeker")
    goblin = _w1g6_put(game, set_pool, 1, "Goblin Sky Raider")
    elemental = _w1g6_put(game, set_pool, 1, "Silvos, Rogue Elemental")
    bear = _w1g6_put(game, set_pool, 1, "Grizzly Bears")
    game._recompute_continuous_effects()

    spec = game.cast_target_spec(0, _w1g6_card(set_pool, "Endemic Plague"))
    assert spec["sacrifice_cost"] and spec["own_only"]
    assert game.queue_from_hand(
        0, "Endemic Plague", cost_permanent_ids=[paid.permanent_id],
    ).supported
    assert [card.name for card in game.players[0].graveyard] == ["Elvish Warrior"]
    _w1g6_resolve_stack(game)

    assert not game.is_on_battlefield(elf), game.log
    assert not game.is_on_battlefield(goblin), game.log
    for survivor in (human, elemental, bear):
        assert game.is_on_battlefield(survivor), (survivor.card.name, game.log)
    assert "Endemic Plague destroyed Wirewood Elf, Goblin Sky Raider" in game.log


def test_w1g6_endemic_plague_cannot_be_regenerated_from(set_pool):
    """"They can't be regenerated." Silvos's regeneration shield is up, and the
    Elemental the Plague is measured against takes it anyway — while the
    Goblin, which shares no type with an Air Elemental, is untouched."""
    game = _w1g6_duel(set_pool, hand=["Endemic Plague"])
    paid = _w1g6_put(game, set_pool, 0, "Air Elemental")
    silvos = _w1g6_put(game, set_pool, 1, "Silvos, Rogue Elemental")
    goblin = _w1g6_put(game, set_pool, 1, "Goblin Sky Raider")
    game._recompute_continuous_effects()
    assert game.queue_permanent_ability(1, "Silvos, Rogue Elemental").supported
    _w1g6_resolve_stack(game)
    assert any("regenerat" in line.lower() for line in game.log), game.log

    assert game.queue_from_hand(
        0, "Endemic Plague", cost_permanent_ids=[paid.permanent_id],
    ).supported
    _w1g6_resolve_stack(game)

    assert not game.is_on_battlefield(silvos), game.log
    assert "Silvos, Rogue Elemental" in [c.name for c in game.players[1].graveyard]
    assert game.is_on_battlefield(goblin)


def test_w1g6_endemic_plague_reads_the_type_the_sacrificed_creature_last_had(set_pool):
    """The sacrificed creature is gone by resolution, so its creature types are
    the ones it last had on the battlefield (CR 608.2h). Imagecrafter made the
    sacrificed Grizzly Bears a Goblin until end of turn — which *replaced* Bear
    (CR 205.1a) — so the Goblin dies and the other Grizzly Bears lives."""
    game = _w1g6_duel(set_pool, hand=["Endemic Plague"], interactive=[0])
    _w1g6_put(game, set_pool, 0, "Imagecrafter")
    paid = _w1g6_put(game, set_pool, 0, "Grizzly Bears")
    goblin = _w1g6_put(game, set_pool, 1, "Goblin Sky Raider")
    other_bears = _w1g6_put(game, set_pool, 1, "Grizzly Bears")
    game._recompute_continuous_effects()
    assert game.queue_permanent_ability(
        0, "Imagecrafter", target_permanent_ids=[paid.permanent_id],
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_creature_type_choice(0, "Goblin") is True
    _w1g6_resolve_stack(game)
    assert not paid.has_type("bear") and paid.has_type("goblin")

    assert game.queue_from_hand(
        0, "Endemic Plague", cost_permanent_ids=[paid.permanent_id],
    ).supported
    _w1g6_resolve_stack(game)

    assert not game.is_on_battlefield(goblin), game.log
    assert game.is_on_battlefield(other_bears), game.log


def test_w1g6_endemic_plague_cannot_be_cast_without_a_creature_to_sacrifice(set_pool):
    """Endemic Plague (2013-04-15): "You must sacrifice exactly one creature to
    cast this spell; you cannot cast it without sacrificing a creature." With
    no creature of its caster's on the battlefield the cast is refused and the
    opponent's creatures are untouched."""
    game = _w1g6_duel(set_pool, hand=["Endemic Plague"])
    goblin = _w1g6_put(game, set_pool, 1, "Goblin Sky Raider")
    result = game.queue_from_hand(0, "Endemic Plague")
    assert not result.supported, result
    assert [card.name for card in game.players[0].hand] == ["Endemic Plague"]
    assert game.is_on_battlefield(goblin)

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


def _w1g10_trade_secrets(set_pool, interactive):
    game = _w1g10_table(set_pool, seats=2)
    for player in game.players:
        player.library = [set_pool("LEA")["Island"]] * 20
    game.interactive_seats = set(interactive)
    game.players[0].hand.append(set_pool("ONS")["Trade Secrets"])
    assert game.queue_from_hand(0, "Trade Secrets", target_player_index=1).supported
    return game


def test_w1g10_trade_secrets_loop_is_the_opponents_to_stop(set_pool):
    """"Target opponent draws two cards, then you draw up to four cards. That
    opponent may repeat this process as many times as they choose." The
    repeat question goes to the **opponent** (seat 1), never the caster; they
    take one more round and then stop, and the caster chooses how many of the
    four each round."""
    game = _w1g10_trade_secrets(set_pool, interactive={0, 1})
    asked = []
    for _ in range(60):
        if not game.stack and not game.pending_choices:
            break
        if not game.pending_choices:
            game.resolve_top_of_stack()
            continue
        choice = game.pending_choices[0]
        asked.append((choice.kind, choice.player_index))
        if choice.kind == "repeat_process":
            assert game.confirm_repeat_process(
                choice.player_index, len([a for a in asked if a[0] == "repeat_process"]) < 2
            )
        elif choice.kind == "draw_up_to":
            assert game.confirm_draw_up_to(choice.player_index, 3)
        else:
            raise AssertionError(choice.kind)
    assert asked == [
        ("draw_up_to", 0), ("repeat_process", 1),
        ("draw_up_to", 0), ("repeat_process", 1),
    ], asked
    assert len(game.players[1].hand) == 4
    assert len(game.players[0].hand) == 6
    assert "P2 declined to repeat (Trade Secrets)" in game.log


def test_w1g10_trade_secrets_headless_opponent_stops_after_one_round(set_pool):
    """The AI's answer terminates: the stated default stops after one round."""
    game = _w1g10_trade_secrets(set_pool, interactive=())
    _w1g10_resolve_stack(game)
    for _ in range(10):
        if not game.pending_choices:
            break
        game.auto_resolve_pending_choices()
    assert not game.stack and not game.pending_choices
    assert len(game.players[1].hand) == 2
    assert len(game.players[0].hand) == 4
    assert "P2 declined to repeat (Trade Secrets)" in game.log


# --- W1G10 drive: the sorcery Chains ------------------------------------------


def test_w1g10_chain_of_smog_a_headless_target_does_not_copy_it_at_itself(set_pool):
    """"Target player discards two cards. That player may copy this spell and
    may choose a new target for that copy." The copy offer is free, and the
    copy keeps its target unless re-aimed — so a seat nobody asks, taking it,
    aimed the copy at itself and was offered again by every copy, discarding
    its own hand without end. The offer is weighed now
    (``ai_prompt_picks.copy_offer_pick``): aimed at the empty-handed caster
    the copy does nothing, so it is declined."""
    game = _w1g10_table(set_pool, seats=2)
    game.players[0].hand.append(set_pool("ONS")["Chain of Smog"])
    game.players[1].hand.extend(
        [set_pool("LEA")[name] for name in ("Lightning Bolt", "Mountain", "Island", "Forest")]
    )
    assert game.queue_from_hand(0, "Chain of Smog", target_player_index=1).supported
    for _ in range(10):
        _w1g10_resolve_stack(game)
        if not game.pending_choices:
            break
        game.auto_resolve_pending_choices()
    assert not game.stack and not game.pending_choices
    assert len(game.players[1].hand) == 2, game.log
    assert not any("copied Chain of Smog" in line for line in game.log), game.log
    assert "P2 declined Chain of Smog (the copy is not worth what taking it costs)" in game.log


def test_w1g10_chain_of_acid_copied_and_copied_back(set_pool):
    """Both seats answering both ways: the destroyed permanent's controller
    copies and re-aims at the caster's enchantment, the caster copies the copy
    back at a land, and the second copy's controller declines."""
    game = _w1g10_table(set_pool, seats=2)
    game.interactive_seats = {0, 1}
    crusade = _w1g10_put(game, 0, set_pool("LEA")["Crusade"])
    bad_moon = _w1g10_put(game, 1, set_pool("LEA")["Bad Moon"])
    mountain = _w1g10_put(game, 1, set_pool("LEA")["Mountain"])
    game.players[0].hand.append(set_pool("ONS")["Chain of Acid"])
    assert game.queue_from_hand(
        0, "Chain of Acid", target_permanent_ids=[bad_moon.permanent_id]
    ).supported
    aims = {1: crusade, 0: mountain}
    offers = [True, True, False]
    asked = []
    for _ in range(60):
        if not game.stack and not game.pending_choices:
            break
        if not game.pending_choices:
            game.resolve_top_of_stack()
            continue
        choice = game.pending_choices[0]
        asked.append((choice.kind, choice.player_index))
        if choice.kind == "optional_pay":
            assert game._resolve_optional_pay(choice, offers.pop(0), None)
        elif choice.kind == "copy_spell_target":
            assert game.confirm_copy_spell_target(
                choice.player_index,
                permanent_id=aims[choice.player_index].permanent_id,
            )
        else:
            raise AssertionError(choice.kind)
    assert asked == [
        ("optional_pay", 1), ("copy_spell_target", 1),
        ("optional_pay", 0), ("copy_spell_target", 0),
        ("optional_pay", 1),
    ], asked
    for perm in (bad_moon, crusade, mountain):
        assert not game.is_on_battlefield(perm), (perm.card.name, game.log)

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# --- W1G12: revealing ---------------------------------------------------------
from engine import Game as _w1g12_Game
from engine.models import Permanent as _w1g12_Permanent
from engine.models import PlayerState as _w1g12_PlayerState
from engine.oracle import compile_card_oracle as _w1g12_compile
from engine.targeting import derive_cast_spec as _w1g12_cast_spec

from tests.helpers import _mk_creature_card as _w1g12_creature
from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_table(set_pool, library, *, hands=None, interactive=(), seats=2,
                 libraries=None):
    ons = set_pool("ONS")
    hands = hands or {}
    libraries = libraries or {}
    names = ["Alice", "Bob", "Cara"][:seats]
    players = [
        _w1g12_PlayerState(
            name=name,
            hand=[ons[card] if isinstance(card, str) else card for card in hands.get(seat, ())],
            library=[
                ons[c] if isinstance(c, str) else c
                for c in (library if seat == 0 else libraries.get(seat, ["Plains"] * 5))
            ],
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g12_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g12_put(game, seat, card):
    permanent = _w1g12_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g12_names(cards):
    return [card.name for card in cards]


def test_w1g12_erratic_explosion_hits_the_chosen_creature_for_the_mana_value(set_pool):
    """"Choose any target. Reveal cards from the top of your library until you
    reveal a nonland card. Erratic Explosion deals damage equal to that card's
    mana value to that permanent or player. Put the revealed cards on the
    bottom of your library in any order." The picker offers any target (the
    choosing sentence is the announcement, CR 601.2c); the run stops on
    Akroma's Vengeance under a land, the giant takes 6, and the two revealed
    cards go under the one never turned over."""
    explosion = set_pool("ONS")["Erratic Explosion"]
    spec = _w1g12_cast_spec(explosion, _w1g12_compile(explosion))
    assert spec is not None and spec.get("kind") == "any"
    game = _w1g12_table(
        set_pool, ["Mountain", "Akroma's Vengeance", "Forest"],
        hands={0: ["Erratic Explosion"]},
    )
    giant = _w1g12_put(game, 1, _w1g12_creature("Bob's Giant", 5, 7))
    assert game.cast_from_hand(
        0, "Erratic Explosion", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g12_resolve_stack(game)
    assert giant.damage_marked == 6
    assert game.players[1].life == 20
    assert _w1g12_names(game.players[0].library) == [
        "Forest", "Mountain", "Akroma's Vengeance",
    ]
    assert _w1g12_names(game.players[0].graveyard) == ["Erratic Explosion"]


def test_w1g12_erratic_explosion_at_a_player_and_over_an_all_land_library(set_pool):
    """At a player: Shock on top deals 1. And the ruling (2004-10-04): "If all
    your cards are lands, no damage is dealt" — the whole library is turned
    over and put back, and the player is untouched."""
    game = _w1g12_table(
        set_pool, ["Shock", "Forest"], hands={0: ["Erratic Explosion"]},
    )
    assert game.cast_from_hand(0, "Erratic Explosion", target_player_index=1).supported
    _w1g12_resolve_stack(game)
    assert game.players[1].life == 19
    assert _w1g12_names(game.players[0].library) == ["Forest", "Shock"]

    game = _w1g12_table(
        set_pool, ["Mountain", "Forest"], hands={0: ["Erratic Explosion"]},
    )
    assert game.cast_from_hand(0, "Erratic Explosion", target_player_index=1).supported
    _w1g12_resolve_stack(game)
    assert game.players[1].life == 20
    assert _w1g12_names(game.players[0].library) == ["Mountain", "Forest"]


def test_w1g12_erratic_explosion_whose_target_left_does_not_reveal(set_pool):
    """CR 608.2b: the one target is illegal as the spell resolves, so the
    spell does nothing at all — no card is revealed and the library is as it
    was."""
    game = _w1g12_table(
        set_pool, ["Mountain", "Shock", "Forest"], hands={0: ["Erratic Explosion"]},
    )
    giant = _w1g12_put(game, 1, _w1g12_creature("Bob's Giant", 5, 7))
    assert game.queue_from_hand(
        0, "Erratic Explosion", target_player_index=1,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    assert len(game.stack) == 1
    game.remove_from_battlefield(giant)
    _w1g12_resolve_stack(game)
    assert _w1g12_names(game.players[0].library) == ["Mountain", "Shock", "Forest"]
    assert not any("stopped on" in line for line in game.log)
    assert _w1g12_names(game.players[0].graveyard) == ["Erratic Explosion"]


_W1G12_MAGNETISM_LIBRARY = [
    "Forest", "Wellwisher", "Island", "Krosan Colossus", "Mountain", "Swamp",
]


def test_w1g12_animal_magnetism_the_opponent_picks_the_creature_you_get(set_pool):
    """"Reveal the top five cards of your library. An opponent chooses a
    creature card from among them. Put that card onto the battlefield and the
    rest into your graveyard." At three seats the caster names which opponent
    chooses (CR 608.2d); Cara is offered only the two creature cards, a land is
    refused, and her pick enters under Alice while the other four revealed
    cards are binned — the sixth card, never revealed, stays."""
    game = _w1g12_table(
        set_pool, _W1G12_MAGNETISM_LIBRARY, hands={0: ["Animal Magnetism"]},
        interactive={0, 1, 2}, seats=3,
    )
    assert game.cast_from_hand(0, "Animal Magnetism").supported
    who = game.pending_choice_of("player_choice", 0)
    assert who is not None and sorted(who.data["seats"]) == [1, 2]
    assert game.resolve_pending_choice("player_choice", 0, seat=2)
    pick = game.pending_choice_of("opponent_picks_revealed", 2)
    assert pick is not None and pick.data["cards"] == _W1G12_MAGNETISM_LIBRARY[:5]
    assert pick.data["legal_indices"] == [1, 3]
    assert not game.confirm_opponent_picks_revealed(2, 0), "a land is not a creature card"
    assert game.confirm_opponent_picks_revealed(2, 3)
    _w1g12_resolve_stack(game)
    entered = list(game.all_permanents())
    assert [p.card.name for p in entered] == ["Krosan Colossus"]
    assert game.controller_index_of(entered[0]) == 0
    assert sorted(_w1g12_names(game.players[0].graveyard)) == [
        "Animal Magnetism", "Forest", "Island", "Mountain", "Wellwisher",
    ]
    assert _w1g12_names(game.players[0].library) == ["Swamp"]


def test_w1g12_animal_magnetism_an_ai_opponent_hands_over_the_weakest(set_pool):
    """A seat nobody asks names the creature that serves the revealer least —
    the cheapest, since the card it names is the one Alice gets (Thran Tome's
    costliest-first is the policy for a pick that is *lost*). And with no
    creature card among the five, nobody chooses anything and all five are
    binned."""
    game = _w1g12_table(
        set_pool, _W1G12_MAGNETISM_LIBRARY, hands={0: ["Animal Magnetism"]},
    )
    assert game.cast_from_hand(0, "Animal Magnetism").supported
    _w1g12_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Wellwisher"]
    assert "Krosan Colossus" in _w1g12_names(game.players[0].graveyard)

    lands = ["Forest", "Island", "Mountain", "Swamp", "Plains", "Forest"]
    game = _w1g12_table(set_pool, lands, hands={0: ["Animal Magnetism"]})
    assert game.cast_from_hand(0, "Animal Magnetism").supported
    _w1g12_resolve_stack(game)
    assert list(game.all_permanents()) == []
    assert game.pending_choices == []
    assert sorted(_w1g12_names(game.players[0].graveyard)) == sorted(
        lands[:5] + ["Animal Magnetism"]
    )
    assert _w1g12_names(game.players[0].library) == ["Forest"]


_W1G12_BOB_HAND = ["Akroma's Vengeance", "Plains", "Shock", "Krosan Colossus", "Island"]


def test_w1g12_blackmail_the_target_shows_three_and_the_caster_takes_one(set_pool):
    """"Target player reveals three cards from their hand and you choose one
    of them. That player discards that card." Bob — the revealer — picks the
    three he shows (CR 608.2c); Alice is offered only those, the two he kept
    back go out face down (no name on the wire), Shock (unrevealed) is
    refused, and the card she takes is discarded."""
    from web.prompt_cards import _revealed_hand_pick as _w1g12_render
    from web.prompt_registry import PromptContext as _w1g12_Ctx

    game = _w1g12_table(
        set_pool, ["Swamp"] * 5, hands={0: ["Blackmail"], 1: _W1G12_BOB_HAND},
        interactive={0, 1},
    )
    assert game.cast_from_hand(0, "Blackmail", target_player_index=1).supported
    shown = game.pending_choice_of("choose_cards_in_hand", 1)
    assert shown is not None and shown.data["count"] == 3
    assert game.pending_choice_of("revealed_hand_pick", 0) is None
    assert game.confirm_choose_cards_in_hand(1, [0, 1, 4])
    pick = game.pending_choice_of("revealed_hand_pick", 0)
    assert pick is not None and pick.data["legal_indices"] == [0, 1, 4]
    rendered = _w1g12_render(
        _w1g12_Ctx(game=game, viewer_seat=0, serialize_card=lambda card: {"name": card.name},
                   seat_type=lambda seat: "human"),
        [pick],
    )
    assert [c["name"] for c in rendered["cards"]] == [
        "Akroma's Vengeance", "Plains", "Face-down card", "Face-down card", "Island",
    ]
    assert not game.confirm_revealed_hand_pick(0, 2), "Shock was never revealed"
    assert game.confirm_revealed_hand_pick(0, 0)
    _w1g12_resolve_stack(game)
    assert _w1g12_names(game.players[1].graveyard) == ["Akroma's Vengeance"]
    assert _w1g12_names(game.players[1].hand) == [
        "Plains", "Shock", "Krosan Colossus", "Island",
    ]
    assert _w1g12_names(game.players[0].graveyard) == ["Blackmail"]


def test_w1g12_blackmail_against_a_two_card_hand_reveals_both(set_pool):
    """The ruling (2004-10-04): "If the player has less than 3 cards, all of
    them are revealed." Nobody asks Bob anything — both cards are shown and
    Alice picks between them at once."""
    game = _w1g12_table(
        set_pool, ["Swamp"] * 5, hands={0: ["Blackmail"], 1: ["Shock", "Plains"]},
        interactive={0, 1},
    )
    assert game.cast_from_hand(0, "Blackmail", target_player_index=1).supported
    assert game.pending_choice_of("choose_cards_in_hand", 1) is None
    pick = game.pending_choice_of("revealed_hand_pick", 0)
    assert pick is not None and pick.data["legal_indices"] == [0, 1]
    assert game.confirm_revealed_hand_pick(0, 1)
    _w1g12_resolve_stack(game)
    assert _w1g12_names(game.players[1].graveyard) == ["Plains"]
    assert _w1g12_names(game.players[1].hand) == ["Shock"]


def test_w1g12_blackmail_between_two_seats_nobody_asks(set_pool):
    """A revealer nobody asks shows its three least costly cards (the lands
    and the Shock), and a caster nobody asks takes the costliest of what was
    shown — never Akroma's Vengeance, which Bob kept back."""
    game = _w1g12_table(
        set_pool, ["Swamp"] * 5, hands={0: ["Blackmail"], 1: _W1G12_BOB_HAND},
    )
    assert game.cast_from_hand(0, "Blackmail", target_player_index=1).supported
    _w1g12_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert game.pending_choices == []
    assert _w1g12_names(game.players[1].graveyard) == ["Shock"]
    assert any("Bob revealed Plains, Island, Shock" in line for line in game.log)

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
    nobody asks, which discards the creature card that spares it the loss —
    kg3's ``ai_prompts.order_discard``, where it used to discard its first
    card), Bob asked and answering with a creature card, and Cara — whose empty
    hand discarded nothing — counted as not having discarded one. The loss
    waits for Bob's answer."""
    giant = _w1g13_creature("Hill Giant", 3, 3)
    game = _w1g13_table(
        set_pool,
        {0: ["Strongarm Tactics", "Plains", _w1g13_creature("Bear", 2, 2)],
         1: ["Shock", giant]},
        interactive={1},
    )
    alice, bob, cara = game.players
    assert game.cast_from_hand(0, "Strongarm Tactics").supported
    assert [c.name for c in alice.graveyard] == ["Bear"], "Alice chose first"
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 1)]
    assert (alice.life, cara.life) == (20, 20), "no loss before the last answer"
    _w1g13_discard(game, 1, 1)
    _w1g13_resolve_stack(game)
    assert [c.name for c in bob.graveyard] == ["Hill Giant"]
    assert (alice.life, bob.life, cara.life) == (20, 20, 16)


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


# ==== W2G1 ==========================================================
# W2G1's tests go between this line and the "end W2G1" line.

from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from tests.helpers import _mk_card as _w2g1_mk_card
from tests.helpers import resolve_stack as _w2g1_resolve_stack

# --- Aphetto Dredging ---------------------------------------------------------
# "Return up to three target creature cards of the creature type of your choice
# from your graveyard to your hand." The type is announced before the targets
# (the card's 2004-10-04 ruling), and every reader of the targets — the picker,
# the cast gates and the handler — judges them under that word.


def _w2g1_yard_card(name, subtype):
    return _w2g1_mk_card(
        name=name, mana_cost="{1}{B}", type_line=f"Creature - {subtype}",
        colors=("B",),
    )


def _w2g1_dredging_table(set_pool):
    ons = set_pool("ONS")
    yard = [
        _w2g1_yard_card("Goblin A", "Goblin"),
        _w2g1_yard_card("Elf A", "Elf Warrior"),
        _w2g1_yard_card("Goblin B", "Goblin"),
        _w2g1_yard_card("Goblin C", "Goblin Rogue"),
        _w2g1_yard_card("Elf B", "Elf"),
        ons["Swamp"],
    ]
    game = _W2G1Game(players=[
        _W2G1PlayerState(name="A", hand=[ons["Aphetto Dredging"]],
                         graveyard=yard, library=[ons["Swamp"]] * 5),
        _W2G1PlayerState(name="B", library=[ons["Swamp"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _w2g1_names(cards):
    return sorted(card.name for card in cards)


def test_w2g1_aphetto_dredging_offers_only_cards_of_the_announced_type(set_pool):
    """The picker asks the type first and lists what that type admits: the
    default is the type most of the caster's graveyard shares (three Goblins
    against two Elves), and re-asked with "elf" the list is the two Elves."""
    game = _w2g1_dredging_table(set_pool)
    card = game.players[0].hand[0]

    spec = game.cast_target_spec(0, card)
    assert spec["announces_creature_type"] is True
    assert spec["default_creature_type"] == spec["chosen_creature_type"] == "goblin"
    assert [t["name"] for t in spec["valid_targets"]] == [
        "Goblin A", "Goblin B", "Goblin C",
    ]

    elves = game.cast_target_spec(0, card, chosen_creature_type="elf")
    assert elves["chosen_creature_type"] == "elf"
    assert [t["name"] for t in elves["valid_targets"]] == ["Elf A", "Elf B"]
    assert elves["max_targets"] == 3


def test_w2g1_aphetto_dredging_returns_the_named_cards_of_that_type(set_pool):
    game = _w2g1_dredging_table(set_pool)
    alice = game.players[0]

    result = game.cast_from_hand(
        0, "Aphetto Dredging", chosen_creature_type="elf",
        target_player_index=0, target_permanent_index=[1, 4],
    )
    assert result.supported, result.details
    _w2g1_resolve_stack(game)

    assert _w2g1_names(alice.hand) == ["Elf A", "Elf B"]
    assert _w2g1_names(alice.graveyard) == [
        "Aphetto Dredging", "Goblin A", "Goblin B", "Goblin C", "Swamp",
    ]
    assert "A chose Elf to cast Aphetto Dredging" in game.log


def test_w2g1_aphetto_dredging_refuses_a_card_of_another_type(set_pool):
    """A Goblin named under "elf" is not a legal target (CR 601.2c): the cast
    is refused before anything moves, and the card stays in hand."""
    game = _w2g1_dredging_table(set_pool)
    alice = game.players[0]

    refused = game.cast_from_hand(
        0, "Aphetto Dredging", chosen_creature_type="elf",
        target_player_index=0, target_permanent_index=[1, 0],
    )
    assert not refused.supported
    assert refused.details == "no valid target for Aphetto Dredging"
    assert _w2g1_names(alice.hand) == ["Aphetto Dredging"]
    assert not game.stack

    not_a_type = game.cast_from_hand(
        0, "Aphetto Dredging", chosen_creature_type="swamp",
        target_player_index=0, target_permanent_index=[1],
    )
    assert not not_a_type.supported
    assert "is not a creature type" in not_a_type.details


def test_w2g1_aphetto_dredging_a_card_gone_in_response_is_skipped(set_pool):
    """CR 608.2b: one of the two named Elves leaves the graveyard before the
    spell resolves; the other still returns, and nothing of another type is
    taken in its place."""
    game = _w2g1_dredging_table(set_pool)
    alice = game.players[0]

    assert game.queue_from_hand(
        0, "Aphetto Dredging", chosen_creature_type="elf",
        target_player_index=0, target_permanent_index=[1, 4],
    ).supported
    assert [item.card.name for item in game.stack] == ["Aphetto Dredging"]
    (elf_a,) = [card for card in alice.graveyard if card.name == "Elf A"]
    alice.graveyard.remove(elf_a)
    alice.exile.append(elf_a)
    _w2g1_resolve_stack(game)

    assert _w2g1_names(alice.hand) == ["Elf B"]
    assert {"Goblin A", "Goblin B", "Goblin C"} <= {c.name for c in alice.graveyard}


# --- Blatant Thievery ---------------------------------------------------------
# "For each opponent, gain control of target permanent that player controls."
# One target per opponent, each among that opponent's permanents (CR 601.2c;
# "You gain control of only one permanent from each player", 2004-10-04), and
# "If a permanent changes controller after being targeted but before this spell
# resolves, you won't gain control of that permanent" (2004-10-04).

from engine.control import change_control as _w2g1_change_control
from engine.models import Permanent as _W2G1Permanent


def _w2g1_permanent(name, type_line="Creature - Bear"):
    permanent = _W2G1Permanent(card=_w2g1_mk_card(
        name=name, mana_cost="{1}{G}", type_line=type_line, colors=("G",),
    ))
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w2g1_thievery_table(set_pool, boards, *, caster=0):
    """One seat per entry of *boards* (its permanents' names); the caster
    holds Blatant Thievery."""
    ons = set_pool("ONS")
    players = []
    for seat, names in enumerate(boards):
        players.append(_W2G1PlayerState(
            name="ABCD"[seat],
            hand=[ons["Blatant Thievery"]] if seat == caster else [],
            battlefield=[
                _w2g1_permanent(name, "Artifact" if "Rock" in name else "Creature - Bear")
                for name in names
            ],
            library=[ons["Island"]] * 5,
        ))
    game = _W2G1Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = caster
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    return game


def _w2g1_named(game, name):
    (permanent,) = [p for p in game.all_permanents() if p.card.name == name]
    return permanent


def _w2g1_ids(game, *names):
    return [_w2g1_named(game, name).permanent_id for name in names]


def _w2g1_boards(game):
    return [
        sorted(p.card.name for p in game.controlled_by(seat))
        for seat in range(len(game.players))
    ]


def test_w2g1_blatant_thievery_takes_one_permanent_from_each_opponent(set_pool):
    """Three seats: the picker asks for opponent B's permanent, then opponent
    C's, and the spell takes both, for good (CR 611.2a)."""
    game = _w2g1_thievery_table(
        set_pool, [["A Bear"], ["B Bear", "B Rock"], ["C Bear"]],
    )
    spec = game.cast_target_spec(0, game.players[0].hand[0])
    assert [role["role"] for role in spec["roles"]] == [
        "opponent 1's target", "opponent 2's target",
    ]
    assert [(o["seat"], o["name"]) for o in spec["valid_targets"]] == [
        (1, "B Bear"), (1, "B Rock"),
    ]
    assert all(
        [(n["seat"], n["name"]) for n in o["next"]] == [(2, "C Bear")]
        for o in spec["valid_targets"]
    )

    result = game.queue_from_hand(
        0, "Blatant Thievery", target_permanent_ids=_w2g1_ids(game, "B Rock", "C Bear"),
    )
    assert result.supported, result.details
    _w2g1_resolve_stack(game)
    assert _w2g1_boards(game) == [["A Bear", "B Rock", "C Bear"], ["B Bear"], []]
    game.resolve_cleanup_step(0)
    assert _w2g1_boards(game) == [["A Bear", "B Rock", "C Bear"], ["B Bear"], []]


def test_w2g1_blatant_thievery_owes_a_target_for_every_opponent(set_pool):
    """CR 601.2c: one target for each opponent, each that opponent's — so a
    cast naming one, naming two of one opponent's, naming them out of turn
    order or naming none is refused before anything is paid; and with an
    opponent who controls nothing there is no legal announcement at all."""
    game = _w2g1_thievery_table(
        set_pool, [["A Bear"], ["B Bear", "B Rock"], ["C Bear"]],
    )
    for named, refusal in (
        (("B Rock",), "Blatant Thievery requires 2 targets"),
        (("B Rock", "B Bear"), "no valid target for Blatant Thievery"),
        (("C Bear", "B Bear"), "no valid target for Blatant Thievery"),
        ((), "Blatant Thievery requires 2 targets"),
    ):
        refused = game.queue_from_hand(
            0, "Blatant Thievery", target_permanent_ids=_w2g1_ids(game, *named) or None,
        )
        assert not refused.supported and refused.details == refusal, named
        assert not game.stack and len(game.players[0].hand) == 1

    empty = _w2g1_thievery_table(set_pool, [["A Bear"], ["B Bear"], []])
    assert empty.cast_target_spec(0, empty.players[0].hand[0])["valid_targets"] == []
    assert not empty.queue_from_hand(
        0, "Blatant Thievery", target_permanent_ids=_w2g1_ids(empty, "B Bear"),
    ).supported


def test_w2g1_blatant_thievery_skips_a_permanent_that_changed_controller(set_pool):
    """The ruling: C's Bear changes controller in response and is not taken;
    B's Bear still is. When every target has changed controller the spell is
    countered by the rules (CR 608.2b)."""
    game = _w2g1_thievery_table(set_pool, [["A Bear"], ["B Bear"], ["C Bear"]])
    assert game.queue_from_hand(
        0, "Blatant Thievery", target_permanent_ids=_w2g1_ids(game, "B Bear", "C Bear"),
    ).supported
    _w2g1_change_control(_w2g1_named(game, "C Bear"), 1, source=None)
    game._sync_control()
    _w2g1_resolve_stack(game)
    assert _w2g1_boards(game) == [["A Bear", "B Bear"], ["C Bear"], []]

    game = _w2g1_thievery_table(set_pool, [["A Bear"], ["B Bear"], ["C Bear"]])
    assert game.queue_from_hand(
        0, "Blatant Thievery", target_permanent_ids=_w2g1_ids(game, "B Bear", "C Bear"),
    ).supported
    _w2g1_change_control(_w2g1_named(game, "B Bear"), 2, source=None)
    _w2g1_change_control(_w2g1_named(game, "C Bear"), 1, source=None)
    game._sync_control()
    _w2g1_resolve_stack(game)
    assert _w2g1_boards(game) == [["A Bear"], ["C Bear"], ["B Bear"]]
    assert "Blatant Thievery was countered by the rules and moved to graveyard" in game.log


def test_w2g1_blatant_thievery_counts_the_opponents_still_in_the_game(set_pool):
    """Four seats, the third has left the game (CR 800.4a): two opponents,
    two targets — B's and D's — counted in turn order from the caster."""
    game = _w2g1_thievery_table(
        set_pool, [["A Bear"], ["B Bear"], ["C Bear"], ["D Bear"]],
    )
    game.players[2].lost = True
    game.remove_from_battlefield(_w2g1_named(game, "C Bear"))
    game._sync_control()
    spec = game.cast_target_spec(0, game.players[0].hand[0])
    assert len(spec["roles"]) == 2
    assert [(o["seat"], [n["seat"] for n in o["next"]]) for o in spec["valid_targets"]] == [
        (1, [3]),
    ]
    assert game.queue_from_hand(
        0, "Blatant Thievery", target_permanent_ids=_w2g1_ids(game, "B Bear", "D Bear"),
    ).supported
    _w2g1_resolve_stack(game)
    assert _w2g1_boards(game)[0] == ["A Bear", "B Bear", "D Bear"]


def test_w2g1_blatant_thievery_opponents_are_in_turn_order_from_the_caster(set_pool):
    """Cast by the second seat of three: its opponents are the third seat, then
    the first (CR 101.4)."""
    game = _w2g1_thievery_table(
        set_pool, [["A Bear"], ["B Bear"], ["C Bear"]], caster=1,
    )
    spec = game.cast_target_spec(1, game.players[1].hand[0])
    assert [(o["seat"], [n["seat"] for n in o["next"]]) for o in spec["valid_targets"]] == [
        (2, [0]),
    ]
    assert game.queue_from_hand(
        1, "Blatant Thievery", target_permanent_ids=_w2g1_ids(game, "C Bear", "A Bear"),
    ).supported
    _w2g1_resolve_stack(game)
    assert _w2g1_boards(game) == [[], ["A Bear", "B Bear", "C Bear"], []]

# --- Kaboom! --------------------------------------------------------------------
# "Choose any number of target players or planeswalkers. For each of them,
# reveal cards from the top of your library until you reveal a nonland card,
# Kaboom! deals damage equal to that card's mana value to that player or
# planeswalker, then you put the revealed cards on the bottom of your library in
# any order." Handled one at a time in turn order from the active player, each
# player's group before the next (2022-09-09); an all-land library deals zero
# (2004-10-04).

from engine.named_counters import add_counters as _w2g1_add_counters
from engine.named_counters import counters_on as _w2g1_counters_on


def _w2g1_walker(name):
    walker = _W2G1Permanent(card=_w2g1_mk_card(
        name=name, mana_cost="{3}{R}", type_line="Legendary Planeswalker - Chandra",
        colors=("R",),
    ))
    _w2g1_add_counters(walker, "loyalty", 5)
    return walker


def _w2g1_kaboom_table(set_pool, library, *, seats=3, caster=0, walkers=()):
    """*seats* players; the caster (also the active player) holds Kaboom! over
    *library* (top first); each seat in *walkers* controls a planeswalker."""
    ons = set_pool("ONS")
    players = []
    for seat in range(seats):
        players.append(_W2G1PlayerState(
            name="ABCD"[seat],
            hand=[ons["Kaboom!"]] if seat == caster else [],
            battlefield=(
                [_w2g1_walker(f"{'ABCD'[seat]} Walker")] if seat in walkers else []
            ),
            library=(
                [ons[name] for name in library] if seat == caster
                else [ons["Island"]] * 5
            ),
        ))
    game = _W2G1Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = caster
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    return game


def test_w2g1_kaboom_handles_each_target_in_turn_order(set_pool):
    """B, then B's planeswalker, then C — the active player's turn order, a
    player before the permanents they control: Shock (1) to B, Clone (4) to
    the planeswalker, Swat (3) to C, each revealed pile to the bottom."""
    game = _w2g1_kaboom_table(
        set_pool,
        ["Island", "Shock", "Swamp", "Clone", "Mountain", "Swat"],
        walkers=(1,),
    )
    walker = _w2g1_named(game, "B Walker")
    result = game.queue_from_hand(0, "Kaboom!", target_role_refs=[
        {"seat": 1}, {"permanent_id": walker.permanent_id}, {"seat": 2},
    ])
    assert result.supported, result.details
    _w2g1_resolve_stack(game)

    assert [player.life for player in game.players] == [20, 19, 17]
    assert _w2g1_counters_on(walker, "loyalty") == 1
    assert len(game.players[0].library) == 6, "every revealed card goes back"
    assert [line for line in game.log if line.startswith("A revealed")] == [
        "A revealed 2 card(s) and stopped on Shock (mana value 1)",
        "A revealed 2 card(s) and stopped on Clone (mana value 4)",
        "A revealed 2 card(s) and stopped on Swat (mana value 3)",
    ]


def test_w2g1_kaboom_offers_one_order_per_set_of_targets(set_pool):
    """The picker's walk: any number of targets, the caster's own seat
    included, each set once in turn order — so C is never offered before B,
    and stopping anywhere is a legal announcement."""
    game = _w2g1_kaboom_table(set_pool, ["Shock"] * 4, walkers=(1,))
    spec = game.cast_target_spec(0, game.players[0].hand[0])
    first = sorted((o["kind"], o["seat"]) for o in spec["valid_targets"])
    assert first == [("permanent", 1), ("player", 0), ("player", 1), ("player", 2)]
    after_c = next(o for o in spec["valid_targets"] if o["seat"] == 2)
    assert after_c["next"] == []
    after_b = next(
        o for o in spec["valid_targets"] if o["kind"] == "player" and o["seat"] == 1
    )
    assert sorted((o["kind"], o["seat"]) for o in after_b["next"]) == [
        ("permanent", 1), ("player", 2),
    ]
    after_walker = next(o for o in spec["valid_targets"] if o["kind"] == "permanent")
    assert [(o["kind"], o["seat"]) for o in after_walker["next"]] == [("player", 2)]


def test_w2g1_kaboom_starts_with_the_active_players_group(set_pool):
    """Cast by the second seat of three: its own turn, so the third seat's
    group comes before the first's — the first reveal goes to C."""
    game = _w2g1_kaboom_table(
        set_pool, ["Shock", "Clone"], caster=1,
    )
    assert game.queue_from_hand(
        1, "Kaboom!", target_role_refs=[{"seat": 2}, {"seat": 0}],
    ).supported
    _w2g1_resolve_stack(game)
    assert [player.life for player in game.players] == [16, 20, 19]


def test_w2g1_kaboom_zero_targets_and_an_all_land_library(set_pool):
    """No target is a legal announcement that does nothing; and an all-land
    library deals zero damage (the 2004-10-04 ruling), its cards still
    revealed and put on the bottom."""
    game = _w2g1_kaboom_table(set_pool, ["Shock"] * 3, seats=2)
    assert game.queue_from_hand(0, "Kaboom!").supported
    _w2g1_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]

    game = _w2g1_kaboom_table(set_pool, ["Island", "Swamp"], seats=2)
    assert game.queue_from_hand(0, "Kaboom!", target_role_refs=[{"seat": 1}]).supported
    _w2g1_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]
    assert [card.name for card in game.players[0].library] == ["Island", "Swamp"]


def test_w2g1_kaboom_a_target_gone_in_response_is_skipped(set_pool):
    """B leaves the game before Kaboom! resolves (CR 800.4a): B is no longer a
    legal target, so nothing is revealed for B, and C still takes the first
    card's damage."""
    game = _w2g1_kaboom_table(set_pool, ["Island", "Clone", "Shock"])
    assert game.queue_from_hand(
        0, "Kaboom!", target_role_refs=[{"seat": 1}, {"seat": 2}],
    ).supported
    game.players[1].lost = True
    _w2g1_resolve_stack(game)
    assert game.players[2].life == 16
    assert [line for line in game.log if line.startswith("A revealed")] == [
        "A revealed 2 card(s) and stopped on Clone (mana value 4)",
    ]
# ==== end W2G1 ======================================================
