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
