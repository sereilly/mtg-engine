"""Planeshift lands.

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
from engine.ai_policy import _land_mana_is_unplannable as _w1g5_ai_unplannable
from engine.ai_policy import _plan_land_taps as _w1g5_ai_tap_plan
from engine.ai_policy import choose_land_drop as _w1g5_choose_land_drop
from engine.ai_simulator import run_ai_simulation as _w1g5_run_ai_simulation
from engine.card_loader import manifest_set_path as _w1g5_manifest_set_path
from engine.land_types import change_land_type as _w1g5_change_land_type
from engine.mana_payment import is_mana_ability as _w1g5_is_mana_ability
from engine.mana_payment import plan_payment as _w1g5_plan_payment
from engine.mana_payment import untapped_mana_lands as _w1g5_payment_lands
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import resolve_stack as _w1g5_resolve_stack

#: The five Lairs and the three colours each prints, in printed order.
_W1G5_LAIRS = (
    ("Crosis's Catacombs", "UBR"),
    ("Darigaaz's Caldera", "BRG"),
    ("Dromar's Cavern", "WUB"),
    ("Rith's Grove", "RGW"),
    ("Treva's Ruins", "GWU"),
)

#: A one-mana creature of each colour out of Alpha: a real spell with one
#: coloured pip and no target, so what pays for it is the whole question.
_W1G5_ONE_DROPS = {
    "W": "Savannah Lions",
    "U": "Merfolk of the Pearl Trident",
    "B": "Will-o'-the-Wisp",
    "R": "Mons's Goblin Raiders",
    "G": "Llanowar Elves",
}


def _w1g5_table(set_pool, *, mine=(), theirs=(), hand=(), interactive=(), costs=False):
    """Seat 0's main phase over a board that is already there: *mine* and
    *theirs* are on the battlefield without having entered (so no entry trigger
    fires for them), *hand* is seat 0's. Names resolve in Planeshift first and
    Alpha second."""
    pls, lea = set_pool("PLS"), set_pool("LEA")

    def card(name):
        return pls[name] if name in pls else lea[name]

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(name)) for name in mine],
        hand=[card(name) for name in hand],
    )
    you = _W1G5PlayerState(
        name="W1G5-B",
        battlefield=[_W1G5Permanent(card=card(name)) for name in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = costs
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    return game  # _w1g5_table


def _w1g5_named(game, seat: int, name: str):
    """The one permanent called *name* under *seat*."""
    (found,) = [p for p in game.controlled_by(seat) if p.card.name == name]
    return found  # _w1g5_named


def _w1g5_floating(game, seat: int = 0) -> dict[str, int]:
    return {
        symbol: amount
        for symbol, amount in game.players[seat].mana_pool.items() if amount
    }  # _w1g5_floating (lands)


@_w1g5_pytest.mark.parametrize("name, colors", _W1G5_LAIRS)
def test_w1g5_a_lair_taps_for_each_of_its_three_colours(set_pool, name, colors):
    """"{T}: Add {U}, {B}, or {R}." A printed choice of **three**: the reader
    of a dual land's "or" stopped at two, so this line refused on its first
    comma and the Lair had no mana ability at all — nothing to activate and an
    unclaimed line, on a card reported supported for its entry trigger.

    One mana of the colour named, each time, without the stack (CR 605.3b) —
    and never a colour the card does not print, whatever is asked for.
    """
    (ability,) = _w1g5_compile(set_pool("PLS")[name]).activated_abilities
    assert ability.supported, ability
    assert _w1g5_is_mana_ability(ability)

    for color in colors:
        game = _w1g5_table(set_pool, mine=[name])
        lair = _w1g5_named(game, 0, name)
        result = game.activate_permanent_ability(
            0, name, permanent_index=game.battlefield_index_of(lair),
            mana_color=color,
        )
        assert result.supported, result
        assert lair.tapped and not game.stack
        assert _w1g5_floating(game) == {color: 1}

    (unprinted, *_rest) = [c for c in "WUBRG" if c not in colors]
    game = _w1g5_table(set_pool, mine=[name])
    lair = _w1g5_named(game, 0, name)
    assert game.tap_land_for_mana(0, name, unprinted, permanent_id=lair.permanent_id)
    made = _w1g5_floating(game)
    assert sum(made.values()) == 1 and set(made) <= set(colors), made


@_w1g5_pytest.mark.parametrize("name, colors", _W1G5_LAIRS)
def test_w1g5_a_lair_pays_for_a_spell_of_each_of_its_colours(set_pool, name, colors):
    """The Rock Hydra test for a land: with costs enforced, a one-mana creature
    of each of the Lair's colours is refused while the Lair is untapped and
    nothing floats, cast once the Lair has been tapped for that colour, and
    the mana is gone afterwards. A creature of a colour the Lair does not make
    stays in hand however the Lair is tapped."""
    for color in colors:
        spell = _W1G5_ONE_DROPS[color]
        game = _w1g5_table(set_pool, mine=[name], hand=[spell], costs=True)
        lair = _w1g5_named(game, 0, name)

        assert not game.cast_from_hand(0, spell).supported, "nothing has paid for it"
        assert game.tap_land_for_mana(0, name, color, permanent_id=lair.permanent_id)
        cast = game.cast_from_hand(0, spell)
        assert cast.supported, cast
        _w1g5_resolve_stack(game)
        assert _w1g5_floating(game) == {}
        assert spell in [p.card.name for p in game.controlled_by(0)]

    (unprinted, *_rest) = [c for c in "WUBRG" if c not in colors]
    spell = _W1G5_ONE_DROPS[unprinted]
    game = _w1g5_table(set_pool, mine=[name], hand=[spell], costs=True)
    lair = _w1g5_named(game, 0, name)
    game.tap_land_for_mana(0, name, unprinted, permanent_id=lair.permanent_id)
    assert not game.cast_from_hand(0, spell).supported
    assert [card.name for card in game.players[0].hand] == [spell]


def test_w1g5_a_lair_counts_as_any_of_its_three_to_both_planners(set_pool):
    """CR 601.2h asks what a player is *able* to pay, so the exact planner has
    to place the Lair on the pip only it can make: {U}{B} over a Swamp and
    Crosis's Catacombs is payable (Swamp for {B}, Lair for {U}), {G}{B} is not.
    The AI's tap plan names the colour it will ask each land for, and asks the
    Lair for the one the Swamp cannot give."""
    game = _w1g5_table(set_pool, mine=["Swamp", "Crosis's Catacombs"], costs=True)
    lands = _w1g5_payment_lands(game.controlled_by(0))
    assert len(lands) == 2

    payable = _w1g5_plan_payment(
        {}, lands, {"U": 1, "B": 1}, produces=game._land_payment_colors
    )
    assert payable is not None and len(payable.tapped) == 2
    assert _w1g5_plan_payment(
        {}, lands, {"G": 1, "B": 1}, produces=game._land_payment_colors
    ) is None
    for color in "UBR":
        assert _w1g5_plan_payment(
            {}, lands[1:], {color: 1}, produces=game._land_payment_colors
        ) is not None, color

    slots, asked = _w1g5_ai_tap_plan(game, game.players[0], {"U": 1, "B": 1})
    by_land = {
        game.permanent_at(0, slot).card.name: color
        for slot, color in zip(slots, asked)
    }
    assert by_land == {"Swamp": "B", "Crosis's Catacombs": "U"}
    assert _w1g5_ai_tap_plan(game, game.players[0], {"G": 1}) is None


def test_w1g5_a_lair_played_as_the_land_drop_returns_a_non_lair_land(set_pool):
    """"When this land enters, sacrifice it unless you return a non-Lair land
    you control to its owner's hand." Played from hand as the turn's land drop
    by an interactive seat: the game waits on the offer, and accepting it asks
    which land. Another **Lair** is not one of the choices ("non-Lair"), and
    neither is the land that is entering; returning nothing is not paying. The
    Island goes to its owner's hand and the Lair stays."""
    game = _w1g5_table(
        set_pool, mine=["Island", "Dromar's Cavern"],
        hand=["Crosis's Catacombs"], interactive={0}, costs=True,
    )
    island = _w1g5_named(game, 0, "Island")
    cavern = _w1g5_named(game, 0, "Dromar's Cavern")

    assert game.cast_from_hand(0, "Crosis's Catacombs").supported
    assert game.pending_choice_of("optional_pay", 0) is not None
    assert game.waiting_prompt() is not None, "the game waits on the offer"
    assert game.confirm_optional_pay(0, accept=True)

    pick = game.pending_choice_of("permanent_set_choice", 0)
    assert [p.card.name for p in game.live_permanent_set_choices(pick)] == ["Island"]
    assert not game.confirm_permanent_set_choice(0, [cavern.permanent_id])
    assert not game.confirm_permanent_set_choice(0, [])
    assert game.confirm_permanent_set_choice(0, [island.permanent_id])

    assert [p.card.name for p in game.controlled_by(0)] == [
        "Dromar's Cavern", "Crosis's Catacombs",
    ]
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert game.players[0].graveyard == []
    assert not game.pending_choices


def test_w1g5_a_lair_is_sacrificed_when_the_price_is_declined_or_unpayable(set_pool):
    """The other three ways the trigger resolves. Declined: sacrificed, the
    Island untouched. No other land at all: sacrificed with nothing asked.
    Only another Lair: the same — "non-Lair" leaves no land to return."""
    declined = _w1g5_table(
        set_pool, mine=["Island"], hand=["Rith's Grove"], interactive={0},
    )
    declined.cast_from_hand(0, "Rith's Grove")
    assert declined.confirm_optional_pay(0, accept=False)
    assert [p.card.name for p in declined.controlled_by(0)] == ["Island"]
    assert [card.name for card in declined.players[0].graveyard] == ["Rith's Grove"]

    alone = _w1g5_table(set_pool, hand=["Rith's Grove"], interactive={0})
    alone.cast_from_hand(0, "Rith's Grove")
    assert not alone.pending_choices, "there is nothing to offer"
    assert list(alone.controlled_by(0)) == []
    assert [card.name for card in alone.players[0].graveyard] == ["Rith's Grove"]

    lairs_only = _w1g5_table(
        set_pool, mine=["Treva's Ruins"], hand=["Rith's Grove"], interactive={0},
    )
    lairs_only.cast_from_hand(0, "Rith's Grove")
    assert not lairs_only.pending_choices
    assert [p.card.name for p in lairs_only.controlled_by(0)] == ["Treva's Ruins"]
    assert [c.name for c in lairs_only.players[0].graveyard] == ["Rith's Grove"]


def test_w1g5_non_lair_is_what_the_land_is_now(set_pool):
    """"Non-Lair" is a land subtype read through the layers (CR 205.3i, CR
    305.7): a Lair whose type an effect has *set* to Swamp is a Swamp and not
    a Lair, so it is a legal land to return — where its printed type line
    still says Lair."""
    game = _w1g5_table(
        set_pool, mine=["Treva's Ruins"], hand=["Rith's Grove"], interactive={0},
    )
    ruins = _w1g5_named(game, 0, "Treva's Ruins")
    _w1g5_change_land_type(ruins, "swamp", source="w1g5-test")
    assert ruins.has_type("swamp") and not ruins.has_type("lair")

    game.cast_from_hand(0, "Rith's Grove")
    assert game.confirm_optional_pay(0, accept=True)
    assert game.confirm_permanent_set_choice(0, [ruins.permanent_id])
    assert [p.card.name for p in game.controlled_by(0)] == ["Rith's Grove"]
    assert [card.name for card in game.players[0].hand] == ["Treva's Ruins"]


def test_w1g5_a_headless_seat_keeps_its_lair(set_pool):
    """The non-interactive seat's default takes the offer and returns a land,
    so an AI or scripted seat is neither blocked nor left sacrificing a Lair
    it could have kept."""
    game = _w1g5_table(set_pool, mine=["Forest"], hand=["Darigaaz's Caldera"])
    assert game.cast_from_hand(0, "Darigaaz's Caldera").supported
    game.auto_resolve_pending_choices()

    assert [p.card.name for p in game.controlled_by(0)] == ["Darigaaz's Caldera"]
    assert [card.name for card in game.players[0].hand] == ["Forest"]
    assert not game.pending_choices


def test_w1g5_the_ai_holds_a_lair_it_would_have_to_sacrifice(set_pool):
    """The land-drop chooser ranked a three-colour land above any basic, which
    on turn one is a Lair played with no land to return: the card and the land
    drop both thrown away. It plays the basic first, and the Lair once there is
    a land to pay with; holding only a Lair, it plays nothing.

    The reading is of the compiled entry trigger, not of a name — Karoo
    (Visions) prints the same sentence about an untapped Plains and is held
    the same way."""
    opening = _w1g5_table(
        set_pool, hand=["Rith's Grove", "Mountain", "Mons's Goblin Raiders"], costs=True,
    )
    drop = _w1g5_choose_land_drop(opening, 0)
    assert drop is not None
    assert opening.players[0].hand[drop.hand_index].name == "Mountain"

    stranded = _w1g5_table(set_pool, hand=["Rith's Grove"], costs=True)
    assert _w1g5_choose_land_drop(stranded, 0) is None

    payable = _w1g5_table(
        set_pool, mine=["Mountain"], hand=["Rith's Grove", "Llanowar Elves"], costs=True,
    )
    drop = _w1g5_choose_land_drop(payable, 0)
    assert drop is not None
    assert payable.players[0].hand[drop.hand_index].name == "Rith's Grove"

    karoo = set_pool("VIS")["Karoo"]
    visions = _w1g5_table(set_pool, mine=["Island"], costs=True)
    visions.players[0].hand.append(karoo)
    assert _w1g5_choose_land_drop(visions, 0) is None, "no Plains to return"
    visions.players[0].battlefield.append(
        _W1G5Permanent(card=set_pool("LEA")["Plains"])
    )
    assert _w1g5_choose_land_drop(visions, 0) is not None


# -- Meteor Crater -----------------------------------------------------------


def _w1g5_crater(set_pool, **board):
    """`_w1g5_table` with a Meteor Crater on seat 0, and the Crater."""
    mine = list(board.pop("mine", ())) + ["Meteor Crater"]
    game = _w1g5_table(set_pool, mine=mine, **board)
    return game, _w1g5_named(game, 0, "Meteor Crater")  # _w1g5_crater


def test_w1g5_meteor_crater_is_a_mana_ability_with_a_narrowed_choice(set_pool):
    """"{T}: Choose a color of a permanent you control. Add one mana of that
    color." Two sentences, one mana ability (CR 605.1a): the choice carries
    the noun phrase as the set whose colours may be named, and the mana reads
    the colour *this* resolution chose."""
    (ability,) = _w1g5_compile(set_pool("PLS")["Meteor Crater"]).activated_abilities
    assert ability.supported and _w1g5_is_mana_ability(ability)
    choose, add = ability.instruction.payload["steps"]
    assert choose.kind == "choose_color"
    assert choose.payload == {"among": {"controller": "you"}}
    assert add.payload == {"color_from": "chosen_color_this_way"}


def test_w1g5_meteor_crater_makes_only_a_colour_its_controller_has(set_pool):
    """One green creature: green, whatever colour is asked for. A red one
    beside it: either, as named. An opponent's permanents offer nothing
    ("you control"), and neither does a board of colourless ones — a land and
    an artifact have no colour (CR 105.2c), so the Crater taps and adds no
    mana. Through both doors to the ability: the activation and the tap seam."""
    def tapped_for(asked, seam, **board):
        game, crater = _w1g5_crater(set_pool, **board)
        if seam == "activate":
            result = game.activate_permanent_ability(
                0, "Meteor Crater",
                permanent_index=game.battlefield_index_of(crater), mana_color=asked,
            )
            assert result.supported, result
        else:
            assert game.tap_land_for_mana(
                0, "Meteor Crater", asked, permanent_id=crater.permanent_id
            )
        assert crater.tapped and not game.stack and not game.pending_choices
        return _w1g5_floating(game)

    for seam in ("activate", "tap"):
        assert tapped_for("G", seam, mine=["Grizzly Bears"]) == {"G": 1}
        assert tapped_for("R", seam, mine=["Grizzly Bears"]) == {"G": 1}
        both = ["Grizzly Bears", "Hill Giant"]
        assert tapped_for("R", seam, mine=both) == {"R": 1}
        assert tapped_for("G", seam, mine=both) == {"G": 1}
        assert tapped_for("R", seam, theirs=["Hill Giant"]) == {}
        assert tapped_for("G", seam, mine=["Forest", "Sol Ring"]) == {}


def test_w1g5_meteor_crater_reads_colour_through_the_layers(set_pool):
    """The colours are the ones the permanents have *now* (CR 105.2, layer 5):
    a Swamp is colourless until Kormus Bell makes every Swamp a black creature,
    and then the Crater beside it makes {B}."""
    game, crater = _w1g5_crater(set_pool, mine=["Swamp"])
    assert game.narrowed_land_mana_colors(crater) == ()

    game, crater = _w1g5_crater(set_pool, mine=["Swamp", "Kormus Bell"])
    assert game.narrowed_land_mana_colors(crater) == ("B",)
    assert game.tap_land_for_mana(0, "Meteor Crater", "B", permanent_id=crater.permanent_id)
    assert _w1g5_floating(game) == {"B": 1}


def test_w1g5_meteor_crater_asks_among_the_colours_on_offer(set_pool):
    """An interactive seat that names a colour its board does not offer has
    not chosen: with two on offer the prompt lists exactly those two, refuses
    a third, and the mana arrives with the answer. Nothing is made until then."""
    game, crater = _w1g5_crater(
        set_pool, mine=["Grizzly Bears", "Hill Giant"], interactive={0},
    )
    result = game.activate_permanent_ability(
        0, "Meteor Crater",
        permanent_index=game.battlefield_index_of(crater), mana_color="U",
    )
    assert result.supported
    prompt = game.pending_choice_of("color_choice", 0)
    assert prompt is not None and prompt.data["colors"] == ["R", "G"]
    assert _w1g5_floating(game) == {}

    assert not game.confirm_color_choice(0, "U")
    assert game.confirm_color_choice(0, "R")
    assert _w1g5_floating(game) == {"R": 1}
    assert not game.pending_choices


def test_w1g5_every_reader_of_what_the_crater_makes_agrees(set_pool):
    """Scryfall summarises the Crater as all five colours. The payment
    planner's hook, the AI's tap plan and the client's picker each read that
    summary, so a Crater beside one green creature was a five-colour land to
    all three. They ask one question now (`Game.narrowed_land_mana_colors`):
    {R} is unpayable and is not planned, {G} is; and on a colourless board the
    Crater is no mana at all rather than a {C} the tap would not make."""
    from web.serialization import _offered_mana

    game, crater = _w1g5_crater(set_pool, mine=["Grizzly Bears"], costs=True)
    lands = _w1g5_payment_lands(game.controlled_by(0))
    assert game._land_payment_colors(crater) == ("G",)
    assert _offered_mana(game, crater) == ("G",)
    assert _w1g5_plan_payment({}, lands, {"R": 1}, produces=game._land_payment_colors) is None
    assert _w1g5_plan_payment({}, lands, {"G": 1}, produces=game._land_payment_colors) is not None
    assert _w1g5_ai_tap_plan(game, game.players[0], {"R": 1}) is None
    slots, asked = _w1g5_ai_tap_plan(game, game.players[0], {"G": 1})
    assert [game.permanent_at(0, slot) for slot in slots] == [crater]
    assert asked == ("G",)

    bare, crater = _w1g5_crater(set_pool, mine=["Sol Ring"], costs=True)
    assert _offered_mana(bare, crater) == ()
    assert _w1g5_ai_unplannable(bare, crater)
    assert _w1g5_ai_tap_plan(bare, bare.players[0], {"generic": 1}) is None


def test_w1g5_meteor_crater_pays_for_a_real_spell(set_pool):
    """With costs enforced: a Hill Giant on the battlefield makes the Crater a
    red source, and it pays for Mons's Goblin Raiders — and not for Llanowar
    Elves, whose green the board does not offer."""
    game, crater = _w1g5_crater(
        set_pool, mine=["Hill Giant"],
        hand=["Mons's Goblin Raiders", "Llanowar Elves"], costs=True,
    )
    assert game.tap_land_for_mana(0, "Meteor Crater", "G", permanent_id=crater.permanent_id)
    assert _w1g5_floating(game) == {"R": 1}
    assert not game.cast_from_hand(0, "Llanowar Elves").supported
    assert game.cast_from_hand(0, "Mons's Goblin Raiders").supported
    _w1g5_resolve_stack(game)
    assert _w1g5_floating(game) == {}


@_w1g5_pytest.mark.slow
def test_w1g5_the_lairs_and_the_crater_in_simulated_games(set_pool):
    """Whole games with a Lair and a Meteor Crater pinned into both decks:
    the land is played as a land drop, its trigger is answered in the step
    that owes it (`steps_left_owing`), a land comes back to hand, and both
    lands are tapped for mana that pays for spells. No seat plays a Lair into
    its own sacrifice, and nothing either card does is an issue."""
    report = _w1g5_run_ai_simulation(
        _w1g5_manifest_set_path("PLS", include_measured=True),
        games=4, seed=515, max_turns=16,
        required_cards=["Rith's Grove", "Meteor Crater"],
    )
    log = report.log_lines

    assert report.games_completed == 4
    assert report.steps_left_owing == {}, dict(report.steps_left_owing)
    assert sum("play Rith's Grove -> resolved" in line for line in log) >= 3
    assert sum("Rith's Grove returned" in line for line in log) >= 3
    assert not [line for line in log if "Rith's Grove was sacrificed" in line]
    assert sum("Rith's Grove produced {" in line for line in log) >= 3
    assert sum("Meteor Crater produced {" in line for line in log) >= 1
    assert not [
        issue.message for issue in report.issues
        if "Rith's Grove" in issue.message or "Meteor Crater" in issue.message
    ]
    assert not [
        why for why in report.refused_casts
        if "Rith's Grove" in why or "Meteor Crater" in why
    ], dict(report.refused_casts)
