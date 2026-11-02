"""A triggered wrapper's label names the moment or the shape — never one card's
effect — and nothing reads a label as a fact.

``engine/effect_labels.py``'s ``TRIGGERED_LABELS_BY_CONDITION`` lets the
*condition* name the moment for a wrapper kind (``may``, ``if_then``,
``unless_player_pays``, ``for_each``), because the wrapper says nothing about
what it offers. Measured at kg3, eleven rows named the effect of the card that
prompted them instead — Thelon's Chant's damage for ten "whenever a <noun>
enters, … may" triggers (Aura Shards destroys, Mana Echoes adds mana),
Insubordination's destruction for a card that deals damage, Verduran
Enchantress's draw, Bazaar of Wonders' counterspell for the cast moment that
also offers life and cards — or the ``spell_pattern`` fallback marker, which is
a leaf's bucket too. The condition-blind ``if_then`` row read
``triggered_label``, a word naming neither. Two fire sites stamped Ankh of
Mishra's ``triggered_damage`` over every trigger they put on the stack
(Tectonic Instability taps), and the enqueue read ``effect_kind ==
"triggered_delayed"`` as the fact that an ability is delayed.

``tests/engine/test_effect_labels.py`` holds a *condition-blind* wrapper row to
its shape and exempts the by-condition rows, because naming the moment is their
design; nothing held what the moment's word is. Two guards here do:

* **one condition, one word**: every wrapper row sharing a condition shares its
  label (the spell-cast moment read three words);
* **a shared word is declared**: a by-condition wrapper label that a leaf
  effect also produces names the moment only where the moment is of that kind
  (``SHARED_MOMENT_WORDS``, both ways) — which is what tells Thelon's Chant's
  ``triggered_damage`` (an effect's word on an entry moment) from
  ``("draws_card", "may")``'s ``triggered_draw`` (a draw moment).
"""
from __future__ import annotations

from collections import defaultdict

import pytest

from engine import Game, PlayerState
from engine import effect_labels
from engine.card_loader import load_catalog
from engine.delayed_triggers import DelayedTrigger, arm_delayed_trigger, fire_delayed_triggers
from engine.effect_labels import TRIGGERED_LABELS, TRIGGERED_LABELS_BY_CONDITION
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from tests.engine.test_effect_labels import triggered_shapes
from tests.helpers import _mk_card, _nosick

CATALOG = {card.name: card for card in load_catalog()}

#: A by-condition wrapper label that a leaf effect also produces, and the
#: conditions whose moment it names — each because the moment *is* of that
#: kind. Held to the pool both ways: a row using a shared word under a
#: condition not listed here names an effect, and an entry no row reaches goes.
SHARED_MOMENT_WORDS: dict[str, frozenset[str]] = {
    # Attacks, blocks, combat steps and combat damage: the combat moment
    # (separate_into_piles and the block-pair keyword removals are leaves
    # filed under it too).
    "triggered_combat": frozenset({
        "attackers_declared", "attacks_unblocked", "combat",
        "combat_opponent_turn", "combat_your_turn", "creature_attacks",
        "creature_attacks_or_blocks", "creature_becomes_blocked",
        "creature_blocks_or_blocked_by", "creature_dealt_damage",
        "damage_dealt", "matching_creature_becomes_blocked",
    }),
    # The upkeep moment, whose word the pay-or-consequence leaves share.
    "upkeep_effect": frozenset({
        "upkeep_each", "upkeep_enchanted_controller", "upkeep_self",
    }),
    # A card drawn, and the draw step.
    "triggered_draw": frozenset({"draws_card", "draw_step_self"}),
    # A card discarded (Confessor).
    "triggered_discard": frozenset({"discards_card"}),
    # A permanent destroyed (Karmic Justice).
    "triggered_destruction": frozenset({"permanent_destroyed"}),
    # A land tapped for mana (Sanctimony).
    "triggered_mana": frozenset({"land_tapped_for_mana"}),
    # A permanent becoming untapped / tapped (Ghostly Pilferer, Thoughtleech).
    "triggered_untap": frozenset({"permanent_becomes_untapped"}),
    "triggered_tap": frozenset({"permanent_becomes_tapped"}),
}


@pytest.fixture(scope="module")
def shapes():
    """``(name, condition, kind, wrapper, by_condition)`` for every trigger the
    grammar reads in the shipped pool. The label is asked of the table at
    assert time (``effect_labels.triggered_label``, the front end's own call),
    so a backwards check that edits the table sees its edit without a second
    sweep."""
    return [
        (name, condition, kind, wrapper, by_condition)
        for name, condition, kind, _label, wrapper, by_condition
        in triggered_shapes(load_catalog())
    ]


def _labelled(shapes):
    return [
        (name, condition, kind, effect_labels.triggered_label(kind, condition), wrapper)
        for name, condition, kind, wrapper, _by in shapes
    ]


def one_word_per_condition(shapes) -> dict:
    """Conditions whose wrapper rows read more than one label."""
    words: dict[str, set] = defaultdict(set)
    for _name, condition, kind, label, wrapper in _labelled(shapes):
        if wrapper and (condition, kind) in TRIGGERED_LABELS_BY_CONDITION:
            words[condition].add(label)
    return {condition: sorted(found) for condition, found in words.items() if len(found) > 1}


def undeclared_shared_words(shapes) -> "tuple[list, list]":
    """``(rows naming an effect's word, declarations nothing reaches)``."""
    labelled = _labelled(shapes)
    leaf_words = {label for _n, _c, _k, label, wrapper in labelled if not wrapper}
    used: set = set()
    named_effect = set()
    for _name, condition, kind, label, wrapper in labelled:
        if not wrapper or (condition, kind) not in TRIGGERED_LABELS_BY_CONDITION:
            continue
        if label not in leaf_words:
            continue
        if condition in SHARED_MOMENT_WORDS.get(label, ()):
            used.add((label, condition))
        else:
            named_effect.add((condition, kind, label))
    declared = {(label, c) for label, conditions in SHARED_MOMENT_WORDS.items() for c in conditions}
    return sorted(named_effect), sorted(declared - used)


# --- the guards ------------------------------------------------------------


def test_every_wrapper_row_of_one_condition_reads_one_word(shapes):
    by_condition = [s for s in shapes if s[3] and s[4]]
    # A floor: the by-condition wrapper rows are a few hundred triggers over
    # dozens of conditions.
    assert len(by_condition) >= 300, len(by_condition)
    assert len({s[1] for s in by_condition}) >= 40
    assert one_word_per_condition(shapes) == {}


def test_a_wrapper_row_naming_an_effects_word_is_a_declared_moment(shapes):
    named_effect, unreached = undeclared_shared_words(shapes)
    assert named_effect == [], (
        "by-condition wrapper rows whose label is a leaf effect's bucket under a "
        "condition whose moment is not of that kind — name the moment: "
        f"{named_effect}"
    )
    assert unreached == [], f"SHARED_MOMENT_WORDS entries no row reaches: {unreached}"


def test_no_wrapper_trigger_reports_the_fallback_marker(shapes):
    """``spell_pattern`` is what a clause nobody claimed reports — and the
    bucket of every ``deal_damage`` leaf. A wrapper has a shape or a moment."""
    wrapped = [s for s in _labelled(shapes) if s[4]]
    assert len(wrapped) >= 500, len(wrapped)
    assert sorted({(c, k) for _n, c, k, label, _w in wrapped if label == "spell_pattern"}) == []


# --- the rows, on their cards ----------------------------------------------


@pytest.mark.parametrize("name, kind, label", [
    # The entry's three.
    ("Thelon's Chant", "may", "triggered_etb"),
    ("Tourach's Chant", "may", "triggered_etb"),
    ("Aura Shards", "may", "triggered_etb"),
    ("Insubordination", "if_then", "triggered_conditional"),
    ("Aggression", "if_then", "triggered_conditional"),
    ("Erg Raiders", "if_then", "triggered_conditional"),
    # The cast moment, whatever the wrapper offers.
    ("Verduran Enchantress", "may", "triggered_cast"),
    ("Bazaar of Wonders", "if_then", "triggered_cast"),
    ("Ice Cave", "unless_player_pays", "triggered_cast"),
    ("Mana Vortex", "may", "triggered_cast"),
    ("Crystal Rod", "may", "triggered_cast"),
    ("Rhystic Study", "may", "triggered_cast"),
    # The fallback marker's rows.
    ("Fecundity", "may", "triggered_death"),
    ("Seasoned Marshal", "may", "triggered_combat"),
    ("Thoughtleech", "may", "triggered_tap"),
    ("Oath of Lim-Dûl", "for_each", "triggered_repeated"),
    # …and the upkeep's own word, untouched.
    ("Lim-Dûl's Hex", "for_each", "upkeep_effect"),
])
def test_each_moved_row_reads_its_moment_on_its_card(name, kind, label):
    found = {
        trig.effect_kind
        for trig in compile_card_oracle(CATALOG[name]).triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == kind
    }
    assert found == {label}, (name, found)


def test_the_old_words_are_gone_from_the_tables():
    assert "triggered_label" not in TRIGGERED_LABELS.values()
    assert TRIGGERED_LABELS["if_then"] == "triggered_conditional"
    assert ("end_step_enchanted_controller", "if_then") not in TRIGGERED_LABELS_BY_CONDITION
    assert ("you_lose_life", "for_each") not in TRIGGERED_LABELS_BY_CONDITION


# --- driven: what the stack object carries ---------------------------------


def _two_seats(mine=(), theirs=(), hand=()):
    p1 = PlayerState(name="P1", battlefield=[_nosick(Permanent(card=CATALOG[n])) for n in mine],
                     hand=[CATALOG[n] for n in hand], library=[CATALOG["Island"]] * 5)
    p2 = PlayerState(name="P2", battlefield=[_nosick(Permanent(card=CATALOG[n])) for n in theirs],
                     library=[CATALOG["Island"]] * 5)
    game = Game(players=[p1, p2])
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _triggers(game):
    return [item for item in game.stack if item.is_ability]


def test_a_land_entering_carries_each_watchers_own_label():
    """Tectonic Instability ("tap all lands its controller controls") and Ankh
    of Mishra ("deals 2 damage to that land's controller") both watch a land
    enter. The fire site reported Ankh's ``triggered_damage`` for both; each
    stack object now carries its own compiled label — and both still do what
    they print."""
    game = _two_seats(mine=("Tectonic Instability", "Ankh of Mishra"), hand=("Forest",))
    game.enforce_mana_costs = False
    assert game.queue_from_hand(0, "Forest").supported
    compiled = {
        name: next(
            trig.effect_kind for trig in compile_card_oracle(CATALOG[name]).triggered_abilities
            if trig.condition.kind == "land_enters"
        )
        for name in ("Tectonic Instability", "Ankh of Mishra")
    }
    assert compiled["Tectonic Instability"] == "triggered_tap"
    carried = {item.card.name: item.ability_effect_kind for item in _triggers(game)}
    assert carried == compiled, carried
    forest = next(p for p in game.controlled_by(0) if p.card.name == "Forest")
    from tests.helpers import resolve_stack
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert forest.tapped, game.log
    assert game.players[0].life == 18, game.log


def test_a_cast_trigger_on_the_stack_reports_the_cast_moment():
    """Verduran Enchantress: "Whenever you cast an enchantment spell, you may
    draw a card." The trigger above the enchantment is the cast moment's, as
    Bazaar of Wonders' and Crystal Rod's are; it read ``triggered_draw``."""
    game = _two_seats(mine=("Verduran Enchantress",), hand=("Crusade",))
    game.enforce_mana_costs = False
    assert game.queue_from_hand(0, "Crusade").supported
    (trigger,) = _triggers(game)
    assert trigger.card.name == "Verduran Enchantress"
    assert trigger.ability_effect_kind == "triggered_cast"


# --- the delayed flag ------------------------------------------------------

_SHRINE = _mk_card(name="Kg3 Shrine", type_line="Enchantment — Shrine")
_SANCTUM = _mk_card(
    name="Kg3 Sanctum", type_line="Enchantment",
    oracle_text=(
        "If a triggered ability of another Shrine you control triggers while you "
        "control one or more Shrines, that ability triggers an additional time."
    ),
)


def _shrine_table():
    shrine, sanctum = Permanent(card=_SHRINE), Permanent(card=_SANCTUM)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[shrine, sanctum], life=20),
        PlayerState(name="P2", life=20),
    ])
    game.interactive_seats = set()
    game.active_player_index = 0
    return game, shrine


_GAIN = OracleInstruction("target_gains_life", "", {"amount": 1, "recipient": "caster"})


@pytest.mark.cr("603.2d", "603.7e")
def test_a_delayed_ability_is_not_doubled_whatever_it_is_labelled(monkeypatch):
    """CR 603.2d: an effect that makes an object's triggered abilities trigger
    an additional time "refers only to triggered abilities that object has,
    not to any delayed or reflexive triggered abilities". The Shrine's own
    trigger is doubled (the control); a delayed ability whose source is the
    Shrine (CR 603.7e) is not — and stays undoubled when its label is changed,
    because the enqueue is told it is delayed rather than reading the label."""
    game, shrine = _shrine_table()
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=shrine, card=_SHRINE,
        instruction=_GAIN, effect_kind="triggered_life",
    )
    assert len(game.stack) == 2, "the doubler doubles the Shrine's own ability"

    for label in ("triggered_delayed", "relabelled_by_a_report_round"):
        game, shrine = _shrine_table()
        real = DelayedTrigger.trigger_event

        def relabelled(self, *args, _label=label, _real=real, **kwargs):
            event = _real(self, *args, **kwargs)
            event["effect_kind"] = _label
            return event

        monkeypatch.setattr(DelayedTrigger, "trigger_event", relabelled)
        arm_delayed_trigger(game, DelayedTrigger(
            controller_index=0, event="controllers_next_main_phase",
            instruction=_GAIN, card=_SHRINE, source_permanent_id=shrine.permanent_id,
        ))
        assert fire_delayed_triggers(game, "controllers_next_main_phase", seat=0) == 1
        assert len(game.stack) == 1, (label, [item.ability_effect_kind for item in game.stack])
        assert game.stack[0].ability_effect_kind == label
        monkeypatch.undo()


# --- backwards: the guards fire on the rows they replaced ------------------


@pytest.mark.parametrize("row, old", [
    (("matching_permanent_enters", "may"), "triggered_damage"),
    (("enchantment_cast", "may"), "triggered_draw"),
    (("self_cast", "may"), "triggered_counterspells"),
])
def test_the_shared_word_guard_names_an_effects_word(shapes, monkeypatch, row, old):
    assert undeclared_shared_words(shapes) == ([], [])
    monkeypatch.setitem(TRIGGERED_LABELS_BY_CONDITION, row, old)
    named_effect, _unreached = undeclared_shared_words(shapes)
    assert (row[0], row[1], old) in named_effect, named_effect


def test_the_one_word_guard_names_the_split_cast_moment(shapes, monkeypatch):
    monkeypatch.setitem(
        TRIGGERED_LABELS_BY_CONDITION, ("spell_cast", "if_then"), "triggered_counterspells",
    )
    assert one_word_per_condition(shapes) == {
        "spell_cast": ["triggered_cast", "triggered_counterspells"],
    }


def test_the_fallback_marker_guard_names_a_spell_pattern_row(shapes, monkeypatch):
    monkeypatch.setitem(TRIGGERED_LABELS_BY_CONDITION, ("creature_dies", "may"), "spell_pattern")
    wrapped = [s for s in _labelled(shapes) if s[4]]
    assert ("creature_dies", "may") in {
        (c, k) for _n, c, k, label, _w in wrapped if label == "spell_pattern"
    }
