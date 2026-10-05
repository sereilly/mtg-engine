"""Invasion enchantments.

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


# --- W1G4: colour census ---
from engine import Game as _W1G4AuraGame
from engine import PlayerState as _W1G4AuraSeat
from engine.models import Permanent as _W1G4AuraPermanent
from tests.helpers import resolve_stack as _w1g4_aura_resolve

_W1G4_LEAK_LINE = (
    "at the beginning of your upkeep, sacrifice this permanent unless you pay "
    "its mana cost."
)


def _w1g4_leak_table():
    """Two seats, mana costs off until a test turns them on to charge the toll."""
    w1g4_leak_game = _W1G4AuraGame(players=[
        _W1G4AuraSeat(name="W1G4-leaker"), _W1G4AuraSeat(name="W1G4-host"),
    ])
    w1g4_leak_game.enforce_mana_costs = False
    w1g4_leak_game.active_player_index = 0
    return w1g4_leak_game


def _w1g4_host(game, seat, card):
    """*card* onto *seat*'s battlefield through the real entry seam."""
    w1g4_host_permanent = _W1G4AuraPermanent(card=card)
    game._put_permanent_onto_battlefield(seat, w1g4_host_permanent, None)
    game.check_state_based_actions()
    return w1g4_host_permanent


def _w1g4_leak_onto(game, aura_card, host):
    """Seat 0 casts *aura_card* on *host* through the real cast; the Aura."""
    game.players[0].hand.append(aura_card)
    w1g4_leak_cast = game.cast_from_hand(
        0, aura_card.name,
        target_player_index=game.controller_index_of(host),
        target_permanent_index=game.battlefield_index_of(host),
    )
    assert w1g4_leak_cast.supported, w1g4_leak_cast.details
    _w1g4_aura_resolve(game)
    game.check_state_based_actions()
    return next(
        permanent for permanent in game.all_permanents()
        if permanent.card.name == aura_card.name
    )


def test_w1g4_essence_leak_charges_a_green_hosts_controller_its_mana_cost(set_pool):
    """'As long as enchanted permanent is red or green, it has "At the beginning
    of your upkeep, sacrifice this permanent unless you pay its mana cost."'

    The ability is the *host's*, so "your upkeep" is its controller's — not the
    Aura's — and the price is the host's own mana cost: Grizzly Bears' {1}{G}
    taps two of three Forests. Nothing happens on the Aura controller's upkeep.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_leak_table()
    bear = _w1g4_host(game, 1, lea["Grizzly Bears"])
    forests = [_w1g4_host(game, 1, lea["Forest"]) for _ in range(3)]
    _w1g4_leak_onto(game, inv["Essence Leak"], bear)
    assert bear.effective_card.oracle_text == _W1G4_LEAK_LINE
    game.enforce_mana_costs = True

    game.resolve_upkeep(0)
    _w1g4_aura_resolve(game)
    assert game.is_on_battlefield(bear) and not any(f.tapped for f in forests)

    quoted = [
        prompt for prompt in game.get_upkeep_pay_triggers(1)
        if prompt["permanent_id"] == bear.permanent_id
    ]
    assert len(quoted) == 1 and quoted[0]["cost"]["mana"] == {"G": 1, "generic": 1}

    game.resolve_upkeep(1)
    _w1g4_aura_resolve(game)
    assert game.is_on_battlefield(bear)
    assert sum(forest.tapped for forest in forests) == 2
    assert "W1G4-host paid upkeep for Grizzly Bears" in game.log


def test_w1g4_essence_leak_takes_the_host_when_its_cost_is_not_paid(set_pool):
    """Declined, or simply unaffordable, the host is sacrificed by its own
    controller — and the Aura follows it as a state-based action (CR 704.5m).
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    for declined in (True, False):
        game = _w1g4_leak_table()
        giant = _w1g4_host(game, 1, lea["Hill Giant"])        # red, {3}{R}
        lands = (
            [_w1g4_host(game, 1, lea["Mountain"]) for _ in range(4)]
            if declined else []
        )
        _w1g4_leak_onto(game, inv["Essence Leak"], giant)
        game.enforce_mana_costs = True
        answers = {giant.permanent_id: False} if declined else None
        game.resolve_upkeep(1, human_choices=answers)
        _w1g4_aura_resolve(game)
        game.check_state_based_actions()

        assert not game.is_on_battlefield(giant)
        assert not any(land.tapped for land in lands), "nothing was paid"
        assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]
        assert [card.name for card in game.players[0].graveyard] == ["Essence Leak"]


def test_w1g4_essence_leak_follows_the_hosts_colour_through_the_layers(set_pool):
    """The criterion is CR 613 layer 5's answer, asked on every recompute: a
    white host has no such ability and survives its upkeep with no lands; a
    Chaoslace makes it red and the ability appears; a Purelace takes it away
    again with nothing to undo (CR 611.3a).
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_leak_table()
    lions = _w1g4_host(game, 1, lea["Savannah Lions"])
    _w1g4_leak_onto(game, inv["Essence Leak"], lions)
    assert lions.effective_card.oracle_text == ""
    game.resolve_upkeep(1)
    _w1g4_aura_resolve(game)
    assert game.is_on_battlefield(lions)

    for lace, expected in (("Chaoslace", _W1G4_LEAK_LINE), ("Purelace", "")):
        game.players[0].hand.append(lea[lace])
        assert game.cast_from_hand(
            0, lace, target_player_index=1,
            target_permanent_ids=[lions.permanent_id],
        ).supported
        _w1g4_aura_resolve(game)
        game.check_state_based_actions()
        assert lions.effective_card.oracle_text == expected, lace


def test_w1g4_a_host_with_no_mana_cost_cannot_pay_it(set_pool):
    """CR 118.6 / CR 202.1b: a land has no mana cost, so a cost based on it is
    unpayable — it may not even be attempted. A Forest turned green by a
    Lifelace is sacrificed however many lands its controller could tap, and the
    prompt quotes nothing for it.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_leak_table()
    forest = _w1g4_host(game, 1, lea["Forest"])
    spare = [_w1g4_host(game, 1, lea["Forest"]) for _ in range(3)]
    _w1g4_leak_onto(game, inv["Essence Leak"], forest)
    assert _W1G4_LEAK_LINE not in forest.effective_card.oracle_text, (
        "a Forest is colourless, whatever mana it makes"
    )

    game.players[0].hand.append(lea["Lifelace"])
    assert game.cast_from_hand(
        0, "Lifelace", target_player_index=1,
        target_permanent_ids=[forest.permanent_id],
    ).supported
    _w1g4_aura_resolve(game)
    game.check_state_based_actions()
    assert _W1G4_LEAK_LINE in forest.effective_card.oracle_text
    game.enforce_mana_costs = True
    assert not [
        prompt for prompt in game.get_upkeep_pay_triggers(1)
        if prompt["permanent_id"] == forest.permanent_id
    ]

    game.resolve_upkeep(1)
    _w1g4_aura_resolve(game)
    assert not game.is_on_battlefield(forest)
    assert not any(land.tapped for land in spare)


def test_w1g4_a_conditional_grant_the_engine_cannot_read_is_not_claimed():
    """The gate asks the same function the grant is derived from, so a quote
    the compiler refuses, or a criterion the matcher cannot test, leaves the
    line unclaimed and the card unsupported — never admitted and inert.
    """
    from engine.auras import aura_conditional_ability_grants, aura_continuous_claim

    printed = (
        'As long as enchanted permanent is red or green, it has "At the '
        'beginning of your upkeep, sacrifice this permanent unless you pay its '
        'mana cost."'
    )
    (criterion, line), = aura_conditional_ability_grants(printed)
    assert dict(criterion)["any_colors"] == ("R", "G")
    assert line == _W1G4_LEAK_LINE
    assert aura_continuous_claim(printed)

    unreadable = (
        'As long as enchanted permanent is red or green, it has "Whenever a '
        'moon rises, win the game."'
    )
    assert aura_conditional_ability_grants(unreadable) == ()
    assert aura_continuous_claim(unreadable) is None
    vacuous = (
        'As long as enchanted permanent is splendid, it has "{T}: Draw a card."'
    )
    assert aura_conditional_ability_grants(vacuous) == ()
