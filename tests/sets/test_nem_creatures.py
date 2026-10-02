"""Nemesis creatures.

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


# --- W1G6: lands, mana and untapping ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g6_crt_upkeep(game, seat):
    """Start *seat*'s turn and settle every trigger its upkeep put on the stack."""
    game.start_turn(seat)
    for _ in range(4):
        game.auto_resolve_pending_choices()
        if not resolve_stack(game):
            break
    return seat


def _w1g6_bears(set_pool, count):
    return [Permanent(card=set_pool("LEA")["Grizzly Bears"]) for _ in range(count)]


def test_wild_mammoth_goes_to_the_player_with_the_most_creatures(set_pool):
    """"At the beginning of your upkeep, if a player controls more creatures
    than each other player, the player who controls the most creatures gains
    control of this creature."

    CR 603.4's intervening-if over a strict superlative: a tie names nobody, so
    the trigger does not even fire. When the other seat is ahead the Mammoth
    goes to them, and "your upkeep" is the new controller's from then on — so
    the *old* controller's upkeep does nothing, and the new one's moves it back
    once the count has turned round.
    """
    island = set_pool("LEA")["Island"]
    mammoth = Permanent(card=set_pool("NEM")["Wild Mammoth"])
    p0 = PlayerState(name="P0", battlefield=[mammoth, *_w1g6_bears(set_pool, 1)],
                     library=[island] * 8)
    p1 = PlayerState(name="P1", battlefield=_w1g6_bears(set_pool, 2),
                     library=[island] * 8)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._settle()

    _w1g6_crt_upkeep(game, 0)
    assert game.controller_index_of(mammoth) == 0, "two against two is a tie"
    assert not any("gains control of Wild Mammoth" in line for line in game.log)

    p1.battlefield.append(_w1g6_bears(set_pool, 1)[0])
    game._settle()
    _w1g6_crt_upkeep(game, 0)
    assert game.controller_index_of(mammoth) == 1
    assert "P1 gains control of Wild Mammoth" in game.log

    p0.battlefield.extend(_w1g6_bears(set_pool, 4))
    game._settle()
    _w1g6_crt_upkeep(game, 0)
    assert game.controller_index_of(mammoth) == 1, (
        "P0's upkeep is no longer the Mammoth controller's upkeep"
    )
    _w1g6_crt_upkeep(game, 1)
    assert game.controller_index_of(mammoth) == 0, (
        "five creatures against four, the Mammoth itself counted on P1's side"
    )


def test_harvest_mage_makes_each_tapped_land_one_mana_of_a_chosen_color(set_pool):
    """"{G}, {T}, Discard a card: Until end of turn, if you tap a land for mana,
    it produces one mana of a color of your choice instead of any other type
    and amount."

    The ability is not a mana ability (it adds no mana, CR 605.1a), so it pays
    its whole cost and uses the stack. Afterwards each land the activator taps
    makes one mana of the colour asked for at that tap — a two-mana land makes
    one — and the planner and the client are told the land can make any colour.
    The opponent's lands are untouched, and the swap ends with the turn.
    """
    from web.serialization import _offered_mana

    lea = set_pool("LEA")
    mage = Permanent(card=set_pool("NEM")["Harvest Mage"])
    mage.metadata["summoning_sickness_turn"] = -99
    forests = [Permanent(card=lea["Forest"]) for _ in range(2)]
    tomb = Permanent(card=set_pool("TMP")["Ancient Tomb"])
    theirs = Permanent(card=lea["Forest"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[mage, *forests, tomb],
                    hand=[lea["Island"]], library=[lea["Island"]] * 8),
        PlayerState(name="P1", battlefield=[theirs], library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = True  # the {G} is part of what is checked
    game._settle()
    _w1g6_crt_upkeep(game, 0)
    p0 = game.players[0]

    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=forests[0].permanent_id)
    result = game.activate_permanent_ability(0, "Harvest Mage", ability_index=0)
    assert result.supported, result.details
    resolve_stack(game)
    assert mage.tapped and not p0.hand, "{T} and the discard were paid"
    assert p0.mana_pool["G"] == 0, "{G} was paid"

    assert game.tap_land_for_mana(0, "Forest", "U", permanent_id=forests[1].permanent_id)
    assert p0.mana_pool["U"] == 1 and p0.mana_pool["G"] == 0
    life = p0.life
    assert game.tap_land_for_mana(0, "Ancient Tomb", "B", permanent_id=tomb.permanent_id)
    assert p0.mana_pool["B"] == 1 and p0.mana_pool["C"] == 0, (
        "two colorless become one black: 'instead of any other type and amount'"
    )
    assert p0.life == life - 2, "the land's own rider still happens"

    assert game._land_payment_colors(forests[0]) == ("W", "U", "B", "R", "G")
    assert _offered_mana(game, forests[0]) == ("W", "U", "B", "R", "G")
    assert game._land_payment_colors(theirs) == ("G",), "only the activator's lands"

    game.resolve_cleanup_step(0)
    assert game._land_payment_colors(forests[0]) == ("G",), (
        "until end of turn: the cleanup step lifts it"
    )
