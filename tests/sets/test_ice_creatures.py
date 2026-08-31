"""Ice Age (ICE) creature cards — the parallel waves.

ICE is a *measured* set, mid-implementation: cards land here with the round
that buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool
resolves through ``set_pool("ICE")`` even though the set is not shipped —
reading a card file is not shipping it. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

Rounds 1–41, the serial half, are in ``test_ice_creatures_early_rounds.py``:
the file passed the 2,600-line guard and README's next axis after the printed
type is a round boundary. Sections here are named for the wave and group that
bought them (``W<wave>G<group>``) rather than for a round, because the work
ran in parallel worktrees from that point on.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.auras import attach_aura
from engine.cumulative_upkeep import cumulative_upkeep_cost
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from engine.pt import add_pt_modifier
from tests.helpers import _nosick

# --- W1G3: mana, additional costs, cost restrictions ---
def _w1g3_cost(**pips):
    """A whole mana cost as a symbol dict — every symbol present, the way
    engine/mana_payment.py says a cost is spelled everywhere."""
    cost = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}
    cost["generic"] = 0
    cost.update(pips)
    return cost


def _w1g3_board(set_pool, *names, hand=(), library=()):
    """Seat 0 with those ICE permanents out, unsick, costs unenforced."""
    pool = set_pool("ICE")
    mine = [Permanent(card=pool[n]) for n in names]
    game = Game(
        players=[
            PlayerState(
                name="P1", battlefield=mine,
                hand=[pool[n] for n in hand],
                library=[pool[n] for n in library],
                life=20,
            ),
            PlayerState(name="P2", life=20),
        ]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    for perm in mine:
        _nosick(perm)
    return game, mine


def test_w1g3_orcish_lumberjack_makes_three_mana_from_one_forest(set_pool):
    """"{T}, Sacrifice a Forest: Add three mana in any combination of {R}
    and/or {G}."

    The count and the two symbols are payload; each unit's colour is the seat's
    choice at resolution. Three mana, not one — the clause refused on
    "expected 'of'" before this, so the card was unsupported rather than wrong.
    """
    game, (jack, forest) = _w1g3_board(set_pool, "Orcish Lumberjack", "Forest")

    result = game.activate_permanent_ability(0, "Orcish Lumberjack")
    game._settle()

    assert result.supported, result.details
    assert forest not in game.players[0].battlefield, "the Forest paid the cost"
    pool = game.players[0].mana_pool
    assert pool["R"] + pool["G"] == 3
    assert all(
        pool[symbol] == 0 for symbol in pool if symbol not in ("R", "G")
    ), "only the printed symbols are produced"


def test_w1g3_orcish_lumberjack_honours_the_colour_the_seat_named(set_pool):
    """The seat's pick rides the same ``mana_color`` channel a dual land's
    choice does. All three of the green, because "any combination" includes
    every unit being the same symbol."""
    game, _ = _w1g3_board(set_pool, "Orcish Lumberjack", "Forest")

    game.activate_permanent_ability(0, "Orcish Lumberjack", mana_color="G")
    game._settle()

    assert game.players[0].mana_pool["G"] == 3
    assert game.players[0].mana_pool["R"] == 0


def test_w1g3_orcish_lumberjack_takes_an_explicit_split(set_pool):
    """"…in any combination of" really is a per-unit choice, and the engine can
    say so: a named split of two green and one red is honoured whole. Only the
    printed symbols and only the printed total — anything else is a split that
    was never offered, and is discarded rather than part-applied."""
    from engine.game_types import OracleExecutionContext
    from engine.handlers.registry import EFFECT_HANDLERS

    game, (jack, _forest) = _w1g3_board(set_pool, "Orcish Lumberjack", "Forest")
    program = compile_card_oracle(jack.card)
    instruction = program.activated_abilities[0].instruction

    EFFECT_HANDLERS[instruction.kind](
        game, instruction,
        OracleExecutionContext(
            caster=game.players[0], target=game.players[1], card=jack.card,
            source_permanent=jack,
            choices={"mana_combination": {"G": 2, "R": 1}},
        ),
    )

    assert game.players[0].mana_pool["G"] == 2
    assert game.players[0].mana_pool["R"] == 1


def test_w1g3_adarkar_unicorn_mana_pays_a_cumulative_upkeep_and_nothing_else(set_pool):
    """"{T}: Add {U} or {C}{U}. Spend this mana only to pay cumulative upkeep
    costs." (CR 106.6.)

    Both halves, together: the alternative the seat takes is a written-out
    *quantity* (the larger one by default — nothing costs anything to choose and
    this engine has no mana burn), and every unit of it lands in the restricted
    bucket rather than in the pool. A restriction parsed and then charged by
    nobody is mana more freely spendable than the card allows, so the second
    half is the one that matters.
    """
    from engine.restricted_mana import CAST, CUMULATIVE_UPKEEP, PaymentPurpose

    game, (unicorn,) = _w1g3_board(set_pool, "Adarkar Unicorn")

    result = game.activate_permanent_ability(0, "Adarkar Unicorn")
    game._settle()

    assert result.supported, result.details
    player = game.players[0]
    assert player.mana_pool["U"] == 0 and player.mana_pool["C"] == 0
    assert player.restricted_mana["cumulative_upkeep"] == {"C": 1, "U": 1}

    # It cannot be spent on a spell…
    assert not game._pay_mana_cost(
        player, _w1g3_cost(U=1),
        purpose=PaymentPurpose(CAST, card=unicorn.card),
    )
    assert player.restricted_mana["cumulative_upkeep"]["U"] == 1
    # …and it can be spent on a cumulative upkeep.
    assert game._pay_mana_cost(
        player, _w1g3_cost(U=1, generic=1),
        purpose=PaymentPurpose(CUMULATIVE_UPKEEP, source=unicorn),
    )
    assert player.restricted_mana["cumulative_upkeep"] == {"C": 0, "U": 0}


def test_w1g3_krovikan_sorcerer_discard_cost_is_narrowed_by_colour(set_pool):
    """"{T}, Discard a nonblack card: Draw a card."

    A discard cost narrowed by a *colour exclusion*. ``exclude_colors`` had no
    entry in the card matcher's key set, so the phrase was refused whole and the
    card was unsupported — the direction that costs support rather than
    narrowing, but a gap either way.
    """
    from engine.subject_filters import card_matches_any

    pool = set_pool("ICE")
    program = compile_card_oracle(pool["Krovikan Sorcerer"])
    assert program.supported
    narrowing = program.activated_abilities[0].cost.discard_filters
    assert narrowing == ({"exclude_colors": ["B"]},)

    assert card_matches_any(pool["Balduvian Bears"], narrowing)   # red
    assert not card_matches_any(pool["Hoar Shade"], narrowing)    # black


def test_w1g3_krovikan_sorcerer_draws_for_a_nonblack_card(set_pool):
    """Played out: the cost eats the red card in hand and the draw happens."""
    game, _ = _w1g3_board(
        set_pool, "Krovikan Sorcerer",
        hand=["Balduvian Bears"], library=["Glacial Wall", "Glacial Wall"],
    )

    result = game.activate_permanent_ability(0, "Krovikan Sorcerer", ability_index=0)
    game._settle()

    assert result.supported, result.details
    assert [c.name for c in game.players[0].hand] == ["Glacial Wall"]


def test_w1g3_krovikan_sorcerer_discards_one_of_the_two_it_drew(set_pool):
    """"{T}, Discard a black card: Draw two cards, then discard one **of
    them**."

    "Of them" is an identity restriction, not a characteristic one: the discard
    comes out of the two cards this resolution just drew. Dropped, the seat
    could pitch anything in hand — a strictly better card than the one printed —
    and the prompt is held to the hand positions the draw landed in, because
    every copy of a card in a hand is the same Python object and no filter can
    tell one from another.
    """
    game, _ = _w1g3_board(
        set_pool, "Krovikan Sorcerer",
        hand=["Hoar Shade", "Balduvian Bears"],
        library=["Glacial Wall", "Arnjlot's Ascent"],
    )
    game.interactive_seats = {0}

    result = game.activate_permanent_ability(0, "Krovikan Sorcerer", ability_index=1)
    game._settle()

    assert result.supported, result.details
    choice = game.pending_choice_of("discard")
    assert choice is not None
    hand = game.players[0].hand
    eligible = game.live_discard_candidates(choice)
    assert [hand[i].name for i in eligible] == ["Glacial Wall", "Arnjlot's Ascent"]


def test_w1g3_a_single_symbol_choice_also_lands_in_the_restricted_bucket(set_pool):
    """The sibling branch Adarkar Unicorn's shape exposed.

    "Add {B} or {R}" lowers to ``pips_choice``, and its lowering has always
    carried ``spend_only`` beside it — but the handler branch wrote straight
    into ``mana_pool`` and never asked. No card in the pool prints the pair
    today, which is exactly why the miss was invisible: had the Unicorn been
    printed "Add {U} or {C}" instead of "{U} or {C}{U}", it would have gone down
    that branch and made unrestricted mana while reporting itself supported.

    Named through the Unicorn's own restriction key so the two branches are held
    to one answer.
    """
    from engine.game_types import OracleExecutionContext
    from engine.grammar import compile_line
    from engine.handlers.registry import EFFECT_HANDLERS

    unicorn = set_pool("ICE")["Adarkar Unicorn"]
    key = compile_card_oracle(unicorn).activated_abilities[0].instruction.payload[
        "spend_only"
    ]

    line = compile_line(
        "{T}: Add {B} or {R}. Spend this mana only to pay cumulative upkeep costs."
    )
    instruction = line.instructions[0]
    assert instruction.payload["pips_choice"] == (("B", 1), ("R", 1))
    assert instruction.payload["spend_only"] == key

    game, _ = _w1g3_board(set_pool, "Adarkar Unicorn")
    EFFECT_HANDLERS[instruction.kind](
        game, instruction,
        OracleExecutionContext(
            caster=game.players[0], target=game.players[1], card=unicorn,
        ),
    )

    assert game.players[0].mana_pool["B"] == 0
    assert game.players[0].restricted_mana[key] == {"B": 1}

# --- end W1G3 ---
# --- W1G2: combat relations and end of combat ---
def _w1g2_combat(
    game: Game, attackers: list[int], blocks: dict[int, int | list[int]] | None = None
) -> None:
    """Put seat 0's attackers and seat 1's blockers in, without a turn.

    *blocks* is keyed by the **blocker's** slot, as `declare_blockers` takes it.
    """
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, msg = game.declare_attackers(0, attackers, 1)
    assert ok, msg
    game._set_phase_and_step("combat", "declare_blockers")
    ok, msg = game.declare_blockers(1, blocks or {})
    assert ok, msg


def test_kjeldoran_frostbeast_compiles_to_the_combat_relation_sweep(set_pool):
    """"At end of combat, destroy all creatures blocking or blocked by this
    creature." A production, not a card hook: Abu Ja'far prints the same
    sentence under a dies trigger and both compile to one instruction."""
    program = compile_card_oracle(set_pool("ICE")["Kjeldoran Frostbeast"])

    assert program.supported
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "end_of_combat"
    assert trigger.instruction.kind == "destroy_creatures_in_combat_with_source"
    # Abu Ja'far prints "They can't be regenerated"; the Frostbeast does not.
    assert "bypass_regeneration" not in trigger.instruction.payload


def test_kjeldoran_frostbeast_destroys_its_blocker_at_end_of_combat(set_pool):
    """The blocker survives combat damage (a 2/4 beast against a 3/3) and is
    destroyed anyway when the end of combat step comes."""
    pool = set_pool("ICE")
    beast = _nosick(Permanent(card=pool["Kjeldoran Frostbeast"]))
    blocker = _nosick(Permanent(card=pool["Tor Giant"]))
    bystander = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[beast], life=20)
    p2 = PlayerState(name="P2", battlefield=[blocker, bystander], life=20)
    game = Game(players=[p1, p2])

    _w1g2_combat(game, [0], {0: [0]})
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    game._settle()
    assert any(p is blocker for p in p2.battlefield), "3 damage does not kill a 3/3"

    game.end_combat(step_already_started=False)
    game._settle()

    assert not any(p is blocker for p in p2.battlefield)
    assert any(c.name == "Tor Giant" for c in p2.graveyard)
    assert any(p is bystander for p in p2.battlefield), "an uninvolved creature lives"


def test_kjeldoran_frostbeast_destroys_the_creature_it_blocked(set_pool):
    """The other half of "blocking or blocked by" — the beast as the blocker."""
    pool = set_pool("ICE")
    beast = _nosick(Permanent(card=pool["Kjeldoran Frostbeast"]))
    attacker = _nosick(Permanent(card=pool["Tor Giant"]))
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[beast], life=20)
    game = Game(players=[p1, p2])

    _w1g2_combat(game, [0], {0: [0]})
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    game._settle()

    game.end_combat(step_already_started=False)
    game._settle()

    assert not any(p is attacker for p in p1.battlefield)
    assert any(p is beast for p in p2.battlefield), "the beast itself survives"


def test_kjeldoran_frostbeast_out_of_combat_destroys_nothing(set_pool):
    """No relation, no victims — the sweep must not widen to the board."""
    pool = set_pool("ICE")
    beast = _nosick(Permanent(card=pool["Kjeldoran Frostbeast"]))
    bystander = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[beast], life=20)
    p2 = PlayerState(name="P2", battlefield=[bystander], life=20)
    game = Game(players=[p1, p2])
    game.active_player_index = 0

    game.end_combat(step_already_started=False)
    game._settle()

    assert any(p is beast for p in p1.battlefield)
    assert any(p is bystander for p in p2.battlefield)


def test_sibilant_spirit_offers_the_draw_to_the_player_being_attacked(set_pool):
    """"Whenever this creature attacks, defending player may draw a card."

    The offer is made to the seat the *combat* named, not to the ability's
    controller — the whole point of the card, and the direction a wrong seat
    would be wrong in.
    """
    pool = set_pool("ICE")
    spirit = _nosick(Permanent(card=pool["Sibilant Spirit"]))
    p1 = PlayerState(name="P1", battlefield=[spirit], life=20)
    p2 = PlayerState(
        name="P2", life=20,
        library=[pool["Balduvian Bears"], pool["Tor Giant"]],
    )
    game = Game(players=[p1, p2])
    p1.library = [pool["Brown Ouphe"]]

    program = compile_card_oracle(spirit.card)
    (trigger,) = program.triggered_abilities
    assert trigger.instruction.kind == "may"
    assert trigger.instruction.payload["actor"] == "defending_player"

    _w1g2_combat(game, [0], {})
    game._settle()

    (offer,) = game.pending_optional_pays
    assert offer["card_name"] == "Sibilant Spirit"
    assert game.players[offer["player_index"]] is p2

    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert len(p2.hand) == 1, "the defender drew"
    assert p1.hand == [], "the attacker's controller did not"


def test_sibilant_spirit_refuses_the_phrase_under_an_event_with_no_defender(set_pool):
    """"Defending player" is a fact about a combat. Under a trigger that
    records none the offer would be made to nobody, which is an optional
    effect that silently never happens — so the line refuses instead."""
    from engine.grammar import compile_line

    attacks = compile_line(
        "Whenever this creature attacks, defending player may draw a card."
    )
    assert attacks.usable

    upkeep = compile_line(
        "At the beginning of your upkeep, defending player may draw a card."
    )
    assert not upkeep.lowered
    assert "defending player" in (upkeep.lowering_error or ""), upkeep.lowering_error


def test_johtull_wurm_shrinks_per_blocker_beyond_the_first(set_pool):
    """"Whenever this creature becomes blocked, it gets -2/-1 until end of turn
    for each creature blocking it beyond the first." Negative rampage, and the
    count is CR 702.23a's: the *first* blocker is free."""
    pool = set_pool("ICE")
    wurm = _nosick(Permanent(card=pool["Johtull Wurm"]))
    blockers = [_nosick(Permanent(card=pool["Glacial Wall"])) for _ in range(3)]
    p1 = PlayerState(name="P1", battlefield=[wurm], life=20)
    p2 = PlayerState(name="P2", battlefield=blockers, life=20)
    game = Game(players=[p1, p2])
    base_power, base_toughness = wurm.effective_power, wurm.effective_toughness

    _w1g2_combat(game, [0], {0: 0, 1: 0, 2: 0})
    game._settle()

    assert wurm.effective_power == base_power - 4, "two blockers beyond the first"
    assert wurm.effective_toughness == base_toughness - 2


def test_johtull_wurm_is_unchanged_by_a_single_blocker(set_pool):
    """One blocker is none beyond the first, so the count is zero rather than
    negative — the offset is floored, not subtracted blindly."""
    pool = set_pool("ICE")
    wurm = _nosick(Permanent(card=pool["Johtull Wurm"]))
    wall = _nosick(Permanent(card=pool["Glacial Wall"]))
    p1 = PlayerState(name="P1", battlefield=[wurm], life=20)
    p2 = PlayerState(name="P2", battlefield=[wall], life=20)
    game = Game(players=[p1, p2])
    base_power, base_toughness = wurm.effective_power, wurm.effective_toughness

    _w1g2_combat(game, [0], {0: [0]})
    game._settle()

    assert (wurm.effective_power, wurm.effective_toughness) == (
        base_power, base_toughness
    )


def test_a_for_each_count_refuses_a_relation_it_cannot_take(set_pool):
    """The bug this round found on the way past.

    ``count_spec`` built its payload straight off ``to_payload``, which emits
    nothing for a relative narrowing — so "for each creature blocking it"
    reduced to "for each creature" and counted the whole of its owner's
    battlefield. A count that is too large is a pump that is too big, so a
    relation with no payload form and no evaluator now refuses the sentence."""
    from engine.grammar import compile_line

    reads = compile_line(
        "This creature gets -1/-1 until end of turn for each creature blocking it."
    )
    assert reads.lowered
    assert reads.instructions[0].payload["x_from_count"]["blocking_source"] is True

    refuses = compile_line(
        "This creature gets -1/-1 until end of turn for each creature that "
        "dealt damage to it this turn."
    )
    assert not refuses.lowered
    assert "count cannot test" in (refuses.lowering_error or ""), refuses.lowering_error


def test_marton_stromgald_pumps_the_team_by_the_number_of_attackers(set_pool):
    """"Whenever Márton Stromgald attacks, other attacking creatures get +1/+1
    until end of turn for each attacking creature other than Márton Stromgald."

    Three other attackers: each of them gets +3/+3, and Márton gets nothing.
    """
    pool = set_pool("ICE")
    marton = _nosick(Permanent(card=pool["Márton Stromgald"]))
    friends = [_nosick(Permanent(card=pool["Balduvian Bears"])) for _ in range(3)]
    bench = _nosick(Permanent(card=pool["Tor Giant"]))
    p1 = PlayerState(name="P1", battlefield=[marton, *friends, bench], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    marton_power = marton.effective_power

    _w1g2_combat(game, [0, 1, 2, 3])
    game._settle()

    for friend in friends:
        assert (friend.effective_power, friend.effective_toughness) == (5, 5), (
            "2/2 plus +3/+3, one for each other attacker"
        )
    assert marton.effective_power == marton_power, "\"other\" excludes the source"
    assert (bench.effective_power, bench.effective_toughness) == (3, 3), (
        "a creature that stayed home is not attacking"
    )


def test_marton_stromgald_alone_pumps_nobody(set_pool):
    """Attacking by himself, the count is zero and there is no team to pump."""
    pool = set_pool("ICE")
    marton = _nosick(Permanent(card=pool["Márton Stromgald"]))
    p1 = PlayerState(name="P1", battlefield=[marton], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    before = (marton.effective_power, marton.effective_toughness)

    _w1g2_combat(game, [0])
    game._settle()

    assert (marton.effective_power, marton.effective_toughness) == before


def test_marton_stromgald_pumps_the_blockers_on_his_side(set_pool):
    """The mirrored line, and the mirror is the whole point: the same sentence
    with "blocks" in it, so it is the same production and the same handler."""
    pool = set_pool("ICE")
    marton = _nosick(Permanent(card=pool["Márton Stromgald"]))
    friends = [_nosick(Permanent(card=pool["Balduvian Bears"])) for _ in range(2)]
    attackers = [_nosick(Permanent(card=pool["Tor Giant"])) for _ in range(3)]
    p1 = PlayerState(name="P1", battlefield=attackers, life=20)
    p2 = PlayerState(name="P2", battlefield=[marton, *friends], life=20)
    game = Game(players=[p1, p2])

    _w1g2_combat(game, [0, 1, 2], {0: 0, 1: 1, 2: 2})
    game._settle()

    for friend in friends:
        assert (friend.effective_power, friend.effective_toughness) == (4, 4), (
            "2/2 plus +2/+2, one for each other blocker"
        )
# --- end W1G2 ---
# --- W1G5: statics, continuous effects, control changes ---
def _w1g5_squatters_game(set_pool, catalog_by_name):
    """Orcish Squatters attacking, with a land of its **own** controller's on
    the board beside the defender's two.

    That third land is the point: "target land **defending player controls**"
    must never offer it, and the seat is a fact about the combat rather than
    about the seat choosing.
    """
    squatters = Permanent(card=set_pool("ICE")["Orcish Squatters"])
    p1 = PlayerState(name="P1", battlefield=[
        squatters, Permanent(card=catalog_by_name["Mountain"]),
    ])
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=catalog_by_name["Forest"]),
        Permanent(card=catalog_by_name["Island"]),
    ])
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}
    return game, p1, p2, squatters


def _w1g5_attack_unblocked(game):
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    game.advance_combat_phase()   # declare blockers
    ok, msg = game.declare_blockers(1, {})
    assert ok, msg
    game._settle()
    game.advance_combat_phase()   # blocks lock: the trigger fires here
    return game.pending_choices_of("trigger_target")


def _w1g5_finish_combat(game):
    game._settle()
    for _ in range(len(list(game._phase_steps("combat"))) + 1):
        if game.current_turn_phase != "combat":
            break
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        game._settle()
        if (game.current_turn_phase, game.current_step) == before:
            break


def test_orcish_squatters_offers_only_the_defending_players_lands(
    set_pool, catalog_by_name
):
    """The printed noun phrase is "target land defending player controls", and
    the picker is what enforces the seat — ``subject_matches`` deliberately
    refuses that key, because the seat belongs to the combat and not to the
    permanent."""
    game, _, p2, _ = _w1g5_squatters_game(set_pool, catalog_by_name)

    pending = list(_w1g5_attack_unblocked(game))

    assert len(pending) == 1, game.log
    offered = pending[0].data["targets"]
    assert {t["name"] for t in offered} == {"Forest", "Island"}, game.log
    assert {t["permanent_id"] for t in offered} == {
        p.permanent_id for p in p2.battlefield
    }


def test_orcish_squatters_steals_the_land_and_then_deals_no_combat_damage(
    set_pool, catalog_by_name
):
    """The whole sentence: the land changes hands, and "if you do, this creature
    assigns no combat damage this turn" is read by the damage step — so the
    defender's life is what this asserts, not a flag."""
    game, p1, p2, _ = _w1g5_squatters_game(set_pool, catalog_by_name)

    pending = list(_w1g5_attack_unblocked(game))
    chosen = next(t for t in pending[0].data["targets"] if t["name"] == "Forest")
    assert game.confirm_trigger_target(0, chosen["permanent_id"])
    game._settle()
    assert game.confirm_optional_pay(0, "Orcish Squatters", accept=True)
    _w1g5_finish_combat(game)

    assert "Forest" in [p.card.name for p in p1.battlefield], game.log
    assert [p.card.name for p in p2.battlefield] == ["Island"], game.log
    assert p2.life == 20, game.log


def test_orcish_squatters_gives_the_land_back_when_it_leaves(
    set_pool, catalog_by_name
):
    """"…for as long as you control this creature" (CR 611.2b). The contribution
    is keyed on the Squatters and the state-based sweep re-checks the condition,
    so the land reverts to the seat it entered under — never to whoever happened
    to hold it last."""
    game, p1, p2, squatters = _w1g5_squatters_game(set_pool, catalog_by_name)

    pending = list(_w1g5_attack_unblocked(game))
    chosen = next(t for t in pending[0].data["targets"] if t["name"] == "Forest")
    assert game.confirm_trigger_target(0, chosen["permanent_id"])
    game._settle()
    assert game.confirm_optional_pay(0, "Orcish Squatters", accept=True)
    stolen = game.permanent_by_id(chosen["permanent_id"])
    assert game.controller_index_of(stolen) == 0, game.log

    game.remove_from_battlefield(squatters)
    game.check_state_based_actions()

    assert game.controller_index_of(stolen) == 1, game.log
    assert {p.card.name for p in p2.battlefield} == {"Forest", "Island"}, game.log


def _w1g5_merieke_board(set_pool, catalog_by_name):
    merieke = Permanent(card=set_pool("ICE")["Merieke Ri Berit"])
    _nosick(merieke)
    victim = Permanent(card=catalog_by_name["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[merieke]),
        PlayerState(name="P2", battlefield=[victim]),
    ])
    game.enforce_mana_costs = False
    return game, merieke, victim


def _w1g5_merieke_steals(game):
    result = game.activate_permanent_ability(
        0, "Merieke Ri Berit", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()


def test_merieke_ri_berit_compiles_its_own_name_as_a_self_reference(set_pool):
    """The card's oracle text names the card — printed text, not a reason to key
    on the name. The lexer collapses it to the same SELF token "this creature"
    produces, so the ability lowers to the ordinary linked steal plus the
    delayed ability the second sentence creates."""
    program = compile_card_oracle(set_pool("ICE")["Merieke Ri Berit"])

    assert program.supported
    ability = program.activated_abilities[0]
    steps = ability.instruction.payload["steps"]
    assert [i.kind for i in steps] == [
        "steal_target_linked_to_source", "create_delayed_trigger",
    ]
    assert steps[0].payload["link_conditions"] == ["you_control_source"]
    assert steps[1].payload["event"] == "bound_permanent_leaves_or_untaps"
    assert steps[1].payload["instruction"].payload["bypass_regeneration"] is True


def test_merieke_ri_berit_takes_the_creature_and_stays_tapped(
    set_pool, catalog_by_name
):
    game, merieke, victim = _w1g5_merieke_board(set_pool, catalog_by_name)

    _w1g5_merieke_steals(game)

    assert game.controller_index_of(victim) == 0, game.log
    assert merieke.tapped


def test_merieke_ri_berit_destroys_the_creature_when_she_untaps(
    set_pool, catalog_by_name
):
    """"When Merieke Ri Berit … becomes untapped, destroy that creature."
    Announced from ``become_untapped``, which is the one place a permanent
    untaps — an announcement wired into the untap step alone would miss every
    Twiddle."""
    game, merieke, victim = _w1g5_merieke_board(set_pool, catalog_by_name)
    _w1g5_merieke_steals(game)

    game.become_untapped(merieke)
    game._settle()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(victim), game.log
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]


def test_merieke_ri_berit_destroys_the_creature_when_she_leaves(
    set_pool, catalog_by_name
):
    """The other half of the same delayed ability. It also proves the two ends
    do not fight: the linked steal reverts control as the sweep runs, and the
    delayed destroy still finds the creature by the id it bound."""
    game, merieke, victim = _w1g5_merieke_board(set_pool, catalog_by_name)
    _w1g5_merieke_steals(game)

    game.remove_from_battlefield(merieke)
    game._settle()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(victim), game.log
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]


def test_merieke_ri_berit_leaves_an_untouched_board_alone(
    set_pool, catalog_by_name
):
    """The delayed ability is armed only by the steal, and it watches Merieke by
    id. Untapping some *other* permanent must not fire it — the guard against an
    entry that answers to the first thing to untap."""
    game, merieke, victim = _w1g5_merieke_board(set_pool, catalog_by_name)
    other = Permanent(card=catalog_by_name["Mountain"], tapped=True)
    game.players[0].battlefield.append(other)
    _w1g5_merieke_steals(game)

    game.become_untapped(other)
    game._settle()
    game.check_state_based_actions()

    assert game.is_on_battlefield(victim), game.log
    assert game.controller_index_of(victim) == 0


def _w1g5_titan_board(set_pool, catalog_by_name):
    titan = Permanent(card=set_pool("ICE")["Mountain Titan"])
    _nosick(titan)
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[titan],
            hand=[
                catalog_by_name["Dark Ritual"],
                catalog_by_name["Lightning Bolt"],
                catalog_by_name["Dark Ritual"],
            ],
        ),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    return game, titan


def _w1g5_cast(game, name):
    game.cast_from_hand(0, name)
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()


def test_mountain_titan_arms_a_delayed_cast_trigger(set_pool):
    """"Until end of turn, whenever you cast a black spell, …" is CR 603.7's
    delayed triggered ability with a stated duration, not an ability the
    permanent has — the same shape Subira prints over a combat event, with the
    subject being a **spell** instead of a creature."""
    program = compile_card_oracle(set_pool("ICE")["Mountain Titan"])

    assert program.supported
    payload = program.activated_abilities[0].instruction.payload
    assert payload["event"] == "you_cast_spell"
    assert payload["subject_filter"] == {"color_filter": "B"}
    assert payload["once"] is False
    assert payload["duration"] == "end_of_turn"


def test_mountain_titan_grows_only_after_the_ability_and_only_on_black(
    set_pool, catalog_by_name
):
    """Three assertions in one game, because each is the other's control: a
    black spell before the activation does nothing, a red spell after it does
    nothing, and a black spell after it grows the Titan."""
    game, titan = _w1g5_titan_board(set_pool, catalog_by_name)

    _w1g5_cast(game, "Dark Ritual")
    assert titan.effective_power == 2, game.log

    assert game.activate_permanent_ability(0, "Mountain Titan").supported
    while game.stack:
        game.resolve_top_of_stack()

    _w1g5_cast(game, "Lightning Bolt")
    assert titan.effective_power == 2, game.log

    _w1g5_cast(game, "Dark Ritual")
    assert titan.effective_power == 3, game.log


def test_mountain_titan_stops_growing_when_the_turn_ends(
    set_pool, catalog_by_name
):
    """CR 603.7b: "until end of turn" is the stated duration, so the ability
    that never stops triggering does stop existing."""
    game, titan = _w1g5_titan_board(set_pool, catalog_by_name)
    assert game.activate_permanent_ability(0, "Mountain Titan").supported
    while game.stack:
        game.resolve_top_of_stack()

    game.resolve_cleanup_step(0)

    assert game.delayed_triggers == [], game.log
    _w1g5_cast(game, "Dark Ritual")
    assert titan.effective_power == 2, game.log


def test_merieke_ri_berit_cannot_take_a_guardian_beast_artifact(
    set_pool, catalog_by_name
):
    """The linked steal is the general one now, so the prohibition it used to
    carry alone had to move somewhere every control change asks — and this is
    the check that it still holds where it always did."""
    beast = Permanent(card=catalog_by_name["Guardian Beast"])
    lotus = Permanent(card=catalog_by_name["Black Lotus"])
    merieke = Permanent(card=set_pool("ICE")["Merieke Ri Berit"])
    _nosick(merieke)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[merieke]),
        PlayerState(name="P2", battlefield=[beast, lotus]),
    ])
    game.enforce_mana_costs = False

    assert game.cant_gain_control(lotus, 0)
    assert not game.take_control(lotus, 0, source=merieke)
    assert game.controller_index_of(lotus) == 1
# --- end W1G5 ---


# --- W1G1: prevention and damage shields ---
def _w1g1_combat(game: Game, attackers: list[int], blockers: dict[int, int] | None = None):
    """Seat 0 attacks with *attackers*; seat 1 blocks per *blockers*."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    assert game.declare_attackers(0, attackers)[0]
    game.advance_combat_phase()  # declare_blockers
    assert game.declare_blockers(1, blockers or {})[0]


def test_kjeldoran_royal_guard_takes_the_unblocked_attackers_damage(set_pool):
    """"{T}: All combat damage that would be dealt to you by unblocked creatures
    this turn is dealt to this creature instead." (CR 614.9.)

    Veteran Bodyguard's sentence with a duration on it, so the record is armed
    once and read back when the damage would be dealt. The damage is *moved*,
    not prevented: the Guard is the one that ends up marked.
    """
    pool = set_pool("ICE")
    guard = _nosick(Permanent(card=pool["Kjeldoran Royal Guard"]))
    attacker = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[guard], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.activate_permanent_ability(1, "Kjeldoran Royal Guard", permanent_index=0)
    assert result.supported, result.details
    game._settle()

    _w1g1_combat(game, [0])
    game.advance_combat_phase()  # combat damage

    assert p2.life == 20, "the damage moved onto the Guard, so no life was lost"
    assert guard.damage_marked == 2


def test_kjeldoran_royal_guard_leaves_a_blocked_attacker_where_it_was(set_pool):
    """CR 509.1h: an attacker with a blocker declared for it is a *blocked*
    creature, so the printed noun phrase does not name it. The class is re-asked
    when the damage would be dealt rather than fixed when the ability resolved.
    """
    pool = set_pool("ICE")
    guard = _nosick(Permanent(card=pool["Kjeldoran Royal Guard"]))
    blocker = _nosick(Permanent(card=pool["Balduvian Bears"]))
    attacker = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[guard, blocker], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert game.activate_permanent_ability(
        1, "Kjeldoran Royal Guard", permanent_index=0
    ).supported
    game._settle()

    _w1g1_combat(game, [0], {1: 0})
    game.advance_combat_phase()

    assert guard.damage_marked == 0, "a blocked attacker's damage never reaches the player"
    assert blocker.damage_marked == 2


def test_kjeldoran_royal_guard_does_not_move_noncombat_damage(set_pool):
    """The printed word "combat" is honoured rather than dropped: without it the
    record would catch an unblocked attacker's ping ability too, which is a
    strictly larger card."""
    pool = set_pool("ICE")
    guard = _nosick(Permanent(card=pool["Kjeldoran Royal Guard"]))
    attacker = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[guard], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert game.activate_permanent_ability(
        1, "Kjeldoran Royal Guard", permanent_index=0
    ).supported
    game._settle()
    _w1g1_combat(game, [0])
    game._deal_damage_to_player(p2, 3, source=attacker)

    assert p2.life == 17
    assert guard.damage_marked == 0


def test_mercenaries_shields_the_player_who_paid_for_it(set_pool):
    """"{3}: The next time this creature would deal damage to you this turn,
    prevent that damage. Any player may activate this ability."

    "You" is the *activator* (CR 109.5) — the seat that paid — not the
    creature's controller, which is the whole reason the second sentence is
    printed. CR 615.8's whole-instance shield, so the whole attack is absorbed
    however big it is.
    """
    pool = set_pool("ICE")
    mercs = _nosick(Permanent(card=pool["Mercenaries"]))
    p1 = PlayerState(name="P1", battlefield=[mercs], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    # Seat 1 does not control it; the printed permission is what lets them
    # reach it at all.
    result = game.activate_permanent_ability(
        1, "Mercenaries", permanent_index=0, source_controller_index=0
    )
    assert result.supported, result.details
    game._settle()

    _w1g1_combat(game, [0])
    game.advance_combat_phase()

    assert p2.life == 20, "the shield the defender paid for absorbed the attack"


def test_mercenaries_shields_nobody_else(set_pool):
    """The shield hangs off the seat that activated it, so a third player — or
    the creature's own controller, who never paid — is untouched."""
    pool = set_pool("ICE")
    mercs = _nosick(Permanent(card=pool["Mercenaries"]))
    p1 = PlayerState(name="P1", battlefield=[mercs], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert game.activate_permanent_ability(
        1, "Mercenaries", permanent_index=0, source_controller_index=0
    ).supported
    game._settle()
    game._deal_damage_to_player(p1, 3, source=mercs)

    assert p1.life == 17


def test_mercenaries_only_stops_its_own_damage(set_pool):
    """CR 615.8's shield records the source it waits for, so another creature's
    damage goes through — the printed "this creature" is honoured rather than
    being read as a Circle against every creature."""
    pool = set_pool("ICE")
    mercs = _nosick(Permanent(card=pool["Mercenaries"]))
    other = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[mercs, other], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert game.activate_permanent_ability(
        1, "Mercenaries", permanent_index=0, source_controller_index=0
    ).supported
    game._settle()
    game._deal_damage_to_player(p2, 2, source=other)

    assert p2.life == 18


def test_elvish_healer_shields_one_point_off_a_nongreen_target(set_pool):
    """"{T}: Prevent the next 1 damage that would be dealt to any target this
    turn. If it's a green creature, prevent the next 2 damage instead."

    The printed default, and the size the second sentence is measured against.
    """
    pool = set_pool("ICE")
    healer = _nosick(Permanent(card=pool["Elvish Healer"]))
    white = Permanent(card=pool["Kjeldoran Royal Guard"])
    p1 = PlayerState(name="P1", battlefield=[healer, white], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    result = game.activate_permanent_ability(
        0, "Elvish Healer", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    game._settle()

    assert white.damage_prevention_pool == 1


def test_elvish_healer_gives_a_green_creature_the_larger_shield(set_pool):
    """One shield of one size, chosen when the target is known — never two
    shields, which would prevent three."""
    pool = set_pool("ICE")
    healer = _nosick(Permanent(card=pool["Elvish Healer"]))
    green = Permanent(card=pool["Balduvian Bears"])
    p1 = PlayerState(name="P1", battlefield=[healer, green], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    assert game.activate_permanent_ability(
        0, "Elvish Healer", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    ).supported
    game._settle()

    assert green.damage_prevention_pool == 2

    game._mark_damage_on_permanent(green, 3)
    assert green.damage_marked == 1, "two of the three points were absorbed"


def test_elvish_healer_shields_a_player_at_the_printed_default(set_pool):
    """"Any target" includes a player, and a player is not a green creature —
    so the rider's noun phrase decides rather than being dropped."""
    pool = set_pool("ICE")
    healer = _nosick(Permanent(card=pool["Elvish Healer"]))
    p1 = PlayerState(name="P1", battlefield=[healer], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert game.activate_permanent_ability(
        0, "Elvish Healer", permanent_index=0, target_player_index=1,
    ).supported
    game._settle()

    assert p2.damage_prevention_pool == 1
# --- end W1G1 ---


# --- W1G4: library, hand and graveyard ---
def _ghoul_game(set_pool, above):
    """Ashen Ghoul in a graveyard with *above* cards stacked on top of it."""
    pool = set_pool("ICE")
    graveyard = [pool["Ashen Ghoul"]] + [pool[name] for name in above]
    p1 = PlayerState(name="P1", graveyard=graveyard, life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"
    return pool, p1, game


def test_ashen_ghoul_returns_itself_with_three_creature_cards_above_it(set_pool):
    """"{B}: Return this card from your graveyard to the battlefield. Activate
    only during your upkeep and only if three or more creature cards are above
    this card."

    CR 404.1 makes the graveyard an ordered pile with each arriving card on
    top, so "above" is the cards that got there later.
    """
    pool, p1, game = _ghoul_game(
        set_pool, ["Balduvian Bears", "Brown Ouphe", "Tor Giant"]
    )

    result = game.activate_from_graveyard(0, "Ashen Ghoul")
    assert result.supported, result.details
    game._settle()

    assert [perm.card.name for perm in p1.battlefield] == ["Ashen Ghoul"]
    assert not any(card.name == "Ashen Ghoul" for card in p1.graveyard)


def test_ashen_ghoul_is_refused_with_only_two_creature_cards_above_it(set_pool):
    """A printed restriction is only done when something refuses the
    activation: two is not three, and nothing is spent finding out."""
    pool, p1, game = _ghoul_game(set_pool, ["Balduvian Bears", "Brown Ouphe"])

    result = game.activate_from_graveyard(0, "Ashen Ghoul")

    assert not result.supported
    assert p1.battlefield == []
    assert p1.graveyard[0].name == "Ashen Ghoul"


def test_ashen_ghoul_counts_only_the_cards_above_it(set_pool):
    """Three creature cards in the graveyard is not three creature cards
    *above* this one — the pile's order is the whole restriction."""
    pool = set_pool("ICE")
    p1 = PlayerState(
        name="P1",
        graveyard=[
            pool["Balduvian Bears"],
            pool["Brown Ouphe"],
            pool["Tor Giant"],
            pool["Ashen Ghoul"],
        ],
        life=20,
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"

    result = game.activate_from_graveyard(0, "Ashen Ghoul")

    assert not result.supported
    assert p1.battlefield == []


def test_ashen_ghoul_is_refused_outside_your_upkeep(set_pool):
    """The other conjunct of the same sentence. A clause conjoining two
    restrictions is two restrictions, and both have to hold."""
    pool, p1, game = _ghoul_game(
        set_pool, ["Balduvian Bears", "Brown Ouphe", "Tor Giant"]
    )
    game.current_turn_phase = "precombat_main"
    game.current_step = None

    result = game.activate_from_graveyard(0, "Ashen Ghoul")

    assert not result.supported
    assert p1.battlefield == []
# --- end W1G4 ---


# --- W2G2: mana-production replacements and land-type changes ---
def _w2g2_board(set_pool, creature_name, lands):
    """*creature_name* out of ICE with *lands* beside it, ready to activate.

    Lands are named out of ICE first and LEA second, so "Snow-Covered Forest"
    and "Forest" are both spellable in one list.
    """
    ice, lea = set_pool("ICE"), set_pool("LEA")
    source = Permanent(card=ice[creature_name])
    perms = [Permanent(card=ice.get(name) or lea[name]) for name in lands]
    p1 = PlayerState(name="P1", battlefield=[source, *perms])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _nosick(source)
    return game, p1, source, perms


def _w2g2_aim(game, name, index):
    result = game.activate_permanent_ability(
        0, name, permanent_index=0,
        target_permanent_index=index, target_player_index=0,
    )
    game._settle()
    return result


def test_orcish_farmer_replaces_the_lands_basic_type(set_pool):
    """"Target land becomes a Swamp until its controller's next untap step."

    CR 305.7's *replacement*: the land is a Swamp instead of a Forest, so it
    makes {B} and not {G}. Read through ``basic_land_types`` (layer 4) and then
    proved by tapping it, because a type change nothing produces mana from is
    a type change only the metadata can see.
    """
    game, p1, _farmer, lands = _w2g2_board(set_pool, "Orcish Farmer", ["Forest"])
    forest = lands[0]
    assert forest.basic_land_types == ("forest",)

    assert _w2g2_aim(game, "Orcish Farmer", 1).supported

    assert forest.basic_land_types == ("swamp",)
    p1.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}
    assert game.tap_land_for_mana(0, "Forest", permanent_index=1)
    assert p1.mana_pool["B"] == 1
    assert p1.mana_pool["G"] == 0


def test_orcish_farmer_ends_at_the_lands_controllers_untap_step(set_pool):
    """The window names the **land's** controller, not the Farmer's opponent
    and not the Farmer itself — so an opponent's untap step does not lift it."""
    game, _p1, _farmer, lands = _w2g2_board(set_pool, "Orcish Farmer", ["Forest"])
    assert _w2g2_aim(game, "Orcish Farmer", 1).supported

    game.resolve_untap_step(1)
    assert lands[0].basic_land_types == ("swamp",), "not that player's step"

    game.resolve_untap_step(0)
    assert lands[0].basic_land_types == ("forest",)


def test_orcish_farmer_change_outlives_the_farmer(set_pool):
    """"Until its controller's next untap step" says nothing about the Farmer,
    so the record is keyed on a label rather than on the permanent — a Farmer
    that dies leaves the Swamp behind until the window closes."""
    game, _p1, farmer, lands = _w2g2_board(set_pool, "Orcish Farmer", ["Forest"])
    assert _w2g2_aim(game, "Orcish Farmer", 1).supported
    game.remove_from_battlefield(farmer)

    assert lands[0].basic_land_types == ("swamp",)

    game.resolve_untap_step(0)
    assert lands[0].basic_land_types == ("forest",)


def test_balduvian_conjurer_animates_a_snow_land(set_pool):
    """"Target snow land becomes a 2/2 creature until end of turn. It's still a
    land." (CR 613 layers 4 and 7b.)

    The line parsed already and refused in the *lowering* — "only the source
    animates itself until end of turn" — so the card was unsupported for want
    of a place to put the record, not for want of a reading.
    """
    game, _p1, _conjurer, lands = _w2g2_board(
        set_pool, "Balduvian Conjurer", ["Snow-Covered Forest"]
    )
    land = lands[0]
    assert not land.is_creature

    assert _w2g2_aim(game, "Balduvian Conjurer", 1).supported

    assert land.is_creature
    assert land.has_type("land"), "it's still a land"
    assert (land.effective_power, land.effective_toughness) == (2, 2)


def test_balduvian_conjurer_animation_ends_at_cleanup(set_pool):
    game, _p1, _conjurer, lands = _w2g2_board(
        set_pool, "Balduvian Conjurer", ["Snow-Covered Forest"]
    )
    assert _w2g2_aim(game, "Balduvian Conjurer", 1).supported

    game.resolve_cleanup_step(0)

    assert not lands[0].is_creature
    assert lands[0].has_type("land")


def test_balduvian_conjurer_refuses_a_land_that_is_not_snow(set_pool):
    """The printed noun narrows the target, and the gate that reads it is the
    one the picker reads (CR 602.2b) — so the ability is refused with the
    Conjurer still untapped rather than animating a land it cannot name."""
    game, _p1, conjurer, lands = _w2g2_board(
        set_pool, "Balduvian Conjurer", ["Forest"]
    )

    result = _w2g2_aim(game, "Balduvian Conjurer", 1)

    assert not result.supported
    assert not conjurer.tapped, "nothing was paid"
    assert not lands[0].is_creature
# --- end W2G2 ---


# --- W2G3: combat restrictions and requirements ---
def _w2g3_block_board(set_pool, attacker_name, *defender_lands, blocker="Hipparion"):
    """Seat 0 attacking with *attacker_name*; seat 1 holding *blocker* and lands.

    Returns ``(game, attacker, blocker, lands)``. The declaration is left to the
    test: whether the block is *legal* and whether it is *paid for* are the two
    halves this section is about, and one helper that declared both would hide
    which one failed.
    """
    pool = set_pool("ICE")
    attacker = _nosick(Permanent(card=pool[attacker_name]))
    defender = _nosick(Permanent(card=pool[blocker]))
    lands = [Permanent(card=pool[name]) for name in defender_lands]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker], life=20),
        PlayerState(name="P2", battlefield=[defender, *lands], life=20),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, msg = game.declare_attackers(0, [0], 1)
    assert ok, msg
    game._set_phase_and_step("combat", "declare_blockers")
    return game, attacker, defender, lands


def test_hipparion_compiles_its_block_cost_as_payload(set_pool):
    """"This creature can't block creatures with power 3 or greater unless you
    pay {1}." (CR 509.1b with CR 509.1d's cost.)

    Its own kind rather than a flag on the unconditional row beside it: that
    one forbids the block outright, and a payload key meaning "and there is a
    way out" would make every unread cost an unconditional ban.
    """
    program = compile_card_oracle(set_pool("ICE")["Hipparion"])

    assert program.supported
    (instruction,) = program.instructions
    assert instruction.kind == "cant_block_power_n_or_greater_unless_pay"
    assert instruction.payload["power"] == 3
    assert instruction.payload["mana"] == {"generic": 1}


def test_hipparion_blocks_a_small_creature_for_nothing(set_pool):
    """Below the threshold the restriction says nothing, and no mana moves — a
    cost charged on every block would be the same bug in the other direction."""
    game, _attacker, _hipparion, (land,) = _w2g3_block_board(
        set_pool, "Balduvian Bears", "Snow-Covered Plains"
    )

    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    assert game.combat_blockers[1] == {0: [0]}
    assert not land.tapped


def test_hipparion_cannot_block_a_big_creature_with_no_mana(set_pool):
    """The gate half: a defender who cannot pay cannot make the block, and the
    declaration is refused before anything is committed."""
    game, attacker, _hipparion, _lands = _w2g3_block_board(set_pool, "Tor Giant")
    assert attacker.effective_power >= 3

    ok, msg = game.declare_blockers(1, {0: 0})

    assert not ok
    assert "cannot block" in msg
    assert 1 not in game.combat_blockers


def test_hipparion_pays_to_block_a_big_creature(set_pool):
    """The charge half: with a land to tap the block is legal, and the land is
    actually tapped. A restriction whose cost nobody collects is the failure
    this table exists to prevent."""
    game, _attacker, _hipparion, (land,) = _w2g3_block_board(
        set_pool, "Tor Giant", "Snow-Covered Plains"
    )

    ok, msg = game.declare_blockers(1, {0: 0})

    assert ok, msg
    assert game.combat_blockers[1] == {0: [0]}
    assert land.tapped


def test_hipparion_reads_the_attackers_effective_power(set_pool):
    """"Power 3 or greater" is CR 613 layer 7, not the printed number: a pumped
    2/2 is what the Horse suddenly cannot block for free."""
    game, attacker, _hipparion, _lands = _w2g3_block_board(
        set_pool, "Balduvian Bears"
    )
    assert game.declare_blockers(1, {0: 0})[0]

    game.combat_blockers.clear()
    game.combat_blockers_declared_by.clear()
    game.combat_blockers_locked = False
    game._set_phase_and_step("combat", "declare_blockers")
    add_pt_modifier(attacker, 1, 0)
    assert attacker.effective_power == 3

    ok, msg = game.declare_blockers(1, {0: 0})
    assert not ok
    assert "cannot block" in msg


def test_two_hipparions_each_owe_their_own_block_cost(set_pool):
    """CR 509.1d totals the declaration's costs. One land pays for one blocker;
    the second is what a per-pair gate alone would let through free."""
    pool = set_pool("ICE")
    giants = [_nosick(Permanent(card=pool["Tor Giant"])) for _ in range(2)]
    horses = [_nosick(Permanent(card=pool["Hipparion"])) for _ in range(2)]
    land = Permanent(card=pool["Snow-Covered Plains"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(giants), life=20),
        PlayerState(name="P2", battlefield=[*horses, land], life=20),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], 1)[0]
    game._set_phase_and_step("combat", "declare_blockers")

    ok, msg = game.declare_blockers(1, {0: 0, 1: 1})

    assert not ok
    assert "declare those blockers" in msg
    assert not land.tapped

    # One of them alone is affordable, and the land pays for exactly that one.
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    assert land.tapped


def test_hipparion_is_never_compelled_to_block_by_lure(set_pool):
    """CR 509.1c's last clause: "If a creature can't block unless a player pays
    a cost, that player is not required to pay that cost, even if blocking with
    that creature would increase the number of requirements being obeyed."

    So a Lure on a 3-power attacker does not drag the Horse in, even with the
    mana to pay — while the Bears beside it are still compelled.
    """
    pool = set_pool("ICE")
    giant = _nosick(Permanent(card=pool["Tor Giant"]))
    lure = Permanent(card=pool["Lure"])
    hipparion = _nosick(Permanent(card=pool["Hipparion"]))
    bears = _nosick(Permanent(card=pool["Balduvian Bears"]))
    land = Permanent(card=pool["Snow-Covered Plains"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[giant, lure], life=20),
        PlayerState(name="P2", battlefield=[hipparion, bears, land], life=20),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    attach_aura(lure, giant)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], 1)[0]
    game._set_phase_and_step("combat", "declare_blockers")

    # Leaving both home is illegal: the Bears owe nothing and are compelled.
    ok, msg = game.declare_blockers(1, {})
    assert not ok
    assert "Lure" in msg

    # The Bears alone satisfy it; the Horse stays home and nothing is spent.
    game.combat_blockers.clear()
    game.combat_blockers_declared_by.clear()
    game.combat_blockers_locked = False
    game._set_phase_and_step("combat", "declare_blockers")
    ok, msg = game.declare_blockers(1, {1: 0})

    assert ok, msg
    assert not land.tapped


def _w2g3_wiitigo(set_pool):
    """Wiitigo cast onto seat 0's battlefield, with a bear for seat 1.

    Cast rather than placed: the card is a printed 0/0 and its six +1/+1
    counters arrive as it enters (CR 614.1c), so a Permanent dropped straight
    onto a battlefield dies to CR 704.5f before the entry effect runs.
    """
    pool = set_pool("ICE")
    bears = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", hand=[pool["Wiitigo"]], life=20)
    p2 = PlayerState(name="P2", battlefield=[bears], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    game.cast_from_hand(0, "Wiitigo")
    game._settle()
    wiitigo = p1.battlefield[0]
    _nosick(wiitigo)
    return game, wiitigo, bears


def test_wiitigo_compiles_its_upkeep_choice(set_pool):
    """"At the beginning of your upkeep, put a +1/+1 counter on this creature if
    it has blocked or been blocked since your last upkeep. Otherwise, remove a
    +1/+1 counter from it."

    The whole shape was already there — a trailing "if", an "Otherwise" arm, a
    counter on the source. What was missing was the *condition*: a window that
    spans the opponents' turns, which no per-turn combat record can answer.
    """
    program = compile_card_oracle(set_pool("ICE")["Wiitigo"])

    assert program.supported
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "upkeep_self"
    assert trigger.instruction.kind == "if_then"
    assert trigger.instruction.payload["condition"] == {
        "kind": "in_a_block_since_your_last_upkeep"
    }


def test_wiitigo_shrinks_when_it_has_been_in_no_block(set_pool):
    """The "Otherwise" arm, and both channels of it: the counter comes off the
    record *and* the creature gets smaller. A removal that moved only the record
    left a 6/6 with five counters on it."""
    game, wiitigo, _bears = _w2g3_wiitigo(set_pool)
    assert (wiitigo.effective_power, wiitigo.effective_toughness) == (6, 6)

    game.start_turn(0)
    game._settle()

    assert (wiitigo.effective_power, wiitigo.effective_toughness) == (5, 5)
    assert counters_on(wiitigo, "+1/+1") == 5


def test_wiitigo_grows_after_a_block_on_an_opponents_turn(set_pool):
    """"Since your last upkeep" spans the turns in between, which is the whole
    difficulty: the block happens on the opponent's turn and every per-turn
    combat record of it is swept before the upkeep that reads it."""
    game, wiitigo, _bears = _w2g3_wiitigo(set_pool)
    game.start_turn(0)
    game._settle()
    assert wiitigo.effective_power == 5

    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    assert game.declare_attackers(1, [0], 0)[0]
    game.advance_combat_phase()  # declare_blockers
    assert game.declare_blockers(0, {0: 0})[0]
    game._settle()

    game.start_turn(0)
    game._settle()

    assert (wiitigo.effective_power, wiitigo.effective_toughness) == (6, 6)


def test_wiitigo_stops_growing_the_upkeep_after_that(set_pool):
    """"**Your last** upkeep" is one seat-turn ordinal back, not "ever": the
    same block does not feed it twice."""
    game, wiitigo, _bears = _w2g3_wiitigo(set_pool)
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0], 0)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {0: 0})[0]
    game._settle()

    game.start_turn(0)
    game._settle()
    assert wiitigo.effective_power == 7

    game.start_turn(1)
    game._settle()
    game.start_turn(0)
    game._settle()

    assert wiitigo.effective_power == 6


def _w2g3_sappers(set_pool):
    """Seat 0 with the Sappers and a bear; seat 1 with a bear to block with."""
    pool = set_pool("ICE")
    sappers = _nosick(Permanent(card=pool["Goblin Sappers"]))
    bears = _nosick(Permanent(card=pool["Balduvian Bears"]))
    blocker = _nosick(Permanent(card=pool["Balduvian Bears"]))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[sappers, bears], life=20),
        PlayerState(name="P2", battlefield=[blocker], life=20),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", None)
    return game, sappers, bears


def _w2g3_sappers_combat(game):
    """Attack with the creature in slot 1 and run combat to its end."""
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [1], 1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    refusal = game.declare_blockers(1, {0: 1})
    assert game.declare_blockers(1, {})[0]
    game.end_combat(step_already_started=True)
    game._settle()
    return refusal


def test_goblin_sappers_compiles_both_of_its_abilities(set_pool):
    """Neither ability buys the card on its own: a creature is supported only
    when every line is claimed, and the two lines differ by four words.

    "Destroy **it** and this creature at end of combat" is two delayed abilities
    (CR 603.7), and they are two *different* ones: "it" is the creature the
    step in front chose and "this creature" is the ability's own source, which
    CR 603.7d freezes into the entry. One instruction with a flag could only
    have spelled one of them.
    """
    program = compile_card_oracle(set_pool("ICE")["Goblin Sappers"])

    assert program.supported
    cheap, dear = program.activated_abilities
    assert [step.kind for step in cheap.instruction.payload["steps"]] == [
        "grant_unblockable_to_target",
        "create_delayed_trigger",
        "create_delayed_trigger",
    ]
    inner = [
        step.payload["instruction"].kind
        for step in cheap.instruction.payload["steps"][1:]
    ]
    assert inner == ["destroy_bound_permanent", "destroy_self"]
    assert [step.kind for step in dear.instruction.payload["steps"]] == [
        "grant_unblockable_to_target",
        "create_delayed_trigger",
    ]


def test_goblin_sappers_cheap_ability_takes_its_own_source_with_it(set_pool):
    """{R}{R}: the target is unblockable, and at end of combat both it and the
    Sappers are destroyed."""
    game, sappers, bears = _w2g3_sappers(set_pool)

    result = game.activate_permanent_ability(
        0, "Goblin Sappers", permanent_index=0, ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()
    assert result.supported, result.details
    assert bears.metadata.get("cant_be_blocked_until_eot")

    refusal = _w2g3_sappers_combat(game)

    assert refusal[0] is False
    assert [p.card.name for p in game.controlled_by(0)] == []
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Balduvian Bears", "Goblin Sappers",
    ]


def test_goblin_sappers_expensive_ability_spares_the_sappers(set_pool):
    """{R}{R}{R}{R}: the same sentence with "and this creature" deleted, which
    is the whole difference between the two abilities."""
    game, sappers, bears = _w2g3_sappers(set_pool)

    result = game.activate_permanent_ability(
        0, "Goblin Sappers", permanent_index=0, ability_index=1,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()
    assert result.supported, result.details

    _w2g3_sappers_combat(game)

    assert [p.card.name for p in game.controlled_by(0)] == ["Goblin Sappers"]
    assert [c.name for c in game.players[0].graveyard] == ["Balduvian Bears"]


def test_a_delayed_destroy_of_it_refuses_when_nothing_chose_a_permanent(set_pool):
    """The gate that makes the card correct rather than merely compiling.

    ``parse_recipient`` reads a bare "it" as the ability's own source, so
    without a producer in front of it "Destroy it at end of combat" would arm a
    destruction of the *Sappers* and never touch the creature the card is
    about — compiling, resolving, logging, and doing the wrong thing.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    node = parse_line(
        "{R}: Destroy it at end of combat.", card_name="Probe"
    )
    with pytest.raises(LoweringError):
        lower_ability(node)


def test_and_this_creature_only_joins_a_union_that_ends_the_sentence(set_pool):
    """The refusal test for the widened union.

    "…and this <type>" is a second *object* on Goblin Sappers and the *subject
    of a second clause* on Monsoon, Earthbind and Vexing Arcanix — a permanent
    naming itself is the commonest subject on a card. So the union takes the
    phrase only where nothing follows it but a terminator or the delay.
    """
    from engine.grammar import ast
    from engine.grammar import parse_line

    node = parse_line(
        "Destroy target land and this creature deals 2 damage to you.",
        card_name="Probe",
    )

    # Two clauses, not one destroy with two victims: the land dies and the
    # source deals the damage. Read as a union, this line would have destroyed
    # the permanent printing it and dropped the damage entirely.
    assert isinstance(node.statement, ast.Sequence)
    first, second = node.statement.steps
    assert isinstance(first, ast.Destroy)
    assert first.subject.filter.card_types == ("land",)
    assert isinstance(second, ast.DealDamage)
# --- end W2G3 ---


# --- W2G5: mass effects and X-spells ---
def _w2g5_zombie_board(set_pool, *land_names):
    """Gangrenous Zombies out for seat 0 with those lands, a creature each side.

    Seat 1's Bears is the control: a sweep that damages "each creature" has to
    reach the other side of the board too, and one that only reads its own
    controller's battlefield passes every test built on one seat.
    """
    pool = set_pool("ICE")
    mine = [Permanent(card=pool["Gangrenous Zombies"])]
    mine += [Permanent(card=pool[name]) for name in land_names]
    mine.append(Permanent(card=pool["Balduvian Bears"]))
    theirs = [Permanent(card=pool["Tor Giant"])]
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=mine, life=20),
            PlayerState(name="P2", battlefield=theirs, life=20),
        ]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    for perm in mine + theirs:
        _nosick(perm)
    return game, mine, theirs


def test_w2g5_gangrenous_zombies_deals_one_without_a_snow_swamp(set_pool):
    """"{T}, Sacrifice this creature: This creature deals 1 damage to each
    creature and each player."

    An ordinary Swamp is not a snow Swamp, so the base number stands. Both
    sides of the board and both players — the sweep is symmetric.
    """
    game, mine, theirs = _w2g5_zombie_board(set_pool, "Swamp")

    result = game.activate_permanent_ability(0, "Gangrenous Zombies")
    game._settle()

    assert result.supported, result.details
    assert game.players[0].life == 19
    assert game.players[1].life == 19
    assert mine[-1].damage_marked == 1, "my own Bears is a creature too"
    assert theirs[0].damage_marked == 1


def test_w2g5_gangrenous_zombies_deals_two_with_a_snow_swamp(set_pool):
    """"If you control a snow Swamp, this creature deals 2 damage to each
    creature and each player **instead**."

    Two, not three: "instead" replaces the first sentence rather than adding to
    it, which is the whole content of the word.
    """
    game, mine, theirs = _w2g5_zombie_board(set_pool, "Snow-Covered Swamp")

    result = game.activate_permanent_ability(0, "Gangrenous Zombies")
    game._settle()

    assert result.supported, result.details
    assert game.players[0].life == 18
    assert game.players[1].life == 18
    assert mine[-1].damage_marked == 2
    assert theirs[0].damage_marked == 2


def test_w2g5_gangrenous_zombies_wants_a_swamp_not_any_snow_land(set_pool):
    """A snow Forest is snow and is not a Swamp. The condition names both
    words and both have to hold — dropping either is the sweep that hits
    harder than the card says."""
    game, _mine, _theirs = _w2g5_zombie_board(set_pool, "Snow-Covered Forest")

    game.activate_permanent_ability(0, "Gangrenous Zombies")
    game._settle()

    assert game.players[1].life == 19
# --- end W2G5 ---


# --- W2G4: Auras and attachments ---
def _mount_board(set_pool):
    """Phantasmal Mount and a 2/2 to ride it, both able to act."""
    pool = set_pool("ICE")
    mount = Permanent(card=pool["Phantasmal Mount"])
    rider = Permanent(card=pool["Balduvian Bears"])  # toughness 2, so eligible
    p1 = PlayerState(name="P1", battlefield=[mount, rider], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game._settle()
    _nosick(mount)
    _nosick(rider)
    return game, mount, rider


def _mount_up(game, mount, rider):
    result = game.activate_permanent_ability(
        0, "Phantasmal Mount",
        target_player_index=0,
        permanent_index=game.battlefield_index_of(mount),
        target_permanent_index=game.battlefield_index_of(rider),
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return result


def _settle_triggers(game):
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()


def test_phantasmal_mount_pumps_and_flies_its_rider(set_pool):
    game, mount, rider = _mount_board(set_pool)

    assert _mount_up(game, mount, rider).supported
    assert (rider.effective_power, rider.effective_toughness) == (3, 3)
    assert rider.has_keyword("flying")


def test_the_mount_leaving_sacrifices_the_creature_it_carried(set_pool):
    """"When this creature leaves the battlefield this turn, sacrifice that
    creature." The bound object (CR 603.7c), not a pick — the ability offers
    its controller no choice at all."""
    game, mount, rider = _mount_board(set_pool)
    _mount_up(game, mount, rider)

    game.remove_from_battlefield(mount)
    game._settle()
    _settle_triggers(game)

    assert rider not in list(game.controlled_by(game.players[0]))
    assert "Balduvian Bears" in [card.name for card in game.players[0].graveyard]


def test_the_rider_leaving_sacrifices_the_mount(set_pool):
    """The other half of the linked pair, printed the other way round."""
    game, mount, rider = _mount_board(set_pool)
    _mount_up(game, mount, rider)

    game.remove_from_battlefield(rider)
    game._settle()
    _settle_triggers(game)

    assert mount not in list(game.controlled_by(game.players[0]))


def test_the_mount_carries_nobody_until_its_ability_is_activated(set_pool):
    """Both delays are armed by the activation, so a Mount that never carried
    anything takes nothing with it — and is taken by nothing."""
    game, mount, rider = _mount_board(set_pool)

    game.remove_from_battlefield(rider)
    game._settle()
    _settle_triggers(game)

    assert mount in list(game.controlled_by(game.players[0]))
# --- end W2G4 ---
