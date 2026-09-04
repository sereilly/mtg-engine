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


# --- W1G5: the statics / characteristics / control family ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _g5_vanilla(name: str, power: int = 2, toughness: int = 2,
                type_line: str = "Creature - Test") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


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


def test_dissipate_exiles_the_spell_it_counters(set_pool):
    """"Counter target spell. If that spell is countered this way, **exile it**
    instead of putting it into its owner's graveyard."

    CR 614.1 replacing CR 701.5a's destination, which Memory Lapse's production
    already carried — written with the destination as a *verb* rather than a
    zone, because "put it into exile" is not a sentence Magic uses. One branch
    of that production rather than a second one: the "instead of … graveyard"
    tail is the whole rest of the clause, and a second production would be a
    second place to forget the word that makes this a replacement at all.
    """
    pool = set_pool("MIR")
    game = _g5_game(pool, ["Dissipate"])
    game.players[1].hand.append(pool["Mangara's Blessing"])
    before = game.players[1].life

    game.queue_from_hand(1, "Mangara's Blessing")
    counter = game.cast_from_hand(0, "Dissipate", target_stack_index=0)
    assert counter.supported, counter.details
    game.resolve_stack()

    # Both halves, because the failure a dropped destination clause causes is
    # silent: the card in the graveyard is exactly what a plain Counterspell
    # leaves behind and reads as nothing having gone wrong.
    assert game.players[1].life == before, "the spell was countered"
    assert [card.name for card in game.players[1].graveyard] == []
    assert [getattr(card, "name", card) for card in game.players[1].exile] == [
        "Mangara's Blessing"
    ]


def test_prismatic_boon_protects_every_creature_it_named(set_pool):
    """"Choose a color. **X** target creatures gain protection from **the chosen
    color** until end of turn."

    "The chosen color" is the same question "the color of your choice" asks —
    CR 609.3 puts both in this resolution, so they name one colour and read one
    channel. A second keyword string would have been a second answer to it, and
    the grant handler would have had to learn which sentence had done the
    asking.
    """
    a = Permanent(card=_g5_vanilla("A"))
    b = Permanent(card=_g5_vanilla("B"))
    game = _g5_game(set_pool("MIR"), ["Prismatic Boon"], battlefield=[a, b])

    cast = game.cast_from_hand(
        0, "Prismatic Boon", x_value=2, new_color="R",
        target_permanent_ids=[a.permanent_id, b.permanent_id],
    )
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert game._protection_colors(a) == {"R"}
    assert game._protection_colors(b) == {"R"}


def test_prismatic_lace_offers_a_set_of_colours(set_pool):
    """"Target permanent becomes the color **or colors** of your choice."

    The one subject of the three that had no path to the set offer: the Aura's
    host and the source itself both reached ``arm_color_set_choice`` and a
    *target* refused outright. Asked as a prompt rather than read off the
    activation's single symbol, because one symbol is a legal answer to the
    offer and not the offer itself — taking it would quietly make "or colors"
    mean "a color" on every printing.
    """
    host = Permanent(card=_g5_vanilla("Statue", 1, 1, "Artifact Creature - Golem"))
    game = _g5_game(set_pool("MIR"), ["Prismatic Lace"], battlefield=[host])

    cast = game.cast_from_hand(0, "Prismatic Lace",
                               target_player_index=0, target_permanent_index=0)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    # A non-interactive seat takes the prompt's stated default at once, which
    # is a colour — the point being that a colour was *asked for* rather than
    # read off a cast that never named one.
    assert game._effective_colors(host), "a colour was chosen and written"


def test_a_counter_on_it_lands_on_what_the_sentence_before_chose():
    """"Gain control of target creature. **Put a -1/-0 counter on it.**"

    A bare "it" is the ability's own source everywhere else, which is what
    ``parse_recipient`` reads — so this sentence lowered to
    ``add_counter_to_self`` and the counter went on the wrong permanent, or,
    for a spell, on nothing at all. Neither raises, which is why the rider
    exists.
    """
    from engine.grammar import compile_line

    result = compile_line(
        "Gain control of target creature. Put a -1/-0 counter on it."
    )
    kinds = [instruction.kind for instruction in result.instructions]
    assert kinds == ["gain_control_of_target", "add_counter_to_target"]


def test_the_pronoun_rider_leaves_a_named_subject_alone():
    """"Put a +1/+1 counter on **this creature**" is not the pronoun, and keeps
    its own referent — the rider fires on ``quantifier == "it"`` alone."""
    from engine.grammar import compile_line

    result = compile_line("Tap target creature. Put a +1/+1 counter on this creature.")
    kinds = [instruction.kind for instruction in result.instructions]
    assert kinds == ["tap_target_permanent", "add_counter_to_self"]


def test_ersatz_gnomes_can_be_aimed(set_pool):
    """"{T}: Target permanent becomes colorless until end of turn."

    A supported card no player could use. The recolour lowering described its
    targets only for the "one or more target creatures" spelling — the *single*
    target got no description at all, so ``derive_activation_spec`` had no
    evidence and the picker offered nothing. The handler reads neither
    description: it resolves through ``resolve_target_permanents``, which asks
    the resolution what was chosen, so the missing half was invisible to every
    test that gave the ability a target by hand.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    pool = set_pool("MIR")
    program = compile_card_oracle(pool["Ersatz Gnomes"])
    recolour = next(
        ability for ability in program.activated_abilities
        if ability.instruction is not None
        and ability.instruction.kind == "recolor_targets_until_eot"
    )
    assert derive_activation_spec(recolour) == {"kind": "permanent"}


def test_soul_rend_actually_destroys_a_white_creature(set_pool):
    """"Destroy target creature if it's white. A creature destroyed this way
    can't be regenerated."

    The card was *supported* and did nothing but draw its cantrip: the effect
    line refused as a whole — CR 701.15c's rider is read by the destroy
    production only when it trails the verb directly, and the sentence layer had
    already wrapped this destroy in the "if it's white" conditional — and a
    ``spell_pattern`` whitelist marker claimed the card anyway.
    """
    pool = set_pool("MIR")
    white = Permanent(card=CardDefinition(
        name="Cleric", mana_cost="", cmc=0.0, type_line="Creature - Human Cleric",
        oracle_text="", colors=("W",), color_identity=("W",), keywords=(),
        produced_mana=(),
        raw={"name": "Cleric", "type_line": "Creature - Human Cleric",
             "power": "2", "toughness": "2", "colors": ["W"]},
    ))
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Soul Rend"]],
                    library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=[white],
                    library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    cast = game.cast_from_hand(0, "Soul Rend", target_player_index=1,
                               target_permanent_index=0)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(white)


def test_soul_rend_spares_a_creature_of_another_colour(set_pool):
    """The condition half. Read as an unconditional destroy the card would be
    strictly better than the one printed."""
    pool = set_pool("MIR")
    green = Permanent(card=CardDefinition(
        name="Wurm", mana_cost="", cmc=0.0, type_line="Creature - Wurm",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": "Wurm", "type_line": "Creature - Wurm",
             "power": "4", "toughness": "4", "colors": ["G"]},
    ))
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Soul Rend"]],
                    library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=[green],
                    library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.cast_from_hand(0, "Soul Rend", target_player_index=1,
                        target_permanent_index=0)
    game.resolve_stack()
    game._settle()

    assert game.is_on_battlefield(green)


def test_early_harvest_untaps_the_seat_the_caster_chose(set_pool):
    """"**Target player** untaps all basic lands they control."

    Both halves were missing and each hid the other. The noun phrase records
    the printed subject as ``controller: "that_player"``, which the picker was
    never told about — so the client sent a bare cast; and the handler read that
    seat only out of a *trigger's* frozen context (CR 603.10), so even a cast
    that named one untapped nothing at all and still went to the graveyard.
    """
    pool = set_pool("MIR")

    def _tapped(card):
        permanent = Permanent(card=card)
        permanent.tapped = True
        return permanent

    mine = _tapped(pool["Forest"])
    basic = _tapped(pool["Island"])
    nonbasic = _tapped(pool["Bad River"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[mine], hand=[pool["Early Harvest"]],
                    library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=[basic, nonbasic],
                    library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    cast = game.cast_from_hand(0, "Early Harvest", target_player_index=1)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not basic.tapped, "the chosen seat's basic land untaps"
    assert nonbasic.tapped, "'basic' is a supertype the sweep still tests"
    assert mine.tapped, "the caster's own board is not the target's"
