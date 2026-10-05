"""Planeshift sorceries.

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


# --- W1G8: damage and the odd ones ---
#
# March of Souls: "Destroy all creatures. They can't be regenerated. For each
# creature destroyed this way, its controller creates a 1/1 white Spirit
# creature token with flying." The sweep and the loop were both built (Martyr's
# Cry prints the same loop over an exile with a draw inside it); what refused
# was the *token's* seat — "its controller" under a loop was read only off a
# firing event, and a sorcery has none.

from engine import Game as _w1g8s_Game, PlayerState as _w1g8s_Player  # noqa: E402
from engine.card_loader import (load_cards as _w1g8s_load,  # noqa: E402
                                manifest_set_path as _w1g8s_path)
from engine.control import change_control as _w1g8s_change_control  # noqa: E402
from engine.grammar import compile_line as _w1g8s_compile_line  # noqa: E402
from engine.models import (CardDefinition as _w1g8s_Card,  # noqa: E402
                           Permanent as _w1g8s_Permanent)
from engine.oracle import compile_card_oracle as _w1g8s_compile  # noqa: E402

from tests.helpers import resolve_stack as _w1g8s_resolve_stack  # noqa: E402


def _w1g8s_lea():
    return {card.name: card for card in _w1g8s_load(_w1g8s_path("LEA"))}


def _w1g8s_body(name, power, toughness, text="", keywords=()):
    """A bare creature for a sweep to find."""
    return _w1g8s_Card(
        name=name, mana_cost="{3}", cmc=3.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=tuple(keywords),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )  # W1G8 sorceries: a test body


def _w1g8s_duel(mine, theirs, *, hand0=(), hand1=(), active=0, interactive=()):
    """Both boards placed and unsick, *active* in its precombat main phase."""
    board0 = [_w1g8s_Permanent(card=card) for card in mine]
    board1 = [_w1g8s_Permanent(card=card) for card in theirs]
    filler = _w1g8s_body("Filler", 0, 1)
    game = _w1g8s_Game(players=[
        _w1g8s_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10),
        _w1g8s_Player(name="P1", battlefield=board1, hand=list(hand1),
                      library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._close_current_priority_step()
    return game, board0, board1  # W1G8 sorceries: the duel


def _w1g8s_spirits(game, seat):
    return [
        perm for perm in game.controlled_by(seat)
        if perm.card.name == "Spirit Token"
    ]  # W1G8 sorceries: the tokens a seat holds


def test_w1g8_march_of_souls_pays_each_controller_a_spirit_per_creature(set_pool):
    """Two of the caster's and three of the opponent's: two Spirits and three,
    each a 1/1 white flier — and created after the destruction, so they are
    there when the spell has finished."""
    lea = _w1g8s_lea()
    march = set_pool("PLS")["March of Souls"]
    assert _w1g8s_compile(march).supported
    game, _, _ = _w1g8s_duel(
        [lea["Hill Giant"], lea["Grizzly Bears"]],
        [lea["Hill Giant"], lea["Grizzly Bears"], lea["Drudge Skeletons"]],
        hand0=[march],
    )

    cast = game.cast_from_hand(0, "March of Souls")
    assert cast.supported, cast.details
    _w1g8s_resolve_stack(game)
    game._settle()

    assert len(_w1g8s_spirits(game, 0)) == 2
    assert len(_w1g8s_spirits(game, 1)) == 3
    assert all(
        perm.card.name == "Spirit Token" for perm in game.all_permanents()
    ), "every creature was destroyed, the Skeletons included"
    token = _w1g8s_spirits(game, 1)[0]
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    assert token.has_keyword("flying")
    assert token.effective_colors == {"W"}
    assert token.has_type("spirit") and token.is_creature
    assert [card.name for card in game.players[1].graveyard] == [
        "Hill Giant", "Grizzly Bears", "Drudge Skeletons",
    ]


def test_w1g8_march_of_souls_cannot_be_regenerated_through(set_pool):
    """"They can't be regenerated." A regeneration shield already on a creature
    does not save it — and it is replaced by a Spirit like the rest."""
    lea = _w1g8s_lea()
    march = set_pool("PLS")["March of Souls"]
    game, _, theirs = _w1g8s_duel([], [lea["Drudge Skeletons"]], hand0=[march])
    skeletons = theirs[0]

    shielded = game.activate_permanent_ability(1, "Drudge Skeletons", ability_index=0)
    assert shielded.supported, shielded.details
    _w1g8s_resolve_stack(game)

    assert game.cast_from_hand(0, "March of Souls").supported
    _w1g8s_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(skeletons)
    assert len(_w1g8s_spirits(game, 1)) == 1


def test_w1g8_march_of_souls_reads_who_controlled_it_as_it_left(set_pool):
    """"Its controller" is last known information (CR 608.2h): a creature the
    caster had taken pays the *caster* its Spirit, though the card goes to its
    owner's graveyard."""
    lea = _w1g8s_lea()
    march = set_pool("PLS")["March of Souls"]
    game, _, theirs = _w1g8s_duel(
        [lea["Hill Giant"]], [lea["Grizzly Bears"]], hand0=[march],
    )
    # the two calls every control-changing handler makes, in that order: the
    # contribution, then the projection that also records who owns it
    _w1g8s_change_control(theirs[0], 0, source="test")
    game._sync_control()
    assert game.controller_index_of(theirs[0]) == 0

    assert game.cast_from_hand(0, "March of Souls").supported
    _w1g8s_resolve_stack(game)
    game._settle()

    assert len(_w1g8s_spirits(game, 0)) == 2
    assert _w1g8s_spirits(game, 1) == []
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_w1g8_march_of_souls_pays_only_for_what_was_destroyed(set_pool):
    """"Destroyed this way": an indestructible creature is still there and
    earns nothing, a token that is destroyed earns its controller a token, and
    an empty board resolves and makes none."""
    lea = _w1g8s_lea()
    march = set_pool("PLS")["March of Souls"]
    idol = _w1g8s_body("Stone Idol", 3, 3, "Indestructible", ("Indestructible",))
    game, mine, _ = _w1g8s_duel(
        [idol], [lea["Grizzly Bears"]], hand0=[march, march, march],
    )

    assert game.cast_from_hand(0, "March of Souls").supported
    _w1g8s_resolve_stack(game)
    game._settle()
    assert game.is_on_battlefield(mine[0])
    assert _w1g8s_spirits(game, 0) == []
    first = _w1g8s_spirits(game, 1)
    assert len(first) == 1

    # the Spirit is a creature too: the second March destroys it and replaces it
    assert game.cast_from_hand(0, "March of Souls").supported
    _w1g8s_resolve_stack(game)
    game._settle()
    second = _w1g8s_spirits(game, 1)
    assert len(second) == 1 and second[0] is not first[0]
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"], (
        "a destroyed token ceases to exist rather than reaching the graveyard"
    )


def test_w1g8_its_controller_needs_the_loop_to_name_anybody():
    """The refusal half. Outside a "for each … this way" loop the sweep's
    per-object record is still written, and "its controller creates a token"
    would compile to a per-iteration read with no iteration round it — so the
    loop marker is what admits the words, not the record."""
    looped = _w1g8s_compile_line(
        "Destroy all creatures. For each creature destroyed this way, its "
        "controller creates a 1/1 white Spirit creature token with flying.",
        card_name="Probe",
    )
    assert not looped.parse_error and not looped.lowering_error
    bare = _w1g8s_compile_line(
        "Destroy all creatures. Its controller creates a 1/1 white Spirit "
        "creature token with flying.",
        card_name="Probe",
    )
    assert bare.parse_error or bare.lowering_error
    assert not bare.instructions


# W1G8, supported on arrival and driven: Hull Breach.


def test_w1g8_hull_breach_destroys_by_mode(set_pool):
    """Three modes: an artifact, an enchantment, or one of each — and the
    third mode's two targets may sit on two different battlefields."""
    lea = _w1g8s_lea()
    breach = set_pool("PLS")["Hull Breach"]
    game, _, theirs = _w1g8s_duel(
        [], [lea["Sol Ring"], lea["Crusade"], lea["Hill Giant"]],
        hand0=[breach] * 2,
    )
    ring, crusade, giant = theirs

    assert game.cast_from_hand(
        0, "Hull Breach", mode_index=0, target_permanent_ids=[ring.permanent_id]
    ).supported
    _w1g8s_resolve_stack(game)
    assert not game.is_on_battlefield(ring)
    assert game.is_on_battlefield(crusade) and game.is_on_battlefield(giant)

    assert game.cast_from_hand(
        0, "Hull Breach", mode_index=1,
        target_permanent_ids=[crusade.permanent_id],
    ).supported
    _w1g8s_resolve_stack(game)
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Hill Giant"]

    game, mine, theirs = _w1g8s_duel(
        [lea["Sol Ring"]], [lea["Crusade"], lea["Hill Giant"]], hand0=[breach],
    )
    cast = game.cast_from_hand(
        0, "Hull Breach", mode_index=2,
        target_permanent_ids=[mine[0].permanent_id, theirs[0].permanent_id],
    )
    assert cast.supported, cast.details
    _w1g8s_resolve_stack(game)
    assert list(game.controlled_by(0)) == []
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Hill Giant"]


# --- W1G5: lands and mana ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_cast_spec as _w1g5_derive_cast_spec
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_implode_table(set_pool, *, mine=(), theirs=(), library=()):
    """Seat 0's main phase holding Implode, costs enforced. Names resolve in
    Planeshift, then Alpha."""
    pls, lea = set_pool("PLS"), set_pool("LEA")

    def card(name):
        return pls[name] if name in pls else lea[name]

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(name)) for name in mine],
        hand=[pls["Implode"]],
        library=[card(name) for name in library],
    )
    you = _W1G5PlayerState(
        name="W1G5-B",
        battlefield=[_W1G5Permanent(card=card(name)) for name in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    return game  # _w1g5_implode_table


def test_w1g5_implode_destroys_a_land_and_draws(set_pool):
    """"Destroy target land. Draw a card." Supported on arrival and never run.
    The picker asks for a land; five Mountains pay {4}{R}; a creature is not a
    legal target and nothing is spent on the refusal; the Lair is destroyed,
    the caster draws, and the mana is gone."""
    implode = set_pool("PLS")["Implode"]
    assert _w1g5_derive_cast_spec(implode, _w1g5_compile(implode)) == {"kind": "land"}

    game = _w1g5_implode_table(
        set_pool, mine=["Mountain"] * 5,
        theirs=["Crosis's Catacombs", "Grizzly Bears"], library=["Swamp"],
    )
    (lair,) = [p for p in game.controlled_by(1) if p.card.name == "Crosis's Catacombs"]
    (bears,) = [p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears"]

    def aimed_at(target):
        return game.cast_from_hand(
            0, "Implode", target_player_index=1,
            target_permanent_ids=[target.permanent_id],
        )

    assert not aimed_at(lair).supported, "nothing has paid for it"
    for mountain in list(game.controlled_by(0)):
        game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert not aimed_at(bears).supported
    assert sum(game.players[0].mana_pool.values()) == 5, "a refusal spends nothing"

    assert aimed_at(lair).supported
    _w1g5_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == ["Crosis's Catacombs"]
    assert [card.name for card in game.players[0].hand] == ["Swamp"]
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g5_implode_needs_a_land_to_name_and_fizzles_without_it(set_pool):
    """CR 601.2c: with no land on the battlefield there is no target to
    announce and the spell cannot be cast. CR 608.2b: when its one target has
    left by resolution it is removed from the stack and its second sentence
    is not performed — no card is drawn for destroying nothing."""
    empty = _w1g5_implode_table(set_pool, theirs=["Grizzly Bears"])
    empty.enforce_mana_costs = False
    assert not empty.cast_from_hand(0, "Implode").supported
    assert [card.name for card in empty.players[0].hand] == ["Implode"]

    game = _w1g5_implode_table(set_pool, theirs=["Forest"], library=["Swamp"])
    game.enforce_mana_costs = False
    (forest,) = list(game.controlled_by(1))
    assert game.queue_from_hand(
        0, "Implode", target_player_index=1,
        target_permanent_ids=[forest.permanent_id],
    ).supported
    game.remove_from_battlefield(forest)
    _w1g5_resolve_stack(game)

    assert game.players[0].hand == []
    assert [card.name for card in game.players[0].graveyard] == ["Implode"]


# --- W1G1: non-mana kicker ---
#
# "Kicker—Sacrifice two lands." (Bog Down), "Kicker—Sacrifice a creature."
# (Primal Growth), and Diabolic Intent's mandatory twin of the same cost.
# Imports are in this block, per the header's parallel-authorship convention.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.ai_policy import choose_cast_action as _w1g1_choose_cast_action
from engine.cast_costs import kicker_cost as _w1g1_kicker_cost
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}


def _w1g1_duel(set_pool, hand, *, library=None, their_hand=()):
    """A two-seat game that **charges mana**, seat 0 holding *hand* (PLS names)
    over *library* (LEA names, top first is the last entry's reverse — it is
    only ever searched here)."""
    pls, lea = set_pool("PLS"), set_pool("LEA")
    mine = _W1G1PlayerState(
        "Kicker",
        library=[lea[name] for name in (library or ["Forest"] * 10)],
        hand=[pls[name] for name in hand],
    )
    theirs = _W1G1PlayerState(
        "Bystander", library=[lea["Forest"]] * 10,
        hand=[lea[name] for name in their_hand],
    )
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G1_RICH)
    return game  # _w1g1_duel (sorceries)


def _w1g1_put(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (sorceries)


def _w1g1_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))  # _w1g1_names (sorceries)


def _w1g1_key(set_pool, name):
    return _w1g1_kicker_cost(set_pool("PLS")[name].oracle_text)  # _w1g1_key (sorceries)


# -- Bog Down ----------------------------------------------------------------


def _w1g1_bog_table(set_pool, swamps=3):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Bog Down"], their_hand=["Grizzly Bears"] * 5)
    lands = [_w1g1_put(game, 0, lea["Swamp"]) for _ in range(swamps)]
    return game, lands  # _w1g1_bog_table


def _w1g1_discard_owed(game) -> int:
    (choice,) = [c for c in game.pending_choices if c.kind == "discard"]
    assert choice.player_index == 1
    return choice.data["count"]  # _w1g1_discard_owed


def test_w1g1_bog_down_unkicked_makes_the_target_discard_two(set_pool):
    game, lands = _w1g1_bog_table(set_pool)
    assert game.cast_from_hand(0, "Bog Down", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert _w1g1_discard_owed(game) == 2
    assert len(_w1g1_names(game, 0)) == 3, "no kicker, no lands"


def test_w1g1_bog_down_kicked_is_three_cards_instead_not_two_then_three(set_pool):
    """"…that player discards three cards **instead**." Kicked, the target owes
    three — one prompt for three, not a prompt for two and another for three —
    and the two lands the caster **named** are the two that go."""
    game, lands = _w1g1_bog_table(set_pool)
    key = _w1g1_key(set_pool, "Bog Down")
    assert key == "sacrifice two lands"

    result = game.cast_from_hand(
        0, "Bog Down", target_player_index=1, optional_cost_payments={key: 1},
        cost_permanent_ids=[lands[0].permanent_id, lands[2].permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    assert _w1g1_discard_owed(game) == 3
    assert [p.permanent_id for p in game.controlled_by(0)] == [lands[1].permanent_id]

    assert game.confirm_discard(1, [0, 1, 2])
    assert len(game.players[1].hand) == 2 and len(game.players[1].graveyard) == 3


def test_w1g1_bog_down_cannot_be_kicked_with_one_land(set_pool):
    """One land is no more a payment of "sacrifice two lands" than none
    (CR 601.2h): refused with the land kept and the mana unspent, and the
    browser's offer says so from the same gate."""
    game, lands = _w1g1_bog_table(set_pool, swamps=1)
    key = _w1g1_key(set_pool, "Bog Down")
    [offer] = game.cast_cost_offers(0, set_pool("PLS")["Bog Down"])
    assert (offer["label"], offer["max_times"]) == ("kicker", 0)

    refused = game.cast_from_hand(
        0, "Bog Down", target_player_index=1, optional_cost_payments={key: 1}
    )
    assert not refused.supported and "601.2h" in refused.details
    assert game.is_on_battlefield(lands[0])
    assert sum(game.players[0].mana_pool.values()) == sum(_W1G1_RICH.values())


def test_w1g1_the_kicked_bog_down_asks_for_two_lands_and_the_plain_one_for_none(set_pool):
    game, lands = _w1g1_bog_table(set_pool)
    card = set_pool("PLS")["Bog Down"]
    key = _w1g1_key(set_pool, "Bog Down")
    assert "cost_spec" not in game.cast_target_spec(0, card, optional_cost_payments={})
    kicked = game.cast_target_spec(0, card, optional_cost_payments={key: 1})
    cost = kicked["cost_spec"]
    assert (cost["kind"], cost["sacrifice_cost"], cost["count"]) == ("land", True, 2)
    assert len(cost["valid_targets"]) == 3
    assert kicked["kind"] == "player", "the target is still a player either way"


# -- Primal Growth -----------------------------------------------------------

#: Two basics, a nonbasic land and two non-lands: what "a basic land card" may
#: and may not find.
_W1G1_GROWTH_LIBRARY = ["Forest", "Grizzly Bears", "Island", "Sol Ring", "Bayou"]


def test_w1g1_primal_growth_unkicked_fetches_one_basic_land(set_pool):
    game = _w1g1_duel(set_pool, ["Primal Growth"], library=_W1G1_GROWTH_LIBRARY)
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    assert game.cast_from_hand(0, "Primal Growth").supported
    _w1g1_resolve_stack(game)

    prompt = game.pending_search_library
    assert prompt["count"] == 1 and not prompt["up_to"]
    assert not game.confirm_search_library(0, 4), "Bayou is a land, and not basic"
    assert game.confirm_search_library(0, 2)
    game._settle()
    assert _w1g1_names(game, 0) == ["Grizzly Bears", "Island"]
    assert game.is_on_battlefield(bears), "no kicker, no sacrifice"
    assert game.pending_search_library is None


def test_w1g1_primal_growth_kicked_fetches_up_to_two_instead(set_pool):
    """"If this spell was kicked, **instead** search your library for up to two
    basic land cards…" The fronted spelling of the "instead" pair: one search
    for up to two, in place of the search for one — and the creature the
    caster named is the price."""
    game = _w1g1_duel(set_pool, ["Primal Growth"], library=_W1G1_GROWTH_LIBRARY)
    lea = set_pool("LEA")
    kept = _w1g1_put(game, 0, lea["Hill Giant"])
    named = _w1g1_put(game, 0, lea["Grizzly Bears"])
    key = _w1g1_key(set_pool, "Primal Growth")
    assert key == "sacrifice a creature"

    result = game.cast_from_hand(
        0, "Primal Growth", optional_cost_payments={key: 1},
        cost_permanent_ids=[named.permanent_id],
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(named) and game.is_on_battlefield(kept)
    _w1g1_resolve_stack(game)

    prompt = game.pending_search_library
    assert prompt["count"] == 2 and prompt["up_to"]
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": 0}, {"zone": "library", "index": 2}]
    )
    game._settle()
    assert _w1g1_names(game, 0) == ["Forest", "Hill Giant", "Island"]
    assert game.pending_search_library is None, "one search, not one and then two"
    assert sorted(c.name for c in game.players[0].library) == [
        "Bayou", "Grizzly Bears", "Sol Ring",
    ]


def test_w1g1_primal_growth_cannot_be_kicked_without_a_creature(set_pool):
    game = _w1g1_duel(set_pool, ["Primal Growth"], library=_W1G1_GROWTH_LIBRARY)
    key = _w1g1_key(set_pool, "Primal Growth")
    refused = game.cast_from_hand(0, "Primal Growth", optional_cost_payments={key: 1})
    assert not refused.supported and "601.2h" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Primal Growth"]

    # …and a kicked cast with one raises a sacrifice picker over the caster's
    # own creatures, which the plain cast does not.
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    _w1g1_put(game, 1, set_pool("LEA")["Hill Giant"])
    card = set_pool("PLS")["Primal Growth"]
    assert game.cast_target_spec(0, card, optional_cost_payments={})["kind"] == "none"
    kicked = game.cast_target_spec(0, card, optional_cost_payments={key: 1})
    assert kicked["sacrifice_cost"] and kicked["kind"] == "creature"
    assert [
        game.permanent_at(t["seat"], t["index"]).permanent_id
        for t in kicked["valid_targets"]
    ] == [bears.permanent_id]


# -- Diabolic Intent ---------------------------------------------------------


def test_w1g1_diabolic_intent_sacrifices_a_creature_and_tutors(set_pool):
    """"As an additional cost to cast this spell, sacrifice a creature." The
    mandatory twin of the kicker's cost: paid as the spell is cast, then a
    search for any card into hand."""
    game = _w1g1_duel(
        set_pool, ["Diabolic Intent"], library=["Forest", "Black Lotus", "Island"]
    )
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    before = sum(game.players[0].mana_pool.values())

    result = game.queue_from_hand(
        0, "Diabolic Intent", cost_permanent_ids=[bears.permanent_id]
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(bears), "paid on the way to the stack"
    assert before - sum(game.players[0].mana_pool.values()) == 2
    _w1g1_resolve_stack(game)

    assert game.confirm_search_library(0, 1)
    game._settle()
    assert [c.name for c in game.players[0].hand] == ["Black Lotus"]


def test_w1g1_diabolic_intent_is_refused_unpaid_with_no_creature(set_pool):
    """CR 601.2h: no creature, no cast — the mana stays, the card stays, and
    the AI does not propose it."""
    game = _w1g1_duel(set_pool, ["Diabolic Intent"])
    refused = game.cast_from_hand(0, "Diabolic Intent")
    assert not refused.supported and "601.2h" in refused.details
    assert sum(game.players[0].mana_pool.values()) == sum(_W1G1_RICH.values())
    assert [c.name for c in game.players[0].hand] == ["Diabolic Intent"]
    assert _w1g1_choose_cast_action(game, 0) is None


def test_w1g1_diabolic_intent_resolves_when_its_payer_was_also_named_as_a_target(set_pool):
    """A spell with no target is not countered for an illegal one. Diabolic
    Intent's whole spec is its cost picker, so an id on the *target* channel
    names nothing the spell targets — but CR 608.2b's gate judged it as a
    target, found the sacrificed creature gone, and removed the spell with its
    cost paid. That is how the AI announced it, in a simulated game."""
    game = _w1g1_duel(
        set_pool, ["Diabolic Intent"], library=["Forest", "Black Lotus", "Island"]
    )
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    result = game.cast_from_hand(
        0, "Diabolic Intent", target_player_index=0, target_permanent_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    assert not any("every target is illegal" in line for line in game.log)
    assert game.pending_search_library is not None, "it resolved: the search is owed"


def test_w1g1_the_ai_casts_diabolic_intent_without_naming_its_payer_a_target(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Diabolic Intent"])
    game.players[0].mana_pool.clear()
    for _ in range(2):
        _w1g1_put(game, 0, lea["Swamp"])
    _w1g1_put(game, 0, lea["Grizzly Bears"])
    game.active_player_index = 0
    game.current_phase = "main"

    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Diabolic Intent"
    assert not action.target_permanent_ids


# --- W1G4: domain ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from tests.helpers import resolve_stack as _w1g4_resolve

_W1G4_FIVE = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _w1g4_board_card(set_pool, name):
    """A board permanent's card: Alpha's lands and bodies, else Antiquities
    (Mishra's Factory, a land with no basic land type) — pools kept separate
    and asked in that order."""
    for w1g4_code in ("LEA", "ATQ"):
        if name in set_pool(w1g4_code):
            return set_pool(w1g4_code)[name]
    raise KeyError(name)  # _w1g4_board_card


def _w1g4_sorcery_table(set_pool, spell, mine=(), theirs=(), interactive=()):
    """*spell* in seat 0's hand over two boards named in board order, each
    seat with a library to draw from (a draw off an empty one loses the game
    and would hide what the spell did)."""
    w1g4_pls, w1g4_lea = set_pool("PLS"), set_pool("LEA")
    w1g4_game = _W1G4Game(players=[
        _W1G4PlayerState(name="W1G4-A", hand=[w1g4_pls[spell]]),
        _W1G4PlayerState(name="W1G4-B"),
    ])
    w1g4_game.enforce_mana_costs = False
    w1g4_game.active_player_index = 0
    w1g4_game.interactive_seats = set(interactive)
    for w1g4_player in w1g4_game.players:
        w1g4_player.library = [w1g4_lea["Grizzly Bears"]] * 20
    w1g4_rows = []
    for w1g4_seat, w1g4_names in enumerate((mine, theirs)):
        w1g4_row = []
        for w1g4_name in w1g4_names:
            w1g4_perm = _W1G4Permanent(card=_w1g4_board_card(set_pool, w1g4_name))
            w1g4_game._put_permanent_onto_battlefield(w1g4_seat, w1g4_perm, None)
            w1g4_row.append(w1g4_perm)
        w1g4_rows.append(w1g4_row)
    return w1g4_game, w1g4_rows[0], w1g4_rows[1]  # _w1g4_sorcery_table


def _w1g4_land_names(game, seat):
    return sorted(
        w1g4_perm.card.name for w1g4_perm in game.controlled_by(seat)
    )  # _w1g4_land_names


def test_w1g4_allied_strategies_offers_a_player(set_pool):
    card = set_pool("PLS")["Allied Strategies"]
    program = _w1g4_compile(card)
    assert program.supported, program.reason
    assert _w1g4_cast_spec(card, program) == {"kind": "player"}


def test_w1g4_allied_strategies_counts_the_targets_lands_not_the_casters(set_pool):
    """"Target player draws a card for each basic land type among lands
    **they** control." Aimed at an opponent holding three types on four lands
    it draws them three, whatever the caster's five types are."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", mine=_W1G4_FIVE,
        theirs=["Forest", "Forest", "Tropical Island", "Mountain"],
    )
    cast = game.cast_from_hand(0, "Allied Strategies", target_player_index=1)
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    assert [len(player.hand) for player in game.players] == [0, 3]
    assert "W1G4-B drew 3 cards" in game.log


def test_w1g4_allied_strategies_aimed_at_its_caster_draws_their_domain(set_pool):
    """The same sentence with the caster as the target: five types, five
    cards — and the opponent's single Forest is nobody's draw."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", mine=_W1G4_FIVE, theirs=["Forest"],
    )
    assert game.cast_from_hand(0, "Allied Strategies", target_player_index=0).supported
    _w1g4_resolve(game)
    assert [len(player.hand) for player in game.players] == [5, 0]


def test_w1g4_allied_strategies_counts_at_resolution_and_types_not_lands(set_pool):
    """CR 608.2h: counted once, as the spell resolves — a dual land that
    arrives while it is on the stack adds its two types, and four Forests
    beside it are still one."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", theirs=["Forest"] * 4,
    )
    assert game.queue_from_hand(0, "Allied Strategies", target_player_index=1).supported
    game._put_permanent_onto_battlefield(
        1, _W1G4Permanent(card=set_pool("LEA")["Badlands"]), None
    )
    _w1g4_resolve(game)
    assert len(game.players[1].hand) == 3

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", mine=_W1G4_FIVE,
    )
    assert game.cast_from_hand(0, "Allied Strategies", target_player_index=1).supported
    _w1g4_resolve(game)
    assert [len(player.hand) for player in game.players] == [0, 0], (
        "a target with no lands draws nothing"
    )


def test_w1g4_they_control_binds_only_to_a_chosen_player():
    """The rewrite is for the player the sentence *targeted*. "Each player …
    they control" and "you … they control" name no chosen seat, and the count
    refuses rather than falling back to whichever board the resolution held."""
    from engine.grammar import compile_line

    bound = compile_line("Target opponent draws a card for each creature they control.")
    assert bound.usable
    assert bound.instructions[0].payload["x_from_count"]["owner"] == "target_player"
    for line in (
        "Each player draws a card for each land they control.",
        "You draw a card for each land they control.",
    ):
        assert not compile_line(line).usable, line


def test_w1g4_planar_overlay_names_no_target(set_pool):
    card = set_pool("PLS")["Planar Overlay"]
    program = _w1g4_compile(card)
    assert program.supported, program.reason
    assert _w1g4_cast_spec(card, program) is None


def test_w1g4_planar_overlay_each_player_returns_one_land_per_basic_type(set_pool):
    """"Each player chooses a land they control of each basic land type.
    Return those lands to their owners' hands." A headless table takes the
    largest choice in board order: one Plains of two, the Forest, and the
    Tropical Island as the Island. The spare Plains, a land with no basic type
    and everything that is not a land stay where they are, and nothing is
    sacrificed — this is Global Ruin's choice with the other half moving."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay",
        mine=["Plains", "Plains", "Forest", "Tropical Island", "Grizzly Bears",
              "Mishra's Factory"],
        theirs=["Mountain", "Mountain", "Island", "Black Lotus"],
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert _w1g4_land_names(game, 0) == ["Grizzly Bears", "Mishra's Factory", "Plains"]
    assert _w1g4_land_names(game, 1) == ["Black Lotus", "Mountain"]
    assert sorted(c.name for c in game.players[0].hand) == [
        "Forest", "Plains", "Tropical Island",
    ]
    assert sorted(c.name for c in game.players[1].hand) == ["Island", "Mountain"]
    assert [c.name for c in game.players[0].graveyard] == ["Planar Overlay"]
    assert not game.players[1].graveyard
    assert (
        "W1G4-B returned Mountain, Island to their owners' hands (Planar Overlay)"
        in game.log
    )


def test_w1g4_planar_overlay_a_dual_land_is_chosen_for_one_type(set_pool):
    """A Tropical Island is a Forest and an Island and is *the* land for one
    of them — the constraint Global Ruin's keep has, on the same matching.
    Alone it is the only land returned; beside a Forest it is the Island and
    both go; five duals can each stand for a different type and all return."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Tropical Island", "Mishra's Factory"],
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Tropical Island"]

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Forest", "Tropical Island"],
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert not _w1g4_land_names(game, 0)

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay",
        mine=["Forest", "Tropical Island", "Tundra", "Badlands", "Taiga", "Forest"],
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert _w1g4_land_names(game, 0) == ["Forest"], "six lands, five types"


def test_w1g4_planar_overlay_asks_the_player_and_checks_the_answer(set_pool):
    """The choice is a decision each seat owes (CR 608.2d), and the spell
    stays on the stack until it is made. Two Plains cannot both be chosen —
    there is one Plains — a short list is refused, and so is a land of no
    basic type; the prompt says which fate it is deciding."""
    game, mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay",
        mine=["Plains", "Plains", "Tropical Island", "Forest", "Swamp",
              "Mishra's Factory"],
        theirs=["Mountain"], interactive=(0,),
    )
    plains_a, plains_b, tropical, forest, swamp, factory = (
        p.permanent_id for p in mine
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index, c.data["fate"]) for c in game.pending_choices] == [
        ("keep_permanents", 0, "return_chosen_to_hand")
    ]
    assert game.stack and game.waiting_prompt() is not None
    # The seat that is not interactive has already chosen and returned.
    assert [c.name for c in game.players[1].hand] == ["Mountain"]

    assert not game.confirm_keep_permanents(0, [plains_a, plains_b, tropical, forest])
    assert not game.confirm_keep_permanents(0, [plains_a])
    assert not game.confirm_keep_permanents(0, [plains_a, tropical, forest, factory])
    assert [c.kind for c in game.pending_choices] == ["keep_permanents"]
    assert len(list(game.controlled_by(0))) == 6, "a refused answer moves nothing"

    # The second Plains, the Tropical Island as the Island, Forest, Swamp.
    assert game.confirm_keep_permanents(0, [plains_b, tropical, forest, swamp])
    _w1g4_resolve(game)
    assert _w1g4_land_names(game, 0) == ["Mishra's Factory", "Plains"]
    assert game.is_on_battlefield(mine[0]) and not game.is_on_battlefield(mine[1])
    assert sorted(c.name for c in game.players[0].hand) == [
        "Forest", "Plains", "Swamp", "Tropical Island",
    ]


def test_w1g4_planar_overlay_returns_a_land_to_its_owners_hand(set_pool):
    """"…to their **owners'** hands" (CR 400.3): a land this seat controls and
    another seat owns is this seat's to choose and that seat's to pick up."""
    from engine.control import change_control

    game, mine, theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Forest"], theirs=["Island"],
    )
    change_control(theirs[0], 0, source=mine[0])
    game._sync_control()
    assert _w1g4_land_names(game, 0) == ["Forest", "Island"]
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Forest"]
    assert [c.name for c in game.players[1].hand] == ["Island"]
    assert not list(game.controlled_by(0)) and not list(game.controlled_by(1))


def test_w1g4_planar_overlay_asks_nobody_with_no_basic_land_type(set_pool):
    """A seat none of whose lands has a basic land type has nothing to choose
    and nothing to return, and is not prompted; and the count is of computed
    types — under Blood Moon a Mishra's Factory is a Mountain and goes back."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Mishra's Factory"],
        theirs=["Grizzly Bears"], interactive=(0, 1),
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert not game.pending_choices and not game.stack
    assert _w1g4_land_names(game, 0) == ["Mishra's Factory"]

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Mishra's Factory"],
    )
    game._put_permanent_onto_battlefield(
        1, _W1G4Permanent(card=set_pool("DRK")["Blood Moon"]), None
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Mishra's Factory"]


def test_w1g4_the_return_fate_is_the_whole_paragraph_or_nothing(set_pool):
    """The choice with no fate behind it, or with "those" naming a different
    noun, is not this production's — a card that prompted every seat and then
    moved nothing would report supported. And Global Ruin, which shares the
    chooser, still carries no ``fate`` key: its payload is byte-identical."""
    from engine.grammar import compile_line

    chosen = "Each player chooses a land they control of each basic land type."
    whole = compile_line(f"{chosen} Return those lands to their owners' hands.")
    assert whole.usable
    assert whole.instructions[0].payload["fate"] == "return_chosen_to_hand"
    assert [slot["filter"]["subtype_filter"] for slot in whole.instructions[0].payload["slots"]] == [
        "plains", "island", "swamp", "mountain", "forest",
    ]
    for line in (
        chosen,
        f"{chosen} Return those creatures to their owners' hands.",
        f"{chosen} Return those lands to your hand.",
    ):
        assert not compile_line(line).usable, line
    ruin = _w1g4_compile(set_pool("INV")["Global Ruin"])
    assert "fate" not in ruin.instructions[0].payload


def test_w1g4_planar_overlay_prompt_reaches_the_client_as_a_return(set_pool):
    """Through the real action endpoint: the cast, the priority pass that
    resolves it, the prompt the state carries, and the answer. The payload
    names the fate so the modal can say "return" rather than "keep", offers
    only the lands a slot could take (not the Factory, not the Bears), and the
    count is the matching's — three, for two Plains, a Tropical Island and a
    Forest. A selection the engine refuses is a 400 and moves nothing."""
    from fastapi.testclient import TestClient

    from web.app import app, store

    client = TestClient(app)
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "W1G4", "host_colors": 2,
        "guest_colors": 2, "seed": 4104,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    session = store.get(session_id)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    game.players[0].hand[:] = [set_pool("PLS")["Planar Overlay"]]
    board = []
    for name in ("Plains", "Plains", "Tropical Island", "Forest",
                 "Mishra's Factory", "Grizzly Bears"):
        perm = _W1G4Permanent(card=_w1g4_board_card(set_pool, name))
        game._put_permanent_onto_battlefield(0, perm, None)
        board.append(perm)
    game.start_priority_window(0)

    def act(**body):
        return client.post(
            f"/api/sessions/{session_id}/action", json={"seat": 0, **body}
        )

    def prompt():
        return client.get(
            f"/api/sessions/{session_id}/state", params={"seat": 0}
        ).json().get("keep_permanents")

    assert act(action="cast", card_name="Planar Overlay").status_code == 200
    assert act(action="pass_priority").status_code == 200
    offered = prompt()
    assert offered["fate"] == "return_chosen_to_hand"
    assert offered["keep_count"] == 3
    assert [entry["name"] for entry in offered["candidates"]] == [
        "Plains", "Plains", "Tropical Island", "Forest",
    ]
    plains_a, plains_b, tropical, forest = (p.permanent_id for p in board[:4])

    refused = act(
        action="keep_permanents_confirm",
        target_permanent_ids=[plains_a, plains_b, tropical],
    )
    assert refused.status_code == 400
    assert len(list(game.controlled_by(0))) == 6

    assert act(
        action="keep_permanents_confirm",
        target_permanent_ids=[plains_b, tropical, forest],
    ).status_code == 200
    assert prompt() is None
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Grizzly Bears", "Mishra's Factory", "Plains",
    ]
    assert sorted(c.name for c in game.players[0].hand) == [
        "Forest", "Plains", "Tropical Island",
    ]


# -- supported on arrival: driven, not built ----------------------------------


def test_w1g4_exotic_disease_drains_by_its_casters_domain(set_pool):
    """"Target player loses X life and you gain X life, where X is the number
    of basic land types among lands you control." Three lands holding five
    types drain five, whatever the target controls; the two halves read one X,
    so aimed at its own caster the spell is a wash."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Exotic Disease",
        mine=["Plains", "Tropical Island", "Badlands"], theirs=["Forest"],
    )
    cast = game.cast_from_hand(0, "Exotic Disease", target_player_index=1)
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    assert [player.life for player in game.players] == [25, 15]
    assert "Exotic Disease: W1G4-B lost 5 life (20 -> 15)" in game.log

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Exotic Disease", mine=["Forest", "Swamp"], theirs=_W1G4_FIVE,
    )
    assert game.cast_from_hand(0, "Exotic Disease", target_player_index=0).supported
    _w1g4_resolve(game)
    assert [player.life for player in game.players] == [20, 20]


def test_w1g4_exotic_disease_counts_at_resolution(set_pool):
    """CR 608.2h: X is the caster's board as the spell resolves — a dual land
    arriving while it is on the stack adds its two types — and a caster with
    no land drains nothing."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Exotic Disease", mine=["Forest"],
    )
    assert game.queue_from_hand(0, "Exotic Disease", target_player_index=1).supported
    game._put_permanent_onto_battlefield(
        0, _W1G4Permanent(card=set_pool("LEA")["Tundra"]), None
    )
    _w1g4_resolve(game)
    assert [player.life for player in game.players] == [23, 17]

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Exotic Disease", theirs=_W1G4_FIVE,
    )
    assert game.cast_from_hand(0, "Exotic Disease", target_player_index=1).supported
    _w1g4_resolve(game)
    assert [player.life for player in game.players] == [20, 20]
