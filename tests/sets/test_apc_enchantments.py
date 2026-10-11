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

from engine import Game as _w1g5e_Game, PlayerState as _w1g5e_Player
from engine.models import Permanent as _w1g5e_Permanent
from tests.helpers import _mk_card as _w1g5e_mk_card
from tests.helpers import resolve_stack as _w1g5e_resolve_stack

_W1G5E_REQUIRED = "must be chosen as a target if able"


def _w1g5e_duel(mine=(), theirs=(), *, hand0=(), hand1=(), active=0):
    """Two boards placed and unsick, *active*'s turn begun."""
    board0 = [_w1g5e_Permanent(card=card) for card in mine]
    board1 = [_w1g5e_Permanent(card=card) for card in theirs]
    filler = _w1g5e_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5e_Game(players=[
        _w1g5e_Player(name="P0", battlefield=board0, hand=list(hand0), library=[filler] * 10),
        _w1g5e_Player(name="P1", battlefield=board1, hand=list(hand1), library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._settle()
    return game, board0, board1  # W1G5 enchantments: the duel


def test_coalition_flag_makes_its_creature_a_flagbearer_and_the_only_target(set_pool):
    """Coalition Flag {W} Aura — "Enchant creature you control / Enchanted
    creature is a Flagbearer. / While an opponent is choosing targets …, that
    player must choose at least one Flagbearer on the battlefield if able."

    The Bears under the Flag are a Flagbearer **and no longer a Bear** (CR
    205.1a: a sentence that sets a subtype without "in addition to its other
    types" replaces the creature types it had). The opponent's Bolt may go
    nowhere else. Disenchant is not bound — the Bears are no legal target for
    it — and with the Flag gone the Bears are Bears and the next Bolt is free."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5e_duel(
        [lea["Grizzly Bears"], lea["Savannah Lions"]], [],
        hand0=[apc["Coalition Flag"]],
        hand1=[lea["Lightning Bolt"], lea["Disenchant"], lea["Lightning Bolt"]],
    )
    bears, lions = mine
    assert bears.has_type("bear") and not bears.has_type("flagbearer")
    assert game.cast_from_hand(
        0, "Coalition Flag", target_permanent_ids=[bears.permanent_id]
    ).supported
    flag = next(p for p in game.controlled_by(0) if p.card.name == "Coalition Flag")
    assert bears.has_type("flagbearer") and bears.is_creature
    assert not bears.has_type("bear")
    assert lions.has_type("cat") and not lions.has_type("flagbearer")

    offered = game.cast_target_spec(1, lea["Lightning Bolt"])["valid_targets"]
    assert [(entry["seat"], entry["name"]) for entry in offered] == [(0, "Grizzly Bears")]
    for announcement in (
        {"target_player_index": 0},
        {"target_permanent_ids": [lions.permanent_id]},
    ):
        refused = game.queue_from_hand(1, "Lightning Bolt", **announcement)
        assert not refused.supported and _W1G5E_REQUIRED in refused.details, refused
        assert "Coalition Flag" in refused.details

    assert game.cast_from_hand(
        1, "Disenchant", target_permanent_ids=[flag.permanent_id]
    ).supported
    assert bears.has_type("bear") and not bears.has_type("flagbearer")
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 17


def test_coalition_flag_enchants_only_its_controllers_own_creature(set_pool):
    """"Enchant creature **you control**": the picker offers the caster's own
    creatures, and a cast at an opponent's is refused with the Aura in hand."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5e_duel(
        [lea["Grizzly Bears"]], [lea["Savannah Lions"]], hand0=[apc["Coalition Flag"]],
    )
    offered = game.cast_target_spec(0, apc["Coalition Flag"])["valid_targets"]
    assert [(entry["seat"], entry["name"]) for entry in offered] == [(0, "Grizzly Bears")]
    refused = game.queue_from_hand(
        0, "Coalition Flag", target_permanent_ids=[theirs[0].permanent_id]
    )
    assert not refused.supported
    assert [card.name for card in game.players[0].hand] == ["Coalition Flag"]


def test_the_flags_own_controller_is_not_bound_by_it(set_pool):
    """"While **an opponent** is choosing targets": the Flag's controller pumps
    their other creature beside the flagged one."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5e_duel(
        [lea["Grizzly Bears"], lea["Savannah Lions"]], [],
        hand0=[apc["Coalition Flag"], lea["Giant Growth"]],
    )
    bears, lions = mine
    assert game.cast_from_hand(
        0, "Coalition Flag", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[lions.permanent_id]
    ).supported
    assert (lions.effective_power, lions.effective_toughness) == (5, 4)


def test_shield_of_duty_and_reason_is_protection_from_green_and_from_blue(set_pool):
    """Shield of Duty and Reason {W} Aura: "Enchanted creature has protection
    from green and from blue." Both colours, each doing protection's work: a
    green Giant Growth and a blue Unsummon may not target the creature — its
    own controller's included — a green creature may not block it, and a red
    Bolt still kills it, taking the Aura to the graveyard with it."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5e_duel(
        [lea["Savannah Lions"]], [lea["Grizzly Bears"]],
        hand0=[apc["Shield of Duty and Reason"], lea["Giant Growth"]],
        hand1=[lea["Unsummon"], lea["Lightning Bolt"]],
    )
    lions, green_bears = mine[0], theirs[0]
    assert game.cast_from_hand(
        0, "Shield of Duty and Reason", target_permanent_ids=[lions.permanent_id]
    ).supported
    assert game._protection_qualities(lions) == {("color", "G"), ("color", "U")}

    for seat, spell in ((0, "Giant Growth"), (1, "Unsummon")):
        refused = game.queue_from_hand(seat, spell, target_permanent_ids=[lions.permanent_id])
        assert not refused.supported, (spell, refused)
    assert lions.permanent_id not in [
        game.permanent_at(entry["seat"], entry["index"]).permanent_id
        for entry in game.cast_target_spec(1, lea["Unsummon"])["valid_targets"]
    ]

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(lions)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    declared = game.declare_blockers(1, {
        game.battlefield_index_of(green_bears): [game.battlefield_index_of(lions)],
    })
    assert declared[0] is False, declared

    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[lions.permanent_id]
    ).supported
    _w1g5e_resolve_stack(game)
    game._settle()
    assert [p.card.name for p in game.controlled_by(0)] == []
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Savannah Lions", "Shield of Duty and Reason",
    ]


def test_coalition_flag_falls_off_a_creature_its_controller_loses(set_pool):
    """"If this card is ever on a creature you don't control, it is put into
    the graveyard as a State-Based Action" (ruling, 2004-10-04; CR 704.5m).
    The opponent's Control Magic has to be aimed at the flagged Bears — the
    only target an Aura spell of theirs may choose — and taking them takes the
    Flag off: the Bears arrive as Bears, and the requirement is gone."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5e_duel(
        [lea["Grizzly Bears"], lea["Savannah Lions"]], [],
        hand0=[apc["Coalition Flag"]], hand1=[lea["Control Magic"], lea["Lightning Bolt"]],
    )
    bears, lions = mine
    assert game.cast_from_hand(
        0, "Coalition Flag", target_permanent_ids=[bears.permanent_id]
    ).supported
    offered = game.cast_target_spec(1, lea["Control Magic"])["valid_targets"]
    assert [entry["name"] for entry in offered] == ["Grizzly Bears"]
    stolen = game.queue_from_hand(1, "Control Magic", target_permanent_ids=[lions.permanent_id])
    assert not stolen.supported and _W1G5E_REQUIRED in stolen.details

    assert game.cast_from_hand(
        1, "Control Magic", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.controller_index_of(bears) == 1
    assert [card.name for card in game.players[0].graveyard] == ["Coalition Flag"]
    assert bears.has_type("bear") and not bears.has_type("flagbearer")
    assert "required_targets" not in game.cast_target_spec(1, lea["Lightning Bolt"])

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

import pytest as _w1g9_pytest

from engine import Game as _w1g9_Game
from engine import PlayerState as _w1g9_PlayerState
from engine.models import CardDefinition as _w1g9_CardDefinition
from engine.models import Permanent as _w1g9_Permanent
from engine.oracle import compile_card_oracle as _w1g9_compile
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_vanilla(name, power, toughness, *, text="", colors=()):
    """A creature carrying only its numbers (and, when given, one printed
    line): the tests below are about what an enchantment does *to* a creature,
    and a pool creature would bring its own abilities along with the answer."""
    type_line = "Creature - Test"
    return _w1g9_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=tuple(colors), color_identity=tuple(colors), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g9_ready(card):
    """*card* as a permanent that may attack and tap this turn."""
    permanent = _w1g9_Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g9_main(mine, theirs, *, hand=(), libraries=((), ())):
    """A two-seat game in the first main phase of seat 0's turn, costs off."""
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P1", battlefield=list(mine), hand=list(hand),
            library=list(libraries[0]),
        ),
        _w1g9_PlayerState(
            name="P2", battlefield=list(theirs), library=list(libraries[1])
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _w1g9_to_attackers(game):
    """Advance *game* from a main phase to its declare-attackers step."""
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    return game


def _w1g9_slot(game, seat, permanent):
    """Where *permanent* sits on *seat*'s battlefield, for the entry points
    (attackers, blockers, the ability's own source) that take a slot."""
    return next(
        slot for slot, found in enumerate(game.controlled_by(seat))
        if found is permanent
    )


def _w1g9_enchant(game, set_pool, name, host):
    """Cast *name* out of seat 0's hand onto *host* and return the Aura."""
    cast = game.cast_from_hand(0, name, target_permanent_ids=[host.permanent_id])
    assert cast.supported, cast.details
    _w1g9_resolve_stack(game)
    game._settle()
    return next(
        (found for found in game.all_permanents() if found.card.name == name),
        None,
    )


def _w1g9_disenchant(game, permanent):
    """Destroy *permanent* with seat 0's Disenchant, through a real cast."""
    cast = game.cast_from_hand(
        0, "Disenchant", target_permanent_ids=[permanent.permanent_id]
    )
    assert cast.supported, cast.details
    _w1g9_resolve_stack(game)
    game._settle()


# --- Fervent Charge ---------------------------------------------------------


def test_w1g9_fervent_charge_pumps_each_creature_you_attack_with(set_pool):
    """"Whenever a creature you control attacks, it gets +2/+2 until end of
    turn." One trigger per attacker, each about that attacker (by id): the two
    that attack grow, the one that stays home does not, and the boost is gone
    at cleanup."""
    charge = _w1g9_Permanent(card=set_pool("APC")["Fervent Charge"])
    first = _w1g9_ready(_w1g9_vanilla("First", 2, 2))
    second = _w1g9_ready(_w1g9_vanilla("Second", 1, 1))
    home = _w1g9_ready(_w1g9_vanilla("Home", 3, 3))
    foe = _w1g9_ready(_w1g9_vanilla("Foe", 3, 3))
    game = _w1g9_to_attackers(_w1g9_main([charge, first, second, home], [foe]))

    assert game.declare_attackers(0, [1, 2])[0]
    assert len(game.stack) == 2, "one trigger for each attacking creature"
    _w1g9_resolve_stack(game)

    assert (first.effective_power, first.effective_toughness) == (4, 4)
    assert (second.effective_power, second.effective_toughness) == (3, 3)
    assert (home.effective_power, home.effective_toughness) == (3, 3)
    assert (foe.effective_power, foe.effective_toughness) == (3, 3)
    assert "Fervent Charge gives First +2/+2 until end of turn" in game.log

    game.resolve_cleanup_step(0)
    assert (first.effective_power, first.effective_toughness) == (2, 2)
    assert (second.effective_power, second.effective_toughness) == (1, 1)


def test_w1g9_fervent_charge_ignores_a_creature_somebody_else_attacks_with(set_pool):
    """"…a creature **you control**…" is the trigger's own narrowing, asked
    against the enchantment's controller: an opponent's attacker fires
    nothing, so nothing goes on the stack and nothing grows."""
    charge = _w1g9_Permanent(card=set_pool("APC")["Fervent Charge"])
    theirs = _w1g9_ready(_w1g9_vanilla("Theirs", 2, 2))
    game = _w1g9_to_attackers(_w1g9_main([theirs], [charge]))

    assert game.declare_attackers(0, [0])[0]

    assert not game.stack
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)


def test_w1g9_an_event_subjects_pump_still_refuses_a_seat_it_cannot_name():
    """The refusal half of the gate Fervent Charge loosened. The handler holds
    the ability's controller and its source, so "you control" is a word it can
    re-ask; "defending player controls" is a seat it has no argument for, and
    a pump carrying it would compile and never land."""
    from engine.subject_filters import observer_source_filter

    assert observer_source_filter(
        {"type_filter": "creature", "controller": "you"}
    ) is not None
    assert observer_source_filter(
        {"type_filter": "creature", "controller": "opponent"}
    ) is not None
    assert observer_source_filter(
        {"type_filter": "creature", "controller": "defending_player"}
    ) is None
    assert observer_source_filter(
        {"type_filter": "creature", "controller": "that_player"}
    ) is None
    assert observer_source_filter(
        {"attached_to_filter": {"controller": "defending_player"}}
    ) is None


# --- Powerstone Minefield -----------------------------------------------------


def test_w1g9_powerstone_minefield_hits_every_attacker_and_every_blocker(set_pool):
    """"Whenever a creature attacks or blocks, this enchantment deals 2 damage
    to it." Both halves of the union in one combat: each attacker as it is
    declared, each blocker as it is declared — and nobody who did neither."""
    minefield = _w1g9_Permanent(card=set_pool("APC")["Powerstone Minefield"])
    small = _w1g9_ready(_w1g9_vanilla("Small Attacker", 2, 2))
    big = _w1g9_ready(_w1g9_vanilla("Big Attacker", 4, 4))
    home = _w1g9_ready(_w1g9_vanilla("Stays Home", 1, 1))
    blocker = _w1g9_ready(_w1g9_vanilla("Blocker", 3, 5))
    idle = _w1g9_ready(_w1g9_vanilla("Idle", 1, 1))
    game = _w1g9_to_attackers(
        _w1g9_main([minefield, small, big, home], [blocker, idle])
    )

    assert game.declare_attackers(0, [1, 2])[0]
    assert len(game.stack) == 2
    _w1g9_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(small), "2 damage kills a 2/2"
    assert big.damage_marked == 2
    assert home.damage_marked == 0 and game.is_on_battlefield(home)

    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {_w1g9_slot(game, 1, blocker): _w1g9_slot(game, 0, big)}
    )[0]
    assert len(game.stack) == 1, "the block half fires for the blocker alone"
    _w1g9_resolve_stack(game)

    assert blocker.damage_marked == 2
    assert idle.damage_marked == 0
    assert big.damage_marked == 2, "becoming blocked is neither attacking nor blocking"


def test_w1g9_powerstone_minefield_is_no_respecter_of_sides(set_pool):
    """"A creature" is any creature: the enchantment's own controller's
    opponent attacks into it and is hit. The damage is the Minefield's (a red
    and white source), so protection from red prevents it (CR 702.16e)."""
    minefield = _w1g9_Permanent(card=set_pool("APC")["Powerstone Minefield"])
    plain = _w1g9_ready(_w1g9_vanilla("Plain", 4, 4))
    warded = _w1g9_ready(
        _w1g9_vanilla("Warded", 2, 2, text="Protection from red")
    )
    game = _w1g9_to_attackers(_w1g9_main([plain, warded], [minefield]))

    assert game.declare_attackers(0, [0, 1])[0]
    _w1g9_resolve_stack(game)
    game._settle()

    assert plain.damage_marked == 2
    assert warded.damage_marked == 0 and game.is_on_battlefield(warded)
    assert "Warded has protection from Powerstone Minefield" in game.log


def test_w1g9_attacks_or_blocks_is_read_whole_or_not_at_all(set_pool):
    """The condition is one kind in both front ends, and it ends at the comma.

    Before the row existed the per-attacker row — its strict prefix — matched
    "whenever a creature attacks" and left " or blocks" at the head of the
    effect. And "…attacks or blocks **a Wall**" is a different condition, so it
    refuses rather than being read as this one with its partner dropped."""
    from engine.grammar import compile_line
    from engine.oracle import trigger_condition_of_line

    program = _w1g9_compile(set_pool("APC")["Powerstone Minefield"])
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "matching_creature_attacks_or_blocks"
    assert trigger.condition.raw_text == "whenever a creature attacks or blocks"
    assert trigger.condition.payload == {
        "combatant_filter": {"type_filter": "creature"}
    }

    narrowed = "Whenever a creature attacks or blocks a Wall, destroy it."
    condition, _ = trigger_condition_of_line(narrowed, "Test")
    assert condition is None or condition.kind != "matching_creature_attacks_or_blocks"
    assert not compile_line(narrowed, card_name="Test").parsed


# --- Manacles of Decay --------------------------------------------------------


def _w1g9_manacled(set_pool):
    """Seat 0's Manacles of Decay on the first of seat 1's two 3/3s, with a
    2/2 of seat 0's own to attack with."""
    held = _w1g9_ready(_w1g9_vanilla("Held", 3, 3))
    free = _w1g9_ready(_w1g9_vanilla("Free", 3, 3))
    mine = _w1g9_ready(_w1g9_vanilla("Mine", 2, 2))
    game = _w1g9_main(
        [mine], [held, free], hand=[set_pool("APC")["Manacles of Decay"]]
    )
    manacles = _w1g9_enchant(game, set_pool, "Manacles of Decay", held)
    return game, manacles, held, free, mine


def test_w1g9_manacles_of_decay_keeps_its_host_from_attacking(set_pool):
    """"Enchanted creature can't attack." The static line, on the creature it
    is attached to and no other."""
    game, manacles, held, free, mine = _w1g9_manacled(set_pool)

    assert game.controller_index_of(manacles) == 0
    assert not game.can_attack(held, 0)
    assert game.can_attack(free, 0)


def test_w1g9_manacles_of_decay_shrinks_its_host_until_end_of_turn(set_pool):
    """"{B}: Enchanted creature gets -1/-1 until end of turn." The Aura's
    controller activates it, as often as it is paid for; three times kills a
    3/3 (CR 704.5f) and the Aura follows it to the graveyard (CR 704.5m)."""
    game, manacles, held, free, mine = _w1g9_manacled(set_pool)
    source = _w1g9_slot(game, 0, manacles)

    assert game.activate_permanent_ability(
        0, "Manacles of Decay", permanent_index=source, ability_index=0
    ).supported
    assert (held.effective_power, held.effective_toughness) == (2, 2)
    assert (free.effective_power, free.effective_toughness) == (3, 3)

    for _ in range(2):
        assert game.activate_permanent_ability(
            0, "Manacles of Decay", permanent_index=_w1g9_slot(game, 0, manacles),
            ability_index=0,
        ).supported

    assert not game.is_on_battlefield(held)
    assert not game.is_on_battlefield(manacles)
    assert [card.name for card in game.players[0].graveyard] == ["Manacles of Decay"]


def test_w1g9_manacles_of_decay_stops_its_host_blocking_for_the_turn(set_pool):
    """"{R}: Enchanted creature can't block this turn." The host — nobody was
    chosen — is refused as a blocker, the creature beside it is not, and the
    mark is swept with the turn."""
    game, manacles, held, free, mine = _w1g9_manacled(set_pool)

    result = game.activate_permanent_ability(
        0, "Manacles of Decay", permanent_index=_w1g9_slot(game, 0, manacles),
        ability_index=1,
    )
    assert result.supported, result.details
    assert "Held can't block this turn" in game.log

    _w1g9_to_attackers(game)
    attacker = _w1g9_slot(game, 0, mine)
    assert game.declare_attackers(0, [attacker])[0]
    game.advance_combat_phase()

    refused, why = game.declare_blockers(1, {_w1g9_slot(game, 1, held): attacker})
    assert not refused and "Held cannot block" in why
    assert game.declare_blockers(1, {_w1g9_slot(game, 1, free): attacker})[0]

    game.resolve_cleanup_step(0)
    assert not held.metadata.get("cant_block_until_eot")


def test_w1g9_the_attached_cant_block_marks_the_host_and_nothing_narrower():
    """The refusal half. The lowering marks the Aura's host and tests nothing
    else, so a narrowing beside "enchanted" is one it would drop — it refuses.
    And the two neighbours keep their own kinds: a chosen creature is a pick,
    a described set is the board-wide blanket."""
    from engine.grammar import compile_line

    host = compile_line(
        "{R}: Enchanted creature can't block this turn.", card_name="Test"
    )
    assert [i.kind for i in host.instructions] == ["attached_cant_block_until_eot"]

    chosen = compile_line(
        "{R}: Target creature can't block this turn.", card_name="Test"
    )
    assert [i.kind for i in chosen.instructions] == ["target_cant_block_until_eot"]

    permanent = compile_line(
        "{R}: Enchanted creature can't block.", card_name="Test"
    )
    assert not permanent.lowered, "with no duration it is a static, not an effect"


# --- Quicksilver Dagger -------------------------------------------------------


def test_w1g9_quicksilver_dagger_grants_both_sentences_of_its_ability(set_pool):
    """'Enchanted creature has "{T}: This creature deals 1 damage to target
    player or planeswalker. **You draw a card.**"' Both sentences happen: the
    creature taps, the chosen player takes 1 from the *creature*, and its
    controller draws."""
    host = _w1g9_ready(_w1g9_vanilla("Host", 2, 2))
    filler = _w1g9_vanilla("Filler", 1, 1)
    game = _w1g9_main(
        [host], [], hand=[set_pool("APC")["Quicksilver Dagger"]],
        libraries=([filler, filler], [filler, filler]),
    )
    _w1g9_enchant(game, set_pool, "Quicksilver Dagger", host)

    spec = game.activation_target_spec(0, _w1g9_slot(game, 0, host), 0)
    assert spec["kind"] == "player_or_planeswalker"
    assert [t["seat"] for t in spec["valid_targets"]] == [0, 1]

    hand = len(game.players[0].hand)
    result = game.activate_permanent_ability(
        0, "Host", permanent_index=_w1g9_slot(game, 0, host), target_player_index=1,
    )

    assert result.supported, result.details
    assert host.tapped
    assert game.players[1].life == 19
    assert len(game.players[0].hand) == hand + 1
    assert "Host dealt 1 damage" in game.log
    assert "Host drew 1 card" in game.log


def test_w1g9_quicksilver_dagger_belongs_to_whoever_controls_the_creature(set_pool):
    """On an opponent's creature the ability is that opponent's: they activate
    it, they aim it, and "you draw a card" is them (CR 109.5). It cannot be
    aimed at a creature, and it is gone the moment the Aura is."""
    theirs = _w1g9_ready(_w1g9_vanilla("Theirs", 2, 2))
    filler = _w1g9_vanilla("Filler", 1, 1)
    game = _w1g9_main(
        [], [theirs],
        hand=[set_pool("APC")["Quicksilver Dagger"], set_pool("LEA")["Disenchant"]],
        libraries=([filler, filler], [filler, filler]),
    )
    dagger = _w1g9_enchant(game, set_pool, "Quicksilver Dagger", theirs)
    hands = (len(game.players[0].hand), len(game.players[1].hand))

    at_a_creature = game.activate_permanent_ability(
        1, "Theirs", permanent_index=0, target_permanent_ids=[theirs.permanent_id],
    )
    assert not at_a_creature.supported and not theirs.tapped

    assert game.activate_permanent_ability(
        1, "Theirs", permanent_index=0, target_player_index=0,
    ).supported
    assert game.players[0].life == 19
    assert (len(game.players[0].hand), len(game.players[1].hand)) == (
        hands[0], hands[1] + 1,
    )

    theirs.tapped = False
    _w1g9_disenchant(game, dagger)
    assert game.usable_abilities_of(theirs) == []
    assert not game.activate_permanent_ability(
        1, "Theirs", permanent_index=0, target_player_index=0,
    ).supported
    assert game.players[0].life == 19


def test_w1g9_quicksilver_daggers_two_sentences_are_claimed_as_one_grant(set_pool):
    """What the instrument said was missing. The sentence splitter cuts at the
    full stop inside the quotes, so the grant reached `parse_coverage` as two
    fragments and each read unclaimed; the reader that carries it out compiles
    the whole quote on the host, and the claim now asks that reader."""
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import parse_coverage

    coverage = parse_coverage.analyze_card(
        set_pool("APC")["Quicksilver Dagger"], parse_coverage._hooked_names(),
        run_probe=False,
    )

    assert coverage.unclaimed == []
    claimed = dict(coverage.claims)
    assert claimed['you draw a card."'] == "auras.py (attached effect)"


# --- Drive list: Foul Presence, Yavimaya's Embrace, Diversionary Tactics, ------
# --- Pernicious Deed -----------------------------------------------------------


def test_w1g9_foul_presence_shrinks_its_host_and_arms_it(set_pool):
    """'Enchanted creature gets -1/-1 and has "{T}: Target creature gets -1/-1
    until end of turn."'

    **The -1/-1 was not applied on arrival.** The static reader took the
    "until end of turn" inside the quoted ability for the grant's own duration
    and declined it, so the host kept its printed size while the card reported
    supported. Both halves, and the Aura leaving takes both away.
    """
    host = _w1g9_ready(_w1g9_vanilla("Host", 3, 3))
    victim = _w1g9_ready(_w1g9_vanilla("Victim", 1, 1))
    other = _w1g9_ready(_w1g9_vanilla("Other", 2, 2))
    game = _w1g9_main(
        [host], [victim, other],
        hand=[set_pool("APC")["Foul Presence"], set_pool("LEA")["Disenchant"]],
    )
    presence = _w1g9_enchant(game, set_pool, "Foul Presence", host)

    assert (host.effective_power, host.effective_toughness) == (2, 2)
    assert [a.source_line for a in game.usable_abilities_of(host)] == [
        "{t}: target creature gets -1/-1 until end of turn."
    ]

    result = game.activate_permanent_ability(
        0, "Host", permanent_index=_w1g9_slot(game, 0, host),
        target_permanent_ids=[victim.permanent_id],
    )
    game._settle()
    assert result.supported, result.details
    assert host.tapped
    assert not game.is_on_battlefield(victim)
    assert (other.effective_power, other.effective_toughness) == (2, 2)

    _w1g9_disenchant(game, presence)
    assert (host.effective_power, host.effective_toughness) == (3, 3)
    assert game.usable_abilities_of(host) == []


def test_w1g9_foul_presence_kills_a_one_toughness_creature_outright(set_pool):
    """The static half on its own: a 1/1 it enchants is a 0/0 and dies
    (CR 704.5f), and the Aura goes to its owner's graveyard (CR 704.5m)."""
    weak = _w1g9_ready(_w1g9_vanilla("Weak", 1, 1))
    game = _w1g9_main([], [weak], hand=[set_pool("APC")["Foul Presence"]])

    presence = _w1g9_enchant(game, set_pool, "Foul Presence", weak)

    assert presence is None
    assert not game.is_on_battlefield(weak)
    assert [card.name for card in game.players[1].graveyard] == ["Weak"]
    assert [card.name for card in game.players[0].graveyard] == ["Foul Presence"]


def test_w1g9_a_quoted_duration_is_not_the_grants_own(set_pool):
    """The reader, asked directly, in both directions: a duration inside the
    quote does not make the grant temporary, and a duration outside it still
    does."""
    from engine.auras import aura_static_pt_grant

    assert aura_static_pt_grant(set_pool("APC")["Foul Presence"].oracle_text) == (-1, -1)
    assert aura_static_pt_grant(
        "Enchanted creature gets +2/+2 and gains trample until end of turn."
    ) is None


def test_w1g9_yavimayas_embrace_takes_the_creature_and_gives_it_back(set_pool):
    """"You control enchanted creature. Enchanted creature gets +2/+2 and has
    trample." All three while attached; when the Aura is destroyed the
    creature returns to its owner at its printed size (CR 613 layer 2: the
    control change is the Aura's contribution, and it is gone)."""
    theirs = _w1g9_ready(_w1g9_vanilla("Theirs", 2, 2))
    game = _w1g9_main(
        [], [theirs],
        hand=[set_pool("APC")["Yavimaya's Embrace"], set_pool("LEA")["Disenchant"]],
    )
    embrace = _w1g9_enchant(game, set_pool, "Yavimaya's Embrace", theirs)

    assert game.controller_index_of(theirs) == 0
    assert [p.card.name for p in game.controlled_by(1)] == []
    assert (theirs.effective_power, theirs.effective_toughness) == (4, 4)
    assert game._has_keyword(theirs, "trample")
    assert not game.can_attack(theirs, 1), "it arrived this turn (CR 302.6)"

    _w1g9_disenchant(game, embrace)

    assert game.controller_index_of(theirs) == 1
    assert [p.card.name for p in game.controlled_by(0)] == []
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)
    assert not game._has_keyword(theirs, "trample")


def test_w1g9_diversionary_tactics_taps_two_of_yours_to_tap_one(set_pool):
    """"Tap two untapped creatures you control: Tap target creature." The cost
    is two creatures the payer names — a summoning-sick one may pay, because
    the cost prints no {T} (CR 302.6) — and it is refused whole when only one
    is left untapped, or when one of the two is not the payer's."""
    tactics = _w1g9_Permanent(card=set_pool("APC")["Diversionary Tactics"])
    first = _w1g9_ready(_w1g9_vanilla("First", 1, 1))
    second = _w1g9_ready(_w1g9_vanilla("Second", 1, 1))
    fresh = _w1g9_Permanent(card=_w1g9_vanilla("Fresh", 1, 1))
    foe = _w1g9_ready(_w1g9_vanilla("Foe", 3, 3))
    game = _w1g9_main([tactics, first, second, fresh], [foe])
    fresh.metadata["summoning_sickness_turn"] = game.turn

    cost = game.activation_target_spec(0, 0, 0)["cost_spec"]
    assert cost["count"] == 2 and cost["own_only"]
    assert [t["name"] for t in cost["valid_targets"]] == ["First", "Second", "Fresh"]

    foreign = game.activate_permanent_ability(
        0, "Diversionary Tactics", permanent_index=0,
        target_permanent_ids=[first.permanent_id],
        cost_permanent_ids=[foe.permanent_id, second.permanent_id],
    )
    assert not foreign.supported
    assert not any(p.tapped for p in (first, second, fresh, foe))

    at_itself = game.activate_permanent_ability(
        0, "Diversionary Tactics", permanent_index=0,
        target_permanent_ids=[tactics.permanent_id],
    )
    assert not at_itself.supported, "an enchantment is not a creature"

    paid = game.activate_permanent_ability(
        0, "Diversionary Tactics", permanent_index=0,
        target_permanent_ids=[foe.permanent_id],
        cost_permanent_ids=[fresh.permanent_id, second.permanent_id],
    )
    assert paid.supported, paid.details
    assert [p.tapped for p in (first, second, fresh, foe)] == [False, True, True, True]

    short = game.activate_permanent_ability(
        0, "Diversionary Tactics", permanent_index=0,
        target_permanent_ids=[first.permanent_id],
    )
    assert not short.supported
    assert "not enough untapped creatures" in short.details
    assert not first.tapped


def _w1g9_deed_board(set_pool):
    lea = set_pool("LEA")
    deed = _w1g9_Permanent(card=set_pool("APC")["Pernicious Deed"])
    mine = [deed] + [_w1g9_Permanent(card=lea[name]) for name in ("Mox Ruby", "Forest")]
    theirs = [
        _w1g9_Permanent(card=lea[name])
        for name in ("Sol Ring", "Grizzly Bears", "Serra Angel", "Crusade")
    ]
    theirs.append(_w1g9_Permanent(card=_w1g9_vanilla("Token", 1, 1)))
    game = _w1g9_main(mine, theirs)
    game.enforce_mana_costs = True
    return game, deed


def _w1g9_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g9_pernicious_deed_destroys_up_to_the_x_that_was_paid(set_pool):
    """"{X}, Sacrifice this enchantment: Destroy each artifact, creature, and
    enchantment with mana value X or less." X is paid, the Deed is sacrificed,
    and the sweep is both boards: everything at 2 or less goes, a five-drop
    and a land stay."""
    game, deed = _w1g9_deed_board(set_pool)
    game.players[0].mana_pool["C"] = 2

    result = game.activate_permanent_ability(
        0, "Pernicious Deed", permanent_index=0, x_value=2
    )
    game._settle()

    assert result.supported, result.details
    assert not any(game.players[0].mana_pool.values()), "X was charged"
    assert _w1g9_names(game, 0) == ["Forest"]
    assert _w1g9_names(game, 1) == ["Serra Angel"]
    assert "Pernicious Deed" in [c.name for c in game.players[0].graveyard]


def test_w1g9_pernicious_deed_for_nothing_takes_only_what_costs_nothing(set_pool):
    """X = 0: the Mox and a token (mana value 0, per the card's ruling) go, a
    one-drop does not."""
    game, deed = _w1g9_deed_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Pernicious Deed", permanent_index=0, x_value=0
    )
    game._settle()

    assert result.supported, result.details
    assert _w1g9_names(game, 0) == ["Forest"]
    assert _w1g9_names(game, 1) == [
        "Crusade", "Grizzly Bears", "Serra Angel", "Sol Ring",
    ]


def test_w1g9_pernicious_deed_is_not_sacrificed_for_an_x_nobody_can_pay(set_pool):
    """An X the pool cannot cover refuses the activation with nothing paid —
    the Deed is still on the battlefield and the board is untouched."""
    game, deed = _w1g9_deed_board(set_pool)
    game.players[0].mana_pool["C"] = 1

    result = game.activate_permanent_ability(
        0, "Pernicious Deed", permanent_index=0, x_value=3
    )

    assert not result.supported and "insufficient mana" in result.details
    assert game.is_on_battlefield(deed)
    assert game.players[0].mana_pool["C"] == 1
    assert len(_w1g9_names(game, 1)) == 5


@_w1g9_pytest.mark.slow
def test_w1g9_the_groups_cards_through_whole_simulated_games():
    """Six AI games with the group's cards pinned into both decks. The pool is
    a measured set, so other cards' unsupported casts are in the report; only
    these cards' lines are read, and the floors sit well under what the seed
    gives today (ten Boa activations, fifteen Minefield triggers, seven Mauler
    attacks, seventeen points of Forge damage) so that another card becoming
    castable does not move them. Fervent Charge resolved twice in that run and
    has no floor for the same reason: what is asserted of it, and of Manacles
    of Decay, is that nothing it did was refused or an issue."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    names = [
        "Zombie Boa", "Fervent Charge", "Powerstone Minefield", "Kavu Mauler",
        "Manacles of Decay", "Llanowar Wastes", "Battlefield Forge",
    ]
    report = run_ai_simulation(
        [manifest_set_path("APC", include_measured=True)],
        games=6, seed=1337, max_turns=20, required_cards=names,
    )
    log = report.log_lines

    assert report.games_completed == 6
    assert not report.steps_left_owing, dict(report.steps_left_owing)
    assert sum("Zombie Boa created a delayed triggered ability" in line for line in log) >= 2
    assert sum("Powerstone Minefield ability resolved" in line for line in log) >= 3
    assert sum("Kavu Mauler triggered on attack" in line for line in log) >= 1
    assert sum("Battlefield Forge dealt 1 damage to " in line for line in log) >= 2
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [key for key in report.refused_activations if key.split(":")[0] in names] == []
    assert [
        issue.message for issue in report.issues
        if any(name in issue.message for name in names)
    ] == []

# ==== end W1G9 ========================================================
