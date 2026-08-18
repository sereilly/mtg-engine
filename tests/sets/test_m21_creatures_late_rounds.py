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
    assert ability.cost.tap_filter == {"type_filter": "creature", "subtype_filter": "spirit"}


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
