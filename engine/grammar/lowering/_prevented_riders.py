"""What a CR 615 shield does **after** it absorbs, and the second size it may
hold.

The lowering half of ``engine/grammar/prevented_riders.py``, and it takes that
module's name for ``_blankets``' reason exactly: the seam is one the parse side
had already found and named, so reusing it re-forms the mirror instead of
forking a second vocabulary for the same clause. CR 615.5 is the rule — "Some
prevention effects also include an additional effect, which may refer to the
amount of damage that was prevented" — and Elvish Healer's second size joins it
because it is the same shape from the other end: a printed clause beside a
shield that the shield itself has no field for, so a branch that read the shield
and not the clause would arm and report the card supported.

Split out of ``lowering/prevention.py`` at Mercadian Masques' first wave, when
Charm Peddler's chosen-source shield over an announced *creature* took that
module 22 lines past the thousand-line guard. What stayed there is the question
that module's docstring states — **which shield records what, and for how long**
— and what came here is the sentence printed next to it, which is neither a
shield nor a duration.

**A floor rather than a family**, for ``_blankets``' reason: ``prevention``
reads it — from three places in ``_lower_prevent_damage``, all of them in front
of the branch that owns the clause — and it reads nothing back.

The three readers are deliberately *in front of* the branches, and that is the
whole safety argument for the module. Every shield branch in ``prevention`` was
written before any rider existed and reads none of them, so a rider printed on a
Circle, a blanket or a halving shield would arm without it and the card would
report supported with a printed sentence doing nothing. Refusing centrally is
what makes "dropped rider" impossible rather than merely unlikely.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ..phrases import is_pt_counter
from ._common import _amount_payload, testable_filter_payload


def _alternate_amount(node: ast.PreventDamage) -> dict | None:
    """The second size Elvish Healer's rider gives its shield, or None.

    ``{"filter": …, "amount": N}`` — the printed noun phrase the recipient is
    tested against and how much the shield holds when it answers. Both halves
    or neither: a filter with no amount is a sentence that prevents nothing and
    an amount with no filter is one that always applies, and either alone would
    be a shield of the wrong size rather than a refusal.

    The filter is held to what ``subject_matches`` can test, like every other
    printed noun phrase that reaches a handler: a narrowing the matcher would
    drop is a shield that takes the *larger* size for every recipient.
    """
    if node.alternate_amount is None and node.alternate_subject is None:
        return None
    if node.alternate_amount is None or node.alternate_subject is None:
        raise LoweringError(
            "a second shield size needs both the condition and the amount",
            node=node,
        )
    larger = _amount_payload(node.alternate_amount)
    if not isinstance(larger, int) or larger <= 0:
        raise LoweringError("a second shield size is a printed number", node=node)
    described = testable_filter_payload(
        node.alternate_subject,
        refusal="the shield cannot test the noun phrase that sizes it",
        node=node,
    )
    return {"filter": described, "amount": larger}


def _counted_pool_counter_rider(node: ast.PreventDamage) -> str | None:
    """The counter Temper's CR 615.5 rider places, or None for every other card.

    "Prevent the next X damage that would be dealt to target creature this turn.
    **For each 1 damage prevented this way, put a +1/+1 counter on that
    creature.**"

    The pool's rider rather than the chosen-source shield's, which is the only
    other shape in this file that carries one — so it is read here, in front of
    the refusal every other branch shares, rather than inside the pool's own
    payload: those branches were written before any rider existed and read none
    of it, and one printed on a Circle or a blanket would arm without it and
    report the card supported.

    Every refusal is a way the sentence could otherwise mean more than it says:

    * the shield must be the plain counted pool. A half, a blanket, a
      colour-scoped Circle, a division and a second size all reach a different
      interceptor, and none of them places a counter — the rider would be
      dropped.
    * the counter must be a CR 122.1a power/toughness kind, because that is
      what the interceptor places (``Game.place_pt_counters``). An invented
      counter (CR 122.1's open half) has no reader behind this rider and would
      be a card reporting supported while placing nothing.
    * the rider carries no condition. "If damage from a black source is
      prevented this way" is a property of the source that the interceptor
      would ignore, which is a card paying for damage it never said it would.
    * the shield must go around a **chosen creature**. "That creature" is the
      one the sentence in front named, so a pool armed on a player, on the
      ability's own source or on the permanent it enchants leaves the pronoun
      pointing at nobody — and a counter placed on a player is not a counter
      this engine has.
    """
    rider = node.prevented_rider
    if rider is None or rider.effect != "put_counter":
        return None
    if (
        node.from_filter is not None
        or node.dealt_by is not None
        or node.dealt_by_others
        or node.combat_only
        or node.division is not None
        or node.to_others
        or node.alternate_amount is not None
        or node.alternate_subject is not None
        or rider.source_colors
        or isinstance(node.amount, (ast.AllOf, ast.Half))
    ):
        raise LoweringError(
            "only the plain counted pool places counters for what it prevented",
            node=node,
        )
    if not is_pt_counter(rider.counter):
        raise LoweringError(
            f"nothing places a {rider.counter} counter for damage prevented "
            "this way",
            node=node,
        )
    if (
        not isinstance(node.to, ast.TargetSpec)
        or node.to.quantifier not in ("target", "any_target")
        or "creature" not in node.to.filter.card_types
    ):
        raise LoweringError(
            "the counters go on the creature the shield was announced on",
            node=node,
        )
    return rider.counter


def _lower_team_shield(
    node: ast.PreventDamage,
) -> tuple[OracleInstruction, ...]:
    """Shadowbane: "The next time a source of your choice would deal damage to
    **you and/or creatures you control** this turn, prevent that damage. If
    damage from a black source is prevented this way, you gain that much life."

    CR 615.8's whole-instance shield over a player *and* a printed set of
    permanents. Its own instruction rather than a flag on the single-recipient
    one, because ``Shield.kind`` names the interceptor that consumes the shield
    and this one is found by a different route: a phrase has no object to hang a
    record on, so it lives on the seat and is matched against each damaged
    permanent (``prevention._class_shields``).

    Every part of the sentence is checked, because each is a way it could mean
    more:

    * exactly one further recipient, and it must be a described set rather than
      a chosen one — nothing enumerates a shield per member of a target list.
    * the phrase must be one ``subject_matches`` can test in full. A narrowing
      the matcher drops is a shield covering strictly more permanents than the
      card names.
    * the rider, if printed, must be one the interceptor performs. Its condition
      is a property of the *source*, so it rides beside the shield's own rather
      than inside it: this card prevents every colour's damage and pays for one.
    """
    if len(node.to_others) != 1:
        raise LoweringError(
            "no shield covers a player and more than one printed set", node=node
        )
    also = node.to_others[0]
    if (
        not isinstance(also, ast.TargetSpec)
        or also.quantifier not in ("all", "each")
        or also.targeted
    ):
        raise LoweringError(
            "the second recipient of a team shield is a described set, not a "
            "chosen one",
            node=node,
        )
    described = testable_filter_payload(
        also.filter,
        refusal="the team shield cannot test the noun phrase it also covers",
        node=node,
    )
    payload: dict[str, object] = {"recipients": described}
    rider = node.prevented_rider
    if rider is not None:
        if rider.effect != "gain_life":
            raise LoweringError(
                "the team shield's interceptor gains life and nothing else",
                node=node,
            )
        payload["rider_colors"] = list(rider.source_colors)
    return (OracleInstruction("grant_team_prevention_shield", "", payload),)
