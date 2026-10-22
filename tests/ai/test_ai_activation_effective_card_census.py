"""Census: does an AI seat activate what its permanent **has**, or only what
its card prints?

``choose_activation_action`` compiled ``permanent.card`` — the card as
printed. A permanent's abilities are its *effective* card's (CR 613: a copy
has the copied object's, layer 1; an Aura's quoted grant is the enchanted
permanent's, layer 6), which is the card the activation path compiles
(``Game.usable_abilities_of``) and the browser lists for a person. So a Clone
of a Prodigal Sorcerer never pinged in an AI's hands and a creature wearing
Hermetic Study was a creature wearing nothing.

**How it is built.** The population is every supported permanent card in the
pool that is not a land, on a small board that gives an ability something to
aim at, in each of three **placements**:

``printed``
    the card itself — the control: what the seat proposed all along;
``copied``
    a blank creature that is a copy of it (``copies.become_copy``);
``worn``
    for an Aura or an Equipment: attached to a permanent of the seat's that
    it may be attached to — a blank creature, an artifact, a land.

The proposal is ``choose_activation_action`` and the activation is the
simulator's own executor (``ai_simulator._play_activations``), so "accepted"
is the engine's answer and a refusal is counted exactly as a seeded run
counts it (``SimulationReport.refused_activations``).

Two claims. **A copy is proposed where its original is**: the seat that
activates a Prodigal Sorcerer activates a Clone of one. And **what the seat
now proposes is refused nowhere its original is not** — the honesty count,
over the pool.

Validated backwards, over the whole pool (3,568 cards) on the tree that
compiled the printed card: 931 cards whose printed self the seat activated,
**a copy of none of them** and no Aura's grant. After: 938 printed (seven
Slivers now use the ability their own static gives them), 918 of them as a
copy — the other twenty are ``pays_in_its_own_counters`` — and four hosts
using what an Aura gave them. The fifteen refusals it pinned were there
before, on the printed card, and were the same fifteen on a copy; eleven of
them were a cost the board could not pay and went with the activation cost
gate (Torment's W2G3), so ``REFUSED`` holds the four that stand.

The suite sweeps a fixed share (``SAMPLE_EVERY``) and the named cards; run it
as a module for all of it
(``python -m tests.ai.test_ai_activation_effective_card_census``).
"""
from __future__ import annotations

import random
import sys
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine import ai_simulator
from engine.ai_abilities import choose_activation_action
from engine.auras import attach_aura
from engine.mixins.stack.casting import aura_enchant_noun
from engine.copies import become_copy
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.ai import test_ai_mode_chooser_census as modes
from tests.helpers import _mk_card

ME, OPP = 0, 1
POOL = modes.POOL
PLACEMENTS = ("printed", "copied", "worn")

#: The creature a copy is made *of nothing* on, and the one an Aura is put on.
BLANK = _mk_card(
    name="Bait Blank", type_line="Creature - Shapeshifter", power=1, toughness=3,
    mana_cost="{3}{U}", colors=("U",),
)
#: What an ability can be aimed at, per seat.
UNITS = ("white creature", "black creature", "artifact", "enchantment", "island")

SAMPLE_EVERY = 8

#: Activations the seat proposes and the engine declines, each with why —
#: **found by this sweep and left**: every one was proposed for the printed
#: card on the tree before this sweep existed, and a copy of the card is
#: refused for the same reason and no other.
#:
#: Four are "up to X target …, where X is the number of verse counters", with
#: no counter yet: the chooser names one target and X is zero.
_VERSE = "names a target for 'up to X', and X is the verse counters it has: none"
REFUSED: dict = {
    "Recantation": _VERSE, "Rumbling Crescendo": _VERSE,
    "Serra's Liturgy": _VERSE, "Vile Requiem": _VERSE,
}
#: Eleven more stood here until Torment's W2G3: a cost this board cannot pay
#: — tapping other permanents, returning them, exiling several cards from a
#: graveyard, a card out of an empty hand. The chooser asked about the costs
#: it knew one at a time, and an activation had no gate of the engine's to
#: ask, the checks being inline in ``activation._activate_onto_stack``. They
#: are one gate now (``Game.unpayable_activation_cost``), which that door
#: refuses with and the chooser asks; swept always, so a twelfth would show.
NO_LONGER_REFUSED = frozenset({
    "Drudge Spell", "Flooded Shoreline", "Hand of Justice", "Hecatomb",
    "Jandor's Ring", "Karplusan Giant", "Night Soil", "Penance",
    "Quirion Ranger", "Shacklegeist", "Vodalian War Machine",
})
#: Cards the suite always sweeps: the two the defect was told with, and one
#: of each way a permanent comes by an ability it does not print.
ALWAYS = frozenset({
    "Prodigal Sorcerer", "Rod of Ruin", "Hermetic Study", "Fire Whip",
    "Sisay's Ingenuity", "Barbed Field", "Short Sword", "Clot Sliver",
    "Triskelion",
}) | frozenset(REFUSED) | NO_LONGER_REFUSED
assert ALWAYS <= set(POOL), sorted(ALWAYS - set(POOL))


def population() -> list:
    """Every supported nonland permanent card, by name."""
    found = []
    for name in sorted(POOL):
        card = POOL[name]
        if card.primary_type in ("instant", "sorcery", "land"):
            continue
        if not compile_card_oracle(card).supported:
            continue
        found.append(card)
    return found


def _is_attachment(card) -> bool:
    line = (card.type_line or "").lower()
    return "aura" in line or "equipment" in line


def board(card, placement: str) -> "tuple[Game, Permanent] | None":
    """The board with *card* placed as *placement* says, and the permanent
    that should have its abilities — or None when the placement is not one
    this card has (only an Aura or an Equipment is worn)."""
    if placement == "worn" and not _is_attachment(card):
        return None
    forest = POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[], library=[forest] * 10),
        PlayerState(name="Opp", hand=[forest], library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat in (ME, OPP):
        for key in UNITS:
            modes.place(game, seat, key)
        game.players[seat].graveyard.extend(modes.GRAVE.values())

    def put(what) -> Permanent:
        permanent = Permanent(card=what)
        game._put_permanent_onto_battlefield(ME, permanent, ME)
        permanent.metadata["summoning_sickness_turn"] = -99
        return permanent

    if placement == "printed":
        subject = put(card)
    elif placement == "copied":
        subject = put(BLANK)
        become_copy(subject, Permanent(card=card))
    else:
        # What it may be attached to: an "enchant land" Aura goes on a land.
        noun = aura_enchant_noun(card) or "creature"
        placed = {permanent.card.name: permanent for permanent in game.controlled_by(ME)}
        if "land" in noun:
            subject = placed[modes.ZOO["island"].name]
        elif "artifact" in noun and "creature" not in noun:
            subject = placed[modes.ZOO["artifact"].name]
        else:
            subject = put(BLANK)
        attach_aura(put(card), subject)
    game._recompute_continuous_effects()
    game.players[ME].mana_pool.update({symbol: 8 for symbol in "WUBRGC"})
    return game, subject


def run(card, placement: str) -> "dict | None":
    row = {
        "card": card.name, "placement": placement, "proposed": False,
        "by_subject": False, "refused": None, "error": None,
    }
    try:
        random.seed(1337)
        built = board(card, placement)
        if built is None:
            return None
        game, subject = built
        action = choose_activation_action(game, ME)
        if action is None:
            return row
        row["proposed"] = True
        row["by_subject"] = game.permanent_at(ME, action.permanent_index) is subject
        report = ai_simulator.SimulationReport(
            games_requested=1, games_completed=0, interaction_count=0,
        )
        ai_simulator._play_activations(game, ME, report, 1, 1)
        row["refused"] = "; ".join(report.refused_activations) or None
    except Exception as exc:  # a crash is a finding, not a pass
        row["error"] = f"EXC {type(exc).__name__}: {exc}"
    return row


def census(sample: bool) -> list:
    rows = []
    for position, card in enumerate(population()):
        if sample and position % SAMPLE_EVERY and card.name not in ALWAYS:
            continue
        for placement in PLACEMENTS:
            row = run(card, placement)
            if row is not None:
                rows.append(row)
    return rows


def tag(row) -> tuple:
    return (row["card"], row["placement"])


def tally(rows) -> Counter:
    counts: Counter = Counter()
    for row in rows:
        counts[(row["placement"], "examined")] += 1
        counts[(row["placement"], "proposed")] += row["proposed"]
        counts[(row["placement"], "by subject")] += row["by_subject"]
        counts[(row["placement"], "refused")] += bool(row["refused"])
    return counts


def pays_in_its_own_counters(card) -> bool:
    """Whether the ability the seat would activate is paid for by removing a
    counter from its own permanent ("Remove a +1/+1 counter from this
    creature: …", Triskelion; a fade counter). The card enters with them and
    this sweep's copy did not enter as a copy — it became one — so it has
    none, and the chooser rightly proposes nothing (CR 601.2h)."""
    from engine.targeting import usable_activated_abilities

    ability = next(iter(usable_activated_abilities(compile_card_oracle(card))), None)
    return ability is not None and bool(ability.cost.remove_counter)


def copies_left_idle(rows) -> list:
    """Cards whose printed self is activated and whose copy is not, though
    the copy could pay for it."""
    by_key = {tag(row): row for row in rows}
    return sorted(
        card for (card, placement), row in by_key.items()
        if placement == "printed" and row["by_subject"]
        and not by_key[(card, "copied")]["by_subject"]
        and not pays_in_its_own_counters(POOL[card])
    )


# -- the tests ------------------------------------------------------------------

@pytest.fixture(scope="module")
def rows() -> list:
    return census(sample=True)


def test_the_sweep_examined_the_pool(rows):
    """The floor: a sweep that reaches nothing passes everything."""
    counts = tally(rows)
    assert counts[("printed", "examined")] >= 330
    assert counts[("copied", "examined")] == counts[("printed", "examined")]
    assert counts[("worn", "examined")] >= 40
    # ...and that it is a sweep of activations, not of permanents with
    # nothing to activate.
    assert counts[("printed", "by subject")] >= 40, dict(counts)
    assert ALWAYS <= {row["card"] for row in rows}


def test_no_proposal_crashed(rows):
    assert {tag(row): row["error"] for row in rows if row["error"]} == {}


def test_what_is_refused_is_the_pinned_set_and_the_same_for_a_copy(rows):
    """`refused_activations`, over the pool: a seat that proposes what the
    engine declines does nothing with that permanent, every turn. The ones
    that stand are ``REFUSED`` — and reading the effective card added none: a
    copy is refused exactly where its original is, and nothing worn is."""
    refused = {tag(row) for row in rows if row["refused"]}
    pinned = {
        (name, placement) for name in REFUSED for placement in ("printed", "copied")
    }
    assert refused == pinned, sorted(refused ^ pinned)


def test_a_copy_is_activated_where_its_original_is(rows):
    """Whole pool, before: 0 of the copies whose original is activated were
    proposed — the blank card under them prints nothing. After: every one
    that can pay."""
    assert copies_left_idle(rows) == []
    counts = tally(rows)
    assert counts[("copied", "by subject")] >= 100, dict(counts)
    by_key = {tag(row): row for row in rows}
    # ...and the ones that cannot are held, not proposed and refused.
    assert by_key[("Triskelion", "printed")]["by_subject"]
    assert not by_key[("Triskelion", "copied")]["proposed"]


def test_a_sliver_uses_what_its_own_static_gives_it(rows):
    """'All Slivers have "{2}: Regenerate this permanent."' (Clot Sliver):
    the card prints a static ability and *has* an activated one. Seven
    Slivers the seat never activated."""
    row = {tag(row): row for row in rows}[("Clot Sliver", "printed")]
    assert row["by_subject"] and not row["refused"], row


def test_a_granted_ability_is_activated(rows):
    """'Enchanted creature has "{T}: This creature deals 1 damage to any
    target."' (Hermetic Study, Fire Whip), '…has "{2}{U}: Target creature
    becomes the color of your choice until end of turn."' (Sisay's
    Ingenuity): the ability is the creature's, and the seat that controls it
    uses it."""
    by_key = {tag(row): row for row in rows}
    for name in ("Hermetic Study", "Fire Whip", "Sisay's Ingenuity"):
        row = by_key[(name, "worn")]
        assert row["by_subject"] and not row["refused"], row


def test_a_land_given_an_ability_is_still_left_alone(rows):
    """Measured and left: 'Enchanted land has "{T}: This land deals 1 damage
    to any target."' (Barbed Field). The chooser passes over every land, as
    it does a land's own printed abilities (a Mishra's Factory, a Maze of
    Ith): what a land is tapped for is the payment planner's question, and
    this chooser has no way to weigh a ping against the mana. Pinned so that
    the day it is weighed, this says so."""
    by_key = {tag(row): row for row in rows}
    assert not by_key[("Barbed Field", "worn")]["proposed"]


def test_a_clone_of_a_pinger_pings():
    """One row, on the board: a copy of Prodigal Sorcerer taps to deal 1
    damage. Its own card is a 1/3 with no text."""
    game, clone = board(POOL["Prodigal Sorcerer"], "copied")
    action = choose_activation_action(game, ME)
    assert action is not None
    assert game.permanent_at(ME, action.permanent_index) is clone
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    before = (game.players[OPP].life, len(list(game.controlled_by(OPP))))
    ai_simulator._play_activations(game, ME, report, 1, 1)
    assert not report.refused_activations
    assert clone.tapped
    after = (game.players[OPP].life, len(list(game.controlled_by(OPP))))
    assert after != before, "the ping landed nowhere"


if __name__ == "__main__":
    rows = census(sample="--sample" in sys.argv)
    counts = tally(rows)
    for key in sorted(counts):
        print(key, counts[key])
    print(f"rows: {len(rows)}  cards: {len({row['card'] for row in rows})}")
    idle = copies_left_idle(rows)
    print(f"== printed self activated, copy idle: {len(idle)}")
    print("   ", idle[:40])
    worn = sorted(row["card"] for row in rows if row["placement"] == "worn" and row["by_subject"])
    print(f"== worn and activated by the host: {len(worn)}")
    print("   ", worn)
    for leg in ("refused", "error"):
        found = {tag(row): row[leg] for row in rows if row[leg]}
        print(f"== {leg}: {len(found)}")
        for key in sorted(found):
            print(f"   {key}: {found[key]}")
