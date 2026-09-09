"""Urza's Legacy lands.

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

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: the animated body — the two lands that animate into it ---
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _g2_land_board(set_pool, name):
    """*name* on Alice's battlefield, untapped and free of summoning sickness."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    land = Permanent(card=set_pool("ULG")[name])
    game._put_permanent_onto_battlefield(0, land, None)
    land.metadata["summoning_sickness_turn"] = -99
    return game, land


def test_ghitu_encampment_animates_with_first_strike(set_pool):
    """"{1}{R}: This land becomes a 2/1 red Warrior creature **with first
    strike** until end of turn. It's still a land."

    The land half of Opal Champion's gap, and the more instructive half: this
    card compiled *supported* — its mana ability carried it — while the
    animation was an ability part with no instruction behind it. It sat on
    `--hollow-lines` from the day of the ingest, which is the only instrument
    that could see it.
    """
    game, camp = _g2_land_board(set_pool, "Ghitu Encampment")

    result = game.activate_permanent_ability(
        0, "Ghitu Encampment", ability_index=1
    )

    assert result.supported, result.details
    assert camp.is_creature
    assert camp.has_type("warrior")
    assert (camp.effective_power, camp.effective_toughness) == (2, 1)
    assert camp.has_keyword("first strike")


def test_ghitu_encampment_stays_a_red_land(set_pool):
    """Two riders in the same sentence, both of which a partial reading drops.
    "It's still a land" is CR 205.1b's retention clause — an animated
    Encampment that stopped being a land would stop tapping for mana — and
    "red" is CR 613 layer 5, which is what a Circle of Protection: Red reads."""
    game, camp = _g2_land_board(set_pool, "Ghitu Encampment")
    assert game._effective_colors(camp) == set(), "a land prints no colour"

    game.activate_permanent_ability(0, "Ghitu Encampment", ability_index=1)

    assert camp.has_type("land")
    assert game._effective_colors(camp) == {"R"}


def test_spawning_pool_animates_and_grants_its_quoted_ability(set_pool):
    """"{1}{B}: This land becomes a 1/1 black Skeleton creature **with "{B}:
    Regenerate this creature"** until end of turn. It's still a land."

    The quoted-ability half of the same production. The lift that separates a
    printed ability from the body around it was anchored at the end of the
    line, so it matched Veiled Serpent — whose quote is the last thing printed —
    and did not match this card, whose duration and retention clause follow the
    closing quote. The tail is rejoined to the body rather than parsed apart,
    which is why both of those survive below.
    """
    game, pool = _g2_land_board(set_pool, "Spawning Pool")

    result = game.activate_permanent_ability(0, "Spawning Pool", ability_index=1)

    assert result.supported, result.details
    assert pool.is_creature and pool.has_type("skeleton")
    assert (pool.effective_power, pool.effective_toughness) == (1, 1)
    assert pool.has_type("land"), "It's still a land"
    assert game._effective_colors(pool) == {"B"}


def test_the_spawning_pool_can_then_regenerate_itself(set_pool):
    """The granted ability is a *printed line* on `engine/keywords`' text
    channel, so `Permanent.effective_card` folds it back into what the compiler
    reads and it becomes an ordinary activated ability. Asserted by activating
    it, not by reading the payload: a granted line nothing can activate is the
    hollow half of this card written one layer down.
    """
    game, pool = _g2_land_board(set_pool, "Spawning Pool")
    game.activate_permanent_ability(0, "Spawning Pool", ability_index=1)

    granted = compile_card_oracle(pool.effective_card).activated_abilities
    assert granted[-1].instruction.kind == "grant_regeneration_to_self"

    result = game.activate_permanent_ability(0, "Spawning Pool", ability_index=2)

    assert result.supported, result.details
    assert "regeneration shield" in game.log[-2]


def test_the_spawning_pools_grant_ends_with_its_body(set_pool):
    """The duration governs both halves. An until-end-of-turn animation whose
    granted ability outlived the cleanup sweep would leave a land saying
    something it no longer is — which is why the tail had to be *read* rather
    than dropped, and this is that assertion."""
    game, pool = _g2_land_board(set_pool, "Spawning Pool")
    game.activate_permanent_ability(0, "Spawning Pool", ability_index=1)

    def _g2_regenerations():
        return [
            ability
            for ability in compile_card_oracle(
                pool.effective_card
            ).activated_abilities
            if ability.instruction is not None
            and ability.instruction.kind == "grant_regeneration_to_self"
        ]

    assert _g2_regenerations(), "the animation granted it"

    game.resolve_cleanup_step(0)

    assert not pool.is_creature
    assert pool.has_type("land")
    assert not _g2_regenerations(), "and the sweep took it away with the body"
