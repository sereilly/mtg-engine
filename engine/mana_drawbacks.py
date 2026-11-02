"""What tapping a mana source costs its controller beyond the tap.

A payment plan chooses which sources pay a cost (``mana_payment._sparing_choice``)
by what the payer still wants to pay for (``mana_wants``). Some sources charge
for the mana as well, and the planners were blind to it: kg2's preference kept
an Island by tapping Timberline Ridge, and with nothing else wanted the order
the sources were listed in decided whether a {1} was paid with a Swamp or with
a City of Brass's point of damage. This module is the **price**: a number per
source and per symbol asked of it, read off what the engine will actually run,
which the sparing choice consults after the wants — so a drawback-free source
of the right colour beats one that hurts, and a source that hurts is still
spent where it keeps a card in hand castable.

**What is priced, and how much.** One point per point of life the tap costs
its controller, one per untap step the source will miss (or the land drop a
return to the hand spends), one per harmful counter, and
:data:`SOURCE_LOST` for a source the tap gives away or destroys — more than any
board's worth of the others, because a land lost is every later turn's mana.
Each is read from the compiled program the tap runs, never a name list:

* **the mana ability run for that symbol** (``Game.land_mana_ability_for``, the
  tap seam's own choice; a non-land source's planned ability): "This land deals
  1 damage to you" (the painlands, Ancient Tomb, Grand Coliseum, Tarnished
  Citadel, the Odyssey threshold lands, Elves of Deep Shadow); "This land
  doesn't untap during your next untap step" (Cinder Marsh and the Tempest
  lands); "Put a depletion counter on this land" where the land's own text
  keeps it tapped while it has one (Timberline Ridge and the Ice Age depletion
  lands); "return this land to its owner's hand" in the next untap step
  (Undiscovered Paradise); a delayed trigger giving the land away (Rainbow
  Vale);
* **every trigger a tap of it fires** — the engine's own collector
  (``events.collect``) over "becomes tapped" (City of Brass, and an Aura on the
  source: Psychic Venom, Blight, Kudzu, Steam Vines, Insolence, Seizures,
  Spirit Shackle — the source itself where its counter is lethal — Orcish
  Mine, and Relic Bind, whose damage another seat aims and is priced as aimed
  at the tapper), and for a land the tap seam's own reading of "whenever a
  player taps a land for mana" (Manabarbs, Overabundance, Price of Glory's
  intervening "if", Storm Cauldron's return to the hand);
* **its standing text about being tapped**: "doesn't untap during your untap
  step" (Mana Vault, the Monoliths, Forsaken City), and a trigger that hurts
  while it is tapped (Mana Vault's draw step);
* **a counter a tap trigger puts on it that the board keeps tapped**:
  Freyalise's Winds' "put a wind counter on it" beside its "would untap …
  remove all wind counters from it instead", Temporal Distortion's hourglass
  counter beside "each permanent with an hourglass counter on it doesn't
  untap" — one missed untap, asked of the untap step's own readers with the
  counter supposed (:func:`_counter_keeps_it_tapped`), and not added where
  the tap already costs that untap.

A step this does not recognise prices nothing: an unrecognised step is not
read as a drawback, so the planners pay exactly as they did wherever nothing
here speaks. ``tests/ai/test_kg3_payment_drawback_census.py`` holds the
derived price to what the tap really costs, over every plannable source in
the pool, by tapping it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent

#: What a source given away or destroyed by its own tap is priced at: more
#: than any tap a board's other sources could charge together.
SOURCE_LOST = 10

#: The events a tap announces about the permanent tapped
#: (``Game.become_tapped``).
_BECOMES_TAPPED_EVENTS = ("permanent_becomes_tapped", "permanent_tapped_or_ability_activated")

#: Where a damage step's recipient is the tapping player: the trigger's own
#: controller for "you" (``caster``), and the tapped object's controller by
#: any of the event's spellings.
_THE_TAPPER = ("event_subject_controller", "event_subject_player", "attached_permanent_controller", "that_player")

#: Steps that take the tapped source away from its controller.
_LOSES_THE_SOURCE = ("give_control_of_source_to_player", "sacrifice_self", "destroy_self")


def tap_prices(
    game: "Game", permanent: "Permanent", symbols, *, ability_index: "int | None" = None,
    watched: "bool | None" = None,
) -> "dict[str, int]":
    """``{symbol: price}`` for tapping *permanent* asked for each of *symbols*
    — see the module's note. *ability_index* is the mana ability a non-land
    source's tap runs (an index into ``Game.usable_abilities_of``); a land's
    is the tap seam's choice for each symbol. *watched* is
    :func:`tap_watchers`' answer where a caller pricing a whole board has
    already asked it."""
    seat = game.controller_index_of(permanent)
    if seat is None:
        return {symbol: 0 for symbol in symbols}
    if watched is None:
        watched = tap_watchers(game)
    standing, counters = _standing_price(game, permanent, seat, watched)
    kept = any(_counter_keeps_it_tapped(game, permanent, seat, counter) for counter in counters)
    found: dict[str, int] = {}
    for symbol in symbols:
        instruction = _ability_run(game, permanent, symbol, ability_index)
        harm = _ability_harm(game, permanent, instruction)
        if kept and not _misses_its_untap_anyway(permanent, instruction):
            # One missed untap, whatever number of reasons it has: a
            # depletion land under the Winds stays tapped once.
            harm += 1
        found[symbol] = standing + harm
    return found


def land_price_profile(game: "Game", land: "Permanent") -> "tuple[int, tuple]":
    """*land*'s price as the effect payer taps it (``Game._pay_planned_cost``):
    ``(price paying generic, ((pip, extra), …))`` — the generic part asks the
    land for what ``_planned_tap_color`` asks with nothing wanted (its default
    ability's symbol), and each pip what it asks for that pip. The shape
    ``mana_payment.plan_payment``'s *prices* takes."""
    offered = [str(symbol).upper() for symbol in game._land_payment_colors(land)]
    generic_symbol = game._planned_tap_color(land, None)
    asked = {pip: game._planned_tap_color(land, pip) for pip in ("W", "U", "B", "R", "G", "C")}
    prices = tap_prices(game, land, {generic_symbol, *offered, *asked.values()})
    generic = prices.get(generic_symbol, 0)
    return generic, tuple(
        (pip, prices.get(symbol, generic) - generic)
        for pip, symbol in asked.items()
        if prices.get(symbol, generic) != generic
    )


def _ability_run(game, permanent, symbol, ability_index):
    """The instruction a tap asked for *symbol* runs."""
    usable = game.usable_abilities_of(permanent)
    if ability_index is not None:
        return usable[ability_index].instruction if 0 <= ability_index < len(usable) else None
    if not permanent.has_type("land"):
        return None
    index = game.land_mana_ability_for(permanent, symbol)
    if index is not None and 0 <= index < len(usable):
        return usable[index].instruction
    free, _priced = game._land_mana_abilities(permanent)
    return free


def _misses_its_untap_anyway(permanent, instruction) -> bool:
    """Whether *permanent* misses its next untap after the tap without any
    counter put on it: its own "doesn't untap" text, or a step of the mana
    ability run that keeps it tapped (``_ability_harm``'s untap rows)."""
    card = permanent.effective_card
    if _untap_text(card.name, card.oracle_text or "")[0]:
        return True
    if instruction is None:
        return False
    from .mana_payment import _every_nested_step

    untap_counters = _untap_blocking_counters(permanent)
    for step in (instruction, *_every_nested_step(instruction)):
        payload = step.payload or {}
        if (
            (step.kind == "skip_next_untap" and payload.get("subject") == "source")
            or (step.kind == "add_named_counter_to_self"
                and str(payload.get("counter")) in untap_counters)
            or step.kind == "return_self_instead_of_untapping"
        ):
            return True
    return False


def _counter_keeps_it_tapped(game, permanent, seat: int, counter: str) -> bool:
    """Whether *permanent*, with a *counter* counter on it, would stay tapped
    through its controller's next untap step — asked of the untap step's own
    readers, with the counter supposed rather than placed:

    * its own text ("…doesn't untap … if it has a depletion counter on it",
      :func:`_untap_blocking_counters`);
    * a "would untap" replacement removing that counter instead (Freyalise's
      Winds: ``replacements.permanents``' reader of the board's counter words);
    * a board restriction on permanents carrying it ("Each permanent with an
      hourglass counter on it doesn't untap …", Temporal Distortion: the
      untap step's ``_untap_constraints``, its noun phrase asked through
      ``subject_matches`` without the counter clause the supposition meets).
    """
    if not counter:
        return False
    if counter in _untap_blocking_counters(permanent):
        return True
    from .replacements.permanents import _untap_counter_kinds
    from .subject_filters import subject_matches

    if counter in _untap_counter_kinds(game):
        return True
    for described, source_seat, source in game._untap_constraints(seat)["blocked"]:
        if str(described.get("with_named_counter") or "") != counter:
            continue
        rest = {key: value for key, value in described.items() if key != "with_named_counter"}
        if subject_matches(game, permanent, rest, observer=source_seat, source=source):
            return True
    return False


def _ability_harm(game, permanent, instruction) -> int:
    """What running the mana ability *instruction* costs beyond its mana."""
    if instruction is None:
        return 0
    from .mana_payment import _every_nested_step

    harm = 0
    untap_counters = _untap_blocking_counters(permanent)
    for step in (instruction, *_every_nested_step(instruction)):
        payload = step.payload or {}
        if step.kind == "deal_damage" and payload.get("recipient") == "caster":
            harm += _amount(payload)
        elif step.kind == "skip_next_untap" and payload.get("subject") == "source":
            harm += 1
        elif step.kind == "add_named_counter_to_self" and str(payload.get("counter")) in untap_counters:
            harm += 1
        elif step.kind == "return_self_instead_of_untapping":
            harm += 1
        elif step.kind in _LOSES_THE_SOURCE:
            harm += SOURCE_LOST
    return harm


def tap_watchers(game: "Game") -> bool:
    """Whether any permanent on the battlefield has an ability that triggers
    on a permanent being tapped — the one board scan a whole board's prices
    need before any trigger is collected for one source."""
    from .trigger_utils import iter_triggered_abilities

    kinds = {*_BECOMES_TAPPED_EVENTS, "land_tapped_for_mana"}
    return next(
        iter(iter_triggered_abilities(game, condition_kinds=kinds, first_match_only=True)),
        None,
    ) is not None


def _standing_price(game, permanent, seat: int, watched: bool = True) -> "tuple[int, tuple]":
    """What any tap of *permanent* costs — the triggers a tap fires, and its
    own text about staying tapped — and the counters those triggers put on
    it (``tap_prices`` asks whether the board then keeps it tapped)."""
    from .events import Event, collect

    harm = _stays_tapped_harm(game, permanent, seat)
    counters: list = []
    if not watched:
        return harm, ()
    for kind in _BECOMES_TAPPED_EVENTS:
        for fired in collect(game, Event(
            kind=kind, subject=permanent,
            payload={"event_subject_controller": seat,
                     "event_subject_permanent_id": permanent.permanent_id},
        )):
            harm += _trigger_harm(
                game, fired["instruction"], fired["controller_index"], seat,
                fired["source_permanent"], permanent,
            )
            counters.extend(_counters_put_on_it(fired["instruction"]))
    if permanent.has_type("land"):
        harm += _land_tap_trigger_harm(game, permanent, seat)
    return harm, tuple(counters)


def _counters_put_on_it(instruction) -> list:
    """The counter words a tap trigger puts on the permanent tapped — "put a
    wind counter on **it**" (Freyalise's Winds), the event's own subject."""
    from .mana_payment import _every_nested_step

    return [
        str((step.payload or {}).get("counter") or "")
        for step in (instruction, *_every_nested_step(instruction))
        if step.kind == "add_named_counter_to_target"
        and (step.payload or {}).get("on_event_subject")
    ]


def _land_tap_trigger_harm(game, land, seat: int) -> int:
    """"Whenever a player taps a land for mana …" — the seam's own reading of
    which fire for *seat* tapping *land*, intervening "if" included
    (``Game._land_tapped_for_mana``)."""
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition
    from .trigger_utils import iter_triggered_abilities

    harm = 0
    for _index, watcher, trig in iter_triggered_abilities(
        game, condition_kinds={"land_tapped_for_mana"}, first_match_only=False,
    ):
        if not game._land_tap_trigger_fires(trig, watcher, seat, land):
            continue
        gate = (trig.instruction.payload or {}).get("intervening_if")
        owner = game.controller_index_of(watcher)
        if owner is None:
            continue
        if gate is not None and not evaluate_condition(
            game,
            OracleExecutionContext(
                caster=game.players[owner], target=game.players[seat],
                card=watcher.card, source_permanent=watcher,
                trigger_context={"event_subject_player": seat},
            ),
            gate,
        ):
            continue
        harm += _trigger_harm(game, trig.instruction, owner, seat, watcher, land)
    return harm


def _trigger_harm(game, instruction, controller: int, tapper: int, source, tapped) -> int:
    """What a trigger fired by the tap costs the tapping player."""
    from .mana_payment import _every_nested_step

    harm = 0
    attached = getattr(source, "metadata", {}).get("attached_to") is tapped
    for step in (instruction, *_every_nested_step(instruction)):
        payload = step.payload or {}
        if step.kind == "deal_damage":
            recipient = payload.get("recipient")
            hit = controller if recipient == "caster" else (
                tapper if recipient in _THE_TAPPER else None
            )
            if hit is None and payload.get("targets") and controller != tapper:
                # Damage another seat's trigger aims where it chooses (Relic
                # Bind's "target player"): priced as aimed at the tapper.
                hit = tapper
            if hit == tapper:
                harm += _amount(payload)
        elif step.kind == "self_damage_unless_pay" and payload.get("payer") in _THE_TAPPER:
            harm += _amount(payload)
        elif step.kind == "destroy_event_subject" or (
            step.kind == "destroy_attached_permanent" and attached
        ) or (step.kind in _LOSES_THE_SOURCE and source is tapped):
            harm += SOURCE_LOST
        elif step.kind == "add_pt_counters_to_attached" and attached:
            # A -0/-N counter (Spirit Shackle) on the host: one point, or the
            # host itself where it is lethal (CR 704.5f).
            harm += SOURCE_LOST if _counter_is_lethal(tapped, payload) else 1
        elif step.kind == "return_tapped_land_to_hand":
            # The land back in the hand (Storm Cauldron): a land drop to play
            # it again, priced as a missed untap is.
            harm += 1
        elif step.kind == "remove_counter_from_self" and attached:
            # An Aura spending a counter each time its host is tapped (Orcish
            # Mine's ore, whose last destroys the land).
            harm += 1
    return harm


def _stays_tapped_harm(game, permanent, seat: int) -> int:
    """"Doesn't untap during your untap step" with no condition (the
    conditional ones are priced where the condition is set, above), and a
    trigger of its own that hurts while it is tapped (Mana Vault's draw
    step)."""
    card = permanent.effective_card
    harm = 1 if _untap_text(card.name, card.oracle_text or "")[0] else 0
    from .oracle import compile_card_oracle

    for trig in compile_card_oracle(card).triggered_abilities:
        instruction = getattr(trig, "instruction", None)
        gate = ((getattr(instruction, "payload", None) or {}).get("intervening_if")) or {}
        if gate.get("kind") == "is_state" and gate.get("state") == "tapped" and not gate.get("negated"):
            harm += _trigger_harm(game, instruction, seat, seat, permanent, permanent)
    return harm


def _counter_is_lethal(permanent, payload) -> bool:
    """Whether the -X/-Y counters *payload* puts on *permanent* leave it with
    toughness 0 or less."""
    import re

    match = re.fullmatch(r"([+-]\d+)/([+-]\d+)", str(payload.get("counter", "")))
    if match is None or not getattr(permanent, "is_creature", False):
        return False
    toughness = permanent.effective_toughness if hasattr(permanent, "effective_toughness") else None
    if toughness is None:
        return False
    count = payload.get("count", 1)
    count = int(count) if isinstance(count, int) and not isinstance(count, bool) else 1
    return int(toughness) + int(match.group(2)) * count <= 0


def _untap_blocking_counters(permanent) -> "frozenset[str]":
    """The counters whose presence keeps *permanent* tapped in its untap step,
    by its own text ("…if it has a depletion counter on it")."""
    card = permanent.effective_card
    return _untap_text(card.name, card.oracle_text or "")[1]


@lru_cache(maxsize=4096)
def _untap_text(name: str, oracle_text: str) -> "tuple[bool, frozenset[str]]":
    """``(doesn't untap at all, counters that keep it tapped)`` — what a card's
    own text says about its untap step, read once per text: the untap step's
    own whole-line readers (``untap_restrictions``)."""
    from .untap_restrictions import self_untap_counter_condition, self_untap_line

    blocked = False
    counters: set[str] = set()
    for line in oracle_text.splitlines():
        if self_untap_line(line, name) == "doesnt_untap":
            blocked = True
        counter = self_untap_counter_condition(line, name)
        if counter is not None:
            counters.add(counter)
    return blocked, frozenset(counters)


def _amount(payload) -> int:
    amount = payload.get("amount", 0)
    return int(amount) if isinstance(amount, int) and not isinstance(amount, bool) else 0


__all__ = ["SOURCE_LOST", "land_price_profile", "tap_prices", "tap_watchers"]
