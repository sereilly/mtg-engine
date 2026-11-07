"""Which printed lines this package implements, for the two readers that ask.

``prevention_claims_line`` is how the grammar's parse claim
(``engine/grammar/registries.py``) and the support gate
(``engine/derived_static_claims.py``) learn that a line is a CR 615 static
prevention the engine carries out in full: an interceptor produces no
instruction, so a permanent whose only ability is one would otherwise claim
nothing and report unsupported however well the interceptor works.

Every matcher below is imported from the module whose interceptor reads it, so
what is claimed and what is prevented cannot drift. Its own module for
``replacements/lines.py``'s reason: it imports from every interceptor module
and none of them may import it back. Split out of ``static.py`` at kg4.
"""

from __future__ import annotations

from .blankets import (prevent_all_from_spell_class, prevent_all_to_controller,
                       prevent_all_to_matching, prevent_and_count_kind,
                       prevent_between_shared_colors, prevent_n_of_damage)
from .shields import attached_damage_shield, self_damage_shield
from .static import (attached_prevent_all_from_source_type,
                     per_damage_counter_kind, prevent_all_from_source_type,
                     prevent_small_event_threshold,
                     prevent_then_remove_counter_kind)


def prevention_claims_line(line: str, card_name: str | None = None) -> bool:
    """Whether one printed line is, in full, a static prevention effect
    implemented in this package.

    The twin of ``replacements.lines.replacement_claims_line`` and read by the same
    two callers — the grammar's parse claim (engine/grammar/registries.py) and
    the support gate (engine/oracle.py) — because a permanent whose ability is a
    prevention produces no instruction either. Nine Lives happened to print
    three other lines, so it reported supported with this one silently doing
    nothing; a card printing only this one would have reported unsupported while
    working perfectly, which is the other half of the same hole.

    *card_name* is optional for the reason ``counter_cap_line``'s is, one gate
    over: the self-referencing form only exists on a card, so a reader asking
    about a bare line still gets the answer it always got, and the two callers
    that hold a card pass it. The runtime read is
    ``_attached_damage_shields``'s, which takes the name off the permanent it is
    already looking at.
    """
    return (
        prevent_and_count_kind(line) is not None
        or prevent_then_remove_counter_kind(line, card_name) is not None
        or prevent_n_of_damage(line) is not None
        or per_damage_counter_kind(line) is not None
        or prevent_all_from_source_type(line) is not None
        or attached_prevent_all_from_source_type(line) is not None
        or attached_damage_shield(line, card_name) is not None
        or self_damage_shield(line, card_name) is not None
        or prevent_all_to_controller(line) is not None
        or prevent_all_to_matching(line) is not None
        or prevent_all_from_spell_class(line) is not None
        or prevent_small_event_threshold(line, card_name) is not None
        or prevent_between_shared_colors(line) is not None
    )
