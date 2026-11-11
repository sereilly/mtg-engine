"""Darksteel sorceries.

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


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
#
# Counters that move: Aether Snap's sweep of every kind and Dismantle's
# "that many" read off the artifact it destroyed.

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import add_counters as _w1g1_add_counters
from engine.named_counters import counter_kinds_on as _w1g1_kinds
from engine.named_counters import counters_on as _w1g1_counters_on
from tests.helpers import settle as _w1g1_settle


def _w1g1_table(set_pool, *, hand=(), interactive=()):
    lea = set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g1_settle(game)
    return game


def _w1g1_put(game, card, seat):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g1_settle(game)
    return permanent


def test_w1g1_aether_snap_removes_every_kind_of_counter_and_exiles_tokens(set_pool):
    """"Remove all counters from all permanents and exile all tokens." Its
    ruling (2004-12-01): "no matter what kind they are" — +1/+1, -1/-1 and
    charge alike, on both sides — and the Spawn token a Spawning Pit made is
    exiled. The Arcbound creatures, 0/0 once their counters are gone, die
    with none, so their modular puts nothing anywhere."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Aether Snap"]])
    pit = _w1g1_put(game, dst["Spawning Pit"], 0)
    _w1g1_add_counters(pit, "charge", 3)
    made = game.activate_permanent_ability(0, "Spawning Pit", ability_index=1)
    assert made.supported, made
    _w1g1_settle(game)
    spawn = next(p for p in game.players[0].battlefield if p.metadata.get("is_token"))
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    coretapper = _w1g1_put(game, dst["Coretapper"], 0)
    bruiser = _w1g1_put(game, dst["Arcbound Bruiser"], 1)
    karstoderm = _w1g1_put(game, dst["Karstoderm"], 1)
    game.place_pt_counters(karstoderm, "-1/-1", 1)
    assert _w1g1_counters_on(pit, "charge") == 1

    result = game.cast_from_hand(0, "Aether Snap")
    assert result.supported, result
    _w1g1_settle(game)

    for permanent in game.all_permanents():
        assert _w1g1_kinds(permanent) == {}, permanent.card.name
    assert pit in game.players[0].battlefield
    assert spawn not in game.players[0].battlefield
    assert not any(p.metadata.get("is_token") for p in game.all_permanents())
    assert worker not in game.players[0].battlefield
    assert bruiser not in game.players[1].battlefield
    assert karstoderm not in game.players[1].battlefield
    # The Worker's modular still named the surviving Coretapper, with nothing
    # to give it.
    assert coretapper in game.players[0].battlefield
    assert "Arcbound Worker: no counters to place" in game.log


def test_w1g1_dismantle_puts_that_many_counters_on_an_artifact_you_control(set_pool):
    """"Destroy target artifact. If that artifact had counters on it, put that
    many +1/+1 counters or charge counters on an artifact you control." The
    count is what it had as it was destroyed (CR 608.2h) — the Bruiser's
    three — and a seat nobody asks takes the +1/+1 option on its creature,
    not on the noncreature artifact offered first."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Dismantle"]])
    pit = _w1g1_put(game, dst["Spawning Pit"], 0)
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    bruiser = _w1g1_put(game, dst["Arcbound Bruiser"], 1)

    result = game.cast_from_hand(0, "Dismantle", target_permanent_ids=[bruiser.permanent_id])
    assert result.supported, result
    _w1g1_settle(game)

    assert bruiser not in game.players[1].battlefield
    assert _w1g1_counters_on(worker, "+1/+1") == 4
    assert _w1g1_kinds(pit) == {}
    # The Bruiser's own modular had only my Worker to name, and its seat
    # declined to feed an opponent's creature.
    assert "P1 declined Arcbound Bruiser (it would help an opponent's permanent)" in game.log


def test_w1g1_dismantle_asks_which_counter_and_which_artifact(set_pool):
    """Its ruling (2020-08-07): "When Dismantle resolves, you choose which type
    of counters you want and choose an artifact you control" — nothing is
    targeted but the destroyed artifact. Driven as an interactive seat: the
    kind, then the artifact, and charge counters on a noncreature one."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Dismantle"]], interactive=(0,))
    coretapper = _w1g1_put(game, dst["Coretapper"], 0)
    pit = _w1g1_put(game, dst["Spawning Pit"], 0)
    bruiser = _w1g1_put(game, dst["Arcbound Bruiser"], 1)

    game.cast_from_hand(0, "Dismantle", target_permanent_ids=[bruiser.permanent_id])
    owed = _w1g1_settle(game, defaults=False)
    assert owed is not None and owed.kind == "mode_choice"
    # Said with the count it places (Darksteel's wave 2, W2G1): "that many".
    assert owed.data["labels"] == ["that many +1/+1 counters", "that many charge counters"]
    game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    owed = _w1g1_settle(game, defaults=False)
    assert owed is not None and owed.kind == "permanent_choice"
    assert owed.data["prompt"] == "Choose an artifact to put that many charge counters on."
    game.confirm_permanent_choice(0, pit.permanent_id)
    _w1g1_settle(game)

    assert _w1g1_counters_on(pit, "charge") == 3
    assert _w1g1_kinds(coretapper) == {}


def test_w1g1_dismantle_on_an_artifact_with_no_counters_puts_none(set_pool):
    """No counters on the destroyed artifact: the condition is false and
    nothing is asked or placed."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Dismantle"]], interactive=(0,))
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    coretapper = _w1g1_put(game, dst["Coretapper"], 1)

    game.cast_from_hand(0, "Dismantle", target_permanent_ids=[coretapper.permanent_id])
    assert _w1g1_settle(game, defaults=False) is None

    assert coretapper not in game.players[1].battlefield
    assert _w1g1_counters_on(worker, "+1/+1") == 1


def test_w1g1_dismantle_still_places_when_the_artifact_survives(set_pool):
    """Its ruling (2020-08-07): "If the target is legal but not destroyed (most
    likely because it has indestructible), you do put counters on an
    artifact." Darksteel Reactor keeps its two charge counters and two more
    land on the Worker."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Dismantle"]])
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    reactor = _w1g1_put(game, dst["Darksteel Reactor"], 1)
    _w1g1_add_counters(reactor, "charge", 2)

    game.cast_from_hand(0, "Dismantle", target_permanent_ids=[reactor.permanent_id])
    _w1g1_settle(game)

    assert reactor in game.players[1].battlefield
    assert _w1g1_counters_on(reactor, "charge") == 2
    assert _w1g1_counters_on(worker, "+1/+1") == 3

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from tests.helpers import settle as _w1g4_settle


def _w1g4_card(set_pool, name):
    """A card by name: Darksteel first, then Alpha, Odyssey, Mirrodin and
    Antiquities."""
    for code in ("DST", "LEA", "ODY", "MRD", "ATQ"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g4_table(set_pool, hand=(), *, mine=(), theirs=(), their_hand=(),
                graveyard=(), interactive=()):
    """Seat 0 to act in its first main phase, mana off, each named
    permanent untapped and able to act."""
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    game = _w1g4_Game(players=[
        _w1g4_PlayerState("A", hand=[card(n) for n in hand],
                          graveyard=[card(n) for n in graveyard],
                          library=[card("Forest")] * 12),
        _w1g4_PlayerState("B", hand=[card(n) for n in their_hand],
                          library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g4_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _w1g4_where(game, name):
    """Every zone holding a card called *name*, as ``"<seat>.<zone>"``."""
    return sorted(
        f"{seat}.{zone}"
        for seat, player in enumerate(game.players)
        for zone in ("hand", "graveyard", "library", "exile")
        for held in getattr(player, zone)
        if held.name == name
    )


def test_w1g4_pulse_of_the_dross_returns_while_the_target_holds_more(set_pool):
    """"Target player reveals three cards from their hand and you choose one
    of them. That player discards that card. Then if that player has more
    cards in hand than you, return Pulse of the Dross to its owner's hand."
    "That player" is the target: five cards, one discarded, four against the
    caster's none — the card comes back."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Dross"],
        their_hand=["Forest", "Island", "Swamp", "Mountain", "Plains"],
    )
    assert game.cast_from_hand(0, "Pulse of the Dross", target_player_index=1).supported
    _w1g4_settle(game)
    assert len(game.players[1].hand) == 4
    assert len(game.players[1].graveyard) == 1
    assert _w1g4_where(game, "Pulse of the Dross") == ["0.hand"]


def test_w1g4_pulse_of_the_dross_counts_the_hand_after_the_discard(set_pool):
    """Both seats answer for themselves: the target shows three of its two
    (it has only two), the caster picks the Swamp. Counted after the discard
    — one card against the caster's one — the target does not have more, so
    the card goes to the graveyard; counted before it, 2 > 1 would have
    returned it."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Dross", "Forest"], their_hand=["Island", "Swamp"],
        interactive={0, 1},
    )
    assert game.cast_from_hand(0, "Pulse of the Dross", target_player_index=1).supported

    def _pick_the_swamp(game, choice):
        names = [game.players[1].hand[i].name for i in choice.data["legal_indices"]]
        assert sorted(names) == ["Island", "Swamp"]
        assert game.confirm_revealed_hand_pick(
            0, choice.data["legal_indices"][names.index("Swamp")]
        )

    _w1g4_settle(game, answers={"revealed_hand_pick": _pick_the_swamp})
    assert [c.name for c in game.players[1].graveyard] == ["Swamp"]
    assert [c.name for c in game.players[1].hand] == ["Island"]
    assert _w1g4_where(game, "Pulse of the Dross") == ["0.graveyard"]


def test_w1g4_pulse_of_the_tangle_returns_while_the_opponent_has_more_creatures(set_pool):
    """Drive list (supported on arrival, and it never returned). The Beast
    makes one creature against the opponent's two: the card comes back; with
    the opponent at one it is a tie and it does not."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Tangle"], theirs=["Grizzly Bears", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Pulse of the Tangle").supported
    _w1g4_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Beast Token"]
    assert _w1g4_where(game, "Pulse of the Tangle") == ["0.hand"]

    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Tangle"], theirs=["Grizzly Bears"],
    )
    game.cast_from_hand(0, "Pulse of the Tangle")
    _w1g4_settle(game)
    assert _w1g4_where(game, "Pulse of the Tangle") == ["0.graveyard"]


def test_w1g4_a_flashed_back_pulse_is_exiled_rather_than_returned(set_pool):
    """CR 702.34a: a spell whose flashback cost was paid is exiled "instead of
    putting it anywhere else any time it would leave the stack" — the Pulse's
    own return included. Recoup grants Pulse of the Tangle flashback; cast
    from the graveyard with the opponent ahead, it makes its Beast and goes to
    exile, not to the hand."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Recoup"], graveyard=["Pulse of the Tangle"],
        theirs=["Grizzly Bears", "Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Recoup", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g4_settle(game)
    assert game.cast_from_hand(0, "Pulse of the Tangle", from_zone="graveyard").supported
    _w1g4_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Beast Token"]
    assert _w1g4_where(game, "Pulse of the Tangle") == ["0.exile"]

def test_w1g4_echoing_ruin_reaches_a_regenerated_target_once(set_pool):
    """Drive list (supported on arrival, and wrong): "Destroy target artifact
    and all other artifacts with the same name as that artifact." The
    targeted Clay Statue spends its one regeneration shield and stays; it is
    not one of "all **other** artifacts", so the sweep does not destroy it a
    second time — it took the other Statue only. Before the sweep excepted
    its target, the shielded Statue died anyway."""
    game, _mine, theirs = _w1g4_table(
        set_pool, ["Echoing Ruin"], theirs=["Clay Statue", "Clay Statue", "Ornithopter"],
    )
    shielded, other, thopter = theirs
    shielded.regeneration_shield = 1
    assert game.cast_from_hand(
        0, "Echoing Ruin", target_permanent_ids=[shielded.permanent_id],
    ).supported
    _w1g4_settle(game)
    assert game.is_on_battlefield(shielded) and shielded.tapped
    assert not game.is_on_battlefield(other)
    assert game.is_on_battlefield(thopter)
    assert [c.name for c in game.players[1].graveyard] == ["Clay Statue"]

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle


def _w1g5_cloud_table(set_pool, *, hands, boards, interactive=()):
    """Alice holds Death Cloud on her first main phase; *hands* and *boards*
    are each seat's cards by name (LEA unless they are Darksteel's)."""
    lea, dst = set_pool("LEA"), set_pool("DST")

    def named(name):
        return dst[name] if name in dst else lea[name]

    game = _W1G5Game(players=[
        _W1G5PlayerState(
            name="Alice", hand=[dst["Death Cloud"]] + [named(n) for n in hands[0]],
            library=[lea["Plains"]] * 10,
        ),
        _W1G5PlayerState(
            name="Bob", hand=[named(n) for n in hands[1]], library=[lea["Island"]] * 10,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat in (0, 1):
        for name in boards[seat]:
            permanent = _W1G5Permanent(card=named(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g5_settle(game)
    return game, placed[0], placed[1]


def test_w1g5_death_cloud_takes_x_of_each_of_four_things_from_each_player(set_pool):
    """"Each player loses X life, discards X cards, sacrifices X creatures of
    their choice, then sacrifices X lands of their choice." X = 2: both seats
    lose 2 life, discard 2 of their 3 cards, give up 2 creatures (Bob has only
    one — as much as possible, CR 609.3) and then 2 lands."""
    game, _mine, _theirs = _w1g5_cloud_table(
        set_pool,
        hands=(["Forest", "Forest", "Island"], ["Island", "Island", "Plains"]),
        boards=(
            ["Grizzly Bears", "Grizzly Bears", "Grizzly Bears", "Forest", "Forest", "Forest"],
            ["Grizzly Bears", "Island", "Island", "Island"],
        ),
    )
    game.cast_from_hand(0, "Death Cloud", x_value=2)
    _w1g5_settle(game)
    alice, bob = game.players

    def names(seat):
        return sorted(p.card.name for p in game.controlled_by(seat))

    assert (alice.life, bob.life) == (18, 18)
    assert (len(alice.hand), len(bob.hand)) == (1, 1)
    assert names(0) == ["Forest", "Grizzly Bears"]
    assert names(1) == ["Island"]
    assert sum(c.name == "Grizzly Bears" for c in alice.graveyard) == 2
    assert sum(c.name == "Island" for c in bob.graveyard) == 4  # two discarded, two sacrificed


def test_w1g5_death_cloud_asks_each_seat_in_turn_order_and_a_creature_land_goes_once(set_pool):
    """Both seats answer for themselves, the active player first (CR 101.4):
    Alice's discard, then Bob's, then each seat's creature, then each seat's
    land. Alice gives up the Forest Living Lands animated as her creature —
    and by the land sacrifice it is gone, so it is not offered again (the
    card's 2013-06-07 ruling: "it won't be on the battlefield when you
    sacrifice lands")."""
    game, mine, theirs = _w1g5_cloud_table(
        set_pool,
        hands=(["Island"], ["Plains"]),
        boards=(["Living Lands", "Forest", "Grizzly Bears", "Plains"],
                ["Grizzly Bears", "Island", "Island"]),
        interactive=(0, 1),
    )
    living_forest, bears, plains = mine[1], mine[2], mine[3]
    assert living_forest.is_creature
    game.cast_from_hand(0, "Death Cloud", x_value=1)
    asked = []
    for _ in range(8):
        owed = _w1g5_settle(game, defaults=False)
        if owed is None:
            break
        asked.append((owed.kind, owed.player_index, (owed.data.get("filter") or {}).get("type_filter")))
        seat = owed.player_index
        if owed.kind == "discard":
            assert game.confirm_discard(seat, [0])
        elif seat == 0 and asked[-1][2] == "creature":
            assert game.confirm_sacrifice(0, permanent_ids=[living_forest.permanent_id])
        elif seat == 0:
            # The animated Forest went as a creature: offering it now refuses.
            assert not game.confirm_sacrifice(0, permanent_ids=[living_forest.permanent_id])
            assert game.confirm_sacrifice(0, permanent_ids=[plains.permanent_id])
        else:
            wanted = asked[-1][2]
            chosen = next(p for p in game.controlled_by(1) if p.has_type(wanted))
            assert game.confirm_sacrifice(1, permanent_ids=[chosen.permanent_id])
    assert asked == [
        ("discard", 0, None), ("discard", 1, None),
        ("sacrifice", 0, "creature"), ("sacrifice", 1, "creature"),
        ("sacrifice", 0, "land"), ("sacrifice", 1, "land"),
    ]
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Living Lands"]
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Island"]
    assert (game.players[0].life, game.players[1].life) == (19, 19)
    assert any(p is bears for p in game.controlled_by(0))

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Flamebreak: Earthquake's sweep with CR 701.19c's rider on the creatures it
# actually dealt damage to.
from engine import Game as _W1G6Game
from engine.models import Permanent as _W1G6Permanent
from engine.models import PlayerState as _W1G6PlayerState
from engine.regeneration import cant_be_regenerated as _w1g6_cant_be_regenerated

from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    return game


def _w1g6_put(game, seat, card):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g6_flamebreak_burns_the_ground_and_denies_regeneration(set_pool):
    """"Flamebreak deals 3 damage to each creature without flying and each
    player. Creatures dealt damage this way can't be regenerated this turn."
    Both players go to 17; a flier is untouched; Drudge Skeletons dies
    through its regeneration shield; a Wall of Stone survives the 3 and is
    left unable to regenerate for the turn."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[dst["Flamebreak"]])
    angel = _w1g6_put(game, 0, lea["Serra Angel"])
    skeletons = _w1g6_put(game, 1, lea["Drudge Skeletons"])
    skeletons.regeneration_shield = 1
    wall = _w1g6_put(game, 1, lea["Wall of Stone"])
    result = game.cast_from_hand(0, "Flamebreak")
    assert result.supported, result.details
    _w1g6_settle(game)
    assert [player.life for player in game.players] == [17, 17]
    assert game.is_on_battlefield(angel) and angel.damage_marked == 0
    assert not game.is_on_battlefield(skeletons)
    assert [card.name for card in game.players[1].graveyard] == ["Drudge Skeletons"]
    assert game.is_on_battlefield(wall) and wall.damage_marked == 3
    assert _w1g6_cant_be_regenerated(wall)
    assert not _w1g6_cant_be_regenerated(angel)


def test_w1g6_flamebreak_leaves_a_creature_it_did_not_damage_regenerable(set_pool):
    """A creature whose damage was prevented (protection from red, CR
    702.16e) was not dealt damage this way: it keeps its ability to
    regenerate."""
    dst, arn = set_pool("DST"), set_pool("ARN")
    game = _w1g6_table(set_pool, hand=[dst["Flamebreak"]])
    blacksmith = _w1g6_put(game, 1, arn["Repentant Blacksmith"])
    assert game.cast_from_hand(0, "Flamebreak").supported
    _w1g6_settle(game)
    assert game.is_on_battlefield(blacksmith) and blacksmith.damage_marked == 0
    assert not _w1g6_cant_be_regenerated(blacksmith)

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
#
# Scrounge: the opponent's pick out of their own graveyard, read by the
# sentence behind it.
from engine import Game as _W1G9Game
from engine.models import PlayerState as _W1G9PlayerState
from engine.oracle import compile_card_oracle as _w1g9_compile
from engine.targeting import derive_cast_spec as _w1g9_derive_cast_spec

from tests.helpers import settle as _w1g9_settle


def _w1g9_table(set_pool, *, hand=(), opponent_graveyard=()):
    lea = set_pool("LEA")
    alice = _W1G9PlayerState(name="Alice", hand=list(hand), library=[lea["Swamp"]] * 8)
    bob = _W1G9PlayerState(
        name="Bob", library=[lea["Plains"]] * 8, graveyard=list(opponent_graveyard),
    )
    game = _W1G9Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def test_w1g9_scrounge_puts_the_opponents_pick_onto_your_battlefield(set_pool):
    """"Target opponent chooses an artifact card in their graveyard. Put that
    card onto the battlefield under your control." The picker offers an
    opponent; a headless opponent gives up the cheaper artifact (its own pile,
    least valuable first), never the Bears; the card enters under Alice's
    control and stays Bob's (CR 108.3), so when it dies it goes to Bob's
    graveyard."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    scrounge = dst["Scrounge"]
    assert _w1g9_derive_cast_spec(scrounge, _w1g9_compile(scrounge)) == {
        "kind": "player", "opponents_only": True,
    }
    game, alice, bob = _w1g9_table(
        set_pool, hand=[scrounge],
        opponent_graveyard=[lea["Juggernaut"], lea["Grizzly Bears"], lea["Sol Ring"]],
    )
    assert not game.cast_from_hand(0, "Scrounge", target_player_index=0).supported
    result = game.cast_from_hand(0, "Scrounge", target_player_index=1)
    assert result.supported, result.details
    _w1g9_settle(game)
    assert [p.card.name for p in alice.battlefield] == ["Sol Ring"]
    assert [card.name for card in bob.graveyard] == ["Juggernaut", "Grizzly Bears"]
    ring = alice.battlefield[0]
    assert game.owner_index_of(ring) == 1
    assert any("Bob chose Sol Ring in Bob's graveyard" in line for line in game.log)


def test_w1g9_scrounge_asks_an_interactive_opponent_and_waits(set_pool):
    """The pick is the opponent's prompt: the spell stays on the stack until it
    is answered, only the artifact cards are offered, and the card named is
    the one that moves; the owner gets it back when it dies."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(
        set_pool, hand=[dst["Scrounge"], dst["Purge"]],
        opponent_graveyard=[lea["Juggernaut"], lea["Grizzly Bears"], lea["Sol Ring"]],
    )
    game.interactive_seats = {1}
    assert game.cast_from_hand(0, "Scrounge", target_player_index=1).supported
    owed = _w1g9_settle(game, defaults=False)
    assert owed is not None and owed.kind == "graveyard_exile_pick", owed
    assert owed.player_index == 1 and owed.data["destination"] == "chosen"
    assert game.live_graveyard_exile_candidates(owed) == [0, 2]
    assert game.stack, "Scrounge waits on the pick (CR 608.2)"
    assert not game.confirm_graveyard_exile_pick(1, [1]), "the Bears are no artifact"
    assert game.confirm_graveyard_exile_pick(1, [0])
    _w1g9_settle(game)
    assert [p.card.name for p in alice.battlefield] == ["Juggernaut"]
    juggernaut = alice.battlefield[0]
    assert game.cast_from_hand(
        0, "Purge", target_permanent_ids=[juggernaut.permanent_id],
    ).supported
    _w1g9_settle(game)
    assert lea["Juggernaut"] in bob.graveyard and lea["Juggernaut"] not in alice.graveyard


def test_w1g9_scrounge_finds_no_artifact_and_does_nothing(set_pool):
    """A pile with no artifact card asks nobody and moves nothing."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(
        set_pool, hand=[dst["Scrounge"]], opponent_graveyard=[lea["Grizzly Bears"]],
    )
    game.interactive_seats = {1}
    assert game.cast_from_hand(0, "Scrounge", target_player_index=1).supported
    assert _w1g9_settle(game, defaults=False) is None
    assert alice.battlefield == [] and [c.name for c in bob.graveyard] == ["Grizzly Bears"]

# ==== end W1G9 ======================================================


# ==== W2G1 ==========================================================
# Dismantle's choice of kind, as the person reading it is told it: the
# label and the artifact prompt say the count placed (they read "a +1/+1
# counter" while four went on).
from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from engine.models import Permanent as _W2G1Permanent
from engine.named_counters import add_counters as _w2g1_add_counters
from engine.named_counters import counters_on as _w2g1_counters_on
from tests.helpers import settle as _w2g1_settle


def test_w2g1_dismantle_offers_that_many_counters_and_places_that_many(set_pool):
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _W2G1Game(players=[
        _W2G1PlayerState(name=f"P{seat}", library=[lea["Island"]] * 10,
                         hand=[dst["Dismantle"]] if seat == 0 else [])
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.start_turn(0)
    _w2g1_settle(game)
    placed = []
    for seat, card in ((0, lea["Sol Ring"]), (1, dst["Arcbound Worker"])):
        permanent = _W2G1Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, permanent, None)
        placed.append(permanent)
    _w2g1_settle(game)
    ring, worker = placed
    _w2g1_add_counters(worker, "+1/+1", 3)
    held = _w2g1_counters_on(worker, "+1/+1")
    assert held == 4, "modular 1 and three more"
    game.cast_from_hand(0, "Dismantle", target_permanent_ids=[worker.permanent_id])
    owed = _w2g1_settle(game, defaults=False)
    assert owed is not None and owed.kind == "mode_choice"
    assert owed.data["labels"] == ["that many +1/+1 counters", "that many charge counters"]
    game.resolve_pending_choice("mode_choice", 0, mode_index=0)
    owed = _w2g1_settle(game, defaults=False)
    assert owed is not None and owed.kind == "permanent_choice"
    assert owed.data["prompt"] == "Choose an artifact to put that many +1/+1 counters on."
    game.confirm_permanent_choice(0, ring.permanent_id)
    _w2g1_settle(game)
    assert _w2g1_counters_on(ring, "+1/+1") == held

# ==== end W2G1 ======================================================
