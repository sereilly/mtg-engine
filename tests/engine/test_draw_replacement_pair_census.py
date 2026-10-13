"""Every pair of draw replacements in the pool, on a two- and a three-card draw.

CR 121.2: "If a player is instructed to draw multiple cards, that player
performs that many individual card draws." One at a time — and each draw's
replacements are run to the end (CR 616.1f) before the next draw exists.

The engine carried "the draws behind this one" on the prompt of the
replacement that took the first, which is right until the *answer* suspends
the same draw again: an optional replacement declined remakes its draw through
the seam, a second replacement asks about it, and the resolver went straight on
to the draws queued behind. Abundance and Pursuit of Knowledge on one
battlefield, Ancestral Recall: the second draw's Pursuit offer and the third
draw's CR 616.1e order were owed together, each refused every action but its
own answer (``web.prompts.blocking_prompt``), and no click and no request
could continue the game.

Measured before the seam parked a draw (``Game._draw_prompt_open``), over the
eleven sources × themselves × a one-, two- and three-card draw × every sequence
of answers: **69 of 198 cases** reached two prompts that refused each other
(163 answer paths), 28 more had two prompts of one kind owed out of order, and
21 could not be explored at all because a doubler re-doubled the draws queued
behind a replaced one for ever (CR 614.5; ``test_a_doubler_...`` below). After:
no case locks, and the only two prompts ever owed together are two
Breathstealer's Crypts taxing the *same* drawn card.

This is that census with a fixed set of answer policies instead of every
sequence, which is what makes it cheap enough for the suite; the exhaustive
form is the round's scratch script. Six policies find what every sequence
found: with the seam switched off they lock 70 of the 132 two- and three-card
cases, the exhaustive census's 69 and one more — two Abundances, where the
order of the cards one reveal put on the bottom (CR 401.4, asked since this
round) met the next draw's offer. It is validated backwards in the suite too:
``test_the_census_sees_the_lock_with_the_seam_switched_off``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_paths
from engine.models import Permanent
from engine.replacements import replacement_candidates
from web.prompts import blocking_prompt

#: Floors, because a sweep that reaches nothing passes. Eleven sources, 66
#: pairs and 132 cases on the day; 94 of them park a draw at least once.
_MIN_SOURCES = 10
_MIN_CASES = 120
_MIN_CASES_THAT_PARK = 80

#: Sources that are armed by an activation rather than printed as a static:
#: one-shot "the next time you would draw a card this turn".
_LAMP = "[armed] Aladdin's Lamp"
_RING = "[armed] Ring of Ma'rûf"

#: The one meeting that is not a defect, by the kinds that meet: two
#: Breathstealer's Crypts each tax the one card a draw put into a hand, so both
#: offers are about one draw and are answered oldest first.
_SAME_DRAW_MEETINGS = {("discard_unless_pay_life", "discard_unless_pay_life")}


@pytest.fixture(scope="module")
def pool():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _game(pool, sources) -> Game:
    battlefield = [
        Permanent(card=pool[name]) for name in sources if name in pool
    ]
    library = [pool["Forest"], pool["Forest"], pool["Grizzly Bears"]] * 8
    me = PlayerState(name="P0", battlefield=battlefield, library=library, life=20)
    me.hand = [pool["Swamp"], pool["Swamp"]]
    me.graveyard = [pool["Plains"]] * 3
    game = Game(players=[me, PlayerState(name="P1", library=list(library), life=20)])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    if _LAMP in sources:
        game.lamp_draw_replacements[0] = 2
    if _RING in sources:
        me.sideboard = [pool["Hill Giant"], pool["Air Elemental"]]
        game.outside_game_draw_replacements.add(0)
    return game


def _draw_sources(pool) -> dict[str, tuple[str, ...]]:
    """Every permanent card that makes a ``draw`` replacement applicable, found
    by asking the registry — a list of names would be the second copy."""
    candidates = replacement_candidates("draw")

    def applicable(game) -> set[str]:
        payload = {
            "player": game.players[0], "count": 1, "drawn": 0,
            "turn_based": False, "exclude_sources": (),
        }
        return {c.key for c in candidates if c.applies(game, payload)}

    nothing = applicable(_game(pool, ()))
    found: dict[str, tuple[str, ...]] = {}
    for name, card in pool.items():
        if "draw" not in (card.oracle_text or "").lower():
            continue
        type_line = (card.type_line or "").lower()
        if "instant" in type_line or "sorcery" in type_line:
            continue
        keys = applicable(_game(pool, (name,))) - nothing
        if keys:
            found[name] = tuple(sorted(keys))
    found[_LAMP] = ("armed",)
    found[_RING] = ("armed",)
    return found


def _owed(game) -> list:
    return [
        (spec, choice)
        for spec, choice in game.iter_pending_prompts()
        if spec.holds_priority and spec.open_for(game, choice)
    ]


def _declines(label: str) -> bool:
    """Whether an offered option is "draw the card after all"."""
    return label.strip().lower().startswith("draw")


def _answer(game, spec, choice, step: int, policy) -> None:
    orders, offers = policy
    if choice.kind == "effect_order":
        count = len(choice.data["options"])
        pick = orders[step % len(orders)] % count
        assert game.resolve_pending_choice(
            "effect_order", choice.player_index, option_index=pick
        )
        return
    options = getattr(choice, "options", None)
    if options is None:
        # Not an offer between named options (a discard, a life payment): the
        # kind's own default is one legal answer.
        game.auto_resolve_choice(choice)
        return
    wants_decline = offers[step % len(offers)]
    labels = [str(option) for option in options]
    declining = [i for i, label in enumerate(labels) if _declines(label)]
    accepting = [i for i, label in enumerate(labels) if not _declines(label)]
    pick = (declining or accepting)[0] if wants_decline else (accepting or declining)[0]
    assert spec.resolve(game, choice, {"option": pick})


#: (which effect is applied first each time CR 616.1e asks, whether each offer
#: is declined). Cycled, so a policy mixes answers along one draw sequence.
_POLICIES = (
    ((0,), (True,)),
    ((1,), (True,)),
    ((0,), (False,)),
    ((1,), (False,)),
    ((0, 1), (False, True)),
    ((1, 0), (True, False)),
)


def _drive(pool, sources, count: int, policy) -> dict:
    """Draw *count* cards under *sources* and answer everything by *policy*."""
    game = _game(pool, sources)
    me = game.players[0]
    parks = [0]
    park = game._park_draw

    def counting_park(*args, **kwargs):
        parks[0] += 1
        return park(*args, **kwargs)

    game._park_draw = counting_park
    game._draw_with_replacements(me, count)
    met: set[tuple[str, ...]] = set()
    for step in range(60):
        prompts = _owed(game)
        if not prompts:
            return {"met": met, "locked": None, "parks": parks[0], "left": game.parked_draws}
        if len(prompts) > 1:
            met.add(tuple(sorted(choice.kind for _spec, choice in prompts)))
        free = [
            (spec, choice) for spec, choice in prompts
            if blocking_prompt(game, choice.player_index, spec.action, frozenset()) is None
        ]
        if not free:
            return {
                "met": met, "parks": parks[0], "left": game.parked_draws,
                "locked": tuple(sorted(choice.kind for _spec, choice in prompts)),
            }
        spec, choice = free[0]
        _answer(game, spec, choice, step, policy)
    raise AssertionError(f"{sources} x {count}: the draw never finished")


def _census(pool, counts=(2, 3)) -> dict:
    sources = sorted(_draw_sources(pool))
    cases = 0
    parked_cases = 0
    locks: list[str] = []
    meetings: list[str] = []
    stranded: list[str] = []
    for index, first in enumerate(sources):
        for second in sources[index:]:
            for count in counts:
                cases += 1
                parked = False
                for policy in _POLICIES:
                    result = _drive(pool, (first, second), count, policy)
                    parked = parked or bool(result["parks"])
                    where = f"{first} + {second} x {count} {policy}"
                    if result["locked"]:
                        locks.append(f"{where}: {result['locked']}")
                    for kinds in result["met"] - _SAME_DRAW_MEETINGS:
                        meetings.append(f"{where}: {kinds}")
                    if result["left"]:
                        stranded.append(f"{where}: {result['left']}")
                parked_cases += parked
    return {
        "sources": sources, "cases": cases, "parked_cases": parked_cases,
        "locks": locks, "meetings": meetings, "stranded": stranded,
    }


def test_no_pair_of_draw_replacements_leaves_two_prompts_that_refuse_each_other(pool):
    census = _census(pool)

    assert len(census["sources"]) >= _MIN_SOURCES, census["sources"]
    assert census["cases"] >= _MIN_CASES, census["cases"]
    # The seam's parking is what the census is about: a run in which no draw
    # was ever parked asked nothing of it.
    assert census["parked_cases"] >= _MIN_CASES_THAT_PARK, census["parked_cases"]

    assert not census["locks"], census["locks"][:10]
    # Two prompts owed together are two draws under way at once — except the
    # one meeting that is two effects on a single draw.
    assert not census["meetings"], census["meetings"][:10]
    # Every draw that was parked was made: nothing is left behind a prompt
    # that has been answered.
    assert not census["stranded"], census["stranded"][:10]


def test_the_census_sees_the_lock_with_the_seam_switched_off(pool, monkeypatch):
    """Backwards: a seam that never parks a draw is the tree before the fix,
    and on it the census names the pair Phase 5 locked a game with."""
    monkeypatch.setattr(Game, "_draw_prompt_open", lambda self, seat: False)

    locked = [
        policy for policy in _POLICIES
        if _drive(pool, ("Abundance", "Pursuit of Knowledge"), 3, policy)["locked"]
    ]

    assert locked, "the census cannot see the defect it is there for"


@pytest.mark.parametrize(
    "beside",
    ["Abundance", "Enduring Renewal", "Forbidden Crypt", "Breathstealer's Crypt",
     "Chains of Mephistopheles"],
)
def test_a_doubler_does_not_double_the_draws_it_made(pool, beside):
    """CR 614.5: a replacement "gets only one opportunity to affect an event or
    any modified events that may replace that event."

    "…draw two cards instead" makes two draws of one, and those two are that
    event modified. A replacement that took the first of them handed the other
    back to the seam as a fresh event, where the doubler doubled it again: one
    card drawn beside an Abundance revealed the library to the bottom and
    raised ``RecursionError``; beside a Forbidden Crypt it returned the whole
    graveyard. Headless and AI seats, which take every default.
    """
    game = _game(pool, ("Teferi's Ageless Insight", beside))
    game.interactive_seats = set()
    me = game.players[0]
    me.graveyard = [pool["Plains"]] * 8
    me.hand = [pool["Swamp"]] * 3
    cards = lambda: len(me.library) + len(me.hand) + len(me.graveyard)  # noqa: E731
    library, total = len(me.library), cards()

    game._draw_with_replacements(me, 1)
    game.auto_resolve_pending_choices()

    # One draw doubled is two draws, each replaced or made once: at most two
    # cards have left the top of the library, whatever the replacement does
    # with them.
    assert library - len(me.library) <= 2, game.log[-8:]
    assert cards() == total, "no card left the game"
    assert not game.pending_choices and not game.pending_replacement_choices
    assert not game.parked_draws
