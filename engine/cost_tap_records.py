"""Which permanents were tapped this turn to pay for a permanent's abilities.

"When this creature dies, destroy all Merfolk **tapped this turn to pay for its
abilities**." (Vodalian War Machine.) The set is narrower than "tapped this
turn": a Merfolk tapped to attack, or by an opponent's Icy Manipulator, is not
in it. Nothing on the board can be asked which it was — a tapped permanent looks
the same however it got that way — so the answer has to be *recorded* when the
cost is paid, and this is the one place that writes it.

**One record, on the permanent that paid.** The alternative — a list on the
permanent whose abilities were paid for — loses the answer the moment that
permanent dies, which is the only moment this card asks the question. Keeping it
on the payer means the trigger reads a record that is still on the battlefield,
and the dead permanent contributes nothing but its id.

The id is CR 400.7's: a permanent that left and came back is a new object, and
its record does not follow it. The window is one turn, enforced by the cleanup
sweep (``engine/mixins/_constants._EOT_METADATA_KEYS``) rather than by a turn
number stored beside each id — a record with no sweep behind it would make
"this turn" mean "ever".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent

#: The metadata key the record lives under, on the permanent that was tapped.
#: Swept at cleanup, which is what makes the phrase's "this turn" true.
TAPPED_TO_PAY_FOR = "tapped_to_pay_for_ability_ids"


def record_tapped_to_pay(source: "Permanent", tapped: "Permanent") -> None:
    """Note that *tapped* was tapped to pay for an ability of *source*.

    Called from the one place an activation cost taps anything
    (``engine/mixins/stack/activation.py``), so a second tapping path cannot
    quietly fail to record — the same reason ``Game.become_tapped`` is the one
    untapped→tapped transition.
    """
    recorded = tapped.metadata.setdefault(TAPPED_TO_PAY_FOR, [])
    if source.permanent_id not in recorded:
        recorded.append(source.permanent_id)


def tapped_to_pay_for(permanent: "Permanent", source: "Permanent | None") -> bool:
    """Whether *permanent* was tapped this turn to pay for an ability of *source*.

    ``False`` with no source, which is the direction that cannot widen a sweep:
    a caller that cannot say whose abilities the phrase is about must not be
    handed every permanent tapped for anybody's.
    """
    if source is None:
        return False
    return source.permanent_id in (permanent.metadata.get(TAPPED_TO_PAY_FOR) or ())


__all__ = ["TAPPED_TO_PAY_FOR", "record_tapped_to_pay", "tapped_to_pay_for"]
