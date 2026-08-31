"""Regression: a chosen target survives the battlefield renumbering under it.

`player.battlefield` is a list, so a permanent leaving shifts every later slot
down by one. Anything holding an index across that shift addresses a *different*
permanent — and a spell on the stack is exactly that: it waits for priority, for
responses, and for everything above it to resolve, any of which can remove a
permanent.

The engine's answer is `Permanent.permanent_id`, stamped at `Game._stack_push`
when the target is chosen (CR 601.2c) and read back through
`Game.chosen_permanent`. These tests drive the renumbering deliberately and
assert the *right* permanent is hit.

They are written to fail on the old code: each has a distractor permanent in a
lower slot that dies while the spell is on the stack, so the index the caster
chose now names its neighbour. An index-only engine hits the neighbour and
reports success, which is the silent-wrongness this repo's first standing
invariant forbids — not a crash, not an error, just the wrong creature dying.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from tests.helpers import CARDS_BY_NAME as CARDS, _game


def _put(game: Game, seat: int, name: str) -> Permanent:
    """Put a permanent onto the battlefield through the engine, so it is
    stamped with an id the way a real entry would be."""
    permanent = Permanent(card=CARDS[name])
    game._put_permanent_onto_battlefield(seat, permanent, seat)
    return permanent


def _kill(game: Game, permanent: Permanent) -> None:
    """Remove *permanent* the way a game does — lethal damage, then CR 704.5g.

    Not ``_permanent_to_graveyard``: that records the arrival in the graveyard
    and leaves the battlefield list to its caller, so using it here would leave
    the slots un-renumbered and the test would pass without ever exercising the
    thing it is about.
    """
    permanent.damage_marked = 99
    game.check_state_based_actions()


def test_damage_hits_the_creature_it_targeted_after_an_earlier_one_dies():
    """Lightning Bolt at slot 1; slot 0 dies first, so slot 1 becomes slot 0.

    Craw Wurm (6/4) rather than a 3-toughness creature on purpose: the bolt has
    to leave its damage *marked* and visible. A creature the bolt kills would
    make the assertion unreadable — a dead target proves nothing about which
    target was chosen.
    """
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    doomed = _put(game, 1, "Grizzly Bears")
    intended = _put(game, 1, "Craw Wurm")
    assert game.battlefield_index_of(intended) == 1

    game.players[0].hand.append(CARDS["Lightning Bolt"])
    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=1)

    # The distractor leaves while the spell is on the stack; Hill Giant slides
    # into slot 0, so the recorded index now names the wrong creature.
    _kill(game, doomed)
    assert game.battlefield_index_of(intended) == 0

    game.resolve_stack()

    assert intended.damage_marked == 3, (
        "the bolt did not hit the creature it targeted — it followed the index "
        "into the slot vacated by the creature that died"
    )


def test_an_aura_attaches_to_the_creature_it_targeted():
    """The longest gap in the engine between choosing a target and using it."""
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    doomed = _put(game, 1, "Grizzly Bears")
    intended = _put(game, 1, "Hill Giant")

    game.players[0].hand.append(CARDS["Weakness"])
    game.queue_from_hand(0, "Weakness", target_player_index=1, target_permanent_index=1)

    _kill(game, doomed)
    game.resolve_stack()

    aura = next(
        perm for perm in game.all_permanents() if perm.card.name == "Weakness"
    )
    attached = aura.metadata.get("attached_to")
    assert attached is intended, (
        f"Weakness attached to {getattr(attached, 'card', None)} rather than the "
        "creature it targeted — the Aura followed a stale index"
    )


def test_an_etb_trigger_phases_out_the_creature_it_targeted(set_pool):
    """The gap the id was threaded through last: a permanent's own "when this
    enters the battlefield" trigger.

    ``_apply_self_enters_battlefield_triggers`` built its execution context from
    the cast-time index alone and dropped the id, so every targeting ETB trigger
    in the pool resolved by slot. Oubliette is the shipped one, and its window is
    as wide as any spell's — the enchantment sits on the stack through a whole
    priority round before its trigger picks a creature up.
    """
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    doomed = _put(game, 1, "Grizzly Bears")
    intended = _put(game, 1, "Hill Giant")
    bystander = _put(game, 1, "Craw Wurm")
    assert game.battlefield_index_of(intended) == 1

    # Oubliette is Arabian Nights, so it comes from the set factory rather than
    # from this module's LEA pool.
    game.players[0].hand.append(set_pool("ARN")["Oubliette"])
    game.queue_from_hand(0, "Oubliette", target_player_index=1, target_permanent_index=1)

    # The distractor dies while Oubliette waits on the stack, so slot 1 now
    # names the bystander rather than the creature the caster chose.
    _kill(game, doomed)
    assert game.battlefield_index_of(bystander) == 1

    game.resolve_stack()

    oubliette = next(p for p in game.all_permanents() if p.card.name == "Oubliette")
    phased = oubliette.metadata.get("phased_out_permanent")
    assert phased is intended, (
        f"Oubliette phased out {getattr(phased, 'card', None)} rather than the "
        "creature its trigger targeted — the trigger followed a stale index"
    )
    assert game.is_on_battlefield(bystander), "the wrong creature was taken"


def test_several_targets_keep_their_own_slots_across_a_renumbering(set_pool):
    """The multi-target version, and the case where the single-target rule is
    actively wrong.

    ``resolve_target_permanent`` falls back to scanning the battlefield when a
    chosen target no longer resolves — right for one target, because hitting
    something beats fizzling. Per slot it would be a disaster: two slots that
    both decayed would both find the *same* first creature and double an effect
    the player chose once. So the plural resolver never scans, and a slot that
    stopped answering is dropped (CR 608.2b).
    """
    from engine.game_types import OracleExecutionContext
    from engine.handlers._common import resolve_target_permanents

    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    doomed = _put(game, 0, "Grizzly Bears")
    kept = _put(game, 0, "Hill Giant")
    bystander = _put(game, 0, "Craw Wurm")
    chosen_ids = [doomed.permanent_id, kept.permanent_id]
    chosen_indices = [0, 1]

    _kill(game, doomed)
    assert game.battlefield_index_of(kept) == 0, "the slots renumbered under the choice"

    context = OracleExecutionContext(
        caster=game.players[0],
        target=game.players[0],
        card=CARDS["Grizzly Bears"],
        target_permanent_index=chosen_indices,
        target_permanent_id=chosen_ids,
    )
    found = resolve_target_permanents(game, context)

    assert found == [kept], (
        "the surviving target must be the one it named and the dead one must "
        f"simply drop — got {[p.card.name for p in found]}"
    )
    assert bystander not in found, "no slot scanned its way onto a creature nobody chose"


def test_the_id_is_what_makes_it_work_not_the_index():
    """Pin the mechanism, so a future change that drops the id but happens to
    keep these passing (because the index still lines up) is still caught."""
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    first = _put(game, 1, "Grizzly Bears")
    second = _put(game, 1, "Hill Giant")

    assert first.permanent_id != second.permanent_id
    assert game.permanent_by_id(second.permanent_id) is second

    _kill(game, first)

    # `second` has slid into slot 0, so index 1 is empty: the index the caster
    # chose has no answer at all now, while the id still names `second`.
    assert game.permanent_by_id(second.permanent_id) is second
    assert game.chosen_permanent(1, 1, second.permanent_id) is second
    assert game.chosen_permanent(1, 1, None) is None, (
        "slot 1 is empty now — the index alone has no answer, which is the "
        "whole reason the id is recorded"
    )


# --- LeadB: an index is not a target ---
#
# The five handler tails that reached a permanent through
# ``Game._tap_or_untap_target`` / ``_bounce_target_creature`` /
# ``_apply_color_override``. Those helpers called ``pick_target_permanent``
# *without* its ``game``/``permanent_id`` keywords, so they got the index-only
# half of the resolver whose whole point is the id — and an index names
# whichever permanent slid into the vacated slot once anything has left
# (CR 400.7).
#
# Every probe below drives an **activated** ability, because
# ``legality.illegal_targets_refusal`` (CR 608.2b) is instants and sorceries
# only: it returns None for every ability, so the fizzle has to happen at the
# resolver or not at all. The Ice Age Talisman cycle reaches one of these tails
# off a *trigger* and is the live case — it is tested on the card, in
# ``tests/sets/test_ice_artifacts.py``.

_LEADB_PROBES = {
    "bounce_target_creature": "{T}: Return target creature to its owner's hand.",
    "return_spell_or_creature_to_hand":
        "{T}: Return target spell or creature to its owner's hand.",
    "recolor_target_from_text": "{T}: Target permanent becomes blue.",
    "tap_target_permanent": "{T}: Tap target permanent.",
    "untap_target_permanent": "{T}: Untap target permanent.",
}


def _leadb_ability(oracle_text):
    """An invented artifact's activated ability, compiled.

    Inventing the card is the point: no *printed* card reaches four of these
    five tails from an ability, so a regression written only against the pool
    would assert nothing about the four. The grammar reads these lines on any
    card, which is what makes the hole reachable the moment such a card is
    printed — and one already is (the Talismans).
    """
    from engine.oracle import compile_card_oracle
    from tests.helpers import _mk_card

    card = _mk_card("LeadB Probe", "{2}", "Artifact", oracle_text)
    program = compile_card_oracle(card)
    assert program.supported, oracle_text
    return card, program.activated_abilities[0].instruction


def _leadb_run(kind, *, depart):
    """Resolve *kind*'s tail against a target that has (or has not) departed.

    Returns ``(game, decoy, intended)``. The decoy sits in the slot the chosen
    permanent vacates, so an index-only resolver hits it and an id-aware one
    finds nothing.
    """
    from engine.game_types import OracleExecutionContext
    from engine.handlers import EFFECT_HANDLERS

    card, instruction = _leadb_ability(_LEADB_PROBES[kind])
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    source = _put(game, 0, "Black Lotus")
    intended = _put(game, 1, "Grizzly Bears")   # slot 0 — the chosen target
    decoy = _put(game, 1, "Hill Giant")         # slot 1 — slides into slot 0
    # The untap probe needs something to undo, so both start tapped there.
    if kind == "untap_target_permanent":
        intended.tapped = decoy.tapped = True

    chosen_index = game.battlefield_index_of(intended)
    chosen_id = intended.permanent_id
    if depart:
        _kill(game, intended)
        assert game.battlefield_index_of(decoy) == chosen_index, (
            "the decoy must inherit the chosen slot, or the test proves nothing"
        )

    EFFECT_HANDLERS[instruction.kind](
        game, instruction,
        OracleExecutionContext(
            caster=game.players[0], target=game.players[1], card=card,
            target_permanent_index=chosen_index, target_permanent_id=chosen_id,
            source_permanent=source,
        ),
    )
    return game, decoy, intended


def _leadb_untouched(kind, game, perm):
    """Whether *perm* was left alone by *kind*'s effect."""
    if kind in ("bounce_target_creature", "return_spell_or_creature_to_hand"):
        # Its own card, not an empty hand: in the present-target direction the
        # *intended* creature is legitimately in that hand.
        return game.is_on_battlefield(perm) and not any(
            card is perm.card for card in game.players[1].hand
        )
    if kind == "recolor_target_from_text":
        return "color_override" not in perm.metadata
    if kind == "tap_target_permanent":
        return not perm.tapped
    return perm.tapped  # untap: still tapped means it was not untapped


def _leadb_affected(kind, game, perm):
    """Whether *perm* was the one the effect acted on."""
    if kind in ("bounce_target_creature", "return_spell_or_creature_to_hand"):
        return (not game.is_on_battlefield(perm)) and any(
            card is perm.card for card in game.players[1].hand
        )
    if kind == "recolor_target_from_text":
        return perm.metadata.get("color_override") == "U"
    if kind == "tap_target_permanent":
        return perm.tapped
    return not perm.tapped


@pytest.mark.parametrize("kind", sorted(_LEADB_PROBES))
def test_a_departed_target_does_not_slide_onto_its_neighbour(kind):
    """The regression. Each of the five tails, against a target that has left.

    Fails on b31acb69: the index the ability recorded now names the decoy, so
    the effect lands on a permanent nobody chose and the log says it resolved.
    """
    game, decoy, intended = _leadb_run(kind, depart=True)

    assert not game.is_on_battlefield(intended), "the chosen target really left"
    assert _leadb_untouched(kind, game, decoy), (
        f"{kind} acted on the permanent that inherited the chosen slot. The "
        "target had left the battlefield, so there is no permanent the choice "
        "can still mean (CR 400.7) and the effect must do nothing (CR 608.2b)"
    )


@pytest.mark.parametrize("kind", sorted(_LEADB_PROBES))
def test_a_present_target_is_still_affected(kind):
    """The other direction, so the fix is a fizzle and not a lobotomy.

    Without this, "resolve nothing, ever" would pass the test above.
    """
    game, decoy, intended = _leadb_run(kind, depart=False)

    assert _leadb_affected(kind, game, intended), (
        f"{kind} must still affect the permanent it named"
    )
    assert _leadb_untouched(kind, game, decoy), (
        f"{kind} affected a bystander as well as its target"
    )


def test_the_helpers_no_longer_take_a_slot_at_all():
    """Pin the mechanism, not just the outcome.

    The three helpers resolved their own target from ``(player, index)``. The
    fix is that they no longer resolve anything — they take the ``Permanent``
    the caller resolved by id — so there is no index to go stale and no
    ``permanent_id`` keyword a future caller can forget. Threading the id in
    instead would have left that second failure mode armed, which is how the
    original hole opened: ``pick_target_permanent`` grew the keywords and these
    three callers silently kept the old behaviour with nothing failing.
    """
    import inspect

    from engine.mixins.effects import EffectsMixin

    for name in (
        "_tap_or_untap_target", "_bounce_target_creature", "_apply_color_override",
    ):
        parameters = inspect.signature(getattr(EffectsMixin, name)).parameters
        assert "target_permanent_index" not in parameters, (
            f"{name} takes a slot again — an index is not a target (CR 400.7)"
        )
        assert "permanent" in parameters, (
            f"{name} must take the Permanent its caller resolved"
        )
# --- end LeadB ---
