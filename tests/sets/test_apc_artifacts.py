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

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
