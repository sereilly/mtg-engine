"""Every ability a **board-wide** static grants in quotes has to be one the
compiler reads — ``test_aura_quoted_grants.py``'s question one reader over.

"All creatures have "…"" / "Each creature has "…"" (Energy Flux, Torrent of
Lava, Breath of Dreams, Aura Flux) is ``global_statics``'
``granted_board_wide_ability``: the quoted sentence lands on each permanent it
reaches through ``effective_card``, and that permanent's compile is what turns
it into an ability — or does not. ``derived_static_claims`` claimed the
granting card on the template match alone, so Fifth Dawn's Endless Whispers
("Each creature has "When this creature dies, choose target opponent. That
player puts this card from its owner's graveyard onto the battlefield under
their control at the beginning of the next end step."") reported supported
and granted a sentence that compiles to nothing. Every instrument passed it:
the card's own program is one ``derived_static_rule``, ``--hollow-lines``
reads parts and it has none, and ``parse_coverage`` takes the claim's word.

Validated backwards: on the tree before the claim asked
``granted_ability_supported`` this named Endless Whispers, and nothing else
(nine board-wide grants in the pool over both manifest roles, the other eight
compile).
"""

from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.global_statics import global_static_for
from engine.granted_abilities import granted_ability_supported
from engine.oracle import compile_card_oracle

#: How many board-wide grants the pool held when this was written. A floor,
#: because a census that examined nothing passes for the same reason as one
#: that found nothing.
EXAMINED_FLOOR = 8


def _census() -> tuple[int, list[str]]:
    """``(grants examined, supported cards granting a sentence that does not
    compile)``, over both manifest roles."""
    examined = 0
    unread: list[str] = []
    seen: set[str] = set()
    for path in manifest_set_paths(include_measured=True):
        for unit in compilation_units(load_cards(path)):
            if unit.name in seen:
                continue
            seen.add(unit.name)
            for line in (unit.oracle_text or "").splitlines():
                static = global_static_for(line)
                if static is None or not static.grants_ability:
                    continue
                examined += 1
                if granted_ability_supported(static.grants_ability):
                    continue
                if compile_card_oracle(unit).supported:
                    unread.append(f"{unit.name}: {static.grants_ability}")
    return examined, unread


def test_every_supported_board_wide_grant_compiles():
    examined, unread = _census()
    assert examined >= EXAMINED_FLOOR, examined
    assert unread == []
