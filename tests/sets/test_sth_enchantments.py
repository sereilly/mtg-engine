"""Stronghold enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G1: damage prevention, redirection and damage-event triggers ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


def _w1g1_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g1_bolt(name="Bolt Test", type_line="Instant"):
    return CardDefinition(
        name=name, mana_cost="{R}", cmc=1.0, type_line=type_line,
        oracle_text=f"{name} deals 3 damage to any target.",
        colors=("R",), color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


def _w1g1_retreat_board(set_pool):
    game = _w1g1_duel()
    p1, p2 = game.players
    retreat = _nosick(Permanent(card=set_pool("STH")["Hidden Retreat"]))
    p1.battlefield.append(retreat)
    p1.hand.append(_w1g1_bolt("Spare Card"))
    return game, p1, p2, retreat


def test_hidden_retreat_pays_by_putting_a_card_back_on_top(set_pool):
    """"Put a card from your hand on top of your library: …"

    CR 118.1 makes the payment the printed action, and the printed action is
    what the ability is *for*: the card is still in the library and will be
    drawn again, which is why this is not a discard wearing another name. So the
    test asserts both ends of the move — the hand one shorter, and that exact
    card on top rather than in a graveyard.
    """
    game, p1, p2, _retreat = _w1g1_retreat_board(set_pool)
    p2.hand.append(_w1g1_bolt())
    game.queue_from_hand(1, "Bolt Test", target_player_index=0)
    paid = p1.hand[0]

    result = game.activate_permanent_ability(
        0, "Hidden Retreat", permanent_index=0, target_stack_index=0,
    )

    assert result.supported
    assert p1.hand == []
    assert p1.library[0] is paid
    assert paid not in p1.graveyard


def test_hidden_retreat_cannot_be_activated_with_an_empty_hand(set_pool):
    """CR 118.3: a player cannot pay a cost without the resources to pay it, and
    CR 602.5c then makes the ability unactivatable rather than free.

    The half that is only done when something enforces it — an unenforced cost
    is not a dead ability, it is an ability that works more often than the card
    allows, and this one would then be a free blanket every turn.
    """
    game, p1, p2, _retreat = _w1g1_retreat_board(set_pool)
    p1.hand.clear()
    p2.hand.append(_w1g1_bolt())
    game.queue_from_hand(1, "Bolt Test", target_player_index=0)

    result = game.activate_permanent_ability(
        0, "Hidden Retreat", permanent_index=0, target_stack_index=0,
    )

    assert not result.supported


def test_hidden_retreat_stops_the_spell_it_named_and_no_other(set_pool):
    """"Prevent all damage that would be dealt by target instant or sorcery
    spell this turn."

    The shield hangs off the **stack item**, not off a recipient and not off the
    printed card, so the assertions are the two things that distinguishes:
    the named spell's damage is gone, and a *second copy of the same card* —
    which shares one ``CardDefinition`` (CR 109.5) — still deals its three.
    """
    game, p1, p2, _retreat = _w1g1_retreat_board(set_pool)
    bolt = _w1g1_bolt()
    p2.hand.extend([bolt, bolt])
    life = p1.life

    game.queue_from_hand(1, "Bolt Test", target_player_index=0)
    assert game.activate_permanent_ability(
        0, "Hidden Retreat", permanent_index=0, target_stack_index=0,
    ).supported
    resolve_stack(game)

    assert p1.life == life, "the spell it named dealt nothing"

    game.cast_from_hand(1, "Bolt Test", target_player_index=0)
    resolve_stack(game)

    assert p1.life == life - 3, "a second cast of the same card is a second spell"
