"""Pool-wide: a card may print two kicker costs, and "kicked" has two questions.

CR 702.33b: "Kicker [cost 1] and/or [cost 2]" means "Kicker [cost 1], kicker
[cost 2]" — two optional additional costs on one card. CR 702.33d then makes
"was it kicked?" *any* of them, and CR 702.33f adds the second question: "if it
was kicked **with its [A] kicker**", an ability linked to one specific cost.

``tests/engine/test_kicker.py`` holds the one-cost arrangement (one rewrite, one
reader, one key). This file holds what a second cost can break, each of them
quiet, over every card in both manifest roles:

* **A reader that knows one key.** The offer is charged under the second cost's
  key and "kicked" looks under the first, so a Battlemage that paid only its
  second kicker resolves unkicked — to its own trigger, to Ertai's Trickery and
  to "whenever a player kicks a spell".
* **A condition naming a cost the card does not offer.** "Kicked with its
  {1}{G} kicker" lowered to a key no payment is ever recorded under is a
  trigger that can never fire on a card reporting itself supported.
* **A card that asks about a kicker it does not print.** ``was_kicked`` is
  answered from the asking object's own record, so on a card with no kicker it
  is False forever. Ertai's Trickery ("Counter target spell if it was kicked")
  was exactly that for as long as the pronoun was read as the spell asking:
  supported, hollow-free, fully claimed, and countering nothing.

Each census carries a floor on what it examined, because a guard over an empty
population passes.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import (additional_costs, is_kicker_line, kicked,
                               kicked_with, kicker_cost, kicker_costs,
                               kickers_paid)
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle, expand_ability_lines

#: Planeshift prints five; a later set raises it and an empty census fails.
_TWO_KICKER_FLOOR = 5
#: Two linked conditions on each of those five.
_NAMED_KICKER_CONDITION_FLOOR = 10
#: Invasion alone prints thirty-five kicker cards.
_KICKER_CARD_FLOOR = 30
#: Supported cards whose program asks ``was_kicked`` of themselves.
_SELF_QUESTION_FLOOR = 20


def _both_roles() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


@pytest.fixture(scope="module")
def pool() -> dict:
    return _both_roles()


@pytest.fixture(scope="module")
def two_kicker_cards(pool) -> list:
    cards = [
        card for card in pool.values()
        if len(kicker_costs(card.oracle_text or "")) >= 2
    ]
    assert len(cards) >= _TWO_KICKER_FLOOR, (
        f"only {len(cards)} two-kicker cards found; the census is reading the "
        "wrong pool"
    )
    return cards


def _conditions(value, kind: str):
    """Every condition payload of *kind* anywhere under *value*."""
    if isinstance(value, dict):
        if value.get("kind") == kind:
            yield value
        for inner in value.values():
            yield from _conditions(inner, kind)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _conditions(inner, kind)
    else:
        payload = getattr(value, "payload", None)
        if isinstance(payload, dict):
            yield from _conditions(payload, kind)


def _program_conditions(card, kind: str) -> list:
    program = compile_card_oracle(card)
    roots = list(program.instructions)
    roots += [a.instruction for a in program.triggered_abilities if a.instruction]
    roots += [a.instruction for a in program.activated_abilities if a.instruction]
    return list(_conditions(roots, kind))


def test_two_kickers_are_two_offers_under_the_keys_the_reader_asks(two_kicker_cards):
    """The rewrite, the cost table and ``kicker_costs`` agree on **both** keys,
    in printed order, and the compiler's text holds the sentence rather than
    the keyword line."""
    for card in two_kicker_cards:
        keys = kicker_costs(card.oracle_text)
        assert len(keys) == 2 and len(set(keys)) == 2, (card.name, keys)
        offered = [
            offer.symbols
            for cost in additional_costs(card)
            for offer in cost.optional_mana
        ]
        assert list(keys) == offered, (card.name, keys, offered)
        expanded = expand_ability_lines(card.oracle_text, card_name=card.name)
        assert not any(is_kicker_line(line) for line in expanded.split("\n")), card.name
        assert compile_card_oracle(card).supported, card.name


def test_the_singular_reader_never_disagrees_with_the_plural(pool):
    """``kicker_cost`` survives for callers that want one key to announce. It
    is the first of ``kicker_costs`` on every kicker card, and None exactly
    when that is empty — so no card is a kicker card to one reader and not to
    the other."""
    examined = 0
    for card in pool.values():
        text = card.oracle_text or ""
        if not any(is_kicker_line(line) for line in text.split("\n")):
            assert kicker_costs(text) == (), card.name
            continue
        examined += 1
        keys = kicker_costs(text)
        assert kicker_cost(text) == (keys[0] if keys else None), card.name
    assert examined >= _KICKER_CARD_FLOOR


def test_a_named_kicker_condition_names_a_cost_the_card_offers(pool):
    """CR 702.33f: "if it was kicked with its [A] kicker" is linked to one of
    the card's own kicker costs. The lowered key must therefore be one of
    ``kicker_costs`` — a key nothing records is a condition that never holds —
    and a card with two kickers must ask about each of them somewhere."""
    named = 0
    for card in pool.values():
        if not compile_card_oracle(card).supported:
            continue
        asked = [
            condition["kicker"]
            for condition in _program_conditions(card, "was_kicked")
            if "kicker" in condition
        ]
        if not asked:
            continue
        keys = kicker_costs(card.oracle_text or "")
        for key in asked:
            named += 1
            assert key in keys, (card.name, key, keys)
        if len(keys) >= 2:
            assert set(keys) <= set(asked), (card.name, keys, asked)
    assert named >= _NAMED_KICKER_CONDITION_FLOOR


def _rich_duel(card):
    forest = _both_roles()["Forest"]
    game = Game(players=[
        PlayerState("Caster", library=[forest] * 10, hand=[card]),
        PlayerState("Other", library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    for symbol in "WUBRG":
        game.players[0].mana_pool[symbol] = 20
    return game


def test_each_kicker_alone_kicks_the_spell_and_the_record_says_which(two_kicker_cards):
    """CR 702.33d, end to end through the real cast path, for every subset of
    the two costs: the announcement the cast records is the one ``kicked``,
    ``kicked_with`` and ``kickers_paid`` read back — any cost kicks the spell,
    and each "with its [A] kicker" is true of exactly the costs paid."""
    examined = 0
    for card in two_kicker_cards:
        first, second = kicker_costs(card.oracle_text)
        for taken in ((), (first,), (second,), (first, second)):
            game = _rich_duel(card)
            result = game.queue_from_hand(
                0, card.name,
                optional_cost_payments={key: 1 for key in taken} or None,
            )
            assert result.supported, (card.name, taken, result)
            item = next(i for i in game.stack if i.card is card)
            assert kickers_paid(card, item.choices) == taken, (card.name, taken)
            assert kicked(card, item.choices) is bool(taken), (card.name, taken)
            for key in (first, second):
                assert kicked_with(card, item.choices, key) is (key in taken), (
                    card.name, taken, key,
                )
            examined += 1
    assert examined >= 4 * _TWO_KICKER_FLOOR


def test_an_unrelated_optional_cost_is_not_a_kicker_payment(two_kicker_cards):
    """CR 702.33f's reference is to the kicker alone. A record of some other
    optional cost — one the card's kicker line does not print — kicks nothing,
    whatever the stack item's record says was paid."""
    card = two_kicker_cards[0]
    stranger = "{7}{7}"
    assert stranger not in kicker_costs(card.oracle_text)
    record = {"additional_costs_paid": {stranger: 1}}
    assert kickers_paid(card, record) == ()
    assert not kicked(card, record)
    assert not kicked_with(card, record, stranger)
    # …and no record at all (an object nothing cast) is unkicked.
    assert not kicked(card, None) and kickers_paid(card, {}) == ()


def test_no_card_asks_whether_it_was_kicked_without_printing_a_kicker(pool):
    """The Ertai's Trickery census. ``was_kicked`` is answered from the asking
    object's own cast, so a supported card that compiles one and prints no
    kicker has a branch that is False forever: it reports supported and does
    nothing. "Counter target spell **if it was kicked**" is about the *target*
    (``target_was_kicked``), which is the only way a kicker-less card may ask.

    Validated backwards: on the tree before that condition existed this named
    Ertai's Trickery and nothing else.
    """
    examined = 0
    hollow = []
    for card in pool.values():
        if not compile_card_oracle(card).supported:
            continue
        if not _program_conditions(card, "was_kicked"):
            continue
        examined += 1
        if not kicker_costs(card.oracle_text or ""):
            hollow.append(card.name)
    assert hollow == []
    assert examined >= _SELF_QUESTION_FLOOR


def test_a_card_asking_about_a_targeted_spells_kicker_targets_a_spell(pool):
    """``target_was_kicked`` reads the stack object the effect targets, so the
    branch it guards must be one that targets a spell — otherwise there is no
    object to ask and the condition answers False for every cast."""
    asking = []
    for card in pool.values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for root in program.instructions:
            payload = root.payload or {}
            condition = payload.get("condition")
            if not (
                root.kind == "if_then"
                and isinstance(condition, dict)
                and condition.get("kind") == "target_was_kicked"
            ):
                continue
            asking.append(card.name)
            assert condition.get("target") == "spell", card.name
            targeted = [
                (step.payload or {}).get("targets", {}).get("kind")
                for step in payload.get("then") or ()
            ]
            assert targeted == ["spell"], (card.name, targeted)
    assert "Ertai's Trickery" in asking
