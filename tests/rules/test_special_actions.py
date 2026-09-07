"""CR 116 — special actions: what a player may do with priority, off the stack.

CR 116.1 defines them as "actions a player may take when they have priority
that don't use the stack", and CR 116.2 lists twelve. This engine implements
four: the land drop (CR 116.2a), which predates the seam and still lives on the
play path; CR 116.2e, the only rule in the whole CR that names a card; and the
two offers a **permanent** makes — 116.2c's "to end a continuous effect"
(Tempest's Licids) and 116.2d's "to ignore the effect from that ability for a
duration" (Volrath's Curse).

The reason the second one needed a seam at all is the first clause of CR 116.1.
No stack means no instruction to compile and no handler to dispatch, so a card
whose remaining text is a keyword line and an upkeep trigger reported
*unsupported* however well the action worked — the compiler had nowhere to put
it. `engine/special_actions.py` is the table, and the support gate reads that
same table, which is what closes the gap.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog, load_cards, manifest_set_path
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack
from engine.special_actions import (available_special_actions,
                                    special_action_line,
                                    special_action_refusal,
                                    special_actions_for, take_special_action)

_WTH = {
    c.name: c
    for c in load_cards(manifest_set_path("WTH", include_measured=True))
}
_CATALOG = {c.name: c for c in load_catalog()}


def _duel(hand=()):
    p1, p2 = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2


@pytest.mark.cr("116.1", "116.2e", "116.3")
def test_116_2e_discarding_circling_vultures_is_a_special_action():
    """"One card (Circling Vultures) has the ability 'You may discard Circling
    Vultures any time you could cast an instant.' Doing so is a special action.
    A player can take such an action any time they have priority."

    Three properties, one per clause, and each is a way this could be built
    wrong:

    * it does not use the stack (CR 116.1), so nothing is put on it and nothing
      resolves;
    * it needs priority and nothing else (CR 116.2e) — *not* CR 601.3d's
      sorcery window, and not `cast_timing.casts_at_instant_speed`, which
      answers about a card being **cast** and nothing here is cast;
    * the player has priority again afterwards (CR 116.3), so the action must
      not pass or advance a step.
    """
    assert special_action_line(
        "You may discard this card any time you could cast an instant."
    ) == "discard_from_hand"
    assert special_actions_for(_WTH["Circling Vultures"]) == ("discard_from_hand",)

    game, p1, _p2 = _duel([_WTH["Circling Vultures"], _CATALOG["Grizzly Bears"]])
    game.priority_player_index = 0
    assert available_special_actions(game, 0) == [
        {"hand_index": 0, "name": "Circling Vultures", "kind": "discard_from_hand"}
    ]

    assert take_special_action(
        game, 0, _WTH["Circling Vultures"], "discard_from_hand"
    ) is None

    assert [c.name for c in p1.hand] == ["Grizzly Bears"]
    assert [c.name for c in p1.graveyard] == ["Circling Vultures"]
    assert game.stack == [], "CR 116.1: a special action does not use the stack"
    assert game.has_priority(0), "CR 116.3: and the player keeps priority"


@pytest.mark.cr("116.1", "116.2e")
def test_116_1_a_special_action_needs_priority_and_the_card_in_hand():
    """The two halves of "when they have priority", asked of the one gate the
    engine and the web layer both read — an action the client offers and the
    engine refuses is a button that does nothing.

    The opponent's answer is the one that matters: the card is in somebody's
    hand and the ability is real, and the seat that may take it is the seat
    holding it.
    """
    game, _p1, _p2 = _duel([_WTH["Circling Vultures"]])
    vultures = _WTH["Circling Vultures"]

    game.priority_player_index = 1
    assert special_action_refusal(game, 0, vultures, "discard_from_hand") == (
        "A does not have priority"
    )
    assert available_special_actions(game, 0) == []

    game.priority_player_index = 0
    assert special_action_refusal(game, 0, vultures, "discard_from_hand") is None
    assert special_action_refusal(game, 1, vultures, "discard_from_hand") == (
        "Circling Vultures is not in B's hand"
    )
    assert available_special_actions(game, 1) == []


@pytest.mark.cr("116.2e", "400.3")
def test_116_2e_a_discard_takes_exactly_one_copy_of_a_shared_definition():
    """A deck repeats one immutable ``CardDefinition`` per copy, so an identity
    *filter* over the hand removes every copy where the caller then files one.
    That class has deleted cards from this game before
    (`tests/engine/test_hand_removal_seam.py`), and the graveyard side is
    CR 614's event rather than a list append — a bare append skips every
    replacement over "if a card would be put into your graveyard".
    """
    vultures = _WTH["Circling Vultures"]
    game, p1, _p2 = _duel([vultures, vultures])
    game.priority_player_index = 0

    take_special_action(game, 0, vultures, "discard_from_hand")

    assert [c.name for c in p1.hand] == ["Circling Vultures"]
    assert [c.name for c in p1.graveyard] == ["Circling Vultures"]


@pytest.mark.cr("116.1")
def test_116_1_a_special_action_makes_its_card_supported():
    """The gap the seam closes, asserted rather than described.

    Circling Vultures' other two lines both worked — flying, and an upkeep
    trigger that compiles to a real ``may``/``otherwise`` pair — and the card
    reported unsupported for the one sentence that produces no instruction
    *by rule*. A support gate that only counts instructions cannot admit a
    CR 116 action at all, which is why it reads this table.
    """
    program = compile_card_oracle(_WTH["Circling Vultures"])

    assert program.supported, program.reason
    assert [t.supported for t in program.triggered_abilities] == [True]


# --- W2G1: CR 116.2c / 116.2d — the offers a *permanent* makes ---------------

from engine.auras import (IGNORED_RESTRICTIONS, attach_aura,  # noqa: E402
                          aura_restriction_active)
from engine.card_loader import manifest_set_path as _w2g1_set_path  # noqa: E402
from engine.models import Permanent  # noqa: E402
from engine.special_actions import (  # noqa: E402
    available_permanent_special_actions, permanent_special_action_refusal,
    permanent_special_action_sentence, take_permanent_special_action)

_W2G1_TMP = {
    c.name: c
    for c in load_cards(_w2g1_set_path("TMP", include_measured=True))
}


def _w2g1_perm(card):
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w2g1_board(mine, theirs=(), pool=None):
    p1 = PlayerState(name="A", battlefield=list(mine), life=20,
                     mana_pool=dict(pool or {}))
    p2 = PlayerState(name="B", battlefield=list(theirs), life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.priority_player_index = 0
    game._sync_control()
    game._refresh_dynamic_creatures()
    return game, p1, p2


@pytest.mark.cr("116.1", "116.2c", "116.3")
def test_116_2c_a_licid_may_pay_to_end_the_effect_its_own_ability_made():
    """"Some effects allow a player to take an action at a later time, usually
    to end a continuous effect … Doing so is a special action."

    Tempest's Licids are that sentence printed on a card: "{R}, {T}: This
    creature loses this ability and becomes an Aura enchantment with enchant
    creature. Attach it to target creature. **You may pay {R} to end this
    effect.**"

    Three properties, one per clause, each a way this could be built wrong:

    * no stack (CR 116.1) — nothing is put on it and nothing resolves, which is
      why a ``PendingChoice`` would be the wrong shape: that queue is a decision
      somebody *owes*, and this one may never be taken at all;
    * priority and nothing else (CR 116.2c's "any time they have priority");
    * "for as long as the effect allows it" — the offer stands exactly while
      the effect does, so it is read off the **effect's** record and not off the
      card, whose sentence the same resolution took away with the ability.
    """
    assert permanent_special_action_sentence(
        "You may pay {R} to end this effect."
    ) == ("end_own_continuous_effect", {"R": 1})

    licid = _w2g1_perm(_W2G1_TMP["Enraging Licid"])
    bear = _w2g1_perm(_W2G1_TMP["Trained Armodon"])
    game, p1, _p2 = _w2g1_board([licid, bear], pool={"R": 2})

    # Before the ability has run there is no effect, so there is no offer.
    assert available_permanent_special_actions(game, 0) == []

    game.activate_permanent_ability(
        0, "Enraging Licid", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    resolve_stack(game)
    # Resolving the stack leaves nobody holding priority in this rig; the offer
    # is about the moment a player *has* it (CR 116.2c), so the test says which.
    game.priority_player_index = 0

    assert available_permanent_special_actions(game, 0) == [
        {"permanent_id": licid.permanent_id, "name": "Enraging Licid",
         "kind": "end_own_continuous_effect"}
    ]
    assert permanent_special_action_refusal(
        game, 1, licid, "end_own_continuous_effect"
    ) == "Enraging Licid is not offering that to B"

    depth = len(game.stack)
    assert take_permanent_special_action(
        game, 0, licid, "end_own_continuous_effect"
    ) is None
    assert len(game.stack) == depth, "CR 116.1: a special action uses no stack"
    assert game.priority_player_index == 0, "CR 116.3"
    assert p1.mana_pool["R"] == 1

    assert licid.is_creature and not licid.has_type("aura")
    assert available_permanent_special_actions(game, 0) == [], (
        "the offer stands only while the effect does (CR 116.2c)"
    )


@pytest.mark.cr("205.1a", "613.1d", "613.1f")
def test_205_1a_a_licid_stops_being_a_creature_and_loses_its_own_ability():
    """"…becomes an **Aura enchantment** with enchant creature."

    CR 205.1a: a sentence that *sets* a card type replaces the ones the object
    had, and the subtypes correlated with a removed type go with it — so the
    Licid stops being a creature and stops being a Licid. CR 613 layer 6 is the
    other half of the same sentence: it loses the ability that ran, which is
    what stops it being activated again from the enchantment it has become.

    Both are contributions rather than a rewritten card, which is what lets the
    CR 116.2c offer above undo them by dropping records.
    """
    licid = _w2g1_perm(_W2G1_TMP["Quickening Licid"])
    bear = _w2g1_perm(_W2G1_TMP["Trained Armodon"])
    game, _p1, _p2 = _w2g1_board([licid, bear], pool={"W": 2})

    game.activate_permanent_ability(
        0, "Quickening Licid", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    resolve_stack(game)

    assert not licid.is_creature
    assert not licid.has_type("licid")
    assert licid.has_type("enchantment") and licid.has_type("aura")
    assert "loses this ability" not in (licid.effective_card.oracle_text or "")
    assert game._has_keyword(bear, "first strike"), (
        "CR 303.4m: the Aura's own line reads the permanent it is attached to"
    )


@pytest.mark.cr("116.1", "116.2d", "514.2")
def test_116_2d_volraths_curse_can_be_ignored_for_a_turn_by_a_sacrifice():
    """"Some effects from static abilities allow a player to take an action to
    ignore the effect from that ability for a duration."

    Volrath's Curse: "That creature's controller may sacrifice a permanent of
    their choice for that player to ignore this effect until end of turn."

    The offer is made to somebody who does **not** control the permanent making
    it, which is why the seat rides the offer; its price is a permanent rather
    than mana, which is why the price does too. CR 514.2 ends it: the suspension
    is an until-end-of-turn record swept by the cleanup step beside the three
    other channels that carry that duration.
    """
    curse = _w2g1_perm(_W2G1_TMP["Volrath's Curse"])
    victim = _w2g1_perm(_W2G1_TMP["Trained Armodon"])
    spare = _w2g1_perm(_W2G1_TMP["Trained Armodon"])
    game, _p1, p2 = _w2g1_board([curse], [victim, spare])
    attach_aura(curse, victim)
    game._refresh_dynamic_creatures()

    assert aura_restriction_active(victim, "cant_attack")
    assert permanent_special_action_refusal(
        game, 0, curse, "ignore_attached_static_until_eot"
    ) == "Volrath's Curse is not offering that to A"

    game.priority_player_index = 1
    assert available_permanent_special_actions(game, 1) == [
        {"permanent_id": curse.permanent_id, "name": "Volrath's Curse",
         "kind": "ignore_attached_static_until_eot"}
    ]
    assert take_permanent_special_action(
        game, 1, curse, "ignore_attached_static_until_eot", sacrificed=spare
    ) is None

    assert [c.name for c in p2.graveyard] == ["Trained Armodon"]
    assert not aura_restriction_active(victim, "cant_attack")
    assert not aura_restriction_active(victim, "cant_block")
    assert available_permanent_special_actions(game, 1) == [], (
        "one turn's relief, bought once"
    )

    game.resolve_cleanup_step(1)
    assert curse.metadata.get(IGNORED_RESTRICTIONS) is None
    assert aura_restriction_active(victim, "cant_attack"), "CR 514.2"


@pytest.mark.cr("602.5", "605.1a")
def test_605_1a_volraths_curse_shuts_off_mana_abilities_and_faiths_fetters_does_not():
    """Two printings of one clause, and the difference is a printed exception.

    Faith's Fetters says "…can't be activated **unless they're mana
    abilities**" and Volrath's Curse does not, so a Llanowar Elves under the
    Curse cannot tap for mana and one under the Fetters can. Read as one
    restriction the Curse would be an ability that works more often than the
    card allows — silent, and in the player's favour.
    """
    curse = _w2g1_perm(_W2G1_TMP["Volrath's Curse"])
    elves = _w2g1_perm(_CATALOG["Llanowar Elves"])
    game, _p1, p2 = _w2g1_board([curse], [elves])
    attach_aura(curse, elves)
    game._refresh_dynamic_creatures()

    refused = game.activate_permanent_ability(1, "Llanowar Elves", ability_index=0)
    assert not refused.supported
    assert p2.mana_pool.get("G", 0) == 0

    fetters = _w2g1_perm(_CATALOG["Faith's Fetters"])
    other = _w2g1_perm(_CATALOG["Llanowar Elves"])
    game, _p1, p2 = _w2g1_board([fetters], [other])
    attach_aura(fetters, other)
    game._refresh_dynamic_creatures()

    allowed = game.activate_permanent_ability(1, "Llanowar Elves", ability_index=0)
    resolve_stack(game)
    assert allowed.supported, allowed.details
    assert p2.mana_pool.get("G", 0) == 1


# --- EXO Phase 5: CR 116.3's other half — the check before priority returns ---

_EXO_PHASE5 = {
    c.name: c
    for c in load_cards(_w2g1_set_path("EXO", include_measured=True))
}


@pytest.mark.cr("116.3", "704.3", "613.1b")
def test_704_3_a_special_action_checks_state_based_actions_before_priority():
    """"If a player takes a special action, that player receives priority
    afterward." (CR 116.3.) "Whenever a player would get priority … the game
    checks for any of the listed conditions for state-based actions." (704.3.)

    Found at Exodus's promotion smoke test, on **Dominating Licid** — the one
    Licid whose second line is a control change. Ending the effect stops the
    permanent being an Aura at once, but *who controls the enchanted creature*
    is a CR 613 layer-2 contribution the sweep in ``mixins/game_ending`` derives
    from the attachment, so it needs a check to notice the attachment is gone.
    ``phase_steps.pass_priority`` runs that check after a **resolution**, and
    CR 116.1 says a special action is not one — so with nothing here the player
    paid {U}, got their Licid back, and kept the creature until some unrelated
    spell happened to resolve. They could attack with it first.

    Asserted with no ``check_state_based_actions()`` of its own, which is the
    whole point: the action is the last thing the test does.
    """
    licid = _w2g1_perm(_EXO_PHASE5["Dominating Licid"])
    bear = _w2g1_perm(_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w2g1_board([licid], [bear], pool={"U": 1})
    assert game.controller_index_of(bear) == 1

    game.activate_permanent_ability(
        0, "Dominating Licid", ability_index=0,
        target_permanent_ids=[bear.permanent_id], target_player_index=1,
    )
    resolve_stack(game)
    game.check_state_based_actions()
    game.priority_player_index = 0
    assert game.controller_index_of(bear) == 0, "the Aura's layer-2 contribution"

    assert take_permanent_special_action(
        game, 0, licid, "end_own_continuous_effect"
    ) is None

    assert licid.is_creature and not licid.has_type("aura")
    assert game.controller_index_of(bear) == 1, (
        "CR 704.3: the contribution is swept before the taker gets priority back"
    )
    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly Bears"]
