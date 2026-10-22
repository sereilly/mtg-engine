"""``engine/bare_announcements.py`` and the resolver behind it, one piece at a
time. The pool-wide statement is ``tests/regressions/
test_bare_announcement_census.py``; these are the parts it is made of.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.bare_announcements import (
    announced_fields, announced_slots, default_activation_target,
    default_cast_target, names_an_object, seat_of_unseated_slot, standing_order,
)
from engine.game_types import OracleExecutionContext
from engine.handlers._targets import (pick_target_permanent,
                                      resolve_target_permanent)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _mk_creature_card, _nosick


def _table(mine=(), theirs=()):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    rows = []
    for seat, cards in enumerate((mine, theirs)):
        row = []
        for card in cards:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_nosick(permanent))
        rows.append(row)
    return game, rows[0], rows[1]


# ---------------------------------------------------------------------------
# Standing order
# ---------------------------------------------------------------------------


def test_standing_order_puts_one_seats_entries_first_and_keeps_the_pickers_order():
    offered = [
        {"kind": "player", "seat": 0},
        {"kind": "player", "seat": 1},
        {"kind": "permanent", "seat": 0, "index": 0},
        {"kind": "permanent", "seat": 0, "index": 1},
        {"kind": "permanent", "seat": 1, "index": 0},
        {"kind": "stack", "stack_index": 0},
    ]

    ordered = standing_order(offered, 1)

    # The standing seat's face before its permanents, as the picker lists
    # them; then everything else exactly as it stood.
    assert ordered[:2] == [
        {"kind": "player", "seat": 1}, {"kind": "permanent", "seat": 1, "index": 0},
    ]
    assert ordered[2:] == [
        {"kind": "player", "seat": 0},
        {"kind": "permanent", "seat": 0, "index": 0},
        {"kind": "permanent", "seat": 0, "index": 1},
        {"kind": "stack", "stack_index": 0},
    ]
    assert standing_order(offered, 0)[0] == {"kind": "player", "seat": 0}
    assert offered[0] == {"kind": "player", "seat": 0}    # not sorted in place


def test_names_an_object_reads_every_channel_and_never_the_seat():
    assert not names_an_object(None, None, None)
    assert not names_an_object(None, [None], None)
    assert not names_an_object([None, None], None, None)
    assert names_an_object(0, None, None)
    assert names_an_object(None, [41], None)
    assert names_an_object(None, None, object())
    assert names_an_object(None, None, None, [{"permanent_id": 3}])
    assert names_an_object(None, None, None, None, [(1, None)])


# ---------------------------------------------------------------------------
# The two defaults
# ---------------------------------------------------------------------------


def test_the_cast_default_is_the_pickers_first_entry_in_standing_order(catalog_by_name):
    bears, giant = catalog_by_name["Grizzly Bears"], catalog_by_name["Hill Giant"]
    game, (mine,), (theirs,) = _table([bears], [giant])
    bolt, growth = catalog_by_name["Lightning Bolt"], catalog_by_name["Giant Growth"]

    # "Any target": the opposing player's face, before that player's creature.
    assert default_cast_target(game, 0, bolt) == ({"kind": "player", "seat": 1}, False)
    assert default_cast_target(game, 1, bolt) == ({"kind": "player", "seat": 0}, False)
    # A seat named for a spell whose target may be a player is the target.
    assert default_cast_target(game, 0, bolt, named_seat=0) == (None, False)

    entry, _ = default_cast_target(game, 0, growth)
    assert (entry["kind"], entry["seat"], entry["index"]) == ("permanent", 1, 0)
    entry, _ = default_cast_target(game, 0, growth, named_seat=0)
    assert (entry["kind"], entry["seat"], entry["index"]) == ("permanent", 0, 0)
    assert announced_fields(game, entry) == {
        "target_player_index": 0, "target_permanent_index": 0,
        "target_permanent_ids": [mine.permanent_id],
    }


def test_a_spell_that_owes_nothing_or_a_count_has_no_default(catalog_by_name):
    game, _, _ = _table(
        [catalog_by_name["Grizzly Bears"]], [catalog_by_name["Hill Giant"]],
    )

    for name in (
        "Wrath of God",      # targets nothing
        "Ashes to Ashes",    # "two target nonartifact creatures": refused, not defaulted
        "Grizzly Bears",     # a permanent spell
    ):
        assert default_cast_target(game, 0, catalog_by_name[name]) == (None, False), name


def test_an_announced_x_no_entry_answers_is_unanswerable(catalog_by_name):
    """"Destroy target artifact with mana value X": entries, and an X none of
    them has — the one "nothing to name" the picker's list cannot show."""
    game, _, (thopter, ring) = _table(
        [], [catalog_by_name["Ornithopter"], catalog_by_name["Sol Ring"]],
    )
    detonate = catalog_by_name["Detonate"]

    entry, unanswerable = default_cast_target(game, 0, detonate, x_value=1)
    assert entry["index"] == 1 and not unanswerable    # the Sol Ring
    assert default_cast_target(game, 0, detonate, x_value=5) == (None, True)
    # With no X announced the target implies it, and the first artifact stands.
    entry, unanswerable = default_cast_target(game, 0, detonate)
    assert entry["index"] == 0 and not unanswerable


def test_a_slot_named_beside_no_seat_is_the_announcers_own_where_the_default_has_none():
    cards = [_mk_creature_card(name, 2, 2) for name in ("One", "Two")]
    game, (mine, second), (theirs,) = _table(cards, cards[:1])

    assert seat_of_unseated_slot(game, 0, 0, 1) is None     # the default seat has slot 0
    assert seat_of_unseated_slot(game, 0, 1, 1) == 0        # …and no slot 1
    assert seat_of_unseated_slot(game, 0, 5, 1) is None     # nobody has slot 5
    assert seat_of_unseated_slot(game, 0, None, 1) is None


def test_the_activation_default_is_the_gates_own_list(catalog_by_name):
    """Royal Assassin's "destroy target **tapped** creature": the default is
    the first *tapped* creature, which is the picker's list and not a scan
    for the first creature."""
    assassin = catalog_by_name["Royal Assassin"]
    bears, giant = catalog_by_name["Grizzly Bears"], catalog_by_name["Hill Giant"]
    game, (source,), (untapped, tapped) = _table([assassin], [bears, giant])
    tapped.tapped = True
    ability = usable_activated_abilities(compile_card_oracle(assassin))[0]

    entry = default_activation_target(game, 0, source, ability)

    assert (entry["kind"], entry["seat"], entry["index"]) == ("permanent", 1, 1)

    tapped.tapped = False
    assert default_activation_target(game, 0, source, ability) is None


# ---------------------------------------------------------------------------
# The resolver has no scan for an announced object
# ---------------------------------------------------------------------------


def _three_creatures():
    cards = [_mk_creature_card(name, 2, 2) for name in ("First", "Second", "Third")]
    game, _, (first, second, third) = _table([], cards)
    return game, first, second, third


def test_an_unannounced_context_still_scans():
    """A triggered ability whose fire site stamped no target, a hand-built
    context: the handler's standing answer, unchanged."""
    game, first, _second, _third = _three_creatures()

    assert pick_target_permanent(game.players[1], None, game=game) is first


def test_an_announced_object_that_named_nobody_resolves_on_nobody():
    game, _first, _second, _third = _three_creatures()

    assert pick_target_permanent(
        game.players[1], None, game=game, announced=True,
    ) is None


def test_an_announced_target_the_sentence_declines_is_not_replaced():
    """The id is the announcement. Where the handler's own predicate does not
    admit that permanent, nothing else is acted on — not the slot beside the
    id, and not the first permanent the predicate does admit (CR 608.2b: an
    illegal target is not affected, and nothing takes its place)."""
    game, first, second, _third = _three_creatures()
    second.tapped = True
    untapped = lambda permanent: not permanent.tapped  # noqa: E731

    assert pick_target_permanent(
        game.players[1], 1, game=game, permanent_id=second.permanent_id,
        predicate=untapped,
    ) is first    # the scan, for a context that is not an announcement
    assert pick_target_permanent(
        game.players[1], 1, game=game, permanent_id=second.permanent_id,
        predicate=untapped, announced=True,
    ) is None
    assert pick_target_permanent(
        game.players[1], 1, game=game, permanent_id=second.permanent_id,
        announced=True,
    ) is second


def test_the_context_carries_the_flag_to_the_resolver():
    game, first, _second, _third = _three_creatures()
    caster, target = game.players
    card = first.card

    bare = OracleExecutionContext(caster=caster, target=target, card=card)
    announced = OracleExecutionContext(
        caster=caster, target=target, card=card, announced=True,
    )

    assert resolve_target_permanent(game, bare) is first
    assert resolve_target_permanent(game, announced) is None
    assert resolve_target_permanent(
        game, announced, fallback_players=(target, caster),
    ) is None


# ---------------------------------------------------------------------------
# The slot is read off the id
# ---------------------------------------------------------------------------


def test_announced_slots_follow_the_permanent_and_end_when_it_leaves():
    game, first, second, third = _three_creatures()
    seat = game.players[1]

    assert announced_slots(game, seat, None, [second.permanent_id]) == 1
    assert announced_slots(game, seat, 1, [second.permanent_id]) == 1
    game.remove_from_battlefield(first)
    assert announced_slots(game, seat, 1, [second.permanent_id]) == 0
    game.remove_from_battlefield(second)
    assert announced_slots(game, seat, 1, [second.permanent_id]) is None
    # …and a permanent on the other seat has no slot on this one.
    assert announced_slots(game, game.players[0], 0, [third.permanent_id]) is None


def test_announced_slots_leave_a_slot_with_no_id_alone():
    """A card in a graveyard is named by slot and carries no permanent id —
    and so is every entry of a list whose id is None."""
    game, first, second, _third = _three_creatures()
    seat = game.players[1]

    assert announced_slots(game, seat, 3, None) == 3
    assert announced_slots(game, seat, 3, [None]) == 3
    assert announced_slots(game, seat, [0, 4], [second.permanent_id, None]) == [1, 4]
    assert announced_slots(
        game, seat, None, [second.permanent_id, first.permanent_id],
    ) == [1, 0]
