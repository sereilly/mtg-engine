"""The trailing clauses that share a sentence's printed subject.

``<subject> <verb> … **and** <second verb> …`` — one noun phrase printed once
and two things said about it. "{R}{R}: This creature gets +2/+0 until end of
turn **and deals 1 damage to you**" (Electric Eel); "{U}: This creature gains
shroud until end of turn **and doesn't untap during your next untap step**"
(Deep Spawn, Homarid Warrior).

Split out of `subject_verb` at the thousand-line guard, along a boundary that
module already had in its own shape: everything else in it reads a sentence's
*opening* — a subject, then the verb it dispatches on — and these two read what
is joined onto the end of one. A family rather than an arbitrary cut, and the
family is defined by the thing that makes these productions necessary at all:
each one joins two **effect families** that may not import each other. A pump
production may not reach a damage production, and a keyword-grant production
may not reach the untap restriction, so the join can only live above both — and
above both is here, one layer under the module that already calls each.

Below `subject_verb`, and it imports nothing from it: a joiner is handed the
statement its caller has already parsed, exactly as `delayed` is handed
`parse_statement`.
"""

from . import ast
from .errors import GrammarError
from .stream import TokenStream
from .effects import (_parse_attacks_this_turn_if_able, _parse_becomes,
                      _parse_damage, _parse_doesnt_untap_next_step,
                      _parse_loses)


def _with_damage_conjunct(
    stream: TokenStream,
    statement: ast.Statement,
    source: "ast.TargetSpec | None",
) -> ast.Statement:
    """``… and deals N damage to <recipient>`` trailing a clause whose subject
    is a permanent.

    "{R}{R}: This creature gets +2/+0 until end of turn **and deals 1 damage to
    you**." (Electric Eel; Wormwood Treefolk prints the same tail behind "gains
    forestwalk until end of turn".) The subject is printed once and does two
    things, and the damage is dealt *by* it — so *source* is the same noun
    phrase the pump acted on rather than a second reading of it.

    Read here rather than inside `_parse_gets` and `_parse_gains` because
    `effects/characteristics.py` may not import `effects/damage.py`: the effect
    families are independent by test, and a pump production that could reach a
    damage production would make the grouping stop being information. This
    module is above both and already calls each, which is the layer the join
    belongs at.

    Not the sentence loop's job either. That loop joins a subjectless tail only
    when the carried subject is a *player*, so a creature carried into "deals"
    would read a sentence nobody printed — and the clause would be unconsumed
    text that takes the whole line down. That is the argument `_parse_gets`
    already makes for reading "and gains …" itself, applied to the other verb
    the same cards print.

    Once "and deals" has been seen the sentence is a damage clause and nothing
    else, so a failure inside it raises rather than rewinding: a rewind would
    leave the clause unread and blame the pump for it.
    """
    if source is None:
        return statement
    mark = stream.mark()
    if not stream.accept_word("and"):
        stream.reset(mark)
        return statement
    if not stream.at_word("deals", "deal"):
        stream.reset(mark)
        return statement
    return ast.Conjunction((statement, _parse_damage(stream, source)))


def _with_untap_conjunct(
    stream: TokenStream,
    statement: ast.Statement,
    source: "ast.TargetSpec | None",
) -> ast.Statement:
    """``… and doesn't untap during <possessive> next untap step`` trailing a
    clause whose subject is a permanent.

    "{U}: This creature gains shroud until end of turn **and doesn't untap
    during your next untap step**." (Deep Spawn, Homarid Warrior.) The subject
    is printed once and two things are said about it, exactly as in
    :func:`_with_damage_conjunct` — and here for that function's own reason:
    ``effects/characteristics.py`` may not import ``effects/tapping.py``, the
    families are independent by test, and this module is above both and already
    calls each.

    Not the sentence loop's job either, and for a sharper version of the same
    argument: the loop joins on full stops, and this clause is joined by "and"
    inside one sentence. Left unread it is unconsumed text that refuses the
    whole line.

    The auxiliary alone is not enough to commit — "gains flying **and can't be
    blocked**" opens the same way with a different word behind it — so the verb
    is checked before dispatching, which is the discipline the "don't untap"
    branch of :func:`parse_subject_verb` already states.
    """
    if source is None:
        return statement
    mark = stream.mark()
    if not stream.accept_word("and"):
        stream.reset(mark)
        return statement
    if not (
        stream.at_word("don't", "doesn't") and stream.peek_word(1) == "untap"
    ):
        stream.reset(mark)
        return statement
    return ast.Conjunction(
        (statement, _parse_doesnt_untap_next_step(stream, source))
    )


def _with_attack_conjunct(
    stream: TokenStream,
    statement: ast.Statement,
    source: "ast.TargetSpec | None",
) -> ast.Statement:
    """``… and attacks this turn if able`` trailing a clause whose subject is a
    permanent.

    "At the beginning of your upkeep, …, this creature deals 3 damage to you
    **and attacks this turn if able**." (Kookus.) The third tail this module
    reads and the same shape as the two above: one noun phrase printed once,
    two things said about it, joined across two effect families that may not
    import each other — ``effects/damage.py`` and ``effects/combat.py``.

    The verb alone is not enough to commit, exactly as the untap joiner's
    auxiliary is not: "and attacks" opens a condition ("and attacks each combat
    if able" is a printed static) as well as this clause, so the production is
    asked and its refusal rewinds the "and" with it.
    """
    if source is None:
        return statement
    mark = stream.mark()
    if not stream.accept_word("and"):
        stream.reset(mark)
        return statement
    joined = _parse_attacks_this_turn_if_able(stream, source)
    if joined is None:
        stream.reset(mark)
        return statement
    return ast.Conjunction((statement, joined))


def _with_keyword_loss_conjunct(
    stream: TokenStream,
    statement: ast.Statement,
    source: "ast.TargetSpec | None",
) -> ast.Statement:
    """``… and loses <keyword>`` trailing a clause whose subject is a permanent.

    "{2}: Until end of turn, this artifact becomes a 3/2 Construct artifact
    creature **and loses flying**." (Chimeric Sphere.) The fourth tail this
    module reads, and the same shape as the three above: one noun phrase
    printed once, two things said about it, joined across two effect families
    that may not import each other — ``effects/types.py`` and
    ``effects/characteristics.py``.

    The card is why the clause exists at all rather than being redundant: the
    Sphere's *other* ability animates it **with** flying, so the second body has
    to take the keyword back off a permanent the first one gave it to. CR 613
    layer 6 answers that by timestamp, so the removal is a real effect and not a
    restatement of the default.

    The verb alone is not enough to commit, exactly as the untap joiner's
    auxiliary is not: `_parse_loses` reads life and "loses the game" as well as
    keywords, and a subject that is a permanent cannot do either — so the
    production is asked and its refusal rewinds the "and" with it, leaving every
    other "and loses …" the reading it had.
    """
    if source is None:
        return statement
    mark = stream.mark()
    if not stream.accept_word("and"):
        stream.reset(mark)
        return statement
    if not stream.at_word("loses", "lose"):
        stream.reset(mark)
        return statement
    try:
        joined = _parse_loses(stream, source)
    except GrammarError:
        stream.reset(mark)
        return statement
    if not isinstance(joined, ast.LoseKeyword):
        # A life loss or a loss of the game read off a permanent's noun phrase
        # is not this sentence; rewinding leaves the clause to whatever else
        # can read it rather than joining a statement about the wrong subject.
        stream.reset(mark)
        return statement
    return ast.Conjunction((statement, joined))


def _with_gained_type_conjunct(
    stream: TokenStream,
    statement: ast.Statement,
    source: "ast.TargetSpec | None",
) -> ast.Statement:
    """``… and becomes <type> in addition to its other types`` trailing a clause
    whose subject is a permanent.

    "{2}: Until end of turn, target nonartifact creature gets +1/+0 **and
    becomes an artifact in addition to its other types**." (Thran Forge.) The
    mirror of :func:`_with_keyword_loss_conjunct` above — that one joins a type
    change to a keyword loss, this one joins a P/T change to a type change — and
    here for the same reason: ``effects/characteristics.py`` may not import
    ``effects/types.py``.

    `_parse_becomes` raises rather than rewinding on a body it cannot read, so
    the refusal is caught and the "and" put back: "gets +1/+1 and becomes
    blocked" is a sentence for somebody else, and a clause half-read here would
    take the whole line down with a message about the wrong verb.
    """
    if source is None:
        return statement
    mark = stream.mark()
    if not stream.accept_word("and"):
        stream.reset(mark)
        return statement
    if not stream.at_word("becomes", "become"):
        stream.reset(mark)
        return statement
    try:
        joined = _parse_becomes(stream, source)
    except GrammarError:
        stream.reset(mark)
        return statement
    return ast.Conjunction((statement, joined))
