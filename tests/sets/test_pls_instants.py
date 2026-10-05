"""Planeshift instants.

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
# Three instants that arrived supported with every instrument quiet and had
# never been run: Treva's Charm (a draw-then-discard beside two targeted
# modes), Eladamri's Call (a search that reveals) and Surprise Deployment (a
# card put onto the battlefield out of a hand, under a timing gate and a
# conditional return). Driven, all three hold; these are the games.
import random as _w1g3_random

from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_instant_table(set_pool, hand, *, theirs=(), library=(), active=0):
    """Seat 0 holds *hand* over *library* (top first); seat 1 controls
    *theirs*. Both seats are interactive, so a queued spell stays on the stack.
    Names are read from PLS, then LEA. Returns the game and a card lookup."""
    pools = [set_pool(code) for code in ("PLS", "LEA")]

    def w1g3_card(card_name):
        return next(pool[card_name] for pool in pools if card_name in pool)

    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(
            name="A", hand=[w1g3_card(n) for n in hand],
            library=[w1g3_card(n) for n in (library or ["Forest"] * 6)],
        ),
        _W1G3PlayerState(
            name="B", battlefield=[_W1G3Permanent(card=w1g3_card(n)) for n in theirs],
            library=[w1g3_card("Forest")] * 6,
        ),
    ])
    w1g3_game.enforce_mana_costs = False
    w1g3_game.interactive_seats = {0, 1}
    w1g3_game.start_turn(active)
    w1g3_game._sync_control()
    for w1g3_perm in w1g3_game.players[1].battlefield:
        w1g3_perm.metadata["summoning_sickness_turn"] = -99
    return w1g3_game, w1g3_card  # _w1g3_instant_table


def _w1g3_names(cards):
    return [card.name for card in cards]  # _w1g3_names


def test_w1g3_trevas_charm_exiles_the_attacker_and_not_the_creature_beside_it(set_pool):
    """Mode 2: "Exile target **attacking** creature." On the opponent's combat,
    aimed at the Bears that attacked: exiled, to its owner's exile. Aimed at the
    Hill Giant that stayed home, the Charm resolves and exiles nothing."""
    game, _card = _w1g3_instant_table(
        set_pool, ["Treva's Charm", "Treva's Charm"],
        theirs=["Grizzly Bears", "Hill Giant"], active=1,
    )
    theirs = game.players[1]
    bears, giant = theirs.battlefield
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(1, [0], defending_player_index=0)[0]

    game.queue_from_hand(
        0, "Treva's Charm", mode_index=1, target_player_index=1,
        target_permanent_ids=[game.permanent_id_of(giant)],
    )
    _w1g3_resolve_stack(game)
    assert _w1g3_names(p.card for p in theirs.battlefield) == ["Grizzly Bears", "Hill Giant"]

    game.queue_from_hand(
        0, "Treva's Charm", mode_index=1, target_player_index=1,
        target_permanent_ids=[game.permanent_id_of(bears)],
    )
    _w1g3_resolve_stack(game)
    assert _w1g3_names(p.card for p in theirs.battlefield) == ["Hill Giant"]
    assert _w1g3_names(theirs.exile) == ["Grizzly Bears"]


def test_w1g3_trevas_charm_destroys_an_enchantment(set_pool):
    """Mode 1: "Destroy target enchantment." The enchantment goes to its
    owner's graveyard and the creature beside it is untouched."""
    game, _card = _w1g3_instant_table(
        set_pool, ["Treva's Charm"], theirs=["Dark Suspicions", "Grizzly Bears"],
    )
    theirs = game.players[1]
    enchantment = theirs.battlefield[0]

    result = game.queue_from_hand(
        0, "Treva's Charm", mode_index=0, target_player_index=1,
        target_permanent_ids=[game.permanent_id_of(enchantment)],
    )
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert _w1g3_names(p.card for p in theirs.battlefield) == ["Grizzly Bears"]
    assert _w1g3_names(theirs.graveyard) == ["Dark Suspicions"]


def test_w1g3_trevas_charm_draws_before_it_discards(set_pool):
    """Mode 3: "Draw a card, **then** discard a card." The card drawn is in the
    hand the discard is chosen from — here it is the one discarded."""
    game, _card = _w1g3_instant_table(
        set_pool, ["Treva's Charm", "Counterspell"], library=["Island", "Swamp"],
    )
    mine = game.players[0]

    result = game.queue_from_hand(0, "Treva's Charm", mode_index=2)
    game.resolve_top_of_stack()
    owed = next(c for c in game.pending_choices if c.kind == "discard")

    assert result.supported and owed.player_index == 0
    assert _w1g3_names(mine.hand) == ["Counterspell", "Island"]
    assert game.confirm_discard(0, [1])
    _w1g3_resolve_stack(game)

    assert _w1g3_names(mine.hand) == ["Counterspell"]
    assert _w1g3_names(mine.graveyard) == ["Island", "Treva's Charm"]
    assert _w1g3_names(mine.library) == ["Swamp"]


def test_w1g3_eladamris_call_finds_a_creature_card_and_shows_it(set_pool):
    """"Search your library for a creature card, reveal that card, put it into
    your hand, then shuffle." A noncreature card is not an answer; the creature
    found is revealed by name, lands in the hand, and the rest is shuffled."""
    _w1g3_random.seed(3)
    game, _card = _w1g3_instant_table(
        set_pool, ["Eladamri's Call"],
        library=["Forest", "Counterspell", "Grizzly Bears", "Shivan Dragon", "Island"],
    )
    mine = game.players[0]
    game.queue_from_hand(0, "Eladamri's Call")
    game.resolve_top_of_stack()
    owed = next(c for c in game.pending_choices if c.kind == "search_library")

    assert owed.data["card_type"] == "creature" and owed.data["reveal"] is True
    assert not game.confirm_search_library(0, 1), "Counterspell is not a creature card"
    assert game.confirm_search_library(0, 3)
    _w1g3_resolve_stack(game)

    assert _w1g3_names(mine.hand) == ["Shivan Dragon"]
    assert sorted(_w1g3_names(mine.library)) == [
        "Counterspell", "Forest", "Grizzly Bears", "Island",
    ]
    assert any(line == "A revealed Shivan Dragon" for line in game.log), game.log[-4:]
    assert _w1g3_names(mine.library) != ["Forest", "Counterspell", "Grizzly Bears", "Island"]


def _w1g3_deploy(set_pool, hand):
    """Cast Surprise Deployment during combat out of a hand that also holds
    *hand*, accept the offer, and stop at the pick. Returns the game, seat 0
    and the pending pick (None when the hand offers nothing)."""
    game, _card = _w1g3_instant_table(set_pool, ["Surprise Deployment", *hand])
    game.interactive_seats = {0}
    game.current_turn_phase, game.current_step = "combat", "declare_blockers"
    assert game.queue_from_hand(0, "Surprise Deployment").supported
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=True)
    pick = next(
        (c for c in game.pending_choices if c.kind == "put_from_hand_choice"), None
    )
    return game, game.players[0], pick  # _w1g3_deploy


def test_w1g3_surprise_deployment_is_cast_only_during_combat(set_pool):
    """"Cast this spell only during combat." Refused in both main phases and
    legal in a combat step — including the opponent's combat, which is the
    point of an instant that makes a blocker."""
    for phase, step, legal in (
        ("precombat_main", "precombat_main", False),
        ("combat", "declare_attackers", True),
        ("combat", "end_of_combat", True),
        ("postcombat_main", "postcombat_main", False),
    ):
        game, _card = _w1g3_instant_table(set_pool, ["Surprise Deployment"])
        game.current_turn_phase, game.current_step = phase, step
        result = game.queue_from_hand(0, "Surprise Deployment")
        assert result.supported is legal, (phase, step, result.details)

    game, _card = _w1g3_instant_table(set_pool, ["Surprise Deployment"], active=1)
    game.current_turn_phase, game.current_step = "combat", "declare_blockers"
    assert game.queue_from_hand(0, "Surprise Deployment").supported


def test_w1g3_surprise_deployment_puts_a_nonwhite_creature_in_and_takes_it_back(set_pool):
    """"You may put a **nonwhite creature** card from your hand onto the
    battlefield. At the beginning of the next end step, return that creature to
    your hand." Only the red Dragon is offered — not the white Lions, not the
    Counterspell — and naming the Lions is refused. The Dragon arrives, and the
    end step returns it."""
    game, mine, pick = _w1g3_deploy(
        set_pool, ["Savannah Lions", "Shivan Dragon", "Counterspell"]
    )

    assert [mine.hand[i].name for i in game.live_put_from_hand_choices(pick)] == [
        "Shivan Dragon"
    ]
    assert not game.confirm_put_from_hand_choice(0, 0), "Savannah Lions is white"
    assert game.confirm_put_from_hand_choice(0, 1)
    _w1g3_resolve_stack(game)
    assert _w1g3_names(p.card for p in mine.battlefield) == ["Shivan Dragon"]

    game.resolve_end_step(0)
    _w1g3_resolve_stack(game)

    assert not mine.battlefield
    assert sorted(_w1g3_names(mine.hand)) == [
        "Counterspell", "Savannah Lions", "Shivan Dragon",
    ]


def test_w1g3_surprise_deployment_returns_it_only_if_it_is_on_the_battlefield(set_pool):
    """"(Return it only if it's on the battlefield.)" The Dragon left before the
    end step: it is not fetched out of the graveyard — and a creature that left
    and came back is a new object the spell never named (CR 400.7), so it
    stays."""
    game, mine, _pick = _w1g3_deploy(set_pool, ["Shivan Dragon"])
    assert game.confirm_put_from_hand_choice(0, 0)
    _w1g3_resolve_stack(game)
    dragon = mine.battlefield[0]
    game.remove_from_battlefield(dragon)
    mine.graveyard.append(dragon.card)

    game.resolve_end_step(0)
    _w1g3_resolve_stack(game)
    assert not mine.hand
    assert "Shivan Dragon" in _w1g3_names(mine.graveyard)

    game, mine, _pick = _w1g3_deploy(set_pool, ["Shivan Dragon"])
    assert game.confirm_put_from_hand_choice(0, 0)
    _w1g3_resolve_stack(game)
    dragon = mine.battlefield[0]
    game.remove_from_battlefield(dragon)
    game._put_permanent_onto_battlefield(0, _W1G3Permanent(card=dragon.card), None)

    game.resolve_end_step(0)
    _w1g3_resolve_stack(game)
    assert _w1g3_names(p.card for p in mine.battlefield) == ["Shivan Dragon"]
    assert not mine.hand


def test_w1g3_surprise_deployment_offers_nothing_from_a_hand_of_white_creatures(set_pool):
    """A hand with no nonwhite creature card: the offer is accepted and there is
    nothing to pick, nothing enters and no return is armed."""
    game, mine, pick = _w1g3_deploy(set_pool, ["Savannah Lions"])
    _w1g3_resolve_stack(game)

    assert pick is None
    assert not mine.battlefield and not game.delayed_triggers
    assert _w1g3_names(mine.hand) == ["Savannah Lions"]
