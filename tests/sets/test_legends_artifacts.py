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
