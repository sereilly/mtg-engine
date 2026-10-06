"""Planeshift artifacts.

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


# --- W1G8: damage and the odd ones ---
#
# Skyship Weatherlight arrived *supported* with its second ability hollow, and
# the hole was two layers deep. The activated line had no production ("Choose a
# card at random that was exiled with <this>. Put that card into its owner's
# hand."), and beneath it the entry trigger never wrote the CR 607.2a link the
# line reads: the exile search recorded a pile on its permanent only when the
# pile was printed face down (Mangara's Tome).

import random as _w1g8a_random  # noqa: E402

from engine import Game as _w1g8a_Game, PlayerState as _w1g8a_Player  # noqa: E402
from engine.card_loader import (load_cards as _w1g8a_load,  # noqa: E402
                                manifest_set_path as _w1g8a_path)
from engine.linked_exile import linked_entries as _w1g8a_linked  # noqa: E402
from engine.models import (CardDefinition as _w1g8a_Card,  # noqa: E402
                           Permanent as _w1g8a_Permanent)
from engine.oracle import compile_card_oracle as _w1g8a_compile  # noqa: E402
from engine.targeting import derive_activation_spec as _w1g8a_activation_spec  # noqa: E402

from tests.helpers import resolve_stack as _w1g8a_resolve_stack  # noqa: E402


def _w1g8a_lea():
    return {card.name: card for card in _w1g8a_load(_w1g8a_path("LEA"))}


def _w1g8a_library(lea):
    """Two creatures, two artifacts and three cards that are neither."""
    return [
        lea[name] for name in (
            "Hill Giant", "Island", "Sol Ring", "Lightning Bolt",
            "Grizzly Bears", "Island", "Juggernaut",
        )
    ]  # W1G8 artifacts: a library to search


def _w1g8a_game(hand, library, *, interactive=()):
    filler = _w1g8a_Card(
        name="Filler", mana_cost="{3}", cmc=3.0, type_line="Sorcery",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Filler", "type_line": "Sorcery"},
    )
    game = _w1g8a_Game(players=[
        _w1g8a_Player(name="P0", hand=list(hand), library=list(library)),
        _w1g8a_Player(name="P1", library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._close_current_priority_step()
    return game  # W1G8 artifacts: the game


def _w1g8a_launch(game):
    """Cast the Weatherlight and answer its entry search the headless way."""
    cast = game.cast_from_hand(0, "Skyship Weatherlight")
    assert cast.supported, cast.details
    _w1g8a_resolve_stack(game)
    game.auto_resolve_pending_choices()
    ship = next(
        perm for perm in game.controlled_by(0)
        if perm.card.name == "Skyship Weatherlight"
    )
    ship.metadata["summoning_sickness_turn"] = -99
    return ship  # W1G8 artifacts: the ship


def _w1g8a_activate(game, ship):
    ship.tapped = False
    used = game.activate_permanent_ability(
        0, "Skyship Weatherlight", ability_index=0
    )
    assert used.supported, used.details
    _w1g8a_resolve_stack(game)  # W1G8 artifacts: one activation


def test_w1g8_skyship_weatherlight_has_no_hollow_ability(set_pool):
    """Both abilities compile to an instruction, and the second targets
    nothing — the card is picked at random, not chosen (CR 115.1)."""
    program = _w1g8a_compile(set_pool("PLS")["Skyship Weatherlight"])

    assert program.supported
    (ability,) = program.activated_abilities
    assert ability.supported and ability.instruction is not None
    assert ability.instruction.payload == {
        "zone": "hand", "one_of": True, "at_random": True,
    }
    assert ability.cost.requires_tap and ability.cost.mana["generic"] == 4
    assert _w1g8a_activation_spec(ability) is None
    (trigger,) = program.triggered_abilities
    assert trigger.instruction is not None


def test_w1g8_skyship_weatherlight_links_what_its_entry_exiled(set_pool):
    """The entry search exiles artifact and/or creature cards and nothing else,
    shuffles, and records the pile *on the Weatherlight* — which is the only
    thing its second ability can read."""
    lea = _w1g8a_lea()
    game = _w1g8a_game(
        [set_pool("PLS")["Skyship Weatherlight"]], _w1g8a_library(lea)
    )

    ship = _w1g8a_launch(game)

    exiled = sorted(card.name for card in game.players[0].exile)
    eligible = ["Grizzly Bears", "Hill Giant", "Juggernaut", "Sol Ring"]
    # A seat nobody asks keeps the three it most wants, not all four (PLS
    # W2G5, `ai_policy.SLOW_RETURN_PILE_SIZE`): the pile comes back one card
    # per {4}, {T}. Which three is the policy's; that they are artifacts and
    # creatures, linked to the ship, is the card's.
    assert len(exiled) == 3 and set(exiled) <= set(eligible)
    assert sorted(entry["card"].name for entry in _w1g8a_linked(ship)) == exiled
    assert not any(entry.get("face_down") for entry in _w1g8a_linked(ship)), (
        "the cards are exiled face up"
    )
    assert sorted(card.name for card in game.players[0].library) == sorted(
        ["Island", "Island", "Lightning Bolt"]
        + [name for name in eligible if name not in exiled]
    )


def test_w1g8_skyship_weatherlight_any_number_is_the_searchers_choice(set_pool):
    """"Any number of": an interactive seat is asked, may take two of the four,
    and may not take a card that is neither an artifact nor a creature."""
    lea = _w1g8a_lea()
    game = _w1g8a_game(
        [set_pool("PLS")["Skyship Weatherlight"]], _w1g8a_library(lea),
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Skyship Weatherlight").supported
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()
    (prompt,) = game.pending_choices_of("search_exile_cards", 0)
    assert prompt.data["card_types"] == ("artifact", "creature")
    library = game.players[0].library

    island = next(i for i, card in enumerate(library) if card.name == "Island")
    assert not game.confirm_search_exile(0, [{"zone": "library", "index": island}])
    picks = [
        {"zone": "library", "index": index}
        for index, card in enumerate(library)
        if card.name in ("Sol Ring", "Juggernaut")
    ]
    assert game.confirm_search_exile(0, picks)
    _w1g8a_resolve_stack(game)

    ship = next(iter(game.controlled_by(0)))
    assert sorted(entry["card"].name for entry in _w1g8a_linked(ship)) == [
        "Juggernaut", "Sol Ring",
    ]
    assert len(game.players[0].library) == 5


def test_w1g8_skyship_weatherlight_returns_one_card_at_random_each_time(set_pool):
    """One card per activation, out of the linked pile and into its owner's
    hand; the rest stay exiled with the ship. One activation per card empties
    the pile and one more finds nothing."""
    lea = _w1g8a_lea()
    game = _w1g8a_game(
        [set_pool("PLS")["Skyship Weatherlight"]], _w1g8a_library(lea)
    )
    ship = _w1g8a_launch(game)
    pile = sorted(card.name for card in game.players[0].exile)

    assert pile, "the entry search exiled something"
    for expected_left in range(len(pile) - 1, -1, -1):
        _w1g8a_activate(game, ship)
        assert len(_w1g8a_linked(ship)) == expected_left
        assert len(game.players[0].exile) == expected_left
    assert sorted(card.name for card in game.players[0].hand) == pile
    assert ship.tapped, "{T} is part of the cost"

    _w1g8a_activate(game, ship)
    assert len(game.players[0].hand) == len(pile)
    assert "nothing is exiled with Skyship Weatherlight" in game.log[-2]


def test_w1g8_skyship_weatherlight_picks_through_the_seeded_rng(set_pool):
    """Chance, and reproducible chance: the same seed returns the same card
    (a seeded AI simulation must replay exactly), and over a run of seeds more
    than one card comes back first — it is not "the first entry"."""
    lea = _w1g8a_lea()
    ship_card = set_pool("PLS")["Skyship Weatherlight"]

    def first_pick(seed):
        _w1g8a_random.seed(seed)
        game = _w1g8a_game([ship_card], _w1g8a_library(lea))
        ship = _w1g8a_launch(game)
        _w1g8a_activate(game, ship)
        (card,) = game.players[0].hand
        return card.name

    assert first_pick(11) == first_pick(11)
    assert len({first_pick(seed) for seed in range(12)}) > 1


def test_w1g8_skyship_weatherlight_reads_only_its_own_pile(set_pool):
    """CR 607.2a / CR 400.7: the pile is the cards *this object's* entry
    trigger exiled. A card some other effect exiled is not in it, and a
    Weatherlight that left and came back is a new object with an empty set —
    the old cards stay exiled and nothing can fetch them."""
    lea = _w1g8a_lea()
    ship_card = set_pool("PLS")["Skyship Weatherlight"]
    game = _w1g8a_game([ship_card], [lea["Island"], lea["Sol Ring"]])
    stranger = lea["Juggernaut"]
    game.players[0].exile.append(stranger)

    ship = _w1g8a_launch(game)
    assert [entry["card"].name for entry in _w1g8a_linked(ship)] == ["Sol Ring"]
    _w1g8a_activate(game, ship)
    assert [card.name for card in game.players[0].hand] == ["Sol Ring"]
    _w1g8a_activate(game, ship)
    assert stranger in game.players[0].exile, "never exiled with the ship"

    game = _w1g8a_game([ship_card], [lea["Island"], lea["Sol Ring"]])
    first = _w1g8a_launch(game)
    game.remove_from_battlefield(first)
    returned = _w1g8a_Permanent(card=ship_card)
    game.players[0].battlefield.append(returned)
    game._settle()
    returned.metadata["summoning_sickness_turn"] = -99

    _w1g8a_activate(game, returned)
    assert game.players[0].hand == []
    assert [card.name for card in game.players[0].exile] == ["Sol Ring"]


# --- W1G5: lands and mana ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.land_types import change_land_type as _w1g5_change_land_type
from engine.mana_could_produce import LANDS_FILTER_KEY as _W1G5_LANDS_FILTER_KEY
from engine.mana_could_produce import (
    mana_lands_could_produce as _w1g5_lands_could_produce,
)
from engine.mana_payment import is_mana_ability as _w1g5_is_mana_ability
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_compass(set_pool, *, mine=(), theirs=(), hand=(), interactive=(), costs=False):
    """An untapped Star Compass under seat 0 beside *mine*, facing *theirs*.
    Names resolve in Planeshift, then Alpha, then Tempest. Nothing here
    *enters* — the Compass's "enters tapped" has its own test — so the board
    is the one the test names."""
    pools = [set_pool("PLS"), set_pool("LEA"), set_pool("TMP")]

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(n)) for n in (*mine, "Star Compass")],
        hand=[card(name) for name in hand],
    )
    you = _W1G5PlayerState(
        name="W1G5-B", battlefield=[_W1G5Permanent(card=card(n)) for n in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = costs
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    (compass,) = [p for p in game.controlled_by(0) if p.card.name == "Star Compass"]
    return game, compass  # _w1g5_compass


def _w1g5_compass_tap(game, compass, color=None):
    """Activate the Compass naming *color*; the engine's answer."""
    return game.activate_permanent_ability(
        0, "Star Compass",
        permanent_index=game.battlefield_index_of(compass), mana_color=color,
    )  # _w1g5_compass_tap


def _w1g5_floating(game, seat: int = 0) -> dict[str, int]:
    return {
        symbol: amount
        for symbol, amount in game.players[seat].mana_pool.items() if amount
    }  # _w1g5_floating (artifacts)


def test_w1g5_star_compass_carries_whose_lands_and_which(set_pool):
    """"{T}: Add one mana of any color that a basic land you control could
    produce." The phrase was two literal sentences, one per shipped card, so
    this card's one adjective refused its whole line. Read as a noun phrase,
    whose lands is the board and which lands is the narrowing beside it —
    and the cards that shipped before it carry no narrowing at all."""
    (ability,) = _w1g5_compile(set_pool("PLS")["Star Compass"]).activated_abilities
    assert ability.supported and _w1g5_is_mana_ability(ability)
    payload = ability.instruction.payload
    assert payload["any_color_from"] == "controlled_lands"
    assert payload[_W1G5_LANDS_FILTER_KEY] == {"supertypes": ["basic"]}

    explorer = _w1g5_compile(set_pool("PLS")["Quirion Explorer"])
    (theirs,) = explorer.activated_abilities
    assert theirs.instruction.payload["any_color_from"] == "opponent_lands"
    assert _W1G5_LANDS_FILTER_KEY not in theirs.instruction.payload
    (pool,) = _w1g5_compile(set_pool("TMP")["Reflecting Pool"]).activated_abilities
    assert pool.instruction.payload["any_type_from_lands"] == "controlled_lands"
    assert _W1G5_LANDS_FILTER_KEY not in pool.instruction.payload


def test_w1g5_star_compass_enters_tapped(set_pool):
    """"This artifact enters tapped." Cast for real and resolved."""
    game, _already = _w1g5_compass(set_pool, hand=["Star Compass"])
    assert game.cast_from_hand(0, "Star Compass").supported
    _w1g5_resolve_stack(game)
    (_old, new) = [p for p in game.controlled_by(0) if p.card.name == "Star Compass"]
    assert new.tapped


def test_w1g5_star_compass_makes_a_colour_of_a_basic_land_you_control(set_pool):
    """Island and Swamp: blue or black as named, and a colour neither makes is
    not made. One mana, no stack (CR 605.3b)."""
    for asked, made in (("U", "U"), ("B", "B")):
        game, compass = _w1g5_compass(set_pool, mine=["Island", "Swamp"])
        assert _w1g5_compass_tap(game, compass, asked).supported
        assert compass.tapped and not game.stack
        assert _w1g5_floating(game) == {made: 1}

    game, compass = _w1g5_compass(set_pool, mine=["Island", "Swamp"])
    _w1g5_compass_tap(game, compass, "G")
    made = _w1g5_floating(game)
    assert sum(made.values()) == 1 and set(made) <= {"U", "B"}, made


def test_w1g5_star_compass_reads_basic_lands_and_only_yours(set_pool):
    """Every word of the phrase narrows. **Basic**: a Lair makes three colours
    and an Underground Sea has two basic land *types*, and neither is a basic
    land (CR 205.4a is a supertype) — beside either alone the Compass makes
    nothing. **You control**: an opponent's Forest offers nothing. No basic
    land at all: the ability is still activatable, the Compass taps, and no
    mana is produced (CR 106.7)."""
    for board in (
        {"mine": ["Crosis's Catacombs"]},
        {"mine": ["Underground Sea"]},
        {"theirs": ["Forest"]},
        {},
    ):
        game, compass = _w1g5_compass(set_pool, **board)
        result = _w1g5_compass_tap(game, compass, "U")
        assert result.supported, (board, result)
        assert compass.tapped
        assert _w1g5_floating(game) == {}, board

    game, compass = _w1g5_compass(
        set_pool, mine=["Crosis's Catacombs", "Forest"], theirs=["Mountain"],
    )
    _w1g5_compass_tap(game, compass, "R")
    assert _w1g5_floating(game) == {"G": 1}, "only the basic Forest counts"


def test_w1g5_star_compass_reads_what_the_basic_land_makes_now(set_pool):
    """"Could produce" is what the land's abilities would make if they resolved
    now (CR 106.7), not what its card prints: a basic Island whose type an
    effect set to Swamp is still basic and makes {B} (CR 305.7), so the Compass
    beside it offers black and not blue."""
    game, compass = _w1g5_compass(set_pool, mine=["Island"])
    (island,) = [p for p in game.controlled_by(0) if p.card.name == "Island"]
    _w1g5_change_land_type(island, "swamp", source="w1g5-test")

    assert _w1g5_lands_could_produce(
        game, 0, "controlled_lands", colors_only=True,
        narrowing={"supertypes": ["basic"]}, source=compass,
    ) == frozenset({"B"})
    _w1g5_compass_tap(game, compass, "U")
    assert _w1g5_floating(game) == {"B": 1}


def test_w1g5_star_compass_asks_among_the_colours_on_offer(set_pool):
    """An interactive seat that names no colour is asked — and the list is the
    board's, not CR 105.1's five: green is refused, black is taken."""
    game, compass = _w1g5_compass(set_pool, mine=["Island", "Swamp"], interactive={0})
    assert _w1g5_compass_tap(game, compass).supported
    prompt = game.pending_choice_of("mana_color_choice", 0)
    assert prompt is not None and sorted(prompt.data["colors"]) == ["B", "U"]
    assert _w1g5_floating(game) == {}

    assert not game.confirm_mana_color_choice(0, "G")
    assert game.confirm_mana_color_choice(0, "B")
    assert _w1g5_floating(game) == {"B": 1}


def test_w1g5_star_compass_pays_for_a_real_spell(set_pool):
    """Costs enforced, a Swamp on the battlefield and nothing else untapped to
    pay with: the Compass's black mana casts Will-o'-the-Wisp, and the Swamp is
    still untapped afterwards."""
    game, compass = _w1g5_compass(
        set_pool, mine=["Swamp"], hand=["Will-o'-the-Wisp"], costs=True,
    )
    assert not game.cast_from_hand(0, "Will-o'-the-Wisp").supported
    assert _w1g5_compass_tap(game, compass, "B").supported
    assert game.cast_from_hand(0, "Will-o'-the-Wisp").supported
    _w1g5_resolve_stack(game)

    (swamp,) = [p for p in game.controlled_by(0) if p.card.name == "Swamp"]
    assert not swamp.tapped and compass.tapped
    assert _w1g5_floating(game) == {}
    assert "Will-o'-the-Wisp" in [p.card.name for p in game.controlled_by(0)]


def test_w1g5_a_derived_land_is_read_through_and_never_as_five_colours(set_pool):
    """Reflecting Pool (Tempest) is Scryfall's five colours and CR 106.7's
    nothing-of-its-own. It is not a basic land, so alone it offers the Compass
    nothing; and a basic Forest beside it is read for what the *Forest* makes."""
    game, compass = _w1g5_compass(set_pool, mine=["Reflecting Pool"])
    _w1g5_compass_tap(game, compass, "W")
    assert _w1g5_floating(game) == {}

    game, compass = _w1g5_compass(set_pool, mine=["Reflecting Pool", "Forest"])
    _w1g5_compass_tap(game, compass, "W")
    assert _w1g5_floating(game) == {"G": 1}


def test_w1g5_mana_cylix_is_a_mana_ability_that_costs_a_mana(set_pool):
    """"{1}, {T}: Add one mana of any color." Supported on arrival and never
    run. A mana ability with a mana cost (CR 605.1a asks what it does, not
    what it costs): with nothing floating it is refused and the Cylix stays
    untapped; with one mana floating it turns a Mountain's red into the blue
    that casts a Merfolk, without the stack."""
    pls, lea = set_pool("PLS"), set_pool("LEA")
    (ability,) = _w1g5_compile(pls["Mana Cylix"]).activated_abilities
    assert _w1g5_is_mana_ability(ability)
    assert ability.cost.mana["generic"] == 1 and ability.cost.requires_tap

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[
            _W1G5Permanent(card=pls["Mana Cylix"]),
            _W1G5Permanent(card=lea["Mountain"]),
        ],
        hand=[lea["Merfolk of the Pearl Trident"]],
    )
    game = _W1G5Game(players=[me, _W1G5PlayerState(name="W1G5-B")])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    (cylix, mountain) = list(game.controlled_by(0))

    def filter_for(color):
        return game.activate_permanent_ability(
            0, "Mana Cylix",
            permanent_index=game.battlefield_index_of(cylix), mana_color=color,
        )

    refused = filter_for("U")
    assert not refused.supported and not cylix.tapped
    assert game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert filter_for("U").supported
    assert cylix.tapped and not game.stack
    assert _w1g5_floating(game) == {"U": 1}
    assert game.cast_from_hand(0, "Merfolk of the Pearl Trident").supported
    _w1g5_resolve_stack(game)
    assert _w1g5_floating(game) == {}

