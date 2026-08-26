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
