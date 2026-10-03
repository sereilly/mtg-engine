"""Prophecy instants.

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
from engine.damage_events import deal_damage as _w1g2_deal_damage
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_snag_combat(set_pool, *, caster: int, hand=("Snag", "Forest"), cast=True):
    """Two Bears of P1's attack P2, whose Wall of Wood blocks the first; Snag is
    cast first by *caster* off its Forest alternative cost, with mana enforced
    and every pool empty, so the cast itself proves the Forest paid. *cast*
    False is the control board, Snag left in hand."""
    lea, pcy = set_pool("LEA"), set_pool("PCY")
    bears = [_W1G2Permanent(card=lea["Grizzly Bears"]) for _ in range(2)]
    wall = _W1G2Permanent(card=lea["Wall of Wood"])
    cards = [pcy[n] if n == "Snag" else lea[n] for n in hand]
    players = [
        _W1G2PlayerState(name="P1", battlefield=list(bears)),
        _W1G2PlayerState(name="P2", battlefield=[wall]),
    ]
    players[caster].hand.extend(cards)
    game = _W1G2Game(players=players)
    game._sync_control()
    game.start_turn(0)
    for bear in bears:
        bear.summoning_sick = False
    game.enforce_mana_costs = True
    if not cast:
        return game, bears, wall
    result = game.cast_from_hand(
        caster, "Snag", alternative_cost=True, alternative_cost_hand_index=1,
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    return game, bears, wall


def _w1g2_fight(game):
    game._set_phase_and_step("combat", "declare_attackers")
    declared, why = game.declare_attackers(0, [0, 1], 1)
    assert declared, why
    game.advance_combat_phase()
    blocked, why = game.declare_blockers(1, {0: 0})
    assert blocked, why
    while game.current_step != "end_of_combat":
        game.advance_combat_phase()


def test_w1g2_snag_prevents_unblocked_creatures_combat_damage(set_pool):
    """"Prevent all combat damage that would be dealt by unblocked creatures
    this turn." Cast by the defender off a discarded Forest: the unblocked Bear
    deals P2 nothing, and the *blocked* Bear's damage to the Wall is not
    prevented — "unblocked" is asked of the source when the damage would be
    dealt (CR 509.1h, CR 615.9), not of every attacker.
    """
    program = _w1g2_compile(set_pool("PCY")["Snag"])
    assert program.supported, program.reason

    game, _bears, wall = _w1g2_snag_combat(set_pool, caster=1)
    assert sorted(c.name for c in game.players[1].graveyard) == ["Forest", "Snag"]
    _w1g2_fight(game)

    assert game.players[1].life == 20, game.log
    assert wall.damage_marked == 2, "the blocked Bear's damage is not prevented"


def test_w1g2_snag_reaches_every_recipient_not_only_its_caster(set_pool):
    """No recipient is printed, so the shield stops that damage whoever it was
    headed for — cast by the *attacker* it fogs their own unblocked Bear's
    damage to the opponent, which is a strictly worse play and still the card.
    Without the shield the same combat costs P2 two life."""
    game, _bears, _wall = _w1g2_snag_combat(set_pool, caster=0)
    _w1g2_fight(game)
    assert game.players[1].life == 20, game.log

    control, _bears, _wall = _w1g2_snag_combat(set_pool, caster=0, cast=False)
    _w1g2_fight(control)
    assert control.players[1].life == 18, control.log


def test_w1g2_snag_leaves_noncombat_damage_alone(set_pool):
    """"…**combat** damage…": a ping from the same unblocked attacker is
    noncombat damage (CR 120.2) and goes through. The word is the event's, not
    the source's, which is why it rides the shield as its own field."""
    game, bears, _wall = _w1g2_snag_combat(set_pool, caster=1)
    game._set_phase_and_step("combat", "declare_attackers")
    declared, why = game.declare_attackers(0, [0, 1], 1)
    assert declared, why
    game.advance_combat_phase()
    blocked, why = game.declare_blockers(1, {})
    assert blocked, why

    def dealt(combat):
        return _w1g2_deal_damage(game, {
            "recipient": game.players[1], "amount": 1, "source": bears[1],
            "combat": combat,
        }).dealt

    assert dealt(combat=True) == 0
    assert dealt(combat=False) == 1


def test_w1g2_snag_has_no_alternative_cost_without_a_forest_card(set_pool):
    """With no Forest card in hand the offer cannot be paid and the cast is
    refused at CR 601.2h with nothing spent — a Swamp is not a Forest."""
    lea, pcy = set_pool("LEA"), set_pool("PCY")
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="P1", hand=[pcy["Snag"], lea["Swamp"]]),
        _W1G2PlayerState(name="P2"),
    ])
    game.start_turn(0)
    game.enforce_mana_costs = True
    result = game.cast_from_hand(0, "Snag", alternative_cost=True)
    assert not result.supported
    assert sorted(c.name for c in game.players[0].hand) == ["Snag", "Swamp"]
