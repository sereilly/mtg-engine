"""How an :class:`ObjectFilter` becomes the payload a dispatcher reads.

Split out of ``_references`` at Exodus's Phase 0, when that module sat **three
lines** under the thousand-line guard with five groups about to land noun-phrase
work on it — the shared-module case SET_PLAYBOOK.md says to pre-split rather
than to brief. Stronghold's Phase 6 had already measured the seam: this function
is 307 lines, 31% of the file, and its only free names are :data:`Fixed` and
:data:`TYPE_LINE_SUPERTYPES`.

The cut is the file's own title read one word further. ``_references`` says what
a printed noun phrase **describes**; this says what that description **emits**,
and the two grow with different rules — the description with the vocabulary of
printed noun phrases, the payload with what ``subject_filters`` can actually
test. Nothing here knows the class it serves: :func:`object_filter_payload`
reads attributes off whatever it is handed, so this module imports no node and
``_references`` keeps the one-line method every caller already speaks through.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...oracle_types import X_BOUND

from ._primitives import Fixed
from ..vocabulary import TYPE_LINE_SUPERTYPES

if TYPE_CHECKING:  # the annotation only — see the module docstring.
    from ._references import ObjectFilter


def object_filter_payload(self: "ObjectFilter") -> dict[str, object]:
    """Instruction-payload dict, emitting only keys that are set.

    The first six keys reproduce ``TargetFilter.to_payload`` exactly.
    """
    payload: dict[str, object] = {}
    if self.card_types:
        if len(self.card_types) == 1:
            payload["type_filter"] = self.card_types[0]
        elif self.type_match == "all":
            # No handler matches "is all of these types at once" yet;
            # lowering refuses rather than emitting a union that would
            # quietly widen the effect.
            payload["type_filter_all"] = list(self.card_types)
        elif set(self.card_types) == {"artifact", "enchantment"}:
            # The one union spelling the handlers already understand;
            # emitting it keeps Disenchant byte-compatible with the rule it
            # replaces.
            payload["type_filter"] = "artifact_or_enchantment"
        else:
            payload["type_filter"] = list(self.card_types)
    if self.subtypes:
        if len(self.subtypes) > 1 and self.subtype_match == "all":
            payload["subtype_filter_all"] = list(self.subtypes)
        else:
            payload["subtype_filter"] = (
                self.subtypes[0] if len(self.subtypes) == 1 else list(self.subtypes)
            )
    if self.any_classes:
        # "a **black or artifact** creature" (Soldevi Adnate), "target
        # **instant or Aura** spell" (Avoid Fate). A union across two axes,
        # emitted whole because the keys above are ANDed by every matcher —
        # split into `colors` and `card_types` it would describe a black
        # creature that is *also* an artifact, a set most cards printing
        # this can never match.
        #
        # It had no payload form until `permanent_matches_filter` learned
        # to test it, and that ordering is the rule rather than an accident:
        # a key with a payload form and no matcher is a narrowing silently
        # dropped, which for a union is an effect reaching every object.
        # The counter lowering one package over still lifts it into its own
        # key, because a *spell*'s classes are answered by a different
        # matcher (`handlers/stack._spell_is_one_of_classes`).
        payload["any_classes"] = [list(entry) for entry in self.any_classes]
    if self.tapped:
        payload["tapped_only"] = True
    # "an **untapped** creature" (Enthralling Hold). ``tapped`` is tri-state
    # and only the True half had a key, so the False half was falsy all the
    # way down and "untapped creature" emitted exactly the payload of
    # "creature" — the round-108 dropped-narrowing shape, wearing a boolean
    # instead of a missing key. Its own key rather than ``tapped_only:
    # False``, because absent already means "no restriction" and a matcher
    # reading a three-valued key with ``.get()`` would answer the wrong one
    # of the two.
    elif self.tapped is False:
        payload["untapped_only"] = True
    if len(self.colors) == 1:
        payload["color_filter"] = self.colors[0]
    elif self.colors:
        # "a green **or** white creature" — an object answering *any* of
        # them, which is what the printed "or" says. Its own key rather than
        # a list-valued `color_filter`, because that key means "has this
        # colour" to every matcher already reading it and a second type
        # under one name is how two readers come to disagree.
        #
        # This branch used to be `colors[0]`, silently dropping the rest:
        # no noun phrase could produce two colours, so nothing exercised it
        # — a dropped rider waiting for the parser to grow the union above.
        payload["any_colors"] = list(self.colors)
    if self.excluded_colors:
        payload["exclude_colors"] = list(self.excluded_colors)
    if self.excluded_types:
        payload["exclude_types"] = list(self.excluded_types)
    if self.attached_to_filter is not None:
        payload["attached_to_filter"] = self.attached_to_filter.to_payload()
    if self.named_as_target is not None:
        payload["named_as_target"] = self.named_as_target.to_payload()
    if self.controller_controls is not None:
        payload["controller_controls"] = self.controller_controls.to_payload()
    # Additive keys — handlers read these with .get() defaults.
    if self.with_keywords:
        payload["with_keywords"] = list(self.with_keywords)
    if self.without_keywords:
        payload["without_keywords"] = list(self.without_keywords)
    if self.controller:
        payload["controller"] = self.controller
    # Emitted on its own, not only beside a controller. It used to hang off
    # the branch above because the one card printing ownership printed both
    # words ("you both own and control", Obelisk of Undoing) — but "all
    # Auras **you own** attached to permanents you control" (Remove
    # Enchantments) narrows by ownership and by the *host's* controller,
    # which is a different seat question about a different object. Nested
    # under the controller test, that Aura's ownership was dropped and the
    # sweep took the opponent's Auras too.
    if self.owner is not None:
        payload["owner"] = self.owner
    if self.owner_or_controller is not None:
        payload["owner_or_controller"] = self.owner_or_controller
    if self.attacking is True:
        payload["attacking_only"] = True
    elif self.attacking is False:
        # "target **nonattacking**, nonblocking creature" (Unlikely
        # Alliance). Both directions, like ``blocked`` below — the field has
        # been ``bool | None`` all along and only the True half had a
        # payload form, which is the silent-drop the ``blocked`` comment
        # names: a card printing the negative would have been narrowed by
        # nobody and pumped anything on the board.
        payload["not_attacking"] = True
    if self.blocked_by_source:
        payload["blocked_by_source"] = True
    # "target creature **blocking this creature**" (Barbed-Back Wurm), and
    # the mirror of the key above it. It reached ``subject_matches``'s
    # footing the day the *other* direction did — both are relations to the
    # ability's own source, both are answered off the same combat maps, and
    # that function already takes the source — but it stayed unemitted a set
    # longer for want of a card that printed it as a **target**. The one
    # card that reads it as a *count* ("for each creature blocking it",
    # Johtull Wurm) lifts the key out of the payload itself, so the specs
    # written before this are byte-identical.
    if self.blocking_source:
        payload["blocking_source"] = True
    if self.blocking_attached_host:
        payload["blocking_attached_host"] = True
    if self.blocked_or_was_blocked_this_turn:
        payload["blocked_or_was_blocked_this_turn"] = True
    if self.blocked_source_this_turn:
        payload["blocked_source_this_turn"] = True
    if self.tapped_to_pay_for_source_this_turn:
        payload["tapped_to_pay_for_source_this_turn"] = True
    if self.other_than_attached_host:
        payload["other_than_attached_host"] = True
    if self.banded_with_source:
        payload["banded_with_source"] = True
    if self.attacking_you:
        payload["attacking_you"] = True
    if self.attacked_you_this_turn:
        payload["attacked_you_this_turn"] = True
    if self.was_dealt_damage_this_turn:
        payload["dealt_damage_this_turn"] = True
    if self.blocking is True:
        payload["blocking_only"] = True
    elif self.blocking is False:
        payload["not_blocking"] = True
    # "…by **unblocked** creatures" (Kjeldoran Royal Guard, Veteran
    # Bodyguard) / "**blocked** creature" (Sorrow's Path). CR 509.1h makes
    # both a state of the attacking permanent itself, so both are payload
    # keys like ``attacking_only`` beside them. Until they were, the field
    # had **no** payload form at all: every lowering that built a filter
    # payload dropped it silently, which is a sweep over every creature
    # where the card printed one word of narrowing.
    if self.blocked is True:
        payload["blocked_only"] = True
    elif self.blocked is False:
        payload["unblocked_only"] = True
    if self.any_states:
        payload["any_states"] = list(self.any_states)
    if self.other_than_source:
        payload["exclude_self"] = True
    if self.not_ability_targeted_by_same_name:
        payload["not_ability_targeted_by_same_name"] = True
    if self.shares_name_with_another:
        payload["shares_name_with_another"] = True
    if self.name_from_event:
        payload["name_from_event"] = True
    if self.excluded_basic_lands:
        payload["exclude_basic_lands"] = True
    if self.not_enchanted:
        payload["not_enchanted"] = True
    if self.enchanted_only:
        payload["enchanted_only"] = True
    if self.nontoken:
        payload["nontoken"] = True
    # "…with a name originally printed in the <Set> expansion" -- a fact
    # about the card, emitted like ``named`` below and tested by the pure
    # matcher for the same reason.
    if self.original_expansion:
        payload["original_expansion"] = self.original_expansion
    if self.chosen_color:
        payload["chosen_color"] = True
    if self.chosen_keyword:
        payload["chosen_keyword"] = True
    if self.chosen_creature_type:
        payload["chosen_creature_type"] = True
    # Emitted, and deliberately outside ``TESTABLE_SUBJECT_FILTER_KEYS``:
    # no matcher can answer "of your choice", so every gate asking whether a
    # payload is testable refuses the phrase and the only way through is a
    # lowering that reads the word and puts the choice where the rules do.
    if self.creature_type_of_your_choice:
        payload["creature_type_of_your_choice"] = True
    if self.chosen_land_type:
        payload["chosen_land_type"] = True
    if self.attacked_this_turn is True:
        payload["attacked_this_turn"] = True
    elif self.attacked_this_turn is False:
        payload["not_attacked_this_turn"] = True
    if self.could_attack_this_turn is True:
        payload["could_attack_this_turn"] = True
    if self.cast_by_you_this_turn:
        payload["cast_by_you_this_turn"] = True
    if self.controlled_since_turn_start is True:
        payload["controlled_since_turn_start"] = True
    if self.token_only:
        payload["token_only"] = True
    if self.created_with_source:
        payload["created_with_source"] = True
    if self.put_onto_battlefield_by_source:
        payload["put_onto_battlefield_by_source"] = True
    # "a card **named** Frantic Inventory". Emitted like every other
    # restriction, and tested like one — a key a matcher dropped would be a
    # count over every card in the graveyard.
    if self.named:
        payload["named"] = self.named
    # The two negatives beside it, each emitted so that every gate asking
    # "are all this payload's keys testable?" sees the narrowing — a
    # dropped exclusion on a condition is a static that holds on a board the
    # card does not name.
    if self.not_named:
        payload["not_named"] = self.not_named
    if self.not_named_source:
        payload["not_named_source"] = True
    if self.with_protection_from:
        payload["with_protection_from"] = self.with_protection_from
    # "of their choice" says *who picks*, which is not a property of the
    # objects picked from — no matcher can test it, and it is deliberately
    # absent from ``TESTABLE_SUBJECT_FILTER_KEYS`` for that reason. Emitting
    # it anyway is what makes the absence load-bearing: every gate that asks
    # "are all this payload's keys testable?" refuses the phrase, so the only
    # way through is a lowering that reads the word and says why its rule
    # already puts the choice there (``_lower_sacrifice``, CR 701.21a).
    if self.their_choice:
        payload["their_choice"] = True
    # "non-Spirit creature" (Roaming Ghostlight). Emitted only when set, so
    # every payload written before this key existed is byte-identical.
    if self.excluded_subtypes:
        payload["exclude_subtypes"] = list(self.excluded_subtypes)
    # "with mana value 3 or less" (Eliminate); "with mana value **X** or less"
    # (Meltdown, Citanul Flute, Ugin's second ability). A literal bound rides
    # the payload as the number it is; a variable one rides it as the string
    # "x", which is the same spelling every *amount* in the engine uses for a
    # value the announcement supplies — and `_execute_oracle_instruction`
    # substitutes it at the one dispatch point, beside the ``x_from_count``
    # substitution that is there for exactly this reason.
    #
    # It used to be left unemitted, so `_filter_payload` refused the line
    # rather than dropping the bound: the right direction while nothing could
    # resolve it, and a card that reports unsupported once something can.
    if self.mana_value is not None:
        payload["mana_value"] = {
            "op": self.mana_value.op,
            "value": (
                self.mana_value.value.value
                if isinstance(self.mana_value.value, Fixed)
                else X_BOUND
            ),
        }
    # "…with mana value less than or equal to the number of rust counters on
    # it" (Corrosion). Always emitted when set, for `characteristic_vs_source`'s
    # reason below: there is no literal half to fall back to, and a set field
    # with no key is exactly what `dropped_narrowings` refuses.
    if self.mana_value_at_most_counters is not None:
        payload["mana_value_at_most_counters"] = self.mana_value_at_most_counters
    if self.mana_value_equals_source_counters is not None:
        key = "mana_value_equals_source_counters"
        payload[key] = self.mana_value_equals_source_counters
    if self.power_at_most_source_counters is not None:
        key = "power_at_most_source_counters"
        payload[key] = self.power_at_most_source_counters
    if self.power_greater_than_cards_in_hand is not None:
        key = "power_greater_than_cards_in_hand"
        payload[key] = self.power_greater_than_cards_in_hand
    # "with power 4 or greater" (Turret Ogre's intervening-if). Same rule
    # as mana_value: a literal bound rides the payload and the matcher
    # tests it against the layer-computed stat; a variable bound stays
    # unemitted. Both stats, because emitting one and dropping the other
    # would let a toughness restriction vanish silently.
    if self.power is not None and isinstance(self.power.value, Fixed):
        payload["power"] = {"op": self.power.op, "value": self.power.value.value}
    if self.toughness is not None and isinstance(self.toughness.value, Fixed):
        payload["toughness"] = {
            "op": self.toughness.op,
            "value": self.toughness.value.value,
        }
    # "…with power equal to or greater than the enchanted creature's
    # toughness" (Ironclaw Curse). Always emitted when set — there is no
    # "literal only" half to fall back to, and a set field with no key is
    # exactly what `dropped_narrowings` refuses.
    if self.characteristic_vs_source is not None:
        payload["characteristic_vs_source"] = {
            "characteristic": self.characteristic_vs_source.characteristic,
            "op": self.characteristic_vs_source.op,
            "source_characteristic":
                self.characteristic_vs_source.source_characteristic,
        }
    if self.colored:
        payload["colored_only"] = True
    # "with a +1/+1 counter on it" (Tempered Veteran). Emitted only when
    # set, so every payload written before this key existed is
    # byte-identical.
    if self.with_plus1_counter:
        payload["with_plus1_counter"] = True
    # "with a **bounty** counter on it" (Bounty Hunter). Emitted only when
    # set, for the reason its neighbour is.
    if self.with_named_counter:
        payload["with_named_counter"] = self.with_named_counter
    # "a **legendary** card" (Niambi), "target **legendary** creature". A
    # supertype is a restriction like any other and rides the payload like
    # any other; until this key existed it rode nothing at all, and
    # "Destroy target legendary creature." lowered byte-identically to
    # "Destroy target creature." — the printed word consumed, recorded on
    # the AST, and then dropped on the way to the dispatcher.
    #
    # All or nothing. A phrase naming a supertype no matcher can test emits
    # no key rather than a narrowed one, so the field stays visibly set with
    # nothing behind it and the three gates below refuse the line. Emitting
    # the testable half would drop the other half silently, which is the
    # thing being fixed.
    if self.supertypes and set(self.supertypes) <= TYPE_LINE_SUPERTYPES:
        payload["supertypes"] = list(self.supertypes)
    if self.excluded_supertypes:
        payload["exclude_supertypes"] = list(self.excluded_supertypes)
    return payload
