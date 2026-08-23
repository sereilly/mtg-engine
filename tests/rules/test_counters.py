"""Comprehensive Rules Section 122 — Counters.

What a counter *is*, as distinct from where the engine keeps one. The engine
has three counter channels — the +1/+1 seam (``Game.place_plus1_counters``),
the inert named-counter store (``engine/named_counters.py``) and loyalty
(``metadata["loyalty_counters"]``) — and CR 122 is the rule they all have to
answer to: a counter is a marker on an object, it modifies that object's
characteristics only when its kind says so, and it does not survive the object
changing zones.

The state-based actions CR 122.3 and 122.4 *point at* are exercised from the
704 side in ``test_state_based_actions.py``; here they are cited from the 122
side, which is where the rule that governs them is written.
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.named_counters import add_counters, counters_on


def _mk_creature(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _duel(*permanents: Permanent) -> tuple[Game, PlayerState, PlayerState]:
    p1 = PlayerState(name="P1", battlefield=list(permanents))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


# ---------------------------------------------------------------------------
# 122.1 — a counter is a marker that modifies characteristics
# ---------------------------------------------------------------------------

@pytest.mark.cr("122.1", "122.1a")
def test_122_1a_a_plus_one_counter_adds_to_power_and_toughness():
    """A +1/+1 counter adds 1 to power and 1 to toughness (CR 122.1a).

    Placed through the seam rather than by writing the metadata key: the record
    and the P/T channel are two different things, and only the seam moves both.
    """
    perm = Permanent(card=_mk_creature("Counter Bear", 2, 2))
    game, p1, _ = _duel(perm)

    game.place_plus1_counters(perm, 3)

    assert perm.metadata["plus_counters"] == 3
    assert (perm.effective_power, perm.effective_toughness) == (5, 5)


@pytest.mark.cr("122.1a", "613.4c")
def test_122_1a_reads_the_deltas_off_the_counter_s_name():
    """"Similarly, -X/-Y counters subtract from power and toughness."

    The rule names the counter by the numbers it carries, so which P/T counters
    exist is derivable rather than a list of the ones printed so far. The list
    it replaced held four kinds and refused "-0/-2" (Spirit Shackle) and
    "-0/-1" (Takklemaggot) as unsupported counter kinds while admitting "-1/-1"
    beside them.
    """
    from engine.pt import pt_counter_deltas

    assert pt_counter_deltas("+1/+1") == (1, 1)
    assert pt_counter_deltas("-0/-2") == (0, -2)
    assert pt_counter_deltas("+3/+0") == (3, 0)
    assert pt_counter_deltas("page") is None, "an invented counter carries no P/T"
    assert pt_counter_deltas("loyalty") is None


@pytest.mark.cr("122.1a")
def test_122_1a_a_minus_counter_subtracts_and_is_recorded_as_itself():
    """A -0/-2 counter takes two toughness and leaves power alone, and is
    recorded under its own name: CR 122.1 makes counters interchangeable with
    counters *of the same name*, so it must not join the -1/-1 pile CR 704.5q
    cancels against +1/+1 counters."""
    perm = Permanent(card=_mk_creature("Shackled", 3, 3))
    game, _, _ = _duel(perm)

    game.place_pt_counters(perm, "-0/-2", 1)

    assert (perm.effective_power, perm.effective_toughness) == (3, 1)
    assert perm.metadata["-0/-2_counters"] == 1
    assert perm.metadata.get("minus_counters", 0) == 0


@pytest.mark.cr("122.1")
def test_122_1_a_counter_of_another_kind_modifies_nothing_on_its_own():
    """A counter modifies characteristics only where a rule or ability says so.

    A page counter is a marker the card's own text reads; CR 122.1 gives it no
    characteristic-changing power by itself, so P/T must be untouched.
    """
    perm = Permanent(card=_mk_creature("Inert Marker", 2, 2))
    _duel(perm)

    add_counters(perm, "page", 4)

    assert counters_on(perm, "page") == 4
    assert (perm.effective_power, perm.effective_toughness) == (2, 2)


@pytest.mark.cr("122.1")
def test_122_1_counters_of_different_kinds_are_counted_separately():
    """"A counter is a marker" — kinds are independent tallies, so adding one
    kind never reads as another. The +1/+1 record and a named kind share a
    permanent without either seeing the other's count."""
    perm = Permanent(card=_mk_creature("Two Kinds", 1, 1))
    game, _, _ = _duel(perm)

    game.place_plus1_counters(perm, 2)
    add_counters(perm, "soul", 5)

    assert perm.metadata["plus_counters"] == 2
    assert counters_on(perm, "soul") == 5
    assert counters_on(perm, "page") == 0
    assert (perm.effective_power, perm.effective_toughness) == (3, 3)


# ---------------------------------------------------------------------------
# 122.2 — counters do not survive a zone change (CR 400.7)
# ---------------------------------------------------------------------------

@pytest.mark.cr("122.2", "400.7")
def test_122_2_counters_cease_to_exist_when_the_permanent_changes_zones():
    """Counters are not retained across a zone change — they cease to exist.

    The engine gets this from CR 400.7 rather than by clearing anything: a
    permanent that leaves and returns is a *new object*, so there is nothing
    for the old counters to be on.
    """
    card = _mk_creature("Returning Bear", 2, 2)
    perm = Permanent(card=card)
    game, p1, _ = _duel(perm)
    game.place_plus1_counters(perm, 2)
    assert (perm.effective_power, perm.effective_toughness) == (4, 4)

    game._permanent_to_graveyard(p1, perm)
    game.remove_from_battlefield(perm)
    assert card in p1.graveyard

    returned = game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
    returned = returned if isinstance(returned, Permanent) else p1.battlefield[-1]

    assert returned.metadata.get("plus_counters", 0) == 0
    assert (returned.effective_power, returned.effective_toughness) == (2, 2)


# ---------------------------------------------------------------------------
# 122.3 / 122.4 — the two state-based actions CR 122 defines
# ---------------------------------------------------------------------------

@pytest.mark.cr("122.3")
def test_122_3_plus_and_minus_counters_annihilate_in_pairs():
    """N +1/+1 and N -1/-1 counters are removed, N being the smaller count.

    Cited from the 122 side; ``test_state_based_actions.py`` cites the same
    behaviour as 704.5q, which is the state-based action this rule points at.
    """
    perm = Permanent(
        card=_mk_creature("Annihilating Bear", 2, 2),
        metadata={"plus_counters": 4, "minus_counters": 3},
    )
    _game, p1, _ = _duel(perm)

    current = p1.battlefield[0]
    assert current.metadata["plus_counters"] == 1
    assert current.metadata["minus_counters"] == 0


@pytest.mark.cr("122.3")
def test_122_3_equal_counts_leave_neither_kind():
    """With equal counts, N is that count and both kinds are gone entirely."""
    perm = Permanent(
        card=_mk_creature("Balanced Bear", 2, 2),
        metadata={"plus_counters": 2, "minus_counters": 2},
    )
    _game, p1, _ = _duel(perm)

    current = p1.battlefield[0]
    assert current.metadata.get("plus_counters", 0) == 0
    assert current.metadata.get("minus_counters", 0) == 0


@pytest.mark.cr("122.6")
def test_122_6_counters_given_as_it_enters_count_as_put_on():
    """"Counters put on an object" covers counters given as it enters (CR 122.6).

    A permanent that enters carrying counters is in the same state as one that
    was given them afterward — the record and the P/T channel agree either way.
    """
    entering = Permanent(card=_mk_creature("Entering Bear", 1, 1))
    game, p1, _ = _duel()
    game.place_plus1_counters(entering, 2)
    p1.battlefield.append(entering)
    game._sync_control()

    on_battlefield = p1.battlefield[0]
    assert on_battlefield.metadata["plus_counters"] == 2
    assert (on_battlefield.effective_power, on_battlefield.effective_toughness) == (3, 3)
