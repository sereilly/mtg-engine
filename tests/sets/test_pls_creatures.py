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


# --- W1G1: non-mana kicker ---
#
# "Kicker—Return a creature you control to its owner's hand." / "Kicker—Pay 3
# life." CR 702.33a: "Kicker [cost]" means "You may pay an additional [cost] as
# you cast this spell", and the cost need not be mana. Imports are in this
# block, per the header's parallel-authorship convention.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.ai_policy import choose_cast_action as _w1g1_choose_cast_action
from engine.cast_costs import KICKED as _W1G1_KICKED
from engine.cast_costs import additional_costs as _w1g1_additional_costs
from engine.cast_costs import kicker_cost as _w1g1_kicker_cost
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}


def _w1g1_duel(set_pool, hand, pool=None):
    """A two-seat game that **charges mana**, seat 0 holding *hand* (PLS names)
    with *pool* floating. Costs are enforced because a kicker is a price: a rig
    that waives mana cannot tell a kicked cast from a free one."""
    pls = set_pool("PLS")
    forest = set_pool("LEA")["Forest"]
    mine = _W1G1PlayerState(
        "Kicker", library=[forest] * 10, hand=[pls[name] for name in hand],
    )
    theirs = _W1G1PlayerState("Bystander", library=[forest] * 10)
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G1_RICH if pool is None else pool)
    return game  # _w1g1_duel (creatures)


def _w1g1_put(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (creatures)


def _w1g1_floating(game) -> int:
    return sum(game.players[0].mana_pool.values())  # _w1g1_floating (creatures)


def _w1g1_named(game, seat, name):
    return next(
        (p for p in game.controlled_by(seat) if p.card.name == name), None
    )  # _w1g1_named (creatures)


def test_w1g1_a_kicker_line_behind_an_em_dash_is_one_optional_cost(set_pool):
    """The rewrite, and the one string it turns on. The key the announcement is
    accepted under, the key the payment charges by and the key `kicked` reads
    back are all the cost's own ``optional_key`` — two spellings of one cost is
    a spell that paid its kicker and resolved unkicked."""
    pls = set_pool("PLS")
    for name, key in (
        ("Arctic Merfolk", "return a creature you control to its owner's hand"),
        ("Phyrexian Scuta", "pay 3 life"),
    ):
        card = pls[name]
        (cost,) = _w1g1_additional_costs(card)
        assert cost.optional_key == key
        assert _w1g1_kicker_cost(card.oracle_text) == key
        assert not cost.optional_mana, "nothing here is folded into the mana"


def test_w1g1_arctic_merfolk_kicked_returns_the_creature_its_caster_names(set_pool):
    """Kicked: the creature the caster **names** goes back to its owner's hand
    as the spell is cast (a cost, CR 601.2h — before the Merfolk exists), and
    the Merfolk enters with a +1/+1 counter. Two creatures are on the table so
    that naming one means something."""
    card = set_pool("PLS")["Arctic Merfolk"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Arctic Merfolk"])
    lea = set_pool("LEA")
    kept = _w1g1_put(game, 0, lea["Grizzly Bears"])
    named = _w1g1_put(game, 0, lea["Hill Giant"])
    before = _w1g1_floating(game)

    result = game.queue_from_hand(
        0, "Arctic Merfolk", optional_cost_payments={key: 1},
        cost_permanent_ids=[named.permanent_id],
    )
    assert result.supported, result.details
    assert [c.name for c in game.players[0].hand] == ["Hill Giant"]
    assert _w1g1_named(game, 0, "Arctic Merfolk") is None, "still a spell"
    _w1g1_resolve_stack(game)

    merfolk = _w1g1_named(game, 0, "Arctic Merfolk")
    assert (merfolk.effective_power, merfolk.effective_toughness) == (2, 2)
    assert int(merfolk.metadata.get("plus_counters", 0)) == 1
    assert merfolk.metadata.get(_W1G1_KICKED)
    assert game.is_on_battlefield(kept)
    assert before - _w1g1_floating(game) == 2, "{1}{U} and no mana for the kicker"
    assert "Kicker kicked Arctic Merfolk" in game.log


def test_w1g1_arctic_merfolk_unkicked_is_a_one_one_and_returns_nothing(set_pool):
    """An offer is not a price (CR 601.2b): declined, the creature beside it
    stays and the Merfolk is the printed 1/1."""
    game = _w1g1_duel(set_pool, ["Arctic Merfolk"])
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    assert game.cast_from_hand(0, "Arctic Merfolk").supported
    _w1g1_resolve_stack(game)

    merfolk = _w1g1_named(game, 0, "Arctic Merfolk")
    assert (merfolk.effective_power, merfolk.effective_toughness) == (1, 1)
    assert not merfolk.metadata.get(_W1G1_KICKED)
    assert game.is_on_battlefield(bears) and not game.players[0].hand


def test_w1g1_arctic_merfolk_cannot_be_kicked_with_no_creature_to_return(set_pool):
    """CR 601.2h: an unpayable cost is an uncastable spell, never a free kick —
    refused with the mana still floating and the card still in hand. And the
    offer the browser is shown says so (``max_times`` 0), from the same gate."""
    card = set_pool("PLS")["Arctic Merfolk"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Arctic Merfolk"])
    before = _w1g1_floating(game)

    [offer] = game.cast_cost_offers(0, card)
    assert (offer["label"], offer["symbols"], offer["max_times"]) == ("kicker", key, 0)
    refused = game.cast_from_hand(
        0, "Arctic Merfolk", optional_cost_payments={key: 1}
    )
    assert not refused.supported and "601.2h" in refused.details
    assert _w1g1_floating(game) == before
    assert [c.name for c in game.players[0].hand] == ["Arctic Merfolk"]

    _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    [offer] = game.cast_cost_offers(0, card)
    assert offer["max_times"] == 1


def test_w1g1_the_kicked_cast_asks_which_creature_and_the_plain_one_does_not(set_pool):
    """The picker (CR 601.2b): a kicked Arctic Merfolk raises a *return* cost
    picker over the caster's own creatures, and a declined kicker raises none —
    a caster who is not kicking must not be asked to name a creature."""
    card = set_pool("PLS")["Arctic Merfolk"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Arctic Merfolk"])
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    _w1g1_put(game, 1, set_pool("LEA")["Hill Giant"])
    _w1g1_put(game, 0, set_pool("LEA")["Forest"])

    plain = game.cast_target_spec(0, card, optional_cost_payments={})
    assert plain["kind"] == "none" and not plain.get("return_cost")

    kicked = game.cast_target_spec(0, card, optional_cost_payments={key: 1})
    assert kicked["kind"] == "creature" and kicked["return_cost"]
    assert [
        game.permanent_at(t["seat"], t["index"]).permanent_id
        for t in kicked["valid_targets"]
    ] == [bears.permanent_id], "the caster's own creatures and nothing else"


def test_w1g1_phyrexian_scuta_kicked_pays_three_life_for_two_counters(set_pool):
    """"Kicker—Pay 3 life." A 3/3 for {3}{B}, or a 5/5 for {3}{B} and 3 life:
    real counters, the life paid as the spell is cast, and no extra mana."""
    card = set_pool("PLS")["Phyrexian Scuta"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Phyrexian Scuta"])
    before = _w1g1_floating(game)

    result = game.queue_from_hand(
        0, "Phyrexian Scuta", optional_cost_payments={key: 1}
    )
    assert result.supported, result.details
    assert game.players[0].life == 17, "paid on the way to the stack, not at resolution"
    _w1g1_resolve_stack(game)

    scuta = _w1g1_named(game, 0, "Phyrexian Scuta")
    assert (scuta.effective_power, scuta.effective_toughness) == (5, 5)
    assert int(scuta.metadata.get("plus_counters", 0)) == 2
    assert before - _w1g1_floating(game) == 4


def test_w1g1_phyrexian_scuta_unkicked_keeps_its_life_and_its_printed_body(set_pool):
    game = _w1g1_duel(set_pool, ["Phyrexian Scuta"])
    assert game.cast_from_hand(0, "Phyrexian Scuta").supported
    _w1g1_resolve_stack(game)
    scuta = _w1g1_named(game, 0, "Phyrexian Scuta")
    assert (scuta.effective_power, scuta.effective_toughness) == (3, 3)
    assert game.players[0].life == 20
    assert not scuta.metadata.get(_W1G1_KICKED)


def test_w1g1_phyrexian_scuta_cannot_be_kicked_with_two_life(set_pool):
    """CR 119.4: life can be paid only down to 0, so 2 life cannot pay 3 — and
    CR 601.2h makes that a refused cast with nothing spent. Three life can."""
    card = set_pool("PLS")["Phyrexian Scuta"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Phyrexian Scuta"])
    game.players[0].life = 2
    before = _w1g1_floating(game)

    [offer] = game.cast_cost_offers(0, card)
    assert offer["max_times"] == 0
    refused = game.cast_from_hand(0, "Phyrexian Scuta", optional_cost_payments={key: 1})
    assert not refused.supported and "601.2h" in refused.details
    assert (game.players[0].life, _w1g1_floating(game)) == (2, before)

    game.players[0].life = 3
    assert game.queue_from_hand(
        0, "Phyrexian Scuta", optional_cost_payments={key: 1}
    ).supported
    assert game.players[0].life == 0


def test_w1g1_a_scuta_nothing_cast_was_not_kicked(set_pool):
    """Put onto the battlefield without being cast: no CR 601.2b, so no kicker
    and no counters, whatever its controller's life total could have paid."""
    game = _w1g1_duel(set_pool, [])
    scuta = _w1g1_put(game, 0, set_pool("PLS")["Phyrexian Scuta"])
    assert (scuta.effective_power, scuta.effective_toughness) == (3, 3)
    assert game.players[0].life == 20


def _w1g1_ai_board(set_pool, name, *, swamps, life=20):
    """Seat 0 on its own main phase holding *name*, with *swamps* untapped
    Swamps and an empty pool — the AI has to plan its own taps."""
    game = _w1g1_duel(set_pool, [name], pool={})
    for _ in range(swamps):
        _w1g1_put(game, 0, set_pool("LEA")["Swamp"])
    game.players[0].life = life
    game.active_player_index = 0
    game.current_phase = "main"
    return game  # _w1g1_ai_board (creatures)


def test_w1g1_the_ai_kicks_a_scuta_only_with_life_to_spare(set_pool):
    """The policy for a kicker that is not mana is the buyback one, by the
    *resource*: life is spent while the reserve still stands after it. At 20
    the seat kicks; at 12 it casts the plain 3/3 rather than drop to 9 — and
    it still casts, because declining an offer is not declining the spell."""
    card = set_pool("PLS")["Phyrexian Scuta"]
    key = _w1g1_kicker_cost(card.oracle_text)

    healthy = _w1g1_choose_cast_action(_w1g1_ai_board(set_pool, card.name, swamps=4), 0)
    assert healthy is not None and healthy.card_name == "Phyrexian Scuta"
    assert healthy.optional_cost_payments == {key: 1}

    hurt = _w1g1_choose_cast_action(
        _w1g1_ai_board(set_pool, card.name, swamps=4, life=12), 0
    )
    assert hurt is not None and hurt.card_name == "Phyrexian Scuta"
    assert not hurt.optional_cost_payments


# -- Dralnu's Pet: a kicker with two clauses, and a count read off the cost --


def _w1g1_pet_duel(set_pool, others, pool):
    """Seat 0 holds Dralnu's Pet and *others* (LEA names) with *pool* floating."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Dralnu's Pet"], pool=pool)
    game.players[0].hand.extend(lea[name] for name in others)
    return game  # _w1g1_pet_duel


_W1G1_PET_POOL = {"U": 10, "B": 10}


def test_w1g1_dralnus_pet_kicker_is_one_offer_of_mana_and_a_creature_card(set_pool):
    """"Kicker—{2}{B}, Discard a creature card." One offer with two clauses:
    the mana is a clause of the price, not a second offer a caster could take
    without the discard — so it is ``mana_symbols`` on the cost that carries
    the key, and ``optional_mana`` stays empty."""
    card = set_pool("PLS")["Dralnu's Pet"]
    (cost,) = _w1g1_additional_costs(card)
    assert cost.optional_key == _w1g1_kicker_cost(card.oracle_text)
    assert cost.mana_symbols == "{2}{B}" and cost.mana_cost == {"generic": 2, "B": 1}
    assert (cost.discard_cards, cost.discard_filters) == (1, ({"type_filter": "creature"},))
    assert not cost.optional_mana


def test_w1g1_dralnus_pet_kicked_flies_with_the_discarded_cards_mana_value(set_pool):
    """Kicked by discarding Hill Giant (mana value 4): six mana in all, the
    Giant in the graveyard — the card the caster **named**, with a cheaper
    creature card beside it — and a 6/6 flier with four real counters that
    still flies after the turn ends."""
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_pet_duel(
        set_pool, ["Lightning Bolt", "Grizzly Bears", "Hill Giant"], _W1G1_PET_POOL
    )

    result = game.queue_from_hand(
        0, "Dralnu's Pet", optional_cost_payments={key: 1}, cost_hand_index=3,
    )
    assert result.supported, result.details
    assert [c.name for c in game.players[0].graveyard] == ["Hill Giant"]
    _w1g1_resolve_stack(game)

    pet = _w1g1_named(game, 0, "Dralnu's Pet")
    assert (pet.effective_power, pet.effective_toughness) == (6, 6)
    assert int(pet.metadata.get("plus_counters", 0)) == 4
    assert game._has_keyword(pet, "flying")
    assert sum(_W1G1_PET_POOL.values()) - _w1g1_floating(game) == 6
    assert [c.name for c in game.players[0].hand] == ["Lightning Bolt", "Grizzly Bears"]

    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert game._has_keyword(pet, "flying"), "no duration: it lasts while the Pet does"
    assert "flying" not in {k.lower() for k in pet.card.keywords}, "a grant, not the card"


def test_w1g1_dralnus_pet_unkicked_is_a_two_two_that_does_not_fly(set_pool):
    """The word "flying" sits in a line about being kicked. An unkicked Pet
    must not have it (the failure Invasion's Faerie Squadron had), discards
    nothing and costs {1}{U}{U}."""
    game = _w1g1_pet_duel(set_pool, ["Hill Giant"], _W1G1_PET_POOL)
    assert game.cast_from_hand(0, "Dralnu's Pet").supported
    _w1g1_resolve_stack(game)

    pet = _w1g1_named(game, 0, "Dralnu's Pet")
    assert (pet.effective_power, pet.effective_toughness) == (2, 2)
    assert not game._has_keyword(pet, "flying")
    assert [c.name for c in game.players[0].hand] == ["Hill Giant"]
    assert sum(_W1G1_PET_POOL.values()) - _w1g1_floating(game) == 3

    put = _w1g1_put(game, 1, set_pool("PLS")["Dralnu's Pet"])
    assert (put.effective_power, put.effective_toughness) == (2, 2)
    assert not game._has_keyword(put, "flying"), "not cast, so not kicked"


def test_w1g1_dralnus_pet_kicked_with_a_free_creature_flies_and_gets_nothing(set_pool):
    """X is the discarded card's mana value, and 0 is a mana value: the Pet
    still flies (the keyword is not sized by X) and gets no counter."""
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_pet_duel(set_pool, [], _W1G1_PET_POOL)
    free = next(
        c for c in set_pool("ATQ").values()
        if c.primary_type == "creature" and not int(c.cmc)
    )
    game.players[0].hand.append(free)
    assert game.cast_from_hand(
        0, "Dralnu's Pet", optional_cost_payments={key: 1}
    ).supported
    _w1g1_resolve_stack(game)

    pet = _w1g1_named(game, 0, "Dralnu's Pet")
    assert (pet.effective_power, pet.effective_toughness) == (2, 2)
    assert game._has_keyword(pet, "flying")


def test_w1g1_dralnus_pets_kicker_is_all_or_nothing(set_pool):
    """Every way the price cannot be met is a refused cast with nothing spent
    and nothing discarded (CR 601.2h): no creature card to discard, a card
    named that is not one, the mana short, and the {B} missing."""
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)
    kick = {"optional_cost_payments": {key: 1}}

    no_creature = _w1g1_pet_duel(set_pool, ["Lightning Bolt"], _W1G1_PET_POOL)
    refused = no_creature.cast_from_hand(0, "Dralnu's Pet", **kick)
    assert not refused.supported and "601.2h" in refused.details

    wrong_card = _w1g1_pet_duel(
        set_pool, ["Lightning Bolt", "Hill Giant"], _W1G1_PET_POOL
    )
    assert not wrong_card.cast_from_hand(
        0, "Dralnu's Pet", cost_hand_index=1, **kick
    ).supported

    for pool in ({"U": 3}, {"U": 5, "G": 3}):
        short = _w1g1_pet_duel(set_pool, ["Hill Giant"], pool)
        assert not short.cast_from_hand(0, "Dralnu's Pet", **kick).supported
        assert sum(short.players[0].mana_pool.values()) == sum(pool.values())
        assert not short.players[0].graveyard, "the discard is not paid first"
        [offer] = short.cast_cost_offers(0, card, spell_hand_index=0)
        assert offer["max_times"] == 0, "nor is it offered"

    for game in (no_creature, wrong_card):
        assert not game.players[0].graveyard
        assert _w1g1_floating(game) == sum(_W1G1_PET_POOL.values())
        assert game.players[0].hand[0].name == "Dralnu's Pet"

    payable = _w1g1_pet_duel(set_pool, ["Hill Giant"], {"U": 5, "B": 1})
    [offer] = payable.cast_cost_offers(0, card, spell_hand_index=0)
    assert (offer["label"], offer["max_times"]) == ("kicker", 1)


def test_w1g1_the_kicked_pet_asks_which_creature_card_to_discard(set_pool):
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_pet_duel(
        set_pool, ["Lightning Bolt", "Grizzly Bears", "Hill Giant"], _W1G1_PET_POOL
    )
    plain = game.cast_target_spec(0, card, optional_cost_payments={})
    assert plain["kind"] == "none"
    kicked = game.cast_target_spec(0, card, optional_cost_payments={key: 1})
    assert kicked["discard_cost"] and kicked["kind"] == "hand_card"
    assert [t["name"] for t in kicked["valid_targets"]] == ["Grizzly Bears", "Hill Giant"]


def test_w1g1_the_ai_plans_the_pets_whole_price_or_declines_it(set_pool):
    """A hand big enough to spare a card (the buyback reserve) and six lands of
    the right colours: the AI kicks, and the lands it plans pay all six mana.
    With only Islands the {B} is not there, so it casts the plain Pet — never
    an announcement the engine then refuses."""
    lea = set_pool("LEA")
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)

    def board(swamps):
        game = _w1g1_pet_duel(set_pool, ["Hill Giant"] + ["Forest"] * 9, {})
        for name, count in (("Island", 3), ("Swamp", swamps)):
            for _ in range(count):
                _w1g1_put(game, 0, lea[name])
        game.active_player_index = 0
        game.current_phase = "main"
        game.lands_played_this_turn[0] = 1
        return game

    kicked = _w1g1_choose_cast_action(board(3), 0)
    assert kicked.card_name == "Dralnu's Pet"
    assert kicked.optional_cost_payments == {key: 1}
    assert len(kicked.land_tap_indices) == 6

    plain = _w1g1_choose_cast_action(board(0), 0)
    assert plain.card_name == "Dralnu's Pet" and not plain.optional_cost_payments
    assert len(plain.land_tap_indices) == 3
