"""Durations that end on an **event** rather than at a turn step (CR 611.2a).

Every other duration in this engine names a *moment in the turn structure* —
the cleanup step, the end of combat, a player's next upkeep — and is ended by a
sweep that step already runs. CR 611.2a allows a second shape — an effect
lasts "as long as stated by the spell or ability creating it", and what the
spell states need not be a turn step at all — and until
Urza's Saga nothing in the pool printed one:

    "{1}{W}, {T}: Target creature becomes an enchantment and loses all
    abilities **until a player casts a creature spell**."  (Soul Sculptor.)

The window closes when something *happens*. Nothing in the turn structure can
end it, so the sweep hangs off the announcement instead — and the announcement
is one that already exists, because a game that can fire "whenever a player
casts a creature spell" (the Opal cycle, Soul Barrier, Straw Golem) already
knows the moment. There is one such site,
``mixins/oracle_instructions._apply_spell_cast_any_triggers``, and that is
where this is called from: the same call that emits the trigger ends the
window, so a cast cannot announce one and not the other.

**The event is the cast, not the resolution** (CR 601.2i: a spell is cast once
it is on the stack and its costs are paid). So the window closes while the
creature spell is still on the stack, and countering that spell does not
re-open it — which is what the card says and the opposite of what a sweep hung
off resolution would do.

**A window whose event never happens never ends.** That is not an omission to
be tidied up at the next cleanup step: CR 611.2a says the effect lasts as long
as the card states, so a Soul Sculptor's target that nobody ever casts a creature
against stays an abilityless enchantment for the rest of the game. Every sweep
in this engine is keyed to the record's own ``duration``, so the turn-step
sweeps pass over these records by construction rather than by anybody
remembering to exclude them.

**What makes a duration legal is having a sweep**, which is why
:data:`EVENT_DURATION_KINDS` is folded into ``keywords.KEYWORD_GRANT_DURATIONS``
rather than spelled there a second time: a row added here becomes a duration the
record channels accept *because* this module now ends it, and a row removed
stops being one. The two cannot drift.

**Whose action closes the window is deliberately not a field.** "A player" is
what the pool prints and it means anybody; "an opponent casts" and "you cast"
are two more printings that would each need CR 109.5's seat carried on the
record, and this engine's grant records only carry a seat for the durations
named in ``keywords.SEATED_GRANT_DURATIONS``. A field here with nothing behind
it would admit those phrases and then ignore the word — a window that ends on
the wrong player's spell, silently. When a card prints one, it gets a row here,
a seat on the record, and a test; until then the phrase has no row and refuses
at lowering, which is the loud direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .keywords import (clear_all_abilities_removals,
                       clear_granted_ability_lines, clear_granted_keywords,
                       clear_removed_ability_keywords)
from .layer_bridge import SET_CARD_TYPES, printed_shape

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent


@dataclass(frozen=True)
class EventWindow:
    """What one printed event-ended duration is watching for.

    *announcement* is the engine's own name for the moment — the same word the
    fire site passes — so a second event kind is a row here and a call there,
    never a branch inside the sweep.

    *card_types* is the printed narrowing on the object the event is about
    ("a **creature** spell"); empty means any spell. It is data for the reason
    every printed word in this engine is: a card saying "until a player casts an
    artifact spell" is one more row, not one more mechanism.
    """

    announcement: str
    card_types: tuple[str, ...] = ()

    def closes_on(self, card) -> bool:
        """Whether a cast of *card* closes this window.

        The type is read off the **printed** card and not off any permanent: a
        spell on the stack is a card (CR 112.1 — there is no permanent to ask), so
        CR 613 does not apply to it and ``printed_shape`` is the accessor for an
        object outside the battlefield.
        """
        if not self.card_types:
            return True
        printed, _ = printed_shape(card)
        return any(word in printed for word in self.card_types)


#: One row per printed phrase. The key is the ``Duration`` kind
#: ``grammar/phrases._DURATIONS`` produces, so the parser's word table and this
#: sweep name the same thing — and a phrase with no row here is a duration the
#: record channels reject, so it refuses at lowering rather than compiling into
#: a window nothing ends.
EVENT_DURATIONS: dict[str, EventWindow] = {
    # "…until a player casts a creature spell." (Soul Sculptor.)
    "until_a_player_casts_a_creature_spell": EventWindow(
        announcement="spell_cast", card_types=("creature",),
    ),
}

#: The duration words above, for ``keywords.KEYWORD_GRANT_DURATIONS`` to fold in.
EVENT_DURATION_KINDS: frozenset[str] = frozenset(EVENT_DURATIONS)


def clear_set_card_types(perm: "Permanent", duration: str) -> bool:
    """Give a CR 205.1a type *replacement* back when its window ends.

    The fifth channel swept at a duration boundary, and the only one whose
    record is a single slot rather than a list: a replacement says what the
    permanent now **is**, so a second one is the same question answered again
    (see ``layer_bridge.SET_CARD_TYPES``) and there is nothing to fold.

    Popped only when the slot's own window is the one closing. A record with no
    duration is Opal Acrolith's — it turned *itself* into an enchantment and
    nothing ever ends that — and a sweep that popped the slot whole would undo
    it on the first creature spell anybody cast.
    """
    record = perm.metadata.get(SET_CARD_TYPES)
    if record and record.get("duration") == duration:
        perm.metadata.pop(SET_CARD_TYPES, None)
        return True
    return False


def holds_window(perm: "Permanent", duration: str) -> bool:
    """Whether *perm* carries any record whose window is *duration*.

    The five channels an event-ended window can be written on, asked in one
    place. It reads the same ``duration`` key each sweep compares, so "is there
    anything to end?" and "end it" cannot disagree about where a record lives —
    a channel added to one and not the other would be a window that reported
    nothing to do and then left an effect running.
    """
    from .keywords import (ABILITY_EFFECTS, ALL_ABILITIES_REMOVED,
                           GRANTED_ABILITY_LINES, REMOVED_ABILITY_KEYWORDS)

    # **`REMOVED_ABILITY_KEYWORDS`, not `REMOVED_ABILITY_LINES`** — two names one
    # word apart, and this asked the wrong one. The *lines* channel is a list of
    # bare normalized sentences with no duration at all (`remove_ability_line`
    # says so in as many words: "nothing in this pool takes an ability away for a
    # while, and a duration nothing sweeps would be a promise the engine does not
    # keep"), so `entry.get` raised `AttributeError` on a `str` the first time a
    # permanent that had lost a line met a spell-cast-ended window. **Leeching
    # Licid crashed every Tempest AI simulation**, which is how it surfaced: the
    # Licid's own ability removes its printed line, then any creature spell cast
    # afterwards reached here.
    #
    # It is also wrong in the direction this function's docstring warns about,
    # crash aside: the sweep below clears `REMOVED_ABILITY_KEYWORDS` through
    # `clear_removed_ability_keywords`, and nothing anywhere ends a removed
    # *line*. So the "is there anything to end?" half was asking about a channel
    # the "end it" half does not touch — the exact disagreement the tuple exists
    # to prevent, with the two halves naming different keys.
    for key in (ABILITY_EFFECTS, GRANTED_ABILITY_LINES, REMOVED_ABILITY_KEYWORDS,
                ALL_ABILITIES_REMOVED):
        for entry in perm.metadata.get(key) or ():
            if entry.get("duration") == duration:
                return True
    record = perm.metadata.get(SET_CARD_TYPES)
    return bool(record) and record.get("duration") == duration


def end_event_durations(game, announcement: str, *, card) -> list[str]:
    """End every window a *card* being announced closes; the kinds that ended.

    Called from the site that makes the announcement, beside the trigger emit,
    so "the game noticed this happened" is one thing rather than two.

    The four ability channels are swept in the order the cleanup step and the
    end-of-combat step already sweep them — a duration ending has to mean the
    same things whichever moment ended it — plus the type replacement, which has
    no turn-step window at all and so is swept only here. ``seat=None`` is what
    makes each sweep take *every* record of the kind: these windows belong to
    nobody in particular, which is the whole content of the printed words "a
    player".
    """
    ended: list[str] = []
    for kind, window in EVENT_DURATIONS.items():
        if window.announcement != announcement or not window.closes_on(card):
            continue
        for perm in game.all_permanents():
            if not holds_window(perm, kind):
                # Asked before anything is cleared, and it is what keeps the
                # cost of this call proportional to the effects that exist
                # rather than to the board: every creature spell cast in every
                # game reaches here, and on almost all of them there is nothing
                # to end. It is also what makes ``ended`` mean "something
                # actually came back", so the recompute below runs when a
                # characteristic moved and not once per creature spell.
                continue
            clear_granted_keywords(perm, kind)
            clear_granted_ability_lines(perm, kind)
            clear_removed_ability_keywords(perm, kind)
            clear_all_abilities_removals(perm, kind)
            clear_set_card_types(perm, kind)
            if kind not in ended:
                ended.append(kind)
    if ended:
        # The layer-4 and layer-6 reads are computed, but the derived channels
        # (a lord's buff, an animated land's size) are rebuilt from the board
        # rather than on every read — so a creature that has just got its
        # abilities and its card types back has to stop being the enchantment
        # they were cached against now, not at the next thing that happens to
        # refresh.
        game._refresh_dynamic_creatures()
    return ended
