"""Core Set 2021 (M21) creatures — the late rounds.

The third creature file, and the second cut along a round boundary. The reason
is the one ``test_m21_creatures_early_rounds.py`` states in full: M21 is 149
creatures, the printed-type axis is spent, and a round section is the unit that
stays whole and stays findable from the ROADMAP entry that bought it. That file
took the rounds that opened the set; this one takes the rounds at the far end,
so the middle file keeps its own history intact rather than being re-cut through
the middle.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (SET_PLAYBOOK.md Phase 3), and the pool resolves through
``set_pool("M21")`` even though the set is not shipped — reading a card file is
not shipping it.
"""

from __future__ import annotations

import dataclasses
import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- Round 88: an ability the payment creates -------------------------------


def _kraken_board(set_pool, *, victim_tapped=False, mana=2):
    pool = set_pool("M21")
    kraken = Permanent(card=pool["Tolarian Kraken"])
    p1 = PlayerState(
        name="P1", battlefield=[kraken],
        library=[pool["Island"], pool["Shock"]],
    )
    victim = Permanent(card=pool["Gale Swooper"], tapped=victim_tapped)
    land = Permanent(card=pool["Mountain"])
    p2 = PlayerState(name="P2", battlefield=[victim, land])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": mana, "generic": 0}
    return game, p1, kraken, victim, land


def _draw_and_pay(game, player, accept=True):
    game._draw_with_replacements(player, 1)
    game._settle()
    game.confirm_optional_pay(0, accept=accept)


def test_tolarian_kraken_compiles_supported(set_pool):
    """"When you do" is CR 603.12's reflexive triggered ability, and it is a
    different field from "if you do" because it is a different *ability*: it
    chooses its own targets when the payment creates it, where an if-you-do
    branch has only the ones this resolution already picked. This trigger fired
    on a card being drawn, which named nothing at all."""
    program = compile_card_oracle(set_pool("M21")["Tolarian Kraken"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "draws_card"
    payload = trigger.instruction.payload
    assert payload["cost"] == {"generic": 1}
    assert "then" not in payload, "the branch is reflexive, not an if-you-do"
    (reflexive,) = payload["reflexive"]
    assert reflexive.kind == "may"


def test_paying_creates_an_ability_that_picks_its_own_target(set_pool):
    game, p1, kraken, victim, _land = _kraken_board(set_pool)

    _draw_and_pay(game, p1)

    (choice,) = game.pending_choices
    assert choice.kind == "reflexive_target"
    # Addressed by stable id, resolved as the ability is created: the prompt
    # outlives the resolution that armed it, and a slot stops naming the same
    # permanent the moment anything ahead of it leaves.
    assert {t["name"] for t in choice.data["targets"]} == {
        "Tolarian Kraken", "Gale Swooper",
    }
    assert all(t["permanent_id"] is not None for t in choice.data["targets"])


def test_the_chosen_creature_is_tapped(set_pool):
    game, p1, _kraken, victim, land = _kraken_board(set_pool)

    _draw_and_pay(game, p1)
    assert game.confirm_reflexive_target(0, game.permanent_id_of(victim))
    game.confirm_optional_pay(0, accept=True)

    assert victim.tapped
    assert not land.tapped
    assert p1.mana_pool["C"] == 1, "the {1} was collected"


def test_a_tapped_creature_is_untapped_instead(set_pool):
    """"Tap **or** untap" — one toggle, and which way it goes is read off the
    creature rather than chosen."""
    game, p1, _kraken, victim, _land = _kraken_board(set_pool, victim_tapped=True)

    _draw_and_pay(game, p1)
    game.confirm_reflexive_target(0, game.permanent_id_of(victim))
    game.confirm_optional_pay(0, accept=True)

    assert not victim.tapped


def test_a_land_is_not_a_legal_target(set_pool):
    """The toggle honours the noun phrase now. It used to honour none at all,
    which is why "tap or untap target creature" had to refuse at lowering —
    lowered onto the unfiltered handler it could have untapped a land."""
    game, p1, _kraken, _victim, land = _kraken_board(set_pool)

    _draw_and_pay(game, p1)

    assert not game.confirm_reflexive_target(0, game.permanent_id_of(land))
    assert game.pending_choices, "the prompt is still owed"


def test_declining_the_payment_creates_no_ability(set_pool):
    """CR 603.12: the reflexive ability triggers on the action being taken. No
    payment, no ability — and no prompt to answer."""
    game, p1, _kraken, victim, _land = _kraken_board(set_pool)

    _draw_and_pay(game, p1, accept=False)

    assert game.pending_choices == []
    assert not victim.tapped
    assert p1.mana_pool["C"] == 2


def test_the_kraken_is_always_a_legal_target_for_its_own_trigger(set_pool):
    """CR 603.7, which 603.12 defers to, would keep the ability off the stack
    with no legal target — and this card can never reach that: the Kraken has to
    be on the battlefield for its own trigger to fire, and it is a creature. So
    the "no legal target" path is real machinery with no reachable case here,
    stated rather than tested through a board that cannot exist.
    """
    game, p1, kraken, _victim, _land = _kraken_board(set_pool)

    _draw_and_pay(game, p1)

    (choice,) = game.pending_choices
    assert game.permanent_id_of(kraken) in {
        target["permanent_id"] for target in choice.data["targets"]
    }


# --- Round 89: one action, two ways to take it ------------------------------


def _lurker_board(set_pool, *, mine=(), hand=()):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=pool[name]) for name in mine],
        hand=[pool["Crypt Lurker"]] + [pool[name] for name in hand],
        library=[pool["Island"], pool["Island"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Crypt Lurker")
    game._settle()
    return game, p1


def _mode_labels(game):
    for choice in game.pending_choices:
        if choice.kind == "mode_choice":
            return list(choice.data["labels"])
    return None


def test_crypt_lurker_compiles_supported(set_pool):
    """"Sacrifice a creature **or** discard a creature card" is one action with
    two ways to take it, so it lowers onto the modal handler a printed
    "Choose one —" already uses: the same question is being asked, and inventing
    a second mechanism would mean two prompts and two defaults.

    The labels are the card's own words, sliced back out of the line."""
    program = compile_card_oracle(set_pool("M21")["Crypt Lurker"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    payload = trigger.instruction.payload
    (choice,) = payload["action"]
    assert choice.kind == "choose_one"
    assert [mode["label"] for mode in choice.payload["modes"]] == [
        "sacrifice a creature", "discard a creature card",
    ]
    assert payload["then"][0].kind == "draw_controller_cards"


def test_both_ways_are_offered_when_both_are_open(set_pool):
    game, _p1 = _lurker_board(
        set_pool, mine=["Gale Swooper"], hand=["Alpine Watchdog", "Shock"]
    )

    game.confirm_optional_pay(0, accept=True)

    assert _mode_labels(game) == ["sacrifice a creature", "discard a creature card"]


def test_a_way_the_player_cannot_take_is_not_offered(set_pool):
    """With no creature card in hand the discard is not something the player
    *could* do, and a mode offered but not performable is one they can pick and
    then not get. (The Lurker itself is a creature, so the sacrifice is always
    open — which is why the reverse case cannot be built.)"""
    game, _p1 = _lurker_board(set_pool, hand=["Shock"])

    game.confirm_optional_pay(0, accept=True)

    assert _mode_labels(game) == ["sacrifice a creature"]


def test_the_discard_takes_a_creature_card_and_draws(set_pool):
    game, p1 = _lurker_board(set_pool, hand=["Alpine Watchdog", "Shock"])

    game.confirm_optional_pay(0, accept=True)
    game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    (prompt,) = game.pending_choices
    assert prompt.kind == "discard"
    # Narrowed to the cards the phrase names — the Shock is in hand and is not
    # one of them.
    assert game.live_discard_candidates(prompt) == [0]
    assert game.confirm_discard(0, [0])

    assert [c.name for c in p1.graveyard] == ["Alpine Watchdog"]
    assert [c.name for c in p1.hand] == ["Shock", "Island"], "the draw happened"


def test_a_card_the_phrase_does_not_name_cannot_pay_the_discard(set_pool):
    """Refused rather than slid onto a card that would do — a stale click must
    not throw away the card the player meant to keep."""
    game, p1 = _lurker_board(set_pool, hand=["Alpine Watchdog", "Shock"])

    game.confirm_optional_pay(0, accept=True)
    game.resolve_pending_choice("mode_choice", 0, mode_index=1)

    assert not game.confirm_discard(0, [1])
    assert [c.name for c in p1.graveyard] == []
    assert game.pending_choices, "the prompt is still owed"


def test_the_sacrifice_takes_a_creature_and_draws(set_pool):
    game, p1 = _lurker_board(set_pool, mine=["Gale Swooper"], hand=["Shock"])

    game.confirm_optional_pay(0, accept=True)
    game.resolve_pending_choice("mode_choice", 0, mode_index=0)
    assert game.resolve_pending_choice("sacrifice", 0, indices=[0])

    assert [p.card.name for p in game.controlled_by(0)] == ["Crypt Lurker"]
    assert [c.name for c in p1.graveyard] == ["Gale Swooper"]
    assert [c.name for c in p1.hand] == ["Shock", "Island"]


def test_declining_gives_up_nothing_and_draws_nothing(set_pool):
    """"If you do" — the draw is the consequence of taking the action, so
    declining is not a free card."""
    game, p1 = _lurker_board(
        set_pool, mine=["Gale Swooper"], hand=["Alpine Watchdog"]
    )

    game.confirm_optional_pay(0, accept=False)

    assert game.pending_choices == []
    assert [c.name for c in p1.hand] == ["Alpine Watchdog"]
    assert p1.graveyard == []
    assert [p.card.name for p in game.controlled_by(0)] == ["Gale Swooper", "Crypt Lurker"]


# --- Round 90: a blocking requirement, and a tally of the dead --------------


def _stalker_combat(set_pool, defenders=()):
    pool = set_pool("M21")
    stalker = _nosick(Permanent(card=pool["Canopy Stalker"]))
    p1 = PlayerState(name="P1", battlefield=[stalker])
    p2 = PlayerState(
        name="P2",
        battlefield=[_nosick(Permanent(card=pool[name])) for name in defenders],
    )
    game = Game(players=[p1, p2])
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.declare_attackers(0, [0])
    game.current_step = "declare_blockers"
    return game, p2


def test_canopy_stalker_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Canopy Stalker"])
    assert program.supported, program.reason

    kinds = {i.kind for i in program.instructions}
    assert "must_be_blocked" in kinds


def test_an_able_defender_must_block_it(set_pool):
    """CR 509.1c, a blocking *requirement*. The declaration is refused rather
    than corrected, because which creature blocks is still the defender's
    choice — the card only takes away "none of them"."""
    game, _p2 = _stalker_combat(set_pool, ["Gale Swooper"])

    legal, detail = game.declare_blockers(1, {})

    assert not legal
    assert "must be blocked" in detail


def test_blocking_it_with_one_creature_is_enough(set_pool):
    """Weaker than Lure, which demands *every* able creature. Folding the two
    together would forbid the defender keeping a second blocker back, which this
    card does not do."""
    game, _p2 = _stalker_combat(set_pool, ["Gale Swooper", "Alpine Watchdog"])

    legal, detail = game.declare_blockers(1, {0: [0]})

    assert legal, detail


def test_a_defender_with_nothing_able_may_decline(set_pool):
    """"If able" is read, not decoration."""
    game, _p2 = _stalker_combat(set_pool)

    legal, detail = game.declare_blockers(1, {})

    assert legal, detail


def test_a_tapped_creature_is_not_able(set_pool):
    game, p2 = _stalker_combat(set_pool, ["Gale Swooper"])
    next(iter(game.controlled_by(1))).tapped = True

    legal, detail = game.declare_blockers(1, {})

    assert legal, detail


def _stalker_dies_with(set_pool, friends=0, opponents=0):
    pool = set_pool("M21")
    stalker = Permanent(card=pool["Canopy Stalker"])
    p1 = PlayerState(
        name="P1",
        battlefield=[stalker] + [Permanent(card=pool["Gale Swooper"]) for _ in range(friends)],
        life=20,
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=pool["Gale Swooper"]) for _ in range(opponents)],
    )
    game = Game(players=[p1, p2])
    for perm in list(game.all_permanents()):
        perm.damage_marked = 99
    game.check_state_based_actions()
    game._settle()
    return game, p1


def test_the_life_gain_counts_every_creature_that_died(set_pool):
    """A *tally*, not a scan: the creatures counted are exactly the ones no
    battlefield still holds, so the count comes off the game's own record. The
    Stalker counts itself — it died too."""
    game, p1 = _stalker_dies_with(set_pool)

    assert game.creatures_died_this_turn == 1
    assert p1.life == 21


def test_the_tally_is_game_wide_and_not_per_seat(set_pool):
    """"Each creature", not "each creature you control". The per-seat tally
    beside it (``creatures_died_under_your_control_this_turn``) is a different
    number the moment an opponent's creature dies, and reading one for the other
    is the whole reason the two are separate fields."""
    game, p1 = _stalker_dies_with(set_pool, friends=1, opponents=2)

    assert game.creatures_died_this_turn == 4
    assert p1.creatures_died_under_your_control_this_turn == 2
    assert p1.life == 24


def test_the_history_clause_is_not_read_as_a_board_count(set_pool):
    """"For each creature that died this turn" names the opposite set from "for
    each creature you control". The noun parser consumes "creature" and stops,
    so before the history clause was read first the trailing words were
    unconsumed and the line failed — loudly, which was right. The ordering is
    what makes it parse *and* mean the tally."""
    from engine.grammar import compile_line

    (instruction,) = compile_line(
        "You gain 1 life for each creature that died this turn."
    ).instructions
    assert instruction.payload["per_each"] == {"history": "creatures_died_this_turn"}

    (board,) = compile_line(
        "You gain 1 life for each creature you control with flying."
    ).instructions
    assert board.payload["per_each"]["zone"] == "battlefield"

    # A narrowing the tally cannot express refuses rather than counting a wider
    # set: the record is one number, not a filterable pile.
    refused = compile_line("You gain 1 life for each artifact that died this turn.")
    assert refused.parsed and not refused.lowered


# --- Round 91: mana that may only pay for some spells -----------------------


def _arcanist_board(set_pool, hand=(), opposing=()):
    pool = set_pool("M21")
    arcanist = _nosick(Permanent(card=pool["Vodalian Arcanist"]))
    p1 = PlayerState(
        name="P1", battlefield=[arcanist], hand=[pool[name] for name in hand]
    )
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=pool[name]) for name in opposing]
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    return game, p1


def test_vodalian_arcanist_compiles_supported(set_pool):
    """"Spend this mana only to…" is a rider on the mana it restricts, not a
    step of its own: parsed as a sentence it would be an effect nothing
    performs, and the mana would land in the unrestricted pool with the
    restriction reported as understood."""
    program = compile_card_oracle(set_pool("M21")["Vodalian Arcanist"])
    assert program.supported, program.reason

    (ability,) = program.activated_abilities
    assert ability.instruction.payload["spend_only"] == "instant_or_sorcery"


def test_the_mana_does_not_reach_the_ordinary_pool(set_pool):
    game, p1 = _arcanist_board(set_pool)

    assert game.activate_permanent_ability(0, "Vodalian Arcanist", permanent_index=0).supported

    assert p1.mana_pool["C"] == 0
    assert p1.restricted_mana["instant_or_sorcery"] == {"C": 1}


def test_an_instant_may_be_paid_for_with_it(set_pool):
    game, p1 = _arcanist_board(
        set_pool, hand=["Scorching Dragonfire"], opposing=["Gale Swooper"]
    )
    game.activate_permanent_ability(0, "Vodalian Arcanist", permanent_index=0)
    p1.mana_pool["R"] = 1

    result = game.cast_from_hand(
        0, "Scorching Dragonfire", target_player_index=1, target_permanent_index=0
    )

    assert result.supported, result.details
    assert p1.restricted_mana["instant_or_sorcery"]["C"] == 0, "the generic pip came from the bucket"


def test_a_creature_spell_cannot_touch_it(set_pool):
    """The restriction is what the whole line is for. Chandra's Magmutt costs the
    same {1}{R} the instant above did and cannot be cast."""
    game, p1 = _arcanist_board(set_pool, hand=["Chandra's Magmutt"])
    game.activate_permanent_ability(0, "Vodalian Arcanist", permanent_index=0)
    p1.mana_pool["R"] = 1

    result = game.cast_from_hand(0, "Chandra's Magmutt")

    assert not result.supported
    assert p1.restricted_mana["instant_or_sorcery"]["C"] == 1, "nothing was spent"


def test_an_activated_ability_is_not_a_spell(set_pool):
    """"Only to **cast**" — an activated ability is not cast at all (CR 602.2),
    so no bucket admits one. The payer is handed None for the spell and None
    admits nothing, which is that rule rather than a missing argument."""
    from engine.restricted_mana import restriction_admits

    game, p1 = _arcanist_board(set_pool)
    game.activate_permanent_ability(0, "Vodalian Arcanist", permanent_index=0)

    from engine.mixins.stack.casting import _spendable_restricted_mana

    assert _spendable_restricted_mana(p1, None) == {}
    assert not restriction_admits("instant_or_sorcery", set_pool("M21")["Alpine Watchdog"])


def test_a_restriction_key_with_no_predicate_admits_nothing(set_pool):
    """The safe direction. A key the engine cannot test is mana whose
    restriction it cannot enforce, and treating it as unrestricted would spend
    it on anything."""
    from engine.restricted_mana import restriction_admits

    assert not restriction_admits("dragon", set_pool("M21")["Alpine Watchdog"])


def test_the_old_field_name_is_a_view_over_the_collection(set_pool):
    """``creature_only_mana`` was the whole feature and is now one bucket. It
    survives as a view because the web payload, the AI simulator and the
    existing tests read it — the same arrangement ``engine/shields.py`` made for
    the prevention fields, and for the same reason."""
    _game, p1 = _arcanist_board(set_pool)

    p1.creature_only_mana["G"] = 2

    assert p1.restricted_mana["creature"] == {"G": 2}


# --- Round 92: a trigger that fires when something points at you ------------


def _warden_board(set_pool, caster_seat, spell, opposing=()):
    pool = set_pool("M21")
    warden = _nosick(Permanent(card=pool["Warden of the Woods"]))
    p1 = PlayerState(name="P1", battlefield=[warden], library=[pool["Island"]] * 5)
    p2 = PlayerState(
        name="P2",
        library=[pool["Island"]] * 5,
        battlefield=[Permanent(card=pool[name]) for name in opposing],
    )
    (p1 if caster_seat == 0 else p2).hand = [pool[spell]]
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    return game, p1, p2, warden


def test_warden_of_the_woods_compiles_supported(set_pool):
    """Whose spell it must be is *data* on one condition, not a kind — the
    unnarrowed wording and "you control" are the same dispatcher asked a
    different question."""
    program = compile_card_oracle(set_pool("M21")["Warden of the Woods"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "self_becomes_target"
    assert trigger.condition.payload["targeting_controller"] == "an opponent controls"


def test_an_opponents_spell_fires_it(set_pool):
    """CR 601.2c chooses targets as the spell is cast, which is the moment it
    goes on the stack — so that is where the announcement is, and the Warden
    draws whether or not the Shock ever resolves."""
    game, p1, _p2, _warden = _warden_board(set_pool, 1, "Shock")

    game.cast_from_hand(1, "Shock", target_player_index=0, target_permanent_index=0)

    (choice,) = game.pending_choices
    assert choice.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    assert len(p1.hand) == 2


def test_its_own_controllers_spell_does_not(set_pool):
    """"An opponent controls" is read, not decoration."""
    game, p1, _p2, _warden = _warden_board(set_pool, 0, "Shock")

    game.cast_from_hand(0, "Shock", target_player_index=0, target_permanent_index=0)

    assert game.pending_choices == []
    assert p1.hand == []


def test_a_spell_aimed_elsewhere_does_not(set_pool):
    """"**This** creature" — the subject is compared by identity, because a
    look-alike on the same battlefield is a different permanent."""
    game, _p1, _p2, _warden = _warden_board(
        set_pool, 1, "Shock", opposing=["Gale Swooper"]
    )

    game.cast_from_hand(1, "Shock", target_player_index=1, target_permanent_index=0)

    assert game.pending_choices == []


# --- Round 93: a token printed by name, and a threshold on your own board ---


def _gadrak_board(set_pool, artifacts=0):
    pool = set_pool("M21")
    gadrak = _nosick(Permanent(card=pool["Gadrak, the Crown-Scourge"]))
    p1 = PlayerState(
        name="P1",
        battlefield=[gadrak] + [
            Permanent(card=pool["Tormod's Crypt"]) for _ in range(artifacts)
        ],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    return game, p1, gadrak


def test_gadrak_compiles_supported(set_pool):
    """The subject of its own static line is its **name**, which is how Magic
    templates a legendary card. The restriction table is anchored on "this
    creature", so the name is collapsed to that before the table is asked — the
    rule the lexer already applies for the grammar, on the static-line path."""
    program = compile_card_oracle(set_pool("M21")["Gadrak, the Crown-Scourge"])
    assert program.supported, program.reason

    restriction = next(
        i for i in program.instructions
        if i.kind == "cant_attack_without_controlled_count"
    )
    # The number and the type are data: a card printed with any other pair is
    # the same restriction, and the printed word is read rather than compared.
    assert restriction.payload == {"count": 4, "controlled_type": "artifact"}


@pytest.mark.parametrize("artifacts,allowed", [(0, False), (3, False), (4, True)])
def test_the_threshold_is_counted_on_your_own_board(set_pool, artifacts, allowed):
    """"Unless **you** control" — the attacker's own controller, which is the
    difference from the land clause beside it (that one counts the defender's)."""
    game, _p1, gadrak = _gadrak_board(set_pool, artifacts)

    assert game.can_attack(gadrak, 1) is allowed


def _gadrak_end_step(set_pool, nontoken_deaths=0, token_deaths=0):
    from engine.tokens import make_token_card

    pool = set_pool("M21")
    gadrak = Permanent(card=pool["Gadrak, the Crown-Scourge"])
    doomed = [Permanent(card=pool["Gale Swooper"]) for _ in range(nontoken_deaths)]
    doomed += [
        Permanent(
            card=make_token_card("Bear", 2, 2, "Creature — Bear"),
            metadata={"is_token": True},
        )
        for _ in range(token_deaths)
    ]
    p1 = PlayerState(name="P1", battlefield=[gadrak] + doomed)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.active_player_index = 0
    for perm in doomed:
        perm.damage_marked = 99
    game.check_state_based_actions()
    game._settle()
    game.resolve_end_step(0)
    game._settle()
    return game, p1


def _treasures(game):
    return [p for p in game.controlled_by(0) if p.card.name == "Treasure Token"]


def test_a_treasure_is_made_for_each_nontoken_creature_that_died(set_pool):
    game, _p1 = _gadrak_end_step(set_pool, nontoken_deaths=2)

    assert len(_treasures(game)) == 2


def test_a_token_that_died_is_not_counted(set_pool):
    """"**Nontoken**" is read, not decoration — a token dying is a real
    creature death, so the two tallies are different numbers and the engine
    keeps them apart rather than filtering one into the other."""
    game, _p1 = _gadrak_end_step(set_pool, nontoken_deaths=2, token_deaths=3)

    assert game.creatures_died_this_turn == 5
    assert game.nontoken_creatures_died_this_turn == 2
    assert len(_treasures(game)) == 2


def test_nothing_died_makes_nothing(set_pool):
    game, _p1 = _gadrak_end_step(set_pool)

    assert _treasures(game) == []


def test_the_treasure_is_a_noncreature_token_that_makes_mana(set_pool):
    """A token Magic prints by name alone (CR 111.10): its characteristics
    belong to the token, so they live in one table rather than being
    transcribed onto every card that makes one. It has no P/T at all — CR 208.1
    gives P/T to creatures, and 0/0 would be a creature card that dies the
    moment anything animates it."""
    game, p1 = _gadrak_end_step(set_pool, nontoken_deaths=1)

    (treasure,) = _treasures(game)
    assert treasure.card.type_line == "Artifact — Treasure"
    assert not treasure.is_creature
    assert treasure.card.power is None and treasure.card.toughness is None

    result = game.activate_permanent_ability(
        0, "Treasure Token",
        permanent_index=game.battlefield_index_of(treasure),
        mana_color="R",
    )
    assert result.supported, result.details
    assert p1.mana_pool["R"] == 1
    assert not game.is_on_battlefield(treasure), "sacrificed to pay its own cost"


# --- Round 94: half a CDA, and a count that is the answer to a prompt -------


def _augur_board(set_pool, graveyard=()):
    pool = set_pool("M21")
    augur = Permanent(card=pool["Kinetic Augur"])
    p1 = PlayerState(
        name="P1", battlefield=[augur],
        graveyard=[pool[name] for name in graveyard],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game._settle()
    return game, p1, augur


def test_kinetic_augur_compiles_supported(set_pool):
    """"**Power** is equal to", not "power and toughness are each" — the one
    printed CDA that defines half of a P/T, so which half it defines rides on
    the payload rather than in the kind. The count is over *cards in a zone*, so
    it goes through the shared evaluator: a card in a graveyard has no computed
    characteristics at all (CR 613.1)."""
    program = compile_card_oracle(set_pool("M21")["Kinetic Augur"])
    assert program.supported, program.reason

    cda = next(i for i in program.instructions if i.kind == "dynamic_pt_count")
    assert cda.payload["defines"] == "power"
    assert cda.payload["count_spec"]["zone"] == "graveyard"


@pytest.mark.parametrize(
    "graveyard,power",
    [
        ((), 0),
        (("Shock",), 1),
        (("Shock", "Scorching Dragonfire"), 2),
        # A creature card in the graveyard is not counted; a CDA is recomputed
        # continuously (CR 604.3), so this is the same read at a different board.
        (("Shock", "Scorching Dragonfire", "Gale Swooper"), 2),
    ],
)
def test_the_power_tracks_the_graveyard(set_pool, graveyard, power):
    _game, _p1, augur = _augur_board(set_pool, graveyard)

    assert augur.effective_power == power


def test_the_printed_toughness_is_left_alone(set_pool):
    """Kinetic Augur is */4. ``set_base_pt`` takes None for "leave this one
    tracking whatever else applies", which is exactly the difference between
    defining one characteristic and defining both."""
    _game, _p1, augur = _augur_board(set_pool, ("Shock",))

    assert augur.effective_toughness == 4


def _augur_enters(set_pool, hand=()):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Kinetic Augur"]] + [pool[name] for name in hand],
        library=[pool["Island"]] * 5,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Kinetic Augur")
    game._settle()
    return game, p1


def test_the_entry_trigger_arms_one_prompt_that_knows_what_follows(set_pool):
    """One instruction, because the second number *is* the answer to the first.
    Decomposed, the draw would run while the discard prompt was still owed and
    draw nothing at all — with the card reporting supported."""
    game, _p1 = _augur_enters(set_pool, ["Shock", "Island"])

    (choice,) = game.pending_choices
    assert choice.kind == "discard"
    assert choice.data["count"] == 2
    assert choice.data["up_to"] and choice.data["draw_that_many"]


def test_discarding_fewer_draws_fewer(set_pool):
    game, p1 = _augur_enters(set_pool, ["Shock", "Island"])

    assert game.confirm_discard(0, [0])

    assert [c.name for c in p1.graveyard] == ["Shock"]
    assert len(p1.hand) == 2, "one discarded, one drawn"


def test_discarding_nothing_is_a_legal_answer_and_draws_nothing(set_pool):
    """"Up to" — a ceiling read as an exact count would force the player to
    pitch cards they were offered the choice of keeping."""
    game, p1 = _augur_enters(set_pool, ["Shock", "Island"])

    assert game.confirm_discard(0, [])

    assert p1.graveyard == []
    assert [c.name for c in p1.hand] == ["Shock", "Island"]
    assert game.pending_choices == []


def test_an_exact_discard_still_demands_its_whole_count(set_pool):
    """The "up to" flag is what makes fewer legal, so a prompt without it is
    unchanged — a plain "discard two cards" is not a choice about how many."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Shock"], pool["Island"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.arm_pending_choice("discard", 0, count=2)

    assert not game.confirm_discard(0, [0])
    assert game.pending_choices, "still owed"


# --- Round 101: mana by a board count, and damage equal to your own power ---


def _leafkin_board(set_pool, friends=()):
    pool = set_pool("M21")
    leafkin = _nosick(Permanent(card=pool["Leafkin Avenger"]))
    p1 = PlayerState(
        name="P1",
        battlefield=[leafkin] + [_nosick(Permanent(card=pool[n])) for n in friends],
    )
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, leafkin


def test_leafkin_avenger_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Leafkin Avenger"])
    assert program.supported, program.reason


@pytest.mark.parametrize(
    "friends,green",
    [
        ((), 1),                          # Leafkin is 4/3 and counts itself
        (("Gale Swooper",), 1),           # a 3/2 is not power 4 or greater
        (("Warden of the Woods",), 2),    # a 5/7 is
    ],
)
def test_the_mana_is_multiplied_by_the_board(set_pool, friends, green):
    """"For each" multiplies the whole clause, so the count applies to every pip
    rather than to one — and it is taken at resolution through the evaluator
    every computed amount shares."""
    game, p1, _p2, _leafkin = _leafkin_board(set_pool, friends)

    game.activate_permanent_ability(
        0, "Leafkin Avenger", permanent_index=0, ability_index=0
    )
    game._settle()

    assert p1.mana_pool["G"] == green


def test_the_multiplier_counts_only_your_own_board(set_pool):
    """"You control" is performed by the count's owner, which scans one seat's
    battlefield — carried rather than tested, which is what
    ``carried_separately`` is for."""
    pool = set_pool("M21")
    game, p1, p2, _leafkin = _leafkin_board(set_pool)
    p2.battlefield = [Permanent(card=pool["Warden of the Woods"])]

    game.activate_permanent_ability(
        0, "Leafkin Avenger", permanent_index=0, ability_index=0
    )
    game._settle()

    assert p1.mana_pool["G"] == 1


def test_it_deals_damage_equal_to_its_own_power_to_a_player(set_pool):
    """The recipient is not an object, so the bites handler — which resolves a
    permanent — cannot carry it. What is new is only where the *number* comes
    from, which is one payload key rather than a kind."""
    game, _p1, p2, _leafkin = _leafkin_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Leafkin Avenger", permanent_index=0, ability_index=1,
        target_player_index=1,
    )
    assert result.supported, result.details
    game._settle()

    assert p2.life == 16


def test_the_power_is_read_at_resolution_not_printed(set_pool):
    """Off the ``Permanent``, so it is the computed power (CR 613) and a pump
    counts."""
    from engine.pt import add_pt_modifier

    game, _p1, p2, leafkin = _leafkin_board(set_pool)
    add_pt_modifier(leafkin, 2, 0)

    game.activate_permanent_ability(
        0, "Leafkin Avenger", permanent_index=0, ability_index=1,
        target_player_index=1,
    )
    game._settle()

    assert p2.life == 14


def test_the_planeswalker_half_of_the_union_is_read(set_pool):
    """"Target player **or planeswalker**" — this word order (the amount before
    the recipient) went through a reader that did not know the union, so the two
    words were unconsumed and the whole line failed."""
    from engine.grammar import compile_line

    (instruction,) = compile_line(
        "This creature deals damage equal to its power to target player or planeswalker.",
        card_name="Leafkin Avenger",
    ).instructions

    assert instruction.payload["targets"]["kind"] == "player_or_planeswalker"


# --- Round 102: blocking only one thing, and a cost paid by tapping ---------


def _geist_board(set_pool, spirits=2):
    pool = set_pool("M21")
    geists = [_nosick(Permanent(card=pool["Shacklegeist"])) for _ in range(spirits)]
    victim = _nosick(Permanent(card=pool["Gale Swooper"]))
    p1 = PlayerState(name="P1", battlefield=geists)
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, geists, victim


def test_shacklegeist_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Shacklegeist"])
    assert program.supported, program.reason

    (ability,) = program.activated_abilities
    assert ability.cost.tap_count == 2
    # "Tap two **untapped** Spirits you control": the word had no payload key
    # until round 112, so it reduced to "Spirits you control" — harmless for a
    # tap cost, which can only be paid by untapped permanents anyway, and a
    # dropped restriction everywhere else.
    assert ability.cost.tap_filter == {
        "type_filter": "creature", "subtype_filter": "spirit", "untapped_only": True,
    }


@pytest.mark.parametrize(
    "attacker,blockable", [("Gale Swooper", True), ("Alpine Watchdog", False)]
)
def test_it_can_block_only_fliers(set_pool, attacker, blockable):
    """The mirror of "can't be blocked by …": that names what may not block,
    this names the only thing that may — so an attacker *without* the word is
    what fails. Asked of layer 6, so a granted flying counts."""
    pool = set_pool("M21")
    geist = _nosick(Permanent(card=pool["Shacklegeist"]))
    att = _nosick(Permanent(card=pool[attacker]))
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[att]),
            PlayerState(name="P2", battlefield=[geist]),
        ]
    )

    assert game._can_block_attacker(geist, att) is blockable


def test_tapping_two_spirits_pays_for_the_tap(set_pool):
    game, geists, victim = _geist_board(set_pool, spirits=2)

    result = game.activate_permanent_ability(
        0, "Shacklegeist", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game._settle()

    assert victim.tapped
    assert all(g.tapped for g in geists), "both Spirits paid the cost"


def test_one_spirit_cannot_pay_a_two_spirit_cost(set_pool):
    """CR 602.5c: an unpayable cost is an unactivatable ability, not a free
    one."""
    game, geists, victim = _geist_board(set_pool, spirits=1)

    result = game.activate_permanent_ability(
        0, "Shacklegeist", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )

    assert not result.supported
    assert not victim.tapped
    assert not geists[0].tapped, "nothing was spent"


def test_an_already_tapped_spirit_is_not_a_legal_payment(set_pool):
    """"**Untapped** Spirits" is carried rather than tested, and for a reason
    stronger than a filter key: a cost that taps a permanent can only ever be
    paid with one that is not already tapped."""
    game, geists, _victim = _geist_board(set_pool, spirits=2)
    geists[1].tapped = True

    result = game.activate_permanent_ability(
        0, "Shacklegeist", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )

    assert not result.supported


def test_the_payer_may_name_which_spirits_tap(set_pool):
    """By id, because the list is chosen before anything taps and a slot
    renumbers as soon as one does."""
    game, geists, victim = _geist_board(set_pool, spirits=3)
    chosen = [game.permanent_id_of(geists[1]), game.permanent_id_of(geists[2])]

    result = game.activate_permanent_ability(
        0, "Shacklegeist", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
        cost_permanent_ids=chosen,
    )
    assert result.supported, result.details

    assert not geists[0].tapped
    assert geists[1].tapped and geists[2].tapped


# --- Round 103: a trigger that includes its own source, and a zone threshold -


def _enforcer_board(set_pool, opponent_graveyard=0, hand=()):
    pool = set_pool("M21")
    enforcer = _nosick(Permanent(card=pool["Thieves' Guild Enforcer"]))
    p1 = PlayerState(
        name="P1", battlefield=[enforcer],
        hand=[pool[name] for name in hand],
        library=[pool["Island"]] * 5,
    )
    p2 = PlayerState(
        name="P2",
        graveyard=[pool["Shock"]] * opponent_graveyard,
        library=[pool["Island"]] * 10,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._settle()
    return game, p1, p2, enforcer


def test_thieves_guild_enforcer_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Thieves' Guild Enforcer"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "matching_permanent_enters"
    # "This creature or another Rogue" *includes* the source, so the exclusion
    # the noun parser folds on for "another" has to be undone.
    assert "exclude_self" not in trigger.condition.payload["enterer_filter"]


def test_its_own_entry_fires_it(set_pool):
    """The spelling exists to say so: the bare "another Rogue you control"
    reading would have excluded the source."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", hand=[pool["Thieves' Guild Enforcer"]], library=[pool["Island"]] * 5
    )
    p2 = PlayerState(name="P2", library=[pool["Island"]] * 10)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Thieves' Guild Enforcer")
    game._settle()

    assert len(p2.graveyard) == 2


def test_a_second_rogue_fires_both(set_pool):
    """Two abilities see one entry: the newcomer's own, and the one already
    there watching for another Rogue."""
    game, _p1, p2, _enforcer = _enforcer_board(
        set_pool, hand=("Thieves' Guild Enforcer",)
    )

    game.cast_from_hand(0, "Thieves' Guild Enforcer")
    game._settle()

    assert len(p2.graveyard) == 4


def test_a_creature_that_is_not_a_rogue_fires_nothing(set_pool):
    game, _p1, p2, _enforcer = _enforcer_board(set_pool, hand=("Gale Swooper",))

    game.cast_from_hand(0, "Gale Swooper")
    game._settle()

    assert p2.graveyard == []


@pytest.mark.parametrize(
    "graveyard,stats,deathtouch",
    [(0, (1, 1), False), (7, (1, 1), False), (8, (3, 2), True)],
)
def test_the_static_reads_the_opponents_graveyard(
    set_pool, graveyard, stats, deathtouch
):
    """A zone *size*, not a set of objects — nothing is matched, so it is its own
    condition kind rather than a `controls` payload with a graveyard filter."""
    game, _p1, _p2, enforcer = _enforcer_board(set_pool, opponent_graveyard=graveyard)

    assert (enforcer.effective_power, enforcer.effective_toughness) == stats
    assert game._has_keyword(enforcer, "deathtouch") is deathtouch


def test_an_unreadable_threshold_refuses_the_condition(set_pool):
    """The number word is read, not compared. A threshold that quietly became
    zero is a static that always holds."""
    from engine.static_bonuses import static_bonus_for

    assert static_bonus_for(
        "as long as an opponent has eight or more cards in their graveyard, "
        "this creature gets +2/+1 and has deathtouch"
    ) is not None
    assert static_bonus_for(
        "as long as an opponent has umpteen or more cards in their graveyard, "
        "this creature gets +2/+1 and has deathtouch"
    ) is None


# --- Round 104: an exile that lasts as long as its source does --------------


def _freebooter_board(set_pool, victim_hand=("Shock", "Gale Swooper", "Island")):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Kitesail Freebooter"]])
    p2 = PlayerState(name="P2", hand=[pool[name] for name in victim_hand])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Kitesail Freebooter", target_player_index=1)
    game._settle()
    return game, p1, p2


def test_kitesail_freebooter_compiles_supported(set_pool):
    """The reveal-and-choose node has carried a ``fate`` since it was written,
    with a docstring naming this card as the one that would need the exile
    ending. This is that card."""
    program = compile_card_oracle(set_pool("M21")["Kitesail Freebooter"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.instruction.payload["fate"] == "exile_until_source_leaves"


def test_only_a_noncreature_nonland_card_may_be_chosen(set_pool):
    game, _p1, p2 = _freebooter_board(set_pool)

    (choice,) = game.pending_choices
    assert choice.data["legal_indices"] == [0], "the Shock, not the creature or the land"
    assert [p2.hand[i].name for i in choice.data["legal_indices"]] == ["Shock"]


def test_the_chosen_card_is_exiled_not_discarded(set_pool):
    game, _p1, p2 = _freebooter_board(set_pool)

    assert game.confirm_revealed_hand_pick(0, 0)

    assert [c.name for c in p2.exile] == ["Shock"]
    assert p2.graveyard == []
    assert [c.name for c in p2.hand] == ["Gale Swooper", "Island"]


def test_it_comes_back_when_the_freebooter_leaves(set_pool):
    """The card is held *by the source*, so what returns it is the source
    leaving — and the return lives on the one transition out, because a return
    wired into any single caller would be a return the other forty forgot."""
    game, _p1, p2 = _freebooter_board(set_pool)
    game.confirm_revealed_hand_pick(0, 0)
    (freebooter,) = list(game.controlled_by(0))

    game.remove_from_battlefield(freebooter)

    assert p2.exile == []
    assert [c.name for c in p2.hand] == ["Gale Swooper", "Island", "Shock"]


def test_a_hand_with_nothing_choosable_queues_no_prompt(set_pool):
    """A choice with no legal answer is not a choice, and leaving it queued
    would block the caster on a prompt they cannot satisfy."""
    game, _p1, p2 = _freebooter_board(set_pool, victim_hand=("Gale Swooper", "Island"))

    assert game.pending_choices == []
    assert p2.exile == []


def test_a_bare_exile_ending_is_not_this_card(set_pool):
    """The whole ending is expected, the duration included: "exile that card"
    with no duration is a permanent exile and a different card, and letting the
    clause be absent would let it be deleted with no change to the parse."""
    from engine.grammar import compile_line

    result = compile_line(
        "Target opponent reveals their hand. You choose a noncreature, nonland "
        "card from it. Exile that card."
    )

    assert not result.lowered


# --- Round 105: a lord that grants protection, and a batched trigger --------


def _sovereign_board(set_pool):
    pool = set_pool("M21")
    sovereign = _nosick(Permanent(card=pool["Feline Sovereign"]))
    lion = _nosick(Permanent(card=pool["Sabertooth Mauler"]))
    dog = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    crypt = Permanent(card=pool["Tormod's Crypt"])
    p1 = PlayerState(name="P1", battlefield=[sovereign, lion])
    p2 = PlayerState(name="P2", battlefield=[dog, crypt])
    game = Game(players=[p1, p2])
    game._settle()
    return game, sovereign, lion, dog, crypt


def test_feline_sovereign_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Feline Sovereign"])
    assert program.supported, program.reason


def test_the_lord_grants_protection_as_well_as_the_buff(set_pool):
    """"Protection" is not a layer-6 word — it names a *quality* and is read
    from its own channel, which is why `grantable_keywords` excludes it. The
    grant is **derived** from the lord, exactly as an Aura's is: a lord buff is
    rebuilt on every recompute, so a stamped grant would be one nothing
    clears."""
    game, _sovereign, lion, _dog, _crypt = _sovereign_board(set_pool)

    assert (lion.effective_power, lion.effective_toughness) == (4, 4)
    assert ("subtype", "dog") in game._protection_qualities(lion)


def test_the_lord_does_not_buff_itself(set_pool):
    """"**Other** Cats" — and the same filter decides both halves, because both
    ask the one matcher."""
    game, sovereign, _lion, _dog, _crypt = _sovereign_board(set_pool)

    assert (sovereign.effective_power, sovereign.effective_toughness) == (2, 3)
    assert game._protection_qualities(sovereign) == set()


def test_a_dog_cannot_block_a_protected_cat(set_pool):
    game, _sovereign, lion, dog, _crypt = _sovereign_board(set_pool)

    assert not game._can_block_attacker(dog, lion)


def _swing(game, attackers):
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.declare_attackers(0, attackers)
    game.current_step = "declare_blockers"
    game.declare_blockers(1, {})
    game.current_step = "combat_damage"
    game.resolve_combat_damage(0)
    game._settle()


def test_the_batched_trigger_fires_once_for_two_cats(set_pool):
    """"Whenever **one or more** Cats … deal combat damage to a player" is one
    trigger however many dealt it — which is why it cannot ride the per-attacker
    fire site, called once per attacker."""
    game, _sovereign, _lion, _dog, crypt = _sovereign_board(set_pool)

    _swing(game, [0, 1])

    assert not game.is_on_battlefield(crypt)
    assert [p.card.name for p in game.controlled_by(1)] == ["Alpine Watchdog"]


def test_no_cat_connecting_fires_nothing(set_pool):
    """The subject is tested against the creatures that actually dealt damage to
    that player, so a board with no Cat among them triggers nothing."""
    pool = set_pool("M21")
    sovereign = _nosick(Permanent(card=pool["Feline Sovereign"]))
    crypt = Permanent(card=pool["Tormod's Crypt"])
    p1 = PlayerState(name="P1", battlefield=[sovereign])
    p2 = PlayerState(name="P2", battlefield=[crypt])
    game = Game(players=[p1, p2])
    game._settle()

    # The Sovereign is itself a Cat, so it *would* fire — swing with nothing.
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.declare_attackers(0, [])
    game.current_step = "combat_damage"
    game.resolve_combat_damage(0)
    game._settle()

    assert game.is_on_battlefield(crypt)


def test_a_combat_damage_trigger_with_any_effect_now_fires(set_pool):
    """The defect this round found. The per-attacker fire site filtered by a
    hard-coded list of *instruction* kinds, so Jeskai Elder — "whenever this
    creature deals combat damage to a player, you may draw a card" — compiled
    cleanly, reported supported, and fired nowhere. A trigger's condition is what
    says when it fires; its effect is not a second condition."""
    pool = set_pool("M21")
    elder = _nosick(Permanent(card=pool["Jeskai Elder"]))
    p1 = PlayerState(
        name="P1", battlefield=[elder], library=[pool["Island"]] * 5,
        hand=[pool["Shock"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}

    _swing(game, [0])

    assert [c.kind for c in game.pending_choices] == ["optional_pay"]


# --- Round 106: a computed pump on the ability's own source -----------------


def _houndmaster_swing(set_pool, other_attackers=0):
    pool = set_pool("M21")
    hound = _nosick(Permanent(card=pool["Alpine Houndmaster"]))
    others = [
        _nosick(Permanent(card=pool["Gale Swooper"])) for _ in range(other_attackers)
    ]
    p1 = PlayerState(name="P1", battlefield=[hound] + others)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.declare_attackers(0, list(range(1 + other_attackers)))
    game._settle()
    return game, hound


def test_alpine_houndmaster_compiles_supported(set_pool):
    """The refusal was "a where-clause pump needs a single target" — every
    computed pump the engine had was aimed at one chosen permanent, and this one
    is on the ability's own source. It routes through ``pump_self``, which
    already boosts the source until end of turn: what was missing was a way to
    say *how big*, and that is the same ``x_from_count`` spec every other
    computed amount carries."""
    program = compile_card_oracle(set_pool("M21")["Alpine Houndmaster"])
    assert program.supported, program.reason

    attack = next(
        t for t in program.triggered_abilities if t.condition.kind == "creature_attacks"
    )
    assert attack.instruction.kind == "pump_self"
    assert attack.instruction.payload["power"] == "x"
    assert attack.instruction.payload["toughness"] == 0, "+X/+0 — only power is variable"


@pytest.mark.parametrize("others,power", [(0, 2), (1, 3), (2, 4)])
def test_the_pump_counts_the_other_attackers(set_pool, others, power):
    game, hound = _houndmaster_swing(set_pool, others)

    assert hound.effective_power == power
    assert hound.effective_toughness == 2, "+X/+0 leaves toughness alone"


def test_other_excludes_the_source_itself(set_pool):
    """"**Other** attacking creatures" is an identity comparison against the
    ability's own source, which ``permanent_matches_filter`` deliberately does
    not answer — it is about one permanent alone. The resolution knows the
    source, so it performs the exclusion; a continuous recompute, which does
    not, never produces the key."""
    game, hound = _houndmaster_swing(set_pool, other_attackers=0)

    assert hound.effective_power == 2, "attacking alone is +0/+0, not +1/+0"


# --- Round 107: the event's own creature, and a tax paid in life ------------


def _terror_board(set_pool, mine=(), theirs=(), their_life=20):
    pool = set_pool("M21")
    terror = _nosick(Permanent(card=pool["Terror of the Peaks"]))
    p1 = PlayerState(
        name="P1",
        battlefield=[terror] + [_nosick(Permanent(card=pool[n])) for n in mine],
    )
    p2 = PlayerState(name="P2", hand=[pool[n] for n in theirs], life=their_life)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, terror


def test_terror_of_the_peaks_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Terror of the Peaks"])
    assert program.supported, program.reason

    trigger = next(
        t for t in program.triggered_abilities
        if t.condition.kind == "matching_permanent_enters"
    )
    assert trigger.instruction.payload["amount_from_trigger"] == "entering_power"


def test_it_pings_for_the_entering_creatures_power(set_pool):
    """"That creature's power" is the *event's* creature, not the ability's
    source — read as "its power" the Dragon would deal its own 5, a number the
    card never mentions."""
    pool = set_pool("M21")
    game, p1, p2, _terror = _terror_board(set_pool)
    p1.hand = [pool["Warden of the Woods"]]        # 5/7

    game.cast_from_hand(0, "Warden of the Woods", target_player_index=1)
    game._settle()

    assert p2.life == 15


def test_the_power_is_frozen_by_the_event(set_pool):
    """CR 608.2's number is the one the event had. The fire site records it as
    the creature enters, because by the time the trigger resolves that creature
    may have been pumped, shrunk or destroyed."""
    from engine.grammar import compile_line

    (instruction,) = compile_line(
        "Whenever another creature you control enters, this creature deals "
        "damage equal to that creature's power to any target.",
        card_name="Terror of the Peaks",
    ).instructions

    assert "amount_from_trigger" in instruction.payload
    assert "amount" not in instruction.payload


def test_an_opponents_spell_aimed_at_it_costs_three_life(set_pool):
    """A tax in **life**, not mana (CR 118.3b), and scoped to the spell's chosen
    targets — which CR 601.2c settles before 601.2h pays, so the answer exists
    at the cast and only to a caller that has it."""
    game, _p1, p2, terror = _terror_board(set_pool, theirs=("Shock",))

    result = game.cast_from_hand(
        1, "Shock", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported, result.details
    assert p2.life == 17
    assert terror.damage_marked == 2, "the spell still resolves"


def test_a_spell_aimed_elsewhere_is_untaxed(set_pool):
    game, _p1, p2, _terror = _terror_board(
        set_pool, mine=("Gale Swooper",), theirs=("Shock",)
    )

    game.cast_from_hand(1, "Shock", target_player_index=0, target_permanent_index=1)

    assert p2.life == 20


def test_a_caster_who_cannot_pay_the_life_cannot_cast(set_pool):
    """CR 118.4: an unpayable cost makes the spell uncastable, not free."""
    game, _p1, p2, _terror = _terror_board(set_pool, theirs=("Shock",), their_life=2)

    result = game.cast_from_hand(
        1, "Shock", target_player_index=0, target_permanent_index=0
    )

    assert not result.supported
    assert p2.life == 2, "nothing was paid"


def test_a_life_tax_is_not_counted_as_mana(set_pool):
    """It is a different resource and a different rule. Counted by the mana
    scan it would be added to the generic cost."""
    from engine.cost_modifiers import cost_modifiers_for, spell_cost_tax

    (modifier,) = cost_modifiers_for(
        "Spells your opponents cast that target this creature cost an "
        "additional 3 life to cast."
    )
    assert modifier.life and modifier.targets_source

    game, _p1, _p2, _terror = _terror_board(set_pool, theirs=("Shock",))
    generic, _names = spell_cost_tax(game, 1, set_pool("M21")["Shock"])
    assert generic == 0


# --- Containment Priest: replaced, not triggered (round 111) ----------------


def _priest_board(set_pool, *, with_priest=True):
    pool = set_pool("M21")
    battlefield = [Permanent(card=pool["Containment Priest"])] if with_priest else []
    p1 = PlayerState(name="P1", battlefield=battlefield, life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, pool


def test_containment_priest_compiles_supported(set_pool):
    """Its whole text is one CR 614 replacement plus a keyword. The creature
    static gate asked for one replacement constant by name where the noncreature
    gate had always asked the whole registry, so this card was unsupported with
    a working interceptor behind it."""
    program = compile_card_oracle(set_pool("M21")["Containment Priest"])
    assert program.supported, program.reason


def test_containment_priest_exiles_a_creature_that_was_not_cast(set_pool):
    game, p1, _, pool = _priest_board(set_pool)

    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Baneslayer Angel"]), None)

    assert [p.card.name for p in game.controlled_by(0)] == ["Containment Priest"]
    assert [c.name for c in p1.exile] == ["Baneslayer Angel"]


def test_containment_priest_leaves_a_cast_creature_alone(set_pool):
    """CR 701.5a. Exactly one entry site in the engine is a cast — a resolving
    permanent spell — and it is the one that says so."""
    game, p1, _, pool = _priest_board(set_pool)
    p1.hand = [pool["Concordia Pegasus"]]

    game.cast_from_hand(0, "Concordia Pegasus")
    game._settle()

    assert "Concordia Pegasus" in [p.card.name for p in game.controlled_by(0)]
    assert p1.exile == []
    # The control, on the same board: something the Priest *does* catch. Without
    # it the assertions above hold on any engine where the card is unsupported
    # and nothing is exiled at all.
    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Baneslayer Angel"]), None)
    assert [c.name for c in p1.exile] == ["Baneslayer Angel"]


def test_containment_priest_stops_an_opponents_uncast_creature(set_pool):
    """"…would enter" is any battlefield, not its controller's. The interceptor
    asks every seat whether it controls the text, which is why an opponent's
    reanimation is caught too."""
    game, _, p2, pool = _priest_board(set_pool)

    game._put_permanent_onto_battlefield(1, Permanent(card=pool["Alpine Watchdog"]), None)

    assert list(game.controlled_by(1)) == []
    assert [c.name for c in p2.exile] == ["Alpine Watchdog"]


def test_containment_priest_does_not_touch_a_token(set_pool):
    """The printed word "nontoken" is a clause of the applicability, not an
    approximation of one: a token is created rather than put onto the
    battlefield from a zone, and would cease to exist rather than be exiled."""
    game, p1, _, pool = _priest_board(set_pool)
    token = Permanent(card=pool["Concordia Pegasus"], metadata={"is_token": True})

    game._put_permanent_onto_battlefield(0, token, None)

    assert "Concordia Pegasus" in [p.card.name for p in game.controlled_by(0)]
    assert p1.exile == []
    # The control, on the same board: something the Priest *does* catch. Without
    # it the assertions above hold on any engine where the card is unsupported
    # and nothing is exiled at all.
    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Baneslayer Angel"]), None)
    assert [c.name for c in p1.exile] == ["Baneslayer Angel"]


def test_containment_priest_does_not_touch_a_noncreature(set_pool):
    game, p1, _, pool = _priest_board(set_pool)

    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Mountain"]), None)

    assert "Mountain" in [p.card.name for p in game.controlled_by(0)]
    assert p1.exile == []
    # The control, on the same board: something the Priest *does* catch. Without
    # it the assertions above hold on any engine where the card is unsupported
    # and nothing is exiled at all.
    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Baneslayer Angel"]), None)
    assert [c.name for c in p1.exile] == ["Baneslayer Angel"]


def test_containment_priest_exiles_to_the_owners_zone(set_pool):
    """CR 400.3: the card goes to its *owner's* exile, which differs from the
    entering controller's the moment an opponent reanimates your creature."""
    game, p1, p2, pool = _priest_board(set_pool)
    stolen = Permanent(
        card=pool["Baneslayer Angel"], metadata={"owner_player_index": 0},
    )

    game._put_permanent_onto_battlefield(1, stolen, None)

    assert [c.name for c in p1.exile] == ["Baneslayer Angel"]
    assert p2.exile == []


def test_the_replaced_creature_never_enters_at_all(set_pool):
    """The difference between this and a "when it enters, exile it" trigger,
    which would let every one of these happen first: no enters-the-battlefield
    trigger is announced, and the permanent gets no battlefield identity."""
    game, p1, _, pool = _priest_board(set_pool)
    watcher = Permanent(card=pool["Baneslayer Angel"])
    before = len(game.stack)

    game._put_permanent_onto_battlefield(0, watcher, None)

    assert len(game.stack) == before
    assert game.permanent_id_of(watcher) is None
    assert not game.is_on_battlefield(watcher)


# --- Archfiend's Vessel: where it came from (round 115) ---------------------


def _vessel_board(set_pool, *, zone):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", life=20,
        hand=[pool["Archfiend's Vessel"]] if zone == "hand" else [],
        graveyard=[pool["Archfiend's Vessel"]] if zone == "graveyard" else [],
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    return game, p1, pool


def test_archfiends_vessel_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Archfiend's Vessel"])
    assert program.supported, program.reason


def test_archfiends_vessel_cast_from_hand_is_just_a_creature(set_pool):
    """CR 603.4's intervening-if, checked when the trigger would fire. From the
    hand the condition is false, so the Vessel stays a 1/1 and no Demon
    arrives."""
    game, p1, _ = _vessel_board(set_pool, zone="hand")

    game.cast_from_hand(0, "Archfiend's Vessel")
    game._settle()

    assert [p.card.name for p in game.controlled_by(0)] == ["Archfiend's Vessel"]
    assert p1.exile == []


def test_archfiends_vessel_cast_from_the_graveyard_exiles_itself_for_a_demon(set_pool):
    """"…or you cast it from your graveyard". The zone the *spell* was cast
    from, which is a different record from the zone the permanent entered from —
    a reanimation stamps the second and not the first."""
    from engine.cast_permissions import grant_permission

    game, p1, _ = _vessel_board(set_pool, zone="graveyard")
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[p1.graveyard[0]], duration=None, source_name="test",
    )

    game.cast_from_hand(0, "Archfiend's Vessel", from_zone="graveyard")
    game._settle()

    assert [p.card.name for p in game.controlled_by(0)] == ["Demon Token"]
    assert [c.name for c in p1.exile] == ["Archfiend's Vessel"]


def test_archfiends_vessel_reanimated_exiles_itself_for_a_demon(set_pool):
    """The half the card is actually built for, and the one that needed the
    entry seam to fire a permanent's own entry trigger at all."""
    game, p1, _ = _vessel_board(set_pool, zone="graveyard")
    card = p1.graveyard.pop()

    game._put_permanent_onto_battlefield(
        0, Permanent(card=card), None, from_zone="graveyard",
    )
    game._settle()

    assert [p.card.name for p in game.controlled_by(0)] == ["Demon Token"]
    assert [c.name for c in p1.exile] == ["Archfiend's Vessel"]


def test_archfiends_vessel_put_into_play_from_nowhere_makes_no_demon(set_pool):
    """A permanent put onto the battlefield without a stated origin answers the
    condition False, which is the reading that leaves the Vessel a 1/1."""
    game, p1, pool = _vessel_board(set_pool, zone="hand")
    p1.hand.clear()
    # The control, on the same board and one argument apart: stating the origin
    # *does* make the Demon. Without it this holds on any engine where the card
    # is unsupported and nothing fires at all.
    control = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    control.enforce_mana_costs = False
    control._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Archfiend's Vessel"]), None, from_zone="graveyard",
    )
    control._settle()
    assert [p.card.name for p in control.controlled_by(0)] == ["Demon Token"]

    game._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Archfiend's Vessel"]), None,
    )
    game._settle()

    assert [p.card.name for p in game.controlled_by(0)] == ["Archfiend's Vessel"]
    assert p1.exile == []


def test_a_permanent_put_into_play_fires_its_own_entry_trigger(set_pool):
    """The general defect the Vessel walked into.

    A permanent's own "when this enters" trigger was fired from exactly one
    place — the resolution of a permanent *spell* — so an entry by any other
    route never fired it. Niambi is the witness because her entry trigger is
    observable as a queued prompt."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Baneslayer Angel"]), None,
    )

    game._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Niambi, Esteemed Speaker"]), None,
    )
    game._settle()

    assert game.pending_choices_of("optional_pay", 0)


def test_exiling_the_source_records_that_it_happened(set_pool):
    """"Exile it. **If you do**, …" after an action that was not optional. The
    branch asks whether the step took place — a source already gone exiles
    nothing (CR 608.2b) and the token must not arrive."""
    from engine.grammar import compile_line

    compiled = compile_line(
        "Exile it. If you do, create a 5/5 black Demon creature token with flying."
    )
    kinds = [i.kind for i in compiled.instructions]

    assert kinds == ["exile_self", "if_then"]
    condition = compiled.instructions[1].payload["condition"]
    assert condition == {"kind": "it_happened", "key": "exiled_self"}


# --- Chandra's Incinerator: a history, and a player the event named (121) ---


def _incinerator_board(set_pool, hand=("Shock",)):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20, hand=[pool[n] for n in hand])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, pool


def test_chandras_incinerator_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Chandra's Incinerator"])
    assert program.supported, program.reason


def test_the_reduction_tracks_noncombat_damage_dealt_this_turn(set_pool):
    """A turn history rather than a board read: the damage is gone the instant
    it is dealt, so nothing on any battlefield could answer it. Recorded at the
    one site that knows both that the damage was noncombat and whose source it
    was."""
    from engine.cost_modifiers import cost_reduction_for_cast

    game, _, p2, pool = _incinerator_board(set_pool)
    card = pool["Chandra's Incinerator"]
    assert cost_reduction_for_cast(game, 0, card)[0].generic == 0

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()

    assert p2.life == 18
    assert cost_reduction_for_cast(game, 0, card)[0].generic == 2


def test_the_history_resets_between_turns(set_pool):
    """"This turn" is the turn, so the tally goes back to nothing with the rest
    of the turn histories."""
    from engine.cost_modifiers import cost_reduction_for_cast

    game, _, _, pool = _incinerator_board(set_pool)
    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()
    assert cost_reduction_for_cast(game, 0, pool["Chandra's Incinerator"])[0].generic == 2

    game.begin_turn_bookkeeping(1)

    assert cost_reduction_for_cast(game, 0, pool["Chandra's Incinerator"])[0].generic == 0


def test_the_trigger_hits_the_board_of_the_player_who_was_damaged(set_pool):
    """"…to target creature or planeswalker **that player** controls." "That
    player" is a referent the *event* picked, resolved by the handler holding
    the trigger's context — not a seat comparison, which would reduce it to
    "any opponent"."""
    game, _, p2, pool = _incinerator_board(set_pool)
    incinerator = Permanent(card=pool["Chandra's Incinerator"])
    game._put_permanent_onto_battlefield(0, incinerator, None)
    _nosick(incinerator)
    theirs = Permanent(card=pool["Baneslayer Angel"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    mine = Permanent(card=pool["Alpine Watchdog"])
    game._put_permanent_onto_battlefield(0, mine, None)

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()

    assert theirs.damage_marked == 2, "that much damage, to their creature"
    assert mine.damage_marked == 0, "not to mine"


def test_that_player_is_refused_as_a_seat_comparison():
    """The matcher answers about a permanent and a seat; "that player" is
    neither. Reduced to "not you" it means "any opponent" — right in a
    two-player game by coincidence, wrong the moment there are three."""
    from engine.subject_filters import subject_matches
    from tests.helpers import _mk_creature_card

    perm = Permanent(card=_mk_creature_card("Bear", 2, 2, ""))
    game = Game(players=[
        PlayerState(name="P1"), PlayerState(name="P2", battlefield=[perm]),
    ])

    assert subject_matches(game, perm, {"controller": "you"}, observer=1)
    assert not subject_matches(game, perm, {"controller": "that_player"}, observer=0)
    assert not subject_matches(game, perm, {"controller": "that_player"}, observer=1)


# --- Garruk's Harbinger: two fire sites, one condition (round 122) ----------


def _harbinger_board(set_pool, library=()):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20, library=[pool[n] for n in library])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    harbinger = Permanent(card=pool["Garruk's Harbinger"])
    game._put_permanent_onto_battlefield(0, harbinger, None)
    _nosick(harbinger)
    game.active_player_index = 0
    return game, p1, p2, harbinger, pool


def _connect(game):
    game._set_phase_and_step("combat", "beginning_of_combat")
    game.advance_combat_phase()
    game.declare_attackers(0, [0])
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    game.advance_combat_phase()
    game.resolve_combat_damage(0)
    game._settle()


def test_garruks_harbinger_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Garruk's Harbinger"])
    assert program.supported, program.reason


def test_the_trigger_looks_at_as_many_cards_as_it_dealt(set_pool):
    """"Look at **that many** cards": the firing event's number, frozen by the
    fire site. An absent record would look at nothing rather than at a count the
    card never printed."""
    game, p1, p2, harbinger, _ = _harbinger_board(
        set_pool, library=("Mountain", "Alpine Watchdog", "Island", "Forest", "Shock"),
    )

    _connect(game)

    assert p2.life == 20 - harbinger.effective_power
    (choice,) = game.pending_choices
    assert choice.kind == "look_top_pick"
    assert choice.data["top_count"] == harbinger.effective_power


def test_only_a_card_the_phrase_names_may_be_taken(set_pool):
    """"a creature card **or** Garruk planeswalker card" — the alternatives are
    OR'd, because the two sides restrict different characteristics and one
    filter AND's its keys. The rest go to the bottom in a *random* order, which
    is a stated shuffle rather than the player's freedom."""
    game, p1, _, _, _ = _harbinger_board(
        set_pool, library=("Mountain", "Alpine Watchdog", "Island", "Forest", "Shock"),
    )

    _connect(game)
    (choice,) = game.pending_choices
    assert game.live_look_top_candidates(choice) == [1]

    game._default_look_top_pick(choice)

    assert [c.name for c in p1.hand] == ["Alpine Watchdog"]
    assert len(p1.library) == 4
    assert p1.library[0].name == "Shock", "the card never looked at stays on top"


def test_the_pick_is_optional(set_pool):
    """"You **may** reveal": declining is a legal answer and not the same as an
    illegal one — the rest still go to the bottom."""
    game, p1, _, _, _ = _harbinger_board(
        set_pool, library=("Mountain", "Island", "Forest", "Plains", "Shock"),
    )

    _connect(game)
    (choice,) = game.pending_choices
    assert choice.data["optional"] is True
    assert game.live_look_top_candidates(choice) == [], "no creature among them"

    game._default_look_top_pick(choice)

    assert p1.hand == []
    assert len(p1.library) == 5


def test_the_planeswalker_half_has_its_own_fire_site(set_pool):
    """A planeswalker takes combat damage as a *permanent*, so the loyalty path
    never reaches the player-damage fire site. A trigger naming both halves
    would otherwise fire on exactly one of them."""
    pool = set_pool("M21")
    game, p1, _, harbinger, _ = _harbinger_board(
        set_pool, library=("Alpine Watchdog", "Island", "Forest", "Plains", "Shock"),
    )
    walker = Permanent(
        card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 6},
    )
    game._put_permanent_onto_battlefield(1, walker, None)

    game._set_phase_and_step("combat", "beginning_of_combat")
    game.advance_combat_phase()
    game.declare_attackers(
        0, [0], attacker_planeswalker_ids={0: game.permanent_id_of(walker)},
    )
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    game.advance_combat_phase()
    game.resolve_combat_damage(0)
    game._settle()

    assert [c.kind for c in game.pending_choices] == ["look_top_pick"]


# --- Waker of Waves: an ability that works from the hand (round 124) --------


def _waker_board(set_pool, library=("Shock", "Island", "Forest")):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", life=20,
        hand=[pool["Waker of Waves"], pool["Mountain"]],
        library=[pool[n] for n in library],
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    return game, p1, pool


def test_waker_of_waves_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Waker of Waves"])
    assert program.supported, program.reason


def test_the_ability_is_activated_from_the_hand(set_pool):
    """CR 113.6: an ability works only from the battlefield unless something
    says otherwise, and "Discard this card" is what says otherwise. The card
    leaves the hand as the cost is paid (CR 602.2b), before the ability is on
    the stack."""
    game, p1, _ = _waker_board(set_pool)

    result = game.activate_from_hand(0, "Waker of Waves")
    game._settle()

    assert result.supported, result.details
    assert [c.name for c in p1.hand] == ["Mountain"]
    assert [c.name for c in p1.graveyard] == ["Waker of Waves"]
    (choice,) = game.pending_choices
    assert choice.kind == "look_top_pick"
    assert choice.data["top_count"] == 2


def test_the_unchosen_card_goes_to_the_graveyard(set_pool):
    """"…and the other into your **graveyard**". Where the rest go is the
    card's own statement — a card that bottomed them instead is a different
    card, and the difference is invisible until the pile is looked at again."""
    game, p1, _ = _waker_board(set_pool)

    game.activate_from_hand(0, "Waker of Waves")
    game._settle()
    game.confirm_look_top_pick(0, 0)
    game._settle()

    assert [c.name for c in p1.hand] == ["Mountain", "Shock"]
    assert [c.name for c in p1.graveyard] == ["Waker of Waves", "Island"]
    assert [c.name for c in p1.library] == ["Forest"]


def test_an_ability_without_that_cost_is_not_activatable_from_hand(set_pool):
    """The refusal that keeps the hand from opening generally: an ability
    activatable from anywhere would let a creature card tap for its own {T}
    ability before it was ever cast."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20, hand=[pool["Shacklegeist"]])
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    result = game.activate_from_hand(0, "Shacklegeist")

    assert not result.supported
    assert "from the battlefield" in result.details
    assert [c.name for c in p1.hand] == ["Shacklegeist"]


def test_the_anthem_still_applies_on_the_battlefield(set_pool):
    """The card's other half, unchanged: a lord buff scoped to the opponents'
    creatures."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Waker of Waves"]), None,
    )
    theirs = Permanent(card=pool["Alpine Watchdog"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    game._recompute_continuous_effects()

    assert (theirs.effective_power, theirs.effective_toughness) == (1, 2)


# --- Ghostly Pilferer: three lines and an untap seam (round 128) ------------


def _pilferer_board(set_pool, mana=2):
    pool = set_pool("M21")
    pilferer = Permanent(card=pool["Ghostly Pilferer"])
    p1 = PlayerState(name="P1", life=20, library=[pool["Mountain"]] * 6)
    p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": mana, "generic": 0}
    p2 = PlayerState(
        name="P2", life=20, hand=[pool["Shock"]], graveyard=[pool["Shock"]],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game._put_permanent_onto_battlefield(0, pilferer, None)
    _nosick(pilferer)
    return game, p1, p2, pilferer, pool


def test_ghostly_pilferer_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Ghostly Pilferer"])
    assert program.supported, program.reason
    assert {t.condition.kind for t in program.triggered_abilities} == {
        "permanent_becomes_untapped", "opponent_casts_spell",
    }


def test_becoming_untapped_offers_the_payment(set_pool):
    """CR 701.26b's event, announced by the one untap seam — which is why the
    seam had to exist first: eleven places set the flag, and a trigger wired
    into one of them would have missed the other ten."""
    game, p1, _, pilferer, _ = _pilferer_board(set_pool)
    pilferer.tapped = True

    game.become_untapped(pilferer)
    game._settle()

    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)
    game._settle()
    assert len(p1.hand) == 1


def test_untapping_an_already_untapped_permanent_is_no_event(set_pool):
    """CR 701.26b: only a tapped permanent can be untapped, so there is no
    state change and no trigger."""
    game, _, _, pilferer, _ = _pilferer_board(set_pool)

    assert not game.become_untapped(pilferer)
    game._settle()

    assert game.pending_choices == []


def test_the_cast_trigger_reads_the_zone_the_spell_came_from(set_pool):
    """"…from anywhere other than their **hand**". The zone rides on the cast
    event — the same field See the Truth's cast-zone conditional reads — and an
    event with no zone recorded counts as a cast from the hand, which is the
    ordinary case and the one that must not fire."""
    from engine.cast_permissions import grant_permission

    game, p1, p2, _, _ = _pilferer_board(set_pool)
    grant_permission(
        game, player_index=1, zone="graveyard", mode="cast",
        cards=[p2.graveyard[0]], duration=None, source_name="test",
    )
    game.enforce_mana_costs = False

    game.cast_from_hand(1, "Shock", target_player_index=0, from_zone="graveyard")
    game._settle()

    assert len(p1.hand) == 1


def test_a_cast_from_hand_does_not_fire_it(set_pool):
    game, p1, _, _, _ = _pilferer_board(set_pool)
    game.enforce_mana_costs = False

    game.cast_from_hand(1, "Shock", target_player_index=0)
    game._settle()

    assert p1.hand == []


def test_the_discard_ability_makes_only_its_own_source_unblockable(set_pool):
    """The ability's own source is not a target — nothing is chosen, so there is
    no picker. A source already gone grants nothing rather than falling back to
    a scan, which would make some other creature unblockable."""
    game, p1, _, pilferer, pool = _pilferer_board(set_pool)
    p1.hand = [pool["Island"]]
    other = Permanent(card=pool["Alpine Watchdog"])
    game._put_permanent_onto_battlefield(0, other, None)
    blocker = Permanent(card=pool["Alpine Watchdog"])
    game._put_permanent_onto_battlefield(1, blocker, None)

    result = game.activate_permanent_ability(0, "Ghostly Pilferer")
    game._settle()

    assert result.supported, result.details
    assert p1.hand == [], "the discard was paid"
    assert not game._can_block_attacker(blocker, pilferer)
    assert game._can_block_attacker(blocker, other), "and nobody else"


# --- Pursued Whale: a token with printed abilities (round 130) --------------


def _whale_board(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20, hand=[pool["Pursued Whale"]])
    p2 = PlayerState(name="P2", life=20, hand=[pool["Shock"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Pursued Whale")
    game._settle()
    whale = next(p for p in game.controlled_by(0) if p.card.name == "Pursued Whale")
    return game, p1, p2, whale, pool


def test_pursued_whale_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Pursued Whale"])
    assert program.supported, program.reason


def test_each_opponent_gets_a_pirate(set_pool):
    """"**Each opponent** creates …" is payload on the same token maker — the
    sentence is otherwise identical, so the recipient is data rather than a
    second production."""
    game, _, _, _, _ = _whale_board(set_pool)

    pirates = list(game.controlled_by(1))

    assert [p.card.name for p in pirates] == ["Pirate Token"]
    assert list(game.controlled_by(0))[0].card.name == "Pursued Whale"


def test_the_token_carries_both_printed_abilities(set_pool):
    """The token's abilities are printed *lines*, not keywords, and they are
    carried as text so the compiler reads them exactly as it reads any card's.
    A line nothing implements refuses the whole card at lowering — a token
    silently lacking an ability is the shape the support gate exists to stop."""
    game, _, _, whale, _ = _whale_board(set_pool)
    pirate = next(iter(game.controlled_by(1)))

    assert "can't block" in pirate.card.oracle_text
    assert "attack each combat if able" in pirate.card.oracle_text
    assert not game._can_block_attacker(pirate, whale)


def test_the_tokens_static_grants_its_controllers_creatures_a_requirement(set_pool):
    """"Creatures you control attack each combat if able" is a board-wide static
    granted through the layer bridge — appended to each affected permanent's
    effective card, so `combat_restrictions.py` reads it as though the creature
    printed it and the declare-attackers step needs no new code."""
    from engine.combat_restrictions import combat_restriction_for
    from engine.oracle import normalize_creature_line

    game, _, _, _, pool = _whale_board(set_pool)
    theirs = Permanent(card=pool["Alpine Watchdog"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    game._recompute_continuous_effects()

    assert "attacks each combat if able" in theirs.effective_card.oracle_text.lower()
    assert combat_restriction_for(
        normalize_creature_line("This creature attacks each combat if able.")
    ) is not None


def test_the_tax_applies_only_to_an_opponents_spell_aimed_at_the_whale(set_pool):
    """The mana twin of round 107's life tax, sharing its scope: a fact about
    the spell's *chosen targets*, answered at CR 601.2f when the cost is
    calculated."""
    from engine.cost_modifiers import spell_cost_tax

    game, _, _, whale, pool = _whale_board(set_pool)
    shock = pool["Shock"]

    assert spell_cost_tax(game, 1, shock, [whale]) == (3, ["Pursued Whale"])
    assert spell_cost_tax(game, 1, shock, []) == (0, [])
    assert spell_cost_tax(game, 0, shock, [whale]) == (0, []), "not the controller's own"


# --- Conspicuous Snoop: the top of your library (round 131) -----------------


def _snoop_board(set_pool, top="Goblin Arsonist"):
    pool = set_pool("M21")
    snoop = Permanent(card=pool["Conspicuous Snoop"])
    p1 = PlayerState(name="P1", life=20, library=[pool[top], pool["Mountain"]])
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, snoop, None)
    _nosick(snoop)
    return game, p1, snoop, pool


def test_conspicuous_snoop_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Conspicuous Snoop"])
    assert program.supported, program.reason


def test_the_top_card_is_public(set_pool):
    """CR 400.2: "play with the top card revealed" makes it a public object —
    a stronger permission than "you may look", which is its own line and shows
    the card to its controller alone."""
    from engine.library_top import top_is_public, top_is_visible

    game, _, _, _ = _snoop_board(set_pool)

    assert top_is_public(game, 0)
    assert top_is_visible(game, 0)
    assert not top_is_public(game, 1)


def test_a_goblin_on_top_may_be_cast_and_a_land_may_not(set_pool):
    """CR 601.3 opens the *top of the library*, not the library — so the
    permission is asked of the card that is actually on top, and the narrowing
    is the printed noun phrase read by the same reader every other one uses."""
    from engine.library_top import top_castable

    game, p1, _, _ = _snoop_board(set_pool)
    assert top_castable(game, 0, p1.library[0])
    assert not top_castable(game, 0, p1.library[1]), "only the top card"

    game, p1, _, _ = _snoop_board(set_pool, top="Mountain")
    assert not top_castable(game, 0, p1.library[0]), "a land is not a Goblin spell"


def test_the_snoop_has_the_top_goblins_activated_abilities(set_pool):
    """A layer-6 grant whose source is a card in a *zone*, not a permanent. It
    is derived on every read rather than stamped, because the library changes
    on every draw and a stamped grant would go stale.

    The Goblin is invented: M21 prints none with an activated ability, and the
    property under test is the shape rather than any particular card.
    """
    from tests.helpers import _mk_creature_card

    game, p1, snoop, _ = _snoop_board(set_pool)
    pinger = _mk_creature_card(
        "Goblin Pinger", 1, 1, "{R}: This creature deals 1 damage to any target.",
    )
    pinger = dataclasses.replace(pinger, type_line="Creature — Goblin")
    p1.library.insert(0, pinger)

    granted = game.playable_card_of(snoop).oracle_text
    assert "{R}: This creature deals 1 damage to any target." in granted

    # Draw the Goblin away and the grant goes with it.
    p1.library.pop(0)
    assert "deals 1 damage" not in game.playable_card_of(snoop).oracle_text


def test_only_activated_abilities_are_granted(set_pool):
    """"…has all **activated** abilities of that card" — a triggered ability on
    top grants nothing, and handing over the whole text would give the Snoop
    abilities it never had. Goblin Arsonist prints only a dies-trigger."""
    from engine.library_top import granted_top_abilities

    game, _, snoop, _ = _snoop_board(set_pool, top="Goblin Arsonist")

    assert granted_top_abilities(game, snoop) == ()


# --- Round 137: a search for two named cards, each optional -----------------


def test_alpine_houndmaster_compiles_its_entry_search(set_pool):
    program = compile_card_oracle(set_pool("M21")["Alpine Houndmaster"])
    assert [t.supported for t in program.triggered_abilities] == [True, True]


def _houndmaster_search(set_pool):
    pool = set_pool("M21")
    hound = Permanent(card=pool["Alpine Houndmaster"])
    p1 = PlayerState(
        name="P1",
        library=[
            pool["Alpine Watchdog"], pool["Igneous Cur"],
            pool["Forest"], pool["Alpine Watchdog"],
        ],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game._put_permanent_onto_battlefield(0, hound, None)
    game._settle()
    game.confirm_optional_pay(0, accept=True)
    game._settle()
    return game, p1


def test_alpine_houndmaster_finds_each_named_card_once(set_pool):
    """"a card named Alpine Watchdog **and/or** a card named Igneous Cur" — one
    find per printed name, answered whole. The picker offers the union, but the
    answer consumes each name as a pick uses it, so two Watchdogs cannot answer
    both finds — the pair is a refused answer, not a widened search."""
    from engine.search_filters import search_matches

    game, p1 = _houndmaster_search(set_pool)

    search = game.pending_choices[0]
    assert [c.name for c in p1.library if search_matches(c, search.data)] == [
        "Alpine Watchdog", "Igneous Cur", "Alpine Watchdog",
    ], "the union is what the picker may offer"

    assert not game.confirm_search_library_picks(
        0,
        [{"zone": "library", "index": 0}, {"zone": "library", "index": 3}],
    ), "two copies of one name cannot answer both finds"

    assert game.confirm_search_library_picks(
        0,
        [{"zone": "library", "index": 0}, {"zone": "library", "index": 1}],
    )
    game._settle()

    assert sorted(c.name for c in p1.hand) == ["Alpine Watchdog", "Igneous Cur"]
    assert game.pending_choices == [], (
        "both slots read \"into your hand\", so there is nothing to ask"
    )
