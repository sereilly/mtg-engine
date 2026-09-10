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


# --- W2G3: a chosen number and a chosen colour, read back ---
import pytest

from engine import Game, PlayerState
from engine.grammar import lower_ability, parse_line
from engine.grammar.errors import LoweringError
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import CHOSEN_COLOR_THIS_WAY, CHOSEN_NUMBER_THIS_WAY


def _w2g3_glass_table(set_pool, opponent_hand, *, interactive=True, extra=()):
    """Scrying Glass on P1's board and a known hand across the table.

    The opponent's hand is the whole subject of the card, so it is named per
    test rather than dealt; the library is only there so a successful guess has
    a card to draw. Returns the game and the Glass, which every caller wants.
    """
    pool = set_pool("UDS")
    lea = set_pool("LEA")
    glass = Permanent(card=pool["Scrying Glass"])
    p1 = PlayerState(
        name="P1", battlefield=[glass], library=[lea["Forest"]] * 10, life=20
    )
    p2 = PlayerState(
        name="P2", hand=list(opponent_hand), library=[lea["Forest"]] * 10, life=20
    )
    game = Game(players=[p1, p2])
    game.interactive_seats = {0} if interactive else set()
    game.enforce_mana_costs = False
    for permanent in extra:
        game._put_permanent_onto_battlefield(1, permanent, None)
    game._settle()
    return game, glass


def _w2g3_activate_the_glass(game):
    """Activate the Glass at its only opponent and hand back the result."""
    return game.activate_permanent_ability(
        0, "Scrying Glass", permanent_index=0, target_player_index=1
    )


def test_scrying_glass_reads_its_whole_printed_line(set_pool):
    """Four sentences, four steps, and no fused kind among them.

    "Choose a number greater than 0 and a color. Target opponent reveals their
    hand. If that opponent reveals exactly the chosen number of cards of the
    chosen color, you draw a card."

    The conjoined first sentence is two statements, not one: they are answered
    separately, recorded separately and read back separately, and the printed
    "and" is an elided second verb rather than a second effect kind.
    """
    program = compile_card_oracle(set_pool("UDS")["Scrying Glass"])
    assert program.supported, program.reason
    ability = program.activated_abilities[0]
    assert ability.cost.requires_tap
    assert ability.cost.mana["generic"] == 3
    steps = ability.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_number", "choose_color", "reveal_hand", "if_then",
    ]
    assert steps[0].payload == {"minimum": 1, "maximum": None}, (
        "'greater than 0' is a floor of one and no ceiling at all (CR 107.1b)"
    )


def test_scrying_glass_draws_when_the_guess_is_exact(set_pool):
    """One red card in the hand, "one" and red named: the guess is right."""
    lea = set_pool("LEA")
    game, _ = _w2g3_glass_table(
        set_pool, [lea["Lightning Bolt"], lea["Island"], lea["Ancestral Recall"]]
    )
    assert _w2g3_activate_the_glass(game).supported
    assert game.confirm_number_choice(0, 1), game.log
    assert game.confirm_color_choice(0, "R"), game.log
    assert len(game.players[0].hand) == 1, game.log


def test_scrying_glass_draws_nothing_when_the_number_is_wrong(set_pool):
    """The same hand and the same colour, one number out.

    "Exactly" is the printed comparison, so a guess of two against one red card
    fails - and the branch not running is the whole of what the card does then.
    """
    lea = set_pool("LEA")
    game, _ = _w2g3_glass_table(
        set_pool, [lea["Lightning Bolt"], lea["Island"], lea["Ancestral Recall"]]
    )
    assert _w2g3_activate_the_glass(game).supported
    assert game.confirm_number_choice(0, 2), game.log
    assert game.confirm_color_choice(0, "R"), game.log
    assert game.players[0].hand == [], game.log


def test_scrying_glass_counts_a_cards_colour_and_not_its_mana(set_pool):
    """A Mountain in a hand is not a red card (CR 202.2).

    A land's colour comes from the mana symbols in its **cost**, and a basic
    land has none - so a hand of two Mountains and a Lightning Bolt holds one
    red card, not three. The card that produces red mana is the trap here, and
    it is the difference between reading a colour and reading a mana symbol.
    """
    lea = set_pool("LEA")
    game, _ = _w2g3_glass_table(
        set_pool, [lea["Mountain"], lea["Mountain"], lea["Lightning Bolt"]]
    )
    assert _w2g3_activate_the_glass(game).supported
    assert game.confirm_number_choice(0, 1), game.log
    assert game.confirm_color_choice(0, "R"), game.log
    assert len(game.players[0].hand) == 1, game.log


def test_scrying_glass_waits_for_both_answers_before_it_counts(set_pool):
    """The hand is not revealed until the colour has been named.

    Both choices are made while the ability resolves (CR 608.2d) and the
    sentence that spends them is a later step of the *same* resolution, so the
    resolution has to stop at each. A prompt that let the steps behind it run
    would count a revealed hand against the deterministic default and then
    record the player's real answer over the top of a question already
    answered - a prompt that lies.
    """
    lea = set_pool("LEA")
    game, _ = _w2g3_glass_table(set_pool, [lea["Lightning Bolt"]])
    assert _w2g3_activate_the_glass(game).supported

    assert [choice.kind for choice in game.pending_choices] == ["number_choice"]
    assert not any("reveals their hand" in line for line in game.log), game.log

    assert game.confirm_number_choice(0, 1), game.log
    assert [choice.kind for choice in game.pending_choices] == ["color_choice"]
    assert not any("reveals their hand" in line for line in game.log), game.log

    assert game.confirm_color_choice(0, "R"), game.log
    assert any("reveals their hand" in line for line in game.log), game.log
    assert len(game.players[0].hand) == 1, game.log


def test_scrying_glass_takes_the_answer_over_the_default(set_pool):
    """The player's colour, not the one the arming stamped.

    The default names the colour the opponents hold most of among nontoken
    permanents - green here - and the answer is red. If the count ran on the
    default it would find no green card and draw nothing, which is the failure
    this chain of suspensions exists to make impossible.
    """
    lea = set_pool("LEA")
    green = Permanent(card=lea["Llanowar Elves"])
    game, _ = _w2g3_glass_table(set_pool, [lea["Lightning Bolt"]], extra=[green])
    glass_permanent = game.players[0].battlefield[0]
    assert _w2g3_activate_the_glass(game).supported
    assert game.confirm_number_choice(0, 1), game.log
    assert glass_permanent.metadata["chosen_color"] == "G", (
        "the default is stamped before the prompt, so a dismissed prompt still "
        "has an answer"
    )
    assert game.confirm_color_choice(0, "R"), game.log
    assert glass_permanent.metadata["chosen_color"] == "R", game.log
    assert len(game.players[0].hand) == 1, game.log


def test_scrying_glass_counts_a_hand_a_static_has_recoloured(set_pool):
    """"...nonland cards you own that aren't on the battlefield" (Celestial Dawn).

    The colour of a card in a hand is CR 105's question about an object, not the
    printed field: with the Dawn out on its owner's side their Lightning Bolt is
    white, and a Glass naming white finds it. Read off the printed colours it
    would find nothing at all.
    """
    lea = set_pool("LEA")
    dawn = Permanent(card=set_pool("MIR")["Celestial Dawn"])
    game, _ = _w2g3_glass_table(set_pool, [lea["Lightning Bolt"]], extra=[dawn])
    assert _w2g3_activate_the_glass(game).supported
    assert game.confirm_number_choice(0, 1), game.log
    assert game.confirm_color_choice(0, "W"), game.log
    assert len(game.players[0].hand) == 1, game.log


def test_scrying_glass_answers_itself_for_a_seat_nobody_asks(set_pool):
    """A headless seat is never blocked: both defaults are stamped at arming.

    The number defaults to the printed floor and the colour to the one the
    opponents hold most of, so the resolution runs to its end with real answers
    rather than waiting for a player who does not exist.
    """
    lea = set_pool("LEA")
    game, _ = _w2g3_glass_table(
        set_pool, [lea["Lightning Bolt"]], interactive=False
    )
    assert _w2g3_activate_the_glass(game).supported
    game.auto_resolve_pending_choices()
    assert game.pending_choices == [], game.pending_choices
    assert any("reveals their hand" in line for line in game.log), game.log


def test_the_chosen_number_and_colour_are_recorded_where_the_count_looks():
    """Both steps write the resolution's scratchpad, not only the permanent.

    A permanent's ``chosen_number`` / ``chosen_color`` is its **standing**
    answer, which is right for the readers that keep asking (Shapeshifter's P/T,
    Chromatic Armor's shield) and wrong for a sentence asking what *this*
    activation named. The declaration is what the reader's gate is checked
    against, so a producer that stopped recording would make the clause refuse
    rather than silently count nothing.
    """
    from engine.grammar.lowering._records import produced_keys
    from engine.oracle_types import OracleInstruction

    assert CHOSEN_NUMBER_THIS_WAY in produced_keys(
        OracleInstruction("choose_number", "", {})
    )
    assert CHOSEN_COLOR_THIS_WAY in produced_keys(
        OracleInstruction("choose_color", "", {})
    )


def test_the_count_refuses_with_nothing_in_front_of_it():
    """A back-reference names its producers or refuses.

    Missing any of the three, the clause is answerable and wrong: no number
    compares against nothing, no colour counts every card or none, and no reveal
    counts an empty record - every one of them a branch that never runs on a
    card reporting itself supported.
    """
    bare = parse_line(
        "{3}, {T}: If that opponent reveals exactly the chosen number of cards "
        "of the chosen color, you draw a card."
    )
    with pytest.raises(LoweringError) as refusal:
        lower_ability(bare)
    message = str(refusal.value)
    assert "number chosen" in message and "colour chosen" in message, message
    assert "hand revealed" in message, message
# --- end W2G3 ---
