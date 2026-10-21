"""Activation instructions (CR 602.1b): the text after an activated ability's
effect that says who may activate it, when, or what some part of its cost is.

CR 602.1 writes an activated ability as "[Cost]: [Effect.] [Activation
instructions (if any).]", and CR 602.1b says that last part "is not part of the
ability's effect". The readers here take the shapes the pool prints: "Activate
only during your upkeep." and "Any player may activate this ability." (when, and
who), "X can't be 0." (CR 601.2b's announced value), "X is the number of pin
counters on this artifact." (Voodoo Doll) and "Spend only red mana on X."
(Crimson Hellkite). Each is recorded as an ``ast.ActivationRestriction`` and
lowered to nothing: the activation path enforces it off the raw
``ability.source_line``, through a table the reader *asks* rather than copies
(``engine/activation_restrictions.py``, ``activation_permissions.py``,
``cost_x_definitions.py``, ``oracle_types.x_spend_colors_from_text``). So the
grammar's job is to account for the tokens, and to refuse a sentence nothing
enforces.

Pre-split out of ``effects/stack.py`` at Torment's Phase 0, when that module
sat 38 lines under the thousand-line guard. Its docstring listed these readers
("the activation restrictions … that gate an ability") beside a subject they do
not share: everything else there is a sentence about an object *on* the stack,
and these say whether an ability may be put there at all. None of them acts on
a stack object, none lowers in ``lowering/stack.py``, and the node they build is
not in ``ast/stack.py`` but in ``ast/lines.py``, among the parts "only a line is
built from". They were one 28-line reader when the grammar became a package and
are three readers and 167 lines now. The module's name is the CR's.

Outside ``effects/`` because they are not effects, which is CR 602.1b's own
sentence and the one each reader below repeats ("the sentence belongs to the
ability rather than to the effect"). Under it in the layer order because a
family reads one: the modal head in ``effects/stack.py`` takes "Choose one.
Activate only if …" (Triassic Egg) through :func:`_parse_activation_restriction`.
``sequences``, the loop that reads a line's trailing sentences and the other
caller, imports all three from here. No mirror name to reuse: nothing lowers
them.
"""

from . import ast
from .lexer import SELF
from .stream import TokenStream


def _parse_cost_x_definition(stream: TokenStream) -> ast.ActivationRestriction | None:
    """A trailing "X is the number of pin counters on this artifact." sentence
    (Voodoo Doll) — what the ability's **cost** X is, when the card says.

    The same arrangement as :func:`_parse_activation_restriction` below, for the
    same reason: the sentence belongs to the ability rather than to the effect,
    and what enforces it is the activation path, which reads the raw text. The
    grammar's job is to account for the tokens — and, through
    ``engine/cost_x_definitions.py``, to refuse a definition nothing computes.

    Refusing is the whole point of asking that module rather than matching "x
    is" here: an unimplemented definition consumed silently would leave the
    activator announcing X freely on a cost the card fixes, which on a {X}{X}
    ability is free.
    """
    from ..cost_x_definitions import cost_x_definition_readable

    mark = stream.mark()
    stream.accept_punct(".", ";")
    if not stream.at_word("x") or stream.peek_word(1) != "is":
        stream.reset(mark)
        return None
    words: list[str] = []
    while not stream.exhausted and not stream.at_punct("."):
        words.append(str(stream.next().text))
    sentence = " ".join(words).replace(" '", "'")
    if not cost_x_definition_readable(sentence):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    return ast.ActivationRestriction(sentence)


def _parse_x_spend_restriction(stream: TokenStream) -> ast.ActivationRestriction | None:
    """A trailing "Spend only red mana on X." sentence (Crimson Hellkite).

    The third rider in this family, and the same arrangement as the two beside
    it: the sentence constrains the ability's **cost**, not its effect, so the
    grammar accounts for the tokens and ``mixins/stack/activation.py`` — which
    reads the raw ``ability.source_line`` — is what charges the colour.

    Read through ``oracle_types.x_spend_colors_from_text``, the same function
    the enforcement calls, rather than by matching the words here. That is the
    rule the two siblings state: a copy of the phrase in the grammar is free to
    drift from the code that acts on it, and a drifted copy consumes a
    restriction nobody applies — which on an {X} cost is the caster paying the
    colour they happen to have.
    """
    from ..oracle_types import x_spend_colors_from_text

    mark = stream.mark()
    stream.accept_punct(".", ";")
    if not stream.at_word("spend"):
        stream.reset(mark)
        return None
    words: list[str] = []
    while not stream.exhausted and not stream.at_punct("."):
        words.append(str(stream.next().text))
    sentence = " ".join(words).replace(" '", "'")
    colours = x_spend_colors_from_text(sentence)
    if len(colours) != 1:
        # No colour read at all, or the "black **and/or** red" pair. The pair is
        # refused rather than charged as its first colour: splitting X between
        # two colours is the activator's CR 601.2h choice, and the machinery
        # that makes it (``casting._x_color_allocations``) is on the spell path
        # only. Charging the first colour alone would make the ability
        # *unpayable* from a pool the card allows — a restriction wrong in the
        # other direction, and still a restriction the card does not print.
        # No card in the pool prints the pair on an activated ability; the day
        # one does, it reports unsupported naming this sentence.
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    return ast.ActivationRestriction(sentence)


def _parse_activation_restriction(stream: TokenStream) -> ast.ActivationRestriction | None:
    """A trailing "Activate only …" / "Any player may activate this ability."
    sentence on an activated ability.

    Recorded on the AST and lowered to nothing. The restriction is *enforced*
    from the raw ability text in ``mixins/stack/activation.py``, which reads
    ``ability.source_line`` -- so consuming the sentence here drops no behaviour,
    it only lets the line satisfy the grammar's full-consumption invariant.

    "Drops no behaviour" is true **only of a clause something enforces**, which
    is why both branches below ask the module that enforces theirs. The
    permission branch already did; the "Activate ..." branch consumed the rest
    of the sentence verbatim and asked nothing, so Vampire Bats' "Activate no
    more than twice each turn" satisfied the invariant against a table with no
    row for it -- the card compiled supported with an uncapped {B} pump. A
    clause `engine/activation_restrictions.py` cannot read now leaves the line
    refused, and the card reports unsupported naming the sentence.
    """
    from ..activation_permissions import permission_clause_readable
    from ..activation_restrictions import (activation_restriction_line,
                                           x_zero_restriction_line)

    mark = stream.mark()
    stream.accept_punct(".", ";")
    words: list[str] = []
    # "X can't be 0." (Aladdin's Lamp, Helm of Obedience.) A constraint on the
    # value chosen for X (CR 601.2b) rather than on when the ability may be
    # activated, so it opens on a different word and is enforced by a different
    # gate — but it is the same *kind* of sentence, a rider on the ability line
    # whose enforcement lives outside the compiled program, and it is admitted
    # here on the same terms: the module that enforces it says whether it can
    # read the sentence, and a wording that module cannot read leaves the line
    # refused.
    if stream.at_word("x"):
        x_mark = stream.mark()
        probe: list[str] = []
        while not stream.exhausted and not stream.at_punct("."):
            probe.append(str(stream.next().text))
        sentence = " ".join(probe).replace(" '", "'")
        if x_zero_restriction_line(sentence):
            stream.accept_punct(".")
            return ast.ActivationRestriction(sentence)
        stream.reset(x_mark)
        stream.reset(mark)
        return None
    if stream.accept_word("activate"):
        words.append("activate")
    elif stream.at_word("any", "only"):
        # A "who may activate" permission (CR 602.1a). The spellings used to be
        # listed here as literal token sequences -- a fourth copy of a table
        # `engine/activation_permissions.py` now holds -- so a permission the
        # engine could not enforce still consumed its line and the card was
        # admitted with the clause dropped. The sentence is read verbatim and
        # handed to that module, which is the code that enforces it: a shape it
        # does not implement leaves the line refused.
        probe_words: list[str] = []
        while not stream.exhausted and not stream.at_punct("."):
            probe_words.append(str(stream.next().text))
        sentence = " ".join(probe_words).replace(" '", "'")
        if not permission_clause_readable(sentence):
            stream.reset(mark)
            return None
        stream.accept_punct(".")
        return ast.ActivationRestriction(sentence)
    else:
        stream.reset(mark)
        return None
    # Consume the remainder of the sentence verbatim; the enforcing code reads
    # the original text, so the grammar only has to account for the tokens --
    # but only once that code has said it can read the sentence at all.
    #
    # A SELF token is rendered as the phrase rather than as the name the lexer
    # collapsed. "Activate only if **Hakim** isn't enchanted" reaches the
    # enforcement path as printed text and reaches *this* path as tokens, and
    # the two have to hand `activation_restrictions` the same sentence or the
    # gate and the grammar disagree about which cards are readable — so both
    # sides say `_SELF_SUBJECT`, the enforcement path by collapsing the name and
    # this one by never having it.
    from ..activation_restrictions import _SELF_SUBJECT

    while not stream.exhausted and not stream.at_punct("."):
        token = stream.next()
        words.append(
            _SELF_SUBJECT if token.kind == SELF else str(token.text)
        )
    sentence = " ".join(words).replace(" '", "'")
    if not activation_restriction_line(sentence):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    return ast.ActivationRestriction(sentence)
