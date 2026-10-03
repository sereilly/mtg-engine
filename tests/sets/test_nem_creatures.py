"""Nemesis creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: fading ---
# Fading (CR 702.32) is a rewrite in `engine/fading.py`: "Fading N" becomes
# "This permanent enters with N fade counters on it." and "At the beginning of
# your upkeep, remove a fade counter from this permanent. If you can't,
# sacrifice the permanent." The keyword's own rules tests are in
# tests/rules/test_fading.py; these drive each Nemesis card's *other* lines on
# top of it, through the real entry seam, the real activation path and the real
# upkeep.
import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine.models import Permanent as _W1G1Permanent
from engine.models import PlayerState as _W1G1PlayerState
from engine.named_counters import counters_on as _w1g1_counters_on

from tests.helpers import _damage_dealt as _w1g1_damage_dealt
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_duel() -> "_W1G1Game":
    game = _W1G1Game(players=[
        _W1G1PlayerState(name="P1", life=20), _W1G1PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    return game


def _w1g1_enter(game, seat: int, card) -> "_W1G1Permanent":
    """*card* onto *seat*'s battlefield through the entry seam, which is what
    places the fade counters."""
    perm = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def _w1g1_upkeeps(game, perm, seats) -> list:
    """Fade counters on *perm* after each of *seats*' upkeeps, or "gone"."""
    seen = []
    for seat in seats:
        game.turn += 1
        game.begin_turn_bookkeeping(seat)
        game.resolve_upkeep(seat)
        _w1g1_resolve_stack(game)
        here = any(p is perm for p in game.all_permanents())
        seen.append(_w1g1_counters_on(perm, "fade") if here else "gone")
    return seen


@_w1g1_pytest.mark.parametrize("name, fading", [
    ("Blastoderm", 3), ("Cloudskate", 3), ("Skyshroud Ridgeback", 2),
    ("Defender en-Vec", 4), ("Jolting Merfolk", 4), ("Phyrexian Prowler", 3),
    ("Ancient Hydra", 5), ("Woodripper", 3), ("Skyshroud Behemoth", 2),
])
def test_w1g1_a_fading_creature_fades_on_its_controllers_upkeeps_and_then_dies(
    set_pool, name, fading
):
    """Each creature enters with its printed N, loses one at each of its
    controller's upkeeps (the opponent's do nothing), and is sacrificed at the
    *(N+1)*th — the upkeep that finds none."""
    game = _w1g1_duel()
    perm = _w1g1_enter(game, 0, set_pool("NEM")[name])
    assert _w1g1_counters_on(perm, "fade") == fading

    seen = _w1g1_upkeeps(game, perm, (1, 0) * (fading + 1))

    expected = []
    for left in range(fading - 1, -1, -1):
        expected += [left + 1, left]
    expected += [0, "gone"]
    assert seen == expected
    assert [card.name for card in game.players[0].graveyard] == [name]
    assert f"{name} was sacrificed" in game.log


def test_w1g1_blastoderm_has_shroud_against_an_ability_that_would_tap_it(set_pool):
    """"Shroud" beside the fading line: Jolting Merfolk's "tap target creature"
    has no legal target in it, so the activation is refused and nothing is
    spent — the Merfolk keeps its fade counter."""
    nem = set_pool("NEM")
    game = _w1g1_duel()
    merfolk = _w1g1_enter(game, 1, nem["Jolting Merfolk"])
    beast = _w1g1_enter(game, 0, nem["Blastoderm"])

    result = game.activate_permanent_ability(
        1, "Jolting Merfolk", target_permanent_ids=[beast.permanent_id],
    )
    _w1g1_resolve_stack(game)

    assert beast.has_keyword("shroud")
    assert not result.supported
    assert beast.tapped is False
    assert _w1g1_counters_on(merfolk, "fade") == 4


def test_w1g1_cloudskate_flies(set_pool):
    game = _w1g1_duel()
    skate = _w1g1_enter(game, 0, set_pool("NEM")["Cloudskate"])

    assert skate.has_keyword("flying")
    assert _w1g1_counters_on(skate, "fade") == 3


def test_w1g1_jolting_merfolk_spends_a_counter_per_tap_and_stops_at_none(set_pool):
    """"Remove a fade counter from this creature: Tap target creature." The
    cost is charged — four taps, four counters — and a fifth is refused with
    nothing spent and nothing tapped."""
    nem = set_pool("NEM")
    game = _w1g1_duel()
    merfolk = _w1g1_enter(game, 0, nem["Jolting Merfolk"])
    victim = _w1g1_enter(game, 1, nem["Skyshroud Ridgeback"])

    for left in (3, 2, 1, 0):
        victim.tapped = False
        assert game.activate_permanent_ability(
            0, "Jolting Merfolk", target_permanent_ids=[victim.permanent_id],
        ).supported
        _w1g1_resolve_stack(game)
        assert victim.tapped is True
        assert _w1g1_counters_on(merfolk, "fade") == left

    victim.tapped = False
    refused = game.activate_permanent_ability(
        0, "Jolting Merfolk", target_permanent_ids=[victim.permanent_id],
    )
    _w1g1_resolve_stack(game)
    assert not refused.supported
    assert victim.tapped is False


def test_w1g1_jolting_merfolk_that_spent_its_counters_dies_at_its_next_upkeep(set_pool):
    """The upkeep removes *a* fade counter, so one spent on the ability is one
    it does not find: a Merfolk that tapped four creatures is sacrificed at its
    controller's very next upkeep instead of the fifth."""
    nem = set_pool("NEM")
    game = _w1g1_duel()
    merfolk = _w1g1_enter(game, 0, nem["Jolting Merfolk"])
    victim = _w1g1_enter(game, 1, nem["Skyshroud Ridgeback"])
    for _ in range(4):
        victim.tapped = False
        game.activate_permanent_ability(
            0, "Jolting Merfolk", target_permanent_ids=[victim.permanent_id],
        )
        _w1g1_resolve_stack(game)

    assert _w1g1_upkeeps(game, merfolk, (1, 0)) == [0, "gone"]


def test_w1g1_phyrexian_prowler_pumps_itself_one_counter_at_a_time(set_pool):
    """"Remove a fade counter from this creature: This creature gets +1/+1
    until end of turn." Three counters, three pumps, a 6/6 — and no fourth."""
    game = _w1g1_duel()
    prowler = _w1g1_enter(game, 0, set_pool("NEM")["Phyrexian Prowler"])

    for _ in range(3):
        assert game.activate_permanent_ability(0, "Phyrexian Prowler").supported
        _w1g1_resolve_stack(game)

    assert (prowler.effective_power, prowler.effective_toughness) == (6, 6)
    assert _w1g1_counters_on(prowler, "fade") == 0
    assert not game.activate_permanent_ability(0, "Phyrexian Prowler").supported


def test_w1g1_ancient_hydra_pays_mana_and_a_counter_for_each_ping(set_pool):
    """"{1}, Remove a fade counter from this creature: It deals 1 damage to any
    target." Both halves of the cost are charged: with no mana the ability is
    refused and the counter stays; with {1} floating it pings and the counter
    goes."""
    game = _w1g1_duel()
    game.enforce_mana_costs = True
    hydra = _w1g1_enter(game, 0, set_pool("NEM")["Ancient Hydra"])
    p1, p2 = game.players

    broke = game.activate_permanent_ability(0, "Ancient Hydra", target_player_index=1)
    _w1g1_resolve_stack(game)
    assert not broke.supported
    assert (p2.life, _w1g1_counters_on(hydra, "fade")) == (20, 5)

    p1.mana_pool["C"] = 1
    paid = game.activate_permanent_ability(0, "Ancient Hydra", target_player_index=1)
    _w1g1_resolve_stack(game)
    assert paid.supported
    assert (p2.life, _w1g1_counters_on(hydra, "fade")) == (19, 4)
    assert p1.mana_pool["C"] == 0


def test_w1g1_woodripper_destroys_an_artifact_per_counter(set_pool):
    """"{1}, Remove a fade counter from this creature: Destroy target
    artifact." Three counters, three artifacts (Rejuvenation Chamber), and a
    fourth activation refused."""
    nem = set_pool("NEM")
    game = _w1g1_duel()
    ripper = _w1g1_enter(game, 0, nem["Woodripper"])
    chambers = [_w1g1_enter(game, 1, nem["Rejuvenation Chamber"]) for _ in range(4)]

    for chamber in chambers[:3]:
        assert game.activate_permanent_ability(
            0, "Woodripper", target_permanent_ids=[chamber.permanent_id],
        ).supported
        _w1g1_resolve_stack(game)

    assert [game.is_on_battlefield(c) for c in chambers] == [False, False, False, True]
    assert _w1g1_counters_on(ripper, "fade") == 0
    assert not game.activate_permanent_ability(
        0, "Woodripper", target_permanent_ids=[chambers[3].permanent_id],
    ).supported
    assert game.is_on_battlefield(chambers[3])


def test_w1g1_defender_en_vec_shields_a_creature_and_a_player(set_pool):
    """"Remove a fade counter from this creature: Prevent the next 2 damage
    that would be dealt to any target this turn." Any target is both halves: a
    creature and a player each have the next 2 of 3 prevented."""
    nem = set_pool("NEM")
    game = _w1g1_duel()
    defender = _w1g1_enter(game, 0, nem["Defender en-Vec"])
    ridgeback = _w1g1_enter(game, 0, nem["Skyshroud Ridgeback"])
    p1 = game.players[0]

    assert game.activate_permanent_ability(
        0, "Defender en-Vec", target_permanent_ids=[ridgeback.permanent_id],
    ).supported
    _w1g1_resolve_stack(game)
    assert game.activate_permanent_ability(
        0, "Defender en-Vec", target_player_index=0,
    ).supported
    _w1g1_resolve_stack(game)

    assert _w1g1_counters_on(defender, "fade") == 2
    assert _w1g1_damage_dealt(game, ridgeback, 3) == 1
    assert _w1g1_damage_dealt(game, p1, 3) == 1


def test_w1g1_skyshroud_behemoth_enters_tapped_with_its_two_counters(set_pool):
    """"This creature enters tapped." beside "Fading 2": cast from hand, it
    arrives tapped *and* carrying both counters — two entry-state readers on
    one permanent."""
    game = _w1g1_duel()
    p1 = game.players[0]
    p1.hand = [set_pool("NEM")["Skyshroud Behemoth"]]

    assert game.cast_from_hand(0, "Skyshroud Behemoth").supported
    _w1g1_resolve_stack(game)

    [behemoth] = [p for p in p1.battlefield if p.card.name == "Skyshroud Behemoth"]
    assert behemoth.tapped is True
    assert _w1g1_counters_on(behemoth, "fade") == 2
    assert (behemoth.effective_power, behemoth.effective_toughness) == (10, 10)


def test_w1g1_rusting_golem_is_as_big_as_its_fade_counters_and_dies_a_0_0(set_pool):
    """"Rusting Golem's power and toughness are each equal to the number of
    fade counters on it." A characteristic-defining ability read off the same
    pile fading takes from: a 5/5 as it enters, one smaller after each of its
    controller's upkeeps — and a 0/0 at the fifth, which the state-based
    check puts in the graveyard (CR 704.5f) an upkeep before fading itself
    would have sacrificed it."""
    game = _w1g1_duel()
    p1 = game.players[0]
    p1.hand = [set_pool("NEM")["Rusting Golem"]]
    assert game.cast_from_hand(0, "Rusting Golem").supported
    _w1g1_resolve_stack(game)
    [golem] = [p for p in p1.battlefield if p.card.name == "Rusting Golem"]
    assert (golem.effective_power, golem.effective_toughness) == (5, 5)

    sizes = []
    for seat in (1, 0) * 5:
        game.turn += 1
        game.begin_turn_bookkeeping(seat)
        game.resolve_upkeep(seat)
        _w1g1_resolve_stack(game)
        game.check_state_based_actions()
        if seat == 0:
            sizes.append(
                golem.effective_power if game.is_on_battlefield(golem) else "gone"
            )

    assert sizes == [4, 3, 2, 1, "gone"]
    assert [c.name for c in p1.graveyard] == ["Rusting Golem"]
    assert "Rusting Golem was sacrificed" not in game.log

# --- end W1G1 ---
