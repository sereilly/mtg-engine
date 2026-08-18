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
