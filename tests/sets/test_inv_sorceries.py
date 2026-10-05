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
