"""Weatherlight artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G4: animation and printed prohibitions ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _damage_dealt


def _w1g4a_creature(name, power, toughness):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4a_game(mine, theirs) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_bubble_matrix_shields_every_creature_and_no_player(set_pool):
    """"Prevent all damage that would be dealt to creatures." — CR 615.1.

    The recipient is a described *set of permanents* rather than a player, which
    is what makes it a different reader from Glacial Chasm's "dealt to you" one
    row up: a player has no characteristics to match. The sentence narrows by
    nothing, so it reaches both seats — and it says nothing about players, so a
    face still takes the damage. Both halves are asserted, because a shield that
    covered players too would pass the first.
    """
    matrix = Permanent(card=set_pool("WTH")["Bubble Matrix"])
    mine = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    theirs = Permanent(card=_w1g4a_creature("Raider", 2, 2))
    game = _w1g4a_game([matrix, mine], [theirs])

    assert _damage_dealt(game, mine, 3) == 0
    assert _damage_dealt(game, theirs, 3) == 0
    assert _damage_dealt(game, game.players[1], 3) == 3


def test_inner_sanctum_shields_only_its_controllers_creatures(set_pool):
    """The same shield with "you control" on the noun phrase (CR 109.5).

    One row for both cards, so the narrowing has to be *honoured* rather than
    merely carried — dropped, Inner Sanctum is a Bubble Matrix, which is the
    direction a prevention fails silently in.
    """
    sanctum = Permanent(card=set_pool("WTH")["Inner Sanctum"])
    mine = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    theirs = Permanent(card=_w1g4a_creature("Raider", 2, 2))
    game = _w1g4a_game([sanctum, mine], [theirs])

    assert _damage_dealt(game, mine, 3) == 0
    assert _damage_dealt(game, theirs, 3) == 3


def test_the_matrix_stops_shielding_when_it_leaves(set_pool):
    """A static ability ends with its source (CR 611.2), and nothing is swept:
    the next event asks the board again."""
    matrix = Permanent(card=set_pool("WTH")["Bubble Matrix"])
    mine = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    game = _w1g4a_game([matrix, mine], [])
    assert _damage_dealt(game, mine, 3) == 0
    game.remove_from_battlefield(matrix)
    assert _damage_dealt(game, mine, 3) == 3


def test_the_shield_is_claimed_by_the_reader_that_applies_it(set_pool):
    """The gate and the interceptor are one function, so a card cannot be
    admitted with its only line doing nothing — and the two singular
    self-references the source-narrowed readers own must keep refusing here."""
    from engine.prevention import prevent_all_to_matching

    assert compile_card_oracle(set_pool("WTH")["Bubble Matrix"]).supported
    assert compile_card_oracle(set_pool("WTH")["Inner Sanctum"]).supported
    for owned_elsewhere in (
        "Prevent all damage that would be dealt to this creature.",
        "Prevent all damage that would be dealt to enchanted creature.",
        "Prevent all damage that would be dealt to you.",
        "Prevent all damage that would be dealt to this creature by artifact sources.",
    ):
        assert prevent_all_to_matching(owned_elsewhere) is None, owned_elsewhere


def _w1g4a_board(perms) -> Game:
    game = _w1g4a_game(perms, [])
    game.start_turn(0)
    return game


def test_chimeric_sphere_animates_itself_and_stays_an_artifact(set_pool):
    """"Until end of turn, this artifact becomes a 2/1 Construct artifact
    creature with flying." — CR 205.1b and CR 613 layers 4, 6 and 7b.

    The clause-less form of the animation: no "in addition to its other types"
    and no "It's still a land", because the printed body already names the
    permanent's own card type. The production admits it on exactly that
    arithmetic, so the artifact type is asserted here rather than assumed —
    an animation that replaced the types would leave a permanent no Shatter
    could reach.
    """
    sphere = Permanent(card=set_pool("WTH")["Chimeric Sphere"])
    game = _w1g4a_board([sphere])
    assert not sphere.is_creature

    assert game.activate_permanent_ability(
        0, "Chimeric Sphere", ability_index=0
    ).supported
    game._recompute_continuous_effects()
    assert sphere.is_creature
    assert (sphere.effective_power, sphere.effective_toughness) == (2, 1)
    assert game._has_keyword(sphere, "flying")
    assert sphere.has_type("construct")
    assert sphere.has_type("artifact")


def test_chimeric_spheres_second_body_takes_the_flying_back_off(set_pool):
    """"…becomes a 3/2 Construct artifact creature **and loses flying**."

    The conjunct is the whole point of the card's second ability rather than a
    restatement of the default: the *first* ability gave the Sphere flying, and
    CR 613 layer 6 settles the two by timestamp. Both abilities are activated in
    order here, because the removal is only observable against the grant.
    """
    sphere = Permanent(card=set_pool("WTH")["Chimeric Sphere"])
    game = _w1g4a_board([sphere])
    assert game.activate_permanent_ability(
        0, "Chimeric Sphere", ability_index=0
    ).supported
    game._recompute_continuous_effects()
    assert game._has_keyword(sphere, "flying")

    assert game.activate_permanent_ability(
        0, "Chimeric Sphere", ability_index=1
    ).supported
    game._recompute_continuous_effects()
    assert (sphere.effective_power, sphere.effective_toughness) == (3, 2)
    assert not game._has_keyword(sphere, "flying")
    assert sphere.has_type("artifact")


def test_xanthic_statue_animates_with_its_printed_keyword(set_pool):
    """The same production one card over, with a different body — which is what
    makes it a production rather than two entries."""
    statue = Permanent(card=set_pool("WTH")["Xanthic Statue"])
    game = _w1g4a_board([statue])
    assert not statue.is_creature

    assert game.activate_permanent_ability(
        0, "Xanthic Statue", ability_index=0
    ).supported
    game._recompute_continuous_effects()
    assert (statue.effective_power, statue.effective_toughness) == (8, 8)
    assert game._has_keyword(statue, "trample")
    assert statue.has_type("golem")
    assert statue.has_type("artifact")


def test_thran_forge_pumps_and_adds_the_type_to_one_target(set_pool):
    """"…target nonartifact creature gets +1/+0 **and becomes an artifact in
    addition to its other types**." — CR 205.1b's *addition*, joined to a pump.

    Two effect families in one sentence over one printed noun phrase, which is
    why the join lives in `grammar/conjuncts.py`: `effects/characteristics.py`
    may not import `effects/types.py`.
    """
    forge = Permanent(card=set_pool("WTH")["Thran Forge"])
    victim = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    game = _w1g4a_board([forge, victim])

    assert game.activate_permanent_ability(
        0, "Thran Forge", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    ).supported
    game._recompute_continuous_effects()
    assert (victim.effective_power, victim.effective_toughness) == (3, 2)
    assert victim.has_type("artifact")
    # "In addition to its other types" — the creature type survives, which is
    # the difference between this clause and the animation two tests up.
    assert victim.is_creature


def test_thran_forge_refuses_an_artifact_creature(set_pool):
    """The printed "nonartifact" is enforced, not merely carried.

    The activation is refused with nothing spent (CR 602.2b), which is the half
    of the narrowing the engine answers. The *picker* is the other half and it
    is unnarrowed today — `derive_activation_spec` answers a bare
    `{"kind": "creature"}` for every activated pump in the pool, this card
    included — so a client would offer the target and the engine would decline
    it. That is a pool-wide gap rather than this card's, and this test pins the
    half that is enforced so a later round can tighten the other.
    """
    artifact_creature = CardDefinition(
        name="Clockwork Test", mana_cost="", cmc=0.0,
        type_line="Artifact Creature - Test", oracle_text="", colors=(),
        color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Clockwork Test", "type_line": "Artifact Creature - Test",
             "power": "2", "toughness": "2"},
    )
    forge = Permanent(card=set_pool("WTH")["Thran Forge"])
    victim = Permanent(card=artifact_creature)
    game = _w1g4a_board([forge, victim])

    result = game.activate_permanent_ability(
        0, "Thran Forge", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    assert not result.supported
    assert (victim.effective_power, victim.effective_toughness) == (2, 2)


def test_an_animation_that_drops_a_type_still_refuses(set_pool):
    """The refusal test for the clause-less form, written before the gate is
    trusted.

    "Target land becomes a 4/4 creature until end of turn" names no land in its
    body, so replacement and addition are *not* the same permanent — the land
    would stop being a land. The engine has no CR 205.1b type removal, so the
    line has to keep refusing rather than be admitted under an adding record.
    """
    from engine.grammar import compile_line

    assert compile_line(
        "Until end of turn, this artifact becomes a 2/1 Construct artifact "
        "creature with flying."
    ).instructions
    for dropped in (
        "Target land becomes a 4/4 creature until end of turn.",
        "This land becomes a 2/2 Assembly-Worker artifact creature until end of turn.",
    ):
        assert not compile_line(dropped).instructions, dropped
