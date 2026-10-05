"""CR 601.2c for a spell that targets a spell: the announcement gate and the
picker are one list.

Found on Invasion's Spite ("Counter target noncreature spell."), the pool's
first *spell* to print that phrase — every earlier printing is an activated
ability, whose gate already asked. A spell's named stack target was checked by
the counter arm of ``_validate_cast_targets`` and that arm asks one question,
the colour. Every other narrowing a counterspell prints was enforced by the
picker (never offered) and by the handler (declined at resolution) and by
nothing in between, so the engine accepted the announcement:

    Remove Soul ("Counter target creature spell.") at a Lightning Bolt
      -> cast accepted, {1}{U} spent, Remove Soul in the graveyard,
         the Bolt resolves for 3.

Not wrong in the caster's favour — nothing illegal is ever countered — but
CR 601.2c makes that cast illegal, and an AI or a client that names the wrong
spell pays for a card that does nothing. ``legality.cast_stack_target_refusal``
is the gate; this sweep holds it to every stack-targeting spell in the pool.

**Validated backwards**, as a census has to be: with the gate switched off the
sweep must find the Remove Soul case above, and it carries a floor on how many
announcements it examined — a sweep that examined none passes on any tree.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_catalog
from engine.models import PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec

#: One spell of each kind a printed narrowing can tell apart: a creature, an
#: artifact, an enchantment, an instant and a sorcery, over three colours.
_VICTIMS = (
    "Grizzly Bears", "Sol Ring", "Crusade", "Lightning Bolt", "Mind Twist",
    "Ancestral Recall",
    # …and one spell with **two** card types (CR 205.2), added at the W1G5
    # integration. Every victim above has one, so a picker that read a spell's
    # type off ``primary_type`` agreed with the gate on all of them — and the
    # gate, which is that picker's list, refused Annul aimed at this.
    "Ornithopter",
)


def _stack_targeting_spells(catalog):
    """Every non-modal instant or sorcery whose cast spec points at the stack."""
    for card in catalog:
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        spec = derive_cast_spec(card, program)
        if spec is not None and spec.get("kind") == "stack":
            yield card, spec


def _announce(card, spec, victim, by_name):
    """Seat 1 answers seat 0's *victim* with *card*. Returns ``(offered,
    accepted)``: whether the picker lists the victim, and whether the engine
    took the announcement."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.players[0].hand.append(by_name[victim])
    game.players[1].hand.append(card)
    queued = game.queue_from_hand(0, victim, target_player_index=1)
    if not queued.supported or len(game.stack) != 1:
        return None
    offered = any(
        entry.get("stack_index") == 0
        for entry in game._enumerate_stack_targets(1, card, spec)
    )
    try:
        result = game.queue_from_hand(1, card.name, target_stack_index=0)
    except Exception:  # noqa: BLE001 - a card needing more than a target is not this sweep's
        return None
    return offered, result.supported


def _sweep(catalog):
    by_name = {card.name: card for card in catalog}
    examined = 0
    accepted_unoffered: list[tuple[str, str]] = []
    for card, spec in _stack_targeting_spells(catalog):
        for victim in _VICTIMS:
            outcome = _announce(card, spec, victim, by_name)
            if outcome is None:
                continue
            examined += 1
            offered, accepted = outcome
            if accepted and not offered:
                accepted_unoffered.append((card.name, victim))
    return examined, accepted_unoffered


@pytest.fixture(scope="module")
def _catalog():
    return load_catalog()


def test_no_spell_can_be_announced_at_a_spell_its_picker_would_not_offer(_catalog):
    examined, accepted_unoffered = _sweep(_catalog)

    assert examined >= 200, f"the sweep examined only {examined} announcements"
    assert accepted_unoffered == [], (
        "CR 601.2c: these spells were announced, and paid for, at a spell their "
        f"printed target phrase does not admit: {accepted_unoffered}"
    )


def test_the_sweep_finds_the_defect_on_a_tree_that_has_it(_catalog, monkeypatch):
    """The backwards half. Without the gate, Remove Soul at a Lightning Bolt is
    accepted — the known defect, by name — so the sweep above is not passing
    because it looks at nothing."""
    monkeypatch.setattr(
        Game, "cast_stack_target_refusal", lambda self, *args, **kwargs: None,
    )
    _examined, accepted_unoffered = _sweep(_catalog)

    assert ("Remove Soul", "Lightning Bolt") in accepted_unoffered
    assert len({name for name, _victim in accepted_unoffered}) >= 10


def test_remove_soul_aimed_at_an_instant_is_refused_with_nothing_spent(_catalog):
    by_name = {card.name: card for card in _catalog}
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = True
    p0, p1 = game.players
    p0.hand.append(by_name["Lightning Bolt"])
    p1.hand.append(by_name["Remove Soul"])
    p0.mana_pool["R"] = 1
    p1.mana_pool["U"] = 2
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported

    refused = game.queue_from_hand(1, "Remove Soul", target_stack_index=0)

    assert not refused.supported
    assert refused.details == "no valid target for Remove Soul"
    assert [card.name for card in p1.hand] == ["Remove Soul"]
    assert p1.mana_pool["U"] == 2 and len(game.stack) == 1


def _handler_acts_where_the_picker_does_not_offer(catalog):
    """``(examined, findings)``: with the announcement gate off, every stack
    spell is cast at every victim and resolved, and a victim that **left the
    stack** although the picker did not offer it is a finding.

    The other half of the sweep above. That one holds the gate to the picker;
    this holds the picker to the handler, which is the reading CR 601.2c is
    actually about — and the half the gate cannot check, because it *is* the
    picker's list. A spell that does not remove its target (Fork, Deflection)
    never produces a finding here and is not a claim either way.
    """
    by_name = {card.name: card for card in catalog}
    examined = 0
    findings: list[tuple[str, str]] = []
    for card, spec in _stack_targeting_spells(catalog):
        for victim in _VICTIMS:
            game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
            game.enforce_mana_costs = False
            game.players[0].hand.append(by_name[victim])
            game.players[1].hand.append(card)
            queued = game.queue_from_hand(0, victim, target_player_index=1)
            if not queued.supported or len(game.stack) != 1:
                continue
            victim_item = game.stack[0]
            offered = any(
                entry.get("stack_index") == 0
                for entry in game._enumerate_stack_targets(1, card, spec)
            )
            try:
                result = game.queue_from_hand(1, card.name, target_stack_index=0)
                if not result.supported:
                    continue
                game.resolve_top_of_stack()
            except Exception:  # noqa: BLE001 - needs more than a target; not this sweep's
                continue
            examined += 1
            removed = not any(item is victim_item for item in game.stack)
            if removed and not offered:
                findings.append((card.name, victim))
    return examined, findings


def test_the_picker_offers_every_spell_the_handler_would_act_on(_catalog, monkeypatch):
    monkeypatch.setattr(
        Game, "cast_stack_target_refusal", lambda self, *args, **kwargs: None,
    )
    examined, findings = _handler_acts_where_the_picker_does_not_offer(_catalog)

    assert examined >= 200, f"the sweep examined only {examined} resolutions"
    assert findings == [], (
        "CR 601.2c / CR 205.2: the handler acts on these spells and the picker "
        f"- which is the announcement gate - does not offer them: {findings}"
    )


def test_annul_counters_an_artifact_creature_spell(_catalog):
    """The case by name: an artifact creature spell is an artifact spell."""
    by_name = {card.name: card for card in _catalog}
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    p0, p1 = game.players
    p0.hand.append(by_name["Ornithopter"])
    p1.hand.append(by_name["Annul"])
    assert game.queue_from_hand(0, "Ornithopter").supported

    cast = game.queue_from_hand(1, "Annul", target_stack_index=0)
    assert cast.supported, cast.details
    game.resolve_top_of_stack()

    assert game.stack == []
    assert [card.name for card in p0.graveyard] == ["Ornithopter"]
    assert not any(perm.card.name == "Ornithopter" for perm in game.all_permanents())
