"""Planeshift sorceries.

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


# --- W1G4: domain ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from tests.helpers import resolve_stack as _w1g4_resolve

_W1G4_FIVE = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _w1g4_board_card(set_pool, name):
    """A board permanent's card: Alpha's lands and bodies, else Antiquities
    (Mishra's Factory, a land with no basic land type) — pools kept separate
    and asked in that order."""
    for w1g4_code in ("LEA", "ATQ"):
        if name in set_pool(w1g4_code):
            return set_pool(w1g4_code)[name]
    raise KeyError(name)  # _w1g4_board_card


def _w1g4_sorcery_table(set_pool, spell, mine=(), theirs=(), interactive=()):
    """*spell* in seat 0's hand over two boards named in board order, each
    seat with a library to draw from (a draw off an empty one loses the game
    and would hide what the spell did)."""
    w1g4_pls, w1g4_lea = set_pool("PLS"), set_pool("LEA")
    w1g4_game = _W1G4Game(players=[
        _W1G4PlayerState(name="W1G4-A", hand=[w1g4_pls[spell]]),
        _W1G4PlayerState(name="W1G4-B"),
    ])
    w1g4_game.enforce_mana_costs = False
    w1g4_game.active_player_index = 0
    w1g4_game.interactive_seats = set(interactive)
    for w1g4_player in w1g4_game.players:
        w1g4_player.library = [w1g4_lea["Grizzly Bears"]] * 20
    w1g4_rows = []
    for w1g4_seat, w1g4_names in enumerate((mine, theirs)):
        w1g4_row = []
        for w1g4_name in w1g4_names:
            w1g4_perm = _W1G4Permanent(card=_w1g4_board_card(set_pool, w1g4_name))
            w1g4_game._put_permanent_onto_battlefield(w1g4_seat, w1g4_perm, None)
            w1g4_row.append(w1g4_perm)
        w1g4_rows.append(w1g4_row)
    return w1g4_game, w1g4_rows[0], w1g4_rows[1]  # _w1g4_sorcery_table


def _w1g4_land_names(game, seat):
    return sorted(
        w1g4_perm.card.name for w1g4_perm in game.controlled_by(seat)
    )  # _w1g4_land_names


def test_w1g4_allied_strategies_offers_a_player(set_pool):
    card = set_pool("PLS")["Allied Strategies"]
    program = _w1g4_compile(card)
    assert program.supported, program.reason
    assert _w1g4_cast_spec(card, program) == {"kind": "player"}


def test_w1g4_allied_strategies_counts_the_targets_lands_not_the_casters(set_pool):
    """"Target player draws a card for each basic land type among lands
    **they** control." Aimed at an opponent holding three types on four lands
    it draws them three, whatever the caster's five types are."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", mine=_W1G4_FIVE,
        theirs=["Forest", "Forest", "Tropical Island", "Mountain"],
    )
    cast = game.cast_from_hand(0, "Allied Strategies", target_player_index=1)
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    assert [len(player.hand) for player in game.players] == [0, 3]
    assert "W1G4-B drew 3 cards" in game.log


def test_w1g4_allied_strategies_aimed_at_its_caster_draws_their_domain(set_pool):
    """The same sentence with the caster as the target: five types, five
    cards — and the opponent's single Forest is nobody's draw."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", mine=_W1G4_FIVE, theirs=["Forest"],
    )
    assert game.cast_from_hand(0, "Allied Strategies", target_player_index=0).supported
    _w1g4_resolve(game)
    assert [len(player.hand) for player in game.players] == [5, 0]


def test_w1g4_allied_strategies_counts_at_resolution_and_types_not_lands(set_pool):
    """CR 608.2h: counted once, as the spell resolves — a dual land that
    arrives while it is on the stack adds its two types, and four Forests
    beside it are still one."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", theirs=["Forest"] * 4,
    )
    assert game.queue_from_hand(0, "Allied Strategies", target_player_index=1).supported
    game._put_permanent_onto_battlefield(
        1, _W1G4Permanent(card=set_pool("LEA")["Badlands"]), None
    )
    _w1g4_resolve(game)
    assert len(game.players[1].hand) == 3

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", mine=_W1G4_FIVE,
    )
    assert game.cast_from_hand(0, "Allied Strategies", target_player_index=1).supported
    _w1g4_resolve(game)
    assert [len(player.hand) for player in game.players] == [0, 0], (
        "a target with no lands draws nothing"
    )


def test_w1g4_they_control_binds_only_to_a_chosen_player():
    """The rewrite is for the player the sentence *targeted*. "Each player …
    they control" and "you … they control" name no chosen seat, and the count
    refuses rather than falling back to whichever board the resolution held."""
    from engine.grammar import compile_line

    bound = compile_line("Target opponent draws a card for each creature they control.")
    assert bound.usable
    assert bound.instructions[0].payload["x_from_count"]["owner"] == "target_player"
    for line in (
        "Each player draws a card for each land they control.",
        "You draw a card for each land they control.",
    ):
        assert not compile_line(line).usable, line


def test_w1g4_planar_overlay_names_no_target(set_pool):
    card = set_pool("PLS")["Planar Overlay"]
    program = _w1g4_compile(card)
    assert program.supported, program.reason
    assert _w1g4_cast_spec(card, program) is None


def test_w1g4_planar_overlay_each_player_returns_one_land_per_basic_type(set_pool):
    """"Each player chooses a land they control of each basic land type.
    Return those lands to their owners' hands." A headless table takes the
    largest choice in board order: one Plains of two, the Forest, and the
    Tropical Island as the Island. The spare Plains, a land with no basic type
    and everything that is not a land stay where they are, and nothing is
    sacrificed — this is Global Ruin's choice with the other half moving."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay",
        mine=["Plains", "Plains", "Forest", "Tropical Island", "Grizzly Bears",
              "Mishra's Factory"],
        theirs=["Mountain", "Mountain", "Island", "Black Lotus"],
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert _w1g4_land_names(game, 0) == ["Grizzly Bears", "Mishra's Factory", "Plains"]
    assert _w1g4_land_names(game, 1) == ["Black Lotus", "Mountain"]
    assert sorted(c.name for c in game.players[0].hand) == [
        "Forest", "Plains", "Tropical Island",
    ]
    assert sorted(c.name for c in game.players[1].hand) == ["Island", "Mountain"]
    assert [c.name for c in game.players[0].graveyard] == ["Planar Overlay"]
    assert not game.players[1].graveyard
    assert (
        "W1G4-B returned Mountain, Island to their owners' hands (Planar Overlay)"
        in game.log
    )


def test_w1g4_planar_overlay_a_dual_land_is_chosen_for_one_type(set_pool):
    """A Tropical Island is a Forest and an Island and is *the* land for one
    of them — the constraint Global Ruin's keep has, on the same matching.
    Alone it is the only land returned; beside a Forest it is the Island and
    both go; five duals can each stand for a different type and all return."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Tropical Island", "Mishra's Factory"],
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Tropical Island"]

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Forest", "Tropical Island"],
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert not _w1g4_land_names(game, 0)

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay",
        mine=["Forest", "Tropical Island", "Tundra", "Badlands", "Taiga", "Forest"],
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert _w1g4_land_names(game, 0) == ["Forest"], "six lands, five types"


def test_w1g4_planar_overlay_asks_the_player_and_checks_the_answer(set_pool):
    """The choice is a decision each seat owes (CR 608.2d), and the spell
    stays on the stack until it is made. Two Plains cannot both be chosen —
    there is one Plains — a short list is refused, and so is a land of no
    basic type; the prompt says which fate it is deciding."""
    game, mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay",
        mine=["Plains", "Plains", "Tropical Island", "Forest", "Swamp",
              "Mishra's Factory"],
        theirs=["Mountain"], interactive=(0,),
    )
    plains_a, plains_b, tropical, forest, swamp, factory = (
        p.permanent_id for p in mine
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index, c.data["fate"]) for c in game.pending_choices] == [
        ("keep_permanents", 0, "return_chosen_to_hand")
    ]
    assert game.stack and game.waiting_prompt() is not None
    # The seat that is not interactive has already chosen and returned.
    assert [c.name for c in game.players[1].hand] == ["Mountain"]

    assert not game.confirm_keep_permanents(0, [plains_a, plains_b, tropical, forest])
    assert not game.confirm_keep_permanents(0, [plains_a])
    assert not game.confirm_keep_permanents(0, [plains_a, tropical, forest, factory])
    assert [c.kind for c in game.pending_choices] == ["keep_permanents"]
    assert len(list(game.controlled_by(0))) == 6, "a refused answer moves nothing"

    # The second Plains, the Tropical Island as the Island, Forest, Swamp.
    assert game.confirm_keep_permanents(0, [plains_b, tropical, forest, swamp])
    _w1g4_resolve(game)
    assert _w1g4_land_names(game, 0) == ["Mishra's Factory", "Plains"]
    assert game.is_on_battlefield(mine[0]) and not game.is_on_battlefield(mine[1])
    assert sorted(c.name for c in game.players[0].hand) == [
        "Forest", "Plains", "Swamp", "Tropical Island",
    ]


def test_w1g4_planar_overlay_returns_a_land_to_its_owners_hand(set_pool):
    """"…to their **owners'** hands" (CR 400.3): a land this seat controls and
    another seat owns is this seat's to choose and that seat's to pick up."""
    from engine.control import change_control

    game, mine, theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Forest"], theirs=["Island"],
    )
    change_control(theirs[0], 0, source=mine[0])
    game._sync_control()
    assert _w1g4_land_names(game, 0) == ["Forest", "Island"]
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Forest"]
    assert [c.name for c in game.players[1].hand] == ["Island"]
    assert not list(game.controlled_by(0)) and not list(game.controlled_by(1))


def test_w1g4_planar_overlay_asks_nobody_with_no_basic_land_type(set_pool):
    """A seat none of whose lands has a basic land type has nothing to choose
    and nothing to return, and is not prompted; and the count is of computed
    types — under Blood Moon a Mishra's Factory is a Mountain and goes back."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Mishra's Factory"],
        theirs=["Grizzly Bears"], interactive=(0, 1),
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert not game.pending_choices and not game.stack
    assert _w1g4_land_names(game, 0) == ["Mishra's Factory"]

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Planar Overlay", mine=["Mishra's Factory"],
    )
    game._put_permanent_onto_battlefield(
        1, _W1G4Permanent(card=set_pool("DRK")["Blood Moon"]), None
    )
    assert game.cast_from_hand(0, "Planar Overlay").supported
    _w1g4_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Mishra's Factory"]


def test_w1g4_the_return_fate_is_the_whole_paragraph_or_nothing(set_pool):
    """The choice with no fate behind it, or with "those" naming a different
    noun, is not this production's — a card that prompted every seat and then
    moved nothing would report supported. And Global Ruin, which shares the
    chooser, still carries no ``fate`` key: its payload is byte-identical."""
    from engine.grammar import compile_line

    chosen = "Each player chooses a land they control of each basic land type."
    whole = compile_line(f"{chosen} Return those lands to their owners' hands.")
    assert whole.usable
    assert whole.instructions[0].payload["fate"] == "return_chosen_to_hand"
    assert [slot["filter"]["subtype_filter"] for slot in whole.instructions[0].payload["slots"]] == [
        "plains", "island", "swamp", "mountain", "forest",
    ]
    for line in (
        chosen,
        f"{chosen} Return those creatures to their owners' hands.",
        f"{chosen} Return those lands to your hand.",
    ):
        assert not compile_line(line).usable, line
    ruin = _w1g4_compile(set_pool("INV")["Global Ruin"])
    assert "fate" not in ruin.instructions[0].payload


def test_w1g4_planar_overlay_prompt_reaches_the_client_as_a_return(set_pool):
    """Through the real action endpoint: the cast, the priority pass that
    resolves it, the prompt the state carries, and the answer. The payload
    names the fate so the modal can say "return" rather than "keep", offers
    only the lands a slot could take (not the Factory, not the Bears), and the
    count is the matching's — three, for two Plains, a Tropical Island and a
    Forest. A selection the engine refuses is a 400 and moves nothing."""
    from fastapi.testclient import TestClient

    from web.app import app, store

    client = TestClient(app)
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "W1G4", "host_colors": 2,
        "guest_colors": 2, "seed": 4104,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    session = store.get(session_id)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    game.players[0].hand[:] = [set_pool("PLS")["Planar Overlay"]]
    board = []
    for name in ("Plains", "Plains", "Tropical Island", "Forest",
                 "Mishra's Factory", "Grizzly Bears"):
        perm = _W1G4Permanent(card=_w1g4_board_card(set_pool, name))
        game._put_permanent_onto_battlefield(0, perm, None)
        board.append(perm)
    game.start_priority_window(0)

    def act(**body):
        return client.post(
            f"/api/sessions/{session_id}/action", json={"seat": 0, **body}
        )

    def prompt():
        return client.get(
            f"/api/sessions/{session_id}/state", params={"seat": 0}
        ).json().get("keep_permanents")

    assert act(action="cast", card_name="Planar Overlay").status_code == 200
    assert act(action="pass_priority").status_code == 200
    offered = prompt()
    assert offered["fate"] == "return_chosen_to_hand"
    assert offered["keep_count"] == 3
    assert [entry["name"] for entry in offered["candidates"]] == [
        "Plains", "Plains", "Tropical Island", "Forest",
    ]
    plains_a, plains_b, tropical, forest = (p.permanent_id for p in board[:4])

    refused = act(
        action="keep_permanents_confirm",
        target_permanent_ids=[plains_a, plains_b, tropical],
    )
    assert refused.status_code == 400
    assert len(list(game.controlled_by(0))) == 6

    assert act(
        action="keep_permanents_confirm",
        target_permanent_ids=[plains_b, tropical, forest],
    ).status_code == 200
    assert prompt() is None
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Grizzly Bears", "Mishra's Factory", "Plains",
    ]
    assert sorted(c.name for c in game.players[0].hand) == [
        "Forest", "Plains", "Tropical Island",
    ]


# -- supported on arrival: driven, not built ----------------------------------


def test_w1g4_exotic_disease_drains_by_its_casters_domain(set_pool):
    """"Target player loses X life and you gain X life, where X is the number
    of basic land types among lands you control." Three lands holding five
    types drain five, whatever the target controls; the two halves read one X,
    so aimed at its own caster the spell is a wash."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Exotic Disease",
        mine=["Plains", "Tropical Island", "Badlands"], theirs=["Forest"],
    )
    cast = game.cast_from_hand(0, "Exotic Disease", target_player_index=1)
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    assert [player.life for player in game.players] == [25, 15]
    assert "Exotic Disease: W1G4-B lost 5 life (20 -> 15)" in game.log

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Exotic Disease", mine=["Forest", "Swamp"], theirs=_W1G4_FIVE,
    )
    assert game.cast_from_hand(0, "Exotic Disease", target_player_index=0).supported
    _w1g4_resolve(game)
    assert [player.life for player in game.players] == [20, 20]


def test_w1g4_exotic_disease_counts_at_resolution(set_pool):
    """CR 608.2h: X is the caster's board as the spell resolves — a dual land
    arriving while it is on the stack adds its two types — and a caster with
    no land drains nothing."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Exotic Disease", mine=["Forest"],
    )
    assert game.queue_from_hand(0, "Exotic Disease", target_player_index=1).supported
    game._put_permanent_onto_battlefield(
        0, _W1G4Permanent(card=set_pool("LEA")["Tundra"]), None
    )
    _w1g4_resolve(game)
    assert [player.life for player in game.players] == [23, 17]

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Exotic Disease", theirs=_W1G4_FIVE,
    )
    assert game.cast_from_hand(0, "Exotic Disease", target_player_index=1).supported
    _w1g4_resolve(game)
    assert [player.life for player in game.players] == [20, 20]
