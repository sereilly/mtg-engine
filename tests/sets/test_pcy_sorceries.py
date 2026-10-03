"""Prophecy sorceries.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: tokens, zones and triggers ---
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import _mk_card as _w1g6_mk_card, resolve_stack as _w1g6_resolve


def _w1g6_creature_card(name):
    return _w1g6_mk_card(name, "Creature — Beast")


def _w1g6_elephants(game, seat):
    return [p for p in game.controlled_by(seat) if p.card.name == "Elephant Token"]


def test_w1g6_elephant_resurgence_sizes_each_token_by_its_controllers_graveyard(set_pool):
    """"Each player creates a green Elephant creature token. Those creatures
    have "This token's power and toughness are each equal to the number of
    creature cards in its controller's graveyard."" Each token counts its own
    controller's pile, and keeps counting it."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P0", hand=[set_pool("PCY")["Elephant Resurgence"]],
            graveyard=[_w1g6_creature_card("Elk"), _w1g6_creature_card("Ox")],
        ),
        _W1G6PlayerState(
            name="P1",
            graveyard=[_w1g6_creature_card("Yak"), _w1g6_mk_card("Forest", "Basic Land — Forest")],
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()

    assert game.cast_from_hand(0, "Elephant Resurgence").supported
    _w1g6_resolve(game)

    (mine,), (theirs,) = _w1g6_elephants(game, 0), _w1g6_elephants(game, 1)
    assert mine.metadata.get("is_token") and theirs.metadata.get("is_token")
    assert "G" in mine.effective_colors
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert (theirs.effective_power, theirs.effective_toughness) == (1, 1)

    # A creature of P1's dies: P1's token grows, P0's does not.
    gnu = _W1G6Permanent(card=_w1g6_creature_card("Gnu"))
    game._put_permanent_onto_battlefield(1, gnu, None)
    game.sacrifice_permanent(gnu)
    game._refresh_dynamic_creatures()
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)
    assert mine.effective_power == 2


def _w1g6_denying_wind_table(set_pool):
    library = [_w1g6_mk_card(f"Card {n}", "Sorcery") for n in range(10)]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", hand=[set_pool("PCY")["Denying Wind"]]),
        _W1G6PlayerState(name="P1", library=list(library)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Denying Wind", target_player_index=1).supported
    return game  # _w1g6_denying_wind_table


def test_w1g6_denying_wind_exiles_up_to_seven_from_the_targets_library(set_pool):
    """"Search target player's library for up to seven cards and exile them.
    Then that player shuffles." The caster searches the *target's* library and
    may stop short of seven: three picks are a legal answer."""
    game = _w1g6_denying_wind_table(set_pool)
    game.interactive_seats = {0}
    _w1g6_resolve(game)
    assert [c.kind for c in game.pending_choices] == ["search_library"]
    assert game.pending_choices[0].data.get("count") == 7
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": i} for i in (0, 4, 9)]
    )
    _w1g6_resolve(game)
    assert sorted(c.name for c in game.players[1].exile) == ["Card 0", "Card 4", "Card 9"]
    assert len(game.players[1].library) == 7
    assert not game.players[0].exile and not game.players[0].library


def _w1g6_theft_table(set_pool):
    shock = set_pool("STH")["Shock"]
    bear = _w1g6_creature_card("Bear")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", hand=[set_pool("PCY")["Psychic Theft"]]),
        _W1G6PlayerState(name="P1", hand=[bear, shock]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Psychic Theft", target_player_index=1).supported
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    return game  # _w1g6_theft_table


def test_w1g6_psychic_theft_exiles_the_instant_and_lets_you_cast_it(set_pool):
    """"Target player reveals their hand. You choose an instant or sorcery card
    from it and exile that card. You may cast that card for as long as it
    remains exiled." The instant — not the creature — goes to its owner's
    exile, and the caster casts it from there."""
    game = _w1g6_theft_table(set_pool)
    assert [c.name for c in game.players[1].exile] == ["Shock"]
    assert [c.name for c in game.players[1].hand] == ["Bear"]
    grant = game.cast_permissions[0]
    assert (grant.player_index, grant.zone_seat, grant.mode) == (0, 1, "cast")

    result = game.cast_from_hand(0, "Shock", target_player_index=1, from_zone="exile")
    assert result.supported, result.details
    _w1g6_resolve(game)
    assert game.players[1].life == 18
    assert not game.players[1].exile
    assert not game.cast_permissions
    # Which graveyard the resolved Shock lands in is not asserted: every
    # leave-the-stack site approximates the owner with the caster's seat (see
    # handlers/stack.py's exile path), so it goes to P0's — CR 400.3 says P1's.
    # Reported at the round with Grinning Totem, the other card it reaches.

    game.resolve_end_step(0)
    game._settle()
    assert [c.name for c in game.players[1].hand] == ["Bear"]


def test_w1g6_psychic_theft_waits_for_an_interactive_pick(set_pool):
    """An interactive caster answers the pick; the permission and the delayed
    return are made only once it is answered, over the card it named."""
    pcy, sth = set_pool("PCY"), set_pool("STH")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", hand=[pcy["Psychic Theft"]]),
        _W1G6PlayerState(name="P1", hand=[sth["Shock"], _w1g6_creature_card("Bear")]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Psychic Theft", target_player_index=1).supported
    game.resolve_top_of_stack()  # one step: the helper would answer the pick
    assert [c.kind for c in game.pending_choices] == ["revealed_hand_pick"]
    assert not game.cast_permissions
    assert not game.confirm_revealed_hand_pick(0, 1), "a creature is not an instant"
    assert game.confirm_revealed_hand_pick(0, 0)
    _w1g6_resolve(game)
    assert [c.name for c in game.players[1].exile] == ["Shock"]
    assert [c.name for c in game.cast_permissions[0].cards] == ["Shock"]
    assert [t.event for t in game.delayed_triggers] == ["next_end_step"]


def test_w1g6_psychic_theft_returns_the_uncast_card_at_the_end_step(set_pool):
    """"At the beginning of the next end step, if you haven't cast the card,
    return it to its owner's hand." Its owner's hand, not the caster's."""
    game = _w1g6_theft_table(set_pool)
    assert [c.name for c in game.players[1].exile] == ["Shock"]

    game.resolve_end_step(0)
    game._settle()
    assert not game.players[1].exile
    assert sorted(c.name for c in game.players[1].hand) == ["Bear", "Shock"]
    assert [c.name for c in game.players[0].hand] == []


def _w1g6_survivors(set_pool, graveyard):
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P0", hand=[set_pool("PCY")["Search for Survivors"]],
            graveyard=list(graveyard),
        ),
        _W1G6PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Search for Survivors").supported
    _w1g6_resolve(game)
    return game  # _w1g6_survivors


def test_w1g6_search_for_survivors_returns_a_creature_card(set_pool):
    """"…An opponent chooses a card at random in your graveyard. If it's a
    creature card, put it onto the battlefield." A graveyard of one creature
    card leaves nothing to chance."""
    game = _w1g6_survivors(set_pool, [_w1g6_creature_card("Elk")])
    assert [p.card.name for p in game.controlled_by(0)] == ["Elk"]
    assert [c.name for c in game.players[0].graveyard] == ["Search for Survivors"]
    assert not game.players[0].exile


def test_w1g6_search_for_survivors_exiles_a_noncreature_card(set_pool):
    """"Otherwise, exile it." — and only the one card the pick named."""
    game = _w1g6_survivors(set_pool, [_w1g6_mk_card("Forest", "Basic Land — Forest")])
    assert not list(game.controlled_by(0))
    assert [c.name for c in game.players[0].exile] == ["Forest"]


def test_w1g6_search_for_survivors_takes_exactly_one_of_several(set_pool):
    import random

    random.seed(7)
    pile = [_w1g6_creature_card("Elk"), _w1g6_mk_card("Forest", "Basic Land — Forest"),
            _w1g6_creature_card("Ox"), _w1g6_mk_card("Swamp", "Basic Land — Swamp")]
    game = _w1g6_survivors(set_pool, pile)
    moved = [p.card.name for p in game.controlled_by(0)] + [c.name for c in game.players[0].exile]
    assert len(moved) == 1
    left = sorted(c.name for c in game.players[0].graveyard if c.name != "Search for Survivors")
    assert sorted(left + moved) == ["Elk", "Forest", "Ox", "Swamp"]
    if moved[0] in ("Elk", "Ox"):
        assert not game.players[0].exile
    else:
        assert not list(game.controlled_by(0))


def test_w1g6_denying_wind_default_takes_at_most_seven(set_pool):
    game = _w1g6_denying_wind_table(set_pool)
    _w1g6_resolve(game)
    exiled = len(game.players[1].exile)
    assert 0 <= exiled <= 7
    assert exiled + len(game.players[1].library) == 10
