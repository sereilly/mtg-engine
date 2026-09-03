"""Per-card tests for Mirage's artifacts.

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


# --- Round 4: a player-quantity intervening-if (CR 603.4) ---

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _r4_board(set_pool, artifact_name: str, *, opponent_hand: int = 0,
              opponent_life: int = 20):
    """The artifact on seat 0, with seat 1's hand and life set to taste.

    Seat 1 is the one every card in this section asks about — each fires on an
    opponent's step and tests *that player*, which is the referent the round was
    really about.
    """
    pool = set_pool("MIR")
    artifact = Permanent(card=pool[artifact_name])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[artifact], library=[pool["Island"]] * 8),
        PlayerState(
            name="P2", hand=[pool["Island"]] * opponent_hand,
            library=[pool["Island"]] * 8,
        ),
    ])
    game.players[1].life = opponent_life
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


@pytest.mark.parametrize(
    "name", ["Misers' Cage", "Paupers' Cage", "Razor Pendulum"]
)
def test_the_three_cages_compile_supported(set_pool, name):
    """All three print one shape with the threshold as data — "at the beginning
    of each <player>'s <step>, if that player has <N or more/fewer> <quantity>,
    this artifact deals 2 damage to that player" — so they are one production
    asked three ways rather than three cards."""
    program = compile_card_oracle(set_pool("MIR")[name])
    assert program.supported, program.reason


def test_misers_cage_fires_on_a_full_hand(set_pool):
    """"…if that player has five or more cards in hand, this artifact deals 2
    damage to that player." """
    game = _r4_board(set_pool, "Misers' Cage", opponent_hand=5)

    game.start_turn(1)
    game.resolve_stack()

    assert game.players[1].life == 20 - 2 - 0 or game.players[1].life == 18


def test_misers_cage_holds_below_the_threshold(set_pool):
    """CR 603.4: the intervening-if is checked when the trigger would go on the
    stack, so four cards in hand is no trigger at all. Read the *seat* as well
    as the number — the clause says "that player", and a version that fell back
    to the caster would have damaged the Cage's own controller."""
    game = _r4_board(set_pool, "Misers' Cage", opponent_hand=4)

    game.start_turn(1)
    game.resolve_stack()

    assert game.players[1].life == 20
    assert game.players[0].life == 20


def test_paupers_cage_reads_the_other_end_of_the_same_comparison(set_pool):
    """"…if that player has **two or fewer** cards in hand".

    "Fewer" is English's countable spelling of "less" and the comparison parser
    knew only "less" — so every printed threshold over a countable noun refused.
    The two cages are the pair that shows the word is data.
    """
    game = _r4_board(set_pool, "Paupers' Cage", opponent_hand=2)
    game.start_turn(1)
    game.resolve_stack()
    assert game.players[1].life == 18

    game = _r4_board(set_pool, "Paupers' Cage", opponent_hand=3)
    game.start_turn(1)
    game.resolve_stack()
    assert game.players[1].life == 20


def test_razor_pendulum_reads_a_life_total(set_pool):
    """"At the beginning of each player's end step, if that player has 5 or less
    life, this artifact deals 2 damage to that player."

    A life total is not a pile, which is why it is its own condition kind rather
    than a zone count with an invented zone name — but it is the same printed
    shape and shares the seat reader with it.
    """
    game = _r4_board(set_pool, "Razor Pendulum", opponent_life=5)
    game.start_turn(1)
    game.resolve_end_step(1)
    game.resolve_stack()
    assert game.players[1].life == 3

    game = _r4_board(set_pool, "Razor Pendulum", opponent_life=6)
    game.start_turn(1)
    game.resolve_end_step(1)
    game.resolve_stack()
    assert game.players[1].life == 6


# --- W1G5: the statics / characteristics / control family ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _g5_bear(name: str = "Bear", power: int = 2, toughness: int = 5) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _g5_chariot(set_pool):
    """Chariot of the Sun on seat 0 beside a 2/5, ready to activate."""
    pool = set_pool("MIR")
    chariot = Permanent(card=pool["Chariot of the Sun"])
    chariot.metadata["summoning_sickness_turn"] = -1
    bear = Permanent(card=_g5_bear())
    game = Game(players=[
        PlayerState(name="P1", battlefield=[chariot, bear],
                    library=[pool["Island"]] * 5),
        PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    return game, bear


def test_chariot_of_the_sun_grants_flying_and_rewrites_the_toughness(set_pool):
    """"{2}, {T}: Until end of turn, target creature you control **gains flying
    and has base toughness 1**."

    Two things were missing and they are one sentence. ``has base toughness N``
    had no branch — the production demanded "power", so the toughness-only half
    of CR 613.4b's rewrite could not be spelled at all, though ``set_base_pt``'s
    None has expressed it since People of the Woods. And the conjunction is an
    arm of the grant beside "and gets", "and loses" and "and \\"…\\"", under the
    same duration rule: whichever half prints one governs both, and the leading
    "Until end of turn" this card uses is distributed by the sentence layer.
    """
    game, bear = _g5_chariot(set_pool)
    assert (bear.effective_power, bear.effective_toughness) == (2, 5)
    assert not game._has_keyword(bear, "flying")

    result = game.activate_permanent_ability(
        0, "Chariot of the Sun", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert game._has_keyword(bear, "flying")
    assert (bear.effective_power, bear.effective_toughness) == (2, 1), (
        "the printed power stands; only the toughness is rewritten"
    )


def test_the_chariots_rewrite_ends_with_the_turn(set_pool):
    """Both halves carry the one printed duration. A base P/T that outlived the
    turn would be the dropped-rider bug with the sign reversed — the creature
    stays a 2/1 for good."""
    game, bear = _g5_chariot(set_pool)
    game.activate_permanent_ability(
        0, "Chariot of the Sun", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game.resolve_stack()
    game._settle()

    game.resolve_cleanup_step(0)
    game._settle()

    assert not game._has_keyword(bear, "flying")
    assert (bear.effective_power, bear.effective_toughness) == (2, 5)


def test_cursed_totem_shuts_off_a_creatures_mana_ability(set_pool, catalog_by_name):
    """"Activated abilities of creatures can't be activated."

    The *board* half of CR 602.5, and the exact mirror of
    ``cast_restrictions.global_cast_ban`` one rule over: not a clause the
    ability prints about itself but a prohibition one permanent imposes on
    everybody, so it is read off the board at every activation.
    ``activation_denial`` is handed one printed line and rightly asks only
    about it, which is why this could not live there.

    **No mana-ability exception**, which is the whole of what the card does:
    CR 605 makes a mana ability an activated ability like any other and the
    sentence names no exception.
    """
    pool = set_pool("MIR")
    bird = Permanent(card=catalog_by_name["Birds of Paradise"])
    bird.metadata["summoning_sickness_turn"] = -1
    mox = Permanent(card=catalog_by_name["Mox Emerald"])
    mox.metadata["summoning_sickness_turn"] = -1
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bird, mox],
                    library=[catalog_by_name["Forest"]] * 5),
        PlayerState(name="P2", library=[catalog_by_name["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()

    assert game.activate_permanent_ability(
        0, "Birds of Paradise", permanent_index=0
    ).supported

    game.players[0].battlefield.append(Permanent(card=pool["Cursed Totem"]))
    game._settle()

    stopped = game.activate_permanent_ability(
        0, "Birds of Paradise", permanent_index=0
    )
    assert not stopped.supported
    assert "can't be activated" in stopped.details

    # It binds the type the sentence names and nothing else — a Mox is not a
    # creature, and the prohibition is read off `has_type` like every other
    # type question in this engine.
    assert game.activate_permanent_ability(
        0, "Mox Emerald", permanent_index=1
    ).supported


def test_cursed_totem_binds_its_own_controller_too(set_pool, catalog_by_name):
    """The sentence names nobody, so it binds everybody — including the seat
    that played it. Read as "your opponents'" it would be a strictly better
    card than the one printed."""
    pool = set_pool("MIR")
    bird = Permanent(card=catalog_by_name["Birds of Paradise"])
    bird.metadata["summoning_sickness_turn"] = -1
    game = Game(players=[
        PlayerState(name="P1", battlefield=[Permanent(card=pool["Cursed Totem"])],
                    library=[catalog_by_name["Forest"]] * 5),
        PlayerState(name="P2", battlefield=[bird],
                    library=[catalog_by_name["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()

    assert not game.activate_permanent_ability(
        1, "Birds of Paradise", permanent_index=0
    ).supported


def _g5_prison(set_pool):
    pool = set_pool("MIR")
    prison = Permanent(card=pool["Amber Prison"])
    prison.metadata["summoning_sickness_turn"] = -1
    bear = Permanent(card=CardDefinition(
        name="Bear", mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": "Bear", "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    ))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[prison], library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=[bear], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    result = game.activate_permanent_ability(
        0, "Amber Prison", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()
    return game, prison, bear


def test_amber_prison_holds_its_target_down_while_it_stays_tapped(set_pool):
    """"Tap target artifact, creature, or land. **That permanent** doesn't
    untap during its controller's untap step for as long as this artifact
    remains tapped."

    Every piece of this was already built — Phyrexian Gremlins prints the same
    linked restriction and Giant Oyster prints it with the duration in front.
    What refused was two words: ``parse_bound_subject`` reads "that
    <card type>", and "permanent" is a *generic* noun. It is the right word for
    this card and not a looser one: a sentence back-referencing a choice across
    three card types cannot say "that artifact", so the phrase carries no card
    type at all — which is exactly the narrowing it means.
    """
    game, prison, bear = _g5_prison(set_pool)
    assert bear.tapped and prison.tapped

    game.start_turn(1)
    game._settle()
    assert bear.tapped, "the Prison is still tapped"


def test_amber_prisons_grip_ends_when_it_untaps(set_pool):
    """"…for as long as this artifact remains tapped." The restriction is read
    off the source at the untap step rather than recorded on the creature, so
    the Prison untapping releases it with nothing to clear."""
    game, prison, bear = _g5_prison(set_pool)

    prison.tapped = False
    game.start_turn(1)
    game._settle()

    assert not bear.tapped
