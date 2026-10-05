"""Pool-wide: kicker (CR 702.33) is one rewrite and one reader.

CR 702.33a defines the keyword as a sentence -- "'Kicker [cost]' means 'You may
pay an additional [cost] as you cast this spell.'" -- so the engine has no
kicker mechanism at all: ``cast_costs.expand_kicker_lines`` turns the line into
CR 601.2b's optional additional cost, and from there the cost table, the cast
path, the payability ceiling and the browser's offer prompt carry it without
knowing the word. What kicker has that an ordinary optional cost does not is
that the card's *other* sentences ask about it, and ``cast_costs.kicked`` is
the one reader of the answer.

Three ways that arrangement can come apart, each of them quiet, each held here
over every card in both manifest roles:

* **The rewrite and the reader disagree about the offer's key.** The cost is
  charged under one spelling and ``kicked`` looks under another, so a spell
  that paid its kicker resolves unkicked. (Buyback's version of this is a spell
  that pays and goes to the graveyard anyway.)
* **A reader of a card's lines that does not start from
  ``expand_ability_lines``** sees a keyword line nothing claims.
* **The word after "and with" is read as a printed keyword.** "If this creature
  was kicked, it enters with two +1/+1 counters on it and with flying" sits in a
  static line, and the printed-ability scan reads static lines: every unkicked
  Faerie Squadron flew on the tree this was written against, with every
  instrument green -- the card was supported, hollow-free and fully claimed.

Each census carries a floor on how many cards it examined, because a guard over
an empty population passes.
"""

from __future__ import annotations

import pytest

from engine.faces import compilation_units
from engine import Game, PlayerState
from engine.cast_costs import (KICKED, additional_costs, expand_kicker_line,
                               is_kicker_line, kicked, kicker_cost,
                               unread_cost_sentence)
from engine.card_loader import load_cards, manifest_set_paths
from engine.enter_effects import kicked_entry
from engine.models import Permanent
from engine.oracle import (compile_card_oracle, expand_ability_lines,
                           expand_card_lines)

#: Invasion alone prints thirty-five; the floors below are deliberately under
#: that, so a later set raises the count without touching this file and an
#: empty population still fails.
_KICKER_CARD_FLOOR = 30
_KICKED_ENTRY_FLOOR = 10
_GRANTED_KEYWORD_FLOOR = 5
_CAST_FLOOR = 20


def _both_roles() -> dict:
    cards: dict = {}
    # Each card whose text compiles: a kicker line on a split card's half is
    # that half's (`faces.compilation_units`), and the whole card prints none.
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


def _kicker_cards() -> list:
    """Every card printing a kicker keyword line, in either manifest role."""
    return [
        card
        for card in _both_roles().values()
        if any(is_kicker_line(line) for line in (card.oracle_text or "").split("\n"))
    ]


@pytest.fixture(scope="module")
def kicker_cards() -> list:
    cards = _kicker_cards()
    assert len(cards) >= _KICKER_CARD_FLOOR, (
        f"only {len(cards)} kicker cards found; the census is reading the "
        "wrong pool"
    )
    return cards


def test_every_kicker_line_is_rewritten_into_an_offer_the_reader_keys_by(kicker_cards):
    """The rewrite, the cost table and ``kicker_cost`` name one offer by one
    key -- or the line is reported as a cost nothing charges. Never neither:
    a kicker line that is neither rewritten nor reported is a card castable
    with half its text unreachable and no instrument saying so."""
    unread = []
    for card in kicker_cards:
        printed = [
            line for line in card.oracle_text.split("\n") if is_kicker_line(line)
        ]
        key = kicker_cost(card.oracle_text)
        if key is None:
            # Refused honestly: every such line must be one the gate reports.
            assert all(unread_cost_sentence(line) for line in printed), card.name
            unread.append(card)
            continue
        offered = [
            offer.symbols
            for cost in additional_costs(card)
            for offer in cost.optional_mana
        ]
        assert key in offered, (card.name, key, offered)
        # …and the compiler's text holds the sentence, not the keyword line.
        expanded = expand_ability_lines(card.oracle_text, card_name=card.name)
        assert not any(is_kicker_line(line) for line in expanded.split("\n")), card.name
        assert any(expand_kicker_line(line) for line in printed), card.name
    # A kicker this cannot read is a **refused card**, never a castable one:
    # the gate reports the line (asserted above), so the card compiles
    # unsupported and no player can deck it. This read "nothing in the pool
    # prints one" until Planeshift was ingested, which prints fourteen
    # ("Kicker—Sacrifice a land.", "Kicker {1}{G} and/or {2}{U}") -- a fact
    # about that day's manifest written as an invariant. The invariant is that
    # an unread kicker never rides on a supported card, and it is asked of the
    # compiler rather than of a list of names, so the set that teaches the
    # reader a new cost shape changes nothing here.
    castable_unkickable = sorted(
        card.name for card in unread if compile_card_oracle(card).supported
    )
    assert castable_unkickable == []


def test_no_kicker_card_is_supported_on_a_line_that_ignores_its_kicker(kicker_cards):
    """A *supported* kicker card must compile every sentence that asks about
    the kicker into something that reads ``cast_costs.kicked``: an entry
    replacement the mixin gates on the stamp, or a ``was_kicked`` condition.
    A card supported with its "if … kicked" sentence dropped plays as the
    unkicked half for either price."""
    examined = 0
    for card in kicker_cards:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        examined += 1
        for line in expand_card_lines(card):
            if "kicked" not in line.lower():
                continue
            if kicked_entry(line, card.name) is not None:
                continue
            assert "was_kicked" in repr(program.instructions), (card.name, line)
    assert examined >= _CAST_FLOOR


def test_a_keyword_a_kicked_creature_enters_with_is_not_a_printed_one(kicker_cards):
    """The Faerie Squadron guard. For every "…and with <keyword>" entry line: a
    permanent of that card that nothing cast -- so not kicked -- does not have
    the keyword, unless the card also prints it outright."""
    entries = 0
    granted = 0
    for card in kicker_cards:
        if not compile_card_oracle(card).supported:
            continue
        for line in expand_card_lines(card):
            entry = kicked_entry(line, card.name)
            if entry is None:
                continue
            entries += 1
            printed = {word.lower() for word in card.keywords}
            for keyword in entry["keywords"]:
                if keyword in printed:
                    continue
                granted += 1
                bystander = Permanent(card=card)
                assert not bystander.has_keyword(keyword), (
                    f"{card.name} has {keyword} without being kicked"
                )
                bystander.metadata[KICKED] = True
                # The stamp alone grants nothing either: the grant is made as
                # the permanent enters, not read off the text afterwards.
                assert not bystander.has_keyword(keyword), card.name
    assert entries >= _KICKED_ENTRY_FLOOR
    assert granted >= _GRANTED_KEYWORD_FLOOR


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


def test_a_cast_that_pays_the_kicker_is_kicked_and_one_that_declines_is_not(
    kicker_cards,
):
    """CR 702.33d, end to end through the real cast path: the announcement the
    cast records is the one ``kicked`` reads. Asked of the stack item, which is
    where the answer lives until the spell resolves.

    A card whose cast is refused on an empty board (it needs a target) is
    skipped rather than faked; the floor is what keeps that honest.
    """
    examined = 0
    for card in kicker_cards:
        key = kicker_cost(card.oracle_text)
        if key is None or not compile_card_oracle(card).supported:
            continue
        outcomes = {}
        for announced in ({key: 1}, None):
            game = _rich_duel(card)
            result = game.queue_from_hand(
                0, card.name, optional_cost_payments=announced,
                x_value=2 if "{X}" in key else None,
            )
            if not result.supported:
                break
            item = next(i for i in game.stack if i.card is card)
            outcomes[bool(announced)] = kicked(card, item.choices)
        else:
            examined += 1
            assert outcomes == {True: True, False: False}, card.name
    assert examined >= _CAST_FLOOR
