"""Legions creatures, W1G4 onward (W1G1-W1G3 are in test_lgn_creatures.py).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("LGN")` / `set_cards("LGN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
#
# Morph's second half: X in a morph cost (CR 702.37f, 107.3d) and the
# "When this creature is turned face up" triggers that needed more than
# Onslaught's seam. Every card is turned face up through the special action
# (``take_permanent_special_action``) on a board built by hand, its trigger
# resolved, and the board, zones and log read.

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.face_down import face_down_card as _w1g4_face_down_card
from engine.face_down import is_face_down as _w1g4_is_face_down
from engine.models import Permanent as _w1g4_Permanent
from engine.special_actions import (
    available_permanent_special_actions as _w1g4_offers,
    take_permanent_special_action as _w1g4_take,
)
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_table(set_pool, mine=(), theirs=(), *, interactive=False):
    """A two-seat game in seat 0's main phase, seat 0 holding priority.

    Each entry of *mine* / *theirs* is a card name, looked up in LGN then the
    shipped sets; ``"fd:<name>"`` puts that card onto the battlefield face down
    (CR 708.2a). Mana is enforced, so a special action pays from the lands.
    """
    pools = [set_pool(code) for code in ("LGN", "ONS", "LEA")]

    def card(name):
        for pool in pools:
            if name in pool:
                return pool[name]
        raise KeyError(name)

    game = _w1g4_Game(players=[
        _w1g4_PlayerState(name="P1", life=20), _w1g4_PlayerState(name="P2", life=20),
    ])
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(0)
    placed = []
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            printed = (
                _w1g4_face_down_card(card(name[3:])) if name.startswith("fd:")
                else card(name)
            )
            permanent = _w1g4_Permanent(card=printed)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.append(permanent)
    game.start_priority_window(0)
    return game, placed


def _w1g4_settle(game):
    """Drain the stack and answer whatever a default seat owes, CR 704
    checked between — the board a player would see once nothing is left."""
    for _ in range(20):
        if game.pending_choices:
            game.auto_resolve_pending_choices()
            continue
        if not game.stack:
            break
        _w1g4_resolve_stack(game)
    game.check_state_based_actions()


def _w1g4_named(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat) if p.is_creature)


# -- Bane of the Living: "Morph {X}{B}{B}" ------------------------------------


def test_w1g4_bane_of_the_living_announces_x_and_shrinks_everything(set_pool):
    """CR 107.3d: X is chosen by the player taking the special action
    immediately before paying; CR 702.37f: the face-up trigger's X is that
    value. Four Swamps pay {2}{B}{B}: the Bears (2/2) die, the Hill Giant
    (3/3) lives at 1/1, and Bane itself (4/3) is a 2/1 until end of turn."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Bane of the Living"] + ["Swamp"] * 4,
        ["Grizzly Bears", "Hill Giant"],
    )
    bane = placed[0]
    (offer,) = _w1g4_offers(game, 0)
    assert offer["morph_cost"] == "{X}{B}{B}"
    assert (offer["x_symbols"], offer["max_x"]) == (1, 2)

    assert _w1g4_take(game, 0, bane, "turn_face_up", x_value=2) is None
    (trigger,) = game.stack
    assert trigger.x_value == 2
    assert all(p.tapped for p in game.controlled_by(0) if p.has_type("land"))
    _w1g4_settle(game)

    assert _w1g4_named(game, 1) == ["Hill Giant"]
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]
    giant = next(p for p in game.controlled_by(1) if p.card.name == "Hill Giant")
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)
    assert (bane.effective_power, bane.effective_toughness) == (2, 1)
    assert any("with X = 2" in line for line in game.log)


def test_w1g4_bane_refuses_an_x_its_lands_cannot_pay(set_pool):
    """X = 3 is {3}{B}{B}, one more than four Swamps make: refused with
    nothing tapped and the creature still face down (CR 601.2h's whole-price
    rule, applied by the special-action seam)."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Bane of the Living"] + ["Swamp"] * 4, ["Grizzly Bears"],
    )
    bane = placed[0]
    assert _w1g4_take(game, 0, bane, "turn_face_up", x_value=3) is not None
    assert _w1g4_is_face_down(bane) and not game.stack
    assert not any(p.tapped for p in game.controlled_by(0))


def test_w1g4_bane_turned_up_by_an_effect_has_no_x(set_pool):
    """Skirk Alarmist turns it face up without the special action, so no X
    was chosen (CR 702.37f names the X "chosen as the morph special action
    was taken"): the trigger still fires (the 2004-10-04 ruling: "or when an
    effect turns it face up") and every creature gets -0/-0."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Bane of the Living", "Skirk Alarmist"], ["Grizzly Bears"],
    )
    bane = placed[0]
    game.enforce_mana_costs = False
    result = game.queue_permanent_ability(
        0, "Skirk Alarmist", target_permanent_ids=[bane.permanent_id], ability_index=0,
    )
    assert result.supported, result.details
    _w1g4_settle(game)

    assert bane.card.name == "Bane of the Living"
    assert any("Bane of the Living triggered (turned face up)" in line for line in game.log)
    assert _w1g4_named(game, 1) == ["Grizzly Bears"]
    assert (bane.effective_power, bane.effective_toughness) == (4, 3)


def test_w1g4_a_morph_cost_without_x_refuses_an_announced_x(set_pool):
    """An X the price does not print is not quietly ignored: the seam refuses
    it, and X = 0 (or none) is the ordinary turn-up."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Willbender", "Island", "Island"], [],
    )
    willbender = placed[0]
    (offer,) = _w1g4_offers(game, 0)
    assert "x_symbols" not in offer and "max_x" not in offer
    assert _w1g4_take(game, 0, willbender, "turn_face_up", x_value=1) == (
        "that price has no X to choose"
    )
    assert _w1g4_take(game, 0, willbender, "turn_face_up", x_value=0) is None
    assert willbender.card.name == "Willbender"


# -- Warbreak Trumpeter: "Morph {X}{X}{R}" ------------------------------------


def test_w1g4_warbreak_trumpeter_pays_two_mana_per_x(set_pool):
    """Two {X} symbols: X = 2 is {2}{2}{R}, all five Mountains, and the
    trigger creates two 1/1 red Goblins."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Warbreak Trumpeter"] + ["Mountain"] * 5, [],
    )
    trumpeter = placed[0]
    (offer,) = _w1g4_offers(game, 0)
    assert (offer["x_symbols"], offer["max_x"]) == (2, 2)
    assert _w1g4_take(game, 0, trumpeter, "turn_face_up", x_value=2) is None
    assert all(p.tapped for p in game.controlled_by(0) if p.has_type("land"))
    _w1g4_settle(game)

    goblins = [p for p in game.controlled_by(0) if p.card.name == "Goblin Token"]
    assert len(goblins) == 2
    assert all(
        (g.effective_power, g.effective_toughness) == (1, 1) and g.has_type("goblin")
        for g in goblins
    )


def test_w1g4_the_ai_announces_the_largest_x_worth_paying(set_pool):
    """The AI's chooser (``ai_special_actions``) rehearses sizes of X against
    the table: for the Trumpeter more Goblins are always more, so it takes
    the largest X the Mountains pay."""
    from engine.ai_special_actions import choose_special_action

    game, placed = _w1g4_table(
        set_pool, ["fd:Warbreak Trumpeter", "Grizzly Bears"] + ["Mountain"] * 5,
        ["Hill Giant"],
    )
    game.current_turn_phase = game.current_step = "precombat_main"
    choice = choose_special_action(game, 0)
    assert choice is not None and choice.kind == "turn_face_up"
    assert choice.x_value == 2


# -- Willbender: "change the target of target spell or ability with a single
#    target" ---------------------------------------------------------------


def test_w1g4_willbender_re_aims_a_spell(set_pool):
    """A Lightning Bolt aimed at the Bears; Willbender turned up in response
    targets the Bolt (CR 603.3d) and, resolving, moves it to another legal
    target (CR 115.7a). The new target is chosen as the trigger resolves (the
    2018-03-16 ruling)."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Willbender", "Grizzly Bears", "Island", "Island"], [],
    )
    willbender, bears = placed[0], placed[1]
    game.enforce_mana_costs = False
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    game.start_priority_window(0)
    assert _w1g4_take(game, 0, willbender, "turn_face_up") is None
    trigger = game.stack[-1]
    assert trigger.target_stack_item is game.stack[0]
    _w1g4_settle(game)

    assert bears.damage_marked == 0
    assert any("Lightning Bolt now targets" in line for line in game.log)
    # A seat nobody asks aims the harm at its opponent (the only other
    # legal target here is its own face): P2 takes the 3.
    assert (game.players[0].life, game.players[1].life) == (20, 17)


def test_w1g4_willbender_re_aims_an_activated_ability(set_pool):
    """"…spell **or ability**": Prodigal Sorcerer's ping is an ability on the
    stack (CR 113.7a), and Willbender moves it off the Bears."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Willbender", "Grizzly Bears", "Island", "Island"],
        ["Prodigal Sorcerer"],
    )
    willbender, bears = placed[0], placed[1]
    game.enforce_mana_costs = False
    assert game.queue_permanent_ability(
        1, "Prodigal Sorcerer", target_permanent_ids=[bears.permanent_id],
        ability_index=0,
    ).supported
    game.start_priority_window(0)
    assert _w1g4_take(game, 0, willbender, "turn_face_up") is None
    assert game.stack[-1].target_stack_item is game.stack[0]
    _w1g4_settle(game)

    assert bears.damage_marked == 0
    assert any("Prodigal Sorcerer now targets" in line for line in game.log)
    assert (game.players[0].life, game.players[1].life) == (20, 19)


def test_w1g4_willbender_cannot_target_a_spell_with_two_targets(set_pool):
    """The 2018-03-16 ruling: "If a spell or ability targets multiple things,
    you can't target it with Willbender's triggered ability." With only such
    a spell on the stack the trigger has no legal target and is removed
    (CR 603.3d); both creatures take their share."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Willbender", "Grizzly Bears", "Hill Giant", "Island", "Island"],
        [],
    )
    willbender, bears, giant = placed[0], placed[1], placed[2]
    game.enforce_mana_costs = False
    game.players[1].hand.append(set_pool("LEG")["Pyrotechnics"])
    # Seat 0's battlefield slots 1 and 2: the Bears and the Hill Giant.
    result = game.queue_from_hand(
        1, "Pyrotechnics", divided_targets=[(0, 1, 2), (0, 2, 2)],
    )
    assert result.supported, result.details
    game.start_priority_window(0)
    assert _w1g4_take(game, 0, willbender, "turn_face_up") is None
    assert [item.card.name for item in game.stack] == ["Pyrotechnics"]
    assert any("no legal target" in line for line in game.log)


# -- Weaver of Lies: "turn any number of target creatures with morph abilities
#    other than this creature face down" ------------------------------------


def test_w1g4_weaver_of_lies_turns_the_opponents_morphs_face_down(set_pool):
    """A seat nobody asks aims the denial at the opponent (CR 708.2a's 2/2
    whose owner must pay its morph cost again): both of their face-up morph
    creatures go face down; the Bears (no morph), the Weaver itself ("other
    than this creature") and our own Daru Mender stay."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Weaver of Lies", "Daru Mender"] + ["Island"] * 5,
        ["Willbender", "Liege of the Axe", "Grizzly Bears"],
    )
    weaver, mender = placed[0], placed[1]
    willbender, liege, bears = placed[-3:]
    assert _w1g4_take(game, 0, weaver, "turn_face_up") is None
    _w1g4_settle(game)

    assert [_w1g4_is_face_down(p) for p in (weaver, mender, willbender, liege, bears)] == [
        False, False, True, True, False,
    ]
    # The opponent's state sees two 2/2s; what they were is public, since the
    # table watched them be turned down (CR 708.2a).
    assert (willbender.effective_power, willbender.effective_toughness) == (2, 2)


def test_w1g4_weaver_of_lies_interactive_chooses_any_number(set_pool):
    """An interactive controller is offered every creature with a morph
    ability but the Weaver, across both boards, may name any number of them
    (CR 107.1c) — here one of the opponent's and its own Daru Mender, so a
    later special action can turn the Mender up again."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Weaver of Lies", "Daru Mender"] + ["Island"] * 5,
        ["Willbender", "Liege of the Axe", "Grizzly Bears"], interactive=True,
    )
    weaver, mender = placed[0], placed[1]
    willbender, liege, _bears = placed[-3:]
    assert _w1g4_take(game, 0, weaver, "turn_face_up") is None
    (choice,) = game.pending_choices
    assert choice.kind == "trigger_target" and choice.data["up_to"] is True
    offered = {t["permanent_id"] for t in choice.data["targets"]}
    assert offered == {mender.permanent_id, willbender.permanent_id, liege.permanent_id}
    assert choice.data["max_targets"] == 3
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_ids=[willbender.permanent_id, mender.permanent_id],
    )
    _w1g4_resolve_stack(game)

    assert [_w1g4_is_face_down(p) for p in (mender, willbender, liege)] == [True, True, False]


def test_w1g4_weaver_of_lies_may_name_nothing(set_pool):
    """CR 107.1c: "any number" includes zero. With no other morph creature on
    the battlefield the trigger names nothing and resolves; with only our own
    to name, a seat nobody asks names none rather than turn its own down."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Weaver of Lies", "Daru Mender"] + ["Island"] * 5,
        ["Grizzly Bears"],
    )
    weaver, mender = placed[0], placed[1]
    assert _w1g4_take(game, 0, weaver, "turn_face_up") is None
    _w1g4_settle(game)
    assert not _w1g4_is_face_down(mender) and not _w1g4_is_face_down(weaver)
    assert not game.stack


# -- Dermoplasm -------------------------------------------------------------


def test_w1g4_dermoplasm_swaps_itself_for_a_morph_card_in_hand(set_pool):
    """"…you may put a creature card with a morph ability from your hand onto
    the battlefield face up. If you do, return this creature to its owner's
    hand." Exalted Angel (morph) enters face up — so it is not turned face up
    and its own trigger-free text is simply there — and Dermoplasm goes home.
    The Bears in the same hand have no morph and are not offered."""
    game, placed = _w1g4_table(set_pool, ["fd:Dermoplasm"] + ["Island"] * 4, [])
    dermoplasm = placed[0]
    game.players[0].hand.extend(
        [set_pool("LEA")["Grizzly Bears"], set_pool("ONS")["Exalted Angel"]]
    )
    assert _w1g4_take(game, 0, dermoplasm, "turn_face_up") is None
    _w1g4_settle(game)

    assert _w1g4_named(game, 0) == ["Exalted Angel"]
    angel = next(p for p in game.controlled_by(0) if p.card.name == "Exalted Angel")
    assert not _w1g4_is_face_down(angel)
    assert sorted(c.name for c in game.players[0].hand) == ["Dermoplasm", "Grizzly Bears"]


def test_w1g4_dermoplasm_interactive_picks_which_card(set_pool):
    """An interactive seat is asked whether (``optional_pay``) and which
    (``put_from_hand_choice``); only the morph cards are candidates."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Dermoplasm"] + ["Island"] * 4, [], interactive=True,
    )
    dermoplasm = placed[0]
    hand = game.players[0].hand
    hand.extend([
        set_pool("LEA")["Grizzly Bears"], set_pool("ONS")["Exalted Angel"],
        set_pool("LGN")["Willbender"],
    ])
    assert _w1g4_take(game, 0, dermoplasm, "turn_face_up") is None
    for _ in range(5):
        if game.stack and not game.pending_choices:
            game.resolve_top_of_stack()
    (offer,) = game.pending_choices
    assert offer.kind == "optional_pay"
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    (pick,) = game.pending_choices
    assert pick.kind == "put_from_hand_choice"
    willbender_slot = next(i for i, c in enumerate(hand) if c.name == "Willbender")
    bears_slot = next(i for i, c in enumerate(hand) if c.name == "Grizzly Bears")
    # The Bears print no morph: an answer naming them is refused and the
    # prompt stays owed.
    assert not game.resolve_pending_choice("put_from_hand_choice", 0, hand_index=bears_slot)
    assert game.resolve_pending_choice("put_from_hand_choice", 0, hand_index=willbender_slot)
    _w1g4_settle(game)

    assert _w1g4_named(game, 0) == ["Willbender"]
    assert "Dermoplasm" in [c.name for c in game.players[0].hand]


def test_w1g4_dermoplasm_with_no_morph_card_stays(set_pool):
    """No creature card with a morph ability in hand: there is nothing to
    put, so "if you do" never happens and Dermoplasm stays on the
    battlefield."""
    game, placed = _w1g4_table(set_pool, ["fd:Dermoplasm"] + ["Island"] * 4, [])
    dermoplasm = placed[0]
    game.players[0].hand.append(set_pool("LEA")["Grizzly Bears"])
    assert _w1g4_take(game, 0, dermoplasm, "turn_face_up") is None
    _w1g4_settle(game)
    assert _w1g4_named(game, 0) == ["Dermoplasm"]
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]


# -- Tribal Forcemage ---------------------------------------------------------


def test_w1g4_tribal_forcemage_pumps_and_tramples_the_chosen_type(set_pool):
    """One printed noun phrase, one choice (CR 608.2d), read by both halves:
    every Elf on the battlefield — ours and theirs — gets +2/+2 and trample;
    nothing else does."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Tribal Forcemage", "Llanowar Elves", "Grizzly Bears", "Forest", "Forest"],
        ["Elvish Archers", "Goblin King"],
    )
    forcemage, elves, bears = placed[0], placed[1], placed[2]
    archers, king = placed[-2], placed[-1]
    assert _w1g4_take(game, 0, forcemage, "turn_face_up") is None
    _w1g4_settle(game)

    asked = [line for line in game.log if "chooses a creature type" in line]
    assert len(asked) == 1, "one choice for both halves"
    for elf in (forcemage, elves, archers):
        assert game._has_keyword(elf, "trample"), elf.card.name
    assert (elves.effective_power, elves.effective_toughness) == (3, 3)
    assert (forcemage.effective_power, forcemage.effective_toughness) == (3, 3)
    assert not game._has_keyword(bears, "trample")
    assert not game._has_keyword(king, "trample")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g4_tribal_forcemage_interactive_choice_reaches_both_halves(set_pool):
    """An interactive controller naming Goblin: the Goblin King is pumped and
    given trample, and the Elves — the type the default would have named —
    get neither."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Tribal Forcemage", "Llanowar Elves", "Forest", "Forest"],
        ["Goblin King"], interactive=True,
    )
    forcemage, elves, king = placed[0], placed[1], placed[-1]
    assert _w1g4_take(game, 0, forcemage, "turn_face_up") is None
    for _ in range(5):
        if game.stack and not game.pending_choices:
            game.resolve_top_of_stack()
    (choice,) = game.pending_choices
    assert choice.kind == "creature_type_choice"
    assert game.resolve_pending_choice("creature_type_choice", 0, creature_type="Goblin")
    _w1g4_resolve_stack(game)

    assert game._has_keyword(king, "trample")
    assert (king.effective_power, king.effective_toughness) == (4, 4)
    assert not game._has_keyword(elves, "trample")
    assert (elves.effective_power, elves.effective_toughness) == (1, 1)


# -- Chromeshell Crab (supported on arrival; its trigger announced nothing) --


def test_w1g4_chromeshell_crab_exchanges_the_two_creatures_it_targets(set_pool):
    """"…you may exchange control of target creature you control and target
    creature an opponent controls." Two instances of "target", chosen as the
    trigger goes on the stack (CR 603.3d) — a roles announcement. The trigger
    used to announce nothing and resolve "the exchange could not be
    completed". A seat nobody asks names each role's first candidate: the
    Crab itself for the Hill Giant (CR 701.12a)."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Chromeshell Crab", "Grizzly Bears"] + ["Island"] * 5,
        ["Hill Giant"],
    )
    crab, bears, giant = placed[0], placed[1], placed[-1]
    assert _w1g4_take(game, 0, crab, "turn_face_up") is None
    assert game.stack[-1].target_permanent_id == [crab.permanent_id, giant.permanent_id]
    _w1g4_settle(game)

    assert game.controller_index_of(giant) == 0
    assert game.controller_index_of(crab) == 1
    assert game.controller_index_of(bears) == 0


def test_w1g4_chromeshell_crab_interactive_names_each_role(set_pool):
    """An interactive seat is offered each candidate under the role it may
    fill and answers one per role, in order: an answer in the wrong order (the
    opponent's creature for "you control") is refused and the prompt stays."""
    game, placed = _w1g4_table(
        set_pool, ["fd:Chromeshell Crab", "Grizzly Bears"] + ["Island"] * 5,
        ["Hill Giant"], interactive=True,
    )
    crab, bears, giant = placed[0], placed[1], placed[-1]
    assert _w1g4_take(game, 0, crab, "turn_face_up") is None
    (choice,) = game.pending_choices
    assert choice.kind == "trigger_target" and len(choice.data["roles"]) == 2
    by_role = {}
    for target in choice.data["targets"]:
        by_role.setdefault(target["role"], set()).add(target["permanent_id"])
    assert by_role == {
        0: {crab.permanent_id, bears.permanent_id}, 1: {giant.permanent_id},
    }
    assert not game.resolve_pending_choice(
        "trigger_target", 0, permanent_ids=[giant.permanent_id, bears.permanent_id],
    )
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    _w1g4_settle(game)

    assert game.controller_index_of(giant) == 0
    assert game.controller_index_of(bears) == 1
    assert game.controller_index_of(crab) == 0

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# --- W1G5: tribal statics and counts ---------------------------------------
import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine.models import Permanent as _W1G5Permanent
from engine.models import PlayerState as _W1G5PlayerState
from engine.oracle import compile_card_oracle as _w1g5_compile

from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, *hand, opponent_hand=(), interactive=()):
    """Alice (seat 0, active) holding *hand*, Bob holding *opponent_hand*;
    both over five Swamps, mana costs unenforced."""
    lgn = set_pool("LGN")
    ons = set_pool("ONS")

    def card(name):
        return lgn[name] if name in lgn else ons[name]

    filler = ons["Swamp"]
    alice = _W1G5PlayerState(
        name="Alice", hand=[card(name) for name in hand], library=[filler] * 5,
    )
    bob = _W1G5PlayerState(
        name="Bob", hand=[card(name) for name in opponent_hand],
        library=[filler] * 5,
    )
    game = _W1G5Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game, alice, bob, card


def _w1g5_put(game, seat, card):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


@_w1g5_pytest.mark.parametrize("interactive", [False, True])
def test_w1g5_gempalm_polluter_drains_by_the_zombies_on_the_whole_battlefield(
    set_pool, interactive,
):
    """"When you cycle this card, you may have target player lose life equal
    to the number of Zombies on the battlefield." Zombies on both sides count
    (two here: one each), an Elf does not, and the count is taken as the
    trigger resolves — after a third Zombie arrived in response. An
    interactive Alice names herself; the default seat names Bob."""
    game, alice, bob, card = _w1g5_table(
        set_pool, "Gempalm Polluter", interactive={0} if interactive else (),
    )
    _w1g5_put(game, 0, card("Severed Legion"))
    _w1g5_put(game, 1, card("Severed Legion"))
    _w1g5_put(game, 1, card("Wellwisher"))
    assert _w1g5_compile(card("Gempalm Polluter")).supported

    assert game.activate_from_hand(0, "Gempalm Polluter").supported
    if interactive:
        assert game.pending_choice_of("trigger_target", 0) is not None
        assert game.confirm_trigger_target(0, seat=0)
    loser = alice if interactive else bob
    # A third Zombie before the trigger resolves: the count is the board's at
    # resolution, not at the cycle.
    _w1g5_put(game, 1, card("Gempalm Polluter"))
    _w1g5_resolve_stack(game)
    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None, "the 'you may' is asked"
    assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()

    assert loser.life == 17
    assert (alice if loser is bob else bob).life == 20
    assert any(f"{loser.name} lost 3 life" in line for line in game.log)


def test_w1g5_gempalm_polluter_declined_loses_nothing(set_pool):
    """The "you may" declined: nobody loses life, and the cycling still draws."""
    game, alice, bob, card = _w1g5_table(set_pool, "Gempalm Polluter")
    _w1g5_put(game, 1, card("Severed Legion"))
    assert game.activate_from_hand(0, "Gempalm Polluter").supported
    _w1g5_resolve_stack(game)
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, False, None)
    game.auto_resolve_pending_choices()
    assert (alice.life, bob.life) == (20, 20)
    assert len(alice.hand) == 1


def test_w1g5_noxious_ghoul_shrinks_every_non_zombie_when_a_zombie_enters(
    set_pool,
):
    """"Whenever this creature or another Zombie enters, all non-Zombie
    creatures get -1/-1 until end of turn." Cast, the Ghoul's own entry
    shrinks both sides' non-Zombies (a 1/1 Elf dies) and no Zombie; Bob's
    Zombie entering afterwards fires it again; a non-Zombie entering does
    not; and the shrink ends at cleanup."""
    game, alice, bob, card = _w1g5_table(
        set_pool, "Noxious Ghoul", opponent_hand=("Severed Legion",),
    )
    elf = _w1g5_put(game, 1, card("Birchlore Rangers"))   # 1/1 Elf
    bear = _w1g5_put(game, 0, card("Wellwisher"))          # 1/1 Elf
    hulk = _w1g5_put(game, 1, card("Krosan Tusker"))       # 6/5 Beast
    legion = _w1g5_put(game, 0, card("Severed Legion"))    # 2/2 Zombie

    assert game.queue_from_hand(0, "Noxious Ghoul").supported
    _w1g5_resolve_stack(game)
    game.check_state_based_actions()
    ghoul = next(p for p in game.controlled_by(0) if p.card.name == "Noxious Ghoul")
    assert not game.is_on_battlefield(elf) and not game.is_on_battlefield(bear)
    assert (hulk.effective_power, hulk.effective_toughness) == (5, 4)
    assert (legion.effective_power, legion.effective_toughness) == (2, 2)
    assert (ghoul.effective_power, ghoul.effective_toughness) == (3, 3)

    # Another Zombie — the opponent's — fires it a second time.
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Severed Legion").supported
    _w1g5_resolve_stack(game)
    assert (hulk.effective_power, hulk.effective_toughness) == (4, 3)
    assert (ghoul.effective_power, ghoul.effective_toughness) == (3, 3)

    # A non-Zombie entering does not.
    _w1g5_put(game, 1, card("Wellwisher"))
    _w1g5_resolve_stack(game)
    assert (hulk.effective_power, hulk.effective_toughness) == (4, 3)

    game.resolve_cleanup_step(1)
    assert (hulk.effective_power, hulk.effective_toughness) == (6, 5)


def _w1g5_slot(game, seat, permanent):
    return next(
        index for index, candidate in enumerate(game.players[seat].battlefield)
        if candidate is permanent
    )


def test_w1g5_frenetic_raptor_grounds_every_beast_as_a_blocker(set_pool):
    """"Beasts can't block." Every Beast on every battlefield — the Raptor
    itself, Alice's other Beast, and Bob's — and nothing else: Alice's Elf
    blocks as usual."""
    game, alice, bob, card = _w1g5_table(set_pool)
    raptor = _w1g5_put(game, 0, card("Frenetic Raptor"))
    tusker = _w1g5_put(game, 0, card("Krosan Tusker"))     # Boar Beast
    elf = _w1g5_put(game, 0, card("Birchlore Rangers"))
    attacker = _w1g5_put(game, 1, card("Wellwisher"))
    bobs_beast = _w1g5_put(game, 1, card("Krosan Tusker"))

    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        1, [_w1g5_slot(game, 1, attacker)], defending_player_index=0,
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    for beast in (raptor, tusker):
        assert not game._can_block_attacker(beast, attacker)
    assert game._can_block_attacker(elf, attacker)
    assert not game._can_block_attacker(bobs_beast, attacker), "any controller"
    ok, _why = game.declare_blockers(
        0, {_w1g5_slot(game, 0, tusker): _w1g5_slot(game, 1, attacker)},
    )
    assert not ok, "the Beast's block is refused"
    ok, why = game.declare_blockers(
        0, {_w1g5_slot(game, 0, elf): _w1g5_slot(game, 1, attacker)},
    )
    assert ok, why

    # The Raptor gone, the Beasts block again (a static, CR 611.3a).
    game.remove_from_battlefield(raptor)
    assert game._can_block_attacker(tusker, attacker)


def test_w1g5_a_one_word_creature_type_subject_cannot_attack():
    """The attack twin of the Raptor's row: "Beasts can't attack." on an
    invented card grounds a Beast attacker and no other."""
    beast = _w1g5_mk_card("Test Beast", "Creature — Beast", power=2, toughness=2)
    elf = _w1g5_mk_card("Test Elf", "Creature — Elf", power=2, toughness=2)
    warden = _w1g5_mk_card(
        "Beast Warden", "Creature — Human", "Beasts can't attack.",
        power=1, toughness=1,
    )
    assert _w1g5_compile(warden).supported
    game = _W1G5Game(players=[_W1G5PlayerState(name="A"), _W1G5PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    attacker_beast = _w1g5_put(game, 0, beast)
    attacker_elf = _w1g5_put(game, 0, elf)
    _w1g5_put(game, 1, warden)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [_w1g5_slot(game, 0, attacker_beast)], defending_player_index=1,
    )
    assert not ok
    ok, why = game.declare_attackers(
        0, [_w1g5_slot(game, 0, attacker_elf)], defending_player_index=1,
    )
    assert ok, why


def test_w1g5_berserk_murlodont_pumps_each_blocked_beast_by_its_blockers(
    set_pool,
):
    """"Whenever a Beast becomes blocked, it gets +1/+1 until end of turn for
    each creature blocking it." Alice attacks with a Beast blocked by two, the
    Murlodont (a Beast) blocked by one, and an Elf blocked by one: the Beast
    gets +2/+2, the Murlodont +1/+1, the Elf nothing — one trigger per
    blocked Beast (CR 509.3c), sized by its own blockers."""
    from tests.helpers import declare_attack

    game, alice, bob, card = _w1g5_table(set_pool)
    murlodont = _w1g5_put(game, 0, card("Berserk Murlodont"))   # 3/3
    tusker = _w1g5_put(game, 0, card("Krosan Tusker"))          # 6/5
    elf = _w1g5_put(game, 0, card("Birchlore Rangers"))         # 1/1
    walls = [_w1g5_put(game, 1, card("Severed Legion")) for _ in range(4)]

    def slot(perm):
        seat = 0 if perm in (murlodont, tusker, elf) else 1
        return _w1g5_slot(game, seat, perm)

    declare_attack(game, 0, blocks={
        slot(walls[0]): slot(tusker), slot(walls[1]): slot(tusker),
        slot(walls[2]): slot(murlodont), slot(walls[3]): slot(elf),
    })
    triggers = [item for item in game.stack if item.card.name == "Berserk Murlodont"]
    assert len(triggers) == 2, [item.ability_text for item in game.stack]
    _w1g5_resolve_stack(game)
    assert (tusker.effective_power, tusker.effective_toughness) == (8, 7)
    assert (murlodont.effective_power, murlodont.effective_toughness) == (4, 4)
    assert (elf.effective_power, elf.effective_toughness) == (1, 1)
    assert any("gives Krosan Tusker +2/+2" in line for line in game.log)


def test_w1g5_berserk_murlodont_watches_the_opponents_beasts_too(set_pool):
    """"A Beast" is any controller's: Bob's Beast, blocked by Alice's two
    creatures, is pumped by Alice's Murlodont."""
    from tests.helpers import declare_attack

    game, alice, bob, card = _w1g5_table(set_pool)
    _w1g5_put(game, 0, card("Berserk Murlodont"))
    blockers = [_w1g5_put(game, 0, card("Birchlore Rangers")) for _ in range(2)]
    for perm in game.controlled_by(0):
        perm.tapped = perm not in blockers
    beast = _w1g5_put(game, 1, card("Krosan Tusker"))
    declare_attack(game, 1, blocks={
        _w1g5_slot(game, 0, blockers[0]): _w1g5_slot(game, 1, beast),
        _w1g5_slot(game, 0, blockers[1]): _w1g5_slot(game, 1, beast),
    })
    _w1g5_resolve_stack(game)
    assert (beast.effective_power, beast.effective_toughness) == (8, 7)


def _w1g5_bears(game, seat):
    return [
        perm for perm in game.controlled_by(seat) if perm.card.name == "Bear Token"
    ]


def test_w1g5_caller_of_the_claw_counts_the_nontoken_creatures_that_died_yours(
    set_pool,
):
    """"When this creature enters, create a 2/2 green Bear creature token for
    each nontoken creature put into your graveyard from the battlefield this
    turn." Two of Alice's cards die; so do a token of hers (CR 111.7 puts it
    in the graveyard, but it is no card), Bob's creature (Bob's graveyard),
    and Alice's creature that Bob had stolen (Alice's graveyard, CR 400.3).
    The Caller enters: three Bears, each a 2/2 green Bear."""
    from engine.control import change_control

    game, alice, bob, card = _w1g5_table(set_pool, "Caller of the Claw")
    mine = [_w1g5_put(game, 0, card("Birchlore Rangers")) for _ in range(2)]
    token = _w1g5_put(game, 0, card("Wellwisher"))
    token.metadata["is_token"] = True
    bobs = _w1g5_put(game, 1, card("Wellwisher"))
    stolen = _w1g5_put(game, 0, card("Severed Legion"))
    change_control(stolen, 1, source=bobs)
    game._sync_control()
    assert game.controller_index_of(stolen) == 1
    for victim in (*mine, token, stolen, bobs):
        game.sacrifice_permanent(victim)
    assert alice.nontoken_creatures_put_into_your_graveyard_this_turn == 3
    assert alice.creatures_put_into_your_graveyard_this_turn == 4
    assert bob.nontoken_creatures_put_into_your_graveyard_this_turn == 1

    assert game.queue_from_hand(0, "Caller of the Claw").supported
    _w1g5_resolve_stack(game)
    bears = _w1g5_bears(game, 0)
    assert len(bears) == 3
    assert all(
        (bear.effective_power, bear.effective_toughness) == (2, 2)
        and bear.has_type("bear") and "G" in bear.effective_colors
        for bear in bears
    )


def test_w1g5_caller_of_the_claw_counts_this_turn_only(set_pool):
    """The tally is the turn's: a death last turn makes no Bear, and with no
    death this turn the Caller enters alone."""
    game, alice, bob, card = _w1g5_table(set_pool, "Caller of the Claw")
    game.sacrifice_permanent(_w1g5_put(game, 0, card("Birchlore Rangers")))
    assert alice.nontoken_creatures_put_into_your_graveyard_this_turn == 1
    game.start_next_turn()
    assert alice.nontoken_creatures_put_into_your_graveyard_this_turn == 0
    assert game.queue_from_hand(0, "Caller of the Claw").supported
    _w1g5_resolve_stack(game)
    assert _w1g5_bears(game, 0) == []
    assert any(p.card.name == "Caller of the Claw" for p in game.controlled_by(0))


def _w1g5_entangle(game, card, target):
    """Alice's Whipgrass Entangler grants its toll to *target*."""
    result = game.activate_permanent_ability(
        0, "Whipgrass Entangler", target_permanent_ids=[target.permanent_id],
    )
    assert result.supported, result.details
    _w1g5_resolve_stack(game)


def test_w1g5_whipgrass_entangler_taxes_the_attack_per_cleric(set_pool):
    """"{1}{W}: Until end of turn, target creature gains "This creature can't
    attack or block unless its controller pays {1} for each Cleric on the
    battlefield."" Two Clerics (the Entangler and Bob's own): Bob's Beast owes
    {2} to attack — refused with one land, paid with two. A third Cleric
    arriving before the declaration makes it {3}. Cleanup ends the grant."""
    game, alice, bob, card = _w1g5_table(set_pool)
    game.active_player_index = 1
    _w1g5_put(game, 0, card("Whipgrass Entangler"))
    _w1g5_put(game, 1, card("Daru Mender"))                # a Cleric
    beast = _w1g5_put(game, 1, card("Krosan Tusker"))
    land = _w1g5_put(game, 1, card("Plains"))
    _w1g5_entangle(game, card, beast)
    assert "for each Cleric on the battlefield" in beast.effective_card.oracle_text
    assert game._attack_mana_costs_of(beast, 0) == [{"generic": 2}]

    game.enforce_mana_costs = True
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        1, [_w1g5_slot(game, 1, beast)], defending_player_index=0,
    )
    assert not ok and not beast.tapped and not land.tapped, "one land, {2} owed"

    _w1g5_put(game, 1, card("Plains"))
    _w1g5_put(game, 0, card("Daru Sanctifier"))             # a third Cleric
    assert game._attack_mana_costs_of(beast, 0) == [{"generic": 3}]
    _w1g5_put(game, 1, card("Plains"))
    ok, why = game.declare_attackers(
        1, [_w1g5_slot(game, 1, beast)], defending_player_index=0,
    )
    assert ok, why
    assert any("paid {3} to declare attackers" in line for line in game.log)

    game.resolve_cleanup_step(1)
    assert game._attack_mana_costs_of(beast, 0) == []


def test_w1g5_whipgrass_entangler_taxes_the_block_too(set_pool):
    """The same grant's block half: Bob's creature owes {2} to block Alice's
    attacker — refused with no land, accepted and charged with two
    Plains. Its toll is the creature's alone: Bob's other creature blocks
    free."""
    game, alice, bob, card = _w1g5_table(set_pool)
    _w1g5_put(game, 0, card("Whipgrass Entangler")).tapped = True
    attacker = _w1g5_put(game, 0, card("Krosan Tusker"))
    _w1g5_put(game, 1, card("Daru Mender")).tapped = True    # Bob's Cleric
    taxed = _w1g5_put(game, 1, card("Wellwisher"))
    free = _w1g5_put(game, 1, card("Birchlore Rangers"))
    _w1g5_entangle(game, card, taxed)
    game.enforce_mana_costs = True
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [_w1g5_slot(game, 0, attacker)], defending_player_index=1,
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert game._block_mana_costs_of(taxed, attacker) == [{"generic": 2}]
    assert game._block_mana_costs_of(free, attacker) == []
    ok, _why = game.declare_blockers(
        1, {_w1g5_slot(game, 1, taxed): _w1g5_slot(game, 0, attacker)},
    )
    assert not ok, "no mana for the {2}"
    lands = [_w1g5_put(game, 1, card("Plains")) for _ in range(2)]
    ok, why = game.declare_blockers(
        1, {_w1g5_slot(game, 1, taxed): _w1g5_slot(game, 0, attacker)},
    )
    assert ok, why
    assert all(land.tapped for land in lands)


# --- W1G5: Mistform Ultimus, every creature type in every zone -------------
#
# "Mistform Ultimus is every creature type (even if this card isn't on the
# battlefield)." A characteristic-defining ability (CR 604.3; changeling's
# CR 702.73a), read off the card's own text by the one type parse both the
# off-battlefield answer and the layer seed share
# (`layer_bridge._printed_shape`).


def test_w1g5_mistform_ultimus_is_supported_and_shows_its_printed_line(set_pool):
    """The line is claimed, and the board shows "Legendary Creature —
    Illusion", not three hundred words."""
    from engine.layer_bridge import displayed_type_line

    ultimus = set_pool("LGN")["Mistform Ultimus"]
    program = _w1g5_compile(ultimus)
    assert program.supported, program.reason
    game, alice, bob, card = _w1g5_table(set_pool)
    permanent = _w1g5_put(game, 0, ultimus)
    assert displayed_type_line(permanent) == "Legendary Creature — Illusion"
    for word in ("illusion", "goblin", "zombie", "beast", "sliver", "cleric"):
        assert permanent.has_type(word), word
    assert not permanent.has_type("forest"), "a creature type, not a land type"


def test_w1g5_mistform_ultimus_is_every_type_in_the_library_and_graveyard(
    set_pool,
):
    """Off the battlefield (CR 604.3): Goblin Matron's "search your library
    for a Goblin card" finds it, Lord of the Undead's "target Zombie card from
    your graveyard" returns it, and Soulless One counts it among "Zombie cards
    in all graveyards"."""
    ultimus = set_pool("LGN")["Mistform Ultimus"]
    game, alice, bob, card = _w1g5_table(set_pool)
    alice.hand = [set_pool("USG")["Goblin Matron"]]
    alice.library = [ultimus] + alice.library
    assert game.queue_from_hand(0, "Goblin Matron").supported
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Mistform Ultimus"]
    assert any("put Mistform Ultimus into hand" in line for line in game.log)

    game, alice, bob, card = _w1g5_table(set_pool)
    alice.graveyard = [ultimus]
    soulless = _w1g5_put(game, 0, set_pool("ONS")["Soulless One"])
    game._refresh_dynamic_creatures()
    assert (soulless.effective_power, soulless.effective_toughness) == (2, 2)
    _w1g5_put(game, 0, set_pool("PLS")["Lord of the Undead"])
    assert game.activate_permanent_ability(0, "Lord of the Undead").supported
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Mistform Ultimus"]


def test_w1g5_mistform_ultimus_is_every_type_as_a_spell(set_pool):
    """On the stack: Rin and Seri's "Whenever you cast a Dog spell" and
    "…a Cat spell" both fire for the one cast."""
    game, alice, bob, card = _w1g5_table(set_pool, "Mistform Ultimus")
    _w1g5_put(game, 0, set_pool("M21")["Rin and Seri, Inseparable"])
    assert game.queue_from_hand(0, "Mistform Ultimus").supported
    assert sorted(
        item.ability_text[:27] for item in game.stack if item.ability_text
    ) == ["Whenever you cast a Cat spe", "Whenever you cast a Dog spe"]
    _w1g5_resolve_stack(game)
    names = sorted(p.card.name for p in game.controlled_by(0))
    assert "Cat Token" in names and "Dog Token" in names


def test_w1g5_mistform_ultimus_in_hand_shares_every_creature_type(set_pool):
    """The hand reader amplify and "share a creature type" ask
    (`object_creature_types.creature_types`) answers every type for the card
    in hand — and a Conspiracy naming Goblin replaces them (CR 205.1a), so the
    card is then a Goblin and nothing else."""
    from engine.object_creature_types import creature_types

    ultimus = set_pool("LGN")["Mistform Ultimus"]
    game, alice, bob, card = _w1g5_table(set_pool, "Mistform Ultimus")
    held = creature_types(game, ultimus, 0)
    assert {"beast", "bird", "soldier", "zombie", "dragon"} <= held
    conspiracy = _w1g5_put(game, 0, set_pool("MMQ")["Conspiracy"])
    game.auto_resolve_pending_choices()
    conspiracy.metadata["chosen_creature_type"] = "goblin"
    assert creature_types(game, ultimus, 0) == frozenset({"goblin"})
    assert creature_types(game, ultimus, 1) >= {"zombie"}, "Bob's seat: no Conspiracy"


def test_w1g5_mistform_ultimus_loses_its_types_to_a_type_setting_effect(
    set_pool,
):
    """The card's rulings (2006-09-25): an effect that makes it another type
    replaces every creature type — Mistform Wakecaster's "Each creature you
    control becomes that type until end of turn" makes it an Advisor and
    nothing else, shown so — and an effect removing its abilities does not
    (layer 4 before layer 6): under Humility it is still a Goblin. Face down
    it has no types at all (CR 708.2)."""
    from engine.face_down import turn_face_down
    from engine.layer_bridge import displayed_type_line

    game, alice, bob, card = _w1g5_table(set_pool)
    ultimus = _w1g5_put(game, 0, card("Mistform Ultimus"))
    _w1g5_put(game, 0, card("Mistform Wakecaster"))
    assert game.activate_permanent_ability(
        0, "Mistform Wakecaster", ability_index=1,
    ).supported
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    chosen = next(
        word for word in ("advisor", "goblin", "zombie") if ultimus.has_type(word)
    )
    assert sum(ultimus.has_type(w) for w in ("advisor", "goblin", "zombie")) == 1
    assert not ultimus.has_type("illusion")
    assert displayed_type_line(ultimus).lower() == f"legendary creature — {chosen}"
    game.resolve_cleanup_step(0)
    assert ultimus.has_type("goblin") and ultimus.has_type("zombie")

    _w1g5_put(game, 1, set_pool("TMP")["Humility"])
    game._refresh_dynamic_creatures()
    assert ultimus.effective_card.oracle_text == ""
    assert ultimus.has_type("goblin") and ultimus.has_type("zombie")
    assert (ultimus.effective_power, ultimus.effective_toughness) == (1, 1)

    game, alice, bob, card = _w1g5_table(set_pool)
    hidden = _w1g5_put(game, 0, card("Mistform Ultimus"))
    assert turn_face_down(game, hidden)
    assert not hidden.has_type("goblin") and not hidden.has_type("illusion")


def test_w1g5_mistform_ultimus_answers_this_groups_tribal_cards(set_pool):
    """On the board it is a Zombie, a Beast and a Cleric: Noxious Ghoul fires
    as it enters and spares it; Frenetic Raptor grounds it; Gempalm
    Polluter and Whipgrass Entangler count it."""
    game, alice, bob, card = _w1g5_table(set_pool, "Mistform Ultimus")
    _w1g5_put(game, 0, card("Noxious Ghoul"))
    _w1g5_resolve_stack(game)
    bystander = _w1g5_put(game, 1, card("Krosan Tusker"))
    assert game.queue_from_hand(0, "Mistform Ultimus").supported
    _w1g5_resolve_stack(game)
    ultimus = next(
        p for p in game.controlled_by(0) if p.card.name == "Mistform Ultimus"
    )
    assert (bystander.effective_power, bystander.effective_toughness) == (5, 4)
    assert (ultimus.effective_power, ultimus.effective_toughness) == (3, 3)

    _w1g5_put(game, 1, card("Frenetic Raptor"))
    attacker = _w1g5_put(game, 1, card("Wellwisher"))
    assert not game._can_block_attacker(ultimus, attacker)

    whip = _w1g5_put(game, 0, card("Whipgrass Entangler"))
    assert game.activate_permanent_ability(
        0, "Whipgrass Entangler", target_permanent_ids=[attacker.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert game._attack_mana_costs_of(attacker, 0) == [{"generic": 2}], (
        "the Entangler and the Ultimus are the Clerics"
    )
    assert whip.has_type("cleric")


# --- W1G5's drive list: the tribal cards that compiled on arrival ----------


@_w1g5_pytest.mark.parametrize("with_ultimus", [False, True])
def test_w1g5_tribal_statics_and_counts_see_mistform_ultimus(
    set_pool, with_ultimus,
):
    """Cloudreach Cavalry ("As long as you control a Bird") and Skirk Outrider
    ("…a Beast") switch on with the Ultimus and not without; Wirewood
    Channeler adds a mana per Elf, Riptide Director draws per Wizard and
    Timberwatch Elf pumps per Elf on the battlefield (Bob's Ultimus counts)."""
    game, alice, bob, card = _w1g5_table(set_pool)
    cavalry = _w1g5_put(game, 0, card("Cloudreach Cavalry"))
    outrider = _w1g5_put(game, 0, card("Skirk Outrider"))
    _w1g5_put(game, 0, card("Wirewood Channeler"))
    _w1g5_put(game, 0, card("Riptide Director"))
    _w1g5_put(game, 0, card("Timberwatch Elf"))
    legion = _w1g5_put(game, 0, card("Severed Legion"))    # 2/2, no Beast
    if with_ultimus:
        _w1g5_put(game, 1, card("Mistform Ultimus"))
        _w1g5_put(game, 0, card("Mistform Ultimus"))
    game._refresh_dynamic_creatures()
    bonus = 2 if with_ultimus else 0
    assert (cavalry.effective_power, cavalry.effective_toughness) == (1 + bonus, 1 + bonus)
    assert game._has_keyword(cavalry, "flying") is with_ultimus
    assert (outrider.effective_power, outrider.effective_toughness) == (2 + bonus, 2 + bonus)
    assert game._has_keyword(outrider, "trample") is with_ultimus

    # The Channeler and Timberwatch Elf, and both Ultimuses where present.
    elves = 2 + (2 if with_ultimus else 0)
    assert game.activate_permanent_ability(0, "Wirewood Channeler").supported
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert sum(alice.mana_pool.values()) == elves

    hand_before = len(alice.hand)
    assert game.activate_permanent_ability(0, "Riptide Director").supported
    _w1g5_resolve_stack(game)
    assert len(alice.hand) - hand_before == (2 if with_ultimus else 1)

    assert game.activate_permanent_ability(
        0, "Timberwatch Elf", target_permanent_ids=[legion.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert legion.effective_power == 2 + elves


@_w1g5_pytest.mark.parametrize("with_ultimus", [False, True])
def test_w1g5_tribal_entry_triggers_and_tap_costs_see_mistform_ultimus(
    set_pool, with_ultimus,
):
    """Totem Speaker ("Whenever a Beast enters, you may gain 3 life") and
    Wirewood Hivemaster ("Whenever another nontoken Elf enters, you may
    create a 1/1 green Insect") both answer the Ultimus entering — and
    neither answers a Human Cleric (Daru Mender) entering. Crookclaw
    Elder's "Tap two untapped Birds you control" can tap the Ultimus as its
    second Bird."""
    entering = "Mistform Ultimus" if with_ultimus else "Daru Mender"
    game, alice, bob, card = _w1g5_table(set_pool, entering)
    _w1g5_put(game, 0, card("Wirewood Hivemaster"))
    _w1g5_put(game, 0, card("Totem Speaker"))     # an Elf: one Insect already
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    def insects():
        return sum(1 for p in game.controlled_by(0) if "Insect" in p.card.name)

    before_life, before_insects = alice.life, insects()
    assert game.queue_from_hand(0, entering).supported
    for _ in range(3):
        _w1g5_resolve_stack(game)
        game.auto_resolve_pending_choices()
    assert alice.life - before_life == (3 if with_ultimus else 0)
    assert insects() - before_insects == (1 if with_ultimus else 0)

    elder = _w1g5_put(game, 0, card("Crookclaw Elder"))
    hand = len(alice.hand)
    result = game.activate_permanent_ability(0, "Crookclaw Elder", ability_index=0)
    _w1g5_resolve_stack(game)
    if with_ultimus:
        assert result.supported and len(alice.hand) == hand + 1
        assert elder.tapped
    else:
        assert not result.supported, "one Bird is not two"

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Libraries, graveyards and exile: a two-card search, a three-zone search for
# a named card, a chosen-type graveyard shuffle, a revealed top card put onto
# the battlefield by type, a dies trigger that exiles itself and returns
# targets, and an exile of every creature until the next end step.

import pytest as _w1g6_pytest

from engine import Game as _w1g6_Game, PlayerState as _w1g6_PlayerState
from engine.models import Permanent as _w1g6_Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve


def _w1g6_card(set_pool, name):
    for code in ("LGN", "ONS", "LEA", "7ED"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g6_game(set_pool, *, library=(), opp_library=(), interactive=False):
    """Two seats in seat 0's precombat main phase, mana costs off."""
    me = _w1g6_PlayerState(
        name="Me", library=[_w1g6_card(set_pool, n) for n in library],
    )
    opp = _w1g6_PlayerState(
        name="Opp",
        library=[_w1g6_card(set_pool, n) for n in (opp_library or ["Forest"] * 5)],
    )
    game = _w1g6_Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(0)
    game._close_current_priority_step()
    game._set_phase_and_step("precombat_main", "main")
    return game, me, opp


def _w1g6_put(game, seat, set_pool, name):
    perm = _w1g6_Permanent(card=_w1g6_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# --- Corpse Harvester -------------------------------------------------------


def _w1g6_harvester(set_pool, *, interactive):
    game, me, _opp = _w1g6_game(
        set_pool,
        library=["Forest", "Withered Wretch", "Forest", "Swamp", "Grizzly Bears"],
        interactive=interactive,
    )
    assert _w1g6_compile(_w1g6_card(set_pool, "Corpse Harvester")).supported
    _w1g6_put(game, 0, set_pool, "Corpse Harvester")
    fodder = _w1g6_put(game, 0, set_pool, "Grizzly Bears")
    result = game.activate_permanent_ability(
        0, "Corpse Harvester", cost_permanent_ids=[fodder.permanent_id],
    )
    assert result.supported, result.details
    assert [c.name for c in me.graveyard] == ["Grizzly Bears"], "the sacrifice is paid"
    (choice,) = game.pending_choices
    assert choice.kind == "search_library"
    return game, me


def test_w1g6_corpse_harvester_finds_a_zombie_and_a_swamp_and_reveals_them(set_pool):
    """"Search your library for a Zombie card and a Swamp card, reveal them,
    put them into your hand, then shuffle." Answered as an interactive seat:
    one pick per printed description, both shown to the table (CR 701.20)."""
    game, me = _w1g6_harvester(set_pool, interactive=True)
    library = [c.name for c in me.library]
    # A pick that fills the Swamp slot with a Forest is no answer.
    assert not game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Withered Wretch")},
        {"zone": "library", "index": library.index("Forest")},
    ])
    # Nor are two cards for one description (the Bears is not a Zombie).
    assert not game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Withered Wretch")},
        {"zone": "library", "index": library.index("Grizzly Bears")},
    ])
    assert game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Withered Wretch")},
        {"zone": "library", "index": library.index("Swamp")},
    ])
    _w1g6_resolve(game)
    assert sorted(c.name for c in me.hand) == ["Swamp", "Withered Wretch"]
    assert sorted(c.name for c in me.library) == ["Forest", "Forest", "Grizzly Bears"]
    assert any(e["cards"] == ["Withered Wretch", "Swamp"] for e in game.reveal_events)
    assert "Me revealed Withered Wretch, Swamp" in game.log


def test_w1g6_corpse_harvester_default_seat_finds_both_and_may_find_one(set_pool):
    """A default seat takes both finds; the ruling (2004-10-04) lets a player
    find fewer, which an interactive seat states with one pick."""
    game, me = _w1g6_harvester(set_pool, interactive=False)
    game.auto_resolve_pending_choices()
    assert sorted(c.name for c in me.hand) == ["Swamp", "Withered Wretch"]

    game, me = _w1g6_harvester(set_pool, interactive=True)
    library = [c.name for c in me.library]
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": library.index("Swamp")}],
    )
    _w1g6_resolve(game)
    assert [c.name for c in me.hand] == ["Swamp"]


# --- Elvish Soultiller ------------------------------------------------------


def _w1g6_soultiller_dies(set_pool, *, interactive):
    game, me, _opp = _w1g6_game(
        set_pool, library=["Forest"] * 3, interactive=interactive,
    )
    me.graveyard.extend(
        _w1g6_card(set_pool, name) for name in (
            "Elvish Warrior", "Llanowar Elves", "Goblin Sky Raider", "Forest",
            "Llanowar Elves",
        )
    )
    assert _w1g6_compile(_w1g6_card(set_pool, "Elvish Soultiller")).supported
    soultiller = _w1g6_put(game, 0, set_pool, "Elvish Soultiller")
    game.sacrifice_permanent(soultiller)
    assert [item.card.name for item in game.stack] == ["Elvish Soultiller"]
    return game, me


def test_w1g6_elvish_soultiller_shuffles_back_only_the_chosen_type(set_pool):
    """"When this creature dies, choose a creature type. Shuffle all creature
    cards of that type from your graveyard into your library." Answered as an
    interactive seat with Goblin: the Goblin goes, the Elves and the land
    stay — the narrowing is the chosen word, not every creature card."""
    game, me = _w1g6_soultiller_dies(set_pool, interactive=True)
    game.resolve_top_of_stack()
    (choice,) = game.pending_choices
    assert choice.kind == "creature_type_choice"
    assert game.confirm_creature_type_choice(0, "Goblin")
    _w1g6_resolve(game)
    assert sorted(c.name for c in me.graveyard) == [
        "Elvish Soultiller", "Elvish Warrior", "Forest", "Llanowar Elves",
        "Llanowar Elves",
    ]
    assert sorted(c.name for c in me.library) == [
        "Forest", "Forest", "Forest", "Goblin Sky Raider",
    ]
    assert "Me shuffled 1 card(s) from their graveyard into their library" in game.log


def test_w1g6_elvish_soultiller_default_names_its_own_commonest_graveyard_type(set_pool):
    """A seat nobody asks names the type its own graveyard holds most of —
    the shuffle is a gift to the chooser — and the Soultiller, an Elf
    Mutant already in the graveyard, goes back with the Elves."""
    game, me = _w1g6_soultiller_dies(set_pool, interactive=False)
    _w1g6_resolve(game)
    assert "Elvish Soultiller: chose elf" in game.log
    assert sorted(c.name for c in me.graveyard) == ["Forest", "Goblin Sky Raider"]
    assert sorted(c.name for c in me.library) == [
        "Elvish Soultiller", "Elvish Warrior", "Forest", "Forest", "Forest",
        "Llanowar Elves", "Llanowar Elves",
    ]


# --- Skirk Drill Sergeant ---------------------------------------------------


def _w1g6_sergeant(set_pool, top, *, interactive, dying="Goblin Sky Raider", seat=0):
    """A Sergeant and three Mountains; *dying* (seat *seat*'s) is sacrificed
    with *top* on top of the Sergeant controller's library. Costs enforced."""
    game, me, opp = _w1g6_game(
        set_pool, library=[top, "Forest", "Forest"], interactive=interactive,
    )
    game.enforce_mana_costs = True
    assert _w1g6_compile(_w1g6_card(set_pool, "Skirk Drill Sergeant")).supported
    for _ in range(3):
        _w1g6_put(game, 0, set_pool, "Mountain")
    sergeant = _w1g6_put(game, 0, set_pool, "Skirk Drill Sergeant")
    victim = sergeant if dying == "Skirk Drill Sergeant" else _w1g6_put(
        game, seat, set_pool, dying,
    )
    game.sacrifice_permanent(victim)
    assert [item.card.name for item in game.stack] == ["Skirk Drill Sergeant"]
    return game, me


def test_w1g6_skirk_drill_sergeant_puts_a_revealed_goblin_onto_the_battlefield(set_pool):
    """"Whenever this creature or another Goblin dies, you may pay {2}{R}. If
    you do, reveal the top card of your library. If it's a Goblin permanent
    card, put it onto the battlefield." Paid as an interactive seat: the three
    Mountains tap and the Goblin on top enters."""
    game, me = _w1g6_sergeant(set_pool, "Goblin Sky Raider", interactive=True)
    _w1g6_resolve(game)
    (offer,) = game.pending_choices
    assert offer.kind == "optional_pay" and offer.data["cost"] == {"R": 1, "generic": 2}
    assert game.confirm_optional_pay(0)
    _w1g6_resolve(game)
    assert "Me revealed Goblin Sky Raider from the top of their library" in game.log
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Goblin Sky Raider", "Mountain", "Mountain", "Mountain",
        "Skirk Drill Sergeant",
    ]
    assert all(p.tapped for p in game.controlled_by(0) if p.card.name == "Mountain")
    assert [c.name for c in me.library] == ["Forest", "Forest"]


def test_w1g6_skirk_drill_sergeant_bins_a_card_that_is_not_a_goblin(set_pool):
    """A creature card that is not a Goblin is no "Goblin permanent card": it
    goes into the graveyard ("Otherwise, put it into your graveyard") — the
    subtype is tested, not merely the creature type it implies."""
    game, me = _w1g6_sergeant(set_pool, "Grizzly Bears", interactive=False)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert "Me revealed Grizzly Bears from the top of their library" in game.log
    assert sorted(c.name for c in me.graveyard) == ["Goblin Sky Raider", "Grizzly Bears"]
    assert not any(p.card.name == "Grizzly Bears" for p in game.all_permanents())


def test_w1g6_skirk_drill_sergeant_declined_reveals_nothing(set_pool):
    """Declining the {2}{R} reveals nothing and moves nothing: "If you do"
    guards the reveal and both destinations behind it."""
    game, me = _w1g6_sergeant(set_pool, "Goblin Sky Raider", interactive=True)
    _w1g6_resolve(game)
    assert game.confirm_optional_pay(0, accept=False)
    _w1g6_resolve(game)
    assert [c.name for c in me.library] == ["Goblin Sky Raider", "Forest", "Forest"]
    assert not any("revealed" in line for line in game.log)
    assert not any(p.tapped for p in game.controlled_by(0))


@_w1g6_pytest.mark.parametrize("dying, seat", [
    ("Skirk Drill Sergeant", 0), ("Goblin Sky Raider", 1),
])
def test_w1g6_skirk_drill_sergeant_triggers_on_itself_and_on_any_goblin(set_pool, dying, seat):
    """"This creature or another Goblin": the Sergeant's own death triggers it
    (leaves-the-battlefield abilities look back, CR 603.10a), and so does an
    opponent's Goblin — the printed noun names no controller."""
    game, me = _w1g6_sergeant(
        set_pool, "Goblin Sky Raider", interactive=False, dying=dying, seat=seat,
    )
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert any(
        p.card.name == "Goblin Sky Raider" for p in game.controlled_by(0)
    ), game.log[-6:]
    assert [c.name for c in me.library] == ["Forest", "Forest"]


# --- Dark Supplicant --------------------------------------------------------


def _w1g6_supplicant(set_pool, where, *, interactive, monkeypatch=None):
    """Scion of Darkness in *where*; the Supplicant activated, three Clerics
    sacrificed. Returns the game, seat 0 and the shuffles counted."""
    game, me, _opp = _w1g6_game(
        set_pool, library=["Forest", "Island", "Swamp"], interactive=interactive,
    )
    scion = _w1g6_card(set_pool, "Scion of Darkness")
    {"hand": me.hand, "graveyard": me.graveyard, "library": me.library}[where].append(scion)
    shuffles = []
    if monkeypatch is not None:
        monkeypatch.setattr(
            "engine.mixins.stack.choices.search.random.shuffle",
            lambda pile: shuffles.append(len(pile)),
        )
    assert _w1g6_compile(_w1g6_card(set_pool, "Dark Supplicant")).supported
    _w1g6_put(game, 0, set_pool, "Dark Supplicant")
    clerics = [
        _w1g6_put(game, 0, set_pool, name)
        for name in ("Blood Celebrant", "Earthblighter", "Deathmark Prelate")
    ]
    result = game.activate_permanent_ability(
        0, "Dark Supplicant", cost_permanent_ids=[p.permanent_id for p in clerics],
    )
    assert result.supported, result.details
    assert {"Blood Celebrant", "Earthblighter", "Deathmark Prelate"} <= {
        c.name for c in me.graveyard
    }
    (choice,) = game.pending_choices
    assert choice.kind == "search_library"
    assert tuple(choice.data["zones"]) == ("library", "graveyard", "hand")
    return game, me, scion, shuffles


@_w1g6_pytest.mark.parametrize("where", ["hand", "graveyard"])
def test_w1g6_dark_supplicant_finds_the_scion_in_hand_or_graveyard(set_pool, where, monkeypatch):
    """"Search your graveyard, hand, and/or library for a card named Scion of
    Darkness and put it onto the battlefield. If you search your library this
    way, shuffle." Answered as an interactive seat naming the zone the Scion
    is in: it enters, and the library — not searched — is not shuffled (the
    ruling, 2004-10-04: "You only shuffle your library if you choose to search
    it")."""
    game, me, scion, shuffles = _w1g6_supplicant(
        set_pool, where, interactive=True, monkeypatch=monkeypatch,
    )
    pile = {"hand": me.hand, "graveyard": me.graveyard}[where]
    index = next(i for i, card in enumerate(pile) if card is scion)
    # A pick that names a zone the card is not in finds a different card,
    # which the name refuses.
    other = "graveyard" if where == "hand" else "hand"
    if len({"hand": me.hand, "graveyard": me.graveyard}[other]) > index:
        assert not game.confirm_search_library(0, index, other)
    assert not game.confirm_search_library(0, 0, "exile"), "never armed for exile"
    assert game.confirm_search_library(0, index, where)
    _w1g6_resolve(game)
    assert any(p.card is scion for p in game.controlled_by(0))
    assert scion not in me.hand and scion not in me.graveyard
    assert [c.name for c in me.library] == ["Forest", "Island", "Swamp"]
    assert shuffles == []
    assert f"Me searched {where} and put Scion of Darkness onto the battlefield" in game.log


def test_w1g6_dark_supplicant_default_seat_finds_it_in_the_library_and_shuffles(set_pool, monkeypatch):
    """A seat nobody asks finds the Scion wherever it is — here the library,
    which it searched, so the library is shuffled."""
    game, me, scion, shuffles = _w1g6_supplicant(
        set_pool, "library", interactive=False, monkeypatch=monkeypatch,
    )
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert any(p.card is scion for p in game.controlled_by(0))
    assert sorted(c.name for c in me.library) == ["Forest", "Island", "Swamp"]
    assert shuffles == [3]


def test_w1g6_dark_supplicant_hand_pick_takes_one_copy(set_pool):
    """Two Scions in hand (one ``CardDefinition`` object, as every deck holds
    copies): a hand find takes exactly one through the hand seam."""
    game, me, scion, _ = _w1g6_supplicant(set_pool, "hand", interactive=True)
    me.hand.append(scion)
    assert game.confirm_search_library(0, 0, "hand")
    _w1g6_resolve(game)
    assert [c.name for c in me.hand] == ["Scion of Darkness"]
    assert sum(p.card is scion for p in game.controlled_by(0)) == 1


def test_w1g6_dark_supplicant_needs_three_clerics(set_pool):
    """"Sacrifice three Clerics": with only one other Cleric there are two in
    all (the Supplicant is a Human Cleric itself), the cost cannot be paid,
    and nothing is sacrificed or searched — the refusal is the result's, not
    the log's (``engine/refusals.py``)."""
    game, me, _opp = _w1g6_game(set_pool, library=["Forest"])
    supplicant = _w1g6_put(game, 0, set_pool, "Dark Supplicant")
    cleric = _w1g6_put(game, 0, set_pool, "Blood Celebrant")
    result = game.activate_permanent_ability(
        0, "Dark Supplicant",
        cost_permanent_ids=[cleric.permanent_id, supplicant.permanent_id],
    )
    assert not result.supported, result.details
    assert me.graveyard == [] and game.pending_choices == []
    assert not supplicant.tapped


# --- Celestial Gatekeeper ---------------------------------------------------


def _w1g6_gatekeeper_dies(set_pool, *, interactive, also_dying=()):
    """Celestial Gatekeeper (and *also_dying*, in one event) sacrificed over a
    graveyard of two Clerics, a Bird and a Bear.

    Inside ``deferring_triggers`` — the window a cost's sacrifices are paid in
    (Dark Supplicant's "Sacrifice three Clerics") — so the trigger goes on the
    stack once every card of the event is in the graveyard (CR 603.3d). A bare
    simultaneous sweep chooses at the fire site instead, before the later
    cards arrive: measured and reported, not this card's to fix."""
    game, me, _opp = _w1g6_game(set_pool, library=["Forest"] * 3, interactive=interactive)
    me.graveyard.extend(
        _w1g6_card(set_pool, name) for name in (
            "Blood Celebrant", "Grizzly Bears", "Aven Envoy", "Earthblighter",
        )
    )
    assert _w1g6_compile(_w1g6_card(set_pool, "Celestial Gatekeeper")).supported
    gatekeeper = _w1g6_put(game, 0, set_pool, "Celestial Gatekeeper")
    others = [_w1g6_put(game, 0, set_pool, name) for name in also_dying]
    with game.deferring_triggers():
        game.sacrifice_permanents([gatekeeper, *others])
    return game, me


def test_w1g6_celestial_gatekeeper_exiles_itself_and_returns_two_birds_or_clerics(set_pool):
    """"When this creature dies, exile it, then return up to two target Bird
    and/or Cleric permanent cards from your graveyard to the battlefield."
    Answered as an interactive seat: the picker offers the Birds and Clerics
    (itself included) and not the Bear; the Gatekeeper is exiled and the two
    chosen enter."""
    game, me = _w1g6_gatekeeper_dies(set_pool, interactive=True)
    (choice,) = game.pending_choices
    assert choice.kind == "trigger_target" and choice.data["max_targets"] == 2
    offered = sorted(t["name"] for t in choice.data["targets"])
    assert offered == [
        "Aven Envoy", "Blood Celebrant", "Celestial Gatekeeper", "Earthblighter",
    ]
    names = [c.name for c in me.graveyard]
    bear = names.index("Grizzly Bears")
    assert not game.confirm_trigger_target(
        0, seat=0, graveyard_indices=[names.index("Aven Envoy"), bear],
    ), "the Bear is no Bird or Cleric"
    assert game.confirm_trigger_target(0, seat=0, graveyard_indices=[
        names.index("Aven Envoy"), names.index("Earthblighter"),
    ])
    _w1g6_resolve(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Aven Envoy", "Earthblighter",
    ]
    assert [c.name for c in me.exile] == ["Celestial Gatekeeper"]
    assert sorted(c.name for c in me.graveyard) == ["Blood Celebrant", "Grizzly Bears"]


def test_w1g6_celestial_gatekeeper_targeting_itself_is_exiled_not_returned(set_pool):
    """The ruling (2004-10-04): "You can choose to target this card as one of
    the two … If you do, it gets exiled and does not get returned." The other
    target still returns — and is the card it named, not the one that slid
    into its slot when the Gatekeeper left the pile."""
    game, me = _w1g6_gatekeeper_dies(set_pool, interactive=True)
    names = [c.name for c in me.graveyard]
    assert game.confirm_trigger_target(0, seat=0, graveyard_indices=[
        names.index("Celestial Gatekeeper"), names.index("Aven Envoy"),
    ])
    _w1g6_resolve(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Aven Envoy"]
    assert [c.name for c in me.exile] == ["Celestial Gatekeeper"]


def test_w1g6_celestial_gatekeeper_target_above_it_in_the_pile_survives_the_exile(set_pool):
    """The Gatekeeper and a Cleric die in one event, the Cleric going in after
    it — so the Cleric's slot is above the Gatekeeper's. Exiling the Gatekeeper
    first slides it down one; the return re-locates it from its stamp and
    returns it, rather than reading the stale slot (out of range, or another
    card)."""
    game, me = _w1g6_gatekeeper_dies(
        set_pool, interactive=True, also_dying=["Deathmark Prelate"],
    )
    names = [c.name for c in me.graveyard]
    assert names.index("Deathmark Prelate") > names.index("Celestial Gatekeeper")
    assert game.confirm_trigger_target(
        0, seat=0, graveyard_indices=[names.index("Deathmark Prelate")],
    )
    _w1g6_resolve(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Deathmark Prelate"]
    assert "Deathmark Prelate" not in [c.name for c in me.graveyard]


def test_w1g6_celestial_gatekeeper_default_seat_returns_two(set_pool):
    """A seat nobody asks names two of the Birds and Clerics as the trigger
    goes on the stack (CR 603.3d) and both return; the Gatekeeper is exiled."""
    game, me = _w1g6_gatekeeper_dies(set_pool, interactive=False)
    _w1g6_resolve(game)
    returned = [p.card.name for p in game.controlled_by(0)]
    assert len(returned) == 2
    assert set(returned) <= {"Aven Envoy", "Blood Celebrant", "Earthblighter"}
    assert [c.name for c in me.exile] == ["Celestial Gatekeeper"]



# --- Planar Guide -----------------------------------------------------------


def _w1g6_planar_guide_board(set_pool):
    """Seat 0: the Guide, a Bears wearing Holy Strength with a +1/+1 counter,
    a Monk ("When this creature enters, you gain 2 life"), a token and a
    Forest. Seat 1: a face-down Krosan Colossus, and a Hill Giant seat 0 has
    stolen. Returns the game and the pieces by name."""
    from engine.control import change_control
    from engine.face_down import turn_face_down
    from engine.aura_attachment import attach_aura
    from engine.named_counters import add_counters
    from engine.tokens import make_token_card

    game, me, opp = _w1g6_game(set_pool, library=["Forest"] * 5)
    assert _w1g6_compile(_w1g6_card(set_pool, "Planar Guide")).supported
    board = {
        name: _w1g6_put(game, 0, set_pool, name)
        for name in ("Planar Guide", "Grizzly Bears", "Venerable Monk", "Forest")
    }
    aura = _w1g6_put(game, 0, set_pool, "Holy Strength")
    attach_aura(aura, board["Grizzly Bears"])
    add_counters(board["Grizzly Bears"], "+1/+1", 1)
    token = _w1g6_Permanent(card=make_token_card("Soldier", 1, 1, "Token Creature — Soldier"))
    token.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(0, token, None)
    colossus = _w1g6_put(game, 1, set_pool, "Krosan Colossus")
    assert turn_face_down(game, colossus)
    giant = _w1g6_put(game, 1, set_pool, "Hill Giant")
    change_control(giant, 0, source=board["Planar Guide"])
    game._recompute_continuous_effects()
    assert game.controller_index_of(giant) == 0
    board.update(token=token, colossus=colossus, giant=giant, aura=aura)
    return game, me, opp, board


def test_w1g6_planar_guide_exiles_every_creature_and_returns_them_at_end_step(set_pool):
    """"{3}{W}, Exile this creature: Exile all creatures. At the beginning of
    the next end step, return those cards to the battlefield under their
    owners' control." Its rulings (2004-10-04, 2005-08-01): the Aura goes to
    the graveyard and the counter is gone, the token does not return, "enters"
    abilities trigger, a face-down creature returns face up — and each card
    comes back under its **owner's** control, so the stolen Giant goes home.
    The Guide, exiled to pay the cost, is not one of "those cards"."""
    game, me, opp, board = _w1g6_planar_guide_board(set_pool)
    result = game.activate_permanent_ability(0, "Planar Guide")
    assert result.supported, result.details
    assert [p.card.name for p in game.all_permanents()] == ["Forest"]
    assert sorted(c.name for c in me.exile) == [
        "Grizzly Bears", "Planar Guide", "Venerable Monk",
    ]
    # The face-down creature is exiled as the card it is (CR 708.9), not as
    # the blank 2/2 it was on the battlefield.
    assert sorted(c.name for c in opp.exile) == ["Hill Giant", "Krosan Colossus"]
    assert [c.name for c in me.graveyard] == ["Holy Strength"]
    life = me.life

    game.resolve_end_step(0)
    _w1g6_resolve(game)
    mine = sorted(p.card.name for p in game.controlled_by(0))
    theirs = sorted(p.card.name for p in game.controlled_by(1))
    assert mine == ["Forest", "Grizzly Bears", "Venerable Monk"]
    assert theirs == ["Hill Giant", "Krosan Colossus"]
    assert [c.name for c in me.exile] == ["Planar Guide"] and opp.exile == []
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    colossus = next(p for p in game.controlled_by(1) if p.card.name == "Krosan Colossus")
    assert colossus.effective_power == 9, "face up, a new object (CR 400.7)"
    assert me.life == life + 2, "the Monk's entry trigger"
    assert not any(p.metadata.get("is_token") for p in game.all_permanents())
    assert (
        "Grizzly Bears, Venerable Monk returned to the battlefield under Me's "
        "control; Krosan Colossus, Hill Giant returned to the battlefield under "
        "Opp's control (Planar Guide)"
    ) in game.log


def test_w1g6_planar_guide_activated_in_the_end_step_returns_at_the_next_one(set_pool):
    """The ruling (2004-10-04): "If the ability is activated during the End
    step, then the creatures do not return until the End step of the
    following turn." The beginning of this end step has passed, so the
    delayed ability waits for the next one there is."""
    game, me, opp, board = _w1g6_planar_guide_board(set_pool)
    game.resolve_end_step(0)
    _w1g6_resolve(game)
    assert game.activate_permanent_ability(0, "Planar Guide").supported
    _w1g6_resolve(game)
    assert [p.card.name for p in game.all_permanents()] == ["Forest"]
    assert game.start_next_turn() == 1
    _w1g6_resolve(game)
    assert [p.card.name for p in game.all_permanents()] == ["Forest"]
    game.resolve_end_step(1)
    _w1g6_resolve(game)
    assert sorted(p.card.name for p in game.all_permanents()) == [
        "Forest", "Grizzly Bears", "Hill Giant", "Krosan Colossus",
        "Venerable Monk",
    ]



# --- Scion of Darkness (drive list) -----------------------------------------


def _w1g6_scion_hits(set_pool, *, interactive):
    """Scion of Darkness attacks unblocked; each graveyard holds a creature
    card. Returns the game once combat damage is dealt."""
    from tests.helpers import declare_attack

    game, me, opp = _w1g6_game(set_pool, library=["Forest"] * 3, interactive=interactive)
    me.graveyard.append(_w1g6_card(set_pool, "Grizzly Bears"))
    opp.graveyard.append(_w1g6_card(set_pool, "Hill Giant"))
    assert _w1g6_compile(_w1g6_card(set_pool, "Scion of Darkness")).supported
    _w1g6_put(game, 0, set_pool, "Scion of Darkness")
    declare_attack(game, 0)
    game.advance_combat_phase()
    assert opp.life == 14
    return game, me, opp


def test_w1g6_scion_of_darkness_takes_from_the_damaged_players_graveyard(set_pool):
    """"Whenever this creature deals combat damage to a player, you may put
    target creature card from that player's graveyard onto the battlefield
    under your control." The picker offers the damaged player's creature card
    and not its controller's own — it reanimated out of its controller's
    graveyard before, the printed owner read as "your"."""
    game, me, opp = _w1g6_scion_hits(set_pool, interactive=True)
    (choice,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert [(t["seat"], t["name"]) for t in choice.data["targets"]] == [(1, "Hill Giant")]
    assert game.confirm_trigger_target(0, seat=1, graveyard_index=0)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert sorted(
        (p.card.name, game.controller_index_of(p)) for p in game.all_permanents()
    ) == [("Hill Giant", 0), ("Scion of Darkness", 0)]
    assert opp.graveyard == [] and [c.name for c in me.graveyard] == ["Grizzly Bears"]


def test_w1g6_scion_of_darkness_default_seat_takes_the_opponents_card(set_pool):
    game, me, opp = _w1g6_scion_hits(set_pool, interactive=False)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert ("Hill Giant", 0) in [
        (p.card.name, game.controller_index_of(p)) for p in game.all_permanents()
    ]
    assert [c.name for c in me.graveyard] == ["Grizzly Bears"]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# --- W1G7: players and odd ends ----------------------------------------------
import pytest as _w1g7_pytest

from engine import Game as _w1g7_Game
from engine.models import Permanent as _w1g7_Permanent
from engine.models import PlayerState as _w1g7_PlayerState

from tests.helpers import _nosick as _w1g7_nosick
from tests.helpers import declare_attack as _w1g7_declare_attack
from tests.helpers import resolve_stack as _w1g7_resolve_stack


#: Where a W1G7 test finds a card by name: Legions first, then Alpha (the
#: lands and the old regulars), then Arabian Nights (Old Man of the Sea).
_W1G7_SETS = ("LGN", "LEA", "ARN")


def _w1g7_card(set_pool, name):
    """A card by name from the first of :data:`_W1G7_SETS` that prints it."""
    for code in _W1G7_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g7_table(set_pool, hands=None, *, libraries=None, seats=2, interactive=()):
    """A *seats*-player table, Alice active, costs unenforced."""
    hands = hands or {}
    libraries = libraries or {}
    names = ["Alice", "Bob", "Cara", "Dan"][:seats]
    players = [
        _w1g7_PlayerState(
            name=name,
            hand=[_w1g7_card(set_pool, c) for c in hands.get(seat, ())],
            library=[
                _w1g7_card(set_pool, c)
                for c in libraries.get(seat, ["Plains"] * 8)
            ],
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g7_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g7_put(game, set_pool, seat, name, *, tapped=False):
    """Put *name* onto *seat*'s battlefield by an effect (never cast)."""
    permanent = _w1g7_Permanent(card=_w1g7_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g7_resolve_stack(game)
    _w1g7_nosick(permanent)
    permanent.tapped = tapped
    return permanent


def _w1g7_finish_combat(game):
    """Step from declare-blockers through the damage, draining each trigger."""
    for _ in range(12):
        _w1g7_resolve_stack(game)
        if game.current_phase != "combat" or game.pending_choices:
            return
        game.advance_combat_phase()


def _w1g7_names(cards):
    return [card.name for card in cards]


# --- Phage the Untouchable ----------------------------------------------------


def test_w1g7_phage_cast_from_a_hand_keeps_its_controller_in_the_game(set_pool):
    """"When Phage enters, if you didn't cast it from your hand, you lose the
    game." Cast from Alice's hand, the intervening-if (CR 603.4) is false when
    the permanent enters, so nothing triggers and nobody loses."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    assert _w1g7_names(p.card for p in game.controlled_by(0)) == ["Phage the Untouchable"]
    assert not game.players[0].lost
    assert any("didn't trigger" in line for line in game.log), game.log[-4:]


def test_w1g7_phage_put_onto_the_battlefield_loses_the_game(set_pool):
    """The ruling (2004-10-04): "Putting it onto the battlefield from your
    hand using a spell or ability will cause you to lose the game." A Phage
    that was never cast has no cast stamp, so its controller loses."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 0, "Phage the Untouchable")
    assert game.players[0].lost
    assert not game.players[1].lost
    assert any("Alice lost the game" in line for line in game.log), game.log[-4:]


def test_w1g7_phage_destroys_what_it_damages_past_regeneration(set_pool):
    """"Whenever Phage deals combat damage to a creature, destroy that
    creature. It can't be regenerated." Drudge Skeletons with two shields
    spends one on the lethal combat damage and the second cannot save it from
    the trigger; a Wall of Stone that survives the damage is destroyed too."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    skeletons = _w1g7_put(game, set_pool, 1, "Drudge Skeletons")
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    for _ in range(2):
        assert game.activate_permanent_ability(
            1, "Drudge Skeletons",
            permanent_index=game.battlefield_index_of(skeletons),
        ).supported
        _w1g7_resolve_stack(game)
    _w1g7_finish_combat(game)
    assert "Drudge Skeletons regenerated" in game.log
    assert "Phage the Untouchable destroyed Drudge Skeletons" in game.log
    assert _w1g7_names(game.players[1].graveyard) == ["Drudge Skeletons"]

    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    _w1g7_put(game, set_pool, 1, "Wall of Stone")
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    _w1g7_finish_combat(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Wall of Stone"]
    assert not game.players[1].lost


def test_w1g7_phage_unblocked_makes_the_damaged_player_lose(set_pool):
    """"Whenever Phage deals combat damage to a player, that player loses the
    game." Bob takes four and loses; Alice, who cast Phage, does not."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    _w1g7_declare_attack(game, 0)
    _w1g7_finish_combat(game)
    assert game.players[1].life == 16
    assert game.players[1].lost
    assert not game.players[0].lost


# --- Riptide Mangler ----------------------------------------------------------


def test_w1g7_riptide_mangler_takes_a_targets_power_and_keeps_it(set_pool):
    """"{1}{U}: This creature's base power becomes equal to target creature's
    power. (This effect lasts indefinitely.)" Layer 7b (CR 613.4b): the 0/3
    becomes 6/3 off a Craw Wurm, toughness untouched; a Giant Growth applies on
    top (the 2015-02-25 ruling); a second activation overwrites the first
    (the other 2015-02-25 ruling); and the write outlasts the turn's
    cleanup."""
    game = _w1g7_table(set_pool, hands={0: ["Giant Growth"]})
    mangler = _w1g7_put(game, set_pool, 0, "Riptide Mangler")
    wurm = _w1g7_put(game, set_pool, 1, "Craw Wurm")
    bears = _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    assert (mangler.effective_power, mangler.effective_toughness) == (0, 3)

    assert game.queue_permanent_ability(
        0, "Riptide Mangler", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (6, 3)
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)

    assert game.cast_from_hand(
        0, "Giant Growth", target_player_index=0,
        target_permanent_ids=[mangler.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (9, 6)

    assert game.queue_permanent_ability(
        0, "Riptide Mangler", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (5, 6)

    game.resolve_cleanup_step(0)
    assert (mangler.effective_power, mangler.effective_toughness) == (2, 3)


def test_w1g7_riptide_mangler_fizzles_when_its_target_leaves(set_pool):
    """CR 608.2b: the Wurm exiled in response leaves the ability with no legal
    target, so it does nothing — the Mangler stays 0/3 rather than reading the
    power of a creature that is gone."""
    game = _w1g7_table(set_pool, hands={0: ["Swords to Plowshares"]})
    mangler = _w1g7_put(game, set_pool, 0, "Riptide Mangler")
    wurm = _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert game.queue_permanent_ability(
        0, "Riptide Mangler", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    assert game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert (mangler.effective_power, mangler.effective_toughness) == (0, 3)
    assert any("every target is illegal" in line for line in game.log)


# --- Seedborn Muse ------------------------------------------------------------


def _w1g7_tapped(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat) if p.tapped)


def test_w1g7_seedborn_muse_untaps_its_controllers_board_in_the_other_step(set_pool):
    """"Untap all permanents you control during each other player's untap
    step." In Bob's untap step Alice untaps everything, including a Basalt
    Monolith ("doesn't untap during your untap step") and a Sunstrike
    Legionnaire ("doesn't untap during your untap step") — the 2004-10-04
    ruling: a restriction printed about its controller's step does not bind
    this one. Bob's own Winter Orb caps *his* step at one land and does not
    touch Alice's lands, which untap in a step that is not hers. In Alice's
    own step the Monolith and the Legionnaire stay tapped and the Orb caps
    her lands at one."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 1, "Grizzly Bears", tapped=True)
    for name in ("Seedborn Muse", "Basalt Monolith", "Sunstrike Legionnaire",
                 "Forest", "Forest"):
        _w1g7_put(game, set_pool, 0, name, tapped=True)
    _w1g7_put(game, set_pool, 1, "Winter Orb")
    _w1g7_put(game, set_pool, 1, "Island", tapped=True)
    _w1g7_put(game, set_pool, 1, "Island", tapped=True)

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert _w1g7_tapped(game, 0) == []
    assert _w1g7_tapped(game, 1) == ["Island"], "Winter Orb still caps Bob's own step"
    assert (
        "Alice untapped 5 permanent(s) during Bob's untap step (Seedborn Muse)"
        in game.log
    )

    for permanent in game.controlled_by(0):
        permanent.tapped = True
    game.active_player_index = 0
    game.resolve_untap_step(0)
    assert _w1g7_tapped(game, 0) == [
        "Basalt Monolith", "Forest", "Sunstrike Legionnaire",
    ]


def test_w1g7_seedborn_muse_gives_old_man_of_the_sea_no_choice(set_pool):
    """The 2007-07-15 ruling: "You have no choice about what untaps." Alice's
    Old Man of the Sea ("You may choose not to untap this creature during your
    untap step") untaps in Bob's step with nobody asked — even with both seats
    interactive — and the Grizzly Bears it held go back to Bob."""
    game = _w1g7_table(set_pool, interactive={0, 1})
    _w1g7_put(game, set_pool, 0, "Seedborn Muse")
    old_man = _w1g7_put(game, set_pool, 0, "Old Man of the Sea")
    bears = _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    assert game.queue_permanent_ability(
        0, "Old Man of the Sea", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert game.controller_index_of(bears) == 0 and old_man.tapped

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert game.pending_choices == []
    assert not old_man.tapped
    assert game.controller_index_of(bears) == 1


def test_w1g7_seedborn_muse_does_nothing_in_a_skipped_step_or_its_own(set_pool):
    """A skipped untap step (Stasis, CR 500.11) is not an untap step at all,
    so the Muse has none to act in. At three seats it acts in each other
    player's step and in no one else's favour: in Cara's step Alice untaps,
    Bob — who has no Muse — does not."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 0, "Seedborn Muse", tapped=True)
    _w1g7_put(game, set_pool, 1, "Stasis")
    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert _w1g7_tapped(game, 0) == ["Seedborn Muse"]

    game = _w1g7_table(set_pool, seats=3)
    _w1g7_put(game, set_pool, 0, "Seedborn Muse", tapped=True)
    _w1g7_put(game, set_pool, 1, "Forest", tapped=True)
    _w1g7_put(game, set_pool, 2, "Forest", tapped=True)
    game.active_player_index = 2
    game.resolve_untap_step(2)
    assert _w1g7_tapped(game, 0) == []
    assert _w1g7_tapped(game, 1) == ["Forest"]
    assert _w1g7_tapped(game, 2) == []


# --- Goblin Assassin ----------------------------------------------------------


def _w1g7_rig_coins(monkeypatch, faces):
    """Each flip the handler makes, in order: True is heads."""
    queue = list(faces)
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda *a, **k: queue.pop(0)
    )
    return queue


def _w1g7_board(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g7_goblin_assassin_tails_sacrifices_heads_does_not(set_pool, monkeypatch):
    """"Whenever this creature or another Goblin enters, each player flips a
    coin. Each player whose coin comes up tails sacrifices a creature of their
    choice." Alice's coin comes up heads and Bob's tails: only Bob gives up a
    creature (the cheaper, by the nobody-asked default), and nobody wins or
    loses a flip (the 2004-10-04 ruling) — the log names faces, not wins."""
    coins = _w1g7_rig_coins(monkeypatch, [True, False])
    game = _w1g7_table(set_pool, hands={0: ["Goblin Assassin"]})
    _w1g7_put(game, set_pool, 0, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert game.cast_from_hand(0, "Goblin Assassin").supported
    _w1g7_resolve_stack(game)
    assert coins == []
    assert _w1g7_board(game, 0) == ["Goblin Assassin", "Grizzly Bears"]
    assert _w1g7_board(game, 1) == ["Craw Wurm"]
    assert "Goblin Assassin: Alice flipped heads" in game.log
    assert "Goblin Assassin: Bob flipped tails" in game.log
    assert not any("won the coin flip" in line for line in game.log)


def test_w1g7_goblin_assassin_asks_each_tails_seat_which_creature(set_pool, monkeypatch):
    """Both coins tails, both seats interactive: each is asked for a creature
    of their choice, and each answer is what goes. Alice may give up the
    Assassin itself."""
    _w1g7_rig_coins(monkeypatch, [False, False])
    game = _w1g7_table(
        set_pool, hands={0: ["Goblin Assassin"]}, interactive={0, 1},
    )
    _w1g7_put(game, set_pool, 0, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Grizzly Bears")
    _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert game.cast_from_hand(0, "Goblin Assassin").supported
    game.resolve_top_of_stack()
    assert not game.resolve_top_of_stack(), "the trigger waits for its answers"
    assert sorted(c.player_index for c in game.pending_choices if c.kind == "sacrifice") == [0, 1]
    assassin = next(
        p for p in game.controlled_by(0) if p.card.name == "Goblin Assassin"
    )
    wurm = next(p for p in game.controlled_by(1) if p.card.name == "Craw Wurm")
    assert game.confirm_sacrifice(0, [game.battlefield_index_of(assassin)])
    assert game.confirm_sacrifice(1, [game.battlefield_index_of(wurm)])
    _w1g7_resolve_stack(game)
    assert _w1g7_board(game, 0) == ["Grizzly Bears"]
    assert _w1g7_board(game, 1) == ["Grizzly Bears"]


def test_w1g7_goblin_assassin_hears_another_goblin_and_no_one_else(set_pool, monkeypatch):
    """Another Goblin entering (Mons's Goblin Raiders) fires it again; a Craw
    Wurm entering fires nothing — no coin is drawn for it."""
    coins = _w1g7_rig_coins(monkeypatch, [True, True])
    game = _w1g7_table(set_pool, hands={0: ["Goblin Assassin"]})
    _w1g7_put(game, set_pool, 0, "Grizzly Bears")
    assert game.cast_from_hand(0, "Goblin Assassin").supported
    _w1g7_resolve_stack(game)
    assert coins == [] and _w1g7_board(game, 0) == ["Goblin Assassin", "Grizzly Bears"]

    coins.extend([False, True])
    _w1g7_put(game, set_pool, 0, "Mons's Goblin Raiders")
    assert coins == []
    assert len(game.players[0].graveyard) == 1
    assert len(_w1g7_board(game, 0)) == 2

    _w1g7_put(game, set_pool, 1, "Craw Wurm")
    assert _w1g7_board(game, 1) == ["Craw Wurm"]


# --- Hollow Specter -----------------------------------------------------------

_W1G7_BOB_HAND = ["Lightning Bolt", "Plains", "Shivan Dragon", "Island", "Giant Growth"]


def _w1g7_specter_hits(set_pool, bob_hand, swamps, *, interactive):
    """Alice's Hollow Specter connects with Bob; returns the game with the
    trigger's resolution started and held on Alice's prompt. Alice must be
    interactive: a seat nobody asks is answered as the trigger resolves."""
    game = _w1g7_table(set_pool, hands={1: bob_hand}, interactive=interactive)
    _w1g7_put(game, set_pool, 0, "Hollow Specter")
    for _ in range(swamps):
        _w1g7_put(game, set_pool, 0, "Swamp")
    _w1g7_declare_attack(game, 0)
    for _ in range(6):
        if game.stack:
            break
        game.advance_combat_phase()
    assert [item.card.name for item in game.stack] == ["Hollow Specter"]
    game.resolve_top_of_stack()
    return game


def test_w1g7_hollow_specter_x_paid_then_shown_then_picked(set_pool):
    """"…you may pay {X}. If you do, that player reveals X cards from their
    hand and you choose one of them. That player discards that card." The
    ruling (2004-10-04): "You decide on the value of X and pay {X} during
    resolution." Alice names 2 and two Swamps tap; Bob picks the two he shows
    (CR 608.2c); Alice may take only one of those, and Bob discards it."""
    game = _w1g7_specter_hits(set_pool, _W1G7_BOB_HAND, 3, interactive={0, 1})
    assert game.players[1].life == 18
    assert game.pending_choice_of("pay_any_amount", 0) is not None
    assert not game.confirm_pay_any_amount(0, 4), "three Swamps cannot pay {4}"
    assert game.confirm_pay_any_amount(0, 2)
    tapped = [p for p in game.controlled_by(0) if p.tapped and p.card.name == "Swamp"]
    assert len(tapped) == 2
    shown = game.pending_choice_of("choose_cards_in_hand", 1)
    assert shown is not None and shown.data["count"] == 2
    assert game.confirm_choose_cards_in_hand(1, [1, 2])
    pick = game.pending_choice_of("revealed_hand_pick", 0)
    assert pick is not None and pick.data["legal_indices"] == [1, 2]
    assert not game.confirm_revealed_hand_pick(0, 0), "Lightning Bolt was never shown"
    assert game.confirm_revealed_hand_pick(0, 2)
    _w1g7_resolve_stack(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Shivan Dragon"]
    assert _w1g7_names(game.players[1].hand) == [
        "Lightning Bolt", "Plains", "Island", "Giant Growth",
    ]
    assert game.stack == [] and game.pending_choices == []


def test_w1g7_hollow_specter_x_past_the_hand_shows_it_all(set_pool):
    """X larger than Bob's hand reveals every card he has (CR 608.2's as much
    as possible) and nobody asks him which; Alice picks among them."""
    game = _w1g7_specter_hits(
        set_pool, ["Plains", "Shivan Dragon"], 4, interactive={0},
    )
    assert game.confirm_pay_any_amount(0, 4)
    assert game.pending_choice_of("choose_cards_in_hand", 1) is None
    pick = game.pending_choice_of("revealed_hand_pick", 0)
    assert pick is not None and pick.data["legal_indices"] == [0, 1]
    assert game.confirm_revealed_hand_pick(0, 1)
    _w1g7_resolve_stack(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Shivan Dragon"]
    assert _w1g7_names(game.players[1].hand) == ["Plains"]


def test_w1g7_hollow_specter_x_zero_discards_nothing(set_pool):
    """The ruling (2004-10-04): "X can be zero, but then that player discards
    nothing." A seat nobody asks pays nothing — the stated default of the
    any-amount payment — and Bob keeps his hand; so does an interactive Alice
    who names 0."""
    game = _w1g7_table(set_pool, hands={1: _W1G7_BOB_HAND})
    _w1g7_put(game, set_pool, 0, "Hollow Specter")
    for _ in range(3):
        _w1g7_put(game, set_pool, 0, "Swamp")
    _w1g7_declare_attack(game, 0)
    _w1g7_finish_combat(game)
    assert game.players[1].life == 18
    assert _w1g7_names(game.players[1].hand) == _W1G7_BOB_HAND
    assert "Alice paid no mana" in game.log

    game = _w1g7_specter_hits(set_pool, _W1G7_BOB_HAND, 3, interactive={0, 1})
    assert game.confirm_pay_any_amount(0, 0)
    _w1g7_resolve_stack(game)
    assert _w1g7_names(game.players[1].hand) == _W1G7_BOB_HAND
    assert not any(p.tapped for p in game.controlled_by(0) if p.card.name == "Swamp")


# --- Drive list: Dreamborn Muse -----------------------------------------------


@_w1g7_pytest.mark.parametrize("controller", [0, 1])
def test_w1g7_dreamborn_muse_mills_each_player_by_their_own_hand(set_pool, controller):
    """"At the beginning of each player's upkeep, that player mills X cards,
    where X is the number of cards in their hand." Alice holds one card and Bob
    three; whoever controls the Muse, Alice mills one in her upkeep and Bob
    three in his. "Their" is the upkeep's player (CR 603.10) — it used to be
    read as the Muse controller's opponent, so both players milled the same
    number."""
    game = _w1g7_table(
        set_pool, hands={0: ["Plains"], 1: ["Island", "Island", "Island"]},
    )
    _w1g7_put(game, set_pool, controller, "Dreamborn Muse")
    for seat in (0, 1):
        game.active_player_index = seat
        game.resolve_upkeep(seat)
        _w1g7_resolve_stack(game)
    assert len(game.players[0].graveyard) == 1
    assert len(game.players[1].graveyard) == 3
    assert len(game.players[0].library) == 7 and len(game.players[1].library) == 5

# ==== end W1G7 ======================================================
