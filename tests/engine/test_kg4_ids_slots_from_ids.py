"""A stack object names its permanents by id; the slots are re-read off the
ids as it resolves — for a triggered ability as for a spell.

kg4 / ``ids`` part 3. ``bare_announcements.resolving_slots`` re-read a spell's
and an activated ability's slots off their stamped ids at resolution; a
triggered ability kept the slot its fire site (or its target prompt) wrote, so
a trigger whose target slid down a slot while it waited handed its handler
the slot of whatever had slid into the old one. And every stack object kept
its slot channel beside its ids for life, a second copy that each re-aim, copy,
CR 608.2b blank and seat re-settle had to remember to rewrite.

Now the push consumes the announcement's slots into ids
(``Game._stamp_stack_targets``) — the stack object carries none — and every
resolution context's slots are derived from the ids on the seat it resolves
about. These tests drive a trigger across a renumbering, and hold the
invariant over a seeded game: at every handler dispatch whose context names
permanents by id, the slot channel is exactly what the ids say now.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, ai_rehearsal
from engine.faces import compilation_units
from engine.handlers import EFFECT_HANDLERS
from engine.models import Permanent


@pytest.fixture(scope="module")
def cards(catalog):
    pool: dict = {}
    for unit in compilation_units(catalog):
        pool.setdefault(unit.name, unit)
    return pool


def _derived(game, context):
    """The slots *context*'s ids name on its own seat's battlefield, now."""
    seat = context.target
    slots = []
    for permanent_id in context.target_permanent_id or ():
        permanent = (
            game.permanent_by_id(permanent_id) if isinstance(permanent_id, int) else None
        )
        slots.append(
            None if permanent is None or not game.controls(seat, permanent)
            else game.battlefield_index_of(permanent)
        )
    return slots


def test_a_trigger_resolves_with_the_slot_its_target_has_now(cards, monkeypatch):
    """Nekrataal named the Hill Giant (slot 1, above a Grizzly Bears) as it was
    cast. While its trigger waits the Bears leaves, and the Giant slides into
    slot 0: the trigger's object holds the Giant's id and no slot, and the
    destroy runs with slot 0 — the Giant's — not the stale slot 1."""
    p1 = PlayerState(name="P1", hand=[cards["Nekrataal"]],
                     library=[cards["Island"]] * 10)
    p2 = PlayerState(name="P2", library=[cards["Island"]] * 10)
    game = Game(players=[p1, p2])
    bears = Permanent(card=cards["Grizzly Bears"])
    giant = Permanent(card=cards["Hill Giant"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game._put_permanent_onto_battlefield(1, giant, None)
    assert game.queue_from_hand(
        0, "Nekrataal", target_player_index=1, target_permanent_index=1,
    ).supported
    game.resolve_top_of_stack()
    trigger = next(obj for obj in game.stack if obj.is_ability)
    assert trigger.target_permanent_index is None
    assert trigger.target_permanent_id == [giant.permanent_id]

    game.remove_from_battlefield(bears)
    assert game.battlefield_index_of(giant) == 0

    seen = []
    kind = trigger.ability_instruction.kind
    handler = EFFECT_HANDLERS[kind]

    def watching(game_, instruction, context):
        seen.append(list(context.target_permanent_index or ()))
        return handler(game_, instruction, context)

    monkeypatch.setitem(EFFECT_HANDLERS, kind, watching)
    game.resolve_top_of_stack()
    assert seen == [[0]], seen
    assert not game.is_on_battlefield(giant)


@pytest.mark.full
def test_every_dispatch_reads_the_slots_its_ids_name(monkeypatch):
    """The invariant, over seeded games: wherever a resolving context names
    permanents by id (and is not handed the object a trigger is *about*), its
    slot channel is the ids' slots on its seat — a derived cache, never a
    second record. A floor on how many such dispatches were read, triggered
    ones among them."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    read = {"spell": 0, "activated": 0, "triggered": 0}
    wrong = []
    resolving: list = []
    original = Game._run_stack_item_resolution

    def tracked(self, item):
        resolving.append(item)
        try:
            return original(self, item)
        finally:
            resolving.pop()

    monkeypatch.setattr(Game, "_run_stack_item_resolution", tracked)

    def wrap(kind, handler):
        def recording(game, instruction, context):
            if (
                not ai_rehearsal.rehearsing()
                and context.target_permanent_id
                and not context.target_graveyard_card
                and getattr(context, "about_permanent_id", None) is None
                and context.target is not None
            ):
                item = resolving[-1] if resolving else None
                label = (
                    "spell" if item is None or not item.is_ability
                    else item.ability_kind or "triggered"
                )
                read[label] = read.get(label, 0) + 1
                if list(context.target_permanent_index or ()) != _derived(game, context):
                    wrong.append(
                        f"{context.card.name} {kind}: slots "
                        f"{context.target_permanent_index}, ids say {_derived(game, context)}"
                    )
            return handler(game, instruction, context)
        return recording

    for kind, handler in list(EFFECT_HANDLERS.items()):
        monkeypatch.setitem(EFFECT_HANDLERS, kind, wrap(kind, handler))
    for code in ("LEA", "MIR", "TMP", "ONS"):
        run_ai_simulation(manifest_set_path(code), games=1, seed=11, max_turns=14)
    assert sum(read.values()) >= 10, read
    assert read.get("triggered", 0) >= 1 and read.get("activated", 0) >= 1, read
    assert not wrong, "\n".join(wrong[:20])


def test_an_aura_whose_host_left_enchants_nobody_else(cards):
    """Holy Strength named the Grizzly Bears (slot 0, below a Hill Giant); the
    Bears leaves while the Aura waits, and the Giant slides into slot 0. The
    Aura names its host by id, the host is gone, so it is put into its
    owner's graveyard (CR 303.4g) — it neither enchants the creature now in
    the old slot (the stale slot did) nor scans for one ("no slot" is not
    "nothing named")."""
    p1 = PlayerState(name="P1", hand=[cards["Holy Strength"]],
                     library=[cards["Island"]] * 10)
    p2 = PlayerState(name="P2", library=[cards["Island"]] * 10)
    game = Game(players=[p1, p2])
    bears = Permanent(card=cards["Grizzly Bears"])
    giant = Permanent(card=cards["Hill Giant"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game._put_permanent_onto_battlefield(1, giant, None)
    assert game.queue_from_hand(
        0, "Holy Strength", target_player_index=1, target_permanent_index=0,
    ).supported
    assert game.stack[-1].target_permanent_id == [bears.permanent_id]
    game.remove_from_battlefield(bears)
    game.resolve_top_of_stack()
    assert giant.metadata.get("attached_auras") in (None, [], ())
    assert not any(
        perm.card.name == "Holy Strength" for perm in game.controlled_by(0)
    )
    assert any(card.name == "Holy Strength" for card in p1.graveyard)
