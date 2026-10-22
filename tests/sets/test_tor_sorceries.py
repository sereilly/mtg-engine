"""Torment sorceries.

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


def _w1g2_table(set_pool, *, hand0=(), gy0=(), gy1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names (TOR over LEA)."""
    pool = {**set_pool("LEA"), **set_pool("TOR")}
    seats = [
        _w1g2_PlayerState(
            name=f"P{seat}", life=20, hand=[pool[n] for n in hand],
            graveyard=[pool[n] for n in gy], library=[pool["Forest"]] * 10,
        )
        for seat, (hand, gy) in enumerate(((hand0, gy0), ((), gy1)))
    ]
    game = _w1g2_Game(players=seats)
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g2_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g2_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g2_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def _w1g2_gy(game, seat):
    return sorted(card.name for card in game.players[seat].graveyard)


#: Six cards and seven: threshold is "seven or more cards in your graveyard"
#: (CR 207.2c makes the word itself mean nothing), asked as the spell resolves,
#: when the spell is on the stack and not yet in that graveyard.
_W1G2_SHORT = ["Forest"] * 6
_W1G2_THRESHOLD = ["Forest"] * 7


# --- Kamahl's Sledge: the replaced sentence, and then its target's controller --

def test_kamahls_sledge_deals_four_to_the_creature_alone_without_threshold(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Kamahl's Sledge"], gy0=_W1G2_SHORT,
        bf1=["Craw Wurm", "Grizzly Bears"],
    )
    wurm = _w1g2_on_board(game, 1, "Craw Wurm")
    assert [t["name"] for t in game.cast_target_spec(
        0, game.players[0].hand[0])["valid_targets"]
    ] == ["Craw Wurm", "Grizzly Bears"]
    assert game.cast_from_hand(
        0, "Kamahl's Sledge", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 1) == ["Grizzly Bears"]
    assert [p.life for p in game.players] == [20, 20]


def test_kamahls_sledge_with_threshold_also_hits_that_creatures_controller(set_pool):
    """"…instead Kamahl's Sledge deals 4 damage to that creature and 4 damage
    to that creature's controller." One announcement (CR 601.2c) — the
    creature — and the seat is whoever controls it, the caster included."""
    game = _w1g2_table(
        set_pool, hand0=["Kamahl's Sledge"], gy0=_W1G2_THRESHOLD,
        bf1=["Craw Wurm"],
    )
    wurm = _w1g2_on_board(game, 1, "Craw Wurm")
    assert game.cast_from_hand(
        0, "Kamahl's Sledge", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 1) == []
    assert [p.life for p in game.players] == [20, 16]

    own = _w1g2_table(
        set_pool, hand0=["Kamahl's Sledge"], gy0=_W1G2_THRESHOLD,
        bf0=["Craw Wurm"],
    )
    assert own.cast_from_hand(
        0, "Kamahl's Sledge",
        target_permanent_ids=[_w1g2_on_board(own, 0, "Craw Wurm").permanent_id],
    ).supported
    _w1g2_resolve_stack(own)
    assert [p.life for p in own.players] == [16, 20]


def test_kamahls_sledge_does_nothing_once_its_one_target_is_gone(set_pool):
    """CR 608.2b: every target illegal, so neither arm runs — no damage to a
    controller the creature no longer has."""
    game = _w1g2_table(
        set_pool, hand0=["Kamahl's Sledge"], gy0=_W1G2_THRESHOLD,
        bf1=["Craw Wurm"],
    )
    wurm = _w1g2_on_board(game, 1, "Craw Wurm")
    assert game.queue_from_hand(
        0, "Kamahl's Sledge", target_permanent_ids=[wurm.permanent_id],
    ).supported
    game.remove_from_battlefield(wurm)
    _w1g2_resolve_stack(game)
    assert [p.life for p in game.players] == [20, 20]


# --- Rancid Earth: the replaced sentence, and then a sweep -----------------

def test_rancid_earth_destroys_the_land_alone_without_threshold(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Rancid Earth"], gy0=_W1G2_SHORT,
        bf0=["Grizzly Bears"], bf1=["Mountain", "Grizzly Bears"],
    )
    mountain = _w1g2_on_board(game, 1, "Mountain")
    assert game.cast_from_hand(
        0, "Rancid Earth", target_permanent_ids=[mountain.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 1) == ["Grizzly Bears"]
    assert [p.life for p in game.players] == [20, 20]
    assert all(p.damage_marked == 0 for p in game.all_permanents())


def test_rancid_earth_with_threshold_also_deals_one_to_each_creature_and_player(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Rancid Earth"], gy0=_W1G2_THRESHOLD,
        bf0=["Grizzly Bears"], bf1=["Mountain", "Mons's Goblin Raiders"],
    )
    mountain = _w1g2_on_board(game, 1, "Mountain")
    assert game.cast_from_hand(
        0, "Rancid Earth", target_permanent_ids=[mountain.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert [p.life for p in game.players] == [19, 19]
    assert _w1g2_names(game, 1) == [], "the land destroyed, the 1/1 dead of 1 damage"
    assert _w1g2_on_board(game, 0, "Grizzly Bears").damage_marked == 1


def test_rancid_earth_does_nothing_once_its_land_is_gone(set_pool):
    """The damage is part of the arm that destroys "that land", and with the
    one target illegal the spell does not resolve at all (CR 608.2b)."""
    game = _w1g2_table(
        set_pool, hand0=["Rancid Earth"], gy0=_W1G2_THRESHOLD,
        bf1=["Mountain", "Grizzly Bears"],
    )
    mountain = _w1g2_on_board(game, 1, "Mountain")
    assert game.queue_from_hand(
        0, "Rancid Earth", target_permanent_ids=[mountain.permanent_id],
    ).supported
    game.remove_from_battlefield(mountain)
    _w1g2_resolve_stack(game)
    assert [p.life for p in game.players] == [20, 20]
    assert _w1g2_on_board(game, 1, "Grizzly Bears").damage_marked == 0


# --- Cleansing Meditation: what the sweep destroyed, returned ----------------

def test_cleansing_meditation_destroys_every_enchantment_without_threshold(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Cleansing Meditation"], gy0=_W1G2_SHORT[:5],
        bf0=["Castle"], bf1=["Crusade"],
    )
    assert game.cast_from_hand(0, "Cleansing Meditation").supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 0) == [] and _w1g2_names(game, 1) == []
    assert "Castle" in _w1g2_gy(game, 0) and _w1g2_gy(game, 1) == ["Crusade"]


def test_cleansing_meditation_with_threshold_returns_only_your_own_destroyed_cards(set_pool):
    """"…instead destroy all enchantments, then return all cards in **your
    graveyard destroyed this way** to the battlefield." The opponent's
    enchantment went to their graveyard and stays; a copy that was already in
    yours before the sweep is not a card destroyed this way and stays too."""
    game = _w1g2_table(
        set_pool, hand0=["Cleansing Meditation"],
        gy0=_W1G2_SHORT + ["Castle"],
        bf0=["Castle", "Crusade"], bf1=["Crusade"],
    )
    assert game.cast_from_hand(0, "Cleansing Meditation").supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 0) == ["Castle", "Crusade"]
    assert _w1g2_names(game, 1) == [] and _w1g2_gy(game, 1) == ["Crusade"]
    assert _w1g2_gy(game, 0).count("Castle") == 1, "the older copy stays put"
    assert any(
        "P0 returned Castle to the battlefield" in line for line in game.log
    )


def test_a_destroyed_this_way_return_with_no_destroy_in_front_is_refused():
    """The record is the producer discipline every "this way" keeps: with no
    step of the effect destroying anything the words name an empty set, and
    read as the plain sweep they would return the whole pile."""
    from engine.grammar import compile_line

    assert not compile_line(
        "Return all cards in your graveyard destroyed this way to the battlefield."
    ).usable
    assert compile_line(
        "Destroy all artifacts, then return all cards in your graveyard "
        "destroyed this way to the battlefield."
    ).usable

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4_pytest

from engine import Game as _W1g4Game, PlayerState as _W1g4PlayerState
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_skullscorch(set_pool, their_hand, *, interactive=(), accept=None):
    """Skullscorch cast at P2 holding *their_hand* Giant Growths."""
    lea = set_pool("LEA")
    game = _W1g4Game(players=[
        _W1g4PlayerState("P1", library=[lea["Swamp"]] * 5,
                         hand=[set_pool("TOR")["Skullscorch"]]),
        _W1g4PlayerState("P2", library=[lea["Swamp"]] * 5,
                         hand=[lea["Giant Growth"]] * their_hand),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_step = "precombat_main"
    assert game.cast_from_hand(0, "Skullscorch", target_player_index=1).details == "resolved"
    if accept is not None:
        while game.stack and not game.pending_choices:
            game.resolve_top_of_stack()
        assert [(c.kind, c.player_index) for c in game.pending_choices] == [("optional_pay", 1)]
        assert game.confirm_optional_pay(1, accept=accept)
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game


@_w1g4_pytest.mark.parametrize("accept, life, hand", [(True, 16, 3), (False, 20, 1)])
def test_w1g4_skullscorch_the_target_chooses_damage_or_the_discard(set_pool, accept, life, hand):
    """"Target player discards two cards at random unless that player has
    Skullscorch deal 4 damage to them." The offer is the target's."""
    game = _w1g4_skullscorch(set_pool, 3, interactive=(1,), accept=accept)

    assert game.players[1].life == life
    assert len(game.players[1].hand) == hand


@_w1g4_pytest.mark.parametrize("held, life, hand", [(0, 20, 0), (1, 20, 0)])
def test_w1g4_skullscorch_a_seat_nobody_asks_keeps_its_life_over_a_short_hand(
    set_pool, held, life, hand
):
    """A seat nobody asks weighs the two losses (``toll_decline_is_smaller_loss``):
    two random cards out of a hand holding none or one are worth less than 4
    life, so it takes the discard. Unpriced, the random discard left the
    standing policy — pay tolls — to take 4 damage to protect an empty hand."""
    game = _w1g4_skullscorch(set_pool, held)

    assert game.players[1].life == life
    assert len(game.players[1].hand) == hand
    assert any("declined Skullscorch" in line for line in game.log)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

import random as _w1g5_random

from engine import Game as _w1g5_Game
from engine import PlayerState as _w1g5_PlayerState
from engine.cast_costs import cast_announces_x as _w1g5_cast_announces_x
from engine.models import Permanent as _w1g5_Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_cast_spec as _w1g5_derive_cast_spec
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import _nosick as _w1g5_nosick
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_game(spell, *, hand=(), graveyard=(), bf0=(), bf1=(), library=None):
    """Seat 0 on its own main phase holding *spell* first in hand, mana free."""
    filler = _w1g5_mk_card(name="W1G5 Filler", type_line="Land")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState(
            "A", library=list(library) if library is not None else [filler] * 10,
            hand=[spell, *hand], graveyard=list(graveyard),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf0],
        ),
        _w1g5_PlayerState(
            "B", library=[filler] * 10,
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf1],
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


def _w1g5_names(cards):
    return [card.name for card in cards]


def test_w1g5_restless_dreams_at_x_zero_is_cast_at_an_empty_graveyard(set_pool):
    """"Return **X** target creature cards": at an X of zero it names nobody
    (CR 601.2c), so an empty graveyard is a legal cast that discards and
    returns nothing — the per-kind arm refused it "no valid target"."""
    dreams = set_pool("TOR")["Restless Dreams"]
    forest = set_pool("LEA")["Forest"]
    game = _w1g5_game(dreams, hand=[forest])

    result = game.cast_from_hand(0, dreams.name, x_value=0)
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    assert _w1g5_names(game.players[0].hand) == ["Forest"]
    assert _w1g5_names(game.players[0].graveyard) == ["Restless Dreams"]


def test_w1g5_restless_dreams_at_x_two_discards_the_two_named_and_returns_two(set_pool):
    """X=2: the caster names both discards (the second was refused "discards 1
    card(s)" — the gate compared with the printed field, not the announced X)
    and two creature cards come back."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Restless Dreams"]
    forest, bolt, island = lea["Forest"], lea["Lightning Bolt"], lea["Island"]
    bears, giant = lea["Grizzly Bears"], lea["Hill Giant"]
    game = _w1g5_game(
        dreams, hand=[forest, bolt, island], graveyard=[bears, giant, forest],
    )

    result = game.cast_from_hand(
        0, dreams.name, x_value=2, target_permanent_index=[0, 1],
        cost_hand_index=2, cost_other_hand_indices=[3],
    )
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    assert sorted(_w1g5_names(game.players[0].hand)) == [
        "Forest", "Grizzly Bears", "Hill Giant",
    ]
    assert sorted(_w1g5_names(game.players[0].graveyard)) == [
        "Forest", "Island", "Lightning Bolt", "Restless Dreams",
    ]
    assert "A discarded Lightning Bolt to cast Restless Dreams" in game.log
    assert "A discarded Island to cast Restless Dreams" in game.log


def test_w1g5_restless_dreams_at_x_zero_charges_no_card_the_picker_named(set_pool):
    """The browser's discard picker is sized by the printed count (one card)
    whatever X is, so an X of zero arrives naming a card: accepted, and not
    charged — the payment discards X. The cost spec says an X is owed
    (``announces_x``) for the client that sizes the picker by it."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Restless Dreams"]
    assert _w1g5_derive_cast_spec(dreams, _w1g5_compile(dreams))["cost_spec"][
        "announces_x"
    ]
    game = _w1g5_game(dreams, hand=[lea["Forest"]])

    result = game.cast_from_hand(0, dreams.name, x_value=0, cost_hand_index=1)
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    assert _w1g5_names(game.players[0].hand) == ["Forest"]


def test_w1g5_restless_dreams_at_x_two_needs_two_creature_cards(set_pool):
    """The other direction: once X is one or more the count is exact."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Restless Dreams"]
    game = _w1g5_game(
        dreams, hand=[lea["Forest"], lea["Island"]],
        graveyard=[lea["Grizzly Bears"], lea["Forest"]],
    )

    result = game.cast_from_hand(0, dreams.name, x_value=2, target_permanent_index=[0])

    assert not result.supported
    assert _w1g5_names(game.players[0].hand) == ["Restless Dreams", "Forest", "Island"]


def test_w1g5_devastating_dreams_announces_x_and_charges_it_at_random(set_pool):
    """"Discard X cards **at random**" is one clause with two modifiers: the X
    is announced (CR 107.3a) and the discards are chance's, so a named card
    is not what goes. Each player then sacrifices X lands and every creature
    is dealt X."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Devastating Dreams"]
    assert _w1g5_cast_announces_x(dreams)
    forest, mountain, island = lea["Forest"], lea["Mountain"], lea["Island"]
    bears, giant = lea["Grizzly Bears"], lea["Hill Giant"]
    hand = [forest, lea["Lightning Bolt"], island, giant]
    game = _w1g5_game(
        dreams, hand=hand, bf0=[mountain, mountain, forest, bears],
        bf1=[island, island, island, giant, bears],
    )
    _w1g5_random.seed(11)

    result = game.cast_from_hand(0, dreams.name, x_value=2)
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    a, b = game.players
    assert len(a.hand) == 2  # four held, two discarded at random
    discarded = [line for line in game.log if "to cast Devastating Dreams" in line]
    assert len(discarded) == 2
    lands = lambda seat: [  # noqa: E731
        p.card.name for p in game.controlled_by(seat) if p.has_type("land")
    ]
    assert len(lands(0)) == 1 and len(lands(1)) == 1
    # Two damage to each creature: the Bears die, the Giant (3/3) lives.
    creatures = lambda seat: [  # noqa: E731
        p.card.name for p in game.controlled_by(seat) if p.is_creature
    ]
    assert creatures(0) == [] and creatures(1) == ["Hill Giant"]
    assert a.life == 20 and b.life == 20


def test_w1g5_devastating_dreams_x_is_bounded_by_the_hand(set_pool):
    """CR 601.2h: X=3 with two other cards in hand cannot be paid."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Devastating Dreams"]
    game = _w1g5_game(dreams, hand=[lea["Forest"], lea["Island"]], bf0=[lea["Mountain"]])

    result = game.cast_from_hand(0, dreams.name, x_value=3)

    assert not result.supported
    assert _w1g5_names(game.players[0].hand) == ["Devastating Dreams", "Forest", "Island"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Mountain"]


def test_w1g5_devastating_dreams_asks_an_interactive_seat_which_lands(set_pool):
    """"…lands **of their choice**": a person is asked, through the standing
    sacrifice prompt, and the spell waits on the stack for the answer."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Devastating Dreams"]
    game = _w1g5_game(
        dreams, hand=[lea["Forest"]], bf0=[lea["Mountain"]],
        bf1=[lea["Island"], lea["Forest"]],
    )
    game.interactive_seats = {1}

    result = game.cast_from_hand(0, dreams.name, x_value=1)

    assert result.supported, result.details
    owed = [choice for choice in game.pending_choices if choice.kind == "sacrifice"]
    assert [choice.player_index for choice in owed] == [1]
    assert game.stack, "the spell resolves only once the choice is made"


def test_w1g5_mind_sludge_discards_one_card_per_swamp_its_caster_controls(set_pool):
    """"…a card for each Swamp **you** control": the caster's Swamps, counted
    as the spell resolves — the target's own Swamps are not counted."""
    lea = set_pool("LEA")
    sludge = set_pool("TOR")["Mind Sludge"]
    swamp = lea["Swamp"]
    game = _w1g5_game(sludge, bf0=[swamp, swamp, swamp, lea["Forest"]], bf1=[swamp, swamp])
    game.players[1].hand = [
        lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Island"], lea["Forest"], swamp,
    ]

    result = game.cast_from_hand(0, sludge.name, target_player_index=1)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert result.supported, result.details
    assert len(game.players[1].hand) == 2
    assert len(game.players[1].graveyard) == 3
    assert "B must choose 3 card(s) to discard" in game.log


def test_w1g5_mind_sludge_asks_a_person_for_as_many_cards_as_swamps(set_pool):
    """The discarding player chooses (the standing discard prompt), sized by
    the count — two Swamps, two cards."""
    lea = set_pool("LEA")
    sludge = set_pool("TOR")["Mind Sludge"]
    game = _w1g5_game(sludge, bf0=[lea["Swamp"], lea["Swamp"]])
    game.players[1].hand = [lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Island"]]
    game.interactive_seats = {1}

    game.cast_from_hand(0, sludge.name, target_player_index=1)
    game.resolve_top_of_stack()
    owed = game.pending_choice_of("discard", 1)

    assert owed is not None and owed.data["count"] == 2
    assert game.resolve_pending_choice("discard", 1, hand_indices=[0, 2], to_library=False)
    assert _w1g5_names(game.players[1].hand) == ["Grizzly Bears"]


def test_w1g5_mind_sludge_with_no_swamp_discards_nothing(set_pool):
    lea = set_pool("LEA")
    sludge = set_pool("TOR")["Mind Sludge"]
    game = _w1g5_game(sludge, bf0=[lea["Forest"]], bf1=[lea["Swamp"]])
    game.players[1].hand = [lea["Lightning Bolt"], lea["Island"]]

    game.cast_from_hand(0, sludge.name, target_player_index=1)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(game.players[1].hand) == 2


def _w1g5_breakthrough_game(set_pool, *, interactive=False):
    lea = set_pool("LEA")
    library = [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Land") for i in range(10)]
    game = _w1g5_game(
        set_pool("TOR")["Breakthrough"],
        hand=[lea["Lightning Bolt"], lea["Grizzly Bears"]], library=library,
    )
    if interactive:
        game.interactive_seats = {0}
    return game


def test_w1g5_breakthrough_at_x_zero_draws_four_and_discards_the_whole_hand(set_pool):
    game = _w1g5_breakthrough_game(set_pool)

    result = game.cast_from_hand(0, "Breakthrough", x_value=0)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert result.supported, result.details
    assert game.players[0].hand == []
    # Two held, four drawn, all six discarded, and the spell itself.
    assert len(game.players[0].graveyard) == 7
    assert len(game.players[0].library) == 6


def test_w1g5_breakthrough_keeps_x_of_its_choosers_choice(set_pool):
    """X=2: six cards in hand after the draw, so four are discarded — and the
    person chooses which, through the standing discard prompt."""
    game = _w1g5_breakthrough_game(set_pool, interactive=True)

    game.cast_from_hand(0, "Breakthrough", x_value=2)
    game.resolve_top_of_stack()
    owed = game.pending_choice_of("discard", 0)

    assert owed is not None and owed.data["count"] == 4
    assert len(game.players[0].hand) == 6
    # Keep the Bolt and the Bears: discard the four drawn cards.
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[2, 3, 4, 5], to_library=False,
    )
    assert _w1g5_names(game.players[0].hand) == ["Lightning Bolt", "Grizzly Bears"]


def test_w1g5_breakthrough_with_x_above_the_hand_discards_nothing(set_pool):
    game = _w1g5_breakthrough_game(set_pool)

    game.cast_from_hand(0, "Breakthrough", x_value=10)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(game.players[0].hand) == 6
    assert _w1g5_names(game.players[0].graveyard) == ["Breakthrough"]

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState  # noqa: E402
from engine import ai_casts as _w1g6_ai_casts  # noqa: E402
from tests.helpers import resolve_stack as _w1g6_resolve_stack  # noqa: E402


def _w1g6_promise_table(set_pool, catalog_by_name, mine, theirs) -> _W1G6Game:
    """Seat 0 holds *mine* (TOR first), seat 1 holds *theirs*; libraries of
    Islands; mana off."""
    def card(name):
        return set_pool("TOR").get(name) or catalog_by_name[name]

    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", hand=[card(n) for n in mine],
                         library=[catalog_by_name["Island"]] * 5),
        _W1G6PlayerState(name="P2", hand=[card(n) for n in theirs],
                         library=[catalog_by_name["Island"]] * 5,
                         graveyard=[catalog_by_name["Island"]] * 3),
    ])
    game.enforce_mana_costs = False
    return game


def test_w1g6_overmaster_s_next_instant_cannot_be_countered_and_only_that_one(
    set_pool, catalog_by_name,
):
    """"The next instant or sorcery spell you cast this turn can't be
    countered. Draw a card." A creature spell cast in between is not what it
    names and is countered as usual; the next instant is protected from
    Counterspell (which resolves and does nothing — the Bolt still hits),
    and the instant after it is not."""
    game = _w1g6_promise_table(
        set_pool, catalog_by_name,
        ["Overmaster", "Grizzly Bears", "Lightning Bolt", "Lightning Bolt"],
        ["Counterspell"] * 3,
    )
    assert game.cast_from_hand(0, "Overmaster").supported
    _w1g6_resolve_stack(game)
    assert len(game.players[0].hand) == 4, "Overmaster drew a card"

    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    # The AI does not spend a counterspell on a spell it cannot counter.
    counterspell = game.players[1].hand[0]
    assert _w1g6_ai_casts._cast_candidate(game, 1, counterspell, 0) is None
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17
    assert any("can't be countered (Overmaster)" in line for line in game.log)

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert _w1g6_ai_casts._cast_candidate(game, 1, game.players[1].hand[0], 0) is not None
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17, "the second Bolt was countered"


def test_w1g6_overmaster_also_stops_a_counter_that_asks_for_a_payment(set_pool, catalog_by_name):
    """"Counter target spell unless its controller pays …" (Circular Logic)
    against the protected spell asks for nothing: CR 701.6a — a spell that
    can't be countered isn't, so there is no payment to offer."""
    game = _w1g6_promise_table(
        set_pool, catalog_by_name, ["Overmaster", "Lightning Bolt"], ["Circular Logic"],
    )
    assert game.cast_from_hand(0, "Overmaster").supported
    _w1g6_resolve_stack(game)
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.cast_from_hand(1, "Circular Logic", target_stack_index=0).supported
    assert not game.pending_choices
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17


def test_w1g6_insist_s_promise_is_for_creature_spells_and_ends_with_the_turn(
    set_pool, catalog_by_name,
):
    """"The next creature spell you cast this turn can't be countered." An
    instant cast in between is countered as usual; the creature is not. A
    promise nobody spent is gone at the next turn."""
    game = _w1g6_promise_table(
        set_pool, catalog_by_name,
        ["Insist", "Lightning Bolt", "Grizzly Bears"], ["Counterspell"] * 2,
    )
    assert game.cast_from_hand(0, "Insist").supported
    _w1g6_resolve_stack(game)
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 20
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(0)]

    game = _w1g6_promise_table(
        set_pool, catalog_by_name, ["Insist", "Grizzly Bears"], ["Counterspell"],
    )
    assert game.cast_from_hand(0, "Insist").supported
    _w1g6_resolve_stack(game)
    game.turn += 1
    game.start_turn(1)
    game.turn += 1
    game.start_turn(0)
    game.players[0].hand.append(catalog_by_name["Grizzly Bears"])
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]


def test_w1g6_a_copy_of_the_protected_spell_is_not_protected(set_pool, catalog_by_name):
    """CR 707.10: a copy is not cast, so it spends no promise, and the effect
    on the original is not a copiable value. Forked, the protected Bolt's copy
    is countered and the original is not."""
    game = _w1g6_promise_table(
        set_pool, catalog_by_name, ["Overmaster", "Lightning Bolt", "Fork"],
        ["Counterspell", "Counterspell"],
    )
    assert game.cast_from_hand(0, "Overmaster").supported
    _w1g6_resolve_stack(game)
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported
    game.resolve_top_of_stack()
    copy = game.stack[-1]
    assert copy.is_copy and copy.uncounterable_by is None
    # Engine (bottom-first) indices: 0 is the original, 1 the copy.
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=1).supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17, "the original hit, the copy was countered"
    assert any("countered Lightning Bolt (copy)" in line for line in game.log)

from engine.models import Permanent as _W1G6Permanent  # noqa: E402


def test_w1g6_chainer_s_edict_and_its_flashback(set_pool, catalog_by_name):
    """"Target player sacrifices a creature of their choice. Flashback
    {5}{B}{B}." Cast from hand, then flashed back: two creatures go, and the
    card ends in exile."""
    game = _w1g6_promise_table(set_pool, catalog_by_name, ["Chainer's Edict"], [])
    for name in ("Grizzly Bears", "Hill Giant"):
        game._put_permanent_onto_battlefield(
            1, _W1G6Permanent(card=catalog_by_name[name]), None
        )
    assert game.cast_from_hand(0, "Chainer's Edict", target_player_index=1).supported
    _w1g6_resolve_stack(game)
    assert len(list(game.controlled_by(1))) == 1
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"B": 2, "C": 5})
    assert game.cast_from_hand(
        0, "Chainer's Edict", target_player_index=1, from_zone="graveyard",
    ).supported
    _w1g6_resolve_stack(game)
    assert list(game.controlled_by(1)) == []
    assert [c.name for c in game.players[0].exile] == ["Chainer's Edict"]


def test_w1g6_acorn_harvest_and_crippling_fatigue_flash_back_for_mana_and_life(
    set_pool, catalog_by_name,
):
    """"Flashback--{1}{G}, Pay 3 life." / "Flashback--{1}{B}, Pay 3 life." The
    life is paid with the mana: two 1/1 green Squirrels for {1}{G} and 3
    life, and -2/-2 on a Hill Giant for {1}{B} and 3 more."""
    game = _w1g6_promise_table(set_pool, catalog_by_name, [], [])
    game.players[0].graveyard.extend(
        set_pool("TOR")[name] for name in ("Acorn Harvest", "Crippling Fatigue")
    )
    giant = _W1G6Permanent(card=catalog_by_name["Hill Giant"])
    game._put_permanent_onto_battlefield(1, giant, None)
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"G": 1, "C": 1})
    assert game.cast_from_hand(0, "Acorn Harvest", from_zone="graveyard").supported
    _w1g6_resolve_stack(game)
    squirrels = list(game.controlled_by(0))
    assert [(p.effective_power, p.effective_toughness) for p in squirrels] == [(1, 1), (1, 1)]
    assert all("G" in p.effective_colors for p in squirrels)
    assert game.players[0].life == 17
    game.players[0].mana_pool.update({"B": 1, "C": 1})
    assert game.cast_from_hand(
        0, "Crippling Fatigue", target_permanent_ids=[giant.permanent_id],
        target_player_index=1, from_zone="graveyard",
    ).supported
    _w1g6_resolve_stack(game)
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)
    assert game.players[0].life == 14
    assert sorted(c.name for c in game.players[0].exile) == ["Acorn Harvest", "Crippling Fatigue"]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve_stack


def _w1g7_flash_board(set_pool, *, from_graveyard=False):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    flash = tor["Flash of Defiance"]
    ogre = _w1g7_nosick(_w1g7_Permanent(card=lea["Gray Ogre"]))
    seat0 = _w1g7_PlayerState(
        name="P0", battlefield=[ogre],
        hand=[] if from_graveyard else [flash],
        graveyard=[flash] if from_graveyard else [],
    )
    seat1 = _w1g7_PlayerState(name="P1", battlefield=[
        _w1g7_Permanent(card=lea[name])
        for name in ("Grizzly Bears", "Savannah Lions", "Scathe Zombies")
    ])
    game = _w1g7_Game(players=[seat0, seat1])
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    return game, flash, ogre


def _w1g7_attack_with(game, ogre):
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"


def test_w1g7_flash_of_defiance_stops_green_and_white_blockers_only(set_pool):
    """"Green creatures and white creatures can't block this turn." The noun
    phrase is a union of two colours (CR 105.2): the Bears and the Lions may not
    block, the black Zombies still may."""
    game, _, ogre = _w1g7_flash_board(set_pool)
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Flash of Defiance").supported
    _w1g7_resolve_stack(game)
    _w1g7_attack_with(game, ogre)

    bears, lions, zombies = game.players[1].battlefield
    ok, why = game.declare_blockers(1, {0: 0})
    assert not ok and "Grizzly Bears" in why
    ok, why = game.declare_blockers(1, {1: 0})
    assert not ok and "Savannah Lions" in why
    ok, why = game.declare_blockers(1, {2: 0})
    assert ok, why
    assert game._can_block_attacker(zombies, ogre)


def test_w1g7_flash_of_defiance_flashback_pays_mana_and_three_life(set_pool):
    """"Flashback—{1}{R}, Pay 3 life." Cast from the graveyard for exactly
    that, it restricts the same blockers and is exiled."""
    game, flash, ogre = _w1g7_flash_board(set_pool, from_graveyard=True)
    game.enforce_mana_costs = True
    game.players[0].mana_pool["R"] = 2
    assert game.cast_from_hand(0, "Flash of Defiance", from_zone="graveyard").supported
    _w1g7_resolve_stack(game)

    assert game.players[0].life == 17
    assert not any(game.players[0].mana_pool.values())
    assert game.players[0].exile == [flash] and flash not in game.players[0].graveyard
    _w1g7_attack_with(game, ogre)
    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok
    ok, why = game.declare_blockers(1, {2: 0})
    assert ok, why


def test_w1g7_flash_of_defiance_ends_with_the_turn(set_pool):
    """"This turn": the cleanup sweep drops the entry, and the next turn the
    Bears block again."""
    game, _, ogre = _w1g7_flash_board(set_pool)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Flash of Defiance")
    _w1g7_resolve_stack(game)
    bears = game.players[1].battlefield[0]
    assert not game._can_block_attacker(bears, ogre)
    game.resolve_cleanup_step(0)
    assert game.blocking_restrictions_until_eot == []
    assert game._can_block_attacker(bears, ogre)

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

import pytest as _w1g8_pytest

from engine import Game as _W1G8Game, PlayerState as _W1G8Player
from engine.models import Permanent as _W1G8Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_eddy_table(set_pool, *, lands=True):
    """Churning Eddy in seat 0's hand; a Grizzly Bears and a Forest for
    seat 1, a Hill Giant and an Island for seat 0."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Churning Eddy"]]),
        _W1G8Player("B"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    placed = {}
    for seat, key, name in (
        (1, "bears", "Grizzly Bears"), (0, "giant", "Hill Giant"),
        (1, "forest", "Forest"), (0, "island", "Island"),
    ):
        if not lands and key in ("forest", "island"):
            continue
        placed[key] = _W1G8Permanent(card=lea[name])
        game._put_permanent_onto_battlefield(seat, placed[key], None)
    return game, placed


def test_w1g8_churning_eddy_returns_a_creature_and_a_land_on_two_boards(set_pool):
    """"Return target creature and target land to their owners' hands." It
    refused at the parse ("no spell picks two targets from one verb"): two
    targets of one verb are one announcement (CR 601.2c), described as ordered
    roles the way Fumarole's destroy is. The two need not sit on one
    battlefield, and each goes to its own owner's hand (CR 400.3)."""
    game, placed = _w1g8_eddy_table(set_pool)
    assert _w1g8_compile(set_pool("TOR")["Churning Eddy"]).supported

    spec = game.cast_target_spec(0, set_pool("TOR")["Churning Eddy"])
    assert [role["kind"] for role in spec["roles"]] == ["creature", "land"]
    assert sorted(o["name"] for o in spec["valid_targets"]) == [
        "Grizzly Bears", "Hill Giant",
    ], "the creature slot offers creatures and nothing else"

    result = game.cast_from_hand(
        0, "Churning Eddy",
        target_permanent_ids=[placed["bears"].permanent_id, placed["island"].permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert game.is_on_battlefield(placed["giant"])
    assert game.is_on_battlefield(placed["forest"])


def test_w1g8_churning_eddy_needs_both_targets_to_be_cast(set_pool):
    """Every target is chosen as part of one announcement: with no land on the
    battlefield there is no legal announcement, and the spell is not cast
    (CR 601.2c) — not cast and half-resolved."""
    game, placed = _w1g8_eddy_table(set_pool, lands=False)
    refused = game.cast_from_hand(
        0, "Churning Eddy", target_permanent_ids=[placed["bears"].permanent_id],
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].hand] == ["Churning Eddy"]
    assert game.is_on_battlefield(placed["bears"])


def test_w1g8_churning_eddy_still_returns_the_target_that_is_left(set_pool):
    """CR 608.2b: one illegal target of two leaves the other to be returned —
    and the departed slot is not filled by whatever slid into its place."""
    game, placed = _w1g8_eddy_table(set_pool)
    result = game.queue_from_hand(
        0, "Churning Eddy",
        target_permanent_ids=[placed["bears"].permanent_id, placed["forest"].permanent_id],
    )
    assert result.supported, result.details
    game.remove_from_battlefield(placed["bears"])
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Forest"]
    assert game.is_on_battlefield(placed["giant"]), "not a stand-in for the Bears"
    assert game.is_on_battlefield(placed["island"])


def _w1g8_evolution_table(set_pool):
    """Parallel Evolution in seat 0's hand. Seat 0 controls a Saproling token
    and a nontoken Grizzly Bears; seat 1 controls a token copy of a Hill
    Giant (a copy effect of its own, CR 707.2) and nothing else."""
    from engine.tokens import make_token_card

    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Parallel Evolution"]]),
        _W1G8Player("B"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    saproling = _W1G8Permanent(card=make_token_card(
        "Saproling", 1, 1, "Creature — Saproling", colors=("G",),
    ), metadata={"is_token": True})
    game._put_permanent_onto_battlefield(0, saproling, None)
    bears = _W1G8Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    giant = _W1G8Permanent(card=lea["Hill Giant"])
    game._put_permanent_onto_battlefield(1, giant, None)
    giant_token = game.create_token_copy(1, giant)
    game.remove_from_battlefield(giant)
    return game, saproling, bears, giant_token


def _w1g8_tokens(game, seat):
    return sorted(
        (p.effective_card.name, p.effective_power, p.effective_toughness)
        for p in game.controlled_by(seat) if p.metadata.get("is_token")
    )


def test_w1g8_parallel_evolution_copies_each_token_for_its_controller(set_pool):
    """"For each creature token on the battlefield, its controller creates a
    token that's a copy of that creature." It refused in lowering ("that
    creature" with nothing in this effect that chose one): inside a loop over
    the board, "that creature" is the permanent the iteration is on and "its
    controller" is that permanent's controller. Each side doubles its own
    tokens; a nontoken creature is not copied; and the set is fixed when the
    loop starts, so the copies made are not themselves copied."""
    game, saproling, bears, giant_token = _w1g8_evolution_table(set_pool)
    result = game.cast_from_hand(0, "Parallel Evolution")
    assert result.supported, result.details
    _w1g8_resolve_stack(game)

    assert _w1g8_tokens(game, 0) == [("Saproling", 1, 1)] * 2
    assert _w1g8_tokens(game, 1) == [("Hill Giant", 3, 3)] * 2, (
        "a copy of a token copy copies what that token copies (CR 707.2)"
    )
    assert [p.card.name for p in game.controlled_by(0) if not p.metadata.get("is_token")] == [
        "Grizzly Bears"
    ]
    assert [c.name for c in game.players[0].graveyard] == ["Parallel Evolution"]


def test_w1g8_parallel_evolution_flashes_back_and_doubles_again(set_pool):
    """Its flashback line reads (CR 702.34): cast again from the graveyard it
    doubles the doubled board, and is exiled as it leaves the stack."""
    game, _saproling, _bears, _giant_token = _w1g8_evolution_table(set_pool)
    game.cast_from_hand(0, "Parallel Evolution")
    _w1g8_resolve_stack(game)
    again = game.cast_from_hand(0, "Parallel Evolution", from_zone="graveyard")
    assert again.supported, again.details
    _w1g8_resolve_stack(game)

    assert len(_w1g8_tokens(game, 0)) == 4
    assert len(_w1g8_tokens(game, 1)) == 4
    assert [c.name for c in game.players[0].exile] == ["Parallel Evolution"]
    assert not game.players[0].graveyard


def _w1g8_retraced_table(set_pool, hand, *, mine=(), theirs=(), humans=(0,)):
    """Retraced Image plus *hand* in seat 0's hand; the named permanents on
    each side."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player(
            "A", hand=[set_pool("TOR")["Retraced Image"]] + [lea[n] for n in hand],
        ),
        _W1G8Player("B"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(humans)
    game.start_turn(0)
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            game._put_permanent_onto_battlefield(seat, _W1G8Permanent(card=lea[name]), None)
    result = game.cast_from_hand(0, "Retraced Image")
    assert result.supported, result.details
    return game


def _w1g8_reveal(game, name):
    (asked,) = game.pending_choices
    assert asked.kind == "choose_cards_in_hand" and asked.data["count"] == 1
    slot = [c.name for c in game.players[0].hand].index(name)
    assert game.confirm_choose_cards_in_hand(0, [slot])
    _w1g8_resolve_stack(game)


def test_w1g8_retraced_image_puts_a_namesake_onto_the_battlefield(set_pool):
    """"Reveal a card in your hand, then put that card onto the battlefield if
    it has the same name as a permanent." It refused at the parse: the trailing
    "if" is part of the clause after the "then" — the reveal happens either
    way — and "it has the same name as a permanent" names the revealed card.
    The caster is asked which card to reveal (a hand picker), and "a
    permanent" is any permanent: here the opponent's."""
    game = _w1g8_retraced_table(
        set_pool, ["Island", "Grizzly Bears"], theirs=["Grizzly Bears"],
    )
    _w1g8_reveal(game, "Grizzly Bears")

    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert "A revealed Grizzly Bears (Retraced Image)" in game.log


def test_w1g8_retraced_image_reveals_and_keeps_a_card_with_no_namesake(set_pool):
    """No permanent shares the revealed card's name: it is revealed and stays
    in hand — the reveal is not conditional, only the put is."""
    game = _w1g8_retraced_table(
        set_pool, ["Island", "Grizzly Bears"], mine=["Hill Giant"],
    )
    _w1g8_reveal(game, "Island")

    assert [p.card.name for p in game.controlled_by(0)] == ["Hill Giant"]
    assert sorted(c.name for c in game.players[0].hand) == ["Grizzly Bears", "Island"]
    assert "A revealed Island (Retraced Image)" in game.log


def test_w1g8_retraced_image_never_puts_an_instant_onto_the_battlefield(set_pool):
    """CR 400.4a: an instant card that would enter the battlefield stays where
    it was. A token can carry any name, so "the same name as a permanent" can
    hold for a revealed Lightning Bolt — and the Bolt stays in hand."""
    from engine.tokens import make_token_card

    game = _w1g8_retraced_table(set_pool, ["Lightning Bolt"], humans=(0,))
    namesake = _W1G8Permanent(card=make_token_card(
        "Lightning Bolt", 1, 1, "Creature — Elemental",
    ), metadata={"is_token": True})
    game._put_permanent_onto_battlefield(1, namesake, None)
    _w1g8_reveal(game, "Lightning Bolt")

    assert [c.name for c in game.players[0].hand] == ["Lightning Bolt"]
    assert not list(game.controlled_by(0))
    assert any("400.4a" in line for line in game.log)


def test_w1g8_retraced_image_a_seat_nobody_asks_reveals_the_namesake(set_pool):
    """The stated default reveals the first card in hand order; a pick the
    next sentence turns into a free permanent (``hand_pick_entry_consumer``)
    is ordered first — and here, only a pick the guarding "if it has the same
    name as a permanent" admits enters at all, so that one goes first."""
    game = _w1g8_retraced_table(
        set_pool, ["Island", "Hill Giant", "Grizzly Bears"],
        mine=["Grizzly Bears"], humans=(),
    )
    _w1g8_resolve_stack(game)

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Grizzly Bears", "Grizzly Bears",
    ]
    assert sorted(c.name for c in game.players[0].hand) == ["Hill Giant", "Island"]


@_w1g8_pytest.mark.parametrize("namesake", [False, True])
def test_w1g8_the_ai_casts_retraced_image_only_over_a_namesake(set_pool, namesake):
    """An AI seat holding no card a permanent shares a name with would spend
    Retraced Image on a reveal: the rehearsal reads the reveal as a change
    worth nothing and proposed it. The hand-pick gate the AI asks before the
    cast (Stronghold Gambit's) now reads the guard around the entering step
    too, so the card is held until something in hand would enter."""
    from engine.ai_policy import choose_cast_action

    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Retraced Image"], lea["Hill Giant"]],
                    library=[lea["Island"]] * 5),
        _W1G8Player("B", library=[lea["Forest"]] * 5),
    ])
    game.enforce_mana_costs = True
    game.start_turn(0)
    game._close_current_priority_step()
    game._put_permanent_onto_battlefield(0, _W1G8Permanent(card=lea["Island"]), None)
    if namesake:
        game._put_permanent_onto_battlefield(1, _W1G8Permanent(card=lea["Hill Giant"]), None)

    action = choose_cast_action(game, 0)
    assert (action is not None and action.card_name == "Retraced Image") is namesake

# ==== end W1G8 ======================================================
