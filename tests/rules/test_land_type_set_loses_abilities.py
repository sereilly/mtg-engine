"""CR 305.7, measured over the pool: a land whose subtype an effect *set* to a
basic land type is that type's land and nothing else.

    305.7  If an effect sets a land's subtype to one or more of the basic land
           types, the land no longer has its old land type. It loses all
           abilities generated from its rules text, its old land types, and
           any copiable effects affecting that land, and it gains the
           appropriate mana ability for each new basic land type. Note that
           this doesn't remove any abilities that were granted to the land by
           other effects. … If a land gains one or more land types in addition
           to its own, it keeps its land types and rules text, and it gains
           the new land types and mana abilities.

The rule was implemented one reader at a time, and each reader was a place it
could be forgotten: layer 6 took the keywords, the activation door refused the
activated abilities, the trigger scan skipped the triggered ones, the land tap
seam and two mana readers were taught later — and every *static* ability a
land prints was never asked at all, so The Tabernacle at Pendrell Vale under
Blood Moon was a Mountain that still taxed every creature on the table.

Three sweeps, all driven through the engine's own doors.

**The cross** (``test_305_7_every_setter_against_every_nonbasic_land``): every
type-setting effect the pool prints against every nonbasic land. After the
effect applies, the land's own text reads as no ability, nothing is listed or
activatable, it taps for exactly the mana of its new type, and emptying the
land's text box changes nothing about any other permanent — no static of it
was reaching the board. Then the effect ends, and everything is back. A pair
the effect does not reach (Conversion beside a land that is not a Mountain),
and the one effect that *adds* a type (Blanket of Night), are the control arm:
the land keeps every word.

**The twin** (``test_305_7_a_set_land_plays_like_a_land_with_no_text``): the
rule stated as behaviour. Two tables, identical until the type is set; on the
second the land's card is then swapped for the same card with an empty text
box. Three half-turns are played on each — untap, upkeep, draw, a land drop,
the land tapped for mana, an attack with everything, the end step, cleanup,
the opponent's turn, and a last turn in which the land's controller is left
with no creature — and the two tables must come out the same, card for card,
counter for counter and log line for log line. A printed ability that still
*does* anything is a difference, and the test names the land. This is the
sweep that sees a trigger and a static, and — with the static on the table
first — a land's entry: CR 614.12, how it enters, and CR 603.6a, what
triggers as it does.

**The grant** (``test_305_7_keeps_what_another_effect_granted``): every way
the pool grants a land an ability — a quoted ability from an Aura or a
board-wide static, a keyword, an until-end-of-turn grant — crossed with every
kind of setter, in both orders. The land has the grant and nothing of its own.

``_PRINTED_ABILITIES_FUNCTIONED`` names what the twin found on the tree before
this file, measured there with this file's own cases; on that tree the cross
names 3,581 of its 4,536 pairs.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.ai_combat import declare_ai_attackers
from engine.auras import aura_land_type_change
from engine.faces import compilation_units
from engine.handlers import EFFECT_HANDLERS
from engine.layer_bridge import (computed_abilities, computed_types,
                                 printed_shape, printed_supertypes)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

_BASIC_MANA = {
    "plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G",
}

#: The instruction kinds that *set* a land's basic land type when they
#: resolve. Held to the engine by ``test_305_7_the_setter_kinds_are_the_
#: handlers_that_write_a_land_type``: a handler that writes a land-type
#: contribution and is not listed here fails that test, so a setter the next
#: set prints cannot be left out of the cross by this list going stale.
_SETTING_KINDS = frozenset({
    "change_target_land_type",
    "add_mire_counter_to_target_land",
    "change_land_type_until",
    "swap_land_types_until_eot",
})

#: The static spelling ("Nonbasic lands are Mountains"), derived by
#: ``engine/land_types.py`` rather than resolved.
_STATIC_KIND = "static_land_type_change"


def _walk(instruction):
    """*instruction* and every instruction nested in its payload."""
    if instruction is None:
        return
    yield instruction
    stack = list((getattr(instruction, "payload", None) or {}).values())
    while stack:
        value = stack.pop()
        if hasattr(value, "kind") and hasattr(value, "payload"):
            yield from _walk(value)
        elif isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, (list, tuple)):
            stack.extend(value)


def _sets_a_land_type(instruction) -> bool:
    return any(step.kind in _SETTING_KINDS for step in _walk(instruction))


@dataclasses.dataclass(frozen=True)
class _Setter:
    """One way the pool sets a land's type, and how to drive it."""

    card: object
    #: "static" (Blood Moon), "aura" (Evil Presence), "ability" (Kavu
    #: Recluse) or "spell" (Jinx).
    shape: str
    #: "…in addition to its other land types" (Blanket of Night): CR 305.7's
    #: last sentence, the control arm.
    additive: bool = False
    ability_index: int | None = None
    mode_index: int | None = None
    #: How the effect ends, when this file can end it: "leaves" (the source
    #: leaves the battlefield), "cleanup" (until end of turn), "untap" (until
    #: the land's controller's next untap step), or None (it lasts
    #: indefinitely, or hangs on something this file does not drive).
    ends: str | None = None

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def label(self) -> str:
        if self.mode_index is not None:
            return f"{self.name} (mode {self.mode_index})"
        return self.name


def _ability_ending(instruction) -> str | None:
    for step in _walk(instruction):
        if step.kind == "change_target_land_type":
            # "…until this creature leaves the battlefield." (Gaea's Liege.)
            return "leaves"
        if step.kind == "swap_land_types_until_eot":
            return "cleanup"
        if step.kind == "change_land_type_until":
            duration = str(step.payload.get("duration") or "")
            if duration == "until_end_of_turn":
                return "cleanup"
            if duration == "until_controllers_next_untap_step":
                return "untap"
    return None


def _derive_setters(catalog) -> list[_Setter]:
    """Every type-setting effect in *catalog*, read off its compiled program."""
    found: list[_Setter] = []
    for card in compilation_units(catalog):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        card_types, _subtypes = printed_shape(card)
        for instruction in program.instructions:
            if instruction.kind == _STATIC_KIND:
                found.append(_Setter(
                    card, "static",
                    additive=bool(instruction.payload.get("additive")),
                    ends="leaves",
                ))
        text = card.oracle_text or ""
        if (
            aura_land_type_change(text) is not None
            or "enchanted land is the chosen type" in text.lower()
        ):
            found.append(_Setter(card, "aura", ends="leaves"))
        if card_types & {"instant", "sorcery"}:
            modes = tuple(getattr(program, "modes", ()) or ())
            if modes:
                for index, mode in enumerate(modes):
                    if _sets_a_land_type(mode.instruction):
                        found.append(_Setter(
                            card, "spell", mode_index=index,
                            ends=_ability_ending(mode.instruction),
                        ))
            elif any(_sets_a_land_type(step) for step in program.instructions):
                found.append(_Setter(
                    card, "spell",
                    ends=next(filter(None, (
                        _ability_ending(step) for step in program.instructions
                    )), None),
                ))
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if _sets_a_land_type(ability.instruction):
                found.append(_Setter(
                    card, "ability", ability_index=index,
                    ends=_ability_ending(ability.instruction),
                ))
    return sorted(found, key=lambda setter: setter.label)


def _nonbasic_lands(catalog) -> list:
    return sorted(
        (
            card for card in compilation_units(catalog)
            if "land" in printed_shape(card)[0]
            and "basic" not in printed_supertypes(card.type_line)
            and compile_card_oracle(card).supported
        ),
        key=lambda card: card.name,
    )


def _printed_lines(card) -> list[str]:
    """The lines of *card*'s text that are an ability rather than reminder
    text alone — what CR 305.7 takes away."""
    lines = []
    for line in (card.oracle_text or "").splitlines():
        stripped = line.strip()
        if not stripped or (stripped.startswith("(") and stripped.endswith(")")):
            continue
        lines.append(stripped)
    return lines


def _blank(card):
    """*card* with an empty text box: the same name, type line and supertypes,
    and no ability of its own."""
    return dataclasses.replace(card, oracle_text="", keywords=(), produced_mana=())


def _eats_a_land(card) -> bool:
    """Whether *card*'s text may take a land as it enters ("sacrifice it
    unless you return an untapped Plains…", "sacrifice two untapped lands
    instead") — so the table it is put on needs lands to give. Generous on
    purpose: a land that says either word anywhere gets them."""
    return bool(re.search(r"\b(?:sacrifice|return)\b", card.oracle_text or "", re.I))


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


class _Refused(Exception):
    """The engine declined to cast or activate a setter at this land: the
    pair cannot be arranged ("target **non-Swamp** land" at a Bayou)."""


def _answer(game) -> None:
    """Take every owed decision's default — the headless seat's answer."""
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_replacement_choices()


class _Board:
    """Seat 0 controls the land under test; seat 1 is the opponent.

    Each seat has a Grizzly Bears, and seat 0 a Sliver Queen besides — a
    legendary creature of all five colours, so a land that says something
    about "creatures", "creatures you control" or "<colour> legendary
    creatures you control" has a creature to say it about.
    """

    def __init__(self, cards, *, bare: bool = False, basics: bool = True) -> None:
        self.cards = cards
        self.game = Game(
            players=[
                PlayerState(name="A", life=200),
                PlayerState(name="B", life=200),
            ],
            prompt_driver=_answer,
        )
        game = self.game
        game.enforce_mana_costs = False
        game.active_player_index = 0
        for player in game.players:
            player.library = [cards["Forest"]] * 40
        game.players[0].hand = [cards["Forest"], cards["Forest"]]
        self.probes = []
        if not bare:
            self.probes = [
                self.enter("Grizzly Bears", 0),
                self.enter("Sliver Queen", 0),
                self.enter("Grizzly Bears", 1),
            ]
            # One basic of each type, for a land that eats one as it enters
            # ("sacrifice it unless you return an untapped Plains", "sacrifice
            # two untapped lands instead") — so it is still there to be set.
            if basics:
                for basic in ("Plains", "Island", "Swamp", "Mountain", "Forest"):
                    self.enter(basic, 0)
            self.settle()

    # -- putting things on the table -------------------------------------

    def enter(self, card, seat: int = 0) -> Permanent:
        if isinstance(card, str):
            card = self.cards[card]
        permanent = Permanent(card=card)
        self.game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        return permanent

    def settle(self, **answers) -> None:
        """Resolve the stack and answer what is owed, the land-type prompts
        with *answers* and everything else with its default."""
        game = self.game
        for _ in range(60):
            moved = False
            for choice in list(game.pending_choices):
                if choice.kind == "land_type_choice" and "land_type" in answers:
                    assert game.confirm_land_type(
                        choice.player_index, answers["land_type"]
                    )
                elif choice.kind == "land_type_swap" and "swap" in answers:
                    assert game.confirm_land_type_swap(
                        choice.player_index, *answers["swap"]
                    )
                else:
                    game.auto_resolve_pending_choices(
                        choice.player_index, kinds=[choice.kind]
                    )
                moved = True
            game.auto_resolve_pending_replacement_choices()
            if game.stack:
                game.resolve_top_of_stack()
                moved = True
            if not moved:
                break
        game._recompute_continuous_effects()

    def on_battlefield(self, permanent) -> bool:
        return self.game.is_on_battlefield(permanent)

    # -- setting a land's type -------------------------------------------

    def new_type_for(self, land) -> str:
        """A basic land type *land* does not have, for a setter that asks."""
        have = set(land.basic_land_types) if land is not None else set()
        return next(word for word in _BASIC_MANA if word not in have)

    def apply(self, setter: _Setter, land) -> object:
        """Apply *setter* (to *land*, when it names one). Returns whatever
        ends the effect, for :meth:`end`."""
        game = self.game
        if setter.shape == "static":
            # Seat 0, so "Lands you control are Plains" (Celestial Dawn) is
            # about the land under test.
            source = self.enter(setter.card, 0)
            self.settle()
            return source
        interactive = set(game.interactive_seats)
        # Interactive for the length of the announcement, so a "choose a basic
        # land type" is this file's answer rather than the default.
        game.interactive_seats = {0, 1}
        try:
            if setter.shape == "aura":
                game.players[0].hand.append(setter.card)
                before = {id(perm) for perm in game.all_permanents()}
                result = game.cast_from_hand(
                    0, setter.name, target_permanent_ids=[land.permanent_id]
                )
                if not result.supported:
                    raise _Refused(result.details)
                self.settle(land_type=self.new_type_for(land))
                return next(
                    (perm for perm in game.all_permanents()
                     if id(perm) not in before and perm.card is setter.card),
                    None,
                )
            if setter.shape == "spell":
                game.players[1].hand.append(setter.card)
                swap = None
                kwargs = {}
                if setter.mode_index is not None:
                    kwargs["mode_index"] = setter.mode_index
                program = compile_card_oracle(setter.card)
                instruction = (
                    program.modes[setter.mode_index].instruction
                    if setter.mode_index is not None else None
                )
                swaps = instruction is not None and any(
                    step.kind == "swap_land_types_until_eot"
                    for step in _walk(instruction)
                )
                if swaps:
                    # "Each land of the first chosen type becomes the second
                    # chosen type": named by a land type the land has.
                    subtypes = sorted(computed_types(land)[1])
                    if not subtypes:
                        return None
                    swap = (subtypes[0], self.new_type_for(land))
                else:
                    kwargs["target_permanent_ids"] = [land.permanent_id]
                result = game.cast_from_hand(1, setter.name, **kwargs)
                if not result.supported:
                    raise _Refused(result.details)
                self.settle(land_type=self.new_type_for(land), swap=swap)
                return None
            # An activated ability, on the opponent's side: "target land an
            # opponent controls" (Kukemssa Serpent) is then the land under
            # test, and every other one targets any land.
            ability = usable_activated_abilities(
                compile_card_oracle(setter.card)
            )[setter.ability_index]
            # Before the source arrives: "When you control no Islands,
            # sacrifice this creature" (Kukemssa Serpent) is a state trigger.
            self._stock_costs(setter.card)
            source = self.enter(setter.card, 1)
            self.settle()
            kwargs = {}
            if "x" in str(
                ((ability.instruction.payload.get("targets") or {}).get("count"))
            ).lower():
                kwargs["x_value"] = 1
            phase, step, active = (
                game.current_turn_phase, game.current_step,
                game.active_player_index,
            )
            # "Activate only during your upkeep." (Cyclopean Tomb.)
            game.active_player_index = 1
            game.current_turn_phase, game.current_step = "beginning", "upkeep"
            try:
                result = game.activate_permanent_ability(
                    1, setter.name, ability_index=setter.ability_index,
                    target_permanent_ids=[land.permanent_id], **kwargs,
                )
            finally:
                game.current_turn_phase, game.current_step = phase, step
                game.active_player_index = active
            if not result.supported:
                raise _Refused(result.details)
            self.settle(land_type=self.new_type_for(land))
            return source
        finally:
            game.interactive_seats = interactive

    def _stock_costs(self, card) -> None:
        """Give the opponent what a setter's cost eats: an Island to
        sacrifice (and one to keep), a green creature to sacrifice, a card to
        discard."""
        text = (card.oracle_text or "").lower()
        if "sacrifice an island" in text:
            self.enter("Island", 1)
            self.enter("Island", 1)
        if "sacrifice a green creature" in text:
            self.enter("Llanowar Elves", 1)
        if "discard a card" in text:
            self.game.players[1].hand.append(self.cards["Forest"])

    def end(self, setter: _Setter, source, land) -> bool:
        """End *setter*'s effect the way its own duration says. Returns False
        when this file cannot (the effect lasts indefinitely)."""
        game = self.game
        if setter.ends == "leaves":
            if source is None or not game.is_on_battlefield(source):
                return False
            # Sacrificed: the engine's whole transition out (CR 701.21a), so
            # what the source's leaving ends is the engine's business — an
            # Aura is torn down, a creature's "until this leaves" is reverted,
            # a static simply stops being derived.
            game.sacrifice_permanent(source)
        elif setter.ends == "cleanup":
            game.resolve_cleanup_step(game.active_player_index)
        elif setter.ends == "untap":
            game.resolve_untap_step(0)
        else:
            return False
        self.settle()
        return True


def _facts(board: _Board, land) -> dict:
    """What *land* is and offers right now, read through the engine's own
    accessors."""
    game = board.game
    return {
        "text": land.effective_card.oracle_text,
        "usable": len(game.usable_abilities_of(land)),
        "mana": tuple(sorted(land.effective_produced_mana)),
        "subtypes": tuple(sorted(computed_types(land)[1])),
        "keywords": tuple(sorted(computed_abilities(land))),
    }


def _others(board: _Board, land) -> list:
    """Every permanent but *land*, as the rest of the table reads it: a
    static of the land's that reaches the board shows up here."""
    game = board.game
    return [
        _permanent_row(game.controller_index_of(probe), probe, with_text=True)
        for probe in board.probes
        if probe is not land and game.is_on_battlefield(probe)
    ]


def _permanent_row(seat: int, permanent, *, with_text: bool) -> tuple:
    card_types, subtypes = computed_types(permanent)
    counters = tuple(sorted(
        (key, value) for key, value in permanent.metadata.items()
        if "counter" in key and isinstance(value, (int, bool)) and value
    ))
    creature = permanent.is_creature
    return (
        seat, permanent.card.name, bool(permanent.tapped),
        permanent.effective_card.oracle_text if with_text else None,
        tuple(sorted(card_types)), tuple(sorted(subtypes)),
        tuple(sorted(computed_abilities(permanent))),
        (permanent.effective_power, permanent.effective_toughness)
        if creature else None,
        counters,
    )


def _digest(board: _Board, land) -> list:
    """The whole table. The land's own *text* is left out: that is the
    accessor's fact, asserted on its own in the cross, and leaving it out is
    what makes a difference here mean an ability **did** something."""
    game = board.game
    rows: list = []
    for seat, player in enumerate(game.players):
        rows.append((
            "player", seat, player.life,
            tuple(sorted(card.name for card in player.hand)),
            len(player.library),
            tuple(sorted(card.name for card in player.graveyard)),
            tuple(sorted(card.name for card in player.exile)),
        ))
    for seat, permanent in game.permanents_with_controller():
        rows.append(("permanent",) + _permanent_row(
            seat, permanent, with_text=permanent is not land
        ))
    rows.append(("stack", tuple(item.card.name for item in game.stack)))
    rows.append(("owed", tuple(choice.kind for choice in game.pending_choices)))
    return rows


# ---------------------------------------------------------------------------
# Three half-turns
# ---------------------------------------------------------------------------


def _drain(game) -> None:
    for _ in range(8):
        game._resolve_priority_window()
        _answer(game)
        if not game.stack:
            return


def _combat(game, seat: int) -> None:
    """One combat phase: *seat* attacks with every creature it has, nobody
    blocks. ``advance_combat_phase`` is the engine's walk; this supplies the
    declarations it stops for, as ``ai_combat.run_ai_combat_phase`` does."""
    for _ in range(40):
        if game.is_game_over():
            return
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        if game.current_turn_phase != "combat":
            return
        if (game.current_turn_phase, game.current_step) != before:
            continue
        step = game.current_step
        if step == "declare_attackers" and not game.combat_attackers_locked:
            attackers = [
                index
                for index, permanent in enumerate(game.players[seat].battlefield)
                if permanent.is_creature
            ]
            declare_ai_attackers(game, seat, attacker_indices=attackers)
            continue
        if step == "declare_blockers" and not game.combat_blockers_locked:
            pending = game._pending_block_declarer()
            if pending is None:
                game.combat_blockers_locked = True
                game._prune_combat_state()
                continue
            ok, _why = game.declare_blockers(
                pending, {}, acting_index=game.block_chooser_index(pending)
            )
            if not ok:
                return
            continue
        if step == "combat_damage" and not game.combat_damage_resolved:
            game.resolve_all_combat_damage(
                game.active_player_index,
                attacker_damage=game._build_auto_damage_assignment(),
            )
            continue
        return


def _rest_of_turn(game, seat: int) -> None:
    for _ in range(12):
        if game.is_game_over():
            return
        phase = game.current_turn_phase
        if phase == "ending":
            break
        if phase == "combat":
            return
        game._close_current_priority_step()
        _answer(game)
        entered = game.enter_next_turn_phase(phase)
        if entered is None:
            return
        if entered == "combat":
            _combat(game, seat)
            _answer(game)
    else:
        return
    _drain(game)
    game.close_end_step()
    game.resolve_cleanup_step(seat)
    _drain(game)


def _half_turn(
    board: _Board, seat: int, land, *, first: bool, lose_creatures: bool = False
) -> list:
    """One turn for *seat*, and what happened in it."""
    game = board.game
    seen: list = []
    game.turn += 1
    game.start_turn(seat)
    _drain(game)
    if seat == 0:
        if first:
            # A land drop: "When you play another land, sacrifice this land."
            played = game.cast_from_hand(0, "Forest")
            seen.append(("land drop", played.supported))
            _drain(game)
        if game.is_on_battlefield(land) and game.controls(0, land):
            symbol = next(iter(land.effective_produced_mana), "C")
            refusal = game.land_mana_tap_refusal(land)
            made = game.tap_land_for_mana(
                0, land.card.name, chosen_color=symbol,
                permanent_id=land.permanent_id,
            )
            pool = tuple(sorted(
                (key, value)
                for key, value in game.players[0].mana_pool.items() if value
            ))
            seen.append(("tapped for mana", refusal, bool(made), pool))
            _drain(game)
    _combat(game, seat)
    _answer(game)
    if lose_creatures:
        # "At the beginning of your end step, if you control no creatures,
        # sacrifice this land."
        for creature in [p for p in game.controlled_by(seat) if p.is_creature]:
            game.sacrifice_permanent(creature)
        _drain(game)
    _rest_of_turn(game, seat)
    seen.append(_digest(board, land))
    return seen


def _play(board: _Board, land) -> list:
    """Three half-turns: the land's controller's, the opponent's, and the
    controller's again — in which its creatures (having attacked last turn
    and this one) are gone before the end step."""
    game = board.game
    game.interactive_seats = set()
    game.log.clear()
    seen: list = [_digest(board, land)]
    try:
        seen.append(_half_turn(board, 0, land, first=True))
        seen.append(_half_turn(board, 1, land, first=False))
        seen.append(_half_turn(board, 0, land, first=False, lose_creatures=True))
    except Exception as exc:  # an arm that cannot be played is a result too
        seen.append(("raised", type(exc).__name__, str(exc)[:200]))
    seen.append(("log", tuple(game.log)))
    return seen


def _first_difference(real: list, twin: list) -> str:
    """Where two played tables part, as something a person can read."""
    def flat(value, path=""):
        if isinstance(value, (list, tuple)) and value and isinstance(
            value[0], (list, tuple)
        ):
            for index, item in enumerate(value):
                yield from flat(item, f"{path}/{index}")
        else:
            yield path, value

    for (path, left), (_, right) in zip(flat(real), flat(twin)):
        if left != right:
            return f"at {path}: the land's table has {left!r}, a blank land's {right!r}"
    return "the two tables differ in length"


# ---------------------------------------------------------------------------
# The measurements
# ---------------------------------------------------------------------------


def _twin_pair(cards, setter: _Setter, land_card, *, timing: str) -> str | None:
    """Play *land_card* under *setter* beside its blank twin. Returns None
    when the two tables agree, the first difference when they do not, and
    ``"unreached"`` when the setter does not set this land's type.

    *timing* is "after" (the type is set on a land already on the
    battlefield) or "under" (the static is there first and the land enters
    beneath it).
    """
    played = {}
    # The blank arm first: whether the setter reaches this land at all is a
    # question about its type line, which the twin shares.
    for arm in ("blank", "real"):
        board = _Board(cards, basics=_eats_a_land(land_card))
        if timing == "under":
            board.apply(setter, None)
            land = board.enter(_blank(land_card) if arm == "blank" else land_card, 0)
            board.settle()
            if arm == "blank" and not _was_set(board, land, land_card):
                return "unreached"
        else:
            land = board.enter(land_card, 0)
            board.settle()
            if not board.on_battlefield(land):
                return "gone"
            before = tuple(sorted(computed_types(land)[1]))
            try:
                board.apply(setter, land)
            except _Refused:
                return "refused"
            if tuple(sorted(computed_types(land)[1])) == before:
                return "unreached"
            if arm == "blank":
                land.card = _blank(land_card)
                board.game._recompute_continuous_effects()
        played[arm] = _play(board, land)
    real, twin = played["real"], played["blank"]
    return None if real == twin else _first_difference(real, twin)


def _was_set(board: _Board, land, land_card) -> bool:
    printed = tuple(sorted(printed_shape(land_card)[1]))
    return (
        board.on_battlefield(land)
        and tuple(sorted(computed_types(land)[1])) != printed
    )


def _cross_pair(cards, setter: _Setter, land_card) -> tuple[str, list[str]]:
    """One (setter, land) pair of the cross: ``(status, problems)``.

    *status* is "set" (the setter replaced the land's types), "added" (it
    added one, Blanket of Night) or "unreached".
    """
    problems: list[str] = []
    board = _Board(cards, basics=_eats_a_land(land_card))
    game = board.game
    land = board.enter(land_card, 0)
    board.settle()
    if not board.on_battlefield(land):
        return "gone", problems
    land.tapped = False
    printed = _facts(board, land)
    try:
        source = board.apply(setter, land)
    except _Refused as refused:
        return "refused", [str(refused)]
    after = _facts(board, land)
    lines = _printed_lines(land_card)

    if after["subtypes"] == printed["subtypes"]:
        # The control arm: a land the effect does not reach keeps every word.
        if after != printed:
            problems.append(f"unreached, and it changed: {printed} -> {after}")
        return "unreached", problems

    if setter.additive:
        # CR 305.7's last sentence: "it keeps its land types and rules text,
        # and it gains the new land types and mana abilities."
        if after["text"] != printed["text"]:
            problems.append("a type added in addition took the land's text")
        if after["usable"] != printed["usable"]:
            problems.append(
                f"a type added in addition left {after['usable']} of "
                f"{printed['usable']} abilities listed"
            )
        if not set(printed["mana"]) <= set(after["mana"]):
            problems.append(
                f"a type added in addition took mana the land made: "
                f"{printed['mana']} -> {after['mana']}"
            )
        gained = {
            _BASIC_MANA[word] for word in after["subtypes"] if word in _BASIC_MANA
        }
        if not gained <= set(after["mana"]):
            problems.append(
                f"a type added in addition gave no mana ability: {after['mana']}"
            )
        return "added", problems

    new_types = [word for word in _BASIC_MANA if word in after["subtypes"]]
    expected_mana = tuple(sorted(_BASIC_MANA[word] for word in new_types))

    # Nothing of the printed text is left to read…
    kept = [line for line in lines if line in after["text"]]
    if kept:
        problems.append(f"its text still reads: {kept[0][:70]!r}")
    if set(after["keywords"]) & set(printed["keywords"]):
        problems.append(f"it kept the keywords {after['keywords']}")
    # …nothing is listed, and the door agrees with the list…
    if after["usable"]:
        problems.append(f"{after['usable']} abilities are still listed")
    if printed["usable"]:
        accepted = game.activate_permanent_ability(
            0, land_card.name, ability_index=0,
            permanent_index=_slot(game, land),
        )
        if accepted.supported:
            problems.append("its first printed ability could still be activated")
        board.settle()
    # …it taps for exactly its new type's mana…
    if after["mana"] != expected_mana:
        problems.append(f"it would make {after['mana']}, not {expected_mana}")
    if board.on_battlefield(land):
        land.tapped = False
        pool = game.players[0].mana_pool
        for symbol in list(pool):
            pool[symbol] = 0
        game.tap_land_for_mana(
            0, land_card.name, chosen_color=expected_mana[0],
            permanent_id=land.permanent_id,
        )
        made = tuple(sorted(
            symbol for symbol, count in pool.items() for _ in range(count)
        ))
        if made != (expected_mana[0],):
            problems.append(
                f"tapped for {expected_mana[0]} it made {made or 'nothing'}"
            )
        for symbol in list(pool):
            pool[symbol] = 0
        land.tapped = False
        board.settle()

    # …and no static of it reaches the board: with its text box emptied,
    # nothing about any other permanent changes.
    if board.on_battlefield(land):
        with_text = _others(board, land)
        land.card = _blank(land_card)
        game._recompute_continuous_effects()
        without_text = _others(board, land)
        land.card = land_card
        game._recompute_continuous_effects()
        for had, has in zip(with_text, without_text):
            if had != has:
                problems.append(
                    f"a static of it still reached {had[1]}: "
                    f"{had[3]!r} with its text, {has[3]!r} without"
                )
                break

    # CR 611.3: and when the effect ends, the land is what it was.
    if not board.on_battlefield(land) or not board.end(setter, source, land):
        return "set", problems
    if board.on_battlefield(land):
        land.tapped = False
        back = _facts(board, land)
        if back != printed:
            problems.append(f"after the effect ended: {printed} -> {back}")
    return "set, ended", problems


def _slot(game, permanent) -> int:
    """*permanent*'s battlefield slot, by identity — the address
    ``activate_permanent_ability`` takes for its source."""
    seat = game.controller_index_of(permanent)
    return next(
        index for index, candidate in enumerate(game.players[seat].battlefield)
        if candidate is permanent
    )


# ---------------------------------------------------------------------------
# What another effect granted
# ---------------------------------------------------------------------------

#: A sentence that gives a land something: "Enchanted land has …", "Lands you
#: control have …", "All lands gain …". The candidates only — whether a card
#: really grants a nonbasic land an ability is asked of the engine
#: (:func:`_derive_granters`), by applying it.
_GRANT_WORDING = re.compile(
    r"\blands?\b[^.\n\"]*\b(?:has|have|gains?)\b", re.IGNORECASE
)


def _grant(board: _Board, card, land) -> None:
    """Apply the granter *card* — to *land* when it is an Aura."""
    game = board.game
    card_types, subtypes = printed_shape(card)
    if "aura" in subtypes:
        game.players[0].hand.append(card)
        result = game.cast_from_hand(
            0, card.name, target_permanent_ids=[land.permanent_id]
        )
    elif card_types & {"instant", "sorcery"}:
        game.players[0].hand.append(card)
        result = game.cast_from_hand(0, card.name)
    else:
        board.enter(card, 0)
        board.settle()
        return
    if not result.supported:
        raise _Refused(result.details)
    board.settle()


def _granted(facts: dict, plain: dict) -> bool:
    """Whether *facts* show something *plain* — the same land with nothing
    granted — does not."""
    return (
        facts["usable"] > plain["usable"]
        or bool(set(facts["keywords"]) - set(plain["keywords"]))
        or len(facts["text"]) > len(plain["text"])
    )


def _derive_granters(catalog, cards) -> list:
    """Every card that grants a nonbasic land an ability, found by granting.

    A candidate by its wording, a granter by what the engine does with it: it
    is applied to a land with an empty text box on a table with no setter, and
    it is one if that land then lists an ability, has a keyword or reads a
    line it did not.
    """
    probe = _blank(cards["Mishra's Factory"])
    found = []
    for card in sorted(compilation_units(catalog), key=lambda card: card.name):
        if not _GRANT_WORDING.search(card.oracle_text or ""):
            continue
        if not compile_card_oracle(card).supported:
            continue
        if "land" in printed_shape(card)[0]:
            continue
        board = _Board(cards, basics=False)
        try:
            if "aura" in printed_shape(card)[1] or (
                printed_shape(card)[0] & {"instant", "sorcery"}
            ):
                land = board.enter(probe, 0)
                board.settle()
                plain = _facts(board, land)
                _grant(board, card, land)
            else:
                # A permanent first: "As this enchantment enters, sacrifice
                # all lands you control." (Overlaid Terrain.)
                _grant(board, card, None)
                land = board.enter(probe, 0)
                board.settle()
                plain = {"usable": 0, "keywords": (), "text": ""}
        except (_Refused, AssertionError):
            continue
        if board.on_battlefield(land) and _granted(_facts(board, land), plain):
            found.append(card)
    return found


def _grant_pair(
    cards, granter, setter: _Setter, land_card, *, grant_first: bool
) -> tuple[str, list[str]]:
    """*land_card* with its type set by *setter* and an ability granted by
    *granter*, in one order or the other: ``(status, problems)``.

    What the land then has must be exactly what the same land **with an empty
    text box** has — the grant, whole, and nothing of its own.
    """
    problems: list[str] = []
    board = _Board(cards, basics=_eats_a_land(land_card))
    game = board.game
    permanent_granter = not (
        "aura" in printed_shape(granter)[1]
        or printed_shape(granter)[0] & {"instant", "sorcery"}
    )
    try:
        if permanent_granter and grant_first:
            _grant(board, granter, None)
        land = board.enter(land_card, 0)
        board.settle()
        if not board.on_battlefield(land):
            return "gone", problems
        land.tapped = False
        before = tuple(sorted(computed_types(land)[1]))
        if grant_first:
            if not permanent_granter:
                _grant(board, granter, land)
            board.apply(setter, land)
        else:
            board.apply(setter, land)
            _grant(board, granter, land)
    except _Refused:
        return "refused", problems
    if not board.on_battlefield(land):
        return "gone", problems
    if tuple(sorted(computed_types(land)[1])) == before:
        return "unreached", problems

    real = _facts(board, land)
    land.card = _blank(land_card)
    game._recompute_continuous_effects()
    blank = _facts(board, land)
    land.card = land_card
    game._recompute_continuous_effects()

    if not _granted(blank, {"usable": 0, "keywords": (), "text": ""}):
        return "nothing granted", problems
    if real != blank:
        problems.append(
            f"it has {real}, where the same land with no text has {blank}"
        )
    # The door agrees with the list: nothing refuses the land whole.
    if blank["usable"] and game.lost_abilities_refusal(land) is not None:
        problems.append(
            f"the activation door refuses it whole: "
            f"{game.lost_abilities_refusal(land)}"
        )
    return "granted", problems


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _cards(catalog_by_name):
    return catalog_by_name


@pytest.fixture(scope="module")
def _setters(catalog):
    return _derive_setters(catalog)


@pytest.fixture(scope="module")
def _lands(catalog):
    return _nonbasic_lands(catalog)


@pytest.mark.cr("305.7")
def test_305_7_the_setter_kinds_are_the_handlers_that_write_a_land_type():
    """``_SETTING_KINDS`` against the engine: every handler that records a
    land-type contribution, or arms the prompt whose answer records one."""
    writers = set()
    for kind, handler in EFFECT_HANDLERS.items():
        source = inspect.getsource(handler)
        if (
            "change_land_type(" in source
            or '"land_type_choice"' in source
            or '"land_type_swap"' in source
        ):
            writers.add(kind)
    assert writers == set(_SETTING_KINDS)


@pytest.mark.cr("305.7")
def test_305_7_the_setters_are_every_card_that_sets_a_land_type(catalog, _setters):
    """The derivation reaches every card whose program holds a setting kind,
    wherever in the program it sits — a setter on a *triggered* ability would
    be a card the cross never drove."""
    named = {setter.name for setter in _setters}
    holding = set()
    for card in compilation_units(catalog):
        program = compile_card_oracle(card)
        steps = list(program.instructions)
        steps += [ability.instruction for ability in program.activated_abilities]
        steps += [trigger.instruction for trigger in program.triggered_abilities]
        steps += [
            mode.instruction for mode in (getattr(program, "modes", ()) or ())
        ]
        if any(
            inner.kind in _SETTING_KINDS or inner.kind == _STATIC_KIND
            for step in steps for inner in _walk(step)
        ):
            holding.add(card.name)
    assert holding <= named, sorted(holding - named)
    # Blood Moon, an Aura, a turn-long ability and a spell are all there.
    assert {"Blood Moon", "Evil Presence", "Kavu Recluse", "Jinx"} <= named
    assert len(_setters) >= 24, [setter.label for setter in _setters]


def _report(problems: dict) -> str:
    """The lands first: a land that fails under one setter usually fails
    under all of them, and the land is what a reader has to go and look at."""
    by_land: dict[str, list] = {}
    for (setter, land), found in sorted(problems.items()):
        by_land.setdefault(land, []).append((setter, found))
    lines = [f"{len(problems)} pair(s), {len(by_land)} land(s):"]
    for land, rows in sorted(by_land.items()):
        setter, found = rows[0]
        lines.append(
            f"  {land} — under {len(rows)} setter(s), e.g. {setter}: "
            + "; ".join(found)[:400]
        )
    return "\n".join(lines)


#: The cross is one sweep cut into this many pieces, by land, so that a test
#: runner with several workers can share it out.
_CROSS_CHUNKS = 6


@pytest.mark.cr("305.7", "305.6")
@pytest.mark.parametrize("chunk", range(_CROSS_CHUNKS))
def test_305_7_every_setter_against_every_nonbasic_land(
    _cards, _setters, _lands, chunk
):
    """Every (type-setting effect, nonbasic land) pair: the land's own text
    reads as no ability, nothing is listed or activatable, it taps for exactly
    its new type's mana, no static of it reaches the board — and when the
    effect ends it is the land it was. A pair the effect does not reach, and
    Blanket of Night's addition, keep every word."""
    problems: dict = {}
    counts: Counter = Counter()
    refused = []
    lands = _lands[chunk::_CROSS_CHUNKS]
    for setter in _setters:
        for land in lands:
            status, found = _cross_pair(_cards, setter, land)
            counts[status] += 1
            if status == "refused":
                refused.append((setter.label, land.name, found[0]))
            elif found:
                problems[(setter.label, land.name)] = found
    assert not problems, _report(problems)

    # A sweep that reaches nothing passes, so what it reached is asserted.
    # Over the whole pool the cross is 4,536 pairs: 3,614 where the type was
    # set (3,051 of them ended and looked at again), 185 where one was added,
    # 733 the effect does not reach and 4 it may not be aimed at.
    assert not counts["gone"], counts
    assert counts["set"] + counts["set, ended"] >= 570, counts
    assert counts["set, ended"] >= 480, counts
    assert counts["added"] >= 28, counts
    assert counts["unreached"] >= 100, counts
    # The only announcement the engine may decline is Cyclopean Tomb's "target
    # **non-Swamp** land" at a land that is a Swamp.
    assert all(
        setter == "Cyclopean Tomb" and "no valid target" in reason
        for setter, _land, reason in refused
    ), refused
    assert len(refused) <= 4, refused


@pytest.mark.cr("305.7")
def test_305_7_the_cross_names_the_lands_whose_text_did_something(_lands, _setters):
    """The population the sweeps above run over, held to the lands this file
    was written for: every land ``_PRINTED_ABILITIES_FUNCTIONED`` names is
    swept, under a setter that reaches it."""
    names = {land.name for land in _lands}
    assert set(_PRINTED_ABILITIES_FUNCTIONED) <= names
    assert len(_lands) >= 189
    assert sum(1 for land in _lands if _printed_lines(land)) >= 179
    assert {"Blood Moon", "Evil Presence"} <= {setter.name for setter in _setters}


#: The lands whose printed ability still **did** something with their type set
#: by an effect already on the table, on the tree before this file — measured
#: there with :func:`_twin_pair` ("after" timing, 15 of 179 under Blood Moon
#: and the same 15 under Evil Presence). For seven the first thing that
#: differed was a static ability, which no reader of CR 305.7 asked about; for
#: eight a triggered one, read by a scan that went round the one that asked.
#: With the static already out as the land *entered*, 102 of 179 differed:
#: tapped by an "enters tapped" they no longer had, charged a toll, given
#: counters, or triggered.
_PRINTED_ABILITIES_FUNCTIONED = (
    # a static ability reaching the board
    "The Tabernacle at Pendrell Vale",
    "Adventurers' Guildhouse", "Cathedral of Serra", "Mountain Stronghold",
    "Seafarer's Quay", "Unholy Citadel",
    # "doesn't untap during your untap step", and its upkeep trigger
    "Forsaken City",
    # cumulative upkeep, charged
    "Glacial Chasm", "Halls of Mist",
    # an upkeep trigger, resolved
    "Land Cap", "Lava Tubes", "River Delta", "Timberline Ridge", "Veldt",
    "Safe Haven",
)

#: The twin sweep: a setter and when it arrives. Blood Moon is the derived
#: channel (a static, rebuilt every refresh) and Evil Presence the recorded
#: one (a contribution written once) — every setter in the pool writes through
#: one of the two (``engine/land_types.py``), and the cross drives each of
#: them. "under" is the static already on the battlefield as the land enters.
_TWINS = (
    ("Blood Moon", "after"),
    ("Blood Moon", "under"),
    ("Evil Presence", "after"),
)
_TWIN_CHUNKS = 3


@pytest.mark.cr("305.7", "614.12", "603.6a")
@pytest.mark.parametrize("chunk", range(_TWIN_CHUNKS))
@pytest.mark.parametrize("setter_name,timing", _TWINS)
def test_305_7_a_set_land_plays_like_a_land_with_no_text(
    _cards, _setters, _lands, setter_name, timing, chunk
):
    """The rule as behaviour: three half-turns beside the same land with an
    empty text box, and the two tables come out the same. "under" is CR
    614.12 and CR 603.6a — how a land enters, and what triggers as it does,
    are decided against the Mountain it is entering as."""
    setter = next(s for s in _setters if s.name == setter_name)
    lands = [land for land in _lands if _printed_lines(land)][chunk::_TWIN_CHUNKS]
    different = {}
    counts: Counter = Counter()
    for land in lands:
        outcome = _twin_pair(_cards, setter, land, timing=timing)
        if outcome in (None, "unreached", "refused", "gone"):
            counts[outcome or "same"] += 1
        else:
            different[(setter.label, land.name)] = [outcome]
    assert not different, _report(different)
    # Both setters reach every nonbasic land, so every pair was played.
    assert counts == Counter(same=len(lands)), counts
    assert len(lands) >= 59


@pytest.fixture(scope="module")
def _granters(catalog, _cards):
    return _derive_granters(catalog, _cards)


@pytest.mark.cr("305.7")
def test_305_7_keeps_what_another_effect_granted(_cards, _setters, _granters):
    """Every way the pool grants a land an ability, against every way it sets
    a land's type, in both orders: the land has the grant and nothing of its
    own — exactly what the same land with an empty text box has.

    "Note that this doesn't remove any abilities that were granted to the
    land by other effects." Not layer 6's timestamp order: the grant made
    *before* the type was set is kept as the one made after is.
    """
    names = {card.name for card in _granters}
    # A quoted activated ability and a quoted triggered one from an Aura, a
    # keyword from an Aura, a board-wide static's quoted ability and its
    # keyword, and two until-end-of-turn grants.
    assert {
        "Caribou Range", "Farmstead", "Consecrate Land", "Overlaid Terrain",
        "Spiritual Asylum", "Rain of Filth", "Skyshroud Blessing",
    } <= names, sorted(names)
    assert len(_granters) >= 16, sorted(names)

    # One setter of each kind — a static, an Aura, a spell, and an ability
    # for each way its effect ends. The cross drives every setter; what
    # differs between two of one kind is which land they may be aimed at,
    # and here there is one land.
    kinds: dict = {}
    for setter in _setters:
        if not setter.additive:
            kinds.setdefault((setter.shape, setter.ends), setter)
    assert len(kinds) >= 7, sorted(kinds)

    land = _cards["Mishra's Factory"]
    problems: dict = {}
    counts: Counter = Counter()
    for granter in _granters:
        for setter in kinds.values():
            for grant_first in (True, False):
                status, found = _grant_pair(
                    _cards, granter, setter, land, grant_first=grant_first
                )
                counts[(status, grant_first)] += 1
                if found:
                    order = "granted first" if grant_first else "set first"
                    problems[(f"{setter.label} + {granter.name}, {order}", land.name)] = found
    assert not problems, _report(problems)
    # Both orders are really arranged, for a real share of the pairs. (What is
    # not: a land with shroud cannot be aimed at, a consecrated land takes no
    # second Aura, and Overlaid Terrain arriving second sacrifices the land.)
    assert counts[("granted", True)] >= 60, counts
    assert counts[("granted", False)] >= 60, counts
    assert not counts[("nothing granted", True)], counts
    assert not counts[("nothing granted", False)], counts


# ---------------------------------------------------------------------------
# The cases with a name
# ---------------------------------------------------------------------------
#
# What the sweeps above found, one card at a time, so that a failure reads as
# a card and a rule rather than as a row.


def _text(permanent) -> str:
    return permanent.effective_card.oracle_text.lower()


@pytest.mark.cr("305.7", "611.3a")
def test_305_7_the_tabernacle_under_blood_moon_taxes_nobody(_cards):
    """"All creatures have 'At the beginning of your upkeep, destroy this
    creature unless you pay {1}.'" Under Blood Moon the Tabernacle is a
    Mountain with no ability, so no creature has that one — and the moment the
    Moon is gone every creature has it again (CR 611.3a: a static ability's
    effect is not locked in)."""
    board = _Board(_cards)
    game = board.game
    tabernacle = board.enter("The Tabernacle at Pendrell Vale", 0)
    board.settle()
    bears = board.probes[0]
    assert "destroy this creature unless you pay {1}" in _text(bears)

    moon = board.enter("Blood Moon", 1)
    board.settle()

    assert tabernacle.basic_land_types == ("mountain",)
    assert _text(tabernacle) == ""
    for creature in board.probes:
        assert "destroy this creature" not in _text(creature)
    # Nothing is asked for, nothing is paid and nothing dies in the upkeep.
    game.interactive_seats = set()
    game.turn += 1
    game.start_turn(0)
    _drain(game)
    assert all(game.is_on_battlefield(creature) for creature in board.probes)
    assert not any("upkeep for" in line for line in game.log)
    assert game.tap_land_for_mana(
        0, tabernacle.card.name, chosen_color="R",
        permanent_id=tabernacle.permanent_id,
    )
    assert game.players[0].mana_pool.get("R") == 1

    game.sacrifice_permanent(moon)
    board.settle()

    assert tabernacle.basic_land_types == ()
    assert "destroy this creature unless you pay {1}" in _text(bears)


@pytest.mark.cr("305.7", "702.24a")
def test_305_7_glacial_chasm_under_blood_moon_is_only_a_mountain(_cards):
    """Cumulative upkeep, "creatures you control can't attack" and "prevent
    all damage that would be dealt to you" — a keyword, a static restriction
    and a prevention effect, read by three different parts of the engine.
    Under Blood Moon none of them is the Chasm's: nothing is paid, the
    creatures attack, and the damage lands."""
    board = _Board(_cards)
    game = board.game
    chasm = board.enter("Glacial Chasm", 0)
    board.settle()
    assert board.on_battlefield(chasm)
    board.enter("Blood Moon", 1)
    board.settle()
    game.interactive_seats = set()
    life = [player.life for player in game.players]

    _half_turn(board, 0, chasm, first=False)

    # No age counter, no life paid, the land still there…
    assert board.on_battlefield(chasm)
    assert not chasm.metadata.get("age_counters")
    assert game.players[0].life == life[0]
    # …and its controller's creatures attacked: Bears for 2, the Queen for 7.
    assert game.players[1].life == life[1] - 9

    _half_turn(board, 1, chasm, first=False)

    # The opponent's Bears connected: nothing prevented the damage.
    assert game.players[0].life == life[0] - 2


@pytest.mark.cr("614.12", "603.6a", "603.6d", "305.7")
def test_305_7_a_land_entering_under_blood_moon_enters_as_a_mountain(_cards):
    """CR 614.12: how a permanent enters is decided against "the
    characteristics of the permanent as it would exist on the battlefield",
    under the continuous effects already there. A nonbasic land entering
    under Blood Moon is a Mountain: it has no "enters tapped", no toll, no
    counters to enter with (each a static ability of its own, CR 603.6d) and
    no "when this land enters" to trigger (CR 603.6a)."""
    def enters(name: str, *, moon: bool = True):
        board = _Board(_cards)
        if moon:
            board.enter("Blood Moon", 1)
            board.settle()
        player = board.game.players[0]

        def table() -> tuple:
            return (
                player.life,
                sorted(card.name for card in player.hand),
                sorted(card.name for card in player.graveyard),
                sorted(perm.card.name for perm in board.game.controlled_by(0)),
            )

        before = table()
        land = board.enter(name, 0)
        board.settle()
        after = table()
        if board.on_battlefield(land):
            after[3].remove(name)
        return board, land, before, after

    # "This land enters tapped. When this land enters, sacrifice it unless you
    # return an untapped Plains you control to its owner's hand."
    board, karoo, before, after = enters("Karoo")
    assert board.on_battlefield(karoo) and not karoo.tapped
    assert before == after, "no Plains was returned and nothing was sacrificed"

    # "If this land would enter, sacrifice two untapped lands instead."
    board, vale, before, after = enters("Lotus Vale")
    assert board.on_battlefield(vale) and before == after

    # "This land enters with three mining counters on it."
    board, mine, before, after = enters("Gemstone Mine")
    assert board.on_battlefield(mine)
    assert not mine.metadata.get("mining_counters")

    # "This land enters tapped. When this land enters, you gain 1 life."
    board, caves, before, after = enters("Bloodfell Caves")
    assert not caves.tapped and before == after

    # It is a Mountain, and taps for {R}.
    assert caves.basic_land_types == ("mountain",)
    assert board.game.tap_land_for_mana(
        0, caves.card.name, chosen_color="R", permanent_id=caves.permanent_id
    )
    assert board.game.players[0].mana_pool.get("R") == 1

    # The control: with no Blood Moon the same lands do all of it.
    board, karoo, before, after = enters("Karoo", moon=False)
    assert karoo.tapped and "Plains" in after[1]
    board, mine, before, after = enters("Gemstone Mine", moon=False)
    assert mine.metadata.get("mining_counters") == 3
    board, caves, before, after = enters("Bloodfell Caves", moon=False)
    assert caves.tapped and after[0] == before[0] + 1


@pytest.mark.cr("305.7", "305.6")
def test_305_7_a_type_gained_in_addition_keeps_the_land_whole(_cards):
    """"Each land is a Swamp in addition to its other land types." (Blanket of
    Night.) CR 305.7's last sentence: the land "keeps its land types and
    rules text, and it gains the new land types and mana abilities". Read as
    a set — which any land-type contribution was — a Mishra's Factory under a
    Blanket of Night listed nothing, made {B} and only {B}, and could not
    animate."""
    board = _Board(_cards)
    game = board.game
    factory = board.enter("Mishra's Factory", 0)
    board.enter("Blanket of Night", 1)
    board.settle()

    assert "swamp" in factory.basic_land_types
    assert "Assembly-Worker" in factory.effective_card.oracle_text
    assert len(game.usable_abilities_of(factory)) == 3
    assert game.lost_abilities_refusal(factory) is None
    assert set(factory.effective_produced_mana) == {"B", "C"}

    pool = game.players[0].mana_pool
    # Its own "{T}: Add {C}." …
    assert game.tap_land_for_mana(
        0, "Mishra's Factory", chosen_color="C", permanent_id=factory.permanent_id
    )
    assert pool.get("C") == 1 and not pool.get("B")
    # …and the Swamp's "{T}: Add {B}." it gained.
    factory.tapped = False
    pool["C"] = 0
    assert game.tap_land_for_mana(
        0, "Mishra's Factory", chosen_color="B", permanent_id=factory.permanent_id
    )
    assert pool.get("B") == 1 and not pool.get("C")
    # And it still animates.
    factory.tapped = False
    animated = game.activate_permanent_ability(
        0, "Mishra's Factory", ability_index=1,
        permanent_index=_slot(game, factory),
    )
    assert animated.supported, animated.details
    board.settle()
    assert factory.is_creature

    # A Blood Moon beside it *sets* the type, and that is the rule's first
    # sentence whichever of the two arrived first.
    board.enter("Blood Moon", 1)
    board.settle()
    assert game.usable_abilities_of(factory) == []
    assert factory.effective_card.oracle_text == ""
    assert factory.effective_produced_mana == ("R",) or set(
        factory.effective_produced_mana
    ) == {"B", "R"}


@pytest.mark.cr("305.7", "605.1a")
def test_305_7_a_granted_mana_ability_is_the_set_lands_to_tap(_cards):
    """'Lands you control have "{T}: Add two mana of any one color."'
    (Overlaid Terrain.) A granted mana ability is one CR 305.7 keeps, and the
    land tap seam is where a land's mana abilities are run: it used to answer
    for a land whose type was set before it looked at what the land had."""
    board = _Board(_cards, bare=True)
    game = board.game
    board.enter("Overlaid Terrain", 0)
    board.settle()
    factory = board.enter("Mishra's Factory", 0)
    board.enter("Blood Moon", 1)
    board.settle()

    assert factory.basic_land_types == ("mountain",)
    assert _text(factory) == "{t}: add two mana of any one color."
    assert len(game.usable_abilities_of(factory)) == 1

    assert game.tap_land_for_mana(
        0, "Mishra's Factory", chosen_color="G", permanent_id=factory.permanent_id
    )
    assert game.players[0].mana_pool.get("G") == 2


@pytest.mark.cr("305.7", "602.2")
def test_305_7_a_granted_ability_is_the_only_one_the_door_opens_for(_cards):
    """'Until end of turn, lands you control gain "Sacrifice this land: Add
    {B}."' (Rain of Filth.) On a Mishra's Factory under Blood Moon that is
    ability 0 — the only one — and the door that used to refuse the land
    whole lets it through; the Factory's own abilities are not there to be
    named."""
    board = _Board(_cards, bare=True)
    game = board.game
    factory = board.enter("Mishra's Factory", 0)
    board.enter("Blood Moon", 1)
    board.settle()
    assert game.lost_abilities_refusal(factory) == (
        "Mishra's Factory lost its abilities when its land type was set (CR 305.7)"
    )

    game.players[0].hand.append(_cards["Rain of Filth"])
    assert game.cast_from_hand(0, "Rain of Filth").supported
    board.settle()

    assert game.lost_abilities_refusal(factory) is None
    assert _text(factory) == "sacrifice this land: add {b}"
    assert len(game.usable_abilities_of(factory)) == 1
    refused = game.activate_permanent_ability(
        0, "Mishra's Factory", ability_index=1,
        permanent_index=_slot(game, factory),
    )
    assert not refused.supported and not factory.is_creature

    accepted = game.activate_permanent_ability(
        0, "Mishra's Factory", ability_index=0,
        permanent_index=_slot(game, factory),
    )
    assert accepted.supported, accepted.details
    board.settle()
    assert not board.on_battlefield(factory)
    assert game.players[0].mana_pool.get("B") == 1
