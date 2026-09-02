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


# --- W1G1: untap denial ---

from engine import Game, PlayerState
from engine.damage_events import deal_damage
from engine.game_types import CardDefinition
from engine.models import Permanent


def _g1_creature(name: str, subtype: str = "Test", colors: tuple[str, ...] = ()):
    """A plain 2/5 with a printed subtype, for the noun phrases these cards
    narrow by. Toughness 5 so a blocker survives the combat its own trigger is
    about."""
    type_line = f"Creature - {subtype}"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=colors, color_identity=colors, keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "5"},
    )


def _g1_ready(*permanents):
    """Everything in *permanents* able to act this turn (CR 302.6)."""
    for permanent in permanents:
        permanent.metadata["summoning_sickness_turn"] = -99
    return permanents


def _g1_settle(game):
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()


def _g1_to_declare_attackers(game):
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers


def test_reveka_pings_and_holds_itself_down_a_turn(set_pool):
    """"{T}: Reveka deals 2 damage to any target **and doesn't untap during
    your next untap step**."

    One noun phrase printed once and two things said about it, which is the
    tail two pump verbs already carried and this round put on the third. The
    damage half and the restriction half are asserted together: the clause used
    to be unconsumed text, so the whole ability was unsupported rather than
    half-done.
    """
    reveka = Permanent(card=set_pool("HML")["Reveka, Wizard Savant"])
    _g1_ready(reveka)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[reveka]), PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()

    result = game.activate_permanent_ability(
        0, "Reveka, Wizard Savant", permanent_index=0, target_player_index=1
    )
    _g1_settle(game)

    assert result.supported, result.details
    assert game.players[1].life == 18
    assert reveka.tapped is True

    game.resolve_untap_step(0)
    assert reveka.tapped is True
    game.resolve_untap_step(0)
    assert reveka.tapped is False


def test_revekas_skipped_untap_is_your_step_and_not_an_opponents(set_pool):
    """"...during **your** next untap step" names a seat, not "its controller's
    next untap step". An opponent's untap step must not spend the restriction,
    because it is not the step the card named."""
    reveka = Permanent(card=set_pool("HML")["Reveka, Wizard Savant"])
    _g1_ready(reveka)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[reveka]), PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()

    game.activate_permanent_ability(
        0, "Reveka, Wizard Savant", permanent_index=0, target_player_index=1
    )
    _g1_settle(game)

    game.resolve_untap_step(1)
    assert reveka.metadata.get("skip_next_untap") == 1
    game.resolve_untap_step(0)
    assert reveka.metadata.get("skip_next_untap") is None


def test_spectral_bears_stays_tapped_when_the_defender_is_not_black(set_pool):
    """"Whenever this creature attacks, if defending player controls no black
    nontoken permanents, **it** doesn't untap during your next untap step."

    "It" is the creature the trigger's own condition named - there is no
    earlier sentence for the pronoun to point back at, which is what the
    lowering used to demand. The Bears attack for free and pay for it on the
    way back.
    """
    bears = Permanent(card=set_pool("HML")["Spectral Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears]), PlayerState(name="P2"),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    _g1_settle(game)

    assert bears.tapped is True
    game.resolve_untap_step(0)
    assert bears.tapped is True
    game.resolve_untap_step(0)
    assert bears.tapped is False


def test_spectral_bears_untaps_normally_against_a_black_permanent(set_pool):
    """The intervening if is the card: one black nontoken permanent on the
    defender's side and the drawback never fires. Asserted beside the row above
    so a trigger that ignored its condition cannot pass on one of them."""
    bears = Permanent(card=set_pool("HML")["Spectral Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears]),
        PlayerState(
            name="P2",
            battlefield=[Permanent(card=_g1_creature("Bog Rat", colors=("B",)))],
        ),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    _g1_settle(game)

    assert bears.metadata.get("skip_next_untap") is None
    game.resolve_untap_step(0)
    assert bears.tapped is False


def test_labyrinth_minotaur_holds_down_what_it_blocks(set_pool):
    """"Whenever this creature blocks a creature, **that creature** doesn't
    untap during its controller's next untap step."

    "That creature" is the *attacker* the trigger bound, which no sentence in
    the line names - so it comes from the block pair rather than from the stack
    item's target. Reading the target on the blocks half would mark the
    Minotaur itself, which is the second assertion below.
    """
    minotaur = Permanent(card=set_pool("HML")["Labyrinth Minotaur"])
    attacker = Permanent(card=_g1_creature("Grey Ogre"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[minotaur]),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {0: 0})[0]
    _g1_settle(game)

    assert attacker.metadata.get("skip_next_untap") == 1
    assert minotaur.metadata.get("skip_next_untap") is None

    attacker.tapped = True
    game.resolve_untap_step(0)
    assert attacker.tapped is True
    game.resolve_untap_step(0)
    assert attacker.tapped is False


def test_labyrinth_minotaur_marks_nobody_when_it_does_not_block(set_pool):
    """No block, no trigger, no marker - the control for the row above, so a
    handler that marked whatever it found on the board cannot pass it."""
    minotaur = Permanent(card=set_pool("HML")["Labyrinth Minotaur"])
    attacker = Permanent(card=_g1_creature("Grey Ogre"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[minotaur]),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {})[0]
    _g1_settle(game)

    assert attacker.metadata.get("skip_next_untap") is None


def test_jovens_ferrets_taps_only_the_creatures_that_blocked_it(set_pool):
    """"At end of combat, tap all creatures that blocked this creature this
    turn. **They** don't untap during their controller's next untap step."

    Two things at once: a noun phrase narrowed by a block *history* read off
    the record the declare-blockers step stamps, and a plural pronoun naming
    what the sentence in front of it swept. A bystander on the same
    battlefield is the control - a dropped narrowing would tap the board.
    """
    ferrets = Permanent(card=set_pool("HML")["Joven's Ferrets"])
    blocker = Permanent(card=_g1_creature("Wall of Test"))
    bystander = Permanent(card=_g1_creature("Idle Ogre"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[ferrets]),
        PlayerState(name="P2", battlefield=[blocker, bystander]),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    _g1_settle(game)
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {0: 0})[0]
    _g1_settle(game)
    game.advance_combat_phase()   # combat damage
    _g1_settle(game)
    game.advance_combat_phase()   # end of combat
    _g1_settle(game)

    assert blocker.tapped is True
    assert blocker.metadata.get("skip_next_untap") == 1
    assert bystander.tapped is False
    assert bystander.metadata.get("skip_next_untap") is None

    game.resolve_untap_step(1)
    assert blocker.tapped is True
    game.resolve_untap_step(1)
    assert blocker.tapped is False


def test_jovens_ferrets_still_pumps_itself_when_it_attacks(set_pool):
    """Its first line, asserted beside the second so a change to either cannot
    pass on the other: a 1/1 Ferret is a 1/3 for the combat it started."""
    ferrets = Permanent(card=set_pool("HML")["Joven's Ferrets"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[ferrets]), PlayerState(name="P2"),
    ])
    _g1_to_declare_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    _g1_settle(game)

    assert ferrets.effective_toughness == 3


def test_samite_alchemist_shields_taps_and_holds_one_creature(set_pool):
    """"{W}{W}, {T}: Prevent the next 4 damage that would be dealt **this turn
    to** target creature you control. Tap that creature. It doesn't untap
    during your next untap step."

    All three sentences about one target. The printed word order puts the
    duration before the recipient, which is the same sentence the modern
    printing spells the other way round - the blanket shield beside it already
    read either, and a numeric one failing on word order was the card lost to a
    printing convention rather than to a missing effect.
    """
    alchemist = Permanent(card=set_pool("HML")["Samite Alchemist"])
    ally = Permanent(card=_g1_creature("Grey Ogre"))
    _g1_ready(alchemist, ally)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[alchemist, ally]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()

    result = game.activate_permanent_ability(
        0, "Samite Alchemist", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    _g1_settle(game)

    assert result.supported, result.details
    assert ally.damage_prevention_pool == 4
    assert ally.tapped is True

    outcome = deal_damage(game, {"recipient": ally, "amount": 3, "source": None})
    assert outcome.dealt == 0
    assert ally.damage_marked == 0
    assert ally.damage_prevention_pool == 1

    game.resolve_untap_step(0)
    assert ally.tapped is True
    game.resolve_untap_step(0)
    assert ally.tapped is False


def test_samite_alchemist_leaves_an_untargeted_creature_alone(set_pool):
    """The tap and the untap restriction name the creature the *first* sentence
    chose, not a second one - so a bystander on the same battlefield is
    untouched by all three sentences."""
    alchemist = Permanent(card=set_pool("HML")["Samite Alchemist"])
    ally = Permanent(card=_g1_creature("Grey Ogre"))
    bystander = Permanent(card=_g1_creature("Idle Ogre"))
    _g1_ready(alchemist, ally, bystander)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[alchemist, ally, bystander]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._settle()

    game.activate_permanent_ability(
        0, "Samite Alchemist", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    _g1_settle(game)

    assert bystander.tapped is False
    assert bystander.damage_prevention_pool == 0
    assert bystander.metadata.get("skip_next_untap") is None


# --- W1G5: upkeep, counters and forced sacrifice ---

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on


def _w1g5_lea():
    return {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _w1g5_caravan(set_pool, *, active_seat: int, counters: int = 3):
    """Trade Caravan and a tapped Plains, on the seat whose upkeep is not
    running unless *active_seat* says so."""
    caravan = Permanent(card=set_pool("HML")["Trade Caravan"])
    caravan.metadata["summoning_sickness_turn"] = -99
    land = Permanent(card=_w1g5_lea()["Plains"])
    p1 = PlayerState(name="P1", battlefield=[caravan, land])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(active_seat)
    game._settle()
    game.current_step = "upkeep"
    add_counters(caravan, "currency", counters - counters_on(caravan, "currency"))
    land.tapped = True
    return game, caravan, land


def test_trade_caravan_banks_a_currency_counter_each_upkeep(set_pool):
    """"At the beginning of your upkeep, put a currency counter on this
    creature." The counters are what the untap is bought with, so a Caravan that
    banked none can never use its ability."""
    caravan = Permanent(card=set_pool("HML")["Trade Caravan"])
    game = Game(players=[PlayerState(name="P1", battlefield=[caravan]),
                         PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()

    assert counters_on(caravan, "currency") == 1


def test_trade_caravan_untaps_a_basic_land_on_an_opponents_upkeep(set_pool):
    """"Remove two currency counters from this creature: Untap target basic
    land. Activate only during an opponent's upkeep." """
    game, caravan, land = _w1g5_caravan(set_pool, active_seat=1)

    result = game.activate_permanent_ability(
        0, "Trade Caravan", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert not land.tapped
    assert counters_on(caravan, "currency") == 1


def test_trade_caravan_is_refused_on_its_own_controllers_upkeep(set_pool):
    """The printed window is an **opponent's** upkeep, and an unenforced timing
    clause is an ability that works more often than the card allows.

    The counters are the other half of the assertion: CR 602.5 forbids the
    activation from *beginning*, so nothing in CR 601.2's steps happens and the
    cost is not paid. This engine charged a counter-removal cost above the
    timing gate, so a Caravan refused here used to lose two counters for it.
    """
    game, caravan, land = _w1g5_caravan(set_pool, active_seat=0)
    held = counters_on(caravan, "currency")

    result = game.activate_permanent_ability(
        0, "Trade Caravan", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert not result.supported
    assert land.tapped
    assert counters_on(caravan, "currency") == held


def test_trade_caravan_is_refused_outside_an_upkeep_step(set_pool):
    """An opponent's *turn* is not an opponent's *upkeep*: the clause names a
    step, and a window widened to the whole turn is the same silent gift."""
    game, caravan, land = _w1g5_caravan(set_pool, active_seat=1)
    game.current_step = None
    game.current_turn_phase = "precombat_main"

    result = game.activate_permanent_ability(
        0, "Trade Caravan", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert not result.supported
    assert land.tapped



# --- W2G3: combat restrictions and shroud exceptions ---

from engine import Game, PlayerState
from engine.activation_restrictions import activation_denial
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.target_immunity import shroud_waived_seats
from engine.targeting import derive_activation_spec


def _w2g3_ready(permanent: Permanent) -> Permanent:
    permanent.metadata["summoning_sickness_turn"] = -5
    return permanent


def _w2g3_game(*seat_battlefields, set_pool=None):
    lea = set_pool("LEA")
    players = [
        PlayerState(name=f"P{index + 1}", battlefield=list(battlefield),
                    library=[lea["Forest"]] * 8)
        for index, battlefield in enumerate(seat_battlefields)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game


# Autumn Willow --------------------------------------------------------------


def test_autumn_willow_opens_its_shroud_to_one_seat_only(set_pool):
    """"{G}: Until end of turn, Autumn Willow can be the target of spells and
    abilities controlled by target player as though it didn't have shroud."

    CR 609.4's "as though" cutting a hole in CR 702.18 for the chosen seat and
    nobody else. Asserted with three seats, where "the named player" and "not
    the controller" are different answers.
    """
    lea = set_pool("LEA")
    willow = _w2g3_ready(Permanent(card=set_pool("HML")["Autumn Willow"]))
    game = _w2g3_game([willow], [], [], set_pool=set_pool)
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Autumn Willow", target_player_index=1
    )
    game._settle()
    assert result.supported, result.details
    assert shroud_waived_seats(willow) == (1,)

    terror = lea["Terror"]
    assert game._can_be_targeted(willow, terror, caster_index=1) is True
    assert game._can_be_targeted(willow, terror, caster_index=2) is False
    assert game._can_be_targeted(willow, terror, caster_index=0) is False
    assert game._can_be_targeted(willow, terror) is False, (
        "a probe that cannot say whose spell this is keeps the shroud"
    )


def test_the_autumn_willow_waiver_ends_with_the_turn(set_pool):
    """"Until end of turn" is the cleanup sweep and nothing else."""
    willow = _w2g3_ready(Permanent(card=set_pool("HML")["Autumn Willow"]))
    game = _w2g3_game([willow], [], set_pool=set_pool)
    game.start_turn(0)
    game.activate_permanent_ability(0, "Autumn Willow", target_player_index=1)
    game._settle()
    assert shroud_waived_seats(willow) == (1,)

    game.resolve_cleanup_step(0)

    assert shroud_waived_seats(willow) == ()
    assert game._can_be_targeted(
        willow, set_pool("LEA")["Terror"], caster_index=1
    ) is False


def test_autumn_willow_targets_a_player_while_it_cannot_be_targeted(set_pool):
    """The card's own shape, and it is legal: CR 702.18 stops spells and
    abilities from choosing the permanent, and says nothing about what the
    permanent's own ability may choose."""
    card = set_pool("HML")["Autumn Willow"]
    program = compile_card_oracle(card)

    assert program.supported, program.reason
    assert "shroud" in program.static_lines
    [ability] = program.activated_abilities
    assert derive_activation_spec(ability) == {"kind": "player"}


# Dwarven Sea Clan -----------------------------------------------------------


def test_dwarven_sea_clan_shoots_the_creature_it_named_at_end_of_combat(set_pool):
    """"{T}: Choose target attacking or blocking creature whose controller
    controls an Island. This creature deals 2 damage to that creature at end of
    combat."

    The delay is printed after its effect and the victim is the object the
    activation bound (CR 603.7c) — so nothing happens when the ability
    resolves, and the damage lands when combat ends.
    """
    lea = set_pool("LEA")
    clan = _w2g3_ready(Permanent(card=set_pool("HML")["Dwarven Sea Clan"]))
    sailor = _w2g3_ready(Permanent(card=lea["Grizzly Bears"]))
    game = _w2g3_game([clan], [Permanent(card=lea["Island"]), sailor],
                      set_pool=set_pool)
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(1, [1], defending_player_index=0)[0]

    result = game.activate_permanent_ability(
        0, "Dwarven Sea Clan", target_player_index=1, target_permanent_index=1
    )
    game._settle()
    assert result.supported, result.details
    assert sailor.damage_marked == 0, "the damage waits for the end of combat"

    game.advance_combat_phase()   # declare blockers
    game.advance_combat_phase()   # combat damage
    game.advance_combat_phase()   # end of combat
    game._settle()

    assert sailor.damage_marked == 2, game.log


def test_dwarven_sea_clan_offers_only_islanders(set_pool):
    """"…whose controller controls an Island" is a question about the
    *candidate's* seat, not the activator's — and the picker asks it, so the
    engine and the browser agree on what is a legal target."""
    lea = set_pool("LEA")
    clan = _w2g3_ready(Permanent(card=set_pool("HML")["Dwarven Sea Clan"]))
    program = compile_card_oracle(clan.card)
    [ability] = program.activated_abilities
    spec = derive_activation_spec(ability)

    offered = []
    for land in ("Island", "Forest"):
        attacker = _w2g3_ready(Permanent(card=lea["Grizzly Bears"]))
        game = _w2g3_game([clan], [Permanent(card=lea[land]), attacker],
                          set_pool=set_pool)
        game.start_turn(1)
        game._close_current_priority_step()
        game.advance_combat_phase()
        game.advance_combat_phase()
        game.declare_attackers(1, [1], defending_player_index=0)
        offered.append(len(game._enumerate_targets(
            0, clan.card, spec, for_cast=False,
            ability_instruction=ability.instruction,
            ability_source=clan, source_permanent=clan,
        )))

    assert offered == [1, 0]


def test_dwarven_sea_clan_closes_at_the_end_of_combat_step(set_pool):
    """"Activate only before the end of combat step." The window closes when
    that step begins and stays shut — the postcombat main phase is not during
    the step either, and reading the clause as "not that step" would let the
    ability be activated after the moment its damage was going to be dealt."""
    clan = _w2g3_ready(Permanent(card=set_pool("HML")["Dwarven Sea Clan"]))
    game = _w2g3_game([clan], [], set_pool=set_pool)
    game.start_turn(0)
    line = clan.card.oracle_text.splitlines()[0]

    open_steps, shut_steps = [], []
    for phase, step in (
        ("beginning", "upkeep"), ("precombat_main", "precombat_main"),
        ("combat", "declare_attackers"), ("combat", "combat_damage"),
        ("combat", "end_of_combat"), ("postcombat_main", "postcombat_main"),
        ("ending", "end"),
    ):
        game.current_turn_phase, game.current_step = phase, step
        target = open_steps if activation_denial(game, 0, clan, line) is None else shut_steps
        target.append(step)

    assert open_steps == ["upkeep", "precombat_main", "declare_attackers",
                          "combat_damage"]
    assert shut_steps == ["end_of_combat", "postcombat_main", "end"]
