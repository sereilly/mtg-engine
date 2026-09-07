"""The damage shields — a prevention that names what is **protected** (CR 615).

The productions for a sentence that puts a shield around a recipient: the
counted pool ("Prevent the next N damage that would be dealt to <recipient>
this turn", CR 615.7), the blanket ("Prevent all [combat] damage that would be
dealt [to <recipient>] [by <source>] <duration>", which has no charges at all),
and Silhouette's shield around the object an earlier sentence bound.

Split out of ``damage.py`` at the 1,000-line guard, along the line the lowering
side had already drawn — ``lowering/prevention.py`` and
``lowering/redirection.py`` left that module for the same reason. It reached the
guard twice more and each split went along a line the CR draws.
``effects/damage_locks.py`` took the sentence *about* the shields
("…can't be prevented or dealt instead…"); ``effects/damage_instances.py`` took
CR 615.8, the shield or redirect that names **whose** damage is stopped and
modifies exactly one instance of it. CR 615.7 says its own half of that line —
these shields "count only the amount of damage; the number of events or sources
dealing it doesn't matter" — which is why the "by <source>" clauses read below
are a *narrowing* on a pool rather than the other family: they say whose damage
the pool may absorb, not that one instance of it is spent.

None of the three modules imports another in either direction. The one
production two of them read is CR 615.5's rider, and it sits a level up in
``grammar/prevented_riders.py`` rather than in either family.
"""

from .. import ast
from ..amounts import parse_amount
from ..references import parse_recipient
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..names import accept_source_card_name
from ..prevented_riders import _parse_prevented_this_way_rider
from ..stream import TokenStream
from ..phrases import (_parse_duration, accept_or_planeswalker,
                       parse_bound_subject)


def _parse_prevent(stream: TokenStream) -> ast.PreventDamage:
    """"Prevent the next N damage that would be dealt to <recipient> this turn."

    The recipient decides which handler shape applies, so it is parsed rather
    than skipped: "you" and "this creature" are different shields from "any
    target", and conflating them would put the shield on the wrong thing.
    """
    stream.expect_word("prevent")
    if stream.at_word("all"):
        return _parse_prevent_all(stream)
    if not stream.accept_phrase("the", "next"):
        raise stream.error("expected 'the next' in a prevention effect")
    amount = parse_amount(stream)
    if not stream.accept_word("damage"):
        raise stream.error("expected 'damage'")
    if not stream.accept_phrase("that", "would", "be", "dealt"):
        raise stream.error("expected 'that would be dealt'")
    # "…that would be dealt **this turn to** target creature you control."
    # (Samite Alchemist.) The pre-modern printing puts the duration first, and
    # both orders are the same sentence — the blanket branch below already
    # reads either for Pack Leader's identical swap, and a numeric shield
    # failing on word order is the card lost to a printing convention rather
    # than to a missing effect. Read here, before the "to", so the recipient
    # reader below sees the same stream either way.
    duration = _parse_duration(stream)
    if not stream.accept_word("to"):
        raise stream.error("expected 'to' in a prevention effect")
    recipient = parse_recipient(stream)
    if recipient is None:
        raise stream.error("expected something to shield")
    # "…dealt to target player **or planeswalker** this turn" (Wandering Mage).
    # CR 115.4's union, read from ``phrases`` because damage prints the same two
    # words (Chandra's Magmutt) and the two families may not import each other.
    # Read before the trailing duration, which is where the card prints it.
    recipient = accept_or_planeswalker(stream, recipient)
    # "…dealt to this creature **by Torrent of Lava** this turn." Whose damage
    # the shield stops — which the blanket branch below has read since
    # Al-abara's Carpet and this one never had, so those words ran off the end
    # of the line and the card refused at "by" with nothing else wrong with it.
    # Read on **both** sides of the trailing duration, exactly as that branch
    # reads its own: the printed orders differ between cards.
    dealt_by = _accept_prevention_source(stream)
    # The trailing spelling. Only one of the two may be printed: a duration on
    # both sides is not a sentence this reads, and taking the second silently
    # would let two windows disagree about how long the shield lasts.
    if duration.kind is None:
        duration = _parse_duration(stream)
    if dealt_by is None:
        dealt_by = _accept_prevention_source(stream)
    # "…to any number of targets, **divided as you choose**." (Remedy.)
    # CR 601.2d's division on the prevention side of the event, read after the
    # recipient because that is where the card prints it.
    division = _accept_division_rider(stream)
    # "…**For each 1 damage prevented this way, put a +1/+1 counter on that
    # creature.**" (Temper.) CR 615.5's additional effect, printed on a
    # *counted* pool where every other card in the pool prints it on a
    # chosen-source shield — so it is the same reader, called from a second
    # sentence, and deliberately not a second reader: two productions for one
    # printed clause would make which riders a card may carry depend on which
    # shield printed them.
    prevented_rider = _parse_prevented_this_way_rider(stream)
    alternate = _parse_instead_rider(stream)
    if alternate is None:
        return ast.PreventDamage(
            amount, to=recipient, duration=duration, dealt_by=dealt_by,
            division=division, prevented_rider=prevented_rider,
        )
    described, larger = alternate
    return ast.PreventDamage(
        amount, to=recipient, duration=duration, dealt_by=dealt_by,
        alternate_amount=larger, alternate_subject=described,
        division=division, prevented_rider=prevented_rider,
    )


def _accept_division_rider(stream: TokenStream) -> str | None:
    """``, divided as you choose`` / ``, divided evenly[, rounded down]``, or
    None with the cursor unmoved.

    "Prevent the next 5 damage that would be dealt this turn to any number of
    targets, **divided as you choose**." (Remedy.) CR 601.2d's announcement,
    printed on a shield rather than on a burn spell — the same clause
    ``effects/damage.py`` reads before its recipients, which is why the word is
    carried rather than the fact that there is one: the engine divided evenly
    for both printed sentences until the *word* had somewhere to go, and four
    burn spells were played weaker than printed for it.

    Refuses with the cursor untouched, so every prevention that names one
    recipient keeps the reading it has.
    """
    mark = stream.mark()
    stream.accept_punct(",")
    if not stream.accept_word("divided"):
        stream.reset(mark)
        return None
    if stream.accept_phrase("as", "you", "choose"):
        return "chosen"
    if stream.accept_word("evenly"):
        # The rounding is consumed rather than dropped: a shield split one
        # point smaller than the card prints is a card doing less, silently.
        # No prevention in the pool prints it, and the lowering refuses the
        # even split outright — this is here so the *words* cannot run off the
        # end of the line and fail the card at full-token consumption instead
        # of at the missing handler.
        mark_rounding = stream.mark()
        stream.accept_punct(",")
        if not (stream.accept_word("rounded") and stream.accept_word("down", "up")):
            stream.reset(mark_rounding)
        return "evenly"
    stream.reset(mark)
    return None


def _accept_prevention_source(stream: TokenStream) -> "ast.Recipient | None":
    """``by <whose damage this stops>``, or None with the cursor unmoved.

    Three readings in that order and for that reason: the noun-phrase
    vocabulary, then the bound reader that follows a pronoun back to what an
    earlier clause chose, and only then a bare card **name** — a literal string
    (``engine/grammar/names.py``), which is why it is last. A phrase either of
    the first two could read must be read as a phrase; the name scan is for the
    words nothing else claims. Refusing with the cursor untouched leaves a "by"
    clause this cannot read unconsumed, so the line refuses naming those words
    instead of arming a shield against nothing.
    """
    mark = stream.mark()
    if not stream.accept_word("by"):
        return None
    found = parse_recipient(stream) or parse_bound_subject(stream)
    if found is not None:
        return found
    named = accept_source_card_name(stream)
    if named is not None:
        return ast.TargetSpec(quantifier="a", filter=ast.ObjectFilter(named=named))
    stream.reset(mark)
    return None


def _parse_instead_rider(
    stream: TokenStream,
) -> "tuple[ast.ObjectFilter, ast.Amount] | None":
    """``. If it's <noun phrase>, prevent the next N damage instead.`` (Elvish
    Healer.)

    A rider on the shield in front of it rather than a sentence of its own: it
    prevents nothing by itself, and "instead" says so — the two sentences arm
    **one** shield whose size depends on what the first one's target turns out
    to be. Read here for the same reason the upkeep toll's trailing sentence is
    read inside its own production: a statement layer that split them would arm
    two shields and prevent three.

    Every part is required. The pronoun must be "it" (the target the sentence
    in front of it chose), the noun phrase is what decides which size applies,
    and the printed "instead" is the difference between a larger shield and a
    second one.

    Refuses with the cursor untouched, so a prevention sentence followed by any
    other sentence keeps the reading it has.
    """
    mark = stream.mark()
    if not stream.accept_punct("."):
        return None
    if not stream.accept_phrase("if", "it", "'s"):
        stream.reset(mark)
        return None
    stream.accept_word("a", "an")
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("prevent", "the", "next"):
        stream.reset(mark)
        return None
    try:
        larger = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("damage", "instead"):
        stream.reset(mark)
        return None
    return described, larger


def _accept_active_voice_shield(
    stream: TokenStream, combat_only: bool
) -> "ast.PreventDamage | None":
    """``<who deals it> would deal [to <recipient>] <duration>``, or None with
    the cursor unmoved.

    "Prevent all combat damage **target creature would deal** this turn."
    (Resistance Fighter.) The blanket shield with its source in the subject
    position instead of behind a "by", which is how the pre-Sixth-Edition
    printings say it — and the *only* difference from the passive spelling
    ``_parse_prevent_all`` already reads, which is why the node it builds is
    the same node with the same ``dealt_by``.

    The optional "to <recipient>" is read rather than skipped for the reason
    every other clause in this file is read: a shield that stops one creature's
    damage *to one player* is strictly smaller than one that stops all of it,
    and a dropped clause here is a shield wider than the card prints.

    Refuses with the cursor untouched, so a "prevent all damage …" sentence
    this cannot finish keeps the refusal it has.
    """
    mark = stream.mark()
    dealt_by = parse_recipient(stream) or parse_bound_subject(stream)
    if dealt_by is None or not stream.accept_phrase("would", "deal"):
        stream.reset(mark)
        return None
    recipient: ast.Recipient | None = None
    if stream.accept_word("to"):
        recipient = parse_recipient(stream)
        if recipient is None:
            stream.reset(mark)
            return None
    duration = _parse_duration(stream)
    return ast.PreventDamage(
        ast.AllOf(), to=recipient, duration=duration, combat_only=combat_only,
        dealt_by=dealt_by,
    )


def _parse_prevent_all(stream: TokenStream) -> ast.PreventDamage:
    """"Prevent all [combat] damage that would be dealt [to <recipient>] <duration>."

    A blanket shield rather than a numeric one, so the quantity is
    :class:`ast.AllOf` and there is nothing to count down. Three parts are read
    rather than skipped, because each one names a *different* card:

    * "combat" — Fog stops only combat damage; a card stopping all damage is a
      strictly larger effect and must not borrow Fog's handler.
    * the recipient — "…dealt to you this turn" is a shield on one player, which
      is not what the turn-wide flag implements.
    * the duration — a blanket prevention with no duration is a continuous
      static ability, not a one-shot effect.

    All three reach lowering, which refuses every combination but the one a
    handler exists for. Parsing them and refusing there (rather than declining
    to parse) is what keeps the backlog honest about which wording is missing.

    **The active voice is the same sentence.** "Prevent all combat damage
    target creature would deal this turn" (Resistance Fighter) says exactly
    what "…that would be dealt by target creature this turn" says, which this
    production has read since Kry Shield — the printed subject simply moves in
    front of the verb. Read as a branch here rather than as a production of its
    own, because everything after the noun is the identical clause and a second
    production would race this one on the four words "prevent all combat
    damage".
    """
    stream.expect_word("all")
    combat_only = bool(stream.accept_word("combat"))
    stream.expect_word("damage")
    if not stream.accept_phrase("that", "would", "be", "dealt"):
        active = _accept_active_voice_shield(stream, combat_only)
        if active is not None:
            return active
        raise stream.error("expected 'that would be dealt' in a prevention effect")
    recipient: ast.Recipient | None = None
    dealt_by: ast.Recipient | None = None
    to_and_by = False
    if stream.accept_word("to"):
        # "…that would be dealt **to and dealt by** that creature this turn."
        # (Ebony Horse, Maze of Ith.) One printed object standing at both ends
        # of the event, named once. Read here rather than as a second "by"
        # clause below, because these words come *before* the noun: a reader
        # expecting them after it would leave "and dealt by" unconsumed and
        # fail the line at the noun instead of at the wording.
        to_and_by = bool(stream.accept_phrase("and", "dealt", "by"))
        recipient = parse_recipient(stream)
        if recipient is None and to_and_by:
            recipient = parse_bound_subject(stream)
        if recipient is None:
            raise stream.error("expected something to shield")
        if to_and_by:
            dealt_by = recipient
    elif stream.accept_word("by"):
        # "…that would be dealt **by** target creature this turn." The word is
        # the whole difference between a creature that cannot be hurt and one
        # that cannot hurt anything, so it is read rather than skipped.
        #
        # ``parse_recipient`` first and the bound reader second, the order
        # ``statements.py`` uses for the same pair: "that creature**'s
        # controller**" is a player reference the first already reads, and a
        # bound reader that got there first would eat the noun and strand the
        # possessive.
        dealt_by = parse_recipient(stream) or parse_bound_subject(stream)
        if dealt_by is None:
            raise stream.error("expected whose damage to prevent")
    duration = _parse_duration(stream)
    # "…dealt to and dealt by that creature **this combat**." (Winter's Chill.)
    # Read here rather than in the shared duration table, and the narrowness is
    # the point: "this combat" appears mid-sentence on six other cards in the
    # pool ("blocked by only that creature this combat", "can't be blocked this
    # combat except by …"), and a trailing-duration reader that claimed it
    # everywhere would swallow those words from productions that do not mean a
    # duration by them. Its own kind rather than ``until_end_of_combat``'s for
    # the reason "this turn" is not ``until_end_of_turn``: two printed spellings
    # of one window are two kinds here, and the sweep is what makes them one.
    if duration.kind is None and stream.accept_phrase("this", "combat"):
        duration = ast.Duration("this_combat")
    # "…that would be dealt **this turn to Dogs you control**" (Pack Leader).
    # The printed order puts the duration first, and both orders are the same
    # sentence — so the recipient is read on either side rather than the card
    # failing on word order. Only one of the two may appear: a line naming a
    # recipient twice is not a wording this reads.
    if recipient is None and stream.accept_word("to"):
        recipient = parse_recipient(stream)
        if recipient is None:
            raise stream.error("expected something to shield")
    # "…that would be dealt **this turn by target creature you control**" (Kry
    # Shield), and "…dealt **to you this turn by attacking creatures without
    # flying**" (Al-abara's Carpet). The same word-order swap as the recipient
    # above, on the other end of the event — read on either side rather than the
    # card failing on the order its printing happens to use. Both ends may
    # appear: a shield naming who is protected *and* whose damage is stopped is
    # a narrower effect than either half, and dropping one would widen it.
    if dealt_by is None and stream.accept_word("by"):
        dealt_by = parse_recipient(stream) or parse_bound_subject(stream)
        if dealt_by is None:
            raise stream.error("expected whose damage to prevent")
    # "…by that creature **and each creature blocking it**." (Feint.) More than
    # one source, joined by the printed "and". Read here rather than in either
    # of the two "by" branches above because it belongs to the conjunct *list*
    # and not to the word order — the same argument `_parse_condition` makes for
    # reading its own "and" once. The loop backtracks: an "and" that does not
    # introduce another source belongs to whatever follows the clause.
    dealt_by_others: list[ast.Recipient] = []
    while dealt_by is not None:
        mark = stream.mark()
        if not stream.accept_word("and"):
            break
        further = parse_recipient(stream) or parse_bound_subject(stream)
        if further is None:
            stream.reset(mark)
            break
        dealt_by_others.append(further)
    return ast.PreventDamage(
        ast.AllOf(), to=recipient, duration=duration, combat_only=combat_only,
        dealt_by=dealt_by, dealt_by_others=tuple(dealt_by_others),
        to_and_by=to_and_by,
    )


def _parse_bound_targeting_prevention(stream: TokenStream) -> "ast.PreventDamage | None":
    """"If a spell or ability that targets <bound object> would cause a source
    to deal damage to <bound object> this turn, prevent that damage."
    (Silhouette — the second sentence of a spell whose first one chose the
    object both halves name.)

    Every word is read, because each one is a way the card could mean less than
    the sentence says: "or ability" is half of what it shields against,
    "a source" is any source rather than the spell itself, and the two bound
    references have to name the *same* object — a sentence shielding one
    creature from spells aimed at another is a different card, and dropping the
    difference would shield against every targeted spell in the game.

    Non-consuming on refusal, so every other sentence opening "If …" keeps the
    ordinary conditional reading.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "a", "spell", "or", "ability", "that", "targets"
    ):
        stream.reset(mark)
        return None
    protected = parse_bound_subject(stream)
    if protected is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "would", "cause", "a", "source", "to", "deal", "damage", "to"
    ):
        stream.reset(mark)
        return None
    damaged = parse_bound_subject(stream)
    if damaged != protected:
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    stream.accept_punct(",")
    if not stream.accept_phrase("prevent", "that", "damage"):
        stream.reset(mark)
        return None
    return ast.PreventDamage(
        ast.AllOf(), to=protected, duration=duration, from_targeting_source=True
    )
