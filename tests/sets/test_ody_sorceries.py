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


# --- Buried Alive, Diabolic Tutor, Extract -----------------------------------

_W1G4_LIBRARY = ["Forest", "Grizzly Bears", "Craw Wurm", "Scryb Sprites",
                 "Black Lotus", "Island", "Shivan Dragon"]


def test_buried_alive_puts_up_to_three_creature_cards_into_the_graveyard(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Buried Alive"], lib0=_W1G4_LIBRARY)
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Buried Alive").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["count"] == 3 and prompt.data["up_to"]
    assert prompt.data["card_type"] == "creature"
    assert prompt.data["destinations"] == ["graveyard"] * 3
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    buried = [n for n in _w1g4_names(game.players[0].graveyard) if n != "Buried Alive"]
    assert len(buried) == 3
    assert set(buried) <= {"Grizzly Bears", "Craw Wurm", "Scryb Sprites", "Shivan Dragon"}
    assert len(game.players[0].library) == 4 and game.players[0].hand == []


def test_buried_alive_over_a_library_of_no_creatures_finds_nothing(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Buried Alive"], lib0=["Forest", "Island"])
    assert game.cast_from_hand(0, "Buried Alive").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g4_names(game.players[0].graveyard) == ["Buried Alive"]
    assert len(game.players[0].library) == 2


def test_diabolic_tutor_finds_any_card_and_does_not_tell_the_table_which(set_pool):
    """A search with no reveal into a hidden zone: the log every viewer is
    sent says a card went to hand and never names it."""
    game = _w1g4_duel(set_pool, hand0=["Diabolic Tutor"], lib0=_W1G4_LIBRARY)
    assert game.cast_from_hand(0, "Diabolic Tutor").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    (found,) = _w1g4_names(game.players[0].hand)
    assert len(game.players[0].library) == 6
    assert not any(found in line for line in game.log)
    assert any("put a card into hand" in line for line in game.log)


def test_extract_exiles_a_card_from_the_library_of_the_player_it_names(set_pool):
    """The caster searches and chooses; the card goes to its owner's exile and
    the searched player's library is the one that shrinks."""
    game = _w1g4_duel(
        set_pool, hand0=["Extract"], lib0=["Swamp", "Plains"], lib1=_W1G4_LIBRARY,
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Extract", target_player_index=1).supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.player_index == 0, "CR 608.2c: the spell's controller chooses"
    assert prompt.data["zone_seat"] == 1 and prompt.data["destination"] == "exile"
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    assert len(game.players[1].library) == 6 and len(game.players[1].exile) == 1
    assert len(game.players[0].library) == 2 and game.players[0].exile == []

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


def _w1g7_picks(*indices):
    return [{"zone": "library", "index": index} for index in indices]


# --- Traumatize: half a library, rounded down ----------------------------------

@_w1g7_pytest.mark.parametrize(
    "library, milled", [(7, 3), (8, 4), (1, 0), (0, 0)],
)
def test_traumatize_mills_half_the_targets_library_rounded_down(
    set_pool, library, milled
):
    """"Target player mills half their library, rounded down." The half is
    taken as the spell resolves (CR 608.2h), of the *target's* library, and an
    empty one mills nothing and loses nobody the game (CR 704.5b is about a
    draw)."""
    game = _w1g7_duel(
        set_pool, hand0=["Traumatize"], lib0=["Island"] * 5,
        lib1=["Forest"] * library,
    )
    assert game.cast_from_hand(0, "Traumatize", target_player_index=1).supported
    _w1g7_settle(game)
    assert len(game.players[1].graveyard) == milled
    assert len(game.players[1].library) == library - milled
    assert len(game.players[0].library) == 5, "the caster's library is untouched"
    assert not game.players[1].lost


def test_traumatize_takes_the_top_cards_and_may_be_aimed_at_its_caster(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Traumatize"],
        lib1=["Forest", "Island", "Swamp", "Plains", "Mountain"],
    )
    game.cast_from_hand(0, "Traumatize", target_player_index=1)
    _w1g7_settle(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Forest", "Island"]
    assert _w1g7_names(game.players[1].library) == ["Swamp", "Plains", "Mountain"]

    own = _w1g7_duel(
        set_pool, hand0=["Traumatize"], lib0=["Island"] * 4, lib1=["Forest"] * 4,
    )
    own.cast_from_hand(0, "Traumatize", target_player_index=0)
    _w1g7_settle(own)
    assert len(own.players[0].library) == 2 and len(own.players[1].library) == 4


def test_a_fraction_of_a_library_is_one_quantity_however_it_is_spelled():
    """"Half their library" is "cards equal to half the number of cards in
    their library" without the noun, so both spell one spec — and the draw
    that has read the long form since Peer into the Abyss reads the same one.
    A set of seats refuses: the count is taken once."""
    def program(text):
        return _w1g7_compile(_w1g7_mk_card("Bisect", "{U}", "Sorcery", text))

    short = program("Target player mills half their library, rounded down.")
    long = program(
        "Target player mills cards equal to half the number of cards in their "
        "library, rounded down."
    )
    assert short.supported and long.supported
    assert short.instructions[0].payload == long.instructions[0].payload
    assert short.instructions[0].payload["x_from_count"] == {
        "zone": "library", "owner": "owner", "filter": {}, "half": "down",
    }
    up = program("Target player mills half their library, rounded up.")
    assert up.instructions[0].payload["x_from_count"]["half"] == "up"
    assert program("Mill half your library, rounded down.").supported
    assert not program("Each player mills half their library, rounded down.").supported
    assert not program("Target player mills half your library, rounded down.").supported
    assert not program("Target player mills half their graveyard.").supported


def test_a_rounded_up_half_and_a_third_are_counted_as_printed(set_pool):
    for text, expected in (
        ("Target player mills half their library, rounded up.", 4),
        ("Target player mills a third of their library, rounded down.", 2),
    ):
        game = _w1g7_duel(set_pool, lib1=["Forest"] * 7)
        game.players[0].hand.append(_w1g7_mk_card("Bisect", "{U}", "Sorcery", text))
        assert game.cast_from_hand(0, "Bisect", target_player_index=1).supported
        _w1g7_settle(game)
        assert len(game.players[1].graveyard) == expected, text


# --- Rites of Spring: a search with a recorded ceiling -------------------------

_W1G7_SPRING_LIBRARY = [
    "Forest", "Grizzly Bears", "Island", "Swamp", "Bayou", "Plains", "Mountain",
]


def test_rites_of_spring_finds_up_to_as_many_basics_as_cards_discarded(set_pool):
    """"Discard any number of cards. Search your library for up to that many
    basic land cards, reveal them, put them into your hand, then shuffle." Two
    discards is a ceiling of two; a nonbasic land, a nonland and a third find
    are each refused; finding fewer is legal (its ruling, 2004-10-04)."""
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Spring", "Grizzly Bears", "Giant Growth", "Terror"],
        lib0=_W1G7_SPRING_LIBRARY, interactive=(0,),
    )
    assert game.cast_from_hand(0, "Rites of Spring").supported
    assert game.confirm_discard(0, [0, 1])
    (search,) = game.pending_choices
    assert search.kind == "search_library"
    assert (search.data["count"], search.data["up_to"]) == (2, True)
    assert search.data["reveal"] is True

    library = _w1g7_names(game.players[0].library)
    at = library.index
    assert not game.confirm_search_library_picks(
        0, _w1g7_picks(at("Forest"), at("Island"), at("Swamp"))
    ), "three finds for two discards"
    assert not game.confirm_search_library_picks(0, _w1g7_picks(at("Bayou")))
    assert not game.confirm_search_library_picks(0, _w1g7_picks(at("Grizzly Bears")))
    assert game.confirm_search_library_picks(0, _w1g7_picks(at("Forest"), at("Island")))

    assert sorted(_w1g7_names(game.players[0].hand)) == ["Forest", "Island", "Terror"]
    assert sorted(_w1g7_names(game.players[0].library)) == sorted(
        ["Grizzly Bears", "Swamp", "Bayou", "Plains", "Mountain"]
    )
    assert not game.stack and not game.pending_choices
    assert any("revealed Forest, Island" in line for line in game.log)


def test_rites_of_spring_may_find_fewer_and_one_discard_is_one_find(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Spring", "Grizzly Bears", "Terror"],
        lib0=_W1G7_SPRING_LIBRARY, interactive=(0,),
    )
    game.cast_from_hand(0, "Rites of Spring")
    assert game.confirm_discard(0, [0, 1])
    library = _w1g7_names(game.players[0].library)
    assert game.confirm_search_library_picks(0, _w1g7_picks(library.index("Swamp")))
    assert _w1g7_names(game.players[0].hand) == ["Swamp"]

    single = _w1g7_duel(
        set_pool, hand0=["Rites of Spring", "Grizzly Bears"],
        lib0=_W1G7_SPRING_LIBRARY, interactive=(0,),
    )
    single.cast_from_hand(0, "Rites of Spring")
    assert single.confirm_discard(0, [0])
    library = _w1g7_names(single.players[0].library)
    assert not single.confirm_search_library(0, library.index("Bayou"))
    assert single.confirm_search_library(0, library.index("Mountain"))
    assert _w1g7_names(single.players[0].hand) == ["Mountain"]


def test_rites_of_spring_with_nothing_discarded_searches_for_nothing(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Spring", "Grizzly Bears"],
        lib0=_W1G7_SPRING_LIBRARY, interactive=(0,),
    )
    game.cast_from_hand(0, "Rites of Spring")
    assert game.confirm_discard(0, [])
    assert not game.pending_choices and not game.stack
    assert _w1g7_names(game.players[0].hand) == ["Grizzly Bears"]
    assert _w1g7_names(game.players[0].library) == _W1G7_SPRING_LIBRARY


def test_a_search_ceiling_with_no_record_behind_it_is_refused():
    assert not _w1g7_compile(_w1g7_mk_card(
        "Bare Spring", "{G}", "Sorcery",
        "Search your library for up to that many basic land cards, reveal "
        "them, put them into your hand, then shuffle.",
    )).supported


# --- Last Rites: a pick out of a revealed hand per card discarded --------------

def test_last_rites_takes_a_nonland_card_per_card_its_caster_discarded(set_pool):
    """"Discard any number of cards. Target player reveals their hand, then
    you choose a nonland card from it for each card discarded this way. That
    player discards those cards." The caster picks, a land is not a legal
    pick, and the picks number exactly what was discarded."""
    game = _w1g7_duel(
        set_pool, hand0=["Last Rites", "Forest", "Island", "Swamp"],
        hand1=["Grizzly Bears", "Forest", "Terror", "Giant Growth"],
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Last Rites", target_player_index=1).supported
    assert game.confirm_discard(0, [0, 1])
    (pick,) = game.pending_choices
    assert (pick.kind, pick.player_index) == ("revealed_hand_pick", 0)
    assert pick.data["legal_indices"] == [0, 2, 3]
    assert pick.data["remaining"] == 2

    assert not game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=1)
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=2)
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=0)
    assert not game.pending_choices and not game.stack

    assert _w1g7_names(game.players[1].hand) == ["Forest", "Giant Growth"]
    assert _w1g7_names(game.players[1].graveyard) == ["Terror", "Grizzly Bears"]
    assert _w1g7_names(game.players[0].hand) == ["Swamp"]


def test_last_rites_takes_what_there_is_and_reveals_even_for_nothing(set_pool):
    """Three discards against one nonland card is one pick (CR 608.2: as much
    as possible); no discards is a revealed hand and no pick."""
    game = _w1g7_duel(
        set_pool, hand0=["Last Rites", "Forest", "Island", "Swamp"],
        hand1=["Grizzly Bears", "Forest"], interactive=(0,),
    )
    game.cast_from_hand(0, "Last Rites", target_player_index=1)
    assert game.confirm_discard(0, [0, 1, 2])
    assert game.pending_choices[0].data["remaining"] == 1
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=0)
    assert _w1g7_names(game.players[1].hand) == ["Forest"]
    assert not game.pending_choices and not game.stack

    none = _w1g7_duel(
        set_pool, hand0=["Last Rites", "Forest"], hand1=["Grizzly Bears"],
        interactive=(0,),
    )
    none.cast_from_hand(0, "Last Rites", target_player_index=1)
    assert none.confirm_discard(0, [])
    assert not none.pending_choices and not none.stack
    assert _w1g7_names(none.players[1].hand) == ["Grizzly Bears"]
    assert any("revealed their hand" in line for line in none.log)


def test_last_rites_discards_reach_a_discard_watcher_on_both_sides(set_pool):
    """Both halves are discards (CR 701.9a) through the one seam: a Confessor
    hears the caster's own card and the one taken from the target."""
    game = _w1g7_duel(
        set_pool, hand0=["Last Rites", "Forest"], hand1=["Grizzly Bears", "Terror"],
        bf0=["Confessor"], interactive=(0,),
    )
    game.cast_from_hand(0, "Last Rites", target_player_index=1)
    assert game.confirm_discard(0, [0])
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=0)
    _w1g7_settle(game)
    assert game.players[0].life == 22


def test_a_counted_revealed_pick_needs_its_record_and_its_ending():
    def supported(text):
        return _w1g7_compile(_w1g7_mk_card("Rite", "{B}", "Sorcery", text)).supported

    pick = (
        "Target player reveals their hand, then you choose a nonland card "
        "from it for each card discarded this way."
    )
    assert supported(
        "Discard any number of cards. " + pick + " That player discards those cards."
    )
    assert not supported(pick + " That player discards those cards."), "no producer"
    assert not supported("Discard any number of cards. " + pick), "no fate"

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
