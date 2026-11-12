"""Fifth Dawn instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import settle as _w1g3_settle


def _w1g3_table(set_pool, *, hand=(), opponent_hand=(), graveyard=()):
    """Two seats on seat 0's first main phase with ten-card libraries."""
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 10,
            hand=list(hand if seat == 0 else opponent_hand),
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g3_settle(game)
    return game


def _w1g3_put(game, seat, card):
    permanent = _W1G3Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g3_settle(game)
    return permanent


def _w1g3_where(game, name):
    return [
        f"{seat}.{zone}"
        for seat, player in enumerate(game.players)
        for zone in ("hand", "library", "graveyard", "exile")
        for card in getattr(player, zone)
        if card.name == name
    ]


def test_w1g3_beacon_of_destruction_kills_and_shuffles_itself_away(set_pool):
    """"Beacon of Destruction deals 5 damage to any target. Shuffle Beacon of
    Destruction into its owner's library." The creature dies; the Beacon ends
    in its owner's library — one card longer — and never in the graveyard
    (CR 608.2n's last step is the library's, not the graveyard's)."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(set_pool, hand=[fdn["Beacon of Destruction"]])
    giant = _w1g3_put(game, 1, lea["Hill Giant"])
    assert game.cast_from_hand(
        0, "Beacon of Destruction", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g3_settle(game)

    assert not game.is_on_battlefield(giant)
    assert _w1g3_where(game, "Beacon of Destruction") == ["0.library"]
    assert len(game.players[0].library) == 11
    assert (
        "Beacon of Destruction resolved and was shuffled into its owner's library"
        in game.log
    )


def test_w1g3_beacon_of_destruction_leaves_a_copy_in_the_graveyard_alone(set_pool):
    """Two Beacons are one ``CardDefinition``: with one already in its owner's
    graveyard, the resolving one is shuffled in and the graveyard's stays
    where it is. At a player, five damage."""
    fdn = set_pool("5DN")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Destruction"]],
        graveyard=[fdn["Beacon of Destruction"]],
    )
    assert game.cast_from_hand(0, "Beacon of Destruction", target_player_index=1).supported
    _w1g3_settle(game)
    assert game.players[1].life == 15
    assert sorted(_w1g3_where(game, "Beacon of Destruction")) == ["0.graveyard", "0.library"]


def test_w1g3_beacon_of_destruction_countered_goes_to_the_graveyard(set_pool):
    """Ruling (2007-07-15): "If a Beacon is countered or doesn't resolve, it's
    put into its owner's graveyard, not shuffled into the library." """
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Destruction"]], opponent_hand=[lea["Counterspell"]],
    )
    assert game.queue_from_hand(0, "Beacon of Destruction", target_player_index=1).supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g3_settle(game)
    assert game.players[1].life == 20
    assert _w1g3_where(game, "Beacon of Destruction") == ["0.graveyard"]
    assert len(game.players[0].library) == 10


def test_w1g3_beacon_of_destruction_whose_target_left_is_not_shuffled(set_pool):
    """The same ruling's "doesn't resolve": its one target Bolted in response,
    the Beacon is removed from the stack (CR 608.2b) into its owner's
    graveyard — the shuffle sentence never runs."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Destruction"]], opponent_hand=[lea["Lightning Bolt"]],
    )
    bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Beacon of Destruction", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_where(game, "Beacon of Destruction") == ["0.graveyard"]
    assert len(game.players[0].library) == 10


def test_w1g3_beacon_of_destruction_shuffle_is_announced(set_pool):
    """The shuffle is an effect's shuffle (CR 701.24a), heard by "Whenever a
    spell or ability causes a player to shuffle their library, this artifact
    deals 2 damage to that player." (Psychogenic Probe): the Beacon's owner
    takes 2 — and the opponent, whose library nothing shuffled, does not."""
    fdn = set_pool("5DN")
    game = _w1g3_table(set_pool, hand=[fdn["Beacon of Destruction"]])
    _w1g3_put(game, 1, set_pool("MRD")["Psychogenic Probe"])
    assert game.cast_from_hand(0, "Beacon of Destruction", target_player_index=1).supported
    _w1g3_settle(game)
    assert game.players[0].life == 18, game.log[-6:]
    assert game.players[1].life == 15

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.
from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.equipment import equipped_creature as _w1g4_equipped
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import settle as _w1g4_settle


def _w1g4_theft_table(set_pool):
    """Seat 0 holds Magnetic Theft on its first main phase."""
    island = set_pool("LEA")["Island"]
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P0", library=[island] * 20,
            hand=[set_pool("5DN")["Magnetic Theft"]],
        ),
        _W1G4PlayerState(name="P1", library=[island] * 20),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g4_put(game, card, seat):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g4_settle(game)
    return permanent


def _w1g4_cast_theft(game, equipment, creature):
    return game.cast_from_hand(
        0, "Magnetic Theft",
        target_permanent_ids=[equipment.permanent_id, creature.permanent_id],
    )


def test_w1g4_magnetic_theft_moves_an_equipment_onto_another_players_creature(set_pool):
    """"Attach target Equipment to target creature. (Control of the Equipment
    doesn't change.)" Its 2004-12-01 ruling: it "can cause an Equipment one
    player controls to be attached to a creature another player controls"
    (CR 301.5d). The picker asks for the Equipment, then the creature, and
    offers both players' creatures."""
    mirrodin, alpha = set_pool("MRD"), set_pool("LEA")
    game = _w1g4_theft_table(set_pool)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    mine = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    theirs = _w1g4_put(game, alpha["Grizzly Bears"], 1)

    spec = game.cast_target_spec(0, set_pool("5DN")["Magnetic Theft"])
    assert [role["role"] for role in spec["roles"]] == ["equipment", "creature"]
    (first,) = spec["valid_targets"]
    assert first["name"] == "Bonesplitter"
    assert {(entry["seat"], entry["name"]) for entry in first["next"]} == {
        (0, "Grizzly Bears"), (1, "Grizzly Bears"),
    }

    result = _w1g4_cast_theft(game, splitter, theirs)
    assert result.supported, result.details
    _w1g4_settle(game)

    assert _w1g4_equipped(splitter) is theirs
    assert theirs.effective_power == 4 and mine.effective_power == 2
    assert game.controller_index_of(splitter) == 0


def test_w1g4_a_stolen_equipment_stays_its_owners_to_equip_back(set_pool):
    """The other half of the same ruling: "The controller of the Equipment can
    pay the equip cost to move the Equipment to a creature they control (but
    only any time that player could cast a sorcery)." Magnetic Theft puts the
    opponent's Bonesplitter on the caster's creature; on its controller's own
    turn the equip ability brings it home."""
    mirrodin, alpha = set_pool("MRD"), set_pool("LEA")
    game = _w1g4_theft_table(set_pool)
    mine = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 1)
    theirs = _w1g4_put(game, alpha["Grizzly Bears"], 1)

    _w1g4_cast_theft(game, splitter, mine)
    _w1g4_settle(game)
    assert _w1g4_equipped(splitter) is mine
    assert game.controller_index_of(splitter) == 1
    assert mine.effective_power == 4

    game.start_turn(1)
    result = game.activate_permanent_ability(
        1, splitter.card.name,
        permanent_index=game.battlefield_index_of(splitter),
        target_permanent_ids=[theirs.permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    assert _w1g4_equipped(splitter) is theirs
    assert mine.effective_power == 2


def test_w1g4_magnetic_theft_does_nothing_once_its_creature_is_gone(set_pool):
    """CR 608.2b in response: the creature leaves before Magnetic Theft
    resolves, and the Equipment stays exactly where it was rather than falling
    off or landing on something nobody chose."""
    mirrodin, alpha = set_pool("MRD"), set_pool("LEA")
    game = _w1g4_theft_table(set_pool)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    mine = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    theirs = _w1g4_put(game, alpha["Grizzly Bears"], 1)
    game.activate_permanent_ability(
        0, splitter.card.name, permanent_index=game.battlefield_index_of(splitter),
        target_permanent_ids=[mine.permanent_id],
    )
    _w1g4_settle(game)
    assert _w1g4_equipped(splitter) is mine

    assert game.queue_from_hand(
        0, "Magnetic Theft",
        target_permanent_ids=[splitter.permanent_id, theirs.permanent_id],
    ).supported
    assert game.stack
    game.sacrifice_permanent(theirs)
    _w1g4_settle(game)

    assert not game.is_on_battlefield(theirs)
    assert _w1g4_equipped(splitter) is mine
    assert mine.effective_power == 4
    assert any("no longer legal" in line for line in game.log)


def test_w1g4_magnetic_theft_onto_goblin_brawler_leaves_the_equipment_in_place(set_pool):
    """Goblin Brawler is a legal target for "target creature" — it is not
    protected from anything — and the Equipment fails to move onto it
    (CR 301.5b, 701.3b): it stays on the creature it was equipping."""
    fifth, mirrodin, alpha = set_pool("5DN"), set_pool("MRD"), set_pool("LEA")
    game = _w1g4_theft_table(set_pool)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    brawler = _w1g4_put(game, fifth["Goblin Brawler"], 1)
    game.activate_permanent_ability(
        0, splitter.card.name, permanent_index=game.battlefield_index_of(splitter),
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g4_settle(game)

    assert _w1g4_compile(fifth["Magnetic Theft"]).supported
    assert _w1g4_cast_theft(game, splitter, brawler).supported
    _w1g4_settle(game)
    assert _w1g4_equipped(splitter) is bears
    assert brawler.effective_power == 2
    assert any("can't be equipped" in line for line in game.log)

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_put(game, seat, card):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g6_settle(game)
    return permanent


def test_w1g6_retaliate_destroys_the_creatures_that_damaged_its_caster(set_pool):
    """'Destroy all creatures that dealt damage to you this turn.' The turn's
    damage ledger, asked about the caster: the unblocked Grizzly Bears (combat
    damage) and the Prodigal Sorcerer (a ping) go; the Hill Giant, blocked by
    a Wall, dealt its damage to the Wall and stays; the Llanowar Elves dealt
    none. A creature that dealt damage, left and came back is a new object
    (CR 400.7) that dealt nothing — the Bears' twin bounced and replayed —
    and stays too."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    plains = lea["Plains"]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", library=[plains] * 20),
        _W1G6PlayerState(name="P1", hand=[fdn["Retaliate"]], library=[plains] * 20),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    bears = _w1g6_put(game, 0, lea["Grizzly Bears"])
    twin = _w1g6_put(game, 0, lea["Grizzly Bears"])
    giant = _w1g6_put(game, 0, lea["Hill Giant"])
    sorcerer = _w1g6_put(game, 0, lea["Prodigal Sorcerer"])
    elves = _w1g6_put(game, 0, lea["Llanowar Elves"])
    wall = _w1g6_put(game, 1, lea["Wall of Stone"])

    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    attackers = [game.battlefield_index_of(p) for p in (bears, twin, giant)]
    ok, why = game.declare_attackers(0, attackers, defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {game.battlefield_index_of(wall): game.battlefield_index_of(giant)})
    assert ok, why
    _w1g6_drive_combat(game)
    assert game.players[1].life == 16
    game._set_phase_and_step("postcombat_main", "postcombat_main")
    result = game.activate_permanent_ability(
        0, "Prodigal Sorcerer", permanent_index=game.battlefield_index_of(sorcerer),
        target_player_index=1,
    )
    assert result.supported, result
    _w1g6_settle(game)
    assert game.players[1].life == 15

    # The twin leaves and comes back: a new object, with no damage behind it.
    game.remove_from_battlefield(twin)
    returned = _w1g6_put(game, 0, lea["Grizzly Bears"])

    result = game.cast_from_hand(1, "Retaliate")
    assert result.supported, result
    _w1g6_settle(game)
    assert not game.is_on_battlefield(bears)
    assert not game.is_on_battlefield(sorcerer)
    for survivor in (giant, elves, returned, wall):
        assert game.is_on_battlefield(survivor), survivor.card.name

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.
#
# Plunge into Darkness: "Pay any amount of life, then look at that many
# cards", a resolution-time number that sizes the look; entwined, both modes
# in printed order.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), mine=(), library=(), interactive=()):
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}",
            library=list(library) if seat == 0 else [set_pool("LEA")["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    placed = []
    for card in mine:
        permanent = _W1G7Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    _w1g7_settle(game)
    return game, placed


def _w1g7_library(set_pool):
    lea = set_pool("LEA")
    return [lea[name] for name in (
        "Forest", "Island", "Swamp", "Mountain", "Plains", "Grizzly Bears",
        "Hill Giant", "Llanowar Elves",
    )]


def test_w1g7_plunge_into_darkness_pays_the_life_it_names_and_looks_that_deep(set_pool):
    """The second mode, its ruling (2004-12-01): "choose X, pay X life, look
    at the top X cards of your library, put one into your hand, and exile the
    rest" — all on resolution. Driven as an interactive seat: the number
    prompt offers 0 up to the life total (CR 119.4), 3 is paid, and the look
    is three cards deep; the pick of the Swamp sends the other two to exile."""
    plunge = set_pool("5DN")["Plunge into Darkness"]
    game, _ = _w1g7_table(
        set_pool, hand=[plunge], library=_w1g7_library(set_pool), interactive=(0,),
    )
    player = game.players[0]

    result = game.cast_from_hand(0, "Plunge into Darkness", mode_index=1)
    assert result.supported, result
    owed = _w1g7_settle(game, defaults=False)
    assert owed is not None and owed.kind == "number_choice"
    assert (owed.data["minimum"], owed.data["maximum"]) == (0, 20)
    assert game.confirm_number_choice(0, 3)
    assert player.life == 17
    owed = _w1g7_settle(game, defaults=False)
    assert owed is not None and owed.kind == "look_top_pick"
    assert owed.data["top_count"] == 3
    swamp = next(card for card in player.library[:3] if card.name == "Swamp")
    assert game.confirm_look_top_pick(0, player.library.index(swamp))
    _w1g7_settle(game)

    assert [card.name for card in player.hand] == ["Swamp"]
    assert sorted(card.name for card in player.exile) == ["Forest", "Island"]
    assert [card.name for card in player.library[:1]] == ["Mountain"]
    assert "Plunge into Darkness: P0 paid 3 life (20 -> 17)" in game.log


def test_w1g7_plunge_into_darkness_unasked_pays_a_measured_amount(set_pool):
    """A seat nobody asks names a real amount and keeps clear of the life
    the AI holds back from every optional price (``life_paid_for_a_look``):
    four at 20 life, nothing at 10 — and a payment of nothing looks at
    nothing."""
    plunge = set_pool("5DN")["Plunge into Darkness"]
    game, _ = _w1g7_table(set_pool, hand=[plunge], library=_w1g7_library(set_pool))
    player = game.players[0]

    game.cast_from_hand(0, "Plunge into Darkness", mode_index=1)
    _w1g7_settle(game)

    assert player.life == 16
    assert len(player.hand) == 1 and len(player.exile) == 3
    assert len(player.library) == 4

    game, _ = _w1g7_table(set_pool, hand=[plunge], library=_w1g7_library(set_pool))
    player = game.players[0]
    player.life = 10
    game.cast_from_hand(0, "Plunge into Darkness", mode_index=1)
    _w1g7_settle(game)

    assert player.life == 10
    assert player.hand == [] and player.exile == []
    assert len(player.library) == 8


def test_w1g7_plunge_into_darkness_entwined_sacrifices_then_pays(set_pool):
    """Entwine {B}: both modes in printed order (CR 702.42b; the ruling's
    (1)–(5)) — the creatures go, 3 life comes back for each, and only then is
    the life chosen and paid, so the gain can fund a deeper look."""
    pool = set_pool("5DN")
    lea = set_pool("LEA")
    plunge = pool["Plunge into Darkness"]
    game, (bear, elves) = _w1g7_table(
        set_pool, hand=[plunge], library=_w1g7_library(set_pool),
        mine=[lea["Grizzly Bears"], lea["Llanowar Elves"]], interactive=(0,),
    )
    player = game.players[0]
    player.life = 11

    result = game.cast_from_hand(
        0, "Plunge into Darkness", optional_cost_payments={"{B}": 1},
    )
    assert result.supported, result
    assert game.pending_sacrifice is not None
    assert game.confirm_sacrifice(0, [0, 1]) is True
    owed = _w1g7_settle(game, defaults=False)
    assert owed is not None and owed.kind == "number_choice"
    assert player.life == 17 and owed.data["maximum"] == 17
    game.confirm_number_choice(0, 2)
    _w1g7_settle(game)

    assert player.battlefield == []
    assert player.life == 15
    assert len(player.hand) == 1 and len(player.exile) == 1

# ==== end w1g7 ======================================================
