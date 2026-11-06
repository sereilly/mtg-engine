"""The template behind Scourge's mana-value cards, on invented cards — the
point is the sentence, not the six that print it.

* "**the greatest <power | mana value> among** <noun phrase>" is one reader
  for the two front ends that print a maximum (``where_x.accept_greatest_among``:
  the ", where X is …" trailer and "equal to …"), spent through one floor
  reader (``_amounts.maximum_amount_spec``) by a damage, a draw, a life gain, a
  discard and a comparison's bound. Carrion Grub's "greatest power among" was
  readable behind a where-clause alone until this.
* A cast trigger "**with mana value N or greater | less**" is condition payload
  (``cast_mana_value``, ``cast_event_filters._cast_narrowing_admits``) on the
  two scopes the pool prints it on, and the grammar reads exactly those: a
  line the table does not carry refuses.
* Final Punishment's "the damage already dealt **to that player** this turn"
  is the ledger joined on the seat the sentence targeted, and nothing else.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.grammar.errors import GrammarError
from engine.grammar.parser import parse_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack


def _table(set_pool, hand, *mine, theirs=()):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="A", hand=list(hand), library=[lea["Island"]] * 10),
        PlayerState(name="B", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=lea[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    resolve_stack(game)
    return game


def _sorcery(text):
    card = _mk_card("W1G4 Probe", "{1}", "Sorcery", text)
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    return card


def test_a_maximum_power_behind_equal_to_draws_that_many(set_pool):
    """The where-clause's "greatest power among" read behind "equal to": the
    Shivan Dragon's 5 power is the caster's greatest; the opponent's Lord of
    the Pit's 7 is not "you control"."""
    card = _sorcery("Draw cards equal to the greatest power among creatures you control.")
    game = _table(set_pool, [card], "Grizzly Bears", "Shivan Dragon", theirs=("Lord of the Pit",))
    assert game.cast_from_hand(0, "W1G4 Probe").supported
    resolve_stack(game)
    assert len(game.players[0].hand) == 5, game.log


def test_the_maximums_noun_phrase_narrows_it(set_pool):
    """"…among **artifacts** you control": the Shivan Dragon (6) is no
    artifact, the Jayemdae Tome (4) is."""
    card = _sorcery("You gain life equal to the greatest mana value among artifacts you control.")
    game = _table(set_pool, [card], "Shivan Dragon", "Jayemdae Tome", "Sol Ring")
    assert game.cast_from_hand(0, "W1G4 Probe").supported
    resolve_stack(game)
    assert game.players[0].life == 24, game.log


def test_a_maximum_over_nothing_is_zero(set_pool):
    card = _sorcery("You gain life equal to the greatest mana value among artifacts you control.")
    game = _table(set_pool, [card], "Shivan Dragon")
    assert game.cast_from_hand(0, "W1G4 Probe").supported
    resolve_stack(game)
    assert game.players[0].life == 20, game.log


@pytest.mark.parametrize("line", [
    # A factor over a maximum is arithmetic no spender here was taught; the
    # line refuses rather than dealing the unscaled number.
    "W1G4 Probe deals damage to any target equal to twice the greatest mana value among permanents you control.",
    # A maximum over a phrase the parser cannot read is no maximum at all.
    "Draw cards equal to the greatest mana value among frobnitzes you control.",
])
def test_a_maximum_the_spender_cannot_honour_refuses(line):
    card = _mk_card("W1G4 Probe", "{1}", "Sorcery", line)
    assert not compile_card_oracle(card).supported


def _watcher_fires_on(set_pool, text, spells):
    """Which of *spells* (LEA names, cast by seat 0) fire an enchantment
    printing *text* — each firing gains its controller 1 life."""
    watcher = _mk_card("Cast Watcher", "{1}", "Enchantment", text)
    program = compile_card_oracle(watcher)
    assert program.supported, program.reason
    fired = set()
    for name in spells:
        card = set_pool("LEA")[name]
        game = _table(set_pool, [card])
        game._put_permanent_onto_battlefield(0, Permanent(card=watcher), None)
        announced = {} if "Creature" in card.type_line else {"target_player_index": 1}
        assert game.queue_from_hand(0, name, **announced).supported
        resolve_stack(game)
        if game.players[0].life == 21:
            fired.add(name)
    return fired


def test_a_you_cast_trigger_by_mana_value_reads_both_directions(set_pool):
    spells = ("Grizzly Bears", "Hill Giant", "Lightning Bolt", "Shivan Dragon")
    assert _watcher_fires_on(
        set_pool,
        "Whenever you cast a creature spell with mana value 4 or greater, you gain 1 life.",
        spells,
    ) == {"Hill Giant", "Shivan Dragon"}
    assert _watcher_fires_on(
        set_pool,
        "Whenever you cast a creature spell with mana value 2 or less, you gain 1 life.",
        spells,
    ) == {"Grizzly Bears"}


def test_the_bound_is_condition_payload_on_both_scopes():
    def condition(text):
        card = _mk_card("Cast Watcher", "{1}", "Enchantment", text)
        (trigger,) = compile_card_oracle(card).triggered_abilities
        return trigger.condition.kind, trigger.condition.payload

    assert condition(
        "Whenever a player casts a spell with mana value 3 or less, you gain 1 life."
    ) == ("spell_cast", {"cast_mana_value": "3", "cast_mana_value_bound": "less"})
    assert condition(
        "Whenever you cast a sorcery spell with mana value 6 or greater, you gain 1 life."
    ) == ("you_cast_spell", {
        "cast_type": "sorcery", "cast_mana_value": "6", "cast_mana_value_bound": "greater",
    })


@pytest.mark.parametrize("line", [
    # Scopes the table carries no bound on: an untested narrowing goes in with
    # the card that prints it.
    "Whenever an opponent casts a spell with mana value 3 or less, you gain 1 life.",
    "Whenever you cast a spell with mana value 3 or less, you gain 1 life.",
    # A bound the table cannot write: an X, an exact value.
    "Whenever a player casts a spell with mana value X or less, you gain 1 life.",
    "Whenever you cast a creature spell with mana value 3, you gain 1 life.",
])
def test_a_mana_value_bound_the_table_does_not_carry_refuses_the_line(line):
    """The condition comes from the table and the grammar only has to read the
    whole line — so a line the grammar read that the table reads differently
    would be a trigger watching a set the card does not print."""
    with pytest.raises(GrammarError):
        parse_line(line)


@pytest.mark.parametrize("line", [
    # "That player" with no targeted player in front of it names nobody.
    "You lose life equal to the damage already dealt to that player this turn.",
    "Each opponent loses life equal to the damage already dealt to that player this turn.",
])
def test_the_damage_dealt_to_that_player_names_the_targeted_player_only(line):
    card = _mk_card("W1G4 Probe", "{1}", "Sorcery", line)
    assert not compile_card_oracle(card).supported


@pytest.mark.parametrize("line", [
    # A deed the seat loop's body is not known to read its seat for.
    "Any number of target players each sacrifice a creature.",
    # "Any number of target creatures each …" is not a seat loop at all.
    "Any number of target creatures each gain life equal to 2.",
])
def test_any_number_of_target_players_each_admits_only_seat_deeds(line):
    card = _mk_card("W1G4 Probe", "{1}", "Sorcery", line)
    assert not compile_card_oracle(card).supported
