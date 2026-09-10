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
    resolve_stack(game)
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
    resolve_stack(game)
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


# --- W2G2: a type chosen during the untap step ---
import pytest as _w2g2_pytest

from engine import Game as _W2G2Game
from engine import PlayerState as _W2G2PlayerState
from engine.models import Permanent as _W2G2Permanent
from engine.oracle import compile_card_oracle as _w2g2_compile
from engine.phases.untap_step import UNTAP_TYPE_CHOICE_STAMP as _W2G2_STAMP


def _w2g2_storage_board(set_pool, *, interactive=(), matrix_tapped=False):
    """Storage Matrix plus one tapped land, creature and artifact per seat.

    Both seats get the same three so a test can watch the *other* player's untap
    step read the same source — "each player chooses … during their untap step"
    is one card asking twice, not two records. Returns the game, the Matrix and
    a name-keyed view of seat 0's three, ending in a dict so no other group's
    helper tail matches this one.
    """
    uds = set_pool("UDS")
    lea = set_pool("LEA")
    matrix = _W2G2Permanent(card=uds["Storage Matrix"], tapped=matrix_tapped)

    def _three():
        return [
            _W2G2Permanent(card=lea["Mountain"], tapped=True),
            _W2G2Permanent(card=lea["Grizzly Bears"], tapped=True),
            _W2G2Permanent(card=lea["Black Lotus"], tapped=True),
        ]

    mine = _three()
    theirs = _three()
    game = _W2G2Game(players=[
        _W2G2PlayerState(name="W2G2-A", battlefield=[matrix, *mine], life=20),
        _W2G2PlayerState(name="W2G2-B", battlefield=theirs, life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, matrix, {
        "land": mine[0], "creature": mine[1], "artifact": mine[2],
        "their_land": theirs[0], "their_creature": theirs[1],
    }


def test_storage_matrix_is_supported_as_a_derived_untap_restriction(set_pool):
    """Both printed sentences are one CR 502 restriction, and it has no
    instruction: the untap step reads the table, so the whole card's support
    rests on `derived_static_rule`."""
    program = _w2g2_compile(set_pool("UDS")["Storage Matrix"])

    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["derived_static_rule"]
    assert program.instructions[0].value == "untap_restrictions"


def test_storage_matrix_lets_only_the_named_type_untap(set_pool):
    """"That player can untap only permanents of the chosen type this step."

    The Mountain, the Bears and the Lotus are one each of the three printed
    options, so naming one has to leave the other two tapped — and the Matrix
    itself is an artifact, which is why it is left untapped here rather than
    being part of the count.
    """
    game, matrix, board = _w2g2_storage_board(set_pool, interactive={0})
    assert game.arm_untap_type_choices(0) is True
    assert game.confirm_card_type_choice(0, "creature")

    game.resolve_untap_step(0)

    assert not board["creature"].tapped
    assert board["land"].tapped, game.log
    assert board["artifact"].tapped, game.log


def test_storage_matrix_offers_exactly_the_three_printed_options(set_pool):
    """The prompt is bounded by the card's sentence, not by a card-type catalog.

    A seat that could answer "enchantment" would name a type Storage Matrix
    never offered — and the untap step would then spend it as if it had.
    """
    game, matrix, _board = _w2g2_storage_board(set_pool, interactive={0})
    game.arm_untap_type_choices(0)

    owed = game.waiting_prompt(0)
    assert owed is not None
    assert owed.data["options"] == ["artifact", "creature", "land"]
    assert owed.data["card_name"] == "Storage Matrix"
    assert not game.confirm_card_type_choice(0, "enchantment")


def test_storage_matrix_asks_nothing_on_a_turn_it_is_tapped(set_pool):
    """"**As long as this artifact is untapped**, each player chooses…"

    Tapping the Matrix is how a player buys one clean untap step, so a turn
    where it is tapped owes no choice and restricts nothing.
    """
    game, matrix, board = _w2g2_storage_board(
        set_pool, interactive={0}, matrix_tapped=True
    )

    assert game.arm_untap_type_choices(0) is False
    game.resolve_untap_step(0)

    assert not board["land"].tapped
    assert not board["creature"].tapped
    assert not board["artifact"].tapped
    assert not matrix.tapped, "and the Matrix untaps like anything else"


def test_storage_matrix_asks_each_player_on_their_own_untap_step(set_pool):
    """One source, two seats, two answers — each spent on the step that made it.

    The answer is recorded on the Matrix, so what keeps seat 0's word out of
    seat 1's step is the `(turn, seat)` stamp that makes the step re-ask.
    """
    game, matrix, board = _w2g2_storage_board(set_pool, interactive={0, 1})
    game.arm_untap_type_choices(0)
    assert game.confirm_card_type_choice(0, "land")
    game.resolve_untap_step(0)
    assert not board["land"].tapped and board["creature"].tapped

    game.turn += 1
    assert game.arm_untap_type_choices(1) is True
    assert matrix.metadata[_W2G2_STAMP] == (game.turn, 1)
    assert game.confirm_card_type_choice(1, "creature")
    game.resolve_untap_step(1)

    assert not board["their_creature"].tapped
    assert board["their_land"].tapped, "seat 1 named creature"


def test_storage_matrix_default_never_blocks_a_headless_seat(set_pool):
    """A seat nobody can ask still gets a real answer, taken inline.

    `card_type_choice` is `default_at_arm`, so a non-interactive seat never
    queues the prompt at all — which is what makes the AI simulator and every
    headless test need no untap-step code of their own.
    """
    game, matrix, board = _w2g2_storage_board(set_pool)

    assert game.arm_untap_type_choices(0) is False
    assert game.pending_choices == []
    assert matrix.metadata["chosen_card_type"] in {"artifact", "creature", "land"}

    game.resolve_untap_step(0)
    untapped = [name for name in ("land", "creature", "artifact") if not board[name].tapped]
    assert len(untapped) == 1, (untapped, game.log)


@_w2g2_pytest.mark.parametrize("named", ["artifact", "creature", "land"])
def test_storage_matrix_spends_every_printed_option(set_pool, named):
    """Each of the three words really is spendable, and each leaves the other
    two down — the sweep a single worked example would not make."""
    game, matrix, board = _w2g2_storage_board(set_pool, interactive={0})
    game.arm_untap_type_choices(0)
    assert game.confirm_card_type_choice(0, named)
    game.resolve_untap_step(0)

    assert not board[named].tapped
    assert all(board[other].tapped for other in {"artifact", "creature", "land"} - {named})
