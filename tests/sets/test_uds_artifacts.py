"""Urza's Destiny artifacts.

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

Cards come from `set_pool("UDS")` / `set_cards("UDS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: name-matched search, graveyards and libraries ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec
from tests.helpers import resolve_stack


@pytest.fixture
def _g2a_lea(set_pool):
    """One Alpha card by name, to fill a graveyard with something that is not
    an Urza's Destiny card."""
    return lambda name: set_pool("LEA")[name]


def test_thran_foundry_shuffles_a_named_players_whole_graveyard_back(set_pool, _g2a_lea):
    """"{1}, {T}, Exile this artifact: Target player shuffles their graveyard
    into their library."

    Feldon's Cane's whole-zone move with a *subject* printed in front of it,
    which is the only thing this card adds — so the assertion is that every card
    moved and that the seat it moved for is the one the ability named.
    """
    foundry = Permanent(card=set_pool("UDS")["Thran Foundry"])
    game = Game(players=[
        PlayerState(
            name="G2a-A", battlefield=[foundry, Permanent(card=_g2a_lea("Mountain"))],
            graveyard=[_g2a_lea("Black Lotus")],
        ),
        PlayerState(
            name="G2a-B",
            graveyard=[_g2a_lea("Healing Salve"), _g2a_lea("Lightning Bolt")],
            library=[_g2a_lea("Island")],
        ),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    result = game.activate_permanent_ability(0, "Thran Foundry", target_player_index=1)
    assert result.supported, result
    resolve_stack(game)
    assert game.players[1].graveyard == []
    assert sorted(c.name for c in game.players[1].library) == [
        "Healing Salve", "Island", "Lightning Bolt",
    ]
    # The activator's own graveyard is not the one the ability named.
    assert [c.name for c in game.players[0].graveyard] == ["Black Lotus"]
    # "Exile this artifact" is a cost (CR 601.2h), so it is gone either way.
    assert [c.name for c in game.players[0].exile] == ["Thran Foundry"]


def test_thran_foundry_raises_a_player_picker(set_pool):
    """The other half of a printed "target player": the ability has to *ask*.

    A supported card whose activation derives no spec is one the browser
    activates with nobody named — the Roots class, one path over.
    """
    program = compile_card_oracle(set_pool("UDS")["Thran Foundry"])
    assert program.supported
    assert len(program.activated_abilities) == 1
    spec = derive_activation_spec(program.activated_abilities[0])
    assert spec is not None and spec.get("kind") == "player", spec


# --- W1G5: player-directed effects, and a cost reduction nothing implemented ---
import pytest

from engine import Game, PlayerState
from engine.cost_modifiers import cost_reduction_for_cast
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g5_artifact_game(*players: PlayerState) -> Game:
    """A duel with mana enforcement off, for this block's artifacts."""
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    return game


def test_urzas_incubator_discounts_only_the_chosen_types_creature_spells(set_pool):
    """"Creature spells of the chosen type cost {2} less to cast."

    The line was **unclaimed** when UDS was ingested: the card compiled as
    supported off its entry choice alone, asked for a type, and then taxed
    nothing — the population `parse_coverage.py` is the only instrument that can
    see, because a card is supported when *any* of its lines is.

    Both directions in one game, because the reduction has to be narrowed by a
    word that is not in the sentence: a Sliver is discounted and a Bear, which
    is equally a creature spell, is not.
    """
    pool = set_pool("UDS")
    program = compile_card_oracle(pool["Urza's Incubator"])
    assert program.supported, program.reason

    game = _g5_artifact_game(
        PlayerState(name="P1", hand=[pool["Urza's Incubator"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.cast_from_hand(0, "Urza's Incubator")
    # No drain: the resolution is held on the stack while this seat owes its
    # answer (CR 608.2), and `resolve_stack` answers what blocks the stack —
    # it would take the default out from under the confirm below.
    assert game.confirm_enter_choice(0, creature_type="sliver"), game.log

    sliver = next(c for c in set_pool("TMP").values() if "Sliver" in c.type_line)
    bear = set_pool("LEA")["Grizzly Bears"]

    discounted, names = cost_reduction_for_cast(game, 0, sliver)
    assert discounted.generic == 2, (sliver.name, discounted)
    assert names == ["Urza's Incubator"], names

    untouched, _ = cost_reduction_for_cast(game, 0, bear)
    assert untouched.generic == 0, untouched


def test_urzas_incubator_discounts_every_seats_creature_spells(set_pool):
    """The sentence names no caster, so CR 601.2f charges nobody in particular.

    An opponent's Sliver is discounted too — the tax loop scans *every*
    battlefield and only a printed "you cast" narrows it, so this is the
    difference between reading the sentence and reading the card's owner.
    """
    pool = set_pool("UDS")
    game = _g5_artifact_game(
        PlayerState(name="P1", hand=[pool["Urza's Incubator"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.cast_from_hand(0, "Urza's Incubator")
    # No drain: the resolution is held on the stack while this seat owes its
    # answer (CR 608.2), and `resolve_stack` answers what blocks the stack —
    # it would take the default out from under the confirm below.
    assert game.confirm_enter_choice(0, creature_type="sliver"), game.log

    sliver = next(c for c in set_pool("TMP").values() if "Sliver" in c.type_line)
    across_the_table, _ = cost_reduction_for_cast(game, 1, sliver)
    assert across_the_table.generic == 2, across_the_table


def test_a_chosen_type_reduction_with_no_word_recorded_discounts_nothing(set_pool):
    """A permanent whose CR 614.1c choice is missing narrows to nothing.

    The safe direction, and the one that decides whether a bug here is visible:
    dropping the narrowing would take {2} off every creature spell in the game,
    which no test of the discounted case can catch.
    """
    pool = set_pool("UDS")
    game = _g5_artifact_game(
        PlayerState(name="P1", hand=[pool["Urza's Incubator"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    game.cast_from_hand(0, "Urza's Incubator")
    resolve_stack(game)
    incubator = game.players[0].battlefield[-1]
    incubator.metadata["chosen_creature_type"] = ""

    nothing, names = cost_reduction_for_cast(
        game, 0, set_pool("LEA")["Grizzly Bears"]
    )
    assert nothing.generic == 0, nothing
    assert names == [], names
