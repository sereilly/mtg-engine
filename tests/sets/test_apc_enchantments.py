"""Apocalypse enchantments.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _w1g4e_Game, PlayerState as _w1g4e_Player  # noqa: E402
from engine.grammar import compile_line as _w1g4e_compile_line  # noqa: E402
from engine.models import Permanent as _w1g4e_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w1g4e_compile  # noqa: E402

from tests.helpers import resolve_stack as _w1g4e_resolve_stack  # noqa: E402

#: Where a name in these tests is looked for, in order — one pool per card.
_W1G4E_POOLS = ("APC", "LEA", "USG")


def _w1g4e_card(set_pool, name):
    """*name* out of the first of this section's pools that prints it."""
    for code in _W1G4E_POOLS:
        found = set_pool(code).get(name)
        if found is not None:
            return found
    raise KeyError(name)  # W1G4 enchantments: no pool here prints that name


def _w1g4e_table(set_pool, *, mine=(), theirs=(), hand0=(), lib0=(), lib1=(),
                 interactive=(), unsick=True):
    """A duel with seat 0 in its precombat main phase and costs not enforced."""
    def cards(names):
        return [_w1g4e_card(set_pool, name) for name in names]

    board0 = [_w1g4e_Permanent(card=card) for card in cards(mine)]
    board1 = [_w1g4e_Permanent(card=card) for card in cards(theirs)]
    game = _w1g4e_Game(players=[
        _w1g4e_Player(name="P0", battlefield=board0, hand=cards(hand0),
                      library=cards(lib0)),
        _w1g4e_Player(name="P1", battlefield=board1, library=cards(lib1)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    if unsick:
        for permanent in board0 + board1:
            permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, board0, board1  # W1G4 enchantments: the table


def _w1g4e_names(cards):
    return [card.name for card in cards]  # W1G4 enchantments: a zone, by name


# -- Wild Research -----------------------------------------------------------

_W1G4E_RESEARCH_LIBRARY = [
    "Forest", "Pacifism", "Counterspell", "Island", "Circle of Protection: Red",
]


def test_w1g4_wild_research_tutors_an_enchantment_then_discards_at_random(set_pool):
    """"{1}{W}: Search your library for an enchantment card and reveal that
    card. Put it into your hand, then discard a card at random. Then shuffle."

    The find is in hand **before** the discard is made, so it is one of the
    cards the random discard may take: three cards in hand when the one is
    chosen, two afterwards. An instant is not an enchantment card.
    """
    research = _w1g4e_card(set_pool, "Wild Research")
    assert _w1g4e_compile(research).supported
    game, _, _ = _w1g4e_table(
        set_pool, mine=["Wild Research"], hand0=["Grizzly Bears", "Hill Giant"],
        lib0=_W1G4E_RESEARCH_LIBRARY, interactive=(0,),
    )
    assert game.queue_permanent_ability(0, "Wild Research", ability_index=0).supported
    game.resolve_top_of_stack()

    prompt = game.pending_search_library
    assert (prompt["count"], prompt["card_type"], prompt["reveal"]) == (1, "enchantment", True)
    assert _w1g4e_names(game.players[0].graveyard) == [], "no discard before the find"
    assert not game.confirm_search_library(0, 2), "Counterspell is an instant"
    assert not game.confirm_search_library(0, 0), "Forest is a land"
    assert game.confirm_search_library(0, 1)
    _w1g4e_resolve_stack(game)

    hand = _w1g4e_names(game.players[0].hand)
    discarded = _w1g4e_names(game.players[0].graveyard)
    assert len(hand) == 2 and len(discarded) == 1
    assert sorted(hand + discarded) == ["Grizzly Bears", "Hill Giant", "Pacifism"]
    assert game.reveal_events[-1]["cards"] == ["Pacifism"]
    assert sorted(_w1g4e_names(game.players[0].library)) == sorted(
        ["Forest", "Counterspell", "Island", "Circle of Protection: Red"]
    )
    log = "\n".join(game.log)
    assert log.index("put Pacifism into hand") < log.index("discarded 1 cards at random")


def test_w1g4_wild_researchs_blue_ability_finds_an_instant(set_pool):
    """"{1}{U}: Search your library for an **instant** card…" — the second
    ability, and a different find: the enchantments are refused here."""
    game, _, _ = _w1g4e_table(
        set_pool, mine=["Wild Research"], lib0=_W1G4E_RESEARCH_LIBRARY,
        interactive=(0,),
    )
    assert game.queue_permanent_ability(0, "Wild Research", ability_index=1).supported
    game.resolve_top_of_stack()

    assert game.pending_search_library["card_type"] == "instant"
    assert not game.confirm_search_library(0, 1), "Pacifism is an enchantment"
    assert game.confirm_search_library(0, 2)
    _w1g4e_resolve_stack(game)

    assert game.players[0].hand == [], "the only card in hand was the one found"
    assert _w1g4e_names(game.players[0].graveyard) == ["Counterspell"]


def test_w1g4_wild_research_still_discards_when_it_finds_nothing(set_pool):
    """The ruling: "You do not have to find an enchantment or instant card if
    you do not want to." Failing to find is an answer (CR 701.23b), and the
    discard is not conditional on the find — a card still goes."""
    game, _, _ = _w1g4e_table(
        set_pool, mine=["Wild Research"], hand0=["Grizzly Bears"],
        lib0=_W1G4E_RESEARCH_LIBRARY, interactive=(0,),
    )
    assert game.queue_permanent_ability(0, "Wild Research", ability_index=0).supported
    game.resolve_top_of_stack()
    assert game.decline_search_library(0)
    _w1g4e_resolve_stack(game)

    assert game.players[0].hand == []
    assert _w1g4e_names(game.players[0].graveyard) == ["Grizzly Bears"]
    assert len(game.players[0].library) == len(_W1G4E_RESEARCH_LIBRARY)


def test_w1g4_wild_research_random_discard_comes_off_the_seeded_rng(set_pool):
    """Determinism: the same seed discards the same card, and over many seeds
    every card in the hand — the one just found included — is taken sometimes."""
    import random

    def discarded(seed):
        random.seed(seed)
        game, _, _ = _w1g4e_table(
            set_pool, mine=["Wild Research"], hand0=["Grizzly Bears", "Hill Giant"],
            lib0=["Pacifism"],
        )
        assert game.activate_permanent_ability(
            0, "Wild Research", ability_index=0
        ).supported
        game.auto_resolve_pending_choices()
        _w1g4e_resolve_stack(game)
        (card,) = game.players[0].graveyard
        return card.name  # W1G4 enchantments: what one seed discarded

    assert discarded(7) == discarded(7)
    assert {discarded(seed) for seed in range(24)} == {
        "Grizzly Bears", "Hill Giant", "Pacifism",
    }


def test_w1g4_the_older_tutor_punctuation_is_the_same_tutor_and_still_refuses():
    """The production's two halves. Wild Research's "and reveal that card. Put
    it … then discard a card at random. Then shuffle." lowers to exactly what
    the modern comma spelling does, and the search still refuses a line with
    its shuffle or its destination missing."""
    older = (
        "Search your library for an enchantment card and reveal that card. Put "
        "it into your hand, then discard a card at random. Then shuffle."
    )
    modern = (
        "Search your library for an enchantment card, reveal it, put it into "
        "your hand, discard a card at random, then shuffle."
    )
    assert _w1g4e_compile_line(older).usable
    assert _w1g4e_compile_line(older).instructions == _w1g4e_compile_line(modern).instructions
    assert not _w1g4e_compile_line(older.replace(" Then shuffle.", "")).parsed
    assert not _w1g4e_compile_line(
        "Search your library for an enchantment card and reveal that card. "
        "Then shuffle."
    ).parsed


# -- Symbiotic Deployment ----------------------------------------------------


def test_w1g4_symbiotic_deployment_skips_its_controllers_draw_step_only(set_pool):
    """"Skip your draw step." CR 614.10: the controller's draw step does not
    happen, and the opponent's does."""
    game, _, _ = _w1g4e_table(
        set_pool, mine=["Symbiotic Deployment"], lib0=["Forest", "Island"],
        lib1=["Swamp", "Plains"],
    )
    game.turn = 3  # past the first turn, whose draw step CR 103.8a skips anyway

    assert game.resolve_draw_step(0) == 0
    assert game.players[0].hand == []
    assert _w1g4e_names(game.players[0].library) == ["Forest", "Island"]
    assert "P0 skips their draw step (Symbiotic Deployment)" in game.log

    assert game.resolve_draw_step(1) == 1
    assert _w1g4e_names(game.players[1].hand) == ["Swamp"]


def test_w1g4_symbiotic_deployment_taps_two_untapped_creatures_to_draw(set_pool):
    """"{1}, Tap two untapped creatures you control: Draw a card." The two
    named are the two tapped — creatures that came in this turn included, since
    the cost is not their own {T} (CR 302.6) — and one card is drawn."""
    game, mine, _ = _w1g4e_table(
        set_pool,
        mine=["Symbiotic Deployment", "Grizzly Bears", "Hill Giant", "Llanowar Elves"],
        lib0=["Forest", "Island"], unsick=False,
    )
    _, bears, giant, elves = mine
    result = game.activate_permanent_ability(
        0, "Symbiotic Deployment", ability_index=0,
        cost_permanent_ids=[giant.permanent_id, elves.permanent_id],
    )
    assert result.supported, result.details
    _w1g4e_resolve_stack(game)

    assert (bears.tapped, giant.tapped, elves.tapped) == (False, True, True)
    assert not mine[0].tapped, "the enchantment itself is not tapped"
    assert _w1g4e_names(game.players[0].hand) == ["Forest"]


def test_w1g4_symbiotic_deployment_refuses_a_cost_it_cannot_be_paid(set_pool):
    """A printed cost is paid as printed or not at all: one untapped creature
    is not two, and neither an opponent's creature nor a tapped one of the
    controller's can be named — each refused with nothing tapped and no card
    drawn."""
    game, mine, theirs = _w1g4e_table(
        set_pool,
        mine=["Symbiotic Deployment", "Grizzly Bears", "Hill Giant", "Llanowar Elves"],
        theirs=["Serra Angel"], lib0=["Forest", "Island"],
    )
    _, bears, giant, elves = mine
    theirs_named = game.activate_permanent_ability(
        0, "Symbiotic Deployment", ability_index=0,
        cost_permanent_ids=[bears.permanent_id, theirs[0].permanent_id],
    )
    assert not theirs_named.supported
    giant.tapped = True
    tapped_named = game.activate_permanent_ability(
        0, "Symbiotic Deployment", ability_index=0,
        cost_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    assert not tapped_named.supported
    assert (bears.tapped, elves.tapped, theirs[0].tapped) == (False, False, False)
    assert game.players[0].hand == []

    elves.tapped = True
    one_left = game.activate_permanent_ability(0, "Symbiotic Deployment", ability_index=0)
    assert not one_left.supported
    assert "not enough untapped creatures" in one_left.details
    assert not bears.tapped and game.players[0].hand == []


# -- Goblin Trenches ---------------------------------------------------------


def test_w1g4_goblin_trenches_turns_a_land_into_two_goblin_soldiers(set_pool):
    """"{2}, Sacrifice a land: Create two 1/1 red and white Goblin Soldier
    creature tokens." The land named is the land sacrificed, and the tokens are
    both colours and both types."""
    game, mine, _ = _w1g4e_table(
        set_pool, mine=["Goblin Trenches", "Mountain", "Plains", "Grizzly Bears"],
    )
    mountain = mine[1]
    result = game.activate_permanent_ability(
        0, "Goblin Trenches", ability_index=0,
        cost_permanent_ids=[mountain.permanent_id],
    )
    assert result.supported, result.details
    _w1g4e_resolve_stack(game)
    game._settle()

    tokens = [perm for perm in game.controlled_by(0) if perm.metadata.get("is_token")]
    assert len(tokens) == 2
    for token in tokens:
        assert (token.effective_power, token.effective_toughness) == (1, 1)
        assert token.effective_colors == {"R", "W"}
        assert token.is_creature and token.has_type("goblin") and token.has_type("soldier")
    assert not game.is_on_battlefield(mountain)
    assert game.is_on_battlefield(mine[2]) and game.is_on_battlefield(mine[3])
    assert _w1g4e_names(game.players[0].graveyard) == ["Mountain"]


def test_w1g4_goblin_trenches_sacrifices_a_land_of_its_controllers_or_nothing(set_pool):
    """"Sacrifice a **land**": a creature named for the cost is refused, so is
    the opponent's land, and with no land left the ability cannot be activated
    — no tokens for free in any of the three."""
    game, mine, theirs = _w1g4e_table(
        set_pool, mine=["Goblin Trenches", "Mountain", "Grizzly Bears"],
        theirs=["Forest"],
    )
    for named in (mine[2], theirs[0]):
        refused = game.activate_permanent_ability(
            0, "Goblin Trenches", ability_index=0,
            cost_permanent_ids=[named.permanent_id],
        )
        assert not refused.supported, named.card.name
        assert game.is_on_battlefield(named)
    assert game.activate_permanent_ability(0, "Goblin Trenches", ability_index=0).supported
    _w1g4e_resolve_stack(game)
    landless = game.activate_permanent_ability(0, "Goblin Trenches", ability_index=0)
    assert not landless.supported and "no land available" in landless.details
    assert sum(1 for perm in game.controlled_by(0) if perm.metadata.get("is_token")) == 2
    assert game.is_on_battlefield(theirs[0])


# -- Overgrown Estate --------------------------------------------------------


def test_w1g4_overgrown_estate_trades_a_land_for_three_life(set_pool):
    """"Sacrifice a land: You gain 3 life." No mana and no tap, so every land
    is three life; a creature is not a land, and with none left there is
    nothing to pay with."""
    game, mine, _ = _w1g4e_table(
        set_pool, mine=["Overgrown Estate", "Forest", "Swamp", "Grizzly Bears"],
    )
    not_a_land = game.activate_permanent_ability(
        0, "Overgrown Estate", ability_index=0,
        cost_permanent_ids=[mine[3].permanent_id],
    )
    assert not not_a_land.supported and game.players[0].life == 20

    for expected in (23, 26):
        assert game.activate_permanent_ability(0, "Overgrown Estate", ability_index=0).supported
        _w1g4e_resolve_stack(game)
        assert game.players[0].life == expected
    assert sorted(_w1g4e_names(game.players[0].graveyard)) == ["Forest", "Swamp"]
    assert not mine[0].tapped

    landless = game.activate_permanent_ability(0, "Overgrown Estate", ability_index=0)
    assert not landless.supported and game.players[0].life == 26
    assert game.is_on_battlefield(mine[3])

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
