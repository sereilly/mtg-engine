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
