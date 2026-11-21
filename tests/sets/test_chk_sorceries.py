"""Champions of Kamigawa sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
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
#
# Glimpse of Nature: "Whenever you cast a creature spell this turn, draw a
# card." — a delayed triggered ability the resolution creates, lasting the
# turn (CR 603.7b), read by the delayed-cast table's second spelling.
from engine import Game as _W1G4Game
from engine.models import PlayerState as _W1G4PlayerState
from tests.helpers import settle as _w1g4_settle


def _w1g4_glimpsed(set_pool, *, hand=(), opponent_hand=()):
    """Alice's first main phase with Glimpse of Nature resolved."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=[chk["Glimpse of Nature"], *hand],
                         library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g4_settle(game)
    assert game.queue_from_hand(0, "Glimpse of Nature").supported
    _w1g4_settle(game)
    return game


def test_w1g4_glimpse_of_nature_draws_for_each_creature_spell_this_turn(set_pool):
    """Two creature spells, two cards — and each draw resolves above the
    spell that triggered it (the 2026-03-20 ruling)."""
    lea = set_pool("LEA")
    game = _w1g4_glimpsed(set_pool, hand=[lea["Grizzly Bears"], lea["Hill Giant"]])
    library = len(game.players[0].library)
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert [item.card.name for item in game.stack] == ["Grizzly Bears", "Glimpse of Nature"]
    game.resolve_top_of_stack()
    assert len(game.players[0].library) == library - 1
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]
    _w1g4_settle(game)
    assert game.queue_from_hand(0, "Hill Giant").supported
    _w1g4_settle(game)
    assert len(game.players[0].library) == library - 2, game.log


def test_w1g4_glimpse_of_nature_draws_even_when_the_creature_is_countered(set_pool):
    """The 2026-03-20 ruling: the draw "resolves even if that spell is
    countered" — Bob's Counterspell, cast above the trigger, still leaves
    Alice her card."""
    lea = set_pool("LEA")
    game = _w1g4_glimpsed(
        set_pool, hand=[lea["Grizzly Bears"]], opponent_hand=[lea["Counterspell"]],
    )
    library = len(game.players[0].library)
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    # ``target_stack_index`` indexes the stack bottom-first: 0 is the Bears.
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g4_settle(game)
    assert "Grizzly Bears" in [card.name for card in game.players[0].graveyard], game.log
    assert len(game.players[0].library) == library - 1


def test_w1g4_glimpse_of_nature_ignores_other_spells_and_other_turns(set_pool):
    """A noncreature spell draws nothing, an opponent's creature spell draws
    nothing ("you cast"), and the trigger is gone by the next turn."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_glimpsed(
        set_pool, hand=[chk["Counsel of the Soratami"], lea["Grizzly Bears"]],
        opponent_hand=[lea["Grizzly Bears"]],
    )
    library = len(game.players[0].library)
    assert game.queue_from_hand(0, "Counsel of the Soratami").supported
    _w1g4_settle(game)
    assert len(game.players[0].library) == library - 2, game.log    # Counsel's own two
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g4_settle(game)
    assert len(game.players[0].library) == library - 2
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    game.start_turn(0)
    _w1g4_settle(game)
    library = len(game.players[0].library)
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g4_settle(game)
    assert len(game.players[0].library) == library, game.log


def test_w1g4_cut_the_tethers_bounces_each_spirit_whose_controller_does_not_pay(set_pool):
    """"For each Spirit, return it to its owner's hand unless that player
    pays {3}." — the drive list's mis-player: the bare "it" in the loop's body
    lowered as the spell's own source, so the sorcery went back to its
    caster's hand and every Spirit stayed. Bob (asked) pays {3} for one Spirit
    and has nothing left for the other; Alice (unasked, no mana) cannot pay for
    hers; the Bears is no Spirit; and the sorcery ends in the graveyard."""
    from engine.models import Permanent

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=[chk["Cut the Tethers"]],
                         library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}

    def put(seat, card):
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, permanent, None)
        game._sync_control()
        return permanent

    kami = put(0, chk["Kami of the Hunt"])
    soilshaper = put(1, chk["Soilshaper"])
    bears = put(1, lea["Grizzly Bears"])
    kumo = put(1, chk["Orbweaver Kumo"])
    game.start_turn(0)
    _w1g4_settle(game)
    game.players[1].mana_pool.update({"C": 3})
    assert game.queue_from_hand(0, "Cut the Tethers").supported
    offers = []

    def pay_once(game, choice):
        offers.append(choice.player_index)
        assert game.confirm_optional_pay(choice.player_index, accept=len(offers) == 1)

    _w1g4_settle(game, answers={"optional_pay": pay_once})
    assert offers == [1], game.log
    assert {p.card.name for p in game.all_permanents()} == {"Soilshaper", "Grizzly Bears"}
    assert game.is_on_battlefield(soilshaper) and game.is_on_battlefield(bears)
    assert not game.is_on_battlefield(kami) and not game.is_on_battlefield(kumo)
    assert [c.name for c in game.players[0].hand] == ["Kami of the Hunt"]
    assert [c.name for c in game.players[1].hand] == ["Orbweaver Kumo"]
    assert [c.name for c in game.players[0].graveyard] == ["Cut the Tethers"]

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

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, hand=(), mine=(), theirs=(), interactive=(), mana=True):
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card("Island")] * 12),
        _W1G9PlayerState(name="Bob", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G9Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed[0], placed[1]


def _w1g9_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g9_mana_seism_adds_a_colourless_mana_for_each_land_sacrificed(set_pool):
    """"Sacrifice any number of lands, then add that much {C}." The seat
    chooses how many as the sorcery resolves (the prompt waits, CR 608.2);
    three lands sacrificed are {C}{C}{C}, and a seat nobody asks sacrifices
    none and adds none."""
    game, mine, _theirs = _w1g9_table(
        set_pool, hand=["Mana Seism"],
        mine=["Mountain", "Mountain", "Forest", "Forest"], interactive=(0,),
    )
    alice = game.players[0]
    for mountain in mine[:2]:
        assert game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert game.cast_from_hand(0, "Mana Seism").supported
    _w1g9_settle(game, defaults=False)
    [prompt] = game.pending_choices
    assert (prompt.kind, prompt.player_index) == ("sacrifice", 0)
    assert game.confirm_sacrifice(
        0, permanent_ids=[mine[0].permanent_id, mine[2].permanent_id, mine[3].permanent_id],
    )
    _w1g9_settle(game)
    assert _w1g9_names(game, 0) == ["Mountain"]
    assert alice.mana_pool["C"] == 3

    game, mine, _theirs = _w1g9_table(
        set_pool, hand=["Mana Seism"], mine=["Mountain", "Mountain"],
    )
    for mountain in mine:
        assert game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert game.cast_from_hand(0, "Mana Seism").supported
    _w1g9_settle(game)
    assert _w1g9_names(game, 0) == ["Mountain", "Mountain"]
    assert game.players[0].mana_pool["C"] == 0


def test_w1g9_feast_of_worms_takes_a_second_land_only_for_a_legendary_one(set_pool):
    """"Destroy target land. If that land was legendary, its controller
    sacrifices another land of their choice." Asked of the land as it last
    was (CR 608.2h), and the sacrifice is its controller's — chosen by Bob
    when Bob is asked. An ordinary land costs Bob only itself."""
    game, _mine, theirs = _w1g9_table(
        set_pool, hand=["Feast of Worms"],
        theirs=["Shizo, Death's Storehouse", "Island", "Swamp"],
        interactive=(1,), mana=False,
    )
    assert game.cast_from_hand(
        0, "Feast of Worms", target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g9_settle(game, defaults=False)
    [prompt] = game.pending_choices
    assert (prompt.kind, prompt.player_index) == ("sacrifice", 1)
    assert game.confirm_sacrifice(1, permanent_ids=[theirs[2].permanent_id])
    _w1g9_settle(game)
    assert _w1g9_names(game, 1) == ["Island"]
    assert sorted(c.name for c in game.players[1].graveyard) == [
        "Shizo, Death's Storehouse", "Swamp",
    ]
    assert _w1g9_names(game, 0) == []

    game, _mine, theirs = _w1g9_table(
        set_pool, hand=["Feast of Worms"],
        theirs=["Shizo, Death's Storehouse", "Island", "Swamp"], mana=False,
    )
    assert game.cast_from_hand(
        0, "Feast of Worms", target_permanent_ids=[theirs[1].permanent_id],
    ).supported
    _w1g9_settle(game)
    assert _w1g9_names(game, 1) == ["Shizo, Death's Storehouse", "Swamp"]

# ==== end w1g9 ======================================================
