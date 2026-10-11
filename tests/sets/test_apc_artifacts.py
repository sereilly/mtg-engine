"""Apocalypse artifacts (artifact creatures included).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.card_loader import manifest_set_path as _w1g1_manifest_set_path
from engine.cast_costs import KICKED as _W1G1_KICKED
from engine.cast_costs import additional_costs as _w1g1_additional_costs
from engine.models import Permanent as _W1G1Permanent
from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import resolve_stack as _w1g1_resolve_stack

# --- Emblazoned Golem --------------------------------------------------------
# "Kicker {X}. Spend only colored mana on X. No more than one mana of each
# color may be spent this way. If this creature was kicked, it enters with X
# +1/+1 counters on it."  {2}, a 1/2.

_W1G1_GOLEM = "Emblazoned Golem"


def _w1g1_duel(set_pool, pool, *, enforce=True, board=()):
    """Seat 0 holds an Emblazoned Golem with *pool* floating and *board* (cards)
    already on its battlefield. Mana is charged unless *enforce* is False."""
    forest = set_pool("LEA")["Forest"]
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            "Caster", library=[forest] * 10, hand=[set_pool("APC")[_W1G1_GOLEM]]
        ),
        _W1G1PlayerState("Bystander", library=[forest] * 10),
    ])
    game.enforce_mana_costs = enforce
    for card in board:
        game._put_permanent_onto_battlefield(0, _W1G1Permanent(card=card), None)
    game.players[0].mana_pool.update(pool)
    return game  # _w1g1_duel


def _w1g1_cast(game, x_value=None, *, kick=True):
    """Announce the Golem — kicked for *x_value* unless *kick* is False —
    resolve it, and return ``(result, the Golem or None)``."""
    result = game.cast_from_hand(
        0, _W1G1_GOLEM,
        optional_cost_payments={"{X}": 1} if kick else None, x_value=x_value,
    )
    if result.supported:
        _w1g1_resolve_stack(game)
    golem = next(
        (p for p in game.controlled_by(0) if p.card.name == _W1G1_GOLEM), None
    )
    return result, golem  # _w1g1_cast


def _w1g1_left(game) -> dict:
    return {
        symbol: count for symbol, count in game.players[0].mana_pool.items() if count
    }  # _w1g1_left


def test_w1g1_emblazoned_golem_compiles_with_its_x_restricted(set_pool):
    """Supported, and the restriction is *on the offer*: every reader that
    prices the kicker holds the flag that says its X is one mana per colour."""
    card = set_pool("APC")[_W1G1_GOLEM]
    assert _w1g1_compile(card).supported
    (cost,) = _w1g1_additional_costs(card)
    (offer,) = cost.optional_mana
    assert (offer.symbols, offer.x_count, offer.x_one_of_each_color) == ("{X}", 1, True)
    assert offer.x_colorings(0) == ((),)
    assert len(offer.x_colorings(2)) == 10 and len(offer.x_colorings(5)) == 1
    assert offer.x_colorings(6) == ()


@_w1g1_pytest.mark.parametrize("pool,x_value,left", [
    # three colours for X = 3, the two colourless for the {2}
    ({"W": 2, "U": 1, "B": 1, "R": 1, "G": 1, "C": 2}, 3, {"W": 1, "R": 1, "G": 1}),
    # all five colours, once each, and the {2} from colourless
    ({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1, "C": 2}, 5, {}),
    # one colour pays X = 1 and the generic {2} as well
    ({"W": 5}, 1, {"W": 2}),
    ({"W": 2, "U": 2}, 2, {}),
])
def test_w1g1_a_kicked_emblazoned_golem_enters_with_x_counters(set_pool, pool, x_value, left):
    """X is paid with one mana of each of X colours on top of the {2}, and the
    Golem enters with X +1/+1 counters: a 1/2 plus X."""
    game = _w1g1_duel(set_pool, pool)
    result, golem = _w1g1_cast(game, x_value)

    assert result.supported, result.details
    assert (golem.effective_power, golem.effective_toughness) == (1 + x_value, 2 + x_value)
    assert int(golem.metadata.get("plus_counters", 0) or 0) == x_value
    assert golem.metadata.get(_W1G1_KICKED)
    assert _w1g1_left(game) == left
    assert f"Caster kicked {_W1G1_GOLEM} (X={x_value})" in game.log


@_w1g1_pytest.mark.parametrize("pool,x_value", [
    # five white mana is one colour: X = 2 needs two
    ({"W": 5}, 2),
    # colourless mana is not coloured mana
    ({"C": 8}, 1),
    ({"C": 7, "R": 1}, 2),
    # all five colours for X, and then nothing left for the {2}
    ({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1}, 5),
])
def test_w1g1_an_x_the_colors_cannot_pay_is_refused_with_nothing_spent(set_pool, pool, x_value):
    """"Spend only colored mana on X. No more than one mana of each color may
    be spent this way." A pool rich enough in *mana* and too poor in *colours*
    does not cast the kicked Golem, and a refused cast spends nothing."""
    game = _w1g1_duel(set_pool, pool)
    result, golem = _w1g1_cast(game, x_value)

    assert not result.supported
    assert golem is None
    assert _w1g1_left(game) == pool
    assert [card.name for card in game.players[0].hand] == [_W1G1_GOLEM]


@_w1g1_pytest.mark.parametrize("enforce", [True, False])
def test_w1g1_x_above_five_is_refused_whether_or_not_mana_is_charged(set_pool, enforce):
    """There are five colours, so no X above five can be paid one mana of
    each. That bounds the announcement itself — refused before any cost, and
    in a game that waives mana too, where nothing else would stop it."""
    rich = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}
    game = _w1g1_duel(set_pool, rich, enforce=enforce)
    result, golem = _w1g1_cast(game, 6)
    assert not result.supported and golem is None
    assert "no more than one mana of each color" in result.details
    assert _w1g1_left(game) == rich

    game = _w1g1_duel(set_pool, rich, enforce=enforce)
    result, golem = _w1g1_cast(game, 5)
    assert result.supported
    assert (golem.effective_power, golem.effective_toughness) == (6, 7)


def test_w1g1_an_unkicked_emblazoned_golem_is_a_one_two_for_two(set_pool):
    """The kicker declined: {2}, a 1/2, no counters — and an X sent along with
    a declined kicker is not an X (CR 601.2b), so it buys nothing."""
    for stray_x in (None, 3):
        game = _w1g1_duel(set_pool, {"W": 2, "U": 2})
        result, golem = _w1g1_cast(game, stray_x, kick=False)
        assert result.supported
        assert (golem.effective_power, golem.effective_toughness) == (1, 2)
        assert int(golem.metadata.get("plus_counters", 0) or 0) == 0
        assert not golem.metadata.get(_W1G1_KICKED)
        assert _w1g1_left(game) == {"U": 2}


def test_w1g1_an_emblazoned_golem_nothing_cast_has_no_counters(set_pool):
    """Put onto the battlefield without being cast: not kicked, no X, a 1/2."""
    game = _w1g1_duel(set_pool, {})
    golem = _W1G1Permanent(card=set_pool("APC")[_W1G1_GOLEM])
    game._put_permanent_onto_battlefield(0, golem, None)
    assert (golem.effective_power, golem.effective_toughness) == (1, 2)


def test_w1g1_the_restriction_reads_the_manas_real_color_under_celestial_dawn(set_pool):
    """CR 609.4b: spending mana "as though it were mana of any color" "doesn't
    change what mana was actually spent". Under Celestial Dawn five white mana
    could pay five different coloured *pips* — and is still one colour of
    mana, so it pays X = 1 and not X = 2. A green mana beside the white is a
    second colour and does: Celestial Dawn lets it pay only generic costs, and
    X is one."""
    dawn = set_pool("MIR")["Celestial Dawn"]

    game = _w1g1_duel(set_pool, {"W": 5}, board=[dawn])
    result, golem = _w1g1_cast(game, 2)
    assert not result.supported and golem is None
    assert _w1g1_left(game) == {"W": 5}

    game = _w1g1_duel(set_pool, {"W": 5}, board=[dawn])
    result, golem = _w1g1_cast(game, 1)
    assert result.supported and golem.effective_power == 2

    game = _w1g1_duel(set_pool, {"W": 1, "G": 3}, board=[dawn])
    result, golem = _w1g1_cast(game, 2)
    assert result.supported, result.details
    assert golem.effective_power == 3 and _w1g1_left(game) == {}


def test_w1g1_colorless_mana_is_not_colored_even_under_chromatic_orrery(set_pool):
    """"You may spend mana as though it were mana of any color." lets {C} pay a
    coloured pip; it does not make {C} coloured mana. Eight colourless pays no
    X at all, and a lone red among it pays X = 1 and not X = 2."""
    orrery = set_pool("M21")["Chromatic Orrery"]

    game = _w1g1_duel(set_pool, {"C": 8}, board=[orrery])
    assert not _w1g1_cast(game, 1)[0].supported

    game = _w1g1_duel(set_pool, {"C": 7, "R": 1}, board=[orrery])
    assert not _w1g1_cast(game, 2)[0].supported

    game = _w1g1_duel(set_pool, {"C": 7, "R": 1}, board=[orrery])
    result, golem = _w1g1_cast(game, 1)
    assert result.supported and golem.effective_power == 2
    assert _w1g1_left(game) == {"C": 5}


def test_w1g1_the_golems_x_box_is_capped_by_the_colors_the_board_can_make(set_pool):
    """The picker's ceiling is the payment's own: with a white and a blue mana
    and two colourless, the kicker can be taken and X goes up to 2 — not to the
    4 a count of mana would give. Four lands of one colour cap it at 1."""
    card = set_pool("APC")[_W1G1_GOLEM]
    game = _w1g1_duel(set_pool, {"W": 1, "U": 1, "C": 2})
    (offer,) = game.cast_cost_offers(0, card)
    assert (offer["label"], offer["symbols"], offer["max_times"]) == ("kicker", "{X}", 1)
    spec = game.cast_target_spec(0, card, optional_cost_payments={"{X}": 1})
    assert spec["announces_x"] and spec["max_x"] == 2
    assert not game.cast_target_spec(0, card).get("announces_x")

    plains = set_pool("LEA")["Plains"]
    game = _w1g1_duel(set_pool, {}, board=[plains] * 4)
    spec = game.cast_target_spec(0, card, optional_cost_payments={"{X}": 1})
    assert spec["max_x"] == 1


def test_w1g1_the_ai_kicks_emblazoned_golem_for_the_colors_it_has():
    """Pinned into both decks of six simulated games: it is cast, it is kicked
    for an X the seat's lands can colour, and it is never refused. (The floors
    sit under today's four casts and three kicks.)"""
    from engine.ai_simulator import run_ai_simulation

    report = run_ai_simulation(
        [_w1g1_manifest_set_path("APC", include_measured=True)],
        games=6, seed=1337, max_turns=18, required_cards=[_W1G1_GOLEM],
    )
    assert report.games_completed == 6
    cast = [l for l in report.log_lines if f" cast {_W1G1_GOLEM} -> resolved" in l]
    kicked = [l for l in report.log_lines if f" kicked {_W1G1_GOLEM} (X=" in l]
    assert len(cast) >= 2, cast
    assert len(kicked) >= 1, kicked
    for line in kicked:
        assert 1 <= int(line.rsplit("(X=", 1)[1].rstrip(")")) <= 5, line
    assert [k for k in report.refused_casts if k.split(":")[0] == _W1G1_GOLEM] == []
    assert [i.message for i in report.issues if _W1G1_GOLEM in i.message] == []
    w1g1_golem_left_nothing_owing = not report.steps_left_owing
    assert w1g1_golem_left_nothing_owing, report.steps_left_owing

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

from engine import Game as _w1g3a_Game, PlayerState as _w1g3a_Player
from engine.game_types import CardDefinition as _w1g3a_CardDefinition
from engine.models import Permanent as _w1g3a_Permanent
from tests.helpers import resolve_stack as _w1g3a_resolve_stack


def _w1g3a_card(name, type_line, power="2", toughness="2"):
    """A card that is nothing but a printed type line — what Brass Herald's
    reveal and its lord line both read."""
    return _w1g3a_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": power, "toughness": toughness},
    )  # W1G3 artifacts: a typed card


def _w1g3a_herald_game(set_pool, library, *, mine=(), theirs=(), interactive=()):
    """Brass Herald in seat 0's hand over *library*, both boards placed."""
    board0 = [_w1g3a_Permanent(card=card) for card in mine]
    board1 = [_w1g3a_Permanent(card=card) for card in theirs]
    game = _w1g3a_Game(players=[
        _w1g3a_Player(
            name="P0", hand=[set_pool("APC")["Brass Herald"]],
            library=list(library), battlefield=board0,
        ),
        _w1g3a_Player(name="P1", battlefield=board1),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game, board0, board1  # W1G3 artifacts: the Herald's game


def _w1g3a_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)  # W1G3 artifacts: P/T


def _w1g3a_herald(game):
    return next(
        p for p in game.controlled_by(0)
        if p.card.name == "Brass Herald" and "herald_fixture" not in p.metadata
    )  # W1G3 artifacts: the Herald just cast


def test_w1g3_brass_herald_takes_the_type_its_own_deck_holds_and_lords_it(set_pool):
    """"As this creature enters, choose a creature type." / "…Put all creature
    cards of the chosen type revealed this way into your hand and the rest on
    the bottom of your library in any order." / "Creatures of the chosen type
    get +1/+1."

    With nobody asked, the type is the one the controller's own hand and
    library hold most of — the reveal and the anthem both feed their
    controller, so the opponents' type would make the card a six-mana 2/2
    that mills four to the bottom. The anthem has no "you control": the
    opponent's Elf grows too, and the Herald, a Golem, does not."""
    library = [
        _w1g3a_card("Elf One", "Creature — Elf"),
        _w1g3a_card("A Goblin", "Creature — Goblin"),
        _w1g3a_card("Elf Two", "Creature — Elf Druid"),
        _w1g3a_card("A Land", "Land"),
        _w1g3a_card("Elf Unseen", "Creature — Elf"),
    ]
    game, mine, theirs = _w1g3a_herald_game(
        set_pool, library,
        mine=[_w1g3a_card("My Elf", "Creature — Elf")],
        theirs=[
            _w1g3a_card("Their Goblin", "Creature — Goblin"),
            _w1g3a_card("Their Other Goblin", "Creature — Goblin"),
            _w1g3a_card("Their Elf", "Creature — Elf"),
        ],
    )
    me = game.players[0]

    assert game.cast_from_hand(0, "Brass Herald").supported

    herald = _w1g3a_herald(game)
    assert herald.metadata["chosen_creature_type"] == "elf"
    assert [c.name for c in me.hand] == ["Elf One", "Elf Two"], game.log
    assert [c.name for c in me.library] == ["Elf Unseen", "A Goblin", "A Land"]
    assert "P0 revealed Elf One, A Goblin, Elf Two, A Land" in game.log
    assert _w1g3a_pt(mine[0]) == (3, 3)
    assert _w1g3a_pt(theirs[2]) == (3, 3)
    assert _w1g3a_pt(theirs[0]) == (2, 2) and _w1g3a_pt(theirs[1]) == (2, 2)
    assert _w1g3a_pt(herald) == (2, 2)


def test_w1g3_brass_herald_reveals_for_the_type_its_controller_answered(set_pool):
    """The reveal reads the type stamped on **this** permanent, after the
    answer. The default here would be Golem (the deck holds two); the player
    names Elf, a word that is not a creature type is refused, and the trigger
    — on the stack since the Herald entered, above nothing — takes the Elf and
    leaves both Golems. A second Herald already on the battlefield that chose
    Ox changes nothing about what this one finds."""
    library = [
        _w1g3a_card("An Elf", "Creature — Elf"),
        _w1g3a_card("Golem One", "Artifact Creature — Golem"),
        _w1g3a_card("An Ox", "Creature — Ox"),
        _w1g3a_card("Golem Two", "Artifact Creature — Golem"),
        _w1g3a_card("Unseen", "Land"),
    ]
    game, mine, _ = _w1g3a_herald_game(
        set_pool, library,
        mine=[set_pool("APC")["Brass Herald"], _w1g3a_card("My Elf", "Creature — Elf")],
        interactive={0},
    )
    older, my_elf = mine
    older.metadata["chosen_creature_type"] = "ox"
    older.metadata["herald_fixture"] = True
    me = game.players[0]

    assert game.cast_from_hand(0, "Brass Herald").supported

    owed = game.pending_enter_choice
    assert owed is not None and owed["needs_creature_type"]
    assert owed["default_creature_type"] == "golem"
    assert me.hand == [] and len(me.library) == 5, "revealed before the type was chosen"

    # Scryfall's ruling for the card: "You must choose an existing creature
    # type … Card types such as artifact and supertypes such as legendary
    # can't be chosen."
    for not_a_creature_type in ("mountain", "artifact", "legendary"):
        assert not game.confirm_enter_choice(0, creature_type=not_a_creature_type)
    assert game.confirm_enter_choice(0, creature_type="Elf")
    herald = _w1g3a_herald(game)
    assert herald.metadata["chosen_creature_type"] == "elf"
    assert _w1g3a_pt(herald) == (2, 2) and _w1g3a_pt(my_elf) == (3, 3)

    game._settle()

    assert [c.name for c in me.hand] == ["An Elf"], game.log
    waiting = game.waiting_prompt()
    assert waiting is not None and waiting.kind == "reorder_library"
    assert [c.name for c in game.reorder_library_pile(waiting)] == [
        "Golem One", "An Ox", "Golem Two",
    ]
    assert game.confirm_reorder_library(0, [1, 2, 0])
    game._settle()
    assert [c.name for c in me.library] == ["Unseen", "An Ox", "Golem Two", "Golem One"]
    assert game.stack == [] and game.pending_choices == []


def test_w1g3_brass_herald_choosing_golem_makes_itself_a_three_three(set_pool):
    """"Creatures of the chosen type get +1/+1" has no "other": a Herald that
    names its own type is a 3/3, and so is every other Golem at the table —
    until the Herald is destroyed, when the bonus goes with it.

    And with it goes the toughness that was holding damage: Scryfall's ruling
    for the card is that "nonlethal damage dealt to creatures of the chosen
    type may become lethal if Brass Herald leaves the battlefield during that
    turn". A 3/4 Golem that took four as a 4/5 dies when the Herald does."""
    library = [_w1g3a_card("Golem One", "Artifact Creature — Golem")]
    game, _, theirs = _w1g3a_herald_game(
        set_pool, library,
        theirs=[
            _w1g3a_card("Their Golem", "Artifact Creature — Golem", "3", "4"),
            _w1g3a_card("Their Ox", "Creature — Ox"),
        ],
    )

    assert game.cast_from_hand(0, "Brass Herald").supported

    herald = _w1g3a_herald(game)
    assert herald.metadata["chosen_creature_type"] == "golem"
    assert _w1g3a_pt(herald) == (3, 3)
    assert _w1g3a_pt(theirs[0]) == (4, 5) and _w1g3a_pt(theirs[1]) == (2, 2)
    assert [c.name for c in game.players[0].hand] == ["Golem One"]

    me = game.players[0]
    me.hand.append(set_pool("APC")["Prophetic Bolt"])
    assert game.cast_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    game.auto_resolve_pending_choices()
    game._settle()
    assert theirs[0].damage_marked == 4 and game.is_on_battlefield(theirs[0])

    me.hand.append(set_pool("LEA")["Shatter"])
    assert game.cast_from_hand(
        0, "Shatter", target_permanent_ids=[herald.permanent_id],
    ).supported
    assert not game.is_on_battlefield(herald)
    assert not game.is_on_battlefield(theirs[0]), game.log
    assert "Their Golem" in [c.name for c in game.players[1].graveyard]
    assert _w1g3a_pt(theirs[1]) == (2, 2)


def test_w1g3_brass_herald_that_left_still_reveals_for_the_type_it_chose(set_pool):
    """The entry trigger is a stack object, so the Herald can be gone before
    it resolves. The type it chose is its last known information (CR 608.2h):
    the reveal still happens and still takes that type — never "every creature
    card", and never nothing."""
    library = [
        _w1g3a_card("A Goblin", "Creature — Goblin"),
        _w1g3a_card("Goblin Two", "Creature — Goblin Warrior"),
        _w1g3a_card("An Ox", "Creature — Ox"),
        _w1g3a_card("A Land", "Land"),
    ]
    game, _, _ = _w1g3a_herald_game(set_pool, library)
    me = game.players[0]

    assert game.queue_from_hand(0, "Brass Herald").supported
    assert game.resolve_top_of_stack()
    herald = _w1g3a_herald(game)
    assert herald.metadata["chosen_creature_type"] == "goblin"
    assert [item.card.name for item in game.stack] == ["Brass Herald"]

    game.remove_from_battlefield(herald)
    _w1g3a_resolve_stack(game)

    assert [c.name for c in me.hand] == ["A Goblin", "Goblin Two"], game.log
    assert [c.name for c in me.library] == ["An Ox", "A Land"]

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack

_W1G6_FOUR_TYPES = ("Plains", "Island", "Swamp", "Mountain")


def _w1g6_mask_table(set_pool, mine=(), theirs=()):
    """Mask of Intolerance under seat 0, with *mine* / *theirs* (Alpha's lands)
    beside it and across from it. Returns the game and seat 0's permanents,
    the Mask first."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="W1G6-A"), _W1G6PlayerState(name="W1G6-B"),
    ])
    w1g6_game.enforce_mana_costs = False
    w1g6_rows = []
    for w1g6_seat, w1g6_names in enumerate((("Mask of Intolerance",) + tuple(mine), theirs)):
        w1g6_row = []
        for w1g6_name in w1g6_names:
            w1g6_card = set_pool("APC").get(w1g6_name) or set_pool("LEA")[w1g6_name]
            w1g6_perm = _W1G6Permanent(card=w1g6_card)
            w1g6_game._put_permanent_onto_battlefield(w1g6_seat, w1g6_perm, None)
            w1g6_row.append(w1g6_perm)
        w1g6_rows.append(w1g6_row)
    return w1g6_game, w1g6_rows[0]  # _w1g6_mask_table


def _w1g6_mask_upkeep(game, seat):
    """Run *seat*'s upkeep; returns what triggered, left on the stack."""
    game.active_player_index = seat
    game.resolve_upkeep(seat, defer_priority=True)
    return [w1g6_item.card.name for w1g6_item in game.stack]  # _w1g6_mask_upkeep


def test_w1g6_mask_of_intolerance_reads_that_players_lands(set_pool):
    """"At the beginning of **each player's** upkeep, if there are four or more
    basic land types among lands **that player** controls, this artifact deals
    3 damage to that player." Domain counted for the player whose upkeep it
    is — the Mask's controller on theirs, the opponent on the opponent's — and
    the damage goes to that same player."""
    program = _w1g6_compile(set_pool("APC")["Mask of Intolerance"])
    assert program.supported, program.reason

    # Four types on the controller's side, one on the other.
    game, _mine = _w1g6_mask_table(
        set_pool, mine=_W1G6_FOUR_TYPES, theirs=("Forest",) * 4,
    )
    assert _w1g6_mask_upkeep(game, 0) == ["Mask of Intolerance"]
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [17, 20]
    assert "Mask of Intolerance dealt 3 damage to W1G6-A" in game.log
    assert _w1g6_mask_upkeep(game, 1) == []
    assert [player.life for player in game.players] == [17, 20]

    # Three on the controller's side, five on the other: the controller's own
    # upkeep is quiet and the opponent's is not.
    game, _mine = _w1g6_mask_table(
        set_pool, mine=_W1G6_FOUR_TYPES[:3], theirs=_W1G6_FOUR_TYPES + ("Forest",),
    )
    assert _w1g6_mask_upkeep(game, 0) == []
    assert _w1g6_mask_upkeep(game, 1) == ["Mask of Intolerance"]
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 17]
    assert "Mask of Intolerance dealt 3 damage to W1G6-B" in game.log


@_w1g6_pytest.mark.parametrize("lands, burned", [
    # Types, not lands: four Forests are one type.
    (("Forest",) * 4, False),
    (("Plains", "Island", "Swamp"), False),
    # A dual land is two (CR 305.6: each basic land type it has).
    (("Tropical Island", "Badlands"), True),
    (("Tropical Island", "Swamp"), False),
    (("Plains", "Island", "Swamp", "Mountain", "Forest"), True),
])
def test_w1g6_mask_of_intolerance_counts_types_not_lands(set_pool, lands, burned):
    game, _mine = _w1g6_mask_table(set_pool, mine=lands)

    triggered = _w1g6_mask_upkeep(game, 0)
    _w1g6_resolve_stack(game)

    assert triggered == (["Mask of Intolerance"] if burned else [])
    assert game.players[0].life == (17 if burned else 20)


def test_w1g6_mask_of_intolerance_checks_again_as_it_resolves(set_pool):
    """CR 603.4's second check. The trigger is on the stack over four types; a
    land leaves in response; three types deal nothing. (An upkeep damage
    trigger with an intervening "if" used to be queued as a bare damage event
    with no condition on it, so the answer came too late to matter.)"""
    game, mine = _w1g6_mask_table(set_pool, mine=_W1G6_FOUR_TYPES)

    assert _w1g6_mask_upkeep(game, 0) == ["Mask of Intolerance"]
    game.remove_from_battlefield(mine[-1])
    _w1g6_resolve_stack(game)

    assert game.players[0].life == 20
    assert (
        "Mask of Intolerance ability did nothing: its condition is no longer true"
    ) in game.log

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

import pytest as _w1g8_pytest

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.replacements import discard_to_battlefield as _w1g8_discard_to_battlefield
from engine.replacements import replacement_claims_line as _w1g8_claims_line
from tests.helpers import _mk_card as _w1g8_mk_card
from tests.helpers import resolve_stack as _w1g8_resolve_stack

# Where the cards these tests borrow from other sets were first printed. Every
# other name is Apocalypse's.
_W1G8_HOMES = {
    "Forest": "LEA", "Island": "LEA", "Grizzly Bears": "LEA",
    "Library of Leng": "LEA", "Wheel of Fortune": "LEA", "Mind Rot": "7ED",
    "Hymn to Tourach": "FEM", "Coercion": "TMP", "Megrim": "STH",
    "Thrill of Possibility": "M21",
}
_W1G8_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}
_W1G8_DODECAPOD_LINE = (
    "If a spell or ability an opponent controls causes you to discard this "
    "card, put it onto the battlefield with two +1/+1 counters on it instead "
    "of putting it into your graveyard."
)


def _w1g8_card(set_pool, name: str):
    return set_pool(_W1G8_HOMES.get(name, "APC"))[name]


def _w1g8_duel(set_pool, *, hand=(), opp_hand=(), interactive=()) -> _w1g8_Game:
    forest = _w1g8_card(set_pool, "Forest")
    me = _w1g8_PlayerState(
        name="Me", hand=[_w1g8_card(set_pool, n) for n in hand], library=[forest] * 12,
    )
    opp = _w1g8_PlayerState(
        name="Opp", hand=[_w1g8_card(set_pool, n) for n in opp_hand],
        library=[forest] * 12,
    )
    game = _w1g8_Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    me.mana_pool.update(_W1G8_RICH)
    opp.mana_pool.update(_W1G8_RICH)
    return game


def _w1g8_put(game, set_pool, seat: int, name: str) -> _w1g8_Permanent:
    perm = _w1g8_Permanent(card=_w1g8_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g8_names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _w1g8_settle(game) -> None:
    """Resolve the stack and take every owed default, as a headless seat's
    loop does between actions."""
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_replacement_choices()
    _w1g8_resolve_stack(game)


def _w1g8_dodecapods(game, seat: int) -> list[tuple[int, int]]:
    return [
        (perm.effective_power, perm.effective_toughness)
        for perm in game.controlled_by(seat) if perm.card.name == "Dodecapod"
    ]


# --- Dodecapod -------------------------------------------------------------------


def test_w1g8_dodecapod_is_supported_by_the_replacement_table_and_nothing_else(set_pool):
    """Its whole text is one CR 614 replacement, so no instruction compiles:
    the line is claimed by ``replacement_claims_line`` through the reader the
    interceptor itself asks, and the card is an artifact creature with that
    static line."""
    program = _w1g8_compile(_w1g8_card(set_pool, "Dodecapod"))
    assert program.supported
    assert [i.kind for i in program.instructions] == ["static_line"]
    assert _w1g8_claims_line(_W1G8_DODECAPOD_LINE)
    assert _w1g8_discard_to_battlefield(_W1G8_DODECAPOD_LINE) == {
        "counters": {"+1/+1": 2},
    }


def test_w1g8_dodecapod_chosen_as_an_opponents_discard_enters_as_a_five_five(set_pool):
    """"If a spell or ability an opponent controls causes you to choose a card
    to discard and you discard Dodecapod, you'll put it onto the battlefield."
    Mind Rot is the opponent's; I pick the Dodecapod and a Forest. One enters
    with its two counters, the other is in the graveyard — and both were
    discarded."""
    game = _w1g8_duel(
        set_pool, hand=["Dodecapod", "Forest", "Island"], opp_hand=["Mind Rot"],
        interactive=(0, 1),
    )
    assert game.queue_from_hand(1, "Mind Rot", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_discard(0, [0, 1])

    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert _w1g8_names(game.players[0].graveyard) == ["Forest"]
    assert _w1g8_names(game.players[0].hand) == ["Island"]
    assert any(
        "discarded Dodecapod, which was put onto the battlefield" in line
        for line in game.log
    )


def test_w1g8_dodecapod_taken_at_random_or_by_the_opponents_pick_still_enters(set_pool):
    """Nobody on my side chose: Hymn to Tourach takes it at random and
    Coercion's caster picks it out of my revealed hand. Two different discard
    paths in the engine, one printed condition."""
    game = _w1g8_duel(set_pool, hand=["Dodecapod", "Forest"], opp_hand=["Hymn to Tourach"])
    assert game.queue_from_hand(1, "Hymn to Tourach", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert _w1g8_names(game.players[0].graveyard) == ["Forest"]

    game = _w1g8_duel(
        set_pool, hand=["Dodecapod", "Forest"], opp_hand=["Coercion"], interactive=(0, 1),
    )
    assert game.queue_from_hand(1, "Coercion", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_revealed_hand_pick(1, 0)
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert game.players[0].graveyard == []
    assert _w1g8_names(game.players[0].hand) == ["Forest"]


def test_w1g8_dodecapod_discarded_by_its_owners_own_doing_goes_to_the_graveyard(set_pool):
    """The restriction is the card: "a spell or ability **an opponent**
    controls". My own Mind Rot, my own Wheel of Fortune, a cost I chose to pay
    and the cleanup step's hand size are none of them that, and each puts it
    in the graveyard like any other card."""
    # My own spell, aimed at me.
    game = _w1g8_duel(set_pool, hand=["Mind Rot", "Dodecapod", "Forest"])
    assert game.queue_from_hand(0, "Mind Rot", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == []
    assert "Dodecapod" in _w1g8_names(game.players[0].graveyard)

    # My own spell that makes *each* player discard.
    game = _w1g8_duel(set_pool, hand=["Wheel of Fortune", "Dodecapod"])
    assert game.queue_from_hand(0, "Wheel of Fortune").supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == []
    assert "Dodecapod" in _w1g8_names(game.players[0].graveyard)

    # A cost (CR 601.2h): nothing caused it but the player paying.
    game = _w1g8_duel(set_pool, hand=["Thrill of Possibility", "Dodecapod"])
    assert game.queue_from_hand(0, "Thrill of Possibility", cost_hand_index=1).supported
    assert _w1g8_dodecapods(game, 0) == []
    assert _w1g8_names(game.players[0].graveyard) == ["Dodecapod"]

    # CR 514.1: the cleanup step's discard is a turn-based action.
    forest = _w1g8_card(set_pool, "Forest")
    game = _w1g8_duel(set_pool, hand=["Dodecapod"])
    game.players[0].hand.extend([forest] * 7)
    game.resolve_cleanup_step(0, discard_hand_indices=[0])
    assert _w1g8_dodecapods(game, 0) == []
    assert _w1g8_names(game.players[0].graveyard) == ["Dodecapod"]


def test_w1g8_the_opponents_wheel_puts_dodecapod_onto_the_battlefield(set_pool):
    """The mirror of the case above: the same spell, cast by the other seat,
    and now an opponent's spell is what discards my hand."""
    game = _w1g8_duel(set_pool, hand=["Dodecapod", "Forest"], opp_hand=["Wheel of Fortune"])
    assert game.queue_from_hand(1, "Wheel of Fortune").supported
    _w1g8_settle(game)

    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert _w1g8_names(game.players[0].graveyard) == ["Forest"]
    assert len(game.players[0].hand) == 7


def test_w1g8_a_dodecapod_put_onto_the_battlefield_was_still_discarded(set_pool):
    """"If you discard Dodecapod and put it onto the battlefield, you've still
    discarded it. Abilities that trigger whenever you discard a card will
    trigger." Megrim deals its 2; and a sentence counting what was discarded
    counts it — Gerrard's Verdict sees two cards go, one of them a land."""
    game = _w1g8_duel(set_pool, hand=["Dodecapod"], opp_hand=["Mind Rot"])
    _w1g8_put(game, set_pool, 1, "Megrim")
    assert game.queue_from_hand(1, "Mind Rot", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)]
    assert game.players[0].life == 18, game.log

    game = _w1g8_duel(
        set_pool, hand=["Dodecapod", "Forest"], opp_hand=["Gerrard's Verdict"],
    )
    assert game.queue_from_hand(1, "Gerrard's Verdict", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)]
    assert game.players[0].hand == []
    assert game.players[1].life == 23, "one land card among the two discarded"


def test_w1g8_library_of_leng_and_dodecapod_contend_for_one_discard(set_pool):
    """Both replace where the discarded card goes (CR 616.1): a seat that is
    asked may take the Library's offer instead, and a seat nobody asks gets the
    creature."""
    game = _w1g8_duel(
        set_pool, hand=["Dodecapod"], opp_hand=["Mind Rot"], interactive=(0, 1),
    )
    _w1g8_put(game, set_pool, 0, "Library of Leng")
    assert game.queue_from_hand(1, "Mind Rot", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_discard(0, [0], to_library=True)
    assert _w1g8_dodecapods(game, 0) == []
    assert game.players[0].library[0].name == "Dodecapod"

    game = _w1g8_duel(set_pool, hand=["Dodecapod"], opp_hand=["Hymn to Tourach"])
    _w1g8_put(game, set_pool, 0, "Library of Leng")
    assert game.queue_from_hand(1, "Hymn to Tourach", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert game.players[0].library[0].name == "Forest"


def test_w1g8_the_sentence_without_counters_is_the_same_replacement(set_pool):
    """The counters are payload: the sentence is printed without them too
    (Loxodon Smiter's wording), and an invented card carrying it enters as
    printed — no name is read anywhere."""
    text = (
        "If a spell or ability an opponent controls causes you to discard this "
        "card, put it onto the battlefield instead of putting it into your "
        "graveyard."
    )
    assert _w1g8_discard_to_battlefield(text) == {"counters": {}}
    smiter = _w1g8_mk_card(
        name="Probe Smiter", mana_cost="{1}{G}{W}", type_line="Creature — Elephant",
        oracle_text=text, power=4, toughness=4,
    )
    assert _w1g8_compile(smiter).supported

    game = _w1g8_duel(set_pool, opp_hand=["Mind Rot"])
    game.players[0].hand.append(smiter)
    assert game.queue_from_hand(1, "Mind Rot", target_player_index=0).supported
    _w1g8_settle(game)

    assert [
        (perm.card.name, perm.effective_power, perm.effective_toughness)
        for perm in game.controlled_by(0)
    ] == [("Probe Smiter", 4, 4)], game.log


@_w1g8_pytest.mark.parametrize("text", [
    # A number word the entry reader does not know: claiming the line would
    # put the creature in play with no counters, or with a guessed number.
    "If a spell or ability an opponent controls causes you to discard this card, "
    "put it onto the battlefield with umpteen +1/+1 counters on it instead of "
    "putting it into your graveyard.",
    # Another destination is another effect.
    "If a spell or ability an opponent controls causes you to discard this card, "
    "put it onto the battlefield instead of putting it into your library.",
    # "You" discarding for any reason is a wider condition than the card's.
    "If you discard this card, put it onto the battlefield instead of putting "
    "it into your graveyard.",
])
def test_w1g8_a_discard_replacement_the_interceptor_cannot_perform_is_not_claimed(text):
    assert _w1g8_discard_to_battlefield(text) is None
    assert not _w1g8_claims_line(text)
    probe = _w1g8_mk_card(
        name="Probe", mana_cost="{4}", type_line="Artifact Creature — Golem",
        oracle_text=text, power=3, toughness=3,
    )
    assert not _w1g8_compile(probe).supported

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================

# ==== W2G1 ============================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ========================================================

# ==== W2G2 ============================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ========================================================

# ==== W2G3 ============================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ========================================================

# ==== W2G4 ============================================================
# W2G4's tests go between this line and the "end W2G4" line.

# ==== end W2G4 ========================================================

# ==== W2G5 ============================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ========================================================
