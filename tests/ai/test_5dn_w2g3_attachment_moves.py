"""Which Equipment Magnetic Theft moves, and onto whose creature.

"Attach target Equipment to target creature. (Control of the Equipment
doesn't change.)" One side per role read the cast as the caster's own
Equipment onto the caster's own creature, so it never took an opponent's
Grafted Wargear off its creature — "Whenever this Equipment becomes
unattached from a permanent, sacrifice that permanent" is its controller's
to obey, so the move kills their creature — and a side picker's fallback
once moved an AI's own Wargear onto an opponent's creature when it
controlled none (5DN W1G4). Every chain the picker offers is now rehearsed
(``ai_slot_targets._weighed_attachment_moves``) and the cast declined where
none pays.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.equipment import attach_equipment, equipped_creature
from engine.models import Permanent
from tests.helpers import settle


def _table(set_pool, *, mine=(), theirs=(), wargear_on=None) -> tuple[Game, dict]:
    pool = {**set_pool("LEA"), **set_pool("5DN")}
    game = Game(players=[
        PlayerState(name="AI", hand=[pool["Magnetic Theft"]], library=[pool["Mountain"]] * 8),
        PlayerState(name="Opp", library=[pool["Forest"]] * 8),
    ])
    game.interactive_seats = set()
    placed: dict = {}
    for seat, names in ((0, ["Mountain", *mine]), (1, list(theirs))):
        for name in names:
            permanent = Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.setdefault((seat, name), permanent)
    game._sync_control()
    if wargear_on is not None:
        attach_equipment(game, placed[(1, "Grafted Wargear")], placed[wargear_on])
    game.start_turn(0)
    settle(game)
    game.enforce_mana_costs = True
    return game, placed


def test_its_own_wargear_is_never_handed_to_an_opponents_creature(set_pool):
    """The seat controls an unattached Grafted Wargear and no creature; the
    opponent has Grizzly Bears. The only chain is a +3/+2 gift (the Wargear's
    sacrifice cannot reach a creature its controller does not control). Not
    cast."""
    game, _placed = _table(set_pool, mine=["Grafted Wargear"], theirs=["Grizzly Bears"])
    assert choose_cast_action(game, 0) is None


def test_an_opponents_wargear_is_moved_off_its_creature_onto_the_casters(set_pool):
    """The opponent's Grafted Wargear on their Grizzly Bears, the seat's
    Llanowar Elves beside: the Wargear goes onto the Elves, still the
    opponent's, and the Bears it left are sacrificed by its controller."""
    game, placed = _table(
        set_pool, mine=["Llanowar Elves"], theirs=["Grizzly Bears", "Grafted Wargear"],
        wargear_on=(1, "Grizzly Bears"),
    )
    wargear, elves = placed[(1, "Grafted Wargear")], placed[(0, "Llanowar Elves")]
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Magnetic Theft"
    assert [ref.get("permanent_id") for ref in action.target_role_refs] == [
        wargear.permanent_id, elves.permanent_id,
    ]
    action = tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result
    settle(game)
    assert equipped_creature(wargear) is elves
    assert game.controls(1, wargear)
    assert any(card.name == "Grizzly Bears" for card in game.players[1].graveyard)
    assert (elves.effective_power, elves.effective_toughness) == (4, 3)


def test_with_no_creature_of_its_own_the_move_still_kills_theirs(set_pool):
    """No creature on the seat's side: the opponent's Wargear moves from
    their Grizzly Bears to their Hill Giant, and the Bears are sacrificed —
    a creature for a card, which is the play."""
    game, placed = _table(
        set_pool, theirs=["Grizzly Bears", "Hill Giant", "Grafted Wargear"],
        wargear_on=(1, "Grizzly Bears"),
    )
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Magnetic Theft"
    named = [ref.get("permanent_id") for ref in action.target_role_refs]
    assert named == [placed[(1, "Grafted Wargear")].permanent_id, placed[(1, "Hill Giant")].permanent_id]
