"""Stable permanent identity (CR 400.7) and the seam that resolves it.

A battlefield *index* is not an identity. It is a position in a list that
anything leaving the battlefield renumbers, so an index taken before a
resolution step and used after it addresses whichever permanent slid into that
slot — a different card, possibly a different player's. ``Permanent`` compares
by value too, so the obvious repair (hold the object and ask ``in``) matches an
opponent's look-alike instead.

``Permanent.permanent_id`` is the answer to both: unique across every seat,
stable for as long as the object is on the battlefield, and — because CR 400.7
makes a permanent that leaves and returns a *new object* — replaced when it
comes back. The lookup lives on the control seam
(``engine/mixins/helpers.py``) beside ``all_permanents`` and friends, so
"resolve this id" has one implementation rather than one per caller.
"""

import pytest

from engine import Game, PlayerState
from engine.models import Permanent, next_permanent_id

from tests.helpers import _mk_card


def _bear(name="Grizzly Bears"):
    return _mk_card(name=name, mana_cost="{1}{G}", type_line="Creature — Bear")


def _game_with(*battlefields):
    """A game whose seats hold the given permanents, put on through the engine's
    own entry point so they are stamped the way real permanents are."""
    players = [PlayerState(name=f"P{i + 1}") for i in range(len(battlefields))]
    game = Game(players=players)
    game.enforce_mana_costs = False
    for seat, permanents in enumerate(battlefields):
        for permanent in permanents:
            game._put_permanent_onto_battlefield(seat, permanent, None)
    return game


# --------------------------------------------------------------------------
# The id itself
# --------------------------------------------------------------------------

def test_every_permanent_gets_an_id_at_construction():
    """A ``Permanent`` is addressable the moment it exists — including one a
    test rig or the Debug Menu's raw-state injection drops straight onto a
    battlefield list without going through the engine's entry point."""
    first = Permanent(card=_bear())
    second = Permanent(card=_bear())
    assert first.permanent_id and second.permanent_id
    assert first.permanent_id != second.permanent_id


def test_ids_are_unique_across_seats_not_per_player():
    """Per-player numbering is what battlefield indices already are, and it is
    why ``combat_blockers`` has to be nested by defender: slot 0 means two
    different permanents. One counter for the whole game removes that."""
    mine, theirs = Permanent(card=_bear()), Permanent(card=_bear())
    game = _game_with([mine], [theirs])
    assert mine.permanent_id != theirs.permanent_id
    assert game.find_permanent_by_id(mine.permanent_id) == (0, mine)
    assert game.find_permanent_by_id(theirs.permanent_id) == (1, theirs)


def test_two_copies_of_the_same_card_are_different_permanents():
    """The bug value equality causes: two identically-stated copies of one card
    are ``==``, so ``in``/``.index()`` cannot tell them apart. Their ids can."""
    mine, theirs = Permanent(card=_bear()), Permanent(card=_bear())
    assert mine == theirs  # value equality is unchanged — this field is additive
    assert mine.permanent_id != theirs.permanent_id


def test_the_id_is_not_part_of_equality():
    """Deliberate: several call sites (the AI simulator's detached clones) still
    compare permanents by value, and folding identity into ``__eq__`` would be a
    separate behavioural change rather than an additive field."""
    card = _bear()
    assert Permanent(card=card) == Permanent(card=card)


# --------------------------------------------------------------------------
# CR 400.7: a returning permanent is a new object
# --------------------------------------------------------------------------

@pytest.mark.parametrize("reuse_object", [False, True])
def test_a_permanent_that_returns_gets_a_new_id(reuse_object):
    """CR 400.7. Whether the return builds a fresh ``Permanent`` (the usual
    path: a creature dies and is reanimated) or puts the same object back
    (Oubliette's scoped phase-out), the thing that comes back must not answer to
    the id the thing that left had — otherwise an effect that remembered its
    target would reach across a zone change it is not allowed to survive."""
    original = Permanent(card=_bear())
    game = _game_with([original], [])
    old_id = original.permanent_id

    game.players[0].battlefield = []
    assert game.permanent_by_id(old_id) is None

    returning = original if reuse_object else Permanent(card=_bear())
    game._put_permanent_onto_battlefield(0, returning, None)

    assert returning.permanent_id != old_id
    assert game.permanent_by_id(old_id) is None
    assert game.permanent_by_id(returning.permanent_id) is returning


def test_entering_the_battlefield_restamps_a_reused_object():
    """The construction stamp is a fallback for objects the engine never sees
    enter; entry is the authoritative moment. A permanent built long before it
    is played must not carry its construction id onto the battlefield, because
    that id belongs to no battlefield object."""
    permanent = Permanent(card=_bear())
    built_as = permanent.permanent_id
    game = _game_with([], [])
    game._put_permanent_onto_battlefield(0, permanent, None)
    assert permanent.permanent_id != built_as


# --------------------------------------------------------------------------
# The lookup seam
# --------------------------------------------------------------------------

def test_permanent_by_id_returns_none_once_the_permanent_has_left():
    """The whole point, stated as a test: a *stale* id resolves to nothing,
    where a stale index resolves to whatever moved up into the slot."""
    doomed, survivor = Permanent(card=_bear("Doomed")), Permanent(card=_bear("Survivor"))
    game = _game_with([doomed, survivor], [])
    doomed_id, survivor_id = doomed.permanent_id, survivor.permanent_id

    # Slot 0 empties; the survivor renumbers from 1 to 0.
    game.players[0].battlefield = [survivor]

    assert game.permanent_by_id(doomed_id) is None
    assert game.permanent_by_id(survivor_id) is survivor
    # The index that named the survivor a moment ago now names nothing, and the
    # index that named the dead permanent now names the survivor.
    assert game.permanent_at(0, 0) is survivor
    assert game.permanent_at(0, 1) is None


def test_an_id_survives_a_change_of_control():
    """The id addresses the permanent, not the seat that happens to hold it, so
    a lookup after a CR 613 layer 2 control change resolves to the same object
    under its new controller."""
    stolen = Permanent(card=_bear())
    game = _game_with([stolen], [])
    stolen_id = stolen.permanent_id

    game.take_control(stolen, 1, source=Permanent(card=_mk_card(
        name="Control Magic", mana_cost="{2}{U}{U}", type_line="Enchantment — Aura",
    )))

    assert game.permanent_by_id(stolen_id) is stolen
    assert game.find_permanent_by_id(stolen_id)[0] == 1


def test_permanent_id_of_is_none_for_a_permanent_that_is_gone():
    """So an id handed out by the seam is always one the seam can still
    resolve. The object still carries a number; it just isn't a battlefield
    identity any more."""
    permanent = Permanent(card=_bear())
    game = _game_with([permanent], [])
    assert game.permanent_id_of(permanent) == permanent.permanent_id
    game.players[0].battlefield = []
    assert game.permanent_id_of(permanent) is None
    assert permanent.permanent_id  # the field is untouched; membership is what changed


def test_permanent_id_of_does_not_match_a_look_alike():
    """``is_on_battlefield`` compares by identity, and this inherits that: an
    off-battlefield permanent whose twin is still in play is still gone."""
    card = _bear()
    gone, twin = Permanent(card=card), Permanent(card=card)
    game = _game_with([gone, twin], [])
    game.players[0].battlefield = [twin]
    assert gone == twin  # indistinguishable by value, having entered together
    assert game.permanent_id_of(gone) is None
    assert game.permanent_id_of(twin) == twin.permanent_id


def test_lookup_tolerates_junk_ids():
    """Ids arrive from the wire. An unknown, negative, missing or non-numeric
    one is "no such permanent", not an exception — the same answer a permanent
    that has left gives, because to the caller it is the same situation."""
    game = _game_with([Permanent(card=_bear())], [])
    for junk in (None, -1, 0, 10 ** 9, "nope", object()):
        assert game.permanent_by_id(junk) is None
        assert game.find_permanent_by_id(junk) is None


# --------------------------------------------------------------------------
# The index bridge
# --------------------------------------------------------------------------

def test_the_index_bridge_round_trips_while_nothing_moves():
    """The wire still speaks indices, so index → permanent → id → permanent has
    to agree with itself for as long as the board is unchanged. It is the
    *holding* of an index across a change that this migration removes, not the
    index at the boundary."""
    permanents = [Permanent(card=_bear(f"Bear {i}")) for i in range(3)]
    game = _game_with(permanents, [])
    for index, permanent in enumerate(permanents):
        assert game.permanent_at(0, index) is permanent
        assert game.battlefield_index_of(permanent) == index
        assert game.permanent_by_id(game.permanent_id_of(permanent)) is permanent


def test_permanent_at_bounds_checks_instead_of_raising():
    """Every open-coded ``0 <= i < len(battlefield)`` is a guard someone can
    forget; this one cannot be."""
    game = _game_with([Permanent(card=_bear())], [])
    assert game.permanent_at(0, 0) is not None
    for junk in (None, -1, 1, 99, "x"):
        assert game.permanent_at(0, junk) is None


def test_battlefield_index_of_is_none_for_a_permanent_that_has_left():
    """A serializer asking for the slot of something that is gone gets None
    rather than a stale number to put on the wire."""
    permanent = Permanent(card=_bear())
    game = _game_with([permanent], [])
    game.players[0].battlefield = []
    assert game.battlefield_index_of(permanent) is None


def test_next_permanent_id_is_monotonic_and_consumes_no_randomness():
    """Determinism: ``run_ai_simulation`` seeds the module RNG and a seed has to
    reproduce a run exactly. A counter advances only when a permanent is
    created — a sequence that is already seed-reproducible — and it draws
    nothing from the RNG, so it cannot perturb one."""
    import random

    random.seed(1234)
    before = random.random()
    random.seed(1234)
    ids = [next_permanent_id() for _ in range(5)]
    assert ids == sorted(ids) and len(set(ids)) == 5
    assert random.random() == before


# --------------------------------------------------------------------------
# What the id is *for*: the address survives the board changing under it
# --------------------------------------------------------------------------

def _lea(name):
    from tests.helpers import CARDS_BY_NAME

    return CARDS_BY_NAME[name]


def test_a_targeted_spell_still_hits_its_target_after_the_board_renumbers():
    """CR 601.2c: the target is chosen as the spell is cast, and it stays that
    permanent. Between then and resolution the defender's first creature dies,
    so every later slot shifts down by one — and the index recorded at cast time
    now names a *different* creature. The id does not move."""
    caster = PlayerState(name="Caster", hand=[_lea("Giant Growth")])
    defender = PlayerState(name="Defender")
    game = Game(players=[caster, defender])
    game.enforce_mana_costs = False

    doomed = Permanent(card=_lea("Grizzly Bears"))
    wanted = Permanent(card=_lea("Hill Giant"))
    game._put_permanent_onto_battlefield(1, doomed, None)
    game._put_permanent_onto_battlefield(1, wanted, None)

    # Cast at slot 1 — the Hill Giant — without resolving.
    queued = game.queue_from_hand(
        0, "Giant Growth", target_player_index=1, target_permanent_index=1
    )
    assert queued.supported
    assert game.stack[-1].target_permanent_id == wanted.permanent_id

    # The Grizzly Bears leaves before the spell resolves; the Hill Giant slides
    # from slot 1 to slot 0, so slot 1 is now out of range and slot 0 is the
    # creature the spell did *not* target.
    game.players[1].battlefield = [wanted]
    game._settle()

    assert wanted.effective_power == _lea("Hill Giant").base_power + 3
    assert game.players[1].battlefield == [wanted]


def test_a_targeted_spell_still_hits_its_target_when_a_look_alike_moves_in():
    """The nastier half of the same bug: the slot is still occupied, by a
    permanent that is ``==`` to the intended target. Identity comparison cannot
    tell them apart and the index has silently changed meaning; only the id
    distinguishes them."""
    caster = PlayerState(name="Caster", hand=[_lea("Giant Growth")])
    defender = PlayerState(name="Defender")
    game = Game(players=[caster, defender])
    game.enforce_mana_costs = False

    decoy = Permanent(card=_lea("Grizzly Bears"))
    wanted = Permanent(card=_lea("Grizzly Bears"))
    other = Permanent(card=_lea("Grizzly Bears"))
    for perm in (decoy, wanted, other):
        game._put_permanent_onto_battlefield(1, perm, None)
    assert decoy == wanted == other  # indistinguishable by value

    game.queue_from_hand(0, "Giant Growth", target_player_index=1, target_permanent_index=1)
    # The decoy leaves: `other` takes slot 1, the slot the spell recorded.
    game.players[1].battlefield = [wanted, other]
    game._settle()

    assert wanted.power_bonus == 3
    assert other.power_bonus == 0


def test_a_target_that_has_left_falls_back_to_the_old_index_behaviour():
    """Deliberately *not* a fizzle. The id is additive: when it no longer
    resolves, resolution behaves exactly as it did before this migration, so the
    identity fix can only turn a wrong answer into a right one and never
    introduces a new way for a spell to do nothing."""
    caster = PlayerState(name="Caster", hand=[_lea("Giant Growth")])
    defender = PlayerState(name="Defender")
    game = Game(players=[caster, defender])
    game.enforce_mana_costs = False

    doomed = Permanent(card=_lea("Grizzly Bears"))
    survivor = Permanent(card=_lea("Hill Giant"))
    game._put_permanent_onto_battlefield(1, doomed, None)
    game._put_permanent_onto_battlefield(1, survivor, None)

    game.queue_from_hand(0, "Giant Growth", target_player_index=1, target_permanent_index=0)
    game.players[1].battlefield = [survivor]
    game._settle()

    # The chosen target is gone, so the pre-existing index/fallback path picks
    # the remaining creature — unchanged behaviour, stated so a later change to
    # it is a deliberate one.
    assert survivor.power_bonus == 3


def test_the_stack_records_identity_for_every_targeted_object():
    """The stamp happens at the one place an object goes on the stack
    (``Game._stack_push``), so a new kind of stack object gets it without
    anyone remembering to."""
    caster = PlayerState(name="Caster", hand=[_lea("Giant Growth")])
    defender = PlayerState(name="Defender", battlefield=[])
    game = Game(players=[caster, defender])
    game.enforce_mana_costs = False
    bear = Permanent(card=_lea("Grizzly Bears"))
    game._put_permanent_onto_battlefield(1, bear, None)

    game.queue_from_hand(0, "Giant Growth", target_player_index=1, target_permanent_index=0)
    item = game.stack[-1]
    assert item.target_permanent_index == 0
    assert item.target_permanent_id == bear.permanent_id
