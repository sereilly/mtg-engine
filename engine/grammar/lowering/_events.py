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

The **scratchpad key names** left at Tempest's Phase 0, for the half of that
same sentence this module had stopped keeping: a key one step of a resolution
writes and a later sentence reads back (CR 608.2) is keyed by nothing and is
not about a firing event at all. They are `_record_keys.py` now, re-exported
from here so no family's import moved, and `_records` next door already said
the line — "three tables, three keys, three questions".
"""

from __future__ import annotations

from ...exiled_records import (EXILE_RECORD_KEY,
                               EXILED_SPELL_CONTROLLER_KEY)

from ...oracle_types import (ATTACHED_PERMANENT_CONTROLLER,  # noqa: F401
                             LAST_TARGET_NAME,
                             EXILED_THIS_WAY, EXILED_THIS_WAY_OBJECTS)
from .. import ast
from ..errors import LoweringError
from ._deaths import (DEAD_CHARACTERISTIC_EVENTS, DEAD_CHARACTERISTIC_RECORDS,
                      _EVENT_SUBJECT_POWER_RECORD,
                      _EVENT_SUBJECT_TOUGHNESS_RECORD)
# The scratchpad key *names*, split out at Tempest's Phase 0 along the line both
# this docstring and `_records`' already drew: nothing over there is keyed by a
# trigger-condition kind. Re-exported under the names this module used, so every
# family that reads one is untouched — `_common` and `_filters` have the same
# arrangement, and for the same reason.
from ._record_keys import (CHOSEN_CAST_DAMAGE,  # noqa: F401
                           CHOSEN_DAMAGE_SOURCE, CHOSEN_PERMANENT,
                           CHOSEN_PLAYER, COUNTED_NUMBER, CREATED_TOKEN,
                           CREATED_TOKENS,
                           DAMAGE_RECIPIENT, EXTRA_TURN_GRANTED,
                           LOOP_BOUND_OBJECT, LOOP_BOUND_PLAYER,
                           OTHER_CHOSEN_PERMANENT, PUT_FROM_HAND_PERMANENTS,
                           SWEPT_CONTROLLER_SEATS,
                           _COUNTERS_PLACED_THIS_WAY, _DAMAGED_PERMANENTS,
                           _PERMANENTS_MADE_BY_THIS_EFFECT,
                           _PRODUCED_QUANTITIES, _REANIMATED_PERMANENTS,
                           _RECORDED_PERMANENTS, _SPELL_POSSESSIVE_RECORDS,
                           _TAPPED_PERMANENTS, _UNTAPPED_PERMANENTS)

# The seat half of this module's three questions, split out at Mercadian
# Masques' second Phase 0 when the file reached 990 of the thousand-line guard.
# Re-exported under the spellings it had, so no family's import moved — the same
# move _record_keys made at Tempest's Phase 0 and for the same reason: this
# is a shared floor, and a floor that renames its names on a split makes every
# reader of it a caller that moved.
from ._frozen_seats import (  # noqa: F401
    DAMAGED_PERMANENT_CONTROLLER,
    EVENT_SUBJECT_CONTROLLER,
    EVENT_SUBJECT_OWNER,
    EVENT_SUBJECT_PLAYER,
    OPPONENT_CHOSE_MODE,
    _DAMAGED_PLAYER_EVENTS,
    _DEFENDING_PLAYER_EVENTS,
    _EVENT_SUBJECT_CONTROLLERS,
    _EVENT_SUBJECT_OWNERS,
    _EVENT_SUBJECT_PLAYERS,
    damage_trigger_names_damaged_end,
    frozen_seat_record,
)


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
    # "Whenever a Djinn or Efreet enters, **destroy it**." (Suleiman's Legacy.)
    # The entering permanent, stamped by the one entry transition
    # (`_put_permanent_onto_battlefield`) — every path onto a battlefield goes
    # through it, so the announcement and the freeze are one place.
    "matching_permanent_enters",
    # "Whenever a creature attacks you, **it** loses flanking until end of
    # turn" / "…this enchantment deals 1 damage to **it**" (Barbed Foliage).
    # The declared attacker, stamped by `_fire_matching_creature_attacks_triggers`
    # for the same reason `become_tapped` stamps its subject: the announcement
    # is game-wide and per object, and by resolution the creature may have been
    # removed from combat or destroyed.
    "matching_creature_attacks",
    # "Whenever a creature of the chosen color deals damage to you …, this
    # enchantment deals that much damage to **that creature**." (Mangara's
    # Equity.) CR 120.4b's event, whose one seam (`damage_events._announce`)
    # freezes the damager's id — the object the words name, which is the *other*
    # end of the event from the permanent it damaged.
    "damage_dealt",
    # "Whenever a creature is dealt damage, **destroy it**." (Death Pits of
    # Rath.) The *damaged* creature, which is what the subject of this event is
    # — the row above is the other way round, and the two are the two ends of
    # one damage event (`_EVENT_SUBJECT_CONTROLLERS` says the same thing about
    # the seats). Frozen by `_fire_dealt_damage_triggers`, which stamps the id
    # while the creature is still on a battlefield: this trigger resolves off
    # the stack (CR 603.3) and lethal damage puts it in a graveyard before then,
    # where CR 400.7 makes it a new object.
    "creature_dealt_damage",
    # "Whenever a Sliver becomes blocked, **that Sliver** gets +1/+1 until end
    # of turn for each creature blocking it." (Spined Sliver.) The creature
    # that became blocked — the attacker, which is the half this board-wide
    # event is announced *about*; its partner is the blocker, and
    # `ROLE_NAMES_BLOCK_PARTNER` below is where a printed role word reaches
    # that one instead.
    #
    # Both of the kind's fire sites stamp the id
    # (`declare_blockers_step._fire_board_wide_block_triggers` for CR 509.3d's
    # narrowed reading, `_announce_bare_board_wide_blocks` for CR 509.3c's bare
    # one), which is what this table is a claim about — and the *source*-scoped
    # scan one screen up announces `creature_becomes_blocked`, a different kind
    # that is not here.
    #
    # Not `_BLOCK_PAIR_EVENTS`, deliberately: under that set "that creature"
    # names the *other* half of the pair, and `binds_block_pair` additionally
    # requires the printed narrowing that makes a bare firing name one creature.
    # A bare "becomes blocked" has several blockers and one attacker, so the
    # attacker is exactly the referent a bare firing can answer for.
    "matching_creature_becomes_blocked",
    # "Whenever a creature becomes the target of a spell or ability, **return
    # that creature** to its owner's hand." (Cowardice.) CR 603.2's event, whose
    # one announcement seam (`mixins/helpers._announce_targeting`) freezes the
    # targeted permanent's id — the object the words name, and the only one this
    # event has: the ability's source is a third party watching the whole board.
    #
    # Safe for the three narrower scopes of the same kind as well: under
    # "**this** creature becomes the target" the frozen id is the source's own,
    # which is what "that creature" would mean there too.
    "self_becomes_target",
})


#: Trigger conditions whose fire site freezes the **name** of the object the
#: event was about (``event_subject_name``), so "with the same name as that
#: creature" / "with that name" names a string the handler can compare against.
#:
#: A narrower claim than :data:`_EVENT_SUBJECT_OBJECTS` above rather than a
#: reading of it: every kind there freezes an *id*, and only these freeze the
#: name beside it. Gated on that set, "that name" under a tap or a damage event
#: compiled clean and then found no name to compare against at resolution — a
#: card reporting supported for a sentence that could never do anything.
#:
#: Membership is a claim about a stamp: the entry seam
#: (`_put_permanent_onto_battlefield`) for Eye of Singularity, and the one
#: transition off the battlefield (`remove_all_from_battlefield`) for Dual
#: Nature, which freezes it while the creature is still there (CR 603.10a) —
#: by resolution it is a card in another zone and CR 400.7 has made it a new
#: object, but the sentence still names the name it had.
EVENT_SUBJECT_NAMES: frozenset[str] = frozenset({
    "matching_permanent_enters",
    "matching_permanent_leaves_battlefield",
})


#: Trigger events whose fire site stamps the object the event was about onto the
#: **stack item** (``target_permanent_id``), so an effect may say "that <noun>"
#: or "the other <noun>" and mean it — and the ordinary targeted handler
#: resolves it with no picker, because the choice was never offered
#: (CR 603.3d).
#:
#: Here rather than in one family, because two now ask it: ``destruction``
#: (Hooded Blightfang's "destroy that planeswalker", Vampiric Feast's "the
#: other creature") and ``control_changes`` (Charisma's "gain control of the
#: other creature"). A family may not import a sibling, so a leaf two of them
#: read sits on this floor — and one fact spelled in two families is how the
#: two come to disagree about which events really freeze an object.
#:
#: Distinct from :data:`_EVENT_SUBJECT_OBJECTS` one screen up, and the pair is
#: the two ends of one damage event: that one names the **damager**
#: (``event_subject_permanent_id`` in the trigger's context) and this one the
#: object that was **damaged**. Reading one for the other on a creature that
#: traded blows acts on the wrong permanent, with nothing to see.
_EVENT_STAMPED_TARGET_OBJECTS: frozenset[str] = frozenset({
    # Hooded Blightfang: "… deals damage to a planeswalker, destroy **that**
    # planeswalker". The damaged object is what `damage_events._announce`
    # stamps onto the stack item. A damage event whose recipient was a player
    # stamps nothing, and the effect then resolves nothing rather than finding
    # a permanent by index.
    "damage_dealt",
})


# What a bare "that much" names when the effect is a *triggered ability*: the
# quantity the firing event carried, frozen into the trigger's context by the
# fire site. Keyed by trigger-condition kind, and deliberately a table rather
# than a rule — an event either carries a number or it does not, and a kind
# absent here refuses the back-reference instead of reading a zero out of an
# empty context.
_EVENT_QUANTITIES: dict[str, str] = {
    "you_gain_life": "life_gained",
    # The mirror, from the state-based sweep that announces it: "for each 1
    # life you lost" (Oath of Lim-Dûl) counts the drop the sweep measured, not
    # the amount an effect set out to take — a life loss that a replacement
    # reduced is the smaller number, exactly as the gain above is.
    "you_lose_life": "life_lost",
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
    # "Whenever that creature deals combat damage this turn, … you gain life
    # equal to **that damage**." (Vigorous Charge.) The same seam's other
    # delayed announcement, which has frozen the same number under the same
    # key since Acidic Dagger — nothing read it until a card asked how much.
    "bound_permanent_deals_combat_damage": "damage_dealt",
}


def trigger_quantity_key(event: str | None) -> str | None:
    """The trigger context key *event* freezes its number under, or None.

    The read side of :data:`_EVENT_QUANTITIES`, for callers outside this module
    that have a bare "that much"/"that many" and an effect family of their own
    to emit into. They were reaching for the scratchpad instead — which is the
    exact failure the table's own comment describes ("reading a trigger's
    number out of the scratchpad silently yields zero") and which two shipped
    cards were living: Light of Promise put zero +1/+1 counters on the creature
    it enchants, and Living Artifact's whole first line put zero vitality
    counters.
    """
    return _EVENT_QUANTITIES.get(event or "")


#: The **toughness** twin of the table above, keyed by trigger kind the same way.
#:
#: A second table rather than more rows in that one, and ``amounts.py`` already
#: wrote down why: every row of ``_EVENT_QUANTITIES`` names a *power*, so a
#: toughness read through it would silently be handed one. Two characteristics
#: of one object are two numbers, and a reader given the wrong one is wrong on
#: every card whose P and T differ — which is most of them.
#:
#: Membership is a claim about a fire site, exactly as it is next door: the
#: entry transition (``_put_permanent_onto_battlefield``) freezes
#: ``entering_toughness`` beside the power it already froze, on every entry,
#: because the cost is one integer and the alternative is a fire site that has
#: to know which cards care.
_EVENT_TOUGHNESS_QUANTITIES: dict[str, str] = {
    # "Whenever a creature you control enters, you gain life equal to **its
    # toughness**." (Angelic Chorus.)
    "matching_permanent_enters": "entering_toughness",
}


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
        # "That creature's power" names the *event's* object, so under a trigger
        # the only place it can be read is the firing event's captured context —
        # and only under an event whose fire site records one.
        key = _EVENT_QUANTITIES.get(event or "")
        if key is not None:
            return {"amount_from_trigger": key}
        # "…this Aura deals damage equal to **that creature's power** to that
        # player…" (Unnatural Hunger.) Under a trigger printed about the
        # attached permanent (:data:`ATTACHED_SUBJECT_EVENTS`) the words name
        # that permanent — and it is *on the battlefield* when the ability
        # resolves, so the number is a live read rather than something a fire
        # site had to freeze. CR 613 makes power computed, so a creature pumped
        # between the trigger and its resolution deals the number it has then,
        # which is what CR 608.2 asks for.
        #
        # It travels the ordinary ``x_from_count`` channel every computed amount
        # in this engine travels rather than a channel of its own, so
        # ``_execute_oracle_instruction`` resolves it once and every effect
        # family that already reads an X gets this for free.
        if event in ATTACHED_SUBJECT_EVENTS:
            return {
                "amount": "x",
                "x_from_count": {
                    "object_characteristic": {
                        "characteristic": "power", "object": "attached",
                    },
                },
            }
        # "Destroy target nonartifact attacking creature. … Its power is equal
        # to **that creature's power**." (Broken Visage.) With no trigger at all
        # there is no event for the words to be about, and the creature the
        # sentence names is the one an earlier step of this same effect acted on
        # — which is the reading "that creature's mana value" already takes one
        # characteristic over. Gated on the record existing, so a spell with no
        # such step still refuses by name rather than reading a zero: by the
        # time the token is built the creature is a card in a graveyard with no
        # characteristics at all (CR 613.1), so the number has to have been
        # frozen when it left (CR 608.2h).
        if _EVENT_SUBJECT_POWER_RECORD in produced:
            return {"amount_from": _EVENT_SUBJECT_POWER_RECORD}
        raise LoweringError(
            "\"that creature's power\" needs a trigger whose event records "
            "one, or a step of this effect that recorded one",
            node=amount,
        )
    if amount.source is not None:
        # The words named the producer ("equal to the damage dealt"), so a step
        # of this same effect has to have recorded it.
        if amount.source in produced:
            return {"amount_from": amount.source}
        # …or recorded it about a **spell**, under the key the spell's own
        # handler writes. See ``_SPELL_POSSESSIVE_RECORDS``.
        alias = _SPELL_POSSESSIVE_RECORDS.get(amount.source)
        if alias is not None and alias in produced:
            return {"amount_from": alias}
        # "…**its controller** loses life equal to **its power** and you gain
        # life equal to **its toughness**." (Death Watch.) "It" is the dead
        # permanent, so no step of this effect produced the number — the fire
        # site froze it. Read here, where a back-reference's home is already
        # decided, so the two halves of one sentence cannot answer differently.
        record = DEAD_CHARACTERISTIC_RECORDS.get(amount.source)
        if record is not None and event in DEAD_CHARACTERISTIC_EVENTS:
            return {"amount_from_trigger": record}
        # "Whenever a creature you control enters, you gain life equal to **its
        # toughness**." (Angelic Chorus.) The same phrase under an event that is
        # not a death: no step of this effect produced the number and no
        # graveyard holds it, so it is the entry's own frozen toughness — read
        # off its own table for the reason that table exists, one screen up.
        if amount.source == _EVENT_SUBJECT_TOUGHNESS_RECORD:
            toughness = _EVENT_TOUGHNESS_QUANTITIES.get(event or "")
            if toughness is not None:
                return {"amount_from_trigger": toughness}
        raise LoweringError(
            f"back-reference to {amount.source!r} with no producer in this effect",
            node=amount,
        )
    # A step of **this** effect that produced a number is read before the
    # trigger's own, because it is the nearer antecedent: "that player discards
    # all the cards in their hand, then draws **that many** cards" (Shocker) is
    # one sentence about the discard, under a trigger whose event also carries a
    # number (the damage dealt). Read the other way round, Shocker draws cards
    # equal to its power — a card that plays, compiles and is wrong, with
    # nothing in this repo able to see it.
    #
    # Only when the effect produced **exactly one**: two candidate numbers is a
    # sentence with two readings, and picking one of them is the guess this
    # whole function exists to refuse.
    within = tuple(sorted(produced & _PRODUCED_QUANTITIES))
    if len(within) == 1:
        return {"amount_from": within[0]}
    key = _EVENT_QUANTITIES.get(event or "")
    if key is not None:
        return {"amount_from_trigger": key}
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
    # The **delayed** spelling of the first row (Goblin Flotilla), announced by
    # the same two fire sites with the same `blocked_permanent_ids` key — so
    # "that creature" under it is the same question with the same answer, and a
    # set that left it out would refuse the created ability while admitting the
    # printed one.
    "source_blocks_or_blocked_by",
})


#: For each printed combat role, the events under which that role names the
#: **partner** — the other half of the pair the firing is about, which
#: ``handlers/_common.block_pair_permanents`` resolves.
#:
#: The mirror of ``rebinding._ROLE_EVENT_SUBJECTS``, which says when a role names
#: the event's *own* subject; between them they are the two objects a block event
#: has, and an event appears in at most one of the two per role. "Whenever a
#: creature becomes blocked by …" is announced about the attacker, so under it
#: "the blocking creature" is the partner; "whenever a creature blocks …" is
#: announced about the blocker, so under it "the attacking creature" is.
#:
#: Only the board-wide kinds are here. Under the source-scoped ones the partner
#: is still what ``block_pair_permanents`` returns, but the *combatant* is the
#: ability's own source and the pool spells the partner "that creature" — the
#: reading the four lowerings gated on :func:`binds_block_pair` already have. A
#: role word admitted there as well would be a second spelling of one referent.
ROLE_NAMES_BLOCK_PARTNER: dict[str, frozenset[str]] = {
    "blocking": frozenset({"matching_creature_becomes_blocked"}),
    "attacking": frozenset({"matching_creature_blocks"}),
}


#: The other half of the table above: for each printed combat role, the events
#: whose **own subject** plays it — the creature the firing is *about*, frozen
#: by the fire site under ``event_subject_permanent_id``.
#:
#: The exact mirror of :data:`ROLE_NAMES_BLOCK_PARTNER`, and an event appears in
#: at most one of the two per role, which is the invariant that makes a role word
#: answerable at all: "the blocking creature" is the announcement's subject under
#: a *blocks* event and its partner under a *becomes blocked* one, and a lowering
#: that read the wrong table would pump, destroy or shrink the other half of the
#: combat with nothing failing.
#:
#: The lowering-side half of ``rebinding._ROLE_EVENT_SUBJECTS``, which says the
#: same thing for the *source-scoped* kinds and rewrites the role away at parse
#: time. It cannot reach these: a board-wide condition's subject is a noun phrase
#: describing a **set**, so there is nothing for the rewrite to bind the word to
#: and the role survives into lowering — which is why the answer has to exist
#: here as well as there.
#:
#: Both rows are a claim about a stamp. ``matching_creature_attacks`` is stamped
#: by ``declare_attackers_step._fire_matching_creature_attacks_triggers`` and
#: ``matching_creature_blocks`` by both of the declare-blockers announcements
#: (``_fire_board_wide_block_triggers`` for CR 509.3d's narrowed reading and
#: ``_announce_bare_board_wide_blocks`` for CR 509.3c's bare one); a row added
#: without one is a role word naming nobody.
ROLE_NAMES_EVENT_SUBJECT: dict[str, frozenset[str]] = {
    "blocking": frozenset({"matching_creature_blocks"}),
    "attacking": frozenset({"matching_creature_attacks"}),
}


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
ATTACHED_SUBJECT_EVENTS: frozenset[str] = frozenset({
    "upkeep_enchanted_controller",
    # "At the beginning of the end step of enchanted creature's controller,
    # destroy **that creature** …" (Aggression). The same printed shape one
    # step later, and the same referent — which is why the parse side reads
    # both through one production.
    "end_step_enchanted_controller",
})


def names_attached_permanent(
    subject, event: str | None, event_subject=None
) -> bool:
    """Whether *subject* names the permanent the ability's source is attached to.

    One reader for both spellings — "it"/"enchanted <noun>", which the noun
    parser already marks, and the repeated "that <noun>" above — so a lowering
    that learns one gets the other and the two cannot come to disagree about
    which permanent an Aura's sentence is talking about.

    *event_subject* is the firing trigger's own printed subject, and it answers
    the case the event set above cannot. :data:`ATTACHED_SUBJECT_EVENTS` holds
    the conditions that are *only ever* printed about an attached permanent, so
    the kind alone settles them; "becomes the target of a spell or ability" is
    not one — the same kind is printed about "this creature" (Warden of the
    Woods) and about "enchanted creature" (Spinal Graft), and adding it to that
    set would make the Warden's "that creature" name a permanent it is not
    attached to. The condition's own subject is what tells the two apart, and
    it is already threaded through every lowering that could need it.

    The noun must be the one the condition named, for the reason the "that"
    test above is bare: "that creature" is a back-reference and "that creature
    you control" is a phrase that chose for itself.
    """
    from ._common import _is_enchanted

    if _is_enchanted(subject):
        return True
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
    ):
        return False
    if event in ATTACHED_SUBJECT_EVENTS:
        return True
    return (
        getattr(event_subject, "is_enchanted", False)
        and tuple(getattr(event_subject, "card_types", ())) == subject.filter.card_types
        and not set(subject.filter.to_payload()) - {"type_filter"}
    )


def chooser_payload(statement, event: str | None, what: str) -> dict[str, object]:
    """Who names the value a "choose a <thing>" sentence produces.

    Here rather than in the dispatcher that calls it, and that is the point of
    the move: the answer is a fact about the **event** — which seat, if any, the
    firing froze — and this module is where that fact already lives
    (``_EVENT_SUBJECT_PLAYERS``, ``EVENT_SUBJECT_PLAYER``). A dispatcher arm
    re-deriving it was the dispatch layer holding a second copy of an events
    fact, and the two would drift the first time a trigger kind joined that set.

    Shared by the colour choice (Chromatic Armor, Hall of Gemstone) and the card
    type (Teferi's Realm), because the question is the same one and the two arms
    were the same twenty lines with a noun changed. *what* is that noun, for the
    refusal message.

    Empty is CR 601.2b's default — the ability's controller, which the handler
    reads off the source — and is the payload every printing before Hall of
    Gemstone produced, so nothing already compiled moves.

    "That player" is the seat the firing event froze (CR 603.10), and it refuses
    under an event that froze none: the prompt would otherwise go to whoever the
    resolution happened to be holding, which is the refusal every other reading
    of those two words in this package makes.
    """
    chooser = statement.chooser
    if chooser is None:
        return {}
    if chooser.kind != "that_player":
        raise LoweringError(
            f"no {what} choice is made by {chooser.kind!r}", node=statement
        )
    if event not in _EVENT_SUBJECT_PLAYERS:
        raise LoweringError(
            f"no event named {event!r} freezes the seat \"that player\" names",
            node=statement,
        )
    return {"chooser": EVENT_SUBJECT_PLAYER}


#: What ``handlers/stack.exile_target_spell`` writes to the resolution
#: scratchpad: the :class:`~engine.exiled_records.ExiledRecord` for the spell it
#: moved to exile, and the seat that spell's controller was. Imported from
#: ``engine/exiled_records.py`` rather than spelled again, because that module
#: is where the *reader* lives and it imports nothing from the engine — so the
#: handler layer and this package can both name the key without either importing
#: the other, which is the second-copy failure every key here exists to avoid.
EXILED_SPELL_RECORD = EXILE_RECORD_KEY


EXILED_SPELL_CONTROLLER = EXILED_SPELL_CONTROLLER_KEY
