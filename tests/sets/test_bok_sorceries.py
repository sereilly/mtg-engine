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
#
# The drive list: Arcane sorceries supported on arrival, each given a game.

from engine import Game as _w1g3_Game
from engine import PlayerState as _w1g3_PlayerState
from engine.models import Permanent as _w1g3_Permanent
from tests.helpers import settle as _w1g3_settle

#: Where each card the section names is looked up, in order.
_W1G3_SETS = ("BOK", "CHK", "LEA")


def _w1g3_card(set_pool, name):
    for code in _W1G3_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g3_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=()):
    cards = lambda names: [_w1g3_card(set_pool, n) for n in names]  # noqa: E731
    island = _w1g3_card(set_pool, "Island")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState("A", hand=cards(hand), library=[island] * 10),
        _w1g3_PlayerState("B", hand=cards(opponent_hand), library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g3_Permanent(card=_w1g3_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g3_settle(game)
    return game, placed[0], placed[1]


def test_w1g3_terashis_grasp_destroys_and_gains_the_mana_value(set_pool):
    game, _mine, (icy,) = _w1g3_table(
        set_pool, hand=["Terashi's Grasp"], theirs=["Icy Manipulator"],
    )
    assert game.cast_from_hand(
        0, "Terashi's Grasp", target_permanent_ids=[icy.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert not game.is_on_battlefield(icy) and game.players[0].life == 24


def test_w1g3_three_tragedies_makes_its_target_discard_three(set_pool):
    game, _mine, _theirs = _w1g3_table(
        set_pool, hand=["Three Tragedies"],
        opponent_hand=["Island", "Mountain", "Forest", "Swamp"],
    )
    assert game.cast_from_hand(0, "Three Tragedies", target_player_index=1).supported
    _w1g3_settle(game)
    assert len(game.players[1].hand) == 1 and len(game.players[1].graveyard) == 3


def test_w1g3_uproot_puts_the_land_on_top_of_its_owners_library(set_pool):
    game, _mine, (mountain,) = _w1g3_table(set_pool, hand=["Uproot"], theirs=["Mountain"])
    assert game.cast_from_hand(
        0, "Uproot", target_permanent_ids=[mountain.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert not game.is_on_battlefield(mountain)
    assert game.players[1].library[0].name == "Mountain"


def test_w1g3_crack_the_earth_has_each_player_sacrifice_a_permanent(set_pool):
    game, (_bears, mountain), (_giant, forest) = _w1g3_table(
        set_pool, hand=["Crack the Earth"],
        mine=["Grizzly Bears", "Mountain"], theirs=["Hill Giant", "Forest"],
    )
    assert game.cast_from_hand(0, "Crack the Earth").supported
    _w1g3_settle(game)
    assert len(list(game.controlled_by(0))) == 1 and len(list(game.controlled_by(1))) == 1
    assert not game.is_on_battlefield(mountain) and not game.is_on_battlefield(forest)


def test_w1g3_ribbons_of_the_reikai_draws_a_card_for_each_spirit(set_pool):
    game, _mine, _theirs = _w1g3_table(
        set_pool, hand=["Ribbons of the Reikai"],
        mine=["Kami of Ancient Law", "Kami of Ancient Law", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Ribbons of the Reikai").supported
    _w1g3_settle(game)
    assert len(game.players[0].hand) == 2

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_derive_cast_spec
from tests.helpers import settle as _w1g4_settle


def _w1g4_card(set_pool, name):
    """A card by name, from Betrayers of Kamigawa first and Alpha for fillers."""
    bok = set_pool("BOK")
    return bok[name] if name in bok else set_pool("LEA")[name]


def _w1g4_table(set_pool, hand=(), *, mine=(), theirs=(), active=0):
    """Seat 0 to act in *active*'s first main phase, mana off; each named
    permanent untapped and able to act."""
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    game = _w1g4_Game(players=[
        _w1g4_PlayerState("A", hand=[card(n) for n in hand], library=[card("Forest")] * 12),
        _w1g4_PlayerState("B", library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g4_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(active)
    game._settle()
    return game, placed[0], placed[1]


def test_w1g4_twist_allegiance_announces_its_opponent(set_pool):
    """"You and **target opponent** …": the cast derivation offers an
    opponent picker (``picker_sweep``'s one Betrayers of Kamigawa finding —
    with none, a client sent a bare cast). Reins of Power, whose seat its
    untap sweep announces, keeps the picker it had."""
    twist = set_pool("BOK")["Twist Allegiance"]
    assert _w1g4_derive_cast_spec(twist, _w1g4_compile(twist)) == {
        "kind": "player", "opponents_only": True,
    }


def test_w1g4_twist_allegiance_swaps_untaps_and_hastes_both_boards(set_pool):
    """Each player gains control of every creature the other controlled,
    untapped and hasty, until end of turn; at cleanup each goes home."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Twist Allegiance"], mine=["Grizzly Bears"], theirs=["Hill Giant"],
    )
    mine[0].tapped = theirs[0].tapped = True
    result = game.cast_from_hand(0, "Twist Allegiance", target_player_index=1)
    assert result.supported, result.details
    _w1g4_settle(game)
    assert game.controller_index_of(theirs[0]) == 0, game.log
    assert game.controller_index_of(mine[0]) == 1, game.log
    for creature in (mine[0], theirs[0]):
        assert not creature.tapped
        assert game._has_keyword(creature, "haste")
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    _w1g4_settle(game)
    assert game.controller_index_of(theirs[0]) == 1
    assert game.controller_index_of(mine[0]) == 0
    assert not game._has_keyword(theirs[0], "haste")


def test_w1g4_sosukes_summons_comes_back_for_a_nontoken_snake(set_pool):
    """Two Snake tokens; a second Summons' token Snakes do not return the
    first ("nontoken"); a nontoken Snake entering returns each copy waiting
    in the graveyard (one trigger per copy, CR 113.6k: it functions there)."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Sosuke's Summons", "Sosuke's Summons"],
    )
    game.players[0].hand.append(set_pool("CHK")["Orochi Sustainer"])
    assert game.cast_from_hand(0, "Sosuke's Summons").supported
    _w1g4_settle(game)
    snakes = [p for p in game.controlled_by(0) if p.card.name == "Snake Token"]
    assert len(snakes) == 2 and all(p.has_type("snake") for p in snakes)
    assert game.cast_from_hand(0, "Sosuke's Summons").supported
    _w1g4_settle(game)
    names = lambda cards: [c.name for c in cards]  # noqa: E731
    assert names(game.players[0].graveyard) == ["Sosuke's Summons"] * 2, game.log
    assert game.cast_from_hand(0, "Orochi Sustainer").supported
    _w1g4_settle(game)
    assert names(game.players[0].hand) == ["Sosuke's Summons"] * 2, game.log
    assert names(game.players[0].graveyard) == []

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.
#
# Stir the Grave: a graveyard target bounded by the announced X.
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=(), graveyard=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), graveyard=list(graveyard),
                         library=[lea["Island"]] * 10),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def test_w1g6_stir_the_grave_returns_a_creature_card_up_to_x(set_pool):
    """"Return target creature card with mana value X or less from your
    graveyard to the battlefield." X is announced before the target
    (CR 601.2b): X=2 cannot name Hill Giant (mana value 4) and the cast is
    refused before anything is paid; it returns Grizzly Bears. Cast again at
    X=4, it returns the Giant."""
    lea = set_pool("LEA")
    stir = set_pool("BOK")["Stir the Grave"]
    game = _w1g6_table(
        set_pool, hand=[stir, stir], graveyard=[lea["Grizzly Bears"], lea["Hill Giant"]],
    )
    assert not game.cast_from_hand(
        0, "Stir the Grave", x_value=2, target_graveyard_indices=[1],
    ).supported
    assert len(game.players[0].hand) == 2
    assert game.cast_from_hand(
        0, "Stir the Grave", x_value=2, target_graveyard_indices=[0],
    ).supported
    _w1g6_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert game.cast_from_hand(
        0, "Stir the Grave", x_value=4,
        target_graveyard_indices=[
            [card.name for card in game.players[0].graveyard].index("Hill Giant")
        ],
    ).supported
    _w1g6_settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Grizzly Bears", "Hill Giant",
    ]


def test_w1g6_stir_the_grave_at_x_zero_has_no_target(set_pool):
    """No creature card in the graveyard has mana value 0, so X=0 has no legal
    target (CR 601.2c) and the cast is refused."""
    lea = set_pool("LEA")
    game = _w1g6_table(
        set_pool, hand=[set_pool("BOK")["Stir the Grave"]],
        graveyard=[lea["Grizzly Bears"]],
    )
    assert not game.cast_from_hand(
        0, "Stir the Grave", x_value=0, target_graveyard_indices=[0],
    ).supported
    assert not game.players[0].battlefield

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
