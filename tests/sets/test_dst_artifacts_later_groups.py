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
#
# Thunderstaff's static shave of each attacker's combat damage while it is
# untapped, and Talon of Pain's trigger on any source its controller controls
# other than itself — both hollow on arrival, both driven here.
from engine import Game as _W1G6Game
from engine.models import Permanent as _W1G6Permanent
from engine.models import PlayerState as _W1G6PlayerState
from engine.named_counters import counters_on as _w1g6_counters_on

from tests.helpers import declare_attack as _w1g6_declare_attack
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=(), opponent_hand=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8),
        _W1G6PlayerState(
            name="Bob", hand=list(opponent_hand), library=[lea["Island"]] * 8,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    return game


def _w1g6_put(game, seat, card, *, tapped=False):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    game._sync_control()
    return permanent


def test_w1g6_thunderstaff_shaves_one_from_each_attacker_while_untapped(set_pool):
    """"As long as this artifact is untapped, if a creature would deal combat
    damage to you, prevent 1 of that damage." Ruling (2004-12-01): "it
    prevents 1 damage from each creature, each time it would deal combat
    damage to you." A Grizzly Bears and a Hill Giant unblocked: 2 + 3 less one
    each is 3. The same attack with the staff tapped is 5."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, dst["Thunderstaff"])
    _w1g6_put(game, 1, lea["Grizzly Bears"])
    _w1g6_put(game, 1, lea["Hill Giant"])
    _w1g6_declare_attack(game, 1)
    _w1g6_drive_combat(game)
    assert game.players[0].life == 17
    assert sum("prevented 1 of" in line and "Thunderstaff" in line for line in game.log) == 2

    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, dst["Thunderstaff"], tapped=True)
    _w1g6_put(game, 1, lea["Grizzly Bears"])
    _w1g6_put(game, 1, lea["Hill Giant"])
    _w1g6_declare_attack(game, 1)
    _w1g6_drive_combat(game)
    assert game.players[0].life == 15


def test_w1g6_thunderstaff_leaves_noncombat_damage_alone(set_pool):
    """Combat damage only: a Lightning Bolt aimed at the staff's controller
    deals its full 3."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, opponent_hand=[lea["Lightning Bolt"]])
    _w1g6_put(game, 0, dst["Thunderstaff"])
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_settle(game)
    assert game.players[0].life == 17


def test_w1g6_thunderstaff_pumps_attackers(set_pool):
    """"{2}, {T}: Attacking creatures get +1/+0 until end of turn." — and
    tapping it for that switches its shield off for the damage that follows."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, dst["Thunderstaff"])
    bear = _w1g6_put(game, 0, lea["Grizzly Bears"])
    _w1g6_declare_attack(game, 0)
    assert game.activate_permanent_ability(0, "Thunderstaff").supported
    _w1g6_settle(game)
    assert bear.effective_power == 3
    _w1g6_drive_combat(game)
    assert game.players[1].life == 17


def test_w1g6_talon_of_pain_counts_damage_from_its_controllers_other_sources(set_pool):
    """"Whenever a source you control other than this artifact deals damage
    to an opponent, put a charge counter on this artifact." A spell (Lightning
    Bolt) and a creature's combat damage each add one; the opponent's own
    Bolt at its own face adds none."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(
        set_pool, hand=[lea["Lightning Bolt"]], opponent_hand=[lea["Lightning Bolt"]],
    )
    talon = _w1g6_put(game, 0, dst["Talon of Pain"])
    _w1g6_put(game, 0, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(talon, "charge") == 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=1).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(talon, "charge") == 1
    _w1g6_declare_attack(game, 0)
    _w1g6_drive_combat(game)
    assert game.players[1].life == 20 - 3 - 3 - 2
    assert _w1g6_counters_on(talon, "charge") == 2


def test_w1g6_talon_of_pain_spends_its_counters_and_does_not_count_itself(set_pool):
    """"{X}, {T}, Remove X charge counters from this artifact: It deals X
    damage to any target." Two counters off, two damage to the opponent —
    and that damage, being the Talon's own, puts no counter back."""
    dst = set_pool("DST")
    game = _w1g6_table(set_pool)
    talon = _w1g6_put(game, 0, dst["Talon of Pain"])
    talon.metadata["charge_counters"] = 2
    result = game.activate_permanent_ability(
        0, "Talon of Pain", target_player_index=1, x_value=2,
    )
    assert result.supported, result.details
    _w1g6_settle(game)
    assert game.players[1].life == 18
    assert _w1g6_counters_on(talon, "charge") == 0
    assert talon.tapped

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


# --- W1G7's drive list: Darksteel cards supported on arrival -------------


def _w1g7_names(game, seat):
    return sorted(p.card.name for p in game.players[seat].battlefield)  # _w1g7_names


def test_w1g7_darksteel_forge_keeps_artifacts_through_wrath_shatter_and_damage(
    set_pool,
):
    """"Artifacts you control have indestructible." CR 702.12b: a Wrath
    leaves the controller's artifacts and takes the Bears and the opponent's
    Ornithopter; Shatter does nothing to the Moonvessel; 3 damage on a 1/1
    artifact creature is not lethal while the Forge stays — and is the moment
    the Forge leaves (its 2020-08-07 ruling)."""
    game, mine, _theirs = _w1g7_table(
        set_pool, hand=["Wrath of God", "Shatter", "Lightning Bolt"],
        mine=["Darksteel Forge", "Myr Moonvessel", "Grizzly Bears"],
        theirs=["Myr Moonvessel"],
    )
    forge, moonvessel = mine[0], mine[1]
    assert game.cast_from_hand(0, "Wrath of God").supported
    _w1g7_settle(game)
    assert _w1g7_names(game, 0) == ["Darksteel Forge", "Myr Moonvessel"]
    assert _w1g7_names(game, 1) == []
    assert game.cast_from_hand(
        0, "Shatter", target_permanent_ids=[moonvessel.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert game.is_on_battlefield(moonvessel)
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[moonvessel.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert game.is_on_battlefield(moonvessel) and moonvessel.damage_marked == 3
    assert game.sacrifice_permanent(forge) is not None
    _w1g7_settle(game)
    assert not game.is_on_battlefield(moonvessel)


def test_w1g7_myr_matrix_pumps_every_myr_and_makes_more(set_pool):
    """"Indestructible. Myr creatures get +1/+1. {5}: Create a 1/1 colorless
    Myr artifact creature token." Both sides' Myr grow (no "you control"),
    the token enters a 2/2, and Shatter leaves the Matrix where it is."""
    game, mine, theirs = _w1g7_table(
        set_pool, opponent_hand=["Shatter"],
        mine=["Myr Matrix", "Myr Moonvessel"], theirs=["Myr Moonvessel"],
        enforce=True,
    )
    matrix = mine[0]
    assert (mine[1].effective_power, mine[1].effective_toughness) == (2, 2)
    assert (theirs[0].effective_power, theirs[0].effective_toughness) == (2, 2)
    game.players[0].mana_pool["C"] = 5
    assert game.activate_permanent_ability(0, "Myr Matrix").supported
    _w1g7_settle(game)
    tokens = [
        p for p in game.players[0].battlefield if p not in mine
    ]
    assert [(p.effective_power, p.effective_toughness) for p in tokens] == [(2, 2)]
    assert tokens[0].has_type("myr") and tokens[0].has_type("artifact")
    game.enforce_mana_costs = False
    game.active_player_index = 1
    assert game.cast_from_hand(
        1, "Shatter", target_permanent_ids=[matrix.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert game.is_on_battlefield(matrix)


def test_w1g7_darksteels_own_indestructibles_survive_destroy_effects(set_pool):
    """Darksteel Gargoyle, Ingot, Pendant and Citadel each print
    indestructible: a Wrath and a Shatter at each leave every one."""
    names = ["Darksteel Gargoyle", "Darksteel Ingot", "Darksteel Pendant",
             "Darksteel Citadel"]
    game, mine, _theirs = _w1g7_table(
        set_pool, hand=["Wrath of God", *["Shatter"] * 4], mine=names,
    )
    assert game.cast_from_hand(0, "Wrath of God").supported
    _w1g7_settle(game)
    for permanent in mine:
        assert game.cast_from_hand(
            0, "Shatter", target_permanent_ids=[permanent.permanent_id]
        ).supported
        _w1g7_settle(game)
    assert _w1g7_names(game, 0) == sorted(names)


def test_w1g7_the_darksteel_mana_rocks_make_what_they_print(set_pool):
    """Ur-Golem's Eye adds {C}{C}, Darksteel Citadel {C}, Darksteel Ingot one
    mana of the colour an interactive seat names."""
    for rock, color, made in (
        ("Ur-Golem's Eye", None, {"C": 2}),
        ("Darksteel Citadel", None, {"C": 1}),
        ("Darksteel Ingot", "U", {"U": 1}),
    ):
        game, mine, _theirs = _w1g7_table(
            set_pool, mine=[rock], interactive=[0] if color else [], enforce=True,
        )
        assert game.activate_permanent_ability(0, rock).supported
        if color:
            assert game.resolve_pending_choice("mana_color_choice", 0, color=color)
        _w1g7_settle(game)
        assert _w1g7_floating(game, 0) == made, rock
        assert mine[0].tapped


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
