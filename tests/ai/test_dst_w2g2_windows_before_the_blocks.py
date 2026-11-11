"""A spell whose printed window shuts before the blocks is weighed before them.

Before the blocks (``ai_rehearsal.blocks_still_to_come``) the attacker's
tricks wait for the declare-blockers step, where the blocks are known
(``ai_policy._weighed_at_instant_speed_now``), and a spell weighed there is
made only for a block it adds that pays (``ai_rehearsal.
pays_before_the_blocks``). Three cards print a window that is shut by the
declare-blockers step — "Cast this spell only during the declare attackers
step" (Tears of Rage, DST; Teleport, LEG), "… during your declare attackers
step" (Camouflage, LEA) — and none of them was ever cast by an AI seat: W1G9
found Tears of Rage cast in no simulated game.

``cast_restrictions.window_closes_before_the_blocks`` is the predicate, read
off each printed ``CAST_RESTRICTIONS`` row through the row's own enforcement
predicate (no list of phrases beside the table), and both gates exempt what
it names: such a card is read through the fight and made for what the fight
leaves (``ai_scoring.read_at_instant_speed``).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_combat import run_ai_combat_phase
from engine.ai_policy import choose_combat_instant_cast_action
from engine.cast_restrictions import CAST_RESTRICTIONS, window_closes_before_the_blocks
from engine.models import Permanent
from tests.helpers import _mk_card, settle

#: What each row's own predicate answers in its caster's declare-attackers
#: step, the attack declared and the blocks to come (CR 508.1, CR 509.1):
#: open now and shut at the blocks (True), or not (False) — open then too,
#: or not open now at all.
EXPECTED = {
    "cast this spell only during your declare attackers step": True,
    "cast this spell only during the declare attackers step": True,
    "cast this spell only before blockers are declared": True,
    "cast this spell only during combat before blockers are declared": True,
    "cast this spell only during combat on your turn before blockers are declared": True,
    # Open in the declare-blockers step too.
    "cast this spell only during combat": False,
    "cast this spell only during combat on your turn": False,
    "cast this spell only before the combat damage step": False,
    "cast this spell only during your turn": False,
    # Not open now.
    "cast this spell only during the declare blockers step": False,
    "cast this spell only during combat after blockers are declared": False,
    "cast this spell only after combat": False,
    "cast this spell only during your end step": False,
    "cast this spell only during an opponent's turn": False,
}


def _attack(game: Game, attacker_seat: int, creatures: list) -> None:
    for creature in creatures:
        permanent = Permanent(card=creature)
        game._put_permanent_onto_battlefield(attacker_seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    game.start_turn(attacker_seat)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step
    slots = [
        index for index, permanent in enumerate(game.players[attacker_seat].battlefield)
        if permanent.is_creature
    ]
    ok, why = game.declare_attackers(attacker_seat, slots, defending_player_index=1 - attacker_seat)
    assert ok, why


def _table(set_pool, hand, mine, theirs=()) -> Game:
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="AI", hand=list(hand), library=[lea["Island"]] * 8),
        PlayerState(name="Opp", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for creature in theirs:
        permanent = Permanent(card=creature)
        game._put_permanent_onto_battlefield(1, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
    _attack(game, 0, mine)
    game.players[0].mana_pool.update({symbol: 3 for symbol in "WUBRG"})
    return game


def test_each_printed_window_is_read_through_its_own_row(set_pool):
    """The predicate asked in the attacker's declare-attackers step, of a
    card printing each row: True exactly where the row's window is open now
    and shut once this combat's blockers are declared. Validated against the
    rows' meanings (CR 506.8), not read back from the table."""
    game = _table(set_pool, (), [set_pool("LEA")["Grizzly Bears"]])
    phrases = {restriction.phrase for restriction in CAST_RESTRICTIONS}
    examined = 0
    for phrase, closes in EXPECTED.items():
        if phrase not in phrases:
            continue
        card = _mk_card(name="Window Probe", type_line="Instant", oracle_text=phrase.capitalize() + ".")
        assert window_closes_before_the_blocks(game, 0, card) is closes, phrase
        examined += 1
    assert examined >= 12
    plain = _mk_card(name="No Window", type_line="Instant", oracle_text="Draw a card.")
    assert not window_closes_before_the_blocks(game, 0, plain)


def test_the_window_is_read_for_the_seat_it_names(set_pool):
    """Teleport's "the declare attackers step" names nobody: shut at the
    blocks for the defending seat too. Camouflage's "your" is the attacker's
    alone, so it is not open for the defender at all."""
    game = _table(set_pool, (), [set_pool("LEA")["Grizzly Bears"]])
    assert window_closes_before_the_blocks(game, 1, set_pool("LEG")["Teleport"])
    assert not window_closes_before_the_blocks(game, 1, set_pool("LEA")["Camouflage"])
    assert window_closes_before_the_blocks(game, 0, set_pool("LEA")["Camouflage"])


def test_teleport_clears_the_lone_attacker_past_the_wall(set_pool):
    """Teleport (LEG): "Target creature can't be blocked this turn", cast
    only during the declare attackers step. A Grizzly Bears attacking into a
    Wall of Stone is two damage stopped; read through the fight, Teleport on
    the Bears is the two damage through, and the seat casts it there — the
    one step it can."""
    lea = set_pool("LEA")
    game = _table(set_pool, [set_pool("LEG")["Teleport"]], [lea["Grizzly Bears"]],
                  theirs=[lea["Wall of Stone"]])
    action = choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Teleport"
    bears = game.players[0].battlefield[0]
    assert action.target_permanent_ids == [bears.permanent_id]
    result = game.cast_from_hand(0, "Teleport", **cast_announcement(action))
    assert result.supported, result.details
    settle(game)
    run_ai_combat_phase(game, 0)
    assert game.players[1].life == 18


def test_teleport_is_held_where_the_block_moves_to_another_attacker(set_pool):
    """Two Bears into one Wall: whichever is made unblockable, the Wall
    blocks the other — the same two damage either way, and the card is
    held."""
    lea = set_pool("LEA")
    game = _table(set_pool, [set_pool("LEG")["Teleport"]],
                  [lea["Grizzly Bears"], lea["Grizzly Bears"]], theirs=[lea["Wall of Stone"]])
    assert choose_combat_instant_cast_action(game, 0) is None
