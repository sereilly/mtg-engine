"""Invasion instants.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: colour census ---
from engine import Game as _W1G4InstantGame
from engine import PlayerState as _W1G4InstantSeat
from engine.models import Permanent as _W1G4InstantPermanent
from tests.helpers import resolve_stack as _w1g4_instant_resolve


def _w1g4_spell_table(*hand):
    """Two seats, seat 0 holding *hand*, mana costs off; the spells' own rig."""
    w1g4_spell_game = _W1G4InstantGame(players=[
        _W1G4InstantSeat(name="W1G4-caster", hand=list(hand)),
        _W1G4InstantSeat(name="W1G4-other"),
    ])
    w1g4_spell_game.enforce_mana_costs = False
    w1g4_spell_game.active_player_index = 0
    return w1g4_spell_game


def _w1g4_onto(game, seat, card):
    """*card* onto *seat*'s battlefield through the real entry seam."""
    w1g4_spell_permanent = _W1G4InstantPermanent(card=card)
    game._put_permanent_onto_battlefield(seat, w1g4_spell_permanent, None)
    game.check_state_based_actions()
    return w1g4_spell_permanent


def _w1g4_aim(game, name, permanent):
    """Seat 0 casts *name* at *permanent* and the stack drains; the cast's result."""
    w1g4_cast = game.cast_from_hand(
        0, name, target_player_index=game.controller_index_of(permanent),
        target_permanent_ids=[permanent.permanent_id],
    )
    _w1g4_instant_resolve(game)
    game.check_state_based_actions()
    return w1g4_cast


def test_w1g4_barrins_unmaking_bounces_only_a_permanent_of_a_leading_colour(set_pool):
    """"Return target permanent to its owner's hand if that permanent shares a
    color with the most common color among all permanents or a color tied for
    most common."

    Any permanent is a legal target (the picker offers a permanent, with no
    colour on it) and the spell resolves either way; what it *does* depends on
    the census taken at resolution. A trailing colour and a colourless artifact
    stay; a leading creature and a leading *enchantment* both go to their
    owner's hand.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    inv, lea = set_pool("INV"), set_pool("LEA")
    unmaking = inv["Barrin's Unmaking"]
    assert derive_cast_spec(unmaking, compile_card_oracle(unmaking)) == {"kind": "permanent"}

    game = _w1g4_spell_table(*[unmaking] * 4)
    bear = _w1g4_onto(game, 1, lea["Grizzly Bears"])       # G1
    lions = _w1g4_onto(game, 1, lea["Savannah Lions"])     # W
    crusade = _w1g4_onto(game, 0, lea["Crusade"])          # W enchantment: W2
    mox = _w1g4_onto(game, 1, lea["Mox Pearl"])            # colourless

    assert _w1g4_aim(game, "Barrin's Unmaking", bear).supported
    assert game.is_on_battlefield(bear), "green trails white"
    assert _w1g4_aim(game, "Barrin's Unmaking", mox).supported
    assert game.is_on_battlefield(mox), "a colourless permanent shares no colour"

    assert _w1g4_aim(game, "Barrin's Unmaking", crusade).supported
    assert not game.is_on_battlefield(crusade)
    assert [card.name for card in game.players[0].hand].count("Crusade") == 1

    # W1, G1 now: tied, and a colour tied for most common counts.
    assert _w1g4_aim(game, "Barrin's Unmaking", lions).supported
    assert not game.is_on_battlefield(lions)
    assert [card.name for card in game.players[1].hand] == ["Savannah Lions"]
    assert len(game.players[0].graveyard) == 4, "every copy resolved"


def test_w1g4_barrins_unmaking_does_nothing_on_a_board_with_no_colour(set_pool):
    """The spell is on the stack while it resolves, so it is not one of "all
    permanents": aimed at an artifact on a board of lands, there is no most
    common colour for the target to share and it stays put.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_spell_table(inv["Barrin's Unmaking"])
    mox = _w1g4_onto(game, 1, lea["Mox Pearl"])
    _w1g4_onto(game, 0, lea["Island"])
    assert _w1g4_aim(game, "Barrin's Unmaking", mox).supported
    assert game.is_on_battlefield(mox)
    assert game.players[1].hand == []


def test_w1g4_lightning_dart_deals_one_damage_or_four_never_both(set_pool):
    """"Lightning Dart deals 1 damage to target creature. If that creature is
    white or blue, Lightning Dart deals 4 damage to it instead."

    One damage event whose size the target's colour decides at resolution
    (CR 608.2c): a green 6/4 takes 1, a white 4/4 and a blue 4/4 each take
    exactly 4 — not 5 — and die. A creature a Purelace has turned white takes
    the 4 too, because the colour is the computed one.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    inv, lea = set_pool("INV"), set_pool("LEA")
    dart = inv["Lightning Dart"]
    assert derive_cast_spec(dart, compile_card_oracle(dart)) == {"kind": "creature"}

    game = _w1g4_spell_table(*[dart] * 4, lea["Purelace"])
    wurm = _w1g4_onto(game, 1, lea["Craw Wurm"])
    angel = _w1g4_onto(game, 1, lea["Serra Angel"])
    elemental = _w1g4_onto(game, 1, lea["Air Elemental"])
    giant = _w1g4_onto(game, 1, lea["Hill Giant"])           # red 3/3

    assert _w1g4_aim(game, "Lightning Dart", wurm).supported
    assert wurm.damage_marked == 1 and game.is_on_battlefield(wurm)
    assert "Lightning Dart dealt 1 damage to Craw Wurm" in game.log

    assert _w1g4_aim(game, "Lightning Dart", angel).supported
    assert "Lightning Dart dealt 4 damage to Serra Angel" in game.log
    assert not game.is_on_battlefield(angel)
    assert _w1g4_aim(game, "Lightning Dart", elemental).supported
    assert not game.is_on_battlefield(elemental)
    assert not any("dealt 5 damage" in line for line in game.log)

    assert _w1g4_aim(game, "Purelace", giant).supported
    assert _w1g4_aim(game, "Lightning Dart", giant).supported
    assert not game.is_on_battlefield(giant), "a 3/3 made white takes 4"
    assert [player.life for player in game.players] == [20, 20]


def test_w1g4_lightning_dart_cannot_be_aimed_at_a_noncreature(set_pool):
    """The target phrase is "target creature" in both sentences — the second's
    "it" is the first's target, not a second choice — so a land is refused at
    announcement with nothing spent.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_spell_table(inv["Lightning Dart"])
    plains = _w1g4_onto(game, 1, lea["Plains"])
    refused = game.cast_from_hand(
        0, "Lightning Dart", target_player_index=1,
        target_permanent_ids=[plains.permanent_id],
    )
    assert not refused.supported
    assert [card.name for card in game.players[0].hand] == ["Lightning Dart"]
