"""Weatherlight enchantments.

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


# --- W1G2: dies, enters and leaves triggers ---
from engine import Game, PlayerState
from engine.models import Permanent


def _w1g2e_settle(game, limit=30):
    """Resolve the stack, stopping at an owed prompt.

    Never a bare ``while game.stack`` loop: an interactive seat that owes an
    answer holds the stack open (CR 608.2, CR 117.3b) and the loop would spin.
    """
    for _ in range(limit):
        if not game.stack or game.waiting_prompt():
            return
        game.resolve_top_of_stack()


def _w1g2e_names(zone):
    return sorted(getattr(entry, "card", entry).name for entry in zone)


def test_angelic_renewal_reanimates_under_the_seat_the_sentence_leaves_unsaid(
    set_pool, catalog_by_name
):
    """"Whenever a creature is put into your graveyard from the battlefield,
    you may sacrifice this enchantment. If you do, return that card to the
    battlefield."

    The sentence names no controller, and CR 110.2a settles it: an effect that
    puts an object onto the battlefield puts it under *that player's* control
    unless it says otherwise. The lowering used to refuse the line for saying
    nothing - it admitted only the explicit "under your control" - so a card
    was unsupported for printing the default.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}

    renewal = Permanent(card=set_pool("WTH")["Angelic Renewal"])
    game._put_permanent_onto_battlefield(0, renewal, None)
    victim = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, victim, None)
    _w1g2e_settle(game)

    victim.damage_marked = 999
    game.check_state_based_actions()
    _w1g2e_settle(game)

    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True) is True
    _w1g2e_settle(game)

    assert _w1g2e_names(alice.battlefield) == ["Grizzly Bears"]
    assert _w1g2e_names(alice.graveyard) == ["Angelic Renewal"]


def test_abduction_gives_the_creature_back_to_its_owner_when_it_dies(
    set_pool, catalog_by_name
):
    """Abduction's three lines are one card, and the last one is the whole
    reason it is not Control Magic.

    "You control enchanted creature" is a CR 613 layer-2 contribution while the
    Aura is attached; "When enchanted creature dies, return that card to the
    battlefield **under its owner's control**" gives it back. That seat is the
    one the reanimation could not say - the handler put every returned card
    under the resolving player's control, which here is the thief - so the card
    was refused rather than quietly stealing the creature twice.
    """
    victim = Permanent(card=catalog_by_name["Grizzly Bears"])
    victim.tapped = True
    owner = PlayerState(name="Bob", battlefield=[victim])
    thief = PlayerState(name="Alice", hand=[set_pool("WTH")["Abduction"]])
    game = Game(players=[thief, owner])
    game.enforce_mana_costs = False
    game._settle()

    game.cast_from_hand(0, "Abduction", target_player_index=1, target_permanent_index=0)
    _w1g2e_settle(game)

    assert game.controller_index_of(victim) == 0, "you control enchanted creature"
    assert not victim.tapped, "the Aura's own entry trigger untaps it"

    victim.damage_marked = 999
    game.check_state_based_actions()
    _w1g2e_settle(game)
    game.check_state_based_actions()

    assert _w1g2e_names(owner.battlefield) == ["Grizzly Bears"], (
        "the Bears come back to Bob, who never stopped owning them"
    )
    assert thief.battlefield == []
    assert _w1g2e_names(thief.graveyard) == ["Abduction"]
