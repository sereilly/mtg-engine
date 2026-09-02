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


# --- W1G2: counted amounts ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g2_game(*battlefields):
    """A game whose seats hold the given battlefields, in seat order."""
    players = [
        PlayerState(name=f"P{i + 1}", battlefield=list(perms))
        for i, perms in enumerate(battlefields)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game, players


def _w1g2_creature(name, colors=("G",), subtypes="Human"):
    """A vanilla 1/1 with the given colours and printed creature types."""
    type_line = f"Creature — {subtypes}"
    return Permanent(card=CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line=type_line,
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1", "toughness": "1"},
    ))


def test_an_havva_constable_counts_green_creatures_on_both_battlefields(set_pool):
    """"An-Havva Constable's **toughness** is equal to 1 plus the number of
    green creatures **on the battlefield**."

    Two halves, and the card is wrong without either. The printed power stands
    (it is a 2/1+*), so only the toughness is defined; and CR 403.1's
    battlefield is one shared zone, so the count spans every seat. An unscoped
    count is taken on the caster's own board by default, which would have made
    the Constable read the opponent's green creatures as nothing at all."""
    pool = set_pool("HML")
    constable = Permanent(card=pool["An-Havva Constable"])
    mine = _w1g2_creature("Mine", colors=("G",))
    theirs = _w1g2_creature("Theirs", colors=("G",))
    red = _w1g2_creature("Red One", colors=("R",))
    game, _ = _w1g2_game([constable, mine, red], [theirs])

    # 1 + (the Constable itself, Mine, Theirs) = 4. The red creature is out.
    assert constable.effective_power == 2
    assert constable.effective_toughness == 4


def test_an_havva_constable_recounts_when_a_green_creature_leaves(set_pool):
    """CR 604.3: a characteristic-defining ability is recomputed continuously,
    so the toughness follows the board rather than being stamped once as the
    creature entered."""
    pool = set_pool("HML")
    constable = Permanent(card=pool["An-Havva Constable"])
    friend = _w1g2_creature("Friend", colors=("G",))
    game, players = _w1g2_game([constable, friend], [])
    assert constable.effective_toughness == 3

    game.remove_from_battlefield(friend)
    game._settle()

    assert constable.effective_toughness == 2


def test_aysen_crusader_counts_two_creature_types_as_a_union(set_pool):
    """"Aysen Crusader's power and toughness are each equal to 2 plus the
    number of **Soldiers and Warriors you control**."

    "And" between two creature types is the *union* — a Soldier is in the set
    and a Warrior is in the set — exactly as "artifact and enchantment" has
    been a union of card types since the noun parser was written. Read as a
    conjunction the set would be creatures that are both, which on this card's
    own board is almost always empty."""
    pool = set_pool("HML")
    crusader = Permanent(card=pool["Aysen Crusader"])
    soldier = _w1g2_creature("A Soldier", colors=("W",), subtypes="Human Soldier")
    warrior = _w1g2_creature("A Warrior", colors=("W",), subtypes="Human Warrior")
    both = _w1g2_creature("A Both", colors=("W",), subtypes="Soldier Warrior")
    plain = _w1g2_creature("A Human", colors=("W",), subtypes="Human")
    game, _ = _w1g2_game([crusader, soldier, warrior, both, plain], [])

    # 2 + (Soldier, Warrior, Both) = 5. The bare Human is out, and the one
    # creature carrying both types is counted once.
    assert crusader.effective_power == 5
    assert crusader.effective_toughness == 5


def test_aysen_crusader_does_not_count_an_opponents_soldiers(set_pool):
    """"…you control" is the half An-Havva Constable does not print, and the
    two cards share one count — so the scope has to come out of the noun phrase
    rather than out of a default, or one of them is wrong."""
    pool = set_pool("HML")
    crusader = Permanent(card=pool["Aysen Crusader"])
    theirs = _w1g2_creature("Their Soldier", colors=("W",), subtypes="Soldier")
    game, _ = _w1g2_game([crusader], [theirs])

    assert crusader.effective_power == 2
    assert crusader.effective_toughness == 2


def test_both_an_havva_cards_compile_the_same_count(set_pool):
    """An-Havva Constable's toughness and An-Havva Inn's life gain print the
    same printed count. They reach it through different machinery — a
    characteristic-defining P/T against a where-clause's X — so the guard worth
    having is that the *spec* they produce is identical: two counters would be
    one sentence meaning two numbers, which is the drift ``count_spec`` exists
    to prevent."""
    pool = set_pool("HML")
    creature = compile_card_oracle(pool["An-Havva Constable"])
    sorcery = compile_card_oracle(pool["An-Havva Inn"])

    cda = next(i for i in creature.instructions if i.kind == "dynamic_pt_count")
    gain = next(i for i in sorcery.instructions if i.kind == "target_gains_life")

    counted = dict(cda.payload["count_spec"])
    # The Constable's spec carries the printed "1 plus" as the count's offset;
    # the Inn prints its "plus 1" on the life gain instead, which is where the
    # sentence puts it.
    assert counted.pop("offset") == 1
    assert counted == gain.payload["x_from_count"]
    assert gain.payload["amount"] == {"plus_x": 1}

