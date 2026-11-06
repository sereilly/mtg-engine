"""A storm copy is announced once, after its controller decides its target
(CR 707.10c) — Scourge's post-promotion browser session.

Scattershot with storm count 7, aimed at Daru Spiritualist ("Whenever a
Cleric creature you control becomes the target of a spell or ability, it gets
+0/+2 until end of turn"): the seven copies went onto the stack with the
original's target and Daru's trigger fired seven times *before* the re-aim
prompt; the two copies then re-aimed at Zealous Inquisitor (also a Cleric)
fired again for the Inquisitor. Daru ended 1/17. The report's own "should be
1/11" counted five triggers; the right number is six — the original's target
announcement and the five copies kept on Daru — so 1/13, with 6 damage marked.
The census over every copying road is
``tests/engine/test_scg_p5_copy_announcement_census.py``.
"""

from __future__ import annotations

from tests.engine.test_scg_p5_copy_announcement_census import (
    _answer_copy_prompts, _copies, _pool, _table)
from tests.helpers import resolve_stack


def test_the_daru_spiritualist_repro():
    """Storm count 7, aimed at Daru Spiritualist, two copies re-aimed at
    Zealous Inquisitor: Daru hears the original and the five copies kept on
    it — six times, 1/13 — and the Inquisitor the two moved to it, +0/+4."""
    pool = _pool()
    game = _table(
        pool, mine=["Daru Spiritualist", "Zealous Inquisitor"],
        hand=["Dark Ritual"] * 7 + ["Scattershot"], interactive={0},
    )
    for _ in range(7):
        assert game.queue_from_hand(0, "Dark Ritual").supported
        resolve_stack(game)
    daru, inquisitor = game.players[0].battlefield[-2:]
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[daru.permanent_id],
    ).supported
    # The storm trigger and the original's own Daru trigger, in the order the
    # prompt's default keeps; then each resolves until the copies are made.
    game.auto_resolve_pending_choices()
    for _ in range(3):
        if any(item.is_copy for item in game.stack):
            break
        game.resolve_top_of_stack()
    assert len(_copies(game)) == 7
    assert _answer_copy_prompts(
        game, 0, [True, True, False, False, False, False, False],
        inquisitor.permanent_id,
    ) == 7
    resolve_stack(game)
    assert (daru.effective_power, daru.effective_toughness - daru.damage_marked) == (1, 13 - 6)
    assert inquisitor.effective_toughness == 2 + 4
