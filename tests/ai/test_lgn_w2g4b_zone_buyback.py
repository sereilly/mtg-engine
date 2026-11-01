"""A spell bought back out of the zone it was cast from is weighed as the same
spell bought back out of a hand.

Buyback (CR 702.27a) puts the card into its owner's hand as it resolves. From
a hand that is a round trip; from an exile or a graveyard a permission opened
(CR 601.3) it is a card arriving in the hand. ``ai_rehearsal.rehearse`` takes
the spell's own trip out of "did this change anything" (``same_position``),
but its "is any of it left at the end of the turn" (``Rehearsal.fleeting``)
first asked the standings whether the lasting swing was nothing — or, for a
hand cast, the card spent — and a zone cast's lasting swing was the card
bought back, so it never read as fleeting. The target chooser drops a target
whose cast leaves nothing (``ai_targets._best_target``), so from the hand a
Mind Games tapped the blocker whose fight left something, and from an exile
the first creature on the board (the zone-cast census at LGN's promotion,
once the defending AI stopped making losing blocks and the fight began to
tell the two apart).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_policy import choose_cast_action
from engine.ai_scoring import _rehearse_announcement
from engine.cast_permissions import grant_permission
from engine.models import Permanent

from tests.helpers import _mk_card, _nosick

ME, OPP = 0, 1


def _creature(name, power, toughness, colors=(), text="", type_line="Creature - Beast"):
    return _mk_card(
        name=name, type_line=type_line, colors=colors,
        power=power, toughness=toughness, oracle_text=text,
    )


def _table(card, zone: str):
    """Seat 0's precombat main phase with *card* in its hand or its exile
    (lent by a permission, as Elkin Bottle lends one), eight of each colour
    floating, and the zone-cast census's board on each side."""
    forest = _mk_card(name="Forest", type_line="Basic Land - Forest")

    def side():
        return [_nosick(Permanent(card=card)) for card in (
            _creature("Bait White", 2, 2, ("W",)),
            _creature("Bait Blue Flyer", 1, 1, ("U",), "Flying"),
            _creature("Bait Black", 3, 3, ("B",)),
            _creature("Bait Golem", 3, 3, (), "", "Artifact Creature - Golem"),
            _mk_card(name="Bait Artifact", type_line="Artifact"),
            _mk_card(name="Bait Enchantment", type_line="Enchantment", colors=("W",)),
            _mk_card(name="Bait Nonbasic", type_line="Land"),
        )]

    me = PlayerState(name="AI", library=[forest] * 10, battlefield=side())
    opp = PlayerState(name="Opp", library=[forest] * 10, battlefield=side())
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = ME
    game._sync_control()
    me.mana_pool.update({symbol: 8 for symbol in "WUBRG"})
    if zone == "hand":
        me.hand.append(card)
    else:
        me.exile.append(card)
        grant_permission(
            game, player_index=ME, zone="exile", mode="play", cards=[card],
            duration="your_next_upkeep", source_name="test",
        )
    return game


def _mind_games_at_the_land(game, zone: str):
    land = next(p for p in game.controlled_by(OPP) if p.card.name == "Bait Nonbasic")
    return {
        "target_player_index": OPP, "target_permanent_index": None,
        "target_permanent_ids": [land.permanent_id], "x_value": None,
        "from_zone": zone, "alternative_cost": False, "divided_targets": None,
        "optional_cost_payments": {"{2}{U}": 1}, "mode_index": None,
        "mode_choices": None, "target_stack_index": None,
    }


def test_a_bought_back_trick_that_leaves_nothing_reads_so_from_either_zone(set_pool):
    """Mind Games, bought back, tapping a land across the table: by the end
    of the turn nothing it did is left but its own card, back in the hand —
    fleeting from the exile exactly as from the hand."""
    mind_games = set_pool("STH")["Mind Games"]
    for zone in ("hand", "exile"):
        game = _table(mind_games, zone)
        rehearsal = _rehearse_announcement(
            game, ME, mind_games, _mind_games_at_the_land(game, zone),
        )
        assert rehearsal is not None and rehearsal.accepted and rehearsal.changed, zone
        assert rehearsal.fleeting, f"from the {zone}: {rehearsal}"


def test_mind_games_names_the_same_creature_from_the_hand_and_the_exile(set_pool):
    """The census's claim on its own board: what the seat announces from its
    hand it announces from the zone a permission opened — the same target,
    the same buyback."""
    mind_games = set_pool("STH")["Mind Games"]

    def said(zone):
        game = _table(mind_games, zone)
        action = choose_cast_action(game, ME)
        if action is None or action.card_name != "Mind Games":
            return None
        names = tuple(
            game.permanent_by_id(pid).card.name
            for pid in action.target_permanent_ids or ()
        )
        return action.target_player_index, names, action.optional_cost_payments

    from_hand = said("hand")
    assert from_hand is not None, "not cast from hand on this board"
    assert from_hand == said("exile")
