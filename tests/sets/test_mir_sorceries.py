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


# --- W1G3: damage / prevention / life ---

from engine import Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent


def _w1g3_cast(set_pool, spell, own=(), theirs=(), **kwargs):
    """Cast *spell* from seat 0 with the named permanents on each battlefield."""
    pool = set_pool("MIR")
    mine = [_W1G3Permanent(card=pool[name]) for name in own]
    yours = [_W1G3Permanent(card=pool[name]) for name in theirs]
    game = Game(players=[
        _W1G3PlayerState(name="P1", battlefield=mine, hand=[pool[spell]],
                         library=[pool["Island"]] * 5),
        _W1G3PlayerState(name="P2", battlefield=yours,
                         library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(0, spell, **kwargs)
    assert result.supported, result.details
    game.resolve_stack()
    return game, mine, yours


def test_kaerveks_hex_deals_the_additional_point_only_to_green(set_pool):
    """"deals 1 damage to each nonblack creature **and an additional 1 damage
    to each green creature**."

    The rider is a second damage clause, so a green nonblack creature takes
    both points and a green creature is not exempted from the first. The black
    creature takes neither, which is what makes this a test of the *first*
    clause's narrowing as well: a reader that dropped "nonblack" would kill it.
    """
    game, mine, yours = _w1g3_cast(
        set_pool, "Kaervek's Hex",
        own=["Zhalfirin Commander"],       # white, 2/2 — first clause only
        theirs=["Cadaverous Knight",       # black — neither clause
                "Wild Elephant"],          # green 3/3 — both clauses
    )

    assert mine[0].damage_marked == 1
    assert yours[0].damage_marked == 0
    assert yours[1].damage_marked == 2


def test_tropical_storm_reads_the_other_printed_word_order(set_pool):
    """"deals X damage to each creature with flying **and 1 additional damage
    to each blue creature**."

    The same rider with "additional" printed after the number instead of before
    it. Both spellings reach one production: a blue flier takes X+1, a blue
    ground creature takes only the 1, and a non-blue ground creature takes
    nothing at all — the third is what proves the first clause kept its
    ``with_keywords`` narrowing rather than becoming a board sweep.
    """
    game, mine, yours = _w1g3_cast(
        set_pool, "Tropical Storm",
        own=["Zhalfirin Commander"],       # white, no flying — neither clause
        theirs=["Wall of Corpses",         # black, no flying — neither
                "Azimaet Drake"],          # blue 1/3 flier — both clauses
        x_value=1,
    )

    assert mine[0].damage_marked == 0
    assert yours[0].damage_marked == 0
    assert yours[1].damage_marked == 2


def test_reign_of_chaos_asks_for_a_land_by_its_printed_subtype(set_pool):
    """"Destroy target **Plains** and target white creature."

    Two independent target roles, which the picker has read since Fumarole —
    the only thing refusing this card was the *name* of the first slot, because
    "Plains" is a subtype and the role namer read card types alone. The land is
    destroyed by the slot that names it and the untargeted Island is not, which
    is what proves the slot kept its filter rather than becoming "any land".
    """
    pool = set_pool("MIR")
    plains = _W1G3Permanent(card=pool["Plains"])
    island = _W1G3Permanent(card=pool["Island"])
    knight = _W1G3Permanent(card=pool["Zhalfirin Commander"])   # white
    zombie = _W1G3Permanent(card=pool["Cadaverous Knight"])     # black
    game = Game(players=[
        _W1G3PlayerState(name="P1", hand=[pool["Reign of Chaos"]],
                         library=[pool["Island"]] * 5),
        _W1G3PlayerState(name="P2", battlefield=[plains, island, knight, zombie],
                         library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    result = game.cast_from_hand(
        0, "Reign of Chaos", mode_index=0,
        target_permanent_ids=[plains.permanent_id, knight.permanent_id],
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert not game.is_on_battlefield(plains)
    assert not game.is_on_battlefield(knight)
    assert game.is_on_battlefield(island)
    assert game.is_on_battlefield(zombie)
