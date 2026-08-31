"""Per-card tests for Legends' instants, from round 35 onward.

Split from `test_legends_instants.py` at the 2,600-line readability cap. The
type axis has no room left here — every card in both files is an instant — so
the cut is a **round boundary**, the division `tests/sets/README.md` names once
a printed type outgrows a file, and the one
`test_legends_creatures_late_rounds.py` already made for that set's creatures.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _creature(name: str, colors: tuple[str, ...] = ("G",)) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    )

# ---------------------------------------------------------------------------
# Remove Enchantments (round 35). "Return to your hand all enchantments you
# both own and control, all Auras you own attached to permanents you control,
# and all Auras you own attached to attacking creatures your opponents
# control. Then destroy all other enchantments you control, all other Auras
# attached to permanents you control, and all other Auras attached to
# attacking creatures your opponents control."
#
# Two sweeps over a union of three noun phrases each, and every phrase names a
# *seat* — ownership on the first sweep, the host's controller inside two of
# them. The whole card is one long argument that a dropped narrowing on a
# sweep is not a card that does less.
# ---------------------------------------------------------------------------


def _r35_enchantment(name: str, aura: bool = False) -> CardDefinition:
    line = "Enchantment - Aura" if aura else "Enchantment"
    return CardDefinition(
        name=name, mana_cost="{W}", cmc=1.0, type_line=line,
        oracle_text="Enchant permanent" if aura else "",
        colors=("W",), color_identity=("W",), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line},
    )


def _r35_board(set_pool):
    """One of every case the card distinguishes, on one battlefield.

    Seat 0 casts the spell. Ownership is set explicitly where it differs from
    control, because that difference is the whole of the first sweep's
    narrowing.
    """
    spell = set_pool("LEG")["Remove Enchantments"]
    mine = Permanent(card=_creature("My Bear"))
    attacker = Permanent(card=_creature("Their Attacker"))
    resting = Permanent(card=_creature("Their Bear"))

    plain = Permanent(card=_r35_enchantment("Mine Outright"))
    borrowed = Permanent(card=_r35_enchantment("Theirs, I Control"))
    on_mine = Permanent(card=_r35_enchantment("Mine, On Mine", aura=True))
    theirs_on_mine = Permanent(card=_r35_enchantment("Theirs, On Mine", aura=True))
    on_attacker = Permanent(card=_r35_enchantment("Mine, On Attacker", aura=True))
    on_resting = Permanent(card=_r35_enchantment("Theirs, On Their Bear", aura=True))
    on_their_attacker = Permanent(
        card=_r35_enchantment("Theirs, On Their Attacker", aura=True)
    )

    # An Aura is a permanent of its own: seat 0 casting one on seat 1's
    # creature controls the Aura and it sits on seat 0's battlefield, however
    # far away its host is.
    p1 = PlayerState(
        name="P1", hand=[spell],
        battlefield=[
            mine, plain, borrowed, on_mine, theirs_on_mine, on_attacker,
        ],
    )
    p2 = PlayerState(
        name="P2", battlefield=[attacker, resting, on_resting, on_their_attacker],
    )
    game = Game(players=[p1, p2])
    # Two permanents seat 0 controls and seat 1 owns (CR 108.3): a stolen
    # enchantment, and an Aura seat 1 cast on seat 0's creature. Ownership is
    # the first sweep's whole narrowing, so the card has to tell them apart
    # from the ones beside them that look identical.
    borrowed.metadata["owner_player_index"] = 1
    theirs_on_mine.metadata["owner_player_index"] = 1
    attach_aura(on_mine, mine)
    attach_aura(theirs_on_mine, mine)
    attach_aura(on_attacker, attacker)
    attach_aura(on_resting, resting)
    attach_aura(on_their_attacker, attacker)
    attacker.attacking = True
    game._settle()
    return game, p1, p2, {
        "plain": plain, "borrowed": borrowed, "on_mine": on_mine,
        "theirs_on_mine": theirs_on_mine, "on_attacker": on_attacker,
        "on_resting": on_resting, "on_their_attacker": on_their_attacker,
    }


def test_r35_remove_enchantments_compiles_to_six_sweeps(set_pool):
    """Three noun phrases per sentence, one instruction each — the union is a
    shape (a conjunction of statements), never a filter, because an
    ObjectFilter's keys are AND'd and the three folded together would name
    nothing at all."""
    program = compile_card_oracle(set_pool("LEG")["Remove Enchantments"])
    assert program.supported, program.reason
    sweeps = program.instructions[0].payload["steps"]
    assert [i.kind for i in sweeps] == [
        "return_all_matching", "return_all_matching", "return_all_matching",
        "destroy_all_matching", "destroy_all_matching", "destroy_all_matching",
    ]
    # Every phrase's seat survived to the payload. The first sweep's ownership
    # is what keeps it from returning the opponent's copy; the host phrase is
    # what keeps the Aura sweeps off the rest of the board.
    assert all(i.payload["filter"]["owner"] == "you" for i in sweeps[:3])
    assert sweeps[1].payload["filter"]["attached_to_filter"] == {"controller": "you"}
    assert sweeps[2].payload["filter"]["attached_to_filter"] == {
        "type_filter": "creature", "controller": "opponent", "attacking_only": True,
    }
    # The destroy half narrows the Aura by nothing but where it is attached —
    # an opponent's Aura on your permanent is destroyed, which is why these
    # three carry no ``owner`` and the three above do.
    assert all("owner" not in i.payload for i in sweeps[3:])


def test_r35_remove_enchantments_returns_what_it_owns_and_destroys_the_rest(set_pool):
    """Run in a game, because the compiler cannot tell a sweep that honours a
    seat from one that ignores it — both compile."""
    game, p1, p2, perms = _r35_board(set_pool)

    assert game.cast_from_hand(0, "Remove Enchantments").supported
    game.resolve_top_of_stack()
    game._settle()

    returned = {card.name for card in p1.hand}
    assert returned == {
        # "…you both own and control."
        "Mine Outright",
        # "…all Auras you own attached to permanents you control."
        "Mine, On Mine",
        # "…all Auras you own attached to attacking creatures your opponents
        # control."
        "Mine, On Attacker",
    }
    # Seat 1's own Aura on seat 1's own creature, which is not attacking. No
    # phrase of either sentence names it, and it is the case a sweep that
    # dropped ``attacking_only`` — or dropped the host phrase entirely — would
    # have taken. Six of the nine permanents move; this is the reason the card
    # is not simply "destroy all enchantments".
    assert game.is_on_battlefield(perms["on_resting"])
    # Everything the second sentence names is gone: the enchantment seat 0
    # controls but does not own (so the *first* sweep left it), the Aura seat 1
    # owns sitting on seat 0's creature, and seat 1's own Aura on their own
    # attacking creature — none of which carry an ownership narrowing.
    for key in ("plain", "borrowed", "on_mine", "theirs_on_mine", "on_attacker",
                "on_their_attacker"):
        assert not game.is_on_battlefield(perms[key]), key
    assert {card.name for card in p2.hand} == set()
    # CR 400.3: each destroyed card goes to its *owner's* graveyard.
    assert {card.name for card in p1.graveyard} == {"Remove Enchantments"}
    assert {card.name for card in p2.graveyard} == {
        "Theirs, I Control", "Theirs, On Mine", "Theirs, On Their Attacker",
    }


# --- FixC: a sweep names a class, not a target ---
def _fixc_reset_board(set_pool):
    """Reset in seat 0's hand, two of their lands tapped, one of seat 1's."""
    lea = set_pool("LEA")
    mine = [Permanent(card=lea["Forest"], tapped=True),
            Permanent(card=lea["Island"], tapped=True)]
    theirs = Permanent(card=lea["Island"], tapped=True)
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("LEG")["Reset"]], battlefield=mine),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    # The card's own window: an opponent's turn, after their upkeep step.
    game.active_player_index = 1
    game.current_turn_phase = "beginning"
    game.current_step = "draw"
    return game, mine, theirs


def test_reset_asks_for_no_land_it_is_about_to_untap(set_pool):
    """"Untap all lands you control." — a class, not a target (CR 115.1a).

    It reported ``kind: "land"`` with ``own_only``, so the browser demanded a
    click on one of the very lands the spell untaps all of. The click changed
    nothing, which is the tell: a picker whose answer no handler reads.
    """
    game, _mine, _theirs = _fixc_reset_board(set_pool)

    assert game.cast_target_spec(0, set_pool("LEG")["Reset"]) == {
        "kind": "none", "requires_target": False, "valid_targets": [],
    }


def test_reset_untaps_every_land_of_its_casters_with_nothing_named(set_pool):
    """And the sweep still reads every word of its own description — the
    opponent's land stays tapped."""
    game, mine, theirs = _fixc_reset_board(set_pool)

    result = game.cast_from_hand(0, "Reset")
    game._settle()

    assert result.supported, result.details
    assert all(not land.tapped for land in mine)
    assert theirs.tapped


def test_reset_is_castable_with_no_land_to_untap_at_all(set_pool):
    """The board the client refused: nothing for a picker to offer, and a
    spell whose sweep is simply empty."""
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("LEG")["Reset"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game.current_turn_phase = "beginning"
    game.current_step = "draw"

    result = game.cast_from_hand(0, "Reset")
    game._settle()

    assert result.supported, result.details


def test_remove_enchantments_chooses_none_of_the_enchantments_it_moves(set_pool):
    """Three sweeps in one sentence — return yours, then destroy the rest —
    and its last clause's ``type_filter`` was read as a picker, so the spell
    reported "target permanent you control" and could not be cast without
    one."""
    pool = set_pool("LEG")
    lea = set_pool("LEA")
    mine = Permanent(card=lea["Circle of Protection: Red"])
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Remove Enchantments"]],
                    battlefield=[mine]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._sync_control()

    assert game.cast_target_spec(0, pool["Remove Enchantments"]) == {
        "kind": "none", "requires_target": False, "valid_targets": [],
    }

    result = game.cast_from_hand(0, "Remove Enchantments")
    game._settle()

    assert result.supported, result.details
    assert game.players[0].battlefield == []
    assert [c.name for c in game.players[0].hand] == ["Circle of Protection: Red"]
# --- end FixC ---
