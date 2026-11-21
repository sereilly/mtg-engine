"""Champions of Kamigawa creatures (legendary ones too) — the later groups' sections.

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
from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, hand=(), mine=(), library=("Island",) * 12):
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card(n) for n in library]),
        _W1G9PlayerState(name="Bob", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    placed = []
    for name in mine:
        permanent = _W1G9Permanent(card=card(name))
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed


def test_w1g9_godo_fetches_an_equipment_as_it_enters(set_pool):
    """"When Godo enters, you may search your library for an Equipment card,
    put it onto the battlefield, then shuffle." Cast, the entry trigger finds
    Tenza among the lands and puts it onto the battlefield."""
    game, _mine = _w1g9_table(
        set_pool, hand=["Godo, Bandit Warlord"],
        library=("Island", "Tenza, Godo's Maul", "Island", "Island"),
    )
    assert game.cast_from_hand(0, "Godo, Bandit Warlord").supported
    _w1g9_settle(game)
    names = sorted(p.card.name for p in game.controlled_by(0))
    assert names == ["Godo, Bandit Warlord", "Tenza, Godo's Maul"]
    assert "Tenza, Godo's Maul" not in [c.name for c in game.players[0].library]


def test_w1g9_godo_untaps_samurai_and_adds_a_combat_only_on_its_first_attack(set_pool):
    """"Whenever Godo attacks for the first time each turn, untap it and all
    Samurai you control. After this phase, there is an additional combat
    phase." (CR 500.8; no extra main phase, the 2020-08-07 ruling.) Godo and a
    tapped Samurai untap, a tapped Bear does not, and the turn's second combat
    follows the first; Godo attacking again there sets nothing off."""
    game, mine = _w1g9_table(
        set_pool, mine=["Godo, Bandit Warlord", "Kitsune Blademaster", "Grizzly Bears"],
    )
    godo, blademaster, bears = mine
    blademaster.tapped = True
    bears.tapped = True
    alice, bob = game.players
    game._set_phase_and_step("combat", "declare_attackers")
    slot = [p.permanent_id for p in alice.battlefield].index(godo.permanent_id)
    ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
    assert ok, why
    _w1g9_settle(game)
    assert not godo.tapped and not blademaster.tapped and bears.tapped
    _w1g9_drive_combat(game)
    assert bob.life == 17
    assert game.current_turn_phase == "combat", "the additional combat phase"

    _w1g9_drive_combat(game, through="beginning_of_combat")
    assert game.current_step == "declare_attackers"
    slots = [
        i for i, p in enumerate(alice.battlefield) if p.is_creature and not p.tapped
    ]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why
    _w1g9_settle(game)
    assert game.stack == [] and godo.tapped and blademaster.tapped
    _w1g9_drive_combat(game)
    assert bob.life == 17 - 3 - 2
    assert game.current_turn_phase == "postcombat_main"

# ==== end w1g9 ======================================================
