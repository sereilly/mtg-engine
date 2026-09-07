"""Stronghold creatures.

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


# --- W1G1: damage prevention, redirection and damage-event triggers ---
import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec
from tests.helpers import _nosick, resolve_stack


def _w1g1_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g1_bear(name="Bear", power=2, toughness=2):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )


#: The sentence all five en-Kor creatures print, word for word.
_W1G1_EN_KOR = (
    "{0}: The next 1 damage that would be dealt to this creature this turn "
    "is dealt to target creature you control instead."
)
_W1G1_EN_KOR_NAMES = (
    "Lancers en-Kor", "Nomads en-Kor", "Shaman en-Kor", "Spirit en-Kor",
    "Warrior en-Kor",
)


@pytest.mark.parametrize("name", _W1G1_EN_KOR_NAMES)
def test_every_en_kor_compiles_the_shared_redirect(set_pool, name):
    """The set's largest cards-per-sentence cluster: five creatures, one printed
    line between them.

    Parametrized rather than written five times because that is the claim worth
    making — the production is the *sentence*, so a card that reached this
    behaviour by any other route (a hook, a near-miss template) would be a
    second implementation of one line. The payload assertion is the narrowing:
    "you control" is re-checked at resolution, and a description that lost it
    would let an en-Kor push its damage onto an opponent's creature.
    """
    card = set_pool("STH")[name]
    assert _W1G1_EN_KOR in card.oracle_text
    program = compile_card_oracle(card)

    assert program.supported
    ability = next(
        a for a in program.activated_abilities
        if a.instruction.kind == "redirect_next_damage_from_source_until_eot"
    )
    assert ability.instruction.payload["amount"] == 1
    assert ability.instruction.payload["targets"]["filter"] == {
        "type_filter": "creature", "controller": "you",
    }
    # The picker the activation raises, which is the other half of "you
    # control": an ability offering an opponent's creatures would let the
    # player announce a target the handler then refuses.
    assert derive_activation_spec(ability) == {"kind": "creature", "own_only": True}


def test_nomads_en_kor_moves_one_point_onto_the_creature_it_named(set_pool):
    """"{0}: The next 1 damage that would be dealt to this creature this turn is
    dealt to target creature you control instead."

    A redirect, not a shield: the damage is still dealt in full by the same
    source and only its recipient changes for the one point the record covers.
    So the assertion is on all three numbers — the point landing on the taker,
    nothing extra marked on the en-Kor, and the *remainder* staying where it was
    aimed. A record that ate the whole event would be a shield wearing a
    redirect's name, and free of a Kor that costs {0} to activate.
    """
    game = _w1g1_duel()
    p1, _ = game.players
    kor = _nosick(Permanent(card=set_pool("STH")["Nomads en-Kor"]))
    taker = _nosick(Permanent(card=_w1g1_bear("Taker", toughness=5)))
    p1.battlefield.extend([kor, taker])

    result = game.activate_permanent_ability(
        0, "Nomads en-Kor", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported

    game._mark_damage_on_permanent(kor, 3)

    assert taker.damage_marked == 1, "one point moved, as the card counts them"
    assert kor.damage_marked == 2, "and the rest landed where it was aimed"


def test_an_en_kor_can_only_aim_at_a_creature_its_controller_controls(set_pool):
    """"target creature **you control**" (CR 109.5: the activating player's
    "you").

    The printed narrowing is only done when something enforces it, and it is
    enforced twice — the picker offers one seat's creatures and the handler
    re-checks the phrase at resolution (CR 608.2b). This is the second half: an
    activation naming an opponent's creature redirects nothing rather than
    stapling a free damage-mover onto every board in the game.
    """
    game = _w1g1_duel()
    p1, p2 = game.players
    kor = _nosick(Permanent(card=set_pool("STH")["Warrior en-Kor"]))
    theirs = _nosick(Permanent(card=_w1g1_bear("Their Bear", toughness=5)))
    p1.battlefield.append(kor)
    p2.battlefield.append(theirs)

    game.activate_permanent_ability(
        0, "Warrior en-Kor", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game._mark_damage_on_permanent(kor, 3)

    assert theirs.damage_marked == 0
    assert kor.damage_marked == 3


def test_shaman_en_kor_moves_a_chosen_sources_damage_onto_itself(set_pool):
    """"{1}{W}: The next time a source of your choice would deal damage to
    target creature this turn, that damage is dealt to this creature instead."

    Two announcements in one activation, and the test is written to separate
    them: the **creature** is a target (CR 601.2c) and the **source** is
    CR 615.8's choice, which is not a target at all. Being a "next time" rather
    than a counted pool, the whole instance moves however large it is — three
    points here, so a record that carried an ``amount`` of 1 would leave two
    behind.

    Only the chosen source's damage moves. The second assertion is the one that
    matters: a record armed against every source would make one activation of a
    two-mana ability protect the creature from the whole turn.
    """
    game = _w1g1_duel()
    p1, p2 = game.players
    shaman = _nosick(Permanent(card=set_pool("STH")["Shaman en-Kor"]))
    friend = _nosick(Permanent(card=_w1g1_bear("Friend", toughness=5)))
    chosen = _nosick(Permanent(card=_w1g1_bear("Chosen Source")))
    bystander = _nosick(Permanent(card=_w1g1_bear("Bystander")))
    p1.battlefield.extend([shaman, friend])
    p2.battlefield.extend([chosen, bystander])

    program = compile_card_oracle(shaman.card)
    ability_index = next(
        i for i, a in enumerate(program.activated_abilities)
        if a.instruction.kind
        == "redirect_chosen_source_damage_off_target_until_eot"
    )
    result = game.activate_permanent_ability(
        0, "Shaman en-Kor", permanent_index=0, ability_index=ability_index,
        target_player_index=0, target_permanent_index=1,
        source_seat=1, source_permanent_index=0,
    )
    assert result.supported

    game._mark_damage_on_permanent(friend, 3, source=chosen)
    assert friend.damage_marked == 0, "the whole instance moved, not one point"
    assert shaman.damage_marked == 3

    game._mark_damage_on_permanent(friend, 2, source=bystander)
    assert friend.damage_marked == 2, "another source's damage is not the card's"
    assert shaman.damage_marked == 3


def _w1g1_block_with(game, wall, attacker_card, *, attacker_seat=1):
    """Run one combat where *attacker_card* attacks and *wall* blocks it.

    The whole point of the two Walls is what happens **in the combat damage
    step**, so the test drives one rather than calling the fire site: a trigger
    that fires from a hand-called seam and not from a real block is a card that
    works only in its own test.
    """
    defender = game.players[1 - attacker_seat]
    attacker_controller = game.players[attacker_seat]
    attacker = _nosick(Permanent(card=attacker_card))
    attacker_controller.battlefield.append(attacker)
    game.start_turn(attacker_seat)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    game.declare_attackers(attacker_seat, [attacker_controller.battlefield.index(attacker)])
    game.advance_combat_phase()   # declare blockers
    game.declare_blockers(
        1 - attacker_seat, {defender.battlefield.index(wall): 0},
    )
    game.advance_combat_phase()   # combat damage
    return attacker


def test_wall_of_essence_gains_life_for_the_combat_damage_it_takes(set_pool):
    """"Whenever this creature is dealt combat damage, you gain that much life."

    Driven through a real block, because "that much" is read out of the *event*
    — the trigger's context freezes what was dealt (CR 603.10), and by the time
    it resolves the marked damage may have been added to or wiped. A Wall that
    gained 0 would look identical to one whose trigger never fired.
    """
    game = _w1g1_duel()
    p1, _ = game.players
    wall = _nosick(Permanent(card=set_pool("STH")["Wall of Essence"]))
    p1.battlefield.append(wall)
    life = p1.life

    _w1g1_block_with(game, wall, _w1g1_bear("Hill Giant", power=3, toughness=3))
    resolve_stack(game)

    assert p1.life == life + 3
    assert wall.damage_marked == 3, "a gain, not a prevention"


def test_wall_of_essence_ignores_damage_that_was_not_combat_damage(set_pool):
    """The printed word is only done when something enforces it, and the
    failure is not a crash: it is a Wall that gains life off every Shock in the
    game, silently and in its controller's favour.

    The narrowing rides ``damage_combat`` on the condition — the same key the
    *dealing* side of this event already reads — and the fire site is where it
    is tested, because whether damage was combat damage is a fact of the event
    and not of the permanent.
    """
    game = _w1g1_duel()
    p1, _ = game.players
    wall = _nosick(Permanent(card=set_pool("STH")["Wall of Essence"]))
    p1.battlefield.append(wall)
    life = p1.life

    game._mark_damage_on_permanent(wall, 2)
    resolve_stack(game)

    assert p1.life == life
    assert wall.damage_marked == 2


def test_wall_of_souls_reflects_its_combat_damage_at_an_opponent(set_pool):
    """"Whenever this creature is dealt combat damage, it deals that much damage
    to target opponent or planeswalker."

    The Wall deals the damage, so the assertion is on the opponent's life *and*
    on the Wall keeping its own: a reading that moved the damage instead of
    reflecting it would leave a 0/4 undamaged and look like a success.
    """
    game = _w1g1_duel()
    p1, p2 = game.players
    wall = _nosick(Permanent(card=set_pool("STH")["Wall of Souls"]))
    p1.battlefield.append(wall)
    their_life = p2.life

    _w1g1_block_with(game, wall, _w1g1_bear("Hill Giant", power=3, toughness=3))
    resolve_stack(game)

    assert p2.life == their_life - 3
    assert wall.damage_marked == 3


def test_an_en_kor_aimed_at_itself_still_takes_the_whole_event(set_pool):
    """"target creature **you control**" includes the en-Kor, so aiming the
    ability at itself is a legal announcement (CR 601.2c) and a no-op — the
    damage is moved from the creature to the creature.

    Written because the AI does exactly this: every seeded simulation over this
    set has an en-Kor activating onto itself on turn 2. The record then points
    at the permanent it hangs off, which is the one shape that could recurse —
    a redirect deals its moved points as a fresh event, and that event asks the
    whole contention set again. ``DamageRedirect.applying`` is what stops it,
    and this is the test that says so.
    """
    game = _w1g1_duel()
    p1, _ = game.players
    kor = _nosick(Permanent(card=set_pool("STH")["Spirit en-Kor"]))
    p1.battlefield.append(kor)

    assert game.activate_permanent_ability(
        0, "Spirit en-Kor", permanent_index=0,
        target_player_index=0, target_permanent_index=0,
    ).supported

    game._mark_damage_on_permanent(kor, 3)

    assert kor.damage_marked == 3
