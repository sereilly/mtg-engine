"""Census: does an AI seat cast a spell that does nothing — or does it to itself?

Three ways a cast is legal and worse than holding the card, and until the
policy measured a cast before proposing it (``ai_valuation.rehearse``) it made
all three:

``idle``
    the resolution moves nothing: a discard aimed at an empty hand, a sweeper
    with nothing to sweep, "attacking creatures get +1/+0" in a main phase, a
    counter-if-it-was-kicked aimed at a spell that was not;
``loss``
    its caster is measurably worse off for it and nobody else is: a removal
    spell whose only legal target is the caster's own creature, Donate handing
    over a permanent, Wrath of God onto a board that is all the caster's;
``own goal``
    the cast names one of the caster's own permanents **with its twin on the
    other side of the table a legal target that measures more**. Seen once in
    a browser as Swords to Plowshares on the AI's own Grizzly Bears: the card
    compiles to a kind with no ``targets`` payload, so nothing read a side for
    it, and the seat came from the words "gains life" in its text.

**How it is built.** The population is every supported instant and sorcery —
each mode of a caster-chosen modal one offered alone, as the mode census
offers it. Three boards, none of them built for any card:

* ``empty``  — nothing on the table, nothing in the opposing hand;
* ``own``    — one of each census permanent, all on the caster's side;
* ``mirror`` — the same on both sides, so every target has a twin.

The proposal is ``choose_cast_action`` and the cast is the simulator's own
executor. What it did is the engine's answer: the table compared with itself a
moment earlier (`table_state`, from the mode census), and each seat's standing
priced with ``ai_valuation`` — the one definition of "larger" the policy
predicts with and this measures with.

Validated backwards, over the whole pool (1,073 ``(card, mode)``s, three
boards each) on the tree before the policy measured a cast: 2,071 casts
proposed, **587 of them idle, 177 losses and 11 own goals** — Swords to
Plowshares among the last, at -8.0 where its twin measures 8.0. After: 1,323
proposed (6,985 rehearsals asked for, none of which could not be run), none
idle, no own goal, and the three losses in ``LOSSES`` below, which are one
card flipping a coin.

The whole pool takes ten minutes, so the suite runs a fixed sixth of it
(``SAMPLE_EVERY``) plus every card named in a pin or in ``ALWAYS``; run it as
a module (``python -m tests.ai.test_ai_idle_cast_census``) for all of it.
"""
from __future__ import annotations

import contextlib
import random
import sys
from collections import Counter
from unittest import mock

import pytest

from engine import Game, PlayerState
from engine import ai_simulator
from engine.ai_policy import choose_cast_action
from engine.ai_valuation import (CARD_WORTH, standing_swing, standings,
                                 swing_worth)
from engine.oracle import compile_card_oracle
from tests.ai import test_ai_mode_chooser_census as modes

ME, OPP = 0, 1
POOL = modes.POOL

#: One of each kind of thing a spell can act on. The same units on both sides
#: of a ``mirror`` board, in the same order, so a slot on one side is its twin
#: on the other.
UNITS = (
    "white creature", "black creature", "artifact", "enchantment",
    "nonbasic land", "island",
)
LAYOUTS = {"empty": (), "own": (ME,), "mirror": (ME, OPP)}

#: The suite's share of the pool: every card whose place in the sorted
#: population is a multiple of this, and the named ones.
SAMPLE_EVERY = 6
#: Cards the suite always sweeps: the ones the round was briefed with.
ALWAYS = frozenset({
    "Swords to Plowshares", "Donate", "Kor Chant", "Ertai's Trickery", "Winnow",
    "Mind Rot", "Duress", "Wrath of God", "Hymn to Tourach",
})

#: A cast is a loss when it leaves its caster this much worse off: half a
#: life, and a hair, so that a cast the policy measured at exactly its own
#: floor (``ai_policy.HARM_FLOOR``) is not one.
LOSS = -0.51
EPSILON = 0.01


def population() -> list:
    """``(card, mode)`` for every supported instant and sorcery: each mode of
    a caster-chosen modal one, None for every other."""
    found = []
    for name in sorted(POOL):
        card = POOL[name]
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        chooses = bool(program.modes) and program.mode_chooser is None
        for mode in (range(len(program.modes)) if chooses else (None,)):
            found.append((card, mode))
    return found


def board(card, layout: str):
    forest = POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[card], library=[forest] * 10),
        PlayerState(name="Opp", hand=[], library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat in LAYOUTS[layout]:
        for key in UNITS:
            modes.place(game, seat, key)
    game.players[ME].mana_pool.update({symbol: 8 for symbol in "WUBRG"})
    return game


_UNTOUCHED: dict = {}


def untouched(layout: str) -> tuple:
    """Each seat's standing on *layout* once the turn has run out with nothing
    cast. One card in hand whichever card it is, so one reading per board."""
    if layout not in _UNTOUCHED:
        game = board(POOL["Forest"], layout)
        modes.run_out(game)
        _UNTOUCHED[layout] = standings(game, now=False)
    return _UNTOUCHED[layout]


def worth(game, card, layout: str, before_now: tuple) -> float:
    """What the cast of *card* that has just resolved on *game* was worth to
    seat 0."""
    # The spell's own card is not part of what the cast did — unless it is
    # back in the hand it left (buyback), and then nothing was spent.
    spent = CARD_WORTH * (0 if any(held is card for held in game.players[ME].hand) else 1)
    now = standing_swing(before_now, standings(game), ME) + spent
    modes.run_out(game)
    lasting = standing_swing(untouched(layout), standings(game, now=False), ME) + spent
    return round(swing_worth(now, lasting), 3)


def own_slot(game, layout: str, action) -> "int | None":
    """The slot of the caster's **own** permanent *action* names on a mirror
    board, or None when it names none of its own."""
    ids = action.target_permanent_ids or []
    if layout != "mirror" or len(ids) != 1:
        return None
    named = game.permanent_by_id(ids[0])
    if named is None or game.controller_index_of(named) != ME:
        return None
    return game.battlefield_index_of(named)


def twin_measure(card, mode, layout: str, action, slot: int) -> "float | None":
    """What the same cast measures aimed at the opposing twin of the caster's
    own permanent in *slot* — or None when the twin is not a legal target."""
    game = board(card, layout)
    twin = game.permanent_at(OPP, slot)
    mine = game.permanent_at(ME, slot)
    if twin is None or mine is None or twin.card.name != mine.card.name:
        return None
    before_now = standings(game)
    result = game.queue_from_hand(
        ME, card.name, mode_index=mode, x_value=action.x_value,
        target_player_index=OPP, target_permanent_ids=[twin.permanent_id],
    )
    if not result.supported:
        return None
    modes.settle(game)
    return worth(game, card, layout, before_now)


class only_mode:
    """Offer *card* in *mode* alone (None: a card that names no mode)."""

    def __init__(self, card, mode):
        real = Game.announceable_modes

        def only(game, caster_index, asked, **kwargs):
            offered = real(game, caster_index, asked, **kwargs)
            if asked.name != card.name:
                return offered
            return [mode] if mode in offered else []

        self.patch = (
            mock.patch.object(Game, "announceable_modes", only)
            if mode is not None else None
        )

    def __enter__(self):
        if self.patch is not None:
            self.patch.start()

    def __exit__(self, *exc):
        if self.patch is not None:
            self.patch.stop()


def run(card, mode, layout: str) -> dict:
    row = {
        "card": card.name, "mode": mode, "layout": layout, "proposed": False,
        "accepted": None, "moved": None, "swing": None, "twin": None, "error": None,
    }
    try:
        # The real cast's randomness on a fixed seed: a coin-flip spell is
        # otherwise idle or not by whatever test ran before this one.
        random.seed(1337)
        with only_mode(card, mode):
            game = board(card, layout)
            action = choose_cast_action(game, ME)
            if action is None or action.card_name != card.name:
                return row
            row["proposed"] = True
            slot = own_slot(game, layout, action)
            before = modes.table_state(game, card)
            mana_before = modes.pools(game)
            before_now = standings(game)
            report = ai_simulator.SimulationReport(
                games_requested=1, games_completed=0, interaction_count=0,
            )
            cast = ai_simulator._play_one_cast(game, ME, report, 1, 1)
            row["accepted"] = bool(cast) and not report.refused_casts
            if not row["accepted"]:
                row["error"] = "; ".join(report.refused_casts) or "refused"
                return row
            modes.settle(game)
            row["moved"] = (
                modes.table_state(game, card) != before
                or modes.mana_made(mana_before, game)
            )
            row["swing"] = worth(game, card, layout, before_now)
        if slot is not None:
            row["twin"] = twin_measure(card, mode, layout, action, slot)
    except Exception as exc:  # a crash is a finding, not a pass
        row["error"] = f"EXC {type(exc).__name__}: {exc}"
    return row


#: How many rehearsals the sweep's proposals asked for, and how many of them
#: could not be run (``ai_valuation.rehearse`` answering None). A policy whose
#: every rehearsal failed would propose as the old one did and this sweep
#: would say so in 590 lines; one that failed for a few cards would hide them.
REHEARSALS = Counter()


def census(sample: bool) -> list:
    from engine import ai_policy

    # None on a tree whose policy does not rehearse: the sweep still runs
    # there (that is how it is validated backwards) and counts none.
    real = getattr(ai_policy, "rehearse", None)

    def counted(*args, **kwargs):
        got = real(*args, **kwargs)
        REHEARSALS["asked"] += 1
        REHEARSALS["not run"] += got is None
        return got

    rows = []
    with (
        mock.patch.object(ai_policy, "rehearse", counted) if real is not None
        else contextlib.nullcontext()
    ):
        for position, (card, mode) in enumerate(population()):
            if sample and position % SAMPLE_EVERY and card.name not in SWEPT:
                continue
            for layout in LAYOUTS:
                rows.append(run(card, mode, layout))
    return rows


def tag(row) -> tuple:
    return (row["card"], row["mode"], row["layout"])


def findings(rows) -> dict:
    out: dict = {"idle": {}, "loss": {}, "own goal": {}, "error": {}}
    for row in rows:
        if row["error"]:
            out["error"][tag(row)] = row["error"]
            continue
        if not row["proposed"]:
            continue
        if not row["moved"]:
            out["idle"][tag(row)] = "moved nothing"
        elif row["swing"] is not None and row["swing"] < LOSS:
            out["loss"][tag(row)] = row["swing"]
        if row["twin"] is not None and row["twin"] > row["swing"] + EPSILON:
            out["own goal"][tag(row)] = (row["swing"], row["twin"])
    return out


# -- the pins -------------------------------------------------------------------

#: Casts still proposed that move nothing, each with why it stands.
IDLE: dict = {}

#: Casts still proposed that leave their caster worse off, each with why.
#:
#: Game of Chaos flips a coin for a point of life each way and doubles the
#: stakes. A rehearsal's randomness is its own on purpose
#: (``ai_valuation._rehearsal_seed``): it says what such a cast is *like* and
#: must not say how the real flip will fall. Its sample won; this sweep's
#: cast, on the seed `run` fixes, lost.
_COIN = "a coin flip: the rehearsal's sample won it, the cast lost it"
LOSSES: dict = {
    ("Game of Chaos", None, "empty"): _COIN,
    ("Game of Chaos", None, "own"): _COIN,
    ("Game of Chaos", None, "mirror"): _COIN,
}

#: Casts that name the caster's own permanent with a better twin opposite.
OWN_GOALS: dict = {}

SWEPT = ALWAYS | {key[0] for pins in (IDLE, LOSSES, OWN_GOALS) for key in pins}
assert SWEPT <= set(POOL), sorted(SWEPT - set(POOL))


# -- the tests ------------------------------------------------------------------

@pytest.fixture(scope="module")
def rows() -> list:
    return census(sample=True)


def test_the_sweep_examined_the_pool(rows):
    """The floor: a sweep that reaches nothing passes everything."""
    assert len(rows) >= 540
    assert len({row["card"] for row in rows}) >= 170
    assert ALWAYS <= {row["card"] for row in rows}
    proposed = [row for row in rows if row["proposed"]]
    # ...and that it is a sweep of casts, not of refusals: a third of the
    # boards still draw a proposal, on each of the three layouts.
    assert len(proposed) >= 120
    assert {row["layout"] for row in proposed} == set(LAYOUTS)


def test_no_proposal_crashed_or_was_refused(rows):
    assert findings(rows)["error"] == {}


def test_every_cast_weighed_was_rehearsed(rows):
    """The floor under the three tests below: the policy measured what it
    proposed, here, on these boards. A rehearsal that cannot be run answers
    None and the cast is proposed unmeasured — which is the old policy, and
    would pass none of them, but only for the cards it happened to."""
    assert REHEARSALS["asked"] >= 300, dict(REHEARSALS)
    assert REHEARSALS["not run"] == 0, dict(REHEARSALS)


def test_no_cast_is_proposed_that_moves_nothing(rows):
    found = findings(rows)["idle"]
    assert set(found) == set(IDLE), sorted(set(found) ^ set(IDLE))


def test_no_cast_is_proposed_that_only_costs_its_caster(rows):
    found = findings(rows)["loss"]
    assert set(found) == set(LOSSES), {
        key: found.get(key) for key in sorted(set(found) ^ set(LOSSES))
    }


def test_no_cast_names_its_own_permanent_with_a_better_twin_opposite(rows):
    found = findings(rows)["own goal"]
    assert set(found) == set(OWN_GOALS), {
        key: found.get(key) for key in sorted(set(found) ^ set(OWN_GOALS))
    }


def test_the_named_casts_are_held_or_aimed_across_the_table(rows):
    """The ones this round was briefed with, so each stays readable in the
    sweep: a discard at an empty hand, Donate, Kor Chant with no source, the
    two guards — none proposed where it does nothing — and Swords to
    Plowshares, which goes to the opposing creature when there is one."""
    by_key = {tag(row): row for row in rows}
    for name in ("Mind Rot", "Duress", "Hymn to Tourach", "Ertai's Trickery",
                 "Kor Chant", "Donate"):
        for layout in ("empty", "own"):
            assert not by_key[(name, None, layout)]["proposed"], (name, layout)
    for layout in ("empty", "own"):
        assert not by_key[("Swords to Plowshares", None, layout)]["proposed"]
        assert not by_key[("Wrath of God", None, layout)]["proposed"]
    swords = by_key[("Swords to Plowshares", None, "mirror")]
    assert swords["proposed"] and swords["swing"] > 0 and swords["twin"] is None
    # Winnow's guard holds for nothing on a board with no two permanents
    # alike; what is left of it is "draw a card", which is a cast.
    winnow = by_key[("Winnow", None, "own")]
    assert not winnow["proposed"] or winnow["swing"] >= CARD_WORTH - EPSILON


if __name__ == "__main__":
    rows = census(sample="--sample" in sys.argv)
    found = findings(rows)
    tally = Counter()
    for row in rows:
        tally[(row["layout"], "examined")] += 1
        if row["proposed"]:
            tally[(row["layout"], "proposed")] += 1
    for key in sorted(tally):
        print(key, tally[key])
    print(f"rows: {len(rows)}  cards: {len({row['card'] for row in rows})}")
    print("rehearsals:", dict(REHEARSALS))
    for leg in ("idle", "loss", "own goal", "error"):
        print(f"== {leg}: {len(found[leg])}")
        for key in sorted(found[leg], key=lambda k: (k[0], str(k[1]), k[2])):
            print(f"   {key}: {found[leg][key]}")
