"""Census: is a spell whose good is this turn's fight cast before that fight —
and only where it changes it?

The policy rehearses a candidate cast on a copy of the game and reads the copy
again at the end of the turn. A rehearsal declared nothing on the way, so what
a cast made in its caster's precombat main phase did **to the combat after
it** was not in the price: a Giant Growth was a quarter of the body it lent
whether or not the creature then attacked, a Fog in the caster's own main
phase "changed" a turn flag and stopped only its caster's own attack, and
Hatred was the life it cost. ``ai_policy._weighed_through_the_fight`` reads
such a cast a second time with the turn's combat fought.

**The population** is every supported instant and sorcery — each mode of a
caster-chosen modal one offered alone — some cast of which, made by hand on
the ``rival`` board below, is **priced by the fight**: everything it changed
is gone once the turn has run out with no combat fought, or more of its good
is than is left. A pump, a shrink, an evasion ability or a shield for the
turn, "can't block", a tap, a Fog, a theft until end of turn, Hatred. A
removal spell, a draw, a discard leave what they leave and are not in it; a
ritual, whose mana is gone because it is spent, is not either.

**The boards** are the caster's own turn with one creature each way, built
for no card: ``open`` (nothing in front of the attacker), ``rival`` (a 2/2
across the table), ``wall`` (a 0/4 Wall), ``lethal`` (nothing in front, the
opponent at five), ``sick`` (the attacker came in this turn), ``bare``
(nobody), and ``after`` (``rival`` once the turn's combat is over).

**The measure** is the engine's and the attack and block policies', on real
boards, never a rehearsal: every announcement the engine's picker offers is
cast by hand (``queue_from_hand``) on a copy of the board, and the copy and a
copy with nothing cast are each run to the end of the turn — through the
turn's combat (``ai_combat.run_ai_combat_phase``) where the cast is priced by
the fight — and priced with ``ai_valuation``'s standing. The policy's own
proposal (``choose_cast_action``, the card alone in hand) is cast and measured
the same way.

Five findings, by board:

``held``
    some cast by hand leaves the caster at least ``WIN`` better off once the
    fight is fought, and the policy proposes nothing (Hatred with lethal on
    the table);
``idle``
    the policy's cast leaves nothing behind once the fight is fought (a pump
    on a creature that cannot attack, flying with nothing to fly over);
``loss``
    the policy's cast leaves its caster worse off (a Fog over its own attack);
``smaller``
    the policy's cast measures less than the best one by hand ("can't block"
    on the caster's own creature);
``priced``
    the score the policy proposed the cast at is not what the cast measures
    (``SPELL_BASE_SCORE`` plus its swing): a pump scored at a quarter of its
    body, which puts three damage through.

**Validated backwards**, the whole pool (229 ``(card, mode)``s of 223 cards,
seven boards each), on ``e67196d6``, where a rehearsal fought no combat:
**716 idle, 34 losses, 514 mispriced, 9 held, 9 smaller**. A seat proposed
the trick on 226 of the 227 ``after`` boards and 228 of the 229 ``sick``
ones; Fog was a loss on ``open`` and ``lethal`` (its caster's own attack
stopped) and idle on four boards; Giant Growth was priced at 1.875, a
quarter of the +3/+3 it lends, on boards where it put three damage through
(3.0) or won the fight (9.0, 8.4), and was cast for that quarter where the
Bear could not attack; Hatred was held with lethal on the table. With the
second reading as it stood when it was first built (a precombat cast read
again through the fight, and nothing else): 76 idle (a ping at a creature
that survives it, a Fog over an attack into a Wall — each "moved" only the
turn's record of who dealt damage), 16 held (every "prevent the next N
damage to any target", whose target was still chosen with no fight in the
reading; Hatred at an X of ten). Now: the fourteen pinned below, none of
them the fight's.

The whole pool takes several minutes, so the suite runs a fixed share of the
population (``SAMPLE_EVERY``) plus every card named in a pin or in ``ALWAYS``,
split across the boards so ``-n`` can share it out; run it as a module
(``python -m tests.ai.test_ai_combat_trick_census``) for all of it.

It reads nothing the policy's second reading added — the fight is
``ai_combat``'s driver, the run-out and "is anything left" are its own
(`run_out`, `lasting_digest`) — so it runs as it stands on a tree without
that reading, which is how it was validated.
"""
from __future__ import annotations

import random
import re
import sys
from collections import Counter
from dataclasses import dataclass

import pytest

from engine import Game, PlayerState
from engine.ai_combat import run_ai_combat_phase
from engine.ai_policy import (SPELL_BASE_SCORE, SWING_CAP, cast_announcement,
                              choose_cast_action, tap_planned_lands)
from engine.ai_valuation import (CARD_WORTH, position_digest, same_position,
                                 scratch_copy, standing_swing, standings,
                                 swing_worth)
from engine.damage_events import DAMAGED_THIS_GAME
from engine.models import Permanent
from tests.ai import test_ai_mode_chooser_census as modes
from tests.ai.test_ai_idle_cast_census import only_mode
from tests.ai.test_ai_idle_cast_census import population as spells

ME, OPP = 0, 1
POOL = modes.POOL
SEED = 1337

#: The caster's creature is every colour, so a trick that names a colour of
#: creature has one to name.
BEAR = modes._creature("Trick Bear", ("W", "U", "B", "R", "G"), 2, 2)
RIVAL = modes._creature("Trick Rival", (), 2, 2)
WALL = modes._creature("Trick Wall", (), 0, 4, "Defender", "Creature - Wall")


@dataclass(frozen=True)
class Layout:
    mine: tuple = ()
    theirs: tuple = ()
    opp_life: int = 20
    #: The caster's creatures came under its control this turn (CR 302.6).
    sick: bool = False
    phase: str = "precombat_main"

    @property
    def fight_to_come(self) -> bool:
        return self.phase == "precombat_main"


BOARDS = {
    "open": Layout(mine=(BEAR,)),
    "rival": Layout(mine=(BEAR,), theirs=(RIVAL,)),
    "wall": Layout(mine=(BEAR,), theirs=(WALL,)),
    "lethal": Layout(mine=(BEAR,), opp_life=5),
    "sick": Layout(mine=(BEAR,), theirs=(RIVAL,), sick=True),
    "bare": Layout(),
    "after": Layout(mine=(BEAR,), theirs=(RIVAL,), phase="postcombat_main"),
}
#: The board the population is read off: the most there is to name.
PROBE = "rival"

#: A cast is worth proposing when it leaves its caster this much better off
#: once the fight is fought; a loss when this much worse.
WIN = 0.5
LOSS = -0.51
EPSILON = 0.01
#: The X a spell that announces one is cast by hand at.
X_VALUES = (1, 2, 3, 5, 10)

#: The suite's share of the population, and the cards it always sweeps: the
#: tricks this round was briefed with, and three that are not tricks — a
#: draw, a ritual and a removal spell, each of which must stay out of it.
SAMPLE_EVERY = 4
TRICKS = frozenset({
    "Fog", "Giant Growth", "Hatred", "Jump", "Twiddle", "Seething Anger",
    "Traitorous Greed", "Orim's Touch",
})
NOT_TRICKS = frozenset({"Sleight of Hand", "Dark Ritual", "Terror"})
ALWAYS = TRICKS | NOT_TRICKS


def board(card, name: str) -> Game:
    """*card* alone in seat 0's hand on board *name*, in seat 0's turn.
    Seat 0 pays out of a mana pool, so nothing on the table is a land."""
    layout = BOARDS[name]
    forest = POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[card], library=[forest] * 10),
        PlayerState(name="Opp", hand=[], library=[forest] * 10, life=layout.opp_life),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat, creatures in ((ME, layout.mine), (OPP, layout.theirs)):
        for creature in creatures:
            permanent = Permanent(card=creature)
            game._put_permanent_onto_battlefield(seat, permanent, seat)
            permanent.metadata["summoning_sickness_turn"] = (
                game.turn if layout.sick and seat == ME else -99
            )
    if layout.phase != "precombat_main":
        game._set_phase_and_step(layout.phase, layout.phase)
    game.players[ME].mana_pool.update({symbol: 6 for symbol in "WUBRG"})
    return game


def run_out(game, *, fight: bool) -> None:
    """The turn run out: the turn's combat fought first if *fight* (the
    attack and the blocks declared by the policies that declare them), then
    whatever of a combat is still owed, then CR 514's cleanup."""
    modes.settle(game)
    if fight and game.current_turn_phase == "precombat_main" and not game.is_game_over():
        random.seed(SEED)
        run_ai_combat_phase(game, game.active_player_index)
        modes.settle(game)
    for _ in range(8):
        if game.current_turn_phase != "combat" or game.is_game_over():
            break
        step = game.current_step
        game.advance_combat_phase()
        game.auto_resolve_pending_choices()
        if game.current_step == step:
            break
    if not game.is_game_over():
        game.resolve_cleanup_step(game.active_player_index)
    modes.settle(game)


def lasting_digest(game) -> dict:
    """``position_digest`` of a board whose turn has run out, with the
    record of what damage was dealt left out: the damage is gone by then
    (CR 514.2), and what it did — a life lost, a creature dead — is on the
    table. Left in, an attack into a Wall that survives it is "changed" by a
    Fog that stopped two damage cleanup would have removed."""
    entries = getattr(getattr(game, "damage_ledger", None), "entries", None)
    if isinstance(entries, list):
        entries.clear()
    for permanent in game.all_permanents():
        permanent.metadata.pop(DAMAGED_THIS_GAME, None)
    return position_digest(game)


_TEMPLATES: dict = {}


def template(card, name: str) -> dict:
    """Board *name* for *card*, and the board with nothing cast run out both
    ways. Every cast on it is made on a copy (``scratch_copy`` keeps every
    permanent's id), so the copies compare with these readings."""
    key = (card.name, name)
    if key not in _TEMPLATES:
        game = board(card, name)
        plain, fought = scratch_copy(game), scratch_copy(game)
        run_out(plain, fight=False)
        run_out(fought, fight=True)
        _TEMPLATES[key] = {
            "game": game,
            "now": standings(game),
            "plain": standings(plain, now=False),
            "plain_digest": lasting_digest(plain),
            "fought": standings(fought, now=False),
            "fought_digest": lasting_digest(fought),
        }
    return _TEMPLATES[key]


def _only_the_card(raw: float) -> bool:
    """Whether a standing swing with the spell's own card in it is that card
    and nothing else: spent (minus a card), or bought back (CR 702.27a)."""
    return abs(raw) < 1e-9 or abs(raw + CARD_WORTH) < 1e-9


def read(card, built: dict, layout: Layout, game, moved: bool, made_mana: bool) -> dict:
    """What the cast that has just resolved on *game* — a copy of *built*'s
    board — did for seat 0.

    ``priced``: everything it changed is gone once the turn has run out with
    no combat fought, or more of its good is than is left — the population's
    test. ``swing`` and ``moved``: what it was worth and whether anything it
    changed is still changed, with the turn's combat fought where the cast is
    priced by a fight still to come.

    The card a cast is made with is given back, as the policy gives it back
    (``ai_valuation.rehearse``), so a spell bought back is a card to the
    good; whether anything *else* changed is asked without it."""
    now = standing_swing(built["now"], standings(game), ME) + CARD_WORTH
    fought = scratch_copy(game) if layout.fight_to_come else None
    run_out(game, fight=False)
    raw = standing_swing(built["plain"], standings(game, now=False), ME)
    lasting = raw + CARD_WORTH
    gone = _only_the_card(raw) and same_position(
        built["plain_digest"], lasting_digest(game), spell_name=card.name, caster=ME,
    )
    # A ritual's mana is gone because it is spent, and is not priced by any
    # fight; a cast that makes mana *and* lends something for the turn (a
    # creature taken until end of turn) is.
    priced = moved and (now > lasting + 1e-9 or (gone and not made_mana))
    if fought is None or not priced:
        return {
            "priced": priced, "swing": round(swing_worth(now, lasting), 3),
            "moved": made_mana or (moved and not gone),
        }
    run_out(fought, fight=True)
    raw = standing_swing(built["fought"], standings(fought, now=False), ME)
    still = not _only_the_card(raw) or not same_position(
        built["fought_digest"], lasting_digest(fought), spell_name=card.name, caster=ME,
    )
    return {"priced": True, "swing": round(raw + CARD_WORTH, 3), "moved": still}


def _x_values(card) -> tuple:
    return X_VALUES if re.search(r"\bX\b", card.oracle_text or "") else (None,)


def announcements(card, mode, game) -> list:
    """Every announcement the engine's picker offers *mode* on *game*: each
    player, each permanent (by id), or nothing — at each X tried. Empty for
    a mode announced as a chain of roles, which is measured as the policy
    announces it."""
    shape = modes.mode_shape(card, mode)
    if shape in ("roles", "stack", "graveyard"):
        return []
    found = []
    for x_value in _x_values(card):
        named = {"mode_index": mode, "x_value": x_value}
        if shape == "untargeted":
            found.append({**named, "target_player_index": ME})
            continue
        listed = game.cast_target_spec(ME, card, mode_index=mode).get("valid_targets") or []
        seats = []
        for entry in listed:
            seat = entry.get("seat")
            if entry.get("kind") == "permanent":
                permanent = game.permanent_at(seat, entry["index"])
                found.append({
                    **named, "target_player_index": seat,
                    "target_permanent_ids": [permanent.permanent_id],
                })
            elif isinstance(seat, int) and seat not in seats:
                seats.append(seat)
                found.append({**named, "target_player_index": seat})
    return found


def cast_by_hand(card, name: str, announcement: dict) -> "dict | None":
    """One announcement made on a copy of board *name*: what it measured, or
    None when the engine refuses it."""
    built = template(card, name)
    game = scratch_copy(built["game"])
    before = modes.table_state(game, card)
    mana_before = modes.pools(game)
    random.seed(SEED)
    try:
        result = game.queue_from_hand(ME, card.name, **announcement)
        if not result.supported:
            return None
        modes.settle(game)
        got = read(
            card, built, BOARDS[name], game, modes.table_state(game, card) != before,
            modes.mana_made(mana_before, game),
        )
    except Exception:
        return None
    got["named"] = announcement
    return got


_BY_HAND: dict = {}


def by_hand(card, mode, name: str) -> list:
    """Every cast of *mode* by hand on board *name* the engine took."""
    key = (card.name, mode, name)
    if key not in _BY_HAND:
        game = template(card, name)["game"]
        _BY_HAND[key] = [
            got for got in (
                cast_by_hand(card, name, announcement)
                for announcement in announcements(card, mode, game)
            )
            if got is not None
        ]
    return _BY_HAND[key]


def in_population(card, mode) -> bool:
    return any(got["priced"] for got in by_hand(card, mode, PROBE))


def proposal(card, mode, name: str) -> dict:
    """The policy's proposal on a copy of board *name*, cast through the
    executors' two lines and measured as a cast by hand is."""
    built = template(card, name)
    out = {"proposed": False, "score": None, "own": None, "error": None}
    random.seed(SEED)
    try:
        with only_mode(card, mode):
            game = scratch_copy(built["game"])
            action = choose_cast_action(game, ME)
            if action is None or action.card_name != card.name:
                return out
            out["proposed"] = True
            out["score"] = action.score
            before = modes.table_state(game, card)
            mana_before = modes.pools(game)
            action = tap_planned_lands(game, ME, action) or action
            random.seed(SEED)
            result = game.queue_from_hand(ME, action.card_name, **cast_announcement(action))
            if not result.supported:
                out["error"] = f"refused: {result.details}"
                return out
            modes.settle(game)
            out["own"] = read(
                card, built, BOARDS[name], game, modes.table_state(game, card) != before,
                modes.mana_made(mana_before, game),
            )
    except Exception as exc:  # a crash is a finding, not a pass
        out["error"] = f"EXC {type(exc).__name__}: {exc}"
    return out


def run(card, mode, name: str) -> dict:
    hands = by_hand(card, mode, name)
    moving = [got for got in hands if got["moved"]]
    best = max(moving, key=lambda got: got["swing"]) if moving else None
    row = {
        "card": card.name, "mode": mode, "board": name,
        "castable": bool(hands), "best": best,
    }
    row.update(proposal(card, mode, name))
    return row


#: How many ``(card, mode)``s the population was read from, the last time.
EXAMINED = Counter()


def population(sample: bool) -> list:
    """``(card, mode)`` for every supported instant and sorcery priced by the
    fight on the ``PROBE`` board — of a fixed share of them when *sample*."""
    found = []
    for position, (card, mode) in enumerate(spells()):
        if sample and position % SAMPLE_EVERY and card.name not in SWEPT:
            continue
        EXAMINED["spells"] += 1
        if in_population(card, mode):
            found.append((card, mode))
    return found


def tag(row) -> tuple:
    return (row["card"], row["mode"], row["board"])


def findings(rows) -> dict:
    out: dict = {leg: {} for leg in ("held", "idle", "loss", "smaller", "priced", "error")}
    for row in rows:
        key = tag(row)
        if row["error"]:
            out["error"][key] = row["error"]
            continue
        best, own = row["best"], row["own"]
        if not row["proposed"]:
            if best is not None and best["swing"] >= WIN:
                out["held"][key] = best["swing"]
            continue
        if not own["moved"]:
            out["idle"][key] = own["swing"]
        elif own["swing"] < LOSS:
            out["loss"][key] = own["swing"]
        # Compared as the policy compares two casts, at most ``SWING_CAP``
        # each: a game won is a game won, and a board the turn did not get
        # to the end of still wears its pumps (Hatred at ten "wins by" more
        # than Hatred at five).
        if best is not None and min(own["swing"], SWING_CAP) < min(
            best["swing"], SWING_CAP,
        ) - EPSILON:
            out["smaller"][key] = (own["swing"], best["swing"])
        if abs(own["swing"]) < SWING_CAP and abs(
            row["score"] - SPELL_BASE_SCORE - own["swing"]
        ) > EPSILON:
            out["priced"][key] = (round(row["score"] - SPELL_BASE_SCORE, 3), own["swing"])
    return out


# -- the pins -------------------------------------------------------------------

#: Each finding that stands, by leg, with why. None is the fight's: each is a
#: chooser this census reaches through a combat trick and that reads the
#: same with no combat in it.

#: "Switch target creature's power and toughness until end of turn" is aimed
#: by its side (``ai_valuation.instruction_target_side``), which reads a
#: switch as a gift to the caster's own board. Across the table, at a 0/4
#: Wall, it is a 4/0 that dies — a removal spell, and not a combat trick.
_SWITCH = "a switch is read as the caster's own; at the opposing 0/4 it kills"
#: A shrink or a tap whose only target here is the caster's own creature,
#: with a card drawn beside it: aimed at an opponent's permanent or not cast
#: (``ai_policy.spell_target_side``), where the card is worth more than the
#: point of damage the attacker loses.
_OWN_ONLY = "its side is the opponent's and its one target is the caster's own; the card it draws is worth more"
#: "All creatures get +X/-X": an X in mana is announced at the largest the
#: seat can pay (``ai_policy._max_affordable_x``), which kills the caster's
#: own 2/2; at one it attacks for three. Sized by what each size does only
#: where the X is life (``ai_policy._cast_candidate_sized``).
_MANA_X = "an X in mana is the largest affordable, and +X/-X at that kills the attacker"
HELD: dict = {
    ("About Face", None, "wall"): _SWITCH,
    ("Transmutation", None, "wall"): _SWITCH,
    ("Afflict", None, "open"): _OWN_ONLY,
    ("Afflict", None, "lethal"): _OWN_ONLY,
    ("Ice", None, "open"): _OWN_ONLY,
    ("Ice", None, "lethal"): _OWN_ONLY,
    ("Flowstone Slide", None, "open"): _MANA_X,
    ("Flowstone Slide", None, "lethal"): _MANA_X,
}
#: Desperate Gambit flips a coin: won, the chosen source's next damage this
#: turn is doubled; lost, it is prevented. A rehearsal's randomness is its own
#: on purpose (``ai_valuation._rehearsal_seed``) — it says what such a cast is
#: *like* and must not say how the real flip will fall. The rehearsal's
#: sample won it; this census's cast, on its own seed, lost.
_COIN = "a coin flip: the rehearsal's sample won it, the cast lost it"
IDLE: dict = {("Desperate Gambit", None, "wall"): _COIN}
LOSSES: dict = {
    ("Desperate Gambit", None, "open"): _COIN,
    ("Desperate Gambit", None, "lethal"): _COIN,
}
SMALLER: dict = {}
PRICED: dict = {
    ("Desperate Gambit", None, "open"): _COIN,
    ("Desperate Gambit", None, "lethal"): _COIN,
    ("Desperate Gambit", None, "wall"): _COIN,
}

SWEPT = ALWAYS | {
    key[0] for pins in (HELD, IDLE, LOSSES, SMALLER, PRICED) for key in pins
}
assert SWEPT <= set(POOL), sorted(SWEPT - set(POOL))


# -- the tests ------------------------------------------------------------------

_POPULATION: list = []


def _population() -> list:
    if not _POPULATION:
        _POPULATION.extend(population(sample=True))
    return _POPULATION


PINS = {"held": HELD, "idle": IDLE, "loss": LOSSES, "smaller": SMALLER, "priced": PRICED}


def test_the_population_is_the_pool_s_combat_tricks():
    """The floor under every board below: a sweep that reaches nothing passes
    everything."""
    population = _population()
    assert EXAMINED["spells"] >= 300, dict(EXAMINED)
    assert len(population) >= 60, len(population)
    named = {card.name for card, _mode in population}
    assert TRICKS <= named, sorted(TRICKS - named)
    assert not NOT_TRICKS & named, sorted(NOT_TRICKS & named)


#: The least each board must reach, of the sampled population: casts the
#: engine took by hand there; boards on which some cast by hand wins at least
#: ``WIN`` and the policy cast the card; and boards on which no cast by hand
#: leaves anything and the policy held it. A board that reaches none of the
#: three says nothing about whether a trick is cast for the fight it changes.
#: (On the tree before the fight was weighed, every board's third number but
#: ``rival``'s was a handful: the trick was cast there anyway.)
FLOORS = {
    "after": (60, 15, 40), "bare": (18, 0, 15), "lethal": (60, 20, 20),
    "open": (60, 20, 20), "rival": (60, 35, 12), "sick": (60, 8, 40),
    "wall": (60, 30, 22),
}


@pytest.mark.parametrize("name", sorted(BOARDS))
def test_each_trick_is_cast_for_the_fight_it_changes_and_only_then(name):
    """Every finding on board *name* is a pinned one, by leg — and the board
    reached what it has to (``FLOORS``)."""
    rows = [run(card, mode, name) for card, mode in _population()]
    castable, cast_to_win, held_for_nothing = FLOORS[name]
    assert sum(row["castable"] for row in rows) >= castable
    assert sum(
        1 for row in rows
        if row["proposed"] and row["best"] is not None and row["best"]["swing"] >= WIN
    ) >= cast_to_win
    assert sum(
        1 for row in rows
        if row["castable"] and row["best"] is None and not row["proposed"]
    ) >= held_for_nothing
    found = findings(rows)
    assert found["error"] == {}
    cards = {(row["card"], row["mode"]) for row in rows}
    for leg, pins in PINS.items():
        pinned = {key for key in pins if key[2] == name and key[:2] in cards}
        assert set(found[leg]) == pinned, (leg, {
            key: found[leg].get(key, "pinned, not found")
            for key in sorted(set(found[leg]) ^ pinned, key=repr)
        })


if __name__ == "__main__":
    everything = population(sample="--sample" in sys.argv)
    print(f"population: {len(everything)} (card, mode)s, "
          f"{len({card.name for card, _ in everything})} cards", flush=True)
    rows = []
    for board_name in sorted(BOARDS):
        for card, mode in everything:
            rows.append(run(card, mode, board_name))
        print(f"  board {board_name} done", flush=True)
    found = findings(rows)
    tally = Counter()
    for row in rows:
        tally[(row["board"], "castable")] += row["castable"]
        tally[(row["board"], "proposed")] += row["proposed"]
    for key in sorted(tally):
        print(key, tally[key])
    for leg in ("held", "idle", "loss", "smaller", "priced", "error"):
        print(f"== {leg}: {len(found[leg])}")
        for key in sorted(found[leg], key=lambda k: (k[0], str(k[1]), k[2])):
            print(f"   {key}: {found[leg][key]}")
    if "--names" in sys.argv:
        for card, mode in everything:
            print("   member:", card.name, mode)
