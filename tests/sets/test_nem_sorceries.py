"""Nemesis sorceries.

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


# --- W1G2: alternative costs and redirects ---
# Mind Swords and Reverent Silence: one of each of Nemesis' alternative-cost
# shapes that was new to the pool (a sacrifice the caster chooses, a life gain
# handed to *every* other player), and the effects behind them.
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g2s_table(set_pool, hands, boards):
    """One seat per entry in *hands*/*boards*, mana costs **enforced** so a
    free cast and an ordinary one are told apart. Cards come from Nemesis,
    then the base set, M21 and Mirage for the basics and the bystanders."""
    pools = (set_pool("NEM"), set_pool("LEA"), set_pool("M21"), set_pool("MIR"))

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    players = [PlayerState(f"P{seat}") for seat in range(len(hands))]
    for player, hand, board in zip(players, hands, boards):
        player.hand = [card(name) for name in hand]
        player.battlefield.extend(Permanent(card=card(name)) for name in board)
    game = Game(players=players)
    game.enforce_mana_costs = True
    game._sync_control()
    return game


def test_w1g2_mind_swords_sacrifices_the_creature_the_caster_names(set_pool):
    """CR 601.2b: "sacrifice **a** creature" is the caster's choice of which.

    The Hill Giant is named; the deterministic pick (the smallest) would have
    taken the Bears, so a payment that ignored the announcement fails here. A
    name that cannot pay — the opponent's creature — is refused with nothing
    spent, never slid onto a creature the caster did not name.
    """
    game = _w1g2s_table(
        set_pool,
        hands=[["Mind Swords"], []],
        boards=[["Swamp", "Grizzly Bears", "Hill Giant"], ["Grizzly Bears"]],
    )
    caster, other = game.players
    theirs = other.battlefield[0]
    refused = game.cast_from_hand(
        0, "Mind Swords", alternative_cost=True,
        alternative_cost_permanent_ids=[theirs.permanent_id],
    )
    assert not refused.supported
    assert len(caster.battlefield) == 3 and [c.name for c in caster.hand] == ["Mind Swords"]

    giant = caster.battlefield[2]
    result = game.cast_from_hand(
        0, "Mind Swords", alternative_cost=True,
        alternative_cost_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Swamp", "Grizzly Bears"]
    assert [c.name for c in caster.graveyard] == ["Hill Giant", "Mind Swords"]
    assert not any(caster.mana_pool.values())


def test_w1g2_mind_swords_needs_the_printed_swamp(set_pool):
    """No Swamp is no offer (CR 601.2b), and the mana cost stands."""
    game = _w1g2s_table(
        set_pool, hands=[["Mind Swords"], []],
        boards=[["Island", "Grizzly Bears"], []],
    )
    offers = game.cast_cost_offers(0, set_pool("NEM")["Mind Swords"], spell_hand_index=0)
    assert [o for o in offers if o["kind"] == "alternative"] == []
    assert not game.cast_from_hand(0, "Mind Swords", alternative_cost=True).supported
    assert len(game.players[0].battlefield) == 2


def test_w1g2_mind_swords_each_player_exiles_two_of_their_choice(set_pool):
    """"Each player exiles two cards from their hand."

    Each seat chooses out of its own hidden hand (CR 400.2), in turn order
    (CR 101.4). The interactive seat is asked twice and its answers are the
    cards that leave; the other seat takes the default. A seat holding one card
    exiles that one (CR 608.2: as much as possible). The cards go to exile —
    not to a graveyard, which would be a discard (CR 701.9a) and would fire
    every "whenever a player discards" watcher.
    """
    game = _w1g2s_table(
        set_pool,
        hands=[["Mind Swords", "Shock", "Giant Growth", "Forest"], ["Island"]],
        boards=[["Swamp", "Grizzly Bears"], []],
    )
    game.interactive_seats = {0}
    caster, other = game.players

    assert game.cast_from_hand(0, "Mind Swords", alternative_cost=True).supported
    owed = [(c.kind, c.player_index) for c in game.pending_choices]
    assert owed == [("exile_from_hand_choice", 0)] * 2
    assert other.hand == [] and [c.name for c in other.exile] == ["Island"]

    assert game.confirm_exile_from_hand_choice(0, 2)   # Forest
    assert game.confirm_exile_from_hand_choice(0, 0)   # Shock
    resolve_stack(game)

    assert [c.name for c in caster.hand] == ["Giant Growth"]
    assert sorted(c.name for c in caster.exile) == ["Forest", "Shock"]
    assert [c.name for c in caster.graveyard] == ["Grizzly Bears", "Mind Swords"]
    assert game.pending_choices == []


def test_w1g2_mind_swords_pick_is_mandatory(set_pool):
    """The printed sentence is not an offer: the prompt refuses a decline,
    because a decline would be a Mind Swords that exiles nothing."""
    game = _w1g2s_table(
        set_pool,
        hands=[["Mind Swords", "Shock"], []],
        boards=[["Swamp", "Grizzly Bears"], []],
    )
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Mind Swords", alternative_cost=True)

    assert not game.confirm_exile_from_hand_choice(0, None)
    assert game.confirm_exile_from_hand_choice(0, 0)
    assert [c.name for c in game.players[0].exile] == ["Shock"]


def test_w1g2_reverent_silence_hands_every_other_player_six_life(set_pool):
    """"…rather than pay this spell's mana cost, you may have **each other
    player** gain 6 life."

    Invigorate's price paid to every other seat rather than to one: at a
    three-player table both opponents gain and the caster does not. Then the
    spell destroys every enchantment, the caster's own included.
    """
    game = _w1g2s_table(
        set_pool,
        hands=[["Reverent Silence"], [], []],
        boards=[["Forest", "Pacifism"], ["Pacifism"], []],
    )
    caster, left, right = game.players

    result = game.cast_from_hand(0, "Reverent Silence", alternative_cost=True)
    resolve_stack(game)

    assert result.supported, result.details
    assert (caster.life, left.life, right.life) == (20, 26, 26)
    assert [p.card.name for p in caster.battlefield] == ["Forest"]
    assert left.battlefield == []
    assert not any(caster.mana_pool.values())


def test_w1g2_reverent_silence_is_unpayable_if_any_player_cannot_gain(set_pool):
    """CR 119.7: "a cost that involves having that player gain life can't be
    paid." Every other player is that player here, so one who cannot gain makes
    the whole price unpayable — where Invigorate's caster could hand the life
    to another opponent. Shown, marked unpayable, and refused with nothing
    paid."""
    game = _w1g2s_table(
        set_pool,
        hands=[["Reverent Silence"], []],
        boards=[["Forest"], ["Forsaken Wastes"]],
    )
    offers = game.cast_cost_offers(
        0, set_pool("NEM")["Reverent Silence"], spell_hand_index=0
    )
    assert [(o["label"], o["payable"]) for o in offers if o["kind"] == "alternative"] == [
        ("have each other player gain 6 life", False)
    ]
    refused = game.cast_from_hand(0, "Reverent Silence", alternative_cost=True)
    assert not refused.supported and "CR 119.7" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Reverent Silence"]
