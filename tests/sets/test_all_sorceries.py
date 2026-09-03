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
# paid "any number of times", with the effect scaling off how many). Both were
# declined in wave 1, each decline naming its parts. **W3G1 built parts 1-5**,
# so the two decline tests that stood here are gone rather than edited: Taste of
# Paradise is supported and has a real test in the W3G1 block below, and
# Primitive Justice's decline shrank to one part and is restated there beside
# it. A decline test for a card that now works is a test asserting the engine
# has not improved.
#
# The rules-level work this group did land is CR 118.9 alternative costs, whose
# cards are all instants — see ``tests/sets/test_all_instants.py`` and
# ``tests/rules/test_alternative_costs.py``.


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


# --- W2G4: library and modal ---
"""Diminishing Returns and Library of Lat-Nam.

Diminishing Returns is three sentences and one of them is two piles: CR 701.19
randomises a library **once**, so "their hand and graveyard into their library"
has to be one shuffle. Written as two statements the hand's cards would be down
among the graveyard's before the second one ran.

Library of Lat-Nam is CR 700.2e — the head names a chooser who is not the
caster, and the mode is picked as the spell is cast (CR 601.2b) by that other
player. The caster naming it would be the caster taking the half that suits
them, which is the opposite of what the card is printed to do.
"""

from engine import Game, PlayerState
from engine.game_types import CardDefinition


def _w2g4_deck_card(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Artifact", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Artifact"},
    )


def _w2g4_duel(set_pool, card_name, *, interactive):
    p1 = PlayerState(
        name="P1", hand=[set_pool("ALL")[card_name]],
        library=[_w2g4_deck_card(f"Mine {i}") for i in range(30)],
    )
    p2 = PlayerState(
        name="P2", library=[_w2g4_deck_card(f"Theirs {i}") for i in range(30)],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def test_w2g4_diminishing_returns_shuffles_hand_and_graveyard_in_one_move(set_pool):
    """One shuffle over two piles (CR 701.19). Both zones end empty and the
    library has grown by exactly what they held."""
    game, p1, p2 = _w2g4_duel(set_pool, "Diminishing Returns", interactive={0, 1})
    p1.hand.extend(_w2g4_deck_card(f"Held {i}") for i in range(2))
    p1.graveyard.extend(_w2g4_deck_card(f"Dead {i}") for i in range(3))
    p2.hand.append(_w2g4_deck_card("Theirs Held"))

    assert game.queue_from_hand(0, "Diminishing Returns").supported
    game._settle()
    assert game.confirm_draw_up_to(0, 7)
    assert game.confirm_draw_up_to(1, 7)
    game._settle()

    # The spell itself lands in the graveyard *after* it resolves (CR 608.2m),
    # so its own name is the only thing either pile still holds.
    assert [c.name for c in p1.graveyard] == ["Diminishing Returns"]
    assert p2.graveyard == []
    # 30 in the deck + 2 hand + 3 graveyard, less the ten exiled and the seven
    # drawn. The spell itself is on the stack by the time the shuffle runs, so
    # it is not one of the hand's cards.
    assert len(p1.library) == 30 + 2 + 3 - 10 - 7
    assert len(p1.exile) == 10
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7


def test_w2g4_diminishing_returns_offers_each_player_a_ceiling(set_pool):
    """"Then each player draws **up to** seven cards." No "may" is printed and
    none is needed: the ceiling is the decision, and a seat may answer with
    fewer."""
    game, p1, p2 = _w2g4_duel(set_pool, "Diminishing Returns", interactive={0, 1})

    assert game.queue_from_hand(0, "Diminishing Returns").supported
    game._settle()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("draw_up_to", 0), ("draw_up_to", 1)
    ]

    assert game.confirm_draw_up_to(0, 7)
    assert game.confirm_draw_up_to(1, 2)
    game._settle()
    assert len(p1.hand) == 7
    assert len(p2.hand) == 2


def test_w2g4_library_of_lat_nam_hands_the_mode_to_the_opponent(set_pool):
    """CR 700.2e: the other player chooses, and does it when the controller
    normally would — inside the announcement, with the spell already on the
    stack and nobody yet holding priority (CR 601.2i)."""
    game, _p1, _p2 = _w2g4_duel(set_pool, "Library of Lat-Nam", interactive={0, 1})

    assert game.queue_from_hand(0, "Library of Lat-Nam").supported

    assert [it.card.name for it in game.stack] == ["Library of Lat-Nam"]
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("opponent_mode_choice", 1)
    ]
    assert game.waiting_prompt() is not None


def test_w2g4_library_of_lat_nam_refuses_a_mode_the_caster_names(set_pool):
    """The refusal is the card. Read as an ordinary modal spell its caster would
    take the tutor every time, which is a strictly better card than the one
    printed — so an announcement naming a mode is refused rather than
    ignored."""
    game, _p1, _p2 = _w2g4_duel(set_pool, "Library of Lat-Nam", interactive={0, 1})

    result = game.queue_from_hand(
        0, "Library of Lat-Nam", mode_choices=[{"index": 1}]
    )

    assert not result.supported
    assert "an opponent chooses this spell's mode" in result.details
    assert game.stack == []


def test_w2g4_library_of_lat_nam_carries_out_the_mode_the_opponent_picked(set_pool):
    """The second mode: the caster searches their own library, which is a
    prompt on the *caster's* seat armed by an answer given on the opponent's.
    A chain of decisions inside one resolution (CR 608.2)."""
    game, p1, _p2 = _w2g4_duel(set_pool, "Library of Lat-Nam", interactive={0, 1})
    assert game.queue_from_hand(0, "Library of Lat-Nam").supported

    assert game.confirm_opponent_mode_choice(1, 1)
    game._settle()

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("search_library", 0)
    ]


def test_w2g4_a_non_interactive_chooser_takes_the_first_printed_mode(set_pool):
    """A stated policy, not a valuation — and the reason headless and AI play
    never stop on this prompt: an unanswered choice inside an announcement would
    hold the cast open forever."""
    game, p1, _p2 = _w2g4_duel(set_pool, "Library of Lat-Nam", interactive={0})

    assert game.cast_from_hand(0, "Library of Lat-Nam").supported

    assert game.pending_choices == []
    assert [t.event for t in game.delayed_triggers] == ["next_turns_upkeep"]


# --- W3G1: repeated additional costs ---
#
# CR 601.2b's *optional* additional cost, which no card in the pool had printed
# before this set: "you may pay {1}{G} **any number of times**". The rules-level
# tests are in ``tests/rules/test_optional_additional_costs.py``; these two are
# about the cards. Imports are in this block, per the header's
# parallel-authorship convention.

from engine import Game as _W3G1Game, PlayerState as _W3G1Player
from engine.cast_costs import additional_costs as _w3g1_costs
from engine.oracle import compile_card_oracle as _w3g1_compile


def _w3g1_taste_game(set_pool, green: int):
    caster = _W3G1Player(name="A", hand=[set_pool("ALL")["Taste of Paradise"]])
    game = _W3G1Game(players=[caster, _W3G1Player(name="B")])
    game.enforce_mana_costs = True
    caster.mana_pool["G"] = green
    game._settle()
    return game, caster


def test_taste_of_paradise_scales_its_one_life_gain_with_the_payments(set_pool):
    """"You gain 3 life plus an additional 3 life for each additional {1}{G} you
    paid."

    **One** life gain, not a base gain and a loop beside it: CR 119.3 makes this
    a single event, and a replacement watching "if you would gain life" must see
    3 + 3N once rather than N + 1 separate gains. So the amount is
    ``Plus(Fixed, Times(step, AdditionalCostPaidCount))`` and the handler does
    the arithmetic — the shape the existing amount nodes already had, with one
    new leaf under them."""
    (gain,) = [
        i for i in _w3g1_compile(set_pool("ALL")["Taste of Paradise"]).instructions
        if i.kind == "target_gains_life"
    ]
    assert gain.payload["amount"] == 3
    assert gain.payload["plus_per_cost_paid"] == {"cost": "{1}{G}", "each": 3}

    for times, expected in ((0, 23), (1, 26), (2, 29)):
        game, caster = _w3g1_taste_game(set_pool, green=4 + 2 * times)
        result = game.cast_from_hand(
            0, "Taste of Paradise",
            optional_cost_payments={"{1}{G}": times} if times else None,
        )
        game._settle()
        assert result.supported, result.details
        assert caster.life == expected, times
        assert sum(caster.mana_pool.values()) == 0, (
            "every offer taken has to come out of the pool; a count read back "
            "but not charged is a free spell"
        )


def test_primitive_justice_declines_on_a_target_per_repetition(set_pool):
    """The cost half now works — "you may pay {1}{R} **and/or** {1}{G} any
    number of times" reads as two independent offers and both counts survive to
    resolution — and the effect half does not. W1G4's parts 1-5 are done; what
    is left is one part, and it is the hard one:

    **a target slot per clause, with the slot count fixed by the announcement.**
    "Destroy target artifact. For each additional {1}{R} you paid, destroy
    another target artifact." CR 601.2c fixes the number of targets when the
    spell is announced, so the spell wants 1 + n(R) + n(G) *distinct* artifact
    targets — a count that only CR 601.2b's payment, one step earlier, can
    supply. Four concrete pieces:

    1. **a ``min_targets``/``max_targets`` pair the picker derives from the
       announced payment**, where ``targeting.derive_cast_spec`` today derives
       both from the printed line alone;
    2. **a per-clause target slot in the resolution**, which is exactly what
       ``_refuse_unfused_distinctness`` refuses for want of: every handler but
       ``_fused_two_target_pump`` and ``target_bites_target`` resolves through
       ``_one_choice`` and would read the *first* chosen permanent for each
       clause, so three destroys would kill one artifact three times;
    3. **an index into that slot list for a ``for_each`` body**, since the loop
       repeats one instruction and ``_A_REPETITION`` deliberately binds nothing
       — the iteration would have to name "the i-th target of this spell";
    4. **a web cost picker for the announcement**, which W1G4 already recorded
       as missing for a different reason (an *offer* shape, "cast for {1}{R} or
       for {1}{R} plus {1}{R}?", where ``_cost_picker_spec`` models a mandatory
       cost). Without it a human can announce no payment at all.

    None of the four is a card hook: every one is a template. Recorded here as
    the assertions that will fail the day it lands, which is the point."""
    justice = set_pool("ALL")["Primitive Justice"]
    (cost,) = _w3g1_costs(justice)
    assert [(o.symbols, o.repeatable) for o in cost.optional_mana] == [
        ("{1}{R}", True), ("{1}{G}", True),
    ], "the cost half landed this round; the decline below is the effect half"
    assert not _w3g1_compile(justice).supported
