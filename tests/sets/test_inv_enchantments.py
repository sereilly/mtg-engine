"""Invasion enchantments.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G7: piles ---
from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import _mk_card as _w1g7_mk_card
from tests.helpers import _nosick as _w1g7_nosick
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_body(name, power, toughness):
    """A vanilla creature permanent, ready to attack."""
    card = _w1g7_mk_card(name, "{2}", "Creature - Bear", "")
    card.raw.update({"power": str(power), "toughness": str(toughness)})
    w1g7_ready_body = _w1g7_nosick(_W1G7Permanent(card=card))
    return w1g7_ready_body


def _w1g7_combat_table(set_pool, enchantment, *, mine=(), theirs=(), active, interactive=()):
    """Seat 0 controlling *enchantment*, at the beginning of *active*'s combat
    with the trigger (if any) on the stack."""
    permanent = _W1G7Permanent(card=set_pool("INV")[enchantment])
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="P1", battlefield=[permanent, *mine]),
        _W1G7PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game._sync_control()
    game.interactive_seats = set(interactive)
    game.enforce_mana_costs = False
    game.start_turn(active)
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert game.current_step == "beginning_of_combat"
    w1g7_combat_ready = game
    return w1g7_combat_ready


def _w1g7_slot(game, seat, name):
    """The battlefield slot of *seat*'s permanent called *name* — combat
    declarations are index-keyed."""
    w1g7_slot_index = next(
        index for index, permanent in enumerate(game.controlled_by(seat))
        if permanent.card.name == name
    )
    return w1g7_slot_index


def test_w1g7_fight_or_flight_only_the_pile_the_attacker_chooses_can_attack(set_pool):
    """"At the beginning of combat on each opponent's turn, separate all
    creatures that player controls into two piles. Only creatures in the pile
    of their choice can attack this turn."

    The enchantment's controller separates the *active player's* creatures
    ("that player" is the seat whose combat fired the trigger, CR 603.10) and
    that player picks a pile. Everything of theirs outside it cannot be
    declared as an attacker — and the restriction ends with the turn.
    """
    program = _w1g7_compile(set_pool("INV")["Fight or Flight"])
    assert program.supported, program.reason
    assert [t.condition.kind for t in program.triggered_abilities] == ["combat_opponent_turn"]

    theirs = [_w1g7_body("Giant", 5, 5), _w1g7_body("Middle", 3, 3), _w1g7_body("Runt", 1, 1)]
    game = _w1g7_combat_table(
        set_pool, "Fight or Flight", mine=[_w1g7_body("Mine", 2, 2)],
        theirs=theirs, active=1, interactive=[0, 1],
    )
    assert [item.card.name for item in game.stack] == ["Fight or Flight"]
    game.resolve_top_of_stack(pause_for_choices=True)

    split = game.pending_choice_of("pile_split", 0)
    assert split is not None, "the enchantment's controller separates"
    assert len(split.data["_group"].items) == 3, "that player's creatures only"
    assert game.confirm_pile_split(0, [0])
    assert game.pending_choice_of("pile_choice", 1) is not None, "that player chooses"
    assert game.confirm_pile_choice(1, 1)
    assert not game.pending_choices

    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    legal = sorted(
        list(game.controlled_by(1))[index].card.name
        for index in game.legal_attacker_indices(1)
    )
    assert legal == ["Middle", "Runt"]
    refused, why = game.declare_attackers(
        1, [_w1g7_slot(game, 1, "Giant")], defending_player_index=0,
    )
    assert not refused, "the creature outside the chosen pile cannot attack"
    accepted, why = game.declare_attackers(
        1, [_w1g7_slot(game, 1, "Middle"), _w1g7_slot(game, 1, "Runt")],
        defending_player_index=0,
    )
    assert accepted, why

    # CR 514.2: "this turn" ends at cleanup.
    game.resolve_cleanup_step(1)
    assert game.attack_restrictions_until_eot == []


def test_w1g7_fight_or_flight_a_creature_that_arrives_after_the_split_is_in_neither_pile(set_pool):
    """"**Only** creatures in the pile … can attack": a restriction on
    everything else, so a creature that was not there to be separated cannot
    attack either. The record is state on the game with the pile as its
    exception list, not a mark on the creatures left out."""
    theirs = [_w1g7_body("Chosen", 2, 2)]
    game = _w1g7_combat_table(set_pool, "Fight or Flight", theirs=theirs, active=1)
    _w1g7_resolve_stack(game)
    # One creature: the even split is it against nothing, and its controller
    # takes the pile it is in.
    late = _w1g7_body("Latecomer", 4, 4)
    game._put_permanent_onto_battlefield(1, late, None)
    _w1g7_nosick(late)

    game.advance_combat_phase()
    legal = [
        list(game.controlled_by(1))[index].card.name
        for index in game.legal_attacker_indices(1)
    ]
    assert legal == ["Chosen"], game.log


def test_w1g7_fight_or_flight_is_silent_on_its_controllers_own_turn(set_pool):
    """"On each **opponent's** turn": the controller's own combat fires
    nothing, and nothing restricts their attack."""
    game = _w1g7_combat_table(
        set_pool, "Fight or Flight", mine=[_w1g7_body("Mine", 2, 2)],
        theirs=[_w1g7_body("Theirs", 2, 2)], active=0,
    )
    assert game.stack == []
    assert game.attack_restrictions_until_eot == []
    game.advance_combat_phase()
    assert [
        list(game.controlled_by(0))[index].card.name
        for index in game.legal_attacker_indices(0)
    ] == ["Mine"]


def test_w1g7_stand_or_fall_only_the_pile_the_defender_chooses_can_block(set_pool):
    """"At the beginning of combat on your turn, for each defending player,
    separate all creatures that player controls into two piles and that player
    chooses one. Only creatures in the chosen piles can block this turn."

    The mirror on your own turn: you separate the defending player's
    creatures, they choose, and only the chosen pile may be declared as
    blockers.
    """
    program = _w1g7_compile(set_pool("INV")["Stand or Fall"])
    assert program.supported, program.reason

    theirs = [_w1g7_body("Wall", 0, 6), _w1g7_body("Guard", 2, 3), _w1g7_body("Scout", 1, 1)]
    game = _w1g7_combat_table(
        set_pool, "Stand or Fall", mine=[_w1g7_body("Raider", 3, 3)],
        theirs=theirs, active=0, interactive=[0, 1],
    )
    assert [item.card.name for item in game.stack] == ["Stand or Fall"]
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.pending_choice_of("pile_split", 0) is not None, "you separate"
    assert game.confirm_pile_split(0, [0, 1])
    assert game.pending_choice_of("pile_choice", 1) is not None, "the defender chooses"
    assert game.confirm_pile_choice(1, 1)

    game.advance_combat_phase()
    raider = _w1g7_slot(game, 0, "Raider")
    accepted, why = game.declare_attackers(0, [raider], defending_player_index=1)
    assert accepted, why
    if game.current_step != "declare_blockers":
        game._close_current_priority_step()
        game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    blockers = sorted(
        list(game.controlled_by(1))[option["blocker_index"]].card.name
        for option in game.legal_blocker_assignments(1)
    )
    assert blockers == ["Scout"], "only the chosen pile can block"
    refused, why = game.declare_blockers(1, {_w1g7_slot(game, 1, "Wall"): raider})
    assert not refused, why
    accepted, why = game.declare_blockers(1, {_w1g7_slot(game, 1, "Scout"): raider})
    assert accepted, why


def test_w1g7_stand_or_fall_is_silent_on_an_opponents_turn(set_pool):
    """"On **your** turn": an opponent's combat fires nothing, so the
    enchantment's controller blocks with whatever they like."""
    game = _w1g7_combat_table(
        set_pool, "Stand or Fall", mine=[_w1g7_body("Mine", 2, 2)],
        theirs=[_w1g7_body("Theirs", 2, 2)], active=1,
    )
    assert game.stack == []
    assert game.blocking_restrictions_until_eot == []


def _w1g7_sanctuary_upkeep(set_pool, interactive=()):
    """Seat 0 controlling Elfhame Sanctuary, stopped in its own upkeep on a
    later turn (the first turn's draw is skipped by rule, CR 103.8a) with the
    trigger on the stack."""
    lea = set_pool("LEA")
    sanctuary = _W1G7Permanent(card=set_pool("INV")["Elfhame Sanctuary"])
    library = [
        lea[name] for name in (
            "Lightning Bolt", "Forest", "Shivan Dragon", "Island", "Serra Angel",
        )
    ]
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="P1", battlefield=[sanctuary], library=library),
        _W1G7PlayerState(name="P2"),
    ])
    game._sync_control()
    game.interactive_seats = set(interactive)
    game.enforce_mana_costs = False
    game.turn = 4
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)
    w1g7_upkeep_ready = game
    return w1g7_upkeep_ready


def test_w1g7_elfhame_sanctuary_trades_the_draw_step_for_a_basic_land(set_pool):
    """"At the beginning of your upkeep, you may search your library for a
    basic land card, reveal that card, put it into your hand, then shuffle. If
    you do, you skip your draw step this turn."

    The offer is accepted, the Island the player names is fetched and revealed
    (a nonbasic or nonland card is not a legal find), and this turn's draw step
    never happens (CR 500.7, CR 614.10): the hand holds the Island and nothing
    else, and the library is one card shorter, not two.
    """
    program = _w1g7_compile(set_pool("INV")["Elfhame Sanctuary"])
    assert program.supported, program.reason

    game = _w1g7_sanctuary_upkeep(set_pool, interactive=[0])
    assert [item.card.name for item in game.stack] == ["Elfhame Sanctuary"]
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)
    search = game.pending_choice_of("search_library", 0)
    assert search is not None
    library = game.players[0].library
    bolt = next(i for i, c in enumerate(library) if c.name == "Lightning Bolt")
    island = next(i for i, c in enumerate(library) if c.name == "Island")
    assert not game.confirm_search_library(0, bolt), "not a basic land card"
    assert game.confirm_search_library(0, island)
    assert not game.stack and not game.pending_choices

    assert game.resolve_draw_step(0) == 0, game.log
    caster = game.players[0]
    assert [c.name for c in caster.hand] == ["Island"]
    assert len(caster.library) == 4
    assert any("revealed Island" in line for line in game.log)
    assert game.skip_step_counts == {}, "the skip was spent on this turn's draw step"


def test_w1g7_elfhame_sanctuary_declined_draws_as_usual(set_pool):
    """"You **may**": declining searches nothing and skips nothing — "if you
    do" is not met, so the draw step happens."""
    game = _w1g7_sanctuary_upkeep(set_pool, interactive=[0])
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=False)
    assert not game.stack and not game.pending_choices

    assert game.resolve_draw_step(0) == 1
    assert [c.name for c in game.players[0].hand] == ["Lightning Bolt"]


def test_w1g7_a_this_turn_draw_skip_does_not_outlive_its_turn(set_pool):
    """"…skip your draw step **this turn**" is a window, not "your next draw
    step": a skip recorded after this turn's draw step has already happened is
    swept at cleanup (CR 514.2) and the next turn's draw is untouched. The
    unbounded spelling (Ivory Gargoyle's "your next draw step") is a different
    record and waits."""
    game = _w1g7_sanctuary_upkeep(set_pool)
    game.pending_choices.clear()
    game.stack.clear()
    assert game.resolve_draw_step(0) == 1
    # Armed late — the draw step it names is already over.
    game.skip_next_step("draw", seat=0, on_turn=game.turn)
    game.skip_next_step("untap", seat=1)
    game.resolve_cleanup_step(0)
    assert game.skip_step_counts == {(1, "untap"): 1}
