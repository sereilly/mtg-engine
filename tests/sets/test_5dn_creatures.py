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

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================
