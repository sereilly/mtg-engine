"""Mirrodin artifacts, the later groups' sections.

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


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


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

from engine.game import Game as _W1G11Game
from engine.models import Permanent as _W1G11Permanent
from engine.models import PlayerState as _W1G11PlayerState
from engine.oracle import compile_card_oracle as _w1g11_compile
from engine.control import change_control as _w1g11_change_control
from engine.targeting import derive_activation_spec as _w1g11_activation_spec

from tests.helpers import resolve_stack as _w1g11_resolve_stack


def _w1g11_table(set_pool, *, library=(), bob_library=(), hand=()):
    lea = set_pool("LEA")
    alice = _W1G11PlayerState(
        name="Alice", hand=list(hand),
        library=list(library) or [lea["Plains"]] * 6,
    )
    bob = _W1G11PlayerState(
        name="Bob", library=list(bob_library) or [lea["Island"]] * 6,
    )
    game = _W1G11Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g11_put(game, seat, card):
    permanent = _W1G11Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g11_activate(game, seat, perm, **targets):
    result = game.activate_permanent_ability(
        seat, perm.card.name, permanent_index=game.battlefield_index_of(perm),
        ability_index=0, **targets,
    )
    assert result.supported, result.details
    return result


def _w1g11_belch(set_pool, library, **targets):
    mrd = set_pool("MRD")
    game, alice, bob = _w1g11_table(set_pool, library=library)
    belcher = _w1g11_put(game, 0, mrd["Goblin Charbelcher"])
    _w1g11_activate(game, 0, belcher, **targets)
    _w1g11_resolve_stack(game)
    return game, alice, bob


def test_w1g11_charbelcher_counts_the_nonland_cards_before_the_land(set_pool):
    lea = set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Lightning Bolt"], lea["Island"],
               lea["Shivan Dragon"]]
    game, alice, bob = _w1g11_belch(set_pool, library, target_player_index=1)
    assert bob.life == 18
    # The revealed pile goes to the bottom; the card under it is now on top.
    assert alice.library[0].name == "Shivan Dragon"
    assert sorted(c.name for c in alice.library[1:]) == [
        "Grizzly Bears", "Island", "Lightning Bolt",
    ]


def test_w1g11_charbelcher_doubles_on_a_mountain(set_pool):
    lea = set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Lightning Bolt"], lea["Shivan Dragon"],
               lea["Mountain"], lea["Island"]]
    game, alice, bob = _w1g11_belch(set_pool, library, target_player_index=1)
    assert bob.life == 20 - 6
    assert alice.library[0].name == "Island"


def test_w1g11_charbelcher_with_no_land_deals_one_per_card_revealed(set_pool):
    """The ruling (2016-06-08): no land revealed is damage equal to the
    number of cards revealed — the whole library."""
    lea = set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Lightning Bolt"], lea["Shivan Dragon"]]
    game, alice, bob = _w1g11_belch(set_pool, library, target_player_index=1)
    assert bob.life == 17
    assert len(alice.library) == 3


def test_w1g11_charbelcher_aims_at_a_creature_and_the_picker_offers_any_target(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    (ability,) = _w1g11_compile(mrd["Goblin Charbelcher"]).activated_abilities
    spec = _w1g11_activation_spec(ability)
    assert spec is not None and spec.get("kind") == "any", spec
    game, alice, bob = _w1g11_table(
        set_pool, library=[lea["Grizzly Bears"], lea["Mountain"]],
    )
    belcher = _w1g11_put(game, 0, mrd["Goblin Charbelcher"])
    dragon = _w1g11_put(game, 1, lea["Shivan Dragon"])
    _w1g11_activate(game, 0, belcher, target_permanent_ids=[dragon.permanent_id])
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 2
    assert bob.life == 20

def test_w1g11_proteus_staff_swaps_a_creature_for_its_controllers_next_creature(set_pool):
    """Bob's Dragon goes to the bottom of Bob's library; Bob reveals down to
    his next creature, which enters under his control, and the rest go under."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    bob_library = [lea["Island"], lea["Lightning Bolt"], lea["Grizzly Bears"],
                   lea["Forest"]]
    game, alice, bob = _w1g11_table(set_pool, bob_library=bob_library)
    staff = _w1g11_put(game, 0, mrd["Proteus Staff"])
    dragon = _w1g11_put(game, 1, lea["Shivan Dragon"])
    _w1g11_activate(game, 0, staff, target_permanent_ids=[dragon.permanent_id])
    _w1g11_resolve_stack(game)
    assert not game.is_on_battlefield(dragon)
    bears = [p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears"]
    assert len(bears) == 1
    assert game.controller_index_of(bears[0]) == 1
    # Forest was never revealed and is on top; the Dragon went under first,
    # then the two revealed cards under it.
    assert [c.name for c in bob.library] == [
        "Forest", "Shivan Dragon", "Island", "Lightning Bolt",
    ]


def test_w1g11_proteus_staff_reads_the_controller_not_the_owner(set_pool):
    """A creature Alice controls but Bob owns: it goes to Bob's library, and
    Alice (its controller) reveals from hers."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g11_table(
        set_pool, library=[lea["Plains"], lea["Grizzly Bears"]],
        bob_library=[lea["Island"]] * 3,
    )
    staff = _w1g11_put(game, 0, mrd["Proteus Staff"])
    dragon = _w1g11_put(game, 1, lea["Shivan Dragon"])
    _w1g11_change_control(dragon, 0, source=lea["Control Magic"])
    game._sync_control()
    assert game.controller_index_of(dragon) == 0
    _w1g11_activate(game, 0, staff, target_permanent_ids=[dragon.permanent_id])
    _w1g11_resolve_stack(game)
    assert bob.library[-1].name == "Shivan Dragon"
    assert [p.card.name for p in game.controlled_by(0)
            if p.card.name == "Grizzly Bears"] == ["Grizzly Bears"]
    assert [c.name for c in alice.library] == ["Plains"]


def test_w1g11_proteus_staff_is_sorcery_speed_and_picks_a_creature(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    (ability,) = _w1g11_compile(mrd["Proteus Staff"]).activated_abilities
    spec = _w1g11_activation_spec(ability)
    assert spec is not None and spec.get("kind") in ("permanent", "creature"), spec
    game, alice, bob = _w1g11_table(set_pool)
    staff = _w1g11_put(game, 0, mrd["Proteus Staff"])
    dragon = _w1g11_put(game, 1, lea["Shivan Dragon"])
    game.current_phase = "combat"
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    result = game.activate_permanent_ability(
        0, "Proteus Staff", permanent_index=game.battlefield_index_of(staff),
        ability_index=0, target_permanent_ids=[dragon.permanent_id],
    )
    assert not result.supported
    assert game.is_on_battlefield(dragon)

def test_w1g11_proteus_staff_asks_the_revealing_player_to_order_the_rest(set_pool):
    """CR 401.4: the pile's owner — the revealer, not the activator — orders
    the cards put on the bottom."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    bob_library = [lea["Island"], lea["Lightning Bolt"], lea["Grizzly Bears"]]
    game, alice, bob = _w1g11_table(set_pool, bob_library=bob_library)
    game.interactive_seats = {1}
    staff = _w1g11_put(game, 0, mrd["Proteus Staff"])
    dragon = _w1g11_put(game, 1, lea["Shivan Dragon"])
    _w1g11_activate(game, 0, staff, target_permanent_ids=[dragon.permanent_id])
    game.resolve_top_of_stack()
    owed = [(c.kind, c.player_index) for c in game.pending_choices]
    assert ("reorder_library", 1) in owed, owed


def _w1g11_incubator_table(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    library = [lea["Sol Ring"], lea["Island"], lea["Jayemdae Tome"],
               lea["Black Vise"], lea["Forest"]]
    game, alice, bob = _w1g11_table(set_pool, library=library)
    incubator = _w1g11_put(game, 0, mrd["Myr Incubator"])
    return game, alice, incubator


def _w1g11_myr_tokens(game, seat):
    return [p for p in game.controlled_by(seat) if p.card.name == "Myr Token"]


def test_w1g11_myr_incubator_exiles_the_artifacts_a_person_picks_and_makes_that_many(set_pool):
    game, alice, incubator = _w1g11_incubator_table(set_pool)
    game.interactive_seats = {0}
    _w1g11_activate(game, 0, incubator)
    assert not game.is_on_battlefield(incubator), "sacrificed as a cost"
    assert not game.resolve_top_of_stack(), "held for the search"
    (choice,) = [c for c in game.pending_choices if c.kind == "search_exile_cards"]
    picks = [
        {"zone": "library", "index": i} for i, card in enumerate(alice.library)
        if card.name in ("Sol Ring", "Black Vise")
    ][:2]
    assert game.confirm_search_exile(0, picks)
    _w1g11_resolve_stack(game)
    assert len(alice.exile) == 2
    assert all("Artifact" in c.type_line for c in alice.exile)
    tokens = _w1g11_myr_tokens(game, 0)
    assert len(tokens) == 2
    assert all(t.effective_power == 1 and t.effective_toughness == 1 for t in tokens)
    assert len(alice.library) == 3


def test_w1g11_myr_incubator_refuses_a_nonartifact_pick(set_pool):
    game, alice, incubator = _w1g11_incubator_table(set_pool)
    game.interactive_seats = {0}
    _w1g11_activate(game, 0, incubator)
    game.resolve_top_of_stack()
    island = next(i for i, c in enumerate(alice.library) if c.name == "Island")
    assert not game.confirm_search_exile(0, [{"zone": "library", "index": island}])
    assert alice.exile == []


def test_w1g11_myr_incubator_left_to_itself_takes_every_artifact(set_pool):
    """The pile is paid for one token a card, so a headless seat takes the
    maximum (``exiled_search_pile_comes_back``)."""
    game, alice, incubator = _w1g11_incubator_table(set_pool)
    _w1g11_activate(game, 0, incubator)
    _w1g11_resolve_stack(game)
    game.auto_resolve_pending_choices()
    artifacts = [c for c in alice.exile if "Artifact" in c.type_line]
    assert len(artifacts) == len(alice.exile) >= 2
    assert len(_w1g11_myr_tokens(game, 0)) == len(alice.exile)
    assert all("Artifact" not in c.type_line for c in alice.library)


def test_w1g11_mesmeric_orb_mills_once_for_each_permanent_the_untap_step_untaps(set_pool):
    """The ruling (2020-08-07): permanents untapped in the untap step trigger
    the Orb that many times, put on the stack at the upkeep."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g11_table(set_pool, bob_library=[lea["Island"]] * 6)
    _w1g11_put(game, 0, mrd["Mesmeric Orb"])
    islands = [_w1g11_put(game, 1, lea["Island"]) for _ in range(2)]
    untapped_already = _w1g11_put(game, 1, lea["Forest"])
    for island in islands:
        island.tapped = True
    assert not untapped_already.tapped
    game.active_player_index = 1
    game.resolve_untap_step(1)
    game._settle()
    _w1g11_resolve_stack(game)
    assert all(not island.tapped for island in islands)
    assert len(bob.graveyard) == 2
    assert len(bob.library) == 4
    assert alice.graveyard == []


def test_w1g11_mesmeric_orb_mills_the_untapped_permanents_controller_mid_turn(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g11_table(set_pool, library=[lea["Plains"]] * 4)
    _w1g11_put(game, 1, mrd["Mesmeric Orb"])
    bears = _w1g11_put(game, 0, lea["Grizzly Bears"])
    bears.tapped = True
    assert game.become_untapped(bears)
    game._settle()
    _w1g11_resolve_stack(game)
    assert [c.name for c in alice.graveyard] == ["Plains"]
    assert bob.graveyard == []
    # Re-untapping an untapped permanent is no event (CR 701.26b).
    assert not game.become_untapped(bears)
    game._settle()
    assert len(alice.graveyard) == 1

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
