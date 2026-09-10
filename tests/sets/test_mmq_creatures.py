"""Mercadian Masques creatures.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: upkeep, end-step and enters-the-battlefield triggers ---
#
# Five creatures whose abilities fire at a step boundary or on entry. The
# pattern worth stating: every one was refused by a *lowering* rather than by a
# parse, and in three cases the printed sentence was already a production one
# word order or one article away.

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack


def _g4_blank(name, type_line="Basic Land - Island"):
    """A filler card with no text, for hands, libraries and graveyards."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name},
    )


def _g4_creature(name, power="2", toughness="2"):
    """A vanilla bear, for a graveyard census or a sacrifice candidate."""
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name},
        power=power, toughness=toughness,
    )


def _g4_duel(set_pool):
    """Two seats, cost enforcement off, and MMQ's pool keyed by name."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, set_pool("MMQ")


def _g4_settle(game):
    """Drain the stack, then answer the offers a trigger left behind it."""
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()
    return game


def test_extravagant_spirits_toll_scales_with_the_hand(set_pool):
    """"...sacrifice this creature unless you pay {1} **for each card in your
    hand**." The multiplier is not a printed number, so it rides the payload as
    an ordinary count spec and is taken when the ability resolves (CR 608.2) -
    the hand as it stands then, not as it stood when the trigger fired.

    The card is asserted at the compiled program because a *headless* seat
    never taps a land for an optional cost (a stated policy, not the payability
    test), so no board this test could build would show the price being paid;
    Megatherium below pays the same toll out of a pool it already holds.
    """
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("MMQ")["Extravagant Spirit"])
    offer = program.triggered_abilities[0].instruction
    assert offer.kind == "may"
    assert offer.payload["cost"] == {"generic": 1}
    assert offer.payload["cost_per"] == {
        "zone": "hand", "owner": "you", "filter": {},
    }


def test_extravagant_spirit_goes_when_the_toll_is_not_paid(set_pool):
    """The decline branch is the sacrifice, and it is the source that goes -
    not a permanent chosen out of the controller's board."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Extravagant Spirit"]))
    p1.battlefield.append(Permanent(card=_g4_creature("Bystander")))
    p1.hand = [_g4_blank("h0"), _g4_blank("h1")]
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Bystander"]


def test_an_empty_hand_makes_extravagant_spirits_toll_free(set_pool):
    """Zero cards is a cost of {0}, which its payer can always cover - so the
    creature stays with no mana at all."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Extravagant Spirit"]))
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Extravagant Spirit"]


def test_megatherium_charges_the_same_toll_on_entry(set_pool):
    """The identical printed sentence on an **enters** trigger. It used to
    lower to ``upkeep_pay_or_sacrifice_self``, which the upkeep registry
    dispatches and nothing else does - so the card would have compiled clean
    and never charged anybody."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.hand = [_g4_blank("h0"), _g4_blank("h1")]
    p1.mana_pool["G"] = 5
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Megatherium"]), None
    )
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Megatherium"]
    assert p1.mana_pool["G"] == 3


def test_nether_spirit_returns_itself_when_it_is_alone(set_pool):
    """CR 113.6b: the intervening-if is where the card says a graveyard is
    where the ability functions at all, so the upkeep's graveyard scan is what
    fires it."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.graveyard = [by_name["Nether Spirit"], _g4_blank("Ritual", "Sorcery")]
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Nether Spirit"]
    assert [card.name for card in p1.graveyard] == ["Ritual"]


@pytest.mark.parametrize("companions, comes_back", [((), True), (("Bear",), False)])
def test_nether_spirit_counts_every_creature_card_in_the_pile(
    set_pool, companions, comes_back,
):
    """"the **only** creature card" is a census, not a position: one other
    creature card anywhere in the graveyard turns the ability off."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.graveyard = [by_name["Nether Spirit"]] + [
        _g4_creature(name) for name in companions
    ]
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    on_board = [perm.card.name for perm in p1.battlefield]
    assert ("Nether Spirit" in on_board) is comes_back


def test_two_nether_spirits_are_two_creature_cards(set_pool):
    """The identity half of the test earns its keep here: a graveyard holding
    two copies has two creature cards in it, and neither is "the only" one.
    Two copies of a card in a deck are the same immutable object, so a count
    that stopped at "is this card in the pile" would return both."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    spirit = by_name["Nether Spirit"]
    p1.graveyard = [spirit, spirit]
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == []
    assert len(p1.graveyard) == 2


def test_charmed_griffin_offers_each_opponent_a_permanent_from_hand(set_pool):
    """"...put an artifact or enchantment card onto the battlefield **from
    their hand**" - the source zone printed after the destination, which the
    noun parser reads perfectly well the other way round."""
    game, _p1, p2, by_name = _g4_duel(set_pool)
    p2.hand = [_g4_blank("Bauble", "Artifact"), _g4_blank("Ritual", "Sorcery")]
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Charmed Griffin"]), None
    )
    _g4_settle(game)

    assert [perm.card.name for perm in p2.battlefield] == ["Bauble"]
    assert [card.name for card in p2.hand] == ["Ritual"]


def test_charmed_griffin_leaves_a_hand_with_nothing_it_names(set_pool):
    """The sorcery is neither an artifact nor an enchantment, and the *card*
    matcher now knows it: ``artifact_or_enchantment`` was a ``type_filter``
    value only the permanent matcher special-cased, so it matched every
    qualifying permanent and no card in any zone."""
    game, _p1, p2, by_name = _g4_duel(set_pool)
    p2.hand = [_g4_blank("Ritual", "Sorcery")]
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Charmed Griffin"]), None
    )
    _g4_settle(game)

    assert [perm.card.name for perm in p2.battlefield] == []
    assert [card.name for card in p2.hand] == ["Ritual"]


def test_enslaved_horror_reanimates_out_of_every_other_graveyard(set_pool):
    """"each other player may return a creature card from **their** graveyard"
    - the offered seat's own pile, and never the controller's."""
    game, p1, p2, by_name = _g4_duel(set_pool)
    p1.graveyard = [_g4_creature("Mine")]
    p2.graveyard = [_g4_blank("Ritual", "Sorcery"), _g4_creature("Theirs")]
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Enslaved Horror"]), None
    )
    _g4_settle(game)

    assert [perm.card.name for perm in p2.battlefield] == ["Theirs"]
    assert [perm.card.name for perm in p1.battlefield] == ["Enslaved Horror"]
    assert [card.name for card in p1.graveyard] == ["Mine"]
