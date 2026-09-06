"""Tempest creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G2: what the turn remembers about spells cast (CR 601.3, 506.1, 113.6g) ---
import pytest

from engine import Game, PlayerState
from engine.cast_restrictions import (cast_own_cast_line, cast_spell_filter,
                                      cast_timing_claims_line,
                                      spells_cast_matching)
from engine.combat_restrictions import combat_restriction_for
from engine.counter_conditions import spell_cant_be_countered
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w1g2_board(set_pool, card_name):
    """*card_name* on the battlefield, unsick, with an opponent to attack."""
    a = PlayerState(name="A")
    game = Game(players=[a, PlayerState(name="B")])
    game.enforce_mana_costs = False
    perm = Permanent(card=set_pool("TMP")[card_name])
    perm.metadata["summoning_sickness_turn"] = -99
    a.battlefield.append(perm)
    game._settle()
    return game, a, perm


# --- Skyshroud Condor: CR 601.3 over the turn's cast record ---

def test_w1g2_skyshroud_condor_is_supported_by_the_timing_table(set_pool):
    """The gap was the **creature** gate, not the table: Skyshroud Condor is the
    first creature in the pool to print a "Cast this spell only …" clause, and a
    creature is refused for any line nothing reads."""
    program = compile_card_oracle(set_pool("TMP")["Skyshroud Condor"])
    assert program.supported, program.reason
    assert cast_timing_claims_line(
        "cast this spell only if you've cast another spell this turn"
    )


def test_w1g2_skyshroud_condor_needs_a_prior_spell(set_pool, catalog_by_name):
    caster = PlayerState(name="A", hand=[set_pool("TMP")["Skyshroud Condor"]])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = False
    game._settle()

    refused = game.cast_from_hand(0, "Skyshroud Condor")
    game._settle()
    assert not refused.supported
    assert "cast another spell this turn" in refused.details
    assert [c.name for c in caster.hand] == ["Skyshroud Condor"]

    caster.spells_cast_this_turn.append(catalog_by_name["Lightning Bolt"])
    allowed = game.cast_from_hand(0, "Skyshroud Condor")
    game._settle()
    assert allowed.supported, allowed.details
    assert [p.card.name for p in caster.battlefield] == ["Skyshroud Condor"]


def test_w1g2_another_spell_is_honoured_by_the_record_not_by_a_narrowing(set_pool):
    """"Another" means "other than this one", and CR 601.3 asks the gate while
    the spell is being announced — before `casting` appends it to the record. So
    a non-empty record *is* "another spell", and the reader is right to return
    an unnarrowed filter rather than inventing one."""
    assert cast_own_cast_line(
        "cast this spell only if you've cast another spell this turn"
    ) == ({}, "another spell")
    assert cast_spell_filter("another spell") == {}
    assert cast_spell_filter("a creature spell") == {"type_filter": "creature"}
    assert cast_spell_filter("no spell") is None, (
        "a negation is a different condition, not presence"
    )


def test_w1g2_the_cast_record_is_read_per_seat(set_pool, catalog_by_name):
    """An opponent's casts are not yours."""
    caster = PlayerState(name="A", hand=[set_pool("TMP")["Skyshroud Condor"]])
    other = PlayerState(name="B")
    game = Game(players=[caster, other])
    game.enforce_mana_costs = False
    other.spells_cast_this_turn.append(catalog_by_name["Lightning Bolt"])
    game._settle()

    assert not spells_cast_matching(game, 0, {})
    assert spells_cast_matching(game, 1, {})
    assert not game.cast_from_hand(0, "Skyshroud Condor").supported


# --- Mogg Conscripts: CR 506.1 over the same record ---

def test_w1g2_mogg_conscripts_reads_the_same_phrase_as_the_casting_gate(set_pool):
    """One reader for two tables: a *spell* is not a permanent (CR 613.1), and
    the two restrictions must not disagree about what "a creature spell" is."""
    program = compile_card_oracle(set_pool("TMP")["Mogg Conscripts"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["cant_attack_unless_you_cast"]
    read = combat_restriction_for(
        "this creature can't attack unless you've cast a creature spell this turn"
    )
    assert read is not None
    assert read.payload == {"spell_filter": cast_spell_filter("a creature spell")}


def test_w1g2_mogg_conscripts_cannot_attack_before_a_creature_spell(
    set_pool, catalog_by_name
):
    game, a, mogg = _w1g2_board(set_pool, "Mogg Conscripts")
    assert not game.can_attack(mogg, 1)

    a.spells_cast_this_turn.append(catalog_by_name["Lightning Bolt"])
    assert not game.can_attack(mogg, 1), "an instant is not a creature spell"

    a.spells_cast_this_turn.append(catalog_by_name["Grizzly Bears"])
    assert game.can_attack(mogg, 1)


def test_w1g2_mogg_conscripts_reads_its_controllers_record(set_pool, catalog_by_name):
    """"You" on a creature's own text is whoever controls it (CR 109.5), so a
    creature stolen this turn is held to its new controller's casts."""
    game, a, mogg = _w1g2_board(set_pool, "Mogg Conscripts")
    game.players[1].spells_cast_this_turn.append(catalog_by_name["Grizzly Bears"])
    assert not game.can_attack(mogg, 1)


# --- Scragnoth: CR 113.6g ---

def test_w1g2_scragnoth_is_supported_by_the_counter_path(set_pool):
    program = compile_card_oracle(set_pool("TMP")["Scragnoth"])
    assert program.supported, program.reason
    assert spell_cant_be_countered(set_pool("TMP")["Scragnoth"])
    assert not spell_cant_be_countered(set_pool("TMP")["Capsize"])


def test_w1g2_counterspell_does_not_counter_scragnoth(set_pool, catalog_by_name):
    """CR 113.6g. It is still a legal *target* — Counterspell prints "target
    spell", not "target spell that can be countered" — so the counter resolves
    and does nothing rather than being refused at announcement."""
    a = PlayerState(name="A", hand=[set_pool("TMP")["Scragnoth"]])
    b = PlayerState(name="B", hand=[catalog_by_name["Counterspell"]])
    game = Game(players=[a, b])

    game.queue_from_hand(0, "Scragnoth")
    game.queue_from_hand(1, "Counterspell", target_player_index=0)
    game.resolve_stack()

    assert [p.card.name for p in a.battlefield] == ["Scragnoth"]
    assert a.graveyard == []
    assert [c.name for c in b.graveyard] == ["Counterspell"]
    assert any("can't be countered" in line for line in game.log)


def test_w1g2_power_sink_arms_no_prompt_against_scragnoth(set_pool, catalog_by_name):
    """The immunity is asked **before** the "unless its controller pays" prompt:
    asking a player to pay to prevent something that could never happen is worse
    than not asking, because they would pay."""
    a = PlayerState(name="A", hand=[set_pool("TMP")["Scragnoth"]])
    b = PlayerState(name="B", hand=[catalog_by_name["Power Sink"]])
    game = Game(players=[a, b])

    game.queue_from_hand(0, "Scragnoth")
    game.queue_from_hand(1, "Power Sink", target_player_index=0, x_value=3)
    game.resolve_stack()

    assert game.pending_choices == []
    assert [p.card.name for p in a.battlefield] == ["Scragnoth"]


def test_w1g2_an_ordinary_creature_spell_is_still_countered(catalog_by_name):
    """The control: the immunity is read off the card, so it reaches exactly the
    card that prints it."""
    a = PlayerState(name="A", hand=[catalog_by_name["Grizzly Bears"]])
    b = PlayerState(name="B", hand=[catalog_by_name["Counterspell"]])
    game = Game(players=[a, b])

    game.queue_from_hand(0, "Grizzly Bears")
    game.queue_from_hand(1, "Counterspell", target_player_index=0)
    game.resolve_stack()

    assert a.battlefield == []
    assert [c.name for c in a.graveyard] == ["Grizzly Bears"]
