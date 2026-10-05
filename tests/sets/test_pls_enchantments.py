"""Planeshift enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: lands and mana ---
import pytest as _w1g5_pytest

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.ai_simulator import run_ai_simulation as _w1g5_run_ai_simulation
from engine.card_loader import manifest_set_path as _w1g5_manifest_set_path
from engine.land_animation import land_animation_for as _w1g5_land_animation_for
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import _mk_card as _w1g5_mk_card


def _w1g5_emergence_table(set_pool, *, mine=(), theirs=(), interactive=()):
    """Seat 0's main phase with *mine*/*theirs* already on the battlefield and
    Natural Emergence in seat 0's hand. Names resolve in Planeshift, then
    Alpha. Costs are off: what the enchantment does is the question."""
    pls, lea = set_pool("PLS"), set_pool("LEA")

    def card(name):
        return pls[name] if name in pls else lea[name]

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(name)) for name in mine],
        hand=[pls["Natural Emergence"]],
    )
    you = _W1G5PlayerState(
        name="W1G5-B",
        battlefield=[_W1G5Permanent(card=card(name)) for name in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game  # _w1g5_emergence_table


def _w1g5_emergence_resolved(set_pool, returning: str, **board):
    """Cast Natural Emergence for an interactive seat 0 and return the
    enchantment named *returning* to its owner's hand; the game."""
    game = _w1g5_emergence_table(set_pool, interactive={0}, **board)
    assert game.cast_from_hand(0, "Natural Emergence").supported
    game.resolve_top_of_stack()
    (chosen,) = [p for p in game.controlled_by(0) if p.card.name == returning]
    assert game.confirm_permanent_set_choice(0, [chosen.permanent_id])
    assert not game.pending_choices
    return game  # _w1g5_emergence_resolved


def _w1g5_shape(game, seat: int) -> dict[str, tuple]:
    """Each of *seat*'s permanents as ``(is a creature, power, toughness,
    has first strike, is a land)``, by name."""
    return {
        p.card.name: (
            p.is_creature, p.effective_power, p.effective_toughness,
            game._has_keyword(p, "first strike"), p.has_type("land"),
        )
        for p in game.controlled_by(seat)
    }  # _w1g5_shape


def test_w1g5_natural_emergence_returns_a_red_or_green_enchantment(set_pool):
    """"When this enchantment enters, return a red or green enchantment you
    control to its owner's hand." The seat is asked, and the choices are its
    own red or green enchantments — Natural Emergence itself among them (it is
    both), a blue one and an opponent's green one not. Returning Fastbond
    leaves the Emergence in play; nothing is returned without an answer."""
    game = _w1g5_emergence_table(
        set_pool, mine=["Fastbond", "Flight"], theirs=["Fastbond"], interactive={0},
    )
    assert game.cast_from_hand(0, "Natural Emergence").supported
    game.resolve_top_of_stack()

    pick = game.pending_choice_of("permanent_set_choice", 0)
    assert pick is not None
    assert sorted(p.card.name for p in game.live_permanent_set_choices(pick)) == [
        "Fastbond", "Natural Emergence",
    ]
    (flight,) = [p for p in game.controlled_by(0) if p.card.name == "Flight"]
    (theirs,) = list(game.controlled_by(1))
    assert not game.confirm_permanent_set_choice(0, [flight.permanent_id])
    assert not game.confirm_permanent_set_choice(0, [theirs.permanent_id])
    assert not game.confirm_permanent_set_choice(0, [])
    (fastbond,) = [p for p in game.controlled_by(0) if p.card.name == "Fastbond"]
    assert game.confirm_permanent_set_choice(0, [fastbond.permanent_id])

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Flight", "Natural Emergence",
    ]
    assert [card.name for card in game.players[0].hand] == ["Fastbond"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Fastbond"]


def test_w1g5_natural_emergence_may_return_itself(set_pool):
    """With no other red or green enchantment it is its own only choice: it
    goes back to hand, and the lands it would have animated are plain lands."""
    game = _w1g5_emergence_table(set_pool, mine=["Forest"], interactive={0})
    game.cast_from_hand(0, "Natural Emergence")
    game.resolve_top_of_stack()
    (emergence,) = [p for p in game.controlled_by(0) if p.card.name == "Natural Emergence"]
    assert _w1g5_shape(game, 0)["Forest"][:2] == (True, 2), "animated while it is in play"
    assert game.confirm_permanent_set_choice(0, [emergence.permanent_id])

    assert [card.name for card in game.players[0].hand] == ["Natural Emergence"]
    assert _w1g5_shape(game, 0) == {"Forest": (False, 0, 0, False, True)}


def test_w1g5_natural_emergence_animates_your_lands_and_only_yours(set_pool):
    """"Lands you control are 2/2 creatures with first strike. They're still
    lands." Three things the animation table could not say before: whose
    lands (an opponent's Island is untouched), a keyword (first strike, layer
    6), and the two-sentence spelling. A land that enters later is animated
    too (CR 611.3a — a static ability is not locked in), a non-land is not,
    and everything reverts when the enchantment leaves (CR 611.3b)."""
    game = _w1g5_emergence_resolved(
        set_pool, "Fastbond",
        mine=["Forest", "Mountain", "Fastbond", "Sol Ring"], theirs=["Island"],
    )
    mine = _w1g5_shape(game, 0)
    assert mine["Forest"] == mine["Mountain"] == (True, 2, 2, True, True)
    assert mine["Sol Ring"] == mine["Natural Emergence"] == (False, 0, 0, False, False)
    assert _w1g5_shape(game, 1) == {"Island": (False, 0, 0, False, True)}

    game._put_permanent_onto_battlefield(
        0, _W1G5Permanent(card=set_pool("LEA")["Swamp"]), None
    )
    assert _w1g5_shape(game, 0)["Swamp"] == (True, 2, 2, True, True)

    (emergence,) = [p for p in game.controlled_by(0) if p.card.name == "Natural Emergence"]
    game.remove_from_battlefield(emergence)
    game._recompute_continuous_effects()
    assert set(_w1g5_shape(game, 0).values()) == {
        (False, 0, 0, False, True), (False, 0, 0, False, False),
    }


def test_w1g5_natural_emergence_follows_its_controller(set_pool):
    """"You control" is the controller of the *source*, through the control
    seam on both sides (CR 109.5): when an opponent takes the enchantment, the
    lands it animates are theirs and the first player's go back to being
    lands."""
    from engine.control import change_control

    game = _w1g5_emergence_resolved(
        set_pool, "Fastbond", mine=["Forest", "Fastbond"], theirs=["Island"],
    )
    (emergence,) = [p for p in game.controlled_by(0) if p.card.name == "Natural Emergence"]
    change_control(emergence, 1, source="w1g5-test")
    game._sync_control()
    game._recompute_continuous_effects()

    assert _w1g5_shape(game, 0) == {"Forest": (False, 0, 0, False, True)}
    assert _w1g5_shape(game, 1)["Island"] == (True, 2, 2, True, True)


def test_w1g5_an_animated_land_strikes_first(set_pool):
    """The keyword is real in combat: an animated Forest, 2/2 with first
    strike, attacks into a Grizzly Bears. The Bears die in the first-strike
    damage step and deal nothing back (CR 510.4), and the Forest is still a
    land that taps for {G} afterwards."""
    game = _w1g5_emergence_resolved(
        set_pool, "Fastbond", mine=["Forest", "Fastbond"], theirs=["Grizzly Bears"],
    )
    (forest,) = [p for p in game.controlled_by(0) if p.card.name == "Forest"]
    (bears,) = list(game.controlled_by(1))

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [game.battlefield_index_of(forest)], defending_player_index=1
    )[0]
    game.advance_combat_phase()
    game.declare_blockers(
        1, {game.battlefield_index_of(bears): game.battlefield_index_of(forest)}
    )
    game.advance_combat_phase()

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert forest in list(game.controlled_by(0))
    assert forest.damage_marked == 0, "the Bears never dealt their damage"


def test_w1g5_the_animation_table_reads_every_printed_word(set_pool):
    """The derivation table is anchored at both ends and each optional word is
    a field: the controller, the keyword list, either spelling of the "still
    lands" clause. A keyword the engine does not implement, or a tail the
    template does not print, refuses the line rather than animating the lands
    and dropping a word — and the four animators that shipped before
    Planeshift read exactly as they did."""
    emergence = _w1g5_land_animation_for(
        "lands you control are 2/2 creatures with first strike. they're still lands"
    )
    assert (emergence.controller, emergence.keywords) == ("you", ("first strike",))
    assert (emergence.land_type, emergence.power, emergence.toughness) == (None, 2, 2)

    typed = _w1g5_land_animation_for(
        "forests you control are 1/1 creatures with flying and trample that are still lands"
    )
    assert (typed.land_type, typed.controller) == ("forest", "you")
    assert typed.keywords == ("flying", "trample")

    plain = _w1g5_land_animation_for("all lands are 2/2 creatures that are still lands")
    assert (plain.controller, plain.keywords) == (None, ())

    for refused in (
        "lands you control are 2/2 creatures with gravestorm. they're still lands",
        "lands you control are 2/2 creatures with first strike",
        "lands you control are 2/2 creatures with first strike. they're still lands. draw a card",
        "lands an opponent controls are 2/2 creatures that are still lands",
    ):
        assert _w1g5_land_animation_for(refused) is None, refused

    invented = _w1g5_mk_card(
        name="Verdant Uprising", type_line="Enchantment",
        oracle_text="Forests you control are 1/1 creatures with trample that are still lands.",
    )
    (instruction,) = _w1g5_compile(invented).instructions
    assert instruction.kind == "animate_all_lands"
    assert instruction.payload == {
        "power": 1, "toughness": 1, "land_type": "forest",
        "controller": "you", "keywords": ["trample"],
    }
    game = _w1g5_emergence_table(set_pool, mine=["Forest", "Mountain"], theirs=["Forest"])
    game._put_permanent_onto_battlefield(0, _W1G5Permanent(card=invented), None)
    assert _w1g5_shape(game, 0)["Forest"][:3] == (True, 1, 1)
    assert game._has_keyword(
        next(p for p in game.controlled_by(0) if p.card.name == "Forest"), "trample"
    )
    assert _w1g5_shape(game, 0)["Mountain"][0] is False
    assert _w1g5_shape(game, 1)["Forest"][0] is False


def test_w1g5_multanis_harmony_gives_its_creature_a_mana_ability(set_pool):
    """'Enchanted creature has "{T}: Add one mana of any color."' Supported on
    arrival and never run. The creature — not the Aura — taps for the colour
    named, as a mana ability (no stack), and the ability is gone with the
    Aura (CR 611.3b)."""
    from engine.targeting import usable_activated_abilities

    pls, lea = set_pool("PLS"), set_pool("LEA")
    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=lea["Grizzly Bears"])],
        hand=[pls["Multani's Harmony"]],
    )
    game = _W1G5Game(players=[me, _W1G5PlayerState(name="W1G5-B")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    (bears,) = list(game.controlled_by(0))
    bears.metadata["summoning_sickness_turn"] = -99

    def granted():
        return [
            ability.source_line.lower() for ability in usable_activated_abilities(
                _w1g5_compile(game.playable_card_of(bears))
            )
        ]

    assert granted() == []
    assert game.cast_from_hand(
        0, "Multani's Harmony", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert granted() == ["{t}: add one mana of any color."]

    result = game.activate_permanent_ability(
        0, "Grizzly Bears",
        permanent_index=game.battlefield_index_of(bears), mana_color="U",
    )
    assert result.supported and bears.tapped and not game.stack
    assert {s: n for s, n in me.mana_pool.items() if n} == {"U": 1}

    (harmony,) = [p for p in game.controlled_by(0) if p.card.name == "Multani's Harmony"]
    game._remove_aura_effects(harmony)
    game.remove_from_battlefield(harmony)
    game._recompute_continuous_effects()
    assert granted() == []


@_w1g5_pytest.mark.slow
def test_w1g5_emergence_blessing_and_compass_in_simulated_games(set_pool):
    """Whole games with this group's three spells pinned into both decks —
    Natural Emergence, Skyshroud Blessing (an instant) and Star Compass (an
    artifact) — because a card can compile and do nothing in a turn structure.
    Each is cast and resolves, the Emergence's entry trigger is answered in
    the step that owes it (`steps_left_owing`), the Blessing's lands gain
    shroud, and nothing any of the three does is an issue or a refused cast.

    The floors are one apiece on purpose: the seed's trajectory moves whenever
    another card in the set changes, and this asks that the cards were *seen*,
    not how often. (Today: fifteen, four and seven casts.)
    """
    names = ["Natural Emergence", "Skyshroud Blessing", "Star Compass"]
    report = _w1g5_run_ai_simulation(
        _w1g5_manifest_set_path("PLS", include_measured=True),
        games=6, seed=11, max_turns=20, required_cards=names,
    )
    log = report.log_lines

    assert report.games_completed == 6
    assert report.steps_left_owing == {}, dict(report.steps_left_owing)
    for name in names:
        assert sum(f"cast {name} -> resolved" in line for line in log) >= 1, name
        assert not [i.message for i in report.issues if name in i.message], name
        assert not [why for why in report.refused_casts if name in why], name
    assert sum("Natural Emergence returned" in line for line in log) >= 1
    assert sum("gain shroud until end of turn" in line for line in log) >= 1
