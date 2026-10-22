"""A cast is measured before it is proposed: which target, which seat, whether
at all.

The behaviour behind the two censuses beside this file
(``test_ai_mode_chooser_census.py``, ``test_ai_idle_cast_census.py``), one
defect at a time and on boards small enough to read. The policy carries a
candidate cast out on a scratch copy of the game (``ai_rehearsal.rehearse``)
and proposes it only if the engine takes it, it changes something, and it
leaves its caster no worse off — and where a cast may name one of several
things, each is a different cast and the one that does most is the one named.

Every assertion here is on the board after the real cast, never on a score.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine import ai_rehearsal
from engine.ai_actions import cast_announcement
from engine.ai_policy import choose_cast_action, choose_combat_instant_cast_action
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from tests.helpers import _mk_card, _mk_creature_card, resolve_stack

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


def _table(pool, hand, mine=(), theirs=(), *, their_hand=(), life=(20, 20)) -> Game:
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=list(hand), library=[forest] * 20, life=life[0]),
        PlayerState(name="Opp", hand=list(their_hand), library=[forest] * 20, life=life[1]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for seat, cards in ((ME, mine), (OPP, theirs)):
        for card in cards:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, seat)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game


def _cast(game, action) -> None:
    result = game.cast_from_hand(ME, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    # What the resolution asked of a seat nobody is playing (which cards a
    # discard takes), then CR 704.3.
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()


def _names(game, seat) -> list:
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def _instant(name, text):
    return _mk_card(name=name, mana_cost="{B}", type_line="Instant", oracle_text=text, colors=("B",))


# --- which target ------------------------------------------------------------


def test_a_shrink_is_aimed_at_the_creature_it_kills(pool):
    """"Target creature gets -2/-2 until end of turn" with a 4/4 and a 2/2
    across the table: the 4/4 was named, being first in battlefield order,
    and was a 4/4 again at the end of the turn. Each legal target is a
    different cast; the one that leaves a creature dead is the one made."""
    shrink = _instant("Wither Probe", "Target creature gets -2/-2 until end of turn.")
    game = _table(
        pool, [shrink],
        theirs=[_mk_creature_card("Their Giant", 4, 4), _mk_creature_card("Their Bear", 2, 2)],
    )
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Wither Probe"
    _cast(game, action)
    assert _names(game, OPP) == ["Their Giant"]
    assert "Their Bear" in [card.name for card in game.players[OPP].graveyard]


def test_removal_takes_the_dearest_thing_it_may_name(pool):
    """Terror with a 1/1 in front of a 5/5: the first legal creature was the
    1/1."""
    game = _table(
        pool, [pool["Terror"]],
        theirs=[_mk_creature_card("Their Squire", 1, 1), _mk_creature_card("Their Wurm", 5, 5)],
    )
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Terror"
    _cast(game, action)
    assert _names(game, OPP) == ["Their Squire"]


def test_any_target_damage_kills_a_creature_until_it_can_kill_the_player(pool):
    """Lightning Bolt, "any target": three damage is worth a 3/3 more than it
    is worth three of twenty life — and is worth the game at three life."""
    bolt = pool["Lightning Bolt"]
    game = _table(pool, [bolt], theirs=[_mk_creature_card("Their Ogre", 3, 3)])
    action = choose_cast_action(game, ME)
    _cast(game, action)
    assert _names(game, OPP) == [] and game.players[OPP].life == 20

    game = _table(pool, [bolt], theirs=[_mk_creature_card("Their Ogre", 3, 3)], life=(20, 3))
    action = choose_cast_action(game, ME)
    _cast(game, action)
    assert game.players[OPP].life == 0 and _names(game, OPP) == ["Their Ogre"]

    # ...and a creature it cannot kill is not worth the card: the face.
    game = _table(pool, [bolt], theirs=[_mk_creature_card("Their Wall", 0, 6)])
    action = choose_cast_action(game, ME)
    _cast(game, action)
    assert game.players[OPP].life == 17


# --- whose board -------------------------------------------------------------


def test_swords_to_plowshares_is_never_aimed_at_its_casters_own_creature(pool):
    """Seen once in a browser. The card compiles to a kind with no ``targets``
    payload, so nothing read a side for it; the seat came from the words
    "gains life" in its text, which scored the caster, and the caster's own
    creature was the first legal one there — with an opposing creature on the
    table."""
    swords, bears = pool["Swords to Plowshares"], pool["Grizzly Bears"]
    game = _table(pool, [swords], mine=[bears], theirs=[bears])
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Swords to Plowshares"
    _cast(game, action)
    assert _names(game, ME) == ["Grizzly Bears"] and _names(game, OPP) == []
    assert game.players[OPP].life == 22

    alone = _table(pool, [swords], mine=[bears])
    assert choose_cast_action(alone, ME) is None


def test_a_sweeper_is_not_cast_onto_a_board_that_is_all_its_casters(pool):
    wrath = pool["Wrath of God"]
    ogre = _mk_creature_card("Ogre", 3, 3)
    assert choose_cast_action(_table(pool, [wrath], mine=[ogre, ogre]), ME) is None
    assert choose_cast_action(_table(pool, [wrath]), ME) is None

    game = _table(pool, [wrath], mine=[ogre], theirs=[ogre, ogre])
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Wrath of God"
    _cast(game, action)
    assert _names(game, ME) == [] and _names(game, OPP) == []


# --- whether at all ----------------------------------------------------------


def test_a_discard_is_not_cast_at_an_empty_hand(pool):
    rot = pool["Mind Rot"]
    assert choose_cast_action(_table(pool, [rot]), ME) is None

    forest = pool["Forest"]
    game = _table(pool, [rot], their_hand=[forest, forest, forest])
    action = choose_cast_action(game, ME)
    assert action is not None and action.target_player_index == OPP
    _cast(game, action)
    assert len(game.players[OPP].hand) == 1


def test_the_lands_that_pay_are_not_mistaken_for_something_the_spell_did(pool):
    """The finished cast is rehearsed as the executor will make it, lands
    tapped and all — and compared with a table on which the same lands are
    tapped. Compared with one on which they were not, every paid-for cast
    "changed something" (three Swamps), and a discard at an empty hand was a
    cast again the moment mana was real."""
    rot, swamp, forest = pool["Mind Rot"], pool["Swamp"], pool["Forest"]
    game = _table(pool, [rot], mine=[swamp] * 3)
    game.enforce_mana_costs = True
    assert choose_cast_action(game, ME) is None

    game = _table(pool, [rot], mine=[swamp] * 3, their_hand=[forest, forest])
    game.enforce_mana_costs = True
    action = choose_cast_action(game, ME)
    assert action is not None and len(action.land_tap_indices) == 3
    assert all(not land.tapped for land in game.controlled_by(ME)), (
        "the rehearsal tapped the copy's lands, not the game's"
    )


def test_a_ritual_is_a_cast(pool):
    """Dark Ritual changes nothing but a mana pool, and a mana pool is what
    every cast changes by being paid for. The two are told apart across the
    resolution: mana that is there after it and was not before is mana the
    spell made."""
    game = _table(pool, [pool["Dark Ritual"]], mine=[pool["Swamp"]])
    game.enforce_mana_costs = True
    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Dark Ritual"


def test_a_player_nothing_distinguishes_is_the_opponent_unless_the_effect_is_a_gift(pool):
    """"Tap all lands target player controls" measures the same at either
    seat — a tapped land is no worse a land — and the tie was the caster's.
    Where the seats measure alike the effect's family says whose it is: the
    opponent's, unless it is a gift (a shield, an untap)."""
    from engine.ai_target_sides import _SEAT_GIFT_KINDS, spell_seat_side
    from engine.handlers import EFFECT_HANDLERS

    assert _SEAT_GIFT_KINDS <= set(EFFECT_HANDLERS)
    assert spell_seat_side(pool["Mana Short"]) == "opponent"
    assert spell_seat_side(pool["Early Harvest"]) == "you"

    island = pool["Island"]
    # In the caster's own main phase the opponent's lands untap in its own
    # untap step (CR 502.3) before they could have been used, and a cast that
    # leaves nothing behind is held (`ai_rehearsal.untap_for_the_next_turn`);
    # in the opponent's turn they stay tapped through the caster's.
    own_turn = _table(pool, [pool["Mana Short"]], mine=[island, island], theirs=[island, island])
    assert choose_cast_action(own_turn, ME) is None
    game = _table(pool, [pool["Mana Short"]], mine=[island, island], theirs=[island, island])
    game.active_player_index = OPP
    action = choose_cast_action(game, ME)
    assert action is not None and action.target_player_index == OPP
    _cast(game, action)
    assert all(land.tapped for land in game.controlled_by(OPP))
    assert not any(land.tapped for land in game.controlled_by(ME))


def test_donate_and_kor_chant_are_held_where_they_only_cost(pool):
    """Donate hands a permanent across the table; Kor Chant with no source of
    damage in play redirects nothing. Both were cast whenever they could be."""
    bears = pool["Grizzly Bears"]
    assert choose_cast_action(_table(pool, [pool["Donate"]], mine=[bears]), ME) is None
    assert choose_cast_action(
        _table(pool, [pool["Kor Chant"]], mine=[bears, bears]), ME
    ) is None


def test_winnow_destroys_the_permanent_that_has_a_twin(pool):
    """"Destroy target nonland permanent if another permanent with the same
    name is on the battlefield. Draw a card." Any nonland permanent is a legal
    target; the one named is the one the guard holds for."""
    winnow = pool["Winnow"]
    ogre = _mk_creature_card("Their Ogre", 3, 3)
    wurm = _mk_creature_card("Their Wurm", 6, 6)
    game = _table(pool, [winnow], theirs=[wurm, ogre, ogre])
    action = choose_cast_action(game, ME)
    assert action is not None
    _cast(game, action)
    assert _names(game, OPP) == ["Their Ogre", "Their Wurm"]
    assert len(game.players[ME].hand) == 1  # the card it draws


def test_goblin_game_is_cast_from_ahead_and_held_from_behind(pool):
    """It had no valuation and was cast whenever it could be. Both seats'
    hidden numbers are the policy's own (``choose_secret_number``), so what
    the cast would do to each life total is known before it is made."""
    game_card = pool["Goblin Game"]
    ahead = _table(pool, [game_card], life=(20, 4))
    assert choose_cast_action(ahead, ME) is not None
    behind = _table(pool, [game_card], life=(4, 20))
    assert choose_cast_action(behind, ME) is None


# --- an instant, in the window it is for -------------------------------------


def _attacking(pool, hand, mine, theirs=()) -> Game:
    """Seat 0's own declare-blockers step: its creatures attacking, no block
    declared."""
    game = _table(pool, hand, mine=mine, theirs=theirs)
    game.start_turn(ME)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step
    attackers = [
        slot for slot, permanent in enumerate(game.controlled_by(ME))
        if permanent.is_creature
    ]
    declared, why = game.declare_attackers(ME, attackers, defending_player_index=OPP)
    assert declared, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step
    declared, why = game.declare_blockers(OPP, {})
    assert declared, why
    return game


def test_hearth_charm_pumps_attackers_when_there_are_attackers(pool):
    """"Attacking creatures get +1/+0 until end of turn" was the bullet an AI
    seat cast in its main phase, with nothing attacking, on a tie the printed
    order broke. It is not cast there now; here is where it is."""
    charm = pool["Hearth Charm"]
    bear = _mk_creature_card("Own Bear", 3, 3)
    main_phase = _table(pool, [charm], mine=[bear, bear])
    action = choose_cast_action(main_phase, ME)
    assert action is None or action.mode_index != 1

    game = _attacking(pool, [charm], mine=[bear, bear])
    action = choose_combat_instant_cast_action(game, ME)
    assert action is not None and action.mode_index == 1
    result = game.queue_from_hand(ME, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    assert [p.effective_power for p in game.controlled_by(ME)] == [4, 4]


def test_a_response_that_changes_nothing_is_held(pool):
    """The web AI's priority window: a pump with no fight to decide and a
    shield with nothing coming were cast at the first spell that went on the
    stack — their base score cleared the bar by itself."""
    growth = pool["Giant Growth"]
    bear = _mk_creature_card("Own Bear", 2, 2)
    game = _table(pool, [growth], mine=[bear], their_hand=[pool["Grizzly Bears"]])
    game.start_turn(OPP)
    game._close_current_priority_step()
    queued = game.queue_from_hand(OPP, "Grizzly Bears")
    assert queued.supported, queued.details
    assert choose_combat_instant_cast_action(game, ME) is None


# --- the rehearsal itself ----------------------------------------------------


def test_a_rehearsal_leaves_the_game_and_its_dice_exactly_as_they_were(pool):
    """The copy is the only thing a rehearsal touches: the game's zones, its
    log and the random sequence the real cast will draw on are as they were —
    which is what lets a seed still reproduce a run."""
    import random

    bolt = pool["Lightning Bolt"]
    game = _table(pool, [bolt], theirs=[_mk_creature_card("Their Ogre", 3, 3)])
    before = ai_rehearsal.position_digest(game)
    log = list(game.log)
    random.seed(99)
    expected = random.Random(99).random()
    assert choose_cast_action(game, ME) is not None
    assert random.random() == expected
    assert ai_rehearsal.same_position(before, ai_rehearsal.position_digest(game))
    assert game.log == log
    assert not ai_rehearsal.rehearsing()


def test_no_rehearsal_is_run_part_way_through_a_resolution(pool):
    """A table that owes the rest of a resolution holds it as continuations —
    closures over the game they were made on — so a copy of it would run them
    on the original. Asked there, the policy is told nothing and scores the
    spell as it would one it could not read."""
    bolt = pool["Lightning Bolt"]
    game = _table(pool, [bolt])
    game.resolving_seats.append(ME)
    try:
        assert ai_rehearsal.mid_resolution(game)
        assert ai_rehearsal.rehearse(game, ME, lambda table: None) is None
    finally:
        game.resolving_seats.pop()
