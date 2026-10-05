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


# --- W1G5: lands and mana ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_cast_spec as _w1g5_derive_cast_spec
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_blessing_table(set_pool, *, mine=(), theirs=(), hand=(), library=()):
    """Seat 0's main phase with *mine*/*theirs* on the battlefield and
    Skyshroud Blessing plus *hand* in seat 0's hand. Costs are off: what the
    spell does is the question. Names resolve in Planeshift, then Alpha."""
    pls, lea = set_pool("PLS"), set_pool("LEA")

    def card(name):
        return pls[name] if name in pls else lea[name]

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(name)) for name in mine],
        hand=[pls["Skyshroud Blessing"], *(card(name) for name in hand)],
        library=[card(name) for name in library],
    )
    you = _W1G5PlayerState(
        name="W1G5-B",
        battlefield=[_W1G5Permanent(card=card(name)) for name in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game  # _w1g5_blessing_table


def _w1g5_shrouded(game) -> dict[str, bool]:
    """Every permanent on the battlefield, by ``seat:name``, and whether it has
    shroud right now (layer 6)."""
    return {
        f"{seat}:{permanent.card.name}": game._has_keyword(permanent, "shroud")
        for seat, permanent in game.permanents_with_controller()
    }  # _w1g5_shrouded


def test_w1g5_skyshroud_blessing_shrouds_every_land_and_draws(set_pool):
    """"All lands gain shroud until end of turn. Draw a card." Both sentences
    resolve: every player's lands have shroud — "all", not "you control" —
    nothing that is not a land does, and the caster draws. It names no target,
    so the picker asks for none."""
    blessing = set_pool("PLS")["Skyshroud Blessing"]
    assert _w1g5_derive_cast_spec(blessing, _w1g5_compile(blessing)) is None

    game = _w1g5_blessing_table(
        set_pool, mine=["Forest", "Grizzly Bears", "Sol Ring"],
        theirs=["Island", "Hill Giant"], library=["Swamp"],
    )
    assert game.cast_from_hand(0, "Skyshroud Blessing").supported
    _w1g5_resolve_stack(game)

    assert _w1g5_shrouded(game) == {
        "0:Forest": True, "0:Grizzly Bears": False, "0:Sol Ring": False,
        "1:Island": True, "1:Hill Giant": False,
    }
    assert [card.name for card in game.players[0].hand] == ["Swamp"]
    assert [card.name for card in game.players[0].graveyard] == ["Skyshroud Blessing"]


def test_w1g5_skyshroud_blessing_locks_its_lands_in_at_resolution(set_pool):
    """CR 611.2c: a continuous effect from a resolving spell that affects a set
    of objects fixes that set as it resolves. A land played afterwards the
    same turn does not have shroud; the lands that were there keep it."""
    game = _w1g5_blessing_table(
        set_pool, mine=["Forest"], hand=["Mountain"], library=["Swamp"],
    )
    game.cast_from_hand(0, "Skyshroud Blessing")
    _w1g5_resolve_stack(game)
    assert game.cast_from_hand(0, "Mountain").supported

    assert _w1g5_shrouded(game) == {"0:Forest": True, "0:Mountain": False}


def test_w1g5_a_shrouded_land_cannot_be_targeted_until_the_turn_ends(set_pool):
    """What shroud is for (CR 702.18a): Implode's "Destroy target land" cannot
    name a land the Blessing covered — refused at announcement with the card
    still in hand — and can name the land that arrived too late. At cleanup
    the grant ends (CR 514.2) and the first land is a legal target again."""
    game = _w1g5_blessing_table(
        set_pool, mine=["Forest"], theirs=["Island"],
        hand=["Implode", "Mountain"], library=["Swamp", "Swamp", "Swamp"],
    )
    game.cast_from_hand(0, "Skyshroud Blessing")
    _w1g5_resolve_stack(game)
    game.cast_from_hand(0, "Mountain")
    (island,) = list(game.controlled_by(1))
    (mountain,) = [p for p in game.controlled_by(0) if p.card.name == "Mountain"]

    refused = game.cast_from_hand(
        0, "Implode", target_player_index=1,
        target_permanent_ids=[island.permanent_id],
    )
    assert not refused.supported, refused
    assert "Implode" in [card.name for card in game.players[0].hand]
    assert game.is_on_battlefield(island)

    assert game.resolve_cleanup_step(0)
    assert not game._has_keyword(island, "shroud")
    game._set_phase_and_step("precombat_main", "precombat_main")
    cast = game.cast_from_hand(
        0, "Implode", target_player_index=1,
        target_permanent_ids=[island.permanent_id],
    )
    assert cast.supported, cast
    _w1g5_resolve_stack(game)
    assert not game.is_on_battlefield(island)
    assert game.is_on_battlefield(mountain)


def test_w1g5_a_typed_mass_keyword_grant_is_one_production(set_pool):
    """The grant is the team keyword grant over a board named by a card type:
    the handler had both widths (creatures, every permanent) and a filter, and
    the lowering admitted only the two widths, so "All lands gain …" was an
    unsupported subject. An invented "Artifacts you control gain shroud until
    end of turn." is the same production: your artifacts, and nobody else's."""
    (grant, _draw) = _w1g5_compile(set_pool("PLS")["Skyshroud Blessing"]).instructions
    assert grant.kind == "grant_team_keyword_until_eot"
    assert grant.payload == {
        "keywords": ("shroud",), "every_permanent": True,
        "filter": {"type_filter": "land"}, "every_seat": True,
        "duration": "end_of_turn",
    }

    invented = _w1g5_mk_card(
        name="Foundry Ward", mana_cost="{W}", type_line="Instant",
        oracle_text="Artifacts you control gain shroud until end of turn.",
    )
    game = _w1g5_blessing_table(
        set_pool, mine=["Sol Ring", "Forest"], theirs=["Sol Ring"],
    )
    game.players[0].hand.append(invented)
    assert game.cast_from_hand(0, "Foundry Ward").supported
    _w1g5_resolve_stack(game)
    assert _w1g5_shrouded(game) == {
        "0:Sol Ring": True, "0:Forest": False, "1:Sol Ring": False,
    }

    # Two card types at once, which the lowering used to refuse outright
    # (`tests/engine/test_grammar_lowering.py` pinned the refusal): only the
    # permanent that is both gets the keyword.
    both = _w1g5_mk_card(
        name="Gearlift", mana_cost="{U}", type_line="Instant",
        oracle_text="Artifact creatures you control gain flying until end of turn.",
    )
    game = _w1g5_blessing_table(
        set_pool, mine=["Obsianus Golem", "Sol Ring", "Grizzly Bears"],
        theirs=["Obsianus Golem"],
    )
    game.players[0].hand.append(both)
    assert game.cast_from_hand(0, "Gearlift").supported
    _w1g5_resolve_stack(game)
    assert {
        f"{seat}:{permanent.card.name}": game._has_keyword(permanent, "flying")
        for seat, permanent in game.permanents_with_controller()
    } == {
        "0:Obsianus Golem": True, "0:Sol Ring": False, "0:Grizzly Bears": False,
        "1:Obsianus Golem": False,
    }


def test_w1g5_the_blessing_in_response_saves_the_land_and_implode_draws_nothing(set_pool):
    """The two cards on one stack. Implode names an opponent's Forest; the
    Blessing resolves first and the Forest has shroud, so when Implode comes
    to resolve its only target is illegal and it is removed from the stack
    with neither sentence performed (CR 608.2b) — the Forest survives and the
    one card drawn is the Blessing's."""
    game = _w1g5_blessing_table(
        set_pool, theirs=["Forest"], hand=["Implode"], library=["Swamp", "Plains"],
    )
    (forest,) = list(game.controlled_by(1))
    assert game.queue_from_hand(
        0, "Implode", target_player_index=1,
        target_permanent_ids=[forest.permanent_id],
    ).supported
    assert game.queue_from_hand(0, "Skyshroud Blessing").supported
    _w1g5_resolve_stack(game)

    assert game.is_on_battlefield(forest)
    assert len(game.players[0].hand) == 1, "one draw, not two"
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Implode", "Skyshroud Blessing",
    ]


# --- W1G2: two kickers ---
# Ertai's Trickery — "Counter target spell if it was kicked." Supported on
# arrival and countering nothing: the pronoun was read as the spell asking, and
# Ertai's Trickery prints no kicker.
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.cast_costs import kicked as _w1g2_kicked
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_counter_table(set_pool, spell_name, spell_set):
    """Seat 0 holds *spell_name*, seat 1 holds Ertai's Trickery; both have mana
    floating and costs are charged."""
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Kicker", library=[forest] * 10, hand=[set_pool(spell_set)[spell_name]],
        ),
        _W1G2PlayerState(
            "Ertai", library=[forest] * 10,
            hand=[set_pool("PLS")["Ertai's Trickery"]],
        ),
    ])
    game.enforce_mana_costs = True
    for seat in (0, 1):
        game.players[seat].mana_pool.update(
            {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}
        )
    return game  # _w1g2_counter_table


def _w1g2_trick(game, spell_name, kick=None, **announced):
    """Seat 0 casts *spell_name* (paying the costs in *kick*), seat 1 answers
    with Ertai's Trickery aimed at it, and everything resolves. Returns whether
    the spell on the stack was a kicked one."""
    assert game.queue_from_hand(
        0, spell_name, optional_cost_payments=kick, **announced
    ).supported
    item = game.stack[-1]
    was_kicked = _w1g2_kicked(item.card, item.choices)
    answer = game.queue_from_hand(
        1, "Ertai's Trickery", target_stack_index=len(game.stack) - 1
    )
    assert answer.supported, answer
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in game.players[1].graveyard] == ["Ertai's Trickery"]
    return was_kicked  # _w1g2_trick


def test_w1g2_ertais_trickery_counters_a_kicked_spell_and_only_a_kicked_one(set_pool):
    """The pronoun is the *targeted* spell (CR 608.2c). A kicked Kavu Titan is
    countered; the same Titan cast for {1}{G} resolves, and the Trickery is
    spent either way."""
    game = _w1g2_counter_table(set_pool, "Kavu Titan", "INV")
    assert _w1g2_trick(game, "Kavu Titan", {"{2}{G}": 1}) is True
    assert [c.name for c in game.players[0].graveyard] == ["Kavu Titan"]
    assert list(game.controlled_by(0)) == []

    game = _w1g2_counter_table(set_pool, "Kavu Titan", "INV")
    assert _w1g2_trick(game, "Kavu Titan") is False
    assert [p.card.name for p in game.controlled_by(0)] == ["Kavu Titan"]
    assert game.players[0].graveyard == []


@_w1g2_pytest.mark.parametrize("kick,countered", [
    (None, False),
    ({"{1}{G}": 1}, True),
    ({"{2}{U}": 1}, True),
    ({"{1}{G}": 1, "{2}{U}": 1}, True),
])
def test_w1g2_ertais_trickery_reads_either_of_two_kickers(set_pool, kick, countered):
    """CR 702.33d: a spell is kicked if its controller paid **any** of its
    kicker costs. A Sunscape Battlemage that paid only its second is as kicked
    as one that paid both — and one that paid neither is not."""
    game = _w1g2_counter_table(set_pool, "Sunscape Battlemage", "PLS")
    assert _w1g2_trick(game, "Sunscape Battlemage", kick) is countered
    on_board = [p.card.name for p in game.controlled_by(0)]
    in_yard = [c.name for c in game.players[0].graveyard]
    if countered:
        assert (on_board, in_yard) == ([], ["Sunscape Battlemage"])
        # …and a countered Battlemage never entered, so nothing was drawn.
        assert game.players[0].hand == []
    else:
        assert (on_board, in_yard) == (["Sunscape Battlemage"], [])


def test_w1g2_ertais_trickery_does_not_take_another_optional_cost_for_a_kicker(set_pool):
    """Buyback is an optional additional cost too (CR 702.27a), and it is not a
    kicker: a bought-back Capsize is not countered, returns its target, and
    comes back to its owner's hand."""
    game = _w1g2_counter_table(set_pool, "Capsize", "TMP")
    forest = _W1G2Permanent(card=set_pool("LEA")["Forest"])
    game._put_permanent_onto_battlefield(1, forest, None)
    assert _w1g2_trick(
        game, "Capsize", {"{3}": 1}, target_permanent_ids=[forest.permanent_id]
    ) is False
    assert not game.is_on_battlefield(forest)
    assert [c.name for c in game.players[0].hand] == ["Capsize"]


def test_w1g2_ertais_trickery_may_be_aimed_at_any_spell(set_pool):
    """"Target spell" is the whole of the printed restriction (CR 608.2b), so
    the picker offers an unkicked spell too — the "if" is read as the Trickery
    resolves, not as it is announced."""
    game = _w1g2_counter_table(set_pool, "Kavu Titan", "INV")
    assert game.queue_from_hand(0, "Kavu Titan").supported
    spec = game.cast_target_spec(1, set_pool("PLS")["Ertai's Trickery"])
    assert spec["kind"] == "stack" and spec["requires_target"]
    assert len(spec["valid_targets"]) == 1
# end of the W1G2 instants block


# --- W1G1: non-mana kicker ---
#
# "Kicker—Sacrifice a land." on five instants, the second sentence each one
# prints about being kicked (CR 702.33d/g), Orim's Chant's cast ban, and Death
# Bomb's mandatory twin of the same cost. Imports are in this block, per the
# header's parallel-authorship convention.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.ai_policy import choose_cast_action as _w1g1_choose_cast_action
from engine.cast_costs import kicker_cost as _w1g1_kicker_cost
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import _damage_dealt as _w1g1_damage_dealt
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}


def _w1g1_card(set_pool, name):
    pls = set_pool("PLS")
    return pls[name] if name in pls else set_pool("LEA")[name]  # _w1g1_card (instants)


def _w1g1_duel(set_pool, hand, *, pool=None, their_hand=()):
    """A two-seat game that **charges mana**, seat 0 holding *hand* with *pool*
    floating; seat 1 holds *their_hand* with mana of its own."""
    forest = set_pool("LEA")["Forest"]
    mine = _W1G1PlayerState(
        "Kicker", library=[forest] * 10,
        hand=[_w1g1_card(set_pool, name) for name in hand],
    )
    theirs = _W1G1PlayerState(
        "Bystander", library=[forest] * 10,
        hand=[_w1g1_card(set_pool, name) for name in their_hand],
    )
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G1_RICH if pool is None else pool)
    game.players[1].mana_pool.update(_W1G1_RICH)
    return game  # _w1g1_duel (instants)


def _w1g1_put(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (instants)


def _w1g1_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))  # _w1g1_names (instants)


def _w1g1_key(set_pool, name):
    return _w1g1_kicker_cost(set_pool("PLS")[name].oracle_text)  # _w1g1_key (instants)


# -- Falling Timber ----------------------------------------------------------


def _w1g1_timber_table(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Falling Timber"])
    land = _w1g1_put(game, 0, lea["Forest"])
    bears = _w1g1_put(game, 1, lea["Grizzly Bears"])
    giant = _w1g1_put(game, 1, lea["Hill Giant"])
    return game, land, bears, giant  # _w1g1_timber_table


def test_w1g1_falling_timber_unkicked_names_one_creature_and_stops_only_it(set_pool):
    """CR 702.33g: the second target belongs to a kicked cast alone. An unkicked
    Falling Timber is a one-target spell — this was refused "requires 2
    targets", because the two targets are one roles announcement and the role
    list sat on the step *outside* the kicked arm."""
    game, land, bears, giant = _w1g1_timber_table(set_pool)
    spec = game.cast_target_spec(0, set_pool("PLS")["Falling Timber"], optional_cost_payments={})
    assert spec["kind"] == "creature" and len(spec["valid_targets"]) == 2

    result = game.cast_from_hand(
        0, "Falling Timber", target_permanent_ids=[bears.permanent_id]
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    me = game.players[0]
    assert _w1g1_damage_dealt(game, me, 2, source=bears, combat=True) == 0
    assert _w1g1_damage_dealt(game, me, 3, source=giant, combat=True) == 3
    assert _w1g1_damage_dealt(game, me, 2, source=bears) == 2, "combat damage only"
    assert game.is_on_battlefield(land), "no kicker, no land"


def test_w1g1_falling_timber_kicked_sacrifices_the_land_and_stops_both(set_pool):
    game, land, bears, giant = _w1g1_timber_table(set_pool)
    key = _w1g1_key(set_pool, "Falling Timber")
    assert key == "sacrifice a land"

    result = game.cast_from_hand(
        0, "Falling Timber", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
        cost_permanent_ids=[land.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    me = game.players[0]
    assert not game.is_on_battlefield(land)
    assert _w1g1_damage_dealt(game, me, 2, source=bears, combat=True) == 0
    assert _w1g1_damage_dealt(game, me, 3, source=giant, combat=True) == 0


def test_w1g1_falling_timbers_two_targets_are_two_and_only_when_kicked(set_pool):
    """Both directions of CR 702.33g, and the printed "another" (CR 601.2c).
    Each refusal lands before anything is paid: the land is still there."""
    key = _w1g1_key(set_pool, "Falling Timber")

    game, land, bears, giant = _w1g1_timber_table(set_pool)
    two_unkicked = game.cast_from_hand(
        0, "Falling Timber",
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    assert not two_unkicked.supported and "702.33g" in two_unkicked.details

    one_kicked = game.cast_from_hand(
        0, "Falling Timber", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id],
        cost_permanent_ids=[land.permanent_id],
    )
    assert not one_kicked.supported and "2 targets" in one_kicked.details

    same_twice = game.cast_from_hand(
        0, "Falling Timber", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, bears.permanent_id],
        cost_permanent_ids=[land.permanent_id],
    )
    assert not same_twice.supported
    assert game.is_on_battlefield(land)
    assert [c.name for c in game.players[0].hand] == ["Falling Timber"]


def test_w1g1_an_unkicked_falling_timber_cannot_be_aimed_at_a_land(set_pool):
    """The named target of the *unkicked* cast is checked against the one-target
    spec. Read as the whole card it is a roles spell, which the named-target
    gate hands on — and the gate it hands on to no longer saw roles."""
    game, land, bears, giant = _w1g1_timber_table(set_pool)
    refused = game.cast_from_hand(
        0, "Falling Timber", target_permanent_ids=[land.permanent_id]
    )
    assert not refused.supported
    assert sum(game.players[0].mana_pool.values()) == sum(_W1G1_RICH.values())


def test_w1g1_a_kicked_falling_timber_offers_the_land_it_sacrifices(set_pool):
    """The kicked spec is roles *and* a cost picker — the first such pair, and
    the roles branch returned before filling the cost's candidates, so the
    picker described a land to give up and offered none."""
    game, land, bears, giant = _w1g1_timber_table(set_pool)
    key = _w1g1_key(set_pool, "Falling Timber")
    spec = game.cast_target_spec(
        0, set_pool("PLS")["Falling Timber"], optional_cost_payments={key: 1}
    )
    assert [role["role"] for role in spec["roles"]] == ["creature", "another creature"]
    assert spec["cost_spec"]["sacrifice_cost"] and spec["cost_spec"]["kind"] == "land"
    assert [t["name"] for t in spec["cost_spec"]["valid_targets"]] == ["Forest"]
    first = spec["valid_targets"][0]
    assert first["name"] == "Grizzly Bears"
    assert [t["name"] for t in first["next"]] == ["Hill Giant"], "never the same one"


# -- Rushing River -----------------------------------------------------------


def _w1g1_river_table(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Rushing River"])
    island = _w1g1_put(game, 0, lea["Island"])
    bears = _w1g1_put(game, 1, lea["Grizzly Bears"])
    ring = _w1g1_put(game, 1, lea["Sol Ring"])
    their_land = _w1g1_put(game, 1, lea["Forest"])
    return game, island, bears, ring, their_land  # _w1g1_river_table


def test_w1g1_rushing_river_unkicked_bounces_one_nonland_permanent(set_pool):
    game, island, bears, ring, their_land = _w1g1_river_table(set_pool)
    spec = game.cast_target_spec(0, set_pool("PLS")["Rushing River"], optional_cost_payments={})
    assert sorted(t["name"] for t in spec["valid_targets"]) == ["Grizzly Bears", "Sol Ring"]

    assert game.cast_from_hand(
        0, "Rushing River", target_permanent_ids=[ring.permanent_id]
    ).supported
    _w1g1_resolve_stack(game)
    assert [c.name for c in game.players[1].hand] == ["Sol Ring"]
    assert _w1g1_names(game, 1) == ["Forest", "Grizzly Bears"]
    assert game.is_on_battlefield(island)


def test_w1g1_rushing_river_kicked_bounces_two_for_a_land(set_pool):
    game, island, bears, ring, their_land = _w1g1_river_table(set_pool)
    key = _w1g1_key(set_pool, "Rushing River")
    result = game.cast_from_hand(
        0, "Rushing River", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, ring.permanent_id],
        cost_permanent_ids=[island.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert sorted(c.name for c in game.players[1].hand) == ["Grizzly Bears", "Sol Ring"]
    assert _w1g1_names(game, 1) == ["Forest"]
    assert not game.is_on_battlefield(island)


def test_w1g1_rushing_river_never_names_a_land_in_either_slot(set_pool):
    """"Nonland" is printed on both targets, and both are enforced at the
    announcement (CR 601.2c) with nothing paid."""
    game, island, bears, ring, their_land = _w1g1_river_table(set_pool)
    key = _w1g1_key(set_pool, "Rushing River")
    assert not game.cast_from_hand(
        0, "Rushing River", target_permanent_ids=[their_land.permanent_id]
    ).supported
    assert not game.cast_from_hand(
        0, "Rushing River", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, their_land.permanent_id],
        cost_permanent_ids=[island.permanent_id],
    ).supported
    assert game.is_on_battlefield(island)
    assert [c.name for c in game.players[0].hand] == ["Rushing River"]


def test_w1g1_a_kicked_river_whose_first_target_left_still_bounces_the_second(set_pool):
    """CR 608.2b: one of two targets gone is a spell that still resolves, and
    the step whose object left does nothing — it must not slide onto the other
    creature, nor skip the kicked half."""
    game, island, bears, ring, their_land = _w1g1_river_table(set_pool)
    key = _w1g1_key(set_pool, "Rushing River")
    assert game.queue_from_hand(
        0, "Rushing River", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, ring.permanent_id],
        cost_permanent_ids=[island.permanent_id],
    ).supported
    game.remove_from_battlefield(bears)
    _w1g1_resolve_stack(game)
    assert [c.name for c in game.players[1].hand] == ["Sol Ring"]
    assert _w1g1_names(game, 1) == ["Forest"]


def _w1g1_ai_table(set_pool, name, land, lands):
    """Seat 0 on its own main phase holding *name* with *lands* untapped copies
    of *land* and an empty pool, a creature on each side and an artifact."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, [name], pool={})
    for _ in range(lands):
        _w1g1_put(game, 0, lea[land])
    _w1g1_put(game, 0, lea["Grizzly Bears"])
    _w1g1_put(game, 1, lea["Hill Giant"])
    _w1g1_put(game, 1, lea["Sol Ring"])
    game.active_player_index = 0
    game.current_phase = "main"
    return game  # _w1g1_ai_table


@_w1g1_pytest.mark.parametrize(
    "name,land", [("Rushing River", "Island"), ("Falling Timber", "Forest")]
)
def test_w1g1_the_ai_casts_the_plain_spell_when_it_cannot_spare_the_kick(
    set_pool, name, land
):
    """It must not stall. With four lands the seat declines the kicker — and
    then has to be able to build the *unkicked* cast, whose one target the
    engine's enumeration probes against the unkicked spec. Probed against the
    card's every arm (two roles) no single target was ever legal, so the seat
    held both cards until it had a land to spare; and the cast it proposes is
    one the engine accepts."""
    game = _w1g1_ai_table(set_pool, name, land, lands=4)
    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == name
    assert not action.optional_cost_payments
    assert len(action.target_permanent_ids) == 1

    from engine.ai_policy import tap_planned_lands

    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(
        0, name, target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
    )
    assert result.supported, result.details


@_w1g1_pytest.mark.parametrize(
    "name,land", [("Rushing River", "Island"), ("Falling Timber", "Forest")]
)
def test_w1g1_the_ai_names_two_targets_for_the_spell_it_kicks(set_pool, name, land):
    """…and with nine it kicks, walking the *kicked* spec's chain of two
    roles rather than the unkicked picker's flat list."""
    game = _w1g1_ai_table(set_pool, name, land, lands=9)
    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == name
    assert action.optional_cost_payments == {_w1g1_key(set_pool, name): 1}
    assert len(set(action.target_permanent_ids)) == 2


# -- Magma Burst -------------------------------------------------------------


def _w1g1_burst_table(set_pool, mountains=3):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Magma Burst"])
    lands = [_w1g1_put(game, 0, lea["Mountain"]) for _ in range(mountains)]
    giant = _w1g1_put(game, 1, lea["Hill Giant"])
    return game, lands, giant  # _w1g1_burst_table


def test_w1g1_magma_burst_unkicked_is_three_damage_to_one_target(set_pool):
    game, lands, giant = _w1g1_burst_table(set_pool)
    spec = game.cast_target_spec(0, set_pool("PLS")["Magma Burst"], optional_cost_payments={})
    assert spec["kind"] == "any"
    assert game.cast_from_hand(0, "Magma Burst", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert game.players[1].life == 17
    assert game.is_on_battlefield(giant) and len(_w1g1_names(game, 0)) == 3


def test_w1g1_magma_burst_kicked_deals_three_to_each_of_two_targets(set_pool):
    """Kicked: two lands, and 3 damage to *each* of two different targets — a
    creature and a face here, which is why this is a cross-seat list and not
    two roles. It dealt 1 and 1: the division gate read the card's every arm,
    found no divided step under the kicked arm, stamped no share, and the
    handler fell back to the even split of 3."""
    game, lands, giant = _w1g1_burst_table(set_pool)
    key = _w1g1_key(set_pool, "Magma Burst")
    assert key == "sacrifice two lands"
    spec = game.cast_target_spec(
        0, set_pool("PLS")["Magma Burst"], optional_cost_payments={key: 1}
    )
    assert (spec["kind"], spec["division"], spec["divided_target_count"]) == (
        "divided", "each", 2,
    )
    assert spec["cost_spec"]["count"] == 2

    result = game.cast_from_hand(
        0, "Magma Burst", optional_cost_payments={key: 1},
        divided_targets=[(1, 0), (1, None)],
        cost_permanent_ids=[lands[0].permanent_id, lands[2].permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    assert game.players[1].life == 17
    assert not game.is_on_battlefield(giant), "3 damage, not a 1/1 split"
    assert [p.permanent_id for p in game.controlled_by(0)] == [lands[1].permanent_id]


def test_w1g1_magma_bursts_kicked_targets_are_exactly_two_different_ones(set_pool):
    """CR 601.2c: "another target" is a different one, and a kicked Magma Burst
    has two — not one, and not the same face twice. Each is refused before the
    lands are sacrificed."""
    game, lands, giant = _w1g1_burst_table(set_pool)
    key = _w1g1_key(set_pool, "Magma Burst")
    for announced in (
        {"divided_targets": [(1, None), (1, None)]},
        {"divided_targets": [(1, None)]},
        {"target_player_index": 1},
    ):
        refused = game.cast_from_hand(
            0, "Magma Burst", optional_cost_payments={key: 1}, **announced
        )
        assert not refused.supported, announced
    assert len(_w1g1_names(game, 0)) == 3
    assert game.players[1].life == 20

    both_faces = game.cast_from_hand(
        0, "Magma Burst", optional_cost_payments={key: 1},
        divided_targets=[(1, None), (0, None)],
    )
    assert both_faces.supported, both_faces.details
    _w1g1_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (17, 17)


def test_w1g1_magma_burst_cannot_be_kicked_with_one_land(set_pool):
    game, lands, giant = _w1g1_burst_table(set_pool, mountains=1)
    key = _w1g1_key(set_pool, "Magma Burst")
    refused = game.cast_from_hand(
        0, "Magma Burst", optional_cost_payments={key: 1},
        divided_targets=[(1, 0), (1, None)],
    )
    assert not refused.supported and "601.2h" in refused.details
    assert game.is_on_battlefield(lands[0])


def test_w1g1_the_ai_announces_two_targets_for_a_magma_burst_it_kicks(set_pool):
    """A kicked candidate is built against the kicked spec. The AI's divided
    chooser read the card's every arm (no divided step) and the unkicked
    picker, so a kicked Magma Burst went out with one bare target and was
    refused. Eight Mountains: enough to pay {3}{R} and still spare two."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Magma Burst"], pool={})
    for _ in range(8):
        _w1g1_put(game, 0, lea["Mountain"])
    _w1g1_put(game, 1, lea["Hill Giant"])
    game.active_player_index = 0
    game.current_phase = "main"
    key = _w1g1_key(set_pool, "Magma Burst")

    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Magma Burst"
    assert action.optional_cost_payments == {key: 1}
    assert len(action.divided_targets) == 2
    assert len(set(tuple(entry[:2]) for entry in action.divided_targets)) == 2


def test_w1g1_the_ai_keeps_its_lands_when_it_has_four(set_pool):
    """It must not sacrifice half its mana for a marginal kick: four lands cast
    the plain spell, kicker declined, one target named."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Magma Burst"], pool={})
    for _ in range(4):
        _w1g1_put(game, 0, lea["Mountain"])
    game.active_player_index = 0
    game.current_phase = "main"

    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Magma Burst"
    assert not action.optional_cost_payments and not action.divided_targets


# -- Pollen Remedy -----------------------------------------------------------


def _w1g1_remedy_table(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Pollen Remedy"])
    plains = _w1g1_put(game, 0, lea["Plains"])
    bears = _w1g1_put(game, 0, lea["Grizzly Bears"])
    return game, plains, bears  # _w1g1_remedy_table


def test_w1g1_pollen_remedy_unkicked_divides_three(set_pool):
    game, plains, bears = _w1g1_remedy_table(set_pool)
    result = game.cast_from_hand(
        0, "Pollen Remedy", divided_targets=[(0, 1, 1), (0, None, 2)]
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert _w1g1_damage_dealt(game, game.players[0], 5) == 3
    assert _w1g1_damage_dealt(game, bears, 9) == 8
    assert game.is_on_battlefield(plains)


def test_w1g1_pollen_remedy_kicked_divides_six_this_way(set_pool):
    """"…prevent the next 6 damage **this way** instead." The replaced
    sentence at another size: the same targets, the same division, six where
    there were three — one shield, not three and then six."""
    game, plains, bears = _w1g1_remedy_table(set_pool)
    key = _w1g1_key(set_pool, "Pollen Remedy")
    result = game.cast_from_hand(
        0, "Pollen Remedy", optional_cost_payments={key: 1},
        divided_targets=[(0, 1, 4), (0, None, 2)],
        cost_permanent_ids=[plains.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert not game.is_on_battlefield(plains)
    assert _w1g1_damage_dealt(game, game.players[0], 5) == 3
    assert _w1g1_damage_dealt(game, bears, 9) == 5, "four prevented, not seven"


def test_w1g1_pollen_remedys_division_totals_what_this_cast_prevents(set_pool):
    """CR 601.2d: the shares total the arm that will run — three unkicked, six
    kicked — and a division of the other arm's total is refused unpaid."""
    game, plains, bears = _w1g1_remedy_table(set_pool)
    key = _w1g1_key(set_pool, "Pollen Remedy")
    six_unkicked = game.cast_from_hand(
        0, "Pollen Remedy", divided_targets=[(0, 1, 4), (0, None, 2)]
    )
    assert not six_unkicked.supported and "total 3" in six_unkicked.details
    three_kicked = game.cast_from_hand(
        0, "Pollen Remedy", optional_cost_payments={key: 1},
        divided_targets=[(0, 1, 1), (0, None, 2)],
        cost_permanent_ids=[plains.permanent_id],
    )
    assert not three_kicked.supported and "total 6" in three_kicked.details
    assert game.is_on_battlefield(plains)


# -- Orim's Chant ------------------------------------------------------------


def _w1g1_chant_table(set_pool):
    """Seat 1's turn: it holds an instant, a creature spell and a land; seat 0
    holds Orim's Chant."""
    lea = set_pool("LEA")
    game = _w1g1_duel(
        set_pool, ["Orim's Chant"],
        their_hand=["Lightning Bolt", "Grizzly Bears", "Forest"],
    )
    game.active_player_index = 1
    game.current_phase = "main"
    attacker = _w1g1_put(game, 1, lea["Hill Giant"])
    return game, attacker  # _w1g1_chant_table


def test_w1g1_orims_chant_stops_every_spell_and_no_land_drop(set_pool):
    """"Target player can't cast spells this turn." No type printed, so every
    spell — and a land is not one (CR 305.1), so the land drop goes through.
    Each refused cast costs the player nothing."""
    game, attacker = _w1g1_chant_table(set_pool)
    assert game.cast_from_hand(0, "Orim's Chant", target_player_index=1).supported
    _w1g1_resolve_stack(game)

    before = sum(game.players[1].mana_pool.values())
    for name in ("Lightning Bolt", "Grizzly Bears"):
        refused = game.cast_from_hand(1, name, target_player_index=0)
        assert not refused.supported and "can't cast any spells" in refused.details
    assert sum(game.players[1].mana_pool.values()) == before
    assert game.cast_from_hand(1, "Forest").supported
    assert "Forest" in _w1g1_names(game, 1)

    # …and the caster is not bound by its own Chant.
    assert not game.spell_types_forbidden_this_turn.get(0)


def test_w1g1_orims_chant_unkicked_leaves_creatures_free_to_attack(set_pool):
    game, attacker = _w1g1_chant_table(set_pool)
    before = sum(game.players[0].mana_pool.values())
    assert game.cast_from_hand(0, "Orim's Chant", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert before - sum(game.players[0].mana_pool.values()) == 1
    assert game.can_attack(attacker, 0)


def test_w1g1_orims_chant_kicked_also_stops_every_attack(set_pool):
    """Kicker {W}: "…creatures can't attack this turn." — every creature, the
    caster's own included, and one that arrives after the Chant resolved."""
    lea = set_pool("LEA")
    game, attacker = _w1g1_chant_table(set_pool)
    mine = _w1g1_put(game, 0, lea["Grizzly Bears"])
    key = _w1g1_key(set_pool, "Orim's Chant")
    assert key == "{W}"
    before = sum(game.players[0].mana_pool.values())
    assert game.cast_from_hand(
        0, "Orim's Chant", target_player_index=1, optional_cost_payments={key: 1}
    ).supported
    _w1g1_resolve_stack(game)
    assert before - sum(game.players[0].mana_pool.values()) == 2

    assert not game.can_attack(attacker, 0)
    assert not game.can_attack(mine, 1)
    late = _w1g1_put(game, 1, lea["Grizzly Bears"])
    assert not game.can_attack(late, 0)


def test_w1g1_orims_chant_ends_with_the_turn(set_pool):
    """"This turn": the record is dropped at the turn boundary, and the player
    casts again."""
    from engine.spell_prohibitions import clear_turn_spell_prohibitions

    game, attacker = _w1g1_chant_table(set_pool)
    assert game.cast_from_hand(0, "Orim's Chant", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert not game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported

    clear_turn_spell_prohibitions(game)
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported


def test_w1g1_a_seat_under_orims_chant_proposes_no_spell(set_pool):
    """A banned seat reads as unable to cast rather than being refused each
    time it tries: the AI's proposal filter asks the record the cast path
    refuses by, and still plays its land."""
    game, attacker = _w1g1_chant_table(set_pool)
    assert _w1g1_choose_cast_action(game, 1) is not None, "it had something to cast"

    assert game.cast_from_hand(0, "Orim's Chant", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    proposed = _w1g1_choose_cast_action(game, 1)
    assert proposed is None or proposed.card_name == "Forest"


# -- Death Bomb --------------------------------------------------------------


def _w1g1_bomb_table(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Death Bomb"])
    fodder = _w1g1_put(game, 0, lea["Grizzly Bears"])
    keeper = _w1g1_put(game, 0, lea["Hill Giant"])
    victim = _w1g1_put(game, 1, lea["Hill Giant"])
    black = _w1g1_put(game, 1, lea["Drudge Skeletons"])
    return game, fodder, keeper, victim, black  # _w1g1_bomb_table


def test_w1g1_death_bomb_sacrifices_the_creature_named_and_kills_its_target(set_pool):
    """The mandatory twin of the kicker's cost: the creature the caster names
    is sacrificed as the spell is cast, the target is destroyed and cannot be
    regenerated, and its controller loses 2 life."""
    game, fodder, keeper, victim, black = _w1g1_bomb_table(set_pool)
    victim.regeneration_shield = 1
    before = sum(game.players[0].mana_pool.values())

    result = game.queue_from_hand(
        0, "Death Bomb", target_permanent_ids=[victim.permanent_id],
        cost_permanent_ids=[fodder.permanent_id],
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(fodder), "paid on the way to the stack"
    assert before - sum(game.players[0].mana_pool.values()) == 4
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(victim), "the shield does not save it"
    assert game.is_on_battlefield(keeper) and game.is_on_battlefield(black)
    assert game.players[1].life == 18


def test_w1g1_death_bomb_is_refused_unpaid_without_a_creature_or_a_nonblack_target(set_pool):
    """CR 601.2h and CR 601.2c, each before any mana leaves the pool: no
    creature to sacrifice, and a black creature as the target."""
    lea = set_pool("LEA")
    full = sum(_W1G1_RICH.values())

    game = _w1g1_duel(set_pool, ["Death Bomb"])
    victim = _w1g1_put(game, 1, lea["Hill Giant"])
    unpaid = game.cast_from_hand(
        0, "Death Bomb", target_permanent_ids=[victim.permanent_id]
    )
    assert not unpaid.supported and "601.2h" in unpaid.details
    assert sum(game.players[0].mana_pool.values()) == full
    assert _w1g1_choose_cast_action(game, 0) is None, "nor does the AI propose it"

    game, fodder, keeper, victim, black = _w1g1_bomb_table(set_pool)
    at_black = game.cast_from_hand(
        0, "Death Bomb", target_permanent_ids=[black.permanent_id]
    )
    assert not at_black.supported
    assert game.is_on_battlefield(fodder) and game.is_on_battlefield(keeper)
    assert sum(game.players[0].mana_pool.values()) == full


# --- W1G4: domain ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_instant_table(set_pool, spell, mine=(), theirs=()):
    """*spell* in seat 0's hand over two boards of Alpha permanents, costs off:
    what the card under test does is a size, not a price."""
    w1g4_lea = set_pool("LEA")
    w1g4_game = _W1G4Game(players=[
        _W1G4PlayerState(name="W1G4-A", hand=[set_pool("PLS")[spell]]),
        _W1G4PlayerState(name="W1G4-B"),
    ])
    w1g4_game.enforce_mana_costs = False
    w1g4_game.active_player_index = 0
    w1g4_boards = []
    for w1g4_seat, w1g4_names in enumerate((mine, theirs)):
        w1g4_board = []
        for w1g4_name in w1g4_names:
            w1g4_perm = _W1G4Permanent(card=w1g4_lea[w1g4_name])
            w1g4_game._put_permanent_onto_battlefield(w1g4_seat, w1g4_perm, None)
            w1g4_board.append(w1g4_perm)
        w1g4_boards.append(w1g4_board)
    return w1g4_game, w1g4_boards[0], w1g4_boards[1]  # _w1g4_instant_table


# -- supported on arrival: driven, not built ----------------------------------


def test_w1g4_gaeas_might_offers_a_creature(set_pool):
    card = set_pool("PLS")["Gaea's Might"]
    program = _w1g4_compile(card)
    assert program.supported, program.reason
    assert _w1g4_cast_spec(card, program) == {"kind": "creature"}


def test_w1g4_gaeas_might_pumps_by_its_casters_domain(set_pool):
    """"Target creature gets +1/+1 until end of turn for each basic land type
    among lands you control." Three lands holding five types make the Bears
    7/7; on an opponent's creature the size is still the caster's two types,
    not the five its controller has."""
    game, mine, _theirs = _w1g4_instant_table(
        set_pool, "Gaea's Might",
        mine=["Grizzly Bears", "Plains", "Tropical Island", "Badlands"],
    )
    bears = mine[0]
    cast = game.cast_from_hand(
        0, "Gaea's Might", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    assert (bears.effective_power, bears.effective_toughness) == (7, 7)
    assert "Gaea's Might gives Grizzly Bears +5/+5 until end of turn" in game.log

    game, _mine, theirs = _w1g4_instant_table(
        set_pool, "Gaea's Might", mine=["Forest", "Island"],
        theirs=["Grizzly Bears", "Plains", "Island", "Swamp", "Mountain", "Forest"],
    )
    assert game.cast_from_hand(
        0, "Gaea's Might", target_player_index=1,
        target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g4_resolve(game)
    assert (theirs[0].effective_power, theirs[0].effective_toughness) == (4, 4)


def test_w1g4_gaeas_might_is_locked_in_and_ends_with_the_turn(set_pool):
    """CR 608.2h: the size is determined once, as the spell resolves. A land lost
    afterwards takes nothing back — the Bears stay 7/7 — and the cleanup step
    ends the whole of it."""
    game, mine, _theirs = _w1g4_instant_table(
        set_pool, "Gaea's Might",
        mine=["Grizzly Bears", "Plains", "Tropical Island", "Badlands"],
    )
    bears, _plains, _tropical, badlands = mine
    assert game.cast_from_hand(
        0, "Gaea's Might", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g4_resolve(game)
    game.sacrifice_permanent(badlands)
    game._recompute_continuous_effects()
    assert (bears.effective_power, bears.effective_toughness) == (7, 7)

    game.resolve_cleanup_step(0)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
