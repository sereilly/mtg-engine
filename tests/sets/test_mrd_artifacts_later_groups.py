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
#
# Drive list: Rustspore Ram and Duskworker, the two artifact creatures among
# W1G2's supported-on-arrival cards, each given a headless game.
from engine import Game as _W1G2Game
from engine.aura_attachment import attach_aura as _w1g2_attach_aura
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import declare_attack as _w1g2_declare_attack
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8)
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


def test_w1g2_rustspore_ram_destroys_an_equipment_as_it_enters(set_pool):
    """"When this creature enters, destroy target Equipment." The target is
    the trigger's (CR 603.3d): an opponent's Equipment is destroyed and the
    creature it equipped loses the bonus; with no Equipment anywhere the
    trigger is removed from the stack and nothing else is touched."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, hand=[mrd["Rustspore Ram"]])
    bear = _w1g2_put(game, 1, lea["Grizzly Bears"])
    _w1g2_put(game, 1, mrd["Leonin Scimitar"], wearing=bear)
    assert game.cast_from_hand(0, "Rustspore Ram").supported
    _w1g2_drain(game)
    game.check_state_based_actions()
    assert [card.name for card in bob.graveyard] == ["Leonin Scimitar"]
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)

    game, _alice, bob = _w1g2_table(set_pool, hand=[mrd["Rustspore Ram"]])
    bear = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Rustspore Ram").supported
    _w1g2_drain(game)
    assert bob.graveyard == [] and game.is_on_battlefield(bear)
    assert any("no legal target (603.3d)" in line for line in game.log)


def test_w1g2_duskworker_regenerates_when_blocked_and_pumps_for_three(set_pool):
    """"Whenever this creature becomes blocked, regenerate it." Blocked by a
    Craw Wurm, the 2/2 takes lethal damage and regenerates (CR 701.19a:
    tapped, damage removed) instead of dying. "{3}: This creature gets +1/+0
    until end of turn." pays from the pool and pumps."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g2_table(set_pool)
    duskworker = _w1g2_put(game, 0, mrd["Duskworker"])
    _w1g2_put(game, 1, lea["Craw Wurm"])
    _w1g2_declare_attack(game, 0, blocks={0: 0})
    _w1g2_drain(game)
    assert duskworker.regeneration_shield == 1
    game.advance_combat_phase()
    _w1g2_drain(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(duskworker)
    assert duskworker.damage_marked == 0 and duskworker.tapped
    assert any(line == "Duskworker regenerated" for line in game.log)

    game, alice, _bob = _w1g2_table(set_pool)
    game.enforce_mana_costs = True
    duskworker = _w1g2_put(game, 0, mrd["Duskworker"])
    alice.mana_pool.update({"C": 3})
    result = game.activate_permanent_ability(
        0, "Duskworker", permanent_index=game.battlefield_index_of(duskworker),
    )
    assert result.supported, result.details
    _w1g2_drain(game)
    assert (duskworker.effective_power, duskworker.effective_toughness) == (3, 2)
    assert sum(alice.mana_pool.values()) == 0

# ==== end W1G2 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Activated abilities on artifacts: Tel-Jilad Stylus's "target permanent you
# own", Scrabbling Claws' target player picking out of their own graveyard,
# and the mana rocks, Talismans and Towers this family drives.
from engine import Game as _W1G8Game
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import derive_activation_spec as _w1g8_activation_spec

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_board(set_pool, mine, theirs=(), *, hand=()):
    """A duel at seat 0's first main phase, *mine* and *theirs* on the
    battlefield and ready to tap; mana costs off unless a test turns them on."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8PlayerState(name="A", hand=list(hand), library=[lea["Plains"]] * 8),
        _W1G8PlayerState(name="B", library=[lea["Plains"]] * 8),
    ])
    game.enforce_mana_costs = False
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            perm = _W1G8Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            placed.append(perm)
    _w1g8_resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.current_step == "precombat_main"
    return game, placed


def test_w1g8_tel_jilad_stylus_offers_what_you_own_not_what_you_control(set_pool):
    """2004-12-01: it "may target a permanent you own but do not control". The
    picker offers the activator's own permanents and the one an opponent
    controls but the activator owns; an opponent's own permanent is refused
    before the {T} is paid; the target goes under its owner's library."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (stylus, bears, ring, giant, angel) = _w1g8_board(
        set_pool,
        [mrd["Tel-Jilad Stylus"], lea["Grizzly Bears"], lea["Sol Ring"]],
        [lea["Hill Giant"], lea["Serra Angel"]],
    )
    # The Angel is seat 0's card on seat 1's battlefield.
    angel.metadata["owner_player_index"] = 0
    ability = _w1g8_compile(stylus.card).activated_abilities[0]
    offered = {
        entry.get("name")
        for entry in game.activation_offer(0, stylus, ability)["valid_targets"]
    }
    assert offered == {"Tel-Jilad Stylus", "Grizzly Bears", "Sol Ring", "Serra Angel"}
    refused = game.activate_permanent_ability(
        0, "Tel-Jilad Stylus", target_permanent_ids=[giant.permanent_id]
    )
    assert not refused.supported and not stylus.tapped
    assert game.activate_permanent_ability(
        0, "Tel-Jilad Stylus", target_permanent_ids=[angel.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert not game.is_on_battlefield(angel)
    assert game.players[0].library[-1].name == "Serra Angel"
    assert [p.card.name for p in game.players[1].battlefield] == ["Hill Giant"]
    assert "Tel-Jilad Stylus: Serra Angel put on the bottom of A's library" in game.log


def test_w1g8_scrabbling_claws_target_player_picks_from_their_own_graveyard(set_pool):
    """"{T}: Target player exiles a card from their graveyard." The activation
    announces a player (the picker is a player picker, CR 601.2c); the card is
    that player's choice as the ability resolves — driven both as a default
    seat and as an interactive one answering the pick."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (claws,) = _w1g8_board(set_pool, [mrd["Scrabbling Claws"]])
    ability = _w1g8_compile(claws.card).activated_abilities[0]
    assert _w1g8_activation_spec(ability) == {"kind": "player"}
    pile = [lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Island"]]
    game.players[1].graveyard = list(pile)
    game.players[0].graveyard = [lea["Plains"]]
    assert game.activate_permanent_ability(
        0, "Scrabbling Claws", target_player_index=1
    ).supported
    _w1g8_resolve_stack(game)
    assert len(game.players[1].graveyard) == 2
    assert len(game.players[1].exile) == 1
    assert [c.name for c in game.players[0].graveyard] == ["Plains"]

    game, (claws,) = _w1g8_board(set_pool, [mrd["Scrabbling Claws"]])
    game.players[1].graveyard = list(pile)
    game.interactive_seats = {0, 1}
    assert game.activate_permanent_ability(
        0, "Scrabbling Claws", target_player_index=1
    ).supported
    owed = [(c.kind, c.player_index) for c in game.pending_choices]
    assert owed == [("graveyard_exile_pick", 1)], owed
    assert game.resolve_pending_choice(
        "graveyard_exile_pick", 1, graveyard_indices=[1]
    )
    _w1g8_resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == ["Lightning Bolt", "Island"]
    assert "B exiled Grizzly Bears from B's graveyard (Scrabbling Claws)" in game.log


_W1G8_SHARDS = {
    "Crystal Shard": "U", "Granite Shard": "R", "Heartwood Shard": "G",
    "Pearl Shard": "W", "Skeleton Shard": "B",
}


def _w1g8_granite(set_pool, pool, **announced):
    """Granite Shard activated at seat 1's face from *pool*, costs enforced."""
    game, (shard,) = _w1g8_board(set_pool, [set_pool("MRD")["Granite Shard"]])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    result = game.activate_permanent_ability(
        0, "Granite Shard", target_player_index=1, **announced
    )
    _w1g8_resolve_stack(game)
    left = {s: n for s, n in game.players[0].mana_pool.items() if n}
    return game, shard, result, left


def test_w1g8_the_shards_print_one_ability_with_two_costs(set_pool):
    """2004-10-04: "You can pay either of the two costs (but not both at the
    same time) to activate the ability." One activated ability per Shard,
    charged {3} or its colour, never both."""
    mrd = set_pool("MRD")
    for name, colour in _W1G8_SHARDS.items():
        program = _w1g8_compile(mrd[name])
        assert program.supported, name
        (ability,) = program.activated_abilities
        assert ability.cost.requires_tap
        assert {s: n for s, n in ability.cost.mana.items() if n} == {"generic": 3}
        assert [
            {s: n for s, n in mana.items() if n} for mana in ability.cost.mana_alternatives
        ] == [{colour: 1}], name


def test_w1g8_granite_shard_pays_whichever_cost_was_announced(set_pool):
    """CR 602.2b through 601.2b: the activator announces which printed cost,
    and CR 601.2f totals that one. With none announced the pool decides —
    the cheapest cost it covers — and a pool covering both pays one."""
    for pool, announced, paid, left in (
        ({"R": 1}, {}, "{R}", {}),
        ({"C": 3}, {}, "{3}", {}),
        ({"R": 1, "C": 3}, {}, "{R}", {"C": 3}),
        ({"R": 3}, {"alternative_cost_index": 0}, "{3}", {}),
        ({"R": 3}, {"alternative_cost_index": 1}, "{R}", {"R": 2}),
    ):
        game, shard, result, remaining = _w1g8_granite(set_pool, pool, **announced)
        assert result.supported, (pool, announced, result.details)
        assert game.players[1].life == 19 and shard.tapped
        assert f"Granite Shard: activated for {paid}" in game.log
        assert remaining == left, (pool, announced, remaining)


def test_w1g8_granite_shard_refuses_a_cost_it_cannot_pay_or_does_not_print(set_pool):
    for pool, announced, why in (
        ({"C": 2}, {}, "insufficient mana"),
        ({"R": 1}, {"alternative_cost_index": 0}, "insufficient mana"),
        ({"R": 1}, {"alternative_cost_index": 2}, "no printed activation cost 2"),
    ):
        game, shard, result, remaining = _w1g8_granite(set_pool, pool, **announced)
        assert not result.supported and why in result.details, result.details
        assert not shard.tapped and game.players[1].life == 20
        assert remaining == pool


def test_w1g8_the_ai_announces_the_cheapest_cost_its_lands_pay(set_pool):
    """The planner sees both prices: one Mountain pays {R}; three other lands
    pay {3}; with neither the Shard is not proposed."""
    from engine.ai_abilities import choose_activation_action

    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for lands, expected in (
        (["Mountain"], 1),
        (["Island", "Forest", "Swamp"], 0),
        (["Island", "Forest"], None),
    ):
        game, _placed = _w1g8_board(
            set_pool, [mrd["Granite Shard"], *(lea[name] for name in lands)],
            [lea["Hill Giant"]],
        )
        game.enforce_mana_costs = True
        action = choose_activation_action(game, 0)
        if expected is None:
            assert action is None or action.permanent_name != "Granite Shard"
            continue
        assert action is not None and action.permanent_name == "Granite Shard"
        assert action.alternative_cost_index == expected, lands


def test_w1g8_crystal_shard_bounces_unless_the_creatures_controller_pays(set_pool):
    """"…unless its controller pays {1}": the offer is the *creature's*
    controller's. Driven as an interactive defender who pays and who
    declines, and as a defender with no mana to pay."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for answer in (True, False):
        game, (shard, bears, swamp) = _w1g8_board(
            set_pool, [mrd["Crystal Shard"]], [lea["Grizzly Bears"], lea["Swamp"]],
        )
        game.enforce_mana_costs = True
        game.interactive_seats = {0, 1}
        game.players[0].mana_pool["U"] = 1
        assert game.activate_permanent_ability(
            0, "Crystal Shard", target_permanent_ids=[bears.permanent_id]
        ).supported
        assert "Crystal Shard: activated for {U}" in game.log
        owed = [(c.kind, c.player_index) for c in game.pending_choices]
        assert owed == [("optional_pay", 1)], owed
        assert game.resolve_pending_choice("optional_pay", 1, accept=answer)
        assert game.is_on_battlefield(bears) is answer
        assert swamp.tapped is answer
    game, (shard, bears) = _w1g8_board(
        set_pool, [mrd["Crystal Shard"]], [lea["Grizzly Bears"]],
    )
    game.players[0].mana_pool["C"] = 3
    game.enforce_mana_costs = True
    assert game.activate_permanent_ability(
        0, "Crystal Shard", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert not game.is_on_battlefield(bears)
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]


def test_w1g8_skeleton_shard_returns_only_an_artifact_creature_card(set_pool):
    """"target **artifact creature** card": both types (CR 205.2b). Read as a
    union the picker offered a Grizzly Bears and a Sol Ring and the default
    returned the Bears."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (shard,) = _w1g8_board(set_pool, [mrd["Skeleton Shard"]])
    game.players[0].graveyard = [lea["Grizzly Bears"], lea["Sol Ring"], mrd["Ornithopter"]]
    ability = _w1g8_compile(shard.card).activated_abilities[0]
    offered = [e.get("name") for e in game.activation_offer(0, shard, ability)["valid_targets"]]
    assert offered == ["Ornithopter"]
    refused = game.activate_permanent_ability(
        0, "Skeleton Shard", target_permanent_index=0, target_player_index=0,
    )
    assert not refused.supported and not shard.tapped
    assert game.activate_permanent_ability(0, "Skeleton Shard").supported
    _w1g8_resolve_stack(game)
    assert [c.name for c in game.players[0].hand] == ["Ornithopter"]
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears", "Sol Ring"]


def test_w1g8_heartwood_pearl_and_granite_shards_resolve(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (heartwood, pearl, granite, bears) = _w1g8_board(
        set_pool,
        [mrd["Heartwood Shard"], mrd["Pearl Shard"], mrd["Granite Shard"], lea["Grizzly Bears"]],
        hand=[lea["Lightning Bolt"]],
    )
    assert game.activate_permanent_ability(
        0, "Heartwood Shard", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert game._has_keyword(bears, "trample")
    # "Prevent the next 2 damage that would be dealt to any target this turn."
    assert game.activate_permanent_ability(0, "Pearl Shard", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    game.cast_from_hand(0, "Lightning Bolt", target_player_index=0)
    _w1g8_resolve_stack(game)
    assert game.players[0].life == 19
    assert game.activate_permanent_ability(
        0, "Granite Shard", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert bears.damage_marked == 1


def test_w1g8_scrabbling_claws_on_an_empty_graveyard_exiles_nothing(set_pool):
    mrd = set_pool("MRD")
    game, (claws,) = _w1g8_board(set_pool, [mrd["Scrabbling Claws"]])
    assert game.activate_permanent_ability(
        0, "Scrabbling Claws", target_player_index=1
    ).supported
    _w1g8_resolve_stack(game)
    assert claws.tapped and not game.players[1].exile
    assert not game.pending_choices

# -- Supported on arrival, driven: the mana rocks, Myr, Talismans, Towers ---

_W1G8_TALISMANS = {
    "Talisman of Dominance": "UB", "Talisman of Impulse": "RG",
    "Talisman of Indulgence": "BR", "Talisman of Progress": "WU",
    "Talisman of Unity": "GW",
}


def test_w1g8_talismans_hurt_only_on_their_coloured_ability(set_pool):
    mrd = set_pool("MRD")
    for name, pair in _W1G8_TALISMANS.items():
        for colour in pair:
            game, (talisman,) = _w1g8_board(set_pool, [mrd[name]])
            assert game.activate_permanent_ability(
                0, name, ability_index=1, mana_color=colour
            ).supported
            assert game.players[0].mana_pool[colour] == 1, (name, colour)
            assert game.players[0].life == 19
            assert f"{name} dealt 1 damage to A" in game.log
        game, (talisman,) = _w1g8_board(set_pool, [mrd[name]])
        assert game.activate_permanent_ability(0, name, ability_index=0).supported
        assert game.players[0].mana_pool["C"] == 1 and game.players[0].life == 20


def test_w1g8_the_ai_pays_a_coloured_pip_off_a_talisman_and_generic_painlessly(set_pool):
    """The planner counted a non-land source by its first free mana ability
    alone, so a Talisman paid only {C} and the AI never cast a coloured spell
    off one. Each colour now names the ability that makes it, priced by it:
    a Mountain pays {R} before the Talisman's painful one does."""
    from types import SimpleNamespace

    from engine.ai_payment import _plan_land_taps, tap_planned_lands

    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for lands, need, paid, life in (
        ([], {"R": 1}, {"R": 1}, 19),
        ([], {"generic": 1}, {"C": 1}, 20),
        (["Mountain"], {"R": 1}, {"R": 1}, 20),
        (["Mountain"], {"R": 1, "generic": 1}, {"R": 1, "C": 1}, 20),
        (["Mountain"], {"R": 1, "G": 1}, {"R": 1, "G": 1}, 19),
    ):
        game, _placed = _w1g8_board(
            set_pool, [mrd["Talisman of Impulse"], *(lea[n] for n in lands)],
        )
        game.enforce_mana_costs = True
        plan = _plan_land_taps(game, game.players[0], need)
        assert plan is not None, (lands, need)
        tap_planned_lands(game, 0, SimpleNamespace(
            land_tap_indices=plan[0], land_tap_colors=plan[1],
        ))
        pool = {s: n for s, n in game.players[0].mana_pool.items() if n}
        assert pool == paid and game.players[0].life == life, (lands, need, pool)


def test_w1g8_myr_and_gilded_lotus_make_their_mana(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for name, colour in (
        ("Copper Myr", "G"), ("Gold Myr", "W"), ("Iron Myr", "R"),
        ("Leaden Myr", "B"), ("Silver Myr", "U"),
    ):
        game, _placed = _w1g8_board(set_pool, [mrd[name]])
        assert game.activate_permanent_ability(0, name).supported
        assert {s: n for s, n in game.players[0].mana_pool.items() if n} == {colour: 1}
    game, _placed = _w1g8_board(set_pool, [mrd["Gilded Lotus"]], hand=[lea["Craw Wurm"]])
    game.enforce_mana_costs = True
    game.players[0].mana_pool["C"] = 3
    assert game.activate_permanent_ability(0, "Gilded Lotus", mana_color="G").supported
    assert game.players[0].mana_pool["G"] == 3
    assert game.cast_from_hand(0, "Craw Wurm").supported
    _w1g8_resolve_stack(game)
    assert "Craw Wurm" in [p.card.name for p in game.players[0].battlefield]


def test_w1g8_galvanic_key_untaps_an_artifact(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (key, ring) = _w1g8_board(set_pool, [mrd["Galvanic Key"], lea["Sol Ring"]])
    ring.tapped = True
    assert game.activate_permanent_ability(
        0, "Galvanic Key", target_permanent_ids=[ring.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert not ring.tapped and key.tapped


def test_w1g8_lodestone_myr_taps_artifacts_to_grow(set_pool):
    """"Tap an untapped artifact you control": any one, itself included (no
    {T} symbol, so CR 302.6 does not apply), and a named one is the one
    tapped."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (lodestone, ring, myr) = _w1g8_board(
        set_pool, [mrd["Lodestone Myr"], lea["Sol Ring"], mrd["Iron Myr"]],
    )
    assert game._has_keyword(lodestone, "trample")
    assert game.activate_permanent_ability(
        0, "Lodestone Myr", cost_permanent_ids=[myr.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert myr.tapped and not ring.tapped and not lodestone.tapped
    assert (lodestone.effective_power, lodestone.effective_toughness) == (3, 3)
    for _ in range(2):
        assert game.activate_permanent_ability(0, "Lodestone Myr").supported
        _w1g8_resolve_stack(game)
    assert lodestone.effective_power == 5 and ring.tapped and lodestone.tapped
    refused = game.activate_permanent_ability(0, "Lodestone Myr")
    assert not refused.supported and lodestone.effective_power == 5


def test_w1g8_tanglebloom_nuisance_engine_and_the_towers(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _placed = _w1g8_board(set_pool, [mrd["Tanglebloom"], mrd["Tower of Eons"]])
    game.activate_permanent_ability(0, "Tanglebloom")
    game.activate_permanent_ability(0, "Tower of Eons")
    _w1g8_resolve_stack(game)
    assert game.players[0].life == 31
    game, (engine_,) = _w1g8_board(set_pool, [mrd["Nuisance Engine"]])
    assert game.activate_permanent_ability(0, "Nuisance Engine").supported
    _w1g8_resolve_stack(game)
    (pest,) = [p for p in game.players[0].battlefield if p is not engine_]
    assert pest.card.type_line == "Artifact Creature — Pest"
    assert (pest.effective_power, pest.effective_toughness) == (0, 1)
    assert not pest.card.colors
    game, (tower, bears) = _w1g8_board(
        set_pool, [mrd["Tower of Champions"], lea["Grizzly Bears"]],
    )
    game.activate_permanent_ability(
        0, "Tower of Champions", target_permanent_ids=[bears.permanent_id]
    )
    _w1g8_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (8, 8)
    game, (fortunes,) = _w1g8_board(set_pool, [mrd["Tower of Fortunes"]])
    game.enforce_mana_costs = True
    game.players[0].mana_pool["C"] = 7
    assert not game.activate_permanent_ability(0, "Tower of Fortunes").supported
    game.players[0].mana_pool["C"] = 8
    before = len(game.players[0].hand)
    assert game.activate_permanent_ability(0, "Tower of Fortunes").supported
    _w1g8_resolve_stack(game)
    assert len(game.players[0].hand) - before == 4


# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_scales_board(set_pool, *, theirs=(), interactive=()):
    """Culling Scales (mana value 3) and a Forest on seat 0; *theirs* (LEA
    names) on seat 1."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    scales = _w1g9_Permanent(card=mrd["Culling Scales"])
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P0", battlefield=[scales, _w1g9_Permanent(card=lea["Forest"])]
        ),
        _w1g9_PlayerState(
            name="P1", battlefield=[_w1g9_Permanent(card=lea[n]) for n in theirs]
        ),
    ])
    game.interactive_seats = set(interactive)
    return game, scales


def test_w1g9_culling_scales_destroys_the_lowest_nonland_permanent(set_pool):
    """"…destroy target nonland permanent with the lowest mana value." The
    Forest (mana value 0) is a land and out of the set; the Elves (1) are the
    lowest of what is left, the Bears (2) and the Scales (3) survive."""
    game, scales = _w1g9_scales_board(
        set_pool, theirs=["Llanowar Elves", "Grizzly Bears"]
    )
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert [c.name for c in game.players[1].graveyard] == ["Llanowar Elves"]
    assert {p.card.name for p in game.all_permanents()} == {
        "Culling Scales", "Forest", "Grizzly Bears",
    }
    assert "Culling Scales destroyed Llanowar Elves" in game.log


def test_w1g9_culling_scales_offers_only_the_tied_lowest(set_pool):
    """The picker (CR 601.2c) offers the permanents tied for lowest and
    nothing else — "If two or more permanents are tied for lowest, target any
    one of them." An interactive controller picks; the Giant (4) is never on
    offer."""
    game, _ = _w1g9_scales_board(
        set_pool, theirs=["Llanowar Elves", "Birds of Paradise", "Hill Giant"],
        interactive=(0,),
    )
    game.resolve_upkeep(0)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("trigger_target", 0)
    ]
    offered = game.pending_choices[0].data["targets"]
    assert sorted(t["name"] for t in offered) == ["Birds of Paradise", "Llanowar Elves"]
    birds = next(p for p in game.all_permanents() if p.card.name == "Birds of Paradise")
    assert game.confirm_trigger_target(0, permanent_id=birds.permanent_id) is True
    _w1g9_resolve_stack(game)
    game._settle()
    assert [c.name for c in game.players[1].graveyard] == ["Birds of Paradise"]


def test_w1g9_culling_scales_target_no_longer_lowest_is_not_destroyed(set_pool):
    """The ruling (2004-12-01): "If the targeted permanent doesn't have the
    lowest mana value when the ability resolves, the ability doesn't resolve
    and the permanent isn't destroyed." A Black Lotus (0) entering in response
    makes the targeted Elves illegal at CR 608.2b."""
    game, _ = _w1g9_scales_board(set_pool, theirs=["Llanowar Elves"], interactive=(0,))
    game.resolve_upkeep(0)
    elves = next(p for p in game.all_permanents() if p.card.name == "Llanowar Elves")
    assert game.confirm_trigger_target(0, permanent_id=elves.permanent_id) is True
    assert game.stack, "the trigger waits on the stack for its resolution"
    lotus = _w1g9_Permanent(card=set_pool("LEA")["Black Lotus"])
    game._put_permanent_onto_battlefield(1, lotus, None)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.is_on_battlefield(elves)
    assert game.is_on_battlefield(lotus)
    assert not game.players[1].graveyard


def test_w1g9_culling_scales_can_destroy_itself(set_pool):
    """The ruling (2004-12-01): "If the lowest mana value is 3, Culling Scales
    can destroy itself." With only a Hill Giant (4) beside it, the Scales are
    the one legal target."""
    game, scales = _w1g9_scales_board(set_pool, theirs=["Hill Giant"])
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert not game.is_on_battlefield(scales)
    assert [c.name for c in game.players[0].graveyard] == ["Culling Scales"]


def _w1g9_choker_game(set_pool):
    from engine.named_counters import counters_on

    choker = _w1g9_Permanent(card=set_pool("MRD")["Jinxed Choker"])
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(name="P0", battlefield=[choker]),
        _w1g9_PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    return game, choker, (lambda: counters_on(choker, "charge"))


def test_w1g9_jinxed_choker_end_step_hands_itself_over_with_a_counter(set_pool):
    """"At the beginning of your end step, target opponent gains control of
    this artifact and puts a charge counter on it." Then the new controller's
    upkeep deals them damage equal to the counters — the ruling (2004-12-01):
    "'You' is always Jinxed Choker's current controller." """
    game, choker, charge = _w1g9_choker_game(set_pool)
    game.resolve_end_step(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(choker) == 1
    assert charge() == 1
    assert "P1 gains control of Jinxed Choker" in game.log

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _w1g9_resolve_stack(game)
    game._settle()
    assert [p.life for p in game.players] == [20, 19]

    # And back again at P1's end step, with a second counter.
    game.resolve_end_step(1)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(choker) == 0
    assert charge() == 2


def test_w1g9_jinxed_choker_activation_chooses_put_or_remove_on_resolution(set_pool):
    """"{3}: Put a charge counter on this artifact or remove one from it." The
    ruling (2004-12-01): "you choose to either add or remove a counter when the
    ability resolves." An interactive controller is asked as it resolves and
    removes one; a seat nobody asks takes the first printed option."""
    game, choker, charge = _w1g9_choker_game(set_pool)
    game.resolve_end_step(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert charge() == 1

    game.interactive_seats = {1}
    logged = len(game.log)
    game.activate_permanent_ability(1, "Jinxed Choker")
    # Announced with nothing chosen, and asked as it resolves (CR 608.2d):
    # the object is held on the stack while the answer is owed.
    assert game.log[logged:] == [
        "Jinxed Choker ability added to stack",
        "Jinxed Choker ability is resolving, awaiting a choice",
    ]
    assert [item.resolution_held for item in game.stack] == [True]
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("mode_choice", 1)
    ]
    assert game.pending_choices[0].data["labels"] == [
        "put a charge counter", "remove a charge counter",
    ]
    assert game.resolve_pending_choice("mode_choice", 1, mode_index=1)
    _w1g9_resolve_stack(game)
    game._settle()
    assert charge() == 0

    game.interactive_seats = set()
    game.activate_permanent_ability(1, "Jinxed Choker")
    _w1g9_resolve_stack(game)
    game._settle()
    assert charge() == 1


# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

from engine import Game as _w1g10_Game, PlayerState as _w1g10_PlayerState
from engine.models import Permanent as _w1g10_Permanent
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_table(set_pool, hand=(), their_hand=()):
    """Two seats with Forests to draw, costs unenforced, P2 active so the
    next turn begun is P1's."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_Game(players=[
        _w1g10_PlayerState("P1", library=[forest] * 20, hand=list(hand)),
        _w1g10_PlayerState("P2", library=[forest] * 20, hand=list(their_hand)),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game.turn = 1
    return game


def _w1g10_put(game, seat, card):
    permanent = _w1g10_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g10_mindstorm_crown_draws_when_the_turn_began_with_an_empty_hand(set_pool):
    game = _w1g10_table(set_pool)
    _w1g10_put(game, 0, set_pool("MRD")["Mindstorm Crown"])
    game.start_next_turn()            # P1: untap, upkeep (the Crown), draw step
    _w1g10_resolve_stack(game)
    p1 = game.players[0]
    assert p1.life == 20
    # One from the Crown, one from the draw step.
    assert len(p1.hand) == 2
    assert "P1 drew 1 card(s) (Mindstorm Crown)" in game.log


def test_w1g10_mindstorm_crown_deals_one_when_the_turn_began_with_a_card(set_pool):
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_table(set_pool, hand=[forest, forest])
    _w1g10_put(game, 0, set_pool("MRD")["Mindstorm Crown"])
    game.start_next_turn()
    _w1g10_resolve_stack(game)
    p1 = game.players[0]
    # "If you had a card in hand" is one *or more*: two cards still hurt.
    assert p1.life == 19
    assert len(p1.hand) == 3          # only the draw step drew
    assert "Mindstorm Crown dealt 1 damage to P1" in game.log


def test_w1g10_mindstorm_crown_reads_the_hand_the_turn_began_with(set_pool):
    """The 2004-12-01 ruling: two Crowns and an empty hand at the start of the
    turn draw two cards — the first Crown's draw does not turn the second
    into a damage trigger, because the hand asked about is the turn's first."""
    game = _w1g10_table(set_pool)
    crown = set_pool("MRD")["Mindstorm Crown"]
    _w1g10_put(game, 0, crown)
    _w1g10_put(game, 0, crown)
    game.start_next_turn()
    _w1g10_resolve_stack(game)
    p1 = game.players[0]
    assert p1.life == 20
    assert len(p1.hand) == 3
    assert game.log.count("P1 drew 1 card(s) (Mindstorm Crown)") == 2


def test_w1g10_mindstorm_crown_ignores_the_hand_at_the_upkeep(set_pool):
    """A hand emptied after the turn began is still a turn that began with a
    card: the record, not the hand at resolution, is asked."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_table(set_pool, hand=[forest])
    _w1g10_put(game, 0, set_pool("MRD")["Mindstorm Crown"])
    game.begin_turn_bookkeeping(0)
    game.turn += 1
    game.players[0].hand.clear()      # gone before the upkeep asks
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)
    _w1g10_resolve_stack(game)
    assert game.players[0].life == 19
    assert not game.players[0].hand


def test_w1g10_platinum_angel_keeps_its_controller_in_the_game(set_pool):
    """A Lightning Bolt to 0 life with the Angel out: no loss, and the game
    goes on; the Angel dies and the next state-based check takes the game.
    The whole of CR 104.3 is in tests/rules/test_mrd_w1g10_cant_lose_the_game.py."""
    game = _w1g10_table(set_pool, their_hand=[set_pool("LEA")["Lightning Bolt"]])
    angel = _w1g10_put(game, 0, set_pool("MRD")["Platinum Angel"])
    game.players[0].life = 2
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g10_resolve_stack(game)
    game.check_state_based_actions()
    assert game.players[0].life == -1
    assert not game.players[0].lost and not game.is_game_over()
    game.remove_from_battlefield(angel)
    game._permanent_to_graveyard(game.players[0], angel)
    game.check_state_based_actions()
    assert game.players[0].lost
    assert game.get_winner() is game.players[1]

def _w1g10_sifter_table(set_pool, top0, top1):
    """P1 controls Timesifter; each library is the named cards, top first."""
    lea = set_pool("LEA")
    game = _w1g10_Game(players=[
        _w1g10_PlayerState("P1", library=[lea[name] for name in top0]),
        _w1g10_PlayerState("P2", library=[lea[name] for name in top1]),
    ])
    game.enforce_mana_costs = False
    sifter = _w1g10_put(game, 0, set_pool("MRD")["Timesifter"])
    return game, sifter


def test_w1g10_timesifter_gives_the_greatest_mana_value_an_extra_turn(set_pool):
    game, sifter = _w1g10_sifter_table(
        set_pool, ["Forest", "Forest", "Forest"], ["Shivan Dragon", "Forest", "Forest"],
    )
    game.active_player_index = 0
    game.turn = 1
    game.resolve_upkeep(0)            # P1's upkeep: each upkeep, not only yours
    _w1g10_resolve_stack(game)
    assert [card.name for card in game.players[0].exile] == ["Forest"]
    assert [card.name for card in game.players[1].exile] == ["Shivan Dragon"]
    assert "P2 gained an extra turn" in game.log
    # The extra turn comes after this one, and then the turn that was next
    # anyway (the 2004-12-01 ruling: "Remember which player would have taken
    # the next turn").
    game.remove_from_battlefield(sifter)
    game._permanent_to_graveyard(game.players[0], sifter)
    game.players[0].library.extend([set_pool("LEA")["Forest"]] * 5)
    game.players[1].library.extend([set_pool("LEA")["Forest"]] * 5)
    assert game.start_next_turn() == 1
    assert game.current_turn_is_extra
    assert game.start_next_turn() == 1
    assert not game.current_turn_is_extra
    assert game.start_next_turn() == 0


def test_w1g10_timesifter_ties_repeat_among_the_tied_players(set_pool):
    game, _ = _w1g10_sifter_table(
        set_pool, ["Grizzly Bears", "Forest"], ["Grizzly Bears", "Hill Giant"],
    )
    game.resolve_upkeep(0)
    _w1g10_resolve_stack(game)
    assert "Timesifter: P1, P2 tied at mana value 2 and repeat the process" in game.log
    assert len(game.players[0].exile) == 2 and len(game.players[1].exile) == 2
    assert game.extra_turn_queue == [1]


def test_w1g10_timesifter_a_player_who_exiles_nothing_cannot_win(set_pool):
    """The ruling: "If a player fails to exile a card, they can't take the
    extra turn." The tie at 0 is repeated; P2 has nothing left to exile, so P1
    is the only one with a card, and wins."""
    game, _ = _w1g10_sifter_table(set_pool, ["Forest", "Forest"], ["Island"])
    game.resolve_upkeep(1)
    _w1g10_resolve_stack(game)
    assert "Timesifter: P2 has no card to exile" in game.log
    assert game.extra_turn_queue == [0]

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


def _w1g11_flip_won_or_lost(game, player):
    """One flip by *player* through the engine's flip seam, at a table nobody
    sits at (a seat nobody asks keeps the win): whether the kept coin won."""
    import engine.handlers.control_flow as _w1g11_control_flow
    from engine.handlers.coin_runs import flip_won_or_lost

    kept = []
    flip_won_or_lost(
        game, player, flip=_w1g11_control_flow.flip_coin, card_name="a flip",
        then=kept.append,
    )
    assert len(kept) == 1
    return kept[0]


def test_w1g11_krarks_thumb_flips_two_coins_and_keeps_the_win(set_pool, monkeypatch):
    """Alice flips (a "flip a coin; if you win" ability): with the Thumb out,
    two coins, the loss ignored (Alice's seat is nobody's to ask, so it
    keeps the win)."""
    mrd = set_pool("MRD")
    game, alice, _bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Krark's Thumb"])

    flips = _w1g11_rigged_coins(monkeypatch, [False, True])
    assert _w1g11_flip_won_or_lost(game, alice)
    assert len(flips) == 2
    assert any("flips 2 coins instead of 1" in line for line in game.log)


def test_w1g11_krarks_thumb_both_coins_lost_is_a_loss(set_pool, monkeypatch):
    mrd = set_pool("MRD")
    game, alice, _bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Krark's Thumb"])

    _w1g11_rigged_coins(monkeypatch, [False, False])
    assert not _w1g11_flip_won_or_lost(game, alice)


def test_w1g11_krarks_thumb_is_only_its_controllers(set_pool, monkeypatch):
    """"If **you** would flip a coin": Bob's flips are one coin."""
    mrd = set_pool("MRD")
    game, _alice, bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Krark's Thumb"])

    flips = _w1g11_rigged_coins(monkeypatch, [False, True])
    assert not _w1g11_flip_won_or_lost(game, bob)
    assert len(flips) == 1


def test_w1g11_two_thumbs_flip_four_coins(set_pool, monkeypatch):
    """CR 614.5: each Thumb has the flip once, the second doubling the two
    flips the first made — four coins, three ignored."""
    mrd = set_pool("MRD")
    game, alice, _bob = _w1g11_table(set_pool)
    _w1g11_put(game, 0, mrd["Krark's Thumb"])
    _w1g11_put(game, 0, mrd["Krark's Thumb"])

    flips = _w1g11_rigged_coins(monkeypatch, [False, False, False, True])
    assert _w1g11_flip_won_or_lost(game, alice)
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
#
# Farsight Mask: "Whenever a source an opponent controls deals damage to you,
# if this artifact is untapped, you may draw a card." The `damage_dealt` row's
# seat narrowing on the damager's side ("a source **an opponent** controls"),
# once per source (each attacker separately, 2004-12-01), with CR 603.4's
# intervening "if" asked as it triggers and again as it resolves.

import pytest as _w1g12_pytest

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine.models import Permanent as _w1g12_Permanent
from tests.helpers import _nosick as _w1g12_nosick
from tests.helpers import declare_attack as _w1g12_declare_attack
from tests.helpers import resolve_stack as _w1g12_resolve_stack

_w1g12_pytest_mark_parametrize = _w1g12_pytest.mark.parametrize


def _w1g12_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g12_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=(),
                 interactive=()):
    """Seat 0 (A) in its first main phase, mana off; each named permanent
    untapped and able to act."""
    card = lambda name: _w1g12_card(set_pool, name)  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState(
            "A", hand=[card(n) for n in hand], library=[card("Forest")] * 12,
        ),
        _w1g12_PlayerState(
            "B", hand=[card(n) for n in opponent_hand],
            library=[card("Island")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
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


def _w1g12_settle(game):
    """Drain the stack and take every offer a headless seat is owed."""
    _w1g12_resolve_stack(game)
    game.auto_resolve_pending_choices()


def test_w1g12_farsight_mask_draws_once_per_opposing_source(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Farsight Mask"], theirs=["Alpha Myr", "Grizzly Bears"],
    )
    _w1g12_declare_attack(game, 1)
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert game.players[0].life == 16
    assert len(game.players[0].hand) == 2


def test_w1g12_farsight_mask_ignores_your_own_source_and_a_tapped_mask(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Farsight Mask", "Pyrite Spellbomb"],
    )
    assert game.activate_permanent_ability(
        0, "Pyrite Spellbomb", target_player_index=0, ability_index=0,
    ).supported
    _w1g12_settle(game)
    assert game.players[0].life == 18
    assert game.players[0].hand == []
    game, (mask,), _ = _w1g12_table(
        set_pool, mine=["Farsight Mask"], theirs=["Grizzly Bears"],
    )
    mask.tapped = True
    _w1g12_declare_attack(game, 1)
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert game.players[0].life == 18
    assert game.players[0].hand == []


def test_w1g12_farsight_mask_tapped_before_it_resolves_draws_nothing(set_pool):
    # 2004-12-01: "Farsight Mask must be untapped both when the damage is
    # dealt and when you would draw the card." Bolted, the trigger waits on
    # the stack, and the Mask is tapped in response.
    game, (mask,), _ = _w1g12_table(
        set_pool, mine=["Farsight Mask"], opponent_hand=["Lightning Bolt"],
    )
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Farsight Mask"]
    mask.tapped = True
    _w1g12_settle(game)
    assert game.players[0].hand == []
    assert "Farsight Mask ability did nothing: its condition is no longer true" in game.log


def test_w1g12_farsight_mask_asks_an_interactive_seat(set_pool):
    for accept, drawn in ((True, 1), (False, 0)):
        game, _, _ = _w1g12_table(
            set_pool, mine=["Farsight Mask"], opponent_hand=["Lightning Bolt"],
            interactive=(0,),
        )
        game.active_player_index = 1
        assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
        game.resolve_top_of_stack()
        game.resolve_top_of_stack()
        assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
        assert game.confirm_optional_pay(0, accept=accept)
        _w1g12_settle(game)
        assert len(game.players[0].hand) == drawn


# Damping Matrix: "Activated abilities of artifacts and creatures can't be
# activated unless they're mana abilities." Null Rod's board-wide row
# (``activation_prohibitions``) with a type list and CR 605.1a's exception,
# asked of the ability on every road: the activation path, the wire's
# ``ability_denials`` and the AI's choosers.


def test_w1g12_damping_matrix_stops_nonmana_abilities_of_artifacts_and_creatures(set_pool):
    game, (_matrix, sorcerer, _elves, bomb, scimitar), (exile,) = _w1g12_table(
        set_pool,
        mine=["Damping Matrix", "Prodigal Sorcerer", "Llanowar Elves",
              "Pyrite Spellbomb", "Leonin Scimitar"],
        theirs=["Tel-Jilad Exile"],
    )
    refused = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert not refused.supported
    assert "(Damping Matrix)" in refused.details
    # Refused before the cost: the Spellbomb is not sacrificed.
    assert not game.activate_permanent_ability(
        0, "Pyrite Spellbomb", target_player_index=1, ability_index=0,
    ).supported
    assert game.is_on_battlefield(bomb)
    # Equip is an activated ability of an artifact (2017-03-14).
    assert not game.activate_permanent_ability(
        0, "Leonin Scimitar", target_permanent_ids=[sorcerer.permanent_id],
    ).supported
    assert not game.activate_permanent_ability(1, "Tel-Jilad Exile").supported
    assert game.players[1].life == 20


def test_w1g12_damping_matrix_leaves_mana_abilities_open(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Damping Matrix", "Llanowar Elves", "Sol Ring", "Seat of the Synod"],
    )
    assert game.activate_permanent_ability(0, "Llanowar Elves").supported
    assert game.activate_permanent_ability(0, "Sol Ring").supported
    assert game.players[0].mana_pool["G"] == 1
    assert game.players[0].mana_pool["C"] == 2


def test_w1g12_damping_matrix_is_on_the_wire_and_ends_when_it_leaves(set_pool):
    from web.offers import _ability_denial

    game, (matrix, sorcerer, elves), _ = _w1g12_table(
        set_pool, mine=["Damping Matrix", "Prodigal Sorcerer", "Llanowar Elves"],
    )
    (ping,) = game.usable_abilities_of(sorcerer)
    (tap,) = game.usable_abilities_of(elves)
    assert "(Damping Matrix)" in (_ability_denial(game, 0, sorcerer, ping) or "")
    assert _ability_denial(game, 0, elves, tap) is None
    game.remove_from_battlefield(matrix)
    assert _ability_denial(game, 0, sorcerer, ping) is None
    assert game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1).supported
    _w1g12_resolve_stack(game)
    assert game.players[1].life == 19


# Quicksilver Fountain. "At the beginning of each player's upkeep, that player
# puts a flood counter on target non-Island land they control of their choice.
# That land is an Island for as long as it has a flood counter on it." / "At
# the beginning of each end step, if all lands on the battlefield are Islands,
# remove all flood counters from them." The Abyss's choice made by the upkeep
# player, a CR 305.7 land-type change ended by the last flood counter
# (``named_counters.remove_counters``), and a universal condition whose set
# "them" names.


def _w1g12_flood(land):
    from engine.named_counters import counters_on

    return counters_on(land, "flood")


def test_w1g12_quicksilver_fountain_floods_a_land_of_the_upkeep_players(set_pool):
    game, (_fountain, plains), (mountain, forest) = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Plains"], theirs=["Mountain", "Forest"],
    )
    # A's own upkeep ran as the table opened: A's only land is flooded.
    assert _w1g12_flood(plains) == 1 and plains.has_type("island")
    assert not plains.has_type("plains")
    game.start_turn(1)
    _w1g12_settle(game)
    flooded = [land for land in (mountain, forest) if _w1g12_flood(land)]
    assert len(flooded) == 1
    (land,) = flooded
    assert land.has_type("island")
    assert land.effective_produced_mana == ("U",)


def test_w1g12_quicksilver_fountain_asks_the_upkeep_player_for_their_land(set_pool):
    game, (_fountain, plains), (mountain, forest, island) = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Plains"],
        theirs=["Mountain", "Forest", "Island"], interactive=(1,),
    )
    game.start_turn(1)
    assert not game.resolve_top_of_stack()  # held for B's answer
    (choice,) = game.pending_choices
    assert (choice.kind, choice.player_index) == ("permanent_choice", 1)
    # Not an Island, and not another player's land.
    assert not game.confirm_permanent_choice(1, island.permanent_id)
    assert not game.confirm_permanent_choice(1, plains.permanent_id)
    assert game.confirm_permanent_choice(1, forest.permanent_id)
    _w1g12_resolve_stack(game)
    assert _w1g12_flood(forest) == 1 and forest.has_type("island")
    assert _w1g12_flood(mountain) == 0 and mountain.has_type("mountain")


def test_w1g12_quicksilver_fountain_end_step_resets_an_all_island_board(set_pool):
    game, _, (mountain,) = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Island"], theirs=["Mountain"],
    )
    game.start_turn(1)
    _w1g12_settle(game)
    assert mountain.has_type("island") and _w1g12_flood(mountain) == 1
    game.resolve_end_step(1)
    _w1g12_settle(game)
    assert _w1g12_flood(mountain) == 0
    assert mountain.has_type("mountain") and not mountain.has_type("island")


def test_w1g12_quicksilver_fountain_end_step_waits_while_a_land_is_not_an_island(set_pool):
    game, (_fountain, plains), (mountain, forest) = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Plains"], theirs=["Mountain", "Forest"],
    )
    game.start_turn(1)
    _w1g12_settle(game)
    game.resolve_end_step(1)
    _w1g12_settle(game)
    # One of B's two lands is still not an Island: nothing is removed.
    assert _w1g12_flood(plains) == 1
    assert sum(_w1g12_flood(land) for land in (mountain, forest)) == 1


def test_w1g12_quicksilver_fountains_island_outlives_it_and_ends_with_the_counter(set_pool):
    # 2004-12-01: "The land stays an Island until the flood counter is
    # removed, even if Quicksilver Fountain leaves the battlefield." And once
    # the counter is gone the effect is over (CR 611.2b): a flood counter put
    # back later does not revive it.
    from engine.named_counters import add_counters, remove_counters

    game, (fountain, plains), _ = _w1g12_table(
        set_pool, mine=["Quicksilver Fountain", "Plains"],
    )
    game.remove_from_battlefield(fountain)
    assert plains.has_type("island") and not plains.has_type("plains")
    remove_counters(plains, "flood", 1)
    assert plains.has_type("plains") and not plains.has_type("island")
    add_counters(plains, "flood", 1)
    assert plains.has_type("plains") and not plains.has_type("island")


# The drive list: Mirrodin artifacts that compiled supported on arrival and
# had never been run, each given a game through the real entry points.


def _w1g12_into_blocks(game, attacker_seat, attacker_slots):
    game.active_player_index = attacker_seat
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        attacker_seat, list(attacker_slots), defending_player_index=1 - attacker_seat,
    )
    assert ok, why
    game.advance_combat_phase()


def test_w1g12_welding_jar_regenerates_an_artifact_only(set_pool):
    game, (jar, myr), (bears,) = _w1g12_table(
        set_pool, mine=["Welding Jar", "Alpha Myr"], theirs=["Grizzly Bears"],
        hand=["Lightning Bolt"],
    )
    assert not game.activate_permanent_ability(
        0, "Welding Jar", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.activate_permanent_ability(
        0, "Welding Jar", target_permanent_ids=[myr.permanent_id],
    ).supported
    _w1g12_settle(game)
    assert not game.is_on_battlefield(jar)
    game.queue_from_hand(0, "Lightning Bolt", target_permanent_ids=[myr.permanent_id])
    _w1g12_settle(game)
    game._settle()  # CR 704.5g's check, where the regeneration shield is spent
    assert game.is_on_battlefield(myr) and myr.tapped


def test_w1g12_pewter_golem_regenerates(set_pool):
    game, (golem,), _ = _w1g12_table(set_pool, mine=["Pewter Golem"], hand=["Lightning Bolt"])
    assert game.activate_permanent_ability(0, "Pewter Golem").supported
    _w1g12_settle(game)
    game.queue_from_hand(0, "Lightning Bolt", target_permanent_ids=[golem.permanent_id])
    _w1g12_settle(game)
    game._settle()  # CR 704.5g's check, where the regeneration shield is spent
    assert game.is_on_battlefield(golem) and golem.damage_marked == 0


def test_w1g12_needlebug_flash_and_protection_from_artifacts(set_pool):
    game, _, _ = _w1g12_table(set_pool, hand=["Needlebug"])
    game.active_player_index = 1
    assert game.queue_from_hand(0, "Needlebug").supported
    game, (bug, _bomb), _ = _w1g12_table(set_pool, mine=["Needlebug", "Pyrite Spellbomb"])
    assert not game.activate_permanent_ability(
        0, "Pyrite Spellbomb", target_permanent_ids=[bug.permanent_id], ability_index=0,
    ).supported
    game, _, _ = _w1g12_table(
        set_pool, mine=["Needlebug"], theirs=["Alpha Myr", "Grizzly Bears"],
    )
    _w1g12_into_blocks(game, 0, [0])
    assert not game.declare_blockers(1, {0: 0})[0]  # an artifact can't block it
    assert game.declare_blockers(1, {1: 0})[0]


@_w1g12_pytest_mark_parametrize("name,size", [
    ("Alpha Myr", (2, 1)), ("Omega Myr", (1, 2)), ("Steel Wall", (0, 4)),
])
def test_w1g12_an_artifact_creature_casts_at_its_printed_size(set_pool, name, size):
    game, _, _ = _w1g12_table(set_pool, hand=[name])
    assert game.queue_from_hand(0, name).supported
    _w1g12_settle(game)
    (perm,) = [p for p in game.controlled_by(0) if p.card.name == name]
    assert (perm.effective_power, perm.effective_toughness) == size
    assert perm.has_type("artifact")


def test_w1g12_steel_wall_cannot_attack(set_pool):
    game, _, _ = _w1g12_table(set_pool, mine=["Steel Wall"])
    game._set_phase_and_step("combat", "declare_attackers")
    assert not game.declare_attackers(0, [0], defending_player_index=1)[0]


@_w1g12_pytest_mark_parametrize("name,keyword", [
    ("Cobalt Golem", "flying"), ("Malachite Golem", "trample"),
    ("Titanium Golem", "first strike"),
])
def test_w1g12_a_golem_buys_its_keyword(set_pool, name, keyword):
    game, (golem,), _ = _w1g12_table(set_pool, mine=[name])
    assert not game._has_keyword(golem, keyword)
    assert game.activate_permanent_ability(0, name).supported
    _w1g12_settle(game)
    assert game._has_keyword(golem, keyword)


def test_w1g12_hematite_golem_pumps_power_only(set_pool):
    game, (golem,), _ = _w1g12_table(set_pool, mine=["Hematite Golem"])
    for _ in range(2):
        assert game.activate_permanent_ability(0, "Hematite Golem").supported
        _w1g12_settle(game)
    assert (golem.effective_power, golem.effective_toughness) == (5, 4)


def test_w1g12_the_replicas_sacrifice_for_their_effect(set_pool):
    game, (elf,), (crusade,) = _w1g12_table(set_pool, mine=["Elf Replica"], theirs=["Crusade"])
    assert game.activate_permanent_ability(
        0, "Elf Replica", target_permanent_ids=[crusade.permanent_id],
    ).supported
    _w1g12_settle(game)
    assert not game.is_on_battlefield(crusade) and not game.is_on_battlefield(elf)
    game, _, (myr,) = _w1g12_table(set_pool, mine=["Goblin Replica"], theirs=["Alpha Myr"])
    game.activate_permanent_ability(0, "Goblin Replica", target_permanent_ids=[myr.permanent_id])
    _w1g12_settle(game)
    assert not game.is_on_battlefield(myr)
    game, _, (elves,) = _w1g12_table(set_pool, mine=["Nim Replica"], theirs=["Llanowar Elves"])
    game.activate_permanent_ability(0, "Nim Replica", target_permanent_ids=[elves.permanent_id])
    _w1g12_settle(game)
    assert not game.is_on_battlefield(elves)


def test_w1g12_soldier_replica_hits_only_a_creature_in_combat(set_pool):
    game, _, (bears,) = _w1g12_table(set_pool, mine=["Soldier Replica"], theirs=["Grizzly Bears"])
    assert not game.activate_permanent_ability(
        0, "Soldier Replica", target_permanent_ids=[bears.permanent_id],
    ).supported
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(1, [0], defending_player_index=0)[0]
    assert game.activate_permanent_ability(
        0, "Soldier Replica", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g12_settle(game)
    assert not game.is_on_battlefield(bears)


def test_w1g12_wizard_replica_counters_a_spell_its_caster_cannot_pay_for(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Wizard Replica"], opponent_hand=["Grizzly Bears"],
    )
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.activate_permanent_ability(0, "Wizard Replica", target_stack_index=0).supported
    _w1g12_settle(game)
    assert [p.card.name for p in game.controlled_by(1)] == []
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]


def test_w1g12_leonin_sun_standard_pumps_your_creatures_only(set_pool):
    game, (_std, bears, myr), (elves,) = _w1g12_table(
        set_pool, mine=["Leonin Sun Standard", "Grizzly Bears", "Alpha Myr"],
        theirs=["Llanowar Elves"],
    )
    assert game.activate_permanent_ability(0, "Leonin Sun Standard").supported
    _w1g12_settle(game)
    assert (bears.effective_power, myr.effective_power, elves.effective_power) == (3, 3, 1)


def test_w1g12_leonin_bladetrap_flash_and_grounded_attackers(set_pool):
    game, _, _ = _w1g12_table(set_pool, hand=["Leonin Bladetrap"])
    game.active_player_index = 1
    assert game.queue_from_hand(0, "Leonin Bladetrap").supported
    game, _, (bears, thopter) = _w1g12_table(
        set_pool, mine=["Leonin Bladetrap"], theirs=["Grizzly Bears", "Ornithopter"],
    )
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(1, [0, 1], defending_player_index=0)[0]
    assert game.activate_permanent_ability(0, "Leonin Bladetrap").supported
    _w1g12_settle(game)
    assert not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(thopter) and thopter.damage_marked == 0


@_w1g12_pytest_mark_parametrize("name,symbol", [
    ("Ancient Den", "W"), ("Great Furnace", "R"), ("Seat of the Synod", "U"),
    ("Tree of Tales", "G"), ("Vault of Whispers", "B"),
])
def test_w1g12_an_artifact_land_is_played_taps_and_is_an_artifact(set_pool, name, symbol):
    game, _, _ = _w1g12_table(set_pool, hand=[name])
    assert game.cast_from_hand(0, name).supported
    (land,) = [p for p in game.controlled_by(0) if p.card.name == name]
    assert land.has_type("artifact") and land.has_type("land")
    assert game.activate_permanent_ability(0, name).supported
    assert game.players[0].mana_pool[symbol] == 1
    game, _, (theirs,) = _w1g12_table(set_pool, theirs=[name], hand=["Shatter"])
    assert game.queue_from_hand(0, "Shatter", target_permanent_ids=[theirs.permanent_id]).supported
    _w1g12_settle(game)
    assert not game.is_on_battlefield(theirs)

# ==== end W1G12 ======================================================


# ==== W2G2 ==========================================================
# W2G2's tests go between this line and the "end W2G2" line.

import random as _w2g2_random

from engine.game import Game as _W2G2Game
from engine.models import Permanent as _W2G2Permanent
from engine.models import PlayerState as _W2G2PlayerState
from engine.oracle import compile_card_oracle as _w2g2_compile
from engine.targeting import derive_activation_spec as _w2g2_activation_spec
from engine.oracle_types import NAMED_CARD_GUESS as _W2G2_NAMED_CARD_GUESS

from tests.helpers import resolve_stack as _w2g2_resolve_stack


def _w2g2_pendulum_table(set_pool, *, hand=(), interactive=(0, 1)):
    """Alice (seat 0) controls an untapped Liar's Pendulum; Bob is seat 1."""
    lea, mrd = set_pool("LEA"), set_pool("MRD")
    alice = _W2G2PlayerState(
        name="Alice", hand=list(hand), library=[lea["Plains"]] * 6,
    )
    bob = _W2G2PlayerState(name="Bob", library=[lea["Island"]] * 6)
    game = _W2G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    pendulum = _W2G2Permanent(card=mrd["Liar's Pendulum"])
    game._put_permanent_onto_battlefield(0, pendulum, None)
    pendulum.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return game, alice, bob, pendulum


def _w2g2_swing(game, pendulum):
    result = game.activate_permanent_ability(
        0, "Liar's Pendulum", permanent_index=game.battlefield_index_of(pendulum),
        ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    assert pendulum.tapped


def _w2g2_owed(game):
    return [(choice.kind, choice.player_index) for choice in game.pending_choices]


def _w2g2_pendulum_by_hand(game, *, name, guess, reveal):
    """Answer the three prompts as two people: Alice names, Bob guesses,
    Alice says whether she reveals."""
    assert _w2g2_owed(game) == [("choose_card_name", 0)]
    assert game.confirm_choose_card_name(0, name)
    assert _w2g2_owed(game) == [("guess_named_card", 1)]
    assert game.confirm_guess_named_card(1, guess)
    assert _w2g2_owed(game) == [("optional_pay", 0)]
    assert game.confirm_optional_pay(0, accept=reveal)
    _w2g2_resolve_stack(game)
    assert not game.stack and not game.pending_choices


def test_w2g2_liars_pendulum_compiles_whole_and_aims_at_an_opponent(set_pool):
    program = _w2g2_compile(set_pool("MRD")["Liar's Pendulum"])
    assert program.supported
    (ability,) = program.activated_abilities
    steps = [step.kind for step in ability.instruction.payload["steps"]]
    assert steps == ["choose_card_name", "guess_named_card_in_hand", "may"]
    # The picker offers what the line says: an opponent, chosen as the
    # ability is activated (CR 602.2b).
    assert _w2g2_activation_spec(ability) == {"kind": "player", "opponents_only": True}


def test_w2g2_a_wrong_guess_and_a_reveal_draws_a_card(set_pool):
    lea = set_pool("LEA")
    game, alice, bob, pendulum = _w2g2_pendulum_table(set_pool, hand=[lea["Shivan Dragon"]])
    _w2g2_swing(game, pendulum)
    _w2g2_pendulum_by_hand(game, name="Shivan Dragon", guess=False, reveal=True)
    assert [card.name for card in alice.hand] == ["Shivan Dragon", "Plains"]
    assert any("Bob guesses that a card named Shivan Dragon is not in Alice's hand" in line
               for line in game.log)
    assert any("Alice reveals their hand" in line for line in game.log)


def test_w2g2_a_right_guess_draws_nothing_even_revealed(set_pool):
    lea = set_pool("LEA")
    game, alice, _bob, pendulum = _w2g2_pendulum_table(set_pool, hand=[lea["Shivan Dragon"]])
    _w2g2_swing(game, pendulum)
    _w2g2_pendulum_by_hand(game, name="Shivan Dragon", guess=True, reveal=True)
    assert [card.name for card in alice.hand] == ["Shivan Dragon"]


def test_w2g2_no_reveal_no_card_however_wrong_the_guess(set_pool):
    """2004-12-01: "You can't draw a card if you don't reveal your hand.\""""
    lea = set_pool("LEA")
    game, alice, _bob, pendulum = _w2g2_pendulum_table(set_pool, hand=[lea["Shivan Dragon"]])
    _w2g2_swing(game, pendulum)
    _w2g2_pendulum_by_hand(game, name="Grizzly Bears", guess=True, reveal=False)
    assert [card.name for card in alice.hand] == ["Shivan Dragon"]
    assert not any("reveals their hand" in line for line in game.log)


def test_w2g2_a_name_held_nowhere_guessed_absent_is_right(set_pool):
    lea = set_pool("LEA")
    game, alice, _bob, pendulum = _w2g2_pendulum_table(set_pool, hand=[lea["Shivan Dragon"]])
    _w2g2_swing(game, pendulum)
    _w2g2_pendulum_by_hand(game, name="Grizzly Bears", guess=False, reveal=True)
    assert [card.name for card in alice.hand] == ["Shivan Dragon"]


def test_w2g2_the_engine_played_controller_reveals_only_for_a_wrong_guess(set_pool):
    """Alice is nobody's seat; Bob is a person. Alice names the card she
    holds (her own hand is what the guess is about). Guessed right, she keeps
    her hand hidden — revealing would buy nothing — and guessed wrong she
    reveals and draws."""
    lea = set_pool("LEA")
    for guess, revealed in ((True, False), (False, True)):
        game, alice, _bob, pendulum = _w2g2_pendulum_table(
            set_pool, hand=[lea["Shivan Dragon"]], interactive=(1,),
        )
        _w2g2_swing(game, pendulum)
        game.auto_resolve_pending_choices(only_player_index=0)
        assert _w2g2_owed(game) == [("guess_named_card", 1)]
        choice = game.pending_choices[0]
        assert choice.data["named"] == "Shivan Dragon"
        assert game.confirm_guess_named_card(1, guess)
        _w2g2_resolve_stack(game)
        game.auto_resolve_pending_choices(only_player_index=0)
        _w2g2_resolve_stack(game)
        shown = any("Alice reveals their hand" in line for line in game.log)
        assert shown is revealed, (guess, game.log[-4:])
        assert len(alice.hand) == (2 if revealed else 1)


def test_w2g2_an_engine_played_guess_never_reads_the_hand(set_pool):
    """The guesser's default is a coin from the seeded RNG: the same seed
    gives the same guess whatever the hidden hand holds (CR 400.2) — and an
    empty hand, whose size is public (CR 402.3), is deduced rather than
    guessed."""
    lea = set_pool("LEA")
    game, _alice, _bob, pendulum = _w2g2_pendulum_table(set_pool, interactive=(0,))
    _w2g2_swing(game, pendulum)
    assert game.confirm_choose_card_name(0, "Shivan Dragon")
    game.auto_resolve_pending_choices()
    assert any("Shivan Dragon is not in Alice's hand" in line for line in game.log)
    guesses = []
    for hand in ([lea["Shivan Dragon"]], [lea["Island"]], [lea["Island"], lea["Island"]]):
        game, _alice, _bob, pendulum = _w2g2_pendulum_table(set_pool, hand=hand, interactive=(0,))
        _w2g2_swing(game, pendulum)
        assert game.confirm_choose_card_name(0, "Shivan Dragon")
        assert _w2g2_owed(game) == [("guess_named_card", 1)]
        _w2g2_random.seed(20041201)
        game.auto_resolve_pending_choices()
        line = next(line for line in game.log if "guesses that" in line)
        guesses.append(" is not in " not in line)
    assert len(set(guesses)) == 1, guesses


def test_w2g2_the_guess_prompt_shows_the_name_and_never_the_hand(set_pool):
    """What the guesser's client is sent: the name and whose hand — the
    hand itself is hidden from that seat, and so is whether the guess would
    be right."""
    from web.prompt_registry import PromptContext
    from web.prompts import render_prompts

    lea = set_pool("LEA")
    game, _alice, _bob, pendulum = _w2g2_pendulum_table(set_pool, hand=[lea["Shivan Dragon"]])
    _w2g2_swing(game, pendulum)
    assert game.confirm_choose_card_name(0, "Shivan Dragon")
    shown = render_prompts(PromptContext(
        game=game, viewer_seat=1, serialize_card=lambda card: {"name": card.name},
        seat_type=lambda seat: "human",
    ))["guess_named_card"]
    assert shown == {
        "player_seat": 1, "card_name": "Liar's Pendulum", "named": "Shivan Dragon",
        "holder_seat": 0, "holder_name": "Alice",
    }
    # Alice's own view carries no guess prompt: it is Bob's to answer.
    assert render_prompts(PromptContext(
        game=game, viewer_seat=0, serialize_card=lambda card: {"name": card.name},
        seat_type=lambda seat: "human",
    ))["guess_named_card"] is None


def test_w2g2_the_condition_reads_the_guess_record_not_the_hand_after(set_pool):
    """The truth is taken as the guess is made: the record says what the
    guess was about, whatever the hand holds later."""
    lea = set_pool("LEA")
    game, alice, _bob, pendulum = _w2g2_pendulum_table(set_pool, hand=[lea["Shivan Dragon"]])
    _w2g2_swing(game, pendulum)
    assert game.confirm_choose_card_name(0, "Shivan Dragon")
    context = game.pending_choices[0].data["record"]
    assert game.confirm_guess_named_card(1, True)
    assert context[_W2G2_NAMED_CARD_GUESS] == {"in_hand": True, "was_in_hand": True}
    assert game.confirm_optional_pay(0, accept=True)
    _w2g2_resolve_stack(game)
    assert len(alice.hand) == 1

# ==== end W2G2 ======================================================


# ==== W2G1 ==========================================================
# W2G1's tests go between this line and the "end W2G1" line.
#
# Mindslaver — "{4}, {T}, Sacrifice Mindslaver: You control target player
# during that player's next turn." The CR 723 rules themselves are in
# tests/rules/test_mrd_w2g1_controlling_a_player.py; these are the card.
from engine import Game as _w2g1_Game, PlayerState as _w2g1_PlayerState
from engine.models import Permanent as _w2g1_Permanent
from engine.oracle import compile_card_oracle as _w2g1_compile
from engine.targeting import derive_activation_spec as _w2g1_activation_spec
from tests.helpers import resolve_stack as _w2g1_resolve_stack


def _w2g1_table(set_pool, *, their_hand=()):
    lea = set_pool("LEA")
    game = _w2g1_Game(players=[
        _w2g1_PlayerState("P1", library=[lea["Forest"]] * 20),
        _w2g1_PlayerState("P2", library=[lea["Forest"]] * 20, hand=list(their_hand)),
    ])
    game.active_player_index = 0
    game.turn = 1
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _w2g1_put(game, seat, card):
    permanent = _w2g1_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w2g1_mindslaver_picks_a_player_and_costs_four_tap_and_itself(set_pool):
    slaver = set_pool("MRD")["Mindslaver"]
    program = _w2g1_compile(slaver)
    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    assert ability.cost.mana["generic"] == 4
    assert ability.cost.requires_tap and ability.cost.sacrifice_self
    assert _w2g1_activation_spec(ability)["kind"] == "player"


def test_w2g1_mindslaver_paid_for_controls_the_opponents_next_turn(set_pool):
    lea = set_pool("LEA")
    game = _w2g1_table(set_pool, their_hand=[lea["Grizzly Bears"]])
    game.enforce_mana_costs = True
    _w2g1_put(game, 0, set_pool("MRD")["Mindslaver"])
    for _ in range(4):
        _w2g1_put(game, 0, lea["Forest"])
    for land in [p for p in game.players[0].battlefield if p.card.name == "Forest"]:
        assert game.tap_land_for_mana(0, "Forest", permanent_id=land.permanent_id)
    assert game.players[0].mana_pool.get("G") == 4
    result = game.activate_permanent_ability(0, "Mindslaver", target_player_index=1)
    assert result.supported, result.details
    _w2g1_resolve_stack(game)
    assert "Mindslaver" in [card.name for card in game.players[0].graveyard]
    assert "P1 will control P2 during P2's next turn" in game.log
    assert game.decider_of(1) == 1    # not yet: P1's own turn goes on
    game.start_next_turn()
    _w2g1_resolve_stack(game)
    assert (game.active_player_index, game.decider_of(1)) == (1, 0)
    game.start_next_turn()
    _w2g1_resolve_stack(game)
    assert game.decider_of(1) == 1


def test_w2g1_an_ai_controlling_the_opponent_casts_nothing_for_them(set_pool):
    """The controlled seat's whole main phase as the simulator plays it: the
    AI deciding for it plays no land, casts no creature and attacks with
    nothing (``engine/ai_player_control.py``); uncontrolled, it would."""
    from engine.ai_simulator import SimulationReport, _play_land_drops, _play_casts
    from engine.ai_declarations import choose_attackers

    lea = set_pool("LEA")
    game = _w2g1_table(set_pool, their_hand=[lea["Forest"], lea["Grizzly Bears"]])
    game.enforce_mana_costs = False
    bears = _w2g1_put(game, 1, lea["Grizzly Bears"])
    _w2g1_put(game, 0, set_pool("MRD")["Mindslaver"])
    assert game.activate_permanent_ability(0, "Mindslaver", target_player_index=1).supported
    _w2g1_resolve_stack(game)
    game.start_next_turn()
    _w2g1_resolve_stack(game)
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _play_land_drops(game, 1, report, 1, 1)
    _play_casts(game, 1, report, 1, 1)
    assert report.lands_played == 0
    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly Bears"]
    assert choose_attackers(game, 1) == []
    game.player_controls.clear()
    _play_land_drops(game, 1, report, 1, 1)
    assert report.lands_played >= 1
    assert bears in list(game.controlled_by(1))

# ==== end W2G1 ======================================================
