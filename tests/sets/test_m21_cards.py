"""Core Set 2021 (M21) tests that are not about one card.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; what is left here is cross-cutting — the per-round
compile sweeps that span several types, the grammar probes that name no card,
and the per-turn records a card's behaviour is read from. The per-card tests
live in test_m21_<type>.py beside this file.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.grammar import compile_line
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle


# --- The token-naming round: CR 111.4 names unnamed tokens ------------------


@pytest.mark.parametrize(
    "name",
    [
        "Valorous Steed",         # ETB: 2/2 white Knight token with vigilance
        "Deathbloom Thallid",     # dies: 1/1 green Saproling token
        "Falconer Adept",         # attacks: 1/1 white Bird token — still gated
        "Goblin Wizardry",        # two 1/1 red Wizard tokens with prowess
        "Sporeweb Weaver",        # dealt damage: gain 1 life + Saproling token
        "Speaker of the Heavens", # {T}: 4/4 white Angel token, conditional
    ],
)
def test_token_round_cards_compile_supported(set_pool, name):
    if name == "Falconer Adept":
        pytest.skip("still gated on the tapped-and-attacking rider")
    assert compile_card_oracle(set_pool("M21")[name]).supported


# --- The each-opponent round: damage and life loss sweep the table ----------


@pytest.mark.parametrize(
    "name",
    [
        "Storm Caller",           # ETB: deals 2 damage to each opponent
        "Spirit of Malevolence",  # dies: each opponent loses 1 life
        "Grim Tutor",             # tutor + "You lose 3 life"
        "Caged Zombie",           # activated: each opponent loses 2 life
    ],
)
def test_each_opponent_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_targeted_several_taps_are_still_refused_rather_than_halved():
    """The *targeted* family stays refused: "tap up to two target creatures"
    names cast-time targets no tap handler resolves as a list. Rewind's
    untargeted spelling is the one that got a lowering, and the ``targeted``
    flag on the spec is what keeps the two apart."""
    result = compile_line("Tap up to two target creatures.", card_name="Test")

    assert result.parsed
    assert not result.lowered
    assert result.failure_reason == "no handler taps or untaps several targets"


# --- The multi-target round: "each of up to N target ..." -------------------


@pytest.mark.parametrize(
    "line",
    [
        "Put a +1/+1 counter on each of up to two target creatures.",
        "Put a +1/+1 counter on up to two target creatures.",
        "Put a +1/+1 counter on each of up to two other target creatures you control.",
    ],
)
def test_counters_on_several_targets_carry_their_maximum(line):
    """All three spellings are one instruction with the count on the payload.

    "each of" is a distributive wrapper over the noun phrase, not a quantifier,
    and "other" prints *before* the word "target" in the middle spelling — the
    one position the object-filter parser cannot reach. The count is what a
    picker reads to collect more than one; it used to be dropped, which is why
    the lowering refused rather than countering one creature and calling the
    card done."""
    result = compile_line(line, card_name="Test")

    assert result.lowered, result.failure_reason
    instruction = result.instructions[0]
    assert instruction.kind == "add_counter_to_target"
    assert instruction.payload["targets"]["count"] == 2


def test_up_to_one_target_is_still_a_single_target():
    """"Up to one target creature" chooses one target or none — exactly what a
    handler reading one id does. Narrowing "several" must not take it away."""
    result = compile_line(
        "Put a +1/+1 counter on up to one target creature.", card_name="Test"
    )

    assert result.lowered, result.failure_reason
    described = result.instructions[0].payload["targets"]
    assert described["quantifier"] == "up_to"
    assert described["filter"]["type_filter"] == "creature"


def test_life_gained_this_turn_counts_and_resets(set_pool):
    """"This turn" is *the turn*, not the player's turn: lifelink on an
    opponent's turn is life you gained this turn. A counter that never resets
    is a bug that first appears on turn two, firing off last turn's gains."""
    p1 = PlayerState(name="P1")
    game = Game(players=[p1, PlayerState(name="P2")])

    game._gain_life(p1, 2)
    game._gain_life(p1, 1)
    assert p1.life_gained_this_turn == 3

    game.begin_turn_bookkeeping(1)
    assert p1.life_gained_this_turn == 0, "every seat resets, not just the active one"


def test_creature_deaths_are_counted_under_the_seat_that_controlled_them(set_pool):
    """The game-wide counter cannot answer "under your control" — it is one
    number for the whole table."""
    pool = set_pool("M21")
    mine = Permanent(card=pool["Concordia Pegasus"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    game._permanent_to_graveyard(p1, mine)
    game._permanent_to_graveyard(p2, theirs)

    assert p1.creatures_died_under_your_control_this_turn == 1
    assert p2.creatures_died_under_your_control_this_turn == 1
    assert game.creatures_died_this_turn == 2

    game.begin_turn_bookkeeping(1)
    assert p1.creatures_died_under_your_control_this_turn == 0


# --- The search round: the filter the flow honours, and the two-zone fetch ---


@pytest.mark.parametrize(
    "name",
    [
        "Fierce Empath",        # search for a creature with mana value 6+
        "Chandra's Firemaw",    # library and/or graveyard, for a named card
        "Garruk's Warsteed",
        "Teferi's Wavecaster",
        "Liliana's Scorn",
    ],
)
def test_search_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_a_search_refuses_a_card_its_restriction_excludes(set_pool):
    """The engine is the authority on what may be found, not the client that
    offered the cards: an index outside the restriction is simply refused."""
    pool = set_pool("M21")
    big = next(c for c in pool.values() if c.primary_type == "creature" and c.cmc >= 6)
    small = next(c for c in pool.values() if c.primary_type == "creature" and c.cmc < 6)
    p1 = PlayerState(name="P1", library=[small, big])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="creature",
        zones=("library",), restrictions={"mana_value": {"op": "ge", "value": 6}},
    )

    assert not game.confirm_search_library(0, 0)
    assert p1.hand == []
    assert game.pending_search_library is not None

    assert game.confirm_search_library(0, 1)
    assert [c.name for c in p1.hand] == [big.name]
    assert game.pending_search_library is None


def test_a_search_that_can_find_nothing_can_still_be_left(set_pool):
    """Failing to find is legal (CR 701.19b) and is the only answer available
    when nothing in the searched zones matches."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", library=[pool["Island"], pool["Island"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="any",
        zones=("library",), restrictions={"named": "Fierce Empath"},
    )

    assert game.decline_search_library(0)
    assert p1.hand == []
    assert len(p1.library) == 2
    assert game.pending_search_library is None


def test_a_search_cannot_be_answered_with_a_zone_it_was_not_armed_with(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", library=[pool["Island"]], graveyard=[pool["Alpine Watchdog"]]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="any",
        zones=("library",), restrictions={},
    )

    assert not game.confirm_search_library(0, 0, "graveyard")
    assert p1.hand == []
    assert [c.name for c in p1.graveyard] == ["Alpine Watchdog"]


def test_a_graveyard_find_does_not_shuffle_the_library(set_pool):
    """CR 701.19d and the printed "If you search your library this way,
    shuffle": a graveyard is an open zone, so randomising a library the player
    did not search would destroy information they were entitled to keep."""
    pool = set_pool("M21")
    wanted = pool["Alpine Watchdog"]
    library = [pool["Island"], pool["Forest"], pool["Mountain"]]
    p1 = PlayerState(name="P1", library=list(library), graveyard=[wanted])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="any",
        zones=("library", "graveyard"), restrictions={"named": "alpine watchdog"},
    )

    assert game.confirm_search_library(0, 0, "graveyard")
    assert [c.name for c in p1.hand] == ["Alpine Watchdog"]
    assert p1.graveyard == []
    assert [c.name for c in p1.library] == [c.name for c in library]


# --- The keyword-grant round: "gains <keyword> until end of turn" -----------


@pytest.mark.parametrize(
    "name",
    [
        "Sure Strike",     # +3/+0 and gains first strike
        "Ranger's Guile",  # your creature gains hexproof
        "Fetid Imp",       # {B}: this creature gains deathtouch
    ],
)
def test_keyword_grant_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


# --- Round 20: Rewind, See the Truth, and the modal-honesty sweep -----------


@pytest.mark.parametrize(
    "name",
    ["Rewind", "See the Truth", "Read the Tides", "Pestilent Haze", "Destructive Tampering"],
)
def test_round_20_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


# --- Round 21: bounce and burn — riders, unions, and one history ------------


@pytest.mark.parametrize(
    "name",
    [
        "Roaming Ghostlight", "Barrin, Tolarian Archmage", "Shipwreck Dowser",
        "Scorching Dragonfire", "Soul Sear", "Life Goes On",
    ],
)
def test_round_21_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


# --- Round 22: the controller discard, and tokens for the other side --------


@pytest.mark.parametrize(
    "name", ["Jeskai Elder", "Secure the Scene", "Angelic Ascension"],
)
def test_round_22_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


# --- Round 24: two spellings and two destinations ----------------------------


@pytest.mark.parametrize(
    "name", ["Falconer Adept", "Epitaph Golem", "Unsubstantiate"],
)
def test_round_24_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_a_modal_trigger_with_a_dead_mode_refuses_naming_it():
    from engine.models import CardDefinition

    card = CardDefinition(
        name="Probe", mana_cost="{1}{G}", cmc=2.0, type_line="Creature — Boar",
        oracle_text=(
            "When this creature enters, choose one —\n"
            "• Put a +1/+1 counter on this creature.\n"
            "• Glimmer uncontrollably."
        ),
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Probe", "type_line": "Creature — Boar",
             "power": "2", "toughness": "2"},
    )
    program = compile_card_oracle(card)
    assert not program.supported
    assert "Glimmer uncontrollably" in program.reason, (
        "the all-of gate names the dead mode instead of resolving the live one"
    )


# --- Round 26: recipient and filter widenings ---------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Bad Deal",           # draw 2, each opponent discards 2, each player loses 2
        "Liliana's Steward",  # sac: target opponent discards; sorcery-speed only
    ],
)
def test_round_26_discard_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


# --- The life-gain event, and a grant that reaches every permanent ----------


def test_vito_and_heroic_intervention_compile_supported(set_pool):
    pool = set_pool("M21")
    for name in ("Vito, Thorn of the Dusk Rose", "Heroic Intervention"):
        program = compile_card_oracle(pool[name])
        assert program.supported, f"{name}: {program.reason}"

# --- Grammar probes that name no card ---------------------------------------
#
# Moved here from test_m21_creatures.py when it hit the size guard. They were
# never per-card tests: each compiles a sentence and asserts a refusal, which is
# what this file is for. Obeying the guard by splitting rather than raising it is
# the rule; what the split showed is that the misfiling was the real growth.


def test_a_fight_that_is_not_the_whole_effect_still_refuses():
    """Round 39's refusal, kept now that the card that motivated it has landed.

    "Then **it** fights…" after another sentence names that sentence's target —
    the fused pair is what reads it — so a bare `Fight` nested in a sequence
    must not lower onto the source-fights instruction, which would fight
    whichever creature the single picker offered. Primal Might proved it;
    this pins the rule after Primal Might stopped being the example.
    """
    from engine.grammar import compile_line

    whole = compile_line("This creature fights another target creature.")
    assert whole.lowered, whole.failure_reason

    nested = compile_line("Draw a card. Then it fights another target creature.")
    assert not nested.lowered


def test_a_static_computed_bonus_cannot_be_negative():
    """The refresh resolves the amount against the computed value and nothing
    carries a sign for it, so "-X/-0" would apply the bonus the wrong way —
    making a creature bigger where the card shrinks it."""
    result = compile_line(
        "This creature gets -X/-0, where X is the greatest power among "
        "creature cards in your graveyard."
    )

    assert result.parsed and not result.lowered
    assert result.failure_reason == "a static computed bonus cannot be negative"


def test_a_flip_condition_with_no_flip_before_it_refuses():
    """The control, and the rule round 33 wrote down: a back-reference names its
    producer or refuses. "the flip" is one â€” with no ``Flip a coin`` earlier in
    the same effect there is no result to read, and a condition that answered
    False instead would give the card a branch that never runs."""
    result = compile_line("If you win the flip, you gain 6 life.")

    assert result.parsed and not result.lowered
    assert result.failure_reason == (
        "'the flip' with no coin flip before it in this effect"
    )


def test_a_variable_life_payment_is_not_admitted_as_a_cost():
    """The second control. ``ActivatedAbilityCost.pay_life`` is a number the
    activation path subtracts, so an X would be admitted by the parser and
    charged as nothing â€” a free ability reporting supported, which is the bug
    class the two-reader guard exists for."""
    result = compile_line("{T}, Pay X life: You gain 6 life.")

    assert not result.parsed
    assert result.failure_reason == "only a fixed, positive life payment is charged"




# --- Round 68: what the loyalty-counter picker refuses ----------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # A narrowing `subject_matches` cannot answer, refused where it is
        # compiled rather than dropped where it is dispatched â€” otherwise the
        # picker would offer every planeswalker the card did not name.
        ("Put a loyalty counter on an attacking planeswalker you control.",
         "attacking"),
        # A restriction `ObjectFilter.to_payload` does not emit at all: "in your
        # graveyard" reduces to the same payload as the plain phrase, so reading
        # only the payload would compile a graveyard clause into a battlefield
        # picker.
        ("Put a loyalty counter on a planeswalker card in your graveyard.",
         "zone"),
        # And a sweep: no handler puts loyalty counters on a set of permanents.
        ("Put a loyalty counter on each planeswalker you control.",
         "controller chooses"),
    ],
)
def test_the_loyalty_counter_picker_refuses_what_it_cannot_honour(line, expected):
    result = compile_line(line, card_name="Test")

    assert result.parsed and not result.lowered
    assert expected in result.failure_reason


def test_a_loyalty_counter_lands_on_one_chosen_permanent(set_pool):
    """The shape that is admitted, and the whole payload it carries. The count
    is data, the noun phrase is a filter, and nothing about the card's name is
    in either."""
    program = compile_card_oracle(set_pool("M21")["Liliana's Scrounger"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "end_step"
    (action,) = trigger.instruction.payload["action"]
    assert action.kind == "add_loyalty_counters_to_chosen"
    assert action.payload == {
        "count": 1,
        "filter": {
            "type_filter": "planeswalker",
            "subtype_filter": "liliana",
            "controller": "you",
        },
    }
