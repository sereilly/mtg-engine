"""Mercadian Masques enchantments, Auras included.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: board-wide statics, cast permissions and control ---

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.cast_timing import casts_at_instant_speed
from engine.combat_restrictions import combat_restriction_for
from engine.damage_events import deal_damage
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack


def _g5_creature(name: str, power: int = 2, toughness: int = 2, colors=()):
    """A vanilla creature with a printed colour, which several of these read."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _g5_board(*battlefields, hands=None):
    """A game with each seat's battlefield (and optionally hand) handed over.

    Started and stepped past the opening priority window, so a trigger this
    block announces has somewhere to go.
    """
    seats = [
        PlayerState(name=f"G5P{index}", battlefield=list(permanents))
        for index, permanents in enumerate(battlefields)
    ]
    for index, hand in enumerate(hands or ()):
        seats[index].hand = list(hand)
    board = Game(players=seats)
    board.enforce_mana_costs = False
    for seat in board.players:
        for permanent in seat.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    board.start_turn(0)
    board._close_current_priority_step()
    return board


# --- Ivory Mask ------------------------------------------------------------
# "You have shroud." CR 702.18a is explicit that a **player** can have it, which
# `engine/game.py` used to assert the opposite of in a comment beside
# `targeting_bans`. Enforced in `legality._enumerate_targets` — the one list the
# picker and both announcement gates read — so the seat is simply not offered.


def test_ivory_mask_takes_its_controller_off_the_target_list(set_pool):
    mask = Permanent(card=set_pool("MMQ")["Ivory Mask"])
    board = _g5_board([mask], [])
    shock = CardDefinition(
        name="G5 Bolt", mana_cost="{R}", cmc=1.0, type_line="Instant",
        oracle_text="G5 Bolt deals 2 damage to any target.",
        colors=("R",), color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": "G5 Bolt", "type_line": "Instant"},
    )
    spec = {"kind": "any"}

    offered = board._enumerate_targets(1, shock, spec, for_cast=True)
    seats = {found["seat"] for found in offered if found["kind"] == "player"}

    assert seats == {1}, "the Mask's controller must not be a legal target"


def test_ivory_mask_leaving_the_battlefield_takes_the_shroud_with_it(set_pool):
    """Derived from the board on every ask (CR 611.3b), so nothing sweeps."""
    from engine.player_statics import seat_has_player_keyword

    mask = Permanent(card=set_pool("MMQ")["Ivory Mask"])
    board = _g5_board([mask], [])
    assert seat_has_player_keyword(board, 0, "shroud")

    board.remove_from_battlefield(mask)

    assert not seat_has_player_keyword(board, 0, "shroud")


def test_ivory_mask_protects_the_seat_that_controls_it_not_its_owner(set_pool):
    """CR 109.5: "you" is the permission's controller, read through the control
    seam — so a stolen Mask protects the thief."""
    from engine.player_statics import seat_has_player_keyword

    mask = Permanent(card=set_pool("MMQ")["Ivory Mask"])
    board = _g5_board([mask], [])
    board.take_control(mask, 1, source=mask)

    assert not seat_has_player_keyword(board, 0, "shroud")
    assert seat_has_player_keyword(board, 1, "shroud")


# --- Magistrate's Veto -----------------------------------------------------
# "White creatures and blue creatures can't block." The printed colour union
# with the head noun spelled twice — one set, and "white or blue creatures" is
# the same narrowing spelled short, which the noun parser has read since
# Abomination. Read as two noun phrases the line refused entirely.


def test_magistrates_veto_reads_the_printed_colour_union(set_pool):
    veto = set_pool("MMQ")["Magistrate's Veto"]
    program = compile_card_oracle(veto)

    assert program.supported
    restriction = combat_restriction_for(
        "white creatures and blue creatures can't block"
    )
    assert restriction is not None
    assert restriction.kind == "creatures_cant_block"
    assert restriction.payload["subject"]["any_colors"] == ["W", "U"]


def test_magistrates_veto_stops_either_colour_blocking(set_pool):
    veto = Permanent(card=set_pool("MMQ")["Magistrate's Veto"])
    attacker = Permanent(card=_g5_creature("G5 Attacker", 3, 3, colors=("R",)))
    white = Permanent(card=_g5_creature("G5 White", 2, 2, colors=("W",)))
    blue = Permanent(card=_g5_creature("G5 Blue", 2, 2, colors=("U",)))
    green = Permanent(card=_g5_creature("G5 Green", 2, 2, colors=("G",)))
    board = _g5_board([veto, attacker], [white, blue, green])

    assert not board._can_block_attacker(white, attacker)
    assert not board._can_block_attacker(blue, attacker)
    # The union is not "every creature": a colour the card did not print still
    # blocks, which is what a dropped narrowing would have taken away.
    assert board._can_block_attacker(green, attacker)


def test_magistrates_veto_reaches_its_own_controllers_creatures(set_pool):
    """The sentence names no controller, so CR 611.3a's set is every creature
    on every battlefield — the enchantment's own side included."""
    veto = Permanent(card=set_pool("MMQ")["Magistrate's Veto"])
    mine = Permanent(card=_g5_creature("G5 Mine", 2, 2, colors=("W",)))
    attacker = Permanent(card=_g5_creature("G5 Theirs", 3, 3, colors=("B",)))
    board = _g5_board([veto, mine], [attacker])

    assert not board._can_block_attacker(mine, attacker)


def test_a_printed_and_union_does_not_fold_two_different_nouns(set_pool):
    """The fold is gated on the same head noun: "white creatures and blue
    enchantments" is two sets and must keep refusing."""
    from engine.grammar.phrases import parse_subject_filter

    assert parse_subject_filter(
        "white creatures and blue enchantments", plural=True
    ) is None
    assert parse_subject_filter(
        "white creatures and blue creatures", plural=True
    ).to_payload() == {"type_filter": "creature", "any_colors": ["W", "U"]}


# --- Common Cause ----------------------------------------------------------
# "Nonartifact creatures get +2/+2 as long as they all share a color." CR 105.2
# makes the question an **intersection**: a board of one white and one blue
# creature shares nothing, which is not what "no two differ" would say. The
# answer is recomputed by the state-based sweep, so a probe that never runs one
# reads a working card as broken.


def test_common_cause_buffs_a_board_that_shares_a_colour(set_pool):
    cause = Permanent(card=set_pool("MMQ")["Common Cause"])
    one = Permanent(card=_g5_creature("G5 W1", 2, 2, colors=("W",)))
    two = Permanent(card=_g5_creature("G5 W2", 1, 1, colors=("W",)))
    board = _g5_board([cause, one], [two])
    board.check_state_based_actions()

    assert (one.effective_power, one.effective_toughness) == (4, 4)
    assert (two.effective_power, two.effective_toughness) == (3, 3)


def test_common_cause_switches_off_when_the_colours_diverge(set_pool):
    cause = Permanent(card=set_pool("MMQ")["Common Cause"])
    white = Permanent(card=_g5_creature("G5 W", 2, 2, colors=("W",)))
    blue = Permanent(card=_g5_creature("G5 U", 2, 2, colors=("U",)))
    board = _g5_board([cause, white], [blue])
    board.check_state_based_actions()

    assert (white.effective_power, white.effective_toughness) == (2, 2)
    assert (blue.effective_power, blue.effective_toughness) == (2, 2)


def test_common_cause_ignores_artifact_creatures_and_is_recomputed(set_pool):
    """The printed "nonartifact" is what keeps a colourless artifact creature —
    which shares a colour with nothing — from switching the anthem off; and
    removing the odd creature turns the buff back on with nothing to undo."""
    cause = Permanent(card=set_pool("MMQ")["Common Cause"])
    white = Permanent(card=_g5_creature("G5 W", 2, 2, colors=("W",)))
    robot = Permanent(card=CardDefinition(
        name="G5 Robot", mana_cost="", cmc=0.0,
        type_line="Artifact Creature - Construct", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "G5 Robot", "type_line": "Artifact Creature - Construct",
             "power": "1", "toughness": "1"},
    ))
    blue = Permanent(card=_g5_creature("G5 U", 2, 2, colors=("U",)))
    board = _g5_board([cause, white, robot], [blue])
    board.check_state_based_actions()
    assert (white.effective_power, white.effective_toughness) == (2, 2)

    board.remove_from_battlefield(blue)
    board.check_state_based_actions()

    assert (white.effective_power, white.effective_toughness) == (4, 4)
    # The artifact creature is outside the set the sentence names, so it is
    # neither counted nor buffed.
    assert (robot.effective_power, robot.effective_toughness) == (1, 1)


# --- Vernal Equinox --------------------------------------------------------
# "Any player may cast creature and enchantment spells as though they had
# flash." Two axes past the Rootwater Shaman row it extends: a printed *union*
# of card types, and a seat word that is every seat rather than the
# permission's own controller.


def test_vernal_equinox_flashes_in_both_printed_classes(set_pool):
    equinox = Permanent(card=set_pool("MMQ")["Vernal Equinox"])
    board = _g5_board([equinox], [])
    creature = _g5_creature("G5 Beast", 3, 3, colors=("G",))
    enchantment = CardDefinition(
        name="G5 Charm", mana_cost="{W}", cmc=1.0, type_line="Enchantment",
        oracle_text="", colors=("W",), color_identity=("W",),
        keywords=(), produced_mana=(),
        raw={"name": "G5 Charm", "type_line": "Enchantment"},
    )
    artifact = CardDefinition(
        name="G5 Rock", mana_cost="{2}", cmc=2.0, type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": "G5 Rock", "type_line": "Artifact"},
    )

    assert casts_at_instant_speed(creature, board, 0)
    assert casts_at_instant_speed(enchantment, board, 0)
    # A class the sentence does not name keeps its own timing, which a union
    # read as "the first word" would have taken away from the second half and
    # a union read as "every spell" would have given away here.
    assert not casts_at_instant_speed(artifact, board, 0)


def test_vernal_equinox_reaches_the_opponent_too(set_pool):
    """"Any player", which is the whole difference from Rootwater Shaman's
    "you" — and a board scan is the only way to see it from the other seat."""
    equinox = Permanent(card=set_pool("MMQ")["Vernal Equinox"])
    board = _g5_board([equinox], [])
    creature = _g5_creature("G5 Beast", 3, 3, colors=("G",))

    assert casts_at_instant_speed(creature, board, 1)


def test_the_you_spelling_of_the_same_static_still_means_its_controller():
    """The scan widened from one battlefield to the whole board, so the seat
    test on the permission is what keeps the narrow printing narrow.

    Tested against an invented card carrying Rootwater Shaman's sentence rather
    than against the Shaman, which is in Tempest: this is a per-set file, and a
    behaviour is checked by giving a card the printed text (`card_hooks.py`'s
    own entry bar read as a testing rule)."""
    narrow = Permanent(card=CardDefinition(
        name="G5 Narrow Timing", mana_cost="{G}", cmc=1.0,
        type_line="Enchantment",
        oracle_text="You may cast creature spells as though they had flash.",
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "G5 Narrow Timing", "type_line": "Enchantment"},
    ))
    board = _g5_board([narrow], [])
    creature = _g5_creature("G5 Beast", 3, 3, colors=("G",))

    assert casts_at_instant_speed(creature, board, 0)
    assert not casts_at_instant_speed(creature, board, 1)


# --- Liability -------------------------------------------------------------
# "Whenever a nontoken permanent is put into **a player's** graveyard from the
# battlefield, that player loses 1 life." The possessive is the unnarrowed
# reading with the owner said out loud (CR 404.1 already sends a permanent to
# its owner's pile), and it was the one spelling neither front end could read.


def test_liability_drains_for_a_nontoken_permanent_that_dies(set_pool):
    liability = Permanent(card=set_pool("MMQ")["Liability"])
    victim = Permanent(card=_g5_creature("G5 Victim", 1, 1))
    board = _g5_board([liability], [victim])
    board.players[1].life = 20

    board._permanent_to_graveyard(board.players[1], victim)
    resolve_stack(board)

    assert board.players[1].life == 19
    assert board.players[0].life == 20


def test_liability_ignores_a_token(set_pool):
    """The printed "nontoken" is a real narrowing, and a token that ceases to
    exist (CR 704.5d) is exactly the case it excludes."""
    liability = Permanent(card=set_pool("MMQ")["Liability"])
    token = Permanent(card=_g5_creature("G5 Token", 1, 1))
    token.metadata["is_token"] = True
    board = _g5_board([liability], [token])
    board.players[1].life = 20

    board._permanent_to_graveyard(board.players[1], token)
    resolve_stack(board)

    assert board.players[1].life == 20


def test_liability_fires_for_its_own_controllers_permanents_too(set_pool):
    """The sentence names no seat, so every graveyard counts — reading "a
    player's" as a narrowing would have made this one-sided."""
    liability = Permanent(card=set_pool("MMQ")["Liability"])
    mine = Permanent(card=_g5_creature("G5 Mine", 1, 1))
    board = _g5_board([liability, mine], [])
    board.players[0].life = 20

    board._permanent_to_graveyard(board.players[0], mine)
    resolve_stack(board)

    assert board.players[0].life == 19


# --- Putrefaction and Snake Pit --------------------------------------------
# One production for two cards: a cast trigger narrowed by a **union** of
# colours (CR 105.2b — an object is each of its colours, so any listed one
# answers). The single-colour narrowing has been read since the Rod/Cup/Sphere
# cycle; the union was the missing half, and it was read for "you cast" alone.


def _g5_coloured_spell(name: str, colors) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=1.0, type_line="Sorcery",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Sorcery"},
    )


def test_putrefaction_fires_on_either_printed_colour(set_pool):
    rot = Permanent(card=set_pool("MMQ")["Putrefaction"])
    spell = _g5_coloured_spell("G5 Green Spell", ("G",))
    junk = _g5_creature("G5 Junk", 1, 1)
    board = _g5_board([rot], [], hands=[(), (spell, junk)])

    board.cast_from_hand(1, "G5 Green Spell")
    resolve_stack(board)
    # The trigger arms the caster's own discard prompt and holds nothing else
    # up; answering it is what a seat does (CR 608.2).
    assert [choice.kind for choice in board.pending_choices] == ["discard"]
    board.auto_resolve_pending_choices()

    assert board.players[1].hand == [], "the caster discarded their card"


def test_putrefaction_ignores_a_colour_it_did_not_print(set_pool):
    rot = Permanent(card=set_pool("MMQ")["Putrefaction"])
    spell = _g5_coloured_spell("G5 Red Spell", ("R",))
    junk = _g5_creature("G5 Junk", 1, 1)
    board = _g5_board([rot], [], hands=[(), (spell, junk)])

    board.cast_from_hand(1, "G5 Red Spell")
    resolve_stack(board)
    board.auto_resolve_pending_choices()

    assert [card.name for card in board.players[1].hand] == ["G5 Junk"]


def test_snake_pit_reads_the_union_on_the_opponent_scoped_kind(set_pool):
    """The same narrowing on the other cast kind — a union tested for "you
    cast" alone is a union the two board-wide kinds silently ignore."""
    pit = Permanent(card=set_pool("MMQ")["Snake Pit"])
    spell = _g5_coloured_spell("G5 Black Spell", ("B",))
    board = _g5_board([pit], [], hands=[(), (spell,)])

    board.cast_from_hand(1, "G5 Black Spell")
    resolve_stack(board)
    # "**You may** create" — the offer is a prompt the trigger's controller owes.
    assert [choice.kind for choice in board.pending_choices] == ["optional_pay"]
    board.auto_resolve_pending_choices()

    snakes = [
        perm for perm in board.controlled_by(0)
        if perm.card.name == "Snake Token"
    ]
    assert len(snakes) == 1


def test_snake_pit_is_silent_for_its_own_controllers_spell(set_pool):
    """"An opponent casts" — the seat word, still enforced under the union."""
    pit = Permanent(card=set_pool("MMQ")["Snake Pit"])
    spell = _g5_coloured_spell("G5 Blue Spell", ("U",))
    board = _g5_board([pit], [], hands=[(spell,), ()])

    board.cast_from_hand(0, "G5 Blue Spell")
    resolve_stack(board)
    board.auto_resolve_pending_choices()

    assert not [
        perm for perm in board.controlled_by(0)
        if perm.card.name == "Snake Token"
    ]


# --- Cowardice -------------------------------------------------------------
# "Whenever a creature becomes the target of a spell or ability, return that
# creature to its owner's hand." The **fourth dispatch scope** for CR 603.2's
# event: an observer that is neither the targeted object, nor attached to it,
# nor its controller. The announcement seam already fired for every targeted
# permanent; what was missing was a scope that could watch the whole board and
# an id for "that creature" to name.


def _g5_zap() -> CardDefinition:
    return CardDefinition(
        name="G5 Zap", mana_cost="{R}", cmc=1.0, type_line="Instant",
        oracle_text="G5 Zap deals 2 damage to target creature.",
        colors=("R",), color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": "G5 Zap", "type_line": "Instant"},
    )


def test_cowardice_bounces_a_creature_a_spell_targeted(set_pool):
    cowardice = Permanent(card=set_pool("MMQ")["Cowardice"])
    victim = Permanent(card=_g5_creature("G5 Victim", 2, 2))
    board = _g5_board([cowardice], [victim], hands=[(_g5_zap(),), ()])

    board.cast_from_hand(0, "G5 Zap", target_permanent_ids=[victim.permanent_id])
    resolve_stack(board)

    assert victim not in board.players[1].battlefield
    assert [card.name for card in board.players[1].hand] == ["G5 Victim"]


def test_cowardice_watches_its_own_controllers_creatures_too(set_pool):
    """The printed noun names no seat, so the set is every creature on every
    battlefield — the enchantment's own side included."""
    cowardice = Permanent(card=set_pool("MMQ")["Cowardice"])
    mine = Permanent(card=_g5_creature("G5 Mine", 2, 2))
    board = _g5_board([cowardice, mine], [], hands=[(), (_g5_zap(),)])

    board.cast_from_hand(1, "G5 Zap", target_permanent_ids=[mine.permanent_id])
    resolve_stack(board)

    assert [card.name for card in board.players[0].hand] == ["G5 Mine"]


def test_cowardice_also_watches_an_ability_and_beats_it_there(set_pool):
    """"a spell **or ability**" — CR 603.2's event is announced for an
    activated ability's targets by the same seam, and the trigger resolves
    first, so the reminder text ("It won't be affected by the spell or
    ability") falls out of CR 608.2b rather than needing a rule of its own."""
    cowardice = Permanent(card=set_pool("MMQ")["Cowardice"])
    pinger = Permanent(card=CardDefinition(
        name="G5 Pinger", mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="{T}: G5 Pinger deals 1 damage to target creature.",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "G5 Pinger", "type_line": "Creature - Test",
             "power": "1", "toughness": "1"},
    ))
    victim = Permanent(card=_g5_creature("G5 Victim", 2, 2))
    board = _g5_board([cowardice, pinger], [victim])

    board.activate_permanent_ability(
        0, "G5 Pinger", target_permanent_ids=[victim.permanent_id]
    )
    resolve_stack(board)

    assert [card.name for card in board.players[1].hand] == ["G5 Victim"]
    assert victim.damage_marked == 0, "the ability found nothing (CR 608.2b)"


def test_cowardice_is_silent_for_a_noncreature_target(set_pool):
    """"A creature" is a narrowing the fourth scope has to test: dropped, the
    enchantment would bounce every targeted permanent there is."""
    cowardice = Permanent(card=set_pool("MMQ")["Cowardice"])
    rock = Permanent(card=CardDefinition(
        name="G5 Rock", mana_cost="{2}", cmc=2.0, type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": "G5 Rock", "type_line": "Artifact"},
    ))
    smash = CardDefinition(
        name="G5 Smash", mana_cost="{R}", cmc=1.0, type_line="Instant",
        oracle_text="Destroy target artifact.", colors=("R",),
        color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": "G5 Smash", "type_line": "Instant"},
    )
    board = _g5_board([cowardice], [rock], hands=[(smash,), ()])

    board.cast_from_hand(0, "G5 Smash", target_permanent_ids=[rock.permanent_id])
    resolve_stack(board)

    assert board.players[1].hand == []


def test_the_narrower_becomes_target_scopes_still_watch_themselves(set_pool):
    """The board-wide row is last in the condition table, so "this creature"
    and "enchanted creature" keep their identity tests — a subject-led row
    placed first would have answered all three through a filter."""
    from engine.oracle import _parse_trigger_condition

    narrow, _ = _parse_trigger_condition(
        "whenever this creature becomes the target of a spell or ability"
    )
    wide, _ = _parse_trigger_condition(
        "whenever a creature becomes the target of a spell or ability"
    )

    assert "targeted_filter" not in narrow.payload
    assert wide.payload["targeted_filter"] == {"type_filter": "creature"}


# --- Spiritual Focus -------------------------------------------------------
# "Whenever a spell or ability an opponent controls causes you to discard a
# card, you gain 2 life and you may draw a card." The **second dispatch scope**
# for the condition Psychic Purge prints: that one is the discarded card's own
# ability watching from the hand (CR 113.6), and this is a permanent on the
# battlefield watching its controller's discards.


def _g5_mind_rot() -> CardDefinition:
    return CardDefinition(
        name="G5 Mind Rot", mana_cost="{2}{B}", cmc=3.0, type_line="Sorcery",
        oracle_text="Target player discards a card.", colors=("B",),
        color_identity=("B",), keywords=(), produced_mana=(),
        raw={"name": "G5 Mind Rot", "type_line": "Sorcery"},
    )


def test_spiritual_focus_pays_off_a_forced_discard(set_pool):
    focus = Permanent(card=set_pool("MMQ")["Spiritual Focus"])
    junk = _g5_creature("G5 Junk", 1, 1)
    board = _g5_board([focus], [], hands=[(junk,), (_g5_mind_rot(),)])
    board.players[0].life = 20
    board.players[0].library = [_g5_creature("G5 Top", 1, 1)]

    board.cast_from_hand(1, "G5 Mind Rot", target_player_index=0)
    resolve_stack(board)
    board.auto_resolve_pending_choices()
    resolve_stack(board)
    board.auto_resolve_pending_choices()

    assert board.players[0].life == 22


def test_spiritual_focus_is_silent_for_a_discard_nobody_caused(set_pool):
    """CR 109.5's other half: an empty stack means the discard was a cost or a
    cleanup, and the printed "a spell or ability an opponent controls" is
    exactly what that is not."""
    focus = Permanent(card=set_pool("MMQ")["Spiritual Focus"])
    junk = _g5_creature("G5 Junk", 1, 1)
    board = _g5_board([focus], [], hands=[(junk,), ()])
    board.players[0].life = 20

    board._discard_card(board.players[0], junk)
    resolve_stack(board)
    board.auto_resolve_pending_choices()

    assert board.players[0].life == 20


# --- Charisma --------------------------------------------------------------
# "Whenever enchanted creature deals damage to a creature, gain control of **the
# other creature** for as long as this Aura remains on the battlefield." A
# damage event has two objects and the condition named one of them, so "the
# other" is the one that took it — the id `damage_events._announce` stamps onto
# the stack item. The duration is CR 613 layer 2's monitored contribution, so
# the Aura leaving ends it with nothing remembered.


def test_charisma_steals_the_creature_its_host_damaged(set_pool):
    from engine.handlers._common import apply_damage_to_creature

    charisma = Permanent(card=set_pool("MMQ")["Charisma"])
    host = Permanent(card=_g5_creature("G5 Host", 3, 3))
    prey = Permanent(card=_g5_creature("G5 Prey", 4, 4))
    board = _g5_board([host, charisma], [prey])
    attach_aura(charisma, host)

    apply_damage_to_creature(board, prey, 1, host)
    resolve_stack(board)

    assert board.controller_index_of(prey) == 0


def test_charisma_leaving_gives_the_creature_back(set_pool):
    """CR 611.2b's monitored duration: the contribution ends the moment the
    Aura is gone, and `base_controller_index` is what it reverts to."""
    from engine.handlers._common import apply_damage_to_creature

    charisma = Permanent(card=set_pool("MMQ")["Charisma"])
    host = Permanent(card=_g5_creature("G5 Host", 3, 3))
    prey = Permanent(card=_g5_creature("G5 Prey", 4, 4))
    board = _g5_board([host, charisma], [prey])
    attach_aura(charisma, host)
    apply_damage_to_creature(board, prey, 1, host)
    resolve_stack(board)
    assert board.controller_index_of(prey) == 0

    board.remove_from_battlefield(charisma)
    board.check_state_based_actions()

    assert board.controller_index_of(prey) == 1


def test_charisma_takes_the_damaged_creature_and_not_its_own_host(set_pool):
    """The two ends of one damage event are two different objects, and reading
    one for the other would have the Aura steal the creature it is on."""
    from engine.handlers._common import apply_damage_to_creature

    charisma = Permanent(card=set_pool("MMQ")["Charisma"])
    host = Permanent(card=_g5_creature("G5 Host", 3, 3))
    prey = Permanent(card=_g5_creature("G5 Prey", 4, 4))
    board = _g5_board([host, charisma], [prey])
    attach_aura(charisma, host)

    apply_damage_to_creature(board, prey, 1, host)
    resolve_stack(board)

    assert board.controller_index_of(host) == 0
    assert board.controller_index_of(prey) == 0


def test_charisma_is_silent_when_its_host_damages_a_player(set_pool):
    """"…to **a creature**" is the printed narrowing; a damage event whose
    recipient is a seat stamps no permanent, and the steal must find nothing
    rather than take whatever the resolution was holding."""
    from engine.damage_events import deal_damage

    charisma = Permanent(card=set_pool("MMQ")["Charisma"])
    host = Permanent(card=_g5_creature("G5 Host", 3, 3))
    prey = Permanent(card=_g5_creature("G5 Prey", 4, 4))
    board = _g5_board([host, charisma], [prey])
    attach_aura(charisma, host)

    deal_damage(board, {
        "recipient": board.players[1], "amount": 3, "source": host,
        "combat": False,
    })
    resolve_stack(board)

    assert board.controller_index_of(prey) == 1


# --- Uphill Battle ---------------------------------------------------------
# "Creatures **played by your opponents** enter tapped." The printed word is
# "played", and CR's glossary makes that "cast that card as a spell" — so a
# creature an opponent reanimated was never played and this does not tap it.
# Read as "your opponents control", the static would bind a strictly larger set
# than the card prints, silently and in its controller's favour.


def test_uphill_battle_taps_a_creature_an_opponent_cast(set_pool):
    battle = Permanent(card=set_pool("MMQ")["Uphill Battle"])
    beast = _g5_creature("G5 Beast", 3, 3)
    board = _g5_board([battle], [], hands=[(), (beast,)])

    board.cast_from_hand(1, "G5 Beast")
    resolve_stack(board)

    entered = [
        perm for perm in board.controlled_by(1) if perm.card.name == "G5 Beast"
    ]
    assert len(entered) == 1
    assert entered[0].tapped


def test_uphill_battle_leaves_its_own_controllers_casts_alone(set_pool):
    battle = Permanent(card=set_pool("MMQ")["Uphill Battle"])
    beast = _g5_creature("G5 Beast", 3, 3)
    board = _g5_board([battle], [], hands=[(beast,), ()])

    board.cast_from_hand(0, "G5 Beast")
    resolve_stack(board)

    entered = [p for p in board.controlled_by(0) if p.card.name == "G5 Beast"][0]
    assert not entered.tapped


def test_uphill_battle_does_not_tap_a_creature_nobody_played(set_pool):
    """CR 701.5a's ``was_cast``: a permanent an effect put onto the battlefield
    carries no cast stamp, and "played" is exactly what it was not."""
    battle = Permanent(card=set_pool("MMQ")["Uphill Battle"])
    board = _g5_board([battle], [])
    reanimated = Permanent(card=_g5_creature("G5 Revenant", 3, 3))

    board._put_permanent_onto_battlefield(1, reanimated, None)

    assert not reanimated.tapped


# --- Cornered Market -------------------------------------------------------
# "Players can't cast spells with the same name as a nontoken permanent." plus
# "Players can't play nonbasic lands with the same name as a nontoken
# permanent." Null Chamber's name-keyed ban with the names read off the board
# instead of chosen — so what it forbids changes with every resolution, and it
# is asked at the announcement rather than recorded anywhere.


def _g5_named(name: str, type_line: str = "Creature - Test") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=1.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": "1", "toughness": "1"},
    )


def test_cornered_market_stops_a_second_copy_of_a_permanent(set_pool):
    market = Permanent(card=set_pool("MMQ")["Cornered Market"])
    on_board = Permanent(card=_g5_named("G5 Twin"))
    board = _g5_board([market, on_board], [], hands=[(), (_g5_named("G5 Twin"),)])

    result = board.cast_from_hand(1, "G5 Twin")

    assert not result.supported
    assert "Cornered Market" in result.details
    assert len(board.players[1].hand) == 1


def test_cornered_market_lets_an_unmatched_name_through(set_pool):
    market = Permanent(card=set_pool("MMQ")["Cornered Market"])
    on_board = Permanent(card=_g5_named("G5 Twin"))
    board = _g5_board([market, on_board], [], hands=[(), (_g5_named("G5 Other"),)])

    result = board.cast_from_hand(1, "G5 Other")

    assert result.supported


def test_cornered_market_binds_its_own_controller_too(set_pool):
    """The sentence names nobody, so it binds everybody (CR 601.3a) — the
    enchantment's own controller included."""
    market = Permanent(card=set_pool("MMQ")["Cornered Market"])
    on_board = Permanent(card=_g5_named("G5 Twin"))
    board = _g5_board([market, on_board], [], hands=[(_g5_named("G5 Twin"),), ()])

    assert not board.cast_from_hand(0, "G5 Twin").supported


def test_cornered_market_ignores_a_token_with_the_same_name(set_pool):
    """"**Nontoken**" is CR 111.1's word and a real narrowing: a token copy
    would otherwise lock its own name out of every hand at the table."""
    market = Permanent(card=set_pool("MMQ")["Cornered Market"])
    token = Permanent(card=_g5_named("G5 Twin"))
    token.metadata["is_token"] = True
    board = _g5_board([market, token], [], hands=[(), (_g5_named("G5 Twin"),)])

    assert board.cast_from_hand(1, "G5 Twin").supported


def test_cornered_market_exempts_a_basic_land(set_pool):
    """The land line says "**nonbasic**", and the spell line has no such word —
    so which half applies has to follow the card being played. Read the other
    way round, a Forest stops being playable the moment anybody resolves one."""
    market = Permanent(card=set_pool("MMQ")["Cornered Market"])
    forest_on_board = Permanent(card=_g5_named("Forest", "Basic Land - Forest"))
    board = _g5_board(
        [market, forest_on_board], [],
        hands=[(), (_g5_named("Forest", "Basic Land - Forest"),)],
    )

    assert board.cast_from_hand(1, "Forest").supported


def test_cornered_market_stops_a_second_nonbasic_land(set_pool):
    market = Permanent(card=set_pool("MMQ")["Cornered Market"])
    on_board = Permanent(card=_g5_named("G5 Tower", "Land"))
    board = _g5_board(
        [market, on_board], [], hands=[(), (_g5_named("G5 Tower", "Land"),)]
    )

    result = board.cast_from_hand(1, "G5 Tower")

    assert not result.supported
    assert "Cornered Market" in result.details


def test_cornered_market_claims_both_of_its_printed_lines(set_pool):
    """Each line is claimed on its own: admitting the card on the casting half
    alone would ship an enchantment that stops a spell and lets the land it
    shares a name with through."""
    from engine.cast_restrictions import same_name_as_permanent_ban_line

    market = set_pool("MMQ")["Cornered Market"]
    halves = [
        same_name_as_permanent_ban_line(line)
        for line in market.oracle_text.splitlines()
    ]

    assert halves == ["cast spells", "play nonbasic lands"]
    assert compile_card_oracle(market).supported
