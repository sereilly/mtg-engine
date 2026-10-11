"""The productions and lowerings Apocalypse's kicker-and-counted-damage cards
needed, each with the sentence it reads and the near-misses it must refuse.

A production consumes every token of its line or raises, and a lowering that
cannot honour part of a clause refuses naming what is missing — so each reading
below is paired with the sentences one word away from it that no card prints.
The per-card behaviour (what a game shows) is in ``tests/sets/test_apc_*.py``;
this file is about what compiles and what must not.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar import compile_line
from engine.oracle import compile_card_oracle
from engine.oracle_types import X_FROM_COUNT

_POOL: dict = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)


def _lowered(line: str, card_name: str | None = None):
    result = compile_line(line, card_name=card_name)
    assert result.lowered, f"{line!r}: {result.failure_reason}"
    return result.instructions


def _refused(line: str, card_name: str | None = None) -> str:
    result = compile_line(line, card_name=card_name)
    assert not result.lowered, f"{line!r} lowered to {result.instructions}"
    return result.failure_reason or ""


def _steps(instructions):
    """The top-level steps of a lowered line, through one ``sequence``."""
    (only,) = instructions if len(instructions) == 1 else (None,)
    if only is not None and only.kind == "sequence":
        return list(only.payload["steps"])
    return list(instructions)


# --- "…get an additional +N/+N" on a narrower set (Strength of Night) --------

_STRENGTH = (
    "Creatures you control get +1/+1 until end of turn. If this spell was "
    "kicked, Zombie creatures you control get an additional +2/+2 until end of "
    "turn."
)


def test_an_additional_pump_of_a_covered_set_is_a_second_pump_behind_the_kicker():
    first, second = _steps(_lowered(_STRENGTH))

    assert (first.kind, first.payload["power"], first.payload["toughness"]) == (
        "buff_creatures_global", 1, 1,
    )
    assert second.kind == "if_then"
    assert second.payload["condition"] == {"kind": "was_kicked"}
    (pump,) = second.payload["then"]
    assert pump.kind == "buff_creatures_global"
    assert (pump.payload["power"], pump.payload["toughness"]) == (2, 2)
    assert pump.payload["subtypes"] == ["zombie"]


@pytest.mark.parametrize("line", [
    # A set the first pump did not cover: an opponent's Zombie got no +1/+1,
    # so "additional" would be false of it.
    "Creatures you control get +1/+1 until end of turn. If this spell was "
    "kicked, Zombie creatures get an additional +2/+2 until end of turn.",
    # Nothing in front of it to be additional to.
    "If this spell was kicked, Zombie creatures you control get an additional "
    "+2/+2 until end of turn.",
    # A keyword grant in front is not a pump.
    "Creatures you control gain trample until end of turn. If this spell was "
    "kicked, Zombie creatures you control get an additional +2/+2 until end "
    "of turn.",
])
def test_an_additional_pump_needs_a_pump_that_covered_those_creatures(line):
    assert _refused(line)


# --- "that permanent's mana value", and two targets with different nouns ------

_THUNDER = (
    "Destroy target artifact or enchantment. If this spell was kicked, it "
    "deals damage equal to that permanent's mana value to target creature."
)


def test_that_permanents_mana_value_reads_the_destroys_record():
    destroy, kicked = _steps(_lowered(_THUNDER, "Orim's Thunder"))

    assert destroy.kind == "destroy_target_permanent"
    (damage,) = kicked.payload["then"]
    assert damage.kind == "deal_damage"
    assert damage.payload["amount_from"] == "its_mana_value"


def test_two_targets_named_by_different_nouns_are_two_announced_roles():
    """An artifact-or-enchantment and a creature are not one target named
    twice: the destroy spends the first role and the damage the second, off
    one shared ordered list."""
    destroy, kicked = _steps(_lowered(_THUNDER, "Orim's Thunder"))
    (damage,) = kicked.payload["then"]

    assert destroy.payload["targets"]["kind"] == "roles"
    assert destroy.payload["targets"]["role"] == "artifact_or_enchantment"
    assert damage.payload["targets"]["role"] == "creature"
    assert destroy.payload["targets"]["roles"] == damage.payload["targets"]["roles"]
    assert [role["role"] for role in destroy.payload["targets"]["roles"]] == [
        "artifact_or_enchantment", "creature",
    ]


def test_a_pronoun_that_only_lost_a_narrowing_is_still_one_target():
    """The other half of that evidence. Jabari's Influence's "it" is a copy of
    its antecedent with "that attacked you this turn" dropped — a different
    filter and the same noun — and must stay one announcement, not two."""
    program = compile_card_oracle(_POOL["Jabari's Influence"])

    def descriptions(instructions):
        for instruction in instructions:
            payload = instruction.payload or {}
            if isinstance(payload.get("targets"), dict):
                yield payload["targets"]
            for key in ("steps", "then", "else", "action", "otherwise"):
                if isinstance(payload.get(key), (list, tuple)):
                    yield from descriptions(payload[key])

    found = list(descriptions(program.instructions))
    assert len(found) == 2
    assert all(described.get("kind") == "object" for described in found)


def test_that_permanents_mana_value_needs_a_step_that_recorded_one():
    reason = _refused(
        "It deals damage equal to that permanent's mana value to target creature.",
        "Orim's Thunder",
    )
    assert "its_mana_value" in reason


# --- "loses N life for each <noun> you control" (Last Stand) ------------------


def test_a_life_loss_per_permanent_its_controller_has_is_one_counted_number():
    (loss,) = _lowered("Target opponent loses 2 life for each Swamp you control.")

    assert loss.kind == "target_loses_life"
    assert loss.payload["amount"] == "x"
    assert loss.payload[X_FROM_COUNT] == {
        "zone": "battlefield", "owner": "you",
        "filter": {"subtype_filter": "swamp"}, "multiplier": 2,
    }
    assert loss.payload["targets"]["opponents_only"] is True


def test_a_life_loss_per_permanent_of_no_named_seat_is_refused():
    """"…for each Swamp" names no seat, and a count nothing scopes is a count
    of somebody's board the card never chose."""
    assert _refused("Target opponent loses 2 life for each Swamp.")


# --- "draw …, then discard that many cards" (Last Stand) ----------------------

_ISLANDS = {"zone": "battlefield", "owner": "you", "filter": {"subtype_filter": "island"}}


def test_discard_that_many_takes_the_draws_own_quantity():
    """CR 608.2h: the number is determined once, so the discard is sized by
    the same count the draw was — not by a second reading of the board, and
    not by how many cards happened to arrive."""
    draw, discard = _steps(_lowered(
        "Draw a card for each Island you control, then discard that many cards."
    ))

    assert (draw.kind, discard.kind) == ("draw_controller_cards", "discard_controller_cards")
    assert draw.payload[X_FROM_COUNT] == _ISLANDS
    assert discard.payload == {"amount": "x", X_FROM_COUNT: _ISLANDS}


def test_discard_that_many_after_a_printed_number_or_an_announced_x():
    _draw, discard = _steps(_lowered("Draw two cards, then discard that many cards."))
    assert discard.payload == {"amount": 2}

    _draw, discard = _steps(_lowered("Draw X cards, then discard that many cards."))
    assert discard.payload == {"amount": "x"}


@pytest.mark.parametrize("line", [
    # No draw in front of it: "that many" names nothing.
    "Discard that many cards.",
    # Somebody else's draw is not the discarding seat's number.
    "Target player draws two cards, then discard that many cards.",
])
def test_discard_that_many_needs_the_same_seats_draw_in_front_of_it(line):
    assert _refused(line)


# --- a payment's number over a sweep (Bloodfire Infusion) ---------------------

_INFUSION = (
    "{R}, Sacrifice enchanted creature: This Aura deals damage equal to the "
    "sacrificed creature's power to each creature."
)


def test_a_cost_sized_damage_reaches_a_described_set():
    (sweep,) = _lowered(_INFUSION, "Bloodfire Infusion")

    assert sweep.kind == "deal_damage_each_matching"
    assert sweep.payload["amount"] == "x"
    assert sweep.payload["filter"] == {"type_filter": "creature"}
    assert sweep.payload[X_FROM_COUNT] == {"cost_sacrifice_characteristic": "power"}


def test_a_cost_sized_sweep_keeps_the_sweeps_own_narrowing():
    (sweep,) = _lowered(
        "{R}, {T}, Tap an untapped creature you control: This artifact deals "
        "damage equal to the tapped creature's power to each creature without "
        "flying."
    )

    assert sweep.payload["filter"] == {
        "type_filter": "creature", "without_keywords": ["flying"],
    }
    assert sweep.payload[X_FROM_COUNT] == {"cost_tap_characteristic": "power"}


@pytest.mark.parametrize("line", [
    # CR 120.1a: damage marked on a land is never read.
    "{R}, Sacrifice a creature: This creature deals damage equal to the "
    "sacrificed creature's power to each land.",
    # Two recipients is a different sweep, which nothing sizes by a payment.
    "{R}, Sacrifice a creature: This creature deals damage equal to the "
    "sacrificed creature's power to each creature and each player.",
])
def test_a_cost_sized_sweep_refuses_what_the_sweep_refuses(line):
    assert _refused(line)


# --- "unless either one is a color the other isn't" (Dead Ringers) ------------

_RINGERS = (
    "Destroy two target nonblack creatures unless either one is a color the "
    "other isn't. They can't be regenerated."
)


def test_a_colour_comparison_guards_a_destroy_of_exactly_two_targets():
    (guard,) = _lowered(_RINGERS, "Dead Ringers")

    assert guard.kind == "if_then"
    assert guard.payload["condition"] == {"kind": "targets_differ_in_color"}
    # "unless": the destroy is what happens when the colours do *not* differ.
    assert guard.payload["then"] == ()
    (destroy,) = guard.payload["else"]
    assert destroy.kind == "destroy_target_permanent"
    assert destroy.payload["bypass_regeneration"] is True
    assert destroy.payload["targets"]["quantifier"] == "exactly"
    assert destroy.payload["targets"]["count"] == 2
    assert destroy.payload["targets"]["filter"] == {
        "type_filter": "creature", "exclude_colors": ["B"],
    }


@pytest.mark.parametrize("line", [
    "Destroy target nonblack creature unless either one is a color the other isn't.",
    "Destroy all creatures unless either one is a color the other isn't.",
    "Destroy three target creatures unless either one is a color the other isn't.",
])
def test_either_one_and_the_other_need_a_pair_to_name(line):
    """One target, a sweep and three targets each leave "either one" and "the
    other" with no pair — refused, rather than compared about nothing."""
    assert "pair" in _refused(line)


def test_half_of_the_colour_clause_is_not_the_clause():
    assert _refused("Destroy two target nonblack creatures unless either one is a color.")


# --- "The next X damage … to target … is dealt to another target … instead" ---

_MANEUVER = (
    "The next X damage that would be dealt to target creature, planeswalker, "
    "or player this turn is dealt to another target creature, planeswalker, "
    "or player instead."
)


def test_a_counted_redirect_between_two_announced_targets():
    """Both ends announced, neither the source: its own kind, on the one
    channel that carries a list of targets spanning both battlefields and the
    players' faces — two entries, each the whole pool."""
    (redirect,) = _lowered(_MANEUVER, "Captain's Maneuver")

    assert redirect.kind == "redirect_next_damage_between_targets_until_eot"
    assert redirect.payload == {
        "amount": "x",
        "targets": {
            "quantifier": "divided", "kind": "divided", "division": "each",
            "target_count": 2,
        },
    }


@pytest.mark.parametrize("line", [
    # No "another": the two ends could be one creature, redirected to itself.
    "The next X damage that would be dealt to target creature, planeswalker, "
    "or player this turn is dealt to target creature, planeswalker, or player "
    "instead.",
    # Narrowed ends have a noun this channel's picker cannot ask per slot.
    "The next X damage that would be dealt to target creature this turn is "
    "dealt to another target creature instead.",
    # A protected end nobody announced and that is not the source. This one
    # used to lower as "…dealt to **this creature**…", with one target of two.
    "The next 1 damage that would be dealt to you this turn is dealt to "
    "target creature instead.",
])
def test_a_counted_redirect_that_is_neither_shape_is_refused(line):
    assert _refused(line)


def test_the_source_ended_counted_redirects_are_what_they_were():
    """Zhalfirin Crusader and Daughter of Autumn: one end the source, one
    announced. The new branch sits in front of theirs and must take neither."""
    (off_source,) = _lowered(
        "{1}{W}: The next 1 damage that would be dealt to this creature this "
        "turn is dealt to any target instead."
    )
    assert off_source.kind == "redirect_next_damage_from_source_until_eot"

    (onto_source,) = _lowered(
        "{W}: The next 1 damage that would be dealt to target white creature "
        "this turn is dealt to this creature instead."
    )
    assert onto_source.kind == "redirect_next_damage_to_source_until_eot"
