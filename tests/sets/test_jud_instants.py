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
#
# Grip of Amnesia: "Counter target spell unless its controller exiles all
# cards from their graveyard. / Draw a card." The punisher offer Molten
# Influence makes (the *spell's* controller asked, ``stack_target_controller``)
# with the whole-graveyard sweep for its price.

import pytest as _w1g5_pytest  # noqa: E402

from engine.oracle import compile_card_oracle as _w1g5_compile  # noqa: E402
from engine.targeting import derive_cast_spec as _w1g5_cast_spec  # noqa: E402
from tests.sets import jud_w1g5_helpers as _w1g5  # noqa: E402


def _w1g5_grip(set_pool, *, bolt_caster=1, graveyard=3, interactive=(0, 1)):
    """*bolt_caster*'s Lightning Bolt at the other seat, with seat 0's Grip of
    Amnesia aimed at it; the Bolt's controller holds *graveyard* cards."""
    hands = [["Grip of Amnesia"], []]
    hands[bolt_caster].append("Lightning Bolt")
    game = _w1g5.table(set_pool, hands=hands, interactive=interactive)
    game.players[bolt_caster].graveyard.extend(
        [_w1g5.card(set_pool, "Grizzly Bears")] * graveyard
    )
    game.start_turn(0)
    bolt = game.queue_from_hand(
        bolt_caster, "Lightning Bolt", target_player_index=1 - bolt_caster,
    )
    assert bolt.supported, bolt.details
    grip = game.queue_from_hand(0, "Grip of Amnesia", target_stack_index=0)
    assert grip.supported, grip.details
    return game


@_w1g5_pytest.mark.parametrize("bolt_caster", [1, 0])
def test_w1g5_grip_exiled_graveyard_lets_the_spell_resolve(set_pool, bolt_caster):
    """The spell's controller is asked — the opponent, or Grip's own caster
    aiming at their own spell — and paying exiles their graveyard."""
    game = _w1g5_grip(set_pool, bolt_caster=bolt_caster)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g5.owed(game) == [bolt_caster]
    assert game.confirm_optional_pay(bolt_caster, accept=True)
    _w1g5.settle(game)

    payer = game.players[bolt_caster]
    assert [found.name for found in payer.exile] == ["Grizzly Bears"] * 3
    # What is left is what arrived after the exile: the Bolt, and Grip itself
    # when its caster was the one who paid.
    assert "Grizzly Bears" not in _w1g5.pile(game, bolt_caster)
    assert game.players[1 - bolt_caster].life == 17, "the Bolt resolved"


def test_w1g5_grip_declined_counters_the_spell_and_keeps_the_graveyard(set_pool):
    game = _w1g5_grip(set_pool)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(1, accept=False)
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 20]
    assert game.players[1].exile == []
    assert _w1g5.pile(game, 1).count("Grizzly Bears") == 3
    assert "Lightning Bolt was countered by Grip of Amnesia and moved to graveyard" in game.log


def test_w1g5_grip_is_offered_to_an_empty_graveyard(set_pool):
    """"You can choose to exile all cards from your graveyard even if it has
    no cards in it." (Grip of Amnesia ruling, 2004-10-04.) The offer is made,
    and taking it saves the spell for nothing."""
    game = _w1g5_grip(set_pool, graveyard=0)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g5.owed(game) == [1]
    assert game.confirm_optional_pay(1, accept=True)
    _w1g5.settle(game)

    assert game.players[0].life == 17


def test_w1g5_grip_draws_a_card_whichever_way_it_goes(set_pool):
    for accept in (True, False):
        game = _w1g5_grip(set_pool)
        game.resolve_top_of_stack(pause_for_choices=True)
        game.confirm_optional_pay(1, accept=accept)
        _w1g5.settle(game)
        assert len(game.players[0].hand) == 1, accept


def test_w1g5_grip_answered_headless_before_the_spell_resolves(set_pool):
    """A seat nobody asks answers where the offer stands, because the spell
    it is about is the next object to resolve — the Molten Influence rule."""
    game = _w1g5_grip(set_pool, interactive=())
    _w1g5.settle(game)

    assert game.stack == []
    countered = "Lightning Bolt was countered by Grip of Amnesia and moved to graveyard" in game.log
    assert countered == (game.players[0].life == 20)
    assert countered != (len(game.players[1].exile) == 3)


def test_w1g5_grip_announces_a_spell_and_nothing_else(set_pool):
    """The picker offers the one target the line prints; the graveyard is the
    payer's, never a player Grip chose."""
    grip = _w1g5.card(set_pool, "Grip of Amnesia")
    assert _w1g5_cast_spec(grip, _w1g5_compile(grip)) == {"kind": "stack"}
    game = _w1g5.table(set_pool, hands=(["Grip of Amnesia"], []))
    game.start_turn(0)
    assert not game.cast_from_hand(0, "Grip of Amnesia").supported, "an empty stack"

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Cunning Wish: "You may reveal an instant card you own from outside the game
# and put it into your hand. Exile Cunning Wish." The sorcery Wishes' tests
# (offer, pick, reveal, ante, exile) are in test_jud_sorceries.py's W1G6
# section; what is the instant's own is the timing.

from engine import Game as _W1G6IGame, PlayerState as _W1G6IPlayerState  # noqa: E402
from tests.helpers import resolve_stack as _w1g6i_resolve_stack  # noqa: E402


def test_w1g6_cunning_wish_on_the_opponents_turn_fetches_an_instant_that_is_then_cast(set_pool):
    """Cast in Bob's turn, with a creature spell of his on the stack — an
    instant's timing (CR 304.1) — Cunning Wish resolves first, brings in the
    one instant its sideboard holds (not the sorcery beside it), and that
    Lightning Bolt is cast from the hand in the same window, at Bob."""
    lea = set_pool("LEA")
    game = _W1G6IGame(players=[
        _W1G6IPlayerState(
            name="Alice", hand=[set_pool("JUD")["Cunning Wish"]],
            library=[lea["Island"]] * 5,
            sideboard=[lea["Stone Rain"], lea["Lightning Bolt"]],
        ),
        _W1G6IPlayerState(
            name="Bob", hand=[lea["Grizzly Bears"]], library=[lea["Island"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    assert game.queue_from_hand(1, "Grizzly Bears").supported

    assert game.queue_from_hand(0, "Cunning Wish").supported
    assert [item.card.name for item in game.stack] == ["Grizzly Bears", "Cunning Wish"]
    assert game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    alice = game.players[0]
    assert [card.name for card in alice.hand] == ["Lightning Bolt"]
    assert [card.name for card in alice.sideboard] == ["Stone Rain"]
    assert [card.name for card in alice.exile] == ["Cunning Wish"]
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6i_resolve_stack(game)
    assert game.players[1].life == 17
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
import pytest as _w1g8_pytest

from engine import Game as _w1g8_Game
from engine import PlayerState as _w1g8_PlayerState
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_duel(*, active: int = 0) -> "_w1g8_Game":
    """Two seats, mana costs waived, seat *active*'s turn started for real."""
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P1"), _w1g8_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(active)
    return game


def _w1g8_zone_names(zone) -> list[str]:
    return sorted(card.name for card in zone)


# --- Seedtime -------------------------------------------------------------

def test_w1g8_seedtime_takes_an_extra_turn_when_an_opponent_cast_a_blue_spell(set_pool):
    """"Take an extra turn after this one if an opponent cast a blue spell this
    turn." Ruling 2004-10-04: "an unresolved spell still counts" — the blue
    spell here is cast *in response*, so it is still on the stack above
    Seedtime when it is cast, and resolves before it."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].hand.append(jud["Seedtime"])
    game.players[1].hand.append(lea["Ancestral Recall"])
    game.players[1].library.extend([lea["Island"]] * 3)
    assert game.queue_from_hand(0, "Seedtime").supported
    assert game.queue_from_hand(1, "Ancestral Recall", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    assert game.extra_turns.get(0, 0) == 1
    assert game.extra_turns.get(1, 0) == 0
    assert "P1 gained an extra turn" in game.log
    assert _w1g8_zone_names(game.players[0].graveyard) == ["Seedtime"]


def test_w1g8_seedtime_without_a_blue_opposing_cast_takes_no_turn(set_pool):
    """The narrowing is enforced, not dropped: an opponent's *red* spell does
    not open it, and neither does a blue spell Seedtime's own caster cast."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].hand.extend([jud["Seedtime"], lea["Ancestral Recall"]])
    game.players[0].library.extend([lea["Island"]] * 3)
    game.players[1].hand.append(lea["Lightning Bolt"])
    assert game.cast_from_hand(0, "Ancestral Recall", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.queue_from_hand(0, "Seedtime").supported
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[0].life == 17                 # the Bolt resolved
    assert game.extra_turns.get(0, 0) == 0
    assert not any("gained an extra turn" in line for line in game.log)
    assert "Seedtime" in _w1g8_zone_names(game.players[0].graveyard)


def test_w1g8_seedtime_is_cast_only_during_its_casters_turn(set_pool):
    """"Cast this spell only during your turn." (CR 601.3.) Refused on the
    opponent's turn with the card still in hand, and legal again on the
    caster's own."""
    jud = set_pool("JUD")
    game = _w1g8_duel(active=1)
    game.players[0].hand.append(jud["Seedtime"])
    refused = game.cast_from_hand(0, "Seedtime")
    assert not refused.supported
    assert "can only be cast during your turn" in refused.details
    assert _w1g8_zone_names(game.players[0].hand) == ["Seedtime"]
    game.start_turn(0)
    assert game.cast_from_hand(0, "Seedtime").supported
    assert "Seedtime" in _w1g8_zone_names(game.players[0].graveyard)


# --- Laquatus's Disdain ---------------------------------------------------

def _w1g8_firebolt_flashed_back(set_pool) -> "_w1g8_Game":
    """Seat 0 flashes Firebolt back at seat 1, leaving it on the stack."""
    game = _w1g8_duel()
    game.players[0].graveyard.append(set_pool("ODY")["Firebolt"])
    assert game.queue_from_hand(
        0, "Firebolt", from_zone="graveyard", target_player_index=1,
    ).supported
    assert game.stack[-1].flashback and game.stack[-1].cast_from_zone == "graveyard"
    return game


def test_w1g8_laquatuss_disdain_counters_a_spell_cast_from_a_graveyard(set_pool):
    """"Counter target spell cast from a graveyard. Draw a card." A flashed-back
    Firebolt is countered (and, flashed back, exiled — CR 702.34a), and the
    Disdain's caster draws."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_firebolt_flashed_back(set_pool)
    game.players[1].hand.append(jud["Laquatus's Disdain"])
    game.players[1].library.append(lea["Island"])
    spec = game.cast_target_spec(1, jud["Laquatus's Disdain"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Firebolt"]
    assert game.queue_from_hand(1, "Laquatus's Disdain", target_stack_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20                       # Firebolt never resolved
    assert _w1g8_zone_names(game.players[0].exile) == ["Firebolt"]
    assert _w1g8_zone_names(game.players[1].hand) == ["Island"]
    assert any(
        line.startswith("Firebolt was countered by Laquatus's Disdain")
        for line in game.log
    )


def test_w1g8_laquatuss_disdain_counters_any_graveyard_cast_not_only_flashback(set_pool):
    """Ruling 2004-10-04: "Can be used to counter a spell cast using the
    Flashback ability, **or cast from the graveyard using any other effect**."
    A graveyard opened by another permission (CR 601.3) is a graveyard cast."""
    from engine.cast_permissions import grant_permission

    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].graveyard.append(lea["Lightning Bolt"])
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast", cards=None,
        duration="end_of_turn", source_name="Test Opened Graveyard",
    )
    assert game.queue_from_hand(
        0, "Lightning Bolt", from_zone="graveyard", target_player_index=1,
    ).supported
    assert not game.stack[-1].flashback
    game.players[1].hand.append(jud["Laquatus's Disdain"])
    assert game.queue_from_hand(1, "Laquatus's Disdain", target_stack_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20
    assert _w1g8_zone_names(game.players[0].graveyard) == ["Lightning Bolt"]


def test_w1g8_laquatuss_disdain_cannot_be_cast_at_a_spell_cast_from_a_hand(set_pool):
    """The narrowing is the picker's and the gate's: a Lightning Bolt cast from
    a hand is not offered, and naming it anyway is refused before anything is
    spent (CR 601.2c) — the Disdain stays in hand and the Bolt resolves."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    game.players[1].hand.append(jud["Laquatus's Disdain"])
    spec = game.cast_target_spec(1, jud["Laquatus's Disdain"])
    assert spec["valid_targets"] == []
    refused = game.cast_from_hand(1, "Laquatus's Disdain", target_stack_index=0)
    assert not refused.supported
    assert _w1g8_zone_names(game.players[1].hand) == ["Laquatus's Disdain"]
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 17


# --- Flash of Insight -----------------------------------------------------

def _w1g8_insight_board(set_pool, *, blue_in_graveyard: int) -> "_w1g8_Game":
    """Seat 0: Flash of Insight on the bottom of its graveyard, *blue_in_graveyard*
    Counterspells and a Lightning Bolt above it, five lands in its library, and
    exactly {1}{U} floating — mana costs enforced."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.enforce_mana_costs = True
    player = game.players[0]
    player.graveyard.append(jud["Flash of Insight"])
    player.graveyard.extend([lea["Counterspell"]] * blue_in_graveyard)
    player.graveyard.append(lea["Lightning Bolt"])
    player.library.extend([lea[name] for name in (
        "Island", "Forest", "Mountain", "Swamp", "Plains",
    )])
    player.mana_pool.update({"U": 1, "C": 1})
    return game


def test_w1g8_flash_of_insight_flashes_back_exiling_x_blue_cards(set_pool):
    """"Flashback—{1}{U}, Exile X blue cards from your graveyard." X is the
    caster's announcement (CR 107.3a) and both the price and the effect read
    it: two blue cards leave the graveyard, the top two cards are looked at,
    one goes to hand and the other to the bottom (CR 702.34a: the spell is
    exiled afterwards). The Lightning Bolt is not blue and stays."""
    game = _w1g8_insight_board(set_pool, blue_in_graveyard=3)
    player = game.players[0]
    spec = game.cast_target_spec(0, set_pool("JUD")["Flash of Insight"], from_zone="graveyard")
    assert spec["announces_x"] and spec["max_x"] == 3     # the spell itself is not one
    # The caster names which blue cards pay (CR 601.2b) — slots in the pile as
    # it stands, the spell still at the bottom of it.
    cast = game.cast_from_hand(
        0, "Flash of Insight", from_zone="graveyard", x_value=2,
        cost_graveyard_indices=[1, 3],
    )
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)
    assert not any(player.mana_pool.values())
    assert _w1g8_zone_names(player.exile) == ["Counterspell", "Counterspell", "Flash of Insight"]
    assert _w1g8_zone_names(player.graveyard) == ["Counterspell", "Lightning Bolt"]
    assert len(player.hand) == 1 and player.hand[0].name in ("Island", "Forest")
    assert [card.name for card in player.library][:3] == ["Mountain", "Swamp", "Plains"]
    assert len(player.library) == 4
    assert "P1 is looking at the top 2 cards of their library" in game.log


def test_w1g8_flash_of_insight_cannot_exile_itself_to_pay_for_its_flashback(set_pool):
    """"You can't exile Flash of Insight to pay for its own flashback cost." CR
    601.2a moves it to the stack before any cost is paid, so with two other
    blue cards an X of three is unpayable (CR 601.2h): refused with nothing
    spent and the card still in the graveyard. An X of two is fine."""
    game = _w1g8_insight_board(set_pool, blue_in_graveyard=2)
    player = game.players[0]
    refused = game.cast_from_hand(0, "Flash of Insight", from_zone="graveyard", x_value=3)
    assert not refused.supported
    assert "flashback cost" in refused.details and "601.2h" in refused.details
    assert player.mana_pool["U"] == 1 and player.exile == []
    assert "Flash of Insight" in _w1g8_zone_names(player.graveyard)
    assert game.cast_from_hand(0, "Flash of Insight", from_zone="graveyard", x_value=2).supported


def test_w1g8_flash_of_insight_holds_a_named_set_of_cards_to_the_announced_x(set_pool):
    """CR 601.2h: "Partial payments are not allowed." Naming one blue card for
    an X of two, or naming the Lightning Bolt, or the spell's own slot, is
    refused before anything is spent."""
    for named in ([1], [1, 4], [0, 1]):
        game = _w1g8_insight_board(set_pool, blue_in_graveyard=3)
        refused = game.cast_from_hand(
            0, "Flash of Insight", from_zone="graveyard", x_value=2,
            cost_graveyard_indices=named,
        )
        assert not refused.supported, named
        assert game.players[0].exile == [] and len(game.players[0].graveyard) == 5


def test_w1g8_flash_of_insight_from_hand_looks_at_x(set_pool):
    """Cast from a hand for {X}{1}{U}, it exiles nothing and looks at X."""
    lea = set_pool("LEA")
    game = _w1g8_duel()
    player = game.players[0]
    player.hand.append(set_pool("JUD")["Flash of Insight"])
    player.graveyard.append(lea["Counterspell"])
    player.library.extend([lea["Island"], lea["Forest"], lea["Mountain"]])
    assert game.cast_from_hand(0, "Flash of Insight", x_value=3).supported
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)
    assert _w1g8_zone_names(player.graveyard) == ["Counterspell", "Flash of Insight"]
    assert len(player.hand) == 1 and len(player.library) == 2
    assert "P1 is looking at the top 3 cards of their library" in game.log


# --- Spelljack ------------------------------------------------------------

def _w1g8_spelljacked(set_pool, name: str, *, from_zone: str = "hand", **cast) -> "_w1g8_Game":
    """Seat 1 casts *name* at seat 0; seat 0 answers with Spelljack, paying
    {3}{U}{U}{U} for it, and the stack is drained. Costs enforced from then on."""
    game = _w1g8_duel(active=1)
    spell = (set_pool("ODY") if name == "Firebolt" else set_pool("LEA"))[name]
    getattr(game.players[1], "graveyard" if from_zone == "graveyard" else "hand").append(spell)
    assert game.queue_from_hand(1, name, from_zone=from_zone, **cast).supported
    game.players[0].hand.append(set_pool("JUD")["Spelljack"])
    assert game.queue_from_hand(0, "Spelljack", target_stack_index=0).supported
    _w1g8_resolve_stack(game)
    game.enforce_mana_costs = True
    return game


def test_w1g8_spelljack_counters_exiles_and_lets_its_caster_cast_the_card_free(set_pool):
    """"Counter target spell. If that spell is countered this way, exile it
    instead of putting it into its owner's graveyard. You may play it without
    paying its mana cost for as long as it remains exiled." The Bolt never
    resolves; it waits in its owner's exile, and Spelljack's caster casts it
    there with an empty pool. Ruling 2004-10-04: "If you cast an instant or
    sorcery, it goes to its owner's graveyard when it resolves.\""""
    game = _w1g8_spelljacked(set_pool, "Lightning Bolt", target_player_index=0)
    assert game.players[0].life == 20
    assert _w1g8_zone_names(game.players[1].exile) == ["Lightning Bolt"]
    assert game.players[1].graveyard == []
    # Seat 1 may not cast its own card back; seat 0 may, and for nothing.
    game.start_turn(0)
    assert not game.cast_from_hand(1, "Lightning Bolt", from_zone="exile", target_player_index=0).supported
    assert not any(game.players[0].mana_pool.values())
    cast = game.cast_from_hand(0, "Lightning Bolt", from_zone="exile", target_player_index=1)
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 17
    assert game.players[1].exile == []
    assert _w1g8_zone_names(game.players[1].graveyard) == ["Lightning Bolt"]
    assert game.players[0].graveyard == [] or _w1g8_zone_names(game.players[0].graveyard) == ["Spelljack"]


def test_w1g8_spelljack_permission_lasts_for_as_long_as_the_card_remains_exiled(set_pool):
    """CR 611.2a's duration stated as a zone: the turn ending does not end it,
    and the card leaving exile does."""
    from engine.cast_permissions import expire_end_of_turn, permission_for

    game = _w1g8_spelljacked(set_pool, "Lightning Bolt", target_player_index=0)
    bolt = game.players[1].exile[0]
    expire_end_of_turn(game)
    assert permission_for(game, 0, bolt, "exile") is not None
    game.players[1].exile.remove(bolt)
    game.players[1].graveyard.append(bolt)
    assert permission_for(game, 0, bolt, "exile") is None


def test_w1g8_spelljack_on_a_flashed_back_spell(set_pool):
    """Ruling 2004-10-04: "This spell can be used on a spell cast using
    Flashback." The flashed-back Firebolt is exiled (by its own keyword, CR
    702.34a, and by Spelljack's replacement — one exile either way), and its
    new controller may cast it from there, as an ordinary cast this time: it
    goes to its owner's graveyard when it resolves, not to exile."""
    game = _w1g8_spelljacked(
        set_pool, "Firebolt", from_zone="graveyard", target_player_index=0,
    )
    assert game.players[0].life == 20
    assert _w1g8_zone_names(game.players[1].exile) == ["Firebolt"]
    game.start_turn(0)
    cast = game.cast_from_hand(0, "Firebolt", from_zone="exile", target_player_index=1)
    assert cast.supported, cast.details
    assert not game.stack or not game.stack[-1].flashback
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 18
    assert _w1g8_zone_names(game.players[1].graveyard) == ["Firebolt"]


def test_w1g8_spelljack_casts_an_x_spell_for_x_equal_to_zero(set_pool):
    """"(If it has X in its mana cost, X is 0.)" — CR 107.3b: cast while paying
    neither its mana cost nor an alternative cost that includes X, a Fireball
    announced at five deals nothing."""
    game = _w1g8_spelljacked(set_pool, "Fireball", x_value=3, target_player_index=0)
    assert game.players[0].life == 20
    game.start_turn(0)
    cast = game.cast_from_hand(0, "Fireball", from_zone="exile", x_value=5, target_player_index=1)
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20
    assert _w1g8_zone_names(game.players[1].graveyard) == ["Fireball"]


# --- Shaman's Trance --------------------------------------------------------

def _w1g8_tranced(set_pool) -> "_w1g8_Game":
    """Seat 0 resolves Shaman's Trance on its own turn. Seat 1's graveyard holds
    a Lightning Bolt, a Firebolt and a Mountain; seat 0's holds a Lightning
    Bolt of its own. Costs waived."""
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g8_duel()
    game.players[0].hand.append(set_pool("JUD")["Shaman's Trance"])
    game.players[0].graveyard.append(lea["Lightning Bolt"])
    game.players[1].graveyard.extend([lea["Lightning Bolt"], ody["Firebolt"], lea["Mountain"]])
    assert game.cast_from_hand(0, "Shaman's Trance").supported
    _w1g8_resolve_stack(game)
    return game


def test_w1g8_shamans_trance_opens_other_players_graveyards_to_its_caster(set_pool):
    """"You may play lands and cast spells from other players' graveyards this
    turn as though those cards were in your graveyard." Seat 0 casts seat 1's
    Bolt (it goes back to its owner's graveyard, CR 608.2n), plays seat 1's
    Mountain as its land drop, and flashes back seat 1's Firebolt (ruling
    2004-10-04: "You can use Flashback on cards to cast them") — exiled to its
    owner's exile. Its own graveyard is not one the sentence opens."""
    from engine.cast_permissions import playable_from_zones

    game = _w1g8_tranced(set_pool)
    offered = {(entry["owner_seat"], entry["name"]) for entry in playable_from_zones(game, 0)}
    assert offered == {(1, "Lightning Bolt"), (1, "Firebolt"), (1, "Mountain")}

    assert game.cast_from_hand(0, "Lightning Bolt", from_zone="graveyard", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 17
    assert "Lightning Bolt" in _w1g8_zone_names(game.players[1].graveyard)

    assert game.cast_from_hand(0, "Mountain", from_zone="graveyard").supported
    mountain = next(p for p in game.controlled_by(0) if p.card.name == "Mountain")
    assert "Mountain" not in _w1g8_zone_names(game.players[1].graveyard)
    # Played by seat 0, still seat 1's card (CR 108.3): it dies into seat 1's pile.
    assert game.owner_index_of(mountain) == 1

    flashed = game.queue_from_hand(
        0, "Firebolt", from_zone="graveyard", target_player_index=1,
        alternative_cost=True,
    )
    assert flashed.supported, flashed.details
    assert game.stack[-1].flashback
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 15
    assert _w1g8_zone_names(game.players[1].exile) == ["Firebolt"]


def test_w1g8_shamans_trance_closes_other_players_graveyards_to_them(set_pool):
    """"Other players can't play lands or cast spells from their graveyards this
    turn." Seat 1 may not flash back its own Firebolt nor play its Mountain out
    of its graveyard — and the cast is refused before anything is spent."""
    game = _w1g8_tranced(set_pool)
    game.enforce_mana_costs = True
    game.players[1].mana_pool.update({"R": 1, "C": 4})
    refused = game.cast_from_hand(1, "Firebolt", from_zone="graveyard", target_player_index=0)
    assert not refused.supported
    assert "can't play lands or cast spells from their graveyard" in refused.details
    assert game.players[1].mana_pool["R"] == 1
    assert "Firebolt" in _w1g8_zone_names(game.players[1].graveyard)
    assert game.players[0].life == 20


def test_w1g8_shamans_trance_on_an_opponents_turn_stops_their_graveyard_land_drop(set_pool):
    """Both verbs are printed, so the ban binds a land drop too (CR 305.1) —
    which matters on the opponent's own turn, where the instant is cast in
    their upkeep: with their graveyard opened by another effect, their
    Mountain still may not be played from it, while one from hand may."""
    from engine.cast_permissions import grant_permission

    lea = set_pool("LEA")
    game = _w1g8_duel(active=1)
    game.players[0].hand.append(set_pool("JUD")["Shaman's Trance"])
    game.players[1].graveyard.append(lea["Mountain"])
    game.players[1].hand.append(lea["Mountain"])
    grant_permission(
        game, player_index=1, zone="graveyard", mode="play", cards=None,
        duration="end_of_turn", source_name="Test Opened Graveyard",
    )
    assert game.cast_from_hand(0, "Shaman's Trance").supported
    _w1g8_resolve_stack(game)
    refused = game.cast_from_hand(1, "Mountain", from_zone="graveyard")
    assert not refused.supported
    assert "can't play lands or cast spells from their graveyard" in refused.details
    assert _w1g8_zone_names(game.players[1].graveyard) == ["Mountain"]
    assert game.cast_from_hand(1, "Mountain").supported
    assert [p.card.name for p in game.controlled_by(1)] == ["Mountain"]


def test_w1g8_envelop_counters_a_sorcery_and_offers_no_instant(set_pool):
    """Drive list: "Counter target sorcery spell." A Mind Twist is offered and
    countered; a Lightning Bolt is not offered and naming it is refused."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[1].hand.append(lea["Mind Twist"])
    game.players[0].hand.extend([lea["Island"], lea["Island"]])
    assert game.queue_from_hand(
        1, "Mind Twist", target_player_index=0, x_value=2,
    ).supported
    game.players[0].hand.append(jud["Envelop"])
    assert [t["name"] for t in game.cast_target_spec(0, jud["Envelop"])["valid_targets"]] == ["Mind Twist"]
    assert game.queue_from_hand(0, "Envelop", target_stack_index=0).supported
    _w1g8_resolve_stack(game)
    assert _w1g8_zone_names(game.players[0].hand) == ["Island", "Island"]
    assert _w1g8_zone_names(game.players[1].graveyard) == ["Mind Twist"]

    game = _w1g8_duel()
    game.players[1].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    game.players[0].hand.append(jud["Envelop"])
    assert game.cast_target_spec(0, jud["Envelop"])["valid_targets"] == []
    assert not game.cast_from_hand(0, "Envelop", target_stack_index=0).supported


@_w1g8_pytest.mark.parametrize("name, power, toughness, first_strike", [
    ("Guided Strike", 3, 2, True),
    ("Sudden Strength", 5, 5, False),
])
def test_w1g8_the_cantrip_pumps_last_the_turn_and_draw(set_pool, name, power, toughness, first_strike):
    """Drive list: "Target creature gets +1/+0 and gains first strike until end
    of turn. Draw a card." / "+3/+3 … Draw a card." Both halves happen, and the
    pump ends at cleanup (CR 514.2)."""
    from engine.models import Permanent
    from tests.helpers import _nosick

    lea = set_pool("LEA")
    game = _w1g8_duel()
    bears = _nosick(Permanent(card=lea["Grizzly Bears"]))
    game.players[0].battlefield.append(bears)
    game.players[0].library.extend([lea["Island"]] * 2)
    game.players[0].hand.append(set_pool("JUD")[name])
    assert game.cast_from_hand(
        0, name, target_permanent_ids=[bears.permanent_id], target_player_index=0,
    ).supported
    _w1g8_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (power, toughness)
    assert game._has_keyword(bears, "first strike") is first_strike
    assert _w1g8_zone_names(game.players[0].hand) == ["Island"]
    game.resolve_cleanup_step(0)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert not game._has_keyword(bears, "first strike")


def test_w1g8_shamans_trance_ends_with_the_turn(set_pool):
    """"This turn" on both halves: after the cleanup sweep (CR 514.2) and the
    next turn's bookkeeping, seat 0 has no permission over seat 1's pile and
    seat 1 may flash its own Firebolt back again."""
    from engine.cast_permissions import playable_from_zones

    game = _w1g8_tranced(set_pool)
    game.resolve_cleanup_step(0)
    game.begin_turn_bookkeeping(1)
    assert playable_from_zones(game, 0) == []
    game.start_turn(1)
    cast = game.cast_from_hand(1, "Firebolt", from_zone="graveyard", target_player_index=0)
    assert cast.supported, cast.details
    assert game.players[0].life == 18

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
