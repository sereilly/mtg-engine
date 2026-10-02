"""Nemesis sorceries.

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


# --- W1G4: amounts and bounded targets ---
# Four sorceries whose number or whose target is read off the board: Flowstone
# Slide's announced X signed both ways over a sweep, Rupture's power frozen as
# its own first sentence sacrifices the creature, Stronghold Discipline's one
# count per losing seat, and Topple's superlative as a *target restriction*.
from engine import Game as _W1g4Game
from engine import PlayerState as _W1g4PlayerState
from engine.models import CardDefinition as _W1g4Card
from engine.models import Permanent as _W1g4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_sorcery_creature(name, power, toughness, keywords=()):
    """A test creature; keywords are printed as its only line."""
    line = "Creature - Test"
    return _W1g4Card(
        name=name, mana_cost="", cmc=0.0, type_line=line,
        oracle_text=", ".join(word.capitalize() for word in keywords),
        colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4_sorcery_table(hand, seat0=(), seat1=()):
    """Two seats, costs unenforced, P0 holding *hand* in its main phase."""
    table = _W1g4Game(players=[
        _W1g4PlayerState(name="P0", battlefield=list(seat0), hand=list(hand)),
        _W1g4PlayerState(name="P1", battlefield=list(seat1)),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set()
    table.start_turn(0)
    table._close_current_priority_step()
    return table


def test_w1g4_flowstone_slide_pumps_power_and_shrinks_toughness_by_x(set_pool):
    """"All creatures get +X/-X until end of turn."

    Both seats' creatures, X the announced one. A creature whose toughness
    reaches 0 dies to the state-based check (CR 704.5f) — not destruction, so
    nothing could regenerate it. The sweep used to resolve every "x" at 0 when
    no count sized it; it now falls back to the announced X like the targeted
    pumps beside it.
    """
    slide = set_pool("NEM")["Flowstone Slide"]
    small = _W1g4Permanent(card=_w1g4_sorcery_creature("Small 2/2", 2, 2))
    sturdy = _W1g4Permanent(card=_w1g4_sorcery_creature("Sturdy 1/3", 1, 3))
    game = _w1g4_sorcery_table((slide,), (small,), (sturdy,))

    result = game.cast_from_hand(0, "Flowstone Slide", x_value=2)

    assert result.supported, result
    assert not game.is_on_battlefield(small)
    assert "Small 2/2 died (704.5f: toughness 0)" in game.log
    assert (sturdy.effective_power, sturdy.effective_toughness) == (3, 1)


def test_w1g4_rupture_deals_the_sacrificed_creatures_power(set_pool):
    """"Sacrifice a creature. Rupture deals damage equal to that creature's
    power to each creature without flying and each player."

    "That creature" is the one the first sentence sacrificed; by the time the
    damage is dealt it is a card in a graveyard with no computed power at all
    (CR 613.1), so the power is frozen as it is sacrificed (CR 608.2h) — the
    record the destroy step writes for the same words. The flier is spared, the
    caster is hit too.
    """
    rupture = set_pool("NEM")["Rupture"]
    big = _W1g4Permanent(card=_w1g4_sorcery_creature("Big 4/4", 4, 4))
    bird = _W1g4Permanent(card=_w1g4_sorcery_creature("Bird 1/1", 1, 1, ("flying",)))
    ogre = _W1g4Permanent(card=_w1g4_sorcery_creature("Ogre 3/3", 3, 3))
    game = _w1g4_sorcery_table((rupture,), (big,), (bird, ogre))
    assert _w1g4_cast_spec(rupture, _w1g4_compile(rupture)) is None

    result = game.cast_from_hand(0, "Rupture")

    assert result.supported, result
    assert not game.is_on_battlefield(big)
    assert not game.is_on_battlefield(ogre)
    assert game.is_on_battlefield(bird)
    assert (game.players[0].life, game.players[1].life) == (16, 16)


def test_w1g4_rupture_with_nothing_to_sacrifice_deals_nothing(set_pool):
    """No creature sacrificed, so "that creature's power" names nothing and the
    damage is zero rather than a number the card never printed."""
    rupture = set_pool("NEM")["Rupture"]
    ogre = _W1g4Permanent(card=_w1g4_sorcery_creature("Ogre 3/3", 3, 3))
    game = _w1g4_sorcery_table((rupture,), (), (ogre,))

    game.cast_from_hand(0, "Rupture")

    assert game.is_on_battlefield(ogre)
    assert ogre.damage_marked == 0
    assert (game.players[0].life, game.players[1].life) == (20, 20)


def test_w1g4_stronghold_discipline_counts_each_losers_own_creatures(set_pool):
    """"Each player loses 1 life for each creature they control."

    One number per seat, counted on that seat's own battlefield — the
    per-recipient channel the damage sweeps read for "that player controls".
    A single shared count would cost both players the same.
    """
    discipline = set_pool("NEM")["Stronghold Discipline"]
    mine = [_W1g4Permanent(card=_w1g4_sorcery_creature(f"Mine {i}", 1, 1)) for i in range(2)]
    theirs = [_W1g4Permanent(card=_w1g4_sorcery_creature(f"Theirs {i}", 1, 1)) for i in range(3)]
    game = _w1g4_sorcery_table((discipline,), mine, theirs)

    game.cast_from_hand(0, "Stronghold Discipline")

    assert (game.players[0].life, game.players[1].life) == (18, 17)


def test_w1g4_topple_offers_only_the_creatures_tied_for_greatest_power(set_pool):
    """"Exile target creature with the greatest power among creatures on the
    battlefield." CR 601.2c: the superlative is a restriction on what may be
    named, so the picker offers only the tied-greatest — on either battlefield
    — and an announcement naming a smaller creature is refused before the
    spell is paid for."""
    topple = set_pool("NEM")["Topple"]
    mine = _W1g4Permanent(card=_w1g4_sorcery_creature("Mine 4/4", 4, 4))
    rival = _W1g4Permanent(card=_w1g4_sorcery_creature("Rival 4/1", 4, 1))
    small = _W1g4Permanent(card=_w1g4_sorcery_creature("Small 2/2", 2, 2))
    game = _w1g4_sorcery_table((topple,), (mine,), (rival, small))

    offered = {
        entry["name"] for entry in game.cast_target_spec(0, topple)["valid_targets"]
    }
    assert offered == {"Mine 4/4", "Rival 4/1"}
    refused = game.cast_from_hand(
        0, "Topple", target_player_index=1, target_permanent_ids=[small.permanent_id],
    )
    assert not refused.supported
    assert game.is_on_battlefield(small) and [c.name for c in game.players[0].hand] == ["Topple"]

    game.cast_from_hand(
        0, "Topple", target_player_index=1, target_permanent_ids=[rival.permanent_id],
    )
    assert not game.is_on_battlefield(rival)
    assert [card.name for card in game.players[1].exile] == ["Rival 4/1"]


def test_w1g4_topple_exiles_nothing_once_its_target_is_no_longer_the_greatest(
    set_pool,
):
    """The restriction is asked again at resolution (CR 608.2b): pump a rival
    past the target in response and the target is illegal, so nothing is
    exiled — and in particular not the creature that is now the greatest."""
    from engine.pt import add_pt_modifier

    topple = set_pool("NEM")["Topple"]
    mine = _W1g4Permanent(card=_w1g4_sorcery_creature("Mine 4/4", 4, 4))
    rival = _W1g4Permanent(card=_w1g4_sorcery_creature("Rival 4/1", 4, 1))
    game = _w1g4_sorcery_table((topple,), (mine,), (rival,))

    queued = game.queue_from_hand(
        0, "Topple", target_player_index=1, target_permanent_ids=[rival.permanent_id],
    )
    assert queued.supported, queued
    add_pt_modifier(mine, 1, 0)
    _w1g4_resolve(game)

    assert game.is_on_battlefield(rival) and game.is_on_battlefield(mine)
    assert game.players[0].exile == [] and game.players[1].exile == []
