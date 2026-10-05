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


# --- W1G6: colour ---
# Becoming a colour, being one, sharing one, and protection from one. Colour is
# read through CR 613's layer 5 everywhere below (`Game._effective_colors`),
# never off the printed card: half of these tests change a colour mid-game and
# ask the card again.
import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine import targeting as _w1g6_targeting
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    """*name* from Planeshift, else Invasion, else Alpha."""
    for code in ("PLS", "INV", "LEA"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(name)  # _w1g6_card (creatures)


def _w1g6_table(set_pool, mine=(), theirs=(), *, mana=False, interactive=(0,)):
    """Seat 0 holds *mine* and seat 1 *theirs*, nothing summoning-sick, on
    seat 0's turn. Returns the game and the two lists of permanents."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = mana
    w1g6_game.interactive_seats = set(interactive)
    w1g6_game.active_player_index = 0
    w1g6_sides = []
    for seat, names in ((0, mine), (1, theirs)):
        side = []
        for name in names:
            perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            side.append(perm)
        w1g6_sides.append(side)
    return w1g6_game, w1g6_sides[0], w1g6_sides[1]  # _w1g6_table (creatures)


def _w1g6_colors(game, perm):
    return sorted(game._effective_colors(perm))  # _w1g6_colors (creatures)


def _w1g6_names(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))  # _w1g6_names (creatures)


def _w1g6_ability(card, index=0):
    """The *index*-th activated ability of *card* and the picker spec the
    compiled program derives for it."""
    w1g6_ability = _w1g6_compile(card).activated_abilities[index]
    return w1g6_ability, _w1g6_targeting.derive_activation_spec(w1g6_ability)  # _w1g6_ability


def test_w1g6_disciple_of_kangee_gives_one_target_flying_and_blue_for_a_turn(set_pool):
    """"{U}, {T}: Target creature gains flying and becomes blue until end of
    turn." One target, two things said about it, one window: the red Giant
    flies and is blue (CR 105.3 — blue *instead of* red), the Bears beside it
    are untouched, the Disciple is tapped and {U} is spent, and at cleanup the
    Giant is a red ground creature again."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Disciple of Kangee", "Grizzly Bears"], ["Hill Giant"], mana=True,
    )
    disciple, bears = mine
    giant = theirs[0]
    _ability, spec = _w1g6_ability(disciple.card)
    assert spec == {"kind": "creature"}

    assert not game.queue_permanent_ability(
        0, "Disciple of Kangee", ability_index=0,
        target_permanent_ids=[giant.permanent_id],
    ).supported, "no {U}, no ability"
    game.players[0].mana_pool["U"] = 1
    assert game.queue_permanent_ability(
        0, "Disciple of Kangee", ability_index=0,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    assert disciple.tapped and game.players[0].mana_pool["U"] == 0
    assert _w1g6_colors(game, giant) == ["R"] and not game._has_keyword(giant, "flying")
    _w1g6_resolve_stack(game)

    assert _w1g6_colors(game, giant) == ["U"] and game._has_keyword(giant, "flying")
    assert _w1g6_colors(game, bears) == ["G"] and not game._has_keyword(bears, "flying")

    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, giant) == ["R"] and not game._has_keyword(giant, "flying")


def test_w1g6_disciple_of_kangee_may_be_aimed_at_its_controllers_own_creature(set_pool):
    """The id names a battlefield as well as an object: aimed at the Bears on
    its own side, the Bears — not the opponent's Giant — fly and turn blue."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Disciple of Kangee", "Grizzly Bears"], ["Hill Giant"],
    )
    bears, giant = mine[1], theirs[0]

    assert game.queue_permanent_ability(
        0, "Disciple of Kangee", ability_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_resolve_stack(game)

    assert _w1g6_colors(game, bears) == ["U"] and game._has_keyword(bears, "flying")
    assert _w1g6_colors(game, giant) == ["R"] and not game._has_keyword(giant, "flying")


def _w1g6_libraries(game, set_pool):
    """Five Forests under seat 0 and five Islands under seat 1, so a card drawn
    names the library it left."""
    game.players[0].library.extend([_w1g6_card(set_pool, "Forest")] * 5)
    game.players[1].library.extend([_w1g6_card(set_pool, "Island")] * 5)
    return game  # _w1g6_libraries


def test_w1g6_questing_phelddagrif_gains_both_protections_and_the_opponent_gains_life(set_pool):
    """"{W}: This creature gains protection from black and from red until end
    of turn. Target opponent gains 2 life." CR 702.16g: two protection
    abilities from one list. Both colours are protected against — a red Bolt
    and a black Terror are illegal announcements — green is not, the *opponent*
    is the one two life up, and both protections are gone at cleanup."""
    game, mine, _theirs = _w1g6_table(set_pool, ["Questing Phelddagrif"], ["Black Knight"], mana=True)
    phelddagrif = mine[0]
    game.players[1].hand.extend(
        _w1g6_card(set_pool, name) for name in ("Lightning Bolt", "Terror", "Giant Growth")
    )
    game.players[0].mana_pool["W"] = 1
    assert game._protection_colors(phelddagrif) == set()

    assert game.queue_permanent_ability(
        0, "Questing Phelddagrif", ability_index=1, target_player_index=1,
    ).supported
    assert game.players[0].mana_pool["W"] == 0
    _w1g6_resolve_stack(game)

    assert game._protection_colors(phelddagrif) == {"B", "R"}
    assert (game.players[0].life, game.players[1].life) == (20, 22)
    for name in ("Lightning Bolt", "Terror"):
        refused = game.queue_from_hand(1, name, target_permanent_ids=[phelddagrif.permanent_id])
        assert not refused.supported and "illegal target" in refused.details, (name, refused.details)
    game.players[1].mana_pool["G"] = 1
    assert game.queue_from_hand(
        1, "Giant Growth", target_permanent_ids=[phelddagrif.permanent_id],
    ).supported, "green is neither black nor red"
    _w1g6_resolve_stack(game)

    game.resolve_cleanup_step(0)
    assert game._protection_colors(phelddagrif) == set()


def test_w1g6_questing_phelddagrifs_other_two_abilities_pay_the_opponent(set_pool):
    """"{G}: … gets +1/+1 until end of turn. Target opponent creates a 1/1 green
    Hippo creature token." and "{U}: … gains flying until end of turn. Target
    opponent may draw a card." The Hippo lands on the opponent's battlefield,
    and the card is drawn **by the opponent, from the opponent's library** —
    the offered seat is the one that draws (the bare "draw a card" used to be
    read as the ability's controller's)."""
    game, mine, _theirs = _w1g6_table(set_pool, ["Questing Phelddagrif"], [], interactive=(0, 1))
    _w1g6_libraries(game, set_pool)
    phelddagrif = mine[0]

    assert game.queue_permanent_ability(
        0, "Questing Phelddagrif", ability_index=0, target_player_index=1,
    ).supported
    _w1g6_resolve_stack(game)
    assert (phelddagrif.effective_power, phelddagrif.effective_toughness) == (5, 5)
    (hippo,) = game.controlled_by(1)
    assert hippo.card.name == "Hippo Token" and _w1g6_colors(game, hippo) == ["G"]
    assert (hippo.effective_power, hippo.effective_toughness) == (1, 1)

    assert game.queue_permanent_ability(
        0, "Questing Phelddagrif", ability_index=2, target_player_index=1,
    ).supported
    game.resolve_top_of_stack()
    assert game._has_keyword(phelddagrif, "flying")
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("optional_pay", 1)]
    assert game.confirm_optional_pay(1, accept=True)
    assert [card.name for card in game.players[1].hand] == ["Island"]
    assert game.players[0].hand == [] and len(game.players[0].library) == 5


def test_w1g6_questing_phelddagrif_offers_and_requires_an_opponent_for_every_ability(set_pool):
    """Each ability's second sentence targets an opponent, so each derives the
    opponent picker and none may be aimed at its own controller. The {W} one
    derived no picker at all — its first step's positive "this targets
    nothing" ended the walk before the sentence behind it was read — and was
    activatable naming its own controller as the "opponent"."""
    card = _w1g6_card(set_pool, "Questing Phelddagrif")
    for index in range(3):
        _ability, spec = _w1g6_ability(card, index)
        assert spec == {"kind": "player", "opponents_only": True}, index

    game, _mine, _theirs = _w1g6_table(set_pool, ["Questing Phelddagrif"], [])
    for index in range(3):
        refused = game.queue_permanent_ability(
            0, "Questing Phelddagrif", ability_index=index, target_player_index=0,
        )
        assert not refused.supported, index
    assert game.stack == [] and game.players[0].life == 20


@_w1g6_pytest.mark.parametrize("name, index, announcement", [
    ("Phelddagrif", 2, {"target_player_index": 1}),
    ("Soldevi Heretic", 0, None),
])
def test_w1g6_a_shipped_target_opponent_may_draw_a_card_draws_for_the_opponent(
    set_pool, name, index, announcement,
):
    """Alliances prints the same sentence twice ("Target opponent may draw a
    card." — Phelddagrif's {U}, Soldevi Heretic's rider) and both handed the
    card to the ability's own controller. Accepted, the opponent draws from
    their own library; declined, nobody draws."""
    for accept in (True, False):
        game = _W1G6Game(players=[
            _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0, 1}
        game.active_player_index = 0
        _w1g6_libraries(game, set_pool)
        source = _W1G6Permanent(card=set_pool("ALL")[name])
        bears = _W1G6Permanent(card=_w1g6_card(set_pool, "Grizzly Bears"))
        for perm in (source, bears):
            game._put_permanent_onto_battlefield(0, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
        chosen = announcement or {"target_role_refs": [
            {"permanent_id": bears.permanent_id}, {"seat": 1},
        ]}

        assert game.queue_permanent_ability(0, name, ability_index=index, **chosen).supported
        game.resolve_top_of_stack()
        assert [(c.kind, c.player_index) for c in game.pending_choices] == [("optional_pay", 1)]
        assert game.confirm_optional_pay(1, accept=accept)

        assert [card.name for card in game.players[1].hand] == (["Island"] if accept else [])
        assert "Forest" not in [card.name for card in game.players[0].hand]
        assert len(game.players[0].library) == 5


def test_w1g6_phelddagrifs_trample_ability_now_offers_its_opponent(set_pool):
    """"{G}: Phelddagrif gains trample until end of turn. Target opponent
    creates a 1/1 green Hippo creature token." (Alliances.) The same shadowed
    picker Questing Phelddagrif's {W} had: the grant in front answered "nothing
    to point at" and the token's target was never derived."""
    ability, spec = _w1g6_ability(set_pool("ALL")["Phelddagrif"], 0)
    assert spec == {"kind": "player", "opponents_only": True}

    game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._put_permanent_onto_battlefield(
        0, _W1G6Permanent(card=set_pool("ALL")["Phelddagrif"]), None,
    )
    assert not game.queue_permanent_ability(
        0, "Phelddagrif", ability_index=0, target_player_index=0,
    ).supported
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Phelddagrif"]


def _w1g6_greevil_table(set_pool, interactive):
    """Root Greevil facing three colours of enchantment, one of them — the
    opponent's red Orcish Oriflamme — turned black through layer 5."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Root Greevil", "Castle", "Bad Moon"],
        ["Crusade", "Bad Moon", "Orcish Oriflamme", "Grizzly Bears", "Howling Mine"],
        mana=True, interactive=interactive,
    )
    oriflamme = theirs[2]
    oriflamme.metadata["color_override_until_eot"] = "B"
    game._recompute_continuous_effects()
    assert _w1g6_colors(game, oriflamme) == ["B"]
    return game, mine, theirs  # _w1g6_greevil_table


def test_w1g6_root_greevil_destroys_every_enchantment_of_the_colour_chosen_at_resolution(set_pool):
    """"{2}{G}, {T}, Sacrifice this creature: Destroy all enchantments of the
    color of your choice." The Greevil is sacrificed and {2}{G} spent as the
    ability is activated; the colour is asked as it **resolves** (CR 608.2d) —
    the white sent with the activation is not read. Black is answered: both
    players' Bad Moons go, and so does the Oriflamme a colour change made
    black. White Castle and Crusade, the green creature and the colourless
    artifact stay."""
    game, mine, _theirs = _w1g6_greevil_table(set_pool, (0,))
    greevil = mine[0]
    _ability, spec = _w1g6_ability(greevil.card)
    assert spec is None, "a sweep chooses no target"

    assert not game.queue_permanent_ability(0, "Root Greevil", ability_index=0).supported
    game.players[0].mana_pool["G"] = 3
    assert game.queue_permanent_ability(
        0, "Root Greevil", ability_index=0, mana_color="W",
    ).supported
    assert not game.is_on_battlefield(greevil)
    assert [card.name for card in game.players[0].graveyard] == ["Root Greevil"]
    assert game.players[0].mana_pool["G"] == 0

    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert _w1g6_names(game, 1) == [
        "Bad Moon", "Crusade", "Grizzly Bears", "Howling Mine", "Orcish Oriflamme",
    ], "nothing is destroyed before the colour is named"
    assert game.confirm_color_choice(0, "B")
    _w1g6_resolve_stack(game)

    assert _w1g6_names(game, 0) == ["Castle"]
    assert _w1g6_names(game, 1) == ["Crusade", "Grizzly Bears", "Howling Mine"]
    assert sorted(card.name for card in game.players[1].graveyard) == [
        "Bad Moon", "Orcish Oriflamme",
    ]


def test_w1g6_root_greevil_sweeps_for_a_seat_nobody_asks(set_pool):
    """A headless seat takes the prompt's default — the colour its opponents
    hold most of — and the sweep still runs once, over one colour: every
    enchantment that goes is the same colour, and at least one enchantment of
    another colour is still there."""
    game, _mine, _theirs = _w1g6_greevil_table(set_pool, ())
    game.players[0].mana_pool["G"] = 3
    before = {
        perm.permanent_id: (perm.card.name, tuple(_w1g6_colors(game, perm)))
        for perm in game.all_permanents() if perm.has_type("enchantment")
    }

    assert game.queue_permanent_ability(0, "Root Greevil", ability_index=0).supported
    _w1g6_resolve_stack(game)

    survivors = {perm.permanent_id for perm in game.all_permanents()}
    gone = {colour for pid, (_name, colour) in before.items() if pid not in survivors}
    kept = {colour for pid, (_name, colour) in before.items() if pid in survivors}
    assert len(gone) == 1 and gone.isdisjoint(kept), (gone, kept)
    assert kept, "enchantments of the other colour were left alone"
    assert game.pending_choices == []


def _w1g6_cast_voice(set_pool, theirs, colour, *, interactive=(0,)):
    """Seat 0 casts Voice of All against *theirs* and (when asked) answers the
    entry choice with *colour*. Returns the game, the Voice and their board."""
    game, _mine, their_side = _w1g6_table(set_pool, [], theirs, interactive=interactive)
    game.players[0].hand.append(_w1g6_card(set_pool, "Voice of All"))
    assert game.queue_from_hand(0, "Voice of All").supported
    game.resolve_top_of_stack()
    voice = next(p for p in game.controlled_by(0) if p.card.name == "Voice of All")
    voice.metadata["summoning_sickness_turn"] = -99
    if interactive:
        assert [(c.kind, c.player_index) for c in game.pending_choices] == [("enter_choice", 0)]
        assert game.confirm_enter_choice(0, mana_color=colour)
    return game, voice, their_side  # _w1g6_cast_voice


def _w1g6_block(game, attacker, blocker):
    """Seat 0 attacks with *attacker*; seat 1 tries to block it with *blocker*.
    Returns the engine's answer to the block declaration."""
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(attacker)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    return game.declare_blockers(1, {
        game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)],
    })  # _w1g6_block


def test_w1g6_voice_of_all_has_protection_from_the_colour_its_controller_chose(set_pool):
    """"As this creature enters, choose a color. / This creature has protection
    from the chosen color." Its controller is asked as it enters; black is
    answered, so a black Terror is an illegal announcement, a red Bolt is a
    legal one, and black damage is prevented while red damage is not
    (CR 702.16e)."""
    voice_card = _w1g6_card(set_pool, "Voice of All")
    assert _w1g6_compile(voice_card).supported
    game, voice, (knight, giant) = _w1g6_cast_voice(
        set_pool, ["Black Knight", "Hill Giant"], "B",
    )
    assert game._has_keyword(voice, "flying")
    assert game._protection_colors(voice) == {"B"}

    game.players[1].hand.extend(_w1g6_card(set_pool, n) for n in ("Terror", "Lightning Bolt"))
    refused = game.queue_from_hand(1, "Terror", target_permanent_ids=[voice.permanent_id])
    assert not refused.supported and "illegal target" in refused.details
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[voice.permanent_id],
    ).supported
    game.stack.clear()

    from tests.helpers import _damage_dealt as _w1g6_damage_dealt

    assert _w1g6_damage_dealt(game, voice, 2, source=knight) == 0
    assert _w1g6_damage_dealt(game, voice, 3, source=giant) == 3


def test_w1g6_voice_of_all_reads_a_blockers_colour_through_the_layers(set_pool):
    """CR 702.16f: it can't be blocked by creatures of the chosen colour — and
    the colour is the one the blocker has *now*. A red Roc may block a Voice
    that chose black; the same Roc turned black for the turn may not, exactly
    as the printed-black Vampire may not."""
    game, voice, (vampire, roc) = _w1g6_cast_voice(
        set_pool, ["Sengir Vampire", "Roc of Kher Ridges"], "B",
    )
    assert not _w1g6_block(game, voice, vampire)[0]

    game, voice, (vampire, roc) = _w1g6_cast_voice(
        set_pool, ["Sengir Vampire", "Roc of Kher Ridges"], "B",
    )
    assert _w1g6_block(game, voice, roc)[0]

    game, voice, (vampire, roc) = _w1g6_cast_voice(
        set_pool, ["Sengir Vampire", "Roc of Kher Ridges"], "B",
    )
    roc.metadata["color_override_until_eot"] = "B"
    game._recompute_continuous_effects()
    assert _w1g6_colors(game, roc) == ["B"]
    assert not _w1g6_block(game, voice, roc)[0]


def test_w1g6_voice_of_alls_protection_follows_the_record_and_the_ability(set_pool):
    """Derived from the entry record on every ask rather than stamped once: a
    seat nobody asks takes the default — the colour its opponents hold most of,
    red here — with no prompt left owing; a later answer is the colour it then
    has; and a Voice that has lost its abilities (Humility, CR 613.1f) has no
    protection at all."""
    game, voice, _theirs = _w1g6_cast_voice(
        set_pool, ["Black Knight", "Hill Giant", "Goblin Balloon Brigade"], None,
        interactive=(),
    )
    assert game.pending_choices == []
    assert game._protection_colors(voice) == {"R"}

    voice.metadata["chosen_color"] = "G"
    assert game._protection_colors(voice) == {"G"}

    humility = _W1G6Permanent(card=set_pool("TMP")["Humility"])
    game._put_permanent_onto_battlefield(1, humility, None)
    game._recompute_continuous_effects()
    assert game._protection_colors(voice) == set()
    assert not game._has_keyword(voice, "flying")


def _w1g6_elder_table(set_pool):
    """A Samite Elder with a green, a three-coloured and a colourless
    permanent beside it, facing a red creature."""
    game, mine, theirs = _w1g6_table(
        set_pool,
        ["Samite Elder", "Grizzly Bears", "Questing Phelddagrif", "Howling Mine", "Forest"],
        ["Hill Giant"],
    )
    return game, mine, theirs[0]  # _w1g6_elder_table


def _w1g6_elder_names(game, target):
    """Activate the Elder naming *target* and resolve it."""
    activated = game.queue_permanent_ability(
        0, "Samite Elder", ability_index=0, target_permanent_ids=[target.permanent_id],
    )
    assert activated.supported, activated.details
    _w1g6_resolve_stack(game)
    return activated  # _w1g6_elder_names


def test_w1g6_samite_elder_protects_its_team_from_each_colour_of_the_chosen_permanent(set_pool):
    """"{T}: Choose target permanent you control. Creatures you control gain
    protection from each of that permanent's colors until end of turn."
    CR 702.16g: one protection ability per colour. The green-white-blue
    Phelddagrif is named, so every creature the Elder's controller has — the
    Elder and the Phelddagrif included — has protection from all three; the
    artifact beside them (not a creature) and the opponent's Giant have none,
    and it is all gone at cleanup."""
    game, mine, giant = _w1g6_elder_table(set_pool)
    elder, bears, phelddagrif, artifact, _forest = mine
    _ability, spec = _w1g6_ability(elder.card)
    assert spec == {"kind": "permanent", "own_only": True}

    _w1g6_elder_names(game, phelddagrif)
    assert elder.tapped
    for creature in (elder, bears, phelddagrif):
        assert game._protection_colors(creature) == {"G", "U", "W"}, creature.card.name
    assert game._protection_colors(artifact) == set()
    assert game._protection_colors(giant) == set()

    game.resolve_cleanup_step(0)
    assert game._protection_colors(bears) == set()


def test_w1g6_samite_elder_may_only_choose_its_controllers_own_permanent(set_pool):
    """"…target permanent **you control**": the opponent's Giant is not a legal
    announcement, and nothing is tapped or granted for trying."""
    game, mine, giant = _w1g6_elder_table(set_pool)
    refused = game.queue_permanent_ability(
        0, "Samite Elder", ability_index=0, target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported
    assert not mine[0].tapped and game.stack == []


def test_w1g6_samite_elder_reads_the_chosen_permanents_colours_as_it_resolves(set_pool):
    """The colours are the chosen permanent's own, read through layer 5 as the
    ability resolves (CR 608.2h) — not the Elder's, and not the printed ones.
    A colourless artifact names no colour, so nobody gains anything (the
    permanent that is recorded is the artifact that was chosen, never the first
    creature on the battlefield in its place); the green Bears turned black
    for the turn give protection from black; and a permanent that has left by
    then gives nothing."""
    game, mine, _giant = _w1g6_elder_table(set_pool)
    elder, bears, _phelddagrif, artifact, _forest = mine
    _w1g6_elder_names(game, artifact)
    assert game._protection_colors(elder) == set() == game._protection_colors(bears)

    game, mine, _giant = _w1g6_elder_table(set_pool)
    elder, bears, _phelddagrif, _artifact, _forest = mine
    bears.metadata["color_override_until_eot"] = "B"
    game._recompute_continuous_effects()
    _w1g6_elder_names(game, bears)
    assert game._protection_colors(elder) == {"B"} == game._protection_colors(bears)

    game, mine, _giant = _w1g6_elder_table(set_pool)
    elder, bears, phelddagrif, _artifact, _forest = mine
    assert game.queue_permanent_ability(
        0, "Samite Elder", ability_index=0, target_permanent_ids=[phelddagrif.permanent_id],
    ).supported
    game.remove_from_battlefield(phelddagrif)
    _w1g6_resolve_stack(game)
    assert game._protection_colors(elder) == set() == game._protection_colors(bears)


def test_w1g6_samite_elders_protection_stops_a_spell_of_the_named_colour(set_pool):
    """What the grant buys: with the green Bears named, a green Giant Growth
    can no longer be aimed at the Elder's creatures and a red Bolt still can."""
    game, mine, _giant = _w1g6_elder_table(set_pool)
    elder, bears, _phelddagrif, _artifact, _forest = mine
    _w1g6_elder_names(game, bears)
    assert game._protection_colors(elder) == {"G"}

    game.players[1].hand.extend(
        _w1g6_card(set_pool, name) for name in ("Giant Growth", "Lightning Bolt")
    )
    refused = game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[elder.permanent_id])
    assert not refused.supported and "illegal target" in refused.details
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[elder.permanent_id],
    ).supported


def _w1g6_dogs_combat(set_pool, choose, *, recolor=None, interactive=(0,)):
    """The opponent's red Hill Giant attacks; seat 0 answers with Guard Dogs
    aimed at it and (when asked) chooses the permanent named *choose*. The
    Giant goes unblocked. Returns the game and the prompts that were owed."""
    game, mine, theirs = _w1g6_table(
        set_pool,
        ["Guard Dogs", "Grizzly Bears", "Mons's Goblin Raiders", "Howling Mine"],
        ["Hill Giant"], mana=True, interactive=interactive,
    )
    giant = theirs[0]
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(1, [game.battlefield_index_of(giant)])[0]
    game.players[0].mana_pool["W"] = 3
    assert game.queue_permanent_ability(
        0, "Guard Dogs", ability_index=0, target_permanent_ids=[giant.permanent_id],
    ).supported
    assert mine[0].tapped and game.players[0].mana_pool["W"] == 0
    if recolor is not None:
        giant.metadata["color_override_until_eot"] = recolor
        game._recompute_continuous_effects()
    game.resolve_top_of_stack()
    owed = [(c.kind, c.player_index) for c in game.pending_choices]
    if owed:
        picked = next(p for p in game.controlled_by(0) if p.card.name == choose)
        assert game.confirm_permanent_choice(0, permanent_id=picked.permanent_id)
    _w1g6_resolve_stack(game)
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(0, {})[0]
    for _ in range(4):
        game.advance_combat_phase()
    return game, owed  # _w1g6_dogs_combat


def test_w1g6_guard_dogs_prevents_the_combat_damage_of_a_creature_sharing_the_chosen_colour(set_pool):
    """"{2}{W}, {T}: Choose a permanent you control. Prevent all combat damage
    target creature would deal this turn if it shares a color with that
    permanent." The creature is a target, announced as the ability is
    activated; the permanent is *chosen as it resolves* (CR 115.10a, 608.2d),
    which is when its controller is asked. The red Goblin is chosen against the
    red Giant: three unblocked combat damage is prevented."""
    dogs = _w1g6_card(set_pool, "Guard Dogs")
    _ability, spec = _w1g6_ability(dogs)
    assert spec == {"kind": "creature"}, "only the creature is announced"

    game, owed = _w1g6_dogs_combat(set_pool, "Mons's Goblin Raiders")
    assert owed == [("permanent_choice", 0)]
    assert game.players[0].life == 20


@_w1g6_pytest.mark.parametrize("choose", ["Grizzly Bears", "Howling Mine", "Guard Dogs"])
def test_w1g6_guard_dogs_prevents_nothing_when_the_colours_do_not_meet(set_pool, choose):
    """A green permanent, a colourless one (CR 105.2: it shares a colour with
    nothing) and the white Dogs themselves: none shares a colour with the red
    Giant, so the ability resolves, the cost is spent and the damage is dealt."""
    game, owed = _w1g6_dogs_combat(set_pool, choose)
    assert owed == [("permanent_choice", 0)]
    assert game.players[0].life == 17


def test_w1g6_guard_dogs_judges_the_target_on_the_colour_it_has_as_it_resolves(set_pool):
    """CR 608.2h, through layer 5: the Giant is turned green after the ability
    is on the stack, so the green Bears share a colour with it by the time the
    condition is asked and the damage is prevented."""
    game, _owed = _w1g6_dogs_combat(set_pool, "Grizzly Bears", recolor="G")
    assert game.players[0].life == 20


def test_w1g6_guard_dogs_resolves_whole_for_a_seat_nobody_asks(set_pool):
    """A headless seat takes the prompt's stated default — the first candidate
    in board order, the white Dogs — with no prompt left owing, and the
    condition is then asked of that pick like any other: white and red do not
    meet, so the damage is dealt."""
    game, owed = _w1g6_dogs_combat(set_pool, None, interactive=())
    assert owed == [] and game.pending_choices == []
    assert game.players[0].life == 17


# -- arrival cards: supported on the day of the ingest, never run until now --


def _w1g6_turn(game, perm, colour):
    """Turn *perm* *colour* for the turn through layer 5's turn-long channel —
    what Aurora Griffin's "becomes white until end of turn" writes."""
    perm.metadata["color_override_until_eot"] = colour
    game._recompute_continuous_effects()
    return perm  # _w1g6_turn


def test_w1g6_honorable_scout_announces_the_opponent_its_count_is_taken_over(set_pool):
    """"When this creature enters, you gain 2 life for each black and/or red
    creature **target opponent** controls." The target sits inside the count's
    noun phrase; the trigger used to reach the stack with no target at all.
    It is announced now ("targets B"), a black-and-red creature counts once
    (CR 105.2: one object of two colours), and the count reads colour through
    the layers — a green creature turned red for the turn is one more."""
    scout = _w1g6_card(set_pool, "Honorable Scout")
    trigger = _w1g6_compile(scout).triggered_abilities[0]
    assert _w1g6_targeting.derive_instruction_spec((trigger.instruction,)) == {
        "kind": "player", "opponents_only": True,
    }

    for recoloured, life in ((False, 26), (True, 28)):
        game, _mine, theirs = _w1g6_table(
            set_pool, ["Scathe Zombies"],
            ["Scathe Zombies", "Hill Giant", "Shivan Zombie", "Grizzly Bears", "Mountain"],
        )
        if recoloured:
            _w1g6_turn(game, theirs[3], "R")
        game.players[0].hand.append(scout)
        assert game.queue_from_hand(0, "Honorable Scout").supported
        _w1g6_resolve_stack(game)
        assert game.players[0].life == life
        assert any(line == "Honorable Scout: targets B" for line in game.log), game.log[-5:]


def test_w1g6_honorable_scouts_controller_chooses_which_opponent_at_three_seats(set_pool):
    """CR 603.3d: the target is chosen as the trigger is put on the stack, and
    with two opponents that is a choice. Both are offered; the one answered —
    C, with three black and/or red creatures to B's one — is the one counted."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(name=name, life=20) for name in ("A", "B", "C")
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.active_player_index = 0
    for seat, names in ((1, ["Scathe Zombies"]), (2, ["Hill Giant", "Scathe Zombies", "Shivan Zombie"])):
        for name in names:
            game._put_permanent_onto_battlefield(
                seat, _W1G6Permanent(card=_w1g6_card(set_pool, name)), None,
            )
    game.players[0].hand.append(_w1g6_card(set_pool, "Honorable Scout"))

    assert game.queue_from_hand(0, "Honorable Scout").supported
    game.resolve_top_of_stack()
    (prompt,) = game.pending_choices
    assert prompt.kind == "trigger_target"
    assert [entry["seat"] for entry in prompt.data["targets"]] == [1, 2]
    assert game.confirm_trigger_target(0, seat=2)
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 26


@_w1g6_pytest.mark.parametrize("pool_code, name, index, written", [
    ("PLS", "Aurora Griffin", 0, ["W"]),
    ("MIR", "Ersatz Gnomes", 1, []),
])
@_w1g6_pytest.mark.parametrize("target", ["Hill Giant", "Bad Moon", "Howling Mine", "Mountain"])
def test_w1g6_target_permanent_becomes_a_colour_reaches_a_permanent_that_is_no_creature(
    set_pool, pool_code, name, index, written, target,
):
    """"{W}: Target **permanent** becomes white until end of turn." (Aurora
    Griffin.) "{T}: Target permanent becomes colorless until end of turn."
    (Ersatz Gnomes, shipped since Mirage.) The picker offers any permanent and
    the resolver held the choice to a creature: an enchantment, an artifact or
    a land was paid for and then dropped as "no creature to recolour". Every
    kind of permanent is recoloured now, and is its own colour again at
    cleanup."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    source = _W1G6Permanent(card=set_pool(pool_code)[name])
    aimed = _W1G6Permanent(card=_w1g6_card(set_pool, target))
    game._put_permanent_onto_battlefield(0, source, None)
    game._put_permanent_onto_battlefield(1, aimed, None)
    source.metadata["summoning_sickness_turn"] = -99
    printed = _w1g6_colors(game, aimed)
    _ability, spec = _w1g6_ability(source.card, index)
    assert spec == {"kind": "permanent"}

    assert game.queue_permanent_ability(
        0, name, ability_index=index, target_permanent_ids=[aimed.permanent_id],
    ).supported
    _w1g6_resolve_stack(game)
    assert _w1g6_colors(game, aimed) == written

    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, aimed) == printed


def test_w1g6_slingshot_goblin_may_only_shoot_a_creature_that_is_blue_right_now(set_pool):
    """"{R}, {T}: This creature deals 2 damage to target blue creature." The
    picker's colour is layer 5's: a red Giant is refused and the blue Elemental
    takes 2; with the two colours swapped for the turn, it is the Giant that
    may be named and the Elemental that may not."""
    _ability, spec = _w1g6_ability(_w1g6_card(set_pool, "Slingshot Goblin"))
    assert spec == {"kind": "creature", "color_filter": "U"}
    for swapped in (False, True):
        game, mine, theirs = _w1g6_table(
            set_pool, ["Slingshot Goblin"], ["Water Elemental", "Hill Giant"],
        )
        elemental, giant = theirs
        if swapped:
            _w1g6_turn(game, elemental, "R")
            _w1g6_turn(game, giant, "U")
        legal, illegal = (giant, elemental) if swapped else (elemental, giant)
        assert not game.queue_permanent_ability(
            0, "Slingshot Goblin", ability_index=0, target_permanent_ids=[illegal.permanent_id],
        ).supported
        assert not mine[0].tapped
        assert game.queue_permanent_ability(
            0, "Slingshot Goblin", ability_index=0, target_permanent_ids=[legal.permanent_id],
        ).supported
        _w1g6_resolve_stack(game)
        assert (legal.damage_marked, illegal.damage_marked) == (2, 0)


def test_w1g6_hunting_drake_tucks_a_creature_that_is_red_or_green_right_now(set_pool):
    """"When this creature enters, put target red or green creature on top of
    its owner's library." With a red Giant and white Lions it takes the Giant;
    with their colours swapped through the layers the Lions are the only legal
    target and are the ones on top of the library."""
    for swapped, tucked in ((False, "Hill Giant"), (True, "Savannah Lions")):
        game, _mine, theirs = _w1g6_table(
            set_pool, [], ["Hill Giant", "Savannah Lions"], interactive=(),
        )
        if swapped:
            _w1g6_turn(game, theirs[0], "W")
            _w1g6_turn(game, theirs[1], "G")
        game.players[0].hand.append(_w1g6_card(set_pool, "Hunting Drake"))
        assert game.queue_from_hand(0, "Hunting Drake").supported
        _w1g6_resolve_stack(game)
        assert [card.name for card in game.players[1].library] == [tucked]
        assert len(list(game.controlled_by(1))) == 1


def test_w1g6_radiant_kavu_prevents_combat_damage_from_whatever_is_blue_or_black_as_it_is_dealt(set_pool):
    """"{R}{G}{W}: Prevent all combat damage blue creatures and black creatures
    would deal this turn." A blue 1/1, a black 2/2 and a red 3/3 attack
    unblocked: 3 of the 6 is prevented. The shield names a class, not a set
    locked in as it resolves (it changes no characteristic, so CR 611.2c does
    not fix one) — the red Giant turned blue afterwards is prevented too."""
    for late_blue, life in ((False, 17), (True, 20)):
        game, _mine, theirs = _w1g6_table(
            set_pool, ["Radiant Kavu"],
            ["Merfolk of the Pearl Trident", "Scathe Zombies", "Hill Giant"], mana=True,
        )
        game.active_player_index = 1
        game._set_phase_and_step("combat", "declare_attackers")
        assert game.declare_attackers(1, [game.battlefield_index_of(p) for p in theirs])[0]
        assert not game.queue_permanent_ability(0, "Radiant Kavu", ability_index=0).supported
        game.players[0].mana_pool.update({"R": 1, "G": 1, "W": 1})
        assert game.queue_permanent_ability(0, "Radiant Kavu", ability_index=0).supported
        _w1g6_resolve_stack(game)
        if late_blue:
            _w1g6_turn(game, theirs[2], "U")
        game._set_phase_and_step("combat", "declare_blockers")
        assert game.declare_blockers(0, {})[0]
        for _ in range(4):
            game.advance_combat_phase()
        assert game.players[0].life == life


@_w1g6_pytest.mark.parametrize("blockers, recolour, size", [
    (["Merfolk of the Pearl Trident"], None, (5, 5)),
    (["Grizzly Bears"], None, (2, 2)),
    (["Merfolk of the Pearl Trident", "Scathe Zombies"], None, (5, 5)),
    (["Grizzly Bears"], "U", (5, 5)),
    (["Merfolk of the Pearl Trident"], "G", (2, 2)),
])
def test_w1g6_amphibious_kavu_grows_once_when_a_blue_or_black_creature_blocks_it(
    set_pool, blockers, recolour, size,
):
    """"Whenever this creature blocks or becomes blocked by one or more blue
    and/or black creatures, this creature gets +3/+3 until end of turn."
    "One or more": two such blockers are one trigger and +3/+3, not +6/+6. And
    the blocker's colour is the one it has as blocks are declared — green
    Bears turned blue set it off, a Merfolk turned green does not."""
    game, mine, theirs = _w1g6_table(set_pool, ["Amphibious Kavu"], blockers)
    kavu = mine[0]
    if recolour is not None:
        _w1g6_turn(game, theirs[0], recolour)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(kavu)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {
        game.battlefield_index_of(blocker): [game.battlefield_index_of(kavu)]
        for blocker in theirs
    })[0]
    assert len(game.stack) == (1 if size == (5, 5) else 0)
    _w1g6_resolve_stack(game)
    assert (kavu.effective_power, kavu.effective_toughness) == size


def test_w1g6_amphibious_kavu_grows_when_it_blocks_a_creature_that_is_black_right_now(set_pool):
    """The *blocks* half: blocking a red Giant does nothing, and blocking the
    same Giant turned black for the turn is +3/+3."""
    for recolour, size in ((None, (2, 2)), ("B", (5, 5))):
        game, mine, theirs = _w1g6_table(set_pool, ["Amphibious Kavu"], ["Hill Giant"])
        kavu, giant = mine[0], theirs[0]
        if recolour is not None:
            _w1g6_turn(game, giant, recolour)
        game.active_player_index = 1
        game._set_phase_and_step("combat", "declare_attackers")
        assert game.declare_attackers(1, [game.battlefield_index_of(giant)])[0]
        game._set_phase_and_step("combat", "declare_blockers")
        assert game.declare_blockers(0, {
            game.battlefield_index_of(kavu): [game.battlefield_index_of(giant)],
        })[0]
        _w1g6_resolve_stack(game)
        assert (kavu.effective_power, kavu.effective_toughness) == size


def test_w1g6_quirion_dryad_grows_once_for_each_of_its_controllers_nongreen_spells(set_pool):
    """"Whenever you cast a spell that's white, blue, black, or red, put a
    +1/+1 counter on this creature." (Shipped since M21.) A red Bolt and a
    white creature spell each grow it; a mono-green Growth and a colourless
    artifact do not; a red-**and**-green spell is one spell and one counter;
    and an opponent's red spell is not "you cast"."""
    game, mine, theirs = _w1g6_table(set_pool, ["Quirion Dryad"], ["Hill Giant"])
    dryad, giant = mine[0], theirs[0]
    for name, announced, grows in (
        ("Lightning Bolt", {"target_player_index": 1}, 1),
        ("Giant Growth", {"target_permanent_ids": [dryad.permanent_id]}, 0),
        ("Shivan Wurm", {}, 1),
        ("Howling Mine", {}, 0),
        ("Disciple of Kangee", {}, 1),
    ):
        game.players[0].hand.append(_w1g6_card(set_pool, name))
        before = dryad.effective_power
        assert game.queue_from_hand(0, name, **announced).supported, name
        _w1g6_resolve_stack(game)
        game.resolve_cleanup_step(0)
        assert dryad.effective_power - before == grows, name

    game.players[1].hand.append(_w1g6_card(set_pool, "Lightning Bolt"))
    before = dryad.effective_power
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_resolve_stack(game)
    assert dryad.effective_power == before


@_w1g6_pytest.mark.parametrize("recolour, drawn", [
    (None, 2), (("Hill Giant", "B"), 3), (("Scathe Zombies", "G"), 1),
])
def test_w1g6_pygmy_kavu_draws_for_each_creature_an_opponent_has_that_is_black_right_now(
    set_pool, recolour, drawn,
):
    """"When this creature enters, draw a card for each black creature your
    opponents control." Two black creatures across the table (the black
    enchantment and its controller's own Zombies are not counted); a Giant
    turned black is a third, and a Zombie turned green is one fewer."""
    game, _mine, theirs = _w1g6_table(
        set_pool, ["Scathe Zombies"],
        ["Scathe Zombies", "Drudge Skeletons", "Hill Giant", "Bad Moon"],
    )
    if recolour is not None:
        _w1g6_turn(game, next(p for p in theirs if p.card.name == recolour[0]), recolour[1])
    game.players[0].library.extend([_w1g6_card(set_pool, "Forest")] * 6)
    game.players[0].hand.append(_w1g6_card(set_pool, "Pygmy Kavu"))
    assert game.queue_from_hand(0, "Pygmy Kavu").supported
    _w1g6_resolve_stack(game)
    assert len(game.players[0].hand) == drawn


def test_w1g6_caldera_kavu_pumps_for_black_and_takes_a_colour_chosen_at_resolution(set_pool):
    """"{1}{B}: This creature gets +1/+1 until end of turn. / {G}: This
    creature becomes the color of your choice until end of turn." Each ability
    costs what it prints; the colour is asked as the second resolves
    (CR 608.2d), not read off the activation; both wear off at cleanup."""
    game, mine, _theirs = _w1g6_table(set_pool, ["Caldera Kavu"], [], mana=True)
    kavu = mine[0]
    assert not game.queue_permanent_ability(0, "Caldera Kavu", ability_index=0).supported
    game.players[0].mana_pool.update({"B": 1, "R": 1, "G": 1})
    assert game.queue_permanent_ability(0, "Caldera Kavu", ability_index=0).supported
    _w1g6_resolve_stack(game)
    assert (kavu.effective_power, kavu.effective_toughness) == (3, 3)

    assert game.queue_permanent_ability(
        0, "Caldera Kavu", ability_index=1, mana_color="W",
    ).supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert game.confirm_color_choice(0, "U")
    assert _w1g6_colors(game, kavu) == ["U"]

    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, kavu) == ["R"]
    assert (kavu.effective_power, kavu.effective_toughness) == (2, 2)


# --- W1G7: triggers and cast rules ---
from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.counter_conditions import cant_be_countered as _w1g7_cant_be_countered
from engine.counter_conditions import (
    uncounterable_class_line as _w1g7_uncounterable_class_line,
)
from engine.models import CardDefinition as _W1G7Card
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_card(name, type_line, text="", *, cost="{1}", colors=(), pt=None):
    """A fixture card with exactly the printed text a creature test needs."""
    raw = {"name": name, "type_line": type_line}
    if pt is not None:
        raw["power"], raw["toughness"] = str(pt[0]), str(pt[1])
    built = _W1G7Card(
        name=name, mana_cost=cost, cmc=float(cost.count("{")),
        type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(), raw=raw,
    )
    return built


def _w1g7_table(mine=(), theirs=(), *, hands=((), ()), interactive=()):
    """Two seats with costs off; the creature under test on seat 0 unless the
    test puts it elsewhere."""
    filler = _w1g7_card("W1G7 Filler", "Creature - Test", pt=(1, 1))
    duel = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", battlefield=list(mine), hand=list(hands[0]),
            library=[filler] * 8,
        ),
        _W1G7PlayerState(
            name="P2", battlefield=list(theirs), hand=list(hands[1]),
            library=[filler] * 8,
        ),
    ])
    duel.enforce_mana_costs = False
    duel.interactive_seats = set(interactive)
    return duel


# Gaea's Herald — "Creature spells can't be countered." The board half of
# Scragnoth's immunity: a permanent's static about every spell of a type,
# asked by the one counter path at CR 608.2 beside the spell's own line.


def _w1g7_counter_a_spell(set_pool, spell, *, counter="Counterspell",
                          herald_seat=0, **cast):
    """Seat 0 casts *spell*, seat 1 answers with *counter*; the stack drains."""
    herald = _W1G7Permanent(card=set_pool("PLS")["Gaea's Herald"])
    sides = [[], []]
    if herald_seat is not None:
        sides[herald_seat].append(herald)
    answer = next(
        set_pool(code)[counter]
        for code in ("LEA", "ICE", "MIR", "INV")
        if counter in set_pool(code)
    )
    duel = _w1g7_table(sides[0], sides[1], hands=((spell,), (answer,)))
    assert duel.queue_from_hand(0, spell.name).supported
    # CR 115.1: the counter is a legal cast — "target spell" is not "target
    # spell that can be countered".
    assert duel.queue_from_hand(1, counter, target_player_index=0, **cast).supported
    _w1g7_resolve_stack(duel)
    duel.auto_resolve_pending_choices()
    return duel


def test_w1g7_gaeas_herald_is_supported_through_the_counter_path(set_pool):
    herald = set_pool("PLS")["Gaea's Herald"]
    program = _w1g7_compile(herald)
    assert program.supported, program.reason
    assert _w1g7_uncounterable_class_line(herald.oracle_text) == "creature"
    # The narrower sentence is a different card and must refuse, not widen.
    assert _w1g7_uncounterable_class_line(
        "Creature spells you control can't be countered."
    ) is None


def test_w1g7_gaeas_herald_keeps_a_creature_spell_from_being_countered(set_pool):
    bears = set_pool("LEA")["Grizzly Bears"]
    duel = _w1g7_counter_a_spell(set_pool, bears)

    assert "Grizzly Bears" in [p.card.name for p in duel.players[0].battlefield]
    assert duel.players[0].graveyard == []
    assert [c.name for c in duel.players[1].graveyard] == ["Counterspell"]
    assert any("can't be countered (Gaea's Herald)" in line for line in duel.log)


def test_w1g7_gaeas_herald_protects_every_players_creature_spells(set_pool):
    """The sentence names nobody: an opponent's Herald protects my creature
    spell from that same opponent's Counterspell."""
    bears = set_pool("LEA")["Grizzly Bears"]
    duel = _w1g7_counter_a_spell(set_pool, bears, herald_seat=1)

    assert [p.card.name for p in duel.players[0].battlefield] == ["Grizzly Bears"]


def test_w1g7_gaeas_herald_reads_every_type_an_artifact_creature_has(set_pool):
    """CR 205.2: an artifact creature spell is a creature spell."""
    golem = _w1g7_card(
        "W1G7 Golem", "Artifact Creature - Golem", cost="{3}", pt=(3, 3)
    )
    duel = _w1g7_counter_a_spell(set_pool, golem)

    assert "W1G7 Golem" in [p.card.name for p in duel.players[0].battlefield]


def test_w1g7_gaeas_herald_says_nothing_about_a_noncreature_spell(set_pool):
    """The narrowing is the card: dropped, the Herald would make every spell
    in the game uncounterable."""
    rock = _w1g7_card("W1G7 Rock", "Artifact", cost="{2}")
    duel = _w1g7_counter_a_spell(set_pool, rock)

    assert [c.name for c in duel.players[0].graveyard] == ["W1G7 Rock"]
    assert "W1G7 Rock" not in [p.card.name for p in duel.players[0].battlefield]


def test_w1g7_gaeas_herald_arms_no_payment_for_a_spell_nothing_can_counter(set_pool):
    """Asked before Power Sink's "unless its controller pays" — a player asked
    to pay to prevent something that cannot happen would pay."""
    bears = set_pool("LEA")["Grizzly Bears"]
    duel = _w1g7_counter_a_spell(set_pool, bears, counter="Power Sink", x_value=3)

    assert duel.pending_choices == []
    assert "Grizzly Bears" in [p.card.name for p in duel.players[0].battlefield]


def test_w1g7_gaeas_herald_does_not_protect_itself_on_the_stack(set_pool):
    """A static of a *permanent* (CR 113.6): the Herald on the stack is not on
    the battlefield, so nothing is yet saying its sentence."""
    herald = set_pool("PLS")["Gaea's Herald"]
    duel = _w1g7_counter_a_spell(set_pool, herald, herald_seat=None)

    assert [c.name for c in duel.players[0].graveyard] == ["Gaea's Herald"]
    assert duel.players[0].battlefield == []


def test_w1g7_gaeas_herald_stops_protecting_once_it_has_left(set_pool):
    herald = _W1G7Permanent(card=set_pool("PLS")["Gaea's Herald"])
    bears = set_pool("LEA")["Grizzly Bears"]
    duel = _w1g7_table([herald], [])
    assert _w1g7_cant_be_countered(duel, bears) is not None

    duel.remove_from_battlefield(herald)

    assert _w1g7_cant_be_countered(duel, bears) is None


# Meddling Mage — "As this creature enters, choose a nonland card name." /
# "Spells with the chosen name can't be cast." Null Chamber's machinery with one
# chooser, CR 201.4a's "nonland" bound and no land half: the entry choice is
# Runed Halo's prompt read as a pattern, and the ban is a second row of the
# chosen-name table read by the same cast gate.


def _w1g7_mage_table(set_pool, *, mine=(), theirs=(), interactive=(0,)):
    """Seat 0 holds a Meddling Mage and casts it; the entry prompt is owed."""
    mage = set_pool("PLS")["Meddling Mage"]
    duel = _w1g7_table(
        [], [], hands=((mage, *mine), tuple(theirs)), interactive=interactive
    )
    assert duel.cast_from_hand(0, "Meddling Mage").supported
    duel.resolve_stack(pause_for_choices=True)
    entered = next(
        p for p in duel.players[0].battlefield if p.card.name == "Meddling Mage"
    )
    return duel, entered


def _w1g7_split_card(set_pool):
    from engine.faces import face_cards

    whole = set_pool("INV")["Stand // Deliver"]
    first, second = face_cards(whole)
    return whole, first.name, second.name


def test_w1g7_meddling_mage_is_supported_by_both_of_its_lines(set_pool):
    from engine.cast_restrictions import chosen_name_ban_row
    from engine.enter_effects import chooses_card_name_on_enter, enter_effect_line

    mage = set_pool("PLS")["Meddling Mage"]
    program = _w1g7_compile(mage)
    assert program.supported, program.reason

    entry, ban = mage.oracle_text.split("\n")
    assert enter_effect_line(entry) == "chooses a card name as it enters"
    assert chooses_card_name_on_enter(entry.lower()) == {
        "excluded_card_type": "land"
    }
    # Spells only: the row says so, and the gate reads it.
    assert chosen_name_ban_row(ban) == ("chosen_card_name", False)
    # A longer bound is a different card and refuses rather than being read as
    # the unbounded choice with its exclusion dropped.
    assert chooses_card_name_on_enter(
        "as this creature enters, choose a card name other than a basic land "
        "card name."
    ) is None


def test_w1g7_meddling_mage_asks_its_controller_for_one_nonland_name(set_pool):
    bolt = set_pool("LEA")["Lightning Bolt"]
    forest = set_pool("LEA")["Forest"]
    duel, entered = _w1g7_mage_table(set_pool, theirs=(bolt,))
    duel.players[1].graveyard.extend([forest, bolt])

    (asked,) = duel.pending_choices
    assert (asked.kind, asked.player_index) == ("enter_choice", 0)
    assert asked.data["needs_card_name"]
    assert asked.data["excluded_card_type"] == "land"

    # CR 201.4a: a land's name is not a nonland card name. Refused, not
    # repaired — the prompt stays owed.
    assert not duel.confirm_enter_choice(0, card_name="Forest")
    assert [c.kind for c in duel.pending_choices] == ["enter_choice"]

    assert duel.confirm_enter_choice(0, card_name="Lightning Bolt")
    assert entered.metadata["chosen_card_name"] == "Lightning Bolt"
    assert duel.pending_choices == []


def test_w1g7_meddling_mage_stops_every_player_casting_the_named_spell(set_pool):
    """CR 601.3: the sentence names nobody, so it binds the Mage's own
    controller as surely as the opponent."""
    bolt = set_pool("LEA")["Lightning Bolt"]
    bears = set_pool("LEA")["Grizzly Bears"]
    duel, _entered = _w1g7_mage_table(
        set_pool, mine=(bolt,), theirs=(bolt, bears)
    )
    assert duel.confirm_enter_choice(0, card_name="Lightning Bolt")

    theirs = duel.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert not theirs.supported and "Meddling Mage" in theirs.details
    mine = duel.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not mine.supported and "Meddling Mage" in mine.details
    assert [seat.life for seat in duel.players] == [20, 20]
    assert len(duel.players[1].hand) == 2, "a refused cast spends nothing"

    # The control: a card nobody named is unaffected.
    assert duel.cast_from_hand(1, "Grizzly Bears").supported


def test_w1g7_meddling_mage_stops_one_half_of_a_split_card_and_not_the_other(
    set_pool,
):
    """CR 201.4b names a split card by one half; CR 709.3a evaluates only the
    half being cast. Naming the first half leaves the second castable, and the
    joined spelling is the name of no spell and is refused as an answer."""
    from engine.cast_restrictions import chosen_name_ban
    from engine.faces import face_cards

    whole, first, second = _w1g7_split_card(set_pool)
    duel, entered = _w1g7_mage_table(set_pool, theirs=(whole, whole))

    assert not duel.confirm_enter_choice(0, card_name=whole.name)
    assert duel.confirm_enter_choice(0, card_name=first)
    assert entered.metadata["chosen_card_name"] == first

    stopped = duel.cast_from_hand(1, first)
    assert not stopped.supported and "Meddling Mage" in stopped.details
    halves = {face.name: face for face in face_cards(whole)}
    assert chosen_name_ban(duel, halves[first]) == "Meddling Mage"
    assert chosen_name_ban(duel, halves[second]) is None


def test_w1g7_meddling_mage_lifts_its_ban_when_it_leaves(set_pool):
    bolt = set_pool("LEA")["Lightning Bolt"]
    duel, entered = _w1g7_mage_table(set_pool, theirs=(bolt,))
    assert duel.confirm_enter_choice(0, card_name="Lightning Bolt")
    refused = duel.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert not refused.supported

    duel.remove_from_battlefield(entered)

    assert duel.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert duel.players[0].life == 17


def test_w1g7_meddling_mage_says_nothing_about_a_land_drop(set_pool):
    """"**Spells** … can't be cast": a land is played, never cast (CR 305.1).
    The name is forced onto the record here because the prompt would refuse it
    — the row, not the prompt, is what this test holds."""
    forest = set_pool("LEA")["Forest"]
    mage = _W1G7Permanent(card=set_pool("PLS")["Meddling Mage"])
    mage.metadata["chosen_card_name"] = "Forest"
    duel = _w1g7_table([mage], [], hands=((forest,), ()))
    duel.start_turn(0)

    assert duel.cast_from_hand(0, "Forest").supported


def test_w1g7_meddling_mage_names_something_for_a_seat_nobody_asks(set_pool):
    """A headless seat names the nonland card it last saw an opponent use —
    never a land, and never nothing while there is something to see."""
    bolt = set_pool("LEA")["Lightning Bolt"]
    forest = set_pool("LEA")["Forest"]
    mage = set_pool("PLS")["Meddling Mage"]
    duel = _w1g7_table([], [], hands=((mage,), (bolt,)))
    duel.players[1].graveyard.extend([bolt, forest])

    assert duel.cast_from_hand(0, "Meddling Mage").supported
    _w1g7_resolve_stack(duel)
    duel.auto_resolve_pending_choices()

    entered = next(
        p for p in duel.players[0].battlefield if p.card.name == "Meddling Mage"
    )
    assert entered.metadata["chosen_card_name"] == "Lightning Bolt"
    # A chosen name is public: the log says it, because for this seat no prompt
    # is ever answered and nothing else would.
    assert "P1 named Lightning Bolt for Meddling Mage" in duel.log
    refused = duel.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert not refused.supported


def test_w1g7_meddling_mage_takes_the_named_card_off_the_ais_proposals(set_pool):
    """A refused cast spends nothing, so a seat that kept proposing the named
    card would do nothing else for as long as the Mage stood."""
    from engine.ai_policy import _can_cast_with_targets

    bears = set_pool("LEA")["Grizzly Bears"]
    wolves = set_pool("LEA")["Timber Wolves"]
    mage = _W1G7Permanent(card=set_pool("PLS")["Meddling Mage"])
    mage.metadata["chosen_card_name"] = "Grizzly Bears"
    duel = _w1g7_table([mage], [], hands=((), (bears, wolves)))

    assert not _can_cast_with_targets(duel, 1, bears)
    assert _can_cast_with_targets(duel, 1, wolves)
