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


# --- W3G2: modes, counters and granted abilities ---
#
# Alliances prints three "An opponent chooses one —" spells (CR 700.2e) and two
# of them refer *back* to the chooser from inside the mode they chose:
# Misfortune's "each creature **that player** controls" and "deals 4 damage to
# **that player**", and Fatal Lore's "**That player** draws up to three cards".
# W2G4 built the head and the choice; what was missing was the seat those words
# name, which is not on any board — it comes into existence when the mode is
# chosen. `_resolve_opponent_mode_choice` freezes it under the same key a
# trigger's fire site freezes one, so `frozen_that_player_seat`, the damage
# recipient and the draw's seat all read one answer.

from engine import Game, PlayerState  # noqa: E402
from engine.models import CardDefinition, Permanent  # noqa: E402


def _w3g2_bear(name: str = "Bear") -> CardDefinition:
    """A vanilla 2/2, so a counter's effect on P/T is the whole observation."""
    return CardDefinition(
        name=name, mana_cost="{1}{G}", cmc=2.0, type_line="Creature — Bear",
        oracle_text="", power="2", toughness="2",
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear"},
    )


def _w3g2_duel(set_pool, card_name: str):
    """A duel with both seats interactive, two 2/2s each, the spell in hand.

    Both seats interactive on purpose: `opponent_mode_choice` is a
    ``default_at_arm`` kind, so a non-interactive chooser takes mode 0 before a
    test can name a mode — which is how a "mode 1" assertion silently tests
    mode 0.
    """
    p1 = PlayerState(name="P1", hand=[set_pool("ALL")[card_name]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    for seat, player in enumerate((p1, p2)):
        for index in range(2):
            game._put_permanent_onto_battlefield(
                seat,
                Permanent(card=_w3g2_bear(f"{player.name} Bear {index}")),
                None,
            )
    return game, p1, p2


def _w3g2_pt(game, player):
    return sorted(
        (perm.effective_power, perm.effective_toughness)
        for perm in game.controlled_by(player)
    )


def test_w3g2_misfortune_first_mode_grows_the_casters_board(set_pool):
    """CR 700.2e's kinder half. "Each creature **you** control" is the caster's
    own board, so the chooser's seat never enters it."""
    game, p1, p2 = _w3g2_duel(set_pool, "Misfortune")

    assert game.queue_from_hand(0, "Misfortune").supported
    assert game.confirm_opponent_mode_choice(1, 0)
    game._settle()

    assert _w3g2_pt(game, p1) == [(3, 3), (3, 3)]
    assert _w3g2_pt(game, p2) == [(2, 2), (2, 2)]
    assert (p1.life, p2.life) == (24, 20)


def test_w3g2_misfortune_second_mode_shrinks_the_choosers_board(set_pool):
    """The -1/-1 sweep and the damage both land on the seat that *chose*, and
    neither touches the caster's own board.

    This is the whole point of freezing the chooser. Read with the scope
    dropped, "each creature that player controls" is every creature in the
    game and the caster shrinks their own board; read with the seat guessed as
    the resolution's default opponent it is right in a duel by coincidence.
    """
    game, p1, p2 = _w3g2_duel(set_pool, "Misfortune")

    assert game.queue_from_hand(0, "Misfortune").supported
    assert game.confirm_opponent_mode_choice(1, 1)
    game._settle()

    assert _w3g2_pt(game, p1) == [(2, 2), (2, 2)]
    assert _w3g2_pt(game, p2) == [(1, 1), (1, 1)]
    assert (p1.life, p2.life) == (20, 16)


def test_w3g2_misfortune_freezes_the_chooser_rather_than_the_opposing_seat(set_pool):
    """The seat is recorded on the spell as the mode is chosen, not derived at
    resolution — which is what makes the phrase answerable with three players
    in the game, where "an opponent" is not "the opponent"."""
    from engine.grammar.lowering._events import EVENT_SUBJECT_PLAYER

    game, _p1, _p2 = _w3g2_duel(set_pool, "Misfortune")
    assert game.queue_from_hand(0, "Misfortune").supported

    assert game.confirm_opponent_mode_choice(1, 1)

    assert game.stack[-1].trigger_context[EVENT_SUBJECT_PLAYER] == 1
