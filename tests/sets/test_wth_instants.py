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


# --- W2G2: damage divided, doubled and prevented ---
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle as _w2g2_compile


def _w2g2_vanilla(name: str, power: int, toughness: int):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature — Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g2_game(p1_hand=(), p2_board=()):
    game = Game(players=[
        PlayerState(name="P1", hand=list(p1_hand)),
        PlayerState(name="P2", battlefield=list(p2_board)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def test_firestorm_deals_the_announced_x_to_each_of_x_targets(set_pool):
    """"As an additional cost to cast this spell, discard X cards. Firestorm
    deals X damage to each of X targets."

    One announcement doing three jobs (CR 107.3a): it prices the discard, it
    sizes the damage, and it fixes the number of targets. The check that matters
    is the *third* — the amounts have to land on the right recipients, and this
    is the shape (a cross-seat list) where an engine that only understood one
    target puts the whole spell on one face.
    """
    wth = set_pool("WTH")
    victim = Permanent(card=_w2g2_vanilla("Bear", 2, 2))
    game = _w2g2_game(
        p1_hand=[wth["Firestorm"], *[_w2g2_vanilla("Filler", 1, 1)] * 3],
        p2_board=[victim],
    )

    result = game.queue_from_hand(
        0, "Firestorm", x_value=2, divided_targets=[(1, 0), (1, None)],
    )
    assert result.supported, result.details
    assert len(game.players[0].hand) == 1, "two cards paid the additional cost"
    game.resolve_stack()

    assert victim.damage_marked == 2
    assert game.players[1].life == 18, "the face took its own 2, not the whole 4"


def test_firestorm_refuses_a_target_list_that_is_not_x_long(set_pool):
    """CR 601.2c fixes the number of targets as the spell is announced, and
    Firestorm's number is the X just announced. A shorter list is an illegal
    proposal, so CR 601.2e returns the game to before it — nothing discarded.
    """
    wth = set_pool("WTH")
    game = _w2g2_game(
        p1_hand=[wth["Firestorm"], *[_w2g2_vanilla("Filler", 1, 1)] * 3],
        p2_board=[Permanent(card=_w2g2_vanilla("Bear", 2, 2))],
    )

    result = game.queue_from_hand(
        0, "Firestorm", x_value=2, divided_targets=[(1, 0)],
    )
    assert not result.supported
    assert "exactly 2 targets" in result.details
    assert len(game.players[0].hand) == 4, "the refusal cost the caster nothing"


def test_firestorm_cannot_announce_an_x_the_hand_cannot_discard(set_pool):
    """CR 601.2h: an unpayable cost can't be paid, and the consequence is that
    the spell isn't cast — never that it is cast for less. The spell itself is
    on the stack before its costs are paid (CR 601.2a), so it is not one of the
    cards that can pay for itself.
    """
    wth = set_pool("WTH")
    game = _w2g2_game(
        p1_hand=[wth["Firestorm"], _w2g2_vanilla("Filler", 1, 1)],
        p2_board=[Permanent(card=_w2g2_vanilla("Bear", 2, 2))],
    )

    result = game.queue_from_hand(
        0, "Firestorm", x_value=2, divided_targets=[(1, 0), (1, None)],
    )
    assert not result.supported
    assert "additional cost" in result.details


def test_fatal_blow_only_reaches_a_creature_damaged_this_turn(set_pool):
    """"Destroy target creature that was dealt damage this turn."

    The simple past of Giant Shark's "has been dealt damage this turn", and the
    same record answers both — which is the whole point of the branch sharing a
    field rather than earning one.
    """
    wth = set_pool("WTH")
    program = _w2g2_compile(wth["Fatal Blow"])
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.payload["dealt_damage_this_turn"] is True
    assert instruction.payload["bypass_regeneration"] is True, (
        "the second sentence is still read"
    )

    untouched = Permanent(card=_w2g2_vanilla("Bear", 2, 2))
    game = _w2g2_game(p1_hand=[wth["Fatal Blow"]], p2_board=[untouched])
    assert not game.cast_target_spec(0, wth["Fatal Blow"])["valid_targets"], (
        "an undamaged creature is not a legal target"
    )

    untouched.metadata["was_dealt_damage_this_turn"] = True
    assert game.cast_target_spec(0, wth["Fatal Blow"])["valid_targets"]


def test_choking_vines_blocks_the_creatures_it_names_and_damages_those(set_pool):
    """"X target attacking creatures become blocked. Choking Vines deals 1
    damage to each of those creatures."

    The second sentence names what the first one chose (CR 611.2c fixed the set
    when the effect began), so the attacker nobody named is untouched — which a
    board read of "every blocked attacker" could not have got right.
    """
    wth = set_pool("WTH")
    named = [Permanent(card=_w2g2_vanilla("Bear", 2, 2)) for _ in range(2)]
    spare = Permanent(card=_w2g2_vanilla("Ox", 3, 3))
    for perm in (*named, spare):
        perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[*named, spare]),
        PlayerState(name="P2", hand=[wth["Choking Vines"]]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    game.declare_attackers(0, [0, 1, 2])
    game.advance_combat_phase()   # declare blockers

    result = game.queue_from_hand(
        1, "Choking Vines", x_value=2,
        target_player_index=0, target_permanent_index=[0, 1],
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert [perm.blocked for perm in named] == [True, True]
    assert [perm.damage_marked for perm in named] == [1, 1]
    assert not spare.blocked and spare.damage_marked == 0
