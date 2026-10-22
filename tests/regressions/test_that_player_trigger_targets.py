"""A "…target <permanent> **that player** controls" trigger, fired for real.

``tests/engine/test_stack_targets.py`` pins the triggered abilities that print
a target and reach the stack without one, and says of fourteen of them that
"a real fire site supplies" the seat its context-free drive cannot. That
sentence had never been run. This runs it for the family a damage event
fires: the source deals damage to a player through the engine's own damage
path, and the trigger that answers is

1. **stamped** with a target as it is put on the stack (CR 603.3d), from its
   own list, with the damaged player's seat frozen;
2. **not aimed at a shrouded permanent** that stands *first* on that player's
   battlefield — which is where a handler's scan would have looked; and
3. **carried out on the permanent it chose**.

Three of the four did all three. Sigil of Sleep did the first two and then
returned nothing: its handler re-checked "that player controls" without the
seat the matcher needs, which fails closed, so the card refused the target it
had just chosen. (``scripts/unasked_narrowings.py`` carried the entry; this is
what showed it was a mis-play and not one of the entries a handler answers
some other way — Chandra's Incinerator is on that list too and is right.)

Not driven here: the three that say "**combat** damage" (Caustic Wasps,
Latulla's Orders, Feline Sovereign), which need a combat damage step.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.models import CardDefinition, Permanent
from engine.stack_targets import chosen_targets
from tests.helpers import _nosick, resolve_stack


def _fixture(name: str, type_line: str, *, shroud: bool) -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power="3", toughness="3")
    return CardDefinition(
        name=name, mana_cost="{3}", cmc=3.0, type_line=type_line,
        oracle_text="Shroud" if shroud else "", colors=(), color_identity=(),
        # ``keywords`` is what layer 6 reads a printed keyword off.
        keywords=("Shroud",) if shroud else (), produced_mana=(), raw=raw,
    )


#: ``(the card, what it enchants or None, the victims' type line, what
#: happened to the chosen one)``.
_CASES = (
    ("Soltari Visionary", None, "Enchantment", "left"),
    ("Somnophore", None, "Creature — Golem", "tapped"),
    ("Sigil of Sleep", "Grizzly Bears", "Creature — Golem", "returned"),
    ("Chandra's Incinerator", None, "Creature — Golem", "damaged"),
)


@pytest.mark.parametrize("name, host, victim_type, outcome", _CASES, ids=[c[0] for c in _CASES])
def test_the_trigger_chooses_that_players_permanent_and_acts_on_it(
    catalog_by_name, name, host, victim_type, outcome,
):
    game = Game(players=[
        PlayerState("A", library=[catalog_by_name["Forest"]] * 12),
        PlayerState("B", library=[catalog_by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    walled = _nosick(Permanent(card=_fixture("Walled", victim_type, shroud=True)))
    plain = _nosick(Permanent(card=_fixture("Open", victim_type, shroud=False)))
    game._put_permanent_onto_battlefield(1, walled, None)
    game._put_permanent_onto_battlefield(1, plain, None)
    # The fixture, asked: the bait is bait.
    assert game._has_keyword(walled, "shroud") and not game._has_keyword(plain, "shroud")
    assert game.battlefield_index_of(walled) < game.battlefield_index_of(plain)

    if host is None:
        dealer = _nosick(Permanent(card=catalog_by_name[name]))
        game._put_permanent_onto_battlefield(0, dealer, None)
    else:
        dealer = _nosick(Permanent(card=catalog_by_name[host]))
        game._put_permanent_onto_battlefield(0, dealer, None)
        aura = Permanent(card=catalog_by_name[name])
        game._put_permanent_onto_battlefield(0, aura, None)
        attach_aura(aura, dealer)
    resolve_stack(game)
    game.stack.clear()
    game.pending_choices.clear()

    game._deal_damage_to_player(game.players[1], 2, source=dealer)
    game.check_state_based_actions()

    triggers = [item for item in game.stack if item.is_ability and item.card.name == name]
    assert len(triggers) == 1
    assert game._that_player_seat(triggers[0]) == 1
    chosen = chosen_targets(game, triggers[0])
    assert [target.permanent_id for target in chosen] == [plain.permanent_id]

    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    # The shrouded one, standing first, is exactly as it was.
    assert game.is_on_battlefield(walled)
    assert not walled.tapped and walled.damage_marked == 0
    if outcome == "left":
        assert not game.is_on_battlefield(plain)
    elif outcome == "tapped":
        assert game.is_on_battlefield(plain) and plain.tapped
    elif outcome == "returned":
        assert not game.is_on_battlefield(plain)
        assert [card.name for card in game.players[1].hand] == ["Open"]
    else:
        assert game.is_on_battlefield(plain) and plain.damage_marked == 2
