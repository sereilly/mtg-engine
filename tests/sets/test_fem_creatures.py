"""Per-card tests for Fallen Empires' creatures.

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
from engine.game import Game
from engine.models import Permanent, PlayerState


def _g3_board(pool, *, mine, theirs, interactive=(0,)):
    """A two-player board with combat ready to be walked, and no mana enforced.

    Seat 0 is interactive by default so an offer the resolution owes *queues*
    rather than taking its default at once — which is also what makes combat
    wait for the answer (CR 608.2).
    """
    p0 = PlayerState(
        name="P0", life=20, battlefield=[Permanent(card=pool[n]) for n in mine]
    )
    p1 = PlayerState(
        name="P1", life=20, battlefield=[Permanent(card=pool[n]) for n in theirs]
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._settle()
    game.start_turn(0)
    for perm in list(p0.battlefield) + list(p1.battlefield):
        perm.metadata["summoning_sickness_turn"] = -99
    return game, p0, p1


def _g3_to_beginning_of_combat(game, *, mana=None, seat=1):
    """Walk to the beginning of combat and resolve what triggered there.

    Its own step because a beginning-of-combat *trigger* goes on the stack
    (CR 603.3) and only offers its payment once it resolves — walking straight
    to the declaration would leave the offer unmade and the prompt unarmed.

    *mana* fills a seat's pool **after** the step boundary, which is where it
    has to go: CR 500.4 empties the pool as a step ends, so mana put there
    before the walk is gone by the time the offer is made. A seat with nothing
    to pay with is not offered the choice at all (CR 601.2b), so the pool is
    what makes the decline a decision rather than an inability.
    """
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    if mana is not None:
        game.players[seat].mana_pool = dict(mana)
    _g3_settle_stack(game)


def _g3_to_declare_attackers(game):
    _g3_to_beginning_of_combat(game)
    game.advance_combat_phase()   # declare attackers


def _g3_settle_stack(game):
    """Resolve what the stack holds, stopping at anything it cannot.

    Bounded rather than ``while game.stack``: an object holding a prompt open
    stays on the stack until the prompt is answered (CR 608.2), so an unbounded
    loop over ``resolve_top_of_stack`` spins instead of failing.
    """
    for _ in range(len(game.stack) + 8):
        if not game.stack or not game.resolve_top_of_stack():
            break
    game._settle()


def _g3_finish_combat(game):
    for _ in range(len(list(game._phase_steps("combat"))) + 1):
        if game.current_turn_phase != "combat":
            break
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        game._settle()
        if (game.current_turn_phase, game.current_step) == before:
            break
    game.check_state_based_actions()


def test_g3_dwarven_soldier_toughens_once_against_one_or_more_orcs(set_pool):
    """"…blocks or becomes blocked by **one or more** Orcs" — CR 509.3e: an
    ability that triggers on being blocked by *at least* a number of creatures
    triggers **once**, however many answer.

    Two Orcs block, and the Dwarf ends the declaration a 2/3 rather than a 2/5:
    the second firing is what a per-creature reading (CR 509.3d) would have
    added, and the toughness is what tells the two apart.
    """
    pool = set_pool("FEM")
    game, p0, p1 = _g3_board(
        pool, mine=["Dwarven Soldier"], theirs=["Orcish Spy", "Orcish Spy"]
    )
    soldier = p0.battlefield[0]

    _g3_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {0: [0], 1: [0]})[0]
    game._settle()
    _g3_settle_stack(game)

    assert soldier.effective_toughness == 3, game.log
    assert soldier.effective_power == 2


def test_g3_dwarven_soldier_ignores_a_block_by_anything_else(set_pool):
    """The printed noun is a narrowing, not decoration: a block by something
    that is not an Orc leaves the 2/1 a 2/1."""
    pool = set_pool("FEM")
    game, p0, p1 = _g3_board(
        pool, mine=["Dwarven Soldier"], theirs=["Vodalian Soldiers"]
    )
    soldier = p0.battlefield[0]

    _g3_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: [0]})[0]
    game._settle()
    _g3_settle_stack(game)

    assert soldier.effective_toughness == 1, game.log


def test_g3_orcish_veteran_may_not_block_a_white_two_power_creature(set_pool):
    """"…can't block **white creatures with power 2 or greater**" — CR 509.1b,
    with *two* narrowings stacked on one noun phrase.

    The colour and the threshold are both payload now, so the gate asks
    ``subject_matches`` about the attacker: a white 2/2 is refused, a white 1/1
    is legal, and so is a red 3/2 — one experiment per printed word, because a
    restriction reading only one of them would pass the first assertion.
    """
    pool = set_pool("FEM")
    game, p0, p1 = _g3_board(
        pool,
        mine=["Farrel's Zealot", "Icatian Infantry", "Brassclaw Orcs"],
        theirs=["Orcish Veteran"],
    )
    veteran = p1.battlefield[0]

    _g3_to_declare_attackers(game)
    assert game.declare_attackers(0, [0, 1, 2])[0]
    game._settle()
    game.advance_combat_phase()

    assert not game._can_block_attacker(veteran, p0.battlefield[0]), (
        "a white 2/2 is exactly what the card forbids"
    )
    assert game._can_block_attacker(veteran, p0.battlefield[1]), (
        "a white 1/1 is under the threshold"
    )
    assert game._can_block_attacker(veteran, p0.battlefield[2]), (
        "a red 3/2 is over the threshold and the wrong colour"
    )
    assert not game.declare_blockers(1, {0: [0]})[0], game.log


def test_g3_icatian_skirmishers_gives_first_strike_to_its_band(set_pool):
    """"…all creatures **banded with it** gain first strike until end of turn."

    CR 702.22e's band is a declaration rather than a characteristic, so the
    test has to be a real attack: the band-mate strikes first and the attacker
    outside the band does not — which is the assertion a filter that dropped
    the phrase would fail, having granted to the whole board.
    """
    pool = set_pool("FEM")
    game, p0, p1 = _g3_board(
        pool,
        mine=["Icatian Skirmishers", "Icatian Phalanx", "Brassclaw Orcs"],
        theirs=[],
    )
    skirmishers, phalanx, orcs = p0.battlefield

    _g3_to_declare_attackers(game)
    assert game.declare_attackers(0, [0, 1, 2], bands=[[0, 1]])[0]
    game._settle()
    _g3_settle_stack(game)

    assert game._has_keyword(phalanx, "first strike"), game.log
    assert not game._has_keyword(orcs, "first strike"), (
        "attacking beside a band is not being in it"
    )


def test_g3_mindstab_thrull_makes_the_defender_choose_three_discards(set_pool):
    """"…you may sacrifice it. If you do, **defending player discards three
    cards**."

    A *counted, chosen* discard by a seat nobody targeted: the count is
    payload, and CR 506.2's seat comes from the trigger's own context. Both
    halves are asserted — the Thrull leaves and the hand loses exactly three —
    because a discard aimed at the wrong seat would still empty a hand.
    """
    pool = set_pool("FEM")
    game, p0, p1 = _g3_board(pool, mine=["Mindstab Thrull"], theirs=[])
    p1.hand = [pool["Vodalian Soldiers"] for _ in range(5)]
    thrull = p0.battlefield[0]

    _g3_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()   # declare blockers: nobody can block
    game.advance_combat_phase()   # blocks lock, the trigger fires
    game._settle()
    _g3_settle_stack(game)

    assert game.confirm_optional_pay(0, "Mindstab Thrull", accept=True), game.log
    game._settle()

    assert not game.is_on_battlefield(thrull), game.log
    # The prompt is the assertion: it is armed for the *defending* seat and it
    # asks for three, which is the whole of what the sentence adds to Cloak of
    # Confusion's one-at-random.
    owed = game.pending_choices_of("discard", 1)
    assert [c.data["count"] for c in owed] == [3], game.log
    assert game.confirm_discard(1, [0, 1, 2])
    game._settle()

    assert len(p1.hand) == 2, game.log
    assert len(p1.graveyard) == 3


def test_g3_goblin_flotilla_hands_first_strike_to_its_blocker_when_unpaid(set_pool):
    """"At the beginning of each combat, **unless you pay {R}**, whenever this
    creature blocks or becomes blocked by a creature this combat, that creature
    gains first strike until end of turn."

    The drawback resolves in three steps and every one is here: the
    beginning-of-combat trigger offers its own controller the payment,
    declining creates a delayed ability scoped to the combat (CR 603.7b), and
    the block then hands first strike to *the other half of the pair* — the
    creature the Flotilla's controller would rather not have it.
    """
    pool = set_pool("FEM")
    game, p0, p1 = _g3_board(
        pool, mine=["Brassclaw Orcs"], theirs=["Goblin Flotilla"],
        interactive=(1,),
    )
    attacker, flotilla = p0.battlefield[0], p1.battlefield[0]

    _g3_to_beginning_of_combat(game, mana={"R": 1})
    assert game.confirm_optional_pay(1, "Goblin Flotilla", accept=False), game.log
    game._settle()
    assert [e.event for e in game.delayed_triggers] == [
        "source_blocks_or_blocked_by"
    ], game.log

    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: [0]})[0]
    game._settle()
    _g3_settle_stack(game)

    assert game._has_keyword(attacker, "first strike"), game.log
    assert not game._has_keyword(flotilla, "first strike"), (
        "the ability names the *other* half of the pair, never its own source"
    )


def test_g3_paying_the_flotillas_price_arms_nothing(set_pool):
    """The other side of the offer: {R} paid, no delayed ability created, and
    the attacker it blocks strikes at ordinary speed."""
    pool = set_pool("FEM")
    game, p0, p1 = _g3_board(
        pool, mine=["Brassclaw Orcs"], theirs=["Goblin Flotilla"],
        interactive=(1,),
    )
    attacker = p0.battlefield[0]

    _g3_to_beginning_of_combat(game, mana={"R": 1})
    assert game.confirm_optional_pay(1, "Goblin Flotilla", accept=True), game.log
    game._settle()
    assert game.delayed_triggers == [], game.log

    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: [0]})[0]
    game._settle()
    _g3_settle_stack(game)

    assert not game._has_keyword(attacker, "first strike"), game.log


def test_g3_the_flotillas_delay_expires_with_its_combat(set_pool):
    """"…this combat" is CR 603.7b's stated duration over the shorter window:
    an entry armed for one combat phase must not still be waiting in the next,
    or a second combat would hand out first strike the card never offered."""
    pool = set_pool("FEM")
    game, p0, p1 = _g3_board(
        pool, mine=["Brassclaw Orcs"], theirs=["Goblin Flotilla"],
        interactive=(1,),
    )

    _g3_to_beginning_of_combat(game, mana={"R": 1})
    assert game.confirm_optional_pay(1, "Goblin Flotilla", accept=False)
    game._settle()
    assert game.delayed_triggers

    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [])[0]
    game._settle()
    _g3_finish_combat(game)

    assert game.delayed_triggers == [], game.log
