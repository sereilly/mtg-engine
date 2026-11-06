"""Storm (CR 702.40), the triggered ability the keyword is.

    702.40a Storm is a triggered ability that functions on the stack. "Storm"
    means "When you cast this spell, copy it for each other spell that was
    cast before it this turn. If the spell has any targets, you may choose new
    targets for any of the copies."
    702.40b If a spell has multiple instances of storm, each triggers
    separately.

The printed reminder ("copy it for each spell cast before it this turn") is not
the rule; the rule's "**other** spell that was cast **before** it" is what is
tested. The count is the storm spell's own position in the turn's cast record
(``storm.spells_cast_before``): every player's spells, from any zone, countered
or not, none cast after it, and never a copy (CR 707.10: a copy of a spell is
not cast).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.storm import spells_cast_before
from tests.helpers import resolve_stack


def _card(set_pool, name):
    scg = set_pool("SCG")
    return scg[name] if name in scg else set_pool("LEA")[name]


def _table(set_pool, hand=(), opponent_hand=(), theirs=(), library=None):
    game = Game(players=[
        PlayerState(
            "A", hand=[_card(set_pool, n) for n in hand],
            library=[_card(set_pool, n) for n in (library or ["Forest"] * 12)],
        ),
        PlayerState(
            "B", hand=[_card(set_pool, n) for n in opponent_hand],
            library=[_card(set_pool, "Forest")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    placed = []
    for name in theirs:
        permanent = Permanent(card=_card(set_pool, name))
        game._put_permanent_onto_battlefield(1, permanent, None)
        placed.append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed


def _cast_and_resolve(game, seat, name, **kwargs):
    result = game.queue_from_hand(seat, name, **kwargs)
    assert result.supported, result.details
    resolve_stack(game)


@pytest.mark.cr("702.40a")
def test_702_40a_storm_counts_every_players_spells_from_any_zone(set_pool):
    """Both seats' spells count, a spell cast out of exile counts (Mind's
    Desire's card), and a spell that was countered counts (2022-12-08:
    "Spells cast from zones other than a player's hand and spells that were
    countered are counted by the storm ability")."""
    game, (wurm,) = _table(
        set_pool, ["Mind's Desire", "Lightning Bolt", "Scattershot"],
        opponent_hand=["Dark Ritual", "Counterspell"], theirs=["Craw Wurm"],
        library=["Giant Growth"] * 8,
    )
    _cast_and_resolve(game, 0, "Mind's Desire")            # 1 (its storm: 0)
    _cast_and_resolve(game, 0, "Giant Growth", from_zone="exile",
                      target_permanent_ids=[wurm.permanent_id])  # 2, from exile
    _cast_and_resolve(game, 1, "Dark Ritual")              # 3, the opponent's
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _cast_and_resolve(game, 1, "Counterspell", target_stack_index=0)  # 4 and 5
    assert game.players[1].life == 20  # the Bolt was countered
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[wurm.permanent_id]
    ).supported
    scattershot = game.stack[0]
    assert spells_cast_before(game, scattershot) == 5
    resolve_stack(game)
    assert wurm.damage_marked == 6


@pytest.mark.cr("702.40a", "707.10")
def test_702_40a_copies_are_not_cast_and_do_not_count(set_pool):
    """2022-12-08: "The copies are put directly onto the stack. They aren't
    cast and won't be counted by other spells with storm cast later in the
    turn." Two Scattershots after one Dark Ritual: the first makes one copy,
    the second counts the Ritual and the first Scattershot — two, not three."""
    game, (wurm,) = _table(
        set_pool, ["Dark Ritual", "Scattershot", "Scattershot"], theirs=["Craw Wurm"],
    )
    _cast_and_resolve(game, 0, "Dark Ritual")
    _cast_and_resolve(game, 0, "Scattershot", target_permanent_ids=[wurm.permanent_id])
    assert wurm.damage_marked == 2
    _cast_and_resolve(game, 0, "Scattershot", target_permanent_ids=[wurm.permanent_id])
    assert wurm.damage_marked == 2 + 3


@pytest.mark.cr("702.40a")
def test_702_40a_a_spell_cast_after_it_is_not_counted(set_pool):
    """A spell cast in response to the storm trigger was cast after the storm
    spell: the count is fixed by the cast, though the trigger resolves later."""
    game, (wurm,) = _table(
        set_pool, ["Dark Ritual", "Scattershot"],
        opponent_hand=["Dark Ritual", "Dark Ritual"], theirs=["Craw Wurm"],
    )
    _cast_and_resolve(game, 0, "Dark Ritual")
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[wurm.permanent_id]
    ).supported
    for _ in range(2):
        assert game.queue_from_hand(1, "Dark Ritual").supported
        assert game.resolve_top_of_stack()
    resolve_stack(game)
    assert wurm.damage_marked == 2


@pytest.mark.cr("702.40a")
def test_702_40a_last_turns_spells_are_not_counted(set_pool):
    """"…cast before it **this turn**": the record is the turn's."""
    game, (wurm,) = _table(
        set_pool, ["Dark Ritual", "Scattershot"], theirs=["Craw Wurm"],
    )
    _cast_and_resolve(game, 0, "Dark Ritual")
    game.start_next_turn()
    game.start_next_turn()
    assert game.active_player_index == 0
    _cast_and_resolve(game, 0, "Scattershot", target_permanent_ids=[wurm.permanent_id])
    assert wurm.damage_marked == 1


@pytest.mark.cr("702.40a")
def test_702_40a_storm_is_a_triggered_ability_on_the_stack(set_pool):
    """It goes on the stack above its spell as the spell becomes cast, and it
    is an object a player can respond to: countered (Stifle), it makes no copy
    and the spell still resolves."""
    game, (wurm,) = _table(
        set_pool, ["Dark Ritual", "Dark Ritual", "Scattershot"],
        opponent_hand=["Stifle"], theirs=["Craw Wurm"],
    )
    _cast_and_resolve(game, 0, "Dark Ritual")
    _cast_and_resolve(game, 0, "Dark Ritual")
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[wurm.permanent_id]
    ).supported
    spell, trigger = game.stack
    assert trigger.ability_kind == "triggered" and trigger.card is spell.card
    _cast_and_resolve(game, 1, "Stifle", target_stack_index=1)
    assert wurm.damage_marked == 1


@pytest.mark.cr("702.40b")
def test_702_40b_two_instances_of_storm_each_trigger(set_pool):
    """A spell with two instances makes two triggers, each copying it once per
    spell before it: with one spell before it, two copies."""
    double = CardDefinition(
        name="Twin Squall", mana_cost="{R}", cmc=1.0, type_line="Instant",
        oracle_text="Twin Squall deals 1 damage to target creature.\nStorm\nStorm",
        colors=("R",), color_identity=("R",), keywords=("Storm",),
        produced_mana=(), raw={"name": "Twin Squall", "type_line": "Instant"},
    )
    program = compile_card_oracle(double)
    assert program.supported, program.reason
    assert [t.condition.kind for t in program.triggered_abilities] == ["self_cast"] * 2
    game, (wurm,) = _table(set_pool, ["Dark Ritual"], theirs=["Craw Wurm"])
    game.players[0].hand.append(double)
    _cast_and_resolve(game, 0, "Dark Ritual")
    assert game.queue_from_hand(
        0, "Twin Squall", target_permanent_ids=[wurm.permanent_id]
    ).supported
    assert [item.ability_kind for item in game.stack[1:]] == ["triggered"] * 2
    resolve_stack(game)
    assert wurm.damage_marked == 3


@pytest.mark.cr("702.40a", "707.10c")
def test_702_40a_each_copy_may_choose_its_own_new_target(set_pool):
    """"…you may choose new targets for any of the copies": one offer per copy
    to the copy's controller, each answered on its own."""
    game, bears = _table(
        set_pool, ["Dark Ritual", "Dark Ritual", "Tendrils of Agony"],
    )
    game.interactive_seats = {0}
    _cast_and_resolve(game, 0, "Dark Ritual")
    _cast_and_resolve(game, 0, "Dark Ritual")
    assert game.queue_from_hand(0, "Tendrils of Agony", target_player_index=1).supported
    assert game.resolve_top_of_stack()
    offers = [choice for choice in game.pending_choices if choice.kind == "copy_spell_target"]
    assert len(offers) == 2
    # One copy aimed at the caster (a choice nobody would make, which is what
    # shows it is a choice), one left where it was.
    assert game.confirm_copy_spell_target(0, target_seat=0)
    assert game.confirm_copy_spell_target(0, target_seat=1)
    resolve_stack(game)
    # Original and one copy drain B (2 each); the other drains A and gains A 2.
    assert [player.life for player in game.players] == [20 + 6 - 2, 20 - 4]
