"""Ground Seal, asked of the whole pool (ODY W1G5).

"Cards in graveyards can't be the targets of spells or abilities." One printed
sentence and three ways of choosing a graveyard card, so the question is asked
of every card in both manifest roles that chooses one:

* a **spell** and an **activated ability** name their target through
  ``legality._enumerate_graveyard_creatures`` — the one enumeration of
  graveyard targets, where the Seal is asked — so the picker offers nothing,
  and CR 601.2c / 602.2b refuse the announcement with nothing paid;
* a **triggered ability** has no picker for a card in a graveyard: its handler
  scans the pile as it resolves. ``legality.sealed_graveyard_target_refusal``
  removes it from the stack instead (CR 603.3d), on the evidence of its own
  printed line saying "target" once.

The card's ruling draws the other edge: "Abilities that don't target cards in
graveyards (like the one Tormod's Crypt has) can still affect those cards." A
cost paid out of a graveyard, a mass exile and an untargeted return are tested
by name below.

**What this does not hold, and why.** Two shipped cards make an *untargeted*
graveyard choice through the graveyard target kind — Experimental Overload (a
spell) and Harvest Wurm (an entry trigger) — because the lowering of a
graveyard return keeps no record of whether the sentence said "target". Under
the Seal their effect still happens (the handler's own pick), but the picker
that would let a person choose *which* card is the enumeration, and it offers
nothing. Both are left out of the sweeps rather than asserted either way; the
fix is a record in ``lowering/returns.py``, in the graveyard-target group's
lane.

**Validated backwards.** ``test_the_census_names_every_case_without_the_seal``
switches the Seal's one reader off — the tree as it stood before the card was
implemented — and requires every examined case to be reported. A census that
passed there would be a census of nothing.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import _target_instances
from engine.targeting import (GRAVEYARD_TARGET_KIND, spec_is_a_cost,
                              usable_activated_abilities)
from tests.helpers import _nosick, resolve_stack

#: One card of each printed type in each graveyard, so most graveyard noun
#: phrases find a card: creatures of three colours, an artifact, an instant, a
#: sorcery, an enchantment, an Aura, a basic and a non-basic land.
_YARD = (
    "Grizzly Bears", "Hill Giant", "Phantom Monster", "Scathe Zombies",
    "Savannah Lions", "Sol Ring", "Lightning Bolt", "Earthquake", "Crusade",
    "Holy Strength", "Forest", "Mishra's Factory",
)

#: Floors, set well inside what the pool measures today (44 targeting spells,
#: 36 activations, 14 entry triggers at Odyssey's ingest) for the reason every
#: floor in this repo is: an ordinary ingest must not move them, and a census
#: that stopped examining anything must not pass.
_CAST_FLOOR = 35
_ACTIVATION_FLOOR = 28
_TRIGGER_FLOOR = 10


def _pool() -> list:
    seen: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            seen.setdefault(card.oracle_id or card.name, card)
    return list(seen.values())


@pytest.fixture(scope="module")
def pool():
    return _pool()


@pytest.fixture(scope="module")
def by_name(pool):
    names: dict = {}
    for card in pool:
        names.setdefault(card.name, card)
    return names


def _board(by_name, *, sealed: bool, source_card=None, hand=(), interactive=()):
    """Two seats with stocked graveyards; seat 1 holds the Seal when *sealed*."""
    yard = [by_name[name] for name in _YARD]
    game = Game(players=[
        PlayerState(name="P1", hand=list(hand), graveyard=list(yard),
                    library=[by_name["Forest"]] * 12),
        PlayerState(name="P2", graveyard=list(yard),
                    library=[by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    source = None
    if source_card is not None:
        source = Permanent(card=source_card)
        game._put_permanent_onto_battlefield(0, source, None)
    # A creature to pay a sacrifice or a tap cost with.
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Scathe Zombies"]), None
    )
    resolve_stack(game)
    for permanent in game.controlled_by(0):
        _nosick(permanent)
    if sealed:
        game._put_permanent_onto_battlefield(
            1, Permanent(card=by_name["Ground Seal"]), None
        )
        resolve_stack(game)
    game.start_turn(0)
    game._settle()
    return game, source


def _graveyard_offers(spec: dict) -> list:
    return [
        target for target in (spec or {}).get("valid_targets", ())
        if target.get("kind") == "graveyard"
    ]


def _units(pool):
    # ``faces.compilation_units`` is the one iterator for a census about text
    # that compiles; ``whole_card`` hands back the card a face is cast from,
    # which is what goes into the hand.
    for face in faces.compilation_units(pool):
        program = compile_card_oracle(face)
        if program.supported and not program.modes:
            yield faces.whole_card(face), face, program


def _sweep_casts(pool, by_name) -> tuple[int, list]:
    examined, failures = 0, []
    for face in faces.compilation_units(pool):
        card = faces.whole_card(face)
        program = compile_card_oracle(face)
        if not program.supported or program.modes:
            continue
        # A spell that itself targets: an instant, a sorcery, or an Aura
        # (CR 303.4a). A creature or enchantment spell targets nothing — this
        # engine names its *entry trigger's* target as it is cast, and that
        # trigger is the third sweep's.
        if face.primary_type not in ("instant", "sorcery") and "Aura" not in face.type_line:
            continue
        # A graveyard choice the card never calls a target is not one, and the
        # Seal does not reach it — the ruling's own edge. One shipped spell
        # derives the graveyard *target* kind for such a choice (Experimental
        # Overload: "you may return an instant or sorcery card from your
        # graveyard to your hand"), because the lowering drops the word: a
        # targeted and an untargeted return compile to one payload. This sweep
        # must not bless that card's picker going empty under the Seal, so it
        # asks the printed line, as ``sealed_graveyard_target_refusal`` does.
        if "Aura" not in face.type_line and not _target_instances(face.oracle_text or ""):
            continue
        game, _ = _board(by_name, sealed=False, hand=[card])
        spec = game.cast_target_spec(0, face)
        if spec.get("kind") != GRAVEYARD_TARGET_KIND or spec_is_a_cost(spec):
            continue
        open_offers = _graveyard_offers(spec)
        if not open_offers:
            continue
        examined += 1
        game, _ = _board(by_name, sealed=True, hand=[card])
        offered = _graveyard_offers(game.cast_target_spec(0, face))
        if offered:
            failures.append(f"cast:{face.name}: offered {len(offered)} graveyard card(s)")
            continue
        named = open_offers[0]
        before = len(game.stack)
        result = game.queue_from_hand(
            0, face.name, target_player_index=named["seat"],
            target_permanent_index=named["index"],
        )
        if result.supported or len(game.stack) != before or card not in game.players[0].hand:
            failures.append(f"cast:{face.name}: accepted a graveyard target ({result.details})")
    return examined, failures


def _sweep_activations(pool, by_name) -> tuple[int, list]:
    examined, failures = 0, []
    for _card, face, program in _units(pool):
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None:
                continue
            game, source = _board(by_name, sealed=False, source_card=face)
            if source is None or game.controller_index_of(source) != 0:
                continue
            slot = game.battlefield_index_of(source)
            spec = game.activation_target_spec(0, slot, ability_index=index)
            if spec.get("kind") != GRAVEYARD_TARGET_KIND or spec_is_a_cost(spec):
                continue
            open_offers = _graveyard_offers(spec)
            if not open_offers:
                continue
            examined += 1
            game, source = _board(by_name, sealed=True, source_card=face)
            slot = game.battlefield_index_of(source)
            offered = _graveyard_offers(
                game.activation_target_spec(0, slot, ability_index=index)
            )
            label = f"act:{face.name}#{index}"
            if offered:
                failures.append(f"{label}: offered {len(offered)} graveyard card(s)")
                continue
            named = open_offers[0]
            before = len(game.stack)
            result = game.queue_permanent_ability(
                0, face.name, ability_index=index,
                target_player_index=named["seat"],
                target_permanent_index=named["index"],
            )
            if result.supported or len(game.stack) != before or source.tapped:
                failures.append(f"{label}: accepted a graveyard target ({result.details})")
    return examined, failures


def _yards(game) -> list:
    return [[card.name for card in player.graveyard] for player in game.players]


def _sweep_entry_triggers(pool, by_name) -> tuple[int, list]:
    """Every permanent whose **entry** trigger targets a card in a graveyard.

    Entry triggers only, because they are the ones a board can fire without
    knowing the card: the permanent is cast and the stack drained. Open, a
    card leaves a graveyard (that is what makes the case one this examined);
    sealed, none does — and the cast itself was accepted both times, because
    a permanent spell targets nothing.
    """
    from engine.targeting import derive_instruction_spec

    examined, failures = 0, []
    for card, face, program in _units(pool):
        if face.primary_type in ("instant", "sorcery") or "Aura" in face.type_line:
            continue
        wanted = False
        for trigger in program.triggered_abilities:
            if trigger.instruction is None or " enters" not in (trigger.source_line or ""):
                continue
            spec = derive_instruction_spec([trigger.instruction]) or {}
            if (
                spec.get("kind") == GRAVEYARD_TARGET_KIND
                and _target_instances(trigger.source_line) == 1
                and "up to" not in trigger.source_line.lower()
            ):
                wanted = True
        if not wanted:
            continue
        results = {}
        for sealed in (False, True):
            game, _ = _board(by_name, sealed=sealed, hand=[card], interactive={0})
            before = _yards(game)
            cast = game.cast_from_hand(0, face.name)
            resolve_stack(game)
            # A headless resolution pops its object and leaves what it asked
            # for the caller to drain ("you may return …"): the trigger's own
            # target is asked of the seat as it goes on the stack (CR 603.3d),
            # so the "may" is answered here rather than inside the cast.
            game.auto_resolve_pending_choices()
            results[sealed] = (before != _yards(game), cast.supported)
        if not results[False][0]:
            # Nothing moved with the Seal away either (a narrowing the stocked
            # pile does not answer): not a case this can judge.
            continue
        examined += 1
        if results[True][0]:
            failures.append(f"trigger:{face.name}: took a card out of a sealed graveyard")
        elif not results[True][1]:
            failures.append(f"trigger:{face.name}: its permanent spell was refused")
    return examined, failures


def test_no_cast_may_name_a_card_in_a_graveyard_under_the_seal(pool, by_name):
    examined, failures = _sweep_casts(pool, by_name)
    assert not failures, failures
    assert examined >= _CAST_FLOOR, examined


def test_no_activation_may_name_a_card_in_a_graveyard_under_the_seal(pool, by_name):
    examined, failures = _sweep_activations(pool, by_name)
    assert not failures, failures
    assert examined >= _ACTIVATION_FLOOR, examined


def test_no_entry_trigger_targets_a_card_in_a_graveyard_under_the_seal(pool, by_name):
    examined, failures = _sweep_entry_triggers(pool, by_name)
    assert not failures, failures
    assert examined >= _TRIGGER_FLOOR, examined


def test_the_census_names_every_case_without_the_seal(pool, by_name, monkeypatch):
    """The backwards validation. With the Seal's one reader answering "no
    such permanent" — the engine as it was before the sentence was implemented
    — all three sweeps must report every case they examine."""
    import engine.target_immunity as target_immunity

    monkeypatch.setattr(
        target_immunity, "graveyard_cards_untargetable", lambda game: None
    )
    for sweep, floor in (
        (_sweep_casts, _CAST_FLOOR),
        (_sweep_activations, _ACTIVATION_FLOOR),
        (_sweep_entry_triggers, _TRIGGER_FLOOR),
    ):
        examined, failures = sweep(pool, by_name)
        assert examined >= floor, (sweep.__name__, examined)
        assert len(failures) == examined, (sweep.__name__, examined, failures[:5])


def test_the_seal_leaves_what_does_not_target_alone(by_name):
    """The ruling's other half: "Abilities that don't target cards in
    graveyards (like the one Tormod's Crypt has) can still affect those
    cards." A mass exile aimed at a *player*, a cost paid out of a graveyard
    (CR 601.2b — a cost is not a target) and an untargeted return all work
    with the Seal on the battlefield."""
    # Tormod's Crypt: "Exile all cards from target player's graveyard."
    game, crypt = _board(by_name, sealed=True, source_card=by_name["Tormod's Crypt"])
    fired = game.activate_permanent_ability(0, "Tormod's Crypt", target_player_index=1)
    resolve_stack(game)
    assert fired.supported, fired.details
    assert game.players[1].graveyard == []

    # Necropolis: "Exile a creature card from your graveyard: Put X counters…"
    game, necropolis = _board(by_name, sealed=True, source_card=by_name["Necropolis"])
    creatures = sum(1 for card in game.players[0].graveyard if "Creature" in card.type_line)
    paid = game.activate_permanent_ability(0, "Necropolis")
    resolve_stack(game)
    assert paid.supported, paid.details
    assert sum(
        1 for card in game.players[0].graveyard if "Creature" in card.type_line
    ) == creatures - 1

    # Harvest Wurm: "…sacrifice it unless you return a basic land card from
    # your graveyard to your hand." No "target": the Seal does not reach it.
    game, _ = _board(
        by_name, sealed=True, hand=[by_name["Harvest Wurm"]], interactive={0},
    )
    assert game.cast_from_hand(0, "Harvest Wurm").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert any(p.card.name == "Harvest Wurm" for p in game.controlled_by(0))
    assert "Forest" in [card.name for card in game.players[0].hand]


def test_the_seal_arriving_in_response_fizzles_what_was_already_aimed(by_name):
    """CR 608.2b: a target that is illegal as the object resolves is not
    affected, and an object whose every target is illegal is removed from the
    stack. A Raise Dead and an Adun Oakenshield activation are each aimed at a
    creature card; the Seal enters in response; the cards stay where they are."""
    yard = [by_name["Grizzly Bears"], by_name["Hill Giant"]]
    game = Game(players=[
        PlayerState(name="P1", hand=[by_name["Raise Dead"]], graveyard=list(yard),
                    library=[by_name["Forest"]] * 12),
        PlayerState(name="P2", library=[by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    adun = Permanent(card=by_name["Adun Oakenshield"])
    game._put_permanent_onto_battlefield(0, adun, None)
    _nosick(adun)

    assert game.queue_from_hand(
        0, "Raise Dead", target_player_index=0, target_permanent_index=1,
    ).supported
    assert game.queue_permanent_ability(
        0, "Adun Oakenshield", target_player_index=0, target_permanent_index=0,
    ).supported
    game._put_permanent_onto_battlefield(1, Permanent(card=by_name["Ground Seal"]), None)
    resolve_stack(game)

    assert [card.name for card in game.players[0].graveyard] == [
        "Grizzly Bears", "Hill Giant", "Raise Dead",
    ]
    assert game.players[0].hand == []
    assert any("can't be targeted (Ground Seal, 608.2b)" in line for line in game.log)
