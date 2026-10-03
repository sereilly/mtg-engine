"""Prophecy enchantments.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: untapped lands and untap steps ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.grammar.vocabulary import singular as _w1g4_singular
from engine.models import Permanent as _W1G4Permanent
from tests.helpers import _mk_creature_card as _w1g4_creature
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_enchantment_duel():
    """Two seats, seat 0 active, mana costs off — ends on its own game name."""
    w1g4_table = _W1G4Game(
        players=[_W1G4PlayerState(name="W1G4-A"), _W1G4PlayerState(name="W1G4-B")]
    )
    w1g4_table.enforce_mana_costs = False
    w1g4_table.active_player_index = 0
    return w1g4_table


def _w1g4_place(game, seat, card, *, tapped=False):
    """*card* onto *seat*'s battlefield through the real entry, tapped as asked."""
    w1g4_placed = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, w1g4_placed, None)
    w1g4_placed.tapped = tapped
    return w1g4_placed


def test_w1g4_mercenaries_is_read_as_the_mercenary_type():
    """English's consonant-y plural, undone only into a word the vocabulary
    knows — so "abilities" is left alone rather than becoming "ability"."""
    assert _w1g4_singular("mercenaries") == "mercenary"
    assert _w1g4_singular("allies") == "ally"
    assert _w1g4_singular("abilities") == "abilities"


def test_w1g4_root_cage_holds_every_mercenary_down_on_both_sides(set_pool):
    """"Mercenaries don't untap during their controllers' untap steps." Each
    untap step is its own controller's, so the opponent's Mercenary stays down
    on their turn and the caster's own on theirs; a non-Mercenary untaps."""
    pcy, ice = set_pool("PCY"), set_pool("ICE")
    game = _w1g4_enchantment_duel()
    _w1g4_place(game, 0, pcy["Root Cage"])
    # Ice Age's Mercenaries is a Human Mercenary; Prophecy prints none.
    mine = _w1g4_place(game, 0, ice["Mercenaries"], tapped=True)
    theirs = _w1g4_place(game, 1, ice["Mercenaries"], tapped=True)
    bystander = _w1g4_place(game, 1, _w1g4_creature("W1G4 Bear", 2, 2), tapped=True)

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert theirs.tapped and not bystander.tapped

    game.active_player_index = 0
    game.resolve_untap_step(0)
    assert mine.tapped


def test_w1g4_sheltering_prayers_asks_each_land_about_its_own_controller(set_pool):
    """"Basic lands each player controls have shroud as long as **that player**
    controls three or fewer lands." The pronoun is each land's controller, so
    the condition is asked per land: the caster's three Plains are shrouded and
    the opponent's four Swamps are not — and a fourth land switches the
    caster's off while the board on the other side stays as it was."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_enchantment_duel()
    _w1g4_place(game, 0, pcy["Sheltering Prayers"])
    plains = [_w1g4_place(game, 0, lea["Plains"]) for _ in range(3)]
    swamps = [_w1g4_place(game, 1, lea["Swamp"]) for _ in range(4)]
    game.check_state_based_actions()
    assert all(game._has_keyword(land, "shroud") for land in plains)
    assert not any(game._has_keyword(land, "shroud") for land in swamps)

    _w1g4_place(game, 0, lea["Plains"])
    game.check_state_based_actions()
    assert not any(game._has_keyword(land, "shroud") for land in plains)

    # …and a small board on the *other* side is covered too: the enchantment
    # is about every player, not only its controller.
    other = _w1g4_enchantment_duel()
    _w1g4_place(other, 0, pcy["Sheltering Prayers"])
    crowded = [_w1g4_place(other, 0, lea["Plains"]) for _ in range(4)]
    lone = _w1g4_place(other, 1, lea["Swamp"])
    other.check_state_based_actions()
    assert other._has_keyword(lone, "shroud")
    assert not any(other._has_keyword(land, "shroud") for land in crowded)


def test_w1g4_sheltering_prayers_turns_away_a_land_destruction_spell(set_pool):
    """The shroud is enforced where it matters (CR 702.18a): Stone Rain at a
    shrouded Plains is refused at announcement; at an unshrouded Swamp it
    resolves. A nonbasic land is never covered — "basic" is read."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _w1g4_enchantment_duel()
    _w1g4_place(game, 0, pcy["Sheltering Prayers"])
    plains = _w1g4_place(game, 0, lea["Plains"])
    tundra = _w1g4_place(game, 0, lea["Tundra"])
    swamps = [_w1g4_place(game, 1, lea["Swamp"]) for _ in range(4)]
    game.check_state_based_actions()
    assert not game._has_keyword(tundra, "shroud")

    game.active_player_index = 1
    game.players[1].hand.append(lea["Stone Rain"])
    assert not game.cast_from_hand(
        1, "Stone Rain", target_player_index=0,
        target_permanent_ids=[plains.permanent_id],
    ).supported
    assert game.is_on_battlefield(plains)
    assert "Plains is an illegal target for Stone Rain" in game.log

    game.active_player_index = 0
    game.players[0].hand.append(lea["Stone Rain"])
    assert game.cast_from_hand(
        0, "Stone Rain", target_player_index=1,
        target_permanent_ids=[swamps[0].permanent_id],
    ).supported
    _w1g4_resolve(game)
    assert not game.is_on_battlefield(swamps[0])

# --- W1G3: activation costs ---
# Brutal Suppression: "Activated abilities of nontoken Rebels cost an additional
# "Sacrifice a land" to activate." Drought's imposed sacrifice
# (``cost_modifiers.sacrifice_taxes``) with its subject read off the ability's
# source — so it is charged, it refuses with nothing paid when no land can pay
# it, and a token Rebel or a non-Rebel is untouched.

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack


def _w1g3_suppressed(set_pool, mine, *, token_rebel=False):
    """Seat 1 controls Brutal Suppression; seat 0 holds *mine*, turn 0 begun.
    *token_rebel* marks seat 0's first permanent as a token."""
    me = [Permanent(card=card) for card in mine]
    if token_rebel:
        me[0].metadata["is_token"] = True
    suppression = Permanent(card=set_pool("PCY")["Brutal Suppression"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(me)),
        PlayerState(name="P1", battlefield=[suppression]),
    ])
    game.enforce_mana_costs = False
    for permanent in me:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, me


def test_w1g3_brutal_suppression_charges_a_rebel_a_land(set_pool):
    """Rappelling Scouts (a Human Rebel Scout) pays a land on top of its {2}{W},
    and its ability still resolves."""
    lea = set_pool("LEA")
    game, (scouts, forest) = _w1g3_suppressed(
        set_pool, [set_pool("MMQ")["Rappelling Scouts"], lea["Forest"]],
    )
    result = game.queue_permanent_ability(0, "Rappelling Scouts", mana_color="B")
    assert result.supported, result.details
    resolve_stack(game)

    assert not game.is_on_battlefield(forest)
    assert [c.name for c in game.players[0].graveyard] == ["Forest"]
    assert ("color", "B") in game._protection_qualities(scouts)


def test_w1g3_brutal_suppression_with_no_land_refuses_before_paying(set_pool):
    """CR 601.2h via 602.2b: an additional cost that cannot be paid makes the
    ability unactivatable — refused with nothing on the stack and nothing paid."""
    game, (scouts,) = _w1g3_suppressed(set_pool, [set_pool("MMQ")["Rappelling Scouts"]])
    result = game.queue_permanent_ability(0, "Rappelling Scouts", mana_color="B")

    assert not result.supported
    assert "Land" in result.details and "Brutal Suppression" in result.details
    assert game.stack == [] and game._protection_qualities(scouts) == set()


def test_w1g3_brutal_suppression_spares_tokens_and_non_rebels(set_pool):
    """"Nontoken Rebels": a token Rebel's ability and a Drudge Skeletons'
    regeneration are activated with every land left where it was."""
    lea = set_pool("LEA")
    game, (scouts, forest) = _w1g3_suppressed(
        set_pool, [set_pool("MMQ")["Rappelling Scouts"], lea["Forest"]],
        token_rebel=True,
    )
    result = game.queue_permanent_ability(0, "Rappelling Scouts", mana_color="B")
    assert result.supported, result.details
    resolve_stack(game)
    assert game.is_on_battlefield(forest)

    game, (_skeletons, forest) = _w1g3_suppressed(
        set_pool, [lea["Drudge Skeletons"], lea["Forest"]],
    )
    result = game.queue_permanent_ability(0, "Drudge Skeletons")
    assert result.supported, result.details
    assert game.is_on_battlefield(forest)

# --- W1G1: rhystic ---
from engine import Game, PlayerState
from engine.damage_events import deal_damage
from engine.models import Permanent


def _w1g1_circle_duel(set_pool, *, opponent_lands: int):
    """Seat 0 (active) holds Rhystic Circle and four Islands; seat 1 holds a
    Hill Giant and *opponent_lands* Islands."""
    island = set_pool("LEA")["Island"]
    circle = Permanent(card=set_pool("PCY")["Rhystic Circle"])
    giant = Permanent(card=set_pool("LEA")["Hill Giant"])
    game = Game(players=[
        PlayerState(
            name="P0", life=20,
            battlefield=[circle] + [Permanent(card=island) for _ in range(4)],
        ),
        PlayerState(
            name="P1", life=20,
            battlefield=[giant] + [Permanent(card=island) for _ in range(opponent_lands)],
        ),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, giant


def _w1g1_giant_hits(game, giant) -> int:
    """What a 3-damage hit from the Giant to seat 0 deals after the shields."""
    return deal_damage(
        game, {"recipient": game.players[0], "amount": 3, "source": giant, "combat": True},
    ).dealt


def test_rhystic_circle_shields_its_controller_when_no_one_pays(set_pool):
    """"{1}: Any player may pay {1}. If no one does, the next time a source of
    your choice would deal damage to you this turn, prevent that damage." The
    controller is asked first and does not pay to stop its own shield; the
    opponent has no mana; so the shield is armed against the chosen source."""
    game, giant = _w1g1_circle_duel(set_pool, opponent_lands=0)

    assert game.activate_permanent_ability(
        0, "Rhystic Circle", target_permanent_ids=[giant.permanent_id],
    ).supported
    game.auto_resolve_pending_choices()
    game._settle()

    assert "P0 declined to pay for Rhystic Circle" in game.log
    assert _w1g1_giant_hits(game, giant) == 0


def test_rhystic_circle_is_bought_off_by_an_opponent_paying_one(set_pool):
    """One Island is enough: the opponent pays {1} and the damage comes
    through. The payment is the whole of what the opponent can do — it is one
    "unless", so once paid nobody else is asked (CR 118.12a)."""
    game, giant = _w1g1_circle_duel(set_pool, opponent_lands=1)

    assert game.activate_permanent_ability(
        0, "Rhystic Circle", target_permanent_ids=[giant.permanent_id],
    ).supported
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g1_giant_hits(game, giant) == 3
    assert [perm.tapped for perm in game.controlled_by(game.players[1])] == [False, True]


def test_rhystic_circle_lets_its_controller_answer_first(set_pool):
    """Asked interactively: the active player — the Circle's controller — is
    asked first; declining moves the offer on, and a decline there arms the
    shield."""
    game, giant = _w1g1_circle_duel(set_pool, opponent_lands=3)

    assert game.activate_permanent_ability(
        0, "Rhystic Circle", target_permanent_ids=[giant.permanent_id],
    ).supported
    owed = [c.player_index for c in game.pending_choices if c.kind == "optional_pay"]
    assert owed == [0]
    assert game.confirm_optional_pay(0, accept=False)
    assert game.confirm_optional_pay(1, accept=False)
    game._settle()

    assert _w1g1_giant_hits(game, giant) == 0

# --- W1G2: spell costs ---
from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_entangler_combat(set_pool, *, enchant: bool):
    """Three attacking Bears against P2's lone Wall of Wood, with Entangler
    cast by P2 onto the Wall first when *enchant* — through the real cast, so
    the picker's target and the attachment are the engine's own."""
    lea = set_pool("LEA")
    wall = _W1G2Permanent(card=lea["Wall of Wood"])
    bears = [_W1G2Permanent(card=lea["Grizzly Bears"]) for _ in range(3)]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="P1", battlefield=list(bears)),
        _W1G2PlayerState(
            name="P2", battlefield=[wall], hand=[set_pool("PCY")["Entangler"]]
        ),
    ])
    game._sync_control()
    game.enforce_mana_costs = False
    if enchant:
        game.start_turn(1)
        result = game.cast_from_hand(
            1, "Entangler", target_player_index=1, target_permanent_index=0,
            target_permanent_ids=[wall.permanent_id],
        )
        assert result.supported, result.details
        _w1g2_resolve_stack(game)
    for bear in bears:
        bear.summoning_sick = False
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    declared, why = game.declare_attackers(0, [0, 1, 2], 1)
    assert declared, why
    game.advance_combat_phase()
    return game, wall


def test_w1g2_entangler_lets_the_enchanted_creature_block_every_attacker(set_pool):
    """"Enchanted creature can block any number of creatures." (CR 509.1b.)

    Wall of Glare's permission one sentence-subject over, asked of the Auras
    attached when blockers are declared — the same table, with "enchanted"
    rewritten to "this", so the two printings cannot come to mean different
    ceilings. Unenchanted, the same Wall blocks one.
    """
    program = _w1g2_compile(set_pool("PCY")["Entangler"])
    assert program.supported, program.reason

    game, wall = _w1g2_entangler_combat(set_pool, enchant=True)
    assert game._max_blocks_for(wall) >= 3
    blocked, why = game.declare_blockers(1, {0: [0, 1, 2]})
    assert blocked, why

    game, wall = _w1g2_entangler_combat(set_pool, enchant=False)
    assert game._max_blocks_for(wall) == 1
    blocked, why = game.declare_blockers(1, {0: [0, 1, 2]})
    assert not blocked, why


def test_w1g2_entanglers_permission_ends_with_the_aura(set_pool):
    """Nothing is stamped on the creature: the ceiling is read off the Aura
    while it is attached, so destroying the Aura takes the permission with it
    and nothing has to remember to clear a flag."""
    game, wall = _w1g2_entangler_combat(set_pool, enchant=True)
    entangler = next(
        p for p in game.all_permanents() if p.card.name == "Entangler"
    )
    assert game._max_blocks_for(wall) > 1
    game.remove_from_battlefield(entangler)
    assert game._max_blocks_for(wall) == 1

# --- W1G5: prevention and odd ones ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_revel_table(set_pool, *, active):
    """Endbringer's Revel on seat 0; a creature card and an instant card in
    each graveyard; *active* in its main phase. W1G5's own."""
    lea = set_pool("LEA")
    me = _W1G5PlayerState(
        name="W1G5-A", graveyard=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    them = _W1G5PlayerState(
        name="W1G5-B", graveyard=[lea["Lightning Bolt"], lea["Hill Giant"]],
    )
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(
        0, _W1G5Permanent(card=set_pool("PCY")["Endbringer's Revel"]), None,
    )
    game.active_player_index = active
    game.current_turn_phase = "precombat_main"
    return game, me, them


def _w1g5_revel(game, activator, *, seat, index):
    return game.activate_permanent_ability(
        activator, "Endbringer's Revel", ability_index=0,
        source_controller_index=0, target_player_index=seat,
        target_permanent_index=index,
    )


def test_w1g5_endbringers_revel_returns_to_the_owners_hand(set_pool):
    """"{4}: Return target creature card from a graveyard to its owner's hand."

    The picker offers the creature cards of **both** graveyards and no instant.
    The Revel's controller reaching into the opponent's pile hands the Hill
    Giant back to the *opponent* — its owner (CR 404.1, 400.3) — not to the
    activator.
    """
    game, me, them = _w1g5_revel_table(set_pool, active=0)
    spec = game.activation_target_spec(0, 0, 0)
    assert spec["kind"] == "graveyard_creature"
    assert sorted((t["seat"], t["name"]) for t in spec["valid_targets"]) == [
        (0, "Grizzly Bears"), (1, "Hill Giant"),
    ]

    assert _w1g5_revel(game, 0, seat=1, index=1).supported
    _w1g5_resolve_stack(game)
    assert [c.name for c in them.hand] == ["Hill Giant"]
    assert me.hand == []
    assert [c.name for c in them.graveyard] == ["Lightning Bolt"]

    assert not _w1g5_revel(game, 0, seat=0, index=1).supported, "an instant card"


def test_w1g5_endbringers_revel_any_player_at_sorcery_speed(set_pool):
    """"Any player may activate this ability but only as a sorcery."

    The opponent activates it on their own main phase, pays the {4} from
    **their** pool, and gets their own creature card back; outside a main
    phase, or on the Revel controller's turn, the same activation is refused
    with nothing paid.
    """
    game, me, them = _w1g5_revel_table(set_pool, active=1)
    game.enforce_mana_costs = True
    them.mana_pool["B"] = 4

    game.current_turn_phase = "beginning_of_combat"
    assert not _w1g5_revel(game, 1, seat=1, index=1).supported
    assert them.mana_pool["B"] == 4, "a refused activation pays nothing"

    game.current_turn_phase = "precombat_main"
    assert _w1g5_revel(game, 1, seat=1, index=1).supported
    assert them.mana_pool["B"] == 0 and me.mana_pool["B"] == 0
    _w1g5_resolve_stack(game)
    assert [c.name for c in them.hand] == ["Hill Giant"]

    game, _me, them = _w1g5_revel_table(set_pool, active=0)
    assert not _w1g5_revel(game, 1, seat=1, index=1).supported, "not their turn"
    assert them.hand == []


def _w1g5_enchantment_in_play(set_pool, name, *, hand=(), mine=20, theirs=20):
    """Seat 0 casts *name* in its main phase with *hand* beside it; libraries
    of Plains/Islands to draw from. W1G5's own."""
    lea = set_pool("LEA")
    me = _W1G5PlayerState(
        name="W1G5-A", hand=[set_pool("PCY")[name], *(lea[n] for n in hand)],
        library=[lea["Plains"]] * 20,
    )
    them = _W1G5PlayerState(name="W1G5-B", library=[lea["Island"]] * 20)
    me.life, them.life = mine, theirs
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.turn = 3
    assert game.cast_from_hand(0, name).supported
    _w1g5_resolve_stack(game)
    return game, me, them


def _w1g5_whole_turn(game, seat):
    """*seat*'s beginning phase, with everything it triggered resolved."""
    game.start_turn(seat)
    for _ in range(4):
        game.auto_resolve_pending_choices()
        if not _w1g5_resolve_stack(game):
            break


def _w1g5_converge(set_pool, *, mine, theirs):
    from engine.named_counters import counters_on

    game, me, them = _w1g5_enchantment_in_play(
        set_pool, "Celestial Convergence", mine=mine, theirs=theirs,
    )
    (convergence,) = [
        p for p in game.controlled_by(0) if p.card.name == "Celestial Convergence"
    ]
    assert counters_on(convergence, "omen") == 7
    seen = []
    for _ in range(7):
        _w1g5_whole_turn(game, 1)
        _w1g5_whole_turn(game, 0)
        seen.append((counters_on(convergence, "omen"), me.lost, them.lost))
    return game, me, them, seen


def test_w1g5_celestial_convergence_seventh_upkeep_crowns_the_life_leader(set_pool):
    """"This enchantment enters with seven omen counters on it. / At the
    beginning of your upkeep, remove an omen counter from this enchantment. If
    there are no omen counters on this enchantment, the player with the highest
    life total wins the game."

    Seven of its controller's upkeeps, one counter each (the opponent's upkeeps
    remove none), and nothing happens until the last. Then the leader wins —
    whichever seat that is: the controller on 20 against 15, the *opponent* on
    15 against 12 (CR 104.2b names a player, not the enchantment's controller).
    """
    _game, me, them, seen = _w1g5_converge(set_pool, mine=20, theirs=15)
    assert [count for count, _a, _b in seen] == [6, 5, 4, 3, 2, 1, 0]
    assert all(not a and not b for _c, a, b in seen[:-1])
    assert (me.lost, them.lost) == (False, True)

    game, me, them, _seen = _w1g5_converge(set_pool, mine=12, theirs=15)
    assert (me.lost, them.lost) == (True, False)
    assert not game.is_draw


def test_w1g5_celestial_convergence_tie_on_the_last_counter_is_a_draw(set_pool):
    """"If two or more players are tied for highest life total, the game is a
    draw." — the tie arm of the win, not a sentence of its own: level on 20
    for six upkeeps with counters left, and the game goes on; level when the
    last counter comes off, and it is a draw (CR 104.4c) with nobody winning.
    """
    game, me, them, seen = _w1g5_converge(set_pool, mine=20, theirs=20)
    assert all(not a and not b for _c, a, b in seen[:-1]), "counters left: no draw"
    assert game.is_draw
    assert not any("wins the game" in line for line in game.log)


def test_w1g5_heightened_awareness_discards_hand_then_draws_extra(set_pool):
    """"As this enchantment enters, discard your hand. / At the beginning of
    your draw step, draw an additional card."

    The hand goes as it enters (CR 614.1c), through the discard seam — every
    card reaches the graveyard, Awareness itself is on the battlefield — and the
    controller's next draw step draws two.
    """
    game, me, _them = _w1g5_enchantment_in_play(
        set_pool, "Heightened Awareness",
        hand=("Island", "Lightning Bolt", "Grizzly Bears"),
    )
    assert me.hand == []
    assert sorted(c.name for c in me.graveyard) == [
        "Grizzly Bears", "Island", "Lightning Bolt",
    ]
    assert [p.card.name for p in game.controlled_by(0)] == ["Heightened Awareness"]

    _w1g5_whole_turn(game, 1)
    _w1g5_whole_turn(game, 0)
    assert [c.name for c in me.hand] == ["Plains", "Plains"]


def _w1g5_terrain_on_a_forest(set_pool):
    """A Forest seat 0 has controlled since the turn began, enchanted by Living
    Terrain cast through the real cast path. W1G5's own."""
    lea = set_pool("LEA")
    forest = _W1G5Permanent(card=lea["Forest"])
    me = _W1G5PlayerState(
        name="W1G5-A", battlefield=[forest],
        hand=[set_pool("PCY")["Living Terrain"], lea["Disenchant"]],
    )
    them = _W1G5PlayerState(name="W1G5-B")
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    forest.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    spec = game.cast_target_spec(0, set_pool("PCY")["Living Terrain"])
    assert [t["name"] for t in spec["valid_targets"]] == ["Forest"]
    assert game.cast_from_hand(
        0, "Living Terrain", target_player_index=0, target_permanent_index=0
    ).supported
    _w1g5_resolve_stack(game)
    return game, me, them, forest


def test_w1g5_living_terrain_makes_a_five_six_green_treefolk_land(set_pool):
    """"Enchanted land is a 5/6 green Treefolk creature that's still a land."

    CR 613 layers 4, 5 and 7b off the Aura's own text: the Forest is a land, a
    Forest, a creature and a Treefolk, green, 5/6 — and it attacks for 5 (it has
    been under its controller's control since the turn began, CR 302.6).
    """
    game, _me, them, forest = _w1g5_terrain_on_a_forest(set_pool)
    assert forest.is_creature and forest.has_type("land")
    assert forest.has_type("forest") and forest.has_type("treefolk")
    assert forest.effective_colors == {"G"}
    assert (forest.effective_power, forest.effective_toughness) == (5, 6)

    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert them.life == 15


def test_w1g5_living_terrain_ends_with_the_aura(set_pool):
    """Removal is the Aura ceasing to be attached: Disenchant on Living Terrain
    leaves a plain colourless Forest, with no remembered body to undo."""
    game, me, _them, forest = _w1g5_terrain_on_a_forest(set_pool)
    (terrain,) = [p for p in game.controlled_by(0) if p.card.name == "Living Terrain"]
    assert game.cast_from_hand(
        0, "Disenchant", target_player_index=0,
        target_permanent_ids=[terrain.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)

    assert "Living Terrain" in [c.name for c in me.graveyard]
    assert not forest.is_creature and forest.has_type("land")
    assert not forest.has_type("treefolk")
    assert forest.effective_colors == set()
# end of the W1G5 enchantments block

# --- W1G6: tokens, zones and triggers ---
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.tokens import make_token_card as _w1g6_make_token_card
from tests.helpers import _mk_card as _w1g6_mk_card, resolve_stack as _w1g6_resolve


def _w1g6_put(game, seat, card, *, token=False):
    perm = _W1G6Permanent(card=card)
    if token:
        perm.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm  # _w1g6_put


def _w1g6_table(p0=None, p1=None):
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", **(p0 or {})),
        _W1G6PlayerState(name="P1", **(p1 or {})),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    return game  # _w1g6_table


def _w1g6_land(name="Forest"):
    return _w1g6_mk_card(name, f"Basic Land — {name}")


def test_w1g6_overburden_bounces_a_land_of_the_creatures_controller(set_pool):
    """"Whenever a player puts a nontoken creature onto the battlefield, that
    player returns a land they control to its owner's hand." The seat whose
    creature entered returns one of *its* lands — the enchantment's controller
    keeps theirs — and a token entering asks nothing."""
    pcy = set_pool("PCY")
    bear = _w1g6_mk_card("Bear", "{1}{G}", "Creature — Bear", "")
    game = _w1g6_table(p1={"hand": [bear]})
    _w1g6_put(game, 0, pcy["Overburden"])
    mine = _w1g6_put(game, 0, _w1g6_land("Island"))
    theirs = [_w1g6_put(game, 1, _w1g6_land(n)) for n in ("Forest", "Mountain")]

    # A token entering is not a nontoken creature: nothing triggers.
    _w1g6_put(game, 1, _w1g6_make_token_card("Elf Token", 1, 1, "Creature — Elf"),
              token=True)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in game.players[1].hand] == ["Bear"]
    assert all(game.is_on_battlefield(p) for p in theirs)

    # The same entry path with a nontoken creature does trigger — for the
    # enchantment's own controller this time, who returns their own land.
    _w1g6_put(game, 0, _w1g6_mk_card("Wolf", "Creature — Wolf"))
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert not game.is_on_battlefield(mine)
    assert all(game.is_on_battlefield(p) for p in theirs)

    game.start_turn(1)
    game._close_current_priority_step()
    result = game.cast_from_hand(1, "Bear")
    assert result.supported, result.details
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)

    assert [c.name for c in game.players[1].hand] in (["Forest"], ["Mountain"])
    assert sum(game.is_on_battlefield(p) for p in theirs) == 1
    assert [c.name for c in game.players[0].hand] == ["Island"]


def _w1g6_harvest_upkeep(set_pool, graveyard):
    pcy = set_pool("PCY")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", graveyard=list(graveyard)),
        _W1G6PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    _w1g6_put(game, 0, pcy["Forgotten Harvest"])
    mine = _w1g6_put(game, 0, _w1g6_mk_card("Wolf", "Creature — Wolf"))
    theirs = _w1g6_put(game, 1, _w1g6_mk_card("Bear", "Creature — Bear"))
    game.start_turn(0)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    return game, mine, theirs  # _w1g6_harvest_upkeep


def test_w1g6_forgotten_harvest_trades_a_land_card_for_a_counter(set_pool):
    """"At the beginning of your upkeep, you may exile a land card from your
    graveyard. If you do, put a +1/+1 counter on target creature." The land
    card — not the creature card beside it — is the one exiled."""
    game, mine, theirs = _w1g6_harvest_upkeep(
        set_pool, [_w1g6_land("Forest"), _w1g6_mk_card("Elk", "Creature — Elk")]
    )
    assert [c.name for c in game.players[0].exile] == ["Forest"]
    assert [c.name for c in game.players[0].graveyard] == ["Elk"]
    assert (mine.effective_power, mine.effective_toughness) == (3, 3)
    assert theirs.effective_power == 2


def _w1g6_spell(name, mana_cost, cmc):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=float(cmc), type_line="Sorcery",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Sorcery"},
    )


def test_w1g6_infernal_genesis_mints_minions_for_the_milled_mana_value(set_pool):
    """"At the beginning of each player's upkeep, that player mills a card.
    Then they create X 1/1 black Minion creature tokens, where X is the milled
    card's mana value." On the opponent's upkeep the opponent mills and gets
    the tokens; on the controller's own, a milled land makes none."""
    game = _w1g6_table(
        p0={"library": [_w1g6_land("Swamp"), _w1g6_land("Swamp")]},
        p1={"library": [_w1g6_spell("Big Spell", "{3}{B}", 4), _w1g6_land("Island")]},
    )
    _w1g6_put(game, 0, set_pool("PCY")["Infernal Genesis"])

    game.start_turn(1)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert [c.name for c in game.players[1].graveyard] == ["Big Spell"]
    minions = [p for p in game.controlled_by(1) if p.card.name == "Minion Token"]
    assert len(minions) == 4
    assert all(p.metadata.get("is_token") for p in minions)
    assert (minions[0].effective_power, minions[0].effective_toughness) == (1, 1)
    assert not [p for p in game.controlled_by(0) if p.card.name == "Minion Token"]

    game.start_turn(0)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert [c.name for c in game.players[0].graveyard] == ["Swamp"]
    assert not [p for p in game.controlled_by(0) if p.card.name == "Minion Token"]
    assert len([p for p in game.controlled_by(1) if p.card.name == "Minion Token"]) == 4


def test_w1g6_forgotten_harvest_with_no_land_card_offers_nothing(set_pool):
    """No land card is no offer, so the if-you-do counter never lands."""
    game, mine, theirs = _w1g6_harvest_upkeep(
        set_pool, [_w1g6_mk_card("Elk", "Creature — Elk")]
    )
    assert not game.players[0].exile
    assert [c.name for c in game.players[0].graveyard] == ["Elk"]
    assert mine.effective_power == 2 and theirs.effective_power == 2


# --- W2G2: dual nature ---
from engine import Game as _W2G2Game, PlayerState as _W2G2PlayerState
from engine.models import Permanent as _W2G2Permanent
from engine.tokens import CREATED_WITH_PERMANENT_ID as _W2G2_MADE_BY
from tests.helpers import _mk_creature_card as _w2g2_creature
from tests.helpers import resolve_stack as _w2g2_resolve


def _w2g2_table(**p1):
    """Two seats, seat 0 active in its main phase, mana costs off."""
    w2g2_game = _W2G2Game(players=[
        _W2G2PlayerState(name="P0"), _W2G2PlayerState(name="P1", **p1),
    ])
    w2g2_game.enforce_mana_costs = False
    w2g2_game.start_turn(0)
    w2g2_game._close_current_priority_step()
    return w2g2_game  # the W2G2 Dual Nature table


def _w2g2_enter(game, seat, card):
    """Put *card* onto the battlefield through the one entry seam, and drain."""
    entered = _W2G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, entered, None)
    _w2g2_resolve(game)
    return entered  # entered through _put_permanent_onto_battlefield


def _w2g2_named(game, seat, name, *, token):
    return [
        perm for perm in game.controlled_by(seat)
        if perm.card.name == name and bool(perm.metadata.get("is_token")) == token
    ]  # W2G2: permanents of one name and tokenness


def test_w2g2_dual_nature_copies_a_cast_creature_for_its_caster(set_pool):
    """"Whenever a nontoken creature enters, its controller creates a token
    that's a copy of that creature." An opponent casts a Bear through the real
    cast path: the copy is theirs (CR 111.2 — its controller creates it), is a
    token, is a 2/2 Bear by CR 707.2, and records the Dual Nature that made it.
    The copy is itself a token entering, so it does not trigger the line again:
    one Bear makes exactly one copy."""
    bear = _w2g2_creature("Bear", 2, 2)
    game = _w2g2_table(hand=[bear])
    nature = _w2g2_enter(game, 0, set_pool("PCY")["Dual Nature"])

    game.start_turn(1)
    game._close_current_priority_step()
    result = game.cast_from_hand(1, "Bear")
    assert result.supported, result.details
    _w2g2_resolve(game)

    assert len(_w2g2_named(game, 1, "Bear", token=False)) == 1
    copies = _w2g2_named(game, 1, "Bear", token=True)
    assert len(copies) == 1
    (copy,) = copies
    assert copy.is_creature
    assert (copy.effective_power, copy.effective_toughness) == (2, 2)
    assert copy.metadata[_W2G2_MADE_BY] == nature.permanent_id
    assert list(game.controlled_by(0)) == [nature], "Dual Nature's controller got nothing"
    assert "Dual Nature created a token copy of Bear" in game.log


def test_w2g2_dual_nature_exiles_every_token_named_like_a_leaving_creature(set_pool):
    """"Whenever a nontoken creature leaves the battlefield, exile all tokens
    with the same name as that creature." Both seats hold a Bear and its copy;
    one Bear dies and *both* Bear tokens go — the sentence names a name, not a
    controller — while the other Bear and an unrelated Wolf copy stay. A token
    leaving is not a nontoken creature leaving, so sacrificing a Wolf copy
    takes nothing else with it."""
    game = _w2g2_table()
    _w2g2_enter(game, 0, set_pool("PCY")["Dual Nature"])
    mine = _w2g2_enter(game, 0, _w2g2_creature("Bear", 2, 2))
    theirs = _w2g2_enter(game, 1, _w2g2_creature("Bear", 2, 2))
    _w2g2_enter(game, 1, _w2g2_creature("Wolf", 3, 3))
    assert len(_w2g2_named(game, 0, "Bear", token=True)) == 1
    assert len(_w2g2_named(game, 1, "Bear", token=True)) == 1

    wolf_copy = _w2g2_named(game, 1, "Wolf", token=True)[0]
    game.sacrifice_permanent(wolf_copy)
    _w2g2_resolve(game)
    assert len(_w2g2_named(game, 0, "Bear", token=True)) == 1
    assert len(_w2g2_named(game, 1, "Bear", token=True)) == 1

    game.sacrifice_permanent(mine)
    _w2g2_resolve(game)
    assert not _w2g2_named(game, 0, "Bear", token=True)
    assert not _w2g2_named(game, 1, "Bear", token=True)
    assert game.is_on_battlefield(theirs)
    assert len(_w2g2_named(game, 1, "Wolf", token=False)) == 1
    assert "Dual Nature exiled 2 permanent(s)" in game.log


def test_w2g2_dual_nature_leaving_takes_only_the_tokens_it_made(set_pool):
    """"When this enchantment leaves the battlefield, exile all tokens created
    with this enchantment." Two Dual Natures double the copies; destroying the
    first exiles the copy it made and leaves the second one's copy — CR 603.10a
    looks back in time, so the departed enchantment's own id still names its
    tokens."""
    game = _w2g2_table()
    first = _w2g2_enter(game, 0, set_pool("PCY")["Dual Nature"])
    second = _w2g2_enter(game, 1, set_pool("PCY")["Dual Nature"])
    bear = _w2g2_enter(game, 1, _w2g2_creature("Bear", 2, 2))
    copies = _w2g2_named(game, 1, "Bear", token=True)
    assert len(copies) == 2
    assert {c.metadata[_W2G2_MADE_BY] for c in copies} == {
        first.permanent_id, second.permanent_id,
    }

    game.sacrifice_permanent(first)
    _w2g2_resolve(game)
    left = _w2g2_named(game, 1, "Bear", token=True)
    assert [c.metadata[_W2G2_MADE_BY] for c in left] == [second.permanent_id]
    assert game.is_on_battlefield(bear) and game.is_on_battlefield(second)


def test_w2g2_dual_nature_copies_a_creature_that_left_before_resolution(set_pool):
    """CR 608.2h: the copy is made from the creature as it last existed when it
    has left by the time the trigger resolves. The Elk leaves with the copy
    trigger still on the stack; its own leave trigger resolves first (exiling
    no Elk token yet), and then the copy arrives and stays."""
    game = _w2g2_table()
    _w2g2_enter(game, 0, set_pool("PCY")["Dual Nature"])
    elk = _W2G2Permanent(card=_w2g2_creature("Elk", 3, 3))
    game._put_permanent_onto_battlefield(1, elk, None)
    assert game.stack, "the copy trigger is waiting"
    game.sacrifice_permanent(elk)
    _w2g2_resolve(game)

    assert not game.is_on_battlefield(elk)
    (copy,) = _w2g2_named(game, 1, "Elk", token=True)
    assert (copy.effective_power, copy.effective_toughness) == (3, 3)


def test_w2g2_tranquility_takes_dual_nature_and_every_copy_it_made(set_pool):
    """A real sweep destroys the enchantment: its leave line exiles the copies
    it made on *both* sides of the table — "created with this enchantment"
    names a maker, not a controller — and the creatures they copied stay."""
    game = _w2g2_table()
    game.players[0].hand.append(set_pool("5ED")["Tranquility"])
    _w2g2_enter(game, 0, set_pool("PCY")["Dual Nature"])
    wolf = _w2g2_enter(game, 0, _w2g2_creature("Wolf", 3, 3))
    bear = _w2g2_enter(game, 1, _w2g2_creature("Bear", 2, 2))
    assert len(_w2g2_named(game, 0, "Wolf", token=True)) == 1
    assert len(_w2g2_named(game, 1, "Bear", token=True)) == 1

    result = game.cast_from_hand(0, "Tranquility")
    assert result.supported, result.details
    _w2g2_resolve(game)

    assert [c.name for c in game.players[0].graveyard].count("Dual Nature") == 1
    assert not [p for p in game.all_permanents() if p.metadata.get("is_token")]
    assert game.is_on_battlefield(wolf) and game.is_on_battlefield(bear)
