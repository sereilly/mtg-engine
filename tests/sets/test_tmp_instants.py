"""Tempest instants.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G2: buyback (CR 702.27) ---
import pytest

from engine import Game, PlayerState
from engine.cast_costs import (BUYBACK_RULES_TEXT, additional_costs,
                               buyback_cost, buyback_paid, expand_buyback_line,
                               is_buyback_line, unread_cost_sentence)
from engine.models import Permanent
from engine.oracle import compile_card_oracle, expand_card_lines


def _g2_rig(set_pool, card_name, **pool):
    """One seat holding *card_name* with *pool* already in its mana pool.

    The pool rather than lands, because casting spends the pool (CR 106.4) and
    a rig that tapped lands would be exercising the mana planner instead.
    """
    caster = PlayerState(name="A", hand=[set_pool("TMP")[card_name]])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = True
    for symbol, count in pool.items():
        caster.mana_pool[symbol] = count
    game._settle()
    return game, caster


def test_g2_every_buyback_line_in_the_set_is_rewritten_into_its_cost(set_cards):
    """CR 702.27a's first static ability, on all twelve.

    Derived from the set rather than listed, so a thirteenth buyback card
    ingested later is covered by whoever ingests it rather than by whoever
    remembers this test.
    """
    printed = [
        card for card in set_cards("TMP")
        if any(is_buyback_line(line) for line in card.oracle_text.split("\n"))
    ]
    assert len(printed) == 12, [c.name for c in printed]
    for card in printed:
        cost = buyback_cost(card.oracle_text)
        assert cost is not None, card.name
        assert BUYBACK_RULES_TEXT.format(cost=cost) in expand_card_lines(card)
        offers = [
            offer
            for entry in additional_costs(card)
            for offer in entry.optional_mana
        ]
        assert [o.symbols for o in offers] == [cost], card.name
        assert not any(o.repeatable for o in offers), (
            f"{card.name}: buyback is paid once, never CR 601.2b's "
            "'any number of times'"
        )


def test_g2_a_buyback_card_still_reports_supported_for_its_effect(set_pool):
    """The rewrite must not cost a card its support: the sentence it produces is
    a *cost*, so the compiler skips it and the effect line is still what makes
    the card supported."""
    program = compile_card_oracle(set_pool("TMP")["Capsize"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["bounce_target_creature"]


def test_g2_declining_buyback_puts_capsize_in_the_graveyard(set_pool, catalog_by_name):
    game, caster = _g2_rig(set_pool, "Capsize", U=3)
    bear = Permanent(card=catalog_by_name["Grizzly Bears"])
    game.players[1].battlefield.append(bear)
    game._settle()

    result = game.cast_from_hand(
        0, "Capsize", target_player_index=1,
        target_permanent_ids=[bear.permanent_id],
    )
    game._settle()
    game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert [c.name for c in caster.graveyard] == ["Capsize"]
    assert caster.hand == []
    assert sum(caster.mana_pool.values()) == 0, "the printed {1}{U}{U} and no more"


def test_g2_paying_buyback_returns_capsize_to_its_owners_hand(set_pool, catalog_by_name):
    """The half no other instrument can see. Capsize compiled, reported
    supported and bounced a permanent before this round; what it did not do was
    offer the price or come back, so it was a strictly weaker card and silently
    so."""
    game, caster = _g2_rig(set_pool, "Capsize", U=6)
    bear = Permanent(card=catalog_by_name["Grizzly Bears"])
    game.players[1].battlefield.append(bear)
    game._settle()

    result = game.cast_from_hand(
        0, "Capsize", target_player_index=1,
        target_permanent_ids=[bear.permanent_id],
        optional_cost_payments={"{3}": 1},
    )
    game._settle()
    game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert [c.name for c in caster.hand] == ["Capsize"]
    assert caster.graveyard == []
    assert sum(caster.mana_pool.values()) == 0, "{1}{U}{U} plus the buyback {3}"
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"], (
        "the effect still happens; buyback replaces only where the card goes"
    )


def test_g2_capsize_can_be_cast_again_from_the_hand_it_came_back_to(
    set_pool, catalog_by_name
):
    """The engine the card is: paid twice, it bounces twice off one copy."""
    game, caster = _g2_rig(set_pool, "Capsize", U=12)
    for _ in range(2):
        game.players[1].battlefield.append(
            Permanent(card=catalog_by_name["Grizzly Bears"])
        )
    game._settle()

    for _ in range(2):
        victim = game.players[1].battlefield[0]
        result = game.cast_from_hand(
            0, "Capsize", target_player_index=1,
            target_permanent_ids=[victim.permanent_id],
            optional_cost_payments={"{3}": 1},
        )
        assert result.supported, result.details
        game._settle()
        game.resolve_top_of_stack()
        game._settle()

    assert [c.name for c in caster.hand] == ["Capsize"]
    assert game.players[1].battlefield == []
    assert len(game.players[1].hand) == 2


def test_g2_buyback_is_refused_when_the_pool_cannot_pay_it(set_pool):
    """CR 601.2h: an unpayable announcement refuses the cast, and refuses it
    before anything is spent — the spell stays in hand with the pool intact."""
    game, caster = _g2_rig(set_pool, "Whispers of the Muse", U=1)
    caster.library = [set_pool("TMP")["Capsize"]]
    game._settle()

    result = game.cast_from_hand(
        0, "Whispers of the Muse", optional_cost_payments={"{5}": 1},
    )
    game._settle()

    assert not result.supported
    assert [c.name for c in caster.hand] == ["Whispers of the Muse"]
    assert sum(caster.mana_pool.values()) == 1


def test_g2_whispers_of_the_muse_draws_and_returns(set_pool):
    game, caster = _g2_rig(set_pool, "Whispers of the Muse", U=6)
    caster.library = [set_pool("TMP")["Capsize"]]
    game._settle()

    result = game.cast_from_hand(
        0, "Whispers of the Muse", optional_cost_payments={"{5}": 1},
    )
    game._settle()
    game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert sorted(c.name for c in caster.hand) == ["Capsize", "Whispers of the Muse"]
    assert caster.graveyard == []


def test_g2_worthy_cause_charges_its_sacrifice_and_its_buyback(
    set_pool, catalog_by_name
):
    """The one card in the set printing buyback *and* another additional cost.
    Both are read off one card, and the optional one does not swallow the
    mandatory one."""
    card = set_pool("TMP")["Worthy Cause"]
    described = [entry.describe() for entry in additional_costs(card)]
    assert described == ["you may pay {2}", "sacrifice a creature"]

    game, caster = _g2_rig(set_pool, "Worthy Cause", W=3)
    caster.battlefield.append(Permanent(card=catalog_by_name["Grizzly Bears"]))
    game._settle()

    result = game.cast_from_hand(
        0, "Worthy Cause", optional_cost_payments={"{2}": 1},
    )
    game._settle()
    game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert caster.battlefield == [], "the sacrifice was still charged"
    assert [c.name for c in caster.hand] == ["Worthy Cause"]


def test_g2_an_unreadable_buyback_line_makes_the_card_unsupported():
    """The gate, tested with an invented printing rather than a real card: a
    buyback whose cost this file cannot read must refuse the card, because the
    alternative is a spell cast at its printed mana cost with the price nobody
    was offered."""
    assert unread_cost_sentence("Buyback-Sacrifice a creature.") == (
        "buyback-sacrifice a creature"
    )
    assert expand_buyback_line("Buyback-Sacrifice a creature.") is None
    assert unread_cost_sentence("Buyback {3}") is None, (
        "a readable one is claimed, not refused"
    )


@pytest.mark.parametrize("choices", [None, {}, {"additional_costs_paid": {}},
                                     {"additional_costs_paid": {"{3}": 0}}])
def test_g2_an_unpaid_or_absent_announcement_reads_back_as_declined(
    set_pool, choices
):
    """Every shape of "nothing was announced" is a decline. The read-back is
    asked at *every* spell's resolution, so the answer for a card printing no
    buyback at all has to be False rather than an exception."""
    assert not buyback_paid(set_pool("TMP")["Capsize"], choices)
    assert not buyback_paid(set_pool("TMP")["Reality Anchor"], choices)
    assert not buyback_paid(
        set_pool("TMP")["Reality Anchor"],
        {"additional_costs_paid": {"{3}": 1}},
    ), "a card printing no buyback is never bought back by somebody else's key"
