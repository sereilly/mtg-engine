"""Tests for CR 703 (Turn-Based Actions).

A turn-based action is something the *game* does when a step or phase begins
or ends — not something a player does. The four rules of the section are all
about that distinction rather than about any one action:

- **703.1** they happen automatically and don't use the stack (703.1a: an
  ability that merely *watches* a step begin is an ordinary triggered ability
  and does use it),
- **703.2** no player controls them,
- **703.3** they are dealt with first when the step begins — before state-based
  actions are checked, before triggered abilities go on the stack, and before
  anybody gets priority,
- **703.4** the list of them.

The engine implements eight of 703.4's entries and each is covered below
against the step that performs it: 703.4a (phasing), 703.4c (untap),
703.4d (draw), 703.4i/703.4j (declare attackers/blockers),
703.4k/703.4m (combat damage assigned, then dealt simultaneously),
703.4n (cleanup discard), 703.4p (damage removed and "until end of turn"
effects end) and 703.4q (unspent mana empties).

What the steps themselves do is CR 500-514 and lives in
``test_phase_steps.py`` / ``test_combat_phase.py``; these tests only ask the
CR 703 questions about those same actions — did it use the stack, could a
player have controlled it, and did it come first.

Not covered because the engine doesn't have the mechanic: 703.4b (day/night),
703.4e (Archenemy schemes), 703.4f (Sagas), 703.4g (Attractions) and
703.4h (a multiplayer game's pre-chosen defending player; this engine chooses
a defender per attacker, CR 802).
"""

import pytest

from engine import Game
from engine.models import CardDefinition, Permanent, PlayerState
from engine.pt import add_pt_modifier


def _mk_creature(name: str, power: int, toughness: int, oracle_text: str = "",
                 keywords: tuple[str, ...] = ()) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=keywords,
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test", "power": str(power), "toughness": str(toughness)},
    )


def _mk_land(name: str = "Test Forest") -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Basic Land — Forest",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=("G",),
        raw={"name": name, "type_line": "Basic Land — Forest"},
    )


def _mk_enchantment(name: str, oracle_text: str) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Enchantment",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Enchantment"},
    )


class _RecordingStack(list):
    """``Game.stack`` that remembers every object ever put on it.

    "The stack is empty afterwards" is not what CR 703.1 says — an object that
    was pushed and then resolved would leave it empty too. This records the
    pushes, so a turn-based action that quietly built a stack object is visible
    even when nothing is left standing on the stack at the end.

    Installed by :func:`_watch_stack`, which is paired with
    :func:`_assert_nothing_was_stacked`: the engine replaces the list wholesale
    when it *removes* an item (``self.stack = [...]``), and a lost recorder
    would report an empty history for the wrong reason, so the check asserts
    the recorder is still the game's stack before believing it.
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.pushed: list = []

    def append(self, item):
        self.pushed.append(item)
        super().append(item)

    def insert(self, index, item):
        self.pushed.append(item)
        super().insert(index, item)


def _watch_stack(game: Game) -> _RecordingStack:
    recorder = _RecordingStack(game.stack)
    game.stack = recorder
    return recorder


def _assert_nothing_was_stacked(game: Game, recorder: _RecordingStack) -> None:
    assert game.stack is recorder, "the recorder was replaced; its history is not trustworthy"
    assert recorder.pushed == [], (
        "a turn-based action put an object on the stack: "
        + str([getattr(item, "card", None) and item.card.name for item in recorder.pushed])
    )
    assert list(recorder) == []


def _to_declare_attackers(game: Game) -> None:
    """Advance a fresh game (player 0 active) to the declare attackers step."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    assert game.current_step == "declare_attackers"


# ---------------------------------------------------------------------------
# 703.1 — turn-based actions don't use the stack
# ---------------------------------------------------------------------------


@pytest.mark.cr("703.1", "703.4c", "703.4d")
def test_turn_based_actions_never_put_an_object_on_the_stack():
    """Turn-based actions happen automatically and don't use the stack
    (703.1). A whole beginning phase performs two of them — the untap
    (703.4c) and the draw (703.4d) — and no stack object is ever created for
    either: not one that resolves and leaves, and not one that lingers."""
    land = Permanent(card=_mk_land("Bound Land"), tapped=True)
    creature = Permanent(card=_mk_creature("Bound Beast", 2, 2), tapped=True)
    p1 = PlayerState(name="P1", battlefield=[land, creature],
                     library=[_mk_land("Top"), _mk_land("Next")])
    p2 = PlayerState(name="P2", library=[_mk_land("Theirs")])
    game = Game(players=[p1, p2])
    game.turn = 2  # an ordinary turn — turn 1 skips the draw (CR 103.8a)
    recorder = _watch_stack(game)
    game.begin_turn_bookkeeping(0)

    untapped = game.resolve_untap_step(0)
    game.resolve_upkeep(0)
    drawn = game.resolve_draw_step(0, defer_priority=True)

    # Both turn-based actions demonstrably happened...
    assert untapped == 2
    assert not land.tapped and not creature.tapped
    assert drawn == 1
    assert [c.name for c in p1.hand] == ["Top"]
    # ...and neither of them was ever an object on the stack.
    _assert_nothing_was_stacked(game, recorder)


@pytest.mark.cr("703.1a", "703.1")
def test_an_ability_watching_a_step_begin_is_a_triggered_ability_not_a_turn_based_action():
    """703.1a: an ability that watches for a step to begin is a *triggered*
    ability, so unlike the turn-based action of the same step it does use the
    stack. The draw step performs both — the card is drawn with no stack
    object, and the one object the step does create is the trigger, which
    still has to resolve through a priority window before it does anything."""
    watcher = _mk_enchantment(
        "Draw Watcher",
        "At the beginning of your draw step, Draw Watcher deals 1 damage to you.",
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=watcher)],
                     library=[_mk_land("Top"), _mk_land("Next")], life=20)
    p2 = PlayerState(name="P2", library=[_mk_land("Theirs")], life=20)
    game = Game(players=[p1, p2])
    game.turn = 2
    recorder = _watch_stack(game)
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)

    drawn = game.resolve_draw_step(0, defer_priority=True)

    # Exactly one object was ever created by the step, and it is the trigger.
    assert game.stack is recorder
    assert len(recorder.pushed) == 1
    assert recorder.pushed[0].card.name == "Draw Watcher"
    assert len(game.stack) == 1  # still waiting: a trigger is not a turn-based action
    assert p1.life == 20         # ...so its effect hasn't happened yet
    # The draw, by contrast, is already done and never had a stack object.
    assert drawn == 1
    assert len(p1.hand) == 1

    assert game.pass_priority(0) == "passed"
    assert game.pass_priority(1) == "resolved_top"
    assert list(game.stack) == []
    assert p1.life == 19


# ---------------------------------------------------------------------------
# 703.2 — turn-based actions are not controlled by any player
# ---------------------------------------------------------------------------


@pytest.mark.cr("703.2", "703.4n")
def test_the_affected_player_cannot_decline_or_shrink_a_turn_based_action():
    """703.2: no player controls a turn-based action. The cleanup discard
    (703.4n) is the clearest case — the active player chooses *which* cards go
    (CR 514.1), which is a choice the action itself calls for, but they cannot
    choose to discard fewer than it demands, and with no input from them at all
    it still happens in full."""
    p1 = PlayerState(name="P1", hand=[_mk_land(f"L{i}") for i in range(9)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    # Naming one card when the action calls for two is refused outright, and
    # nothing is discarded: the player does not get to perform less of it.
    with pytest.raises(ValueError):
        game.resolve_cleanup_step(0, discard_hand_indices=[3])
    assert len(p1.hand) == 9
    assert p1.graveyard == []

    # And with no player input whatsoever, the action still happens.
    game.resolve_cleanup_step(0)

    assert len(p1.hand) == 7
    assert len(p1.graveyard) == 2


@pytest.mark.cr("703.2", "703.4c")
def test_a_turn_based_action_is_not_performed_by_whoever_holds_priority():
    """703.2 again, from the other side: the untap (703.4c) is the game's
    action for the active player, not an action taken by the player who
    happens to hold priority. Parking priority on the non-active player
    changes nothing — the active player's permanents untap and the priority
    holder's stay tapped, and nobody is asked anything."""
    mine = Permanent(card=_mk_creature("Mine", 2, 2), tapped=True)
    my_land = Permanent(card=_mk_land("My Land"), tapped=True)
    theirs = Permanent(card=_mk_creature("Theirs", 2, 2), tapped=True)
    p1 = PlayerState(name="P1", battlefield=[mine, my_land])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    game.start_priority_window(1)  # the *non-active* player holds priority
    assert game.priority_player_index == 1

    untapped = game.resolve_untap_step(0)

    assert untapped == 2
    assert not mine.tapped and not my_land.tapped
    assert theirs.tapped  # the priority holder's permanent is untouched
    assert game.pending_choices == []


# ---------------------------------------------------------------------------
# 703.3 — dealt with first: before SBAs, triggers and priority
# ---------------------------------------------------------------------------


@pytest.mark.cr("703.3", "703.4c")
def test_the_untap_action_is_dealt_with_before_state_based_actions_are_checked():
    """703.3: a step's turn-based actions come *before* state-based actions
    are checked. A creature carrying lethal damage as the untap step begins
    untaps first (703.4c, and the count proves it did) and only then dies to
    CR 704.5g — checking state-based actions first would have binned it while
    it was still tapped and left one permanent to untap instead of two."""
    doomed = Permanent(card=_mk_creature("Doomed", 2, 2), tapped=True)
    land = Permanent(card=_mk_land("Survivor"), tapped=True)
    p1 = PlayerState(name="P1", battlefield=[doomed, land])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    # Marked after the bookkeeping sweep, so the only state-based check that
    # can see it is the one the untap step itself runs.
    doomed.damage_marked = 3

    untapped = game.resolve_untap_step(0)

    assert untapped == 2       # the doomed creature untapped before it died
    assert not doomed.tapped
    assert [c.name for c in p1.graveyard] == ["Doomed"]
    assert [perm.card.name for perm in p1.battlefield] == ["Survivor"]


@pytest.mark.cr("703.3", "703.4d")
def test_the_draw_action_is_dealt_with_before_the_steps_trigger_and_before_priority():
    """703.3: the draw step's turn-based action (703.4d) is dealt with before
    triggered abilities are put on the stack and before any player receives
    priority. With a trigger watching the step begin, the card is already in
    hand while the trigger is still sitting on the stack unresolved and the
    active player has only just been handed priority."""
    watcher = _mk_enchantment(
        "Draw Watcher",
        "At the beginning of your draw step, Draw Watcher deals 1 damage to you.",
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=watcher)],
                     library=[_mk_land("Top"), _mk_land("Next")], life=20)
    p2 = PlayerState(name="P2", library=[_mk_land("Theirs")], life=20)
    game = Game(players=[p1, p2])
    game.turn = 2
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)

    drawn = game.resolve_draw_step(0, defer_priority=True)

    assert drawn == 1
    assert [c.name for c in p1.hand] == ["Top"]  # the turn-based action came first
    assert len(p1.library) == 1
    assert len(game.stack) == 1                  # the trigger has not resolved
    assert p1.life == 20
    assert game.has_priority(0)                  # ...and priority arrives after both


# ---------------------------------------------------------------------------
# 703.4a — phasing, during the untap step
# ---------------------------------------------------------------------------


@pytest.mark.cr("703.4a", "703.1")
def test_permanents_with_phasing_phase_out_when_the_untap_step_begins():
    """703.4a: immediately after the untap step begins, the active player's
    phased-in permanents with phasing phase out — automatically, and with
    nothing on the stack."""
    phaser = Permanent(card=_mk_creature("Phaser", 2, 2, "Phasing", keywords=("Phasing",)))
    steady = Permanent(card=_mk_creature("Steady", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[phaser, steady])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    recorder = _watch_stack(game)
    game.begin_turn_bookkeeping(0)

    game.resolve_untap_step(0)

    assert [perm.card.name for perm in p1.phased_out] == ["Phaser"]
    assert [perm.card.name for perm in p1.battlefield] == ["Steady"]
    _assert_nothing_was_stacked(game, recorder)


@pytest.mark.cr("703.4a", "703.4c")
def test_phasing_in_happens_before_the_active_player_untaps():
    """703.4a runs *before* 703.4c: a permanent that phased out tapped phases
    in during the same untap step and is then untapped by the untap action
    that follows it. Reverse the two and it would sit tapped for a turn."""
    held = Permanent(card=_mk_creature("Held", 2, 2, "Phasing", keywords=("Phasing",)), tapped=True)
    held.metadata["phased_out"] = True
    p1 = PlayerState(name="P1", battlefield=[], phased_out=[held])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    untapped = game.resolve_untap_step(0)

    assert p1.phased_out == []
    assert [perm.card.name for perm in p1.battlefield] == ["Held"]
    assert untapped == 1     # the untap action saw the permanent that had just arrived
    assert not held.tapped


# ---------------------------------------------------------------------------
# 703.4i / 703.4j — the two combat declarations
# ---------------------------------------------------------------------------


@pytest.mark.cr("703.4i", "703.1")
def test_attackers_are_declared_as_the_declare_attackers_steps_turn_based_action():
    """703.4i: the active player declares attackers immediately after the
    declare attackers step begins. The declaration itself uses no stack."""
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    bystander = Permanent(card=_mk_creature("Bystander", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker, bystander], library=[_mk_land()])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    _to_declare_attackers(game)
    recorder = _watch_stack(game)
    assert not attacker.attacking
    assert game.combat_attackers == {}

    ok, _ = game.declare_attackers(0, [0])

    assert ok
    assert game.current_step == "declare_attackers"
    assert attacker.attacking
    assert not bystander.attacking
    assert 0 in game.combat_attackers
    _assert_nothing_was_stacked(game, recorder)


@pytest.mark.cr("703.4j", "703.1")
def test_blockers_are_declared_as_the_declare_blockers_steps_turn_based_action():
    """703.4j: the defending player declares blockers immediately after the
    declare blockers step begins, and that declaration uses no stack either."""
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker], library=[_mk_land()])
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = Game(players=[p1, p2])
    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    recorder = _watch_stack(game)
    assert game.combat_blockers == {}

    ok, _ = game.declare_blockers(1, {0: [0]})

    assert ok
    assert game.current_step == "declare_blockers"
    assert game.combat_blockers == {1: {0: [0]}}
    _assert_nothing_was_stacked(game, recorder)


# ---------------------------------------------------------------------------
# 703.4k / 703.4m — combat damage assigned, then dealt simultaneously
# ---------------------------------------------------------------------------


@pytest.mark.cr("703.4k", "703.4m", "703.1")
def test_combat_damage_is_announced_first_and_then_dealt_simultaneously():
    """703.4k then 703.4m: each player announces how their attacking and
    blocking creatures assign their combat damage, and only *after* the
    assignment is all of that damage dealt — all of it at once.

    The 3/3 splits 2 and 1 across two 2/2 blockers. Simultaneity is what makes
    the attacker die: the blocker taking lethal is dealing its own 2 damage in
    the same event, so the attacker takes 4. Dealt one creature at a time with
    a state-based check between, the dead blocker would have dealt nothing and
    the attacker would have survived on 2."""
    attacker = Permanent(card=_mk_creature("Ogre", 3, 3))
    first = Permanent(card=_mk_creature("Bear A", 2, 2))
    second = Permanent(card=_mk_creature("Bear B", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker], library=[_mk_land()])
    p2 = PlayerState(name="P2", battlefield=[first, second], life=20)
    game = Game(players=[p1, p2])
    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {0: 0, 1: 0})
    game.advance_combat_phase()
    recorder = _watch_stack(game)

    # 703.4k: the step is waiting on the announcement, and until it comes no
    # combat damage has been dealt.
    assert game.current_step == "combat_damage"
    assert game._needs_manual_damage_assignment()
    assert game.combat_damage_resolved is False
    assert [perm.card.name for perm in p2.battlefield] == ["Bear A", "Bear B"]

    ok, _ = game.resolve_combat_damage(0, attacker_damage={0: {0: 2, 1: 1}})

    # 703.4m: everything the announcement assigned is dealt at once.
    assert ok
    assert game.combat_damage_resolved is True
    assert [perm.card.name for perm in p2.battlefield] == ["Bear B"]
    assert [c.name for c in p2.graveyard] == ["Bear A"]
    assert p1.battlefield == []                       # 2 + 2 killed the 3/3
    assert [c.name for c in p1.graveyard] == ["Ogre"]
    assert second.damage_marked == 1                  # the sub-lethal share landed too
    _assert_nothing_was_stacked(game, recorder)


# ---------------------------------------------------------------------------
# 703.4n / 703.4p — the cleanup step's two actions
# ---------------------------------------------------------------------------


@pytest.mark.cr("703.4n", "703.1")
def test_the_cleanup_discard_is_a_turn_based_action_of_the_cleanup_step():
    """703.4n: immediately after the cleanup step begins, an active player
    whose hand is over their maximum hand size discards down to it — with no
    stack object, and only the active player."""
    p1 = PlayerState(name="P1", hand=[_mk_land(f"L{i}") for i in range(10)])
    p2 = PlayerState(name="P2", hand=[_mk_land(f"T{i}") for i in range(9)])
    game = Game(players=[p1, p2])
    recorder = _watch_stack(game)
    game.begin_turn_bookkeeping(0)

    assert game.resolve_cleanup_step(0)

    assert len(p1.hand) == 7
    assert len(p1.graveyard) == 3
    assert len(p2.hand) == 9      # the non-active player's oversized hand is untouched
    _assert_nothing_was_stacked(game, recorder)


@pytest.mark.cr("703.4p", "703.4n")
def test_damage_is_removed_and_until_end_of_turn_effects_end_in_the_same_cleanup():
    """703.4p: after the discard, all damage is removed from permanents and
    all "until end of turn" effects end — simultaneously. The creature here is
    a 2/2 pumped to 2/5 until end of turn and carrying 4 damage: both halves
    happen in the one step, and because they happen together it neither dies
    of the damage it had nor keeps the toughness that was holding it up."""
    survivor = Permanent(card=_mk_creature("Survivor", 2, 2))
    add_pt_modifier(survivor, power=0, toughness=3, until="end_of_turn")
    survivor.damage_marked = 4
    p1 = PlayerState(name="P1", battlefield=[survivor],
                     hand=[_mk_land(f"L{i}") for i in range(8)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    assert survivor.effective_toughness == 5

    game.resolve_cleanup_step(0)

    assert len(p1.hand) == 7                  # 703.4n happened first
    assert survivor.damage_marked == 0        # damage removed...
    assert survivor.effective_toughness == 2  # ...and the "until end of turn" buff ended
    assert [perm.card.name for perm in p1.battlefield] == ["Survivor"]


# ---------------------------------------------------------------------------
# 703.4q — unspent mana empties as each step or phase ends
# ---------------------------------------------------------------------------


@pytest.mark.cr("703.4q")
def test_unspent_mana_empties_as_a_step_ends():
    """703.4q: as each step ends, any unspent mana left in a player's mana
    pool empties — every player's, not only the active player's."""
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=_mk_land("L"), tapped=True)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)
    p1.mana_pool["G"] = 3
    p2.mana_pool["U"] = 2

    game.resolve_untap_step(0)

    assert p1.mana_pool.get("G", 0) == 0
    assert p2.mana_pool.get("U", 0) == 0


@pytest.mark.cr("703.4q")
def test_unspent_mana_empties_as_a_phase_ends():
    """703.4q, the other half of "each step or phase": the main phase has no
    steps, so its own end is what empties the pool."""
    p1 = PlayerState(name="P1", library=[_mk_land("Top")])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    assert game.current_turn_phase == "precombat_main"
    p1.mana_pool["G"] = 3
    p2.mana_pool["U"] = 2

    game._close_current_priority_step()

    assert p1.mana_pool.get("G", 0) == 0
    assert p2.mana_pool.get("U", 0) == 0
