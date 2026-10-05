"""Planeshift instants.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: lands and mana ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_cast_spec as _w1g5_derive_cast_spec
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_blessing_table(set_pool, *, mine=(), theirs=(), hand=(), library=()):
    """Seat 0's main phase with *mine*/*theirs* on the battlefield and
    Skyshroud Blessing plus *hand* in seat 0's hand. Costs are off: what the
    spell does is the question. Names resolve in Planeshift, then Alpha."""
    pls, lea = set_pool("PLS"), set_pool("LEA")

    def card(name):
        return pls[name] if name in pls else lea[name]

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(name)) for name in mine],
        hand=[pls["Skyshroud Blessing"], *(card(name) for name in hand)],
        library=[card(name) for name in library],
    )
    you = _W1G5PlayerState(
        name="W1G5-B",
        battlefield=[_W1G5Permanent(card=card(name)) for name in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game  # _w1g5_blessing_table


def _w1g5_shrouded(game) -> dict[str, bool]:
    """Every permanent on the battlefield, by ``seat:name``, and whether it has
    shroud right now (layer 6)."""
    return {
        f"{seat}:{permanent.card.name}": game._has_keyword(permanent, "shroud")
        for seat, permanent in game.permanents_with_controller()
    }  # _w1g5_shrouded


def test_w1g5_skyshroud_blessing_shrouds_every_land_and_draws(set_pool):
    """"All lands gain shroud until end of turn. Draw a card." Both sentences
    resolve: every player's lands have shroud — "all", not "you control" —
    nothing that is not a land does, and the caster draws. It names no target,
    so the picker asks for none."""
    blessing = set_pool("PLS")["Skyshroud Blessing"]
    assert _w1g5_derive_cast_spec(blessing, _w1g5_compile(blessing)) is None

    game = _w1g5_blessing_table(
        set_pool, mine=["Forest", "Grizzly Bears", "Sol Ring"],
        theirs=["Island", "Hill Giant"], library=["Swamp"],
    )
    assert game.cast_from_hand(0, "Skyshroud Blessing").supported
    _w1g5_resolve_stack(game)

    assert _w1g5_shrouded(game) == {
        "0:Forest": True, "0:Grizzly Bears": False, "0:Sol Ring": False,
        "1:Island": True, "1:Hill Giant": False,
    }
    assert [card.name for card in game.players[0].hand] == ["Swamp"]
    assert [card.name for card in game.players[0].graveyard] == ["Skyshroud Blessing"]


def test_w1g5_skyshroud_blessing_locks_its_lands_in_at_resolution(set_pool):
    """CR 611.2c: a continuous effect from a resolving spell that affects a set
    of objects fixes that set as it resolves. A land played afterwards the
    same turn does not have shroud; the lands that were there keep it."""
    game = _w1g5_blessing_table(
        set_pool, mine=["Forest"], hand=["Mountain"], library=["Swamp"],
    )
    game.cast_from_hand(0, "Skyshroud Blessing")
    _w1g5_resolve_stack(game)
    assert game.cast_from_hand(0, "Mountain").supported

    assert _w1g5_shrouded(game) == {"0:Forest": True, "0:Mountain": False}


def test_w1g5_a_shrouded_land_cannot_be_targeted_until_the_turn_ends(set_pool):
    """What shroud is for (CR 702.18a): Implode's "Destroy target land" cannot
    name a land the Blessing covered — refused at announcement with the card
    still in hand — and can name the land that arrived too late. At cleanup
    the grant ends (CR 514.2) and the first land is a legal target again."""
    game = _w1g5_blessing_table(
        set_pool, mine=["Forest"], theirs=["Island"],
        hand=["Implode", "Mountain"], library=["Swamp", "Swamp", "Swamp"],
    )
    game.cast_from_hand(0, "Skyshroud Blessing")
    _w1g5_resolve_stack(game)
    game.cast_from_hand(0, "Mountain")
    (island,) = list(game.controlled_by(1))
    (mountain,) = [p for p in game.controlled_by(0) if p.card.name == "Mountain"]

    refused = game.cast_from_hand(
        0, "Implode", target_player_index=1,
        target_permanent_ids=[island.permanent_id],
    )
    assert not refused.supported, refused
    assert "Implode" in [card.name for card in game.players[0].hand]
    assert game.is_on_battlefield(island)

    assert game.resolve_cleanup_step(0)
    assert not game._has_keyword(island, "shroud")
    game._set_phase_and_step("precombat_main", "precombat_main")
    cast = game.cast_from_hand(
        0, "Implode", target_player_index=1,
        target_permanent_ids=[island.permanent_id],
    )
    assert cast.supported, cast
    _w1g5_resolve_stack(game)
    assert not game.is_on_battlefield(island)
    assert game.is_on_battlefield(mountain)


def test_w1g5_a_typed_mass_keyword_grant_is_one_production(set_pool):
    """The grant is the team keyword grant over a board named by a card type:
    the handler had both widths (creatures, every permanent) and a filter, and
    the lowering admitted only the two widths, so "All lands gain …" was an
    unsupported subject. An invented "Artifacts you control gain shroud until
    end of turn." is the same production: your artifacts, and nobody else's."""
    (grant, _draw) = _w1g5_compile(set_pool("PLS")["Skyshroud Blessing"]).instructions
    assert grant.kind == "grant_team_keyword_until_eot"
    assert grant.payload == {
        "keywords": ("shroud",), "every_permanent": True,
        "filter": {"type_filter": "land"}, "every_seat": True,
        "duration": "end_of_turn",
    }

    invented = _w1g5_mk_card(
        name="Foundry Ward", mana_cost="{W}", type_line="Instant",
        oracle_text="Artifacts you control gain shroud until end of turn.",
    )
    game = _w1g5_blessing_table(
        set_pool, mine=["Sol Ring", "Forest"], theirs=["Sol Ring"],
    )
    game.players[0].hand.append(invented)
    assert game.cast_from_hand(0, "Foundry Ward").supported
    _w1g5_resolve_stack(game)
    assert _w1g5_shrouded(game) == {
        "0:Sol Ring": True, "0:Forest": False, "1:Sol Ring": False,
    }
