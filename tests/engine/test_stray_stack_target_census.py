"""Census: a stack object named for an announcement that has no target there.

CR 601.2c chooses "an appropriate object or player **for each target the spell
requires**". A ``target_stack_index`` on a Lightning Bolt, a Terror or a Wrath
of God names an object for a target the spell does not have, and the engine
accepted it — the stack gate (``legality_stack.cast_stack_target_refusal``) asks
whether the named spell is one the printed phrase admits and has nothing to ask
a spell with no stack target at all. Measured on the tree before the gate:

* **casts**: 888 of 888 examined announcements accepted, 853 distinct cards —
  every instant and sorcery in the pool whose spec does not name the stack;
* **activations**: 1,311 of 1,458 — 881 abilities that target nothing (the
  activation gate returned before it looked) and 429 naming a permanent
  beside the stack object (the ids were checked, the stack object recorded
  unread).

No client sends one and nothing was countered by it. The record was not inert,
though: CR 608.2b counts a recorded stack object among a spell's targets, so a
spell whose real target had left stayed "partly legal" while the stray one sat
on the stack.

``legality_stack.stray_stack_target_refusal`` and its activation twin are the gate.
**Validated backwards**, as a census has to be: with each gate switched off the
sweep must find the known cases by name, and it carries a floor on how many
announcements it examined — a sweep that examined none passes on any tree.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_catalog
from engine.faces import compilation_units, whole_card
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import (derive_activation_spec, derive_cast_spec,
                              spec_names_the_stack)

#: One permanent of each kind a printed target phrase can ask for, on both
#: battlefields, so a spell that needs a target has one to name.
_BOARD = ("Grizzly Bears", "Forest", "Sol Ring", "Crusade", "Wall of Wood")

#: Casts the census found accepting a stray stack object, by name — the ones
#: W1G5's hand probe reported, which is what makes the backwards half a check
#: of *this* defect rather than of some other acceptance.
_KNOWN_CASTS = ("Giant Growth", "Lightning Bolt", "Terror", "Wrath of God")
_KNOWN_ACTIVATIONS = ("Icy Manipulator", "Llanowar Elves")


@pytest.fixture(scope="module")
def _catalog():
    return load_catalog()


def _table(by_name, *, source=None):
    """A game with the board above on both sides and seat 1's Shock on the
    stack — the stray object every announcement below names."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    for seat in (0, 1):
        for name in _BOARD:
            permanent = Permanent(card=by_name[name])
            permanent.metadata["summoning_sickness_turn"] = -99
            game.players[seat].battlefield.append(permanent)
        game.players[seat].graveyard.extend([by_name["Grizzly Bears"], by_name["Sol Ring"]])
        game.players[seat].library.extend([by_name["Forest"]] * 10)
    placed = None
    if source is not None:
        placed = Permanent(card=source)
        placed.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield.append(placed)
        game.players[0].hand.extend([by_name["Forest"]] * 3)
    game._sync_control()
    game.players[1].hand.append(by_name["Shock"])
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    return game, placed


def _plain_announcements(game):
    """Announcements to try, in order, until the engine takes one: nothing, a
    seat, each permanent by id."""
    yield {}
    yield {"target_player_index": 1}
    yield {"target_player_index": 0}
    for seat in (1, 0):
        for permanent in game.players[seat].battlefield:
            yield {"target_permanent_ids": [permanent.permanent_id]}


def _cast_sweep(catalog, *, only=None):
    """``(examined, accepted)``: for every instant or sorcery whose spec does
    not name the stack, the first announcement the engine takes — asked first
    with the Shock named beside it.

    One table per spell. A refused cast spends nothing and moves nothing, so
    the candidates are tried in turn on the same game: each with the stray
    stack object (accepted is the defect, and ends the search) and then
    without (accepted is the proof that the announcement was otherwise a legal
    one, which is what makes the refusal above it a refusal *of the stack
    object*).
    """
    by_name = {card.name: card for card in catalog}
    examined = 0
    accepted: list[str] = []
    for card in compilation_units(catalog):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        if only is not None and card.name not in only:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        modes = (
            range(len(program.modes))
            if program.modes and program.mode_chooser is None else [None]
        )
        for mode in modes:
            if spec_names_the_stack(derive_cast_spec(card, program, mode_index=mode)):
                continue
            extra = {} if mode is None else {"mode_index": mode}
            game, _ = _table(by_name)
            game.players[0].hand.append(whole_card(card))
            for announcement in _plain_announcements(game):
                try:
                    strayed = game.queue_from_hand(
                        0, card.name, target_stack_index=0, **announcement, **extra
                    )
                    if strayed.supported:
                        examined += 1
                        accepted.append(card.name)
                        break
                    plain = game.queue_from_hand(0, card.name, **announcement, **extra)
                except Exception:  # noqa: BLE001 - a card needing more is not this sweep's
                    break
                if plain.supported:
                    examined += 1
                    break
    return examined, accepted


def _activation_announcement(game, source, ability_index):
    """The first target the ability's own picker offers, or ``{}`` for an
    ability that targets nothing; None where the picker offers nothing."""
    spec = game.activation_target_spec(
        0, game.battlefield_index_of(source), ability_index
    )
    if spec.get("kind") in ("none", None):
        return {}
    for entry in spec.get("valid_targets") or ():
        if entry.get("kind") == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            if permanent is not None and permanent is not source:
                return {"target_permanent_ids": [permanent.permanent_id]}
        if entry.get("kind") == "player":
            return {"target_player_index": entry["seat"]}
    return None


def _activation_sweep(catalog, *, only=None):
    """``(examined, accepted)``: the activation twin, over every activated
    ability whose spec does not name the stack — the stray announcement first
    and the plain one after it on the same table, as :func:`_cast_sweep`."""
    by_name = {card.name: card for card in catalog}
    examined = 0
    accepted: list[str] = []
    # Face by face, as the cast sweep reads them: a split card compiled whole
    # is a supported program with nothing in it.
    for card in compilation_units(catalog):
        if card.primary_type in ("instant", "sorcery"):
            continue
        if only is not None and card.name not in only:
            continue
        program = compile_card_oracle(card)
        if not program.supported or not program.activated_abilities:
            continue
        count = len(program.activated_abilities)
        for ability_index in range(count):
            try:
                game, source = _table(by_name, source=card)
                usable = game.usable_abilities_of(source)
                if ability_index >= len(usable):
                    break
                if spec_names_the_stack(derive_activation_spec(usable[ability_index])):
                    continue
                announcement = _activation_announcement(game, source, ability_index)
                if announcement is None:
                    continue
                slot = game.battlefield_index_of(source)
                strayed = game.queue_permanent_ability(
                    0, card.name, permanent_index=slot, ability_index=ability_index,
                    target_stack_index=0, **announcement,
                )
                if strayed.supported:
                    examined += 1
                    accepted.append(card.name)
                    continue
                plain = game.queue_permanent_ability(
                    0, card.name, permanent_index=slot,
                    ability_index=ability_index, **announcement,
                )
            except Exception:  # noqa: BLE001 - a cost this board cannot pay
                continue
            if plain.supported:
                examined += 1
    return examined, accepted


def test_no_cast_may_name_a_stack_object_its_spell_has_no_target_for(_catalog):
    examined, accepted = _cast_sweep(_catalog)

    assert examined >= 800, f"the sweep examined only {examined} casts"
    assert accepted == [], (
        "CR 601.2c: these spells target nothing on the stack and were "
        f"announced naming a spell there: {sorted(set(accepted))[:20]}"
    )


def test_no_activation_may_name_a_stack_object_its_ability_has_no_target_for(_catalog):
    examined, accepted = _activation_sweep(_catalog)

    assert examined >= 1300, f"the sweep examined only {examined} activations"
    assert accepted == [], (
        "CR 602.2b: these abilities target nothing on the stack and were "
        f"activated naming a spell there: {sorted(set(accepted))[:20]}"
    )


def test_the_cast_sweep_finds_the_defect_on_a_tree_that_has_it(_catalog, monkeypatch):
    """The backwards half: without the gate, the named casts are accepted."""
    monkeypatch.setattr(
        Game, "stray_stack_target_refusal", lambda self, *args, **kwargs: None,
    )
    examined, accepted = _cast_sweep(_catalog, only=_KNOWN_CASTS)

    assert examined == len(_KNOWN_CASTS)
    assert sorted(accepted) == sorted(_KNOWN_CASTS)


def test_the_activation_sweep_finds_the_defect_on_a_tree_that_has_it(
    _catalog, monkeypatch
):
    """…and the named activations: one that names a permanent beside the stack
    object, and one that targets nothing at all (a mana ability)."""
    monkeypatch.setattr(
        Game, "stray_activation_stack_target_refusal",
        lambda self, *args, **kwargs: None,
    )
    examined, accepted = _activation_sweep(_catalog, only=_KNOWN_ACTIVATIONS)

    assert examined >= len(_KNOWN_ACTIVATIONS)
    assert sorted(set(accepted)) == sorted(_KNOWN_ACTIVATIONS)


@pytest.mark.parametrize(
    "name, announcement",
    [
        ("Lightning Bolt", {"target_player_index": 1}),
        ("Wrath of God", {}),
    ],
)
def test_a_stray_stack_target_is_refused_with_the_card_in_hand(
    _catalog, name, announcement
):
    by_name = {card.name: card for card in _catalog}
    game, _ = _table(by_name)
    game.players[0].hand.append(by_name[name])

    refused = game.queue_from_hand(0, name, target_stack_index=0, **announcement)

    assert not refused.supported
    assert "targets nothing on the stack" in refused.details
    assert by_name[name] in game.players[0].hand
    assert [item.card.name for item in game.stack] == ["Shock"]
    # The same announcement without the stray object is the cast it always was.
    assert game.queue_from_hand(0, name, **announcement).supported


def test_a_counterspell_and_a_lace_still_name_their_spell(_catalog):
    """The other direction: the gate is about a spell with no target on the
    stack, never about one that has."""
    by_name = {card.name: card for card in _catalog}
    for name in ("Counterspell", "Chaoslace", "Unsubstantiate"):
        game, _ = _table(by_name)
        game.players[0].hand.append(by_name[name])
        assert game.queue_from_hand(0, name, target_stack_index=0).supported, name
