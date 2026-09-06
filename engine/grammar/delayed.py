"""Delayed triggered abilities (CR 603.7): the ability, and what its sentence
may refer back to.

Split from `statements` at the thousand-line guard, along the section boundary
that module already drew. A delayed trigger is not a statement like the others:
the rest of `statements` reads a sentence that *does* something now, while these
read one that arranges for something later, and the arrangement is what the
parse has to get right — which event, and what the later sentence is allowed to
refer back to.

Those are two subjects, and at Tempest's Phase 0 the second half of that
sentence became the seam: **which event** the printed opener names is
`delay_openers`, which this asks and never imports back. What is left is the
production that *arranges* the ability — :func:`_parse_create_delayed_trigger`,
the one place the rows become a node — and the three walks over the sentence it
wraps, which are the whole of "what may it refer back to": whether the effect is
about an object the spell chose, what "that turn" names inside a delay, and the
following sentence that back-references a flip only the delay produces.

That is also the stable half. Each walk is written against the dataclass fields
rather than a per-node list, so a statement class added later is covered by
default — where `delay_openers` takes a row or a production every time a set
prints a new wording.

`Choose target <noun>.` used to live here "for the same reason" a delayed
trigger does; a shared reason is not a shared subject, and it is `choices` now.

**The recursion arrives as a parameter.** A delayed trigger contains a whole
statement, so this file needs `parse_statement`, which is the roof one layer up.
Taking it as an argument keeps the dependency running one way — the inversion
`lowering/where_x.py` and `postmodifiers.py` both make, for the same reason.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .delay_openers import (_DELAYED_OPENERS, _delayed_bound_subject,
                            _parse_land_tapped_for_mana,
                            _parse_source_block_pair_delay,
                            _parse_targeted_combat_delay,
                            _parse_targeted_damage_delay,
                            parse_leaves_battlefield_delay,
                            parse_untap_or_control_delay)
from .errors import GrammarError
from .conditions import _parse_condition
from .nouns import parse_object_filter
from .rebinding import rebind_pronoun_to_delay_target
from .stream import TokenStream


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
                if leading is None:
                    # "When this creature **becomes untapped or you lose
                    # control of this creature**, exile that creature."
                    # (Coffin Queen.) The sibling opener, tried after it and
                    # declining without consuming: the two open on the same
                    # three words and differ from the fourth on, so the order
                    # decides which refusal survives rather than which card is
                    # read.
                    stream.reset(mark)
                    leading = parse_untap_or_control_delay(stream)
                if leading is not None:
                    event, once, duration, _permitted, watches = leading
                    binds = True
    elif stream.accept_word("whenever"):
        # "Whenever that creature is dealt damage by an attacking creature this
        # turn, …" — "this turn" is CR 603.7b's stated duration, so this one
        # fires every time for as long as it lasts.
        after_whenever = stream.mark()
        # "Whenever **target creature** deals combat damage to a non-Wall
        # creature this turn, …" (Acidic Dagger.) Read before the bound-subject
        # openers below: this one *chooses* its object where those name one the
        # effect already holds, and it declines without consuming — the same
        # order the "when" branch puts `_parse_targeted_combat_delay` in.
        aimed = _parse_targeted_damage_delay(stream)
        if aimed is not None:
            target, agent = aimed
            event, binds, once, duration = (
                "bound_permanent_deals_combat_damage", True, False, "end_of_turn",
            )
        subject = None if event is not None else _delayed_bound_subject(stream)
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
                # "…at the beginning of your next main phase **this turn**"
                # (Pygmy Hippo). CR 603.7b's stated duration printed at the
                # *end* of the opener rather than in front of it — the window
                # the leading reader at the top of this function takes from the
                # other side. It narrows rather than widens: an opener whose
                # own default waits for its step however many turns away
                # (`until_it_triggers`) is held to this turn, so a next main
                # phase that never comes leaves nothing armed.
                #
                # Read here rather than as a row of its own, because a row per
                # opener per window is the table squared, and the words say the
                # same thing after any of them.
                if stream.accept_phrase("this", "turn"):
                    duration = "end_of_turn"
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
