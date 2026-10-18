"""Census: a permanent named to pay a spell's additional cost pays it, or the
cast is refused (CR 601.2h).

"As an additional cost to cast this spell, sacrifice a creature." *Which*
creature is the caster's, and a caster who names one has announced that
payment. The cast path honoured the name "where it is legal" and otherwise fell
to ``default_sacrifice_pick`` — right for a seat that named nothing, and wrong
for one that did: Diabolic Intent told to sacrifice a Forest sacrificed a
creature, and Gaea's Balance told to sacrifice four lands sacrificed five. The
activation path had the same shape until ``_named_cost_refusal``; this is its
cast-side twin, ``_named_cast_cost_refusal``.

The census asks the question of **every** spell in both manifest roles whose
additional cost names a chosen permanent — mandatory ones, and the kicker and
buyback ones with their offer taken — rather than of the card that surfaced it,
and it is its own backwards validation: the numbers it reported on the tree
before the gate are in the test's docstring below.

Each probe is one cast, judged by what left the battlefield — never by the
result string alone, because the defect was a cast that reported success.
"""

from __future__ import annotations

import copy
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import additional_costs
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import spec_is_a_cost
from tests.helpers import _nosick

#: What the caster holds. Wide on purpose and no wider: every printed cost
#: phrase in the pool ("a creature", "a green creature", "a Goblin", "a blue
#: permanent", "an artifact", "a land", "X Swamps", "five lands") finds one
#: more payer than it takes — so a list that is too long can be named — and a
#: near miss that cannot pay it.
_BOARD = (
    "Forest", "Forest", "Island", "Swamp", "Swamp", "Swamp", "Mountain", "Plains",
    "Grizzly Bears", "Hill Giant", "Llanowar Elves",
    "Mons's Goblin Raiders", "Mons's Goblin Raiders",
    "Merfolk of the Pearl Trident", "Merfolk of the Pearl Trident",
    "Sol Ring", "Clockwork Beast", "Crusade",
)

#: What the far seat holds: one permanent that answers each of those phrases
#: — so that only its *seat* says it cannot pay — and two of whatever a kicked
#: spell needs as its second target.
_FAR_BOARD = (
    "Forest", "Swamp", "Grizzly Bears", "Mons's Goblin Raiders",
    "Merfolk of the Pearl Trident", "Sol Ring",
)

#: The verbs a chosen-permanent additional cost prints, with the field each
#: reads — ``_COST_CANDIDATE_FIELDS``' additional-cost rows, in the order the
#: payment collects them.
_VERBS = (
    ("exile", "exile_filter"),
    ("sacrifice", "sacrifice_filter"),
    ("return", "return_filter"),
)


def _pool() -> list:
    """Every unit of text that compiles, in both manifest roles: a measured
    set is exactly the population this gate must already be right about when
    it ships, and a split card's halves are where its costs are printed."""
    return list(compilation_units(load_cards(manifest_set_paths(include_measured=True))))


@pytest.fixture(scope="module")
def pool():
    return _pool()


@pytest.fixture(scope="module")
def by_name(pool):
    names: dict = {}
    for card in pool:
        names.setdefault(card.name, card)
    return names


def _chosen_costs(pool) -> list[tuple]:
    """``(card, cost, verb)`` for every supported spell whose additional cost
    hands its payer a choice of permanent."""
    found = []
    for card in pool:
        if not compile_card_oracle(card).supported:
            continue
        for cost in additional_costs(card):
            for verb, field in _VERBS:
                if getattr(cost, field) is not None:
                    found.append((card, cost, verb))
    return found


def _wanted(cost, verb) -> int:
    """How many permanents the cost takes. An X cost is announced as 2."""
    if verb == "sacrifice":
        return max(1, cost.sacrifice_count)
    if verb == "return":
        return 2 if cost.return_count_x else max(1, cost.return_count)
    return 1


def _board(by_name) -> Game:
    """A two-seat board at the caster's precombat main phase.

    The far side matters for one probe: an opposing creature answers "a
    creature" as well as the caster's own does, and only the seat says it
    cannot pay.
    """
    def side(names) -> list:
        return [_nosick(Permanent(card=by_name[name])) for name in names]

    yard = [by_name[name] for name in ("Grizzly Bears", "Sol Ring", "Forest")]
    game = Game(players=[
        PlayerState(name="P1", battlefield=side(_BOARD), life=20,
                    graveyard=list(yard), library=[by_name["Forest"]] * 12),
        PlayerState(name="P2", battlefield=side(_FAR_BOARD), life=20,
                    graveyard=list(yard), library=[by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game


def _taken(cost) -> dict:
    """CR 601.2b's announcement for an optional price: taken once."""
    return {cost.optional_key: 1} if cost.optional_key else {}


def _aim(game, by_name, card, cost, verb, *, declined: bool = False) -> dict:
    """Keywords for a legal announcement of everything about *card* **except**
    which permanents pay: the offer taken, the X, and targets read off the
    card's own picker.

    A target is never a permanent that could pay the cost, so no probe's
    payment can be confused with what the spell was aimed at.
    """
    keywords: dict = {}
    # *declined* is the same spell with its offer not taken — a different
    # announcement, because a kicked spell may print a second target.
    taken = {} if declined else _taken(cost)
    if taken:
        keywords["optional_cost_payments"] = taken
    if cost.return_count_x:
        keywords["x_value"] = 2

    def spec() -> dict:
        return game.cast_target_spec(0, card, optional_cost_payments=taken or None)

    found = spec()
    if spec_is_a_cost(found):
        return keywords
    if found.get("kind") == "stack":
        # "Counter target spell" (Abjure): the far seat casts something to aim
        # at, at its own creature so nothing of the caster's is involved.
        game.players[1].hand.append(by_name["Giant Growth"])
        bears = next(p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears")
        game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
        found = spec()
    payers = game._additional_cost_candidates(0, cost, giving_up=verb)
    entries = found.get("valid_targets") or []

    def far_permanents() -> list:
        return [
            permanent for permanent in (
                game.permanent_at(entry["seat"], entry["index"])
                for entry in entries
                if entry.get("kind") == "permanent" and entry["seat"] == 1
            )
            if permanent is not None
        ]

    if found.get("kind") == "divided":
        # One entry, or as many as a kicked "…to another target" prints.
        count = int(found.get("divided_target_count") or 1)
        keywords["divided_targets"] = [
            (1, game.battlefield_index_of(permanent))
            for permanent in far_permanents()[:count]
        ]
        return keywords
    if found.get("kind") == "roles":
        # One permanent per printed role ("target land … another target land").
        keywords["target_permanent_ids"] = [
            permanent.permanent_id
            for permanent in far_permanents()[:len(found.get("roles") or ())]
        ]
        return keywords
    # A player first, then the far side's permanents, then the caster's own.
    for entry in sorted(entries, key=lambda e: (e.get("kind") != "player", e.get("seat") != 1)):
        kind = entry.get("kind")
        if kind == "player":
            keywords["target_player_index"] = entry["seat"]
            return keywords
        if kind == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            if permanent is None or any(permanent is payer for payer in payers):
                continue
            keywords["target_permanent_ids"] = [permanent.permanent_id]
            return keywords
        if kind == "graveyard":
            keywords["target_player_index"] = entry["seat"]
            keywords["target_permanent_index"] = entry["index"]
            return keywords
        if kind == "stack" and isinstance(entry.get("stack_index"), int):
            # The picker counts from the top; the engine's argument from the bottom.
            keywords["target_stack_index"] = len(game.stack) - 1 - entry["stack_index"]
            return keywords
    return keywords


class _Table:
    """One card's board, rebuilt only when a probe changed it.

    A refused cast costs its caster nothing (CR 601.2e: the game returns to the
    moment before the cast was proposed), so every probe that is refused leaves
    the board exactly as the next one needs it. That is a claim about the
    engine, and :meth:`cast` checks it rather than assuming it: a probe that
    cast, or that moved a permanent or the card, retires the board.
    """

    def __init__(self, by_name, pristine, card, cost, verb, *, declined: bool = False) -> None:
        self.by_name, self.card, self.cost, self.verb = by_name, card, cost, verb
        self.pristine = pristine
        self.declined = declined
        self.game = None
        self.aim: dict = {}
        self.boards = 0

    def board(self) -> tuple:
        """The current board and the cost's candidates on it.

        A fresh one is a copy of *pristine* — the engine's own snapshot
        operation (``game_history`` takes one per undo step) — with the card
        put into the caster's hand, so 43 spells and their probes share one
        opening turn instead of replaying it a hundred times.
        """
        if self.game is None:
            self.game = copy.deepcopy(self.pristine)
            self.game.players[0].hand.append(self.card)
            self.aim = _aim(
                self.game, self.by_name, self.card, self.cost, self.verb,
                declined=self.declined,
            )
            self.boards += 1
        return self.game, self.game._additional_cost_candidates(
            0, self.cost, giving_up=self.verb
        )

    def cast(self, naming) -> tuple:
        """One probe. *naming* is given the game and the cost's candidates and
        returns ``(cost keywords, the permanents it named)``; the answer is
        ``(result, named, left)``, *left* being every permanent of the
        caster's that is no longer on the battlefield."""
        game, candidates = self.board()
        cost_keywords, named = naming(game, candidates)
        mine = list(game.controlled_by(0))
        stacked = len(game.stack)
        result = game.queue_from_hand(0, self.card.name, **{**self.aim, **cost_keywords})
        left = [perm for perm in mine if not game.is_on_battlefield(perm)]
        if (
            result.supported or left or len(game.stack) != stacked
            or self.card not in game.players[0].hand
        ):
            self.game = None
        return result, named, left


def _judge(result, named, left, *, legal: bool) -> str:
    """What a probe showed, as one phrase.

    * ``refused`` — not cast, and nothing left the battlefield.
    * ``as named`` — cast, and exactly the named permanents paid.
    * ``substituted`` — cast, and something the caster did not name paid.
    * anything else is spelled out, and is a finding.
    """
    named_ids = {id(perm) for perm in named if perm is not None}
    left_ids = {id(perm) for perm in left}
    if not result.supported:
        return "refused" if not left else f"refused but paid {[p.card.name for p in left]}"
    if left_ids == named_ids and legal:
        return "as named"
    if left_ids - named_ids:
        return "substituted"
    return f"cast; named {len(named_ids)}, paid {len(left_ids)}"


def _least_preferred(game, candidates, count) -> list:
    """The *count* candidates the engine's own default would give up **last**
    — so a cast that ignored its names and took the default is seen."""
    return sorted(candidates, key=game.sacrifice_preference_key, reverse=True)[:count]


def _ids(permanents) -> dict:
    return {"cost_permanent_ids": [perm.permanent_id for perm in permanents]}


def run_census(pool, by_name) -> dict:
    """Every probe of every chosen-permanent additional cost.

    Returns ``{"examined": Counter, "wrong": [str], "unprobed": [str],
    "boards": int}``. *examined* counts probes by kind so the test below can
    hold a floor on each — a census that examined nothing reports nothing
    wrong.
    """
    examined: Counter = Counter()
    wrong: list[str] = []
    unprobed: list[str] = []
    boards = 0
    pristine = _board(by_name)
    for card, cost, verb in _chosen_costs(pool):
        wanted = _wanted(cost, verb)
        label = f"{card.name} ({verb} {wanted}{', optional' if cost.optional_key else ''})"
        table = _Table(by_name, pristine, card, cost, verb)

        # The convention every other probe is measured against: a cast that
        # names no payer is cast, and pays the cost's count by default.
        result, _named, left = table.cast(lambda g, c: ({}, []))
        if not result.supported or len(left) != wanted:
            unprobed.append(f"{label}: bare cast -> {result.details[:80]!r}, paid {len(left)}")
            boards += table.boards
            continue
        examined["bare cast pays by default"] += 1
        examined["optional" if cost.optional_key else "mandatory"] += 1

        def probe(kind: str, naming, *, legal: bool = False, table=table, label=label) -> None:
            result, named, left = table.cast(naming)
            verdict = _judge(result, named, left, legal=legal)
            examined[kind] += 1
            if verdict != ("as named" if legal else "refused"):
                wrong.append(f"{label}: {kind} -> {verdict}")

        # A permanent of the caster's own that the printed phrase does not
        # name — one probe per printed type on the board, so a near miss (a
        # red creature for "a green creature", a Forest for "X Swamps") is
        # asked as well as a far one. A counted cost is otherwise named in
        # full, so the outsider is the only thing wrong with the list.
        _game, candidates = table.board()
        outsiders = sorted({
            perm.card.type_line.split(" ")[0]: perm.card.name
            for perm in _game.controlled_by(0)
            if not any(perm is option for option in candidates)
        }.values())
        for name in outsiders:
            def an_outsider(g, c, name=name, wanted=wanted):
                perm = next(
                    p for p in g.controlled_by(0)
                    if p.card.name == name and not any(p is option for option in c)
                )
                payers = [perm] + _least_preferred(g, c, wanted - 1)
                return _ids(payers), payers
            probe("names a permanent that cannot pay", an_outsider)

        # The other seat's permanent that answers the phrase: only the seat
        # says it cannot pay ("a creature **you control**").
        def the_opponents(g, c, cost=cost, verb=verb, wanted=wanted):
            theirs = g._additional_cost_candidates(1, cost, giving_up=verb)
            payers = [theirs[0]] + _least_preferred(g, c, wanted - 1)
            return _ids(payers), payers
        probe("names an opponent's permanent", the_opponents)

        def a_stale_id(g, c):
            return {"cost_permanent_ids": [10 ** 9]}, [None]
        probe("names an id that is not on the battlefield", a_stale_id)

        # The single-slot channel every caller written before the id list
        # existed still sends, pointed at a permanent that cannot pay.
        def an_outsider_by_slot(g, c):
            perm = next(p for p in g.controlled_by(0) if not any(p is option for option in c))
            return {"cost_permanent_index": g.battlefield_index_of(perm)}, [perm]
        probe("names a slot that cannot pay", an_outsider_by_slot)

        if wanted > 1:
            # CR 601.2h: "Partial payments are not allowed."
            def a_short_list(g, c, wanted=wanted):
                payers = _least_preferred(g, c, wanted - 1)
                return _ids(payers), payers
            probe("names fewer than the cost takes", a_short_list)

            def one_twice(g, c, wanted=wanted):
                payers = _least_preferred(g, c, 1) * wanted
                return _ids(payers), payers
            probe("names one permanent twice", one_twice)

        def a_long_list(g, c, wanted=wanted):
            payers = _least_preferred(g, c, wanted + 1)
            return _ids(payers), payers
        probe("names more than the cost takes", a_long_list)

        # And the half that must keep working: the payers the caster names are
        # the payers — the ones the default would have kept.
        def as_named(g, c, wanted=wanted):
            payers = _least_preferred(g, c, wanted)
            return _ids(payers), payers
        probe("names legal payers by id", as_named, legal=True)

        if wanted == 1:
            def as_named_by_slot(g, c):
                payers = _least_preferred(g, c, 1)
                return {"cost_permanent_index": g.battlefield_index_of(payers[0])}, payers
            probe("names a legal payer by slot", as_named_by_slot, legal=True)

        if cost.optional_key:
            # A declined offer charges nothing, so a stray name pays nothing
            # and substitutes nothing: the cast goes ahead with the board whole.
            def a_stray_name(g, c):
                return _ids(_least_preferred(g, c, 1)), []
            unpaid = _Table(by_name, pristine, card, cost, verb, declined=True)
            result, _named, left = unpaid.cast(a_stray_name)
            boards += unpaid.boards
            examined["declines the offer and names a payer anyway"] += 1
            if not result.supported or left:
                wrong.append(
                    f"{label}: declined offer with a stray name -> "
                    f"{result.details[:60]!r}, paid {[p.card.name for p in left]}"
                )
        boards += table.boards
    return {"examined": examined, "wrong": wrong, "unprobed": unprobed, "boards": boards}


def test_a_named_cast_cost_payer_pays_or_the_cast_is_refused(pool, by_name):
    """CR 601.2h over the whole pool: a named payer that cannot pay refuses the
    cast with nothing spent, and a named payer that can is the one that pays.

    **What this reported on the tree before the gate**, which is its backwards
    validation: all 43 spells (32 mandatory, 11 kicker or buyback) paid with a
    permanent the caster had not named — for an outsider of their own, for the
    other seat's creature, for an id that names nothing and for a list one too
    long alike; all 5 counted costs topped a short list up from the default;
    Soul Exchange's exile ignored a *legal* creature named by id, and Arctic
    Merfolk's return ignored one named by slot.

    The floors are what stop it passing on nothing: a sweep that reached no
    spell, or stopped asking one of the questions, would be green on any
    engine.
    """
    census = run_census(pool, by_name)
    examined = census["examined"]

    assert census["unprobed"] == [], census["unprobed"]
    assert census["wrong"] == [], "\n".join(census["wrong"])
    assert examined["mandatory"] >= 32, examined
    assert examined["optional"] >= 11, examined
    assert examined["bare cast pays by default"] >= 43, examined
    assert examined["names a permanent that cannot pay"] >= 120, examined
    assert examined["names an opponent's permanent"] >= 43, examined
    assert examined["names an id that is not on the battlefield"] >= 43, examined
    assert examined["names a slot that cannot pay"] >= 43, examined
    assert examined["names more than the cost takes"] >= 43, examined
    assert examined["names fewer than the cost takes"] >= 5, examined
    assert examined["names one permanent twice"] >= 5, examined
    assert examined["names legal payers by id"] >= 43, examined
    assert examined["names a legal payer by slot"] >= 38, examined
    assert examined["declines the offer and names a payer anyway"] >= 11, examined
