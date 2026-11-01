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

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
