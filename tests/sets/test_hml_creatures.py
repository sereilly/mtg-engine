"""Per-card tests for Homelands' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G4: filtered statics and block triggers ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g4_creature(
    name: str, colors: tuple[str, ...] = (), power: int = 2, toughness: int = 2,
) -> CardDefinition:
    """A vanilla creature of a named colour, for the far side of a block.

    Invented rather than pulled from the pool so the colour under test is the
    only thing that varies between the two halves of each pair below.
    """
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4_blocking(set_pool, own_name: str, *attackers: CardDefinition):
    """*own_name* on seat 1 blocking every one of *attackers* from seat 0.

    Stops in the declare-blockers step with the attack already declared, which
    is where a block trigger is announced (CR 509.1g).
    """
    mine = Permanent(card=set_pool("HML")[own_name])
    theirs = [Permanent(card=card) for card in attackers]
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(theirs)),
        PlayerState(name="P2", battlefield=[mine]),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(0, list(range(len(theirs))))
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers
    assert game.current_step == "declare_blockers"
    return game, mine, theirs


def test_rashka_the_slayer_pumps_when_it_blocks_a_black_creature(set_pool):
    """"Whenever Rashka blocks one or more black creatures, Rashka gets +1/+2."

    The narrowed half. Rashka is a 3/3 and the trigger is the only thing on the
    board that could change that.
    """
    game, rashka, _attackers = _w1g4_blocking(
        set_pool, "Rashka the Slayer", _w1g4_creature("Test Wight", ("B",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    assert (rashka.effective_power, rashka.effective_toughness) == (4, 5)


def test_rashka_the_slayer_does_not_pump_blocking_a_creature_of_another_colour(set_pool):
    """The half the card was mis-playing.

    Rashka reported *supported* before this group — its Reach line carries the
    card — while the trigger condition fell through to the bare "whenever this
    creature blocks" row, so the +1/+2 arrived on any block at all. The census
    cannot see that (a card is supported when any of its lines is), which is
    what makes this test the one worth writing.
    """
    game, rashka, _attackers = _w1g4_blocking(
        set_pool, "Rashka the Slayer", _w1g4_creature("Test Bear", ("G",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    assert (rashka.effective_power, rashka.effective_toughness) == (3, 3)


def test_rashka_the_slayer_triggers_once_for_two_black_creatures(set_pool):
    """CR 509.3e: "one or more" is a threshold, so the ability fires **once**
    however many creatures answered — not once per creature, which is what the
    singular "blocks a creature" wording would have given.

    Rashka can block two attackers only because an effect says so, so the block
    is built by hand rather than through the declaration's one-attacker cap.
    """
    game, rashka, _attackers = _w1g4_blocking(
        set_pool, "Rashka the Slayer",
        _w1g4_creature("Test Wight", ("B",)),
        _w1g4_creature("Test Shade", ("B",)),
    )
    rashka.metadata["can_block_any_number_until_eot"] = True

    assert game.declare_blockers(1, {0: [0, 1]})[0]
    game.resolve_stack()
    game._settle()

    assert (rashka.effective_power, rashka.effective_toughness) == (4, 5)


def test_sea_troll_cannot_regenerate_without_a_blue_creature_in_the_block(set_pool):
    """"Activate only if this creature blocked or was blocked by a blue creature
    this turn." (CR 602.5.)

    The unenforced direction is the dangerous one — an ability that works more
    often than the card allows — so the refusal is asserted before the
    permission.
    """
    game, troll, _attackers = _w1g4_blocking(
        set_pool, "Sea Troll", _w1g4_creature("Test Bear", ("G",))
    )
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    result = game.activate_permanent_ability(1, "Sea Troll")

    assert not result.supported
    assert "block" in result.details
    assert troll.regeneration_shield == 0


def test_sea_troll_regenerates_after_blocking_a_blue_creature(set_pool):
    """The same board with the attacker's colour changed, which is the only
    thing the clause asks about."""
    game, troll, _attackers = _w1g4_blocking(
        set_pool, "Sea Troll", _w1g4_creature("Test Drake", ("U",))
    )
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    result = game.activate_permanent_ability(1, "Sea Troll")
    game.resolve_stack()
    game._settle()

    assert result.supported, result.details
    assert troll.regeneration_shield == 1


def test_sea_troll_reads_the_block_from_the_other_side_too(set_pool):
    """"blocked **or was blocked by**" is one question about a symmetric
    relation (CR 509.1a), so the Troll attacking into a blue blocker answers it
    exactly as blocking a blue attacker does. Reading one of the two pair
    records would answer it for half the combats the creature was in.
    """
    troll = Permanent(card=set_pool("HML")["Sea Troll"])
    blocker = Permanent(card=_w1g4_creature("Test Drake", ("U",)))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[troll]),
        PlayerState(name="P2", battlefield=[blocker]),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    result = game.activate_permanent_ability(0, "Sea Troll")
    game.resolve_stack()
    game._settle()

    assert result.supported, result.details
    assert troll.regeneration_shield == 1


# --- W1G3: prevention, redirection and filtered damage ---

from engine import Game, PlayerState
from engine.damage_redirects import redirects_on
from engine.models import Permanent


def _g3_board(set_pool, *cards):
    """One seat with *cards* in play, costs off and nothing summoning-sick.

    ``cards`` is a card name from HML, or a ``(set_code, name)`` pair for
    anything else. Both seats get a battlefield: Daughter of Autumn's target is
    any white creature, so half of what these tests check is which board the
    chosen one was on.
    """
    perms = []
    for entry in cards:
        code, name = entry if isinstance(entry, tuple) else ("HML", entry)
        perms.append(Permanent(card=set_pool(code)[name]))
    for perm in perms:
        perm.metadata["summoning_sickness_turn"] = -99
    mine, theirs = perms[:1], perms[1:]
    p0 = PlayerState(name="P0", battlefield=list(mine))
    p1 = PlayerState(name="P1", battlefield=list(theirs))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._settle()
    return game, perms


def _g3_activate(game, name, target, *, x_value=None):
    """Activate *name*'s only ability at *target*, and resolve it.

    ``target_player_index`` is the seat the chosen permanent is *on*, which is
    what both the browser picker and ``ai_policy`` send: the resolver scopes an
    announced id to that battlefield, so an ability aimed across the table has
    to say so.
    """
    seat, _ = game.find_permanent_by_id(game.permanent_id_of(target))
    result = game.activate_permanent_ability(
        0, name, ability_index=0, target_player_index=seat,
        target_permanent_ids=[game.permanent_id_of(target)],
        **({} if x_value is None else {"x_value": x_value}),
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return result


def test_daughter_of_autumn_moves_one_point_and_leaves_the_rest(set_pool):
    """"The next 1 damage that would be dealt to target white creature this turn
    is dealt to Daughter of Autumn instead."

    A **point pool**, not a whole-event record: one point moves and the other
    two are dealt to the creature exactly as they would have been. A redirect
    with no pool would have taken all three, which is a strictly larger card.
    """
    game, (daughter, knight) = _g3_board(
        set_pool, "Daughter of Autumn", ("LEA", "White Knight"),
    )
    result = _g3_activate(game, "Daughter of Autumn", knight)
    assert result.supported, result.details

    game._mark_damage_on_permanent(knight, 3, source=None)

    assert daughter.damage_marked == 1, "one point moved onto the Daughter"
    assert knight.damage_marked == 2, "and the rest landed where it was aimed"


def test_daughter_of_autumns_pool_is_spent_by_the_first_event(set_pool):
    """Once the point is gone the record is gone, so a second source this turn
    is dealt in full. A record spent by *instances* would have survived a
    1-point event and moved a point of the next one too."""
    game, (daughter, knight) = _g3_board(
        set_pool, "Daughter of Autumn", ("LEA", "White Knight"),
    )
    _g3_activate(game, "Daughter of Autumn", knight)

    game._mark_damage_on_permanent(knight, 1, source=None)
    game._mark_damage_on_permanent(knight, 1, source=None)

    assert daughter.damage_marked == 1
    assert knight.damage_marked == 1
    assert redirects_on(knight) == [], "the spent record no longer exists"


def test_daughter_of_autumn_protects_an_opponents_white_creature_too(set_pool):
    """The printed phrase is "target white creature" with no seat clause, so
    either board is a legal answer — and the record has to be armed on the
    permanent that was actually named rather than on one this seat controls."""
    game, (daughter, knight) = _g3_board(
        set_pool, "Daughter of Autumn", ("LEA", "White Knight"),
    )
    game.remove_from_battlefield(knight)
    game.players[1].battlefield.append(knight)
    game._settle()

    result = _g3_activate(game, "Daughter of Autumn", knight)

    assert result.supported, result.details
    game._mark_damage_on_permanent(knight, 1, source=None)
    assert daughter.damage_marked == 1


def test_daughter_of_autumn_refuses_a_creature_that_is_not_white(set_pool):
    """The colour is the narrowing, and an ability with a mandatory target it
    cannot fill is refused with nothing paid rather than activated at nothing."""
    game, (_daughter, bears) = _g3_board(
        set_pool, "Daughter of Autumn", ("LEA", "Grizzly Bears"),
    )

    result = _g3_activate(game, "Daughter of Autumn", bears)

    assert not result.supported
    assert redirects_on(bears) == []


def test_hazduhr_the_abbot_moves_the_x_its_controller_announced(set_pool):
    """"{X}, {T}: The next X damage …" — the pool is the announced X, and it is
    spent across as many events as it takes. Three points cover a 2 and then one
    point of a 4; the remaining 3 land on the creature."""
    game, (abbot, knight) = _g3_board(
        set_pool, "Hazduhr the Abbot", ("LEA", "White Knight"),
    )
    game.remove_from_battlefield(knight)
    game.players[0].battlefield.append(knight)
    knight.metadata["summoning_sickness_turn"] = -99
    game._settle()
    result = _g3_activate(game, "Hazduhr the Abbot", knight, x_value=3)
    assert result.supported, result.details

    game._mark_damage_on_permanent(knight, 2, source=None)
    game._mark_damage_on_permanent(knight, 4, source=None)

    assert abbot.damage_marked == 3, "the whole announced pool moved"
    assert knight.damage_marked == 3, "and what it could not cover landed"


def test_hazduhr_the_abbot_only_protects_creatures_you_control(set_pool):
    """Hazduhr prints "target white creature **you control**" where Daughter of
    Autumn prints none — the same sentence, one word narrower, and a lowering
    that dropped the word would let the Abbot shield the table."""
    game, (_abbot, knight) = _g3_board(
        set_pool, "Hazduhr the Abbot", ("LEA", "White Knight"),
    )

    result = _g3_activate(game, "Hazduhr the Abbot", knight, x_value=2)

    assert not result.supported
    assert redirects_on(knight) == []


def test_the_ai_points_daughter_of_autumn_at_its_own_creature(set_pool):
    """The ability protects whoever it names, so a seat that aims it across the
    table has spent its mana shielding the enemy.

    ``activation_target_side`` derives the side from the compiled program, and
    the *category* cannot answer here: a CR 614.9 redirect is categorised
    ``damage`` because the damage is still dealt, which is right about the
    family and backwards about the side. Aimed by the category alone the AI
    picked the opponent's White Knight.
    """
    from engine.ai_policy import choose_activation_action

    game, (daughter, theirs) = _g3_board(
        set_pool, "Daughter of Autumn", ("LEA", "White Knight"),
    )
    mine = Permanent(card=set_pool("LEA")["White Knight"])
    mine.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield.append(mine)
    game._settle()

    action = choose_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Daughter of Autumn"
    assert action.target_player_index == 0, "it shields its own controller's board"
    chosen = game.permanent_at(game.players[0], action.target_permanent_index)
    assert chosen is mine and chosen is not theirs
