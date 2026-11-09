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
    """"target **artifact creature** card": both types (CR 205.2a). Read as a
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
