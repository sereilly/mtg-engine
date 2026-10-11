"""Apocalypse creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.grammar import compile_line as _w1g7_compile_line
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_creature_duel(*, interactive=(0,)):
    """A two-seat game with costs off. Seat 0 is interactive by default, so a
    prompt one of these cards arms is *queued* rather than answered by its own
    default."""
    p0, p1 = _W1G7PlayerState(name="A"), _W1G7PlayerState(name="B")
    game = _W1G7Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p0, p1


def _w1g7_creature_put(game, seat, card):
    """Put *card* onto *seat*'s battlefield, ready to act this turn."""
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    return permanent


def _w1g7_activation_targets(game, seat, permanent, ability_index=None):
    """What the activation picker offers for *permanent*'s ability, as
    ``(kind, [names])`` — the engine's own list, which is also the gate."""
    slot = next(
        index for index, held in enumerate(game.players[seat].battlefield)
        if held is permanent
    )
    spec = game.activation_target_spec(seat, slot, ability_index)
    return spec["kind"], [entry["name"] for entry in spec["valid_targets"]]


def _w1g7_prompt(game, seat, key):
    """The payload a human at *seat* is shown for prompt *key*, through the web
    layer's own renderer."""
    from web.prompts import PromptContext, render_prompts

    context = PromptContext(
        game=game, viewer_seat=seat,
        serialize_card=lambda card: {"name": getattr(card, "name", str(card))},
        seat_type=lambda index: "human" if index in game.interactive_seats else "ai",
    )
    return render_prompts(context)[key]


# -- Vodalian Mystic ---------------------------------------------------------


def test_vodalian_mystic_can_only_be_aimed_at_an_instant_or_sorcery_spell(
    set_pool, catalog_by_name
):
    """"{T}: Target **instant or sorcery** spell becomes the color of your
    choice." The picker is the announcement gate: nothing on the stack, or only
    a creature spell, is nothing to name — and the Mystic stays untapped."""
    game, p0, p1 = _w1g7_creature_duel()
    mystic = _w1g7_creature_put(game, 0, set_pool("APC")["Vodalian Mystic"])
    p1.hand = [catalog_by_name["Grizzly Bears"], catalog_by_name["Lightning Bolt"]]

    assert _w1g7_activation_targets(game, 0, mystic) == ("stack", [])
    assert not game.queue_permanent_ability(0, "Vodalian Mystic").supported

    game.queue_from_hand(1, "Grizzly Bears")
    assert _w1g7_activation_targets(game, 0, mystic) == ("stack", [])
    refused = game.queue_permanent_ability(0, "Vodalian Mystic", target_stack_index=0)
    assert not refused.supported
    assert mystic.tapped is False

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert _w1g7_activation_targets(game, 0, mystic) == ("stack", ["Lightning Bolt"])


def test_vodalian_mystic_asks_for_the_color_as_it_resolves(set_pool, catalog_by_name):
    """CR 608.2d: "the color of your choice" is named while the effect is
    applied, not announced with the activation. The Bolt is still red while the
    question stands, an answer that is not a colour is refused, and the spell
    is the chosen colour — and no other (CR 105.3) — once it is given."""
    game, p0, p1 = _w1g7_creature_duel()
    mystic = _w1g7_creature_put(game, 0, set_pool("APC")["Vodalian Mystic"])
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    bolt = game.stack[-1]

    assert game.queue_permanent_ability(0, "Vodalian Mystic", target_stack_index=0).supported
    assert mystic.tapped is True
    game.resolve_top_of_stack(pause_for_choices=True)

    asked = _w1g7_prompt(game, 0, "color_choice")
    assert asked is not None and asked["card_name"] == "Vodalian Mystic"
    assert game._stack_item_colors(bolt) == ("R",)
    assert game.resolve_pending_choice("color_choice", 0, mana_color="purple") is False
    assert game.resolve_pending_choice("color_choice", 0, mana_color="U") is True

    assert game._stack_item_colors(bolt) == ("U",)
    assert "Lightning Bolt (on the stack) became U (Vodalian Mystic)" in game.log
    # Only the colour changed: the Bolt still resolves as printed.
    _w1g7_resolve_stack(game)
    assert p0.life == 17


def test_a_spell_vodalian_mystic_recolored_is_that_color_to_every_reader(
    set_pool, catalog_by_name
):
    """One colour record for a spell (``_stack_item_colors``): the blue Bolt is
    a legal target for "counter target blue spell" and no longer one for
    "counter target red spell"."""
    game, p0, p1 = _w1g7_creature_duel()
    _w1g7_creature_put(game, 0, set_pool("APC")["Vodalian Mystic"])
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    red_blast = catalog_by_name["Red Elemental Blast"]
    blue_blast = catalog_by_name["Blue Elemental Blast"]

    def offered(card):
        spec = game.cast_target_spec(0, card, mode_index=0)
        return [entry["name"] for entry in spec["valid_targets"]]

    assert offered(blue_blast) == ["Lightning Bolt"] and offered(red_blast) == []

    game.queue_permanent_ability(0, "Vodalian Mystic", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    game.resolve_pending_choice("color_choice", 0, mana_color="U")

    assert offered(red_blast) == ["Lightning Bolt"] and offered(blue_blast) == []


def test_vodalian_mystic_recolors_nothing_when_its_spell_has_left(
    set_pool, catalog_by_name
):
    """CR 608.2b: the target is gone, so the ability does nothing — it does not
    reach for another spell or for a permanent."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    _w1g7_creature_put(game, 0, set_pool("APC")["Vodalian Mystic"])
    bears = _w1g7_creature_put(game, 1, catalog_by_name["Grizzly Bears"])
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    bolt = game.stack[-1]

    game.queue_permanent_ability(0, "Vodalian Mystic", target_stack_index=0)
    game.counter_stack_object(bolt)
    _w1g7_resolve_stack(game)

    assert "color_override" not in bolt.choices
    assert game._effective_colors(bears) == {"G"}
    assert not any("became" in line for line in game.log)


def test_a_recolored_spell_phrase_carries_its_types_or_refuses():
    """The lowering: the printed card types reach the stack picker, and a
    narrowing nothing tests, a duration or a colour *set* refuses rather than
    recolouring more — or for longer — than the sentence says."""
    typed = _w1g7_compile_line("Target instant spell becomes colorless.")
    assert typed.usable
    assert typed.instructions[0].payload["targets"] == {
        "quantifier": "target", "kind": "spell", "card_types": ["instant"],
    }

    for line, reason in (
        ("Target blue spell becomes the color of your choice.", "colors"),
        ("Target spell becomes the color of your choice until end of turn.",
         "one chosen colour"),
        ("Target spell becomes the color or colors of your choice.",
         "one chosen colour"),
    ):
        refused = _w1g7_compile_line(line)
        assert refused.parsed and not refused.usable
        assert reason in refused.lowering_error


# -- Tundra Kavu -------------------------------------------------------------


def test_tundra_kavu_offers_plains_or_island_and_refuses_any_other_type(
    set_pool, catalog_by_name
):
    """"{T}: Target land becomes **a Plains or an Island** until end of turn."
    The choice is made as the ability resolves (CR 608.2d), among the two the
    card prints: the prompt offers exactly those and a third is refused with
    the land untouched — a restriction on a choice is enforced where the
    choice is made."""
    game, p0, p1 = _w1g7_creature_duel()
    kavu = _w1g7_creature_put(game, 0, set_pool("APC")["Tundra Kavu"])
    forest = _w1g7_creature_put(game, 1, catalog_by_name["Forest"])
    bears = _w1g7_creature_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w1g7_creature_put(game, 0, catalog_by_name["Swamp"])

    assert _w1g7_activation_targets(game, 0, kavu) == ("land", ["Swamp", "Forest"])
    assert not game.queue_permanent_ability(
        0, "Tundra Kavu", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert kavu.tapped is False

    assert game.queue_permanent_ability(
        0, "Tundra Kavu", target_permanent_ids=[forest.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_prompt(game, 0, "land_type_choice")["options"] == ["plains", "island"]
    assert "Tundra Kavu: choose Plains or Island for Forest" in game.log
    for unprinted in ("swamp", "mountain", "forest", "desert"):
        assert game.confirm_land_type(0, unprinted) is False
    assert forest.basic_land_types == ("forest",)

    assert game.confirm_land_type(0, "plains") is True
    # CR 305.7: the land is a Plains *instead of* a Forest, and taps for white.
    assert forest.basic_land_types == ("plains",)
    assert not forest.has_type("forest")
    assert game._land_payment_colors(forest) == ("W",)


def test_tundra_kavus_change_ends_in_the_cleanup_step(set_pool, catalog_by_name):
    game, p0, p1 = _w1g7_creature_duel()
    _w1g7_creature_put(game, 0, set_pool("APC")["Tundra Kavu"])
    forest = _w1g7_creature_put(game, 1, catalog_by_name["Forest"])
    game.queue_permanent_ability(0, "Tundra Kavu", target_permanent_ids=[forest.permanent_id])
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_land_type(0, "island")
    assert forest.basic_land_types == ("island",)

    game.resolve_cleanup_step(0)

    assert forest.basic_land_types == ("forest",)


def test_tundra_kavu_played_by_a_seat_nobody_asks_makes_an_island(
    set_pool, catalog_by_name
):
    """The stated default: an Island, which is one of the two printed types —
    the default has to be an answer the resolver accepts, or the ability would
    resolve having changed nothing."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    _w1g7_creature_put(game, 0, set_pool("APC")["Tundra Kavu"])
    forest = _w1g7_creature_put(game, 1, catalog_by_name["Forest"])

    assert game.activate_permanent_ability(
        0, "Tundra Kavu", target_permanent_ids=[forest.permanent_id]
    ).supported
    game.auto_resolve_pending_choices()

    assert forest.basic_land_types == ("island",)


def test_a_printed_choice_of_land_types_is_among_basic_land_types(set_pool):
    """The production reads the alternatives whole; the lowering admits them
    only where the prompt can carry them. "The basic land type of your choice"
    (Reef Shaman) prints no list and keeps the payload it had."""
    kavu = _w1g7_compile(set_pool("APC")["Tundra Kavu"])
    assert kavu.activated_abilities[0].instruction.payload["land_type_options"] == [
        "plains", "island",
    ]
    shaman = _w1g7_compile(set_pool("APC")["Reef Shaman"])
    assert "land_type_options" not in shaman.activated_abilities[0].instruction.payload

    three = _w1g7_compile_line(
        "Target land becomes a Plains or an Island or a Swamp until end of turn."
    )
    assert three.instructions[0].payload["land_type_options"] == [
        "plains", "island", "swamp",
    ]
    nonbasic = _w1g7_compile_line(
        "Target land becomes a Plains or a Desert until end of turn."
    )
    assert nonbasic.parsed and not nonbasic.usable
    not_a_land_type = _w1g7_compile_line(
        "Target land becomes a Plains or a Wall until end of turn."
    )
    assert not not_a_land_type.parsed


# -- Reef Shaman (driven) ----------------------------------------------------


def test_reef_shaman_makes_a_land_the_basic_land_type_its_controller_names(
    set_pool, catalog_by_name
):
    """"{T}: Target land becomes the basic land type of your choice until end
    of turn." All five are offered, the land is the named type *instead of* its
    own (CR 305.7) — an opponent's Forest made a Swamp taps for {B} whatever it
    is asked for — and the cleanup step gives the Forest back."""
    game, p0, p1 = _w1g7_creature_duel()
    shaman = _w1g7_creature_put(game, 0, set_pool("APC")["Reef Shaman"])
    forest = _w1g7_creature_put(game, 1, catalog_by_name["Forest"])
    bears = _w1g7_creature_put(game, 1, catalog_by_name["Grizzly Bears"])

    assert _w1g7_activation_targets(game, 0, shaman) == ("land", ["Forest"])
    assert not game.queue_permanent_ability(
        0, "Reef Shaman", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.queue_permanent_ability(
        0, "Reef Shaman", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert shaman.tapped is True
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_prompt(game, 0, "land_type_choice")["options"] == [
        "plains", "island", "swamp", "mountain", "forest",
    ]
    assert forest.basic_land_types == ("forest",)
    assert game.confirm_land_type(0, "swamp") is True
    assert forest.basic_land_types == ("swamp",)

    game.enforce_mana_costs = True
    assert game.tap_land_for_mana(1, "Forest", "G", permanent_id=forest.permanent_id)
    assert {s: n for s, n in p1.mana_pool.items() if n} == {"B": 1}

    game.resolve_cleanup_step(0)
    assert forest.basic_land_types == ("forest",)


# -- Kavu Glider (driven) ----------------------------------------------------


def test_kavu_gliders_two_abilities_cost_what_they_print_and_end_with_the_turn(
    set_pool, catalog_by_name
):
    """"{W}: This creature gets +0/+1 until end of turn." / "{U}: This creature
    gains flying until end of turn." With costs on: nothing happens for free,
    each ability spends its own colour, and both wear off at cleanup."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    game.enforce_mana_costs = True
    glider = _w1g7_creature_put(game, 0, set_pool("APC")["Kavu Glider"])
    plains = _w1g7_creature_put(game, 0, catalog_by_name["Plains"])
    island = _w1g7_creature_put(game, 0, catalog_by_name["Island"])

    refused = game.activate_permanent_ability(0, "Kavu Glider", ability_index=0)
    assert not refused.supported
    assert (glider.effective_power, glider.effective_toughness) == (2, 1)

    game.tap_land_for_mana(0, "Plains", "W", permanent_id=plains.permanent_id)
    assert game.activate_permanent_ability(0, "Kavu Glider", ability_index=0).supported
    assert (glider.effective_power, glider.effective_toughness) == (2, 2)
    assert not game._has_keyword(glider, "flying")

    game.tap_land_for_mana(0, "Island", "U", permanent_id=island.permanent_id)
    assert game.activate_permanent_ability(0, "Kavu Glider", ability_index=1).supported
    assert game._has_keyword(glider, "flying")
    assert not any(p0.mana_pool.values())

    game.resolve_cleanup_step(0)
    assert (glider.effective_power, glider.effective_toughness) == (2, 1)
    assert not game._has_keyword(glider, "flying")


# -- Urborg Elf / Llanowar Dead (driven) -------------------------------------


@_w1g7_pytest.mark.parametrize("colour", ["B", "G", "U"])
def test_urborg_elf_taps_for_each_of_its_three_colors(set_pool, colour):
    """"{T}: Add {B}, {G}, or {U}." One mana of the colour asked for, and the
    Elf is tapped — a second activation is refused."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    game.enforce_mana_costs = True
    elf = _w1g7_creature_put(game, 0, set_pool("APC")["Urborg Elf"])

    assert game.activate_permanent_ability(0, "Urborg Elf", mana_color=colour).supported

    assert {s: n for s, n in p0.mana_pool.items() if n} == {colour: 1}
    assert elf.tapped is True
    assert not game.activate_permanent_ability(0, "Urborg Elf", mana_color=colour).supported
    assert sum(p0.mana_pool.values()) == 1


def test_urborg_elf_never_makes_a_color_it_does_not_print(set_pool):
    """Asked for red, it makes one of its own three: the request is not a way
    to a fourth colour."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    _w1g7_creature_put(game, 0, set_pool("APC")["Urborg Elf"])

    assert game.activate_permanent_ability(0, "Urborg Elf", mana_color="R").supported

    made = {s for s, n in p0.mana_pool.items() if n}
    assert len(made) == 1 and made <= {"B", "G", "U"}
    assert sum(p0.mana_pool.values()) == 1


def test_llanowar_dead_taps_for_black_and_not_while_summoning_sick(set_pool):
    """"{T}: Add {B}." A creature's {T} ability waits for CR 302.6: the copy
    that came in this turn cannot be tapped for mana."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    game.enforce_mana_costs = True
    dead = _w1g7_creature_put(game, 0, set_pool("APC")["Llanowar Dead"])

    assert game.activate_permanent_ability(0, "Llanowar Dead", mana_color="G").supported
    assert {s: n for s, n in p0.mana_pool.items() if n} == {"B": 1}
    assert dead.tapped is True

    fresh = _w1g7_creature_put(game, 0, set_pool("APC")["Llanowar Dead"])
    fresh.metadata["summoning_sickness_turn"] = game.turn
    refused = game.activate_permanent_ability(
        0, "Llanowar Dead", permanent_index=len(p0.battlefield) - 1
    )
    assert not refused.supported and "summoning sickness" in refused.details
    assert fresh.tapped is False

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
