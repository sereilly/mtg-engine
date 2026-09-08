"""A printed superlative as the step that picks one object out of a set.

"…deals 2 damage to **the creature with the least toughness**" (Purging Scythe)
and "destroy **the creature with the least power**" (Drop of Honey) are the same
noun phrase under two verbs, and the phrase is not a narrowing: no permanent can
be asked whether another one is smaller (``ast.Superlative`` says why). So the
selection is a *step* — one ``choose_permanent`` naming the extreme, which
records the answer under ``CHOSEN_PERMANENT``, and then whatever the verb does
reading it back through the ``permanents_from`` channel every other bound
permanent travels.

A **floor**, not a family: ``damage`` and ``destruction`` both read it, and
families do not import each other. It sits beside ``_common`` for the reason
``_amounts`` does one package over — a leaf several lowerings share is not one
lowering's property, however small it is.

**The prompt was already here**, which is the whole reason this module is
fourteen lines of payload rather than a new instruction kind, a new
``PendingChoice`` and a new renderer. ``choose_permanent`` has carried
``only_on_tie`` since Juxtapose, suspends its resolution so the steps behind it
read the answer, and takes its default at arm for a non-interactive seat. What
it did **not** have was a way to say which superlative: the key was
``greatest_mana_value: True``, one corner of the phrase spelled into a flag, and
Drop of Honey — printing the same sentence with power for mana value and destroy
for exchange — had a name-keyed hook instead, with a prompt kind
(``least_power_choice``) duplicating this one down to the web renderer.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import testable_filter_payload
from ._record_keys import CHOSEN_PERMANENT


def superlative_pick(
    spec: "ast.Recipient", *, node, verb: str
) -> tuple[OracleInstruction, str] | None:
    """The ``choose_permanent`` step *spec*'s superlative names, or None.

    None — with nothing raised — when the phrase carries no superlative, so a
    caller can probe with it before its ordinary branches and be untouched by
    every other noun phrase in the pool.

    *verb* goes in the prompt ("damage", "destroy"), which is the only part of
    the question that differs between the two callers: the seat asked, the
    candidate rule and the recorded answer are identical.
    """
    if not isinstance(spec, ast.TargetSpec) or spec.filter.superlative is None:
        return None
    superlative = spec.filter.superlative
    if spec.targeted or spec.quantifier != "all":
        # "all" is what the noun parser gives the definite article over a
        # description (``references.parse_recipient``'s identified-object
        # branch), and it is the only quantifier this phrase is printed with:
        # a superlative *is* the article's promise that one object answers.
        # A card printing "target creature with the least toughness" would be
        # choosing among a set the picker has to bound, which is a different
        # announcement (CR 601.2c) and refuses here rather than resolving into
        # a prompt nobody was offered.
        raise LoweringError(
            "a superlative names one object and this phrase quantifies it "
            "some other way",
            node=node,
        )
    # The rest of the phrase, without the word that is not a narrowing. Through
    # the ordinary gate, so a superlative over a set the matcher *cannot*
    # describe ("the creature blocking it with the least toughness" under a
    # trigger that froze nothing) refuses by name rather than offering a wider
    # pool than the card prints.
    described = testable_filter_payload(
        dataclasses.replace(spec.filter, superlative=None),
        refusal=f"the {verb} cannot narrow its superlative by",
        node=node,
        require_narrowing=False,
    )
    printed = superlative.characteristic.replace("_", " ")
    step = OracleInstruction(
        "choose_permanent", "",
        {
            "result_key": CHOSEN_PERMANENT,
            "filter": described,
            "superlative": {
                "extreme": superlative.extreme,
                "characteristic": superlative.characteristic,
            },
            # "**If two or more** creatures are tied for least toughness, you
            # choose one of them." CR 608.2d's choice — announced while the effect
            # is applied, because the card offers it there — and the reason the
            # prompt is conditional: with one candidate the card names it
            # outright, so asking would put a question with one answer to the
            # controller every upkeep.
            "only_on_tie": True,
            # No ``chooser`` key: "**you** choose one of them" is the ability's
            # own controller, which is what ``_chooser_seat`` answers with none.
            "prompt": (
                f"Choose which creature with the {superlative.extreme} "
                f"{printed} to {verb}."
            ),
        },
    )
    return step, CHOSEN_PERMANENT


__all__ = ["superlative_pick"]
