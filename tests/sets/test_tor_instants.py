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

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, *, hand0=(), gy0=(), bf1=()):
    """A two-seat game with costs off, built from card names (TOR over LEA)."""
    pool = {**set_pool("LEA"), **set_pool("TOR")}
    seats = [
        _w1g2_PlayerState(
            name="P0", life=20, hand=[pool[n] for n in hand0],
            graveyard=[pool[n] for n in gy0], library=[pool["Forest"]] * 10,
        ),
        _w1g2_PlayerState(name="P1", life=20, library=[pool["Forest"]] * 10),
    ]
    game = _w1g2_Game(players=seats)
    game.enforce_mana_costs = False
    for name in bf1:
        perm = _w1g2_Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(1, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g2_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Temporary Insanity: a target bounded by the caster's graveyard ----------

def test_temporary_insanity_offers_only_creatures_under_the_graveyard_count(set_pool):
    """"…target creature with power **less than** the number of cards in your
    graveyard" — strictly less, counted as the spell is announced (CR 601.2c),
    so a 3-power creature is no target over a graveyard of three."""
    def offered(graveyard_size):
        game = _w1g2_table(
            set_pool, hand0=["Temporary Insanity"],
            gy0=["Forest"] * graveyard_size,
            bf1=["Grizzly Bears", "Hill Giant", "Craw Wurm"],
        )
        spec = game.cast_target_spec(0, game.players[0].hand[0])
        return [target["name"] for target in spec["valid_targets"]]

    assert offered(2) == []
    assert offered(3) == ["Grizzly Bears"]
    assert offered(4) == ["Grizzly Bears", "Hill Giant"]
    assert offered(7) == ["Grizzly Bears", "Hill Giant", "Craw Wurm"]

    game = _w1g2_table(
        set_pool, hand0=["Temporary Insanity"], gy0=["Forest"] * 3,
        bf1=["Hill Giant"],
    )
    giant = _w1g2_on_board(game, 1, "Hill Giant")
    assert not game.cast_from_hand(
        0, "Temporary Insanity", target_permanent_ids=[giant.permanent_id],
    ).supported
    assert [card.name for card in game.players[0].hand] == ["Temporary Insanity"]


def test_temporary_insanity_untaps_steals_and_hastes_until_end_of_turn(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Temporary Insanity"], gy0=["Forest"] * 3,
        bf1=["Grizzly Bears"],
    )
    bears = _w1g2_on_board(game, 1, "Grizzly Bears")
    bears.tapped = True
    assert game.cast_from_hand(
        0, "Temporary Insanity", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert game.controller_index_of(bears) == 0
    assert not bears.tapped
    assert game._has_keyword(bears, "haste")
    game.resolve_cleanup_step(0)
    assert game.controller_index_of(bears) == 1
    assert not game._has_keyword(bears, "haste")


def test_temporary_insanity_asks_the_bound_again_as_it_resolves(set_pool):
    """CR 608.2b: a graveyard that shrank in response leaves the creature's
    power no longer under the count, so its one target is illegal and the
    spell does nothing — the creature stays tapped and stays put."""
    game = _w1g2_table(
        set_pool, hand0=["Temporary Insanity"], gy0=["Forest"] * 3,
        bf1=["Grizzly Bears"],
    )
    bears = _w1g2_on_board(game, 1, "Grizzly Bears")
    bears.tapped = True
    assert game.queue_from_hand(
        0, "Temporary Insanity", target_permanent_ids=[bears.permanent_id],
    ).supported
    game.players[0].graveyard.pop()
    _w1g2_resolve_stack(game)
    assert game.controller_index_of(bears) == 1 and bears.tapped
    assert any("every target is illegal" in line for line in game.log)

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5_Game
from engine import PlayerState as _w1g5_PlayerState
from engine.models import Permanent as _w1g5_Permanent
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import _nosick as _w1g5_nosick
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_insidious_game(set_pool, *, library, interactive=False):
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Insidious Dreams"]
    filler = _w1g5_mk_card(name="W1G5 Filler", type_line="Land")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState(
            "A", library=list(library),
            hand=[dreams, lea["Forest"], lea["Lightning Bolt"], lea["Island"]],
        ),
        _w1g5_PlayerState("B", library=[filler] * 5),
    ])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game._sync_control()
    return game


def _w1g5_library():
    return [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Land") for i in range(8)]


def test_w1g5_insidious_dreams_puts_the_x_cards_it_found_on_top_in_the_chosen_order(set_pool):
    """X=2: two cards discarded, two found; the finder's pick order is the
    order on top ("in any order", the reading Goblin Recruiter already has)."""
    library = _w1g5_library()
    game = _w1g5_insidious_game(set_pool, library=library, interactive=True)

    result = game.cast_from_hand(
        0, "Insidious Dreams", x_value=2, cost_hand_index=1, cost_other_hand_indices=[2],
    )
    search = game.pending_choice_of("search_library", 0)

    assert result.supported, result.details
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert search is not None
    names = [card.name for card in game.players[0].library]
    picks = [
        {"zone": "library", "index": names.index("W1G5 Card 6")},
        {"zone": "library", "index": names.index("W1G5 Card 3")},
    ]
    assert game.resolve_pending_choice("search_library", 0, picks=picks)
    _w1g5_resolve_stack(game)

    top = [card.name for card in game.players[0].library[:2]]
    assert top == ["W1G5 Card 6", "W1G5 Card 3"]
    assert len(game.players[0].library) == 8


def test_w1g5_insidious_dreams_must_find_x_cards(set_pool):
    """"for X cards" prints no "up to": a quantity search is a floor
    (CR 701.23d), so an answer finding one of two is refused."""
    game = _w1g5_insidious_game(set_pool, library=_w1g5_library(), interactive=True)

    game.cast_from_hand(0, "Insidious Dreams", x_value=2)
    search = game.pending_choice_of("search_library", 0)

    assert game._search_floor(search) == 2
    assert not game.resolve_pending_choice(
        "search_library", 0, picks=[{"zone": "library", "index": 0}],
    )
    assert game.pending_choice_of("search_library", 0) is search


def test_w1g5_insidious_dreams_at_x_zero_shuffles_and_finds_nothing(set_pool):
    library = _w1g5_library()
    game = _w1g5_insidious_game(set_pool, library=library)

    result = game.cast_from_hand(0, "Insidious Dreams", x_value=0)
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    assert len(game.players[0].hand) == 3
    assert len(game.players[0].library) == 8
    assert "A searched their library for 0 cards and shuffled" in game.log


def _w1g5_vengeful_game(set_pool):
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Vengeful Dreams"]
    filler = _w1g5_mk_card(name="W1G5 Filler", type_line="Land")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState(
            "A", library=[filler] * 5,
            hand=[dreams, lea["Forest"], lea["Island"], lea["Swamp"]],
        ),
        _w1g5_PlayerState(
            "B", library=[filler] * 5,
            battlefield=[
                _w1g5_nosick(_w1g5_Permanent(card=lea[name]))
                for name in ("Grizzly Bears", "Hill Giant", "Serra Angel")
            ],
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    bears, giant, angel = game.controlled_by(1)
    bears.attacking = giant.attacking = True
    return game, (bears, giant, angel)


def test_w1g5_vengeful_dreams_exiles_every_one_of_its_x_attackers(set_pool):
    """X=2 at two attackers: both go. The exile handler read a count of "x" as
    the single target and exiled only the first one named."""
    game, (bears, giant, _angel) = _w1g5_vengeful_game(set_pool)

    result = game.cast_from_hand(
        0, "Vengeful Dreams", x_value=2, target_player_index=1,
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    assert sorted(card.name for card in game.players[1].exile) == [
        "Grizzly Bears", "Hill Giant",
    ]
    assert [p.card.name for p in game.controlled_by(1)] == ["Serra Angel"]
    assert [card.name for card in game.players[0].hand] == ["Swamp"]


def test_w1g5_vengeful_dreams_cannot_name_a_creature_that_is_not_attacking(set_pool):
    game, (bears, _giant, angel) = _w1g5_vengeful_game(set_pool)

    result = game.cast_from_hand(
        0, "Vengeful Dreams", x_value=2, target_player_index=1,
        target_permanent_ids=[bears.permanent_id, angel.permanent_id],
    )

    assert not result.supported
    assert len(list(game.controlled_by(1))) == 3
    assert len(game.players[0].hand) == 4

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState  # noqa: E402
from engine import ai_policy as _w1g6_ai_policy  # noqa: E402
from tests.helpers import resolve_stack as _w1g6_resolve_stack  # noqa: E402


def _w1g6_liquify_table(set_pool, catalog_by_name, spell: str, **cast) -> _W1G6Game:
    """Seat 1 has *spell* on the stack; seat 0 holds Liquify. Mana off."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", hand=[set_pool("TOR")["Liquify"]]),
        _W1G6PlayerState(
            name="P2", hand=[catalog_by_name[spell]],
            library=[catalog_by_name["Island"]] * 5,
        ),
    ])
    game.players[0].hand.extend([catalog_by_name["Island"]] * 4)
    game.enforce_mana_costs = False
    assert game.queue_from_hand(1, spell, **cast).supported
    return game


def test_w1g6_liquify_counters_a_small_spell_and_exiles_it(set_pool, catalog_by_name):
    """"Counter target spell with mana value 3 or less. If that spell is
    countered this way, exile it instead of putting it into its owner's
    graveyard." A Grizzly Bears (mana value 2) is offered, countered and
    exiled."""
    game = _w1g6_liquify_table(set_pool, catalog_by_name, "Grizzly Bears")
    spec = game.cast_target_spec(0, set_pool("TOR")["Liquify"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]
    assert game.cast_from_hand(0, "Liquify", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
    assert game.players[1].graveyard == [] and list(game.controlled_by(1)) == []
    assert [c.name for c in game.players[0].graveyard] == ["Liquify"]


def test_w1g6_liquify_cannot_be_announced_at_a_spell_with_mana_value_four(
    set_pool, catalog_by_name,
):
    """A Hill Giant (mana value 4) is not offered, a cast naming it is refused
    with nothing spent (CR 601.2c), and the AI does not propose it."""
    game = _w1g6_liquify_table(set_pool, catalog_by_name, "Hill Giant")
    liquify = set_pool("TOR")["Liquify"]
    assert game.cast_target_spec(0, liquify)["valid_targets"] == []
    refused = game.cast_from_hand(0, "Liquify", target_stack_index=0)
    assert not refused.supported
    assert "Liquify" in [c.name for c in game.players[0].hand]
    assert len(game.stack) == 1
    assert _w1g6_ai_policy._cast_candidate(
        game, 0, liquify, game.players[0].hand.index(liquify),
    ) is None
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Hill Giant"]


def test_w1g6_liquify_reads_mana_value_on_the_stack_with_its_x(set_pool, catalog_by_name):
    """CR 202.3b: on the stack an {X} counts at the announced value. Mind Twist
    ({X}{B}) cast for X=2 is a three and is countered; cast for X=3 it is a
    four and Liquify cannot be aimed at it."""
    game = _w1g6_liquify_table(
        set_pool, catalog_by_name, "Mind Twist", target_player_index=0, x_value=2,
    )
    assert game.cast_from_hand(0, "Liquify", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Mind Twist"]
    assert len(game.players[0].hand) == 4, "Mind Twist was countered: nothing discarded"

    game = _w1g6_liquify_table(
        set_pool, catalog_by_name, "Mind Twist", target_player_index=0, x_value=3,
    )
    assert not game.cast_from_hand(0, "Liquify", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert [c.name for c in game.players[1].graveyard] == ["Mind Twist"]
    assert len(game.players[0].hand) == 2, "Liquify stayed in hand; three Islands went"

from engine.models import Permanent as _W1G6Permanent  # noqa: E402
from tests.helpers import _nosick as _w1g6_nosick  # noqa: E402


def _w1g6_gambit_table(set_pool, catalog_by_name, *, zone="hand", life=20,
                       interactive=(), walker=False):
    """Seat 0 has Flaming Gambit in *zone*; seat 1 has a Grizzly Bears, a
    Hill Giant and (with *walker*) a Basri Ket at 3 loyalty. Mana enforced."""
    gambit = set_pool("TOR")["Flaming Gambit"]
    theirs = [
        _w1g6_nosick(_W1G6Permanent(card=catalog_by_name[name]))
        for name in ("Grizzly Bears", "Hill Giant")
    ]
    if walker:
        theirs.append(_W1G6Permanent(
            card=catalog_by_name["Basri Ket"], metadata={"loyalty_counters": 3},
        ))
    me = _W1G6PlayerState(name="P1", library=[catalog_by_name["Island"]] * 3)
    getattr(me, zone).append(gambit)
    game = _W1G6Game(players=[
        me, _W1G6PlayerState(name="P2", life=life, battlefield=theirs),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    return game


def _w1g6_permanent(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def test_w1g6_flaming_gambit_hits_the_player_who_declines(set_pool, catalog_by_name):
    """"Flaming Gambit deals X damage to target player or planeswalker. That
    player … may choose a creature they control and have Flaming Gambit deal
    that damage to it instead." Cast for X=3 ({3}{R}, the whole pool): a seat
    nobody asks keeps its creatures while the damage is not lethal, and a
    person who is asked may decline."""
    game = _w1g6_gambit_table(set_pool, catalog_by_name)
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    assert game.cast_from_hand(0, "Flaming Gambit", target_player_index=1, x_value=3).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17
    assert not any(game.players[0].mana_pool.values())
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears", "Hill Giant"]

    game = _w1g6_gambit_table(set_pool, catalog_by_name, interactive={1})
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    assert game.cast_from_hand(0, "Flaming Gambit", target_player_index=1, x_value=3).supported
    owed = [choice for choice in game.pending_choices if choice.kind == "permanent_choice"]
    assert [choice.player_index for choice in owed] == [1], "the damaged player is asked"
    assert game.confirm_permanent_choice(1, None)
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17


def test_w1g6_flaming_gambit_s_damaged_player_sends_it_to_a_creature(set_pool, catalog_by_name):
    """The asked seat names its Hill Giant: the Giant is dealt the 3 and dies,
    the player loses nothing. A seat nobody asks does the same when the damage
    would otherwise be lethal (it names its first creature)."""
    game = _w1g6_gambit_table(set_pool, catalog_by_name, interactive={1})
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    giant = _w1g6_permanent(game, 1, "Hill Giant")
    assert game.cast_from_hand(0, "Flaming Gambit", target_player_index=1, x_value=3).supported
    assert game.confirm_permanent_choice(1, giant.permanent_id)
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 20
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert "Hill Giant" in [c.name for c in game.players[1].graveyard]

    game = _w1g6_gambit_table(set_pool, catalog_by_name, life=3)
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    assert game.cast_from_hand(0, "Flaming Gambit", target_player_index=1, x_value=3).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 3
    assert [p.card.name for p in game.controlled_by(1)] == ["Hill Giant"]


def test_w1g6_flaming_gambit_at_a_planeswalker_asks_its_controller(set_pool, catalog_by_name):
    """"…or that planeswalker's controller": aimed at Basri Ket, the walker's
    controller is asked. Declining, the walker loses 2 loyalty; naming the
    Grizzly Bears, the Bears are dealt the 2 and the walker is untouched."""
    game = _w1g6_gambit_table(set_pool, catalog_by_name, interactive={1}, walker=True)
    walker = _w1g6_permanent(game, 1, "Basri Ket")
    spec = game.cast_target_spec(0, set_pool("TOR")["Flaming Gambit"])
    assert {entry["name"] for entry in spec["valid_targets"] if entry["kind"] == "permanent"} == {"Basri Ket"}
    game.players[0].mana_pool.update({"R": 1, "C": 2})
    assert game.cast_from_hand(
        0, "Flaming Gambit", target_permanent_ids=[walker.permanent_id],
        target_player_index=1, x_value=2,
    ).supported
    assert game.confirm_permanent_choice(1, None)
    _w1g6_resolve_stack(game)
    assert walker.metadata["loyalty_counters"] == 1
    assert game.players[1].life == 20

    game = _w1g6_gambit_table(set_pool, catalog_by_name, interactive={1}, walker=True)
    walker = _w1g6_permanent(game, 1, "Basri Ket")
    bears = _w1g6_permanent(game, 1, "Grizzly Bears")
    game.players[0].mana_pool.update({"R": 1, "C": 2})
    assert game.cast_from_hand(
        0, "Flaming Gambit", target_permanent_ids=[walker.permanent_id],
        target_player_index=1, x_value=2,
    ).supported
    assert game.confirm_permanent_choice(1, bears.permanent_id)
    _w1g6_resolve_stack(game)
    assert walker.metadata["loyalty_counters"] == 3
    assert "Grizzly Bears" in [c.name for c in game.players[1].graveyard]


def test_w1g6_flaming_gambit_flashes_back_for_x_r_r(set_pool, catalog_by_name):
    """"Flashback {X}{R}{R}": the X the cast announces is paid in the
    flashback cost and dealt by the spell, which is then exiled. One mana
    short of {2}{R}{R} for X=2 is a cast refused with nothing spent."""
    game = _w1g6_gambit_table(set_pool, catalog_by_name, zone="graveyard")
    game.players[0].mana_pool.update({"R": 2, "C": 1})
    refused = game.cast_from_hand(
        0, "Flaming Gambit", target_player_index=1, x_value=2, from_zone="graveyard",
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].graveyard] == ["Flaming Gambit"]
    game.players[0].mana_pool["C"] += 1
    assert game.cast_from_hand(
        0, "Flaming Gambit", target_player_index=1, x_value=2, from_zone="graveyard",
    ).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 18
    assert not any(game.players[0].mana_pool.values())
    assert [c.name for c in game.players[0].exile] == ["Flaming Gambit"]

def _w1g6_radiate_table(set_pool, catalog_by_name, mine, theirs, their_hand):
    """Seat 0 holds Radiate over *mine*; seat 1 holds *their_hand* over
    *theirs*. Mana off."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", hand=[set_pool("TOR")["Radiate"]],
            battlefield=[_w1g6_nosick(_W1G6Permanent(card=catalog_by_name[n])) for n in mine],
        ),
        _W1G6PlayerState(
            name="P2", hand=[catalog_by_name[n] for n in their_hand],
            battlefield=[_w1g6_nosick(_W1G6Permanent(card=catalog_by_name[n])) for n in theirs],
        ),
    ])
    game.enforce_mana_costs = False
    return game


def test_w1g6_radiate_copies_a_bolt_onto_everything_else_it_could_target(
    set_pool, catalog_by_name,
):
    """"Choose target instant or sorcery spell that targets only a single
    permanent or player. Copy that spell for each other permanent or player
    the spell could target. Each copy targets a different one of those
    permanents and players." An opponent's Lightning Bolt at seat 0's Grizzly
    Bears: four copies, all seat 0's (CR 707.10a), at the Hill Giant, the
    Serra Angel and both players — and the original still hits the Bears."""
    game = _w1g6_radiate_table(
        set_pool, catalog_by_name, ["Grizzly Bears", "Hill Giant"], ["Serra Angel"],
        ["Lightning Bolt"],
    )
    bears = _w1g6_permanent(game, 0, "Grizzly Bears")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id], target_player_index=0,
    ).supported
    assert game.queue_from_hand(0, "Radiate", target_stack_index=0).supported
    game.resolve_top_of_stack()
    copies = [item for item in game.stack if item.is_copy]
    assert len(copies) == 4 and {item.caster_index for item in copies} == {0}
    _w1g6_resolve_stack(game)
    game.check_state_based_actions()
    assert (game.players[0].life, game.players[1].life) == (17, 17)
    assert _w1g6_permanent(game, 1, "Serra Angel").damage_marked == 3
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Grizzly Bears", "Hill Giant", "Radiate",
    ]


def test_w1g6_radiate_copies_only_onto_what_the_spell_could_target(set_pool, catalog_by_name):
    """"…each other permanent or player **the spell could target**": Terror
    ("target nonartifact, nonblack creature") at a Grizzly Bears is copied
    onto the Hill Giant and nothing else — not the black Knight, not the Sol
    Ring, not a player."""
    game = _w1g6_radiate_table(
        set_pool, catalog_by_name, ["Grizzly Bears", "Hill Giant", "Sol Ring"],
        ["Black Knight"], ["Terror"],
    )
    bears = _w1g6_permanent(game, 0, "Grizzly Bears")
    assert game.queue_from_hand(
        1, "Terror", target_permanent_ids=[bears.permanent_id], target_player_index=0,
    ).supported
    assert game.queue_from_hand(0, "Radiate", target_stack_index=0).supported
    game.resolve_top_of_stack()
    copies = [item for item in game.stack if item.is_copy]
    assert [item.target_permanent_id for item in copies] == [
        _w1g6_permanent(game, 0, "Hill Giant").permanent_id
    ]
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Sol Ring"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Black Knight"]


def test_w1g6_radiate_is_not_offered_a_spell_with_another_kind_of_target(
    set_pool, catalog_by_name,
):
    """A Counterspell targets a spell, not a permanent or player, so it is
    not offered, and a cast naming it is refused with Radiate still in hand
    (CR 601.2c). A Lightning Bolt beside it is the one offered."""
    game = _w1g6_radiate_table(
        set_pool, catalog_by_name, ["Grizzly Bears"], [], ["Lightning Bolt", "Counterspell"],
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    spec = game.cast_target_spec(0, set_pool("TOR")["Radiate"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Lightning Bolt"]
    refused = game.cast_from_hand(0, "Radiate", target_stack_index=1)
    assert not refused.supported
    assert "Radiate" in [c.name for c in game.players[0].hand]

def test_w1g6_alter_reality_rewrites_a_permanent_s_colour_word(set_pool, catalog_by_name):
    """"Change the text of target spell or permanent by replacing all
    instances of one color word with another." On a Black Knight, white
    becomes black: the Knight's text reads "protection from black", and a
    black Terror can no longer target it while a white Swords to Plowshares
    can. Flashed back for {1}{U}, the same, and the card is exiled.

    The *spell* half ("target spell") is not offered: ROADMAP's "Text changes
    aimed at a spell" (Sleight of Mind, Magical Hack, Crystal Spray) is this
    card's too."""
    alter = set_pool("TOR")["Alter Reality"]
    for zone in ("hand", "graveyard"):
        knight = _w1g6_nosick(_W1G6Permanent(card=catalog_by_name["Black Knight"]))
        me = _W1G6PlayerState(name="P1")
        getattr(me, zone).append(alter)
        game = _W1G6Game(players=[me, _W1G6PlayerState(name="P2", battlefield=[knight])])
        game.enforce_mana_costs = False
        assert game.cast_from_hand(
            0, "Alter Reality", target_permanent_ids=[knight.permanent_id],
            target_player_index=1, old_color="W", new_color="B", from_zone=zone,
        ).supported
        _w1g6_resolve_stack(game)
        assert "Protection from black" in knight.effective_card.oracle_text
        assert "white" not in knight.effective_card.oracle_text.lower()
        terror = game.cast_target_spec(0, catalog_by_name["Terror"])
        assert terror["valid_targets"] == [], "black Terror vs protection from black"
        swords = game.cast_target_spec(0, catalog_by_name["Swords to Plowshares"])
        assert [entry["name"] for entry in swords["valid_targets"]] == ["Black Knight"]
        where = "exile" if zone == "graveyard" else "graveyard"
        assert "Alter Reality" in [c.name for c in getattr(game.players[0], where)]


def test_w1g6_accelerate_gives_haste_and_draws(set_pool, catalog_by_name):
    """"Target creature gains haste until end of turn. Draw a card." A
    creature that came under its controller's control this turn can attack."""
    bears = _W1G6Permanent(card=catalog_by_name["Grizzly Bears"])
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", hand=[set_pool("TOR")["Accelerate"]], battlefield=[bears],
                         library=[catalog_by_name["Island"]] * 2),
        _W1G6PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    bears.metadata["summoning_sickness_turn"] = game.turn
    assert game._is_summoning_sick(bears)
    assert game.cast_from_hand(
        0, "Accelerate", target_permanent_ids=[bears.permanent_id], target_player_index=0,
    ).supported
    _w1g6_resolve_stack(game)
    assert not game._is_summoning_sick(bears)
    assert [c.name for c in game.players[0].hand] == ["Island"]


def test_w1g6_cabal_ritual_adds_five_with_threshold(set_pool, catalog_by_name):
    """"Add {B}{B}{B}. Threshold -- Add {B}{B}{B}{B}{B} instead if there are
    seven or more cards in your graveyard." Paid {1}{B}, it leaves three black
    with six cards in the graveyard and five with seven."""
    for graveyard, black in ((6, 3), (7, 5)):
        game = _W1G6Game(players=[
            _W1G6PlayerState(name="P1", hand=[set_pool("TOR")["Cabal Ritual"]],
                             graveyard=[catalog_by_name["Island"]] * graveyard),
            _W1G6PlayerState(name="P2"),
        ])
        game.enforce_mana_costs = True
        game.players[0].mana_pool.update({"B": 1, "C": 1})
        assert game.cast_from_hand(0, "Cabal Ritual").supported
        _w1g6_resolve_stack(game)
        assert game.players[0].mana_pool["B"] == black, graveyard

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import (
    _damage_dealt as _w1g7_damage_dealt, _nosick as _w1g7_nosick,
    resolve_stack as _w1g7_resolve_stack,
)


def _w1g7_equal_treatment_board(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    giant = _w1g7_nosick(_w1g7_Permanent(card=lea["Hill Giant"]))
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", hand=[tor["Equal Treatment"], lea["Lightning Bolt"]],
            library=[lea["Forest"]] * 3,
        ),
        _w1g7_PlayerState(name="P1", battlefield=[giant]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    assert game.cast_from_hand(0, "Equal Treatment").supported
    _w1g7_resolve_stack(game)
    return game, giant


def test_w1g7_equal_treatment_makes_every_damage_event_two(set_pool):
    """"If any source would deal 1 or more damage to a permanent or player this
    turn, it deals 2 damage to that permanent or player instead. Draw a card."
    A Bolt to the face deals 2; 7 to a player and 1 to a creature are both 2
    (CR 120.4b, the damage dealt); the card is drawn."""
    game, giant = _w1g7_equal_treatment_board(set_pool)
    assert [c.name for c in game.players[0].hand] == ["Lightning Bolt", "Forest"]
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g7_resolve_stack(game)
    assert game.players[1].life == 18
    assert "3 damage becomes 2 (Equal Treatment)" in game.log
    assert _w1g7_damage_dealt(game, game.players[1], 7) == 2
    assert _w1g7_damage_dealt(game, giant, 1) == 2
    assert _w1g7_damage_dealt(game, giant, 1, combat=True) == 2


def test_w1g7_equal_treatment_ends_with_the_turn(set_pool):
    """"This turn": the record is on its caster's seat and the cleanup step's
    one sweep ends it (CR 514.2)."""
    game, giant = _w1g7_equal_treatment_board(set_pool)
    game.resolve_cleanup_step(0)
    assert _w1g7_damage_dealt(game, game.players[1], 7) == 7
    assert _w1g7_damage_dealt(game, giant, 1) == 1


def test_w1g7_equal_treatment_and_a_shield_contend_by_cr_616(set_pool):
    """One contention set with the prevention shields (CR 616.1): by default
    the 2 is set first, so Hypochondria's "prevent the next 3" absorbs all of
    a 5 — and its last point still stops a later 1, which Equal Treatment has
    made a 2, to 1."""
    game, _ = _w1g7_equal_treatment_board(set_pool)
    target = game.players[1]
    game.players[1].battlefield.append(
        _w1g7_Permanent(card=set_pool("TOR")["Hypochondria"])
    )
    assert game.activate_permanent_ability(
        1, "Hypochondria", target_player_index=1, permanent_index=1,
        ability_index=1,
    ).supported
    _w1g7_resolve_stack(game)
    assert _w1g7_damage_dealt(game, target, 5) == 0
    assert _w1g7_damage_dealt(game, target, 1) == 1
    assert _w1g7_damage_dealt(game, target, 1) == 2


def _w1g7_plagiarize_board(set_pool, *, p0=("Plagiarize",), p1=(), p1_library=5):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", hand=[tor[n] for n in p0], library=[lea["Forest"]] * 5,
        ),
        _w1g7_PlayerState(
            name="P1", hand=[tor[n] for n in p1],
            library=[lea["Island"]] * p1_library,
        ),
    ])
    game.enforce_mana_costs = False
    return game


def _w1g7_hands(game):
    return [[c.name for c in player.hand] for player in game.players]


def test_w1g7_plagiarize_gives_each_of_a_players_draws_to_its_caster(set_pool):
    """"Until end of turn, if target player would draw a card, instead that
    player skips that draw and you draw a card." Two draws by P1 are two
    replaced draws (CR 121.2): P0 draws both, P1 none."""
    game = _w1g7_plagiarize_board(set_pool)
    assert game.cast_from_hand(0, "Plagiarize", target_player_index=1).supported
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[1], 2)
    assert _w1g7_hands(game) == [["Forest", "Forest"], []]
    assert [len(p.library) for p in game.players] == [3, 5]
    assert game.log.count("P1 skips a draw and P0 draws instead (Plagiarize)") == 2


def test_w1g7_two_plagiarizes_cast_at_each_other_cancel_out(set_pool):
    """The 2007-07-15 ruling: "the two spells effectively cancel each other
    out". P1's draw goes to P0, whose substitute draw the second Plagiarize
    hands back to P1 — and that one has been through both (CR 614.5)."""
    game = _w1g7_plagiarize_board(set_pool, p1=("Plagiarize",))
    game.cast_from_hand(0, "Plagiarize", target_player_index=1)
    _w1g7_resolve_stack(game)
    game.cast_from_hand(1, "Plagiarize", target_player_index=0)
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[1], 1)
    assert _w1g7_hands(game) == [[], ["Island"]]
    game._draw_with_replacements(game.players[0], 1)
    assert _w1g7_hands(game) == [["Forest"], ["Island"]]


def test_w1g7_plagiarize_aimed_at_its_caster_does_nothing(set_pool):
    """The 2004-10-04 ruling: no loop, because the draw it makes is the one it
    may not replace (CR 614.5)."""
    game = _w1g7_plagiarize_board(set_pool)
    game.cast_from_hand(0, "Plagiarize", target_player_index=0)
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[0], 1)
    assert _w1g7_hands(game) == [["Forest"], []]


def test_w1g7_plagiarize_spares_an_empty_library_until_cleanup(set_pool):
    """The 2007-07-15 ruling on an empty library: the target's draw is replaced,
    so they never draw from it and do not lose (CR 704.5b). After the cleanup
    sweep the next draw is their own, and it loses them the game."""
    game = _w1g7_plagiarize_board(set_pool, p1_library=0)
    game.cast_from_hand(0, "Plagiarize", target_player_index=1)
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[1], 1)
    game.check_state_based_actions()
    assert not game.players[1].lost
    assert _w1g7_hands(game) == [["Forest"], []]
    game.resolve_cleanup_step(0)
    game._draw_with_replacements(game.players[1], 1)
    game.check_state_based_actions()
    assert game.players[1].lost


def test_w1g7_plagiarize_takes_the_draw_step_draw(set_pool):
    """A turn-based draw is a draw (CR 504.1): cast in P1's upkeep, it takes
    P1's draw-step card."""
    game = _w1g7_plagiarize_board(set_pool)
    game.active_player_index = 1
    game._set_phase_and_step("beginning", "upkeep")
    assert game.cast_from_hand(0, "Plagiarize", target_player_index=1).supported
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[1], 1, turn_based=True)
    assert _w1g7_hands(game) == [["Forest"], []]


def _w1g7_spirit_flare_board(set_pool, *, from_graveyard=False):
    """Seat 1's Gray Ogre attacking seat 0, who holds Spirit Flare and an
    untapped Hill Giant (3 power)."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    flare = tor["Spirit Flare"]
    giant = _w1g7_nosick(_w1g7_Permanent(card=lea["Hill Giant"]))
    ogre = _w1g7_nosick(_w1g7_Permanent(card=lea["Gray Ogre"]))
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", battlefield=[giant],
            hand=[] if from_graveyard else [flare],
            graveyard=[flare] if from_graveyard else [],
        ),
        _w1g7_PlayerState(name="P1", battlefield=[ogre]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why
    return game, flare, giant, ogre


def _w1g7_flare_roles(giant, ogre):
    return [{"permanent_id": giant.permanent_id}, {"permanent_id": ogre.permanent_id}]


def test_w1g7_spirit_flare_bites_with_the_creature_it_tapped(set_pool):
    """"Tap target untapped creature you control. If you do, it deals damage
    equal to its power to target attacking or blocking creature an opponent
    controls." "It" is the tapped Giant — a spell has no source to bite with,
    which is what the card did before: tapped its creature and dealt nothing."""
    game, _, giant, ogre = _w1g7_spirit_flare_board(set_pool)
    spec = game.cast_target_spec(0, set_pool("TOR")["Spirit Flare"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Hill Giant"]
    assert [entry["name"] for entry in spec["valid_targets"][0]["next"]] == ["Gray Ogre"]
    assert game.cast_from_hand(
        0, "Spirit Flare", target_role_refs=_w1g7_flare_roles(giant, ogre),
    ).supported
    _w1g7_resolve_stack(game)
    assert giant.tapped
    assert "Hill Giant deals 3 damage to Gray Ogre" in game.log
    assert ogre not in game.players[1].battlefield


def test_w1g7_spirit_flare_does_nothing_if_its_creature_is_tapped_in_response(set_pool):
    """"If you do": the Giant tapped in response is no longer "untapped" — an
    illegal target as the spell resolves (CR 608.2b) — so it is not tapped by
    the spell and deals no damage (the 2004-10-04 ruling: "If either target is
    illegal when the spell resolves, it will do no damage")."""
    game, _, giant, ogre = _w1g7_spirit_flare_board(set_pool)
    assert game.queue_from_hand(
        0, "Spirit Flare", target_role_refs=_w1g7_flare_roles(giant, ogre),
    ).supported
    game.become_tapped(giant)
    _w1g7_resolve_stack(game)
    assert ogre in game.players[1].battlefield and ogre.damage_marked == 0
    assert not any("deals 3 damage" in line for line in game.log)


def test_w1g7_spirit_flare_flashback_pays_mana_and_three_life(set_pool):
    """"Flashback—{1}{W}, Pay 3 life." From the graveyard for exactly that, the
    same bite, and the card is exiled."""
    game, flare, giant, ogre = _w1g7_spirit_flare_board(set_pool, from_graveyard=True)
    game.enforce_mana_costs = True
    game.players[0].mana_pool["W"] = 2
    assert game.cast_from_hand(
        0, "Spirit Flare", from_zone="graveyard",
        target_role_refs=_w1g7_flare_roles(giant, ogre),
    ).supported
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 17
    assert game.players[0].exile == [flare]
    assert ogre not in game.players[1].battlefield


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
