"""Census: every entry trigger is a stack object, never an effect of the entry.

CR 603.3: "Once an ability has triggered, its controller puts it on the stack
as an object that's not a card the next time a player would receive priority."
CR 603.6a makes "when this permanent enters" an ordinary triggered ability, so
it is put on the stack like a dies trigger or an upkeep trigger, and until it
resolves every player gets priority with it there.

This engine carried a permanent's own entry trigger out **inline**, inside the
event that put the permanent onto the battlefield — a standing approximation
that went in with Arabian Nights (Oubliette), when the reason was that nothing
could choose a trigger's target. ``_choose_trigger_targets`` has been that
picker since, and the approximation outlived its reason: nothing could respond
to an entry trigger, so Planeshift's best-known play — Cavern Harpy returned to
its owner's hand in response to its own gating trigger — could not be made.

The sweep asks the question of **every supported permanent in both manifest
roles** that prints an entry trigger, on the three roads a permanent takes to
the battlefield:

* **cast**, with the picker's own announcement and every kicker the card
  offers paid, the spell then resolved once — a land is played instead, which
  puts no spell on the stack at all;
* **cast bare**, the same with nothing announced;
* **put** onto the battlefield by an effect (a reanimation, a token, "put it
  onto the battlefield"), which is an entry nothing cast.

On each road it instruments the engine's own dispatch and requires, of every
trigger, that **no instruction of it ran inside the entry**, and that it is
either an object on the stack whose source is the permanent that entered, or
absent for a reason the rules name: its intervening "if" was false as it
triggered (CR 603.4), or it had a target to choose and no legal one
(CR 603.3d).

Validated backwards: on the tree before the change this fails naming 265 of
278 entry triggers executed inline on the cast road and 211 on the put road.
The floors are what stop a later filter from making the sweep pass by
examining nothing.

**What is left, pinned.** Three Auras' entry sentences are not dispatched as
triggers at all when the Aura is *cast*: ``_apply_aura_effect`` performs them
itself, by text, as the Aura attaches — Animate Dead's and Dance of the Dead's
reanimation and Earthbind's conditional damage. They are the last entry
effects with no stack object and no window, and ``_PERFORMED_BY_THE_ATTACH``
holds them to exactly those three names: the set can neither grow nor quietly
shrink. Each needs its bespoke branch retired onto the trigger it already
compiles — the same three go on the stack today when *put* onto the
battlefield, where the attach path is not involved.
"""

from __future__ import annotations

from functools import lru_cache

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_ENTRY_CONDITIONS = frozenset({"enters_battlefield", "enters_or_dies"})
_ROADS = ("cast", "cast_bare", "put")

# 278 entry triggers on 269 permanents across both roles (October 2026).
# Floors, not equalities: the pool grows.
_MIN_TRIGGERS = 270
_MIN_CARDS = 260
# ...and how many of them each road actually left on the stack. A trigger whose
# "if" is false or that has no legal target is legitimately absent, so these
# sit below the totals: 269 on the cast road, 254 on the put road.
_MIN_STACKED_WHEN_CAST = 255
_MIN_STACKED_WHEN_PUT = 240
_MIN_LAND_TRIGGERS = 25
_MIN_AURA_TRIGGERS = 20

#: Cast Auras whose entry sentence ``_apply_aura_effect`` performs inline, by
#: text, instead of the entry site announcing the trigger they compile. A
#: ratchet: equality, not membership.
_PERFORMED_BY_THE_ATTACH = frozenset({"Animate Dead", "Dance of the Dead", "Earthbind"})

_BOARD = ("Grizzly Bears", "Black Knight", "Forest", "Island", "Sol Ring", "Castle")
_YARD = ("Hill Giant", "Lightning Bolt", "Ornithopter", "Holy Strength", "Swamp")
_HAND = ("Scryb Sprites", "Mountain", "Giant Growth")
_LIBRARY = (
    "Forest", "Craw Wurm", "Plains", "Counterspell", "Mox Pearl", "Swamp",
    "Mountain", "Island", "Serra Angel", "Terror",
) * 3


@lru_cache(maxsize=1)
def _pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


@lru_cache(maxsize=1)
def _entry_trigger_cards() -> tuple:
    """``(card, entry triggers)`` for every supported permanent printing one."""
    rows = []
    for card in _pool().values():
        if card.primary_type in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        triggers = tuple(
            trig for trig in program.triggered_abilities
            if trig.condition.kind in _ENTRY_CONDITIONS
            and trig.supported and trig.instruction is not None
        )
        if triggers:
            rows.append((card, triggers))
    return tuple(sorted(rows, key=lambda row: row[0].name))


def _table(card) -> tuple[Game, list]:
    """A two-seat table holding *card*, with something of every kind for an
    entry trigger to act on, and its dispatch recorded.

    ``executed_in_entry`` collects every instruction the entry site ran itself.
    Wrapped on the instance and counted by depth, so a trigger that is on the
    stack and resolves later — outside the entry — is not counted against it.
    """
    pool = _pool()

    def named(names):
        return [pool[name] for name in names]

    game = Game(players=[
        PlayerState("A", library=named(_LIBRARY), hand=[card] + named(_HAND),
                    graveyard=named(_YARD)),
        PlayerState("B", library=named(_LIBRARY), hand=named(_HAND),
                    graveyard=named(_YARD)),
    ])
    game.enforce_mana_costs = False
    # A human at each seat: nothing is defaulted on the spot, so a prompt the
    # entry would have armed inline is still a prompt nobody has answered.
    game.interactive_seats = {0, 1}
    for seat in (0, 1):
        for symbol in "WUBRG":
            game.players[seat].mana_pool[symbol] = 20
        for name in _BOARD:
            game._put_permanent_onto_battlefield(seat, Permanent(card=pool[name]), None)

    executed_in_entry: list = []
    depth = [0]
    entry = game._apply_self_enters_battlefield_triggers
    execute = game._execute_oracle_instruction

    def recording_entry(*args, **kwargs):
        depth[0] += 1
        try:
            return entry(*args, **kwargs)
        finally:
            depth[0] -= 1

    def recording_execute(instruction, context, *args, **kwargs):
        if depth[0]:
            executed_in_entry.append(instruction)
        return execute(instruction, context, *args, **kwargs)

    game._apply_self_enters_battlefield_triggers = recording_entry
    game._execute_oracle_instruction = recording_execute
    return game, executed_in_entry


def _kickers(game, card) -> dict:
    """Every optional cost *card* offers, taken once — so an entry trigger
    printed "if it was kicked" is one this sweep reaches."""
    taken = {}
    for offer in game.cast_cost_offers(0, card, from_zone="hand") or ():
        key = offer.get("key") or offer.get("symbols")
        if key:
            taken[key] = 1
    return taken


def _announcement(game, card, payments) -> dict:
    """The picker's first legal target as ``queue_from_hand`` keywords — an
    opponent's permanent before the caster's own, a permanent before a seat."""
    spec = game.cast_target_spec(0, card, optional_cost_payments=payments)
    targets = spec.get("valid_targets") or []
    if not targets:
        return {}
    first = sorted(
        targets,
        key=lambda entry: (entry.get("kind") != "permanent", entry.get("seat") != 1),
    )[0]
    if first.get("kind") == "permanent":
        permanent = game.permanent_at(game.players[first["seat"]], first["index"])
        return {
            "target_player_index": first["seat"],
            "target_permanent_ids": [permanent.permanent_id],
        }
    if first.get("kind") == "player":
        return {"target_player_index": first["seat"]}
    if first.get("kind") in ("graveyard", "graveyard_card"):
        return {
            "target_player_index": first.get("seat"),
            "target_permanent_index": first.get("index"),
        }
    return {}


def _enter(card, road) -> tuple[Game, list, Permanent | None] | None:
    """Put *card* onto seat 0's battlefield by *road*; None if a cast was
    refused (an Aura cast with no target named, say)."""
    game, executed_in_entry = _table(card)
    if road == "put":
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        return game, executed_in_entry, permanent
    payments = _kickers(game, card)
    keywords = _announcement(game, card, payments) if road == "cast" else {}
    if payments:
        keywords["optional_cost_payments"] = payments
        if any("X" in key for key in payments):
            keywords["x_value"] = 2
    result = game.queue_from_hand(0, card.name, **keywords)
    if not result.supported:
        return None
    if card.primary_type != "land":
        # The permanent spell, and nothing else: one resolution.
        assert game.stack and game.stack[-1].card is card, card.name
        game.resolve_top_of_stack(pause_for_choices=True)
    permanent = next(
        (perm for perm in game.controlled_by(0) if perm.card is card), None
    )
    return game, executed_in_entry, permanent


def _chooses_a_target(game, trigger) -> bool:
    return bool(game._entry_trigger_chooses_a_target(trigger.instruction))


def test_w2g6_no_entry_trigger_is_carried_out_inside_the_entry():
    """CR 603.3 over the pool: on every road onto the battlefield, an entry
    trigger's instruction is not run by the entry, and the trigger is a stack
    object — or absent for CR 603.4's or CR 603.3d's reason."""
    rows = _entry_trigger_cards()
    cards = {card.name for card, _ in rows}
    triggers = sum(len(found) for _, found in rows)
    assert triggers >= _MIN_TRIGGERS, triggers
    assert len(cards) >= _MIN_CARDS, len(cards)

    inline: dict[str, list[str]] = {road: [] for road in _ROADS}
    unexplained: list[str] = []
    performed_by_the_attach: set[str] = set()
    stacked = {road: 0 for road in _ROADS}
    land_triggers = aura_triggers = 0
    stacked_cards: dict[str, set] = {road: set() for road in _ROADS}

    for card, found in rows:
        land_triggers += len(found) * (card.primary_type == "land")
        aura_triggers += len(found) * ("Aura" in card.type_line)
        for road in _ROADS:
            entered = _enter(card, road)
            if entered is None:
                continue
            game, executed_in_entry, _permanent = entered
            for trigger in found:
                if any(ran is trigger.instruction for ran in executed_in_entry):
                    inline[road].append(card.name)
                    continue
                on_stack = [
                    item for item in game.stack
                    if item.ability_instruction is trigger.instruction
                ]
                if on_stack:
                    assert all(
                        item.source_permanent is not None
                        and item.source_permanent.card is card
                        for item in on_stack
                    ), card.name
                    stacked[road] += 1
                    stacked_cards[road].add(card.name)
                    continue
                payload = trigger.instruction.payload or {}
                if "intervening_if" in payload or _chooses_a_target(game, trigger):
                    # CR 603.4: it did not trigger. CR 603.3d: it triggered and
                    # had no legal choice, so it was removed from the stack.
                    continue
                if road != "put" and "Aura" in card.type_line:
                    # No object and no reason the rules name: the attach path
                    # performed the sentence itself. Collected, and held to
                    # the pinned names below.
                    performed_by_the_attach.add(card.name)
                    continue
                unexplained.append(f"{card.name} [{road}]: {trigger.source_line}")

    assert not any(inline.values()), {
        road: (len(names), sorted(set(names))[:12])
        for road, names in inline.items() if names
    }
    assert not unexplained, unexplained[:12]
    assert performed_by_the_attach == _PERFORMED_BY_THE_ATTACH, (
        sorted(performed_by_the_attach ^ _PERFORMED_BY_THE_ATTACH)
    )
    assert stacked["cast"] >= _MIN_STACKED_WHEN_CAST, stacked
    assert stacked["put"] >= _MIN_STACKED_WHEN_PUT, stacked
    assert land_triggers >= _MIN_LAND_TRIGGERS, land_triggers
    assert aura_triggers >= _MIN_AURA_TRIGGERS, aura_triggers
    # The card the defect was named for, a targeted one whose target the cast
    # announced, a land (played: no spell resolves around it) and an Aura.
    assert {"Cavern Harpy", "Man-o'-War", "Karoo", "Paralyze"} <= stacked_cards["cast"]
    assert {"Cavern Harpy", "Man-o'-War", "Karoo"} <= stacked_cards["put"]
