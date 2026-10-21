"""Torment instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
#
# Madness (CR 702.35). Each instant is discarded the way Torment discards —
# to an Aquamoeba's "Discard a card:" cost unless the test says otherwise —
# and is then cast for its madness cost out of exile during its trigger's
# resolution (CR 608.2g). A seat in ``interactive_seats`` is asked
# (``confirm_madness_cast``); any other seat answers with the AI's rehearsed
# chooser as the prompt is armed.

from engine import Game as _w1g1_Game, PlayerState as _w1g1_PlayerState
from engine.models import Permanent as _w1g1_Permanent
from tests.helpers import _nosick as _w1g1_nosick, resolve_stack as _w1g1_resolve


def _w1g1_board(set_pool, madness_name, *, lands, opponent=(), interactive=True,
                graveyard=(), opponent_hand=()):
    """P0 holds *madness_name* beside an untapped Aquamoeba and *lands*; P1
    has *opponent* on the battlefield. Mana is enforced, so what a cast costs
    is what the lands can pay."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    pool = {**lea, **tor}
    aqua = _w1g1_nosick(_w1g1_Permanent(card=tor["Aquamoeba"]))
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            name="P0",
            battlefield=[aqua] + [_w1g1_Permanent(card=pool[land]) for land in lands],
            hand=[tor[madness_name]],
            graveyard=[pool[name] for name in graveyard],
            library=[lea["Island"]] * 5,
        ),
        _w1g1_PlayerState(
            name="P1",
            battlefield=[_w1g1_nosick(_w1g1_Permanent(card=pool[name])) for name in opponent],
            hand=[pool[name] for name in opponent_hand],
        ),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = {0} if interactive else set()
    return game, aqua


def _w1g1_discard_to_aquamoeba(game):
    result = game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0)
    assert result.supported, result.details


def test_w1g1_fiery_temper_is_cast_for_its_madness_cost_by_a_seat_nobody_asks(set_pool):
    """Discarded to Aquamoeba, an AI seat casts Fiery Temper for {R} — one
    Mountain, where the mana cost {1}{R}{R} would need three — at the
    opponent's Grizzly Bears, and the ability the discard paid for still
    resolves (last)."""
    game, aqua = _w1g1_board(
        set_pool, "Fiery Temper", lands=("Mountain",),
        opponent=("Grizzly Bears",), interactive=False,
    )
    _w1g1_discard_to_aquamoeba(game)
    assert not game.stack
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Fiery Temper"]
    assert not game.players[0].exile
    assert any("cast Fiery Temper for its madness cost" in line for line in game.log)
    assert (aqua.effective_power, aqua.effective_toughness) == (3, 1)


def test_w1g1_fiery_temper_declined_goes_to_the_graveyard(set_pool):
    game, _aqua = _w1g1_board(
        set_pool, "Fiery Temper", lands=("Mountain",), opponent=("Grizzly Bears",),
    )
    _w1g1_discard_to_aquamoeba(game)
    assert game.pending_choice_of("madness_cast", 0) is not None
    assert game.confirm_madness_cast(0, False)
    _w1g1_resolve(game)
    assert [c.name for c in game.players[0].graveyard] == ["Fiery Temper"]
    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly Bears"]
    assert not game.players[0].battlefield[1].tapped  # nothing was paid


def test_w1g1_circular_logic_counters_for_u_when_discarded_in_response(set_pool):
    """Lightning Bolt is on the stack; in response P0 discards Circular Logic
    to Aquamoeba and casts it for {U}, naming the Bolt. Two cards in P0's
    graveyard and no untapped land behind the Bolt: it is countered."""
    game, _aqua = _w1g1_board(
        set_pool, "Circular Logic", lands=("Island",),
        graveyard=("Island", "Island"), opponent_hand=("Lightning Bolt",),
    )
    game.active_player_index = 1
    game.enforce_mana_costs = False
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    game.enforce_mana_costs = True
    _w1g1_discard_to_aquamoeba(game)
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Aquamoeba", "Circular Logic",
    ]
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.tap_land_for_mana(0, "Island")
    bolt_index = next(
        i for i, item in enumerate(game.stack) if item.card.name == "Lightning Bolt"
    )
    assert game.confirm_madness_cast(0, True, target_stack_index=bolt_index)
    _w1g1_resolve(game)
    assert game.players[0].life == 20
    assert "Lightning Bolt" in [c.name for c in game.players[1].graveyard]


def test_w1g1_frantic_purification_destroys_an_enchantment_for_w(set_pool):
    game, _aqua = _w1g1_board(
        set_pool, "Frantic Purification", lands=("Plains",), opponent=("Bad Moon",),
    )
    moon = game.players[1].battlefield[0]
    _w1g1_discard_to_aquamoeba(game)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.tap_land_for_mana(0, "Plains")
    assert game.confirm_madness_cast(
        0, True, target_permanent_ids=[moon.permanent_id], target_player_index=1,
    )
    _w1g1_resolve(game)
    assert [c.name for c in game.players[1].graveyard] == ["Bad Moon"]
    assert [c.name for c in game.players[0].graveyard] == ["Frantic Purification"]


def test_w1g1_obsessive_search_draws_a_card_for_its_madness_cost(set_pool):
    game, _aqua = _w1g1_board(
        set_pool, "Obsessive Search", lands=("Island",), interactive=False,
    )
    _w1g1_discard_to_aquamoeba(game)
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert [c.name for c in game.players[0].graveyard] == ["Obsessive Search"]


def test_w1g1_psychotic_haze_is_cast_for_two_mana_where_its_mana_cost_is_four(set_pool):
    """{1}{B} out of exile with two Swamps, where {2}{B}{B} could not be paid
    from them: 1 damage to each creature and each player."""
    game, aqua = _w1g1_board(
        set_pool, "Psychotic Haze", lands=("Swamp", "Swamp"),
        opponent=("Llanowar Elves",),
    )
    _w1g1_discard_to_aquamoeba(game)
    game.resolve_top_of_stack(pause_for_choices=True)
    game.tap_land_for_mana(0, "Swamp", permanent_index=1)
    game.tap_land_for_mana(0, "Swamp", permanent_index=2)
    assert game.confirm_madness_cast(0, True)
    _w1g1_resolve(game)
    game.check_state_based_actions()
    assert (game.players[0].life, game.players[1].life) == (19, 19)
    assert [c.name for c in game.players[1].graveyard] == ["Llanowar Elves"]
    assert aqua.damage_marked == 1


def test_w1g1_violent_eruption_divides_four_damage_for_its_madness_cost(set_pool):
    game, _aqua = _w1g1_board(
        set_pool, "Violent Eruption", lands=("Mountain", "Mountain", "Mountain"),
        opponent=("Grizzly Bears",),
    )
    _w1g1_discard_to_aquamoeba(game)
    game.resolve_top_of_stack(pause_for_choices=True)
    for slot in (1, 2, 3):
        game.tap_land_for_mana(0, "Mountain", permanent_index=slot)
    assert game.confirm_madness_cast(
        0, True, divided_targets=[(1, 0, 2), (1, None, 2)],
    )
    _w1g1_resolve(game)
    game.check_state_based_actions()
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]
    assert game.players[1].life == 18


def test_w1g1_sonic_seizure_s_random_discard_is_a_madness_discard(set_pool):
    """Drive list: "As an additional cost to cast this spell, discard a card at
    random." The madness card's trigger — and the spell it becomes — resolve
    before the Seizure it paid for (the ruling), and the Seizure still deals
    its 3."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            name="P0",
            battlefield=[
                _w1g1_Permanent(card=lea["Mountain"]), _w1g1_Permanent(card=lea["Island"]),
            ],
            hand=[tor["Sonic Seizure"], tor["Obsessive Search"]],
            library=[lea["Forest"]] * 3,
        ),
        _w1g1_PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = True
    assert game.tap_land_for_mana(0, "Mountain")
    assert game.cast_from_hand(0, "Sonic Seizure", target_player_index=1).supported
    log = game.log
    drew = next(i for i, line in enumerate(log) if "Obsessive Search drew 1 card" in line)
    seizure = next(i for i, line in enumerate(log) if "P1 took 3 damage" in line)
    assert drew < seizure
    assert game.players[1].life == 17
    assert [c.name for c in game.players[0].hand] == ["Forest"]

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
