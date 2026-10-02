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


# --- W1G5: library, hand and graveyard ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.revealed_hands import hand_revealed_to as _w1g5_hand_revealed_to
from engine.targeting import derive_activation_spec as _w1g5_activation_spec
from tests.helpers import client as _w1g5_client
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, name, *, seat=0, **players):
    """A duel with *name* on *seat*'s battlefield, free to tap. Keyword
    arguments are the two seats' zones (``a_library=…``, ``b_hand=…``). W1G5's
    own rig."""
    a = _W1G5PlayerState(
        name="W1G5-A",
        **{k[2:]: v for k, v in players.items() if k.startswith("a_")},
    )
    b = _W1G5PlayerState(
        name="W1G5-B",
        **{k[2:]: v for k, v in players.items() if k.startswith("b_")},
    )
    game = _W1G5Game(players=[a, b])
    game.enforce_mana_costs = False
    perm = _W1G5Permanent(card=set_pool("NEM")[name])
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return game, perm, a, b


def test_w1g5_lin_sivvi_search_finds_only_a_rebel_within_x(set_pool):
    """"{X}, {T}: Search your library for a Rebel permanent card with mana
    value X or less, put it onto the battlefield, then shuffle."

    Both narrowings are asked of the live prompt rather than of the payload:
    with X paid as 2, the four-mana Rebel and the two-mana Goblin are each
    refused as answers, and only the two-mana Rebel enters. A search that
    dropped the bound would take the Poacher; one that dropped the subtype
    would take the Toady.
    """
    nem = set_pool("NEM")
    game, lin, me, _ = _w1g5_table(
        set_pool, "Lin Sivvi, Defiant Hero",
        a_library=[nem["Skyshroud Poacher"], nem["Defiant Falcon"], nem["Mogg Toady"]],
    )

    result = game.activate_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=0, x_value=2
    )
    assert result.supported, result.details
    assert lin.tapped, "{T} is part of the cost"
    assert not game.confirm_search_library(0, 0), "mana value 4 is more than X"
    assert not game.confirm_search_library(0, 2), "a Goblin is not a Rebel"
    assert game.confirm_search_library(0, 1)
    game._settle()

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Defiant Falcon", "Lin Sivvi, Defiant Hero",
    ]
    assert sorted(c.name for c in me.library) == ["Mogg Toady", "Skyshroud Poacher"]


def test_w1g5_lin_sivvi_x_is_the_bound_not_a_constant(set_pool):
    """The same library at X = 4 admits the Poacher: the bound is the
    activation's own X, resolved when the search is armed (CR 601.2b)."""
    nem = set_pool("NEM")
    game, _, _, _ = _w1g5_table(
        set_pool, "Lin Sivvi, Defiant Hero",
        a_library=[nem["Skyshroud Poacher"], nem["Defiant Falcon"]],
    )
    game.activate_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=0, x_value=4
    )
    assert game.confirm_search_library(0, 0)
    game._settle()
    assert "Skyshroud Poacher" in [p.card.name for p in game.controlled_by(0)]


def test_w1g5_lin_sivvi_bottoms_only_a_rebel_card(set_pool):
    """"{3}: Put target Rebel card from your graveyard on the bottom of your
    library."

    The subtype narrows three readers at once and each is asserted: the picker
    offers only the Rebel, an announcement naming the Goblin is refused with
    the {3} still in the pool (CR 601.2c precedes 601.2h), and the Rebel goes
    under the library rather than on top of it.
    """
    nem = set_pool("NEM")
    game, _, me, _ = _w1g5_table(
        set_pool, "Lin Sivvi, Defiant Hero",
        a_graveyard=[nem["Mogg Toady"], nem["Defiant Falcon"]],
        a_library=[nem["Wild Mammoth"]],
    )
    ability = _w1g5_compile(nem["Lin Sivvi, Defiant Hero"]).activated_abilities[1]
    spec = _w1g5_activation_spec(ability)
    assert spec["kind"] == "graveyard_creature"
    assert spec["graveyard_subtypes"] == ["rebel"]
    assert "any_card" not in spec, "the subtype is the whole narrowing"

    game.enforce_mana_costs = True
    me.mana_pool["C"] = 3
    refused = game.activate_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=1,
        target_player_index=0, target_permanent_index=0,
    )
    assert not refused.supported
    assert me.mana_pool["C"] == 3, "a refused announcement pays nothing"
    assert [c.name for c in me.graveyard] == ["Mogg Toady", "Defiant Falcon"]

    taken = game.activate_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=1,
        target_player_index=0, target_permanent_index=1,
    )
    assert taken.supported, taken.details
    game._settle()
    assert [c.name for c in me.graveyard] == ["Mogg Toady"]
    assert [c.name for c in me.library] == ["Wild Mammoth", "Defiant Falcon"]


def _w1g5_thief_swing(set_pool, *, islands=2):
    """Rootwater Thief connects with seat 1, who holds three known cards in
    their library. Seat 0 is interactive so the "you may pay" waits. W1G5's
    own combat rig."""
    lea = set_pool("LEA")
    game, thief, me, them = _w1g5_table(
        set_pool, "Rootwater Thief",
        a_library=[lea["Forest"]] * 3,
        b_library=[lea["Lightning Bolt"], lea["Shivan Dragon"], lea["Giant Growth"]],
    )
    game.enforce_mana_costs = True
    lands = [_W1G5Permanent(card=lea["Island"]) for _ in range(islands)]
    for land in lands:
        game._put_permanent_onto_battlefield(0, land, None)
    game.interactive_seats = {0}
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.declare_attackers(0, [0])
    game.current_step = "declare_blockers"
    game.declare_blockers(1, {})
    game.current_step = "combat_damage"
    game.resolve_combat_damage(0)
    game._settle()
    return game, lands, me, them


def test_w1g5_rootwater_thief_exiles_from_the_damaged_players_library(set_pool):
    """"Whenever this creature deals combat damage to a player, you may pay
    {2}. If you do, search that player's library for a card and exile it, then
    the player shuffles."

    The {2} is paid inside a resolving trigger, where nobody gets a priority
    window to tap for mana, so the payment taps the two Islands itself. "That
    player" is the one the combat damage was dealt to — the search opens
    seat 1's library, not the Thief controller's — and the card goes to its
    owner's exile.
    """
    game, lands, me, them = _w1g5_thief_swing(set_pool)
    assert them.life == 19

    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None and offer.data["cost"] == {"generic": 2}
    assert game._resolve_optional_pay(offer, True, None)
    assert all(land.tapped for land in lands), "the payment tapped the lands"

    search = game.pending_choice_of("search_library", 0)
    assert search is not None and search.data["zone_seat"] == 1
    assert game.confirm_search_library(0, 1)
    game._settle()

    assert [c.name for c in them.exile] == ["Shivan Dragon"]
    assert sorted(c.name for c in them.library) == ["Giant Growth", "Lightning Bolt"]
    assert len(me.library) == 3 and me.exile == [], "the searcher's own zones are untouched"


def test_w1g5_rootwater_thief_decline_and_no_mana_search_nothing(set_pool):
    """"May": declining searches nothing — and with no untapped land the
    offer is never made at all (CR 601.2b offers only what a player is able to
    do), so the trigger resolves without a prompt and seat 1's library keeps
    all three cards."""
    game, _, _, them = _w1g5_thief_swing(set_pool)
    offer = game.pending_choice_of("optional_pay", 0)
    game._resolve_optional_pay(offer, False, None)
    game._settle()
    assert len(them.library) == 3 and them.exile == []

    game, _, _, them = _w1g5_thief_swing(set_pool, islands=0)
    assert game.pending_choice_of("optional_pay", 0) is None
    assert game.pending_choice_of("search_library", 0) is None
    assert len(them.library) == 3 and them.exile == []


def test_w1g5_wandering_eye_reveals_every_hand_including_its_controllers(set_pool):
    """"Players play with their hands revealed." — Revelation's line on a
    creature. Every hand to every seat, the controller's own included (that is
    what separates it from Telepathy), and only while the Eye is on the
    battlefield."""
    card = set_pool("NEM")["Wandering Eye"]
    assert _w1g5_compile(card).supported
    game, eye, _, _ = _w1g5_table(set_pool, "Wandering Eye", seat=1)

    assert _w1g5_hand_revealed_to(game, owner_seat=0, viewer_seat=1)
    assert _w1g5_hand_revealed_to(game, owner_seat=1, viewer_seat=0), (
        "the Eye's controller's hand is revealed too"
    )
    game.remove_from_battlefield(eye)
    assert not _w1g5_hand_revealed_to(game, owner_seat=1, viewer_seat=0)


def test_w1g5_wandering_eye_puts_the_hand_on_the_opponents_wire(set_pool):
    """The card is done only when a client receives the hand: the per-seat
    state payload is where "revealed" stops being a predicate and becomes card
    faces on the other player's screen."""
    from web.app import store

    created = _w1g5_client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "W1G5 Host",
            "guest_name": "W1G5 Guest", "host_colors": 2, "guest_colors": 2,
            "seed": 515,
        },
    ).json()
    sid = created["session_id"]
    _w1g5_client.post(f"/api/sessions/{sid}/join", json={"guest_name": "W1G5 Joiner"})
    game = store.get(sid).game

    def hand_on_wire(viewer, owner):
        state = _w1g5_client.get(
            f"/api/sessions/{sid}/state", params={"seat": viewer}
        ).json()
        return [
            c["name"] if isinstance(c, dict) else c
            for c in state["players"][owner]["hand"]
        ]

    assert set(hand_on_wire(0, 1)) == {"<hidden>"}
    eye = _W1G5Permanent(card=set_pool("NEM")["Wandering Eye"])
    game._put_permanent_onto_battlefield(0, eye, None)
    for viewer in (0, 1):
        owner = 1 - viewer
        assert hand_on_wire(viewer, owner) == [c.name for c in game.players[owner].hand]
    game.remove_from_battlefield(eye)
    assert set(hand_on_wire(0, 1)) == {"<hidden>"}
