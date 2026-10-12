"""Odyssey instants.

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

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4_pytest

from engine import Game as _w1g4_Game, PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names.

    Odyssey and Alpha in one pool: the Bursts count their own name, and what
    they are aimed at is furniture.
    """
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    seats = [
        _w1g4_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g4_Game(players=seats)
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            game._put_permanent_onto_battlefield(
                seat, _w1g4_Permanent(card=pool[name]), None
            )
    return game


def _w1g4_names(cards):
    return [card.name for card in cards]


def _w1g4_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- The Bursts: "N plus the number of cards named ~ in all graveyards" ------

def test_flame_burst_counts_its_name_in_every_graveyard(set_pool):
    """2 plus one in each graveyard: 4 damage, and the copy being cast is on
    the stack while the count is taken, so it is not one of them."""
    game = _w1g4_duel(
        set_pool, hand0=["Flame Burst"], gy0=["Flame Burst"],
        gy1=["Flame Burst", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Flame Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 16
    assert _w1g4_names(game.players[0].graveyard) == ["Flame Burst", "Flame Burst"]


def test_flame_burst_with_none_in_a_graveyard_deals_its_printed_two(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Flame Burst"], bf1=["Grizzly Bears"])
    bears = _w1g4_on_board(game, 1, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Flame Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert game.players[1].life == 20


def test_muscle_burst_is_three_plus_the_bursts_in_all_graveyards(set_pool):
    """The same definition Flame Burst prints, in the +X/+X position — which
    refused ("only a count or a maximum can define X here") while the damage
    form read it: one where-clause, two readers that had drifted apart."""
    game = _w1g4_duel(
        set_pool, hand0=["Muscle Burst"], gy0=["Muscle Burst"],
        gy1=["Muscle Burst", "Flame Burst"], bf0=["Grizzly Bears"],
    )
    bears = _w1g4_on_board(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Muscle Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (7, 7)


def test_muscle_burst_needs_a_creature_to_aim_at(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Muscle Burst"], bf1=["Forest"])
    forest = _w1g4_on_board(game, 1, "Forest")
    refused = game.cast_from_hand(
        0, "Muscle Burst", target_permanent_ids=[forest.permanent_id]
    )
    assert not refused.supported
    assert _w1g4_names(game.players[0].hand) == ["Muscle Burst"]


@_w1g4_pytest.mark.parametrize("line, expected", [
    # The arithmetic the sentence form always read, now in the pump position.
    ("Target creature gets +X/+X until end of turn, where X is twice the "
     "number of cards named Vigor Burst in all graveyards minus 1.", (5, 5)),
    ("Target creature gets +X/+0 until end of turn, where X is the number of "
     "cards in your graveyard minus the number of cards in your hand.", (4, 2)),
])
def test_a_pump_reads_the_arithmetic_a_damage_where_clause_reads(
    set_pool, line, expected
):
    """An invented card, not a name: the fork was in which *sentence* could
    carry a sum, so the proof is a card nobody printed carrying one."""
    burst = _w1g4_mk_card("Vigor Burst", "{G}", "Instant", line)
    assert _w1g4_compile(burst).supported
    game = _w1g4_duel(set_pool, bf0=["Grizzly Bears"])
    game.players[0].hand.append(burst)
    game.players[0].graveyard.extend([burst, burst])
    bears = _w1g4_on_board(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Vigor Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == expected


def test_a_damage_where_clause_reads_the_maximum_a_pump_reads(set_pool):
    """The fork's other direction: "the greatest power among" defined a pump's
    X (Carrion Grub) and refused a damage's."""
    blast = _w1g4_mk_card(
        "Grave Blast", "{R}", "Instant",
        "Grave Blast deals X damage to any target, where X is the greatest "
        "power among creature cards in your graveyard.",
    )
    assert _w1g4_compile(blast).supported
    game = _w1g4_duel(set_pool, gy0=["Grizzly Bears", "Craw Wurm", "Forest"])
    game.players[0].hand.append(blast)
    assert game.cast_from_hand(0, "Grave Blast", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 14


def test_a_continuous_x_refuses_a_count_taken_off_a_count():
    """A durationless +X/+0 is rebuilt by the CR 613 recompute, which asks the
    zone evaluator and never the resolution-time function that subtracts — so
    the shape refuses instead of dropping its subtrahend."""
    grower = _w1g4_mk_card(
        "Odd Grower", "{G}", "Creature — Beast",
        "This creature gets +X/+0, where X is the number of cards in your "
        "hand minus the number of cards in your graveyard.",
    )
    assert not _w1g4_compile(grower).supported
    steady = _w1g4_mk_card(
        "Even Grower", "{G}", "Creature — Beast",
        "This creature gets +X/+0, where X is 1 plus the number of cards in "
        "your graveyard.",
    )
    assert _w1g4_compile(steady).supported


# --- Aether Burst: an X counted as the spell is cast (CR 601.2b/601.2c) ------

def test_aether_burst_announces_its_x_and_bounds_the_picker(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Aether Burst"], gy1=["Aether Burst"],
        bf0=["Grizzly Bears"], bf1=["Craw Wurm", "Scryb Sprites"],
    )
    card = set_pool("ODY")["Aether Burst"]
    assert game.announced_cast_x(0, card) == 2
    spec = game.cast_target_spec(0, card)
    assert spec["defined_x"] == 2 and spec["max_targets"] == 2
    assert len(spec["valid_targets"]) == 3
    every = [p.permanent_id for p in game.all_permanents()]
    refused = game.cast_from_hand(0, "Aether Burst", target_permanent_ids=every)
    assert not refused.supported
    assert refused.details == "Aether Burst has 2 targets, not 3"
    assert _w1g4_names(game.players[0].hand) == ["Aether Burst"]


def test_aether_burst_returns_what_was_named_to_its_owners_hand(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Aether Burst"], gy1=["Aether Burst"],
        bf0=["Grizzly Bears"], bf1=["Craw Wurm", "Scryb Sprites"],
    )
    theirs = [p.permanent_id for p in game.controlled_by(1)]
    assert game.cast_from_hand(
        0, "Aether Burst", target_permanent_ids=theirs
    ).supported
    _w1g4_resolve_stack(game)
    assert sorted(_w1g4_names(game.players[1].hand)) == ["Craw Wurm", "Scryb Sprites"]
    assert [p.card.name for p in game.all_permanents()] == ["Grizzly Bears"]


def test_aether_burst_may_name_nobody_and_refuses_a_land(set_pool):
    """"Up to X": naming none is a legal announcement (CR 601.2c), and what is
    named has to be a creature."""
    game = _w1g4_duel(set_pool, hand0=["Aether Burst"], bf1=["Craw Wurm"])
    assert game.cast_from_hand(0, "Aether Burst", target_permanent_ids=[]).supported
    _w1g4_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Craw Wurm"]

    again = _w1g4_duel(set_pool, hand0=["Aether Burst"], bf1=["Forest"])
    forest = _w1g4_on_board(again, 1, "Forest")
    refused = again.cast_from_hand(
        0, "Aether Burst", target_permanent_ids=[forest.permanent_id]
    )
    assert not refused.supported
    assert _w1g4_names(again.players[0].hand) == ["Aether Burst"]


def test_aether_burst_freezes_its_x_at_the_announcement(set_pool):
    """CR 601.2c: the number of targets does not change once determined. The
    graveyards are emptied in response and one target leaves: the two that are
    left are still returned, where a count taken again would return one."""
    game = _w1g4_duel(
        set_pool, hand0=["Aether Burst"], gy1=["Aether Burst", "Aether Burst"],
        bf1=["Craw Wurm", "Scryb Sprites", "Grizzly Bears"],
    )
    ids = [p.permanent_id for p in game.controlled_by(1)]
    assert game.queue_from_hand(0, "Aether Burst", target_permanent_ids=ids).supported
    assert game.stack[-1].x_value == 3
    game.players[1].graveyard.clear()
    game.remove_from_battlefield(game.permanent_by_id(ids[0]))
    _w1g4_resolve_stack(game)
    assert sorted(_w1g4_names(game.players[1].hand)) == ["Grizzly Bears", "Scryb Sprites"]


def test_aether_burst_with_every_target_gone_does_nothing(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Aether Burst"], bf1=["Craw Wurm"])
    wurm = _w1g4_on_board(game, 1, "Craw Wurm")
    assert game.queue_from_hand(
        0, "Aether Burst", target_permanent_ids=[wurm.permanent_id]
    ).supported
    game.remove_from_battlefield(wurm)
    _w1g4_resolve_stack(game)
    assert any("608.2b" in line for line in game.log)
    assert game.players[1].hand == []


# --- Life Burst: "…for each card named ~ in each graveyard" -------------------

def test_life_burst_gains_four_then_four_per_burst_in_each_graveyard(set_pool):
    """One Life Burst in each graveyard: 4, then 8 more. "In each graveyard" is
    "in all graveyards" distributed (CR 400.1: one pile per seat), and the copy
    being cast is still on the stack."""
    game = _w1g4_duel(
        set_pool, hand0=["Life Burst"], gy0=["Life Burst"],
        gy1=["Life Burst", "Forest"],
    )
    assert game.cast_from_hand(0, "Life Burst", target_player_index=0).supported
    _w1g4_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (32, 20)


def test_life_burst_names_its_player_and_gives_the_plain_four(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Life Burst"])
    spec = game.cast_target_spec(0, set_pool("ODY")["Life Burst"])
    assert spec["kind"] == "player" and spec["requires_target"]
    assert game.cast_from_hand(0, "Life Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (20, 24)


# --- Entomb and Predict --------------------------------------------------------

def test_entomb_puts_the_found_card_into_its_owners_graveyard(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Entomb"], lib0=["Forest", "Craw Wurm", "Island"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Entomb").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["destination"] == "graveyard" and prompt.data["count"] == 1
    assert prompt.data["card_type"] == "any" and not prompt.data["up_to"]
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    graveyard = _w1g4_names(game.players[0].graveyard)
    assert len(graveyard) == 2 and "Entomb" in graveyard
    assert len(game.players[0].library) == 2


@_w1g4_pytest.mark.parametrize("named, drawn", [
    ("Grizzly Bears", 2),   # the card that is milled
    ("Craw Wurm", 1),       # a card that is not
    ("", 1),                # naming nothing
])
def test_predict_draws_two_for_the_right_name_and_one_otherwise(
    set_pool, named, drawn
):
    """The name is chosen as the spell resolves, before the mill, and it is
    the caster's to choose — a prompt on their seat while the spell is held."""
    game = _w1g4_duel(
        set_pool, hand0=["Predict"], lib0=["Forest", "Island", "Swamp"],
        lib1=["Grizzly Bears", "Craw Wurm"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Predict", target_player_index=1).supported
    game.resolve_top_of_stack()
    prompt = game.waiting_prompt()
    assert prompt.kind == "choose_card_name" and prompt.player_index == 0
    assert game.players[1].graveyard == [], "nothing is milled before the name"
    assert game.confirm_choose_card_name(0, named)
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert len(game.players[0].hand) == drawn
    assert _w1g4_names(game.players[0].graveyard) == ["Predict"]


def test_predict_may_mill_its_own_caster(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Predict"], lib0=["Forest", "Island", "Swamp"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Predict", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_choose_card_name(0, "Forest")
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].graveyard) == ["Forest", "Predict"]
    assert _w1g4_names(game.players[0].hand) == ["Island", "Swamp"]

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

import pytest as _w1g9_pytest

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from engine.oracle import compile_card_oracle as _w1g9_compile
from tests.helpers import _mk_card as _w1g9_mk_card
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_duel(set_pool, *, hand0=(), hand1=(), bf0=(), bf1=(), gy0=(),
               gy1=(), costs=False):
    """A two-seat game built from card names (Odyssey first, then Alpha),
    with ten Forests in each library and nobody summoning-sick."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name=f"P{seat}", life=20, hand=[pool[n] for n in hand],
            graveyard=[pool[n] for n in gy], library=[pool["Forest"]] * 10,
        )
        for seat, (hand, gy) in enumerate(((hand0, gy0), (hand1, gy1)))
    ])
    game.enforce_mana_costs = costs
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            permanent = _w1g9_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game  # _w1g9_duel (instants)


def _w1g9_on(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g9_names(cards):
    return [card.name for card in cards]


# --- Deluge: "Tap all creatures without flying." ---------------------------

def test_deluge_taps_every_creature_without_flying_and_nothing_else(set_pool):
    game = _w1g9_duel(
        set_pool, hand0=["Deluge"], bf0=["Grizzly Bears"],
        bf1=["Air Elemental", "Gray Ogre", "Forest", "Mox Pearl"],
    )
    assert game.cast_from_hand(0, "Deluge").supported
    _w1g9_resolve_stack(game)
    tapped = {p.card.name for p in game.all_permanents() if p.tapped}
    assert tapped == {"Grizzly Bears", "Gray Ogre"}


def test_deluge_asks_what_a_creature_has_as_it_resolves(set_pool):
    """A keyword is CR 613 layer 6: an Ogre given flying in response is not
    tapped, and an Air Elemental whose flying is gone is."""
    game = _w1g9_duel(
        set_pool, hand0=["Deluge"], hand1=["Jump"],
        bf1=["Gray Ogre", "Grizzly Bears"],
    )
    ogre = _w1g9_on(game, 1, "Gray Ogre")
    assert game.queue_from_hand(0, "Deluge").supported
    assert game.queue_from_hand(
        1, "Jump", target_permanent_ids=[ogre.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert not ogre.tapped
    assert _w1g9_on(game, 1, "Grizzly Bears").tapped


def test_a_tap_sweep_still_refuses_a_keyword_it_was_never_shown(set_pool):
    """The whitelist grew by the one field the pool prints: "with flying" on
    a tap sweep is still a refusal, not a sweep of everything."""
    assert _w1g9_compile(_w1g9_mk_card(
        "Low Tide", "{U}", "Instant", "Tap all creatures without flying."
    )).supported
    assert not _w1g9_compile(_w1g9_mk_card(
        "High Tide Probe", "{U}", "Instant", "Tap all creatures with flying."
    )).supported


# --- Syncopate: a price, and a destination if it goes unpaid ----------------

def _w1g9_zones(game, seat):
    player = game.players[seat]
    return (
        _w1g9_names(player.graveyard), _w1g9_names(player.exile),
        _w1g9_names(p.card for p in game.controlled_by(seat)),
    )


def test_syncopate_exiles_the_spell_it_counters(set_pool):
    """"Counter target spell unless its controller pays {X}. If that spell is
    countered this way, exile it instead of putting it into its owner's
    graveyard." The payer cannot cover {2}: countered, and the card is in
    exile, never in a graveyard."""
    game = _w1g9_duel(
        set_pool, hand0=["Syncopate"], hand1=["Grizzly Bears"], costs=True,
    )
    game.players[0].mana_pool.update({"U": 3})
    game.players[1].mana_pool.update({"G": 2})
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(
        0, "Syncopate", target_stack_index=0, x_value=2
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_zones(game, 1) == ([], ["Grizzly Bears"], [])
    assert _w1g9_names(game.players[0].graveyard) == ["Syncopate"]


def test_syncopate_leaves_a_spell_whose_controller_pays(set_pool):
    game = _w1g9_duel(
        set_pool, hand0=["Syncopate"], hand1=["Grizzly Bears"], costs=True,
    )
    game.players[0].mana_pool.update({"U": 3})
    game.players[1].mana_pool.update({"G": 4})
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(
        0, "Syncopate", target_stack_index=0, x_value=2
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_zones(game, 1) == ([], [], ["Grizzly Bears"])
    assert sum(game.players[1].mana_pool.values()) == 0


def test_syncopate_asks_a_person_and_exiles_when_they_decline(set_pool):
    """The destination rides the payment prompt: a seat that could pay and
    says no has the spell countered by the answer, and it is exiled there."""
    game = _w1g9_duel(
        set_pool, hand0=["Syncopate"], hand1=["Grizzly Bears"], costs=True,
    )
    game.interactive_seats = {0, 1}
    game.players[0].mana_pool.update({"U": 3})
    game.players[1].mana_pool.update({"G": 4})
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(
        0, "Syncopate", target_stack_index=0, x_value=2
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    prompt = game.pending_choice_of("mana_payment")
    assert prompt is not None and prompt.player_index == 1
    assert _w1g9_names(i.card for i in game.stack)[0] == "Grizzly Bears"
    assert game.resolve_pending_choice("mana_payment", 1, pay=False)
    assert _w1g9_zones(game, 1) == ([], ["Grizzly Bears"], [])
    assert game.players[1].mana_pool["G"] == 2, "only the Bears were paid for"


def test_syncopate_for_nothing_counters_nothing_and_needs_a_spell(set_pool):
    game = _w1g9_duel(
        set_pool, hand0=["Syncopate", "Syncopate"], hand1=["Grizzly Bears"],
    )
    refused = game.queue_from_hand(0, "Syncopate", x_value=2)
    assert not refused.supported and len(game.players[0].hand) == 2
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(
        0, "Syncopate", target_stack_index=0, x_value=0
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_zones(game, 1) == ([], [], ["Grizzly Bears"])


@_w1g9_pytest.mark.parametrize("tail, where", [
    ("put it on top of its owner's library instead of into that player's "
     "graveyard.", "library"),
    ("put it into its owner's hand instead of into that player's graveyard.",
     "hand"),
])
def test_a_priced_counter_sends_the_card_wherever_its_tail_prints(
    set_pool, tail, where
):
    """An invented card: the tail is Memory Lapse's and Remand's, and behind
    a price it reaches the same mover the hard counter uses."""
    tax = _w1g9_mk_card(
        "Toll Lapse", "{1}{U}", "Instant",
        "Counter target spell unless its controller pays {2}. If that spell "
        "is countered this way, " + tail,
    )
    assert _w1g9_compile(tax).supported
    game = _w1g9_duel(set_pool, hand1=["Grizzly Bears"], costs=True)
    game.players[0].hand.append(tax)
    game.players[0].mana_pool.update({"U": 2})
    game.players[1].mana_pool.update({"G": 2})
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(0, "Toll Lapse", target_stack_index=0).supported
    _w1g9_resolve_stack(game)
    victim = game.players[1]
    assert _w1g9_zones(game, 1) == ([], [], [])
    if where == "library":
        assert victim.library[0].name == "Grizzly Bears"
    else:
        assert _w1g9_names(victim.hand) == ["Grizzly Bears"]


# --- Cease-Fire: a turn-long ban on one seat, by spell type -----------------

def test_cease_fire_stops_its_target_casting_creature_spells_this_turn(set_pool):
    """Enforced by the one cast-prohibition table its three readers ask: the
    engine refuses the cast, and the same call says no to the AI and the
    castable highlight."""
    from engine.cast_prohibitions import cast_prohibition

    game = _w1g9_duel(
        set_pool, hand0=["Cease-Fire", "Grizzly Bears"],
        hand1=["Grizzly Bears", "Juggernaut", "Lightning Bolt"],
    )
    spec = game.cast_target_spec(0, game.players[0].hand[0])
    assert spec["kind"] == "player" and spec["requires_target"]
    assert game.queue_from_hand(0, "Cease-Fire", target_player_index=1).supported
    _w1g9_resolve_stack(game)
    assert len(game.players[0].hand) == 2, "and its caster drew a card"

    victim = game.players[1]
    for name in ("Grizzly Bears", "Juggernaut"):  # an artifact creature too
        card = next(c for c in victim.hand if c.name == name)
        refusal = cast_prohibition(game, 1, card)
        assert refusal is not None and "creature spells this turn" in refusal.details
        assert not game.queue_from_hand(1, name).supported
    assert len(victim.hand) == 3 and not game.stack
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    # The caster named somebody else: their own creatures are not stopped.
    assert game.queue_from_hand(0, "Grizzly Bears").supported


def test_cease_fire_ends_with_the_turn(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Cease-Fire"], hand1=["Grizzly Bears"])
    assert game.queue_from_hand(0, "Cease-Fire", target_player_index=1).supported
    _w1g9_resolve_stack(game)
    assert not game.queue_from_hand(1, "Grizzly Bears").supported
    game.start_next_turn()
    assert game.spell_types_forbidden_this_turn == {}
    assert game.queue_from_hand(1, "Grizzly Bears").supported


@_w1g9_pytest.mark.parametrize("line, supported", [
    ("Target player can't cast creature spells this turn.", True),
    ("Target player can't cast instant or sorcery spells this turn.", True),
    # A window the record does not have, and no window at all (a permanent's
    # static ability, which a table reads): both refuse.
    ("Target player can't cast creature spells until your next turn.", False),
    ("Target player can't cast creature spells.", False),
    ("Target player can't cast green creature spells this turn.", False),
])
def test_a_typed_cast_ban_reads_only_the_window_it_can_keep(line, supported):
    card = _w1g9_mk_card("Truce Probe", "{W}", "Instant", line)
    assert _w1g9_compile(card).supported is supported


# --- Aura Graft: take an Aura and move it to something else it can enchant --

def _w1g9_enchant(game, set_pool, seat, aura_name, host):
    from engine.auras import attach_aura

    pool = {**set_pool("LEA"), **set_pool("ODY")}
    aura = _w1g9_Permanent(card=pool[aura_name])
    game._put_permanent_onto_battlefield(seat, aura, None)
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    return aura


def _w1g9_where(game, aura):
    """``(who controls the Aura, the permanent it is on)``."""
    return game.controller_index_of(aura), aura.metadata.get("attached_to")


def test_aura_graft_takes_an_aura_and_moves_it_to_another_permanent(set_pool):
    """"Gain control of target Aura that's attached to a permanent. Attach it
    to another permanent it can enchant." The opponent's Weakness comes off
    my Bears, becomes mine, and goes onto their Ogre."""
    game = _w1g9_duel(
        set_pool, hand0=["Aura Graft"], bf0=["Grizzly Bears"], bf1=["Gray Ogre"],
    )
    bears, ogre = _w1g9_on(game, 0, "Grizzly Bears"), _w1g9_on(game, 1, "Gray Ogre")
    weakness = _w1g9_enchant(game, set_pool, 1, "Weakness", bears)
    spec = game.cast_target_spec(0, game.players[0].hand[0])
    assert [t["name"] for t in spec["valid_targets"]] == ["Weakness"]
    assert game.queue_from_hand(
        0, "Aura Graft", target_permanent_ids=[weakness.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    controller, host = _w1g9_where(game, weakness)
    assert controller == 0 and host is ogre


def test_aura_graft_asks_its_caster_for_the_new_host_and_offers_legal_ones(set_pool):
    """The host is chosen as the spell resolves (no second "target"), by the
    caster, among the *other* permanents the Aura can enchant: the two
    creatures across the table, not the Bears it is on and not a Forest."""
    game = _w1g9_duel(
        set_pool, hand0=["Aura Graft"], bf0=["Grizzly Bears"],
        bf1=["Gray Ogre", "Hill Giant", "Forest"],
    )
    game.interactive_seats = {0, 1}
    bears, giant = _w1g9_on(game, 0, "Grizzly Bears"), _w1g9_on(game, 1, "Hill Giant")
    weakness = _w1g9_enchant(game, set_pool, 1, "Weakness", bears)
    assert game.queue_from_hand(
        0, "Aura Graft", target_permanent_ids=[weakness.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    prompt = game.pending_choice_of("permanent_choice")
    assert prompt is not None and prompt.player_index == 0
    offered = {p.card.name for p in game.live_permanent_choices(prompt)}
    assert offered == {"Gray Ogre", "Hill Giant"}
    assert game.confirm_permanent_choice(0, permanent_id=giant.permanent_id)
    _w1g9_resolve_stack(game)
    assert _w1g9_where(game, weakness) == (0, giant)


def test_aura_graft_keeps_an_aura_it_has_nowhere_to_move(set_pool):
    """The ruling of 2004-10-04: "If there is no legal place to move the
    enchantment, then it doesn't move but you still control it."""
    game = _w1g9_duel(
        set_pool, hand0=["Aura Graft"], bf0=["Grizzly Bears"], bf1=["Forest"],
    )
    bears = _w1g9_on(game, 0, "Grizzly Bears")
    weakness = _w1g9_enchant(game, set_pool, 1, "Weakness", bears)
    assert game.queue_from_hand(
        0, "Aura Graft", target_permanent_ids=[weakness.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_where(game, weakness) == (0, bears)


def test_aura_graft_moves_an_aura_its_caster_already_controls(set_pool):
    """The ruling of 2007-07-15: "You can target an Aura you already control
    just to move that Aura to a new permanent." And the Aura's own enchant
    line is what decides where: a land Aura goes to a land."""
    game = _w1g9_duel(
        set_pool, hand0=["Aura Graft"], bf0=["Forest", "Grizzly Bears"],
        bf1=["Forest"],
    )
    mine, theirs = _w1g9_on(game, 0, "Forest"), _w1g9_on(game, 1, "Forest")
    growth = _w1g9_enchant(game, set_pool, 0, "Wild Growth", mine)
    assert game.queue_from_hand(
        0, "Aura Graft", target_permanent_ids=[growth.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_where(game, growth) == (0, theirs)


def test_aura_graft_needs_an_aura_to_aim_at(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Aura Graft"], bf1=["Crusade"])
    crusade = _w1g9_on(game, 1, "Crusade")
    for ids in ([crusade.permanent_id], None):
        assert not game.queue_from_hand(
            0, "Aura Graft", target_permanent_ids=ids
        ).supported
    assert _w1g9_names(game.players[0].hand) == ["Aura Graft"]


@_w1g9_pytest.mark.parametrize("text, supported", [
    ("Gain control of target Aura that's attached to a permanent. Attach it "
     "to another permanent it can enchant.", True),
    ("Destroy target Aura that's attached to a permanent.", True),
    # "It" after a sentence that chose an object is that object: attaching it
    # to a second *target* is a pair of targets nothing here reads, and it
    # compiled as the spell attaching itself.
    ("Gain control of target Aura. Attach it to target creature.", False),
])
def test_the_attach_pronoun_names_what_the_sentence_in_front_took(text, supported):
    card = _w1g9_mk_card("Graft Probe", "{U}", "Instant", text)
    assert _w1g9_compile(card).supported is supported


# --- The instants that compiled on arrival, each given a game ---------------

def _w1g9_settle(game, answer=None):
    """Resolve the stack one object at a time, answering what each leaves
    owed before the next resolves. *answer* is offered every prompt first and
    returns True when it has dealt with it; the rest take their default.

    Not `resolve_stack`: an offer made to a seat nobody is sitting in does not
    hold the stack, so that helper resolves the spell underneath before the
    offer is answered - which for Divert is the whole card.
    """
    for _ in range(40):
        if game.pending_choices:
            choice = game.pending_choices[0]
            if answer is None or not answer(choice):
                game.take_choice_default(choice)
            continue
        if not game.stack:
            return
        game.resolve_top_of_stack(pause_for_choices=True)
    raise AssertionError("the stack never settled")


def test_afflict_shrinks_a_creature_and_draws(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Afflict"], bf1=["Llanowar Elves", "Forest"])
    elves, forest = _w1g9_on(game, 1, "Llanowar Elves"), _w1g9_on(game, 1, "Forest")
    assert not game.queue_from_hand(
        0, "Afflict", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert game.queue_from_hand(
        0, "Afflict", target_permanent_ids=[elves.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g9_names(game.players[1].graveyard) == ["Llanowar Elves"]
    assert len(game.players[0].hand) == 1


def test_afflict_draws_nothing_once_its_only_target_is_gone(set_pool):
    """CR 608.2b: every target illegal, so the spell does not resolve - the
    second line is not a consolation prize."""
    game = _w1g9_duel(
        set_pool, hand0=["Afflict"], hand1=["Unsummon"], bf1=["Grizzly Bears"],
    )
    bears = _w1g9_on(game, 1, "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Afflict", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.queue_from_hand(
        1, "Unsummon", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert game.players[0].hand == []


def test_peek_shows_its_caster_a_hand_without_telling_the_table(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Peek"], hand1=["Grizzly Bears", "Forest"])
    game.interactive_seats = {0, 1}
    assert game.queue_from_hand(0, "Peek", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    shown = game.pending_choices[0]
    assert (shown.kind, shown.player_index) == ("hand_reveal", 0)
    assert len(game.players[0].hand) == 1, "and it drew"
    assert not any("Grizzly Bears" in line for line in game.log), game.log


def test_vivify_makes_a_land_a_creature_that_is_still_a_land(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Vivify"], bf0=["Forest", "Grizzly Bears"])
    forest, bears = _w1g9_on(game, 0, "Forest"), _w1g9_on(game, 0, "Grizzly Bears")
    assert not game.queue_from_hand(
        0, "Vivify", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.queue_from_hand(
        0, "Vivify", target_permanent_ids=[forest.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert forest.is_creature and forest.has_type("land") and forest.has_type("forest")
    assert (forest.effective_power, forest.effective_toughness) == (3, 3)
    assert game.tap_land_for_mana(0, "Forest", permanent_id=forest.permanent_id)
    assert len(game.players[0].hand) == 1
    game.resolve_cleanup_step(0)
    game._recompute_continuous_effects()
    assert not forest.is_creature


def _w1g9_divert_table(set_pool, payer_mana):
    game = _w1g9_duel(
        set_pool, hand0=["Divert"], hand1=["Lightning Bolt"],
        bf0=["Grizzly Bears"], bf1=["Gray Ogre"], costs=True,
    )
    game.interactive_seats = {0, 1}
    game.players[0].mana_pool.update({"U": 1})
    game.players[1].mana_pool.update({"R": 1 + payer_mana})
    bears, ogre = _w1g9_on(game, 0, "Grizzly Bears"), _w1g9_on(game, 1, "Gray Ogre")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.queue_from_hand(0, "Divert", target_stack_index=0).supported
    return game, bears, ogre


def test_divert_turns_a_spell_onto_the_target_its_caster_names(set_pool):
    """"Change the target of target spell with a single target unless that
    spell's controller pays {2}." Unpaid, Divert's controller chooses among the
    *other* legal targets (CR 115.7a) and the Bolt lands there."""
    game, bears, ogre = _w1g9_divert_table(set_pool, payer_mana=2)

    def answer(choice):
        if choice.kind == "optional_pay":
            assert choice.player_index == 1, "the Bolt's controller is asked"
            return game.confirm_optional_pay(1, accept=False)
        if choice.kind == "retarget_choice":
            assert choice.player_index == 0
            names = [option["name"] for option in choice.data["options"]]
            assert "Grizzly Bears" not in names and "Gray Ogre" in names
            return game.confirm_retarget_choice(0, names.index("Gray Ogre"))
        return False

    _w1g9_settle(game, answer)
    game.check_state_based_actions()
    assert bears in game.all_permanents() and ogre not in game.all_permanents()
    assert game.players[1].mana_pool["R"] == 2


def test_divert_does_nothing_to_a_spell_whose_controller_pays(set_pool):
    game, bears, _ogre = _w1g9_divert_table(set_pool, payer_mana=2)
    _w1g9_settle(
        game,
        lambda c: c.kind == "optional_pay" and game.confirm_optional_pay(1, accept=True),
    )
    game.check_state_based_actions()
    assert bears not in game.all_permanents()
    assert game.players[1].mana_pool["R"] == 0


def test_divert_cannot_be_aimed_at_a_spell_with_no_target(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Divert"], hand1=["Wrath of God"])
    assert game.queue_from_hand(1, "Wrath of God").supported
    assert not game.queue_from_hand(0, "Divert", target_stack_index=0).supported
    assert _w1g9_names(game.players[0].hand) == ["Divert"]

# ==== end W1G9 ======================================================
