"""A spliced text's targets are the spell's own (CR 702.47d) — so they can be
changed (CR 115.7) and a copy may choose new ones for them (CR 707.10c).

Wave 1 left both roads reading only the host's announcement: Sideswipe on a
Reach Through Mists with Glacial Ray spliced onto it found "no targets" (the
host draws and targets nothing), and a Forked copy kept the original's Glacial
Ray target with no offer. The slots now carry the segment they live in
(``stack_targets.ChosenTarget.splice``), and the write lands in that segment.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle


def _card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _spliced_ray_at_bobs_bears(set_pool, answer, *, interactive=()):
    """Alice casts Reach Through Mists with Glacial Ray spliced onto it, the
    Ray aimed at Bob's Bears; Bob answers with *answer* (Sideswipe or Fork)
    aimed at the spell. Returns the game and the two Bears, unsettled."""
    card = lambda name: _card(set_pool, name)  # noqa: E731
    game = Game(players=[
        PlayerState(name="Alice", hand=[card("Reach Through Mists"), card("Glacial Ray")],
                    library=[card("Island")] * 6),
        PlayerState(name="Bob", hand=[card(answer)], library=[card("Island")] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    bears = []
    for seat in (0, 1):
        permanent = Permanent(card=card("Grizzly Bears"))
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        bears.append(permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    mine, theirs = bears
    assert game.queue_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [theirs.permanent_id]},
    ]).supported
    assert game.queue_from_hand(1, answer, target_stack_index=0).supported
    return game, mine, theirs


@pytest.mark.cr("115.7c", "702.47d")
def test_sideswipe_changes_the_target_a_spliced_text_chose(set_pool):
    """"You may change any targets of target Arcane spell." The only target
    of the spliced spell is Glacial Ray's, and Bob (a seat nobody asks, the
    measured chooser) moves it from his Bears to Alice's: Alice's die, his
    live, and Alice still draws for the host."""
    game, mine, theirs = _spliced_ray_at_bobs_bears(set_pool, "Sideswipe")
    settle(game)
    assert any(
        "changed Reach Through Mists's target from Bob's Grizzly Bears to "
        "Alice's Grizzly Bears" in line for line in game.log
    ), game.log[-12:]
    assert not game.is_on_battlefield(mine)
    assert game.is_on_battlefield(theirs) and theirs.damage_marked == 0
    assert "Alice drew 1 card(s) (Reach Through Mists)" in game.log


@pytest.mark.cr("115.7c", "702.47d")
def test_a_person_is_offered_the_spliced_texts_target_and_may_keep_it(set_pool):
    """An interactive Bob is asked about the spliced slot (``retarget_choice``,
    "keep" first). Keeping it, the Ray still hits his own Bears."""
    game, mine, theirs = _spliced_ray_at_bobs_bears(
        set_pool, "Sideswipe", interactive={1},
    )
    prompt = settle(game, defaults=False)
    assert prompt is not None and prompt.kind == "retarget_choice"
    options = prompt.data["options"]
    assert options[0]["kind"] == "keep"
    assert any(o.get("permanent_id") == mine.permanent_id for o in options)
    assert game.confirm_retarget_choice(1, 0)
    settle(game)
    assert not game.is_on_battlefield(theirs)
    assert game.is_on_battlefield(mine)


@pytest.mark.cr("707.10c", "702.47d")
def test_a_copy_of_a_spliced_spell_chooses_a_new_target_for_the_spliced_text(set_pool):
    """Fork copies the spell with its spliced text (Uyo, Silent Prophet's
    2004-12-01 ruling: "you'll copy the spliced text as well"), and Bob may
    choose new targets for the copy: its Glacial Ray goes at Alice's Bears
    while the original's still hits his. Both Bears die, and the copy's draw
    is Bob's."""
    game, mine, theirs = _spliced_ray_at_bobs_bears(set_pool, "Fork")
    settle(game)
    assert "Reach Through Mists (copy) targets Alice's Grizzly Bears" in game.log
    assert not game.is_on_battlefield(mine)
    assert not game.is_on_battlefield(theirs)
    assert "Bob drew 1 card(s) (Reach Through Mists)" in game.log
