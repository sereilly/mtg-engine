"""Betrayers of Kamigawa sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

from engine import Game as _W1G10Game
from engine.models import PlayerState as _W1G10PlayerState
from tests.helpers import settle as _w1g10_settle


def _w1g10_table(set_pool, *, hand=(), library=(), opponent_library=None,
                 graveyard=(), opponent_hand=(), opponent_graveyard=()):
    """Alice's first main phase, costs off, both seats headless."""
    lea = set_pool("LEA")
    game = _W1G10Game(players=[
        _W1G10PlayerState(name="Alice", hand=list(hand), library=list(library),
                          graveyard=list(graveyard)),
        _W1G10PlayerState(
            name="Bob", hand=list(opponent_hand),
            graveyard=list(opponent_graveyard),
            library=list(opponent_library if opponent_library is not None
                         else [lea["Island"]] * 10),
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g10_settle(game)
    return game


def test_w1g10_heed_the_mists_draws_the_milled_cards_mana_value(set_pool):
    """Heed the Mists: "Mill a card, then draw cards equal to the milled card's
    mana value." A milled Hill Giant ({3}{R}) draws four cards."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    library = [lea["Hill Giant"], *[lea["Island"]] * 6]
    game = _w1g10_table(set_pool, hand=[bok["Heed the Mists"]], library=library)
    assert game.cast_from_hand(0, "Heed the Mists").supported
    _w1g10_settle(game)
    alice = game.players[0]
    assert [card.name for card in alice.graveyard] == ["Hill Giant", "Heed the Mists"]
    assert [card.name for card in alice.hand] == ["Island"] * 4
    assert len(alice.library) == 2


def test_w1g10_heed_the_mists_a_milled_land_draws_nothing(set_pool):
    """A land's mana value is 0, so nothing is drawn; an empty library mills
    nothing and draws nothing (CR 107.2's zero), and no one loses for it."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g10_table(set_pool, hand=[bok["Heed the Mists"]] * 2,
                        library=[lea["Island"], lea["Hill Giant"]])
    assert game.cast_from_hand(0, "Heed the Mists").supported
    _w1g10_settle(game)
    alice = game.players[0]
    assert [card.name for card in alice.graveyard] == ["Island", "Heed the Mists"]
    assert [card.name for card in alice.hand] == ["Heed the Mists"]
    alice.library.clear()
    assert game.cast_from_hand(0, "Heed the Mists").supported
    _w1g10_settle(game)
    assert alice.hand == []
    assert not game.is_game_over()


def test_w1g10_enshrined_memories_keeps_the_creatures_among_the_top_x(set_pool):
    """Enshrined Memories, X=3: "Reveal the top X cards of your library. Put all
    creature cards revealed this way into your hand and the rest on the bottom
    of your library in any order." The fourth card is never revealed."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Island"], lea["Hill Giant"],
               lea["Llanowar Elves"], lea["Forest"]]
    game = _w1g10_table(set_pool, hand=[bok["Enshrined Memories"]], library=library)
    assert game.cast_from_hand(0, "Enshrined Memories", x_value=3).supported
    _w1g10_settle(game)
    alice = game.players[0]
    assert sorted(card.name for card in alice.hand) == ["Grizzly Bears", "Hill Giant"]
    assert [card.name for card in alice.library] == [
        "Llanowar Elves", "Forest", "Island",
    ]
    assert any("revealed Grizzly Bears, Island, Hill Giant" in line for line in game.log)


def test_w1g10_enshrined_memories_for_zero_reveals_nothing(set_pool):
    """X=0 reveals no card and moves none."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Island"]]
    game = _w1g10_table(set_pool, hand=[bok["Enshrined Memories"]], library=library)
    assert game.cast_from_hand(0, "Enshrined Memories", x_value=0).supported
    _w1g10_settle(game)
    alice = game.players[0]
    assert alice.hand == []
    assert [card.name for card in alice.library] == ["Grizzly Bears", "Island"]


def test_w1g10_psychic_spear_offers_only_spirit_or_arcane_cards(set_pool):
    """Psychic Spear: "Target player reveals their hand. You choose a Spirit or
    Arcane card from it. That player discards that card." Asked of a person:
    of Bob's four cards the picker offers the Spirit creature and the Arcane
    sorcery, never the Bears or the Bolt; the chosen card is discarded."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    bob_hand = [lea["Grizzly Bears"], bok["Bile Urchin"], lea["Lightning Bolt"],
                bok["Heed the Mists"]]
    game = _w1g10_table(set_pool, hand=[bok["Psychic Spear"]], opponent_hand=bob_hand)
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Psychic Spear", target_player_index=1).supported
    owed = _w1g10_settle(game, defaults=False)
    assert owed is not None and owed.kind == "revealed_hand_pick"
    bob = game.players[1]
    offered = sorted(bob.hand[i].name for i in owed.data["legal_indices"])
    assert offered == ["Bile Urchin", "Heed the Mists"]
    index = next(i for i, held in enumerate(bob.hand) if held.name == "Heed the Mists")
    assert game.confirm_revealed_hand_pick(0, index)
    _w1g10_settle(game)
    assert [card.name for card in bob.graveyard] == ["Heed the Mists"]
    assert sorted(card.name for card in bob.hand) == [
        "Bile Urchin", "Grizzly Bears", "Lightning Bolt",
    ]


def test_w1g10_psychic_spear_with_no_spirit_or_arcane_discards_nothing(set_pool):
    """A hand with neither is revealed and nothing is discarded; a headless
    caster takes a Spirit when there is one."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g10_table(set_pool, hand=[bok["Psychic Spear"]] * 2,
                        opponent_hand=[lea["Grizzly Bears"], lea["Lightning Bolt"]])
    assert game.cast_from_hand(0, "Psychic Spear", target_player_index=1).supported
    _w1g10_settle(game)
    bob = game.players[1]
    assert bob.graveyard == [] and len(bob.hand) == 2
    assert any("Bob revealed their hand (2 card(s))" in line for line in game.log)
    bob.hand.append(bok["Bile Urchin"])
    assert game.cast_from_hand(0, "Psychic Spear", target_player_index=1).supported
    _w1g10_settle(game)
    assert [card.name for card in bob.graveyard] == ["Bile Urchin"]


def test_w1g10_sway_of_the_stars_resets_the_whole_table(set_pool):
    """Sway of the Stars: "Each player shuffles their hand, graveyard, and all
    permanents they own into their library, then draws seven cards. Each
    player's life total becomes 7." Alice has stolen Bob's Hill Giant with
    Control Magic: the Giant goes to Bob's library (CR 400.3, its owner's), the
    Aura and her Bears to hers; her token ceases to exist (2005-02-01). The
    Sway is on the stack and is not shuffled in (2013-07-01): it ends in her
    graveyard alone. Both players draw seven; Alice gains to 7, Bob loses to 7
    (CR 119.5)."""
    from engine.models import Permanent as _Permanent
    from engine.tokens import make_token_card

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g10_table(
        set_pool,
        hand=[bok["Sway of the Stars"], lea["Control Magic"], lea["Island"]],
        library=[lea["Forest"]] * 10,
        graveyard=[lea["Lightning Bolt"]],
        opponent_hand=[lea["Dark Ritual"]],
        opponent_graveyard=[lea["Shivan Dragon"]],
        opponent_library=[lea["Swamp"]] * 10,
    )
    alice, bob = game.players
    bears = _Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    token = _Permanent(card=make_token_card("Soldier Token", 1, 1, "Creature — Soldier"))
    game._put_permanent_onto_battlefield(0, token, None)
    giant = _Permanent(card=lea["Hill Giant"])
    game._put_permanent_onto_battlefield(1, giant, None)
    game._sync_control()
    assert game.cast_from_hand(
        0, "Control Magic", target_permanent_ids=[giant.permanent_id]
    ).supported
    _w1g10_settle(game)
    assert game.controller_index_of(giant) == 0
    alice.life, bob.life = 3, 20
    assert game.cast_from_hand(0, "Sway of the Stars").supported
    _w1g10_settle(game)
    assert list(game.all_permanents()) == []
    assert [card.name for card in alice.graveyard] == ["Sway of the Stars"]
    assert bob.graveyard == []
    assert len(alice.hand) == 7 and len(bob.hand) == 7
    alice_cards = sorted(card.name for card in alice.hand + alice.library)
    assert alice_cards == sorted(
        ["Forest"] * 10 + ["Control Magic", "Island", "Lightning Bolt", "Grizzly Bears"]
    )
    bob_cards = sorted(card.name for card in bob.hand + bob.library)
    assert bob_cards == sorted(["Swamp"] * 10 + ["Dark Ritual", "Shivan Dragon", "Hill Giant"])
    assert (alice.life, bob.life) == (7, 7)
    assert not any("Soldier Token" in card.name for card in alice.hand + alice.library)

# ==== end w1g10 ======================================================
