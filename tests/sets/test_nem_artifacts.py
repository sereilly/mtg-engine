"""Nemesis artifacts.

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

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: library, hand and graveyard ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_portal(set_pool, hand, *, chosen="Goblin"):
    """Belbe's Portal entered on seat 0 with *chosen* answered at the
    "choose a creature type" prompt, untapped and free to activate. Seat 0 is
    interactive so the activation's offers wait to be answered. W1G5's own."""
    me = _W1G5PlayerState(name="W1G5-A", hand=list(hand))
    game = _W1G5Game(players=[me, _W1G5PlayerState(name="W1G5-B")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    portal = _W1G5Permanent(card=set_pool("NEM")["Belbe's Portal"])
    game._put_permanent_onto_battlefield(0, portal, None)
    assert game.confirm_enter_choice(0, creature_type=chosen)
    portal.metadata["summoning_sickness_turn"] = -99
    return game, portal, me


def test_w1g5_belbes_portal_offers_only_the_chosen_type(set_pool):
    """"As this artifact enters, choose a creature type." / "{3}, {T}: You may
    put a creature card of the chosen type from your hand onto the
    battlefield."

    Goblin chosen, two Goblins and an Elephant in hand: the live offer is the
    two Goblins, an answer naming the Elephant is refused, and the Goblin
    answered with enters. The choice is the CR 614.1c record the entry wrote,
    read off the Portal when the ability resolves.
    """
    nem = set_pool("NEM")
    game, portal, me = _w1g5_portal(
        set_pool, [nem["Wild Mammoth"], nem["Shrieking Mogg"], nem["Mogg Toady"]]
    )
    assert portal.metadata["chosen_creature_type"] == "goblin"

    assert game.activate_permanent_ability(0, "Belbe's Portal").supported
    assert portal.tapped
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, True, None)
    pick = game.pending_choice_of("put_from_hand_choice", 0)
    assert game.live_put_from_hand_choices(pick) == [1, 2]
    assert not game.confirm_put_from_hand_choice(0, 0), "an Elephant is not a Goblin"
    assert game.confirm_put_from_hand_choice(0, 1)
    _w1g5_resolve_stack(game)

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Belbe's Portal", "Shrieking Mogg",
    ]
    assert [c.name for c in me.hand] == ["Wild Mammoth", "Mogg Toady"]


def test_w1g5_belbes_portal_with_nothing_of_the_type_puts_nothing(set_pool):
    """Elephant chosen and no Elephant in hand: the offer has nothing to give,
    so nothing enters — the narrowing is not dropped into "any creature card"
    for want of a match."""
    nem = set_pool("NEM")
    game, _, me = _w1g5_portal(
        set_pool, [nem["Shrieking Mogg"], nem["Mogg Toady"]], chosen="Elephant"
    )
    game.activate_permanent_ability(0, "Belbe's Portal")
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [p.card.name for p in game.controlled_by(0)] == ["Belbe's Portal"]
    assert len(me.hand) == 2


def test_w1g5_belbes_portal_without_a_record_offers_nothing(set_pool):
    """The fail-closed half: a Portal whose chosen type is somehow absent must
    not fall back to every creature card. ``_card_matches_filter`` refuses the
    unresolved key, the way ``permanent_matches_filter`` already did."""
    nem = set_pool("NEM")
    game, portal, _ = _w1g5_portal(set_pool, [nem["Shrieking Mogg"]])
    portal.metadata.pop("chosen_creature_type")
    game.activate_permanent_ability(0, "Belbe's Portal")
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [p.card.name for p in game.controlled_by(0)] == ["Belbe's Portal"]
