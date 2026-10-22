"""What an attached Aura gives its host, derived rather than remembered.

The continuous effects of an Aura or an Equipment while it is attached
(CR 611.3a, 613): the P/T it grants (layer 7c), the keywords, quoted abilities
and conditional grants it gives or takes away (layer 6), the types, colours and
protection it adds (layers 4 to 6), the artifact or land it animates, the
control it takes (layer 2), and the attached-only effects that are not
characteristics at all: a reduction to the host's activation costs, a damage
redirect, a chosen landwalk. Each is read off the Aura's own text on every
recompute, by the pattern the support gate claims the line with, so there is
no delta to subtract when the Aura leaves. The contribution simply stops being
derived.

Split out of ``engine/auras.py`` at the 2,000-line cap. The layer bridge and
the permanent-state mixin read these, and ``engine/auras.py``'s
``aura_continuous_claim`` claims each line through the reader that applies it.
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import fast_paths
from .late_modules import LateModules
from .aura_attachment import auras_attached_to
from .aura_restrictions import (
    _KEYWORD_GRANT_AND_RESTRICTION,
    aura_restrictions,
    aura_combat_restriction,
)
from .aura_vocabulary import (
    _NOUN,
    _ATTACHED,
    _COLORS,
    _PROTECTION_QUALITIES,
    _LazyPattern,
    _TYPE_ADDITION_GRANT,
    _CREATURE_TYPE_SET,
    _line_text,
    _keyword_alternation,
)


# Modules loaded after this one, read on every recompute and every
# ``effective_card`` read of an enchanted permanent — so through a binding
# made once rather than a function-level import run on every call, and not
# at the top, which would change the package's load order
# (``engine/late_modules.py``).
_late = LateModules(__package__)
_late_grammar = LateModules(f"{__package__}.grammar")


# ---------------------------------------------------------------------------
# The static P/T an Aura grants, derived rather than remembered
# ---------------------------------------------------------------------------

# "Enchanted creature gets +2/+2." The grant is a property of the Aura's text,
# so it can be recomputed from the Aura at any time. It used to be applied once
# into the enchanted permanent's `power_bonus` with the delta recorded on the
# Aura and subtracted again on removal (CR 611.3) — the shape that shipped the
# Aspect of Wolf compounding bug.
#
# "+N/+N until end of turn" is deliberately excluded: that comes from an
# *activated* ability the Aura grants (Firebreathing, Blessing) and applies when
# the ability is activated, not while the Aura is attached.
_STATIC_PT_GRANT = re.compile(r"gets ([+-]\d+)/([+-]\d+)(?! until end of turn)")

#: "…gets +1/+1 **for each soul counter on this Equipment**." (Malefic Scythe.)
#: The multiplier is the whole card: read as a flat grant the Scythe is a
#: permanent +1/+1 whose counters do nothing, which is what it was. Its own
#: pattern rather than a tail on the one above, because the two produce
#: different *kinds* of answer — a number, and a number per counter.
_PT_GRANT_PER_COUNTER = re.compile(
    r"gets ([+-]\d+)/([+-]\d+) for each (?P<counter>[a-z]+) counter on "
    r"(?:this|~)\b"
)


def aura_pt_grant_per_counter(oracle_text: str) -> tuple[int, int, str] | None:
    """``(power, toughness, counter name)`` for a per-counter grant, or None.

    Read before the flat grant everywhere both are asked, because the flat
    pattern matches this line's prefix: "gets +1/+1" is true of "gets +1/+1 for
    each soul counter", and answering the prefix is a card whose counters are
    decoration.
    """
    for raw_line in oracle_text.splitlines():
        match = _PT_GRANT_PER_COUNTER.search(_line_text(raw_line))
        if match is not None:
            return int(match.group(1)), int(match.group(2)), match.group("counter")
    return None


#: A line that is **not** a static ability, however much of one its middle
#: looks like. A continuous grant is derived from an Aura's text on every
#: recompute, so it may only be read off a line that is continuously true: a
#: triggered ability's effect is a one-shot (CR 603.1) and an activated
#: ability's is spent when it resolves (CR 602.1), and reading either as a
#: static grant applies it *before the ability has done anything* and never
#: stops.
#:
#: Bestial Fury is the card. "Whenever enchanted creature becomes blocked, it
#: gets +4/+0 and gains trample until end of turn" was read here as a permanent
#: +4/+0: the enchanted creature got it the moment the Aura attached, kept it
#: through the opponent's turns, and got a *second* +4/+0 on top whenever it was
#: actually blocked. The trample half was correct — the keyword reader below
#: takes only whole "…has <keyword>" lines — so one printed sentence had one
#: half continuous and one half not, which is the shape that makes this kind of
#: bug invisible in a game.
_NON_STATIC_LINE = re.compile(r"^(?:when|whenever|at the beginning|at end of)\b")


def _static_ability_line(line: str) -> bool:
    """Whether *line* is a static ability, and so may be read as a continuous
    grant at all.

    An activated ability is caught by the colon its cost ends at (CR 602.1),
    which is the same delimiter ``_parse_activated_ability`` splits on — asked
    here as the shape rather than by calling that parser, because the question
    is only "is there a cost in front of this", and a line whose *effect* the
    compiler cannot read is still not a static ability.
    """
    if _NON_STATIC_LINE.match(line):
        return False
    return ":" not in line.split(" gets ")[0]


def aura_static_pt_grant(oracle_text: str) -> tuple[int, int] | None:
    """The permanent +P/+T an Aura grants while attached, or None.

    Derived from the Aura's own text on every recompute, so detaching it is
    simply ceasing to contribute — there is nothing to subtract, and nothing
    that can drift out of step with what was added.
    """
    # A per-counter grant is a different answer to a question this function only
    # knows how to answer with a constant, and its line starts the same way — so
    # it is declined here rather than reported as the flat grant it is not.
    if aura_pt_grant_per_counter(oracle_text) is not None:
        return None
    for raw_line in oracle_text.splitlines():
        line = _line_text(raw_line)
        match = _STATIC_PT_GRANT.search(line)
        if match is None:
            continue
        # Only a static ability grants continuously — see `_NON_STATIC_LINE`.
        if not _static_ability_line(line):
            continue
        tail = line[match.end():].lstrip()
        # The duration, wherever in the tail it is printed. `_STATIC_PT_GRANT`'s
        # own lookahead and this check both used to require it immediately after
        # the numbers, so "gets +4/+0 **and gains trample** until end of turn"
        # slipped between them and was read as permanent. Two readers of one
        # clause, and the sentence only has to put a word between them to defeat
        # both.
        #
        # **Outside any quoted ability**, which is a different ability's text:
        # 'Enchanted creature gets -1/-1 and has "{T}: Target creature gets
        # -1/-1 **until end of turn**."' (Foul Presence.) The duration there
        # belongs to the ability the host is granted, and read as this grant's
        # own it made the Aura's -1/-1 vanish — the card reported supported,
        # the host kept its printed size, and a 1/1 it enchanted lived.
        if "until end of turn" in tail.split('"', 1)[0]:
            continue
        # "…gets +2/+2 **as long as an opponent controls a black permanent**"
        # (Ice Age's five Scarabs), and "for as long as this artifact remains
        # tapped". A conditional grant is not a flat one, and this pattern
        # matches the prefix of both — so answering here would attach the bonus
        # unconditionally, which is the condition-dropping bug the per-counter
        # decline above exists for. The conditional grant lowers to a
        # ``conditional_static`` instruction instead (grammar/statics.py) and
        # the P/T refresh asks the condition on every recompute.
        #
        # **Wherever on the line the condition is printed**, outside any quoted
        # ability — the lesson the duration check above already paid for. This
        # asked only the words straight after the numbers, so "gets +1/+1
        # **and can't block** as long as …" and the fronted "As long as …,
        # enchanted creature gets +1/+1 …" both slipped past it. No card
        # printed either while the grammar could not read them, and the round
        # that taught it to (Odyssey's threshold grants,
        # ``static_lines._parse_conditional_grant_line``) would have made each
        # a +1/+1 from here *on top of* the conditional one. Two readers of one
        # clause again, and a word between them again.
        if re.search(
            r"\bas long as\b", (line[:match.start()] + tail).split('"', 1)[0]
        ):
            continue
        # "…gets +3/+3 **unless it shares a color with the most common color**
        # …" (Heroic Defiance). "As long as" with the polarity printed the
        # other way round, and the same decline for the same reason: the line
        # lowers to a ``conditional_static`` whose complement arm carries the
        # delta, so answering the prefix here grants a flat +3/+3 on top of it
        # — the bonus the card says it does *not* give is given, and the one it
        # does give is doubled.
        if re.match(r"unless\b", tail):
            continue
        # "...gets +1/+1 **for each other creature you control**" (Vampirism).
        # A *counted* grant, which is a different kind of answer from the
        # constant this function knows how to give - and this pattern matches
        # its prefix, so answering here would grant a flat +1/+1 **on top of**
        # the count the layer-7c refresh already contributes from the
        # ``dynamic_pt_bonus`` the line lowers to: the enchanted creature came
        # out one point too big in each half.
        #
        # The same decline ``aura_pt_grant_per_counter`` gets at the top of this
        # function, widened from the one multiplier that had a card to the
        # printed clause itself. "For each" says the size is a count, whatever
        # is counted, and a multiplier this reader cannot see is one it must not
        # answer past.
        if re.match(r"for each\b", tail):
            continue
        return int(match.group(1)), int(match.group(2))
    return None


#: Snowblind: "Enchanted creature gets -X/-Y. If that creature is attacking, X
#: is the number of snow lands defending player controls. Otherwise, X is the
#: number of snow lands its controller controls. Y is equal to X or to enchanted
#: creature's toughness minus 1, whichever is smaller."
#:
#: Four sentences, one effect, and every one of them is load-bearing: the count,
#: the two boards it can be counted on, and the clamp. Matched together for the
#: reason ``_ABILITY_COST_REDUCTION`` above matches its pair together — the
#: clamp without the count modifies nothing, and the count without the clamp is
#: a card that kills what it enchants.
#:
#: The counted noun is payload, read by the grammar's own noun parser rather
#: than spelled here, so "snow lands" means on this card what it means on every
#: other line in the engine. The repeated phrase must be the *same* phrase: a
#: card counting two different things is not this sentence, and reading only
#: the first would give the second board the wrong count.
def _build_board_counted_penalty() -> re.Pattern[str]:
    return re.compile(
        r"^enchanted creature gets -x/-y\. "
        r"if that creature is attacking, x is the number of (?P<attacking>.+?) "
        r"defending player controls\. "
        r"otherwise, x is the number of (?P<otherwise>.+?) its controller "
        r"controls\. y is equal to x or to enchanted creature's toughness "
        r"minus 1, whichever is smaller$"
    )


_BOARD_COUNTED_PENALTY = _LazyPattern(_build_board_counted_penalty)


def aura_board_counted_penalty(oracle_text: str) -> dict | None:
    """The payload of Snowblind's clamped, board-counted penalty, or None.

    ``{"filter": <noun-phrase payload>}`` — what to count. Whose board it is
    counted on is not payload: the sentence says, and the answer changes with
    the combat, so it is asked at every recompute by
    ``dynamic_creatures._refresh_board_counted_penalties``.

    The noun phrase is refused unless ``subject_matches`` can test it, the same
    gate every other text-keyed table applies: a narrowing the matcher cannot
    answer would be dropped, and a dropped narrowing here counts *every land*
    rather than the snow ones.
    """
    for raw_line in (oracle_text or "").splitlines():
        match = _BOARD_COUNTED_PENALTY.match(_line_text(raw_line))
        if match is None:
            continue
        from .grammar import subject_filter_payload
        from .subject_filters import untestable_filter_keys

        phrase = match.group("attacking").strip()
        if phrase != match.group("otherwise").strip():
            return None
        described = subject_filter_payload(phrase, plural=True)
        if not described or untestable_filter_keys(described):
            return None
        return {"filter": described}
    return None


def aura_board_counted_penalty_sentences(oracle_text: str) -> tuple[str, ...]:
    """The sentences :func:`aura_board_counted_penalty` reads, or empty.

    Snowblind's effect is **four sentences on one printed line** and none of
    them means anything alone: the penalty, the two boards it can be counted on,
    and the clamp. So the reader matches them joined, and this names the run for
    a caller that walks a card sentence by sentence
    (``scripts/parse_coverage.py``) and would otherwise report all four as text
    nothing read. The same pairing :func:`aura_cost_reduction_sentences` keeps
    for Power Artifact, which is the other reader shaped this way.
    """
    if aura_board_counted_penalty(oracle_text) is None:
        return ()
    for raw_line in (oracle_text or "").splitlines():
        line = _line_text(raw_line)
        if _BOARD_COUNTED_PENALTY.match(line) is None:
            continue
        return tuple(
            sentence.strip() for sentence in line.split(". ") if sentence.strip()
        )
    return ()

# "Enchanted creature gets +1/+0 and has flying **and first strike**" (Wings of
# Aesthir). The grant is a *list*: CR 702 keywords are independent abilities and
# a card printing two grants two, so reading only the first would ship an Aura
# giving half of what it prints — silently, since the line still matches. The
# splitting is `_keyword_list` below, which refuses a run it cannot read whole
# rather than keeping the part it understood.
_KEYWORD_GRANT = _LazyPattern(lambda: re.compile(
    rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? has "
    rf"(?P<keyword>(?:{_keyword_alternation()})"
    rf"(?:(?:, and |, | and )(?:{_keyword_alternation()}))*)$"
))


#: "Enchanted creature **loses** flying." (Mammoth Harness.) The exact mirror of
#: ``_KEYWORD_GRANT``, in the same layer and built out of the same alternation —
#: which is the point: a word the Aura may grant is a word it may take away, and
#: two vocabularies would let one of them drift. The optional P/T prefix is the
#: same split every other pattern in this file makes, so "gets +2/+2 and loses
#: flying" is one line read into two channels rather than a line matching
#: nothing.
#:
#: Its own pattern rather than an optional verb inside the grant's, because the
#: two are **opposite contributions to one layer** (CR 613.4/613.9) and the
#: consumer has to be able to tell them apart: folded together, "loses flying"
#: would come back through ``aura_keyword_grants`` and hand the host the very
#: ability the Aura removes. The same reason ``lord_buffs.LordBuff`` keeps
#: ``lost_keywords`` beside ``keywords`` instead of signing one list.
_KEYWORD_REMOVAL = _LazyPattern(lambda: re.compile(
    rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? loses "
    rf"(?P<keyword>(?:{_keyword_alternation()})"
    rf"(?:(?:, and |, | and )(?:{_keyword_alternation()}))*)$"
))


_COMPOUND_INDESTRUCTIBLE = re.compile(
    rf"^enchanted {_NOUN} has indestructible and can't be enchanted by other auras$"
)

# "Enchanted creature has shroud as long as it's untapped." (Spectral Cloak.)
# The same layer-6 grant one line up with a condition on the attached
# permanent's own state — so the keyword is data, as it already was, and the
# state is data too: a card printing "…as long as it's tapped" is this rule read
# the other way and needs no code.
#
# "It" is the enchanted permanent, not the Aura. That is what the sentence
# means, and it is also the only reading with a consumer: the grant is derived
# on the *host* every recompute (`layer_bridge.collect_ability_effects`), which
# is where the state is known.
_CONDITIONAL_KEYWORD_GRANT = _LazyPattern(lambda: re.compile(
    rf"^{_ATTACHED} {_NOUN} has "
    rf"(?P<keyword>{_keyword_alternation()}) "
    r"as long as it's (?P<state>untapped|tapped)$"
))


def aura_conditional_keyword_grants(oracle_text: str) -> tuple[tuple[str, str], ...]:
    """``(keyword, state)`` pairs an Aura grants *while its host is in state*.

    Kept apart from :func:`aura_keyword_grants` rather than folded in with an
    optional condition, because the callers are different: the unconditional
    grant is a contribution the layer bridge always makes, and this one has to
    be asked of the host before it is made. A single list returning both would
    have the bridge granting a conditional keyword unconditionally the moment a
    caller forgot the second element.
    """
    grants: list[tuple[str, str]] = []
    for raw_line in (oracle_text or "").splitlines():
        match = _CONDITIONAL_KEYWORD_GRANT.match(_line_text(raw_line))
        if match is not None:
            grants.append((match.group("keyword"), match.group("state")))
    return tuple(grants)


def aura_conditional_grant_holds(permanent, state: str) -> bool:
    """Whether *permanent* is in *state* right now (CR 611.3a — asked on every
    recompute, never locked in when the Aura attached)."""
    return permanent.tapped if state == "tapped" else not permanent.tapped


# 'Enchanted land has "{T}: Counter target spell if it would destroy a land you
# control."' (Equinox.) A whole printed *ability*, not a keyword — so what the
# host gains is the line, and the compiler is what turns a line into an ability.
# The same channel a board-wide static's granted ability already travels on
# (`engine/global_statics.py`), for the same reason: nothing downstream of the
# compiler knows a word for "counter target spell if …".
#: The optional P/T prefix is the same split ``_KEYWORD_GRANT`` and the untap
#: restriction make, and it was missing here. Infernal Scarring prints
#: "Enchanted creature gets +2/+0 and has "When this creature dies, draw a
#: card."" — one line, two channels — and the anchored pattern matched neither
#: the whole line nor its tail, so the card reported supported, applied the
#: +2/+0, and granted **nothing**: the claim came from the P/T row of
#: ``_TEMPLATES``, which is checked first and says "and optional granted
#: keyword or ability" without asking whether anything grants one.
_QUOTED_ABILITY_GRANT = re.compile(
    rf'^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? has "(?P<ability>[^"]+)"$'
)


@lru_cache(maxsize=None)
def aura_quoted_grants(oracle_text: str) -> tuple[str, ...]:
    """Every ability *oracle_text* grants its host in quotes, **as printed** —
    whether or not the engine can read it.

    The half of :func:`aura_granted_ability_lines` that is a pure function of
    the text, for the reason ``_conditional_ability_grant_shapes`` is split
    from its own compile check: what the card *says* is cacheable here, and
    whether it compiles is ``granted_ability_supported``'s answer, held in a
    cache ``clear_compilation_caches`` knows about. It is also the reader a
    census wants — one that asked the filtered list below how many grants were
    unreadable would always be told none.
    """
    quotes: list[str] = []
    for raw_line in (oracle_text or "").splitlines():
        match = _QUOTED_ABILITY_GRANT.match(_line_text(raw_line))
        if match is not None:
            quotes.append(match.group("ability"))
    return tuple(quotes)


def quoted_grant_readable(quote: str, granter_name: str | None = None) -> bool:
    """Whether the host will be able to read *quote* once it is folded on.

    The one question both ends ask: the support gate
    (:func:`aura_effect_claim`), so an Aura whose quote the compiler refuses is
    not reported supported, and the fold (:func:`aura_granted_ability_lines`),
    so such a quote is never handed to a host. Bound first, because the quote
    is compiled on the *host* and the granter's own name means nothing there
    until ``bind_granter`` has said which object it is (CR 201.5a).
    """
    granted_abilities = _late.granted_abilities
    return granted_abilities.granted_ability_supported(
        granted_abilities.bind_granter(quote, granter_name)
    )


def aura_granted_ability_lines(
    oracle_text: str, *, granter_name: str | None = None,
    granter_id: int | None = None,
) -> tuple[str, ...]:
    """The printed ability lines an Aura grants the permanent it is attached to.

    **Derived, not recorded.** ``Permanent.effective_card`` asks this of every
    attachment on every read, so detaching the Aura takes the ability away with
    nothing to undo — CR 611.3b's "removal is the absence of a contribution",
    the arrangement every other continuous half of this file already uses.

    The claim table at the top of ``engine/auras.py`` named this behaviour and
    the code it named had been deleted, so Equinox's whole printed effect was a
    claim with nothing behind it: the card reported supported and the land it
    enchanted gained nothing at all.

    **Bound to the granter, and only what compiles.** *granter_name* and
    *granter_id* are the attached permanent's: a quote naming its own Aura
    ("…the number of arrow counters on Archery Training") is handed to the host
    naming that one object (``granted_abilities.bind_granter``). And a quote
    the compiler cannot read is not handed over at all — the host's rules text
    is compiled as a whole, so one unreadable line appended to a creature made
    the *creature* unsupported and took every ability it printed with it. A
    Prodigal Sorcerer wearing the unread Archery Training could not ping.
    """
    quotes = aura_quoted_grants(oracle_text or "")
    if not quotes:
        return ()
    granted_abilities = _late.granted_abilities
    bound_id = (
        granted_abilities.GRANTER_PROBE_ID if granter_id is None else granter_id
    )
    return tuple(
        granted_abilities.bind_granter(quote, granter_name, bound_id)
        for quote in quotes
        if quoted_grant_readable(quote, granter_name)
    )


# 'As long as enchanted permanent is red or green, it has "At the beginning of
# your upkeep, sacrifice this permanent unless you pay its mana cost."' (Essence
# Leak.) The quoted grant one pattern up with a **criterion on the host** in
# front of it — CR 613.1's "as long as", so the ability is there exactly while
# the host answers the description and is gone, with nothing to undo, the
# moment a Lace or a Sway of Illusion changes the answer (CR 611.3a).
#
# The criterion is captured as words and read by the grammar's **noun parser**
# (:func:`_host_criterion_filter`), not by a colour alternation here: "is red or
# green" is "is a red or green permanent", which is a phrase that parser already
# reads and ``subject_matches`` already tests through the layers. A regex of
# colour words would be a second reader of what a colour is, and would make
# "is tapped" or "is an artifact" on the next card a new pattern instead of the
# same one.
_CONDITIONAL_QUOTED_ABILITY_GRANT = re.compile(
    rf'^as long as {_ATTACHED} (?P<noun>{_NOUN}) is (?P<criterion>[a-z][a-z, \-]*), '
    r'it has "(?P<ability>[^"]+)"$'
)


def _host_criterion_filter(noun: str, criterion: str) -> dict | None:
    """The filter payload "<attached> *noun* is *criterion*" tests, or None.

    Built by handing the noun parser the phrase the clause abbreviates — "red or
    green" + "permanent" — so the criterion means what the same words mean in
    front of any noun in the engine. None when the parser cannot read it, when
    it reads past the phrase, when the result carries a key ``subject_matches``
    cannot test, or when the criterion added nothing to the bare noun: each of
    those is a condition that would be admitted and then not enforced, which
    for a granted *drawback* is the card doing more than it prints.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    def _described(phrase: str) -> dict | None:
        stream = TokenStream(tokenize(phrase).tokens)
        try:
            described = parse_object_filter(stream)
        except GrammarError:
            return None
        if not stream.exhausted:
            return None
        return described.to_payload()

    bare = _described(noun)
    narrowed = _described(f"{criterion} {noun}")
    if bare is None or narrowed is None or narrowed == bare:
        return None
    if untestable_filter_keys(narrowed):
        return None
    return narrowed


@lru_cache(maxsize=None)
def _conditional_ability_grant_shapes(oracle_text: str) -> tuple[tuple[tuple, str], ...]:
    """Every ``(criterion, quoted ability)`` *oracle_text* prints in the
    conditional-grant shape, whether or not the engine can read the quote.

    The half of :func:`aura_conditional_ability_grants` that is a pure function
    of the text, and the only half cached here: whether the quote **compiles**
    is ``granted_ability_supported``'s answer, held in a cache
    ``clear_compilation_caches`` knows about. Caching that answer a second time
    under this function would be a compiled answer in a cache nothing clears —
    the two-poisoned-keys failure ``oracle_types.compilation_cache`` exists for.

    The recompute asks this of every Aura on every pass, so the quick refusal
    is first and is what nearly every card takes.
    """
    text = oracle_text or ""
    if '"' not in text or "as long as" not in text.lower():
        return ()
    shapes: list[tuple[tuple, str]] = []
    for raw_line in text.splitlines():
        match = _CONDITIONAL_QUOTED_ABILITY_GRANT.match(_line_text(raw_line))
        if match is None:
            continue
        described = _host_criterion_filter(
            match.group("noun"), match.group("criterion").strip()
        )
        if described is not None:
            shapes.append((_freeze_filter(described), match.group("ability")))
    return tuple(shapes)


def aura_conditional_ability_grants(oracle_text: str) -> tuple[tuple[tuple, str], ...]:
    """``(criterion, ability line)`` pairs an Aura grants its host **while the
    host answers the criterion**.

    The criterion is a filter payload frozen as sorted items (the shapes are
    cached, and a shared dict would be one caller's mutation away from changing
    the card); :func:`conditional_ability_lines_for` thaws it.

    Kept apart from :func:`aura_granted_ability_lines` for the reason
    :func:`aura_conditional_keyword_grants` is kept apart from the keyword
    grants: that list is folded into ``Permanent.effective_card`` unconditionally
    and with no game in hand, so a conditional grant returned from it would be
    an unconditional one the moment a caller forgot the second element.

    A pair is returned only when **both** halves are implemented — the
    criterion is testable and the quote compiles
    (``granted_abilities.granted_ability_supported``) — so the support gate,
    which asks this function, cannot admit a line whose ability does nothing.
    """
    shapes = _conditional_ability_grant_shapes(oracle_text or "")
    if not shapes:
        return ()
    from .granted_abilities import granted_ability_supported

    return tuple(
        (criterion, ability)
        for criterion, ability in shapes
        if granted_ability_supported(ability)
    )


def _freeze_filter(described: dict) -> tuple:
    """*described* as hashable, order-stable items (lists become tuples)."""
    return tuple(
        (key, tuple(value) if isinstance(value, list) else value)
        for key, value in sorted(described.items())
    )


def conditional_ability_lines_for(game, aura, seat: int, host) -> tuple[str, ...]:
    """The quoted abilities *aura* grants *host* right now.

    Asked on every recompute by ``_recalculate_lord_buffs``, which owns the
    derived-ability channel's clear and rebuild — so the answer is never
    remembered, and the ability leaves with the Aura, with the criterion, or
    with either's text being changed (CR 611.3a/b).

    The criterion is tested through ``subject_matches``: the host's colour is
    CR 613 layer 5's answer, not its printed one. *seat* is the Aura's
    controller (CR 109.5), which is who a relative key would be measured from.
    """
    from .subject_filters import subject_matches

    lines: list[str] = []
    for frozen, ability in aura_conditional_ability_grants(
        aura.effective_card.oracle_text or ""
    ):
        described = {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in frozen
        }
        if subject_matches(game, host, described, observer=seat, source=aura):
            lines.append(ability)
    return tuple(lines)


def _keyword_list(run: str) -> list[str]:
    """The keywords a printed run names — "flying and first strike", "flying,
    first strike, and trample".

    Only words the alternation admitted can be here, because the pattern that
    captured this run was built from that alternation; the split is therefore
    a split and not a second vocabulary.
    """
    return [part.strip() for part in re.split(r",| and ", run) if part.strip()]


def aura_keyword_grants(oracle_text: str) -> tuple[str, ...]:
    """Keyword abilities an Aura grants to the permanent it enchants.

    Only whole-line grants of a known keyword count. "Enchanted creature has
    protection from black. This effect doesn't remove this Aura." and
    'Enchanted land has "…"' are deliberately not matched: protection is a
    metadata channel with its own checks, and a granted *quoted* ability is not
    a keyword — claiming either here would say the layer-6 grant carries them
    when it does not.
    """
    grants: list[str] = []
    for raw_line in oracle_text.split("\n"):
        line = _line_text(raw_line)
        match = _KEYWORD_GRANT.match(line) or _TYPE_ADDITION_GRANT.match(line)
        if match is not None:
            grants.extend(_keyword_list(match.group("keyword")))
        elif (
            (compound := _KEYWORD_GRANT_AND_RESTRICTION.match(line)) is not None
            # …and only when the restriction half **has** a reader. The
            # pattern's own note says a tail the table cannot read "leaves the
            # whole line unmatched", and nothing made that true: "has flying
            # and can't block **as long as …**" matched, granted flying for
            # good and dropped the restriction with its condition, on a card
            # reporting supported. No printing reached it; asked now, the
            # keyword is not granted and the line is left to a reader of the
            # whole sentence. Either reader counts: the combat table, or the
            # attached-restriction one Consecrate Land's "can't be enchanted
            # by other Auras" is read by.
            and (
                aura_combat_restriction(raw_line) is not None
                or aura_restrictions(raw_line)
            )
        ):
            # "…has phasing and can't be blocked except by Walls." The keyword
            # half only; the restriction half is claimed by
            # :func:`aura_combat_restriction` off the same line, exactly as
            # Consecrate Land's compound below splits between two readers.
            grants.extend(_keyword_list(compound.group("keyword")))
        elif _COMPOUND_INDESTRUCTIBLE.match(line):
            # Consecrate Land prints one line carrying two effects. Its trailing
            # clause is claimed separately as a restriction, so matching only
            # the keyword half here drops nothing — which is the whole reason
            # the compound is spelled out rather than matched loosely.
            grants.append("indestructible")
    return tuple(grants)


def aura_granted_line_derived_lines(oracle_text: str) -> tuple[str, ...]:
    """The printed **lines** an Aura's keyword grant has to be turned into.

    A keyword grant is normally one word into CR 613 layer 6's ability set, and
    every reader of "does it have flying?" looks there. That is no use for a
    keyword the CR *defines* as an ability rather than describing one: the
    compiler built rampage and flanking out of a printed line before layer 6
    existed for this permanent, so a word in the ability set grants the word and
    not the trigger. Agility is the card that shows it — "Enchanted creature
    gets +1/+1 and **has flanking**" made its host count as a flanker for the
    next flanker's filter and gave it no ability at all.

    So the grant of such a keyword is a grant of the *line*, exactly as
    ``keywords.LINE_DERIVED_KEYWORDS`` already says for the one-shot path
    (`handlers/keywords._grant_one_keyword`) — this is that same rule on the
    continuous path, derived per read like every other half of this file so
    detaching the Aura takes the ability away with nothing to undo. The word
    comes back for free: ``layer_bridge._TEXT_KEYWORDS`` scans the compiled
    keyword lines, so the appended line puts "flanking" back in the ability set
    and both halves travel together.

    Capitalised because it is folded into the permanent's *printed* rules text,
    which the UI shows; the compiler lowercases it again.

    **Read once per text.** ``Permanent.effective_card`` asks this of every
    Aura on every read of an enchanted permanent — 282,000 times in two
    simulated Mirage games, nearly all for the same few texts — and the
    answer is a function of the text and the keyword registry alone, so it
    is kept per text. Nothing about the Aura or the board reaches it: which
    host it is on, and whether it still is, are the caller's to ask on every
    read, and are. Under ``engine/fast_paths.py``'s checking mode every kept
    answer is read again and compared.
    """
    lines = _line_derived_lines_of(oracle_text)
    if fast_paths.CHECKING:
        fresh = _line_derived_lines_of.__wrapped__(oracle_text)
        fast_paths.checked(
            "aura_granted_line_derived_lines", fresh == lines,
            lambda: f"{oracle_text!r}: kept {lines}, read {fresh}",
        )
    return lines


@lru_cache(maxsize=None)
def _line_derived_lines_of(oracle_text: str) -> tuple[str, ...]:
    """:func:`aura_granted_line_derived_lines`, read off the text."""
    keywords = _late.keywords

    return tuple(
        keyword.capitalize()
        for keyword in aura_keyword_grants(oracle_text)
        if keywords.keyword_ability_name(keyword) in keywords.LINE_DERIVED_KEYWORDS
    )


def aura_keyword_removals(oracle_text: str) -> tuple[str, ...]:
    """Keyword abilities an Aura **takes away** from the permanent it enchants.

    "Enchanted creature loses flying." (Mammoth Harness.) CR 613 layer 6 again,
    and derived on every recompute exactly as :func:`aura_keyword_grants` is —
    so the ability comes back the moment the Aura stops being attached, with no
    remembered grant to restore. That symmetry is the reason this is a
    derivation rather than a `remove_keyword` call at attach time: a stored
    removal would have to be found and undone by whichever of the ways an Aura
    can leave happened to run.

    Kept apart from the grant for the reason the module comment on
    ``_KEYWORD_REMOVAL`` gives: grants and removals share the layer and are
    opposite contributions, so one list would make them indistinguishable —
    and the wrong reading of "loses flying" is an Aura that grants it.
    """
    removals: list[str] = []
    for raw_line in (oracle_text or "").split("\n"):
        match = _KEYWORD_REMOVAL.match(_line_text(raw_line))
        if match is not None:
            removals.extend(_keyword_list(match.group("keyword")))
    return tuple(removals)


#: The word a protection grant names when the colour was **chosen** rather
#: than printed: "Enchanted creature has protection from **the chosen
#: color**." (Ward of Lights.)
#:
#: A sixth value in the same channel as the five colour words rather than a
#: second function, because :func:`aura_protection_colors` already returns
#: *words* and leaves the mapping to its caller — "it is the one that knows
#: about text-changing remaps". Resolving a choice is the same kind of
#: knowledge, and that caller is also the only reader holding the Aura the
#: choice was recorded on.
CHOSEN_PROTECTION_COLOR = "chosen"

#: The word a protection grant names when the colours are **computed**:
#: "Enchanted creature has protection from **each color among permanents you
#: control**." (Pledge of Loyalty.) A seventh value in the same channel, for
#: the reason the sixth is one: :func:`aura_protection_colors` returns words
#: and its caller resolves them, and that caller is the only reader holding
#: both the Aura and the game. "You" is the Aura's controller (CR 109.5), and
#: the set is whatever that seat's board holds when the question is asked —
#: a static ability is not locked in (CR 611.3a), so the protection widens the
#: moment its controller lands a permanent of a new colour and narrows when
#: one leaves.
AMONG_CONTROLLED_PROTECTION_COLORS = "among_controlled"

#: The printed phrases that are not a colour word, as the value each travels as.
_PROTECTION_QUALITY_WORDS = {
    "the chosen color": CHOSEN_PROTECTION_COLOR,
    "each color among permanents you control": AMONG_CONTROLLED_PROTECTION_COLORS,
}

#: The P/T prefix is optional for :data:`_COLOR_GRANT`'s reason exactly: one
#: printed line can carry a layer-7c bonus and a layer-6 grant, and each half is
#: read by the reader that owns its layer. Without it a card printing "enchanted
#: creature gets +1/+1 and has protection from black" would be *claimed* by the
#: keyword row of ``auras._TEMPLATES`` -- ``_KEYWORDS`` is an alternative there
#: -- and granted nothing, which is this family's own defining failure with an
#: anchor as its cause.
_PROTECTION_GRANT = re.compile(
    rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? has protection from "
    rf"(?P<colors>{_PROTECTION_QUALITIES})\b"
)


#: "Enchanted creature gets +1/+1 and **is an artifact in addition to its other
#: types**." (Transmogrifying Licid.) The same rider one level up the type
#: hierarchy: `aura_vocabulary._TYPE_ADDITION_GRANT` adds a creature *subtype*
#: (CR 205.3), this adds a *card type* (CR 205.2), and both are CR 613 layer 4
#: additions that never replace.
#:
#: Its own pattern rather than a widened alternation in that one, because the
#: two grants go into different fields of the same contribution — a subtype
#: handed to ``card_types`` makes the permanent a "Knight" *type*, which nothing
#: on any board is — and because the shapes differ: Dub prints a keyword between
#: the P/T and the type where this prints nothing at all.
#:
#: The P/T half is deliberately not read here. ``_STATIC_PT_GRANT`` is an
#: unanchored *search* for exactly this reason (see its comment): the two halves
#: of one printed line live in two layers, and each is read by the reader that
#: owns its layer.
_CARD_TYPE_ADDITION_GRANT = re.compile(
    rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? is an? "
    r"(?P<card_type>artifact|enchantment|land|creature) "
    r"in addition to its other types$"
)


def aura_card_type_grants(oracle_text: str) -> tuple[str, ...]:
    """Card **types** an Aura adds to what it enchants (CR 613 layer 4).

    :func:`aura_type_grants`' twin one level up CR 205's hierarchy — a *card
    type* (CR 205.2) rather than a creature subtype (CR 205.3) — and separate
    because the two go into different fields of the contribution the layer
    engine takes. "In addition to its other types" is the printed rider that
    makes it an addition; nothing here ever replaces.
    """
    granted: list[str] = []
    for raw_line in oracle_text.splitlines():
        match = _CARD_TYPE_ADDITION_GRANT.match(_line_text(raw_line))
        if match is not None:
            granted.append(match.group("card_type"))
    return tuple(granted)


def aura_type_grants(oracle_text: str) -> tuple[str, ...]:
    """Creature subtypes an Aura *adds* to what it enchants (CR 613 layer 4).

    "…and is a Knight in addition to its other types" — added, never replacing,
    which is the difference between this and a land-type change (CR 305.7) and
    why it goes through ``add_types`` with ``replace_subtypes`` off.
    """
    granted: list[str] = []
    for raw_line in oracle_text.split("\n"):
        match = _TYPE_ADDITION_GRANT.match(_line_text(raw_line))
        if match is not None:
            granted.append(match.group("subtype"))
    return tuple(granted)


def aura_creature_type_sets(oracle_text: str) -> tuple[str, ...]:
    """Creature types an Aura **sets** on what it enchants (CR 613 layer 4).

    "Enchanted creature is a Flagbearer." (Coalition Flag.) :func:`aura_type_
    grants`' other half, and separate because the layer contribution differs:
    this one replaces the creature's other creature types (CR 205.1a) and
    leaves every other subtype it has alone — an animated Forest under the
    Flag is still a Forest — which is ``add_types(replaces_subtypes_from=)``
    scoped to the creature types.
    """
    found: list[str] = []
    for raw_line in oracle_text.split("\n"):
        match = _CREATURE_TYPE_SET.match(_line_text(raw_line))
        if match is not None:
            found.append(match.group("subtype"))
    return tuple(found)


#: "Enchanted creature gets +3/-1 **and is black**." (Grave Servitude.) The
#: colour half of the compound line, and the bare "…is black" beside it.
#:
#: A **search**, not an anchored match, for `_STATIC_PT_GRANT`'s reason one
#: screen down: the two halves of one printed line live in two layers (7c and
#: 5), and each is read by the reader that owns its layer. Anchoring here would
#: make the compound line answer for the colour and not the P/T, or the other
#: way round, depending on which reader was written last.
#:
#: The trailing anchor is still required. "is black" ends the sentence on every
#: printing of it, and without the anchor "enchanted creature is black **as
#: long as …**" — a conditional this does not implement — would read as the
#: unconditional grant.
_COLOR_GRANT = re.compile(
    rf"{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? is (?P<color>{_COLORS})$"
)


def aura_color_grants(oracle_text: str) -> tuple[str, ...]:
    """Colour words an Aura gives what it enchants (CR 613 layer 5).

    CR 105.3: a new colour **replaces** every colour the object had, unless the
    effect says "in addition". No printing of this sentence says it, so the
    grant is a `set_colors` contribution and not an addition — a creature under
    Grave Servitude is black and nothing else.

    Colour *words*, exactly as :func:`aura_protection_colors` returns them: the
    caller is the one that knows whether a text change has remapped the word
    (Sleight of Mind), and mapping here would be a second answer to that.
    """
    granted: list[str] = []
    for raw_line in oracle_text.splitlines():
        match = _COLOR_GRANT.search(_line_text(raw_line))
        if match is not None:
            granted.append(match.group("color"))
    return tuple(granted)


def aura_protection_colors(oracle_text: str) -> frozenset[str]:
    """Colour words an Aura grants protection from (the Ward cycle).

    Colour *words*, not mana symbols: the caller maps them, and it is the one
    that knows about text-changing remaps (Sleight of Mind).

    :data:`CHOSEN_PROTECTION_COLOR` is the sixth value, for "protection from
    **the chosen color**" (Ward of Lights). It travels through this same
    channel for that mapping reason exactly: the caller holds the Aura, and
    the choice is recorded on it by "As this Aura enters, choose a color."
    :data:`AMONG_CONTROLLED_PROTECTION_COLORS` is the seventh, for "each color
    among permanents you control" (Pledge of Loyalty), resolved the same way.
    """
    found = set()
    for raw_line in oracle_text.splitlines():
        match = _PROTECTION_GRANT.match(_line_text(raw_line))
        if match is not None:
            # CR 702.16g: "protection from black **and from red**" (Mask of Law
            # and Grace) is two protection abilities. Split here rather than
            # returned as a phrase, because every consumer of this frozenset
            # maps one word to one quality -- a joined string maps to none of
            # them and the Aura would protect from nothing at all. That is what
            # the pattern already did while its alternation was one colour wide
            # and its tail unanchored: it matched Mask's line and returned
            # ``{"black"}``, dropping red in silence.
            for word in match.group("colors").split(" and from "):
                word = word.strip()
                found.add(_PROTECTION_QUALITY_WORDS.get(word, word))
    return frozenset(found)


# Animate Artifact: "As long as enchanted artifact isn't a creature, it's an
# artifact creature with power and toughness each equal to its mana value."
#
# Two layers from one line — layer 4 adds the creature type, layer 7b sets P/T —
# which is why it cannot be expressed as a flag. The engine used to *rebuild the
# CardDefinition* with "Creature" spliced into the type line and P/T baked in,
# swap it onto the permanent, and stash the original to restore on removal: the
# remember-and-undo shape, applied to the object's identity.
_ANIMATE_ARTIFACT = re.compile(
    r"^as long as enchanted artifact isn't a creature, it's an artifact creature "
    r"with power and toughness each equal to its mana value$"
)


def aura_animates_artifact(oracle_text: str) -> bool:
    """Whether this Aura animates the artifact it enchants."""
    return any(
        _ANIMATE_ARTIFACT.match(_line_text(raw_line))
        for raw_line in oracle_text.splitlines()
    )


#: "Enchanted land is a 5/6 green Treefolk creature that's still a land."
#: (Living Terrain.) Animate Artifact's shape with the body printed rather than
#: computed: layer 4 adds the creature type and the printed creature types
#: (CR 205.1b's "still a land" is the *addition* — nothing is replaced), layer 5
#: sets the printed colours (CR 105.3) and layer 7b sets the printed P/T. All
#: three are derived from the Aura's text on every recompute, so the land is a
#: land again the moment the Aura leaves.
#:
#: The colour run and the creature types are captured loosely and *checked* by
#: :func:`aura_land_animation` against the vocabulary, so a word that is neither
#: a colour nor a creature type refuses the line instead of being dropped.
_ATTACHED_LAND_ANIMATION = re.compile(
    r"^enchanted land is an? (?P<power>\d+)/(?P<toughness>\d+)"
    r"(?P<words>(?: [a-z][a-z'-]*)*?) creature that's still a land$"
)


def aura_land_animation(oracle_text: str) -> dict | None:
    """The body an Aura makes its land, or None.

    ``{"power", "toughness", "colors", "subtypes"}`` — colours as symbols, the
    creature types as the vocabulary spells them. One reader for the support
    gate (through :func:`aura_continuous_claim`) and for the three layers in
    ``layer_bridge`` that apply it, which is this file's standing rule.

    Colours come first and creature types after them, which is the order the
    templating prints a body in (the same order ``effects/types.py`` reads
    Quirion Druid's "2/2 green creature" in); a word out of place, or a word
    that is neither, answers None.
    """
    for raw_line in (oracle_text or "").splitlines():
        match = _ATTACHED_LAND_ANIMATION.match(_line_text(raw_line))
        if match is None:
            continue
        vocabulary = _late_grammar.vocabulary
        COLOR_WORDS, CREATURE_TYPES = vocabulary.COLOR_WORDS, vocabulary.CREATURE_TYPES
        colors: list[str] = []
        subtypes: list[str] = []
        for word in match.group("words").split():
            if word in COLOR_WORDS and not subtypes:
                colors.append(COLOR_WORDS[word])
            elif word in CREATURE_TYPES:
                subtypes.append(word)
            else:
                return None
        return {
            "power": int(match.group("power")),
            "toughness": int(match.group("toughness")),
            "colors": tuple(colors),
            "subtypes": tuple(subtypes),
        }
    return None


#: "**You control** enchanted creature." (Control Magic, Dominating Licid;
#: Steal Artifact prints the same sentence one noun over.) CR 613 layer 2,
#: derived from the attachment on every state-based pass rather than performed
#: when an Aura *spell* resolves — which is the difference the Licids force. A
#: Licid becomes an Aura through an activated ability and attaches through
#: ``attach_source_to_target``; no Aura spell ever resolves, so the resolution-
#: time reading reached it not at all.
_ATTACHED_CONTROL_CHANGE = re.compile(rf"^you control {_ATTACHED} {_NOUN}$")


def aura_grants_control(attachment) -> bool:
    """Whether *attachment* says its controller controls what it is attached to.

    Asked of the permanent rather than of a string, because the text that
    matters is ``effective_card`` — a Licid's printed lines survive its type
    change, and a copy or a text-changing effect is read here for the reason
    every other derivation in this file reads it (CR 613 layers 1 and 3).

    Read by the state-based sweep in ``mixins/game_ending.py`` in **both**
    directions: it records the contribution while the attachment holds and ends
    it when the attachment does not. That is why the claim in
    :func:`aura_continuous_claim` is honest — the effect really is derived from
    the Aura's own text on every pass, with no remembered delta to undo, which
    is what the rest of this file means by "continuous".
    """
    text = attachment.effective_card.oracle_text or ""
    return any(
        _ATTACHED_CONTROL_CHANGE.match(_line_text(raw_line))
        for raw_line in text.splitlines()
    )


#: "Enchanted artifact's activated abilities cost {2} less to activate. This
#: effect can't reduce the mana in that cost to less than one mana." (Power
#: Artifact.) Both sentences are matched together and both are required: the
#: floor is not a decoration, it is what stops a {2} ability becoming free, and
#: a pattern claiming only the first sentence would leave the second unclaimed
#: while quietly implementing a cheaper card.
_ABILITY_COST_REDUCTION = re.compile(
    rf"^{_ATTACHED} {_NOUN}'s activated abilities cost \{{(?P<generic>\d+)\}} "
    r"less to activate\. this effect can't reduce the mana in that cost to "
    r"less than (?P<floor>one|two|three) mana$"
)

_FLOOR_WORDS = {"one": 1, "two": 2, "three": 3}


def aura_ability_cost_reduction(oracle_text: str) -> tuple[int, int] | None:
    """``(generic reduction, minimum mana)`` an attached Aura grants, or None.

    Read off the Aura's whole text rather than one line, because the two
    sentences are printed as one paragraph and the floor belongs to the
    reduction in front of it.
    """
    # The "Enchant <noun>" line is the targeting restriction, not an effect —
    # flattening it in with the rest would put four words in front of an
    # anchored pattern and match nothing. Dropped here for the same reason
    # `unclaimed_aura_lines` drops it there.
    effect_lines = [
        line for line in (_line_text(raw) for raw in oracle_text.splitlines())
        if line and not line.startswith("enchant ")
    ]
    text = " ".join(" ".join(effect_lines).split())
    match = _ABILITY_COST_REDUCTION.match(text)
    if match is None:
        return None
    return int(match.group("generic")), _FLOOR_WORDS[match.group("floor")]


def aura_cost_reduction_sentences(oracle_text: str) -> tuple[str, ...]:
    """The sentences :func:`aura_ability_cost_reduction` reads, or empty.

    The reduction is **two sentences on one printed line** — the amount and the
    floor — and neither means anything alone: the first without the second is a
    strictly better card, and the second without the first modifies nothing. So
    the reader matches them joined, and this names the pair for a caller that
    walks a card sentence by sentence (``scripts/parse_coverage.py``) and would
    otherwise report both as text nothing read.
    """
    if aura_ability_cost_reduction(oracle_text) is None:
        return ()
    effect_lines = [
        line for line in (_line_text(raw) for raw in (oracle_text or "").splitlines())
        if line and not line.startswith("enchant ")
    ]
    joined = " ".join(" ".join(effect_lines).split())
    return tuple(
        sentence.strip() for sentence in joined.split(". ") if sentence.strip()
    )


def attached_ability_cost_reduction(permanent) -> tuple[int, int]:
    """``(reduction, floor)`` every Aura on *permanent* contributes, combined.

    Reductions add; the floor is the *highest* any of them names, which is the
    reading that keeps two Auras from cancelling each other's protection
    against a free ability.
    """
    total = 0
    floor = 0
    for aura in auras_attached_to(permanent):
        found = aura_ability_cost_reduction(aura.effective_card.oracle_text)
        if found is None:
            continue
        total += found[0]
        floor = max(floor, found[1])
    return total, floor


#: "All damage that would be dealt to you is dealt to enchanted creature
#: instead." (Pariah.) CR 614.9's redirection printed as an Aura's **static**
#: ability: it lasts exactly as long as the Aura is attached, which is why it
#: is derived here on every damage event rather than armed as a record —
#: removal is the Aura ceasing to be attached, and there is no remembered
#: delta to undo. The same shape ``prevention.shields._attached_damage_shields`` has one
#: module over, and for the same reason.
#:
#: "You" is CR 109.5's controller of the **Aura**, not of the creature: an
#: opponent may well control the host, and Pariah on their creature still moves
#: your damage onto it. The seat is read off the Aura at the event, so a control
#: change moves the protection with it.
#:
#: The noun is payload the way every printed noun in this file is, and both
#: attachment words are read (CR 301.5f) — an Equipment printing the sentence is
#: the same rule.
_ATTACHED_ALL_DAMAGE_REDIRECT = re.compile(
    rf"^all damage that would be dealt to you is dealt to {_ATTACHED} "
    rf"(?P<noun>{_NOUN}) instead$"
)


def aura_redirects_all_damage(line: str) -> bool:
    """Whether one printed line moves all of its controller's damage onto the
    attached permanent.

    One reader, two callers, which is this file's standing rule: the support
    gate asks it through :func:`aura_continuous_claim` so the line is claimed,
    and ``damage_redirects.attached_static_redirects`` asks it at the damage
    event so the line is *carried out*. A line claimed here and read nowhere
    else would be an Aura reporting supported while every point of damage still
    landed on its controller.
    """
    return _ATTACHED_ALL_DAMAGE_REDIRECT.match(_line_text(line)) is not None


#: "All damage that would be dealt to enchanted creature is dealt to its
#: controller instead." (Treacherous Link.) The row above's mirror, and the two
#: are not one pattern with the ends swapped: that one protects the Aura's
#: *controller* and moves the damage onto a permanent, this one protects the
#: *attached permanent* and moves it onto a player. Different recipients, so
#: different scans in ``damage_redirects`` — a record lives on the object it
#: watches, and those are two different objects.
#:
#: **"its" is the enchanted creature's**, not the Aura's. The possessive takes
#: the nearest noun phrase, which is the one the sentence has just named, and
#: the difference is the whole card: this is a {1}{B} Aura you put on an
#: *opponent's* creature so that damage aimed at it lands on them. Read as the
#: Aura's controller it would be a card that damages you.
#:
#: The noun is payload the way every printed noun in this file is, and both
#: attachment words are read (CR 301.5f) — an Equipment printing the sentence is
#: the same rule.
_ATTACHED_HOST_DAMAGE_TO_CONTROLLER = re.compile(
    rf"^all damage that would be dealt to {_ATTACHED} (?P<noun>{_NOUN}) is dealt "
    rf"to its controller instead$"
)


#: "Enchanted creature has landwalk of the chosen type." (Traveler's Cloak.)
#: CR 702.14a builds a landwalk's name out of a land type, and here the type is
#: not printed: it is the one this Aura recorded as it entered (CR 614.1c, "As
#: this Aura enters, choose a land type."). So the line grants a keyword whose
#: *word* is read off the Aura at each recompute — which is what keeps it out
#: of ``aura_keyword_grants``, whose answer is a function of the text alone.
#:
#: Both attachment words are read (CR 301.5f), like every pattern in this file.
_ATTACHED_CHOSEN_LANDWALK = re.compile(
    rf"^{_ATTACHED} creature has landwalk of the chosen type$"
)


def aura_grants_chosen_landwalk(line: str) -> bool:
    """Whether one printed line grants the host landwalk of the land type the
    attachment chose as it entered.

    One reader, two callers, which is this file's standing rule: the support
    gate asks it through :func:`aura_continuous_claim`, and
    :func:`chosen_landwalk_grants` asks it at each layer-6 recompute.
    """
    return _ATTACHED_CHOSEN_LANDWALK.match(_line_text(line)) is not None


def chosen_landwalk_grants(aura) -> tuple[str, ...]:
    """The landwalk ability *aura* gives its host — ``("islandwalk",)`` for an
    Aura that chose Island — or nothing when it prints no such line, has not
    chosen, or chose a word that names no land type.

    Read off ``effective_card`` (CR 707.2: a copy of the Cloak grants what the
    *copy* chose) and off the record the entry choice wrote. The word is put
    to ``landwalk.landwalk_requirement`` — the reader that enforces the ability
    at the declare-blockers step — so a grant nothing would enforce is never
    made.
    """
    chosen = str(
        aura.metadata.get(_late.entry_choices.CHOSEN_LAND_TYPE_KEY) or ""
    ).strip().lower()
    if not chosen:
        return ()
    if not any(
        aura_grants_chosen_landwalk(line)
        for line in (aura.effective_card.oracle_text or "").splitlines()
    ):
        return ()
    walk = f"{chosen}walk"
    return (walk,) if _late.landwalk.landwalk_requirement(walk) is not None else ()


def aura_redirects_host_damage_to_controller(line: str) -> bool:
    """Whether one printed line moves all of the attached permanent's damage
    onto that permanent's controller.

    One reader, two callers, which is this file's standing rule: the support
    gate asks it through :func:`aura_continuous_claim` so the line is claimed,
    and ``damage_redirects.attached_static_redirects`` asks it at the damage
    event so the line is *carried out*. Claimed here and read nowhere else it
    would be an Aura reporting supported while every point of damage still
    landed on the creature.
    """
    return _ATTACHED_HOST_DAMAGE_TO_CONTROLLER.match(_line_text(line)) is not None


def animating_auras(permanent) -> list:
    """Attached Auras that animate *permanent*, honouring "isn't a creature".

    **Whether the host "isn't a creature" is asked as the effect starts to
    apply** — of CR 613 layer 4's intermediate state, by the board-wide pass
    (``engine/type_statics.py``), which records its answer on each Aura. That
    is the only moment the question has one answer: asked of the finished
    layer it would include the creature type this very effect adds, and asked
    of the printed type line — which is what this did — it cannot see what
    some *other* effect has already made the artifact. Under an older
    Titania's Song the artifact is a creature by the time this Aura applies,
    so the Aura does nothing (and the Song strips the artifact's abilities);
    under a younger one the Aura applies first and the Song passes the artifact
    by. The two depend on each other, which is a loop, and CR 613.8b settles a
    loop by timestamp. CR 613.6 then keeps the layer-7b half on the set of
    objects layer 4 found, which is why both collectors read this one answer.

    Where no refresh has decided it — a board built by hand, an Aura read
    before anything recomputed — the printed type line stands in, as it always
    did.
    """
    animates_host = _late.type_changes.animates_host

    printed_creature = "creature" in permanent.card.type_line.lower()
    found = []
    for aura in auras_attached_to(permanent):
        if not aura_animates_artifact(aura.effective_card.oracle_text):
            continue
        decided = animates_host(aura)
        if decided if decided is not None else not printed_creature:
            found.append(aura)
    return found
