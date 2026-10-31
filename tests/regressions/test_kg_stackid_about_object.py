"""The object a trigger is about is not its target (CR 603.3d, CR 115.10).

A combat fire site names an object the ability acts on — the attacker or
blocker itself (Mijae Djinn's "remove this creature from combat"), the
creature on the other side of a block (Battering Ram's "destroy that Wall",
Aisling Leprechaun's "that creature becomes green"), the permanent a damage
event damaged (Charisma's "the other creature"). Until round kg it threaded
that object through the stack object's **target** fields, the same fields
that hold what a player chose, and every reader of a target read it as one:

* **"becomes the target"** was announced for it (CR 603.2). Under Cowardice
  ("Whenever a creature becomes the target of a spell or ability, return that
  creature to its owner's hand") 175 shipped cards' combat triggers bounced
  the creature they were about — Cockatrice's own block sent the Cockatrice
  home — and a Skulking Ghost that blocked an Aisling Leprechaun was
  sacrificed to an ability that targets nothing;
* **CR 603.3d's choice** was skipped for a line that prints its own target,
  because the gate read the object as a choice already made: Goblin Cadets'
  "target opponent gains control of it" was never chosen when it blocked, and
  did nothing.

Now the object rides its own field, ``StackItem.about_permanent_id``, recorded
only for a line that names no target of its own
(``trigger_utils.bound_event_object``) and handed to the effect by the context
builder. The census drives every shipped card printing a combat trigger down
each road that can fire it — attacking unblocked, attacking into a Wall,
blocking a Bear — and asks the announcement itself: an ability whose printed
line names no target announces nothing. Validated backwards: on the base
tree the sample names 95 of its 175 objects (every one about an object)
announced as targets; the round's scratch census of the whole pool down the
same roads counted 298 such pushes (``MTG_FULL_CENSUS=1`` runs every card).
"""
from __future__ import annotations

import random

import pytest

from engine import Game, PlayerState, faces
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import announces_a_target

from tests.helpers import _nosick, resolve_stack, stable_sample

#: One card in every STRIDE, by a digest of its name (``stable_sample``).
STRIDE = 3

#: Always in the sample: what the whole census (``MTG_FULL_CENSUS=1``) named at
#: Onslaught's promotion — the unblocked-attack site stamps its controller's
#: seat, and "…defending player discards three cards" announced it targeted.
_KNOWN = ("Mindstab Thrull", "Dauthi Mindripper")

COMBAT_KINDS = frozenset({
    "creature_attacks", "creature_attacks_or_blocks", "creature_blocks",
    "creature_blocks_or_blocked_by", "creature_becomes_blocked",
    "matching_creature_becomes_blocked", "matching_creature_blocks",
    "attacks_unblocked", "damage_dealt", "creature_dealt_damage",
})

ROADS = ("attack_unblocked", "attack_blocked", "block")


def _vanilla(name: str, type_line: str, power=None, toughness=None) -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw.update(power=str(power), toughness=str(toughness))
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw=raw,
    )


BEAR = _vanilla("Bear", "Creature - Bear", 2, 2)
WALL = _vanilla("Wall", "Creature - Wall", 1, 4)
BYSTANDER = _vanilla("Bystander", "Creature - Human", 1, 1)
RELIC = _vanilla("Relic", "Artifact")


def _put(game: Game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return _nosick(permanent)


def _settle(game: Game) -> None:
    for _ in range(60):
        if game.pending_choices:
            game.auto_resolve_pending_choices()
            game.auto_resolve_pending_replacement_choices()
            continue
        if not game.stack:
            return
        if not game.resolve_top_of_stack():
            game.auto_resolve_pending_choices()
            game.auto_resolve_pending_replacement_choices()


def _combat(card, road: str, *, watcher=None, interactive=()):
    """*card* on the side of the combat *road* puts it, with a Bystander and a
    Relic on each side so a printed target has something to choose. Returns
    the game, after the combat, and every triggered stack object pushed from
    *card* paired with what its announcement announced (``self_becomes_target``
    emits)."""
    from engine.aura_attachment import attach_aura
    import engine.events as events

    random.seed(7)
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    if watcher is not None:
        _put(game, 1, watcher)
    for seat in (0, 1):
        _put(game, seat, BYSTANDER)
        _put(game, seat, RELIC)
    creature = "Creature" in card.type_line
    if road == "block":
        attacker = _put(game, 0, BEAR)
        blocker = _put(game, 1, card if creature else WALL)
        source = blocker if creature else _put(game, 1, card)
        host = blocker
    else:
        attacker = _put(game, 0, card if creature else BEAR)
        source = attacker if creature else _put(game, 0, card)
        blocker = _put(game, 1, WALL)
        host = attacker
    if "Aura" in card.type_line:
        attach_aura(source, host)
    _settle(game)

    announced: list[tuple[object, list]] = []
    real_announce = game._announce_targeting
    real_emit = events.emit

    def announce(item):
        heard: list = []

        def emit(g, kind, /, **payload):
            if kind == "self_becomes_target":
                heard.append(payload.get("subject") or payload.get("targeted_seat"))
            return real_emit(g, kind, **payload)

        events.emit = emit
        try:
            real_announce(item)
        finally:
            events.emit = real_emit
        if item.source_permanent is source:
            announced.append((item, heard))

    game._announce_targeting = announce
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    # The attacker may not be there to declare: a 0/0 that counted nothing on
    # this board, or an upkeep that sacrificed it.
    slot = game.battlefield_index_of(attacker)
    if slot is None or game.controller_index_of(attacker) != 0:
        return game, announced
    if not game.declare_attackers(0, [slot])[0]:
        return game, announced
    _settle(game)
    if game.current_step != "declare_blockers":
        game.advance_combat_phase()
    blocks = {}
    attacking = game.battlefield_index_of(attacker) if attacker.attacking else None
    blocking = (
        game.battlefield_index_of(blocker)
        if game.controller_index_of(blocker) == 1 else None
    )
    if road != "attack_unblocked" and attacking is not None and blocking is not None:
        blocks = {blocking: attacking}
    if not game.declare_blockers(1, blocks)[0]:
        return game, announced
    _settle(game)
    game.advance_combat_phase()
    _settle(game)
    return game, announced


def _combat_cards(catalog):
    seen = set()
    # Each half of a split card is a card of its own (``faces``).
    for card in faces.compilation_units(catalog):
        if card.name in seen or "Land" in card.type_line.split(" - ")[0]:
            continue
        seen.add(card.name)
        if "Instant" in card.type_line or "Sorcery" in card.type_line:
            continue
        program = compile_card_oracle(card)
        if any(
            trig.instruction is not None and trig.condition.kind in COMBAT_KINDS
            for trig in program.triggered_abilities
        ):
            yield card


@pytest.mark.cr("603.3d", "115.10a", "603.2")
def test_a_combat_trigger_that_names_no_target_announces_none(catalog):
    """Every triggered ability a combat fire site puts on the stack from a
    sampled card, down every road: one whose printed line names no target of
    its own announces nobody as targeted, and one that prints a target
    announces only what was chosen for it — never the object the event named.
    """
    examined = acted_on = 0
    wrong: list[str] = []
    for card in _combat_cards(catalog):
        if card.name not in _KNOWN and not stable_sample(card.name, STRIDE):
            continue
        for road in ROADS:
            _game, announced = _combat(card, road)
            for item, heard in announced:
                examined += 1
                about = getattr(item, "about_permanent_id", None)
                if about is not None:
                    acted_on += 1
                    if any(
                        getattr(subject, "permanent_id", None) == about
                        for subject in heard
                    ):
                        wrong.append(f"{card.name} ({road}): announced what it is about")
                if not announces_a_target(item.ability_instruction) and heard:
                    wrong.append(f"{card.name} ({road}): names no target, announced {heard}")
    # Floors: on the pool this was written against the sample drives 175
    # triggered objects, 95 of them about an object the event named.
    assert examined >= 140, examined
    assert wrong == [], (len(wrong), wrong[:20])
    assert acted_on >= 75, acted_on


@pytest.mark.cr("603.2", "115.10a")
def test_skulking_ghost_survives_blocking_an_aisling_leprechaun(set_pool):
    """"Whenever this creature blocks or becomes blocked by a creature, that
    creature becomes green." The Ghost ("When this creature becomes the target
    of a spell or ability, sacrifice it") is that creature, and nothing
    targeted it."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    aisling = _put(game, 0, set_pool("LEG")["Aisling Leprechaun"])
    ghost = _put(game, 1, set_pool("MIR")["Skulking Ghost"])
    resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [game.battlefield_index_of(aisling)])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {game.battlefield_index_of(ghost): game.battlefield_index_of(aisling)})[0]
    resolve_stack(game)

    assert game.is_on_battlefield(ghost), game.log
    assert "Skulking Ghost became G (Aisling Leprechaun)" in game.log, game.log
    assert not any("sacrificed" in line for line in game.log)


@pytest.mark.cr("603.2", "115.10a")
def test_cowardice_does_not_bounce_a_cockatrice_for_blocking(set_pool):
    """Cowardice answers a creature that becomes a target, and Cockatrice's
    "destroy that creature at end of combat" targets nothing — the block made
    the Cockatrice "the target" of its own ability, and it went home."""
    game, announced = _combat(
        set_pool("LEA")["Cockatrice"], "block", watcher=set_pool("MMQ")["Cowardice"],
    )
    assert announced and all(heard == [] for _item, heard in announced)
    assert any(perm.card.name == "Cockatrice" for perm in game.controlled_by(1)), game.log
    assert not any("(Cowardice)" in line for line in game.log), game.log


@pytest.mark.cr("603.3d", "115.1d")
def test_goblin_cadets_blocking_chooses_its_opponent(set_pool):
    """"Whenever this creature blocks or becomes blocked, target opponent gains
    control of it." The block fire site recorded the Cadets and its own
    controller as the trigger's target, so CR 603.3d's choice was read as made
    and the Cadets' controller "gained control" of it. The opponent is chosen
    — asked of an interactive seat, defaulted for any other — and takes it."""
    cadets = set_pool("USG")["Goblin Cadets"]

    game, _ = _combat(cadets, "block")
    assert [perm.card.name for perm in game.controlled_by(0)].count("Goblin Cadets") == 1, game.log

    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}
    bear = _put(game, 0, BEAR)
    blocker = _put(game, 1, cadets)
    resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [game.battlefield_index_of(bear)])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {game.battlefield_index_of(blocker): game.battlefield_index_of(bear)})[0]
    (choice,) = game.pending_choices_of("trigger_target", 1)
    assert [entry.get("seat") for entry in choice.data["targets"]] == [0]
    assert game.confirm_trigger_target(1, seat=0)
    resolve_stack(game)
    assert game.controller_index_of(blocker) == 0, game.log


@pytest.mark.cr("603.10", "400.7")
def test_mijae_djinn_still_removes_itself_from_combat(set_pool, monkeypatch):
    """The reader the object was threaded through the target fields *for*:
    ``resolve_own_combatant`` now asks the object the trigger is about, by id.
    A creature leaving in front of the Djinn renumbers its slot and changes
    nothing."""
    import engine.handlers.combat as combat

    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    in_front = _put(game, 0, BEAR)
    djinn = _put(game, 0, set_pool("ARN")["Mijae Djinn"])
    resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [game.battlefield_index_of(djinn)])[0]
    (trigger,) = [item for item in game.stack if item.is_ability]
    assert trigger.about_permanent_id == djinn.permanent_id
    assert trigger.target_permanent_id is None and trigger.target_permanent_index is None
    game.remove_from_battlefield(in_front)

    monkeypatch.setattr(combat, "flip_coin", lambda *args, **kwargs: False)
    resolve_stack(game)
    assert not djinn.attacking and game.is_on_battlefield(djinn), game.log
    assert any("lost the coin flip: removed from combat" in line for line in game.log)


@pytest.mark.cr("603.3d", "115.1d")
def test_guerrilla_tactics_chooses_any_target(set_pool, catalog_by_name):
    """"When a spell or ability an opponent controls causes you to discard
    this card, it deals 4 damage to any target." The seat twin of the block
    site's stamp: the discard fire site handed over the player who caused it
    in ``target_player_index``, which the picker read as a choice already
    made, so the card always shot the causer. Its owner chooses — here, the
    causer's creature."""
    game = Game(players=[
        PlayerState(name="P1", hand=[catalog_by_name["Mind Rot"]]),
        PlayerState(name="P2", hand=[catalog_by_name["Guerrilla Tactics"]] * 2),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}
    bear = _put(game, 0, BEAR)
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    assert game.queue_from_hand(0, "Mind Rot", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    (discard,) = game.pending_choices
    assert discard.kind == "discard"
    assert game.confirm_discard(1, [0, 1])

    owed = game.pending_choices_of("trigger_target", 1)
    assert owed, "CR 603.3d: the owner is asked"
    assert bear.permanent_id in {entry.get("permanent_id") for entry in owed[0].data["targets"]}
    assert game.confirm_trigger_target(1, permanent_id=bear.permanent_id)
    for choice in list(game.pending_choices_of("trigger_target", 1)):
        assert game.confirm_trigger_target(1, seat=0)
    resolve_stack(game)

    assert bear.damage_marked == 4, game.log
    assert game.players[0].life == 16, game.log
