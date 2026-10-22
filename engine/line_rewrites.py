"""Every rewrite applied to a card's text before a single line is classified.

:func:`expand_ability_lines` is the text every reader of a card's lines must
start from — the compiler, ``engine/legality.py``,
``scripts/parse_coverage.py``, ``scripts/hook_reliance.py`` — or it is
reading a different card; :func:`expand_card_lines` is that rule made cheap
for a reader holding the card. Most rewrites are the rules' own. A keyword the
CR defines *as* an ability becomes that ability's sentence (equip, cycling,
buyback, kicker, echo, fading, flashback — each read in the keyword's own
module); a modal activated head becomes one ability per bullet; two trigger
conditions joined by "and" become two triggers; a static-then-trigger
paragraph becomes two lines; "The same is true for ..." becomes one line per
quality; and an ability-word paragraph saying "...instead" is joined onto the
paragraph it replaces (CR 608.2c, CR 207.2c). One is the card's: a legendary
card's short self-reference written out (``engine/self_reference.py``).

Split out of ``engine/oracle.py`` at the 2,000-line cap; ``engine.oracle``
still exports the two entry points.
"""

from __future__ import annotations

import re

from .oracle_types import strip_ability_word
from .cycling import expand_cycling_lines
from .flashback import expand_flashback_lines
from .equipment import expand_equip_lines
from .grammar import ast as grammar_ast
from .front_ends import _is_ability_line
from .ability_lines import _bullets_after, _modal_head
from .derived_static_claims import _derived_static_claims


def expand_modal_activated_lines(oracle_text: str) -> str:
    """Rewrite '{cost}: Choose one —' + bullets into one ability line per
    bullet. Text without that shape is returned unchanged. Shared with
    engine.legality so target classification sees the same lines.

    A modal ACTIVATED ability ("{2}: Choose one —" followed by bullet lines,
    e.g. Pyramids) becomes one plain activated-ability line per bullet, same
    cost, so the existing multi-ability machinery (ability_index choice,
    per-ability targeting) covers it — and so the bullets are never mistaken for
    cast-time modes or top-level spell effects.

    Whether a line *is* such a head is the grammar's answer
    (:func:`_modal_head`), not a regex's. The regex it replaced admitted mana
    symbols only, so "Sacrifice a creature: Choose one —" would have been left
    on the floor, and it hard-coded "choose one" so no other count could ever be
    read — while the grammar refuses a count the engine cannot carry out and
    that refusal reaches here as a head this declines to expand. Only the cost
    is still taken from the raw text, because this rewrites text: re-rendering a
    parsed cost would be a second spelling of it, free to differ from the one
    ``mixins/stack/activation.py`` charges.
    """
    if "choose" not in (oracle_text or "").lower():
        return oracle_text
    lines = (oracle_text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # ":" and "choose" are both necessary for the grammar to read the line
        # as an activated modal head, so testing them first only skips work.
        if ":" in line and "choose" in line.lower() and (
            _modal_head(line, grammar_ast.ActivatedAbilityNode) is not None
        ):
            bullets = _bullets_after(lines, i)
            if bullets:
                cost, _, effect = line.partition(":")
                cost = cost.strip()
                # Whatever the head line printed *after* "Choose one." rides on
                # to every expanded ability — "Activate only if there are two or
                # more hatchling counters on this artifact." (Triassic Egg). The
                # restriction is enforced off ``source_line``, so a rewrite that
                # dropped it would turn a gated ability into a free one, on
                # every mode at once. Taken from the raw text for the same
                # reason the cost is: re-rendering it would be a second
                # spelling, free to differ from the one the restriction table
                # matches.
                head, _, tail = effect.partition(".")
                tail = tail.strip()
                out.extend(
                    f"{cost}: {bullet}" + (f" {tail}" if tail else "")
                    for bullet in bullets
                )
                i += 1 + len(bullets)
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


#: "At the beginning of your upkeep **and** whenever enchanted land becomes
#: tapped, remove an ore counter from this Aura." (Orcish Mine.) CR 603.1 lets
#: one triggered ability name several trigger events; the printed shape is two
#: conditions joined by "and", one comma, then the effect they share.
#:
#: Neither condition may contain a comma, which is what pins the shape: the
#: single comma in the line is the boundary between the conditions and the
#: effect. Chaos Moon prints "…red creatures get +1/+1 **and whenever** a player
#: taps a Mountain for mana, that player adds…" and is *not* this shape — its
#: first clause ends in a comma long before the joining word, so the pattern
#: cannot reach across it.
_CONJOINED_TRIGGER_LINE = re.compile(
    r"^(?P<first>(?:at|whenever|when) [^,]+?)"
    r" and (?P<second>(?:at|whenever|when) [^,]+?), (?P<effect>.+)$",
    re.IGNORECASE,
)


def expand_conjoined_trigger_lines(oracle_text: str) -> str:
    """*oracle_text* with a two-condition trigger line rewritten as two lines.

    "At the beginning of your upkeep and whenever enchanted land becomes tapped,
    remove an ore counter from this Aura" is one ability with two trigger events
    (CR 603.1), and it triggers on each of them — which is behaviourally what
    two abilities with one event each and the same effect do. Rewriting it here
    is the ``expand_equip_lines`` move: from this point on the grammar, the
    condition table, the Aura gate, the parse-coverage census and the hook
    census all read two ordinary trigger lines that already work, and none of
    them learns a second shape.

    A representation instead — a list of conditions on ``ParsedTriggeredAbility``
    — would have to be taught to every fire site in the engine, each of which
    matches on one condition kind.

    The safety here is the full-consumption invariant, not this function's
    judgement: a split that produced a sentence the grammar cannot read leaves
    the card unsupported naming the line, which is the loud direction. What it
    must never do is *quietly* rewrite a line that was not this shape, which is
    why both conditions are comma-free and the joining word must begin a trigger
    word rather than merely appear.
    """
    if not oracle_text or " and " not in oracle_text:
        return oracle_text
    out: list[str] = []
    for line in oracle_text.splitlines():
        match = _CONJOINED_TRIGGER_LINE.match(line.strip())
        if match is None:
            out.append(line)
            continue
        effect = match.group("effect")
        second = match.group("second")
        out.append(f"{match.group('first')}, {effect}")
        out.append(f"{second[:1].upper()}{second[1:]}, {effect}")
    return "\n".join(out)


def expand_ability_lines(
    oracle_text: str, *, card_name: str | None = None, legendary: bool = False
) -> str:
    """Every rewrite the compiler applies to a card's text before a single line
    is classified — and therefore the text every *other* reader of a card's
    lines must start from (``engine/legality.py``, ``scripts/parse_coverage.py``,
    ``scripts/hook_reliance.py``), or it is reading a different card.

    Three rewrites today, all of them the rules' own:

    * a modal activated head and its bullets become one ability line per
      bullet (:func:`expand_modal_activated_lines`);
    * an equip keyword line becomes the activated ability CR 702.6a says it
      *means* — "[Cost]: Attach this permanent to target creature you control.
      Activate only as a sorcery." (``engine/equipment.py``). From there it is
      an ordinary activated ability to the grammar, the cost parser, the timing
      table and the target picker, none of which know the word.
    * a **cycling** keyword line becomes the activated ability CR 702.29a says
      it *means* — "[Cost], Discard this card: Draw a card." (``engine/cycling.py``).
      From there it is an ordinary activated ability to the grammar, the cost
      parser, ``engine/activation_zones.py``'s CR 113.6j zone read and the web
      layer's hand-activation path, none of which know the word. The rule's
      *other* half — CR 702.29b, the ability existing in every zone while being
      activatable from one — is not a rewrite and is not here: it is CR 113.6j
      asked of the cost, in ``engine/activation_zones.py``.
    * a **buyback** keyword line becomes the additional cost CR 702.27a says it
      means — "As an additional cost to cast this spell, you may pay [cost]."
      (``engine/cast_costs.py``). From there it is an ordinary CR 601.2b
      optional additional cost to the cost table, the cast path, the payability
      ceiling and the browser's cast-offer prompt, none of which know the word.
      The rule's *second* static ability — the spell goes to its owner's hand
      instead of the graveyard as it resolves — has no sentence to rewrite into
      and is implemented at the one seam a resolving spell leaves the stack
      through (``mixins/stack/resolution._bin_spell_card``), off the same
      reader that produced this line.
    * an **echo** keyword line becomes the triggered ability CR 702.30a says it
      means — "At the beginning of your upkeep, if this permanent came under
      your control since the beginning of your last upkeep, sacrifice it unless
      you pay [cost]." (``engine/echo.py``). From there it is an ordinary
      pay-or-sacrifice upkeep trigger to the grammar, to CR 603.4's
      intervening-if gate the upkeep step already checks, and to the registered
      handler that charges it, none of which know the word.
    * a **fading** keyword line becomes the *two* abilities CR 702.32a says it
      represents — "This permanent enters with N fade counters on it." and "At
      the beginning of your upkeep, remove a fade counter from this permanent.
      If you can't, sacrifice the permanent." (``engine/fading.py``), one line
      each. From there it is the named-counter entry state and an ordinary
      upkeep trigger with a ``CouldNot`` branch, none of which know the word.

    * an **ability-word paragraph that says "…instead"** becomes the last
      sentence of the paragraph above it
      (:func:`expand_instead_paragraph_lines`) — "Thermal Blast deals 3 damage
      to target creature.\\nThreshold — Thermal Blast deals 5 damage instead if
      there are seven or more cards in your graveyard." CR 608.2c's later text
      modifying earlier text, over a paragraph break the ability word put
      there and CR 207.2c says means nothing. The one rewrite here that joins
      lines; from there the pair is two sentences of one line to the sentence
      loop, which already folds an "instead" sentence into the step it
      replaces.

    And one rewrite that is the *card's* rather than the rules': a legendary
    card's shortened self-reference written out in full
    (``engine/self_reference.py``). It belongs in this pass for exactly the
    reason the other three do — every reader of a card's lines has to see the
    same sentence, and the readers that see only the compiler's stored text have
    no name to shorten *with*. A caller that names no card gets the text
    unchanged, which is what every reader asking about a line rather than a card
    wants.
    """
    from .cast_costs import expand_buyback_lines, expand_kicker_lines
    from .echo import expand_echo_lines
    from .fading import expand_fading_lines
    from .self_reference import expand_short_self_references

    oracle_text = expand_short_self_references(
        oracle_text, card_name, legendary=legendary
    )
    # CR 608.2c's, and the one rewrite here that *joins* lines where the rest
    # split or replace them: an ability-word paragraph saying "…instead" is the
    # last sentence of the paragraph above it. Its own statement for echo's
    # reason below, and ahead of every keyword rewrite on purpose: a printed
    # keyword line does not end a sentence, which is the gate that keeps this
    # from joining onto one, and several of them are rewritten into text that
    # does.
    oracle_text = expand_instead_paragraph_lines(oracle_text)
    # CR 702.30a's rewrite, as its own statement rather than another layer of
    # the composition below: an echo keyword line is a whole line and none of
    # the rewrites below reads one, so the order between them carries no
    # meaning and nesting it would only make the next addition here a conflict.
    oracle_text = expand_echo_lines(oracle_text)
    # CR 702.32a's, for echo's reason: a whole line in, whole lines out, read by
    # none of the rewrites below.
    oracle_text = expand_fading_lines(oracle_text)
    # CR 702.33a's: "Kicker [cost]" *means* "You may pay an additional [cost] as
    # you cast this spell", which is the CR 601.2b offer buyback's first half
    # already becomes (``engine/cast_costs.py``). Its own statement for echo's
    # reason -- a whole keyword line in, one cost sentence out, read by none of
    # the rewrites below. What makes kicker more than a cost is that the card's
    # *other* sentences ask whether it was paid; that is ``cast_costs.kicked``,
    # not a rewrite.
    oracle_text = expand_kicker_lines(oracle_text)

    # Its own statement rather than another layer of the nested call below. The
    # composition is what every keyword-as-a-rewrite adds itself to, so it is
    # the one expression several parallel rounds edit at once; a statement line
    # appends cleanly where a nested argument collides. Order is free here —
    # no other rewrite produces a cycling line and none consumes one.
    oracle_text = expand_cycling_lines(oracle_text)
    # CR 702.34a's, for cycling's reason and with its freedom of order: a whole
    # flashback keyword line in, the rule's own first sentence out ("You may
    # cast this card from your graveyard by paying [cost] rather than paying
    # its mana cost."), read by none of the rewrites around it
    # (``engine/flashback.py``). From there it is a CR 601.3 permission that
    # requires a CR 118.9 alternative cost, to ``cast_permissions`` and to the
    # cast path, neither of which knows the word. The rule's *second* static
    # ability — the card is exiled instead of going anywhere else as it leaves
    # the stack — has no sentence to rewrite into, for the reason buyback's
    # second half has none: it is a fact about one cast, stamped on the stack
    # object.
    oracle_text = expand_flashback_lines(oracle_text)
    return expand_same_is_true_lines(
        expand_static_then_trigger_lines(expand_conjoined_trigger_lines(
            expand_buyback_lines(
                expand_equip_lines(expand_modal_activated_lines(oracle_text))
            )
        ))
    )


#: "Reveal the first card you draw each turn. **Whenever** you reveal a basic
#: land card this way, draw a card." (Rowen.) A static ability and a triggered
#: one printed in a single paragraph, which is CR 113.3's "a card's abilities"
#: rather than one ability with two sentences.
#:
#: The gate is what makes the split safe, and it is deliberately not "a sentence
#: that begins a trigger word": the pool holds two spells whose second sentence
#: opens the same way and is a *delayed* ability the first sentence creates —
#: Glyph of Life's "choose target Wall creature. Whenever that creature is dealt
#: damage…" and Song of Blood's "mill four cards. Whenever a creature attacks
#: this turn…". Splitting either would take the second half away from the
#: resolution that has to create it. So the first sentence must be a **static
#: ability the engine already implements in full**, asked of the same derivation
#: tables the support gate asks — which no imperative answers.
_STATIC_THEN_TRIGGER_LINE = re.compile(
    r"^(?P<static>[^.]+\.) (?P<trigger>(?:Whenever|When|At) .+)$"
)


def expand_static_then_trigger_lines(oracle_text: str) -> str:
    """*oracle_text* with a static-then-trigger paragraph rewritten as two lines.

    The ``expand_conjoined_trigger_lines`` move one shape over: from here on the
    grammar, the condition table, the parse-coverage census and the hook census
    all read two ordinary lines that already work, and none of them learns a
    second shape.

    The safety is the gate above plus the full-consumption invariant: a split
    that produced a sentence the grammar cannot read leaves the card unsupported
    naming the line, which is the loud direction. What it must never do is
    quietly rewrite a line that was not this shape.
    """
    if not oracle_text:
        return oracle_text
    out: list[str] = []
    for line in oracle_text.splitlines():
        match = _STATIC_THEN_TRIGGER_LINE.match(line.strip())
        static = match.group("static").strip() if match else ""
        if not match or not _derived_static_claims(static, static.lower().rstrip("."), None):
            out.append(line)
            continue
        out.append(static)
        out.append(match.group("trigger"))
    return "\n".join(out)


#: "As long as an opponent controls a creature with flying not named ~, this
#: creature has flying. **The same is true for first strike, trample, and
#: protection from any color.**" (Escaped Shapeshifter.)
#:
#: CR 113.3: what the second sentence names is not a second ability, it is a
#: shorthand for the first ability repeated once per quality — so the rewrite
#: writes them out and every reader downstream sees ordinary conditional
#: statics, none of which learns the phrase.
#:
#: The gate is deliberately narrow. Both halves of the first sentence must name
#: the **same** quality, checked as a substitution rather than as a pattern (see
#: below), and the sentence must be the conditional-static shape: the other card
#: in the pool printing these five words is Celestial Dawn, whose "The same is
#: true for spells you control and nonland cards you own…" extends a *colour
#: rewrite* to objects in other zones and is nothing like this.
_SAME_IS_TRUE_LINE = re.compile(
    r"^(?P<first>As long as .+?, this creature has (?P<quality>[^.]+?)\.) "
    r"The same is true for (?P<rest>[^.]+)\.$"
)

#: "protection from **any color**" is five abilities, not one quality
#: (CR 702.16b: protection is always from a stated quality). The card gains
#: protection from a colour only while an opponent controls a creature with
#: protection from *that* colour, so a single "any color" static would be five
#: conditions collapsed into one and would hold when none of them did.
_ANY_COLOR_PROTECTION = "protection from any color"
_PROTECTION_COLOR_WORDS = ("white", "blue", "black", "red", "green")


def _same_is_true_qualities(rest: str) -> list[str] | None:
    """The qualities "The same is true for <rest>" names, or None.

    A printed list with an Oxford comma, so the conjunction is stripped from the
    last item rather than used as the separator. An empty item refuses the whole
    rewrite: a rewrite that guesses is worse than a card left unsupported.
    """
    items: list[str] = []
    for part in rest.split(","):
        part = part.strip()
        if part.lower().startswith("and "):
            part = part[len("and "):].strip()
        if not part:
            return None
        if part.lower() == _ANY_COLOR_PROTECTION:
            items.extend(f"protection from {word}" for word in _PROTECTION_COLOR_WORDS)
        else:
            items.append(part)
    return items or None


def expand_same_is_true_lines(oracle_text: str) -> str:
    """*oracle_text* with a "The same is true for …" paragraph written out.

    One line in, one line per quality out — the first sentence verbatim, then a
    copy of it per further quality with the quality **substituted in both
    places it appears**. Substitution rather than a template is what makes the
    rewrite checkable: the quality has to occur exactly twice in the sentence
    (once in the condition, once in the effect), and a sentence where it does
    not is left alone. Anything else would be guessing which "flying" the second
    sentence meant.
    """
    if not oracle_text or "The same is true for" not in oracle_text:
        return oracle_text
    out: list[str] = []
    for line in oracle_text.splitlines():
        match = _SAME_IS_TRUE_LINE.match(line.strip())
        if match is None:
            out.append(line)
            continue
        first, quality = match.group("first"), match.group("quality")
        qualities = _same_is_true_qualities(match.group("rest"))
        if qualities is None or first.count(quality) != 2:
            out.append(line)
            continue
        out.append(first)
        out.extend(first.replace(quality, other) for other in qualities)
    return "\n".join(out)


#: The sentence-replacing "instead": the word with no "of" behind it. "Instead
#: of" compares two things inside one sentence ("…instead of any other type"),
#: which is a sentence standing on its own.
_REPLACING_INSTEAD = re.compile(r"\binstead\b(?! of\b)", re.IGNORECASE)

#: Parenthesised reminder text, for asking how a printed line *ends* without it.
_TRAILING_REMINDER = re.compile(r"\s*\([^()]*\)\s*$")


def _replaces_the_paragraph_above(sentence: str) -> bool:
    """Whether an ability-word paragraph's text replaces the paragraph above
    it rather than standing as an ability of its own.

    "Thermal Blast deals 5 damage **instead** if there are seven or more cards
    in your graveyard." Three tests, each a way the word can mean something
    else:

    * it says "instead", and not "instead of";
    * it does not say "would" — "If a creature would die, exile it instead" is
      CR 614.1a's replacement of an *event*, complete in itself;
    * it is not an ability with a cost or a trigger of its own, whose "instead"
      is about its own effect.
    """
    lowered = sentence.lower()
    if _REPLACING_INSTEAD.search(lowered) is None or re.search(r"\bwould\b", lowered):
        return False
    return not _is_ability_line(sentence)


def expand_instead_paragraph_lines(oracle_text: str) -> str:
    """*oracle_text* with an ability-word paragraph that replaces the one above
    it joined onto that paragraph as its last sentence.

    "Thermal Blast deals 3 damage to target creature.\\nThreshold — Thermal
    Blast deals 5 damage instead if there are seven or more cards in your
    graveyard." is **one** effect printed as two paragraphs: CR 608.2c's later
    text modifying the meaning of earlier text, with exactly one of the two
    amounts ever dealt. Every reader of a card's lines takes a line as a unit —
    the compiler lowers each to its own instruction and a spell resolves them
    all in order — so read as printed the second paragraph either means
    nothing (it names no recipient) or happens *as well* (3 damage, then 5).
    The sentence loop already folds an "…instead" sentence into the step it
    replaces (``engine/grammar/conditional_instead.py``); what it needs is to
    be handed both sentences on one line.

    The paragraph break is typography, and the rule says so: an ability word
    "has no rules meaning" (CR 207.2c), and it is the ability word that puts
    the break there. So the join is gated on exactly that — the line must open
    with one — and the word is dropped as the grammar would have dropped it.
    Threshold prints it this way, and so do hellbent ("…deals 5 damage instead
    if you have no cards in hand") and metalcraft after it.

    Everything else about the gate is refusal: see
    :func:`_replaces_the_paragraph_above`, and the paragraph above must *end a
    sentence* — a keyword line ("Kicker {2}") is nothing an "instead" can
    replace. A paragraph this does not join is left exactly as printed, where
    it reports as unclaimed text rather than as a guess.
    """
    if not oracle_text or "instead" not in oracle_text.lower():
        return oracle_text
    out: list[str] = []
    for line in oracle_text.splitlines():
        printed = line.strip()
        sentence = strip_ability_word(printed)
        if (
            out
            and sentence != printed
            and _TRAILING_REMINDER.sub("", out[-1]).rstrip().endswith((".", '."'))
            and _replaces_the_paragraph_above(sentence)
        ):
            out[-1] = f"{out[-1].rstrip()} {sentence}"
            continue
        out.append(line)
    return "\n".join(out)


def expand_card_lines(card) -> list[str]:
    """*card*'s printed lines after every rewrite :func:`expand_ability_lines`
    applies, as a list.

    The convenience the rule "every other reader of a card's lines must start
    from that same function" needs to be cheap to obey. A reader holding the
    card has no excuse to split ``oracle_text`` itself, and the one that did —
    the entry state — was reading a legendary card's shortened self-reference
    that the gate above it had already written out, so the card compiled
    supported and then entered with nothing on it.
    """
    return expand_ability_lines(
        card.oracle_text or "", card_name=card.name, legendary=card.is_legendary
    ).splitlines()
