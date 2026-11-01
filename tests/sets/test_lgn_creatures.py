"""Legions creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("LGN")` / `set_cards("LGN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Provoke (CR 702.39) and the cards that print or grant it. The rule's own
# clauses (the "may", "this combat", CR 702.39b, the multiplayer defending
# player) are tested once in tests/rules/test_lgn_w1g2_provoke.py; each test
# here is what one card adds to them, driven through a real combat.

from engine import PlayerState as _w1g2_PlayerState
from engine.ai_declarations import choose_combat_blockers as _w1g2_choose_blockers
from engine.combat_permissions import (
    MUST_BLOCK_ATTACKERS_THIS_COMBAT as _W1G2_PROVOKED,
)
from engine.game import Game as _w1g2_Game
from engine.models import CardDefinition as _w1g2_CardDefinition
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile

from tests.helpers import (_mk_creature_card as _w1g2_creature,
                           _nosick as _w1g2_nosick,
                           resolve_stack as _w1g2_resolve_stack)


def _w1g2_typed(name, type_line, power, toughness, oracle_text=""):
    return _w1g2_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g2_table(attackers, defenders, *, interactive=(), tapped=(), sick=()):
    """*attackers* on seat 0, *defenders* on seat 1, at seat 0's
    declare-attackers step. *tapped* are defender slots; *sick* are attacker
    slots that arrived this turn (CR 302.6)."""
    game = _w1g2_Game(players=[
        _w1g2_PlayerState(name="P0", library=[_w1g2_creature("Filler", 1, 1)] * 3),
        _w1g2_PlayerState(name="P1", library=[_w1g2_creature("Filler", 1, 1)] * 3),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    mine = []
    for slot, card in enumerate(attackers):
        perm = _w1g2_Permanent(card=card)
        game._put_permanent_onto_battlefield(0, perm, None)
        if slot not in sick:
            _w1g2_nosick(perm)
        mine.append(perm)
    theirs = []
    for slot, card in enumerate(defenders):
        perm = _w1g2_Permanent(card=card)
        game._put_permanent_onto_battlefield(1, perm, None)
        perm.tapped = slot in tapped
        theirs.append(perm)
    _w1g2_resolve_stack(game)
    game.start_turn(0)
    for slot in sick:
        mine[slot].metadata["summoning_sickness_turn"] = game.turn
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game, mine, theirs


def _w1g2_provoke(game, target, *, accept=True):
    """Seat 0 (interactive) names *target* for the one provoke on the stack
    and answers the "may"."""
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_id=target.permanent_id
    )
    assert game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=accept)
    _w1g2_resolve_stack(game)


def _w1g2_settle(game):
    """Resolve and answer as a seat nobody asks would."""
    for _ in range(10):
        _w1g2_resolve_stack(game)
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices()


def _w1g2_finish_combat(game):
    """Step through the rest of combat — bounded, so a step that will not
    advance fails the test naming what it waits on instead of hanging it."""
    for _ in range(12):
        if game.current_turn_phase != "combat":
            return
        game.advance_combat_phase()
    raise AssertionError(
        f"combat did not end: step {game.current_step!r}, waiting on "
        f"{game.waiting_prompt()!r}"
    )


def test_w1g2_every_provoke_card_compiles_one_provoke_trigger(set_pool):
    """The seven cards printing the keyword each carry exactly one provoke
    ability (CR 702.39a), and nothing else on them is dropped: the keyword
    line beside it, Deftblade Elite's prevention, Swooping Talon's flying
    toggle and Krosan Vorine's ceiling all compile too."""
    pool = set_pool("LGN")
    for name in ("Brontotherium", "Crested Craghorn", "Deftblade Elite",
                 "Goblin Grappler", "Krosan Vorine", "Lowland Tracker",
                 "Swooping Talon"):
        program = _w1g2_compile(pool[name])
        assert program.supported, (name, program.reason)
        provokes = [t for t in program.triggered_abilities if t.source_line == "provoke"]
        assert len(provokes) == 1, name
        assert provokes[0].condition.kind == "creature_attacks"
    assert [a.instruction.kind for a in _w1g2_compile(pool["Deftblade Elite"]).activated_abilities] == [
        "prevent_damage_to_target_until_eot"
    ]
    assert [a.instruction.kind for a in _w1g2_compile(pool["Swooping Talon"]).activated_abilities] == [
        "remove_self_keyword"
    ]
    assert any(
        i.kind == "cant_be_blocked_by_more_than"
        for i in _w1g2_compile(pool["Krosan Vorine"]).instructions
    )


def test_w1g2_goblin_grappler_drags_a_tapped_blocker_into_the_fight(set_pool):
    """Goblin Grappler, 1/1. Its controller provokes the tapped Bear: the Bear
    untaps and must block, and does — the one way a tapped creature comes to
    block at all."""
    grappler = set_pool("LGN")["Goblin Grappler"]
    game, (attacker,), (bear,) = _w1g2_table(
        [grappler], [_w1g2_creature("Bear", 2, 2)], interactive=(0, 1), tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear)
    assert not bear.tapped
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g2_finish_combat(game)
    assert attacker not in game.players[0].battlefield, "the Bear kills the Grappler"
    assert game.players[1].life == 20


def test_w1g2_goblin_grappler_declines_a_provoke_it_would_lose(set_pool):
    """A seat nobody asks: the Grappler's only target is a 2/2 that would kill
    it, so the "may" is declined — the Bear stays tapped and the Grappler's
    point of damage goes through."""
    grappler = set_pool("LGN")["Goblin Grappler"]
    game, (attacker,), (bear,) = _w1g2_table(
        [grappler], [_w1g2_creature("Bear", 2, 2)], tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_settle(game)
    assert bear.tapped
    assert any("declined Goblin Grappler" in line for line in game.log)
    game.advance_combat_phase()
    assert _w1g2_choose_blockers(game, 1) == {}
    assert game.declare_blockers(1, {})[0]
    _w1g2_finish_combat(game)
    assert game.players[1].life == 19


def test_w1g2_lowland_tracker_provokes_the_creature_its_first_strike_kills(set_pool):
    """Lowland Tracker, 2/2 first strike. A seat nobody asks names the 2/2 —
    first strike kills it before it strikes back — not the 0/4 it cannot hurt
    or the 3/3 that survives. The defending AI obeys the requirement."""
    tracker = set_pool("LGN")["Lowland Tracker"]
    game, (attacker,), (wall, bear, ogre) = _w1g2_table(
        [tracker],
        [_w1g2_creature("Wall", 0, 4), _w1g2_creature("Bear", 2, 2),
         _w1g2_creature("Ogre", 3, 3)],
        tapped=(1,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_settle(game)
    assert any("Lowland Tracker: targets Bear" in line for line in game.log)
    assert not bear.tapped
    assert bear.metadata[_W1G2_PROVOKED] == [attacker.permanent_id]
    game.advance_combat_phase()
    blocks = _w1g2_choose_blockers(game, 1)
    assert blocks.get(1) == 0, blocks
    assert game.declare_blockers(1, blocks)[0], game.log
    # The fight the provoke bought, alone: a declaration with the Bear
    # blocking by itself is legal, and first strike kills it before it
    # strikes back.
    game2, (attacker2,), (_w2, bear2, _o2) = _w1g2_table(
        [tracker],
        [_w1g2_creature("Wall", 0, 4), _w1g2_creature("Bear", 2, 2),
         _w1g2_creature("Ogre", 3, 3)],
        tapped=(1,),
    )
    assert game2.declare_attackers(0, [0], 1)[0]
    _w1g2_settle(game2)
    game2.advance_combat_phase()
    assert game2.declare_blockers(1, {1: 0})[0], game2.log
    _w1g2_finish_combat(game2)
    assert bear2 not in game2.players[1].battlefield
    assert attacker2 in game2.players[0].battlefield
    assert attacker2.damage_marked == 0, "first strike: the Bear never struck"


def test_w1g2_brontotherium_tramples_over_the_creature_it_provoked(set_pool):
    """Brontotherium, 5/3 trample. Provoked, the Bear blocks it; lethal
    damage to the Bear is 2 and the other 3 trample over (CR 702.19b)."""
    bronto = set_pool("LGN")["Brontotherium"]
    game, (attacker,), (bear,) = _w1g2_table(
        [bronto], [_w1g2_creature("Bear", 2, 2)], interactive=(0, 1), tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g2_finish_combat(game)
    assert bear not in game.players[1].battlefield
    assert game.players[1].life == 17
    assert attacker in game.players[0].battlefield


def test_w1g2_crested_craghorn_provokes_the_turn_it_arrives(set_pool):
    """Crested Craghorn, 4/1 haste: it attacks the turn it enters (CR 702.10b)
    and its provoke triggers like anyone's."""
    craghorn = set_pool("LGN")["Crested Craghorn"]
    game, (attacker,), (bear,) = _w1g2_table(
        [craghorn], [_w1g2_creature("Wall", 0, 3)], interactive=(0, 1), tapped=(0,),
        sick=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0], game.log
    _w1g2_provoke(game, bear)
    assert not bear.tapped
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g2_finish_combat(game)
    assert bear not in game.players[1].battlefield, "4 damage kills the 0/3"


def test_w1g2_deftblade_elite_provokes_and_then_prevents_the_fight(set_pool):
    """Deftblade Elite, 1/1: provoke a 4/4, then "{1}{W}: Prevent all combat
    damage that would be dealt to and dealt by this creature this turn." The
    4/4 is held in the block and neither creature is hurt."""
    elite = set_pool("LGN")["Deftblade Elite"]
    game, (attacker,), (giant,) = _w1g2_table(
        [elite], [_w1g2_creature("Giant", 4, 4)], interactive=(0, 1),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, giant)
    assert game.activate_permanent_ability(0, "Deftblade Elite", ability_index=0).supported
    _w1g2_resolve_stack(game)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g2_finish_combat(game)
    assert attacker in game.players[0].battlefield
    assert attacker.damage_marked == 0 and giant.damage_marked == 0
    assert giant in game.players[1].battlefield


def test_w1g2_swooping_talon_compels_only_once_it_lands(set_pool):
    """Swooping Talon, a 2/6 flier. The Bear it provokes cannot block a flier
    (CR 702.9b), so the requirement binds nothing (CR 509.1c) — until "{1}:
    This creature loses flying until end of turn" brings it down, and then
    the Bear must block."""
    talon = set_pool("LGN")["Swooping Talon"]
    game, (attacker,), (bear,) = _w1g2_table(
        [talon], [_w1g2_creature("Bear", 2, 2)], interactive=(0, 1), tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear)
    assert not bear.tapped
    assert game.block_requirement_refusal(1, {}) is None, "a flier it cannot block"
    assert game.activate_permanent_ability(0, "Swooping Talon", ability_index=0).supported
    _w1g2_resolve_stack(game)
    assert not game._has_keyword(attacker, "flying")
    game.advance_combat_phase()
    assert game.declare_blockers(1, {}) == (
        False, "Bear must block Swooping Talon this combat if able"
    )
    assert game.declare_blockers(1, {0: 0})[0]


def test_w1g2_krosan_vorine_is_blocked_by_its_provoked_creature_alone(set_pool):
    """Krosan Vorine: provoke, and "This creature can't be blocked by more
    than one creature." The provoked Bear must block it and a second blocker
    may not join — and the defending AI, offered two creatures that both
    like the block, declares the compelled one alone."""
    vorine = set_pool("LGN")["Krosan Vorine"]
    game, (attacker,), (bear, other) = _w1g2_table(
        [vorine], [_w1g2_creature("Bear", 2, 2), _w1g2_creature("Other Bear", 2, 2)],
        interactive=(0,), tapped=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0, 1: 0})[0] is False
    assert game.declare_blockers(1, {1: 0})[0] is False, "the Bear is the one owed"
    blocks = _w1g2_choose_blockers(game, 1)
    assert blocks == {0: 0}, blocks
    assert game.declare_blockers(1, blocks)[0], game.log


def test_w1g2_the_ai_respects_a_blocker_ceiling_with_no_requirement(set_pool):
    """Krosan Vorine's ceiling with provoke declined: two Bears that each like
    the block. The AI proposed both, the declaration was refused whole, and
    the seat blocked with nobody (SET_PLAYBOOK's "The AI proposes blocks past
    an attacker's blocker ceiling"); it keeps the better one now."""
    vorine = set_pool("LGN")["Krosan Vorine"]
    game, (attacker,), (bear_a, bear_b) = _w1g2_table(
        [vorine], [_w1g2_creature("Bear A", 2, 2), _w1g2_creature("Bear B", 2, 2)],
        interactive=(0,),
    )
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g2_provoke(game, bear_a, accept=False)
    game.advance_combat_phase()
    assert not game.block_requirements(1)
    blocks = _w1g2_choose_blockers(game, 1)
    assert len(blocks) == 1, blocks
    assert game.declare_blockers(1, blocks)[0], game.log


def test_w1g2_hunter_sliver_gives_every_sliver_provoke(set_pool):
    """Hunter Sliver: "All Sliver creatures have provoke." Itself, another
    Sliver of its controller's and an opponent's Sliver each have the keyword
    and the trigger (CR 613.1f); a non-Sliver does not. The grant is a grant
    of the line, so the Sliver that attacks puts a provoke on the stack."""
    hunter = set_pool("LGN")["Hunter Sliver"]
    mine = _w1g2_typed("Test Sliver", "Creature — Sliver", 2, 2)
    theirs = _w1g2_typed("Their Sliver", "Creature — Sliver", 2, 2)
    game, (lord, sliver, bear), (their_sliver, wall) = _w1g2_table(
        [hunter, mine, _w1g2_creature("Bear", 2, 2)],
        [theirs, _w1g2_creature("Wall", 0, 4)],
        interactive=(0, 1), tapped=(1,),
    )
    game.check_state_based_actions()
    for perm in (lord, sliver, their_sliver):
        assert game._has_keyword(perm, "provoke"), perm.card.name
        assert any(
            t.source_line == "provoke"
            for t in _w1g2_compile(perm.effective_card).triggered_abilities
        ), perm.card.name
    assert not game._has_keyword(bear, "provoke")
    assert game.declare_attackers(0, [1, 2], 1)[0]
    provokes = [item for item in game.stack if item.ability_text == "provoke"]
    assert [item.source_permanent for item in provokes] == [sliver]
    _w1g2_provoke(game, wall)
    assert not wall.tapped
    assert wall.metadata[_W1G2_PROVOKED] == [sliver.permanent_id]


def test_w1g2_hunter_sliver_leaving_takes_provoke_with_it(set_pool):
    """CR 611.3a: the grant applies while Hunter Sliver is on the battlefield
    and stops when it leaves — the Sliver's next attack triggers nothing."""
    hunter = set_pool("LGN")["Hunter Sliver"]
    mine = _w1g2_typed("Test Sliver", "Creature — Sliver", 2, 2)
    game, (lord, sliver), _theirs = _w1g2_table(
        [hunter, mine], [_w1g2_creature("Bear", 2, 2)],
    )
    game.check_state_based_actions()
    assert game._has_keyword(sliver, "provoke")
    game.remove_from_battlefield(lord)
    game.check_state_based_actions()
    assert not game._has_keyword(sliver, "provoke")
    assert game.declare_attackers(0, [0], 1)[0]
    assert not [item for item in game.stack if item.ability_text == "provoke"]

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================
