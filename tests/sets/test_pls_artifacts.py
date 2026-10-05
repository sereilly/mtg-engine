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

