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
