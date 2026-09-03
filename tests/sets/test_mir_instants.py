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


# --- W1G4: the zones / cards / library family ---

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent


def _w1g4_duel(pool, *, seat0_hand=(), seat1_battlefield=(), seat1_hand=(),
               seat1_library=("Island",) * 5):
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", hand=[pool[n] for n in seat0_hand],
            library=[pool["Island"]] * 5,
        ),
        _W1G4PlayerState(
            name="P2",
            battlefield=[_W1G4Permanent(card=pool[n]) for n in seat1_battlefield],
            hand=[pool[n] for n in seat1_hand],
            library=[pool[n] for n in seat1_library],
        ),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    return game


def test_afterlife_gives_the_token_to_the_destroyed_creatures_controller(set_pool):
    """"Destroy target creature. It can't be regenerated. **Its controller**
    creates a 1/1 white Spirit creature token with flying."

    The rider is the one Angelic Ascension prints behind an *exile*, and it
    refused here for want of a producer -- while the destroy handler had been
    recording exactly that seat all along, under a second name. The assertion
    that matters is whose battlefield the Spirit lands on: reading the
    ability's own controller would have handed it to the caster.
    """
    pool = set_pool("MIR")
    game = _w1g4_duel(
        pool, seat0_hand=("Afterlife",), seat1_battlefield=("Femeref Scouts",)
    )
    game.start_turn(0)

    result = game.cast_from_hand(
        0, "Afterlife", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert [c.name for c in game.players[1].graveyard] == ["Femeref Scouts"]
    assert game.players[0].battlefield == [], "the caster gets nothing"
    spirits = [p for p in game.players[1].battlefield if p.card.name == "Spirit Token"]
    assert len(spirits) == 1
    assert spirits[0].card.colors == ("W",)
    assert "Flying" in spirits[0].card.keywords


def test_afterlife_creates_nothing_when_the_destroy_chose_nothing(set_pool):
    """CR 608.2b: the rider names the object the previous step chose, so with no
    target chosen there is no controller for the sentence to name and no token.

    The gate is the producer record's absence rather than a branch in the token
    handler, which is what keeps "does as much as it can" from inventing a seat.
    """
    pool = set_pool("MIR")
    game = _w1g4_duel(pool, seat0_hand=("Afterlife",))
    game.start_turn(0)

    game.cast_from_hand(0, "Afterlife")
    game.resolve_stack()

    assert game.players[0].battlefield == []
    assert game.players[1].battlefield == []


def test_illumination_heals_the_countered_spells_controller_for_its_mana_value(set_pool):
    """"Counter target artifact or enchantment spell. **Its controller** gains
    life equal to **its mana value**."

    Both halves name the countered spell, and by the time the second sentence
    runs it is a card in a graveyard: CR 108.4 gives that no controller and
    CR 613.1 no characteristics, so both are read off records the counter wrote
    (CR 608.2h). The life goes to the *opponent* -- the payload used to say
    ``recipient: "target"``, which for a counterspell is the spell.
    """
    pool = set_pool("MIR")
    game = _w1g4_duel(pool, seat0_hand=("Illumination",), seat1_hand=("Mana Prism",))
    game.start_turn(1)
    assert game.queue_from_hand(1, "Mana Prism").supported
    assert [item.card.name for item in game.stack] == ["Mana Prism"]

    result = game.cast_from_hand(0, "Illumination", target_stack_index=0)
    assert result.supported, result.details
    game.resolve_stack()

    assert [c.name for c in game.players[1].graveyard] == ["Mana Prism"]
    assert game.players[1].life == 23, "Mana Prism costs {3}"
    assert game.players[0].life == 20, "the caster heals nobody"


def test_illumination_gains_no_life_when_it_counters_nothing(set_pool):
    """With nothing countered there is no spell for either possessive to name,
    so no life is gained -- rather than the caster's own total moving, which is
    what a recipient defaulted to "caster" would have done."""
    pool = set_pool("MIR")
    game = _w1g4_duel(pool, seat0_hand=("Illumination",))
    game.start_turn(0)

    game.cast_from_hand(0, "Illumination")
    game.resolve_stack()

    assert (game.players[0].life, game.players[1].life) == (20, 20)
