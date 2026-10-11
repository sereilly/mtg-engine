"""Apocalypse sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.color_changes import change_color as _w1g2_change_color
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand=(), mana=None, opp_hand=(), opp_mana=None):
    """A two-seat game with mana costs enforced. *hand* names Apocalypse cards
    (or Alpha ones, for a hand that has to hold something to discard);
    *opp_hand* is Alpha."""
    lea, apc = set_pool("LEA"), set_pool("APC")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[apc[name] if name in apc else lea[name] for name in hand],
        ),
        _W1G2PlayerState(
            "Opponent", library=[lea["Forest"]] * 10,
            hand=[lea[name] for name in opp_hand],
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    game.players[1].mana_pool.update(opp_mana or {})
    return game  # _w1g2_table (sorceries)


def _w1g2_put(game, set_pool, seat, name, code="LEA"):
    """*name* onto *seat*'s battlefield, able to act this turn."""
    permanent = _W1G2Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put (sorceries)


def _w1g2_saprolings(game, seat=0):
    return [
        permanent for permanent in game.controlled_by(seat)
        if permanent.card.name == "Saproling Token"
    ]  # _w1g2_saprolings


# Last Stand -----------------------------------------------------------------

_W1G2_LAST_STAND_LANDS = (
    ("Swamp", 2), ("Mountain", 3), ("Forest", 1), ("Plains", 2), ("Island", 2),
)


def _w1g2_last_stand_table(set_pool, lands=_W1G2_LAST_STAND_LANDS):
    """Last Stand and three other cards in hand, {W}{U}{B}{R}{G} in the pool,
    and *lands* under the caster. The opponent has a Hill Giant and a Swamp
    and an Island of their own, which the card must not count."""
    game = _w1g2_table(
        set_pool, ["Last Stand", "Grizzly Bears", "Hill Giant", "Shatter"],
        {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1},
    )
    for name, count in lands:
        for _ in range(count):
            _w1g2_put(game, set_pool, 0, name)
    giant = _w1g2_put(game, set_pool, 1, "Hill Giant")
    _w1g2_put(game, set_pool, 1, "Swamp")
    _w1g2_put(game, set_pool, 1, "Island")
    return game, giant  # _w1g2_last_stand_table


def test_w1g2_last_stand_counts_each_of_its_controllers_basic_land_types(set_pool):
    """All five sentences, each sized by a different land type the caster
    controls: two Swamps cost the opponent 4 life, three Mountains deal 3 to
    the Hill Giant, one Forest makes one Saproling, two Plains gain 4, and two
    Islands draw two cards and then owe a discard of that many. The opponent's
    own Swamp and Island are counted for nothing."""
    game, giant = _w1g2_last_stand_table(set_pool)

    result = game.cast_from_hand(
        0, "Last Stand", target_player_index=1,
        target_permanent_ids=[None, giant.permanent_id],
    )
    _w1g2_resolve_stack(game)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert [player.life for player in game.players] == [24, 16]
    assert not game.is_on_battlefield(giant)
    assert "Last Stand dealt 3 damage to Hill Giant" in game.log
    assert len(_w1g2_saprolings(game)) == 1
    # Three cards were left in hand, two were drawn — and two are owed back.
    assert len(game.players[0].hand) == 5
    (owed,) = game.pending_choices
    assert (owed.kind, owed.player_index, owed.data["count"]) == ("discard", 0, 2)

    game.auto_resolve_pending_choices()

    assert len(game.players[0].hand) == 3
    assert "Last Stand" in [card.name for card in game.players[0].graveyard]
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g2_last_stand_with_no_basic_lands_does_nothing_at_all(set_pool):
    """Every amount is a count, and every count can be zero: no life lost or
    gained, no damage, no token, no card drawn and none discarded."""
    game, giant = _w1g2_last_stand_table(set_pool, lands=())

    result = game.cast_from_hand(
        0, "Last Stand", target_player_index=1,
        target_permanent_ids=[None, giant.permanent_id],
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert [player.life for player in game.players] == [20, 20]
    assert giant.damage_marked == 0
    assert not _w1g2_saprolings(game)
    assert len(game.players[0].hand) == 3 and not game.pending_choices


def test_w1g2_last_stand_announces_an_opponent_and_a_creature(set_pool):
    """Two targets of different kinds, one announcement (CR 601.2c): the
    caster is no opponent of theirs, the creature slot may not be left empty,
    and a land is not a creature. Nothing is spent on a refusal."""
    game, giant = _w1g2_last_stand_table(set_pool)
    land = next(iter(game.controlled_by(0)))
    spec = game.cast_target_spec(0, set_pool("APC")["Last Stand"])
    assert [role["kind"] for role in spec["roles"]] == ["player", "creature"]
    assert [target["seat"] for target in spec["valid_targets"]] == [1]

    for seat, ids in (
        (0, [None, giant.permanent_id]),
        (1, [None, None]),
        (1, [None, land.permanent_id]),
    ):
        assert not game.cast_from_hand(
            0, "Last Stand", target_player_index=seat, target_permanent_ids=ids,
        ).supported, (seat, ids)

    assert sum(game.players[0].mana_pool.values()) == 5
    assert [player.life for player in game.players] == [20, 20]


def test_w1g2_last_stand_still_resolves_for_the_player_when_the_creature_left(
    set_pool,
):
    """CR 608.2b: one illegal target of two leaves the spell resolving for the
    rest. The Hill Giant is gone, so nothing is dealt 3 — and the opponent
    still loses 4, the Saproling still arrives and the life is still gained."""
    game, giant = _w1g2_last_stand_table(set_pool)
    game.queue_from_hand(
        0, "Last Stand", target_player_index=1,
        target_permanent_ids=[None, giant.permanent_id],
    )
    game.remove_from_battlefield(giant)

    _w1g2_resolve_stack(game)

    assert [player.life for player in game.players] == [24, 16]
    assert len(_w1g2_saprolings(game)) == 1
    assert not any("dealt 3 damage" in line for line in game.log)


# Dead Ringers ---------------------------------------------------------------


def _w1g2_ringers_table(set_pool, first, second):
    """Dead Ringers in hand; *first* and *second* across the table beside a
    black creature, which "nonblack" keeps out of the picker."""
    game = _w1g2_table(set_pool, ["Dead Ringers"], {"B": 5})
    one = _w1g2_put(game, set_pool, 1, first)
    other = _w1g2_put(game, set_pool, 1, second)
    _w1g2_put(game, set_pool, 1, "Scathe Zombies")
    return game, one, other  # _w1g2_ringers_table


@_w1g2_pytest.mark.parametrize("first, second, destroyed", [
    ("Pearled Unicorn", "Savannah Lions", True),     # white and white
    ("Juggernaut", "Obsianus Golem", True),          # colourless and colourless
    ("Pearled Unicorn", "Grizzly Bears", False),     # white and green
    ("Juggernaut", "Grizzly Bears", False),          # colourless and green
])
def test_w1g2_dead_ringers_destroys_two_creatures_of_exactly_the_same_colours(
    set_pool, first, second, destroyed,
):
    """"Destroy two target nonblack creatures unless either one is a color the
    other isn't." The card's ruling: "Both of the target creatures must be
    exactly the same color or combination of colors. Both being colorless is
    also okay. If they differ in any way, you can still cast the spell, but it
    does not do anything on resolution." """
    game, one, other = _w1g2_ringers_table(set_pool, first, second)

    result = game.cast_from_hand(
        0, "Dead Ringers", target_permanent_ids=[one.permanent_id, other.permanent_id],
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert game.is_on_battlefield(one) is (not destroyed)
    assert game.is_on_battlefield(other) is (not destroyed)
    assert sum(game.players[0].mana_pool.values()) == 0
    assert "Dead Ringers" in [card.name for card in game.players[0].graveyard]


def test_w1g2_dead_ringers_names_exactly_two_different_nonblack_creatures(set_pool):
    """The picker offers the two white creatures and not the black one; one
    target, a black target, the same creature twice and three targets are each
    refused with nothing spent — and with a single nonblack creature on the
    table the spell cannot be cast at all."""
    game, one, other = _w1g2_ringers_table(set_pool, "Pearled Unicorn", "Savannah Lions")
    zombies = next(p for p in game.controlled_by(1) if p.card.name == "Scathe Zombies")
    card = set_pool("APC")["Dead Ringers"]
    spec = game.cast_target_spec(0, card)
    assert sorted(target["name"] for target in spec["valid_targets"]) == [
        "Pearled Unicorn", "Savannah Lions",
    ]
    assert spec["exact_targets"] and spec["max_targets"] == 2

    for ids in (
        [one.permanent_id],
        [one.permanent_id, zombies.permanent_id],
        [one.permanent_id, one.permanent_id],
        [one.permanent_id, other.permanent_id, zombies.permanent_id],
        [],
    ):
        assert not game.cast_from_hand(
            0, "Dead Ringers", target_permanent_ids=ids,
        ).supported, ids
    assert sum(game.players[0].mana_pool.values()) == 5

    game.remove_from_battlefield(other)
    assert game.no_legal_cast_target_refusal(0, card) is not None


def test_w1g2_dead_ringers_reads_the_colours_as_it_resolves(set_pool):
    """The ruling's second line: "Colors are checked on resolution." Two white
    creatures, one turned green in response, are not destroyed; a white and a
    green one, the green turned white in response, are."""
    game, one, other = _w1g2_ringers_table(set_pool, "Pearled Unicorn", "Savannah Lions")
    game.queue_from_hand(
        0, "Dead Ringers", target_permanent_ids=[one.permanent_id, other.permanent_id],
    )
    _w1g2_change_color(one, ("G",), until_eot=True)
    _w1g2_resolve_stack(game)
    assert game.is_on_battlefield(one) and game.is_on_battlefield(other)

    game, one, other = _w1g2_ringers_table(set_pool, "Pearled Unicorn", "Grizzly Bears")
    game.queue_from_hand(
        0, "Dead Ringers", target_permanent_ids=[one.permanent_id, other.permanent_id],
    )
    _w1g2_change_color(other, ("W",), until_eot=True)
    _w1g2_resolve_stack(game)
    assert not game.is_on_battlefield(one) and not game.is_on_battlefield(other)


def test_w1g2_dead_ringers_cannot_compare_a_target_that_became_illegal(set_pool):
    """CR 608.2b: "If part of the effect requires information about an illegal
    target, it fails to determine any such information." One of two white
    creatures is given protection from black in response (Mother of Runes), so
    it is no longer a legal target — and the other, still white and still
    targeted, is not destroyed on the strength of a comparison nobody could
    make. The same when a target simply left."""
    game, one, other = _w1g2_ringers_table(set_pool, "Pearled Unicorn", "Savannah Lions")
    _w1g2_put(game, set_pool, 1, "Mother of Runes", code="ULG")
    game.interactive_seats = {1}
    game.queue_from_hand(
        0, "Dead Ringers", target_permanent_ids=[one.permanent_id, other.permanent_id],
    )
    assert game.queue_permanent_ability(
        1, "Mother of Runes", target_player_index=1,
        target_permanent_ids=[one.permanent_id],
    ).supported
    game.resolve_top_of_stack()
    assert game.confirm_color_choice(1, "B")
    game.interactive_seats = set()

    _w1g2_resolve_stack(game)

    assert game._protection_colors(one) == {"B"}
    assert game.is_on_battlefield(one) and game.is_on_battlefield(other)
    assert "Dead Ringers" in [card.name for card in game.players[0].graveyard]

    game, one, other = _w1g2_ringers_table(set_pool, "Pearled Unicorn", "Savannah Lions")
    game.queue_from_hand(
        0, "Dead Ringers", target_permanent_ids=[one.permanent_id, other.permanent_id],
    )
    game.remove_from_battlefield(one)
    _w1g2_resolve_stack(game)
    assert game.is_on_battlefield(other)


def test_w1g2_dead_ringers_victims_cannot_be_regenerated(set_pool):
    """"They can't be regenerated." A regeneration shield on each of the two
    saves neither (CR 701.19c)."""
    game, one, other = _w1g2_ringers_table(set_pool, "Pearled Unicorn", "Savannah Lions")
    one.regeneration_shield = other.regeneration_shield = 1

    game.cast_from_hand(
        0, "Dead Ringers", target_permanent_ids=[one.permanent_id, other.permanent_id],
    )
    _w1g2_resolve_stack(game)

    assert sorted(card.name for card in game.players[1].graveyard) == [
        "Pearled Unicorn", "Savannah Lions",
    ]


# Illuminate -----------------------------------------------------------------


@_w1g2_pytest.mark.parametrize("red, blue", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_w1g2_illuminate_does_what_each_of_its_two_kickers_bought(set_pool, red, blue):
    """"Kicker {2}{R} and/or {3}{U}" (CR 702.33b). X = 2 at a Craw Wurm: the
    creature always takes 2; its controller takes 2 only for the {2}{R}
    kicker, and the caster draws 2 only for the {3}{U} one — each paid for
    separately (CR 702.33f)."""
    game = _w1g2_table(set_pool, ["Illuminate"], {"R": 6, "U": 6})
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    payments = {
        **({"{2}{R}": 1} if red else {}), **({"{3}{U}": 1} if blue else {}),
    }

    result = game.cast_from_hand(
        0, "Illuminate", x_value=2, target_permanent_ids=[wurm.permanent_id],
        optional_cost_payments=payments or None,
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert wurm.damage_marked == 2
    assert game.players[1].life == (18 if red else 20)
    assert len(game.players[0].hand) == (2 if blue else 0)
    spent = 3 + (3 if red else 0) + (4 if blue else 0)
    assert sum(game.players[0].mana_pool.values()) == 12 - spent


def test_w1g2_illuminate_fully_kicked_does_nothing_once_its_creature_is_gone(set_pool):
    """One target, and both kicked sentences hang off it: with the creature
    gone the spell leaves the stack unresolved (CR 608.2b), so "that
    creature's controller" takes nothing and no card is drawn. And it needs a
    creature to be cast at — a land is not one."""
    game = _w1g2_table(set_pool, ["Illuminate"], {"R": 6, "U": 6})
    land = _w1g2_put(game, set_pool, 1, "Mountain")
    assert not game.cast_from_hand(0, "Illuminate", x_value=2).supported
    assert not game.cast_from_hand(
        0, "Illuminate", x_value=2, target_permanent_ids=[land.permanent_id],
    ).supported

    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    game.queue_from_hand(
        0, "Illuminate", x_value=2, target_permanent_ids=[wurm.permanent_id],
        optional_cost_payments={"{2}{R}": 1, "{3}{U}": 1},
    )
    game.remove_from_battlefield(wurm)
    _w1g2_resolve_stack(game)

    assert game.players[1].life == 20
    assert not game.players[0].hand


# Dwarven Landslide ----------------------------------------------------------

#: The key the cast offers Dwarven Landslide's kicker under — "Kicker—{2}{R},
#: Sacrifice a land." is one optional additional cost with two halves.
_W1G2_LANDSLIDE_KICKER = "pay {2}{r}, sacrifice a land"


def test_w1g2_dwarven_landslide_unkicked_destroys_one_land(set_pool):
    game = _w1g2_table(set_pool, ["Dwarven Landslide"], {"R": 7})
    mine = _w1g2_put(game, set_pool, 0, "Mountain")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    island = _w1g2_put(game, set_pool, 1, "Island")
    offers = game.cast_target_spec(0, set_pool("APC")["Dwarven Landslide"])["cost_offers"]
    assert [offer["symbols"] for offer in offers] == [_W1G2_LANDSLIDE_KICKER]

    result = game.cast_from_hand(
        0, "Dwarven Landslide", target_permanent_ids=[forest.permanent_id],
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert not game.is_on_battlefield(forest)
    assert game.is_on_battlefield(island) and game.is_on_battlefield(mine)
    assert game.players[0].mana_pool["R"] == 3


def test_w1g2_dwarven_landslide_kicked_costs_a_land_and_destroys_two(set_pool):
    """"Kicker—{2}{R}, Sacrifice a land." Kicked, the caster pays seven mana
    and the land they name, and both of the opponent's lands are destroyed."""
    game = _w1g2_table(set_pool, ["Dwarven Landslide"], {"R": 7})
    mountain = _w1g2_put(game, set_pool, 0, "Mountain")
    plains = _w1g2_put(game, set_pool, 0, "Plains")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    island = _w1g2_put(game, set_pool, 1, "Island")

    result = game.cast_from_hand(
        0, "Dwarven Landslide",
        target_permanent_ids=[forest.permanent_id, island.permanent_id],
        optional_cost_payments={_W1G2_LANDSLIDE_KICKER: 1},
        cost_permanent_ids=[plains.permanent_id],
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert "Caster sacrificed Plains to cast Dwarven Landslide" in game.log
    assert game.is_on_battlefield(mountain) and not game.is_on_battlefield(plains)
    assert sorted(card.name for card in game.players[1].graveyard) == ["Forest", "Island"]
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g2_dwarven_landslide_cannot_be_kicked_without_its_whole_cost(set_pool):
    """Both halves of the kicker are owed (CR 601.2h): with no land to
    sacrifice, or with four mana, the kicked cast is refused and nothing is
    paid; and a kicked cast owes its second target."""
    game = _w1g2_table(set_pool, ["Dwarven Landslide"], {"R": 7})
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    island = _w1g2_put(game, set_pool, 1, "Island")
    both = [forest.permanent_id, island.permanent_id]
    kicked = {_W1G2_LANDSLIDE_KICKER: 1}

    assert not game.cast_from_hand(
        0, "Dwarven Landslide", target_permanent_ids=both,
        optional_cost_payments=kicked,
    ).supported, "no land to sacrifice"
    _w1g2_put(game, set_pool, 0, "Mountain")
    assert not game.cast_from_hand(
        0, "Dwarven Landslide", target_permanent_ids=[forest.permanent_id],
        optional_cost_payments=kicked,
    ).supported, "a kicked cast names two lands"
    game.players[0].mana_pool["R"] = 4
    assert not game.cast_from_hand(
        0, "Dwarven Landslide", target_permanent_ids=both,
        optional_cost_payments=kicked,
    ).supported, "seven mana, not four"

    assert game.players[0].mana_pool["R"] == 4
    assert game.is_on_battlefield(forest) and game.is_on_battlefield(island)
    assert len(list(game.controlled_by(0))) == 1


# Death Grasp ----------------------------------------------------------------


def test_w1g2_death_grasp_deals_x_and_gains_x(set_pool):
    """"Death Grasp deals X damage to any target. You gain X life." At a
    creature for 4, and at a face for 3 with the unspent mana left over."""
    game = _w1g2_table(set_pool, ["Death Grasp"], {"W": 1, "B": 5})
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    assert game.cast_from_hand(
        0, "Death Grasp", x_value=4, target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(wurm)
    assert [player.life for player in game.players] == [24, 20]
    assert sum(game.players[0].mana_pool.values()) == 0

    game = _w1g2_table(set_pool, ["Death Grasp"], {"W": 1, "B": 5})
    assert game.cast_from_hand(0, "Death Grasp", x_value=3, target_player_index=1).supported
    _w1g2_resolve_stack(game)
    assert [player.life for player in game.players] == [23, 17]
    assert sum(game.players[0].mana_pool.values()) == 1


def test_w1g2_death_grasp_gains_nothing_when_its_target_is_gone(set_pool):
    """One target, so CR 608.2b takes the whole spell: no damage and no life.
    And a creature with protection from white is not a legal target for a
    white-and-black spell (CR 702.16b)."""
    game = _w1g2_table(set_pool, ["Death Grasp"], {"W": 1, "B": 5})
    knight = _w1g2_put(game, set_pool, 1, "Black Knight")
    assert not game.cast_from_hand(
        0, "Death Grasp", x_value=3, target_permanent_ids=[knight.permanent_id],
    ).supported

    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    game.queue_from_hand(
        0, "Death Grasp", x_value=3, target_permanent_ids=[wurm.permanent_id],
    )
    game.remove_from_battlefield(wurm)
    _w1g2_resolve_stack(game)

    assert [player.life for player in game.players] == [20, 20]


# Aether Mutation / Death Mutation -------------------------------------------


def test_w1g2_aether_mutation_makes_a_saproling_for_each_point_of_mana_value(set_pool):
    """"Return target creature to its owner's hand. Create X 1/1 green
    Saproling creature tokens, where X is that creature's mana value." The
    Craw Wurm is in its owner's hand by the time the tokens are counted, so
    the number is its last known mana value, six (CR 608.2h) — this card
    arrived "supported" and made none."""
    game = _w1g2_table(set_pool, ["Aether Mutation"], {"G": 3, "U": 2})
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")

    result = game.cast_from_hand(
        0, "Aether Mutation", target_permanent_ids=[wurm.permanent_id],
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert [card.name for card in game.players[1].hand] == ["Craw Wurm"]
    tokens = _w1g2_saprolings(game)
    assert len(tokens) == 6
    assert {(t.effective_power, t.effective_toughness) for t in tokens} == {(1, 1)}
    assert all(t.effective_colors == {"G"} for t in tokens)


def test_w1g2_aether_mutation_on_its_casters_own_creature_and_on_none(set_pool):
    """The caster's own two-drop comes back to their hand and leaves two
    Saprolings; with the target gone before resolution the spell does nothing
    (CR 608.2b), tokens included."""
    game = _w1g2_table(set_pool, ["Aether Mutation"], {"G": 3, "U": 2})
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    game.cast_from_hand(0, "Aether Mutation", target_permanent_ids=[bears.permanent_id])
    _w1g2_resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]
    assert len(_w1g2_saprolings(game)) == 2

    game = _w1g2_table(set_pool, ["Aether Mutation"], {"G": 3, "U": 2})
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    game.queue_from_hand(0, "Aether Mutation", target_permanent_ids=[wurm.permanent_id])
    game.remove_from_battlefield(wurm)
    _w1g2_resolve_stack(game)
    assert not _w1g2_saprolings(game)


def test_w1g2_death_mutation_destroys_through_regeneration_and_counts_what_died(
    set_pool,
):
    """"Destroy target nonblack creature. It can't be regenerated. Create X
    1/1 green Saproling creature tokens, where X is that creature's mana
    value." A regeneration shield does not save the Wurm, six Saprolings
    arrive for a creature that is already in the graveyard (CR 608.2h), and a
    black creature was never a legal target."""
    game = _w1g2_table(set_pool, ["Death Mutation"], {"G": 4, "B": 4})
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    zombies = _w1g2_put(game, set_pool, 1, "Scathe Zombies")
    wurm.regeneration_shield = 1
    assert not game.cast_from_hand(
        0, "Death Mutation", target_permanent_ids=[zombies.permanent_id],
    ).supported

    result = game.cast_from_hand(
        0, "Death Mutation", target_permanent_ids=[wurm.permanent_id],
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert [card.name for card in game.players[1].graveyard] == ["Craw Wurm"]
    assert len(_w1g2_saprolings(game)) == 6
    assert game.is_on_battlefield(zombies)


# Divine Light ---------------------------------------------------------------


def test_w1g2_divine_light_shields_its_casters_creatures_and_nobody_else(set_pool):
    """"Prevent all damage that would be dealt this turn to creatures you
    control." A Bolt at the caster's Bears is prevented; so is one at a Hill
    Giant that arrived after the spell resolved (CR 611.2c — a prevention
    effect changes no characteristic, so its set is not locked in). The
    caster's own face and the opponent's creature are not covered."""
    game = _w1g2_table(
        set_pool, ["Divine Light"], {"W": 1},
        opp_hand=["Lightning Bolt"] * 4, opp_mana={"R": 4},
    )
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    lions = _w1g2_put(game, set_pool, 1, "Savannah Lions")
    assert game.cast_from_hand(0, "Divine Light").supported
    _w1g2_resolve_stack(game)
    giant = _w1g2_put(game, set_pool, 0, "Hill Giant")

    for seat, permanent in ((0, bears), (0, giant), (1, lions), (0, None)):
        assert game.cast_from_hand(
            1, "Lightning Bolt", target_player_index=seat,
            **({"target_permanent_ids": [permanent.permanent_id]} if permanent else {}),
        ).supported
    game.check_state_based_actions()

    assert (bears.damage_marked, giant.damage_marked) == (0, 0)
    assert game.is_on_battlefield(bears) and game.is_on_battlefield(giant)
    assert "Divine Light prevented 3 damage to Grizzly Bears" in game.log
    assert not game.is_on_battlefield(lions)
    assert game.players[0].life == 17

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
