"""Nemesis artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: library, hand and graveyard ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_portal(set_pool, hand, *, chosen="Goblin"):
    """Belbe's Portal entered on seat 0 with *chosen* answered at the
    "choose a creature type" prompt, untapped and free to activate. Seat 0 is
    interactive so the activation's offers wait to be answered. W1G5's own."""
    me = _W1G5PlayerState(name="W1G5-A", hand=list(hand))
    game = _W1G5Game(players=[me, _W1G5PlayerState(name="W1G5-B")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    portal = _W1G5Permanent(card=set_pool("NEM")["Belbe's Portal"])
    game._put_permanent_onto_battlefield(0, portal, None)
    assert game.confirm_enter_choice(0, creature_type=chosen)
    portal.metadata["summoning_sickness_turn"] = -99
    return game, portal, me


def test_w1g5_belbes_portal_offers_only_the_chosen_type(set_pool):
    """"As this artifact enters, choose a creature type." / "{3}, {T}: You may
    put a creature card of the chosen type from your hand onto the
    battlefield."

    Goblin chosen, two Goblins and an Elephant in hand: the live offer is the
    two Goblins, an answer naming the Elephant is refused, and the Goblin
    answered with enters. The choice is the CR 614.1c record the entry wrote,
    read off the Portal when the ability resolves.
    """
    nem = set_pool("NEM")
    game, portal, me = _w1g5_portal(
        set_pool, [nem["Wild Mammoth"], nem["Shrieking Mogg"], nem["Mogg Toady"]]
    )
    assert portal.metadata["chosen_creature_type"] == "goblin"

    assert game.activate_permanent_ability(0, "Belbe's Portal").supported
    assert portal.tapped
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, True, None)
    pick = game.pending_choice_of("put_from_hand_choice", 0)
    assert game.live_put_from_hand_choices(pick) == [1, 2]
    assert not game.confirm_put_from_hand_choice(0, 0), "an Elephant is not a Goblin"
    assert game.confirm_put_from_hand_choice(0, 1)
    _w1g5_resolve_stack(game)

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Belbe's Portal", "Shrieking Mogg",
    ]
    assert [c.name for c in me.hand] == ["Wild Mammoth", "Mogg Toady"]


def test_w1g5_belbes_portal_with_nothing_of_the_type_puts_nothing(set_pool):
    """Elephant chosen and no Elephant in hand: the offer has nothing to give,
    so nothing enters — the narrowing is not dropped into "any creature card"
    for want of a match."""
    nem = set_pool("NEM")
    game, _, me = _w1g5_portal(
        set_pool, [nem["Shrieking Mogg"], nem["Mogg Toady"]], chosen="Elephant"
    )
    game.activate_permanent_ability(0, "Belbe's Portal")
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [p.card.name for p in game.controlled_by(0)] == ["Belbe's Portal"]
    assert len(me.hand) == 2


def test_w1g5_belbes_portal_without_a_record_offers_nothing(set_pool):
    """The fail-closed half: a Portal whose chosen type is somehow absent must
    not fall back to every creature card. ``_card_matches_filter`` refuses the
    unresolved key, the way ``permanent_matches_filter`` already did."""
    nem = set_pool("NEM")
    game, portal, _ = _w1g5_portal(set_pool, [nem["Shrieking Mogg"]])
    portal.metadata.pop("chosen_creature_type")
    game.activate_permanent_ability(0, "Belbe's Portal")
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [p.card.name for p in game.controlled_by(0)] == ["Belbe's Portal"]


# --- W1G4: amounts and bounded targets ---
# Two artifacts whose number is read off something else: Belbe's Armor's
# announced X, signed both ways on one creature, and Eye of Yawgmoth's count
# taken off the creature its own cost sacrificed (CR 601.2h, read back as
# CR 608.2h's last-known information).
from engine import Game as _W1g4Game
from engine import PlayerState as _W1g4PlayerState
from engine.models import CardDefinition as _W1g4Card
from engine.models import Permanent as _W1g4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_activation_spec as _w1g4_activation_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_artifact_creature(name, power, toughness):
    """A vanilla test creature; the name says its size."""
    line = "Creature - Test"
    return _W1g4Card(
        name=name, mana_cost="", cmc=0.0, type_line=line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4_artifact_table(seat0=(), seat1=(), library=()):
    """Two seats, costs unenforced, P0's main phase with priority open."""
    table = _W1g4Game(players=[
        _W1g4PlayerState(name="P0", battlefield=list(seat0), library=list(library)),
        _W1g4PlayerState(name="P1", battlefield=list(seat1)),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set()
    table.start_turn(0)
    table._close_current_priority_step()
    return table


def test_w1g4_belbes_armor_shrinks_power_and_grows_toughness_by_the_announced_x(
    set_pool,
):
    """"{X}, {T}: Target creature gets -X/+X until end of turn."

    The negated X is the half that used to refuse ("negative variable pump is
    not supported"): it travels as ``{"times_x": -1}``, the shape a "-1/-1 for
    each" repetition already lowers to, so the one amount reader applies the
    sign. A sign carried beside a bare "x" would be honoured only by handlers
    taught to read it — every other one would *grow* the creature.
    """
    armor = _W1g4Permanent(card=set_pool("NEM")["Belbe's Armor"])
    bear = _W1g4Permanent(card=_w1g4_artifact_creature("Bear 2/2", 2, 2))
    game = _w1g4_artifact_table((armor,), (bear,))
    ability = _w1g4_compile(armor.card).activated_abilities[0]
    assert _w1g4_activation_spec(ability) == {"kind": "creature"}

    result = game.activate_permanent_ability(
        0, "Belbe's Armor", target_player_index=1,
        target_permanent_ids=[bear.permanent_id], x_value=3,
    )
    assert result.supported, result
    _w1g4_resolve(game)

    assert (bear.effective_power, bear.effective_toughness) == (-1, 5)
    assert armor.tapped
    assert "Belbe's Armor gives Bear 2/2 -3/+3 until end of turn" in game.log


def test_w1g4_eye_of_yawgmoth_reveals_as_many_as_the_sacrificed_power(set_pool):
    """"{3}, {T}, Sacrifice a creature: Reveal a number of cards from the top of
    your library equal to the sacrificed creature's power. Put one into your
    hand and exile the rest."

    The count is the sacrificed creature's power *as it last existed* (CR
    608.2h) — the payment path's record, not a board read, since by resolution
    the creature is a card in a graveyard. The reveal is CR 701.20a's public
    one, recorded for every player; the pick and the exile are the look-and-
    pick procedure the family already runs (Browse's destinations).
    """
    eye = _W1g4Permanent(card=set_pool("NEM")["Eye of Yawgmoth"])
    fodder = _W1g4Permanent(card=_w1g4_artifact_creature("Fodder 3/1", 3, 1))
    library = [_w1g4_artifact_creature(f"Card {i}", 1, 1) for i in range(5)]
    game = _w1g4_artifact_table((eye, fodder), library=library)

    result = game.activate_permanent_ability(
        0, "Eye of Yawgmoth", cost_permanent_ids=[fodder.permanent_id],
    )
    assert result.supported, result
    _w1g4_resolve(game)

    assert not game.is_on_battlefield(fodder)
    assert game.reveal_events[-1]["cards"] == ["Card 0", "Card 1", "Card 2"]
    assert game.pending_choice_of("look_top_pick", 0) is not None
    assert game.confirm_look_top_pick(0, 1)

    me = game.players[0]
    assert [card.name for card in me.hand] == ["Card 1"]
    assert sorted(card.name for card in me.exile) == ["Card 0", "Card 2"]
    assert [card.name for card in me.library] == ["Card 3", "Card 4"]


def test_w1g4_eye_of_yawgmoth_reads_last_known_power_not_the_printed_one(set_pool):
    """A pumped creature sacrificed for the cost reveals its *pumped* power: the
    record carries the permanent, whose computed power is what it had on the
    battlefield (CR 608.2h). The printed 1 would reveal one card."""
    from engine.pt import add_pt_modifier

    eye = _W1g4Permanent(card=set_pool("NEM")["Eye of Yawgmoth"])
    fodder = _W1g4Permanent(card=_w1g4_artifact_creature("Fodder 1/1", 1, 1))
    library = [_w1g4_artifact_creature(f"Card {i}", 1, 1) for i in range(5)]
    game = _w1g4_artifact_table((eye, fodder), library=library)
    add_pt_modifier(fodder, 3, 0)

    game.activate_permanent_ability(
        0, "Eye of Yawgmoth", cost_permanent_ids=[fodder.permanent_id],
    )
    _w1g4_resolve(game)

    assert len(game.reveal_events[-1]["cards"]) == 4


# --- W1G6: lands, mana and untapping ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g6_art_take_turn(game, seat):
    """Start *seat*'s turn and settle what its beginning phase put on the stack."""
    game.start_turn(seat)
    for _ in range(4):
        game.auto_resolve_pending_choices()
        if not resolve_stack(game):
            break
    return game.turn


def _w1g6_kill_switch_board(set_pool, *, own_before_switch):
    """Kill Switch beside its controller's own artifact, in either board
    order, and one artifact on the other seat."""
    lea = set_pool("LEA")
    switch = Permanent(card=set_pool("NEM")["Kill Switch"])
    mine = Permanent(card=lea["Jayemdae Tome"])
    theirs = Permanent(card=lea["Howling Mine"])
    ours = [mine, switch] if own_before_switch else [switch, mine]
    players = [
        PlayerState(name="P0", battlefield=ours, library=[lea["Island"]] * 8),
        PlayerState(name="P1", battlefield=[theirs], library=[lea["Island"]] * 8),
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._settle()
    return game, switch, mine, theirs


@pytest.mark.parametrize("own_before_switch", [True, False])
def test_kill_switch_holds_the_artifacts_it_tapped_while_it_stays_tapped(
    set_pool, own_before_switch
):
    """"{2}, {T}: Tap all other artifacts. They don't untap during their
    controllers' untap steps for as long as this artifact remains tapped."

    "They" is the set the sweep named, by identity: not the Switch ("other"),
    and not an artifact that arrives afterwards. The opponent's artifact stays
    down through their untap step; the Switch's controller's own stays down
    through the very step the Switch untaps in, because CR 502.3 determines
    what untaps *before* untapping anything — in either board order, which is
    what the parametrize is for (the step used to read the lock live, so a
    Switch earlier in the list released what came after it).
    """
    game, switch, mine, theirs = _w1g6_kill_switch_board(
        set_pool, own_before_switch=own_before_switch
    )
    _w1g6_art_take_turn(game, 0)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(0, "Kill Switch", ability_index=0)
    resolve_stack(game)

    assert result.supported, result.details
    assert switch.tapped and mine.tapped and theirs.tapped
    late = Permanent(card=set_pool("LEA")["Sol Ring"])
    game.players[1].battlefield.append(late)
    game._settle()
    late.tapped = True

    _w1g6_art_take_turn(game, 1)
    assert theirs.tapped, "held through its controller's untap step"
    assert not late.tapped, "an artifact the sweep never named is not held"

    _w1g6_art_take_turn(game, 0)
    assert not switch.tapped, "the Switch prints no choice to stay tapped"
    assert mine.tapped, "held through the step the Switch untapped in"

    _w1g6_art_take_turn(game, 1)
    assert not theirs.tapped, "released once the Switch untapped"
    _w1g6_art_take_turn(game, 0)
    assert not mine.tapped
