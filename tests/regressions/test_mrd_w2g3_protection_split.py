"""CR 702.16g: "Protection from [quality A] and from [quality B]" is shorthand
for two protection abilities — and the conditional-static table could not
read it.

``engine/static_bonuses._protection_list`` split its clause with
``r",|<BS>and from<BS>|<BS>and<BS>"``: four literal U+0008 BACKSPACE
characters where ``\\b`` was meant (a heredoc ate the backslash). Only the
comma ever split, so "has protection from green and from white" was one
quality nobody models and the table refused the sentence.

Measured at MRD W2G3. Eleven cards in the pool print two protections in one
sentence (Paladin en-Vec, Sabertooth Nishoba, Akroma, Angel of Wrath,
Baneslayer Angel, Mystic Crusader, Masked Gorgon, Shield of Duty and Reason,
Crown of Awe, Mask of Law and Grace, Questing Phelddagrif, Grotesque Hybrid);
every keyword, Aura and activated grant among them is read by other splitters
and was right on the board before and after. Only Masked Gorgon prints the
sentence as a conditional static, and its condition (threshold) is one the
table does not read, so the table refused that line before the fix and after
it alike; the grammar's conditional-grant production lowers it. No program
moved (``oracle_diff`` 0/0/0): the defect was latent in this pool, waiting for
the first "has protection from A and from B as long as / during your turn"
whose condition the table does read.

So the table's split is pinned here on conditions it reads, and the board is
driven for two of the eleven.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.static_bonuses import static_bonus_for


def _table(set_pool, *seat0_cards):
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    placed = []
    for card in seat0_cards:
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._settle()
    return game, placed


def test_the_conditional_static_table_splits_and_from():
    """Two qualities, in both word orders the table reads, under a condition
    it reads. Before the fix each was None: "green and from white" was one
    word nobody models, so the whole sentence refused."""
    fronted = static_bonus_for(
        "during your turn, this creature has protection from green and from white"
    )
    assert fronted is not None
    assert fronted.payload["protection_from"] == ["green", "white"]
    assert fronted.payload["condition"] == {"kind": "your_turn"}
    trailing = static_bonus_for(
        "this creature has protection from black and from red as long as you "
        "control a plains"
    )
    assert trailing is not None
    assert trailing.payload["protection_from"] == ["black", "red"]
    assert trailing.payload["condition"]["kind"] == "controls"


def test_masked_gorgon_at_threshold_cannot_be_targeted_by_green_or_white(set_pool):
    """Seven cards in its controller's graveyard: Giant Growth (green) and
    Swords to Plowshares (white) cannot target it; Lightning Bolt can."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game, (gorgon,) = _table(set_pool, jud["Masked Gorgon"])
    for _ in range(7):
        assert game.put_card_into_graveyard(0, lea["Island"])
    game._settle()
    program = compile_card_oracle(jud["Masked Gorgon"])
    assert program.supported

    assert game._protection_qualities(gorgon) >= {("color", "G"), ("color", "W")}
    for spell in ("Giant Growth", "Swords to Plowshares"):
        game.players[1].hand.append(lea[spell])
    game.players[1].hand.append(lea["Lightning Bolt"])
    game.active_player_index = 1
    for spell in ("Giant Growth", "Swords to Plowshares"):
        refused = game.queue_from_hand(
            1, spell, target_player_index=0,
            target_permanent_ids=[gorgon.permanent_id],
        )
        assert not refused.supported, (spell, refused)
    bolt = game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[gorgon.permanent_id],
    )
    assert bolt.supported, bolt


def test_paladin_en_vec_cannot_be_targeted_by_black_or_red(set_pool):
    """"First strike, protection from black and from red": Lightning Bolt and
    Terror are refused at it; Swords to Plowshares is not."""
    exo, lea = set_pool("EXO"), set_pool("LEA")
    game, (paladin,) = _table(set_pool, exo["Paladin en-Vec"])
    assert game._protection_qualities(paladin) == {("color", "B"), ("color", "R")}
    for spell in ("Lightning Bolt", "Terror", "Swords to Plowshares"):
        game.players[1].hand.append(lea[spell])
    game.active_player_index = 1
    for spell in ("Lightning Bolt", "Terror"):
        refused = game.queue_from_hand(
            1, spell, target_player_index=0,
            target_permanent_ids=[paladin.permanent_id],
        )
        assert not refused.supported, (spell, refused)
    swords = game.queue_from_hand(
        1, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[paladin.permanent_id],
    )
    assert swords.supported, swords
