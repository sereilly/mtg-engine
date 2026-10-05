"""Planeshift creatures.

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
from engine.mana_payment import is_mana_ability as _w1g5_is_mana_ability
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_creature_table(set_pool, *, mine=(), theirs=(), hand=(), interactive=(), costs=True):
    """Seat 0's main phase over a board that is already there, nobody
    summoning-sick. Names resolve in Planeshift, then Alpha. Costs are
    enforced unless a test says otherwise."""
    pls, lea = set_pool("PLS"), set_pool("LEA")

    def card(name):
        return pls[name] if name in pls else lea[name]

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(name)) for name in mine],
        hand=[card(name) for name in hand],
    )
    you = _W1G5PlayerState(
        name="W1G5-B",
        battlefield=[_W1G5Permanent(card=card(name)) for name in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = costs
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game  # _w1g5_creature_table


def _w1g5_one(game, seat: int, name: str):
    (found,) = [p for p in game.controlled_by(seat) if p.card.name == name]
    return found  # _w1g5_one


def _w1g5_mana(game, seat: int = 0) -> dict[str, int]:
    return {
        symbol: amount
        for symbol, amount in game.players[seat].mana_pool.items() if amount
    }  # _w1g5_mana


def _w1g5_activate(game, name: str, **announced):
    """Activate *name*'s ability under seat 0; the engine's answer."""
    source = _w1g5_one(game, 0, name)
    return game.activate_permanent_ability(
        0, name, permanent_index=game.battlefield_index_of(source), **announced
    )  # _w1g5_activate


def test_w1g5_quirion_explorer_sees_all_three_of_a_lairs_colours(set_pool):
    """"{T}: Add one mana of any color that a land an opponent controls could
    produce." Supported on arrival and never run. Facing a Lair it makes any of
    the Lair's three and not a fourth; an interactive seat that names no colour
    is offered exactly those three, in WUBRG order every time (the list used
    to come out in a set's order, which changes from process to process)."""
    for asked in "UBR":
        game = _w1g5_creature_table(
            set_pool, mine=["Quirion Explorer"], theirs=["Crosis's Catacombs"],
        )
        assert _w1g5_activate(game, "Quirion Explorer", mana_color=asked).supported
        assert not game.stack and _w1g5_mana(game) == {asked: 1}

    game = _w1g5_creature_table(
        set_pool, mine=["Quirion Explorer"], theirs=["Crosis's Catacombs"],
    )
    _w1g5_activate(game, "Quirion Explorer", mana_color="G")
    made = _w1g5_mana(game)
    assert sum(made.values()) == 1 and set(made) <= set("UBR"), made

    asking = _w1g5_creature_table(
        set_pool, mine=["Quirion Explorer"], theirs=["Crosis's Catacombs"],
        interactive={0},
    )
    _w1g5_activate(asking, "Quirion Explorer")
    assert asking.pending_choice_of("mana_color_choice", 0).data["colors"] == [
        "U", "B", "R",
    ]


def test_w1g5_quirion_explorer_reads_a_meteor_crater_for_what_it_makes_now(set_pool):
    """CR 106.7: what a land "could produce" is what its ability would make if
    it resolved now. Scryfall summarises Meteor Crater as all five colours, so
    an Explorer facing a lone Crater was handed five; the Crater's controller
    has no coloured permanent, it could produce nothing, and the Explorer adds
    no mana. With a Hill Giant beside the Crater, the Explorer makes red."""
    bare = _w1g5_creature_table(
        set_pool, mine=["Quirion Explorer"], theirs=["Meteor Crater"],
    )
    assert _w1g5_activate(bare, "Quirion Explorer", mana_color="R").supported
    assert _w1g5_mana(bare) == {}
    assert _w1g5_one(bare, 0, "Quirion Explorer").tapped

    red = _w1g5_creature_table(
        set_pool, mine=["Quirion Explorer"], theirs=["Meteor Crater", "Hill Giant"],
    )
    _w1g5_activate(red, "Quirion Explorer", mana_color="G")
    assert _w1g5_mana(red) == {"R": 1}


def test_w1g5_morgue_toad_is_sacrificed_for_blue_and_red(set_pool):
    """"Sacrifice this creature: Add {U}{R}." A mana ability (CR 605.1a) whose
    whole cost is the Toad: both mana arrive at once without the stack, the
    Toad is in its owner's graveyard, and — no {T} in the cost — a Toad that
    entered this turn can do it (CR 302.6 is about {T} and {Q})."""
    (ability,) = _w1g5_compile(set_pool("PLS")["Morgue Toad"]).activated_abilities
    assert _w1g5_is_mana_ability(ability) and ability.cost.sacrifice_self

    game = _w1g5_creature_table(set_pool, hand=["Morgue Toad"], costs=False)
    assert game.cast_from_hand(0, "Morgue Toad").supported
    _w1g5_resolve_stack(game)
    assert _w1g5_activate(game, "Morgue Toad").supported

    assert _w1g5_mana(game) == {"U": 1, "R": 1}
    assert not game.stack and list(game.controlled_by(0)) == []
    assert [card.name for card in game.players[0].graveyard] == ["Morgue Toad"]


def test_w1g5_kavu_recluse_makes_a_lair_a_forest_for_the_turn(set_pool):
    """"{T}: Target land becomes a Forest until end of turn." CR 305.7: the
    Lair is a Forest and not a Lair, taps for {G} whatever it is asked for,
    and has lost the three-colour ability it prints — refused by name through
    the activation path. At cleanup it is a Lair again."""
    game = _w1g5_creature_table(
        set_pool, mine=["Kavu Recluse"], theirs=["Crosis's Catacombs"],
    )
    lair = _w1g5_one(game, 1, "Crosis's Catacombs")
    assert _w1g5_activate(
        game, "Kavu Recluse", target_permanent_ids=[lair.permanent_id]
    ).supported
    _w1g5_resolve_stack(game)

    assert lair.has_type("forest") and not lair.has_type("lair")
    assert lair.effective_produced_mana == ("G",)
    refused = game.activate_permanent_ability(
        1, "Crosis's Catacombs",
        permanent_index=game.battlefield_index_of(lair), mana_color="U",
    )
    assert not refused.supported and "305.7" in refused.details
    assert game.tap_land_for_mana(1, "Crosis's Catacombs", "U", permanent_id=lair.permanent_id)
    assert _w1g5_mana(game, 1) == {"G": 1}

    assert game.resolve_cleanup_step(0)
    assert lair.has_type("lair") and not lair.has_type("forest")
    assert set(lair.effective_produced_mana) == set("UBR")

    wrong = _w1g5_creature_table(
        set_pool, mine=["Kavu Recluse"], theirs=["Grizzly Bears"],
    )
    bears = _w1g5_one(wrong, 1, "Grizzly Bears")
    assert not _w1g5_activate(
        wrong, "Kavu Recluse", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert not _w1g5_one(wrong, 0, "Kavu Recluse").tapped, "nothing was paid"


def test_w1g5_sea_snidd_asks_for_a_basic_land_type_and_the_land_taps_for_it(set_pool):
    """"{T}: Target land becomes the basic land type of your choice until end
    of turn." The choice is made as the ability resolves (CR 608.2d) and the
    game waits on it; only a basic land type is an answer. The Mountain is a
    Swamp, taps for {B} whatever it is asked for — which casts a black spell a
    Mountain could not — and is a Mountain again after cleanup."""
    game = _w1g5_creature_table(
        set_pool, mine=["Sea Snidd", "Mountain"], hand=["Will-o'-the-Wisp"],
        interactive={0},
    )
    mountain = _w1g5_one(game, 0, "Mountain")
    assert _w1g5_activate(
        game, "Sea Snidd", target_permanent_ids=[mountain.permanent_id]
    ).supported
    game.resolve_top_of_stack()
    assert game.pending_choice_of("land_type_choice", 0) is not None
    assert game.waiting_prompt() is not None
    assert mountain.basic_land_types == ("mountain",), "not before the answer"

    assert not game.confirm_land_type(0, "lair")
    assert game.confirm_land_type(0, "swamp")
    assert mountain.basic_land_types == ("swamp",)
    assert game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert _w1g5_mana(game) == {"B": 1}
    assert game.cast_from_hand(0, "Will-o'-the-Wisp").supported
    _w1g5_resolve_stack(game)

    assert game.resolve_cleanup_step(0)
    assert mountain.basic_land_types == ("mountain",)
