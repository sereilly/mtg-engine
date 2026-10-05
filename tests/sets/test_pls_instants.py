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
