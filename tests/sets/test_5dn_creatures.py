"""Fifth Dawn creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
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
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.ai_policy import choose_cast_action as _w1g2_choose_cast_action
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle

_W1G2_BRINGERS = (
    "Bringer of the White Dawn", "Bringer of the Blue Dawn",
    "Bringer of the Black Dawn", "Bringer of the Red Dawn",
    "Bringer of the Green Dawn",
)
_W1G2_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _w1g2_table(set_pool, *, hand=(), mine=(), theirs=(), graveyard=(),
                library=None, interactive=(), mana=True, start=True):
    """Two seats; *mine* / *theirs* placed (not summoning sick) before seat
    0's turn begins, so an upkeep trigger among them fires as it does."""
    lea = set_pool("LEA")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            name="Alice", hand=list(hand), graveyard=list(graveyard),
            library=list(library) if library is not None else [lea["Island"]] * 12,
        ),
        _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 12),
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set(interactive)
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _W1G2Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    if start:
        game.start_turn(0)
        _w1g2_settle(game)
    return game


def _w1g2_basics(set_pool, names=_W1G2_BASICS):
    lea = set_pool("LEA")
    return [lea[name] for name in names]


def _w1g2_tap_lands(game, seat=0):
    """Tap every untapped land *seat* controls for its one colour, by id."""
    for permanent in list(game.controlled_by(seat)):
        if permanent.has_type("land") and not permanent.tapped:
            refused = game.tap_land_for_mana_or_refusal(
                seat, permanent.card.name, permanent_id=permanent.permanent_id,
            )
            assert refused is None, refused


def _w1g2_names(game, seat):
    return [permanent.card.name for permanent in game.controlled_by(seat)]


@_w1g2_pytest.mark.parametrize("bringer", _W1G2_BRINGERS)
def test_w1g2_each_bringer_is_cast_for_wubrg_off_five_basic_lands(set_pool, bringer):
    """"You may pay {W}{U}{B}{R}{G} rather than pay this spell's mana cost."
    Five lands, one of each colour, pay a nine-mana creature (CR 118.9): the
    alternative cost is charged by the ordinary cast payment, and nothing of
    the pool is left over."""
    card = set_pool("5DN")[bringer]
    game = _w1g2_table(set_pool, hand=[card], mine=_w1g2_basics(set_pool))
    _w1g2_tap_lands(game)

    result = game.cast_from_hand(0, bringer, alternative_cost=True)

    assert result.supported, result.details
    _w1g2_settle(game)
    assert bringer in _w1g2_names(game, 0)
    assert not any(game.players[0].mana_pool.values())
    assert f"{bringer} cast for its alternative cost (pay {{W}}{{U}}{{B}}{{R}}{{G}})" in game.log


def test_w1g2_a_bringer_announced_plainly_pays_its_mana_cost(set_pool):
    """CR 118.9b: the alternative cost is optional and never taken by
    default — WUBRG floating does not pay {7}{G}{G}, and the spell stays in
    hand; nine lands do pay it the ordinary way."""
    green = set_pool("5DN")["Bringer of the Green Dawn"]
    game = _w1g2_table(set_pool, hand=[green], mine=_w1g2_basics(set_pool))
    _w1g2_tap_lands(game)

    refused = game.cast_from_hand(0, "Bringer of the Green Dawn")

    assert not refused.supported
    assert "insufficient mana" in refused.details
    assert [held.name for held in game.players[0].hand] == ["Bringer of the Green Dawn"]

    lands = _w1g2_basics(set_pool, ("Forest",) * 9)
    game = _w1g2_table(set_pool, hand=[green], mine=lands)
    _w1g2_tap_lands(game)
    assert game.cast_from_hand(0, "Bringer of the Green Dawn").supported
    assert "Bringer of the Green Dawn" in _w1g2_names(game, 0)


def test_w1g2_wubrg_missing_a_colour_is_refused_before_anything_moves(set_pool):
    """CR 601.2h: an alternative cost the pool cannot pay makes the spell
    uncastable, never cheaper — two Islands and no Forest do not pay WUBRG,
    and the card stays in hand with the mana still floating."""
    blue = set_pool("5DN")["Bringer of the Blue Dawn"]
    lands = _w1g2_basics(set_pool, ("Plains", "Island", "Swamp", "Mountain", "Island"))
    game = _w1g2_table(set_pool, hand=[blue], mine=lands)
    _w1g2_tap_lands(game)

    result = game.cast_from_hand(0, "Bringer of the Blue Dawn", alternative_cost=True)

    assert not result.supported
    assert [held.name for held in game.players[0].hand] == ["Bringer of the Blue Dawn"]
    assert sum(game.players[0].mana_pool.values()) == 5


def test_w1g2_the_offer_is_priced_in_mana_on_the_wire(set_pool):
    """The picker's offer (``cast_cost_offers``) names the price and what it
    owes, so a client can show "pay {W}{U}{B}{R}{G}" beside the mana cost."""
    red = set_pool("5DN")["Bringer of the Red Dawn"]
    game = _w1g2_table(set_pool, hand=[red], mine=_w1g2_basics(set_pool))

    (offer,) = game.cast_cost_offers(0, red, spell_hand_index=0)

    assert offer["kind"] == "alternative"
    assert offer["label"] == "pay {W}{U}{B}{R}{G}"
    assert offer["mana_owed"] == "{W}{U}{B}{R}{G}"
    assert offer["payable"] is True


def test_w1g2_the_ai_casts_a_bringer_for_wubrg_when_only_that_is_payable(set_pool):
    """Five lands of five colours: the mana cost is out of reach and the AI
    announces the alternative cost, tapping all five."""
    blue = set_pool("5DN")["Bringer of the Blue Dawn"]
    game = _w1g2_table(set_pool, hand=[blue], mine=_w1g2_basics(set_pool))

    action = _w1g2_choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Bringer of the Blue Dawn"
    assert action.alternative_cost
    assert len(action.land_tap_indices) == 5


def test_w1g2_the_ai_pays_wubrg_over_nine_mana_and_keeps_four_lands(set_pool):
    """Nine lands, both prices payable: {W}{U}{B}{R}{G} is the same resource
    as {7}{U}{U}, fewer of it, so the AI announces it (CR 118.9b leaves the
    choice to the caster) and the four lands it keeps are the turn's next
    spell — the Grizzly Bears behind it."""
    blue = set_pool("5DN")["Bringer of the Blue Dawn"]
    bears = set_pool("LEA")["Grizzly Bears"]
    lands = _w1g2_basics(set_pool, _W1G2_BASICS + ("Forest",) * 4)
    game = _w1g2_table(set_pool, hand=[blue, bears], mine=lands)

    action = _w1g2_choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Bringer of the Blue Dawn"
    assert action.alternative_cost
    assert len(action.land_tap_indices) == 5


def test_w1g2_blue_dawn_draws_two_at_upkeep_only_if_its_controller_says_so(set_pool):
    """"At the beginning of your upkeep, you may draw two cards." Accepted, two
    cards; declined by an interactive seat, none (and the turn's draw is
    skipped on the first turn, CR 103.8a)."""
    blue = set_pool("5DN")["Bringer of the Blue Dawn"]
    game = _w1g2_table(set_pool, mine=[blue], mana=False)
    assert len(game.players[0].hand) == 2
    assert "Alice drew 2 card(s) (Bringer of the Blue Dawn)" in game.log

    game = _w1g2_table(set_pool, mine=[blue], mana=False, interactive=(0,), start=False)
    game.start_turn(0)
    _w1g2_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=False),
    })
    assert game.players[0].hand == []


def test_w1g2_green_dawn_makes_a_three_three_green_beast_at_upkeep(set_pool):
    """"…you may create a 3/3 green Beast creature token.\""""
    green = set_pool("5DN")["Bringer of the Green Dawn"]
    game = _w1g2_table(set_pool, mine=[green], mana=False)

    (beast,) = [p for p in game.controlled_by(0) if p.card.name == "Beast Token"]
    assert (beast.effective_power, beast.effective_toughness) == (3, 3)
    assert beast.is_creature
    assert beast.effective_card.colors == ("G",)
    assert "Bringer of the Green Dawn created a Beast Token" in game.log


def test_w1g2_white_dawn_returns_an_artifact_card_and_never_a_creature_card(set_pool):
    """"…you may return target artifact card from your graveyard to the
    battlefield." The interactive seat is offered the Sol Ring and not the
    Grizzly Bears beside it, and the Ring comes back."""
    lea = set_pool("LEA")
    white = set_pool("5DN")["Bringer of the White Dawn"]
    game = _w1g2_table(
        set_pool, mine=[white], mana=False, interactive=(0,), start=False,
        graveyard=[lea["Grizzly Bears"], lea["Sol Ring"]],
    )
    game.start_turn(0)
    asked = _w1g2_settle(game, defaults=False)

    assert asked is not None and asked.kind == "trigger_target"
    assert "Sol Ring" in str(asked.data["targets"])
    assert "Grizzly Bears" not in str(asked.data["targets"])
    _w1g2_settle(game)
    assert "Sol Ring" in _w1g2_names(game, 0)
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears"]


def test_w1g2_red_dawn_borrows_a_tapped_creature_untapped_and_hasty_for_the_turn(set_pool):
    """"…you may untap target creature and gain control of it until end of
    turn. That creature gains haste until end of turn." Aimed at Bob's tapped
    Grizzly Bears: Alice controls it untapped with haste, and it goes home at
    the turn's cleanup (CR 514.2)."""
    red = set_pool("5DN")["Bringer of the Red Dawn"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game = _w1g2_table(set_pool, mine=[red], theirs=[bears], mana=False,
                       interactive=(0,), start=False)
    (borrowed,) = [p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears"]
    borrowed.tapped = True
    game.start_turn(0)
    _w1g2_settle(game, answers={
        "trigger_target": lambda g, c: g.confirm_trigger_target(
            0, permanent_id=borrowed.permanent_id, seat=1,
        ),
        "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=True),
    })

    assert game.controller_index_of(borrowed) == 0
    assert not borrowed.tapped
    assert game._has_keyword(borrowed, "haste")
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    _w1g2_settle(game)
    assert game.controller_index_of(borrowed) == 1


def test_w1g2_black_dawn_pays_two_life_and_puts_the_card_it_found_on_top(set_pool):
    """"…you may pay 2 life. If you do, search your library for a card, then
    shuffle and put that card on top." Alice finds the Black Lotus from the
    bottom of four cards; after the shuffle it is the top card, and she paid
    2 life for it."""
    lea = set_pool("LEA")
    black = set_pool("5DN")["Bringer of the Black Dawn"]
    library = [lea["Island"], lea["Island"], lea["Island"], lea["Black Lotus"]]
    game = _w1g2_table(set_pool, mine=[black], mana=False, library=library,
                       interactive=(0,), start=False)
    game.start_turn(0)
    asked = _w1g2_settle(game, defaults=False)
    assert asked is not None and asked.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    searched = _w1g2_settle(game, defaults=False)
    assert searched is not None and searched.kind == "search_library", game.log[-4:]
    assert searched.data["destination"] == "library_top"
    lotus = next(
        index for index, entry in enumerate(game.players[0].library)
        if entry.name == "Black Lotus"
    )
    assert game.confirm_search_library(0, lotus)
    _w1g2_settle(game)

    assert game.players[0].life == 18
    assert game.players[0].library[0].name == "Black Lotus"
    assert len(game.players[0].library) == 4
# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================
