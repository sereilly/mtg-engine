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

def test_w1g11_psychogenic_probe_burns_whoever_an_ability_makes_shuffle(set_pool):
    """Bob's Myr Mindservant shuffles Bob's library: Alice's Probe deals Bob 2."""
    mrd = set_pool("MRD")
    game, alice, bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Psychogenic Probe"])
    servant = _w1g11_put(game, 1, mrd["Myr Mindservant"])
    _w1g11_activate(game, 1, servant)
    _w1g11_resolve_stack(game)
    game._settle()
    _w1g11_resolve_stack(game)
    assert bob.life == 18
    assert alice.life == 20


def test_w1g11_psychogenic_probe_hears_a_search_and_an_empty_library(set_pool):
    """The ruling (2009-02-01): the ability triggers "even if the player's
    library is empty"; and a search's shuffle is a shuffle (CR 701.23a)."""
    mrd = set_pool("MRD")
    game, alice, bob = _w1g11_table(set_pool)
    _w1g11_put(game, 1, mrd["Psychogenic Probe"])
    alice.library.clear()
    game.shuffle_library_of(alice)
    game._settle()
    _w1g11_resolve_stack(game)
    assert alice.life == 18
    servant = _w1g11_put(game, 0, mrd["Myr Mindservant"])
    _w1g11_activate(game, 0, servant)
    _w1g11_resolve_stack(game)
    game._settle()
    _w1g11_resolve_stack(game)
    assert alice.life == 16
    assert bob.life == 20


def test_w1g11_two_probes_each_burn_for_one_shuffle(set_pool):
    mrd = set_pool("MRD")
    game, alice, bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Psychogenic Probe"])
    _w1g11_put(game, 0, mrd["Psychogenic Probe"])
    game.shuffle_library_of(bob)
    game._settle()
    _w1g11_resolve_stack(game)
    assert bob.life == 16

def _w1g11_rigged_coins(monkeypatch, results):
    """Rig the engine's coin to come up *results* in order (True = a win /
    heads), recording how many coins were flipped."""
    import engine.handlers.control_flow as _w1g11_control_flow

    queue = list(results)
    flips = []

    def coin(win_probability: float = 0.5) -> bool:
        flips.append(1)
        return queue.pop(0)

    monkeypatch.setattr(_w1g11_control_flow, "flip_coin", coin)
    return flips


def test_w1g11_krarks_thumb_flips_two_coins_and_keeps_the_win(set_pool, monkeypatch):
    """Alice flips (a "flip a coin; if you win" ability): with the Thumb out,
    two coins, the loss ignored."""
    from engine.handlers._common import flip_coin_for

    mrd = set_pool("MRD")
    game, alice, _bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Krark's Thumb"])
    import engine.handlers.control_flow as _w1g11_control_flow

    flips = _w1g11_rigged_coins(monkeypatch, [False, True])
    assert flip_coin_for(game, alice, flip=_w1g11_control_flow.flip_coin)
    assert len(flips) == 2
    assert any("flips 2 coins instead of 1" in line for line in game.log)


def test_w1g11_krarks_thumb_both_coins_lost_is_a_loss(set_pool, monkeypatch):
    from engine.handlers._common import flip_coin_for

    mrd = set_pool("MRD")
    game, alice, _bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Krark's Thumb"])
    import engine.handlers.control_flow as _w1g11_control_flow

    _w1g11_rigged_coins(monkeypatch, [False, False])
    assert not flip_coin_for(game, alice, flip=_w1g11_control_flow.flip_coin)


def test_w1g11_krarks_thumb_is_only_its_controllers(set_pool, monkeypatch):
    """"If **you** would flip a coin": Bob's flips are one coin."""
    from engine.handlers._common import flip_coin_for

    mrd = set_pool("MRD")
    game, _alice, bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Krark's Thumb"])
    import engine.handlers.control_flow as _w1g11_control_flow

    flips = _w1g11_rigged_coins(monkeypatch, [False, True])
    assert not flip_coin_for(game, bob, flip=_w1g11_control_flow.flip_coin)
    assert len(flips) == 1


def test_w1g11_two_thumbs_flip_four_coins(set_pool, monkeypatch):
    """CR 614.5: each Thumb has the flip once, the second doubling the two
    flips the first made — four coins, three ignored."""
    from engine.handlers._common import flip_coin_for

    mrd = set_pool("MRD")
    game, alice, _bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Krark's Thumb"])
    _w1g11_put(game, 0, mrd["Krark's Thumb"])
    import engine.handlers.control_flow as _w1g11_control_flow

    flips = _w1g11_rigged_coins(monkeypatch, [False, False, False, True])
    assert flip_coin_for(game, alice, flip=_w1g11_control_flow.flip_coin)
    assert len(flips) == 4


def test_w1g11_krarks_thumb_keeps_heads_on_a_flip_nobody_wins(set_pool, monkeypatch):
    """"Each player flips a coin" (Goblin Assassin's sentence), run through
    its handler: Alice's Thumb turns her tails into heads; Bob's coin is one."""
    from engine.game_types import OracleExecutionContext
    from engine.handlers._common import COIN_FACES_BY_SEAT
    from engine.handlers.control_flow import flip_a_coin
    from engine.oracle import OracleInstruction

    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Krark's Thumb"])
    # APNAP: Alice's two coins (tails, heads), then Bob's one (tails).
    flips = _w1g11_rigged_coins(monkeypatch, [False, True, False])
    context = OracleExecutionContext(caster=alice, target=bob, card=lea["Island"])
    flip_a_coin(
        game, OracleInstruction("flip_coin", "", {"flipper": "each_player"}), context,
    )
    assert context.results[COIN_FACES_BY_SEAT] == {0: "heads", 1: "tails"}
    assert len(flips) == 3

def test_w1g11_minds_eye_pays_one_to_draw_when_an_opponent_draws(set_pool):
    """Drive list. "Whenever an opponent draws a card, you may pay {1}. If you
    do, draw a card." Bob draws; Alice, with an untapped land, pays and draws;
    Alice's own draw does not trigger it."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g11_table(set_pool)
    game.enforce_mana_costs = True
    _w1g11_put(game, 0, mrd["Mind's Eye"])
    _w1g11_put(game, 0, lea["Island"])
    game._draw_with_replacements(bob, 1)
    game._settle()
    _w1g11_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g11_resolve_stack(game)
    assert len(alice.hand) == 1
    assert len(bob.hand) == 1
    game._draw_with_replacements(alice, 1)
    game._settle()
    _w1g11_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert len(alice.hand) == 2


def test_w1g11_tower_of_murmurs_mills_its_target_eight(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g11_table(set_pool, bob_library=[lea["Island"]] * 10)
    tower = _w1g11_put(game, 0, mrd["Tower of Murmurs"])
    _w1g11_activate(game, 0, tower, target_player_index=1)
    _w1g11_resolve_stack(game)
    assert len(bob.graveyard) == 8 and len(bob.library) == 2
    assert tower.tapped


def test_w1g11_myr_mindservant_shuffles_its_controllers_library(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g11_table(set_pool)
    servant = _w1g11_put(game, 0, mrd["Myr Mindservant"])
    _w1g11_activate(game, 0, servant)
    _w1g11_resolve_stack(game)
    assert servant.tapped
    assert any("shuffled their library" in line for line in game.log)


def _w1g11_spellbomb(set_pool, name, ability_index, **targets):
    mrd = set_pool("MRD")
    game, alice, bob = _w1g11_table(set_pool)
    bomb = _w1g11_put(game, 0, mrd[name])
    result = game.activate_permanent_ability(
        0, name, permanent_index=game.battlefield_index_of(bomb),
        ability_index=ability_index, **targets,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(bomb), "sacrificed as a cost"
    _w1g11_resolve_stack(game)
    return game, alice, bob


def test_w1g11_every_spellbomb_cycles_for_one(set_pool):
    for name in ("Aether Spellbomb", "Necrogen Spellbomb", "Pyrite Spellbomb",
                 "Sunbeam Spellbomb", "Lifespark Spellbomb"):
        game, alice, _bob = _w1g11_spellbomb(set_pool, name, 1)
        assert len(alice.hand) == 1, name
        assert [c.name for c in alice.graveyard] == [name]


def test_w1g11_the_spellbombs_first_abilities(set_pool):
    lea = set_pool("LEA")
    # Aether: bounce a creature.
    mrd = set_pool("MRD")
    game, alice, bob = _w1g11_table(set_pool)
    bears = _w1g11_put(game, 1, lea["Grizzly Bears"])
    bomb = _w1g11_put(game, 0, mrd["Aether Spellbomb"])
    _w1g11_activate(game, 0, bomb, target_permanent_ids=[bears.permanent_id])
    _w1g11_resolve_stack(game)
    assert [c.name for c in bob.hand] == ["Grizzly Bears"]
    # Necrogen: target player discards.
    game, alice, bob = _w1g11_table(set_pool)
    bob.hand.append(lea["Shivan Dragon"])
    bomb = _w1g11_put(game, 0, mrd["Necrogen Spellbomb"])
    _w1g11_activate(game, 0, bomb, target_player_index=1)
    _w1g11_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in bob.graveyard] == ["Shivan Dragon"]
    # Pyrite: 2 damage to any target.
    game, alice, bob = _w1g11_table(set_pool)
    bomb = _w1g11_put(game, 0, mrd["Pyrite Spellbomb"])
    _w1g11_activate(game, 0, bomb, target_player_index=1)
    _w1g11_resolve_stack(game)
    assert bob.life == 18
    # Sunbeam: gain 5.
    game, alice, bob = _w1g11_table(set_pool)
    bomb = _w1g11_put(game, 0, mrd["Sunbeam Spellbomb"])
    _w1g11_activate(game, 0, bomb)
    _w1g11_resolve_stack(game)
    assert alice.life == 25
    # Lifespark: a land becomes a 3/3 that is still a land, until end of turn.
    game, alice, bob = _w1g11_table(set_pool)
    forest = _w1g11_put(game, 0, lea["Forest"])
    bomb = _w1g11_put(game, 0, mrd["Lifespark Spellbomb"])
    _w1g11_activate(game, 0, bomb, target_permanent_ids=[forest.permanent_id])
    _w1g11_resolve_stack(game)
    game._recompute_continuous_effects()
    assert forest.is_creature and forest.has_type("land")
    assert (forest.effective_power, forest.effective_toughness) == (3, 3)
    game.resolve_cleanup_step(0)
    game._recompute_continuous_effects()
    assert not forest.is_creature

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
