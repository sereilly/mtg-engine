"""What a permanent's **death** leaves behind, for the sentence that reads it.

A floor beside ``_events`` rather than a family, and split out of it when the
Death Watch round pushed that module back over the thousand-line guard. The
seam is not arbitrary: ``_events`` answers "what did the firing event freeze"
across every event there is, and this answers the same question for the one
event class whose answer several *unrelated* families need — a life gain, a
life loss, a damage, a return, a reanimation are all printed about a creature
that is already in a graveyard.

CR 603.10 and CR 608.2h are why any of it is frozen. By the time a death
trigger resolves the permanent is a card in a graveyard: it has a printed power
with no anthem on it, no counters (CR 400.7), and CR 108.4 gives it no
controller at all. Every table here is therefore a claim about a **fire site**,
verified one at a time — an event absent from one refuses the sentence rather
than reading a zero, or a seat, out of a context nothing wrote to.
"""

from __future__ import annotations


#: The trigger events whose fire site records the dying card, so "that card" /
#: "it" in the effect behind them names something the handler can find. Written
#: as a set rather than one literal because three fire sites stamp ``dead_card``
#: and a fourth would only have to be added here — where an event *not* listed
#: refuses the sentence rather than resolving to nothing.
#:
#: Public, because it is not this family's question: ``zones`` asks it too, for
#: "put **that card** onto the battlefield under your control" (Seraph,
#: Krovikan Vampire). One set, so a fire site taught to record the card reaches
#: both readings of the phrase at once — two copies would let a card be returned
#: to a hand and refused onto the battlefield under the same trigger.
BOUND_CARD_EVENTS = frozenset({
    "attached_creature_dies",
    "permanent_dies",
    # "Whenever a creature dealt damage by this creature this turn dies, …"
    # (Seraph, Krovikan Vampire, Sengir Vampire). The scan in
    # ``mixins/helpers._fire_creature_dies_triggers`` stamps the same
    # ``dead_card`` its three sibling scans do — it did not until Seraph asked,
    # which is why the set is what says an event is admitted rather than the
    # condition table that merely names it.
    "creature_dealt_damage_by_self_dies",
})

#: The scratchpad key "that creature's power" falls back to when the sentence
#: sits under no trigger — the power an earlier step of the same effect froze
#: about the permanent it acted on (Broken Visage's destroy). Named here beside
#: the event table because ``_back_reference_payload`` is what chooses between
#: the two, and ``_records._PRODUCES`` writes the same string: a second spelling
#: would make the producer gate vacuous while the handler read an empty record.
_EVENT_SUBJECT_POWER_RECORD = "its_power"

#: Its toughness twin, for the other half of the same printed sentence. A
#: constant rather than a literal for the reason above, and separate from the
#: power because the two are different characteristics of one object rather than
#: one number under two names.
_EVENT_SUBJECT_TOUGHNESS_RECORD = "its_toughness"

#: The same two spellings under a **death**, where the number is not in any
#: scratchpad: the fire site froze it (CR 603.10 / 608.2h), because by
#: resolution the permanent is a card in a graveyard with a printed number and
#: no anthem on it. Built from the constants above so one key has one name.
DEAD_CHARACTERISTIC_RECORDS: dict[str, str] = {
    _EVENT_SUBJECT_POWER_RECORD: "dead_power",
    _EVENT_SUBJECT_TOUGHNESS_RECORD: "dead_toughness",
}

#: And **which** deaths freeze them: a claim about a fire site, verified one at
#: a time. ``creature_dies`` is deliberately absent though the same context
#: announces it — the scan reaching it rebuilds a context of its own for a
#: ``target_gains_life`` instruction, so a trigger lowered onto that kind with
#: an ``amount_from_trigger`` would arrive with the numbers missing and use the
#: payload's default. A row goes in when that branch is retired, not before.
DEAD_CHARACTERISTIC_EVENTS: frozenset[str] = frozenset({
    "dies",                    # the permanent's own death loop
    "permanent_dies",          # _fire_permanent_dies_triggers
    "attached_creature_dies",  # _fire_creature_dies_triggers' died_context
})
