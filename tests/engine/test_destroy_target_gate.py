"""Guard: every narrowing a destroy prints is enforced by the gate that offers
its targets.

The failure this exists for is not a crash and not a missing ability. It is an
ability that works **more often than the card allows**: Merfolk Assassin's
"{T}: Destroy target creature with islandwalk" destroyed a vanilla 4/4 Bear,
accepted at activation and resolved, because ``Game._destroy_target_legal``
asked ``permanent_matches_filter`` — the half of the matcher readable off a
permanent alone. Keywords are layer 6 (CR 613.1f), a controller and an owner
are seats, a combat relation needs the ability's source: every one of those is
a key the pure half does not read, and a key it does not read is a restriction
it silently ignores.

**Both questions are asked of the behaviour, over the pool, and neither is a
second copy of a list.**

* :func:`test_the_gate_asks_the_whole_noun_phrase` — over every
  ``destroy_target_permanent`` payload the manifest produces (both roles) and a
  board of probe permanents, what the gate offers is exactly what the full
  matcher agrees the sentence names. This is the invariant that broke, and it
  fails the moment the gate is routed back through a partial reading.
* :func:`test_every_game_relative_key_the_pool_prints_is_enforced` — the half
  that keeps the first from being vacuous. "Which keys does the pure matcher not
  read?" is *observed* rather than declared: a key asked **on its own** against
  which the pure matcher and the full matcher disagree is, by that fact alone, a
  key the pure half cannot answer. Asked on its own precisely so no other key
  can mask it — the confounder that makes a whole-payload deletion probe report
  Royal Assassin's "creature" as unenforced because "tapped" already refused
  every non-creature on the board.

A list of affected card names would be the cheapest thing to write here and the
most expensive to own: it goes stale the day a set is ingested, and its failures
look like findings. The payloads come out of ``cards/manifest.json``.
"""

from __future__ import annotations

import pytest

from engine.faces import compilation_units
from engine.card_loader import load_cards, manifest_set_paths
from engine.game import Game
from engine.handlers._common import permanent_matches_filter
from engine.models import PlayerState, Permanent
from engine.oracle import compile_card_oracle
from engine.subject_filters import subject_matches
from engine.targeting import destroy_subject_filter

from tests.helpers import _mk_card

# The seats the probes are asked with. Arbitrary and *stated*, because
# ``subject_matches`` refuses a seat-relative narrowing it is not given — so a
# probe that withheld them would report every seat key as enforced by refusing
# everything, which is the opposite of what these tests mean to observe.
_OBSERVER = 0
_DEFENDING = 1
_THAT_PLAYER = 1


def _probe_permanents() -> list[Permanent]:
    """One permanent per shape a printed destroy narrows by.

    Rich enough that the *pure* half of every payload in the pool matches
    something: Pit Trap's "attacking creature without flying" needs an attacker
    to exist before its keyword clause has anything to bite on, and a payload
    whose pure half matches nothing would report its blind key as enforced for
    the wrong reason.
    """
    plain = Permanent(card=_mk_card("Probe Bear", "Creature - Bear"))
    flyer = Permanent(card=_mk_card("Probe Bird", "Creature - Bird", "Flying"))
    attacker = Permanent(card=_mk_card("Probe Raider", "Creature - Soldier"))
    attacker.attacking = True
    attacking_flyer = Permanent(
        card=_mk_card("Probe Drake", "Creature - Drake", "Flying")
    )
    attacking_flyer.attacking = True
    tapped = Permanent(card=_mk_card("Probe Ox", "Creature - Ox"), tapped=True)
    artifact = Permanent(card=_mk_card("Probe Rock", "Artifact"))
    artifact_creature = Permanent(
        card=_mk_card("Probe Golem", "Artifact Creature - Golem")
    )
    enchantment = Permanent(card=_mk_card("Probe Charm", "Enchantment"))
    land = Permanent(card=_mk_card("Probe Waste", "Land"))
    return [
        plain, flyer, attacker, attacking_flyer, tapped,
        artifact, artifact_creature, enchantment, land,
    ]


@pytest.fixture(scope="module")
def destroy_payloads() -> list[tuple[str, dict]]:
    """Every ``destroy_target_permanent`` payload in both manifest roles.

    ``include_measured=True`` deliberately: a measured set is where a new
    narrowing arrives, and a guard that waited for promotion would let the set
    be implemented against a gate that ignores it.
    """
    found: list[tuple[str, dict]] = []
    seen_cards: dict[str, object] = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards([path]):
            seen_cards.setdefault(card.oracle_id or card.name, card)

    def walk(name: str, instructions) -> None:
        for instruction in instructions:
            if instruction.kind == "destroy_target_permanent":
                found.append((name, instruction.payload))
            for value in instruction.payload.values():
                if isinstance(value, (list, tuple)):
                    nested = [
                        item for item in value
                        if hasattr(item, "kind") and hasattr(item, "payload")
                    ]
                    if nested:
                        walk(name, nested)

    for card in compilation_units(seen_cards.values()):
        try:
            program = compile_card_oracle(card)
        except Exception:  # pragma: no cover - a card that will not compile is
            continue       # somebody else's failing test, not this guard's
        walk(card.name, program.instructions)
        for ability in program.activated_abilities:
            if ability.instruction is not None:
                walk(card.name, [ability.instruction])
        for ability in program.triggered_abilities:
            if ability.instruction is not None:
                walk(card.name, [ability.instruction])
    assert found, "no destroy_target_permanent in the pool — the walk is broken"
    return found


@pytest.fixture(scope="module")
def probe_game() -> tuple[Game, list[Permanent], list[Permanent]]:
    mine = _probe_permanents()
    theirs = _probe_permanents()
    game = Game(players=[
        PlayerState(name="P1", battlefield=mine),
        PlayerState(name="P2", battlefield=theirs),
    ])
    return game, mine, theirs


def _gate(game: Game, payload: dict, perm: Permanent) -> bool:
    return game._destroy_target_legal(
        payload, perm,
        observer=_OBSERVER, source=None,
        defending=_DEFENDING, that_player=_THAT_PLAYER,
    )


def test_the_gate_asks_the_whole_noun_phrase(destroy_payloads, probe_game):
    """What the gate offers is exactly what the matcher says the sentence names.

    Both directions, because both are failures: offering more than the card
    prints is the bug this file exists for, and offering less is an ability
    refused for a narrowing nobody printed. The gate used to ask
    ``permanent_matches_filter``, which agrees on every key it reads and
    silently says yes to every key it does not.
    """
    game, mine, theirs = probe_game
    disagreed: list[str] = []
    for name, payload in destroy_payloads:
        described = destroy_subject_filter(payload)
        for perm in mine + theirs:
            gate = _gate(game, payload, perm)
            matcher = subject_matches(
                game, perm, described,
                observer=_OBSERVER, source=None,
                defending=_DEFENDING, that_player=_THAT_PLAYER,
            )
            if gate != matcher:
                disagreed.append(
                    f"{name} on {perm.card.name}: gate {gate}, matcher {matcher}"
                )
    assert not disagreed, (
        "target gate and matcher name different sets: "
        + "; ".join(sorted(set(disagreed)))
    )


def test_every_game_relative_key_the_pool_prints_is_enforced(
    destroy_payloads, probe_game
):
    """A key the pure matcher cannot answer must be one the gate does.

    Each ``(key, value)`` the pool prints is asked **alone**, which is what
    makes the observation unambiguous: with nothing else in the payload there is
    nothing to mask it, so a disagreement between the pure matcher and the full
    one is proof that the key needs the game — and agreement is proof of
    nothing, so those keys are simply not claimed either way.

    For every key proved game-relative this way the gate must answer as the full
    matcher does and not as the pure one. Before the fix it answered as the pure
    one for all of them, which is what let Merfolk Assassin destroy a vanilla
    Bear, Pit Trap shoot down a flyer and Despotic Scepter destroy a permanent
    somebody else owned.
    """
    game, mine, theirs = probe_game
    probes = mine + theirs
    pairs: dict[tuple[str, str], object] = {}
    for _name, payload in destroy_payloads:
        for key, value in destroy_subject_filter(payload).items():
            pairs.setdefault((key, repr(value)), value)

    relative: list[str] = []
    unenforced: list[str] = []
    for (key, shown), value in sorted(pairs.items()):
        alone = {key: value}
        pure = [permanent_matches_filter(perm, alone) for perm in probes]
        full = [
            subject_matches(
                game, perm, alone,
                observer=_OBSERVER, source=None,
                defending=_DEFENDING, that_player=_THAT_PLAYER,
            )
            for perm in probes
        ]
        if pure == full:
            continue  # the board cannot tell the two apart; claim nothing
        relative.append(f"{key}={shown}")
        gate = [_gate(game, alone, perm) for perm in probes]
        if gate != full:
            unenforced.append(f"{key}={shown}")
    assert not unenforced, (
        "printed destroy narrowings the gate does not enforce: "
        + "; ".join(sorted(set(unenforced)))
    )
    # The pool really does print such keys, so the assertion above is a
    # statement about behaviour rather than about an empty set.
    assert relative, (
        "no game-relative narrowing observed at all — either the pool stopped "
        "printing one or the probe board can no longer tell them apart"
    )
