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
#
# Mycosynth Lattice: a board-wide layer-4 card-type addition, a layer-5
# colour set reaching every zone and every player's objects, and every
# player's spend-as-any-colour permission (CR 609.4b). Boards are built
# through the entry seam and read after `settle`.

from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from engine.object_colors import card_colors as _w1g8_card_colors
from engine.targeting import derive_cast_spec as _w1g8_cast_spec
from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.helpers import settle as _w1g8_settle


def _w1g8_table(set_pool, *, library=None):
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", library=list(library or [island] * 20))
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g8_put(game, card, seat=0):
    permanent = _W1G8Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._settle()
    return permanent


def _w1g8_lattice(set_pool):
    return set_pool("DST")["Mycosynth Lattice"]


def test_w1g8_lattice_makes_every_permanent_an_artifact(set_pool):
    lea = set_pool("LEA")
    game = _w1g8_table(set_pool)
    forest = _w1g8_put(game, lea["Forest"])
    bears = _w1g8_put(game, lea["Grizzly Bears"])
    crusade = _w1g8_put(game, lea["Crusade"], seat=1)
    angel = _w1g8_put(game, lea["Serra Angel"], seat=1)
    assert not any(p.has_type("artifact") for p in (forest, bears, crusade, angel))

    lattice = _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_settle(game)
    for permanent in (forest, bears, crusade, angel, lattice):
        assert permanent.has_type("artifact"), permanent.card.name
    # CR 205.1b: every other type is kept.
    assert forest.has_type("land") and forest.has_type("forest")
    assert bears.is_creature and bears.has_type("bear")
    assert crusade.has_type("enchantment")

    # A static ability: the Lattice leaving ends it (CR 611.3a).
    game.remove_from_battlefield(lattice)
    _w1g8_settle(game)
    assert not any(p.has_type("artifact") for p in (forest, bears, crusade, angel))


def test_w1g8_lattice_makes_every_object_in_every_zone_colorless(set_pool):
    lea = set_pool("LEA")
    bolt, bears, forest = lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Forest"]
    game = _w1g8_table(set_pool, library=[lea["Giant Growth"]] * 10)
    game.players[0].hand.append(bolt)
    game.players[1].graveyard.append(lea["Dark Ritual"])
    angel = _w1g8_put(game, lea["Serra Angel"], seat=1)
    _w1g8_put(game, bears)
    assert _w1g8_card_colors(game, bolt, 0) == ("R",)
    assert game._effective_colors(angel) == {"W"}

    lattice = _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_settle(game)
    # Permanents, through the layers.
    assert game._effective_colors(angel) == set()
    # Cards in a hand, a library and a graveyard, both players', and whether
    # or not the caller can say whose (the sentence names no seat).
    assert _w1g8_card_colors(game, bolt, 0) == ()
    assert _w1g8_card_colors(game, bolt) == ()
    assert _w1g8_card_colors(game, game.players[1].library[0], 1) == ()
    assert _w1g8_card_colors(game, game.players[1].graveyard[0], 1) == ()
    assert _w1g8_card_colors(game, forest, 0) == ()
    # A spell on the stack.
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game._stack_item_colors(game.stack[-1]) == ()
    _w1g8_settle(game)
    assert game.players[1].life == 17

    game.remove_from_battlefield(lattice)
    _w1g8_settle(game)
    assert game._effective_colors(angel) == {"W"}
    assert _w1g8_card_colors(game, game.players[1].library[0], 1) == ("G",)


def test_w1g8_lattice_lets_every_player_spend_mana_as_any_color(set_pool):
    """CR 609.4b: each player pays a {G} with {C}. Only how the cost may be
    paid changes, never the cost — and with no Lattice the {C} pays
    nothing coloured."""
    lea = set_pool("LEA")
    for with_lattice in (True, False):
        for seat in (0, 1):
            game = _w1g8_table(set_pool)
            game.enforce_mana_costs = True
            game.players[seat].hand.append(lea["Giant Growth"])
            bears = _w1g8_put(game, lea["Grizzly Bears"], seat=seat)
            if with_lattice:
                _w1g8_put(game, _w1g8_lattice(set_pool), seat=0)
            if seat == 1:
                game.start_turn(1)
            _w1g8_settle(game)
            game.players[seat].mana_pool = {
                "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1,
            }
            result = game.cast_from_hand(
                seat, "Giant Growth", target_permanent_ids=[bears.permanent_id],
            )
            assert result.supported is with_lattice, (with_lattice, seat, result)
            _w1g8_settle(game)
            assert bears.effective_power == (5 if with_lattice else 2)


def test_w1g8_lattice_lets_shatter_destroy_a_land_and_stops_terror(set_pool):
    """Every reader of "artifact" follows layer 4: Shatter ("target
    artifact") reaches a land, and Terror ("nonartifact, nonblack creature")
    reaches no creature at all."""
    lea = set_pool("LEA")
    game = _w1g8_table(set_pool)
    game.players[0].hand.extend([lea["Shatter"], lea["Terror"]])
    island = _w1g8_put(game, lea["Island"], seat=1)
    bears = _w1g8_put(game, lea["Grizzly Bears"], seat=1)
    shatter, terror = game.players[0].hand
    shatter_spec = _w1g8_cast_spec(shatter, _w1g8_compile(shatter))
    terror_spec = _w1g8_cast_spec(terror, _w1g8_compile(terror))

    def offered(card, spec):
        return {
            entry["name"]
            for entry in game._enumerate_targets(0, card, spec, for_cast=True)
        }

    assert "Island" not in offered(shatter, shatter_spec)
    assert "Grizzly Bears" in offered(terror, terror_spec)

    _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_settle(game)
    assert "Island" in offered(shatter, shatter_spec)
    assert offered(terror, terror_spec) == set()
    assert not game.cast_from_hand(
        0, "Terror", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.cast_from_hand(
        0, "Shatter", target_permanent_ids=[island.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert not game.is_on_battlefield(island)
    assert island.card in game.players[1].graveyard


def test_w1g8_lattice_lets_a_colorless_white_spell_target_through_protection(set_pool):
    """CR 702.16b: protection from white stops only white objects. Under the
    Lattice Swords to Plowshares is colourless, so Black Knight can be its
    target; without it, it cannot."""
    lea = set_pool("LEA")
    game = _w1g8_table(set_pool)
    game.players[0].hand.append(lea["Swords to Plowshares"])
    knight = _w1g8_put(game, lea["Black Knight"], seat=1)
    assert not game.cast_from_hand(
        0, "Swords to Plowshares", target_permanent_ids=[knight.permanent_id],
    ).supported

    _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_settle(game)
    assert game.cast_from_hand(
        0, "Swords to Plowshares", target_permanent_ids=[knight.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert not game.is_on_battlefield(knight)
    assert game.players[1].life == 22


def test_w1g8_lattice_counts_every_permanent_for_affinity(set_pool):
    """Affinity for artifacts counts what *is* an artifact (CR 702.41a): a
    Lattice, two Forests and a Bears are four, so Myr Enforcer costs {3} —
    and the three Forests' mana pays exactly that."""
    lea = set_pool("LEA")
    game = _w1g8_table(set_pool)
    game.enforce_mana_costs = True
    game.players[0].hand.append(set_pool("MRD")["Myr Enforcer"])
    _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_put(game, lea["Grizzly Bears"])
    _w1g8_put(game, lea["Forest"])
    _w1g8_put(game, lea["Forest"])
    _w1g8_settle(game)
    game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 2, "C": 0}
    assert not game.cast_from_hand(0, "Myr Enforcer").supported
    game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 3, "C": 0}
    assert game.cast_from_hand(0, "Myr Enforcer").supported
    _w1g8_settle(game)
    assert "Myr Enforcer" in [p.card.name for p in game.all_permanents()]

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
#
# The one-offs that are artifacts: Auriok Siege Sled's requirement on an
# "artifact creature", and the rest below as they land.
from engine import Game as _W1G9Game
from engine import ai_declarations as _w1g9_ai_declarations
from engine.models import Permanent as _W1G9Permanent
from engine.models import PlayerState as _W1G9PlayerState
from engine.oracle import compile_card_oracle as _w1g9_compile

from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_table(set_pool, *, hand=(), library=None, opponent_library=None):
    lea = set_pool("LEA")
    alice = _W1G9PlayerState(
        name="Alice", hand=list(hand),
        library=list(library) if library is not None else [lea["Plains"]] * 8,
    )
    bob = _W1G9PlayerState(
        name="Bob",
        library=list(opponent_library) if opponent_library is not None else [lea["Swamp"]] * 8,
    )
    game = _W1G9Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g9_put(game, seat, card, *, sick=False):
    permanent = _W1G9Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g9_slot(game, seat, permanent):
    return game.players[seat].battlefield.index(permanent)


def _w1g9_attack_with(game, seat, attackers):
    game.active_player_index = seat
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [_w1g9_slot(game, seat, each) for each in attackers]
    ok, why = game.declare_attackers(seat, slots, defending_player_index=1 - seat)
    assert ok, why


def test_w1g9_auriok_siege_sled_compels_the_artifact_creature_it_names(set_pool):
    """"{1}: Target artifact creature blocks this creature this turn if able."
    CR 509.1c: with the requirement on Obsianus Golem, a declaration in which
    the Golem does not block the Sled obeys fewer requirements than it could,
    and is illegal — no block, and the Bears blocking alone, both refused."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    sled = dst["Auriok Siege Sled"]
    assert _w1g9_compile(sled).supported
    game, alice, bob = _w1g9_table(set_pool)
    attacker = _w1g9_put(game, 0, sled)
    golem = _w1g9_put(game, 1, lea["Obsianus Golem"])
    bears = _w1g9_put(game, 1, lea["Grizzly Bears"])
    _w1g9_attack_with(game, 0, [attacker])

    refused = game.activate_permanent_ability(
        0, "Auriok Siege Sled", ability_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert not refused.supported, "Grizzly Bears is not an artifact creature"
    result = game.activate_permanent_ability(
        0, "Auriok Siege Sled", ability_index=0, target_permanent_ids=[golem.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_settle(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    sled_slot = _w1g9_slot(game, 0, attacker)
    ai_blocks = _w1g9_ai_declarations.choose_combat_blockers(game, 1)
    assert ai_blocks.get(_w1g9_slot(game, 1, golem)) == sled_slot, ai_blocks
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {_w1g9_slot(game, 1, bears): sled_slot})[0] is False
    ok, why = game.declare_blockers(1, {_w1g9_slot(game, 1, golem): sled_slot})
    assert ok, why
    _w1g9_drive_combat(game)
    assert bob.life == 20
    assert game.is_on_battlefield(golem) and game.is_on_battlefield(attacker)


def test_w1g9_auriok_siege_sled_denies_the_artifact_creature_a_block(set_pool):
    """"{1}: Target artifact creature can't block this creature this turn."
    The Golem may not block the Sled; the Sled's damage reaches Bob."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    attacker = _w1g9_put(game, 0, dst["Auriok Siege Sled"])
    golem = _w1g9_put(game, 1, lea["Obsianus Golem"])
    _w1g9_attack_with(game, 0, [attacker])
    result = game.activate_permanent_ability(
        0, "Auriok Siege Sled", ability_index=1, target_permanent_ids=[golem.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_settle(game)
    game.advance_combat_phase()
    sled_slot = _w1g9_slot(game, 0, attacker)
    assert game.declare_blockers(1, {_w1g9_slot(game, 1, golem): sled_slot})[0] is False
    assert game.declare_blockers(1, {})[0]
    _w1g9_drive_combat(game)
    assert bob.life == 17



def _w1g9_names(player):
    return [permanent.card.name for permanent in player.battlefield]


def test_w1g9_genesis_chamber_gives_each_entering_creatures_controller_a_myr(set_pool):
    """"Whenever a nontoken creature enters, if this artifact is untapped, that
    creature's controller creates a 1/1 colorless Myr artifact creature token."
    Alice's Bears give Alice a Myr and Bob's Zombies give Bob one; the Myr
    entering is a token and sets nothing off; tapped, the Chamber does nothing
    (CR 603.4)."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    chamber = _w1g9_put(game, 0, dst["Genesis Chamber"])
    alice.hand.extend([lea["Grizzly Bears"], lea["Llanowar Elves"]])
    bob.hand.append(lea["Scathe Zombies"])

    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g9_settle(game)
    assert _w1g9_names(alice) == ["Genesis Chamber", "Grizzly Bears", "Myr Token"]
    myr = alice.battlefield[2]
    assert (myr.effective_power, myr.effective_toughness) == (1, 1)
    assert myr.has_type("artifact") and myr.has_type("creature")

    game.active_player_index = 1
    assert game.cast_from_hand(1, "Scathe Zombies").supported
    _w1g9_settle(game)
    assert _w1g9_names(bob) == ["Scathe Zombies", "Myr Token"]
    assert _w1g9_names(alice).count("Myr Token") == 1

    chamber.tapped = True
    game.active_player_index = 0
    assert game.cast_from_hand(0, "Llanowar Elves").supported
    _w1g9_settle(game)
    assert _w1g9_names(alice).count("Myr Token") == 1


def test_w1g9_genesis_chamber_tapped_before_resolution_makes_nothing(set_pool):
    """The intervening "if" is asked again on resolution (CR 603.4): the
    Chamber was untapped as the Bears entered and is tapped in response, so the
    trigger resolves and creates nothing."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    chamber = _w1g9_put(game, 0, dst["Genesis Chamber"])
    alice.hand.append(lea["Grizzly Bears"])
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Genesis Chamber"], game.stack
    chamber.tapped = True
    _w1g9_settle(game)
    assert "Myr Token" not in _w1g9_names(alice)
    assert any("its condition is no longer true" in line for line in game.log)



def test_w1g9_sundering_titan_destroys_a_land_of_each_basic_type_as_it_enters(set_pool):
    """"When this creature enters or leaves the battlefield, choose a land of
    each basic land type, then destroy those lands." A headless controller
    chooses the other seat's lands first and its own only where no other land
    has the type (the ruling, 2020-08-07: "If the only land of a certain type
    is one you control, you must choose it"); Bob's Volcanic Island answers
    Island and Mountain at once ("If a land has more than one basic land type,
    it can be chosen more than once"); no Forest anywhere, so none is chosen."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    alice.hand.append(dst["Sundering Titan"])
    for name in ("Plains", "Swamp", "Mountain"):
        _w1g9_put(game, 0, lea[name])
    _w1g9_put(game, 1, lea["Plains"])
    _w1g9_put(game, 1, set_pool("LEB")["Volcanic Island"])
    assert game.cast_from_hand(0, "Sundering Titan").supported
    _w1g9_settle(game)
    # Bob's Plains, his Volcanic Island for Island and Mountain, Alice's Swamp.
    assert _w1g9_names(alice) == ["Plains", "Mountain", "Sundering Titan"]
    assert _w1g9_names(bob) == []
    assert {"Plains", "Volcanic Island"} == {c.name for c in bob.graveyard}


def test_w1g9_sundering_titan_destroys_again_as_it_leaves(set_pool):
    """The departure half of the same ability (CR 603.1): sacrificed, the
    Titan's controller chooses again and every chosen land is destroyed."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    titan = _w1g9_put(game, 0, dst["Sundering Titan"])
    _w1g9_settle(game)  # its entry finds no land to destroy
    _w1g9_put(game, 0, lea["Island"])
    _w1g9_put(game, 1, lea["Forest"])
    _w1g9_put(game, 1, lea["Forest"])
    game.sacrifice_permanent(titan)
    _w1g9_settle(game)
    assert _w1g9_names(alice) == []
    assert _w1g9_names(bob) == ["Forest"], "one land per type: one Forest of two"


def test_w1g9_sundering_titan_asks_an_interactive_controller_across_both_boards(set_pool):
    """An interactive controller is asked; the candidates are every
    battlefield's lands, and the answer must leave no type it could answer
    unanswered — here Alice destroys her own Plains and spares Bob's."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool)
    game.interactive_seats = {0}
    titan = _w1g9_put(game, 0, dst["Sundering Titan"])
    _w1g9_settle(game)  # its entry finds no land to destroy
    mine = _w1g9_put(game, 0, lea["Plains"])
    theirs = _w1g9_put(game, 1, lea["Plains"])
    swamp = _w1g9_put(game, 1, lea["Swamp"])
    game.sacrifice_permanent(titan)
    owed = _w1g9_settle(game, defaults=False)
    assert owed is not None and owed.kind == "keep_permanents", owed
    assert owed.data["fate"] == "destroy_chosen"
    assert {id(p) for p in game.keep_candidates_of(owed)} == {id(mine), id(theirs), id(swamp)}
    assert not game.confirm_keep_permanents(0, [mine.permanent_id]), "a Swamp is owed"
    assert game.confirm_keep_permanents(0, [mine.permanent_id, swamp.permanent_id])
    _w1g9_settle(game)
    assert _w1g9_names(alice) == [] and _w1g9_names(bob) == ["Plains"]



def test_w1g9_gemini_engine_makes_an_attacking_twin_sacrificed_at_end_of_combat(set_pool):
    """"Whenever this creature attacks, create a colorless Construct artifact
    creature token named Twin that's attacking. Its power is equal to this
    creature's power and its toughness is equal to this creature's toughness.
    Sacrifice the token at end of combat." The Twin "enters as an untapped
    attacking creature" (2004-12-01), deals its 3 beside the Engine's 3, and
    is gone when combat ends (CR 511.2)."""
    dst = set_pool("DST")
    game, alice, bob = _w1g9_table(set_pool)
    engine = _w1g9_put(game, 0, dst["Gemini Engine"])
    _w1g9_attack_with(game, 0, [engine])
    _w1g9_settle(game)
    twin = next(p for p in alice.battlefield if p.card.name == "Twin")
    assert twin.metadata.get("is_token") and twin.attacking and not twin.tapped
    assert (twin.effective_power, twin.effective_toughness) == (3, 4)
    assert twin.has_type("artifact") and twin.has_type("creature") and twin.has_type("Construct")
    assert twin.effective_colors in ((), [], set(), frozenset())
    _w1g9_drive_combat(game)
    assert bob.life == 14
    assert _w1g9_names(alice) == ["Gemini Engine"]


def test_w1g9_gemini_engines_twin_copies_the_engines_pt_once(set_pool):
    """The rulings (2004-12-01): with a Glorious Anthem the Engine is 4/5, the
    Twin "starts as a 4/5, and then the Anthem gives it +1/+1, making the Twin
    a 5/6"; and once created, its P/T "won't change if Gemini Engine's power and
    toughness change" — a Giant Growth on the Engine leaves the Twin alone."""
    dst = set_pool("DST")
    game, alice, bob = _w1g9_table(set_pool)
    _w1g9_put(game, 0, set_pool("7ED")["Glorious Anthem"])
    engine = _w1g9_put(game, 0, dst["Gemini Engine"])
    alice.hand.append(set_pool("2ED")["Giant Growth"])
    _w1g9_attack_with(game, 0, [engine])
    _w1g9_settle(game)
    twin = next(p for p in alice.battlefield if p.card.name == "Twin")
    assert (engine.effective_power, engine.effective_toughness) == (4, 5)
    assert (twin.effective_power, twin.effective_toughness) == (5, 6)
    assert game.cast_from_hand(0, "Giant Growth", target_permanent_ids=[engine.permanent_id]).supported
    _w1g9_settle(game)
    assert engine.effective_power == 7
    assert (twin.effective_power, twin.effective_toughness) == (5, 6)



def _w1g9_dissector_table(set_pool, library_names):
    lea = set_pool("LEA")
    game, alice, bob = _w1g9_table(
        set_pool, opponent_library=[lea[name] for name in library_names],
    )
    dissector = _w1g9_put(game, 0, set_pool("DST")["Thought Dissector"])
    return game, alice, bob, dissector


def test_w1g9_thought_dissector_takes_the_first_artifact_within_x_cards(set_pool):
    """"{X}, {T}: Target opponent reveals cards from the top of their library
    until an artifact card or X cards are revealed, whichever comes first. If
    an artifact card is revealed this way, put it onto the battlefield under
    your control and sacrifice this artifact. Put the rest of the revealed
    cards into that player's graveyard." X=3: two creatures, then Sol Ring —
    the Ring is Alice's to control and Bob's to own, the creatures are milled,
    and the Dissector is sacrificed."""
    game, alice, bob, dissector = _w1g9_dissector_table(
        set_pool, ["Grizzly Bears", "Llanowar Elves", "Sol Ring", "Forest"],
    )
    from engine.targeting import derive_activation_spec as _spec

    ability = _w1g9_compile(dissector.card).activated_abilities[0]
    assert _spec(ability) == {"kind": "player", "opponents_only": True}
    assert not game.activate_permanent_ability(
        0, "Thought Dissector", target_player_index=0, x_value=3,
    ).supported, "an opponent only"
    result = game.activate_permanent_ability(
        0, "Thought Dissector", target_player_index=1, x_value=3,
    )
    assert result.supported, result.details
    _w1g9_settle(game)
    assert _w1g9_names(alice) == ["Sol Ring"]
    assert game.owner_index_of(alice.battlefield[0]) == 1
    assert [c.name for c in bob.graveyard] == ["Grizzly Bears", "Llanowar Elves"]
    assert [c.name for c in bob.library] == ["Forest"]
    assert [c.name for c in alice.graveyard] == ["Thought Dissector"]


def test_w1g9_thought_dissector_stops_after_x_cards_with_no_artifact(set_pool):
    """X=2 runs out first: both creatures go to Bob's graveyard, the Sol Ring
    beneath them stays on top of his library, and nothing is sacrificed."""
    game, alice, bob, dissector = _w1g9_dissector_table(
        set_pool, ["Grizzly Bears", "Llanowar Elves", "Sol Ring", "Forest"],
    )
    assert game.activate_permanent_ability(
        0, "Thought Dissector", target_player_index=1, x_value=2,
    ).supported
    _w1g9_settle(game)
    assert _w1g9_names(alice) == ["Thought Dissector"]
    assert [c.name for c in bob.graveyard] == ["Grizzly Bears", "Llanowar Elves"]
    assert [c.name for c in bob.library] == ["Sol Ring", "Forest"]


def test_w1g9_thought_dissector_gone_in_response_still_delivers_the_artifact(set_pool):
    """The ruling (2004-12-01): "You put the artifact card onto the battlefield
    even if Thought Dissector has already left the battlefield and you can't
    sacrifice it." Sacrificed with the ability on the stack, the Dissector is
    gone, and the Ring still arrives."""
    game, alice, bob, dissector = _w1g9_dissector_table(set_pool, ["Sol Ring"])
    assert game.queue_permanent_ability(
        0, "Thought Dissector", target_player_index=1, x_value=1,
    ).supported
    assert game.stack, "the ability waits on the stack"
    game.sacrifice_permanent(dissector)
    _w1g9_settle(game)
    assert _w1g9_names(alice) == ["Sol Ring"]
    assert [c.name for c in alice.graveyard] == ["Thought Dissector"]



def test_w1g9_eater_of_days_skips_its_controllers_next_two_turns(set_pool):
    """"When this creature enters, you skip your next two turns." CR 614.10a:
    two "next" skips, each spent on one turn — after Alice's turn the next
    three turns are Bob's, and the fourth is hers."""
    dst = set_pool("DST")
    game, alice, bob = _w1g9_table(set_pool)
    alice.hand.append(dst["Eater of Days"])
    assert game.cast_from_hand(0, "Eater of Days").supported
    _w1g9_settle(game)
    assert "Eater of Days" in _w1g9_names(alice)
    assert game.skip_turn_counts.get(0) == 2
    assert any("will skip their next 2 turns" in line for line in game.log)
    assert [game.start_next_turn() for _ in range(4)] == [1, 1, 1, 0], game.log[-12:]
    assert game.skip_turn_counts.get(0, 0) == 0


def test_w1g9_eater_of_days_put_onto_the_battlefield_skips_too(set_pool):
    """The trigger is the entry's, however it entered (CR 603.6a): put onto the
    battlefield by an effect, it still costs two turns; a second Eater stacks
    two more (CR 614.10a: each skip waits for its own turn)."""
    dst = set_pool("DST")
    game, alice, bob = _w1g9_table(set_pool)
    _w1g9_put(game, 0, dst["Eater of Days"])
    _w1g9_settle(game)
    _w1g9_put(game, 0, dst["Eater of Days"])
    _w1g9_settle(game)
    assert game.skip_turn_counts.get(0) == 4

# ==== end W1G9 ======================================================
