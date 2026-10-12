"""Odyssey sorceries.

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

    Odyssey over Stronghold over Alpha: the furniture is Alpha's, and Megrim —
    which is how a discard is seen to have gone through its seam — is
    Stronghold's.
    """
    pool = {**set_pool("LEA"), **set_pool("STH"), **set_pool("ODY")}
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


# --- Mind Burst: a *chosen* discard of X cards -------------------------------

def test_mind_burst_makes_its_target_choose_one_plus_the_bursts(set_pool):
    """One plus two in graveyards is three, and the discarding player picks
    them — the lowering refused a chosen discard of X on the ground that the
    only variable handler discarded at random, long after the chosen handler
    began sizing its prompt from X."""
    game = _w1g4_duel(
        set_pool, hand0=["Mind Burst"], gy0=["Mind Burst"], gy1=["Mind Burst"],
        hand1=["Grizzly Bears", "Forest", "Island", "Swamp", "Mountain"],
    )
    game.interactive_seats.add(1)
    assert game.cast_from_hand(0, "Mind Burst", target_player_index=1).supported
    prompt = next(c for c in game.pending_choices if c.kind == "discard")
    assert prompt.player_index == 1 and prompt.data["count"] == 3
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 2
    assert len(game.players[1].graveyard) == 4


def test_mind_burst_takes_what_there_is_from_a_short_hand(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Mind Burst"], gy0=["Mind Burst", "Mind Burst"],
        hand1=["Forest"],
    )
    assert game.cast_from_hand(0, "Mind Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert game.players[1].hand == []
    assert "Forest" in _w1g4_names(game.players[1].graveyard)


def test_a_chosen_discard_of_a_cast_x_reads_the_announced_number(set_pool):
    """The same handler under an X the caster pays for rather than counts."""
    warp = _w1g4_mk_card(
        "Mind Wrench", "{X}{B}", "Sorcery", "Target player discards X cards."
    )
    assert _w1g4_compile(warp).supported
    game = _w1g4_duel(set_pool, hand1=["Forest", "Island", "Swamp"])
    game.players[0].hand.append(warp)
    assert game.cast_from_hand(
        0, "Mind Wrench", target_player_index=1, x_value=2
    ).supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 1


# --- Hint of Insanity: "…the same name as another card in their hand" --------

def test_hint_of_insanity_discards_every_nonland_card_held_in_multiples(set_pool):
    """A pair and a triple go; the two Forests share a name and are lands, and
    the lone Wurm shares a name with nothing. Nobody chooses, so no prompt."""
    game = _w1g4_duel(
        set_pool, hand0=["Hint of Insanity"],
        hand1=["Grizzly Bears", "Forest", "Lightning Bolt", "Grizzly Bears",
               "Forest", "Craw Wurm", "Lightning Bolt", "Lightning Bolt"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert game.pending_choices == []
    assert _w1g4_names(game.players[1].hand) == ["Forest", "Forest", "Craw Wurm"]
    assert sorted(_w1g4_names(game.players[1].graveyard)) == [
        "Grizzly Bears", "Grizzly Bears",
        "Lightning Bolt", "Lightning Bolt", "Lightning Bolt",
    ]
    assert any(
        line.startswith("P1 reveals their hand") for line in game.log
    ), "the reveal is its own sentence and happens whatever is discarded"


def test_hint_of_insanity_with_no_pair_reveals_and_discards_nothing(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Hint of Insanity"],
        hand1=["Grizzly Bears", "Forest", "Forest", "Craw Wurm"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert len(game.players[1].hand) == 4 and game.players[1].graveyard == []
    assert any(line.startswith("P1 reveals their hand") for line in game.log)


def test_hint_of_insanity_at_its_own_caster_does_not_pair_with_itself(set_pool):
    """The copy being cast is on the stack, so a second Hint in hand shares a
    name with no *other card in that hand* — and the two Bears go."""
    game = _w1g4_duel(
        set_pool,
        hand0=["Hint of Insanity", "Hint of Insanity", "Grizzly Bears", "Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=0
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].hand) == ["Hint of Insanity"]
    assert game.players[1].hand == []


def test_hint_of_insanity_discards_through_the_discard_seam(set_pool):
    """Megrim sees each card: the discards are announced, not written."""
    game = _w1g4_duel(
        set_pool, hand0=["Hint of Insanity"],
        hand1=["Grizzly Bears", "Grizzly Bears", "Forest"], bf0=["Megrim"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 16


@_w1g4_pytest.mark.parametrize("line", [
    # "Another card" with no pile behind it compares against nobody knows what.
    "Target player discards all nonland cards with the same name as another card.",
    # A pile other than the one being discarded from is a different sentence.
    "Target player discards all nonland cards with the same name as another "
    "card in your hand.",
    # A card phrase compared with a permanent names two kinds of object.
    "Target player discards all nonland cards with the same name as another "
    "permanent.",
])
def test_the_shared_name_discard_refuses_what_it_cannot_compare(line):
    hint = _w1g4_mk_card("Odd Hint", "{B}", "Sorcery", line)
    assert not _w1g4_compile(hint).supported


# --- Haunting Echoes: a sweep of one graveyard, then a strip by every name ---

def test_haunting_echoes_exiles_the_graveyard_and_every_library_copy(set_pool):
    """The basic land stays in the graveyard and its copy in the library; the
    nonbasic land, the creature and the instant go from both. The caster's own
    graveyard and library are not touched."""
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"],
        gy1=["Grizzly Bears", "Forest", "Lightning Bolt", "Bayou"],
        lib1=["Grizzly Bears", "Forest", "Lightning Bolt", "Craw Wurm",
              "Grizzly Bears", "Bayou", "Island"],
        gy0=["Craw Wurm"], lib0=["Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Forest"]
    assert sorted(_w1g4_names(game.players[1].library)) == [
        "Craw Wurm", "Forest", "Island",
    ]
    assert sorted(_w1g4_names(game.players[1].exile)) == [
        "Bayou", "Bayou", "Grizzly Bears", "Grizzly Bears", "Grizzly Bears",
        "Lightning Bolt", "Lightning Bolt",
    ]
    assert _w1g4_names(game.players[0].library) == ["Grizzly Bears"]
    assert _w1g4_names(game.players[0].graveyard) == ["Craw Wurm", "Haunting Echoes"]
    assert game.players[0].exile == []


def test_haunting_echoes_over_only_basic_lands_strips_nothing(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"], gy1=["Forest", "Island"],
        lib1=["Forest", "Island", "Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Forest", "Island"]
    assert len(game.players[1].library) == 3 and game.players[1].exile == []


def test_haunting_echoes_may_be_aimed_at_its_caster(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"], gy0=["Grizzly Bears"],
        lib0=["Grizzly Bears", "Craw Wurm"], lib1=["Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=0
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].library) == ["Craw Wurm"]
    assert _w1g4_names(game.players[0].exile) == ["Grizzly Bears", "Grizzly Bears"]
    assert _w1g4_names(game.players[1].library) == ["Grizzly Bears"]


def test_haunting_echoes_shuffles_the_library_it_searched(set_pool):
    """CR 701.24. Fifteen distinct-order cards and a seeded RNG: the survivors'
    order changes, which an unshuffled strip would leave as it was."""
    import random

    library = (["Grizzly Bears"] + ["Forest", "Island", "Swamp", "Mountain",
               "Plains", "Craw Wurm", "Scryb Sprites", "Black Lotus",
               "Shivan Dragon", "Giant Growth", "Fireball", "Lightning Bolt",
               "Sol Ring", "Mox Pearl"])
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"], gy1=["Grizzly Bears"], lib1=library,
    )
    random.seed(11)
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    after = _w1g4_names(game.players[1].library)
    assert sorted(after) == sorted(library[1:])
    assert after != library[1:]


@_w1g4_pytest.mark.parametrize("text", [
    # No sweep in front of the loop: "exiled this way" names nothing.
    "For each card exiled this way, search target player's library for all "
    "cards with the same name as that card and exile them. Then that player "
    "shuffles.",
    # CR 701.24: a library search ends with the shuffle.
    "Exile all cards from target player's graveyard other than basic land "
    "cards. For each card exiled this way, search that player's library for "
    "all cards with the same name as that card and exile them.",
    # A loop over a narrower set than the sweep recorded.
    "Exile all cards from target player's graveyard. For each creature card "
    "exiled this way, search that player's library for all cards with the "
    "same name as that card and exile them. Then that player shuffles.",
    # "That card" outside any loop.
    "Search target player's library for all cards with the same name as that "
    "card and exile them. Then that player shuffles.",
])
def test_the_strip_by_exiled_names_refuses_without_its_sweep_and_shuffle(text):
    echoes = _w1g4_mk_card("Odd Echoes", "{B}", "Sorcery", text)
    assert not _w1g4_compile(echoes).supported


def test_a_sweep_of_a_chosen_graveyard_names_its_player(set_pool):
    """The sweep on its own, on an invented card: "target opponent's" pile and
    a narrowing the card matcher answers, with the caster's pile left alone."""
    purge = _w1g4_mk_card(
        "Grave Purge", "{B}", "Sorcery",
        "Exile all creature cards from target opponent's graveyard.",
    )
    assert _w1g4_compile(purge).supported
    game = _w1g4_duel(
        set_pool, gy0=["Grizzly Bears"], gy1=["Grizzly Bears", "Forest", "Craw Wurm"],
    )
    game.players[0].hand.append(purge)
    spec = game.cast_target_spec(0, purge)
    assert [t["seat"] for t in spec["valid_targets"]] == [1]
    assert game.cast_from_hand(0, "Grave Purge", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Forest"]
    assert _w1g4_names(game.players[0].graveyard) == ["Grizzly Bears", "Grave Purge"]

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
