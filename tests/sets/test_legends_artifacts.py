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
    # (CR 611.2c) and no sweep is named.
    assert steps[1].payload["duration"] is None


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



# ---------------------------------------------------------------------------
# Mana Matrix (round 26) — a printed *list* of card types on a reduction
# ---------------------------------------------------------------------------


def _mana_matrix_game(set_pool, battlefield, hand, *, seat=0, **mana):
    pool = set_pool("LEG")
    players = [PlayerState(name="P1"), PlayerState(name="P2")]
    players[0].battlefield = [Permanent(card=pool[n]) for n in battlefield]
    players[seat].hand = [pool[n] for n in hand]
    for player in players:
        player.library = [pool["Karakas"]] * 6
    game = Game(players=players)
    game.enforce_mana_costs = True
    game.active_player_index = seat
    players[seat].mana_pool = {
        sym: mana.get(sym, 0) for sym in ("W", "U", "B", "R", "G", "C")
    }
    return game, players[seat]


def test_mana_matrix_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Mana Matrix"])
    assert program.supported, program.reason


def test_mana_matrix_discounts_an_instant_and_spends_the_reduced_mana(set_pool):
    """Divine Offering is {1}{W}; the Matrix takes {2} off a cost with {1} of
    generic, so one white mana pays for it — and the pool afterwards is what
    proves the discount was applied at payment rather than only computed."""
    game, caster = _mana_matrix_game(
        set_pool, ["Mana Matrix"], ["Divine Offering"], W=1,
    )

    assert game.queue_from_hand(0, "Divine Offering").supported
    assert caster.mana_pool["W"] == 0, "the {W} pip is still paid"
    assert sum(caster.mana_pool.values()) == 0

    bare, _ = _mana_matrix_game(set_pool, [], ["Divine Offering"], W=1)
    assert not bare.queue_from_hand(0, "Divine Offering").supported


def test_mana_matrix_reads_both_printed_types(set_pool):
    """"Instant **and** enchantment spells" is an alternation, so both halves
    of the list have to be discounted — a pattern that read one type would
    silently drop the other."""
    # Greater Realm of Preservation is {1}{W}; {2} less leaves {W}.
    enchantment, _ = _mana_matrix_game(
        set_pool, ["Mana Matrix"], ["Greater Realm of Preservation"], W=1,
    )
    assert enchantment.queue_from_hand(0, "Greater Realm of Preservation").supported

    bare, _ = _mana_matrix_game(set_pool, [], ["Greater Realm of Preservation"], W=1)
    assert not bare.queue_from_hand(0, "Greater Realm of Preservation").supported


def test_mana_matrix_does_not_discount_a_type_it_does_not_name(set_pool):
    """A creature spell is neither of the two printed types. Fallen Angel is
    {3}{B}{B}; this is exactly the mana a {2} discount would make enough."""
    game, _ = _mana_matrix_game(set_pool, ["Mana Matrix"], ["Fallen Angel"], B=2, C=1)
    assert not game.queue_from_hand(0, "Fallen Angel").supported


def test_mana_matrix_never_reduces_a_coloured_pip(set_pool):
    """CR 118.7a: a generic reduction touches only the generic component, and
    it clamps at zero rather than spilling onto a pip. Divine Offering is
    {1}{W} and the Matrix offers {2}: the {1} goes, the {W} stays, so a single
    colorless mana still cannot pay for it."""
    game, _ = _mana_matrix_game(set_pool, ["Mana Matrix"], ["Divine Offering"], C=1)
    assert not game.queue_from_hand(0, "Divine Offering").supported


def test_mana_matrix_does_not_discount_an_opponents_spell(set_pool):
    """"…spells **you cast**" is the Matrix's controller (CR 109.5)."""
    game, _ = _mana_matrix_game(
        set_pool, ["Mana Matrix"], ["Divine Offering"], seat=1, W=1,
    )
    assert not game.queue_from_hand(1, "Divine Offering").supported


# ---------------------------------------------------------------------------
# North Star (round 26) — CR 609.4, a bounded "as though" on the payment
# ---------------------------------------------------------------------------


def _north_star_game(set_pool, hand=("Divine Offering",)):
    pool = set_pool("LEG")
    star = Permanent(card=pool["North Star"])
    p1 = PlayerState(
        name="P1", battlefield=[star],
        hand=[pool[name] for name in hand],
        library=[pool["Karakas"]] * 6,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True
    game.start_turn(0)
    return game, p1


def _charge_north_star(game, player):
    player.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 4, "C": 0}
    result = game.activate_permanent_ability(0, "North Star", permanent_index=0)
    game._settle()
    return result


def _pool(player, **mana):
    player.mana_pool = {
        sym: mana.get(sym, 0) for sym in ("W", "U", "B", "R", "G", "C")
    }


def test_north_star_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["North Star"])
    assert program.supported, program.reason


def test_north_star_lets_green_mana_pay_a_white_pip(set_pool):
    """Divine Offering is {1}{W} and the pool is two green. Without the
    permission that is not a payment; with it, it is — and the pool afterwards
    is what shows the mana was actually spent."""
    game, p1 = _north_star_game(set_pool)
    refused, _ = _north_star_game(set_pool)
    _pool(refused.players[0], G=2)
    assert not refused.queue_from_hand(0, "Divine Offering").supported

    assert _charge_north_star(game, p1).supported
    _pool(p1, G=2)

    assert game.queue_from_hand(0, "Divine Offering").supported
    assert sum(p1.mana_pool.values()) == 0


def test_north_star_covers_only_one_spell(set_pool):
    """"For **one** spell this turn." The permission is bounded, so the second
    spell is paid the ordinary way or not at all."""
    game, p1 = _north_star_game(
        set_pool, hand=("Divine Offering", "Divine Offering"),
    )
    assert _charge_north_star(game, p1).supported

    _pool(p1, G=2)
    assert game.queue_from_hand(0, "Divine Offering").supported

    _pool(p1, G=2)
    assert not game.queue_from_hand(0, "Divine Offering").supported


def test_north_star_is_not_spent_on_a_spell_that_did_not_need_it(set_pool):
    """The ordinary payment is tried first, so a spell the pool covers outright
    leaves the permission for the spell the player actually wanted it for."""
    game, p1 = _north_star_game(
        set_pool, hand=("Divine Offering", "Divine Offering"),
    )
    assert _charge_north_star(game, p1).supported

    _pool(p1, W=1, C=1)
    assert game.queue_from_hand(0, "Divine Offering").supported
    assert p1.spend_mana_as_though_grants == [{"spells": 1, "any_type": True}]

    _pool(p1, G=2)
    assert game.queue_from_hand(0, "Divine Offering").supported


def test_north_star_permission_expires_with_the_turn(set_pool):
    """"…this turn." Nothing sweeps a card name; the grant carries its own
    lifetime and the cleanup step drops it."""
    game, p1 = _north_star_game(set_pool)
    assert _charge_north_star(game, p1).supported

    game.resolve_cleanup_step(0)
    assert p1.spend_mana_as_though_grants == []

    _pool(p1, G=2)
    assert not game.queue_from_hand(0, "Divine Offering").supported


def test_north_star_does_not_pay_for_an_activated_ability(set_pool):
    """"…to pay that **spell's** mana cost." An activated ability is not a
    spell (CR 602.1), so the permission never reaches one."""
    pool = set_pool("LEG")
    star = Permanent(card=pool["North Star"])
    bees = Permanent(card=pool["Killer Bees"])
    bees.summoning_sick = False
    p1 = PlayerState(name="P1", battlefield=[star, bees])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True
    game.start_turn(0)
    assert _charge_north_star(game, p1).supported

    # Killer Bees costs {G} to pump and the pool is white. The permission would
    # cover it if it applied to abilities; it does not.
    _pool(p1, W=1)
    assert not game.activate_permanent_ability(
        0, "Killer Bees", permanent_index=1,
    ).supported
    assert p1.spend_mana_as_though_grants == [{"spells": 1, "any_type": True}]
    assert p1.mana_pool["W"] == 1, "nothing was paid"



# ---------------------------------------------------------------------------
# Nova Pentacle (round 26) — the next damage from a chosen source, moved onto a
# creature the *opponent* picks
# ---------------------------------------------------------------------------


def _pentacle_game(set_pool):
    """Seat 0 holds the Pentacle and a creature of its own; seat 1 holds the
    source the Pentacle will name."""
    from tests.helpers import _mk_creature_card

    pentacle = Permanent(card=set_pool("LEG")["Nova Pentacle"])
    mine = Permanent(card=_mk_creature_card("Ox", 1, 4))
    theirs = Permanent(card=_mk_creature_card("Pinger", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[pentacle, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    p1.mana_pool.update({"generic": 3})
    return game, p1, mine, theirs


def _arm_pentacle(game):
    result = game.activate_permanent_ability(
        0, "Nova Pentacle", source_seat=1, source_permanent_index=0
    )
    assert result.supported, result
    return result


def test_nova_pentacle_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Nova Pentacle"])

    assert program.supported
    steps = program.activated_abilities[0].instruction.payload["steps"]
    # The opponent's pick is a prompt the resolution arms, and the redirect
    # behind it reads the answer — two steps of one sentence, in printed order.
    assert [step.kind for step in steps] == [
        "choose_permanent", "redirect_damage_from_chosen_source_until_eot"
    ]


def test_nova_pentacle_moves_the_chosen_sources_damage_onto_a_creature(set_pool):
    """"…that damage is dealt to target creature of an opponent's choice
    instead." The player takes none of it and the creature takes all of it —
    a redirect, not a shield."""
    game, p1, mine, theirs = _pentacle_game(set_pool)
    _arm_pentacle(game)

    game._deal_damage_to_player(p1, 2, source=theirs)

    assert p1.life == 20
    assert mine.damage_marked == 2


def test_nova_pentacle_moves_one_instance_only(set_pool):
    """"The **next time**…" — one damage event, however much of the turn is
    left."""
    game, p1, mine, theirs = _pentacle_game(set_pool)
    _arm_pentacle(game)

    game._deal_damage_to_player(p1, 2, source=theirs)
    game._deal_damage_to_player(p1, 3, source=theirs)

    assert mine.damage_marked == 2
    assert p1.life == 17


def test_nova_pentacle_answers_only_the_source_that_was_chosen(set_pool):
    """"a source of your choice" is one object (CR 615.8's phrase, on a
    redirect). Another creature's damage is not it."""
    from tests.helpers import _mk_creature_card

    game, p1, mine, _theirs = _pentacle_game(set_pool)
    other = Permanent(card=_mk_creature_card("Other", 3, 3))
    game.players[1].battlefield.append(other)
    game._sync_control()
    _arm_pentacle(game)

    game._deal_damage_to_player(p1, 3, source=other)

    assert p1.life == 17
    assert mine.damage_marked == 0


def test_nova_pentacle_asks_the_opponent_who_takes_the_damage(set_pool):
    """"…of an **opponent's** choice." The prompt is owed by the other seat, not
    by the activating player — the one thing about this card that the ordinary
    target picker cannot express, since the picker in front of an activation is
    the activating player's."""
    game, _p1, mine, theirs = _pentacle_game(set_pool)
    game.interactive_seats = {1}

    _arm_pentacle(game)

    owed = game.pending_choices_of("permanent_choice")
    assert len(owed) == 1
    assert owed[0].player_index == 1, "the opponent chooses"
    offered = {perm.card.name for perm in game.live_permanent_choices(owed[0])}
    assert offered == {"Ox", "Pinger"}, "every creature, on either battlefield"

    assert game.confirm_permanent_choice(1, theirs.permanent_id)
    game._settle()
    game._deal_damage_to_player(game.players[0], 2, source=theirs)

    assert theirs.damage_marked == 2, "the creature the opponent picked"
    assert mine.damage_marked == 0


# ---------------------------------------------------------------------------
# Knowledge Vault (round 30) — cards exiled *with* a permanent (CR 400.7/610.3)
# ---------------------------------------------------------------------------


def _r30_vault_game(set_pool, vault_count: int = 1):
    """A board with *vault_count* Knowledge Vaults and a library of named cards.

    The library entries are distinct cards so a test can say which Vault exiled
    which — one shared name would let a record keyed on the wrong thing pass.
    """
    pool = set_pool("LEG")
    vaults = [Permanent(card=pool["Knowledge Vault"]) for _ in range(vault_count)]
    library = [
        pool["Hell's Caretaker"], pool["Nova Pentacle"],
        pool["Alchor's Tomb"], pool["Serpent Generator"],
    ]
    p1 = PlayerState(name="P1", battlefield=list(vaults), library=library)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, vaults, p1, p2


def _r30_exile_with(game, vault, seat: int = 0):
    """Run one Vault's ``{2}, {T}`` ability and settle the stack."""
    game.activate_permanent_ability(
        seat, "Knowledge Vault", permanent_index=game.players[seat].battlefield.index(vault),
        ability_index=0,
    )
    game._settle()
    vault.tapped = False       # so the next activation of the same Vault can pay {T}


def test_knowledge_vault_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Knowledge Vault"])
    assert program.supported, program.reason
    assert len(program.activated_abilities) == 2
    assert len(program.triggered_abilities) == 1


def test_knowledge_vault_exiles_the_top_card(set_pool):
    """"{2}, {T}: Exile the top card of your library face down." — one card,
    off the top, into exile."""
    game, (vault,), p1, _p2 = _r30_vault_game(set_pool)

    _r30_exile_with(game, vault)

    assert [c.name for c in p1.exile] == ["Hell's Caretaker"]
    assert [c.name for c in p1.library] == [
        "Nova Pentacle", "Alchor's Tomb", "Serpent Generator",
    ]


def test_knowledge_vault_exiles_face_down(set_pool):
    """The rider is carried out, not dropped: the exiled card is face down
    (CR 406.3), which the engine answers from the linked-exile record because
    two copies of one card in a deck are the same object."""
    from engine.linked_exile import face_down_exiled_cards

    game, (vault,), p1, _p2 = _r30_vault_game(set_pool)

    _r30_exile_with(game, vault)

    assert [c.name for c in face_down_exiled_cards(game, 0)] == ["Hell's Caretaker"]


def test_knowledge_vault_sacrifice_returns_exactly_what_it_exiled(set_pool):
    """"{0}: Sacrifice this artifact. If you do, discard your hand, then put
    all cards exiled with this artifact into their owner's hand."

    The record has to survive the Vault's own sacrifice — the sentence that
    reads it runs after the sentence that destroys the permanent holding it.
    """
    game, (vault,), p1, _p2 = _r30_vault_game(set_pool)
    _r30_exile_with(game, vault)
    _r30_exile_with(game, vault)
    p1.hand = [set_pool("LEG")["Nova Pentacle"]]

    game.activate_permanent_ability(0, "Knowledge Vault", permanent_index=0, ability_index=1)
    game._settle()

    assert sorted(c.name for c in p1.hand) == ["Hell's Caretaker", "Nova Pentacle"]
    assert p1.exile == []
    assert not any(p.card.name == "Knowledge Vault" for p in p1.battlefield)


def test_knowledge_vault_sacrifice_discards_the_hand_first(set_pool):
    """"discard your hand, **then** put all cards exiled with this artifact
    into their owner's hand" — the order is printed, and reversing it would
    bin the cards the ability just gave back."""
    game, (vault,), p1, _p2 = _r30_vault_game(set_pool)
    _r30_exile_with(game, vault)
    p1.hand = [set_pool("LEG")["Serpent Generator"]]

    game.activate_permanent_ability(0, "Knowledge Vault", permanent_index=0, ability_index=1)
    game._settle()

    assert [c.name for c in p1.hand] == ["Hell's Caretaker"]
    assert sorted(c.name for c in p1.graveyard) == ["Knowledge Vault", "Serpent Generator"]


def test_a_second_knowledge_vault_keeps_its_own_pile(set_pool):
    """Two Vaults, each holding a different card: sacrificing one gives back
    that one's cards and leaves the other's in exile.

    This is the test a record keyed on the *name* of the permanent, or on a
    game-wide list, or on a ``permanent_id`` stamped fresh on entry (CR 400.7)
    would fail.
    """
    game, (first, second), p1, _p2 = _r30_vault_game(set_pool, vault_count=2)
    _r30_exile_with(game, first)     # Hell's Caretaker
    _r30_exile_with(game, second)    # Nova Pentacle

    game.activate_permanent_ability(
        0, "Knowledge Vault", permanent_index=p1.battlefield.index(first),
        ability_index=1,
    )
    game._settle()

    assert [c.name for c in p1.hand] == ["Hell's Caretaker"]
    assert [c.name for c in p1.exile] == ["Nova Pentacle"]
    assert [p.card.name for p in p1.battlefield] == ["Knowledge Vault"]


def test_knowledge_vault_trigger_finds_nothing_after_its_own_sacrifice(set_pool):
    """The ``{0}`` ability sacrifices the Vault, so its leaves-the-battlefield
    trigger goes on the stack — but the pile was *drained* when the cards were
    put into the hand, so the trigger cannot pull them back out of it."""
    game, (vault,), p1, _p2 = _r30_vault_game(set_pool)
    _r30_exile_with(game, vault)

    game.activate_permanent_ability(0, "Knowledge Vault", permanent_index=0, ability_index=1)
    game._settle()

    assert [c.name for c in p1.hand] == ["Hell's Caretaker"]
    assert [c.name for c in p1.graveyard] == ["Knowledge Vault"], (
        "only the Vault itself; the trigger found an empty pile"
    )


def test_knowledge_vault_destroyed_buries_what_it_exiled(set_pool):
    """"When this artifact leaves the battlefield, put all cards exiled with it
    into their owner's graveyard." — the other half of the link, fired from the
    record rather than from a permanent that is no longer there."""
    game, (vault,), p1, _p2 = _r30_vault_game(set_pool)
    _r30_exile_with(game, vault)
    _r30_exile_with(game, vault)

    game.sacrifice_permanent(vault)
    game._settle()

    assert sorted(c.name for c in p1.graveyard) == [
        "Hell's Caretaker", "Knowledge Vault", "Nova Pentacle",
    ]
    assert p1.exile == []


def test_untapping_a_knowledge_vault_keeps_its_pile(set_pool):
    """The Vault taps for its own ability and untaps every turn. Only Tawnos's
    Coffin's exile ends on an untap, and the entry says so — before that was
    per entry, ``become_untapped`` ended *every* linked exile in the game."""
    game, (vault,), p1, _p2 = _r30_vault_game(set_pool)
    game.activate_permanent_ability(0, "Knowledge Vault", permanent_index=0, ability_index=0)
    game._settle()
    assert vault.tapped

    game.become_untapped(vault)

    assert [c.name for c in p1.exile] == ["Hell's Caretaker"]
    assert p1.graveyard == []


# ---------------------------------------------------------------------------
# Voodoo Doll (round 34) — a trigger that lowered to nothing until "destroy
# this artifact" had an instruction behind it.
# ---------------------------------------------------------------------------


def _r34_doll(set_pool, *, tapped: bool, pins: int = 3):
    """A Voodoo Doll with *pins* pin counters already on it, at its
    controller's end step. Its own builder rather than a shared one because the
    turn must *not* be started here: the untap step would untap the tapped
    case, which is the whole distinction the card draws."""
    doll = Permanent(card=set_pool("LEG")["Voodoo Doll"])
    doll.metadata["summoning_sick"] = False
    doll.entered_turn = -5
    doll.tapped = tapped
    doll.metadata["pin_counters"] = pins
    p1 = PlayerState(name="P1", battlefield=[doll])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.turn = 3
    game.active_player_index = 0
    return game, doll, p1


def test_voodoo_doll_kills_itself_and_its_controller_at_end_step(set_pool):
    """"At the beginning of your end step, if this artifact is untapped,
    destroy this artifact and it deals damage to you equal to the number of pin
    counters on it."

    The whole sentence used to lower to nothing — the destroy half refused on
    its "this artifact" subject, so the ability compiled to ``None`` and the
    card sat in the pool with a trigger that never did anything.
    """
    game, doll, p1 = _r34_doll(set_pool, tapped=False)

    game.resolve_end_step(0)
    game._settle()

    assert doll not in p1.battlefield
    assert p1.life == 17, "3 pin counters, 3 damage"


def test_a_tapped_voodoo_doll_is_left_alone(set_pool):
    """CR 603.4's intervening-if: "**if this artifact is untapped**".

    Checked as the trigger would fire, so a tapped Doll's ability never goes on
    the stack at all — which is why the card is worth tapping for its own
    activated ability.
    """
    game, doll, p1 = _r34_doll(set_pool, tapped=True)

    game.resolve_end_step(0)
    assert game.stack == [], "a false intervening-if is not a trigger"
    game._settle()

    assert doll in p1.battlefield
    assert p1.life == 20


# ---------------------------------------------------------------------------
# Phase 4 promotion — six artifacts whose ability compiled to nothing at all.
# Every one reported *supported* on another line while the ability players
# actually activate logged "ability not implemented", which is the hollow shape
# `support_report.py --hollow-lines` censuses. These tests activate in a game
# and assert the effect, never the compilation.
# ---------------------------------------------------------------------------

import pytest

from engine.models import CardDefinition
from engine.named_counters import counters_key, counters_on


def _p4_game(*battlefield, **player_kwargs):
    """A two-player game with *battlefield* under P1, costs off, no sickness."""
    for permanent in battlefield:
        permanent.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=list(battlefield), **player_kwargs)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def _p4_creature(name: str, power: int, toughness: int) -> CardDefinition:
    type_line = "Creature - Test"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


_P4_BATTERIES = {
    "Black Mana Battery": "B",
    "Blue Mana Battery": "U",
    "Green Mana Battery": "G",
    "Red Mana Battery": "R",
    "White Mana Battery": "W",
}


@pytest.mark.parametrize("name,symbol", sorted(_P4_BATTERIES.items()))
def test_a_mana_battery_pays_one_plus_every_counter_it_removes(set_pool, name, symbol):
    """"{T}, Remove any number of charge counters from this artifact: Add {B},
    then add an additional {B} for each charge counter removed this way."

    One template and five cards, so the colour is payload and the test is
    parametrized over the cycle: a colour wired into the instruction instead of
    read off the card is exactly what a single-card test would miss.
    """
    battery = Permanent(card=set_pool("LEG")[name])
    battery.metadata[counters_key("charge")] = 3
    game, p1, _ = _p4_game(battery)

    result = game.activate_permanent_ability(0, name, ability_index=1)
    game._settle()

    assert result.supported
    assert p1.mana_pool[symbol] == 4, "one flat, plus one for each of three counters"
    assert counters_on(battery, "charge") == 0
    assert battery.tapped


def test_a_battery_removing_fewer_counters_pays_out_less(set_pool):
    """"**Any number**" is the payer's choice, announced on activation — so the
    count is not "all of them" wired in, and the counters unspent stay put."""
    battery = Permanent(card=set_pool("LEG")["Red Mana Battery"])
    battery.metadata[counters_key("charge")] = 4
    game, p1, _ = _p4_game(battery)

    result = game.activate_permanent_ability(
        0, "Red Mana Battery", ability_index=1, x_value=1
    )
    game._settle()

    assert result.supported
    assert p1.mana_pool["R"] == 2, "one flat, plus the single counter removed"
    assert counters_on(battery, "charge") == 3


def test_a_battery_with_no_counters_still_makes_its_one_mana(set_pool):
    """Zero is a legal answer to "any number" (CR 601.2h), so the ability is
    activatable with an empty artifact and pays only its printed pip."""
    battery = Permanent(card=set_pool("LEG")["White Mana Battery"])
    game, p1, _ = _p4_game(battery)

    result = game.activate_permanent_ability(0, "White Mana Battery", ability_index=1)
    game._settle()

    assert result.supported
    assert p1.mana_pool["W"] == 1


def test_life_chisel_gains_the_sacrificed_creature_s_toughness(set_pool):
    """"Sacrifice a creature: You gain life equal to the sacrificed creature's
    toughness. Activate only during your upkeep."

    The toughness is read off the creature the *cost* ate (CR 608.2h), which is
    off the battlefield before the ability ever reaches the stack.
    """
    chisel = Permanent(card=set_pool("LEG")["Life Chisel"])
    wall = Permanent(card=_p4_creature("Big Wall", 0, 8))
    game, p1, _ = _p4_game(chisel, wall, life=20)
    game.current_step = "upkeep"
    game.active_player_index = 0

    result = game.activate_permanent_ability(0, "Life Chisel", cost_permanent_index=1)
    game._settle()

    assert result.supported
    assert p1.life == 28
    assert [p.card.name for p in p1.battlefield] == ["Life Chisel"]


def test_life_chisel_is_still_gated_to_your_upkeep(set_pool):
    """The restriction and the effect have to agree. A gate over an ability that
    never resolved is the state this round found the card in — the clause was
    enforced and there was nothing behind it."""
    chisel = Permanent(card=set_pool("LEG")["Life Chisel"])
    wall = Permanent(card=_p4_creature("Big Wall", 0, 8))
    game, p1, _ = _p4_game(chisel, wall, life=20)
    game.current_step = "draw"
    game.active_player_index = 0

    result = game.activate_permanent_ability(0, "Life Chisel", cost_permanent_index=1)

    assert not result.supported
    assert p1.life == 20
    assert wall in p1.battlefield, "a refused activation pays no cost"


def test_mirror_universe_swaps_both_life_totals(set_pool):
    """CR 701.12c: each player gains or loses the difference. Both totals are
    read before either moves — reading the second after the first had moved
    would copy one total onto both players."""
    mirror = Permanent(card=set_pool("LEG")["Mirror Universe"])
    game, p1, p2 = _p4_game(mirror, life=3)
    p2.life = 19
    game.current_step = "upkeep"
    game.active_player_index = 0

    result = game.activate_permanent_ability(0, "Mirror Universe", target_player_index=1)
    game._settle()

    assert result.supported
    assert (p1.life, p2.life) == (19, 3)
    assert mirror not in p1.battlefield, "the exchange costs the artifact"


def test_the_life_exchange_goes_through_the_gain_seam(set_pool):
    """The rising half is a life *gain* (CR 701.12c), so it is recorded like any
    other — which is what lets a replacement effect or a gain trigger see it."""
    mirror = Permanent(card=set_pool("LEG")["Mirror Universe"])
    game, p1, p2 = _p4_game(mirror, life=3)
    p2.life = 19
    game.current_step = "upkeep"
    game.active_player_index = 0

    game.activate_permanent_ability(0, "Mirror Universe", target_player_index=1)
    game._settle()

    assert p1.life_gained_this_turn >= 16


def test_voodoo_doll_deals_its_pin_counters_and_costs_two_x(set_pool):
    """"{X}{X}, {T}: This artifact deals damage equal to the number of pin
    counters on it to any target. X is the number of pin counters on this
    artifact."

    The trailing sentence defines the *cost's* X, so the activator does not
    announce it — and {X}{X} is two of them, not one.
    """
    doll = Permanent(card=set_pool("LEG")["Voodoo Doll"])
    doll.metadata[counters_key("pin")] = 3
    game, p1, p2 = _p4_game(doll)
    game.enforce_mana_costs = True
    p1.mana_pool["C"] = 6

    result = game.activate_permanent_ability(0, "Voodoo Doll", target_player_index=1)
    game._settle()

    assert result.supported
    assert p2.life == 17
    assert sum(p1.mana_pool.values()) == 0, "{X}{X} with X=3 costs six, not three"


def test_voodoo_doll_cannot_be_activated_for_half_its_cost(set_pool):
    """The half a single "{x}" substring test charged: five mana is one short of
    the {X}{X} the card prints."""
    doll = Permanent(card=set_pool("LEG")["Voodoo Doll"])
    doll.metadata[counters_key("pin")] = 3
    game, p1, p2 = _p4_game(doll)
    game.enforce_mana_costs = True
    p1.mana_pool["C"] = 5

    result = game.activate_permanent_ability(0, "Voodoo Doll", target_player_index=1)

    assert not result.supported
    assert p2.life == 20


def test_triassic_egg_returns_a_creature_card_from_the_graveyard(set_pool):
    """"Sacrifice this artifact: Choose one. … • Return target creature card
    from your graveyard to the battlefield."

    A modal *activated* ability whose head carries a trailing restriction: the
    head refused on those four words, so the whole ability went unread and only
    the counter-adding line kept the card looking supported.
    """
    egg = Permanent(card=set_pool("LEG")["Triassic Egg"])
    egg.metadata[counters_key("hatchling")] = 2
    game, p1, _ = _p4_game(egg, graveyard=[_p4_creature("Sleeper", 2, 2)])

    result = game.activate_permanent_ability(0, "Triassic Egg", ability_index=2)
    game._settle()

    assert result.supported
    assert [p.card.name for p in p1.battlefield] == ["Sleeper"]


def test_triassic_egg_needs_two_hatchling_counters(set_pool):
    """The restriction rides onto every expanded mode. Dropped in that rewrite
    it would have gated nothing at all — one counter, both modes free."""
    egg = Permanent(card=set_pool("LEG")["Triassic Egg"])
    egg.metadata[counters_key("hatchling")] = 1
    game, p1, _ = _p4_game(egg, graveyard=[_p4_creature("Sleeper", 2, 2)])

    result = game.activate_permanent_ability(0, "Triassic Egg", ability_index=2)

    assert not result.supported
    assert egg in p1.battlefield


def test_sword_of_the_ages_deals_the_total_power_it_ate_and_exiles_it(set_pool):
    """"{T}, Sacrifice this artifact and any number of creatures you control:
    … deals X damage …, where X is the total power of the creatures sacrificed
    this way, then exile this artifact and those creature cards."

    Every part is last-known information: the creatures are cards in a graveyard
    by the time X is read, and the exile reaches into that graveyard for exactly
    them.
    """
    sword = Permanent(card=set_pool("LEG")["Sword of the Ages"])
    ogre = Permanent(card=_p4_creature("Ogre", 3, 3))
    bear = Permanent(card=_p4_creature("Bear", 2, 2))
    game, p1, p2 = _p4_game(sword, ogre, bear)

    result = game.activate_permanent_ability(
        0, "Sword of the Ages", target_player_index=1,
        cost_permanent_ids=[ogre.permanent_id, bear.permanent_id],
    )
    game._settle()

    assert result.supported
    assert p2.life == 15, "3 + 2 total power"
    assert p1.battlefield == []
    assert sorted(c.name for c in p1.exile) == ["Bear", "Ogre", "Sword of the Ages"]
    assert p1.graveyard == [], "the sacrificed cards are exiled, not left behind"


def test_sword_of_the_ages_sacrificing_nothing_deals_nothing(set_pool):
    """"Any number" includes none (CR 601.2h), and none is what a seat that
    names no creature has chosen — so the ability may not help itself to a board
    to make its X larger."""
    sword = Permanent(card=set_pool("LEG")["Sword of the Ages"])
    ogre = Permanent(card=_p4_creature("Ogre", 3, 3))
    game, p1, p2 = _p4_game(sword, ogre)

    result = game.activate_permanent_ability(0, "Sword of the Ages", target_player_index=1)
    game._settle()

    assert result.supported
    assert p2.life == 20
    assert [p.card.name for p in p1.battlefield] == ["Ogre"]
    assert [c.name for c in p1.exile] == ["Sword of the Ages"]


# ---------------------------------------------------------------------------
# Forethought Amulet (Phase 4 parse-coverage round) — a CR 614 damage cap
# ---------------------------------------------------------------------------


def _amulet_game(set_pool, with_amulet: bool):
    pool = set_pool("LEG")
    perms = [Permanent(card=pool["Forethought Amulet"])] if with_amulet else []
    game = Game(players=[
        PlayerState(name="P1"),
        PlayerState(name="P2", battlefield=perms),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._sync_control()
    return game


def test_forethought_amulet_caps_instant_and_sorcery_damage(catalog_by_name, set_pool):
    """"If an instant or sorcery source would deal 3 or more damage to you, it
    deals 2 damage to you instead."

    A CR 614 replacement with no interceptor behind it until this round: the
    card compiled supported on its upkeep line while the half a player buys it
    for did nothing. Capped at the *dealt* number (CR 120.4b), not at the life
    lost — which is what separates it from Ali from Cairo.
    """
    game = _amulet_game(set_pool, with_amulet=True)
    game.players[0].hand.append(catalog_by_name["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    game._settle()
    assert game.players[1].life == 18

    # Below the threshold, the Amulet does nothing — a 2-damage burn is still 2.
    bare = _amulet_game(set_pool, with_amulet=False)
    bare.players[0].hand.append(catalog_by_name["Lightning Bolt"])
    bare.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    bare._settle()
    assert bare.players[1].life == 17, "no Amulet, no cap"


def test_forethought_amulet_ignores_a_source_of_the_wrong_class(catalog_by_name, set_pool):
    """The source class is part of the printed sentence, not decoration: an
    artifact's ping is not an instant or sorcery source, so nothing is capped.
    A cap that fired on every source would be a strictly better card."""
    game = _amulet_game(set_pool, with_amulet=True)
    rod = Permanent(card=catalog_by_name["Rod of Ruin"])
    game.players[0].battlefield.append(rod)
    game._sync_control()
    assert game.queue_permanent_ability(0, "Rod of Ruin", target_player_index=1).supported
    game._settle()
    assert game.players[1].life == 19


# --- FixC: a sweep names a class, not a target ---
def test_arena_is_castable_on_a_board_with_no_legendary_creature(set_pool):
    """An **artifact** that demanded a creature target to be cast.

    ``derive_cast_spec`` reads a permanent's enters trigger at cast time — this
    engine's standing approximation of CR 603.3d — so Arena's "tap all
    legendary creatures" reached the cast picker, and its ``type_filter``
    was read as the class a picker offers rather than the class the sweep
    affects (CR 115.1a). On a creature-free board the browser enumerated zero
    candidates and abandoned the cast, which makes an Artifact spell that costs
    {4} unplayable for the reason its *trigger* would have found nothing to do.

    The trigger fared no better once cast: with no legal target it was struck
    off the stack under CR 603.3c, a rule about targets applied to an ability
    that names none.
    """
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("LEG")["Arena of the Ancients"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False

    assert game.cast_target_spec(0, set_pool("LEG")["Arena of the Ancients"]) == {
        "kind": "none", "requires_target": False, "valid_targets": [],
    }

    result = game.cast_from_hand(0, "Arena of the Ancients")
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert [p.card.name for p in game.players[0].battlefield] == [
        "Arena of the Ancients"
    ]
    assert not any("603.3c" in line for line in game.log), game.log


def test_arena_taps_the_class_it_names_without_being_asked_for_one(set_pool):
    """And on a populated board the sweep is unchanged: every legend, neither
    chosen nor narrowed by anything a caster clicked."""
    game, my_legend, my_bear, their_legend = _arena_game(set_pool)

    assert game.cast_target_spec(0, set_pool("LEG")["Arena of the Ancients"])[
        "requires_target"
    ] is False

    game.cast_from_hand(0, "Arena of the Ancients")
    game._settle()

    assert my_legend.tapped and their_legend.tapped
    assert not my_bear.tapped
# --- end FixC ---
