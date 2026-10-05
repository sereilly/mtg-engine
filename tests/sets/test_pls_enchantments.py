"""Planeshift enchantments.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G8: damage and the odd ones ---
#
# Lashknife Barrier's second line — "If a source would deal damage to a creature
# you control, it deals that much damage minus 1 to that creature instead." —
# is Benevolent Unicorn's sentence with both ends changed, and it arrived
# *supported* with that line unclaimed: the card compiled on its draw trigger
# alone. The source class and the protected recipients are parameters of the
# one CR 614 interceptor (``replacements._read_damage_delta``), never a second
# one.

from engine import Game as _w1g8e_Game, PlayerState as _w1g8e_Player  # noqa: E402
from engine.card_loader import (load_cards as _w1g8e_load,  # noqa: E402
                                manifest_set_path as _w1g8e_path)
from engine.control import change_control as _w1g8e_change_control  # noqa: E402
from engine.models import (CardDefinition as _w1g8e_Card,  # noqa: E402
                           Permanent as _w1g8e_Permanent)
from engine.oracle import compile_card_oracle as _w1g8e_compile  # noqa: E402
from engine.replacements import (  # noqa: E402
    damage_delta_recipients as _w1g8e_delta_recipients,
    replacement_claims_line as _w1g8e_claims,
    source_damage_delta as _w1g8e_delta,
)

from tests.helpers import (_damage_dealt as _w1g8e_dealt,  # noqa: E402
                           resolve_stack as _w1g8e_resolve_stack)


def _w1g8e_lea():
    return {card.name: card for card in _w1g8e_load(_w1g8e_path("LEA"))}


def _w1g8e_body(name, power, toughness, text="", keywords=()):
    """A bare creature for the other side of a damage event."""
    return _w1g8e_Card(
        name=name, mana_cost="{3}", cmc=3.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=tuple(keywords),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )  # W1G8 enchantments: a test body


def _w1g8e_duel(mine, theirs, *, hand0=(), hand1=(), active=0):
    """Both boards placed and unsick, *active* in its precombat main phase."""
    board0 = [_w1g8e_Permanent(card=card) for card in mine]
    board1 = [_w1g8e_Permanent(card=card) for card in theirs]
    filler = _w1g8e_body("Filler", 0, 1)
    game = _w1g8e_Game(players=[
        _w1g8e_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10),
        _w1g8e_Player(name="P1", battlefield=board1, hand=list(hand1),
                      library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._close_current_priority_step()
    return game, board0, board1  # W1G8 enchantments: the duel


def _w1g8e_fight(game, attacker_slot, blocker_slot, *, defender):
    """The active seat attacks with one creature, *defender* blocks it, and
    combat runs through to the second main phase."""
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(game.active_player_index, [attacker_slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocked = game.declare_blockers(defender, {blocker_slot: attacker_slot})
    assert blocked[0], blocked
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g8e_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # W1G8: fought


def test_w1g8_lashknife_barrier_claims_both_of_its_lines(set_pool):
    """The card was "supported" on the draw trigger with the replacement line
    read by nothing. Both readers of the sentence now answer for it, and the
    narrowing is read rather than dropped."""
    barrier = set_pool("PLS")["Lashknife Barrier"]
    line = barrier.oracle_text.splitlines()[1]

    assert _w1g8e_compile(barrier).supported
    assert _w1g8e_claims(line)
    assert _w1g8e_delta(line) == ("source", -1)
    assert _w1g8e_delta_recipients(line) == {
        "type_filter": "creature", "controller": "you",
    }
    # the unnarrowed printing names every recipient, so it carries no phrase
    assert _w1g8e_delta_recipients(
        "If a spell would deal damage to a permanent or player, it deals that "
        "much damage minus 1 to that permanent or player instead."
    ) is None
    # the two halves must name the same thing: a creature you control in front
    # and "that permanent or player" behind is not this sentence
    assert _w1g8e_delta(
        "If a source would deal damage to a creature you control, it deals "
        "that much damage minus 1 to that permanent or player instead."
    ) is None
    assert not _w1g8e_claims(
        "If a source would deal damage to a creature you control, it deals "
        "that much damage minus 1 to that permanent or player instead."
    )


def test_w1g8_lashknife_barrier_draws_on_entering(set_pool):
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, _, _ = _w1g8e_duel([], [], hand0=[barrier])

    cast = game.cast_from_hand(0, "Lashknife Barrier")
    assert cast.supported, cast.details
    _w1g8e_resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(0)] == ["Lashknife Barrier"]
    assert len(game.players[0].hand) == 1, "the entry trigger drew a card"


def test_w1g8_lashknife_barrier_shaves_a_burn_spell_aimed_at_its_creature(set_pool):
    """Three becomes two on the Barrier's controller's creature — and stays
    three on that player's face and on the other side's creature, because the
    sentence names "a creature you control" and nothing wider."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, theirs = _w1g8e_duel(
        [barrier, lea["Hill Giant"]], [lea["Hill Giant"]],
        hand1=[lea["Lightning Bolt"]] * 2, hand0=[lea["Lightning Bolt"]],
        active=1,
    )
    giant = mine[1]

    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[giant.permanent_id]
    ).supported
    _w1g8e_resolve_stack(game)
    game._settle()
    assert giant.damage_marked == 2
    assert game.is_on_battlefield(giant), "3 minus 1 does not kill a 3/3"

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8e_resolve_stack(game)
    assert game.players[0].life == 17, "a player is not a creature you control"

    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[theirs[0].permanent_id]
    ).supported
    _w1g8e_resolve_stack(game)
    game._settle()
    assert not game.is_on_battlefield(theirs[0]), (
        "the opponent's creature takes the printed three"
    )


def test_w1g8_lashknife_barrier_shaves_combat_damage(set_pool):
    """"A source" is every source: a 3/3 blocked by the Barrier's 3/3 deals it
    two and dies to the three it takes back."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, theirs = _w1g8e_duel(
        [barrier, lea["Hill Giant"]], [lea["Hill Giant"]], active=1,
    )

    _w1g8e_fight(game, 0, 1, defender=0)

    assert game.is_on_battlefield(mine[1])
    assert mine[1].damage_marked == 2
    assert not game.is_on_battlefield(theirs[0])


def test_w1g8_one_damage_reduced_to_none_is_not_dealt(set_pool):
    """CR 120.8: a source that would deal 0 damage deals none at all. The
    event's *dealt* number is 0, which is what lifelink gains from and what a
    "deals damage" trigger sees — a shield would have prevented 1 of 1 and
    still announced an event."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, theirs = _w1g8e_duel(
        [barrier, lea["Hill Giant"], lea["Prodigal Sorcerer"]],
        [lea["Prodigal Sorcerer"]], active=1,
    )
    giant = mine[1]

    # the opponent's pinger, and then the Barrier's controller's own
    for seat in (1, 0):
        used = game.activate_permanent_ability(
            seat, "Prodigal Sorcerer",
            target_permanent_ids=[giant.permanent_id], ability_index=0,
        )
        assert used.supported, used.details
        _w1g8e_resolve_stack(game)
    assert giant.damage_marked == 0
    assert _w1g8e_dealt(game, giant, 1, source=theirs[0]) == 0
    assert _w1g8e_dealt(game, giant, 1, source=theirs[0], combat=True) == 0


def test_w1g8_two_lashknife_barriers_each_take_a_point(set_pool):
    """CR 616.1 applies them one at a time in an order the creature's
    controller picks; subtraction commutes and the floor is reached only from
    above, so either order is minus 2 and never less than nothing."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, _ = _w1g8e_duel([barrier, barrier, lea["Hill Giant"]], [])
    giant = mine[2]

    assert _w1g8e_dealt(game, giant, 3) == 1
    assert _w1g8e_dealt(game, giant, 2) == 0
    assert _w1g8e_dealt(game, giant, 1) == 0


def test_w1g8_lashknife_barrier_is_per_recipient_and_per_controller(set_pool):
    """A mass damage event is one event per recipient (Earthquake for 2): each
    of the Barrier's side's creatures takes 1, the other side's take 2 and
    both players take 2. And "you control" is the Barrier's controller *now*
    (CR 109.5) — a creature that changes hands changes cover with it."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, theirs = _w1g8e_duel(
        [barrier, lea["Hill Giant"], lea["Hill Giant"]], [lea["Hill Giant"]],
        hand0=[lea["Earthquake"]],
    )

    cast = game.cast_from_hand(0, "Earthquake", x_value=2)
    assert cast.supported, cast.details
    _w1g8e_resolve_stack(game)

    assert [perm.damage_marked for perm in mine[1:]] == [1, 1]
    assert theirs[0].damage_marked == 2
    assert [player.life for player in game.players] == [18, 18]

    stolen = theirs[0]
    assert _w1g8e_dealt(game, stolen, 3) == 3
    _w1g8e_change_control(stolen, 0, source="test")
    game._sync_control()
    assert _w1g8e_dealt(game, stolen, 3) == 2
    _w1g8e_change_control(mine[1], 1, source="test")
    game._sync_control()
    assert _w1g8e_dealt(game, mine[1], 3) == 3
