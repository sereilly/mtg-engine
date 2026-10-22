"""Census: does an AI seat reach every mode of every modal instant and sorcery?

The pool-wide half of ``test_ai_mode_chooser.py``. 34 instants and sorceries
print a "Choose one —" head their caster answers, 88 modes between them, and
until the policy had a mode to name (``CastAction.mode_index``) an AI seat
cast every one of them as its first bullet — and held the card whenever that
bullet had nothing to point at.

**How it is built, so it can be read backwards.** Stable public surfaces only:

* the **population** is every supported instant or sorcery whose compiled
  program has modes its caster chooses (``mode_chooser is None``);
* the **board** for one ``(card, mode)`` comes from the engine's own per-mode
  picker (``Game.cast_target_spec(mode_index=)``): one bait the mode may
  target **and does something to** (the mode cast at it by hand and the board
  compared — "destroy target permanent if it's blue" may name any permanent
  and touches only a blue one), on the side its effect wants, and for every
  other mode a decoy on the side that mode does *not* want — "its target exists and is the
  opponent's; the others have no legal target, or only the caster's own
  things";
* the **proposal** is ``choose_cast_action`` in the seat's own main phase, or
  ``choose_combat_instant_cast_action`` in the windows the web AI answers
  in — a spell on the stack, an opponent's attack, and the seat's own attack
  once blocks are declared (the one board on which "attacking creatures get
  +1/+0" is a cast);
* the **executor** is ``ai_simulator._play_one_cast``, the real one, with a
  spy on ``Game._cast_onto_stack`` reading the mode the cast was announced
  with. A proposal naming no mode is mode 0: that is what the engine resolves
  a cast naming none as, so on the tree before the chooser this census reads
  **0 modes other than the first reached**, and 30 of 87.

Three legs per mode:

``natural``
    the chooser, unaided, on the mode's own board. Where the board makes this
    the **only** mode worth casting (41 of them) it must be the one proposed.
    Where it cannot — a sibling needs no target, or targets a player, or may
    name the very same permanent — the sibling may win, and which one did is
    pinned in ``SHADOWED`` below, each with the reason it loses.
``forced``
    the same board with ``Game.announceable_modes`` answering only this mode:
    "were this the one mode on offer, is it proposed, is the cast accepted in
    that mode, and does the resolution do anything?" A seat no longer casts a
    spell that changes nothing, so a mode's board is one it has something to
    act on — and it no longer casts one **nothing of which outlasts the
    turn**, so of the 85 modes with a board 73 are proposed and twelve are
    *held* (``HELD``): "target creature gains flying until end of turn" at a
    creature with nothing to fly over. Each of those twelve is held because the
    census's own cast of it there, the turn's fight fought, leaves nothing
    behind (``weighed``) — the engine's answer, not the policy's.
``measured``
    **is the cast the larger one?** For the mode and every sibling its board
    leaves worth casting, each is cast *by hand* at every target the engine's
    picker offers, and each cast is priced with ``ai_valuation``'s one
    definition of "larger": the swing in each seat's standing, as the board
    stood and again once the turn had run out — **with the turn's combat
    fought**, for a cast made before it whose good is this turn's only
    (``weighed``). The policy's own cast, made
    through the real executor and priced the same way, must measure as much
    as the best of them (``SMALLER``, empty). The policy predicts with that
    definition by rehearsing a cast on a copy of the game; this measures with
    it on boards of its own, never through the rehearsal.

Run it as a module (``python -m tests.ai.test_ai_mode_chooser_census``) for the
whole table.
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from dataclasses import replace
from unittest import mock

import pytest

from engine import Game, PlayerState
from engine import ai_simulator
from engine.ai_policy import (choose_cast_action,
                              choose_combat_instant_cast_action)
from engine.ai_valuation import (CARD_WORTH, combat_is_still_to_come,
                                 forget_damage_history,
                                 instruction_target_side, position_digest,
                                 untap_for_the_next_turn,
                                 priced_by_the_fight, run_out_the_turn,
                                 same_position, scratch_copy,
                                 several_target_slot_sides, standing_swing,
                                 standings, swing_worth)
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, spec_roles
from tests.helpers import _mk_card, resolve_stack

PLAYER_KINDS = {"player", "player_or_planeswalker", "any", "opponent"}
ME, OPP = 0, 1


def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


POOL = pool()


def population() -> list:
    """Every caster-chosen modal instant and sorcery, by name."""
    found = []
    for name in sorted(POOL):
        card = POOL[name]
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or len(program.modes) < 2:
            continue
        if program.mode_chooser is not None:
            continue  # CR 700.2e: an opponent chooses
        found.append(card)
    return found


# -- the zoo ------------------------------------------------------------------

def _creature(name, colors=(), power=2, toughness=2, text="", type_line=None):
    return _mk_card(
        name=name, type_line=type_line or "Creature - Beast", colors=colors,
        power=power, toughness=toughness, oracle_text=text,
    )


ZOO = {
    "white creature": _creature("Bait White", ("W",)),
    "blue flyer": _creature("Bait Blue Flyer", ("U",), 1, 1, "Flying"),
    "black creature": _creature("Bait Black", ("B",), 3, 3),
    "red creature": _creature("Bait Red", ("R",)),
    "green creature": _creature("Bait Green", ("G",), 4, 4),
    "wall": _creature("Bait Wall", (), 0, 4, "Defender", "Creature - Wall"),
    "artifact creature": _creature("Bait Golem", (), 3, 3, "", "Artifact Creature - Golem"),
    # Placed tapped (`place`): "Untap target permanent" has nothing to do to
    # one that is not.
    "tapped creature": _creature("Bait Tapped", ("G",), 2, 3),
    "artifact": _mk_card(name="Bait Artifact", type_line="Artifact"),
    "enchantment": _mk_card(name="Bait Enchantment", type_line="Enchantment", colors=("W",)),
    "nonbasic land": _mk_card(name="Bait Nonbasic", type_line="Land"),
    "planeswalker": replace(
        _mk_card(name="Bait Walker", type_line="Legendary Planeswalker - Bait", colors=("B",)),
        loyalty="4",
    ),
    "plains": POOL["Plains"], "island": POOL["Island"], "swamp": POOL["Swamp"],
    "mountain": POOL["Mountain"], "forest": POOL["Forest"],
    # An Aura is placed with the creature it enchants (`place`).
    "aura": _mk_card(
        name="Bait Aura", type_line="Enchantment - Aura", colors=("G",),
        oracle_text="Enchant creature",
    ),
}
_AURA_HOST = _creature("Bait Host", (), 2, 2)
#: Graveyard baits: a creature card and a noncreature card.
GRAVE = {
    "creature card": _creature("Bait Dead Bear", ("G",)),
    "sorcery card": _mk_card(name="Bait Dead Spell", type_line="Sorcery"),
}
#: Stack baits: a creature spell of each colour the pool's stack modes read.
SPELLS = {
    "red spell": _mk_card(
        name="Bait Red Spell", mana_cost="{R}", type_line="Creature - Goblin",
        colors=("R",), power=1, toughness=1,
    ),
    "blue spell": _mk_card(
        name="Bait Blue Spell", mana_cost="{U}", type_line="Creature - Bird",
        colors=("U",), power=1, toughness=1,
    ),
}


#: The one card in the opponent's hand: a discard needs something to take.
SPARE = _mk_card(name="Bait Spare Card", type_line="Sorcery")


def place(game, seat: int, key: str) -> Permanent:
    """Put zoo unit *key* onto *seat*'s battlefield; the bait permanent."""
    if key == "aura":
        host = Permanent(card=_AURA_HOST)
        game._put_permanent_onto_battlefield(seat, host, seat)
        host.metadata["summoning_sickness_turn"] = -99
        aura = Permanent(card=ZOO["aura"])
        game._put_permanent_onto_battlefield(seat, aura, seat)
        attach_aura(aura, host)
        return aura
    permanent = Permanent(card=ZOO[key])
    game._put_permanent_onto_battlefield(seat, permanent, seat)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = key == "tapped creature"
    return permanent


def board(card, placements=(), *, window=None, grave=(), stack=None):
    """A duel with *card* alone in seat 0's hand and nothing on the table but
    *placements* (``(seat, zoo key)``).

    *window* is None for seat 0's own main phase, ``"combat"`` for seat 1's
    declare-blockers step (seat 1's creatures attacking seat 0), ``"attack"``
    for seat 0's own (its creatures attacking, no block declared), ``"stack"``
    for seat 1's main phase with *stack* (a ``SPELLS`` key) cast and waiting.
    Seat 0 pays out of a mana pool, so the board holds no land the census did
    not put there.
    """
    forest = POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[card], library=[forest] * 10),
        PlayerState(name="Opp", hand=[SPARE], library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    placed = {}
    for seat, key in placements:
        placed[(seat, key)] = place(game, seat, key)
    for seat, key in grave:
        game.players[seat].graveyard.append(GRAVE[key])
    if window == "combat":
        game.start_turn(OPP)
        game._close_current_priority_step()
        game.advance_combat_phase()
        game.advance_combat_phase()
        assert game.current_step == "declare_attackers", game.current_step
        attackers = [
            index for index, perm in enumerate(game.players[OPP].battlefield)
            if perm.is_creature and not perm.tapped
            and "Defender" not in (perm.card.oracle_text or "")
        ]
        game.declare_attackers(OPP, attackers, defending_player_index=ME)
    elif window == "attack":
        game.start_turn(ME)
        game._close_current_priority_step()
        game.advance_combat_phase()
        game.advance_combat_phase()
        assert game.current_step == "declare_attackers", game.current_step
        attackers = [
            index for index, perm in enumerate(game.players[ME].battlefield)
            if perm.is_creature and not perm.tapped
            and "Defender" not in (perm.card.oracle_text or "")
        ]
        game.declare_attackers(ME, attackers, defending_player_index=OPP)
        game.advance_combat_phase()
        assert game.current_step == "declare_blockers", game.current_step
        game.declare_blockers(OPP, {})
        # The turn's draw is not part of the board: one card in hand, as on
        # every other.
        game.players[ME].hand[:] = [card]
    elif window == "stack":
        game.start_turn(OPP)
        game._close_current_priority_step()
        spell = SPELLS[stack]
        game.players[OPP].hand.append(spell)
        game.players[OPP].mana_pool.update({"R": 3, "U": 3})
        queued = game.queue_from_hand(OPP, spell.name)
        assert queued.supported, queued.details
    game.players[ME].mana_pool.update({symbol: 6 for symbol in "WUBRG"})
    return game, placed


# -- what a mode is -----------------------------------------------------------

def mode_spec(card, index):
    return derive_cast_spec(card, compile_card_oracle(card), mode_index=index) or {}


def mode_shape(card, index) -> str:
    spec = mode_spec(card, index)
    kind = spec.get("kind")
    if spec_roles(spec):
        return "roles"
    if kind in (None, "none"):
        return "untargeted"
    if kind in PLAYER_KINDS:
        return "player"
    if kind == "stack":
        return "stack"
    if kind == "graveyard_creature":
        return "graveyard"
    return "object"


def mode_side(card, index) -> "str | None":
    """Whose permanent this mode's object target should be -- the reading the
    one-target chooser makes (denial wins), over this mode's own steps."""
    instruction = compile_card_oracle(card).modes[index].instruction
    sides: set = set()

    def walk(step) -> None:
        payload = getattr(step, "payload", None) or {}
        targets = payload.get("targets")
        if isinstance(targets, dict) and targets.get("kind") in ("object", "roles"):
            side = instruction_target_side(step)
            if side is not None:
                sides.add(side)
        for key in ("steps", "then", "else", "action", "otherwise"):
            for nested in payload.get(key) or ():
                walk(nested)

    if instruction is not None:
        walk(instruction)
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


def legal_permanents(game, card, index) -> list:
    """The permanents the engine's own picker offers mode *index*."""
    listed = game.cast_target_spec(ME, card, mode_index=index).get("valid_targets") or []
    return [entry for entry in listed if entry.get("kind") == "permanent"]


def wanted_seat(side) -> int:
    return ME if side == "you" else OPP


def worth_casting(game, card, index) -> "str | None":
    """Why mode *index* is worth casting on this board, or None when it is not:
    it has a legal announcement and what it names is not on the side its own
    effect does not want."""
    if index not in game.announceable_modes(ME, card):
        return None
    shape = mode_shape(card, index)
    if shape == "untargeted":
        return "needs no target"
    if shape == "player":
        return "targets a player"
    if shape in ("stack", "graveyard"):
        return f"has a {shape} target"
    side = mode_side(card, index)
    if shape == "roles":
        chains = game.cast_target_spec(ME, card, mode_index=index).get("valid_targets") or []
        if side is None:
            return "has a chain" if chains else None
        seat = wanted_seat(side)

        def on_side(options) -> bool:
            return any(
                option.get("seat") == seat
                and (not option.get("next") or on_side(option["next"]))
                for option in options
            )

        return "has a chain on its side" if on_side(chains) else None
    legal = legal_permanents(game, card, index)
    if side is None:
        return "has a target" if legal else None
    seat = wanted_seat(side)
    return "has a target on its side" if any(e["seat"] == seat for e in legal) else None


# -- building one mode's board --------------------------------------------------

def _zoo_keys_legal(card, index, seat, window=None, grave=(), stack=None) -> list:
    """Which zoo units mode *index* may target when they sit on *seat*."""
    keys = []
    for key in ZOO:
        game, placed = board(card, [(seat, key)], window=window, grave=grave, stack=stack)
        bait = placed[(seat, key)]
        slot = (game.controller_index_of(bait), game.battlefield_index_of(bait))
        if any((e["seat"], e["index"]) == slot for e in legal_permanents(game, card, index)):
            keys.append(key)
    return keys


def zones(game, spell) -> str:
    """Where every card is, with no object identity in it: comparable between
    two boards built the same way, which `signature` is not (a permanent's id
    is a process-wide counter)."""
    parts = []
    for seat, player in enumerate(game.players):
        hand = sorted(c.name for c in player.hand)
        yard = sorted(c.name for c in player.graveyard)
        if seat == ME:
            for pile in (hand, yard):
                if spell.name in pile:
                    pile.remove(spell.name)
        parts.append((
            player.life, hand, yard, sorted(c.name for c in player.exile),
            len(player.library),
            sorted(
                (perm.card.name, perm.tapped,
                 perm.is_creature and perm.effective_power,
                 perm.is_creature and perm.effective_toughness)
                for perm in player.battlefield
            ),
        ))
    return repr(parts)


def untouched(card, built) -> str:
    """Where every card ends up on *built*'s board when seat 0 casts
    **nothing**: whatever is already on the stack resolves, and that is all.
    What a cast in a stack window is measured against — the opposing spell
    changes the board by resolving, so "the board changed" would say nothing
    about the counterspell."""
    game, _ = board(
        card, built["placements"], window=built["window"],
        grave=built["grave"], stack=built["stack"],
    )
    resolve_stack(game)
    return zones(game, card)


def mode_acts_on(card, index, candidate) -> bool:
    """Whether mode *index*, cast by hand at the candidate board's one bait
    (a permanent, or the spell on the stack), resolves doing anything — the
    engine's answer, with no policy in it."""
    game, placed = board(
        card, candidate["placements"], window=candidate["window"],
        grave=candidate["grave"], stack=candidate["stack"],
    )
    x_value = 2 if "{X}" in (card.mana_cost or "").upper() else None
    in_response = candidate["window"] == "stack"
    if in_response:
        named = {"target_stack_index": len(game.stack) - 1}
    else:
        bait = next(iter(placed.values()))
        named = {
            "target_player_index": game.controller_index_of(bait),
            "target_permanent_ids": [bait.permanent_id],
        }
    before = signature(game, card)
    result = game.queue_from_hand(
        ME, card.name, mode_index=index, x_value=x_value, **named,
    )
    if not result.supported:
        return False
    resolve_stack(game)
    if in_response:
        return zones(game, card) != untouched(card, candidate)
    return signature(game, card) != before


# -- measuring a cast -----------------------------------------------------------
#
# The second half of the census: not "is the mode reached" but "is the cast
# the larger one". Every cast here is made **by the engine, on a census
# board** — never by ``ai_valuation.rehearse`` — and priced with the one
# definition of "larger" (``ai_valuation.swing_worth`` over the standing of
# each seat). The policy predicts with that definition; this measures with
# it; a census that asked the scorer whether the scorer was right would
# measure nothing.

#: The game's own fields a cast writes whatever it does (the table is read
#: separately): left out of `table_state`, as `_BOOKKEEPING` is left out of
#: `signature`.
_GAME_BOOKKEEPING = frozenset({
    "players", "log", "stack", "priority_player_index", "priority_pass_count",
    "pending_choices", "damage_ledger",
})
def table_state(game, spell) -> str:
    """`signature` and the game's own records beside it — the Fog a turn is
    under, the extra turn it has been given, the ban a seat is under. For a
    cast compared with the same game a moment earlier."""
    records = sorted(
        (key, repr(value)) for key, value in vars(game).items()
        if key not in _GAME_BOOKKEEPING and repr(value) not in _EMPTY_READINGS
    )
    damage = repr(getattr(getattr(game, "damage_ledger", None), "entries", None))
    # Every field of every permanent, by name: a dataclass's own repr leaves
    # out the ones declared ``repr=False``, and a redirect armed on a creature
    # (Sivvi's Valor) is one of those.
    fields = sorted(
        (perm.permanent_id, sorted(
            (key, repr(value)) for key, value in vars(perm).items() if key != "card"
        ))
        for perm in game.all_permanents()
    )
    return signature(game, spell) + repr(records) + damage + repr(fields)


def pools(game) -> list:
    return [dict(player.mana_pool) for player in game.players]


def mana_made(before: list, game) -> bool:
    """Whether some pool holds more of some mana than it did in *before*
    (`pools`). `table_state` leaves the pools out, because paying for the
    cast empties them whatever the cast does — but paying only ever takes
    mana away, so mana that is *there* afterwards is mana the spell made, and
    a ritual moved something."""
    return any(
        int(now.get(symbol, 0) or 0) > int(was.get(symbol, 0) or 0)
        for was, now in zip(before, pools(game))
        for symbol in now
    )


def fresh(card, built):
    return board(
        card, built["placements"], window=built["window"], grave=built["grave"],
        stack=built["stack"],
    )


def settle(game) -> None:
    """Everything a cast leaves owed: the stack resolved, the prompts it armed
    answered by default, and state-based actions checked (CR 704.3) — a
    creature dealt lethal damage is still on the battlefield until they are,
    and a measure taken before would count it as alive."""
    for _ in range(6):
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        game.check_state_based_actions()
        if not game.stack and not game.pending_choices:
            return


def run_out(game) -> None:
    """The turn run out: a combat whose attack is declared and whose blocks
    nobody is owed deals its damage, then CR 514 — "until end of turn" ends
    and marked damage goes (``ai_valuation.run_out_the_turn``, the reading a
    rehearsal takes). Nothing is declared on the way, so what is read
    afterwards is what the cast left and not what a policy then did with it.

    The damage is part of it because a response is *for* the damage: "prevent
    the next 3 damage" cast under an attack measured nothing while this
    stopped short of the combat it was cast in."""
    settle(game)
    run_out_the_turn(game)
    settle(game)


_BASELINES: dict = {}


def baseline(card, built) -> dict:
    """The board with nothing cast: what is on the stack resolves, the turn
    runs out. Each seat's standing at both moments."""
    key = (
        card.name, repr(built["placements"]), built["window"],
        repr(built["grave"]), built["stack"],
    )
    if key not in _BASELINES:
        game, _ = fresh(card, built)
        settle(game)
        now = standings(game)
        run_out(game)
        _BASELINES[key] = {"now": now, "lasting": standings(game, now=False)}
    return _BASELINES[key]


def weighed(
    card, game, before_cast, moved: bool, untouched_now: tuple,
    untouched_lasting: tuple, *, in_main: bool = True,
) -> "tuple[float, bool]":
    """``(swing, moved)`` for the cast that has just resolved on *game*: what
    it was worth to seat 0, and whether what it moved is **still moved once
    the turn is over**.

    The swing is ``ai_valuation.swing_worth`` of seat 0's standing swing now
    and once the turn has run out, against the same board with nothing cast
    (*untouched_now*, *untouched_lasting*). The spell's own card is not part
    of it.

    **A cast made before the turn's fight is priced with the fight fought**,
    where a reading with no combat in it cannot price it
    (``ai_valuation.priced_by_the_fight``: everything it changed is gone by
    the end of the turn, or more of its good is than is left). Then the
    attack, the blocks and the damage are played on a copy of the board as
    the cast left it and on a copy of it with nothing cast (*before_cast*,
    taken before the cast: ``ai_valuation.scratch_copy``), each run to the
    end of its turn (``ai_valuation.run_out_the_turn``), and the swing is
    between those two — and a cast that has left nothing even then **moved
    nothing**: a pump on a creature that had no fight to decide, a shield
    nothing came for, a Fog over a turn nobody attacked in.

    The fight is the engine's and the policies' that declare it, on real
    copies of a real board; the price is ``ai_valuation``'s standing. Nothing
    here goes through a rehearsal.
    """
    # The spell's own card is not part of what the cast did — unless it is
    # back in the hand it left (buyback), and then nothing was spent.
    spent = CARD_WORTH * (0 if any(held is card for held in game.players[ME].hand) else 1)
    to_come = in_main and combat_is_still_to_come(game, ME)
    spares = (scratch_copy(game), scratch_copy(before_cast)) if to_come else None
    now = standing_swing(untouched_now, standings(game), ME) + spent
    run_out(game)
    lasting = standing_swing(untouched_lasting, standings(game, now=False), ME) + spent
    swing = round(swing_worth(now, lasting), 3)
    # Whether anything it changed is still changed: asked of the same board
    # with nothing cast, run out the same way.
    run_out(before_cast)
    gone = abs(lasting) < 1e-9 and same_position(
        lasting_digest(before_cast), lasting_digest(game),
        spell_name=card.name, caster=ME,
    )
    if spares is None:
        # No fight still to come (a response, a cast in combat): what is gone
        # by the end of the turn moved nothing that lasted.
        return swing, moved and not gone
    if not priced_by_the_fight(now, lasting, gone):
        return swing, moved
    fought, untouched_fought = spares
    # The fight's coin flips are its own: the row that follows this one is
    # not to be cast on whatever randomness a combat here happened to use.
    sequence = random.getstate()
    try:
        run_out_the_turn(untouched_fought, through_combat=True)
        run_out_the_turn(fought, through_combat=True)
    finally:
        random.setstate(sequence)
    left = standing_swing(
        standings(untouched_fought, now=False), standings(fought, now=False), ME
    ) + spent
    still = abs(left) > 1e-9 or not same_position(
        lasting_digest(untouched_fought), lasting_digest(fought),
        spell_name=card.name, caster=ME,
    )
    return round(left, 3), moved and still


def lasting_digest(game) -> dict:
    """``ai_valuation.position_digest`` of a board whose turn has run out,
    without the record of what damage was dealt
    (``ai_valuation.forget_damage_history``) and with the opponent's
    permanents untapped as its untap step will leave them
    (``ai_valuation.untap_for_the_next_turn``) — the rehearsal's own reading:
    the damage and the tap are gone by then, and what they did is on the
    table."""
    forget_damage_history(game)
    untap_for_the_next_turn(game)
    return position_digest(game)


def measured(card, built, game, before_cast, moved: bool) -> "tuple[float, bool]":
    """:func:`weighed` for a cast on a census board built from *built*."""
    untouched_board = baseline(card, built)
    return weighed(
        card, game, before_cast, moved, untouched_board["now"],
        untouched_board["lasting"], in_main=built["window"] is None,
    )


def announcements(card, index, built, x_value) -> list:
    """Every announcement mode *index* may make on *built*'s board, off the
    engine's own picker and nothing else: each player, each permanent, the
    spell on the stack, or nothing at all. Empty for a mode whose targets are
    announced as a chain of roles — the census has no enumeration of those,
    and the mode is measured as the policy announces it."""
    game, _ = fresh(card, built)
    shape = mode_shape(card, index)
    named = {"mode_index": index, "x_value": x_value}
    if shape == "untargeted":
        return [{**named, "target_player_index": ME}]
    if shape == "stack":
        return [{**named, "target_stack_index": len(game.stack) - 1}]
    if shape == "roles":
        return []
    listed = game.cast_target_spec(ME, card, mode_index=index).get("valid_targets") or []
    found: list = []
    seats: list = []
    for entry in listed:
        seat = entry.get("seat")
        if entry.get("kind") == "permanent":
            # By slot here and by id at the cast (`cast_by_hand`): every
            # census board is built afresh, and an id is one board's.
            found.append({**named, "bait": (seat, entry["index"])})
        elif isinstance(seat, int) and seat not in seats:
            seats.append(seat)
    return [{**named, "target_player_index": seat} for seat in seats] + found


def cast_by_hand(card, built, announcement) -> "dict | None":
    """One announcement made on a fresh census board: what it measured and
    whether it moved anything — or None when the engine refuses it."""
    game, _ = fresh(card, built)
    before = table_state(game, card)
    before_cast = scratch_copy(game)
    keywords = dict(announcement)
    if "bait" in keywords:
        seat, slot = keywords.pop("bait")
        keywords["target_player_index"] = seat
        keywords["target_permanent_ids"] = [
            game.permanent_id_of(game.permanent_at(seat, slot))
        ]
    try:
        result = game.queue_from_hand(ME, card.name, **keywords)
        if not result.supported:
            return None
        settle(game)
    except Exception:
        return None
    moved = (
        zones(game, card) != untouched(card, built) if built["window"] == "stack"
        else table_state(game, card) != before
    )
    swing, moved = measured(card, built, game, before_cast, moved)
    return {"swing": swing, "moved": moved, "named": announcement}


def best_announcement(card, index, built, x_value) -> "dict | None":
    """The most mode *index* can be measured to do on *built*'s board, over
    every announcement the engine's picker offers it."""
    best = None
    for announcement in announcements(card, index, built, x_value):
        got = cast_by_hand(card, built, announcement)
        if got is not None and (best is None or got["swing"] > best["swing"]):
            best = got
    return best


def does_something(card, index, candidate) -> "float | None":
    """What an untargeted or player-aimed mode measures on the candidate
    board when it has something to act on there — some announcement of it
    moves the table and leaves its caster no worse off — and None when it has
    not. The engine's answer, with no policy in it."""
    x_value = 2 if "{X}" in (card.mana_cost or "").upper() else None
    measures = [
        got["swing"]
        for got in (
            cast_by_hand(card, candidate, announcement)
            for announcement in announcements(card, index, candidate, x_value)
        )
        if got is not None and got["moved"] and got["swing"] >= 0
    ]
    return max(measures) if measures else None


def plan(card, index) -> dict:
    """The board for one mode: ``placements``, ``window``, ``grave``, ``stack``
    -- or ``{"unbuildable": reason}``."""
    program = compile_card_oracle(card)
    shape = mode_shape(card, index)
    side = mode_side(card, index)
    seat = wanted_seat(side)
    instant = card.primary_type == "instant"
    base = {"placements": [], "window": None, "grave": [], "stack": None}

    if shape in ("untargeted", "player"):
        # The empty board, when the mode does anything there (three damage to
        # a player, three cards drawn) — and otherwise the first board with
        # one census permanent on it where it does: "All creatures get -1/-1"
        # wants a creature to shrink, and one that is not its caster's. A
        # seat does not cast a spell that changes nothing, so a board on
        # which the mode has nothing to act on is not a board for it.
        candidates = [dict(base)]
        if does_something(card, index, candidates[0]) is None:
            candidates = [
                {**base, "placements": [(holder, key)], "window": window}
                for window in ((None, "combat", "attack") if instant else (None,))
                for holder in (
                    (OPP,) if window == "combat" else (ME,) if window == "attack"
                    else (OPP, ME)
                )
                for key in ZOO
            ] + [
                {**base, "grave": [(holder, key)]}
                for holder in (OPP, ME) for key in GRAVE
            ]
            measured = [(does_something(card, index, c), c) for c in candidates]
            # The boards it does its caster some good on, when there are any:
            # "All creatures get -2/-0" moves a Wall's power from nought to
            # nought, and that is not the board to judge the bullet on.
            helped = [c for swing, c in measured if swing is not None and swing > 0]
            candidates = helped or [c for swing, c in measured if swing is not None]
            if not candidates:
                return {"unbuildable": "it has nothing to act on on any census board"}
    elif shape == "stack":
        if not instant:
            return {"unbuildable": "a sorcery cannot be cast with a spell on the stack"}
        candidates = []
        for key in SPELLS:
            game, _ = board(card, window="stack", stack=key)
            if index in game.announceable_modes(ME, card):
                candidates.append({**base, "window": "stack", "stack": key})
        if not candidates:
            return {"unbuildable": "no census spell on the stack is a legal target"}
        # "Counter target spell if it's red" may be announced at any spell;
        # the census wants the one it counters.
        candidates = [c for c in candidates if mode_acts_on(card, index, c)] or candidates
    elif shape == "graveyard":
        candidates = []
        # Whose pile the bait goes in, the way the permanent branch below
        # places its own: on the side the mode's effect wants. Only a
        # graveyard *exile* has one — "Exile up to three target cards from a
        # single graveyard" (Ebony Charm) is a denial, announced since
        # Odyssey's second wave, and a bait in the caster's own pile is a
        # board the mode is rightly not cast on. A return names cards in the
        # pile its phrase prints, and keeps both.
        denies = set(several_target_slot_sides(
            program, (program.modes[index].instruction,)
        )) == {"opponent"}
        for owner in ((OPP,) if denies else (ME, OPP)):
            for key in GRAVE:
                game, _ = board(card, grave=[(owner, key)])
                if index in game.announceable_modes(ME, card):
                    candidates.append({**base, "grave": [(owner, key)]})
        if not candidates:
            return {"unbuildable": "no census graveyard card is a legal target"}
    elif shape == "roles":
        candidates = []
        keys = list(ZOO)
        for first in keys:
            for second in keys:
                if first == second:
                    continue
                placements = [(seat, first), (seat, second)]
                game, _ = board(card, placements)
                if index in game.announceable_modes(ME, card):
                    candidates.append({**base, "placements": placements})
        if not candidates:
            return {"unbuildable": "no pair of census permanents fills its roles"}
    else:
        window = None
        keys = _zoo_keys_legal(card, index, seat)
        if not keys and instant:
            window = "combat"
            seat = OPP
            keys = _zoo_keys_legal(card, index, seat, window="combat")
        if not keys:
            return {"unbuildable": "no census permanent is a legal target on the side it wants"}
        candidates = [
            {**base, "placements": [(seat, key)], "window": window} for key in keys
        ]
        # ...and of those, the baits this mode *does something to*: "Destroy
        # target permanent if it's blue" may legally name any permanent and
        # touches only a blue one. Judged by the engine — the mode cast at
        # that bait, resolved, and the board compared — never by the policy
        # under test.
        acted_on = [
            candidate for candidate in candidates
            if mode_acts_on(card, index, candidate)
        ]
        candidates = acted_on or candidates

    def shadows(candidate) -> dict:
        game, _ = board(
            card, candidate["placements"], window=candidate["window"],
            grave=candidate["grave"], stack=candidate["stack"],
        )
        return {
            other: reason
            for other in range(len(program.modes))
            if other != index
            and (reason := worth_casting(game, card, other)) is not None
        }

    def announceable(candidate) -> bool:
        game, _ = board(
            card, candidate["placements"], window=candidate["window"],
            grave=candidate["grave"], stack=candidate["stack"],
        )
        return index in game.announceable_modes(ME, card)

    candidates = [c for c in candidates if announceable(c)]
    if not candidates:
        return {"unbuildable": "the engine offers this mode on no census board"}
    chosen = min(candidates, key=lambda c: len(shadows(c)))
    chosen = dict(chosen)
    # Decoys: for every other object mode with a side, something it could
    # target on the side it does not want -- kept only while it makes no other
    # mode worth casting.
    before = shadows(chosen)
    for other in range(len(program.modes)):
        if other == index or mode_shape(card, other) != "object":
            continue
        other_side = mode_side(card, other)
        if other_side is None:
            continue
        wrong = ME if other_side == "opponent" else OPP
        for key in _zoo_keys_legal(
            card, other, wrong, window=chosen["window"], grave=chosen["grave"],
            stack=chosen["stack"],
        ):
            if (wrong, key) in chosen["placements"]:
                break
            trial = {**chosen, "placements": [*chosen["placements"], (wrong, key)]}
            if (
                shadows(trial) == before and announceable(trial)
                # ...and while it leaves this mode something to do: a decoy
                # that turns "all creatures get -2/-0" on its own caster has
                # changed the question.
                and (
                    shape not in ("untargeted", "player")
                    or does_something(card, index, trial) is not None
                )
            ):
                chosen = trial
                break
    chosen["shadowed_by"] = before
    chosen["shape"] = shape
    chosen["side"] = side
    return chosen


# -- running a board ------------------------------------------------------------

#: What every cast changes whatever it does: the zones the spell itself moves
#: through, the mana that paid for it and the turn's record of spells cast.
#: Left in, a resolution that did nothing still read as a change.
_BOOKKEEPING = frozenset({
    "hand", "graveyard", "library", "mana_pool", "battlefield",
    "spells_cast_this_turn",
})


#: How a field nothing has used reads once something has emptied it.
_EMPTY_READINGS = frozenset({"None", "False", "0", "''", "[]", "()", "{}", "set()"})


def signature(game, spell) -> str:
    """Everything a resolution could have changed, with the spell's own trip
    from hand to graveyard taken out."""
    parts = []
    for seat, player in enumerate(game.players):
        hand = sorted(c.name for c in player.hand)
        yard = sorted(c.name for c in player.graveyard)
        if seat == ME:
            for pile in (hand, yard):
                if spell.name in pile:
                    pile.remove(spell.name)
        # Less the bookkeeping, and less every field that reads as empty: a
        # record the engine creates on first use (`_land_mana_swaps`, made
        # by the tap planner) is otherwise a "change" every cast makes, and
        # a resolution that did nothing read as one that did.
        rest = {
            key: value for key, value in vars(player).items()
            if key not in _BOOKKEEPING and repr(value) not in _EMPTY_READINGS
        }
        parts.append((hand, yard, len(player.library), repr(sorted(rest.items(), key=lambda kv: kv[0]))))
        parts.append(sorted(
            (perm.permanent_id, repr(perm), perm.is_creature and perm.effective_power,
             perm.is_creature and perm.effective_toughness)
            for perm in player.battlefield
        ))
    parts.append(len(getattr(game, "delayed_triggers", ()) or ()))
    return repr(parts)


def proposed_modes(action) -> "list | None":
    """The modes a proposal names -- ``[0]`` for one that names none, which is
    what the engine resolves such a cast as; several for a "choose one or
    more" announcement."""
    if action is None:
        return None
    choices = getattr(action, "mode_choices", None)
    if choices:
        return sorted(choice.get("index") for choice in choices)
    named = getattr(action, "mode_index", None)
    return [0 if named is None else named]


def run(card, index, built, *, forced: bool) -> dict:
    """One leg on one board: what was proposed, what the cast announced, and
    whether it was accepted and did anything."""
    window = built["window"]
    chooser = choose_cast_action if window is None else choose_combat_instant_cast_action

    def fresh():
        game, placed = board(
            card, built["placements"], window=window, grave=built["grave"],
            stack=built["stack"],
        )
        # "Untap target permanent" (Emerald Charm's first bullet) has to find
        # something tapped, or it resolves changing nothing — and the board
        # already holds it: the plan places a **tapped** bait (`place`), which
        # is the one every other reader of this board (`baseline`,
        # `cast_by_hand`) measures against. Two rounds each gave the bullet its
        # tapped permanent on the same day; the other one tapped *every* bait
        # here, in this leg alone, so the policy's cast was priced on a board
        # two tapped permanents poorer than the one its rivals were cast on
        # and read as the smaller cast (0.275 beside 1.525, for the same untap
        # of the same permanent). One board, built one way.
        return game, placed

    def only_this_mode(self, caster_index, asked, **kwargs):
        offered = real(self, caster_index, asked, **kwargs)
        return [index] if asked.name == card.name and index in offered else (
            offered if asked.name != card.name else []
        )

    real = Game.announceable_modes
    patches = []
    if forced:
        patches.append(mock.patch.object(Game, "announceable_modes", only_this_mode))
    announced: list = []
    real_cast = Game._cast_onto_stack

    def spy(self, caster_index, card_name, *args, **kwargs):
        if caster_index == ME and card_name == card.name:
            choices = kwargs.get("mode_choices")
            named = kwargs.get("mode_index")
            announced.append(
                sorted(c.get("index") for c in choices) if choices
                else [0 if named is None else named]
            )
        return real_cast(self, caster_index, card_name, *args, **kwargs)

    patches.append(mock.patch.object(Game, "_cast_onto_stack", spy))
    outcome = {"proposed": None, "announced": None, "accepted": None, "changed": None, "error": None}
    for patch in patches:
        patch.start()
    try:
        game, _ = fresh()
        action = chooser(game, ME)
        if action is not None and action.card_name != card.name:
            action = None
        outcome["proposed"] = proposed_modes(action)
        outcome["score"] = None if action is None else round(action.score, 3)
        if action is None:
            return outcome
        outcome["x_value"] = action.x_value
        game, _ = fresh()
        before = signature(game, card)
        state_before = table_state(game, card)
        before_cast = scratch_copy(game)
        if window is None:
            report = ai_simulator.SimulationReport(
                games_requested=1, games_completed=0, interaction_count=0,
            )
            cast = ai_simulator._play_one_cast(game, ME, report, 1, 1)
            outcome["accepted"] = bool(cast) and not report.refused_casts
            if report.refused_casts:
                outcome["error"] = "; ".join(report.refused_casts)
            if report.issues:
                outcome["error"] = "; ".join(issue.message for issue in report.issues)
        else:
            # The web AI's window: the executor there needs a session, and is
            # driven by tests/ui; here the announcement is made the way it is.
            from engine.ai_policy import spell_being_cast, tap_planned_lands

            action = chooser(game, ME)
            spell = spell_being_cast(game.players[ME].hand, action)
            tap_planned_lands(game, ME, action)
            if hasattr(sys.modules["engine.ai_policy"], "cast_announcement"):
                keywords = sys.modules["engine.ai_policy"].cast_announcement(action)
            else:
                keywords = dict(
                    target_player_index=action.target_player_index,
                    target_permanent_index=action.target_permanent_index,
                    target_permanent_ids=action.target_permanent_ids,
                    x_value=action.x_value,
                    divided_targets=action.divided_targets,
                )
            result = game.queue_from_hand(ME, spell.name, **keywords)
            outcome["accepted"] = bool(result.supported)
            if not result.supported:
                outcome["error"] = result.details
            else:
                resolve_stack(game)
        outcome["announced"] = announced[-1] if announced else None
        # In response to a spell, "did something" is measured against the same
        # board with nothing cast: the opposing spell resolving is a change
        # whatever the answer to it did.
        outcome["changed"] = (
            zones(game, card) != untouched(card, built) if window == "stack"
            else signature(game, card) != before
        )
        if outcome["accepted"]:
            # ...and what the cast was worth, and whether it moved anything
            # at all — the game's own records counted (`table_state`).
            settle(game)
            outcome["swing"], outcome["moved"] = measured(
                card, built, game, before_cast,
                outcome["changed"] if window == "stack"
                else table_state(game, card) != state_before,
            )
    except Exception as exc:  # a crash is a finding, not a pass
        outcome["error"] = f"EXC {type(exc).__name__}: {exc}"
    finally:
        for patch in patches:
            patch.stop()
    return outcome


def census() -> dict:
    rows = []
    for card in population():
        program = compile_card_oracle(card)
        for index, mode in enumerate(program.modes):
            row = {
                "card": card.name, "mode": index, "label": mode.label,
                "supported": bool(mode.supported),
            }
            rows.append(row)
            if not mode.supported:
                row["unbuildable"] = "the mode is unsupported"
                continue
            built = plan(card, index)
            if "unbuildable" in built:
                row["unbuildable"] = built["unbuildable"]
                continue
            row.update(
                shape=built["shape"], side=built["side"],
                placements=built["placements"], window=built["window"],
                grave=built["grave"], stack=built["stack"],
                shadowed_by=built["shadowed_by"],
            )
            row["natural"] = run(card, index, built, forced=False)
            row["forced"] = run(card, index, built, forced=True)
            row["bests"] = bests(card, index, built, row)
    return {"rows": rows}


def bests(card, index, built, row) -> dict:
    """For this mode and every sibling its board leaves worth casting: the
    most each can be measured to do there (`best_announcement`), or None for
    a mode the census cannot enumerate (a chain of roles) — which, when it is
    the row's own, is measured as the forced leg cast it."""
    x_value = next(
        (
            row[leg].get("x_value") for leg in ("natural", "forced")
            if row[leg].get("x_value") is not None
        ),
        2 if "{X}" in (card.mana_cost or "").upper() else None,
    )
    found: dict = {}
    for mode in sorted({index, *built["shadowed_by"]}):
        best = best_announcement(card, mode, built, x_value)
        if best is None and mode == index and row["forced"].get("swing") is not None:
            best = {
                "swing": row["forced"]["swing"],
                "moved": bool(row["forced"].get("moved")),
                "named": "as the policy announces it",
            }
        found[mode] = best
    return found


#: Two measures this close are the same measure.
EPSILON = 0.01


def larger(row: dict) -> "str | None":
    """Why the cast the policy made on this row's board is **not** the larger
    one, or None when it is: some bullet, at some target the engine's picker
    offers, measures more than what was cast — or the seat cast nothing while
    a bullet measured more than nothing."""
    moving = {
        mode: best for mode, best in row["bests"].items()
        if best is not None and best["moved"]
    }
    if not moving:
        return None
    top_mode = max(moving, key=lambda mode: (moving[mode]["swing"], -mode))
    top = moving[top_mode]
    got = row["natural"]
    if got["proposed"] is None:
        if top["swing"] > EPSILON:
            return f"nothing cast; mode {top_mode} measures {top['swing']}"
        return None
    if not got.get("accepted") or got.get("swing") is None:
        return None
    if got["swing"] + EPSILON < top["swing"]:
        return (
            f"cast mode {got['proposed']} for {got['swing']}; mode {top_mode} "
            f"measures {top['swing']} ({top['named']})"
        )
    if not got.get("moved"):
        return f"cast mode {got['proposed']}, which moved nothing; mode {top_mode} does"
    return None


def rightly_held(row: dict, leg: str) -> bool:
    """Whether *leg* cast nothing on this row's board **and was right to**:
    the mode, cast by hand at every target the engine's picker offers it
    there, moves nothing that is still moved once the turn is over
    (``weighed``) — "gains haste until end of turn" on a creature that could
    attack anyway, a shield with no damage coming. Holding the card for a
    board on which it does something is the play; casting it was the defect.
    """
    best = row["bests"].get(row["mode"])
    return row[leg]["proposed"] is None and best is not None and not best["moved"]


def findings(result: dict) -> dict:
    """The census read as failures, by leg."""
    out: dict = {
        "unbuildable": [], "natural": [], "forced": [], "shadowed": [], "smaller": [],
    }
    for row in result["rows"]:
        tag = f"{row['card']} [{row['mode']}] {row['label'][:48]!r}"
        if "unbuildable" in row:
            out["unbuildable"].append((tag, row["unbuildable"]))
            continue
        why = larger(row)
        if why is not None:
            out["smaller"].append((tag, why))
        for leg in ("natural", "forced"):
            got = row[leg]
            exclusive = leg == "forced" or not row["shadowed_by"]
            problems = []
            if got["error"]:
                problems.append(got["error"])
            named = got["proposed"]
            if named is None or row["mode"] not in named:
                if exclusive and not rightly_held(row, leg):
                    problems.append(f"proposed {named}")
            else:
                if got["announced"] != named:
                    problems.append(f"the cast announced {got['announced']}")
                if not got["accepted"]:
                    problems.append("the cast was refused")
                elif not got.get("moved"):
                    problems.append("the resolution moved nothing")
            if named is not None and not exclusive:
                strays = [m for m in named if m != row["mode"] and m not in row["shadowed_by"]]
                if strays:
                    problems.append(
                        f"proposed {named}: {strays} the board does not make worth casting"
                    )
                elif row["mode"] not in named:
                    measured = {
                        m: best and best["swing"] for m, best in row["bests"].items()
                    }
                    out["shadowed"].append((tag, "; ".join(
                        f"mode {m} proposed ({row['shadowed_by'][m]})" for m in named
                    ) + f", measuring {got.get('swing')}; the modes measure {measured}"))
            # A shadowed board on which nothing is cast is `larger`'s to
            # judge: holding the card is right when no bullet measures more
            # than nothing.
            if problems:
                out[leg].append((tag, "; ".join(problems)))
    return out


def hit(row: dict, leg: str) -> bool:
    """Whether *leg* proposed this row's own mode."""
    return row["mode"] in (row[leg]["proposed"] or ())


def counts(result: dict) -> dict:
    rows = result["rows"]
    built = [row for row in rows if "unbuildable" not in row]
    exclusive = [row for row in built if not row["shadowed_by"]]
    return {
        "cards": len({row["card"] for row in rows}),
        "modes": len(rows),
        "boards_built": len(built),
        "exclusive_boards": len(exclusive),
        "shadowed_boards": len(built) - len(exclusive),
        "natural_proposed_as_mode": sum(
            1 for row in built if hit(row, "natural")
        ),
        "natural_exclusive_proposed_as_mode": sum(
            1 for row in exclusive if hit(row, "natural")
        ),
        "forced_proposed_as_mode": sum(
            1 for row in built if hit(row, "forced")
        ),
        "forced_cast_accepted_in_mode": sum(
            1 for row in built
            if hit(row, "forced")
            and row["forced"]["accepted"] and row["forced"]["announced"] == [row["mode"]]
        ),
        "modes_reached": sum(
            1 for row in built
            if hit(row, "natural")
            or hit(row, "forced")
        ),
        "nonzero_modes_reached": sum(
            1 for row in built
            if row["mode"] != 0 and (
                hit(row, "natural")
                or hit(row, "forced")
            )
        ),
        "proposals_by_natural_mode": dict(sorted(Counter(
            str(row["natural"]["proposed"]) for row in built
        ).items())),
    }



# -- the tests ----------------------------------------------------------------

#: Modes the census cannot build a board for, each with why. Named rather than
#: skipped: a sweep that silently drops what it cannot reach reports a smaller
#: pool as a clean one.
UNBUILDABLE = {
    # "Counter target activated or triggered ability": the census puts spells
    # on the stack, not abilities. The mode is announceable only in response
    # to one, which is `choose_combat_instant_cast_action`'s window.
    ("Sublime Epiphany", 1): "no census spell on the stack is a legal target",
    # "Creatures without flying can't block this turn" and "each land of the
    # first chosen type becomes the second until end of turn": everything
    # either does is over with the turn, and what it is *for* is a fight —
    # an attacker with a blocker in front of it. A census board is one
    # permanent; none of them is that fight. Each had a board while a cast
    # was priced with the turn's combat left out, on which it "did something"
    # that was gone by cleanup.
    ("Destructive Tampering", 1): "it has nothing to act on on any census board",
    ("Vision Charm", 1): "it has nothing to act on on any census board",
}

#: Modes with a board on which **nothing is cast**, each with why: the mode's
#: whole effect is over with the turn, and on its census board — one bait, in
#: the caster's own main phase — it decides no fight. The census's own cast of
#: each, with the turn's combat fought, leaves nothing behind (`rightly_held`),
#: which is what makes this a list of right answers rather than of misses.
#:
#: Every one was proposed until the policy weighed a precombat cast through
#: the fight (``ai_policy._weighed_through_the_fight``): cast, at
#: ``SPELL_BASE_SCORE`` and a quarter of whatever it lent, on the first main
#: phase it was castable in. Named, because a sweep that silently drops what
#: it does not reach reports a smaller pool as a clean one: these twelve are
#: reached only where there is a fight for them to decide, and the fight
#: boards are ``tests/ai/test_ai_precombat_tricks.py``'s.
_NO_FIGHT = "for a turn, on a creature with no fight to decide"
HELD = {
    # "Chaos Charm deals 1 damage to target creature", at a creature it does
    # not kill: the damage is gone at cleanup (CR 514.2), and was a change
    # that lasted only while the turn's record of who dealt what was read
    # as one (``ai_valuation.forget_damage_history``).
    ("Chaos Charm", 1): "1 damage to a creature it does not kill, with no fight to finish it",
    ("Chaos Charm", 2): "haste " + _NO_FIGHT + " and no summoning sickness to lift",
    ("Ebony Charm", 2): "fear " + _NO_FIGHT,
    ("Emerald Charm", 2): "an opposing flyer grounded for a turn it was not blocking in",
    ("Funeral Charm", 2): "swampwalk " + _NO_FIGHT,
    ("Hearth Charm", 2): "unblockable " + _NO_FIGHT,
    ("Hope Charm", 0): "first strike " + _NO_FIGHT,
    # "Tap target creature": on a board with no attack to clear a blocker
    # for, the creature untaps in its controller's untap step (CR 502.3)
    # having done nothing it would not have done untapped
    # (``ai_valuation.untap_for_the_next_turn``).
    ("Ivory Charm", 1): "a tap of a creature with no attack to stop, undone at its untap step",
    ("Rith's Charm", 2): "a shield against a source with no damage coming",
    ("Sapphire Charm", 1): "flying " + _NO_FIGHT,
    ("Seedling Charm", 1): "a regeneration shield with nothing to survive",
    ("Seedling Charm", 2): "trample " + _NO_FIGHT,
}

#: Modes whose own board leaves a sibling worth casting too, and the sibling
#: the policy takes there: ``(card, mode) -> (the modes proposed instead,
#: why)``.
#:
#: **Every one of these loses to a bullet that measures at least as much** —
#: `test_the_cast_made_is_never_the_smaller_one` is what holds that, on the
#: engine's own casts — and the reason beside each is that measurement in a
#: line. Two are ties, which printed order breaks.
#:
#: This table was 25 entries pinned without reasons, six of them the scorer's
#: text probes showing through: Crosis's Charm bounced a creature it could
#: destroy, Treva's Charm looted rather than destroy an enchantment or exile
#: an attacker ("draw" in a bullet's text scored as a card gained), Dromar's
#: Charm gained five life at twenty rather than give -2/-2, Hearth Charm
#: pumped attackers that were not attacking and Ivory Charm shrank creatures
#: in its own main phase. The policy now measures a cast before it proposes
#: one (``ai_valuation.rehearse``); those six are gone, and so are Thunderbolt
#: and Sapphire Charm's two, which were never named and lost the same way.
#:
#: A change to a weight in ``ai_valuation`` moves an entry here, and moving
#: it is the review.
SHADOWED = {
    ("Alabaster Potion", 1): ([0], "X life lasts; a shield with no damage coming measures nothing"),
    ("Darigaaz's Charm", 0): ([1], "three damage kills the 2/2 across the table: a creature against a card back"),
    ("Darigaaz's Charm", 2): ([1], "three damage lasts; +3/+3 until end of turn is a quarter of itself"),
    ("Ebony Charm", 1): ([0], "a life drained each way; cards exiled from a graveyard are nothing the standing counts"),
    ("Ebony Charm", 2): ([0], "a life drained each way against fear for a turn"),
    ("Energy Bolt", 1): ([0], "X damage to the opponent against X life at twenty"),
    ("Funeral Charm", 1): ([0], "a card out of the opposing hand against +2/-1 for a turn"),
    ("Funeral Charm", 2): ([0], "a card out of the opposing hand against swampwalk for a turn"),
    ("Healing Salve", 1): ([0], "three life lasts; a shield with no damage coming measures nothing"),
    ("Hope Charm", 0): ([1], "two life against first strike for a turn"),
    ("Ivory Charm", 2): ([0], "under an attack, -2/-0 on the attacker stops two damage and the shield one"),
    ("Parch", 1): ([0], "a tie: either bullet kills the 1/1, and printed order breaks it"),
    ("Read the Tides", 1): ([0], "three cards against one creature back in a hand"),
    ("Rith's Charm", 0): ([1], "three Saprolings against one land"),
    ("Rith's Charm", 2): ([1], "three Saprolings against a shield with no damage coming"),
    ("Sapphire Charm", 1): ([0], "a card next upkeep is still coming at the end of the turn; flying with nothing to fly over is not"),
}

#: Boards on which the cast the policy made measures **less** than some
#: bullet, at some target, that the engine's picker offers — or on which it
#: cast nothing while a bullet measured more than nothing. Each with why it
#: stands. Empty: on the tree before the policy measured a cast it was 19.
SMALLER: dict = {}


@pytest.fixture(scope="module")
def result() -> dict:
    return census()


def test_the_census_examined_the_pool(result):
    """The floor: a sweep that reaches nothing passes everything."""
    counted = counts(result)
    assert counted["cards"] >= 34
    assert counted["modes"] >= 88
    assert counted["boards_built"] >= 85
    assert counted["exclusive_boards"] >= 40
    # ...and that the measuring leg measured: every board has a best cast to
    # compare with, and the sibling of every shadowed mode was cast by hand.
    built = [row for row in result["rows"] if "unbuildable" not in row]
    assert all(row["bests"].get(row["mode"]) is not None for row in built)
    measured = sum(
        1 for row in built for best in row["bests"].values() if best is not None
    )
    assert measured >= 135, measured


def test_the_modes_with_no_board_are_the_named_ones(result):
    unbuildable = {
        (row["card"], row["mode"]): row["unbuildable"]
        for row in result["rows"] if "unbuildable" in row
    }
    assert unbuildable == UNBUILDABLE


def test_a_mode_that_is_the_only_one_worth_casting_is_the_one_cast(result):
    """The natural leg. Before the chooser: 16 of these 41 (the first
    bullets), and for the other 25 either mode 0 aimed at whatever the board
    held or no cast at all."""
    found = findings(result)
    assert found["natural"] == [], "\n".join(
        f"{tag}: {what}" for tag, what in found["natural"]
    )
    counted = counts(result)
    held = sum(
        1 for row in result["rows"]
        if "unbuildable" not in row and not row["shadowed_by"]
        and rightly_held(row, "natural")
    )
    assert (
        counted["natural_exclusive_proposed_as_mode"]
        == counted["exclusive_boards"] - held
    )
    assert counted["natural_exclusive_proposed_as_mode"] >= 36


def test_every_mode_is_within_reach(result):
    """The forced leg: offered alone, every mode with a board is proposed,
    announced as itself through the simulator's own executor, accepted by the
    cast gates, and resolves doing something. Before the chooser: the first
    bullets, 30 of 87, and no other."""
    found = findings(result)
    assert found["forced"] == [], "\n".join(
        f"{tag}: {what}" for tag, what in found["forced"]
    )
    counted = counts(result)
    assert (
        counted["forced_cast_accepted_in_mode"]
        == counted["boards_built"] - len(HELD)
    )
    assert counted["forced_cast_accepted_in_mode"] >= 73
    assert counted["nonzero_modes_reached"] >= 40


def test_the_modes_held_on_their_board_are_the_named_ones(result):
    """A mode offered alone and not proposed is in ``HELD`` — and is there
    because its own cast, made by hand with the turn's fight fought, leaves
    nothing behind. A new entry is a mode that stopped being reached; a
    missing one is a pin gone stale."""
    held = {
        (row["card"], row["mode"]) for row in result["rows"]
        if "unbuildable" not in row and rightly_held(row, "forced")
    }
    assert held == set(HELD), sorted(held ^ set(HELD))
    assert all(HELD.values()), "a pin is a reason"


def test_where_a_sibling_wins_it_is_the_pinned_one(result):
    """The valuation, as a ratchet both ways: a new entry is a mode that
    stopped being chosen on its own board, a missing one is a pin gone
    stale."""
    shadowed = {}
    for row in result["rows"]:
        if "unbuildable" in row or not row["shadowed_by"]:
            continue
        named = row["natural"]["proposed"]
        if named is not None and row["mode"] not in named:
            shadowed[(row["card"], row["mode"])] = named
    assert shadowed == {key: named for key, (named, _why) in SHADOWED.items()}
    assert all(why for _named, why in SHADOWED.values()), "a pin is a reason"


def test_the_cast_made_is_never_the_smaller_one(result):
    """**Which bullet, and at which target.** On every board the census
    builds, every bullet worth casting is cast by hand at every target the
    engine's picker offers it, and each cast is priced with the one
    definition of "larger" (``ai_valuation.swing_worth`` over each seat's
    standing, read as the board stood and again once the turn had run out).
    The cast the policy makes — through the simulator's own executor — must
    measure as much as the best of them, and must move something if any of
    them does.

    Validated backwards: on the tree before the policy measured a cast, 19
    boards fail it, the six named above among them (Crosis's Charm cast for
    5.0 where its second bullet measures 9.0; Treva's Charm for nothing where
    its first measures 4.0 and its second 9.0; Hearth Charm "cast mode [1],
    which moved nothing").
    """
    found = dict(findings(result)["smaller"])
    labels = {(row["card"], row["mode"]): row["label"] for row in result["rows"]}
    pinned = {
        f"{card} [{mode}] {labels[(card, mode)][:48]!r}": why
        for (card, mode), why in SMALLER.items()
    }
    assert set(found) == set(pinned), "\n".join(
        f"{tag}: {what}" for tag, what in sorted(found.items())
        if tag not in pinned
    )


if __name__ == "__main__":
    result = census()
    verbose = "-v" in sys.argv
    for row in result["rows"]:
        if "unbuildable" in row:
            print(f"-- {row['card']} [{row['mode']}] UNBUILDABLE: {row['unbuildable']}")
            continue
        natural, forced = row["natural"], row["forced"]
        print(
            f"{row['card']} [{row['mode']}] {row['shape']}/{row['side']} "
            f"board={row['placements']} win={row['window']} grave={row['grave']} stack={row['stack']} "
            f"shadow={row['shadowed_by']} | natural: mode={natural['proposed']} score={natural.get('score')} "
            f"ann={natural['announced']} ok={natural['accepted']} chg={natural['changed']} err={natural['error']} "
            f"| forced: mode={forced['proposed']} score={forced.get('score')} ann={forced['announced']} "
            f"ok={forced['accepted']} chg={forced['changed']} err={forced['error']} "
            f"| measured: natural={natural.get('swing')} forced={forced.get('swing')} "
            f"bests={ {m: b and (b['swing'], b['moved']) for m, b in row['bests'].items()} }"
        )
    found = findings(result)
    for leg in ("unbuildable", "natural", "forced", "shadowed", "smaller"):
        print(f"== {leg}: {len(found[leg])}")
        for tag, what in found[leg]:
            print(f"   {tag}: {what}")
    print("counts:", counts(result))
