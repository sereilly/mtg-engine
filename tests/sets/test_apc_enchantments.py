"""Apocalypse enchantments.

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

#: Where the furniture these tests stand beside the Sanctuaries is printed.
#: Apocalypse first, so a name it prints is always its own card.
_W1G6_SETS = ("APC", "LEA", "LEG")


def _w1g6_find(set_pool, name):
    for w1g6_code in _W1G6_SETS:
        w1g6_found = set_pool(w1g6_code).get(name)
        if w1g6_found is not None:
            return w1g6_found
    raise KeyError(name)  # _w1g6_find


def _w1g6_table(set_pool, mine=(), theirs=(), interactive=False):
    """A two-seat table on seat 0's turn with *mine* / *theirs* already on the
    battlefield. Costs are off: every card here acts in an upkeep, for free."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="W1G6-A"), _W1G6PlayerState(name="W1G6-B"),
    ])
    w1g6_game.enforce_mana_costs = False
    w1g6_game.active_player_index = 0
    if interactive:
        w1g6_game.interactive_seats.add(0)
    w1g6_rows = []
    for w1g6_seat, w1g6_names in enumerate((mine, theirs)):
        w1g6_row = []
        for w1g6_name in w1g6_names:
            w1g6_perm = _W1G6Permanent(card=_w1g6_find(set_pool, w1g6_name))
            w1g6_game._put_permanent_onto_battlefield(w1g6_seat, w1g6_perm, None)
            w1g6_perm.metadata["summoning_sickness_turn"] = -99
            w1g6_row.append(w1g6_perm)
        w1g6_rows.append(w1g6_row)
    return w1g6_game, w1g6_rows[0], w1g6_rows[1]  # _w1g6_table


def _w1g6_upkeep(game, seat=0):
    """Run *seat*'s upkeep step and leave what triggered on the stack; returns
    the names of the sources there."""
    game.active_player_index = seat
    game.resolve_upkeep(seat, defer_priority=True)
    return [w1g6_item.card.name for w1g6_item in game.stack]  # _w1g6_upkeep


def _w1g6_enter(game, set_pool, seat, name):
    """Put one more permanent onto *seat*'s battlefield — "in response"."""
    w1g6_new = _W1G6Permanent(card=_w1g6_find(set_pool, name))
    game._put_permanent_onto_battlefield(seat, w1g6_new, None)
    return w1g6_new  # _w1g6_enter


@_w1g6_pytest.mark.parametrize("name", [
    "Ana Sanctuary", "Ceta Sanctuary", "Dega Sanctuary", "Necra Sanctuary",
    "Raka Sanctuary",
])
def test_w1g6_every_sanctuary_compiles_one_gated_two_armed_trigger(set_pool, name):
    """The cycle is one template: an upkeep trigger with an intervening "if"
    over either colour, whose effect is two arms of which exactly one runs.
    Neither arm may be empty — Raka Sanctuary's upgrade arm compiled to no
    instruction at all on arrival and the card still read supported."""
    program = _w1g6_compile(set_pool("APC")[name])
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "upkeep_self"
    payload = trigger.instruction.payload
    assert trigger.instruction.kind == "if_then"
    assert len(payload["intervening_if"]["filter"]["any_colors"]) == 2
    assert payload["then"] and payload["else"], payload


# Dega Sanctuary -------------------------------------------------------------


@_w1g6_pytest.mark.parametrize("mine, life", [
    ((), 20),
    # A land has no colour (CR 105.2c), whatever mana it makes.
    (("Swamp",), 20),
    (("Black Knight",), 22),
    (("Goblin King",), 22),
    # Both colours: 4 *instead* — "2 or 4 life, but never 6" (the card's
    # ruling, 2004-10-04).
    (("Black Knight", "Goblin King"), 24),
    # One permanent that is both colours is a black permanent and a red one.
    (("Lady Orca",), 24),
])
def test_w1g6_dega_sanctuary_gains_two_or_four_never_six(set_pool, mine, life):
    game, _mine, _theirs = _w1g6_table(set_pool, mine=("Dega Sanctuary",) + mine)

    triggered = _w1g6_upkeep(game)
    _w1g6_resolve_stack(game)

    assert triggered == (["Dega Sanctuary"] if life > 20 else [])
    assert [player.life for player in game.players] == [life, 20]


def test_w1g6_dega_sanctuary_reads_its_controllers_board_on_their_upkeep(set_pool):
    """"**Your** upkeep", "**you** control": an opponent's black creature is no
    condition, and the opponent's upkeep is no trigger."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=["Dega Sanctuary"], theirs=["Black Knight", "Goblin King"],
    )
    assert _w1g6_upkeep(game) == []

    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=["Dega Sanctuary", "Black Knight"],
    )
    assert _w1g6_upkeep(game, seat=1) == []
    assert [player.life for player in game.players] == [20, 20]


# Ana Sanctuary --------------------------------------------------------------


def test_w1g6_ana_sanctuary_asks_for_its_target_as_it_triggers(set_pool):
    """"…target creature gets +1/+1 until end of turn." The target is chosen
    as the trigger goes on the stack (CR 603.3d), from every creature on the
    table and nothing else; the answer is the creature pumped, and the pump
    ends with the turn."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer", "Forest"],
        theirs=["Hill Giant", "Sol Ring"], interactive=True,
    )
    giant = theirs[0]

    assert _w1g6_upkeep(game) == ["Ana Sanctuary"]
    (prompt,) = game.pending_choices
    assert prompt.kind == "trigger_target" and prompt.player_index == 0
    assert [entry["name"] for entry in prompt.data["targets"]] == [
        "Prodigal Sorcerer", "Hill Giant",
    ]
    # A land is not on the list, and naming it is not an answer.
    assert not game.confirm_trigger_target(0, permanent_id=mine[2].permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)
    _w1g6_resolve_stack(game)

    assert (giant.effective_power, giant.effective_toughness) == (4, 4)
    assert "Ana Sanctuary gives Hill Giant +1/+1 until end of turn" in game.log
    game.resolve_cleanup_step(0)
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)


@_w1g6_pytest.mark.parametrize("colours, size", [
    (("Prodigal Sorcerer",), (4, 4)),
    (("Black Knight",), (4, 4)),
    # "+1/+1 or +5/+5, never +6/+6" (the card's ruling, 2004-10-04).
    (("Prodigal Sorcerer", "Black Knight"), (8, 8)),
    (("Sivitri Scarzam",), (8, 8)),
])
def test_w1g6_ana_sanctuary_pumps_by_one_or_by_five(set_pool, colours, size):
    game, mine, theirs = _w1g6_table(
        set_pool, mine=("Ana Sanctuary",) + colours, theirs=["Hill Giant"],
        interactive=True,
    )
    _w1g6_upkeep(game)
    assert game.confirm_trigger_target(0, permanent_id=theirs[0].permanent_id)
    _w1g6_resolve_stack(game)

    assert (theirs[0].effective_power, theirs[0].effective_toughness) == size


def test_w1g6_ana_sanctuary_decides_the_upgrade_as_it_resolves(set_pool):
    """The target is announced with one colour in play; the second arrives in
    response. Which arm runs is asked at resolution (CR 608.2c: the "instead"
    sentence replaces the first as the effect is carried out), so the creature
    already chosen gets +5/+5."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer"], theirs=["Hill Giant"],
        interactive=True,
    )
    _w1g6_upkeep(game)
    assert game.confirm_trigger_target(0, permanent_id=theirs[0].permanent_id)
    _w1g6_enter(game, set_pool, 0, "Black Knight")
    _w1g6_resolve_stack(game)

    assert (theirs[0].effective_power, theirs[0].effective_toughness) == (8, 8)


def test_w1g6_ana_sanctuary_does_nothing_if_its_condition_is_gone(set_pool):
    """CR 603.4: the intervening "if" is checked again as the ability
    resolves. The only blue permanent leaves in response, and the creature the
    trigger was aimed at is not pumped."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer"], theirs=["Hill Giant"],
    )
    assert _w1g6_upkeep(game) == ["Ana Sanctuary"]
    game.remove_from_battlefield(mine[1])
    _w1g6_resolve_stack(game)

    assert (theirs[0].effective_power, theirs[0].effective_toughness) == (3, 3)
    assert "Ana Sanctuary ability did nothing: its condition is no longer true" in game.log


def test_w1g6_ana_sanctuary_never_pumps_a_bystander_for_an_illegal_pick(set_pool):
    """The upkeep step also takes a target as an answer in hand
    (``trigger_targets``). A pick the trigger could not have chosen — a land —
    used to be stamped on the stack object anyway, and the pump handler's
    fallback then took the first creature on *that seat's* battlefield: the
    opponent's Hill Giant, which nobody named. It is set aside and the trigger
    chooses for itself, from its own legal list."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer"], theirs=["Forest", "Hill Giant"],
    )
    sanctuary, sorcerer = mine
    giant = theirs[1]

    game.resolve_upkeep(
        0, defer_priority=True, trigger_targets={sanctuary.permanent_id: (1, 0)},
    )
    _w1g6_resolve_stack(game)

    assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    assert (sorcerer.effective_power, sorcerer.effective_toughness) == (2, 2)

    # …and a pick it could have chosen is the creature pumped.
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Ana Sanctuary", "Prodigal Sorcerer"], theirs=["Forest", "Hill Giant"],
    )
    game.resolve_upkeep(
        0, defer_priority=True, trigger_targets={mine[0].permanent_id: (1, 1)},
    )
    _w1g6_resolve_stack(game)
    assert (theirs[1].effective_power, theirs[1].effective_toughness) == (4, 4)


def test_w1g6_ana_sanctuary_with_no_creature_to_target_leaves_the_stack(set_pool):
    """The condition holds (Undertow is a blue permanent) and there is no
    creature anywhere: CR 603.3d removes a trigger that cannot choose its
    target."""
    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Ana Sanctuary", "Undertow"])

    assert _w1g6_upkeep(game) == []
    assert (
        "Ana Sanctuary's triggered ability was removed from the stack: "
        "it has no legal target (603.3d)"
    ) in game.log


# Raka Sanctuary -------------------------------------------------------------


@_w1g6_pytest.mark.parametrize("colours, damage", [
    (("White Knight",), 1),
    (("Prodigal Sorcerer",), 1),
    # "1 or 3 damage, but never 4" (the card's ruling, 2004-10-04). This arm
    # dealt nothing at all on arrival: "this enchantment deals 3 damage
    # instead" names no recipient, and it compiled to no instruction.
    (("White Knight", "Prodigal Sorcerer"), 3),
    (("Tobias Andrion",), 3),
])
def test_w1g6_raka_sanctuary_deals_one_or_three_to_the_chosen_creature(
    set_pool, colours, damage,
):
    game, mine, theirs = _w1g6_table(
        set_pool, mine=("Raka Sanctuary",) + colours, theirs=["Craw Wurm"],
        interactive=True,
    )
    wurm = theirs[0]

    assert _w1g6_upkeep(game) == ["Raka Sanctuary"]
    assert game.confirm_trigger_target(0, permanent_id=wurm.permanent_id)
    _w1g6_resolve_stack(game)

    assert wurm.damage_marked == damage
    assert f"Raka Sanctuary dealt {damage} damage to Craw Wurm" in game.log
    assert [player.life for player in game.players] == [20, 20]


def test_w1g6_raka_sanctuarys_three_kills_what_its_one_would_not(set_pool):
    """A headless seat aims the damage at an opponent's creature when there is
    one; three is lethal to a Hill Giant and one is not."""
    for colours, survives in (
        (("White Knight",), True),
        (("White Knight", "Prodigal Sorcerer"), False),
    ):
        game, _mine, theirs = _w1g6_table(
            set_pool, mine=("Raka Sanctuary",) + colours, theirs=["Hill Giant"],
        )
        _w1g6_upkeep(game)
        _w1g6_resolve_stack(game)
        game.check_state_based_actions()

        assert game.is_on_battlefield(theirs[0]) is survives
        assert [card.name for card in game.players[1].graveyard] == (
            [] if survives else ["Hill Giant"]
        )


# Ceta Sanctuary -------------------------------------------------------------


def _w1g6_ceta(set_pool, colours, interactive=False):
    """Ceta Sanctuary beside *colours*, two cards in hand and a library to
    draw from; returns the game after the upkeep trigger has resolved (the
    discard it asks for still owed)."""
    w1g6_game, _w1g6_mine, _w1g6_theirs = _w1g6_table(
        set_pool, mine=("Ceta Sanctuary",) + tuple(colours), interactive=interactive,
    )
    w1g6_player = w1g6_game.players[0]
    w1g6_player.hand = [_w1g6_find(set_pool, "Island"), _w1g6_find(set_pool, "Swamp")]
    w1g6_player.library = [_w1g6_find(set_pool, "Forest")] * 6
    w1g6_triggered = _w1g6_upkeep(w1g6_game)
    _w1g6_resolve_stack(w1g6_game)
    return w1g6_game, w1g6_triggered  # _w1g6_ceta


@_w1g6_pytest.mark.parametrize("colours, drawn", [
    (("Hill Giant",), 1),
    (("Grizzly Bears",), 1),
    # "One or two cards, but never three" (the card's ruling, 2004-10-04).
    (("Hill Giant", "Grizzly Bears"), 2),
    (("Jerrard of the Closed Fist",), 2),
])
def test_w1g6_ceta_sanctuary_draws_one_or_two_then_discards_one(set_pool, colours, drawn):
    """"…draw a card, then discard a card. If you control a red permanent and
    a green permanent, **instead** draw two cards, then discard a card." The
    whole first sentence is what the second replaces: one loot, of one size."""
    game, triggered = _w1g6_ceta(set_pool, colours, interactive=True)
    player = game.players[0]

    assert triggered == ["Ceta Sanctuary"]
    assert len(player.hand) == 2 + drawn and len(player.library) == 6 - drawn
    assert f"Ceta Sanctuary: W1G6-A drew {drawn} card(s)" in game.log
    # The discard is the player's to choose, and exactly one is owed.
    (prompt,) = game.pending_choices
    assert prompt.kind == "discard" and prompt.data["count"] == 1
    assert game.confirm_discard(0, [0])
    assert [card.name for card in player.graveyard] == ["Island"]
    assert len(player.hand) == 1 + drawn
    assert not game.pending_choices


def test_w1g6_ceta_sanctuary_without_red_or_green_does_not_trigger(set_pool):
    game, triggered = _w1g6_ceta(set_pool, ("Prodigal Sorcerer", "Forest"))

    assert triggered == []
    assert len(game.players[0].hand) == 2 and len(game.players[0].library) == 6


# Necra Sanctuary ------------------------------------------------------------


def test_w1g6_necra_sanctuary_asks_which_player_and_may_name_its_own(set_pool):
    """"…target player loses 1 life." Any player, the controller included; the
    choice is made as the trigger goes on the stack."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=["Necra Sanctuary", "Grizzly Bears"], interactive=True,
    )
    assert _w1g6_upkeep(game) == ["Necra Sanctuary"]
    (prompt,) = game.pending_choices
    assert [(entry["kind"], entry["seat"]) for entry in prompt.data["targets"]] == [
        ("player", 0), ("player", 1),
    ]
    assert game.confirm_trigger_target(0, seat=0)
    _w1g6_resolve_stack(game)

    assert [player.life for player in game.players] == [19, 20]


@_w1g6_pytest.mark.parametrize("colours, lost", [
    (("Grizzly Bears",), 1),
    (("White Knight",), 1),
    # "0, 1, or 3 life, but never 4" (the card's ruling, 2004-10-04).
    (("Grizzly Bears", "White Knight"), 3),
    # "One permanent that is both white and green will cause the player to be
    # affected by the lose 3 life portion." (The same ruling.)
    (("Jasmine Boreal",), 3),
])
def test_w1g6_necra_sanctuary_costs_the_chosen_player_one_or_three(set_pool, colours, lost):
    """"…**that player** loses 3 life instead": the upgrade lands on the player
    the first sentence targeted, and only one of the two sentences happens."""
    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=("Necra Sanctuary",) + colours, interactive=True,
    )
    _w1g6_upkeep(game)
    assert game.confirm_trigger_target(0, seat=1)
    _w1g6_resolve_stack(game)

    assert [player.life for player in game.players] == [20, 20 - lost]
    assert f"Necra Sanctuary: W1G6-B lost {lost} life (20 -> {20 - lost})" in game.log


def test_w1g6_necra_sanctuary_checks_its_condition_at_both_ends(set_pool):
    """CR 603.4. No green or white permanent: no trigger. One at the trigger
    and none at resolution: the ability does nothing. One at the trigger and
    both at resolution: three, to the player already chosen."""
    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Necra Sanctuary", "Black Knight"])
    assert _w1g6_upkeep(game) == []

    game, mine, _theirs = _w1g6_table(set_pool, mine=["Necra Sanctuary", "Grizzly Bears"])
    assert _w1g6_upkeep(game) == ["Necra Sanctuary"]
    game.remove_from_battlefield(mine[1])
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]
    assert "Necra Sanctuary ability did nothing: its condition is no longer true" in game.log

    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Necra Sanctuary", "Grizzly Bears"])
    _w1g6_upkeep(game)
    _w1g6_enter(game, set_pool, 0, "White Knight")
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 17]


# Phyrexian Arena ------------------------------------------------------------


def test_w1g6_phyrexian_arena_draws_and_bleeds_on_its_controllers_upkeep(set_pool):
    """"At the beginning of your upkeep, you draw a card and lose 1 life." Both
    halves, once, on its controller's upkeep and not the opponent's."""
    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Phyrexian Arena"])
    for player in game.players:
        player.library = [_w1g6_find(set_pool, "Forest")] * 4

    assert _w1g6_upkeep(game) == ["Phyrexian Arena"]
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [19, 20]
    assert [len(player.hand) for player in game.players] == [1, 0]
    assert "Phyrexian Arena: W1G6-A lost 1 life (20 -> 19)" in game.log

    assert _w1g6_upkeep(game, seat=1) == []
    assert [player.life for player in game.players] == [19, 20]
    assert [len(player.hand) for player in game.players] == [1, 0]

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
