"""Apocalypse enchantments.

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
from engine.layer_bridge import computed_types as _w1g7_computed_types
from engine.mana_payment import spell_mana_cost as _w1g7_spell_mana_cost
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_enchantment_game(*, seats=2, interactive=(0,)):
    """A game of *seats* players with costs off. Seat 0 is interactive by
    default, so a prompt one of these cards arms is *queued* rather than
    answered by its own default."""
    players = [_W1G7PlayerState(name=name) for name in "ABCD"[:seats]]
    game = _W1G7Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, players


def _w1g7_enchantment_put(game, seat, card):
    """Put *card* onto *seat*'s battlefield, ready to act this turn."""
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    return permanent


def _w1g7_enchantment_prompt(game, seat, key):
    """The payload a human at *seat* is shown for prompt *key*, through the web
    layer's own renderer."""
    from web.prompts import PromptContext, render_prompts

    context = PromptContext(
        game=game, viewer_seat=seat,
        serialize_card=lambda card: {"name": getattr(card, "name", str(card))},
        seat_type=lambda index: "human" if index in game.interactive_seats else "ai",
    )
    return render_prompts(context)[key]


def _w1g7_cast_for_free(game, seat, name, **announcement):
    """Seat casts *name* without paying, then costs go back on — so what an
    offer charges afterwards is really charged."""
    game.enforce_mana_costs = False
    result = game.queue_from_hand(seat, name, **announcement)
    game.enforce_mana_costs = True
    assert result.supported, result.details
    return game.stack[0]


# -- Unnatural Selection -----------------------------------------------------


def test_unnatural_selection_sets_the_creature_type_chosen_as_it_resolves(
    set_pool, catalog_by_name
):
    """"{1}: Choose a creature type other than Wall. Target creature becomes
    that type until end of turn." The type is named on resolution (CR 608.2d)
    and *replaces* the creature types the permanent had (CR 205.1a) — which a
    lord then sees: the Bears-turned-Goblin take Goblin King's +1/+1 and
    mountainwalk."""
    game, (p0, p1) = _w1g7_enchantment_game()
    selection = _w1g7_enchantment_put(game, 0, set_pool("APC")["Unnatural Selection"])
    bears = _w1g7_enchantment_put(game, 0, catalog_by_name["Grizzly Bears"])
    _w1g7_enchantment_put(game, 1, catalog_by_name["Goblin King"])
    forest = _w1g7_enchantment_put(game, 0, catalog_by_name["Forest"])
    game._recompute_continuous_effects()

    # A land is not a creature: the picker does not offer it and the
    # announcement gate refuses it.
    assert not game.queue_permanent_ability(
        0, "Unnatural Selection", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert game.queue_permanent_ability(
        0, "Unnatural Selection", target_permanent_ids=[bears.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_computed_types(bears)[1] == {"bear"}
    assert game.confirm_creature_type_choice(0, "Goblin") is True

    assert _w1g7_computed_types(bears) == ({"creature"}, {"goblin"})
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    assert game._has_keyword(bears, "mountainwalk")
    assert "Grizzly Bears became a Goblin until end of turn (Unnatural Selection)" in game.log

    game.resolve_cleanup_step(0)

    assert _w1g7_computed_types(bears)[1] == {"bear"}
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_unnatural_selection_never_offers_or_accepts_wall(set_pool, catalog_by_name):
    """"…a creature type **other than Wall**." A restriction on a choice, so it
    is enforced where the choice is made: the prompt's list has no Wall in it,
    the answer "Wall" is refused with the question still standing and the
    creature unchanged, and so is a word that is no creature type at all (the
    card's ruling: "a creature type that already exists in Magic")."""
    game, (p0, p1) = _w1g7_enchantment_game()
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Unnatural Selection"])
    bears = _w1g7_enchantment_put(game, 1, catalog_by_name["Grizzly Bears"])
    game.queue_permanent_ability(
        0, "Unnatural Selection", target_permanent_ids=[bears.permanent_id]
    )
    game.resolve_top_of_stack(pause_for_choices=True)

    offered = _w1g7_enchantment_prompt(game, 0, "creature_type_choice")
    assert "wall" not in offered["creature_types"]
    assert {"goblin", "elf", "bear"} <= set(offered["creature_types"])
    assert "Unnatural Selection: A chooses a creature type other than Wall" in game.log

    assert game.confirm_creature_type_choice(0, "Wall") is False
    assert game.confirm_creature_type_choice(0, "forest") is False
    assert game.confirm_creature_type_choice(0, "sorcery") is False
    assert _w1g7_computed_types(bears)[1] == {"bear"}
    assert game.waiting_prompt() is not None

    assert game.confirm_creature_type_choice(0, "elf") is True
    assert _w1g7_computed_types(bears)[1] == {"elf"}


def test_unnatural_selection_takes_wall_off_a_wall(set_pool, catalog_by_name):
    """The other half of "other than Wall": a Wall can be *made* something
    else. The set replaces its creature types, so it is no longer a Wall."""
    game, (p0, p1) = _w1g7_enchantment_game()
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Unnatural Selection"])
    wall = _w1g7_enchantment_put(game, 1, catalog_by_name["Wall of Wood"])
    game.queue_permanent_ability(
        0, "Unnatural Selection", target_permanent_ids=[wall.permanent_id]
    )
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_creature_type_choice(0, "elf")

    assert not wall.has_type("wall") and wall.has_type("elf")


def test_unnatural_selection_leaves_the_other_subtypes_alone(set_pool, catalog_by_name):
    """CR 205.1a: a subtype set replaces "any existing subtypes **from the
    appropriate set**" — the creature types. A Forest that Living Lands has made
    a creature, made an Elf, is still a Forest and still a land."""
    game, (p0, p1) = _w1g7_enchantment_game()
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Unnatural Selection"])
    forest = _w1g7_enchantment_put(game, 0, catalog_by_name["Forest"])
    _w1g7_enchantment_put(game, 0, catalog_by_name["Living Lands"])
    game._recompute_continuous_effects()
    assert forest.is_creature and forest.has_type("forest")

    assert game.queue_permanent_ability(
        0, "Unnatural Selection", target_permanent_ids=[forest.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_creature_type_choice(0, "elf")

    assert forest.has_type("elf")
    assert forest.has_type("forest") and forest.has_type("land")
    assert forest.basic_land_types == ("forest",)


def test_unnatural_selection_for_a_seat_nobody_asks_names_a_type_on_the_board(
    set_pool, catalog_by_name
):
    """The default: a creature type that is on the battlefield and is not the
    excluded one, so the ability does what it says rather than nothing."""
    game, (p0, p1) = _w1g7_enchantment_game(interactive=())
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Unnatural Selection"])
    _w1g7_enchantment_put(game, 0, catalog_by_name["Grizzly Bears"])
    wall = _w1g7_enchantment_put(game, 1, catalog_by_name["Wall of Wood"])

    assert game.activate_permanent_ability(
        0, "Unnatural Selection", target_permanent_ids=[wall.permanent_id]
    ).supported

    assert _w1g7_computed_types(wall)[1] == {"bear"}


def test_that_type_needs_a_chosen_type_a_creature_and_a_window():
    """The production reads "becomes that type"; the lowering admits it only
    where the words name something and a sweep ends it."""
    for line, reason in (
        ("Target creature becomes that type until end of turn.", "no step of this effect chose"),
        ("Choose a creature type. Target creature becomes that type.", "no sweep ends"),
        ("Choose a creature type other than Wall. Target permanent becomes that "
         "type until end of turn.", "set on a creature"),
    ):
        refused = _w1g7_compile_line(line)
        assert refused.parsed and not refused.usable
        assert reason in refused.lowering_error

    # "Other than" a word that is no creature type is a sentence nobody read.
    assert not _w1g7_compile_line(
        "Choose a creature type other than Island. Target creature becomes "
        "that type until end of turn."
    ).parsed


# -- Ice Cave ----------------------------------------------------------------


def test_ice_cave_lets_another_player_pay_the_spells_mana_cost_to_counter_it(
    set_pool, catalog_by_name
):
    """"Whenever a player casts a spell, any other player may pay that spell's
    mana cost. If a player does, counter the spell. (Mana cost includes
    color.)" The Bolt costs {R}: the Mountain is tapped, the Island is not,
    and the Bolt is in a graveyard having dealt nothing."""
    game, (p0, p1) = _w1g7_enchantment_game(interactive=(0, 1))
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Ice Cave"])
    mountain = _w1g7_enchantment_put(game, 0, catalog_by_name["Mountain"])
    island = _w1g7_enchantment_put(game, 0, catalog_by_name["Island"])
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    _w1g7_cast_for_free(game, 1, "Lightning Bolt", target_player_index=0)

    # CR 603.3: the trigger is a stack object above the spell it is about.
    assert [item.card.name for item in game.stack] == ["Lightning Bolt", "Ice Cave"]
    game.resolve_top_of_stack(pause_for_choices=True)

    asked = _w1g7_enchantment_prompt(game, 0, "optional_pay")["pending"][0]
    assert asked["cost"] == {"R": 1}
    assert asked["prompt"] == "Pay {R} (Lightning Bolt's mana cost)?"
    # "Any **other** player": the Bolt's own caster is not asked.
    assert _w1g7_enchantment_prompt(game, 1, "optional_pay") is None

    assert game.confirm_optional_pay(0, accept=True) is True

    assert (mountain.tapped, island.tapped) == (True, False)
    assert [card.name for card in p1.graveyard] == ["Lightning Bolt"]
    assert game.stack == [] and p0.life == 20
    assert "Lightning Bolt was countered by Ice Cave and moved to graveyard" in game.log


def test_ice_caves_price_includes_color(set_pool, catalog_by_name):
    """Two Islands cannot pay {R}: saying yes buys nothing, taps nothing, and
    the Bolt resolves."""
    game, (p0, p1) = _w1g7_enchantment_game(interactive=(0, 1))
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Ice Cave"])
    islands = [_w1g7_enchantment_put(game, 0, catalog_by_name["Island"]) for _ in range(2)]
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    _w1g7_cast_for_free(game, 1, "Lightning Bolt", target_player_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.confirm_optional_pay(0, accept=True) is True
    game.enforce_mana_costs = False
    _w1g7_resolve_stack(game)

    assert [land.tapped for land in islands] == [False, False]
    assert p0.life == 17


def test_ice_cave_offers_its_controllers_own_spell_to_the_opponent(
    set_pool, catalog_by_name
):
    """The Cave is symmetrical: "other" is measured from the player who cast
    the spell, so when its controller casts, the opponent is the one asked —
    and a decline lets the spell resolve."""
    game, (p0, p1) = _w1g7_enchantment_game(interactive=(0, 1))
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Ice Cave"])
    mountain = _w1g7_enchantment_put(game, 1, catalog_by_name["Mountain"])
    p0.hand = [catalog_by_name["Lightning Bolt"]]
    _w1g7_cast_for_free(game, 0, "Lightning Bolt", target_player_index=1)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_enchantment_prompt(game, 0, "optional_pay") is None
    assert _w1g7_enchantment_prompt(game, 1, "optional_pay") is not None
    assert game.confirm_optional_pay(1, accept=False) is True
    game.enforce_mana_costs = False
    _w1g7_resolve_stack(game)

    assert p1.life == 17 and mountain.tapped is False


def test_ice_cave_charges_the_announced_x(set_pool, catalog_by_name):
    """CR 107.3h: "If an effect instructs a player to pay an object's mana cost
    that includes {X} … [and] the object is a spell on the stack … the value of
    X is the value chosen or determined for it as the spell was cast." A
    Fireball cast for X=3 costs {3}{R} to counter."""
    game, (p0, p1) = _w1g7_enchantment_game(interactive=(0, 1))
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Ice Cave"])
    lands = [
        _w1g7_enchantment_put(game, 0, catalog_by_name[name])
        for name in ("Mountain", "Island", "Island", "Island")
    ]
    p1.hand = [catalog_by_name["Fireball"]]
    fireball = _w1g7_cast_for_free(game, 1, "Fireball", target_player_index=0, x_value=3)
    assert _w1g7_spell_mana_cost(fireball) == {"R": 1, "generic": 3}
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_enchantment_prompt(game, 0, "optional_pay")["pending"][0]["prompt"] == (
        "Pay {3}{R} (Fireball's mana cost)?"
    )
    assert game.confirm_optional_pay(0, accept=True) is True

    assert all(land.tapped for land in lands)
    assert [card.name for card in p1.graveyard] == ["Fireball"] and p0.life == 20


def test_ice_cave_counters_a_free_spell_for_free(set_pool, catalog_by_name):
    """{0} is a mana cost, and one every player can pay (CR 118.6 is about a
    spell with *no* mana cost): the offer is "Pay {0}?" and taking it counters
    the Ornithopter."""
    game, (p0, p1) = _w1g7_enchantment_game(interactive=(0, 1))
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Ice Cave"])
    p1.hand = [catalog_by_name["Ornithopter"]]
    _w1g7_cast_for_free(game, 1, "Ornithopter")
    game.resolve_top_of_stack(pause_for_choices=True)

    asked = _w1g7_enchantment_prompt(game, 0, "optional_pay")["pending"][0]
    assert asked["prompt"] == "Pay {0} (Ornithopter's mana cost)?"
    assert game.confirm_optional_pay(0, accept=True) is True

    assert [card.name for card in p1.graveyard] == ["Ornithopter"]
    assert [perm.card.name for perm in p1.battlefield] == []


def test_ice_cave_asks_each_other_player_in_turn_and_one_payment_ends_it(
    set_pool, catalog_by_name
):
    """Three seats (CR 101.4): the two players who did not cast are asked in
    turn order, one at a time; the first declines, the second pays, and nobody
    is asked again — one spell is countered once."""
    game, (p0, p1, p2) = _w1g7_enchantment_game(seats=3, interactive=(0, 1, 2))
    _w1g7_enchantment_put(game, 2, set_pool("APC")["Ice Cave"])
    b_land = _w1g7_enchantment_put(game, 1, catalog_by_name["Mountain"])
    c_land = _w1g7_enchantment_put(game, 2, catalog_by_name["Mountain"])
    game.active_player_index = 0
    p0.hand = [catalog_by_name["Lightning Bolt"]]
    _w1g7_cast_for_free(game, 0, "Lightning Bolt", target_player_index=1)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert [choice.player_index for choice in game.pending_choices] == [1]
    assert game.confirm_optional_pay(1, accept=False) is True
    assert [choice.player_index for choice in game.pending_choices] == [2]
    assert game.confirm_optional_pay(2, accept=True) is True

    assert game.pending_choices == [] and game.stack == []
    assert (b_land.tapped, c_land.tapped) == (False, True)
    assert p1.life == 20


@_w1g7_pytest.mark.parametrize(
    "cave_seat, active_seat, payer_lands, payer_hand, countered",
    [
        # Its own Cave, the opponent's turn: the lands are idle, so it pays.
        (0, 1, ("Mountain",), (), True),
        # Somebody else's Cave: the offer is the same gift, and it pays.
        (1, 1, ("Mountain",), (), True),
        # Its own turn with nothing to spend the land on: pays.
        (0, 0, ("Mountain",), (), True),
        # Its own turn with a spell in hand that land could cast: keeps it.
        (0, 0, ("Mountain",), ("Lightning Bolt",), False),
        # "Mana cost includes color": an Island cannot pay {R}.
        (0, 1, ("Island",), (), False),
    ],
)
def test_ice_caves_offer_as_a_seat_nobody_asks_answers_it(
    set_pool, catalog_by_name, cave_seat, active_seat, payer_lands, payer_hand,
    countered,
):
    """The stated policy for a seat nobody asks: the payment buys the payer an
    opponent's spell countered — a gift at a price, whoever's Cave it is — so
    it is paid from floating mana, or from lands that are idle (another seat's
    turn) or that nothing in the hand could use."""
    # Seat 0 is the seat nobody asks; seat 1 is the human who casts.
    game, (p0, p1) = _w1g7_enchantment_game(interactive=(1,))
    _w1g7_enchantment_put(game, cave_seat, set_pool("APC")["Ice Cave"])
    lands = [_w1g7_enchantment_put(game, 0, catalog_by_name[name]) for name in payer_lands]
    game.active_player_index = active_seat
    p0.hand = [catalog_by_name[name] for name in payer_hand]
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    _w1g7_cast_for_free(game, 1, "Lightning Bolt", target_player_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)

    game.auto_resolve_pending_choices(only_player_index=0)
    game.enforce_mana_costs = False
    _w1g7_resolve_stack(game)

    assert p0.life == (20 if countered else 17)
    assert [land.tapped for land in lands] == [countered] * len(lands)


def test_an_ice_cave_answer_that_arrives_after_the_spell_charges_nothing(
    set_pool, catalog_by_name
):
    """A table with nobody to wait for resolves the stack and drains its
    prompts afterwards, so this offer can be answered with the spell already
    gone. Paying then would buy a counter of nothing: the offer is one no
    player may take any more (CR 118.6), and the Mountain stays untapped."""
    game, (p0, p1) = _w1g7_enchantment_game(interactive=())
    _w1g7_enchantment_put(game, 0, set_pool("APC")["Ice Cave"])
    mountain = _w1g7_enchantment_put(game, 0, catalog_by_name["Mountain"])
    game.active_player_index = 1
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    _w1g7_cast_for_free(game, 1, "Lightning Bolt", target_player_index=0)

    game._settle()
    assert p0.life == 17
    game.auto_resolve_pending_choices()

    assert mountain.tapped is False and game.pending_choices == []


def test_a_spell_with_no_mana_cost_cannot_be_paid_for(catalog_by_name):
    """``spell_mana_cost``: None is "unpayable" (CR 118.6, CR 202.1b), never
    "free" — the two must not be confused, because an empty cost is one every
    player can pay."""
    from engine.game_types import StackItem

    def cost_of(card, x_value=None):
        return _w1g7_spell_mana_cost(StackItem(
            card=card, caster_index=0, target_player_index=None,
            target_permanent_index=None, x_value=x_value,
        ))

    assert cost_of(catalog_by_name["Ornithopter"]) == {}
    assert cost_of(catalog_by_name["Forest"]) is None
    assert cost_of(catalog_by_name["Counterspell"]) == {"U": 2}
    assert cost_of(catalog_by_name["Fireball"], x_value=0) == {"R": 1}
    assert cost_of(catalog_by_name["Fireball"], x_value=5) == {"R": 1, "generic": 5}


def test_any_other_player_and_that_spells_mana_cost_refuse_without_their_event():
    """The lowering's gates. "Any other player" is measured from the seat a
    cast (or any seat-freezing) event recorded, and "that spell's mana cost" is
    read off the spell a cast trigger recorded — outside those, each would be
    an offer to the wrong table or a price of nothing."""
    no_event = _w1g7_compile_line(
        "Any other player may pay that spell's mana cost. If a player does, "
        "counter the spell."
    )
    assert no_event.parsed and not no_event.usable
    assert "any other player" in no_event.lowering_error

    not_a_cast = _w1g7_compile_line(
        "At the beginning of your upkeep, any other player may pay {2}. If a "
        "player does, draw a card."
    )
    assert not not_a_cast.usable

    printed_price = _w1g7_compile_line(
        "Whenever a player casts a spell, any other player may pay {2}. If a "
        "player does, counter the spell."
    )
    assert printed_price.usable
    assert printed_price.instructions[0].payload["cost"] == {"generic": 2}

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
