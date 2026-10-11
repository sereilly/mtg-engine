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

from engine import Game as _w1g3s_Game, PlayerState as _w1g3s_Player
from engine.game_types import CardDefinition as _w1g3s_CardDefinition


def _w1g3s_index_game(set_pool, size, *, interactive=()):
    """Index in seat 0's hand over a library of *size* numbered cards."""
    library = [
        _w1g3s_CardDefinition(
            name=f"Card {n}", mana_cost="", cmc=0.0, type_line="Land",
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=(), raw={"name": f"Card {n}", "type_line": "Land"},
        )
        for n in range(1, size + 1)
    ]
    game = _w1g3s_Game(players=[
        _w1g3s_Player(name="P0", hand=[set_pool("APC")["Index"]], library=library),
        _w1g3s_Player(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game  # W1G3 sorceries: the Index game


def test_w1g3_index_puts_the_top_five_back_in_the_order_its_caster_chooses(set_pool):
    """"Look at the top five cards of your library, then put them back in any
    order." The caster is shown five of six and asked for an order; a
    permutation of the wrong length is refused, the answer is the new top of
    the library, and the sixth card stays sixth. Nothing is drawn."""
    game = _w1g3s_index_game(set_pool, 6, interactive={0})
    me = game.players[0]

    assert game.cast_from_hand(0, "Index").supported

    waiting = game.waiting_prompt()
    assert waiting is not None and waiting.kind == "reorder_library"
    assert waiting.data["top_count"] == 5 and waiting.data.get("position") is None
    assert [c.name for c in game.reorder_library_pile(waiting)] == [
        f"Card {n}" for n in range(1, 6)
    ]
    assert [item.card.name for item in game.stack] == ["Index"]

    assert not game.confirm_reorder_library(0, [0, 1, 2])
    assert not game.confirm_reorder_library(0, [5, 4, 3, 2, 1])
    assert game.confirm_reorder_library(0, [4, 3, 2, 1, 0])
    game._settle()

    assert [c.name for c in me.library] == [
        "Card 5", "Card 4", "Card 3", "Card 2", "Card 1", "Card 6",
    ]
    assert me.hand == [] and game.stack == []
    assert [c.name for c in me.graveyard] == ["Index"]


def test_w1g3_index_over_a_short_library_orders_what_is_there(set_pool):
    """Three cards are looked at when three is all there is (CR 609.3), and
    one card has no order to choose: nothing is asked and the spell resolves."""
    game = _w1g3s_index_game(set_pool, 3, interactive={0})
    assert game.cast_from_hand(0, "Index").supported
    assert game.waiting_prompt().data["top_count"] == 3
    assert game.confirm_reorder_library(0, [1, 2, 0])
    game._settle()
    assert [c.name for c in game.players[0].library] == ["Card 2", "Card 3", "Card 1"]

    game = _w1g3s_index_game(set_pool, 1, interactive={0})
    assert game.cast_from_hand(0, "Index").supported
    assert game.pending_choices == [] and game.stack == []
    assert [c.name for c in game.players[0].library] == ["Card 1"]
    assert [c.name for c in game.players[0].graveyard] == ["Index"]

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4s_pytest  # noqa: E402

from engine import Game as _w1g4s_Game, PlayerState as _w1g4s_Player  # noqa: E402
from engine.grammar import compile_line as _w1g4s_compile_line  # noqa: E402
from engine.models import Permanent as _w1g4s_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w1g4s_compile  # noqa: E402

from tests.helpers import resolve_stack as _w1g4s_resolve_stack  # noqa: E402

#: Where a name in these tests is looked for, in order. One pool per card, as
#: `tests/sets/README.md` asks; the order only matters for a reprint, and every
#: basic land resolves to Alpha's.
_W1G4S_POOLS = ("APC", "LEA", "ATQ", "MIR")


def _w1g4s_card(set_pool, name):
    """*name* out of the first of this section's pools that prints it."""
    for code in _W1G4S_POOLS:
        found = set_pool(code).get(name)
        if found is not None:
            return found
    raise KeyError(name)  # W1G4 sorceries: no pool here prints that name


def _w1g4s_table(set_pool, *, mine=(), theirs=(), hand0=(), hand1=(), lib0=(),
                 lib1=(), gy0=(), gy1=(), interactive=(), seats=2):
    """A duel (or a table of *seats*) with seat 0 in its precombat main phase.

    Every zone is named card by card, so a test reads as the board it is about;
    libraries are top first. Costs are not enforced unless a test turns them on.
    """
    def cards(names):
        return [_w1g4s_card(set_pool, name) for name in names]

    boards = [
        [_w1g4s_Permanent(card=card) for card in cards(mine)],
        [_w1g4s_Permanent(card=card) for card in cards(theirs)],
    ]
    players = [
        _w1g4s_Player(name="P0", battlefield=boards[0], hand=cards(hand0),
                      library=cards(lib0), graveyard=cards(gy0)),
        _w1g4s_Player(name="P1", battlefield=boards[1], hand=cards(hand1),
                      library=cards(lib1), graveyard=cards(gy1)),
    ]
    for extra in range(2, seats):
        players.append(_w1g4s_Player(name=f"P{extra}", library=cards(["Swamp"] * 3)))
    game = _w1g4s_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in boards[0] + boards[1]:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, boards[0], boards[1]  # W1G4 sorceries: the table


def _w1g4s_names(cards):
    return [card.name for card in cards]  # W1G4 sorceries: a zone, by name


def _w1g4s_picks(*indices):
    """A counted search's answer over a library."""
    return [{"zone": "library", "index": index} for index in indices]  # W1G4


# -- Tahngarth's Glare -------------------------------------------------------

_W1G4S_GLARE_MINE = ["Forest", "Hill Giant", "Grizzly Bears", "Sol Ring", "Black Lotus"]
_W1G4S_GLARE_THEIRS = ["Island", "Counterspell", "Air Elemental", "Mox Sapphire"]


def test_w1g4_tahngarths_glare_each_player_orders_the_others_top_three(set_pool):
    """"Look at the top three cards of target opponent's library, then put them
    back in any order. That player looks at the top three cards of your
    library, then puts them back in any order."

    Two looks and two seats: the caster orders the opponent's top three, and
    only then does the opponent order the caster's. Each prompt belongs to the
    seat that looks, over the *other* seat's library, and neither seat can
    answer the other's.
    """
    glare = _w1g4s_card(set_pool, "Tahngarth's Glare")
    assert _w1g4s_compile(glare).supported
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib0=_W1G4S_GLARE_MINE,
        lib1=_W1G4S_GLARE_THEIRS, interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Tahngarth's Glare", target_player_index=1).supported
    game.resolve_top_of_stack()

    first = game.pending_reorder_library
    assert (first["caster_index"], first["target_index"], first["top_count"]) == (0, 1, 3)
    assert len(game.pending_choices) == 1, "the second look waits for the first"
    assert not game.confirm_reorder_library(1, [2, 1, 0]), "not the opponent's prompt"
    assert game.confirm_reorder_library(0, [2, 1, 0])

    second = game.pending_reorder_library
    assert (second["caster_index"], second["target_index"], second["top_count"]) == (1, 0, 3)
    assert not game.confirm_reorder_library(0, [1, 0, 2]), "not the caster's prompt"
    assert game.confirm_reorder_library(1, [1, 0, 2])
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[1].library) == [
        "Air Elemental", "Counterspell", "Island", "Mox Sapphire",
    ]
    assert _w1g4s_names(game.players[0].library) == [
        "Hill Giant", "Forest", "Grizzly Bears", "Sol Ring", "Black Lotus",
    ]
    assert _w1g4s_names(game.players[0].graveyard) == ["Tahngarth's Glare"]
    assert game.pending_choices == []
    log = "\n".join(game.log)
    assert log.index("P0 is looking at the top 3 cards of P1's library") < log.index(
        "P1 is looking at the top 3 cards of P0's library"
    )


def test_w1g4_tahngarths_glare_targets_an_opponent_and_nobody_else(set_pool):
    """"Target **opponent**": the picker offers the other seat alone, and a
    cast aimed at the caster is refused with the card still in hand."""
    glare = _w1g4s_card(set_pool, "Tahngarth's Glare")
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib0=_W1G4S_GLARE_MINE,
        lib1=_W1G4S_GLARE_THEIRS,
    )
    spec = game.cast_target_spec(0, glare)
    assert spec["kind"] == "player"
    assert spec["valid_targets"] == [{"kind": "player", "seat": 1}]

    refused = game.cast_from_hand(0, "Tahngarth's Glare", target_player_index=0)
    assert not refused.supported
    assert _w1g4s_names(game.players[0].hand) == ["Tahngarth's Glare"]
    assert game.pending_choices == []


def test_w1g4_tahngarths_glare_looks_at_what_a_short_library_holds(set_pool):
    """CR 609.3: as many as there are. A library of two is a choice between two
    cards; a library of one has no order to choose and is still a *look* — the
    seat is shown the card — and an empty one shows nothing and asks nobody."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib0=["Forest", "Hill Giant"],
        lib1=["Island"], interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Tahngarth's Glare", target_player_index=1).supported
    game.resolve_top_of_stack()

    one = game.pending_reorder_library
    assert (one["caster_index"], one["target_index"], one["top_count"]) == (0, 1, 1)
    assert game.confirm_reorder_library(0, [0])
    two = game.pending_reorder_library
    assert (two["caster_index"], two["target_index"], two["top_count"]) == (1, 0, 2)
    assert game.confirm_reorder_library(1, [1, 0])
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].library) == ["Hill Giant", "Forest"]
    assert _w1g4s_names(game.players[1].library) == ["Island"]

    # The caster's own library empty: the first look happens, the second has
    # nothing to show, and the spell finishes with no prompt left behind.
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib1=["Island", "Swamp"],
        interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Tahngarth's Glare", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert game.confirm_reorder_library(0, [1, 0])
    _w1g4s_resolve_stack(game)
    assert game.pending_choices == []
    assert _w1g4s_names(game.players[1].library) == ["Swamp", "Island"]
    assert "P0 has no cards for P1 to look at (Tahngarth's Glare)" in game.log


def test_w1g4_tahngarths_glare_default_seats_bury_and_surface(set_pool):
    """Two seats nobody asks: each look is answered by the stated policy with
    no prompt left behind, and both libraries keep exactly their cards."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib0=_W1G4S_GLARE_MINE,
        lib1=_W1G4S_GLARE_THEIRS,
    )
    assert game.cast_from_hand(0, "Tahngarth's Glare", target_player_index=1).supported
    game.auto_resolve_pending_choices()
    _w1g4s_resolve_stack(game)

    assert game.pending_choices == []
    assert sorted(_w1g4s_names(game.players[0].library)) == sorted(_W1G4S_GLARE_MINE)
    assert sorted(_w1g4s_names(game.players[1].library)) == sorted(_W1G4S_GLARE_THEIRS)
    assert _w1g4s_names(game.players[0].library)[3:] == ["Sol Ring", "Black Lotus"]


def test_w1g4_the_glares_second_look_reads_every_word_or_refuses():
    """The production's refusals. "That player looks at the top three cards of
    your library" with no rearrangement is not this sentence, a "random order"
    is not "any order", and a looker the sentence would have to *choose* is a
    target nothing here has a picker for — refused by name in the lowering."""
    second = (
        "That player looks at the top three cards of your library, then puts "
        "them back in any order."
    )
    assert _w1g4s_compile_line(second).usable
    assert not _w1g4s_compile_line(
        "That player looks at the top three cards of your library."
    ).parsed
    assert not _w1g4s_compile_line(second.replace("any order", "a random order")).parsed
    chosen = _w1g4s_compile_line(second.replace("That player", "Target opponent"))
    assert chosen.parsed and not chosen.lowered
    assert "only \"that player\"" in chosen.lowering_error


# -- Guided Passage ----------------------------------------------------------

#: A creature, a second creature, an artifact creature, two lands, and three
#: cards that are neither.
_W1G4S_PASSAGE_LIBRARY = [
    "Forest", "Hill Giant", "Grizzly Bears", "Sol Ring", "Black Lotus",
    "Island", "Counterspell", "Clockwork Beast",
]


def test_w1g4_guided_passage_an_opponent_picks_one_card_of_each_kind(set_pool):
    """"Reveal the cards in your library. An opponent chooses from among them a
    creature card, a land card, and a noncreature, nonland card. You put the
    chosen cards into your hand. Then shuffle."

    The whole library is shown to everybody, the *opponent* is the seat that is
    asked, and what it picks lands in the caster's hand.
    """
    passage = _w1g4s_card(set_pool, "Guided Passage")
    assert _w1g4s_compile(passage).supported
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"], lib0=_W1G4S_PASSAGE_LIBRARY,
        interactive=(0, 1),
    )
    assert game.cast_target_spec(0, passage)["kind"] == "none"
    assert game.queue_from_hand(0, "Guided Passage").supported
    game.resolve_top_of_stack()

    assert game.reveal_events[-1] == {
        "id": 1, "seat": 0, "cards": list(_W1G4S_PASSAGE_LIBRARY),
    }
    prompt = game.pending_search_library
    assert prompt["caster_index"] == 1, "the opponent chooses"
    assert prompt["zone_seat"] == 0, "out of the caster's library"
    assert prompt["count"] == 3 and not prompt.get("up_to")
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(2, 5, 6)), (
        "the library's owner is not the one asked"
    )
    assert game.confirm_search_library_picks(1, _w1g4s_picks(2, 5, 6))
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].hand) == [
        "Grizzly Bears", "Island", "Counterspell",
    ]
    assert game.players[1].hand == []
    assert sorted(_w1g4s_names(game.players[0].library)) == sorted([
        "Forest", "Hill Giant", "Sol Ring", "Black Lotus", "Clockwork Beast",
    ])
    assert _w1g4s_names(game.players[0].graveyard) == ["Guided Passage"]
    assert "P1 searched P0's library and found Grizzly Bears, Island, Counterspell" in game.log


def test_w1g4_guided_passage_holds_the_opponent_to_one_of_each(set_pool):
    """One card **per description**, and none of them optional. Two creatures
    are each a legal pick and together are not an answer; an artifact creature
    is not a "noncreature" card; and the opponent may neither decline nor stop
    at two while the library can answer all three."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"], lib0=_W1G4S_PASSAGE_LIBRARY,
        interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Guided Passage").supported
    game.resolve_top_of_stack()

    assert not game.decline_search_library(1)
    assert not game.confirm_search_library_picks(1, [])
    assert not game.confirm_search_library_picks(1, _w1g4s_picks(1, 0)), "one short"
    assert not game.confirm_search_library_picks(1, _w1g4s_picks(1, 2, 0)), (
        "two creatures fill one description"
    )
    assert not game.confirm_search_library_picks(1, _w1g4s_picks(1, 0, 7)), (
        "Clockwork Beast is a creature card"
    )
    assert _w1g4s_names(game.players[0].library) == _W1G4S_PASSAGE_LIBRARY, (
        "a refused answer moves nothing"
    )
    assert game.confirm_search_library_picks(1, _w1g4s_picks(7, 0, 4))
    _w1g4s_resolve_stack(game)
    assert _w1g4s_names(game.players[0].hand) == [
        "Clockwork Beast", "Forest", "Black Lotus",
    ]


def test_w1g4_guided_passage_skips_a_kind_the_library_does_not_hold(set_pool):
    """The card's ruling: "If you have no cards of any of the specified card
    types, then ignore those types and the opponent only selects cards of the
    types you do have." With no land to find the floor is two, and two is then
    the whole answer."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"],
        lib0=["Hill Giant", "Sol Ring", "Grizzly Bears"], interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Guided Passage").supported
    game.resolve_top_of_stack()

    assert not game.confirm_search_library_picks(1, _w1g4s_picks(0)), "two can be found"
    assert game.confirm_search_library_picks(1, _w1g4s_picks(2, 1))
    _w1g4s_resolve_stack(game)
    assert _w1g4s_names(game.players[0].hand) == ["Grizzly Bears", "Sol Ring"]
    assert _w1g4s_names(game.players[0].library) == ["Hill Giant"]


def test_w1g4_guided_passage_over_an_empty_library_asks_nobody(set_pool):
    game, _, _ = _w1g4s_table(set_pool, hand0=["Guided Passage"], interactive=(0, 1))
    assert game.cast_from_hand(0, "Guided Passage").supported
    _w1g4s_resolve_stack(game)

    assert game.pending_choices == []
    assert game.players[0].hand == []
    assert _w1g4s_names(game.players[0].graveyard) == ["Guided Passage"]


def test_w1g4_guided_passage_default_opponent_hands_over_its_least(set_pool):
    """A seat nobody asks still answers in full — one card for every
    description the library can fill — and what it gives its opponent is the
    weakest card of each kind, not the strongest."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"], lib0=_W1G4S_PASSAGE_LIBRARY,
    )
    assert game.cast_from_hand(0, "Guided Passage").supported
    game.auto_resolve_pending_choices()
    _w1g4s_resolve_stack(game)

    hand = _w1g4s_names(game.players[0].hand)
    assert len(hand) == 3 and game.pending_choices == []
    kinds = [_w1g4s_card(set_pool, name).type_line for name in hand]
    assert sum("Creature" in line for line in kinds) == 1
    assert sum("Land" in line for line in kinds) == 1
    assert "Black Lotus" not in hand, "the opponent chose, and not for the caster"
    assert len(game.players[0].library) == len(_W1G4S_PASSAGE_LIBRARY) - 3


def test_w1g4_guided_passage_at_three_seats_the_caster_names_the_opponent(set_pool):
    """CR 608.2d: "an opponent" nobody named is the controller's pick, made as
    the spell resolves. The seat named is then the only one asked."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"],
        # The Swamp is drawn on the way in: CR 103.8a skips the first draw
        # step only at a table of two.
        lib0=["Swamp", "Forest", "Hill Giant", "Sol Ring"],
        interactive=(0, 1, 2), seats=3,
    )
    assert _w1g4s_names(game.players[0].hand) == ["Guided Passage", "Swamp"]
    assert game.queue_from_hand(0, "Guided Passage").supported
    game.resolve_top_of_stack()

    (asked,) = game.pending_choices
    assert (asked.kind, asked.player_index, asked.data["seats"]) == ("player_choice", 0, [1, 2])
    assert game.confirm_player_choice(0, 2)
    prompt = game.pending_search_library
    assert prompt["caster_index"] == 2
    assert not game.confirm_search_library_picks(1, _w1g4s_picks(0, 1, 2))
    assert game.confirm_search_library_picks(2, _w1g4s_picks(0, 1, 2))
    _w1g4s_resolve_stack(game)
    assert sorted(_w1g4s_names(game.players[0].hand)) == [
        "Forest", "Hill Giant", "Sol Ring", "Swamp",
    ]
    assert game.players[2].hand == [] and game.players[1].hand == []


def test_w1g4_guided_passage_reads_all_four_sentences_or_refuses():
    """The production's refusals: no shuffle, no line; a description the
    picker cannot test off a card's face refuses in the lowering by name
    rather than becoming a slot any card fills. A list joined by a bare "and"
    is the same list."""
    printed = (
        "Reveal the cards in your library. An opponent chooses from among them "
        "a creature card, a land card, and a noncreature, nonland card. You "
        "put the chosen cards into your hand. Then shuffle."
    )
    assert _w1g4s_compile_line(printed).usable
    assert not _w1g4s_compile_line(printed.replace(" Then shuffle.", "")).parsed
    assert not _w1g4s_compile_line(
        printed.replace("into your hand", "into your graveyard")
    ).parsed
    untestable = _w1g4s_compile_line(
        printed.replace("a creature card,", "a creature card with flying,")
    )
    assert untestable.parsed and not untestable.lowered
    assert "with_keywords" in untestable.lowering_error
    pair = _w1g4s_compile_line(
        "Reveal the cards in your library. An opponent chooses from among them "
        "a creature card and a land card. You put the chosen cards into your "
        "hand. Then shuffle."
    )
    assert pair.usable
    (sequence,) = pair.instructions
    assert sequence.payload["steps"][1].payload["one_of_each"] == [
        {"card_type": "creature"}, {"card_type": "land"},
    ]


# -- Gaea's Balance ----------------------------------------------------------

#: Two basic Forests, a Forest Island, a Mountain Forest, the other four basic
#: types, a land with no basic type and a card that is no land.
_W1G4S_BALANCE_LIBRARY = [
    "Forest", "Tropical Island", "Grizzly Bears", "Battlefield Forge", "Swamp",
    "Taiga", "Island", "Plains", "Mountain", "Forest",
]
_W1G4S_SIX_LANDS = ["Forest", "Forest", "Forest", "Forest", "Island", "Island"]


def test_w1g4_gaeas_balance_cannot_be_cast_on_four_lands(set_pool):
    """"As an additional cost to cast this spell, sacrifice five lands."
    CR 601.2h: with four the cost cannot be paid, so the spell is not cast —
    nothing is sacrificed, the card stays in hand, and an AI seat does not
    propose it."""
    from engine.ai_policy import choose_cast_action

    game, mine, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:4] + ["Grizzly Bears"],
        hand0=["Gaea's Balance"], lib0=_W1G4S_BALANCE_LIBRARY,
    )
    refused = game.cast_from_hand(0, "Gaea's Balance")

    assert not refused.supported and "601.2h" in refused.details
    assert all(game.is_on_battlefield(permanent) for permanent in mine)
    assert _w1g4s_names(game.players[0].hand) == ["Gaea's Balance"]
    assert choose_cast_action(game, 0) is None


def test_w1g4_gaeas_balance_sacrifices_the_five_lands_its_caster_named(set_pool):
    """The payer chooses which five (CR 601.2b): of six lands and a creature,
    the five named are gone as the spell goes on the stack and the sixth land
    and the creature are still there. The picker is a sacrifice picker over the
    caster's own lands, for five."""
    balance = _w1g4s_card(set_pool, "Gaea's Balance")
    game, mine, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS + ["Grizzly Bears"], theirs=["Mountain"],
        hand0=["Gaea's Balance"], lib0=_W1G4S_BALANCE_LIBRARY, interactive=(0,),
    )
    spec = game.cast_target_spec(0, balance)
    assert (spec["kind"], spec["sacrifice_cost"], spec["count"], spec["own_only"]) == (
        "land", True, 5, True,
    )
    assert len(spec["valid_targets"]) == 6, "the opponent's Mountain is not offered"

    kept = mine[0]
    result = game.queue_from_hand(
        0, "Gaea's Balance",
        cost_permanent_ids=[land.permanent_id for land in mine[1:6]],
    )
    assert result.supported, result.details
    assert game.is_on_battlefield(kept) and game.is_on_battlefield(mine[6])
    assert not any(game.is_on_battlefield(land) for land in mine[1:6])
    assert _w1g4s_names(game.players[0].graveyard) == [
        "Forest", "Forest", "Forest", "Island", "Island",
    ]


def test_w1g4_gaeas_balance_finds_one_land_for_each_basic_land_type(set_pool):
    """"Search your library for a land card of each basic land type, put those
    cards onto the battlefield, then shuffle."

    Five descriptions, one find apiece. A Tropical Island is a Forest card and
    an Island card (the ruling: "You can find a nonbasic land card this way as
    long as it has a basic land type"), so it answers one of the two — and
    whether an answer is legal is a question about the whole of it: the dual, a
    basic Forest and a Taiga are three finds only with the dual read as the
    Island and the Taiga as the Mountain.
    """
    game, _, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:5], hand0=["Gaea's Balance"],
        lib0=_W1G4S_BALANCE_LIBRARY, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Gaea's Balance").supported
    game.resolve_top_of_stack()

    prompt = game.pending_search_library
    assert prompt["count"] == 5 and prompt["up_to"]
    assert prompt["destinations"] == ["battlefield"] * 5
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(0, 9)), "two Forests"
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(2)), "not a land"
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(3)), (
        "Battlefield Forge has no basic land type"
    )
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(1, 0, 5, 8)), (
        "four cards over Forest, Island and Mountain"
    )
    assert game.confirm_search_library_picks(0, _w1g4s_picks(1, 0, 5, 4, 7))
    _w1g4s_resolve_stack(game)
    game._settle()

    assert sorted(perm.card.name for perm in game.controlled_by(0)) == [
        "Forest", "Plains", "Swamp", "Taiga", "Tropical Island",
    ]
    assert not any(perm.tapped for perm in game.controlled_by(0))
    assert sorted(_w1g4s_names(game.players[0].library)) == sorted([
        "Grizzly Bears", "Battlefield Forge", "Island", "Mountain", "Forest",
    ])
    assert game.pending_choices == []


def test_w1g4_gaeas_balance_may_fail_to_find_any_or_all(set_pool):
    """The ruling: "You can fail to find a land card for any or all basic land
    types, even if a land card with that basic land type is in your library."
    One land is an answer, and so is none — the library is shuffled either way
    and the five lands are gone either way."""
    game, _, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:5], hand0=["Gaea's Balance"],
        lib0=_W1G4S_BALANCE_LIBRARY, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Gaea's Balance").supported
    game.resolve_top_of_stack()
    assert game.confirm_search_library_picks(0, _w1g4s_picks(8))
    _w1g4s_resolve_stack(game)
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Mountain"]

    game, _, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:5], hand0=["Gaea's Balance"],
        lib0=_W1G4S_BALANCE_LIBRARY, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Gaea's Balance").supported
    game.resolve_top_of_stack()
    assert game.decline_search_library(0)
    _w1g4s_resolve_stack(game)
    assert list(game.controlled_by(0)) == []
    assert len(game.players[0].library) == len(_W1G4S_BALANCE_LIBRARY)
    assert "P0 searched and found nothing more" in game.log


def test_w1g4_gaeas_balance_default_seat_takes_as_many_as_can_be_assigned(set_pool):
    """A seat nobody asks finds a land for every type it can — and gets the
    assignment right where a first-fit would not: with only a Tropical Island
    and a basic Island to find, both come out (the dual as the Forest)."""
    game, _, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:5], hand0=["Gaea's Balance"],
        lib0=["Tropical Island", "Island", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Gaea's Balance").supported
    game.auto_resolve_pending_choices()
    _w1g4s_resolve_stack(game)
    game._settle()

    assert sorted(perm.card.name for perm in game.controlled_by(0)) == [
        "Island", "Tropical Island",
    ]
    assert _w1g4s_names(game.players[0].library) == ["Grizzly Bears"]
    assert game.pending_choices == []


def test_w1g4_gaeas_balance_search_reads_its_plural_tail_or_refuses():
    """The production's refusals: "of each basic land type" is several cards,
    so "put it" is a different sentence, and the shuffle is required."""
    printed = (
        "Search your library for a land card of each basic land type, put "
        "those cards onto the battlefield, then shuffle."
    )
    compiled = _w1g4s_compile_line(printed)
    assert compiled.usable
    (search,) = compiled.instructions
    assert [
        slot["restrictions"]["subtypes"]
        for slot in search.payload["restrictions"]["one_of_each"]
    ] == [["plains"], ["island"], ["swamp"], ["mountain"], ["forest"]]
    assert not _w1g4s_compile_line(printed.replace("those cards", "it")).parsed
    assert not _w1g4s_compile_line(printed.replace(", then shuffle", "")).parsed


# -- Squee's Revenge ---------------------------------------------------------


def _w1g4s_revenge(set_pool, monkeypatch, flips, number, library=12):
    """Squee's Revenge cast by an asked seat that names *number*, with the
    coin scripted to come up *flips* in order (True is a win)."""
    script = iter(flips)
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda: next(script)
    )
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Squee's Revenge"], lib0=["Forest"] * library,
        interactive=(0,),
    )
    assert game.queue_from_hand(0, "Squee's Revenge").supported
    game.resolve_top_of_stack()
    assert game.confirm_number_choice(0, number)
    _w1g4s_resolve_stack(game)
    return game, list(script)  # W1G4 sorceries: the game and the flips unused


def test_w1g4_squees_revenge_draws_two_cards_for_each_flip_of_a_clean_run(
    set_pool, monkeypatch,
):
    """"Choose a number. Flip a coin that many times or until you lose a flip,
    whichever comes first. If you win all the flips, draw two cards for each
    flip." Three named, three won: six cards."""
    game, unused = _w1g4s_revenge(set_pool, monkeypatch, [True] * 5, 3)

    assert len(game.players[0].hand) == 6
    assert len(game.players[0].library) == 6
    assert len(unused) == 2, "exactly three coins were flipped"
    assert game.log.count("Squee's Revenge: won the coin flip") == 3
    assert "Squee's Revenge: 3 of 3 flip(s) made, every one won" in game.log


def test_w1g4_squees_revenge_stops_at_the_first_loss_and_draws_nothing(
    set_pool, monkeypatch,
):
    """"…or until you lose a flip, whichever comes first": the third and
    fourth coins are never flipped, and a run with a loss in it pays nothing —
    not even for the two flips that were won."""
    game, unused = _w1g4s_revenge(
        set_pool, monkeypatch, [True, True, False, True, True], 5,
    )

    assert game.players[0].hand == []
    assert len(game.players[0].library) == 12
    assert len(unused) == 2
    assert "Squee's Revenge: 3 of 5 flip(s) made, the last one lost" in game.log
    assert _w1g4s_names(game.players[0].graveyard) == ["Squee's Revenge"]


def test_w1g4_squees_revenge_at_zero_flips_nothing_and_draws_nothing(
    set_pool, monkeypatch,
):
    """Zero is a number (CR 107.1). No coin is flipped, every flip of none was
    won, and two cards for each of no flips is no cards."""
    game, unused = _w1g4s_revenge(set_pool, monkeypatch, [True, True], 0)

    assert game.players[0].hand == []
    assert len(unused) == 2
    assert "Squee's Revenge: 0 of 0 flip(s) made, every one won" in game.log


def test_w1g4_squees_revenge_asks_for_a_number_with_no_ceiling(set_pool):
    """The prompt is the open number prompt: zero or more, no upper bound, and
    a negative answer is refused with the prompt still owed. The flips wait for
    the answer — nothing is flipped while the number is unknown."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Squee's Revenge"], lib0=["Forest"] * 4, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Squee's Revenge").supported
    game.resolve_top_of_stack()

    (asked,) = game.pending_choices
    assert asked.kind == "number_choice" and asked.player_index == 0
    assert (asked.data["minimum"], asked.data["maximum"]) == (0, None)
    assert not any("coin flip" in line for line in game.log)
    assert not game.confirm_number_choice(0, -1)
    assert game.pending_choices == [asked]
    assert game.confirm_number_choice(0, 1000), "any number at all"
    _w1g4s_resolve_stack(game)
    assert game.pending_choices == []
    assert any("flip(s) made" in line for line in game.log)


def test_w1g4_squees_revenge_default_seat_flips_the_seeded_coin_twice(set_pool):
    """A seat nobody asks names two (the expectation is the same at one and
    two, and falls from three), and the flips come off the seeded RNG — the
    same seed plays the same game."""
    import random

    outcomes = []
    for _ in range(2):
        random.seed(4)
        game, _, _ = _w1g4s_table(
            set_pool, hand0=["Squee's Revenge"], lib0=["Forest"] * 12,
        )
        assert game.cast_from_hand(0, "Squee's Revenge").supported
        game.auto_resolve_pending_choices()
        _w1g4s_resolve_stack(game)
        assert "Squee's Revenge: chose 2" in game.log
        outcomes.append(
            ([line for line in game.log if "coin flip" in line],
             len(game.players[0].hand))
        )
    assert outcomes[0] == outcomes[1]
    flips, drawn = outcomes[0]
    assert drawn == (4 if flips == ["Squee's Revenge: won the coin flip"] * 2 else 0)


def test_w1g4_squees_run_of_flips_needs_its_number_and_its_reward():
    """The production's refusals. "That many" with no number chosen in front of
    it bounds nothing and refuses in the lowering; the run with no sentence
    saying what a clean one pays is not this card; and a plain "Flip a coin."
    is still one flip."""
    run = (
        "Flip a coin that many times or until you lose a flip, whichever comes "
        "first. If you win all the flips, draw two cards for each flip."
    )
    assert _w1g4s_compile_line("Choose a number. " + run).usable
    unbound = _w1g4s_compile_line(run)
    assert unbound.parsed and not unbound.lowered
    assert "no number chosen" in unbound.lowering_error
    assert not _w1g4s_compile_line(
        "Choose a number. Flip a coin that many times or until you lose a flip, "
        "whichever comes first."
    ).parsed
    (flip,) = _w1g4s_compile_line("Flip a coin.").instructions
    assert flip.kind == "flip_coin"


# -- Lay of the Land ---------------------------------------------------------


def test_w1g4_lay_of_the_land_finds_a_basic_land_and_shows_it(set_pool):
    """"Search your library for a basic land card, reveal it, put it into your
    hand, then shuffle." A nonbasic land and a creature are refused; the find
    is revealed to the table and the rest of the library is still all there."""
    library = ["Grizzly Bears", "Tropical Island", "Forest", "Sol Ring", "Island"]
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Lay of the Land"], lib0=library, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Lay of the Land").supported
    game.resolve_top_of_stack()

    prompt = game.pending_search_library
    assert (prompt["count"], prompt["card_type"]) == (1, "land")
    assert not game.confirm_search_library(0, 0), "a creature"
    assert not game.confirm_search_library(0, 1), "a land, and not basic"
    assert game.confirm_search_library(0, 2)
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].hand) == ["Forest"]
    assert game.reveal_events[-1]["cards"] == ["Forest"]
    assert sorted(_w1g4s_names(game.players[0].library)) == sorted(
        ["Grizzly Bears", "Tropical Island", "Sol Ring", "Island"]
    )
    assert _w1g4s_names(game.players[0].graveyard) == ["Lay of the Land"]


# -- Temporal Spring ---------------------------------------------------------


def test_w1g4_temporal_spring_puts_the_named_permanent_on_its_owners_library(set_pool):
    """"Put target permanent on top of its owner's library." Any permanent is
    a target, the one named is the one moved, and it is the next card that
    library gives up."""
    spring = _w1g4s_card(set_pool, "Temporal Spring")
    game, mine, theirs = _w1g4s_table(
        set_pool, mine=["Forest"], theirs=["Serra Angel", "Sol Ring"],
        hand0=["Temporal Spring"], lib1=["Island", "Island"],
    )
    spec = game.cast_target_spec(0, spring)
    assert spec["kind"] == "permanent" and len(spec["valid_targets"]) == 3

    ring = theirs[1]
    cast = game.cast_from_hand(0, "Temporal Spring", target_permanent_ids=[ring.permanent_id])
    assert cast.supported, cast.details
    _w1g4s_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(ring)
    assert game.is_on_battlefield(theirs[0]) and game.is_on_battlefield(mine[0])
    assert _w1g4s_names(game.players[1].library) == ["Sol Ring", "Island", "Island"]
    assert game.players[1].graveyard == []


def test_w1g4_temporal_spring_sends_a_stolen_permanent_to_its_owner(set_pool):
    """"Its **owner's** library" (CR 400.3): a creature the caster had taken
    goes on top of the library it came out of, not the caster's."""
    from engine.control import change_control

    game, _, theirs = _w1g4s_table(
        set_pool, theirs=["Serra Angel"], hand0=["Temporal Spring"],
        lib0=["Forest"], lib1=["Island"],
    )
    angel = theirs[0]
    change_control(angel, 0, source="test")
    game._sync_control()
    assert game.controller_index_of(angel) == 0

    assert game.cast_from_hand(
        0, "Temporal Spring", target_permanent_ids=[angel.permanent_id]
    ).supported
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[1].library) == ["Serra Angel", "Island"]
    assert _w1g4s_names(game.players[0].library) == ["Forest"]


# -- Urborg Uprising ---------------------------------------------------------

_W1G4S_UPRISING_GRAVEYARD = ["Grizzly Bears", "Sol Ring", "Hill Giant", "Serra Angel"]


def _w1g4s_uprising(set_pool, **kwargs):
    return _w1g4s_table(
        set_pool, hand0=["Urborg Uprising"], gy0=_W1G4S_UPRISING_GRAVEYARD,
        gy1=["Air Elemental"], lib0=["Forest", "Island"], **kwargs,
    )  # W1G4 sorceries: the Uprising's table


def test_w1g4_urborg_uprising_returns_two_creature_cards_and_draws(set_pool):
    """"Return up to two target creature cards from your graveyard to your
    hand. Draw a card.\""""
    uprising = _w1g4s_card(set_pool, "Urborg Uprising")
    game, _, _ = _w1g4s_uprising(set_pool)
    spec = game.cast_target_spec(0, uprising)
    assert (spec["max_targets"], spec["own_graveyard_only"]) == (2, True)
    assert [target["name"] for target in spec["valid_targets"]] == [
        "Grizzly Bears", "Hill Giant", "Serra Angel",
    ]

    cast = game.cast_from_hand(
        0, "Urborg Uprising", target_player_index=0, target_permanent_index=[0, 3],
    )
    assert cast.supported, cast.details
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].hand) == ["Grizzly Bears", "Serra Angel", "Forest"]
    assert _w1g4s_names(game.players[0].graveyard) == ["Sol Ring", "Hill Giant", "Urborg Uprising"]
    assert _w1g4s_names(game.players[0].library) == ["Island"]


def test_w1g4_urborg_uprising_refuses_what_its_target_phrase_does_not_name(set_pool):
    """Held at the announcement: a card that is no creature, the same card
    twice, a third target, and a card in somebody else's graveyard are each
    refused with the spell still in hand and nothing moved."""
    game, _, _ = _w1g4s_uprising(set_pool)
    for seat, indices in ((0, [1]), (0, [0, 0]), (0, [0, 2, 3]), (1, [0])):
        refused = game.cast_from_hand(
            0, "Urborg Uprising", target_player_index=seat,
            target_permanent_index=indices,
        )
        assert not refused.supported, (seat, indices)
    assert _w1g4s_names(game.players[0].hand) == ["Urborg Uprising"]
    assert _w1g4s_names(game.players[0].graveyard) == _W1G4S_UPRISING_GRAVEYARD
    assert _w1g4s_names(game.players[1].graveyard) == ["Air Elemental"]


def test_w1g4_urborg_uprising_with_no_target_still_draws(set_pool):
    """"Up to two" may be none (CR 601.2c), and a spell that named no target
    is not one whose targets are all illegal: the draw happens."""
    game, _, _ = _w1g4s_uprising(set_pool)
    assert game.cast_from_hand(0, "Urborg Uprising").supported
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].hand) == ["Forest"]
    assert _w1g4s_names(game.players[0].graveyard) == (
        _W1G4S_UPRISING_GRAVEYARD + ["Urborg Uprising"]
    )


def test_w1g4_urborg_uprising_follows_its_targets_and_fizzles_without_them(set_pool):
    """CR 608.2b at both sizes. With one of two targets exiled in response the
    other still comes back — the card it named, though the pile has shifted
    under it — and the draw happens. With its only target gone the spell is
    removed from the stack and draws nothing."""
    game, _, _ = _w1g4s_uprising(set_pool)
    assert game.queue_from_hand(
        0, "Urborg Uprising", target_player_index=0, target_permanent_index=[0, 3],
    ).supported
    game.players[0].exile.append(game.players[0].graveyard.pop(0))
    _w1g4s_resolve_stack(game)
    assert _w1g4s_names(game.players[0].hand) == ["Serra Angel", "Forest"]
    assert _w1g4s_names(game.players[0].graveyard) == ["Sol Ring", "Hill Giant", "Urborg Uprising"]

    game, _, _ = _w1g4s_uprising(set_pool)
    assert game.queue_from_hand(
        0, "Urborg Uprising", target_player_index=0, target_permanent_index=[2],
    ).supported
    game.players[0].exile.append(game.players[0].graveyard.pop(2))
    _w1g4s_resolve_stack(game)
    assert game.players[0].hand == []
    assert _w1g4s_names(game.players[0].library) == ["Forest", "Island"]
    assert any("608.2b" in line for line in game.log)


# -- Whole games -------------------------------------------------------------


@_w1g4s_pytest.mark.slow
def test_w1g4_the_ai_plays_this_groups_spells_through_whole_games():
    """Six simulated games with this group's cards pinned into both decks,
    because a card can compile and do nothing in a turn structure. Each of the
    four sorceries is cast and resolves; the opponent's pick, both looks, the
    run of flips and the five-land search all happen inside the step that owes
    them (`steps_left_owing`); and nothing any of them does is an issue or a
    refused cast.

    The floors are one apiece on purpose: the seed's trajectory moves whenever
    another card in the set changes, and this asks that each was *seen*.
    (The pool is a measured set, so other cards' unsupported casts are in the
    report; only these cards' lines are read.)
    """
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    names = [
        "Guided Passage", "Squee's Revenge", "Tahngarth's Glare", "Wild Research",
        "Dragon Arch", "Gaea's Balance", "Legacy Weapon",
    ]
    report = run_ai_simulation(
        [manifest_set_path("APC", include_measured=True)],
        games=6, seed=1337, max_turns=24, required_cards=names,
    )
    log = report.log_lines

    assert report.games_completed == 6
    assert report.steps_left_owing == {}, dict(report.steps_left_owing)
    for name in names:
        assert not [i.message for i in report.issues if name in i.message], name
        assert not [why for why in report.refused_casts if name in why], name
    w1g4_cast = {
        name for name in names
        if any(f"cast {name} -> resolved" in line for line in log)
    }
    assert len(w1g4_cast) >= 5, sorted(w1g4_cast)
    w1g4_seen = {
        "the run of flips": any("flip(s) made" in line for line in log),
        "the revealed library": any("revealed their library" in line for line in log),
        "the five-land cost": any("to cast Gaea's Balance" in line for line in log),
        "the two looks": sum(
            "is looking at the top 3 cards of" in line for line in log
        ) >= 2,
        "the tutor's random discard": any(
            "discarded 1 cards at random" in line for line in log
        ),
    }
    assert sum(w1g4_seen.values()) >= 4, w1g4_seen

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5s_Game, PlayerState as _w1g5s_Player
from engine import faces as _w1g5s_faces
from engine.models import Permanent as _w1g5s_Permanent
from tests.helpers import _mk_card as _w1g5s_mk_card
from tests.helpers import resolve_stack as _w1g5s_resolve_stack


def _w1g5s_duel(mine=(), theirs=(), *, hand0=(), graveyard0=(), graveyard1=()):
    """Two boards placed and unsick, seat 0's turn begun."""
    board0 = [_w1g5s_Permanent(card=card) for card in mine]
    board1 = [_w1g5s_Permanent(card=card) for card in theirs]
    filler = _w1g5s_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5s_Game(players=[
        _w1g5s_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10, graveyard=list(graveyard0)),
        _w1g5s_Player(name="P1", battlefield=board1, library=[filler] * 10,
                      graveyard=list(graveyard1)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._settle()
    return game, board0, board1  # W1G5 sorceries: the duel


def _w1g5s_half(card, name):
    return next(face for face in _w1g5s_faces.face_cards(card) if face.name == name)  # W1G5


def test_life_makes_its_casters_lands_creatures_that_are_still_lands(set_pool):
    """Life // Death, the Life half {G}: "All lands you control become 1/1
    creatures until end of turn. They're still lands." The caster's Forests
    are 1/1 creatures and still Forests; the opponent's is untouched; a land
    played afterwards is not animated (CR 611.2c); and at cleanup they are
    lands and nothing else."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Life // Death"]
    game, mine, theirs = _w1g5s_duel(
        [lea["Forest"], lea["Forest"], lea["Grizzly Bears"]], [lea["Forest"]], hand0=[card],
    )
    assert game.cast_target_spec(0, _w1g5s_half(card, "Life"))["kind"] == "none"
    assert game.cast_from_hand(0, "Life").supported
    for forest in mine[:2]:
        assert forest.is_creature and forest.has_type("land") and forest.has_type("forest")
        assert (forest.effective_power, forest.effective_toughness) == (1, 1)
    assert (mine[2].effective_power, mine[2].effective_toughness) == (2, 2)
    assert not theirs[0].is_creature
    late = _w1g5s_Permanent(card=lea["Forest"])
    game._put_permanent_onto_battlefield(0, late, None)
    assert not late.is_creature
    game.resolve_cleanup_step(0)
    assert not any(forest.is_creature for forest in mine[:2])
    assert all(forest.has_type("forest") for forest in mine[:2])


def test_death_returns_a_creature_card_and_charges_its_mana_value_in_life(set_pool):
    """The Death half {1}{B}: "Return target creature card from your graveyard
    to the battlefield. You lose life equal to its mana value." The Craw Wurm
    (mana value 6) comes back under its owner's control and the caster is at
    14. Only a creature card, only the caster's own graveyard: a Bolt there and
    a creature in the opponent's are neither offered nor accepted, and with
    nothing to return the spell cannot be cast."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Life // Death"]
    game, _mine, _theirs = _w1g5s_duel(
        hand0=[card], graveyard0=[lea["Lightning Bolt"], lea["Craw Wurm"]],
        graveyard1=[lea["Grizzly Bears"]],
    )
    offered = game.cast_target_spec(0, _w1g5s_half(card, "Death"))["valid_targets"]
    assert [(entry["seat"], entry["name"]) for entry in offered] == [(0, "Craw Wurm")]
    for announcement in (
        {"target_player_index": 0, "target_permanent_index": 0},   # the Bolt
        {"target_player_index": 1, "target_permanent_index": 0},   # their Bears
    ):
        refused = game.queue_from_hand(0, "Death", **announcement)
        assert not refused.supported, refused
    assert game.players[0].hand == [card]

    assert game.cast_from_hand(
        0, "Death", target_player_index=0, target_permanent_index=1
    ).supported
    wurm = next(iter(game.controlled_by(0)))
    assert wurm.card.name == "Craw Wurm"
    assert game.players[0].life == 14 and game.players[1].life == 20
    assert sorted(c.name for c in game.players[0].graveyard) == ["Life // Death", "Lightning Bolt"]

    empty, _mine, _theirs = _w1g5s_duel(hand0=[card], graveyard0=[lea["Lightning Bolt"]])
    refused = empty.queue_from_hand(0, "Death")
    assert not refused.supported and "no valid target" in refused.details


def test_vindicate_destroys_whatever_permanent_it_names(set_pool):
    """Vindicate {1}{W}{B}: "Destroy target permanent." A land, an artifact,
    an enchantment, a creature — each named by id and each in its owner's
    graveyard afterwards, with the rest of the board where it was."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    vindicate = apc["Vindicate"]
    game, _mine, theirs = _w1g5s_duel(
        [], [lea["Forest"], lea["Sol Ring"], lea["Crusade"], lea["Grizzly Bears"]],
        hand0=[vindicate] * 4,
    )
    offered = game.cast_target_spec(0, vindicate)
    assert offered["kind"] == "permanent"
    assert [entry["name"] for entry in offered["valid_targets"]] == [
        "Forest", "Sol Ring", "Crusade", "Grizzly Bears",
    ]
    for victim in theirs:
        before = [p.card.name for p in game.controlled_by(1)]
        assert game.cast_from_hand(
            0, "Vindicate", target_permanent_ids=[victim.permanent_id]
        ).supported
        before.remove(victim.card.name)
        assert [p.card.name for p in game.controlled_by(1)] == before
    assert sorted(c.name for c in game.players[1].graveyard) == [
        "Crusade", "Forest", "Grizzly Bears", "Sol Ring",
    ]
    assert game.players[1].life == 20


def test_vindicate_has_to_be_spent_on_a_flagbearer(set_pool):
    """Under Standard Bearer the land Vindicate was held for is not a legal
    announcement while the Bearer can be named; with the Bearer destroyed the
    next one takes the land."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    vindicate = apc["Vindicate"]
    game, _mine, theirs = _w1g5s_duel(
        [], [lea["Forest"], apc["Standard Bearer"]], hand0=[vindicate, vindicate],
    )
    forest, bearer = theirs
    refused = game.queue_from_hand(0, "Vindicate", target_permanent_ids=[forest.permanent_id])
    assert not refused.supported and "must be chosen as a target if able" in refused.details
    assert game.cast_from_hand(
        0, "Vindicate", target_permanent_ids=[bearer.permanent_id]
    ).supported
    assert game.cast_from_hand(
        0, "Vindicate", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert list(game.controlled_by(1)) == []

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.board_payment import board_can_pay as _w1g7_board_can_pay
from engine.grammar import compile_line as _w1g7_compile_line
from engine.mana_payment import mana_cost_from_symbols as _w1g7_cost
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_sorcery_duel(*, interactive=()):
    """A two-seat game with costs off, nobody interactive unless a test says."""
    p0, p1 = _W1G7PlayerState(name="A"), _W1G7PlayerState(name="B")
    game = _W1G7Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game, p0, p1


def _w1g7_sorcery_put(game, seat, card):
    """Put *card* onto *seat*'s battlefield, ready to act this turn."""
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    return permanent


def _w1g7_floating(player):
    """The mana in *player*'s pool, zero entries dropped."""
    return {symbol: amount for symbol, amount in player.mana_pool.items() if amount}


def _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name):
    """Seat 0 casts False Dawn for free and it resolves; costs then go on."""
    caster = game.players[0]
    caster.hand = [set_pool("APC")["False Dawn"], *caster.hand]
    if not caster.library:
        caster.library = [catalog_by_name["Grizzly Bears"]]
    assert game.cast_from_hand(0, "False Dawn").supported
    _w1g7_resolve_stack(game)
    game.enforce_mana_costs = True


# -- False Dawn --------------------------------------------------------------


def test_false_dawn_turns_the_colored_mana_its_caster_adds_white(
    set_pool, catalog_by_name
):
    """"Until end of turn, spells and abilities you control that would add
    colored mana instead add that much white mana." A land's mana ability, a
    creature's and a ritual are all "abilities and spells you control"; {C} is
    not coloured mana (CR 106.1a) and the opponent's Mountain is not the
    caster's."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    tropical = _w1g7_sorcery_put(game, 0, catalog_by_name["Tropical Island"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Llanowar Elves"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Sol Ring"])
    mountain = _w1g7_sorcery_put(game, 1, catalog_by_name["Mountain"])
    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)
    assert (
        "False Dawn: colored mana A's spells and abilities would add is {W} "
        "this turn"
    ) in game.log

    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    assert _w1g7_floating(p0) == {"W": 1}
    # A dual land asked for blue still makes white.
    assert game.tap_land_for_mana(0, "Tropical Island", "U", permanent_id=tropical.permanent_id)
    assert _w1g7_floating(p0) == {"W": 2}
    assert game.activate_permanent_ability(0, "Llanowar Elves").supported
    assert _w1g7_floating(p0) == {"W": 3}
    assert "Llanowar Elves added {W} instead (False Dawn)" in game.log
    assert game.activate_permanent_ability(0, "Sol Ring").supported
    assert _w1g7_floating(p0) == {"W": 3, "C": 2}

    assert game.tap_land_for_mana(1, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert _w1g7_floating(p1) == {"R": 1}


def test_false_dawn_lets_white_mana_pay_for_any_color(set_pool, catalog_by_name):
    """"Until end of turn, you may spend white mana as though it were mana of
    any color." Three Forests cast a {2}{U} creature and pay a Dark Ritual's
    {B} — and the Ritual, a spell its caster controls, adds {W}{W}{W} ("that
    much white mana")."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forests = [_w1g7_sorcery_put(game, 0, catalog_by_name["Forest"]) for _ in range(4)]
    p0.hand = [catalog_by_name["Prodigal Sorcerer"], catalog_by_name["Dark Ritual"]]
    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)
    assert "False Dawn: A may spend {W} as though it were mana of any color this turn" in game.log

    for forest in forests:
        game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    assert _w1g7_floating(p0) == {"W": 4}

    assert game.cast_from_hand(0, "Prodigal Sorcerer").supported
    assert _w1g7_floating(p0) == {"W": 1}
    assert "Prodigal Sorcerer" in [perm.card.name for perm in p0.battlefield]

    assert game.cast_from_hand(0, "Dark Ritual").supported
    assert _w1g7_floating(p0) == {"W": 3}
    assert "Dark Ritual added {W} instead (False Dawn)" in game.log


def test_false_dawn_is_what_the_castable_highlight_and_the_planner_read(
    set_pool, catalog_by_name
):
    """The payment questions asked *without* tapping anything: what a land
    would put in the pool, and whether the board covers a cost. Before the
    spell two Forests cannot pay {U}{U}; after it they can, and the opponent's
    Mountain still cannot pay {U}."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    mountain = _w1g7_sorcery_put(game, 1, catalog_by_name["Mountain"])
    blue = _w1g7_cost("{U}{U}")
    assert not _w1g7_board_can_pay(game, 0, blue)
    assert game._land_payment_colors(forest) == ("G",)

    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)

    assert game._land_payment_colors(forest) == ("W",)
    assert game._land_payment_colors(mountain) == ("R",)
    assert _w1g7_board_can_pay(game, 0, blue)
    assert not _w1g7_board_can_pay(game, 1, _w1g7_cost("{U}"))


def test_false_dawn_changes_no_permanent_and_draws_a_card(set_pool, catalog_by_name):
    """The card's rulings: it "does not change the color of any permanents" and
    "does not change any lands into Plains" — the effect is on mana and on how
    it is spent. And the third sentence: draw a card."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    elves = _w1g7_sorcery_put(game, 0, catalog_by_name["Llanowar Elves"])
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)

    assert [card.name for card in p0.hand] == ["Island"]
    assert [card.name for card in p0.graveyard] == ["False Dawn"]
    assert forest.basic_land_types == ("forest",)
    assert game._effective_colors(elves) == {"G"}


def test_false_dawn_ends_in_the_cleanup_step(set_pool, catalog_by_name):
    """Both sentences are "until end of turn": after cleanup the Forest makes
    green again and green does not pay for blue."""
    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)
    assert p0.mana_spending_permissions

    game.resolve_cleanup_step(0)

    assert p0.mana_spending_permissions == ()
    assert game._land_payment_colors(forest) == ("G",)
    assert not _w1g7_board_can_pay(game, 0, _w1g7_cost("{U}{U}"))
    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    assert _w1g7_floating(p0) == {"G": 1}


def test_false_dawn_reaches_a_triggered_mana_ability_its_caster_controls(
    set_pool, catalog_by_name
):
    """Wild Growth's "adds an additional {G}" is an ability of the Aura, which
    its controller controls — so it adds {W} too."""
    from engine.auras import attach_aura

    game, p0, p1 = _w1g7_sorcery_duel()
    forest = _w1g7_sorcery_put(game, 0, catalog_by_name["Forest"])
    growth = _w1g7_sorcery_put(game, 0, catalog_by_name["Wild Growth"])
    attach_aura(growth, forest)
    _w1g7_resolve_false_dawn(game, set_pool, catalog_by_name)

    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)

    assert _w1g7_floating(p0) == {"W": 2}
    assert "Wild Growth: A added an additional {W}" in game.log


def test_the_turn_long_mana_sentences_are_read_only_behind_their_window(
    set_pool, catalog_by_name
):
    """The two productions sit behind "Until end of turn," and nowhere else.
    The bare permission is a *static* line two shipped cards print, read by
    ``engine/mana_spending.py``'s derivation — a production that claimed it
    would take both cards' lines away."""
    dawn = _w1g7_compile(set_pool("APC")["False Dawn"])
    assert [step.kind for step in dawn.instructions[0].payload["steps"]] == [
        "swap_controller_added_mana_until_eot", "grant_mana_spending_until_eot",
    ]
    for name in ("Celestial Dawn", "Sunglasses of Urza"):
        program = _w1g7_compile(catalog_by_name[name])
        assert program.supported
        assert any(
            step.kind == "derived_static_rule" and step.value == "mana_spending"
            for step in program.instructions
        )

    assert not _w1g7_compile_line(
        "You may spend white mana as though it were mana of any color."
    ).parsed
    # The half that takes something away is not a permission, and "colorless"
    # is not a colour coloured mana can become.
    assert not _w1g7_compile_line(
        "Until end of turn, you may spend other mana only as though it were "
        "colorless mana."
    ).parsed
    assert not _w1g7_compile_line(
        "Until end of turn, spells and abilities you control that would add "
        "colored mana instead add that much colorless mana."
    ).parsed
    # A window with no sweep behind it refuses in the lowering.
    longer = _w1g7_compile_line(
        "Until your next turn, you may spend white mana as though it were mana "
        "of any color."
    )
    assert longer.parsed and not longer.usable


# -- Planar Despair (driven) -------------------------------------------------


def test_planar_despair_shrinks_every_creature_by_its_casters_domain(
    set_pool, catalog_by_name
):
    """"Domain — All creatures get -1/-1 until end of turn for each basic land
    type among lands you control." Island, two Swamps and a Tropical Island are
    three types (Island, Swamp, Forest); the opponent's lands are not counted.
    Both players' 2/2s and a 0/3 die, a 6/4 lives as a 3/1, and the cleanup
    step gives it its size back."""
    game, p0, p1 = _w1g7_sorcery_duel()
    for name in ("Island", "Swamp", "Swamp", "Tropical Island"):
        _w1g7_sorcery_put(game, 0, catalog_by_name[name])
    for name in ("Mountain", "Plains"):
        _w1g7_sorcery_put(game, 1, catalog_by_name[name])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Grizzly Bears"])
    _w1g7_sorcery_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w1g7_sorcery_put(game, 1, catalog_by_name["Wall of Wood"])
    wurm = _w1g7_sorcery_put(game, 1, catalog_by_name["Craw Wurm"])
    p0.hand = [set_pool("APC")["Planar Despair"]]

    assert game.cast_from_hand(0, "Planar Despair").supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()

    assert [perm.card.name for perm in p0.battlefield if perm.is_creature] == []
    assert [perm.card.name for perm in p1.battlefield if perm.is_creature] == ["Craw Wurm"]
    assert (wurm.effective_power, wurm.effective_toughness) == (3, 1)
    assert sorted(card.name for card in p1.graveyard) == ["Grizzly Bears", "Wall of Wood"]

    game.resolve_cleanup_step(0)
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)


def test_planar_despair_with_no_basic_land_type_changes_nothing(
    set_pool, catalog_by_name
):
    """A domain of zero is -0/-0: every creature keeps its size."""
    game, p0, p1 = _w1g7_sorcery_duel()
    _w1g7_sorcery_put(game, 0, catalog_by_name["Mishra's Factory"])
    bears = _w1g7_sorcery_put(game, 1, catalog_by_name["Grizzly Bears"])
    p0.hand = [set_pool("APC")["Planar Despair"]]

    assert game.cast_from_hand(0, "Planar Despair").supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()

    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert bears in p1.battlefield


# -- Tranquil Path (driven) --------------------------------------------------


def test_tranquil_path_destroys_every_enchantment_and_draws_a_card(
    set_pool, catalog_by_name
):
    """"Destroy all enchantments. / Draw a card." Both players', Auras
    included; nothing that is not an enchantment is touched."""
    from engine.auras import attach_aura

    game, p0, p1 = _w1g7_sorcery_duel()
    _w1g7_sorcery_put(game, 0, set_pool("APC")["Unnatural Selection"])
    _w1g7_sorcery_put(game, 1, set_pool("APC")["Ice Cave"])
    forest = _w1g7_sorcery_put(game, 1, catalog_by_name["Forest"])
    growth = _w1g7_sorcery_put(game, 1, catalog_by_name["Wild Growth"])
    attach_aura(growth, forest)
    _w1g7_sorcery_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w1g7_sorcery_put(game, 0, catalog_by_name["Sol Ring"])
    p0.hand = [set_pool("APC")["Tranquil Path"]]
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    assert game.cast_from_hand(0, "Tranquil Path").supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()

    assert [perm.card.name for perm in p0.battlefield] == ["Sol Ring"]
    assert [perm.card.name for perm in p1.battlefield] == ["Forest", "Grizzly Bears"]
    assert sorted(card.name for card in p0.graveyard) == [
        "Tranquil Path", "Unnatural Selection",
    ]
    assert sorted(card.name for card in p1.graveyard) == ["Ice Cave", "Wild Growth"]
    assert [card.name for card in p0.hand] == ["Island"]


def test_tranquil_path_with_no_enchantment_still_draws(set_pool, catalog_by_name):
    """It targets nothing, so an empty board is no reason not to resolve."""
    game, p0, p1 = _w1g7_sorcery_duel()
    p0.hand = [set_pool("APC")["Tranquil Path"]]
    p0.library = [catalog_by_name["Island"]]

    assert game.cast_from_hand(0, "Tranquil Path").supported
    _w1g7_resolve_stack(game)

    assert [card.name for card in p0.hand] == ["Island"]

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

import pytest as _w1g8_pytest

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.color_changes import change_color as _w1g8_change_color
from engine.models import Permanent as _w1g8_Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.helpers import _mk_card as _w1g8_mk_card
from tests.helpers import resolve_stack as _w1g8_resolve_stack

# Where the cards these tests borrow from other sets were first printed. Every
# other name is Apocalypse's.
_W1G8_HOMES = {
    "Terror": "LEA", "Lightning Bolt": "LEA", "Swamp": "LEA", "Forest": "LEA",
    "Island": "LEA", "Healing Salve": "LEA", "Giant Growth": "LEA",
    "Grizzly Bears": "LEA", "Drudge Skeletons": "LEA", "Counterspell": "LEA",
    "Library of Leng": "LEA", "Megrim": "STH",
}
_W1G8_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}


def _w1g8_card(set_pool, name: str):
    return set_pool(_W1G8_HOMES.get(name, "APC"))[name]


def _w1g8_duel(set_pool, *, hand=(), opp_hand=(), library=(), opp_library=(),
               interactive=()) -> _w1g8_Game:
    """Two seats with costs enforced and mana to pay them, so a refused cast
    can be shown to have spent nothing."""
    forest = _w1g8_card(set_pool, "Forest")
    me = _w1g8_PlayerState(
        name="Me", hand=[_w1g8_card(set_pool, n) for n in hand],
        library=[_w1g8_card(set_pool, n) for n in library] or [forest] * 12,
    )
    opp = _w1g8_PlayerState(
        name="Opp", hand=[_w1g8_card(set_pool, n) for n in opp_hand],
        library=[_w1g8_card(set_pool, n) for n in opp_library] or [forest] * 12,
    )
    game = _w1g8_Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    me.mana_pool.update(_W1G8_RICH)
    opp.mana_pool.update(_W1G8_RICH)
    return game


def _w1g8_put(game, set_pool, seat: int, name: str) -> _w1g8_Permanent:
    perm = _w1g8_Permanent(card=_w1g8_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g8_names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _w1g8_settle(game) -> None:
    """Resolve the stack and take every owed default — the two calls an AI or
    headless seat's loop makes between actions."""
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)


def _w1g8_exile_on_the_wire(game, viewer, seat: int) -> list:
    from web.serialization import _serialize_player

    payload = _serialize_player(game.players[seat], viewer, seat, game)["exile"]
    return [entry if isinstance(entry, str) else entry["name"] for entry in payload]


# --- Mind Extraction ----------------------------------------------------------

_W1G8_VICTIM_HAND = [
    "Terror", "Lightning Bolt", "Swamp", "Gerrard's Verdict", "Dodecapod",
    "Healing Salve",
]


@_w1g8_pytest.mark.parametrize("sacrificed, gone", [
    # Black: the black card and the white-black one (CR 105.2b: it *is* black).
    ("Drudge Skeletons", ["Terror", "Gerrard's Verdict"]),
    # White-black: every card sharing either colour (the ruling of 2004-10-04).
    ("Putrid Warrior", ["Terror", "Gerrard's Verdict", "Healing Salve"]),
])
def test_w1g8_mind_extraction_discards_every_card_of_the_sacrificed_creatures_colors(
    set_pool, sacrificed, gone,
):
    """"Target player reveals their hand and discards all cards of each of the
    sacrificed creature's colors." The land, the red card and the colorless
    artifact stay, whatever was sacrificed."""
    game = _w1g8_duel(set_pool, hand=["Mind Extraction"], opp_hand=_W1G8_VICTIM_HAND)
    paid = _w1g8_put(game, set_pool, 0, sacrificed)
    bystander = _w1g8_put(game, set_pool, 0, "Grizzly Bears")

    spec = game.cast_target_spec(0, _w1g8_card(set_pool, "Mind Extraction"))
    assert [t["seat"] for t in spec["valid_targets"]] == [0, 1]
    assert {t["name"] for t in spec["cost_spec"]["valid_targets"]} == {
        sacrificed, "Grizzly Bears",
    }
    assert game.queue_from_hand(
        0, "Mind Extraction", target_player_index=1,
        cost_permanent_ids=[paid.permanent_id],
    ).supported
    assert _w1g8_names(game.players[0].graveyard) == [sacrificed], "paid as it was cast"
    assert game.is_on_battlefield(bystander)
    _w1g8_settle(game)

    kept = [name for name in _W1G8_VICTIM_HAND if name not in gone]
    assert _w1g8_names(game.players[1].hand) == kept, game.log
    assert sorted(_w1g8_names(game.players[1].graveyard)) == sorted(gone)
    assert any(
        line.startswith("Opp reveals their hand: Terror, Lightning Bolt")
        for line in game.log
    ), game.log


def test_w1g8_mind_extraction_with_a_colorless_sacrifice_only_reveals(set_pool):
    """"If you sacrifice a colorless creature, you get to see their hand but
    they discard no cards." A colourless creature has no colours for a card to
    be *of* — read as "no narrowing" it would empty the hand."""
    game = _w1g8_duel(set_pool, hand=["Mind Extraction"], opp_hand=_W1G8_VICTIM_HAND)
    _w1g8_put(game, set_pool, 0, "Dodecapod")

    assert game.queue_from_hand(0, "Mind Extraction", target_player_index=1).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].hand) == _W1G8_VICTIM_HAND
    assert game.players[1].graveyard == []
    assert any("Opp reveals their hand" in line for line in game.log)
    assert any("colorless, so nothing is discarded" in line for line in game.log)


def test_w1g8_mind_extraction_reads_the_colour_the_creature_last_had(set_pool):
    """CR 608.2h: the creature is a card in a graveyard by resolution, so its
    colours are the ones it last had on the battlefield — a green Bears turned
    black takes the black cards, and the green Giant Growth stays."""
    hand = ["Terror", "Giant Growth", "Lightning Bolt"]
    game = _w1g8_duel(set_pool, hand=["Mind Extraction"], opp_hand=hand)
    bears = _w1g8_put(game, set_pool, 0, "Grizzly Bears")
    _w1g8_change_color(bears, ["B"], until_eot=True)

    assert game.queue_from_hand(0, "Mind Extraction", target_player_index=1).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].hand) == ["Giant Growth", "Lightning Bolt"]
    assert _w1g8_names(game.players[1].graveyard) == ["Terror"]


def test_w1g8_mind_extraction_cannot_be_cast_with_no_creature_to_sacrifice(set_pool):
    """The additional cost is mandatory (CR 601.2h): no creature, no cast, and
    nothing is spent on the way to the refusal."""
    game = _w1g8_duel(set_pool, hand=["Mind Extraction"], opp_hand=["Terror"])
    before = dict(game.players[0].mana_pool)

    result = game.queue_from_hand(0, "Mind Extraction", target_player_index=1)

    assert not result.supported and "no creature to sacrifice" in result.details
    assert _w1g8_names(game.players[0].hand) == ["Mind Extraction"]
    assert dict(game.players[0].mana_pool) == before
    assert game.stack == [] and _w1g8_names(game.players[1].hand) == ["Terror"]


def test_w1g8_megrim_sees_each_card_mind_extraction_takes(set_pool):
    """Nobody chooses, but they are still discards (CR 701.9a): a watcher fires
    once per card."""
    game = _w1g8_duel(
        set_pool, hand=["Mind Extraction"], opp_hand=["Terror", "Gerrard's Verdict", "Island"],
    )
    _w1g8_put(game, set_pool, 0, "Megrim")
    _w1g8_put(game, set_pool, 0, "Drudge Skeletons")

    assert game.queue_from_hand(0, "Mind Extraction", target_player_index=1).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].hand) == ["Island"]
    assert game.players[1].life == 16, game.log


# --- Gerrard's Verdict ---------------------------------------------------------


@_w1g8_pytest.mark.parametrize("picks, gained", [
    ([0, 2], 6),      # Forest and Island
    ([0, 1], 3),      # Forest and Grizzly Bears
    ([1, 3], 0),      # Grizzly Bears and Terror
])
def test_w1g8_gerrards_verdict_gains_three_per_land_the_player_chose_to_discard(
    set_pool, picks, gained,
):
    """"Target player discards two cards. You gain 3 life for each land card
    discarded this way." The discarding player chooses (CR 701.9b), so nothing
    is gained until they have — and what is counted is what they picked."""
    hand = ["Forest", "Grizzly Bears", "Island", "Terror"]
    game = _w1g8_duel(
        set_pool, hand=["Gerrard's Verdict"], opp_hand=hand, interactive=(0, 1),
    )

    assert game.queue_from_hand(0, "Gerrard's Verdict", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 1)]
    assert game.players[0].life == 20, "the gain waits for the answer"
    assert game.confirm_discard(1, picks)

    assert game.players[0].life == 20 + gained, game.log
    assert sorted(_w1g8_names(game.players[1].graveyard)) == sorted(hand[i] for i in picks)
    assert _w1g8_names(game.players[0].graveyard) == ["Gerrard's Verdict"]


def test_w1g8_gerrards_verdict_counts_what_was_discarded_not_what_was_asked(set_pool):
    """One card in hand is one discard (CR 608.2: as much as possible), and an
    empty hand is none — the printed "two" is not the number counted."""
    game = _w1g8_duel(set_pool, hand=["Gerrard's Verdict"], opp_hand=["Island"])
    assert game.queue_from_hand(0, "Gerrard's Verdict", target_player_index=1).supported
    _w1g8_settle(game)
    assert game.players[0].life == 23 and game.players[1].hand == []

    game = _w1g8_duel(set_pool, hand=["Gerrard's Verdict"])
    assert game.queue_from_hand(0, "Gerrard's Verdict", target_player_index=1).supported
    _w1g8_settle(game)
    assert game.players[0].life == 20
    assert _w1g8_names(game.players[0].graveyard) == ["Gerrard's Verdict"]


def test_w1g8_a_land_put_on_the_library_by_library_of_leng_is_not_a_land_card_discarded(
    set_pool,
):
    """CR 701.9c: a card discarded into a hidden zone unrevealed has undefined
    characteristics, so it is discarded and is not "a land card"."""
    game = _w1g8_duel(
        set_pool, hand=["Gerrard's Verdict"], opp_hand=["Forest", "Island"],
        interactive=(0, 1),
    )
    _w1g8_put(game, set_pool, 1, "Library of Leng")

    assert game.queue_from_hand(0, "Gerrard's Verdict", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert game.confirm_discard(1, [0, 1], to_library=True)

    assert game.players[0].life == 20, game.log
    assert _w1g8_names(game.players[1].library[:2]) == ["Forest", "Island"]
    assert game.players[1].graveyard == []


@_w1g8_pytest.mark.parametrize("text", [
    # No step of the effect discarded anything for "this way" to name.
    "You gain 3 life for each land card discarded this way.",
    # What is discarded is a card (CR 701.9a); "each land discarded" is a
    # sentence nobody printed and is not read as a count of lands in play.
    "Target player discards two cards. You gain 3 life for each land discarded this way.",
    # The record holds printed cards, so only what is printed on one is
    # testable — "you control" is not.
    "Target player discards two cards. You gain 3 life for each land card you control discarded this way.",
])
def test_w1g8_a_discarded_card_count_the_record_cannot_answer_is_refused(text):
    probe = _w1g8_mk_card(
        name="Probe", mana_cost="{1}", type_line="Sorcery", oracle_text=text,
    )
    assert not _w1g8_compile(probe).supported


# --- Suppress --------------------------------------------------------------------


def _w1g8_suppress_turn(game) -> None:
    """Start seat 0's turn through the real turn structure, and refill the
    pool the beginning phase emptied."""
    game.start_turn(0)
    game.players[0].mana_pool.update(_W1G8_RICH)


def test_w1g8_suppress_hides_a_hand_until_the_end_of_that_players_next_turn(set_pool):
    """"Target player exiles all cards from their hand face down. At the
    beginning of the end step of that player's next turn, that player returns
    those cards to their hand." Cast on my turn: gone through my end step,
    still gone while they draw and play their turn, back at *their* end step —
    with the card they drew in between untouched."""
    held = ["Terror", "Counterspell", "Island"]
    game = _w1g8_duel(
        set_pool, hand=["Suppress"], opp_hand=held, opp_library=["Swamp"] * 10,
    )
    _w1g8_suppress_turn(game)

    assert game.queue_from_hand(0, "Suppress", target_player_index=1).supported
    _w1g8_settle(game)
    assert game.players[1].hand == []
    assert _w1g8_names(game.players[1].exile) == held

    game.resolve_end_step(0)
    _w1g8_settle(game)
    assert game.players[1].hand == [], "my end step is not theirs"

    game.start_next_turn()
    assert game.active_player_index == 1
    assert _w1g8_names(game.players[1].hand) == ["Swamp"], "they still draw"
    game.resolve_end_step(1)
    assert _w1g8_names(game.stack) == ["Suppress"], "a trigger, on the stack"
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].hand) == ["Swamp", *held], game.log
    assert game.players[1].exile == []
    assert game.delayed_triggers == []


def test_w1g8_suppress_is_face_down_to_every_viewer_and_the_log_names_nothing(set_pool):
    """CR 406.3: a card exiled face down can't be examined by any player — its
    owner included, since nothing here says they may look. The wire sends a
    card back for each, to the opponent, the owner and a spectator alike, and
    neither the exile nor the return writes a card name into the public log."""
    held = ["Terror", "Counterspell"]
    game = _w1g8_duel(set_pool, hand=["Suppress"], opp_hand=held)
    _w1g8_suppress_turn(game)
    game.players[1].exile.append(_w1g8_card(set_pool, "Giant Growth"))  # face up, before

    assert game.queue_from_hand(0, "Suppress", target_player_index=1).supported
    _w1g8_settle(game)

    for viewer in (0, 1, None):
        assert _w1g8_exile_on_the_wire(game, viewer, 1) == [
            "Giant Growth", "<hidden>", "<hidden>",
        ], viewer
    game.resolve_end_step(0)
    game.start_next_turn()
    game.resolve_end_step(1)
    _w1g8_settle(game)

    assert sorted(_w1g8_names(game.players[1].hand)) == ["Counterspell", "Forest", "Terror"]
    assert _w1g8_exile_on_the_wire(game, 0, 1) == ["Giant Growth"]
    told = [line for line in game.log if "Terror" in line or "Counterspell" in line]
    assert told == [], told
    assert sum("returned a face-down card" in line for line in game.log) == 2


def test_w1g8_suppress_cast_on_that_players_own_turn_waits_for_their_next_one(set_pool):
    """"That player's **next** turn": aimed at myself in my own main phase,
    this turn's end step is not the one named, and neither is my opponent's —
    the cards come back a full round later."""
    game = _w1g8_duel(set_pool, hand=["Suppress", "Terror", "Island"])
    _w1g8_suppress_turn(game)

    assert game.queue_from_hand(0, "Suppress", target_player_index=0).supported
    _w1g8_settle(game)
    assert game.players[0].hand == []

    game.resolve_end_step(0)
    _w1g8_settle(game)
    assert game.players[0].hand == [], "this turn is not my next turn"
    game.start_next_turn()
    game.resolve_end_step(1)
    _w1g8_settle(game)
    assert game.players[0].hand == [], "nor is my opponent's turn"
    game.start_next_turn()
    assert game.active_player_index == 0
    game.resolve_end_step(0)
    _w1g8_settle(game)

    assert sorted(_w1g8_names(game.players[0].hand)) == ["Forest", "Island", "Terror"]
    assert game.players[0].exile == []


def test_w1g8_suppress_returns_only_what_is_still_exiled(set_pool):
    """CR 608.2: as much as possible. A card something else took out of exile
    in between is not conjured back, and an empty hand arms a trigger that
    returns nothing."""
    game = _w1g8_duel(set_pool, hand=["Suppress"], opp_hand=["Terror", "Counterspell"])
    _w1g8_suppress_turn(game)
    assert game.queue_from_hand(0, "Suppress", target_player_index=1).supported
    _w1g8_settle(game)
    terror = _w1g8_card(set_pool, "Terror")
    assert game.take_card_from_exile(game.players[1], terror)
    game.put_card_into_graveyard(game.players[1], terror)

    game.resolve_end_step(0)
    game.start_next_turn()
    game.resolve_end_step(1)
    _w1g8_settle(game)

    assert sorted(_w1g8_names(game.players[1].hand)) == ["Counterspell", "Forest"]
    assert _w1g8_names(game.players[1].graveyard) == ["Terror"]

    game = _w1g8_duel(set_pool, hand=["Suppress"])
    _w1g8_suppress_turn(game)
    assert game.queue_from_hand(0, "Suppress", target_player_index=1).supported
    _w1g8_settle(game)
    game.resolve_end_step(0)
    game.start_next_turn()
    game.resolve_end_step(1)
    _w1g8_settle(game)
    assert _w1g8_names(game.players[1].hand) == ["Forest"]
    assert any("no exiled cards to put back" in line for line in game.log)


@_w1g8_pytest.mark.parametrize("target", [0, 1])
def test_w1g8_that_player_returns_those_cards_names_whoever_exiled_them(set_pool, target):
    """The return reads its seat off the per-seat record, not off whichever
    seat the delay happens to hand it — so the same sentence behind a delay
    that binds no player ("the next end step") still gives the hand back to
    the player who lost it. Read off the resolution's target instead, this
    compiled and a caster who aimed it at themselves never saw the cards
    again."""
    probe = _w1g8_mk_card(
        name="Probe", mana_cost="{1}", type_line="Sorcery",
        oracle_text=(
            "Target player exiles all cards from their hand face down. At the "
            "beginning of the next end step, that player returns those cards "
            "to their hand."
        ),
    )
    assert _w1g8_compile(probe).supported
    game = _w1g8_duel(set_pool, hand=["Terror"], opp_hand=["Counterspell"])
    game.players[0].hand.insert(0, probe)
    _w1g8_suppress_turn(game)

    assert game.queue_from_hand(0, "Probe", target_player_index=target).supported
    _w1g8_settle(game)
    assert game.players[target].hand == []
    assert len(game.players[target].exile) == 1

    game.resolve_end_step(0)
    _w1g8_settle(game)

    assert _w1g8_names(game.players[0].hand) == ["Terror"], game.log
    assert _w1g8_names(game.players[1].hand) == ["Counterspell"]
    assert game.players[0].exile == [] and game.players[1].exile == []


@_w1g8_pytest.mark.parametrize("text", [
    # "Those cards" with no step in front that exiled a pile names nothing.
    "At the beginning of the end step of that player's next turn, that player "
    "returns those cards to their hand.",
    # One hand and every player: the actor and the owner are one claim.
    "Each player exiles all cards from your hand face down.",
    # A pick is owed by the seat that makes it; a named seat takes the hand.
    "Target player exiles any number of cards from their hand face down.",
])
def test_w1g8_a_hand_exile_the_handlers_cannot_perform_is_refused(text):
    probe = _w1g8_mk_card(
        name="Probe", mana_cost="{1}", type_line="Sorcery", oracle_text=text,
    )
    assert not _w1g8_compile(probe).supported


# --- Last Caress (driven) ---------------------------------------------------------


def test_w1g8_last_caress_drains_one_and_draws(set_pool):
    """"Target player loses 1 life and you gain 1 life. / Draw a card." Three
    things for three mana, on the opponent or on oneself."""
    game = _w1g8_duel(set_pool, hand=["Last Caress"], library=["Swamp"] * 5)
    spec = game.cast_target_spec(0, _w1g8_card(set_pool, "Last Caress"))
    assert spec["requires_target"] and [t["seat"] for t in spec["valid_targets"]] == [0, 1]

    assert game.queue_from_hand(0, "Last Caress", target_player_index=1).supported
    _w1g8_settle(game)

    assert (game.players[0].life, game.players[1].life) == (21, 19)
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]

    game = _w1g8_duel(set_pool, hand=["Last Caress"], library=["Swamp"] * 5)
    assert game.queue_from_hand(0, "Last Caress", target_player_index=0).supported
    _w1g8_settle(game)
    assert (game.players[0].life, game.players[1].life) == (20, 20)
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]


@_w1g8_pytest.mark.slow
def test_w1g8_the_ai_plays_the_hand_spells_through_whole_games():
    """The three sorceries, Dodecapod and Haunted Angel pinned into both decks
    of six simulated games: each is cast and resolves, none is refused, and no
    step ends owing a prompt one of them armed. (APC is a measured set, so
    other cards' unsupported casts are in the report; only these lines are
    read.)"""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    names = [
        "Mind Extraction", "Gerrard's Verdict", "Suppress", "Dodecapod",
        "Haunted Angel",
    ]
    report = run_ai_simulation(
        [manifest_set_path("APC", include_measured=True)],
        games=6, seed=1337, max_turns=24, required_cards=names,
    )

    assert report.games_completed == 6
    cast = {
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    }
    assert len(cast) >= 4, sorted(cast)
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [i.message for i in report.issues if any(n in i.message for n in names)] == []
    w1g8_nothing_left_owing = not report.steps_left_owing
    assert w1g8_nothing_left_owing, report.steps_left_owing

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================

# ==== W2G1 ============================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ========================================================

# ==== W2G2 ============================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ========================================================

# ==== W2G3 ============================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ========================================================

# ==== W2G4 ============================================================
# W2G4's tests go between this line and the "end W2G4" line.

# ==== end W2G4 ========================================================

# ==== W2G5 ============================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ========================================================
