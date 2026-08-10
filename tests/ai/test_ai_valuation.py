"""The AI values a card by what it does, not by what it is called.

``engine/ai_policy.py`` carried eight ``card.name == "..."`` comparisons. They
were not rules code — a heuristic naming a card is tuning, not a correctness
claim — but *which cards a tuning constant reaches* is a claim about the pool,
and it had already expired. Measured before ``engine/ai_valuation.py`` existed:

* ``card.name == "Disenchant"`` pointed a targeted destroy at the opponent.
  Shatter, Terror, Stone Rain and Desert Twister print the same template under
  other names, and the AI **targeted itself** with all four.
* ``card.name == "Ancestral Recall"`` stopped the AI decking itself. Braingeyser
  is the same sentence with X in it, and the AI emptied its own library.
* ``permanent.card.name == "Jayemdae Tome"`` stopped the AI drawing from an
  empty library. Jandor's Ring draws the same one card.

So every property below is pinned with an **invented** card printing the
template under a name the engine has never seen. A test naming only the real
card passes against the broken version — which is exactly how these survived.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_activation_action, choose_cast_action
from engine.ai_valuation import (
    MANA_ABILITY_KINDS,
    cards_drawn_by_target,
    counters_a_spell,
    destroyed_permanent_filter,
    mana_ability_amount,
    returns_creature_to_hand,
)
from engine.handlers import EFFECT_HANDLERS
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, _nosick


def _spell(name: str, type_line: str, oracle_text: str, mana_cost: str = "{U}") -> CardDefinition:
    return _mk_card(name=name, mana_cost=mana_cost, type_line=type_line, oracle_text=oracle_text)


# Invented cards, each printing a template the whitelist knew under one name.
SCRIBE_OF_ULM = _spell("Scribe of Ulm", "Instant", "Target player draws three cards.")
CALL_IT_BACK = _spell("Call It Back", "Instant", "Return target creature to its owner's hand.")
CLEANSING_RITE = _spell("Cleansing Rite", "Instant", "Destroy target artifact or enchantment.")
SALT_THE_FIELDS = _spell("Salt the Fields", "Sorcery", "Destroy target land.")
BLUE_WARD = _spell("Blue Ward", "Instant", "Counter target blue spell.")


def _board(hand=(), mine=(), theirs=(), library=(), enforce=False) -> Game:
    p1 = PlayerState(name="P1", hand=list(hand), library=list(library),
                     battlefield=[Permanent(card=c) for c in mine])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=c) for c in theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = enforce
    return game


# ---------------------------------------------------------------------------
# Derivation: what the compiled program says the card does
# ---------------------------------------------------------------------------

def test_draw_count_comes_from_the_instruction():
    assert cards_drawn_by_target(SCRIBE_OF_ULM) == 3


def test_a_variable_draw_is_unanswerable_until_x_is_chosen(all_cards):
    """"Target player draws X cards" has no answer before X is picked, and the
    caller must not read the absence of one as "draws nothing"."""
    braingeyser = next(c for c in all_cards if c.name == "Braingeyser")
    assert cards_drawn_by_target(braingeyser) is None
    assert cards_drawn_by_target(braingeyser, x_value=4) == 4


def test_a_permanents_activated_ability_is_not_a_spell_effect(all_cards):
    """``OracleProgram.instructions`` mirrors a permanent's activated ability, so
    Royal Assassin's "{T}: Destroy target creature" is in there. Reading it
    unguarded would value the *creature card in hand* as a removal spell."""
    assassin = next(c for c in all_cards if c.name == "Royal Assassin")
    assert any(i.kind == "destroy_target_permanent" for i in compile_card_oracle(assassin).instructions)
    assert destroyed_permanent_filter(assassin) is None


@pytest.mark.parametrize(
    "ability",
    [
        "{2}, {T}: Target creature gains flying until end of turn.",
        "{1}, {T}: Destroy target artifact.",
        "{2}, {T}: Target creature gets +1/+1 until end of turn.",
    ],
)
def test_a_permanent_is_castable_with_nothing_for_its_ability_to_target(ability):
    """The sibling of the test above, on the AI's *castability* check.

    ``_can_cast_with_targets`` scans that same mirrored list, so an artifact
    whose ability targets a creature was judged uncastable while its controller
    had no creature, and one whose ability destroys an artifact uncastable while
    the opponent had none. Both are perfectly castable — the ability picks its
    target when it is *activated*. ``SPELL_TYPES`` is the gate, the same one
    ``_spell_instructions`` uses one module over.

    Invented names, per this module's rule: the real cards (Flying Carpet,
    Pyramids) would pass against a fix that special-cased them.
    """
    from engine.ai_policy import _can_cast_with_targets

    card = _mk_card(name="Gadget", mana_cost="{3}", type_line="Artifact", oracle_text=ability)
    # The premise: the branch kind really is in the mirrored card-level list, so
    # a missing gate would be read. Without this the test could pass vacuously.
    assert any(i.kind != "spell_pattern" for i in compile_card_oracle(card).instructions)

    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    assert _can_cast_with_targets(game, 0, card), (
        "a permanent's ability targets on activation, not on cast"
    )


def test_counter_profile_carries_the_colour_restriction():
    """A colourless reading would have the AI hold Red Elemental Blast up
    against a green spell — the generalisation that looks free and plays worse
    than the whitelist it replaces."""
    blue = _mk_card(name="Blue Thing", mana_cost="{U}", type_line="Instant", oracle_text="", colors=("U",))
    red = _mk_card(name="Red Thing", mana_cost="{R}", type_line="Instant", oracle_text="", colors=("R",))

    profile = counters_a_spell(BLUE_WARD)
    assert profile is not None and profile.color == "U"
    assert profile.can_counter(blue)
    assert not profile.can_counter(red)

    unrestricted = counters_a_spell(_spell("Say No", "Instant", "Counter target spell.", "{U}{U}"))
    assert unrestricted is not None and unrestricted.color is None
    assert unrestricted.can_counter(red)


def test_every_named_instruction_kind_is_a_registered_handler():
    """The set this module replaced was ``{"add_mana", "black_lotus_add_mana"}``
    and **neither kind existed any more** — both had been renamed out from under
    it, so the check that stopped the AI idly tapping its mana rocks had
    silently stopped firing. A kind named here must be one something dispatches."""
    missing = sorted(MANA_ABILITY_KINDS - set(EFFECT_HANDLERS))
    assert not missing, f"ai_valuation names instruction kinds no handler implements: {missing}"


# ---------------------------------------------------------------------------
# Targeting: an unnamed card gets the named card's judgement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "spell, mine, theirs",
    [
        (CLEANSING_RITE, "Howling Mine", "Howling Mine"),
        (SALT_THE_FIELDS, "Mountain", "Mountain"),
        (CALL_IT_BACK, "Grizzly Bears", "Grizzly Bears"),
    ],
)
def test_interaction_is_aimed_at_the_opponent(all_cards, spell, mine, theirs):
    """Before the derivation, only the two named cards did this; every other
    printing of the same template resolved onto the AI's own permanent."""
    pool = {c.name: c for c in all_cards}
    game = _board(hand=[spell], mine=[pool[mine]], theirs=[pool[theirs]])

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == spell.name
    assert action.target_player_index == 1, f"{spell.name} was aimed at its own controller"


def test_a_destroy_is_valued_by_what_the_opponent_actually_has(all_cards):
    """The count uses the engine's own filter matcher, so the AI cannot have a
    second opinion about what "target artifact or enchantment" means."""
    pool = {c.name: c for c in all_cards}
    assert destroyed_permanent_filter(CLEANSING_RITE)["type_filter"] == "artifact_or_enchantment"

    barren = _board(hand=[CLEANSING_RITE], theirs=[pool["Grizzly Bears"]])
    stocked = _board(hand=[CLEANSING_RITE], theirs=[pool["Howling Mine"], pool["Black Vise"]])

    from engine.ai_policy import _score_spell_target

    assert _score_spell_target(CLEANSING_RITE, 0, 1, barren) < _score_spell_target(
        CLEANSING_RITE, 0, 1, stocked
    )


def test_bounce_is_recognized_without_a_name():
    assert returns_creature_to_hand(CALL_IT_BACK)
    assert not returns_creature_to_hand(CLEANSING_RITE)


# ---------------------------------------------------------------------------
# CR 704.5b: a draw the library cannot cover
# ---------------------------------------------------------------------------

def test_an_unnamed_draw_spell_is_not_aimed_at_a_library_it_would_empty(all_cards):
    """The named card was Ancestral Recall. This is its sentence under another
    name: three cards, three left in the library, and drawing them all loses the
    game on the next draw step."""
    island = next(c for c in all_cards if c.name == "Island")
    game = _board(hand=[SCRIBE_OF_ULM], library=[island, island])

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == SCRIBE_OF_ULM.name
    assert action.target_player_index == 1, "the AI aimed a deck-out at itself"


def test_a_variable_draw_respects_the_library_it_would_empty(all_cards):
    """Braingeyser is in the pool and was never named. With two cards left the
    AI used to cast it at itself for X=2 and empty its own library."""
    pool = {c.name: c for c in all_cards}
    island = pool["Island"]
    game = _board(hand=[pool["Braingeyser"]], library=[island, island],
                  mine=[island] * 4, enforce=True)

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Braingeyser"
    assert action.target_player_index == 1


def test_an_unnamed_draw_ability_is_not_activated_into_an_empty_library(catalog_by_name):
    """The named permanent was Jayemdae Tome. Jandor's Ring draws the same card
    and was never named, so the AI would draw itself to death with it."""
    pool = catalog_by_name
    for permanent_name in ("Jayemdae Tome", "Jandor's Ring"):
        game = _board(mine=[pool[permanent_name]])
        game.turn = 5
        _nosick(game.players[0].battlefield[0])

        action = choose_activation_action(game, 0)

        assert action is None or action.permanent_name != permanent_name, (
            f"{permanent_name} was activated with an empty library (CR 704.5b)"
        )


# ---------------------------------------------------------------------------
# Mana sources
# ---------------------------------------------------------------------------

def test_mana_ability_amount_reads_both_payload_shapes(all_cards):
    pool = {c.name: c for c in all_cards}
    assert mana_ability_amount(pool["Black Lotus"]) == 3   # bare count
    assert mana_ability_amount(pool["Sol Ring"]) == 2      # pip list
    assert mana_ability_amount(pool["Mox Sapphire"]) == 1
    assert mana_ability_amount(pool["Lightning Bolt"]) is None


def test_a_mana_source_is_unattractive_when_mana_is_free(all_cards):
    """The named card was Black Lotus. With ``enforce_mana_costs`` off, a Mox is
    worth exactly as little and used to be worth +0.8 for being an artifact."""
    pool = {c.name: c for c in all_cards}
    game = _board(hand=[pool["Mox Sapphire"], pool["Lightning Bolt"]])

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Lightning Bolt"


def test_a_mana_ability_is_never_activated_for_its_own_sake(all_cards):
    """Mana added outside a cost payment empties at the end of the step, and
    Black Lotus sacrifices itself to add it. The skip that was meant to prevent
    this named two instruction kinds that no longer exist, so the AI had been
    throwing the Lotus away for nothing."""
    pool = {c.name: c for c in all_cards}
    for permanent_name in ("Black Lotus", "Mox Sapphire", "Sol Ring"):
        game = _board(mine=[pool[permanent_name]])
        game.turn = 5
        _nosick(game.players[0].battlefield[0])

        action = choose_activation_action(game, 0)

        assert action is None, f"{permanent_name} was tapped for mana with nothing to spend it on"
