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


# --- W1G2: split cards ---
import pytest as _w1g2_pytest

from engine import Game as _W1G2SorceryGame
from engine.card_loader import manifest_set_path as _w1g2_manifest_set_path
from engine.faces import face_cards as _w1g2_sorcery_faces
from engine.models import Permanent as _W1G2SorceryPermanent
from engine.models import PlayerState as _W1G2SorceryPlayerState
from engine.oracle import compile_card_oracle as _w1g2_sorcery_compile
from engine.targeting import derive_cast_spec as _w1g2_sorcery_cast_spec


def _w1g2_sorcery_duel(set_pool):
    """Two seats that pay for what they cast — the halves of a split card are
    told apart by their costs (CR 709.3a)."""
    filler = set_pool("LEA")["Forest"]
    game = _W1G2SorceryGame(players=[
        _W1G2SorceryPlayerState(name="P0", library=[filler] * 10),
        _W1G2SorceryPlayerState(name="P1", library=[filler] * 10),
    ])
    game.enforce_mana_costs = True
    w1g2_sorcery_seats = (game, game.players[0], game.players[1])
    return w1g2_sorcery_seats


def _w1g2_sorcery_permanent(game, set_pool, seat, name, code="LEA"):
    w1g2_sorcery_entered = _W1G2SorceryPermanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, w1g2_sorcery_entered, None)
    return w1g2_sorcery_entered


def test_w1g2_the_two_sorcery_split_cards_compile_one_spell_per_half(set_pool):
    expected = {
        "Pain // Suffering": [("Pain", "{B}", {"kind": "player"}),
                              ("Suffering", "{3}{R}", {"kind": "land"})],
        "Assault // Battery": [("Assault", "{R}", {"kind": "any"}),
                               ("Battery", "{3}{G}", None)],
    }
    for name, halves in expected.items():
        card = set_pool("INV")[name]
        assert _w1g2_sorcery_compile(card).supported
        found = [
            (half.name, half.mana_cost,
             _w1g2_sorcery_cast_spec(half, _w1g2_sorcery_compile(half)))
            for half in _w1g2_sorcery_faces(card)
        ]
        assert found == halves, name
        assert all(half.type_line == "Sorcery" for half in _w1g2_sorcery_faces(card))


def test_w1g2_pain_makes_the_target_player_discard_a_card_of_their_choice(set_pool):
    """`Target player discards a card.` The **discarding** player chooses
    (CR 701.9a), so an interactive seat is asked; one card leaves that hand."""
    game, p0, p1 = _w1g2_sorcery_duel(set_pool)
    game.interactive_seats = {1}
    split = set_pool("INV")["Pain // Suffering"]
    p0.hand.append(split)
    p1.hand.extend([set_pool("LEA")["Grizzly Bears"], set_pool("LEA")["Lightning Bolt"]])
    p0.mana_pool["B"] = 1

    assert game.queue_from_hand(0, "Pain", target_player_index=1).supported
    game.resolve_top_of_stack()
    owed = next(iter(game.pending_choices_of("discard")))
    assert owed.player_index == 1 and owed.data["count"] == 1
    assert len(p1.hand) == 2, "nothing is discarded until P1 chooses"
    assert p0.graveyard == [], "CR 608.2n: Pain is not binned mid-resolution"
    game.auto_resolve_pending_choices()
    game._settle()

    assert len(p1.hand) == 1 and len(p1.graveyard) == 1
    assert game.stack == [] and p0.graveyard == [split]
    assert p0.mana_pool["B"] == 0


def test_w1g2_suffering_destroys_a_land_and_only_a_land(set_pool):
    """`Destroy target land.` For {3}{R}; a creature is refused unpaid."""
    game, p0, p1 = _w1g2_sorcery_duel(set_pool)
    land = _w1g2_sorcery_permanent(game, set_pool, 1, "Forest")
    bears = _w1g2_sorcery_permanent(game, set_pool, 1, "Grizzly Bears")
    split = set_pool("INV")["Pain // Suffering"]
    p0.hand.append(split)
    p0.mana_pool["R"] = 4

    refused = game.cast_from_hand(0, "Suffering", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and p0.mana_pool["R"] == 4

    assert game.cast_from_hand(0, "Suffering", target_permanent_ids=[land.permanent_id]).supported
    assert [card.name for card in p1.graveyard] == ["Forest"]
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Grizzly Bears"]
    assert p0.mana_pool["R"] == 0 and p0.graveyard == [split]


def test_w1g2_assault_deals_two_damage_to_a_creature_or_a_player(set_pool):
    """`Assault deals 2 damage to any target.` The self-reference is the
    **half's** name — the reason a half compiles as a card of its own — and the
    spell is red: it is not green (CR 709.3b)."""
    game, p0, p1 = _w1g2_sorcery_duel(set_pool)
    bears = _w1g2_sorcery_permanent(game, set_pool, 1, "Grizzly Bears")
    split = set_pool("INV")["Assault // Battery"]
    p0.hand.extend([split, split])
    p0.mana_pool["R"] = 2

    assert game.queue_from_hand(0, "Assault", target_permanent_ids=[bears.permanent_id]).supported
    assert tuple(game._stack_item_colors(game.stack[-1])) == ("R",)
    game._settle()
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]

    assert game.cast_from_hand(0, "Assault", target_player_index=1).supported
    assert p1.life == 18
    assert "Assault resolved and moved to graveyard" in game.log
    assert p0.graveyard == [split, split] and p0.mana_pool["R"] == 0


def test_w1g2_battery_creates_a_three_three_green_elephant(set_pool):
    """`Create a 3/3 green Elephant creature token.` For {3}{G}, with no
    target to choose."""
    game, p0, _p1 = _w1g2_sorcery_duel(set_pool)
    split = set_pool("INV")["Assault // Battery"]
    p0.hand.append(split)
    p0.mana_pool["G"] = 4

    assert game.cast_from_hand(0, "Battery").supported

    (elephant,) = game.controlled_by(0)
    assert elephant.metadata.get("is_token")
    assert (elephant.effective_power, elephant.effective_toughness) == (3, 3)
    assert set(elephant.effective_colors) == {"G"}
    assert elephant.has_type("creature") and "Elephant" in elephant.effective_card.type_line
    assert p0.graveyard == [split] and p0.mana_pool["G"] == 0


@_w1g2_pytest.mark.slow
def test_w1g2_the_ai_casts_split_cards_as_halves_without_a_refusal():
    """The simulator deals whole split cards and its policy scores each half as
    the spell it is (`ai_policy.hand_spells`), pays for the one it picks and
    casts it by the half's name. A policy that proposed the *card* would be
    refused every turn (CR 709.3), and a half that reached a graveyard without
    becoming the whole card again would fail the zone-conservation audit under
    a name the deck never held."""
    from engine.ai_simulator import run_ai_simulation

    names = [
        "Assault // Battery", "Pain // Suffering", "Spite // Malice",
        "Stand // Deliver", "Wax // Wane",
    ]
    halves = {half for name in names for half in name.split(" // ")}
    report = run_ai_simulation(
        [_w1g2_manifest_set_path("INV", include_measured=True)],
        games=6, seed=77, max_turns=16, required_cards=names,
    )

    cast = {
        half for half in halves
        if any(f" cast {half} -> resolved" in line for line in report.log_lines)
    }
    assert len(cast) >= 4, f"only {sorted(cast)} were cast"
    refused = [
        key for key in report.refused_casts
        if key.split(":")[0] in halves | set(names)
    ]
    assert refused == []
    leaks = [
        issue.message for issue in report.issues
        if any(half in issue.message for half in halves)
        and "Unsupported card" not in issue.message
    ]
    w1g2_no_half_leaked = leaks == []
    assert w1g2_no_half_leaked, leaks


# --- W1G6: colour choices ---
# Wash Out ("…of the color of your choice"), Addle ("Choose a color. … a card of
# that color") and Searing Rays ("…the number of creatures of that color that
# player controls"). CR 608.2d: the colour is named while the spell resolves.
from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent


def _w1g6_spell_table(set_pool, spell, mine=(), theirs=(), *, their_hand=()):
    """Seat 0 (interactive) holds *spell* in hand and *mine* in play."""
    inv, lea = set_pool("INV"), set_pool("LEA")
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = False
    w1g6_game.interactive_seats = {0}
    w1g6_sides = []
    for seat, names in ((0, mine), (1, theirs)):
        side = []
        for name in names:
            perm = _W1G6Permanent(card=lea[name])
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            side.append(perm)
        w1g6_sides.append(side)
    w1g6_game.players[0].hand.append(inv[spell])
    w1g6_game.players[1].hand.extend(lea[name] for name in their_hand)
    return w1g6_game, w1g6_sides[0], w1g6_sides[1]  # _w1g6_spell_table


def _w1g6_board(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))  # _w1g6_board


def test_w1g6_wash_out_returns_every_permanent_of_the_colour_named_at_resolution(set_pool):
    """"Return all permanents of the color of your choice to their owners'
    hands." Cast "for red" by a caller that still sends a colour; green is
    named when it resolves and green is what goes — both players' green
    permanents, each to its owner, and nothing colourless or red."""
    game, _mine, _theirs = _w1g6_spell_table(
        set_pool, "Wash Out",
        ["Grizzly Bears", "Forest", "Hill Giant"],
        ["Llanowar Elves", "Grizzly Bears", "Mountain"],
    )
    assert game.queue_from_hand(0, "Wash Out", new_color="R").supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert _w1g6_board(game, 0) == ["Forest", "Grizzly Bears", "Hill Giant"], "not yet"
    assert game.confirm_color_choice(0, "G")
    from tests.helpers import resolve_stack

    resolve_stack(game)

    assert _w1g6_board(game, 0) == ["Forest", "Hill Giant"]
    assert _w1g6_board(game, 1) == ["Mountain"]
    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]
    assert sorted(card.name for card in game.players[1].hand) == [
        "Grizzly Bears", "Llanowar Elves",
    ]
    assert [card.name for card in game.players[0].graveyard] == ["Wash Out"]


def test_w1g6_wash_out_takes_the_default_colour_for_a_seat_nobody_asks(set_pool):
    """A non-interactive caster is not blocked: the default is the colour its
    opponents hold most of, and that colour is what is swept."""
    game, _mine, _theirs = _w1g6_spell_table(
        set_pool, "Wash Out", ["Grizzly Bears"], ["Hill Giant", "Hill Giant", "Llanowar Elves"],
    )
    game.interactive_seats = set()
    from tests.helpers import resolve_stack

    assert game.queue_from_hand(0, "Wash Out").supported
    resolve_stack(game)

    assert _w1g6_board(game, 1) == ["Llanowar Elves"]
    assert _w1g6_board(game, 0) == ["Grizzly Bears"]


def test_w1g6_addle_offers_only_the_cards_of_the_colour_chosen_first(set_pool):
    """"Choose a color. Target player reveals their hand and you choose a card
    of that color from it. That player discards that card." The colour is
    named before the hand is seen; the prompt then offers the green cards and
    refuses the red one, and exactly the chosen card is discarded."""
    game, _mine, _theirs = _w1g6_spell_table(
        set_pool, "Addle",
        their_hand=["Giant Growth", "Grizzly Bears", "Lightning Bolt", "Forest"],
    )
    assert game.queue_from_hand(0, "Addle", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert not any("revealed their hand" in line for line in game.log)
    assert game.confirm_color_choice(0, "G")

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("revealed_hand_pick", 0)
    ]
    assert game.pending_choices[0].data["legal_indices"] == [0, 1]
    assert not game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=2)
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=1)
    from tests.helpers import resolve_stack

    resolve_stack(game)

    assert [card.name for card in game.players[1].hand] == [
        "Giant Growth", "Lightning Bolt", "Forest",
    ]
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_w1g6_addle_takes_nothing_from_a_hand_with_no_card_of_that_colour(set_pool):
    """Blue is named against a hand with no blue card: the hand is revealed
    and nothing is chosen or discarded — never a card of some other colour."""
    game, _mine, _theirs = _w1g6_spell_table(
        set_pool, "Addle", their_hand=["Giant Growth", "Lightning Bolt"],
    )
    assert game.queue_from_hand(0, "Addle", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert game.confirm_color_choice(0, "U")
    from tests.helpers import resolve_stack

    resolve_stack(game)

    assert not game.pending_choices
    assert len(game.players[1].hand) == 2 and not game.players[1].graveyard


def test_w1g6_searing_rays_counts_each_players_creatures_of_the_chosen_colour(set_pool):
    """"Choose a color. Searing Rays deals damage to each player equal to the
    number of creatures of that color that player controls." Green: one green
    creature on the caster's side, two on the other. It arrived supported and
    dealt each player damage for *every* creature they had."""
    game, _mine, _theirs = _w1g6_spell_table(
        set_pool, "Searing Rays",
        ["Grizzly Bears", "Hill Giant"],
        ["Llanowar Elves", "Grizzly Bears", "Hill Giant"],
    )
    assert game.queue_from_hand(0, "Searing Rays").supported
    game.resolve_top_of_stack()
    assert game.confirm_color_choice(0, "G")
    from tests.helpers import resolve_stack

    resolve_stack(game)

    assert (game.players[0].life, game.players[1].life) == (19, 18)


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


# --- INTEGRATOR: Coalition Victory, where W1G3 and W1G5 met ---
import pytest as _int_pytest

from engine import Game as _IntGame
from engine import PlayerState as _IntPlayerState
from engine.models import Permanent as _IntPermanent
from tests.helpers import resolve_stack as _int_resolve_stack

_INT_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")
_INT_MONO = (
    "Savannah Lions", "Merfolk of the Pearl Trident", "Black Knight",
    "Mons's Goblin Raiders", "Grizzly Bears",
)


def _int_coalition_table(catalog_by_name, set_pool, lands, creatures):
    """Seat 0 controls *lands* and *creatures* and resolves Coalition Victory;
    returns who has lost."""
    game = _IntGame(players=[_IntPlayerState(name="A"), _IntPlayerState(name="B")])
    game.enforce_mana_costs = False
    for name in (*lands, *creatures):
        game.players[0].battlefield.append(_IntPermanent(card=catalog_by_name[name]))
    game.players[0].hand.append(set_pool("INV")["Coalition Victory"])
    assert game.cast_from_hand(0, "Coalition Victory").supported
    _int_resolve_stack(game)
    lost = [player.name for player in game.players if player.lost]
    return lost  # _int_coalition_table


@_int_pytest.mark.parametrize("lands,creatures,loser", [
    # One land of each basic land type and one creature of each colour.
    (_INT_BASICS, _INT_MONO, ["B"]),
    # A dual land answers two of the five types (CR 305.6), as a Tropical
    # Island answers "a Forest and an Island".
    (("Tundra", "Badlands", "Forest"), _INT_MONO, ["B"]),
    # One five-colour creature is a creature of each colour.
    (_INT_BASICS, ("Sliver Queen",), ["B"]),
    # One type short, one colour short, and a colourless creature: no win.
    (_INT_BASICS[:4], _INT_MONO, []),
    (_INT_BASICS, _INT_MONO[:4], []),
    (_INT_BASICS, ("Ornithopter",), []),
])
def test_int_coalition_victory_wins_on_both_halves_of_its_condition(
    catalog_by_name, set_pool, lands, creatures, loser
):
    """"You win the game if you control a land of each basic land type and a
    creature of each color." Declined by W1G3 one piece short — the colour half
    was W1G5's — and landed by neither: W1G3 reads "of each basic land type" as
    the five nouns it abbreviates, W1G5 reads "of each color" as a relation on
    one conjunct, and both were written at the same line of
    ``condition_counts.py`` in one wave. The merge keeps one reader per
    characteristic, and this is the card that needs both."""
    assert _int_coalition_table(catalog_by_name, set_pool, lands, creatures) == loser
# --- end INTEGRATOR: Coalition Victory ---


# --- W1G1: kicker ---
import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_sorcery_duel(set_pool, name, pool):
    """Seat 0 holds the INV sorcery *name* with *pool* floating; costs are
    charged, because a kicker is a price."""
    lea = set_pool("LEA")
    mine = _W1G1PlayerState(
        "Caster", library=[lea["Forest"]] * 10, hand=[set_pool("INV")[name]],
    )
    theirs = _W1G1PlayerState("Victim", library=[lea["Forest"]] * 10)
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    return game  # _w1g1_sorcery_duel


def _w1g1_board(game, set_pool):
    """A walker and a flier for the other seat, a walker for the caster."""
    lea = set_pool("LEA")
    placed = {}
    for seat, name in ((1, "Hill Giant"), (1, "Serra Angel"), (0, "Grizzly Bears")):
        permanent = _W1G1Permanent(card=lea[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        placed[name] = permanent
    return placed  # _w1g1_board


def _w1g1_settle(game):
    """Resolve the stack and answer what the resolution asked (Probe's own
    discard is a prompt owed after the spell has left the stack)."""
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g1_resolve_stack(game)  # _w1g1_settle


def test_w1g1_probe_kicked_makes_the_target_player_discard_two(set_pool):
    """"Draw three cards, then discard two cards. If this spell was kicked,
    target player discards two cards." Both halves, in the order written."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_duel(set_pool, "Probe", {"U": 3, "B": 2})
    game.players[1].hand.extend([lea["Mountain"], lea["Island"], lea["Swamp"]])
    result = game.cast_from_hand(
        0, "Probe", optional_cost_payments={"{1}{B}": 1}, target_player_index=1,
    )
    assert result.supported, result
    _w1g1_settle(game)

    assert len(game.players[0].hand) == 1          # drew 3, discarded 2
    assert len(game.players[0].graveyard) == 3     # two discards and Probe
    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 2


def test_w1g1_probe_unkicked_touches_nobody_else(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_sorcery_duel(set_pool, "Probe", {"U": 3, "B": 2})
    game.players[1].hand.extend([lea["Mountain"], lea["Island"], lea["Swamp"]])
    result = game.cast_from_hand(0, "Probe")
    assert result.supported, result
    _w1g1_settle(game)

    assert len(game.players[0].hand) == 1
    assert len(game.players[1].hand) == 3
    assert game.players[1].graveyard == []
    assert sum(game.players[0].mana_pool.values()) == 2


def test_w1g1_probe_names_a_player_only_when_kicked(set_pool):
    """CR 702.33g: the kicked-only part's target is chosen only if the spell
    was kicked. The spec a player is shown asks for nobody until the kicker is
    taken, and then for a player."""
    card = set_pool("INV")["Probe"]
    game = _w1g1_sorcery_duel(set_pool, "Probe", {"U": 3, "B": 2})
    plain = game.cast_target_spec(0, card)
    assert (plain["kind"], plain["requires_target"]) == ("none", False)
    assert [offer["label"] for offer in plain["cost_offers"]] == ["kicker"]

    kicked = game.cast_target_spec(0, card, optional_cost_payments={"{1}{B}": 1})
    assert (kicked["kind"], kicked["requires_target"]) == ("player", True)
    assert len(kicked["valid_targets"]) == 2


@_w1g1_pytest.mark.parametrize(
    "name,colour,kicked_dies,spared",
    [
        # "…to each creature **without** flying and each player."
        ("Breath of Darigaaz", "R", ("Hill Giant", "Grizzly Bears"), ("Serra Angel",)),
        # "…to each creature **with** flying and each player."
        ("Canopy Surge", "G", ("Serra Angel",), ("Hill Giant", "Grizzly Bears")),
    ],
)
def test_w1g1_the_instead_sweepers_deal_one_or_four(
    set_pool, name, colour, kicked_dies, spared
):
    """"<This> deals 1 damage to each creature … and each player. If this spell
    was kicked, it deals 4 damage … **instead**." One or the other, never both:
    unkicked nothing dies and each player loses 1; kicked the named half of the
    board dies and each player loses 4."""
    plain = _w1g1_sorcery_duel(set_pool, name, {colour: 4})
    board = _w1g1_board(plain, set_pool)
    assert plain.cast_from_hand(0, name).supported
    _w1g1_settle(plain)
    assert all(plain.is_on_battlefield(p) for p in board.values())
    assert [player.life for player in plain.players] == [19, 19]
    assert sum(plain.players[0].mana_pool.values()) == 2

    kicked = _w1g1_sorcery_duel(set_pool, name, {colour: 4})
    board = _w1g1_board(kicked, set_pool)
    assert kicked.cast_from_hand(
        0, name, optional_cost_payments={"{2}": 1}
    ).supported
    _w1g1_settle(kicked)
    assert [player.life for player in kicked.players] == [16, 16]
    for creature in kicked_dies:
        assert not kicked.is_on_battlefield(board[creature])
    for creature in spared:
        assert kicked.is_on_battlefield(board[creature])


def test_w1g1_hypnotic_cloud_is_one_card_or_three_never_four(set_pool):
    """"Target player discards a card. If this spell was kicked, **that
    player** discards three cards **instead**." One discard of one size from
    the one player the spell names."""
    lea = set_pool("LEA")
    for kick, left in ((None, 3), ("{4}", 1)):
        game = _w1g1_sorcery_duel(set_pool, "Hypnotic Cloud", {"B": 6})
        game.players[1].hand.extend(
            [lea["Mountain"], lea["Island"], lea["Swamp"], lea["Plains"]]
        )
        spec = game.cast_target_spec(
            0, set_pool("INV")["Hypnotic Cloud"],
            optional_cost_payments={kick: 1} if kick else None,
        )
        assert spec["kind"] == "player" and "max_targets" not in spec
        result = game.cast_from_hand(
            0, "Hypnotic Cloud",
            optional_cost_payments={kick: 1} if kick else None,
            target_player_index=1,
        )
        assert result.supported, result
        _w1g1_settle(game)
        assert len(game.players[1].hand) == left
        assert len(game.players[1].graveyard) == 4 - left
        assert game.players[0].hand == []
# end of the W1G1 sorceries block


# --- W1G7: piles ---
from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine import targeting as _w1g7_targeting
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import _mk_card as _w1g7_mk_card
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_body(name, power, toughness):
    """A vanilla creature permanent whose size is its name's business."""
    card = _w1g7_mk_card(name, "{2}", "Creature - Bear", "")
    card.raw.update({"power": str(power), "toughness": str(toughness)})
    w1g7_body_permanent = _W1G7Permanent(card=card)
    return w1g7_body_permanent


def _w1g7_table(set_pool, spell, *, mine=(), theirs=(), graveyard=(), interactive=()):
    """Seat 0 holding *spell* (an Invasion card), with the boards given."""
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", hand=[set_pool("INV")[spell]], battlefield=list(mine),
            graveyard=list(graveyard),
        ),
        _W1G7PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game._sync_control()
    game.interactive_seats = set(interactive)
    game.enforce_mana_costs = False
    game.start_turn(0)
    w1g7_spell_table = game
    return w1g7_spell_table


def _w1g7_board(game, seat):
    w1g7_board_names = [p.card.name for p in game.controlled_by(seat)]
    return w1g7_board_names


def _w1g7_owed(game):
    w1g7_owed_prompts = [(c.kind, c.player_index) for c in game.pending_choices]
    return w1g7_owed_prompts


def test_w1g7_do_or_die_the_caster_separates_and_the_victim_picks_the_pile_that_dies(set_pool):
    """"Separate all creatures target player controls into two piles. Destroy
    all creatures in the pile of that player's choice. They can't be
    regenerated."

    The caster separates (CR 608.2c — no subject is printed), the *targeted
    player* chooses, and the chosen pile is destroyed with no regeneration: the
    shield on the creature in it is not spent and does not save it. The other
    pile, the victim's land and the caster's own creature are untouched.
    """
    card = set_pool("INV")["Do or Die"]
    program = _w1g7_compile(card)
    assert program.supported, program.reason
    # "Target player" is announced (CR 601.2c), so the client is offered one.
    assert _w1g7_targeting.derive_cast_spec(card, program) == {"kind": "player"}

    shielded = _w1g7_body("Shielded", 2, 2)
    shielded.regeneration_shield += 1
    theirs = [
        shielded, _w1g7_body("Second", 3, 3), _w1g7_body("Third", 1, 1),
        _W1G7Permanent(card=set_pool("LEA")["Forest"]),
    ]
    game = _w1g7_table(
        set_pool, "Do or Die", mine=[_w1g7_body("Mine", 4, 4)], theirs=theirs,
        interactive=[0, 1],
    )
    assert game.cast_from_hand(0, "Do or Die", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_owed(game) == [("pile_split", 0)], "the caster separates"
    split = game.pending_choice_of("pile_split", 0)
    # Only the targeted player's creatures are in the piles — not their land,
    # not the caster's creature.
    assert len(split.data["_group"].items) == 3
    assert game.confirm_pile_split(0, [0, 2])
    assert _w1g7_owed(game) == [("pile_choice", 1)], "that player chooses"
    assert game.confirm_pile_choice(1, 0)

    assert _w1g7_board(game, 1) == ["Second", "Forest"], game.log
    assert sorted(c.name for c in game.players[1].graveyard) == ["Shielded", "Third"]
    assert _w1g7_board(game, 0) == ["Mine"]
    assert not game.stack and not game.pending_choices


def test_w1g7_do_or_die_headless_seats_split_evenly_and_keep_the_better_pile(set_pool):
    """Both decisions have a default that reads the board. The separator's is
    the most even split by value — a 5/5 against a 3/3 and a 1/1 here is not
    even, so the 5/5 stands alone against the other two — and the victim,
    choosing which of their own piles dies, gives up the lesser one."""
    theirs = [
        _w1g7_body("Giant", 6, 6), _w1g7_body("Middle", 2, 2),
        _w1g7_body("Runt", 1, 1),
    ]
    game = _w1g7_table(set_pool, "Do or Die", theirs=theirs)
    assert game.cast_from_hand(0, "Do or Die", target_player_index=1).supported
    _w1g7_resolve_stack(game)

    assert _w1g7_board(game, 1) == ["Giant"], game.log
    assert sorted(c.name for c in game.players[1].graveyard) == ["Middle", "Runt"]


def test_w1g7_death_or_glory_an_opponent_exiles_one_pile_and_the_other_returns(set_pool):
    """"Separate all creature cards in your graveyard into two piles. Exile the
    pile of an opponent's choice and return the other to the battlefield."

    The caster separates their own graveyard's **creature** cards — the
    instant among them is in neither pile and stays put — and the opponent
    chooses which pile is exiled. The two Grizzly Bears are one
    ``CardDefinition`` object, as two copies in a deck always are, and they go
    into different piles: one is exiled and one comes back, which only a
    graveyard *index* can say (CR 700.3c keeps the graveyard's order).
    """
    program = _w1g7_compile(set_pool("INV")["Death or Glory"])
    assert program.supported, program.reason

    lea = set_pool("LEA")
    graveyard = [
        lea["Shivan Dragon"], lea["Grizzly Bears"], lea["Lightning Bolt"],
        lea["Grizzly Bears"], lea["Serra Angel"],
    ]
    game = _w1g7_table(
        set_pool, "Death or Glory", graveyard=graveyard, interactive=[0, 1],
    )
    assert game.cast_from_hand(0, "Death or Glory").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_owed(game) == [("pile_split", 0)]
    split = game.pending_choice_of("pile_split", 0)
    assert split.data["_group"].items == [0, 1, 3, 4], "creature cards, by index"
    # Dragon and the first Bears against the second Bears and the Angel.
    assert game.confirm_pile_split(0, [0, 1])
    assert _w1g7_owed(game) == [("pile_choice", 1)], "an opponent chooses"
    assert game.confirm_pile_choice(1, 0)

    caster = game.players[0]
    assert sorted(c.name for c in caster.exile) == ["Grizzly Bears", "Shivan Dragon"]
    assert sorted(_w1g7_board(game, 0)) == ["Grizzly Bears", "Serra Angel"], game.log
    assert [c.name for c in caster.graveyard] == ["Lightning Bolt", "Death or Glory"]
    assert not game.stack and not game.pending_choices


def test_w1g7_death_or_glory_headless_the_opponent_exiles_the_better_pile(set_pool):
    """The opponent's default reads the piles and exiles the more valuable one
    — it is choosing *against* the player the cards belong to."""
    lea = set_pool("LEA")
    graveyard = [lea["Shivan Dragon"], lea["Grizzly Bears"], lea["Scryb Sprites"]]
    game = _w1g7_table(set_pool, "Death or Glory", graveyard=graveyard)
    assert game.cast_from_hand(0, "Death or Glory").supported
    _w1g7_resolve_stack(game)

    caster = game.players[0]
    assert [c.name for c in caster.exile] == ["Shivan Dragon"], game.log
    assert sorted(_w1g7_board(game, 0)) == ["Grizzly Bears", "Scryb Sprites"]


def test_w1g7_bend_or_break_every_player_separates_and_an_opponent_picks_what_is_destroyed(set_pool):
    """"Each player separates all nontoken lands they control into two piles.
    For each player, one of their piles is chosen by one of their opponents of
    their choice. Destroy all lands in the chosen piles. Tap all lands in the
    other piles."

    Four decisions at two seats, in APNAP order (CR 101.4, CR 608.2e): both
    separations first, then both choices — each made by the *other* player —
    and only then do the fates happen, over both players' piles at once. A
    creature is in nobody's pile.
    """
    program = _w1g7_compile(set_pool("INV")["Bend or Break"])
    assert program.supported, program.reason

    lea = set_pool("LEA")

    def lands(*names):
        w1g7_lands = [_W1G7Permanent(card=lea[name]) for name in names]
        return w1g7_lands

    game = _w1g7_table(
        set_pool, "Bend or Break",
        mine=lands("Forest", "Mountain", "Plains"),
        theirs=lands("Island", "Swamp") + [_w1g7_body("Bystander", 2, 2)],
        interactive=[0, 1],
    )
    assert game.cast_from_hand(0, "Bend or Break").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_owed(game) == [("pile_split", 0)], "the active player separates first"
    assert game.confirm_pile_split(0, [0])
    assert _w1g7_owed(game) == [("pile_split", 1)]
    assert len(game.pending_choices[0].data["_group"].items) == 2, "lands only"
    assert game.confirm_pile_split(1, [0, 1])
    # Nothing has happened to any land yet: every choice comes first.
    assert all(not p.tapped for p in game.all_permanents())
    assert _w1g7_owed(game) == [("pile_choice", 1)], "P2 chooses between P1's piles"
    assert game.confirm_pile_choice(1, 1)
    assert _w1g7_owed(game) == [("pile_choice", 0)], "P1 chooses between P2's piles"
    # P2 put both lands in one pile; P1 picks the empty one, so nothing of
    # P2's is destroyed and both are tapped.
    assert game.confirm_pile_choice(0, 1)

    assert [(p.card.name, p.tapped) for p in game.controlled_by(0)] == [
        ("Forest", True),
    ], game.log
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Bend or Break", "Mountain", "Plains",
    ]
    assert [(p.card.name, p.tapped) for p in game.controlled_by(1)] == [
        ("Island", True), ("Swamp", True), ("Bystander", False),
    ]
    assert not game.stack and not game.pending_choices


def test_w1g7_bend_or_break_headless_everyone_loses_about_half(set_pool):
    """Headless, every separator splits as evenly as it can and every chooser
    — choosing against the lands' owner — destroys the bigger pile."""
    lea = set_pool("LEA")
    mine = [_W1G7Permanent(card=lea["Forest"]) for _ in range(3)]
    theirs = [_W1G7Permanent(card=lea["Island"]) for _ in range(4)]
    game = _w1g7_table(set_pool, "Bend or Break", mine=mine, theirs=theirs)
    assert game.cast_from_hand(0, "Bend or Break").supported
    _w1g7_resolve_stack(game)

    assert [(p.card.name, p.tapped) for p in game.controlled_by(0)] == [("Forest", True)]
    assert [(p.card.name, p.tapped) for p in game.controlled_by(1)] == [
        ("Island", True), ("Island", True),
    ], game.log


def _w1g7_sized_card(name, type_line, mana_value):
    """A card with a stated mana value and no text."""
    from engine.models import CardDefinition

    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update({"power": "2", "toughness": "2"})
    w1g7_sized = CardDefinition(
        name=name, mana_cost="{%d}" % mana_value if mana_value else "",
        cmc=float(mana_value), type_line=type_line, oracle_text="", colors=(),
        color_identity=(), keywords=(), produced_mana=(), raw=raw,
    )
    return w1g7_sized


def test_w1g7_desperate_research_takes_every_copy_of_the_named_card_and_exiles_the_rest(set_pool):
    """"Choose a card name other than a basic land card name. Reveal the top
    seven cards of your library and put all of them with that name into your
    hand. Exile the rest."

    The name is chosen first and the printed bound on it is enforced where the
    choice is made: a basic land's name — plain, snow-covered or Wastes — is
    refused, not repaired. Both Shivan Dragons among the top seven go to the
    hand, the other five are **exiled** (not binned), and the eighth card never
    moves.
    """
    program = _w1g7_compile(set_pool("INV")["Desperate Research"])
    assert program.supported, program.reason

    lea = set_pool("LEA")
    library = [
        lea[name] for name in (
            "Forest", "Shivan Dragon", "Lightning Bolt", "Shivan Dragon", "Island",
            "Forest", "Serra Angel", "Mountain",
        )
    ]
    game = _w1g7_table(set_pool, "Desperate Research", interactive=[0])
    game.players[0].library = library
    assert game.cast_from_hand(0, "Desperate Research").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    prompt = game.pending_choice_of("choose_card_name", 0)
    assert prompt is not None and prompt.data.get("exclude_basic_land_names")
    assert len(game.players[0].library) == 8, "nothing is revealed before the name"
    for refused in ("Forest", "island", "Snow-Covered Mountain", "Wastes"):
        assert not game.confirm_choose_card_name(0, refused), refused
    assert game.confirm_choose_card_name(0, "Shivan Dragon")

    caster = game.players[0]
    assert [c.name for c in caster.hand] == ["Shivan Dragon", "Shivan Dragon"]
    assert [c.name for c in caster.exile] == [
        "Forest", "Lightning Bolt", "Island", "Forest", "Serra Angel",
    ]
    assert [c.name for c in caster.graveyard] == ["Desperate Research"]
    assert [c.name for c in caster.library] == ["Mountain"]
    assert not game.stack and not game.pending_choices


def test_w1g7_void_destroys_and_discards_by_the_number_its_caster_names(set_pool):
    """"Choose a number. Destroy all artifacts and creatures with mana value
    equal to that number. Then target player reveals their hand and discards
    all nonland cards with mana value equal to the number."

    A *spell* choosing a number, with no printed bound (CR 107.1: any whole
    number from zero up — a negative one is refused). Naming three takes every
    artifact and creature of mana value three **on both sides**, leaves the
    enchantment of the same mana value and the two-drops, and then strips the
    targeted hand of its nonland threes.
    """
    card = set_pool("INV")["Void"]
    program = _w1g7_compile(card)
    assert program.supported, program.reason
    assert _w1g7_targeting.derive_cast_spec(card, program) == {"kind": "player"}

    three = _w1g7_sized_card("Three Drop", "Creature - Bear", 3)
    rock = _w1g7_sized_card("Three Rock", "Artifact", 3)
    aura = _w1g7_sized_card("Three Glyph", "Enchantment", 3)
    two = _w1g7_sized_card("Two Drop", "Creature - Bear", 2)
    spell3 = _w1g7_sized_card("Three Spell", "Sorcery", 3)
    spell1 = _w1g7_sized_card("One Spell", "Instant", 1)
    forest = set_pool("LEA")["Forest"]
    game = _w1g7_table(
        set_pool, "Void",
        mine=[_W1G7Permanent(card=three), _W1G7Permanent(card=two)],
        theirs=[
            _W1G7Permanent(card=three), _W1G7Permanent(card=rock),
            _W1G7Permanent(card=aura), _W1G7Permanent(card=two),
            _W1G7Permanent(card=forest),
        ],
        interactive=[0],
    )
    game.players[1].hand = [spell3, spell1, three, forest]
    assert game.cast_from_hand(0, "Void", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    prompt = game.pending_choice_of("number_choice", 0)
    assert prompt is not None
    assert (prompt.data["minimum"], prompt.data["maximum"]) == (0, None)
    assert not game.confirm_number_choice(0, -1)
    assert game.confirm_number_choice(0, 3)

    assert _w1g7_board(game, 0) == ["Two Drop"], game.log
    assert _w1g7_board(game, 1) == ["Three Glyph", "Two Drop", "Forest"]
    victim = game.players[1]
    assert [c.name for c in victim.hand] == ["One Spell", "Forest"]
    assert sorted(c.name for c in victim.graveyard) == [
        "Three Drop", "Three Drop", "Three Rock", "Three Spell",
    ]
    assert any("Void: chose 3" in line for line in game.log)
    assert not game.stack and not game.pending_choices


def test_w1g7_void_naming_zero_spares_lands_on_the_board_and_in_the_hand(set_pool):
    """Zero is a number, and the two sentences each say what it does not
    reach: a land is neither an artifact nor a creature, and the discard is of
    **nonland** cards — so naming zero on a board of lands takes nothing."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g7_table(
        set_pool, "Void", theirs=[_W1G7Permanent(card=forest)], interactive=[0],
    )
    game.players[1].hand = [forest, _w1g7_sized_card("One Spell", "Instant", 1)]
    game.cast_from_hand(0, "Void", target_player_index=1)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_number_choice(0, 0)

    assert _w1g7_board(game, 1) == ["Forest"]
    assert [c.name for c in game.players[1].hand] == ["Forest", "One Spell"]


def test_w1g7_void_headless_names_the_number_that_costs_the_opponent_most(set_pool):
    """A seat that is not asked names the mana value borne by the most
    permanents its opponents control, net of its own — read off the
    battlefield, which is public, and never off a hand."""
    three = _w1g7_sized_card("Three Drop", "Creature - Bear", 3)
    two = _w1g7_sized_card("Two Drop", "Creature - Bear", 2)
    game = _w1g7_table(
        set_pool, "Void",
        mine=[_W1G7Permanent(card=two), _W1G7Permanent(card=two)],
        theirs=[
            _W1G7Permanent(card=three), _W1G7Permanent(card=three),
            _W1G7Permanent(card=two),
        ],
    )
    game.cast_from_hand(0, "Void", target_player_index=1)
    _w1g7_resolve_stack(game)
    # The number is a queued prompt for every seat; a headless table drains it
    # the way the simulator does, and the steps behind it then run.
    game.auto_resolve_pending_choices()

    assert _w1g7_board(game, 1) == ["Two Drop"], game.log
    assert _w1g7_board(game, 0) == ["Two Drop", "Two Drop"]


# --- W1G8: odd ones ---
from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_wave_table(set_pool, *, active: int, blue_mana: int):
    """Seat 0 holds Breaking Wave with *blue_mana* floating, in *active*'s
    precombat main phase, costs enforced. Seat 0's Grizzly Bears and seat 1's
    Scryb Sprites and Forest start tapped; seat 1's Hill Giant untapped."""
    pool = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", life=20, library=[pool["Island"]] * 10)
        for seat in range(2)
    ])
    game.interactive_seats = set()
    game.start_turn(active)
    game.current_turn_phase = "precombat_main"
    game.enforce_mana_costs = True
    board = {}
    for seat, name, tapped in (
        (0, "Grizzly Bears", True), (1, "Hill Giant", False),
        (1, "Scryb Sprites", True), (1, "Forest", True),
    ):
        permanent = _W1G8Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.tapped = tapped
        board[name] = permanent
    game.players[0].hand = [set_pool("INV")["Breaking Wave"]]
    game.players[0].mana_pool["U"] = blue_mana
    return game, board


def test_breaking_wave_inverts_every_creature_at_once(set_pool):
    """"Simultaneously untap all tapped creatures and tap all untapped
    creatures." Both sets are read before either is turned: the tapped Bears
    and Sprites untap, the untapped Hill Giant taps — on both battlefields —
    and the tapped Forest, not a creature, is left alone. Cast in its
    controller's main phase it costs its printed {2}{U}{U}."""
    game, board = _w1g8_wave_table(set_pool, active=0, blue_mana=4)

    assert game.cast_from_hand(0, "Breaking Wave").supported
    _w1g8_resolve_stack(game)

    assert not board["Grizzly Bears"].tapped
    assert not board["Scryb Sprites"].tapped
    assert board["Hill Giant"].tapped
    assert board["Forest"].tapped
    assert game.players[0].mana_pool["U"] == 0


def test_breaking_wave_costs_two_more_outside_sorcery_timing(set_pool):
    """"You may cast this spell as though it had flash if you pay {2} more to
    cast it." On the opponent's turn four mana is not enough — the cast is
    refused with nothing spent and nothing turned."""
    game, board = _w1g8_wave_table(set_pool, active=1, blue_mana=4)

    assert not game.cast_from_hand(0, "Breaking Wave").supported

    assert game.players[0].mana_pool["U"] == 4
    assert [card.name for card in game.players[0].hand] == ["Breaking Wave"]
    assert board["Grizzly Bears"].tapped and not board["Hill Giant"].tapped


def test_breaking_wave_is_cast_as_though_it_had_flash_for_six(set_pool):
    """The permission bought: on the opponent's turn, six mana casts it and
    all six are spent. In its controller's own main phase the same six leave
    two floating — the price is owed only when the permission is used."""
    game, board = _w1g8_wave_table(set_pool, active=1, blue_mana=6)
    assert game.cast_from_hand(0, "Breaking Wave").supported
    _w1g8_resolve_stack(game)
    assert game.players[0].mana_pool["U"] == 0
    assert board["Hill Giant"].tapped and not board["Grizzly Bears"].tapped

    game, _board = _w1g8_wave_table(set_pool, active=0, blue_mana=6)
    assert game.cast_from_hand(0, "Breaking Wave").supported
    assert game.players[0].mana_pool["U"] == 2


# --- W2G1: kicker spells ---
import pytest as _w2g1_pytest

from engine import Game as _W2G1Game
from engine import PlayerState as _W2G1PlayerState
from engine.models import Permanent as _W2G1Permanent
from tests.helpers import resolve_stack as _w2g1_resolve_stack


def _w2g1_offensive(set_pool, *, kicked):
    """Savage Offensive resolved with two creatures on its caster's side and
    one across the table. Returns ``(game, mine, theirs)``."""
    lea = set_pool("LEA")
    game = _W2G1Game(players=[
        _W2G1PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[set_pool("INV")["Savage Offensive"]],
        ),
        _W2G1PlayerState("Victim", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"R": 2, "G": 1})
    mine = []
    for name in ("Grizzly Bears", "Hill Giant"):
        permanent = _W2G1Permanent(card=lea[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        mine.append(permanent)
    theirs = _W2G1Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    result = game.cast_from_hand(
        0, "Savage Offensive",
        optional_cost_payments={"{G}": 1} if kicked else None,
    )
    assert result.supported, result
    _w2g1_resolve_stack(game)
    return game, mine, theirs  # _w2g1_offensive


def _w2g1_stats(game, permanent):
    return (
        permanent.effective_power, permanent.effective_toughness,
        game._has_keyword(permanent, "first strike"),
    )  # _w2g1_stats


@_w2g1_pytest.mark.parametrize("kicked, bears, giant", [
    (False, (2, 2, True), (3, 3, True)),
    (True, (3, 3, True), (4, 4, True)),
])
def test_w2g1_savage_offensive_pumps_the_same_creatures_only_when_kicked(
    set_pool, kicked, bears, giant,
):
    """"Creatures you control gain first strike until end of turn. If this
    spell was kicked, **they** get +1/+1 until end of turn." The pronoun is the
    set the first sentence described — the caster's creatures, and nobody
    else's."""
    game, mine, theirs = _w2g1_offensive(set_pool, kicked=kicked)

    assert _w2g1_stats(game, mine[0]) == bears
    assert _w2g1_stats(game, mine[1]) == giant
    assert _w2g1_stats(game, theirs) == (2, 2, False)
    assert sum(game.players[0].mana_pool.values()) == (0 if kicked else 1)


def test_w2g1_savage_offensive_fixes_its_set_and_ends_with_the_turn(set_pool):
    """CR 611.2c: both effects lock in the creatures on the battlefield as the
    spell resolves, so one that arrives afterwards has neither; and both say
    "until end of turn"."""
    game, mine, _theirs = _w2g1_offensive(set_pool, kicked=True)
    late = _W2G1Permanent(card=set_pool("LEA")["Craw Wurm"])
    game._put_permanent_onto_battlefield(0, late, None)
    assert _w2g1_stats(game, late) == (6, 4, False)

    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert _w2g1_stats(game, mine[0]) == (2, 2, False)
    assert _w2g1_stats(game, mine[1]) == (3, 3, False)
# end of the W2G1 sorceries block
