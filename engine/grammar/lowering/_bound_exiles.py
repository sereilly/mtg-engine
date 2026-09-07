"""An exile whose object the sentence names by **reference**.

The exile family's twin of ``_bound_returns``, and it carries that module's name
and its line for its reason. That file is titled "a return whose object the
sentence names by reference", and says of its two references:

    "The firing event recorded the object ("return **that card**", "return
    **it**"), or it is the ability's own source ("return **this card**"). Either
    way the object was fixed before this sentence ran, so nothing is matched and
    nothing is picked: the only question left is where that object is *now* …
    Which is why every narrowing check below is a **refusal** rather than a
    payload."

Every branch here answers that description word for word, one keyword action
over. Nothing below resolves a target, offers a prompt or carries a filter to a
handler: the object is the one a delayed ability was armed about (CR 603.7c),
the one a damage trigger froze (CR 603.10), the one an earlier step of this same
resolution put onto the battlefield or created as a token, or the ability's own
source. What is left to decide is only which handler reads which record, and
every rider the sentence prints beyond that refuses rather than being dropped —
an exile that lost its counters is a card whose second ability can never fire.

Split out of ``lowering/exile.py`` at Exodus' second wave, when that module sat
four lines from the thousand-line guard after wave 1 trimmed a comment to stay
under it. The cut is not a new line. ``exile.py``'s remaining branches all pick
their object out of the game — a target announced under CR 601.2c, a sweep
matched with ``subject_matches``, a pile the resolving seat is prompted for —
and each of them carries a filter payload to its handler. These carry none. The
same division ``returns`` was cut on at Alliances, and the reason the two halves
grow at different rates: a reference is read once and then reused by every card
printing the same pronoun, where the describing half grows with the vocabulary
of printed noun phrases.

**Two entry points, because the chain reads them at two different points.**
:func:`lower_restated_noun_exile` is read *before* the sweep and pile
quantifiers, since "exile **that creature**" restates a noun phrase and has to
be told apart from "exile **each** creature" by its quantifier before either is
tried; :func:`lower_pronoun_exile` is read *after* them, because "the creature",
"it", "that token" and "the token" print no card type at all and the branches
around them are what say which is which. Splitting them would put one reference
in two modules, which is the fork this file exists to close; ordering them
inside one function would move a branch across the sweep, which is a behaviour
change dressed as a cut. Each returns ``None`` where the sentence is not one of
its own, so ``_lower_exile``'s order is exactly what it was.

A floor rather than a family, for ``_bound_returns``' reason exactly: ``exile``
is its only reader and a family may not import a sibling. It reads ``_common``,
``_events`` and ``_delays``, and nothing reads back.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (_filter_payload, _is_created_token, _is_source,
                      _restrictions_beyond)
from ._delays import _BOUND_OBJECT_DELAYED_EVENTS
from ._events import (_RECORDED_PERMANENTS, CREATED_TOKEN,
                      damage_trigger_names_damaged_end)


def _entering_counter_payload(
    counters: "tuple[tuple[str, int | ast.Var], ...]",
) -> dict[str, "int | str"]:
    """``((counter word, how many), …)`` as the payload every counter handler
    reads.

    The count is a printed number or the cast's X, and ``ast.Var`` is how the
    parse spells the second (CR 107.3). It becomes the *string* ``"x"`` here
    because that is the one spelling ``handlers/_common.resolve_amount`` reads,
    and a payload carrying an AST node would be a second answer to "what is this
    number" that no handler asks.

    One converter for both branches that write this key, so the self-exile and
    the spell exile cannot come to disagree about how a variable count travels.

    Those two branches are now one on each side of this cut — the self-exile
    below, the targeted-spell exile back in ``exile`` — so it lives here, in the
    module underneath both, and is imported back up. A fragment two readers
    share belongs below them; keeping it in ``exile`` would have made the floor
    import the family.
    """
    return {
        name: (count.name if isinstance(count, ast.Var) else int(count))
        for name, count in counters
    }


def lower_restated_noun_exile(
    node: ast.Exile,
    subject: "ast.Recipient",
    event: str | None,
    event_subject: object | None,
) -> "tuple[OracleInstruction, ...] | None":
    """The reference printed as a **restated noun phrase** — "exile that creature".

    ``None`` where the sentence is not one, so ``_lower_exile`` falls through to
    the pile and sweep readings after it exactly as it did when this branch sat
    inline.
    """
    # "…**exile that creature**." (Coffin Queen, inside the delay its activated
    # ability creates.) The object the delayed ability was armed about
    # (CR 603.7c), addressed by id out of the trigger's context — the same
    # reading `destroy_bound_permanent` takes of the same two words one family
    # over, and its own kind for that handler's reason: routed through the
    # targeted exile it would ask for a choice the card never offered and then
    # exile whichever permanent the resolution context happened to carry.
    #
    # Gated on the *event*, like every other reading of "that <noun>" in this
    # grammar. Under an event that freezes no object the words name nothing at
    # all, and a refusal is the honest answer rather than a handler that finds
    # nothing while the card compiles supported.
    #
    # Narrowed to the **restated noun phrase**, which is what tells this apart
    # from the other three references that carry the same quantifier: "the
    # token" (Stangg, Dance of Many) and "that card" name objects with no card
    # type printed on them, and each has its own branch below. Reading them
    # here refused two long-supported cards on a gate that was never about
    # them.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
        and subject.filter.card_types
        and not subject.filter.created_with_source
    ):
        if node.counters or node.face_down or node.same_zone:
            raise LoweringError(
                "the bound-object exile carries no rider", node=node
            )
        if damage_trigger_names_damaged_end(event, event_subject):
            # "Whenever this creature deals damage to a creature, **exile that
            # creature**." (Pit Spawn.) The immediate twin of Lowland
            # Basilisk's delayed destroy, one keyword action over.
            # `damage_events._announce` stamps the damaged permanent as the
            # trigger's **target** (`target_permanent_id`), which is what lets
            # this ride the ordinary targeted exile with no `targets`
            # description — nothing is chosen, exactly as
            # `destroy_target_permanent` reads the same stamp for the same
            # sentence in the destruction family. Gated on
            # :func:`damage_trigger_names_damaged_end` rather than on the kind,
            # which is that helper's whole point: under Mangara's Equity's
            # spelling the same two words name the *damager*.
            if _restrictions_beyond(subject.filter, frozenset({"card_types"})):
                raise LoweringError(
                    "a creature named by a damage trigger carries no narrowing "
                    "the exile could honour", node=node,
                )
            return (
                OracleInstruction(
                    "exile_target_permanent", "", _filter_payload(subject.filter)
                ),
            )
        if event not in _BOUND_OBJECT_DELAYED_EVENTS:
            raise LoweringError(
                "\"that\" names the firing event's object, and this event "
                "records none",
                node=node,
            )
        # The **same kind and the same empty payload** the "exile it" branch
        # below already emits (Zirilan of the Claw, Shallow Grave): the two
        # sentences name one object two ways, and the id the arming handler
        # froze is what says which. The noun is read and not carried, for
        # ``destroy_event_subject``'s stated reason — the phrase re-states what
        # the ability was already aimed at, and asking again at resolution
        # would let a creature that stopped being one escape an exile the rules
        # have already aimed at it.
        return (OracleInstruction("exile_bound_permanent", "", {}),)
    return None


def lower_pronoun_exile(
    node: ast.Exile,
    subject: "ast.Recipient",
    produced: frozenset[str],
    event: str | None,
) -> "tuple[OracleInstruction, ...] | None":
    """The references printed as a **pronoun**, and the card naming itself.

    "The creature", "it", "that token", "the token" — none of which prints a
    card type, which is what keeps them out of :func:`lower_restated_noun_exile`
    above — and "this creature", the source (CR 109.5). ``None`` where the
    sentence is none of them, so the several-target, hand and single-target
    readings after it are reached exactly as they were.
    """
    # "When **the creature** dies this turn, exile **the creature**."
    # (Whippoorwill.) Idiom 20's pronoun, inside a delayed ability that bound
    # an object: the words name the creature the *creating* ability targeted,
    # not the ability's own source (CR 603.7d makes the source the Whippoorwill
    # and the sentence is not about it). By the time this fires that creature
    # is a card in a graveyard, so what is exiled is the card — which is why it
    # is its own kind rather than a payload flag on ``exile_self``: one handler
    # moves a permanent off a battlefield and the other moves a card out of a
    # pile, and they share nothing.
    #
    # Read above the source branch below, which cannot tell the two apart: the
    # noun parser collapses "the creature" onto the same bare-pronoun spec "it"
    # produces (quantifier ``it``, ``is_source``), where a card naming itself
    # ("this creature", Archfiend's Vessel) parses to quantifier ``this``. That
    # collapse is why Whippoorwill exiled **itself** whenever its target died —
    # supported, tested by nothing, and invisible to every census in the repo.
    #
    # ``bound_permanent_dies`` alone, not every bound-object delay: it is the
    # one whose fire site records the dead card. Under a leaves-the-battlefield
    # or end-of-combat delay the object may still be on a battlefield, which is
    # a different move and a different handler.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "it"
        and _is_source(subject)
        and event == "bound_permanent_dies"
    ):
        if node.duration.kind is not None or node.counters:
            raise LoweringError(
                "a bound card's exile carries no duration or counters", node=node
            )
        return (OracleInstruction("exile_bound_card", "", {}),)
    # "Exile it." / "Exile this creature." (Archfiend's Vessel.) The ability's
    # own source, which is not a chosen target at all — nothing is picked, so
    # there is no picker, no legality check and nothing to re-resolve if it has
    # moved. It gets its own instruction kind for that reason rather than a
    # payload flag on the targeted exile: a handler that resolves a target and
    # one that reads ``context.source_permanent`` share no code beyond the move.
    # "Return the top creature card of your graveyard to the battlefield. …
    # **Exile it** at the beginning of the next end step." (Shallow Grave;
    # Zirilan of the Claw prints the same tail behind a search.) The pronoun
    # reads as the source everywhere else, and here the source is a spell or
    # an activated ability — so `exile_self` exiled nothing while the card
    # compiled clean. What it names is the permanent an earlier step of this
    # same resolution put onto the battlefield.
    #
    # `produced` is the whole gate, and it is what keeps Dark Maze's "Exile
    # it at the beginning of the next end step" reading as its own source:
    # nothing in that effect records a permanent, so the branch declines and
    # the source reading below stands.
    if (
        _is_source(subject)
        and isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "it"
        and (produced & _RECORDED_PERMANENTS)
    ):
        if node.duration.kind is not None or node.counters:
            raise LoweringError(
                "an exile of a recorded permanent carries no duration or "
                "counters", node=node,
            )
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if len(recorded) != 1:
            raise LoweringError(
                "several earlier steps recorded permanents; which one \"it\" names is ambiguous",
                node=node,
            )
        return (OracleInstruction("exile_bound_permanent", "", {}),)
    if _is_source(subject):
        if node.duration.kind is not None:
            raise LoweringError(
                "a timed exile of the source has no handler", node=node
            )
        # "…**with two scream counters on it**" (All Hallow's Eve). Payload, so
        # the counter word and the number never reach an instruction *kind*;
        # the handler registers the exiled card with them
        # (``engine/exiled_records.py``) and the card's own upkeep trigger
        # reads them back off the register.
        payload: dict = {}
        if node.counters:
            payload["counters"] = _entering_counter_payload(node.counters)
        return (OracleInstruction("exile_self", "", payload),)
    # "Exile **that token**…" (Stangg). The token this same effect created,
    # addressed by the id the token maker wrote to the scratchpad — not a
    # chosen target and not the source, so it gets its own kind for the reason
    # ``exile_self`` has one: a handler that reads a recorded id and one that
    # resolves a target share nothing beyond the move.
    #
    # ``produced`` is the whole gate. With no token maker in front of it there
    # is no id to read, and an exile that silently found nothing would be a
    # card that reports itself supported and does nothing.
    if _is_created_token(subject):
        if node.duration.kind is not None:
            raise LoweringError(
                "a timed exile of a created token has no handler", node=node
            )
        if CREATED_TOKEN not in produced:
            raise LoweringError(
                "back-reference to a created token with no token maker in "
                "this effect",
                node=node,
            )
        return (OracleInstruction("exile_created_token", "", {}),)
    # "Exile **the token**." (Dance of Many.) The same object one reach
    # further out: the token this *permanent* created, rather than the token
    # this *resolution* created. Dance of Many prints the sentence as an
    # ability of its own, so by the time it fires the scratchpad the branch
    # above reads is long gone — what survives is the record the token maker
    # stamped on the token, which is why this is a payload variant of that
    # kind and not a second kind. There is no `produced` gate for the same
    # reason: the token maker is a different line of the same card, and a
    # permanent that made no token has nothing to exile, which is CR 608.2b.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.filter.created_with_source
        and subject.filter.token_only
        and subject.quantifier == "that"
    ):
        if node.duration.kind is not None:
            raise LoweringError(
                "a timed exile of a created token has no handler", node=node
            )
        leftovers = _restrictions_beyond(
            subject.filter, frozenset({"token_only", "created_with_source", "zone"})
        )
        if leftovers:
            raise LoweringError(
                f"the created-token exile does not honour {leftovers[0]!r}",
                node=node,
            )
        return (
            OracleInstruction(
                "exile_created_token", "", {"created_with_source": True}
            ),
        )
    return None
