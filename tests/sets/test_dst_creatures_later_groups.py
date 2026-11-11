"""Darksteel creatures (legendary ones too) — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), mine=(), theirs=(),
                interactive=()):
    """Costs not enforced, every permanent past summoning sickness and
    untapped, seat 0 active in its first main phase."""
    pools = [set_pool("DST"), set_pool("MRD"), set_pool("LEA")]

    def w1g7_card(name):
        return next(pool[name] for pool in pools if name in pool)

    game = _W1G7Game(players=[
        _W1G7PlayerState(name="W1G7-A", hand=[w1g7_card(n) for n in hand],
                         library=[w1g7_card("Forest") for _ in range(10)]),
        _W1G7PlayerState(name="W1G7-B", hand=[w1g7_card(n) for n in opponent_hand],
                         library=[w1g7_card("Forest") for _ in range(10)]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    rows = []
    for seat, names in ((0, mine), (1, theirs)):
        row = []
        for name in names:
            perm = _W1G7Permanent(card=w1g7_card(name))
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            row.append(perm)
        rows.append(row)
    game.start_turn(0)
    _w1g7_settle(game)
    return game, rows[0], rows[1]  # _w1g7_table


def test_w1g7_pristine_angel_is_protected_exactly_while_untapped(set_pool):
    """"As long as this creature is untapped, it has protection from artifacts
    and from each color." CR 702.16g/h: one ability per quality, so an
    untapped Angel can't be the target of a red Bolt; tapped, it can, and two
    Bolts kill the 4/4."""
    game, mine, _theirs = _w1g7_table(
        set_pool, opponent_hand=["Lightning Bolt"] * 3, mine=["Pristine Angel"],
    )
    angel = mine[0]
    assert game._protection_qualities(angel) == {
        ("card_type", "artifact"), ("color", "W"), ("color", "U"),
        ("color", "B"), ("color", "R"), ("color", "G"),
    }
    game.active_player_index = 1
    refused = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[angel.permanent_id]
    )
    assert not refused.supported
    assert "illegal target" in refused.details
    angel.tapped = True
    assert game._protection_qualities(angel) == set()
    for _ in range(2):
        bolt = game.cast_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[angel.permanent_id]
        )
        assert bolt.supported, bolt.details
        _w1g7_settle(game)
    assert not game.is_on_battlefield(angel)
    assert "Pristine Angel" in [c.name for c in game.players[0].graveyard]


def _w1g7_bolt_the_tapped_angel_and_respond(set_pool):
    """Seat 1 Bolts a tapped Angel; seat 0 Bolts a Bears in response, which
    triggers the Angel's "you may untap" above both spells."""
    game, mine, theirs = _w1g7_table(
        set_pool, hand=["Lightning Bolt"], opponent_hand=["Lightning Bolt"],
        mine=["Pristine Angel"], theirs=["Grizzly Bears"], interactive=[0],
    )
    angel, bears = mine[0], theirs[0]
    angel.tapped = True
    game.active_player_index = 1
    first = game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[angel.permanent_id]
    )
    assert first.supported, first.details
    second = game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    )
    assert second.supported, second.details
    owed = _w1g7_settle(game, defaults=False)
    assert owed is not None and owed.kind == "optional_pay"
    assert owed.player_index == 0
    return game, angel, bears  # _w1g7_bolt_the_tapped_angel_and_respond


def test_w1g7_pristine_angel_untaps_in_response_and_the_bolt_fizzles(set_pool):
    """"Whenever you cast a spell, you may untap this creature." The tapped
    Angel is Bolted; its controller casts a spell in response and says yes to
    the untap as an interactive seat, so the Angel has protection again
    before the first Bolt resolves — its one target is illegal and it does
    nothing (CR 608.2b)."""
    game, angel, bears = _w1g7_bolt_the_tapped_angel_and_respond(set_pool)
    _w1g7_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(
            c.player_index, accept=True
        ),
    })
    assert not angel.tapped
    assert game.is_on_battlefield(angel) and angel.damage_marked == 0
    assert not game.is_on_battlefield(bears)


def test_w1g7_pristine_angel_declined_untap_stays_tapped_and_is_burned(set_pool):
    """The same offer declined: the Angel stays tapped and unprotected, and
    the first Bolt marks its 3 damage."""
    game, angel, bears = _w1g7_bolt_the_tapped_angel_and_respond(set_pool)
    _w1g7_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(
            c.player_index, accept=False
        ),
    })
    assert angel.tapped
    assert game.is_on_battlefield(angel) and angel.damage_marked == 3
    assert not game.is_on_battlefield(bears)


def test_w1g7_pristine_angel_blocking_untapped_takes_no_damage_from_a_red_creature(
    set_pool,
):
    """CR 702.16f is the attacking half, and an attacking Angel is tapped —
    so the case that shows the static in combat is the *blocking* one: an
    untapped Angel blocks a red Hill Giant and takes none of its damage
    (CR 702.16e), and the Giant dies to the Angel's four."""
    game, mine, theirs = _w1g7_table(
        set_pool, mine=["Pristine Angel"], theirs=["Hill Giant"],
    )
    angel = mine[0]
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(0, {0: 0})
    assert ok, why
    from tests.helpers import drive_combat as _w1g7_drive_combat

    _w1g7_drive_combat(game)
    assert game.is_on_battlefield(angel) and angel.damage_marked == 0
    assert not game.is_on_battlefield(theirs[0])


def test_w1g7_tanglewalker_makes_its_side_unblockable_against_an_artifact_land(
    set_pool,
):
    """"Each creature you control can't be blocked as long as defending player
    controls an artifact land." Darksteel Citadel on the defender's side:
    neither attacker can be blocked, and the UI's flag agrees with the step.
    The defender's own creatures are not "creatures you control" for it."""
    game, mine, theirs = _w1g7_table(
        set_pool, mine=["Tanglewalker", "Grizzly Bears"],
        theirs=["Darksteel Citadel", "Grizzly Bears"],
    )
    walker, bears = mine
    blocker = theirs[1]
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0, 1], defending_player_index=1)
    assert ok, why
    assert game.is_unblockable(walker) and game.is_unblockable(bears)
    assert not game.is_unblockable(blocker)
    game.advance_combat_phase()
    for slot in (0, 1):
        ok, _why = game.declare_blockers(1, {1: slot})
        assert not ok
    ok, why = game.declare_blockers(1, {})
    assert ok, why
    from tests.helpers import drive_combat as _w1g7_drive_combat

    _w1g7_drive_combat(game)
    assert game.players[1].life == 20 - 2 - 2


def test_w1g7_tanglewalker_does_nothing_without_an_artifact_land(set_pool):
    """The condition is the card, asked as blockers are declared: the
    defender's Forest and Myr Moonvessel (an artifact that is no land) do not
    satisfy it, so once the Citadel has left before blockers the Moonvessel
    blocks as usual."""
    game, mine, theirs = _w1g7_table(
        set_pool, mine=["Tanglewalker"],
        theirs=["Forest", "Myr Moonvessel", "Darksteel Citadel"],
    )
    walker = mine[0]
    citadel = theirs[2]
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    assert game.is_unblockable(walker)
    # Indestructible, so it leaves the way an indestructible land can.
    assert game.sacrifice_permanent(citadel) is not None
    assert not game.is_on_battlefield(citadel)
    assert not game.is_unblockable(walker)
    game.advance_combat_phase()
    moonvessel_slot = game.battlefield_index_of(theirs[1])
    ok, why = game.declare_blockers(1, {moonvessel_slot: 0})
    assert ok, why


def _w1g7_engineer_mana(set_pool, *, hand=(), mine=(), color=None):
    """Seat 0 taps a Vedalken Engineer for two mana of one colour — as an
    interactive seat answering the colour prompt when *color* is given, as a
    default seat otherwise. Costs enforced from here on."""
    game, board, _theirs = _w1g7_table(
        set_pool, hand=hand, mine=["Vedalken Engineer", *mine],
        interactive=[0] if color else [],
    )
    game.enforce_mana_costs = True
    tapped = game.activate_permanent_ability(0, "Vedalken Engineer")
    assert tapped.supported, tapped.details
    if color:
        owed = _w1g7_settle(game, defaults=False)
        assert owed is not None and owed.kind == "mana_color_choice"
        assert game.resolve_pending_choice("mana_color_choice", 0, color=color)
    _w1g7_settle(game)
    return game, board  # _w1g7_engineer_mana


def _w1g7_restricted(game):
    return {
        key: {symbol: n for symbol, n in bucket.items() if n}
        for key, bucket in game.players[0].restricted_mana.items()
        if any(bucket.values())
    }  # _w1g7_restricted


def test_w1g7_vedalken_engineer_mana_casts_an_artifact_but_not_a_creature_spell(
    set_pool,
):
    """"{T}: Add two mana of any one color. Spend this mana only to cast
    artifact spells or activate abilities of artifacts." Two green from the
    Engineer cannot pay for Grizzly Bears — the cast is refused and the mana
    stays — and then pays for a Myr Moonvessel ({1}), one left over and still
    restricted; none of it ever reaches the ordinary pool (CR 106.6)."""
    game, _board = _w1g7_engineer_mana(
        set_pool, hand=["Grizzly Bears", "Myr Moonvessel"], color="G",
    )
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"G": 2}}
    assert not any(game.players[0].mana_pool.values())
    refused = game.cast_from_hand(0, "Grizzly Bears")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears", "Myr Moonvessel"]
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"G": 2}}
    cast = game.cast_from_hand(0, "Myr Moonvessel")
    assert cast.supported, cast.details
    _w1g7_settle(game)
    assert "Myr Moonvessel" in [p.card.name for p in game.players[0].battlefield]
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"G": 1}}


def test_w1g7_vedalken_engineer_mana_activates_an_artifact_not_a_creature(set_pool):
    """The other half: the mana pays Darksteel Pendant's "{1}, {T}: Scry 1"
    and not Shivan Dragon's "{R}: +1/+0" — a creature's ability is no
    "ability of an artifact" — even when the colour chosen is red."""
    game, board = _w1g7_engineer_mana(
        set_pool, mine=["Darksteel Pendant", "Shivan Dragon"], color="R",
    )
    _engineer, pendant, dragon = board
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"R": 2}}
    firebreath = game.activate_permanent_ability(0, "Shivan Dragon")
    assert not firebreath.supported
    assert dragon.effective_power == 5
    scry = game.activate_permanent_ability(0, "Darksteel Pendant")
    assert scry.supported, scry.details
    _w1g7_settle(game)
    assert pendant.tapped
    assert _w1g7_restricted(game) == {"artifact_or_artifact_ability": {"R": 1}}


def test_w1g7_vedalken_engineer_default_seat_makes_the_same_restricted_mana(
    set_pool,
):
    """A seat nobody asks takes the colour prompt's default as it is armed:
    two mana of one colour, under the same restriction."""
    game, _board = _w1g7_engineer_mana(set_pool)
    restricted = _w1g7_restricted(game)
    assert list(restricted) == ["artifact_or_artifact_ability"]
    assert sum(restricted["artifact_or_artifact_ability"].values()) == 2
    assert len(restricted["artifact_or_artifact_ability"]) == 1


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
