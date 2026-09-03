"""Per-card tests for Fallen Empires' sorceries.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations

# --- G4: costs from the board and the graveyard ---

from engine import Game, PlayerState
from engine.models import Permanent


def _g4_nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g4_game(battlefield, hand, *, graveyard=()):
    p1 = PlayerState(
        name="P1", battlefield=list(battlefield), hand=list(hand),
        graveyard=list(graveyard),
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2


def test_goblin_grenade_cannot_be_cast_without_a_goblin(set_pool):
    """"**As an additional cost to cast this spell, sacrifice a Goblin.** Goblin
    Grenade deals 5 damage to any target."

    The card compiled ``supported`` on its damage line alone while this sentence
    was claimed by nothing and charged by nothing — so it dealt 5 for {R} with
    no Goblin anywhere. CR 601.2h makes an unpayable cost an *uncastable spell*,
    never a free one: nothing is dealt and the spell stays in hand."""
    pool = set_pool("FEM")
    game, p1, p2 = _g4_game([], [pool["Goblin Grenade"]])

    result = game.cast_from_hand(0, "Goblin Grenade", target_player_index=1)
    game._settle()

    assert not result.supported
    assert p2.life == 20
    assert [card.name for card in p1.hand] == ["Goblin Grenade"]


def test_goblin_grenade_eats_a_goblin_and_deals_five(set_pool):
    """With the cost payable the Goblin is sacrificed as the spell is cast
    (CR 601.2b), and the damage lands."""
    pool = set_pool("FEM")
    goblin = _g4_nosick(Permanent(card=pool["Goblin Chirurgeon"]))
    game, p1, p2 = _g4_game([goblin], [pool["Goblin Grenade"]])

    result = game.cast_from_hand(0, "Goblin Grenade", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    assert p2.life == 15
    assert p1.battlefield == []
    assert [card.name for card in p1.graveyard] == [
        "Goblin Chirurgeon", "Goblin Grenade",
    ]


def test_goblin_grenade_will_not_eat_a_creature_that_is_not_a_goblin(set_pool):
    """The subtype is the whole difference between this card and one that costs
    any creature. A board of Merfolk pays nothing."""
    pool = set_pool("FEM")
    merfolk = _g4_nosick(Permanent(card=pool["River Merfolk"]))
    game, p1, p2 = _g4_game([merfolk], [pool["Goblin Grenade"]])

    result = game.cast_from_hand(0, "Goblin Grenade", target_player_index=1)
    game._settle()

    assert not result.supported
    assert p2.life == 20
    assert [perm.card.name for perm in p1.battlefield] == ["River Merfolk"]


def test_soul_exchange_returns_a_creature_and_pays_with_one(set_pool):
    """"As an additional cost to cast this spell, **exile a creature you
    control**. Return target creature card from your graveyard to the
    battlefield…"

    The cost is charged while the spell is being cast, so the exiled creature is
    gone before the returned one arrives."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    homarid = _g4_nosick(Permanent(card=pool["Homarid"]))
    game, p1, _p2 = _g4_game(
        [homarid], [pool["Soul Exchange"]], graveyard=[lea["Grizzly Bears"]]
    )

    result = game.cast_from_hand(0, "Soul Exchange", target_permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert [card.name for card in p1.exile] == ["Homarid"]
    assert [perm.card.name for perm in p1.battlefield] == ["Grizzly Bears"]


def test_soul_exchange_cannot_be_cast_with_no_creature_to_exile(set_pool):
    """CR 601.2h again: with nothing to pay the additional cost the spell is not
    cast, and the creature card stays in the graveyard."""
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    game, p1, _p2 = _g4_game(
        [], [pool["Soul Exchange"]], graveyard=[lea["Grizzly Bears"]]
    )

    result = game.cast_from_hand(0, "Soul Exchange")
    game._settle()

    assert not result.supported
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]
    assert [card.name for card in p1.hand] == ["Soul Exchange"]


def test_soul_exchange_counters_the_returned_creature_only_for_a_thrull(set_pool):
    """"Put a +2/+2 counter on that creature **if the exiled creature was a
    Thrull**."

    Two things at once. "That creature" is the permanent the sentence in front
    of it created — not the spell's target, which is a card in a graveyard — and
    the condition reads back what the *cost* ate, which by then is a memory the
    payment path kept (CR 608.2h).
    """
    pool = set_pool("FEM")
    lea = set_pool("LEA")

    def cast_paying_with(name):
        payment = _g4_nosick(Permanent(card=pool[name]))
        game, p1, _p2 = _g4_game(
            [payment], [pool["Soul Exchange"]], graveyard=[lea["Grizzly Bears"]]
        )
        assert game.cast_from_hand(
            0, "Soul Exchange", target_permanent_index=0
        ).supported
        game._settle()
        bears = next(
            perm for perm in p1.battlefield if perm.card.name == "Grizzly Bears"
        )
        return bears.effective_power, bears.effective_toughness

    assert cast_paying_with("Armor Thrull") == (4, 4), "a Thrull paid: +2/+2"
    assert cast_paying_with("Homarid") == (2, 2), "no Thrull, no counter"


# --- W3-divided: the divided-target announcement ---
#
# CR 601.2d is announced as the spell is cast, and nothing outside the browser
# had a field to announce it in -- so every AI cast of a divided spell arrived
# with no division at all. For a spell whose printed noun names only creatures,
# the resolver then fell through to the engine's older single-target path,
# whose only reading of the announcement is ``target_player_index``.


def test_dwarven_catapult_divides_evenly_over_the_opponents_creatures(set_pool):
    """"Dwarven Catapult deals X damage divided evenly, rounded down, among all
    creatures target opponent controls."

    It names no player, so a seat is not a legal target of it (CR 601.2c) --
    and with no division announced the card burned a player's face for X
    instead of dividing among a board. An evenly-divided spell announces no
    *shares* (CR 601.2d asks a division only of a caster who chooses one), so
    the announcement is the target list alone and the engine splits it.
    """
    from engine import Game
    from engine.ai_policy import choose_divided_targets
    from engine.models import Permanent, PlayerState

    pool = set_pool("FEM")
    lea = set_pool("LEA")
    p0 = PlayerState(name="P0", life=20, hand=[pool["Dwarven Catapult"]])
    p1 = PlayerState(
        name="P1", life=20,
        battlefield=[Permanent(card=lea["Hill Giant"]) for _ in range(2)],
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)

    catapult = pool["Dwarven Catapult"]
    announced = choose_divided_targets(game, 0, catapult, 2)
    result = game.cast_from_hand(
        0, "Dwarven Catapult", target_player_index=1, x_value=2,
        divided_targets=announced,
    )
    game._settle()

    assert result.supported, result.details
    assert announced == [(1, 0), (1, 1)], announced
    assert game.players[1].life == 20, "the card names creatures, not a player"
    assert [perm.damage_marked for perm in game.players[1].battlefield] == [1, 1]


def test_dwarven_catapult_with_no_target_named_is_refused(set_pool):
    """CR 601.2d divides "among **one or more** targets". With no creature to
    divide among, the proposal is illegal and CR 601.2e returns the game to the
    moment before it -- rather than the spell being cast, for its full cost,
    into a face it may not target.
    """
    from engine import Game
    from engine.models import PlayerState

    pool = set_pool("FEM")
    p0 = PlayerState(name="P0", life=20, hand=[pool["Dwarven Catapult"]])
    game = Game(players=[p0, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.cast_from_hand(0, "Dwarven Catapult", target_player_index=1, x_value=3)

    assert not result.supported
    assert "601.2d" in result.details, result.details
    assert [card.name for card in game.players[0].hand] == ["Dwarven Catapult"]
    assert game.players[1].life == 20
# --- end W3-divided ---
