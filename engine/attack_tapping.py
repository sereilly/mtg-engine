"""Whether attacking causes a creature to tap — CR 508.1f.

Declaring a creature as an attacker taps it (CR 508.1f, "the active player taps
the chosen creatures"), and the rules print two different things that say
otherwise. One is the keyword vigilance, which CR 702.20b defines as exactly
this exemption. The other is an effect that spells the exemption out without
using the word:

    "If you do, attacking doesn't cause creatures you control to tap this
    combat if Johan is untapped." — Johan

That is deliberately *not* vigilance: nothing in it gives a creature the
keyword, so "creatures with vigilance" does not find them and a later "creatures
lose all abilities" does not take it away. It is a rule about the declaration
step, which is why it lives beside the step rather than in layer 6.

**Both answers go through one function.** The tapping half of declaring an
attacker used to ask ``_has_keyword(attacker, "vigilance")`` inline, so an
effect phrased the long way round had nowhere to be asked at all — and adding a
second `if` there is the shape this codebase keeps finding at the bottom of a
bug: one question with two owners that eventually disagree.

**What the effect narrows is payload.** Which creatures it reaches is a printed
noun phrase (``subject_filter``), tested through ``subject_matches`` like every
other one; what has to stay true for it to apply is a second noun phrase about
the effect's own source (``gate_filter`` over ``gate_permanent_id``), because
Johan's exemption stops the moment Johan taps. Neither is part of the
instruction kind's name: a card printing the same sentence about artifact
creatures, or with no gate at all, needs no new code here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .models import Permanent


# ``eq=False`` so two entries compare by identity, for the reason
# `delayed_triggers.DelayedTrigger` records: two resolutions of the same trigger
# arm two entries with every field equal, and a value comparison would let a
# sweep that removed one remove both.
@dataclass(eq=False)
class AttackTapExemption:
    """One standing "attacking doesn't cause … to tap" effect.

    ``controller_index`` is the seat whose ability created it — the observer
    ``subject_matches`` needs to read "you control", and never re-derived from
    the board, because the effect outlives the resolution that made it.

    ``gate_permanent_id`` addresses the gating permanent by id rather than by
    index or by value (CR 400.7): a Johan that leaves and returns is a new
    object, and the exemption its earlier self armed must not follow it.
    """

    controller_index: int
    subject_filter: dict = field(default_factory=dict)
    gate_permanent_id: int | None = None
    gate_filter: dict = field(default_factory=dict)
    #: For the log. The card that created the effect.
    source_name: str = "attack-tap exemption"

    def applies_to(self, game: "Game", attacker: "Permanent") -> bool:
        """Whether *attacker* is one of the creatures this effect exempts."""
        from .subject_filters import subject_matches

        if self.gate_permanent_id is not None:
            gate = game.permanent_by_id(self.gate_permanent_id)
            if gate is None:
                return False
            if self.gate_filter and not subject_matches(
                game, gate, self.gate_filter, observer=self.controller_index
            ):
                return False
        if not self.subject_filter:
            return True
        return subject_matches(
            game, attacker, self.subject_filter, observer=self.controller_index
        )


def arm_attack_tap_exemption(
    game: "Game", exemption: AttackTapExemption
) -> AttackTapExemption:
    """Put *exemption* on the game's list of standing exemptions."""
    game.attack_tap_exemptions.append(exemption)
    return exemption


def clear_attack_tap_exemptions(game: "Game") -> None:
    """CR 511: every exemption the engine can arm is scoped to "this combat",
    so the end of combat step drops them all. A duration that outlived its
    combat would be a creature that never taps to attack again."""
    game.attack_tap_exemptions.clear()


def attacking_causes_tap(game: "Game", attacker: "Permanent") -> bool:
    """CR 508.1f: does declaring *attacker* as an attacker tap it?

    The one place both answers are given. Vigilance is read through the layer
    accessor (CR 613.1f — a *granted* vigilance exempts exactly as a printed one
    does), and the standing exemptions are read after it.
    """
    if game._has_keyword(attacker, "vigilance"):
        return False
    for exemption in game.attack_tap_exemptions:
        if exemption.applies_to(game, attacker):
            return False
    return True


__all__ = [
    "AttackTapExemption",
    "arm_attack_tap_exemption",
    "attacking_causes_tap",
    "clear_attack_tap_exemptions",
]
