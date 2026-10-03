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
