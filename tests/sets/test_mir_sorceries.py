"""Per-card tests for Mirage's sorceries.

See tests/sets/README.md for the convention: get cards through
``set_pool("MIR")`` / ``set_cards("MIR")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained round sections, each headed
``# --- Round N: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared header
loses it in exactly that move — a ``NameError`` at collection, found only after
the merge is committed. A self-contained block cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block. The integrator compares every branch's copy of this header against the
merge base byte for byte; a branch that changed it is a branch whose block
cannot be appended mechanically.
"""

from __future__ import annotations


# --- Round 6: narrowings the sweep and the tuck were dropping ---

from engine import Game, PlayerState
from engine.models import Permanent


def _r6_cast(set_pool, spell: str, own=(), theirs=()):
    pool = set_pool("MIR")
    mine = [Permanent(card=pool[name]) for name in own]
    yours = [Permanent(card=pool[name]) for name in theirs]
    game = Game(players=[
        PlayerState(name="P1", battlefield=mine, hand=[pool[spell]],
                    library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=yours, library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(0, spell)
    assert result.supported, result.details
    game.resolve_stack()
    return game, mine, yours


def test_blinding_light_taps_only_the_nonwhite(set_pool):
    """"Tap all **nonwhite** creatures."

    The sweep already resolves through ``subject_matches``, which tests
    ``exclude_colors`` like any other key — the whitelist in the lowering was
    the only thing refusing the word. Dropping it instead would have tapped the
    caster's own white team, which is the direction a dropped narrowing on a
    sweep always goes.
    """
    game, mine, yours = _r6_cast(
        set_pool, "Blinding Light",
        own=["Femeref Knight"],            # white
        theirs=["Cadaverous Knight"],      # black
    )

    assert not mine[0].tapped
    assert yours[0].tapped


def test_fallow_earth_tucks_a_land(set_pool):
    """"Put target land on top of its owner's library." The other card the
    creature-pinned tuck refused."""
    pool = set_pool("MIR")
    land = Permanent(card=pool["Island"])
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Fallow Earth"]], library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=[land], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(
        0, "Fallow Earth", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert not game.is_on_battlefield(land)
    assert game.players[1].library[0].name == "Island"


# --- W1G5: the statics / characteristics / control family ---

from engine import Game, PlayerState
from engine.models import Permanent


def _g5_game(pool, hand, battlefield=(), opponent=()):
    game = Game(players=[
        PlayerState(name="P1", hand=[pool[name] for name in hand],
                    battlefield=list(battlefield),
                    library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=list(opponent),
                    library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_choking_sands_damages_only_over_a_nonbasic_land(set_pool):
    """"Destroy target non-Swamp land. **If that land was nonbasic**, this spell
    deals 2 damage to the land's controller."

    Both halves already worked apart. What refused was the condition's printed
    shape: Icequake's "if that land was **a snow land**" spells the head noun
    out and this one leaves it off, because the sentence supplied it two words
    earlier. The adjective run is lifted out, the noun put back, and the result
    handed to the same noun parser — so "nonbasic" is the same restriction here
    as in any target's description.
    """
    pool = set_pool("MIR")
    game = _g5_game(
        pool, ["Choking Sands"],
        opponent=[Permanent(card=pool["Bad River"]), Permanent(card=pool["Forest"])],
    )
    river = game.players[1].battlefield[0]

    cast = game.cast_from_hand(0, "Choking Sands", target_player_index=1,
                               target_permanent_index=0)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(river)
    assert game.players[1].life == 18, "a nonbasic land takes the 2 damage"


def test_choking_sands_spares_a_basic_lands_controller(set_pool):
    """The other arm of the same condition. Dropping it would have made the
    damage unconditional, which is a strictly better card than the printed
    one."""
    pool = set_pool("MIR")
    game = _g5_game(
        pool, ["Choking Sands"],
        opponent=[Permanent(card=pool["Forest"])],
    )
    forest = game.players[1].battlefield[0]

    cast = game.cast_from_hand(0, "Choking Sands", target_player_index=1,
                               target_permanent_index=0)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(forest)
    assert game.players[1].life == 20
