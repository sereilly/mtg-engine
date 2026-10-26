"""ONS W1G10: "that player may <deed>" is performed by that player.

"Then that permanent's controller may **sacrifice a land of their choice**"
(Chain of Vapor, Chain of Silence) and "…that player or that permanent's
controller may **discard a card**" (Chain of Plasma) compiled with the deed's
elided subject left as "you": the offered player said yes and the *caster*
sacrificed their own land or discarded their own card. The parse now binds the
elided subject of a Draw, Sacrifice or Discard under "that player may" to that
player (``grammar/player_verbs``, the rebinding Soldevi Sentry's draw already
had).

The census is over both manifest roles: every compiled ``may`` whose actor is
``that_player`` and whose action is a sacrifice or a discard must name a
performer other than the caster. Validated backwards: on the round's base
(``ons/L6`` 29ed0249) it names Chain of Plasma, Chain of Silence and Chain of
Vapor.
"""
from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_paths
from engine.oracle import compiled_units

#: Deeds whose kind or payload says who performs them.
_CASTER_PERFORMS = {
    # The controller's own discard: by name, the caster's hand.
    "discard_controller_cards": lambda payload: True,
    # The targeted seat's discard, read off the offer's seat: never the
    # caster's (examined so the floor counts it).
    "discard_target_cards": lambda payload: False,
    # A sacrifice with no seat named is the caster's.
    "sacrifice_matching_permanent": lambda payload: payload.get("who") in (None, "you", "caster"),
}


def _offers(node, found):
    if hasattr(node, "kind") and hasattr(node, "payload"):
        if node.kind == "may" and node.payload.get("actor") == "that_player":
            found.append(node)
        _offers(node.payload, found)
    elif isinstance(node, dict):
        for value in node.values():
            _offers(value, found)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _offers(value, found)


def test_an_offered_deed_is_performed_by_the_offered_player():
    examined = 0
    caster_performs = set()
    for card, program in compiled_units(load_cards(manifest_set_paths(include_measured=True))):
        if not program.supported:
            continue
        roots = [*program.instructions]
        roots += [a.instruction for a in program.activated_abilities if a.instruction is not None]
        roots += [t.instruction for t in program.triggered_abilities if t.instruction is not None]
        found: list = []
        for root in roots:
            _offers(root, found)
        for offer in found:
            for action in offer.payload.get("action") or ():
                test = _CASTER_PERFORMS.get(getattr(action, "kind", None))
                if test is None:
                    continue
                examined += 1
                if test(action.payload or {}):
                    caster_performs.add(card.name)
    assert examined >= 3, f"examined {examined} offered deeds"
    assert caster_performs == set(), sorted(caster_performs)
