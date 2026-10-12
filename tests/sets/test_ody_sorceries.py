"""Odyssey sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
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

import pytest as _w1g2_pytest

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_duel(set_pool, hand, *, graveyard=0):
    """A two-seat game with costs off, seat 0 holding *hand* (card names from
    Odyssey) with *graveyard* cards in its graveyard, in its main phase."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_Game(players=[
        _w1g2_PlayerState(
            "Caster", library=[lea["Forest"]] * 10, hand=[ody[name] for name in hand],
        ),
        _w1g2_PlayerState("Bystander", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.players[0].graveyard.extend([lea["Grizzly Bears"]] * graveyard)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game  # _w1g2_duel


def _w1g2_put(game, seat, card):
    permanent = _w1g2_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put


def _w1g2_names(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))  # _w1g2_names


# ---------------------------------------------------------------------------
# Epicenter
# ---------------------------------------------------------------------------

def test_epicenter_below_threshold_costs_the_target_one_land(set_pool):
    """"Target player sacrifices a land of their choice." One land, the
    targeted player's, and the caster's own lands are untouched."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Epicenter"], graveyard=6)
    for _ in range(3):
        _w1g2_put(game, 0, lea["Forest"])
        _w1g2_put(game, 1, lea["Island"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])

    assert game.queue_from_hand(0, "Epicenter", target_player_index=1).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g2_names(game, 0) == ["Forest"] * 3
    assert _w1g2_names(game, 1) == ["Grizzly Bears", "Island", "Island"]
    assert game.is_on_battlefield(bears)
    assert [card.name for card in game.players[1].graveyard] == ["Island"]


def test_epicenter_at_threshold_takes_every_land_instead(set_pool):
    """"Threshold — **Each player** sacrifices all lands they control
    **instead** if there are seven or more cards in your graveyard." The
    replacement names somebody else outright: every land on both sides goes,
    creatures stay, and the one-land sacrifice does not happen as well — the
    targeted player loses three lands, not four of a larger board's."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Epicenter"], graveyard=7)
    for _ in range(3):
        _w1g2_put(game, 0, lea["Forest"])
        _w1g2_put(game, 1, lea["Island"])
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Grizzly Bears"])

    assert game.queue_from_hand(0, "Epicenter", target_player_index=1).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g2_names(game, 0) == ["Grizzly Bears"]
    assert _w1g2_names(game, 1) == ["Grizzly Bears"]
    assert game.is_on_battlefield(mine) and game.is_on_battlefield(theirs)
    assert len(game.players[1].graveyard) == 3
    assert len(game.players[0].graveyard) == 7 + 3 + 1
    assert sum("sacrificed" in line for line in game.log) == 2


def test_epicenter_still_announces_its_target_player_at_threshold(set_pool):
    """The target is chosen as the spell is cast (CR 601.2c), when nobody
    knows which sentence will run: the picker offers players whichever the
    graveyard says, and a permanent is not a legal announcement."""
    lea = set_pool("LEA")
    card = set_pool("ODY")["Epicenter"]
    for graveyard in (0, 7):
        game = _w1g2_duel(set_pool, ["Epicenter"], graveyard=graveyard)
        island = _w1g2_put(game, 1, lea["Island"])
        spec = game.cast_target_spec(0, card)
        assert spec["requires_target"], graveyard
        assert {entry["kind"] for entry in spec["valid_targets"]} == {"player"}
        refused = game.queue_from_hand(
            0, "Epicenter", target_permanent_ids=[island.permanent_id],
        )
        assert not refused.supported, (graveyard, refused.details)
        assert game.players[0].hand == [card]


# ---------------------------------------------------------------------------
# Kirtar's Wrath
# ---------------------------------------------------------------------------

def _w1g2_wrath_board(set_pool, graveyard):
    """Kirtar's Wrath in hand over a board with a regeneration shield up on
    the opponent's Drudge Skeletons."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Kirtar's Wrath"], graveyard=graveyard)
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Craw Wurm"])
    skeletons = _w1g2_put(game, 1, lea["Drudge Skeletons"])
    assert game.activate_permanent_ability(1, "Drudge Skeletons").supported
    return game, (mine, theirs, skeletons)  # _w1g2_wrath_board


@_w1g2_pytest.mark.parametrize("graveyard, spirits", [(6, 0), (7, 2)])
def test_kirtars_wrath_destroys_everything_and_regeneration_does_not_help(
    set_pool, graveyard, spirits,
):
    """"Destroy all creatures. They can't be regenerated. / Threshold — If
    there are seven or more cards in your graveyard, **instead** destroy all
    creatures, then create two 1/1 white Spirit creature tokens with flying.
    Creatures destroyed this way can't be regenerated." Either way every
    creature dies and a regeneration shield is no answer (CR 701.19c); at
    threshold two Spirits arrive *after* the sweep and survive it."""
    game, creatures = _w1g2_wrath_board(set_pool, graveyard)

    assert game.cast_from_hand(0, "Kirtar's Wrath").supported

    assert not any(game.is_on_battlefield(creature) for creature in creatures)
    assert _w1g2_names(game, 1) == []
    tokens = list(game.controlled_by(0))
    assert len(tokens) == spirits
    for token in tokens:
        assert token.card.name == "Spirit Token"
        assert (token.effective_power, token.effective_toughness) == (1, 1)
        assert set(token.effective_colors) == {"W"}
        assert game._has_keyword(token, "flying")
    assert sum("were destroyed" in line for line in game.log) == 1, "one sweep, not two"


def test_kirtars_wrath_marks_the_replacing_sweep_unregenerable_too(set_pool):
    """The rider is printed twice, once per sentence, and each has to reach
    its own sweep: "Creatures destroyed this way can't be regenerated" follows
    a "…, then create …" sentence, so it marks the destroy inside it. Read
    onto the replaced arm alone, the threshold sweep could be regenerated
    from."""
    program = _w1g2_compile(set_pool("ODY")["Kirtar's Wrath"])
    (gate,) = program.instructions
    assert gate.kind == "if_then"
    then, otherwise = gate.payload["then"], gate.payload["else"]
    assert [step.kind for step in then] == ["destroy_all_creatures", "create_token"]
    assert [step.kind for step in otherwise] == ["destroy_all_creatures"]
    assert then[0].payload.get("bypass_regeneration") is True
    assert otherwise[0].payload.get("bypass_regeneration") is True
    assert then[1].payload["count"] == 2


def test_the_threshold_sorceries_compile_every_printed_sentence(set_pool):
    """None is supported on its first sentence alone: the whole card is one
    conditional whose condition is the graveyard count."""
    ody = set_pool("ODY")
    for name in ("Epicenter", "Kirtar's Wrath", "Shower of Coals"):
        program = _w1g2_compile(ody[name])
        assert program.supported, name
        assert [i.kind for i in program.instructions] == ["if_then"], name
        assert program.instructions[0].payload["condition"]["value"] == 7


# ---------------------------------------------------------------------------
# Shower of Coals
# ---------------------------------------------------------------------------

def _w1g2_shower_board(set_pool, graveyard):
    """Shower of Coals in hand; the opponent has Bears (2/2), a Wurm (6/4)
    and a Giant (3/3), the caster a Wurm of its own."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Shower of Coals"], graveyard=graveyard)
    mine = _w1g2_put(game, 0, lea["Craw Wurm"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    wurm = _w1g2_put(game, 1, lea["Craw Wurm"])
    giant = _w1g2_put(game, 1, lea["Hill Giant"])
    return game, mine, bears, wurm, giant  # _w1g2_shower_board


def _w1g2_slot(game, permanent):
    return (game.controller_index_of(permanent), game.battlefield_index_of(permanent))  # _w1g2_slot


@_w1g2_pytest.mark.parametrize("graveyard, each", [(6, 2), (7, 4)])
def test_shower_of_coals_deals_two_or_four_to_each_of_up_to_three(
    set_pool, graveyard, each,
):
    """"Shower of Coals deals 2 damage to each of up to three targets. /
    Threshold — Shower of Coals deals 4 damage to **each of those permanents
    and/or players** instead if there are seven or more cards in your
    graveyard." One list — a face and two creatures here — announced once, and
    every target on it takes the whole amount of whichever sentence runs:
    2 kills the Bears and not the Wurm, 4 kills both. The Giant was never
    named and is never touched."""
    game, _mine, bears, wurm, giant = _w1g2_shower_board(set_pool, graveyard)

    assert game.queue_from_hand(
        0, "Shower of Coals",
        divided_targets=[(1, None), _w1g2_slot(game, bears), _w1g2_slot(game, wurm)],
    ).supported
    _w1g2_resolve_stack(game)
    game._settle()

    assert game.players[1].life == 20 - each and game.players[0].life == 20
    assert not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(wurm) is (each < 4)
    assert game.is_on_battlefield(giant)
    assert sum("Shower of Coals dealt" in line for line in game.log) == 3
    assert all(
        f"dealt {each} damage" in line
        for line in game.log if "Shower of Coals dealt" in line
    )


def test_shower_of_coals_holds_its_list_to_three_different_targets(set_pool):
    """CR 601.2c: "up to three" is a ceiling the caster may fall short of and
    never exceed, one instance of the word names each target once, and the
    card — not the caster — says what each gets. Every refusal leaves the
    spell in hand."""
    card = set_pool("ODY")["Shower of Coals"]
    game, mine, bears, wurm, giant = _w1g2_shower_board(set_pool, 7)
    spec = game.cast_target_spec(0, card)
    assert (spec["kind"], spec["division"], spec["max_targets"]) == ("divided", "each", 3)
    assert {entry["kind"] for entry in spec["valid_targets"]} == {"player", "permanent"}

    four = game.queue_from_hand(0, "Shower of Coals", divided_targets=[
        (1, None), _w1g2_slot(game, bears), _w1g2_slot(game, wurm), _w1g2_slot(game, giant),
    ])
    twice = game.queue_from_hand(
        0, "Shower of Coals", divided_targets=[(1, None), (1, None)],
    )
    sized = game.queue_from_hand(
        0, "Shower of Coals", divided_targets=[(*_w1g2_slot(game, bears), 9)],
    )
    assert "at most 3 targets" in four.details
    assert "different" in twice.details
    assert "printed, not announced" in sized.details
    assert not (four.supported or twice.supported or sized.supported)
    assert game.players[0].hand == [card] and game.stack == []

    assert game.cast_from_hand(
        0, "Shower of Coals", divided_targets=[_w1g2_slot(game, giant)],
    ).supported
    assert not game.is_on_battlefield(giant)
    assert game.is_on_battlefield(bears) and game.is_on_battlefield(mine)
    assert game.players[1].life == 20


def test_shower_of_coals_reads_threshold_as_it_resolves_and_drops_a_gone_target(set_pool):
    """Six cards as it is cast and a seventh arriving in response is 4 each
    (CR 608.2h). A target that left in response is dealt nothing and nothing
    takes its place (CR 608.2b); the rest of the list still burns."""
    lea = set_pool("LEA")
    game, _mine, bears, wurm, giant = _w1g2_shower_board(set_pool, 6)
    assert game.queue_from_hand(
        0, "Shower of Coals",
        divided_targets=[_w1g2_slot(game, bears), _w1g2_slot(game, wurm), (1, None)],
    ).supported

    game.players[0].graveyard.append(lea["Forest"])
    game.remove_from_battlefield(bears)
    _w1g2_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(wurm), "4, not 2"
    assert game.is_on_battlefield(giant), "never named"
    assert game.players[1].life == 16

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from engine.cast_permissions import (expire_end_of_turn as _w1g3_expire_end_of_turn,
                                     playable_from_zones as _w1g3_playable_from_zones)
from engine.mana_payment import mana_cost_from_symbols as _w1g3_mana_cost_from_symbols
from engine.models import Permanent as _w1g3_Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from tests.helpers import resolve_stack as _w1g3_resolve_stack

# Flashback (CR 702.34): every Odyssey sorcery printing it, the one that grants
# it (Recoup) and the one that names it (Tombfire). Each flashback card is cast
# **twice** — from a hand for its mana cost, from a graveyard for its flashback
# cost — with mana enforced and exactly that cost in the pool, and is held to
# doing the same thing both times and to ending up in the right pile: its
# owner's graveyard after the first, exile after the second. The keyword's own
# rules (who may cast it, every way off the stack, cost changes) are
# tests/rules/test_flashback.py; these say what each *card* does.


def _w1g3_game() -> _w1g3_Game:
    game = _w1g3_Game(players=[_w1g3_PlayerState(name="P1"), _w1g3_PlayerState(name="P2")])
    game.enforce_mana_costs = True
    return game


def _w1g3_pay(player, cost: str) -> None:
    """Exactly *cost* in *player*'s pool, the generic part as colourless."""
    pool = {symbol: 0 for symbol in "WUBRGC"}
    for symbol, count in _w1g3_mana_cost_from_symbols(cost).items():
        pool["C" if symbol == "generic" else symbol] += count
    player.mana_pool.update(pool)


def _w1g3_put(game, seat: int, card, *, tapped: bool = False) -> _w1g3_Permanent:
    permanent = _w1g3_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    return permanent


def _w1g3_settle(game) -> None:
    _w1g3_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g3_resolve_stack(game)


def _w1g3_zones_holding(game, card) -> list[str]:
    return [
        f"P{seat + 1}.{zone}"
        for seat, player in enumerate(game.players)
        for zone in ("hand", "graveyard", "exile", "library")
        for held in getattr(player, zone) if held is card
    ]


def _w1g3_both_ways(set_pool, name: str, flashback_cost: str, arrange, expect) -> None:
    """Cast *name* from a hand for its mana cost and from a graveyard for
    *flashback_cost*. ``arrange(game, seen)`` builds the board and returns the
    cast's keywords; ``expect(game, seen)`` asserts what the spell did."""
    card = set_pool("ODY")[name]
    for zone, cost, afterwards in (
        ("hand", card.mana_cost, "P1.graveyard"),
        ("graveyard", flashback_cost, "P1.exile"),
    ):
        game, seen = _w1g3_game(), {}
        getattr(game.players[0], zone).append(card)
        keywords = arrange(game, seen) or {}
        _w1g3_pay(game.players[0], cost)
        cast = game.cast_from_hand(0, name, from_zone=zone, **keywords)
        assert cast.supported, (zone, cast.details)
        _w1g3_settle(game)
        assert not any(game.players[0].mana_pool.values()), (zone, f"did not cost {cost}")
        expect(game, seen)
        assert _w1g3_zones_holding(game, card) == [afterwards], zone


def _w1g3_names(zone) -> list[str]:
    return sorted(card.name for card in zone)


def test_w1g3_ancestral_tribute_counts_the_graveyard_it_is_not_in(set_pool):
    """"You gain 2 life for each card in your graveyard." On the stack it is
    not in the graveyard — cast from hand it has not arrived yet, flashed back
    it has just left — so three other cards are 6 life either way."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        game.players[0].graveyard.extend([lea["Forest"], lea["Forest"], lea["Grizzly Bears"]])
        game.players[1].graveyard.append(lea["Forest"])

    def expect(game, seen):
        assert (game.players[0].life, game.players[1].life) == (26, 20)

    _w1g3_both_ways(set_pool, "Ancestral Tribute", "{9}{W}{W}{W}", arrange, expect)


def test_w1g3_the_three_token_sorceries_make_their_token_twice(set_pool):
    for name, flashback_cost, token, stats in (
        ("Call of the Herd", "{3}{G}", "Elephant", (3, 3)),
        ("Chatter of the Squirrel", "{1}{G}", "Squirrel", (1, 1)),
        ("Roar of the Wurm", "{3}{G}", "Wurm", (6, 6)),
    ):
        def expect(game, seen):
            made, = game.controlled_by(0)
            assert token in made.card.type_line and "G" in made.card.colors
            assert (made.effective_power, made.effective_toughness) == stats
            assert not list(game.controlled_by(1))

        _w1g3_both_ways(set_pool, name, flashback_cost, lambda game, seen: None, expect)


def test_w1g3_deep_reconnaissance_fetches_a_basic_land_tapped(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        game.players[0].library.extend([lea["Sol Ring"], lea["Bayou"], lea["Forest"], lea["Grizzly Bears"]])

    def expect(game, seen):
        land, = game.controlled_by(0)
        assert land.card.name == "Forest" and land.tapped
        assert _w1g3_names(game.players[0].library) == ["Bayou", "Grizzly Bears", "Sol Ring"]

    _w1g3_both_ways(set_pool, "Deep Reconnaissance", "{4}{G}", arrange, expect)


def test_w1g3_dematerialize_returns_a_permanent_to_its_owner_s_hand(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        ring = _w1g3_put(game, 1, lea["Sol Ring"])
        return {"target_permanent_ids": [ring.permanent_id], "target_player_index": 1}

    def expect(game, seen):
        assert not list(game.controlled_by(1))
        assert _w1g3_names(game.players[1].hand) == ["Sol Ring"]

    _w1g3_both_ways(set_pool, "Dematerialize", "{5}{U}{U}", arrange, expect)


def test_w1g3_earth_rift_destroys_a_land_and_only_a_land(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        land = _w1g3_put(game, 1, lea["Forest"])
        _w1g3_put(game, 1, lea["Grizzly Bears"])
        return {"target_permanent_ids": [land.permanent_id], "target_player_index": 1}

    def expect(game, seen):
        assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
        assert _w1g3_names(game.players[1].graveyard) == ["Forest"]

    _w1g3_both_ways(set_pool, "Earth Rift", "{5}{R}{R}", arrange, expect)

    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].graveyard.append(set_pool("ODY")["Earth Rift"])
    bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
    refused = game.cast_from_hand(
        0, "Earth Rift", from_zone="graveyard",
        target_permanent_ids=[bears.permanent_id], target_player_index=1,
    )
    assert not refused.supported
    assert game.is_on_battlefield(bears)


def test_w1g3_firebolt_deals_2_to_any_target(set_pool):
    lea = set_pool("LEA")

    def at_a_player(game, seen):
        return {"target_player_index": 1}

    _w1g3_both_ways(
        set_pool, "Firebolt", "{4}{R}", at_a_player,
        lambda game, seen: _w1g3_assert_life(game, 20, 18),
    )

    def at_a_creature(game, seen):
        bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
        return {"target_permanent_ids": [bears.permanent_id], "target_player_index": 1}

    def expect(game, seen):
        assert not list(game.controlled_by(1))
        assert _w1g3_names(game.players[1].graveyard) == ["Grizzly Bears"]
        _w1g3_assert_life(game, 20, 20)

    _w1g3_both_ways(set_pool, "Firebolt", "{4}{R}", at_a_creature, expect)


def _w1g3_assert_life(game, mine: int, theirs: int) -> None:
    assert (game.players[0].life, game.players[1].life) == (mine, theirs)


def test_w1g3_morbid_hunger_deals_3_and_gains_3(set_pool):
    _w1g3_both_ways(
        set_pool, "Morbid Hunger", "{7}{B}{B}",
        lambda game, seen: {"target_player_index": 1},
        lambda game, seen: _w1g3_assert_life(game, 23, 17),
    )


def test_w1g3_morgue_theft_returns_a_creature_card_from_under_or_over_itself(set_pool):
    """"Return target creature card from your graveyard to your hand." Flashed
    back it is leaving the pile its target is in, so the slot it announces is
    counted with the spell still there (CR 601.2a) — on either side of it."""
    lea = set_pool("LEA")
    theft = set_pool("ODY")["Morgue Theft"]

    def arrange(game, seen):
        # The spell is already in the pile when it is flashed back: put one
        # creature card under it and one over, and name the one over.
        mine = game.players[0].graveyard
        mine.insert(0, lea["Grizzly Bears"])
        mine.extend([lea["Serra Angel"], lea["Sol Ring"]])
        return {"target_player_index": 0, "target_permanent_index": mine.index(lea["Serra Angel"])}

    def expect(game, seen):
        assert _w1g3_names(game.players[0].hand) == ["Serra Angel"]
        assert {"Grizzly Bears", "Sol Ring"} <= set(_w1g3_names(game.players[0].graveyard))

    _w1g3_both_ways(set_pool, "Morgue Theft", "{4}{B}", arrange, expect)

    # Not a noncreature card, and not somebody else's graveyard.
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].graveyard.extend([theft, lea["Sol Ring"]])
    game.players[1].graveyard.append(lea["Grizzly Bears"])
    offered = game.cast_target_spec(0, theft, from_zone="graveyard")["valid_targets"]
    assert offered == []
    assert not game.cast_from_hand(
        0, "Morgue Theft", from_zone="graveyard",
        target_player_index=0, target_permanent_index=1,
    ).supported


def test_w1g3_reckless_charge_gives_plus_3_and_haste_until_end_of_turn(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["bears"] = _w1g3_put(game, 0, lea["Grizzly Bears"])
        return {"target_permanent_ids": [seen["bears"].permanent_id], "target_player_index": 0}

    def expect(game, seen):
        bears = seen["bears"]
        assert (bears.effective_power, bears.effective_toughness) == (5, 2)
        assert game._has_keyword(bears, "haste")

    _w1g3_both_ways(set_pool, "Reckless Charge", "{2}{R}", arrange, expect)


def test_w1g3_scorching_missile_hits_a_player_and_cannot_be_aimed_at_a_creature(set_pool):
    lea = set_pool("LEA")
    _w1g3_both_ways(
        set_pool, "Scorching Missile", "{9}{R}",
        lambda game, seen: {"target_player_index": 1},
        lambda game, seen: _w1g3_assert_life(game, 20, 16),
    )
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].graveyard.append(set_pool("ODY")["Scorching Missile"])
    bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
    refused = game.cast_from_hand(
        0, "Scorching Missile", from_zone="graveyard",
        target_permanent_ids=[bears.permanent_id], target_player_index=1,
    )
    assert not refused.supported
    assert bears.damage_marked == 0 and game.players[1].life == 20


def test_w1g3_seize_the_day_untaps_and_adds_a_combat_and_a_main_phase(set_pool):
    """"Untap target creature. After this main phase, there is an additional
    combat phase followed by an additional main phase." Flashed back in that
    second main phase it does it again."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["bears"] = _w1g3_put(game, 0, lea["Grizzly Bears"], tapped=True)
        assert game.extra_phases_remaining() == []
        return {"target_permanent_ids": [seen["bears"].permanent_id], "target_player_index": 0}

    def expect(game, seen):
        assert not seen["bears"].tapped
        assert game.extra_phases_remaining() == ["combat", "postcombat_main"]

    _w1g3_both_ways(set_pool, "Seize the Day", "{2}{R}", arrange, expect)


def test_w1g3_skull_fracture_makes_the_target_player_discard(set_pool):
    lea = set_pool("LEA")

    def arrange(game, seen):
        game.players[1].hand.append(lea["Forest"])
        return {"target_player_index": 1}

    def expect(game, seen):
        assert game.players[1].hand == []
        assert _w1g3_names(game.players[1].graveyard) == ["Forest"]

    _w1g3_both_ways(set_pool, "Skull Fracture", "{3}{B}", arrange, expect)


def test_w1g3_volcanic_spray_spares_the_fliers(set_pool):
    """"…deals 1 damage to each creature without flying and each player."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["angel"] = _w1g3_put(game, 1, lea["Serra Angel"])
        seen["bears"] = _w1g3_put(game, 1, lea["Grizzly Bears"])
        seen["birds"] = _w1g3_put(game, 0, lea["Birds of Paradise"])

    def expect(game, seen):
        assert (seen["angel"].damage_marked, seen["bears"].damage_marked) == (0, 1)
        assert seen["birds"].damage_marked == 0 and game.is_on_battlefield(seen["birds"])
        _w1g3_assert_life(game, 19, 19)

    _w1g3_both_ways(set_pool, "Volcanic Spray", "{1}{R}", arrange, expect)


def test_w1g3_volley_of_boulders_divides_6_as_announced(set_pool):
    """Flashback {R}{R}{R}{R}{R}{R}: the division (CR 601.2d) is announced from
    a graveyard exactly as it is from a hand."""
    lea = set_pool("LEA")

    def arrange(game, seen):
        seen["angel"] = _w1g3_put(game, 1, lea["Serra Angel"])
        seen["bears"] = _w1g3_put(game, 1, lea["Grizzly Bears"])
        return {"divided_targets": [
            (1, None, 1),
            (1, game.battlefield_index_of(seen["angel"]), 3),
            (1, game.battlefield_index_of(seen["bears"]), 2),
        ]}

    def expect(game, seen):
        _w1g3_assert_life(game, 20, 19)
        assert seen["angel"].damage_marked == 3 and game.is_on_battlefield(seen["angel"])
        assert not game.is_on_battlefield(seen["bears"])

    _w1g3_both_ways(set_pool, "Volley of Boulders", "{R}{R}{R}{R}{R}{R}", arrange, expect)

    # A division that does not come to 6 is no announcement at all.
    game = _w1g3_game()
    game.enforce_mana_costs = False
    volley = set_pool("ODY")["Volley of Boulders"]
    game.players[0].graveyard.append(volley)
    refused = game.cast_from_hand(
        0, "Volley of Boulders", from_zone="graveyard", divided_targets=[(1, None, 5)],
    )
    assert not refused.supported
    assert _w1g3_zones_holding(game, volley) == ["P1.graveyard"]


def test_w1g3_recoup_gives_a_sorcery_card_flashback_for_its_mana_cost(set_pool):
    """"Target sorcery card in your graveyard gains flashback until end of
    turn. The flashback cost is equal to its mana cost." The card is then cast
    from the graveyard for that cost and exiled, like any flashback cast."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    recoup, wrath = ody["Recoup"], lea["Wrath of God"]
    assert _w1g3_compile(recoup).supported

    game = _w1g3_game()
    game.players[0].hand.append(recoup)
    game.players[0].graveyard.extend([lea["Counterspell"], wrath, lea["Grizzly Bears"]])
    game.players[1].graveyard.append(lea["Armageddon"])
    bears = _w1g3_put(game, 1, lea["Grizzly Bears"])
    # A sorcery card, in the caster's own graveyard: not the instant beside it
    # and not the opponent's sorcery.
    offered = game.cast_target_spec(0, recoup)["valid_targets"]
    assert [(t["seat"], t["name"]) for t in offered] == [(0, "Wrath of God")]
    assert _w1g3_playable_from_zones(game, 0) == []

    _w1g3_pay(game.players[0], "{1}{R}")
    assert game.cast_from_hand(
        0, "Recoup", target_player_index=0, target_permanent_index=1,
    ).supported
    assert any("Wrath of God gains flashback {2}{W}{W}" in line for line in game.log)
    castable = {entry["name"]: entry for entry in _w1g3_playable_from_zones(game, 0)}
    # Recoup is in the graveyard now with its own printed flashback; the Wrath
    # has the granted one, priced at its mana cost.
    assert castable["Wrath of God"]["cost_mana"] == "{2}{W}{W}"
    assert castable["Recoup"]["cost_mana"] == "{3}{R}"
    assert set(castable) == {"Wrath of God", "Recoup"}

    _w1g3_pay(game.players[0], "{1}{W}{W}")
    short = game.cast_from_hand(0, "Wrath of God", from_zone="graveyard")
    assert not short.supported and "flashback cost ({2}{W}{W})" in short.details
    assert game.is_on_battlefield(bears)
    _w1g3_pay(game.players[0], "{2}{W}{W}")
    assert game.cast_from_hand(0, "Wrath of God", from_zone="graveyard").supported
    _w1g3_settle(game)
    assert not game.is_on_battlefield(bears)
    assert _w1g3_zones_holding(game, wrath) == ["P1.exile"]
    # One card, one grant: used, it is gone.
    assert [entry["name"] for entry in _w1g3_playable_from_zones(game, 0)] == ["Recoup"]


def test_w1g3_recoup_over_an_x_spell_charges_the_x_that_was_announced(set_pool):
    """"(Mana cost includes color.)" — and its {X}: Disintegrate's granted
    flashback cost is {X}{R}, paid at the X the cast announces."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    disintegrate = lea["Disintegrate"]
    game = _w1g3_game()
    game.players[0].hand.append(ody["Recoup"])
    game.players[0].graveyard.append(disintegrate)
    _w1g3_pay(game.players[0], "{1}{R}")
    assert game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=0).supported
    granted, = [e for e in _w1g3_playable_from_zones(game, 0) if e["name"] == "Disintegrate"]
    assert granted["cost_mana"] == "{X}{R}"

    _w1g3_pay(game.players[0], "{2}{R}")
    refused = game.cast_from_hand(
        0, "Disintegrate", from_zone="graveyard", target_player_index=1, x_value=3,
    )
    assert not refused.supported and game.players[1].life == 20
    _w1g3_pay(game.players[0], "{3}{R}")
    assert game.cast_from_hand(
        0, "Disintegrate", from_zone="graveyard", target_player_index=1, x_value=3,
    ).supported
    _w1g3_settle(game)
    assert game.players[1].life == 17
    assert not any(game.players[0].mana_pool.values())
    assert _w1g3_zones_holding(game, disintegrate) == ["P1.exile"]


def test_w1g3_recoup_s_grant_ends_with_the_turn_and_needs_a_sorcery_to_name(set_pool):
    ody, lea = set_pool("ODY"), set_pool("LEA")
    recoup, wrath = ody["Recoup"], lea["Wrath of God"]
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].hand.append(recoup)
    game.players[0].graveyard.append(lea["Counterspell"])
    refused = game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=0)
    assert not refused.supported and recoup in game.players[0].hand

    game.players[0].graveyard.append(wrath)
    assert game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=1).supported
    assert "Wrath of God" in [e["name"] for e in _w1g3_playable_from_zones(game, 0)]
    _w1g3_expire_end_of_turn(game)
    assert [e["name"] for e in _w1g3_playable_from_zones(game, 0)] == ["Recoup"]
    assert not game.cast_from_hand(0, "Wrath of God", from_zone="graveyard").supported


def test_w1g3_recoup_flashed_back_cannot_name_itself(set_pool):
    """Recoup has flashback and is a sorcery card in a graveyard — but not
    while it is being cast out of one (CR 601.2a)."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    recoup = ody["Recoup"]
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].graveyard.append(recoup)
    assert game.cast_target_spec(0, recoup, from_zone="graveyard")["valid_targets"] == []
    assert not game.cast_from_hand(
        0, "Recoup", from_zone="graveyard", target_player_index=0, target_permanent_index=0,
    ).supported
    # With a sorcery beside it, it names that one — by the slot it was in while
    # Recoup was still under it.
    game.players[0].graveyard.append(lea["Wrath of God"])
    assert game.cast_from_hand(
        0, "Recoup", from_zone="graveyard", target_player_index=0, target_permanent_index=1,
    ).supported
    assert _w1g3_zones_holding(game, recoup) == ["P1.exile"]
    granted, = [e for e in _w1g3_playable_from_zones(game, 0)]
    assert (granted["name"], granted["cost_mana"]) == ("Wrath of God", "{2}{W}{W}")


def test_w1g3_tombfire_exiles_the_cards_with_flashback_from_one_graveyard(set_pool):
    """"Target player exiles all cards with flashback from their graveyard."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    tombfire = ody["Tombfire"]
    assert _w1g3_compile(tombfire).supported

    def board():
        game = _w1g3_game()
        game.enforce_mana_costs = False
        game.players[0].hand.append(tombfire)
        game.players[0].graveyard.extend([ody["Firebolt"], lea["Forest"]])
        game.players[1].graveyard.extend(
            [ody["Firebolt"], lea["Grizzly Bears"], ody["Recoup"], ody["Roar of the Wurm"], lea["Terror"]]
        )
        return game

    game = board()
    assert [t["seat"] for t in game.cast_target_spec(0, tombfire)["valid_targets"]] == [0, 1]
    assert game.cast_from_hand(0, "Tombfire", target_player_index=1).supported
    assert _w1g3_names(game.players[1].exile) == ["Firebolt", "Recoup", "Roar of the Wurm"]
    assert _w1g3_names(game.players[1].graveyard) == ["Grizzly Bears", "Terror"]
    # The other graveyard was not the one chosen.
    assert _w1g3_names(game.players[0].graveyard) == ["Firebolt", "Forest", "Tombfire"]
    assert game.players[0].exile == []

    game = board()
    assert game.cast_from_hand(0, "Tombfire", target_player_index=0).supported
    assert _w1g3_names(game.players[0].exile) == ["Firebolt"]
    assert "Firebolt" in _w1g3_names(game.players[1].graveyard)


def test_w1g3_tombfire_takes_a_card_recoup_gave_flashback_this_turn(set_pool):
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g3_game()
    game.enforce_mana_costs = False
    game.players[0].hand.extend([ody["Recoup"], ody["Tombfire"]])
    game.players[0].graveyard.extend([lea["Wrath of God"], lea["Armageddon"]])
    assert game.cast_from_hand(0, "Recoup", target_player_index=0, target_permanent_index=0).supported
    assert game.cast_from_hand(0, "Tombfire", target_player_index=0).supported
    # The Wrath (granted) and Recoup itself (printed); not the other sorcery.
    assert _w1g3_names(game.players[0].exile) == ["Recoup", "Wrath of God"]
    assert _w1g3_names(game.players[0].graveyard) == ["Armageddon", "Tombfire"]

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4_pytest

from engine import Game as _w1g4_Game, PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names.

    Odyssey over Stronghold over Alpha: the furniture is Alpha's, and Megrim —
    which is how a discard is seen to have gone through its seam — is
    Stronghold's.
    """
    pool = {**set_pool("LEA"), **set_pool("STH"), **set_pool("ODY")}
    seats = [
        _w1g4_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g4_Game(players=seats)
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            game._put_permanent_onto_battlefield(
                seat, _w1g4_Permanent(card=pool[name]), None
            )
    return game


def _w1g4_names(cards):
    return [card.name for card in cards]


# --- Mind Burst: a *chosen* discard of X cards -------------------------------

def test_mind_burst_makes_its_target_choose_one_plus_the_bursts(set_pool):
    """One plus two in graveyards is three, and the discarding player picks
    them — the lowering refused a chosen discard of X on the ground that the
    only variable handler discarded at random, long after the chosen handler
    began sizing its prompt from X."""
    game = _w1g4_duel(
        set_pool, hand0=["Mind Burst"], gy0=["Mind Burst"], gy1=["Mind Burst"],
        hand1=["Grizzly Bears", "Forest", "Island", "Swamp", "Mountain"],
    )
    game.interactive_seats.add(1)
    assert game.cast_from_hand(0, "Mind Burst", target_player_index=1).supported
    prompt = next(c for c in game.pending_choices if c.kind == "discard")
    assert prompt.player_index == 1 and prompt.data["count"] == 3
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 2
    assert len(game.players[1].graveyard) == 4


def test_mind_burst_takes_what_there_is_from_a_short_hand(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Mind Burst"], gy0=["Mind Burst", "Mind Burst"],
        hand1=["Forest"],
    )
    assert game.cast_from_hand(0, "Mind Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert game.players[1].hand == []
    assert "Forest" in _w1g4_names(game.players[1].graveyard)


def test_a_chosen_discard_of_a_cast_x_reads_the_announced_number(set_pool):
    """The same handler under an X the caster pays for rather than counts."""
    warp = _w1g4_mk_card(
        "Mind Wrench", "{X}{B}", "Sorcery", "Target player discards X cards."
    )
    assert _w1g4_compile(warp).supported
    game = _w1g4_duel(set_pool, hand1=["Forest", "Island", "Swamp"])
    game.players[0].hand.append(warp)
    assert game.cast_from_hand(
        0, "Mind Wrench", target_player_index=1, x_value=2
    ).supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 1


# --- Hint of Insanity: "…the same name as another card in their hand" --------

def test_hint_of_insanity_discards_every_nonland_card_held_in_multiples(set_pool):
    """A pair and a triple go; the two Forests share a name and are lands, and
    the lone Wurm shares a name with nothing. Nobody chooses, so no prompt."""
    game = _w1g4_duel(
        set_pool, hand0=["Hint of Insanity"],
        hand1=["Grizzly Bears", "Forest", "Lightning Bolt", "Grizzly Bears",
               "Forest", "Craw Wurm", "Lightning Bolt", "Lightning Bolt"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert game.pending_choices == []
    assert _w1g4_names(game.players[1].hand) == ["Forest", "Forest", "Craw Wurm"]
    assert sorted(_w1g4_names(game.players[1].graveyard)) == [
        "Grizzly Bears", "Grizzly Bears",
        "Lightning Bolt", "Lightning Bolt", "Lightning Bolt",
    ]
    assert any(
        line.startswith("P1 reveals their hand") for line in game.log
    ), "the reveal is its own sentence and happens whatever is discarded"


def test_hint_of_insanity_with_no_pair_reveals_and_discards_nothing(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Hint of Insanity"],
        hand1=["Grizzly Bears", "Forest", "Forest", "Craw Wurm"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert len(game.players[1].hand) == 4 and game.players[1].graveyard == []
    assert any(line.startswith("P1 reveals their hand") for line in game.log)


def test_hint_of_insanity_at_its_own_caster_does_not_pair_with_itself(set_pool):
    """The copy being cast is on the stack, so a second Hint in hand shares a
    name with no *other card in that hand* — and the two Bears go."""
    game = _w1g4_duel(
        set_pool,
        hand0=["Hint of Insanity", "Hint of Insanity", "Grizzly Bears", "Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=0
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].hand) == ["Hint of Insanity"]
    assert game.players[1].hand == []


def test_hint_of_insanity_discards_through_the_discard_seam(set_pool):
    """Megrim sees each card: the discards are announced, not written."""
    game = _w1g4_duel(
        set_pool, hand0=["Hint of Insanity"],
        hand1=["Grizzly Bears", "Grizzly Bears", "Forest"], bf0=["Megrim"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 16


@_w1g4_pytest.mark.parametrize("line", [
    # "Another card" with no pile behind it compares against nobody knows what.
    "Target player discards all nonland cards with the same name as another card.",
    # A pile other than the one being discarded from is a different sentence.
    "Target player discards all nonland cards with the same name as another "
    "card in your hand.",
    # A card phrase compared with a permanent names two kinds of object.
    "Target player discards all nonland cards with the same name as another "
    "permanent.",
])
def test_the_shared_name_discard_refuses_what_it_cannot_compare(line):
    hint = _w1g4_mk_card("Odd Hint", "{B}", "Sorcery", line)
    assert not _w1g4_compile(hint).supported


# --- Haunting Echoes: a sweep of one graveyard, then a strip by every name ---

def test_haunting_echoes_exiles_the_graveyard_and_every_library_copy(set_pool):
    """The basic land stays in the graveyard and its copy in the library; the
    nonbasic land, the creature and the instant go from both. The caster's own
    graveyard and library are not touched."""
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"],
        gy1=["Grizzly Bears", "Forest", "Lightning Bolt", "Bayou"],
        lib1=["Grizzly Bears", "Forest", "Lightning Bolt", "Craw Wurm",
              "Grizzly Bears", "Bayou", "Island"],
        gy0=["Craw Wurm"], lib0=["Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Forest"]
    assert sorted(_w1g4_names(game.players[1].library)) == [
        "Craw Wurm", "Forest", "Island",
    ]
    assert sorted(_w1g4_names(game.players[1].exile)) == [
        "Bayou", "Bayou", "Grizzly Bears", "Grizzly Bears", "Grizzly Bears",
        "Lightning Bolt", "Lightning Bolt",
    ]
    assert _w1g4_names(game.players[0].library) == ["Grizzly Bears"]
    assert _w1g4_names(game.players[0].graveyard) == ["Craw Wurm", "Haunting Echoes"]
    assert game.players[0].exile == []


def test_haunting_echoes_over_only_basic_lands_strips_nothing(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"], gy1=["Forest", "Island"],
        lib1=["Forest", "Island", "Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Forest", "Island"]
    assert len(game.players[1].library) == 3 and game.players[1].exile == []


def test_haunting_echoes_may_be_aimed_at_its_caster(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"], gy0=["Grizzly Bears"],
        lib0=["Grizzly Bears", "Craw Wurm"], lib1=["Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=0
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].library) == ["Craw Wurm"]
    assert _w1g4_names(game.players[0].exile) == ["Grizzly Bears", "Grizzly Bears"]
    assert _w1g4_names(game.players[1].library) == ["Grizzly Bears"]


def test_haunting_echoes_shuffles_the_library_it_searched(set_pool):
    """CR 701.24. Fifteen distinct-order cards and a seeded RNG: the survivors'
    order changes, which an unshuffled strip would leave as it was."""
    import random

    library = (["Grizzly Bears"] + ["Forest", "Island", "Swamp", "Mountain",
               "Plains", "Craw Wurm", "Scryb Sprites", "Black Lotus",
               "Shivan Dragon", "Giant Growth", "Fireball", "Lightning Bolt",
               "Sol Ring", "Mox Pearl"])
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"], gy1=["Grizzly Bears"], lib1=library,
    )
    random.seed(11)
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    after = _w1g4_names(game.players[1].library)
    assert sorted(after) == sorted(library[1:])
    assert after != library[1:]


@_w1g4_pytest.mark.parametrize("text", [
    # No sweep in front of the loop: "exiled this way" names nothing.
    "For each card exiled this way, search target player's library for all "
    "cards with the same name as that card and exile them. Then that player "
    "shuffles.",
    # CR 701.24: a library search ends with the shuffle.
    "Exile all cards from target player's graveyard other than basic land "
    "cards. For each card exiled this way, search that player's library for "
    "all cards with the same name as that card and exile them.",
    # A loop over a narrower set than the sweep recorded.
    "Exile all cards from target player's graveyard. For each creature card "
    "exiled this way, search that player's library for all cards with the "
    "same name as that card and exile them. Then that player shuffles.",
    # "That card" outside any loop.
    "Search target player's library for all cards with the same name as that "
    "card and exile them. Then that player shuffles.",
])
def test_the_strip_by_exiled_names_refuses_without_its_sweep_and_shuffle(text):
    echoes = _w1g4_mk_card("Odd Echoes", "{B}", "Sorcery", text)
    assert not _w1g4_compile(echoes).supported


def test_a_sweep_of_a_chosen_graveyard_names_its_player(set_pool):
    """The sweep on its own, on an invented card: "target opponent's" pile and
    a narrowing the card matcher answers, with the caster's pile left alone."""
    purge = _w1g4_mk_card(
        "Grave Purge", "{B}", "Sorcery",
        "Exile all creature cards from target opponent's graveyard.",
    )
    assert _w1g4_compile(purge).supported
    game = _w1g4_duel(
        set_pool, gy0=["Grizzly Bears"], gy1=["Grizzly Bears", "Forest", "Craw Wurm"],
    )
    game.players[0].hand.append(purge)
    spec = game.cast_target_spec(0, purge)
    assert [t["seat"] for t in spec["valid_targets"]] == [1]
    assert game.cast_from_hand(0, "Grave Purge", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Forest"]
    assert _w1g4_names(game.players[0].graveyard) == ["Grizzly Bears", "Grave Purge"]


# --- Buried Alive, Diabolic Tutor, Extract -----------------------------------

_W1G4_LIBRARY = ["Forest", "Grizzly Bears", "Craw Wurm", "Scryb Sprites",
                 "Black Lotus", "Island", "Shivan Dragon"]


def test_buried_alive_puts_up_to_three_creature_cards_into_the_graveyard(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Buried Alive"], lib0=_W1G4_LIBRARY)
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Buried Alive").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["count"] == 3 and prompt.data["up_to"]
    assert prompt.data["card_type"] == "creature"
    assert prompt.data["destinations"] == ["graveyard"] * 3
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    buried = [n for n in _w1g4_names(game.players[0].graveyard) if n != "Buried Alive"]
    assert len(buried) == 3
    assert set(buried) <= {"Grizzly Bears", "Craw Wurm", "Scryb Sprites", "Shivan Dragon"}
    assert len(game.players[0].library) == 4 and game.players[0].hand == []


def test_buried_alive_over_a_library_of_no_creatures_finds_nothing(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Buried Alive"], lib0=["Forest", "Island"])
    assert game.cast_from_hand(0, "Buried Alive").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g4_names(game.players[0].graveyard) == ["Buried Alive"]
    assert len(game.players[0].library) == 2


def test_diabolic_tutor_finds_any_card_and_does_not_tell_the_table_which(set_pool):
    """A search with no reveal into a hidden zone: the log every viewer is
    sent says a card went to hand and never names it."""
    game = _w1g4_duel(set_pool, hand0=["Diabolic Tutor"], lib0=_W1G4_LIBRARY)
    assert game.cast_from_hand(0, "Diabolic Tutor").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    (found,) = _w1g4_names(game.players[0].hand)
    assert len(game.players[0].library) == 6
    assert not any(found in line for line in game.log)
    assert any("put a card into hand" in line for line in game.log)


def test_extract_exiles_a_card_from_the_library_of_the_player_it_names(set_pool):
    """The caster searches and chooses; the card goes to its owner's exile and
    the searched player's library is the one that shrinks."""
    game = _w1g4_duel(
        set_pool, hand0=["Extract"], lib0=["Swamp", "Plains"], lib1=_W1G4_LIBRARY,
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Extract", target_player_index=1).supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.player_index == 0, "CR 608.2c: the spell's controller chooses"
    assert prompt.data["zone_seat"] == 1 and prompt.data["destination"] == "exile"
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    assert len(game.players[1].library) == 6 and len(game.players[1].exile) == 1
    assert len(game.players[0].library) == 2 and game.players[0].exile == []

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.stack_targets import chosen_targets as _w1g6_chosen_targets
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_game(
    mine=(), theirs=(), yard=(), their_yard=(), library=(), hand=(),
):
    """Two seats, costs unenforced, nobody summoning sick. Cards are handed
    over as ``CardDefinition``s; seat 0's turn has started."""
    def board(cards):
        permanents = [_W1G6Permanent(card=card) for card in cards]
        for permanent in permanents:
            permanent.metadata["summoning_sickness_turn"] = -99
        return permanents

    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", battlefield=board(mine), graveyard=list(yard),
            library=list(library), hand=list(hand), life=20,
        ),
        _W1G6PlayerState(
            name="P2", battlefield=board(theirs), graveyard=list(their_yard),
            library=list(library), life=20,
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game  # _w1g6_game


def _w1g6_pile(player, zone="graveyard"):
    return [card.name for card in getattr(player, zone)]


def _w1g6_names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


# --- Piper's Melody ---------------------------------------------------------
# "Shuffle any number of target creature cards from your graveyard into your
# library." Gaea's Blessing's chosen cards out of the caster's own pile.

def _w1g6_melody(set_pool, **piles):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    piles.setdefault("yard", [
        lea["Grizzly Bears"], lea["Forest"], lea["Hill Giant"],
        lea["Grizzly Bears"], lea["Lightning Bolt"],
    ])
    return _w1g6_game(
        hand=[ody["Piper's Melody"]], library=[lea["Island"]] * 4,
        their_yard=[lea["Craw Wurm"]], **piles,
    )  # _w1g6_melody


def test_w1g6_pipers_melody_offers_only_your_own_creature_cards(set_pool):
    game = _w1g6_melody(set_pool)
    spec = game.cast_target_spec(0, set_pool("ODY")["Piper's Melody"])

    assert spec["own_graveyard_only"] and spec["card_type"] == "creature"
    assert [(t["seat"], t["index"], t["name"]) for t in spec["valid_targets"]] == [
        (0, 0, "Grizzly Bears"), (0, 2, "Hill Giant"), (0, 3, "Grizzly Bears"),
    ]


def test_w1g6_pipers_melody_shuffles_in_exactly_the_cards_named(set_pool):
    game = _w1g6_melody(set_pool)

    # Both copies of one card: the same object in the pile twice.
    cast = game.queue_from_hand(
        0, "Piper's Melody", target_player_index=0, target_permanent_index=[0, 3]
    )
    assert cast.supported, cast.details
    named = _w1g6_chosen_targets(game, game.stack[-1])
    assert [(t.stamp.card.name, t.stamp.ordinal) for t in named] == [
        ("Grizzly Bears", 0), ("Grizzly Bears", 1),
    ]
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[0]) == [
        "Forest", "Hill Giant", "Lightning Bolt", "Piper's Melody",
    ]
    assert sorted(_w1g6_pile(game.players[0], "library")) == [
        "Grizzly Bears", "Grizzly Bears", "Island", "Island", "Island", "Island",
    ]


def test_w1g6_pipers_melody_may_name_none_and_still_resolves(set_pool):
    game = _w1g6_melody(set_pool)

    cast = game.queue_from_hand(0, "Piper's Melody")
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)

    assert len(game.players[0].graveyard) == 6   # the five, and the Melody
    assert len(game.players[0].library) == 4


@_w1g6_pytest.mark.parametrize(
    "seat, slots",
    [
        (0, [1]),      # the Forest is not a creature card
        (1, [0]),      # the opponent's Craw Wurm is not in your graveyard
        (0, [0, 0]),   # one card cannot fill two of the slots (CR 115.3)
    ],
)
def test_w1g6_pipers_melody_refuses_a_card_its_picker_does_not_offer(
    set_pool, seat, slots
):
    game = _w1g6_melody(set_pool)

    refused = game.queue_from_hand(
        0, "Piper's Melody", target_player_index=seat, target_permanent_index=slots
    )

    assert not refused.supported
    assert _w1g6_pile(game.players[0], "hand") == ["Piper's Melody"]
    assert len(game.players[0].graveyard) == 5 and len(game.players[0].library) == 4


def test_w1g6_pipers_melody_does_not_replace_a_target_that_left(set_pool):
    game = _w1g6_melody(set_pool)
    cast = game.queue_from_hand(
        0, "Piper's Melody", target_player_index=0, target_permanent_index=[0, 2]
    )
    assert cast.supported
    game.players[0].graveyard.pop(2)   # the Hill Giant leaves in response
    _w1g6_resolve_stack(game)

    # One Bears went in; the other Bears, never named, stayed (CR 608.2b).
    assert sorted(_w1g6_pile(game.players[0], "library")).count("Grizzly Bears") == 1
    assert _w1g6_pile(game.players[0]).count("Grizzly Bears") == 1


# --- Decompose --------------------------------------------------------------
# "Exile up to three target cards from a single graveyard." Driven. The pile
# and the cards are picked as it resolves (Ebony Charm's shipped route, a
# stated deviation from CR 601.2c): one graveyard, and up to three out of it.

def test_w1g6_decompose_exiles_up_to_three_cards_out_of_one_graveyard(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Decompose"]], yard=[lea["Forest"], lea["Island"]],
        their_yard=[
            lea["Hill Giant"], lea["Lightning Bolt"], lea["Craw Wurm"], lea["Sol Ring"],
        ],
    )
    game.interactive_seats = {0, 1}

    assert game.queue_from_hand(0, "Decompose").supported
    game.resolve_top_of_stack()
    pile = game.pending_choices[0]
    assert (pile.kind, pile.player_index, pile.data["seats"]) == (
        "graveyard_pile_choice", 0, [0, 1],
    )
    assert game.confirm_graveyard_pile_choice(0, 1)
    pick = game.pending_choices[0]
    assert (pick.kind, pick.data["owner_index"], pick.data["count"], pick.data["up_to"]) == (
        "graveyard_exile_pick", 1, 3, True,
    )
    # Four is more than three, and a card of the other pile is not in this one.
    assert not game.confirm_graveyard_exile_pick(0, [0, 1, 2, 3])
    assert game.confirm_graveyard_exile_pick(0, [0, 2, 3])
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Lightning Bolt"]
    assert sorted(_w1g6_pile(game.players[1], "exile")) == [
        "Craw Wurm", "Hill Giant", "Sol Ring",
    ]
    assert _w1g6_pile(game.players[0]) == ["Forest", "Island", "Decompose"]


def test_w1g6_decompose_with_no_card_anywhere_resolves_and_exiles_nothing(set_pool):
    game = _w1g6_game(hand=[set_pool("ODY")["Decompose"]])
    game.interactive_seats = {0, 1}

    assert game.queue_from_hand(0, "Decompose").supported
    _w1g6_resolve_stack(game)

    assert not game.pending_choices
    assert _w1g6_pile(game.players[0]) == ["Decompose"]


# --- Zombify ----------------------------------------------------------------
# "Return target creature card from your graveyard to the battlefield." Driven.

def test_w1g6_zombify_returns_the_creature_card_it_was_aimed_at(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Zombify"]],
        yard=[lea["Forest"], lea["Craw Wurm"], lea["Hill Giant"]],
        their_yard=[lea["Shivan Dragon"]],
    )

    # Not a land card, and not somebody else's creature card.
    assert not game.queue_from_hand(
        0, "Zombify", target_player_index=0, target_permanent_index=0
    ).supported
    assert not game.queue_from_hand(
        0, "Zombify", target_player_index=1, target_permanent_index=0
    ).supported

    cast = game.queue_from_hand(
        0, "Zombify", target_player_index=0, target_permanent_index=2
    )
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)

    assert _w1g6_names(game, 0) == ["Hill Giant"]
    assert _w1g6_pile(game.players[0]) == ["Forest", "Craw Wurm", "Zombify"]


def test_w1g6_zombify_does_nothing_when_its_target_has_left(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Zombify"]], yard=[lea["Craw Wurm"], lea["Hill Giant"]],
    )
    assert game.queue_from_hand(
        0, "Zombify", target_player_index=0, target_permanent_index=0
    ).supported
    game.players[0].graveyard.pop(0)
    _w1g6_resolve_stack(game)

    # CR 608.2b: the other creature card is not reanimated in its place.
    assert _w1g6_names(game, 0) == []
    assert _w1g6_pile(game.players[0]) == ["Hill Giant", "Zombify"]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
# (moved whole to test_ody_sorceries_later_groups.py when this file reached its size cap)

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
