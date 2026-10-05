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


# --- W1G2: split cards ---
from engine import Game as _W1G2Game
from engine.faces import face_cards as _w1g2_face_cards
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState
from engine.oracle import compile_card_oracle as _w1g2_compile
from engine.targeting import derive_cast_spec as _w1g2_cast_spec

from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_instant_duel(set_pool):
    """Two seats that **pay** for what they cast (CR 601.2h): a split card's
    whole point is that its halves cost different mana, and a rig with costs
    off cannot tell Stand's {W} from Deliver's {2}{U}."""
    filler = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="P0", library=[filler] * 10),
        _W1G2PlayerState(name="P1", library=[filler] * 10),
    ])
    game.enforce_mana_costs = True
    w1g2_seats = (game, game.players[0], game.players[1])
    return w1g2_seats


def _w1g2_instant_permanent(game, set_pool, seat, name, code="LEA"):
    w1g2_entered = _W1G2Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, w1g2_entered, None)
    return w1g2_entered


def test_w1g2_the_three_instant_split_cards_compile_one_spell_per_half(set_pool):
    """Each half is its own spell with its own picker (CR 709.3a): the kinds
    and specs below are what the client is offered once a half is chosen, and
    the whole card offers neither — only the choice between them."""
    expected = {
        "Stand // Deliver": [("Stand", "{W}", {"kind": "creature"}),
                             ("Deliver", "{2}{U}", {"kind": "permanent"})],
        "Spite // Malice": [
            ("Spite", "{3}{U}", {"kind": "stack", "stack_excluded_types": ["creature"]}),
            ("Malice", "{3}{B}", {"kind": "creature", "filter": {"exclude_colors": ["B"]}}),
        ],
        "Wax // Wane": [
            ("Wax", "{G}", {"kind": "creature"}),
            ("Wane", "{W}", {"kind": "permanent", "filter": {"type_filter": "enchantment"}}),
        ],
    }
    for name, halves in expected.items():
        card = set_pool("INV")[name]
        assert _w1g2_compile(card).supported
        assert _w1g2_compile(card).instructions == (), "the whole card is no spell"
        found = [
            (half.name, half.mana_cost, _w1g2_cast_spec(half, _w1g2_compile(half)))
            for half in _w1g2_face_cards(card)
        ]
        assert found == halves, name
        assert all(half.type_line == "Instant" for half in _w1g2_face_cards(card))


def test_w1g2_stand_prevents_the_next_two_damage_to_the_creature_it_targets(set_pool):
    """`Prevent the next 2 damage that would be dealt to target creature this
    turn.` For {W}: a Lightning Bolt at a 2/2 deals 1 and the Bears live."""
    game, p0, p1 = _w1g2_instant_duel(set_pool)
    bears = _w1g2_instant_permanent(game, set_pool, 0, "Grizzly Bears")
    p0.hand.append(set_pool("INV")["Stand // Deliver"])
    p1.hand.append(set_pool("LEA")["Lightning Bolt"])
    p0.mana_pool["W"] = 1
    p1.mana_pool["R"] = 1

    cast = game.cast_from_hand(0, "Stand", target_permanent_ids=[bears.permanent_id])
    assert cast.supported, cast.details
    assert p0.mana_pool["W"] == 0
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported

    assert game.is_on_battlefield(bears), "2 of the 3 were prevented"
    assert "Prevented 2 damage to Grizzly Bears" in game.log
    assert [card.name for card in p0.graveyard] == ["Stand // Deliver"]


def test_w1g2_deliver_returns_any_permanent_to_its_owners_hand(set_pool):
    """`Return target permanent to its owner's hand.` A **permanent**, not a
    creature: an opponent's land and an opponent's artifact both go back, each
    for {2}{U}, and the blue pool is what is charged."""
    game, p0, p1 = _w1g2_instant_duel(set_pool)
    land = _w1g2_instant_permanent(game, set_pool, 1, "Forest")
    ring = _w1g2_instant_permanent(game, set_pool, 1, "Sol Ring")
    split = set_pool("INV")["Stand // Deliver"]
    p0.hand.extend([split, split])
    p0.mana_pool["U"] = 6

    assert game.cast_from_hand(0, "Deliver", target_permanent_ids=[land.permanent_id]).supported
    assert game.cast_from_hand(0, "Deliver", target_permanent_ids=[ring.permanent_id]).supported

    assert sorted(card.name for card in p1.hand) == ["Forest", "Sol Ring"]
    assert list(game.controlled_by(1)) == []
    assert p0.mana_pool["U"] == 0 and p0.hand == []
    assert p0.graveyard == [split, split]


def test_w1g2_stand_and_deliver_are_paid_for_in_their_own_colours(set_pool):
    """CR 709.3a: only the chosen half is evaluated. A single white mana casts
    Stand and cannot cast Deliver; nothing leaves the hand on the refusal."""
    game, p0, _p1 = _w1g2_instant_duel(set_pool)
    bears = _w1g2_instant_permanent(game, set_pool, 0, "Grizzly Bears")
    split = set_pool("INV")["Stand // Deliver"]
    p0.hand.append(split)
    p0.mana_pool["W"] = 1

    refused = game.cast_from_hand(0, "Deliver", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and "insufficient mana" in refused.details
    assert p0.hand == [split] and p0.mana_pool["W"] == 1
    whole = game.cast_from_hand(0, "Stand // Deliver", target_permanent_ids=[bears.permanent_id])
    assert not whole.supported and "Stand or Deliver" in whole.details
    assert game.cast_from_hand(0, "Stand", target_permanent_ids=[bears.permanent_id]).supported


def test_w1g2_spite_counters_a_noncreature_spell_and_cannot_be_aimed_at_a_creature_spell(set_pool):
    """`Counter target noncreature spell.` The narrowing is enforced at the
    **announcement** (CR 601.2c): aimed at a creature spell Spite is refused
    with nothing spent, where it used to be cast, paid for and then declined
    by its own handler."""
    game, p0, p1 = _w1g2_instant_duel(set_pool)
    split = set_pool("INV")["Spite // Malice"]
    p0.hand.extend([set_pool("LEA")["Grizzly Bears"], set_pool("LEA")["Lightning Bolt"]])
    p1.hand.append(split)
    p0.mana_pool["G"] = 2
    p1.mana_pool["U"] = 4

    assert game.queue_from_hand(0, "Grizzly Bears").supported
    refused = game.queue_from_hand(1, "Spite", target_stack_index=0)
    assert not refused.supported, "a creature spell is not a legal target"
    assert p1.hand == [split] and p1.mana_pool["U"] == 4

    p0.mana_pool["R"] = 1
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.queue_from_hand(1, "Spite", target_stack_index=1).supported
    spite = game.stack[-1]
    assert (spite.card.name, tuple(game._stack_item_colors(spite))) == ("Spite", ("U",))
    _w1g2_resolve_stack(game)

    assert p1.life == 20, "the Bolt was countered"
    assert [card.name for card in p0.graveyard] == ["Lightning Bolt"]
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Grizzly Bears"]
    assert p1.graveyard == [split] and p1.mana_pool["U"] == 0


def test_w1g2_malice_destroys_a_nonblack_creature_past_its_regeneration(set_pool):
    """`Destroy target nonblack creature. It can't be regenerated.` Both riders:
    a black creature is no target at all, and a regeneration shield on the
    creature it does destroy is not spent saving it."""
    game, p0, p1 = _w1g2_instant_duel(set_pool)
    knight = _w1g2_instant_permanent(game, set_pool, 1, "Black Knight")
    bears = _w1g2_instant_permanent(game, set_pool, 1, "Grizzly Bears")
    bears.regeneration_shield = 1
    split = set_pool("INV")["Spite // Malice"]
    p0.hand.append(split)
    p0.mana_pool["B"] = 4

    refused = game.cast_from_hand(0, "Malice", target_permanent_ids=[knight.permanent_id])
    assert not refused.supported and p0.mana_pool["B"] == 4

    assert game.cast_from_hand(0, "Malice", target_permanent_ids=[bears.permanent_id]).supported
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Black Knight"]
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]
    assert p0.graveyard == [split]


def test_w1g2_wax_pumps_until_end_of_turn(set_pool):
    """`Target creature gets +2/+2 until end of turn.` — and it ends."""
    game, p0, _p1 = _w1g2_instant_duel(set_pool)
    bears = _w1g2_instant_permanent(game, set_pool, 0, "Grizzly Bears")
    p0.hand.append(set_pool("INV")["Wax // Wane"])
    p0.mana_pool["G"] = 1

    assert game.cast_from_hand(0, "Wax", target_permanent_ids=[bears.permanent_id]).supported
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)

    game.resolve_cleanup_step(0)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g2_wane_destroys_an_enchantment_and_nothing_else(set_pool):
    """`Destroy target enchantment.` A creature is refused with the {W} unspent;
    the enchantment goes to its owner's graveyard."""
    game, p0, p1 = _w1g2_instant_duel(set_pool)
    bears = _w1g2_instant_permanent(game, set_pool, 1, "Grizzly Bears")
    crusade = _w1g2_instant_permanent(game, set_pool, 1, "Crusade")
    split = set_pool("INV")["Wax // Wane"]
    p0.hand.append(split)
    p0.mana_pool["W"] = 1

    refused = game.cast_from_hand(0, "Wane", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and p0.mana_pool["W"] == 1 and p0.hand == [split]

    assert game.cast_from_hand(0, "Wane", target_permanent_ids=[crusade.permanent_id]).supported
    assert [card.name for card in p1.graveyard] == ["Crusade"]
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Grizzly Bears"]
    w1g2_whole_card_in_graveyard = p0.graveyard == [split]
    assert w1g2_whole_card_in_graveyard
