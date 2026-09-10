"""Regressions: the printed "another" was swallowed on the graveyard route.

Found at Urza's Destiny's promotion gate and confirmed by driving the card:
**Junk Diver returned itself**. "When this creature dies, return another target
artifact card from your graveyard to your hand" -- with nothing else in the
pile, the ability had no legal choice at all and the handler's scan took the
first artifact card it found, which was the Diver that had just died.

The mechanism is worth keeping in view, because it is not the one the word's
name suggests. The parser reads "another" perfectly well: ``parse_target_spec``
records it as ``TargetSpec.distinct_from_prior``. What dropped it was the
*graveyard family's* gate for narrowings it cannot honour,
``_reads_no_return_restriction`` -- which does refuse ``other_than_source``, and
asks the **ObjectFilter**. The word was on the **TargetSpec**. A rider on the
neighbouring dataclass is invisible to a gate that reads only one of them, and
the card compiles supported the whole way through.

The fix is both ends: the lowering carries ``exclude_source_card``, and the
picker (``legality._enumerate_graveyard_creatures``) and the handler
(``handlers/zones.return_creature_from_graveyard_to_hand``) resolve it through
one reader, ``handlers/_common.excluded_graveyard_slot``. Every zone pair that
cannot read it refuses the line instead.
"""

from __future__ import annotations

from engine import Game
from engine.card_loader import load_catalog, load_cards, manifest_set_path
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec

_CATALOG = {card.name: card for card in load_catalog()}
_UDS = {
    card.name: card
    for card in load_cards(manifest_set_path("UDS", include_measured=True))
}


def _duel(**p1_kwargs) -> tuple[Game, PlayerState]:
    p1 = PlayerState(name="P1", **p1_kwargs)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, p1


def _kill(game: Game, permanent: Permanent) -> None:
    game._mark_damage_on_permanent(permanent, 99, source=None, combat=False)
    game.check_state_based_actions()
    game._settle()


def test_junk_diver_does_not_return_itself():
    """The driven report, as a test. Nothing else in the graveyard, so the
    printed sentence names nothing and nothing comes back."""
    game, p1 = _duel()
    diver = Permanent(card=_UDS["Junk Diver"])
    p1.battlefield.append(diver)
    game._sync_control()

    _kill(game, diver)

    assert [card.name for card in p1.hand] == []
    assert [card.name for card in p1.graveyard] == ["Junk Diver"]
    assert any(
        "No artifact card in graveyard to return" in line for line in game.log
    ), game.log[-6:]


def test_junk_diver_still_returns_the_artifact_it_may_name():
    """The other direction, which is the one an over-eager exclusion would
    break: the word takes one object out of the choice and leaves the rest."""
    game, p1 = _duel(graveyard=[_CATALOG["Ornithopter"], _CATALOG["Black Lotus"]])
    diver = Permanent(card=_UDS["Junk Diver"])
    p1.battlefield.append(diver)
    game._sync_control()

    _kill(game, diver)

    assert [card.name for card in p1.hand] == ["Ornithopter"]


def test_sylvan_hierophant_returns_the_creature_card_beside_it():
    """The shipped card of the same shape (Exodus). Its sentence exiles the
    source first, so the exclusion finds no slot and must not reach for
    anything else -- a self-exclusion that fell back to "the first matching
    card" would take the Grizzly Bears away."""
    game, p1 = _duel(graveyard=[_CATALOG["Grizzly Bears"]])
    hierophant = Permanent(card=_CATALOG["Sylvan Hierophant"])
    p1.battlefield.append(hierophant)
    game._sync_control()

    _kill(game, hierophant)

    assert [card.name for card in p1.exile] == ["Sylvan Hierophant"]
    assert [card.name for card in p1.hand] == ["Grizzly Bears"]


def _scrap_diver() -> CardDefinition:
    """Junk Diver's sentence on an *activated* ability.

    A dies-trigger with a graveyard target announces nothing -- graveyard kinds
    are deliberately outside ``_CHOOSABLE_TRIGGER_TARGET_KINDS`` -- so the two
    shipped cards of this shape never reach the picker at all, and the picker
    end of the fix would go untested if this test used one of them. An
    activated ability with the same printed line does reach it (Adun Oakenshield
    is the pool's example of that shape), which is what makes this the right
    witness rather than a convenience.
    """
    name, type_line = "Scrap Diver", "Artifact Creature - Construct"
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text=(
            "{T}: Return another target artifact card from your graveyard "
            "to your hand."
        ),
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def test_the_picker_never_offers_the_card_the_word_excludes():
    """Idiom #9's other half: the picker's enumeration and the handler's
    re-check are one predicate. An exclusion that landed only in the handler
    would leave the browser offering the source and the engine then declining
    what it had just offered."""
    card = _scrap_diver()
    program = compile_card_oracle(card)
    ability = program.activated_abilities[0]
    spec = derive_activation_spec(ability)

    game, p1 = _duel(graveyard=[card, _CATALOG["Ornithopter"]])
    source = Permanent(card=card)
    source.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(source)
    game._sync_control()

    offered = game._enumerate_targets(
        0, card, spec, for_cast=False,
        ability_instruction=ability.instruction,
        source_permanent=source, ability_source=source,
    )

    assert [entry["name"] for entry in offered] == ["Ornithopter"]
    assert all(entry["index"] != 0 for entry in offered), (
        "slot 0 holds the ability's own source"
    )


def test_the_activation_gate_refuses_an_activation_with_nothing_left_to_name():
    """CR 602.2b, through the same list: with the source the only artifact card
    in the pile the ability has no legal target, and the activation is declined
    with nothing paid rather than resolving onto the source."""
    card = _scrap_diver()
    game, p1 = _duel(graveyard=[card])
    source = Permanent(card=card)
    source.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(source)
    game._sync_control()

    program = compile_card_oracle(card)
    refusal = game.activation_target_refusal(
        0, source, program.activated_abilities[0], target_permanent_index=0,
    )

    assert refusal, "the source is the only candidate and the word excludes it"
