"""Betrayers of Kamigawa creatures (legendary ones too) — the later groups' sections.

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
from engine.models import Permanent as _W1G10Permanent
from engine.models import PlayerState as _W1G10PlayerState
from tests.helpers import settle as _w1g10_settle


def _w1g10_game(*, mine=(), hand=(), library=(), graveyard=(), theirs=(),
                opponent_hand=(), opponent_library=None, island=None):
    """Alice's first main phase, costs off, both seats headless."""
    game = _W1G10Game(players=[
        _W1G10PlayerState(
            name="Alice", hand=list(hand), library=list(library),
            graveyard=list(graveyard),
            battlefield=[_W1G10Permanent(card=c) for c in mine],
        ),
        _W1G10PlayerState(
            name="Bob", hand=list(opponent_hand),
            battlefield=[_W1G10Permanent(card=c) for c in theirs],
            library=list(opponent_library if opponent_library is not None
                         else [island] * 10),
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    for perm in game.all_permanents():
        perm.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    _w1g10_settle(game)
    return game


def _w1g10_tallowisp_game(set_pool):
    bok, lea, leg = set_pool("BOK"), set_pool("LEA"), set_pool("LEG")
    library = [lea["Wild Growth"], lea["Animate Dead"], leg["Cocoon"],
               lea["Holy Strength"], lea["Island"]]
    return _w1g10_game(
        mine=[bok["Tallowisp"]], hand=[bok["Bile Urchin"], lea["Grizzly Bears"]],
        library=library, island=lea["Island"],
    )


def test_w1g10_tallowisp_finds_only_an_aura_with_enchant_creature(set_pool):
    """Tallowisp: "Whenever you cast a Spirit or Arcane spell, you may search
    your library for an Aura card with enchant creature, reveal it, put it
    into your hand, then shuffle." Asked of a person: Bile Urchin (a Spirit)
    triggers it; the search refuses Wild Growth (enchant land), Animate Dead
    ("enchant creature card in a graveyard") and Cocoon ("enchant creature you
    control") — CR 702.5a's ability is its whole subject — and takes Holy
    Strength."""
    game = _w1g10_tallowisp_game(set_pool)
    game.interactive_seats = {0}
    alice = game.players[0]
    assert game.cast_from_hand(0, "Bile Urchin").supported
    owed = _w1g10_settle(game, defaults=False)
    assert owed is not None and owed.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    owed = _w1g10_settle(game, defaults=False)
    assert owed is not None and owed.kind == "search_library"
    names = [card.name for card in alice.library]
    for refused in ("Wild Growth", "Animate Dead", "Cocoon", "Island"):
        assert not game.confirm_search_library(0, names.index(refused)), refused
    assert game.confirm_search_library(0, names.index("Holy Strength"))
    _w1g10_settle(game)
    assert sorted(card.name for card in alice.hand) == ["Grizzly Bears", "Holy Strength"]
    assert len(alice.library) == 4


def test_w1g10_tallowisp_ignores_a_spell_that_is_neither_spirit_nor_arcane(set_pool):
    """A Grizzly Bears is no Spirit: nothing triggers. A headless seat takes
    the offer on Bile Urchin and finds the one legal Aura."""
    game = _w1g10_tallowisp_game(set_pool)
    alice = game.players[0]
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g10_settle(game)
    assert [card.name for card in alice.hand] == ["Bile Urchin"]
    assert len(alice.library) == 5
    assert game.cast_from_hand(0, "Bile Urchin").supported
    _w1g10_settle(game)
    assert [card.name for card in alice.hand] == ["Holy Strength"]


def _w1g10_tomorrow_game(set_pool, library_names):
    bok, lea = set_pool("BOK"), set_pool("LEA")
    return _w1g10_game(
        mine=[bok["Tomorrow, Azami's Familiar"]],
        library=[lea[name] for name in library_names], island=lea["Island"],
    )


def test_w1g10_tomorrow_replaces_each_draw_with_a_look_and_a_keep(set_pool):
    """Tomorrow, Azami's Familiar: "If you would draw a card, look at the top
    three cards of your library instead. Put one of those cards into your hand
    and the rest on the bottom of your library in any order." Two draws, asked
    of a person, are two looks in turn (2005-02-01): Alice keeps the Hill Giant
    of the first three and orders the other two onto the bottom; the second
    look is of the new top three, and the second draw waited for the first."""
    game = _w1g10_tomorrow_game(set_pool, [
        "Grizzly Bears", "Hill Giant", "Island", "Forest", "Lightning Bolt", "Dark Ritual",
    ])
    game.interactive_seats = {0}
    alice = game.players[0]
    drawn_before = list(alice.cards_drawn_this_turn)
    assert game._draw_with_replacements(alice, 2) == 0
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "look_top_pick" and owed.data["top_count"] == 3
    assert alice.hand == []
    assert game.confirm_look_top_pick(0, 1)
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "reorder_library" and owed.data["position"] == "bottom"
    assert game.confirm_reorder_library(0, [1, 0])
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "look_top_pick"
    assert [card.name for card in alice.library[:3]] == ["Forest", "Lightning Bolt", "Dark Ritual"]
    assert game.confirm_look_top_pick(0, 2)
    _w1g10_settle(game)
    assert [card.name for card in alice.hand] == ["Hill Giant", "Dark Ritual"]
    assert [card.name for card in alice.library] == [
        "Island", "Grizzly Bears", "Forest", "Lightning Bolt",
    ]
    # Not a draw: nothing was drawn, so no draw trigger has anything to see.
    assert alice.cards_drawn_this_turn == drawn_before
    assert not any("Hill Giant" in line or "Dark Ritual" in line for line in game.log)


def test_w1g10_tomorrow_on_a_short_library_and_an_empty_one(set_pool):
    """Fewer than three cards: one is kept and the rest put back; no cards:
    nothing happens, and the player does not lose for drawing from an empty
    library while Tomorrow applies (2005-02-01) — the draw step's draw is
    replaced too."""
    game = _w1g10_tomorrow_game(set_pool, ["Grizzly Bears"])
    alice = game.players[0]
    assert [card.name for card in alice.hand] == []
    assert game._draw_with_replacements(alice, 1) == 0
    _w1g10_settle(game)
    assert [card.name for card in alice.hand] == ["Grizzly Bears"]
    assert alice.library == []
    assert game._draw_with_replacements(alice, 3) == 0
    _w1g10_settle(game)
    game.check_state_based_actions()
    assert not alice.lost and not game.is_game_over()
    assert any("has no card to look at instead of drawing" in line for line in game.log)


def test_w1g10_tomorrow_replaces_the_draw_step_draw(set_pool):
    """The draw step's draw (CR 504.1) is a draw like any other: a headless
    seat keeps a card of the top three, the rest go to the bottom."""
    game = _w1g10_tomorrow_game(set_pool, [
        "Grizzly Bears", "Hill Giant", "Island", "Forest",
    ])
    alice = game.players[0]
    hand_before, library_before = len(alice.hand), len(alice.library)
    game.turn = 3  # not the first turn's skipped draw (CR 103.8a)
    game.resolve_draw_step(0)
    _w1g10_settle(game)
    assert len(alice.hand) == hand_before + 1
    assert len(alice.library) == library_before - 1
    assert any("instead of drawing (Tomorrow, Azami's Familiar)" in line for line in game.log)


def _w1g10_toshiro_game(set_pool, *, graveyard=("Lightning Bolt",)):
    bok, lea = set_pool("BOK"), set_pool("LEA")
    return _w1g10_game(
        mine=[bok["Toshiro Umezawa"]], hand=[lea["Terror"]],
        graveyard=[lea[name] for name in graveyard],
        theirs=[lea["Grizzly Bears"], lea["Hill Giant"]], island=lea["Island"],
    )


def _w1g10_graveyard_slot(owed, name, game, seat=0):
    """The offered target slot naming the card *name* in *seat*'s graveyard."""
    pile = game.players[seat].graveyard
    return next(
        target["graveyard_index"] for target in owed.data["targets"]
        if target.get("kind") == "graveyard" and target.get("seat") == seat
        and pile[target["graveyard_index"]].name == name
    )


def test_w1g10_toshiro_casts_an_instant_from_the_graveyard_as_it_resolves(set_pool):
    """Toshiro Umezawa: "Whenever a creature an opponent controls dies, you may
    cast target instant card from your graveyard. If that spell would be put
    into a graveyard, exile it instead." Asked of a person. The Terror that
    killed the Bears is already in the graveyard when the trigger chooses its
    target (the 2011-01-01 ruling), beside the Lightning Bolt; Alice targets
    the Bolt. The cast is made during the trigger's resolution (CR 608.2g):
    the ability is still on the stack while the offer is owed, the Bolt goes
    above it, kills the Hill Giant and is exiled instead of going to the
    graveyard. The Giant's death triggers Toshiro again; Alice declines, and
    the Terror stays where it is."""
    game = _w1g10_toshiro_game(set_pool)
    alice, bob = game.players
    bears, giant = game.controlled_by(1)
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id]).supported
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "trigger_target"
    offered = sorted(alice.graveyard[t["graveyard_index"]].name for t in owed.data["targets"])
    assert offered == ["Lightning Bolt", "Terror"]
    assert game.confirm_trigger_target(
        0, seat=0, graveyard_index=_w1g10_graveyard_slot(owed, "Lightning Bolt", game),
    )
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "copy_cast" and owed.data["card_name"] == "Lightning Bolt"
    assert [item.card.name for item in game.stack] == ["Toshiro Umezawa"]
    assert game.confirm_copy_cast(0, True, target_permanent_ids=[giant.permanent_id])
    assert [item.card.name for item in game.stack][-1] == "Lightning Bolt"
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "trigger_target"
    assert [card.name for card in alice.exile] == ["Lightning Bolt"]
    assert [card.name for card in bob.graveyard] == ["Grizzly Bears", "Hill Giant"]
    assert game.confirm_trigger_target(
        0, seat=0, graveyard_index=_w1g10_graveyard_slot(owed, "Terror", game),
    )
    owed = _w1g10_settle(game, defaults=False)
    assert owed.kind == "copy_cast"
    assert game.confirm_copy_cast(0, False)
    _w1g10_settle(game)
    assert [card.name for card in alice.graveyard] == ["Terror"]
    assert game.stack == []


def test_w1g10_toshiros_cast_pays_the_mana_cost_and_is_not_kept_for_later(set_pool):
    """"You must still pay the mana cost" (2005-02-01): a headless seat with no
    untapped land cannot pay for the Bolt and casts nothing — and the offer is
    not a lasting permission (CR 608.2g): once the trigger has resolved, the
    Bolt cannot be cast from the graveyard later. With a Mountain untapped,
    the Bolt is cast, the Mountain paying for it."""
    lea = set_pool("LEA")
    game = _w1g10_toshiro_game(set_pool)
    alice = game.players[0]
    bears, giant = game.controlled_by(1)
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id]).supported
    game.enforce_mana_costs = True
    _w1g10_settle(game)
    assert "Lightning Bolt" in [card.name for card in alice.graveyard]
    assert game.is_on_battlefield(giant)
    assert not game.cast_from_hand(
        0, "Lightning Bolt", from_zone="graveyard", target_permanent_ids=[giant.permanent_id],
    ).supported
    game._put_permanent_onto_battlefield(0, _W1G10Permanent(card=lea["Mountain"]), None)
    game._sync_control()
    game.enforce_mana_costs = False
    alice.hand.append(lea["Terror"])
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[giant.permanent_id]).supported
    game.enforce_mana_costs = True
    _w1g10_settle(game)
    assert [card.name for card in alice.exile] == ["Lightning Bolt"]
    land = next(p for p in game.controlled_by(0) if p.card.name == "Mountain")
    assert land.tapped

# ==== end w1g10 ======================================================
