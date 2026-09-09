"""Two copies of one upkeep card are two decisions — CR 603.3 / 603.3d.

The upkeep step's interactive prompts (``get_upkeep_pay_triggers`` and friends)
are the one prompt protocol in this engine that never got the treatment
CLAUDE.md's "address a permanent by its id, not its slot" section describes.
They addressed a permanent by its **printed card name**, on both sides: the
prompt carried ``card_name`` and the answer map was keyed by it. That is the
same failure as addressing by index, with a name instead of a number, and it
fails in the same direction — the look-alike answers too.

Two shapes, both measured on a real board before this file existed:

* **The pay-or-consequence prompt** (112 shipped cards: every non-legendary
  card with cumulative upkeep, "sacrifice this unless you pay", echo, and the
  rest). Two Breeding Pits and four black mana: ``{"Breeding Pit": True}``
  paid for **both**, spending {B}{B}{B}{B}. There was no way to say "pay for
  this one, let that one go" — one answer for two abilities, which CR 603.3
  says are two abilities, each put on the stack and each resolving on its own.

* **The targeted upkeep trigger** (2 shipped cards a seat can hold two of:
  Erhnam Djinn and Afiya Grove — Halfdane prints the third such trigger but is
  legendary, so CR 704.5j means one controller never has two). Two Erhnam
  Djinns produced **one** prompt, because the collector deduped by name, and
  the single answer was then used for both triggers: both Djinns granted
  forestwalk to the same creature. CR 603.3d sends the choice through CR
  601.2c, which is made per ability, by its controller, as it goes on the
  stack. This is the worse of the two — it is an *unasked* choice rather than
  a shared answer.

The fix is the id: every battlefield-backed upkeep prompt carries
``permanent_id`` (CR 400.7's identity, stamped on entering the battlefield) and
every answer map is keyed by it. A **string** key is still accepted as the
legacy shorthand — it names a *card*, so it answers every copy at once, which
is what a board with one copy has always meant — and is normalised to ids in
exactly one place, ``Game._upkeep_answers_by_permanent``, so no handler below
can be written against a name again. The two prompts whose subject is not a
permanent (Nether Shadow in a graveyard, a Nafs Asp obligation record) keep
their name key and are named in ``ROADMAP.md``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState

from ..helpers import resolve_stack


def _upkeep_game(p1: PlayerState, p2: PlayerState) -> Game:
    game = Game(players=[p1, p2])
    game.active_player_index = 0
    game._refresh_dynamic_creatures()
    return game


# ---------------------------------------------------------------------------
# The pay-or-consequence prompt
# ---------------------------------------------------------------------------

@pytest.mark.cr("603.3", "603.3b", "702.24a")
def test_two_copies_of_one_upkeep_cost_are_two_separate_decisions(set_pool):
    """Two Breeding Pits: pay for one, let the other go.

    CR 603.3 puts *each* ability that triggered on the stack and CR 603.3b
    orders them; each carries its own "unless you pay" decision. So the prompt
    has to be able to name which permanent it is quoting a price for, and the
    answer has to be able to name which one it is buying.

    The assertion that matters is the pair: one Breeding Pit survives *and*
    the other is in the graveyard, out of one call. Before the ids, the same
    call paid for both and sacrificed neither.
    """
    fem = set_pool("FEM")
    kept = Permanent(card=fem["Breeding Pit"])
    doomed = Permanent(card=fem["Breeding Pit"])
    payer = PlayerState(name="P1", battlefield=[kept, doomed])
    payer.mana_pool = {"B": 4}
    game = _upkeep_game(payer, PlayerState(name="P2"))

    prompts = game.get_upkeep_pay_triggers(0)
    assert [p["card_name"] for p in prompts] == ["Breeding Pit", "Breeding Pit"]
    # Two prompts that can be told apart. This is the whole defect: the entries
    # were byte-identical, so a client could render two buttons and the server
    # could not tell which one had been pressed.
    assert {p["permanent_id"] for p in prompts} == {
        kept.permanent_id, doomed.permanent_id
    }

    game.resolve_upkeep(0, human_choices={
        kept.permanent_id: True,
        doomed.permanent_id: False,
    })

    assert [p.card.name for p in payer.battlefield] == ["Breeding Pit"]
    assert payer.battlefield[0] is kept
    assert [c.name for c in payer.graveyard] == ["Breeding Pit"]
    # One payment and one sacrifice, read off the log rather than off the mana
    # pool: CR 500.4 empties the pool as the step ends, so what is left there
    # says nothing about what was spent.
    assert sum("paid upkeep for Breeding Pit" in line for line in game.log) == 1
    assert sum("sacrificed Breeding Pit" in line for line in game.log) == 1


@pytest.mark.cr("603.3", "702.24a")
def test_a_card_name_answer_still_speaks_for_every_copy(set_pool):
    """The legacy shorthand, asserted rather than left as folklore.

    ``resolve_upkeep`` still accepts a printed name, because every headless
    caller and every test in this repo uses one and on a board with a single
    copy it is exact. What it means is "every permanent of this name", and
    that has to be *stated* — a shorthand nobody has written down is a
    shorthand somebody re-derives as "the first one".
    """
    fem = set_pool("FEM")
    first = Permanent(card=fem["Breeding Pit"])
    second = Permanent(card=fem["Breeding Pit"])
    payer = PlayerState(name="P1", battlefield=[first, second])
    payer.mana_pool = {"B": 4}
    game = _upkeep_game(payer, PlayerState(name="P2"))

    game.resolve_upkeep(0, human_choices={"Breeding Pit": False})

    assert [p.card.name for p in payer.battlefield] == []
    assert [c.name for c in payer.graveyard] == ["Breeding Pit", "Breeding Pit"]
    assert sum("paid upkeep for Breeding Pit" in line for line in game.log) == 0


@pytest.mark.cr("603.3", "702.24a")
def test_an_id_answer_wins_over_a_name_answer_for_the_same_permanent(set_pool):
    """A precedence the normalisation has to state, because it has one.

    A caller that sends both is answering the same decision twice; the id is
    the specific answer and the name is the blanket one, so the id wins. The
    alternative — dict order — is the silent-precedence bug the upkeep
    registry itself was built to remove.
    """
    fem = set_pool("FEM")
    kept = Permanent(card=fem["Breeding Pit"])
    doomed = Permanent(card=fem["Breeding Pit"])
    payer = PlayerState(name="P1", battlefield=[kept, doomed])
    payer.mana_pool = {"B": 4}
    game = _upkeep_game(payer, PlayerState(name="P2"))

    game.resolve_upkeep(0, human_choices={
        "Breeding Pit": False,
        kept.permanent_id: True,
    })

    assert [p.card.name for p in payer.battlefield] == ["Breeding Pit"]
    assert payer.battlefield[0] is kept


# ---------------------------------------------------------------------------
# The targeted upkeep trigger
# ---------------------------------------------------------------------------

@pytest.mark.cr("603.3d", "601.2c")
def test_two_targeted_upkeep_triggers_each_ask_their_own_target(set_pool):
    """Two Erhnam Djinns choose two different creatures.

    CR 603.3d hands the remainder of putting a triggered ability on the stack
    to CR 601.2c — targets are chosen per ability. The collector deduped by
    printed name, so the second Djinn's ability was never offered a choice and
    silently reused the first's answer: both grants landed on one creature.

    Driven through the real upkeep step and read off the board, not off the
    prompt list — the prompt being right is necessary and not sufficient.
    """
    arn, lea = set_pool("ARN"), set_pool("LEA")
    first = Permanent(card=arn["Erhnam Djinn"])
    second = Permanent(card=arn["Erhnam Djinn"])
    bears = Permanent(card=lea["Grizzly Bears"])
    giant = Permanent(card=lea["Hill Giant"])
    mine = PlayerState(name="P1", battlefield=[first, second])
    theirs = PlayerState(name="P2", battlefield=[bears, giant])
    game = _upkeep_game(mine, theirs)

    prompts = game.get_upkeep_target_triggers(0)
    assert len(prompts) == 2, "one prompt for two triggers is an unasked choice"
    assert {p["permanent_id"] for p in prompts} == {
        first.permanent_id, second.permanent_id
    }

    game.resolve_upkeep(0, trigger_targets={
        first.permanent_id: (1, 0),   # Grizzly Bears
        second.permanent_id: (1, 1),  # Hill Giant
    })
    resolve_stack(game)

    assert game._has_keyword(bears, "forestwalk")
    assert game._has_keyword(giant, "forestwalk")


@pytest.mark.cr("603.3d")
def test_a_second_targeted_trigger_is_not_answered_by_the_firsts_pick(set_pool):
    """The half of the defect that is *not* fixed by offering two prompts.

    A client that answers only the first prompt must leave the second one
    unanswered rather than have its own answer applied to it. With the name as
    the key the two were indistinguishable, so answering "the Erhnam Djinn"
    answered both; with ids the unanswered trigger falls back to the first
    legal candidate, which is the AI/headless rule and not the other seat's
    pick.
    """
    arn, lea = set_pool("ARN"), set_pool("LEA")
    first = Permanent(card=arn["Erhnam Djinn"])
    second = Permanent(card=arn["Erhnam Djinn"])
    bears = Permanent(card=lea["Grizzly Bears"])
    giant = Permanent(card=lea["Hill Giant"])
    mine = PlayerState(name="P1", battlefield=[first, second])
    theirs = PlayerState(name="P2", battlefield=[bears, giant])
    game = _upkeep_game(mine, theirs)

    # Only the *second* Djinn is answered, and it picks the Hill Giant.
    game.resolve_upkeep(0, trigger_targets={second.permanent_id: (1, 1)})
    resolve_stack(game)

    # The unanswered one took the first legal candidate rather than the Hill
    # Giant, so both creatures ended up walking — which is only observable
    # because the two triggers were told apart.
    assert game._has_keyword(bears, "forestwalk")
    assert game._has_keyword(giant, "forestwalk")


@pytest.mark.cr("603.3d", "601.2c")
def test_two_afiya_groves_move_a_counter_onto_two_different_creatures(set_pool):
    """The other shipped card a seat can hold two of.

    "At the beginning of your upkeep, move a +1/+1 counter from this
    enchantment onto target creature." Two Groves, two counters moved, and
    with the name as the key both landed on whichever creature the one prompt
    named.
    """
    mir, lea = set_pool("MIR"), set_pool("LEA")
    grove_a = Permanent(card=mir["Afiya Grove"])
    grove_b = Permanent(card=mir["Afiya Grove"])
    bears = Permanent(card=lea["Grizzly Bears"])
    giant = Permanent(card=lea["Hill Giant"])
    mine = PlayerState(name="P1", battlefield=[grove_a, grove_b, bears, giant])
    game = _upkeep_game(mine, PlayerState(name="P2"))
    game._initialize_permanent_state(grove_a, 0, None)
    game._initialize_permanent_state(grove_b, 0, None)

    prompts = game.get_upkeep_target_triggers(0)
    assert len(prompts) == 2
    assert {p["permanent_id"] for p in prompts} == {
        grove_a.permanent_id, grove_b.permanent_id
    }

    game.resolve_upkeep(0, trigger_targets={
        grove_a.permanent_id: (0, 2),  # Grizzly Bears
        grove_b.permanent_id: (0, 3),  # Hill Giant
    })
    resolve_stack(game)

    from engine.named_counters import counters_on

    assert counters_on(bears, "+1/+1") == 1
    assert counters_on(giant, "+1/+1") == 1
