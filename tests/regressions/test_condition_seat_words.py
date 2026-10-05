"""Regression: a counted "controls" condition asks about the seat its printed
word names — not about the whole table.

``handlers/control_flow.evaluate_condition`` answers ``kind: controls`` by
counting the boards of a list of players, and the list defaulted to *every*
player for any seat word it did not name. Two words fell through:

* ``defending_player`` (Spectral Bears' intervening-if, CR 603.4/506.2) counted
  the **attacker's own** board too, so a Spectral Bears beside a Black Knight
  never triggered and untapped every turn the card says it should not — wrong
  in its controller's favour, and invisible to every coverage instrument,
  because the program was right and only the evaluator's seat was not;
* ``target_opponent`` / ``target_player`` would have counted every opponent
  rather than the one the spell chose (no shipped card prints a counted one).

And one word is a trap held shut at the lowering: ``each_opponent`` is both
"each opponent" and "your opponents" (`grammar/seats.py` aliases them), which
agree only on "no"/zero. Kezzerdrix prints exactly that; any other count is
refused rather than answered by a sum the card may not mean.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar import compile_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import _nosick, resolve_stack


def _w2g5_attack_with_spectral_bears(set_pool, *, mine=(), theirs=()):
    bears = _nosick(Permanent(card=set_pool("HML")["Spectral Bears"]))
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(
            name="P0", battlefield=[bears, *(Permanent(card=lea[n]) for n in mine)],
            library=[lea["Forest"]] * 5,
        ),
        PlayerState(
            name="P1", battlefield=[Permanent(card=lea[n]) for n in theirs],
            library=[lea["Forest"]] * 5,
        ),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    return game, bears  # _w2g5_attack_with_spectral_bears


def test_spectral_bears_ignores_its_own_controllers_black_permanents(set_pool):
    """"Whenever this creature attacks, if **defending player** controls no
    black nontoken permanents, it doesn't untap during your next untap step."
    The defender controls none; the attacker's own Black Knight is not the
    defending player's, and must not stop the trigger."""
    game, bears = _w2g5_attack_with_spectral_bears(set_pool, mine=["Black Knight"])

    assert "Spectral Bears won't untap during P0's next untap step" in game.log
    game.start_turn(0)
    assert bears.tapped, "the Bears skipped this untap step"


def test_spectral_bears_untaps_when_the_defender_controls_a_black_permanent(set_pool):
    """The control: the condition is still asked of the defender, so a black
    nontoken permanent on *their* side keeps the trigger from firing."""
    game, bears = _w2g5_attack_with_spectral_bears(set_pool, theirs=["Black Knight"])

    assert any("didn't trigger" in line for line in game.log)
    game.start_turn(0)
    assert not bears.tapped


def _w2g5_kezzerdrix_upkeep(set_pool, opponent_boards):
    """Kezzerdrix's controller at seat 0 of a table with one opponent per entry
    of *opponent_boards*, each a list of LEA card names on that opponent's
    battlefield."""
    lea = set_pool("LEA")
    kezzerdrix = Permanent(card=set_pool("TMP")["Kezzerdrix"])
    players = [PlayerState(name="P0", battlefield=[kezzerdrix])] + [
        PlayerState(name=f"P{i + 1}", battlefield=[Permanent(card=lea[n]) for n in board])
        for i, board in enumerate(opponent_boards)
    ]
    game = Game(players=players)
    game.active_player_index = 0
    game.resolve_upkeep(0)
    game._settle()
    resolve_stack(game)
    return game  # _w2g5_kezzerdrix_upkeep


def test_kezzerdrix_hits_its_controller_when_no_opponent_has_a_creature(set_pool):
    """"…if **your opponents** control no creatures, this creature deals 4
    damage to you." Pinned at a three-seat table: no opponent has one."""
    game = _w2g5_kezzerdrix_upkeep(set_pool, [["Forest"], ["Island"]])
    assert game.players[0].life == 16


def test_kezzerdrix_holds_its_fire_when_any_opponent_has_a_creature(set_pool):
    """Zero is the one count where "the total over your opponents" and "each
    opponent's own" agree: one opponent's Bears makes both readings false."""
    game = _w2g5_kezzerdrix_upkeep(set_pool, [["Forest"], ["Grizzly Bears"]])
    assert game.players[0].life == 20


def test_a_counted_each_opponent_condition_is_refused_not_pooled():
    """An invented line printing the two spellings with a real number. "Your
    opponents control two or more creatures" is a total; "each opponent
    controls two or more" is a test every opponent must pass. The seat word
    cannot carry the difference, so the lowering refuses both, naming why —
    rather than answering both with the sum."""
    for line in (
        "At the beginning of your upkeep, if your opponents control two or more "
        "creatures, you gain 1 life.",
        "At the beginning of your upkeep, if each opponent controls two or more "
        "creatures, you gain 1 life.",
    ):
        compiled = compile_line(line)
        assert not compiled.instructions, line
        assert "each opponent" in (compiled.lowering_error or ""), compiled.lowering_error


def test_no_shipped_card_prints_a_counted_each_opponent_board_condition():
    """The pin, with a floor on what it read: every ``controls`` condition in
    the pool (both manifest roles), and every ``each_opponent`` one is a zero.

    Kezzerdrix's was the only one until Invasion, whose two Kavus print the
    same count with the negation on the *seat* — "as long as **no opponent**
    controls a white or blue creature" — and on a static rather than an
    intervening-if. The invariant is the zero, which is what both evaluators'
    pooled tallies are right for; the names are pinned beside it so a third
    arrival is read rather than waved through.
    """

    def walk(value, seen):
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, dict):
            if value.get("kind") == "controls":
                yield value
            for inner in value.values():
                yield from walk(inner, seen)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                yield from walk(inner, seen)
        elif hasattr(value, "__dataclass_fields__"):
            for name in value.__dataclass_fields__:
                yield from walk(getattr(value, name), seen)

    examined = 0
    each_opponent = []
    for card in load_cards(manifest_set_paths(include_measured=True)):
        for payload in walk(compile_card_oracle(card), set()):
            examined += 1
            if payload.get("who") == "each_opponent":
                each_opponent.append((card.name, payload.get("op"), payload.get("count")))

    assert examined >= 50, examined
    assert all((op, count) == ("eq", 0) for _name, op, count in each_opponent), (
        each_opponent
    )
    assert sorted(name for name, _op, _count in each_opponent) == [
        "Kavu Runner", "Kezzerdrix", "Skittish Kavu",
    ]
