"""Stronghold enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""



# --- W1G2: combat restrictions and requirements ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _g2e_creature(name, power, toughness, subtype="Test", keywords=()):
    text = "\n".join(word.capitalize() for word in keywords)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=f"Creature - {subtype}",
        oracle_text=text, colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": f"Creature - {subtype}",
             "power": str(power), "toughness": str(toughness)},
    )


def _g2e_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g2e_combat(mine, theirs) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def test_rolling_stones_lifts_defender_for_walls_and_nothing_else(set_pool):
    """"Wall creatures can attack as though they didn't have defender."

    CR 609.4: the permission applies to the stated effect only, so the Wall
    still *has* defender for everything that counts them - and the noun phrase
    is payload, so the non-Wall defender beside it is untouched. Both halves are
    the assertion; a reading that removed the keyword or that ignored the noun
    would pass one of them and fail the other.
    """
    stones = Permanent(card=set_pool("STH")["Rolling Stones"])
    program = compile_card_oracle(stones.card)
    assert program.supported, program.reason

    wall = _g2e_nosick(Permanent(
        card=_g2e_creature("Stone Wall", 0, 4, "Wall", ("defender",))
    ))
    keeper = _g2e_nosick(Permanent(
        card=_g2e_creature("Gate Keeper", 0, 4, "Soldier", ("defender",))
    ))
    game = _g2e_combat([wall, keeper], [])
    assert not game.can_attack(wall, 1)
    assert not game.can_attack(keeper, 1)

    game.players[0].battlefield.append(stones)
    assert game.can_attack(wall, 1)
    assert not game.can_attack(keeper, 1), (
        "the sentence names Walls; a dropped noun phrase would free every "
        "creature with defender"
    )
    assert game._has_keyword(wall, "defender"), (
        "CR 609.4: the permission is not a keyword removal"
    )


def test_invasion_plans_compels_every_block_and_moves_the_choice(set_pool):
    """Both printed lines, because a card is supported when *any* of them is.

    "All creatures block each combat if able" is CR 509.1c over a described set,
    found by a board scan because the sentence is printed on an enchantment
    nobody is blocking with. "The attacking player chooses how each creature
    blocks each combat" is CR 509.1a's chooser, substituted by a static rather
    than by Melee's one-shot - so the seat is derived at the declaration and
    stops being derived when the enchantment leaves.
    """
    plans = Permanent(card=set_pool("STH")["Invasion Plans"])
    program = compile_card_oracle(plans.card)
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == [
        "creatures_must_block", "attacker_chooses_blocks",
    ]

    attacker = _g2e_nosick(Permanent(card=_g2e_creature("Raider", 2, 2)))
    blocker = _g2e_nosick(Permanent(card=_g2e_creature("Guard", 2, 2)))
    game = _g2e_combat([attacker, plans], [blocker])
    assert game.block_chooser_index(1) == 0, (
        "the attacking player is the active player (CR 506.2)"
    )
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    # The defender may no longer submit their own declaration: CR 509.1a's
    # choices are seat 0's while the enchantment is out.
    refused, whose = game.declare_blockers(1, {0: 0})
    assert not refused and "P1 chooses" in whose, whose

    ok, message = game.declare_blockers(1, {}, acting_index=0)
    assert not ok and "blocks each combat if able" in message, message
    assert game.declare_blockers(1, {0: 0}, acting_index=0)[0]


def test_invasion_plans_stops_choosing_when_it_leaves(set_pool):
    """The substitution is derived, not stored.

    Melee writes a seat onto the game and the combat reset clears it; this is a
    static, so the only thing that ends it is the enchantment leaving - and a
    board scan is what makes that automatic rather than something a zone-change
    path has to remember.
    """
    plans = Permanent(card=set_pool("STH")["Invasion Plans"])
    attacker = _g2e_nosick(Permanent(card=_g2e_creature("Raider", 2, 2)))
    blocker = _g2e_nosick(Permanent(card=_g2e_creature("Guard", 2, 2)))
    game = _g2e_combat([attacker, plans], [blocker])
    assert game.block_chooser_index(1) == 0

    game.remove_from_battlefield(plans)
    assert game.block_chooser_index(1) == 1, (
        "with the enchantment gone the defending player chooses again"
    )


# --- W1G3: combat triggers, delayed effects and retargeting ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g3_creature(name, power, toughness) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_block(attackers, defenders, *, blocks, watchers=()):
    """Seat 0 attacks with *attackers*; seat 1 blocks per *blocks*.

    *watchers* are permanents put on seat 0's battlefield before combat — the
    board-wide enchantments these tests are about, which are in no combat at all.

    ``blocks`` is keyed by position in *attackers* / *defenders*; the watchers
    sitting in front of the attackers on the battlefield are offset here so no
    test has to count them.
    """
    game = Game(players=[
        PlayerState(name="P1", battlefield=[*watchers, *attackers]),
        PlayerState(name="P2", battlefield=list(defenders)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for perm in (*watchers, *attackers, *defenders):
        perm.summoning_sick = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(
        0, [len(watchers) + i for i in range(len(attackers))]
    )[0]
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {b: a + len(watchers) for b, a in blocks.items()}
    )[0]
    game.resolve_stack()
    return game


def test_heat_of_battle_burns_each_blocking_creatures_controller(set_pool):
    """"Whenever a creature blocks, this enchantment deals 1 damage to that
    creature's controller."

    A board-wide watcher on a third permanent: it is neither combatant, so the
    seat is the one the declare-blockers announcement froze rather than anything
    read off the source. Two blockers, two triggers, two damage.
    """
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attackers = [Permanent(card=_w1g3_creature(f"Bear {i}", 2, 2)) for i in range(2)]
    blockers = [Permanent(card=_w1g3_creature(f"Wall {i}", 0, 4)) for i in range(2)]
    game = _w1g3_block(attackers, blockers, blocks={0: 0, 1: 1}, watchers=[heat])

    assert game.players[1].life == 18, game.log
    assert game.players[0].life == 20, game.log


def test_heat_of_battle_fires_once_per_blocker_not_once_per_attacker(set_pool):
    """CR 509.3c: a condition with no partner phrase fires once for the creature
    the event is about, however many creatures are on the other side.

    One blocker against one attacker is one trigger — the per-pair announcement
    the narrowed spellings answer to would be the same number here, so the test
    that separates them is the multi-block one below.
    """
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attacker = Permanent(card=_w1g3_creature("Bear", 2, 2))
    blocker = Permanent(card=_w1g3_creature("Wall", 0, 4))
    game = _w1g3_block([attacker], [blocker], blocks={0: 0}, watchers=[heat])

    assert game.players[1].life == 19, game.log


def test_heat_of_battle_fires_once_for_each_of_two_creatures_blocking_one(set_pool):
    """CR 509.3d against CR 509.3c, on the one board that tells them apart.

    Two creatures block a single attacker. "Whenever a creature blocks" is about
    each *blocker*, so it fires twice; the per-pair announcement the narrowed
    spellings (No Quarter) answer to would fire twice here as well — what would
    fire twice *wrongly* is the becomes-blocked side, which is one creature
    becoming blocked and is announced once. Both readings share one fire site,
    so this is the board that would show the pair announcement leaking into the
    bare condition.
    """
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attacker = Permanent(card=_w1g3_creature("Bear", 2, 2))
    blockers = [Permanent(card=_w1g3_creature(f"Wall {i}", 0, 4)) for i in range(2)]
    game = _w1g3_block([attacker], blockers, blocks={0: 0, 1: 0}, watchers=[heat])

    assert game.players[1].life == 18, game.log


def test_heat_of_battle_says_nothing_about_an_unblocked_attack(set_pool):
    """The condition is about blocking, not about combat: an attack nobody
    blocks announces no firing at all."""
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attacker = Permanent(card=_w1g3_creature("Bear", 2, 2))
    game = _w1g3_block([attacker], [], blocks={}, watchers=[heat])

    assert game.players[1].life == 20, game.log


# --- W1G5: player-action triggers and replacements ---
#
# Four enchantments whose *event* is something a player does — a discard, an
# upkeep, a land put into a graveyard by somebody's spell, a draw — rather than
# something a permanent does. Every one of them is driven through a real game
# rather than read off the compiled program: a trigger condition can be in both
# front ends' tables and still have nothing that announces it, which is a shape
# no instrument in this repo can see.

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle

_G5_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g5_game(*players: PlayerState) -> Game:
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    return game


def test_megrim_damages_the_opponent_who_discarded(set_pool):
    """"Whenever an opponent discards a card, this enchantment deals 2 damage
    to **that player**."

    Two halves, and both were holes. The discard condition existed for the word
    "you" alone — its kind was named `you_discard_card`, after one of its own
    narrowings — so the board walk skipped every permanent whose controller had
    not discarded. And "that player" needs a seat the *event* froze: the discard
    seam records it now, because by resolution nothing on a board says who
    discarded.
    """
    program = compile_card_oracle(set_pool("STH")["Megrim"])
    assert program.supported, program.reason

    megrim = Permanent(card=set_pool("STH")["Megrim"])
    game = _g5_game(
        PlayerState(name="P1", battlefield=[megrim], life=20),
        PlayerState(name="P2", hand=[_G5_LEA["Island"]], life=20),
    )
    game.start_turn(0)
    game._discard_card(game.players[1], game.players[1].hand.pop(0))
    game.resolve_stack()

    assert game.players[1].life == 18, game.log
    assert game.players[0].life == 20, game.log


def test_megrim_ignores_its_own_controllers_discard(set_pool):
    """The narrowing, from the side that fires too often. "An opponent" is any
    seat but the ability's controller (CR 109.5), and the unnarrowed reading
    would have Megrim burn its own player."""
    megrim = Permanent(card=set_pool("STH")["Megrim"])
    game = _g5_game(
        PlayerState(name="P1", battlefield=[megrim],
                    hand=[_G5_LEA["Island"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    game._discard_card(game.players[0], game.players[0].hand.pop(0))
    game.resolve_stack()

    assert game.players[0].life == 20, game.log
    assert game.players[1].life == 20, game.log


def test_bottomless_pit_empties_the_hand_of_whoevers_upkeep_it_is(set_pool):
    """"At the beginning of each player's upkeep, **that player** discards a
    card at random."

    The seat varies every upkeep and nothing on a board records it, so the
    discard reads the one the firing event froze. Read as the resolving player
    instead, this enchantment would take a card out of its own controller's hand
    on three upkeeps in four — and silently, because either way exactly one card
    leaves exactly one hand.
    """
    program = compile_card_oracle(set_pool("STH")["Bottomless Pit"])
    assert program.supported, program.reason

    pit = Permanent(card=set_pool("STH")["Bottomless Pit"])
    game = _g5_game(
        PlayerState(name="P1", battlefield=[pit],
                    hand=[_G5_LEA["Forest"], _G5_LEA["Mountain"]], life=20),
        PlayerState(name="P2",
                    hand=[_G5_LEA["Island"], _G5_LEA["Swamp"]], life=20),
    )
    game.start_turn(0)
    game.resolve_stack()
    assert (len(game.players[0].hand), len(game.players[1].hand)) == (1, 2), game.log

    game.start_next_turn()
    game.resolve_stack()
    assert (len(game.players[0].hand), len(game.players[1].hand)) == (1, 1), game.log


def test_sacred_ground_returns_a_land_an_opponents_spell_destroyed(set_pool):
    """"Whenever a spell or ability an opponent controls causes a land to be put
    into your graveyard from the battlefield, return that card to the
    battlefield."

    The condition is about the *cause*, which nothing on a board records once
    the death has happened.
    """
    program = compile_card_oracle(set_pool("STH")["Sacred Ground"])
    assert program.supported, program.reason

    game = _g5_game(
        PlayerState(name="P1",
                    battlefield=[Permanent(card=set_pool("STH")["Sacred Ground"])],
                    hand=[_G5_LEA["Forest"]], life=20),
        PlayerState(name="P2", hand=[_G5_LEA["Stone Rain"]], life=20),
    )
    game.start_turn(0)
    game.cast_from_hand(0, "Forest")
    game.resolve_stack()
    game.start_next_turn()
    game.cast_from_hand(1, "Stone Rain", target_player_index=0, target_permanent_index=1)
    game.resolve_stack()

    assert [p.card.name for p in game.players[0].battlefield] == [
        "Sacred Ground", "Forest",
    ], game.log
    assert not game.players[0].graveyard, game.log


def test_sacred_ground_ignores_a_land_its_own_controller_destroyed(set_pool):
    """The other side of the same narrowing, and the reason it is a payload key
    rather than a wider reading of the death: a land its controller's own spell
    kills stays dead."""
    game = _g5_game(
        PlayerState(name="P1",
                    battlefield=[Permanent(card=set_pool("STH")["Sacred Ground"])],
                    hand=[_G5_LEA["Forest"], _G5_LEA["Stone Rain"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    game.cast_from_hand(0, "Forest")
    game.resolve_stack()
    game.cast_from_hand(0, "Stone Rain", target_player_index=0, target_permanent_index=1)
    game.resolve_stack()

    assert [p.card.name for p in game.players[0].battlefield] == ["Sacred Ground"], game.log
    assert "Forest" in [c.name for c in game.players[0].graveyard], game.log


def test_sacred_ground_ignores_a_land_no_spell_killed(set_pool):
    """And a land that simply left, with nothing resolving. An empty stack means
    no spell or ability caused the move at all — a state-based action, a cost, a
    turn-based effect — which is exactly when this trigger must not fire."""
    game = _g5_game(
        PlayerState(name="P1",
                    battlefield=[Permanent(card=set_pool("STH")["Sacred Ground"])],
                    hand=[_G5_LEA["Forest"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    game.cast_from_hand(0, "Forest")
    game.resolve_stack()
    forest = game.players[0].battlefield[-1]
    game.remove_from_battlefield(forest)
    game._permanent_to_graveyard(game.players[0], forest)
    game.resolve_stack()

    assert [p.card.name for p in game.players[0].battlefield] == ["Sacred Ground"], game.log
    assert [c.name for c in game.players[0].graveyard] == ["Forest"], game.log


def test_overgrowth_adds_both_of_the_mana_it_prints(set_pool):
    """"Whenever enchanted land is tapped for mana, its controller adds an
    additional **{G}{G}**."

    Wild Growth's template with the symbol doubled, and the pattern behind it
    read exactly one symbol — so the count is data now. The failure this guards
    is the quiet one: half the mana the card prints, with the Aura reporting
    supported.
    """
    program = compile_card_oracle(set_pool("STH")["Overgrowth"])
    assert program.supported, program.reason

    forest = Permanent(card=_G5_LEA["Forest"])
    game = _g5_game(
        PlayerState(name="P1", battlefield=[forest], life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    overgrowth = Permanent(card=set_pool("STH")["Overgrowth"])
    game.players[0].battlefield.append(overgrowth)
    attach_aura(overgrowth, forest)

    assert game.tap_land_for_mana(0, "Forest"), game.log
    # The land's own {G} plus the two the Aura adds.
    assert game.players[0].mana_pool["G"] == 3, game.log


def test_pursuit_of_knowledge_trades_a_draw_for_a_counter_and_back(set_pool):
    """"If you would draw a card, you may put a study counter on this
    enchantment instead." / "Remove three study counters …, Sacrifice …: Draw
    seven cards."

    The whole card in one game: three draws replaced, then the counters spent.
    """
    program = compile_card_oracle(set_pool("STH")["Pursuit of Knowledge"])
    assert program.supported, program.reason

    pursuit = Permanent(card=set_pool("STH")["Pursuit of Knowledge"])
    game = _g5_game(
        PlayerState(name="P1", battlefield=[pursuit],
                    library=[_G5_LEA["Forest"]] * 30, life=20),
        PlayerState(name="P2", library=[_G5_LEA["Island"]] * 30, life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.resolve_stack()
    for _ in range(3):
        game.start_next_turn()          # P2
        game.start_next_turn()          # P1's draw step
        game.resolve_stack()
        assert game.pending_draw_becomes_counters, game.log
        assert game.confirm_draw_becomes_counter(0, take_the_counter=True)

    assert counters_on(pursuit, "study") == 3, game.log
    assert not game.players[0].hand, game.log

    result = game.activate_permanent_ability(0, "Pursuit of Knowledge")
    game.resolve_stack()
    assert result.supported, result
    assert len(game.players[0].hand) == 7, game.log
    assert [c.name for c in game.players[0].graveyard] == ["Pursuit of Knowledge"]


def test_pursuit_of_knowledge_declined_still_draws_the_card(set_pool):
    """The declining answer. It replaces the event as far as the interceptor is
    concerned — the draw it leaves is remade through the seam with this source
    excluded (CR 614.5) — so a card that quietly drew nothing would look
    identical to one that worked."""
    pursuit = Permanent(card=set_pool("STH")["Pursuit of Knowledge"])
    game = _g5_game(
        PlayerState(name="P1", battlefield=[pursuit],
                    library=[_G5_LEA["Forest"]] * 30, life=20),
        PlayerState(name="P2", library=[_G5_LEA["Island"]] * 30, life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.start_next_turn()
    game.start_next_turn()
    game.resolve_stack()

    assert game.pending_draw_becomes_counters, game.log
    assert game.confirm_draw_becomes_counter(0, take_the_counter=False)
    assert len(game.players[0].hand) == 1, game.log
    assert counters_on(pursuit, "study") == 0, game.log


def test_pursuit_of_knowledge_keeps_a_headless_seat_drawing(set_pool):
    """The default a non-interactive seat takes. A seat that accepted every
    offer would never draw another card, in exchange for counters no AI policy
    spends — so the default is the draw, and this is what says so."""
    pursuit = Permanent(card=set_pool("STH")["Pursuit of Knowledge"])
    game = _g5_game(
        PlayerState(name="P1", battlefield=[pursuit],
                    library=[_G5_LEA["Forest"]] * 30, life=20),
        PlayerState(name="P2", library=[_G5_LEA["Island"]] * 30, life=20),
    )
    game.start_turn(0)
    game.start_next_turn()
    game.start_next_turn()
    game.resolve_stack()

    assert len(game.players[0].hand) == 1, game.log
    assert counters_on(pursuit, "study") == 0, game.log
    assert not game.pending_draw_becomes_counters, game.log


# --- W1G1: damage prevention, redirection and damage-event triggers ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


def _w1g1_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g1_bolt(name="Bolt Test", type_line="Instant"):
    return CardDefinition(
        name=name, mana_cost="{R}", cmc=1.0, type_line=type_line,
        oracle_text=f"{name} deals 3 damage to any target.",
        colors=("R",), color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


def _w1g1_retreat_board(set_pool):
    game = _w1g1_duel()
    p1, p2 = game.players
    retreat = _nosick(Permanent(card=set_pool("STH")["Hidden Retreat"]))
    p1.battlefield.append(retreat)
    p1.hand.append(_w1g1_bolt("Spare Card"))
    return game, p1, p2, retreat


def test_hidden_retreat_pays_by_putting_a_card_back_on_top(set_pool):
    """"Put a card from your hand on top of your library: …"

    CR 118.1 makes the payment the printed action, and the printed action is
    what the ability is *for*: the card is still in the library and will be
    drawn again, which is why this is not a discard wearing another name. So the
    test asserts both ends of the move — the hand one shorter, and that exact
    card on top rather than in a graveyard.
    """
    game, p1, p2, _retreat = _w1g1_retreat_board(set_pool)
    p2.hand.append(_w1g1_bolt())
    game.queue_from_hand(1, "Bolt Test", target_player_index=0)
    paid = p1.hand[0]

    result = game.activate_permanent_ability(
        0, "Hidden Retreat", permanent_index=0, target_stack_index=0,
    )

    assert result.supported
    assert p1.hand == []
    assert p1.library[0] is paid
    assert paid not in p1.graveyard


def test_hidden_retreat_cannot_be_activated_with_an_empty_hand(set_pool):
    """CR 118.3: a player cannot pay a cost without the resources to pay it, and
    CR 602.5c then makes the ability unactivatable rather than free.

    The half that is only done when something enforces it — an unenforced cost
    is not a dead ability, it is an ability that works more often than the card
    allows, and this one would then be a free blanket every turn.
    """
    game, p1, p2, _retreat = _w1g1_retreat_board(set_pool)
    p1.hand.clear()
    p2.hand.append(_w1g1_bolt())
    game.queue_from_hand(1, "Bolt Test", target_player_index=0)

    result = game.activate_permanent_ability(
        0, "Hidden Retreat", permanent_index=0, target_stack_index=0,
    )

    assert not result.supported


def test_hidden_retreat_stops_the_spell_it_named_and_no_other(set_pool):
    """"Prevent all damage that would be dealt by target instant or sorcery
    spell this turn."

    The shield hangs off the **stack item**, not off a recipient and not off the
    printed card, so the assertions are the two things that distinguishes:
    the named spell's damage is gone, and a *second copy of the same card* —
    which shares one ``CardDefinition`` (CR 109.5) — still deals its three.
    """
    game, p1, p2, _retreat = _w1g1_retreat_board(set_pool)
    bolt = _w1g1_bolt()
    p2.hand.extend([bolt, bolt])
    life = p1.life

    game.queue_from_hand(1, "Bolt Test", target_player_index=0)
    assert game.activate_permanent_ability(
        0, "Hidden Retreat", permanent_index=0, target_stack_index=0,
    ).supported
    resolve_stack(game)

    assert p1.life == life, "the spell it named dealt nothing"

    game.cast_from_hand(1, "Bolt Test", target_player_index=0)
    resolve_stack(game)

    assert p1.life == life - 3, "a second cast of the same card is a second spell"


# --- W1G4: library, graveyard and unusual costs ---

import pytest

from engine import Game, PlayerState
from engine.alternative_costs import (granted_alternative_cost,
                                      granted_alternative_cost_claims_line)
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g4_halls(hand: list, halls) -> tuple[Game, PlayerState, PlayerState]:
    """A board with Dream Halls out and **mana enforcement on**: the whole
    point of the card is casting a spell for no mana at all, so a game that
    charged nothing would prove nothing."""
    caster, victim = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[caster, victim])
    game.active_player_index = 0
    game.enforce_mana_costs = True
    caster.battlefield.append(Permanent(card=halls))
    return game, caster, victim


@pytest.mark.cr("118.9", "118.9a")
def test_g4_dream_halls_grants_an_alternative_cost_to_every_spell(set_pool):
    """"Rather than pay the mana cost for a spell, its controller may discard a
    card that shares a color with that spell."

    CR 118.9's alternative cost from a **board** rather than printed on the
    spell — which is what nothing read: ``alternative_costs`` was card-scoped,
    so the sentence was claimed by nobody and the enchantment reported
    unsupported. The relationship is ``cost_modifiers``' to ``cast_costs``, one
    rule over.
    """
    halls = set_pool("STH")["Dream Halls"]
    assert compile_card_oracle(halls).supported
    assert granted_alternative_cost_claims_line(halls.oracle_text)

    cost = granted_alternative_cost(halls.oracle_text)
    assert cost is not None
    assert cost.discard_from_hand == (), "any card, narrowed by the relation"
    assert cost.shares_color_with_spell is True
    assert cost.exile_from_hand is None, "a discard is not an exile"


@pytest.mark.cr("118.9", "701.9a")
def test_g4_dream_halls_casts_a_blue_spell_for_a_blue_card(set_pool):
    """The mana payment is replaced, not reduced: the pool is empty and the
    spell resolves. The card paying goes through the discard seam, so it lands
    in the graveyard as a discard rather than as a bare move."""
    game, caster, _ = _g4_halls(
        [_G4_LEA["Ancestral Recall"], _G4_LEA["Counterspell"],
         _G4_LEA["Lightning Bolt"]],
        set_pool("STH")["Dream Halls"],
    )

    offers = game.cast_cost_offers(
        0, _G4_LEA["Ancestral Recall"], spell_hand_index=0,
    )
    assert len(offers) == 1 and offers[0]["kind"] == "alternative"
    assert offers[0]["payable"] is True
    assert [c["name"] for c in offers[0]["hand_choices"]] == ["Counterspell"], (
        "only the colour-sharing card is offered"
    )

    result = game.cast_from_hand(
        0, "Ancestral Recall", target_player_index=0,
        alternative_cost=True, alternative_cost_hand_index=1,
    )

    assert result.supported, result.details
    assert sum(caster.mana_pool.values()) == 0, "nothing was spent"
    assert [c.name for c in caster.hand] == ["Lightning Bolt"]
    assert "Counterspell" in [c.name for c in caster.graveyard]


@pytest.mark.cr("118.9", "105.2")
def test_g4_dream_halls_needs_a_shared_color(set_pool):
    """The relation is between the card paying and the spell being cast, so a
    red card cannot buy a blue spell — and a **colourless** spell shares a
    colour with nothing, which is why the offer is an intersection rather than
    a default of "no restriction"."""
    halls = set_pool("STH")["Dream Halls"]

    game, _caster, _ = _g4_halls(
        [_G4_LEA["Ancestral Recall"], _G4_LEA["Lightning Bolt"]], halls,
    )
    named = game.cast_from_hand(
        0, "Ancestral Recall", target_player_index=0,
        alternative_cost=True, alternative_cost_hand_index=1,
    )
    assert not named.supported, "a red card is not a blue card"

    game, _caster, _ = _g4_halls(
        [_G4_LEA["Ancestral Recall"], _G4_LEA["Lightning Bolt"]], halls,
    )
    unpayable = game.cast_from_hand(
        0, "Ancestral Recall", target_player_index=0, alternative_cost=True,
    )
    assert not unpayable.supported
    assert "CR 601.2h" in unpayable.details

    game, _caster, _ = _g4_halls(
        [_G4_LEA["Black Lotus"], _G4_LEA["Lightning Bolt"]], halls,
    )
    assert not game.cast_from_hand(
        0, "Black Lotus", alternative_cost=True,
    ).supported, "a colourless spell shares a colour with nothing"


@pytest.mark.cr("118.9b")
def test_g4_without_dream_halls_no_spell_carries_the_offer(set_pool):
    """The grant is a board read, so it is gone the moment the enchantment is.
    Asserted because the cost is now gathered from two places, and a source
    that leaked into every cast would be the loudest possible mis-play."""
    caster, victim = (
        PlayerState(name="A", hand=[_G4_LEA["Ancestral Recall"],
                                    _G4_LEA["Counterspell"]]),
        PlayerState(name="B"),
    )
    game = Game(players=[caster, victim])
    game.enforce_mana_costs = True

    assert game.cast_cost_offers(
        0, _G4_LEA["Ancestral Recall"], spell_hand_index=0,
    ) == []
    assert not game.cast_from_hand(
        0, "Ancestral Recall", target_player_index=0, alternative_cost=True,
    ).supported


@pytest.mark.cr("118.9b")
def test_g4_an_ai_seat_sees_the_granted_cost_too(set_pool):
    """The AI's affordability question asks the engine's own gate rather than
    re-deriving one — so it has to ask the *same* reader. A policy that saw
    only the printed half would sit on a castable spell all game, which is the
    shape ``_alternative_cost_is_payable`` was written for."""
    from engine.ai_policy import _alternative_cost_is_payable

    game, _caster, _ = _g4_halls(
        [_G4_LEA["Ancestral Recall"], _G4_LEA["Counterspell"]],
        set_pool("STH")["Dream Halls"],
    )
    assert _alternative_cost_is_payable(
        game, 0, _G4_LEA["Ancestral Recall"], 0,
    )

    game, _caster, _ = _g4_halls(
        [_G4_LEA["Ancestral Recall"], _G4_LEA["Lightning Bolt"]],
        set_pool("STH")["Dream Halls"],
    )
    assert not _alternative_cost_is_payable(
        game, 0, _G4_LEA["Ancestral Recall"], 0,
    ), "no colour-sharing card is no payable offer"


# --- W2G1: Contempt ---
"""Contempt — "When enchanted creature attacks, return it and this Aura to
their owners' hands at end of combat."

Three things had to be true at once and none of them was: the trigger condition
had to exist on **both** front ends (only one of them dispatches), the
declare-attackers fire site had to scan the attacker's attachments for the bare
"attacks" event as well as the joined one, and the delayed ability had to bind
the Aura's *host* — no fire site stamps it and an attached trigger's stack item
has no target, so every other binding in `create_delayed_trigger` would have
armed an entry about nothing while the card compiled clean.
"""
import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.grammar import GrammarError, parse_line
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g1_creature(name, power=2, toughness=2) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g1_attack_with_contempt(set_pool, *, aura_seat=1, extra_attackers=()):
    """Seat 0 attacks with a creature enchanted by *aura_seat*'s Contempt.

    Returns ``(game, aura, attacker)`` at the declare-attackers step with the
    trigger already resolved, which is where the delayed ability is armed.
    """
    aura = Permanent(card=set_pool("STH")["Contempt"])
    attacker = Permanent(card=_w2g1_creature("Charging Bull", 3, 3))
    others = [Permanent(card=_w2g1_creature(name)) for name in extra_attackers]
    seats = [
        PlayerState(name="P0", battlefield=[attacker, *others]),
        PlayerState(name="P1", battlefield=[]),
    ]
    seats[aura_seat].battlefield.append(aura)
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for perm in (attacker, *others):
        perm.summoning_sick = False
    attach_aura(aura, attacker)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    assert game.declare_attackers(0, list(range(1 + len(others))))[0]
    game.resolve_stack()
    return game, aura, attacker


def _w2g1_run_out_combat(game):
    """Every remaining combat step, resolving what each one puts on the stack."""
    for _ in range(4):
        game.advance_combat_phase()
        game.resolve_stack()


def test_contempt_compiles_to_a_delay_that_binds_the_attachments_host(set_pool):
    """The whole card is one trigger, and every field of it is load-bearing.

    ``binds_attached_host`` rather than ``binds_target``: the ability is the
    Aura's own (CR 603.3a), and the fire site pushes its stack item with no
    target at all — so the target reading would arm an entry about nothing.
    """
    program = compile_card_oracle(set_pool("STH")["Contempt"])
    assert program.supported

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "creature_attacks"
    assert trigger.condition.payload["combatant_attached"] == "creature"

    delay = trigger.instruction
    assert delay.kind == "create_delayed_trigger"
    assert delay.payload["event"] == "next_end_of_combat"
    assert delay.payload["binds_attached_host"] is True
    assert delay.payload["binds_target"] is False
    assert [
        step.kind for step in delay.payload["instruction"].payload["steps"]
    ] == ["return_bound_permanent_to_hand", "return_source_card_to_owners_hand"]


@pytest.mark.parametrize("aura_seat", [0, 1])
def test_contempt_returns_both_the_creature_and_itself_at_end_of_combat(
    set_pool, aura_seat
):
    """The card's whole point: the Aura goes to a **hand**, not to a graveyard.

    Run from either seat, because CR 400.3 sends each object to its own owner
    and an Aura the attacker's opponent controls is the way the card is played.
    """
    game, aura, attacker = _w2g1_attack_with_contempt(
        set_pool, aura_seat=aura_seat
    )
    assert "Charging Bull" in [p.card.name for p in game.players[0].battlefield]

    _w2g1_run_out_combat(game)

    assert [p.card.name for p in game.players[0].battlefield] == [], game.log
    assert "Charging Bull" in [c.name for c in game.players[0].hand], game.log
    assert [
        p.card.name for p in game.players[aura_seat].battlefield
    ] == [], game.log
    assert "Contempt" in [
        c.name for c in game.players[aura_seat].hand
    ], game.log
    assert [c.name for c in game.players[aura_seat].graveyard] == [], (
        "the Aura returns to hand; it does not die to CR 704.5m"
    )
    assert [c.name for c in game.players[0].graveyard] == [], game.log


def test_contempt_binds_the_creature_it_enchanted_and_not_another_attacker(
    set_pool
):
    """The negative case. The delay names one permanent by id (CR 603.7c), so a
    second creature in the same declaration is untouched — the failure a
    reading that swept the attackers would produce."""
    game, aura, attacker = _w2g1_attack_with_contempt(
        set_pool, extra_attackers=("Bystander",)
    )
    (entry,) = game.delayed_triggers
    assert entry.bound_permanent_id == attacker.permanent_id, game.log
    assert entry.bound_permanent_id != aura.permanent_id

    _w2g1_run_out_combat(game)
    assert [
        p.card.name for p in game.players[0].battlefield
    ] == ["Bystander"], game.log


def test_contempt_still_returns_the_creature_when_the_aura_is_gone(set_pool):
    """CR 603.7c: the delayed ability is about the creature the Aura was on when
    it was *created*, so destroying the Aura in between does not save it.

    This is what makes the binding a resolution-time id rather than a read of
    the attachment at end of combat — the reading that would have found no host
    and quietly done nothing.
    """
    game, aura, attacker = _w2g1_attack_with_contempt(set_pool)
    game.remove_from_battlefield(aura)
    game.players[1].graveyard.append(aura.card)

    _w2g1_run_out_combat(game)
    assert [c.name for c in game.players[0].hand] == ["Charging Bull"], game.log
    assert [c.name for c in game.players[1].graveyard] == ["Contempt"], game.log


def test_contempt_does_not_fire_when_the_enchanted_creature_stays_home(set_pool):
    """"When enchanted creature **attacks**" — CR 508.1's declaration, not the
    combat phase. A creature that never attacked arms nothing."""
    aura = Permanent(card=set_pool("STH")["Contempt"])
    homebody = Permanent(card=_w2g1_creature("Homebody"))
    attacker = Permanent(card=_w2g1_creature("Charging Bull", 3, 3))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[attacker, homebody]),
        PlayerState(name="P1", battlefield=[aura]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for perm in (attacker, homebody):
        perm.summoning_sick = False
    attach_aura(aura, homebody)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.resolve_stack()

    assert game.delayed_triggers == [], game.log
    _w2g1_run_out_combat(game)
    assert sorted(p.card.name for p in game.players[0].battlefield) == [
        "Charging Bull", "Homebody",
    ], game.log


def test_an_attached_attack_trigger_reads_the_same_event_on_both_front_ends():
    """Two trigger front ends and only one of them dispatches.

    A condition in `engine/oracle.py`'s table alone parses and fires nowhere; a
    production in the grammar alone compiles an instruction the fire sites never
    reach. Both are asked here, of the same printed sentence.
    """
    from engine.oracle import _parse_triggered_ability

    line = "whenever enchanted creature attacks, tap it"
    parsed = _parse_triggered_ability(line, "Test")
    assert parsed is not None and parsed.supported
    assert parsed.condition.kind == "creature_attacks"
    assert parsed.condition.payload["combatant_attached"] == "creature"

    node = parse_line("Whenever enchanted creature attacks, tap it.")
    assert node.event.kind == "creature_attacks"
    assert node.event.subject.is_enchanted


def test_the_bare_attached_attack_row_does_not_swallow_the_unblocked_one():
    """The refusal test for the ordering. "attacks" is a strict prefix of
    "attacks and isn't blocked" (Cloak of Confusion), so a bare row read first
    would leave those words unconsumed — or worse, drop them and give the card
    a trigger that fires on every attack."""
    node = parse_line(
        "Whenever enchanted creature attacks and isn't blocked, "
        "you may have it assign no combat damage this turn."
    )
    assert node.event.kind == "attacks_unblocked"


def test_a_union_ending_in_this_permanent_still_refuses_a_second_clause():
    """The union may end in the ability's own source only where the phrase ends
    the sentence, or in front of a clause the caller is about to read. A verb
    after it is a new clause and must stay one — the hazard the whole
    quantifier gate is written for."""
    with pytest.raises(GrammarError):
        parse_line(
            "Return target creature and this enchantment deals 2 damage to you."
        )
