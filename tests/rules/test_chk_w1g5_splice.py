"""Splice onto Arcane (CR 702.47): ``engine/splice.py``.

Every test casts a real spell through ``Game.queue_from_hand`` /
``cast_from_hand`` with ``splice_cards`` and reads the board, the hands, the
life totals and the log after ``settle``. The rules each one holds:

* 702.47a — splice is a static ability of a card in a hand; the spliced card
  is revealed and stays there; its cost is an additional cost (CR 601.2f).
* 702.47b — the targets of the gained text must be choosable; a card is
  spliced at most once; the main spell's effects happen first, then the
  spliced texts in the order announced.
* 702.47c — the spell keeps its own characteristics: the gained text's
  "Glacial Ray deals 2 damage" is dealt by the host spell, in its colour.
* 702.47d — targets for the gained text; CR 608.2b over all of them.
* 702.47e — nothing spliced survives the spell leaving the stack.
* 707.10 — a copy of a spliced spell copies the spliced text (Uyo, Silent
  Prophet's 2004-12-01 ruling).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.splice import splice_offer, spliced_text_card
from tests.helpers import settle

#: Where each card the tests name is looked up, in order.
_SETS = ("CHK", "LEA", "DST", "6ED", "EXO", "MIR")


def _card(set_pool, name):
    for code in _SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _table(set_pool, *, hand=(), mine=(), theirs=(), graveyard=(),
           opponent_hand=(), mana=False, interactive=()):
    cards = lambda names: [_card(set_pool, n) for n in names]  # noqa: E731
    island = _card(set_pool, "Island")
    game = Game(players=[
        PlayerState("A", hand=cards(hand), library=[island] * 10,
                    graveyard=cards(graveyard)),
        PlayerState("B", hand=cards(opponent_hand), library=[island] * 10),
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    return game, placed[0], placed[1]


def _hand(game, seat=0):
    return [card.name for card in game.players[seat].hand]


@pytest.mark.cr("702.47a", "702.47c")
def test_the_gained_text_is_the_spells_and_the_spliced_card_stays_in_hand(set_pool):
    game, _mine, (giant,) = _table(
        set_pool, hand=["Reach Through Mists", "Glacial Ray"], theirs=["Hill Giant"],
    )
    result = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [giant.permanent_id]},
    ])
    assert result.supported, result.details
    settle(game)
    assert giant.damage_marked == 2
    # "Reach Through Mists deals the damage" (CR 702.47c's own example).
    assert "Reach Through Mists dealt 2 damage to Hill Giant" in game.log
    assert any("spliced Glacial Ray onto Reach Through Mists" in line for line in game.log)
    # Revealed, never moved (CR 702.47a's example): it is still in the hand
    # beside the card the host drew, and the host is in the graveyard.
    assert "Glacial Ray" in _hand(game)
    assert [card.name for card in game.players[0].graveyard] == ["Reach Through Mists"]


@pytest.mark.cr("702.47c")
def test_a_spliced_red_text_on_a_blue_spell_may_target_protection_from_red(set_pool):
    """CR 702.47c's example: the spell is still blue, so Glacial Ray's text may
    target a creature with protection from red."""
    game, _mine, (paladin,) = _table(
        set_pool, hand=["Glacial Ray", "Reach Through Mists", "Glacial Ray"],
        theirs=["Paladin en-Vec"],
    )
    alone = game.cast_from_hand(
        0, "Glacial Ray", target_permanent_ids=[paladin.permanent_id],
    )
    assert not alone.supported
    result = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 2, "target_permanent_ids": [paladin.permanent_id]},
    ])
    assert result.supported, result.details
    settle(game)
    assert paladin.damage_marked == 2


@pytest.mark.cr("702.47a", "601.2f")
def test_the_splice_cost_is_an_additional_cost_paid_with_the_spell(set_pool):
    game, _mine, (giant,) = _table(
        set_pool, hand=["Reach Through Mists", "Glacial Ray"], theirs=["Hill Giant"],
        mana=True,
    )
    seat = game.players[0]
    seat.mana_pool["U"], seat.mana_pool["R"] = 1, 1
    entry = {"hand_index": 1, "target_permanent_ids": [giant.permanent_id]}
    short = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[entry])
    assert not short.supported
    assert "splicing Glacial Ray" in short.details
    # Nothing spent on a refused cast (read off the seat again: the refusal
    # takes the attempt back, the pool included).
    assert (seat.mana_pool["U"], seat.mana_pool["R"]) == (1, 1)
    seat.mana_pool["C"] = 1
    paid = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[entry])
    assert paid.supported, paid.details
    settle(game)
    assert sum(seat.mana_pool.values()) == 0
    assert giant.damage_marked == 2


@pytest.mark.cr("702.47a", "702.47b")
def test_a_card_is_spliced_once_and_never_onto_itself(set_pool):
    game, _mine, _theirs = _table(set_pool, hand=["Glacial Ray", "Glacial Ray", "Reach Through Mists"])
    itself = game.cast_from_hand(0, "Glacial Ray", target_player_index=1, splice_cards=[
        {"hand_index": 0, "target_player_index": 1},
    ])
    assert not itself.supported and "onto itself" in itself.details
    twice = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 0, "target_player_index": 1},
        {"hand_index": 0, "target_player_index": 1},
    ])
    assert not twice.supported and "twice" in twice.details
    # Two *cards* of one name are two cards: both may be spliced.
    both = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 0, "target_player_index": 1},
        {"hand_index": 1, "target_player_index": 1},
    ])
    assert both.supported, both.details
    settle(game)
    assert game.players[1].life == 16
    assert _hand(game).count("Glacial Ray") == 2


@pytest.mark.cr("702.47a")
def test_splice_onto_arcane_needs_an_arcane_spell_and_a_splice_card(set_pool):
    game, _mine, _theirs = _table(set_pool, hand=["Shock", "Glacial Ray", "Reach Through Mists", "Lava Spike"])
    not_arcane = game.cast_from_hand(0, "Shock", target_player_index=1, splice_cards=[
        {"hand_index": 1, "target_player_index": 1},
    ])
    assert not not_arcane.supported and "not one" in not_arcane.details
    no_splice = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 3, "target_player_index": 1},
    ])
    assert not no_splice.supported and "no splice ability" in no_splice.details
    assert _hand(game) == ["Shock", "Glacial Ray", "Reach Through Mists", "Lava Spike"]


@pytest.mark.cr("702.47b")
def test_a_text_whose_targets_cannot_be_chosen_cannot_be_spliced(set_pool):
    game, _mine, _theirs = _table(set_pool, hand=["Reach Through Mists", "Kodama's Might"])
    refused = game.cast_from_hand(0, "Reach Through Mists", splice_cards=[{"hand_index": 1}])
    assert not refused.supported and "CR 702.47b" in refused.details
    assert _hand(game) == ["Reach Through Mists", "Kodama's Might"]


@pytest.mark.cr("702.47b")
def test_the_main_spell_happens_first_then_each_splice_in_the_order_announced(set_pool):
    game, (bears,), (giant, elves) = _table(
        set_pool, hand=["Consuming Vortex", "Kodama's Might", "Glacial Ray"],
        mine=["Grizzly Bears"], theirs=["Hill Giant", "Llanowar Elves"],
    )
    result = game.cast_from_hand(
        0, "Consuming Vortex", target_permanent_ids=[elves.permanent_id],
        splice_cards=[
            {"hand_index": 2, "target_permanent_ids": [giant.permanent_id]},
            {"hand_index": 1, "target_permanent_ids": [bears.permanent_id]},
        ],
    )
    assert result.supported, result.details
    settle(game)
    lines = [
        game.log.index(line) for line in (
            "Llanowar Elves returned to its owner's hand (Consuming Vortex)",
            "Consuming Vortex dealt 2 damage to Hill Giant",
            "Consuming Vortex gives Grizzly Bears +2/+2 until end of turn",
        )
    ]
    assert lines == sorted(lines)
    assert bears.effective_power == 4 and giant.damage_marked == 2


@pytest.mark.cr("702.47d", "608.2b")
def test_a_spliced_spell_whose_every_target_is_illegal_does_not_resolve(set_pool):
    """Reach Through Mists targets nothing; the gained text's one target
    leaving makes every target of the spell illegal, and nothing happens —
    not even the draw (the splice cards' 2013-06-07 ruling)."""
    game, _mine, (giant,) = _table(
        set_pool, hand=["Reach Through Mists", "Glacial Ray"], theirs=["Hill Giant"],
        opponent_hand=["Unsummon"],
    )
    game.queue_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [giant.permanent_id]},
    ])
    game.queue_from_hand(1, "Unsummon", target_permanent_ids=[giant.permanent_id])
    settle(game)
    assert any("every target is illegal" in line for line in game.log)
    assert _hand(game) == ["Glacial Ray"]  # no card drawn
    assert [card.name for card in game.players[0].graveyard] == ["Reach Through Mists"]


@pytest.mark.cr("702.47d", "608.2b")
def test_a_spliced_target_gone_leaves_the_rest_of_the_spell_to_resolve(set_pool):
    game, _mine, (giant, bears) = _table(
        set_pool, hand=["Consuming Vortex", "Glacial Ray"],
        theirs=["Hill Giant", "Grizzly Bears"], opponent_hand=["Unsummon"],
    )
    game.queue_from_hand(
        0, "Consuming Vortex", target_permanent_ids=[bears.permanent_id],
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [giant.permanent_id]}],
    )
    game.queue_from_hand(1, "Unsummon", target_permanent_ids=[giant.permanent_id])
    settle(game)
    assert sorted(_hand(game, 1)) == ["Grizzly Bears", "Hill Giant"]
    # The gained text's target is gone: it deals its 2 to nobody — never to
    # the seat its target stood on.
    assert game.players[1].life == 20


@pytest.mark.cr("702.47d", "608.2b")
def test_the_main_target_gone_leaves_the_spliced_text_to_resolve(set_pool):
    game, _mine, (giant, bears) = _table(
        set_pool, hand=["Consuming Vortex", "Glacial Ray"],
        theirs=["Hill Giant", "Grizzly Bears"], opponent_hand=["Unsummon"],
    )
    game.queue_from_hand(
        0, "Consuming Vortex", target_permanent_ids=[bears.permanent_id],
        splice_cards=[{"hand_index": 1, "target_permanent_ids": [giant.permanent_id]}],
    )
    game.queue_from_hand(1, "Unsummon", target_permanent_ids=[bears.permanent_id])
    settle(game)
    assert giant.damage_marked == 2
    assert game.is_on_battlefield(giant)


@pytest.mark.cr("702.47c", "601.2i")
def test_a_spliced_spell_is_cast_once_and_keeps_its_own_colour(set_pool):
    """Kraken's Eye sees one blue spell cast; Dragon's Claw sees no red one,
    though a red card's text was spliced onto it (CR 702.47c)."""
    game, (eye, claw), _theirs = _table(
        set_pool, hand=["Reach Through Mists", "Glacial Ray"],
        mine=["Kraken's Eye", "Dragon's Claw"],
    )
    game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_player_index": 1},
    ])
    settle(game)
    assert game.players[0].life == 21
    assert game.players[1].life == 18


@pytest.mark.cr("707.10", "702.47c")
def test_a_copy_of_a_spliced_spell_copies_the_spliced_text(set_pool):
    """Uyo, Silent Prophet's ruling (2004-12-01): "If you copy an Arcane spell
    that has cards spliced onto it, you'll copy the spliced text as well as
    the original spell text." Forked, Reach Through Mists draws twice and its
    gained Glacial Ray deals 2 twice."""
    game, _mine, _theirs = _table(set_pool, hand=["Reach Through Mists", "Glacial Ray", "Fork"])
    game.queue_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_player_index": 1},
    ])
    forked = game.queue_from_hand(0, "Fork", target_stack_index=0)
    assert forked.supported, forked.details
    settle(game)
    assert game.players[1].life == 16
    assert _hand(game).count("Island") == 2


@pytest.mark.cr("702.47d", "601.2c")
def test_the_gained_texts_target_becomes_the_target_of_the_spell(set_pool):
    """Skulking Ghost: "When this creature becomes the target of a spell or
    ability, sacrifice it." Targeted only by the spliced text."""
    game, _mine, (ghost,) = _table(
        set_pool, hand=["Reach Through Mists", "Glacial Ray"], theirs=["Skulking Ghost"],
    )
    game.cast_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [ghost.permanent_id]},
    ])
    settle(game)
    assert not game.is_on_battlefield(ghost)
    assert "Skulking Ghost" in [card.name for card in game.players[1].graveyard]


@pytest.mark.cr("702.47e", "702.47a")
def test_a_countered_spliced_spell_leaves_nothing_spliced_behind(set_pool):
    """The host is countered: Glacial Ray never left the hand, and cast later
    it is its own spell; the host in the graveyard is the printed card."""
    game, _mine, _theirs = _table(
        set_pool, hand=["Reach Through Mists", "Glacial Ray"], opponent_hand=["Counterspell"],
    )
    game.queue_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_player_index": 1},
    ])
    game.queue_from_hand(1, "Counterspell", target_stack_index=0)
    settle(game)
    assert game.players[1].life == 20
    binned = game.players[0].graveyard[0]
    assert binned.name == "Reach Through Mists" and "damage" not in binned.oracle_text
    assert game.cast_from_hand(0, "Glacial Ray", target_player_index=1).supported
    settle(game)
    assert game.players[1].life == 18


@pytest.mark.cr("702.47a")
def test_every_champions_splice_line_is_read_by_the_splice_reader(set_cards):
    """Every Champions of Kamigawa card printing "Splice onto" is read by
    the reader the cast path splices with, and its gained text compiles as
    the host's — the census floor is the fifteen printed (thirteen of them
    reported supported with the keyword dropped before this module)."""
    printed = [
        card for card in set_cards("CHK")
        if "Splice onto" in (card.oracle_text or "")
    ]
    assert len(printed) >= 15
    host = next(card for card in set_cards("CHK") if card.name == "Reach Through Mists")
    for card in printed:
        offer = splice_offer(card.oracle_text)
        assert offer is not None and offer.quality == "arcane", card.name
        gained = spliced_text_card(host, card)
        assert "Splice" not in gained.oracle_text, card.name
        assert gained.name == host.name and gained.colors == host.colors
        if compile_card_oracle(card).supported:
            assert compile_card_oracle(gained).supported, card.name
