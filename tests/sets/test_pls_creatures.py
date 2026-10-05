"""Planeshift creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
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
