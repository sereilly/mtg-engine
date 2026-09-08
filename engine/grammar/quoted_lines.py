"""Whole printed lines whose **quotation marks** are what delimits them.

Four shapes, and the one thing they share is why they are here rather than in
``effects/``: the lexer throws quotation marks away, so a production reading the
token stream cannot tell a granted ability from the sentence around it. Each of
these is matched against the raw text instead — an emblem's ability (CR 114.2),
the reanimation Aura's whole entry line, Necromancy's "becomes an Aura with"
sentence, and Garruk's granted damage-assignment.

Split out of ``parser`` at the size guard, along the boundary that module had
already drawn in its own shape: ``parse_line`` routes a line carrying a ``QUOTE``
token here *before* the ordinary sentence loop, because that loop would refuse
every one of them on punctuation it never sees. Above nothing and below
``parser``, which is the only module that calls them; it reads ``ast`` and the
lexer and no other sibling.

:func:`_parse_becomes_aura_line` is the one production that re-enters the line
layer — what is left of its sentence is an ordinary line — so it takes that
entry point as an argument rather than importing it back, which is the cycle the
layer order forbids.
"""

from __future__ import annotations

import dataclasses
import re

from . import ast
from .lexer import SELF, tokenize


_EMBLEM_LINE_RE = re.compile(
    r'^\s*you get an emblem with\s+["“](?P<text>.+)["”]\.?\s*$',
    re.IGNORECASE | re.DOTALL,
)

# "Until end of turn, creatures you control gain "You may have this creature
# assign its combat damage as though it weren't blocked."" (Garruk, Savage
# Herald's −7.) The quoted grant is matched whole: the granted sentence IS the
# effect, so a paraphrase is a different card and must keep refusing.
_ASSIGN_UNBLOCKED_LINE_RE = re.compile(
    r'^\s*until end of turn, creatures you control gain\s+'
    r'["“]you may have this creature assign its combat damage as though it '
    r'wasn.t blocked\.?["”]\.?\s*$'
    .replace("wasn.t", r"(?:wasn|weren)['’]t"),
    re.IGNORECASE,
)


#: The reanimation Aura's entry line, whole (Animate Dead, Dance of the Dead) —
#: a whole-line pattern for the reason the emblem shape below is one: the
#: quotation marks are part of what the sentence says, and the three sentences
#: are one effect on one object rather than three statements. The two printings
#: differ by one verb and one word of timing, which is what makes this a
#: template rather than a card, and what retired the name-keyed hook that used
#: to claim the first of them. Exact on purpose: a card printing one of the
#: three sentences and not the others is a different card.
_REANIMATION_AURA_LINE_RE = re.compile(
    r'^\s*when this (?:aura|enchantment) enters, if it.s on the battlefield, '
    r'it loses ["“]enchant creature card in a graveyard["”] and gains '
    r'["“]enchant creature put onto the battlefield with this '
    r'(?:aura|enchantment)\.?["”]\.?\s*'
    r'(?:return|put) enchanted creature card (?:to|onto) the battlefield '
    r'(?P<tapped>tapped )?under your control and attach this '
    r'(?:aura|enchantment) to it\.\s*'
    r'when this (?:aura|enchantment) leaves the battlefield, '
    r'that creature.s controller sacrifices it\.?\s*$',
    re.IGNORECASE,
)


def _parse_reanimation_aura_line(line: str) -> "ast.TriggeredAbilityNode | None":
    """The reanimation Aura's entry line as one triggered ability, or None.

    Off the raw text, as the emblem shape below is: what the pattern pins down
    is the quoted rewrite and the sentence order, both of them punctuation the
    token stream has already discarded.
    """
    match = _REANIMATION_AURA_LINE_RE.match(line.strip())
    if match is None:
        return None
    return ast.TriggeredAbilityNode(
        ast.TriggerEvent(kind="enters_battlefield", word="when"),
        ast.ReanimateEnchantedCard(tapped=bool(match.group("tapped"))),
    )


#: ``It becomes an Aura with "enchant <quality>."`` (Necromancy) as a *sentence*
#: rather than as a whole line: the card prints it in the middle of an
#: enters-the-battlefield trigger, between the intervening-if and the sentence
#: that reanimates a creature and attaches the enchantment to it.
#:
#: Matched off the raw text for :data:`_EMBLEM_LINE_RE`'s reason — the quotation
#: marks are what delimit the granted ability, and the lexer has already thrown
#: them away by the time a production could look. What comes out is not a
#: rewrite of the sentence but its *removal*: the quoted clause becomes an
#: :class:`ast.BecomeAura` node and the rest of the line is handed back to the
#: ordinary parser, which is the same shape ``oracle.expand_conjoined_trigger_lines``
#: uses one layer up — a line every reader downstream already knows how to read.
_BECOMES_AURA_SENTENCE_RE = re.compile(
    r'(?P<head>^.*?)\bit becomes an aura with '
    r'["“]enchant (?P<quality>[^"”]+?)\.?["”]\.?\s*'
    r'(?P<tail>.*)$',
    re.IGNORECASE | re.DOTALL,
)

#: The one enchant quality this engine can *test* on a permanent that became an
#: Aura: a head noun plus CR 201.5's self-reference ("creature put onto the
#: battlefield with Necromancy"). The rider is the whole sentence — it is what
#: stops the Aura being moved onto a creature it never reanimated — so a quality
#: naming anything else refuses here rather than being admitted with the rider
#: dropped. `engine/auras.enchant_card_refusal` is what tests it.
_BECOMES_AURA_QUALITY_RE = re.compile(
    r'^(?P<noun>[a-z]+) put onto the battlefield with (?P<owner>.+?)\.?$',
    re.IGNORECASE,
)


def _parse_becomes_aura_line(
    line: str, *, card_name: str | None = None, parse
) -> "ast.AbilityNode | None":
    """*line* with its ``becomes an Aura with "…"`` sentence lifted out, or None.

    The sentence is replaced by an :class:`ast.BecomeAura` step at the front of
    whatever the rest of the line says, so the trigger prefix, the intervening
    "if", the reanimation and the trailing delayed ability behind it are read by
    the ordinary productions rather than by a second whole-line pattern.
    Refusing (None) leaves the quote guard's own error standing, which is what
    every other card carrying a quote still gets.

    The self-reference is asked of the **lexer**, never of the card's name in
    this file: ``tokenize`` collapses a card naming itself into one ``SELF``
    token (CR 201.5), so "with Necromancy" is recognised by what the token
    stream says and a card printing a different name in that slot refuses.
    """
    match = _BECOMES_AURA_SENTENCE_RE.match(line.strip())
    if match is None:
        return None
    quality = _BECOMES_AURA_QUALITY_RE.match(match.group("quality").strip())
    if quality is None:
        return None
    owner = tokenize(quality.group("owner"), card_name=card_name)
    if len(owner.tokens) != 1 or owner.tokens[0].kind != SELF:
        return None
    rest = f"{match.group('head').strip()} {match.group('tail').strip()}".strip()
    if not rest:
        return None
    # The removed sentence sat mid-line, so what followed it was capitalised as
    # a sentence and what preceded it ended in a comma. Lower-casing the join is
    # the whole fix-up: every production below reads a normalized stream, and
    # the one thing the raw text still has to be is a grammatical sentence.
    if match.group("head").strip():
        rest = rest[:1].lower() + rest[1:]
    node = parse(rest, card_name=card_name)
    become = ast.BecomeAura(noun=quality.group("noun").lower(), origin_is_source=True)
    statement = getattr(node, "statement", None)
    if statement is None:
        return None
    steps = (
        statement.steps if isinstance(statement, ast.Sequence) else (statement,)
    )
    return dataclasses.replace(node, statement=ast.Sequence((become, *steps)))


def _parse_emblem_line(line: str) -> "ast.CreateEmblem | None":
    """The whole-line emblem shape, read off the raw text.

    Raw rather than token-by-token because the payload IS the raw text: the
    quoted ability keeps its printed casing and punctuation, which is what the
    compiler will read when the emblem fires.
    """
    match = _EMBLEM_LINE_RE.match(line.strip())
    if match is None:
        return None
    return ast.CreateEmblem(text=match.group("text").strip())


#: ``…becomes a 4/4 Serpent creature with "<ability>."`` (Veiled Serpent) and
#: ``…with flying and "<ability>."`` (Veiled Apparition) — a creature body whose
#: last item is a whole printed ability rather than a keyword.
#:
#: Matched off the raw text for this module's standing reason: the lexer throws
#: the quotation marks away, so the token stream cannot tell where the granted
#: ability begins. Both joining words are read, because both are printed and
#: they differ only in whether a keyword came first — "with" opens the body's
#: list and "and" continues it.
#:
#: ``head`` is non-greedy so the split falls at the **first** joining word a
#: quote follows: Veiled Apparition prints "with flying and "…"", where "with"
#: is followed by a keyword and only "and" by the quote.
_BECOMES_WITH_GRANTED_ABILITY_RE = re.compile(
    r'(?P<head>^.*\bbecomes an? .*?)\s+(?:and|with)\s+'
    r'["“](?P<granted>.+?)["”]\.?\s*$',
    re.IGNORECASE | re.DOTALL,
)


def _parse_becomes_with_granted_ability(
    line: str, *, card_name: str | None = None, parse
) -> "ast.AbilityNode | None":
    """*line* with the quoted ability lifted off its creature body, or None.

    The same removal :func:`_parse_becomes_aura_line` performs and for the same
    reason: what is left is an ordinary line, so the trigger prefix, the
    intervening "if" and the creature body behind it are read by the ordinary
    productions rather than by a second whole-line pattern.

    Three refusals, each of them a card this has *not* understood rather than a
    convenience:

    * the rest of the line must lower to a creature body. "…gains "…"" is a
      layer-6 grant with no animation in it and belongs to whatever production
      reads that sentence, not to this one;
    * the granted text must **parse as an ability line**, checked here through
      the same entry point the card's own lines go through. A grant of text no
      reader claims is a permanent that says something the engine will drop —
      the failure the support gate exists to make loud;
    * exactly one quoted ability, which is all the pool prints. A body granting
      two would need the joining word read between them, and consuming only the
      last is the dropped-rider bug this grammar refuses by construction.
    """
    match = _BECOMES_WITH_GRANTED_ABILITY_RE.match(line.strip())
    if match is None:
        return None
    granted = match.group("granted").strip()
    if '"' in granted or "“" in granted or "”" in granted:
        return None
    head = match.group("head").strip()
    if not head.endswith("."):
        head += "."
    try:
        node = parse(head, card_name=card_name)
    except Exception:
        return None
    statement = getattr(node, "statement", None)
    if not isinstance(statement, ast.BecomeCreature):
        return None
    try:
        parse(granted, card_name=card_name)
    except Exception:
        return None
    return dataclasses.replace(
        node,
        statement=dataclasses.replace(
            statement, granted_ability_lines=(granted,)
        ),
    )
