"""Per-card tests for Antiquities' artifacts.

See tests/sets/README.md for the convention; ROADMAP's ATQ rounds for why each
of these was blocked.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


# ---------------------------------------------------------------------------
# Urza's Chalice (round 3) — "whenever a player casts an artifact spell"
# ---------------------------------------------------------------------------


def test_urzas_chalice_triggers_on_an_artifact_spell(set_pool):
    pool = set_pool("ATQ")
    chalice = Permanent(card=pool["Urza's Chalice"])
    p1 = PlayerState(name="P1", battlefield=[chalice], hand=[pool["Ornithopter"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Ornithopter")

    assert any("Urza's Chalice" in entry for entry in game.log), game.log


def test_urzas_chalice_ignores_a_nonartifact_spell(set_pool):
    """The narrowing under load. Before the `cast_type` row existed the line
    refused outright, so the card was unsupported rather than over-firing —
    but the dispatcher already read a narrowing key nothing emitted, and a
    bare `spell_cast` row would have fired this trigger on every spell."""
    pool = set_pool("ATQ")
    chalice = Permanent(card=pool["Urza's Chalice"])
    p1 = PlayerState(name="P1", battlefield=[chalice], hand=[pool["Detonate"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Detonate")

    assert not any("Urza's Chalice" in entry for entry in game.log), game.log


def test_urzas_chalice_compiles_its_optional_payment(set_pool):
    program = compile_card_oracle(set_pool("ATQ")["Urza's Chalice"])
    (trigger,) = program.triggered_abilities

    assert trigger.supported
    assert trigger.condition.kind == "spell_cast"
    assert trigger.condition.payload["cast_type"] == "artifact"
    assert trigger.instruction.kind == "may"


# ---------------------------------------------------------------------------
# Tablet of Epityr (round 3) — "whenever an artifact you control is put into a
# graveyard from the battlefield"
# ---------------------------------------------------------------------------


def _dies(game, seat, permanent):
    game._permanent_to_graveyard(game.players[seat], permanent)


def test_tablet_of_epityr_triggers_when_your_artifact_dies(set_pool):
    pool = set_pool("ATQ")
    tablet = Permanent(card=pool["Tablet of Epityr"])
    doomed = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[tablet, doomed])
    game = Game(players=[p1, PlayerState(name="P2")])

    _dies(game, 0, doomed)

    # CR 603.3: a trigger goes on the stack and resolves later, so the stack is
    # what the announcement is observable as — not a log line, which only
    # appears once it resolves.
    assert [item.card.name for item in game.stack] == ["Tablet of Epityr"]


def test_tablet_of_epityr_ignores_an_opponents_artifact(set_pool):
    """"an artifact **you control**" is relative to the controller of the
    triggered ability (CR 109.5), not to the dying permanent's controller —
    which is why the dispatcher passes the observer's seat to subject_matches
    rather than the dead permanent's."""
    pool = set_pool("ATQ")
    tablet = Permanent(card=pool["Tablet of Epityr"])
    theirs = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[tablet])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    _dies(game, 1, theirs)

    assert game.stack == []


def test_tablet_of_epityr_ignores_a_dying_creature(set_pool):
    """The type half of the same narrowing."""
    pool = set_pool("ATQ")
    tablet = Permanent(card=pool["Tablet of Epityr"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[tablet, druid])
    game = Game(players=[p1, PlayerState(name="P2")])

    _dies(game, 0, druid)

    assert [item.card.name for item in game.stack] == []


# ---------------------------------------------------------------------------
# Ashnod's Battle Gear / Tawnos's Weaponry (round 5) — a linked duration
# ---------------------------------------------------------------------------


def _weaponry_and_creature(set_pool):
    """Tawnos's Weaponry (+1/+1) rather than Ashnod's Battle Gear (+2/-2).

    The Gear is the sharper card and the worse fixture: -2 toughness kills any
    small creature outright through CR 704.5f, so the boost would be measured
    on a permanent that is no longer there. Its own behaviour is asserted
    separately below, on a creature big enough to survive it.
    """
    pool = set_pool("ATQ")
    weaponry = Permanent(card=pool["Tawnos's Weaponry"])
    creature = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[weaponry, creature])
    game = Game(players=[p1, PlayerState(name="P2")])
    return game, weaponry, creature


def test_tawnoss_weaponry_boosts_while_tapped(set_pool):
    game, weaponry, creature = _weaponry_and_creature(set_pool)
    base_power, base_toughness = creature.effective_power, creature.effective_toughness

    game.activate_permanent_ability(0, "Tawnos's Weaponry", target_permanent_index=1)

    assert weaponry.tapped, "the ability costs {T}"
    assert creature.effective_power == base_power + 1
    assert creature.effective_toughness == base_toughness + 1


def test_the_boost_ends_the_moment_the_source_untaps(set_pool):
    """The reason this is a linked duration and not an until-end-of-turn pump.
    Nothing schedules the removal — the boost is contributed while the source
    is tapped and simply stops being contributed when it is not, so untapping
    mid-turn ends it rather than the cleanup step doing so.
    """
    game, weaponry, creature = _weaponry_and_creature(set_pool)
    base_power = creature.effective_power

    game.activate_permanent_ability(0, "Tawnos's Weaponry", target_permanent_index=1)
    assert creature.effective_power == base_power + 1

    weaponry.tapped = False
    game._refresh_dynamic_creatures()

    assert creature.effective_power == base_power


def test_the_boost_does_not_compound_across_recomputes(set_pool):
    """Aspect of Wolf's bug class: a delta written onto the pumped creature has
    to be subtracted again, and a subtraction that does not exactly match its
    addition compounds on every refresh — and CR 611.3a means refreshes are
    constant. Contributing to the derived channel makes the question moot, and
    this is what would notice if that ever changed."""
    game, weaponry, creature = _weaponry_and_creature(set_pool)
    base_power = creature.effective_power

    game.activate_permanent_ability(0, "Tawnos's Weaponry", target_permanent_index=1)
    for _ in range(5):
        game._refresh_dynamic_creatures()

    assert creature.effective_power == base_power + 1


def test_ashnods_battle_gear_is_a_real_drawback(set_pool):
    """+2/-2, and the minus is not decoration: a 1/1 given it dies to CR 704.5f
    before the boost can be read anywhere."""
    pool = set_pool("ATQ")
    gear = Permanent(card=pool["Ashnod's Battle Gear"])
    fragile = Permanent(card=pool["Citanul Druid"])  # 1/1
    p1 = PlayerState(name="P1", battlefield=[gear, fragile])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.activate_permanent_ability(0, "Ashnod's Battle Gear", target_permanent_index=1)

    assert fragile not in list(game.all_permanents())


# ---------------------------------------------------------------------------
# Golgothian Sylex (round 7)
# ---------------------------------------------------------------------------


def test_golgothian_sylex_sacrifices_antiquities_permanents(set_pool):
    pool = set_pool("ATQ")
    sylex = Permanent(card=pool["Golgothian Sylex"])
    thopter = Permanent(card=pool["Ornithopter"])
    survivor = Permanent(card=pool["Mishra's Workshop"])  # a land, also ATQ
    p1 = PlayerState(name="P1", battlefield=[sylex, thopter, survivor])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Golgothian Sylex")

    names = {perm.card.name for perm in game.all_permanents()}
    assert "Ornithopter" not in names
    assert "Mishra's Workshop" not in names, "every nontoken ATQ permanent, not only creatures"
    assert "Golgothian Sylex" not in names, "the Sylex is an Antiquities card too"


def test_golgothian_sylex_spares_a_permanent_from_another_set(set_pool, catalog_by_name):
    pool = set_pool("ATQ")
    sylex = Permanent(card=pool["Golgothian Sylex"])
    bystander = Permanent(card=catalog_by_name["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[sylex, bystander])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Golgothian Sylex")

    assert "Grizzly Bears" in {perm.card.name for perm in game.all_permanents()}


def test_the_set_name_is_resolved_through_the_manifest(set_pool):
    """The card prints a set *name* and the effect needs its code. Reading the
    manifest — the registry that already holds both — is what keeps this from
    being a second table that could disagree with it about what a set is
    called, and is why Apocalypse Chime would need no code at all."""
    program = compile_card_oracle(set_pool("ATQ")["Golgothian Sylex"])
    (ability,) = program.activated_abilities

    assert ability.instruction.payload["set_code"] == "atq"


# ---------------------------------------------------------------------------
# Feldon's Cane (round 10)
# ---------------------------------------------------------------------------


def test_feldons_cane_moves_the_whole_graveyard_and_exiles_itself(set_pool):
    pool = set_pool("ATQ")
    cane = Permanent(card=pool["Feldon's Cane"])
    graveyard = [pool["Ornithopter"], pool["Jalum Tome"], pool["Citanul Druid"]]
    p1 = PlayerState(name="P1", battlefield=[cane], graveyard=list(graveyard), library=[])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Feldon's Cane")

    assert p1.graveyard == [], "every card in it goes — that is what 'your graveyard' means"
    assert len(p1.library) == 3
    assert "Feldon's Cane" not in {perm.card.name for perm in game.all_permanents()}, (
        "'Exile this artifact' is part of the cost (CR 601.2h)"
    )


def test_feldons_cane_leaves_an_opponents_graveyard_alone(set_pool):
    pool = set_pool("ATQ")
    cane = Permanent(card=pool["Feldon's Cane"])
    p1 = PlayerState(name="P1", battlefield=[cane], graveyard=[pool["Ornithopter"]], library=[])
    p2 = PlayerState(name="P2", graveyard=[pool["Jalum Tome"]], library=[])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Feldon's Cane")

    assert len(p2.graveyard) == 1


# ---------------------------------------------------------------------------
# Ashnod's Transmogrant / Xenic Poltergeist (round 11) — gained types
# ---------------------------------------------------------------------------


def test_ashnods_transmogrant_makes_a_creature_an_artifact_permanently(set_pool):
    """"in addition to its other types", and with no duration at all — the
    creature is still an artifact long after the Transmogrant has been
    sacrificed to pay for the ability."""
    pool = set_pool("ATQ")
    transmogrant = Permanent(card=pool["Ashnod's Transmogrant"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[transmogrant, druid])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Ashnod's Transmogrant", target_permanent_index=1)

    assert druid.has_type("artifact")
    assert druid.is_creature, "'in addition to' — it does not stop being a creature"
    assert "Ashnod's Transmogrant" not in {p.card.name for p in game.all_permanents()}

    game.resolve_cleanup_step(0)
    assert druid.has_type("artifact"), "no duration means it does not wear off"


def _poltergeist_game(set_pool):
    pool = set_pool("ATQ")
    poltergeist = Permanent(card=pool["Xenic Poltergeist"])
    tome = Permanent(card=pool["Jalum Tome"])  # a {3} artifact
    p1 = PlayerState(name="P1", battlefield=[poltergeist, tome])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, tome


def test_xenic_poltergeist_animates_an_artifact_at_its_mana_value(set_pool):
    game, tome = _poltergeist_game(set_pool)
    assert not tome.is_creature

    game.activate_permanent_ability(0, "Xenic Poltergeist", target_permanent_index=1)

    assert tome.is_creature
    assert (tome.effective_power, tome.effective_toughness) == (3, 3)


def test_the_animation_ends_at_your_next_upkeep(set_pool):
    """"Until **your** next upkeep" is a real duration and not "until end of
    turn" — the two are different moments (CR 500 puts the upkeep step inside
    the turn), so the record is swept at the upkeep of the seat that made it."""
    game, tome = _poltergeist_game(set_pool)

    game.activate_permanent_ability(0, "Xenic Poltergeist", target_permanent_index=1)
    assert tome.is_creature

    game.resolve_cleanup_step(0)
    assert tome.is_creature, "the turn ending is not when this expires"

    game.resolve_upkeep(0)
    assert not tome.is_creature


# ---------------------------------------------------------------------------
# Coral Helm / Obelisk of Undoing (round 13)
# ---------------------------------------------------------------------------


def test_coral_helm_discards_without_letting_the_payer_choose(set_pool):
    """"Discard a card **at random**" is not "discard a card" with a filter —
    it removes the *choice*, and a cost the payer picks is a strictly better
    cost than one chance picks. A caller that names an index is ignored."""
    import random

    pool = set_pool("ATQ")
    helm = Permanent(card=pool["Coral Helm"])
    creature = Permanent(card=pool["Citanul Druid"])
    hand = [pool["Ornithopter"], pool["Jalum Tome"], pool["Detonate"]]
    p1 = PlayerState(name="P1", battlefield=[helm, creature], hand=list(hand))
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    random.seed(7)
    base = creature.effective_power

    result = game.activate_permanent_ability(
        0, "Coral Helm", target_permanent_index=1, cost_hand_index=0
    )

    assert result.supported
    assert creature.effective_power == base + 2
    assert len(p1.hand) == 2 and len(p1.graveyard) == 1


def test_obelisk_of_undoing_refuses_a_permanent_you_only_control(set_pool):
    """"you both **own** and control" — ownership (CR 108.3) never changes and
    control (CR 613 layer 2) does, and this card is printed for the case where
    they differ. Reading one as the other returns a stolen permanent to the
    thief's hand."""
    from engine.control import change_control

    pool = set_pool("ATQ")
    obelisk = Permanent(card=pool["Obelisk of Undoing"])
    theirs = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[obelisk])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(1, theirs, None)
    change_control(theirs, 0, source=obelisk)
    game._sync_control()
    assert game.controls(0, theirs), "the fixture needs it stolen, not given"

    game.activate_permanent_ability(0, "Obelisk of Undoing", target_permanent_index=1)

    assert "Citanul Druid" in {p.card.name for p in game.all_permanents()}
    assert not p1.hand, "it is not your card to take"


# ---------------------------------------------------------------------------
# Candelabra of Tawnos (round 16) — a counted, variable target list
# ---------------------------------------------------------------------------


def _candelabra(set_pool, land_count=3):
    pool = set_pool("ATQ")
    candelabra = Permanent(card=pool["Candelabra of Tawnos"])
    lands = [Permanent(card=pool["Mishra's Workshop"]) for _ in range(land_count)]
    for land in lands:
        land.tapped = True
    p1 = PlayerState(name="P1", battlefield=[candelabra, *lands])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, lands


def test_candelabra_untaps_exactly_the_lands_named(set_pool):
    game, lands = _candelabra(set_pool)

    game.activate_permanent_ability(
        0, "Candelabra of Tawnos", x_value=2,
        target_player_index=0, target_permanent_index=[1, 2],
    )

    assert [not land.tapped for land in lands] == [True, True, False]


def test_candelabra_untaps_only_lands(set_pool):
    """The printed noun phrase is enforced at resolution as well as at
    announcement. `resolve_target_permanents` defaults to "is it a creature?",
    which would have matched none of these — and on a card that did name
    creatures would have skipped the rest of the phrase."""
    pool = set_pool("ATQ")
    candelabra = Permanent(card=pool["Candelabra of Tawnos"])
    creature = Permanent(card=pool["Citanul Druid"])
    creature.tapped = True
    p1 = PlayerState(name="P1", battlefield=[candelabra, creature])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(
        0, "Candelabra of Tawnos", x_value=1,
        target_player_index=0, target_permanent_index=[1],
    )

    assert creature.tapped, "a creature is not a land"


# ---------------------------------------------------------------------------
# Urza's Miter (round 17) — an intervening-if about how it died
# ---------------------------------------------------------------------------


def _miter_and_fodder(set_pool):
    pool = set_pool("ATQ")
    miter = Permanent(card=pool["Urza's Miter"])
    fodder = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[miter, fodder])
    game = Game(players=[p1, PlayerState(name="P2")])
    return game, fodder


def test_urzas_miter_triggers_when_an_artifact_is_destroyed(set_pool):
    game, fodder = _miter_and_fodder(set_pool)

    game._permanent_to_graveyard(game.players[0], fodder)

    assert [item.card.name for item in game.stack] == ["Urza's Miter"]


def test_urzas_miter_stays_quiet_when_the_artifact_was_sacrificed(set_pool):
    """"…**if it wasn't sacrificed**" (CR 603.4). A sacrifice and a destruction
    leave the artifact in the same graveyard, so the graveyard cannot answer
    the question — only the record the one sacrifice transition leaves can."""
    game, fodder = _miter_and_fodder(set_pool)

    game.sacrifice_permanent(fodder)

    assert game.stack == [], (
        "the Miter fires more often than it prints if the qualifier is dropped"
    )


# ---------------------------------------------------------------------------
# Rakalite (round 21) — a delayed triggered ability on itself
# ---------------------------------------------------------------------------


def test_rakalite_prevents_one_damage_and_returns_itself(set_pool):
    from engine.damage_events import deal_damage

    pool = set_pool("ATQ")
    rakalite = Permanent(card=pool["Rakalite"])
    p1 = PlayerState(name="P1", battlefield=[rakalite])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Rakalite", target_player_index=0)
    outcome = deal_damage(
        game, {"recipient": p1, "amount": 3, "source": None, "combat": False}
    )

    assert outcome.dealt == 2, "one of the three prevented"
    assert "Rakalite" in {perm.card.name for perm in game.all_permanents()}, (
        "it is still there until the end step — the return is delayed (CR 603.7)"
    )

    game.resolve_end_step(0)

    assert "Rakalite" not in {perm.card.name for perm in game.all_permanents()}
    assert [card.name for card in p1.hand] == ["Rakalite"]


def test_the_return_is_delayed_not_immediate(set_pool):
    """The whole sentence is one production for this reason: the action on its
    own is performed *now*, and an artifact that bounces itself the moment its
    ability resolves can only be used once per turn cycle instead of once per
    activation."""
    pool = set_pool("ATQ")
    rakalite = Permanent(card=pool["Rakalite"])
    p1 = PlayerState(name="P1", battlefield=[rakalite])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Rakalite", target_player_index=0)
    game.activate_permanent_ability(0, "Rakalite", target_player_index=0)

    assert p1.damage_prevention_pool == 2, "two activations, two shields"


# ---------------------------------------------------------------------------
# Tawnos's Coffin (round 28) — a linked exile that comes back the way it left
# ---------------------------------------------------------------------------


def _coffin_board(set_pool, *, aura=True, counters=2):
    from engine.auras import attach_aura
    from engine.pt import add_plus1_counters

    pool = set_pool("ATQ")
    coffin = Permanent(card=pool["Tawnos's Coffin"])
    victim = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[coffin])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    if aura:
        ward = Permanent(card=pool["Artifact Ward"])
        game._put_permanent_onto_battlefield(1, ward, None)
        attach_aura(ward, victim)
    if counters:
        add_plus1_counters(victim, counters)
    return game, p1, p2, coffin, victim


def _shut_the_lid(game):
    return game.activate_permanent_ability(
        0, "Tawnos's Coffin", target_player_index=1, target_permanent_index=0
    )


def test_the_coffin_exiles_the_creature_and_its_auras(set_pool):
    game, p1, p2, coffin, victim = _coffin_board(set_pool)

    result = _shut_the_lid(game)

    assert result.supported, result.details
    assert p2.battlefield == []
    assert [card.name for card in p2.exile] == ["Citanul Druid", "Artifact Ward"]


def test_untapping_the_coffin_gives_everything_back(set_pool):
    """"When this artifact leaves the battlefield **or becomes untapped**." The
    second half is the one the card is played for, and `become_untapped` is the
    one place a permanent untaps — a return wired into any single untapper
    would be a return the other ten forgot."""
    game, p1, p2, coffin, victim = _coffin_board(set_pool)
    _shut_the_lid(game)

    game.become_untapped(coffin)

    returned = {perm.card.name: perm for perm in p2.battlefield}
    assert set(returned) == {"Citanul Druid", "Artifact Ward"}
    assert returned["Citanul Druid"].tapped is True, "…to the battlefield tapped"
    assert p2.exile == []


def test_the_noted_counters_come_back_with_it(set_pool):
    """"…with the noted number and kind of counters on it." Noted, not derived:
    by the time the return runs the permanent is gone, and what comes back is a
    new object (CR 400.7) with no counters at all."""
    game, p1, p2, coffin, victim = _coffin_board(set_pool, counters=2)
    _shut_the_lid(game)

    game.become_untapped(coffin)

    druid = next(p for p in p2.battlefield if p.card.name == "Citanul Druid")
    assert druid.metadata["plus_counters"] == 2
    assert (druid.effective_power, druid.effective_toughness) == (3, 3)


def test_the_auras_go_back_onto_the_creature(set_pool):
    """"…**attached to that permanent**." An Aura that came back unattached
    would be binned by the CR 704.5n sweep on the next check, which is a
    strictly worse card than the one printed."""
    game, p1, p2, coffin, victim = _coffin_board(set_pool)
    _shut_the_lid(game)

    game.become_untapped(coffin)

    aura = next(p for p in p2.battlefield if p.card.name == "Artifact Ward")
    druid = next(p for p in p2.battlefield if p.card.name == "Citanul Druid")
    assert aura.metadata.get("attached_to") is druid


def test_the_coffin_leaving_gives_everything_back_too(set_pool):
    """The other half of the printed trigger, through the one transition off
    the battlefield."""
    game, p1, p2, coffin, victim = _coffin_board(set_pool)
    _shut_the_lid(game)

    game.remove_from_battlefield(coffin)

    assert {perm.card.name for perm in p2.battlefield} == {
        "Citanul Druid", "Artifact Ward",
    }


def test_nothing_comes_back_while_the_coffin_stays_tapped(set_pool):
    """The control: the return is the trigger's, not the activation's. Without
    it every test above would pass against a card that exiled nothing."""
    game, p1, p2, coffin, victim = _coffin_board(set_pool)

    _shut_the_lid(game)

    assert coffin.tapped is True
    assert p2.battlefield == []
