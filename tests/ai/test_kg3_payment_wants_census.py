"""What a payment's wants could not see: a census for each later cost.

Round kg2 gave every planner the payer's wants (``mana_wants.mana_wants``)
and the preference that spares them (``mana_payment._sparing_choice``);
Legions' closer C2 added a face-down spell's own turn-up. Three later costs
were still not wants, so a payment could spend the very sources they needed:

* **a permanent spell's own activated abilities** — the payment is the card's
  cast, and nothing told the wants so: Shivan Dragon cast on Mountains and
  Plains could take the Mountains for its generic and leave its own
  firebreathing {R} unpayable;
* **a card the seat may cast from its graveyard** (flashback, CR 702.34a) —
  ``mana_wants`` read no graveyard at all;
* **the flashback of an instant or sorcery cast from the hand** — it lands in
  the graveyard as it resolves (CR 608.2n), and its flashback is the next
  price it asks.

Now the caller says what the payment is (``mana_wants(cast=…)``, from
``_PaymentPlanner.spell``, the web auto-tap's purpose and the cast path's
floating spend), and the wants read what a card leaves behind
(``mana_wants.wants_left_behind``) and what the seat may cast from outside its
hand (``ai_weighed_cast.permitted_casts``, at the permission's price).

**The census.** C2's shape: for each of kg2's boards and each row — a card
whose cast and later cost the board can pay together — the card goes where it
is (the hand, or the graveyard beside a spell in hand), the payment is planned
the way each planner plans it, and the rest of the board is asked for the
later cost. A **strand** is a row where it cannot although some set of
sources would have paid the first cost and left the later one payable
(``_sources_leave``). Each part runs backwards with its want switched off and
must find strands.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

import pytest

from engine import mana_wants as wants_module
from engine.activation_zones import HAND
from engine.ai_payment import _PaymentPlanner, _paying_for
from engine.flashback import printed_flashback_cost
from engine.mana_payment import is_mana_ability, mana_cost_label, mana_cost_x_as_zero, plan_payment
from engine.oracle import compile_card_oracle
from engine.search_filters import card_has_type
from engine.targeting import usable_activated_abilities
from tests.ai.test_kg2_payment_colour_census import (
    BOARDS, _CARDS, _board, _cost, _real_costs, _sources_leave, _together,
)
from tests.helpers import stable_sample
from web.payment_plan import planned_taps, unpaid_costs


def _in_main_phase(game):
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return game


def _land_boards():
    return {
        label: names for label, names in BOARDS.items()
        if all(_CARDS[name].primary_type == "land" for name in names)
        or label == "a Llanowar Elves"
    }


# -- the rows ------------------------------------------------------------------


def _ability_cards() -> dict:
    """``{(cost, ability cost): card}`` — one supported permanent card per
    distinct pair of its printed mana cost and the mana of a battlefield
    activated ability that is not a mana ability and that it could activate
    the turn it arrives (no {T} on a creature without haste, CR 302.6). No
    card with an ability that works from the hand, so the card is the one
    want in it."""
    found: dict = {}
    for name in sorted(_CARDS):
        card = _CARDS[name]
        if card.primary_type in ("land", "instant", "sorcery"):
            continue
        cost = mana_cost_x_as_zero(card.mana_cost or "")
        if not cost:
            continue
        program = compile_card_oracle(card)
        if not program.supported or usable_activated_abilities(program, zone=HAND):
            continue
        creature = card_has_type(card, "creature")
        hasty = any(str(k).lower() == "haste" for k in card.keywords or ())
        for ability in usable_activated_abilities(program):
            if ability.cost is None or is_mana_ability(ability):
                continue
            if ability.cost.requires_tap and creature and not hasty:
                continue
            mana = {s: int(n) for s, n in (ability.cost.mana or {}).items() if int(n or 0) > 0}
            if not mana:
                continue
            found.setdefault((mana_cost_label(cost), mana_cost_label(mana)), card)
            break
    return found


def _flashback_cards() -> dict:
    """``{(cost, flashback cost): card}`` — one supported instant or sorcery
    per distinct pair of its mana cost and its printed flashback cost's
    mana, {X} as 0."""
    found: dict = {}
    for name in sorted(_CARDS):
        card = _CARDS[name]
        if not (card_has_type(card, "instant") or card_has_type(card, "sorcery")):
            continue
        flashback = printed_flashback_cost(card)
        if flashback is None or not compile_card_oracle(card).supported:
            continue
        later = mana_cost_x_as_zero(flashback.mana or "")
        cost = mana_cost_x_as_zero(card.mana_cost or "")
        if not later or not cost:
            continue
        found.setdefault((mana_cost_label(cost), mana_cost_label(later)), card)
    return found


# -- the planners ---------------------------------------------------------------


def _ai_plan(game, card, required):
    with _paying_for(card):
        planner = _PaymentPlanner(game, game.players[0])
    return planner.plan(required)


def _web_plan(game, card, required):
    _result, asked = unpaid_costs(game, lambda table: table.cast_from_hand(0, card.name))
    if not asked:
        return None
    required, purpose = asked[0]
    return planned_taps(game, 0, required, purpose)


PLANNERS = {"ai": _ai_plan, "web": _web_plan}


def _left_pays(game, slots, later) -> bool:
    empty = _PaymentPlanner(game, game.players[0])
    left = [source for source in empty.sources if source.slot not in set(slots)]
    return empty._plan_with(left, later) is not None


def _cast_census(planner_name: str, cards: dict, every: int = 1) -> dict:
    """A card cast from the hand, alone there: does what it leaves behind
    stay payable?"""
    plan = PLANNERS[planner_name]
    found = {"examined": 0, "strands": [], "boards": set()}
    for label, names in _land_boards().items():
        bare = _board(names)
        empty = _PaymentPlanner(bare, bare.players[0])
        for (printed, later_printed), card in cards.items():
            if not stable_sample("|".join((label, printed, later_printed)), every):
                continue
            cost, later = _cost(printed), _cost(later_printed)
            if empty.plan(_together(cost, later)) is None or empty.plan(cost) is None:
                continue
            game = _in_main_phase(_board(names, hand=[card]))
            planned = plan(game, card, cost)
            if planned is None:
                continue  # refused for something other than mana (a target)
            found["examined"] += 1
            found["boards"].add(label)
            if _left_pays(game, planned[0], later):
                continue
            if _sources_leave(names, cost, later):
                found["strands"].append((
                    label, printed, later_printed, card.name,
                    [game.permanent_at(0, slot).card.name for slot in planned[0]],
                ))
    return found


#: One row in this many in the quick pass; the full pass (`MTG_FULL_CENSUS`)
#: examines every one.
_EVERY = 6
_EVERY_ABILITY = 2


def _graveyard_census(planner_name: str) -> dict:
    """A flashback card in the graveyard and a spell in hand: does the
    spell's payment leave the flashback payable? The AI planner, and the
    effect payer (``Game._pay_planned_cost``) for the same rows."""
    costs = _real_costs()
    flashbacks = _flashback_cards()
    found = {"examined": 0, "strands": [], "boards": set()}
    for label, names in _land_boards().items():
        if planner_name == "effect" and label == "a Llanowar Elves":
            continue
        bare = _board(names)
        empty = _PaymentPlanner(bare, bare.players[0])
        for printed, spell in costs.items():
            for (_fb_cost, later_printed), waiting in flashbacks.items():
                row = "|".join((label, printed, later_printed))
                if not stable_sample(row, _EVERY):
                    continue
                cost, later = _cost(printed), _cost(later_printed)
                if empty.plan(_together(cost, later)) is None or empty.plan(cost) is None:
                    continue
                game = _in_main_phase(_board(names, hand=[spell]))
                game.players[0].graveyard = [waiting]
                if planner_name == "ai":
                    slots = _ai_plan(game, spell, cost)[0]
                    paid = None
                else:
                    player = game.players[0]
                    game.players[0].hand = []

                    def planner(required, game=game, player=player):
                        return lambda: plan_payment(
                            player.mana_pool, game.payment_lands(0), required,
                            produces=game._land_payment_colors, payer=player,
                        )

                    assert game._pay_planned_cost(player, planner(cost)), row
                    paid = [p for p in game.controlled_by(0) if p.tapped]
                    slots = [game.battlefield_index_of(p) for p in paid]
                    player.mana_pool.clear()
                found["examined"] += 1
                found["boards"].add(label)
                if planner_name == "ai":
                    if _left_pays(game, slots, later):
                        continue
                else:
                    after = _PaymentPlanner(game, game.players[0])
                    if after.plan(later) is not None:
                        continue
                if _sources_leave(names, cost, later):
                    found["strands"].append((label, printed, later_printed, waiting.name))
    return found


@contextmanager
def _nothing_left_behind():
    """The tree before: a cast told the wants nothing of what it leaves."""
    with mock.patch.object(wants_module, "wants_left_behind", lambda card, **kw: ((), ())):
        yield


@contextmanager
def _no_graveyard():
    """The tree before: the wants read no zone but the hand and battlefield."""
    with mock.patch.object(wants_module, "_permitted_cast_wants", lambda *args: []):
        yield


# -- the tests ------------------------------------------------------------------


@pytest.fixture(scope="module", params=sorted(PLANNERS))
def ability_census(request):
    return request.param, _cast_census(request.param, _ability_cards(), _EVERY_ABILITY)


@pytest.fixture(scope="module", params=sorted(PLANNERS))
def flashback_cast_census(request):
    return request.param, _cast_census(request.param, _flashback_cards())


@pytest.fixture(scope="module", params=("ai", "effect"))
def graveyard_census(request):
    return request.param, _graveyard_census(request.param)


def test_a_permanent_spell_leaves_its_own_abilities_payable(ability_census):
    name, found = ability_census
    assert found["strands"] == [], (name, found["strands"][:10])
    assert found["examined"] >= 250 and len(found["boards"]) >= 8, (name, found["examined"])


def test_a_flashback_spell_cast_from_the_hand_leaves_its_flashback_payable(flashback_cast_census):
    name, found = flashback_cast_census
    assert found["strands"] == [], (name, found["strands"][:10])
    # Fewer on the web's side: a flashback spell that must name a target is
    # refused for that before the engine asks the pool for anything.
    assert found["examined"] >= 35 and len(found["boards"]) >= 8, (name, found["examined"])


def test_a_payment_leaves_a_graveyard_flashback_payable(graveyard_census):
    name, found = graveyard_census
    assert found["strands"] == [], (name, found["strands"][:10])
    assert found["examined"] >= 400 and len(found["boards"]) >= 8, (name, found["examined"])


@pytest.mark.full
def test_the_census_names_the_wants_left_out():
    """Backwards, each part with its want switched off: every planner
    strands. Measured over every row: a permanent's abilities 42 (AI) and
    41 (web) of ~700; a flashback cast 4 and 3; a graveyard flashback 47 (AI)
    and 116 (the effect payer) of a one-in-six sample."""
    with _nothing_left_behind():
        for name in PLANNERS:
            assert len(_cast_census(name, _ability_cards())["strands"]) >= 10, name
            assert len(_cast_census(name, _flashback_cards())["strands"]) >= 2, name
    with _no_graveyard():
        for name in ("ai", "effect"):
            assert len(_graveyard_census(name)["strands"]) >= 10, name
