"""Betrayers of Kamigawa artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from engine.named_counters import add_counters as _w1g9_add_counters
from engine.named_counters import counters_on as _w1g9_counters_on
from tests.helpers import declare_attack as _w1g9_declare_attack
from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("BOK", "LEA", "LGN", "CHK", "5DN"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, hand=(), mine=(), theirs=(), their_hand=(), interactive=()):
    """Two seats on seat 0's first main phase, costs not enforced; *mine* /
    *theirs* placed and not summoning sick."""
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card("Forest")] * 12),
        _W1G9PlayerState(name="Bob", hand=[card(n) for n in their_hand],
                         library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G9Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed[0], placed[1]


def _w1g9_slot(game, permanent):
    seat = game.controller_index_of(permanent)
    return [p.permanent_id for p in game.players[seat].battlefield].index(
        permanent.permanent_id
    )


def _w1g9_activate(game, permanent, **announce):
    seat = game.controller_index_of(permanent)
    result = game.activate_permanent_ability(
        seat, permanent.card.name, permanent_index=_w1g9_slot(game, permanent),
        **announce,
    )
    _w1g9_settle(game)
    return result


def _w1g9_equip_index(permanent):
    """The equip ability's index among the Equipment's activated abilities —
    the CR 702.6a rewrite sits after every ability printed above it."""
    from engine.oracle import compile_card_oracle

    abilities = compile_card_oracle(permanent.card).activated_abilities
    return next(
        index for index, ability in enumerate(abilities)
        if ability.instruction is not None
        and ability.instruction.kind == "attach_source_to_target"
    )


def _w1g9_equip(game, equipment, creature):
    return _w1g9_activate(
        game, equipment, ability_index=_w1g9_equip_index(equipment),
        target_permanent_ids=[creature.permanent_id],
    )


# Umezawa's Jitte: "Whenever equipped creature deals combat damage, put two
# charge counters on Umezawa's Jitte." / "Remove a charge counter from
# Umezawa's Jitte: Choose one — • Equipped creature gets +2/+2 until end of
# turn. • Target creature gets -1/-1 until end of turn. • You gain 2 life."
# The modal head names the card in full in its cost; it is rewritten into one
# activated ability per bullet (ability indexes 0, 1, 2), the equip rewrite
# after them.


def test_w1g9_jitte_charges_once_per_combat_damage_step(set_pool):
    """Blocked by two Grizzly Bears, the Craw Wurm deals combat damage to both
    at once — one event, one trigger, two charge counters (CR 510.2). The
    Jitte charges even though the Wurm dies in the same damage step: the
    creature was equipped when it dealt the damage."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Umezawa's Jitte", "Craw Wurm"],
        theirs=["Grizzly Bears", "Grizzly Bears"],
    )
    jitte, wurm = mine
    assert _w1g9_equip(game, jitte, wurm).supported
    assert jitte.metadata.get("attached_to") is wurm
    _w1g9_declare_attack(game, 0, blocks={
        _w1g9_slot(game, blocker): _w1g9_slot(game, wurm) for blocker in theirs
    })
    _w1g9_drive_combat(game)
    assert _w1g9_counters_on(jitte, "charge") == 2
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"] * 2


def test_w1g9_jitte_charges_in_each_damage_step_of_a_double_striker(set_pool):
    """Double strike deals combat damage in two steps (CR 702.4b): two
    triggers, four counters."""
    game, mine, _ = _w1g9_table(set_pool, mine=["Umezawa's Jitte", "Ridgetop Raptor"])
    jitte, raptor = mine
    assert _w1g9_equip(game, jitte, raptor).supported
    _w1g9_declare_attack(game, 0)
    _w1g9_drive_combat(game)
    assert game.players[1].life == 16
    assert _w1g9_counters_on(jitte, "charge") == 4


def test_w1g9_jitte_does_not_charge_without_combat_damage(set_pool):
    """No combat damage dealt, no counters, and every mode is refused with
    nothing to remove (CR 602.2b, 601.2h)."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Umezawa's Jitte", "Grizzly Bears"], theirs=["Grizzly Bears"],
    )
    jitte, bears = mine
    assert _w1g9_equip(game, jitte, bears).supported
    assert _w1g9_counters_on(jitte, "charge") == 0
    assert not _w1g9_activate(game, jitte, ability_index=2).supported
    assert not _w1g9_activate(game, jitte, ability_index=0).supported
    assert game.players[0].life == 20
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g9_jitte_modes_each_remove_one_counter(set_pool):
    """Unblocked, the Bears charge the Jitte with two counters; a third is put
    on by hand. Each mode is its own activation removing one: -1/-1 on Bob's
    Hill Giant, two life, +2/+2 on the equipped Bears — and nothing left for a
    fourth."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Umezawa's Jitte", "Grizzly Bears"],
        theirs=["Grizzly Bears", "Hill Giant"],
    )
    jitte, bears = mine
    their_bears, giant = theirs
    assert _w1g9_equip(game, jitte, bears).supported
    _w1g9_declare_attack(game, 0)
    _w1g9_drive_combat(game)
    assert game.players[1].life == 18
    assert _w1g9_counters_on(jitte, "charge") == 2
    _w1g9_add_counters(jitte, "charge", 1)

    assert _w1g9_activate(
        game, jitte, ability_index=1, target_permanent_ids=[giant.permanent_id],
    ).supported
    assert (giant.effective_power, giant.effective_toughness) == (2, 2)
    assert _w1g9_counters_on(jitte, "charge") == 2
    assert _w1g9_activate(game, jitte, ability_index=2).supported
    assert game.players[0].life == 22
    assert _w1g9_counters_on(jitte, "charge") == 1
    assert _w1g9_activate(game, jitte, ability_index=0).supported
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)
    assert (their_bears.effective_power, their_bears.effective_toughness) == (2, 2)
    assert _w1g9_counters_on(jitte, "charge") == 0
    assert not _w1g9_activate(
        game, jitte, ability_index=1, target_permanent_ids=[their_bears.permanent_id],
    ).supported
    assert (their_bears.effective_power, their_bears.effective_toughness) == (2, 2)


def test_w1g9_jitte_pump_reaches_the_last_equipped_creature_after_it_leaves(set_pool):
    """2005-02-01 ruling: "If the Jitte leaves the battlefield after the
    '+2/+2' mode is announced but before it resolves, the bonus is given to
    the creature that was most recently equipped." Shattered in response,
    the Jitte's pump still reaches the Bears (CR 608.2h)."""
    game, mine, _ = _w1g9_table(
        set_pool, hand=["Shatter"], mine=["Umezawa's Jitte", "Grizzly Bears"],
    )
    jitte, bears = mine
    assert _w1g9_equip(game, jitte, bears).supported
    _w1g9_add_counters(jitte, "charge", 1)
    assert game.queue_permanent_ability(
        0, jitte.card.name, permanent_index=_w1g9_slot(game, jitte), ability_index=0,
    ).supported
    assert _w1g9_counters_on(jitte, "charge") == 0
    assert game.queue_from_hand(
        0, "Shatter", target_permanent_ids=[jitte.permanent_id],
    ).supported
    _w1g9_settle(game)
    assert not game.is_on_battlefield(jitte)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)


def test_w1g9_unattached_jitte_pump_does_nothing(set_pool):
    """2005-02-01 ruling: "Choosing the 'Equipped creature gets +2/+2 until
    end of turn' mode does nothing if the Jitte isn't equipped to a creature
    when the ability resolves." The counter is still spent (it is the cost)."""
    game, mine, _ = _w1g9_table(set_pool, mine=["Umezawa's Jitte", "Grizzly Bears"])
    jitte, bears = mine
    _w1g9_add_counters(jitte, "charge", 1)
    _w1g9_activate(game, jitte, ability_index=0)
    assert _w1g9_counters_on(jitte, "charge") == 0
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
