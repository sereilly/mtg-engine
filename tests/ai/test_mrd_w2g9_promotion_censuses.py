"""Mirrodin's promotion: four sampled censuses swept whole for the first time
with its cards shipped, and what each found (MRD W2G9).

* **Irradiate** ("Target creature gets -1/-1 until end of turn for each
  artifact you control") was an own goal on the idle-cast census's mirror
  board: its sign rides inside the amount (``{"times_x": -1}``, the shape
  "for each" and "-X" both lower to), ``ai_target_sides._pt_delta_sign`` did
  not read it, and the shrink fell through to the ``pump`` category's "you".
  Chill Haunting's "-X/-X" is the same shape and was aimed the same way.
* **Wail of the Nim** entwined from the hand and cast one bullet from an
  opened graveyard (the zone-cast census): every single mode carries the
  bonus a cast under a permission that ends is worth
  (``ai_cast_score.zone_cast_bonus``) and the entwined cast did not, and the
  entwined cast was priced outside the permission (a waived mana cost was
  planned as owed).
* **Solar Tide** and **Promise of Power** were refused in the optional-cost
  test, whose executor forwarded seven fields of the announcement by hand and
  dropped the mode list; every executor that plays a game sends
  ``ai_actions.cast_announcement``, which the engine takes.
* **Awe Strike** held on the combat-trick census's wall board is a reviewed
  row there (``HELD``), not a defect: its side is the opponent's.

Each is pinned into its census's sample as well; these are the quick pass's
reading of the same four decisions.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_casts import _cast_candidate
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.ai_target_sides import _pt_delta_sign, spell_target_side
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


def _table(cards, hand, mine, theirs, *, graveyard=(), pool=8) -> Game:
    me = PlayerState(
        name="Me", hand=[cards[name] for name in hand],
        battlefield=[_nosick(Permanent(card=cards[name])) for name in mine],
        graveyard=[cards[name] for name in graveyard],
        library=[cards["Forest"]] * 10,
    )
    you = PlayerState(
        name="You",
        battlefield=[_nosick(Permanent(card=cards[name])) for name in theirs],
        library=[cards["Forest"]] * 10,
    )
    game = Game(players=[me, you], enforce_mana_costs=True)
    game.interactive_seats = set()
    game._sync_control()
    game.turn = 5
    game.begin_turn_bookkeeping(0)
    game._enter_main_phase(precombat=True)
    me.mana_pool.update({symbol: pool for symbol in "WUBRG"})
    return game


def _execute(game: Game, action):
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    return result


def _bears(game: Game, seat: int) -> list:
    return [p for p in game.controlled_by(seat) if p.card.name == "Grizzly Bears"]


# --- a shrink whose sign rides in its amount ----------------------------------


def test_a_counted_or_variable_shrink_is_aimed_across_the_table(catalog_by_name):
    """The side, read off the payload's own sign — and a trade that raises one
    half by X and lowers the other by X stays a trade."""
    assert spell_target_side(catalog_by_name["Irradiate"]) == "opponent"
    assert spell_target_side(catalog_by_name["Chill Haunting"]) == "opponent"
    # "+1/+1 for each …" and "+X/+0" are gifts, as the category said.
    for name in ("Gaea's Might", "Hatred"):
        (step,) = compile_card_oracle(catalog_by_name[name]).instructions
        assert _pt_delta_sign(step) == 1, name
    # "{X}, {T}: Target creature gets -X/+X until end of turn."
    (armor,) = [
        ability.instruction
        for ability in compile_card_oracle(catalog_by_name["Belbe's Armor"]).activated_abilities
    ]
    assert _pt_delta_sign(armor) == 0


def test_irradiate_kills_the_opposing_twin_not_the_casters_own(catalog_by_name):
    """The census's own goal, on a board of twins: two artifacts make it
    -2/-2, which kills a Grizzly Bears on either side."""
    game = _table(
        catalog_by_name, ["Irradiate"],
        mine=["Grizzly Bears", "Sol Ring", "Mox Pearl"],
        theirs=["Grizzly Bears", "Sol Ring", "Mox Pearl"],
    )
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Irradiate"
    (named,) = action.target_permanent_ids
    assert game.controller_index_of(game.permanent_by_id(named)) == 1

    assert _execute(game, action).supported
    assert len(_bears(game, 0)) == 1
    assert _bears(game, 1) == []
    assert "Grizzly Bears" in [card.name for card in game.players[1].graveyard]


def test_chill_haunting_shrinks_an_opposing_creature(catalog_by_name):
    """The same sign on a negated variable: "-X/-X", X the creature cards
    exiled from its caster's graveyard as it is cast."""
    game = _table(
        catalog_by_name, ["Chill Haunting"],
        mine=["Grizzly Bears"], theirs=["Grizzly Bears"],
        graveyard=["Hill Giant", "Craw Wurm"],
    )
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Chill Haunting"
    (named,) = action.target_permanent_ids
    assert game.controller_index_of(game.permanent_by_id(named)) == 1

    assert _execute(game, action).supported
    assert len(_bears(game, 0)) == 1
    assert _bears(game, 1) == []


# --- an entwined cast out of a zone a permission opened -----------------------


def test_wail_of_the_nim_is_entwined_from_an_opened_graveyard_as_from_hand():
    """The zone-cast census's row: the same announcement both ways — every
    mode, the entwine paid — and the cast out of the graveyard accepted."""
    from tests.regressions import test_ody_w2g2_zone_cast_census as zone

    wail = zone.BY_NAME["Wail of the Nim"]
    hand = zone.rig(wail, None, floating=zone.FLOATING)
    from_hand = zone.proposal(hand, wail)
    opened = zone.rig(wail, "graveyard_open", floating=zone.FLOATING)
    from_yard = zone.proposal(opened, wail)

    assert from_hand is not None and from_yard is not None
    assert from_yard.from_zone == "graveyard"
    assert [entry["index"] for entry in from_yard.mode_choices] == [0, 1]
    assert zone.announced(opened, from_yard) == zone.announced(hand, from_hand)
    assert from_yard.score > from_hand.score  # the permission ends this turn

    assert zone.execute(opened, from_yard).supported
    assert "Wail of the Nim cast from AI's graveyard" in opened.log
    assert any("regeneration shield" in line for line in opened.log)
    assert "Wail of the Nim dealt 1 damage to each creature and each player" in opened.log


def test_an_entwine_under_a_waiver_is_planned_as_the_entwine_alone():
    """"…you may play that card without paying its mana cost": the cast is
    charged its entwine and nothing else (CR 118.9, 601.2f), so three Swamps
    pay it. Priced outside the permission, the entwined cast was planned at
    {2}{B} plus {B} and never made."""
    from tests.regressions import test_ody_w2g2_zone_cast_census as zone

    wail = zone.BY_NAME["Wail of the Nim"]
    game = zone.rig(wail, "library_top_free", lands=["Swamp"] * 3)
    action = zone.proposal(game, wail)

    assert action is not None and action.from_zone == "library"
    assert action.mode_choices and action.optional_cost_payments == {"{B}": 1}
    assert len(action.land_tap_indices) == 1
    assert zone.execute(game, action).supported
    assert zone._floating(game) == 0
    assert "Wail of the Nim dealt 1 damage to each creature and each player" in game.log


# --- an entwined cast as every executor makes it -------------------------------


def _offer_table(cards, name) -> Game:
    """The optional-cost test's board (``test_ai_optional_costs``)."""
    lands = ["Plains", "Island", "Swamp", "Mountain", "Forest"] * 3
    me = PlayerState(
        name="Me", hand=[cards[name]],
        battlefield=[Permanent(card=cards[n]) for n in (*lands, "Grizzly Bears", "Hill Giant")],
        library=[cards["Forest"]] * 10, graveyard=[cards["Grizzly Bears"]],
    )
    you = PlayerState(
        name="You",
        battlefield=[Permanent(card=cards[n]) for n in (
            "Grizzly Bears", "Sol Ring", "Mox Pearl", "Mox Jet", "Castle",
            "Serra Angel", "Forest", "Hill Giant",
        )],
        library=[cards["Forest"]] * 10, graveyard=[cards["Grizzly Bears"]],
    )
    game = Game(players=[me, you], enforce_mana_costs=True)
    game._sync_control()
    game.turn = 5
    game.begin_turn_bookkeeping(0)
    game._enter_main_phase(precombat=True)
    return game


def test_solar_tide_entwined_is_taken_and_resolves_both_modes(catalog_by_name):
    game = _offer_table(catalog_by_name, "Solar Tide")
    action = _cast_candidate(game, 0, catalog_by_name["Solar Tide"], 0)
    assert action is not None
    assert action.optional_cost_payments == {"sacrifice two lands": 1}
    assert [entry["index"] for entry in action.mode_choices] == [0, 1]

    assert _execute(game, action).supported
    assert not any(p.is_creature for p in game.all_permanents())
    assert sum(1 for line in game.log if "to cast Solar Tide" in line) == 2


def test_promise_of_power_entwined_is_taken_and_resolves_both_modes(catalog_by_name):
    game = _offer_table(catalog_by_name, "Promise of Power")
    action = _cast_candidate(game, 0, catalog_by_name["Promise of Power"], 0)
    assert action is not None and action.optional_cost_payments == {"{4}": 1}
    assert [entry["index"] for entry in action.mode_choices] == [0, 1]

    assert _execute(game, action).supported
    assert game.players[0].life == 15
    demons = [p for p in game.controlled_by(0) if "Demon" in p.card.type_line]
    assert len(demons) == 1
    # X is the cards in hand as the token enters: the five just drawn.
    assert demons[0].effective_power == len(game.players[0].hand) == 5


def test_an_entwined_cast_that_drops_its_mode_list_is_still_refused(catalog_by_name):
    """Why the optional-cost test's executor was the defect: the engine will
    not spread a cast-level seat over several modes (CR 601.2c), and every
    executor that plays a game sends the list."""
    game = _offer_table(catalog_by_name, "Solar Tide")
    action = _cast_candidate(game, 0, catalog_by_name["Solar Tide"], 0)
    said = {**cast_announcement(action), "mode_choices": None}
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, "Solar Tide", **said)
    assert not result.supported
    assert "names each mode's targets on that mode" in result.details
