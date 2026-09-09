"""Urza's Legacy creatures.

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

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: a keyword chosen from a printed list, on the removal side ---
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g2_removal_pool():
    """Every shipped card by name, for the creature the Sponge points at.

    Memoized on the function, and read through the manifest rather than a
    spelled-out filename — `set_pool("ULG")` cannot supply a card from another
    set and the victim has to have the keywords the Sponge takes away.
    """
    cached = getattr(_g2_removal_pool, "_g2_victims", None)
    if cached is None:
        cached = {}
        for path in manifest_set_paths():
            for card in load_cards(path):
                cached.setdefault(card.name, card)
        _g2_removal_pool._g2_victims = cached
    return cached


def _g2_sponge_board(set_pool, victim_name, *, interactive=False):
    """The Sponge on Alice's board and *victim_name* on Bob's."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    sponge = Permanent(card=set_pool("ULG")["Walking Sponge"])
    game._put_permanent_onto_battlefield(0, sponge, None)
    sponge.metadata["summoning_sickness_turn"] = -99
    victim = Permanent(card=_g2_removal_pool()[victim_name])
    game._put_permanent_onto_battlefield(1, victim, None)
    return game, sponge, victim


def test_walking_sponge_takes_away_one_keyword_not_three(set_pool):
    """"{T}: Target creature loses **your choice of** flying, first strike, or
    trample until end of turn."

    CR 608.2d: the pick is announced while the effect is applied, so the card
    removes *one* of the three. The four printed words were unread on this side
    of the layer — the grant reads them (Alchemist's Gift) and the removal did
    not — and the connective went with them, so the tuple the lowering received
    could not tell "or" from "and".
    """
    game, _, angel = _g2_sponge_board(set_pool, "Serra Angel")
    assert angel.has_keyword("flying") and angel.has_keyword("vigilance")

    result = game.activate_permanent_ability(
        0, "Walking Sponge", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert not angel.has_keyword("flying")
    assert angel.has_keyword("vigilance"), "a keyword the card never named"


def test_walking_sponge_offers_all_three_to_an_interactive_seat(set_pool):
    """The choice reaches its player as the mode prompt every nested "or"
    already uses, so no new pending-choice kind and no new renderer were needed
    — and the ability stays on the stack while the prompt is owed (CR 608.2,
    CR 117.3b)."""
    game, _, knight = _g2_sponge_board(
        set_pool, "White Knight", interactive=True
    )
    game.activate_permanent_ability(
        0, "Walking Sponge", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )

    game.resolve_top_of_stack()

    (prompt,) = game.pending_choices
    assert prompt.kind == "mode_choice"
    assert prompt.data["labels"] == ["flying", "first strike", "trample"]
    assert len(game.stack) == 1, "the ability waits for the answer"


def test_walking_sponge_removes_the_keyword_its_player_named(set_pool):
    """The answer is honoured rather than defaulted: an interactive seat that
    names "first strike" takes first strike, where the headless default takes
    the first printed option."""
    game, _, knight = _g2_sponge_board(
        set_pool, "White Knight", interactive=True
    )
    assert knight.has_keyword("first strike")
    game.activate_permanent_ability(
        0, "Walking Sponge", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game.resolve_top_of_stack()

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    resolve_stack(game)

    assert not knight.has_keyword("first strike")


def test_walking_sponge_leaves_a_creature_with_none_of_the_three_alone(set_pool):
    """The control. A removal that wrote the word regardless would pass every
    test above; this one asserts the Sponge changes nothing it did not name."""
    game, _, bears = _g2_sponge_board(set_pool, "Grizzly Bears")

    game.activate_permanent_ability(
        0, "Walking Sponge", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    resolve_stack(game)

    assert not bears.has_keyword("flying")
    assert not bears.has_keyword("first strike")
    assert not bears.has_keyword("trample")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


# --- W1G4: combat — who may attack, who may block, and protection ---
from engine import Game, PlayerState
from engine.equipment import equip_refusal
from engine.models import CardDefinition, Permanent
from tests.helpers import _nosick


def _g4_prop(
    name: str, power: int = 2, toughness: int = 2,
    type_line: str = "Creature - Test", oracle_text: str = "",
) -> CardDefinition:
    """A prop card. Its own name and its own closing lines, per this file's
    header — a helper ending like another block's is what a union splices."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _g4_duel(attackers, blockers):
    """Seat 0 attacking seat 1, parked in the declare-attackers step. Returns
    the game; the caller drives the declarations itself."""
    game = Game(players=[
        PlayerState(name="P1", battlefield=[_nosick(p) for p in attackers]),
        PlayerState(name="P2", battlefield=[_nosick(p) for p in blockers]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    return game


# ---------------------------------------------------------------------------
# Bouncing Beebles — conditional evasion (CR 509.1b)
# ---------------------------------------------------------------------------


def _g4_beebles_board(set_pool, *, defender_has_artifact: bool):
    beebles = Permanent(card=set_pool("ULG")["Bouncing Beebles"])
    blocker = Permanent(card=_g4_prop("Wall of Nothing"))
    board = [blocker]
    if defender_has_artifact:
        board.append(Permanent(card=_g4_prop(
            "Spare Cog", type_line="Artifact",
        )))
    game = _g4_duel([beebles], board)
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.current_step = "declare_blockers"
    return game, beebles, blocker


def test_bouncing_beebles_can_be_blocked_when_the_defender_has_no_artifact(set_pool):
    """The rider is the whole card. Without it the Beebles would be a Phantom
    Warrior for {2}{U}, which is what dropping the "as long as" clause does."""
    game, beebles, _blocker = _g4_beebles_board(set_pool, defender_has_artifact=False)

    assert not game.is_unblockable(beebles)
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg


def test_bouncing_beebles_is_unblockable_while_the_defender_has_an_artifact(set_pool):
    """CR 509.1b, and the condition is read at the declaration rather than
    materialized: the answer changes with the defender's board."""
    game, beebles, _blocker = _g4_beebles_board(set_pool, defender_has_artifact=True)

    assert game.is_unblockable(beebles)
    ok, _msg = game.declare_blockers(1, {0: 0})
    assert not ok


def test_bouncing_beebles_condition_follows_the_board_mid_combat(set_pool):
    """The picker and the step must agree at every moment, not once. Removing
    the artifact after attackers were declared makes the block legal again."""
    game, beebles, _blocker = _g4_beebles_board(set_pool, defender_has_artifact=True)
    assert game.is_unblockable(beebles)

    cog = game.players[1].battlefield[-1]
    game.remove_from_battlefield(cog)

    assert not game.is_unblockable(beebles)
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg


def test_bouncing_beebles_reads_the_defending_players_board_not_its_own(set_pool):
    """"Defending player controls an artifact" — an artifact on the *attacker's*
    side is not the clause, and reading the wrong seat is a creature that turns
    unblockable off its controller's own Mox."""
    game, beebles, _blocker = _g4_beebles_board(set_pool, defender_has_artifact=False)
    game.players[0].battlefield.append(
        Permanent(card=_g4_prop("My Own Cog", type_line="Artifact"))
    )

    assert not game.is_unblockable(beebles)
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg


# ---------------------------------------------------------------------------
# Viashino Bey — a requirement created by the declaration (CR 508.1d)
# ---------------------------------------------------------------------------


def _g4_bey_board(set_pool):
    bey = Permanent(card=set_pool("ULG")["Viashino Bey"])
    friend = Permanent(card=_g4_prop("Bystander"))
    return _g4_duel([bey, friend], [])


def test_viashino_bey_compels_the_rest_of_the_board_when_it_attacks(set_pool):
    """"If this creature attacks, all creatures you control attack if able."
    The Bey alone is an illegal declaration while an untapped friend could
    attack."""
    game = _g4_bey_board(set_pool)

    ok, msg = game.declare_attackers(0, [0], defending_player_index=1)
    assert not ok
    assert "Bystander must attack if able" in msg

    ok, msg = game.declare_attackers(0, [0, 1], defending_player_index=1)
    assert ok, msg


def test_viashino_bey_compels_nobody_while_it_stays_home(set_pool):
    """The condition is about the declaration being made. A Bey that does not
    attack requires nothing of anyone — read as unconditional, the card would
    force the whole board into combat every turn."""
    game = _g4_bey_board(set_pool)

    ok, msg = game.declare_attackers(0, [1], defending_player_index=1)
    assert ok, msg


def test_viashino_bey_compels_only_its_own_controllers_creatures(set_pool):
    """"Creatures **you** control" is CR 109.5's seat. The defender's creatures
    are not the Bey's business, and an untapped one on their side must not make
    the attacker's declaration illegal."""
    game = _g4_duel(
        [Permanent(card=set_pool("ULG")["Viashino Bey"])],
        [Permanent(card=_g4_prop("Their Bystander"))],
    )

    ok, msg = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, msg


def test_an_opponents_viashino_bey_does_not_compel_your_board(set_pool):
    """Identity, not value: the requirement fires on *this* permanent being
    among the declared attackers, so a Bey nobody declared — on the defending
    side, where it could not attack at all — compels nothing."""
    game = _g4_duel(
        [Permanent(card=_g4_prop("Bystander"))],
        [Permanent(card=set_pool("ULG")["Viashino Bey"])],
    )

    ok, msg = game.declare_attackers(0, [], defending_player_index=1)
    assert ok, msg


# ---------------------------------------------------------------------------
# Lone Wolf — CR 510.1b instead of CR 510.1a, at the controller's option
# ---------------------------------------------------------------------------


def _g4_wolf_combat(set_pool, attacker_card):
    attacker = Permanent(card=attacker_card)
    blocker = Permanent(card=_g4_prop("Roadblock", 0, 4))
    game = _g4_duel([attacker], [blocker])
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.current_step = "declare_blockers"
    assert game.declare_blockers(1, {0: 0})[0]
    game.current_step = "combat_damage"
    return game, attacker, blocker


def test_lone_wolf_sends_its_damage_past_a_blocker(set_pool):
    """"You may have this creature assign its combat damage as though it weren't
    blocked." Taken by default, exactly as Garruk's granted copy of the same
    sentence is: no explicit per-blocker assignment IS the offer accepted."""
    game, _wolf, blocker = _g4_wolf_combat(set_pool, set_pool("ULG")["Lone Wolf"])
    game.players[1].life = 20

    ok, msg = game.resolve_combat_damage(0)
    assert ok, msg
    game._settle()

    assert game.players[1].life == 18
    assert blocker.damage_marked == 0, "the blocker was assigned nothing"


def test_lone_wolf_can_be_declined_by_assigning_the_blocker(set_pool):
    """The "may" is answered by the assignment: naming the blocker is how its
    controller takes CR 510.1a instead. Without the offer the card is a 2/2
    that fights walls, and without the decline it is a restriction."""
    game, _wolf, blocker = _g4_wolf_combat(set_pool, set_pool("ULG")["Lone Wolf"])
    game.players[1].life = 20

    ok, msg = game.resolve_combat_damage(0, attacker_damage={0: {0: 2}})
    assert ok, msg
    game._settle()

    assert game.players[1].life == 20
    assert blocker.damage_marked == 2


def test_a_blocked_creature_without_the_offer_damages_its_blocker(set_pool):
    """The control. A 2/2 with no such line assigns to the blocker, so the two
    tests above are measuring the printed sentence rather than the rig."""
    game, _plain, blocker = _g4_wolf_combat(set_pool, _g4_prop("Plain Bear"))
    game.players[1].life = 20

    ok, msg = game.resolve_combat_damage(0)
    assert ok, msg
    game._settle()

    assert game.players[1].life == 20
    assert blocker.damage_marked == 2


# ---------------------------------------------------------------------------
# Angelic Curator — protection from a card type (CR 702.16)
# ---------------------------------------------------------------------------


def test_angelic_curator_has_the_quality_the_shield_reads(set_pool):
    """The whole of the front-end refusal was here: "artifacts" was a quality
    ``_permanent_has_quality`` could answer and the support gate's own copy of
    the reader could not."""
    game = _g4_duel([Permanent(card=set_pool("ULG")["Angelic Curator"])], [])
    curator = game.players[0].battlefield[0]

    assert game._protection_qualities(curator) == {("card_type", "artifact")}


def test_angelic_curator_cannot_be_blocked_by_an_artifact_creature(set_pool):
    """CR 702.16f, the B in protection's DEBT."""
    curator = Permanent(card=set_pool("ULG")["Angelic Curator"])
    robot = Permanent(card=_g4_prop(
        "Clanking Wall", 4, 4, type_line="Artifact Creature - Construct",
        oracle_text="Flying",
    ))
    game = _g4_duel([curator], [robot])
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.current_step = "declare_blockers"

    assert not game._can_block_attacker(robot, curator)
    ok, _msg = game.declare_blockers(1, {0: 0})
    assert not ok, "an artifact creature blocked a creature protected from it"


def test_angelic_curator_takes_no_combat_damage_from_an_artifact_creature(set_pool):
    """CR 702.16e in combat, the D in DEBT — reached here by blocking *it*,
    which protection does not stop."""
    curator = Permanent(card=set_pool("ULG")["Angelic Curator"])
    robot = Permanent(card=_g4_prop(
        "Clanking Wall", 4, 4, type_line="Artifact Creature - Construct",
        oracle_text="Flying",
    ))
    game = _g4_duel([robot], [curator])
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.current_step = "declare_blockers"
    assert game.declare_blockers(1, {0: 0})[0]
    game.current_step = "combat_damage"

    assert game.resolve_all_combat_damage(0)[0]
    game._settle()

    assert curator.damage_marked == 0
    assert curator in game.players[1].battlefield


def test_angelic_curator_cannot_be_equipped(set_pool):
    """CR 702.16d, the E in DEBT. **Every Equipment in this game is an
    artifact**, so this creature is protected from all of them — and the check
    read the colour slice of the quality set, which an artifact has none of."""
    curator = Permanent(card=set_pool("ULG")["Angelic Curator"])
    sword = Permanent(card=_g4_prop(
        "Test Sword", type_line="Artifact - Equipment",
        oracle_text="Equipped creature gets +1/+1.\nEquip {2}",
    ))
    game = _g4_duel([curator, sword], [])

    refusal = equip_refusal(game, sword, curator)
    assert refusal is not None
    assert "702.16d" in refusal


def test_angelic_curator_cannot_be_targeted_by_an_artifact_source(set_pool):
    """CR 702.16b, the T in DEBT."""
    curator = Permanent(card=set_pool("ULG")["Angelic Curator"])
    rod = Permanent(card=_g4_prop(
        "Test Rod", type_line="Artifact",
        oracle_text="{T}: This artifact deals 1 damage to any target.",
    ))
    totem = Permanent(card=_g4_prop("Test Totem", type_line="Enchantment"))
    game = _g4_duel([curator], [rod, totem])

    # Both arguments, exactly as `legality._enumerate_targets` passes them: the
    # object says an *ability* is choosing, the card is what a spell would be.
    assert not game._can_be_targeted(
        curator, rod.card, caster_index=1, ability_source=rod
    )
    assert game._can_be_targeted(
        curator, totem.card, caster_index=1, ability_source=totem
    )


def test_yavimaya_scion_gets_the_same_shield(set_pool):
    """The card the widened reader was really about: "Protection from
    artifacts" on a line of its own was admitted by a bare `startswith` and
    compiled to a `static_line` nothing read, so the creature reported
    supported with no protection at all."""
    game = _g4_duel([Permanent(card=set_pool("ULG")["Yavimaya Scion"])], [])
    scion = game.players[0].battlefield[0]

    assert game._protection_qualities(scion) == {("card_type", "artifact")}
