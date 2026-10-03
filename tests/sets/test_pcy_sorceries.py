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


# --- W1G1: rhystic ---
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _w1g1_sorcery_table(set_pool, seats: int = 2, *, active: int = 0, lands=()):
    """*seats* players, the *active* one first to be asked (CR 101.4), with
    ``lands[i]`` untapped Islands on seat i. Mana enforcement off for the cast;
    every rhystic payment is still made out of the board."""
    island = set_pool("LEA")["Island"]
    players = []
    for seat in range(seats):
        count = lands[seat] if seat < len(lands) else 0
        players.append(PlayerState(
            name=f"P{seat}", life=20,
            battlefield=[Permanent(card=island) for _ in range(count)],
        ))
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = active
    return game


def _w1g1_owed(game) -> list[int]:
    """Which seats are being asked to pay, in queue order."""
    return [c.player_index for c in game.pending_choices if c.kind == "optional_pay"]


def _w1g1_tapped(game, seat: int) -> int:
    return sum(1 for perm in game.controlled_by(game.players[seat]) if perm.tapped)


def test_soul_strings_returns_both_cards_when_no_one_can_pay_x(set_pool):
    """"Return two target creature cards from your graveyard to your hand
    unless any player pays {X}." X is the spell's own announced X: with X = 3 a
    two-Island opponent cannot buy it off, so both cards come back."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(0, 2))
    caster = game.players[0]
    caster.hand.append(set_pool("PCY")["Soul Strings"])
    caster.graveyard.extend([lea["Grizzly Bears"], lea["Hill Giant"], lea["Island"]])

    assert game.cast_from_hand(
        0, "Soul Strings", x_value=3, target_permanent_index=[0, 1]
    ).supported
    game.auto_resolve_pending_choices()

    assert sorted(card.name for card in caster.hand) == ["Grizzly Bears", "Hill Giant"]
    assert [card.name for card in caster.graveyard] == ["Island", "Soul Strings"]
    assert _w1g1_tapped(game, 1) == 0, "nothing was paid"


def test_soul_strings_is_bought_off_for_x_by_the_opponent_not_its_caster(set_pool):
    """With X = 2 the same opponent can pay, and does; the caster — asked first,
    because it is the active player — declines rather than paying to stop its
    own spell. The {X} is charged at the announced number, off the board."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(4, 2))
    caster = game.players[0]
    caster.hand.append(set_pool("PCY")["Soul Strings"])
    caster.graveyard.extend([lea["Grizzly Bears"], lea["Hill Giant"]])

    assert game.cast_from_hand(
        0, "Soul Strings", x_value=2, target_permanent_index=[0, 1]
    ).supported
    assert _w1g1_owed(game) == [0], "the active player is asked first"
    assert game.pending_choices[0].data["cost"] == {"generic": 2}, "X is 2"
    game.auto_resolve_pending_choices()

    assert "P0 declined to pay for Soul Strings" in game.log
    assert caster.hand == [], "the payment bought the return off"
    assert _w1g1_tapped(game, 0) == 0 and _w1g1_tapped(game, 1) == 2


def test_rhystic_payment_is_asked_in_turn_order_from_the_active_player(set_pool):
    """Four seats, seat 2 active and casting. CR 101.4 orders the offer from
    the active player around the table — 2, 3, 0 — and the first payment ends
    it (CR 118.12a: one "unless"), so seat 1 is never asked."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, 4, active=2, lands=(2, 2, 2, 2))
    caster = game.players[2]
    caster.hand.append(set_pool("PCY")["Soul Strings"])
    caster.graveyard.extend([lea["Grizzly Bears"], lea["Hill Giant"]])

    assert game.cast_from_hand(
        2, "Soul Strings", x_value=1, target_permanent_index=[0, 1]
    ).supported
    asked = []
    for answer in (False, False, True):
        asked.extend(_w1g1_owed(game))
        assert game.confirm_optional_pay(asked[-1], accept=answer)

    assert asked == [2, 3, 0]
    assert _w1g1_owed(game) == [], "seat 1 is never asked once seat 0 paid"
    assert caster.hand == [] and _w1g1_tapped(game, 0) == 1


def test_rhystic_scrying_discards_three_when_an_opponent_pays(set_pool):
    """"Draw three cards. Then **if** any player pays {2}, discard three cards."
    The polarity reversed: paying is what causes the discard — and the discard
    is the caster's, whoever paid. The paying opponent's own hand is untouched."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(0, 2))
    caster, payer = game.players
    caster.hand.append(set_pool("PCY")["Rhystic Scrying"])
    caster.library.extend([lea["Island"], lea["Forest"], lea["Swamp"], lea["Plains"]])
    payer.hand.append(lea["Mountain"])

    assert game.cast_from_hand(0, "Rhystic Scrying").supported
    assert len(caster.hand) == 3, "the draw happens first"
    assert game.confirm_optional_pay(0, accept=False), "the caster declines"
    assert _w1g1_owed(game) == [1]
    assert game.confirm_optional_pay(1, accept=True)
    game.auto_resolve_pending_choices()

    assert caster.hand == []
    assert sorted(c.name for c in caster.graveyard) == [
        "Forest", "Island", "Rhystic Scrying", "Swamp",
    ]
    assert [c.name for c in payer.hand] == ["Mountain"]
    assert _w1g1_tapped(game, 1) == 2


def test_rhystic_scrying_keeps_the_cards_when_no_one_pays(set_pool):
    """Left to the AI defaults: the caster never buys its own discard, and an
    opponent with no mana cannot — so the three cards stay."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(4, 0))
    caster = game.players[0]
    caster.hand.append(set_pool("PCY")["Rhystic Scrying"])
    caster.library.extend([lea["Island"], lea["Forest"], lea["Swamp"]])

    assert game.cast_from_hand(0, "Rhystic Scrying").supported
    game.auto_resolve_pending_choices()

    assert sorted(c.name for c in caster.hand) == ["Forest", "Island", "Swamp"]
    assert _w1g1_tapped(game, 0) == 0


def test_rhystic_syphon_drains_a_target_player_who_cannot_pay(set_pool):
    """"Unless target player pays {3}, that player loses 5 life and you gain 5
    life." One seat is offered — the one the spell targeted — and two Islands
    do not cover {3}."""
    game = _w1g1_sorcery_table(set_pool, lands=(0, 2))
    syphon = set_pool("PCY")["Rhystic Syphon"]
    game.players[0].hand.append(syphon)

    assert derive_cast_spec(syphon, compile_card_oracle(syphon)) == {"kind": "player"}
    assert game.cast_from_hand(0, "Rhystic Syphon", target_player_index=1).supported
    game.auto_resolve_pending_choices()

    assert (game.players[0].life, game.players[1].life) == (25, 15)


def test_rhystic_syphon_is_paid_off_by_the_target_alone(set_pool):
    """The offer goes to the target and nobody else: with three Islands the
    target pays, and the caster's own untapped lands are never asked."""
    game = _w1g1_sorcery_table(set_pool, lands=(5, 3))
    game.players[0].hand.append(set_pool("PCY")["Rhystic Syphon"])

    assert game.cast_from_hand(0, "Rhystic Syphon", target_player_index=1).supported
    assert _w1g1_owed(game) == [1]
    game.auto_resolve_pending_choices()

    assert (game.players[0].life, game.players[1].life) == (20, 20)
    assert (_w1g1_tapped(game, 0), _w1g1_tapped(game, 1)) == (0, 3)


def test_flay_takes_a_second_random_card_from_a_target_who_cannot_pay(set_pool):
    """"Target player discards a card at random. Then **that player** discards
    **another** card at random unless they pay {1}." Both discards come from
    the one player the spell targeted — never the caster's hand — and with no
    mana the second is not bought off."""
    lea = set_pool("LEA")
    flay = set_pool("PCY")["Flay"]
    game = _w1g1_sorcery_table(set_pool, lands=(3, 0))
    caster, victim = game.players
    caster.hand.extend([flay, lea["Forest"]])
    victim.hand.extend([lea["Island"], lea["Swamp"], lea["Mountain"]])

    assert derive_cast_spec(flay, compile_card_oracle(flay)) == {"kind": "player"}
    assert game.cast_from_hand(0, "Flay", target_player_index=1).supported
    game.auto_resolve_pending_choices()

    assert len(victim.hand) == 1 and len(victim.graveyard) == 2
    assert [c.name for c in caster.hand] == ["Forest"], "the caster discards nothing"


def test_flay_second_discard_is_bought_off_by_the_target_alone(set_pool):
    """The offer is the target's: one Island pays {1}, so only the first card
    goes. The caster is never asked."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(3, 1))
    caster, victim = game.players
    caster.hand.append(set_pool("PCY")["Flay"])
    victim.hand.extend([lea["Island"], lea["Swamp"], lea["Mountain"]])

    assert game.cast_from_hand(0, "Flay", target_player_index=1).supported
    assert _w1g1_owed(game) == [1]
    game.auto_resolve_pending_choices()

    assert len(victim.hand) == 2 and len(victim.graveyard) == 1
    assert (_w1g1_tapped(game, 0), _w1g1_tapped(game, 1)) == (0, 1)
