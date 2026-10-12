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

    Odyssey over Apocalypse over Alpha: the Shrines count a spell's name, the
    spells are furniture, and one of them is a split card.
    """
    pool = {**set_pool("LEA"), **set_pool("APC"), **set_pool("ODY")}
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


def _w1g4_cast_bears_under(set_pool, shrine, **zones):
    """P1 casts Grizzly Bears while P0 controls *shrine*; the whole stack is
    resolved and every prompt it left is answered by its default."""
    hand1 = ["Grizzly Bears", *zones.pop("hand1", ())]
    game = _w1g4_duel(set_pool, hand1=hand1, bf0=[shrine], **zones)
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert [item.card.name for item in game.stack] == ["Grizzly Bears", shrine]
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game


# --- The Shrines: "…cards in all graveyards with the same name as that spell" -

def test_aven_shrine_gains_the_caster_a_life_per_same_named_card(set_pool):
    """Both graveyards are read, a card of another name is not, and it is the
    *caster* who gains — here the Shrine's controller's opponent."""
    game = _w1g4_cast_bears_under(
        set_pool, "Aven Shrine",
        gy0=["Grizzly Bears"], gy1=["Grizzly Bears", "Forest"],
    )
    assert (game.players[0].life, game.players[1].life) == (20, 22)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_aven_shrine_with_no_such_card_gains_nothing(set_pool):
    game = _w1g4_cast_bears_under(set_pool, "Aven Shrine", gy0=["Forest"])
    assert game.players[1].life == 20


def test_cabal_shrine_makes_the_caster_choose_that_many_discards(set_pool):
    game = _w1g4_duel(
        set_pool, hand1=["Grizzly Bears", "Island", "Swamp", "Mountain"],
        gy0=["Grizzly Bears"], gy1=["Grizzly Bears"], bf0=["Cabal Shrine"],
    )
    game.interactive_seats.add(1)
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "discard")
    assert prompt.player_index == 1 and prompt.data["count"] == 2
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 1
    assert game.players[0].hand == []


def test_dwarven_shrine_deals_twice_the_count_to_the_caster(set_pool):
    game = _w1g4_cast_bears_under(
        set_pool, "Dwarven Shrine",
        gy0=["Grizzly Bears"], gy1=["Grizzly Bears", "Forest"],
    )
    assert (game.players[0].life, game.players[1].life) == (20, 16)


def test_nantuko_shrine_gives_the_caster_that_many_squirrels(set_pool):
    game = _w1g4_cast_bears_under(
        set_pool, "Nantuko Shrine", gy0=["Grizzly Bears"], gy1=["Grizzly Bears"],
    )
    theirs = sorted(p.card.name for p in game.controlled_by(1))
    assert theirs == ["Grizzly Bears", "Squirrel Token", "Squirrel Token"]
    squirrel = next(
        p for p in game.controlled_by(1) if p.card.name == "Squirrel Token"
    )
    assert (squirrel.effective_power, squirrel.effective_toughness) == (1, 1)
    assert [p.card.name for p in game.controlled_by(0)] == ["Nantuko Shrine"]


def test_cephalid_shrine_counters_a_spell_whose_price_goes_unpaid(set_pool):
    """Mana is enforced and the caster has nothing left to tap: {2} is owed for
    two Bears in graveyards, and the spell is countered."""
    game = _w1g4_duel(
        set_pool, hand1=["Grizzly Bears"], gy0=["Grizzly Bears"],
        gy1=["Grizzly Bears"], bf0=["Cephalid Shrine"], bf1=["Forest", "Forest"],
    )
    game.enforce_mana_costs = True
    game.active_player_index = 1
    for forest in list(game.controlled_by(1)):
        assert game.tap_land_for_mana(
            1, "Forest", "G", permanent_id=forest.permanent_id
        )
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"] * 2
    assert [p.card.name for p in game.controlled_by(1)] == ["Forest", "Forest"]


def test_cephalid_shrine_lets_a_spell_through_once_x_is_paid(set_pool):
    """One Bears in a graveyard is {1}: a third Forest pays it (CR 605.3b — the
    payment has no priority window, so the lands are tapped inside it)."""
    game = _w1g4_duel(
        set_pool, hand1=["Grizzly Bears"], gy0=["Grizzly Bears"],
        bf0=["Cephalid Shrine"], bf1=["Forest", "Forest", "Forest"],
    )
    game.enforce_mana_costs = True
    game.active_player_index = 1
    forests = list(game.controlled_by(1))
    for forest in forests[:2]:
        assert game.tap_land_for_mana(
            1, "Forest", "G", permanent_id=forest.permanent_id
        )
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(1)]
    assert forests[2].tapped


def test_cephalid_shrine_asks_nothing_when_x_is_zero(set_pool):
    game = _w1g4_cast_bears_under(set_pool, "Cephalid Shrine")
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(1)]
    assert any("pays {0}" in line for line in game.log)


def test_a_shrine_counts_the_spell_itself_once_it_is_a_card_in_a_graveyard(set_pool):
    """CR 608.2h: the spell left the stack in response (countered), so its name
    is last known information — and the card is now in a graveyard with it."""
    game = _w1g4_duel(set_pool, hand1=["Grizzly Bears"], bf0=["Aven Shrine"])
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    spell = next(item for item in game.stack if item.card.name == "Grizzly Bears")
    game.counter_stack_object(spell)
    game.players[1].graveyard.append(spell.card)
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 21


def test_a_shrine_reads_the_cast_half_of_a_split_card(set_pool):
    """CR 709.3b gives the spell the cast half's name and CR 709.4a gives the
    card in the graveyard both halves' — so a Fire // Ice there shares a name
    with a Fire on the stack (CR 201.2a), and Grizzly Bears does not."""
    game = _w1g4_duel(
        set_pool, hand1=["Fire // Ice"], gy0=["Fire // Ice", "Grizzly Bears"],
        bf0=["Aven Shrine"],
    )
    assert game.queue_from_hand(1, "Fire", target_player_index=0).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 21


def test_each_shrine_triggers_for_its_own_controllers_spell_too(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Grizzly Bears"], gy1=["Grizzly Bears"],
        bf0=["Aven Shrine", "Aven Shrine"],
    )
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (22, 20)


@_w1g4_pytest.mark.parametrize("line", [
    # No cast event froze a spell for the words to name.
    "At the beginning of your upkeep, you gain X life, where X is the number "
    "of cards in all graveyards with the same name as that spell.",
    # A permanent's name is computed; the count has no key for the relation.
    "Whenever a player casts a spell, that player gains X life, where X is "
    "the number of permanents with the same name as that spell.",
])
def test_the_same_name_count_refuses_where_nothing_could_answer_it(line):
    shrine = _w1g4_mk_card("Odd Shrine", "{W}", "Enchantment", line)
    assert not _w1g4_compile(shrine).supported


def test_an_opponent_scoped_cast_trigger_reads_the_same_name_count(set_pool):
    """An invented card: the relation is the event's, not the five names'."""
    shrine = _w1g4_mk_card(
        "Rival Shrine", "{W}", "Enchantment",
        "Whenever an opponent casts a spell, you gain X life, where X is the "
        "number of cards in all graveyards with the same name as that spell.",
    )
    assert _w1g4_compile(shrine).supported
    game = _w1g4_duel(
        set_pool, hand0=["Grizzly Bears"], hand1=["Grizzly Bears"],
        gy0=["Grizzly Bears", "Grizzly Bears", "Forest"],
    )
    game._put_permanent_onto_battlefield(0, _w1g4_Permanent(card=shrine), None)
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    assert game.players[0].life == 22
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    assert game.players[0].life == 22, "its own controller is no opponent"


# --- Verdant Succession -------------------------------------------------------

def _w1g4_bolt(game, set_pool, seat, victim):
    """*seat* casts Lightning Bolt at *victim*; the Bolt resolves and
    state-based actions are checked, leaving any dies-trigger on the stack."""
    game.players[seat].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[victim.permanent_id]
    ).supported
    game.resolve_top_of_stack()
    game.check_state_based_actions()


def test_verdant_succession_replaces_a_dead_green_creature_from_its_controllers_library(set_pool):
    """The dead creature's **controller** searches — here the opponent of the
    Succession's controller — and the copy enters under that player."""
    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Grizzly Bears"],
        lib0=["Grizzly Bears"],
        lib1=["Forest", "Grizzly Bears", "Grizzly Bears", "Island"],
    )
    _w1g4_bolt(game, set_pool, 0, next(iter(game.controlled_by(1))))
    assert [item.card.name for item in game.stack] == ["Verdant Succession"]
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert len(game.players[1].library) == 3
    assert _w1g4_names(game.players[0].library) == ["Grizzly Bears"]
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"]


def test_verdant_succession_with_no_copy_left_finds_nothing(set_pool):
    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Grizzly Bears"],
        lib0=["Grizzly Bears"], lib1=["Forest", "Island"],
    )
    _w1g4_bolt(game, set_pool, 0, next(iter(game.controlled_by(1))))
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert list(game.controlled_by(1)) == []
    assert len(game.players[1].library) == 2


def test_verdant_succession_ignores_a_nongreen_creature_and_a_token(set_pool):
    from engine.tokens import make_token_card

    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Scathe Zombies"],
        lib1=["Scathe Zombies", "Grizzly Bears"],
    )
    _w1g4_bolt(game, set_pool, 0, next(iter(game.controlled_by(1))))
    assert game.stack == []

    squirrel = _w1g4_Permanent(card=make_token_card(
        name="Squirrel Token", power=1, toughness=1,
        type_line="Creature — Squirrel", colors=("G",),
    ))
    squirrel.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(1, squirrel, None)
    _w1g4_bolt(game, set_pool, 0, squirrel)
    assert game.stack == []


def test_verdant_succession_asks_the_dead_creatures_controller(set_pool):
    """"That creature's controller **may**": the offer is on the seat that
    controlled the creature, not on the enchantment's controller."""
    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Grizzly Bears"],
        lib1=["Forest", "Grizzly Bears"],
    )
    game.interactive_seats.update({0, 1})
    _w1g4_bolt(game, set_pool, 0, next(iter(game.controlled_by(1))))
    game.resolve_top_of_stack()
    assert [c.player_index for c in game.pending_choices] == [1]
    assert game.players[1].library and list(game.controlled_by(1)) == []


def test_verdant_succession_reads_the_controller_of_a_stolen_creature(set_pool):
    """A creature P0 took from P1 dies: P0 controlled it, so P0's library is
    searched — and the card itself goes to its owner's graveyard."""
    from engine.control import change_control

    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Grizzly Bears"],
        lib0=["Grizzly Bears"], lib1=["Grizzly Bears", "Grizzly Bears"],
    )
    bears = next(iter(game.controlled_by(1)))
    change_control(bears, 0, source="w1g4")
    game._sync_control()
    assert game.controller_index_of(bears) == 0
    _w1g4_bolt(game, set_pool, 1, bears)
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(0)]
    assert game.players[0].library == [] and len(game.players[1].library) == 2
    assert "Grizzly Bears" in _w1g4_names(game.players[1].graveyard)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

import pytest as _w1g7_pytest

from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import _mk_card as _w1g7_mk_card
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=(), interactive=()):
    """A two-seat game with costs off, built from card names (ODY over LEA).
    A seat in *interactive* is asked its decisions instead of defaulting."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    seats = [
        _w1g7_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g7_Game(players=seats)
    game.enforce_mana_costs = False
    for seat in interactive:
        game.interactive_seats.add(seat)
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g7_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g7_names(cards):
    return [card.name for card in cards]


def _w1g7_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g7_settle(game, limit=50):
    """Drain the stack and give every owed prompt its default answer."""
    for _ in range(limit):
        _w1g7_resolve_stack(game)
        if not game.pending_choices and not game.pending_replacement_choices:
            return
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
    raise AssertionError("the game did not settle")


# --- Think Tank: surveil (CR 701.25) ------------------------------------------

def test_think_tank_surveils_at_its_controllers_upkeep_and_the_card_may_go(
    set_pool,
):
    """"At the beginning of your upkeep, surveil 1." CR 701.25a: look at the
    top card, then put it into your graveyard or leave it on top. The ability
    stays on the stack until its controller has decided (CR 608.2)."""
    game = _w1g7_duel(
        set_pool, bf0=["Think Tank"], lib0=["Forest", "Grizzly Bears", "Island"],
        interactive=(0,),
    )
    game.resolve_upkeep(0)
    assert not game.resolve_top_of_stack(), "held: a decision is owed"
    (choice,) = game.pending_choices
    assert (choice.kind, choice.player_index) == ("scry", 0)
    assert choice.data["destination"] == "graveyard"
    assert choice.data["top_count"] == 1

    assert game.confirm_scry(0, [0], 1)
    assert _w1g7_names(game.players[0].graveyard) == ["Forest"]
    assert _w1g7_names(game.players[0].library) == ["Grizzly Bears", "Island"]
    assert game.players[0].hand == [], "a surveil draws nothing"
    assert not game.stack


def test_think_tank_may_leave_the_card_on_top(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Think Tank"], lib0=["Forest", "Grizzly Bears"],
        interactive=(0,),
    )
    game.resolve_upkeep(0)
    game.resolve_top_of_stack()
    assert game.confirm_scry(0, [0], 0)
    assert game.players[0].graveyard == []
    assert _w1g7_names(game.players[0].library) == ["Forest", "Grizzly Bears"]


def test_think_tank_is_silent_on_an_opponents_upkeep_and_over_an_empty_library(
    set_pool,
):
    """"Your upkeep" is its controller's; and a surveil with nothing to look
    at asks nothing and is not a draw (no CR 704.5b loss)."""
    game = _w1g7_duel(set_pool, bf0=["Think Tank"], lib0=["Forest"], lib1=["Island"])
    game.resolve_upkeep(1)
    _w1g7_settle(game)
    assert game.players[0].graveyard == [] and len(game.players[0].library) == 1

    empty = _w1g7_duel(set_pool, bf0=["Think Tank"], interactive=(0,))
    empty.resolve_upkeep(0)
    _w1g7_settle(empty)
    assert not empty.pending_choices
    assert not empty.players[0].lost


def test_think_tank_resolves_after_it_has_left_the_battlefield(set_pool):
    """The ability is independent of its source once on the stack (CR 113.7a)."""
    game = _w1g7_duel(
        set_pool, bf0=["Think Tank"], lib0=["Forest", "Island"], interactive=(0,),
    )
    game.resolve_upkeep(0)
    game.remove_from_battlefield(_w1g7_on_board(game, 0, "Think Tank"))
    game.resolve_top_of_stack()
    assert game.confirm_scry(0, [0], 1)
    assert _w1g7_names(game.players[0].graveyard) == ["Forest"]


def test_surveil_is_an_action_any_card_can_print(set_pool):
    """Built as the keyword action, not as the card: an invented "Surveil 3."
    sorcery looks at three, bins the two its controller names and keeps the
    third on top — and an answer that is not a permutation of what was looked
    at is refused with the prompt still owed."""
    look = _w1g7_mk_card("Deep Look", "{U}", "Sorcery", "Surveil 3.")
    assert _w1g7_compile(look).supported
    game = _w1g7_duel(
        set_pool, lib0=["Forest", "Grizzly Bears", "Island", "Swamp"],
        interactive=(0,),
    )
    game.players[0].hand.append(look)
    assert game.cast_from_hand(0, "Deep Look").supported
    assert not game.confirm_scry(0, [0, 0, 1], 1)
    assert not game.confirm_scry(0, [0, 1, 2], 4)
    assert game.pending_choices, "a refused answer leaves the prompt owed"

    # Keep the Bears; the Forest and the Island go to the graveyard.
    assert game.confirm_scry(0, [1, 0, 2], 2)
    assert _w1g7_names(game.players[0].library) == ["Grizzly Bears", "Swamp"]
    assert _w1g7_names(game.players[0].graveyard) == ["Forest", "Island", "Deep Look"]


def test_surveil_and_scry_are_two_actions_with_one_answer_shape(set_pool):
    """Scry sends the cards not kept to the bottom (CR 701.22a) where surveil
    sends them to the graveyard (CR 701.25a); the same answer means each."""
    scry = _w1g7_mk_card("Shallow Look", "{U}", "Sorcery", "Scry 2.")
    game = _w1g7_duel(
        set_pool, lib0=["Forest", "Grizzly Bears", "Island"], interactive=(0,),
    )
    game.players[0].hand.append(scry)
    assert game.cast_from_hand(0, "Shallow Look").supported
    assert game.pending_choices[0].data.get("destination") is None
    assert game.confirm_scry(0, [1, 0], 1)
    assert _w1g7_names(game.players[0].library) == ["Grizzly Bears", "Island", "Forest"]
    assert _w1g7_names(game.players[0].graveyard) == ["Shallow Look"]


@_w1g7_pytest.mark.parametrize("text", ["Surveil 2 cards.", "Surveil."])
def test_a_surveil_line_saying_more_or_less_is_refused(text):
    assert not _w1g7_compile(
        _w1g7_mk_card("Odd Look", "{U}", "Sorcery", text)
    ).supported


# --- Battle of Wits: an intervening "if" on a library count -------------------

def test_battle_of_wits_wins_with_two_hundred_cards_in_the_library(set_pool):
    game = _w1g7_duel(set_pool, bf0=["Battle of Wits"], lib0=["Forest"] * 200)
    game.resolve_upkeep(0)
    _w1g7_settle(game)
    assert game.players[1].lost and not game.players[0].lost


def test_battle_of_wits_does_not_trigger_one_card_short_or_on_another_upkeep(
    set_pool,
):
    """CR 603.4: the condition is checked as the ability would trigger, and a
    false one means it never does — no object reaches the stack."""
    game = _w1g7_duel(
        set_pool, bf0=["Battle of Wits"], lib0=["Forest"] * 199,
        lib1=["Forest"] * 250, interactive=(0, 1),
    )
    game.resolve_upkeep(0, defer_priority=True)
    assert not game.stack
    game.resolve_upkeep(1, defer_priority=True)
    assert not game.stack, "'your upkeep', and 'you have' is its controller"
    assert not any(player.lost for player in game.players)


def test_battle_of_wits_checks_the_library_again_as_it_resolves(set_pool):
    """CR 603.4's second half, and the card's own ruling (2012-07-01): "if you
    have fewer than 200 cards in your library when the ability resolves, the
    ability will do nothing"."""
    game = _w1g7_duel(
        set_pool, bf0=["Battle of Wits"], lib0=["Forest"] * 200,
        interactive=(0, 1),
    )
    game.resolve_upkeep(0, defer_priority=True)
    assert len(game.stack) == 1
    game.players[0].library.pop()
    _w1g7_settle(game)
    assert not any(player.lost for player in game.players)


def test_battle_of_wits_still_wins_if_it_leaves_in_response(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Battle of Wits"], lib0=["Forest"] * 200,
        interactive=(0, 1),
    )
    game.resolve_upkeep(0, defer_priority=True)
    game.remove_from_battlefield(_w1g7_on_board(game, 0, "Battle of Wits"))
    _w1g7_settle(game)
    assert game.players[1].lost


def test_a_pile_count_reads_the_subjects_own_pile_in_either_word_order():
    """"If you have 200 or more cards in your library" is the third word order
    of one question ("your library has ten or more cards in it"), and the
    possessive has to be the subject's own — a clause counting one player's
    pile on another's say-so is a different sentence."""
    def supported(clause):
        return _w1g7_compile(_w1g7_mk_card(
            "Pile Counter", "{1}", "Enchantment",
            f"At the beginning of your upkeep, if {clause}, you gain 1 life.",
        )).supported

    assert supported("you have three or more cards in your library")
    assert supported("your library has three or more cards in it")
    assert supported("you have three or more cards in your graveyard")
    assert not supported("you have three or more cards in their library")
    assert not supported("you have three or more cards in your sideboard")


# --- Zombie Infestation (compiled before this round; driven) ---------------------

def test_zombie_infestation_trades_two_cards_for_a_black_zombie(set_pool):
    """"Discard two cards: Create a 2/2 black Zombie creature token." Two
    cards, the two its controller names; one card cannot pay; and a pair of
    identical cards is two cards."""
    game = _w1g7_duel(
        set_pool, bf0=["Zombie Infestation"], hand0=["Forest", "Forest", "Island"],
    )
    assert game.activate_permanent_ability(
        0, "Zombie Infestation", cost_hand_index=0, cost_other_hand_indices=[2]
    ).supported
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].hand) == ["Forest"]
    assert sorted(_w1g7_names(game.players[0].graveyard)) == ["Forest", "Island"]
    tokens = [p for p in game.controlled_by(0) if p.is_creature]
    assert [(t.effective_power, t.effective_toughness) for t in tokens] == [(2, 2)]
    assert tokens[0].has_type("zombie") and list(tokens[0].effective_card.colors) == ["B"]

    short = _w1g7_duel(set_pool, bf0=["Zombie Infestation"], hand0=["Forest"])
    assert not short.activate_permanent_ability(0, "Zombie Infestation").supported
    assert _w1g7_names(short.players[0].hand) == ["Forest"]

    pair = _w1g7_duel(set_pool, bf0=["Zombie Infestation"], hand0=["Forest", "Forest"])
    assert pair.activate_permanent_ability(0, "Zombie Infestation").supported
    _w1g7_settle(pair)
    assert pair.players[0].hand == [] and len(pair.players[0].graveyard) == 2
    assert sum(1 for p in pair.controlled_by(0) if p.is_creature) == 1

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
