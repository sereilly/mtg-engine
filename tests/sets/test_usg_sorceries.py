"""Urza's Saga sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: cycling (CR 702.29) ---
import pytest

from engine import Game, PlayerState
from engine.activation_zones import HAND
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The three sorceries with cycling. All three reported supported before the
#: rewrite, with the keyword unclaimed — see the instants file for why that is
#: the interesting half.
_G1_CYCLING_SORCERIES = ("Lay Waste", "Hush", "Rejuvenate")


def _g1_sorcery_game(card, *, library=4):
    """Seat 0 holds *card* over a library of copies of it. Named for this block."""
    player = PlayerState(name="G1-S", hand=[card], library=[card] * library)
    return Game(players=[player, PlayerState(name="G1-T")]), player


@pytest.mark.parametrize("name", _G1_CYCLING_SORCERIES)
def test_w1g1_a_cycling_sorcery_is_discarded_for_a_card(set_pool, name):
    """Rejuvenate is the one to read: cycled, it gains no life. A rewrite that
    let the spell's own line resolve would be invisible on the other two."""
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    game, player = _g1_sorcery_game(card)
    game.enforce_mana_costs = False
    life_before = player.life

    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)

    assert [c.name for c in player.graveyard] == [name]
    assert len(player.library) == 3
    assert player.life == life_before


# --- W2G1: the two burn sorceries ---
from engine import Game as _G1sGame, PlayerState as _G1sPlayerState  # noqa: E402
from engine.models import Permanent as _G1sPermanent  # noqa: E402
from engine.oracle import compile_card_oracle as _g1s_compile  # noqa: E402
from engine.game_types import OracleExecutionContext as _G1sContext  # noqa: E402
from engine.targeting import derive_cast_spec as _g1s_spec  # noqa: E402


def _g1s_board(pool, mine=(), theirs=()):
    """Two seats with a USG library each. Ends on the control sync, this
    block's own helper tail."""
    game = _G1sGame(players=[
        _G1sPlayerState(name="G1sA", battlefield=list(mine),
                        library=[pool["Remote Isle"]] * 8),
        _G1sPlayerState(name="G1sB", battlefield=list(theirs),
                        library=[pool["Remote Isle"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


def test_w2g1_arc_lightning_offers_at_most_three_targets(set_pool):
    """"Arc Lightning deals 3 damage divided as you choose among one, two, or
    three targets."

    CR 601.2c's printed ceiling on a variable target count, which the engine has
    read since Contagion's counters — the same clause about damage instead, and
    CR 601.2d covers both in one sentence. What was missing was only the parse,
    so the whole of this test is the number reaching the picker: a spell whose
    spec omitted it would offer a fourth target the cast gate then refuses.
    """
    pool = set_pool("USG")
    card = pool["Arc Lightning"]
    spec = _g1s_spec(card, _g1s_compile(card))
    assert spec["kind"] == "divided"
    assert spec["division"] == "chosen", "the caster divides, not the game"
    assert spec["max_targets"] == 3, "one, two, or three"
    assert spec["division_total"] == 3


def test_w2g1_disorder_burns_white_creatures_and_only_their_controllers(set_pool):
    """"Disorder deals 2 damage to each white creature and each player who
    controls a white creature."

    Two described sets in one sentence, the second keyed to the first. Three
    assertions, one per way the sentence could reach further than it says: the
    colour on the creature half, the presence test on the seat half, and the
    seat that controls nothing white taking nothing.
    """
    pool = set_pool("USG")
    white = _G1sPermanent(card=pool["Intrepid Hero"])
    green = _G1sPermanent(card=pool["Blanchwood Treefolk"])
    game = _g1s_board(pool, mine=[white], theirs=[green])

    card = pool["Disorder"]
    program = _g1s_compile(card)
    context = _G1sContext(card=card, caster=game.players[0], target=game.players[0])
    for instruction in program.instructions:
        game._execute_oracle_instruction(instruction, context)

    assert white.damage_marked == 2, "a white creature"
    assert green.damage_marked == 0, "the colour is tested, not dropped"
    assert game.players[0].life == 18, "its controller"
    assert game.players[1].life == 20, "a player controlling nothing white"
