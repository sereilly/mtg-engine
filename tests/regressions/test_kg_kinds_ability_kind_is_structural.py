"""Whether a stack object is an activated or a triggered ability (CR 113.3b–c)
is how it got there, never what its effect label says.

``engine/effect_labels.py`` is a reporting vocabulary — "never dispatch" — and
its prefixes do not follow the ability's kind: the activated table files
`add_counter_to_target` under `triggered_counter` (Dwarven Weaponsmith's hook
declared it, and the table carried it so the card was not re-bucketed), and the
triggered tables give hundreds of triggers `upkeep_effect` or `spell_pattern`.
Three readers took the prefix as the answer anyway:

* ``handlers/stack._stack_ability_kind`` — what "counter target **activated**
  ability" asks (Rust, Interdict, Bind, Brown Ouphe, Ayesha Tanaka), through
  the handler and the picker (``legality_stack``). Measured on the base: the
  23 shipped activated abilities labelled `triggered_counter` — Serrated
  Arrows, Extruder, Living Armor, the eleven Spikes among them — could not be
  targeted or countered by any of them.
* ``stack_targets._is_triggered`` — which list a target change is offered
  from (CR 115.7), triggered abilities' narrowing included.
* ``web/serialization`` — the stack item's ``is_triggered``. Every upkeep
  trigger labelled `upkeep_effect` reached the client as not triggered, and
  every `triggered_counter` activation as triggered.

The structural mark already exists: ``StackItem.activated``, set by the three
activation paths (CR 602.2) and by nothing else. A seeded game census over the
shipped pool found every object labelled `activated_*` carrying it, and the
`triggered_counter` activations carrying it too.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.pt import add_plus1_counters
from tests.helpers import resolve_stack
from web.serialization import _serialize_stack_item

CATALOG = {card.name: card for card in load_catalog()}


def _ready(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _arrows_board():
    arrows = _ready(Permanent(card=CATALOG["Serrated Arrows"]))
    arrows.metadata["arrowhead_counters"] = 3
    bears = _ready(Permanent(card=CATALOG["Grizzly Bears"]))
    p1 = PlayerState(name="P1", battlefield=[arrows], library=[CATALOG["Island"]] * 5, life=20)
    p2 = PlayerState(name="P2", battlefield=[bears], hand=[CATALOG["Rust"], CATALOG["Bind"]],
                     library=[CATALOG["Island"]] * 5, life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, arrows, bears


def test_an_activated_ability_with_a_triggered_label_is_still_activated():
    """Serrated Arrows' "{T}, Remove an arrowhead counter from this artifact:
    Put a -1/-1 counter on target creature." is labelled `triggered_counter`;
    on the stack it is an activated ability, and the wire says so."""
    game, arrows, bears = _arrows_board()
    result = game.queue_permanent_ability(0, "Serrated Arrows", target_player_index=1, target_permanent_index=0)
    assert result.supported, result.details
    item = game.stack[-1]
    assert item.ability_effect_kind == "triggered_counter", "the label this guards against"
    assert item.activated
    assert _serialize_stack_item(item, game)["is_triggered"] is False


def test_rust_counters_an_artifact_s_activated_ability_whatever_its_label():
    """"Counter target activated ability from an artifact source." On the base
    Rust could not name Serrated Arrows' ability at all: the picker and the
    handler both asked the label, which said `triggered_`."""
    game, arrows, bears = _arrows_board()
    assert game.queue_permanent_ability(
        0, "Serrated Arrows", target_player_index=1, target_permanent_index=0
    ).supported
    toughness = bears.effective_toughness
    rust = game.queue_from_hand(1, "Rust", target_stack_index=0)
    assert rust.supported, rust.details
    resolve_stack(game)

    assert bears.effective_toughness == toughness, f"the ability was countered: {game.log}"
    assert int(arrows.metadata.get("arrowhead_counters", 0)) == 2, "its cost was still paid"


def test_bind_counters_a_spike_s_activated_ability():
    """Spike Feeder's "{2}, Remove a +1/+1 counter from this creature: Put a
    +1/+1 counter on target creature." — the same label, a creature source,
    and "Counter target activated ability" with no source narrowing."""
    feeder = _ready(Permanent(card=CATALOG["Spike Feeder"]))
    # Its printed 0/0 needs the counters it enters with before the first
    # state check (CR 704.5f), which the table makes as it is set up.
    add_plus1_counters(feeder, 2)
    p1 = PlayerState(name="P1", battlefield=[feeder], library=[CATALOG["Island"]] * 5, life=20)
    p2 = PlayerState(name="P2", hand=[CATALOG["Bind"]], library=[CATALOG["Island"]] * 5, life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    queued = game.queue_permanent_ability(
        0, "Spike Feeder", target_player_index=0, target_permanent_index=0
    )
    assert queued.supported, queued.details
    assert game.stack[-1].ability_effect_kind == "triggered_counter"
    bind = game.queue_from_hand(1, "Bind", target_stack_index=0)
    assert bind.supported, bind.details
    resolve_stack(game)
    assert any("Bind" in line and "counter" in line.lower() for line in game.log), game.log
    assert not any("Spike Feeder ability resolved" in line for line in game.log), game.log


def test_an_upkeep_trigger_reaches_the_client_as_a_triggered_ability(monkeypatch):
    """Icy Prison's "At the beginning of your upkeep, sacrifice this
    enchantment unless any player pays {3}." is labelled `upkeep_effect`, which
    has no `triggered_` prefix; it is a triggered ability on the stack. Read as
    it is pushed, because the upkeep resolves it before returning."""
    from engine.mixins.target_announcements import TargetAnnouncementsMixin

    pushed = []
    original = TargetAnnouncementsMixin._stack_push_object

    def spy(self, item, *, announce=True):
        if item.ability_instruction is not None:
            pushed.append((item, _serialize_stack_item(item, self)["is_triggered"]))
        return original(self, item, announce=announce)

    monkeypatch.setattr(TargetAnnouncementsMixin, "_stack_push_object", spy)
    prison = Permanent(card=CATALOG["Icy Prison"])
    game = Game(players=[PlayerState(name="P1", battlefield=[prison]), PlayerState(name="P2")])
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    resolve_stack(game)

    prisons = [(item, wire) for item, wire in pushed if item.card.name == "Icy Prison"]
    assert prisons, game.log
    item, wire = prisons[0]
    assert item.ability_effect_kind == "upkeep_effect", "the label this guards against"
    assert not item.activated
    assert wire is True
