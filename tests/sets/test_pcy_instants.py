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


# --- W1G1: rhystic ---
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _w1g1_instant_duel(set_pool, *, lands=(0, 0), active: int = 0) -> Game:
    """Two seats with ``lands[i]`` untapped Islands each, enforcement off."""
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(
            name=f"P{seat}", life=20,
            battlefield=[Permanent(card=island) for _ in range(count)],
        )
        for seat, count in enumerate(lands)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = active
    return game


def _w1g1_creature(game, set_pool, seat: int, name: str) -> Permanent:
    perm = Permanent(card=set_pool("LEA")[name])
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def _w1g1_lands_tapped(game, seat: int) -> int:
    return sum(
        1 for perm in game.controlled_by(game.players[seat])
        if perm.tapped and not perm.is_creature
    )


def test_excise_exiles_an_attacker_whose_controller_cannot_pay_x(set_pool):
    """"Exile target attacking creature unless its controller pays {X}." The
    offer is the creature's controller's, at the spell's announced X: one
    Island does not cover X = 2."""
    game = _w1g1_instant_duel(set_pool, lands=(0, 1), active=1)
    attacker = _w1g1_creature(game, set_pool, 1, "Grizzly Bears")
    attacker.attacking = True
    game.players[0].hand.append(set_pool("PCY")["Excise"])

    assert game.cast_from_hand(
        0, "Excise", x_value=2, target_permanent_ids=[attacker.permanent_id],
    ).supported
    game.auto_resolve_pending_choices()

    assert not game.is_on_battlefield(attacker)
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]


def test_excise_is_paid_off_by_the_attackers_controller(set_pool):
    """Two Islands cover X = 2, so the attacker stays — and the {X} came off
    its controller's board, not the caster's."""
    game = _w1g1_instant_duel(set_pool, lands=(3, 2), active=1)
    attacker = _w1g1_creature(game, set_pool, 1, "Grizzly Bears")
    attacker.attacking = True
    game.players[0].hand.append(set_pool("PCY")["Excise"])

    assert game.cast_from_hand(
        0, "Excise", x_value=2, target_permanent_ids=[attacker.permanent_id],
    ).supported
    assert [c.player_index for c in game.pending_choices] == [1]
    game.auto_resolve_pending_choices()

    assert game.is_on_battlefield(attacker)
    assert (_w1g1_lands_tapped(game, 0), _w1g1_lands_tapped(game, 1)) == (0, 2)


def test_excise_cannot_target_a_creature_that_is_not_attacking(set_pool):
    """"target **attacking** creature" — the narrowing is enforced at
    announcement and offered by the picker, not dropped."""
    excise = set_pool("PCY")["Excise"]
    game = _w1g1_instant_duel(set_pool, lands=(0, 0), active=1)
    idle = _w1g1_creature(game, set_pool, 1, "Grizzly Bears")
    game.players[0].hand.append(excise)

    assert derive_cast_spec(excise, compile_card_oracle(excise)) == {
        "kind": "creature", "attacking_only": True,
    }
    assert not game.cast_from_hand(
        0, "Excise", x_value=1, target_permanent_ids=[idle.permanent_id],
    ).supported
    assert game.is_on_battlefield(idle)


def test_wild_might_adds_the_second_pump_when_no_one_pays(set_pool):
    """"Target creature gets +1/+1 until end of turn. That creature gets **an
    additional** +4/+4 until end of turn unless any player pays {2}." One
    target, named once and pumped twice: +5/+5 when the opponent cannot pay."""
    wild_might = set_pool("PCY")["Wild Might"]
    game = _w1g1_instant_duel(set_pool, lands=(3, 1))
    bears = _w1g1_creature(game, set_pool, 0, "Grizzly Bears")
    game.players[0].hand.append(wild_might)

    assert derive_cast_spec(wild_might, compile_card_oracle(wild_might)) == {
        "kind": "creature",
    }, "one choice, asked once"
    assert game.cast_from_hand(
        0, "Wild Might", target_permanent_ids=[bears.permanent_id],
    ).supported
    game.auto_resolve_pending_choices()

    assert (bears.effective_power, bears.effective_toughness) == (7, 7)
    assert _w1g1_lands_tapped(game, 0) == 0, "the caster never pays its own toll"


def test_wild_might_keeps_only_the_first_pump_when_an_opponent_pays(set_pool):
    """Two Islands buy off the additional +4/+4; the first sentence's +1/+1 is
    not part of the offer and stays."""
    game = _w1g1_instant_duel(set_pool, lands=(0, 2))
    bears = _w1g1_creature(game, set_pool, 0, "Grizzly Bears")
    game.players[0].hand.append(set_pool("PCY")["Wild Might"])

    assert game.cast_from_hand(
        0, "Wild Might", target_permanent_ids=[bears.permanent_id],
    ).supported
    game.auto_resolve_pending_choices()

    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    assert _w1g1_lands_tapped(game, 1) == 2


def test_rhystic_shield_gives_every_creature_you_control_both_pumps(set_pool):
    """"Creatures you control get +0/+1 until end of turn. **They** get an
    additional +0/+2 …" — "they" is the set the first sentence named, so both
    of the caster's creatures get +0/+3 and the opponent's creature nothing."""
    game = _w1g1_instant_duel(set_pool, lands=(0, 0))
    bears = _w1g1_creature(game, set_pool, 0, "Grizzly Bears")
    giant = _w1g1_creature(game, set_pool, 0, "Hill Giant")
    theirs = _w1g1_creature(game, set_pool, 1, "Gray Ogre")
    game.players[0].hand.append(set_pool("PCY")["Rhystic Shield"])

    assert game.cast_from_hand(0, "Rhystic Shield").supported
    game.auto_resolve_pending_choices()

    assert (bears.effective_toughness, giant.effective_toughness) == (5, 6)
    assert theirs.effective_toughness == 2


def test_rhystic_shield_additional_toughness_is_bought_off_for_two(set_pool):
    """An opponent paying {2} leaves the first +0/+1 alone."""
    game = _w1g1_instant_duel(set_pool, lands=(0, 2))
    bears = _w1g1_creature(game, set_pool, 0, "Grizzly Bears")
    game.players[0].hand.append(set_pool("PCY")["Rhystic Shield"])

    assert game.cast_from_hand(0, "Rhystic Shield").supported
    game.auto_resolve_pending_choices()

    assert bears.effective_toughness == 3
    assert _w1g1_lands_tapped(game, 1) == 2
