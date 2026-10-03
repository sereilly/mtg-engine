"""Prophecy enchantments.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: tokens, zones and triggers ---
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.tokens import make_token_card as _w1g6_make_token_card
from tests.helpers import _mk_card as _w1g6_mk_card, resolve_stack as _w1g6_resolve


def _w1g6_put(game, seat, card, *, token=False):
    perm = _W1G6Permanent(card=card)
    if token:
        perm.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm  # _w1g6_put


def _w1g6_table(p0=None, p1=None):
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", **(p0 or {})),
        _W1G6PlayerState(name="P1", **(p1 or {})),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    return game  # _w1g6_table


def _w1g6_land(name="Forest"):
    return _w1g6_mk_card(name, f"Basic Land — {name}")


def test_w1g6_overburden_bounces_a_land_of_the_creatures_controller(set_pool):
    """"Whenever a player puts a nontoken creature onto the battlefield, that
    player returns a land they control to its owner's hand." The seat whose
    creature entered returns one of *its* lands — the enchantment's controller
    keeps theirs — and a token entering asks nothing."""
    pcy = set_pool("PCY")
    bear = _w1g6_mk_card("Bear", "{1}{G}", "Creature — Bear", "")
    game = _w1g6_table(p1={"hand": [bear]})
    _w1g6_put(game, 0, pcy["Overburden"])
    mine = _w1g6_put(game, 0, _w1g6_land("Island"))
    theirs = [_w1g6_put(game, 1, _w1g6_land(n)) for n in ("Forest", "Mountain")]

    # A token entering is not a nontoken creature: nothing triggers.
    _w1g6_put(game, 1, _w1g6_make_token_card("Elf Token", 1, 1, "Creature — Elf"),
              token=True)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in game.players[1].hand] == ["Bear"]
    assert all(game.is_on_battlefield(p) for p in theirs)

    # The same entry path with a nontoken creature does trigger — for the
    # enchantment's own controller this time, who returns their own land.
    _w1g6_put(game, 0, _w1g6_mk_card("Wolf", "Creature — Wolf"))
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert not game.is_on_battlefield(mine)
    assert all(game.is_on_battlefield(p) for p in theirs)

    game.start_turn(1)
    game._close_current_priority_step()
    result = game.cast_from_hand(1, "Bear")
    assert result.supported, result.details
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)

    assert [c.name for c in game.players[1].hand] in (["Forest"], ["Mountain"])
    assert sum(game.is_on_battlefield(p) for p in theirs) == 1
    assert [c.name for c in game.players[0].hand] == ["Island"]


def _w1g6_harvest_upkeep(set_pool, graveyard):
    pcy = set_pool("PCY")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", graveyard=list(graveyard)),
        _W1G6PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    _w1g6_put(game, 0, pcy["Forgotten Harvest"])
    mine = _w1g6_put(game, 0, _w1g6_mk_card("Wolf", "Creature — Wolf"))
    theirs = _w1g6_put(game, 1, _w1g6_mk_card("Bear", "Creature — Bear"))
    game.start_turn(0)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    return game, mine, theirs  # _w1g6_harvest_upkeep


def test_w1g6_forgotten_harvest_trades_a_land_card_for_a_counter(set_pool):
    """"At the beginning of your upkeep, you may exile a land card from your
    graveyard. If you do, put a +1/+1 counter on target creature." The land
    card — not the creature card beside it — is the one exiled."""
    game, mine, theirs = _w1g6_harvest_upkeep(
        set_pool, [_w1g6_land("Forest"), _w1g6_mk_card("Elk", "Creature — Elk")]
    )
    assert [c.name for c in game.players[0].exile] == ["Forest"]
    assert [c.name for c in game.players[0].graveyard] == ["Elk"]
    assert (mine.effective_power, mine.effective_toughness) == (3, 3)
    assert theirs.effective_power == 2


def _w1g6_spell(name, mana_cost, cmc):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=float(cmc), type_line="Sorcery",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Sorcery"},
    )


def test_w1g6_infernal_genesis_mints_minions_for_the_milled_mana_value(set_pool):
    """"At the beginning of each player's upkeep, that player mills a card.
    Then they create X 1/1 black Minion creature tokens, where X is the milled
    card's mana value." On the opponent's upkeep the opponent mills and gets
    the tokens; on the controller's own, a milled land makes none."""
    game = _w1g6_table(
        p0={"library": [_w1g6_land("Swamp"), _w1g6_land("Swamp")]},
        p1={"library": [_w1g6_spell("Big Spell", "{3}{B}", 4), _w1g6_land("Island")]},
    )
    _w1g6_put(game, 0, set_pool("PCY")["Infernal Genesis"])

    game.start_turn(1)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert [c.name for c in game.players[1].graveyard] == ["Big Spell"]
    minions = [p for p in game.controlled_by(1) if p.card.name == "Minion Token"]
    assert len(minions) == 4
    assert all(p.metadata.get("is_token") for p in minions)
    assert (minions[0].effective_power, minions[0].effective_toughness) == (1, 1)
    assert not [p for p in game.controlled_by(0) if p.card.name == "Minion Token"]

    game.start_turn(0)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert [c.name for c in game.players[0].graveyard] == ["Swamp"]
    assert not [p for p in game.controlled_by(0) if p.card.name == "Minion Token"]
    assert len([p for p in game.controlled_by(1) if p.card.name == "Minion Token"]) == 4


def test_w1g6_forgotten_harvest_with_no_land_card_offers_nothing(set_pool):
    """No land card is no offer, so the if-you-do counter never lands."""
    game, mine, theirs = _w1g6_harvest_upkeep(
        set_pool, [_w1g6_mk_card("Elk", "Creature — Elk")]
    )
    assert not game.players[0].exile
    assert [c.name for c in game.players[0].graveyard] == ["Elk"]
    assert mine.effective_power == 2 and theirs.effective_power == 2
