"""Combat **requirements** — CR 508.1d and CR 509.1c, "attacks/blocks if able".

The parse-side mirror of ``lowering/requirements.py``, and it arrives the way
that module's own docstring said it would: that family was declared
"lowering-only … the parse side keeps both productions in ``effects/combat.py``,
where each is one branch of a verb table, and it is the lowerings that outgrew
the cap". Urza's Saga's second wave is where the *parse* half outgrew it too, so
the mirror re-forms rather than forking — the move this package's notes keep
asking for, and the name was waiting one directory over.

The line is CR 506.3's own pair of words, exactly as the lowering half draws it:
a **restriction** says a creature *can't* and a **requirement** says it *must*,
and CR 509.1c makes the pair asked in a fixed order — a requirement is obeyed
"to the maximum possible number without disobeying any restrictions" — so
neither can be written as the negation of the other. Everything left in
``effects/combat.py`` reads the first, plus the permissions that lift one; every
production here reads the second.

The two paragraph productions come with them, and that is the same line rather
than a second one. "Choose target non-Wall creature … **That creature attacks
this turn if able.** Destroy it at the beginning of the next end step if it
didn't attack this turn" (Nettling Imp, Norritt, Arcum's Whistle) is a
requirement with its chooser and its consequence printed around it — three
sentences whose middle one is the rule and whose other two exist to say who it
is about and what happens if it is not obeyed. Splitting the paragraph from the
one-sentence spelling of the same requirement would put one printed rule in two
modules.

``_parse_choose_blocks_for_defenders`` (Melee) stayed behind, and the reason is
the trio the lowering side names: substituting CR 509.1a's *chooser* neither
forbids nor compels anything — it is a permission, and permissions live with the
restrictions they lift.
"""

from .. import ast
from ..lexer import MANA
from ..nouns import parse_object_filter
from ..back_references import parse_bound_subject
from ..references import parse_recipient, parse_target_spec
from ..stream import TokenStream


# ---------------------------------------------------------------------------
# A whole printed paragraph that is one combat effect
# ---------------------------------------------------------------------------
#
# Read here rather than in `paragraphs`, which is where it was until Arcum's
# Whistle's payment tail pushed that module past the thousand-line guard. The
# split reuses the family name the other side already carries — the lowering is
# `lowering/combat.py`, so one template has one home per side and a reader
# looking for the force-to-attack template finds it under `combat` on either.
# Nothing about the production changed in the move: it still reads its own words
# to the end and never calls back into the sentence parser, which is what made
# it a paragraph in the first place.

def _parse_force_chosen_creature_to_attack(stream: TokenStream) -> "ast.Statement | None":
    """``Choose target non-Wall creature the active player has controlled
    continuously since the beginning of the turn. That creature attacks this
    turn if able. Destroy it at the beginning of the next end step if it didn't
    attack this turn.`` (Nettling Imp, Norritt.)

    Three sentences and one effect: "that creature" and "it" are both the
    creature the first sentence chose, and the destruction is conditional on
    what that creature did about the requirement the second one imposed.

    **This was a card hook**, keyed by name on the whole printed line — the
    activation restriction included. Norritt prints the identical ability with a
    shorter restriction ("Activate only before attackers are declared" against
    Nettling Imp's "Activate only during an opponent's turn, before attackers
    are declared") and so got nothing at all, which is the arithmetic
    `HOOK_RELIANCE.md` exists to measure: a name-keyed entry buys one card where
    a production buys every card printed the same way. Arcum's Whistle prints
    this same opening sentence with a payment rider and is one round further
    out.

    Every word of the noun phrase is read rather than skipped. "Non-Wall" and
    "the active player has controlled continuously since the beginning of the
    turn" are the two narrowings that make this creature choosable at all, and a
    production that consumed them into nothing would be a card that can force
    any creature to attack — including one that just arrived, which is the
    difference between this and Siren's Call.
    """
    if not stream.accept_phrase("choose", "target", "non-wall", "creature"):
        return None
    for word in (
        "the", "active", "player", "has", "controlled", "continuously",
        "since", "the", "beginning", "of", "the", "turn",
    ):
        if not stream.accept_word(word):
            return None
    if not stream.accept_punct("."):
        return None
    # Arcum's Whistle's tail, tried first because it is the one that opens with
    # a *payment*: the chosen creature's controller is offered its mana value,
    # and only a refusal imposes the requirement. Same opening sentence, same
    # requirement, same delayed destruction — so it is a tail of this production
    # rather than a second one, and the two narrowings above are read once.
    if _accept_pay_to_avoid_the_attack(stream):
        return ast.ForceChosenCreatureToAttack(unless_controller_pays_mana_value=True)
    if not stream.accept_phrase(
        "that", "creature", "attacks", "this", "turn", "if", "able"
    ):
        return None
    if not stream.accept_punct("."):
        return None
    if not stream.accept_phrase(
        "destroy", "it", "at", "the", "beginning", "of", "the", "next", "end",
        "step", "if", "it", "didn't", "attack", "this", "turn",
    ):
        return None
    return ast.ForceChosenCreatureToAttack()


def _accept_pay_to_avoid_the_attack(stream: TokenStream) -> bool:
    """``That player may pay {X}, where X is that creature's mana value. If they
    don't pay, the creature attacks this turn if able, and at the beginning of
    the next end step, destroy it if it didn't attack this turn.``
    (Arcum's Whistle.)

    Non-consuming on refusal, so Nettling Imp's shorter tail is read by the
    branch behind it.

    The X is required to be *that creature's mana value* rather than read as a
    number: the price is a fact about the object the sentence in front of it
    chose, and a printed {X} with any other definition would be a different
    offer. Read here as words for the reason the noun phrase above is — this
    whole paragraph is one production, and admitting a variable the lowering has
    no spec for would be an offer priced at nothing.
    """
    mark = stream.mark()
    if not stream.accept_phrase("that", "player", "may", "pay"):
        stream.reset(mark)
        return False
    if stream.accept_kind(MANA) is None:
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "where", "x", "is", "that", "creature", "'s", "mana", "value"
    ):
        stream.reset(mark)
        return False
    if not stream.accept_punct("."):
        stream.reset(mark)
        return False
    if not stream.accept_phrase("if", "they", "don't", "pay"):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "the", "creature", "attacks", "this", "turn", "if", "able",
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "and", "at", "the", "beginning", "of", "the", "next", "end", "step",
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "destroy", "it", "if", "it", "didn't", "attack", "this", "turn",
    ):
        stream.reset(mark)
        return False
    return True


def _parse_attacks_this_turn_if_able(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.AttacksThisTurnIfAble | None":
    """``<subject> attacks this turn if able.`` (Kookus.)

    The subject has already been read, so this starts at the verb. Every word of
    the duration and the escape is required: "attacks **each combat** if able"
    is the printed static one file over, and "attacks this turn" with the "if
    able" dropped would be a requirement CR 508.1a says a creature that cannot
    attack must somehow meet.

    Refuses without consuming, so a sentence opening on the same verb keeps its
    own reading and its own refusal.
    """
    mark = stream.mark()
    if not stream.accept_word("attacks", "attack"):
        return None
    window: str | None = None
    if stream.accept_phrase("this", "turn"):
        window = "this_turn"
    if not stream.accept_phrase("if", "able"):
        stream.reset(mark)
        return None
    if window is None and not stream.at_punct(".", ",", ";") and not stream.exhausted:
        # The durationless spelling exists only because the window was printed
        # in *front* of the sentence ("During that player's next turn, the
        # chosen creatures attack if able, and …", Oracle en-Vec), and a
        # leading duration is attached to a whole sentence rather than to a
        # clause inside one. So the sentence has to end here; anything else is
        # a longer sentence this production has not read, and consuming three
        # words of it would replace its refusal with one from the wrong place.
        stream.reset(mark)
        return None
    return ast.AttacksThisTurnIfAble(
        subject,
        destroy_if_absent=_accept_destroy_those_that_didnt_attack(stream),
        window=window,
    )


def _parse_destroy_chosen_that_didnt_attack(
    stream: TokenStream,
) -> "ast.DestroyChosenThatDidntAttack | None":
    """``At the beginning of that turn's end step, destroy each of the chosen
    creatures that didn't attack this turn.`` (Oracle en-Vec.)

    :func:`_accept_destroy_those_that_didnt_attack` reads the identical sentence
    as a *tail* of the requirement it belongs to, because Maddening Imp prints
    the two adjacent and says "those creatures". This card prints a third
    sentence between them and names the set outright, so the tail reader never
    sees it — and it does not need to, which is the whole content of the
    difference: "the chosen creatures" resolves against the record rather than
    against the sentence in front of it.

    Read **before** the delayed-trigger opener, whose table has a row for these
    very words: Final Fortune's "at the beginning of **that turn's** end step"
    names the extra turn its own sentence just queued (CR 500.7), and this one
    names a seat's next turn a sentence three clauses back described. Matched
    there first, the words would arm an ability for a turn nobody granted, and
    the lowering's refusal would take the whole line down.

    Non-consuming on refusal, so both readings above keep the stream they had.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "at", "the", "beginning", "of", "that", "turn", "'s", "end", "step",
    ):
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("destroy", "each", "of"):
        stream.reset(mark)
        return None
    subject = parse_target_spec(stream)
    if subject is None or subject.quantifier != "chosen":
        # The window is named by a *record*, so the set has to be too: an
        # ordinary noun phrase here would be a class re-read off the board a
        # turn later, which is not the set CR 608.2 fixed when the ability
        # resolved.
        stream.reset(mark)
        return None
    # "…that didn't attack this turn" is a postmodifier ``parse_object_filter``
    # has read since Siren's Call, so it is already inside the filter above and
    # is **not** consumed here — expecting the words as words would refuse the
    # sentence the noun parser had just read in full. Which narrowings the
    # lowering will accept is its business; the sentence has only to end.
    if not (stream.exhausted or stream.at_punct(".")):
        stream.reset(mark)
        return None
    return ast.DestroyChosenThatDidntAttack(subject)


def _accept_destroy_those_that_didnt_attack(stream: TokenStream) -> bool:
    """``. At the beginning of the next end step, destroy each of those
    creatures that didn't attack this turn`` — the tail Maddening Imp prints
    behind its requirement.

    Read here rather than as its own sentence, which is what
    ``_parse_force_chosen_creature_to_attack`` does one screen up for Nettling
    Imp's identical shape at singular scale: "those creatures" is the set the
    sentence in front of it described, and a production reading this sentence on
    its own would have nothing to resolve the words against. What the AST
    carries is therefore a flag on the requirement rather than a second
    statement.

    Non-consuming on refusal, so a card printing the requirement alone (Kookus,
    Boiling Blood) is unaffected and a card printing a *different* tail keeps
    its own refusal, naming the sentence this could not read.

    The full stop is consumed only when the whole tail is: a sentence boundary
    the caller still owns is the difference between reading two sentences and
    eating one.
    """
    mark = stream.mark()
    if not stream.accept_punct("."):
        return False
    if not stream.accept_phrase(
        "at", "the", "beginning", "of", "the", "next", "end", "step",
    ):
        stream.reset(mark)
        return False
    if not stream.accept_punct(","):
        stream.reset(mark)
        return False
    if not stream.accept_phrase(
        "destroy", "each", "of", "those", "creatures", "that", "didn't",
        "attack", "this", "turn",
    ):
        stream.reset(mark)
        return False
    return True


def _parse_blocks_this_turn_if_able(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.BlocksThisTurnIfAble | None":
    """``<subject> blocks <attacker> this turn if able.`` (Trumpeting Armodon.)

    The blocking twin of :func:`_parse_attacks_this_turn_if_able`, and the same
    shape: the subject has already been read, so this starts at the verb, and
    every word of the duration and the escape is required. "Blocks **each
    combat** if able" is the printed static ``engine/combat_restrictions.py``
    reads (Watchdog), so a production that consumed that spelling would take
    the table's line away — which is why the duration is matched exactly.

    What it carries that the attack twin does not is the **attacker**: a block
    is a pair (CR 509.1a), so the sentence names both halves and a requirement
    that dropped the second one would compel the creature to block anything at
    all.

    Refuses without consuming, so a sentence opening on the same verb keeps its
    own reading and its own refusal.
    """
    mark = stream.mark()
    if not stream.accept_word("blocks", "block"):
        return None
    # "That creature **blocks this turn if able**." (Provoke.) No attacker at
    # all — the weakest CR 509.1c requirement, and the one Watchdog prints as a
    # static: block *something* you legally can. Read first, on the words
    # themselves, because the two recipient readers below would otherwise be
    # asked to decline "this" as a noun and the sentence would refuse at the
    # wrong place.
    if stream.accept_phrase("this", "turn", "if", "able"):
        return ast.BlocksThisTurnIfAble(subject, None)
    attacker = parse_recipient(stream)
    if attacker is None:
        # "…block **that creature** this turn if able" (Magnetic Web). A
        # back-reference to the object the trigger's event was about, which
        # `parse_recipient` does not read — its pronouns are "it" and "itself",
        # and a demonstrative with a noun behind it is the bound subject
        # `parse_bound_subject` reads. Tried second so the pronoun spellings
        # keep their own reading, and refused by every lowering that has not
        # said otherwise, which is what makes reading it here safe.
        attacker = parse_bound_subject(stream)
    if attacker is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("this", "turn", "if", "able"):
        stream.reset(mark)
        return None
    return ast.BlocksThisTurnIfAble(subject, attacker)
