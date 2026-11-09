"""Mirrodin enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Drive list: Contaminated Bond, whose "its controller" read a record nothing
# wrote until the combat fire sites froze the combatant's seat.
from engine import Game as _W1G2Game
from engine.aura_attachment import attach_aura as _w1g2_attach_aura
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import declare_attack as _w1g2_declare_attack
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", library=[lea["Plains"]] * 8)
    bob = _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 8)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card, *, wearing=None):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    if wearing is not None:
        _w1g2_attach_aura(permanent, wearing)
        game._recompute_continuous_effects()
    return permanent


def _w1g2_drain(game):
    """Answer what blocks the game and drain the stack, until nothing does."""
    for _ in range(20):
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        elif game.stack:
            _w1g2_resolve_stack(game)
        else:
            return


def test_w1g2_contaminated_bond_drains_the_enchanted_creatures_controller(set_pool):
    """"Whenever enchanted creature attacks or blocks, its controller loses 3
    life." Bob's Bond on Alice's Grizzly Bears: Alice loses 3 when the Bears
    attack and 3 when they block — the creature's controller, not the
    Aura's (CR 603.3a gives the Aura's controller the ability; "its" is the
    creature). Before the fire sites froze the seat nobody lost anything."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for blocking in (False, True):
        game, alice, bob = _w1g2_table(set_pool)
        bears = _w1g2_put(game, 0, lea["Grizzly Bears"])
        _w1g2_put(game, 1, lea["Grizzly Bears"])
        _w1g2_put(game, 1, mrd["Contaminated Bond"], wearing=bears)
        if blocking:
            _w1g2_declare_attack(game, 1, blocks={0: 0})
        else:
            _w1g2_declare_attack(game, 0)
        _w1g2_drain(game)
        assert (alice.life, bob.life) == (17, 20), blocking
        assert any("Contaminated Bond: Alice lost 3 life" in line for line in game.log)


def test_w1g2_contaminated_bond_on_its_own_controllers_creature(set_pool):
    """The same seat when the Aura's controller is the creature's: Alice's
    Bond on Alice's own attacker costs Alice the 3."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g2_table(set_pool)
    bears = _w1g2_put(game, 0, lea["Grizzly Bears"])
    _w1g2_put(game, 0, mrd["Contaminated Bond"], wearing=bears)
    _w1g2_declare_attack(game, 0)
    _w1g2_drain(game)
    assert (alice.life, bob.life) == (17, 20)

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.cost_modifiers import cast_mana_charge as _w1g3_charge
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_hum_table(set_pool, mine=(), theirs=(), hand=(), their_hand=(), active=0):
    """Hum of the Radix on seat 0's battlefield beside *mine*; mana costs
    enforced for both seats."""
    mrd = set_pool("MRD")
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[mrd[n] for n in hand]),
        _W1G3PlayerState(name="W1G3-B", hand=[mrd[n] for n in their_hand]),
    ])
    w1g3_game.enforce_mana_costs = True
    w1g3_game.interactive_seats = set()
    w1g3_game.active_player_index = active
    for w1g3_seat, w1g3_names in enumerate((("Hum of the Radix",) + tuple(mine), theirs)):
        for w1g3_name in w1g3_names:
            w1g3_game._put_permanent_onto_battlefield(
                w1g3_seat, _W1G3Permanent(card=mrd[w1g3_name]), None
            )
    return w1g3_game  # _w1g3_hum_table


def _w1g3_tap_all(game, seat):
    for w1g3_land in list(game.controlled_by(seat)):
        if w1g3_land.has_type("land") and not w1g3_land.tapped:
            assert game.tap_land_for_mana(
                seat, w1g3_land.card.name,
                (w1g3_land.effective_produced_mana or ("C",))[0],
                permanent_id=w1g3_land.permanent_id,
            )  # _w1g3_tap_all


def test_w1g3_hum_taxes_each_artifact_spell_by_its_casters_artifacts(set_pool):
    """"Each artifact spell costs {1} more to cast for each artifact its
    controller controls." "Its controller" is the spell's — the player who
    cast it (CR 405.4) — so the Hum taxes its own controller by that
    player's board and an opponent by theirs, and a nonartifact spell not at
    all. Under it, with four artifact lands, Iron Myr is {2}+{4}; Frogmite is
    {4}+{4}-{4} (CR 601.2f: increases, then reductions); a Thoughtcast is just
    its affinity price, {U}. The opponent with two artifacts pays {2} for an
    Ornithopter, and with none pays nothing and is named by no tax."""
    mrd = set_pool("MRD")
    game = _w1g3_hum_table(
        set_pool, mine=["Seat of the Synod"] * 4, theirs=["Great Furnace"] * 2,
    )
    for name, generic in (("Iron Myr", 6), ("Frogmite", 4), ("Thoughtcast", 0)):
        assert _w1g3_charge(game, 0, mrd[name]).get("generic") == generic, name
    assert _w1g3_charge(game, 1, mrd["Ornithopter"]).get("generic") == 2
    assert _w1g3_charge(game, 1, mrd["Thoughtcast"]).get("generic") == 2

    game = _w1g3_hum_table(set_pool)
    assert _w1g3_charge(game, 1, mrd["Ornithopter"]).get("generic") == 0
    assert _w1g3_charge(game, 0, mrd["Iron Myr"]).get("generic") == 2


def test_w1g3_hum_charges_the_cast_and_names_itself_in_the_log(set_pool):
    """The cast path charges what the price readers quote. The Hum's own
    controller casts Frogmite for {4} off four artifact lands (taxed {4},
    discounted {4}) and cannot cast Iron Myr for {6} off the same four. On the
    opponent's turn, their two artifact lands pay the {2} an Ornithopter now
    costs, and the log names the Hum."""
    game = _w1g3_hum_table(
        set_pool, mine=["Seat of the Synod"] * 4, hand=["Iron Myr", "Frogmite"],
    )
    _w1g3_tap_all(game, 0)
    refused = game.cast_from_hand(0, "Iron Myr")
    assert not refused.supported and "insufficient mana" in refused.details
    assert sum(game.players[0].mana_pool.values()) == 4
    cast = game.cast_from_hand(0, "Frogmite")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert "Frogmite is taxed by Hum of the Radix" in game.log
    assert sum(game.players[0].mana_pool.values()) == 0
    assert [p.card.name for p in game.controlled_by(0)].count("Frogmite") == 1

    game = _w1g3_hum_table(
        set_pool, theirs=["Great Furnace"] * 2, their_hand=["Ornithopter"],
        active=1,
    )
    cast = game.cast_from_hand(1, "Ornithopter")
    assert not cast.supported and "insufficient mana" in cast.details
    _w1g3_tap_all(game, 1)
    cast = game.cast_from_hand(1, "Ornithopter")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert "Ornithopter is taxed by Hum of the Radix" in game.log
    assert [p.card.name for p in game.controlled_by(1)].count("Ornithopter") == 1

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.equipment import attach_equipment as _w1g7_attach
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_march_board(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    names = ["Grizzly Bears", "Bonesplitter", "Serum Tank", "Seat of the Synod", "Ornithopter"]
    perms = {
        name: _w1g7_nosick(_w1g7_Permanent(card=mrd[name] if name in mrd else lea[name]))
        for name in names
    }
    p1 = _w1g7_PlayerState(
        name="P1", battlefield=list(perms.values()),
        hand=[mrd["March of the Machines"]], library=[lea["Island"]] * 10,
    )
    p2 = _w1g7_PlayerState(name="P2", library=[lea["Island"]] * 10)
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    assert _w1g7_attach(game, perms["Bonesplitter"], perms["Grizzly Bears"])
    return game, p1, perms


def test_w1g7_march_of_the_machines_animates_each_noncreature_artifact(set_pool):
    """"Each noncreature artifact is an artifact creature with power and
    toughness each equal to its mana value." Titania's Song's sentence without
    the ability loss: a row in `global_statics` beside it.

    The 2004-12-01 rulings, each driven: an Equipment that becomes a creature
    becomes unattached and stays on the battlefield (CR 301.5c, 704.5n); an
    artifact land has mana value 0 and dies as a 0/0 (704.5f); an artifact
    that already was a creature is not a *noncreature* artifact and keeps its
    own P/T. Abilities stay (a Tank is still a Tank). When March leaves, all of
    it ends."""
    game, p1, perms = _w1g7_march_board(set_pool)
    bears, splitter, tank = perms["Grizzly Bears"], perms["Bonesplitter"], perms["Serum Tank"]
    seat, thopter = perms["Seat of the Synod"], perms["Ornithopter"]
    assert (bears.effective_power, bears.effective_toughness) == (4, 2)

    assert game.cast_from_hand(0, "March of the Machines").supported
    _w1g7_resolve(game)
    game.check_state_based_actions()

    assert splitter.is_creature and splitter.has_type("artifact")
    assert (splitter.effective_power, splitter.effective_toughness) == (1, 1)
    assert game.is_on_battlefield(splitter), "unattached, not destroyed"
    assert (bears.effective_power, bears.effective_toughness) == (2, 2), "it fell off"
    assert any("Bonesplitter became unattached" in line for line in game.log)
    assert tank.is_creature and (tank.effective_power, tank.effective_toughness) == (3, 3)
    assert not game.is_on_battlefield(seat)
    assert [c.name for c in p1.graveyard] == ["Seat of the Synod"]
    assert (thopter.effective_power, thopter.effective_toughness) == (0, 2)
    assert game.can_attack(tank, 1), "under its controller's control since the turn began"

    march = next(p for p in p1.battlefield if p.card.name == "March of the Machines")
    game.sacrifice_permanent(march)
    game.check_state_based_actions()
    assert not splitter.is_creature and not tank.is_creature
    assert thopter.is_creature


def test_w1g7_march_of_the_machines_an_artifact_that_just_arrived_is_summoning_sick(set_pool):
    """2009-10-01 ruling: a noncreature permanent that turns into a creature is
    subject to CR 302.6 — one that entered this turn cannot attack."""
    game, p1, _perms = _w1g7_march_board(set_pool)
    assert game.cast_from_hand(0, "March of the Machines").supported
    _w1g7_resolve(game)
    sphere = _w1g7_Permanent(card=set_pool("MRD")["Chromatic Sphere"])
    game._put_permanent_onto_battlefield(0, sphere, None)
    game.check_state_based_actions()
    assert sphere.is_creature and (sphere.effective_power, sphere.effective_toughness) == (1, 1)
    assert not game.can_attack(sphere, 1)


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from engine.oracle import compile_card_oracle as _w1g9_compile
from engine.targeting import derive_cast_spec as _w1g9_derive_cast_spec
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_domineer_board(set_pool, theirs):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(name="P0", hand=[mrd["Domineer"]]),
        _w1g9_PlayerState(
            name="P1", battlefield=[_w1g9_Permanent(card=lea[n]) for n in theirs]
        ),
    ])
    game.enforce_mana_costs = False
    return game


def _w1g9_named(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def test_w1g9_domineer_offers_only_artifact_creatures(set_pool):
    """"Enchant artifact creature": the ruling (2004-12-01) — "The enchanted
    permanent must be both an artifact and a creature." The picker offers the
    Juggernaut and neither the Bears (a creature) nor the Sol Ring (an
    artifact)."""
    game = _w1g9_domineer_board(set_pool, ["Juggernaut", "Grizzly Bears", "Sol Ring"])
    domineer = set_pool("MRD")["Domineer"]
    spec = _w1g9_derive_cast_spec(domineer, _w1g9_compile(domineer))
    offered = game._enumerate_targets(0, domineer, spec, for_cast=True)
    assert sorted(t["name"] for t in offered) == ["Juggernaut"]


def test_w1g9_domineer_takes_control_of_the_artifact_creature(set_pool):
    """"You control enchanted artifact creature." The Juggernaut changes
    sides as Domineer attaches (CR 613 layer 2, the attachment sweep), and a
    cast aimed at the Bears is refused."""
    game = _w1g9_domineer_board(set_pool, ["Juggernaut", "Grizzly Bears"])
    bears = _w1g9_named(game, "Grizzly Bears")
    refused = game.cast_from_hand(
        0, "Domineer", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert not getattr(refused, "supported", True) or not game.stack
    assert [c.name for c in game.players[0].hand] == ["Domineer"]
    juggernaut = _w1g9_named(game, "Juggernaut")
    game.cast_from_hand(
        0, "Domineer", target_player_index=1,
        target_permanent_ids=[juggernaut.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(juggernaut) == 0
    assert _w1g9_named(game, "Domineer").metadata.get("attached_to") is juggernaut


def test_w1g9_domineer_falls_off_an_artifact_that_stops_being_a_creature(set_pool):
    """The ruling (2004-12-01): "Domineer 'falls off' and is put into the
    graveyard if the artifact creature it's enchanting stops being an artifact
    or stops being a creature." A Sol Ring animated by Animate Artifact is
    stolen; destroying Animate Artifact ends the creature type, the CR 704.5m
    sweep bins Domineer, and the Sol Ring goes home."""
    lea = set_pool("LEA")
    game = _w1g9_domineer_board(set_pool, ["Sol Ring"])
    ring = _w1g9_named(game, "Sol Ring")
    game.players[1].hand.append(lea["Animate Artifact"])
    game.cast_from_hand(
        1, "Animate Artifact", target_player_index=1,
        target_permanent_ids=[ring.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert ring.is_creature
    game.cast_from_hand(
        0, "Domineer", target_player_index=1,
        target_permanent_ids=[ring.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(ring) == 0
    game._destroy_target_permanent(
        game.players[1], described={"named": "Animate Artifact"}
    )
    game._settle()
    assert not ring.is_creature
    assert [c.name for c in game.players[0].graveyard] == ["Domineer"]
    assert game.controller_index_of(ring) == 1


def _w1g9_loyalty_board(set_pool):
    """Fractured Loyalty (seat 0's) on seat 1's Grizzly Bears, two Giant
    Growths in each hand."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P0", hand=[mrd["Fractured Loyalty"], lea["Giant Growth"]]
        ),
        _w1g9_PlayerState(
            name="P1", hand=[lea["Giant Growth"]],
            battlefield=[_w1g9_Permanent(card=lea["Grizzly Bears"])],
        ),
    ])
    game.enforce_mana_costs = False
    bears = _w1g9_named(game, "Grizzly Bears")
    game.cast_from_hand(
        0, "Fractured Loyalty", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    return game, bears


def test_w1g9_fractured_loyalty_hands_the_creature_to_whoever_targets_it(set_pool):
    """"Whenever enchanted creature becomes the target of a spell or ability,
    that spell or ability's controller gains control of that creature." P0's
    Giant Growth on P1's Bears hands them to P0 (the trigger resolves first,
    above the spell); P1 targeting them back takes them home."""
    game, bears = _w1g9_loyalty_board(set_pool)
    assert game.controller_index_of(bears) == 1
    game.queue_from_hand(
        0, "Giant Growth", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert [item.card.name for item in game.stack] == [
        "Giant Growth", "Fractured Loyalty",
    ]
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(bears) == 0
    assert "P0 gains control of Grizzly Bears" in game.log
    assert bears.effective_power == 5

    game.cast_from_hand(
        1, "Giant Growth", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(bears) == 1


def test_w1g9_fractured_loyalty_change_lasts_after_the_aura_is_gone(set_pool):
    """"(This effect lasts indefinitely.)" CR 611.2a: the trigger's control
    change has no duration, so neither the Aura leaving *in response* — the
    trigger resolves without its source (CR 113.7a) and still names the
    creature it fired on — nor the Aura being gone afterwards sends the Bears
    back."""
    game, bears = _w1g9_loyalty_board(set_pool)
    game.queue_from_hand(
        0, "Giant Growth", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert len(game.stack) == 2
    # In response to the trigger, the Aura is destroyed.
    game._destroy_target_permanent(
        game.players[0], described={"named": "Fractured Loyalty"}
    )
    assert [c.name for c in game.players[0].graveyard] == ["Fractured Loyalty"]
    assert len(game.stack) == 2
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(bears) == 0
    assert bears.effective_power == 5


def test_w1g9_fractured_loyalty_own_controller_targeting_changes_nothing(set_pool):
    game, bears = _w1g9_loyalty_board(set_pool)
    game.cast_from_hand(
        1, "Giant Growth", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(bears) == 1
    assert "Grizzly Bears is already controlled by P1" in game.log


def _w1g9_confusion_game(set_pool, *, mine=(), theirs=(), hands=((), ())):
    """Confusion in the Ranks on seat 0's battlefield beside *mine*; *theirs*
    on seat 1's; LEA cards in each hand."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P0",
            battlefield=[_w1g9_Permanent(card=mrd["Confusion in the Ranks"])]
            + [_w1g9_Permanent(card=lea[n]) for n in mine],
            hand=[lea[n] for n in hands[0]],
        ),
        _w1g9_PlayerState(
            name="P1",
            battlefield=[_w1g9_Permanent(card=lea[n]) for n in theirs],
            hand=[lea[n] for n in hands[1]],
        ),
    ])
    game.enforce_mana_costs = False
    return game


def _w1g9_seats(game):
    return {p.card.name: game.controller_index_of(p) for p in game.all_permanents()}


def test_w1g9_confusion_in_the_ranks_exchanges_the_entering_creature(set_pool):
    """"Whenever an artifact, creature, or enchantment enters, its controller
    chooses target permanent another player controls that shares a card type
    with it. Exchange control of those permanents." P0's Bears enter and are
    traded for P1's Hill Giant — the creature, not the Sol Ring, which shares
    no type with them."""
    game = _w1g9_confusion_game(
        set_pool, theirs=["Hill Giant", "Sol Ring"], hands=(["Grizzly Bears"], ())
    )
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g9_resolve_stack(game)
    game._settle()
    assert _w1g9_seats(game) == {
        "Confusion in the Ranks": 0, "Hill Giant": 0, "Grizzly Bears": 1,
        "Sol Ring": 1,
    }


def test_w1g9_confusion_in_the_ranks_entering_permanents_controller_chooses(set_pool):
    """"**Its controller** chooses": when P1's Elves enter, the choice is
    P1's — an interactive P1 is asked, offered P0's creatures only (not the
    enchantment, which shares no type with the Elves). Asked as the ability
    goes on the stack since MRD W2G4 (CR 603.3d: the printed "target" is an
    announcement), so the answer is the stacked ability's target."""
    game = _w1g9_confusion_game(
        set_pool, mine=["Grizzly Bears", "Hill Giant"],
        hands=((), ["Llanowar Elves"]),
    )
    game.interactive_seats = {1}
    game.active_player_index = 1
    game.cast_from_hand(1, "Llanowar Elves")
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("trigger_target", 1)
    ]
    offered = game.pending_choices[0].data["targets"]
    assert sorted(entry["name"] for entry in offered) == ["Grizzly Bears", "Hill Giant"]
    assert [item.card.name for item in game.stack] == ["Confusion in the Ranks"]
    giant = _w1g9_named(game, "Hill Giant")
    assert game.confirm_trigger_target(1, permanent_id=giant.permanent_id) is True
    _w1g9_resolve_stack(game)
    game._settle()
    assert _w1g9_seats(game) == {
        "Confusion in the Ranks": 0, "Grizzly Bears": 0, "Llanowar Elves": 0,
        "Hill Giant": 1,
    }


def test_w1g9_confusion_in_the_ranks_trades_itself_for_an_enchantment(set_pool):
    """The ruling (2004-12-01): "Confusion in the Ranks triggers on itself
    entering. If an opponent controls an enchantment, exchange Confusion in the
    Ranks for that enchantment." And the exchange is not optional (2004-10-04)
    — a seat nobody asks takes the one legal choice."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(name="P0", hand=[mrd["Confusion in the Ranks"]]),
        _w1g9_PlayerState(
            name="P1",
            battlefield=[
                _w1g9_Permanent(card=lea["Crusade"]),
                _w1g9_Permanent(card=lea["Grizzly Bears"]),
            ],
        ),
    ])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Confusion in the Ranks")
    _w1g9_resolve_stack(game)
    game._settle()
    assert _w1g9_seats(game) == {
        "Confusion in the Ranks": 1, "Crusade": 0, "Grizzly Bears": 1,
    }


def test_w1g9_confusion_in_the_ranks_needs_both_on_the_battlefield(set_pool):
    """The ruling (2004-12-01): "The permanents are exchanged only if they're
    both on the battlefield when the ability resolves." The entering Bears
    leave with the trigger on the stack, and nothing changes hands."""
    game = _w1g9_confusion_game(
        set_pool, theirs=["Hill Giant"], hands=(["Grizzly Bears"], ())
    )
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Grizzly Bears")
    assert [item.card.name for item in game.stack] == ["Confusion in the Ranks"]
    bears = _w1g9_named(game, "Grizzly Bears")
    game.remove_from_battlefield(bears)
    _w1g9_resolve_stack(game)
    game._settle()
    assert _w1g9_seats(game) == {"Confusion in the Ranks": 0, "Hill Giant": 1}


def _w1g9_aura_on_ring(set_pool, aura_name):
    """*aura_name* (seat 0's) cast onto seat 1's Sol Ring."""
    lea = set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(name="P0", hand=[set_pool("MRD")[aura_name]]),
        _w1g9_PlayerState(name="P1", battlefield=[_w1g9_Permanent(card=lea["Sol Ring"])]),
    ])
    game.enforce_mana_costs = False
    ring = _w1g9_named(game, "Sol Ring")
    game.cast_from_hand(
        0, aura_name, target_player_index=1, target_permanent_ids=[ring.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert _w1g9_named(game, aura_name).metadata.get("attached_to") is ring
    return game, ring


def test_w1g9_inertia_bubble_keeps_the_artifact_tapped(set_pool):
    """"Enchanted artifact doesn't untap during its controller's untap step."
    The untap step asked the Aura restriction of creatures only, so the Sol
    Ring untapped as if nothing were attached (the shipped Paralyze, on a
    creature, was unaffected). It stays tapped now, and untaps once the Aura
    is gone."""
    game, ring = _w1g9_aura_on_ring(set_pool, "Inertia Bubble")
    ring.tapped = True
    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert ring.tapped
    game._destroy_target_permanent(
        game.players[0], described={"named": "Inertia Bubble"}
    )
    game.resolve_untap_step(1)
    assert not ring.tapped


def test_w1g9_relic_bane_drains_the_artifacts_controller(set_pool):
    """"Enchanted artifact has 'At the beginning of your upkeep, you lose 2
    life.'" A granted ability is the artifact's, so "you" is the artifact's
    controller (CR 113.8): P1 loses 2 on P1's upkeep and P0, the Aura's
    controller, loses nothing on P0's."""
    game, _ = _w1g9_aura_on_ring(set_pool, "Relic Bane")
    game.active_player_index = 1
    game.resolve_upkeep(1)
    _w1g9_resolve_stack(game)
    game._settle()
    assert [p.life for p in game.players] == [20, 18]
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert [p.life for p in game.players] == [20, 18]


# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.
#
# Sphere of Purity: "If an artifact would deal damage to you, prevent 1 of
# that damage." Urza's Armor's static shield (``prevention/blankets.py``)
# narrowed by the source's card type, asked as the damage would be dealt
# (CR 609.7c) — a sacrificed Spellbomb's damage is an artifact's.

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine.models import Permanent as _w1g12_Permanent
from tests.helpers import _nosick as _w1g12_nosick
from tests.helpers import declare_attack as _w1g12_declare_attack
from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g12_table(set_pool, *, mine=(), theirs=(), opponent_hand=()):
    card = lambda name: _w1g12_card(set_pool, name)  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState("A", library=[card("Forest")] * 12),
        _w1g12_PlayerState(
            "B", hand=[card(n) for n in opponent_hand],
            library=[card("Forest")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g12_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g12_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def test_w1g12_sphere_of_purity_shaves_an_artifacts_damage_to_you(set_pool):
    # The source is sacrificed to pay the cost: what deals the damage is an
    # artifact that is no longer on the battlefield (CR 609.7c).
    game, _, _ = _w1g12_table(
        set_pool, mine=["Sphere of Purity"], theirs=["Pyrite Spellbomb"],
    )
    game.active_player_index = 1
    assert game.activate_permanent_ability(
        1, "Pyrite Spellbomb", target_player_index=0, ability_index=0,
    ).supported
    _w1g12_resolve_stack(game)
    assert game.players[0].life == 19
    assert "A prevented 1 of 2 damage (Sphere of Purity)" in game.log


def test_w1g12_sphere_of_purity_shaves_artifact_combat_damage_only(set_pool):
    # Alpha Myr (an artifact creature, 2) and Grizzly Bears (2) both
    # unblocked: one point of the Myr's is prevented and none of the Bears'.
    game, _, _ = _w1g12_table(
        set_pool, mine=["Sphere of Purity"], theirs=["Alpha Myr", "Grizzly Bears"],
    )
    _w1g12_declare_attack(game, 1)
    game.advance_combat_phase()
    assert game.players[0].life == 17


def test_w1g12_sphere_of_purity_ignores_a_spell_and_covers_only_you(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Sphere of Purity"], opponent_hand=["Lightning Bolt"],
    )
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g12_resolve_stack(game)
    assert game.players[0].life == 17
    # The opponent's Sphere protects its own controller, not the player an
    # artifact of theirs is not hitting.
    game, _, _ = _w1g12_table(
        set_pool, mine=["Pyrite Spellbomb"], theirs=["Sphere of Purity"],
    )
    assert game.activate_permanent_ability(
        0, "Pyrite Spellbomb", target_player_index=1, ability_index=0,
    ).supported
    _w1g12_resolve_stack(game)
    assert game.players[1].life == 19

# ==== end W1G12 ======================================================


# ==== W2G4 ==========================================================
# Confusion in the Ranks announces its target (CR 603.3d with the seat the
# card names): "its controller chooses target permanent another player
# controls that shares a card type with it" is chosen by the entering object's
# controller as the ability goes on the stack, out of exactly the permanents
# the two relations admit, and re-checked as it resolves (CR 608.2b; the
# ruling, 2004-12-01: "The permanents have to share a permanent type both when
# the target is chosen and when the ability resolves").
from engine import Game as _w2g4_Game
from engine import PlayerState as _w2g4_PlayerState
from engine.control import change_control as _w2g4_change_control
from engine.models import Permanent as _w2g4_Permanent
from tests.helpers import resolve_stack as _w2g4_resolve_stack


def _w2g4_confusion(set_pool, boards, hand, *, seats=2, interactive=()):
    """Confusion in the Ranks on seat 0's battlefield; *boards* maps a seat to
    the LEA permanents on it; *hand* is ``(seat, name)``, the LEA creature that
    seat holds and is active to cast."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    players = []
    for seat in range(seats):
        battlefield = [_w2g4_Permanent(card=lea[n]) for n in boards.get(seat, ())]
        if seat == 0:
            battlefield.insert(0, _w2g4_Permanent(card=mrd["Confusion in the Ranks"]))
        players.append(_w2g4_PlayerState(
            name=f"P{seat}", battlefield=battlefield,
            hand=[lea[hand[1]]] if hand[0] == seat else [],
            library=[lea["Island"]] * 5,
        ))
    game = _w2g4_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = hand[0]
    game._sync_control()
    return game


def _w2g4_named(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def test_w2g4_confusion_names_its_target_on_the_stack(set_pool):
    """The target is the stacked ability's before anything resolves — a seat
    nobody asks names the one creature another player controls."""
    from engine.stack_targets import chosen_targets

    game = _w2g4_confusion(
        set_pool, {1: ["Hill Giant", "Sol Ring"]}, (0, "Grizzly Bears"),
    )
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    # Resolve the Bears alone: the trigger goes on the stack above nothing.
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Confusion in the Ranks"]
    giant = _w2g4_named(game, "Hill Giant")
    assert [t.permanent_id for t in chosen_targets(game, game.stack[-1])] == [
        giant.permanent_id
    ], game.log


def test_w2g4_confusion_target_taken_by_the_chooser_in_response_is_illegal(set_pool):
    """CR 608.2b: the announced Hill Giant comes under the chooser's control
    before the ability resolves, so it is no longer a permanent "another
    player controls" — the one target is illegal and nothing is exchanged."""
    game = _w2g4_confusion(
        set_pool, {1: ["Hill Giant"]}, (0, "Grizzly Bears"),
    )
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Confusion in the Ranks"]
    giant = _w2g4_named(game, "Hill Giant")
    _w2g4_change_control(giant, 0, source="response")
    game._sync_control()

    _w2g4_resolve_stack(game)
    bears = _w2g4_named(game, "Grizzly Bears")
    assert game.controller_index_of(bears) == 0
    assert game.controller_index_of(giant) == 0
    assert any("is controlled by the player who chose it" in line for line in game.log), game.log


def test_w2g4_confusion_another_player_is_measured_from_the_chooser(set_pool):
    """Three seats: P1's Elves enter, so P1 announces, offered P0's and P2's
    creatures and never its own Bears — "another player" against the chooser,
    not against the ability's controller (P0)."""
    game = _w2g4_confusion(
        set_pool,
        {0: ["Hill Giant"], 1: ["Grizzly Bears"], 2: ["Craw Wurm", "Sol Ring"]},
        (1, "Llanowar Elves"), seats=3, interactive={1},
    )
    assert game.queue_from_hand(1, "Llanowar Elves").supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("trigger_target", 1)
    ]
    offered = sorted(e["name"] for e in game.pending_choices[0].data["targets"])
    assert offered == ["Craw Wurm", "Hill Giant"]
    wurm = _w2g4_named(game, "Craw Wurm")
    assert game.confirm_trigger_target(1, permanent_id=wurm.permanent_id) is True
    _w2g4_resolve_stack(game)
    elves = _w2g4_named(game, "Llanowar Elves")
    assert game.controller_index_of(elves) == 2
    assert game.controller_index_of(wurm) == 1


def test_w2g4_confusion_refuses_an_answer_the_relations_exclude(set_pool):
    """The answer is held to the offer: the chooser's own creature and a
    permanent sharing no type with the Elves are refused."""
    game = _w2g4_confusion(
        set_pool, {0: ["Hill Giant", "Sol Ring"], 1: ["Grizzly Bears"]},
        (1, "Llanowar Elves"), interactive={1},
    )
    assert game.queue_from_hand(1, "Llanowar Elves").supported
    game.resolve_top_of_stack()
    own = _w2g4_named(game, "Grizzly Bears")
    ring = _w2g4_named(game, "Sol Ring")
    assert game.confirm_trigger_target(1, permanent_id=own.permanent_id) is False
    assert game.confirm_trigger_target(1, permanent_id=ring.permanent_id) is False
    assert [c.kind for c in game.pending_choices] == ["trigger_target"]

# ==== end W2G4 ======================================================
