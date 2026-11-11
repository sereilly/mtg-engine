"""Darksteel creatures (legendary ones too) — the later groups' sections.

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
# Mephitic Ooze: "destroy that creature. The creature can't be regenerated."
# — the destroy's rider read through the one reader of CR 701.19c's spellings,
# driven through a real combat against a regeneration shield.
from engine import Game as _W1G6Game
from engine.models import Permanent as _W1G6Permanent
from engine.models import PlayerState as _W1G6PlayerState

from tests.helpers import declare_attack as _w1g6_declare_attack
from tests.helpers import drive_combat as _w1g6_drive_combat


def _w1g6_table(set_pool):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", library=[lea["Plains"]] * 8),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 8),
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


def test_w1g6_mephitic_ooze_counts_artifacts_and_destroys_a_shielded_blocker(set_pool):
    """"This creature gets +1/+0 for each artifact you control. Whenever this
    creature deals combat damage to a creature, destroy that creature. The
    creature can't be regenerated." With one artifact the Ooze is 1/5; a
    Wall of Stone (0/8) carrying a regeneration shield blocks it, survives the
    point of damage, and the trigger destroys it all the same — the shield is
    still there, unspent (CR 701.19c)."""
    dst, lea, atq = set_pool("DST"), set_pool("LEA"), set_pool("ATQ")
    game = _w1g6_table(set_pool)
    ooze = _w1g6_put(game, 0, dst["Mephitic Ooze"])
    assert (ooze.effective_power, ooze.effective_toughness) == (0, 5)
    _w1g6_put(game, 0, atq["Ornithopter"], tapped=True)
    game._recompute_continuous_effects()
    assert (ooze.effective_power, ooze.effective_toughness) == (1, 5)
    wall = _w1g6_put(game, 1, lea["Wall of Stone"])
    wall.regeneration_shield = 1
    _w1g6_declare_attack(game, 0, blocks={0: 0})
    _w1g6_drive_combat(game)
    assert not game.is_on_battlefield(wall)
    assert [card.name for card in game.players[1].graveyard] == ["Wall of Stone"]
    assert wall.regeneration_shield == 1, "the shield was never spent"
    assert any("Mephitic Ooze destroyed Wall of Stone" in line for line in game.log)


def test_w1g6_mephitic_ooze_damage_to_a_player_destroys_nothing(set_pool):
    """The trigger is about a *creature* dealt combat damage: unblocked, the
    Ooze's point goes to the player and no creature on either side is
    destroyed."""
    dst, lea, atq = set_pool("DST"), set_pool("LEA"), set_pool("ATQ")
    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, dst["Mephitic Ooze"])
    _w1g6_put(game, 0, atq["Ornithopter"], tapped=True)
    bear = _w1g6_put(game, 1, lea["Grizzly Bears"])
    _w1g6_declare_attack(game, 0)
    _w1g6_drive_combat(game)
    assert game.players[1].life == 19
    assert game.is_on_battlefield(bear)
    assert not any("Mephitic Ooze destroyed" in line for line in game.log)

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), mine=(), theirs=(),
                interactive=()):
    """Costs not enforced, every permanent past summoning sickness and
    untapped, seat 0 active in its first main phase."""
    pools = [set_pool("DST"), set_pool("MRD"), set_pool("LEA")]

    def w1g7_card(name):
        return next(pool[name] for pool in pools if name in pool)

    game = _W1G7Game(players=[
        _W1G7PlayerState(name="W1G7-A", hand=[w1g7_card(n) for n in hand],
                         library=[w1g7_card("Forest") for _ in range(10)]),
        _W1G7PlayerState(name="W1G7-B", hand=[w1g7_card(n) for n in opponent_hand],
                         library=[w1g7_card("Forest") for _ in range(10)]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    rows = []
    for seat, names in ((0, mine), (1, theirs)):
        row = []
        for name in names:
            perm = _W1G7Permanent(card=w1g7_card(name))
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            row.append(perm)
        rows.append(row)
    game.start_turn(0)
    _w1g7_settle(game)
    return game, rows[0], rows[1]  # _w1g7_table


def test_w1g7_pristine_angel_is_protected_exactly_while_untapped(set_pool):
    """"As long as this creature is untapped, it has protection from artifacts
    and from each color." CR 702.16g/h: one ability per quality, so an
    untapped Angel can't be the target of a red Bolt; tapped, it can, and two
    Bolts kill the 4/4."""
    game, mine, _theirs = _w1g7_table(
        set_pool, opponent_hand=["Lightning Bolt"] * 3, mine=["Pristine Angel"],
    )
    angel = mine[0]
    assert game._protection_qualities(angel) == {
        ("card_type", "artifact"), ("color", "W"), ("color", "U"),
        ("color", "B"), ("color", "R"), ("color", "G"),
    }
    game.active_player_index = 1
    refused = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[angel.permanent_id]
    )
    assert not refused.supported
    assert "illegal target" in refused.details
    angel.tapped = True
    assert game._protection_qualities(angel) == set()
    for _ in range(2):
        bolt = game.cast_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[angel.permanent_id]
        )
        assert bolt.supported, bolt.details
        _w1g7_settle(game)
    assert not game.is_on_battlefield(angel)
    assert "Pristine Angel" in [c.name for c in game.players[0].graveyard]


def _w1g7_bolt_the_tapped_angel_and_respond(set_pool):
    """Seat 1 Bolts a tapped Angel; seat 0 Bolts a Bears in response, which
    triggers the Angel's "you may untap" above both spells."""
    game, mine, theirs = _w1g7_table(
        set_pool, hand=["Lightning Bolt"], opponent_hand=["Lightning Bolt"],
        mine=["Pristine Angel"], theirs=["Grizzly Bears"], interactive=[0],
    )
    angel, bears = mine[0], theirs[0]
    angel.tapped = True
    game.active_player_index = 1
    first = game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[angel.permanent_id]
    )
    assert first.supported, first.details
    second = game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    )
    assert second.supported, second.details
    owed = _w1g7_settle(game, defaults=False)
    assert owed is not None and owed.kind == "optional_pay"
    assert owed.player_index == 0
    return game, angel, bears  # _w1g7_bolt_the_tapped_angel_and_respond


def test_w1g7_pristine_angel_untaps_in_response_and_the_bolt_fizzles(set_pool):
    """"Whenever you cast a spell, you may untap this creature." The tapped
    Angel is Bolted; its controller casts a spell in response and says yes to
    the untap as an interactive seat, so the Angel has protection again
    before the first Bolt resolves — its one target is illegal and it does
    nothing (CR 608.2b)."""
    game, angel, bears = _w1g7_bolt_the_tapped_angel_and_respond(set_pool)
    _w1g7_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(
            c.player_index, accept=True
        ),
    })
    assert not angel.tapped
    assert game.is_on_battlefield(angel) and angel.damage_marked == 0
    assert not game.is_on_battlefield(bears)


def test_w1g7_pristine_angel_declined_untap_stays_tapped_and_is_burned(set_pool):
    """The same offer declined: the Angel stays tapped and unprotected, and
    the first Bolt marks its 3 damage."""
    game, angel, bears = _w1g7_bolt_the_tapped_angel_and_respond(set_pool)
    _w1g7_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(
            c.player_index, accept=False
        ),
    })
    assert angel.tapped
    assert game.is_on_battlefield(angel) and angel.damage_marked == 3
    assert not game.is_on_battlefield(bears)


def test_w1g7_pristine_angel_blocking_untapped_takes_no_damage_from_a_red_creature(
    set_pool,
):
    """CR 702.16f is the attacking half, and an attacking Angel is tapped —
    so the case that shows the static in combat is the *blocking* one: an
    untapped Angel blocks a red Hill Giant and takes none of its damage
    (CR 702.16e), and the Giant dies to the Angel's four."""
    game, mine, theirs = _w1g7_table(
        set_pool, mine=["Pristine Angel"], theirs=["Hill Giant"],
    )
    angel = mine[0]
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(0, {0: 0})
    assert ok, why
    from tests.helpers import drive_combat as _w1g7_drive_combat

    _w1g7_drive_combat(game)
    assert game.is_on_battlefield(angel) and angel.damage_marked == 0
    assert not game.is_on_battlefield(theirs[0])


def test_w1g7_tanglewalker_makes_its_side_unblockable_against_an_artifact_land(
    set_pool,
):
    """"Each creature you control can't be blocked as long as defending player
    controls an artifact land." Darksteel Citadel on the defender's side:
    neither attacker can be blocked, and the UI's flag agrees with the step.
    The defender's own creatures are not "creatures you control" for it."""
    game, mine, theirs = _w1g7_table(
        set_pool, mine=["Tanglewalker", "Grizzly Bears"],
        theirs=["Darksteel Citadel", "Grizzly Bears"],
    )
    walker, bears = mine
    blocker = theirs[1]
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0, 1], defending_player_index=1)
    assert ok, why
    assert game.is_unblockable(walker) and game.is_unblockable(bears)
    assert not game.is_unblockable(blocker)
    game.advance_combat_phase()
    for slot in (0, 1):
        ok, _why = game.declare_blockers(1, {1: slot})
        assert not ok
    ok, why = game.declare_blockers(1, {})
    assert ok, why
    from tests.helpers import drive_combat as _w1g7_drive_combat

    _w1g7_drive_combat(game)
    assert game.players[1].life == 20 - 2 - 2


def test_w1g7_tanglewalker_does_nothing_without_an_artifact_land(set_pool):
    """The condition is the card, asked as blockers are declared: the
    defender's Forest and Myr Moonvessel (an artifact that is no land) do not
    satisfy it, so once the Citadel has left before blockers the Moonvessel
    blocks as usual."""
    game, mine, theirs = _w1g7_table(
        set_pool, mine=["Tanglewalker"],
        theirs=["Forest", "Myr Moonvessel", "Darksteel Citadel"],
    )
    walker = mine[0]
    citadel = theirs[2]
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    assert game.is_unblockable(walker)
    # Indestructible, so it leaves the way an indestructible land can.
    assert game.sacrifice_permanent(citadel) is not None
    assert not game.is_on_battlefield(citadel)
    assert not game.is_unblockable(walker)
    game.advance_combat_phase()
    moonvessel_slot = game.battlefield_index_of(theirs[1])
    ok, why = game.declare_blockers(1, {moonvessel_slot: 0})
    assert ok, why


def _w1g7_engineer_mana(set_pool, *, hand=(), mine=(), color=None):
    """Seat 0 taps a Vedalken Engineer for two mana of one colour — as an
    interactive seat answering the colour prompt when *color* is given, as a
    default seat otherwise. Costs enforced from here on."""
    game, board, _theirs = _w1g7_table(
        set_pool, hand=hand, mine=["Vedalken Engineer", *mine],
        interactive=[0] if color else [],
    )
    game.enforce_mana_costs = True
    tapped = game.activate_permanent_ability(0, "Vedalken Engineer")
    assert tapped.supported, tapped.details
    if color:
        owed = _w1g7_settle(game, defaults=False)
        assert owed is not None and owed.kind == "mana_color_choice"
        assert game.resolve_pending_choice("mana_color_choice", 0, color=color)
    _w1g7_settle(game)
    return game, board  # _w1g7_engineer_mana


def _w1g7_restricted(game):
    return {
        key: {symbol: n for symbol, n in bucket.items() if n}
        for key, bucket in game.players[0].restricted_mana.items()
        if any(bucket.values())
    }  # _w1g7_restricted


def test_w1g7_vedalken_engineer_mana_casts_an_artifact_but_not_a_creature_spell(
    set_pool,
):
    """"{T}: Add two mana of any one color. Spend this mana only to cast
    artifact spells or activate abilities of artifacts." Two green from the
    Engineer cannot pay for Grizzly Bears — the cast is refused and the mana
    stays — and then pays for a Myr Moonvessel ({1}), one left over and still
    restricted; none of it ever reaches the ordinary pool (CR 106.6)."""
    game, _board = _w1g7_engineer_mana(
        set_pool, hand=["Grizzly Bears", "Myr Moonvessel"], color="G",
    )
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"G": 2}}
    assert not any(game.players[0].mana_pool.values())
    refused = game.cast_from_hand(0, "Grizzly Bears")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears", "Myr Moonvessel"]
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"G": 2}}
    cast = game.cast_from_hand(0, "Myr Moonvessel")
    assert cast.supported, cast.details
    _w1g7_settle(game)
    assert "Myr Moonvessel" in [p.card.name for p in game.players[0].battlefield]
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"G": 1}}


def test_w1g7_vedalken_engineer_mana_activates_an_artifact_not_a_creature(set_pool):
    """The other half: the mana pays Darksteel Pendant's "{1}, {T}: Scry 1"
    and not Shivan Dragon's "{R}: +1/+0" — a creature's ability is no
    "ability of an artifact" — even when the colour chosen is red."""
    game, board = _w1g7_engineer_mana(
        set_pool, mine=["Darksteel Pendant", "Shivan Dragon"], color="R",
    )
    _engineer, pendant, dragon = board
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"R": 2}}
    firebreath = game.activate_permanent_ability(0, "Shivan Dragon")
    assert not firebreath.supported
    assert dragon.effective_power == 5
    scry = game.activate_permanent_ability(0, "Darksteel Pendant")
    assert scry.supported, scry.details
    _w1g7_settle(game)
    assert pendant.tapped
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"R": 1}}


def test_w1g7_vedalken_engineer_default_seat_makes_the_same_restricted_mana(
    set_pool,
):
    """A seat nobody asks takes the colour prompt's default as it is armed:
    two mana of one colour, under the same restriction."""
    game, _board = _w1g7_engineer_mana(set_pool)
    restricted = _w1g7_restricted(game)
    assert list(restricted) == ["artifact_or_artifact_ability"]
    assert sum(restricted["artifact_or_artifact_ability"].values()) == 2
    assert len(restricted["artifact_or_artifact_ability"]) == 1


# --- W1G7's drive list: Darksteel creatures supported on arrival ---------


def test_w1g7_krark_clan_stoker_sacrifices_an_artifact_for_two_red(set_pool):
    """"{T}, Sacrifice an artifact: Add {R}{R}." With Myr Moonvessel out the
    Stoker makes {R}{R} and the Moonvessel's own death trigger adds {C};
    with no artifact the activation is refused, nothing tapped."""
    game, mine, _theirs = _w1g7_table(
        set_pool, mine=["Krark-Clan Stoker", "Myr Moonvessel"],
    )
    game.enforce_mana_costs = True
    stoker, moonvessel = mine
    assert game.activate_permanent_ability(
        0, "Krark-Clan Stoker", cost_permanent_ids=[moonvessel.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert not game.is_on_battlefield(moonvessel)
    pool = {s: n for s, n in game.players[0].mana_pool.items() if n}
    assert pool == {"R": 2, "C": 1}
    game, mine, _theirs = _w1g7_table(set_pool, mine=["Krark-Clan Stoker"])
    refused = game.activate_permanent_ability(0, "Krark-Clan Stoker")
    assert not refused.supported and not mine[0].tapped


def test_w1g7_hoverguard_observer_blocks_only_fliers(set_pool):
    """"This creature can block only creatures with flying." It may block an
    attacking Pristine Angel (tapped, so unprotected) and not a Grizzly
    Bears."""
    game, mine, theirs = _w1g7_table(
        set_pool, mine=["Grizzly Bears", "Pristine Angel"],
        theirs=["Hoverguard Observer"],
    )
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0, 1], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(1, {0: 0})
    assert not ok
    ok, why = game.declare_blockers(1, {0: 1})
    assert ok, why


def test_w1g7_tel_jilad_outrider_cannot_be_blocked_by_an_artifact_creature(
    set_pool,
):
    """"Protection from artifacts." CR 702.16f: a Myr Moonvessel can't block
    it; a Grizzly Bears can."""
    game, mine, theirs = _w1g7_table(
        set_pool, mine=["Tel-Jilad Outrider"],
        theirs=["Myr Moonvessel", "Grizzly Bears"],
    )
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(1, {0: 0})
    assert not ok
    ok, why = game.declare_blockers(1, {1: 0})
    assert ok, why


def test_w1g7_leonin_battlemage_pumps_and_untaps_when_its_controller_casts(
    set_pool,
):
    """"{T}: Target creature gets +1/+1 until end of turn. Whenever you cast a
    spell, you may untap this creature." It pumps itself to 3/4, the Bolt its
    controller casts offers the untap (an interactive seat says yes), and it
    pumps again to 4/5."""
    game, mine, theirs = _w1g7_table(
        set_pool, hand=["Lightning Bolt"], mine=["Leonin Battlemage"],
        theirs=["Hill Giant"], interactive=[0],
    )
    battlemage = mine[0]
    assert game.activate_permanent_ability(
        0, "Leonin Battlemage", target_permanent_ids=[battlemage.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert battlemage.tapped
    assert (battlemage.effective_power, battlemage.effective_toughness) == (3, 4)
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[theirs[0].permanent_id]
    ).supported
    _w1g7_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(
            c.player_index, accept=True
        ),
    })
    assert not battlemage.tapped
    assert game.activate_permanent_ability(
        0, "Leonin Battlemage", target_permanent_ids=[battlemage.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert (battlemage.effective_power, battlemage.effective_toughness) == (4, 5)


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Neurok Transmuter: CR 613 layer 4's removing half ("…and isn't an
# artifact", CR 205.1a) beside a layer-5 colour set, under one fronted
# duration. Every activation goes through the real activation entry point
# and every board is read after `settle`.

from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.layer_bridge import displayed_type_line as _w1g8_type_line
from engine.models import Permanent as _W1G8Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import derive_activation_spec as _w1g8_activation_spec
from engine.type_changes import lost_types as _w1g8_lost_types
from tests.helpers import settle as _w1g8_settle


def _w1g8_table(set_pool):
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", library=[island] * 20)
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


def _w1g8_transmute(game, target, ability_index=1, *, queue=False):
    """Activate one of the Transmuter's abilities at *target*; with *queue*,
    leave it on the stack (``queue_permanent_ability``) so a second can be
    activated in response."""
    activate = (
        game.queue_permanent_ability if queue else game.activate_permanent_ability
    )
    result = activate(
        0, "Neurok Transmuter", ability_index=ability_index,
        target_permanent_ids=[target.permanent_id],
    )
    assert result.supported, (result, game.log[-4:])
    return result


def test_w1g8_neurok_transmuter_strips_the_artifact_type_until_end_of_turn(set_pool):
    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool("DST")["Neurok Transmuter"])
    myr = _w1g8_put(game, set_pool("MRD")["Myr Enforcer"])
    assert myr.has_type("artifact") and game._effective_colors(myr) == set()

    _w1g8_transmute(game, myr)
    _w1g8_settle(game)

    # Blue, no longer an artifact, still a creature and still a Myr: the
    # artifact type goes and nothing else (the card's 2004-12-01 ruling).
    assert not myr.has_type("artifact")
    assert myr.is_creature and myr.has_type("myr")
    assert game._effective_colors(myr) == {"U"}
    assert _w1g8_type_line(myr) == "Creature — Myr"

    # CR 514.2: both halves end together at cleanup.
    game.resolve_cleanup_step(0)
    assert myr.has_type("artifact") and myr.is_creature
    assert game._effective_colors(myr) == set()
    assert not _w1g8_lost_types(myr)


def test_w1g8_neurok_transmuter_leaves_the_equipment_on(set_pool):
    """An Equipment on the creature is still attached: the creature is still a
    creature, and only the creature lost a type (CR 301.5)."""
    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool("DST")["Neurok Transmuter"])
    myr = _w1g8_put(game, set_pool("MRD")["Myr Enforcer"])
    bone = _w1g8_put(game, set_pool("MRD")["Bonesplitter"])
    game.activate_permanent_ability(
        0, "Bonesplitter", target_permanent_ids=[myr.permanent_id],
    )
    _w1g8_settle(game)
    assert myr.effective_power == 6

    _w1g8_transmute(game, myr)
    _w1g8_settle(game)
    assert not myr.has_type("artifact")
    assert bone.metadata.get("attached_to") is myr
    assert myr.effective_power == 6


def test_w1g8_neurok_transmuter_under_march_leaves_no_types(set_pool):
    """The card's 2004-12-01 ruling: an artifact that is a creature only
    because of March of the Machines loses the artifact type, March no longer
    reaches it, and the permanent has no types whatsoever — and (CR 205.1a)
    no Equipment subtype either."""
    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool("DST")["Neurok Transmuter"])
    _w1g8_put(game, set_pool("MRD")["March of the Machines"])
    bone = _w1g8_put(game, set_pool("MRD")["Bonesplitter"])
    _w1g8_settle(game)
    assert bone.is_creature and bone.has_type("equipment")

    _w1g8_transmute(game, bone)
    _w1g8_settle(game)

    assert game.is_on_battlefield(bone)
    assert _w1g8_type_line(bone) == ""
    assert not bone.is_creature
    assert not bone.has_type("artifact") and not bone.has_type("equipment")
    assert game._effective_colors(bone) == {"U"}

    game.resolve_cleanup_step(0)
    assert bone.is_creature and bone.has_type("equipment")


def test_w1g8_neurok_transmuter_later_effect_wins_and_retargets_are_rechecked(set_pool):
    """The first ability makes a Bears an artifact; the second, later, takes
    it away again (CR 613.7). A second activation answered in response leaves
    the first one's target illegal as it resolves (CR 608.2b), so it changes
    nothing more."""
    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool("DST")["Neurok Transmuter"])
    bears = _w1g8_put(game, set_pool("LEA")["Grizzly Bears"], seat=1)

    _w1g8_transmute(game, bears, ability_index=0)
    _w1g8_settle(game)
    assert bears.has_type("artifact")

    # On the stack, aimed at an artifact creature, and a second in response.
    _w1g8_transmute(game, bears, queue=True)
    _w1g8_transmute(game, bears, queue=True)
    assert [item.card.name for item in game.stack] == ["Neurok Transmuter"] * 2
    _w1g8_settle(game)

    assert not bears.has_type("artifact") and bears.is_creature
    assert game._effective_colors(bears) == {"U"}
    # One removal recorded: the second resolution found no artifact creature.
    assert len(_w1g8_lost_types(bears)) == 1
    assert any("no valid target" in line or "fizzle" in line.lower()
               or "illegal" in line.lower() for line in game.log[-6:]), game.log[-6:]


def test_w1g8_neurok_transmuter_picker_offers_what_each_line_prints(set_pool):
    program = _w1g8_compile(set_pool("DST")["Neurok Transmuter"])
    assert program.supported
    first, second = program.activated_abilities
    assert _w1g8_activation_spec(first)["kind"] == "creature"
    assert _w1g8_activation_spec(second) is not None

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
