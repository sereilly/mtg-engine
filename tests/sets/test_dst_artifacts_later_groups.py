"""Darksteel artifacts — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_card(set_pool, name):
    return next(
        pool[name] for pool in (
            set_pool("DST"), set_pool("MRD"), set_pool("LEA"), set_pool("VIS")
        )
        if name in pool
    )  # _w1g7_card


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), mine=(), theirs=(),
                interactive=(), enforce=False):
    """Seat 0 active in its first main phase, every permanent past summoning
    sickness and untapped; costs enforced only when asked."""
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="W1G7-A",
                         hand=[_w1g7_card(set_pool, n) for n in hand],
                         library=[_w1g7_card(set_pool, "Forest") for _ in range(10)]),
        _W1G7PlayerState(name="W1G7-B",
                         hand=[_w1g7_card(set_pool, n) for n in opponent_hand],
                         library=[_w1g7_card(set_pool, "Forest") for _ in range(10)]),
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set(interactive)
    rows = []
    for seat, names in ((0, mine), (1, theirs)):
        row = []
        for name in names:
            row.append(_w1g7_put(game, seat, _w1g7_card(set_pool, name)))
        rows.append(row)
    game.start_turn(0)
    _w1g7_settle(game)
    return game, rows[0], rows[1]  # _w1g7_table


def _w1g7_put(game, seat, card):
    perm = _W1G7Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm  # _w1g7_put


def test_w1g7_drill_skimmer_has_shroud_only_beside_another_artifact_creature(
    set_pool,
):
    """"This creature has shroud as long as you control another artifact
    creature." Alone it is a legal target — "another" (CR 113.7) never counts
    itself; beside a Myr Moonvessel it has shroud and the Bolt is refused; the
    Moonvessel itself gains nothing; with the Moonvessel gone the Bolt is
    legal again and kills it."""
    game, mine, _theirs = _w1g7_table(
        set_pool, opponent_hand=["Lightning Bolt", "Lightning Bolt"],
        mine=["Drill-Skimmer"],
    )
    skimmer = mine[0]
    assert not game._has_keyword(skimmer, "shroud")
    moonvessel = _w1g7_put(game, 0, _w1g7_card(set_pool, "Myr Moonvessel"))
    _w1g7_settle(game)
    assert game._has_keyword(skimmer, "shroud")
    assert not game._has_keyword(moonvessel, "shroud")
    game.active_player_index = 1
    refused = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[skimmer.permanent_id]
    )
    assert not refused.supported and "illegal target" in refused.details
    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[moonvessel.permanent_id]
    )
    assert bolt.supported, bolt.details
    _w1g7_settle(game)
    assert not game.is_on_battlefield(moonvessel)
    assert not game._has_keyword(skimmer, "shroud")
    game.players[1].hand.append(_w1g7_card(set_pool, "Lightning Bolt"))
    finisher = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[skimmer.permanent_id]
    )
    assert finisher.supported, finisher.details
    _w1g7_settle(game)
    assert not game.is_on_battlefield(skimmer)


def test_w1g7_drill_skimmer_gaining_shroud_in_response_counters_the_bolt(set_pool):
    """The Bolt is aimed at a lone Skimmer; before it resolves a second
    artifact creature arrives, the Skimmer has shroud, and its one target is
    illegal (CR 608.2b): the Bolt does nothing. Two Skimmers shroud each
    other."""
    game, mine, _theirs = _w1g7_table(
        set_pool, opponent_hand=["Lightning Bolt"], mine=["Drill-Skimmer"],
    )
    skimmer = mine[0]
    game.active_player_index = 1
    bolt = game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[skimmer.permanent_id]
    )
    assert bolt.supported, bolt.details
    assert game.stack
    second = _w1g7_put(game, 0, _w1g7_card(set_pool, "Drill-Skimmer"))
    _w1g7_settle(game)
    assert game.is_on_battlefield(skimmer) and skimmer.damage_marked == 0
    assert game._has_keyword(skimmer, "shroud")
    assert game._has_keyword(second, "shroud")


def _w1g7_pool(game, seat, **mana):
    pool = game.players[seat].mana_pool
    for symbol in list(pool):
        pool[symbol] = 0
    pool.update(mana)  # _w1g7_pool


def _w1g7_floating(game, seat):
    return {s: n for s, n in game.players[seat].mana_pool.items() if n}  # _w1g7_floating


def test_w1g7_trinisphere_makes_a_one_mana_spell_cost_three(set_pool):
    """"As long as this artifact is untapped, each spell that would cost less
    than three mana to cast costs three mana to cast." Lightning Bolt costs
    {2}{R}: two red is refused with nothing spent and the Bolt still in
    hand, three red casts it — the difference paid with any mana, as the
    reminder says — and the price the client is shown is the price charged."""
    from engine.cost_modifiers import cast_mana_charge

    game, mine, theirs = _w1g7_table(
        set_pool, hand=["Lightning Bolt"], mine=["Trinisphere"],
        theirs=["Hill Giant"], enforce=True,
    )
    bolt = game.players[0].hand[0]
    charge = cast_mana_charge(game, 0, bolt)
    assert (charge["R"], charge["generic"]) == (1, 2)
    _w1g7_pool(game, 0, R=2)
    refused = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[theirs[0].permanent_id]
    )
    assert not refused.supported and "insufficient mana" in refused.details
    assert _w1g7_floating(game, 0) == {"R": 2}
    assert [c.name for c in game.players[0].hand] == ["Lightning Bolt"]
    _w1g7_pool(game, 0, R=1, U=1, C=1)
    cast = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[theirs[0].permanent_id]
    )
    assert cast.supported, cast.details
    _w1g7_settle(game)
    assert _w1g7_floating(game, 0) == {}
    assert theirs[0].damage_marked == 3
    assert "Lightning Bolt costs 3 mana to cast (Trinisphere)" in game.log


def test_w1g7_tapped_trinisphere_imposes_nothing(set_pool):
    """The condition is the card: a tapped Trinisphere leaves the Bolt at
    {R} — and the floor returns the moment it untaps."""
    from engine.cost_modifiers import cast_mana_charge

    game, mine, theirs = _w1g7_table(
        set_pool, hand=["Lightning Bolt", "Lightning Bolt"], mine=["Trinisphere"],
        theirs=["Hill Giant"], enforce=True,
    )
    trinisphere = mine[0]
    trinisphere.tapped = True
    bolt = game.players[0].hand[0]
    assert sum(cast_mana_charge(game, 0, bolt).values()) == 1
    _w1g7_pool(game, 0, R=1)
    cast = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[theirs[0].permanent_id]
    )
    assert cast.supported, cast.details
    _w1g7_settle(game)
    assert theirs[0].damage_marked == 3
    game.become_untapped(trinisphere)
    assert sum(cast_mana_charge(game, 0, game.players[0].hand[0]).values()) == 3


def test_w1g7_trinisphere_raises_a_two_mana_spell_and_leaves_three_alone(set_pool):
    """Grizzly Bears ({1}{G}) costs {2}{G}; Hill Giant ({3}{R}) already costs
    four and is charged four — the floor adds only what a total lacks. It
    reaches the opponent's spells too: "each spell"."""
    game, _mine, _theirs = _w1g7_table(
        set_pool, hand=["Grizzly Bears", "Hill Giant"],
        opponent_hand=["Grizzly Bears"], mine=["Trinisphere"], enforce=True,
    )
    _w1g7_pool(game, 0, G=1, R=1)
    assert not game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g7_pool(game, 0, G=1, R=2)
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    assert _w1g7_floating(game, 0) == {}
    _w1g7_pool(game, 0, R=4)
    assert game.cast_from_hand(0, "Hill Giant").supported
    assert _w1g7_floating(game, 0) == {}
    _w1g7_settle(game)
    game.active_player_index = 1
    _w1g7_pool(game, 1, G=2)
    assert not game.cast_from_hand(1, "Grizzly Bears").supported
    _w1g7_pool(game, 1, G=3)
    assert game.cast_from_hand(1, "Grizzly Bears").supported
    assert _w1g7_floating(game, 1) == {}


def test_w1g7_trinisphere_counts_x_and_comes_after_the_reductions(set_pool):
    """CR 601.2f and the 2020-08-07 ruling: the total — X at the number
    announced, then the increases, then the reductions — and only then the
    floor. Fireball at X=1 ({1}{R}) costs three; at X=2 it already does and
    deals 2. Under Helm of Awakening ("spells cost {1} less") Grizzly Bears
    reaches {G} and is floored back to {2}{G}, not to {1}{G}."""
    game, _mine, _theirs = _w1g7_table(
        set_pool, hand=["Fireball", "Fireball"], mine=["Trinisphere"],
        enforce=True,
    )
    _w1g7_pool(game, 0, R=2)
    assert not game.cast_from_hand(
        0, "Fireball", target_player_index=1, x_value=1
    ).supported
    _w1g7_pool(game, 0, R=3)
    assert game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=1).supported
    _w1g7_settle(game)
    assert game.players[1].life == 19 and _w1g7_floating(game, 0) == {}
    _w1g7_pool(game, 0, R=3)
    assert game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=2).supported
    _w1g7_settle(game)
    assert game.players[1].life == 17 and _w1g7_floating(game, 0) == {}

    game, _mine, _theirs = _w1g7_table(
        set_pool, hand=["Grizzly Bears"], mine=["Trinisphere", "Helm of Awakening"],
        enforce=True,
    )
    _w1g7_pool(game, 0, G=2)
    assert not game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g7_pool(game, 0, G=3)
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    assert _w1g7_floating(game, 0) == {}


def test_w1g7_trinisphere_charges_three_for_a_copy_cast_without_paying(set_pool):
    """"Without paying its mana cost" is an alternative cost of {0} (CR 118.9),
    which the floor raises to {3}: an Isochron Scepter holding a Bolt, with
    five mana, pays {2} to activate and {3} for the copy, which kills the
    Giant. With only the {2}, the copy cannot be paid for and is not cast."""
    for floating, giant_dies in ((5, True), (2, False)):
        game, _mine, theirs = _w1g7_table(
            set_pool, hand=["Isochron Scepter", "Lightning Bolt"],
            mine=["Trinisphere"], theirs=["Hill Giant"],
        )
        assert game.cast_from_hand(0, "Isochron Scepter").supported
        _w1g7_settle(game)
        assert [c.name for c in game.players[0].exile] == ["Lightning Bolt"]
        game.enforce_mana_costs = True
        _w1g7_pool(game, 0, C=floating)
        assert game.activate_permanent_ability(0, "Isochron Scepter").supported
        _w1g7_settle(game)
        assert _w1g7_floating(game, 0) == {}
        assert game.is_on_battlefield(theirs[0]) is not giant_dies
        if giant_dies:
            assert "Lightning Bolt costs 3 mana to cast (Trinisphere)" in game.log


def test_w1g7_the_ai_prices_trinisphere_before_proposing_a_cast(set_pool):
    """The AI's cost reader sees the floor: two Mountains under a
    Trinisphere and it proposes no Bolt (the cast would be refused); three
    and it does, tapping all three."""
    from engine.ai_policy import choose_cast_action

    for lands, proposes in ((2, False), (3, True)):
        game, _mine, _theirs = _w1g7_table(
            set_pool, hand=["Lightning Bolt"],
            mine=["Trinisphere", *["Mountain"] * lands], theirs=["Hill Giant"],
            enforce=True,
        )
        action = choose_cast_action(game, 0)
        assert (action is not None) is proposes
        if proposes:
            assert action.card_name == "Lightning Bolt"
            assert len(action.land_tap_indices) == 3


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
