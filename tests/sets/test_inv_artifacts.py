"""Invasion artifacts.

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


# --- W1G5: colour relations ---
from engine import Game as _W1G5ArtGame, PlayerState as _W1G5ArtPlayer
from engine.cost_modifiers import cost_modifiers_for as _w1g5_cost_modifiers_for
from engine.cost_modifiers import cost_reduction_for_cast as _w1g5_reduction_for_cast
from engine.models import Permanent as _W1G5ArtPermanent
from engine.oracle import compile_card_oracle as _w1g5_art_compile
from tests.helpers import resolve_stack as _w1g5_art_resolve_stack


def _w1g5_filter_table(set_pool, *, hand=(), enforce=False):
    """Urza's Filter on seat 0's battlefield, seat 0 in its main phase holding
    *hand*. Mana is enforced only where a test is about what is paid."""
    game = _W1G5ArtGame(players=[
        _W1G5ArtPlayer(
            name="P0", hand=list(hand),
            battlefield=[_W1G5ArtPermanent(card=set_pool("INV")["Urza's Filter"])],
            library=[set_pool("LEA")["Island"]] * 10,
        ),
        _W1G5ArtPlayer(name="P1", library=[set_pool("LEA")["Island"]] * 10),
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game  # W1G5 artifacts: the Filter's table


# --- Urza's Filter ---------------------------------------------------------
# "Multicolored spells cost {2} less to cast." A CR 601.2f reduction whose
# subject is a *count* of colours (CR 105.2b), printed where a colour goes.


def test_w1g5_urzas_filter_discounts_gold_spells_and_nothing_else(set_pool):
    """Two colours is the whole test: a gold spell is {2} cheaper, a
    monocoloured one and a colourless one are untouched — and a **red** spell
    in particular, because the sentence used to be read from the middle of the
    word ("multicolo-red spells cost {2} less") as a discount on those."""
    filter_card = set_pool("INV")["Urza's Filter"]
    assert _w1g5_art_compile(filter_card).supported
    (modifier,) = _w1g5_cost_modifiers_for(filter_card.oracle_text)
    assert modifier.colour == "multicolored" and modifier.reduces

    game = _w1g5_filter_table(set_pool)
    gold = set_pool("INV")["Shivan Zombie"]
    assert len(gold.colors) == 2

    discounted, names = _w1g5_reduction_for_cast(game, 0, gold)
    assert discounted.generic == 2 and names == ["Urza's Filter"]
    for plain in ("Lightning Bolt", "Grizzly Bears", "Mox Ruby", "Dark Ritual"):
        untouched, _ = _w1g5_reduction_for_cast(game, 0, set_pool("LEA")[plain])
        assert untouched.generic == 0, plain


def test_w1g5_urzas_filter_discounts_every_players_gold_spells(set_pool):
    """The sentence names no caster (CR 601.2f charges whoever is casting), so
    the opponent's gold spell is {2} cheaper too."""
    game = _w1g5_filter_table(set_pool)
    across, _ = _w1g5_reduction_for_cast(game, 1, set_pool("INV")["Shivan Zombie"])
    assert across.generic == 2


def test_w1g5_urzas_filter_is_what_lets_a_gold_spell_be_paid_for(set_pool):
    """Through a real cast with costs enforced. Shivan Zombie is {1}{B}{R};
    with exactly {B}{R} floating it is castable only because the Filter took
    the generic mana off (CR 118.7a: a generic reduction touches the generic
    part alone — the coloured pips are still owed). Dark Ritual's cousin, a
    monoblack {1}{B} creature, is refused on {B} alone."""
    pool = set_pool("INV")
    zombie = pool["Shivan Zombie"]
    mono = next(
        card for card in set_pool("LEA").values()
        if card.mana_cost == "{1}{B}" and "Creature" in card.type_line
    )
    game = _w1g5_filter_table(set_pool, hand=[zombie, mono], enforce=True)
    me = game.players[0]

    me.mana_pool["B"] = 1
    refused = game.cast_from_hand(0, mono.name)
    assert not refused.supported, refused.details
    assert me.mana_pool["B"] == 1

    me.mana_pool["R"] = 1
    cast = game.cast_from_hand(0, "Shivan Zombie")
    assert cast.supported, cast.details
    _w1g5_art_resolve_stack(game)
    assert any(p.card.name == "Shivan Zombie" for p in game.controlled_by(0))
    assert me.mana_pool["B"] == 0 and me.mana_pool["R"] == 0


def test_w1g5_urzas_filter_reads_the_spells_colours_not_its_printed_cost(set_pool):
    """CR 105.2b through the layers: under Celestial Dawn every nonland card
    its controller owns is white and nothing else, so their gold spell is
    monocoloured while they cast it — and across the table it is still gold."""
    game = _w1g5_filter_table(set_pool)
    game._put_permanent_onto_battlefield(
        0, _W1G5ArtPermanent(card=set_pool("MIR")["Celestial Dawn"]), None
    )
    zombie = set_pool("INV")["Shivan Zombie"]
    mine, _ = _w1g5_reduction_for_cast(game, 0, zombie)
    theirs, _ = _w1g5_reduction_for_cast(game, 1, zombie)
    assert mine.generic == 0 and theirs.generic == 2
