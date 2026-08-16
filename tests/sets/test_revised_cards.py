"""Per-card tests for Revised Edition (3ED) additions.

Revised is mostly a reprint set, but it introduced a handful of cards the
engine had never seen. These use invented cards carrying the printed text
rather than the catalog, because the set is not in the manifest yet — the point
is that the *templates* work, which is what makes ingesting it cheap.
"""

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle


@pytest.fixture(scope="module")
def catalog():
    return {c.name: c for c in load_catalog()}


def _spell(catalog, name, text, cost="{2}", cmc=2.0):
    return dataclasses.replace(
        catalog["Shatter"], name=name, mana_cost=cost, cmc=cmc, oracle_text=text
    )


# ---------------------------------------------------------------------------
# Millstone — mill, which every set after this one uses
# ---------------------------------------------------------------------------

def test_millstone_mills_the_named_number(catalog):
    card = dataclasses.replace(
        catalog["Jayemdae Tome"], name="Millstone", mana_cost="{2}", cmc=2.0,
        oracle_text="{2}, {T}: Target player mills two cards.",
    )
    program = compile_card_oracle(card)
    assert program.supported
    ability = program.activated_abilities[0]
    assert ability.instruction.kind == "mill_target_player"
    assert ability.instruction.payload["amount"] == 2

    stone = Permanent(card=card)
    stone.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[stone])
    p2 = PlayerState(name="P2", library=[catalog["Forest"]] * 5)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Millstone", target_player_index=1)

    assert len(p2.library) == 3
    assert len(p2.graveyard) == 2


def test_mill_count_is_a_parameter_not_a_rule_per_number(catalog):
    """The number is read from the text, spelled out or numeric."""
    from engine.grammar import compile_line

    for text, expected in (
        ("Target player mills two cards.", 2),
        ("Target player mills 5 cards.", 5),
        ("Target player mills ten cards.", 10),
    ):
        result = compile_line(text)
        assert result.usable, (text, result.failure_reason)
        assert [i.kind for i in result.instructions] == ["mill_target_player"], text
        assert result.instructions[0].payload["amount"] == expected, text


def test_mill_stops_at_an_empty_library_without_losing_the_game(catalog):
    """CR 704.5b fires on an attempted *draw* from an empty library, not on
    milling more cards than remain."""
    card = dataclasses.replace(
        catalog["Jayemdae Tome"], name="Millstone", mana_cost="{2}", cmc=2.0,
        oracle_text="{2}, {T}: Target player mills two cards.",
    )
    stone = Permanent(card=card)
    stone.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[stone])
    p2 = PlayerState(name="P2", library=[catalog["Forest"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Millstone", target_player_index=1)
    game.check_state_based_actions()

    assert p2.library == []
    assert len(p2.graveyard) == 1
    assert not p2.lost


# ---------------------------------------------------------------------------
# Hurkyl's Recall — ownership, not control
# ---------------------------------------------------------------------------

def test_hurkyls_recall_returns_artifacts_to_their_owners_hand(catalog):
    card = _spell(
        catalog, "Hurkyl's Recall",
        "Return all artifacts target player owns to their hand.", "{1}{U}", 2.0,
    )
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=catalog["Sol Ring"]), Permanent(card=catalog["Grizzly Bears"])],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Hurkyl's Recall", target_player_index=1)

    assert [p.card.name for p in p2.battlefield] == ["Grizzly Bears"]
    assert [c.name for c in p2.hand] == ["Sol Ring"]


def test_hurkyls_recall_leaves_another_players_artifacts_alone(catalog):
    card = _spell(
        catalog, "Hurkyl's Recall",
        "Return all artifacts target player owns to their hand.", "{1}{U}", 2.0,
    )
    p1 = PlayerState(name="P1", hand=[card], battlefield=[Permanent(card=catalog["Sol Ring"])])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog["Jayemdae Tome"])])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Hurkyl's Recall", target_player_index=1)

    assert [p.card.name for p in p1.battlefield] == ["Sol Ring"]
    assert p2.battlefield == []


# ---------------------------------------------------------------------------
# Crumble
# ---------------------------------------------------------------------------

def test_crumble_destroys_and_gives_the_controller_its_mana_value(catalog):
    card = _spell(
        catalog, "Crumble",
        "Destroy target artifact. It can't be regenerated. That artifact's "
        "controller gains life equal to its mana value.",
        "{G}", 1.0,
    )
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog["Jayemdae Tome"])])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    before = p2.life

    game.cast_from_hand(0, "Crumble", target_player_index=1, target_permanent_index=0)

    assert p2.battlefield == []
    assert p2.life == before + 4          # Jayemdae Tome's mana value


def test_crumble_reads_the_mana_value_before_destroying(catalog):
    """The life clause is about the object the first clause destroyed, so both
    its controller and its mana value have to be read while it is still on the
    battlefield (CR 603.10 last-known information)."""
    card = _spell(
        catalog, "Crumble",
        "Destroy target artifact. It can't be regenerated. That artifact's "
        "controller gains life equal to its mana value.",
        "{G}", 1.0,
    )
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog["Black Lotus"])])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    before = p2.life

    game.cast_from_hand(0, "Crumble", target_player_index=1, target_permanent_index=0)

    assert p2.battlefield == []
    assert p2.life == before              # Black Lotus's mana value is 0


# ---------------------------------------------------------------------------
# Titania's Song — a static that changes objects its source does not own
# ---------------------------------------------------------------------------

def _song(catalog):
    return dataclasses.replace(
        catalog["Bad Moon"], name="Titania's Song", mana_cost="{3}{G}", cmc=4.0,
        oracle_text=(
            "Each noncreature artifact loses all abilities and becomes an "
            "artifact creature with power and toughness each equal to its mana value."
        ),
    )


@pytest.mark.cr("613.1d", "613.1f")
def test_titanias_song_animates_noncreature_artifacts_at_their_mana_value(catalog):
    tome = Permanent(card=catalog["Jayemdae Tome"])       # mana value 4
    bears = Permanent(card=catalog["Grizzly Bears"])
    player = PlayerState(name="P1", battlefield=[tome, bears])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    assert tome.is_creature is False

    player.battlefield.append(Permanent(card=_song(catalog)))
    game._refresh_dynamic_creatures()

    assert tome.is_creature is True
    assert (tome.effective_power, tome.effective_toughness) == (4, 4)
    # A creature is not a *noncreature* artifact, and Grizzly Bears is neither.
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


@pytest.mark.cr("611.3")
def test_titanias_song_effect_ends_when_the_source_leaves(catalog):
    """The affected permanent holds a reference to the *source*, not a copy of
    the effect, so removal is the source dropping out of that list — the same
    shape attached Auras use, and the reason there is no flag to clear."""
    tome = Permanent(card=catalog["Jayemdae Tome"])
    song = Permanent(card=_song(catalog))
    player = PlayerState(name="P1", battlefield=[tome, song])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    assert tome.is_creature is True

    player.battlefield.remove(song)
    game._refresh_dynamic_creatures()

    assert tome.is_creature is False


@pytest.mark.cr("613.1f")
def test_titanias_song_removes_activated_abilities_too(catalog):
    """"Loses all abilities" means the activated ones. Layer 6 removes keyword
    abilities, but an activated ability is read from the compiled program, so
    the loss has to be enforced where activation is authorised — otherwise the
    card is half-implemented and a Tome keeps drawing cards."""
    tome = Permanent(card=catalog["Jayemdae Tome"])
    tome.metadata["summoning_sickness_turn"] = -99
    song = Permanent(card=_song(catalog))
    player = PlayerState(
        name="P1", battlefield=[tome, song], library=[catalog["Forest"]] * 5
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()

    result = game.activate_permanent_ability(0, "Jayemdae Tome")
    assert result.supported is False
    assert player.hand == []

    player.battlefield.remove(song)
    game._refresh_dynamic_creatures()

    assert game.activate_permanent_ability(0, "Jayemdae Tome").supported is True
    assert len(player.hand) == 1


# ---------------------------------------------------------------------------
# Energy Flux — a static that *grants* an ability board-wide
# ---------------------------------------------------------------------------

@pytest.mark.cr("613.1f")
def test_energy_flux_grants_the_upkeep_cost_to_every_artifact(catalog):
    """The granted ability is appended to each artifact's effective card, so the
    compiler produces it like a printed one and the upkeep step finds it without
    knowing a static granted it."""
    flux = dataclasses.replace(
        catalog["Bad Moon"], name="Energy Flux", mana_cost="{2}{U}", cmc=3.0,
        oracle_text=(
            'All artifacts have "At the beginning of your upkeep, sacrifice '
            'this artifact unless you pay {2}."'
        ),
    )
    assert compile_card_oracle(flux).supported

    ring = Permanent(card=catalog["Sol Ring"])
    bears = Permanent(card=catalog["Grizzly Bears"])
    player = PlayerState(name="P1", battlefield=[ring, bears])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    assert game.get_upkeep_pay_triggers(0) == []

    player.battlefield.append(Permanent(card=flux))
    game._refresh_dynamic_creatures()

    triggers = game.get_upkeep_pay_triggers(0)
    assert [t["card_name"] for t in triggers] == ["Sol Ring"]
    assert triggers[0]["mana"]["generic"] == 2


@pytest.mark.cr("611.3")
def test_energy_flux_grant_ends_when_it_leaves(catalog):
    flux = dataclasses.replace(
        catalog["Bad Moon"], name="Energy Flux", mana_cost="{2}{U}", cmc=3.0,
        oracle_text=(
            'All artifacts have "At the beginning of your upkeep, sacrifice '
            'this artifact unless you pay {2}."'
        ),
    )
    ring = Permanent(card=catalog["Sol Ring"])
    flux_perm = Permanent(card=flux)
    player = PlayerState(name="P1", battlefield=[ring, flux_perm])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    assert len(game.get_upkeep_pay_triggers(0)) == 1

    player.battlefield.remove(flux_perm)
    game._refresh_dynamic_creatures()

    assert game.get_upkeep_pay_triggers(0) == []


# ---------------------------------------------------------------------------
# Primal Clay — enters as one of three bodies
# ---------------------------------------------------------------------------

def _clay(catalog):
    return dataclasses.replace(
        catalog["Grizzly Bears"], name="Primal Clay", mana_cost="{4}", cmc=4.0,
        type_line="Artifact Creature — Shapeshifter",
        oracle_text=(
            "As this creature enters, it becomes your choice of a 3/3 artifact "
            "creature, a 2/2 artifact creature with flying, or a 1/6 Wall "
            "artifact creature with defender in addition to its other types."
        ),
        raw={"name": "Primal Clay", "type_line": "Artifact Creature — Shapeshifter",
             "power": "*", "toughness": "*"},
    )


def test_primal_clay_bodies_are_parsed_from_the_text(catalog):
    """A template, not a card: any "your choice of <body>, <body>, or <body>"
    creature reads the same way."""
    from engine.enter_effects import choosable_bodies

    assert choosable_bodies(_clay(catalog).oracle_text) == (
        {"power": 3, "toughness": 3, "keyword": ""},
        {"power": 2, "toughness": 2, "keyword": "flying"},
        {"power": 1, "toughness": 6, "keyword": "defender"},
    )


def test_primal_clay_enters_as_the_first_body_by_default(catalog):
    """Headless and AI play must never block on the choice. The default is the
    first body *printed*, not the strongest — picking "best" would be the engine
    deciding strategy, and in a different order from the prompt."""
    card = _clay(catalog)
    assert compile_card_oracle(card).supported

    player = PlayerState(name="P1", hand=[card])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Primal Clay")
    clay = player.battlefield[0]

    assert (clay.effective_power, clay.effective_toughness) == (3, 3)
    # The card's *text* names flying and defender, so a keyword scan over the
    # oracle text grants them; a body that does not have them must not keep them.
    assert game._has_keyword(clay, "flying") is False
    assert game._has_keyword(clay, "defender") is False


@pytest.mark.parametrize(
    "option,expected",
    [(0, (3, 3, False, False)), (1, (2, 2, True, False)), (2, (1, 6, False, True))],
)
def test_primal_clay_choice_replaces_the_body(catalog, option, expected):
    player = PlayerState(name="P1", hand=[_clay(catalog)])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Primal Clay")
    clay = player.battlefield[0]

    # Only an interactive controller is offered the replacement; every other
    # seat keeps the first printed body applied as the creature entered.
    game.interactive_seats = {0}
    game.arm_pending_choice(
        "body_choice", 0, card_name="Primal Clay",
        permanent=clay, options=clay.metadata["body_options"],
    )
    assert game.confirm_enter_body_choice(0, option) is True

    power, toughness, flying, defender = expected
    assert (clay.effective_power, clay.effective_toughness) == (power, toughness)
    assert game._has_keyword(clay, "flying") is flying
    assert game._has_keyword(clay, "defender") is defender


def test_atog_pays_an_artifact_for_its_pump(catalog):
    """Atog's sacrifice was parsed by the grammar and charged by nobody, so the
    pump was free and repeatable: the ability read as supported, the artifact
    stayed on the battlefield, and +2/+2 could be taken as many times as the
    player liked. The cost is collected on activation now (CR 601.2h), and an
    unpayable one makes the ability unactivatable rather than free (602.5c)."""
    atog = Permanent(card=catalog["Atog"])
    mox = Permanent(card=catalog["Mox Pearl"])
    p1 = PlayerState(name="P1", battlefield=[atog, mox])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    base = atog.effective_power

    first = game.activate_permanent_ability(0, "Atog", permanent_index=0)

    assert first.supported, first.details
    assert atog.effective_power == base + 2
    assert not any(perm is mox for perm in game.controlled_by(0))
    assert any(card.name == "Mox Pearl" for card in p1.graveyard)

    second = game.activate_permanent_ability(0, "Atog", permanent_index=0)

    assert not second.supported
    assert atog.effective_power == base + 2


# ---------------------------------------------------------------------------
# The never-checked-cards round
#
# Revised added nineteen cards that no manual pass had ever looked at — the
# verification tracker had no result for any of them and its generated file
# claimed there were none missing (round 45). Working through them by hand
# turned up two that reported `supported` and did something else. Both are here.
# ---------------------------------------------------------------------------


def test_dwarven_weaponsmith_counters_the_creature_it_targeted(catalog):
    """"{T}, Sacrifice an artifact: Put a +1/+1 counter on target creature."

    The artifact sits *before* the target on the battlefield, so paying the cost
    slides the target down a slot. The counter has to land on the creature that
    was chosen, not on whatever moved into its index — which was the source
    itself, because index 2 no longer existed.
    """
    smith = Permanent(card=catalog["Dwarven Weaponsmith"])
    smith.metadata["summoning_sickness_turn"] = -99
    fuel = Permanent(card=catalog["Black Lotus"])
    bear = Permanent(card=catalog["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[smith, fuel, bear])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "beginning", "upkeep"

    result = game.activate_permanent_ability(
        0, "Dwarven Weaponsmith", target_player_index=0, target_permanent_index=2
    )
    assert result.supported, result.details
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    assert (smith.effective_power, smith.effective_toughness) == (1, 1), (
        "the Weaponsmith kept nothing for itself"
    )


def test_energy_flux_makes_artifacts_pay_a_generic_upkeep(catalog):
    """"All artifacts have 'At the beginning of your upkeep, sacrifice this
    artifact unless you pay {2}.'"

    A cost of pure generic mana. The pay-or-sacrifice handler tested the
    *coloured* pips alone, so this one had nothing to test and every artifact on
    the board paid it for free — the enchantment did nothing at all.
    """
    flux = Permanent(card=catalog["Energy Flux"])
    stone = Permanent(card=catalog["Millstone"])
    p1 = PlayerState(name="P1", battlefield=[flux])
    p2 = PlayerState(name="P2", battlefield=[stone])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.active_player_index = 1
    game._recompute_continuous_effects()

    game.resolve_upkeep(1)

    assert [perm.card.name for perm in p2.battlefield] == [], "no mana, no Millstone"


def test_energy_flux_is_paid_off_with_two_floating_mana(catalog):
    """The other half: the cost is payable, so paying it keeps the artifact and
    actually spends the mana."""
    flux = Permanent(card=catalog["Energy Flux"])
    stone = Permanent(card=catalog["Millstone"])
    p1 = PlayerState(name="P1", battlefield=[flux])
    p2 = PlayerState(name="P2", battlefield=[stone])
    p2.mana_pool["C"] = 2
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.active_player_index = 1
    game._recompute_continuous_effects()

    game.resolve_upkeep(1)

    assert [perm.card.name for perm in p2.battlefield] == ["Millstone"]
    assert p2.mana_pool["C"] == 0, "the {2} was actually spent"
