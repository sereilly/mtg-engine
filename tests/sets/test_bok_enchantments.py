"""Betrayers of Kamigawa enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
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

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

import pytest as _w1g4_pytest

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.aura_attachment import attach_aura as _w1g4_attach_aura
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_derive_cast_spec
from tests.helpers import settle as _w1g4_settle


def _w1g4_card(set_pool, name):
    """A card by name, from Betrayers of Kamigawa first, then Champions of
    Kamigawa, then Alpha for the fillers."""
    for code in ("BOK", "CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g4_table(set_pool, hand=(), *, mine=(), theirs=(), active=0,
                interactive=(), library=None):
    """Seat 0 to act in *active*'s first main phase, mana off; each named
    permanent untapped and able to act."""
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    game = _w1g4_Game(players=[
        _w1g4_PlayerState(
            "A", hand=[card(n) for n in hand],
            library=[card(n) for n in (library or ["Forest"] * 12)],
        ),
        _w1g4_PlayerState("B", library=[card("Forest")] * 12),
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
    game.start_turn(active)
    game._settle()
    return game, placed[0], placed[1]


def test_w1g4_threads_of_disloyalty_picks_only_a_two_drop(set_pool):
    """"Enchant creature with mana value 2 or less": the picker carries the
    bound, the cast gate refuses a three-drop, and a two-drop is stolen."""
    threads = set_pool("BOK")["Threads of Disloyalty"]
    spec = _w1g4_derive_cast_spec(threads, _w1g4_compile(threads))
    assert spec == {"kind": "creature", "filter": {"mana_value": {"op": "le", "value": 2}}}
    game, _mine, theirs = _w1g4_table(
        set_pool, ["Threads of Disloyalty"], theirs=["Grizzly Bears", "Hill Giant"],
    )
    bears, giant = theirs
    refused = game.cast_from_hand(
        0, "Threads of Disloyalty", target_player_index=1,
        target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].hand] == ["Threads of Disloyalty"]
    result = game.cast_from_hand(
        0, "Threads of Disloyalty", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    assert game.controller_index_of(bears) == 0, game.log
    assert game.controller_index_of(giant) == 1


def test_w1g4_threads_of_disloyalty_falls_off_a_three_drop(set_pool):
    """The ruling (2005-02-01): "If it somehow enchants a creature with mana
    value 3 or greater, Threads of Disloyalty is put into the graveyard the
    next time state-based actions are checked" (CR 704.5m) — and the control
    it gave ends with it."""
    game, mine, theirs = _w1g4_table(
        set_pool, mine=["Threads of Disloyalty"], theirs=["Hill Giant"],
    )
    threads, giant = mine[0], theirs[0]
    _w1g4_attach_aura(threads, giant)
    _w1g4_settle(game)
    assert not game.is_on_battlefield(threads)
    assert "Threads of Disloyalty" in [c.name for c in game.players[0].graveyard]
    assert game.controller_index_of(giant) == 1


def _w1g4_names(cards):
    return [c.name for c in cards]


def test_w1g4_kumanos_blessing_exiles_what_its_host_traded_with(set_pool):
    """"If a creature dealt damage by enchanted creature this turn would die,
    exile it instead": the blocker the enchanted Bears killed is exiled (no
    death, CR 614.6), the Bears itself — dealt damage by the other one — dies
    as usual, and the Aura follows its host to the graveyard."""
    from tests.helpers import declare_attack, drive_combat

    game, mine, theirs = _w1g4_table(
        set_pool, ["Kumano's Blessing"], mine=["Grizzly Bears"], theirs=["Grizzly Bears"],
    )
    result = game.cast_from_hand(
        0, "Kumano's Blessing", target_player_index=0,
        target_permanent_ids=[mine[0].permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    declare_attack(game, 0, blocks={0: 0})
    drive_combat(game)
    assert _w1g4_names(game.players[1].exile) == ["Grizzly Bears"], game.log
    assert _w1g4_names(game.players[1].graveyard) == []
    assert sorted(_w1g4_names(game.players[0].graveyard)) == [
        "Grizzly Bears", "Kumano's Blessing",
    ]


def test_w1g4_kumanos_blessing_reads_its_host_as_the_creature_dies(set_pool):
    """Flashed onto a Craw Wurm *after* the Wurm dealt 6 to a Wall of Stone:
    the Aura's static ability reads "enchanted creature" as the Wall would die
    (the reading Vampiric Embrace's death trigger takes), so the Wall a Bolt
    finishes is exiled — and a Bear the Wurm never touched dies as usual."""
    from tests.helpers import declare_attack, drive_combat

    game, mine, theirs = _w1g4_table(
        set_pool, ["Kumano's Blessing", "Lightning Bolt", "Lightning Bolt"],
        mine=["Craw Wurm"], theirs=["Wall of Stone", "Grizzly Bears"],
    )
    wurm, (wall, bears) = mine[0], theirs
    declare_attack(game, 0, blocks={0: 0})
    drive_combat(game)
    assert game.is_on_battlefield(wall) and wall.damage_marked == 6, game.log
    result = game.cast_from_hand(
        0, "Kumano's Blessing", target_player_index=0,
        target_permanent_ids=[wurm.permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    for victim in (wall, bears):
        bolt = game.cast_from_hand(
            0, "Lightning Bolt", target_player_index=1,
            target_permanent_ids=[victim.permanent_id],
        )
        assert bolt.supported, bolt.details
        _w1g4_settle(game)
    assert _w1g4_names(game.players[1].exile) == ["Wall of Stone"], game.log
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"]


# --- The Genju cycle --------------------------------------------------------
# "Enchant <land>" / "{2}: Enchanted <land> becomes a … Spirit creature until
# end of turn. It's still a land." / "When enchanted <land> is put into a
# graveyard, you may return this card from your graveyard to your hand."

def _w1g4_genju_on(set_pool, genju, land, *, hand=(), theirs=(), interactive=()):
    """Seat 0 with *genju* cast onto its own *land*; returns the game, the
    land and the Aura permanent."""
    game, mine, _theirs = _w1g4_table(
        set_pool, [genju, *hand], mine=[land], theirs=theirs, interactive=interactive,
    )
    host = mine[0]
    result = game.cast_from_hand(
        0, genju, target_player_index=0, target_permanent_ids=[host.permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    aura = next(p for p in game.controlled_by(0) if p.card.name == genju)
    assert aura.metadata.get("attached_to") is host
    return game, host, aura


def _w1g4_animate(game, genju):
    result = game.activate_permanent_ability(0, genju)
    assert result.supported, result.details
    _w1g4_settle(game)


def _w1g4_end_turn(game, seat=0):
    game.resolve_end_step(seat)
    game.resolve_cleanup_step(seat)
    _w1g4_settle(game)


def test_w1g4_genju_of_the_cedars_enchants_only_a_forest(set_pool):
    """"Enchant Forest" (CR 303.4a): the cast gate refuses a Plains."""
    game, mine, _theirs = _w1g4_table(
        set_pool, ["Genju of the Cedars"], mine=["Plains", "Forest"],
    )
    plains, forest = mine
    refused = game.cast_from_hand(
        0, "Genju of the Cedars", target_player_index=0,
        target_permanent_ids=[plains.permanent_id],
    )
    assert not refused.supported
    result = game.cast_from_hand(
        0, "Genju of the Cedars", target_player_index=0,
        target_permanent_ids=[forest.permanent_id],
    )
    assert result.supported, result.details


def test_w1g4_genju_of_the_cedars_animates_its_forest_until_end_of_turn(set_pool):
    """{2}: the Forest becomes a 4/4 green Spirit creature that is still a
    Forest land, fights, and is a land again after cleanup."""
    game, forest, _aura = _w1g4_genju_on(
        set_pool, "Genju of the Cedars", "Forest", theirs=["Grizzly Bears"],
    )
    assert not forest.is_creature
    _w1g4_animate(game, "Genju of the Cedars")
    assert forest.is_creature
    assert (forest.effective_power, forest.effective_toughness) == (4, 4)
    for word in ("spirit", "land", "forest"):
        assert forest.has_type(word), word
    from engine.handlers._filters import permanent_effective_colors

    assert permanent_effective_colors(forest) == {"G"}
    from tests.helpers import declare_attack, drive_combat

    declare_attack(game, 0, blocks={0: 0})
    drive_combat(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"], game.log
    assert game.is_on_battlefield(forest)
    _w1g4_end_turn(game)
    assert not forest.is_creature
    assert forest.has_type("land") and not forest.has_type("spirit")


def test_w1g4_genju_reactivated_resets_its_size_but_keeps_a_pump(set_pool):
    """The 2009-10-01 ruling: activating it again "will override any effects
    that set its power and/or toughness to a specific number. However, any
    effect that raises or lowers power and/or toughness (such as … Giant
    Growth …) will continue to apply." 4/4, Giant Growth 7/7, again 7/7."""
    game, forest, _aura = _w1g4_genju_on(
        set_pool, "Genju of the Cedars", "Forest", hand=["Giant Growth"],
    )
    _w1g4_animate(game, "Genju of the Cedars")
    growth = game.cast_from_hand(
        0, "Giant Growth", target_player_index=0,
        target_permanent_ids=[forest.permanent_id],
    )
    assert growth.supported, growth.details
    _w1g4_settle(game)
    assert (forest.effective_power, forest.effective_toughness) == (7, 7)
    _w1g4_animate(game, "Genju of the Cedars")
    assert (forest.effective_power, forest.effective_toughness) == (7, 7), game.log


def test_w1g4_genju_animation_outlives_the_aura_destroyed_in_response(set_pool):
    """The ability exists apart from its source (CR 113.7a): the Genju
    destroyed with its activation on the stack still animates the Forest it
    last enchanted (CR 608.2h)."""
    game, forest, aura = _w1g4_genju_on(
        set_pool, "Genju of the Cedars", "Forest", hand=["Disenchant"],
    )
    result = game.queue_permanent_ability(0, "Genju of the Cedars")
    assert result.supported, result.details
    assert game.stack
    disenchant = game.cast_from_hand(
        0, "Disenchant", target_player_index=0, target_permanent_ids=[aura.permanent_id],
    )
    assert disenchant.supported, disenchant.details
    _w1g4_settle(game)
    assert not game.is_on_battlefield(aura)
    assert forest.is_creature and forest.effective_power == 4, game.log


def test_w1g4_an_animated_land_played_this_turn_cannot_attack(set_pool):
    """The 2008-08-01 ruling: a noncreature permanent turned into a creature
    can attack only if its controller has controlled it continuously since
    the start of their most recent turn (CR 302.6)."""
    game, forest, _aura = _w1g4_genju_on(set_pool, "Genju of the Cedars", "Forest")
    forest.metadata["summoning_sickness_turn"] = game.turn
    _w1g4_animate(game, "Genju of the Cedars")
    assert forest.is_creature
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [game.battlefield_index_of(forest)], defending_player_index=1,
    )
    assert not ok


@_w1g4_pytest.mark.parametrize("decline", [False, True])
def test_w1g4_genju_returns_to_hand_when_its_forest_is_destroyed(set_pool, decline):
    """Stone Rain on the enchanted Forest: the Genju looks back at the land's
    departure (CR 603.10a), CR 704.5m puts it in the graveyard, and its
    ability — functioning on the battlefield, CR 113.6m's Aura exception —
    returns it from there. A person at the seat is asked, and may decline."""
    game, forest, _aura = _w1g4_genju_on(
        set_pool, "Genju of the Cedars", "Forest", hand=["Stone Rain"],
        interactive=(0,),
    )
    rain = game.cast_from_hand(
        0, "Stone Rain", target_player_index=0, target_permanent_ids=[forest.permanent_id],
    )
    assert rain.supported, rain.details
    asked = []

    def may(game, choice):
        asked.append(choice.kind)
        game.confirm_optional_pay(choice.player_index, accept=not decline)

    _w1g4_settle(game, answers={"optional_pay": may}, defaults=False)
    assert asked == ["optional_pay"], game.log
    hand = _w1g4_names(game.players[0].hand)
    graveyard = _w1g4_names(game.players[0].graveyard)
    if decline:
        assert hand == [] and "Genju of the Cedars" in graveyard
    else:
        assert hand == ["Genju of the Cedars"], game.log
        assert "Genju of the Cedars" not in graveyard


def test_w1g4_genju_destroyed_first_does_not_return_later(set_pool):
    """The Genju destroyed on its own goes to the graveyard and stays: when
    the Forest dies later, nothing is attached to it to see it go."""
    game, forest, aura = _w1g4_genju_on(
        set_pool, "Genju of the Cedars", "Forest", hand=["Disenchant", "Stone Rain"],
    )
    for spell, victim in (("Disenchant", aura), ("Stone Rain", forest)):
        result = game.cast_from_hand(
            0, spell, target_player_index=0, target_permanent_ids=[victim.permanent_id],
        )
        assert result.supported, result.details
        _w1g4_settle(game)
    assert "Genju of the Cedars" in _w1g4_names(game.players[0].graveyard)
    assert _w1g4_names(game.players[0].hand) == []


def test_w1g4_genju_returns_when_its_animated_land_dies_in_combat(set_pool):
    """Genju of the Spires' 6/1 Mountain blocked by a Bear dies in combat: the
    Mountain is put into the graveyard and the Genju comes back to hand."""
    game, mountain, _aura = _w1g4_genju_on(
        set_pool, "Genju of the Spires", "Mountain", theirs=["Grizzly Bears"],
    )
    _w1g4_animate(game, "Genju of the Spires")
    assert (mountain.effective_power, mountain.effective_toughness) == (6, 1)
    from tests.helpers import declare_attack, drive_combat

    declare_attack(game, 0, blocks={0: 0})
    drive_combat(game)
    assert not game.is_on_battlefield(mountain)
    assert "Mountain" in _w1g4_names(game.players[0].graveyard)
    assert _w1g4_names(game.players[0].hand) == ["Genju of the Spires"], game.log


def test_w1g4_genju_of_the_realm_makes_a_legendary_trampler(set_pool):
    """"…becomes a legendary 8/12 Spirit creature with trample": CR 205.4a's
    supertype on the animation's layer-4 record, gone with it at cleanup."""
    game, land, _aura = _w1g4_genju_on(set_pool, "Genju of the Realm", "Plains")
    _w1g4_animate(game, "Genju of the Realm")
    assert (land.effective_power, land.effective_toughness) == (8, 12)
    assert land.has_supertype("legendary")
    assert game._has_keyword(land, "trample")
    assert land.has_type("spirit") and land.has_type("plains")
    _w1g4_end_turn(game)
    assert not land.has_supertype("legendary") and not land.is_creature


def test_w1g4_genju_of_the_falls_flies(set_pool):
    game, island, _aura = _w1g4_genju_on(set_pool, "Genju of the Falls", "Island")
    _w1g4_animate(game, "Genju of the Falls")
    assert (island.effective_power, island.effective_toughness) == (3, 2)
    assert game._has_keyword(island, "flying")
    from engine.handlers._filters import permanent_effective_colors

    assert permanent_effective_colors(island) == {"U"}


def test_w1g4_genju_of_the_fens_grants_its_quoted_pump(set_pool):
    """"…a 2/2 black Spirit creature with "{B}: This creature gets +1/+1
    until end of turn."": the Swamp's own ability, activated by its
    controller, and gone with the body at cleanup."""
    game, swamp, _aura = _w1g4_genju_on(set_pool, "Genju of the Fens", "Swamp")
    _w1g4_animate(game, "Genju of the Fens")
    assert (swamp.effective_power, swamp.effective_toughness) == (2, 2)
    pumped = game.activate_permanent_ability(
        0, "Swamp", permanent_index=game.battlefield_index_of(swamp),
        ability_index=len(_w1g4_compile(swamp.effective_card).activated_abilities) - 1,
    )
    assert pumped.supported, pumped.details
    _w1g4_settle(game)
    assert (swamp.effective_power, swamp.effective_toughness) == (3, 3), game.log
    _w1g4_end_turn(game)
    assert not swamp.is_creature
    assert all(
        "this creature gets +1/+1" not in ability.source_line.lower()
        for ability in _w1g4_compile(swamp.effective_card).activated_abilities
    )


def test_w1g4_genju_of_the_fields_gains_life_once_per_activation(set_pool):
    """The 2005-08-01 ruling: "When activated multiple times, it will have the
    triggered ability multiple times … you'll gain six life" for three. Two
    activations, 2 combat damage, 4 life."""
    game, plains, _aura = _w1g4_genju_on(set_pool, "Genju of the Fields", "Plains")
    _w1g4_animate(game, "Genju of the Fields")
    _w1g4_animate(game, "Genju of the Fields")
    assert (plains.effective_power, plains.effective_toughness) == (2, 5)
    from tests.helpers import declare_attack, drive_combat

    declare_attack(game, 0)
    drive_combat(game)
    assert game.players[1].life == 18, game.log
    assert game.players[0].life == 24, game.log


# --- Supported on arrival, driven -------------------------------------------

def test_w1g4_blessing_of_leeches_regenerates_and_bleeds_its_controller(set_pool):
    """{0}: the enchanted Bears survives a Bolt, tapped (CR 701.19); its
    controller loses 1 life at their own upkeep and not at the opponent's."""
    game, mine, _theirs = _w1g4_table(
        set_pool, ["Blessing of Leeches", "Lightning Bolt"], mine=["Grizzly Bears"],
    )
    bears = mine[0]
    result = game.cast_from_hand(
        0, "Blessing of Leeches", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    assert game.activate_permanent_ability(0, "Blessing of Leeches").supported
    _w1g4_settle(game)
    bolt = game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert bolt.supported, bolt.details
    _w1g4_settle(game)
    assert game.is_on_battlefield(bears) and bears.tapped, game.log
    _w1g4_end_turn(game, 0)
    game.start_turn(1)
    _w1g4_settle(game)
    assert game.players[0].life == 20
    _w1g4_end_turn(game, 1)
    game.start_turn(0)
    _w1g4_settle(game)
    assert game.players[0].life == 19, game.log


@_w1g4_pytest.mark.parametrize("demon", [False, True])
def test_w1g4_mark_of_the_oni_leaves_at_end_step_without_a_demon(set_pool, demon):
    """"At the beginning of the end step, if you control no Demons, sacrifice
    this Aura": without one the stolen Bears goes home; a Lord of the Pit
    keeps it."""
    game, _mine, theirs = _w1g4_table(
        set_pool, ["Mark of the Oni"], mine=["Lord of the Pit"] if demon else [],
        theirs=["Grizzly Bears"],
    )
    bears = theirs[0]
    result = game.cast_from_hand(
        0, "Mark of the Oni", target_player_index=1, target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    assert game.controller_index_of(bears) == 0
    game.resolve_end_step(0)
    _w1g4_settle(game)
    assert game.controller_index_of(bears) == (0 if demon else 1), game.log
    assert ("Mark of the Oni" in _w1g4_names(game.players[0].graveyard)) is not demon

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# Damage redirection from an Aura's host (CR 614.9, 303.4e).

import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle

_W1G5_SEATS = [
    _w1g5_pytest.param(set(), id="nobody-asked"),
    _w1g5_pytest.param({0, 1}, id="interactive"),
]


def _w1g5_table(set_pool, interactive=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G5Game(players=[
        _W1G5PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g5_settle(game)
    return game


def _w1g5_put(game, card, seat=0):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
@_w1g5_pytest.mark.parametrize("aim", ["creature", "player"])
def test_w1g5_ward_of_piety_moves_the_next_point_off_its_host(
    set_pool, interactive, aim,
):
    """"Enchant creature / {1}{W}: The next 1 damage that would be dealt to
    enchanted creature this turn is dealt to any target instead." Ward of
    Piety's controller activates it (CR 303.4e) at the opposing Craw Wurm
    or at the opponent; a Lightning Bolt at the enchanted Grizzly Bears
    deals 1 there and 2 to the Bears, which die (CR 615.7's pool read with
    CR 614.9's verb). A Bolt at the Wurm itself is not the Ward's
    business."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(
        set_pool, interactive, hand=[bok["Ward of Piety"]],
        opponent_hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
    )
    bears = _w1g5_put(game, lea["Grizzly Bears"])
    giant = _w1g5_put(game, lea["Craw Wurm"], seat=1)
    assert game.cast_from_hand(
        0, "Ward of Piety", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_settle(game)
    ward = next(p for p in game.players[0].battlefield if p.card.name == "Ward of Piety")
    announce = (
        {"target_permanent_ids": [giant.permanent_id]} if aim == "creature"
        else {"target_player_index": 1}
    )
    result = game.activate_permanent_ability(
        0, ward.card.name, permanent_index=game.battlefield_index_of(ward),
        **announce,
    )
    assert result.supported, (result.details, game.log[-4:])
    _w1g5_settle(game)
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_settle(game)
    assert giant.damage_marked == 3 and bears.damage_marked == 0, game.log
    giant.damage_marked = 0
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_settle(game)
    if aim == "creature":
        assert giant.damage_marked == 1 and game.players[1].life == 20, game.log
    else:
        assert giant.damage_marked == 0 and game.players[1].life == 19, game.log
    assert not game.is_on_battlefield(bears), game.log
    assert any("is dealt to" in line and "(Ward of Piety)" in line
               for line in game.log), game.log


def test_w1g5_heart_of_light_stops_damage_to_and_by_its_host(set_pool):
    """"Prevent all damage that would be dealt to and dealt by enchanted
    creature." (Supported on arrival; driven here.) A Bolt at the enchanted
    Hill Giant marks nothing, and blocked by the Bears neither deals the
    other any damage."""
    from tests.helpers import declare_attack, drive_combat

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(
        set_pool, hand=[bok["Heart of Light"]], opponent_hand=[lea["Lightning Bolt"]],
    )
    giant = _w1g5_put(game, lea["Hill Giant"])
    bears = _w1g5_put(game, lea["Grizzly Bears"], seat=1)
    assert game.cast_from_hand(
        0, "Heart of Light", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_settle(game)
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_settle(game)
    assert giant.damage_marked == 0, game.log
    declare_attack(game, 0, blocks={0: 0})
    drive_combat(game)
    assert giant.damage_marked == 0 and bears.damage_marked == 0, game.log
    assert game.is_on_battlefield(bears) and game.is_on_battlefield(giant)

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.aura_attachment import attach_aura as _w1g8_attach_aura
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (declare_attack as _w1g8_declare_attack,
                           drive_combat as _w1g8_drive_combat,
                           stock_libraries as _w1g8_stock_libraries)


def test_w1g8_mark_of_sakiko_grants_its_host_the_kept_mana_trigger(set_pool):
    """'Enchanted creature has "Whenever this creature deals combat damage to
    a player, add that much {G}. Until end of turn, you don't lose this mana
    as steps and phases end."' The host deals 3 and its controller adds
    {G}{G}{G} that stays into the postcombat main phase; the unenchanted
    attacker beside it adds nothing, and the Aura gone takes the ability."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    giant = _w1g8_Permanent(card=lea["Hill Giant"])
    bears = _w1g8_Permanent(card=lea["Grizzly Bears"])
    mark = _w1g8_Permanent(card=bok["Mark of Sakiko"])
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P0", battlefield=[giant, bears, mark]),
        _w1g8_PlayerState(name="P1"),
    ])
    _w1g8_stock_libraries(game)
    game._sync_control()
    _w1g8_attach_aura(mark, giant)
    game.active_player_index = 0
    _w1g8_declare_attack(game, 0)
    _w1g8_drive_combat(game)
    assert game.players[1].life == 15
    assert game.players[0].restricted_mana["kept_until_end_of_turn"] == {"G": 3}
    assert "Hill Giant produced {G}{G}{G} (kept until end of turn)" in game.log
    assert not any("Grizzly Bears produced" in line for line in game.log)
    assert game.current_step == "postcombat_main"
    assert "deals combat damage" not in (bears.effective_card.oracle_text or "")

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
