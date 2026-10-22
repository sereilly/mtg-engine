"""Census: does a cast proposal depend on cards its seat cannot see?

The policy rehearses a candidate cast on a copy of the game
(``ai_rehearsal.rehearse``), and a copy of the game is a copy of everything
in it — the next card of every library and every card in the other player's
hand. Read as they stand, a rehearsed Duress knows whether there is a card
for it to take: the cast was *proposed* when the opponent held a spell and
*held* when the same opponent, with the same deck, held lands. That is a
decision made on a hidden zone (CR 400.2).

``ai_rehearsal.conceal_from`` deals what the seat cannot see again, on the
copy, out of everything it cannot tell apart. This sweep is the definition of
that being done.

**How it is built.** The population is every supported instant and sorcery,
each mode of a caster-chosen modal one offered alone — the idle-cast census's
population and its ``mirror`` board, so every target has something to name.
Each is asked for its proposal (``choose_cast_action``) in three **worlds**
that differ only in where hidden cards are:

``lands``
    the opponent holds three lands; three spells are in their library;
``spells``
    the opponent holds those three spells — a creature, an instant and an
    artifact card — and the lands are in the library;
``reversed``
    ``spells``, with both libraries in the opposite order.

Every world has the same cards in the same player's hand-and-library, the
same sizes of hand, and the same table. A seat that sees only what it may
proposes the same cast in all three — the same card, mode, target, payment
and score.

Validated backwards, over the whole pool (1,073 ``(card, mode)``s) on the
tree before the copy concealed anything: see ``BEFORE``, the rows that
differed there, which the suite always sweeps. The suite runs a fixed share
of the rest (``SAMPLE_EVERY``); run it as a module for all of it
(``python -m tests.ai.test_ai_hidden_information_census``). And it is
validated backwards **in the suite** too: with the concealment taken out
again (`test_the_sweep_can_tell`), the named rows differ.
"""
from __future__ import annotations

import random
import sys
from dataclasses import replace
from unittest import mock

import pytest

from engine import Game, PlayerState
from engine import ai_rehearsal
from engine.ai_actions import cast_announcement
from engine.ai_policy import choose_cast_action
from tests.ai import test_ai_idle_cast_census as idle
from tests.ai import test_ai_mode_chooser_census as modes
from tests.helpers import _mk_card

ME, OPP = 0, 1
POOL = modes.POOL
WORLDS = ("lands", "spells", "reversed")

#: The three cards that are in the opponent's hand in one world and in their
#: library in another: one of each kind a "discard a … card" asks for.
HIDDEN = (
    _mk_card(
        name="Bait Hidden Creature", type_line="Creature - Beast", colors=("B",),
        mana_cost="{2}{B}", power=3, toughness=3,
    ),
    _mk_card(name="Bait Hidden Instant", type_line="Instant", colors=("U",), mana_cost="{U}"),
    _mk_card(name="Bait Hidden Artifact", type_line="Artifact", mana_cost="{2}"),
)
#: The caster's own library: lands and spells of different costs, so that
#: which of them is on top is something a cast could turn on.
OWN_LIBRARY = (
    "Forest", "Forest", "Forest", "Forest", "Forest",
    "Lightning Bolt", "Grizzly Bears", "Craw Wurm", "Sol Ring", "Wrath of God",
)

#: The suite's share of the pool: every card whose place in the sorted
#: population is a multiple of this, and the named ones.
SAMPLE_EVERY = 12

#: ``(card, mode)`` -> the proposals that differed, on the tree whose copy
#: held the real hands and libraries. Each is swept by the suite.
BEFORE: dict = {
    ("Duress", None): "held against a hand of lands, cast against one holding a spell",
    ("Ostracize", None): "held against a hand of lands, cast against one holding a creature",
}
ALWAYS = frozenset(key[0] for key in BEFORE)
assert ALWAYS <= set(POOL), sorted(ALWAYS - set(POOL))


def board(card, world: str) -> Game:
    """The idle census's ``mirror`` board, in *world*."""
    forest = POOL["Forest"]
    own = [POOL[name] for name in OWN_LIBRARY]
    if world == "lands":
        their_hand, their_library = [forest] * 3, [*HIDDEN, *[forest] * 7]
    else:
        their_hand, their_library = list(HIDDEN), [forest] * 10
    if world == "reversed":
        own.reverse()
        their_library.reverse()
    game = Game(players=[
        PlayerState(name="AI", hand=[card], library=own),
        PlayerState(name="Opp", hand=their_hand, library=their_library),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat in (ME, OPP):
        for key in idle.UNITS:
            modes.place(game, seat, key)
    game.players[ME].mana_pool.update({symbol: 8 for symbol in "WUBRG"})
    return game


def proposal(card, mode, world: str) -> "dict | None":
    """What seat 0 proposes to cast in *world*, or None when it holds the
    card. Permanents by seat and slot: two boards built alike number theirs
    differently (CR 400.7's counter is the process's)."""
    # The real game's randomness on a fixed seed, as the idle census fixes it.
    random.seed(1337)
    with idle.only_mode(card, mode):
        game = board(card, world)
        action = choose_cast_action(game, ME)
    if action is None or action.card_name != card.name:
        return None
    named = [
        (game.controller_index_of(permanent), game.battlefield_index_of(permanent))
        for permanent in map(game.permanent_by_id, action.target_permanent_ids or ())
        if permanent is not None
    ]
    said = cast_announcement(replace(action, target_permanent_ids=None))
    return {
        **said, "named": named, "score": action.score,
        "taps": (action.land_tap_indices, action.land_tap_colors),
    }


def run(card, mode) -> dict:
    row = {"card": card.name, "mode": mode, "error": None, "proposals": {}}
    try:
        for world in WORLDS:
            row["proposals"][world] = proposal(card, mode, world)
    except Exception as exc:  # a crash is a finding, not a pass
        row["error"] = f"EXC {type(exc).__name__}: {exc}"
    return row


def census(sample: bool) -> list:
    rows = []
    for position, (card, mode) in enumerate(idle.population()):
        if sample and position % SAMPLE_EVERY and card.name not in ALWAYS:
            continue
        rows.append(run(card, mode))
    return rows


def tag(row) -> tuple:
    return (row["card"], row["mode"])


def differing(rows) -> dict:
    """The rows whose proposal is not the same in every world, each with the
    worlds it was made in."""
    found = {}
    for row in rows:
        if row["error"]:
            continue
        seen = row["proposals"]
        if any(seen[world] != seen[WORLDS[0]] for world in WORLDS):
            found[tag(row)] = {
                world: ("held" if seen[world] is None else round(seen[world]["score"], 3))
                for world in WORLDS
            }
    return found


class the_real_hidden_cards:
    """The copy as it was: libraries shuffled where they stood, the opposing
    hand left as it is — what a rehearsal read before it concealed anything."""

    def __enter__(self):
        def shuffle_in_place(game, seat) -> None:
            for player in game.players:
                random.shuffle(player.library)

        self.patch = mock.patch.object(ai_rehearsal, "conceal_from", shuffle_in_place)
        self.patch.start()

    def __exit__(self, *exc) -> None:
        self.patch.stop()


# -- the tests ------------------------------------------------------------------

@pytest.fixture(scope="module")
def rows() -> list:
    return census(sample=True)


def test_the_sweep_examined_the_pool(rows):
    """The floor: a sweep that reaches nothing passes everything."""
    assert len(rows) >= 85
    assert ALWAYS <= {row["card"] for row in rows}
    # ...and that it is a sweep of proposals: a cast that is never proposed
    # is the same in every world whatever the copy shows.
    proposed = [
        row for row in rows
        if any(row["proposals"].get(world) is not None for world in WORLDS)
    ]
    assert len(proposed) >= 45, len(proposed)


def test_no_proposal_crashed(rows):
    assert {tag(row): row["error"] for row in rows if row["error"]} == {}


def test_a_proposal_is_the_same_whatever_the_hidden_cards_are(rows):
    assert differing(rows) == {}


def test_the_sweep_can_tell():
    """Backwards, where the suite can see it: with the opposing hand left as
    it stands in the copy, the casts that take a card of one kind out of it
    are proposed in one world and held in another."""
    with the_real_hidden_cards():
        found = differing([
            run(card, mode) for card, mode in idle.population()
            if card.name in ALWAYS
        ])
    assert set(BEFORE) <= set(found), sorted(set(BEFORE) - set(found))


def test_duress_is_weighed_against_a_hand_it_cannot_see():
    """One row, readable: Duress ("…reveals their hand. You choose a
    noncreature, nonland card from it. That player discards that card.")
    against three lands and against three spells. The proposal is one
    proposal — it was no cast and a cast."""
    duress = POOL["Duress"]
    assert proposal(duress, None, "lands") == proposal(duress, None, "spells")


if __name__ == "__main__":
    rows = census(sample="--sample" in sys.argv)
    found = differing(rows)
    errors = {tag(row): row["error"] for row in rows if row["error"]}
    proposed = sum(
        1 for row in rows
        if any(row["proposals"].get(world) is not None for world in WORLDS)
    )
    print(f"rows: {len(rows)}  cards: {len({row['card'] for row in rows})}  "
          f"proposed in some world: {proposed}")
    print(f"== differ: {len(found)}")
    for key in sorted(found, key=lambda k: (k[0], str(k[1]))):
        print(f"   {key}: {found[key]}")
    print(f"== error: {len(errors)}")
    for key in sorted(errors, key=lambda k: (k[0], str(k[1]))):
        print(f"   {key}: {errors[key]}")
