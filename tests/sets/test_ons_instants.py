"""Onslaught instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# Face-down permanents acted on by a spell (CR 708): Backslide turns a creature
# with a morph ability face down, Break Open turns an opponent's face-down
# creature face up for free, and Spy Network looks at one player's hidden
# objects — each driven through the cast path, picker included.

import pytest as _w1g2_pytest

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine import targeting as _w1g2_targeting
from engine.card_loader import load_catalog as _w1g2_load_catalog
from engine.copies import become_copy as _w1g2_become_copy
from engine.face_down import (face_down_card as _w1g2_face_down_card,
                              face_up_morph_cost as _w1g2_face_up_morph_cost,
                              hidden_card_of as _w1g2_hidden_card_of,
                              is_face_down as _w1g2_is_face_down)
from engine.mana_payment import mana_cost_from_symbols as _w1g2_symbols
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from engine.pt import add_plus1_counters as _w1g2_add_plus1
from engine.special_actions import (
    take_permanent_special_action as _w1g2_take_special_action)
from tests.helpers import resolve_stack as _w1g2_resolve_stack

_W1G2_CATALOG = {card.name: card for card in _w1g2_load_catalog()}


def _w1g2_game(mine=(), theirs=(), hand=(), *, enforce=False):
    p1 = _W1G2PlayerState(name="A", hand=list(hand), battlefield=list(mine),
                          library=[_W1G2_CATALOG["Island"]] * 10)
    p2 = _W1G2PlayerState(name="B", battlefield=list(theirs),
                          library=[_W1G2_CATALOG["Island"]] * 10)
    game = _W1G2Game(players=[p1, p2])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    return game, p1, p2


def _w1g2_permanent(card, *, face_down=False):
    permanent = _W1G2Permanent(card=_w1g2_face_down_card(card) if face_down else card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g2_turn_up_for(game, seat, permanent, cost):
    """CR 702.37e with *cost* in the pool and nothing else."""
    pool = game.players[seat].mana_pool
    for symbol, count in _w1g2_symbols(cost).items():
        key = "C" if symbol == "generic" else symbol
        pool[key] = pool.get(key, 0) + count
    game.priority_player_index = seat
    refusal = _w1g2_take_special_action(game, seat, permanent, "turn_face_up")
    assert refusal is None, refusal
    assert sum(pool.values()) == 0


def _w1g2_cast_offers(game, seat, card):
    """What the cast picker offers *card*, as ``(seat, battlefield index)``."""
    spec = _w1g2_targeting.derive_cast_spec(card, _w1g2_compile(card))
    assert spec is not None, card.name
    return [
        (entry["seat"], entry["index"])
        for entry in game._enumerate_targets(seat, card, spec, for_cast=True)
    ]


# --- Backslide -------------------------------------------------------------


def test_w1g2_backslide_turns_a_morph_creature_face_down_and_it_keeps_its_state(set_pool):
    """"Turn target creature with a morph ability face down." The opponent's
    face-up Exalted Angel, tapped, with a +1/+1 counter and 1 damage, becomes
    the face-down 2/2 (CR 708.2a) — the same permanent with all of it still
    on (a 3/3 with 1 damage, tapped) — and its controller turns it face up
    again for its morph cost {2}{W}{W} (CR 702.37e)."""
    ons = set_pool("ONS")
    angel = _w1g2_permanent(ons["Exalted Angel"])
    angel.tapped = True
    _w1g2_add_plus1(angel, 1)
    angel.damage_marked = 1
    game, _p1, _p2 = _w1g2_game(theirs=[angel], hand=[ons["Backslide"]])
    identity = angel.permanent_id
    result = game.queue_from_hand(
        0, "Backslide", target_player_index=1, target_permanent_ids=[angel.permanent_id],
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g2_is_face_down(angel) and angel.permanent_id == identity
    assert (angel.effective_power, angel.effective_toughness) == (3, 3)
    assert angel.tapped and angel.damage_marked == 1 and game.is_on_battlefield(angel)
    assert not angel.has_keyword("flying")
    assert _w1g2_hidden_card_of(angel) is ons["Exalted Angel"]

    _w1g2_turn_up_for(game, 1, angel, "{2}{W}{W}")
    assert angel.card is ons["Exalted Angel"] and angel.has_keyword("flying")
    assert (angel.effective_power, angel.effective_toughness) == (5, 6)


def test_w1g2_backslide_kills_a_turned_down_creature_its_damage_now_exceeds(set_pool):
    """Damage stays on the permanent (CR 708.8's same object), so a 5/5
    Skittish Valesk with 3 damage on it is a 2/2 with 3 damage once face down
    — and dies to CR 704.5g; it goes to the graveyard as the card it is
    (CR 708.9)."""
    ons = set_pool("ONS")
    valesk = _w1g2_permanent(ons["Skittish Valesk"])
    valesk.damage_marked = 3
    game, _p1, p2 = _w1g2_game(theirs=[valesk], hand=[ons["Backslide"]])
    assert game.queue_from_hand(
        0, "Backslide", target_player_index=1, target_permanent_ids=[valesk.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(valesk)
    assert [c.name for c in p2.graveyard] == ["Skittish Valesk"]


def test_w1g2_backslide_is_refused_at_a_creature_without_morph_or_already_face_down(set_pool):
    """The picker offers the morph creature and nothing else: a Grizzly Bears
    has no morph ability, and a face-down creature has no text and so none
    either (CR 708.2a — which is CR 708.2b's "can't be turned face down"
    reached at announcement). Either named, the cast is refused before any
    mana is spent (CR 601.2c)."""
    ons = set_pool("ONS")
    angel = _w1g2_permanent(ons["Exalted Angel"])
    bears = _w1g2_permanent(_W1G2_CATALOG["Grizzly Bears"])
    hidden = _w1g2_permanent(ons["Krosan Colossus"], face_down=True)
    game, p1, _p2 = _w1g2_game(theirs=[angel, bears, hidden], hand=[ons["Backslide"]],
                               enforce=True)
    assert _w1g2_cast_offers(game, 0, ons["Backslide"]) == [(1, 0)]
    p1.mana_pool.update({"U": 1, "C": 1})
    for refused in (bears, hidden):
        result = game.queue_from_hand(
            0, "Backslide", target_player_index=1,
            target_permanent_ids=[refused.permanent_id],
        )
        assert not result.supported
        assert [c.name for c in p1.hand] == ["Backslide"]
        assert sum(p1.mana_pool.values()) == 2, "nothing paid for a refused cast"


def test_w1g2_backslide_on_a_clone_of_a_morph_creature(set_pool):
    """A face-up Clone copying a morph creature has the morph ability it
    copied (CR 707.2: copiable values include the text), so Backslide may
    turn it face down; face down it is a 2/2 like any other (CR 708.10); and
    because face up it *would* have a morph cost — its copiable values become
    the copied ones again (CR 708.10's last sentence) — it is turned face up
    for the copied cost (CR 702.37e: "what the permanent's morph cost would be
    if it were face up"), as the Exalted Angel it copied."""
    ons = set_pool("ONS")
    angel = _w1g2_permanent(ons["Exalted Angel"])
    clone = _w1g2_permanent(_W1G2_CATALOG["Clone"])
    # Copied before the board is built: a bare Clone is a 0/0.
    _w1g2_become_copy(clone, angel)
    game, _p1, _p2 = _w1g2_game(theirs=[angel, clone], hand=[ons["Backslide"]])
    assert clone.effective_card.name == "Exalted Angel"
    assert (1, 1) in _w1g2_cast_offers(game, 0, ons["Backslide"])
    assert game.queue_from_hand(
        0, "Backslide", target_player_index=1, target_permanent_ids=[clone.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_is_face_down(clone)
    assert (clone.effective_power, clone.effective_toughness) == (2, 2)
    assert clone.effective_card.name != "Exalted Angel"
    assert _w1g2_face_up_morph_cost(clone) == "{2}{W}{W}"

    _w1g2_turn_up_for(game, 1, clone, "{2}{W}{W}")
    assert not _w1g2_is_face_down(clone)
    assert clone.effective_card.name == "Exalted Angel" and clone.has_keyword("flying")


# --- Break Open ------------------------------------------------------------


def test_w1g2_break_open_turns_an_opponents_face_down_creature_up_for_free(set_pool):
    """"Turn target face-down creature an opponent controls face up." Its
    2004-10-04 ruling: "The player does not have to pay the Morph cost (if
    any) of the creature." The face-down Krosan Colossus is a 9/9 for the
    Break Open's {1}{R}; the reveal is public."""
    ons = set_pool("ONS")
    colossus = _w1g2_permanent(ons["Krosan Colossus"], face_down=True)
    game, p1, p2 = _w1g2_game(theirs=[colossus], hand=[ons["Break Open"]], enforce=True)
    p1.mana_pool.update({"R": 1, "C": 1})
    result = game.queue_from_hand(
        0, "Break Open", target_player_index=1, target_permanent_ids=[colossus.permanent_id],
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    assert sum(p1.mana_pool.values()) == 0 and sum(p2.mana_pool.values()) == 0
    assert not _w1g2_is_face_down(colossus)
    assert (colossus.effective_power, colossus.effective_toughness) == (9, 9)
    assert any("it is Krosan Colossus (Break Open)" in line for line in game.log)


def test_w1g2_break_open_offers_only_an_opponents_face_down_creature(set_pool):
    """The picker holds every word: not the caster's own face-down creature
    ("an opponent controls"), not a face-up one ("face-down"). Named, both are
    refused at announcement (CR 601.2c)."""
    ons = set_pool("ONS")
    theirs_down = _w1g2_permanent(ons["Exalted Angel"], face_down=True)
    theirs_up = _w1g2_permanent(_W1G2_CATALOG["Grizzly Bears"])
    mine_down = _w1g2_permanent(ons["Krosan Colossus"], face_down=True)
    game, p1, _p2 = _w1g2_game([mine_down], [theirs_down, theirs_up],
                               hand=[ons["Break Open"]])
    assert _w1g2_cast_offers(game, 0, ons["Break Open"]) == [(1, 0)]
    for seat, refused in ((0, mine_down), (1, theirs_up)):
        result = game.queue_from_hand(
            0, "Break Open", target_player_index=seat,
            target_permanent_ids=[refused.permanent_id],
        )
        assert not result.supported
    assert _w1g2_is_face_down(mine_down) and [c.name for c in p1.hand] == ["Break Open"]


def test_w1g2_break_open_does_nothing_to_a_creature_already_turned_up_in_response(set_pool):
    """The target is turned face up for its morph cost before Break Open
    resolves: it is no longer a face-down creature (CR 608.2b), so the spell
    does nothing — no second "turned face up" and no error."""
    ons = set_pool("ONS")
    angel = _w1g2_permanent(ons["Exalted Angel"], face_down=True)
    game, _p1, _p2 = _w1g2_game(theirs=[angel], hand=[ons["Break Open"]])
    assert game.queue_from_hand(
        0, "Break Open", target_player_index=1, target_permanent_ids=[angel.permanent_id],
    ).supported
    assert len(game.stack) == 1
    _w1g2_turn_up_for(game, 1, angel, "{2}{W}{W}")
    turned = sum("turned a face-down creature face up" in line for line in game.log)
    _w1g2_resolve_stack(game)
    assert sum("turned a face-down creature face up" in line for line in game.log) == turned
    assert angel.card is ons["Exalted Angel"]


# --- Spy Network -----------------------------------------------------------


def test_w1g2_spy_network_looks_at_one_players_hidden_cards_then_orders_your_top_four(set_pool):
    """"Look at target player's hand, the top card of that player's library,
    and any face-down creatures they control. Look at the top four cards of
    your library, then put them back in any order." Every look is a prompt
    owed by the caster alone, in printed order, and the log names none of what
    was seen; the last answer rearranges the caster's own top four."""
    ons = set_pool("ONS")
    colossus = _w1g2_permanent(ons["Krosan Colossus"], face_down=True)
    angel = _w1g2_permanent(ons["Exalted Angel"], face_down=True)
    bears = _w1g2_permanent(_W1G2_CATALOG["Grizzly Bears"])
    game, p1, p2 = _w1g2_game(theirs=[colossus, angel, bears], hand=[ons["Spy Network"]])
    game.interactive_seats = {0}
    p2.hand[:] = [_W1G2_CATALOG["Lightning Bolt"], _W1G2_CATALOG["Shock"]]
    p2.library[:] = [_W1G2_CATALOG["Forest"]] + [_W1G2_CATALOG["Island"]] * 4
    mine = ["Swamp", "Plains", "Mountain", "Forest"]
    p1.library[:] = [_W1G2_CATALOG[name] for name in mine] + [_W1G2_CATALOG["Island"]]

    result = game.queue_from_hand(0, "Spy Network", target_player_index=1)
    assert result.supported, result.details
    game.resolve_top_of_stack()
    assert game.pending_choice_of("hand_reveal", 0).data["card_names"] == [
        "Lightning Bolt", "Shock",
    ]
    peek = game.pending_choice_of("reorder_library", 0)
    assert peek.data["target_index"] == 1 and peek.data["top_count"] == 1
    assert not peek.data["may_reorder"]
    assert game.resolve_pending_choice("reorder_library", 0, new_order=[0], shuffle=False)

    look = game.pending_choice_of("face_down_look", 0)
    assert look is not None and look.data["permanent_ids"] == [
        colossus.permanent_id, angel.permanent_id,
    ]
    assert game.pending_choice_of("face_down_look", 1) is None
    own = game.pending_choice_of("reorder_library", 0)
    assert own.data["target_index"] == 0 and own.data["top_count"] == 4
    assert game.resolve_pending_choice("reorder_library", 0, new_order=[3, 2, 1, 0], shuffle=False)
    assert [c.name for c in p1.library[:4]] == list(reversed(mine))
    assert _w1g2_is_face_down(colossus) and _w1g2_is_face_down(angel)
    for secret in ("Krosan Colossus", "Exalted Angel", "Lightning Bolt", "Forest"):
        assert not any(secret in line for line in game.log), secret
    game.dismiss_face_down_look(0)
    game.dismiss_hand_reveal(0)
    _w1g2_resolve_stack(game)
    assert [c.name for c in p1.graveyard] == ["Spy Network"]


def test_w1g2_spy_network_on_a_player_with_no_face_down_creature(set_pool):
    """"Any face-down creatures" admits none: the look over an empty set
    shows nothing and arms nothing, and the spell resolves."""
    ons = set_pool("ONS")
    game, p1, _p2 = _w1g2_game(theirs=[_w1g2_permanent(_W1G2_CATALOG["Grizzly Bears"])],
                               hand=[ons["Spy Network"]])
    assert game.queue_from_hand(0, "Spy Network", target_player_index=1).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    assert any("controls no face-down creatures" in line for line in game.log)
    assert [c.name for c in p1.graveyard] == ["Spy Network"]


@_w1g2_pytest.mark.parametrize("name", ["Backslide", "Break Open", "Spy Network"])
def test_w1g2_the_face_down_instants_compile_whole(set_pool, name):
    """Each spell line is an instruction (Backslide compiled 'supported' on its
    cycling line alone before this, and did nothing when cast)."""
    program = _w1g2_compile(set_pool("ONS")[name])
    assert program.supported and program.instructions, (name, program.reason)

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# --- W1G3: cycling triggers (CR 702.29c) and the cycling instants -----------
#
# "When you cycle this card, …" is the cycled card's own triggered ability,
# announced where the cycling ability's discard cost is paid
# (`CardActivationMixin._announce_cycle`) and asked of the card in the
# graveyard. Each test cycles the card, resolves the trigger **alone** — the
# cycling ability is still under it, so nothing has been drawn yet (the
# 2022-12-08 rulings) — reads the board, then lets the draw resolve.
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import _mk_creature_card, resolve_stack


def _w1g3_table(set_pool, *hand, opponent_hand=(), library=5, interactive=()):
    """Alice (seat 0, active) holding *hand*; Bob holding *opponent_hand*."""
    ons = set_pool("ONS")
    filler = ons["Plains"]
    alice = PlayerState(
        name="Alice", hand=[ons[name] for name in hand], library=[filler] * library,
    )
    bob = PlayerState(
        name="Bob", hand=[ons[name] for name in opponent_hand],
        library=[filler] * library,
    )
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game, alice, bob


def _w1g3_put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g3_cycle_and_resolve_trigger(game, name, *, accept=True):
    """Cycle *name* from seat 0 and resolve its trigger — only its trigger.

    Asserts the trigger is above the cycling ability, answers the "you may"
    (*accept*), and returns with the cycling ability still on the stack.
    """
    assert game.activate_from_hand(0, name).supported
    assert game.stack[-1].ability_text.startswith("When you cycle this card")
    assert game.stack[-2].ability_text.endswith("Discard this card: Draw a card.")
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    if offer is not None:
        assert game._resolve_optional_pay(offer, accept, None)
    game.auto_resolve_pending_choices()
    assert len(game.stack) == 1, "the cycling ability is still waiting to draw"


def _w1g3_resolve_cycle_trigger_alone(game):
    """Resolve the trigger on top of the cycling ability and take its "you
    may", leaving the draw on the stack."""
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    if offer is not None:
        assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()
    assert len(game.stack) == 1


def test_w1g3_renewed_faith_cycled_gains_2_life_before_the_draw(set_pool):
    """"When you cycle this card, you may gain 2 life." — not the spell's 6."""
    game, alice, _bob = _w1g3_table(set_pool, "Renewed Faith")

    _w1g3_cycle_and_resolve_trigger(game, "Renewed Faith")
    assert alice.life == 22
    assert alice.hand == [] and len(alice.library) == 5

    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]
    assert [c.name for c in alice.graveyard] == ["Renewed Faith"]
    assert alice.life == 22


def test_w1g3_renewed_faith_declined_still_draws(set_pool):
    game, alice, _bob = _w1g3_table(set_pool, "Renewed Faith")

    _w1g3_cycle_and_resolve_trigger(game, "Renewed Faith", accept=False)
    resolve_stack(game)
    assert alice.life == 20
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_sunfire_balm_cycled_shields_the_creature_its_controller_names(set_pool):
    """"…you may prevent the next 1 damage that would be dealt to any target
    this turn." Alice is asked for the target as the trigger goes on the stack
    (CR 603.3d) and names her own Bear; a Shock then marks only 1 of its 2."""
    game, alice, bob = _w1g3_table(
        set_pool, "Sunfire Balm", opponent_hand=["Shock"], interactive={0},
    )
    bear = _w1g3_put(game, 0, _mk_creature_card("Bear", 2, 2))

    assert game.activate_from_hand(0, "Sunfire Balm").supported
    asked = game.pending_choice_of("trigger_target", 0)
    offered = {(entry["kind"], entry.get("seat"), entry.get("permanent_id"))
               for entry in asked.data["targets"]}
    assert offered == {
        ("player", 0, None), ("player", 1, None),
        ("permanent", 0, bear.permanent_id),
    }
    assert game.resolve_pending_choice("trigger_target", 0, permanent_id=bear.permanent_id)
    assert game.stack[-1].target_permanent_id == [bear.permanent_id]

    # The trigger resolves and stops to ask; it stays on the stack (CR 608.2)
    # until the "you may" is answered, and only then does the draw come.
    assert game.resolve_top_of_stack(pause_for_choices=True)
    assert len(game.stack) == 2 and alice.hand == []
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    assert len(game.stack) == 1
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]

    game.interactive_seats = set()
    assert game.queue_from_hand(1, "Shock", target_permanent_ids=[bear.permanent_id]).supported
    resolve_stack(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(bear)
    assert bear.damage_marked == 1
    assert "Prevented 1 damage to Bear" in game.log


def test_w1g3_sunfire_balm_cycled_by_a_seat_nobody_asks_shields_itself(set_pool):
    """The default a non-interactive seat takes for "any target" is the
    standing opposing seat — except for a gift, which this is: the AI and a
    headless seat shield their own face, not the opponent's
    (`TriggerChoicesMixin._default_trigger_target`)."""
    game, alice, bob = _w1g3_table(set_pool, "Sunfire Balm", opponent_hand=["Shock"])

    assert game.activate_from_hand(0, "Sunfire Balm").supported
    assert game.stack[-1].target_player_index == 0
    _w1g3_resolve_cycle_trigger_alone(game)
    resolve_stack(game)

    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    resolve_stack(game)
    assert alice.life == 19, "1 of the Shock's 2 was prevented"


def test_w1g3_choking_tethers_cycled_taps_a_creature_before_the_draw(set_pool):
    game, alice, _bob = _w1g3_table(set_pool, "Choking Tethers")
    theirs = _w1g3_put(game, 1, _mk_creature_card("Attacker", 3, 3))

    _w1g3_cycle_and_resolve_trigger(game, "Choking Tethers")
    assert theirs.tapped
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_complicate_cycled_counters_a_spell_its_controller_cannot_pay_for(set_pool):
    """Bob's Shock is on the stack; Alice cycles Complicate in response. The
    trigger targets the Shock (the cycling ability under it is no spell), Bob
    has no mana for the {1}, and the Shock is countered before Alice draws."""
    game, alice, bob = _w1g3_table(set_pool, "Complicate", opponent_hand=["Shock"])
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported

    assert game.activate_from_hand(0, "Complicate").supported
    trigger = game.stack[-1]
    assert trigger.target_stack_item is game.stack[0]
    assert game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    assert [c.name for c in bob.graveyard] == ["Shock"]
    assert [item.card.name for item in game.stack] == ["Complicate"]

    resolve_stack(game)
    assert alice.life == 20
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_complicate_cycled_is_paid_off_by_a_controller_with_the_mana(set_pool):
    """The same, with an untapped Mountain beside Bob: he pays {1} and the
    Shock resolves."""
    game, alice, bob = _w1g3_table(set_pool, "Complicate", opponent_hand=["Shock"])
    game.enforce_mana_costs = True
    mountain = _w1g3_put(game, 1, set_pool("ONS")["Mountain"])
    bob.mana_pool["R"] = 1
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    alice.mana_pool.update({"C": 2, "U": 1})

    assert game.activate_from_hand(0, "Complicate").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert mountain.tapped, "Bob tapped it to pay"
    assert alice.life == 18, game.log
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_complicate_cycled_with_no_spell_on_the_stack_just_draws(set_pool):
    """"You can cycle this card even if there are no legal targets for the
    triggered ability." (2022-12-08.) CR 603.3d takes the trigger off."""
    game, alice, _bob = _w1g3_table(set_pool, "Complicate")
    assert game.activate_from_hand(0, "Complicate").supported
    assert [item.ability_text for item in game.stack] == [
        "{2}{U}, Discard this card: Draw a card."
    ]
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_death_pulse_cycled_kills_a_one_toughness_creature(set_pool):
    game, alice, bob = _w1g3_table(set_pool, "Death Pulse")
    weenie = _w1g3_put(game, 1, _mk_creature_card("Weenie", 1, 1))

    _w1g3_cycle_and_resolve_trigger(game, "Death Pulse")
    game.check_state_based_actions()
    assert not game.is_on_battlefield(weenie)
    assert [c.name for c in bob.graveyard] == ["Weenie"]
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_solar_blast_cycled_deals_1_damage_from_the_graveyard(set_pool):
    """"…you may have it deal 1 damage to any target." "It" is the card, in
    the graveyard by now; the seat nobody asks aims at the opponent."""
    game, alice, bob = _w1g3_table(set_pool, "Solar Blast")

    _w1g3_cycle_and_resolve_trigger(game, "Solar Blast")
    assert bob.life == 19
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_primal_boost_cycled_pumps_until_end_of_turn(set_pool):
    game, alice, _bob = _w1g3_table(set_pool, "Primal Boost")
    bear = _w1g3_put(game, 0, _mk_creature_card("Bear", 2, 2))

    _w1g3_cycle_and_resolve_trigger(game, "Primal Boost")
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    resolve_stack(game)
    game.resolve_cleanup_step(0)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


#: The Onslaught instants that print cycling and nothing that triggers on it,
#: with the mana their cycling cost takes from the pool. Supported on arrival;
#: driven here for the first time.
_W1G3_PLAIN_CYCLING_INSTANTS = {
    "Akroma's Blessing": {"W": 1},
    "Aura Extraction": {"C": 2},
    "Fade from Memory": {"B": 1},
    "Mage's Guile": {"U": 1},
    "Starstorm": {"C": 3},
    "Swat": {"C": 2},
}


@pytest.mark.parametrize("name", sorted(_W1G3_PLAIN_CYCLING_INSTANTS))
def test_w1g3_a_plain_cycling_instant_pays_its_cost_and_draws(set_pool, name):
    """Cycling from the hand with mana costs enforced: exactly the printed
    cycling cost leaves the pool, the card goes to the graveyard, one card is
    drawn and the spell's own effect never happens."""
    card = set_pool("ONS")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert len(usable_activated_abilities(program, zone=HAND)) == 1
    assert usable_activated_abilities(program) == []

    game, alice, bob = _w1g3_table(set_pool, name)
    game.enforce_mana_costs = True
    alice.mana_pool.update(_W1G3_PLAIN_CYCLING_INSTANTS[name])
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)

    assert not any(alice.mana_pool.values()), alice.mana_pool
    assert [c.name for c in alice.graveyard] == [name]
    assert [c.name for c in alice.hand] == ["Plains"]
    assert (alice.life, bob.life) == (20, 20)


def test_w1g3_a_cycling_instant_cannot_be_cycled_without_its_cost(set_pool):
    game, alice, _bob = _w1g3_table(set_pool, "Starstorm")
    game.enforce_mana_costs = True
    alice.mana_pool.update({"C": 2})
    assert not game.activate_from_hand(0, "Starstorm").supported
    assert [c.name for c in alice.hand] == ["Starstorm"]


# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.type_changes import gain_types as _w1g4_gain_types
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_creature(name, subtype):
    return _W1G4Permanent(card=_w1g4_mk_card(name, "{2}", f"Creature - {subtype}", ""))


def _w1g4_pump_game(set_pool, spell, mine, theirs, interactive=()):
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", hand=[set_pool("ONS")[spell]], battlefield=list(mine),
        ),
        _W1G4PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g4_pt(perm):
    return (perm.effective_power, perm.effective_toughness)


def test_w1g4_defensive_maneuvers_asks_on_resolution_and_toughens_only_that_type(set_pool):
    """"Creatures of the creature type of your choice get +0/+4 until end of
    turn." CR 608.2d: the type is chosen as the spell resolves, so the prompt
    holds the spell on the stack and nothing is pumped until the answer — then
    every creature of the type, the opponent's included, and nothing else."""
    elf = _w1g4_creature("Elf", "Elf")
    my_goblin = _w1g4_creature("My Goblin", "Goblin")
    their_goblin = _w1g4_creature("Their Goblin", "Goblin")
    zombie = _w1g4_creature("Zombie", "Zombie")
    game = _w1g4_pump_game(
        set_pool, "Defensive Maneuvers", [elf, my_goblin], [their_goblin, zombie],
        interactive=[0],
    )
    result = game.cast_from_hand(0, "Defensive Maneuvers")
    assert result.supported, result.details

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("creature_type_choice", 0)
    ]
    assert _w1g4_pt(my_goblin) == (2, 2), "nothing is pumped before the answer"

    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g4_resolve_stack(game)
    assert _w1g4_pt(my_goblin) == (2, 6)
    assert _w1g4_pt(their_goblin) == (2, 6)
    assert _w1g4_pt(elf) == (2, 2)
    assert _w1g4_pt(zombie) == (2, 2)
    assert any("Defensive Maneuvers: chose Goblin" in line for line in game.log)


def test_w1g4_defensive_maneuvers_default_names_the_casters_own_type(set_pool):
    """A seat nobody asks names the type its own creatures have most of, net
    of the opponents' — a pump aimed at the opponents' type is not a choice a
    player makes. Elves 2 − 0 beat Goblins 1 − 3."""
    elves = [_w1g4_creature("Elf A", "Elf"), _w1g4_creature("Elf B", "Elf")]
    my_goblin = _w1g4_creature("My Goblin", "Goblin")
    theirs = [_w1g4_creature(f"Goblin {n}", "Goblin") for n in range(3)]
    game = _w1g4_pump_game(set_pool, "Defensive Maneuvers", [*elves, my_goblin], theirs)
    game.cast_from_hand(0, "Defensive Maneuvers")
    _w1g4_resolve_stack(game)

    assert game.pending_choices == []
    assert [_w1g4_pt(perm) for perm in elves] == [(2, 6), (2, 6)]
    assert _w1g4_pt(my_goblin) == (2, 2)
    assert all(_w1g4_pt(perm) == (2, 2) for perm in theirs)
    assert any("Defensive Maneuvers: chose Elf" in line for line in game.log)


def test_w1g4_tribal_unity_pumps_the_named_type_by_x_through_the_layers(set_pool):
    """"Creatures of the creature type of your choice get +X/+X until end of
    turn." X is the announced one (CR 107.3a), and the type is read through
    layer 4: a creature that *became* a Goblin is one (CR 613.1d), and the
    Elf beside it that did not is left alone."""
    became_goblin = _w1g4_creature("Shifted Elf", "Elf")
    _w1g4_gain_types(became_goblin, subtypes=("goblin",), source="test")
    elf = _w1g4_creature("Elf", "Elf")
    goblin = _w1g4_creature("Goblin", "Goblin")
    game = _w1g4_pump_game(
        set_pool, "Tribal Unity", [became_goblin, elf], [goblin], interactive=[0],
    )
    result = game.cast_from_hand(0, "Tribal Unity", x_value=3)
    assert result.supported, result.details
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g4_resolve_stack(game)

    assert _w1g4_pt(became_goblin) == (5, 5)
    assert _w1g4_pt(goblin) == (5, 5)
    assert _w1g4_pt(elf) == (2, 2)


def test_w1g4_a_pump_with_no_type_to_name_pumps_nothing(set_pool):
    """No creature of the caster's means no type worth naming: the default is
    no choice, and the buff reads that as pumping nothing — never as a buff
    with no narrowing, which would pump the opponent's whole board."""
    theirs = [_w1g4_creature("Goblin", "Goblin")]
    game = _w1g4_pump_game(set_pool, "Defensive Maneuvers", [], theirs)
    game.cast_from_hand(0, "Defensive Maneuvers")
    _w1g4_resolve_stack(game)

    assert _w1g4_pt(theirs[0]) == (2, 2)
    assert any("no creature type was chosen" in line for line in game.log)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# --- W1G5: Trickery Charm, Standardize (CR 205.1a, CR 611.2c) and
# Artificial Evolution (CR 612, CR 613.1c) ---------------------------------
from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.layer_bridge import computed_types as _w1g5_computed_types
from engine.models import Permanent as _W1G5Permanent
from engine.text_changes import changed_words as _w1g5_changed_words
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, hand, *, interactive=(0,)):
    """Seat 0 holding *hand* (ONS names), costs off, in its main phase."""
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="A", hand=[set_pool("ONS")[name] for name in hand]),
        _W1G5PlayerState(name="B"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _w1g5_put(game, seat, card):
    permanent = _W1G5Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._recompute_continuous_effects()
    return permanent


def _w1g5_types(permanent):
    return set(_w1g5_computed_types(permanent)[1])


def test_w1g5_trickery_charm_sets_its_targets_type(set_pool, catalog_by_name):
    """"• Target creature becomes the creature type of your choice until end of
    turn." The mode's picker offers creatures and only creatures; the type is
    chosen as the Charm resolves, with no exclusion — an opponent's Bears can
    be made a Wall — and it is a Wall alone until cleanup."""
    game = _w1g5_table(set_pool, ["Trickery Charm"])
    bears = _w1g5_put(game, 1, catalog_by_name["Grizzly Bears"])
    forest = _w1g5_put(game, 1, catalog_by_name["Forest"])
    charm = set_pool("ONS")["Trickery Charm"]
    spec = game.cast_target_spec(0, charm, mode_index=1)
    assert spec["kind"] == "creature" and spec["requires_target"]
    assert not game.queue_from_hand(
        0, "Trickery Charm", mode_index=1, target_permanent_ids=[forest.permanent_id],
    ).supported
    assert game.queue_from_hand(
        0, "Trickery Charm", mode_index=1, target_permanent_ids=[bears.permanent_id],
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_creature_type_choice(0, "wall")
    _w1g5_resolve_stack(game)
    assert _w1g5_types(bears) == {"wall"}
    assert "Grizzly Bears became a Wall until end of turn (Trickery Charm)" in game.log
    game.resolve_cleanup_step(0)
    assert _w1g5_types(bears) == {"bear"}


def test_w1g5_trickery_charm_flying_mode_is_untouched(set_pool, catalog_by_name):
    """The first mode is still flying alone: no type prompt is armed."""
    game = _w1g5_table(set_pool, ["Trickery Charm"])
    bears = _w1g5_put(game, 0, catalog_by_name["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Trickery Charm", mode_index=0, target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert game._has_keyword(bears, "flying") and _w1g5_types(bears) == {"bear"}
    assert not game.pending_choices


def test_w1g5_standardize_sets_every_creature_on_the_battlefield(
    set_pool, catalog_by_name,
):
    """"Choose a creature type other than Wall. Each creature becomes that type
    until end of turn." Wall is refused with the question still standing; the
    answer sets every creature on either side — so Goblin King, itself made a
    Goblin, pumps all the others — and a creature that enters afterwards is
    untouched (CR 611.2c; the card's ruling: "This spell only affects creatures
    on the battlefield when it resolves"). Cleanup ends every one."""
    game = _w1g5_table(set_pool, ["Standardize"])
    game.players[0].hand.append(catalog_by_name["Grizzly Bears"])
    dreamer = _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    king = _w1g5_put(game, 0, catalog_by_name["Goblin King"])
    their_bears = _w1g5_put(game, 1, catalog_by_name["Grizzly Bears"])
    assert game.queue_from_hand(0, "Standardize").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_creature_type_choice(0, "wall") is False
    assert _w1g5_types(their_bears) == {"bear"}
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g5_resolve_stack(game)

    assert [_w1g5_types(p) for p in (dreamer, king, their_bears)] == [{"goblin"}] * 3
    assert (their_bears.effective_power, their_bears.effective_toughness) == (3, 3)
    assert (dreamer.effective_power, dreamer.effective_toughness) == (3, 2)

    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g5_resolve_stack(game)
    (late,) = [
        perm for perm in game.controlled_by(0) if perm.card.name == "Grizzly Bears"
    ]
    assert _w1g5_types(late) == {"bear"}
    assert (late.effective_power, late.effective_toughness) == (2, 2)

    game.resolve_cleanup_step(0)
    assert _w1g5_types(dreamer) == {"illusion"}
    assert _w1g5_types(king) == {"goblin"}
    assert _w1g5_types(their_bears) == {"bear"}



def _w1g5_evolve(game, target, old, new):
    """Seat 0 casts Artificial Evolution at *target* and names *old*, then
    *new* — each asked as the spell resolves, one after the other."""
    assert game.queue_from_hand(
        0, "Artificial Evolution", target_permanent_ids=[target.permanent_id],
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [c.kind for c in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(0, old)
    assert [c.kind for c in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(0, new)
    _w1g5_resolve_stack(game)


def test_w1g5_artificial_evolution_rewrites_a_lords_text_and_type_line(
    set_pool, catalog_by_name,
):
    """"Change the text of target spell or permanent by replacing all instances
    of one creature type with another." Elf to Goblin on Elvish Champion: its
    "Other Elf creatures" now reads Goblin, so the opponent's Llanowar Elves
    lose the +1/+1 and seat 0's Raging Goblin gets it with forestwalk; its type
    line reads Goblin too (CR 612.1 — the ruling: "the text box and the type
    line"); its name does not change (CR 612.2). Indefinite: cleanup leaves
    it."""
    game = _w1g5_table(set_pool, ["Artificial Evolution"])
    champion = _w1g5_put(game, 1, catalog_by_name["Elvish Champion"])
    elves = _w1g5_put(game, 1, catalog_by_name["Llanowar Elves"])
    goblin = _w1g5_put(game, 0, catalog_by_name["Raging Goblin"])
    assert (elves.effective_power, goblin.effective_power) == (2, 1)

    _w1g5_evolve(game, champion, "elf", "goblin")

    assert champion.effective_card.oracle_text.startswith(
        "Other Goblin creatures get +1/+1 and have forestwalk."
    )
    assert _w1g5_types(champion) == {"goblin"}
    assert (elves.effective_power, elves.effective_toughness) == (1, 1)
    assert (goblin.effective_power, goblin.effective_toughness) == (2, 2)
    assert game._has_keyword(goblin, "forestwalk")
    assert champion.effective_card.name == "Elvish Champion"
    assert {"from": "elf", "to": "goblin"} in _w1g5_changed_words(champion)
    assert (
        "Artificial Evolution changed elf to goblin in Elvish Champion's text"
        in game.log
    )
    game.resolve_cleanup_step(0)
    assert goblin.effective_power == 2


def test_w1g5_artificial_evolution_refuses_wall_and_the_same_word(
    set_pool, catalog_by_name,
):
    """"The new creature type can't be Wall." and the ruling "It can't change
    a word to the same word": the second question refuses both with the
    question still standing, and its own list offers neither."""
    from web.prompts import PromptContext, render_prompts

    game = _w1g5_table(set_pool, ["Artificial Evolution"])
    champion = _w1g5_put(game, 1, catalog_by_name["Elvish Champion"])
    assert game.queue_from_hand(
        0, "Artificial Evolution", target_permanent_ids=[champion.permanent_id],
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    (first,) = game.pending_choices
    assert first.data["word_role"] == "replaced"
    assert first.data["default_creature_type"] == "elf", "written on the target"
    assert game.confirm_creature_type_choice(0, "elf")
    assert game.confirm_creature_type_choice(0, "wall") is False
    assert game.confirm_creature_type_choice(0, "elf") is False
    offered = render_prompts(PromptContext(
        game=game, viewer_seat=0,
        serialize_card=lambda card: {"name": getattr(card, "name", str(card))},
        seat_type=lambda index: "human" if index in game.interactive_seats else "ai",
    ))["creature_type_choice"]
    assert "wall" not in offered["creature_types"]
    assert "elf" not in offered["creature_types"]
    # The second of the two questions says it is the replacement.
    assert offered["word_role"] == "replacement"
    assert _w1g5_types(champion) == {"elf"}
    assert game.confirm_creature_type_choice(0, "zombie")
    _w1g5_resolve_stack(game)
    assert _w1g5_types(champion) == {"zombie"}


def test_w1g5_a_creature_type_set_by_an_effect_beats_the_text_change(set_pool):
    """The ruling: "If a creature's creature type has been changed by a spell
    or ability, changing the card's text won't affect or alter the new
    creature type." The Mistform's set is layer 4 and the text change layer 3
    (CR 613.1c–d), so the set wins whichever came first: an Elf by its own
    ability stays an Elf after its "Illusion" is rewritten Goblin, and once
    cleanup ends the set it is the Goblin its text now says. A set made after
    the text change wins the same way."""
    game = _w1g5_table(set_pool, ["Artificial Evolution"])
    dreamer = _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    assert game.activate_permanent_ability(0, "Mistform Dreamer").supported
    assert game.confirm_creature_type_choice(0, "elf")
    _w1g5_resolve_stack(game)

    _w1g5_evolve(game, dreamer, "illusion", "goblin")
    assert dreamer.effective_card.type_line == "Creature — Goblin"
    assert _w1g5_types(dreamer) == {"elf"}
    game.resolve_cleanup_step(0)
    assert _w1g5_types(dreamer) == {"goblin"}

    assert game.activate_permanent_ability(0, "Mistform Dreamer").supported
    assert game.confirm_creature_type_choice(0, "wizard")
    _w1g5_resolve_stack(game)
    assert _w1g5_types(dreamer) == {"wizard"}


def test_w1g5_artificial_evolution_for_a_seat_nobody_asks(set_pool, catalog_by_name):
    """The defaults: the word replaced is the first creature type written on
    the target (its type line), and its replacement the caster's own
    commonest type that is neither Wall nor that word — so the opponent's
    Elvish Champion becomes a lord of seat 0's Goblins."""
    game = _w1g5_table(set_pool, ["Artificial Evolution"], interactive=())
    champion = _w1g5_put(game, 1, catalog_by_name["Elvish Champion"])
    kings = [_w1g5_put(game, 0, catalog_by_name["Goblin King"]) for _ in range(2)]
    assert game.queue_from_hand(
        0, "Artificial Evolution", target_permanent_ids=[champion.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert _w1g5_types(champion) == {"goblin"}
    assert (
        "Artificial Evolution changed elf to goblin in Elvish Champion's text"
        in game.log
    )
    # Each King: 2/2, +1/+1 from the other King, +1/+1 from the Champion.
    assert kings[0].effective_power == 4

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from engine.type_changes import gain_types as _w1g7_gain_types
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_perm(pool, name):
    return _w1g7_nosick(_w1g7_Permanent(card=pool[name]))


def _w1g7_game(mine=(), theirs=(), *, p1=None, p2=None):
    one = _w1g7_PlayerState(name="P1", battlefield=list(mine), **(p1 or {}))
    two = _w1g7_PlayerState(name="P2", battlefield=list(theirs), **(p2 or {}))
    game = _w1g7_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    return game, one, two


def test_w1g7_wirewood_pride_counts_every_elf(set_pool):
    """"…+X/+X until end of turn, where X is the number of **Elves** on the
    battlefield." Both sides' Elves, not a Goblin — and a Goblin that became
    an Elf is one."""
    pool = set_pool("ONS")
    target = _w1g7_perm(pool, "Skirk Prospector")
    game, p1, _p2 = _w1g7_game(
        [target, _w1g7_perm(pool, "Wirewood Elf")],
        [_w1g7_perm(pool, "Wellwisher")],
        p1={"hand": [pool["Wirewood Pride"]] * 2},
    )
    result = game.cast_from_hand(
        0, "Wirewood Pride", target_player_index=0,
        target_permanent_ids=[target.permanent_id],
    )
    assert result.supported, result.details
    _w1g7_resolve(game)
    game._recompute_continuous_effects()
    assert (target.effective_power, target.effective_toughness) == (3, 3)

    _w1g7_gain_types(target, subtypes=("elf",))
    game._recompute_continuous_effects()
    game.cast_from_hand(
        0, "Wirewood Pride", target_player_index=0,
        target_permanent_ids=[target.permanent_id],
    )
    _w1g7_resolve(game)
    game._recompute_continuous_effects()
    assert (target.effective_power, target.effective_toughness) == (6, 6)

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# The family's instants that compiled on arrival and had never been run:
# abilities granted in quotes until end of turn (Psychic Trance, Run Wild,
# Commando Raid), and Inspirit and the three Charms, every mode.

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.aura_attachment import attach_aura as _w1g8_attach_aura
from engine.models import Permanent as _w1g8_Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import (
    derive_cast_spec as _w1g8_derive_cast_spec,
    usable_activated_abilities as _w1g8_usable,
)
from tests.helpers import (
    _nosick as _w1g8_nosick, declare_attack as _w1g8_declare_attack,
    resolve_stack as _w1g8_resolve,
)


def _w1g8_perm(pool, name):
    return _w1g8_nosick(_w1g8_Permanent(card=pool[name]))


def _w1g8_game(pool, mine=(), theirs=(), *, hand=(), their_hand=()):
    one = _w1g8_PlayerState(
        name="P1", battlefield=list(mine), hand=[pool[name] for name in hand],
        library=[pool["Island"]] * 5,
    )
    two = _w1g8_PlayerState(
        name="P2", battlefield=list(theirs),
        hand=[pool[name] for name in their_hand], library=[pool["Island"]] * 5,
    )
    game = _w1g8_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    return game, one, two


def _w1g8_cast(game, name, target=None, *, mode=None):
    kwargs = {} if mode is None else {"mode_index": mode}
    if target is not None:
        kwargs.update(
            target_player_index=game.controller_index_of(target),
            target_permanent_ids=[target.permanent_id],
        )
    result = game.cast_from_hand(0, name, **kwargs)
    assert result.supported, result.details
    _w1g8_resolve(game)
    game._recompute_continuous_effects()


def _w1g8_lines(game, perm):
    game._recompute_continuous_effects()
    return [
        ability.source_line
        for ability in _w1g8_usable(_w1g8_compile(perm.effective_card))
    ]


def _w1g8_offered(game, card, mode=None):
    spec = _w1g8_derive_cast_spec(card, _w1g8_compile(card), mode_index=mode)
    return {
        game.players[found["seat"]].battlefield[found["index"]].permanent_id
        for found in game._enumerate_targets(
            0, card, spec, for_cast=True, mode_index=mode,
        )
        if found["kind"] == "permanent"
    }


def test_w1g8_psychic_trance_counters_a_spell_in_response(set_pool):
    """'Until end of turn, Wizards you control gain "{T}: Counter target
    spell."' Only the caster's Wizards gain it; one counters a Shock cast in
    response; the line is gone after cleanup."""
    pool = set_pool("ONS")
    wizard = _w1g8_perm(pool, "Aphetto Grifter")
    theirs = _w1g8_perm(pool, "Aphetto Grifter")
    game, one, two = _w1g8_game(
        pool, [wizard], [theirs], hand=["Psychic Trance"], their_hand=["Shock"],
    )
    _w1g8_cast(game, "Psychic Trance")
    granted = "{T}: Counter target spell"
    assert granted in _w1g8_lines(game, wizard)
    assert granted not in _w1g8_lines(game, theirs)

    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    index = _w1g8_lines(game, wizard).index(granted)
    result = game.activate_permanent_ability(
        0, "Aphetto Grifter", ability_index=index, target_stack_index=0,
    )
    assert result.supported, result.details
    _w1g8_resolve(game)
    assert one.life == 20 and wizard.tapped
    assert [card.name for card in two.graveyard] == ["Shock"]
    assert any("countered" in line for line in game.log)

    game.resolve_cleanup_step(0)
    assert granted not in _w1g8_lines(game, wizard)


def test_w1g8_run_wild_grants_trample_and_a_regeneration_line(set_pool):
    """'Until end of turn, target creature gains trample and "{G}: Regenerate
    this creature."' The line costs {G}, its shield saves the creature, and
    both grants end at cleanup."""
    pool = set_pool("ONS")
    seeker = _w1g8_perm(pool, "Glory Seeker")
    game, one, _two = _w1g8_game(pool, [seeker], hand=["Run Wild"])
    _w1g8_cast(game, "Run Wild", seeker)
    assert game._has_keyword(seeker, "trample")
    assert _w1g8_lines(game, seeker) == ["{G}: Regenerate this creature"]
    game.enforce_mana_costs = True
    one.mana_pool["G"] = 1
    assert game.activate_permanent_ability(0, "Glory Seeker").supported
    _w1g8_resolve(game)
    assert one.mana_pool["G"] == 0
    game._destroy_target_permanent(one, target_permanent_index=0)
    _w1g8_resolve(game)
    assert game.is_on_battlefield(seeker) and seeker.tapped

    game.resolve_cleanup_step(0)
    game._recompute_continuous_effects()
    assert not game._has_keyword(seeker, "trample")
    assert _w1g8_lines(game, seeker) == []


def test_w1g8_commando_raid_bites_a_creature_of_the_damaged_player(set_pool):
    """'Until end of turn, target creature you control gains "When this
    creature deals combat damage to a player, you may have it deal damage
    equal to its power to target creature that player controls."' The
    granted trigger fires on combat damage, aims at the damaged player's
    creature, and — taken — deals the attacker's power to it."""
    pool = set_pool("ONS")
    raider = _w1g8_perm(pool, "Glory Seeker")
    victim = _w1g8_perm(pool, "Wirewood Elf")
    game, _one, two = _w1g8_game(pool, [raider], [victim], hand=["Commando Raid"])
    _w1g8_cast(game, "Commando Raid", raider)
    _w1g8_declare_attack(game, 0)
    for _ in range(8):
        if game.pending_choices:
            assert game.confirm_optional_pay(0, accept=True)
            _w1g8_resolve(game)
        elif game.stack:
            _w1g8_resolve(game)
        elif game.current_step == "end_of_combat":
            break
        else:
            game.advance_combat_phase()
    assert two.life == 18
    assert not game.is_on_battlefield(victim), "2 damage to the 1/2 Elf"


def test_w1g8_inspirit_untaps_and_pumps_until_end_of_turn(set_pool):
    pool = set_pool("ONS")
    seeker = _w1g8_perm(pool, "Glory Seeker")
    seeker.tapped = True
    game, _one, _two = _w1g8_game(pool, [seeker], hand=["Inspirit"])
    _w1g8_cast(game, "Inspirit", seeker)
    assert not seeker.tapped
    assert (seeker.effective_power, seeker.effective_toughness) == (4, 6)
    game.resolve_cleanup_step(0)
    game._recompute_continuous_effects()
    assert (seeker.effective_power, seeker.effective_toughness) == (2, 2)


def test_w1g8_piety_charm_every_mode(set_pool):
    """'• Destroy target Aura attached to a creature. • Target Soldier
    creature gets +2/+2 until end of turn. • Creatures you control gain
    vigilance until end of turn.' Each mode's picker holds its own noun."""
    pool = set_pool("ONS")
    soldier = _w1g8_perm(pool, "Glory Seeker")
    elf = _w1g8_perm(pool, "Wirewood Elf")
    theirs = _w1g8_perm(pool, "Wirewood Elf")
    aura = _w1g8_Permanent(card=pool["Pacifism"])
    game, _one, _two = _w1g8_game(
        pool, [soldier, elf], [theirs, aura], hand=["Piety Charm"] * 3,
    )
    _w1g8_attach_aura(aura, theirs)
    game._settle()
    charm = pool["Piety Charm"]
    assert _w1g8_offered(game, charm, 0) == {aura.permanent_id}
    _w1g8_cast(game, "Piety Charm", aura, mode=0)
    assert not game.is_on_battlefield(aura)
    assert _w1g8_offered(game, charm, 1) == {soldier.permanent_id}
    _w1g8_cast(game, "Piety Charm", soldier, mode=1)
    assert (soldier.effective_power, soldier.effective_toughness) == (4, 4)
    _w1g8_cast(game, "Piety Charm", mode=2)
    assert game._has_keyword(soldier, "vigilance") and game._has_keyword(elf, "vigilance")
    assert not game._has_keyword(theirs, "vigilance")


def test_w1g8_vitality_charm_every_mode(set_pool):
    pool = set_pool("ONS")
    elf = _w1g8_perm(pool, "Wirewood Elf")
    beast = _w1g8_perm(pool, "Graxiplon")
    game, one, _two = _w1g8_game(pool, [elf, beast], hand=["Vitality Charm"] * 3)
    _w1g8_cast(game, "Vitality Charm", mode=0)
    (insect,) = [p for p in one.battlefield if p.card.name == "Insect Token"]
    assert (insect.effective_power, insect.effective_toughness) == (1, 1)
    _w1g8_cast(game, "Vitality Charm", elf, mode=1)
    assert (elf.effective_power, elf.effective_toughness) == (2, 3)
    assert game._has_keyword(elf, "trample")
    charm = pool["Vitality Charm"]
    assert _w1g8_offered(game, charm, 2) == {beast.permanent_id}, "Beasts only"
    _w1g8_cast(game, "Vitality Charm", beast, mode=2)
    game._destroy_target_permanent(
        one, target_permanent_index=one.battlefield.index(beast)
    )
    _w1g8_resolve(game)
    assert game.is_on_battlefield(beast), "regenerated"


def test_w1g8_fever_charm_every_mode(set_pool):
    pool = set_pool("ONS")
    goblin = _w1g8_Permanent(card=pool["Skirk Prospector"])
    wizard = _w1g8_perm(pool, "Aphetto Grifter")
    seeker = _w1g8_perm(pool, "Glory Seeker")
    game, _one, _two = _w1g8_game(
        pool, [goblin], [wizard, seeker], hand=["Fever Charm"] * 3,
    )
    goblin.metadata["summoning_sickness_turn"] = game.turn
    assert not game.can_attack(goblin, 1)
    _w1g8_cast(game, "Fever Charm", goblin, mode=0)
    assert game.can_attack(goblin, 1)
    _w1g8_cast(game, "Fever Charm", goblin, mode=1)
    assert (goblin.effective_power, goblin.effective_toughness) == (3, 1)
    assert _w1g8_offered(game, pool["Fever Charm"], 2) == {wizard.permanent_id}
    _w1g8_cast(game, "Fever Charm", wizard, mode=2)
    assert not game.is_on_battlefield(wizard)

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# --- W1G10: control and the stack, on instants --------------------------------
import pytest as _w1g10_pytest

from engine import Game as _w1g10_Game
from engine.models import Permanent as _w1g10_Permanent
from engine.models import PlayerState as _w1g10_PlayerState
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_runes_game(set_pool, *, library: int = 8, interactive: bool = False):
    game = _w1g10_Game(players=[
        _w1g10_PlayerState(
            name=f"P{seat + 1}", life=20,
            library=[set_pool("LEA")["Island"]] * library,
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(0)
    for name in ("Grizzly Bears", "Forest"):
        game._put_permanent_onto_battlefield(
            0, _w1g10_Permanent(card=set_pool("LEA")[name]), None
        )
    game.players[0].hand.extend(
        [set_pool("ONS")["Shock"], set_pool("ONS")["Read the Runes"]]
    )
    return game


def _w1g10_drain(game) -> None:
    """Resolve, then answer each owed offer with its default (a headless seat's
    offers are drained once the stack is empty)."""
    _w1g10_resolve_stack(game)
    for _ in range(20):
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices()
    raise AssertionError([c.kind for c in game.pending_choices])


def test_w1g10_read_the_runes_draws_then_discards_one_per_card(set_pool):
    """"Draw X cards. For each card drawn this way, discard a card unless you
    sacrifice a permanent." X = 3: three cards arrive first (the ruling: "You
    draw the cards, then …"), then three tolls; the headless seat keeps its
    permanents and discards three (never forced to sacrifice)."""
    game = _w1g10_runes_game(set_pool)
    assert game.queue_from_hand(0, "Read the Runes", x_value=3).supported
    _w1g10_drain(game)
    me = game.players[0]
    assert "Read the Runes drew 3 card" in game.log
    assert len(me.hand) == 1, [c.name for c in me.hand]
    assert sorted(c.name for c in me.graveyard if c.name != "Read the Runes") == [
        "Island", "Island", "Shock",
    ]
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears", "Forest"]
    assert game.log.index("Read the Runes drew 3 card") < min(
        i for i, line in enumerate(game.log) if "discarded" in line
    )


def test_w1g10_read_the_runes_a_sacrifice_buys_off_one_discard(set_pool):
    """The toll answered both ways by a seat that is asked: the first is paid
    with a permanent (the Forest), the other two are discards."""
    game = _w1g10_runes_game(set_pool, interactive=True)
    assert game.queue_from_hand(0, "Read the Runes", x_value=3).supported
    answered = 0
    for _ in range(30):
        if not game.stack and not game.pending_choices:
            break
        if not game.pending_choices:
            game.resolve_top_of_stack()
            continue
        choice = game.pending_choices[0]
        if choice.kind == "optional_pay":
            assert game._resolve_optional_pay(choice, answered == 0, None)
            answered += 1
        else:
            game.auto_resolve_pending_choices(kinds=(choice.kind,))
    assert answered == 3
    me = game.players[0]
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"], game.log
    assert "Forest" in [c.name for c in me.graveyard]
    assert len(me.hand) == 2, [c.name for c in me.hand]


def test_w1g10_read_the_runes_counts_the_cards_really_drawn(set_pool):
    """"…drawn **this way**": X = 4 from a two-card library draws two, and
    asks two tolls, not four."""
    game = _w1g10_runes_game(set_pool, library=2)
    assert game.queue_from_hand(0, "Read the Runes", x_value=4).supported
    _w1g10_drain(game)
    assert sum("declined Read the Runes" in line for line in game.log) == 2, game.log


# --- W1G10 drive: the instant Chains -----------------------------------------
#
# "…that permanent's controller may sacrifice a land of their choice" / "…may
# discard a card": the offered player is the one who sacrifices or discards.
# Before the fix the offered player said yes and the *caster* did it.


def _w1g10_chain_table(set_pool):
    game = _w1g10_Game(players=[
        _w1g10_PlayerState(
            name=f"P{seat + 1}", life=20,
            library=[set_pool("LEA")["Island"]] * 8,
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    placed = {}
    for seat, name in (
        (0, "Grizzly Bears"), (0, "Forest"), (1, "Hill Giant"), (1, "Mountain"),
    ):
        perm = _w1g10_Permanent(card=set_pool("LEA")[name])
        game._put_permanent_onto_battlefield(seat, perm, None)
        placed[name] = perm
    return game, placed


def _w1g10_play_out(game, offers):
    """Answer each optional offer from *offers* (True/False, in order; False
    once exhausted) and every other prompt with its default."""
    offers = list(offers)
    asked = []
    for _ in range(60):
        if not game.stack and not game.pending_choices:
            return asked
        if not game.pending_choices:
            game.resolve_top_of_stack()
            continue
        choice = game.pending_choices[0]
        asked.append((choice.kind, choice.player_index))
        if choice.kind == "optional_pay":
            assert game._resolve_optional_pay(
                choice, offers.pop(0) if offers else False, None
            )
        else:
            game.auto_resolve_pending_choices(kinds=(choice.kind,))
    raise AssertionError(asked)


def test_w1g10_chain_of_vapor_the_bounced_permanents_controller_sacrifices(set_pool):
    game, placed = _w1g10_chain_table(set_pool)
    game.players[0].hand.append(set_pool("ONS")["Chain of Vapor"])
    assert game.queue_from_hand(
        0, "Chain of Vapor", target_permanent_ids=[placed["Hill Giant"].permanent_id]
    ).supported
    asked = _w1g10_play_out(game, [True, False])
    assert ("sacrifice", 1) in asked and ("sacrifice", 0) not in asked, asked
    assert "Hill Giant" in [c.name for c in game.players[1].hand]
    assert "Mountain" in [c.name for c in game.players[1].graveyard], game.log
    assert game.is_on_battlefield(placed["Forest"]), "the caster's land is not theirs to give"
    assert "P2 sacrificed Mountain (Chain of Vapor)" in game.log


def test_w1g10_chain_of_plasma_the_damaged_creatures_controller_discards(set_pool):
    game, placed = _w1g10_chain_table(set_pool)
    game.players[0].hand.extend(
        [set_pool("ONS")["Chain of Plasma"], set_pool("ONS")["Shock"]]
    )
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(
        0, "Chain of Plasma", target_permanent_ids=[placed["Hill Giant"].permanent_id]
    ).supported
    _w1g10_play_out(game, [True, False])
    assert placed["Hill Giant"].damage_marked == 3
    assert [c.name for c in game.players[1].graveyard] == ["Lightning Bolt"], game.log
    assert [c.name for c in game.players[0].hand] == ["Shock"], "the caster kept its card"


# --- W1G10: Wheel and Deal ------------------------------------------------------
#
# "Any number of target opponents each discard their hands, then draw seven
# cards. Draw a card." Announced as a chain of optional opponent seat roles
# (`target_roles.any_number_of_opponents_roles`); the rulings (2004-10-04):
# "You can choose to target zero opponents." "You can't target yourself."


def _w1g10_wheel_table(set_pool):
    game = _w1g10_Game(players=[
        _w1g10_PlayerState(
            name=f"P{seat + 1}", life=20,
            library=[set_pool("LEA")["Island"]] * 12,
        )
        for seat in range(3)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game.players[0].hand.append(set_pool("ONS")["Wheel and Deal"])
    game.players[1].hand.extend(
        [set_pool("LEA")["Lightning Bolt"], set_pool("LEA")["Mountain"]]
    )
    game.players[2].hand.append(set_pool("LEA")["Forest"])
    return game


@_w1g10_pytest.mark.parametrize("named, wheeled", [
    ([1, 2], {1, 2}), ([2], {2}), ([], set()),
])
def test_w1g10_wheel_and_deal_wheels_exactly_the_named_opponents(set_pool, named, wheeled):
    game = _w1g10_wheel_table(set_pool)
    before = [len(player.hand) for player in game.players]
    assert game.queue_from_hand(
        0, "Wheel and Deal", target_role_refs=[{"seat": seat} for seat in named],
    ).supported
    _w1g10_resolve_stack(game)
    for seat in (1, 2):
        if seat in wheeled:
            assert len(game.players[seat].hand) == 7, game.log
            assert len(game.players[seat].graveyard) == before[seat]
        else:
            assert len(game.players[seat].hand) == before[seat]
            assert game.players[seat].graveyard == []
    # "Draw a card" — the caster, whoever was named (the spell itself went to
    # the graveyard from the hand).
    assert len(game.players[0].hand) == before[0] - 1 + 1, game.log


@_w1g10_pytest.mark.parametrize("named", [[0], [1, 1], [2, 1]])
def test_w1g10_wheel_and_deal_refuses_itself_a_repeat_and_a_reordering(set_pool, named):
    """Not yourself; each opponent once (CR 115.3); and the set is announced
    once, in seat order, rather than once per ordering."""
    game = _w1g10_wheel_table(set_pool)
    assert not game.queue_from_hand(
        0, "Wheel and Deal", target_role_refs=[{"seat": seat} for seat in named],
    ).supported
    assert "Wheel and Deal" in [c.name for c in game.players[0].hand]
    assert game.stack == []


def test_w1g10_wheel_and_deal_skips_an_opponent_that_became_illegal(
    set_pool, catalog_by_name,
):
    """CR 608.2b: of two named opponents, the one that gained shroud is not
    affected and the rest of the spell happens; with that one alone named, the
    whole spell is countered — the draw included."""
    mask = catalog_by_name["Ivory Mask"]
    game = _w1g10_wheel_table(set_pool)
    assert game.queue_from_hand(
        0, "Wheel and Deal", target_role_refs=[{"seat": 1}, {"seat": 2}],
    ).supported
    game._put_permanent_onto_battlefield(2, _w1g10_Permanent(card=mask), None)
    _w1g10_resolve_stack(game)
    assert len(game.players[1].hand) == 7 and len(game.players[2].hand) == 1, game.log

    game = _w1g10_wheel_table(set_pool)
    hand_before = len(game.players[0].hand)
    assert game.queue_from_hand(
        0, "Wheel and Deal", target_role_refs=[{"seat": 2}],
    ).supported
    game._put_permanent_onto_battlefield(2, _w1g10_Permanent(card=mask), None)
    _w1g10_resolve_stack(game)
    assert len(game.players[2].hand) == 1
    assert len(game.players[0].hand) == hand_before - 1, "countered: no card drawn"
    assert any("every target is illegal" in line for line in game.log), game.log

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# Oblation: "The owner of target nonland permanent shuffles it into their
# library, then draws two cards." Rishadan Pawnshop's move with its subject
# printed (`effects/zones.parse_owner_shuffles_target_into_library`), and the
# draw read off the record that move writes (`LAST_TARGET_OWNER`). False
# Cure: a delayed ability for the turn over the one life-gain seam
# (`Game._gain_life` announces `player_gains_life`), losing 2 per 1 gained.

from engine import Game as _W1G11Game, PlayerState as _W1G11PlayerState
from engine.control import change_control as _w1g11_change_control
from engine.delayed_triggers import expire_delayed_triggers as _w1g11_expire_delayed
from engine.models import Permanent as _W1G11Permanent
from engine.oracle import compile_card_oracle as _w1g11_compile
from engine.targeting import derive_cast_spec as _w1g11_cast_spec
from tests.helpers import resolve_stack as _w1g11_resolve_stack


def _w1g11_table(set_pool, *hand):
    ons = set_pool("ONS")
    alice = _W1G11PlayerState(
        name="Alice", library=[ons["Island"]] * 6, hand=[ons[name] for name in hand],
    )
    bob = _W1G11PlayerState(name="Bob", library=[ons["Mountain"]] * 6)
    game = _W1G11Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    return game


def _w1g11_put(game, seat, card):
    permanent = _W1G11Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    _w1g11_resolve_stack(game)
    return permanent


def test_w1g11_oblation_sends_a_stolen_permanent_home_and_its_owner_draws(set_pool):
    """The **owner** shuffles it into their library and draws two (CR 108.3):
    Alice has taken Bob's Elvish Pioneer, and Oblation aimed at it puts it into
    Bob's library and gives Bob the two cards — not Alice, who controls it."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool, "Oblation")
    pioneer = _w1g11_put(game, 1, ons["Elvish Pioneer"])
    _w1g11_change_control(pioneer, 0, source="test")
    game._sync_control()
    assert game.controller_index_of(pioneer) == 0
    alice, bob = game.players

    result = game.cast_from_hand(0, "Oblation", target_permanent_ids=[pioneer.permanent_id])
    assert result.supported, result.details
    _w1g11_resolve_stack(game)

    assert not game.is_on_battlefield(pioneer)
    assert len(bob.library) + len(bob.hand) == 7, "six Mountains and the Pioneer"
    assert len(bob.hand) == 2 and "Bob drew 2 cards" in game.log
    assert alice.hand == [] and len(alice.library) == 6
    assert "Oblation: Elvish Pioneer was shuffled into Bob's library" in game.log


def test_w1g11_oblation_targets_a_nonland_permanent_only(set_pool):
    """"target **nonland** permanent": the picker excludes lands, and a cast
    naming one is refused before anything is paid."""
    ons = set_pool("ONS")
    oblation = ons["Oblation"]
    assert _w1g11_cast_spec(oblation, _w1g11_compile(oblation)) == {
        "kind": "permanent", "filter": {"exclude_types": ["land"]},
    }
    game = _w1g11_table(set_pool, "Oblation")
    forest = _w1g11_put(game, 1, ons["Forest"])

    refused = game.cast_from_hand(0, "Oblation", target_permanent_ids=[forest.permanent_id])

    assert not refused.supported
    assert game.is_on_battlefield(forest) and [c.name for c in game.players[0].hand] == ["Oblation"]


def test_w1g11_false_cure_makes_each_life_gain_cost_double_this_turn(set_pool):
    """"Until end of turn, whenever a player gains life, that player loses 2
    life for each 1 life they gained." A delayed ability (CR 603.7) that
    repeats for its stated duration (CR 603.7b): Bob's 3 costs him 6, and
    Alice's own Renewed Faith (6) costs her 12 — "a player" is any seat. The
    loss is a triggered ability on the stack (CR 603.3), so it can be
    answered; and the turn over, a gain is only a gain."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool, "False Cure", "Renewed Faith")
    alice, bob = game.players
    assert game.cast_from_hand(0, "False Cure").supported
    _w1g11_resolve_stack(game)

    game._gain_life(bob, 3, source_name="a test")
    assert bob.life == 23 and len(game.stack) == 1, "the loss waits on the stack"
    _w1g11_resolve_stack(game)
    assert bob.life == 17

    assert game.cast_from_hand(0, "Renewed Faith").supported
    _w1g11_resolve_stack(game)
    assert alice.life == 20 + 6 - 12
    assert "False Cure: Alice lost 12 life (26 -> 14)" in game.log

    _w1g11_expire_delayed(game)
    game._gain_life(bob, 3, source_name="a test")
    _w1g11_resolve_stack(game)
    assert bob.life == 20

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================


# ==== W2G1 ==========================================================
# W2G1's tests go between this line and the "end W2G1" line.

# Shade's Breath: "Until end of turn, each creature you control becomes a
# black Shade and gains "{B}: This creature gets +1/+1 until end of turn."" —
# a colour set (layer 5), a creature-type set with its word printed (layer 4,
# CR 205.1a) and a quoted grant (layer 6), each over the creatures the caster
# controls as it resolves (CR 611.2c), all ending at cleanup.

from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from engine.layer_bridge import computed_types as _w2g1_computed_types
from engine.models import Permanent as _W2G1Permanent
from tests.helpers import _mk_card as _w2g1_mk_card
from tests.helpers import resolve_stack as _w2g1_resolve_stack


def _w2g1_creature(name, subtype, color="R"):
    permanent = _W2G1Permanent(card=_w2g1_mk_card(
        name=name, mana_cost=f"{{1}}{{{color}}}", type_line=f"Creature - {subtype}",
        colors=(color,),
    ))
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w2g1_breath_table(set_pool, mine, theirs):
    ons = set_pool("ONS")
    game = _W2G1Game(players=[
        _W2G1PlayerState(name="A", hand=[ons["Shade's Breath"]],
                         battlefield=list(mine), library=[ons["Swamp"]] * 5),
        _W2G1PlayerState(name="B", battlefield=list(theirs),
                         library=[ons["Swamp"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    return game


def test_w2g1_shades_breath_makes_each_of_your_creatures_a_black_shade(set_pool):
    """Both of the caster's creatures become black Shades — their printed
    colour and creature types replaced, not joined — and each gains the
    pump, which then works; the opponent's creature is untouched."""
    goblin = _w2g1_creature("Red Goblin", "Goblin Warrior")
    soldier = _w2g1_creature("White Soldier", "Human Soldier", "W")
    elf = _w2g1_creature("Their Elf", "Elf", "G")
    game = _w2g1_breath_table(set_pool, [goblin, soldier], [elf])

    assert game.cast_from_hand(0, "Shade's Breath").supported
    _w2g1_resolve_stack(game)

    for perm in (goblin, soldier):
        assert perm.effective_colors == {"B"}
        assert _w2g1_computed_types(perm) == ({"creature"}, {"shade"})
        assert "{B}: This creature gets +1/+1" in perm.effective_card.oracle_text
    assert _w2g1_computed_types(elf) == ({"creature"}, {"elf"})
    assert elf.effective_colors == {"G"}
    assert "{B}" not in (elf.effective_card.oracle_text or "")

    before = (goblin.effective_power, goblin.effective_toughness)
    assert game.activate_permanent_ability(0, "Red Goblin").supported
    _w2g1_resolve_stack(game)
    assert (goblin.effective_power, goblin.effective_toughness) == (
        before[0] + 1, before[1] + 1,
    )


def test_w2g1_shades_breath_ends_at_cleanup_and_skips_a_later_arrival(set_pool):
    """CR 611.2c: a creature that arrives after the spell resolves keeps its
    colour and type; and every change wears off in the cleanup step."""
    goblin = _w2g1_creature("Red Goblin", "Goblin")
    game = _w2g1_breath_table(set_pool, [goblin], [])
    assert goblin.effective_colors == {"R"}

    assert game.cast_from_hand(0, "Shade's Breath").supported
    _w2g1_resolve_stack(game)
    late = _w2g1_creature("Late Wolf", "Wolf", "G")
    game.players[0].battlefield.append(late)
    game._sync_control()
    game._recompute_continuous_effects()
    assert _w2g1_computed_types(late) == ({"creature"}, {"wolf"})
    assert late.effective_colors == {"G"}
    assert "{B}" not in (late.effective_card.oracle_text or "")
    assert _w2g1_computed_types(goblin) == ({"creature"}, {"shade"})

    game.resolve_cleanup_step(0)
    assert _w2g1_computed_types(goblin) == ({"creature"}, {"goblin"})
    assert goblin.effective_colors == {"R"}
    assert "{B}" not in (goblin.effective_card.oracle_text or "")

# ==== end W2G1 ======================================================


# ==== W2G6 ==========================================================
# Cruel Revival's two targets, one announcement (CR 601.2c) - found by
# Onslaught's promotion rehearsal (tests/engine/test_up_to_names_nobody_census.py):
# its "up to one target Zombie card" was never announced and the return
# scanned the graveyard at resolution.
from engine import Game as _W2G6Game
from engine import PlayerState as _W2G6PlayerState
from engine.models import Permanent as _W2G6Permanent
from tests.helpers import resolve_stack as _w2g6_resolve_stack


def _w2g6_revival_table(set_pool, catalog_by_name):
    """Seat 0 holds Cruel Revival with two Zombie cards and a Hill Giant in its
    graveyard; seat 1 controls a Grizzly Bears and a Zombie, with a Zombie
    card of its own in its graveyard."""
    ons = set_pool("ONS")
    zombie_cards = [ons["Gangrenous Goliath"], ons["Aphetto Vulture"]]
    game = _W2G6Game(players=[
        _W2G6PlayerState(
            name="A", hand=[ons["Cruel Revival"]],
            graveyard=[catalog_by_name["Hill Giant"], *zombie_cards],
            library=[ons["Swamp"]] * 5,
        ),
        _W2G6PlayerState(
            name="B", graveyard=[ons["Gluttonous Zombie"]],
            library=[ons["Swamp"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    bears = _W2G6Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    rotter = _W2G6Permanent(card=ons["Gluttonous Zombie"])
    game._put_permanent_onto_battlefield(1, rotter, None)
    return game, bears, rotter


def test_w2g6_cruel_revival_announces_both_of_its_targets(set_pool, catalog_by_name):
    """"Destroy target non-Zombie creature. It can't be regenerated. Return up
    to one target Zombie card from your graveyard to your hand." The picker is
    one walk: the non-Zombie creature first, then the Zombie cards in the
    caster's own graveyard - not the Hill Giant, not the opponent's Zombie card
    - and the card named is the card that comes back, not the first one."""
    game, bears, rotter = _w2g6_revival_table(set_pool, catalog_by_name)
    spec = game.cast_target_spec(0, set_pool("ONS")["Cruel Revival"])
    assert spec["kind"] == "roles"
    (creature,) = spec["valid_targets"]
    assert creature["name"] == "Grizzly Bears"
    assert [(entry["seat"], entry["name"]) for entry in creature["next"]] == [
        (0, "Gangrenous Goliath"), (0, "Aphetto Vulture"),
    ]

    assert game.queue_from_hand(0, "Cruel Revival", target_role_refs=[
        {"permanent_id": bears.permanent_id},
        {"graveyard_seat": 0, "graveyard_index": 2},
    ]).supported
    _w2g6_resolve_stack(game)
    assert not game.is_on_battlefield(bears) and game.is_on_battlefield(rotter)
    assert [card.name for card in game.players[0].hand] == ["Aphetto Vulture"]
    assert "Returned Aphetto Vulture from graveyard to hand" in game.log


def test_w2g6_cruel_revival_may_name_no_zombie_card(set_pool, catalog_by_name):
    """CR 601.2c's "up to one" answered with none: the creature is destroyed
    and no card comes back - the return does not go looking for one."""
    game, bears, _rotter = _w2g6_revival_table(set_pool, catalog_by_name)
    assert game.queue_from_hand(0, "Cruel Revival", target_role_refs=[
        {"permanent_id": bears.permanent_id},
    ]).supported
    _w2g6_resolve_stack(game)
    assert not game.is_on_battlefield(bears)
    assert game.players[0].hand == []
    assert [card.name for card in game.players[0].graveyard] == [
        "Hill Giant", "Gangrenous Goliath", "Aphetto Vulture", "Cruel Revival",
    ]


def test_w2g6_cruel_revival_refuses_what_its_phrases_do_not_admit(set_pool, catalog_by_name):
    """A Zombie for the creature, the Hill Giant or the opponent's Zombie card
    for the card: each refused before anything is spent."""
    for case in ("zombie creature", "non-zombie card", "their zombie card"):
        game, bears, rotter = _w2g6_revival_table(set_pool, catalog_by_name)
        refs = {
            "zombie creature": [{"permanent_id": rotter.permanent_id}],
            "non-zombie card": [
                {"permanent_id": bears.permanent_id},
                {"graveyard_seat": 0, "graveyard_index": 0},
            ],
            "their zombie card": [
                {"permanent_id": bears.permanent_id},
                {"graveyard_seat": 1, "graveyard_index": 0},
            ],
        }[case]
        refused = game.queue_from_hand(0, "Cruel Revival", target_role_refs=refs)
        assert not refused.supported, case
        assert [card.name for card in game.players[0].hand] == ["Cruel Revival"], case
        assert game.stack == [] and game.is_on_battlefield(bears), case


def test_w2g6_cruel_revival_keeps_its_legal_half(set_pool, catalog_by_name):
    """CR 608.2b, each half on its own: with the creature gone in response the
    Zombie card still comes back; with the card gone the creature is still
    destroyed. Only with both gone is the spell removed."""
    def cast_at_both(game, bears):
        return game.queue_from_hand(0, "Cruel Revival", target_role_refs=[
            {"permanent_id": bears.permanent_id},
            {"graveyard_seat": 0, "graveyard_index": 1},
        ]).supported

    game, bears, _rotter = _w2g6_revival_table(set_pool, catalog_by_name)
    assert cast_at_both(game, bears)
    game.remove_from_battlefield(bears)
    _w2g6_resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Gangrenous Goliath"]

    game, bears, _rotter = _w2g6_revival_table(set_pool, catalog_by_name)
    assert cast_at_both(game, bears)
    yard = game.players[0].graveyard
    game.players[0].exile.append(yard.pop(1))
    _w2g6_resolve_stack(game)
    assert not game.is_on_battlefield(bears)
    assert game.players[0].hand == []
    assert [card.name for card in yard] == ["Hill Giant", "Aphetto Vulture", "Cruel Revival"]

# ==== end W2G6 ======================================================
