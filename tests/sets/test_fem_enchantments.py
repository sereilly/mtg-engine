"""Per-card tests for Fallen Empires' enchantments.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations


# --- G3: combat triggers, block restrictions and damage substitution ---
from engine.auras import attach_aura
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _g3_mantle_board(set_pool):
    """Farrel's Mantle on a 2/2 attacker, with two creatures to aim at.

    Seat 0 is interactive so the two decisions the trigger owes — its target
    and the offer to the enchanted creature's controller — *queue* rather than
    taking their defaults, which is also what makes combat wait for them
    (CR 608.2).
    """
    pool = set_pool("FEM")
    # A creature with no abilities of its own, deliberately: Farrel's Zealot
    # prints the *same* trigger condition, and two triggers owing two targets
    # would make the prompt this test reads ambiguous.
    attacker = Permanent(card=pool["Vodalian Soldiers"])     # 1/2, vanilla
    mantle = Permanent(card=pool["Farrel's Mantle"])
    victim = Permanent(card=pool["Icatian Phalanx"])         # 2/4
    bystander = Permanent(card=pool["Icatian Infantry"])     # 1/1
    game = Game(players=[
        PlayerState(name="P0", life=20, battlefield=[attacker, mantle]),
        PlayerState(name="P1", life=20, battlefield=[victim, bystander]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    attach_aura(mantle, attacker)
    game._settle()
    game.start_turn(0)
    for perm in (attacker, victim, bystander):
        perm.metadata["summoning_sickness_turn"] = -99
    return game, attacker, mantle, victim, bystander


def _g3_mantle_combat(game):
    """Attack unblocked and stop where blocks lock — CR 509.1h, which is where
    "attacks and isn't blocked" is announced."""
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {})[0]
    game._settle()
    game.advance_combat_phase()   # blocks lock; the trigger fires
    game._settle()
    for _ in range(len(game.stack) + 8):
        if not game.stack or not game.resolve_top_of_stack():
            break
    game._settle()


def _g3_finish_mantle_combat(game):
    for _ in range(len(list(game._phase_steps("combat"))) + 1):
        if game.current_turn_phase != "combat":
            break
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        game._settle()
        if (game.current_turn_phase, game.current_step) == before:
            break
    game.check_state_based_actions()


def test_g3_farrels_mantle_enchant_clause_offers_a_creature(set_pool):
    """The Aura's ``Enchant creature`` line is what the *cast* picker reads.

    Asserted on its own because the failure has no other symptom: a clause that
    derived ``kind: "none"`` would leave the client with nothing to ask for and
    the Aura uncastable in the app, while every compile-time instrument still
    reported the card supported.
    """
    card = set_pool("FEM")["Farrel's Mantle"]
    program = compile_card_oracle(card)

    assert program.supported
    assert derive_cast_spec(card, program) == {"kind": "creature"}


def test_g3_farrels_mantle_trades_combat_damage_for_a_bite(set_pool):
    """"…its controller may have it deal damage equal to its **power plus 2**
    to another target creature. If that player does, the attacking creature
    assigns no combat damage this turn."

    Every clause is measured by something it changed: the 1/2 deals **3** (the
    printed constant is carried, not dropped), the creature it bites is not
    itself ("another"), and the defending player's life is untouched — which is
    the only evidence the substitution ran, since nothing is prevented and no
    shield is spent.
    """
    game, attacker, mantle, victim, bystander = _g3_mantle_board(set_pool)

    pending = list(game.pending_choices_of("trigger_target"))
    assert pending == [], "the target is chosen when the trigger is put on the stack"

    _g3_mantle_combat(game)
    owed = list(game.pending_choices_of("trigger_target", 0))
    assert len(owed) == 1, game.log
    offered = {t["permanent_id"] for t in owed[0].data["targets"]}
    assert victim.permanent_id in offered
    assert attacker.permanent_id not in offered, (
        "\"another target creature\" excludes the creature dealing the damage"
    )
    assert game.confirm_trigger_target(0, victim.permanent_id)
    game._settle()

    assert game.confirm_optional_pay(0, "Farrel's Mantle", accept=True), game.log
    _g3_finish_mantle_combat(game)

    assert victim.damage_marked == 3, game.log
    assert game.players[1].life == 20, game.log


def test_g3_declining_the_mantle_leaves_the_attack_alone(set_pool):
    """"If that player does" — the other half. Nothing bitten, so the rider
    never runs and the 1/2 connects for one."""
    game, attacker, mantle, victim, bystander = _g3_mantle_board(set_pool)

    _g3_mantle_combat(game)
    assert game.confirm_trigger_target(0, victim.permanent_id)
    game._settle()
    assert game.confirm_optional_pay(0, "Farrel's Mantle", accept=False), game.log
    _g3_finish_mantle_combat(game)

    assert victim.damage_marked == 0
    assert game.players[1].life == 19, game.log
