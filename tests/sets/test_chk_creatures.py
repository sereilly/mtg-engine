"""Champions of Kamigawa creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
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
import pytest as _w1g3_pytest

from engine import Game as _w1g3_Game
from engine.models import CardDefinition as _w1g3_CardDefinition
from engine.models import Permanent as _w1g3_Permanent
from engine.models import PlayerState as _w1g3_PlayerState
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.soulshift import soulshift_count as _w1g3_soulshift_count

from tests.helpers import _nosick as _w1g3_nosick
from tests.helpers import drive_combat as _w1g3_drive_combat
from tests.helpers import settle as _w1g3_settle

#: Every Champions of Kamigawa creature printing "Soulshift N" — W1G3's eleven
#: and W1G4's Thief of Hope (whose cast trigger is W1G4's; the integrator
#: writes its whole-card test).
_W1G3_SOULSHIFT = (
    "Burr Grafter", "Gibbering Kami", "Hundred-Talon Kami", "Kami of Lunacy",
    "Kami of the Palace Fields", "Rootrunner", "Scuttling Death",
    "Thousand-legged Kami", "Venerable Kumo", "Vine Kami", "He Who Hungers",
)


def _w1g3_card(name: str, cost: int, type_line: str = "Creature — Spirit",
               text: str = "", power: str = "1", toughness: str = "1"):
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power=power, toughness=toughness)
    return _w1g3_CardDefinition(
        name=name, mana_cost="{%d}" % cost if cost else "", cmc=float(cost),
        type_line=type_line, oracle_text=text, colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw=raw,
    )


def _w1g3_table(mine=(), theirs=(), *, hand=(), graveyard=(), interactive=()):
    land = _w1g3_card("Filler Land", 0, "Land")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P1", battlefield=[_w1g3_nosick(_w1g3_Permanent(card=c)) for c in mine],
            hand=list(hand), graveyard=list(graveyard), library=[land] * 10,
        ),
        _w1g3_PlayerState(
            name="P2", battlefield=[_w1g3_nosick(_w1g3_Permanent(card=c)) for c in theirs],
            library=[land] * 10,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._settle()
    return game


def _w1g3_names(cards) -> list[str]:
    return [card.name for card in cards]


def _w1g3_on_field(game, seat: int, name: str):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def test_w1g3_every_soulshift_creature_prints_one_readable_soulshift_line(set_pool):
    pool = set_pool("CHK")
    printed = sorted(
        name for name, card in pool.items()
        if any(_w1g3_soulshift_count(line) for line in (card.oracle_text or "").split("\n"))
    )
    assert set(_W1G3_SOULSHIFT) <= set(printed)
    assert "Thief of Hope" in printed


@_w1g3_pytest.mark.parametrize("name", _W1G3_SOULSHIFT)
def test_w1g3_soulshift_returns_a_spirit_at_its_n_and_not_one_above(set_pool, name):
    """CR 702.46a, on every printed soulshift creature: destroyed by Rend
    Spirit, it returns the Spirit card of mana value N from its graveyard and
    leaves the one of mana value N + 1 (and a non-Spirit of mana value N)."""
    pool = set_pool("CHK")
    card = pool[name]
    assert _w1g3_compile(card).supported, name
    (n,) = [_w1g3_soulshift_count(line) for line in card.oracle_text.split("\n")
            if _w1g3_soulshift_count(line)]
    at_n = _w1g3_card(f"Spirit at {n}", n)
    above = _w1g3_card(f"Spirit at {n + 1}", n + 1)
    bear = _w1g3_card(f"Bear at {n}", n, "Creature — Bear")
    game = _w1g3_table(
        mine=[card], hand=[pool["Rend Spirit"]], graveyard=[above, bear, at_n],
    )
    victim = _w1g3_on_field(game, 0, name)
    assert game.cast_from_hand(0, "Rend Spirit", target_permanent_ids=[victim.permanent_id]).supported
    _w1g3_settle(game)
    assert _w1g3_names(game.players[0].hand) == [f"Spirit at {n}"], game.log[-8:]
    graveyard = _w1g3_names(game.players[0].graveyard)
    assert name in graveyard and f"Spirit at {n + 1}" in graveyard and f"Bear at {n}" in graveyard


def test_w1g3_burr_grafter_sacrificed_pumps_and_its_soulshift_resolves_first(set_pool):
    """Sacrifice is a cost, so the soulshift trigger goes on the stack above
    the pump (CR 603.3) and resolves first; an interactive seat is offered only
    the Spirit cards of mana value 3 or less and names the one it wants."""
    pool = set_pool("CHK")
    bears = _w1g3_card("Target Bear", 2, "Creature — Bear", power="2", toughness="2")
    game = _w1g3_table(
        mine=[pool["Burr Grafter"]], theirs=[bears],
        graveyard=[pool["Kami of Ancient Law"], pool["Kami of Lunacy"], pool["Hana Kami"]],
        interactive=(0,),
    )
    bear = _w1g3_on_field(game, 1, "Target Bear")
    assert game.activate_permanent_ability(
        0, "Burr Grafter", target_permanent_ids=[bear.permanent_id]
    ).supported
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "trigger_target", game.log[-6:]
    assert sorted(t["name"] for t in asked.data["targets"]) == ["Hana Kami", "Kami of Ancient Law"]
    hana = next(t for t in asked.data["targets"] if t["name"] == "Hana Kami")
    assert game.confirm_trigger_target(0, seat=hana["seat"], graveyard_index=hana["graveyard_index"])
    _w1g3_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True),
    })
    assert _w1g3_names(game.players[0].hand) == ["Hana Kami"]
    assert bear.effective_power == 4
    returned = next(i for i, line in enumerate(game.log) if "Returned Hana Kami" in line)
    pumped = next(i for i, line in enumerate(game.log) if "+2/+2" in line)
    assert returned < pumped


def test_w1g3_rootrunner_tops_a_land_and_soulshifts(set_pool):
    pool = set_pool("CHK")
    game = _w1g3_table(
        mine=[pool["Rootrunner"]], theirs=[_w1g3_card("Their Land", 0, "Land")],
        graveyard=[pool["Kami of Ancient Law"]],
    )
    land = _w1g3_on_field(game, 1, "Their Land")
    assert game.activate_permanent_ability(
        0, "Rootrunner", target_permanent_ids=[land.permanent_id]
    ).supported
    _w1g3_settle(game)
    assert game.players[1].library[0].name == "Their Land"
    assert _w1g3_names(game.players[0].hand) == ["Kami of Ancient Law"]


def test_w1g3_scuttling_death_shrinks_and_soulshifts(set_pool):
    pool = set_pool("CHK")
    elf = _w1g3_card("Small Elf", 1, "Creature — Elf", power="1", toughness="1")
    game = _w1g3_table(
        mine=[pool["Scuttling Death"]], theirs=[elf],
        graveyard=[pool["Kami of Twisted Reflection"]],
    )
    target = _w1g3_on_field(game, 1, "Small Elf")
    assert game.activate_permanent_ability(
        0, "Scuttling Death", target_permanent_ids=[target.permanent_id]
    ).supported
    _w1g3_settle(game)
    assert "Small Elf" in _w1g3_names(game.players[1].graveyard)
    assert _w1g3_names(game.players[0].hand) == ["Kami of Twisted Reflection"]


def test_w1g3_thousand_legged_kami_dies_in_combat_and_returns_a_seven_drop_spirit(set_pool):
    """A combat death, the other road to a graveyard: blocked by a creature
    that kills it, it returns Kami of Lunacy (mana value 6, at most 7)."""
    pool = set_pool("CHK")
    wall = _w1g3_card("Big Wall", 4, "Creature — Wall", power="7", toughness="7")
    game = _w1g3_table(
        mine=[pool["Thousand-legged Kami"]], theirs=[wall],
        graveyard=[pool["Kami of Lunacy"]],
    )
    from tests.helpers import declare_attack

    # The only creature on each side: blocker slot 0 blocks attacker slot 0.
    declare_attack(game, 0, blocks={0: 0})
    _w1g3_drive_combat(game)
    _w1g3_settle(game)
    assert "Thousand-legged Kami" in _w1g3_names(game.players[0].graveyard)
    assert _w1g3_names(game.players[0].hand) == ["Kami of Lunacy"]

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================
