"""Trigger events whose subject the sentence **names** rather than quantifies.

Four productions, and one property holds all four together: the permanent the
event is about is known from the ability's own position — it is the source
("whenever **this land** becomes tapped", City of Brass) or the permanent the
source is attached to ("whenever **enchanted creature** attacks or blocks",
Imprison) — so no noun phrase is parsed and no filter is chosen from.

That is what separates them from `_parse_quantified_tap_event` next door, which
reads "**a Forest an opponent controls** becomes tapped" through the noun
parser. The two readings of "becomes tapped" disagree about what the words in
front of the verb are, and a named subject must be tried first: `parse_target_spec`
would happily claim "enchanted land" as a quantified subject and name a condition
`engine/oracle.py`'s table does not.

Split out of `triggers` at the thousand-line guard, along the boundary that
module already drew — these four sat together, called together, and reach
nothing the trigger tables hold. Below `triggers`, which imports them: they read
tokens and build events, and nothing in them needs a table.
"""

from __future__ import annotations

from . import ast
from .lexer import MANA, SELF
from .stream import TokenStream


def _accept_ability_activated_tail(stream: TokenStream) -> bool:
    """"…or a player activates an artifact's ability without {T} in its
    activation cost" — the second trigger event of a tap-or-activate ability.

    All-or-nothing: a partial match rewinds, so a line that says something else
    after "becomes tapped" keeps its tokens and the plain tap reading stands.
    """
    mark = stream.mark()
    if not stream.accept_word("or"):
        stream.reset(mark)
        return False
    if not (
        stream.accept_phrase("a", "player", "activates")
        or stream.accept_phrase("an", "opponent", "activates")
    ):
        stream.reset(mark)
        return False
    # "an artifact's ability" / "an ability of enchanted artifact" — the object
    # whose ability it is repeats the subject already parsed, so it is consumed
    # rather than re-read. Whatever it named, the ability belongs to the same
    # set of permanents the tap half describes; a card pairing two *different*
    # subjects would not consume its line and would fall back.
    while not stream.exhausted and not stream.at_word("without"):
        stream.advance()
    if not stream.accept_word("without"):
        stream.reset(mark)
        return False
    token = stream.peek()
    if token is None or token.kind != MANA or token.text != "{T}":
        stream.reset(mark)
        return False
    stream.advance()
    if not stream.accept_phrase("in", "its", "activation", "cost"):
        stream.reset(mark)
        return False
    return True



def _parse_attached_combat_event(
    stream: TokenStream, word: str
) -> ast.TriggerEvent | None:
    """"Whenever **enchanted creature** attacks or blocks" (Imprison).

    The same event ``_WHENEVER_EVENTS`` holds for "this creature", watched by
    an Aura or Equipment rather than by the creature itself — one kind, because
    it is one event, and whose ability is watching is the narrowing.

    A production rather than another row of that table, and the *subject* is
    why: a table row builds an event with none, and the effect behind this one
    says "tap the creature, remove **it** from combat". With no subject on the
    event `rebinding.py` leaves the pronoun pointing at the ability's own
    source, and the Aura would tap and remove *itself*.
    """
    mark = stream.mark()
    if not stream.accept_word("enchanted"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("attacks", "or", "blocks"):
        stream.reset(mark)
        return None
    return ast.TriggerEvent(
        "creature_attacks_or_blocks", word,
        subject=ast.ObjectFilter(is_enchanted=True, card_types=(noun,)),
    )



def _parse_ability_activated_event(
    stream: TokenStream, word: str
) -> ast.TriggerEvent | None:
    """"Whenever a player activates an ability of **enchanted creature** with
    {T} in its activation cost that isn't a mana ability" (Imprison).

    The activation event on its own, where :func:`_accept_ability_activated_tail`
    reads the same clause joined onto a *tap* event. Two events, not two
    wordings of one: Artifact Possession's card fires when its host is tapped
    for any reason at all, and this one never does — so a card printing this
    must not answer to an attack that taps the creature.

    Both printed narrowings ride the event rather than the kind. Which side of
    {T} the cost falls on is one word, and the noun after "enchanted" is what
    the attached permanent has to be; `engine/events.py`'s filter reads both.
    """
    mark = stream.mark()
    if not (
        stream.accept_phrase("a", "player", "activates")
        or stream.accept_phrase("an", "opponent", "activates")
    ):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("an", "ability", "of", "enchanted"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not (stream.at_word("with") or stream.at_word("without")):
        stream.reset(mark)
        return None
    stream.advance()
    token = stream.peek()
    if token is None or token.kind != MANA or token.text != "{T}":
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("in", "its", "activation", "cost"):
        stream.reset(mark)
        return None
    # Required, not optional. Without the exclusion the printed condition also
    # covers mana abilities, which never use the stack (CR 605.3a) and so are
    # announced nowhere — a card admitted without it would fire on strictly
    # fewer events than it prints, silently.
    if not stream.accept_phrase("that", "isn't", "a", "mana", "ability"):
        stream.reset(mark)
        return None
    return ast.TriggerEvent(
        "nonmana_ability_activated", word,
        subject=ast.ObjectFilter(is_enchanted=True, card_types=(noun,)),
    )



def _parse_named_subject_tap_event(
    stream: TokenStream, word: str
) -> ast.TriggerEvent | None:
    """"When(ever) **enchanted <noun>** / **this <noun>** becomes tapped" —
    CR 701.26a's event about a subject the sentence *names* rather than
    quantifies.

    One production for both subjects and both trigger words, because they are
    one event: `engine/oracle.py`'s table used to spell "enchanted land"
    (Psychic Venom) and "this land" (City of Brass) as conditions of their own,
    and a kind of its own is what let each be dispatched by a pass inside
    `tap_land_for_mana` that fired on the single tapper it sat in. The subject
    rides the event; who tapped is `become_tapped`'s business either way.

    The compound tail is read first where it is present (Artifact Possession's
    "…**or a player activates an ability of enchanted artifact**"): that clause
    has the plain tap reading as a strict prefix, so returning the plain event
    first would leave the rest of the *condition* to be parsed as the effect.
    """
    mark = stream.mark()
    if stream.accept_word("enchanted"):
        noun = stream.peek_word()
        if noun is not None:
            stream.advance()
            if stream.accept_phrase("becomes", "tapped"):
                subject = ast.ObjectFilter(is_enchanted=True)
                if _accept_ability_activated_tail(stream):
                    return ast.TriggerEvent(
                        "permanent_tapped_or_ability_activated", word,
                        subject=subject,
                    )
                return ast.TriggerEvent(
                    "permanent_becomes_tapped", word, subject=subject,
                )
    stream.reset(mark)
    # "**This** land becomes tapped" — the source itself. The self-reference
    # arrives either as the SELF token (the card's own name, which
    # `normalize_creature_line` leaves in place) or as the word "this" with the
    # printed type behind it.
    if stream.at_kind(SELF) or stream.at_word("this"):
        stream.advance()
        if not stream.at_kind(SELF):
            stream.accept_word("creature", "artifact", "enchantment", "land", "permanent")
        if stream.accept_phrase("becomes", "tapped"):
            return ast.TriggerEvent(
                "permanent_becomes_tapped", word,
                subject=ast.ObjectFilter(is_source=True),
            )
    stream.reset(mark)
    return None


