"""Urza's Legacy creatures.

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


# --- W1G1: a quantity the sentence that spends it produced ---
#
# Three creatures whose numbers are counted rather than printed: what the
# ability's own cost took off (Molten Hydra), what an earlier step of the same
# sentence destroyed (Viashino Heretic), and what every hand at the table holds
# (Multani). Each test drives the card in a game and reads the outcome — an
# assertion about instruction kinds would pass on a card that resolved to zero.

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack as _g1_resolve


def _g1_untired(perm):
    """*perm* with its summoning sickness cleared, returned for chaining.

    ``_g1_`` prefixed and ending on ``return perm`` — SET_PLAYBOOK.md's note
    about a mechanical union splicing one helper's body onto another's
    signature.
    """
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g1_two_seats(*, mine=(), theirs=(), hand=()):
    """Two seats, mana enforcement off, seat 0 holding *mine*. Ends on the
    three-tuple so no union can graft another helper onto this signature."""
    seat0 = PlayerState(
        name="G1-A", battlefield=[_g1_untired(p) for p in mine], hand=list(hand),
    )
    seat1 = PlayerState(name="G1-B", battlefield=[_g1_untired(p) for p in theirs])
    game = Game(players=[seat0, seat1])
    game.enforce_mana_costs = False
    return game, seat0, seat1


# Molten Hydra — "{T}, Remove all +1/+1 counters from this creature: It deals
# damage to any target equal to the number of +1/+1 counters removed this way."


def test_g1_molten_hydra_deals_the_counters_its_cost_removed(set_pool):
    """CR 601.2h pays the cost before the ability is on the stack, so by the
    time the damage resolves the creature holds no counters at all — the number
    can only come from what the *payment* recorded.

    The refusal this replaces was a parse: "+1/+1" is a power/toughness token
    rather than a word, so the reader that claims "<kind> counters removed this
    way" saw no kind and the whole ability refused at the noun parser behind it.
    """
    hydra = Permanent(card=set_pool("ULG")["Molten Hydra"])
    game, _mine, theirs = _g1_two_seats(mine=[hydra])
    for _ in range(3):
        game.activate_permanent_ability(0, "Molten Hydra", ability_index=0)
        _g1_resolve(game)
    assert (hydra.effective_power, hydra.effective_toughness) == (4, 4)

    game.activate_permanent_ability(
        0, "Molten Hydra", ability_index=1, target_player_index=1,
    )
    _g1_resolve(game)

    assert theirs.life == 17, "three counters came off, three damage"
    assert hydra.metadata.get("plus_counters", 0) == 0
    assert (hydra.effective_power, hydra.effective_toughness) == (1, 1), (
        "CR 122.1a: the counters took their power and toughness with them"
    )


def test_g1_molten_hydra_with_no_counters_deals_none(set_pool):
    """"Remove **all**" of nothing removes nothing, which CR 601.2h permits —
    so the ability is activatable and the damage is zero rather than the
    creature's power or a printed number the card never names."""
    hydra = Permanent(card=set_pool("ULG")["Molten Hydra"])
    game, _mine, theirs = _g1_two_seats(mine=[hydra])

    result = game.activate_permanent_ability(
        0, "Molten Hydra", ability_index=1, target_player_index=1,
    )
    _g1_resolve(game)

    assert result.supported, result.details
    assert theirs.life == 20


# Viashino Heretic — "{1}{R}, {T}: Destroy target artifact. This creature deals
# damage to that artifact's controller equal to the artifact's mana value."


def test_g1_viashino_heretic_burns_for_the_destroyed_artifacts_mana_value(set_pool):
    """The number is about an object that is in a graveyard by the time the
    second sentence runs (CR 400.7), so it is the last-known information the
    destroy step froze (CR 608.2h) — read off the board it would be nothing.

    Su-Chi's mana value is 4.
    """
    heretic = Permanent(card=set_pool("ULG")["Viashino Heretic"])
    victim = Permanent(card=set_pool("ATQ")["Su-Chi"])
    game, _mine, theirs = _g1_two_seats(mine=[heretic], theirs=[victim])

    result = game.activate_permanent_ability(
        0, "Viashino Heretic", target_player_index=1, target_permanent_index=0,
    )
    _g1_resolve(game)

    assert result.supported, result.details
    assert [p.card.name for p in game.controlled_by(1)] == []
    assert theirs.life == 16


def test_g1_viashino_heretic_burns_its_own_controller_for_their_artifact(set_pool):
    """"That artifact's controller" is whoever controlled the artifact, not
    whoever activated the ability — the printed sentence names an object's seat
    and nothing about the card says it is an opponent's."""
    heretic = Permanent(card=set_pool("ULG")["Viashino Heretic"])
    mine = Permanent(card=set_pool("ATQ")["Su-Chi"])
    game, seat0, theirs = _g1_two_seats(mine=[heretic, mine])

    game.activate_permanent_ability(
        0, "Viashino Heretic", target_player_index=0, target_permanent_index=1,
    )
    _g1_resolve(game)

    assert seat0.life == 16, "the artifact was theirs, so the damage is theirs"
    assert theirs.life == 20


def test_g1_viashino_heretic_scales_with_the_artifact_not_a_printed_number(set_pool):
    """The control on the test above: nothing about the Heretic is a fixed 4.
    An Ornithopter costs nothing, so the artifact dies for free (CR 120.8 makes
    0 damage no damage at all)."""
    heretic = Permanent(card=set_pool("ULG")["Viashino Heretic"])
    victim = Permanent(card=set_pool("ATQ")["Ornithopter"])
    game, _mine, theirs = _g1_two_seats(mine=[heretic], theirs=[victim])

    game.activate_permanent_ability(
        0, "Viashino Heretic", target_player_index=1, target_permanent_index=0,
    )
    _g1_resolve(game)

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert theirs.life == 20


# Multani, Maro-Sorcerer — "Multani's power and toughness are each equal to the
# total number of cards in all players' hands." (CR 604.3.)


def test_g1_multani_counts_every_players_hand(set_pool):
    """CR 400.1 gives each player their own hand, so "all players' hands" is one
    pile per seat rather than one shared zone — a count scoped to the
    controller's own hand is the wrong number the moment anybody else holds a
    card."""
    multani = Permanent(card=set_pool("ULG")["Multani, Maro-Sorcerer"])
    # Any card at all: what the count reads is how many are held, never what
    # they are. Urza's Legacy prints no basic land, so the filler comes from a
    # set that does.
    forest = set_pool("MIR")["Forest"]
    game, _seat0, seat1 = _g1_two_seats(mine=[multani], hand=[forest, forest])
    seat1.hand = [forest, forest, forest]
    game._settle()

    assert (multani.effective_power, multani.effective_toughness) == (5, 5)


def test_g1_multani_is_recomputed_as_the_hands_change(set_pool):
    """CR 604.3: a characteristic-defining ability is not a one-off stamp. A
    fresh board per reading rather than one mutated in place, so the assertion
    is about the derivation and not about whatever refreshed last."""
    pool = set_pool("ULG")
    forest = set_pool("MIR")["Forest"]
    sizes = {}
    for mine, theirs in ((2, 3), (4, 1), (1, 0)):
        multani = Permanent(card=pool["Multani, Maro-Sorcerer"])
        game, _seat0, seat1 = _g1_two_seats(mine=[multani], hand=[forest] * mine)
        seat1.hand = [forest] * theirs
        game._settle()
        sizes[(mine, theirs)] = multani.effective_power

    assert sizes == {(2, 3): 5, (4, 1): 5, (1, 0): 1}


def test_g1_multani_keeps_its_shroud(set_pool):
    """The card's other line, asserted because the P/T half is read by a
    derivation table and the keyword by the compiler — a change to either could
    have taken the other's line with it."""
    program = compile_card_oracle(set_pool("ULG")["Multani, Maro-Sorcerer"])

    assert program.supported
    assert "shroud" in program.static_lines


def test_g1_maro_still_counts_one_hand(set_pool):
    """The control on Multani: Mirage's Maro prints the same sentence over
    "cards in **your** hand", and the two must stay different counts. Both are
    read by one row of the characteristic-defining table, so a scope widened for
    one of them would silently widen the other."""
    maro = Permanent(card=set_pool("MIR")["Maro"])
    forest = set_pool("MIR")["Forest"]
    game, _seat0, seat1 = _g1_two_seats(mine=[maro], hand=[forest] * 4)
    seat1.hand = [forest] * 3
    game._settle()

    assert (maro.effective_power, maro.effective_toughness) == (4, 4)
