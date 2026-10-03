"""Prophecy sorceries.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: spell costs ---
from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import _mk_card as _w1g2_mk_card
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_typed(name, subtype, toughness=1):
    """A 1/*toughness* creature of *subtype*, so a -1/-1 is the difference
    between dying and surviving and the board says which creatures were hit."""
    card = _w1g2_mk_card(name, "{2}", f"Creature - {subtype}", "")
    card.raw.update({"power": "1", "toughness": str(toughness)})
    return _W1G2Permanent(card=card)


def _w1g2_outbreak_game(set_pool, mine=(), theirs=(), hand_extra=(), interactive=()):
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            name="P1", battlefield=list(mine),
            hand=[pcy["Outbreak"]] + [lea[n] for n in hand_extra],
        ),
        _W1G2PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game._sync_control()
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_board(game):
    return sorted(p.card.name for _seat, p in game.permanents_with_controller())


def test_w1g2_outbreak_shrinks_only_the_creature_type_its_caster_names(set_pool):
    """"Choose a creature type. All creatures of that type get -1/-1 until end
    of turn."

    Two sentences, two steps: CR 608.2d's choice is made while the spell
    resolves and recorded in its scratchpad — Extinction's record, written by a
    sentence of its own — and "of that type" reads it back. The interactive
    seat's answer arrives before the sweep, so the board it takes is the one the
    player named: both Goblins die, on both sides, and the Bear lives.
    """
    program = _w1g2_compile(set_pool("PCY")["Outbreak"])
    assert program.supported, program.reason

    game = _w1g2_outbreak_game(
        set_pool,
        mine=[_w1g2_typed("My Goblin", "Goblin")],
        theirs=[_w1g2_typed("Their Goblin", "Goblin"), _w1g2_typed("Their Bear", "Bear"),
                _w1g2_typed("Their Elf", "Elf", toughness=2)],
        interactive=[0],
    )
    game.enforce_mana_costs = False
    result = game.cast_from_hand(0, "Outbreak")
    assert result.supported, result.details
    assert [c.kind for c in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g2_resolve_stack(game)
    game._settle()

    assert _w1g2_board(game) == ["Their Bear", "Their Elf"], game.log


def test_w1g2_outbreak_lasts_until_end_of_turn(set_pool):
    """The -1/-1 is a one-shot layer-7c change swept with the turn: a 1/2 Elf
    survives it at 1/1 and is back to 1/2 after the cleanup step."""
    elf = _w1g2_typed("Their Elf", "Elf", toughness=2)
    game = _w1g2_outbreak_game(set_pool, theirs=[elf], interactive=[0])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Outbreak")
    assert game.confirm_creature_type_choice(0, "elf")
    _w1g2_resolve_stack(game)
    assert (elf.effective_power, elf.effective_toughness) == (0, 1), game.log

    game.resolve_cleanup_step(0)
    assert (elf.effective_power, elf.effective_toughness) == (1, 2)


def test_w1g2_outbreak_can_be_cast_by_discarding_a_swamp_card(set_pool):
    """"You may discard a Swamp card rather than pay this spell's mana cost."

    CR 118.9 with mana enforced and an empty pool: the Swamp card leaves the
    hand for the graveyard and the spell resolves. With no Swamp card in hand
    the offer is absent from the picker and the cast is refused at CR 601.2h
    with nothing spent — the Forest beside it answers nothing.
    """
    game = _w1g2_outbreak_game(set_pool, hand_extra=("Swamp",))
    game.enforce_mana_costs = True
    offers = game.cast_cost_offers(0, set_pool("PCY")["Outbreak"], spell_hand_index=0)
    alternative = next(o for o in offers if o["kind"] == "alternative")
    assert alternative["payable"]
    assert [c["name"] for c in alternative["hand_choices"]] == ["Swamp"]
    # The button names the price: the Swamp is discarded, not exiled.
    assert alternative["hand_verb"] == "discard"

    result = game.cast_from_hand(
        0, "Outbreak", alternative_cost=True, alternative_cost_hand_index=1,
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    assert sorted(c.name for c in game.players[0].graveyard) == ["Outbreak", "Swamp"]
    assert game.players[0].hand == []

    game = _w1g2_outbreak_game(set_pool, hand_extra=("Forest",))
    game.enforce_mana_costs = True
    offers = game.cast_cost_offers(0, set_pool("PCY")["Outbreak"], spell_hand_index=0)
    assert not next(o for o in offers if o["kind"] == "alternative")["payable"]
    result = game.cast_from_hand(0, "Outbreak", alternative_cost=True)
    assert not result.supported
    assert sorted(c.name for c in game.players[0].hand) == ["Forest", "Outbreak"]


def test_w1g2_of_that_type_without_a_choice_in_front_refuses(set_pool):
    """"All creatures of that type get -1/-1" with no step of the same effect
    choosing a type names nothing — and an unresolved "that type" read as no
    narrowing would shrink the whole board. The line refuses instead."""
    from engine.grammar import compile_line

    compiled = compile_line("All creatures of that type get -1/-1 until end of turn.")
    assert not compiled.usable
    assert "no step of this effect chose" in (compiled.failure_reason or "")
