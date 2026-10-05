"""CR 602.2b / 601.2c for an **activated ability** that targets an object on
the stack: the picker, the activation gate and the handler are one list.

The spell side of this question is ``test_announced_stack_target.py``; that
file's second sweep was written when the picker read a spell's card type off
``primary_type`` and so was short of every two-type spell the handler would
counter (Annul never offered an Ornithopter). INV W1G8 noted the disagreement
"is still there for every typed counterspell"; this is the same sweep one step
over, asked of the 34 activated abilities whose spec points at the stack, with
the victims that question needs:

* a spell of **two** card types (Ornithopter, an artifact creature — CR 205.2);
* an ability from a **two-type source** (Triskelion, an artifact creature), for
  "target activated ability from an artifact source" (Ayesha Tanaka, Brown
  Ouphe).

**What it found** (INV W2G3). The type disagreement is *not* there on this
side — the ability list already asked the handler's reader. Two other things
were:

* **Goblin Artisans** and **Hidden Retreat** could be activated *naming a
  stack object their picker did not offer*. ``activation_target_refusal``
  returned before comparing the named object when its walk found no mandatory
  ``target`` quantifier, and it found none on either card — the Artisans'
  counter sits in a conditional branch the walk does not enter, and Hidden
  Retreat's kind carried no ``targets`` description at all.
* **Hidden Retreat** could also be activated with the stack **empty**, its
  cost — a card from hand put back on the library — paid for nothing.

**Validated backwards**, both halves, with floors on what was examined: a sweep
that examined nothing passes on any tree.
"""

from __future__ import annotations

import pytest

import engine.legality as legality
from engine import Game
from engine.card_loader import load_catalog
from engine.legality import targeting_instruction
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec

_SPELL_VICTIMS = (
    "Grizzly Bears", "Sol Ring", "Crusade", "Lightning Bolt", "Mind Twist",
    "Ancestral Recall", "Ornithopter", "Dark Ritual", "Wild Growth",
    "Black Knight",
)
#: ``(source permanent, what its ability is aimed at)``.
_ABILITY_VICTIMS = (
    ("Prodigal Sorcerer", "player"), ("Icy Manipulator", "own_land"),
    ("Icy Manipulator", "their_land"), ("Icy Manipulator", "source"),
    ("Triskelion", "player"), ("Triskelion", "source"),
)
_VICTIMS = _SPELL_VICTIMS + _ABILITY_VICTIMS

#: Abilities activatable with **nothing on the stack to name**, and why. A
#: two-way ratchet: a name here that is refused, or a name not here that is
#: accepted, both fail.
#:
#: Goblin Artisans — "Flip a coin. If you win the flip, draw a card. If you lose
#: the flip, counter target artifact spell you control …". The target sits in a
#: conditional branch, which ``legality._announced_target_slots`` deliberately
#: does not walk, and ``test_goblin_artisans_draws_on_a_won_flip`` holds the
#: bare activation. CR 601.2c reads the other way (a target is announced
#: whether or not the sentence it is in turns out to apply); recorded here
#: rather than changed, because the same walk decides it for every conditional
#: target in the pool and that is a pool-wide decision.
_NAMES_NOTHING = {"Goblin Artisans"}


@pytest.fixture(scope="module")
def _catalog():
    return load_catalog()


def _stack_abilities(catalog):
    """Every supported activated ability whose activation spec is ``stack``."""
    for card in catalog:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(program.activated_abilities):
            spec = derive_activation_spec(ability)
            if spec is not None and spec.get("kind") == "stack":
                yield card, index, ability, spec


def _table(card, by_name):
    """Seat 1 controls *card*, ready to activate, with what a cost may want
    (two cards in hand, a creature to sacrifice). Returns ``(game, source)``."""
    island = by_name["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[island] * 8) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for seat, name in ((0, "Forest"), (1, "Island"), (1, "Grizzly Bears")):
        game._put_permanent_onto_battlefield(
            seat, Permanent(card=by_name[name]), None
        )
    source = Permanent(card=card)
    game._put_permanent_onto_battlefield(1, source, None)
    source.metadata["summoning_sickness_turn"] = -99
    game.players[1].hand.extend([island, island])
    return game, source


def _put_victim(game, by_name, victim, source):
    """Seat 0's *victim* on the stack. Returns its stack item, or None."""
    if isinstance(victim, str):
        game.players[0].hand.append(by_name[victim])
        queued = game.queue_from_hand(0, victim, target_player_index=1)
    else:
        name, aim = victim
        permanent = Permanent(card=by_name[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        if aim == "player":
            announced = {"target_player_index": 1}
        elif aim == "source":
            announced = {"target_permanent_ids": [source.permanent_id]}
        else:
            seat = 0 if aim == "own_land" else 1
            land = next(
                perm for perm in game.controlled_by(game.players[seat])
                if perm.card.name in ("Forest", "Island")
            )
            announced = {"target_permanent_ids": [land.permanent_id]}
        queued = game.queue_permanent_ability(0, name, **announced)
    if not queued.supported or len(game.stack) != 1:
        return None
    return game.stack[0]


def _offered(game, source, ability, spec, item) -> bool:
    """Whether the activation picker lists *item* — the same call
    ``activation_target_refusal`` and the web layer make."""
    depth = len(game.stack)
    for entry in game._enumerate_targets(
        1, source.effective_card, dict(spec), for_cast=False,
        ability_instruction=targeting_instruction(ability.instruction),
        source_permanent=source, ability_source=source,
    ):
        index = entry.get("stack_index")
        if entry.get("kind") == "stack" and isinstance(index, int):
            if 0 <= depth - 1 - index < depth and game.stack[depth - 1 - index] is item:
                return True
    return False


def _label(victim) -> str:
    return victim if isinstance(victim, str) else f"{victim[0]} ability -> {victim[1]}"


def _named_sweep(catalog):
    """``(examined, accepted_unoffered, refused_offered)`` with the gate on."""
    by_name = {card.name: card for card in catalog}
    examined = 0
    accepted_unoffered: list[tuple[str, str]] = []
    refused_offered: list[tuple[str, str]] = []
    for card, index, ability, spec in _stack_abilities(catalog):
        for victim in _VICTIMS:
            game, source = _table(card, by_name)
            item = _put_victim(game, by_name, victim, source)
            if item is None:
                continue
            offered = _offered(game, source, ability, spec, item)
            result = game.queue_permanent_ability(
                1, card.name, target_stack_index=0, ability_index=index,
            )
            examined += 1
            if result.supported and not offered:
                accepted_unoffered.append((card.name, _label(victim)))
            if offered and not result.supported:
                refused_offered.append((card.name, _label(victim)))
    return examined, accepted_unoffered, refused_offered


def _handler_sweep(catalog, monkeypatch):
    """``(examined, findings)``: with the activation gate off, every ability is
    aimed at every victim its picker does **not** offer and resolved, and a
    victim that left the stack is a finding — the picker is short of something
    the handler acts on."""
    monkeypatch.setattr(
        Game, "activation_target_refusal", lambda self, *args, **kwargs: None,
    )
    by_name = {card.name: card for card in catalog}
    examined = 0
    findings: list[tuple[str, str]] = []
    for card, index, ability, spec in _stack_abilities(catalog):
        for victim in _VICTIMS:
            game, source = _table(card, by_name)
            item = _put_victim(game, by_name, victim, source)
            if item is None or _offered(game, source, ability, spec, item):
                continue
            result = game.queue_permanent_ability(
                1, card.name, target_stack_index=0, ability_index=index,
            )
            if not result.supported:
                continue
            game.resolve_top_of_stack()
            examined += 1
            if not any(entry is item for entry in game.stack):
                findings.append((card.name, _label(victim)))
    return examined, findings


def test_no_ability_can_name_a_stack_object_its_picker_does_not_offer(_catalog):
    examined, accepted_unoffered, refused_offered = _named_sweep(_catalog)

    assert examined >= 400, f"the sweep examined only {examined} activations"
    assert accepted_unoffered == [], (
        "CR 602.2b / 601.2c: activated, and paid for, naming a stack object "
        f"the printed target phrase does not admit: {accepted_unoffered}"
    )
    assert refused_offered == [], (
        "the picker offers these and the gate refuses them: "
        f"{refused_offered}"
    )


def test_the_named_sweep_finds_the_defect_on_a_tree_that_has_it(_catalog, monkeypatch):
    """Backwards. ``_STACK_TARGET_KINDS`` is what sends a named stack object to
    the comparison when the mandatory-target walk found nothing; without it
    Goblin Artisans is activatable at an opponent's Lightning Bolt again."""
    monkeypatch.setattr(legality, "_STACK_TARGET_KINDS", frozenset())
    _examined, accepted_unoffered, _refused = _named_sweep(_catalog)

    assert ("Goblin Artisans", "Lightning Bolt") in accepted_unoffered


def test_the_picker_offers_every_stack_object_an_ability_would_act_on(
    _catalog, monkeypatch
):
    examined, findings = _handler_sweep(_catalog, monkeypatch)

    assert examined >= 300, f"the sweep examined only {examined} resolutions"
    assert findings == [], (
        "CR 205.2: the handler acts on these and the picker - which is the "
        f"activation gate - does not offer them: {findings}"
    )


def test_the_handler_sweep_finds_a_picker_that_reads_one_type(_catalog, monkeypatch):
    """Backwards: the defect W1G8 named, built on purpose. A picker that asks a
    source's ``primary_type`` calls Triskelion a creature and not an artifact,
    so "activated ability from an artifact source" stops offering its ability
    while the handler — which reads every printed type — still counters it."""
    real = Game._enumerate_stack_ability_targets

    def one_type_picker(self, spec, ability_kinds, **kwargs):
        wanted = tuple(spec.get("stack_ability_source_types") or ())
        depth = len(self.stack)
        entries = real(self, spec, ability_kinds, **kwargs)
        if not wanted:
            return entries
        return [
            entry for entry in entries
            if self.stack[depth - 1 - entry["stack_index"]]
            .source_permanent.card.primary_type in wanted
        ]

    monkeypatch.setattr(Game, "_enumerate_stack_ability_targets", one_type_picker)
    _examined, findings = _handler_sweep(_catalog, monkeypatch)

    assert ("Ayesha Tanaka", "Triskelion ability -> player") in findings
    assert ("Brown Ouphe", "Triskelion ability -> player") in findings


def test_only_a_conditional_target_may_be_activated_with_nothing_to_name(_catalog):
    """CR 602.2b: an ability with a mandatory target is unactivatable while the
    stack holds nothing its phrase admits. The one exception is recorded in
    ``_NAMES_NOTHING`` with its reason."""
    by_name = {card.name: card for card in _catalog}
    examined = 0
    accepted: set[str] = set()
    for card, index, _ability, _spec in _stack_abilities(_catalog):
        game, _source = _table(card, by_name)
        result = game.queue_permanent_ability(1, card.name, ability_index=index)
        examined += 1
        if result.supported:
            accepted.add(card.name)

    assert examined >= 30, f"only {examined} bare activations examined"
    assert accepted == _NAMES_NOTHING


def test_hidden_retreat_keeps_its_card_when_there_is_no_spell_to_name(_catalog):
    """"Put a card from your hand on top of your library: Prevent all damage
    that would be dealt by **target** instant or sorcery spell this turn." With
    the stack empty there is no target, so no cost is paid (CR 602.2b)."""
    by_name = {card.name: card for card in _catalog}
    game, _retreat = _table(by_name["Hidden Retreat"], by_name)
    hand = list(game.players[1].hand)
    library = len(game.players[1].library)

    refused = game.queue_permanent_ability(1, "Hidden Retreat")

    assert not refused.supported
    assert refused.details == "no valid target for Hidden Retreat"
    assert game.players[1].hand == hand
    assert len(game.players[1].library) == library and game.stack == []


def test_hidden_retreat_cannot_name_a_creature_spell(_catalog):
    by_name = {card.name: card for card in _catalog}
    game, retreat = _table(by_name["Hidden Retreat"], by_name)
    assert _put_victim(game, by_name, "Grizzly Bears", retreat) is not None
    hand = list(game.players[1].hand)

    refused = game.queue_permanent_ability(
        1, "Hidden Retreat", target_stack_index=0,
    )

    assert not refused.supported
    assert game.players[1].hand == hand and len(game.stack) == 1


def test_goblin_artisans_cannot_name_an_opponents_instant(_catalog):
    """"…counter target **artifact** spell **you control**": an opponent's
    Lightning Bolt is neither, and naming it is refused before the tap."""
    by_name = {card.name: card for card in _catalog}
    game, artisans = _table(by_name["Goblin Artisans"], by_name)
    assert _put_victim(game, by_name, "Lightning Bolt", artisans) is not None

    refused = game.queue_permanent_ability(
        1, "Goblin Artisans", target_stack_index=0,
    )

    assert not refused.supported
    assert refused.details == "no valid target for Goblin Artisans"
    assert not artisans.tapped and len(game.stack) == 1
