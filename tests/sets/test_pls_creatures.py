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


# --- W1G3: revealed cards ---
# Choices made out of a hand. Doomsday Specter looks at the hand of the player
# it damaged — the seat the *damage* froze (CR 603.10), where every shipped
# printing of the sentence read a seat a cast or a target supplied. Sawtooth
# Loon is Brainstorm's put-back at the other end of the library, without the
# "in any order" rider CR 401.4 makes redundant.
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_creature_table(set_pool, mine=(), theirs=(), *, hands=(), seats=2):
    """Seat 0 controls *mine* and seat 1 *theirs*, put straight onto the
    battlefield with no entry trigger run; ``hands[seat]`` is each seat's hand.
    Seat 0 is interactive and it is seat 0's turn. Returns the game, a
    name -> card lookup, and both battlefields."""
    pools = [set_pool(code) for code in ("PLS", "LEA")]

    def w1g3_card(card_name):
        return next(pool[card_name] for pool in pools if card_name in pool)

    w1g3_players = []
    for seat in range(seats):
        names = (mine, theirs)[seat] if seat < 2 else ()
        held = hands[seat] if seat < len(hands) else ()
        w1g3_players.append(_W1G3PlayerState(
            name="ABC"[seat],
            battlefield=[_W1G3Permanent(card=w1g3_card(n)) for n in names],
            hand=[w1g3_card(n) for n in held],
            library=[w1g3_card("Forest")] * 6,
        ))
    w1g3_game = _W1G3Game(players=w1g3_players)
    w1g3_game.enforce_mana_costs = False
    w1g3_game.interactive_seats = {0}
    w1g3_game.start_turn(0)
    w1g3_game._sync_control()
    for w1g3_player in w1g3_players:
        for w1g3_perm in w1g3_player.battlefield:
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
    return w1g3_game, w1g3_card, w1g3_players[0].battlefield, w1g3_players[1].battlefield  # _w1g3_creature_table


def _w1g3_attack(game, attacker, *, defender=None, pick=None, blocks=None):
    """Declare *attacker* at *defender* and run combat to its end, answering a
    ``revealed_hand_pick`` with hand slot *pick*. *blocks* maps a blocker's
    battlefield slot to the attacker's. Returns the prompts seen, as
    ``(kind, seat owing it, seat whose hand it is about)``."""
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    slot = next(
        index for index, perm in enumerate(game.players[0].battlefield)
        if perm is attacker
    )
    declared = game.declare_attackers(0, [slot], defending_player_index=defender)
    assert declared[0], declared
    w1g3_seen = []
    for _ in range(5):
        game.advance_combat_phase()
        if blocks and game.current_step == "declare_blockers":
            blocker_seat = 1 if defender is None else defender
            assert game.declare_blockers(blocker_seat, blocks)[0]
            blocks = None
        for _ in range(8):
            if game.pending_choices:
                choice = game.pending_choices[0]
                w1g3_seen.append(
                    (choice.kind, choice.player_index, choice.data.get("victim_index"))
                )
                if choice.kind == "revealed_hand_pick" and pick is not None:
                    assert game.confirm_revealed_hand_pick(0, hand_index=pick)
                else:
                    game.auto_resolve_pending_choices()
            elif game.stack:
                game.resolve_top_of_stack()
    return w1g3_seen  # _w1g3_attack


def test_w1g3_doomsday_specter_picks_a_card_out_of_the_damaged_players_hand(set_pool):
    """"Whenever this creature deals combat damage to a player, look at that
    player's hand and choose a card from it. The player discards that card."
    Three seats, and the Specter attacks the *far* one: C took the damage, so
    it is C's hand the Specter's controller chooses from — the Counterspell,
    slot 1 — and B, the first opponent, keeps their card."""
    game, _card, mine, _theirs = _w1g3_creature_table(
        set_pool, ["Doomsday Specter"], [],
        hands=([], ["Swamp"], ["Shivan Dragon", "Counterspell", "Forest"]), seats=3,
    )

    seen = _w1g3_attack(game, mine[0], defender=2, pick=1)

    assert seen == [("revealed_hand_pick", 0, 2)], seen
    assert [player.life for player in game.players] == [20, 20, 18]
    assert [card.name for card in game.players[2].graveyard] == ["Counterspell"]
    assert [card.name for card in game.players[2].hand] == ["Shivan Dragon", "Forest"]
    assert [card.name for card in game.players[1].hand] == ["Swamp"]
    # "Look at", not "reveals": the hand is shown to the chooser alone.
    assert any("C showed their hand (3 card(s)) to A" in line for line in game.log)


def test_w1g3_doomsday_specter_chooses_nothing_from_an_empty_hand(set_pool):
    """A hand with no card in it offers no choice: the damage is dealt, no
    prompt is armed and nothing is discarded."""
    game, _card, mine, _theirs = _w1g3_creature_table(
        set_pool, ["Doomsday Specter"], [], hands=([], []),
    )

    seen = _w1g3_attack(game, mine[0])

    assert seen == [], seen
    assert game.players[1].life == 18
    assert not game.players[1].graveyard and not game.stack


def test_w1g3_doomsday_specter_does_not_trigger_when_it_is_blocked(set_pool):
    """"…deals combat damage **to a player**": blocked by a flyer, its damage
    goes to the creature, so no hand is looked at and no card is discarded."""
    game, _card, mine, theirs = _w1g3_creature_table(
        set_pool, ["Doomsday Specter"], ["Air Elemental"],
        hands=([], ["Counterspell"]),
    )

    seen = _w1g3_attack(game, mine[0], pick=0, blocks={0: 0})

    assert seen == [], seen
    assert game.players[1].life == 20
    assert [card.name for card in game.players[1].hand] == ["Counterspell"]
    assert theirs[0].damage_marked == 2 or not game.is_on_battlefield(theirs[0])


def test_w1g3_doomsday_specter_is_gated_by_a_blue_or_black_creature(set_pool):
    """"When this creature enters, return a blue or black creature you control
    to its owner's hand." Cast for real: the red Hill Giant is not offered, the
    black Drudge Skeletons is, and the Specter stays."""
    game, card, mine, _theirs = _w1g3_creature_table(
        set_pool, ["Hill Giant", "Drudge Skeletons"], [],
        hands=(["Doomsday Specter"], []),
    )
    giant, skeletons = mine[0], mine[1]

    result = game.cast_from_hand(0, "Doomsday Specter")
    assert result.supported, result.details
    owed = next(c for c in game.pending_choices if c.kind == "permanent_set_choice")
    assert not game.confirm_permanent_set_choice(0, [game.permanent_id_of(giant)])
    assert game.confirm_permanent_set_choice(0, [game.permanent_id_of(skeletons)])
    _w1g3_resolve_stack(game)

    assert owed.player_index == 0
    assert sorted(perm.card.name for perm in game.controlled_by(0)) == [
        "Doomsday Specter", "Hill Giant",
    ]
    assert [held.name for held in game.players[0].hand] == ["Drudge Skeletons"]


def _w1g3_cast_loon(set_pool, hand, library):
    """Cast Sawtooth Loon from a hand of the Loon plus *hand*, over *library*
    (top first), and answer its gating by returning the Loon itself — the only
    white or blue creature its controller has. Returns the game and seat 0."""
    game, card, _mine, _theirs = _w1g3_creature_table(
        set_pool, [], [], hands=(["Sawtooth Loon", *hand], []),
    )
    player = game.players[0]
    player.library[:] = [card(name) for name in library]
    result = game.cast_from_hand(0, "Sawtooth Loon")
    assert result.supported, result.details
    gating = next(c for c in game.pending_choices if c.kind == "permanent_set_choice")
    loon = next(p for p in game.controlled_by(0) if p.card.name == "Sawtooth Loon")
    assert game.resolve_pending_choice(
        gating.kind, 0, permanent_ids=[game.permanent_id_of(loon)]
    )
    return game, player  # _w1g3_cast_loon


def test_w1g3_sawtooth_loon_draws_two_then_bottoms_two_in_the_order_named(set_pool):
    """"When this creature enters, draw two cards, then put two cards from your
    hand on the bottom of your library." Two are drawn first — the put-back is
    chosen out of the hand *with* them in it — and exactly two go down, in the
    order their owner names them (CR 401.4): the last named is the very bottom."""
    game, player = _w1g3_cast_loon(
        set_pool, ["Counterspell"], ["Island", "Swamp", "Plains", "Mountain"],
    )
    owed = next(c for c in game.pending_choices if c.kind == "hand_to_library")
    names = [card.name for card in player.hand]

    assert owed.data["count"] == 2 and owed.data["destination"] == "bottom"
    assert sorted(names) == ["Counterspell", "Island", "Swamp"], "two drawn"
    assert not game.confirm_hand_to_library(0, [0]), "one card is not two"
    assert game.confirm_hand_to_library(
        0, [names.index("Swamp"), names.index("Counterspell")]
    )
    _w1g3_resolve_stack(game)

    assert [card.name for card in player.library] == [
        "Plains", "Mountain", "Swamp", "Counterspell",
    ]
    # The Island it drew and kept, and the Loon its own gating returned.
    assert sorted(card.name for card in player.hand) == ["Island", "Sawtooth Loon"]
    assert any("put 2 card(s) on the bottom" in line for line in game.log)


def test_w1g3_sawtooth_loon_bottoms_what_it_can_from_a_short_hand(set_pool):
    """CR 608.2's "as much as possible": an empty library draws nothing, the
    hand holds one card, and that one card is what goes to the bottom."""
    game, player = _w1g3_cast_loon(set_pool, ["Counterspell"], [])
    owed = next(c for c in game.pending_choices if c.kind == "hand_to_library")

    assert owed.data["count"] == 1
    assert game.confirm_hand_to_library(0, [0])
    _w1g3_resolve_stack(game)

    assert [card.name for card in player.library] == ["Counterspell"]
    assert [card.name for card in player.hand] == ["Sawtooth Loon"]
