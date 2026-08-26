"""Per-card tests for Legends' artifacts.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


# ---------------------------------------------------------------------------
# Serpent Generator (round 11) — a token granted an ability in quotes
# ---------------------------------------------------------------------------


def _generator_game(set_pool):
    gen = Permanent(card=set_pool("LEG")["Serpent Generator"])
    p1 = PlayerState(name="P1", battlefield=[gen])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, gen, p1, p2


def test_serpent_generator_token_is_built_as_printed(set_pool):
    """"Create a 1/1 colorless Snake artifact creature token. It has "…"." —
    the granted line rides the token's own oracle text, so every reader (the
    trigger scan, the UI, the coverage scripts) sees it as printed."""
    game, gen, p1, _ = _generator_game(set_pool)

    result = game.activate_permanent_ability(0, "Serpent Generator", permanent_index=0)
    game._settle()

    assert result.supported
    assert gen.tapped, "{4}, {T} taps the generator"
    tokens = [p for p in game.controlled_by(0) if p.card.name != "Serpent Generator"]
    assert len(tokens) == 1
    token = tokens[0]
    assert token.card.name == "Snake Token"
    assert "Snake" in token.card.type_line and "Artifact Creature" in token.card.type_line
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    assert token.card.colors == ()
    assert "gets a poison counter" in token.card.oracle_text
    assert compile_card_oracle(token.card).supported, (
        "the granted ability must compile on the token itself — a token that "
        "carries the words without the trigger is the hollow-support shape"
    )


def test_serpent_generators_token_poisons_on_damage(set_pool):
    """The granted trigger is live on the token: its damage to a player gives
    that player a poison counter, exactly as Pit Scorpion's own does."""
    game, _, _, p2 = _generator_game(set_pool)
    game.activate_permanent_ability(0, "Serpent Generator", permanent_index=0)
    game._settle()
    token = next(p for p in game.controlled_by(0) if p.card.name == "Snake Token")

    game._deal_damage_to_player(p2, 1, source=token)
    game._settle()

    assert p2.poison_counters == 1


# ---------------------------------------------------------------------------
# Arena of the Ancients (round 13) — an enter-tap over a described set, and a
# supertype-scoped untap restriction. CR 502.3.
# ---------------------------------------------------------------------------

from engine.models import CardDefinition


def _legend(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0,
        type_line="Legendary Creature — Human Knight",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Legendary Creature — Human Knight",
             "power": "2", "toughness": "2"},
    )


def _bear(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
    )


def _arena_game(set_pool):
    my_legend = Permanent(card=_legend("Kasimir"))
    my_bear = Permanent(card=_bear("Bear"))
    their_legend = Permanent(card=_legend("Tobias"))
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Arena of the Ancients"]],
                     battlefield=[my_legend, my_bear])
    p2 = PlayerState(name="P2", battlefield=[their_legend])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, my_legend, my_bear, their_legend


def test_arena_taps_every_legendary_creature_as_it_enters(set_pool):
    """"When this artifact enters, tap all legendary creatures." — both
    players' legends, and nobody's plain creatures: the supertype rides the
    filter payload, not a bespoke handler."""
    game, my_legend, my_bear, their_legend = _arena_game(set_pool)

    result = game.cast_from_hand(0, "Arena of the Ancients")
    assert result.supported, result.details
    game._settle()

    assert my_legend.tapped
    assert their_legend.tapped
    assert not my_bear.tapped, "a plain Bear is not legendary"


def test_arena_holds_legendary_creatures_tapped_through_the_untap_step(set_pool):
    """"Legendary creatures don't untap during their controllers' untap
    steps." (CR 502.3) — the plural-possessive spelling, read by the untap
    table; a tapped legend stays down while everything else untaps."""
    game, my_legend, my_bear, their_legend = _arena_game(set_pool)
    game.cast_from_hand(0, "Arena of the Ancients")
    game._settle()
    my_bear.tapped = True

    game.resolve_untap_step(0)
    assert my_legend.tapped, "held by Arena"
    assert not my_bear.tapped, "everything else untaps as normal"

    game.resolve_untap_step(1)
    assert their_legend.tapped, "the restriction is symmetrical"


def test_arena_releases_the_legends_when_it_leaves(set_pool):
    """The restriction is derived from the Arena's presence, not stamped on
    the creatures — remove it and the next untap step is normal."""
    game, my_legend, _, _ = _arena_game(set_pool)
    game.cast_from_hand(0, "Arena of the Ancients")
    game._settle()

    arena = next(p for p in game.controlled_by(0) if p.card.name == "Arena of the Ancients")
    game.remove_from_battlefield(arena)
    game.resolve_untap_step(0)

    assert not my_legend.tapped


# ---------------------------------------------------------------------------
# Ring of Immortals (round 21) — Avoid Fate's sentence as an activated ability.
# The same production, the same payload and the same handler; what is different
# is that a cost is paid before the target is chosen (CR 602.2b), so the
# narrowing has to be enforced by the activation gate as well as at resolution.
# ---------------------------------------------------------------------------


def _ring_game(set_pool, threat: str, seat: int):
    pool = set_pool("LEG")
    mine = Permanent(card=_bear("Mine"))
    ring = Permanent(card=pool["Ring of Immortals"])
    theirs = Permanent(card=_bear("Theirs"))
    p1 = PlayerState(name="P1", battlefield=[mine, ring])
    p2 = PlayerState(name="P2", hand=[pool[threat]], battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.start_turn(1)
    queued = game.queue_from_hand(
        1, threat, target_player_index=seat, target_permanent_index=0
    )
    assert queued.supported, queued.details
    p1.mana_pool.update({"generic": 3})
    return game, ring, p1, p2


def test_ring_of_immortals_is_the_same_sentence_as_avoid_fate(set_pool):
    """One production, two cards. The ability's instruction is byte-identical to
    the spell's, which is what "the printed class is payload" buys."""
    pool = set_pool("LEG")
    ring = compile_card_oracle(pool["Ring of Immortals"])
    assert ring.supported, ring.reason
    (ability,) = ring.activated_abilities
    assert ability.supported
    spell = compile_card_oracle(pool["Avoid Fate"])
    counter = next(i for i in spell.instructions if i.kind == "counter_top_stack_spell")
    assert ability.instruction.kind == counter.kind
    assert ability.instruction.payload == counter.payload
    assert ability.cost.requires_tap and ability.cost.mana["generic"] == 3


def test_ring_of_immortals_counters_an_aura_aimed_at_your_permanent(set_pool):
    game, ring, _p1, p2 = _ring_game(set_pool, "Divine Transformation", 0)

    result = game.queue_permanent_ability(0, "Ring of Immortals", target_stack_index=0)
    game.resolve_stack()
    game._settle()

    assert result.supported, result.details
    assert ring.tapped
    assert not game.stack
    assert [c.name for c in p2.graveyard] == ["Divine Transformation"]


def test_ring_of_immortals_refuses_to_activate_with_nothing_it_may_counter(set_pool):
    """CR 602.2b: the target is chosen as the ability is activated, so a board
    with no legal one refuses the activation *before* any cost is paid. The
    round-17 shape: an ability that armed, took the tap and then countered
    nothing would look like it worked."""
    game, ring, p1, p2 = _ring_game(set_pool, "Transmutation", 1)

    result = game.queue_permanent_ability(0, "Ring of Immortals", target_stack_index=0)

    assert not result.supported
    assert not ring.tapped, "nothing was paid"
    assert p1.mana_pool.get("generic", 0) == 3
    game.resolve_stack()
    game._settle()
    assert any("Transmutation switched" in line for line in game.log)


def test_ring_of_immortals_offers_only_what_it_could_counter(set_pool):
    """The picker and the handler read one payload through one pair of readers,
    so the list a player is shown is exactly the list the counter would act on."""
    from engine.targeting import derive_activation_spec

    pool = set_pool("LEG")
    program = compile_card_oracle(pool["Ring of Immortals"])
    spec = derive_activation_spec(program.activated_abilities[0])
    assert spec == {
        "kind": "stack",
        "stack_any_classes": [["card_type", "instant"], ["subtype", "aura"]],
        "stack_targets_filter": {"controller": "you"},
    }

    game, _ring, _p1, _p2 = _ring_game(set_pool, "Psychic Purge", 0)
    assert game._enumerate_targets(
        0, pool["Ring of Immortals"], spec, for_cast=False
    ) == [], "a sorcery is outside the printed class union"


# ---------------------------------------------------------------------------
# Alchor's Tomb (round 22) — a colour chosen as the ability resolves
# ---------------------------------------------------------------------------


def _tomb_game(set_pool):
    pool = set_pool("LEG")
    tomb = Permanent(card=pool["Alchor's Tomb"])
    mine = Permanent(card=pool["Hell's Caretaker"])
    theirs = Permanent(card=pool["Hell's Caretaker"])
    p1 = PlayerState(name="P1", battlefield=[tomb, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, tomb, mine, theirs


def test_alchors_tomb_recolours_the_permanent_that_was_targeted(set_pool):
    """The colour is not in the text — it arrives with the activation (CR 609.3)
    and reaches the permanent the activator actually named. Both creatures share
    a name, so a handler locating by value would recolour the wrong one."""
    game, tomb, mine, theirs = _tomb_game(set_pool)

    result = game.activate_permanent_ability(
        0, "Alchor's Tomb", permanent_index=0,
        target_player_index=0,
        target_permanent_ids=[mine.permanent_id],
        mana_color="U",
    )
    game._settle()

    assert result.supported
    assert tomb.tapped
    assert mine.effective_colors == {"U"}, "the named creature became blue"
    assert theirs.effective_colors == set(theirs.card.colors), "the look-alike is untouched"


def test_alchors_tomb_refuses_a_permanent_the_activator_does_not_control(set_pool):
    """"Target permanent **you control**" — the narrowing is on the payload and
    is asked at resolution, so the opponent's creature is not recoloured even if
    its id is sent."""
    game, _tomb, mine, theirs = _tomb_game(set_pool)

    game.activate_permanent_ability(
        0, "Alchor's Tomb", permanent_index=0,
        target_player_index=1,
        target_permanent_ids=[theirs.permanent_id],
        mana_color="U",
    )
    game._settle()

    assert theirs.effective_colors == set(theirs.card.colors)
    assert mine.effective_colors == set(mine.card.colors)


def test_alchors_tomb_without_a_chosen_colour_recolours_nothing(set_pool):
    """No colour answered means no colour applied — a permanent that became a
    colour nobody picked is the wrong colour."""
    game, _tomb, mine, _theirs = _tomb_game(set_pool)

    game.activate_permanent_ability(
        0, "Alchor's Tomb", permanent_index=0,
        target_player_index=0,
        target_permanent_ids=[mine.permanent_id],
    )
    game._settle()

    assert mine.effective_colors == set(mine.card.colors)


# ---------------------------------------------------------------------------
# Gauntlets of Chaos (round 22) — an atomic exchange of control
# ---------------------------------------------------------------------------


def _gauntlets_game(set_pool):
    """P1 holds the Gauntlets and two look-alike Batteries; P2 holds a third.

    Two permanents sharing a name is the point: an exchange that located either
    half by value would swap whichever Battery it found first.
    """
    pool = set_pool("LEG")
    gauntlets = Permanent(card=pool["Gauntlets of Chaos"])
    decoy = Permanent(card=pool["Black Mana Battery"])
    mine = Permanent(card=pool["Black Mana Battery"])
    theirs = Permanent(card=pool["Red Mana Battery"])
    p1 = PlayerState(name="P1", battlefield=[gauntlets, decoy, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, gauntlets, decoy, mine, theirs


def _fire_gauntlets(game, first, second):
    result = game.activate_permanent_ability(
        0, "Gauntlets of Chaos", permanent_index=0,
        target_player_index=0,
        target_permanent_ids=[
            first.permanent_id if first is not None else None,
            second.permanent_id if second is not None else None,
        ],
    )
    game._settle()
    return result


def test_gauntlets_of_chaos_exchanges_both_halves(set_pool):
    """CR 701.12b: each player simultaneously gains control of the permanent the
    other controlled. Both halves move, and the look-alike beside the named
    permanent stays where it is."""
    from engine.control import base_controller

    game, _gauntlets, decoy, mine, theirs = _gauntlets_game(set_pool)

    result = _fire_gauntlets(game, mine, theirs)

    assert result.supported
    assert game.controller_index_of(mine) == 1, "P1's Battery went to P2"
    assert game.controller_index_of(theirs) == 0, "P2's Battery came to P1"
    assert game.controller_index_of(decoy) == 0, "the look-alike never moved"
    # CR 613.1b / 108.3: the exchange is a layer-2 contribution, so the seat each
    # permanent entered under — and the owner that reads off it — is untouched.
    assert base_controller(mine) == 0
    assert base_controller(theirs) == 1
    assert game.owner_index_of(mine) == 0
    assert game.owner_index_of(theirs) == 1


def test_gauntlets_of_chaos_exchange_survives_one_half_leaving(set_pool):
    """Two contributions, one per permanent, not one remembered swap: destroying
    the permanent that went the other way leaves this one exactly where the
    exchange put it."""
    game, _gauntlets, _decoy, mine, theirs = _gauntlets_game(set_pool)
    _fire_gauntlets(game, mine, theirs)

    game.remove_from_battlefield(theirs)
    game.check_state_based_actions()

    assert game.controller_index_of(mine) == 1


def test_gauntlets_of_chaos_does_nothing_when_a_half_is_gone(set_pool):
    """CR 701.12a: if the entire exchange can't be completed, no part of it
    occurs — the other permanent must not change hands on its own."""
    game, _gauntlets, _decoy, mine, theirs = _gauntlets_game(set_pool)
    game.remove_from_battlefield(theirs)

    _fire_gauntlets(game, mine, theirs)

    assert game.controller_index_of(mine) == 0, "half an exchange is a gift"


def test_gauntlets_of_chaos_refuses_two_permanents_sharing_no_printed_type(set_pool):
    """"…that shares one of those types with it." The relation is between the two
    slots, so a Battery traded for an enchantment is not an exchange this card
    allows."""
    pool = set_pool("LEG")
    gauntlets = Permanent(card=pool["Gauntlets of Chaos"])
    mine = Permanent(card=pool["Black Mana Battery"])
    theirs = Permanent(card=pool["Arena of the Ancients"])
    enchantment = Permanent(card=pool["Land Equilibrium"])
    p1 = PlayerState(name="P1", battlefield=[gauntlets, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs, enchantment])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    _fire_gauntlets(game, mine, enchantment)

    assert game.controller_index_of(mine) == 0
    assert game.controller_index_of(enchantment) == 1
    assert any("shares none of" in entry for entry in game.log), (
        "the refusal must be the shared-type test, not a failure to find the "
        "opponent's permanent at all"
    )

    # The artifact on that same battlefield *does* share a type, so the same
    # activation against it goes through — which is what makes the refusal above
    # about the relation between the slots rather than about the slots.
    game.players[0].battlefield.insert(0, Permanent(card=pool["Gauntlets of Chaos"]))
    game._sync_control()
    _fire_gauntlets(game, mine, theirs)
    assert game.controller_index_of(mine) == 1
    assert game.controller_index_of(theirs) == 0


def test_gauntlets_of_chaos_destroys_the_auras_on_both_halves(set_pool):
    """"If those permanents are exchanged this way, destroy all Auras attached to
    them." The rider is executed, and it reads the two exchanged permanents —
    an Aura on a third permanent survives."""
    from engine.auras import attach_aura

    pool = set_pool("LEG")
    gauntlets = Permanent(card=pool["Gauntlets of Chaos"])
    mine = Permanent(card=pool["Segovian Leviathan"])
    bystander = Permanent(card=pool["Segovian Leviathan"])
    theirs = Permanent(card=pool["Sivitri Scarzam"])
    on_mine = Permanent(card=pool["Giant Strength"])
    on_theirs = Permanent(card=pool["Spirit Link"])
    elsewhere = Permanent(card=pool["Giant Strength"])
    p1 = PlayerState(name="P1", battlefield=[gauntlets, mine, bystander, on_mine, elsewhere])
    p2 = PlayerState(name="P2", battlefield=[theirs, on_theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    attach_aura(on_mine, mine)
    attach_aura(on_theirs, theirs)
    attach_aura(elsewhere, bystander)

    _fire_gauntlets(game, mine, theirs)

    assert game.controller_index_of(mine) == 1
    assert game.controller_index_of(theirs) == 0
    assert not game.is_on_battlefield(on_mine)
    assert not game.is_on_battlefield(on_theirs)
    assert game.is_on_battlefield(elsewhere), "an Aura on a third permanent survives"


def test_gauntlets_of_chaos_leaves_no_aura_destruction_when_nothing_is_exchanged(set_pool):
    """The rider is conditioned on the exchange having happened, and the
    condition is the binding rather than a second reading of the board."""
    from engine.auras import attach_aura

    pool = set_pool("LEG")
    gauntlets = Permanent(card=pool["Gauntlets of Chaos"])
    mine = Permanent(card=pool["Segovian Leviathan"])
    theirs = Permanent(card=pool["Sivitri Scarzam"])
    on_mine = Permanent(card=pool["Giant Strength"])
    p1 = PlayerState(name="P1", battlefield=[gauntlets, mine, on_mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    attach_aura(on_mine, mine)
    game.remove_from_battlefield(theirs)

    _fire_gauntlets(game, mine, theirs)

    assert game.controller_index_of(mine) == 0
    assert game.is_on_battlefield(on_mine)

# ---------------------------------------------------------------------------
# Kry Shield (round 22) — the directional shield without the word "combat"
# ---------------------------------------------------------------------------


def _kry_game(set_pool, mana_cost: str = "{2}{G}"):
    """Kry Shield beside a creature of a known mana value, and an opposing one."""
    from engine.models import CardDefinition

    guard = CardDefinition(
        name="Guard", mana_cost=mana_cost, cmc=3.0, type_line="Creature - Test",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": "Guard", "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )
    other = CardDefinition(
        name="Other", mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Other", "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )
    shield = Permanent(card=set_pool("LEG")["Kry Shield"])
    mine = Permanent(card=guard)
    theirs = Permanent(card=other)
    p1 = PlayerState(name="P1", battlefield=[shield, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    p1.mana_pool["C"] = 6
    return game, shield, mine, theirs, p1, p2


def _dealt(game, recipient, amount, source, *, combat=True) -> int:
    from engine.damage_events import deal_damage

    return deal_damage(game, {
        "recipient": recipient, "amount": amount, "source": source, "combat": combat,
    }).dealt


def test_kry_shield_stops_every_kind_of_damage_the_creature_deals(set_pool):
    """"Prevent all damage that would be dealt this turn by target creature you
    control." Horn of Deafening's sentence with the word "combat" deleted, so
    the shield has to cover a ping as well as combat damage — the word is
    payload on one instruction, not a second one."""
    game, _shield, mine, theirs, _p1, p2 = _kry_game(set_pool)

    result = game.activate_permanent_ability(
        0, "Kry Shield", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert result.supported, result.reason
    assert _dealt(game, theirs, 2, mine) == 0, "combat damage it deals is prevented"
    assert _dealt(game, p2, 2, mine, combat=False) == 0, "so is a ping"
    assert _dealt(game, mine, 2, theirs) == 2, "the shield is on what it deals"


def test_kry_shields_rider_is_carried_out(set_pool):
    """"That creature gets +0/+X until end of turn, where X is its mana value."
    The bound pronoun is the creature the first sentence targeted, so the
    toughness rises by that creature's own mana value and nothing is chosen
    twice."""
    game, _shield, mine, _theirs, _p1, _p2 = _kry_game(set_pool)
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)

    game.activate_permanent_ability(
        0, "Kry Shield", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert (mine.effective_power, mine.effective_toughness) == (2, 5), (
        "+0/+X where X is the creature's mana value (3)"
    )


def test_kry_shields_shield_wears_off_at_cleanup(set_pool):
    """"…this turn." The record is swept with every other turn-long marker, so
    the duration is real rather than printed."""
    game, _shield, mine, theirs, _p1, p2 = _kry_game(set_pool)
    game.activate_permanent_ability(
        0, "Kry Shield", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()
    assert _dealt(game, p2, 2, mine, combat=False) == 0

    game.resolve_cleanup_step(0)
    assert _dealt(game, p2, 2, mine, combat=False) == 2


def test_kry_shield_only_offers_creatures_you_control(set_pool):
    """"target creature **you control**". The narrowing rides the payload the
    picker reads, so the offer and the effect agree on which creatures the card
    reaches."""
    from engine.targeting import derive_activation_spec

    pool = set_pool("LEG")
    program = compile_card_oracle(pool["Kry Shield"])
    spec = derive_activation_spec(program.activated_abilities[0])
    game, _shield, _mine, _theirs, _p1, _p2 = _kry_game(set_pool)
    offered = game._enumerate_targets(0, pool["Kry Shield"], spec, for_cast=False)
    assert [t["name"] for t in offered] == ["Guard"], (
        "the opponent's creature is not a creature you control"
    )


# ---------------------------------------------------------------------------
# Al-abara's Carpet (round 22) — a blanket shield keyed on a printed noun phrase
# ---------------------------------------------------------------------------


def _carpet_game(set_pool):
    """The Carpet on my side; a ground attacker, a flying attacker and a
    creature that stayed home on the opponent's."""
    from engine.models import CardDefinition

    def creature(name: str, keywords: tuple[str, ...] = ()) -> CardDefinition:
        return CardDefinition(
            name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
            oracle_text="Flying" if keywords else "", colors=(), color_identity=(),
            keywords=keywords, produced_mana=(),
            raw={"name": name, "type_line": "Creature - Test",
                 "power": "3", "toughness": "3"},
        )

    carpet = Permanent(card=set_pool("LEG")["Al-abara's Carpet"])
    ground = Permanent(card=creature("Ground"))
    flyer = Permanent(card=creature("Flyer", ("Flying",)))
    homebody = Permanent(card=creature("Homebody"))
    ground.attacking = True
    flyer.attacking = True
    p1 = PlayerState(name="P1", battlefield=[carpet])
    p2 = PlayerState(name="P2", battlefield=[ground, flyer, homebody])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    p1.mana_pool["C"] = 9
    return game, ground, flyer, homebody, p1


def _arm_carpet(game):
    result = game.activate_permanent_ability(0, "Al-abara's Carpet", permanent_index=0)
    game._settle()
    assert result.supported, result.reason


def test_al_abaras_carpet_stops_the_creatures_its_phrase_names(set_pool):
    """"Prevent all damage that would be dealt to you this turn by attacking
    creatures without flying." A blanket, not a charge: every matching source
    this turn is prevented, so a second ground attacker after the first is
    stopped too."""
    game, ground, _flyer, _homebody, p1 = _carpet_game(set_pool)
    _arm_carpet(game)

    assert _dealt(game, p1, 3, ground) == 0
    assert _dealt(game, p1, 3, ground) == 0, "a blanket is not used up"


def test_al_abaras_carpet_honours_every_word_of_its_phrase(set_pool):
    """Each adjective is enforced, because a shield admitting the phrase and
    then ignoring half of it is damage prevented the card does not prevent.

    A flyer is excluded by "without flying"; a creature that is not attacking is
    excluded by "attacking"; and a spell is no creature at all.
    """
    game, _ground, flyer, homebody, p1 = _carpet_game(set_pool)
    _arm_carpet(game)

    assert _dealt(game, p1, 3, flyer) == 3, "'without flying'"
    assert _dealt(game, p1, 3, homebody, combat=False) == 3, "'attacking'"
    assert _dealt(game, p1, 3, set_pool("LEG")["Al-abara's Carpet"], combat=False) == 3, (
        "a spell's card is not a permanent the phrase describes"
    )


def test_al_abaras_carpet_rechecks_the_phrase_when_damage_is_dealt(set_pool):
    """CR 615.9: the shield records the phrase, not the set. A creature that
    leaves combat stops being described by it, with nothing having to be
    updated when it does."""
    game, ground, _flyer, _homebody, p1 = _carpet_game(set_pool)
    _arm_carpet(game)
    assert _dealt(game, p1, 3, ground) == 0

    ground.attacking = False
    assert _dealt(game, p1, 3, ground) == 3


def test_al_abaras_carpet_shield_expires_with_the_turn(set_pool):
    """"…this turn." The shield carries its own lifetime, so the cleanup sweep
    ends it and no turn step needs a line naming this card."""
    game, ground, _flyer, _homebody, p1 = _carpet_game(set_pool)
    _arm_carpet(game)
    assert _dealt(game, p1, 3, ground) == 0

    game.resolve_cleanup_step(0)
    assert _dealt(game, p1, 3, ground) == 3


# ---------------------------------------------------------------------------
# Life Matrix (round 26) - an ability granted to another permanent as quoted text
# ---------------------------------------------------------------------------


def _matrix_game(set_pool):
    """Life Matrix, a creature to grant to, and a creature to leave alone."""
    matrix = Permanent(card=set_pool("LEG")["Life Matrix"])
    granted = Permanent(card=set_pool("LEG")["Barbary Apes"])
    other = Permanent(card=set_pool("LEG")["Barbary Apes"])
    p1 = PlayerState(name="P1", battlefield=[matrix, granted, other])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._set_phase_and_step("beginning", "upkeep")
    return game, matrix, granted, other


def test_life_matrix_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Life Matrix"])
    assert program.supported, program.reason

    (ability,) = program.activated_abilities
    steps = ability.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "add_named_counter_to_target", "grant_target_ability_text",
    ]
    # The counter's word and the granted ability's text are both payload.
    assert steps[0].payload["counter"] == "matrix"
    assert steps[1].payload["abilities"] == (
        "Remove a matrix counter from this creature: Regenerate this creature",
    )
    # No printed duration, so the grant lasts as long as the creature does
    # (CR 611.2c).
    assert steps[1].payload["until_eot"] is False


def test_life_matrix_grants_an_ability_that_can_then_be_activated(set_pool):
    """The point of the round: the granted ability is not just recorded, it is
    *usable*, and using it spends the counter the same sentence placed."""
    game, _matrix, granted, other = _matrix_game(set_pool)

    result = game.activate_permanent_ability(
        0, "Life Matrix", target_player_index=0,
        target_permanent_ids=[granted.permanent_id],
    )
    game._settle()
    assert result.supported, result.reason
    assert granted.metadata["matrix_counters"] == 1

    used = game.activate_permanent_ability(
        0, "Barbary Apes", permanent_index=1,
    )
    game._settle()

    assert used.supported, used.reason
    assert granted.regeneration_shield == 1
    # CR 602.1a: the counter removal is the cost, so it is spent.
    assert granted.metadata["matrix_counters"] == 0
    assert other.regeneration_shield == 0


def test_the_granted_ability_is_unactivatable_with_no_counter_left(set_pool):
    game, _matrix, granted, _other = _matrix_game(set_pool)
    game.activate_permanent_ability(
        0, "Life Matrix", target_player_index=0,
        target_permanent_ids=[granted.permanent_id],
    )
    game._settle()
    game.activate_permanent_ability(0, "Barbary Apes", permanent_index=1)
    game._settle()

    again = game.activate_permanent_ability(
        0, "Barbary Apes", permanent_index=1,
    )

    assert not again.supported
    assert granted.regeneration_shield == 1


def test_a_creature_that_was_not_granted_it_has_no_such_ability(set_pool):
    """The grant is per-permanent, and the two Apes are the same card."""
    game, _matrix, granted, other = _matrix_game(set_pool)
    game.activate_permanent_ability(
        0, "Life Matrix", target_player_index=0,
        target_permanent_ids=[granted.permanent_id],
    )
    game._settle()

    assert compile_card_oracle(granted.effective_card).activated_abilities
    assert not compile_card_oracle(other.effective_card).activated_abilities
    assert "matrix_counters" not in other.metadata


def test_life_matrix_is_refused_outside_your_upkeep(set_pool):
    """"Activate only during your upkeep." The clause sits behind a closing
    quotation mark, which is exactly why it used to go unenforced."""
    game, _matrix, granted, _other = _matrix_game(set_pool)
    game._set_phase_and_step("precombat_main", "precombat_main")

    result = game.activate_permanent_ability(
        0, "Life Matrix", target_player_index=0,
        target_permanent_ids=[granted.permanent_id],
    )

    assert not result.supported
    assert "matrix_counters" not in granted.metadata
