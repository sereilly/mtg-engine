"""Invasion sorceries.

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


# --- W1G3: domain ---
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_cast_spec as _w1g3_cast_spec
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_sorcery_table(set_pool, spell, mine=(), theirs=(), interactive=()):
    """*spell* in seat 0's hand over two boards named in board order. Lands and
    bodies come from Alpha: what these cards read is which basic land *types*
    a board holds, and Alpha's dual lands are the ones that carry two."""
    w1g3_inv, w1g3_lea = set_pool("INV"), set_pool("LEA")
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[w1g3_inv[spell]]),
        _W1G3PlayerState(name="W1G3-B"),
    ])
    w1g3_game.enforce_mana_costs = False
    w1g3_game.active_player_index = 0
    w1g3_game.interactive_seats = set(interactive)
    w1g3_rows = []
    for w1g3_seat, w1g3_names in enumerate((mine, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_perm = _W1G3Permanent(card=w1g3_lea[w1g3_name])
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    return w1g3_game, w1g3_rows[0], w1g3_rows[1]  # _w1g3_sorcery_table


def _w1g3_names(game, seat):
    return [perm.card.name for perm in game.controlled_by(seat)]  # _w1g3_names


def test_w1g3_tribal_flames_offers_any_target(set_pool):
    card = set_pool("INV")["Tribal Flames"]
    assert _w1g3_cast_spec(card, _w1g3_compile(card))["kind"] == "any"


def test_w1g3_tribal_flames_deals_its_casters_domain_to_a_player(set_pool):
    """"Tribal Flames deals X damage to any target, where X is the number of
    basic land types among lands you control." Three lands, four types."""
    game, _mine, _theirs = _w1g3_sorcery_table(
        set_pool, "Tribal Flames",
        mine=["Plains", "Tropical Island", "Badlands"], theirs=["Forest"] * 5,
    )
    assert game.cast_from_hand(0, "Tribal Flames", target_player_index=1).supported
    _w1g3_resolve(game)
    assert game.players[1].life == 15
    assert game.players[0].life == 20


def test_w1g3_tribal_flames_kills_a_creature_it_names(set_pool):
    """Aimed at a creature by id: five types kill a 6/4 and the player behind
    it takes nothing."""
    game, _mine, theirs = _w1g3_sorcery_table(
        set_pool, "Tribal Flames",
        mine=["Plains", "Island", "Swamp", "Mountain", "Forest"],
        theirs=["Grizzly Bears", "Craw Wurm"],
    )
    wurm = theirs[1]
    cast = game.cast_from_hand(
        0, "Tribal Flames", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id],
    )
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert _w1g3_names(game, 1) == ["Grizzly Bears"]
    assert game.players[1].life == 20


def test_w1g3_tribal_flames_counts_at_resolution(set_pool):
    """CR 608.2h: the number is taken once, as the spell resolves — a land
    that arrives while it is on the stack counts."""
    game, _mine, _theirs = _w1g3_sorcery_table(
        set_pool, "Tribal Flames", mine=["Mountain"],
    )
    assert game.queue_from_hand(0, "Tribal Flames", target_player_index=1).supported
    assert len(game.stack) == 1
    game._put_permanent_onto_battlefield(
        0, _W1G3Permanent(card=set_pool("LEA")["Tundra"]), None
    )
    _w1g3_resolve(game)
    assert game.players[1].life == 17


def test_w1g3_tribal_flames_with_no_lands_deals_nothing(set_pool):
    game, _mine, _theirs = _w1g3_sorcery_table(set_pool, "Tribal Flames")
    assert game.cast_from_hand(0, "Tribal Flames", target_player_index=1).supported
    _w1g3_resolve(game)
    assert game.players[1].life == 20


def test_w1g3_wandering_stream_gains_two_per_basic_land_type(set_pool):
    """"You gain 2 life for each basic land type among lands you control."
    Five lands holding four types is 8, not 10."""
    game, _mine, _theirs = _w1g3_sorcery_table(
        set_pool, "Wandering Stream",
        mine=["Plains", "Island", "Swamp", "Tropical Island", "Forest"],
        theirs=["Mountain"],
    )
    assert game.cast_from_hand(0, "Wandering Stream").supported
    _w1g3_resolve(game)
    assert game.players[0].life == 28
    assert "W1G3-A gained 8 life from Wandering Stream (20 -> 28)" in game.log


def test_w1g3_wandering_stream_ignores_the_opponents_lands(set_pool):
    game, _mine, _theirs = _w1g3_sorcery_table(
        set_pool, "Wandering Stream",
        theirs=["Plains", "Island", "Swamp", "Mountain", "Forest"],
    )
    assert game.cast_from_hand(0, "Wandering Stream").supported
    _w1g3_resolve(game)
    assert [player.life for player in game.players] == [20, 20]


def test_w1g3_ordered_migration_makes_a_bird_per_basic_land_type(set_pool):
    """"Create a 1/1 blue Bird creature token with flying for each basic land
    type among lands you control." Six lands, five types, five Birds."""
    game, _mine, _theirs = _w1g3_sorcery_table(
        set_pool, "Ordered Migration",
        mine=["Plains", "Island", "Swamp", "Tropical Island", "Forest", "Badlands"],
    )
    assert game.cast_from_hand(0, "Ordered Migration").supported
    _w1g3_resolve(game)
    birds = [perm for perm in game.controlled_by(0) if perm.metadata.get("is_token")]
    assert len(birds) == 5
    for bird in birds:
        assert (bird.effective_power, bird.effective_toughness) == (1, 1)
        assert bird.has_type("bird") and bird.is_creature
        assert bird.effective_colors == {"U"}
        assert game._has_keyword(bird, "flying")
    assert not [p for p in game.controlled_by(1) if p.metadata.get("is_token")]


def test_w1g3_ordered_migration_with_no_basic_types_makes_nothing(set_pool):
    game, _mine, _theirs = _w1g3_sorcery_table(set_pool, "Ordered Migration")
    assert game.cast_from_hand(0, "Ordered Migration").supported
    _w1g3_resolve(game)
    assert not list(game.controlled_by(0))


def test_w1g3_global_ruin_each_player_keeps_one_land_per_basic_type(set_pool):
    """"Each player chooses from the lands they control a land of each basic
    land type, then sacrifices the rest." A headless table takes the maximum
    keep: the three spare Plains and the two spare Mountains go, and nothing
    that is not a land is touched."""
    game, mine, theirs = _w1g3_sorcery_table(
        set_pool, "Global Ruin",
        mine=["Plains", "Plains", "Plains", "Plains", "Forest", "Grizzly Bears"],
        theirs=["Mountain", "Mountain", "Mountain", "Island", "Black Lotus"],
    )
    assert game.cast_from_hand(0, "Global Ruin").supported
    _w1g3_resolve(game)
    assert sorted(_w1g3_names(game, 0)) == ["Forest", "Grizzly Bears", "Plains"]
    assert sorted(_w1g3_names(game, 1)) == ["Black Lotus", "Island", "Mountain"]
    assert [c.name for c in game.players[0].graveyard].count("Plains") == 3
    assert [c.name for c in game.players[1].graveyard].count("Mountain") == 2


def test_w1g3_global_ruin_a_dual_land_fills_one_type_only(set_pool):
    """A Tropical Island is a Forest and an Island and can be *the* land for
    one of them. Beside a Forest and an Island it is spare; beside only a
    Forest it is the Island, and all of them survive."""
    game, _mine, _theirs = _w1g3_sorcery_table(
        set_pool, "Global Ruin", mine=["Forest", "Island", "Tropical Island"],
    )
    assert game.cast_from_hand(0, "Global Ruin").supported
    _w1g3_resolve(game)
    assert len(_w1g3_names(game, 0)) == 2, "three lands, two types between them"

    game, _mine, _theirs = _w1g3_sorcery_table(
        set_pool, "Global Ruin",
        mine=["Forest", "Tropical Island", "Tundra", "Badlands", "Taiga"],
    )
    assert game.cast_from_hand(0, "Global Ruin").supported
    _w1g3_resolve(game)
    assert len(_w1g3_names(game, 0)) == 5, (
        "five lands can each stand for a different type "
        "(Forest, Island, Plains, Swamp, Mountain)"
    )


def test_w1g3_global_ruin_asks_the_player_and_checks_the_answer(set_pool):
    """The keeps are a decision each seat owes (CR 608.2d). Two Plains cannot
    both be kept — there is one Plains slot — and a short list is refused, so
    the spell stays on the stack until a legal keep is named."""
    game, mine, _theirs = _w1g3_sorcery_table(
        set_pool, "Global Ruin",
        mine=["Plains", "Plains", "Tropical Island", "Forest", "Swamp"],
        interactive=(0,),
    )
    plains_a, plains_b, tropical, forest, swamp = (p.permanent_id for p in mine)
    assert game.cast_from_hand(0, "Global Ruin").supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("keep_permanents", 0)
    ]
    assert game.stack and game.waiting_prompt() is not None

    assert not game.confirm_keep_permanents(0, [plains_a, plains_b, tropical, forest])
    assert not game.confirm_keep_permanents(0, [plains_a])
    assert [c.kind for c in game.pending_choices] == ["keep_permanents"]

    # Plains, the Tropical Island as the Island, Forest, Swamp.
    assert game.confirm_keep_permanents(0, [plains_b, tropical, forest, swamp])
    _w1g3_resolve(game)
    assert sorted(_w1g3_names(game, 0)) == [
        "Forest", "Plains", "Swamp", "Tropical Island",
    ]
    assert not game.is_on_battlefield(mine[0]) and game.is_on_battlefield(mine[1])
    assert [c.name for c in game.players[0].graveyard] == ["Plains", "Global Ruin"]


def test_w1g3_global_ruin_takes_a_land_with_no_basic_type(set_pool):
    """"The rest" is every land not chosen, and a land with no basic land type
    can be chosen for none of the five."""
    game, _mine, _theirs = _w1g3_sorcery_table(set_pool, "Global Ruin", mine=["Swamp"])
    library = _W1G3Permanent(card=set_pool("ARN")["Library of Alexandria"])
    game._put_permanent_onto_battlefield(0, library, None)
    assert library.has_type("land") and library.basic_land_types == ()

    assert game.cast_from_hand(0, "Global Ruin").supported
    _w1g3_resolve(game)
    assert _w1g3_names(game, 0) == ["Swamp"]
    assert "Library of Alexandria" in [c.name for c in game.players[0].graveyard]
