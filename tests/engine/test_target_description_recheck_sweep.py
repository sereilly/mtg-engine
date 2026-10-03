"""Pool sweep: a spell whose every target stopped answering its printed
description does nothing at all (CR 608.2b), however its handlers are written.

``legality.illegal_targets_refusal`` re-asks the announcement's own question —
``Game._described_cast_target_slots`` — of each surviving target. Before it
did, a spell whose target stopped matching resolved anyway: what its handler
re-checked was skipped, what it did not re-check ran, and a resolver that
declined the id sometimes scanned on to a permanent nobody named. The full
census over 280 spells and 19 kinds of change is ``scratch/w2g2/census_608.py``
(130 spells acted before the fix, 0 after); this sweep keeps the two largest
rows of it honest on every run:

* every shipped instant and sorcery whose target is a **creature**, cast at an
  opponent's creature (or its caster's own, where the spell says "you
  control") that then stops being a creature;
* every shipped instant and sorcery whose description **excludes a colour**
  ("nonblack", "nonwhite"), cast at a creature that then becomes that colour.

The assertion is the whole board: nothing but the spell's own trip to the
graveyard may differ between the moment before resolution and after it, and the
log must say the rule did it. A floor on how many spells were examined keeps a
rig that stopped casting anything from passing over zero cards.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.layer_bridge import SET_CARD_TYPES
from engine.legality import _resolution_rechecks_description
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec
from tests.helpers import resolve_stack

_GATE = "every target is illegal (608.2b)"

_POOL: dict = {}
for _card in load_cards(manifest_set_paths()):
    _POOL.setdefault(_card.name, _card)


def _spells(predicate):
    out = []
    for name, card in sorted(_POOL.items()):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        spec = derive_cast_spec(card, program)
        if spec is None or not _resolution_rechecks_description(spec):
            continue
        if predicate(spec):
            out.append((card, spec))
    return out


def _board(spell):
    def perm(name):
        p = Permanent(card=_POOL[name])
        p.metadata["summoning_sickness_turn"] = -99
        return p

    fillers = [_POOL[n] for n in ("Forest", "Grizzly Bears", "Mountain")]
    game = Game(players=[
        PlayerState(name="P0", hand=[spell, *fillers],
                    battlefield=[perm("Grizzly Bears"), perm("Scathe Zombies"), perm("Forest")],
                    library=[_POOL["Island"]] * 4),
        PlayerState(name="P1", hand=list(fillers),
                    battlefield=[perm("Grizzly Bears"), perm("Hill Giant"), perm("Forest")],
                    library=[_POOL["Island"]] * 4),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _fingerprint(game, spell_name):
    players = []
    for seat, player in enumerate(game.players):
        graveyard = [card.name for card in player.graveyard]
        if seat == 0 and spell_name in graveyard:
            graveyard.remove(spell_name)
        players.append((player.life, sorted(c.name for c in player.hand),
                        len(player.library), graveyard, [c.name for c in player.exile]))
    permanents = {
        perm.permanent_id: (
            game.controller_index_of(perm), perm.tapped, perm.damage_marked,
            perm.effective_power if perm.is_creature else None,
            perm.effective_toughness if perm.is_creature else None,
            sorted((k, repr(v)) for k, v in perm.metadata.items()),
        )
        for perm in game.all_permanents()
    }
    return players, permanents, len(game.delayed_triggers)


def _sweep(spells, change, *, floor):
    examined, failures = 0, []
    for card, spec in spells:
        game = _board(card)
        offered = {
            game.players[t["seat"]].battlefield[t["index"]].permanent_id
            for t in game._enumerate_targets(0, card, spec, for_cast=True)
            if t.get("kind") == "permanent" and t.get("index") is not None
        }
        target = next(
            (
                perm for seat in (1, 0) for perm in game.players[seat].battlefield
                if perm.card.name == "Grizzly Bears" and perm.permanent_id in offered
            ),
            None,
        )
        if target is None:
            continue  # this spell's board is not this rig's (combat-only, …)
        kwargs = {}
        if "{X}" in (card.mana_cost or ""):
            kwargs["x_value"] = 1 if spec.get("x_targets") else 4
        queued = game.queue_from_hand(
            0, card.name, target_player_index=game.controller_index_of(target),
            target_permanent_ids=[target.permanent_id], **kwargs,
        )
        if not queued.supported or not game.stack:
            continue
        change(target)
        if target.permanent_id in {
            game.players[t["seat"]].battlefield[t["index"]].permanent_id
            for t in game._enumerate_targets(0, card, spec, for_cast=True)
            if t.get("kind") == "permanent" and t.get("index") is not None
        }:
            continue  # the change did not take this spell's target out of its description
        examined += 1
        before = _fingerprint(game, card.name)
        mark = len(game.log)
        resolve_stack(game)
        if not any(_GATE in line for line in game.log[mark:]):
            failures.append(f"{card.name}: not countered by the rule — {game.log[mark:][-3:]}")
        elif _fingerprint(game, card.name) != before:
            failures.append(f"{card.name}: countered, but the game changed")
    assert not failures, "\n".join(failures)
    assert examined >= floor, f"only {examined} spells examined; the rig stopped casting"
    return examined


def _stops_being_a_creature(perm):
    perm.metadata[SET_CARD_TYPES] = {
        "card_types": ["enchantment"], "timestamp": 10**6, "source": "sweep",
    }


def test_a_creature_spell_target_that_stops_being_a_creature_counters_the_spell():
    spells = _spells(lambda spec: spec.get("kind") == "creature")
    assert len(spells) >= 150, len(spells)
    _sweep(spells, _stops_being_a_creature, floor=120)


def test_a_colour_excluded_by_the_description_counters_the_spell():
    spells = _spells(
        lambda spec: bool((spec.get("filter") or {}).get("exclude_colors"))
    )
    examined = 0
    for colour in ("W", "U", "B", "R", "G"):
        family = [
            (card, spec) for card, spec in spells
            if colour in spec["filter"]["exclude_colors"]
        ]
        if not family:
            continue

        def recolour(perm, colour=colour):
            perm.metadata["color_override"] = (colour,)

        examined += _sweep(family, recolour, floor=0)
    assert examined >= 10, examined
