"""Planeshift creatures, the later groups.

Split from `test_pls_creatures.py` at a group boundary when the wave's blocks
summed past the per-set file cap at integration (tests/sets/README.md: past
the printed-type axis the next division is a round boundary, and a group's
block is this wave's round). Everything here follows that file's block
convention - one delimited block per group, each with its own imports at the
top of the block - which is what let the blocks move whole. A later group
appends its block to whichever of the two files has room.
"""


# --- W1G4: domain ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import resolve_stack as _w1g4_resolve

_W1G4_FIVE = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _w1g4_find(set_pool, name):
    """*name* out of Planeshift, else Alpha (the lands and bodies), else The
    Dark (Blood Moon) — pools kept separate, asked in that order."""
    for w1g4_code in ("PLS", "LEA", "DRK"):
        w1g4_pool = set_pool(w1g4_code)
        if name in w1g4_pool:
            return w1g4_pool[name]
    raise KeyError(name)  # _w1g4_find


def _w1g4_table(set_pool, hand=(), mine=(), theirs=(), enforce=True):
    """A two-seat table on seat 0's turn with costs enforced: what these cards
    change is a price, so nothing here is free."""
    w1g4_game = _W1G4Game(players=[
        _W1G4PlayerState(name="W1G4-A", hand=[_w1g4_find(set_pool, n) for n in hand]),
        _W1G4PlayerState(name="W1G4-B"),
    ])
    w1g4_game.enforce_mana_costs = enforce
    w1g4_game.active_player_index = 0
    w1g4_rows = []
    for w1g4_seat, w1g4_names in enumerate((mine, theirs)):
        w1g4_row = []
        for w1g4_name in w1g4_names:
            w1g4_perm = _W1G4Permanent(card=_w1g4_find(set_pool, w1g4_name))
            w1g4_game._put_permanent_onto_battlefield(w1g4_seat, w1g4_perm, None)
            w1g4_perm.metadata["summoning_sickness_turn"] = -99
            w1g4_row.append(w1g4_perm)
        w1g4_rows.append(w1g4_row)
    return w1g4_game, w1g4_rows[0], w1g4_rows[1]  # _w1g4_table


def _w1g4_tap_lands(game, seat=0):
    """Tap every untapped land *seat* controls for one mana, through the real
    mana-ability entry point; returns how much reached the pool."""
    w1g4_before = sum(game.players[seat].mana_pool.values())
    for w1g4_land in list(game.controlled_by(seat)):
        if w1g4_land.has_type("land") and not w1g4_land.tapped:
            w1g4_color = (w1g4_land.effective_produced_mana or ("C",))[0]
            assert game.tap_land_for_mana(
                seat, w1g4_land.card.name, w1g4_color,
                permanent_id=w1g4_land.permanent_id,
            )
    return sum(game.players[seat].mana_pool.values()) - w1g4_before  # _w1g4_tap_lands


def _w1g4_untapped_lands(game, seat=0):
    return sum(
        1 for w1g4_perm in game.controlled_by(seat)
        if w1g4_perm.has_type("land") and not w1g4_perm.tapped
    )  # _w1g4_untapped_lands


def test_w1g4_stratadon_costs_one_less_per_basic_land_type(set_pool):
    """"Domain — This spell costs {1} less to cast for each basic land type
    among lands you control." Printed {10}; five types make it {5}, and five
    lands pay it. The pool is empty afterwards: nothing was waived."""
    program = _w1g4_compile(set_pool("PLS")["Stratadon"])
    assert program.supported, program.reason

    game, _mine, _theirs = _w1g4_table(set_pool, hand=["Stratadon"], mine=_W1G4_FIVE)
    assert _w1g4_tap_lands(game) == 5
    cast = game.cast_from_hand(0, "Stratadon")
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    stratadon = next(p for p in game.controlled_by(0) if p.card.name == "Stratadon")
    assert (stratadon.effective_power, stratadon.effective_toughness) == (5, 5)
    assert game._has_keyword(stratadon, "trample")
    assert sum(game.players[0].mana_pool.values()) == 0
    assert "Stratadon costs less to cast (Stratadon)" in game.log


def test_w1g4_stratadon_counts_types_not_lands(set_pool):
    """Five lands holding four types is {6}: the fifth land is a second
    Mountain, the cast is refused for want of one mana, and nothing is spent."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, hand=["Stratadon"],
        mine=["Plains", "Island", "Swamp", "Mountain", "Mountain"],
    )
    assert _w1g4_tap_lands(game) == 5
    cast = game.cast_from_hand(0, "Stratadon")
    assert not cast.supported
    assert "insufficient mana" in cast.details, cast.details
    assert [c.name for c in game.players[0].hand] == ["Stratadon"]
    assert sum(game.players[0].mana_pool.values()) == 5


def test_w1g4_stratadon_reads_its_casters_lands_through_the_layers(set_pool):
    """The count is the caster's board as the cost is determined (CR 601.2f):
    an opponent's five types are nobody's discount, three dual lands are five
    types — and under Blood Moon ("Nonbasic lands are Mountains.") they are
    one, because a land's basic land types are computed (CR 613 layer 4)."""
    from engine.cost_modifiers import cost_reduction_for_cast

    stratadon = set_pool("PLS")["Stratadon"]
    game, _mine, _theirs = _w1g4_table(
        set_pool, mine=["Forest"], theirs=_W1G4_FIVE,
    )
    assert cost_reduction_for_cast(game, 0, stratadon)[0].generic == 1

    game, _mine, _theirs = _w1g4_table(
        set_pool, mine=["Tropical Island", "Badlands", "Tundra"],
    )
    assert cost_reduction_for_cast(game, 0, stratadon)[0].generic == 5
    game._put_permanent_onto_battlefield(
        1, _W1G4Permanent(card=_w1g4_find(set_pool, "Blood Moon")), None
    )
    assert cost_reduction_for_cast(game, 0, stratadon)[0].generic == 1

    game, _mine, _theirs = _w1g4_table(set_pool)
    assert not cost_reduction_for_cast(game, 0, stratadon)[0]


def test_w1g4_the_ai_prices_the_domain_spells_at_the_reduced_cost(set_pool):
    """The AI's affordability read goes through the same
    ``cost_reduction_for_cast`` the cast does. Priced at the printed {16} it
    would never propose Draco; priced cheap where it is not, it would propose
    a cast the rules refuse every turn."""
    from engine.ai_policy import _cost_for

    pls = set_pool("PLS")
    for lands, stratadon, draco in (
        (_W1G4_FIVE, 5, 6), (("Forest",) * 6, 9, 14), ((), 10, 16),
        (("Tropical Island", "Badlands"), 6, 8),
    ):
        game, _mine, _theirs = _w1g4_table(set_pool, mine=lands)
        seat = game.players[0]
        assert _cost_for(game, seat, pls["Stratadon"], None)["generic"] == stratadon
        assert _cost_for(game, seat, pls["Draco"], None)["generic"] == draco


def test_w1g4_a_seat_with_five_types_and_six_lands_is_offered_draco(set_pool):
    """The Rock Hydra test for a cost: the client's castable highlight is a
    third reader of the price, and a seat holding five basic land types on six
    lands must be *offered* a {16} Draco that costs it {6} — while the same
    six lands of one type are offered neither domain creature."""
    from fastapi.testclient import TestClient

    from web.app import app, store

    client = TestClient(app)
    pls = set_pool("PLS")

    def playable(lands):
        response = client.post("/api/sessions", json={
            "mode": "human_vs_ai", "host_name": "W1G4", "host_colors": 2,
            "guest_colors": 2, "seed": 4104,
            "host_deck_cards": [{"name": "Forest", "count": 40}],
            "guest_deck_cards": [{"name": "Forest", "count": 40}],
        })
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]
        session = store.get(session_id)
        game = session.game
        session.pregame_phase = None
        session.current_turn = 0
        game.active_player_index = 0
        game.players[0].hand[:] = [pls["Draco"], pls["Stratadon"]]
        for name in lands:
            game._put_permanent_onto_battlefield(
                0, _W1G4Permanent(card=_w1g4_find(set_pool, name)), None
            )
        game.start_priority_window(0)
        state = client.get(
            f"/api/sessions/{session_id}/state", params={"seat": 0}
        ).json()
        return state["players"][0]["playable_hand_indices"]

    assert playable(_W1G4_FIVE + ("Forest",)) == [0, 1]
    assert playable(_W1G4_FIVE) == [1], "Draco is {6} and there are five lands"
    assert playable(("Forest",) * 6) == []


def test_w1g4_draco_is_cast_for_six_off_five_basic_land_types(set_pool):
    """"This spell costs {2} less to cast for each basic land type among lands
    you control." Printed {16}: five types take {10} off, six lands pay the
    rest, and five lands do not."""
    program = _w1g4_compile(set_pool("PLS")["Draco"])
    assert program.supported, program.reason

    game, _mine, _theirs = _w1g4_table(
        set_pool, hand=["Draco"], mine=_W1G4_FIVE + ("Forest",),
    )
    assert _w1g4_tap_lands(game) == 6
    cast = game.cast_from_hand(0, "Draco")
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    draco = next(p for p in game.controlled_by(0) if p.card.name == "Draco")
    assert (draco.effective_power, draco.effective_toughness) == (9, 9)
    assert game._has_keyword(draco, "flying")
    assert sum(game.players[0].mana_pool.values()) == 0

    game, _mine, _theirs = _w1g4_table(set_pool, hand=["Draco"], mine=_W1G4_FIVE)
    assert _w1g4_tap_lands(game) == 5
    cast = game.cast_from_hand(0, "Draco")
    assert not cast.supported and "insufficient mana" in cast.details
    assert sum(game.players[0].mana_pool.values()) == 5


def test_w1g4_draco_upkeep_is_free_with_five_basic_land_types(set_pool):
    """"…sacrifice this creature unless you pay {10}. This cost is reduced by
    {2} for each basic land type among lands you control." Five types take the
    whole {10} off. A cost of nothing is *paid*, not unpayable: Draco stays,
    no land is tapped, and the prompt quotes the price the handler charges."""
    game, mine, _theirs = _w1g4_table(set_pool, mine=("Draco",) + _W1G4_FIVE)
    draco = mine[0]
    quotes = game.get_upkeep_pay_triggers(0)
    assert [(q["card_name"], q["cost_label"]) for q in quotes] == [("Draco", "{0}")]
    game.resolve_upkeep(0)
    _w1g4_resolve(game)
    assert game.is_on_battlefield(draco)
    assert _w1g4_untapped_lands(game) == 5
    assert "W1G4-A paid upkeep for Draco" in game.log


def test_w1g4_draco_upkeep_charges_what_is_left_of_ten(set_pool):
    """Four types leave {2}, and exactly two lands are tapped for it. Three
    types leave {4}, which three lands cannot pay, so Draco is sacrificed and
    nothing is spent — the reduction never rounds a price to free."""
    game, mine, _theirs = _w1g4_table(
        set_pool, mine=["Draco", "Plains", "Island", "Swamp", "Forest"],
    )
    assert game.get_upkeep_pay_triggers(0)[0]["cost"]["mana"]["generic"] == 2
    game.resolve_upkeep(0)
    _w1g4_resolve(game)
    assert game.is_on_battlefield(mine[0])
    assert _w1g4_untapped_lands(game) == 2

    game, mine, _theirs = _w1g4_table(
        set_pool, mine=["Draco", "Plains", "Island", "Swamp"],
    )
    assert game.get_upkeep_pay_triggers(0)[0]["cost_label"] == "{4}"
    game.resolve_upkeep(0)
    _w1g4_resolve(game)
    assert not game.is_on_battlefield(mine[0])
    assert [c.name for c in game.players[0].graveyard] == ["Draco"]
    assert _w1g4_untapped_lands(game) == 3
    assert "W1G4-A sacrificed Draco on upkeep" in game.log


def test_w1g4_draco_upkeep_with_no_lands_asks_the_printed_ten(set_pool):
    """No basic land type, no reduction: the price is the printed {10}, and a
    seat that cannot pay it loses the Dragon."""
    game, mine, _theirs = _w1g4_table(set_pool, mine=["Draco"])
    assert game.get_upkeep_pay_triggers(0)[0]["cost_label"] == "{10}"
    game.resolve_upkeep(0)
    _w1g4_resolve(game)
    assert not game.is_on_battlefield(mine[0])


def test_w1g4_draco_upkeep_counts_at_resolution_and_may_be_declined(set_pool):
    """The reduction is the board's as the trigger resolves (CR 608.2h): three
    dual lands are five types and the upkeep is free, and under Blood Moon the
    same three lands are one type, the price is {8}, and Draco goes. And a
    free price is still an offer — a player who declines it sacrifices."""
    game, mine, _theirs = _w1g4_table(
        set_pool, mine=["Draco", "Tropical Island", "Badlands", "Tundra"],
    )
    game.resolve_upkeep(0)
    _w1g4_resolve(game)
    assert game.is_on_battlefield(mine[0]) and _w1g4_untapped_lands(game) == 3

    game, mine, _theirs = _w1g4_table(
        set_pool, mine=["Draco", "Tropical Island", "Badlands", "Tundra"],
        theirs=["Blood Moon"],
    )
    assert game.get_upkeep_pay_triggers(0)[0]["cost_label"] == "{8}"
    game.resolve_upkeep(0)
    _w1g4_resolve(game)
    assert not game.is_on_battlefield(mine[0])

    game, mine, _theirs = _w1g4_table(set_pool, mine=("Draco",) + _W1G4_FIVE)
    game.resolve_upkeep(0, human_choices={mine[0].permanent_id: False})
    _w1g4_resolve(game)
    assert not game.is_on_battlefield(mine[0])
    assert _w1g4_untapped_lands(game) == 5


def test_w1g4_a_toll_reduction_refuses_what_it_cannot_charge():
    """The rider is admitted only where something enforces it. A coloured
    reduction per object and a count on somebody else's board both refuse the
    line, and the sentence behind anything but the toll is not consumed — a
    price that shrank unprinted would be wrong in the player's favour."""
    from engine.grammar import compile_line

    toll = "At the beginning of your upkeep, sacrifice this creature unless you pay {10}."
    counted = compile_line(
        f"{toll} This cost is reduced by {{2}} for each artifact you control."
    )
    assert counted.usable
    assert counted.instructions[0].payload["reduced_per_each"] == {
        "generic": 2,
        "count": {
            "zone": "battlefield", "owner": "you",
            "filter": {"type_filter": "artifact"},
        },
    }
    for rider in (
        "This cost is reduced by {U} for each artifact you control.",
        "This cost is reduced by {2} for each creature your opponents control.",
        "This cost is reduced by {2}.",
    ):
        assert not compile_line(f"{toll} {rider}").usable, rider
    assert not compile_line(
        "Destroy target creature. This cost is reduced by {2} for each "
        "artifact you control."
    ).usable


def test_w1g4_a_counted_self_reduction_refuses_what_it_cannot_count():
    """``self_cost_reduction`` reads the multiplier through the grammar's own
    per-each reader and refuses when that refuses: a count on another seat's
    board, a coloured pip repeated per object, and a multiplier beside a gate
    are all a cheaper spell than any card prints."""
    from engine.cost_modifiers import self_cost_reduction

    counted = self_cost_reduction(
        "This spell costs {2} less to cast for each artifact you control."
    )
    assert counted is not None and counted.reduction.generic == 2
    assert counted.per_each == {
        "zone": "battlefield", "owner": "you", "filter": {"type_filter": "artifact"},
    }
    for line in (
        "This spell costs {1} less to cast for each creature your opponents control.",
        "This spell costs {U} less to cast for each artifact you control.",
        "This spell costs {1} less to cast for each card in your graveyard.",
        "This spell costs {1} less to cast for each artifact you control if "
        "you control a Swamp.",
        "This spell costs {X} less to cast for each artifact you control, "
        "where X is the total power of creatures you control.",
    ):
        assert self_cost_reduction(line) is None, line


_W1G4_WALKS = ("plainswalk", "islandwalk", "swampwalk", "mountainwalk", "forestwalk")


def _w1g4_walks(game, permanent):
    return [
        w1g4_walk for w1g4_walk in _W1G4_WALKS
        if game._has_keyword(permanent, w1g4_walk)
    ]  # _w1g4_walks


def test_w1g4_magnigoth_treefolk_walks_by_its_controllers_basic_land_types(set_pool):
    """"Domain — For each basic land type among lands you control, this
    creature has landwalk of that type." The words are named by the walker's
    own lands: a Forest and a Tropical Island are forestwalk and islandwalk,
    an opponent's Swamp is nobody's swampwalk, and with no land there is no
    walk at all."""
    program = _w1g4_compile(set_pool("PLS")["Magnigoth Treefolk"])
    assert program.supported, program.reason

    game, mine, _theirs = _w1g4_table(
        set_pool, mine=["Magnigoth Treefolk", "Forest", "Tropical Island"],
        theirs=["Swamp", "Mountain"], enforce=False,
    )
    assert _w1g4_walks(game, mine[0]) == ["islandwalk", "forestwalk"]

    game, mine, _theirs = _w1g4_table(
        set_pool, mine=("Magnigoth Treefolk",) + _W1G4_FIVE, enforce=False,
    )
    assert _w1g4_walks(game, mine[0]) == list(_W1G4_WALKS)

    game, mine, _theirs = _w1g4_table(
        set_pool, mine=["Magnigoth Treefolk"], theirs=_W1G4_FIVE, enforce=False,
    )
    assert _w1g4_walks(game, mine[0]) == []


def test_w1g4_magnigoth_treefolk_cannot_be_blocked_through_a_shared_land_type(set_pool):
    """CR 702.14c: each walk is checked against the *defending* player's
    lands. With a Forest on both sides the Bears cannot block the Treefolk;
    with the defender's Forest swapped for an Island, forestwalk is idle and
    the same block is legal."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, mine=["Magnigoth Treefolk", "Forest"],
        theirs=["Grizzly Bears", "Forest"], enforce=False,
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    blocked, why = game.declare_blockers(1, {0: 0})
    assert not blocked and "cannot block" in why

    game, _mine, _theirs = _w1g4_table(
        set_pool, mine=["Magnigoth Treefolk", "Forest"],
        theirs=["Grizzly Bears", "Island"], enforce=False,
    )
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0], "no Forest over there"


def test_w1g4_magnigoth_treefolk_recounts_as_the_lands_change(set_pool):
    """A static ability locks nothing in (CR 611.3a). A land drop adds its
    walk, a land destroyed by a spell takes its walk with it, and the types
    are the computed ones — under Blood Moon two dual lands are Mountains and
    the only walk is mountainwalk; once it is destroyed the four come back."""
    game, mine, _theirs = _w1g4_table(
        set_pool, hand=["Island", "Disenchant"],
        mine=["Magnigoth Treefolk", "Forest", "Tropical Island"],
        theirs=["Grizzly Bears"], enforce=False,
    )
    tree, _forest, tropical = mine
    game.players[1].hand.extend(
        [_w1g4_find(set_pool, "Stone Rain"), _w1g4_find(set_pool, "Blood Moon")]
    )
    assert _w1g4_walks(game, tree) == ["islandwalk", "forestwalk"]

    assert game.cast_from_hand(
        1, "Stone Rain", target_player_index=0,
        target_permanent_ids=[tropical.permanent_id],
    ).supported
    _w1g4_resolve(game)
    assert not game.is_on_battlefield(tropical)
    assert _w1g4_walks(game, tree) == ["forestwalk"]

    assert game.cast_from_hand(0, "Island").supported
    _w1g4_resolve(game)
    assert _w1g4_walks(game, tree) == ["islandwalk", "forestwalk"]

    game, mine, _theirs = _w1g4_table(
        set_pool, hand=["Disenchant"],
        mine=["Magnigoth Treefolk", "Tropical Island", "Badlands"], enforce=False,
    )
    tree = mine[0]
    game.players[1].hand.append(_w1g4_find(set_pool, "Blood Moon"))
    assert _w1g4_walks(game, tree) == [
        "islandwalk", "swampwalk", "mountainwalk", "forestwalk",
    ]
    assert game.cast_from_hand(1, "Blood Moon").supported
    _w1g4_resolve(game)
    assert _w1g4_walks(game, tree) == ["mountainwalk"]
    moon = next(p for p in game.controlled_by(1) if p.card.name == "Blood Moon")
    assert game.cast_from_hand(
        0, "Disenchant", target_player_index=1,
        target_permanent_ids=[moon.permanent_id],
    ).supported
    _w1g4_resolve(game)
    assert _w1g4_walks(game, tree) == [
        "islandwalk", "swampwalk", "mountainwalk", "forestwalk",
    ]


def test_w1g4_magnigoth_treefolk_walks_for_whoever_controls_it(set_pool):
    """"Lands **you** control" is the Treefolk's controller (CR 109.5), read
    as the walks are derived: stolen with Control Magic, it walks by its new
    controller's Swamp and no longer by its owner's Forest."""
    game, mine, _theirs = _w1g4_table(
        set_pool, mine=["Magnigoth Treefolk", "Forest"], theirs=["Swamp"],
        enforce=False,
    )
    tree = mine[0]
    game.players[1].hand.append(_w1g4_find(set_pool, "Control Magic"))
    assert _w1g4_walks(game, tree) == ["forestwalk"]
    assert game.cast_from_hand(
        1, "Control Magic", target_player_index=0,
        target_permanent_ids=[tree.permanent_id],
    ).supported
    _w1g4_resolve(game)
    assert game.controller_index_of(tree) == 1
    assert _w1g4_walks(game, tree) == ["swampwalk"]


def test_w1g4_a_board_named_landwalk_refuses_what_it_cannot_name():
    """One reader, two callers: the support gate claims the line through the
    function the layer-6 pass grants through. A set on another player's board,
    a characteristic no landwalk is built from, and a grant to some other
    object all refuse — admitted, each would be a creature that reports
    supported and has no evasion at all."""
    from engine.grammar import compile_line
    from engine.landwalk import landwalk_per_type_spec

    printed = (
        "Domain — For each basic land type among lands you control, this "
        "creature has landwalk of that type. (It can't be blocked as long as "
        "defending player controls a land of that type.)"
    )
    assert landwalk_per_type_spec(printed) == {
        "zone": "battlefield", "owner": "you",
        "filter": {"type_filter": "land"},
        "aggregate": "distinct_basic_land_types",
    }
    assert compile_line(printed).parsed
    for line in (
        "For each basic land type among lands your opponents control, this "
        "creature has landwalk of that type.",
        "For each creature you control, this creature has landwalk of that type.",
        "For each basic land type among lands you control, target creature "
        "has landwalk of that type.",
        "For each basic land type among lands you control, this creature has "
        "landwalk of that type and flying.",
    ):
        assert landwalk_per_type_spec(line) is None, line
        assert not compile_line(line).usable, line


# -- supported on arrival: driven, not built ----------------------------------

_W1G4_FAMILIARS = (
    # (the Familiar, a spell of each colour it names, a spell of neither)
    ("Sunscape Familiar", "Craw Wurm", "Air Elemental", "Serra Angel"),
    ("Stormscape Familiar", "Serra Angel", "Sengir Vampire", "Craw Wurm"),
    ("Nightscape Familiar", "Air Elemental", "Shivan Dragon", "Craw Wurm"),
    ("Thunderscape Familiar", "Sengir Vampire", "Craw Wurm", "Serra Angel"),
    ("Thornscape Familiar", "Shivan Dragon", "Serra Angel", "Air Elemental"),
)


def _w1g4_generic_cost(game, seat, card):
    from engine.ai_policy import _cost_for

    return _cost_for(game, game.players[seat], card, None)["generic"]  # _w1g4_generic_cost


import pytest as _w1g4_pytest


@_w1g4_pytest.mark.parametrize(
    "familiar,first,second,neither", _W1G4_FAMILIARS,
    ids=[row[0] for row in _W1G4_FAMILIARS],
)
def test_w1g4_familiar_takes_one_generic_off_its_controllers_two_colours(
    set_pool, familiar, first, second, neither,
):
    """"<Colour> spells and <colour> spells you cast cost {1} less to cast."
    Each named colour is a mana cheaper for the Familiar's controller, a spell
    of neither colour is not, and the seat across the table pays full price
    for everything — "you cast" is the controller (CR 109.5)."""
    lea = set_pool("LEA")
    game, _mine, _theirs = _w1g4_table(set_pool, mine=[familiar])
    plain, _a, _b = _w1g4_table(set_pool)
    for spell in (first, second):
        printed = _w1g4_generic_cost(plain, 0, lea[spell])
        assert _w1g4_generic_cost(game, 0, lea[spell]) == printed - 1, spell
        assert _w1g4_generic_cost(game, 1, lea[spell]) == printed, spell
    printed = _w1g4_generic_cost(plain, 0, lea[neither])
    assert _w1g4_generic_cost(game, 0, lea[neither]) == printed


def test_w1g4_familiars_stack_and_one_familiar_is_one_reduction(set_pool):
    """Two Familiars are two effects and take {2}; one Familiar naming both of
    a spell's colours is one effect and takes {1} — Arcades Sabboth is green
    *and* blue under a single Sunscape Familiar and is one mana cheaper, not
    two. A second Familiar naming one of its colours takes the second."""
    from engine.cost_modifiers import cost_reduction_for_cast

    lea, leg = set_pool("LEA"), set_pool("LEG")
    game, _mine, _theirs = _w1g4_table(set_pool, mine=["Sunscape Familiar"])
    assert cost_reduction_for_cast(game, 0, leg["Arcades Sabboth"])[0].generic == 1

    game, _mine, _theirs = _w1g4_table(
        set_pool, mine=["Sunscape Familiar", "Sunscape Familiar"],
    )
    assert cost_reduction_for_cast(game, 0, lea["Craw Wurm"])[0].generic == 2

    # Sunscape names green and blue, Thunderscape black and green.
    game, _mine, _theirs = _w1g4_table(
        set_pool, mine=["Sunscape Familiar", "Thunderscape Familiar"],
    )
    reductions = {
        name: cost_reduction_for_cast(game, 0, lea[name])[0].generic
        for name in ("Craw Wurm", "Air Elemental", "Sengir Vampire", "Serra Angel",
                     "Juggernaut")
    }
    assert reductions == {
        "Craw Wurm": 2, "Air Elemental": 1, "Sengir Vampire": 1, "Serra Angel": 0,
        "Juggernaut": 0,
    }


def test_w1g4_a_familiars_reduction_is_generic_mana_only(set_pool):
    """CR 118.7a: a generic reduction touches the generic component and
    nothing else. Under a Sunscape Familiar a {1}{G} Bears is cast for one
    Forest, and a {G} Giant Growth is still {G} — with the pool empty the cast
    is refused, because there was no generic mana for the Familiar to take."""
    game, mine, _theirs = _w1g4_table(
        set_pool, hand=["Grizzly Bears", "Giant Growth"],
        mine=["Sunscape Familiar", "Forest"],
    )
    assert _w1g4_tap_lands(game) == 1
    cast = game.cast_from_hand(0, "Grizzly Bears")
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    assert "Grizzly Bears costs less to cast (Sunscape Familiar)" in game.log
    assert sum(game.players[0].mana_pool.values()) == 0

    growth = game.cast_from_hand(
        0, "Giant Growth", target_player_index=0,
        target_permanent_ids=[mine[0].permanent_id],
    )
    assert not growth.supported and "insufficient mana" in growth.details


def test_w1g4_a_familiar_takes_its_mana_off_an_x_spell(set_pool):
    """{X} is generic mana once announced (CR 107.3), so the reduction comes
    off it: Hurricane with X=3 is {3}{G}, and three Forests pay it under a
    Sunscape Familiar. All three points of damage are dealt."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, hand=["Hurricane"],
        mine=["Sunscape Familiar", "Forest", "Forest", "Forest"],
    )
    assert _w1g4_tap_lands(game) == 3
    cast = game.cast_from_hand(0, "Hurricane", x_value=3)
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    assert [player.life for player in game.players] == [17, 17]
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g4_the_familiars_keep_their_printed_bodies(set_pool):
    """The line beside the reduction is the rest of the card: Sunscape is a
    0/3 with defender and cannot be declared as an attacker, Stormscape flies,
    Thunderscape has first strike."""
    for name, keyword in (
        ("Sunscape Familiar", "defender"), ("Stormscape Familiar", "flying"),
        ("Thunderscape Familiar", "first strike"),
    ):
        game, mine, _theirs = _w1g4_table(set_pool, mine=[name])
        assert game._has_keyword(mine[0], keyword), name

    game, mine, _theirs = _w1g4_table(set_pool, mine=["Sunscape Familiar"])
    assert (mine[0].effective_power, mine[0].effective_toughness) == (0, 3)
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert not game.declare_attackers(0, [0])[0]


def test_w1g4_nightscape_familiar_regenerates_for_one_and_a_black(set_pool):
    """"{1}{B}: Regenerate this creature." Two Swamps pay it; a Lightning Bolt
    then destroys nothing — the shield is spent, the Familiar is tapped and
    still on the battlefield (CR 701.19a)."""
    game, mine, _theirs = _w1g4_table(
        set_pool, mine=["Nightscape Familiar", "Swamp", "Swamp"],
    )
    familiar = mine[0]
    game.players[1].hand.append(_w1g4_find(set_pool, "Lightning Bolt"))
    assert _w1g4_tap_lands(game) == 2
    activated = game.activate_permanent_ability(0, "Nightscape Familiar")
    assert activated.supported, activated.details
    _w1g4_resolve(game)
    assert sum(game.players[0].mana_pool.values()) == 0

    game.enforce_mana_costs = False
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[familiar.permanent_id],
    ).supported
    _w1g4_resolve(game)
    assert game.is_on_battlefield(familiar) and familiar.tapped
    assert "Nightscape Familiar regenerated" in game.log


def test_w1g4_samite_pilgrim_prevents_its_activators_domain(set_pool):
    """"{T}: Prevent the next X damage that would be dealt to target creature
    this turn, where X is the number of basic land types among lands you
    control." Three types shield the Bears for three: a 5-point hit deals 2
    and the next is dealt in full. The count is the *activator's* — aimed at
    an opponent's creature it is still sized by the Pilgrim's side."""
    from tests.helpers import _damage_dealt

    game, mine, theirs = _w1g4_table(
        set_pool, mine=["Samite Pilgrim", "Grizzly Bears", "Plains", "Island", "Swamp"],
        theirs=["Mountain"], enforce=False,
    )
    pilgrim, bears = mine[0], mine[1]
    activated = game.activate_permanent_ability(
        0, "Samite Pilgrim", target_permanent_ids=[bears.permanent_id],
    )
    assert activated.supported, activated.details
    _w1g4_resolve(game)
    assert pilgrim.tapped
    assert "Grizzly Bears gains prevention shield for 3 damage" in game.log
    assert _damage_dealt(game, bears, 5, source=theirs[0]) == 2
    assert _damage_dealt(game, bears, 2, source=theirs[0]) == 2

    game, mine, theirs = _w1g4_table(
        set_pool, mine=["Samite Pilgrim", "Forest"],
        theirs=("Grizzly Bears",) + _W1G4_FIVE, enforce=False,
    )
    assert game.activate_permanent_ability(
        0, "Samite Pilgrim", target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g4_resolve(game)
    assert _damage_dealt(game, theirs[0], 5, source=mine[1]) == 4


def test_w1g4_the_castable_highlight_sees_a_familiars_reduction(set_pool):
    """The client's glow is the third reader of a price. One Forest and a
    Sunscape Familiar make a {1}{G} Bears castable where one Forest alone
    does not; an opponent's Familiar changes nothing for this seat, and a
    white spell is never cheaper."""
    from fastapi.testclient import TestClient

    from web.app import app, store

    client = TestClient(app)
    hand = ("Grizzly Bears", "Craw Wurm", "Serra Angel", "Llanowar Elves")

    def playable(mine, theirs=()):
        response = client.post("/api/sessions", json={
            "mode": "human_vs_ai", "host_name": "W1G4", "host_colors": 2,
            "guest_colors": 2, "seed": 4104,
            "host_deck_cards": [{"name": "Forest", "count": 40}],
            "guest_deck_cards": [{"name": "Forest", "count": 40}],
        })
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]
        session = store.get(session_id)
        game = session.game
        session.pregame_phase = None
        session.current_turn = 0
        game.active_player_index = 0
        game.players[0].hand[:] = [_w1g4_find(set_pool, name) for name in hand]
        for seat, names in enumerate((mine, theirs)):
            for name in names:
                game._put_permanent_onto_battlefield(
                    seat, _W1G4Permanent(card=_w1g4_find(set_pool, name)), None
                )
        game.start_priority_window(0)
        state = client.get(
            f"/api/sessions/{session_id}/state", params={"seat": 0}
        ).json()
        return state["players"][0]["playable_hand_indices"]

    assert playable(["Forest"]) == [3], "one Forest casts the Elves alone"
    assert playable(["Forest", "Sunscape Familiar"]) == [0, 3]
    assert playable(["Forest"], theirs=["Sunscape Familiar"]) == [3]
    assert playable(["Forest"] * 5 + ["Sunscape Familiar"]) == [0, 1, 3], (
        "the Wurm is {3}{G}{G} under the Familiar; the Angel is white and is not"
    )
