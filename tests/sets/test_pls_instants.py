"""Planeshift instants.

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


# --- W1G8: damage and the odd ones ---
#
# Rith's Charm's third mode — "Prevent all damage a source of your choice would
# deal this turn." — is Samite Ministration's chosen-source blanket in the
# active voice and with **no recipient printed**: the source deals no damage to
# anything. One parse branch (the subject position), one lowering flag
# (``any_recipient``, Penance's) and the shield Invasion built.

from engine import Game as _w1g8i_Game, PlayerState as _w1g8i_Player  # noqa: E402
from engine import targeting as _w1g8i_targeting  # noqa: E402
from engine.card_loader import (load_cards as _w1g8i_load,  # noqa: E402
                                manifest_set_path as _w1g8i_path)
from engine.grammar import compile_line as _w1g8i_compile_line  # noqa: E402
from engine.models import (CardDefinition as _w1g8i_Card,  # noqa: E402
                           Permanent as _w1g8i_Permanent)
from engine.oracle import compile_card_oracle as _w1g8i_compile  # noqa: E402

from tests.helpers import (_damage_dealt as _w1g8i_dealt,  # noqa: E402
                           resolve_stack as _w1g8i_resolve_stack)


def _w1g8i_lea():
    return {card.name: card for card in _w1g8i_load(_w1g8i_path("LEA"))}


def _w1g8i_body(name, power, toughness, text="", type_line="Creature - Test",
                colors=()):
    """A bare card for the other side of a spell."""
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power=str(power), toughness=str(toughness))
    return _w1g8i_Card(
        name=name, mana_cost="{3}", cmc=3.0, type_line=type_line,
        oracle_text=text, colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(), raw=raw,
    )  # W1G8 instants: a test body


def _w1g8i_duel(mine, theirs, *, hand0=(), hand1=(), active=0, graveyard0=()):
    """Both boards placed and unsick, *active* in its precombat main phase."""
    board0 = [_w1g8i_Permanent(card=card) for card in mine]
    board1 = [_w1g8i_Permanent(card=card) for card in theirs]
    filler = _w1g8i_body("Filler", 0, 1)
    game = _w1g8i_Game(players=[
        _w1g8i_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10, graveyard=list(graveyard0)),
        _w1g8i_Player(name="P1", battlefield=board1, hand=list(hand1),
                      library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._close_current_priority_step()
    return game, board0, board1  # W1G8 instants: the duel


def _w1g8i_attack(game, attacker_slot, blocks=None, *, defender):
    """The active seat attacks with one creature; combat runs to main two."""
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(game.active_player_index, [attacker_slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocked = game.declare_blockers(defender, dict(blocks or {}))
    assert blocked[0], blocked
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g8i_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # W1G8: fought


def _w1g8i_mode_spec(card, mode_index):
    """What one mode of a modal spell asks the cast picker for."""
    program = _w1g8i_compile(card)
    return _w1g8i_targeting._from_instructions(
        (program.modes[mode_index].instruction,)
    )  # W1G8 instants: a mode's picker


def test_w1g8_riths_charm_offers_each_mode_its_own_picker(set_pool):
    """A modal spell announces its targets per mode (CR 700.2): a nonbasic
    land, nothing, and CR 609.7a's source of your choice — a permanent or a
    spell on the stack, and not a target."""
    charm = set_pool("PLS")["Rith's Charm"]
    program = _w1g8i_compile(charm)

    assert program.supported
    assert [mode.instruction.kind for mode in program.modes] == [
        "destroy_target_permanent", "create_token",
        "grant_chosen_source_blanket_shield",
    ]
    assert _w1g8i_mode_spec(charm, 0) == {
        "kind": "land", "filter": {"exclude_supertypes": ["basic"]},
    }
    assert _w1g8i_mode_spec(charm, 1) is None
    assert _w1g8i_mode_spec(charm, 2) == {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    }
    assert program.modes[2].instruction.payload == {"any_recipient": True}


def test_w1g8_riths_charm_destroys_a_nonbasic_land_and_only_one(set_pool):
    """Mode one. "Nonbasic" is honoured: aimed at a basic land the mode
    destroys nothing — and never falls through onto the nonbasic land beside
    it — and with no nonbasic land anywhere it cannot be cast in that mode.

    The refusal is at *resolution* for an announced basic land, not at
    announcement: the cast-time target gate declines every modal spell
    (ROADMAP, "Modal spells are excluded"), so this asserts the half that
    holds today and is rules-visible — which permanent is destroyed.
    """
    lea = _w1g8i_lea()
    charm = set_pool("PLS")["Rith's Charm"]
    game, _, theirs = _w1g8i_duel(
        [], [lea["Badlands"], lea["Island"]], hand0=[charm] * 2,
    )
    badlands, island = theirs

    game.cast_from_hand(
        0, "Rith's Charm", mode_index=0,
        target_permanent_ids=[island.permanent_id],
    )
    _w1g8i_resolve_stack(game)
    assert game.is_on_battlefield(island), "a basic land is not a nonbasic one"
    assert game.is_on_battlefield(badlands), "and the bystander is not chosen"

    cast = game.cast_from_hand(
        0, "Rith's Charm", mode_index=0,
        target_permanent_ids=[badlands.permanent_id],
    )
    assert cast.supported, cast.details
    _w1g8i_resolve_stack(game)
    assert not game.is_on_battlefield(badlands)
    assert game.is_on_battlefield(island)
    assert [card.name for card in game.players[1].graveyard] == ["Badlands"]

    game, _, _ = _w1g8i_duel([], [lea["Island"]], hand0=[charm])
    assert not game.cast_from_hand(0, "Rith's Charm", mode_index=0).supported
    assert len(game.players[0].hand) == 1, "a refused cast spends nothing"


def test_w1g8_riths_charm_makes_three_green_saprolings(set_pool):
    """Mode two, on a board with no land to destroy and no source to choose."""
    charm = set_pool("PLS")["Rith's Charm"]
    game, _, _ = _w1g8i_duel([], [], hand0=[charm])

    cast = game.cast_from_hand(0, "Rith's Charm", mode_index=1)
    assert cast.supported, cast.details
    _w1g8i_resolve_stack(game)

    tokens = list(game.controlled_by(0))
    assert len(tokens) == 3
    for token in tokens:
        assert token.card.name == "Saproling Token"
        assert (token.effective_power, token.effective_toughness) == (1, 1)
        assert token.effective_colors == {"G"}
        assert token.has_type("saproling") and token.is_creature


def test_w1g8_riths_charm_silences_one_chosen_source_for_everyone(set_pool):
    """Mode three with a creature chosen: every recipient that creature would
    damage this turn is spared — the caster, the caster's creature and the
    creature's own controller alike — while another source deals its damage
    as printed. The attack is run through the combat damage step."""
    lea = _w1g8i_lea()
    charm = set_pool("PLS")["Rith's Charm"]
    game, mine, theirs = _w1g8i_duel(
        [lea["Grizzly Bears"]], [lea["Hill Giant"], lea["Prodigal Sorcerer"]],
        hand0=[charm], active=1,
    )
    giant, pinger = theirs

    cast = game.cast_from_hand(
        0, "Rith's Charm", mode_index=2,
        target_permanent_ids=[giant.permanent_id],
    )
    assert cast.supported, cast.details
    _w1g8i_resolve_stack(game)

    assert _w1g8i_dealt(game, game.players[0], 3, source=giant, combat=True) == 0
    assert _w1g8i_dealt(game, mine[0], 3, source=giant, combat=True) == 0
    assert _w1g8i_dealt(game, game.players[1], 3, source=giant) == 0
    assert _w1g8i_dealt(game, game.players[0], 1, source=pinger) == 1

    _w1g8i_attack(game, 0, {0: 0}, defender=0)
    assert game.is_on_battlefield(mine[0]), "the blocker took no damage"
    assert mine[0].damage_marked == 0
    assert giant.damage_marked == 2, "the Bears still dealt theirs"
    assert game.players[0].life == 20


def test_w1g8_riths_charm_shield_is_never_used_up_and_ends_with_the_turn(set_pool):
    """"All damage … this turn": the second event is prevented like the first
    (no charge is spent), and the cleanup step is what ends it."""
    lea = _w1g8i_lea()
    charm = set_pool("PLS")["Rith's Charm"]
    game, _, theirs = _w1g8i_duel([], [lea["Hill Giant"]], hand0=[charm])
    giant = theirs[0]

    assert game.cast_from_hand(
        0, "Rith's Charm", mode_index=2,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g8i_resolve_stack(game)

    for _ in range(3):
        assert _w1g8i_dealt(game, game.players[0], 3, source=giant) == 0
    game.resolve_cleanup_step(0)
    assert _w1g8i_dealt(game, game.players[0], 3, source=giant) == 3


def test_w1g8_riths_charm_can_choose_a_spell_on_the_stack(set_pool):
    """CR 609.7a: the source may be a spell. Cast in response to a Lightning
    Bolt and naming it, the Charm resolves first and the Bolt deals nothing."""
    lea = _w1g8i_lea()
    charm = set_pool("PLS")["Rith's Charm"]
    game, _, _ = _w1g8i_duel(
        [], [], hand0=[charm], hand1=[lea["Lightning Bolt"]], active=1,
    )

    assert game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0
    ).supported
    cast = game.queue_from_hand(
        0, "Rith's Charm", mode_index=2, target_stack_index=0,
    )
    assert cast.supported, cast.details
    assert len(game.stack) == 2
    _w1g8i_resolve_stack(game)

    assert game.players[0].life == 20
    assert any("prevented 3 damage" in line for line in game.log)


def test_w1g8_riths_charm_with_no_source_named_takes_the_stated_default(set_pool):
    """A headless cast names no source. A turn-long shield has no sourceless
    form, so the seat takes the stated default — the opponent's attacker — and
    with nothing on the table to choose the mode does nothing."""
    lea = _w1g8i_lea()
    charm = set_pool("PLS")["Rith's Charm"]
    game, _, theirs = _w1g8i_duel([], [lea["Hill Giant"]], hand0=[charm] * 2)

    assert game.cast_from_hand(0, "Rith's Charm", mode_index=2).supported
    _w1g8i_resolve_stack(game)
    assert _w1g8i_dealt(game, game.players[0], 3, source=theirs[0]) == 0

    game, _, _ = _w1g8i_duel([], [], hand0=[charm])
    assert game.cast_from_hand(0, "Rith's Charm", mode_index=2).supported
    _w1g8i_resolve_stack(game)
    assert any("no source of damage to choose" in line for line in game.log)


def test_w1g8_a_recipient_free_chosen_source_blanket_reads_its_whole_sentence():
    """The parse and lowering halves. The active voice builds the passive's
    node; a printed recipient keeps Samite Ministration's shield; and a
    recipient the shield cannot hang off still refuses."""
    bare = _w1g8i_compile_line(
        "Prevent all damage a source of your choice would deal this turn.",
        card_name="Probe",
    )
    assert [(i.kind, i.payload) for i in bare.instructions] == [
        ("grant_chosen_source_blanket_shield", {"any_recipient": True}),
    ]
    to_you = _w1g8i_compile_line(
        "Prevent all damage a source of your choice would deal to you this turn.",
        card_name="Probe",
    )
    assert [(i.kind, i.payload) for i in to_you.instructions] == [
        ("grant_chosen_source_blanket_shield", {}),
    ]
    to_target = _w1g8i_compile_line(
        "Prevent all damage a source of your choice would deal to target "
        "creature this turn.",
        card_name="Probe",
    )
    assert to_target.lowering_error and not to_target.instructions
    no_duration = _w1g8i_compile_line(
        "Prevent all damage a source of your choice would deal.",
        card_name="Probe",
    )
    assert no_duration.lowering_error and not no_duration.instructions


# W1G8, supported on arrival and driven: Malicious Advice, the three other
# Charms (each mode through its own picker), Terminate, Gerrard's Command and
# Daring Leap. Every one compiled with all four instruments quiet and none had
# been run.


def test_w1g8_malicious_advice_taps_x_targets_and_costs_x_life(set_pool):
    """"Tap X target artifacts, creatures, and/or lands. You lose X life." The
    picker asks for X distinct targets out of those three types; an
    enchantment is not one of them."""
    lea = _w1g8i_lea()
    advice = set_pool("PLS")["Malicious Advice"]
    assert _w1g8i_targeting.derive_cast_spec(advice, _w1g8i_compile(advice)) == {
        "kind": "permanent", "x_targets": True, "distinct_targets": True,
        "filter": {"type_filter": ["artifact", "creature", "land"]},
    }
    game, _, theirs = _w1g8i_duel(
        [], [lea["Hill Giant"], lea["Sol Ring"], lea["Island"], lea["Crusade"]],
        hand0=[advice] * 3,
    )
    giant, ring, island, crusade = theirs

    cast = game.cast_from_hand(
        0, "Malicious Advice", x_value=2,
        target_permanent_ids=[giant.permanent_id, island.permanent_id],
    )
    assert cast.supported, cast.details
    _w1g8i_resolve_stack(game)
    assert [perm.tapped for perm in theirs] == [True, False, True, False]
    assert game.players[0].life == 18

    refused = game.cast_from_hand(
        0, "Malicious Advice", x_value=1,
        target_permanent_ids=[crusade.permanent_id],
    )
    assert not refused.supported
    assert not crusade.tapped and game.players[0].life == 18

    assert game.cast_from_hand(0, "Malicious Advice", x_value=0).supported
    _w1g8i_resolve_stack(game)
    assert game.players[0].life == 18 and not ring.tapped


def test_w1g8_crosiss_charm_modes(set_pool):
    """Bounce any permanent to its owner's hand; destroy a **nonblack**
    creature through a regeneration shield; destroy an artifact."""
    lea = _w1g8i_lea()
    charm = set_pool("PLS")["Crosis's Charm"]
    assert [_w1g8i_mode_spec(charm, index) for index in range(3)] == [
        {"kind": "permanent"},
        {"kind": "creature", "filter": {"exclude_colors": ["B"]}},
        {"kind": "artifact"},
    ]
    regenerator = _w1g8i_body(
        "Regenerator", 2, 2, "{G}: Regenerate this creature.", colors=("G",),
    )
    game, _, theirs = _w1g8i_duel(
        [], [regenerator, lea["Scathe Zombies"], lea["Sol Ring"], lea["Island"]],
        hand0=[charm] * 4,
    )
    troll, zombies, ring, island = theirs

    assert game.cast_from_hand(
        0, charm.name, mode_index=0, target_permanent_ids=[island.permanent_id]
    ).supported
    _w1g8i_resolve_stack(game)
    assert [card.name for card in game.players[1].hand] == ["Island"]

    # a black creature is not a nonblack one: nothing is destroyed, and the
    # nonblack creature beside it is not taken in its place
    game.cast_from_hand(
        0, charm.name, mode_index=1, target_permanent_ids=[zombies.permanent_id]
    )
    _w1g8i_resolve_stack(game)
    assert game.is_on_battlefield(zombies) and game.is_on_battlefield(troll)

    shielded = game.activate_permanent_ability(1, "Regenerator", ability_index=0)
    assert shielded.supported, shielded.details
    _w1g8i_resolve_stack(game)
    assert game.cast_from_hand(
        0, charm.name, mode_index=1, target_permanent_ids=[troll.permanent_id]
    ).supported
    _w1g8i_resolve_stack(game)
    assert not game.is_on_battlefield(troll), "it can't be regenerated"

    assert game.cast_from_hand(
        0, charm.name, mode_index=2, target_permanent_ids=[ring.permanent_id]
    ).supported
    _w1g8i_resolve_stack(game)
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Scathe Zombies"]


def test_w1g8_darigaazs_charm_modes(set_pool):
    """Raise a creature card from *your* graveyard (not a land card, not the
    opponent's graveyard); 3 damage to any target; +3/+3 until end of turn."""
    lea = _w1g8i_lea()
    charm = set_pool("PLS")["Darigaaz's Charm"]
    assert [_w1g8i_mode_spec(charm, index) for index in range(3)] == [
        {"kind": "graveyard_creature", "own_graveyard_only": True},
        {"kind": "any"},
        {"kind": "creature"},
    ]
    game, mine, theirs = _w1g8i_duel(
        [lea["Grizzly Bears"]], [lea["Hill Giant"]], hand0=[charm] * 5,
        graveyard0=[lea["Island"], lea["Hill Giant"]],
    )

    assert not game.cast_from_hand(
        0, charm.name, mode_index=0, target_permanent_index=0
    ).supported, "slot 0 is a land card"
    assert game.cast_from_hand(
        0, charm.name, mode_index=0, target_permanent_index=1
    ).supported
    _w1g8i_resolve_stack(game)
    assert "Hill Giant" in [card.name for card in game.players[0].hand]
    assert "Hill Giant" not in [card.name for card in game.players[0].graveyard]

    assert game.cast_from_hand(
        0, charm.name, mode_index=1, target_player_index=1
    ).supported
    _w1g8i_resolve_stack(game)
    assert game.players[1].life == 17
    assert game.cast_from_hand(
        0, charm.name, mode_index=1,
        target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g8i_resolve_stack(game)
    game._settle()
    assert not game.is_on_battlefield(theirs[0])

    assert game.cast_from_hand(
        0, charm.name, mode_index=2, target_permanent_ids=[mine[0].permanent_id]
    ).supported
    _w1g8i_resolve_stack(game)
    assert (mine[0].effective_power, mine[0].effective_toughness) == (5, 5)
    game.resolve_cleanup_step(0)
    assert (mine[0].effective_power, mine[0].effective_toughness) == (2, 2)


def test_w1g8_dromars_charm_modes(set_pool):
    """Gain 5; counter a spell (and not castable in that mode onto an empty
    stack); -2/-2 until end of turn, which kills a 2/2 and wears off a 3/3."""
    lea = _w1g8i_lea()
    charm = set_pool("PLS")["Dromar's Charm"]
    assert [_w1g8i_mode_spec(charm, index) for index in range(3)] == [
        None, {"kind": "stack"}, {"kind": "creature"},
    ]
    game, _, theirs = _w1g8i_duel(
        [], [lea["Grizzly Bears"], lea["Hill Giant"]], hand0=[charm] * 5,
        hand1=[lea["Lightning Bolt"]],
    )
    bears, giant = theirs

    assert game.cast_from_hand(0, charm.name, mode_index=0).supported
    _w1g8i_resolve_stack(game)
    assert game.players[0].life == 25

    assert not game.cast_from_hand(0, charm.name, mode_index=1).supported
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(
        0, charm.name, mode_index=1, target_stack_index=0
    ).supported
    _w1g8i_resolve_stack(game)
    assert game.players[0].life == 25, "the Bolt was countered"
    assert "Lightning Bolt" in [card.name for card in game.players[1].graveyard]

    for target in (bears, giant):
        assert game.cast_from_hand(
            0, charm.name, mode_index=2, target_permanent_ids=[target.permanent_id]
        ).supported
        _w1g8i_resolve_stack(game)
    game._settle()
    assert not game.is_on_battlefield(bears)
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)
    game.resolve_cleanup_step(0)
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)


def test_w1g8_terminate_destroys_any_creature_through_regeneration(set_pool):
    """"Destroy target creature. It can't be regenerated." Any colour, either
    battlefield — named by id, so the caster's own creature is the one that
    dies — and never an artifact."""
    lea = _w1g8i_lea()
    terminate = set_pool("PLS")["Terminate"]
    regenerator = _w1g8i_body(
        "Regenerator", 2, 2, "{G}: Regenerate this creature.", colors=("G",),
    )
    game, mine, theirs = _w1g8i_duel(
        [lea["Grizzly Bears"]], [regenerator, lea["Scathe Zombies"], lea["Sol Ring"]],
        hand0=[terminate] * 3,
    )
    assert game.activate_permanent_ability(1, "Regenerator", ability_index=0).supported
    _w1g8i_resolve_stack(game)

    assert game.cast_from_hand(
        0, "Terminate", target_permanent_ids=[theirs[0].permanent_id]
    ).supported
    _w1g8i_resolve_stack(game)
    assert not game.is_on_battlefield(theirs[0])

    assert game.cast_from_hand(
        0, "Terminate", target_permanent_ids=[mine[0].permanent_id]
    ).supported
    _w1g8i_resolve_stack(game)
    assert not game.is_on_battlefield(mine[0])
    assert game.is_on_battlefield(theirs[1]), "the opponent's creature was not named"

    assert not game.cast_from_hand(
        0, "Terminate", target_permanent_ids=[theirs[2].permanent_id]
    ).supported


def test_w1g8_gerrards_command_untaps_and_pumps_one_creature(set_pool):
    lea = _w1g8i_lea()
    command = set_pool("PLS")["Gerrard's Command"]
    game, mine, _ = _w1g8i_duel(
        [lea["Grizzly Bears"], lea["Hill Giant"]], [], hand0=[command],
    )
    bears, giant = mine
    bears.tapped = giant.tapped = True

    assert game.cast_from_hand(
        0, "Gerrard's Command", target_permanent_ids=[giant.permanent_id]
    ).supported
    _w1g8i_resolve_stack(game)

    assert not giant.tapped and bears.tapped
    assert (giant.effective_power, giant.effective_toughness) == (6, 6)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    game.resolve_cleanup_step(0)
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)


def test_w1g8_daring_leap_grants_both_keywords_until_end_of_turn(set_pool):
    lea = _w1g8i_lea()
    leap = set_pool("PLS")["Daring Leap"]
    game, mine, _ = _w1g8i_duel(
        [lea["Grizzly Bears"], lea["Hill Giant"]], [], hand0=[leap],
    )
    bears, giant = mine

    assert game.cast_from_hand(
        0, "Daring Leap", target_permanent_ids=[giant.permanent_id]
    ).supported
    _w1g8i_resolve_stack(game)

    assert (giant.effective_power, giant.effective_toughness) == (4, 4)
    assert giant.has_keyword("flying") and giant.has_keyword("first strike")
    assert not bears.has_keyword("flying")
    game.resolve_cleanup_step(0)
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    assert not giant.has_keyword("flying")
    assert not giant.has_keyword("first strike")
