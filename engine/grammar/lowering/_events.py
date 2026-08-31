"""What a back-reference in a *triggered* ability names.

Beside `_common` rather than inside it, and beside the families rather than in
one of them: every value here is keyed by **trigger-condition kind**, and every
one answers the same question — the sentence says "that player", "that much" or
"they", and the referent is not in the sentence. It is whatever the firing event
froze (CR 603.10), because by the time the trigger resolves the creature is in a
graveyard, the blocker has left combat, or the upkeep has moved on.

Each is a *table* rather than a rule, and that is load-bearing. An event either
carried a subject, a seat or a number or it did not; a rule would have to guess,
and guessing here is silent in both directions — a back-reference reading zero
off an empty context compiles clean and does nothing, and one reading the wrong
seat compiles clean and does something to the wrong player. So a condition absent
from a table refuses the line instead.

Split out of `_common` when it crossed the thousand-line guard: `_common` is
"payload shapes every family needs" and these are "what the event left behind",
which is a different question with a different key. Both are shared modules —
six lowering families read something here — so `test_grammar_layering.py` names
this one beside `_common` in its `shared` tuple.
"""

from __future__ import annotations

from ...oracle_types import EXILED_THIS_WAY, EXILED_THIS_WAY_OBJECTS
from ...tokens import CREATED_TOKEN_RESULT_KEY
from .. import ast
from ..errors import LoweringError

# Trigger events that hand a *damaged player* to the effect after them: "that
# player" names the player the trigger recorded taking the damage
# (``defending_player_index`` in the trigger's context), and nothing in the
# instruction's own payload. Under any other trigger the same words would name
# a player nobody recorded. Here rather than beside one reader because two
# effect families ask it — a discard (Hypnotic Specter) and a player counter
# (Pit Scorpion) — and a fragment two families need belongs in the shared
# module.
_DAMAGED_PLAYER_EVENTS: frozenset[str] = frozenset({"damage_dealt"})


# Trigger events after which "that player" names the controller of the object
# the event was about, frozen into the trigger's context by the fire site.
#
# Here rather than beside either reader: two effect families ask it — a life
# loss (Massacre Wurm) and a damage event (Backfire) — and a fragment two
# families need belongs in the shared module, which is the same rule the parse
# side's `phrases.py` follows.
_EVENT_SUBJECT_CONTROLLERS: frozenset[str] = frozenset({
    "creature_opponent_controls_dies",   # Massacre Wurm — the dead creature's
    "creature_becomes_blocked",          # Gloom Sower — the blocker's
    # Backfire — the damager's. The subject of a damage event is whatever dealt
    # it, so "that creature's controller" is the seat `deal_damage` derives for
    # every event and freezes into the announcement.
    "damage_dealt",
    # Psychic Venom — the tapped land's. Both tap announcements stamp the key
    # (`become_tapped`), because the words name the object the event was about
    # and not the seat that did the tapping: an Icy Manipulator taps a land its
    # controller does not own, and the printed sentence still means the land's
    # controller. Absent from this table the phrase fell through to
    # `target_player`, which is a choice the card never offers — so Psychic
    # Venom damaged the Aura controller's opponent, and did it even when the
    # enchanted land was the Aura controller's own.
    "permanent_becomes_tapped",
    # Haunting Wind, Artifact Possession — the tapped artifact's, for the same
    # reason and from the same stamp. This condition has two announcements (a
    # tap, and an ability activated without {T}); both freeze the *subject's*
    # controller, which is the artifact's, never the activating seat.
    "permanent_tapped_or_ability_activated",
})


#: Trigger conditions whose fire site freezes the **object** the event was about
#: (``event_subject_permanent_id``), so a bare "it" in the effect names that
#: permanent rather than the ability's own source.
#:
#: A third table beside the two above rather than more entries in either,
#: because the three answer different questions off different frozen keys: the
#: seat that controlled the subject, the seat that *was* the subject, and the
#: subject itself. Reading one from another's key is how a phrase resolves
#: against whatever an empty context defaults to.
#:
#: Membership is a claim about the fire site, and the site is what makes it
#: true: ``become_tapped`` stamps the id (CR 400.7 — an index is not an
#: identity, and by resolution the permanent may have moved). Kudzu's "destroy
#: it" already reads the same key from its own handler.
_EVENT_SUBJECT_OBJECTS: frozenset[str] = frozenset({
    "permanent_becomes_tapped",         # Freyalise's Winds, Kudzu
})


#: Trigger conditions whose subject **is a player** rather than an object, so
#: "that player" (and its pronoun "they") names the seat the event was about
#: directly — there is no object in between to take a controller from.
#:
#: A separate table from `_EVENT_SUBJECT_CONTROLLERS` rather than more entries
#: in it, because the two answer different questions and the fire sites freeze
#: different things. Folding "each player's upkeep" into the controller table
#: would have read the seat out of `event_subject_controller`, a key no upkeep
#: fire site stamps, and every such card would have resolved against whatever
#: an empty context defaults to.
#:
#: `upkeep_self` is deliberately absent: "at the beginning of **your** upkeep"
#: has only one seat and it is already spelled "you". Only the conditions whose
#: seat *varies* need freezing, and `upkeep_each` is the one the ordinary
#: (non-registry) upkeep path admits — see `_ORDINARY_UPKEEP_SEATS`.
_EVENT_SUBJECT_PLAYERS: frozenset[str] = frozenset({
    "upkeep_each",                       # Spiritual Sanctuary, Storm World
    # "Whenever an opponent draws a card, this enchantment deals 1 damage to
    # **that player**" (Underworld Dreams). CR 121.2 makes a draw a per-card
    # event about one seat, and which seat varies per firing — an opponent in a
    # three-player game is not "the opponent" — so it is frozen by the draw
    # sweep that announces it rather than re-derived at resolution.
    "draws_card",
    # "Whenever an opponent casts an instant spell …, this creature deals 4
    # damage to **that player**" (Ichneumon Druid). The condition names one
    # seat — whoever cast the spell — and nothing chose it, so it is the seat
    # the cast froze rather than a target. Read as `target_player` instead, the
    # ability would ask for a choice the card never offers.
    "opponent_casts_spell",
})

#: Delayed-trigger events (CR 603.7) whose fire site freezes the **owner** of
#: the object the event was about, under `EVENT_SUBJECT_OWNER` below.
#:
#: Its own table beside `_EVENT_SUBJECT_CONTROLLERS` rather than more entries in
#: it, and for that table's own stated reason: ownership is CR 108.3 and never
#: changes, control is CR 613 layer 2 and does. Reincarnation returns the card
#: under the *owner's* control, so reading the controller instead would hand the
#: creature to whoever had stolen the one that died.
_EVENT_SUBJECT_OWNERS: frozenset[str] = frozenset({
    "bound_permanent_dies",              # Reincarnation
})

#: Delayed-trigger events (CR 603.7) whose entry names a **particular object**
#: — CR 603.7c. `create_delayed_trigger` stamps that permanent's id into the
#: trigger's context, so a clause back-referring to it ("that creature", "…that
#: were blocked by that creature this turn") is admitted only under one of
#: these. Under any other event the words name an object nobody recorded, and a
#: sweep that dropped the relation would take the whole board.
#:
#: Held to `delayed_triggers.DELAYED_EVENTS` by
#: `tests/engine/test_delayed_triggers.py`, so a renamed event cannot leave a
#: row here pointing at nothing.
_BOUND_OBJECT_DELAYED_EVENTS: frozenset[str] = frozenset({
    "bound_permanent_dies",              # Reincarnation
    "bound_permanent_dealt_damage",      # Glyph of Life
    "next_end_of_combat",                # Glyph of Doom
    # War Barge ("when this artifact leaves the battlefield this turn, destroy
    # **that creature**") and Runesword. The object the ability is *about* is
    # not always the object it watches: this membership is the acted-on half,
    # and `DelayedTrigger.watched_permanent_id` carries the watched one.
    "bound_permanent_leaves_battlefield",
    # Merieke Ri Berit: watches its own source, destroys **that creature** —
    # the same two-object shape War Barge prints, with the wider event.
    "bound_permanent_leaves_or_untaps",
})

#: The payload key the delayed machinery stamps that object's id under.
BOUND_PERMANENT_ID = "bound_permanent_id"

#: The scratchpad key a token maker writes the created token's ``permanent_id``
#: under. Imported rather than spelled again: ``engine/tokens.py`` is the one
#: home for it, because the handler that writes it lives on the other side of
#: the pipeline from the lowering that gates the phrase on it.
CREATED_TOKEN = CREATED_TOKEN_RESULT_KEY

#: What "**exiled this way**" names (Martyr's Cry): the `produced` marker a
#: sweep that exiles stamps, and the scratchpad key it records the objects
#: under. Imported rather than spelled again for ``CREATED_TOKEN``'s reason —
#: the sweep handler writes them and this lowering gates on them, so the two
#: sides live on opposite ends of the pipeline and a second copy would rot.

#: The payload key those fire sites stamp it under. One constant for the same
#: reason `EVENT_SUBJECT_PLAYER` is one: the fire site writes it and the handler
#: reads it, and three copies of a string is how they come apart.
EVENT_SUBJECT_OWNER = "event_subject_owner"

#: The payload spelling both a recipient and a condition subject use for that
#: seat. One constant, because the fire site writes it, the life handler reads
#: it and `evaluate_condition` reads it — three copies of a string is how they
#: come apart.
EVENT_SUBJECT_PLAYER = "event_subject_player"


# What a bare "that much" names when the effect is a *triggered ability*: the
# quantity the firing event carried, frozen into the trigger's context by the
# fire site. Keyed by trigger-condition kind, and deliberately a table rather
# than a rule — an event either carries a number or it does not, and a kind
# absent here refuses the back-reference instead of reading a zero out of an
# empty context.
_EVENT_QUANTITIES: dict[str, str] = {
    "you_gain_life": "life_gained",
    # "Whenever another creature you control enters, this creature deals damage
    # equal to **that creature's** power…" (Terror of the Peaks). The entering
    # creature's power, frozen by the fire site — by the time the trigger
    # resolves the creature may have been pumped or destroyed, and CR 608.2's
    # number is the one the event had.
    "matching_permanent_enters": "entering_power",
    # "Whenever this creature **is dealt damage**, it deals that much damage to
    # target opponent." (Brash Taunter.) The number is frozen by the fire site,
    # because by resolution the marked damage may have been added to or wiped.
    "creature_dealt_damage": "damage_dealt",
    # **The whole "deals damage" family, in one row.** "You gain that much
    # life" (Spirit Link, El-Hajjâj), "this creature deals that much damage to
    # …" (Chandra's Incinerator, Backfire), "look at that many cards"
    # (Garruk's Harbinger) — one event, one number, recorded once by
    # `damage_events._announce`. It is the damage *dealt* (CR 120.4b), not what
    # the life total lost: Ali from Cairo caps the second without capping the
    # first.
    #
    # This row is what retires a *deliberate refusal*. El-Hajjâj's "you gain
    # that much life" was recorded as one, on the grounds that "its fire site
    # records the amount under a different key" — which was true of a fire
    # site, not of the rule, and stopped being true the moment there was one
    # seam to record it at.
    "damage_dealt": "amount",
    # "Whenever that creature is dealt damage by an attacking creature this
    # turn, you gain **that much** life." (Glyph of Life.) A delayed triggered
    # ability (CR 603.7) reads its number from the same place an ordinary one
    # does — the context its fire site froze — so it is a row here rather than
    # anything the delayed machinery answers for itself.
    "bound_permanent_dealt_damage": "damage_dealt",
}

# The scratchpad key the untap records and two later sentences read ("remove
# **it** from combat", "gain control of **that creature**" — Disharmony). One
# name in one place, shared by the ``board`` and ``combat`` lowering families,
# because a fragment two families need lives here rather than in either of
# them — and because ``categories._PRODUCES`` writes the same string, so a
# second spelling would make the producer gate vacuous while the handler read
# an empty record.
_UNTAPPED_PERMANENTS = "untapped_permanents"

# What a one-way bite recorded it damaged, so the sentence after it can name the
# same creature: "This creature deals damage equal to its power to target
# creature. **That creature** deals damage equal to its power to this creature."
# (Tracker.) Named here for the reason the key above is - the `damage` lowering
# family and ``categories._PRODUCES`` both write the string, and a second
# spelling would make the producer gate vacuous while the handler read an empty
# record.
_DAMAGED_PERMANENTS = "damaged_permanents"

# The seat "Choose a player who cast one or more sorcery spells this turn."
# records, and the number "the damage dealt by one of those sorcery spells this
# turn" records once one of them is chosen (Backdraft). Named here beside the
# two above and for their reason: the `game` and `damage` lowering families and
# ``categories._PRODUCES`` all write these strings, so a second spelling would
# make one producer gate vacuous while the handler read an empty record — and
# on this card that is a spell that reports itself resolved and deals nothing.
CHOSEN_PLAYER = "chosen_player"

# The scratchpad key a "<player> chooses <permanent>" step writes and the
# sentences behind it read — "attach it to **that** permanent" (Enchantment
# Alteration), "return this card … **attached to that creature**"
# (Takklemaggot). Named here for the reason every other key on this page is:
# the ``board`` and ``zones`` lowering families and ``categories._PRODUCES``
# all write the string, and a second spelling would make one producer gate
# vacuous while the handler read an empty record.
CHOSEN_PERMANENT = "attach_host"
CHOSEN_CAST_DAMAGE = "damage_dealt_by_chosen_cast"

# The scratchpad keys that are *quantities*. `categories._PRODUCES` also records
# things no amount can read — a controller's seat, a list of exiled cards — so
# a bare back-reference resolves against this narrower set. A producer added
# there and not here fails safe: the bare reading refuses rather than reading a
# number out of something that is not one.
_PRODUCED_QUANTITIES: frozenset[str] = frozenset({
    "damage_dealt",
    # How many cards a discard this effect asked for actually went (Recall).
    "discarded_count",
    CHOSEN_CAST_DAMAGE,
})

# The scratchpad keys that hold *permanents*, by id — what an earlier step of
# this effect acted on rather than a number it computed. A clause reading a
# characteristic off "that creature" (Energy Tap's mana value) resolves against
# these: the permanent is still on the battlefield, so the characteristic is
# read at resolution instead of being remembered. The mirror of
# `_PRODUCED_QUANTITIES` above and narrow for the same reason — a producer
# missing from here refuses the words rather than reading a mana value out of
# something that is not a permanent.
#: The tap half of the pair, named for the same reason ``_UNTAPPED_PERMANENTS``
#: is: two lowering families and ``categories._PRODUCES`` all write this string,
#: and a second spelling would make one of the producer gates vacuous while the
#: handler read an empty record.
_TAPPED_PERMANENTS = "tapped_permanents"

_RECORDED_PERMANENTS: frozenset[str] = frozenset({
    _TAPPED_PERMANENTS, _UNTAPPED_PERMANENTS,
})


def _back_reference_payload(
    amount: ast.ThatMuch,
    produced: frozenset[str],
    event: str | None,
) -> dict[str, object]:
    """Where a handler should read *amount* from, as payload keys.

    ``amount_from`` is a key in this resolution's scratchpad (an earlier step of
    the same effect recorded it); ``amount_from_trigger`` is a key in the firing
    event's captured context. Which one applies is decided here, once, rather
    than by each effect family guessing — reading a trigger's number out of the
    scratchpad silently yields zero, which is the failure this refuses on
    behalf of every caller.
    """
    if amount.source == "event_subject_power":
        # "That creature's power" names the *event's* object, so the only place
        # it can be read is the firing event's captured context — and only under
        # an event whose fire site records one. Under any other trigger the words
        # name a creature nobody recorded, and the amount would silently be zero.
        key = _EVENT_QUANTITIES.get(event or "")
        if key is None:
            raise LoweringError(
                "\"that creature's power\" needs a trigger whose event records "
                "one",
                node=amount,
            )
        return {"amount_from_trigger": key}
    if amount.source is not None:
        # The words named the producer ("equal to the damage dealt"), so a step
        # of this same effect has to have recorded it.
        if amount.source in produced:
            return {"amount_from": amount.source}
        raise LoweringError(
            f"back-reference to {amount.source!r} with no producer in this effect",
            node=amount,
        )
    key = _EVENT_QUANTITIES.get(event or "")
    if key is not None:
        return {"amount_from_trigger": key}
    within = tuple(sorted(produced & _PRODUCED_QUANTITIES))
    if len(within) == 1:
        return {"amount_from": within[0]}
    raise LoweringError(
        "bare back-reference with no producer in this effect and no quantity "
        "on its trigger",
        node=amount,
    )


# Trigger events that bind a *blocking pair*, so "that creature" names the other
# half of it — "destroy that creature at end of combat" (Thicket Basilisk),
# "that creature becomes green" (Aisling Leprechaun). The sentence only means
# what it says while one of these fired, so anywhere else the pronoun refuses.
#
# **Which** half fired decides how the handler finds the creature, and the two
# fire sites answer differently: the becomes-blocked half makes it the stack
# item's target, the blocks half puts it in `blocked_permanent_ids` and targets
# the blocker itself. `handlers/_common.block_pair_permanents` is the one reader
# of both, so an effect added here does not have to rediscover the difference.
_BLOCK_PAIR_EVENTS = frozenset({
    "creature_blocks_or_blocked_by",           # Thicket Basilisk, Cockatrice,
                                               # Abomination, Aisling Leprechaun
    "creature_becomes_blocked",                # Battering Ram
    "creature_blocks",                         # Infernal Medusa
})


def binds_block_pair(event: str | None, event_subject: object | None) -> bool:
    """Whether "that creature" under *event* names exactly one creature.

    **The kind alone cannot answer**, and reading it as though it could was
    wrong in both directions at once. CR 509.3c/509.3d: "whenever this creature
    becomes blocked" fires *once* however many creatures block it, while
    "…becomes blocked **by a creature**" fires once for each one the phrase
    admits — the narrowing is the whole difference, and the two spellings are
    the same kind.

    So a bare firing has several creatures and no way to say which "that
    creature" is (the fire site takes ``blockers[:1]``, an arbitrary one), and a
    narrowed firing has exactly the one that admitted it. Keyed on the kind
    alone, this table admitted the bare becomes-blocked form — a sentence that
    would destroy whichever blocker happened to be first — and refused the
    narrowed *blocks* form, which is why Infernal Medusa was supported with its
    first line lowering to nothing.

    `creature_blocks_or_blocked_by` carries a subject by construction: both
    front ends require the noun phrase to end the condition, so the joined
    sentence cannot reach here bare.
    """
    return event in _BLOCK_PAIR_EVENTS and event_subject is not None


def _chosen_cast_amount(
    amount: ast.Amount,
) -> "tuple[ast.DamageDealtByChosenCast, str | None] | None":
    """"[half] the damage dealt by one of those <type> spells this turn", and
    how the card said to round it — or None when the amount is something else.

    The halving is unwrapped here rather than inside the branch below, for the
    reason ``lower_where_x`` unwraps ``ast.Times``: the rounding belongs to the
    printed quantity and rides the count spec every computed amount already
    travels on (CR 107.2).
    """
    rounding = None
    if isinstance(amount, ast.Half):
        rounding = amount.rounding
        amount = amount.of
    return (amount, rounding) if isinstance(amount, ast.DamageDealtByChosenCast) else None


#: Trigger events whose *condition* already names the permanent the source is
#: attached to. Under one of them a later "that <noun>" in the same sentence is
#: that same permanent — "At the beginning of the upkeep of enchanted land's
#: controller, destroy **that land**" (Erosion), "…unless they sacrifice **that
#: artifact**" (Curse Artifact).
#:
#: Idiom 20's rule with the noun repeated instead of "it": the pronoun names the
#: object the sentence already named. It has to be an event set rather than a
#: property of the noun phrase, because "that land" under any *other* event is
#: the firing event's object (Hooded Blightfang's damaged planeswalker) and
#: under most events is nothing at all — and a "that" resolved against the
#: wrong one of those does not fail, it acts on a different permanent.
ATTACHED_SUBJECT_EVENTS: frozenset[str] = frozenset({"upkeep_enchanted_controller"})


def names_attached_permanent(subject, event: str | None) -> bool:
    """Whether *subject* names the permanent the ability's source is attached to.

    One reader for both spellings — "it"/"enchanted <noun>", which the noun
    parser already marks, and the repeated "that <noun>" above — so a lowering
    that learns one gets the other and the two cannot come to disagree about
    which permanent an Aura's sentence is talking about.
    """
    from ._common import _is_enchanted

    if _is_enchanted(subject):
        return True
    return (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
        and event in ATTACHED_SUBJECT_EVENTS
    )
