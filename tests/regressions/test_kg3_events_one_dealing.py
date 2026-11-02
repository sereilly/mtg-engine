"""Damage several sources deal at once is one event, and a damage trigger is
once per the end of it the sentence names (CR 603.2c, CR 510.2).

``engine/simultaneous_damage.py`` states the reading and its sources. In short:

* **recipient-keyed** — "whenever this creature is dealt damage", "whenever
  enchanted creature is dealt damage", "whenever a creature is dealt damage",
  "whenever you're dealt damage": once per recipient, for the total every
  source dealt it (Fungusaur's ruling, 2004-10-04: "If more than one creature
  damages it at one time, it only gets one counter"; Boros Reckoner's,
  Sporeweb Weaver's, Wrathful Raptors', Vengeful Pharaoh's);
* **source-keyed** — "whenever this creature deals damage", "whenever a red
  creature or spell deals damage": once per source, for the total it dealt to
  every recipient (Drinker of Sorrow's ruling, 2004-10-04: "You only sacrifice
  one permanent, no matter how many things it deals damage to"; Justice's:
  "Justice will add up all the damage done and deal damage to the source's
  controller at one time");
* **pair-keyed** — both ends named: once per chunk, as every damage event
  already was.

The census reads every damage trigger in both manifest roles, classifies it
from its compiled condition, and drives each recipient- and source-keyed one
under **one multi-source combat damage step**: its subject double-blocked by
two 1/1s, so two chunks reach it (or leave it) at once. Exactly one trigger,
for the total, is the rule. Then a sweep: Justice beside an Earthquake (one
source, several recipients: one trigger) and Pestilence's activation beside
Fungusaurs and a Blood Hound (one source, one chunk per recipient: one
trigger each, unchanged).

No card in the pool deals **non-combat** damage from two sources to one
recipient at once: its three fights and Wave of Reckoning deal one chunk to
each recipient (census run at kg3).

Validated backwards: on 753c241a every recipient- and source-keyed card
triggered once per chunk (Blood Hound four times for four attackers), and
Justice once per Earthquake recipient.
"""

from __future__ import annotations

import dataclasses

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from engine.simultaneous_damage import PAIR, RECIPIENT, SOURCE, occurrence
from tests.helpers import resolve_stack

_UNITS = {}
for _card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
    _UNITS.setdefault(_card.name, _card)

_KINDS = {"damage_dealt", "creature_dealt_damage"}
#: Floors on what the census examines (kg3: 24 recipient-keyed cards, 17
#: source-keyed, 113 damage triggers in all).
_RECIPIENT_FLOOR = 24
_SOURCE_FLOOR = 15
_TRIGGER_FLOOR = 100


def _reading(trig) -> str:
    if trig.condition.kind == "creature_dealt_damage":
        return RECIPIENT
    return occurrence(trig.condition.payload or {})


def _census():
    rows = []
    for name, card in sorted(_UNITS.items()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trig in program.triggered_abilities:
            if trig.condition is not None and trig.condition.kind in _KINDS:
                rows.append((name, card, trig, _reading(trig)))
    return rows


def _test_creature(name: str, power: int, toughness: int, *, flying: bool = False,
                   red_sliver: bool = False) -> CardDefinition:
    type_line = "Creature — Sliver" if red_sliver else "Creature — Test"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="Flying" if flying else "",
        colors=("R",) if red_sliver else (), color_identity=(),
        keywords=("Flying",) if flying else (), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


#: Something for an "Enchant artifact" Aura (Living Artifact) to stay on.
_ARTIFACT = CardDefinition(
    name="Host Artifact", mana_cost="", cmc=0.0, type_line="Artifact",
    oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
    raw={"name": "Host Artifact", "type_line": "Artifact"},
)


def _able_to_attack(card: CardDefinition) -> CardDefinition:
    """*card* without "Defender" (Wall of Souls, Wall of Essence, …), so it can
    be the creature double-blocked: the trigger under census is unchanged."""
    lines = [
        line for line in (card.oracle_text or "").split("\n")
        if not line.strip().lower().startswith("defender")
    ]
    keywords = tuple(k for k in card.keywords if str(k).lower() != "defender")
    return dataclasses.replace(card, oracle_text="\n".join(lines), keywords=keywords)


def _put(game: Game, seat: int, card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table() -> Game:
    game = Game(players=[
        PlayerState(f"P{seat}", library=[_UNITS["Island"]] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


def _double_blocked(game: Game, attacker: Permanent) -> None:
    """Seat 0's *attacker* is blocked by two 1/1s of seat 1 (flying, so a flyer
    can be blocked) and combat damage is dealt: two chunks to it, and two from
    it — one combat damage step, one event (CR 510.2)."""
    first = _put(game, 1, _test_creature("First Blocker", 1, 1, flying=True))
    second = _put(game, 1, _test_creature("Second Blocker", 1, 1, flying=True))
    _combat(game, [attacker], [(first, attacker), (second, attacker)])


def _combat(game: Game, attackers, blocks) -> None:
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(a) for a in attackers], defending_player_index=1,
    )
    assert ok, why
    game._set_phase_and_step("combat", "declare_blockers")
    ok, why = game.declare_blockers(1, {
        game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)]
        for blocker, attacker in blocks
    })
    assert ok, why
    game._set_phase_and_step("combat", "combat_damage")
    ok, why = game.resolve_all_combat_damage(0)
    assert ok, why


def _triggers(game: Game, watcher: Permanent, trig) -> list:
    return [
        item for item in game.stack
        if item.source_permanent is watcher
        and (item.ability_text or "").strip() == (trig.source_line or "").strip()
    ]


def _amount(item) -> int:
    context = item.trigger_context or {}
    return int(context.get("damage_dealt", context.get("amount", 0)) or 0)


def _recipient_board(card: CardDefinition, trig):
    """The board for a recipient-keyed trigger: (game, watcher, subject, total
    dealt to the subject)."""
    game = _table()
    payload = trig.condition.payload or {}
    if trig.condition.kind == "damage_dealt":
        # "Whenever you're dealt damage": the watcher's controller is dealt
        # damage by two unblocked attackers at once.
        if "Aura" in card.type_line:
            host = _put(game, 1, _ARTIFACT)
            watcher = _put(game, 1, card)
            attach_aura(watcher, host)
        else:
            watcher = _put(game, 1, card)
        resolve_stack(game)
        game.pending_choices.clear()
        before = game.players[1].life
        attackers = [_put(game, 0, _test_creature(f"Attacker {i}", 1, 1)) for i in range(2)]
        _combat(game, attackers, [])
        return game, watcher, game.players[1], before - game.players[1].life
    if "damaged_attached" in payload:
        subject = _put(game, 0, _test_creature("Enchanted Attacker", 3, 3))
        watcher = _put(game, 0, card)
        attach_aura(watcher, subject)
    elif "damaged_filter" in payload:
        watcher = _put(game, 0, card)
        subject = _put(game, 0, _test_creature("Attacker", 3, 3))
    else:
        subject = watcher = _put(game, 0, _able_to_attack(card))
    resolve_stack(game)
    game.pending_choices.clear()
    _double_blocked(game, subject)
    return game, watcher, subject, 2


def _source_board(card: CardDefinition, trig):
    """The board for a source-keyed trigger: (game, watcher, subject)."""
    game = _table()
    payload = trig.condition.payload or {}
    if "damager_attached" in payload:
        subject = _put(game, 0, _test_creature("Enchanted Attacker", 3, 3))
        watcher = _put(game, 0, card)
        attach_aura(watcher, subject)
    elif "damager_self" in payload or "Creature" in card.type_line:
        subject = watcher = _put(game, 0, _able_to_attack(card))
    else:
        watcher = _put(game, 0, card)
        subject = _put(game, 0, _test_creature("Red Sliver", 3, 3, red_sliver=True))
    resolve_stack(game)
    game.pending_choices.clear()
    _double_blocked(game, subject)
    return game, watcher, subject


def test_a_damage_trigger_is_once_per_the_end_of_the_event_it_names():
    rows = _census()
    assert len(rows) >= _TRIGGER_FLOOR, len(rows)
    recipient = [row for row in rows if row[3] == RECIPIENT]
    source = [row for row in rows if row[3] == SOURCE]
    assert len({row[0] for row in recipient}) >= _RECIPIENT_FLOOR, [r[0] for r in recipient]
    assert len({row[0] for row in source}) >= _SOURCE_FLOOR, [r[0] for r in source]

    wrong = []
    for name, card, trig, _ in recipient:
        game, watcher, subject, total = _recipient_board(card, trig)
        fired = [
            item for item in _triggers(game, watcher, trig)
            if not isinstance(subject, Permanent)
            or (item.trigger_context or {}).get("event_subject_permanent_id")
            == subject.permanent_id
        ]
        if len(fired) != 1 or _amount(fired[0]) != total:
            wrong.append((name, "recipient", [_amount(i) for i in fired], total))
    for name, card, trig, _ in source:
        game, watcher, subject = _source_board(card, trig)
        fired = _triggers(game, watcher, trig)
        dealt = sum(
            entry.amount for entry in game.damage_ledger.entries
            if entry.source_permanent_id == subject.permanent_id
        )
        if len(fired) != 1 or _amount(fired[0]) != dealt or dealt <= 0:
            wrong.append((name, "source", [_amount(i) for i in fired], dealt))
    assert wrong == [], (
        "a trigger that names one end of a simultaneous damage event fired "
        "other than once, for the total (card, reading, amounts it fired "
        f"with, the total): {wrong}"
    )


def test_pair_keyed_triggers_still_fire_per_chunk():
    """Both ends named: Vengeful Pharaoh's ruling has damage to you and to a
    planeswalker trigger twice, and Pain Magnification's has one source
    hitting two opponents trigger "once for each". A Spiritmonger ("whenever
    this creature deals damage to a creature") double-blocked deals damage to
    two creatures: two triggers."""
    game = _table()
    monger = _put(game, 0, _UNITS["Spiritmonger"])
    trig = next(
        t for t in compile_card_oracle(_UNITS["Spiritmonger"]).triggered_abilities
        if t.condition.kind == "damage_dealt"
    )
    assert occurrence(trig.condition.payload) == PAIR
    _double_blocked(game, monger)
    assert len(_triggers(game, monger, trig)) == 2


def test_blood_hound_takes_four_attackers_as_one_event():
    """The entry's own board: four attackers, unblocked, one combat damage
    step. One trigger, for 4 — and, answered yes, four counters."""
    game = _table()
    game.interactive_seats = {1}
    hound = _put(game, 1, _UNITS["Blood Hound"])
    attackers = [_put(game, 0, _test_creature(f"Attacker {i}", 1, 1)) for i in range(4)]
    _combat(game, attackers, [])
    fired = [item for item in game.stack if item.source_permanent is hound]
    assert [_amount(item) for item in fired] == [4]
    resolve_stack(game)
    while game.pending_choice_of("optional_pay", 1) is not None:
        assert game.resolve_pending_choice("optional_pay", 1, accept=True)
        resolve_stack(game)
    assert counters_on(hound, "+1/+1") == 4
    assert sum("Blood Hound gets 4 +1/+1 counters" in line for line in game.log) == 1


def test_a_sweep_is_one_event_for_its_source():
    """Justice ("whenever a red creature or spell deals damage, this enchantment
    deals that much damage to that creature's or spell's controller") beside
    an Earthquake for 1 that reaches two players and two creatures: one
    Justice trigger for 4, as its ruling adds it up. On the base, four."""
    game = _table()
    justice = _put(game, 1, _UNITS["Justice"])
    _put(game, 0, _test_creature("Bear A", 2, 2))
    _put(game, 1, _test_creature("Bear B", 2, 2))
    game.players[0].hand.append(_UNITS["Earthquake"])
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.cast_from_hand(0, "Earthquake", x_value=1)
    resolve_stack(game)
    assert sum("Justice dealt" in line for line in game.log) == 1, game.log
    assert "Justice dealt 4 damage to P0" in game.log
    assert justice is not None


def test_pestilence_is_one_chunk_per_recipient():
    """Pestilence's activation: one source, one chunk to each creature and each
    player — so a Fungusaur on each side grows one counter apiece, and a
    Blood Hound's controller is dealt damage once (one trigger, for 1)."""
    game = _table()
    game.interactive_seats = {1}
    pestilence = _put(game, 0, _UNITS["Pestilence"])
    first = _put(game, 0, _able_to_attack(_UNITS["Fungusaur"]))
    second = _put(game, 1, _UNITS["Fungusaur"])
    for fungusaur in (first, second):
        game.place_plus1_counters(fungusaur, 2)
    hound = _put(game, 1, _UNITS["Blood Hound"])
    game.place_plus1_counters(hound, 2)
    game._sync_control()
    game._set_phase_and_step("precombat_main", "precombat_main")
    result = game.activate_permanent_ability(0, "Pestilence")
    assert result.supported, result.details
    resolve_stack(game)
    offers = 0
    while game.pending_choice_of("optional_pay", 1) is not None:
        offers += 1
        assert game.resolve_pending_choice("optional_pay", 1, accept=True)
        resolve_stack(game)
    assert offers == 1
    assert counters_on(hound, "+1/+1") == 3
    assert counters_on(first, "+1/+1") == 3
    assert counters_on(second, "+1/+1") == 3
    assert pestilence is not None
