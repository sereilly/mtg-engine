"""Which delayed-trigger event a printed opener names (CR 603.7).

Split out of ``delayed`` at Tempest's Phase 0 caps step, along the line that
module's own docstring already draws:

    "…these read one that arranges for something later, and the arrangement is
    what the parse has to get right — **which event, and what the later
    sentence is allowed to refer back to.**"

Two subjects in one sentence, and this file is the first of them. Everything
here answers "which event do these printed words name" and hands back a *row* —
``(event, once, duration, binds)``, plus the object the opener watches or
chooses where it names one. Nothing here builds a node, reads the sentence
behind the comma, or knows what a delayed ability's effect may refer to; that is
all ``delayed``, which asks these and is never imported back.

**It is the half that grows with the pool**, which is the playbook's tiebreak.
``_DELAYED_OPENERS`` has taken a row per printed wording set after set and the
productions below one per new shape, while what stays in ``delayed`` is a walk
over the dataclass fields, written so a node added later is covered by default
rather than by remembering the function.

**The seam is not the one between the two word orders**, which is where the
module's shape invites the cut: a delay printed in front of its effect and one
printed behind it are the *same* rows, so ``parse_trailing_delay`` reads the
very table and the very sub-production ``_parse_create_delayed_trigger`` reads.
Cutting there would put the table on one side and one of its two readers on the
other, and buy no room at all. Both spellings live here together, and what they
have in common — the table — lives here with them.
"""

from __future__ import annotations

from . import ast
from .errors import GrammarError
from .lexer import SELF
from .nouns import parse_object_filter
from .phrases import parse_bound_subject, parse_subject_filter_at
from .readers import accept_source_reference
from .references import parse_target_spec
from .stream import TokenStream
from .vocabulary import CARD_TYPES



# Which printed opener names which delayed-trigger event, and what the two
# words CR 603.7 turns into fields say:
#
#   ``once``        CR 603.7b — "when" triggers once, "whenever" keeps
#                   triggering for as long as the ability lasts.
#   ``duration``    how long an ability that never triggers survives. "This
#                   turn" expires with the turn; an ability naming a future
#                   step waits for that step however many turns away it is.
#   ``binds``       whether the opener is about "**that** <noun>" — the object
#                   the creating spell targeted (CR 603.7c).
#
# A table rather than a production each, because the difference between these
# rows is four values and no structure at all. The event names are keys of
# ``engine/delayed_triggers.DELAYED_EVENTS``; one that is not is refused when
# the sentence is lowered, so a new row cannot arm an ability nothing announces.
_DELAYED_OPENERS: tuple[tuple[tuple[str, ...], str, bool, str, bool], ...] = (
    # "At the beginning of your next main phase, …" (Mana Drain). Either main
    # phase of the controller's — whichever one comes next.
    (("at", "the", "beginning", "of", "your", "next", "main", "phase"),
     "controllers_next_main_phase", True, "until_it_triggers", False),
    # "At this turn's next end of combat, …" (Glyph of Doom).
    (("at", "this", "turn", "'s", "next", "end", "of", "combat"),
     "next_end_of_combat", True, "end_of_turn", True),
    # The same delay printed short — "…, at end of combat, sacrifice it and it
    # deals 5 damage to you" (Time Elemental). CR 511.1 gives a combat phase one
    # end-of-combat step, so "at end of combat" inside a sentence that is being
    # performed *during* combat names the same moment the longer spelling does;
    # it is one event with two printed wordings, not two events.
    (("at", "end", "of", "combat"),
     "next_end_of_combat", True, "end_of_turn", True),
    # "At the beginning of **the next end step**, …" (Infinite Authority).
    # Nobody's in particular: CR 513.1 gives every turn one end step, and the
    # next one there is belongs to whoever's turn it happens to be. So the fire
    # site announces it unseated, and the entry waits for the step rather than
    # expiring with the turn — an ability created during the end step itself
    # would otherwise be swept away before the step it names arrives.
    #
    # It **may** bind, as `next_end_of_combat` beside it does and for the same
    # reason: a step names no object itself, so whether one was chosen is a fact
    # about the sentence behind it (Goblin Kites' "sacrifice **that creature**"
    # against Rukh Egg's token, which names nothing). The column is a permission
    # and `delayed.delay_binds_an_object` is the answer.
    (("at", "the", "beginning", "of", "the", "next", "end", "step"),
     "next_end_step", True, "until_it_triggers", True),
    # "…At the beginning of **that turn's** end step, you lose the game."
    # (Final Fortune.) Read above the two rows below it because "that turn"
    # is neither of the referents they name: those wait for an end step that
    # already has a turn, and this one names the turn the sentence in front of
    # it just queued (CR 500.7). Binds nothing — a step is not an object — and
    # the lowering refuses the words with no extra-turn grant in front of them,
    # because "that turn" with no producer names nothing at all.
    (("at", "the", "beginning", "of", "that", "turn", "'s", "end", "step"),
     "granted_extra_turns_end_step", True, "until_it_triggers", False),
    # "At the beginning of **your** next end step, …" (Necropotence). Not the
    # row above: that one is the next end step there is, whoever's turn it falls
    # in, and this one waits for one of the controller's own. On an opponent's
    # turn those are a turn apart, and a card exiled back a turn late is the
    # wrong card — the same distinction the two upkeep rows draw.
    (("at", "the", "beginning", "of", "your", "next", "end", "step"),
     "controllers_next_end_step", True, "until_it_triggers", False),
    # "At the beginning of your next upkeep, …" (Giant Slug, Hazezon Tamar).
    # The controller's own upkeep, however many turns away — so it waits for
    # the step rather than expiring with the turn.
    (("at", "the", "beginning", "of", "your", "next", "upkeep"),
     "controllers_next_upkeep", True, "until_it_triggers", False),
    # "…at the beginning of **each of your draw steps**, put a -1/-1 counter on
    # that creature." (Giant Oyster.) The repeating row: "each of" is CR 603.7b's
    # stated-duration half of the rule, so the ability fires at every one of its
    # controller's draw steps rather than at the next one — which is why `once`
    # is False here where every row around it is True.
    #
    # Its duration is **unstated**, the shape `land_tapped_for_mana` below
    # already has: the window is printed once in front of the whole sentence
    # ("for as long as this creature remains tapped") and shared with the untap
    # restriction beside it, so the opener leaves it None and the leading linked
    # duration fills it in. A node that reaches the lowering still None refuses,
    # because a repeating ability with no window is one nothing ever lifts.
    (("at", "the", "beginning", "of", "each", "of", "your", "draw", "steps"),
     "controllers_draw_step", False, None, True),
    # "…at the beginning of **the next turn's** upkeep" (Ice Age's cantrip
    # cycle). Whichever upkeep comes next rather than the controller's own —
    # see `delayed_triggers.DELAYED_EVENTS` for why that is a separate event
    # and not a second spelling of the row above.
    (("at", "the", "beginning", "of", "the", "next", "turn", "'s", "upkeep"),
     "next_turns_upkeep", True, "until_it_triggers", False),
    # "…at the beginning of **their** next upkeep" (Sabertooth Cobra). The
    # third upkeep row and the third seat: not the controller's own and not
    # whichever comes next, but the one belonging to the player the firing
    # event was about. See `delayed_triggers.DELAYED_EVENTS` for why the
    # possessive makes it a separate event rather than a spelling of either.
    (("at", "the", "beginning", "of", "their", "next", "upkeep"),
     "damaged_players_next_upkeep", True, "until_it_triggers", False),
    # "…at the beginning of **each of that player's upkeeps**" (Ertai's
    # Meddling). The repeating spelling of the row above — "each of" is
    # CR 603.7b's stated-duration half exactly as it is in the draw-step row,
    # so `once` is False — and the possessive names the same kind of seat: one
    # the creating effect recorded.
    #
    # Its duration is `while_the_game_lasts`, the one row that carries it: the
    # card prints no window at all, and the sentence's own intervening-if is
    # what stops it (see `delayed_triggers.WHILE_THE_GAME_LASTS`). Read *above*
    # the "their next upkeep" row would make no difference — the two differ from
    # the fifth word on — and it is placed below it so the three one-shot upkeep
    # rows stay together.
    (("at", "the", "beginning", "of", "each", "of", "that", "player", "'s",
      "upkeeps"),
     "bound_players_upkeep", False, "while_the_game_lasts", False),
    # "…at the beginning of **the next cleanup step**" (Thawing Glaciers,
    # Bounty of the Hunt). Unseated for `next_end_step`'s reason — CR 514 gives
    # every turn one cleanup step and the ability names the next one there is —
    # and it waits for that step rather than expiring with the turn, because the
    # step it names comes *after* the sweep that would expire it (CR 514.2 then
    # CR 514.3a).
    #
    # It **may** bind, exactly as the end-step row above may: the step names no
    # object, so whether one was chosen is a fact about the sentence behind it.
    # Thawing Glaciers' "return **this land**" names its own source and binds
    # nothing; Bounty of the Hunt's "remove a +1/+1 counter from **that
    # creature**" names the creature the spell chose.
    # `delayed.delay_binds_an_object` is the answer, and the column only the
    # permission.
    (("at", "the", "beginning", "of", "the", "next", "cleanup", "step"),
     "next_cleanup_step", True, "until_it_triggers", True),
)


#: The two objects a ``when <X> leaves the battlefield`` opener can name, and
#: what each one is called in the payload. Neither is a chosen target: the card
#: naming itself is the lexer's SELF token, and "that token" is the token an
#: earlier sentence of the same effect created — so both are objects the effect
#: already holds, and the delayed machinery is handed the id rather than a
#: target to resolve.
#:
#: A table because the difference between the two rows is one printed phrase.
#: Adding a third means adding the phrase and the id the arming handler reads
#: it back from; there is no branch to widen.
_WATCHED_OBJECTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("that", "token"), "created_token"),
)

#: The card types a permanent uses to name **itself** mid-sentence. The same set
#: `triggers.py` reads after "this", spelled here rather than imported because
#: the two front ends of one printed phrase are exactly the pair this codebase
#: keeps finding drifted — and a word missing from one of them is a card whose
#: delay opener refuses while its trigger condition reads.
_SELF_TYPE_WORDS: tuple[str, ...] = (
    "creature", "artifact", "enchantment", "land", "aura", "permanent",
)


def _parse_watched_object(stream: TokenStream) -> str | None:
    """Which object a ``leaves the battlefield`` delay watches, or None."""
    for phrase, name in _WATCHED_OBJECTS:
        mark = stream.mark()
        if stream.accept_phrase(*phrase):
            return name
        stream.reset(mark)
    # The card naming itself, which the lexer has already collapsed into one
    # SELF token — the same referent `references.parse_recipient` reads, so a
    # card that spells its own name and a card that says "this creature" name
    # the same object to the delayed machinery.
    mark = stream.mark()
    if stream.accept_kind(SELF) is not None:
        return "source"
    # "…when **this artifact** leaves the battlefield this turn" (War Barge).
    # The modern templating of the same self-reference, and the type word is
    # read against the same closed set the trigger parser reads it against:
    # "this artifact" on an artifact and "this creature" on a creature are one
    # referent printed two ways, not two objects.
    if stream.accept_word("this") and stream.accept_word(*_SELF_TYPE_WORDS):
        return "source"
    stream.reset(mark)
    return None


def parse_untap_or_control_delay(
    stream: TokenStream,
) -> tuple[str, bool, str, bool, str] | None:
    """``when <object> becomes untapped or you lose control of <object>`` —
    the delay Coffin Queen prints in front of its effect.

    CR 603.7 with **two** events and one ability, exactly as Merieke Ri Berit's
    "leaves the battlefield or becomes untapped" is one key announced from two
    sites: the ability fires the first time *either* happens and, having no
    stated duration, is done (CR 603.7b). Two entries would each be one-shot on
    their own and the second would still be waiting.

    A separate event from that one and not a wider spelling of it. Losing
    control of a permanent and it leaving the battlefield are different things
    — CR 603.10d's half is a change of hands, with the permanent still there —
    and an ability armed under one name must not be woken by the other's.
    (A permanent that *leaves* is also its controller losing control of it,
    which is why this event's fire sites include the leave transition; that is
    a fact about the sites, not about the key.)

    **Both halves must name the same object.** "When this creature becomes
    untapped or you lose control of *that* creature" is not a sentence Magic
    prints, and reading the two references separately would arm an ability
    watching one permanent and answering for another.

    Returns the ``(event, once, duration, binds, watches)`` shape
    :func:`parse_leaves_battlefield_delay` returns, so the one caller builds one
    node.
    """
    mark = stream.mark()
    if not stream.accept_word("when"):
        stream.reset(mark)
        return None
    watched = _parse_watched_object(stream)
    if watched is None or not stream.accept_phrase("becomes", "untapped"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("or", "you", "lose", "control", "of"):
        stream.reset(mark)
        return None
    if _parse_watched_object(stream) != watched:
        stream.reset(mark)
        return None
    # `binds` stays False here, exactly as it does in the sibling below: the
    # effect is printed *behind* the delay and names an object the ability
    # already holds — the creature its own reanimation put onto the battlefield
    # — so the permission is granted by the caller, which reads the effect.
    return ("bound_permanent_untaps_or_control_lost", True, "until_it_triggers", False, watched)


def parse_leaves_battlefield_delay(stream: TokenStream) -> tuple[str, bool, str, bool, str] | None:
    """``when <object> leaves the battlefield`` — the trailing delay whose
    opener names the object it watches (CR 603.6c, CR 603.7).

    Stangg prints both directions of it in one line: "Exile that token **when
    Stangg leaves the battlefield**. Sacrifice Stangg **when that token leaves
    the battlefield**." Which object is watched and which is acted on swap
    between the two sentences, which is exactly why the watched one is read
    here and the acted-on one is left to the sentence in front of it.

    Returns the ``(event, once, duration, binds, watches)`` shape
    :func:`parse_trailing_delay` returns, so the one caller builds one node.
    """
    mark = stream.mark()
    if not stream.accept_word("when"):
        stream.reset(mark)
        return None
    watched = _parse_watched_object(stream)
    if watched is None or not stream.accept_phrase("leaves", "the", "battlefield"):
        stream.reset(mark)
        return None
    # "…leaves the battlefield **or becomes untapped**" (Merieke Ri Berit,
    # Tawnos's Coffin). One ability answering to either event, so it is one
    # event key announced from two sites rather than two entries — see
    # ``delayed_triggers.DELAYED_EVENTS``. Read here, in the opener that already
    # says which object is watched, because the second half is about the same
    # object as the first.
    event = "bound_permanent_leaves_battlefield"
    if stream.accept_phrase("or", "becomes", "untapped"):
        event = "bound_permanent_leaves_or_untaps"
    # "When" is CR 603.7b's one-shot, and the object it watches leaves the
    # battlefield exactly once — a returning permanent is a new object with a
    # new id (CR 400.7), so there is nothing for a second firing to be about.
    # It waits however many turns that takes, so it does not expire with the
    # turn; only firing removes it — unless the card prints the other half of
    # CR 603.7b, a **stated duration**: War Barge's "…leaves the battlefield
    # **this turn**" is an ability that stops waiting when the turn ends, and
    # dropping the two words would make the boat's target answerable to a
    # destruction three turns later.
    duration = "end_of_turn" if stream.accept_phrase("this", "turn") else "until_it_triggers"
    # `binds` stays False in **this** word order. Stangg prints the effect in
    # front of the delay and both of its sentences act on an object the effect
    # already holds — the source, and the token it just made. Granting the
    # permission here would hand "exile that token" to
    # ``delayed.delay_binds_an_object``, which reads a ``that`` quantifier and
    # would send the arming handler off to resolve a target the card never
    # chose, arming nothing at all. The leading spelling in
    # :func:`delayed._parse_create_delayed_trigger` is where an acted-on target
    # is possible, and it grants the permission itself.
    return (event, True, duration, False, watched)


def parse_trailing_delay(stream: TokenStream) -> tuple[str, bool, str, bool, str | None] | None:
    """The **trailing** spelling of a delay: ``<effect> at the beginning of your
    next upkeep``.

    Hazezon Tamar prints its delay after the effect rather than in front of it —
    "create X … tokens that are red, green, and white **at the beginning of your
    next upkeep**, where X is …". Same delay, same table, other word order, so
    it reads the same rows :data:`_DELAYED_OPENERS` already holds; a second list
    would be a second answer to "which delays does this engine arm".

    Returns the row's ``(event, once, duration, binds)`` or None. The caller
    builds the node, because the effect it wraps is the sentence the caller
    already has in hand — and because the clause that defines the sentence's X
    belongs *inside* the delay (see ``statements.parse_statement``).
    """
    # "You gain control of that creature **if it regenerates this way**."
    # (Debt of Loyalty.) The trailing spelling of the `when it regenerates
    # this way` opener above, printed as an "if" — one delay, one event, and
    # the same row it would reach from the other word order.
    #
    # **Not a condition on this resolution.** The shield is spent the next
    # time the creature would be destroyed, which is later than the spell
    # that made it (CR 701.19c: creating a shield is not regenerating), so a
    # reading that asked the question now would answer no on every board and
    # the control change would never happen.
    #
    # ``binds`` is True where the opener's row watches the **source**: this
    # is a spell, so the creature that regenerates is the one it targeted,
    # and CR 603.7d's own-source default would watch a sorcery in a
    # graveyard. Left as ``watches=None``, the entry watches the object it
    # is about, which is that same creature.
    regen = stream.mark()
    if stream.accept_phrase("if", "it", "regenerates", "this", "way"):
        return "source_regenerates", True, "end_of_turn", True, None
    stream.reset(regen)
    for phrase, kind, once, duration, binds in _DELAYED_OPENERS:
        mark = stream.mark()
        if stream.accept_phrase(*phrase):
            return kind, once, duration, binds, None
        stream.reset(mark)
    return parse_leaves_battlefield_delay(stream)


def _delayed_bound_subject(stream: TokenStream) -> "ast.ObjectFilter | None":
    """``that creature`` — the noun phrase naming the object an earlier
    sentence of the same spell chose, as a filter.

    :func:`phrases.parse_bound_subject` is the one reader of the phrase; this
    only asks for the singular half of it and hands back the filter. "Those
    creatures" is a *list* the delayed-trigger machinery has no shape for —
    one entry binds one permanent id — so it is refused rather than silently
    bound to whichever one the reader returned first.

    The phrase is read rather than skipped, and travels as the delayed
    ability's own subject filter, for the reason
    ``delayed_destroy_blocked_or_blocker`` states about "destroy that
    **Wall**": the id already names the object exactly, so the noun re-states
    rather than narrows — but a word consumed and never read is a word that
    could be deleted with no change to what the card does, and this engine
    does not leave one lying in a payload.
    """
    # "When **the targeted creature** leaves the battlefield this turn, …"
    # (Acidic Dagger.) The definite spelling of the same referent: the ability
    # targeted once (CR 602.2b) and both of its delayed sentences are about that
    # one creature, so the words name what "that creature" names and reach the
    # same binding. Read here rather than taught to `parse_bound_subject`,
    # because "targeted" is a word about *this* ability's announcement and means
    # nothing on a line that chose nobody.
    definite = stream.mark()
    if stream.accept_phrase("the", "targeted"):
        noun = stream.peek_word()
        if noun in CARD_TYPES:
            stream.advance()
            return ast.ObjectFilter(card_types=(noun,))
    stream.reset(definite)
    spec = parse_bound_subject(stream)
    if spec is None or spec.quantifier != "that":
        return None
    return spec.filter


def _parse_land_tapped_for_mana(stream: TokenStream) -> "ast.ObjectFilter | None":
    """``a player taps <land phrase> for mana`` — the land phrase, or None.

    The active-voice spelling of the event ``trigger_tables`` already reads in
    the passive ("whenever a Mountain **is tapped** for mana"), and the same
    event: CR 106.11's mana production, announced by the tap seam. Read here
    rather than there because a delayed ability is created by a resolving
    effect, so the sentence sits inside a statement rather than opening a line.

    Refuses without consuming anything it can put back — the caller marks — so
    every other "whenever …" opener keeps its reading. The noun phrase travels
    as the ability's subject filter and is tested by the fire site, which is
    what makes "a Mountain" payload rather than a second event.
    """
    if not stream.accept_phrase("a", "player", "taps"):
        return None
    # The indefinite article is the noun parser's caller's business everywhere
    # in this grammar: `parse_object_filter` reads the phrase from the noun on.
    stream.accept_word("a", "an")
    try:
        land = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.accept_phrase("for", "mana"):
        return None
    # A land, and the parser says so rather than the fire site: the seam only
    # ever announces a land being tapped, so a phrase describing anything else
    # would arm an ability that can never fire — and "land" is how the card says
    # which objects it is about ("a **Mountain**" is a land type, CR 305.6).
    if land.card_types not in ((), ("land",)) or (
        not land.subtypes and land.card_types != ("land",)
    ):
        return None
    return land


#: The combat events a ``this turn, when target <noun> …`` opener can name, by
#: the words printed after the target phrase. Two rows would be two spellings of
#: one shape, so the phrase is the key and the event is the value — a card
#: printing "attacks" alone is a row, not a production.
#:
#: The keys are of ``engine/delayed_triggers.DELAYED_EVENTS``; one that is not
#: refuses when the sentence is lowered, so a row added here cannot arm an
#: ability nothing announces.
_TARGETED_COMBAT_DELAYS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("attacks", "and", "isn't", "blocked"), "creature_attacks_unblocked"),
)


def _parse_targeted_combat_delay(
    stream: TokenStream,
) -> "tuple[str, ast.TargetSpec] | None":
    """``when target <noun> attacks and isn't blocked`` — the opener that
    **chooses** the creature it watches (Delif's Cone, Delif's Cube).

    The other openers here name an object the effect already holds: its own
    source, a token it made, or the target an *earlier sentence* chose. This one
    names the target itself, so CR 601.2c/602.2b pick it as the ability is
    activated and the spec has to travel out of the parse — otherwise the picker
    has nothing to offer and the arming handler has nothing to bind.

    Refuses with the cursor untouched, so every other "when" opener keeps its
    reading.
    """
    mark = stream.mark()
    try:
        chosen = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if chosen is None or not chosen.targeted or chosen.count != 1:
        # One permanent per entry: ``DelayedTrigger`` binds one id, so a counted
        # phrase would arm an ability about whichever one the reader returned
        # first. Refusing leaves the line's own refusal.
        stream.reset(mark)
        return None
    for phrase, event in _TARGETED_COMBAT_DELAYS:
        after = stream.mark()
        if stream.accept_phrase(*phrase):
            return event, chosen
        stream.reset(after)
    stream.reset(mark)
    return None


#: How long a block-pair delay's printed window lasts (CR 603.7b). "This
#: combat" is the shorter of the two sweeps `engine/delayed_triggers.py` runs;
#: a card printing "this turn" is the same ability over the longer one.
_BLOCK_PAIR_WINDOWS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("this", "combat"), "end_of_combat"),
    (("this", "turn"), "end_of_turn"),
)


def _parse_targeted_damage_delay(
    stream: TokenStream,
) -> "tuple[ast.TargetSpec, ast.ObjectFilter] | None":
    """``target <noun> deals combat damage to <noun> this turn`` — the opener
    that **chooses** the creature whose damage it watches (Acidic Dagger).

    :func:`_parse_targeted_combat_delay`'s twin one event over, and the same
    reason it exists: CR 602.2b picks the target as the ability is activated, so
    the spec has to travel out of the parse or the picker has nothing to offer
    and the arming handler nothing to bind.

    The phrase after "to" is the **agent** — the other end of the event — and is
    read rather than skipped for the reason every narrowing in this grammar is:
    "a **non-Wall** creature" is what keeps the Dagger from destroying the Wall
    that stopped it, and a word consumed and never read is a word that could be
    deleted with no change to what the card does.

    Refuses with the cursor untouched, so every other "whenever" opener keeps
    its reading.
    """
    mark = stream.mark()
    try:
        chosen = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if chosen is None or not chosen.targeted or chosen.count != 1:
        # One permanent per entry, for `_parse_targeted_combat_delay`'s reason:
        # ``DelayedTrigger`` binds one id.
        stream.reset(mark)
        return None
    if not stream.accept_phrase("deals", "combat", "damage", "to"):
        stream.reset(mark)
        return None
    stream.accept_word("a", "an")
    try:
        agent = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if agent is None or not stream.accept_phrase("this", "turn"):
        stream.reset(mark)
        return None
    return chosen, agent


def _parse_source_block_pair_delay(
    stream: TokenStream,
) -> "tuple[ast.ObjectFilter, str] | None":
    """``this creature blocks or becomes blocked by <noun> this combat`` — the
    delayed spelling of the joined block event (Goblin Flotilla).

    The printed static form of the same sentence is a trigger of the permanent
    (``engine/oracle.py``'s ``creature_blocks_or_blocked_by``); this is that
    ability *created* for a window, which is what the trailing "this combat"
    says. Its subject is the source rather than a described class — the delayed
    entry watches one permanent by id — so the noun phrase after "by" narrows
    the **other** half of the pair, exactly as it does on the static form.

    Refuses with the cursor untouched, so every other "whenever …" opener keeps
    its reading.
    """
    mark = stream.mark()
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("blocks", "or", "becomes", "blocked", "by"):
        stream.reset(mark)
        return None
    described = parse_subject_filter_at(stream)
    if described is None:
        stream.reset(mark)
        return None
    for phrase, duration in _BLOCK_PAIR_WINDOWS:
        window = stream.mark()
        if stream.accept_phrase(*phrase):
            return described, duration
        stream.reset(window)
    # A window is required: CR 603.7b's "unless it has a stated duration" is
    # what makes this ability repeat, and one with no window is a static the
    # permanent simply has.
    stream.reset(mark)
    return None
