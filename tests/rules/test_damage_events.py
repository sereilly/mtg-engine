"""One damage event, start to finish — engine/damage_events.py.

Two rules meet here. CR 120.4 sequences a damage event: the damage is dealt
(120.4b, as modified by shields and redirects), then what was dealt is processed
into its results (120.4c, as modified by effects that cap life lost or damage
marked). CR 616.1 chooses *within* each of those halves, and does not separate
replacement effects from prevention effects while doing it.

So these tests are about two seams: that each half gathers both registries into
one contention set, and that the halves stay distinct — the damage dealt and the
life lost are two numbers, and collapsing them is what kept the combat damage
step running its shields and its replacements at two different moments.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from engine import PlayerState
from engine.control import change_control
from engine.damage_redirects import DamageRedirect, add_redirect, redirects_on
from engine.damage_events import (
    _assert_one_order_space,
    damage_candidates,
    damage_source_seat,
    deal_damage,
)
from engine.game import Game
from engine.models import CardDefinition, Permanent
from engine.prevention import POOL
from engine.replacements import REPLACEMENTS, replacement_effect
from tests.helpers import _mk_creature_card

FLOOR_TEXT = (
    "damage that would reduce your life total to less than 1 reduces it to 1 instead"
)


def _player_with_a_floor_and_a_pool(life: int = 4, pool: int = 2):
    ali = _mk_creature_card("Life Floor", power=1, toughness=3, oracle_text=FLOOR_TEXT)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ali)], life=life)
    p1.damage_prevention_pool = pool
    game = Game(players=[p1, PlayerState(name="P2")])
    return game, p1


# ---------------------------------------------------------------------------
# CR 616.1 — one contention set per half
# ---------------------------------------------------------------------------

@pytest.mark.cr("616.1")
def test_616_1_one_damage_event_gathers_both_registries():
    """The effects attempting to modify one damage event are the shields *and*
    the replacements at once. Counting from a single registry can only
    undercount, and that count is exactly what the affected player's choice
    would be over."""
    game, p1 = _player_with_a_floor_and_a_pool()
    event = {"recipient": p1, "amount": 10, "source": None, "combat": False}

    keys = [c.key for c in damage_candidates(p1)]
    applicable = [c.key for c in damage_candidates(p1) if c.applies(game, event)]

    assert "_redirect_damage_to_bodyguard" in keys, "the replacement registry contributed"
    assert "_prevention_pool" in applicable, "the shield registry applies to this event"


@pytest.mark.cr("616.1")
def test_616_1_asking_the_union_applies_nothing():
    """The purity contract holds across the seam, not just within one registry:
    an effect from either side may be asked about and then not chosen."""
    game, p1 = _player_with_a_floor_and_a_pool()
    event = {"recipient": p1, "amount": 10, "source": None, "combat": False}

    before = (p1.life, p1.damage_prevention_pool)
    [c.applies(game, event) for c in damage_candidates(p1)]

    assert (p1.life, p1.damage_prevention_pool) == before, (
        "asking which effects apply to a damage event applied one"
    )


@pytest.mark.cr("616.1e")
def test_616_1e_redirects_default_ahead_of_shields_for_both_recipients():
    """CR 616.1e lets the affected player pick any order; this is the default a
    non-interactive seat takes, and it is the same answer for both recipients
    for the same reason — a shield spent on damage that is about to be dealt to
    someone else is spent on nothing."""
    bear = Permanent(card=_mk_creature_card("Bear", 2, 2))
    creature_orders = {c.key: c.order for c in damage_candidates(bear)}
    player_orders = {c.key: c.order for c in damage_candidates(PlayerState(name="P"))}

    assert creature_orders["_redirect_damage_to_player"] < creature_orders["_prevention_pool"]
    assert creature_orders["_prevent_desert_damage"] < creature_orders["_prevention_pool"]
    assert player_orders["_redirect_damage_to_bodyguard"] < player_orders["_prevention_pool"]


@pytest.mark.cr("616.1")
def test_616_1_a_shield_and_a_replacement_may_not_share_an_order():
    """Each registry rejects a duplicate within itself, but the damage-dealt
    order space spans both — so the tie neither can see on its own has to be
    caught where they are put together, and at import for the same reason."""
    kind = "damage_to_player"
    try:
        replacement_effect(kind, POOL, applies=lambda game, payload: True)(
            lambda game, payload: None
        )
        with pytest.raises(ValueError, match="share one order space"):
            _assert_one_order_space()
    finally:
        REPLACEMENTS[kind] = [c for c in REPLACEMENTS[kind] if c.order != POOL]
    _assert_one_order_space()


# ---------------------------------------------------------------------------
# CR 120.4 — the damage dealt and its result are two numbers
# ---------------------------------------------------------------------------

@pytest.mark.cr("120.4b", "120.4c")
def test_120_4_a_result_replacement_caps_the_result_not_the_damage():
    """Ali from Cairo modifies what the damage *does* (CR 120.4c), not the
    damage (120.4b). So the full 8 is dealt — which is what lifelink and a
    "deals damage to a player" trigger read — and only the life loss is capped.
    One number could not answer both questions."""
    game, p1 = _player_with_a_floor_and_a_pool(life=4, pool=2)

    outcome = deal_damage(
        game, {"recipient": p1, "amount": 10, "source": None, "combat": False}
    )

    assert p1.damage_prevention_pool == 0, "the shield applied in the first half"
    assert outcome.dealt == 8, "10 damage, 2 prevented, 8 dealt"
    assert outcome.result == 3, "of which only 3 reduces a life total of 4"
    assert not outcome.consumed


@pytest.mark.cr("120.4b", "615.1")
def test_120_4b_prevented_damage_never_reaches_the_results_half():
    """A shield that absorbs the whole event leaves nothing to be dealt, so
    there is no result to process and no effect in the second half is asked."""
    game, p1 = _player_with_a_floor_and_a_pool(life=4, pool=20)

    outcome = deal_damage(
        game, {"recipient": p1, "amount": 10, "source": None, "combat": False}
    )

    assert (outcome.consumed, outcome.dealt, outcome.result) == (False, 0, 0)
    assert p1.damage_prevention_pool == 10
    assert p1.life == 4, "deal_damage does not apply the result; the caller does"


@pytest.mark.cr("509.1h", "702.19b")
def test_509_1h_a_blocked_trampler_is_not_an_unblocked_creature():
    """Veteran Bodyguard covers damage "by unblocked creatures". CR 509.1h: an
    attacker with a blocker declared for it *is* a blocked creature, and stays
    one even if every blocker leaves combat — so the excess a trampler assigns
    to the player is not dealt by an unblocked creature and is not redirected.

    The redirect reads the source permanent's own combat state, which is what
    makes it get this right; a check that trusted "this damage arrived on the
    player's pile during combat" cannot tell the two apart."""
    # Veteran Bodyguard's line *in full*. The fixture used to carry only the
    # second half, which worked while the interceptor probed for it as a
    # substring — and the untapped condition is not decoration: a redirect that
    # fires while its creature is tapped is a strictly better card. The reader
    # is anchored on the whole printed line now, so the fixture prints one.
    guard_text = (
        "As long as this creature is untapped, all damage that would be dealt "
        "to you by unblocked creatures is dealt to this creature instead."
    )
    bodyguard = Permanent(card=_mk_creature_card("Bodyguard", 2, 5, guard_text))
    defender = PlayerState(name="P1", battlefield=[bodyguard], life=20)
    game = Game(players=[defender, PlayerState(name="P2")])

    trampler = Permanent(card=_mk_creature_card("Trampler", 4, 4))
    trampler.attacking, trampler.blocked = True, True
    unblocked = Permanent(card=_mk_creature_card("Unblocked", 4, 4))
    unblocked.attacking, unblocked.blocked = True, False

    trample_over = deal_damage(
        game, {"recipient": defender, "amount": 2, "source": trampler, "combat": True}
    )
    assert trample_over.dealt == 2, "trample damage reaches the player"
    assert bodyguard.damage_marked == 0, "the bodyguard covers unblocked creatures only"

    redirected = deal_damage(
        game, {"recipient": defender, "amount": 4, "source": unblocked, "combat": True}
    )
    assert redirected.consumed and redirected.dealt == 0
    assert bodyguard.damage_marked == 4


@pytest.mark.cr("120.3f", "120.4c")
def test_120_3f_lifelink_reads_the_damage_dealt_not_the_life_lost():
    """A lifelinking attacker into a life floor. CR 120.3f gains life equal to
    the damage *dealt*, and the floor is a 120.4c effect that changes only what
    the damage costs in life — so the attacker's controller gains the full 9
    while the defender's life stops at 1.

    This is the case that used to force the combat damage step to run its
    shields where the event was recorded: with one number, lifelink and the life
    total could not both be right."""
    attacker = Permanent(
        card=replace(_mk_creature_card("Lifelinker", 9, 9), keywords=("Lifelink",))
    )
    attacker.metadata["summoning_sickness_turn"] = -99
    ali = _mk_creature_card("Life Floor", 1, 3, FLOOR_TEXT)
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=ali)], life=5)
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    game.declare_attackers(0, [0])
    game.advance_combat_phase()  # declare_blockers
    game.declare_blockers(1, {})
    game.advance_combat_phase()  # combat damage

    assert p2.life == 1, "the floor capped the life lost at 4"
    assert p1.life == 29, "but lifelink gained the 9 that was dealt"


@pytest.mark.cr("120.7")
def test_120_7_each_combat_event_is_attributed_to_the_creature_that_dealt_it():
    """"The source of damage is the object that dealt it." With several
    attackers the step applies their events in a second loop, and each one has
    to carry its own source: Reverse Polarity counts only what artifact sources
    dealt, so attributing every event to whichever attacker happened to be
    processed last silently mis-tallies it."""
    artifact = Permanent(
        card=replace(
            _mk_creature_card("Clockwork", 2, 2),
            type_line="Artifact Creature — Test",
            raw={"name": "Clockwork", "type_line": "Artifact Creature — Test",
                 "power": "2", "toughness": "2"},
        )
    )
    flesh = Permanent(card=_mk_creature_card("Flesh", 3, 3))
    for permanent in (artifact, flesh):
        permanent.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[artifact, flesh], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    game.declare_attackers(0, [0, 1])
    game.advance_combat_phase()  # declare_blockers
    game.declare_blockers(1, {})
    game.advance_combat_phase()  # combat damage

    assert p2.damage_taken_this_turn == 5, "both attackers connected"
    assert p2.artifact_damage_taken_this_turn == 2, "only the artifact's 2 counts"


@pytest.mark.cr("616.1g")
def test_616_1g_an_effect_on_a_contained_event_is_chosen_after_the_outer_one():
    """"One replacement effect may apply to an event, and another may apply to
    an event contained within the first. The second can't be chosen until after
    the first has been chosen."

    Jade Monolith's redirect makes a new damage event *inside* its own
    application, so the shields on the redirect's destination are only ever
    gathered once the redirect has been chosen — the ordering falls out of the
    inner event happening within `apply`, not from a rule about it. What the
    outer choice settles is whether the inner event exists at all: the
    creature's own shield is never spent, because the damage left."""
    bear = Permanent(card=_mk_creature_card("Bear", 2, 2))
    bear.damage_prevention_pool = 5
    bear.metadata["redirect_damage_to_player"] = 1
    p1 = PlayerState(name="P1", battlefield=[bear], life=20)
    p2 = PlayerState(name="P2", life=20)
    p2.damage_prevention_pool = 2
    game = Game(players=[p1, p2])

    game._mark_damage_on_permanent(bear, 3, source=None)

    assert bear.damage_marked == 0 and bear.damage_prevention_pool == 5, (
        "the outer choice sent the damage away, so the creature's shield was "
        "never in contention for it"
    )
    assert p2.damage_prevention_pool == 0, "the inner event contended over its own shield"
    assert p2.life == 19, "3 redirected, 2 prevented"


@pytest.mark.cr("616.1e")
def test_616_1e_a_damage_event_given_a_restart_asks_and_re_runs():
    """A damage event asks exactly as a draw does, given a caller that can offer
    the re-run. Held at this level because every real path — spell damage,
    combat damage — reaches CR 616.1e through this one contract, and it is
    cheaper to see a broken restart here than three loops out
    (tests/rules/test_resumption.py is where the loops are pinned).

    A Circle of Protection and a prevention pool are both applicable to one red
    source, which is the contention this pool reaches easily. Picking the pool
    is the opposite of the default, so it cannot pass by accident."""
    red = Permanent(card=replace(_mk_creature_card("Red Ogre", 3, 3), colors=("R",)))
    p1 = PlayerState(name="P1", life=20)
    p1.color_prevention_shields = ["R"]
    p1.damage_prevention_pool = 5
    game = Game(players=[p1, PlayerState(name="P2", battlefield=[red])])
    game.interactive_seats = {0}
    calls: list[int] = []

    def hit():
        return game._deal_damage_to_player(
            p1, 3, red, then=calls.append, restart=hit
        )

    hit()

    prompt = game.pending_choices_of("effect_order", 0)
    assert len(prompt) == 1, "the affected player was asked"
    assert p1.damage_prevention_pool == 5 and p1.color_prevention_shields == ["R"], (
        "nothing was spent while the question was open"
    )
    assert calls == [], "and nothing downstream ran on a suspended event"

    pool = prompt[0].data["_keys"].index("_prevention_pool")
    game.resolve_pending_choice("effect_order", 0, option_index=pool)

    assert p1.damage_prevention_pool == 2, "the chosen shield absorbed the 3"
    assert p1.color_prevention_shields == ["R"], "the Circle was not spent"
    assert p1.life == 20
    assert calls == [0], "the re-run carried the caller's consequences with it"


@pytest.mark.cr("120.8")
def test_120_8_a_zero_damage_event_spends_nothing():
    """"If a source would deal 0 damage, it does not deal damage at all" — so no
    shield is asked and no trigger has anything to fire on."""
    game, p1 = _player_with_a_floor_and_a_pool(life=4, pool=2)

    outcome = deal_damage(
        game, {"recipient": p1, "amount": 0, "source": None, "combat": False}
    )

    assert (outcome.consumed, outcome.dealt, outcome.result) == (False, 0, 0)
    assert p1.damage_prevention_pool == 2, "a 0-damage event consumed a shield"


# ---------------------------------------------------------------------------
# 701.14 — Fight
# ---------------------------------------------------------------------------


def _fighter(name: str, power: int, toughness: int, oracle_text: str = "") -> CardDefinition:
    raw = {
        "name": name, "type_line": "Creature — Test",
        "power": str(power), "toughness": str(toughness),
    }
    return CardDefinition(
        name=name, mana_cost="{1}{R}", cmc=2.0, type_line="Creature — Test",
        oracle_text=oracle_text, colors=("R",), color_identity=("R",),
        keywords=(), produced_mana=(), raw=raw,
        power=str(power), toughness=str(toughness),
    )


_FIGHTER_TEXT = "{T}: This creature fights another target creature."


def _fight_game(mine_pt, theirs_pt):
    mine = Permanent(card=_fighter("Brawler", *mine_pt, oracle_text=_FIGHTER_TEXT))
    theirs = Permanent(card=_fighter("Bystander", *theirs_pt))
    p1 = PlayerState(name="P1", battlefield=[mine], life=20)
    p2 = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, mine, theirs


@pytest.mark.cr("701.14a")
def test_701_14a_each_fighter_deals_damage_equal_to_its_power_to_the_other():
    game, mine, theirs = _fight_game((3, 5), (2, 6))

    result = game.activate_permanent_ability(
        0, "Brawler", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    assert theirs.damage_marked == 3
    assert mine.damage_marked == 2


@pytest.mark.cr("701.14a")
def test_701_14a_both_powers_are_read_before_either_half_is_dealt():
    """A fighter killed by the first half has still dealt its own damage — so a
    1/1 and a 5/5 trade, rather than the 1/1 dying first and dealing nothing."""
    game, mine, theirs = _fight_game((1, 1), (5, 5))

    game.activate_permanent_ability(
        0, "Brawler", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert theirs.damage_marked == 1, "the dying fighter still dealt its power"
    assert not game.is_on_battlefield(mine)


@pytest.mark.cr("701.14b")
def test_701_14b_with_only_one_creature_neither_deals_damage():
    """"If one or both creatures instructed to fight are no longer on the
    battlefield … neither of them fights or deals damage." That is why the
    exchange is one instruction: two damage steps would run the first."""
    mine = Permanent(card=_fighter("Brawler", 3, 5, oracle_text=_FIGHTER_TEXT))
    p1 = PlayerState(name="P1", battlefield=[mine], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Brawler", target_player_index=1)
    game._settle()

    assert mine.damage_marked == 0


@pytest.mark.cr("701.14d")
def test_701_14d_the_damage_a_fight_deals_is_not_combat_damage():
    """It goes through the ordinary creature-damage path, so a blanket combat
    shield does not see it."""
    game, mine, theirs = _fight_game((3, 5), (2, 6))
    game.players[1].combat_damage_prevented_this_turn = True

    game.activate_permanent_ability(
        0, "Brawler", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert theirs.damage_marked == 3


# ---------------------------------------------------------------------------
# Who dealt it (CR 109.5)
# ---------------------------------------------------------------------------


@pytest.mark.cr("109.5")
def test_a_permanents_damage_is_its_controllers():
    """The easy half, and the only one that ever worked: a permanent has a
    controller, and the control seam answers CR 613 layer 2 — so a stolen
    creature's damage belongs to the thief, not to the seat it entered under."""
    creature = Permanent(card=_mk_creature_card("Pinger", 1, 1))
    p1, p2 = PlayerState(name="P1", battlefield=[creature]), PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert damage_source_seat(game, creature) == 0

    change_control(creature, 1, source=creature)
    game._sync_control()
    assert damage_source_seat(game, creature) == 1


@pytest.mark.cr("109.5")
def test_a_spells_damage_is_the_resolving_seats():
    """The half that had no answer. A spell reaches the damage paths as its
    printed ``CardDefinition`` — one object per *card*, shared by every copy in
    every deck and controlled by nobody — so reading the source cannot work
    however carefully it is done. CR 109.5 says a spell's "you" is its
    controller, and the seat currently resolving is that player.
    """
    card = replace(_mk_creature_card("Bolt", 0, 0), type_line="Instant")
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])

    assert damage_source_seat(game, card) is None, "nothing is resolving"

    game.resolving_seats.append(1)
    assert damage_source_seat(game, card) == 1


@pytest.mark.cr("109.5")
def test_a_source_with_no_controller_at_all_answers_none():
    """None, not the active player. Every predicate reading this asks "do *you*
    control it", and a guessed seat answers yes for somebody."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])

    assert damage_source_seat(game, None) is None


@pytest.mark.cr("109.5", "614.1a")
def test_every_damage_event_carries_the_seat_without_its_caller_filling_it_in():
    """Derived inside the event rather than at each entry point: there are 45
    damage call sites and a list of them is only ever as complete as the last
    card that touched one."""
    creature = Permanent(card=_mk_creature_card("Pinger", 1, 1))
    p1, p2 = PlayerState(name="P1", battlefield=[creature]), PlayerState(name="P2")
    game = Game(players=[p1, p2])
    event = {"recipient": p2, "amount": 1, "source": creature, "combat": False}

    deal_damage(game, event)

    assert event["source_seat"] == 0


# ---------------------------------------------------------------------------
# Redirection (CR 614.9) — the half of 120.4b that moves damage rather than
# removing it
# ---------------------------------------------------------------------------


def _redirect_board(*, lifelink: bool = False):
    """A player with a redirect armed onto their own creature, and the source
    whose damage it moves."""
    taker = Permanent(card=_mk_creature_card("Taker", 2, 5))
    card = _mk_creature_card("Pinger", 3, 3)
    if lifelink:
        card = replace(card, keywords=("lifelink",))
    pinger = Permanent(card=card)
    p1 = PlayerState(name="P1", battlefield=[taker])
    p2 = PlayerState(name="P2", battlefield=[pinger])
    game = Game(players=[p1, p2])
    add_redirect(p1, DamageRedirect(new_recipient=taker, source=pinger))
    return game, p1, p2, taker, pinger


@pytest.mark.cr("614.9", "120.4b")
def test_a_redirect_moves_the_damage_rather_than_preventing_it():
    """The whole distinction. The damage is still dealt, in full, by the same
    source — only its recipient changed."""
    game, p1, _p2, taker, pinger = _redirect_board()

    game._deal_damage_to_player(p1, 3, source=pinger)

    assert p1.life == 20, "the redirected damage never reached the player"
    assert taker.damage_marked == 3, "and all of it reached the creature"


@pytest.mark.cr("614.9", "702.15b", "120.3f")
def test_redirected_damage_still_gains_its_source_lifelink():
    """A redirect written as "prevent, then deal fresh damage" would lose this,
    and it is the number that says whether the engine treats CR 614.9 as a
    replacement or as a shield: the damage was *dealt*, so lifelink gains from
    it (CR 120.3f)."""
    game, p1, p2, _taker, pinger = _redirect_board(lifelink=True)
    before = p2.life

    game._deal_damage_to_player(p1, 3, source=pinger)

    assert p2.life == before + 3


@pytest.mark.cr("614.9")
def test_a_redirect_whose_new_recipient_has_left_does_nothing():
    """CR 614.9 in its own words: if the permanent is no longer on the
    battlefield when the damage would be redirected, the effect does nothing —
    which is damage dealt to the *original* recipient, not damage prevented."""
    game, p1, _p2, taker, pinger = _redirect_board()
    game.remove_from_battlefield(taker)

    game._deal_damage_to_player(p1, 3, source=pinger)

    assert p1.life == 17
    assert taker.damage_marked == 0


@pytest.mark.cr("614.9", "400.7")
def test_a_redirect_answers_only_the_source_it_named():
    """A second copy of the chosen creature's card is a different source. Two
    permanents of one card share a single ``CardDefinition``, so a redirect
    matching on the card would move damage the player never pointed at."""
    game, p1, p2, taker, pinger = _redirect_board()
    twin = Permanent(card=pinger.card)
    p2.battlefield.append(twin)

    game._deal_damage_to_player(p1, 3, source=twin)

    assert p1.life == 17, "the twin's damage is not the chosen source's"
    assert taker.damage_marked == 0


@pytest.mark.cr("614.9", "615.3")
def test_a_one_shot_redirect_moves_one_instance_and_no_more():
    """"The **next time** a source … would deal damage" (Nova Pentacle): one
    instance, not every instance for the turn."""
    game, p1, _p2, taker, pinger = _redirect_board()
    redirects_on(p1)[0].uses = 1

    game._deal_damage_to_player(p1, 2, source=pinger)
    game._deal_damage_to_player(p1, 2, source=pinger)

    assert taker.damage_marked == 2
    assert p1.life == 18


@pytest.mark.cr("616.1", "614.9")
def test_the_predicate_does_not_spend_the_record_it_is_asked_about():
    """CR 616.1 counts the applicable effects before applying one, so asking
    must not consume. Purity is what lets the choice be *asked* at all."""
    game, p1, _p2, _taker, pinger = _redirect_board()
    redirects_on(p1)[0].uses = 1
    event = {"recipient": p1, "amount": 2, "source": pinger, "combat": False}

    applicable = [c for c in damage_candidates(p1) if c.applies(game, event)]

    assert applicable, "the redirect is in contention"
    assert redirects_on(p1)[0].uses == 1, "and asking left it unspent"


# ---------------------------------------------------------------------------
# The turn's record of what each source dealt — engine/damage_ledger.py
# ---------------------------------------------------------------------------


def _ledger_board():
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", life=20)
    return Game(players=[p1, p2]), p1, p2


@pytest.mark.cr("120.4b", "120.8")
def test_the_ledger_records_what_was_dealt_and_ignores_a_zero_event():
    """CR 120.4b is the number the record keeps — what was *dealt*, before
    CR 120.4c turns it into a result. A 0-damage event is no damage event at
    all (CR 120.8), so it leaves no row: one would let a later clause join
    against a source that dealt nothing."""
    from engine.damage_ledger import ledger

    game, p1, _p2 = _ledger_board()
    deal_damage(game, {"recipient": p1, "amount": 3, "source": None, "combat": False})
    deal_damage(game, {"recipient": p1, "amount": 0, "source": None, "combat": False})

    assert [entry.amount for entry in ledger(game).entries] == [3]


@pytest.mark.cr("107.1a")
def test_a_halved_amount_rounds_the_way_the_card_says():
    """CR 107.1a: an effect that could generate a fraction says which way to
    round, and the words ride the computed amount rather than the card. Read
    through the one evaluator every computed quantity uses, so the rounding
    cannot be honoured at one return site and dropped at another."""
    from engine.handlers._common import count_from_payload
    from engine.game_types import OracleExecutionContext

    game, p1, p2 = _ledger_board()
    context = OracleExecutionContext(caster=p1, target=p2, card=None)
    context.results["damage_dealt_by_chosen_cast"] = 5

    spec = {"back_reference": "damage_dealt_by_chosen_cast"}
    assert count_from_payload(game, context, dict(spec, half="down")) == 2
    assert count_from_payload(game, context, dict(spec, half="up")) == 3
    assert count_from_payload(game, context, spec) == 5


@pytest.mark.cr("107.2")
def test_an_undetermined_amount_is_zero():
    """CR 107.2: a number that cannot be determined is 0. "The damage dealt by
    one of those sorcery spells this turn" with no such spell names nothing,
    and the reader answers 0 rather than raising or guessing."""
    from engine.handlers._common import count_from_payload
    from engine.game_types import OracleExecutionContext

    game, p1, p2 = _ledger_board()
    context = OracleExecutionContext(caster=p1, target=p2, card=None)

    spec = {"back_reference": "damage_dealt_by_chosen_cast", "half": "down"}
    assert count_from_payload(game, context, spec) == 0


@pytest.mark.cr("109.5", "400.7")
def test_two_casts_of_one_card_are_two_rows():
    """A spell's damage source is its printed card (CR 109.5), which is one
    object shared by every copy — so the record keys a spell's damage on the
    stack object, one per cast. Without that, "one of those sorcery spells"
    could not tell two copies apart."""
    from engine.damage_ledger import damage_dealt_by_cast, ledger, record_cast

    game, p1, p2 = _ledger_board()
    card = object()
    first, second = type("Item", (), {})(), type("Item", (), {})()
    first.card = second.card = card
    first.caster_index = second.caster_index = 0
    record_cast(game, first)
    record_cast(game, second)

    game.resolving_items.append(first)
    deal_damage(game, {"recipient": p2, "amount": 4, "source": card, "combat": False})
    game.resolving_items.pop()
    game.resolving_items.append(second)
    deal_damage(game, {"recipient": p2, "amount": 2, "source": card, "combat": False})
    game.resolving_items.pop()

    assert damage_dealt_by_cast(game, first) == 4
    assert damage_dealt_by_cast(game, second) == 2
    assert len(ledger(game).entries) == 2
