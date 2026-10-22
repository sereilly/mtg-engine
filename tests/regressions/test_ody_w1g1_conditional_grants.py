"""A static that hands its permanent more than a number, behind a condition.

Odyssey's threshold ("as long as there are seven or more cards in your
graveyard") is the first condition in the pool printed in front of a static
whose effect is not just a delta and a keyword: "…gets +2/+2 **and can't
block**" (Childhood Horror), "…**is black**, has trample, and has **"At the
beginning of your upkeep, sacrifice a creature."**" (Wayward Angel), "**all
creatures able to block** enchanted creature **do so**" (Seton's Desire). The
per-card tests are in ``tests/sets/test_ody_*.py``. What is held here is the
mechanism, with invented cards, because a sentence two cards could print has to
work for the second one:

* the condition is **payload** — the number, the comparison and the zone are
  read off the sentence, and it is the same payload a spell's "if" carries for
  the same words;
* both word orders are one static;
* the three new parts each have a reader — the colour in layer 5, a quoted
  ability and a static sentence on the derived-ability channel
  (``keywords.DERIVED_ABILITY_LINES``) — and a part with **no** reader refuses
  the card rather than compiling into a payload key nothing consults;
* the production keeps its hands off the lines other readers own.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.granted_abilities import (DERIVABLE_STATIC_KINDS,
                                      derived_line_supported)
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, compiled_units
from tests.helpers import resolve_stack

_THRESHOLD = "there are seven or more cards in your graveyard"


def _probe(text: str, type_line: str = "Creature — Horror", name: str = "Probe Horror"):
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power="2", toughness="2")
    return CardDefinition(
        name=name, mana_cost="{1}{B}", cmc=2.0, type_line=type_line,
        oracle_text=text, colors=("B",), color_identity=("B",), keywords=(),
        produced_mana=(), raw=raw,
    )


def _board(catalog_by_name, *cards_by_seat):
    """A two-seat game with each seat's cards put onto its battlefield."""
    forest = catalog_by_name["Forest"]
    game = Game(players=[
        PlayerState("A", library=[forest] * 10),
        PlayerState("B", library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    permanents = []
    for seat, cards in enumerate(cards_by_seat):
        for card in cards:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            permanents.append(permanent)
    return game, permanents


def _graveyard(game, catalog_by_name, seat, count):
    game.players[seat].graveyard[:] = [catalog_by_name["Forest"]] * count
    game.check_state_based_actions()


def _to_declare_attackers(game, seat=0):
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step


def _slot(game, seat, permanent):
    return list(game.controlled_by(seat)).index(permanent)


def _conditional(card):
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    (static,) = [i for i in program.instructions if i.kind == "conditional_static"]
    return static.payload


# ---------------------------------------------------------------------------
# The condition is payload, and one payload
# ---------------------------------------------------------------------------


def test_the_count_and_the_comparison_are_read_off_the_sentence(catalog_by_name):
    """"Three or more" is not seven or more, and "no cards" is neither: an
    invented creature printing a different number turns on at that number."""
    card = _probe(
        "This creature gets +1/+1 as long as there are three or more cards in "
        "your graveyard."
    )
    game, (probe,) = _board(catalog_by_name, [card])

    seen = []
    for count in (2, 3, 7, 2):
        _graveyard(game, catalog_by_name, 0, count)
        seen.append((probe.effective_power, probe.effective_toughness))

    assert seen == [(2, 2), (3, 3), (3, 3), (2, 2)]


def test_a_card_type_in_the_count_is_part_of_the_count(catalog_by_name):
    """"…seven or more **creature** cards in your graveyard" counts creature
    cards: seven lands are not seven creatures. The narrowing rides the same
    count spec a where-clause uses, so nothing here had to learn it."""
    card = _probe(
        "This creature has flying as long as there are two or more creature "
        "cards in your graveyard."
    )
    game, (probe,) = _board(catalog_by_name, [card])
    _graveyard(game, catalog_by_name, 0, 7)
    assert not game._has_keyword(probe, "flying")

    game.players[0].graveyard.extend([catalog_by_name["Grizzly Bears"]] * 2)
    game.check_state_based_actions()
    assert game._has_keyword(probe, "flying")


def test_a_static_and_a_spell_carry_the_same_condition_for_the_same_words():
    """One fact, one payload: the condition a threshold static carries is the
    ``cards_in_zones`` the condition lowering builds for a spell's "if" — so
    the count is taken by one evaluator wherever the clause is printed."""
    static = _conditional(_probe(f"This creature gets +1/+1 as long as {_THRESHOLD}."))
    spell = compile_card_oracle(_probe(
        f"If {_THRESHOLD}, draw a card.", type_line="Sorcery", name="Probe Insight",
    ))
    (branch,) = spell.instructions

    assert branch.kind == "if_then"
    assert static["condition"] == branch.payload["condition"]
    assert static["condition"]["kind"] == "cards_in_zones"


def test_both_word_orders_are_one_static():
    """The condition printed first or last is the same instruction, for every
    part a static may carry."""
    for effect in (
        "gets +1/+1 and has flying",
        "gets +2/+2 and can't block",
        "is white and has \"{T}: Destroy target black creature.\"",
    ):
        fronted = _conditional(_probe(f"As long as {_THRESHOLD}, this creature {effect}."))
        trailing = _conditional(_probe(f"This creature {effect} as long as {_THRESHOLD}."))
        assert fronted == trailing, effect


# ---------------------------------------------------------------------------
# Each new part has a reader
# ---------------------------------------------------------------------------


def test_the_derivable_static_kinds_are_exactly_the_ones_driven_here():
    """``DERIVABLE_STATIC_KINDS`` is a claim about three readers, and the three
    tests below are what it stands on. A fourth kind fails here until it has a
    test of its own driving it through the step that reads it."""
    assert DERIVABLE_STATIC_KINDS == {
        "cant_block", "must_attack_each_combat", "must_be_blocked_by_all_able",
    }
    assert derived_line_supported("This creature can't block.")
    assert derived_line_supported("This creature attacks each combat if able.")
    assert derived_line_supported("All creatures able to block this creature do so.")


def test_a_conditional_cant_block_is_read_at_the_declaration(catalog_by_name):
    card = _probe(f"As long as {_THRESHOLD}, this creature gets +1/+1 and can't block.")
    outcomes = []
    for count in (6, 7):
        game, (attacker, blocker) = _board(
            catalog_by_name, [catalog_by_name["Grizzly Bears"]], [card],
        )
        game.players[1].graveyard[:] = [catalog_by_name["Forest"]] * count
        _to_declare_attackers(game)
        slot = _slot(game, 0, attacker)
        assert game.declare_attackers(0, [slot])[0]
        game.advance_combat_phase()
        outcomes.append(game.declare_blockers(1, {_slot(game, 1, blocker): slot})[0])

    assert outcomes == [True, False]


def test_a_conditional_must_attack_is_read_at_the_declaration(catalog_by_name):
    card = _probe(f"This creature attacks each combat if able as long as {_THRESHOLD}.")
    outcomes = []
    for count in (6, 7):
        game, (probe,) = _board(catalog_by_name, [card])
        game.players[0].graveyard[:] = [catalog_by_name["Forest"]] * count
        _to_declare_attackers(game)
        outcomes.append(game.declare_attackers(0, [])[0])

    assert outcomes == [True, False]


def test_a_conditional_lure_is_read_at_the_declaration(catalog_by_name):
    card = _probe(
        f"As long as {_THRESHOLD}, all creatures able to block this creature do so."
    )
    outcomes = []
    for count in (6, 7):
        game, (probe, bears) = _board(
            catalog_by_name, [card], [catalog_by_name["Grizzly Bears"]],
        )
        game.players[0].graveyard[:] = [catalog_by_name["Forest"]] * count
        _to_declare_attackers(game)
        slot = _slot(game, 0, probe)
        assert game.declare_attackers(0, [slot])[0]
        game.advance_combat_phase()
        outcomes.append(game.declare_blockers(1, {})[0])

    assert outcomes == [True, False]


def test_a_conditional_colour_replaces_the_printed_one_and_goes_with_the_condition(
    catalog_by_name,
):
    """CR 105.3: the new colour replaces the ones the object had — a black
    card that "is white" under its condition is white and not black — and
    CR 611.3a: it is black again the moment the condition stops holding."""
    card = _probe(f"As long as {_THRESHOLD}, this creature is white.")
    game, (probe,) = _board(catalog_by_name, [card])

    seen = []
    for count in (6, 7, 6):
        _graveyard(game, catalog_by_name, 0, count)
        seen.append(sorted(probe.effective_colors))

    assert seen == [["B"], ["W"], ["B"]]


def test_a_conditional_quoted_ability_is_an_ability_only_while_the_condition_holds(
    catalog_by_name,
):
    """The quoted trigger is found by the upkeep scan while its controller has
    threshold and is simply not there otherwise — nothing to undo, because the
    line is re-derived on every recompute."""
    card = _probe(
        f"As long as {_THRESHOLD}, this creature has "
        "\"At the beginning of your upkeep, you gain 1 life.\""
    )
    game, (probe,) = _board(catalog_by_name, [card])
    game.active_player_index = 0

    life = []
    for count in (6, 7, 6):
        _graveyard(game, catalog_by_name, 0, count)
        game.resolve_upkeep(0)
        resolve_stack(game)
        life.append(game.players[0].life)

    assert life == [20, 21, 21]


def test_an_auras_conditional_grant_lands_on_its_host(catalog_by_name):
    """Printed on an Aura about "enchanted creature", every part goes to the
    host and the condition is asked of the Aura's controller (CR 109.5)."""
    aura_card = _probe(
        "Enchant creature\n"
        f"Enchanted creature gets +1/+1 and can't block as long as {_THRESHOLD}.",
        type_line="Enchantment — Aura", name="Probe Shackles",
    )
    assert compile_card_oracle(aura_card).supported
    game, (host,) = _board(catalog_by_name, [], [catalog_by_name["Grizzly Bears"]])
    game.players[0].hand.append(aura_card)
    assert game.cast_from_hand(
        0, "Probe Shackles", target_permanent_ids=[host.permanent_id],
    ).supported
    resolve_stack(game)
    (aura,) = [p for p in game.controlled_by(0) if p.card.name == "Probe Shackles"]
    assert aura.metadata.get("attached_to") is host

    seen = []
    for seat, count in ((1, 7), (0, 7), (0, 6)):
        game.players[0].graveyard.clear()
        game.players[1].graveyard.clear()
        _graveyard(game, catalog_by_name, seat, count)
        program = compile_card_oracle(host.effective_card)
        seen.append((
            (host.effective_power, host.effective_toughness),
            any(i.kind == "cant_block" for i in program.instructions),
        ))

    # Never a flat +1/+1 underneath the conditional one: the Aura text table
    # (``aura_grants.aura_static_pt_grant``) answers the words "gets +1/+1"
    # wherever it finds them, and used to decline a condition only when it was
    # printed straight after the numbers.
    assert seen == [((2, 2), False), ((3, 3), True), ((2, 2), False)]


def test_the_aura_tables_do_not_answer_half_of_a_conditional_sentence():
    """Three shapes the grammar reads whole, each of which a text table used
    to answer in part: a flat delta under a condition printed behind another
    clause or in front of the sentence, and a keyword granted for good beside
    a restriction nothing read."""
    from engine.aura_grants import aura_keyword_grants, aura_static_pt_grant

    assert aura_static_pt_grant(
        f"Enchanted creature gets +1/+1 and can't block as long as {_THRESHOLD}."
    ) is None
    assert aura_static_pt_grant(
        f"As long as {_THRESHOLD}, enchanted creature gets +1/+1 and can't block."
    ) is None
    assert aura_keyword_grants(
        f"Enchanted creature has flying and can't block as long as {_THRESHOLD}."
    ) == ()
    # …and the lines those readers do own are untouched.
    assert aura_static_pt_grant("Enchanted creature gets +2/+2.") == (2, 2)
    assert aura_static_pt_grant(
        'Enchanted creature gets +2/+0 and has "{T}: This creature gets +1/+1 '
        'as long as it\'s tapped."'
    ) == (2, 0)
    assert aura_keyword_grants(
        "Enchanted land has indestructible and can't be enchanted by other Auras."
    ) == ("indestructible",)
    assert aura_keyword_grants(
        "Enchanted creature has phasing and can't be blocked except by Walls."
    ) == ("phasing",)


# ---------------------------------------------------------------------------
# What the gate refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # A static sentence nothing reads at the moment it would matter: an
        # entry-state phrase is consulted once, as the permanent arrives.
        f"As long as {_THRESHOLD}, this creature has \"This creature enters tapped.\"",
        # A predicate whose first word is not one the reader knows.
        f"As long as {_THRESHOLD}, this creature gets +1/+1 and dances.",
        # A sentence the compiler cannot read once it is spelled out.
        f"As long as {_THRESHOLD}, this creature gets +1/+1 and can't block "
        "creatures with three heads.",
        # Not a colour.
        f"As long as {_THRESHOLD}, this creature is purple.",
        # Two colours set by one static.
        f"As long as {_THRESHOLD}, this creature is white and is blue.",
        # A quoted ability the compiler cannot read.
        f"As long as {_THRESHOLD}, this creature has \"Whenever the moon is "
        "full, you win the game.\"",
        # The pronoun: after a fronted condition "it" is whatever the
        # condition was about, and this reader does not guess.
        f"As long as {_THRESHOLD}, it gets +1/+1 and can't block.",
        # A trailing word the clause does not account for.
        f"As long as {_THRESHOLD}, this creature gets +1/+1 and can't block "
        "this turn.",
    ],
)
def test_a_conditional_grant_the_engine_cannot_honour_refuses_the_card(text):
    """Loud, not narrower: each of these would otherwise compile into a
    payload with a part nothing reads, on a card reporting supported."""
    program = compile_card_oracle(_probe(text))
    assert not program.supported, program.instructions


def test_a_conditional_grant_does_not_take_a_line_another_reader_owns(
    catalog_by_name,
):
    """Essence Leak's "As long as enchanted permanent is red or green, **it**
    has "…"" is the Aura front end's
    (``aura_grants.conditional_ability_lines_for``), whose pronoun names the
    host. The grammar's conditional-grant production
    refuses the pronoun, so the card keeps exactly the program it had."""
    program = compile_card_oracle(catalog_by_name["Essence Leak"])

    assert program.supported
    assert not [i for i in program.instructions if i.kind == "conditional_static"]


# ---------------------------------------------------------------------------
# The pool: no conditional static carries a part nobody reads
# ---------------------------------------------------------------------------

#: Every key a ``conditional_static`` payload may carry, each read by a pass:
#: the delta and its complement by ``_refresh_dynamic_creatures``, the
#: keywords and the granted lines by ``_recalculate_lord_buffs``, the colour by
#: ``_refresh_global_statics``, protection by ``_protection_qualities``, and
#: the two combat permissions at their declarations.
_READ_KEYS = frozenset({
    "condition", "subject", "power", "toughness", "otherwise_power",
    "otherwise_toughness", "keywords", "protection_from", "cant_be_blocked",
    "ignores_defender", "colors", "ability_lines",
})


def test_every_conditional_static_in_the_pool_carries_only_parts_a_pass_reads():
    examined = 0
    stray: dict[str, set[str]] = {}
    unreadable: dict[str, list[str]] = {}
    pool: dict[str, object] = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    # ``compiled_units``: a split card's text is on its halves (CR 709.4c).
    for card, program in compiled_units(pool.values()):
        if not program.supported:
            continue
        for instruction in program.instructions:
            if instruction.kind != "conditional_static":
                continue
            examined += 1
            extra = set(instruction.payload) - _READ_KEYS
            if extra:
                stray[card.name] = extra
            for line in instruction.payload.get("ability_lines") or ():
                if not derived_line_supported(line):
                    unreadable.setdefault(card.name, []).append(line)
    # A floor, so a refactor that stops this loop finding the instruction
    # cannot leave it green over nothing: 81 on the day it was written.
    assert examined >= 70, examined
    assert not stray, stray
    assert not unreadable, unreadable
