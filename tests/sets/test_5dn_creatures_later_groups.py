"""Fifth Dawn creatures (legendary ones too) — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool):
    """Two seats with Plains libraries on seat 0's first main phase."""
    plains = set_pool("LEA")["Plains"]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name=f"P{seat}", library=[plains] * 20) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def _w1g6_put(game, seat, card):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g6_settle(game)
    return permanent


def _w1g6_granted(permanent):
    return [
        ability.source_line.lower()
        for ability in _w1g6_compile(permanent.effective_card).triggered_abilities
    ]


def test_w1g6_mephidross_vampire_makes_its_controllers_creatures_vampires(set_pool):
    """'Each creature you control is a Vampire in addition to its other
    creature types and has "Whenever this creature deals damage to a creature,
    put a +1/+1 counter on this creature."' Layer 4 and layer 6 over its
    controller's creatures, the Vampire itself included and nobody else's;
    the granted trigger fires on any damage to a creature, not just combat
    damage (ruling 2004-12-01) — a Prodigal Sorcerer's ping and a combat both
    grow the dealer — and an opponent's creature dealing damage grows
    nothing. The grant ends with the Vampire (CR 611.3b)."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g6_table(set_pool)
    vampire = _w1g6_put(game, 0, fdn["Mephidross Vampire"])
    sorcerer = _w1g6_put(game, 0, lea["Prodigal Sorcerer"])
    bears = _w1g6_put(game, 0, lea["Grizzly Bears"])
    giant = _w1g6_put(game, 1, lea["Hill Giant"])
    wall = _w1g6_put(game, 1, lea["Wall of Stone"])
    quote = "whenever this creature deals damage to a creature, put a +1/+1 counter on this creature."
    for mine in (vampire, sorcerer, bears):
        assert mine.has_type("vampire") and quote in _w1g6_granted(mine)
    assert bears.has_type("bear")
    for theirs in (giant, wall):
        assert not theirs.has_type("vampire") and quote not in _w1g6_granted(theirs)

    result = game.activate_permanent_ability(
        0, "Prodigal Sorcerer", permanent_index=game.battlefield_index_of(sorcerer),
        target_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result
    _w1g6_settle(game)
    assert (sorcerer.effective_power, sorcerer.effective_toughness) == (2, 2)

    # Bears attack into the Wall: the Bears deal 2 to the Wall and grow; the
    # Wall deals nothing (0 power).
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(bears)], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {game.battlefield_index_of(wall): game.battlefield_index_of(bears)})
    assert ok, why
    _w1g6_drive_combat(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    assert not wall.effective_power

    game.remove_from_battlefield(vampire)
    _w1g6_settle(game)
    assert not bears.has_type("vampire") and quote not in _w1g6_granted(bears)


def test_w1g6_relentless_rats_counts_the_others_and_lifts_the_four_of_rule(set_pool):
    """'This creature gets +1/+1 for each other creature on the battlefield
    named Relentless Rats. A deck can have any number of cards named
    Relentless Rats.' Every Rat on the battlefield counts, whoever controls it
    (and not itself); the deck rule is CR 100.2a's four-of limit lifted for
    the card's own name, enforced at deck construction by the reader that
    claims the line — so twenty Rats is a legal deck, and the line is a claim
    the compiler sees rather than a sentence it drops."""
    from engine.deck_construction import any_number_line
    from web.deck_legality import validate_deck

    fdn = set_pool("5DN")
    rats_card = fdn["Relentless Rats"]
    assert _w1g6_compile(rats_card).supported
    assert any_number_line("A deck can have any number of cards named Relentless Rats.", "Relentless Rats")
    assert not any_number_line("A deck can have any number of cards named Relentless Rats.", "Shadowborn Apostle")
    game = _w1g6_table(set_pool)
    first = _w1g6_put(game, 0, rats_card)
    assert (first.effective_power, first.effective_toughness) == (2, 2)
    second = _w1g6_put(game, 1, rats_card)
    third = _w1g6_put(game, 0, rats_card)
    for rat in (first, second, third):
        assert (rat.effective_power, rat.effective_toughness) == (4, 4)
    game.remove_from_battlefield(second)
    _w1g6_settle(game)
    assert (first.effective_power, first.effective_toughness) == (3, 3)

    catalog = {"relentless rats": rats_card.raw}
    verdict = validate_deck([{"name": "Relentless Rats", "count": 20}], "legacy", catalog)
    assert verdict["illegal_names"] == [], verdict

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
