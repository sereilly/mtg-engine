"""Delayed triggered abilities (CR 603.7), and the opener that binds one.

Split from `statements` at the thousand-line guard, along the section boundary
that module already drew. A delayed trigger is not a statement like the others:
the rest of `statements` reads a sentence that *does* something now, while these
read one that arranges for something later, and the arrangement is what the
parse has to get right — which event, and what the later sentence is allowed to
refer back to.

`Choose target <noun>.` lives here for the same reason. It performs nothing on
its own and parses **only** when the sentence binding what it chose follows; a
spell whose one instruction chose a target and did nothing would otherwise
report itself supported.

**The recursion arrives as a parameter.** A delayed trigger contains a whole
statement, so this file needs `parse_statement`, which is the roof one layer up.
Taking it as an argument keeps the dependency running one way — the inversion
`lowering/where_x.py` and `postmodifiers.py` both make, for the same reason.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .errors import GrammarError
from .conditions import _parse_condition
from .nouns import parse_object_filter
from .phrases import parse_bound_subject, parse_subject_filter_at
from .rebinding import rebind_pronoun_to_delay_target
from .readers import accept_source_reference
from .references import parse_recipient, parse_target_spec
from .lexer import SELF
from .stream import TokenStream

# ---------------------------------------------------------------------------
# Delayed triggered abilities (CR 603.7)
# ---------------------------------------------------------------------------

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
    # and `delay_binds_an_object` is the answer.
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
    # creature**" names the creature the spell chose. `delay_binds_an_object` is
    # the answer, and the column only the permission.
    (("at", "the", "beginning", "of", "the", "next", "cleanup", "step"),
     "next_cleanup_step", True, "until_it_triggers", True),
)


def delay_binds_an_object(may_bind: bool, effect) -> bool:
    """Whether a delay's sentence is actually **about** an object the creating
    spell chose (CR 603.7c).

    The ``binds`` column of :data:`_DELAYED_OPENERS` says a row *may* bind: the
    opener names no object itself, so whether one was chosen is a fact about the
    sentence behind it. Glyph of Doom's "destroy all creatures that were blocked
    by **that creature** this turn" refers back and must resolve the target it
    was given; Time Elemental's "sacrifice it and it deals 5 damage to you" —
    one printed word shorter in its opener and under the very same event —
    refers to nothing but its own source.

    Reading the column alone is what would break that second card, and break it
    in the worst direction: ``create_delayed_trigger`` resolves a target when the
    payload says the ability binds one, finds none, and arms **nothing** while
    the card compiles supported. So the column is a permission and this is the
    answer.

    The question is asked of the AST rather than of a list of cards, and the
    markers are the ones the noun phrase already carries: a ``that <noun>``
    quantifier, or any filter field whose name says it is about a bound object.
    Written against the field *names* rather than a hand-listed set, so a
    narrowing added later — the ``blocked_by_bound_object`` / ``of_bound_type``
    family — is covered the day it is named rather than the day someone
    remembers this function.

    A bound **card** is not one of them. ``create_delayed_trigger`` answers this
    permission by resolving a *permanent* and arming **nothing** when it finds
    none, so a sentence about a card in a graveyard — Seraph's "put **that
    card** onto the battlefield", which reads the dead card out of the frozen
    trigger context instead — would be granted a binding it cannot fill and lose
    its whole ability. So the two card markers are excluded by name, the same
    way the object ones are included by name.
    """
    if not may_bind:
        return False
    return _names_a_bound_object(effect)


def _names_a_bound_object(node) -> bool:
    if isinstance(node, ast.TargetSpec) and node.quantifier in ("that", "other", "first"):
        # "…that **card**" is a card in a hidden or public zone, not a permanent
        # the arming handler could look up by id (CR 400.7: what comes back is a
        # different object). The rest of the walk still runs, so a sentence
        # naming a card *and* a permanent is still a binding.
        if not node.filter.is_card:
            return True
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            if "bound" in field.name and "card" not in field.name and value:
                return True
            if _names_a_bound_object(value):
                return True
        return False
    if isinstance(node, (tuple, list)):
        return any(_names_a_bound_object(item) for item in node)
    return False


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
    # ``delay_binds_an_object``, which reads a ``that`` quantifier and would
    # send the arming handler off to resolve a target the card never chose,
    # arming nothing at all. The leading spelling in
    # :func:`_parse_create_delayed_trigger` is where an acted-on target is
    # possible, and it grants the permission itself.
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


def _parse_create_delayed_trigger(stream: TokenStream, parse_statement) -> "ast.CreateDelayedTrigger | None":
    """A sentence that **creates** a delayed triggered ability (CR 603.7).

    ``When that creature dies this turn, <effect>.`` (Reincarnation)
    ``Whenever that creature is dealt damage by <phrase> this turn, <effect>.``
      (Glyph of Life)
    ``At the beginning of your next main phase, <effect>.`` (Mana Drain)

    The whole sentence, delay included, for the reason
    ``_parse_delayed_self_action`` gives: the effect on its own is performed
    *now*, and a spell that gains the life immediately is a different card from
    one that gains it when a creature is next damaged.

    The inner effect is parsed by the ordinary sentence parser, so a delayed
    ability's effect is every effect this engine has, and one that fails to
    parse refuses the whole line rather than arming an ability that fires into
    nothing.
    """
    mark = stream.mark()
    event: str | None = None
    once = True
    duration = "end_of_turn"
    binds = False
    subject = None
    agent = None
    watches: str | None = None
    target: "ast.TargetSpec | None" = None

    # "**This turn,** when target creature you control attacks and isn't
    # blocked, …" (Delif's Cone, Delif's Cube). CR 603.7b's stated duration
    # printed *in front of* the opener rather than inside it — the same window
    # "…dies this turn" states from the other end of the sentence, so it is read
    # here and the openers behind it keep their own defaults. Consumed only when
    # a delay opener really follows: on any refusal below the mark is restored,
    # so a sentence beginning "this turn" and going on to say something else
    # keeps every other reading it had.
    if stream.accept_phrase("this", "turn") and not stream.accept_punct(","):
        stream.reset(mark)
        return None

    if stream.accept_word("when"):
        # "When **it regenerates this way,** that player may draw a card."
        # (Soldevi Sentry.) A delayed ability (CR 603.7) and not CR 603.12's
        # reflexive one: the regeneration it waits for is the *shield* being
        # spent, which happens the next time the creature would be destroyed —
        # later than this resolution, where a reflexive trigger's event has to
        # have happened during it.
        #
        # "This turn" is not printed and is not needed: CR 701.19a scopes the
        # shield itself to the turn, so an ability waiting on it cannot outlive
        # one either, and `end_of_turn` is the shield's own window rather than
        # an assumption.
        #
        # `watches` is the source, which is what makes "it" mean the permanent
        # whose ability armed this rather than whichever creature regenerates
        # next. It binds no *object* — the sentence behind it names a **player**,
        # which is `binds_player` one layer down.
        #
        # Read first among the "when" openers: the ones below it all start from
        # a bound-object noun phrase, and "it" is not one they read.
        if stream.accept_phrase("it", "regenerates", "this", "way"):
            event, once, duration, watches = (
                "source_regenerates", True, "end_of_turn", "source",
            )
        # "…when **target creature you control** attacks and isn't blocked, …"
        # (Delif's Cone, Delif's Cube). Read before the bound-subject openers
        # below: this one *chooses* its object where those name one the effect
        # already holds, and it declines without consuming.
        targeted = _parse_targeted_combat_delay(stream) if event is None else None
        if targeted is not None:
            event, target = targeted
            binds = True
        # "When that creature dies this turn, …"
        if event is None:
            subject = _delayed_bound_subject(stream)
            if subject is not None and stream.accept_phrase("dies", "this", "turn"):
                event, binds = "bound_permanent_dies", True
            elif subject is not None and stream.accept_phrase(
                "becomes", "blocked", "this", "turn"
            ):
                # "When that creature **becomes blocked** this turn, …"
                # (Barreling Attack.) CR 509.1h's state, watched about the one
                # creature the spell chose rather than about a class — which is
                # what separates it from the printed static "whenever this
                # creature becomes blocked": that one is an ability of the
                # creature, and this one is created by a spell that will be in a
                # graveyard by the time it fires.
                #
                # "This turn" is CR 603.7b's stated duration and the ability is
                # still one-shot: a creature blocked twice in a turn is blocked
                # in two combats, and the card gives its bonus once.
                event, binds = "bound_permanent_becomes_blocked", True
            elif subject is not None and stream.accept_phrase(
                "leaves", "the", "battlefield"
            ):
                # "When that creature leaves the battlefield this turn,
                # sacrifice this artifact." (Runesword.) CR 603.6c's wider event
                # about the same bound object the row above names — a bounce and
                # a tuck are both this and neither is a death, which is why the
                # two are separate events rather than one with a flag.
                event, binds = "bound_permanent_leaves_battlefield", True
                if not stream.accept_phrase("this", "turn"):
                    duration = "until_it_triggers"
            elif subject is None:
                # "When **this artifact** leaves the battlefield this turn,
                # destroy that creature." (War Barge.) The delay printed *in
                # front* of its effect, naming the object it watches — which
                # here is the ability's own source, while the effect names the
                # creature the ability targeted. Two objects, so `binds` is
                # granted: the opener says what is watched and
                # `delay_binds_an_object` reads the effect for what is acted on.
                stream.reset(mark)
                leading = parse_leaves_battlefield_delay(stream)
                if leading is not None:
                    event, once, duration, _permitted, watches = leading
                    binds = True
    elif stream.accept_word("whenever"):
        # "Whenever that creature is dealt damage by an attacking creature this
        # turn, …" — "this turn" is CR 603.7b's stated duration, so this one
        # fires every time for as long as it lasts.
        after_whenever = stream.mark()
        subject = _delayed_bound_subject(stream)
        if subject is not None and stream.accept_phrase("is", "dealt", "damage", "by"):
            # The indefinite article is the noun parser's caller's business
            # everywhere in this grammar: `parse_object_filter` reads the
            # phrase from the noun onward.
            stream.accept_word("a", "an")
            try:
                agent = parse_object_filter(stream)
            except GrammarError:
                agent = None
            if agent is not None and stream.accept_phrase("this", "turn"):
                event, binds, once = "bound_permanent_dealt_damage", True, False
        if event is None:
            # "…whenever **this creature** blocks or becomes blocked by a
            # creature this combat, …" (Goblin Flotilla). The joined block event
            # about the ability's own source, created for a window — read before
            # the land-tap opener below, which it does not collide with, and
            # after the bound-object one above, whose "that <noun>" it is not.
            stream.reset(after_whenever)
            pair = _parse_source_block_pair_delay(stream)
            if pair is not None:
                # The noun phrase is the **agent**, not the subject: the entry
                # watches the ability's own source by id, and the phrase after
                # "by" describes the *other* half of the pair. Filed under the
                # field that is tested against that half, so the narrowing is
                # asked of the creature the card narrows.
                agent, duration = pair
                event, once, watches = "source_blocks_or_blocked_by", False, "source"
        if event is None:
            # "…**whenever a player taps a Mountain for mana**, that player adds
            # an additional {R}." (Chaos Moon's odd branch.) The one opener here
            # that names no bound object at all: the land is described by a
            # printed noun phrase and the ability answers to whichever one is
            # tapped, on anybody's battlefield.
            #
            # Its duration is **unstated** — the card prints "until end of turn"
            # once, in front of the whole sentence, and shares it with the anthem
            # beside it. So the opener leaves it None and the leading-duration
            # reader fills it in; a sentence that reaches the lowering still
            # unstated refuses, because a repeating ability with no window is one
            # nothing ever lifts.
            stream.reset(after_whenever)
            subject = _parse_land_tapped_for_mana(stream)
            if subject is not None:
                event, once, duration = "land_tapped_for_mana", False, None
    else:
        for phrase, kind, kind_once, kind_duration, kind_binds in _DELAYED_OPENERS:
            if stream.accept_phrase(*phrase):
                event, once, duration, binds = kind, kind_once, kind_duration, kind_binds
                break

    if event is None:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    try:
        effect = parse_statement(stream, top_level=False)
    except GrammarError:
        stream.reset(mark)
        return None
    # The delay governs its whole sentence, so the effect has to run to the end
    # of one. Without this the production would accept a *prefix* — "destroy
    # all creatures" out of "destroy all creatures that were blocked by that
    # creature this turn" — and the words left over would either fail the line
    # somewhere that says nothing about what happened or, worse, parse as a
    # sentence of their own and be performed **now** rather than when the
    # ability fires. Declining instead leaves the refusal the line already had.
    if not stream.exhausted and not stream.at_punct(".", ";"):
        stream.reset(mark)
        return None
    if event == "land_tapped_for_mana" and not isinstance(
        effect, ast.AddManaForTappedLand
    ):
        # CR 605.4a: the abilities this event announces resolve *without using
        # the stack*, inside the cost payment that tapped the land — so the seam
        # that announces them can only carry out a mana production, and there is
        # no priority window in which anything else could resolve. An effect the
        # seam cannot perform refuses here rather than arming an ability that
        # would be found and skipped.
        stream.reset(mark)
        return None
    effect = resolve_that_turn(effect) or effect
    effect = fold_flip_stakes(stream, effect, parse_statement)
    if target is not None:
        # CR 603.7c: the ability is about the object its opener chose, so the
        # pronouns behind the comma name that object rather than the ability's
        # own source — which for Delif's Cube is a different permanent still on
        # the battlefield, named by the very next clause.
        effect = rebind_pronoun_to_delay_target(target, effect)
    return ast.CreateDelayedTrigger(
        event=event, effect=effect,
        once=once, duration=duration,
        binds_target=(
            # An opener that chose its own target binds it whatever the effect
            # behind it says: the choosing is the opener's, so there is no
            # sentence to read the permission against.
            binds if subject is not None or target is not None
            else delay_binds_an_object(binds, effect)
        ),
        subject=subject, agent=agent,
        watches=watches, target=target,
    )


def _contains_flip(node) -> bool:
    """Whether *node* flips a coin somewhere inside it (CR 705.1).

    Written as a walk over the dataclass rather than a check on the top-level
    node, for :func:`_names_a_bound_object`'s reason one function up: the flip
    may be one step of a sequence or the body of an offer, and a shape added
    later is covered by default instead of silently answering False.
    """
    if isinstance(node, ast.FlipCoin):
        return True
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return any(
            _contains_flip(getattr(node, field.name))
            for field in dataclasses.fields(node)
        )
    if isinstance(node, (tuple, list)):
        return any(_contains_flip(item) for item in node)
    return False


def fold_flip_stakes(stream: TokenStream, effect, parse_statement):
    """Fold ``If you {win,lose} the flip, <effect>.`` into the delayed sentence
    in front of it.

    "{R}: Target creature you control with toughness 2 or less gains flying
    until end of turn. **Flip a coin at the beginning of the next end step. If
    you lose the flip, sacrifice that creature.**" (Goblin Kites.)

    The two printed sentences are one delayed triggered ability: the flip
    happens at the end step and so does everything that depends on it. Left as a
    sibling step the conditional would be performed *now*, on the result of a
    flip that has not happened — which is what the lowering already refuses by
    name ("'the flip' with no coin flip before it in this effect"). So this can
    only turn a refusal into a card; it can never change a reading that already
    worked.

    Which is also what makes the fold safe to decide here rather than by a list
    of cards: the marker is that the following sentence back-references a value
    **only the delayed effect produces**. A flip inside the delay and a
    ``CoinFlipResult`` behind it is that relation spelled out, and nothing else
    matches it.

    Returns *effect* unchanged, cursor untouched, when the sentence behind it is
    anything else — a second delay, an ordinary step, a conditional on a board
    state — so every other card keeps the reading it has.
    """
    if not _contains_flip(effect):
        return effect
    mark = stream.mark()
    if not (stream.accept_punct(".") and stream.accept_word("if")):
        stream.reset(mark)
        return effect
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return effect
    if not isinstance(condition, ast.CoinFlipResult) or not stream.accept_punct(","):
        stream.reset(mark)
        return effect
    try:
        consequence = parse_statement(stream, top_level=False)
    except GrammarError:
        stream.reset(mark)
        return effect
    # The stakes govern their whole sentence, so the consequence has to run to
    # the end of one — the same guard `_parse_create_delayed_trigger` states
    # about its own body, and for the same reason: a prefix accepted here would
    # leave the rest to be performed immediately or to fail the line somewhere
    # that says nothing about what happened.
    if not stream.exhausted and not stream.at_punct(".", ";"):
        stream.reset(mark)
        return effect
    return ast.Sequence((effect, ast.Conditional(condition, consequence)))


def resolve_that_turn(node):
    """*node* with every ``until_end_of_that_turn`` duration made an ordinary
    end of turn, or None when it holds none.

    "…until the end of **that** turn" (Giant Slug) names the turn the delay it
    sits inside is about, and a delayed ability resolves *during* that turn — so
    inside a delay the two moments are the same one. Outside a delay the phrase
    names a turn nothing in the sentence identifies, and no lowering knows the
    kind, which is what keeps this rewrite from being a synonym table.

    Written against the dataclass fields rather than a per-node list, for the
    reason ``statements._round_every_half`` gives: a statement class added later
    is covered by default instead of silently keeping a duration nothing ends.
    """
    if isinstance(node, ast.Duration) and node.kind == "until_end_of_that_turn":
        return dataclasses.replace(node, kind="until_end_of_turn")
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        updates = {}
        for field in dataclasses.fields(node):
            rebuilt = resolve_that_turn(getattr(node, field.name))
            if rebuilt is not None:
                updates[field.name] = rebuilt
        return dataclasses.replace(node, **updates) if updates else None
    if isinstance(node, tuple):
        rebuilt_items = [resolve_that_turn(item) for item in node]
        if not any(item is not None for item in rebuilt_items):
            return None
        return tuple(
            new if new is not None else old
            for new, old in zip(rebuilt_items, node)
        )
    return None
