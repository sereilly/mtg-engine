"""Torment instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState  # noqa: E402
from engine import ai_policy as _w1g6_ai_policy  # noqa: E402
from tests.helpers import resolve_stack as _w1g6_resolve_stack  # noqa: E402


def _w1g6_liquify_table(set_pool, catalog_by_name, spell: str, **cast) -> _W1G6Game:
    """Seat 1 has *spell* on the stack; seat 0 holds Liquify. Mana off."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", hand=[set_pool("TOR")["Liquify"]]),
        _W1G6PlayerState(
            name="P2", hand=[catalog_by_name[spell]],
            library=[catalog_by_name["Island"]] * 5,
        ),
    ])
    game.players[0].hand.extend([catalog_by_name["Island"]] * 4)
    game.enforce_mana_costs = False
    assert game.queue_from_hand(1, spell, **cast).supported
    return game


def test_w1g6_liquify_counters_a_small_spell_and_exiles_it(set_pool, catalog_by_name):
    """"Counter target spell with mana value 3 or less. If that spell is
    countered this way, exile it instead of putting it into its owner's
    graveyard." A Grizzly Bears (mana value 2) is offered, countered and
    exiled."""
    game = _w1g6_liquify_table(set_pool, catalog_by_name, "Grizzly Bears")
    spec = game.cast_target_spec(0, set_pool("TOR")["Liquify"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]
    assert game.cast_from_hand(0, "Liquify", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
    assert game.players[1].graveyard == [] and list(game.controlled_by(1)) == []
    assert [c.name for c in game.players[0].graveyard] == ["Liquify"]


def test_w1g6_liquify_cannot_be_announced_at_a_spell_with_mana_value_four(
    set_pool, catalog_by_name,
):
    """A Hill Giant (mana value 4) is not offered, a cast naming it is refused
    with nothing spent (CR 601.2c), and the AI does not propose it."""
    game = _w1g6_liquify_table(set_pool, catalog_by_name, "Hill Giant")
    liquify = set_pool("TOR")["Liquify"]
    assert game.cast_target_spec(0, liquify)["valid_targets"] == []
    refused = game.cast_from_hand(0, "Liquify", target_stack_index=0)
    assert not refused.supported
    assert "Liquify" in [c.name for c in game.players[0].hand]
    assert len(game.stack) == 1
    assert _w1g6_ai_policy._cast_candidate(
        game, 0, liquify, game.players[0].hand.index(liquify),
    ) is None
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Hill Giant"]


def test_w1g6_liquify_reads_mana_value_on_the_stack_with_its_x(set_pool, catalog_by_name):
    """CR 202.3b: on the stack an {X} counts at the announced value. Mind Twist
    ({X}{B}) cast for X=2 is a three and is countered; cast for X=3 it is a
    four and Liquify cannot be aimed at it."""
    game = _w1g6_liquify_table(
        set_pool, catalog_by_name, "Mind Twist", target_player_index=0, x_value=2,
    )
    assert game.cast_from_hand(0, "Liquify", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Mind Twist"]
    assert len(game.players[0].hand) == 4, "Mind Twist was countered: nothing discarded"

    game = _w1g6_liquify_table(
        set_pool, catalog_by_name, "Mind Twist", target_player_index=0, x_value=3,
    )
    assert not game.cast_from_hand(0, "Liquify", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert [c.name for c in game.players[1].graveyard] == ["Mind Twist"]
    assert len(game.players[0].hand) == 2, "Liquify stayed in hand; three Islands went"

from engine.models import Permanent as _W1G6Permanent  # noqa: E402
from tests.helpers import _nosick as _w1g6_nosick  # noqa: E402


def _w1g6_gambit_table(set_pool, catalog_by_name, *, zone="hand", life=20,
                       interactive=(), walker=False):
    """Seat 0 has Flaming Gambit in *zone*; seat 1 has a Grizzly Bears, a
    Hill Giant and (with *walker*) a Basri Ket at 3 loyalty. Mana enforced."""
    gambit = set_pool("TOR")["Flaming Gambit"]
    theirs = [
        _w1g6_nosick(_W1G6Permanent(card=catalog_by_name[name]))
        for name in ("Grizzly Bears", "Hill Giant")
    ]
    if walker:
        theirs.append(_W1G6Permanent(
            card=catalog_by_name["Basri Ket"], metadata={"loyalty_counters": 3},
        ))
    me = _W1G6PlayerState(name="P1", library=[catalog_by_name["Island"]] * 3)
    getattr(me, zone).append(gambit)
    game = _W1G6Game(players=[
        me, _W1G6PlayerState(name="P2", life=life, battlefield=theirs),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    return game


def _w1g6_permanent(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def test_w1g6_flaming_gambit_hits_the_player_who_declines(set_pool, catalog_by_name):
    """"Flaming Gambit deals X damage to target player or planeswalker. That
    player … may choose a creature they control and have Flaming Gambit deal
    that damage to it instead." Cast for X=3 ({3}{R}, the whole pool): a seat
    nobody asks keeps its creatures while the damage is not lethal, and a
    person who is asked may decline."""
    game = _w1g6_gambit_table(set_pool, catalog_by_name)
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    assert game.cast_from_hand(0, "Flaming Gambit", target_player_index=1, x_value=3).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17
    assert not any(game.players[0].mana_pool.values())
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears", "Hill Giant"]

    game = _w1g6_gambit_table(set_pool, catalog_by_name, interactive={1})
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    assert game.cast_from_hand(0, "Flaming Gambit", target_player_index=1, x_value=3).supported
    owed = [choice for choice in game.pending_choices if choice.kind == "permanent_choice"]
    assert [choice.player_index for choice in owed] == [1], "the damaged player is asked"
    assert game.confirm_permanent_choice(1, None)
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17


def test_w1g6_flaming_gambit_s_damaged_player_sends_it_to_a_creature(set_pool, catalog_by_name):
    """The asked seat names its Hill Giant: the Giant is dealt the 3 and dies,
    the player loses nothing. A seat nobody asks does the same when the damage
    would otherwise be lethal (it names its first creature)."""
    game = _w1g6_gambit_table(set_pool, catalog_by_name, interactive={1})
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    giant = _w1g6_permanent(game, 1, "Hill Giant")
    assert game.cast_from_hand(0, "Flaming Gambit", target_player_index=1, x_value=3).supported
    assert game.confirm_permanent_choice(1, giant.permanent_id)
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 20
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert "Hill Giant" in [c.name for c in game.players[1].graveyard]

    game = _w1g6_gambit_table(set_pool, catalog_by_name, life=3)
    game.players[0].mana_pool.update({"R": 1, "C": 3})
    assert game.cast_from_hand(0, "Flaming Gambit", target_player_index=1, x_value=3).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 3
    assert [p.card.name for p in game.controlled_by(1)] == ["Hill Giant"]


def test_w1g6_flaming_gambit_at_a_planeswalker_asks_its_controller(set_pool, catalog_by_name):
    """"…or that planeswalker's controller": aimed at Basri Ket, the walker's
    controller is asked. Declining, the walker loses 2 loyalty; naming the
    Grizzly Bears, the Bears are dealt the 2 and the walker is untouched."""
    game = _w1g6_gambit_table(set_pool, catalog_by_name, interactive={1}, walker=True)
    walker = _w1g6_permanent(game, 1, "Basri Ket")
    spec = game.cast_target_spec(0, set_pool("TOR")["Flaming Gambit"])
    assert {entry["name"] for entry in spec["valid_targets"] if entry["kind"] == "permanent"} == {"Basri Ket"}
    game.players[0].mana_pool.update({"R": 1, "C": 2})
    assert game.cast_from_hand(
        0, "Flaming Gambit", target_permanent_ids=[walker.permanent_id],
        target_player_index=1, x_value=2,
    ).supported
    assert game.confirm_permanent_choice(1, None)
    _w1g6_resolve_stack(game)
    assert walker.metadata["loyalty_counters"] == 1
    assert game.players[1].life == 20

    game = _w1g6_gambit_table(set_pool, catalog_by_name, interactive={1}, walker=True)
    walker = _w1g6_permanent(game, 1, "Basri Ket")
    bears = _w1g6_permanent(game, 1, "Grizzly Bears")
    game.players[0].mana_pool.update({"R": 1, "C": 2})
    assert game.cast_from_hand(
        0, "Flaming Gambit", target_permanent_ids=[walker.permanent_id],
        target_player_index=1, x_value=2,
    ).supported
    assert game.confirm_permanent_choice(1, bears.permanent_id)
    _w1g6_resolve_stack(game)
    assert walker.metadata["loyalty_counters"] == 3
    assert "Grizzly Bears" in [c.name for c in game.players[1].graveyard]


def test_w1g6_flaming_gambit_flashes_back_for_x_r_r(set_pool, catalog_by_name):
    """"Flashback {X}{R}{R}": the X the cast announces is paid in the
    flashback cost and dealt by the spell, which is then exiled. One mana
    short of {2}{R}{R} for X=2 is a cast refused with nothing spent."""
    game = _w1g6_gambit_table(set_pool, catalog_by_name, zone="graveyard")
    game.players[0].mana_pool.update({"R": 2, "C": 1})
    refused = game.cast_from_hand(
        0, "Flaming Gambit", target_player_index=1, x_value=2, from_zone="graveyard",
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].graveyard] == ["Flaming Gambit"]
    game.players[0].mana_pool["C"] += 1
    assert game.cast_from_hand(
        0, "Flaming Gambit", target_player_index=1, x_value=2, from_zone="graveyard",
    ).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 18
    assert not any(game.players[0].mana_pool.values())
    assert [c.name for c in game.players[0].exile] == ["Flaming Gambit"]

def _w1g6_radiate_table(set_pool, catalog_by_name, mine, theirs, their_hand):
    """Seat 0 holds Radiate over *mine*; seat 1 holds *their_hand* over
    *theirs*. Mana off."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", hand=[set_pool("TOR")["Radiate"]],
            battlefield=[_w1g6_nosick(_W1G6Permanent(card=catalog_by_name[n])) for n in mine],
        ),
        _W1G6PlayerState(
            name="P2", hand=[catalog_by_name[n] for n in their_hand],
            battlefield=[_w1g6_nosick(_W1G6Permanent(card=catalog_by_name[n])) for n in theirs],
        ),
    ])
    game.enforce_mana_costs = False
    return game


def test_w1g6_radiate_copies_a_bolt_onto_everything_else_it_could_target(
    set_pool, catalog_by_name,
):
    """"Choose target instant or sorcery spell that targets only a single
    permanent or player. Copy that spell for each other permanent or player
    the spell could target. Each copy targets a different one of those
    permanents and players." An opponent's Lightning Bolt at seat 0's Grizzly
    Bears: four copies, all seat 0's (CR 707.10a), at the Hill Giant, the
    Serra Angel and both players — and the original still hits the Bears."""
    game = _w1g6_radiate_table(
        set_pool, catalog_by_name, ["Grizzly Bears", "Hill Giant"], ["Serra Angel"],
        ["Lightning Bolt"],
    )
    bears = _w1g6_permanent(game, 0, "Grizzly Bears")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id], target_player_index=0,
    ).supported
    assert game.queue_from_hand(0, "Radiate", target_stack_index=0).supported
    game.resolve_top_of_stack()
    copies = [item for item in game.stack if item.is_copy]
    assert len(copies) == 4 and {item.caster_index for item in copies} == {0}
    _w1g6_resolve_stack(game)
    game.check_state_based_actions()
    assert (game.players[0].life, game.players[1].life) == (17, 17)
    assert _w1g6_permanent(game, 1, "Serra Angel").damage_marked == 3
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Grizzly Bears", "Hill Giant", "Radiate",
    ]


def test_w1g6_radiate_copies_only_onto_what_the_spell_could_target(set_pool, catalog_by_name):
    """"…each other permanent or player **the spell could target**": Terror
    ("target nonartifact, nonblack creature") at a Grizzly Bears is copied
    onto the Hill Giant and nothing else — not the black Knight, not the Sol
    Ring, not a player."""
    game = _w1g6_radiate_table(
        set_pool, catalog_by_name, ["Grizzly Bears", "Hill Giant", "Sol Ring"],
        ["Black Knight"], ["Terror"],
    )
    bears = _w1g6_permanent(game, 0, "Grizzly Bears")
    assert game.queue_from_hand(
        1, "Terror", target_permanent_ids=[bears.permanent_id], target_player_index=0,
    ).supported
    assert game.queue_from_hand(0, "Radiate", target_stack_index=0).supported
    game.resolve_top_of_stack()
    copies = [item for item in game.stack if item.is_copy]
    assert [item.target_permanent_id for item in copies] == [
        _w1g6_permanent(game, 0, "Hill Giant").permanent_id
    ]
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Sol Ring"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Black Knight"]


def test_w1g6_radiate_is_not_offered_a_spell_with_another_kind_of_target(
    set_pool, catalog_by_name,
):
    """A Counterspell targets a spell, not a permanent or player, so it is
    not offered, and a cast naming it is refused with Radiate still in hand
    (CR 601.2c). A Lightning Bolt beside it is the one offered."""
    game = _w1g6_radiate_table(
        set_pool, catalog_by_name, ["Grizzly Bears"], [], ["Lightning Bolt", "Counterspell"],
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    spec = game.cast_target_spec(0, set_pool("TOR")["Radiate"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Lightning Bolt"]
    refused = game.cast_from_hand(0, "Radiate", target_stack_index=1)
    assert not refused.supported
    assert "Radiate" in [c.name for c in game.players[0].hand]

def test_w1g6_alter_reality_rewrites_a_permanent_s_colour_word(set_pool, catalog_by_name):
    """"Change the text of target spell or permanent by replacing all
    instances of one color word with another." On a Black Knight, white
    becomes black: the Knight's text reads "protection from black", and a
    black Terror can no longer target it while a white Swords to Plowshares
    can. Flashed back for {1}{U}, the same, and the card is exiled.

    The *spell* half ("target spell") is not offered: ROADMAP's "Text changes
    aimed at a spell" (Sleight of Mind, Magical Hack, Crystal Spray) is this
    card's too."""
    alter = set_pool("TOR")["Alter Reality"]
    for zone in ("hand", "graveyard"):
        knight = _w1g6_nosick(_W1G6Permanent(card=catalog_by_name["Black Knight"]))
        me = _W1G6PlayerState(name="P1")
        getattr(me, zone).append(alter)
        game = _W1G6Game(players=[me, _W1G6PlayerState(name="P2", battlefield=[knight])])
        game.enforce_mana_costs = False
        assert game.cast_from_hand(
            0, "Alter Reality", target_permanent_ids=[knight.permanent_id],
            target_player_index=1, old_color="W", new_color="B", from_zone=zone,
        ).supported
        _w1g6_resolve_stack(game)
        assert "Protection from black" in knight.effective_card.oracle_text
        assert "white" not in knight.effective_card.oracle_text.lower()
        terror = game.cast_target_spec(0, catalog_by_name["Terror"])
        assert terror["valid_targets"] == [], "black Terror vs protection from black"
        swords = game.cast_target_spec(0, catalog_by_name["Swords to Plowshares"])
        assert [entry["name"] for entry in swords["valid_targets"]] == ["Black Knight"]
        where = "exile" if zone == "graveyard" else "graveyard"
        assert "Alter Reality" in [c.name for c in getattr(game.players[0], where)]


def test_w1g6_accelerate_gives_haste_and_draws(set_pool, catalog_by_name):
    """"Target creature gains haste until end of turn. Draw a card." A
    creature that came under its controller's control this turn can attack."""
    bears = _W1G6Permanent(card=catalog_by_name["Grizzly Bears"])
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", hand=[set_pool("TOR")["Accelerate"]], battlefield=[bears],
                         library=[catalog_by_name["Island"]] * 2),
        _W1G6PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    bears.metadata["summoning_sickness_turn"] = game.turn
    assert game._is_summoning_sick(bears)
    assert game.cast_from_hand(
        0, "Accelerate", target_permanent_ids=[bears.permanent_id], target_player_index=0,
    ).supported
    _w1g6_resolve_stack(game)
    assert not game._is_summoning_sick(bears)
    assert [c.name for c in game.players[0].hand] == ["Island"]


def test_w1g6_cabal_ritual_adds_five_with_threshold(set_pool, catalog_by_name):
    """"Add {B}{B}{B}. Threshold -- Add {B}{B}{B}{B}{B} instead if there are
    seven or more cards in your graveyard." Paid {1}{B}, it leaves three black
    with six cards in the graveyard and five with seven."""
    for graveyard, black in ((6, 3), (7, 5)):
        game = _W1G6Game(players=[
            _W1G6PlayerState(name="P1", hand=[set_pool("TOR")["Cabal Ritual"]],
                             graveyard=[catalog_by_name["Island"]] * graveyard),
            _W1G6PlayerState(name="P2"),
        ])
        game.enforce_mana_costs = True
        game.players[0].mana_pool.update({"B": 1, "C": 1})
        assert game.cast_from_hand(0, "Cabal Ritual").supported
        _w1g6_resolve_stack(game)
        assert game.players[0].mana_pool["B"] == black, graveyard

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
