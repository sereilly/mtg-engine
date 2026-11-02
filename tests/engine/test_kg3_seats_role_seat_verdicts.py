"""CR 608.2b for an **ability** whose roles announcement names a player.

    "If all its targets, for every instance of the word 'target,' are now
    illegal, the spell or ability doesn't resolve. … Otherwise, the spell or
    ability will resolve normally. Illegal targets, if any, won't be affected
    by parts of a resolving spell's effect for which they're illegal."

``legality_resolution.ability_target_verdicts`` judged a roles announcement of
permanents and graveyard cards role by role, and declined one with a **seat**
role outright — so "every target is illegal" was never asked of Keeper of the
Dead, the Planeswalker's Scorn and Favor, Soldevi Heretic or Shieldmage
Advocate (an "any target" role a player answered): each resolved with every
target gone, and the Advocate's shield still went up around a player who had
gained shroud in response. A seat role is now judged as the one its own
enumeration still offers (``Game.role_seat_is_offered``, the predicate the
handlers' per-target half asks too).

The census drives every activated ability in both manifest roles whose
announcement is a roles announcement with a player role: announced at the
first chain its own picker offers, then three arms — nothing done (not
removed), every target made illegal (removed by the rule, nothing else moved),
and the player alone given shroud (it still resolves, and the player is not
affected). Validated backwards, with a floor on what it examined.
"""

from __future__ import annotations

import copy

import pytest

from engine import Game, PlayerState, faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.legality import _activation_spec
from engine.mana_payment import is_mana_ability
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.shields import shields_on
from engine.targeting import spec_roles, usable_activated_abilities
from engine.target_roles import role_is_seat
from tests.helpers import _mk_card, _nosick, resolve_stack

_POOL: dict = {}
for _card in faces.compilation_units(load_cards(manifest_set_paths(include_measured=True))):
    _POOL.setdefault(_card.name, _card)

_REMOVED = "removed from the stack"

_MASK = CardDefinition(
    name="Census Mask", mana_cost="", cmc=0.0, type_line="Enchantment",
    oracle_text="You have shroud.", colors=(), color_identity=(), keywords=(),
    produced_mana=(), raw={"name": "Census Mask", "type_line": "Enchantment"},
)
_BAIT = (
    _mk_card(name="Bait Creature", type_line="Creature - Human Soldier", power=2,
             toughness=2, colors=("W", "U", "B", "R", "G")),
    _mk_card(name="Bait Artifact", type_line="Artifact"),
    _mk_card(name="Bait Other Creature", type_line="Creature - Elf Druid", power=1,
             toughness=4),
)
_SHARED = {id(card): card for card in (*_POOL.values(), *_BAIT, _MASK)}

#: Five on the day (Keeper of the Dead, Planeswalker's Favor, Planeswalker's
#: Scorn, Shieldmage Advocate, Soldevi Heretic); a floor well over zero so a
#: rig that stopped announcing cannot read green.
_MIN_DRIVEN = 4

#: What each showed on the base tree: none of them was removed with every
#: target illegal.
_KNOWN = (
    "Keeper of the Dead", "Planeswalker's Favor", "Planeswalker's Scorn",
    "Shieldmage Advocate", "Soldevi Heretic",
)


def _seat_role_activations() -> list:
    """``(card, ability index)`` for every supported, non-mana activated
    ability whose derived picker is a roles announcement with a player role
    — sorted, so the census reads the same cards every run."""
    found = []
    for name in sorted(_POOL):
        card = _POOL[name]
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None or is_mana_ability(ability):
                continue
            spec, _ = _activation_spec([ability])
            if spec.get("kind") != "roles":
                continue
            # A player role, or an "any target" role a player may answer.
            if any(
                role_is_seat(role) or role.get("kind") == "any"
                for role in spec_roles(spec)
            ):
                found.append((card, index))
    return found


def _board(source_card) -> tuple[Game, Permanent]:
    """Two seats in seat 0's main phase, the source on seat 0 and the same
    plain permanents on both sides; seat 0 has four more creature cards in its
    graveyard than seat 1 (Keeper of the Dead's announcement), seat 1 a card
    of each other type in its graveyard and two cards in hand."""
    yard = [_POOL[name] for name in ("Sol Ring", "Lightning Bolt", "Forest", "Crusade")]
    source = _nosick(Permanent(card=source_card))
    game = Game(players=[
        PlayerState(
            name="P1", life=20, library=[_POOL["Forest"]] * 12,
            graveyard=list(yard) + [_POOL["Grizzly Bears"]] * 4,
            hand=[_POOL["Forest"], _POOL["Grizzly Bears"]],
            battlefield=[source] + [_nosick(Permanent(card=card)) for card in _BAIT],
        ),
        PlayerState(
            name="P2", life=20, library=[_POOL["Forest"]] * 12, graveyard=list(yard),
            hand=[_POOL["Forest"], _POOL["Grizzly Bears"]],
            battlefield=[_nosick(Permanent(card=card)) for card in _BAIT],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.check_state_based_actions()
    return game, source


def _chain(entries, depth: int):
    """The first full walk of a roles picker's tree, an opponent's object or
    face first at every step."""
    for entry in sorted(entries, key=lambda e: e.get("seat") != 1):
        if depth == 1:
            return [entry]
        rest = _chain(entry.get("next") or [], depth - 1)
        if rest:
            return [entry] + rest
    return None


def _announce(card, index):
    """Put the ability on the stack of a fresh board at the chain its own
    picker offers first: ``(game, objects)``, each object ``(kind, what)``,
    or None when this rig has no announcement to make."""
    game, source = _board(card)
    slot = game.battlefield_index_of(source)
    spec = game.activation_target_spec(0, slot, ability_index=index)
    chain = _chain(spec.get("valid_targets") or [], len(spec_roles(spec)))
    if chain is None:
        return None
    refs, objects = [], []
    for entry in chain:
        kind = entry.get("kind")
        if kind == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            refs.append({"permanent_id": permanent.permanent_id})
            objects.append(("permanent", permanent.permanent_id))
        elif kind == "player":
            refs.append({"seat": entry["seat"]})
            objects.append(("player", entry["seat"]))
        elif kind == "graveyard":
            stamp = game.graveyard_target_at(entry["seat"], entry["index"])
            refs.append({"graveyard_seat": entry["seat"], "graveyard_index": entry["index"]})
            objects.append(("graveyard", (entry["seat"], stamp.card.name)))
        else:
            return None
    depth = len(game.stack)
    result = game.queue_permanent_ability(0, card.name, ability_index=index, target_role_refs=refs)
    if not result.supported or len(game.stack) <= depth:
        return None
    return game, objects


def _make_illegal(game, obj) -> None:
    kind, what = obj
    if kind == "permanent":
        permanent = game.permanent_by_id(what)
        seat = game.controller_index_of(permanent)
        game.remove_from_battlefield(permanent)
        game.players[seat].graveyard.append(permanent.card)
    elif kind == "player":
        game._put_permanent_onto_battlefield(what, _nosick(Permanent(card=_MASK)), what)
    else:
        seat, name = what
        gone = [c for c in game.players[seat].graveyard if c.name == name]
        game.players[seat].graveyard = [c for c in game.players[seat].graveyard if c.name != name]
        game.players[seat].exile.extend(gone)


def _fingerprint(game) -> tuple:
    """Each seat's life and zones, and every permanent's controller, tapped
    state, damage, computed P/T and shields."""
    return (
        tuple(
            (player.life, len(player.hand), len(player.library),
             tuple(c.name for c in player.graveyard), repr(shields_on(player)))
            for player in game.players
        ),
        tuple(sorted(
            (
                permanent.permanent_id, game.controller_index_of(permanent),
                permanent.tapped, permanent.damage_marked,
                permanent.effective_power if permanent.is_creature else None,
                permanent.effective_toughness if permanent.is_creature else None,
                repr(shields_on(permanent)),
            )
            for permanent in game.all_permanents()
        )),
    )


def _arm(announced, change):
    game0, objects = announced
    game = copy.deepcopy(game0, dict(_SHARED))
    for obj in change:
        _make_illegal(game, obj)
    game._recompute_continuous_effects()
    before = _fingerprint(game)
    mark = len(game.log)
    resolve_stack(game)
    return game, game.log[mark:], before


def _drive(only=None) -> dict:
    counts = {"driven": 0, "removed": 0, "seat_masked": 0}
    findings: list[str] = []
    for card, index in _seat_role_activations():
        if only is not None and card.name not in only:
            continue
        announced = _announce(card, index)
        if announced is None:
            continue
        _game0, objects = announced
        counts["driven"] += 1
        label = f"{card.name}#{index}"
        game, said, _before = _arm(announced, [])
        if any(_REMOVED in line for line in said):
            findings.append(f"{label}: removed with every target legal — {said[-2:]}")
            continue
        game, said, before = _arm(announced, objects)
        if not any(_REMOVED in line for line in said):
            findings.append(f"{label} [every target illegal]: not removed — {said[-3:]}")
        else:
            counts["removed"] += 1
            if _fingerprint(game) != before or game.stack:
                findings.append(f"{label} [every target illegal]: removed, but the game moved")
        seats = [obj for obj in objects if obj[0] == "player"]
        if seats and len(objects) > len(seats):
            game, said, before = _arm(announced, seats)
            if any(_REMOVED in line for line in said):
                findings.append(f"{label} [player masked]: removed with a target still legal")
            else:
                counts["seat_masked"] += 1
                # Not affected as the target it no longer is: no life moved,
                # no card drawn, no card revealed, no shield put up around it.
                # (A card returned to its hand from its graveyard is the
                # graveyard target's effect, not the player's.)
                masked = game.players[seats[0][1]]
                if (
                    masked.life != 20 or len(masked.library) != 12
                    or shields_on(masked)
                    or any(f"{masked.name} reveals" in line for line in said)
                ):
                    findings.append(f"{label} [player masked]: the masked player was affected — {said[-3:]}")
    return {"counts": counts, "findings": findings}


def test_an_ability_with_a_player_role_is_held_to_every_target():
    result = _drive()
    assert not result["findings"], "\n".join(result["findings"])
    counts = result["counts"]
    assert counts["driven"] >= _MIN_DRIVEN, counts
    assert counts["removed"] == counts["driven"], counts
    assert counts["seat_masked"] >= _MIN_DRIVEN, counts


def test_the_census_goes_red_without_the_seat_verdict(monkeypatch):
    """The base tree's reading: a roles verdict holding a player declines the
    whole object. The census has to name every known card."""
    judged = Game.ability_target_verdicts

    def declining(self, item, **kwargs):
        verdicts = judged(self, item, **kwargs)
        if verdicts and any(
            target.kind == "player" and target.channel == "role"
            for target, _legal in verdicts
        ):
            return None
        return verdicts

    monkeypatch.setattr(Game, "ability_target_verdicts", declining)
    findings = _drive(only=set(_KNOWN))["findings"]
    named = {line.split("#")[0] for line in findings if "[every target illegal]: not removed" in line}
    assert named == set(_KNOWN), findings


def test_keeper_of_the_dead_destroys_its_creature_when_its_opponent_gains_shroud():
    """"Choose target opponent … Destroy target nonblack creature that player
    controls." The opponent given shroud in response is an illegal target and
    is not affected; the creature is still a nonblack creature that player
    controls, so it is still a legal target and the ability resolves for it
    (CR 608.2b). On the base tree "that player" named nobody once the seat was
    illegal, and the creature stood."""
    keeper = _POOL["Keeper of the Dead"]
    index = next(i for c, i in _seat_role_activations() if c is keeper)
    announced = _announce(keeper, index)
    assert announced is not None
    _game0, objects = announced
    creature_id = next(what for kind, what in objects if kind == "permanent")
    seat = next(what for kind, what in objects if kind == "player")

    game, said, _before = _arm(announced, [("player", seat)])

    assert game.permanent_by_id(creature_id) is None, said
    assert any("destroyed" in line for line in said), said
    assert not any(_REMOVED in line for line in said), said
