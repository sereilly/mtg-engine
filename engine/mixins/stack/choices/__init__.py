"""Choices a player has to make part-way through casting or resolving.

Each is the same shape: something *arms* a choice on ``game.pending_choices``,
an interactive seat answers it through a ``confirm_*`` method the web layer
calls, and every other seat takes the kind's recorded default. Both paths
finish through the one registered resolver, so there is a single completion
path to keep correct rather than an inline branch and a ``confirm_`` method
that must agree forever.

``table.py`` is the index of every prompt in the engine: what answers it, what
a non-interactive seat does instead, and how the web layer renders, gates and
refuses around it. See ``engine/pending_choices.py`` for what each field means
and why the table exists. ``tests/engine/test_pending_choices.py`` fails if a
kind is armed with no spec, or registered with a part missing.

This package was one 13,312-line module, ``choices.py``. The queue the prompts
wait on is one mixin; every family of prompt is a mixin of its own, holding
its kinds' arm / ``confirm_*`` / resolver / default methods:

    queue          PendingChoicesMixin        arming, waiting, answering, defaults
    replacements   ReplacementChoicesMixin    CR 614 offers answered; CR 616.1e's order
    search         LibrarySearchChoicesMixin  searching a library (CR 701.23)
    library        LibraryChoicesMixin        looking at, ordering and drawing a library's top
    hand           HandChoicesMixin           cards picked out of a hand
    pile_picks     PileChoicesMixin           piles (CR 700.3), shared exile piles, graveyards
    values         ValueChoicesMixin          a type, a colour or a word; "as this enters, choose"
    card_names     CardNameChoicesMixin       "choose a card name", and what the name does
    numbers        NumberChoicesMixin         how many, how much, which number, whether again
    permanents     PermanentChoicesMixin      a permanent, several, or a player chosen on resolution
    payments       PaymentChoicesMixin        paying from the board; "unless its controller pays"
    optional_pay   OptionalPayChoicesMixin    "you may pay" offers, and what buying one runs
    triggers       TriggerChoicesMixin        a trigger's order, targets and mode (CR 603.3b-d)
    spells         SpellChoicesMixin          a spell cast, moded or aimed by a prompt
    sacrifice      SacrificeChoicesMixin      sacrifices, keeps, and Balance

``Game`` composes them in that order, immediately after ``PendingChoicesMixin``
where the one class they came out of sat. They are disjoint — no method is
defined twice and none calls ``super()`` — so their order among themselves
carries no meaning; methods of one family call another's through ``self``.

**The table is one table in one module, and that is behaviour rather than
tidiness.** ``iter_pending_prompts`` walks the registry in registration order,
so the order of the rows decides which owed prompt an AI seat answers first
(``web/prompts.auto_resolve_ai_prompts``), which one ``waiting_prompt`` says the
game is waiting on, and which one ``blocking_prompt`` refuses an action with.
Moving each family's rows into its module would make that order an accident of
which module imports first. A new prompt is a row appended to ``table.py`` plus
its methods in the family it belongs to.
"""

from .queue import PendingChoicesMixin
from .replacements import ReplacementChoicesMixin
from .search import LibrarySearchChoicesMixin
from .library import LibraryChoicesMixin
from .hand import HandChoicesMixin
from .pile_picks import PileChoicesMixin
from .values import ValueChoicesMixin
from .card_names import CardNameChoicesMixin
from .numbers import NumberChoicesMixin
from .permanents import PermanentChoicesMixin
from .payments import PaymentChoicesMixin
from .optional_pay import OptionalPayChoicesMixin
from .triggers import TriggerChoicesMixin
from .spells import SpellChoicesMixin
from .sacrifice import SacrificeChoicesMixin
# Imported last and for its side effect: every ``register_choice`` row, in
# the one order ``iter_pending_prompts`` reads them in.
from . import table  # noqa: F401

__all__ = [
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
]
