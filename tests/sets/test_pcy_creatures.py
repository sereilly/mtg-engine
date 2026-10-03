"""Prophecy creatures.

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


# --- W1G6: tokens, zones and triggers ---
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.tokens import make_token_card as _w1g6_make_token_card
from tests.helpers import _mk_card as _w1g6_mk_card, resolve_stack as _w1g6_resolve


def _w1g6_permanent(game, seat, card, *, token=False):
    perm = _W1G6Permanent(card=card)
    if token:
        perm.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g6_two_seat_game(**p1_zones):
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0"), _W1G6PlayerState(name="P1", **p1_zones),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    return game  # _w1g6_two_seat_game


def _w1g6_tuck_test(set_pool, informer_name, subtype):
    pcy = set_pool("PCY")
    library_top = _w1g6_mk_card("Library Top", "Sorcery")
    game = _w1g6_two_seat_game(library=[library_top])
    informer = _w1g6_permanent(game, 0, pcy[informer_name])
    victim = _w1g6_permanent(
        game, 1, _w1g6_mk_card(f"Hired {subtype}", f"Creature — Human {subtype}")
    )
    token = _w1g6_permanent(game, 1, _w1g6_make_token_card(
        f"{subtype} Token", 1, 1, f"Creature — {subtype}"), token=True)
    bystander = _w1g6_permanent(game, 1, _w1g6_mk_card("Bear", "Creature — Bear"))

    # "nontoken" and the creature type are both the picker's answer, so a
    # token of the type and a creature of another type are refused before any
    # cost is paid.
    for refused in (token, bystander):
        result = game.activate_permanent_ability(
            0, informer_name, target_permanent_ids=[refused.permanent_id]
        )
        assert not result.supported, refused.card.name
    assert not game.stack

    result = game.activate_permanent_ability(
        0, informer_name, target_permanent_ids=[victim.permanent_id]
    )
    assert result.supported, result.details
    _w1g6_resolve(game)

    assert not game.is_on_battlefield(victim)
    # The bottom, not the top: the card on top stays where it was.
    assert [c.name for c in game.players[1].library] == [
        "Library Top", f"Hired {subtype}",
    ]
    assert game.is_on_battlefield(token) and game.is_on_battlefield(bystander)
    assert game.is_on_battlefield(informer)
    assert any("on the bottom of" in line for line in game.log)


def test_w1g6_mercenary_informer_bottoms_a_nontoken_mercenary(set_pool):
    """"{2}{W}: Put target nontoken Mercenary on the bottom of its owner's
    library." The owner's library, the bottom end, and only a nontoken
    Mercenary is a legal target."""
    _w1g6_tuck_test(set_pool, "Mercenary Informer", "Mercenary")


def test_w1g6_rebel_informer_bottoms_a_nontoken_rebel(set_pool):
    """"{3}: Put target nontoken Rebel on the bottom of its owner's library.\""""
    _w1g6_tuck_test(set_pool, "Rebel Informer", "Rebel")


def test_w1g6_thresher_beast_makes_the_defending_player_sacrifice_a_land(set_pool):
    """"Whenever this creature becomes blocked, defending player sacrifices a
    land of their choice." The defending seat sacrifices — not the attacker,
    who also controls a land — and only once it is blocked."""
    pcy = set_pool("PCY")
    game = _w1g6_two_seat_game()
    beast = _w1g6_permanent(game, 0, pcy["Thresher Beast"])
    my_land = _w1g6_permanent(game, 0, _w1g6_mk_card("Forest", "Basic Land — Forest"))
    blocker = _w1g6_permanent(game, 1, _w1g6_mk_card("Bear", "Creature — Bear"))
    for name in ("Mountain", "Island"):
        _w1g6_permanent(game, 1, _w1g6_mk_card(name, f"Basic Land — {name}"))

    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [game.players[0].battlefield.index(beast)])[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert len([p for p in game.controlled_by(1) if p.card.type_line.startswith("Basic")]) == 2
    assert game.declare_blockers(1, {game.players[1].battlefield.index(blocker): 0})[0]
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()

    their_lands = [p.card.name for p in game.controlled_by(1) if p.card.name != "Bear"]
    assert len(their_lands) == 1, their_lands
    assert len(game.players[1].graveyard) == 1
    assert game.players[1].graveyard[0].name in ("Mountain", "Island")
    assert game.is_on_battlefield(my_land)
    assert not game.players[0].graveyard
