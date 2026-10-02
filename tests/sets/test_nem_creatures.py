"""Nemesis creatures.

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

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: combat restrictions and triggers ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent

from tests.helpers import resolve_stack


def _w1g3_creature(name: str, power: int, toughness: int, *,
                   text: str = "", keywords: tuple = (),
                   type_line: str = "Creature - Test") -> CardDefinition:
    """An invented creature for the side of the table these cards fight."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=keywords,
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_table(attackers, defenders):
    """Seat 0 holds *attackers*, seat 1 holds *defenders*, turn 0 begun.

    Every entry may be a ``CardDefinition`` or a ready ``Permanent``; the
    permanents come back in the order given, so a test can name them.
    """
    mine = [a if isinstance(a, Permanent) else Permanent(card=a) for a in attackers]
    theirs = [d if isinstance(d, Permanent) else Permanent(card=d) for d in defenders]
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(mine)),
        PlayerState(name="P1", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    for permanent in (*mine, *theirs):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, mine, theirs


def _w1g3_to_blocks(game, attacking_slots):
    """Declare *attacking_slots* for seat 0 and stop at declare blockers."""
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(0, list(attacking_slots))
    assert declared[0], declared
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"


def _w1g3_finish_combat(game, *, until: str = "postcombat_main"):
    """Walk the combat steps to *until*, draining the stack at each one."""
    for _ in range(6):
        if game.current_step == until:
            return
        game.advance_combat_phase()
        resolve_stack(game)
    assert game.current_step == until, game.current_step


# --- Sneaky Homunculus -----------------------------------------------------
# "This creature can't block or be blocked by creatures with power 2 or
# greater." Two prohibitions over one noun phrase, so both halves are asked of
# the one block legality predicate the declaration and the AI both read.


def test_w1g3_sneaky_homunculus_cannot_block_a_two_power_attacker(set_pool):
    game, (big, small), (homunculus,) = _w1g3_table(
        [_w1g3_creature("Big", 2, 2), _w1g3_creature("Small", 1, 1)],
        [set_pool("NEM")["Sneaky Homunculus"]],
    )
    _w1g3_to_blocks(game, [0, 1])

    assert not game._can_block_attacker(homunculus, big)
    assert game._can_block_attacker(homunculus, small)
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused
    assert game.declare_blockers(1, {0: 1})[0]


def test_w1g3_sneaky_homunculus_cannot_be_blocked_by_a_two_power_creature(set_pool):
    game, (homunculus,), (big, small) = _w1g3_table(
        [set_pool("NEM")["Sneaky Homunculus"]],
        [_w1g3_creature("Big", 2, 2), _w1g3_creature("Small", 1, 1)],
    )
    _w1g3_to_blocks(game, [0])

    assert not game._can_block_attacker(big, homunculus)
    assert game._can_block_attacker(small, homunculus)
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused
    assert game.declare_blockers(1, {1: 0})[0]


def test_w1g3_sneaky_homunculus_reads_power_through_the_layers(set_pool):
    """A 1/1 pumped to power 2 is a creature with power 2 or greater — the
    threshold is asked of ``effective_power``, not of the printed number."""
    game, (homunculus,), (small,) = _w1g3_table(
        [set_pool("NEM")["Sneaky Homunculus"]], [_w1g3_creature("Small", 1, 1)],
    )
    _w1g3_to_blocks(game, [0])
    assert game._can_block_attacker(small, homunculus)

    small.power_bonus += 1

    assert small.effective_power == 2
    assert not game._can_block_attacker(small, homunculus)


# --- Blinding Angel --------------------------------------------------------
# "Whenever this creature deals combat damage to a player, that player skips
# their next combat phase." The seat is the one the damage event froze, and a
# skip is owed once per hit (CR 500.11, CR 614.10).


def test_w1g3_blinding_angel_skips_the_damaged_players_next_combat(set_pool):
    game, (angel,), _ = _w1g3_table([set_pool("NEM")["Blinding Angel"]], [])
    _w1g3_to_blocks(game, [0])
    game.declare_blockers(1, {})
    _w1g3_finish_combat(game)

    assert game.players[1].life == 18
    assert any("P1 will skip their next combat phase" in line for line in game.log)
    # The damaged player's next turn runs main phase to main phase …
    game.active_player_index = 1
    assert game.next_unskipped_phase_after("precombat_main") == "postcombat_main"
    # … once, and the next one has its combat back.
    assert game.next_unskipped_phase_after("precombat_main") == "combat"


def test_w1g3_blinding_angel_never_skips_its_own_controllers_combat(set_pool):
    game, _, _ = _w1g3_table([set_pool("NEM")["Blinding Angel"]], [])
    _w1g3_to_blocks(game, [0])
    game.declare_blockers(1, {})
    _w1g3_finish_combat(game)

    game.active_player_index = 0
    assert game.next_unskipped_phase_after("precombat_main") == "combat"


def test_w1g3_two_blinding_angel_hits_owe_two_skipped_combats(set_pool):
    angel = set_pool("NEM")["Blinding Angel"]
    game, _, _ = _w1g3_table([angel, angel], [])
    _w1g3_to_blocks(game, [0, 1])
    game.declare_blockers(1, {})
    _w1g3_finish_combat(game)

    game.active_player_index = 1
    assert game.next_unskipped_phase_after("precombat_main") == "postcombat_main"
    assert game.next_unskipped_phase_after("precombat_main") == "postcombat_main"
    assert game.next_unskipped_phase_after("precombat_main") == "combat"


def test_w1g3_a_blocked_blinding_angel_skips_nothing(set_pool):
    game, _, _ = _w1g3_table(
        [set_pool("NEM")["Blinding Angel"]],
        [_w1g3_creature("Bird", 1, 5, text="Flying", keywords=("Flying",))],
    )
    _w1g3_to_blocks(game, [0])
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g3_finish_combat(game)

    assert game.players[1].life == 20
    assert not game.skip_phase_counts


# --- Defiant Vanguard ------------------------------------------------------
# "When this creature blocks, at end of combat, destroy it and all creatures it
# blocked this turn." The blocked creatures are read off the record each of
# them carries, so the sweep still finds them when the Vanguard has died first.


def test_w1g3_defiant_vanguard_destroys_itself_and_what_it_blocked(set_pool):
    game, (wall, other), (vanguard,) = _w1g3_table(
        [_w1g3_creature("Plodder", 0, 4), _w1g3_creature("Other", 1, 1)],
        [set_pool("NEM")["Defiant Vanguard"]],
    )
    _w1g3_to_blocks(game, [0, 1])
    assert game.declare_blockers(1, {0: 0})[0]
    resolve_stack(game)
    _w1g3_finish_combat(game)

    assert not game.is_on_battlefield(vanguard)
    assert not game.is_on_battlefield(wall)
    assert game.is_on_battlefield(other)
    assert "Plodder" in [card.name for card in game.players[0].graveyard]


def test_w1g3_defiant_vanguard_still_destroys_what_it_blocked_after_dying(set_pool):
    """The Vanguard dies to combat damage before the end of combat it names —
    the ordinary way the card is played — and the attacker it blocked, which
    survived the fight, is destroyed all the same."""
    game, (brute, other), (vanguard,) = _w1g3_table(
        [_w1g3_creature("Brute", 3, 3), _w1g3_creature("Other", 1, 1)],
        [set_pool("NEM")["Defiant Vanguard"]],
    )
    _w1g3_to_blocks(game, [0, 1])
    assert game.declare_blockers(1, {0: 0})[0]
    resolve_stack(game)
    _w1g3_finish_combat(game, until="end_of_combat")
    assert not game.is_on_battlefield(vanguard)
    assert game.is_on_battlefield(brute)
    _w1g3_finish_combat(game)

    assert not game.is_on_battlefield(brute)
    assert game.is_on_battlefield(other)


def test_w1g3_defiant_vanguard_that_did_not_block_destroys_nothing(set_pool):
    game, (brute,), (vanguard,) = _w1g3_table(
        [_w1g3_creature("Brute", 3, 3)], [set_pool("NEM")["Defiant Vanguard"]],
    )
    _w1g3_to_blocks(game, [0])
    game.declare_blockers(1, {})
    _w1g3_finish_combat(game)

    assert game.is_on_battlefield(vanguard)
    assert game.is_on_battlefield(brute)
    assert not game.delayed_triggers


def test_w1g3_defiant_vanguard_fetches_a_small_rebel(set_pool):
    """"{5}, {T}: Search your library for a Rebel permanent card with mana
    value 4 or less, put it onto the battlefield, then shuffle." Both
    narrowings hold: the non-Rebel and the mana-value-5 Rebel stay behind."""
    nem = set_pool("NEM")
    vanguard = Permanent(card=nem["Defiant Vanguard"])
    vanguard.metadata["summoning_sickness_turn"] = -99
    big_rebel = CardDefinition(
        name="Big Rebel", mana_cost="{4}{W}", cmc=5.0,
        type_line="Creature — Human Rebel", oracle_text="", colors=("W",),
        color_identity=("W",), keywords=(), produced_mana=(),
        raw={"name": "Big Rebel", "type_line": "Creature — Human Rebel",
             "power": "5", "toughness": "5"},
    )
    game = Game(players=[
        PlayerState(
            name="P0", battlefield=[vanguard],
            library=[_w1g3_creature("Bystander", 2, 2), big_rebel,
                     nem["Defiant Falcon"]],
        ),
        PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(0, "Defiant Vanguard")
    resolve_stack(game)
    # The search is a prompt the seat answers; a seat nobody asks takes the
    # registry's default, which picks among what the printed filter admits.
    assert [choice.kind for choice in game.pending_choices] == ["search_library"]
    game.auto_resolve_pending_choices()

    assert result.supported, result.details
    assert vanguard.tapped
    on_board = [perm.card.name for perm in game.controlled_by(0)]
    assert "Defiant Falcon" in on_board
    assert "Big Rebel" not in on_board
    assert sorted(card.name for card in game.players[0].library) == [
        "Big Rebel", "Bystander",
    ]


# --- Flint Golem -----------------------------------------------------------
# "Whenever this creature becomes blocked, defending player mills three cards."
# The seat is CR 506.2's, frozen by the combat fire site.


def test_w1g3_flint_golem_mills_the_defending_player_when_blocked(set_pool):
    game, (golem,), (wall,) = _w1g3_table(
        [set_pool("NEM")["Flint Golem"]], [_w1g3_creature("Wall", 0, 4)],
    )
    game.players[0].library = [_w1g3_creature(f"Mine{i}", 1, 1) for i in range(5)]
    game.players[1].library = [_w1g3_creature(f"Theirs{i}", 1, 1) for i in range(5)]
    _w1g3_to_blocks(game, [0])
    assert game.declare_blockers(1, {0: 0})[0]
    resolve_stack(game)

    assert [card.name for card in game.players[1].graveyard] == [
        "Theirs0", "Theirs1", "Theirs2",
    ]
    assert len(game.players[0].library) == 5
    assert not game.players[0].graveyard


def test_w1g3_an_unblocked_flint_golem_mills_nobody(set_pool):
    game, _, _ = _w1g3_table([set_pool("NEM")["Flint Golem"]], [])
    game.players[1].library = [_w1g3_creature(f"Theirs{i}", 1, 1) for i in range(5)]
    _w1g3_to_blocks(game, [0])
    game.declare_blockers(1, {})
    _w1g3_finish_combat(game)

    assert len(game.players[1].library) == 5
    assert game.players[1].life == 18


# --- Laccolith Grunt (what the Rig's sentence was driven against) -----------
# "Whenever this creature becomes blocked, you may have it deal damage equal to
# its power to target creature." The target is a choice its controller makes
# (CR 603.3d), not the blocker the fire site used to stamp into it.


def test_w1g3_laccolith_grunt_may_shoot_a_creature_other_than_its_blocker(set_pool):
    game, (grunt,), (blocker, bystander) = _w1g3_table(
        [set_pool("NEM")["Laccolith Grunt"]],
        [_w1g3_creature("Blocker", 1, 1), _w1g3_creature("Bystander", 2, 2)],
    )
    game.interactive_seats = {0}
    _w1g3_to_blocks(game, [0])
    assert game.declare_blockers(1, {0: 0})[0]

    owed = game.pending_choices_of("trigger_target", 0)
    assert len(owed) == 1
    offered = {entry["permanent_id"] for entry in owed[0].data["targets"]}
    assert {blocker.permanent_id, bystander.permanent_id} <= offered
    assert game.confirm_trigger_target(0, permanent_id=bystander.permanent_id)
    resolve_stack(game)
    assert game.confirm_optional_pay(0, accept=True)
    resolve_stack(game)

    assert "Laccolith Grunt deals 2 damage to Bystander" in game.log
    assert grunt.metadata.get("assigns_no_combat_damage_until_eot")


def test_w1g3_laccolith_grunt_left_to_itself_still_shoots_its_blocker(set_pool):
    """A seat nobody asks answers with the creature the block named — the
    target the fire site used to stamp, so headless play is unchanged."""
    game, _, (blocker, _bystander) = _w1g3_table(
        [set_pool("NEM")["Laccolith Grunt"]],
        [_w1g3_creature("Blocker", 1, 1), _w1g3_creature("Bystander", 2, 2)],
    )
    _w1g3_to_blocks(game, [0])
    assert game.declare_blockers(1, {0: 0})[0]

    assert game.stack[-1].target_permanent_id == blocker.permanent_id
