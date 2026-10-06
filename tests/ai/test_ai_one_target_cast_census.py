"""Census: does an AI seat cast a one-object spell when the board offers exactly
one legal target, on the side the spell's effect wants?

``ai_policy._can_cast_with_targets`` carries three *preference arms* — "is
there something on the opponent's board worth destroying", and the like —
and two of them answered with a matcher of their own instead of the engine's
list. The mode chooser's census found them, because a mode is cast or not on
exactly this question, and they were wrong for spells with no mode at all:

* the **destroy** arm compared a permanent's printed, collapsed type word to
  the instruction's ``type_filter``. An artifact creature is "creature", so
  Shatter, Disenchant, Crash, Scrap and the rest were never cast at one; and a
  filter naming several types is a *list*, which equals no word — Pillage,
  Creeping Mold, Fissure, Eliminate and Finishing Blow were **never cast**;
* the **pump** arm asked whether the caster controlled a creature of its own,
  for a kind that is also "target creature gets -4/-4": Grasp of Darkness and
  Shrink were held until the seat had a creature it did not want to shrink.

Both now ask ``Game._enumerate_targets`` — the list a human's picker is built
from — for the seat the effect wants. This sweep is the definition of done:
every supported instant and sorcery whose cast names **one battlefield
object** (per mode, for a modal one, offered alone), and every census
permanent that is a legal target on the side ``ai_valuation`` says its effect
wants *and that the spell does something to* — the engine's answer, the spell
cast at it by hand and the board compared, because "Destroy target permanent
if it's blue" may name any permanent and touches only a blue one.

Before: 227 of 1,414 pairs declined, over 51 ``(card, mode)``s — 66 of them
over fifteen spells that print no mode. After: 29, over the three cards named
in ``DECLINED``, each one declined on purpose.

Run it as a module (``python -m tests.ai.test_ai_one_target_cast_census``) for
the table.
"""
from __future__ import annotations

from collections import Counter
from unittest import mock

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_cast_action
from engine.ai_valuation import instruction_target_side
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import (announced_mode_instructions, derive_cast_spec,
                              spec_roles)
from tests.helpers import _mk_card, resolve_stack

OBJECT_KINDS = {"creature", "artifact", "land", "permanent", "enchantment", "planeswalker"}
ME, OPP = 0, 1


def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


POOL = pool()


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
    "artifact": _mk_card(name="Bait Artifact", type_line="Artifact"),
    "enchantment": _mk_card(name="Bait Enchantment", type_line="Enchantment", colors=("W",)),
    "nonbasic land": _mk_card(name="Bait Nonbasic", type_line="Land"),
    "plains": POOL["Plains"], "island": POOL["Island"], "swamp": POOL["Swamp"],
    "mountain": POOL["Mountain"], "forest": POOL["Forest"],
}


def board(card, seat, key):
    forest = POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[card], library=[forest] * 10),
        PlayerState(name="Opp", library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    permanent = Permanent(card=ZOO[key])
    game._put_permanent_onto_battlefield(seat, permanent, seat)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[ME].mana_pool.update({symbol: 8 for symbol in "WUBRG"})
    return game, permanent


#: What every cast changes whatever it does (see the mode census).
_BOOKKEEPING = frozenset({
    "hand", "graveyard", "library", "mana_pool", "battlefield",
    "spells_cast_this_turn",
})


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
        rest = {
            key: value for key, value in vars(player).items()
            if key not in _BOOKKEEPING
        }
        parts.append((hand, yard, len(player.library), repr(sorted(rest.items(), key=lambda kv: kv[0]))))
        parts.append(sorted(
            (perm.permanent_id, repr(perm), perm.is_creature and perm.effective_power,
             perm.is_creature and perm.effective_toughness)
            for perm in player.battlefield
        ))
    return repr(parts)


def acts_on(card, mode, seat, key) -> bool:
    """Whether *card* (in *mode*), cast by hand at the lone bait, resolves
    doing anything — the engine's answer, with no policy in it. "Destroy
    target permanent if it's blue" may name any permanent and touches only a
    blue one; a pair the spell does nothing to is not one a seat should cast."""
    game, bait = board(card, seat, key)
    before = signature(game, card)
    x_value = 2 if "{X}" in (card.mana_cost or "").upper() else None
    try:
        result = game.queue_from_hand(
            ME, card.name, mode_index=mode, x_value=x_value,
            target_player_index=seat, target_permanent_ids=[bait.permanent_id],
        )
        if not result.supported:
            return False
        resolve_stack(game)
    except Exception:
        return False
    return signature(game, card) != before


def steps_side(instructions):
    sides = set()

    def walk(step):
        payload = getattr(step, "payload", None) or {}
        targets = payload.get("targets")
        if isinstance(targets, dict) and targets.get("kind") == "object":
            side = instruction_target_side(step)
            if side is not None:
                sides.add(side)
        for key in ("steps", "then", "else", "action", "otherwise"):
            for nested in payload.get(key) or ():
                walk(nested)

    for step in instructions:
        walk(step)
    return "opponent" if "opponent" in sides else "you" if "you" in sides else None


def census():
    rows = []
    for name in sorted(POOL):
        card = POOL[name]
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.mode_chooser is not None:
            continue
        modes = range(len(program.modes)) if program.modes else (None,)
        for mode in modes:
            spec = derive_cast_spec(card, program, mode_index=mode, optional_cost_payments={}) or {}
            if spec.get("kind") not in OBJECT_KINDS or spec_roles(spec):
                continue
            if spec.get("source_of_choice") or spec.get("max_targets") or spec.get("x_targets"):
                continue
            if any(spec.get(flag) for flag in ("sacrifice_cost", "discard_cost", "exile_cost", "cost_spec")):
                continue
            steps = announced_mode_instructions(program, mode)
            side = steps_side(steps)
            if side is None:
                continue  # no side: the chooser may aim it anywhere
            seat = ME if side == "you" else OPP
            first = steps[0].kind if steps else None
            for key in ZOO:
                game, bait = board(card, seat, key)
                slot = (game.controller_index_of(bait), game.battlefield_index_of(bait))
                listed = game.cast_target_spec(ME, card, mode_index=mode).get("valid_targets") or []
                if not any(
                    entry.get("kind") == "permanent" and (entry["seat"], entry["index"]) == slot
                    for entry in listed
                ):
                    continue
                if program.modes and mode not in game.announceable_modes(ME, card):
                    continue
                if not acts_on(card, mode, seat, key):
                    continue

                def only(self, caster_index, asked, **kwargs):
                    return [mode] if asked.name == card.name else []

                error = None
                with mock.patch.object(Game, "announceable_modes", only):
                    try:
                        action = choose_cast_action(game, ME)
                    except Exception as exc:
                        action, error = None, f"EXC {type(exc).__name__}: {exc}"
                named = None if action is None else (
                    (getattr(action, "mode_index", None) or 0) if program.modes else None
                )
                rows.append({
                    "card": name, "mode": mode, "kind": first, "side": side, "bait": key,
                    "proposed": action is not None and named == mode,
                    "error": error,
                })
    return rows



# -- the tests ----------------------------------------------------------------

#: The spells still declined with a legal target on the side they want, and
#: why each is a decision rather than a miss: a denial the printed words aim
#: at the caster's **own** permanent (`ai_valuation.spell_denies_its_own
#: _target`) is a price or a rescue this policy has no way to time.
DECLINED = {
    "Energy Tap": "taps the caster's own creature",
    "Liberate": "exiles the caster's own creature",
    "Rescue": "returns the caster's own permanent",
}


@pytest.fixture(scope="module")
def rows() -> list:
    return census()


def test_the_sweep_examined_the_pool(rows):
    """The floor: a sweep that reaches nothing passes everything."""
    assert len(rows) >= 1350
    assert len({row["card"] for row in rows}) >= 220
    kinds = {row["kind"] for row in rows}
    assert {"destroy_target_permanent", "pump_target_creature_until_eot",
            "bounce_target_creature"} <= kinds


def test_no_proposal_crashed(rows):
    assert [row for row in rows if row["error"]] == []


def test_a_one_target_spell_with_a_target_on_its_side_is_cast(rows):
    declined = sorted({row["card"] for row in rows if not row["proposed"]})
    assert declined == sorted(DECLINED), (
        "declined with a legal target on the wanted side: "
        + ", ".join(sorted(set(declined) - set(DECLINED)))
    )


def test_the_spells_the_old_arms_never_cast_are_cast_at_everything_legal(rows):
    """The named ones, so the two defects stay readable in the sweep."""
    by_card: dict = {}
    for row in rows:
        by_card.setdefault(row["card"], []).append(row)
    for name in ("Pillage", "Creeping Mold", "Fissure", "Eliminate",
                 "Finishing Blow", "Grasp of Darkness", "Shrink"):
        assert len(by_card[name]) >= 5, name
        assert all(row["proposed"] for row in by_card[name]), name
    for name in ("Shatter", "Disenchant", "Crash", "Scrap", "Verdigris"):
        at_golem = [row for row in by_card[name] if row["bait"] == "artifact creature"]
        assert at_golem and all(row["proposed"] for row in at_golem), name


def test_a_guarded_effect_is_swept_only_where_it_does_something(rows):
    """"Destroy target permanent if it's blue": the one blue census permanent
    is a pair, the fourteen others are not — a seat that cast it at those
    would be the defect, not the cure."""
    baits = {
        row["bait"] for row in rows
        if row["card"] == "Pyroblast" and row["mode"] == 1
    }
    assert baits == {"blue flyer"}


if __name__ == "__main__":
    rows = census()
    declined = [row for row in rows if not row["proposed"]]
    by_kind = Counter(row["kind"] for row in declined)
    by_card = Counter((row["card"], row["mode"]) for row in declined)
    print(f"pairs examined: {len(rows)}  cards: {len({row['card'] for row in rows})}")
    print(f"declined: {len(declined)} over {len(by_card)} (card, mode)s")
    print("declined by first step kind:", dict(by_kind.most_common()))
    for (card, mode), count in sorted(by_card.items()):
        baits = sorted(row["bait"] for row in declined if (row["card"], row["mode"]) == (card, mode))
        errors = sorted({row["error"] for row in declined if (row["card"], row["mode"]) == (card, mode) and row["error"]})
        print(f"   {card} [{mode}]: {count} -- {', '.join(baits)}{' ' + str(errors) if errors else ''}")
