"""Entwine (CR 702.42), the cost and the mode choice it buys.

    702.42a Entwine is a static ability of modal spells (see rule 700.2) that
    functions while the spell is on the stack. "Entwine [cost]" means "You may
    choose all modes of this spell instead of just the number specified. If
    you do, you pay an additional [cost]." Using the entwine ability follows
    the rules for choosing modes and paying additional costs in rules 601.2b
    and 601.2f–h.
    702.42b If the entwine cost was paid, follow the text of each of the modes
    in the order written on the card when the spell resolves.

``engine/entwine.py`` rewrites the keyword line into CR 601.2b's optional
additional cost, and an entwined cast is one whose ``mode_choices`` name every
mode (the "choose one or more" announcement) with that offer paid. These tests
drive the two halves together through the real cast path.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack


def _card(set_pool, name):
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _table(set_pool, hand=(), *, mine=(), theirs=(), graveyard=(), library=None):
    card = lambda name: _card(set_pool, name)  # noqa: E731
    game = Game(players=[
        PlayerState(
            "A", hand=[card(n) for n in hand],
            library=[card(n) for n in (library or ["Forest"] * 12)],
            graveyard=[card(n) for n in graveyard],
        ),
        PlayerState("B", library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


@pytest.mark.cr("702.42a", "601.2f")
def test_the_entwine_cost_is_paid_on_top_of_the_mana_cost(set_pool):
    """{5}{G} plus {G}{G}{G}: nine green from a pool of nine, both modes."""
    game, _mine, _theirs = _table(set_pool, ["One Dozen Eyes"])
    game.enforce_mana_costs = True
    game.players[0].mana_pool["G"] = 8
    short = game.cast_from_hand(0, "One Dozen Eyes", optional_cost_payments={"{G}{G}{G}": 1})
    assert not short.supported, "eight green paid for a nine-mana announcement"
    assert not game.players[0].battlefield
    game.players[0].mana_pool["G"] = 9
    paid = game.cast_from_hand(0, "One Dozen Eyes", optional_cost_payments={"{G}{G}{G}": 1})
    assert paid.supported, paid.details
    assert game.players[0].mana_pool["G"] == 0
    assert len(game.players[0].battlefield) == 6


@pytest.mark.cr("702.42a", "700.2a")
def test_every_mode_without_the_cost_and_the_cost_without_every_mode_are_refused(set_pool):
    game, _mine, _theirs = _table(set_pool, ["One Dozen Eyes"])
    every = [{"index": 0}, {"index": 1}]
    unpaid = game.cast_from_hand(0, "One Dozen Eyes", mode_choices=every)
    assert not unpaid.supported, unpaid.details
    partial = game.cast_from_hand(
        0, "One Dozen Eyes", optional_cost_payments={"{G}{G}{G}": 1},
        mode_choices=every[1:],
    )
    assert not partial.supported, partial.details
    assert not game.players[0].battlefield
    single = game.cast_from_hand(0, "One Dozen Eyes", mode_index=1)
    assert single.supported, single.details
    assert sorted(p.card.name for p in game.players[0].battlefield) == ["Insect Token"] * 5


@pytest.mark.cr("702.42a")
def test_a_paid_entwine_with_no_mode_named_chooses_every_mode(set_pool):
    """The announcement a headless caller makes: the cost alone. Each mode
    then names its own default target, as a mode of "choose one or more"
    does; a target named on the cast itself is refused, because it belongs
    to no one mode."""
    game, _mine, theirs = _table(set_pool, ["Dream's Grip", "Dream's Grip"], theirs=["Hill Giant"])
    named = game.cast_from_hand(
        0, "Dream's Grip", optional_cost_payments={"{1}": 1},
        target_player_index=1, target_permanent_ids=[theirs[0].permanent_id],
    )
    assert not named.supported and "on that mode" in named.details
    bare = game.cast_from_hand(0, "Dream's Grip", optional_cost_payments={"{1}": 1})
    assert bare.supported, bare.details
    assert any("Tapped" in line for line in game.log)
    assert any("Untapped" in line for line in game.log)


@pytest.mark.cr("702.42a", "601.2h")
def test_a_non_mana_entwine_is_paid_and_refused_when_it_cannot_be(set_pool):
    """"Entwine—Sacrifice two lands." (Solar Tide.) Paid during casting; with
    one land the cost cannot be paid and the spell is not cast."""
    game, mine, theirs = _table(
        set_pool, ["Solar Tide"], mine=["Plains", "Plains"], theirs=["Llanowar Elves", "Hill Giant"],
    )
    cast = game.cast_from_hand(0, "Solar Tide", optional_cost_payments={"sacrifice two lands": 1})
    assert cast.supported, cast.details
    assert not game.players[0].battlefield and not game.players[1].battlefield
    assert [c.name for c in game.players[0].graveyard].count("Plains") == 2

    game, _mine, theirs = _table(
        set_pool, ["Solar Tide"], mine=["Plains"], theirs=["Llanowar Elves", "Hill Giant"],
    )
    refused = game.cast_from_hand(0, "Solar Tide", optional_cost_payments={"sacrifice two lands": 1})
    assert not refused.supported
    assert all(game.is_on_battlefield(p) for p in theirs)


@pytest.mark.cr("700.2a", "702.42a")
def test_a_mode_with_no_legal_target_cannot_be_entwined(set_pool):
    """CR 700.2a: a mode that cannot choose its targets cannot be chosen, and
    an entwined cast chooses every mode — so Betrayal of Flesh with no creature
    card in its caster's graveyard can destroy a creature but not entwine."""
    game, _mine, theirs = _table(
        set_pool, ["Betrayal of Flesh"], mine=["Swamp"] * 3, theirs=["Grizzly Bears"],
    )
    entwined = game.cast_from_hand(
        0, "Betrayal of Flesh", optional_cost_payments={"sacrifice three lands": 1},
    )
    assert not entwined.supported, entwined.details
    assert len(game.players[0].battlefield) == 3, "no land was sacrificed"
    single = game.cast_from_hand(0, "Betrayal of Flesh", mode_index=0)
    assert single.supported, single.details
    assert not game.is_on_battlefield(theirs[0])


@pytest.mark.cr("702.42b", "608.2c")
def test_the_modes_resolve_in_printed_order(set_pool):
    """Promise of Power's ruling (2004-12-01): draw five, lose five life, then
    the Demon — "The five cards you draw count toward the Demon's power and
    toughness." Mode 1 named first changes nothing: the order is printed."""
    game, _mine, _theirs = _table(set_pool, ["Promise of Power"])
    cast = game.cast_from_hand(
        0, "Promise of Power", optional_cost_payments={"{4}": 1},
        mode_choices=[{"index": 1}, {"index": 0}],
    )
    assert cast.supported, cast.details
    (demon,) = game.players[0].battlefield
    assert (demon.effective_power, demon.effective_toughness) == (5, 5)
    drew = next(i for i, line in enumerate(game.log) if "draws 5" in line or "drew 5" in line.lower())
    made = next(i for i, line in enumerate(game.log) if "Demon" in line)
    assert drew < made, game.log


@pytest.mark.cr("702.42b", "608.2c")
def test_a_later_mode_waits_for_an_earlier_modes_answer(set_pool):
    """Tooth and Nail entwined, its caster asked: the search's prompt is owed
    and the second mode has not run; once it is answered, the hand the second
    mode chooses from holds what the search found."""
    game, _mine, _theirs = _table(
        set_pool, ["Tooth and Nail"], library=["Craw Wurm"] + ["Forest"] * 8,
    )
    game.interactive_seats = {0}
    cast = game.cast_from_hand(0, "Tooth and Nail", optional_cost_payments={"{2}": 1})
    assert cast.supported, cast.details
    assert [c.kind for c in game.pending_choices] == ["search_library"]
    assert game.confirm_search_library_picks(0, [{"zone": "library", "index": 0}])
    assert [c.kind for c in game.pending_choices] == ["choose_cards_in_hand"]
    assert game.confirm_choose_cards_in_hand(0, [0])
    resolve_stack(game)
    assert [p.card.name for p in game.players[0].battlefield] == ["Craw Wurm"]


@pytest.mark.cr("707.10", "700.2g")
def test_a_copy_of_an_entwined_spell_has_every_mode(set_pool):
    game, _mine, _theirs = _table(set_pool, ["One Dozen Eyes", "Fork"])
    assert game.queue_from_hand(
        0, "One Dozen Eyes", optional_cost_payments={"{G}{G}{G}": 1},
    ).supported
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported
    resolve_stack(game)
    names = sorted(p.card.name for p in game.players[0].battlefield)
    assert names == ["Beast Token"] * 2 + ["Insect Token"] * 10, names


@pytest.mark.cr("611.2c", "502.3")
def test_an_untap_step_lock_reaches_a_creature_that_arrived_afterwards(set_pool):
    """Blinding Beam's second mode modifies the rules of the game rather than
    any object's characteristics, so (CR 611.2c) it applies to a creature that
    was not on the battlefield when it began — the card's ruling, 2013-06-07."""
    game, _mine, theirs = _table(set_pool, ["Blinding Beam"], theirs=["Grizzly Bears"])
    theirs[0].tapped = True
    assert game.cast_from_hand(0, "Blinding Beam", mode_index=1, target_player_index=1).supported
    late = Permanent(card=_card(set_pool, "Hill Giant"))
    game._put_permanent_onto_battlefield(1, late, None)
    late.tapped = True
    game.start_turn(1)
    assert theirs[0].tapped and late.tapped, game.log
    assert not game.untap_step_locks, "the lock is spent by the step it named"


@pytest.mark.cr("608.2b")
def test_a_modes_graveyard_target_that_left_does_nothing(set_pool):
    """The second mode's card leaves in response; the first mode's creature is
    still legal, so the spell resolves, and the second mode returns nothing —
    not the other creature card still in the graveyard."""
    game, _mine, theirs = _table(
        set_pool, ["Betrayal of Flesh"], mine=["Swamp"] * 3, theirs=["Grizzly Bears"],
        graveyard=["Hill Giant", "Craw Wurm"],
    )
    assert game.queue_from_hand(
        0, "Betrayal of Flesh", optional_cost_payments={"sacrifice three lands": 1},
        mode_choices=[
            {"index": 0, "target_player_index": 1, "target_permanent_index": 0},
            {"index": 1, "target_player_index": 0, "target_permanent_index": 0},
        ],
    ).supported
    giant = game.players[0].graveyard.pop(0)
    game.players[0].exile.append(giant)
    resolve_stack(game)
    assert not game.is_on_battlefield(theirs[0])
    assert not game.players[0].battlefield
    assert "Craw Wurm" in [c.name for c in game.players[0].graveyard]


@pytest.mark.cr("702.42a")
def test_entwine_the_engine_cannot_honour_is_refused_not_dropped():
    """A card printing an entwine nothing can charge, or one on a spell with no
    modes to choose all of, reports unsupported naming it — the eleven readable
    Mirrodin printings compiled as a plain "choose one" before the keyword
    existed, supported and silently cheaper than printed."""
    unmodal = _mk_card(
        name="Entwine Probe", type_line="Instant", mana_cost="{U}",
        oracle_text="Draw a card.\nEntwine {2} (Choose both if you pay the entwine cost.)",
    )
    program = compile_card_oracle(unmodal)
    assert not program.supported and "no modes" in program.reason, program.reason
    unread = _mk_card(
        name="Entwine Probe X", type_line="Instant", mana_cost="{U}",
        oracle_text="Choose one —\n• Draw a card.\n• You gain 2 life.\nEntwine {X}",
    )
    program = compile_card_oracle(unread)
    assert not program.supported and "entwine" in program.reason, program.reason
    readable = _mk_card(
        name="Entwine Probe Ok", type_line="Instant", mana_cost="{U}",
        oracle_text="Choose one —\n• Draw a card.\n• You gain 2 life.\nEntwine {2}",
    )
    assert compile_card_oracle(readable).supported


@pytest.mark.cr("702.42a", "601.2b")
def test_the_cast_offer_names_the_entwine(set_pool):
    """The offer rides the card's own "modal" spec, labelled "entwine", for a
    mana cost and a non-mana one: taking it is choosing every mode, so a
    client asks it before the mode — and no single mode's spec offers it,
    because a one-mode cast that took it is refused."""
    game, _mine, _theirs = _table(
        set_pool, ["Dream's Grip", "Solar Tide"], mine=["Island", "Island", "Plains"],
    )
    for name, key in (("Dream's Grip", "{1}"), ("Solar Tide", "sacrifice two lands")):
        card = _card(set_pool, name)
        spec = game.cast_target_spec(0, card)
        assert spec["kind"] == "modal" and spec["entwine"] == key, spec
        assert [offer["label"] for offer in spec["cost_offers"]] == ["entwine"]
        assert spec["cost_offers"][0]["max_times"] == 1, "payable here"
        for index in (0, 1):
            mode_spec = game.cast_target_spec(0, card, mode_index=index)
            assert not mode_spec.get("cost_offers"), mode_spec
