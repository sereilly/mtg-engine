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


# --- W1G5: library, hand and graveyard ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.revealed_hands import hand_revealed_to as _w1g5_hand_revealed_to
from engine.targeting import derive_activation_spec as _w1g5_activation_spec
from tests.helpers import client as _w1g5_client
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, name, *, seat=0, **players):
    """A duel with *name* on *seat*'s battlefield, free to tap. Keyword
    arguments are the two seats' zones (``a_library=…``, ``b_hand=…``). W1G5's
    own rig."""
    a = _W1G5PlayerState(
        name="W1G5-A",
        **{k[2:]: v for k, v in players.items() if k.startswith("a_")},
    )
    b = _W1G5PlayerState(
        name="W1G5-B",
        **{k[2:]: v for k, v in players.items() if k.startswith("b_")},
    )
    game = _W1G5Game(players=[a, b])
    game.enforce_mana_costs = False
    perm = _W1G5Permanent(card=set_pool("NEM")[name])
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return game, perm, a, b


def test_w1g5_lin_sivvi_search_finds_only_a_rebel_within_x(set_pool):
    """"{X}, {T}: Search your library for a Rebel permanent card with mana
    value X or less, put it onto the battlefield, then shuffle."

    Both narrowings are asked of the live prompt rather than of the payload:
    with X paid as 2, the four-mana Rebel and the two-mana Goblin are each
    refused as answers, and only the two-mana Rebel enters. A search that
    dropped the bound would take the Poacher; one that dropped the subtype
    would take the Toady.
    """
    nem = set_pool("NEM")
    game, lin, me, _ = _w1g5_table(
        set_pool, "Lin Sivvi, Defiant Hero",
        a_library=[nem["Skyshroud Poacher"], nem["Defiant Falcon"], nem["Mogg Toady"]],
    )

    result = game.activate_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=0, x_value=2
    )
    assert result.supported, result.details
    assert lin.tapped, "{T} is part of the cost"
    assert not game.confirm_search_library(0, 0), "mana value 4 is more than X"
    assert not game.confirm_search_library(0, 2), "a Goblin is not a Rebel"
    assert game.confirm_search_library(0, 1)
    game._settle()

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Defiant Falcon", "Lin Sivvi, Defiant Hero",
    ]
    assert sorted(c.name for c in me.library) == ["Mogg Toady", "Skyshroud Poacher"]


def test_w1g5_lin_sivvi_x_is_the_bound_not_a_constant(set_pool):
    """The same library at X = 4 admits the Poacher: the bound is the
    activation's own X, resolved when the search is armed (CR 601.2b)."""
    nem = set_pool("NEM")
    game, _, _, _ = _w1g5_table(
        set_pool, "Lin Sivvi, Defiant Hero",
        a_library=[nem["Skyshroud Poacher"], nem["Defiant Falcon"]],
    )
    game.activate_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=0, x_value=4
    )
    assert game.confirm_search_library(0, 0)
    game._settle()
    assert "Skyshroud Poacher" in [p.card.name for p in game.controlled_by(0)]


def test_w1g5_lin_sivvi_bottoms_only_a_rebel_card(set_pool):
    """"{3}: Put target Rebel card from your graveyard on the bottom of your
    library."

    The subtype narrows three readers at once and each is asserted: the picker
    offers only the Rebel, an announcement naming the Goblin is refused with
    the {3} still in the pool (CR 601.2c precedes 601.2h), and the Rebel goes
    under the library rather than on top of it.
    """
    nem = set_pool("NEM")
    game, _, me, _ = _w1g5_table(
        set_pool, "Lin Sivvi, Defiant Hero",
        a_graveyard=[nem["Mogg Toady"], nem["Defiant Falcon"]],
        a_library=[nem["Wild Mammoth"]],
    )
    ability = _w1g5_compile(nem["Lin Sivvi, Defiant Hero"]).activated_abilities[1]
    spec = _w1g5_activation_spec(ability)
    assert spec["kind"] == "graveyard_creature"
    assert spec["graveyard_subtypes"] == ["rebel"]
    assert "any_card" not in spec, "the subtype is the whole narrowing"

    game.enforce_mana_costs = True
    me.mana_pool["C"] = 3
    refused = game.activate_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=1,
        target_player_index=0, target_permanent_index=0,
    )
    assert not refused.supported
    assert me.mana_pool["C"] == 3, "a refused announcement pays nothing"
    assert [c.name for c in me.graveyard] == ["Mogg Toady", "Defiant Falcon"]

    taken = game.activate_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=1,
        target_player_index=0, target_permanent_index=1,
    )
    assert taken.supported, taken.details
    game._settle()
    assert [c.name for c in me.graveyard] == ["Mogg Toady"]
    assert [c.name for c in me.library] == ["Wild Mammoth", "Defiant Falcon"]


def _w1g5_thief_swing(set_pool, *, islands=2):
    """Rootwater Thief connects with seat 1, who holds three known cards in
    their library. Seat 0 is interactive so the "you may pay" waits. W1G5's
    own combat rig."""
    lea = set_pool("LEA")
    game, thief, me, them = _w1g5_table(
        set_pool, "Rootwater Thief",
        a_library=[lea["Forest"]] * 3,
        b_library=[lea["Lightning Bolt"], lea["Shivan Dragon"], lea["Giant Growth"]],
    )
    game.enforce_mana_costs = True
    lands = [_W1G5Permanent(card=lea["Island"]) for _ in range(islands)]
    for land in lands:
        game._put_permanent_onto_battlefield(0, land, None)
    game.interactive_seats = {0}
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.declare_attackers(0, [0])
    game.current_step = "declare_blockers"
    game.declare_blockers(1, {})
    game.current_step = "combat_damage"
    game.resolve_combat_damage(0)
    game._settle()
    return game, lands, me, them


def test_w1g5_rootwater_thief_exiles_from_the_damaged_players_library(set_pool):
    """"Whenever this creature deals combat damage to a player, you may pay
    {2}. If you do, search that player's library for a card and exile it, then
    the player shuffles."

    The {2} is paid inside a resolving trigger, where nobody gets a priority
    window to tap for mana, so the payment taps the two Islands itself. "That
    player" is the one the combat damage was dealt to — the search opens
    seat 1's library, not the Thief controller's — and the card goes to its
    owner's exile.
    """
    game, lands, me, them = _w1g5_thief_swing(set_pool)
    assert them.life == 19

    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None and offer.data["cost"] == {"generic": 2}
    assert game._resolve_optional_pay(offer, True, None)
    assert all(land.tapped for land in lands), "the payment tapped the lands"

    search = game.pending_choice_of("search_library", 0)
    assert search is not None and search.data["zone_seat"] == 1
    assert game.confirm_search_library(0, 1)
    game._settle()

    assert [c.name for c in them.exile] == ["Shivan Dragon"]
    assert sorted(c.name for c in them.library) == ["Giant Growth", "Lightning Bolt"]
    assert len(me.library) == 3 and me.exile == [], "the searcher's own zones are untouched"


def test_w1g5_rootwater_thief_decline_and_no_mana_search_nothing(set_pool):
    """"May": declining searches nothing — and with no untapped land the
    offer is never made at all (CR 601.2b offers only what a player is able to
    do), so the trigger resolves without a prompt and seat 1's library keeps
    all three cards."""
    game, _, _, them = _w1g5_thief_swing(set_pool)
    offer = game.pending_choice_of("optional_pay", 0)
    game._resolve_optional_pay(offer, False, None)
    game._settle()
    assert len(them.library) == 3 and them.exile == []

    game, _, _, them = _w1g5_thief_swing(set_pool, islands=0)
    assert game.pending_choice_of("optional_pay", 0) is None
    assert game.pending_choice_of("search_library", 0) is None
    assert len(them.library) == 3 and them.exile == []


def test_w1g5_wandering_eye_reveals_every_hand_including_its_controllers(set_pool):
    """"Players play with their hands revealed." — Revelation's line on a
    creature. Every hand to every seat, the controller's own included (that is
    what separates it from Telepathy), and only while the Eye is on the
    battlefield."""
    card = set_pool("NEM")["Wandering Eye"]
    assert _w1g5_compile(card).supported
    game, eye, _, _ = _w1g5_table(set_pool, "Wandering Eye", seat=1)

    assert _w1g5_hand_revealed_to(game, owner_seat=0, viewer_seat=1)
    assert _w1g5_hand_revealed_to(game, owner_seat=1, viewer_seat=0), (
        "the Eye's controller's hand is revealed too"
    )
    game.remove_from_battlefield(eye)
    assert not _w1g5_hand_revealed_to(game, owner_seat=1, viewer_seat=0)


def test_w1g5_wandering_eye_puts_the_hand_on_the_opponents_wire(set_pool):
    """The card is done only when a client receives the hand: the per-seat
    state payload is where "revealed" stops being a predicate and becomes card
    faces on the other player's screen."""
    from web.app import store

    created = _w1g5_client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "W1G5 Host",
            "guest_name": "W1G5 Guest", "host_colors": 2, "guest_colors": 2,
            "seed": 515,
        },
    ).json()
    sid = created["session_id"]
    _w1g5_client.post(f"/api/sessions/{sid}/join", json={"guest_name": "W1G5 Joiner"})
    game = store.get(sid).game

    def hand_on_wire(viewer, owner):
        state = _w1g5_client.get(
            f"/api/sessions/{sid}/state", params={"seat": viewer}
        ).json()
        return [
            c["name"] if isinstance(c, dict) else c
            for c in state["players"][owner]["hand"]
        ]

    assert set(hand_on_wire(0, 1)) == {"<hidden>"}
    eye = _W1G5Permanent(card=set_pool("NEM")["Wandering Eye"])
    game._put_permanent_onto_battlefield(0, eye, None)
    for viewer in (0, 1):
        owner = 1 - viewer
        assert hand_on_wire(viewer, owner) == [c.name for c in game.players[owner].hand]
    game.remove_from_battlefield(eye)
    assert set(hand_on_wire(0, 1)) == {"<hidden>"}


# --- W1G2: alternative costs and redirects ---
# Skyshroud Cutter (an alternative cost that hands every other player life) and
# Oracle's Attendants (a blanket redirect off an announced creature, answering
# to one chosen source).
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec
from tests.helpers import _nosick


def _w1g2c_table(set_pool, hand=(), mine=(), theirs=()):
    """Two seats, mana costs **enforced**. Basics and bystanders come from
    the base set."""
    pools = (set_pool("NEM"), set_pool("LEA"))

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [card(name) for name in hand]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    caster.battlefield.extend(_nosick(Permanent(card=card(name))) for name in mine)
    other.battlefield.extend(_nosick(Permanent(card=card(name))) for name in theirs)
    game._sync_control()
    return game, caster, other


def test_w1g2_skyshroud_cutter_costs_the_opponent_five_life(set_pool):
    """"If you control a Forest, rather than pay this spell's mana cost, you may
    have each other player gain 5 life." The Cutter lands, the opponent gains,
    and the pool is untouched; with no Forest there is no offer."""
    game, caster, other = _w1g2c_table(set_pool, ["Skyshroud Cutter"], mine=("Island",))
    assert not game.cast_from_hand(0, "Skyshroud Cutter", alternative_cost=True).supported

    game, caster, other = _w1g2c_table(set_pool, ["Skyshroud Cutter"], mine=("Forest",))
    result = game.cast_from_hand(0, "Skyshroud Cutter", alternative_cost=True)

    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Forest", "Skyshroud Cutter"]
    assert (caster.life, other.life) == (20, 25)
    assert not any(caster.mana_pool.values())


def _w1g2c_attendants_ability_index(set_pool):
    program = compile_card_oracle(set_pool("NEM")["Oracle's Attendants"])
    return next(
        i for i, ability in enumerate(program.activated_abilities)
        if ability.instruction.kind
        == "redirect_chosen_source_damage_off_target_until_eot"
    )


def test_w1g2_oracles_attendants_picker_asks_for_a_creature_and_a_source(set_pool):
    """Two announcements: the protected creature is a target (CR 601.2c) and
    the source is CR 609.7a's choice, which is not one. A picker asking only
    for the creature would send an activation that moves nothing."""
    program = compile_card_oracle(set_pool("NEM")["Oracle's Attendants"])
    ability = program.activated_abilities[_w1g2c_attendants_ability_index(set_pool)]
    assert derive_activation_spec(ability) == {
        "kind": "creature", "requires_source": True,
    }


def test_w1g2_oracles_attendants_takes_the_chosen_sources_damage_all_turn(set_pool):
    """"{T}: **All** damage that would be dealt to target creature this turn by
    a source of your choice is dealt to this creature instead."

    Blanket, not "the next time": both hits from the chosen source move, and
    the first does not use the effect up. Only that source's damage moves — a
    second creature's hit lands on the protected one as printed.
    """
    game, caster, other = _w1g2c_table(
        set_pool, mine=("Oracle's Attendants", "Grizzly Bears"),
        theirs=("Hill Giant", "Llanowar Elves"),
    )
    attendants, bears = caster.battlefield
    giant, elves = other.battlefield

    result = game.activate_permanent_ability(
        0, "Oracle's Attendants", permanent_index=0,
        ability_index=_w1g2c_attendants_ability_index(set_pool),
        target_player_index=0, target_permanent_index=1,
        source_seat=1, source_permanent_index=0,
    )
    assert result.supported, result.details
    assert attendants.tapped

    game._mark_damage_on_permanent(bears, 1, source=giant)
    game._mark_damage_on_permanent(bears, 2, source=giant)
    assert (bears.damage_marked, attendants.damage_marked) == (0, 3)

    game._mark_damage_on_permanent(bears, 1, source=elves)
    assert (bears.damage_marked, attendants.damage_marked) == (1, 3)


def test_w1g2_oracles_attendants_with_no_source_named_moves_nothing(set_pool):
    """CR 609.7a requires the source be chosen. A blanket record answering to
    any source would make the Attendants take every point dealt to the creature
    all turn, so an activation that named none arms nothing — the reading that
    cannot be wrong in its controller's favour."""
    game, caster, other = _w1g2c_table(
        set_pool, mine=("Oracle's Attendants", "Grizzly Bears"),
        theirs=("Hill Giant",),
    )
    attendants, bears = caster.battlefield

    result = game.activate_permanent_ability(
        0, "Oracle's Attendants", permanent_index=0,
        ability_index=_w1g2c_attendants_ability_index(set_pool),
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details

    game._mark_damage_on_permanent(bears, 1, source=other.battlefield[0])
    assert (bears.damage_marked, attendants.damage_marked) == (1, 0)


# --- W1G4: amounts and bounded targets ---
# Two legends: Ascendant Evincar's colour-*negated* anthem, carried as a filter
# field the layer-7c refresh tests through the layer-5 colour accessor, and
# Volrath the Fallen's pump sized by what its own discard cost paid.
from engine import Game as _W1g4Game
from engine import PlayerState as _W1g4PlayerState
from engine.models import CardDefinition as _W1g4Card
from engine.models import Permanent as _W1g4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_activation_spec as _w1g4_activation_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_creature_card(name, power, toughness, colors=(), cmc=0):
    """A vanilla test creature of *colors* and mana value *cmc*."""
    line = "Creature - Test"
    return _W1g4Card(
        name=name, mana_cost="{%d}" % cmc if cmc else "", cmc=float(cmc),
        type_line=line, oracle_text="", colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4_creature_table(seat0=(), seat1=(), hand=()):
    """Two seats, costs unenforced, P0's main phase with *hand* in it."""
    table = _W1g4Game(players=[
        _W1g4PlayerState(name="P0", battlefield=list(seat0), hand=list(hand)),
        _W1g4PlayerState(name="P1", battlefield=list(seat1)),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set()
    table.start_turn(0)
    table._close_current_priority_step()
    return table


def test_w1g4_ascendant_evincar_lifts_black_and_shrinks_nonblack_everywhere(
    set_pool,
):
    """"Other black creatures get +1/+1. Nonblack creatures get -1/-1."

    Both lines reach every player's creatures. The Evincar is black, so the
    first line's "other" keeps it a 3/3 and the second line misses it; a
    colourless creature is nonblack (CR 105.2c) and shrinks; a nonblack 1/1
    dies to the state-based check. The exclusion was the refused half — the
    lord-buff table carried no colour exclusion, so the sentence could only be
    dropped or refused.
    """
    black_ally = _W1g4Permanent(card=_w1g4_creature_card("Black Ally", 2, 2, ("B",)))
    green_ally = _W1g4Permanent(card=_w1g4_creature_card("Green Ally", 2, 2, ("G",)))
    colourless = _W1g4Permanent(card=_w1g4_creature_card("Grey Foe", 2, 2))
    black_foe = _W1g4Permanent(card=_w1g4_creature_card("Black Foe", 2, 2, ("B",)))
    weenie = _W1g4Permanent(card=_w1g4_creature_card("Weenie", 1, 1, ("W",)))
    game = _w1g4_creature_table(
        (black_ally, green_ally), (colourless, black_foe, weenie),
        hand=(set_pool("NEM")["Ascendant Evincar"],),
    )

    game.cast_from_hand(0, "Ascendant Evincar")
    _w1g4_resolve(game)

    evincar = next(
        perm for perm in game.all_permanents() if perm.card.name == "Ascendant Evincar"
    )
    sizes = {
        perm.card.name: (perm.effective_power, perm.effective_toughness)
        for perm in (evincar, black_ally, green_ally, colourless, black_foe)
    }
    assert sizes == {
        "Ascendant Evincar": (3, 3),
        "Black Ally": (3, 3), "Black Foe": (3, 3),
        "Green Ally": (1, 1), "Grey Foe": (1, 1),
    }
    assert not game.is_on_battlefield(weenie)


def test_w1g4_ascendant_evincar_reads_colour_through_the_layers(set_pool):
    """A creature *made* black escapes the debuff and joins the anthem, because
    both lines ask the layer-5 colour accessor on every recompute rather than
    the printed colour (CR 613.5's own worked example, one colour over)."""
    evincar = _W1g4Permanent(card=set_pool("NEM")["Ascendant Evincar"])
    bear = _W1g4Permanent(card=_w1g4_creature_card("Green Bear", 2, 2, ("G",)))
    game = _w1g4_creature_table((evincar,), (bear,))
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()
    assert (bear.effective_power, bear.effective_toughness) == (1, 1)

    bear.metadata["color_override"] = ("B",)
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()
    assert "B" in bear.effective_colors
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)


def test_w1g4_volrath_grows_by_the_discarded_creature_cards_mana_value(set_pool):
    """"{1}{B}, Discard a creature card: Volrath the Fallen gets +X/+X until
    end of turn, where X is the discarded card's mana value."

    X is read off the payment path's record of the card the cost discarded
    (CR 601.2h then 608.2h) — the same channel Pyromancy's damage reads. The
    cost is narrowed to a *creature* card and the player names which: naming a
    noncreature card is refused with nothing paid.
    """
    volrath = _W1g4Permanent(card=set_pool("NEM")["Volrath the Fallen"])
    volrath.metadata["summoning_sickness_turn"] = -99
    instant = set_pool("NEM")["Rupture"]
    five_drop = _w1g4_creature_card("Five Drop", 5, 5, cmc=5)
    game = _w1g4_creature_table((volrath,), hand=(instant, five_drop))
    ability = _w1g4_compile(volrath.card).activated_abilities[0]
    assert _w1g4_activation_spec(ability)["filters"] == [{"type_filter": "creature"}]

    refused = game.activate_permanent_ability(0, "Volrath the Fallen", cost_hand_index=0)
    assert not refused.supported
    assert [card.name for card in game.players[0].hand] == ["Rupture", "Five Drop"]

    result = game.activate_permanent_ability(0, "Volrath the Fallen", cost_hand_index=1)
    assert result.supported, result
    _w1g4_resolve(game)

    assert [card.name for card in game.players[0].graveyard] == ["Five Drop"]
    assert (volrath.effective_power, volrath.effective_toughness) == (11, 9)
