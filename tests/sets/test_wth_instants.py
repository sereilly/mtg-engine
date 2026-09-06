"""Weatherlight instants.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G1: the top of a graveyard as a cost ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str, colors: tuple = ()) -> CardDefinition:
    """A vanilla card to stack a graveyard with. The colour is what Spinning
    Darkness's cost scans for, so it is the one characteristic that varies."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=tuple(colors), color_identity=tuple(colors), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2",
             "toughness": "2", "colors": list(colors)},
    )


def _w1g1_darkness(set_pool, graveyard):
    """Spinning Darkness in hand with *graveyard* behind it and a creature to
    aim at. The graveyard is bottom-first (CR 404.1: an arriving card goes on
    top, so the last element is the top card)."""
    victim = Permanent(card=_w1g1_card("Victim", "Creature — Bear"))
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Spinning Darkness"]],
                    graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", battlefield=[victim],
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.start_turn(0)
    return game, victim


def test_spinning_darkness_is_cast_for_three_black_cards_and_no_mana(set_pool):
    """"You may exile the top three black cards of your graveyard rather than
    pay this spell's mana cost." (CR 118.9.)

    The mana is *never* paid — the game has no lands at all here — and the
    three cards come off the top of the pile, skipping the white card that
    happens to be above one of them. CR 118.9c leaves the printed {4}{B}{B}
    untouched; what is skipped is the payment.
    """
    game, victim = _w1g1_darkness(set_pool, [
        _w1g1_card("Black Deep", "Creature — Zombie", ("B",)),
        _w1g1_card("White Card", "Creature — Bear", ("W",)),
        _w1g1_card("Black Mid", "Creature — Zombie", ("B",)),
        _w1g1_card("Black Top", "Creature — Zombie", ("B",)),
    ])
    me = game.players[0]
    result = game.cast_from_hand(
        0, "Spinning Darkness", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert sorted(card.name for card in me.exile) == [
        "Black Deep", "Black Mid", "Black Top"
    ]
    # The spell itself lands in the graveyard on resolution (CR 608.2m), so
    # the pile is read for what the *cost* left behind.
    assert [
        card.name for card in me.graveyard if card.name != "Spinning Darkness"
    ] == ["White Card"]
    if game.stack:
        game.resolve_top_of_stack()
    assert victim.damage_marked == 3
    assert me.life == 23


def test_spinning_darkness_refuses_a_pile_that_cannot_pay_in_full(set_pool):
    """CR 118.3: a cost is paid in full or not at all, and CR 601.2h then makes
    an unpayable alternative cost an *uncastable* spell — never one cast for
    nothing, which is what a partial charge would be once the mana payment has
    already been replaced."""
    game, _victim = _w1g1_darkness(set_pool, [
        _w1g1_card("Black One", "Creature — Zombie", ("B",)),
        _w1g1_card("Black Two", "Creature — Zombie", ("B",)),
    ])
    me = game.players[0]
    result = game.cast_from_hand(
        0, "Spinning Darkness", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )
    assert not result.supported
    assert len(me.graveyard) == 2, "the two black cards are still there"
    assert me.exile == []
    assert [card.name for card in me.hand] == ["Spinning Darkness"]


# --- W2G1: costs charged and permissions granted ---
from engine import Game, PlayerState
from engine.cast_costs import additional_cost_for_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w2g1_duel(hand=()):
    p1, p2 = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2


def test_abjure_charges_the_blue_permanent_it_names(set_pool, catalog_by_name):
    """"As an additional cost to cast this spell, sacrifice a blue permanent."

    The cost table refused the phrase because it pinned no card *type*, and a
    refused cost line is a refused card (`cast_costs.unread_cost_sentence`) —
    which is the right direction, since the alternative is a counterspell cast
    for {U} and nothing else. "A blue permanent" names what may pay it exactly
    as precisely as "a creature" does; what it names is a colour.
    """
    pool = set_pool("WTH")
    cost = additional_cost_for_line(
        "As an additional cost to cast this spell, sacrifice a blue permanent."
    )
    assert cost is not None
    assert cost.sacrifice_filter == {"color_filter": "U"}
    assert compile_card_oracle(pool["Abjure"]).supported

    game, caster, victim = _w2g1_duel([pool["Abjure"]])
    blue = Permanent(card=catalog_by_name["Vodalian Soldiers"])
    caster.battlefield.append(blue)
    victim.hand = [catalog_by_name["Lightning Bolt"]]
    victim.library = [catalog_by_name["Island"]] * 4

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    result = game.queue_from_hand(0, "Abjure", target_stack_index=0)
    game.resolve_stack()

    assert result.supported, result.details
    assert caster.battlefield == [], "the blue permanent paid for it"
    assert "Vodalian Soldiers" in [c.name for c in caster.graveyard]
    assert caster.life == 20, "and the bolt was countered"


def test_abjure_is_not_cast_with_no_blue_permanent_to_sacrifice(
    set_pool, catalog_by_name
):
    """CR 601.2h: an unpayable cost can't be paid, and casting rewinds. A green
    creature is not a legal payment, which is the whole of what the colour
    narrowing buys — dropped, this would eat the nearest thing on the board."""
    pool = set_pool("WTH")
    game, caster, victim = _w2g1_duel([pool["Abjure"]])
    green = Permanent(card=catalog_by_name["Grizzly Bears"])
    caster.battlefield.append(green)
    victim.hand = [catalog_by_name["Lightning Bolt"]]

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    result = game.queue_from_hand(0, "Abjure", target_stack_index=0)

    assert not result.supported
    assert [c.name for c in caster.hand] == ["Abjure"], "still in hand"
    assert [p.card.name for p in caster.battlefield] == ["Grizzly Bears"]
    assert len(game.stack) == 1, "and the bolt is still on the stack"
