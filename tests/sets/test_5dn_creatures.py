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
#
# Sunburst (CR 702.44): every sunburst creature is cast through the real cast
# path with costs enforced, so the counters it enters with are the colours the
# payment measured. The keyword's rules tests are
# tests/rules/test_5dn_w1g1_sunburst.py.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import add_counters as _w1g1_add_counters
from engine.named_counters import counters_on as _w1g1_counters_on
from tests.helpers import declare_attack as _w1g1_declare_attack
from tests.helpers import drive_combat as _w1g1_drive_combat
from tests.helpers import settle as _w1g1_settle


def _w1g1_table(set_pool, *, hand=(), interactive=()):
    """Two seats on seat 0's first main phase, costs enforced."""
    lea = set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g1_settle(game)
    return game


def _w1g1_cast(game, name, pool, **announce):
    """Cast *name* from seat 0's hand with *pool* floating; the permanent,
    past its summoning sickness."""
    game.players[0].mana_pool.update(pool)
    result = game.cast_from_hand(0, name, **announce)
    assert result.supported, (result, game.log[-5:])
    _w1g1_settle(game)
    permanent = next(p for p in game.all_permanents() if p.card.name == name)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g1_put(game, card, seat):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g1_activate(game, name, pool=None, **announce):
    if pool:
        game.players[0].mana_pool.update(pool)
    result = game.activate_permanent_ability(0, name, **announce)
    assert result.supported, (result, game.log[-5:])
    return result


def _w1g1_pt(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_w1g1_suntouched_myr_is_as_big_as_the_colors_spent(set_pool):
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Suntouched Myr"], fdn["Suntouched Myr"]])
    three = _w1g1_cast(game, "Suntouched Myr", {"W": 1, "U": 1, "B": 1})
    assert _w1g1_pt(three) == (3, 3)
    assert any(
        "Suntouched Myr enters with 3 +1/+1 counters" in line for line in game.log
    )
    game.players[0].mana_pool.update({"R": 3})
    assert game.cast_from_hand(0, "Suntouched Myr").supported
    _w1g1_settle(game)
    myrs = sorted(
        _w1g1_counters_on(p, "+1/+1")
        for p in game.all_permanents() if p.card.name == "Suntouched Myr"
    )
    assert myrs == [1, 3]


def test_w1g1_skyreach_manta_five_colors_is_a_five_five_flier(set_pool):
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Skyreach Manta"]])
    manta = _w1g1_cast(game, "Skyreach Manta", {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1})
    assert _w1g1_pt(manta) == (5, 5)
    assert game._has_keyword(manta, "flying")


def test_w1g1_sawtooth_thresher_trades_two_counters_for_four_four(set_pool):
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Sawtooth Thresher"]])
    thresher = _w1g1_cast(game, "Sawtooth Thresher", {"W": 1, "U": 1, "C": 4})
    assert _w1g1_pt(thresher) == (3, 3)
    _w1g1_activate(game, "Sawtooth Thresher")
    _w1g1_settle(game)
    assert _w1g1_counters_on(thresher, "+1/+1") == 0
    assert _w1g1_pt(thresher) == (5, 5)
    game.resolve_cleanup_step(0)
    assert _w1g1_pt(thresher) == (1, 1)


def test_w1g1_etched_oracle_spends_four_counters_to_draw_three(set_pool):
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Etched Oracle"]])
    oracle = _w1g1_cast(game, "Etched Oracle", {"W": 1, "U": 1, "B": 1, "R": 1})
    assert _w1g1_pt(oracle) == (4, 4)
    _w1g1_activate(game, "Etched Oracle", {"C": 1}, target_player_index=0)
    _w1g1_settle(game)
    assert len(game.players[0].hand) == 3
    # A 0/0 once its four counters paid for the draw.
    assert "Etched Oracle" in [card.name for card in game.players[0].graveyard]


def test_w1g1_etched_oracle_with_three_colors_cannot_pay_its_cost(set_pool):
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Etched Oracle"]])
    oracle = _w1g1_cast(game, "Etched Oracle", {"W": 1, "U": 1, "B": 1, "C": 1})
    assert _w1g1_counters_on(oracle, "+1/+1") == 3
    game.players[0].mana_pool.update({"C": 1})
    refused = game.activate_permanent_ability(0, "Etched Oracle", target_player_index=0)
    assert not refused.supported
    assert _w1g1_counters_on(oracle, "+1/+1") == 3


def test_w1g1_lunar_avenger_gains_the_keyword_its_controller_picks(set_pool):
    """The choice is made as the ability resolves (2004-12-01)."""
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Lunar Avenger"]], interactive=(0,))
    avenger = _w1g1_cast(game, "Lunar Avenger", {"W": 1, "U": 1, "B": 1, "C": 4})
    assert _w1g1_pt(avenger) == (5, 5)
    _w1g1_activate(game, "Lunar Avenger")
    owed = _w1g1_settle(game, defaults=False)
    assert owed is not None and owed.kind == "mode_choice"
    assert list(owed.data["labels"]) == ["flying", "first strike", "haste"]
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=2)
    _w1g1_settle(game)
    assert _w1g1_pt(avenger) == (4, 4)
    assert game._has_keyword(avenger, "haste")
    assert not game._has_keyword(avenger, "flying")


def test_w1g1_suncrusher_destroys_and_then_goes_home(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Suncrusher"]])
    giant = _w1g1_put(game, lea["Hill Giant"], 1)
    crusher = _w1g1_cast(
        game, "Suncrusher", {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1, "C": 4},
    )
    assert _w1g1_pt(crusher) == (8, 8)
    _w1g1_activate(
        game, "Suncrusher", {"C": 4}, ability_index=0,
        target_permanent_ids=[giant.permanent_id],
    )
    _w1g1_settle(game)
    assert not game.is_on_battlefield(giant)
    assert crusher.tapped and _w1g1_counters_on(crusher, "+1/+1") == 4
    _w1g1_activate(game, "Suncrusher", {"C": 2}, ability_index=1)
    _w1g1_settle(game)
    assert [card.name for card in game.players[0].hand] == ["Suncrusher"]


def test_w1g1_solarion_s_sunburst_line_is_the_entry_reader_s(set_pool):
    """Solarion's sunburst is this group's; its doubling line is CR 701.10e's
    (W1G7's round). The sunburst line, rewritten, is claimed whole by the
    entry reader the compiler and the entry state share."""
    from engine.enter_effects import (SUNBURST_COUNTER,
                                      enters_with_counters_per_color_spent)
    from engine.line_rewrites import expand_card_lines

    solarion = set_pool("5DN")["Solarion"]
    lines = expand_card_lines(solarion)
    assert enters_with_counters_per_color_spent(lines[0], solarion.name) == SUNBURST_COUNTER
    assert lines[1].startswith("{T}: Double")


def test_w1g1_spinal_parasite_takes_a_charge_counter_off_a_prism(set_pool):
    """Base -1/-1 (the 2004-12-01 ruling): five colours make a 4/4, and two of
    its counters pay to take one off the opponent's Pentad Prism."""
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Spinal Parasite"]])
    prism = _w1g1_put(game, fdn["Pentad Prism"], 1)
    _w1g1_add_counters(prism, "charge", 2)
    parasite = _w1g1_cast(game, "Spinal Parasite", {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1})
    assert _w1g1_pt(parasite) == (4, 4)
    _w1g1_activate(game, "Spinal Parasite", target_permanent_ids=[prism.permanent_id])
    _w1g1_settle(game)
    assert _w1g1_counters_on(prism, "charge") == 1
    assert _w1g1_pt(parasite) == (2, 2)


def test_w1g1_spinal_parasite_s_controller_picks_the_kind_of_counter(set_pool):
    """"The player who controls Spinal Parasite chooses which counter to remove
    from the targeted permanent" (2004-12-01) — asked of seat 0 even though
    the target is seat 1's; a seat nobody asks takes the +1/+1 off an
    opponent's creature first."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    for interactive, pick, left in (((0,), 1, {"+1/+1": 1, "charge": 0}),
                                    ((), None, {"+1/+1": 0, "charge": 1})):
        game = _w1g1_table(set_pool, hand=[fdn["Spinal Parasite"]], interactive=interactive)
        _w1g1_cast(game, "Spinal Parasite", {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1})
        bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
        game.place_pt_counters(bears, "+1/+1", 1)
        _w1g1_add_counters(bears, "charge", 1)
        _w1g1_activate(game, "Spinal Parasite", target_permanent_ids=[bears.permanent_id])
        if pick is not None:
            owed = _w1g1_settle(game, defaults=False)
            assert owed is not None and owed.kind == "mode_choice"
            assert owed.player_index == 0
            assert game.resolve_pending_choice("mode_choice", 0, mode_index=pick)
        _w1g1_settle(game)
        assert {kind: _w1g1_counters_on(bears, kind) for kind in left} == left


def test_w1g1_spinal_parasite_may_target_a_permanent_with_no_counters(set_pool):
    """Any permanent is a legal target (2004-12-01); one with none loses none."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Spinal Parasite"]])
    _w1g1_cast(game, "Spinal Parasite", {"W": 1, "U": 1, "B": 1, "C": 2})
    bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
    _w1g1_activate(game, "Spinal Parasite", target_permanent_ids=[bears.permanent_id])
    _w1g1_settle(game)
    assert any("has no counters to remove" in line for line in game.log)
    assert game.is_on_battlefield(bears)


def test_w1g1_ferropede_takes_a_counter_off_as_it_connects(set_pool):
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool)
    ferropede = _w1g1_put(game, fdn["Ferropede"], 0)
    prism = _w1g1_put(game, fdn["Pentad Prism"], 1)
    _w1g1_add_counters(prism, "charge", 3)
    _w1g1_declare_attack(game, 0)
    assert ferropede.attacking
    _w1g1_drive_combat(game)
    assert game.players[1].life == 19
    assert _w1g1_counters_on(prism, "charge") == 2


def test_w1g1_ferropede_s_target_is_asked_of_a_person(set_pool):
    """The trigger targets as it goes on the stack (CR 603.3d), and a person
    names which permanent — here their own Suntouched Myr is spared and the
    opponent's Prism loses one."""
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, interactive=(0,))
    _w1g1_put(game, fdn["Ferropede"], 0)
    prism = _w1g1_put(game, fdn["Pentad Prism"], 1)
    _w1g1_add_counters(prism, "charge", 2)
    _w1g1_declare_attack(game, 0)
    seen = []

    def pick_prism(game, choice):
        seen.append(choice.kind)
        assert game.resolve_pending_choice(
            choice.kind, 0, permanent_id=prism.permanent_id,
        )

    def accept(game, choice):
        seen.append(choice.kind)
        assert game.resolve_pending_choice(choice.kind, 0, accept=True, option=None)

    _w1g1_drive_combat(
        game, answers={"trigger_target": pick_prism, "optional_pay": accept},
    )
    assert "trigger_target" in seen
    assert _w1g1_counters_on(prism, "charge") == 1


def test_w1g1_arcbound_wanderer_counts_colors_and_passes_them_on(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Arcbound Wanderer"], fdn["Suntouched Myr"], lea["Shatter"]])
    wanderer = _w1g1_cast(game, "Arcbound Wanderer", {"W": 1, "U": 1, "B": 1, "C": 3})
    assert _w1g1_pt(wanderer) == (3, 3)
    myr = _w1g1_cast(game, "Suntouched Myr", {"G": 1, "R": 1, "C": 1})
    assert _w1g1_counters_on(myr, "+1/+1") == 2
    game.players[0].mana_pool.update({"R": 1, "C": 1})
    assert game.cast_from_hand(0, "Shatter", target_permanent_ids=[wanderer.permanent_id]).supported
    _w1g1_settle(game)
    assert not game.is_on_battlefield(wanderer)
    assert _w1g1_counters_on(myr, "+1/+1") == 5

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


def test_w1g2_red_dawn_unasked_borrows_the_opponents_creature_not_its_own(set_pool):
    """A seat nobody asks aims the trigger as the engine's default does
    (``_default_trigger_target_side``): the steal is the point of the
    ability, so it is aimed across the table — Bob's Grizzly Bears, not the
    Bringer itself, which the untap alone read as "you"."""
    red = set_pool("5DN")["Bringer of the Red Dawn"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game = _w1g2_table(set_pool, mine=[red], theirs=[bears], mana=False)

    (borrowed,) = [p for p in game.all_permanents() if p.card.name == "Grizzly Bears"]
    assert game.controller_index_of(borrowed) == 0
    assert "Bringer of the Red Dawn: targets Grizzly Bears" in game.log


def test_w1g2_red_dawn_with_its_target_gone_in_response_steals_and_hastes_nothing(set_pool):
    """The trigger aimed at Bob's Grizzly Bears, and the Bears bolted in
    response: the trigger's one target is illegal and it is removed as it
    resolves (CR 608.2b) — nothing is offered, nothing untapped, the steal
    and the haste rider (both reading the untap's record) touch nothing, and
    the Bringer stays its controller's, untouched."""
    lea = set_pool("LEA")
    red = set_pool("5DN")["Bringer of the Red Dawn"]
    game = _w1g2_table(set_pool, mine=[red], theirs=[lea["Grizzly Bears"]],
                       mana=False, interactive=(0,), start=False)
    (bears,) = [p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears"]
    game.players[1].hand.append(lea["Lightning Bolt"])
    game.start_turn(0)
    asked = _w1g2_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target"
    assert game.confirm_trigger_target(0, permanent_id=bears.permanent_id, seat=1)
    assert game.stack, "the trigger waits on the stack"

    bolt = game.queue_from_hand(1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    assert bolt.supported, bolt.details
    _w1g2_settle(game)

    assert sorted(card.name for card in game.players[1].graveyard) == [
        "Grizzly Bears", "Lightning Bolt",
    ]
    (bringer,) = [p for p in game.all_permanents() if p.card.name == "Bringer of the Red Dawn"]
    assert game.controller_index_of(bringer) == 0
    assert not game._has_keyword(bringer, "haste")
    assert not any("gains control" in line for line in game.log)


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

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_activation_spec as _w1g3_activation_spec
from tests.helpers import settle as _w1g3_settle


def _w1g3_table(set_pool, *, graveyard=(), hand=(), interactive=()):
    """Two seats on seat 0's first main phase, *graveyard* and *hand* seat
    0's, libraries to draw from."""
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g3_settle(game)
    return game


def _w1g3_small_artifact_pile(set_pool):
    """A graveyard where "artifact card with mana value 1 or less" names two
    cards out of five: a four-drop artifact, a creature, the 1-drop, an
    artifact creature at 0, and an {X} artifact (X is 0 off the stack,
    CR 202.3e — Auriok Salvagers' 2020-08-07 ruling)."""
    lea, atq, fdn = set_pool("LEA"), set_pool("ATQ"), set_pool("5DN")
    return [
        lea["Rod of Ruin"], lea["Grizzly Bears"], lea["Sol Ring"],
        atq["Ornithopter"], fdn["Engineered Explosives"],
    ]


def _w1g3_names(cards):
    return [card.name for card in cards]


def test_w1g3_leonin_squire_returns_only_a_small_artifact_card(set_pool):
    """"When this creature enters, return target artifact card with mana value
    1 or less from your graveyard to your hand." A seat nobody asks takes a
    legal card — never the Rod of Ruin first in the pile, which is what the
    unnarrowed artifact return would take."""
    pile = _w1g3_small_artifact_pile(set_pool)
    pile = [pile[0], pile[1], pile[2]]  # Rod of Ruin, Grizzly Bears, Sol Ring
    game = _w1g3_table(
        set_pool, graveyard=pile, hand=[set_pool("5DN")["Leonin Squire"]],
    )
    assert game.cast_from_hand(0, "Leonin Squire").supported
    _w1g3_settle(game)

    alice = game.players[0]
    assert _w1g3_names(alice.hand) == ["Sol Ring"], game.log[-8:]
    assert _w1g3_names(alice.graveyard) == ["Rod of Ruin", "Grizzly Bears"]


def test_w1g3_leonin_squire_offers_the_small_artifacts_and_takes_the_named_one(set_pool):
    """Asked as it goes on the stack (CR 603.3d), the picker lists the three
    artifact cards at mana value 1 or less — the 1-drop, the artifact creature
    at 0 and the {X} artifact — and not the Rod of Ruin or the creature card.
    The one named is the one returned."""
    game = _w1g3_table(
        set_pool, graveyard=_w1g3_small_artifact_pile(set_pool),
        hand=[set_pool("5DN")["Leonin Squire"]], interactive={0},
    )
    assert game.cast_from_hand(0, "Leonin Squire").supported
    choice = _w1g3_settle(game, defaults=False)
    assert choice is not None and choice.kind == "trigger_target", game.log[-6:]
    assert sorted(entry["name"] for entry in choice.data["targets"]) == [
        "Engineered Explosives", "Ornithopter", "Sol Ring",
    ]
    assert game.confirm_trigger_target(0, seat=0, graveyard_index=3)
    _w1g3_settle(game)

    alice = game.players[0]
    assert _w1g3_names(alice.hand) == ["Ornithopter"]
    assert "Rod of Ruin" in _w1g3_names(alice.graveyard)


def test_w1g3_leonin_squire_with_no_small_artifact_returns_nothing(set_pool):
    lea = set_pool("LEA")
    game = _w1g3_table(
        set_pool, graveyard=[lea["Rod of Ruin"], lea["Jayemdae Tome"]],
        hand=[set_pool("5DN")["Leonin Squire"]],
    )
    assert game.cast_from_hand(0, "Leonin Squire").supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert alice.hand == []
    assert _w1g3_names(alice.graveyard) == ["Rod of Ruin", "Jayemdae Tome"]
    assert any(p.card.name == "Leonin Squire" for p in alice.battlefield)


def test_w1g3_auriok_salvagers_picker_and_gate_read_the_mana_value(set_pool):
    """"{1}{W}: Return target artifact card with mana value 1 or less from your
    graveyard to your hand." The activation spec carries the bound, a named
    Rod of Ruin is refused at announcement (CR 602.2b), and a named Sol Ring
    comes back — repeatably, the ability having no tap in its cost."""
    game = _w1g3_table(set_pool, graveyard=_w1g3_small_artifact_pile(set_pool))
    salvagers = set_pool("5DN")["Auriok Salvagers"]
    game._put_permanent_onto_battlefield(0, _W1G3Permanent(card=salvagers), None)
    ability = _w1g3_compile(salvagers).activated_abilities[0]
    spec = _w1g3_activation_spec(ability)
    assert spec["card_type"] == "artifact" and spec["own_graveyard_only"]
    assert spec["graveyard_mana_value"] == {"op": "le", "value": 1}

    refused = game.activate_permanent_ability(
        0, "Auriok Salvagers", target_player_index=0, target_graveyard_indices=[0],
    )
    assert not refused.supported, "a Rod of Ruin is not a legal target"
    assert game.activate_permanent_ability(
        0, "Auriok Salvagers", target_player_index=0, target_graveyard_indices=[2],
    ).supported
    _w1g3_settle(game)
    assert game.activate_permanent_ability(
        0, "Auriok Salvagers", target_player_index=0, target_graveyard_indices=[3],
    ).supported
    _w1g3_settle(game)

    alice = game.players[0]
    assert sorted(_w1g3_names(alice.hand)) == ["Engineered Explosives", "Sol Ring"]
    assert _w1g3_names(alice.graveyard) == ["Rod of Ruin", "Grizzly Bears", "Ornithopter"]


def test_w1g3_auriok_salvagers_unannounced_takes_a_legal_card(set_pool):
    """A bare activation (an AI seat, a caller that named no slot) still takes
    only a card the line allows."""
    lea = set_pool("LEA")
    game = _w1g3_table(
        set_pool, graveyard=[lea["Rod of Ruin"], lea["Black Lotus"]],
    )
    salvagers = set_pool("5DN")["Auriok Salvagers"]
    game._put_permanent_onto_battlefield(0, _W1G3Permanent(card=salvagers), None)
    assert game.activate_permanent_ability(0, "Auriok Salvagers").supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert _w1g3_names(alice.hand) == ["Black Lotus"]
    assert _w1g3_names(alice.graveyard) == ["Rod of Ruin"]

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.
from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.equipment import equipped_creature as _w1g4_equipped
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import settle as _w1g4_settle


def _w1g4_table(set_pool, *, interactive=()):
    """Two seats on seat 0's first main phase, libraries to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G4Game(players=[
        _W1G4PlayerState(name=f"P{seat}", library=[island] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g4_put(game, card, seat):
    """*card* onto *seat*'s battlefield through the entry seam, not sick."""
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g4_settle(game)
    return permanent


def _w1g4_activate(game, seat, permanent, **targets):
    result = game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **targets,
    )
    _w1g4_settle(game)
    return result


def test_w1g4_goblin_brawler_is_a_legal_equip_target_the_equipment_never_moves_onto(set_pool):
    """"This creature can't be equipped." Its 2004-12-01 ruling: "You can
    activate an equip ability that targets Goblin Brawler, but the Equipment
    will fail to move onto it" (CR 301.5b). So the activation is accepted and
    paid, the resolution leaves the Equipment where it was, and the same
    Equipment then equips another creature normally."""
    fifth, mirrodin, alpha = set_pool("5DN"), set_pool("MRD"), set_pool("LEA")
    assert _w1g4_compile(fifth["Goblin Brawler"]).supported
    game = _w1g4_table(set_pool)
    brawler = _w1g4_put(game, fifth["Goblin Brawler"], 0)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)

    result = _w1g4_activate(
        game, 0, splitter, target_permanent_ids=[brawler.permanent_id]
    )
    assert result.supported
    assert _w1g4_equipped(splitter) is None
    assert (brawler.effective_power, brawler.effective_toughness) == (2, 2)
    assert any("can't be equipped" in line for line in game.log)

    _w1g4_activate(game, 0, splitter, target_permanent_ids=[bears.permanent_id])
    assert _w1g4_equipped(splitter) is bears
    assert bears.effective_power == 4


def test_w1g4_the_ai_never_plans_an_equip_onto_goblin_brawler(set_pool):
    """The restriction is asked by ``equip_refusal``, the predicate the AI's
    equip planner asks too, so it never pays for an equip that cannot land:
    with the Brawler alone there is nothing to equip, and beside a Bears it
    picks the Bears."""
    from engine.ai_activation_targets import _choose_equip_target

    fifth, mirrodin, alpha = set_pool("5DN"), set_pool("MRD"), set_pool("LEA")
    game = _w1g4_table(set_pool)
    brawler = _w1g4_put(game, fifth["Goblin Brawler"], 0)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    assert _choose_equip_target(game, 0, splitter) is None
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    chosen = _choose_equip_target(game, 0, splitter)
    assert game.players[0].battlefield[chosen] is bears
    assert brawler is not bears


def test_w1g4_auriok_windwalker_moves_its_controllers_equipment_between_their_creatures(set_pool):
    """"{T}: Attach target Equipment you control to target creature you
    control." Two roles, both narrowed to the activator: the picker offers only
    the activator's Equipment and creatures, an announcement naming either of
    the opponent's is refused before the {T} is paid (CR 602.2b), and the legal
    one moves the Equipment at instant speed."""
    from engine.targeting import derive_activation_spec

    fifth, mirrodin, alpha = set_pool("5DN"), set_pool("MRD"), set_pool("LEA")
    game = _w1g4_table(set_pool)
    walker = _w1g4_put(game, fifth["Auriok Windwalker"], 0)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    their_splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 1)
    their_bears = _w1g4_put(game, alpha["Grizzly Bears"], 1)

    ability = _w1g4_compile(walker.card).activated_abilities[0]
    spec = derive_activation_spec(ability)
    assert [(role["role"], role.get("own_only")) for role in spec["roles"]] == [
        ("equipment", True), ("creature", True),
    ]

    for equipment, creature in (
        (their_splitter, bears), (splitter, their_bears),
    ):
        refused = _w1g4_activate(
            game, 0, walker,
            target_permanent_ids=[equipment.permanent_id, creature.permanent_id],
        )
        assert not refused.supported
        assert not walker.tapped

    result = _w1g4_activate(
        game, 0, walker,
        target_permanent_ids=[splitter.permanent_id, bears.permanent_id],
    )
    assert result.supported, result.details
    assert walker.tapped
    assert _w1g4_equipped(splitter) is bears
    assert bears.effective_power == 4
    assert _w1g4_equipped(their_splitter) is None

# ==== end w1g4 ======================================================
