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

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
