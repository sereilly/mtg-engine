"""Fifth Dawn sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
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
from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def test_w1g2_channel_the_suns_pays_a_bringers_wubrg(set_pool):
    """"Add {W}{U}{B}{R}{G}." Four Forests cast Channel the Suns, and the five
    mana it makes is exactly the alternative cost a Bringer prints — one cast
    payment for each, the Bringer's through the ordinary pool."""
    lea, fdn = set_pool("LEA"), set_pool("5DN")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            name="Alice", library=[lea["Island"]] * 8,
            hand=[fdn["Channel the Suns"], fdn["Bringer of the Green Dawn"]],
        ),
        _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = True
    for _ in range(4):
        forest = _W1G2Permanent(card=lea["Forest"])
        game._put_permanent_onto_battlefield(0, forest, None)
    game.start_turn(0)
    _w1g2_settle(game)
    for permanent in list(game.controlled_by(0)):
        assert game.tap_land_for_mana_or_refusal(
            0, "Forest", permanent_id=permanent.permanent_id,
        ) is None

    assert game.cast_from_hand(0, "Channel the Suns").supported
    assert {k: v for k, v in game.players[0].mana_pool.items() if v} == {
        "W": 1, "U": 1, "B": 1, "R": 1, "G": 1,
    }
    result = game.cast_from_hand(0, "Bringer of the Green Dawn", alternative_cost=True)

    assert result.supported, result.details
    _w1g2_settle(game)
    assert "Bringer of the Green Dawn" in [p.card.name for p in game.controlled_by(0)]
    assert not any(game.players[0].mana_pool.values())

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_cast_spec as _w1g3_derive_cast_spec
from tests.helpers import settle as _w1g3_settle


def _w1g3_table(set_pool, *, hand=(), graveyard=(), opponent_graveyard=(), interactive=()):
    """Two seats on seat 0's first main phase with ten-card libraries."""
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 10,
            hand=list(hand) if seat == 0 else [],
            graveyard=list(graveyard if seat == 0 else opponent_graveyard),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g3_settle(game)
    return game


def _w1g3_put(game, seat, card):
    permanent = _W1G3Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g3_settle(game)
    return permanent


def _w1g3_where(game, name):
    return [
        f"{seat}.{zone}"
        for seat, player in enumerate(game.players)
        for zone in ("hand", "library", "graveyard", "exile")
        for card in getattr(player, zone)
        if card.name == name
    ]


def _w1g3_cast_spec(card):
    return _w1g3_derive_cast_spec(card, _w1g3_compile(card))


def _w1g3_board(game, seat):
    return [p.card.name for p in game.controlled_by(seat)]


def test_w1g3_beacon_of_creation_counts_your_forests_and_shuffles_away(set_pool):
    """"Create a 1/1 green Insect creature token for each Forest you control.
    Shuffle Beacon of Creation into its owner's library." Three Forests of
    the caster's (not the opponent's one), three Insects, and the Beacon in
    the library."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(set_pool, hand=[fdn["Beacon of Creation"]])
    for _ in range(3):
        _w1g3_put(game, 0, lea["Forest"])
    _w1g3_put(game, 1, lea["Forest"])
    assert game.cast_from_hand(0, "Beacon of Creation").supported
    _w1g3_settle(game)

    insects = [p for p in game.controlled_by(0) if p.card.name == "Insect Token"]
    assert len(insects) == 3
    assert all((p.effective_power, p.effective_toughness) == (1, 1) for p in insects)
    assert _w1g3_where(game, "Beacon of Creation") == ["0.library"]
    assert len(game.players[0].library) == 11


def test_w1g3_beacon_of_creation_flashed_back_is_exiled_and_still_shuffles(set_pool):
    """CR 702.34a exiles a flashed-back spell "instead of putting it anywhere
    else", the library included — and CR 701.24c shuffles the library all the
    same (its own example: Black Sun's Zenith cast with flashback). Recoup
    grants the flashback; Psychogenic Probe hears the shuffle."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[set_pool("ODY")["Recoup"]], graveyard=[fdn["Beacon of Creation"]],
    )
    _w1g3_put(game, 0, lea["Forest"])
    _w1g3_put(game, 1, set_pool("MRD")["Psychogenic Probe"])
    assert game.cast_from_hand(
        0, "Recoup", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g3_settle(game)
    assert game.cast_from_hand(0, "Beacon of Creation", from_zone="graveyard").supported
    _w1g3_settle(game)

    assert _w1g3_board(game, 0).count("Insect Token") == 1
    assert _w1g3_where(game, "Beacon of Creation") == ["0.exile"]
    assert len(game.players[0].library) == 10
    assert game.players[0].life == 18, "the library was shuffled"


def test_w1g3_beacon_of_tomorrows_gives_the_target_player_the_extra_turn(set_pool):
    """"Target player takes an extra turn after this one." Any player — the
    picker offers both seats — and the seat named is the one owed the turn
    (Time Warp's handler, CR 500.7), the caster's own when it names itself."""
    fdn = set_pool("5DN")
    beacon = fdn["Beacon of Tomorrows"]
    spec = _w1g3_cast_spec(beacon)
    assert spec is not None and spec.get("kind") == "player", spec
    assert not spec.get("opponent_only")

    for seat in (1, 0):
        game = _w1g3_table(set_pool, hand=[beacon])
        assert game.cast_from_hand(
            0, "Beacon of Tomorrows", target_player_index=seat,
        ).supported
        _w1g3_settle(game)
        assert _w1g3_where(game, "Beacon of Tomorrows") == ["0.library"]
        assert game.extra_turns.get(seat, 0) == 1
        assert game.extra_turns.get(1 - seat, 0) == 0
        assert f"P{seat} gained an extra turn" in game.log


def test_w1g3_beacon_of_unrest_takes_an_artifact_from_an_opponents_graveyard(set_pool):
    """"Put target artifact or creature card from a graveyard onto the
    battlefield under your control." Any graveyard, either type: the
    opponent's Rod of Ruin comes over under the caster's control and stays
    the opponent's card (CR 108.3) — destroyed, it goes to their graveyard.
    The instant beside it is no legal target."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Unrest"], lea["Shatter"]],
        opponent_graveyard=[lea["Lightning Bolt"], lea["Rod of Ruin"]],
    )
    spec = _w1g3_cast_spec(fdn["Beacon of Unrest"])
    assert spec.get("card_types") == ["artifact", "creature"]
    assert not spec.get("own_graveyard_only")
    refused = game.cast_from_hand(
        0, "Beacon of Unrest", target_player_index=1, target_graveyard_indices=[0],
    )
    assert not refused.supported, "an instant card is not an artifact or creature card"

    assert game.cast_from_hand(
        0, "Beacon of Unrest", target_player_index=1, target_graveyard_indices=[1],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_board(game, 0) == ["Rod of Ruin"]
    assert _w1g3_where(game, "Beacon of Unrest") == ["0.library"]

    (rod,) = list(game.controlled_by(0))
    assert game.cast_from_hand(0, "Shatter", target_permanent_ids=[rod.permanent_id]).supported
    _w1g3_settle(game)
    assert _w1g3_where(game, "Rod of Ruin") == ["1.graveyard"]


def test_w1g3_beacon_of_unrest_returns_a_creature_from_your_own_graveyard(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Unrest"]],
        graveyard=[lea["Shivan Dragon"]],
    )
    assert game.cast_from_hand(
        0, "Beacon of Unrest", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_board(game, 0) == ["Shivan Dragon"]
    assert _w1g3_where(game, "Beacon of Unrest") == ["0.library"]


def test_w1g3_beacon_of_unrest_whose_card_left_is_not_shuffled(set_pool):
    """Ruling (2020-08-07): "If the target card is an illegal target by the
    time Beacon of Unrest tries to resolve, the spell won't resolve. You won't
    shuffle it into your library." The Rod of Ruin leaves the graveyard in
    response; the Beacon goes to its owner's graveyard and the library is
    untouched."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Unrest"]], opponent_graveyard=[lea["Rod of Ruin"]],
    )
    assert game.queue_from_hand(
        0, "Beacon of Unrest", target_player_index=1, target_graveyard_indices=[0],
    ).supported
    rod = game.players[1].graveyard.pop(0)
    game.put_card_into_exile(game.players[1], rod)
    _w1g3_settle(game)
    assert _w1g3_board(game, 0) == []
    assert _w1g3_where(game, "Beacon of Unrest") == ["0.graveyard"]
    assert len(game.players[0].library) == 10


def _w1g3_dawn_table(set_pool, graveyard, **kwargs):
    pool = {**set_pool("LEA"), **set_pool("INV"), **set_pool("PLS")}
    return _w1g3_table(
        set_pool, hand=[set_pool("5DN")["All Suns' Dawn"]],
        graveyard=[pool[name] for name in graveyard], **kwargs,
    )


def _w1g3_hand(game):
    return sorted(c.name for c in game.players[0].hand)


def test_w1g3_all_suns_dawn_returns_one_card_of_each_color_and_exiles_itself(set_pool):
    """"For each color, return up to one target card of that color from your
    graveyard to your hand. Exile All Suns' Dawn." Five targets, one per
    colour; the colourless Black Lotus and the second red card stay; the
    spell is exiled rather than put into the graveyard."""
    game = _w1g3_dawn_table(set_pool, [
        "Swords to Plowshares", "Counterspell", "Dark Ritual", "Shivan Dragon",
        "Lightning Bolt", "Giant Growth", "Black Lotus",
    ])
    spec = _w1g3_cast_spec(set_pool("5DN")["All Suns' Dawn"])
    assert spec["max_targets"] == 5 and spec["distinct_targets"]
    assert spec["one_target_per_color"] is True
    assert sorted(spec["graveyard_colors"]) == ["B", "G", "R", "U", "W"]

    assert game.cast_from_hand(
        0, "All Suns' Dawn", target_player_index=0,
        target_graveyard_indices=[0, 1, 2, 3, 5],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_hand(game) == [
        "Counterspell", "Dark Ritual", "Giant Growth", "Shivan Dragon",
        "Swords to Plowshares",
    ]
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Black Lotus", "Lightning Bolt",
    ]
    assert _w1g3_where(game, "All Suns' Dawn") == ["0.exile"]


def test_w1g3_all_suns_dawn_refuses_two_cards_of_one_color(set_pool):
    """Two red cards are not one red card and a card of another colour: the
    announcement is refused (CR 601.2c), and so are a colourless card and one
    card named twice (CR 115.3)."""
    game = _w1g3_dawn_table(set_pool, ["Shivan Dragon", "Lightning Bolt", "Black Lotus"])
    for slots in ([0, 1], [2], [0, 0]):
        refused = game.cast_from_hand(
            0, "All Suns' Dawn", target_player_index=0, target_graveyard_indices=slots,
        )
        assert not refused.supported, slots
    assert _w1g3_hand(game) == ["All Suns' Dawn"]


def test_w1g3_all_suns_dawn_takes_two_gold_cards_as_two_colors(set_pool):
    """Ruling (2004-12-01): "You can target two blue-and-white multicolored
    cards by choosing one as the blue card and one as the white card." — but
    two blue-and-white cards beside a white one and a blue one are four cards
    for two colours."""
    game = _w1g3_dawn_table(
        set_pool, ["Absorb", "Galina's Knight", "Swords to Plowshares", "Counterspell"],
    )
    assert not game.cast_from_hand(
        0, "All Suns' Dawn", target_player_index=0,
        target_graveyard_indices=[0, 1, 2, 3],
    ).supported
    assert game.cast_from_hand(
        0, "All Suns' Dawn", target_player_index=0, target_graveyard_indices=[0, 1],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_hand(game) == ["Absorb", "Galina's Knight"]


def test_w1g3_all_suns_dawn_with_no_targets_still_resolves_and_is_exiled(set_pool):
    """Zero targets is a legal announcement ("up to one" five times, the
    2004-12-01 ruling: "from zero to five targets"); a spell with no targets
    is not one whose targets all became illegal (CR 608.2b), so it resolves
    and exiles itself."""
    game = _w1g3_dawn_table(set_pool, ["Black Lotus"])
    assert game.cast_from_hand(0, "All Suns' Dawn", target_player_index=0).supported
    _w1g3_settle(game)
    assert _w1g3_where(game, "All Suns' Dawn") == ["0.exile"]
    assert [c.name for c in game.players[0].graveyard] == ["Black Lotus"]


def test_w1g3_all_suns_dawn_whose_targets_all_left_goes_to_the_graveyard(set_pool):
    """Every named card gone before it resolves, the spell does not resolve
    (CR 608.2b) and goes to its owner's graveyard — the exile sentence never
    runs."""
    game = _w1g3_dawn_table(set_pool, ["Shivan Dragon", "Counterspell"])
    assert game.queue_from_hand(
        0, "All Suns' Dawn", target_player_index=0, target_graveyard_indices=[0, 1],
    ).supported
    alice = game.players[0]
    for _ in range(2):
        game.put_card_into_exile(alice, alice.graveyard.pop(0))
    _w1g3_settle(game)
    assert _w1g3_where(game, "All Suns' Dawn") == ["0.graveyard"]
    assert _w1g3_hand(game) == []


def test_w1g3_all_suns_dawn_ai_names_one_card_of_each_color(set_pool):
    """The AI's several-target choice takes the best card of each colour it
    can fill — never the two red cards its ranking alone would put first."""
    from engine.ai_slot_targets import _choose_several_targets

    game = _w1g3_dawn_table(set_pool, [
        "Shivan Dragon", "Lightning Bolt", "Counterspell", "Black Lotus",
    ])
    seat, slots, _ids = _choose_several_targets(
        game, 0, set_pool("5DN")["All Suns' Dawn"],
    )
    named = sorted(game.players[0].graveyard[slot].name for slot in slots)
    assert seat == 0 and len(named) == 2, named
    assert "Counterspell" in named
    assert game.cast_from_hand(
        0, "All Suns' Dawn", target_player_index=seat, target_graveyard_indices=slots,
    ).supported

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
#
# Mana Geyser's count of the opponents' tapped lands; Vicious Betrayal's
# sacrifice as a cast cost; Rude Awakening's lands become creatures.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), mine=(), theirs=(), interactive=()):
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    placed = {0: [], 1: []}
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _W1G7Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    _w1g7_settle(game)
    return game, placed[0], placed[1]


def _w1g7_pool(player):
    return {symbol: n for symbol, n in player.mana_pool.items() if n}


def test_w1g7_mana_geyser_counts_only_the_opponents_tapped_lands(set_pool):
    """"Add {R} for each tapped land your opponents control." Three of the
    opponent's four lands are tapped and so is one of the caster's own: three
    {R}, the caster's tapped Mountain and the opponent's untapped Plains
    counted for nothing."""
    lea = set_pool("LEA")
    game, mine, theirs = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Mana Geyser"]],
        mine=[lea["Mountain"], lea["Mountain"]],
        theirs=[lea["Forest"], lea["Forest"], lea["Island"], lea["Plains"]],
    )
    mine[0].tapped = True
    for land in theirs[:3]:
        land.tapped = True

    result = game.cast_from_hand(0, "Mana Geyser")
    assert result.supported, result
    _w1g7_settle(game)

    assert _w1g7_pool(game.players[0]) == {"R": 3}
    assert _w1g7_pool(game.players[1]) == {}
    assert "Mana Geyser produced {R}{R}{R}" in game.log


def test_w1g7_mana_geyser_with_no_tapped_opposing_land_adds_nothing(set_pool):
    lea = set_pool("LEA")
    game, mine, _ = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Mana Geyser"]],
        mine=[lea["Mountain"]], theirs=[lea["Forest"]],
    )
    mine[0].tapped = True

    game.cast_from_hand(0, "Mana Geyser")
    _w1g7_settle(game)

    assert _w1g7_pool(game.players[0]) == {}


def test_w1g7_vicious_betrayal_counts_the_creatures_its_cost_sacrificed(set_pool):
    """"As an additional cost to cast this spell, sacrifice any number of
    creatures. Target creature gets +2/+2 until end of turn for each creature
    sacrificed this way." Three named creatures go as the cost is paid
    (CR 601.2h) and the Giant gets +6/+6; the picker asks for a set of any
    size (``any_number``)."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    betrayal = set_pool("5DN")["Vicious Betrayal"]
    spec = derive_cast_spec(betrayal, compile_card_oracle(betrayal))
    assert spec["cost_spec"] == {
        "kind": "creature", "own_only": True, "sacrifice_cost": True,
        "any_number": True,
    }
    lea = set_pool("LEA")
    game, (bear, other_bear, giant, elves), _ = _w1g7_table(
        set_pool, hand=[betrayal],
        mine=[lea["Grizzly Bears"], lea["Grizzly Bears"], lea["Hill Giant"],
              lea["Llanowar Elves"]],
    )

    result = game.cast_from_hand(
        0, "Vicious Betrayal", target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[bear.permanent_id, other_bear.permanent_id,
                            elves.permanent_id],
    )
    assert result.supported, result
    _w1g7_settle(game)

    assert [p.card.name for p in game.players[0].battlefield] == ["Hill Giant"]
    assert (giant.effective_power, giant.effective_toughness) == (9, 9)
    assert "Vicious Betrayal gives Hill Giant +6/+6 until end of turn" in game.log


def test_w1g7_vicious_betrayal_with_its_target_sacrificed_does_nothing(set_pool):
    """CR 601.2c chooses the target before CR 601.2h pays the cost, so the
    target may be among the creatures sacrificed — then its only target is
    gone and the spell is removed as it would resolve (CR 608.2b)."""
    lea = set_pool("LEA")
    game, (bear, giant), _ = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Vicious Betrayal"]],
        mine=[lea["Grizzly Bears"], lea["Hill Giant"]],
    )

    game.cast_from_hand(
        0, "Vicious Betrayal", target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[bear.permanent_id, giant.permanent_id],
    )
    _w1g7_settle(game)

    assert game.players[0].battlefield == []
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Grizzly Bears", "Hill Giant", "Vicious Betrayal",
    ]
    assert any("every target is illegal" in line for line in game.log)


def test_w1g7_vicious_betrayal_sacrifices_only_what_was_named(set_pool):
    """None is a number: a cast naming nobody sacrifices nothing and pumps
    +0/+0 (no default pick eats a board for a cost of zero), and a creature
    the caster does not control cannot pay — the cast is refused with
    nothing spent (CR 601.2h)."""
    lea = set_pool("LEA")
    game, (bear, giant), (theirs,) = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Vicious Betrayal"]],
        mine=[lea["Grizzly Bears"], lea["Hill Giant"]],
        theirs=[lea["Grizzly Bears"]],
    )

    refused = game.cast_from_hand(
        0, "Vicious Betrayal", target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[theirs.permanent_id],
    )
    assert not refused.supported
    assert theirs in game.players[1].battlefield

    game.cast_from_hand(
        0, "Vicious Betrayal", target_permanent_ids=[giant.permanent_id],
    )
    _w1g7_settle(game)

    assert bear in game.players[0].battlefield
    assert giant.effective_power == 3
    assert "P0 sacrificed no permanents to cast Vicious Betrayal" in game.log


def test_w1g7_rude_awakening_entwined_untaps_and_animates_your_lands(set_pool):
    """Entwine {2}{G}: "Untap all lands you control" and then "Until end of
    turn, lands you control become 2/2 creatures that are still lands." The
    caster's lands untap and become 2/2 land creatures (layers 4 and 7b); the
    opponent's do not. A land that came under its controller's control this
    turn cannot attack (CR 302.6; the 2008-08-01 ruling), the others can; a
    land played after the spell resolved is not animated (the 2013-06-07
    ruling)."""
    lea = set_pool("LEA")
    game, mine, (island,) = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Rude Awakening"], lea["Forest"]],
        mine=[lea["Forest"], lea["Forest"], lea["Mountain"]],
        theirs=[lea["Island"]],
    )
    for land in mine:
        land.tapped = True
    fresh = _W1G7Permanent(card=lea["Forest"])
    game._put_permanent_onto_battlefield(0, fresh, None)
    _w1g7_settle(game)

    result = game.cast_from_hand(
        0, "Rude Awakening", optional_cost_payments={"{2}{G}": 1},
    )
    assert result.supported, result
    _w1g7_settle(game)

    for land in (*mine, fresh):
        assert not land.tapped
        assert land.is_creature and land.has_type("land")
        assert (land.effective_power, land.effective_toughness) == (2, 2)
    assert not island.is_creature

    played = game.cast_from_hand(0, "Forest")
    assert played.supported, played
    newcomer = game.players[0].battlefield[-1]
    assert newcomer.card.name == "Forest" and not newcomer.is_creature

    game._set_phase_and_step("combat", "declare_attackers")
    slots = {id(p): slot for slot, p in enumerate(game.players[0].battlefield)}
    refused, _why = game.declare_attackers(0, [slots[id(fresh)]], defending_player_index=1)
    assert not refused
    ok, why = game.declare_attackers(
        0, [slots[id(land)] for land in mine], defending_player_index=1,
    )
    assert ok, why


def test_w1g7_rude_awakening_animation_ends_at_cleanup(set_pool):
    """The second mode alone: until end of turn, so at the cleanup step the
    lands are lands again and nothing else (CR 514.2)."""
    lea = set_pool("LEA")
    game, (forest,), _ = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Rude Awakening"]], mine=[lea["Forest"]],
    )

    game.cast_from_hand(0, "Rude Awakening", mode_index=1)
    _w1g7_settle(game)
    assert forest.is_creature

    game.resolve_cleanup_step(0)
    assert not forest.is_creature and forest.has_type("land")

# ==== end w1g7 ======================================================
