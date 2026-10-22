"""The stack (CR 405) — putting things on it, and taking them off.

One 2,277-line ``stack_casting`` module held four distinct jobs. They are now a
mixin each, composed onto :class:`~engine.game.Game` the same way
``engine.phases`` composes one mixin per turn phase:

    casting      SpellCastingMixin       CR 601 — cast a spell from hand
    activation   AbilityActivationMixin  CR 602 — activate a permanent's ability
    resolution   StackResolutionMixin    CR 603/608 — trigger, resolve, clean up
    choices      PendingChoicesMixin     the arm / confirm / auto-resolve queue
                 (+ one mixin per prompt family; a package, see its __init__)

The first three outgrew one module each at the 2,000-line cap, and each part
split out of one is a mixin ``Game`` composes immediately after it:

    casting      cast_announcement       CR 601.2a–c — where from, modes,
                                         each mode's targets
                 cast_additional_costs   CR 601.2b/f–h — additional costs
                 cast_alternative_costs  CR 118.9 — the alternative cost
                 cast_target_validation  CR 601.2c–d — the target gate
                 pool_payment            CR 601.2g–h — spending the pool, and X
    activation   activation_checks       CR 602.2a–b, 602.5 — before any cost
                 activation_payment      CR 602.2b — can the cost be paid, by what
                 activation_charges      CR 601.2h — the payers chosen, the payment
                 card_activation         an ability of a card in a hand or
                                         a graveyard (CR 113.6)

``_cast_onto_stack`` and ``_activate_onto_stack`` each call their steps in
CR order from those modules; the hinge between refusing and paying (the mana
payment) stays in the method itself.
    resolution   trigger_targets         CR 603.3c–d — a trigger's mode, targets
                 triggered_abilities     CR 603.3 — triggers onto the stack

The split is along "what stage of the object's life is this?", which is why
``choices`` exists as its own module rather than staying inside the two that arm
its prompts: a pending choice belongs to no single stage, and the arm/confirm/
auto-resolve triple is only recognisable as one pattern when its 33 members sit
together.

The four are disjoint — no method moved between them and none is overridden, so
composition order carries no meaning. ``choices`` outgrew one module at 13,312
lines and is a package now: ``PendingChoicesMixin`` is still the queue, and each
family of prompt beside it is a mixin ``Game`` composes immediately after it.
"""

from .activation import AbilityActivationMixin
from .activation_payment import ActivationPaymentMixin
from .card_activation import CardActivationMixin
from .activation_checks import ActivationChecksMixin
from .activation_charges import ActivationChargesMixin
from .casting import SpellCastingMixin
from .cast_additional_costs import AdditionalCastCostsMixin
from .cast_alternative_costs import AlternativeCastCostsMixin
from .cast_target_validation import (
    CastTargetValidationMixin,
    aura_enchant_noun,
    enchant_noun_seat,
    enchant_seat_satisfied,
    permanent_matches_enchant_noun,
)
from .pool_payment import PoolPaymentMixin
from .cast_announcement import CastAnnouncementMixin
from .choices import (
    PendingChoicesMixin,
    ReplacementChoicesMixin,
    LibrarySearchChoicesMixin,
    LibraryChoicesMixin,
    HandChoicesMixin,
    PileChoicesMixin,
    ValueChoicesMixin,
    CardNameChoicesMixin,
    NumberChoicesMixin,
    PermanentChoicesMixin,
    PaymentChoicesMixin,
    OptionalPayChoicesMixin,
    TriggerChoicesMixin,
    SpellChoicesMixin,
    SacrificeChoicesMixin,
)
from .resolution import StackResolutionMixin
from .trigger_targets import TriggerTargetsMixin
from .triggered_abilities import TriggeredAbilitiesMixin

__all__ = [
    "AbilityActivationMixin",
    "ActivationPaymentMixin",
    "CardActivationMixin",
    "ActivationChecksMixin",
    "ActivationChargesMixin",
    "PendingChoicesMixin",
    "ReplacementChoicesMixin",
    "LibrarySearchChoicesMixin",
    "LibraryChoicesMixin",
    "HandChoicesMixin",
    "PileChoicesMixin",
    "ValueChoicesMixin",
    "CardNameChoicesMixin",
    "NumberChoicesMixin",
    "PermanentChoicesMixin",
    "PaymentChoicesMixin",
    "OptionalPayChoicesMixin",
    "TriggerChoicesMixin",
    "SpellChoicesMixin",
    "SacrificeChoicesMixin",
    "SpellCastingMixin",
    "AdditionalCastCostsMixin",
    "AlternativeCastCostsMixin",
    "CastTargetValidationMixin",
    "PoolPaymentMixin",
    "CastAnnouncementMixin",
    "StackResolutionMixin",
    "TriggerTargetsMixin",
    "TriggeredAbilitiesMixin",
    "aura_enchant_noun",
    "enchant_noun_seat",
    "enchant_seat_satisfied",
    "permanent_matches_enchant_noun",
]
