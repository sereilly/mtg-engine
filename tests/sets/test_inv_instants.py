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


# --- W1G6: colour choices ---
# Sway of Illusion: "Any number of target creatures become the color of your
# choice until end of turn. / Draw a card." It arrived supported with no
# target description at all, so the picker offered nothing and the resolution
# recoloured whatever one creature it happened on.
from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from engine.targeting import derive_cast_spec as _w1g6_cast_spec


def _w1g6_sway_table(set_pool, mine, theirs):
    lea = set_pool("LEA")
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = False
    w1g6_game.interactive_seats = {0}
    w1g6_sides = []
    for seat, names in ((0, mine), (1, theirs)):
        side = []
        for name in names:
            perm = _W1G6Permanent(card=lea[name])
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            side.append(perm)
        w1g6_sides.append(side)
    w1g6_game.players[0].hand.append(set_pool("INV")["Sway of Illusion"])
    w1g6_game.players[0].library.extend([lea["Forest"]] * 3)
    return w1g6_game, w1g6_sides[0], w1g6_sides[1]  # _w1g6_sway_table


def _w1g6_resolve_sway(game, colour):
    """Resolve the spell, answering its colour; report whether it was asked."""
    w1g6_asked = False
    for _ in range(6):
        if game.pending_choices:
            assert [(c.kind, c.player_index) for c in game.pending_choices] == [
                ("color_choice", 0)
            ]
            assert game.confirm_color_choice(0, colour)
            w1g6_asked = True
        elif game.stack:
            game.resolve_top_of_stack()
    return w1g6_asked  # _w1g6_resolve_sway


def test_w1g6_sway_of_illusion_offers_any_number_of_creature_targets(set_pool):
    """The picker is derived from the compiled program: creatures, as many as
    the caster likes, each at most once (CR 601.2c)."""
    card = set_pool("INV")["Sway of Illusion"]
    spec = _w1g6_cast_spec(card, _w1g6_compile(card))

    assert spec == {"kind": "creature", "unbounded_targets": True, "distinct_targets": True}


def test_w1g6_sway_of_illusion_recolours_exactly_the_chosen_creatures(set_pool):
    """Two of four creatures are targeted, one on each side; blue is named as
    the spell resolves — after the targets, not with them. Those two are blue
    until cleanup, the other two keep their colours, and the card is drawn."""
    game, mine, theirs = _w1g6_sway_table(
        set_pool, ["Grizzly Bears", "Hill Giant"], ["Llanowar Elves", "Black Knight"],
    )
    bears, giant = mine
    elves, knight = theirs

    assert game.queue_from_hand(
        0, "Sway of Illusion", new_color="R",
        target_permanent_ids=[bears.permanent_id, knight.permanent_id],
    ).supported
    assert _w1g6_resolve_sway(game, "U")

    colours = {
        perm.card.name: sorted(game._effective_colors(perm))
        for perm in (bears, giant, elves, knight)
    }
    assert colours == {
        "Grizzly Bears": ["U"], "Hill Giant": ["R"],
        "Llanowar Elves": ["G"], "Black Knight": ["U"],
    }
    assert [card.name for card in game.players[0].hand] == ["Forest"]

    game.resolve_cleanup_step(0)
    assert sorted(game._effective_colors(bears)) == ["G"]
    assert sorted(game._effective_colors(knight)) == ["B"]


def test_w1g6_sway_of_illusion_with_no_targets_still_draws(set_pool):
    """"Any number" includes none (CR 601.2c): nothing is recoloured — in
    particular not the one creature on the table — and the card is drawn."""
    game, mine, _theirs = _w1g6_sway_table(set_pool, ["Grizzly Bears"], [])

    assert game.queue_from_hand(0, "Sway of Illusion").supported
    _w1g6_resolve_sway(game, "U")

    assert sorted(game._effective_colors(mine[0])) == ["G"]
    assert [card.name for card in game.players[0].hand] == ["Forest"]


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


# --- W1G5: colour relations ---
from engine import Game as _W1G5IGame, PlayerState as _W1G5IPlayer
from engine.models import CardDefinition as _W1G5ICard, Permanent as _W1G5IPermanent
from engine.oracle import compile_card_oracle as _w1g5i_compile
from tests.helpers import _damage_dealt as _w1g5i_damage_dealt
from tests.helpers import resolve_stack as _w1g5i_resolve_stack


def _w1g5_attacker(name, power, colors):
    """A vanilla creature of the given colours, for a shield to be aimed at."""
    return _W1G5ICard(
        name=name, mana_cost="".join("{%s}" % symbol for symbol in colors) or "{3}",
        cmc=3.0, type_line="Creature - Test", oracle_text="", colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(power)},
    )  # W1G5 instants: a source of damage


def _w1g5_ministration_table(set_pool, theirs):
    """Seat 1's turn, seat 0 holding Samite Ministration; *theirs* on seat 1's
    battlefield and unsick."""
    board = [_W1G5IPermanent(card=card) for card in theirs]
    filler = _w1g5_attacker("Filler", 1, ())
    game = _W1G5IGame(players=[
        _W1G5IPlayer(name="P0", hand=[set_pool("INV")["Samite Ministration"]],
                     library=[filler] * 10),
        _W1G5IPlayer(name="P1", battlefield=board, library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(1)
    game._close_current_priority_step()
    return game, board  # W1G5 instants: the Ministration's table


def _w1g5_minister(game, source=None):
    """Cast Samite Ministration naming *source* (or no source at all)."""
    aimed = {} if source is None else {
        "target_player_index": game.controller_index_of(source),
        "target_permanent_index": game.battlefield_index_of(source),
    }
    result = game.cast_from_hand(0, "Samite Ministration", **aimed)
    assert result.supported, result.details
    _w1g5i_resolve_stack(game)  # W1G5: the Ministration has resolved


# --- Samite Ministration ---------------------------------------------------
# "Prevent all damage that would be dealt to you this turn by a source of your
# choice. Whenever damage from a black or red source is prevented this way this
# turn, you gain that much life."


def test_w1g5_samite_ministration_stops_every_hit_from_the_chosen_red_source(set_pool):
    """The red Giant is named: its first hit, its second hit and its combat
    damage are all prevented — "all", where the one-shot shields stop at the
    first — and each prevention pays that much life, because the source is red
    (CR 615.5). Another source's damage is untouched."""
    card = set_pool("INV")["Samite Ministration"]
    program = _w1g5i_compile(card)
    assert program.supported
    from engine.targeting import derive_cast_spec

    assert derive_cast_spec(card, program)["source_of_choice"] is True

    game, (giant, bears) = _w1g5_ministration_table(
        set_pool, [_w1g5_attacker("Giant", 3, ("R",)), _w1g5_attacker("Bears", 2, ("G",))]
    )
    me = game.players[0]
    _w1g5_minister(game, giant)

    game._deal_damage_to_player(me, 3, source=giant)
    assert me.life == 23
    game._deal_damage_to_player(me, 2, source=giant)
    assert me.life == 25
    game._deal_damage_to_player(me, 2, source=bears)
    assert me.life == 23
    assert _w1g5i_damage_dealt(game, me, 3, source=giant, combat=True) == 0


def test_w1g5_samite_ministration_through_a_real_attack(set_pool):
    """The whole card in one combat: the named black 4/4 attacks unblocked, the
    damage is prevented in the combat damage step and its four points come
    back as life."""
    game, (specter,) = _w1g5_ministration_table(
        set_pool, [_w1g5_attacker("Specter", 4, ("B",))]
    )
    _w1g5_minister(game, specter)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {})[0]
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5i_resolve_stack(game)
    assert game.players[0].life == 24


def test_w1g5_samite_ministration_prevents_but_does_not_pay_for_other_colours(set_pool):
    """The rider is conditional and the prevention is not: a green source's
    damage is prevented just the same, and no life is gained. A gold
    black-green source pays — it is a black source (CR 105.2b)."""
    game, (bears,) = _w1g5_ministration_table(set_pool, [_w1g5_attacker("Bears", 2, ("G",))])
    me = game.players[0]
    _w1g5_minister(game, bears)
    game._deal_damage_to_player(me, 2, source=bears)
    assert me.life == 20

    game, (rot,) = _w1g5_ministration_table(set_pool, [_w1g5_attacker("Rot", 2, ("B", "G"))])
    me = game.players[0]
    _w1g5_minister(game, rot)
    game._deal_damage_to_player(me, 2, source=rot)
    assert me.life == 22


def test_w1g5_samite_ministration_protects_only_its_caster_and_only_this_turn(set_pool):
    """"To you": the caster's own creature is not shielded from the named
    source, and neither is the opponent. "This turn": the cleanup step ends
    it."""
    game, (giant,) = _w1g5_ministration_table(set_pool, [_w1g5_attacker("Giant", 3, ("R",))])
    me = game.players[0]
    mine = _W1G5IPermanent(card=_w1g5_attacker("Squire", 5, ("W",)))
    game._put_permanent_onto_battlefield(0, mine, None)
    _w1g5_minister(game, giant)

    assert _w1g5i_damage_dealt(game, mine, 3, source=giant) == 3
    assert _w1g5i_damage_dealt(game, game.players[1], 3, source=giant) == 3
    assert _w1g5i_damage_dealt(game, me, 3, source=giant) == 0
    game.resolve_cleanup_step(1)
    assert _w1g5i_damage_dealt(game, me, 3, source=giant) == 3


def test_w1g5_samite_ministration_with_no_source_named_chooses_one(set_pool):
    """A shield that lasts all turn has no sourceless form: left unnamed it
    would be "prevent all damage dealt to you this turn". So a seat that names
    nothing takes the stated default — the opponent's biggest creature — and
    every other source still deals its damage."""
    game, (giant, bears) = _w1g5_ministration_table(
        set_pool, [_w1g5_attacker("Giant", 3, ("R",)), _w1g5_attacker("Bears", 2, ("G",))]
    )
    me = game.players[0]
    _w1g5_minister(game)

    assert _w1g5i_damage_dealt(game, me, 3, source=giant) == 0
    assert _w1g5i_damage_dealt(game, me, 2, source=bears) == 2
    assert _w1g5i_damage_dealt(game, me, 5) == 5


def test_w1g5_samite_ministration_with_nothing_to_choose_does_nothing(set_pool):
    """No source on the table at all: the spell resolves, arms nothing and says
    so (CR 609.7a) — and a later, unrelated damage event is dealt in full."""
    game, _board = _w1g5_ministration_table(set_pool, [])
    me = game.players[0]
    _w1g5_minister(game)
    assert any("no source of damage to choose" in line for line in game.log)
    assert _w1g5i_damage_dealt(game, me, 4) == 4


def test_w1g5_the_blanket_and_the_one_shot_keep_their_own_rider_spelling():
    """"Whenever … this turn" belongs to the shield that lasts the turn and
    "if …" to the one-shot. Each printed on the other's shield refuses, so the
    two sentences cannot drift into arming each other's interceptor."""
    from engine.grammar import compile_line

    blanket = (
        "Prevent all damage that would be dealt to you this turn by a source "
        "of your choice."
    )
    one_shot = (
        "The next time a source of your choice would deal damage to you and/or "
        "creatures you control this turn, prevent that damage."
    )
    whenever = (
        " Whenever damage from a black source is prevented this way this turn, "
        "you gain that much life."
    )
    if_once = " If damage from a black source is prevented this way, you gain that much life."

    assert compile_line(blanket + whenever).usable
    assert compile_line(one_shot + if_once).usable
    assert not compile_line(blanket + if_once).usable
    assert not compile_line(one_shot + whenever).usable
    # …and neither narrowing the blanket does not carry is dropped
    assert not compile_line(blanket.replace("all damage", "all combat damage")).usable
    assert not compile_line(blanket.replace("to you", "to target creature")).usable


def test_w1g5_samite_ministration_answers_a_burn_spell_on_the_stack(set_pool):
    """Cast in response, which is how the card is played: the opponent's
    Lightning Bolt is on the stack, the Ministration goes on top naming no
    source, and the stated default is that spell — the topmost one an opponent
    controls (CR 609.7a lets the choice be a spell on the stack). The Bolt then
    resolves into the shield: three prevented, three gained, because it is
    red."""
    bolt = set_pool("LEA")["Lightning Bolt"]
    game, (bears,) = _w1g5_ministration_table(set_pool, [_w1g5_attacker("Bears", 2, ("G",))])
    me = game.players[0]
    game.players[1].hand.append(bolt)

    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(0, "Samite Ministration").supported
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Samite Ministration",
    ]
    _w1g5i_resolve_stack(game)

    assert me.life == 23
    assert any(
        "prevent all damage Lightning Bolt would deal them this turn" in line
        for line in game.log
    )
    # the creature it did not choose still connects
    assert _w1g5i_damage_dealt(game, me, 2, source=bears) == 2


# --- W1G3: domain ---
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_cast_spec as _w1g3_cast_spec
from tests.helpers import resolve_stack as _w1g3_resolve

_W1G3_LIBRARY = [
    "Grizzly Bears", "Craw Wurm", "Lightning Bolt", "Giant Growth",
    "Counterspell", "Dark Ritual",
]


def _w1g3_counsel(set_pool, lands, *, interactive=True):
    """Worldly Counsel cast by seat 0 over a six-card library of known order,
    with *lands* on its side. Stops with the look's prompt owed."""
    w1g3_lea = set_pool("LEA")
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(
            name="W1G3-A",
            hand=[set_pool("INV")["Worldly Counsel"]],
            library=[w1g3_lea[name] for name in _W1G3_LIBRARY],
        ),
        _W1G3PlayerState(name="W1G3-B"),
    ])
    w1g3_game.enforce_mana_costs = False
    w1g3_game.active_player_index = 0
    if interactive:
        w1g3_game.interactive_seats = {0}
    for w1g3_name in lands:
        w1g3_game._put_permanent_onto_battlefield(
            0, _W1G3Permanent(card=w1g3_lea[w1g3_name]), None
        )
    assert w1g3_game.cast_from_hand(0, "Worldly Counsel").supported
    w1g3_game.resolve_top_of_stack()
    return w1g3_game  # _w1g3_counsel


def test_w1g3_worldly_counsel_chooses_nothing_as_it_is_cast(set_pool):
    """It has no target; the look is a decision made as it resolves."""
    card = set_pool("INV")["Worldly Counsel"]
    spec = _w1g3_cast_spec(card, _w1g3_compile(card))
    assert spec is None or spec.get("kind") == "none"


def test_w1g3_worldly_counsel_looks_at_one_card_per_basic_land_type(set_pool):
    """"Look at the top X cards of your library, where X is the number of basic
    land types among lands you control. Put one of those cards into your hand
    and the rest on the bottom of your library in any order." Three types (a
    Plains and a Tropical Island) offer the top three, not the top two."""
    game = _w1g3_counsel(set_pool, ["Plains", "Tropical Island"])
    [owed] = [c for c in game.pending_choices if c.kind == "look_top_pick"]
    assert owed.player_index == 0 and owed.data["top_count"] == 3

    assert game.confirm_look_top_pick(0, 1)
    _w1g3_resolve(game)
    me = game.players[0]
    assert [card.name for card in me.hand] == ["Craw Wurm"]
    assert [card.name for card in me.library] == [
        "Giant Growth", "Counterspell", "Dark Ritual",
        "Grizzly Bears", "Lightning Bolt",
    ], "the two not taken go to the bottom"
    assert [card.name for card in me.graveyard] == ["Worldly Counsel"]


def test_w1g3_worldly_counsel_cannot_reach_past_its_domain(set_pool):
    """Two Forests are one type: only the top card is offered, and an answer
    naming the second card is refused with the prompt still owed."""
    game = _w1g3_counsel(set_pool, ["Forest", "Forest"])
    [owed] = [c for c in game.pending_choices if c.kind == "look_top_pick"]
    assert owed.data["top_count"] == 1
    assert not game.confirm_look_top_pick(0, 1)
    assert [c.kind for c in game.pending_choices] == ["look_top_pick"]
    assert game.confirm_look_top_pick(0, 0)
    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]


def test_w1g3_worldly_counsel_with_no_basic_land_types_looks_at_nothing(set_pool):
    """X is 0: no prompt, no card, and the library is untouched."""
    game = _w1g3_counsel(set_pool, [])
    _w1g3_resolve(game)
    me = game.players[0]
    assert not game.pending_choices
    assert not me.hand
    assert [card.name for card in me.library] == _W1G3_LIBRARY
    assert "W1G3-A has no cards to look at" in game.log


def test_w1g3_worldly_counsel_a_headless_seat_takes_the_default(set_pool):
    """A non-interactive seat is never left owing the look."""
    game = _w1g3_counsel(
        set_pool, ["Plains", "Island", "Swamp", "Mountain", "Forest"],
        interactive=False,
    )
    _w1g3_resolve(game)
    game.auto_resolve_pending_choices()
    me = game.players[0]
    assert not game.pending_choices and not game.stack
    assert len(me.hand) == 1 and len(me.library) == 5


# --- W1G1: kicker ---
from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_instant_duel(set_pool, name, pool):
    """Seat 0 holds the INV instant *name* with *pool* floating, and costs are
    charged — a kicker is a price, so a rig that waives mana cannot tell a
    kicked cast from a free one."""
    lea = set_pool("LEA")
    mine = _W1G1PlayerState(
        "Caster", library=[lea["Forest"]] * 10, hand=[set_pool("INV")[name]],
    )
    theirs = _W1G1PlayerState("Victim", library=[lea["Forest"]] * 10)
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    return game  # _w1g1_instant_duel


def _w1g1_onto_battlefield(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent  # _w1g1_onto_battlefield


def test_w1g1_dismantling_blow_kicked_also_draws_two(set_pool):
    """"Destroy target artifact or enchantment. If this spell was kicked, draw
    two cards." The plain additive shape: the condition is read at resolution
    off the spell's own stack record."""
    game = _w1g1_instant_duel(set_pool, "Dismantling Blow", {"W": 3, "U": 3})
    ring = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Sol Ring"])
    result = game.cast_from_hand(
        0, "Dismantling Blow", optional_cost_payments={"{2}{U}": 1},
        target_permanent_ids=[ring.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(ring)
    assert [card.name for card in game.players[0].hand] == ["Forest", "Forest"]
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g1_dismantling_blow_unkicked_only_destroys(set_pool):
    game = _w1g1_instant_duel(set_pool, "Dismantling Blow", {"W": 3, "U": 3})
    ring = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Sol Ring"])
    result = game.cast_from_hand(
        0, "Dismantling Blow", target_permanent_ids=[ring.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(ring)
    assert game.players[0].hand == []
    # {2}{W} spent; the three that would have paid the kicker are still there.
    assert sum(game.players[0].mana_pool.values()) == 3


def test_w1g1_dismantling_blow_asks_for_its_target_kicked_or_not(set_pool):
    """The destroy is no part of the kicker (CR 702.33g reaches only a part
    that has its effect *only if* kicked), so the picker asks for the artifact
    or enchantment on either announcement — and offers nothing else."""
    card = set_pool("INV")["Dismantling Blow"]
    game = _w1g1_instant_duel(set_pool, "Dismantling Blow", {"W": 3, "U": 3})
    _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Sol Ring"])
    _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Hill Giant"])
    for announced in ({}, {"{2}{U}": 1}):
        spec = game.cast_target_spec(0, card, optional_cost_payments=announced)
        assert spec["requires_target"]
        assert [entry["name"] for entry in spec["valid_targets"]] == ["Sol Ring"]

    refused = game.cast_from_hand(
        0, "Dismantling Blow", optional_cost_payments={"{2}{U}": 1},
        target_permanent_ids=[
            next(p for p in game.controlled_by(1) if p.card.name == "Hill Giant")
            .permanent_id
        ],
    )
    assert not refused.supported
    assert sum(game.players[0].mana_pool.values()) == 6


def test_w1g1_agonizing_demise_kicked_burns_the_creatures_controller(set_pool):
    """"Destroy target nonblack creature. It can't be regenerated. If this
    spell was kicked, Agonizing Demise deals damage equal to that creature's
    power to the creature's controller." The power is the destroyed creature's
    last known (CR 608.2h) and the damage goes to *its* controller."""
    game = _w1g1_instant_duel(set_pool, "Agonizing Demise", {"B": 4, "R": 2})
    giant = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Hill Giant"])
    giant.regeneration_shield = 1
    result = game.cast_from_hand(
        0, "Agonizing Demise", optional_cost_payments={"{1}{R}": 1},
        target_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(giant)
    assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]
    assert [player.life for player in game.players] == [20, 17]


def test_w1g1_agonizing_demise_unkicked_deals_no_damage(set_pool):
    game = _w1g1_instant_duel(set_pool, "Agonizing Demise", {"B": 4, "R": 2})
    giant = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Hill Giant"])
    result = game.cast_from_hand(
        0, "Agonizing Demise", target_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(giant)
    assert [player.life for player in game.players] == [20, 20]


def test_w1g1_agonizing_demise_cannot_be_aimed_at_a_black_creature(set_pool):
    """"…target **nonblack** creature": the picker offers only the Giant, and a
    cast naming the Knight is refused before any mana is spent."""
    game = _w1g1_instant_duel(set_pool, "Agonizing Demise", {"B": 4, "R": 2})
    knight = _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Black Knight"])
    _w1g1_onto_battlefield(game, 1, set_pool("LEA")["Hill Giant"])
    spec = game.cast_target_spec(0, set_pool("INV")["Agonizing Demise"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Hill Giant"]

    refused = game.cast_from_hand(
        0, "Agonizing Demise", optional_cost_payments={"{1}{R}": 1},
        target_permanent_ids=[knight.permanent_id],
    )
    assert not refused.supported
    assert game.is_on_battlefield(knight)
    assert sum(game.players[0].mana_pool.values()) == 6


def test_w1g1_explosive_growth_is_two_or_five_never_seven(set_pool):
    """"Target creature gets +2/+2 until end of turn. If this spell was kicked,
    **that creature** gets +5/+5 until end of turn **instead**." One pump on
    the one creature the spell names, sized by the kicker — the back-reference
    in the second sentence is the first sentence's own target, so the spell
    still names exactly one creature (CR 601.2c)."""
    card = set_pool("INV")["Explosive Growth"]
    for kick, body in ((None, (4, 4)), ("{5}", (7, 7))):
        game = _w1g1_instant_duel(set_pool, "Explosive Growth", {"G": 9})
        bears = _w1g1_onto_battlefield(game, 0, set_pool("LEA")["Grizzly Bears"])
        giant = _w1g1_onto_battlefield(game, 0, set_pool("LEA")["Hill Giant"])
        spec = game.cast_target_spec(
            0, card, optional_cost_payments={kick: 1} if kick else None
        )
        assert spec["kind"] == "creature" and "max_targets" not in spec
        result = game.cast_from_hand(
            0, "Explosive Growth",
            optional_cost_payments={kick: 1} if kick else None,
            target_permanent_ids=[bears.permanent_id],
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        assert (bears.effective_power, bears.effective_toughness) == body
        assert (giant.effective_power, giant.effective_toughness) == (3, 3)
        assert sum(game.players[0].mana_pool.values()) == (3 if kick else 8)


def test_w1g1_orims_touch_prevents_two_or_four(set_pool):
    """"Prevent the next 2 damage that would be dealt to any target this turn.
    If this spell was kicked, prevent the next 4 damage that would be dealt to
    **that permanent or player** this turn instead." One shield of one size on
    the one thing the spell names, a creature or a player."""
    from engine.damage_events import deal_damage

    bolt = set_pool("LEA")["Lightning Bolt"]
    for kick, prevented in ((None, 2), ("{1}", 4)):
        announced = {kick: 1} if kick else None

        game = _w1g1_instant_duel(set_pool, "Orim's Touch", {"W": 4})
        giant = _w1g1_onto_battlefield(game, 0, set_pool("LEA")["Hill Giant"])
        result = game.cast_from_hand(
            0, "Orim's Touch", optional_cost_payments=announced,
            target_permanent_ids=[giant.permanent_id],
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        event = {"recipient": giant, "amount": 5, "source": bolt, "combat": False}
        assert deal_damage(game, event).dealt == 5 - prevented

        game = _w1g1_instant_duel(set_pool, "Orim's Touch", {"W": 4})
        result = game.cast_from_hand(
            0, "Orim's Touch", optional_cost_payments=announced,
            target_player_index=0,
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        # A fresh event each time: `deal_damage` writes what survived the
        # shields back onto the one it is handed.
        for seat, survives in ((0, 5 - prevented), (1, 5)):
            event = {
                "recipient": game.players[seat], "amount": 5, "source": bolt,
                "combat": False,
            }
            # …seat 1 was given no shield.
            assert deal_damage(game, event).dealt == survives


def test_w1g1_a_copy_of_a_kicked_spell_is_kicked(set_pool):
    """CR 707.10: a copy of a spell copies the choices made as it was cast, and
    paying a kicker is one (CR 702.33d). Fork on a kicked Dismantling Blow puts
    a kicked copy on the stack: the copy resolves first, destroys the artifact
    and draws the two cards — and the original, its only target gone, is
    removed by CR 608.2b and draws nothing."""
    lea = set_pool("LEA")
    game = _w1g1_instant_duel(set_pool, "Dismantling Blow", {"W": 3, "U": 3, "R": 2})
    game.players[0].hand.append(lea["Fork"])
    ring = _w1g1_onto_battlefield(game, 1, lea["Sol Ring"])
    assert game.queue_from_hand(
        0, "Dismantling Blow", optional_cost_payments={"{2}{U}": 1},
        target_permanent_ids=[ring.permanent_id],
    ).supported
    assert game.queue_from_hand(0, "Fork").supported
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(ring)
    assert [card.name for card in game.players[0].hand] == ["Forest", "Forest"]
    assert "Dismantling Blow (copy) resolved" in game.log
# end of the W1G1 instants block


# --- W1G7: piles ---
from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack

_W1G7_FOF_LIBRARY = (
    "Shivan Dragon", "Forest", "Lightning Bolt", "Forest", "Serra Angel", "Island",
)


def _w1g7_fof_table(set_pool, library=_W1G7_FOF_LIBRARY, interactive=()):
    """Seat 0 holding Fact or Fiction over a stacked library."""
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", hand=[inv["Fact or Fiction"]],
            library=[lea[name] for name in library],
        ),
        _W1G7PlayerState(name="P2"),
    ])
    game._sync_control()
    game.interactive_seats = set(interactive)
    game.enforce_mana_costs = False
    game.start_turn(0)
    w1g7_table_ready = game
    return w1g7_table_ready


def _w1g7_zone_names(cards):
    w1g7_names = [card.name for card in cards]
    return w1g7_names


def test_w1g7_fact_or_fiction_an_opponent_separates_and_the_caster_takes_a_pile(set_pool):
    """"Reveal the top five cards of your library. An opponent separates those
    cards into two piles. Put one pile into your hand and the other into your
    graveyard."

    CR 700.3 with two seats and two decisions, in that order: the **opponent**
    separates, then the **caster** chooses, and the game waits on each (CR
    608.2) — the spell is still on the stack while either is owed. Nothing
    moves at the split (CR 700.3c); the sixth card never leaves the library.
    """
    program = _w1g7_compile(set_pool("INV")["Fact or Fiction"])
    assert program.supported, program.reason

    game = _w1g7_fof_table(set_pool, interactive=[0, 1])
    assert game.cast_from_hand(0, "Fact or Fiction").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    split = game.pending_choice_of("pile_split", 1)
    assert split is not None, "the separation is owed by the opponent"
    assert [c.kind for c in game.pending_choices] == ["pile_split"]
    assert game.stack and game.waiting_prompt() is not None
    assert len(game.players[0].library) == 6, "a pile is not a zone: nothing moved"
    # Not the caster's to answer, no position twice, no position off the end.
    assert not game.confirm_pile_split(0, [0])
    assert not game.confirm_pile_split(1, [0, 0])
    assert not game.confirm_pile_split(1, [5])
    # The two Forests are one ``CardDefinition`` object, as two copies in a
    # deck always are — and they go into *different* piles, which only a
    # position can say.
    assert game.confirm_pile_split(1, [0, 1])

    choice = game.pending_choice_of("pile_choice", 0)
    assert choice is not None, "the choice is owed by the caster"
    assert game.stack, "still resolving"
    assert not game.confirm_pile_choice(1, 0)
    assert not game.confirm_pile_choice(0, 2)
    assert game.confirm_pile_choice(0, 1)

    caster = game.players[0]
    assert _w1g7_zone_names(caster.hand) == ["Lightning Bolt", "Forest", "Serra Angel"]
    assert _w1g7_zone_names(caster.graveyard) == [
        "Shivan Dragon", "Forest", "Fact or Fiction",
    ]
    assert _w1g7_zone_names(caster.library) == ["Island"]
    assert not game.stack and not game.pending_choices


def test_w1g7_fact_or_fiction_an_empty_pile_is_a_legal_separation(set_pool):
    """CR 700.3d: a pile can contain zero objects. Five-and-none is a real
    separation, and it makes the caster choose between everything and nothing —
    here they take nothing, and all five revealed cards are binned."""
    game = _w1g7_fof_table(set_pool, interactive=[0, 1])
    game.cast_from_hand(0, "Fact or Fiction")
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_pile_split(1, [])
    assert game.confirm_pile_choice(0, 0)

    caster = game.players[0]
    assert caster.hand == []
    assert _w1g7_zone_names(caster.graveyard) == [
        "Shivan Dragon", "Forest", "Lightning Bolt", "Forest", "Serra Angel",
        "Fact or Fiction",
    ]


def test_w1g7_fact_or_fiction_reveals_what_a_short_library_has(set_pool):
    """Three cards in the library: three are revealed and separated, and a
    headless table answers both decisions where they stand — the opponent's
    default is the most even split it can make, and the caster's reads the
    piles and takes the better one."""
    game = _w1g7_fof_table(
        set_pool, library=("Shivan Dragon", "Forest", "Lightning Bolt"),
    )
    assert game.cast_from_hand(0, "Fact or Fiction").supported
    _w1g7_resolve_stack(game)

    caster = game.players[0]
    assert caster.library == []
    # The Dragon alone outweighs a land and a one-mana spell, so the even
    # split is the Dragon against the other two and the caster takes it.
    assert _w1g7_zone_names(caster.hand) == ["Shivan Dragon"]
    assert _w1g7_zone_names(caster.graveyard) == [
        "Forest", "Lightning Bolt", "Fact or Fiction",
    ]
    assert any("reveals Shivan Dragon, Forest, Lightning Bolt" in line for line in game.log)
    assert not game.pending_choices


def _w1g7_reveal_table(set_pool, spell, library, interactive=()):
    """Seat 0 holding *spell* over a stacked library of LEA cards."""
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", hand=[inv[spell]], library=[lea[name] for name in library],
        ),
        _W1G7PlayerState(name="P2"),
    ])
    game._sync_control()
    game.interactive_seats = set(interactive)
    game.enforce_mana_costs = False
    game.start_turn(0)
    w1g7_reveal_ready = game
    return w1g7_reveal_ready


def test_w1g7_reviving_vapors_gains_the_mana_value_of_the_card_it_takes(set_pool):
    """"Reveal the top three cards of your library and put one of them into
    your hand. You gain life equal to that card's mana value. Put all other
    cards revealed this way into your graveyard."

    The pick is the caster's and the life is read off the card *taken* — six
    for Shivan Dragon, not the Forest's zero — which is a number the pick has
    to write down, because the card is in a hand by the time the gain asks
    (CR 608.2h). The other two revealed cards are binned; the fourth is not
    touched.
    """
    program = _w1g7_compile(set_pool("INV")["Reviving Vapors"])
    assert program.supported, program.reason

    game = _w1g7_reveal_table(
        set_pool, "Reviving Vapors",
        ("Forest", "Shivan Dragon", "Lightning Bolt", "Island"), interactive=[0],
    )
    assert game.cast_from_hand(0, "Reviving Vapors").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("look_top_pick", 0),
    ]
    assert any("reveals Forest, Shivan Dragon, Lightning Bolt" in line for line in game.log)
    assert game.players[0].life == 20, "nothing is gained before the pick"
    assert game.confirm_look_top_pick(0, 1)

    caster = game.players[0]
    assert _w1g7_zone_names(caster.hand) == ["Shivan Dragon"]
    assert caster.life == 26, game.log
    assert _w1g7_zone_names(caster.graveyard) == [
        "Forest", "Lightning Bolt", "Reviving Vapors",
    ]
    assert _w1g7_zone_names(caster.library) == ["Island"]
    assert not game.stack and not game.pending_choices


def test_w1g7_reviving_vapors_headless_takes_the_card_worth_the_most_life(set_pool):
    """A seat that is not asked takes the revealed card with the greatest mana
    value — the one printing in the look-and-pick family whose own sentence
    says which card is worth more — and an empty library gains nothing."""
    game = _w1g7_reveal_table(
        set_pool, "Reviving Vapors", ("Lightning Bolt", "Forest", "Serra Angel"),
    )
    game.cast_from_hand(0, "Reviving Vapors")
    _w1g7_resolve_stack(game)
    game.auto_resolve_pending_choices()
    caster = game.players[0]
    assert _w1g7_zone_names(caster.hand) == ["Serra Angel"]
    assert caster.life == 25, game.log

    empty = _w1g7_reveal_table(set_pool, "Reviving Vapors", ())
    empty.cast_from_hand(0, "Reviving Vapors")
    _w1g7_resolve_stack(empty)
    empty.auto_resolve_pending_choices()
    assert empty.players[0].life == 20
    assert not empty.pending_choices


def _w1g7_typed_card(name, subtypes):
    """A 2/2 creature card of the given subtypes."""
    from tests.helpers import _mk_card

    card = _mk_card(name, "{2}", f"Creature - {subtypes}", "")
    card.raw.update({"power": "2", "toughness": "2"})
    w1g7_typed = card
    return w1g7_typed


def test_w1g7_tsabos_decree_strips_one_creature_type_from_a_hand_and_a_board(set_pool):
    """"Choose a creature type. Target player reveals their hand and discards
    all creature cards of that type. Then destroy all creatures of that type
    that player controls. They can't be regenerated."

    The type is chosen as the spell resolves (CR 608.2d) and read back twice:
    by the discard — every Goblin *card*, the Goblin Warrior included, and
    neither the Elf nor the instant — and by the destroy, which takes that
    player's Goblins through a regeneration shield and leaves the caster's own
    Goblin alone ("that player controls").
    """
    from engine import targeting
    from engine.models import Permanent

    card = set_pool("INV")["Tsabo's Decree"]
    program = _w1g7_compile(card)
    assert program.supported, program.reason
    assert targeting.derive_cast_spec(card, program) == {"kind": "player"}

    goblin = _w1g7_typed_card("Goblin Raider", "Goblin")
    veteran = _w1g7_typed_card("Goblin Veteran", "Goblin Warrior")
    elf = _w1g7_typed_card("Elf Scout", "Elf")
    shielded = Permanent(card=goblin)
    shielded.regeneration_shield += 1
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="P1", hand=[card], battlefield=[Permanent(card=goblin)]),
        _W1G7PlayerState(
            name="P2",
            hand=[goblin, elf, veteran, set_pool("LEA")["Lightning Bolt"], goblin],
            battlefield=[shielded, Permanent(card=elf), Permanent(card=veteran)],
        ),
    ])
    game._sync_control()
    game.interactive_seats = {0}
    game.enforce_mana_costs = False
    game.start_turn(0)
    assert game.cast_from_hand(0, "Tsabo's Decree", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("creature_type_choice", 0),
    ]
    assert game.confirm_creature_type_choice(0, "goblin")

    victim = game.players[1]
    assert _w1g7_zone_names(victim.hand) == ["Elf Scout", "Lightning Bolt"], game.log
    assert [p.card.name for p in game.controlled_by(1)] == ["Elf Scout"]
    assert sorted(_w1g7_zone_names(victim.graveyard)) == [
        "Goblin Raider", "Goblin Raider", "Goblin Raider", "Goblin Veteran",
        "Goblin Veteran",
    ]
    assert [p.card.name for p in game.controlled_by(0)] == ["Goblin Raider"]
    assert any("P2 reveals their hand" in line for line in game.log)
    assert not game.stack and not game.pending_choices


# --- W1G8: odd ones ---
from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import derive_cast_spec as _w1g8_cast_spec
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_instant_duel(set_pool, *, active: int = 0, library: int = 10):
    """Two seats, costs off, each with *library* Islands to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", life=20, library=[island] * library)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = active
    return game


def _w1g8_instant_put(game, set_pool, seat: int, name: str, code: str = "LEA"):
    """*name* on *seat*'s battlefield, free of summoning sickness."""
    permanent = _W1G8Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g8_instant_names(game, seat: int) -> list[str]:
    """The names on *seat*'s battlefield, through the control seam."""
    return sorted(
        permanent.effective_card.name
        for permanent in game.controlled_by(game.players[seat])
    )


def test_winnow_destroys_a_permanent_with_a_namesake_and_draws(set_pool):
    """"Destroy target nonland permanent if another permanent with the same
    name is on the battlefield. / Draw a card." Two Grizzly Bears: the targeted
    one dies, the other stays, and the caster draws."""
    game = _w1g8_instant_duel(set_pool)
    target = _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    twin = _w1g8_instant_put(game, set_pool, 0, "Grizzly Bears")
    game.players[0].hand.append(set_pool("INV")["Winnow"])

    assert game.cast_from_hand(
        0, "Winnow", target_permanent_ids=[target.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert not game.is_on_battlefield(target)
    assert game.is_on_battlefield(twin)
    assert [card.name for card in game.players[0].hand] == ["Island"]


def test_winnow_spares_a_permanent_with_no_namesake_and_still_draws(set_pool):
    """The condition is checked on resolution (CR 608.2c) and guards the
    destroy alone: a lone Grizzly Bears survives, the card is still drawn."""
    game = _w1g8_instant_duel(set_pool)
    target = _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    _w1g8_instant_put(game, set_pool, 1, "Hill Giant")
    game.players[0].hand.append(set_pool("INV")["Winnow"])

    assert game.cast_from_hand(
        0, "Winnow", target_permanent_ids=[target.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert game.is_on_battlefield(target)
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert not any("Destroyed" in line for line in game.log)


def test_winnow_offers_nonland_permanents_and_refuses_a_land(set_pool):
    """"target **nonland** permanent" reaches the picker and the announcement
    gate: two Forests share a name and neither can be named."""
    winnow = set_pool("INV")["Winnow"]
    assert _w1g8_cast_spec(winnow, _w1g8_compile(winnow)) == {
        "kind": "permanent", "filter": {"exclude_types": ["land"]},
    }
    game = _w1g8_instant_duel(set_pool)
    forest = _w1g8_instant_put(game, set_pool, 1, "Forest")
    _w1g8_instant_put(game, set_pool, 1, "Forest")
    game.players[0].hand.append(winnow)

    assert not game.cast_from_hand(
        0, "Winnow", target_permanent_ids=[forest.permanent_id],
    ).supported
    assert game.is_on_battlefield(forest)
    assert game.players[0].hand == [winnow]


def _w1g8_response_table(set_pool):
    """Seat 0 holds Teferi's Response and an Island; seat 1 has a Forest and
    an Icy Manipulator to aim at either land."""
    game = _w1g8_instant_duel(set_pool)
    mine = _w1g8_instant_put(game, set_pool, 0, "Island")
    theirs = _w1g8_instant_put(game, set_pool, 1, "Forest")
    icy = _w1g8_instant_put(game, set_pool, 1, "Icy Manipulator")
    game.players[0].hand.append(set_pool("INV")["Teferi's Response"])
    return game, mine, theirs, icy


def _w1g8_response_offers(game, set_pool) -> list[str]:
    """What Teferi's Response's cast picker shows seat 0 right now."""
    card = set_pool("INV")["Teferi's Response"]
    spec = _w1g8_cast_spec(card, _w1g8_compile(card))
    return [
        entry["name"]
        for entry in game._enumerate_targets(0, card, spec, for_cast=True)
    ]


def test_teferis_response_counters_an_ability_and_destroys_its_source(set_pool):
    """"Counter target spell or ability an opponent controls that targets a
    land you control. If a permanent's ability is countered this way, destroy
    that permanent. / Draw two cards." The Icy Manipulator's ability is
    countered (the Island stays untapped), the Manipulator is destroyed, and
    two cards are drawn."""
    game, mine, _theirs, icy = _w1g8_response_table(set_pool)
    assert game.queue_permanent_ability(
        1, "Icy Manipulator", target_permanent_ids=[mine.permanent_id],
    ).supported
    assert _w1g8_response_offers(game, set_pool) == [
        "Icy Manipulator's activated ability"
    ]

    assert game.cast_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported
    _w1g8_resolve_stack(game)

    assert not mine.tapped
    assert not game.is_on_battlefield(icy)
    assert [card.name for card in game.players[1].graveyard] == ["Icy Manipulator"]
    assert len(game.players[0].hand) == 2


def test_teferis_response_counters_a_spell_and_destroys_nothing(set_pool):
    """The spell half: Stone Rain aimed at the Island is countered and binned,
    and "a permanent's ability" was not what was countered — nothing on either
    battlefield is destroyed."""
    game, mine, theirs, icy = _w1g8_response_table(set_pool)
    game.active_player_index = 1
    game.players[1].hand.append(set_pool("LEA")["Stone Rain"])
    assert game.queue_from_hand(
        1, "Stone Rain", target_permanent_ids=[mine.permanent_id],
    ).supported

    assert game.cast_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported
    _w1g8_resolve_stack(game)

    assert game.is_on_battlefield(mine)
    assert game.is_on_battlefield(theirs) and game.is_on_battlefield(icy)
    assert [card.name for card in game.players[1].graveyard] == ["Stone Rain"]
    assert len(game.players[0].hand) == 2


def test_teferis_response_cannot_name_an_object_aimed_at_another_land(set_pool):
    """"…that targets a land **you control**": an ability aimed at the
    opponent's own Forest is not offered, and naming it is refused at
    announcement (CR 601.2c) — so the spell is not two cards for {1}{U}."""
    game, _mine, theirs, _icy = _w1g8_response_table(set_pool)
    assert game.queue_permanent_ability(
        1, "Icy Manipulator", target_permanent_ids=[theirs.permanent_id],
    ).supported
    assert _w1g8_response_offers(game, set_pool) == []

    assert not game.cast_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported
    assert [card.name for card in game.players[0].hand] == ["Teferi's Response"]
    assert len(game.stack) == 1


def test_teferis_response_cannot_name_its_casters_own_ability(set_pool):
    """"…an **opponent** controls": the caster's own Icy Manipulator aimed at
    the caster's own Island answers the second clause and fails the first."""
    game, mine, _theirs, _icy = _w1g8_response_table(set_pool)
    _w1g8_instant_put(game, set_pool, 0, "Icy Manipulator")
    assert game.queue_permanent_ability(
        0, "Icy Manipulator", target_permanent_ids=[mine.permanent_id],
    ).supported
    assert _w1g8_response_offers(game, set_pool) == []

    assert not game.cast_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported
    assert [card.name for card in game.players[0].hand] == ["Teferi's Response"]


def test_teferis_response_is_uncastable_with_nothing_to_counter(set_pool):
    """A bare cast with an empty stack has no legal target (CR 601.2c) — the
    draw cannot be bought on its own."""
    game, _mine, _theirs, _icy = _w1g8_response_table(set_pool)

    assert not game.cast_from_hand(0, "Teferi's Response").supported
    assert [card.name for card in game.players[0].hand] == ["Teferi's Response"]


def test_teferis_response_does_not_resolve_once_its_target_is_illegal(set_pool):
    """CR 608.2b: the Island leaves in response, so the Stone Rain no longer
    "targets a land you control". Teferi's Response has no legal target left
    and is removed from the stack — no counter, and no cards drawn."""
    game, mine, _theirs, _icy = _w1g8_response_table(set_pool)
    game.active_player_index = 1
    game.players[1].hand.append(set_pool("LEA")["Stone Rain"])
    assert game.queue_from_hand(
        1, "Stone Rain", target_permanent_ids=[mine.permanent_id],
    ).supported
    assert game.queue_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported

    game.remove_from_battlefield(mine)
    assert game.resolve_top_of_stack()

    assert game.players[0].hand == []
    assert [item.card.name for item in game.stack] == ["Stone Rain"]
    assert any("608.2b" in line for line in game.log)


def _w1g8_dance_table(set_pool, *, in_hand=("Serra Angel",)):
    """Seat 0 in its own combat with Cauldron Dance in hand, Hill Giant and
    Craw Wurm in the graveyard, and *in_hand* beside the spell."""
    game = _w1g8_instant_duel(set_pool)
    game.interactive_seats = set()
    game.start_turn(0)
    pool = set_pool("LEA")
    _w1g8_instant_put(game, set_pool, 0, "Scryb Sprites")
    _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    game.players[0].graveyard.extend([pool["Hill Giant"], pool["Craw Wurm"]])
    game.players[0].hand = [set_pool("INV")["Cauldron Dance"]]
    game.players[0].hand.extend(pool[name] for name in in_hand)
    game._set_phase_and_step("combat", "beginning_of_combat")
    return game


def _w1g8_dance_cast(game, graveyard_slot: int):
    """Cast Cauldron Dance at *graveyard_slot* and settle everything it asks."""
    result = game.cast_from_hand(
        0, "Cauldron Dance", target_permanent_index=graveyard_slot,
    )
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return result


def test_cauldron_dance_is_cast_only_during_combat(set_pool):
    """"Cast this spell only during combat." Refused in a main phase with the
    card still in hand; its picker is the caster's own graveyard."""
    dance = set_pool("INV")["Cauldron Dance"]
    assert _w1g8_cast_spec(dance, _w1g8_compile(dance)) == {
        "kind": "graveyard_creature", "own_graveyard_only": True,
    }
    game = _w1g8_dance_table(set_pool)
    game._set_phase_and_step("precombat_main", "precombat_main")

    assert not game.cast_from_hand(
        0, "Cauldron Dance", target_permanent_index=0,
    ).supported
    assert dance in game.players[0].hand
    assert [card.name for card in game.players[0].graveyard] == [
        "Hill Giant", "Craw Wurm",
    ]


def test_cauldron_dance_returns_one_creature_and_puts_in_another_with_haste(set_pool):
    """Both paragraphs: the targeted Hill Giant comes back from the graveyard,
    the Serra Angel comes in from the hand, and both have haste."""
    game = _w1g8_dance_table(set_pool)

    assert _w1g8_dance_cast(game, 0).supported

    assert _w1g8_instant_names(game, 0) == [
        "Hill Giant", "Scryb Sprites", "Serra Angel",
    ]
    arrived = {
        permanent.card.name: permanent
        for permanent in game.controlled_by(game.players[0])
    }
    assert game._has_keyword(arrived["Hill Giant"], "haste")
    assert game._has_keyword(arrived["Serra Angel"], "haste")
    assert not game._has_keyword(arrived["Scryb Sprites"], "haste")
    assert [card.name for card in game.players[0].graveyard] == [
        "Craw Wurm", "Cauldron Dance",
    ]


def test_cauldron_dance_bounces_the_first_and_sacrifices_the_second_at_end_step(set_pool):
    """"Return it to your hand at the beginning of the next end step." / "Its
    controller sacrifices it at the beginning of the next end step." Each
    pronoun names the creature its own paragraph made: the Hill Giant goes to
    hand, the Serra Angel to the graveyard, and neither bystander is touched."""
    game = _w1g8_dance_table(set_pool)
    _w1g8_dance_cast(game, 0)

    game.resolve_end_step(0)
    _w1g8_resolve_stack(game)

    assert _w1g8_instant_names(game, 0) == ["Scryb Sprites"]
    assert _w1g8_instant_names(game, 1) == ["Grizzly Bears"]
    assert [card.name for card in game.players[0].hand] == ["Hill Giant"]
    assert [card.name for card in game.players[0].graveyard] == [
        "Craw Wurm", "Cauldron Dance", "Serra Angel",
    ]


def test_cauldron_dance_with_an_empty_hand_sacrifices_nothing(set_pool):
    """"You **may** put a creature card from your hand…" With none to put, the
    second paragraph's delayed sacrifice is about no object and arms nothing —
    it must not fall back to the reanimated creature or to a bystander. The
    target here is graveyard slot 1, the number that used to be read as a
    battlefield slot."""
    game = _w1g8_dance_table(set_pool, in_hand=())

    assert _w1g8_dance_cast(game, 1).supported
    assert _w1g8_instant_names(game, 0) == ["Craw Wurm", "Scryb Sprites"]
    assert len(
        [entry for entry in game.delayed_triggers if entry.event == "next_end_step"]
    ) == 1

    game.resolve_end_step(0)
    _w1g8_resolve_stack(game)

    assert _w1g8_instant_names(game, 0) == ["Scryb Sprites"]
    assert _w1g8_instant_names(game, 1) == ["Grizzly Bears"]
    assert [card.name for card in game.players[0].hand] == ["Craw Wurm"]
    assert "Craw Wurm" not in [card.name for card in game.players[0].graveyard]


def test_backlash_taps_a_creature_and_has_it_hit_its_own_controller(set_pool):
    """"Tap target untapped creature. That creature deals damage equal to its
    power to its controller." The Hill Giant is tapped and deals 3 to the seat
    that controls it — and the creature is the source of that damage
    (CR 120.7), not the spell."""
    game = _w1g8_instant_duel(set_pool)
    giant = _w1g8_instant_put(game, set_pool, 1, "Hill Giant")
    game.players[0].hand.append(set_pool("INV")["Backlash"])

    assert game.cast_from_hand(
        0, "Backlash", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert giant.tapped
    assert [player.life for player in game.players] == [20, 17]
    assert "Hill Giant deals 3 damage to P1" in game.log


def test_backlash_aimed_at_its_casters_own_creature_hits_the_caster(set_pool):
    """"**its** controller" is the creature's, whoever cast the spell."""
    game = _w1g8_instant_duel(set_pool)
    wurm = _w1g8_instant_put(game, set_pool, 0, "Craw Wurm")
    game.players[0].hand.append(set_pool("INV")["Backlash"])

    assert game.cast_from_hand(
        0, "Backlash", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert wurm.tapped
    assert [player.life for player in game.players] == [14, 20]


def test_backlash_cannot_target_a_tapped_creature(set_pool):
    """"target **untapped** creature" narrows the picker and the announcement:
    a creature already tapped is not offered and cannot be named."""
    backlash = set_pool("INV")["Backlash"]
    assert _w1g8_cast_spec(backlash, _w1g8_compile(backlash)) == {
        "kind": "creature", "filter": {"untapped_only": True},
    }
    game = _w1g8_instant_duel(set_pool)
    bears = _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    bears.tapped = True
    game.players[0].hand.append(backlash)

    assert not game.cast_from_hand(
        0, "Backlash", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.players[1].life == 20
    assert game.players[0].hand == [backlash]


def _w1g8_liberate_table(set_pool):
    """Seat 0 on its own turn with Liberate in hand and a Grizzly Bears;
    seat 1 has a Hill Giant."""
    game = _w1g8_instant_duel(set_pool)
    game.interactive_seats = set()
    game.start_turn(0)
    bears = _w1g8_instant_put(game, set_pool, 0, "Grizzly Bears")
    giant = _w1g8_instant_put(game, set_pool, 1, "Hill Giant")
    game.players[0].hand = [set_pool("INV")["Liberate"]]
    return game, bears, giant


def test_liberate_exiles_a_creature_and_returns_it_at_the_next_end_step(set_pool):
    """"Exile target creature you control. Return that card to the battlefield
    under its owner's control at the beginning of the next end step." Gone
    until the end step, then back as a new object (CR 400.7)."""
    game, bears, _giant = _w1g8_liberate_table(set_pool)

    assert game.cast_from_hand(
        0, "Liberate", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)
    assert _w1g8_instant_names(game, 0) == []
    assert [card.name for card in game.players[0].exile] == ["Grizzly Bears"]

    game.resolve_end_step(0)
    _w1g8_resolve_stack(game)

    assert _w1g8_instant_names(game, 0) == ["Grizzly Bears"]
    assert game.players[0].exile == []
    returned = next(iter(game.controlled_by(game.players[0])))
    assert returned.permanent_id != bears.permanent_id


def test_liberate_returns_a_stolen_creature_to_its_owner(set_pool):
    """"…under its **owner's** control": a creature seat 0 controls and seat 1
    owns is exiled to seat 1's exile (CR 400.3) and comes back on seat 1's
    side."""
    from engine.control import change_control

    game, bears, giant = _w1g8_liberate_table(set_pool)
    change_control(giant, 0, source=bears)
    game._sync_control()
    assert game.controller_index_of(giant) == 0

    assert game.cast_from_hand(
        0, "Liberate", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)
    assert [card.name for card in game.players[1].exile] == ["Hill Giant"]

    game.resolve_end_step(0)
    _w1g8_resolve_stack(game)

    assert _w1g8_instant_names(game, 1) == ["Hill Giant"]
    assert _w1g8_instant_names(game, 0) == ["Grizzly Bears"]


def test_liberate_cannot_target_a_creature_its_caster_does_not_control(set_pool):
    """"target creature **you control**": the opponent's Hill Giant is not
    offered and cannot be named."""
    liberate = set_pool("INV")["Liberate"]
    assert _w1g8_cast_spec(liberate, _w1g8_compile(liberate)) == {
        "kind": "creature", "own_only": True,
    }
    game, _bears, giant = _w1g8_liberate_table(set_pool)

    assert not game.cast_from_hand(
        0, "Liberate", target_permanent_ids=[giant.permanent_id],
    ).supported
    assert game.is_on_battlefield(giant)
    assert game.players[0].hand == [liberate]


# --- W2G1: kicker spells ---
import pytest as _w2g1_pytest

from engine import Game as _W2G1Game
from engine import PlayerState as _W2G1PlayerState
from engine.models import Permanent as _W2G1Permanent
from engine.oracle import compile_card_oracle as _w2g1_compile
from tests.helpers import _nosick as _w2g1_nosick
from tests.helpers import resolve_stack as _w2g1_resolve_stack


def _w2g1_duel(set_pool, name, pool, *, theirs=()):
    """Seat 0 holds the INV instant *name* with *pool* floating; seat 1 holds
    the LEA cards *theirs*. Costs are charged: a kicker is a price, and a rig
    that waives mana cannot tell a kicked cast from a free one."""
    lea = set_pool("LEA")
    game = _W2G1Game(players=[
        _W2G1PlayerState(
            "Caster", library=[lea["Forest"]] * 10, hand=[set_pool("INV")[name]],
        ),
        _W2G1PlayerState(
            "Victim", library=[lea["Forest"]] * 10,
            hand=[lea[other] for other in theirs],
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    return game  # _w2g1_duel


def _w2g1_put(game, seat, card):
    permanent = _W2G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent  # _w2g1_put


def _w2g1_names(cards):
    return [card.name for card in cards]  # _w2g1_names


# --- Prohibit ---------------------------------------------------------------


@_w2g1_pytest.mark.parametrize("spell, mana, x_value, kicked, countered", [
    ("Lightning Bolt", {"R": 1}, None, False, True),    # mana value 1 <= 2
    ("Hill Giant", {"R": 4}, None, False, False),       # 4 > 2
    ("Hill Giant", {"R": 4}, None, True, True),         # 4 <= 4, kicked
    ("Craw Wurm", {"G": 6}, None, True, False),         # 6 > 4
    # CR 202.3b: on the stack an X in the cost is the announced value.
    ("Fireball", {"R": 4}, 1, False, True),             # {X}{R}, X=1: 2
    ("Fireball", {"R": 4}, 3, False, False),            # X=3: 4
    ("Fireball", {"R": 4}, 3, True, True),
])
def test_w2g1_prohibit_counters_by_the_spells_mana_value(
    set_pool, spell, mana, x_value, kicked, countered,
):
    """"Counter target spell if its mana value is 2 or less. If this spell was
    kicked, counter that spell if its mana value is 4 or less instead."

    The clause is a condition on the *effect* (CR 608.2c), not a targeting
    restriction: every row is a legal announcement, paid for in full, and the
    rows that are not countered resolve as if Prohibit had not been cast."""
    game = _w2g1_duel(set_pool, "Prohibit", {"U": 4}, theirs=[spell])
    game.players[1].mana_pool.update(mana)
    is_creature = "Creature" in set_pool("LEA")[spell].type_line
    announced = {} if is_creature else {"target_player_index": 0}
    if x_value is not None:
        announced["x_value"] = x_value
    assert game.queue_from_hand(1, spell, **announced).supported

    result = game.queue_from_hand(
        0, "Prohibit", target_stack_index=0,
        optional_cost_payments={"{2}": 1} if kicked else None,
    )
    assert result.supported, result
    assert sum(game.players[0].mana_pool.values()) == (0 if kicked else 2)
    _w2g1_resolve_stack(game)

    assert _w2g1_names(game.players[0].graveyard) == ["Prohibit"]
    on_their_board = _w2g1_names(p.card for p in game.controlled_by(1))
    if countered:
        assert _w2g1_names(game.players[1].graveyard) == [spell]
        assert game.players[0].life == 20 and on_their_board == []
        assert any("countered by Prohibit" in line for line in game.log)
    elif is_creature:
        assert on_their_board == [spell]
    else:
        assert game.players[0].life == 20 - (x_value or 3), game.log


def test_w2g1_prohibit_offers_every_spell_whatever_it_costs(set_pool):
    """CR 601.2c reads the printed target phrase, which is "target spell": a
    six-drop is offered to the picker exactly as a one-drop is."""
    game = _w2g1_duel(set_pool, "Prohibit", {"U": 4}, theirs=["Craw Wurm"])
    game.players[1].mana_pool.update({"G": 6})
    assert game.queue_from_hand(1, "Craw Wurm").supported

    spec = game.cast_target_spec(0, set_pool("INV")["Prohibit"])
    assert spec["requires_target"]
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Craw Wurm"]


# --- Overload ---------------------------------------------------------------


@_w2g1_pytest.mark.parametrize("artifact, kicked, destroyed", [
    ("Sol Ring", False, True),              # 1 <= 2
    ("Jayemdae Tome", False, False),        # 4 > 2
    ("Jayemdae Tome", True, True),          # 4 <= 5, kicked
    ("Colossus of Sardia", True, False),    # 9 > 5
])
def test_w2g1_overload_destroys_by_the_artifacts_mana_value(
    set_pool, artifact, kicked, destroyed,
):
    """"Destroy target artifact if its mana value is 2 or less. If this spell
    was kicked, destroy that artifact if its mana value is 5 or less instead."
    One artifact is announced whichever arm resolves, and "that artifact" is
    it."""
    game = _w2g1_duel(set_pool, "Overload", {"R": 3})
    pool = {**set_pool("LEA"), **set_pool("ATQ")}
    victim = _w2g1_put(game, 1, pool[artifact])
    bystander = _w2g1_put(game, 1, set_pool("LEA")["Mox Ruby"])

    result = game.cast_from_hand(
        0, "Overload", target_permanent_ids=[victim.permanent_id],
        optional_cost_payments={"{2}": 1} if kicked else None,
    )
    assert result.supported, result
    _w2g1_resolve_stack(game)

    assert game.is_on_battlefield(victim) is (not destroyed), game.log
    assert game.is_on_battlefield(bystander), "a zero-drop nobody aimed at"
    assert sum(game.players[0].mana_pool.values()) == (0 if kicked else 2)


def test_w2g1_overload_may_be_aimed_at_any_artifact_and_at_nothing_else(set_pool):
    """The mana value is asked at resolution, so a nine-drop is a legal target
    the spell simply does nothing to; a creature is not an artifact and the
    cast is refused with nothing spent."""
    game = _w2g1_duel(set_pool, "Overload", {"R": 3})
    colossus = _w2g1_put(game, 1, set_pool("ATQ")["Colossus of Sardia"])
    giant = _w2g1_put(game, 1, set_pool("LEA")["Hill Giant"])

    spec = game.cast_target_spec(0, set_pool("INV")["Overload"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Colossus of Sardia"]

    refused = game.cast_from_hand(
        0, "Overload", target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported
    assert sum(game.players[0].mana_pool.values()) == 3
    assert game.is_on_battlefield(colossus)


# --- Scorching Lava ---------------------------------------------------------


@_w2g1_pytest.mark.parametrize("kicked", [False, True])
def test_w2g1_scorching_lava_exiles_what_it_kills_only_when_kicked(set_pool, kicked):
    """"…If this spell was kicked, that creature can't be regenerated this
    turn and if it would die this turn, exile it instead." Two points to a 2/2
    either way; the kick decides which zone it ends up in."""
    game = _w2g1_duel(set_pool, "Scorching Lava", {"R": 3})
    bears = _w2g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])

    assert game.cast_from_hand(
        0, "Scorching Lava", target_permanent_ids=[bears.permanent_id],
        optional_cost_payments={"{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)

    assert not game.is_on_battlefield(bears)
    assert _w2g1_names(game.players[1].exile) == (["Grizzly Bears"] if kicked else [])
    assert _w2g1_names(game.players[1].graveyard) == ([] if kicked else ["Grizzly Bears"])


@_w2g1_pytest.mark.parametrize("kicked", [False, True])
def test_w2g1_scorching_lava_kicked_beats_a_regeneration_shield(set_pool, kicked):
    """"…can't be regenerated this turn" (CR 701.19c). The same shield saves
    the creature from the unkicked spell, which is what shows the kicked run
    measured the rider rather than a shield that never worked."""
    game = _w2g1_duel(set_pool, "Scorching Lava", {"R": 3})
    bears = _w2g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    bears.regeneration_shield = 1

    assert game.cast_from_hand(
        0, "Scorching Lava", target_permanent_ids=[bears.permanent_id],
        optional_cost_payments={"{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)

    assert game.is_on_battlefield(bears) is (not kicked), game.log
    if kicked:
        assert _w2g1_names(game.players[1].exile) == ["Grizzly Bears"]
    else:
        assert bears.tapped and bears.damage_marked == 0


def test_w2g1_scorching_lava_marks_a_survivor_for_the_turn_and_spares_a_player(set_pool):
    """The riders last "this turn", so a creature that survives the two points
    carries them until cleanup; "that creature" is the guard, so a kicked Lava
    aimed at a player is two damage and nothing else."""
    game = _w2g1_duel(set_pool, "Scorching Lava", {"R": 3})
    giant = _w2g1_put(game, 1, set_pool("LEA")["Hill Giant"])
    assert game.cast_from_hand(
        0, "Scorching Lava", target_permanent_ids=[giant.permanent_id],
        optional_cost_payments={"{R}": 1},
    ).supported
    _w2g1_resolve_stack(game)
    assert giant.damage_marked == 2
    assert giant.metadata.get("cant_be_regenerated_this_turn")
    assert giant.metadata.get("exile_if_dies_this_turn")

    game = _w2g1_duel(set_pool, "Scorching Lava", {"R": 3})
    assert game.cast_from_hand(
        0, "Scorching Lava", optional_cost_payments={"{R}": 1},
    ).supported
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 18


# --- Urza's Rage ------------------------------------------------------------


@_w2g1_pytest.mark.parametrize("kicked, damage", [(False, 3), (True, 10)])
def test_w2g1_urzas_rage_deals_three_or_ten(set_pool, kicked, damage):
    """"Urza's Rage deals 3 damage to any target. If this spell was kicked,
    **instead** it deals 10 damage to **that permanent or player** …" One
    target, announced once; the fronted "instead" replaces the three rather
    than adding to it (thirteen is the two sentences read as steps)."""
    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 12})
    assert game.cast_from_hand(
        0, "Urza's Rage", optional_cost_payments={"{8}{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 20 - damage
    assert sum(game.players[0].mana_pool.values()) == (0 if kicked else 9)

    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 12})
    wurm = _w2g1_put(game, 1, set_pool("LEA")["Craw Wurm"])      # 6/4
    elemental = _w2g1_put(game, 1, set_pool("LEA")["Force of Nature"])  # 8/8
    assert game.cast_from_hand(
        0, "Urza's Rage", target_permanent_ids=[elemental.permanent_id],
        optional_cost_payments={"{8}{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 20, "a creature was named, not the face"
    assert game.is_on_battlefield(elemental) is (not kicked)
    assert game.is_on_battlefield(wurm) and wurm.damage_marked == 0


@_w2g1_pytest.mark.parametrize("kicked, life", [(False, 20), (True, 10)])
def test_w2g1_urzas_rage_kicked_goes_through_a_players_shield(set_pool, kicked, life):
    """"…and the damage can't be prevented." A Circle-shaped shield on the
    player swallows the three and does nothing to the ten — any recipient, not
    only a creature, which is what separates this clause from Lava Burst's."""
    from engine.shields import PREVENT_NEXT_N, Shield, add_shield

    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 12})
    add_shield(game.players[1], Shield(kind=PREVENT_NEXT_N, amount=10, uses=None))
    assert game.cast_from_hand(
        0, "Urza's Rage", optional_cost_payments={"{8}{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)
    assert game.players[1].life == life, game.log


@_w2g1_pytest.mark.parametrize("kicked", [False, True])
def test_w2g1_urzas_rage_kicked_goes_through_a_creatures_shield(set_pool, kicked):
    """The same clause about a permanent: a ten-point shield on a 9/9 absorbs
    the unkicked three whole, and absorbs none of the kicked ten."""
    from engine.shields import PREVENT_NEXT_N, Shield, add_shield

    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 12})
    colossus = _w2g1_put(game, 1, set_pool("ATQ")["Colossus of Sardia"])   # 9/9
    add_shield(colossus, Shield(kind=PREVENT_NEXT_N, amount=10, uses=None))
    assert game.cast_from_hand(
        0, "Urza's Rage", target_permanent_ids=[colossus.permanent_id],
        optional_cost_payments={"{8}{R}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)

    if kicked:
        assert not game.is_on_battlefield(colossus), game.log
    else:
        assert game.is_on_battlefield(colossus) and colossus.damage_marked == 0


def test_w2g1_urzas_rage_cant_be_countered(set_pool):
    """"This spell can't be countered." A Counterspell aimed at it resolves
    and the Rage resolves after it."""
    game = _w2g1_duel(set_pool, "Urza's Rage", {"R": 3}, theirs=["Counterspell"])
    game.players[1].mana_pool.update({"U": 2})
    assert game.queue_from_hand(0, "Urza's Rage").supported
    game.queue_from_hand(1, "Counterspell", target_stack_index=0)
    _w2g1_resolve_stack(game)
    assert game.players[1].life == 17, game.log


def test_w2g1_urzas_rage_program_carries_the_printed_lock_on_one_arm(set_pool):
    """The rider is written into the kicked arm's payload and nowhere else:
    an unkicked Rage is an ordinary three-damage spell."""
    program = _w2g1_compile(set_pool("INV")["Urza's Rage"])
    branch = next(i for i in program.instructions if i.kind == "if_then")
    kicked, plain = branch.payload["then"][0], branch.payload["else"][0]
    assert (kicked.payload["amount"], plain.payload["amount"]) == (10, 3)
    assert kicked.payload.get("cant_be_prevented") is True
    assert "cant_be_prevented" not in plain.payload
    assert kicked.payload["targets"] == plain.payload["targets"]


# --- Vigorous Charge --------------------------------------------------------


def _w2g1_charge(set_pool, *, kicked, blocker=None, second_attacker=False):
    """Vigorous Charge on a 6/4 that then attacks, through to the end of the
    combat damage step. Returns the game."""
    lea = set_pool("LEA")
    game = _w2g1_duel(set_pool, "Vigorous Charge", {})
    game.interactive_seats = set()
    wurm = _w2g1_nosick(_w2g1_put(game, 0, lea["Craw Wurm"]))
    if second_attacker:
        _w2g1_nosick(_w2g1_put(game, 0, lea["Hill Giant"]))
    if blocker:
        _w2g1_nosick(_w2g1_put(game, 1, lea[blocker]))
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].mana_pool.update({"G": 1, "W": 1})
    assert game.cast_from_hand(
        0, "Vigorous Charge", target_permanent_ids=[wurm.permanent_id],
        optional_cost_payments={"{W}": 1} if kicked else None,
    ).supported
    _w2g1_resolve_stack(game)
    assert game._has_keyword(wurm, "trample")
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1] if second_attacker else [0])[0]
    game.advance_combat_phase()
    if blocker:
        assert game.declare_blockers(1, {0: 0})[0]
    _w2g1_resolve_stack(game)
    game.advance_combat_phase()
    _w2g1_resolve_stack(game)
    return game  # _w2g1_charge


def test_w2g1_vigorous_charge_unkicked_is_trample_and_nothing_else(set_pool):
    """"…if this spell was kicked, you gain life equal to that damage." The
    gate is asked as the delayed ability would be created: unkicked, none is,
    and six combat damage gains nobody anything."""
    game = _w2g1_charge(set_pool, kicked=False)
    assert game.delayed_triggers == []
    assert (game.players[0].life, game.players[1].life) == (20, 14)


def test_w2g1_vigorous_charge_kicked_gains_the_damage_dealt_to_a_player(set_pool):
    game = _w2g1_charge(set_pool, kicked=True)
    assert (game.players[0].life, game.players[1].life) == (26, 14), game.log


def test_w2g1_vigorous_charge_counts_trample_damage_on_both_sides_of_a_block(set_pool):
    """"Whenever that creature deals combat damage this turn" — to anything.
    Blocked by a 2/2, the 6/4 trampler assigns two to the blocker and four to
    the player, and the life gained is all six."""
    game = _w2g1_charge(set_pool, kicked=True, blocker="Grizzly Bears")
    assert game.players[1].life == 16
    assert game.players[0].life == 26, game.log


def test_w2g1_vigorous_charge_watches_only_the_creature_it_named(set_pool):
    """Another attacker's three points are not "that creature"'s damage, and
    the ability is gone with the turn (CR 603.7b)."""
    game = _w2g1_charge(set_pool, kicked=True, second_attacker=True)
    assert game.players[1].life == 11
    assert game.players[0].life == 26, game.log

    from engine.delayed_triggers import expire_delayed_triggers

    assert [entry.event for entry in game.delayed_triggers] == [
        "bound_permanent_deals_combat_damage"
    ]
    expire_delayed_triggers(game)
    assert game.delayed_triggers == []
# end of the W2G1 instants block
