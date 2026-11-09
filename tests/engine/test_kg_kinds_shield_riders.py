"""The chosen-source whole-instance shield is one instruction kind, and what a
card prints after "prevent that damage" is its ``rider`` payload key.

Reverse Damage, Bone Mask, Shadowbane and Honorable Passage print Pentagram of
the Ages' sentence — "The next time a source of your choice would deal damage
to … this turn, prevent that damage." — and then one more: CR 615.5's
additional effect (gain that much life; exile that many cards from your library;
gain it only for a black source, over you and your creatures; deal it back to a
red source's controller). The choice they make (CR 609.7a, 615.8), the picker
they run and the body that resolves them were all Pentagram's; they were four
instruction kinds anyway — ``grant_reverse_damage_shield``,
``grant_exile_prevention_shield``, ``grant_team_prevention_shield`` and
``grant_reflecting_prevention_shield`` — with four handlers wrapping one body,
and a row each in the picker table, the effect labels and the categories saying
the same thing four times.

They are ``grant_whole_prevention_shield`` with ``rider`` (the word the parse
writes, ``ast.PreventedRider.effect``) since the round that folded them, and
``handlers.prevention._whole_shield_build`` maps the rider to the ``Shield.kind``
whose interceptor performs it. Validated backwards on the base: the census
below found the five cards (Reverse Damage, Cho-Arrim Alchemist, Bone Mask,
Shadowbane, Honorable Passage) on the four retired kinds and no instruction
carrying a ``rider``; ``scripts/oracle_diff.py`` moved exactly those five, in
the kind and the new key; and the drives below logged byte-identical games
before and after (sixty scenarios in the round's scratch).
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, load_catalog, manifest_set_paths
from engine.damage_events import deal_damage
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.grammar import compile_line
from engine.handlers import EFFECT_HANDLERS
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from engine.shields import (PREVENT_AND_DAMAGE_SOURCE, PREVENT_AND_EXILE,
                            PREVENT_AND_GAIN_LIFE, PREVENT_TEAM, PREVENT_WHOLE,
                            shields_on)
from tests.helpers import resolve_stack

KIND = "grant_whole_prevention_shield"

RETIRED = (
    "grant_reverse_damage_shield",
    "grant_exile_prevention_shield",
    "grant_team_prevention_shield",
    "grant_reflecting_prevention_shield",
)

#: What each rider arms — the interceptor that performs the sentence after
#: "prevent that damage". ``recipients`` (Shadowbane's "and/or creatures you
#: control") selects the team interceptor, whose rider is the life gain.
EXPECTED_SHIELD = {
    None: PREVENT_WHOLE,
    "gain_life": PREVENT_AND_GAIN_LIFE,
    "exile_from_library": PREVENT_AND_EXILE,
    "damage_source_controller": PREVENT_AND_DAMAGE_SOURCE,
}


def _walk(obj):
    if isinstance(obj, OracleInstruction):
        yield obj
        yield from _walk(obj.payload)
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, (list, tuple, set)):
        for value in obj:
            yield from _walk(value)


def _programs():
    """Every compiled program over both manifest roles, by name."""
    seen: dict[str, object] = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        seen.setdefault(card.name, card)
    for name, card in seen.items():
        program = compile_card_oracle(card)
        found = list(_walk(program.instructions))
        for ability in program.activated_abilities:
            found += list(_walk(ability.instruction))
        for trig in program.triggered_abilities:
            found += list(_walk(trig.instruction))
        yield card, found


@pytest.fixture(scope="module")
def population():
    """``(card, instruction)`` for every whole-instance shield in the pool,
    and every instruction of a retired kind (there must be none)."""
    shields, retired = [], []
    for card, found in _programs():
        for step in found:
            if step.kind == KIND:
                shields.append((card, step))
            elif step.kind in RETIRED:
                retired.append((card.name, step.kind))
    return shields, retired


def test_no_card_compiles_to_a_retired_kind_and_no_handler_answers_one(population):
    shields, retired = population
    assert not retired, f"compiled to a folded kind: {sorted(set(retired))}"
    assert not set(RETIRED) & set(EFFECT_HANDLERS), "a folded kind is still registered"
    # A floor on what was examined: the unnarrowed shield is printed on more
    # than a dozen cards, and every rider the pool prints is among them.
    names = {card.name for card, _ in shields}
    assert len(names) >= 12, sorted(names)
    riders = {step.payload.get("rider") for _, step in shields}
    assert riders >= {None, "gain_life", "exile_from_library", "damage_source_controller"}, riders


def _context(game, card, caster, target):
    return OracleExecutionContext(caster=caster, target=target, card=card)


def test_every_rider_the_pool_prints_arms_the_shield_that_performs_it(population):
    """Run the handler for each instruction carrying a rider and read the
    shield it hung: the rider is the interceptor, so a rider armed as the
    plain shield — or as another rider's — is the card doing something else."""
    shields, _ = population
    driven = set()
    for card, step in shields:
        if "rider" not in step.payload:
            continue
        p1 = PlayerState(name="P1", life=20)
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])
        context = _context(game, card, p1, p1)
        if step.payload.get("source_from") == "target":
            # Awe Strike: the shield is keyed on the creature the spell
            # targeted, so the drive names one, as the announcement would —
            # on the seat the announcement settles (its controller's).
            source = Permanent(card=next(
                c for c in load_catalog() if c.name == "Grizzly Bears"
            ))
            game._put_permanent_onto_battlefield(1, source, None)
            context = _context(game, card, p1, p2)
            context.target_permanent_id = [source.permanent_id]
        ok, detail = EFFECT_HANDLERS[KIND](game, step, context)
        assert ok, (card.name, detail)
        armed = [shield.kind for shield in shields_on(p1)]
        expected = (
            PREVENT_TEAM if step.payload.get("recipients")
            else EXPECTED_SHIELD[step.payload["rider"]]
        )
        assert armed == [expected], (card.name, step.payload, armed)
        driven.add(card.name)
    assert driven >= {
        "Reverse Damage", "Cho-Arrim Alchemist", "Bone Mask", "Shadowbane",
        "Honorable Passage",
    }, driven


def test_a_rider_no_interceptor_performs_is_refused_rather_than_dropped():
    """The handler's own half of the gate: a payload naming a rider it has no
    shield for arms nothing and says so — never the plain shield, which would
    be a card reporting a prevention while its sentence after did nothing."""
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    card = next(c for c in load_catalog() if c.name == "Pentagram of the Ages")
    for payload in ({"rider": "an_invented_rider"},
                    {"recipients": {"type_filter": "creature", "controller": "you"},
                     "rider": "exile_from_library"}):
        ok, detail = EFFECT_HANDLERS[KIND](
            game, OracleInstruction(KIND, "", payload), _context(game, card, p1, p1)
        )
        assert not ok and "no interceptor performs" in detail, (payload, detail)
    assert shields_on(p1) == []


def test_a_team_shield_with_nothing_after_it_refuses_rather_than_paying():
    """The team interceptor gains life — unconditionally when no colour is
    recorded — so the lowering admits a shield over "you and/or creatures you
    control" only with the life rider printed. On the base this line compiled to
    the team kind with no rider, and the shield it armed gained its controller
    the damage it prevented: a card nobody prints doing more than its words."""
    result = compile_line(
        "The next time a source of your choice would deal damage to you and/or "
        "creatures you control this turn, prevent that damage.",
        card_name="An Invented Shadowbane",
    )
    assert not result.usable
    assert result.lowering_error == "the team shield's interceptor gains life and nothing else"

    printed = compile_line(
        "The next time a source of your choice would deal damage to you and/or "
        "creatures you control this turn, prevent that damage. If damage from a "
        "black source is prevented this way, you gain that much life.",
        card_name="Shadowbane",
    )
    assert printed.usable
    assert [(i.kind, i.payload) for i in printed.instructions] == [(KIND, {
        "recipients": {"type_filter": "creature", "controller": "you"},
        "rider": "gain_life",
        "rider_colors": ["B"],
    })]


# --- the five cards, driven through the real entry points -------------------

CATALOG = {card.name: card for card in load_catalog()}


def _ready(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _board(name: str, chosen_name: str, *, interactive: bool, activated: bool):
    chosen = _ready(Permanent(card=CATALOG[chosen_name]))
    other = _ready(Permanent(card=CATALOG["Grizzly Bears"]))
    mine = _ready(Permanent(card=CATALOG["Savannah Lions"]))
    battlefield, hand = [mine], [CATALOG["Island"], CATALOG["Island"]]
    if activated:
        battlefield.insert(0, _ready(Permanent(card=CATALOG[name])))
    else:
        hand.insert(0, CATALOG[name])
    p1 = PlayerState(name="P1", battlefield=battlefield, hand=hand,
                     library=[CATALOG["Island"]] * 10, life=20)
    p2 = PlayerState(name="P2", battlefield=[chosen, other],
                     hand=[CATALOG["Lightning Bolt"]],
                     library=[CATALOG["Island"]] * 10, life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    return game, p1, p2, chosen, other, mine


def _dealt(game, recipient, amount, source) -> int:
    """One damage event through CR 120.4 (applying it is the caller's job, so
    the life totals below move only by what the riders do)."""
    outcome = deal_damage(
        game, {"recipient": recipient, "amount": amount, "source": source, "combat": False}
    )
    game._settle()
    return outcome.dealt


#: name -> (activated?, colour of the chosen source, how it is announced)
DRIVEN = {
    "Reverse Damage": (False, "Hill Giant", "target"),
    "Cho-Arrim Alchemist": (True, "Hill Giant", "target"),
    "Bone Mask": (True, "Hill Giant", "target"),
    "Shadowbane": (False, "Cadaverous Knight", "target"),
    "Honorable Passage": (False, "Hill Giant", "chosen_source"),
}


@pytest.mark.parametrize("interactive", [False, True], ids=["default", "interactive"])
@pytest.mark.parametrize("name", sorted(DRIVEN))
def test_the_shield_answers_only_its_chosen_source_and_then_its_rider_runs(name, interactive):
    activated, chosen_name, channel = DRIVEN[name]
    game, p1, p2, chosen, other, mine = _board(
        name, chosen_name, interactive=interactive, activated=activated,
    )
    if channel == "target":
        if activated:
            result = game.activate_permanent_ability(
                0, name, target_player_index=1, target_permanent_index=0
            )
        else:
            result = game.cast_from_hand(
                0, name, target_player_index=1, target_permanent_ids=[chosen.permanent_id]
            )
    else:
        result = game.cast_from_hand(
            0, name, target_player_index=0,
            chosen_source_seat=1, chosen_source_permanent_index=0,
        )
    assert result.supported, result.details
    resolve_stack(game)

    if name == "Shadowbane":
        # "…to you **and/or creatures you control**": the black source's damage
        # to the caster's creature is the instance the shield spends, and the
        # caster — not the creature — gains it.
        assert _dealt(game, mine, 2, chosen) == 0, game.log
        assert p1.life == 22, game.log
        assert _dealt(game, p1, 3, chosen) == 3, "a one-shot shield is spent"
        return
    assert _dealt(game, p1, 2, other) == 2, f"an unchosen source is not this shield's: {game.log}"
    assert _dealt(game, p1, 3, chosen) == 0, game.log
    assert _dealt(game, p1, 1, chosen) == 1, "spent on the one instance (CR 615.8)"
    if name in ("Reverse Damage", "Cho-Arrim Alchemist"):
        assert p1.life == 23, game.log
    elif name == "Bone Mask":
        assert (len(p1.library), len(p1.exile)) == (7, 3), game.log
        assert p1.life == 20
    elif name == "Honorable Passage":
        assert p2.life == 17, f"a red source's controller takes it back: {game.log}"
        assert p1.life == 20


@pytest.mark.parametrize("name", ["Reverse Damage", "Honorable Passage", "Bone Mask"])
def test_a_spell_on_the_stack_is_a_source_the_shield_answers(name):
    """CR 609.7a: the source may be a spell, matched by the card it deals its
    damage with. Lightning Bolt goes on the stack at the caster; the shield is
    announced in response naming it, and resolves first."""
    activated, chosen_name, channel = DRIVEN[name]
    game, p1, p2, chosen, other, mine = _board(
        name, chosen_name, interactive=False, activated=activated,
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    if activated:
        result = game.queue_permanent_ability(0, name, target_stack_index=0)
    elif channel == "chosen_source":
        result = game.queue_from_hand(0, name, target_player_index=0, chosen_source_stack_index=0)
    else:
        result = game.queue_from_hand(0, name, target_stack_index=0)
    assert result.supported, result.details
    resolve_stack(game)

    assert f"{name} prevented 3 damage to P1" in " ".join(game.log), game.log
    if name == "Reverse Damage":
        assert p1.life == 23
    elif name == "Honorable Passage":
        assert (p1.life, p2.life) == (20, 17), "Lightning Bolt is red"
    else:
        assert (p1.life, len(p1.exile)) == (20, 3)
