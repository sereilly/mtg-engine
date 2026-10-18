"""Whole printed lines that are **continuous** abilities (CR 613).

The parse mirror of ``engine/grammar/statics.py``, split out of ``parser.py``
at the 1,000-line guard the round Homarid's leading-order condition landed —
and the file had been sitting on 995 of it, so the boundary was already there
to be found. It is the one ``parser.py`` already drew in its own shape: every
production here reads a line the sentence loop would fail, because the line's
*frame* is a condition rather than a verb, and each one hands back an
``ast.StaticAbilityNode`` rather than a step.

**The name.** The mirror's word is ``statics``, and that path is taken one
directory up by the lowering half — so this is ``OracleProgram.static_lines``'
own word for the same thing rather than a new one. Which is also what the
module is: what these productions produce is exactly what the compiler records
under that name.

Sits between ``riders`` and ``costs`` in the layer order: it reads whole
sentences (``statements``) and conditions, and nothing above it reaches back.

The one fragment it used to read out of ``phrases`` is here now.
``accept_member_state_clause`` — the "it's not attacking" of Arcades Sabboth's
"as long as" — was filed there as a shared fragment and has had exactly one
caller since the day it was written, ``_narrow_by_member_state`` below. It came
across at the Phase 0 before Invasion, when ``phrases`` was 38 lines under the
guard and its own rule ("a fragment two families need") was the test.
"""

from __future__ import annotations

from dataclasses import replace

from . import ast
from .amounts import expect_pt
from .conditions import _parse_condition
from .effects.characteristics import _parse_quoted_abilities
from .errors import GrammarError
from .keywords import parse_keyword_list
from .lexer import QUOTE, SELF
from .nouns import _STATE_ADJECTIVES
from .references import parse_recipient
from .statements import parse_statement
from .stream import TokenStream
from .vocabulary import COLOR_WORDS


def _looks_static(statement: ast.Statement) -> bool:
    """A continuous effect with no duration on a non-targeted subject is a
    static ability.

    A *conjunction* of them is one too — "Other Goblins get +1/+1 and have
    mountainwalk" is a single static ability with two halves, not a spell
    effect. It reached ``SpellEffectLine`` only because this predicate looked at
    one effect at a time, which put the lord lines on a different lowering path
    from the anthem lines that say exactly the same kind of thing.
    """
    if isinstance(statement, ast.Conjunction):
        return bool(statement.effects) and all(
            _looks_static(effect) for effect in statement.effects
        )
    if isinstance(statement, ast.Pump):
        return statement.duration.kind is None and (
            not isinstance(statement.subject, ast.TargetSpec)
            or statement.subject.quantifier not in ("target", "up_to")
        )
    if isinstance(statement, (ast.GainKeyword, ast.LoseKeyword)):
        return statement.duration.kind is None and (
            not isinstance(statement.subject, ast.TargetSpec)
            or statement.subject.quantifier not in ("target", "up_to")
        )
    return False


def _parse_turn_scoped_static_line(
    stream: TokenStream,
) -> ast.StaticAbilityNode | None:
    """``During your turn, <continuous effect>.`` / ``During turns other than
    yours, <continuous effect>.`` (Vibrating Sphere, CR 613 layer 7c.)

    The same shape :func:`_parse_static_condition_line` reads with the condition
    printed *last*, and it lands on the same node — so the two word orders
    cannot mean different things. What it is **not** is a duration: nothing
    resolves here, and the bonus is gone at the next untap step with nothing to
    undo (the distinction that function's docstring draws for "as long as").

    Deliberately narrowed to a **distributive** subject, and that narrowing is
    the ordering rule rather than a convenience: "During your turn, this
    creature has first strike" (Radha, Heart of Keld) is read by
    ``engine/static_bonuses.conditional_static_for``, a derivation table the
    grammar reaches only where every production refuses the line *in full*
    (``engine/grammar/derived.py``). A production that parsed that sentence and
    then refused in lowering would take the table's line away — parsed-but-
    unlowered is still parsed — so the refusal happens here, in the parse.
    """
    mark = stream.mark()
    if not stream.accept_word("during"):
        return None
    if stream.accept_phrase("your", "turn"):
        negated = False
    elif stream.accept_phrase("turns", "other", "than", "yours"):
        negated = True
    else:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    try:
        statement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if (
        not stream.exhausted
        or not _looks_static(statement)
        or _distributive_subject(statement) is None
    ):
        stream.reset(mark)
        return None
    return ast.StaticAbilityNode(statement, ast.TurnIsYours(negated=negated))


def _parse_leading_static_condition_line(
    stream: TokenStream,
) -> ast.StaticAbilityNode | None:
    """``As long as <counter count>, <continuous effect>.``

    "As long as there is exactly one tide counter on this creature, it gets
    -1/-1." (Homarid.) "As long as there are exactly three tide counters on
    this enchantment, all blue creatures get +2/+0." (Tidal Influence.) One
    sentence with the subject and the affected set changed, and the two land on
    the same node as :func:`_parse_static_condition_line`'s trailing word order
    — so which half of the line the condition was printed on cannot change what
    the ability means.

    ``As long as <state of the source>, <anthem>.`` ("As long as this creature
    is untapped, green creatures you control get +1/+1." — Juniper Order
    Advocate.) The same node with a different condition and a *set* in place of
    the single subject, so which half of the line the condition was printed on
    still cannot change what the ability means.

    **Restricted to two shapes**, and the restriction is the ordering rule
    rather than a convenience. ``engine/static_bonuses.py`` reads this exact
    word order ("As long as you control a Swamp, this creature gets +1/+1") as a
    derivation table, which the grammar reaches only where every production
    refuses the line *in full* (``engine/grammar/derived.py``). A production
    that read every leading condition would parse those sentences and then
    refuse them in lowering — parsed-but-unlowered is still parsed — and take
    the table's lines away. So each admitted shape has to be one that table
    cannot read at all:

    - the **counter count**, which it has no row for, and whose effect side
      ("it gets -1/-1") is not the literal subject "this creature " its own
      pattern is anchored on;
    - any condition over a **distributive** subject, which that table cannot
      read for the same anchoring reason from the other end — its effect half
      *is* "this creature ", so "green creatures you control get +1/+1" is a
      sentence it declines whatever the condition says. That is also the one
      shape ``lord_buffs`` exists for, and the trailing word order of it
      already lowers through :func:`statics._lower_static_ability`'s
      conditional branch.

    A condition the anthem lowering cannot evaluate still refuses — there, by
    name — and the line falls back to the ordinary path with nothing consumed.
    """
    mark = stream.mark()
    if not stream.accept_phrase("as", "long", "as"):
        return None
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    try:
        statement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.exhausted or not _looks_static(statement):
        stream.reset(mark)
        return None
    # A third admitted shape, for the first one's reason: a **count of cards in
    # a zone** ("As long as there are seven or more cards in your graveyard,
    # this creature gets +1/+1 and has flying." — Odyssey's Mystics). That
    # table has no row for "there are …", so no printing of it has a second
    # reader to take a line from.
    if not isinstance(condition, (ast.SourceCounterCount, ast.CardsInZones)) and (
        _distributive_subject(statement) is None
    ):
        stream.reset(mark)
        return None
    return ast.StaticAbilityNode(statement, condition)


#: The first word of a predicate that is a whole **static sentence** about its
#: subject rather than a delta, a keyword or a colour: "…and **can't** block",
#: "…and **attacks** each combat if able". Closed on purpose. The words behind
#: one are recovered as printed and handed over as the sentence they
#: abbreviate ("This creature can't block."), and `statics` then asks the
#: compiler whether it reads that sentence — so a head listed here admits
#: nothing by itself, and a head not listed here fails the clause loudly
#: rather than being swallowed as part of the predicate in front of it.
_SENTENCE_PREDICATE_HEADS = ("can't", "attacks", "attack")

#: Every word a predicate of a conditional grant may open with.
_PREDICATE_HEADS = ("gets", "get", "has", "have", "is", "are") + _SENTENCE_PREDICATE_HEADS


def _granted_subject(stream: TokenStream) -> ast.TargetSpec | None:
    """The subject a conditional grant is printed about, or None.

    "This creature", "this enchantment", "enchanted creature", or a described
    set ("white creatures"). **Not the pronoun**: after a fronted condition
    "it" names whatever the condition was about — the Aura's host in "As long
    as enchanted permanent is red or green, **it** has …" (Essence Leak), the
    source in Homarid's — and a production that guessed would hand one card's
    ability to the wrong permanent. The readers that know which it is keep
    those lines.
    """
    try:
        subject = parse_recipient(stream)
    except GrammarError:
        return None
    if not isinstance(subject, ast.TargetSpec):
        return None
    if subject.quantifier in ("all", "each"):
        return subject
    if subject.quantifier == "this" and subject.filter.is_source:
        return subject
    if subject.filter.is_enchanted and subject.quantifier != "it":
        return subject
    return None


def _sentence_about(subject: ast.TargetSpec, words: str) -> str | None:
    """*words* as the static sentence its subject would print alone.

    "…this creature gets +2/+2 **and can't block**" abbreviates "This creature
    can't block.", and that sentence is what the subject has while the
    condition holds — on an Aura too, where "enchanted creature can't block"
    is, on the creature, the same "This creature can't block." Only one
    creature has one: every sentence admitted here is about combat, and a
    sentence handed to a *set* is a lord's quoted grant, which no card prints
    behind a condition.
    """
    if not _is_one_creature(subject) or not words.strip():
        return None
    return f"This creature {words.strip()}."


def _is_one_creature(subject: ast.TargetSpec) -> bool:
    return subject.quantifier not in ("all", "each") and (
        subject.filter.card_types == ("creature",)
    )


def _parse_granted_predicates(
    stream: TokenStream, subject: ast.TargetSpec
) -> tuple[ast.Statement, ...] | None:
    """``gets ±N/±N`` / ``has <keywords>`` / ``has "<ability>"`` / ``is
    <colour>`` / a static sentence, joined by commas and "and" — every
    predicate of one subject, as one statement apiece, or None.

    "…this creature gets +3/+3, is black, has trample, and has "At the
    beginning of your upkeep, sacrifice a creature."" (Wayward Angel) is four.
    A joining word is consumed only when a predicate head follows it, so the
    clause's own tail ("as long as …", the full stop) is left for the caller.
    """
    statements: list[ast.Statement] = []
    while True:
        head = stream.peek_word()
        if head not in _PREDICATE_HEADS:
            return None
        if head in ("gets", "get"):
            stream.advance()
            # "gets **an additional** +2/-2" (Patriarch's Desire, Divine
            # Sacrament). The words say this delta is on top of the one the
            # line above grants, which is what a second contribution to layer
            # 7c already is (CR 613.4c) — so they are read and add nothing.
            stream.accept_phrase("an", "additional")
            try:
                power, power_negative, toughness, toughness_negative = expect_pt(stream)
            except GrammarError:
                return None
            statements.append(ast.Pump(
                subject, power, toughness,
                power_negative=power_negative, toughness_negative=toughness_negative,
            ))
        elif head in ("has", "have"):
            stream.advance()
            if stream.at_kind(QUOTE):
                try:
                    abilities, self_name = _parse_quoted_abilities(stream)
                except GrammarError:
                    return None
                statements.append(
                    ast.GainAbilityText(subject, abilities, self_name=self_name)
                )
            else:
                try:
                    keywords, disjunctive = parse_keyword_list(stream)
                except GrammarError:
                    return None
                if not keywords or disjunctive:
                    return None
                statements.append(ast.GainKeyword(subject, keywords))
        elif head in ("is", "are"):
            stream.advance()
            color = COLOR_WORDS.get(stream.peek_word() or "")
            if color is None:
                return None
            stream.advance()
            statements.append(ast.BecomeColor(subject, color))
        else:
            start = stream.mark()
            while not (
                stream.exhausted
                or stream.at_punct(".", ",")
                or stream.at_kind(QUOTE)
                or stream.at_word("and")
                or (stream.at_word("as") and stream.words_from()[:3] == ("as", "long", "as"))
            ):
                stream.advance()
            sentence = _sentence_about(subject, stream.text_between(start, stream.mark()))
            if sentence is None:
                return None
            statements.append(ast.GainAbilityText(subject, (sentence,)))
        joined = stream.mark()
        stream.accept_punct(",")
        stream.accept_word("and")
        if stream.mark() == joined or stream.peek_word() not in _PREDICATE_HEADS:
            stream.reset(joined)
            return tuple(statements)


def _parse_granted_clause(stream: TokenStream) -> ast.Statement | None:
    """The effect half of a conditional grant: one subject and its predicates,
    or the one whole sentence printed *about* a subject —

    "**all creatures able to block** this creature **do so**" (Stone-Tongue
    Basilisk; Seton's Desire prints it about the enchanted creature). CR
    509.1c's requirement on every potential blocker, which the engine reads
    off the attacker as "All creatures able to block this creature do so." —
    so that sentence is what the subject is handed.
    """
    mark = stream.mark()
    if stream.accept_phrase("all", "creatures", "able", "to", "block"):
        subject = _granted_subject(stream)
        if (
            subject is None
            or not _is_one_creature(subject)
            or not stream.accept_phrase("do", "so")
        ):
            stream.reset(mark)
            return None
        return ast.GainAbilityText(
            subject, ("All creatures able to block this creature do so.",)
        )
    subject = _granted_subject(stream)
    if subject is None:
        stream.reset(mark)
        return None
    statements = _parse_granted_predicates(stream, subject)
    if not statements:
        stream.reset(mark)
        return None
    return statements[0] if len(statements) == 1 else ast.Conjunction(statements)


def _parse_conditional_grant_line(stream: TokenStream) -> ast.StaticAbilityNode | None:
    """``As long as <condition>, <subject> <predicates>.`` and its trailing
    twin, where a predicate is something the two productions above cannot
    read: a **quoted ability**, a **colour**, a **static sentence**, or a delta
    printed as "an additional" one.

    "As long as there are seven or more cards in your graveyard, this creature
    gets +2/+2 and can't block." (Childhood Horror.) "…this creature is white
    and has "{T}: Destroy target black creature."" (Repentant Vampire.)
    "Enchanted creature can't block as long as …" (Kirtar's Desire.) One
    continuous ability whose effect has several parts in several layers
    (CR 613.6), all of them there exactly while the condition is.

    Tried **after** its two siblings and returning None for any clause they
    could have read, which is the ordering rule this module keeps repeating:
    a self bonus behind a condition about your own board is
    ``engine/static_bonuses.py``'s, and a production that parsed those lines
    here would have a second opinion about them. What makes a line this
    production's is a predicate nothing else reads.

    The line arrives here from two places — the ordinary path, and
    ``parse_line``'s quote guard, which refuses every line carrying a
    quotation mark before the ordinary path can see it.
    """
    mark = stream.mark()
    condition: ast.Condition | None = None
    statement: ast.Statement | None = None
    if stream.accept_phrase("as", "long", "as"):
        try:
            condition = _parse_condition(stream)
        except GrammarError:
            condition = None
        if condition is not None and stream.accept_punct(","):
            statement = _parse_granted_clause(stream)
    else:
        statement = _parse_granted_clause(stream)
        if statement is not None and stream.accept_phrase("as", "long", "as"):
            try:
                condition = _parse_condition(stream)
            except GrammarError:
                condition = None
        else:
            statement = None
    stream.accept_punct(".")
    if statement is None or condition is None or not stream.exhausted:
        stream.reset(mark)
        return None
    effects = statement.effects if isinstance(statement, ast.Conjunction) else (statement,)
    if not any(_only_this_production_reads(effect, stream) for effect in effects):
        stream.reset(mark)
        return None
    if _a_text_table_reads(stream):
        stream.reset(mark)
        return None
    return ast.StaticAbilityNode(statement, condition)


def _a_text_table_reads(stream: TokenStream) -> bool:
    """Whether one of the two text tables that read a whole conditional
    sentence about "this creature" reads the line *stream* holds — in which
    case the line is that table's and not a production's.

    "This creature can't be blocked by creatures with power 2 or greater **as
    long as defending player controls a snow land**." (Arctic Foxes,
    ``engine/combat_restrictions.py``.) A combat restriction with a condition
    the table reads itself, enforced at the declaration with the defending
    player in hand — a seat no continuous recompute has. "This creature can't
    be blocked **as long as it's enchanted**." (Metathran Elite,
    ``engine/static_bonuses.py``.) Each table is reached where the grammar
    does not lower the line, and ``tests/engine/test_grammar_derived_lines.py``
    holds the first one's lines to *failing the parser*. This production's
    static-sentence predicate is the same words: left unasked it parsed both
    lines, refused them a layer later, and stood between a line and its only
    reader. A differential of the grammar's verdict on every line in the pool
    named them; the compiled programs had not moved.

    So the tables are asked, of the line as the compiler would hand it over —
    lower-cased, the card's own name read as "this creature" — rather than
    this module keeping a second list of which conditions each one knows.
    The imports are at call time: both modules read the grammar themselves.
    """
    from ..combat_restrictions import combat_restriction_for
    from ..static_bonuses import static_bonus_for

    pieces: list[str] = []
    start = 0
    for index, token in enumerate(stream.tokens):
        if token.kind == SELF:
            pieces += [stream.text_between(start, index), "this creature"]
            start = index + 1
    pieces.append(stream.text_between(start, len(stream.tokens)))
    line = " ".join(" ".join(pieces).split()).lower()
    return (
        combat_restriction_for(line) is not None
        or static_bonus_for(line) is not None
    )


def _only_this_production_reads(effect: ast.Statement, stream: TokenStream) -> bool:
    """Whether *effect* is a predicate the older static productions cannot
    read — the admission test :func:`_parse_conditional_grant_line` documents.

    A plain delta or keyword is not, with one exception read off the tokens:
    "gets **an additional** …", which the pump production refuses outright.
    """
    if isinstance(effect, (ast.GainAbilityText, ast.BecomeColor)):
        return True
    return isinstance(effect, ast.Pump) and "additional" in {
        token.text.lower() for token in stream.tokens
    }


def _parse_static_condition_line(stream: TokenStream) -> ast.StaticAbilityNode | None:
    """``<continuous effect> as long as <condition>.`` (CR 613, Sedge Troll,
    Kird Ape, Giant Tortoise.)

    The condition lands on :class:`ast.StaticAbilityNode` rather than becoming
    an ``ast.Conditional``, and the distinction is the whole content of the
    sentence. A ``Conditional`` lowers to ``if_then``: tested once, and if it
    holds the effect happens and then stays. "As long as" says the bonus exists
    exactly while the condition does — it appears and disappears with the
    Swamp. Reading one as the other gives a Kird Ape that keeps +1/+2 after its
    Forest is destroyed.

    Nothing here lowers. ``lower_ability`` refuses every ``StaticAbilityNode``
    until the CR 613 layers engine exists (roadmap phase 6), and the engine
    keeps running these cards off the compiler's static-line path exactly as it
    did. What the production buys is a backlog that points at the right thing —
    the lines move out of "unconsumed text", which reads as a parser gap, into
    the phase they are actually waiting on — plus an AST for phase 6 to lower
    instead of a sentence to re-read.

    Every one of the three gates below can only *reduce* what this claims: an
    unmodelled condition, a token left over, or an effect that is not
    continuous all send the line back to the ordinary path untouched.
    """
    mark = stream.mark()
    try:
        statement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("as", "long", "as"):
        unless = _parse_static_unless(stream, statement)
        if unless is None:
            stream.reset(mark)
        return unless
    # "…**as long as it's not attacking**" over a distributive subject
    # (Arcades Sabboth). Tried first, and only for that subject, because the two
    # readings of "it" differ: over "each creature you control" it is a member
    # of the set and the clause narrows the noun phrase, while over "this
    # creature" it is the source and the clause is an ordinary state condition
    # (Giant Tortoise), which `_parse_condition` below already reads. Folding it
    # into the filter is what keeps the answer per-creature — as a condition it
    # would be asked once, of the source.
    narrowed = _narrow_by_member_state(stream, statement)
    if narrowed is not None:
        stream.accept_punct(".")
        if stream.exhausted and _looks_static(narrowed):
            return ast.StaticAbilityNode(narrowed, None)
        stream.reset(mark)
        return None
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    otherwise = _accept_static_otherwise(stream, statement)
    if not stream.exhausted or not _looks_static(statement):
        stream.reset(mark)
        return None
    if otherwise is not None and not _looks_static(otherwise):
        # The complement has to be the same *kind* of thing as the arm it
        # complements. A one-shot in the second sentence would be an effect
        # happening once beside one that applies continuously, and no card
        # prints that — so the line goes back to the ordinary path rather than
        # being claimed and half-read.
        stream.reset(mark)
        return None
    # A fourth reducing gate, in the spirit of the three above: a condition
    # narrowed to "**of the chosen color**" (Jihad) reads a colour recorded on
    # the *source permanent* as it entered (CR 614.1c). Nothing a continuous
    # buff's condition is evaluated by can see that — the answer belongs to one
    # permanent's metadata, not to a board — and `engine/lord_buffs.py`
    # implements this exact sentence through `chosen_color_permanent`. So the
    # production declines the line rather than claiming it and refusing a layer
    # later, which is the one failure the derivation-table fallback cannot
    # recover from: `parse_line` reaches the tables only on a *parse* refusal.
    if getattr(getattr(condition, "filter", None), "chosen_color", False):
        stream.reset(mark)
        return None
    return ast.StaticAbilityNode(statement, condition, otherwise=otherwise)


def _parse_static_unless(
    stream: TokenStream, statement: ast.Statement
) -> ast.StaticAbilityNode | None:
    """``<continuous P/T bonus> unless <condition>.``

    "Enchanted creature gets +3/+3 **unless** it shares a color with the most
    common color among all permanents or a color tied for most common."
    (Heroic Defiance.) "As long as" with the polarity printed the other way
    round: the bonus exists exactly while the condition is *false*. The
    sentence loop reads the same word after a one-shot as an ``ast.Conditional``
    — tested once as the effect resolves — and reading this line that way gives
    an Aura whose +3/+3 is decided the moment it is cast and never again.

    **A durationless pump and nothing else**, which is the ordering rule rather
    than caution. "This creature can't attack unless defending player controls
    an Island" and its whole family are read by ``engine/combat_restrictions``
    as a table, reached only where every production refuses the line in full;
    a production that took any static statement behind "unless" would parse
    those sentences and take the table's lines away. A bonus to power and
    toughness is the one shape no table reads behind this word.

    Returns None on anything else; the caller rewinds.
    """
    if not (isinstance(statement, ast.Pump) and _looks_static(statement)):
        return None
    if not stream.accept_word("unless"):
        return None
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        return None
    stream.accept_punct(".")
    if not stream.exhausted:
        return None
    return ast.StaticAbilityNode(statement, condition, unless=True)


def _accept_static_otherwise(
    stream: TokenStream, statement: ast.Statement
) -> ast.Statement | None:
    """``Otherwise, <continuous effect>.`` after an "as long as" sentence.

    "Enchanted creature gets +2/+1 as long as it's black. **Otherwise, it gets
    -1/-2.**" (Phyrexian Boon.) Two continuous effects with complementary
    criteria (CR 613.1), printed as two sentences on one line.

    Deliberately **not** ``control_flow._attach_otherwise``, which is the same
    printed word on a one-shot: that one hangs a branch off an
    ``ast.Conditional`` whose condition is tested once as the spell resolves.
    Here nothing resolves — the criteria are re-asked on every recompute
    (CR 611.3b), and the arm that applies changes the moment the creature does.
    One word, two sentences, and the difference is which node it lands on.

    Returns None and consumes nothing when the word is absent, so every line
    that parsed before this existed parses identically.
    """
    mark = stream.mark()
    if not stream.accept_word("otherwise"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    try:
        arm = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    return _rebind_otherwise_subject(arm, statement)


def _rebind_otherwise_subject(
    arm: ast.Statement, statement: ast.Statement
) -> ast.Statement:
    """*arm* with its "it" pointed at whatever the first sentence was about.

    "**Enchanted creature** gets +2/+1 as long as it's black. Otherwise, **it**
    gets -1/-2." The pronoun opening the second sentence names the subject of
    the first, and the parser has no way to know that on its own: a bare "it"
    reads as the ability's own source, so Phyrexian Boon's penalty arm arrived
    pointing at the **Aura** — a permanent with no power or toughness at all.
    Left alone it would have lowered to a -1/-2 on nothing, on a card reporting
    supported.

    The same substitution ``rebinding.rebind_pronoun_to_condition_target``
    performs for a one-shot's arms, with the referent taken from the sentence
    rather than from a targeting condition: an "as long as" clause chooses
    nothing (CR 613.1), so there is no target to inherit and the subject is the
    only referent there is.

    A second sentence that names its subject outright keeps it. Only the
    pronoun is rewritten, so a printing whose arms are about different
    permanents still reaches the lowering with both subjects intact — and is
    refused there rather than silently merged.
    """
    subject = getattr(statement, "subject", None)
    arm_subject = getattr(arm, "subject", None)
    if not isinstance(subject, ast.TargetSpec) or not isinstance(
        arm_subject, ast.TargetSpec
    ):
        return arm
    if arm_subject.quantifier not in ("it", "this") or not arm_subject.filter.is_source:
        return arm
    return replace(arm, subject=subject)


def _distributive_subject(statement: ast.Statement) -> ast.TargetSpec | None:
    """The one ``all``/``each`` subject *statement* is about, or None.

    None for a conjunction whose halves disagree, for a targeted or singular
    subject, and for anything with no subject at all — every case where "it" in
    a trailing clause does not name a member of a described set.
    """
    effects = statement.effects if isinstance(statement, ast.Conjunction) else (statement,)
    if not effects:
        return None
    subjects = {getattr(effect, "subject", None) for effect in effects}
    if len(subjects) != 1:
        return None
    subject = subjects.pop()
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier not in ("all", "each"):
        return None
    return subject


def accept_member_state_clause(stream: TokenStream) -> tuple[str, bool] | None:
    """``it's [not] <state>`` — the ``(ObjectFilter field, value)`` it names.

    The trailing half of "Each untapped creature you control gets +0/+2 **as
    long as it's not attacking**" (Arcades Sabboth). "It" is a member of the set
    the sentence already described, so what the clause states is one more
    adjective on that noun phrase — which is why this returns a filter field
    rather than an :class:`ast.Condition`. Read as a condition it would ask the
    question of the ability's *source*, and Arcades would hand its whole team
    +0/+2 whenever Arcades itself stayed home.

    The state vocabulary is ``nouns._STATE_ADJECTIVES``, the same table the
    *leading* adjectives are read from, so "attacking" cannot mean one field
    here and another in front of the noun. The negation is a word read in front
    of the adjective rather than rows of its own, because Magic prints "not
    <adjective>" for every one of them.

    Returns None with the cursor where it was when the clause is not this.
    """
    mark = stream.mark()
    if not stream.accept_word("it"):
        stream.reset(mark)
        return None
    # The lexer splits the contraction, so "it's" and "it is" are the same two
    # tokens with a different second one — both copulas are accepted here for
    # the reason `conditions._parse_single_condition` accepts both.
    if not (stream.accept_word("'s") or stream.accept_word("is")):
        stream.reset(mark)
        return None
    negated = bool(stream.accept_word("not"))
    word = stream.peek_word()
    state = _STATE_ADJECTIVES.get(word) if word else None
    if state is None:
        stream.reset(mark)
        return None
    stream.advance()
    field_name, value = state
    return field_name, (not value) if negated else value


def _narrow_by_member_state(
    stream: TokenStream, statement: ast.Statement
) -> ast.Statement | None:
    """*statement* with a trailing ``it's [not] <state>`` folded into its
    subject, or None when the clause is not there or the subject is not a set.

    Refuses when the noun phrase already states the field — "each attacking
    creature … as long as it's not attacking" describes nothing, and silently
    letting the later word win would be a set the card never printed.
    """
    subject = _distributive_subject(statement)
    if subject is None:
        return None
    state = accept_member_state_clause(stream)
    if state is None:
        return None
    field_name, value = state
    if getattr(subject.filter, field_name) is not None:
        return None
    narrowed = replace(
        subject, filter=replace(subject.filter, **{field_name: value})
    )
    effects = statement.effects if isinstance(statement, ast.Conjunction) else (statement,)
    rebuilt = tuple(replace(effect, subject=narrowed) for effect in effects)
    return ast.Conjunction(rebuilt) if isinstance(statement, ast.Conjunction) else rebuilt[0]
