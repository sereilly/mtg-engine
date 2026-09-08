"""Urza's Saga instants.

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

#: The six instants with cycling. Five of them (all but Brand) were reported
#: **supported** before the CR 702.29a rewrite existed — a spell is supported
#: when any of its lines is, and their effect line always compiled — so the
#: keyword sat in `parse_coverage.py --set USG` as an unclaimed line and in no
#: other instrument at all. That is the population a refusal census cannot
#: reach, and it is why these tests cycle the card in a game rather than
#: asserting that it compiles.
_G1_CYCLING_INSTANTS = ("Clear", "Rescind", "Expunge", "Brand", "Scrap", "Lull")


def _g1_spell_game(card, *, library=4):
    """Seat 0 holds *card* over a library of copies of it."""
    player = PlayerState(name="G1-A", hand=[card], library=[card] * library)
    game = Game(players=[player, PlayerState(name="G1-B")])
    game.enforce_mana_costs = False
    return game, player


@pytest.mark.parametrize("name", _G1_CYCLING_INSTANTS)
def test_w1g1_a_cycling_instant_is_discarded_for_a_card(set_pool, name):
    """Cycling replaces casting the spell, not part of it: the card goes to the
    graveyard, one card is drawn, and the printed effect never happens."""
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]
    # An instant is never on the battlefield, so it has no battlefield abilities
    # to confuse with the cycling one.
    assert usable_activated_abilities(program) == []

    game, player = _g1_spell_game(card)
    opponent_board = [p.card.name for p in game.players[1].battlefield]

    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)

    assert [c.name for c in player.graveyard] == [name]
    assert [c.name for c in player.hand] == [name]      # the card drawn
    assert len(player.library) == 3
    assert [p.card.name for p in game.players[1].battlefield] == opponent_board


# --- W2G1: Redeem's shield over up to two creatures ---
from engine import Game as _G1iGame, PlayerState as _G1iPlayerState  # noqa: E402
from engine.damage_events import deal_damage as _g1i_deal  # noqa: E402
from engine.models import Permanent as _G1iPermanent  # noqa: E402
from engine.oracle import compile_card_oracle as _g1i_compile  # noqa: E402
from engine.game_types import OracleExecutionContext as _G1iContext  # noqa: E402
from engine.targeting import derive_cast_spec as _g1i_spec  # noqa: E402


def _g1i_board(pool, mine=()):
    """One seat with a board and a USG library. Ends on the control sync, this
    block's own helper tail."""
    game = _G1iGame(players=[
        _G1iPlayerState(name="G1iA", battlefield=list(mine),
                        library=[pool["Remote Isle"]] * 8),
        _G1iPlayerState(name="G1iB", library=[pool["Remote Isle"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


def test_w2g1_redeem_shields_both_chosen_creatures(set_pool):
    """"Prevent all damage that would be dealt this turn to up to two target
    creatures."

    One shield armed once per chosen recipient — the branch the handler already
    had for Energy Arc's recorded set, reached from a list the caster named
    instead. Four claims: the picker's ceiling, both chosen creatures, the one
    nobody chose, and the direction (this shield covers damage dealt *to* them
    and leaves their own alone).
    """
    pool = set_pool("USG")
    a = _G1iPermanent(card=pool["Coral Merfolk"])
    b = _G1iPermanent(card=pool["Coral Merfolk"])
    c = _G1iPermanent(card=pool["Coral Merfolk"])
    game = _g1i_board(pool, mine=[a, b, c])

    card = pool["Redeem"]
    program = _g1i_compile(card)
    assert _g1i_spec(card, program) == {"kind": "creature", "max_targets": 2}

    context = _G1iContext(
        card=card, caster=game.players[0], target=game.players[0],
        target_permanent_id=[a.permanent_id, b.permanent_id],
    )
    for instruction in program.instructions:
        game._execute_oracle_instruction(instruction, context)

    assert _g1i_deal(game, {"recipient": a, "amount": 3, "source": None}).dealt == 0
    assert _g1i_deal(game, {"recipient": b, "amount": 3, "source": None,
                            "combat": True}).dealt == 0
    assert _g1i_deal(game, {"recipient": c, "amount": 3, "source": None}).dealt == 3
    assert _g1i_deal(game, {"recipient": c, "amount": 1, "source": a,
                            "combat": True}).dealt == 1, (
        "the shield is one-way: it prevents damage dealt to them, not by them"
    )
