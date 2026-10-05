"""Planeshift enchantments.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: revealed cards ---
# "{3}{C}: Target opponent reveals a card at random from their hand. <something
# sized by that card's mana value>." The reveal shipped with Wand of Ith; what
# the Planeswalker's cycle adds is a later sentence *reading* what it showed —
# "that card's mana value" (a record the reveal step freezes, CR 608.2h) and
# "the revealed card's mana value" (the where-clause spelling of the same
# card). An empty hand reveals nothing and CR 107.2 makes the number 0.
import random as _w1g3_random

from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_activation_spec as _w1g3_activation_spec
from engine.targeting import spec_roles as _w1g3_spec_roles
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_cycle_board(set_pool, name, held, *, mine=(), theirs=(), seats=2, active=0):
    """Seat 0 controls the Planeswalker's enchantment *name*; seat 1 holds
    *held*. Names are read from PLS, then M21, then LEA. Every seat is
    interactive, so ``queue_permanent_ability`` leaves the ability on the
    stack. Returns ``(game, players, card lookup)``."""
    pools = [set_pool(code) for code in ("PLS", "M21", "LEA")]

    def w1g3_card(card_name):
        return next(pool[card_name] for pool in pools if card_name in pool)

    w1g3_players = [
        _W1G3PlayerState(
            name="A",
            battlefield=[_W1G3Permanent(card=w1g3_card(n)) for n in (name, *mine)],
        ),
        _W1G3PlayerState(
            name="B", hand=[w1g3_card(n) for n in held],
            battlefield=[_W1G3Permanent(card=w1g3_card(n)) for n in theirs],
        ),
    ]
    w1g3_players.extend(
        _W1G3PlayerState(name="CDE"[index - 2]) for index in range(2, seats)
    )
    for w1g3_player in w1g3_players:
        w1g3_player.library.extend([w1g3_card("Forest")] * 6)
    w1g3_game = _W1G3Game(players=w1g3_players)
    w1g3_game.enforce_mana_costs = False
    w1g3_game.interactive_seats = set(range(seats))
    w1g3_game.start_turn(active)
    w1g3_game._sync_control()
    return w1g3_game, w1g3_players, w1g3_card  # _w1g3_cycle_board


def _w1g3_two_targets(game, seat, permanent):
    """The role refs Favor and Scorn announce: the opponent, then the creature."""
    return [{"seat": seat}, {"permanent_id": game.permanent_id_of(permanent)}]  # _w1g3_two_targets


def test_w1g3_planeswalkers_mirth_gains_the_revealed_cards_mana_value(set_pool):
    """"You gain life equal to that card's mana value." Shivan Dragon is the
    only card in the hand, so the reveal is of a six-drop and the gain is 6 —
    and the card stays in the hand it was revealed from (CR 701.20a: a reveal
    shows a card, it does not move one)."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mirth", ["Shivan Dragon"]
    )

    result = game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert players[0].life == 26 and players[1].life == 20, game.log[-4:]
    assert [card.name for card in players[1].hand] == ["Shivan Dragon"]
    assert any("B reveals Shivan Dragon at random" in line for line in game.log)


def test_w1g3_planeswalkers_mirth_reveals_at_random(set_pool):
    """One card of the hand, chosen by nobody: over thirty seeds a hand of a
    six-drop, a two-drop and a land gains each of 6, 2 and 0 at least once,
    and never anything else."""
    gained = set()
    for seed in range(30):
        _w1g3_random.seed(seed)
        game, players, _card = _w1g3_cycle_board(
            set_pool, "Planeswalker's Mirth", ["Shivan Dragon", "Counterspell", "Forest"]
        )
        game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
        _w1g3_resolve_stack(game)
        gained.add(players[0].life - 20)

    assert gained == {0, 2, 6}


def test_w1g3_planeswalkers_mirth_gains_nothing_from_an_empty_hand(set_pool):
    """CR 107.2: a number that cannot be determined is 0. No life is gained —
    and no life-*gain event* happens, so Vito's "whenever you gain life" does
    not trigger. With a card to reveal, the same board drains for 6."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mirth", [], mine=["Vito, Thorn of the Dusk Rose"]
    )
    game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert (players[0].life, players[1].life) == (20, 20), game.log[-4:]
    assert not any("gained" in line for line in game.log), game.log[-4:]

    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mirth", ["Shivan Dragon"],
        mine=["Vito, Thorn of the Dusk Rose"],
    )
    game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert (players[0].life, players[1].life) == (26, 14), game.log[-5:]


def test_w1g3_planeswalkers_mirth_names_an_opponent_at_instant_speed(set_pool):
    """"Target **opponent**": the activator's own seat is refused with nothing
    resolved. And Mirth prints no "Activate only as a sorcery", so it is
    activated on the opponent's turn."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mirth", ["Shivan Dragon"], active=1
    )
    ability = _w1g3_compile(set_pool("PLS")["Planeswalker's Mirth"]).activated_abilities[0]
    assert _w1g3_activation_spec(ability) == {"kind": "player", "opponents_only": True}

    refused = game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=0)
    assert not refused.supported and not game.stack, refused.details

    allowed = game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
    _w1g3_resolve_stack(game)
    assert allowed.supported and players[0].life == 26, game.log[-4:]


def test_w1g3_planeswalkers_fury_burns_the_opponent_who_revealed(set_pool):
    """"This enchantment deals damage equal to that card's mana value to that
    player." Three seats, the far one named: C reveals a Counterspell and C
    takes 2 — not B, the first opponent, whose hand holds a six-drop."""
    game, players, card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Fury", ["Shivan Dragon"], seats=3
    )
    players[2].hand.append(card("Counterspell"))

    result = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=2)
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert [player.life for player in players] == [20, 20, 18], game.log[-4:]
    assert any("Planeswalker's Fury dealt 2 damage to C" in line for line in game.log)


def test_w1g3_planeswalkers_fury_deals_nothing_for_an_empty_hand(set_pool):
    """CR 107.2 again: no card, no number, no damage — and no damage event in
    the log either."""
    game, players, _card = _w1g3_cycle_board(set_pool, "Planeswalker's Fury", [])

    result = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert players[1].life == 20
    assert not any("dealt" in line for line in game.log), game.log[-4:]


def test_w1g3_planeswalkers_fury_is_activated_only_as_a_sorcery(set_pool):
    """"Activate only as a sorcery." Refused on the opponent's turn, and
    refused on its controller's own main phase while the stack holds anything
    — here its own first activation."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Fury", ["Shivan Dragon"], active=1
    )
    refused = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=1)
    assert not refused.supported and "sorcery" in refused.details, refused.details
    assert players[1].life == 20 and not game.stack

    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Fury", ["Shivan Dragon"]
    )
    first = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=1)
    second = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert first.supported and not second.supported, second.details
    assert players[1].life == 14, "one activation, one six-drop"


def test_w1g3_planeswalkers_favor_pumps_by_the_revealed_cards_mana_value(set_pool):
    """"Target creature gets +X/+X until end of turn, where X is the revealed
    card's mana value." Two targets on one ability — the opponent who reveals
    and the creature that grows — and the picker is offered both, in the order
    the sentence prints them."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Favor", ["Shivan Dragon"], mine=["Grizzly Bears"]
    )
    bear = players[0].battlefield[1]
    ability = _w1g3_compile(set_pool("PLS")["Planeswalker's Favor"]).activated_abilities[0]
    roles = _w1g3_spec_roles(_w1g3_activation_spec(ability))
    assert [role["role"] for role in roles] == ["player", "creature"]
    assert roles[0]["opponents_only"] is True

    result = game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert (bear.effective_power, bear.effective_toughness) == (8, 8), game.log[-4:]


def test_w1g3_planeswalkers_favor_refuses_a_target_its_line_does_not_print(set_pool):
    """The announcement is held to both printed phrases: the activator is not
    their own opponent, and an enchantment is not a creature."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Favor", ["Shivan Dragon"], mine=["Grizzly Bears"]
    )
    favor, bear = players[0].battlefield

    own_seat = game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 0, bear)
    )
    not_a_creature = game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, favor)
    )

    assert not own_seat.supported and not not_a_creature.supported
    assert not game.stack


def test_w1g3_planeswalkers_favor_reads_each_activations_own_reveal(set_pool):
    """Two activations in one turn, at instant speed on the opponent's turn
    (Favor prints no sorcery clause): the second reads the card *it* revealed
    — a two-drop — rather than the six the first one froze. 2/2 + 6 + 2."""
    game, players, card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Favor", ["Shivan Dragon"],
        mine=["Grizzly Bears"], active=1,
    )
    bear = players[0].battlefield[1]

    game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )
    _w1g3_resolve_stack(game)
    players[1].hand[:] = [card("Counterspell")]
    game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )
    _w1g3_resolve_stack(game)

    assert (bear.effective_power, bear.effective_toughness) == (10, 10), game.log[-6:]


def test_w1g3_planeswalkers_favor_still_reveals_when_its_creature_has_gone(set_pool):
    """CR 608.2b, per target: the creature left in response, so that target is
    illegal and nothing is pumped — but the opponent is still a legal target,
    so the ability resolves and the card is still revealed."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Favor", ["Shivan Dragon"], mine=["Grizzly Bears"]
    )
    bear = players[0].battlefield[1]
    game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )

    game.remove_from_battlefield(bear)
    _w1g3_resolve_stack(game)

    assert any("B reveals Shivan Dragon at random" in line for line in game.log)
    assert not any("gives Grizzly Bears" in line for line in game.log), game.log[-4:]


def test_w1g3_planeswalkers_scorn_shrinks_by_the_revealed_cards_mana_value(set_pool):
    """"Target creature gets -X/-X until end of turn": a six-drop revealed, so
    the 2/2 is a 2/2 with -6/-6 and dies to CR 704.5f."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Scorn", ["Shivan Dragon"], theirs=["Grizzly Bears"]
    )
    bear = players[1].battlefield[0]

    result = game.queue_permanent_ability(
        0, "Planeswalker's Scorn", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )
    _w1g3_resolve_stack(game)
    game._settle()

    assert result.supported, result.details
    assert not players[1].battlefield, game.log[-4:]
    assert [card.name for card in players[1].graveyard] == ["Grizzly Bears"]


def test_w1g3_planeswalkers_scorn_does_nothing_when_the_hand_is_emptied_in_response(set_pool):
    """The hand is read when the ability *resolves*: emptied in response, no
    card is revealed, X is 0 (CR 107.2) and the creature lives."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Scorn", ["Shivan Dragon"], theirs=["Grizzly Bears"]
    )
    bear = players[1].battlefield[0]
    game.queue_permanent_ability(
        0, "Planeswalker's Scorn", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )

    players[1].hand.clear()
    _w1g3_resolve_stack(game)
    game._settle()

    assert [perm.card.name for perm in players[1].battlefield] == ["Grizzly Bears"]
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_w1g3_planeswalkers_scorn_is_activated_only_as_a_sorcery(set_pool):
    """Scorn prints the clause Favor does not: refused on the opponent's turn
    with the creature untouched."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Scorn", ["Shivan Dragon"],
        theirs=["Grizzly Bears"], active=1,
    )
    bear = players[1].battlefield[0]

    refused = game.queue_permanent_ability(
        0, "Planeswalker's Scorn", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )

    assert not refused.supported and "sorcery" in refused.details, refused.details
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
