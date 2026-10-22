"""An AI seat casts what an effect lets it cast from outside its hand (CR 601.3).

``ai_policy.choose_cast_action`` walked the hand and the command zone, so the
second half of every flashback card (CR 702.34a), a graveyard opened by
Yawgmoth's Will or Yawgmoth's Agenda, a card an Elkin Bottle exiled and the
top of a library under a Temporal Aperture were text no AI seat reached — in a
simulated game or across the table from a human. The pool-wide statement is
``tests/regressions/test_ody_w2g2_zone_cast_census.py``; this file is the
decisions, one at a time:

* **the price** is the permission's (a flashback cost, a waiver, the card's own
  mana cost) with CR 601.2f's increases and reductions over it (CR 118.9d);
* **the order**: a permission that *ends* is spent first, one that lasts as
  long as the card stays put competes on what the spell does, and a tie goes
  to the hand;
* **the zone** reaches every gate that takes one, and the one executor reader
  (`zone_being_cast_from`) finds the card;
* **the report** counts it, so a regression to "never" is a number.
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

from engine import ai_simulator
from engine.ai_actions import (
    CastAction,
    cast_announcement,
    spell_being_cast,
    zone_being_cast_from,
)
from engine.ai_policy import (
    choose_cast_action,
    choose_combat_instant_cast_action,
    choose_land_drop,
)
from engine.ai_payment import tap_planned_lands
from engine.ai_weighed_cast import permitted_casts
from engine.card_loader import manifest_set_path
from engine.cast_permissions import grant_permission
from engine.flashback import granted_cost
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, resolve_stack

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool(set_pool, catalog_by_name):
    """Every shipped card by name, with Odyssey's (still ``measured``) on top."""
    return {**catalog_by_name, **set_pool("ODY")}


def _duel(pool, *, hand=(), graveyard=(), exile=(), mine=(), theirs=(),
          their_exile=()):
    """A two-seat game on the AI's main phase with mana costs enforced; every
    zone is given by card name."""
    forest = pool["Forest"]

    def cards(names):
        return [pool[name] for name in names]

    me = PlayerState(
        name="AI", library=[forest] * 10, hand=cards(hand),
        graveyard=cards(graveyard), exile=cards(exile),
        battlefield=[_nosick(Permanent(card=card)) for card in cards(mine)],
    )
    opp = PlayerState(
        name="Opp", library=[forest] * 10, exile=cards(their_exile),
        battlefield=[_nosick(Permanent(card=card)) for card in cards(theirs)],
    )
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = ME
    game._sync_control()
    return game


def _cast(game, action):
    """Carry *action* out the way every executor does."""
    spell = spell_being_cast(zone_being_cast_from(game, ME, action), action)
    tap_planned_lands(game, ME, action)
    result = game.cast_from_hand(ME, spell.name, **cast_announcement(action))
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return result


def _names(cards) -> list[str]:
    return [card.name for card in cards]


# --- flashback: the price and the exile ----------------------------------------

def test_a_flashback_card_is_cast_from_the_graveyard_for_its_flashback_cost(pool):
    """Firebolt is {R} from hand and "Flashback {4}{R}" from the graveyard:
    five lands, the announcement that names the flashback permission, and the
    card exiled as it leaves the stack (CR 702.34a)."""
    game = _duel(pool, graveyard=["Firebolt"], mine=["Mountain"] * 5)

    action = choose_cast_action(game, ME)

    assert action is not None and action.card_name == "Firebolt"
    assert action.from_zone == "graveyard" and action.zone_seat is None
    assert action.alternative_cost is True
    assert len(action.land_tap_indices) == 5
    assert _cast(game, action).supported
    assert game.players[OPP].life == 18
    assert _names(game.players[ME].exile) == ["Firebolt"]
    assert game.players[ME].graveyard == []
    assert not any(game.players[ME].mana_pool.values()), "paid exactly"


def test_a_flashback_cost_the_lands_cannot_pay_is_not_proposed(pool):
    """Four lands pay Firebolt's mana cost four times over and its flashback
    cost not at all. A plan that read the printed cost proposed this, was
    refused "insufficient mana for Firebolt's flashback cost", and proposed it
    again the next turn."""
    game = _duel(pool, graveyard=["Firebolt"], mine=["Mountain"] * 4)

    assert choose_cast_action(game, ME) is None


@pytest.mark.parametrize("stone_is_mine, lands", [(True, 3), (False, 7)])
def test_a_flashback_cost_is_priced_as_the_cast_path_charges_it(pool, stone_is_mine, lands):
    """"Flashback costs you pay cost {2} less. Flashback costs your opponents
    pay cost {2} more." (Catalyst Stone.) CR 601.2f over the alternative cost:
    {4}{R} is three lands under the seat's own Stone and seven under the
    other seat's — and one land short of either is no proposal."""
    stone = ["Catalyst Stone"]
    enough = _duel(
        pool, graveyard=["Firebolt"], mine=["Mountain"] * lands + (stone if stone_is_mine else []),
        theirs=[] if stone_is_mine else stone,
    )
    short = _duel(
        pool, graveyard=["Firebolt"],
        mine=["Mountain"] * (lands - 1) + (stone if stone_is_mine else []),
        theirs=[] if stone_is_mine else stone,
    )

    action = choose_cast_action(enough, ME)

    assert action is not None and action.from_zone == "graveyard"
    assert len(action.land_tap_indices) == lands
    assert _cast(enough, action).supported
    assert not any(enough.players[ME].mana_pool.values())
    assert choose_cast_action(short, ME) is None


def test_the_spell_cast_out_of_a_graveyard_is_not_a_card_in_it(pool):
    """Morgue Theft returns "target creature card from your graveyard" and has
    flashback. Cast from the graveyard it is on the stack before its target is
    chosen (CR 601.2a), so alone there it has nothing to name — the zone
    reaches the spec (`_cast_zone`) — and with a creature card beside it, it
    is cast."""
    alone = _duel(pool, graveyard=["Morgue Theft"], mine=["Swamp"] * 6)
    with_a_creature = _duel(
        pool, graveyard=["Grizzly Bears", "Morgue Theft"], mine=["Swamp"] * 6,
    )

    assert choose_cast_action(alone, ME) is None
    action = choose_cast_action(with_a_creature, ME)
    assert action is not None and action.card_name == "Morgue Theft"
    assert action.from_zone == "graveyard"
    assert _cast(with_a_creature, action).supported
    assert _names(with_a_creature.players[ME].hand) == ["Grizzly Bears"]
    assert _names(with_a_creature.players[ME].exile) == ["Morgue Theft"]


# --- the order -----------------------------------------------------------------

def test_the_hand_copy_is_cast_before_the_graveyard_copy(pool):
    """The two score alike — the score is what the spell does — and the tie
    goes to the hand, which is the {R} cast; the lands that are left then flash
    the other one back."""
    game = _duel(
        pool, hand=["Firebolt"], graveyard=["Firebolt"], mine=["Mountain"] * 6,
    )

    first = choose_cast_action(game, ME)
    assert (first.from_zone, len(first.land_tap_indices)) == ("hand", 1)
    assert _cast(game, first).supported
    second = choose_cast_action(game, ME)
    assert (second.from_zone, len(second.land_tap_indices)) == ("graveyard", 5)
    assert _cast(game, second).supported
    assert game.players[OPP].life == 16
    assert choose_cast_action(game, ME) is None


def test_a_flashback_does_not_outrank_a_better_card_in_hand(pool):
    """A permission that lasts as long as the card stays in the graveyard is
    not use-it-or-lose-it: with six lands the seat makes its Craw Wurm, and
    does not spend five of them on two damage."""
    game = _duel(
        pool, hand=["Craw Wurm"], graveyard=["Firebolt"],
        mine=["Forest"] * 2 + ["Mountain"] * 4,
    )

    action = choose_cast_action(game, ME)

    assert (action.card_name, action.from_zone) == ("Craw Wurm", "hand")


def test_a_card_on_loan_is_played_before_the_hand(pool):
    """"Until the beginning of your next upkeep, you may play that card."
    (Elkin Bottle.) The hand's Hill Giant is still there next turn and the
    Bottle's Grizzly Bears is not, so the Bears go first — where on what the
    spells do the Giant would."""
    game = _duel(
        pool, hand=["Hill Giant"], exile=["Grizzly Bears"],
        mine=["Mountain"] * 2 + ["Forest"] * 2,
    )
    bears = game.players[ME].exile[0]
    assert choose_cast_action(game, ME).card_name == "Hill Giant"

    grant_permission(
        game, player_index=ME, zone="exile", mode="play", cards=[bears],
        duration="your_next_upkeep", source_name="Elkin Bottle",
    )
    action = choose_cast_action(game, ME)

    assert (action.card_name, action.from_zone) == ("Grizzly Bears", "exile")
    assert action.alternative_cost is False
    assert _cast(game, action).supported
    assert "Grizzly Bears cast from AI's exile" in game.log
    assert game.players[ME].exile == []


# --- the other permissions -------------------------------------------------------

def test_a_card_in_another_seats_exile_is_found_there(pool):
    """"Search target opponent's library for a card and exile it. … you may
    play that card." (Grinning Totem.) The card stays in the searched
    player's exile; the action says whose pile, and the executor's one reader
    finds it."""
    game = _duel(pool, their_exile=["Grizzly Bears"], mine=["Forest"] * 2)
    bears = game.players[OPP].exile[0]
    grant_permission(
        game, player_index=ME, zone="exile", mode="play", cards=[bears],
        duration="your_next_upkeep", source_name="Grinning Totem",
        zone_player_index=OPP,
    )

    action = choose_cast_action(game, ME)

    assert (action.card_name, action.from_zone, action.zone_seat) == (
        "Grizzly Bears", "exile", OPP,
    )
    assert zone_being_cast_from(game, ME, action) is game.players[OPP].exile
    assert "zone_seat" not in cast_announcement(action)
    assert _cast(game, action).supported
    assert "Grizzly Bears cast from Opp's exile" in game.log
    assert _names(perm.card for perm in game.controlled_by(ME) if perm.is_creature) == [
        "Grizzly Bears"
    ]


def test_a_waived_cast_plans_no_mana_and_a_waived_x_is_not_proposed(pool):
    """"…you may play that card without paying its mana cost." With no land at
    all the Bears are cast; and an {X} spell under the same waiver has X = 0
    (CR 107.3b), which is a cast of nothing and is not made."""
    game = _duel(pool, exile=["Grizzly Bears", "Blaze"])
    for card in list(game.players[ME].exile):
        grant_permission(
            game, player_index=ME, zone="exile", mode="cast", cards=[card],
            free=True, duration="end_of_turn", source_name="census",
        )

    assert [(p.spell.name, p.waives_mana_cost) for p in permitted_casts(game, ME)] == [
        ("Grizzly Bears", True), ("Blaze", True),
    ]
    action = choose_cast_action(game, ME)
    assert (action.card_name, action.from_zone, action.land_tap_indices) == (
        "Grizzly Bears", "exile", (),
    )
    assert _cast(game, action).supported
    assert choose_cast_action(game, ME) is None, "Blaze for X = 0"


def test_a_granted_flashback_equal_to_the_mana_cost_announces_its_x(pool):
    """"The flashback cost is equal to its mana cost." (Recoup.) Over Blaze
    that cost is {X}{R}, an alternative cost that *includes* X, so the X is the
    one announced (CR 107.3b's other half) — sized by the lands, as from hand."""
    game = _duel(pool, graveyard=["Blaze"], mine=["Mountain"] * 4)
    blaze = game.players[ME].graveyard[0]
    grant_permission(
        game, player_index=ME, zone="graveyard", mode="cast", cards=[blaze],
        duration="end_of_turn", exile_instead=True,
        card_types=("instant", "sorcery"), cost=granted_cost(blaze, "mana_cost"),
        source_name="Recoup",
    )

    action = choose_cast_action(game, ME)

    assert (action.card_name, action.from_zone, action.x_value) == ("Blaze", "graveyard", 3)
    assert action.alternative_cost is True
    assert _cast(game, action).supported
    assert game.players[OPP].life == 17
    assert _names(game.players[ME].exile) == ["Blaze"]


def test_a_hand_cast_under_a_waiver_needs_no_mana(pool):
    """"Any player may cast creature spells with mana value 3 or less without
    paying their mana costs" (Aluren). The cast path applies the waiver
    unasked; a seat that planned the mana cost under it held a free creature
    until it had the lands."""
    without = _duel(pool, hand=["Grizzly Bears"])
    under = _duel(pool, hand=["Grizzly Bears", "Craw Wurm"], mine=["Aluren"])

    assert choose_cast_action(without, ME) is None
    action = choose_cast_action(under, ME)
    assert (action.card_name, action.from_zone, action.land_tap_indices) == (
        "Grizzly Bears", "hand", (),
    )
    assert _cast(under, action).supported
    assert choose_cast_action(under, ME) is None, "the Wurm's mana value is six"


def test_a_life_cost_is_not_paid_with_the_seats_last_point(pool):
    """"You may cast this card from your graveyard by paying 3 life and
    discarding a card in addition to paying its other costs." (Demonic
    Embrace.) CR 119.4 lets a player pay life equal to their total and the
    cast gates accept it — so the day a seat could cast from its graveyard it
    could also pay its last three life to do it. At four it still may; at
    three it does not. The same line holds a hand cast: Fumarole's "As an
    additional cost to cast this spell, pay 3 life"."""
    def embrace(life: int):
        game = _duel(
            pool, graveyard=["Demonic Embrace"], hand=["Scaled Wurm"],
            mine=["Swamp"] * 3 + ["Grizzly Bears"],
        )
        game.players[ME].life = life
        return choose_cast_action(game, ME)

    def fumarole(life: int):
        game = _duel(
            pool, hand=["Fumarole"], mine=["Swamp"] * 3 + ["Mountain"] * 2,
            theirs=["Grizzly Bears", "Forest"],
        )
        game.players[ME].life = life
        return choose_cast_action(game, ME)

    at_four = embrace(4)
    assert (at_four.card_name, at_four.from_zone) == ("Demonic Embrace", "graveyard")
    assert embrace(3) is None
    assert fumarole(4).card_name == "Fumarole"
    assert fumarole(3) is None


def test_a_land_is_played_out_of_an_opened_graveyard(pool):
    """"You may play lands and cast spells from your graveyard." (Yawgmoth's
    Agenda.) The land-drop chooser reads the zone; a land in hand wins the
    tie, and a land on loan (a permission that ends) wins it back."""
    agenda = _duel(pool, graveyard=["Forest"], mine=["Yawgmoth's Agenda"])
    with_a_hand_land = _duel(
        pool, hand=["Forest"], graveyard=["Forest"], mine=["Yawgmoth's Agenda"],
    )
    on_loan = _duel(pool, hand=["Forest"], exile=["Forest"])
    grant_permission(
        on_loan, player_index=ME, zone="exile", mode="play",
        cards=[on_loan.players[ME].exile[0]], duration="your_next_upkeep",
        source_name="Elkin Bottle",
    )

    drop = choose_land_drop(agenda, ME)
    assert (drop.card_name, drop.from_zone) == ("Forest", "graveyard")
    assert choose_land_drop(with_a_hand_land, ME).from_zone == "hand"
    assert choose_land_drop(on_loan, ME).from_zone == "exile"

    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    ai_simulator._play_land_drops(agenda, ME, report, 1, 1)
    assert report.lands_played == 1 and report.refused_casts == Counter()
    assert report.casts_from_zones == Counter({"graveyard": 1})
    assert report.log_lines == ["G1 T1 AI play Forest -> resolved [from graveyard]"]
    assert agenda.players[ME].graveyard == []


def test_the_top_of_a_library_is_cast_and_played_where_a_permanent_opens_it(pool):
    """"You may cast Goblin spells from the top of your library." (Conspicuous
    Snoop.) "…you may play lands from the top of your library." (Radha, Heart
    of Keld.) The third zone the engine's list names: a Goblin on top is cast,
    a land on top is the land drop, and a card neither permanent covers is not
    offered at all."""
    def top(source, card):
        game = _duel(pool, mine=[source, "Mountain", "Mountain"])
        game.players[ME].library.insert(0, pool[card])
        return game

    goblin = top("Conspicuous Snoop", "Goblin Arsonist")
    action = choose_cast_action(goblin, ME)
    assert (action.card_name, action.from_zone) == ("Goblin Arsonist", "library")
    assert zone_being_cast_from(goblin, ME, action) is goblin.players[ME].library
    assert _cast(goblin, action).supported
    assert goblin.players[ME].library[0].name == "Forest"
    assert "Goblin Arsonist" in [perm.card.name for perm in goblin.controlled_by(ME)]

    land = top("Radha, Heart of Keld", "Forest")
    drop = choose_land_drop(land, ME)
    assert (drop.card_name, drop.from_zone) == ("Forest", "library")

    assert permitted_casts(top("Conspicuous Snoop", "Grizzly Bears"), ME) == ()


def test_an_instant_with_flashback_is_offered_in_the_response_window(pool):
    """The web AI's priority chooser walks the same list: Moment's Peace in
    the graveyard is castable in the declare-blockers step as the hand's
    instants are — here against a Craw Wurm really attacking, because the
    policy rehearses a response and holds one that would prevent nothing."""
    game = _duel(
        pool, graveyard=["Moment's Peace"], mine=["Forest"] * 3, theirs=["Craw Wurm"],
    )
    game.active_player_index = OPP
    game.start_turn(OPP)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    wurm = next(iter(game.controlled_by(OPP)))
    declared, why = game.declare_attackers(
        OPP, [game.battlefield_index_of(wurm)], defending_player_index=ME,
    )
    assert declared, why
    game.advance_combat_phase()
    assert (game.current_turn_phase, game.current_step) == ("combat", "declare_blockers")

    action = choose_combat_instant_cast_action(game, ME)

    assert action is not None and action.card_name == "Moment's Peace"
    assert (action.from_zone, action.alternative_cost) == ("graveyard", True)
    assert len(action.land_tap_indices) == 3


# --- the executors and the report -----------------------------------------------

def test_the_simulator_casts_from_the_graveyard_and_counts_it(pool):
    """`_play_one_cast` read "the command zone, or else the hand": handed this
    action it would have indexed an empty hand. The count is the honesty
    check — zero over a pool that prints flashback is the old silence."""
    game = _duel(pool, graveyard=["Firebolt"], mine=["Mountain"] * 5)
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )

    assert ai_simulator._play_one_cast(game, ME, report, 1, 1) is True

    assert report.casts_from_zones == Counter({"graveyard": 1})
    assert report.refused_casts == Counter() and report.issues == []
    assert report.log_lines == ["G1 T1 AI cast Firebolt -> resolved [from graveyard]"]
    assert _names(game.players[ME].exile) == ["Firebolt"]


def test_a_hand_cast_is_not_counted_as_a_zone_cast(pool):
    game = _duel(pool, hand=["Firebolt"], mine=["Mountain"])
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )

    assert ai_simulator._play_one_cast(game, ME, report, 1, 1) is True

    assert report.casts_from_zones == Counter()
    assert report.log_lines == ["G1 T1 AI cast Firebolt -> resolved"]


def test_zone_being_cast_from_reads_the_zone_the_action_names(pool):
    game = _duel(pool, hand=["Forest"], graveyard=["Firebolt"], exile=["Blaze"],
                 their_exile=["Grizzly Bears"])
    me, opp = game.players

    def action(**fields):
        return CastAction(
            card_name="Probe", target_player_index=OPP, x_value=None,
            land_tap_indices=(), score=1.0, hand_index=0, **fields,
        )

    assert zone_being_cast_from(game, ME, action()) is me.hand
    assert zone_being_cast_from(game, ME, action(from_zone="graveyard")) is me.graveyard
    assert zone_being_cast_from(game, ME, action(from_zone="exile")) is me.exile
    assert zone_being_cast_from(game, ME, action(from_zone="library")) is me.library
    assert zone_being_cast_from(game, ME, action(from_zone="command")) is me.command_zone
    assert zone_being_cast_from(
        game, ME, action(from_zone="exile", zone_seat=OPP)
    ) is opp.exile


def test_no_executor_picks_the_zone_for_itself():
    """Every `spell_being_cast(…)` in the simulator and in the web layer is
    handed `zone_being_cast_from(…)`. Each of them used to spell "the command
    zone, or else the hand" out — the shape `cast_announcement` was written to
    end for the keywords, here for the pile — and two of the four read the
    hand outright."""
    root = Path(__file__).resolve().parents[2]
    found = 0
    # …and the instant-speed executor both of them share
    # (`ai_policy.cast_chosen_instant`, round 4), where the web AI seat's
    # answer to priority moved.
    policy = ast.parse((root / "engine/ai_policy.py").read_text(encoding="utf-8"))
    shared = next(
        node for node in ast.walk(policy)
        if isinstance(node, ast.FunctionDef) and node.name == "cast_chosen_instant"
    )
    trees = [
        (relative, ast.parse((root / relative).read_text(encoding="utf-8")))
        for relative in ("engine/ai_simulator.py", "web/game_flow.py")
    ] + [("engine/ai_policy.py::cast_chosen_instant", shared)]
    for relative, tree in trees:
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "spell_being_cast"
            ):
                continue
            found += 1
            zone = node.args[0]
            assert (
                isinstance(zone, ast.Call)
                and getattr(zone.func, "id", None) == "zone_being_cast_from"
            ) or (
                isinstance(zone, ast.Name) and zone.id == "cast_zone"
            ), (relative, node.lineno)
        # ...and where a site binds the pile to a name first, the name is that
        # function's result.
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and any(getattr(target, "id", None) == "cast_zone" for target in node.targets)
            ):
                assert (
                    isinstance(node.value, ast.Call)
                    and getattr(node.value.func, "id", None) == "zone_being_cast_from"
                ), (relative, node.lineno)
    assert found == 4, f"expected the four executor sites, found {found}"


# --- the seam: no chooser can read the hand by leaving a keyword out -----------

#: Engine questions about a cast that take the zone it leaves. A call to one
#: of them from `ai_policy` without ``from_zone=`` is asking about a cast from
#: hand, whatever is being weighed.
_ZONE_QUESTIONS = {
    "derive_cast_spec", "cast_target_spec", "no_legal_cast_target_refusal",
    "cast_prohibition", "cast_target_requirement_refusal",
    "_unpayable_additional_cost", "_additional_cost_x_ceiling",
    "cast_announces_x", "cast_target_refusal", "cast_stack_target_refusal",
    "cast_cost_offers", "optional_x_offers", "targeting_ban_refusal",
    "stray_stack_target_refusal",
}


def test_every_cast_question_the_policy_asks_names_the_zone():
    """The permission being weighed is one context variable read at one seam
    (`ai_actions._cast_zone`); this holds it, in every module of the policy
    (`policy_modules`, the mode guard's own reading of which those are). The
    mode's twin is
    ``test_ai_mode_chooser.test_every_cast_question_the_policy_asks_names_the_mode``."""
    from tests.ai.test_ai_mode_chooser import policy_modules

    asked = 0
    missing = []
    for path in policy_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name not in _ZONE_QUESTIONS:
                continue
            asked += 1
            if "from_zone" not in {keyword.arg for keyword in node.keywords}:
                missing.append((path.name, name, node.lineno))
    assert asked >= 12, f"the scan found only {asked} zone questions"
    assert missing == []


# --- a seeded game ---------------------------------------------------------------

#: Flashback cards a two-colour limited deck can cast twice: cheap, and across
#: two colours so either seat's deck holds some.
_PINNED = ["Firebolt", "Chatter of the Squirrel", "Call of the Herd", "Volcanic Spray"]


@pytest.mark.slow
def test_a_simulated_odyssey_game_casts_a_spell_from_a_graveyard():
    """The Phase 5 instrument reaches the mechanic: with flashback cards
    pinned, a seeded run casts at least one from a graveyard — **a floor of
    one, never a count**, because a count over a seeded game is a statement
    about every other card in the set — the card is exiled, and no cast of a
    pinned card is refused and none is left on the stack as a step ends. And
    the seed reproduces the run."""
    path = manifest_set_path("ODY", include_measured=True)

    def run():
        return ai_simulator.run_ai_simulation(
            path, games=3, seed=2024, max_turns=14, required_cards=_PINNED,
        )

    report = run()

    assert report.casts_from_zones["graveyard"] >= 1
    assert any(" [from graveyard]" in line for line in report.log_lines)
    assert any(
        "cast for its flashback cost" in line for line in report.log_lines
    )
    assert any(
        "was exiled instead of going to the graveyard" in line
        for line in report.log_lines
    )
    # Only what names a pinned card: what the rest of the set does in a seeded
    # game is the rest of the set's business.
    assert [
        why for why in report.refused_casts if why.split(":")[0] in _PINNED
    ] == []
    assert [
        what for what in report.steps_left_owing
        if any(name in what for name in _PINNED)
    ] == []
    assert run().log_lines == report.log_lines
