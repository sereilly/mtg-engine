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


# --- W2G5: Meltdown — a sweep the announcement sizes ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g5s_artifact_board(set_pool, catalog_by_name, *names):
    """Meltdown in seat 0's hand, *names* on seat 1's battlefield."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    for name in names:
        game._put_permanent_onto_battlefield(
            1, Permanent(card=catalog_by_name[name]), None
        )
    alice.hand = [set_pool("USG")["Meltdown"]]
    return game


def test_meltdown_destroys_exactly_the_artifacts_x_reaches(set_pool, catalog_by_name):
    """"Destroy each artifact with mana value X or less."

    The bound is not printed — it is the X announced as the spell is cast
    (CR 601.2b) — and it reaches the *filter* rather than an amount, which is
    why the payload carries the same "x" string every amount does and the
    single dispatch point resolves it.

    Three X values in three games, because a sweep that ignored the bound
    would destroy everything and one that read it as zero would destroy the
    two free artifacts — and either would look right at whichever number a
    single-value test happened to pick.
    """
    board = ("Black Lotus", "Howling Mine", "Jayemdae Tome")

    game = _g5s_artifact_board(set_pool, catalog_by_name, *board)
    game.cast_from_hand(0, "Meltdown", x_value=0)
    resolve_stack(game)
    assert sorted(p.card.name for p in game.controlled_by(1)) == [
        "Howling Mine", "Jayemdae Tome",
    ]

    game = _g5s_artifact_board(set_pool, catalog_by_name, *board)
    game.cast_from_hand(0, "Meltdown", x_value=2)
    resolve_stack(game)
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Jayemdae Tome"]

    game = _g5s_artifact_board(set_pool, catalog_by_name, *board)
    game.cast_from_hand(0, "Meltdown", x_value=4)
    resolve_stack(game)
    assert not list(game.controlled_by(1))


def test_meltdown_leaves_nonartifacts_alone(set_pool, catalog_by_name):
    """The type narrowing survives the variable bound: a creature well inside
    any X is still outside the sweep.

    Grizzly Bears rather than Ornithopter, which reads like the obvious control
    and is not: CR 205.1b makes an artifact creature an artifact, so Meltdown
    destroys it and the "control" would have proved the opposite of what it
    looked like.
    """
    game = _g5s_artifact_board(
        set_pool, catalog_by_name, "Black Lotus", "Grizzly Bears",
    )
    game.cast_from_hand(0, "Meltdown", x_value=9)
    resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


# --- W2G5: Befoul — a union whose members are narrowed differently ---
def _g5b_board(set_pool, catalog_by_name, *names):
    """Befoul in seat 0's hand, *names* on seat 1's battlefield."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    made = []
    for name in names:
        perm = Permanent(card=catalog_by_name[name])
        game._put_permanent_onto_battlefield(1, perm, None)
        made.append(perm)
    alice.hand = [set_pool("USG")["Befoul"]]
    return game, made


def test_befoul_destroys_either_half_of_its_union(set_pool, catalog_by_name):
    """"Destroy target land or nonblack creature. It can't be regenerated."

    The census blamed the no-regeneration rider; the sentence refuses **without
    it**, because a type union cannot carry a narrowing on one member. Both
    halves are asserted in the same game: a land the black opponent controls
    is a legal target, which is the case an ``exclude_colors`` on the whole
    filter would have wrongly refused.
    """
    game, (swamp,) = _g5b_board(set_pool, catalog_by_name, "Swamp")

    game.cast_from_hand(
        0, "Befoul", target_player_index=1,
        target_permanent_ids=[swamp.permanent_id],
    )
    resolve_stack(game)

    assert not list(game.controlled_by(1))
    assert [c.name for c in game.players[1].graveyard] == ["Swamp"]


def test_befoul_refuses_a_black_creature(set_pool, catalog_by_name):
    """The narrowing that only reaches the *second* member: a black creature is
    no target, while a green one is.

    Dropped, the spell would kill anything; applied to the whole phrase, it
    would spare a black player's lands. Both halves in one test, because either
    failure passes the other's assertion.
    """
    game, (zombie, bears) = _g5b_board(
        set_pool, catalog_by_name, "Scathe Zombies", "Grizzly Bears",
    )

    refused = game.cast_from_hand(
        0, "Befoul", target_player_index=1,
        target_permanent_ids=[zombie.permanent_id],
    )
    assert not refused.supported, "a black creature is not a legal target"
    assert [c.name for c in game.players[0].hand] == ["Befoul"]

    game.cast_from_hand(
        0, "Befoul", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Scathe Zombies"]


def test_befoul_carries_its_no_regeneration_rider(set_pool, catalog_by_name):
    """"It can't be regenerated." The rider the census named, which was never
    the refusal — but it is still a rider, and a union that consumed the noun
    phrase and dropped this would be the bug class the other way round.
    """
    game, (bears,) = _g5b_board(set_pool, catalog_by_name, "Grizzly Bears")
    program = compile_card_oracle(set_pool("USG")["Befoul"])

    assert program.instructions[0].payload["bypass_regeneration"] is True
