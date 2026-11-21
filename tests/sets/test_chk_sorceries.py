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
#
# Devouring Greed's variable sacrifice, and sorcery hosts for splice onto
# Arcane (CR 702.47, ``engine/splice.py``): an X spell and an "up to three"
# spell carry gained text as well as an instant does.

from engine import Game as _w1g5_Game, PlayerState as _w1g5_PlayerState
from engine.models import Permanent as _w1g5_Permanent
from tests.helpers import settle as _w1g5_settle

_W1G5_SETS = ("CHK", "LEA")


def _w1g5_card(set_pool, name):
    for code in _W1G5_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g5_table(set_pool, *, hand=(), mine=(), theirs=()):
    """A two-seat game on seat 0's first main phase, costs off, settled."""
    island = _w1g5_card(set_pool, "Island")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState("A", hand=[_w1g5_card(set_pool, n) for n in hand],
                          library=[island] * 10),
        _w1g5_PlayerState("B", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g5_Permanent(card=_w1g5_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g5_settle(game)
    return game, placed[0], placed[1]


def test_w1g5_devouring_greed_drains_two_plus_two_per_spirit_sacrificed(set_pool):
    """'Target player loses 2 life plus 2 life for each Spirit sacrificed
    this way. You gain that much life.'"""
    for sacrificed, drained in ((2, 6), (0, 2)):
        game, spirits, _theirs = _w1g5_table(
            set_pool, hand=["Devouring Greed"], mine=["Kami of Ancient Law", "Lantern Kami"],
        )
        result = game.cast_from_hand(
            0, "Devouring Greed", target_player_index=1,
            cost_permanent_ids=[s.permanent_id for s in spirits[:sacrificed]],
            optional_cost_payments={"sacrifice any number of spirits": 1},
        )
        assert result.supported, result.details
        _w1g5_settle(game)
        assert game.players[1].life == 20 - drained, sacrificed
        assert game.players[0].life == 20 + drained, sacrificed
        assert len(game.players[0].battlefield) == 2 - sacrificed


def test_w1g5_splice_onto_an_x_sorcery_keeps_the_hosts_x(set_pool):
    """Swallowing Plague at X=2 with Glacial Ray spliced: the host's own X
    for its own text, the gained text's 2 for the gained target."""
    game, _mine, (giant, bears) = _w1g5_table(
        set_pool, hand=["Swallowing Plague", "Glacial Ray"], theirs=["Hill Giant", "Grizzly Bears"],
    )
    result = game.cast_from_hand(
        0, "Swallowing Plague", target_permanent_ids=[giant.permanent_id], x_value=2,
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [bears.permanent_id]}],
    )
    assert result.supported, result.details
    _w1g5_settle(game)
    assert giant.damage_marked == 2 and game.players[0].life == 22
    assert not game.is_on_battlefield(bears)


def test_w1g5_splice_onto_an_up_to_three_sorcery(set_pool):
    """Terashi's Cry taps up to three creatures; Kodama's Might spliced onto it
    pumps a creature of its own, its own target."""
    game, (bears,), theirs = _w1g5_table(
        set_pool, hand=["Terashi's Cry", "Kodama's Might"], mine=["Grizzly Bears"],
        theirs=["Hill Giant", "Llanowar Elves"],
    )
    result = game.cast_from_hand(
        0, "Terashi's Cry", target_permanent_ids=[p.permanent_id for p in theirs],
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [bears.permanent_id]}],
    )
    assert result.supported, result.details
    _w1g5_settle(game)
    assert all(p.tapped for p in theirs)
    assert bears.effective_power == 4 and not bears.tapped

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), library=None, opponent_library=None,
                opponent_hand=(), opponent_graveyard=(), mine=(), theirs=(),
                interactive=()):
    """Two seats on seat 0's first main phase, costs off; libraries top
    first. Names resolve in CHK first, then the older sets the tests use."""
    pools = [set_pool(code) for code in ("CHK", "LEA", "MRD", "TMP")]

    def named(name):
        for pool in pools:
            if name in pool:
                return pool[name]
        raise KeyError(name)

    game = _W1G7Game(players=[
        _W1G7PlayerState(
            "P0", hand=[named(n) for n in hand],
            library=[named(n) for n in (library or ["Forest"] * 10)],
        ),
        _W1G7PlayerState(
            "P1", hand=[named(n) for n in opponent_hand],
            library=[named(n) for n in (opponent_library or ["Island"] * 10)],
            graveyard=[named(n) for n in opponent_graveyard],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G7Permanent(card=named(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_names(cards):
    return [card.name for card in cards]


_W1G7_LOOKED = [
    "Forest", "Grizzly Bears", "Lightning Bolt", "Dark Ritual", "Craw Wurm",
    "Island", "Swamp",
]


def test_w1g7_commune_with_nature_takes_a_creature_and_bottoms_the_rest(set_pool):
    game = _w1g7_table(
        set_pool, hand=["Commune with Nature"], library=_W1G7_LOOKED,
        interactive={0},
    )
    assert game.cast_from_hand(0, "Commune with Nature").supported
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "look_top_pick" and asked.data["top_count"] == 5
    # Only the creature cards among the five are offered.
    offered = game.live_look_top_candidates(asked)
    assert [game.players[0].library[i].name for i in offered] == [
        "Grizzly Bears", "Craw Wurm",
    ]
    # A noncreature card is refused.
    assert not game.confirm_look_top_pick(0, 2)
    assert game.confirm_look_top_pick(0, 4)
    # "in any order": the looker is asked to arrange the bottom.
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "reorder_library" and asked.data["position"] == "bottom"
    assert asked.data["top_count"] == 4
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].hand) == ["Craw Wurm"]
    library = _w1g7_names(game.players[0].library)
    assert library[:2] == ["Island", "Swamp"]
    assert sorted(library[2:]) == sorted(
        ["Forest", "Grizzly Bears", "Lightning Bolt", "Dark Ritual"]
    )


def test_w1g7_commune_with_nature_may_take_nothing(set_pool):
    """Its ruling (2004-12-01): no creature revealed, all five go to the
    bottom."""
    game = _w1g7_table(
        set_pool, hand=["Commune with Nature"],
        library=["Forest", "Island", "Lightning Bolt", "Swamp", "Mountain",
                 "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Commune with Nature").supported
    _w1g7_settle(game)
    assert game.players[0].hand == []
    library = _w1g7_names(game.players[0].library)
    assert library[0] == "Grizzly Bears" and len(library) == 6


def _w1g7_petals(set_pool, accept):
    game = _w1g7_table(
        set_pool, hand=["Petals of Insight"],
        library=["Forest", "Grizzly Bears", "Lightning Bolt", "Island", "Swamp"],
        interactive={0},
    )
    assert game.cast_from_hand(0, "Petals of Insight").supported
    asked = _w1g7_settle(game, defaults=False)
    # The offer is made having seen the three cards (CR 701.20e: a look, the
    # private half of a reveal).
    assert asked.kind == "optional_pay"
    assert asked.data["looked_at"] == ["Forest", "Grizzly Bears", "Lightning Bolt"]
    _w1g7_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=accept),
    })
    return game


def test_w1g7_petals_of_insight_bottoms_the_three_and_returns_to_hand(set_pool):
    game = _w1g7_petals(set_pool, accept=True)
    player = game.players[0]
    # Its ruling (2013-06-07): it returns to the hand straight from the stack.
    assert _w1g7_names(player.hand) == ["Petals of Insight"]
    assert player.graveyard == []
    assert _w1g7_names(player.library)[:2] == ["Island", "Swamp"]
    assert sorted(_w1g7_names(player.library)[2:]) == sorted(
        ["Forest", "Grizzly Bears", "Lightning Bolt"]
    )


def _w1g7_extraction(set_pool, interactive=()):
    game = _w1g7_table(
        set_pool, hand=["Cranial Extraction"], interactive=interactive,
        opponent_hand=["Lightning Bolt", "Grizzly Bears", "Lightning Bolt"],
        opponent_library=["Island", "Lightning Bolt", "Swamp", "Lightning Bolt", "Craw Wurm"],
        opponent_graveyard=["Lightning Bolt", "Forest"],
    )
    assert game.cast_from_hand(0, "Cranial Extraction", target_player_index=1).supported
    return game


def test_w1g7_cranial_extraction_exiles_every_copy_of_the_named_card(set_pool):
    game = _w1g7_extraction(set_pool, interactive={0})
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "choose_card_name"
    # "a nonland card name": a land's name is refused.
    assert not game.confirm_choose_card_name(0, "Island")
    _w1g7_settle(game, answers={
        "choose_card_name": lambda g, c: g.confirm_choose_card_name(0, "Lightning Bolt"),
    })
    victim = game.players[1]
    assert _w1g7_names(victim.exile) == ["Lightning Bolt"] * 5
    assert _w1g7_names(victim.hand) == ["Grizzly Bears"]
    assert _w1g7_names(victim.graveyard) == ["Forest"]
    assert sorted(_w1g7_names(victim.library)) == ["Craw Wurm", "Island", "Swamp"]
    assert game.players[0].exile == []


def test_w1g7_cranial_extraction_at_a_seat_nobody_asks_names_from_public_evidence(set_pool):
    """The default names what the target's graveyard shows (CR 400.2), and
    the strip finds the hidden copies too."""
    game = _w1g7_extraction(set_pool)
    _w1g7_settle(game)
    assert _w1g7_names(game.players[1].exile) == ["Lightning Bolt"] * 5


def _w1g7_mindblaze(set_pool, name, number):
    game = _w1g7_table(
        set_pool, hand=["Mindblaze"], interactive={0},
        opponent_library=["Lightning Bolt", "Island", "Lightning Bolt", "Swamp",
                          "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Mindblaze", target_player_index=1).supported

    def pick_number(g, c):
        # "a number greater than 0": zero is refused.
        assert not g.confirm_number_choice(0, 0)
        assert g.confirm_number_choice(0, number)

    _w1g7_settle(game, answers={
        "choose_card_name": lambda g, c: g.confirm_choose_card_name(0, name),
        "number_choice": pick_number,
    })
    return game


def test_w1g7_mindblaze_deals_8_when_the_count_is_exact(set_pool):
    game = _w1g7_mindblaze(set_pool, "Lightning Bolt", 2)
    assert game.players[1].life == 12
    assert any("reveals their library (5 card(s))" in line for line in game.log)
    assert any("shuffled their library" in line for line in game.log)
    assert sorted(_w1g7_names(game.players[1].library)) == [
        "Grizzly Bears", "Island", "Lightning Bolt", "Lightning Bolt", "Swamp",
    ]


def test_w1g7_mindblaze_misses_on_any_other_count(set_pool):
    assert _w1g7_mindblaze(set_pool, "Lightning Bolt", 1).players[1].life == 20
    assert _w1g7_mindblaze(set_pool, "Lightning Bolt", 3).players[1].life == 20
    assert _w1g7_mindblaze(set_pool, "Craw Wurm", 1).players[1].life == 20


def test_w1g7_mindblaze_refuses_a_land_name(set_pool):
    game = _w1g7_table(set_pool, hand=["Mindblaze"], interactive={0})
    assert game.cast_from_hand(0, "Mindblaze", target_player_index=1).supported
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "choose_card_name"
    assert not game.confirm_choose_card_name(0, "Island")


def test_w1g7_petals_of_insight_otherwise_draws_three(set_pool):
    game = _w1g7_petals(set_pool, accept=False)
    player = game.players[0]
    assert _w1g7_names(player.hand) == ["Forest", "Grizzly Bears", "Lightning Bolt"]
    assert _w1g7_names(player.graveyard) == ["Petals of Insight"]
    assert _w1g7_names(player.library) == ["Island", "Swamp"]

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (
    _game as _w1g8_game,
    _nosick as _w1g8_nosick,
    settle as _w1g8_settle,
    stock_libraries as _w1g8_stock_libraries,
)


def _w1g8_table(mine=(), theirs=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's precombat main phase of turn 2, the permanents
    placed through the entry funnel, libraries stocked."""
    game = _w1g8_game(
        _w1g8_PlayerState(name="P1", hand=list(hand), life=20),
        _w1g8_PlayerState(name="P2", hand=list(opponent_hand), life=20),
    )
    _w1g8_stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        row = []
        for card in cards:
            permanent = _w1g8_Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_w1g8_nosick(permanent))
        placed.append(row)
    game._sync_control()
    _w1g8_settle(game)
    return game, placed[0], placed[1]


def _w1g8_zone_names(game, seat, zone):
    return [card.name for card in getattr(game.players[seat], zone)]


# --- Yamabushi's Storm --------------------------------------------------------
# "Yamabushi's Storm deals 1 damage to each creature. If a creature dealt
# damage this way would die this turn, exile it instead." The sweep stamps
# the replacement on each creature it actually dealt to (CR 615.1a).


def test_w1g8_yamabushis_storm_exiles_every_creature_it_kills(set_pool):
    storm = set_pool("CHK")["Yamabushi's Storm"]
    elves = set_pool("LEA")["Llanowar Elves"]
    giant = set_pool("LEA")["Hill Giant"]
    game, _, (_, hill) = _w1g8_table([elves], [elves, giant], hand=[storm])
    cast = game.cast_from_hand(0, "Yamabushi's Storm")
    assert cast.supported, cast.details
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 0, "exile") == ["Llanowar Elves"]
    assert _w1g8_zone_names(game, 1, "exile") == ["Llanowar Elves"]
    assert _w1g8_zone_names(game, 0, "graveyard") == ["Yamabushi's Storm"]
    assert _w1g8_zone_names(game, 1, "graveyard") == []
    assert game.is_on_battlefield(hill) and hill.damage_marked == 1


def test_w1g8_yamabushis_storm_spares_what_it_dealt_no_damage_to(set_pool):
    """Protection from red prevents the Storm's damage to the Blacksmith
    (CR 702.16e), so it was not dealt damage this way: destroyed later that
    turn it dies as usual, while the Hill Giant the Storm did damage is
    exiled by the same Terror's twin."""
    storm = set_pool("CHK")["Yamabushi's Storm"]
    blacksmith = set_pool("ARN")["Repentant Blacksmith"]
    giant = set_pool("LEA")["Hill Giant"]
    terror = set_pool("LEA")["Terror"]
    game, _, (smith, hill) = _w1g8_table(
        [], [blacksmith, giant], hand=[storm, terror, terror]
    )
    assert game.cast_from_hand(0, "Yamabushi's Storm").supported
    _w1g8_settle(game)
    assert smith.damage_marked == 0 and hill.damage_marked == 1
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[smith.permanent_id]).supported
    _w1g8_settle(game)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[hill.permanent_id]).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "graveyard") == ["Repentant Blacksmith"]
    assert _w1g8_zone_names(game, 1, "exile") == ["Hill Giant"]



# --- Reverse the Sands --------------------------------------------------------
# "Redistribute any number of players' life totals." CR 119.7's
# redistribution; the rulings (2004-12-01): a life total is never split, and
# the caster chooses which player gets which as the spell resolves.


def test_w1g8_reverse_the_sands_hands_its_caster_the_higher_total(set_pool):
    sands = set_pool("CHK")["Reverse the Sands"]
    game, _, _ = _w1g8_table([], [], hand=[sands])
    game.players[0].life, game.players[1].life = 5, 15
    cast = game.cast_from_hand(0, "Reverse the Sands")
    assert cast.supported, cast.details
    _w1g8_settle(game)
    assert [p.life for p in game.players] == [15, 5]


def test_w1g8_reverse_the_sands_asks_its_caster_who_gets_each_total(set_pool):
    """An asked caster may leave the totals where they are — "any number of
    players" includes none — answering the ``player_choice`` prompt."""
    sands = set_pool("CHK")["Reverse the Sands"]
    game, _, _ = _w1g8_table([], [], hand=[sands])
    game.interactive_seats = {0}
    game.players[0].life, game.players[1].life = 5, 15
    assert game.queue_from_hand(0, "Reverse the Sands").supported
    owed = _w1g8_settle(game, defaults=False)
    assert owed is not None and owed.kind == "player_choice"
    assert "5 life" in owed.data["prompt"]
    assert sorted(owed.data["seats"]) == [0, 1]
    assert game.confirm_player_choice(0, 0)
    _w1g8_settle(game)
    assert [p.life for p in game.players] == [5, 15]


def test_w1g8_reverse_the_sands_at_a_table_of_three(set_pool):
    """Each total goes to one player; the caster's default takes the highest
    and hands the lowest to the opponent most ahead."""
    sands = set_pool("CHK")["Reverse the Sands"]
    game, _, _ = _w1g8_table([], [], hand=[sands])
    game.players.append(_w1g8_PlayerState(name="P3", life=20))
    _w1g8_stock_libraries(game)
    game.players[0].life, game.players[1].life, game.players[2].life = 3, 12, 30
    assert game.cast_from_hand(0, "Reverse the Sands").supported
    _w1g8_settle(game)
    lives = [p.life for p in game.players]
    assert sorted(lives) == [3, 12, 30]
    assert lives[0] == 30 and lives[2] == 3


def test_w1g8_reverse_the_sands_hands_no_higher_total_to_a_player_who_cant_gain(set_pool):
    """CR 119.7: under "Players can't gain life" no player may receive a
    higher total, so the only redistribution left is none."""
    sands = set_pool("CHK")["Reverse the Sands"]
    wastes = set_pool("MIR")["Forsaken Wastes"]
    game, _, _ = _w1g8_table([wastes], [], hand=[sands])
    game.players[0].life, game.players[1].life = 5, 15
    assert game.cast_from_hand(0, "Reverse the Sands").supported
    _w1g8_settle(game)
    assert [p.life for p in game.players] == [5, 15]

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
