"""Exodus enchantments.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: the Oaths, and the seat a trigger's comparison is against ---
import pytest

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g1e_card(name, type_line="Creature — Bear"):
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1",
             "toughness": "1"},
    )


def _g1e_plains(name="Plains"):
    return _g1e_card(name, "Basic Land — Plains")


def _g1e_table(set_pool, oath, *, seat0=(), seat1=(), lives=(20, 20),
               hands=((), ()), graveyards=((), ()), libraries=(None, None)):
    """*oath* under seat 0's control, at a two-seat table seat 1 is about to
    take a turn at — so the trigger fires for a player who is **not** the
    enchantment's controller, which is the whole question these cards ask."""
    enchantment = Permanent(card=set_pool("EXO")[oath])
    players = []
    for index, (own, life, hand, graveyard, library) in enumerate(
        zip((seat0, seat1), lives, hands, graveyards, libraries)
    ):
        battlefield = [Permanent(card=c) for c in own]
        if index == 0:
            battlefield.insert(0, enchantment)
        players.append(PlayerState(
            name="P%d" % index, life=life, battlefield=battlefield,
            hand=list(hand), graveyard=list(graveyard),
            library=list(library if library is not None
                         else [_g1e_card("Deck%d %d" % (index, i))
                               for i in range(6)]),
        ))
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._settle()
    return game, players[0], players[1]


def _g1e_take_upkeep(game, seat):
    """Start *seat*'s turn and drain everything the upkeep trigger arms."""
    game.start_turn(seat)
    for _ in range(6):
        game.auto_resolve_pending_choices()
        if not resolve_stack(game):
            break
    game.auto_resolve_pending_choices()
    return game


@pytest.mark.parametrize("oath", [
    "Oath of Druids", "Oath of Ghouls", "Oath of Lieges", "Oath of Mages",
    "Oath of Scholars",
])
def test_every_oath_is_supported(set_pool, oath):
    program = compile_card_oracle(set_pool("EXO")[oath])
    assert program.supported, program.reason


def test_oath_of_lieges_fetches_for_the_player_whose_upkeep_it_is(set_pool):
    """"At the beginning of each player's upkeep, that player chooses target
    player who controls more lands than they do and is their opponent. The
    first player may search their library for a basic land card…"

    The payoff belongs to **the first player** — the seat whose upkeep it is —
    and not to the enchantment's controller. An offer made to one seat and
    carried out by another is the failure this card is the test for.
    """
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Lieges",
        seat0=(_g1e_plains("Theirs A"), _g1e_plains("Theirs B")),
        libraries=(None, [_g1e_plains("Fetched")]
                   + [_g1e_card("R%d" % i) for i in range(5)]),
    )

    _g1e_take_upkeep(game, 1)

    assert "Fetched" in [p.card.name for p in seat1.battlefield]
    assert "Fetched" not in [p.card.name for p in seat0.battlefield]


def test_oath_of_lieges_does_nothing_when_nobody_is_ahead(set_pool):
    """CR 603.3c: a triggered ability with no legal target is removed from the
    stack. Without the comparison in the picker every upkeep would fetch."""
    game, _seat0, seat1 = _g1e_table(set_pool, "Oath of Lieges")

    _g1e_take_upkeep(game, 1)

    assert [p.card.name for p in seat1.battlefield] == []
    assert any("no legal target" in line for line in game.log), game.log


def test_oath_of_scholars_empties_and_refills_the_upkeep_players_hand(set_pool):
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Scholars",
        hands=([_g1e_card("Mine %d" % i) for i in range(4)],
               [_g1e_card("Theirs")]),
    )

    _g1e_take_upkeep(game, 1)

    assert len(seat0.hand) == 4, "the enchantment's controller keeps their hand"
    assert [c.name for c in seat1.graveyard] == ["Theirs"]
    assert len(seat1.hand) == 3


def test_oath_of_mages_pings_the_second_player(set_pool):
    """"The first player may have this enchantment deal 1 damage to **the
    second player**." Wizards' own disambiguator: the first player chose, the
    second was chosen, and the damage goes to the one that was chosen.
    """
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Mages", lives=(25, 15),
    )

    _g1e_take_upkeep(game, 1)

    assert seat0.life == 24
    assert seat1.life == 15


def test_oath_of_ghouls_regrows_for_the_player_who_has_lost_more(set_pool):
    """"…chooses target player whose graveyard has fewer creature cards in it
    than their graveyard does". The comparison runs the *other* way from the
    rest of the cycle — the chooser must be **ahead** on dead creatures — so
    reading it as "more" would hand the regrowth to the wrong seat.
    """
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Ghouls",
        graveyards=([_g1e_card("Theirs A")],
                    [_g1e_card("Mine %d" % i) for i in range(3)]),
    )

    _g1e_take_upkeep(game, 1)

    assert len(seat1.hand) == 1
    assert len(seat1.graveyard) == 2
    assert seat0.hand == []


def test_oath_of_ghouls_is_silent_when_the_upkeep_player_is_behind(set_pool):
    game, _seat0, seat1 = _g1e_table(
        set_pool, "Oath of Ghouls",
        graveyards=([_g1e_card("Theirs %d" % i) for i in range(3)],
                    [_g1e_card("Mine")]),
    )

    _g1e_take_upkeep(game, 1)

    assert seat1.hand == []
    assert len(seat1.graveyard) == 1


def test_oath_of_druids_reanimates_off_the_upkeep_players_own_library(set_pool):
    """"The first player may reveal cards from the top of **their** library
    until **they** reveal a creature card. If the first player does, that
    player puts that card onto the battlefield and all other cards revealed
    this way into their graveyard."

    Every pronoun in that procedure is the upkeep player's, including the
    library the run reads and the graveyard the rest lands in.
    """
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Druids",
        seat0=(_g1e_card("Big A"), _g1e_card("Big B")),
        libraries=(None, [_g1e_plains("Skipped 1"), _g1e_plains("Skipped 2"),
                          _g1e_card("Reanimated")]
                   + [_g1e_card("R%d" % i) for i in range(3)]),
    )

    _g1e_take_upkeep(game, 1)

    assert [p.card.name for p in seat1.battlefield] == ["Reanimated"]
    assert [c.name for c in seat1.graveyard] == ["Skipped 1", "Skipped 2"]
    assert seat0.graveyard == []


def test_an_oath_fires_on_its_own_controllers_upkeep_too(set_pool):
    """"At the beginning of **each player's** upkeep" — the enchantment's
    controller is one of them, and is behind here."""
    game, seat0, _seat1 = _g1e_table(
        set_pool, "Oath of Lieges",
        seat1=(_g1e_plains("Theirs A"), _g1e_plains("Theirs B")),
        libraries=([_g1e_plains("Fetched")]
                   + [_g1e_card("L%d" % i) for i in range(5)], None),
    )

    _g1e_take_upkeep(game, 0)

    assert "Fetched" in [p.card.name for p in seat0.battlefield]


def test_the_oaths_ask_the_upkeep_player_which_opponent(set_pool):
    """"**That player** chooses target player…" — CR 601.2c's announcement,
    made by the seat the card names rather than by the ability's controller.
    Only visible with three seats and two legal answers: at two seats the
    comparison leaves one candidate and who picks cannot be observed.
    """
    enchantment = Permanent(card=set_pool("EXO")["Oath of Mages"])
    players = [
        PlayerState(name="P0", life=30, battlefield=[enchantment],
                    library=[_g1e_card("L%d" % i) for i in range(5)]),
        PlayerState(name="P1", life=10,
                    library=[_g1e_card("R%d" % i) for i in range(5)]),
        PlayerState(name="P2", life=30,
                    library=[_g1e_card("S%d" % i) for i in range(5)]),
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1, 2}
    game._settle()

    game.start_turn(1)

    prompts = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert len(prompts) == 1, [c.kind for c in game.pending_choices]
    assert prompts[0].player_index == 1, (
        "the upkeep player announces the target, not the Oath's controller"
    )
    assert sorted(
        target["seat"] for target in prompts[0].data["targets"]
    ) == [0, 2], "both opponents who are ahead on life are offered"


def test_a_printed_chooser_beside_target_opponent_refuses(set_pool):
    """Two seats in one phrase. "Target opponent" excludes whoever announces,
    and a printed chooser is the card saying that is somebody other than the
    ability's controller — so the word would be enforced against a seat the
    card does not name. Refused rather than resolved to either half.
    """
    line = compile_line(
        "that player chooses target opponent who has more life than they do. "
        "the first player may draw a card"
    )
    assert not line.instructions
    assert line.lowering_error or line.parse_error
