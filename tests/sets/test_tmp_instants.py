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


# --- W1G2: Whim of Volrath — a text change with a printed duration (CR 612) ---
from engine.card_loader import load_cards as _w1g2_load
from engine.card_loader import manifest_set_path as _w1g2_path
from engine.text_changes import UNTIL_END_OF_TURN, text_changes

_W1G2_LEA = {card.name: card for card in _w1g2_load(_w1g2_path("LEA"))}
_W1G2_MIR = {card.name: card for card in _w1g2_load(_w1g2_path("MIR"))}


def _g2_text_change(spell, *, old="W", new="U"):
    """Cast *spell* at a Black Knight and answer any vocabulary prompt.

    Black Knight is the subject because its "Protection from white" is a colour
    word in its *rules text* — so the rewrite is visible through
    ``effective_card`` (CR 613 layer 3) rather than only in a record.
    """
    caster = PlayerState(name="A", hand=[spell])
    holder = PlayerState(name="B")
    game = Game(players=[caster, holder])
    game.enforce_mana_costs = False
    knight = Permanent(card=_W1G2_LEA["Black Knight"])
    holder.battlefield.append(knight)
    game._settle()

    result = game.cast_from_hand(
        0, spell.name, target_player_index=1, target_permanent_index=0,
        target_permanent_ids=[knight.permanent_id],
        old_color=old, new_color=new,
    )
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game._settle()
    for choice in list(game.pending_choices):
        game.confirm_text_change_vocabulary(choice.player_index, "color_word")
        game._settle()
    return game, knight, result


def test_g2_whim_of_volrath_is_mind_bend_with_a_duration(set_pool):
    """The union vocabulary already existed (Mind Bend, MIR). What Whim of
    Volrath adds is the *duration*, which is why it is a field on the node and
    a key on the payload rather than a second instruction kind."""
    program = compile_card_oracle(set_pool("TMP")["Whim of Volrath"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["mark_text_modified"]
    assert program.instructions[0].payload == {
        "mode": "color_word_or_land_type", "duration": "until_end_of_turn",
    }
    assert compile_card_oracle(_W1G2_MIR["Mind Bend"]).instructions[0].payload == {
        "mode": "color_word_or_land_type",
    }, "the durationless printing keeps the payload it always had"


def test_g2_whim_of_volrath_rewrites_the_word_and_the_cleanup_puts_it_back(set_pool):
    game, knight, result = _g2_text_change(set_pool("TMP")["Whim of Volrath"])

    assert result.supported, result.details
    assert "protection from blue" in knight.effective_card.oracle_text.lower()
    assert [
        (c["from"], c["to"], c.get("duration")) for c in text_changes(knight)
    ] == [("white", "blue", UNTIL_END_OF_TURN)]

    game.resolve_cleanup_step(0)
    game._settle()

    assert text_changes(knight) == ()
    assert "protection from white" in knight.effective_card.oracle_text.lower(), (
        "dropping the contribution is the reversion (CR 611.3b) — nothing was "
        "stashed and nothing is restored"
    )


def test_g2_the_cleanup_keeps_a_text_change_printed_without_a_duration():
    """The half a plain `_EOT_METADATA_KEYS` entry would have got wrong: the key
    holds records of two lifetimes, and popping it whole would end Mind Bend's
    indefinite rewrite with the turn."""
    game, knight, result = _g2_text_change(_W1G2_MIR["Mind Bend"])

    assert result.supported, result.details
    assert [c.get("duration") for c in text_changes(knight)] == [None]

    game.resolve_cleanup_step(0)
    game._settle()

    assert [c.get("duration") for c in text_changes(knight)] == [None]
    assert "protection from blue" in knight.effective_card.oracle_text.lower()


def test_g2_both_lifetimes_on_one_permanent_end_separately(set_pool):
    """Mind Bend first, then Whim of Volrath: the cleanup drops one record and
    keeps the other, and what the permanent reads afterwards is whatever
    contributions remain.

    Neither swap names blue, and that is not incidental: Whim of Volrath is a
    **blue** spell, so rewriting Black Knight's protection to blue would make it
    an illegal target for the second cast (CR 702.16b). The engine refuses that
    correctly, which is how this test first failed.
    """
    caster = PlayerState(
        name="A",
        hand=[_W1G2_MIR["Mind Bend"], set_pool("TMP")["Whim of Volrath"]],
    )
    holder = PlayerState(name="B")
    game = Game(players=[caster, holder])
    game.enforce_mana_costs = False
    knight = Permanent(card=_W1G2_LEA["Black Knight"])
    holder.battlefield.append(knight)
    game._settle()

    for name, old, new in (("Mind Bend", "W", "G"), ("Whim of Volrath", "G", "R")):
        cast = game.cast_from_hand(
            0, name, target_player_index=1, target_permanent_index=0,
            target_permanent_ids=[knight.permanent_id],
            old_color=old, new_color=new,
        )
        assert cast.supported, f"{name}: {cast.details}"
        game._settle()
        while game.stack:
            game.resolve_top_of_stack()
            game._settle()
        for choice in list(game.pending_choices):
            game.confirm_text_change_vocabulary(choice.player_index, "color_word")
            game._settle()

    assert "protection from red" in knight.effective_card.oracle_text.lower()

    game.resolve_cleanup_step(0)
    game._settle()

    assert [c.get("duration") for c in text_changes(knight)] == [None]
    assert "protection from green" in knight.effective_card.oracle_text.lower(), (
        "Mind Bend's white->green is still there; only Whim's green->red ended"
    )
