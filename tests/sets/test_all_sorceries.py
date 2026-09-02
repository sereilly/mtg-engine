"""Per-card tests for Alliances' sorceries.

See tests/sets/README.md for the convention: get cards through
``set_pool("ALL")`` / ``set_cards("ALL")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement
Alliances split by grammar family rather than by printed type, so several
groups land tests in this one file. Each group appends a single delimited
block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G4: alternative and repeated costs ---
#
# Alliances' two *repeated* additional-cost sorceries (CR 601.2b/601.2f: a cost
# paid "any number of times", with the effect scaling off how many). Both are
# declined this round, and each decline names the parts rather than the card.
# The rules-level work this group did land is CR 118.9 alternative costs, whose
# cards are all instants — see ``tests/sets/test_all_instants.py`` and
# ``tests/rules/test_alternative_costs.py``.

from engine.cast_costs import additional_costs
from engine.oracle import compile_card_oracle


def test_taste_of_paradise_declines_on_a_repeated_additional_cost(set_pool):
    """"As an additional cost to cast this spell, you may pay {1}{G} **any
    number of times**." Four named parts, and the first three are shared with
    Primitive Justice below:

    1. **a mana clause in ``cast_costs._COST_CLAUSES``** — the table reads life,
       discards, sacrifices and exiles, and no mana at all;
    2. **an optional cost** — every clause the table reads is mandatory, which
       is what makes CR 601.2h's gate a refusal rather than an offer;
    3. **a repeat count announced at CR 601.2b** and carried on the stack item,
       so the resolution can read how many times it was paid — the channel
       ``sacrificed_for_cost`` already demonstrates, one payment kind over;
    4. **an amount that counts that repeat** — "3 life plus an additional 3 life
       for each additional {1}{G} you paid" is ``lowering/_amounts.py``'s
       question (CR 107.3) asked of a cost rather than of a board.

    Note what is *not* missing: nothing here needs a card hook. Every part is a
    template five cards across four sets would print the same way."""
    taste = set_pool("ALL")["Taste of Paradise"]
    assert not compile_card_oracle(taste).supported
    assert not additional_costs(taste), (
        "reading an optional repeated cost as a mandatory single one would "
        "make the spell cost {3}{G} plus {1}{G} and never scale"
    )


def test_primitive_justice_declines_on_the_same_parts_plus_a_target_count(set_pool):
    """Parts 1-3 of Taste of Paradise, and then two of its own:

    5. **two repeat counts on one spell** — "you may pay {1}{R} and/or {1}{G}
       any number of times" is two independent counters, which a single repeat
       count cannot say;
    6. **a target count that depends on those counts** — "For each additional
       {1}{R} you paid, destroy another target artifact". CR 601.2c fixes the
       number of targets at announcement, so the count has to be known before
       the targets are named, which is the ordering CR 601.2b/601.2c already
       has and no card in the pool has needed yet."""
    justice = set_pool("ALL")["Primitive Justice"]
    assert not compile_card_oracle(justice).supported
    assert not additional_costs(justice)


# --- W2G2: costs ---
#
# The additional cost was already read (W1G4's table); what was missing was the
# **untimed** control change behind it (CR 611.2). Imports are in this block,
# per the header's parallel-authorship convention.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.cast_costs import additional_costs
from engine.control import base_controller, control_changes
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_W2G2_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g2_ritual_board(set_pool):
    """Ritual of the Machine in hand, one creature each side. Costs enforced so
    the sacrifice is really collected."""
    caster = PlayerState(name="A", hand=[set_pool("ALL")["Ritual of the Machine"]])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = False
    caster.battlefield.append(Permanent(card=_W2G2_LEA["Grizzly Bears"]))
    game.players[1].battlefield.append(Permanent(card=_W2G2_LEA["Hill Giant"]))
    game._settle()
    return game, caster


def test_ritual_of_the_machine_steals_a_creature_for_good(set_pool):
    """"Gain control of target nonartifact, nonblack creature." No duration at
    all, which used to refuse — and CR 611.2 makes that a lifetime rather than
    a missing one, so nothing may ever hand the creature back.

    Cleanup is the assertion that matters: the until-end-of-turn contribution
    beside this one is dropped there, and reusing that kind would have made
    this steal last a turn."""
    game, caster = _w2g2_ritual_board(set_pool)
    stolen = game.players[1].battlefield[0]

    result = game.cast_from_hand(
        0, "Ritual of the Machine", target_player_index=1,
        target_permanent_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert game.controller_index_of(stolen) == 0
    # CR 108.3 / CR 613.1: ownership and the base controller are untouched, so
    # an effect that later ended would revert to the right seat.
    assert base_controller(stolen) == 1
    assert [c["until_eot"] for c in control_changes(stolen)] == [False]

    game.resolve_cleanup_step(0)
    game._settle()
    assert game.controller_index_of(stolen) == 0, "an untimed steal is forever"
    assert [p.card.name for p in game.controlled_by(0)] == ["Hill Giant"]


def test_ritual_of_the_machine_charges_its_printed_sacrifice(set_pool):
    """The cost half. "As an additional cost to cast this spell, sacrifice a
    creature" was already in the table W1G4 built; what this pins is that the
    two halves are on the *same* card and both really happen — a cost that is
    parsed and charged by nobody is this repo's recurring bug."""
    ritual = set_pool("ALL")["Ritual of the Machine"]
    (cost,) = additional_costs(ritual)
    assert cost.sacrifice_filter == {"type_filter": "creature"}

    game, caster = _w2g2_ritual_board(set_pool)
    game.cast_from_hand(
        0, "Ritual of the Machine", target_player_index=1,
        target_permanent_index=0,
    )
    game._settle()

    assert [c.name for c in caster.graveyard] == [
        "Grizzly Bears", "Ritual of the Machine",
    ]


def test_ritual_of_the_machine_cannot_be_cast_with_no_creature(set_pool):
    """CR 601.2h: an unpayable additional cost makes the spell uncastable, not
    free. The creature this eats is the caster's own, so an empty board is the
    case — and the steal must not happen anyway."""
    caster = PlayerState(name="A", hand=[set_pool("ALL")["Ritual of the Machine"]])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.players[1].battlefield.append(Permanent(card=_W2G2_LEA["Hill Giant"]))
    game._settle()
    stolen = game.players[1].battlefield[0]

    result = game.cast_from_hand(
        0, "Ritual of the Machine", target_player_index=1,
        target_permanent_index=0,
    )
    game._settle()

    assert not result.supported
    assert game.controller_index_of(stolen) == 1
    assert [c.name for c in caster.hand] == ["Ritual of the Machine"]


def test_ritual_of_the_machine_honours_its_printed_exclusions(set_pool):
    """"nonartifact, **nonblack**" — the narrowing rides the target description
    and is enforced where Terror's identical one is, at announcement. A steal
    that dropped it would take anything at all."""
    program = compile_card_oracle(set_pool("ALL")["Ritual of the Machine"])
    (steal,) = [i for i in program.instructions if i.kind == "gain_control_of_target"]
    assert steal.payload["exclude_colors"] == ["B"]
    assert steal.payload["exclude_types"] == ["artifact"]

    caster = PlayerState(name="A", hand=[set_pool("ALL")["Ritual of the Machine"]])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = False
    caster.battlefield.append(Permanent(card=_W2G2_LEA["Grizzly Bears"]))
    game.players[1].battlefield.append(Permanent(card=_W2G2_LEA["Bog Wraith"]))
    game._settle()
    wraith = game.players[1].battlefield[0]

    result = game.cast_from_hand(
        0, "Ritual of the Machine", target_player_index=1,
        target_permanent_index=0,
    )
    game._settle()

    assert not result.supported, "Bog Wraith is black"
    assert game.controller_index_of(wraith) == 1
