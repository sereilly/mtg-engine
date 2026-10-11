"""Apocalypse creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.card_loader import manifest_set_path as _w1g6_manifest_set_path
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import _damage_dealt as _w1g6_damage_dealt
from tests.helpers import resolve_stack as _w1g6_resolve_stack

#: Where the furniture these tests stand beside Apocalypse's creatures is
#: printed. Apocalypse first, so a name it prints is always its own card.
_W1G6_SETS = ("APC", "LEA", "LEG")

_W1G6_BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}


def _w1g6_find(set_pool, name):
    for w1g6_code in _W1G6_SETS:
        w1g6_found = set_pool(w1g6_code).get(name)
        if w1g6_found is not None:
            return w1g6_found
    raise KeyError(name)  # _w1g6_find


def _w1g6_table(set_pool, mine=(), theirs=(), hand=(), their_hand=(), enforce=False,
                interactive=False, active=0):
    """A two-seat table in *active*'s first main phase, with *mine* / *theirs*
    on the battlefield and unsick, and *hand* / *their_hand* in hand."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="W1G6-A", hand=[_w1g6_find(set_pool, n) for n in hand]),
        _W1G6PlayerState(name="W1G6-B", hand=[_w1g6_find(set_pool, n) for n in their_hand]),
    ])
    w1g6_game.enforce_mana_costs = enforce
    w1g6_game.active_player_index = active
    w1g6_game.current_turn_phase = w1g6_game.current_step = "precombat_main"
    if interactive:
        w1g6_game.interactive_seats.add(0)
    w1g6_rows = []
    for w1g6_seat, w1g6_names in enumerate((mine, theirs)):
        w1g6_row = []
        for w1g6_name in w1g6_names:
            w1g6_perm = _W1G6Permanent(card=_w1g6_find(set_pool, w1g6_name))
            w1g6_game._put_permanent_onto_battlefield(w1g6_seat, w1g6_perm, None)
            w1g6_perm.metadata["summoning_sickness_turn"] = -99
            w1g6_row.append(w1g6_perm)
        w1g6_rows.append(w1g6_row)
    return w1g6_game, w1g6_rows[0], w1g6_rows[1]  # _w1g6_table


def _w1g6_upkeep(game, seat=0):
    """Run *seat*'s upkeep step and leave what triggered on the stack; returns
    the names of the sources there."""
    game.active_player_index = seat
    game.resolve_upkeep(seat, defer_priority=True)
    return [w1g6_item.card.name for w1g6_item in game.stack]  # _w1g6_upkeep


def _w1g6_tap_for(game, land, colour, seat=0):
    """Tap *land* for one mana of *colour* through the real mana ability."""
    w1g6_tapped = game.tap_land_for_mana(
        seat, land.card.name, colour, permanent_id=land.permanent_id,
    )
    assert w1g6_tapped, f"{land.card.name} did not tap for {colour}"
    return w1g6_tapped  # _w1g6_tap_for


def _w1g6_offered(game, permanent, ability_index):
    """What the activation picker offers for one ability of *permanent*, as
    card names and ``player<seat>`` entries."""
    w1g6_spec = game.activation_target_spec(
        0, game.battlefield_index_of(permanent), ability_index,
    )
    w1g6_names = []
    for w1g6_entry in w1g6_spec.get("valid_targets", []):
        if w1g6_entry.get("kind") == "permanent":
            w1g6_names.append(
                game.permanent_at(w1g6_entry["seat"], w1g6_entry["index"]).card.name
            )
        else:
            w1g6_names.append(f"player{w1g6_entry.get('seat')}")
    return w1g6_names  # _w1g6_offered


# Gerrard Capashen ------------------------------------------------------------


def test_w1g6_gerrard_capashen_gains_a_life_for_each_card_in_an_opponents_hand(set_pool):
    """"At the beginning of your upkeep, you gain 1 life for each card in
    target opponent's hand." The opponent is a target, chosen as the trigger
    goes on the stack, and only an opponent is offered; the count is of that
    hand, not of Gerrard's controller's."""
    program = _w1g6_compile(set_pool("APC")["Gerrard Capashen"])
    assert program.supported, program.reason

    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=["Gerrard Capashen"], hand=["Forest"] * 5,
        their_hand=["Forest"] * 3, interactive=True,
    )
    assert _w1g6_upkeep(game) == ["Gerrard Capashen"]
    (prompt,) = game.pending_choices
    assert [(entry["kind"], entry["seat"]) for entry in prompt.data["targets"]] == [
        ("player", 1),
    ]
    assert not game.confirm_trigger_target(0, seat=0)
    assert game.confirm_trigger_target(0, seat=1)
    _w1g6_resolve_stack(game)

    assert [player.life for player in game.players] == [23, 20]
    assert "W1G6-A gained 3 life from Gerrard Capashen (20 -> 23)" in game.log

    # Not on the opponent's upkeep, and an empty hand is worth nothing.
    assert _w1g6_upkeep(game, seat=1) == []
    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Gerrard Capashen"], hand=["Forest"])
    assert _w1g6_upkeep(game) == ["Gerrard Capashen"]
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]


def test_w1g6_gerrard_capashen_taps_only_while_he_is_attacking(set_pool):
    """"{3}{W}: Tap target creature. Activate only if Gerrard Capashen is
    attacking." The clause names the card (CR 201.5) and is enforced: refused
    at home with nothing spent, legal once he is declared as an attacker, and
    the mana is charged."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Gerrard Capashen"] + ["Plains"] * 4,
        theirs=["Hill Giant", "Grizzly Bears"], enforce=True,
    )
    gerrard, giant = mine[0], theirs[0]
    for land in mine[1:]:
        _w1g6_tap_for(game, land, "W")

    refused = game.activate_permanent_ability(
        0, "Gerrard Capashen", target_permanent_ids=[giant.permanent_id], ability_index=0,
    )
    assert not refused.supported
    assert refused.details == "Gerrard Capashen: this creature is not attacking"
    assert not giant.tapped and sum(game.players[0].mana_pool.values()) == 4

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(gerrard)])[0]
    assert gerrard.attacking
    # The picker offers creatures — every one, his own side's too — and a land
    # named anyway is refused before the cost is paid.
    assert _w1g6_offered(game, gerrard, 0) == [
        "Gerrard Capashen", "Hill Giant", "Grizzly Bears",
    ]
    wrong = game.activate_permanent_ability(
        0, "Gerrard Capashen", target_permanent_ids=[mine[1].permanent_id], ability_index=0,
    )
    assert not wrong.supported and sum(game.players[0].mana_pool.values()) == 4

    tapped = game.activate_permanent_ability(
        0, "Gerrard Capashen", target_permanent_ids=[giant.permanent_id], ability_index=0,
    )
    assert tapped.supported, tapped.details
    _w1g6_resolve_stack(game)
    assert giant.tapped and not theirs[1].tapped
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g6_gerrard_capashens_clause_is_read_as_a_self_reference_only():
    """The row reads "this <noun> is attacking" — the card's own name collapsed
    (CR 201.5) — so the clause is a restriction with the name in hand and an
    unread sentence without it. Some *other* creature's name is never the
    subject: read as one, the clause would be admitted and then ask about the
    wrong permanent."""
    from engine.activation_restrictions import activation_restriction_line

    clause = "Activate only if Gerrard Capashen is attacking."
    assert activation_restriction_line(clause, "Gerrard Capashen")
    assert not activation_restriction_line(clause)
    assert not activation_restriction_line(clause, "Dwarven Patrol")
    assert activation_restriction_line("Activate only if this creature is attacking.")
    assert not activation_restriction_line("Activate only if this creature is sleeping.")


def test_w1g6_gerrard_capashens_ability_costs_three_and_a_white(set_pool):
    """Attacking, with nothing in the pool: refused for the mana, and the
    Giant stays untapped."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Gerrard Capashen"], theirs=["Hill Giant"], enforce=True,
    )
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0])[0]

    unpaid = game.activate_permanent_ability(
        0, "Gerrard Capashen", target_permanent_ids=[theirs[0].permanent_id], ability_index=0,
    )

    assert not unpaid.supported and "insufficient mana" in unpaid.details
    assert not theirs[0].tapped


# Dwarven Patrol ---------------------------------------------------------------


def test_w1g6_dwarven_patrol_stays_tapped_through_its_controllers_untap_step(set_pool):
    """"This creature doesn't untap during your untap step." The Bears beside
    it do."""
    game, mine, _theirs = _w1g6_table(set_pool, mine=["Dwarven Patrol", "Grizzly Bears"])
    for permanent in mine:
        permanent.tapped = True

    game.resolve_untap_step(0)

    assert [(permanent.card.name, permanent.tapped) for permanent in mine] == [
        ("Dwarven Patrol", True), ("Grizzly Bears", False),
    ]


@_w1g6_pytest.mark.parametrize("spell, untaps", [
    ("Grizzly Bears", True),               # green
    ("Giant Growth", True),                # an instant is a spell too
    ("Sol Ring", True),                    # colourless is not red (CR 105.2c)
    ("Goblin King", False),                # red
    ("Lightning Bolt", False),
    ("Jerrard of the Closed Fist", False), # red and green is red (CR 105.2b)
])
def test_w1g6_dwarven_patrol_untaps_when_its_controller_casts_a_nonred_spell(
    set_pool, spell, untaps,
):
    """"Whenever you cast a nonred spell, untap this creature." A trigger on
    the cast (it resolves before the spell does), narrowed by what the spell's
    colours are *not*."""
    program = _w1g6_compile(set_pool("APC")["Dwarven Patrol"])
    assert program.supported, program.reason

    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Dwarven Patrol"], theirs=["Hill Giant"], hand=[spell],
    )
    patrol = mine[0]
    patrol.tapped = True
    aimed = {}
    if spell == "Giant Growth":
        aimed = {"target_permanent_ids": [patrol.permanent_id]}
    elif spell == "Lightning Bolt":
        aimed = {"target_player_index": 1}

    cast = game.queue_from_hand(0, spell, **aimed)
    assert cast.supported, cast.details
    on_stack = [item.card.name for item in game.stack]
    assert on_stack == ([spell, "Dwarven Patrol"] if untaps else [spell])
    _w1g6_resolve_stack(game)

    assert patrol.tapped is not untaps
    assert ("Dwarven Patrol untapped" in game.log) is untaps


def test_w1g6_dwarven_patrol_ignores_an_opponents_spell_and_a_land(set_pool):
    """"**You** cast": the opponent's green spell is not the trigger. And a
    land is played, not cast — "Remember that lands are not spells" (the card's
    ruling, 2004-10-04)."""
    game, mine, _theirs = _w1g6_table(
        set_pool, mine=["Dwarven Patrol"], their_hand=["Grizzly Bears"], active=1,
    )
    mine[0].tapped = True
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]
    _w1g6_resolve_stack(game)
    assert mine[0].tapped

    game, mine, _theirs = _w1g6_table(set_pool, mine=["Dwarven Patrol"], hand=["Forest"])
    mine[0].tapped = True
    assert game.cast_from_hand(0, "Forest").supported
    assert [p.card.name for p in game.controlled_by(0)] == ["Dwarven Patrol", "Forest"]
    assert mine[0].tapped and not game.stack


# Bog Gnarr, Glade Gnarr --------------------------------------------------------


@_w1g6_pytest.mark.parametrize("gnarr, base, colour_spell, other_spell", [
    ("Bog Gnarr", (2, 2), "Black Knight", "Grizzly Bears"),
    ("Glade Gnarr", (4, 4), "Prodigal Sorcerer", "Black Knight"),
])
def test_w1g6_a_gnarr_grows_when_any_player_casts_its_colour(
    set_pool, gnarr, base, colour_spell, other_spell,
):
    """"Whenever **a player** casts a black/blue spell, this creature gets
    +2/+2 until end of turn." Either seat's spell of that colour, no other
    colour's, and the bonus is gone at cleanup."""
    grown = (base[0] + 2, base[1] + 2)
    for caster in (0, 1):
        for spell, expected in ((colour_spell, grown), (other_spell, base)):
            hands = {"hand": [spell]} if caster == 0 else {"their_hand": [spell]}
            game, mine, _theirs = _w1g6_table(set_pool, mine=[gnarr], active=caster, **hands)
            assert game.queue_from_hand(caster, spell).supported
            _w1g6_resolve_stack(game)
            size = (mine[0].effective_power, mine[0].effective_toughness)
            assert size == expected, (gnarr, caster, spell)

    game, mine, _theirs = _w1g6_table(set_pool, mine=[gnarr], hand=[colour_spell] * 2)
    assert game.queue_from_hand(0, colour_spell).supported
    assert game.queue_from_hand(0, colour_spell).supported
    _w1g6_resolve_stack(game)
    # Each cast is its own trigger.
    assert (mine[0].effective_power, mine[0].effective_toughness) == (
        base[0] + 4, base[1] + 4,
    )
    game.resolve_cleanup_step(0)
    assert (mine[0].effective_power, mine[0].effective_toughness) == base


# Minotaur Tactician ------------------------------------------------------------


@_w1g6_pytest.mark.parametrize("beside, size", [
    ((), (1, 1)),
    (("White Knight",), (2, 2)),
    (("Prodigal Sorcerer",), (2, 2)),
    (("White Knight", "Prodigal Sorcerer"), (3, 3)),
    # One white-and-blue creature answers both lines.
    (("Tobias Andrion",), (3, 3)),
    # "A white **creature**": a white enchantment is not one.
    (("Circle of Protection: Red",), (1, 1)),
])
def test_w1g6_minotaur_tactician_counts_each_colour_of_creature_once(set_pool, beside, size):
    """Two static lines, one per colour, each +1/+1 "as long as you control" a
    creature of it — yours, so the opponent's white and blue creatures across
    the table add nothing. Haste is printed."""
    game, mine, _theirs = _w1g6_table(
        set_pool, mine=("Minotaur Tactician",) + beside,
        theirs=["White Knight", "Prodigal Sorcerer"],
    )
    tactician = mine[0]

    assert (tactician.effective_power, tactician.effective_toughness) == size
    assert game._has_keyword(tactician, "haste")


def test_w1g6_minotaur_tactician_shrinks_when_the_white_creature_leaves(set_pool):
    game, mine, _theirs = _w1g6_table(set_pool, mine=["Minotaur Tactician", "White Knight"])
    assert (mine[0].effective_power, mine[0].effective_toughness) == (2, 2)

    game.remove_from_battlefield(mine[1])
    game.check_state_based_actions()

    assert (mine[0].effective_power, mine[0].effective_toughness) == (1, 1)


# The Disciples ----------------------------------------------------------------

#: (card, ability index, the off-colour mana its cost asks for, what it does).
_W1G6_DISCIPLE_ABILITIES = [
    ("Ana Disciple", 0, "U", "flying"),
    ("Ana Disciple", 1, "B", "shrink"),
    ("Ceta Disciple", 0, "R", "grow"),
    ("Ceta Disciple", 1, "G", "mana"),
    ("Dega Disciple", 0, "B", "shrink"),
    ("Dega Disciple", 1, "R", "grow"),
    ("Necra Disciple", 0, "G", "mana"),
    ("Necra Disciple", 1, "W", "prevent"),
    ("Raka Disciple", 0, "W", "prevent"),
    ("Raka Disciple", 1, "U", "flying"),
]


@_w1g6_pytest.mark.parametrize("name, index, colour, effect", _W1G6_DISCIPLE_ABILITIES)
def test_w1g6_each_disciple_ability_is_paid_aimed_and_carried_out(
    set_pool, name, index, colour, effect,
):
    """Every Disciple prints two abilities, each costing one mana of an
    *enemy* colour and a tap. Each is refused with the mana unpaid, offers
    exactly what its sentence targets, does what it says to the creature named
    — the opponent's Hill Giant, not a bystander — and cannot be used again
    while the Disciple is tapped."""
    program = _w1g6_compile(set_pool("APC")[name])
    assert program.supported, program.reason

    game, mine, theirs = _w1g6_table(
        set_pool, mine=[name, _W1G6_BASICS[colour], "Grizzly Bears"],
        theirs=["Hill Giant"], enforce=True,
    )
    disciple, land, bears = mine
    giant = theirs[0]
    aimed = {"ability_index": index}
    if effect == "mana":
        aimed["mana_color"] = "W"
        assert _w1g6_offered(game, disciple, index) == []
    else:
        aimed["target_permanent_ids"] = [giant.permanent_id]
        creatures = [name, "Grizzly Bears", "Hill Giant"]
        assert _w1g6_offered(game, disciple, index) == (
            ["player0", "player1"] + creatures if effect == "prevent" else creatures
        )

    unpaid = game.activate_permanent_ability(0, name, **aimed)
    assert not unpaid.supported and "insufficient mana" in unpaid.details
    assert not disciple.tapped

    _w1g6_tap_for(game, land, colour)
    paid = game.activate_permanent_ability(0, name, **aimed)
    assert paid.supported, paid.details
    _w1g6_resolve_stack(game)
    assert disciple.tapped

    pool = {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}
    size = (giant.effective_power, giant.effective_toughness)
    untouched = (bears.effective_power, bears.effective_toughness) == (2, 2)
    if effect == "mana":
        # A mana ability: one mana of the colour asked for, the {G} spent.
        assert pool == {"W": 1}
    else:
        assert pool == {}
    if effect == "flying":
        assert game._has_keyword(giant, "flying") and not game._has_keyword(bears, "flying")
        game.resolve_cleanup_step(0)
        assert not game._has_keyword(giant, "flying")
    elif effect == "shrink":
        assert size == (1, 3) and untouched
        game.resolve_cleanup_step(0)
        assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    elif effect == "grow":
        assert size == (5, 3) and untouched
    elif effect == "prevent":
        # "Prevent the next 1 damage": one of the next three, and then spent.
        assert _w1g6_damage_dealt(game, giant, 3) == 2
        assert _w1g6_damage_dealt(game, giant, 3) == 3
        assert _w1g6_damage_dealt(game, bears, 1) == 1

    again = game.activate_permanent_ability(0, name, **aimed)
    assert not again.supported and "already tapped" in again.details


@_w1g6_pytest.mark.parametrize("name, index, colour", [
    ("Necra Disciple", 1, "W"), ("Raka Disciple", 0, "W"),
])
def test_w1g6_a_disciples_shield_may_be_put_on_a_player(set_pool, name, index, colour):
    """"…dealt to **any target**": a player's face is one."""
    game, mine, _theirs = _w1g6_table(
        set_pool, mine=[name, _W1G6_BASICS[colour]], enforce=True,
    )
    _w1g6_tap_for(game, mine[1], colour)

    shielded = game.activate_permanent_ability(
        0, name, ability_index=index, target_player_index=0,
    )
    assert shielded.supported, shielded.details
    _w1g6_resolve_stack(game)

    assert _w1g6_damage_dealt(game, game.players[0], 2) == 1
    assert _w1g6_damage_dealt(game, game.players[1], 2) == 2


@_w1g6_pytest.mark.parametrize("name, index, colour", [
    ("Ana Disciple", 0, "U"), ("Ceta Disciple", 0, "R"), ("Dega Disciple", 0, "B"),
])
def test_w1g6_a_disciple_refuses_a_target_its_sentence_does_not_name(
    set_pool, name, index, colour,
):
    """"Target **creature**": a land named anyway is refused at announcement
    with the mana still in the pool and the Disciple untapped."""
    game, mine, _theirs = _w1g6_table(
        set_pool, mine=[name, _W1G6_BASICS[colour], "Grizzly Bears"], enforce=True,
    )
    _w1g6_tap_for(game, mine[1], colour)

    refused = game.activate_permanent_ability(
        0, name, ability_index=index, target_permanent_ids=[mine[1].permanent_id],
    )

    assert not refused.supported
    assert not mine[0].tapped and game.players[0].mana_pool[colour] == 1
    bears = mine[2]
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert not game._has_keyword(bears, "flying")


# The simulator ------------------------------------------------------------------


@_w1g6_pytest.mark.slow
def test_w1g6_the_ai_plays_the_groups_cards_through_whole_games():
    """Six of the group's cards pinned into both decks of six simulated games.
    They are cast, their upkeep triggers go on the stack and resolve, nothing
    is refused and no step is left owing a prompt. (Apocalypse is a measured
    set, so other cards' unsupported casts are in the report; only these
    cards' lines are read. The floors are well under what the seed gives.)"""
    from engine.ai_simulator import run_ai_simulation

    names = [
        "Ceta Sanctuary", "Necra Sanctuary", "Raka Sanctuary",
        "Mask of Intolerance", "Dwarven Patrol", "Gerrard Capashen",
    ]
    report = run_ai_simulation(
        [_w1g6_manifest_set_path("APC", include_measured=True)],
        games=6, seed=4242, required_cards=names,
    )

    assert report.games_completed == 6
    cast = {
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    }
    assert len(cast) >= 4, sorted(cast)
    resolved = {
        name for name in names
        if any(f"{name} ability resolved" in line for line in report.log_lines)
    }
    assert len(resolved) >= 3, sorted(resolved)
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [
        issue.message for issue in report.issues
        if any(name in issue.message for name in names)
    ] == []
    w1g6_nothing_left_owing = not report.steps_left_owing
    assert w1g6_nothing_left_owing, report.steps_left_owing

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
