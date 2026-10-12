"""Odyssey creatures.

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
from engine.counted_names import card_answers_to_name as _w1g4_answers_to_name
from engine.counted_names import counts_as_line as _w1g4_counts_as_line
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.oracle import simple_card_keywords as _w1g4_simple_keywords
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names (ODY over LEA)."""
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
            perm = _w1g4_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g4_names(cards):
    return [card.name for card in cards]


def _w1g4_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Pardic Firecat / Diligent Farmhand: a card that counts as another's name -

def test_pardic_firecat_in_a_graveyard_is_a_flame_burst_to_flame_burst(set_pool):
    """2 plus the real Flame Burst plus a Firecat in each graveyard is 5. The
    count is of cards, so each Firecat is one."""
    game = _w1g4_duel(
        set_pool, hand0=["Flame Burst"], gy0=["Pardic Firecat", "Flame Burst"],
        gy1=["Pardic Firecat", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Flame Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 15


def test_pardic_firecat_counts_only_while_it_is_in_a_graveyard(set_pool):
    """"If this card is in a graveyard" (CR 113.6b): one on the battlefield and
    one in a hand are not cards named Flame Burst to anything."""
    game = _w1g4_duel(
        set_pool, hand0=["Flame Burst", "Pardic Firecat"], bf1=["Pardic Firecat"],
    )
    assert game.cast_from_hand(0, "Flame Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 18


def test_each_helper_counts_for_its_own_burst_and_no_other(set_pool):
    """A Firecat and a Farmhand in one graveyard: Muscle Burst sees the
    Farmhand (3 + 1) and Flame Burst sees the Firecat (2 + 1)."""
    game = _w1g4_duel(
        set_pool, hand0=["Muscle Burst", "Flame Burst"],
        gy0=["Pardic Firecat", "Diligent Farmhand"], bf0=["Grizzly Bears"],
    )
    bears = _w1g4_on_board(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Muscle Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (6, 6)
    assert game.cast_from_hand(0, "Flame Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 17


def test_an_ability_counting_flame_bursts_does_not_count_a_firecat(set_pool):
    """"Effects from **spells** named Flame Burst": an activated ability asking
    the same count is not one, whatever its source is called."""
    counter = _w1g4_mk_card(
        "Burst Counter", "{R}", "Creature — Goblin",
        "{T}: This creature deals X damage to any target, where X is the "
        "number of cards named Flame Burst in all graveyards.",
    )
    assert _w1g4_compile(counter).supported
    game = _w1g4_duel(set_pool, gy0=["Pardic Firecat", "Flame Burst"])
    perm = _w1g4_Permanent(card=counter)
    game._put_permanent_onto_battlefield(0, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    assert game.activate_permanent_ability(
        0, "Burst Counter", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 19


def test_the_counts_as_line_is_payload_not_two_card_names(set_pool):
    """An invented pair: a spell nobody printed and the helper that counts for
    it. Nothing in the engine knows either name."""
    burst = _w1g4_mk_card(
        "Frost Burst", "{U}", "Instant",
        "Frost Burst deals X damage to any target, where X is 1 plus the "
        "number of cards named Frost Burst in all graveyards.",
    )
    helper = _w1g4_mk_card(
        "Frost Otter", "{U}", "Creature — Otter",
        "If this card is in a graveyard, effects from spells named Frost Burst "
        "count it as a card named Frost Burst.",
    )
    assert _w1g4_compile(burst).supported and _w1g4_compile(helper).supported
    game = _w1g4_duel(set_pool, gy1=["Pardic Firecat"])
    game.players[0].hand.append(burst)
    game.players[1].graveyard.extend([helper, helper])
    assert game.cast_from_hand(0, "Frost Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 17


@_w1g4_pytest.mark.parametrize("line", [
    # A zone the table has no row for.
    "If this card is in your hand, effects from spells named Flame Burst "
    "count it as a card named Flame Burst.",
    # A second sentence on the line: a registry claims a whole line or none.
    "If this card is in a graveyard, effects from spells named Flame Burst "
    "count it as a card named Flame Burst. Draw a card.",
    "If this card is in a graveyard, effects count it as a card named Flame Burst.",
])
def test_a_counts_as_line_the_table_cannot_read_is_refused(line):
    """The refusing half: a creature whose line this module does not carry out
    in full is unsupported, never admitted with the sentence doing nothing."""
    assert _w1g4_counts_as_line(line) is None
    card = _w1g4_mk_card("Odd Cat", "{R}", "Creature — Cat", line)
    assert not _w1g4_compile(card).supported


def test_a_name_is_a_set_of_names_and_the_helper_gives_none(set_pool):
    """`card_answers_to_name` is CR 201.2a for a reader that is not a spell's
    effect: the Firecat is named Pardic Firecat and nothing else."""
    firecat = set_pool("ODY")["Pardic Firecat"]
    assert _w1g4_answers_to_name(firecat, "pardic firecat")
    assert not _w1g4_answers_to_name(firecat, "Flame Burst")
    assert not _w1g4_answers_to_name(firecat, "Flame Burst", zone="graveyard")
    assert not _w1g4_answers_to_name(
        firecat, "Flame Burst", zone="hand", effect_spell="Flame Burst"
    )
    assert not _w1g4_answers_to_name(
        firecat, "Muscle Burst", zone="graveyard", effect_spell="Muscle Burst"
    )
    assert _w1g4_answers_to_name(
        firecat, "flame burst", zone="graveyard", effect_spell="Flame Burst"
    )
    assert not _w1g4_answers_to_name(firecat, "", zone="graveyard")


def test_pardic_firecat_is_a_hasty_creature_with_a_line_of_its_own(set_pool):
    firecat = set_pool("ODY")["Pardic Firecat"]
    assert _w1g4_simple_keywords(firecat) is None, "not a keywords-only auto-pass"
    game = _w1g4_duel(set_pool)
    perm = _w1g4_Permanent(card=firecat)
    game._put_permanent_onto_battlefield(0, perm, None)
    assert game._has_keyword(perm, "haste")
    assert (perm.effective_power, perm.effective_toughness) == (2, 3)


def test_diligent_farmhand_is_sacrificed_for_a_tapped_basic_land(set_pool):
    game = _w1g4_duel(
        set_pool, bf0=["Diligent Farmhand"],
        lib0=["Grizzly Bears", "Bayou", "Forest", "Island"],
    )
    assert game.activate_permanent_ability(0, "Diligent Farmhand").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    (land,) = list(game.controlled_by(0))
    assert land.card.name == "Forest" and land.tapped
    assert _w1g4_names(game.players[0].graveyard) == ["Diligent Farmhand"]
    assert len(game.players[0].library) == 3


def test_diligent_farmhand_offers_only_basic_lands_to_a_person(set_pool):
    """The nonbasic land and the creature are in the library and not in the
    search: the prompt carries the restriction, so the picker cannot offer
    them and an answer naming one is refused."""
    game = _w1g4_duel(
        set_pool, bf0=["Diligent Farmhand"],
        lib0=["Grizzly Bears", "Bayou", "Forest"],
    )
    game.interactive_seats.add(0)
    assert game.activate_permanent_ability(0, "Diligent Farmhand").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["restrictions"] == {"supertypes": ["basic"]}
    assert prompt.data["card_type"] == "land" and prompt.data["enters_tapped"]


def test_diligent_farmhand_finding_no_basic_land_still_shuffles_and_is_gone(set_pool):
    game = _w1g4_duel(
        set_pool, bf0=["Diligent Farmhand"], lib0=["Grizzly Bears", "Bayou"],
    )
    assert game.activate_permanent_ability(0, "Diligent Farmhand").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert list(game.controlled_by(0)) == []
    assert sorted(_w1g4_names(game.players[0].library)) == ["Bayou", "Grizzly Bears"]


# --- The five -vores: a P/T counted over every graveyard (CR 604.3) ----------

@_w1g4_pytest.mark.parametrize("vore, counted, keyword", [
    ("Cantivore", "Animate Dead", "vigilance"),
    ("Cognivore", "Giant Growth", "flying"),
    ("Magnivore", "Fireball", "haste"),
    ("Mortivore", "Grizzly Bears", None),
    ("Terravore", "Forest", "trample"),
])
def test_a_vore_is_as_big_as_its_card_type_in_all_graveyards(
    set_pool, vore, counted, keyword
):
    """Two in its controller's graveyard and one in the opponent's: 3/3. A
    card of another type in each pile is not counted; a fourth arriving is
    (CR 611.3a: the count is never locked in); with none it is 0/0 and put
    into its owner's graveyard (CR 704.5f)."""
    game = _w1g4_duel(
        set_pool, gy0=[counted, counted, "Black Lotus"], gy1=[counted, "Black Lotus"],
        bf0=[vore],
    )
    perm = _w1g4_on_board(game, 0, vore)
    game.check_state_based_actions()
    assert (perm.effective_power, perm.effective_toughness) == (3, 3)
    if keyword:
        assert game._has_keyword(perm, keyword)
    game.players[1].graveyard.append(set_pool("LEA")[counted])
    game.check_state_based_actions()
    assert (perm.effective_power, perm.effective_toughness) == (4, 4)
    game.players[0].graveyard.clear()
    game.players[1].graveyard.clear()
    game.check_state_based_actions()
    assert not game.is_on_battlefield(perm)
    assert _w1g4_names(game.players[0].graveyard) == [vore]


def test_mortivore_regenerates_for_one_black_mana(set_pool):
    game = _w1g4_duel(
        set_pool, gy0=["Grizzly Bears", "Grizzly Bears"], bf0=["Mortivore"],
    )
    mortivore = _w1g4_on_board(game, 0, "Mortivore")
    assert game.activate_permanent_ability(0, "Mortivore").supported
    _w1g4_resolve_stack(game)
    assert any("regeneration shield" in line for line in game.log)
    assert game.is_on_battlefield(mortivore)


# --- Dwarven Recruiter ---------------------------------------------------------

def test_dwarven_recruiter_stacks_every_dwarf_on_top_of_a_shuffled_library(set_pool):
    """Its entry trigger is a stack object; the search finds the Dwarf cards
    and nothing else, reveals them (the log may name them), and they are the
    top of the library afterwards."""
    game = _w1g4_duel(
        set_pool, hand0=["Dwarven Recruiter"],
        lib0=["Forest", "Dwarven Warriors", "Grizzly Bears",
              "Dwarven Demolition Team", "Island"],
    )
    assert game.queue_from_hand(0, "Dwarven Recruiter").supported
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Dwarven Recruiter"]
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    library = _w1g4_names(game.players[0].library)
    assert sorted(library[:2]) == ["Dwarven Demolition Team", "Dwarven Warriors"]
    assert sorted(library[2:]) == ["Forest", "Grizzly Bears", "Island"]
    assert any(line.startswith("P0 revealed") for line in game.log)


def test_dwarven_recruiter_asks_a_person_for_up_to_every_dwarf(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Dwarven Recruiter"],
        lib0=["Forest", "Dwarven Warriors", "Dwarven Demolition Team"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Dwarven Recruiter").supported
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["restrictions"] == {"subtypes": ["dwarf"]}
    assert prompt.data["up_to"] and prompt.data["count"] == 2
    assert prompt.data["reveal"] and prompt.data["destination"] == "library_top"

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

import random as _w1g7_random

import pytest as _w1g7_pytest

from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.hand_size import maximum_hand_size as _w1g7_maximum_hand_size
from engine.handlers._common import permanent_effective_colors as _w1g7_colors
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


# --- Thought Nibbler / Eater / Devourer: a maximum hand size that is changed --

@_w1g7_pytest.mark.parametrize(
    "name, limit",
    [("Thought Nibbler", 5), ("Thought Eater", 4), ("Thought Devourer", 3)],
)
def test_a_thought_beast_lowers_its_controllers_maximum_hand_size(
    set_pool, name, limit
):
    """"Your maximum hand size is reduced by two / three / four." Its
    controller alone, for as long as it is on the battlefield (CR 611.3a), and
    enforced where CR 514.1 enforces it: the cleanup step."""
    game = _w1g7_duel(
        set_pool, bf0=[name],
        hand0=["Grizzly Bears"] * 7, hand1=["Grizzly Bears"] * 7,
    )
    assert _w1g7_maximum_hand_size(game, 0) == limit
    assert _w1g7_maximum_hand_size(game, 1) == 7

    game.resolve_cleanup_step(0)
    assert len(game.players[0].hand) == limit
    assert len(game.players[0].graveyard) == 7 - limit

    game.resolve_cleanup_step(1)
    assert len(game.players[1].hand) == 7, "the opponent keeps seven"

    game.remove_from_battlefield(_w1g7_on_board(game, 0, name))
    assert _w1g7_maximum_hand_size(game, 0) == 7


def test_the_thought_beasts_stack_and_stop_at_no_cards(set_pool):
    """Two static abilities, both applied (CR 613.11): seven less two less
    three is two; all three beasts are seven less nine, and a hand cannot be
    smaller than empty (CR 107.1b)."""
    two = _w1g7_duel(
        set_pool, bf0=["Thought Nibbler", "Thought Eater"],
        hand0=["Grizzly Bears"] * 6,
    )
    assert _w1g7_maximum_hand_size(two, 0) == 2
    two.resolve_cleanup_step(0)
    assert len(two.players[0].hand) == 2

    three = _w1g7_duel(
        set_pool,
        bf0=["Thought Nibbler", "Thought Eater", "Thought Devourer"],
        hand0=["Grizzly Bears"] * 3,
    )
    assert _w1g7_maximum_hand_size(three, 0) == 0
    three.resolve_cleanup_step(0)
    assert three.players[0].hand == []


def test_a_thought_beast_and_a_cursed_rack_apply_in_the_order_they_entered(set_pool):
    """The beasts' own ruling (Scryfall, 2009-10-01): "if you are affected by
    Cursed Rack … and then put Thought Eater onto the battlefield, your maximum
    hand size would be one. However, if those permanents entered in the
    opposite order, your maximum hand size would be four." """
    pool = {**set_pool("ATQ"), **set_pool("ODY")}

    def board(*order):
        game = _w1g7_duel(set_pool)
        for name in order:
            perm = _w1g7_Permanent(card=pool[name])
            seat = 1 if name == "Cursed Rack" else 0
            game._put_permanent_onto_battlefield(seat, perm, None)
            if name == "Cursed Rack":
                perm.metadata["chosen_player_index"] = 0
        return game

    assert _w1g7_maximum_hand_size(board("Cursed Rack", "Thought Eater"), 0) == 1
    assert _w1g7_maximum_hand_size(board("Thought Eater", "Cursed Rack"), 0) == 4


def test_a_thought_beast_under_another_controller_lowers_that_players_maximum(
    set_pool,
):
    """"Your" is whoever controls it now (CR 613 layer 2 through the control
    seam), not who it entered under."""
    from engine.control import change_control

    game = _w1g7_duel(set_pool, bf0=["Thought Devourer"])
    beast = _w1g7_on_board(game, 0, "Thought Devourer")
    change_control(beast, 1, source="test")
    game._sync_control()
    assert _w1g7_maximum_hand_size(game, 0) == 7
    assert _w1g7_maximum_hand_size(game, 1) == 3


def _w1g7_settle(game, limit=50):
    """Drain the stack and give every owed prompt its default answer."""
    for _ in range(limit):
        _w1g7_resolve_stack(game)
        if not game.pending_choices and not game.pending_replacement_choices:
            return
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
    raise AssertionError("the game did not settle")


# --- Confessor: "whenever a player discards a card" ---------------------------

def test_confessor_watches_every_players_discards_its_controllers_included(
    set_pool,
):
    """"Whenever **a player** discards a card, you may gain 1 life." The third
    printed seat of the discard trigger, and the widest: an opponent's discard
    to a spell and the controller's own discard to a cost both fire it, once
    per card (CR 701.9a)."""
    pool = {**set_pool("LEA"), **set_pool("ODY"), **set_pool("7ED")}
    game = _w1g7_duel(
        set_pool, bf0=["Confessor", "Wild Mongrel"], hand0=["Forest", "Forest"],
        hand1=["Grizzly Bears", "Grizzly Bears", "Forest"],
    )
    game.players[0].hand.append(pool["Mind Rot"])

    assert game.cast_from_hand(0, "Mind Rot", target_player_index=1).supported
    _w1g7_settle(game)
    assert len(game.players[1].graveyard) == 2
    assert game.players[0].life == 22, "one trigger per card an opponent discarded"

    assert game.activate_permanent_ability(
        0, "Wild Mongrel", cost_hand_index=0
    ).supported
    _w1g7_settle(game)
    assert game.players[0].life == 23, "its controller's own discard counts too"
    assert game.players[1].life == 20


def test_confessor_sees_a_cleanup_discard_and_each_copy_answers_for_its_owner(
    set_pool,
):
    """No spell or ability caused the cleanup discard (CR 514.1) and it is a
    discard all the same; and "you" is each Confessor's own controller."""
    game = _w1g7_duel(
        set_pool, bf0=["Confessor"], bf1=["Confessor"],
        hand1=["Grizzly Bears"] * 9,
    )
    game.resolve_cleanup_step(1)
    _w1g7_settle(game)
    assert len(game.players[1].hand) == 7
    assert (game.players[0].life, game.players[1].life) == (22, 22)


def test_confessor_asks_its_controller_and_no_is_an_answer(set_pool):
    """"You may": an interactive seat is asked once per trigger, and declining
    gains nothing."""
    game = _w1g7_duel(
        set_pool, bf0=["Confessor"], hand1=["Grizzly Bears"] * 8,
        interactive=(0,),
    )
    game.resolve_cleanup_step(1)
    _w1g7_resolve_stack(game)
    offers = game.pending_choices_of("optional_pay", 0)
    assert len(offers) == 1
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    assert game.players[0].life == 20

    game.players[1].hand.extend([game.players[1].hand[0]])
    game.resolve_cleanup_step(1)
    _w1g7_resolve_stack(game)
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    assert game.players[0].life == 21


def test_the_discard_trigger_still_tells_its_three_seats_apart():
    """The narrowing is data on one condition kind, so all three spellings are
    asked of one fire site — and an invented card printing each must hear only
    what it names."""
    def watcher(name, who):
        card = _w1g7_mk_card(
            name, "{1}", "Enchantment",
            f"Whenever {who} a card, you gain 1 life.",
        )
        assert _w1g7_compile(card).supported, name
        return card

    yours = watcher("Own Discards", "you discard")
    theirs = watcher("Their Discards", "an opponent discards")
    anyones = watcher("Any Discards", "a player discards")
    filler = _w1g7_mk_card("Filler", "", "Sorcery", "")

    def life_after(discarder):
        seats = [_w1g7_PlayerState(name="P0", life=20), _w1g7_PlayerState(name="P1", life=20)]
        game = _w1g7_Game(players=seats)
        game.enforce_mana_costs = False
        for card in (yours, theirs, anyones):
            game._put_permanent_onto_battlefield(0, _w1g7_Permanent(card=card), None)
        seats[discarder].hand = [filler] * 8
        game.resolve_cleanup_step(discarder)
        _w1g7_settle(game)
        return seats[0].life

    assert life_after(0) == 22, "'you' and 'a player'"
    assert life_after(1) == 22, "'an opponent' and 'a player'"


def _w1g7_attack(game, seat, name, blocks=None):
    """*seat* attacks with its creature *name*; combat walks to the second
    main phase, or stops where a prompt holds it. True if it got there."""
    game.start_turn(seat)
    game._close_current_priority_step()
    slot = [p.card.name for p in game.controlled_by(seat)].index(name)
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(seat, [slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocked = game.declare_blockers(1 - seat, dict(blocks or {}))
    assert blocked[0], blocked
    for _ in range(10):
        if game.current_step == "postcombat_main":
            return True
        game.advance_combat_phase()
        if game.pending_choices:
            return False
        _w1g7_resolve_stack(game)
    return game.current_step == "postcombat_main"


# --- Balshan Beguiler: the damaged player's top two, and its controller picks ---

_W1G7_BEGUILED = ["Forest", "Grizzly Bears", "Island", "Terror"]


def test_balshan_beguiler_bins_one_of_the_damaged_players_top_two(set_pool):
    """"Whenever this creature deals combat damage to a player, that player
    reveals the top two cards of their library. You choose one of those cards
    and put it into their graveyard." The pile is the damaged player's, the
    choice is the Beguiler's controller's, and the card not chosen stays where
    it was — the sentence moves one card."""
    game = _w1g7_duel(
        set_pool, bf0=["Balshan Beguiler"], lib0=["Mountain"] * 5,
        lib1=_W1G7_BEGUILED, interactive=(0,),
    )
    assert not _w1g7_attack(game, 0, "Balshan Beguiler"), "held: a pick is owed"
    assert game.players[1].life == 19
    (pick,) = game.pending_choices
    assert (pick.kind, pick.player_index) == ("look_top_pick", 0)
    assert (pick.data["pile_index"], pick.data["top_count"]) == (1, 2)
    assert any("P1 reveals Forest, Grizzly Bears" in line for line in game.log)

    assert game.resolve_pending_choice("look_top_pick", 0, keep_index=1)
    assert _w1g7_names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert _w1g7_names(game.players[1].library) == ["Forest", "Island", "Terror"]
    assert not game.pending_choices, "one card left: nothing to order"
    assert len(game.players[0].library) == 5


def test_balshan_beguiler_does_nothing_when_blocked_and_reads_the_seat_it_hit(
    set_pool,
):
    """Blocked, it dealt no combat damage to a player. And "that player" is
    whoever was damaged: under the other seat's control it opens *this*
    seat's library and that seat's controller chooses."""
    blocked = _w1g7_duel(
        set_pool, bf0=["Balshan Beguiler"], bf1=["Grizzly Bears"],
        lib0=["Mountain"] * 5, lib1=_W1G7_BEGUILED, interactive=(0,),
    )
    assert _w1g7_attack(blocked, 0, "Balshan Beguiler", blocks={0: 0})
    assert blocked.players[1].graveyard == []
    assert _w1g7_names(blocked.players[1].library) == _W1G7_BEGUILED

    theirs = _w1g7_duel(
        set_pool, bf1=["Balshan Beguiler"], lib0=_W1G7_BEGUILED,
        lib1=["Mountain"] * 5, interactive=(1,),
    )
    assert not _w1g7_attack(theirs, 1, "Balshan Beguiler")
    (pick,) = theirs.pending_choices
    assert (pick.player_index, pick.data["pile_index"]) == (1, 0)
    assert theirs.resolve_pending_choice("look_top_pick", 1, keep_index=0)
    assert _w1g7_names(theirs.players[0].graveyard) == ["Forest"]
    assert _w1g7_names(theirs.players[0].library) == ["Grizzly Bears", "Island", "Terror"]


def test_balshan_beguiler_over_a_library_of_one_or_none(set_pool):
    one = _w1g7_duel(
        set_pool, bf0=["Balshan Beguiler"], lib0=["Mountain"] * 5, lib1=["Forest"],
        interactive=(0,),
    )
    _w1g7_attack(one, 0, "Balshan Beguiler")
    assert one.resolve_pending_choice("look_top_pick", 0, keep_index=0)
    assert _w1g7_names(one.players[1].graveyard) == ["Forest"]

    none = _w1g7_duel(
        set_pool, bf0=["Balshan Beguiler"], lib0=["Mountain"] * 5, interactive=(0,),
    )
    assert _w1g7_attack(none, 0, "Balshan Beguiler")
    assert not none.pending_choices and not none.players[1].lost


def test_that_player_reveals_and_you_choose_needs_an_event_that_froze_a_seat():
    """Under a trigger that damaged nobody, "that player" names a seat no fire
    site recorded, and a pile nobody named is not opened."""
    card = _w1g7_mk_card(
        "Idle Beguiler", "{U}", "Enchantment",
        "At the beginning of your upkeep, that player reveals the top two "
        "cards of their library. You choose one of those cards and put it "
        "into their graveyard.",
    )
    assert not _w1g7_compile(card).supported


# --- The sheet's creatures that compiled before this round, driven --------------

_W1G7_CHOSEN_DISCARD_COSTS = [
    "Amugaba", "Balshan Griffin", "Face of Fear", "Fledgling Imp",
    "Krosan Archer", "Patrol Hound", "Phantatog", "Pulsating Illusion",
    "Stalking Bloodsucker", "Tireless Tribe", "Wild Mongrel",
]
_W1G7_RANDOM_DISCARD_COSTS = [
    "Dwarven Strike Force", "Frenetic Ogre", "Pardic Swordsmith",
]


def _w1g7_discard_ability(set_pool, name):
    program = _w1g7_compile(set_pool("ODY")[name])
    return next(
        index for index, ability in enumerate(program.activated_abilities)
        if "discard" in ability.source_line.lower()
    )


@_w1g7_pytest.mark.parametrize(
    "name", _W1G7_CHOSEN_DISCARD_COSTS + _W1G7_RANDOM_DISCARD_COSTS
)
def test_a_discard_cost_takes_exactly_one_of_two_identical_cards(set_pool, name):
    """"Discard a card: …" A hand holds one immutable card object per copy, so
    paying with one of two Forests has to leave the other (CR 701.9a moves a
    card, not a name). And an empty hand cannot pay: the activation is refused
    with nothing spent."""
    index = _w1g7_discard_ability(set_pool, name)
    game = _w1g7_duel(set_pool, bf0=[name], hand0=["Forest", "Forest"])
    assert game.activate_permanent_ability(
        0, name, ability_index=index, cost_hand_index=0
    ).supported
    _w1g7_settle(game)
    hand = _w1g7_names(game.players[0].hand)
    assert hand.count("Forest") == 1, hand
    assert _w1g7_names(game.players[0].graveyard) == ["Forest"]

    empty = _w1g7_duel(set_pool, bf0=[name])
    refused = empty.activate_permanent_ability(0, name, ability_index=index)
    assert not refused.supported and "discard" in refused.details
    assert _w1g7_on_board(empty, 0, name) is not None


@_w1g7_pytest.mark.parametrize("name", _W1G7_CHOSEN_DISCARD_COSTS)
def test_a_chosen_discard_cost_discards_the_card_its_payer_named(set_pool, name):
    index = _w1g7_discard_ability(set_pool, name)
    game = _w1g7_duel(set_pool, bf0=[name], hand0=["Forest", "Forest", "Island"])
    assert game.activate_permanent_ability(
        0, name, ability_index=index, cost_hand_index=2
    ).supported
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].graveyard) == ["Island"]


@_w1g7_pytest.mark.parametrize("name", _W1G7_RANDOM_DISCARD_COSTS)
def test_a_random_discard_cost_is_chances_and_replays_per_seed(set_pool, name):
    """"Discard a card **at random**:" the payer names nothing — an index sent
    with the activation does not choose — and the seeded RNG picks, so a seed
    replays and different seeds differ."""
    def gone(seed):
        _w1g7_random.seed(seed)
        game = _w1g7_duel(set_pool, bf0=[name], hand0=["Forest", "Island", "Swamp"])
        assert game.activate_permanent_ability(0, name, cost_hand_index=0).supported
        _w1g7_settle(game)
        return tuple(_w1g7_names(game.players[0].graveyard))

    assert gone(5) == gone(5)
    assert len({gone(seed) for seed in range(20)}) == 3, "every card can be the one"


def test_what_the_discard_cost_creatures_buy(set_pool):
    """One line per card: what the ability does, and that it ends at cleanup."""
    def after(name, **zones):
        game = _w1g7_duel(set_pool, bf0=[name], hand0=["Forest"], **zones)
        index = _w1g7_discard_ability(set_pool, name)
        assert game.activate_permanent_ability(0, name, ability_index=index).supported
        _w1g7_settle(game)
        return game

    def body(game, name):
        permanent = _w1g7_on_board(game, 0, name)
        return permanent.effective_power, permanent.effective_toughness

    for name, expected in (
        ("Krosan Archer", (2, 5)), ("Phantatog", (2, 3)),
        ("Pulsating Illusion", (4, 5)), ("Stalking Bloodsucker", (6, 6)),
        ("Tireless Tribe", (1, 5)), ("Frenetic Ogre", (5, 3)),
        ("Pardic Swordsmith", (3, 1)), ("Wild Mongrel", (3, 3)),
    ):
        game = after(name)
        assert body(game, name) == expected, name
        game.resolve_cleanup_step(0)
        printed = set_pool("ODY")[name].raw
        assert body(game, name) == (int(printed["power"]), int(printed["toughness"])), name

    for name, keywords in (
        ("Face of Fear", ["fear"]), ("Fledgling Imp", ["flying"]),
        ("Patrol Hound", ["first strike"]),
        ("Dwarven Strike Force", ["first strike", "haste"]),
    ):
        game = after(name)
        permanent = _w1g7_on_board(game, 0, name)
        assert all(game._has_keyword(permanent, word) for word in keywords), name
        game.resolve_cleanup_step(0)
        assert not any(game._has_keyword(permanent, word) for word in keywords), name

    for name in ("Amugaba", "Balshan Griffin"):
        game = after(name)
        assert name in _w1g7_names(game.players[0].hand), name
        assert name not in [p.card.name for p in game.controlled_by(0)]


def test_pulsating_illusion_may_be_activated_once_each_turn(set_pool):
    game = _w1g7_duel(set_pool, bf0=["Pulsating Illusion"], hand0=["Forest", "Island"])
    assert game.activate_permanent_ability(0, "Pulsating Illusion").supported
    _w1g7_settle(game)
    second = game.activate_permanent_ability(0, "Pulsating Illusion")
    assert not second.supported and "once each turn" in second.details
    assert len(game.players[0].hand) == 1, "the refused activation discarded nothing"


def test_wild_mongrels_colour_is_chosen_as_the_ability_resolves(set_pool):
    """CR 608.2d: "the color of your choice" is asked during resolution, not
    announced with the activation; the colour is written through the layer and
    is gone with the turn."""
    game = _w1g7_duel(
        set_pool, bf0=["Wild Mongrel"], hand0=["Forest", "Island"], interactive=(0,),
    )
    mongrel = _w1g7_on_board(game, 0, "Wild Mongrel")
    assert game.activate_permanent_ability(0, "Wild Mongrel", cost_hand_index=0).supported
    (choice,) = game.pending_choices
    assert choice.kind == "color_choice"
    assert sorted(_w1g7_colors(mongrel)) == ["G"], "nothing chosen yet"
    assert not game.resolve_pending_choice("color_choice", 0, mana_color="purple")
    assert game.resolve_pending_choice("color_choice", 0, mana_color="U")
    assert sorted(_w1g7_colors(mongrel)) == ["U"]
    assert (mongrel.effective_power, mongrel.effective_toughness) == (3, 3)

    game.activate_permanent_ability(0, "Wild Mongrel", cost_hand_index=0)
    assert game.resolve_pending_choice("color_choice", 0, mana_color="R")
    assert sorted(_w1g7_colors(mongrel)) == ["R"], "the later choice (CR 613.7)"
    game.resolve_cleanup_step(0)
    assert sorted(_w1g7_colors(mongrel)) == ["G"]


def test_phantatogs_other_ability_sacrifices_an_enchantment(set_pool):
    game = _w1g7_duel(set_pool, bf0=["Phantatog", "Think Tank"], hand0=["Forest"])
    assert game.activate_permanent_ability(0, "Phantatog", ability_index=0).supported
    _w1g7_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Phantatog"]
    assert _w1g7_names(game.players[0].hand) == ["Forest"]

    bare = _w1g7_duel(set_pool, bf0=["Phantatog"], hand0=["Forest"])
    assert not bare.activate_permanent_ability(0, "Phantatog", ability_index=0).supported


def test_overeager_apprentice_pays_both_costs_for_three_black_mana(set_pool):
    game = _w1g7_duel(set_pool, bf0=["Overeager Apprentice"], hand0=["Forest", "Island"])
    assert game.activate_permanent_ability(
        0, "Overeager Apprentice", cost_hand_index=1
    ).supported
    _w1g7_settle(game)
    assert game.players[0].mana_pool["B"] == 3
    assert _w1g7_names(game.players[0].hand) == ["Forest"]
    assert list(game.controlled_by(0)) == []

    empty = _w1g7_duel(set_pool, bf0=["Overeager Apprentice"])
    assert not empty.activate_permanent_ability(0, "Overeager Apprentice").supported
    assert len(list(empty.controlled_by(0))) == 1, "not sacrificed for a cost unpaid"


def test_the_cephalids_loot_for_a_player_their_controller_targets(set_pool):
    """"{T}: **Target player** draws a card, then discards a card." The picker
    offers both seats and the targeted player chooses the discard."""
    for name, count in (("Cephalid Looter", 1), ("Cephalid Broker", 2)):
        game = _w1g7_duel(
            set_pool, bf0=[name], hand1=["Forest"],
            lib0=["Mountain"] * 3, lib1=["Island", "Swamp", "Plains"],
            interactive=(1,),
        )
        spec = game.activation_target_spec(0, 0, 0)
        assert spec["kind"] == "player" and len(spec["valid_targets"]) == 2
        assert game.activate_permanent_ability(0, name, target_player_index=1).supported
        (choice,) = game.pending_choices
        assert (choice.kind, choice.player_index, choice.data["count"]) == ("discard", 1, count)
        assert len(game.players[1].hand) == 1 + count
        assert game.confirm_discard(1, list(range(count)))
        assert len(game.players[1].hand) == 1 and len(game.players[0].library) == 3
        assert not game.activate_permanent_ability(0, name, target_player_index=1).supported, (
            "tapped"
        )


def test_mindslicer_empties_every_hand_when_it_dies_and_only_then(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Mindslicer"], hand0=["Forest", "Island"], hand1=["Swamp"],
    )
    game.sacrifice_permanent(_w1g7_on_board(game, 0, "Mindslicer"))
    assert len(game.stack) == 1, "a dies trigger is a stack object"
    _w1g7_settle(game)
    assert game.players[0].hand == [] and game.players[1].hand == []

    moved = _w1g7_duel(set_pool, bf0=["Mindslicer"], hand0=["Forest"], hand1=["Swamp"])
    moved.remove_from_battlefield(_w1g7_on_board(moved, 0, "Mindslicer"))
    _w1g7_settle(moved)
    assert len(moved.players[0].hand) == 1 and len(moved.players[1].hand) == 1


def test_minotaur_explorer_is_sacrificed_unless_a_random_card_goes(set_pool):
    def enter(hand, accept):
        game = _w1g7_duel(
            set_pool, hand0=["Minotaur Explorer", *hand], interactive=(0,),
        )
        assert game.cast_from_hand(0, "Minotaur Explorer").supported
        # The cast runs on until the entry trigger's offer holds it (or, with
        # nothing to discard, until the trigger has resolved); the offer is
        # answered by hand, since ``resolve_stack`` would give it its default.
        if game.pending_choices:
            assert len(game.stack) == 1, "the entry trigger is a stack object"
            assert game.resolve_pending_choice("optional_pay", 0, accept=accept)
        _w1g7_settle(game)
        return game

    _w1g7_random.seed(9)
    kept = enter(["Forest", "Island"], True)
    assert [p.card.name for p in kept.controlled_by(0)] == ["Minotaur Explorer"]
    assert len(kept.players[0].hand) == 1 and len(kept.players[0].graveyard) == 1

    declined = enter(["Forest"], False)
    assert list(declined.controlled_by(0)) == []
    assert _w1g7_names(declined.players[0].hand) == ["Forest"]

    unable = enter([], True)
    assert list(unable.controlled_by(0)) == [], "no card to discard is no choice"


def test_cursed_monstrosity_asks_for_a_land_card_whenever_it_is_targeted(set_pool):
    """By a spell or by an ability, and the discard is of a *land* card: a
    hand with none cannot pay, so the creature is sacrificed and the spell
    that targeted it finds nothing (CR 608.2b)."""
    def aimed(hand):
        game = _w1g7_duel(
            set_pool, hand0=["Giant Growth"], bf1=["Cursed Monstrosity"],
            hand1=hand, interactive=(1,),
        )
        monster = _w1g7_on_board(game, 1, "Cursed Monstrosity")
        assert game.queue_from_hand(
            0, "Giant Growth", target_permanent_ids=[monster.permanent_id]
        ).supported
        assert [item.card.name for item in game.stack] == [
            "Giant Growth", "Cursed Monstrosity",
        ]
        game.resolve_top_of_stack()
        return game, monster

    game, monster = aimed(["Grizzly Bears", "Forest"])
    assert game.resolve_pending_choice("optional_pay", 1, accept=True)
    assert not game.confirm_discard(1, [0]), "a creature card is not a land card"
    assert game.confirm_discard(1, [1])
    _w1g7_settle(game)
    assert (monster.effective_power, monster.effective_toughness) == (7, 6)
    assert _w1g7_names(game.players[1].graveyard) == ["Forest"]

    game, _monster = aimed(["Grizzly Bears"])
    _w1g7_settle(game)
    assert list(game.controlled_by(1)) == []
    assert "Cursed Monstrosity" in _w1g7_names(game.players[1].graveyard)

    pinged = _w1g7_duel(
        set_pool, bf0=["Prodigal Sorcerer"], bf1=["Cursed Monstrosity"],
        hand1=["Forest"], interactive=(1,),
    )
    monster = _w1g7_on_board(pinged, 1, "Cursed Monstrosity")
    assert pinged.queue_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[monster.permanent_id]
    ).supported
    assert [item.card.name for item in pinged.stack][-1] == "Cursed Monstrosity"


def test_aven_windreader_shows_the_top_card_and_moves_nothing(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Aven Windreader"], lib1=["Terror", "Swamp"],
    )
    assert game.activate_permanent_ability(
        0, "Aven Windreader", target_player_index=1
    ).supported
    _w1g7_settle(game)
    assert any("revealed Terror" in line for line in game.log)
    assert _w1g7_names(game.players[1].library) == ["Terror", "Swamp"]


def test_sadistic_hypnotist_is_a_sorcery_speed_sacrifice_outlet(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Sadistic Hypnotist", "Grizzly Bears"],
        hand1=["Forest", "Island", "Swamp"], interactive=(1,),
    )
    game.start_turn(0)
    game._close_current_priority_step()
    bears = _w1g7_on_board(game, 0, "Grizzly Bears")
    assert game.activate_permanent_ability(
        0, "Sadistic Hypnotist", target_player_index=1,
        cost_permanent_ids=[bears.permanent_id],
    ).supported
    assert [p.card.name for p in game.controlled_by(0)] == ["Sadistic Hypnotist"]
    assert game.confirm_discard(1, [0, 1])
    assert _w1g7_names(game.players[1].hand) == ["Swamp"]

    theirs = _w1g7_duel(
        set_pool, bf0=["Sadistic Hypnotist", "Grizzly Bears"], hand1=["Forest"],
    )
    theirs.start_turn(1)
    theirs._close_current_priority_step()
    refused = theirs.activate_permanent_ability(
        0, "Sadistic Hypnotist", target_player_index=1
    )
    assert not refused.supported and "sorcery" in refused.details
    assert len(list(theirs.controlled_by(0))) == 2, "nothing was sacrificed"

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
