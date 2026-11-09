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

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
