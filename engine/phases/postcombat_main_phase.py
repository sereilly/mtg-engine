from __future__ import annotations

"""Postcombat main phase (CR 505).

The second main phase, entered after the combat phase ends. It is mechanically
identical to the precombat main phase — the active player may still play their
land for the turn (if they haven't) and cast sorcery-speed spells. It is entered
via the shared ``_enter_main_phase(precombat=False)`` (see
``precombat_main_phase``); this engine has no postcombat-specific turn-based
action, so this mixin carries no additional behavior.
"""


class PostcombatMainPhaseMixin:
    pass
