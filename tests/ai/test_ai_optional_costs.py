"""The AI answers CR 601.2b's optional additional costs — every one, not kicker.

``CastAction.optional_cost_payments`` existed and both executors forwarded it,
but ``ai_policy._cast_candidate`` asked one question: does this card print a
kicker? So no AI seat ever bought a spell back, and Primitive Justice was always
cast for one artifact. 31 shipped cards print such an offer; half of each was
unreachable in simulation.

Which offers a card makes and what each buys is derived
(``ai_valuation.cast_offers``); how far a seat goes for one is the policy
(``ai_policy._times_worth_taking``). Both are held here: the derivation against
the pool and against cards nobody printed, the policy by what a seat does at a
table.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import (
    BUYBACK_LIFE_RESERVE,
    BUYBACK_PERMANENTS_KEPT,
    _cast_candidate,
    choose_cast_action,
    tap_planned_lands,
)
from engine.ai_simulator import run_ai_simulation
from engine.ai_valuation import (
    OFFER_ADDS,
    OFFER_ALTERS,
    OFFER_KICKS,
    OFFER_RETURNS_SPELL,
    cast_offers,
)
from engine.card_loader import manifest_set_path
from engine.faces import castable_faces
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack


def _w2g6_table(
    cards, hand, lands, *, theirs=(), mine=(), life=20, enforce=True,
) -> Game:
    me = PlayerState(
        name="Me", life=life,
        hand=[cards[name] if isinstance(name, str) else name for name in hand],
        battlefield=[Permanent(card=cards[name]) for name in (*lands, *mine)],
        library=[cards["Forest"]] * 10,
    )
    you = PlayerState(
        name="You",
        battlefield=[Permanent(card=cards[name]) for name in theirs],
        library=[cards["Forest"]] * 10,
    )
    game = Game(players=[me, you], enforce_mana_costs=enforce)
    game._sync_control()
    game.turn = 5
    game.begin_turn_bookkeeping(0)
    game._enter_main_phase(precombat=True)
    return game


def _w2g6_cast(game: Game, action):
    """Carry *action* out the way both executors do: tap, then announce."""
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(
        0, action.card_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
        x_value=action.x_value,
        alternative_cost=action.alternative_cost,
        divided_targets=action.divided_targets,
        optional_cost_payments=action.optional_cost_payments,
    )
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    return result


def _w2g6_untapped_lands(game: Game) -> int:
    return sum(
        1 for permanent in game.controlled_by(0)
        if permanent.card.primary_type == "land" and not permanent.tapped
    )


# --- which cards, and what each offer buys: derived --------------------------


def test_w2g6_every_shipped_offer_is_read_and_classified(catalog):
    """The population, with a floor: 31 shipped cards make an optional offer —
    28 buybacks, the two "any number of times" spells and Undergrowth — and
    every one is classified by what the payment buys."""
    by_what: dict[str, list[str]] = {}
    examined = 0
    for whole in catalog:
        for card in castable_faces(whole):
            examined += 1
            for offer in cast_offers(card):
                by_what.setdefault(offer.buys, []).append(card.name)
                assert (offer.mana is None) != (offer.price is None), card.name

    assert examined >= 4_300
    assert len(by_what[OFFER_RETURNS_SPELL]) >= 28
    assert {"Capsize", "Constant Mists", "Slaughter", "Forbid", "Flowstone Flood"} <= set(
        by_what[OFFER_RETURNS_SPELL]
    )
    assert {"Primitive Justice", "Taste of Paradise"} <= set(by_what[OFFER_ADDS])
    assert by_what[OFFER_ALTERS] == ["Undergrowth"], (
        "a second offer whose paid spell is a different spell rather than a "
        "larger one: the policy declines these, so decide whether it should"
    )


def test_w2g6_an_offer_is_classified_by_what_it_buys_not_by_its_name():
    """Invented cards: the keyword spelled out as its own rules text, a
    kicker-shaped "more" under no keyword, and an offer nothing reads."""
    spelled_out = _mk_card(
        "Invented Recall", "{U}", "Instant",
        "Buyback {2}\nDraw a card.",
    )
    counted = _mk_card(
        "Invented Feast", "{G}", "Sorcery",
        "As an additional cost to cast this spell, you may pay {1}{G} any number of times.\n"
        "You gain 3 life plus an additional 3 life for each additional {1}{G} you paid.",
    )
    kicked = _mk_card(
        "Invented Bolt", "{R}", "Instant",
        "Kicker {2}\nInvented Bolt deals 2 damage to any target. If this spell was "
        "kicked, it deals 4 damage instead.",
    )

    assert [(o.key, o.buys, o.repeatable) for o in cast_offers(spelled_out)] == [
        ("{2}", OFFER_RETURNS_SPELL, False)
    ]
    assert [(o.key, o.buys, o.repeatable) for o in cast_offers(counted)] == [
        ("{1}{G}", OFFER_ADDS, True)
    ]
    assert [(o.key, o.buys) for o in cast_offers(kicked)] == [("{2}", OFFER_KICKS)]
    assert cast_offers(_mk_card("Invented Plain", "{R}", "Instant", "Draw a card.")) == ()


# --- buyback: with mana nothing else wants -------------------------------------


def test_w2g6_a_seat_buys_a_spell_back_when_the_lands_cover_both(catalog_by_name):
    """Capsize, {1}{U}{U} with buyback {3}: six Islands pay for both, the
    permanent is bounced and the card is back in hand; five do not, and the
    seat casts the plain spell rather than keeping it."""
    rich = _w2g6_table(catalog_by_name, ["Capsize"], ["Island"] * 6, theirs=["Grizzly Bears"])
    action = choose_cast_action(rich, 0)
    assert action.optional_cost_payments == {"{3}": 1}
    assert len(action.land_tap_indices) == 6
    assert _w2g6_cast(rich, action).supported
    assert [card.name for card in rich.players[0].hand] == ["Capsize"]
    assert rich.players[0].graveyard == []
    assert [card.name for card in rich.players[1].hand] == ["Grizzly Bears"]
    assert _w2g6_untapped_lands(rich) == 0 and not any(rich.players[0].mana_pool.values())

    short = _w2g6_table(catalog_by_name, ["Capsize"], ["Island"] * 5, theirs=["Grizzly Bears"])
    action = choose_cast_action(short, 0)
    assert action.optional_cost_payments is None
    assert _w2g6_cast(short, action).supported
    assert short.players[0].hand == []
    assert [card.name for card in short.players[0].graveyard] == ["Capsize"]
    assert _w2g6_untapped_lands(short) == 2


def test_w2g6_a_buyback_is_not_paid_with_mana_another_spell_wants(catalog_by_name):
    """An AI that always buys back is as wrong as one that never does. With
    six Islands, Capsize and a three-mana creature in hand, the six lands are
    two spells or one spell bought back — and the seat keeps its creature
    castable. With nine there is mana for all of it."""
    tight = _w2g6_table(
        catalog_by_name, ["Capsize", "Wind Drake"], ["Island"] * 6, theirs=["Grizzly Bears"],
    )
    capsize = _cast_candidate(tight, 0, catalog_by_name["Capsize"], 0)
    assert capsize.optional_cost_payments is None
    assert len(capsize.land_tap_indices) == 3

    spare = _w2g6_table(
        catalog_by_name, ["Capsize", "Wind Drake"], ["Island"] * 9, theirs=["Grizzly Bears"],
    )
    capsize = _cast_candidate(spare, 0, catalog_by_name["Capsize"], 0)
    assert capsize.optional_cost_payments == {"{3}": 1}
    assert len(capsize.land_tap_indices) == 6


def test_w2g6_a_buyback_paid_in_life_keeps_a_reserve(catalog_by_name):
    """Slaughter, "Buyback—Pay 4 life": taken from 20, declined from 12 —
    and declining still casts the spell."""
    healthy = _w2g6_table(catalog_by_name, ["Slaughter"], ["Swamp"] * 4, theirs=["Grizzly Bears"])
    action = choose_cast_action(healthy, 0)
    assert action.optional_cost_payments == {"pay 4 life": 1}
    assert _w2g6_cast(healthy, action).supported
    assert healthy.players[0].life == 16
    assert [card.name for card in healthy.players[0].hand] == ["Slaughter"]
    assert [card.name for card in healthy.players[1].graveyard] == ["Grizzly Bears"]

    low = BUYBACK_LIFE_RESERVE + 3
    hurt = _w2g6_table(
        catalog_by_name, ["Slaughter"], ["Swamp"] * 4, theirs=["Grizzly Bears"], life=low,
    )
    action = choose_cast_action(hurt, 0)
    assert action.optional_cost_payments is None
    assert _w2g6_cast(hurt, action).supported
    assert hurt.players[0].life == low
    assert [card.name for card in hurt.players[0].graveyard] == ["Slaughter"]


def test_w2g6_a_buyback_paid_in_lands_is_for_a_seat_with_lands_to_spare(catalog_by_name):
    """Constant Mists, "Buyback—Sacrifice a land": the engine's own candidate
    list is what is counted, so the land sacrificed is one the cost would take."""
    few = _w2g6_table(catalog_by_name, ["Constant Mists"], ["Forest"] * 4)
    assert choose_cast_action(few, 0).optional_cost_payments is None

    lands = BUYBACK_PERMANENTS_KEPT + 2
    many = _w2g6_table(catalog_by_name, ["Constant Mists"], ["Forest"] * lands)
    action = choose_cast_action(many, 0)
    assert action.optional_cost_payments == {"sacrifice a land": 1}
    assert _w2g6_cast(many, action).supported
    me = many.players[0]
    assert [card.name for card in me.hand] == ["Constant Mists"]
    assert [card.name for card in me.graveyard] == ["Forest"]
    assert sum(1 for p in many.controlled_by(0) if p.card.primary_type == "land") == lands - 1


# --- "any number of times": as many as the lands and the board allow ----------


def test_w2g6_a_repeatable_offer_is_paid_once_per_target_the_board_has(catalog_by_name):
    """Primitive Justice: each extra payment names another artifact
    (CR 601.2c), so the count is bounded by the lands *and* by the targets.
    Three artifacts and six lands are two payments and three destroyed; one
    artifact is the plain spell, with four lands left for something else."""
    lands = ["Mountain"] * 3 + ["Forest"] * 3
    three = _w2g6_table(
        catalog_by_name, ["Primitive Justice"], lands, theirs=["Sol Ring", "Mox Pearl", "Mox Jet"],
    )
    action = choose_cast_action(three, 0)
    assert sum(action.optional_cost_payments.values()) == 2
    assert _w2g6_cast(three, action).supported
    assert sorted(card.name for card in three.players[1].graveyard) == [
        "Mox Jet", "Mox Pearl", "Sol Ring",
    ]

    one = _w2g6_table(catalog_by_name, ["Primitive Justice"], lands, theirs=["Sol Ring"])
    action = choose_cast_action(one, 0)
    assert action.optional_cost_payments is None
    assert len(action.land_tap_indices) == 2
    assert _w2g6_cast(one, action).supported
    assert [card.name for card in one.players[1].graveyard] == ["Sol Ring"]


def test_w2g6_a_destroy_with_an_exact_count_is_not_aimed_at_the_casters_own(catalog_by_name):
    """Found while sizing the count: with no artifact across the table the
    several-target chooser fell back to the caster's own board, so Primitive
    Justice destroyed its controller's Sol Ring. An exact count every slot of
    which wants an opponent's permanent has no announcement on this board."""
    game = _w2g6_table(
        catalog_by_name, ["Primitive Justice"], ["Mountain"] * 3 + ["Forest"] * 3,
        mine=["Sol Ring"],
    )
    assert _cast_candidate(game, 0, catalog_by_name["Primitive Justice"], 0) is None


def test_w2g6_a_repeatable_offer_with_no_target_is_paid_as_often_as_the_lands_can(catalog_by_name):
    """Taste of Paradise, {3}{G} and "{1}{G} any number of times": eight
    Forests are the spell and two payments — 3 + 3 + 3 life."""
    game = _w2g6_table(catalog_by_name, ["Taste of Paradise"], ["Forest"] * 8)
    action = choose_cast_action(game, 0)
    assert action.optional_cost_payments == {"{1}{G}": 2}
    assert _w2g6_cast(game, action).supported
    assert game.players[0].life == 29
    assert _w2g6_untapped_lands(game) == 0


def test_w2g6_an_offer_that_changes_the_spell_is_declined(catalog_by_name):
    """Undergrowth's paid Fog spares red creatures — whoever controls them.
    The policy has no reading of which the board wants, so it is declined,
    stated, and counted in the census above as the pool's one such card."""
    game = _w2g6_table(
        catalog_by_name, ["Undergrowth"], ["Forest", "Mountain", "Mountain", "Mountain"],
    )
    action = choose_cast_action(game, 0)
    assert action is not None and action.optional_cost_payments is None
    assert len(action.land_tap_indices) == 1


# --- the engine takes what the policy proposes --------------------------------


def _w2g6_offer_cards(pool):
    return [
        (whole, card) for whole in pool for card in castable_faces(whole)
        if cast_offers(card) and compile_card_oracle(card).supported
    ]


def test_w2g6_no_announcement_the_ai_makes_is_refused(catalog, catalog_by_name, set_cards):
    """What the AI proposes is this group's; what the engine refuses is
    another's. So: every card that makes an offer, on a board rich enough to
    take it, cast exactly as proposed. A refusal here is a seat re-proposing
    the same card every turn for the rest of the game.

    Over the shipped pool and Invasion's kickers (while it is measured, and
    after), with floors on how many cards were examined and how many of them
    the seat actually paid extra for.
    """
    lands = ["Plains", "Island", "Swamp", "Mountain", "Forest"] * 3
    theirs = ["Grizzly Bears", "Sol Ring", "Mox Pearl", "Mox Jet", "Castle",
              "Serra Angel", "Forest", "Hill Giant"]
    seen = {card.name for card in catalog}
    pool = list(catalog) + [card for card in set_cards("INV") if card.name not in seen]
    examined = paid = 0
    refused = []
    for whole, card in _w2g6_offer_cards(pool):
        game = _w2g6_table(
            catalog_by_name, [whole], lands, theirs=theirs,
            mine=["Grizzly Bears", "Hill Giant"],
        )
        game.players[0].graveyard = [catalog_by_name["Grizzly Bears"]]
        game.players[1].graveyard = [catalog_by_name["Grizzly Bears"]]
        examined += 1
        action = _cast_candidate(game, 0, card, 0)
        if action is None:
            continue
        paid += bool(action.optional_cost_payments)
        result = _w2g6_cast(game, action)
        if not result.supported:
            refused.append((card.name, action.optional_cost_payments, result.details))

    assert examined >= 55, f"only {examined} offer cards examined"
    assert paid >= 50, f"the seat paid an optional cost on only {paid} of {examined}"
    assert not refused, refused


@pytest.mark.slow
def test_w2g6_a_simulated_seat_buys_a_spell_back():
    """The Rock Hydra test. Tempest is the set buyback was printed in; before
    this, ten games of it bought back nothing, because nothing could. Counted
    in the log the resolution itself writes, and with nothing refused for an
    additional cost — a refusal is the policy proposing what it cannot pay."""
    report = run_ai_simulation(manifest_set_path("TMP"), games=6, seed=1337, max_turns=18)
    bought = [line for line in report.log_lines if "(buyback)" in line]

    assert len(bought) >= 5, f"{len(bought)} buyback(s) in six games of Tempest"
    assert not report.issues, [issue.message for issue in report.issues]
    assert not [why for why in report.refused_casts if "additional cost" in why]
    assert report.steps_left_owing == {}
