"""What a seat nobody asked does with a free "you may …" offer.

``_default_optional_pay`` decided by **affordability**, which for a free offer
is vacuously true — so every free offer was accepted, and nobody chose that.
It was right for a gift ("you may draw a card") and wrong for a price the
grammar had put somewhere the affordability test could not look: "you may
sacrifice another creature", "you may ante the top card of your library". Those
are costs printed as deeds rather than as mana, and the seat paid them every
time it was not asked.

The policy now is one line — **take gifts, pay tolls, make no trades** — and
both halves of it are read off the compiled program:

* the *price* is ``ai_valuation.offered_action_is_a_payment``, over the
  instruction kinds the rules define as done to oneself (CR 701.21a, 701.9a,
  118.3b, 407.4, 701.13a). A kind, never a card name, so the eight cards in the
  pool that print "you may sacrifice …" and every card still to come are
  classified by construction;
* the *penalty* is whether the offer has an "if you don't" branch at all. With
  one, refusing is not free either and which of two losses is smaller is the
  seat's judgement rather than a default's.

These tests ask the property of **every** free offer the pool compiles, found
by walking the programs rather than by naming cards, so a newly ingested card
is covered the day it is ingested.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_valuation import SELF_PAYMENT_KINDS, offered_action_is_a_payment
from engine.handlers.registry import EFFECT_HANDLERS
from engine.oracle import compile_card_oracle
from engine.pending_choices import PendingChoice

#: Payload keys that hold nested instructions. The walk has to be wide because a
#: ``may`` can sit under any of them — Oath of Lim-Dûl's is under ``effect`` (a
#: ``for_each`` body), Tolarian Kraken's under ``reflexive`` (CR 603.12), Mystic
#: Remora's under ``otherwise``.
_NESTED_KEYS = (
    "steps", "then", "otherwise", "else", "action", "instruction",
    "unpaid", "reflexive", "effect", "option_effects",
)

#: The actors whose offer rebinds the resolution's ``caster`` **and** ``target``
#: to the offered seat, mirroring ``handlers/control_flow._EACH_ACTORS``.
_REBINDING_ACTORS = frozenset({"each_player", "each_opponent", "defending_player"})
#: The actors whose offer is made to a seat the ability already chose: the
#: back-reference names them, the resolution's controller does not.
_OTHER_SEAT_ACTORS = frozenset({"that_player", "target_opponent", "controller"})


def _walk(instruction):
    yield instruction
    for key in _NESTED_KEYS:
        value = instruction.payload.get(key) or ()
        if not isinstance(value, (list, tuple)):
            continue
        for item in value:
            nested = item if isinstance(item, (list, tuple)) else (item,)
            for step in nested:
                if hasattr(step, "payload"):
                    yield from _walk(step)


def _program_instructions(program):
    for instruction in program.instructions:
        yield from _walk(instruction)
    for ability in program.activated_abilities:
        if ability.instruction is not None:
            yield from _walk(ability.instruction)
    for ability in program.triggered_abilities:
        if ability.instruction is not None:
            yield from _walk(ability.instruction)


def _free_offers(catalog):
    """Every free ``may`` every supported card in the pool compiles.

    "Free" as the *entry* states it: no mana cost, no life cost and no CR 118.8
    alternative. A printed cost is already answered correctly — the seat spends
    what is floating and taps nothing — and this is the half nobody chose.
    """
    seen = set()
    for card in sorted(catalog, key=lambda c: c.name):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for instruction in _program_instructions(program):
            if instruction.kind != "may":
                continue
            payload = instruction.payload
            if (
                payload.get("cost")
                or payload.get("life_cost")
                or payload.get("cost_alternatives")
            ):
                continue
            action = tuple(payload.get("action") or ())
            then = tuple(payload.get("then") or ())
            otherwise = tuple(payload.get("otherwise") or ())
            key = (
                card.name,
                tuple(step.kind for step in action),
                tuple(step.kind for step in then),
                tuple(step.kind for step in otherwise),
            )
            if key in seen:
                continue
            seen.add(key)
            yield card, payload, action + then, otherwise


def _decision(accept_steps, otherwise, actor: str) -> str:
    """The engine's own answer, through the method the default calls.

    The entry is built the way ``handlers/control_flow._offer_to_seat`` builds
    it — accept branch as ``action`` then ``then``, decline branch as
    ``otherwise`` — because that convention is what the default reads, and a
    test that rebuilt it differently would stop noticing if the handler changed
    its mind.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    seat = game.players[0]
    other = game.players[1]

    class _Context:
        caster = seat if actor not in _OTHER_SEAT_ACTORS else other
        target = seat if actor != "you" else other

    entry = {
        "card_name": "probe",
        "cost": {},
        "life_cost": 0,
        "_on_accept": tuple(accept_steps),
        "_on_decline": tuple(otherwise),
        "_context": _Context(),
    }
    choice = PendingChoice("optional_pay", 0, entry)
    return "decline" if game._offer_is_an_unpriced_trade(choice) else "accept"


def _expected(accept_steps, otherwise, actor: str) -> str:
    """The same answer re-derived from the printed shape, in the terms the
    policy is stated in — a price with no penalty is refused, everything else
    is taken."""
    if otherwise:
        return "accept"
    recipients = {"caster"}
    if actor in _REBINDING_ACTORS:
        recipients |= {"target", "target_player"}
    elif actor in _OTHER_SEAT_ACTORS:
        recipients = {"target", "target_player"}
    return "decline" if offered_action_is_a_payment(accept_steps, recipients) else "accept"


def test_every_self_payment_kind_is_a_live_instruction_kind():
    """``MANA_ABILITY_KINDS``' guard, for the same reason it exists: the set it
    replaced named two kinds that had both been renamed out from under it, so
    the check it guarded silently stopped firing. A rename that emptied
    ``SELF_PAYMENT_KINDS`` would silently restore the always-accept default —
    no error, no missing behaviour, just a seat paying every price again."""
    missing = sorted(SELF_PAYMENT_KINDS - set(EFFECT_HANDLERS))
    assert not missing, missing


def test_every_self_payment_kind_is_still_printed_by_the_pool(catalog):
    """Both directions, the way ``test_effect_labels`` holds its tables: a kind
    nothing in the pool offers is a claim about a card that is not there, and a
    frozen list nothing checks rots into a description of a pool that has moved
    on. Prune for cause, not by guesswork."""
    offered = set()
    for _card, _payload, accept, _otherwise in _free_offers(catalog):
        for step in accept:
            offered.add(step.kind)
            for mode in step.payload.get("modes") or ():
                if isinstance(mode, dict) and mode.get("instruction") is not None:
                    offered.add(mode["instruction"].kind)
    unreached = sorted(SELF_PAYMENT_KINDS - offered)
    assert not unreached, unreached


def test_the_pools_free_offers_are_decided_by_shape_and_nothing_else(catalog):
    """The whole policy, asked of every free offer the pool compiles.

    Derived twice over: the offers come from walking the compiled programs, and
    the expected answer comes from the printed shape (is the offered deed a
    price? does refusing cost anything?). No card is named on either side, so a
    newly ingested "you may sacrifice a Forest" is covered the day it lands.
    """
    disagreements = []
    for card, payload, accept, otherwise in _free_offers(catalog):
        actor = payload.get("actor", "you")
        got = _decision(accept, otherwise, actor)
        want = _expected(accept, otherwise, actor)
        if got != want:
            disagreements.append((card.name, got, want))
    assert not disagreements, disagreements


def test_the_pool_holds_free_offers_of_both_kinds(catalog):
    """Neither half of the policy may pass vacuously. A sweep that found no
    price would agree with an always-accept default, and a sweep that found no
    gift would agree with an always-decline one — and both are what this round
    was fixing."""
    decisions = [
        _decision(accept, otherwise, payload.get("actor", "you"))
        for _card, payload, accept, otherwise in _free_offers(catalog)
    ]
    assert decisions.count("decline") >= 5, decisions
    assert decisions.count("accept") >= 20, decisions


def test_a_toll_is_still_paid_because_refusing_it_is_not_free(catalog):
    """The line the policy draws, asked of the pool rather than asserted about
    one card: **no** offer with a printed "if you don't" branch is refused by
    the default, however expensive taking it is. Elder Spawn's Island is a
    price and so is the 6 damage and the 7/7 behind refusing it; picking the
    cheaper is valuation, and a default that guessed would guess wrong on
    Season of the Witch (2 life against the enchantment) in the same breath as
    it guessed right on Curse Artifact."""
    refused_tolls = [
        card.name
        for card, payload, accept, otherwise in _free_offers(catalog)
        if otherwise
        and _decision(accept, otherwise, payload.get("actor", "you")) == "decline"
    ]
    assert not refused_tolls, refused_tolls


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("sacrifice_matching_permanent", True),
        ("discard_controller_cards", True),
        ("pay_life", True),
        ("ante_top_card", True),
        ("draw_controller_cards", False),
        ("search_library", False),
        ("remove_counter_from_self", False),
    ],
)
def test_the_leading_step_is_what_the_sentence_offers(kind, expected):
    """"You may **A**. If you do, B." — the grammar splits the sentence at the
    comma and ``_offer_to_seat`` concatenates ``action`` then ``then``, so A
    leads. Reading the branch as a whole would make Sylvan Library ("draw two
    additional cards … then pay 4 life or put the card back") a price and Crypt
    Lurker ("sacrifice a creature … draw a card") a gift, which is both answers
    exactly backwards.

    ``remove_counter_from_self`` is the deliberate exclusion: Living Artifact's
    counters are not an object anybody owns (CR 122.1), so trading one for a
    life is the card working rather than a price being paid.
    """
    from engine.oracle_types import OracleInstruction

    steps = (
        OracleInstruction(kind, "", {}),
        OracleInstruction("draw_controller_cards", "", {"amount": 1}),
    )
    assert offered_action_is_a_payment(steps, {"caster"}) is expected


# ---------------------------------------------------------------------------
# The same policy one layer in: a "Choose one —" whose alternatives are not
# alike. ``_default_mode_choice`` took printed order, which is a fine policy
# while the modes are two ways of doing the same size of thing and a bad one
# the moment a price is printed beside a free alternative.
# ---------------------------------------------------------------------------


def _modal_choices(catalog):
    """Every ``choose_one`` the pool compiles, with its modes' instructions."""
    seen = set()
    for card in sorted(catalog, key=lambda c: c.name):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for instruction in _program_instructions(program):
            if instruction.kind != "choose_one":
                continue
            modes = [
                mode for mode in (instruction.payload.get("modes") or ())
                if isinstance(mode, dict) and mode.get("instruction") is not None
            ]
            if not modes:
                continue
            key = (card.name, tuple(mode["label"] for mode in modes))
            if key in seen:
                continue
            seen.add(key)
            yield card, modes


def _mode_taken(modes) -> int:
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])

    class _Context:
        caster = game.players[0]
        target = game.players[1]

    choice = PendingChoice("mode_choice", 0, {
        "card_name": "probe",
        "labels": [mode["label"] for mode in modes],
        "_modes": tuple(mode["instruction"] for mode in modes),
        "_context": _Context(),
    })
    return game._first_unpriced_mode(choice)


def test_a_modal_choice_prefers_an_alternative_that_costs_the_chooser_nothing(catalog):
    """Asked of every modal choice in the pool, by shape: the first alternative
    that is not paid out of the chooser's own resources, and printed order when
    every one of them is (Crypt Lurker's "sacrifice a creature or discard a
    creature card" — two prices, and picking the smaller is valuation)."""
    wrong = []
    for card, modes in _modal_choices(catalog):
        priced = [
            offered_action_is_a_payment((mode["instruction"],), {"caster"})
            for mode in modes
        ]
        want = next((i for i, p in enumerate(priced) if not p), 0)
        got = _mode_taken(modes)
        if got != want:
            wrong.append((card.name, got, want))
    assert not wrong, wrong


def test_the_pool_still_contains_a_modal_choice_that_is_not_uniform(catalog):
    """The guard above passes vacuously if every modal in the pool offers two
    alternatives of the same kind. Exactly one does not, which is why printed
    order survived this long."""
    mixed = [
        card.name
        for card, modes in _modal_choices(catalog)
        if len({
            offered_action_is_a_payment((mode["instruction"],), {"caster"})
            for mode in modes
        }) > 1
    ]
    assert mixed, "no modal choice mixes a price with a free alternative"
