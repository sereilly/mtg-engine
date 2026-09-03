"""Per-card tests for Mirage's instants.

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


# --- Round 2: phasing (CR 702.26) ---

import pytest

from engine import Game, PlayerState
from engine.models import Permanent


def _r2_ripple_board(set_pool, victim_name: str):
    """Reality Ripple in hand on seat 0, one permanent to aim it at on seat 1."""
    pool = set_pool("MIR")
    victim = Permanent(card=pool[victim_name])
    game = Game(players=[
        PlayerState(
            name="P1", hand=[pool["Reality Ripple"]],
            library=[pool["Island"]] * 6,
        ),
        PlayerState(name="P2", battlefield=[victim], library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, victim


@pytest.mark.parametrize(
    "victim_name", ["Sandbar Crocodile", "Island", "Charcoal Diamond"]
)
def test_reality_ripple_phases_out_all_three_printed_types(set_pool, victim_name):
    """"Target **artifact, creature, or land** phases out."

    The card was already reported supported, claimed every printed sentence and
    derived a correct picker — and the handler then declined two of the three
    types, because the type test was hardcoded to "creature" rather than read
    off the noun phrase the picker had already enumerated with. Nothing failed;
    the spell resolved and did nothing. That is the class only a game finds.
    """
    game, victim = _r2_ripple_board(set_pool, victim_name)

    result = game.cast_from_hand(
        0, "Reality Ripple", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert not game.is_on_battlefield(victim)
    assert victim in game.players[1].phased_out


def test_a_permanent_reality_ripple_phased_out_comes_back_once(set_pool):
    """The incoming half of CR 702.26a reads the holding list rather than the
    keyword, so a permanent with no phasing of its own returns exactly once and
    then stays."""
    game, victim = _r2_ripple_board(set_pool, "Island")
    game.cast_from_hand(
        0, "Reality Ripple", target_player_index=1, target_permanent_index=0
    )
    game.resolve_stack()

    game.start_turn(1)
    assert game.is_on_battlefield(victim)

    game.start_next_turn()
    game.start_next_turn()
    assert game.is_on_battlefield(victim)


# --- Round 6: a handler that pinned a type its card did not print ---

def test_disempower_tucks_either_of_its_printed_types(set_pool):
    """"Put target **artifact or enchantment** on top of its owner's library."

    Reality Ripple's defect, one file over and found the same way. The tuck
    lowering demanded ``card_types == ("creature",)`` and the handler asked
    ``is_creature`` — two copies of a narrowing the printed noun phrase does not
    have, on an effect that is the same for every permanent type: CR 400.3's
    owner lookup and the library move do not care what was moved.
    """
    pool = set_pool("MIR")
    for host_name in ("Charcoal Diamond", "Armor of Thorns"):
        host = Permanent(card=pool[host_name])
        game = Game(players=[
            PlayerState(name="P1", hand=[pool["Disempower"]],
                        library=[pool["Island"]] * 5),
            PlayerState(name="P2", battlefield=[host],
                        library=[pool["Island"]] * 5),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = set()
        result = game.cast_from_hand(
            0, "Disempower", target_player_index=1, target_permanent_index=0
        )
        assert result.supported, result.details
        game.resolve_stack()

        assert not game.is_on_battlefield(host)
        assert game.players[1].library[0].name == host_name


def test_disempower_still_refuses_a_creature(set_pool):
    """The narrowing is carried, not dropped — which is the other half of the
    fix. Widening the lowering to any noun phrase would be worth nothing if the
    handler then moved whatever it was handed."""
    pool = set_pool("MIR")
    creature = Permanent(card=pool["Femeref Knight"])
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Disempower"]], library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=[creature], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.cast_from_hand(
        0, "Disempower", target_player_index=1, target_permanent_index=0
    )
    game.resolve_stack()

    assert game.is_on_battlefield(creature)


# --- Round 9: the tutor cycle (CR 701.19 / 701.23) ---

from engine.search_filters import search_matches


def _r9_tutor(set_pool, spell: str, library_names: list[str]):
    """*spell* cast on seat 0 over a library built from *library_names*."""
    pool = set_pool("MIR")
    game = Game(players=[
        PlayerState(
            name="P1", hand=[pool[spell]],
            library=[pool[name] for name in library_names],
        ),
        PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    result = game.cast_from_hand(0, spell)
    assert result.supported, result.details
    game.resolve_stack()
    (choice,) = game.pending_choices
    assert choice.kind == "search_library"
    return game, choice


_R9_LIBRARY = [
    "Island", "Femeref Knight", "Charcoal Diamond", "Armor of Thorns", "Island",
]


def test_enlightened_tutor_finds_either_of_its_two_types(set_pool):
    """"Search your library for an **artifact or enchantment** card…"

    A printed union is an OR — the reading `any_colors` beside it already gets,
    and the one every noun-phrase matcher in this engine gives a multi-type
    filter. The lowering used to refuse a union outright ("the search picker
    tests one card type"), which was the safe direction and cost all three
    tutors their cards.
    """
    _game, choice = _r9_tutor(set_pool, "Enlightened Tutor", _R9_LIBRARY)

    assert choice.data["card_type"] == ("artifact", "enchantment")
    assert choice.data["destination"] == "library_top"


def test_enlightened_tutor_offers_only_the_matching_cards(set_pool):
    """The union narrows the search; it does not widen it."""
    game, choice = _r9_tutor(set_pool, "Enlightened Tutor", _R9_LIBRARY)

    legal = {
        card.name for card in game.players[0].library
        if search_matches(card, choice.data)
    }

    assert legal == {"Charcoal Diamond", "Armor of Thorns"}


def test_a_tutor_puts_its_find_on_top_after_the_shuffle(set_pool):
    """"…, reveal it, **then shuffle and put that card on top**."

    The order is the effect. Placing the find first and then shuffling — which
    is what falling through to the shared shuffle would do — is the card doing
    nothing at all, so the destination branch shuffles itself and returns.
    """
    game, _choice = _r9_tutor(set_pool, "Worldly Tutor", _R9_LIBRARY)
    index = next(
        i for i, card in enumerate(game.players[0].library)
        if card.name == "Femeref Knight"
    )

    assert game.confirm_search_library(0, index)

    assert game.players[0].library[0].name == "Femeref Knight"
    assert len(game.players[0].library) == len(_R9_LIBRARY)


# --- W1G1: the combat family ---
#
# Yare is the instant half of the combat group: CR 509.1b's block-count ceiling
# raised rather than tightened, which is the one direction the combat
# productions did not read.

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g1i_creature(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g1i_nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g1i_combat(set_pool, attackers: int = 3):
    """Seat 0 attacking with *attackers* creatures into seat 1's lone Defender,
    with Yare in seat 1's hand and the attack already declared."""
    raiders = [
        _w1g1i_nosick(Permanent(card=_w1g1i_creature(f"Raider{i}", 1, 1)))
        for i in range(attackers)
    ]
    defender = _w1g1i_nosick(Permanent(card=_w1g1i_creature("Defender", 2, 6)))
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(raiders)),
        PlayerState(name="P2", battlefield=[defender], hand=[set_pool("MIR")["Yare"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, list(range(attackers)))[0]
    return game, defender


def test_yare_compiles_both_of_its_sentences(set_pool):
    """The second sentence's "that creature" is the bound object the first one
    targeted, not a second choice -- so it emits no target description of its
    own and the handler acts on the spell's one target, the idiom
    ``lowering/keywords.py`` established for the identical pronoun."""
    program = compile_card_oracle(set_pool("MIR")["Yare"])
    assert program.supported, program.reason
    (sequence, _pattern) = program.instructions
    steps = sequence.payload["steps"]
    assert [step.kind for step in steps] == [
        "pump_target_creature_until_eot", "grant_additional_blocks_until_eot",
    ]
    assert steps[1].payload == {"count": 2}


def test_yare_lets_one_creature_block_three(set_pool):
    """CR 509.1b's ceiling raised by two. The permission **adds** to the
    printed default rather than replacing it -- a creature blocks one attacker
    to begin with, so "up to two additional" is three."""
    game, defender = _w1g1i_combat(set_pool)
    assert game._max_blocks_for(defender) == 1

    result = game.cast_from_hand(
        1, "Yare", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert (defender.effective_power, defender.effective_toughness) == (5, 6)
    assert game._max_blocks_for(defender) == 3

    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: [0, 1, 2]})[0]


def test_yare_ends_with_the_turn(set_pool):
    """"…this turn" is the sweep, and the sweep is what says so: a granted
    combat permission nothing clears is a permanent one. Blaze of Glory's two
    flags had exactly that hole -- written by a handler, read by the blockers
    step and by the AI, swept by nothing -- and were found by putting this
    count beside them."""
    game, defender = _w1g1i_combat(set_pool)
    assert game.cast_from_hand(
        1, "Yare", target_player_index=1, target_permanent_index=0
    ).supported
    game.resolve_stack()
    game._settle()
    assert game._max_blocks_for(defender) == 3

    game.resolve_cleanup_step(0)

    assert game._max_blocks_for(defender) == 1


def test_yare_is_uncastable_with_no_combat(set_pool):
    """"Target creature **defending player controls**" outside combat names a
    seat that does not exist (CR 506.2), so the spell has no legal target.

    That is the answer rather than a fallback, and it is the half of the
    defending-player narrowing a *spell* needed: a trigger's announcement
    freezes the seat because its combat may be over by resolution, and a spell
    has no such record because it is being cast right now.
    """
    defender = _w1g1i_nosick(Permanent(card=_w1g1i_creature("Defender", 2, 6)))
    game = Game(players=[
        PlayerState(name="P1"),
        PlayerState(name="P2", battlefield=[defender],
                    hand=[set_pool("MIR")["Yare"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.cast_from_hand(
        1, "Yare", target_player_index=1, target_permanent_index=0
    )
    assert not result.supported
    assert game._max_blocks_for(defender) == 1


def test_yare_does_not_reach_the_attacking_players_creatures(set_pool):
    """The narrowing the picker had no way to answer, and which the pump
    handler dropped on the other side: "defending player controls" is a seat,
    and both ends now read the live combat's."""
    game, _defender = _w1g1i_combat(set_pool)

    result = game.cast_from_hand(
        1, "Yare", target_player_index=0, target_permanent_index=0
    )
    assert not result.supported, "an attacker is not a creature the defender controls"
