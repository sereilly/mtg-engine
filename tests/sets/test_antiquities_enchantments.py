"""Per-card tests for Antiquities' enchantments.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# ---------------------------------------------------------------------------
# Haunting Wind / Powerleech (round 6) — one ability, two trigger events
# ---------------------------------------------------------------------------


def test_haunting_wind_fires_when_an_artifact_becomes_tapped(set_pool):
    pool = set_pool("ATQ")
    wind = Permanent(card=pool["Haunting Wind"])
    thopter = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[wind])
    p2 = PlayerState(name="P2", battlefield=[thopter])
    game = Game(players=[p1, p2])

    game.become_tapped(thopter)

    # CR 603.3: the trigger goes on the stack. Nothing drives the stack in this
    # fixture, so that is the observable here — the activation tests below go
    # through a path that resolves, and assert on the damage instead.
    assert [item.card.name for item in game.stack] == ["Haunting Wind"]


def test_haunting_wind_fires_when_an_artifact_ability_is_activated_without_tapping(set_pool):
    """The half that had no dispatcher. A declaration in two front-end tables
    is not a trigger that fires — round 140's lesson — so this asserts the
    activation seam actually announces the event."""
    pool = set_pool("ATQ")
    wind = Permanent(card=pool["Haunting Wind"])
    # Dragon Engine's "{2}: This creature gets +1/+0 until end of turn" is an
    # artifact ability with no {T} in its cost, which is exactly the condition
    # the card names.
    engine_perm = Permanent(card=pool["Dragon Engine"])
    p1 = PlayerState(name="P1", battlefield=[wind])
    p2 = PlayerState(name="P2", battlefield=[engine_perm])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    before = p2.life

    game.activate_permanent_ability(1, "Dragon Engine")

    assert not engine_perm.tapped, "the fixture needs an ability with no {T} cost"
    assert p2.life == before - 1, game.log


def test_haunting_wind_does_not_fire_twice_for_a_tap_ability(set_pool):
    """An ability that *does* tap announces the condition once, through
    become_tapped. Emitting from the activation seam as well would fire the
    same printed ability twice for one activation."""
    pool = set_pool("ATQ")
    wind = Permanent(card=pool["Haunting Wind"])
    tome = Permanent(card=pool["Jalum Tome"])  # "{2}, {T}: Draw a card, then discard a card."
    p1 = PlayerState(name="P1", battlefield=[wind])
    p2 = PlayerState(name="P2", battlefield=[tome], library=[pool["Ornithopter"]] * 3)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    before = p2.life
    game.activate_permanent_ability(1, "Jalum Tome")

    assert p2.life == before - 1, (
        f"one activation, one trigger — took {before - p2.life} damage: {game.log}"
    )


def test_haunting_wind_ignores_a_nonartifact_tapping(set_pool):
    pool = set_pool("ATQ")
    wind = Permanent(card=pool["Haunting Wind"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[wind])
    p2 = PlayerState(name="P2", battlefield=[druid])
    game = Game(players=[p1, p2])

    game.become_tapped(druid)

    assert game.stack == []


def test_powerleech_only_watches_its_opponents_artifacts(set_pool):
    """"an artifact **an opponent controls**" — the controller scope half."""
    pool = set_pool("ATQ")
    leech = Permanent(card=pool["Powerleech"])
    mine = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[leech, mine])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.become_tapped(mine)

    assert game.stack == [], "Powerleech watches an opponent's artifacts, not its own"


# ---------------------------------------------------------------------------
# Artifact Possession (round 8) — the same compound event, attached subject
# ---------------------------------------------------------------------------


def test_artifact_possession_fires_only_for_the_artifact_it_enchants(set_pool):
    """"Whenever **enchanted artifact** becomes tapped…" is an identity
    question, not a class one — and identity rather than equality, because two
    Ornithopters compare equal by value and the Aura is on exactly one."""
    from engine.auras import attach_aura

    pool = set_pool("ATQ")
    aura = Permanent(card=pool["Artifact Possession"])
    enchanted = Permanent(card=pool["Ornithopter"])
    other = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[aura])
    p2 = PlayerState(name="P2", battlefield=[enchanted, other])
    game = Game(players=[p1, p2])
    attach_aura(aura, enchanted)

    game.become_tapped(other)
    assert game.stack == [], "the look-alike must not trigger it"

    game.become_tapped(enchanted)
    assert [item.card.name for item in game.stack] == ["Artifact Possession"]


def test_the_tap_triggers_damage_the_artifacts_controller(set_pool):
    """"…deals damage to **that artifact's controller**" reads the subject of
    the event, not the seat that caused it and not the trigger controller's
    opponent.

    Every other test in this block puts the artifact on the opposing seat,
    where those three answers coincide — so a wrong reading passed. Both cards
    are asserted together because they share one condition kind with two
    announcements, and the seat has to be frozen at both: Haunting Wind watches
    every artifact, so the discriminating case is its controller's **own**
    artifact, and Artifact Possession's is the Aura on an artifact its own
    controller has.
    """
    from engine.auras import attach_aura

    pool = set_pool("ATQ")
    wind = Permanent(card=pool["Haunting Wind"])
    mine = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[wind, mine], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.become_tapped(mine)
    game.resolve_top_of_stack()
    assert (p1.life, p2.life) == (19, 20), "the artifact's controller, who is also you"

    aura = Permanent(card=pool["Artifact Possession"])
    thopter = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[aura, thopter], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    attach_aura(aura, thopter)

    game.become_tapped(thopter)
    game.resolve_top_of_stack()
    assert (p1.life, p2.life) == (18, 20)


# ---------------------------------------------------------------------------
# Circle of Protection: Artifacts (round 8)
# ---------------------------------------------------------------------------


def test_cop_artifacts_stops_damage_from_an_artifact_source(set_pool):
    from engine.damage_events import deal_damage

    pool = set_pool("ATQ")
    circle = Permanent(card=pool["Circle of Protection: Artifacts"])
    thopter = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[circle])
    p2 = PlayerState(name="P2", battlefield=[thopter])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Circle of Protection: Artifacts")
    outcome = deal_damage(
        game, {"recipient": p1, "amount": 4, "source": thopter, "combat": False}
    )

    assert outcome.dealt == 0, game.log


def test_cop_artifacts_does_not_stop_a_creature(set_pool):
    """CR 615.9 rechecks the property the shield recorded. A colour Circle
    holding a colour and this one holding a card type are the same shield with
    different questions, and neither answers the other's."""
    from engine.damage_events import deal_damage

    pool = set_pool("ATQ")
    circle = Permanent(card=pool["Circle of Protection: Artifacts"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[circle])
    p2 = PlayerState(name="P2", battlefield=[druid])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Circle of Protection: Artifacts")
    outcome = deal_damage(
        game, {"recipient": p1, "amount": 4, "source": druid, "combat": False}
    )

    assert outcome.dealt == 4, game.log


# ---------------------------------------------------------------------------
# Damping Field (round 14) — the third constrained untap type
# ---------------------------------------------------------------------------


def test_damping_field_lets_only_one_artifact_untap(set_pool):
    pool = set_pool("ATQ")
    field = Permanent(card=pool["Damping Field"])
    artifacts = [Permanent(card=pool["Ornithopter"]) for _ in range(3)]
    for perm in artifacts:
        perm.tapped = True
    p1 = PlayerState(name="P1", battlefield=[field, *artifacts])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.resolve_untap_step(0)

    assert sum(1 for perm in artifacts if not perm.tapped) == 1


def test_damping_field_leaves_lands_and_creatures_alone(set_pool):
    """The restriction names artifacts. Winter Orb's land limit and Smoke's
    creature limit are separate entries in the same map — one constrained type
    must not constrain the others."""
    pool = set_pool("ATQ")
    field = Permanent(card=pool["Damping Field"])
    lands = [Permanent(card=pool["Mishra's Workshop"]) for _ in range(2)]
    creatures = [Permanent(card=pool["Citanul Druid"]) for _ in range(2)]
    for perm in (*lands, *creatures):
        perm.tapped = True
    p1 = PlayerState(name="P1", battlefield=[field, *lands, *creatures])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.resolve_untap_step(0)

    assert all(not perm.tapped for perm in lands)
    assert all(not perm.tapped for perm in creatures)


def test_the_untap_prompt_names_artifacts(set_pool):
    """The limits map is what the browser builds its noun phrase from, so a
    third constrained type has to arrive there as data rather than as a third
    named field."""
    pool = set_pool("ATQ")
    field = Permanent(card=pool["Damping Field"])
    artifacts = [Permanent(card=pool["Ornithopter"]) for _ in range(3)]
    for perm in artifacts:
        perm.tapped = True
    p1 = PlayerState(name="P1", battlefield=[field, *artifacts])
    game = Game(players=[p1, PlayerState(name="P2")])

    options = game.get_untap_land_selection_options(0)

    assert options is not None
    assert options["limits"] == {"artifact": 1}
    assert options["max_count"] == 1


# ---------------------------------------------------------------------------
# Power Artifact (round 19) — the first cost *reduction*
# ---------------------------------------------------------------------------


def _tome_with_power_artifact(set_pool, mana, attached=True):
    from engine.auras import attach_aura

    pool = set_pool("ATQ")
    tome = Permanent(card=pool["Jalum Tome"])  # "{2}, {T}: Draw a card, then discard a card."
    aura = Permanent(card=pool["Power Artifact"])
    battlefield = [tome, aura] if attached else [tome]
    p1 = PlayerState(
        name="P1", battlefield=battlefield,
        library=[pool["Ornithopter"]] * 3, hand=[pool["Detonate"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True
    if attached:
        attach_aura(aura, tome)
    p1.mana_pool["C"] = mana
    return game, p1


def test_power_artifact_reduces_the_enchanted_artifacts_ability(set_pool):
    game, p1 = _tome_with_power_artifact(set_pool, mana=1)

    result = game.activate_permanent_ability(0, "Jalum Tome")

    assert result.supported, "a {2} ability costs {1} under Power Artifact"
    assert p1.mana_pool["C"] == 0


def test_the_floor_stops_the_ability_becoming_free(set_pool):
    """"This effect **can't reduce the mana in that cost to less than one
    mana**." A {2} ability reduced by {2} pays {1}, not nothing — the floor is
    the second half of the printed card and a reduction without it is a
    strictly better Power Artifact."""
    game, p1 = _tome_with_power_artifact(set_pool, mana=0)

    result = game.activate_permanent_ability(0, "Jalum Tome")

    assert not result.supported


def test_without_the_aura_the_ability_costs_what_it_prints(set_pool):
    """The control. Without it the test above would pass against a rule that
    made every ability cost {1}."""
    game, p1 = _tome_with_power_artifact(set_pool, mana=1, attached=False)

    assert not game.activate_permanent_ability(0, "Jalum Tome").supported


# ---------------------------------------------------------------------------
# Artifact Ward (round 22) — three sentences, three existing tables
# ---------------------------------------------------------------------------


def _warded(set_pool, *, attached=True):
    """A creature on P2's battlefield, enchanted by P1's Artifact Ward."""
    from engine.auras import attach_aura

    pool = set_pool("ATQ")
    ward = Permanent(card=pool["Artifact Ward"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[ward])
    p2 = PlayerState(name="P2", battlefield=[druid])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    if attached:
        attach_aura(ward, druid)
    return game, pool, druid


def test_artifact_ward_stops_an_artifact_creature_blocking(set_pool):
    """Argothian Pixies prints this restriction about itself; the Ward prints
    it about what it enchants. One table row, read through the attached
    channel."""
    game, pool, druid = _warded(set_pool)
    thopter = Permanent(card=pool["Ornithopter"])
    game.players[0].battlefield.append(thopter)

    assert game._can_block_attacker(thopter, druid) is False


def test_an_unwarded_creature_can_still_be_blocked_by_an_artifact(set_pool):
    """The control: without it the test above would pass against a rule that
    stopped every artifact creature blocking anything."""
    game, pool, druid = _warded(set_pool, attached=False)
    thopter = Permanent(card=pool["Ornithopter"])
    game.players[0].battlefield.append(thopter)

    assert game._can_block_attacker(thopter, druid) is True


def test_artifact_ward_prevents_damage_from_an_artifact_source(set_pool):
    from engine.damage_events import deal_damage

    game, pool, druid = _warded(set_pool)
    thopter = Permanent(card=pool["Ornithopter"])
    game.players[0].battlefield.append(thopter)

    outcome = deal_damage(
        game, {"recipient": druid, "amount": 3, "source": thopter, "combat": False}
    )

    assert outcome.dealt == 0, game.log


def test_artifact_ward_leaves_damage_from_a_creature_alone(set_pool):
    """The narrowing: the sentence names artifact sources."""
    from engine.damage_events import deal_damage

    game, pool, druid = _warded(set_pool)
    treefolk = Permanent(card=pool["Argothian Treefolk"])
    game.players[0].battlefield.append(treefolk)

    outcome = deal_damage(
        game, {"recipient": druid, "amount": 3, "source": treefolk, "combat": False}
    )

    assert outcome.dealt == 3, game.log


def test_the_ward_does_not_shield_itself(set_pool):
    """"Dealt to **enchanted** creature" is not "dealt to this enchantment".
    Deriving the shield by reading a permanent's text is what makes this worth
    a test — the Aura is a permanent, and one permissive matcher would have it
    shielding itself from a class of source it never mentions protecting it
    from."""
    from engine.damage_events import deal_damage

    game, pool, druid = _warded(set_pool)
    ward = game.players[0].battlefield[0]
    thopter = Permanent(card=pool["Ornithopter"])
    game.players[0].battlefield.append(thopter)

    outcome = deal_damage(
        game, {"recipient": ward, "amount": 2, "source": thopter, "combat": False}
    )

    assert outcome.dealt == 2, game.log


def test_artifact_ward_hides_the_creature_from_an_artifacts_ability(set_pool):
    """Staff of Zegon: "{3}, {T}: Target creature gets -2/-0 until end of
    turn." An artifact source, so the warded creature is not offered."""
    game, pool, druid = _warded(set_pool)
    staff = Permanent(card=pool["Staff of Zegon"])
    game.players[0].battlefield.append(staff)

    spec = game.activation_target_spec(0, len(game.players[0].battlefield) - 1)

    assert "Citanul Druid" not in {t["name"] for t in spec["valid_targets"]}


def test_without_the_ward_the_artifacts_ability_offers_the_creature(set_pool):
    game, pool, druid = _warded(set_pool, attached=False)
    staff = Permanent(card=pool["Staff of Zegon"])
    game.players[0].battlefield.append(staff)

    spec = game.activation_target_spec(0, len(game.players[0].battlefield) - 1)

    assert "Citanul Druid" in {t["name"] for t in spec["valid_targets"]}


def test_artifact_ward_does_not_stop_a_spell(set_pool):
    """The sentence names *abilities*. Asked of the very same artifact with no
    ability behind the question — which is how a spell asks it — the answer is
    still yes, so what the immunity reads is the ability and not the source
    alone."""
    game, pool, druid = _warded(set_pool)

    assert game._can_be_targeted(druid, pool["Staff of Zegon"]) is True
