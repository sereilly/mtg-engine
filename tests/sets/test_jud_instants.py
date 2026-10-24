"""Judgment instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
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

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from engine.shields import shields_on as _w1g2_shields_on
from tests.helpers import (_nosick as _w1g2_nosick,
                           declare_attack as _w1g2_declare_attack,
                           resolve_stack as _w1g2_resolve_stack)


def _w1g2_table(set_pool, catalog_by_name, *, interactive=()):
    """Two seats with libraries, mana off, a card lookup over Judgment first
    and the shipped pool second."""
    jud = set_pool("JUD")

    def card(name):
        return jud[name] if name in jud else catalog_by_name[name]

    island = catalog_by_name["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="Alice", library=[island] * 10),
        _W1G2PlayerState(name="Bob", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g2_card = card
    return game


def _w1g2_put(game, seat, name):
    """*name* onto *seat*'s battlefield through the one entry path, awake."""
    permanent = _W1G2Permanent(card=game._w1g2_card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g2_resolve_stack(game)
    _w1g2_nosick(permanent)
    return permanent


def _w1g2_cast(game, seat, name, **announcement):
    """*seat* casts *name* out of its hand (added for the purpose)."""
    game.players[seat].hand.append(game._w1g2_card(name))
    result = game.cast_from_hand(seat, name, **announcement)
    assert result.supported, result.details
    return result


def _w1g2_bolt_player(game, caster_seat, victim_seat, name="Lightning Bolt"):
    _w1g2_cast(game, caster_seat, name, target_player_index=victim_seat)
    _w1g2_resolve_stack(game)


# --- Prismatic Strands ----------------------------------------------------


def test_w1g2_prismatic_strands_asks_its_colour_as_it_resolves_and_stops_that_colour(
    set_pool, catalog_by_name,
):
    """"Prevent all damage that sources of the color of your choice would deal
    this turn." The colour is chosen on resolution (CR 608.2d) by the caster;
    afterwards every red source's damage is prevented, to anyone — a red
    *spell* (Lightning Bolt is a source, CR 609.7a), a red creature in combat
    on either side — and a green creature's damage is not."""
    game = _w1g2_table(set_pool, catalog_by_name, interactive={0})
    _w1g2_cast(game, 0, "Prismatic Strands")
    assert not game.resolve_top_of_stack(), "the spell waits on its colour"
    choice = game.pending_choice_of("color_choice")
    assert choice is not None and choice.player_index == 0
    assert game.resolve_pending_choice("color_choice", 0, mana_color="R")
    _w1g2_resolve_stack(game)
    assert any(
        "all damage red sources would deal this turn is prevented" in line
        for line in game.log
    )

    _w1g2_bolt_player(game, 1, 0)
    _w1g2_bolt_player(game, 1, 1)
    assert (game.players[0].life, game.players[1].life) == (20, 20)

    ogre = _w1g2_put(game, 1, "Gray Ogre")
    bears = _w1g2_put(game, 1, "Grizzly Bears")
    _w1g2_declare_attack(game, 1)
    game.advance_combat_phase()
    game.resolve_all_combat_damage(1)
    assert game.players[0].life == 18, "the Bears' 2 lands; the Ogre's 2 does not"
    assert game.is_on_battlefield(ogre) and game.is_on_battlefield(bears)


def test_w1g2_prismatic_strands_in_response_names_the_threatening_colour(
    set_pool, catalog_by_name,
):
    """Cast in response to a burn spell by a seat nobody asks, the colour is
    the default the colour prompt takes — the colour of the opposing object on
    the stack the choice is answering — and the bolt under it fizzles into
    nothing."""
    game = _w1g2_table(set_pool, catalog_by_name)
    # A green permanent across the table: the board-wide fallback would name
    # green, so red can only come from the Bolt on the stack.
    _w1g2_put(game, 1, "Grizzly Bears")
    game.players[1].hand.append(game._w1g2_card("Lightning Bolt"))
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    game.players[0].hand.append(game._w1g2_card("Prismatic Strands"))
    assert game.queue_from_hand(0, "Prismatic Strands").supported
    _w1g2_resolve_stack(game)

    assert game.players[0].life == 20
    assert any("red sources" in line for line in game.log)


def test_w1g2_prismatic_strands_flashback_taps_an_untapped_white_creature(
    set_pool, catalog_by_name,
):
    """"Flashback—Tap an untapped white creature you control." The cost is the
    tap, not mana: cast from the graveyard, the White Knight is tapped, and the
    spell is exiled as it leaves the stack (CR 702.34a)."""
    game = _w1g2_table(set_pool, catalog_by_name)
    knight = _w1g2_put(game, 0, "White Knight")
    strands = game._w1g2_card("Prismatic Strands")
    game.players[0].graveyard.append(strands)
    result = game.cast_from_hand(0, "Prismatic Strands", from_zone="graveyard")
    assert result.supported, result.details
    _w1g2_resolve_stack(game)

    assert knight.tapped
    assert [c.name for c in game.players[0].exile] == ["Prismatic Strands"]
    assert game.players[0].graveyard == []


def test_w1g2_prismatic_strands_flashback_needs_a_white_creature_to_tap(
    set_pool, catalog_by_name,
):
    """With only a green creature, or only a tapped white one, the flashback
    cost cannot be paid and the cast is refused before anything moves
    (CR 601.2h)."""
    game = _w1g2_table(set_pool, catalog_by_name)
    _w1g2_put(game, 0, "Grizzly Bears")
    knight = _w1g2_put(game, 0, "White Knight")
    knight.tapped = True
    game.players[0].graveyard.append(game._w1g2_card("Prismatic Strands"))
    result = game.cast_from_hand(0, "Prismatic Strands", from_zone="graveyard")

    assert not result.supported
    assert [c.name for c in game.players[0].graveyard] == ["Prismatic Strands"]
    assert not game.stack


# --- Serene Sunset ----------------------------------------------------------


def test_w1g2_serene_sunset_silences_exactly_the_x_creatures_it_names(
    set_pool, catalog_by_name,
):
    """"Prevent all combat damage X target creatures would deal this turn."
    X = 2 against three attackers: the two named deal nothing, the third's 3
    lands."""
    game = _w1g2_table(set_pool, catalog_by_name)
    ogre = _w1g2_put(game, 1, "Gray Ogre")
    bears = _w1g2_put(game, 1, "Grizzly Bears")
    _w1g2_put(game, 1, "Hill Giant")
    _w1g2_declare_attack(game, 1)
    _w1g2_cast(
        game, 0, "Serene Sunset", x_value=2,
        target_permanent_ids=[ogre.permanent_id, bears.permanent_id],
    )
    _w1g2_resolve_stack(game)
    game.advance_combat_phase()
    game.resolve_all_combat_damage(1)

    assert game.players[0].life == 17


def test_w1g2_serene_sunset_holds_x_to_the_targets_it_names(
    set_pool, catalog_by_name,
):
    """CR 601.2c: X is the number of targets. X = 2 naming one creature is not
    an announcement, and X = 0 naming none is (the spell does nothing)."""
    game = _w1g2_table(set_pool, catalog_by_name)
    ogre = _w1g2_put(game, 1, "Gray Ogre")
    game.players[0].hand.append(game._w1g2_card("Serene Sunset"))
    refused = game.cast_from_hand(
        0, "Serene Sunset", x_value=2, target_permanent_ids=[ogre.permanent_id],
    )
    assert not refused.supported
    assert "needs 2 targets" in refused.details

    accepted = game.cast_from_hand(0, "Serene Sunset", x_value=0, target_permanent_ids=[])
    assert accepted.supported, accepted.details
    _w1g2_resolve_stack(game)
    assert "Serene Sunset: no creature to silence" in game.log


def test_w1g2_serene_sunset_leaves_noncombat_damage_alone(
    set_pool, catalog_by_name,
):
    """"…all **combat** damage": the named Prodigal Sorcerer's ping is not
    combat damage (CR 510.2 is what makes damage combat damage) and lands."""
    game = _w1g2_table(set_pool, catalog_by_name)
    sorcerer = _w1g2_put(game, 1, "Prodigal Sorcerer")
    _w1g2_cast(
        game, 0, "Serene Sunset", x_value=1,
        target_permanent_ids=[sorcerer.permanent_id],
    )
    _w1g2_resolve_stack(game)
    result = game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0)
    assert result.supported, result.details
    _w1g2_resolve_stack(game)

    assert game.players[0].life == 19


def test_w1g2_serene_sunset_picker_asks_for_x_creatures(set_pool):
    """The picker reads the compiled program: a creature target description
    whose count is the announced X, so the client asks for X creatures rather
    than sending a bare cast the engine refuses."""
    from engine.targeting import derive_cast_spec

    card = set_pool("JUD")["Serene Sunset"]
    spec = derive_cast_spec(card, _w1g2_compile(card))
    assert spec == {"kind": "creature", "x_targets": True, "distinct_targets": True}


# --- Flaring Pain -----------------------------------------------------------


def test_w1g2_flaring_pain_switches_off_a_circle_without_spending_it(
    set_pool, catalog_by_name,
):
    """"Damage can't be prevented this turn." Under it a Circle of Protection:
    Red prevents nothing — the bolt's 3 lands — and CR 615.12's last sentence
    keeps the shield unspent: it is still there, waiting, after the bolt."""
    game = _w1g2_table(set_pool, catalog_by_name)
    _w1g2_put(game, 0, "Circle of Protection: Red")
    assert game.activate_permanent_ability(0, "Circle of Protection: Red").supported
    _w1g2_resolve_stack(game)
    assert len(_w1g2_shields_on(game.players[0])) == 1
    _w1g2_cast(game, 1, "Flaring Pain")
    _w1g2_resolve_stack(game)

    _w1g2_bolt_player(game, 1, 0)

    assert game.players[0].life == 17
    assert len(_w1g2_shields_on(game.players[0])) == 1


def test_w1g2_flaring_pain_overrides_protection_and_a_fog(
    set_pool, catalog_by_name,
):
    """Protection's damage clause is a prevention effect (CR 702.16e), and so
    is a Fog: Pestilence, a black source, hurts the pro-black White Knight, and
    unblocked attackers hurt their defender through Fog."""
    game = _w1g2_table(set_pool, catalog_by_name)
    knight = _w1g2_put(game, 0, "White Knight")
    _w1g2_put(game, 1, "Pestilence")
    _w1g2_cast(game, 1, "Flaring Pain")
    _w1g2_resolve_stack(game)
    assert game.activate_permanent_ability(1, "Pestilence").supported
    _w1g2_resolve_stack(game)
    assert knight.damage_marked == 1

    _w1g2_put(game, 1, "Gray Ogre")
    _w1g2_declare_attack(game, 1)
    _w1g2_cast(game, 0, "Fog")
    _w1g2_resolve_stack(game)
    game.advance_combat_phase()
    game.resolve_all_combat_damage(1)
    assert game.players[0].life == 20 - 1 - 2


def test_w1g2_flaring_pain_leaves_a_redirect_standing(set_pool, catalog_by_name):
    """The sentence names prevention and nothing else, and a redirect is a
    CR 614.9 replacement: Veteran Bodyguard still takes the unblocked Ogre's
    damage in its controller's place."""
    game = _w1g2_table(set_pool, catalog_by_name)
    guard = _w1g2_put(game, 0, "Veteran Bodyguard")
    _w1g2_put(game, 1, "Gray Ogre")
    _w1g2_cast(game, 1, "Flaring Pain")
    _w1g2_resolve_stack(game)
    _w1g2_declare_attack(game, 1)
    game.advance_combat_phase()
    game.resolve_all_combat_damage(1)

    assert game.players[0].life == 20
    assert guard.damage_marked == 2


def test_w1g2_flaring_pain_lasts_until_the_cleanup_step(set_pool, catalog_by_name):
    """The record ends with every other turn record at cleanup (CR 514.2): a
    Phantom's shield prevents again afterwards, and nothing else was needed to
    end it."""
    game = _w1g2_table(set_pool, catalog_by_name)
    tiger = _w1g2_put(game, 0, "Phantom Tiger")
    _w1g2_cast(game, 1, "Flaring Pain")
    _w1g2_resolve_stack(game)
    game.resolve_cleanup_step(game.active_player_index)

    _w1g2_cast(game, 1, "Shock", target_player_index=0,
               target_permanent_ids=[tiger.permanent_id])
    _w1g2_resolve_stack(game)

    assert tiger.damage_marked == 0
    assert int(tiger.metadata.get("plus_counters", 0)) == 1


def test_w1g2_flaring_pain_flashes_back_for_red(set_pool, catalog_by_name):
    """"Flashback {R}": from the graveyard, then exiled; the lock is armed
    exactly as the hand cast arms it."""
    game = _w1g2_table(set_pool, catalog_by_name)
    game.enforce_mana_costs = True
    game.players[1].mana_pool["R"] = 1
    game.players[1].graveyard.append(game._w1g2_card("Flaring Pain"))
    game.active_player_index = 1
    result = game.cast_from_hand(1, "Flaring Pain", from_zone="graveyard")
    assert result.supported, result.details
    _w1g2_resolve_stack(game)

    assert [c.name for c in game.players[1].exile] == ["Flaring Pain"]
    assert game.players[1].mana_pool["R"] == 0
    assert "Flaring Pain: damage can't be prevented this turn" in game.log

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
#
# Cards in a graveyard as targets. Funeral Pyre exiles a card from any
# graveyard and gives the token to that card's **owner** (CR 404.1: a card in a
# graveyard is in its owner's; CR 108.4a: it has no controller).

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from engine.targeting import derive_cast_spec as _w1g3_derive_cast_spec
from engine.oracle import compile_card_oracle as _w1g3_compile
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_pyre_game(set_pool, *, mine=(), theirs=()):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", hand=[jud["Funeral Pyre"]],
            graveyard=[lea[name] for name in mine], library=[lea["Plains"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[name] for name in theirs],
            library=[lea["Plains"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _w1g3_spirits(player, game):
    return [
        perm for perm in game.controlled_by(game.players.index(player))
        if perm.card.name == "Spirit Token"
    ]


def test_w1g3_funeral_pyre_gives_the_spirit_to_the_exiled_cards_owner(set_pool):
    game = _w1g3_pyre_game(set_pool, mine=("Swamp",), theirs=("Grizzly Bears", "Terror"))
    pyre = set_pool("JUD")["Funeral Pyre"]
    spec = _w1g3_derive_cast_spec(pyre, _w1g3_compile(pyre))
    # Any graveyard, any card: the picker is not scoped to either pile.
    assert spec["kind"] == "graveyard_creature" and spec.get("any_card")
    assert not spec.get("own_graveyard_only")
    offered = {(t["seat"], t["name"]) for t in game.cast_target_spec(0, pyre)["valid_targets"]}
    assert offered == {(0, "Swamp"), (1, "Grizzly Bears"), (1, "Terror")}

    assert game.queue_from_hand(
        0, "Funeral Pyre", target_player_index=1, target_permanent_index=1,
    ).supported
    _w1g3_resolve(game)

    victim = game.players[1]
    assert [c.name for c in victim.exile] == ["Terror"]
    assert [c.name for c in victim.graveyard] == ["Grizzly Bears"]
    (spirit,) = _w1g3_spirits(victim, game)
    assert game._has_keyword(spirit, "flying")
    assert (spirit.effective_power, spirit.effective_toughness) == (1, 1)
    assert spirit.card.colors in (("W",), ["W"])
    assert _w1g3_spirits(game.players[0], game) == []


def test_w1g3_funeral_pyre_on_its_casters_own_card_gives_the_caster_the_spirit(set_pool):
    game = _w1g3_pyre_game(set_pool, mine=("Swamp",), theirs=("Grizzly Bears",))
    assert game.queue_from_hand(
        0, "Funeral Pyre", target_player_index=0, target_permanent_index=0,
    ).supported
    _w1g3_resolve(game)

    assert [c.name for c in game.players[0].exile] == ["Swamp"]
    assert len(_w1g3_spirits(game.players[0], game)) == 1
    assert _w1g3_spirits(game.players[1], game) == []


def test_w1g3_funeral_pyre_whose_card_left_in_response_makes_no_spirit(set_pool):
    """CR 608.2b: its one target gone, the spell does not resolve — so there
    is no exiled card, and no owner to hand a token to."""
    game = _w1g3_pyre_game(set_pool, theirs=("Grizzly Bears", "Terror"))
    assert game.queue_from_hand(
        0, "Funeral Pyre", target_player_index=1, target_permanent_index=0,
    ).supported
    victim = game.players[1]
    victim.exile.append(victim.graveyard.pop(0))          # the Bears, in response

    _w1g3_resolve(game)

    assert [c.name for c in victim.graveyard] == ["Terror"]
    assert _w1g3_spirits(victim, game) == [] and _w1g3_spirits(game.players[0], game) == []

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
#
# Threshold and the graveyard counted.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from engine.targeting import derive_cast_spec as _w1g7_derive_cast_spec
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_table(set_pool, catalog_by_name, graveyard=0, *, interactive=()):
    """Two seats with libraries; seat 0 holds *graveyard* Islands in its
    graveyard. Mana off; a card lookup over Judgment first."""
    jud = set_pool("JUD")

    def card(name):
        return jud[name] if name in jud else catalog_by_name[name]

    island = catalog_by_name["Island"]
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="Alice", library=[island] * 10,
                         graveyard=[island] * graveyard),
        _W1G7PlayerState(name="Bob", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g7_card = card
    return game


def _w1g7_put(game, seat, name):
    permanent = _W1G7Permanent(card=game._w1g7_card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g7_resolve(game)
    _w1g7_nosick(permanent)
    return permanent


def _w1g7_cast(game, seat, name, **announcement):
    game.players[seat].hand.append(game._w1g7_card(name))
    result = game.cast_from_hand(seat, name, **announcement)
    assert result.supported, result.details
    _w1g7_resolve(game)
    return result


# --- Toxic Stench -----------------------------------------------------------


@_w1g7_pytest.mark.parametrize(("graveyard", "destroyed"), [(6, False), (7, True)])
def test_w1g7_toxic_stench_shrinks_or_destroys_its_one_target(
    set_pool, catalog_by_name, graveyard, destroyed,
):
    """-1/-1 below threshold; "instead destroy that creature" at it — the same
    creature, never both effects."""
    game = _w1g7_table(set_pool, catalog_by_name, graveyard)
    giant = _w1g7_put(game, 1, "Hill Giant")
    _w1g7_cast(game, 0, "Toxic Stench", target_permanent_ids=[giant.permanent_id])

    assert game.is_on_battlefield(giant) is not destroyed
    if destroyed:
        assert [c.name for c in game.players[1].graveyard] == ["Hill Giant"]
    else:
        assert (giant.effective_power, giant.effective_toughness) == (2, 2)


def test_w1g7_toxic_stench_at_threshold_cannot_be_regenerated(
    set_pool, catalog_by_name,
):
    """"It can't be regenerated." Uthden Troll's regeneration shield is up and
    the destruction goes through it anyway (CR 701.19c)."""
    game = _w1g7_table(set_pool, catalog_by_name, 7)
    troll = _w1g7_put(game, 1, "Uthden Troll")
    assert game.activate_permanent_ability(1, "Uthden Troll").supported
    _w1g7_resolve(game)
    _w1g7_cast(game, 0, "Toxic Stench", target_permanent_ids=[troll.permanent_id])

    assert not game.is_on_battlefield(troll)
    assert [c.name for c in game.players[1].graveyard] == ["Uthden Troll"]


def test_w1g7_toxic_stench_names_only_a_nonblack_creature(set_pool, catalog_by_name):
    """"Target nonblack creature": the picker offers the Giant and not the
    Black Knight, and naming the Knight is refused before anything is paid —
    so the threshold arm cannot reach a black creature either."""
    game = _w1g7_table(set_pool, catalog_by_name, 7)
    _w1g7_put(game, 1, "Hill Giant")
    knight = _w1g7_put(game, 1, "Black Knight")
    stench = game._w1g7_card("Toxic Stench")
    assert _w1g7_derive_cast_spec(stench, _w1g7_compile(stench)) == {
        "kind": "creature", "filter": {"exclude_colors": ["B"]},
    }
    offered = [t["name"] for t in game.cast_target_spec(0, stench)["valid_targets"]]
    assert offered == ["Hill Giant"]
    game.players[0].hand.append(stench)
    refused = game.cast_from_hand(0, "Toxic Stench", target_permanent_ids=[knight.permanent_id])
    assert not refused.supported
    assert game.is_on_battlefield(knight)

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
