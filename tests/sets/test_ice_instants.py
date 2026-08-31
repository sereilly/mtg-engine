"""Ice Age (ICE) instant cards.

ICE **ships** (SET_PLAYBOOK.md Phase 4 moved it from ``measured`` to ``sets``).
It was measured while these tests were written, and the pool resolves through
``set_pool("ICE")`` either way — that fixture is about which cards a test may
name, not about which a player may deck. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_creature_card, _nosick


# --- Round 10: sweeps and grants over a set the sentence names ---
def _combat(game: Game, attacker_indices: list[int]) -> None:
    """Advance seat 0's turn to the declare-blockers step with those attackers."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"
def test_stampede_reaches_attacking_creatures_the_caster_does_not_control(set_pool):
    """"Attacking creatures get +1/+0 and gain trample until end of turn."

    Both halves of the sentence name the same set, and only the P/T half read
    it: the keyword half refused the narrowing, so supporting the card without
    this would have pumped every attacker and given trample to none of them.
    The set is also not the caster's board — Stampede is castable by the
    defending player, which is what `every_seat` carries.
    """
    pool = set_pool("ICE")
    attacker = Permanent(card=pool["Balduvian Bears"])
    home = Permanent(card=pool["Balduvian Barbarians"])
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[home], hand=[pool["Stampede"]], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    _combat(game, [0])
    game.cast_from_hand(1, "Stampede")
    game._settle()

    assert attacker.has_keyword("trample"), "the opponent's attacker is in the set"
    assert not home.has_keyword("trample"), "a creature that is not attacking is not"
# --- Round 12: a counted amount, and a name that is also a creature type ---
def test_songs_of_the_damned_counts_a_graveyard(set_pool):
    """"Add {B} for each creature card **in your graveyard**."

    The mana multiplier was hardwired to the battlefield. The evaluator behind
    it already reads a zone off its spec; what was missing was carrying the one
    the phrase named — and a card in a zone has no computed characteristics
    (CR 613.1), so the narrowing is held to what a *card* can answer.
    """
    pool = set_pool("ICE")
    p1 = PlayerState(
        name="P1", hand=[pool["Songs of the Damned"]],
        graveyard=[pool["Balduvian Bears"], pool["Moor Fiend"], pool["Icequake"]],
        life=20,
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Songs of the Damned")
    game._settle()

    # Two creature cards; Icequake is a sorcery and does not count.
    assert p1.mana_pool["B"] == 2
# --- Round 20: a possessive back-reference written with its noun ---
def test_word_of_blasting_burns_for_the_walls_mana_value(set_pool):
    """"Destroy target Wall. It can't be regenerated. This spell deals damage
    equal to **that Wall's** mana value to **the Wall's** controller."

    Three readers had to widen for one card, and each was narrowed by a word
    rather than by a meaning: the amount read only "its mana value" (a pronoun),
    the recipient read only "that/this <card type>'s controller" (a Wall is a
    *subtype*), and the damage handler had no branch for the scratchpad channel
    at all — so the lowering was already emitting `amount_from` and nothing read
    it, which would have dealt 0 on a card reporting supported.
    """
    pool = set_pool("ICE")
    wall = Permanent(card=pool["Glacial Wall"])  # mana value 3
    p1 = PlayerState(name="P1", hand=[pool["Word of Blasting"]], life=20)
    p2 = PlayerState(name="P2", battlefield=[wall], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(
        0, "Word of Blasting", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert wall not in p2.battlefield
    assert p2.life == 17
# --- Round 22: "if it's <colour>" — the colour is payload, the pronoun is not ---
def _blast_board(set_pool, blast: str, spell: str, **cast):
    """Seat 0 holding *blast*, with seat 1's *spell* already on the stack."""
    pool = set_pool("ICE")
    library = [pool["Balduvian Bears"] for _ in range(5)]
    p1 = PlayerState(name="P1", hand=[pool[blast]], library=library, life=20)
    p2 = PlayerState(name="P2", hand=[pool[spell]], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.queue_from_hand(1, spell, **cast)
    assert [item.card.name for item in game.stack] == [spell]
    return game
def test_hydroblast_counters_a_red_spell(set_pool):
    """"Counter target spell **if it's red**." CR 608.2c: the colour is read
    while the instruction is followed, so the clause lowers to an `if_then`
    over the ordinary counter rather than to a colour narrowing on it."""
    game = _blast_board(set_pool, "Hydroblast", "Incinerate", target_player_index=0)

    game.cast_from_hand(0, "Hydroblast", mode_index=0, target_stack_index=0)
    game.resolve_stack()
    game._settle()

    assert game.players[0].life == 20, "the burn never resolved"
    assert "Incinerate" in [c.name for c in game.players[1].graveyard]
def test_hydroblast_may_target_a_spell_it_cannot_counter(set_pool):
    """The half that separates this from "counter target **red** spell".

    "Target spell" is the whole of the printed restriction (CR 608.2b), so a
    blue spell is a legal target and Hydroblast simply does nothing to it —
    where a colour narrowing on the counter would have refused the cast and
    narrowed the picker. Lowering it as `counter_top_stack_spell` with a
    `color_filter` would have been the smaller diff and the wrong card.
    """
    game = _blast_board(
        set_pool, "Hydroblast", "Ray of Erasure", target_player_index=0
    )

    game.cast_from_hand(0, "Hydroblast", mode_index=0, target_stack_index=0)
    game.resolve_stack()
    game._settle()

    assert not game.stack
    # The blue spell resolved: its mill took a card off the library it named.
    assert len(game.players[0].library) == 4
    assert "Balduvian Bears" in [c.name for c in game.players[0].graveyard]
    assert "Ray of Erasure" in [c.name for c in game.players[1].graveyard]
def test_pyroblast_destroys_a_blue_permanent_and_spares_the_rest(set_pool):
    """The second mode, and the colour read off a *permanent* rather than a
    spell. Same printed condition, different half of the resolution context —
    which is why the referent is bound at lowering, from the effect beside it,
    rather than guessed at resolution."""
    pool = set_pool("ICE")

    def _destroys(victim: str) -> bool:
        target = Permanent(card=pool[victim])
        p1 = PlayerState(name="P1", hand=[pool["Pyroblast"]], life=20)
        p2 = PlayerState(name="P2", battlefield=[target], life=20)
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = False
        game.cast_from_hand(
            0, "Pyroblast", mode_index=1,
            target_player_index=1, target_permanent_index=0,
        )
        game._settle()
        return target not in p2.battlefield

    assert _destroys("Illusionary Wall")      # blue
    assert not _destroys("Balduvian Bears")   # red
def test_the_two_blasts_differ_only_by_the_colour_in_the_payload(set_pool):
    """One production, two cards. The colour is a payload symbol — the spelling
    every filter and colour accessor in the engine already uses — so a third
    card printing "if it's white" needs no parser change at all."""
    pool = set_pool("ICE")
    conditions = {}
    for name in ("Hydroblast", "Pyroblast"):
        program = compile_card_oracle(pool[name])
        conditions[name] = [
            mode.instruction.payload["condition"] for mode in program.modes
        ]

    assert conditions["Hydroblast"] == [
        {"kind": "target_is_color", "color": "R", "negated": False, "target": "spell"},
        {"kind": "target_is_color", "color": "R", "negated": False, "target": "permanent"},
    ]
    assert conditions["Pyroblast"] == [
        {"kind": "target_is_color", "color": "U", "negated": False, "target": "spell"},
        {"kind": "target_is_color", "color": "U", "negated": False, "target": "permanent"},
    ]
# --- Round 25: a borrowed permanent, and what the sentences after it name ---
def _borrow(set_pool, spell: str, victim: str, tapped: bool = True):
    """Cast *spell* on seat 1's *victim*, and return the game and the permanent."""
    pool = set_pool("ICE")
    borrowed = Permanent(card=pool[victim])
    borrowed.tapped = tapped
    hand = [pool[spell]] if spell == "Ray of Command" else []
    battlefield = [] if spell == "Ray of Command" else [
        _nosick(Permanent(card=pool[spell]))
    ]
    game = Game(players=[
        PlayerState(name="P1", hand=hand, battlefield=battlefield, life=20),
        PlayerState(name="P2", battlefield=[borrowed], life=20),
    ])
    game.enforce_mana_costs = False
    if spell == "Ray of Command":
        game.cast_from_hand(
            0, spell, target_player_index=1, target_permanent_index=0
        )
    else:
        game.activate_permanent_ability(
            0, spell, 0, target_player_index=1, target_permanent_index=0
        )
    game._settle()
    return game, borrowed
def test_ray_of_command_untaps_steals_and_hastes_in_one_resolution(set_pool):
    """"Untap target creature an opponent controls and gain control of **it**
    until end of turn. That creature gains haste until end of turn."

    The pronoun and the repeated noun are one referent (idiom 20): "gain
    control of **it**" was refused where Disharmony's "gain control of **that
    creature**" was admitted, because a bare "it" parses as the ability's own
    source and that default was read as a narrowing.
    """
    game, borrowed = _borrow(set_pool, "Ray of Command", "Balduvian Bears")

    assert not borrowed.tapped
    assert game.controller_index_of(borrowed) == 0
    assert borrowed.has_keyword("haste"), (
        "the sentence after the steal is about the creature the steal moved"
    )
def test_the_haste_grant_after_a_bound_steal_finds_the_creature(set_pool):
    """The defect: two branches of one handler left different things behind.

    `gain_control_until_eot` rescopes the resolution's target seat when it
    takes a *chosen* target — the sentences after it are about a creature that
    is now on another battlefield — and its **bound** branch did not. So under
    the pronoun spelling the announced id was still scoped to the seat the
    creature had left: it resolved to nothing, and the grant that followed
    logged "no valid creature target" while the card compiled clean.
    """
    game, borrowed = _borrow(set_pool, "Ray of Command", "Balduvian Bears")

    assert "no valid creature target" not in " ".join(game.log)
    assert borrowed.has_keyword("haste")
def test_ray_of_command_returns_the_creature_tapped(set_pool):
    """"When you lose control of the creature, tap it." CR 603.7's delayed
    trigger, and the cleanup that ends an until-end-of-turn control change is
    the one place control is lost — so that is where it fires."""
    game, borrowed = _borrow(set_pool, "Ray of Command", "Balduvian Bears")
    assert not borrowed.tapped

    game.resolve_cleanup_step(0)

    assert game.controller_index_of(borrowed) == 1, "the loan ended"
    assert borrowed.tapped, "and the creature came back tapped"
    assert not borrowed.has_keyword("haste")
# --- Round 28: N cards from a hand back onto the top of a library ---
def _casting(set_pool, spell: str, *, hand=(), library=(), opponent_hand=(), opponent_library=()):
    """The caster holding *spell*, with both seats' hidden zones set."""
    pool = set_pool("ICE")
    from engine.card_loader import load_catalog

    shipped = {card.name: card for card in load_catalog()}

    def card(name):
        return pool.get(name) or shipped[name]

    p1 = PlayerState(
        name="P1", hand=[card(spell), *[card(n) for n in hand]],
        library=[card(n) for n in library], life=20,
    )
    p2 = PlayerState(
        name="P2", hand=[card(n) for n in opponent_hand],
        library=[card(n) for n in opponent_library], life=20,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = {0, 1}
    return game, p1, p2
def test_brainstorm_draws_three_then_asks_for_two_back(set_pool):
    """"Draw three cards, then put two cards from your hand on top of your
    library in any order."

    Two steps of one resolution: the prompt is armed *after* the draw, so the
    cards just drawn are among the ones that may go back — which is the whole
    card.
    """
    game, p1, _p2 = _casting(
        set_pool, "Brainstorm",
        hand=["Balduvian Bears"],
        library=["Icy Manipulator", "Dark Banishing", "Hoar Shade", "Snow Fortress"],
    )

    result = game.cast_from_hand(0, "Brainstorm")
    game._settle()

    assert result.supported, result.details
    assert len(p1.hand) == 4, "the Bear plus the three drawn"
    choice = game.pending_choice_of("hand_to_library", 0)
    assert choice is not None and choice.data["count"] == 2
    assert game.waiting_prompt(), "the resolution waits on the answer (CR 608.2)"

    names = [c.name for c in p1.hand]
    game.confirm_hand_to_library(
        0, [names.index("Hoar Shade"), names.index("Balduvian Bears")]
    )
    game._settle()

    assert len(p1.hand) == 2
    assert [c.name for c in p1.library[:2]] == ["Hoar Shade", "Balduvian Bears"], (
        "the first card named goes on top"
    )
def test_putting_a_card_back_is_not_a_discard(set_pool):
    """CR 701.9a: discarding moves a card to a **graveyard**. Neither card here
    does that, so neither may reach the discard prompt — reusing it with its
    Library of Leng destination flag would have fired every "whenever you
    discard" ability in the game on a Brainstorm."""
    game, p1, _p2 = _casting(
        set_pool, "Brainstorm",
        hand=["Balduvian Bears"],
        library=["Icy Manipulator", "Dark Banishing", "Hoar Shade", "Snow Fortress"],
    )

    game.cast_from_hand(0, "Brainstorm")
    game._settle()

    assert game.pending_choice_of("discard", 0) is None
    names = [c.name for c in p1.hand]
    game.confirm_hand_to_library(0, [names.index("Hoar Shade"), 0])
    game._settle()

    assert p1.graveyard == [] or all(
        c.name == "Brainstorm" for c in p1.graveyard
    ), "only the spell itself went to the graveyard"
# --- Round 30: a card counted supported that did nothing it said ---
def test_panic_stops_the_creature_it_targets_from_blocking(set_pool):
    """"Target creature can't block this turn."

    Panic was already counted **supported**: its cast restriction and its
    delayed draw compiled, and the sentence that is the whole point of the card
    produced no instruction at all. Nothing in the repo could see that, which is
    what this round's instrument change fixes; this is the card it found first.
    """
    pool = set_pool("ICE")
    attacker = Permanent(card=pool["Balduvian Bears"])
    blocker = Permanent(card=pool["Hoar Shade"])
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[attacker], hand=[pool["Panic"]], life=20),
            PlayerState(name="P2", battlefield=[blocker], life=20),
        ]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game._sync_control()
    _nosick(attacker)
    _nosick(blocker)

    ok, message = game.declare_attackers(0, [0])
    assert ok, message

    result = game.cast_from_hand(
        0, "Panic", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    assert result.supported, result.details

    game.current_step = "declare_blockers"
    blocked, message = game.declare_blockers(1, {0: 0})

    assert not blocked, "the creature Panic named cannot block"
def test_the_targeted_restriction_is_not_the_blanket_one(set_pool):
    """"Target creature can't block this turn" (Panic) and "Creatures without
    flying can't block this turn" (Destructive Tampering) are one printed
    sentence over two subjects, and two effects: one marks the permanent the
    spell chose, the other arms a board-wide filter.

    Folding them would make Panic reach every creature its noun phrase
    describes — which, on "target creature", is all of them.
    """
    from engine.grammar import compile_line

    targeted = compile_line("Target creature can't block this turn.")
    blanket = compile_line("Creatures without flying can't block this turn.")

    assert targeted.instructions[0].kind == "target_cant_block_until_eot"
    assert "targets" in targeted.instructions[0].payload
    assert blanket.instructions[0].kind == "cant_block_until_eot"
    assert "filter" in blanket.instructions[0].payload


# --- W1G3: mana, additional costs, cost restrictions ---
def _w1g3_cast_board(set_pool, spell, mine=(), theirs=()):
    """Seat 0 holding *spell*, with those ICE permanents on each battlefield."""
    pool = set_pool("ICE")
    ours = [Permanent(card=pool[n]) for n in mine]
    yours = [Permanent(card=pool[n]) for n in theirs]
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=ours, hand=[pool[spell]], life=20),
            PlayerState(name="P2", battlefield=yours, life=20),
        ]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    for perm in ours + yours:
        _nosick(perm)
    return game, ours, yours


def test_w1g3_burnt_offering_pays_a_creature_for_its_mana_value_in_mana(set_pool):
    """"As an additional cost to cast this spell, sacrifice a creature." /
    "Add X mana in any combination of {B} and/or {R}, where X is the sacrificed
    creature's mana value."

    Two pieces meeting. The cost is CR 601.2b's, charged by ``cast_costs`` while
    the spell is announced; X is read back off what it ate (CR 608.2h), because
    by resolution the creature is a card in a graveyard. Glacial Wall's mana
    value is 3, so three mana come out — never one, and never zero.
    """
    game, ours, _ = _w1g3_cast_board(
        set_pool, "Burnt Offering", mine=["Glacial Wall"]
    )
    wall = ours[0]

    game.cast_from_hand(0, "Burnt Offering", cost_permanent_index=0)
    game._settle()

    assert wall not in game.players[0].battlefield, "the additional cost was paid"
    pool = game.players[0].mana_pool
    assert pool["B"] + pool["R"] == 3, pool


def test_w1g3_burnt_offering_reads_the_mana_value_of_the_creature_it_ate(set_pool):
    """The number is the sacrificed creature's, not a constant. A 2-drop pays
    two mana where the 3-drop above paid three — which is what makes the
    where-clause a reference rather than a printed digit."""
    game, ours, _ = _w1g3_cast_board(
        set_pool, "Burnt Offering", mine=["Balduvian Bears"]  # mana value 2
    )

    game.cast_from_hand(0, "Burnt Offering", cost_permanent_index=0)
    game._settle()

    pool = game.players[0].mana_pool
    assert pool["B"] + pool["R"] == 2, pool


def test_w1g3_essence_vortex_destroys_when_the_controller_declines(set_pool):
    """"Destroy target creature unless its controller pays life equal to its
    toughness. A creature destroyed this way can't be regenerated."

    The payer is read off the *targeted permanent* through the control seam —
    not off ``context.target``, which for a spell aimed at a creature is not a
    player at all. Declining runs the penalty, and the penalty carries the
    no-regeneration rider the trailing sentence prints.
    """
    game, _, theirs = _w1g3_cast_board(
        set_pool, "Essence Vortex", theirs=["Glacial Wall"]  # 0/7
    )
    wall = theirs[0]
    game.interactive_seats = {1}

    game.cast_from_hand(
        0, "Essence Vortex", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    offer = game.pending_choice_of("optional_pay")
    assert offer is not None, "the creature's controller was never asked"
    assert offer.player_index == 1
    assert offer.data["life_cost"] == 7, "life equal to its toughness"

    game.confirm_optional_pay(1, accept=False)
    game._settle()

    assert wall not in game.players[1].battlefield
    assert game.players[1].life == 20


def test_w1g3_essence_vortex_spares_a_creature_whose_controller_pays(set_pool):
    """The other branch, and the one that proves the offer is real: paying the
    toughness in life keeps the creature. Without it the "unless" clause is a
    rider nobody charges and the spell is unconditional removal."""
    game, _, theirs = _w1g3_cast_board(
        set_pool, "Essence Vortex", theirs=["Glacial Wall"]
    )
    wall = theirs[0]
    game.interactive_seats = {1}

    game.cast_from_hand(
        0, "Essence Vortex", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    game.confirm_optional_pay(1, accept=True)
    game._settle()

    assert wall in game.players[1].battlefield
    assert game.players[1].life == 13


def test_w1g3_essence_vortex_reads_the_toughness_it_finds_at_resolution(set_pool):
    """CR 613 makes toughness computed, so the number is taken when the offer is
    made rather than when the spell was announced. A 2/2 asks for two."""
    game, _, theirs = _w1g3_cast_board(
        set_pool, "Essence Vortex", theirs=["Balduvian Bears"]  # 2/2
    )
    game.interactive_seats = {1}

    game.cast_from_hand(
        0, "Essence Vortex", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert game.pending_choice_of("optional_pay").data["life_cost"] == 2


def test_w1g3_essence_vortex_offers_the_creature_as_a_cast_target(set_pool):
    """The whole spell sits on the offer's *declined* branch, and CR 601.2c
    picks its target as the spell is announced — before anybody is asked to pay.
    A picker that read only the accept branch left this spell with no prompt and
    the destruction pointed at nothing."""
    from engine.targeting import derive_cast_spec

    pool = set_pool("ICE")
    card = pool["Essence Vortex"]

    assert derive_cast_spec(card, compile_card_oracle(card)) == {"kind": "creature"}


# --- W1G3 (cont.): the declined instant, now landed ---
def test_w1g3_spoils_of_evil_counts_a_chosen_graveyard(set_pool):
    """"For each artifact or creature card in target opponent's graveyard, add
    {C} and you gain 1 life." (W3G3 - the refusal this test used to pin.)

    W1G3 named five pieces and W2 corrected the brief on the fourth: this is a
    **count**, not a loop. Two mana and two life is one addition and one gain,
    not two of each, and the pool already reads the multiplier in the trailing
    position ("Add {G} for each Forest you control") - so the leading spelling
    is a distribution onto the same ``per_each`` field rather than an
    ``ast.ForEach`` nothing could walk.

    What was really missing: the noun parser's "in **target opponent's**
    graveyard", a leading production that distributes the count, the two
    lowerings' insistence on the caster's own zone, and a targets description so
    the picker asks for the opponent.
    """
    program = compile_card_oracle(set_pool("ICE")["Spoils of Evil"])
    assert program.supported

    (sequence,) = [i for i in program.instructions if i.kind == "sequence"]
    add_mana, gain_life = sequence.payload["steps"]
    counted = {"zone": "graveyard", "owner": "target_opponent",
               "filter": {"type_filter": ["artifact", "creature"]}}
    assert add_mana.payload["per_each"] == counted
    assert gain_life.payload["per_each"] == counted,         "one sentence, one count - two readings of it would be two answers"


def test_spoils_of_evil_pays_out_the_count_and_asks_for_an_opponent(set_pool):
    """CR 115.4: "target opponent" never names the caster's own seat."""
    from engine.targeting import derive_cast_spec

    pool = set_pool("ICE")
    lea = set_pool("LEA")
    spoils = pool["Spoils of Evil"]
    assert derive_cast_spec(spoils, compile_card_oracle(spoils)) == {
        "kind": "player", "opponents_only": True,
    }

    p0 = PlayerState(name="P0", hand=[spoils], life=20)
    p1 = PlayerState(name="P1", life=20, graveyard=[
        pool["Balduvian Bears"], lea["Black Lotus"], lea["Mountain"],
        pool["Tor Giant"],
    ])
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.cast_from_hand(0, "Spoils of Evil", target_player_index=1)
    assert result.supported, result.details
    game._settle()

    assert p0.life == 23, "three artifact-or-creature cards; the Mountain is neither"
    assert p0.mana_pool["C"] == 3


def test_an_empty_graveyard_is_a_real_answer(set_pool):
    """"For each" of nothing is nothing - the spell resolves and pays out zero,
    which is what makes the count above a count rather than a fixed 1."""
    pool = set_pool("ICE")
    p0 = PlayerState(name="P0", hand=[pool["Spoils of Evil"]], life=20)
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.cast_from_hand(0, "Spoils of Evil", target_player_index=1).supported
    game._settle()

    assert p0.life == 20 and p0.mana_pool["C"] == 0


def test_a_leading_count_over_an_effect_that_cannot_carry_it_refuses():
    """A count silently dropped is a card that adds one mana where it should add
    five, so a statement with no ``per_each`` to fold it onto takes the line
    down rather than resolving flat."""
    from engine.grammar import compile_line

    assert compile_line(
        "For each artifact card in target opponent's graveyard, add {C}."
    ).parsed
    refused = compile_line(
        "For each artifact card in target opponent's graveyard, draw a card."
    )
    assert not refused.parsed
    assert "leading count" in (refused.parse_error or "")
# --- end W1G3 ---
# --- W1G2: combat relations and end of combat ---
def _w1g2_venomous_board(set_pool, target_seat: int, target_index: int):
    """P1 attacks with two; P2 has a blocker. Venomous Breath is cast by P2."""
    pool = set_pool("ICE")
    first = _nosick(Permanent(card=pool["Tor Giant"]))
    second = _nosick(Permanent(card=pool["Balduvian Bears"]))
    blocker = _nosick(Permanent(card=pool["Glacial Wall"]))
    p1 = PlayerState(name="P1", battlefield=[first, second], life=20)
    p2 = PlayerState(
        name="P2", battlefield=[blocker], life=20,
        hand=[pool["Venomous Breath"]],
    )
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        1, "Venomous Breath",
        target_player_index=target_seat, target_permanent_index=target_index,
    )
    assert result.supported, result.details
    game._settle()
    return game, p1, p2, first, second, blocker


def _w1g2_one_combat(game: Game, attackers: list[int], blocks: dict[int, int]) -> None:
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, attackers)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    ok, msg = game.declare_blockers(1, blocks)
    assert ok, msg
    game.advance_combat_phase()  # combat damage
    game.end_combat(step_already_started=True)
    game._settle()


def test_venomous_breath_arms_a_two_way_relation_not_a_board_wipe(set_pool):
    """"Destroy all creatures that blocked or were blocked by it this turn."

    The relation is the whole sentence: dropped, the delayed ability would
    destroy every creature on the battlefield.
    """
    program = compile_card_oracle(set_pool("ICE")["Venomous Breath"])

    assert program.supported
    steps = program.instructions[0].payload["steps"]
    assert steps[0].kind == "choose_target_permanent"
    delayed = steps[1].payload
    assert delayed["event"] == "next_end_of_combat"
    assert delayed["binds_target"] is True
    assert delayed["instruction"].kind == "destroy_all_matching"
    assert delayed["instruction"].payload["in_combat_with_bound_object"] is True
    # Not the one-way key Glyph of Doom carries — the sets differ.
    assert "blocked_by_bound_object" not in delayed["instruction"].payload


def test_venomous_breath_kills_the_creatures_that_blocked_its_target(set_pool):
    """The named creature is an attacker, so the sentence names its blockers."""
    game, p1, p2, first, _second, blocker = _w1g2_venomous_board(set_pool, 0, 0)

    _w1g2_one_combat(game, [0, 1], {0: 0})

    assert not any(p is blocker for p in p2.battlefield)
    assert any(c.name == "Glacial Wall" for c in p2.graveyard)
    assert any(p is first for p in p1.battlefield), (
        "the named creature itself stood opposite nobody, so it is not swept"
    )


def test_venomous_breath_spares_the_creatures_that_never_met_its_target(set_pool):
    """The other attacker was in the same combat and is not in the relation."""
    game, p1, _p2, _first, second, _blocker = _w1g2_venomous_board(set_pool, 0, 0)

    _w1g2_one_combat(game, [0, 1], {0: 0})

    assert any(p is second for p in p1.battlefield), "an unblocked attacker lives"


def test_venomous_breath_reads_the_relation_after_its_target_has_died(set_pool):
    """The named creature — an attacker — dies in the very combat the sentence
    is about, and its blocker is still destroyed."""
    pool = set_pool("ICE")
    doomed = _nosick(Permanent(card=pool["Balduvian Bears"]))
    bystander = _nosick(Permanent(card=pool["Brown Ouphe"]))
    killer = _nosick(Permanent(card=pool["Tor Giant"]))
    p1 = PlayerState(name="P1", battlefield=[doomed, bystander], life=20)
    p2 = PlayerState(
        name="P2", battlefield=[killer], life=20, hand=[pool["Venomous Breath"]],
    )
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        1, "Venomous Breath", target_player_index=0, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    _w1g2_one_combat(game, [0, 1], {0: 0})

    assert not any(p is doomed for p in p1.battlefield), "3 damage kills the 2/2"
    assert not any(p is killer for p in p2.battlefield), (
        "the blocker is destroyed even though what it blocked is already gone"
    )
    assert any(p is bystander for p in p1.battlefield)


def test_venomous_breath_names_the_attackers_a_dead_blocker_blocked(set_pool):
    """The other half of the relation, read after the bound creature is gone.

    "Creatures that were blocked by it" is a record kept on *it* — which by end
    of combat is a card in a graveyard, since a blocker chump-blocking is the
    ordinary way this card is played. The block is therefore written from both
    ends when it is declared, and this sweep reads the attacker's copy.
    """
    pool = set_pool("ICE")
    attacker = _nosick(Permanent(card=pool["Tor Giant"]))
    bystander = _nosick(Permanent(card=pool["Brown Ouphe"]))
    chump = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[attacker, bystander], life=20)
    p2 = PlayerState(
        name="P2", battlefield=[chump], life=20, hand=[pool["Venomous Breath"]],
    )
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        1, "Venomous Breath", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    _w1g2_one_combat(game, [0, 1], {0: 0})

    assert not any(p is chump for p in p2.battlefield), "3 damage kills the 2/2"
    assert not any(p is attacker for p in p1.battlefield), (
        "the creature the dead blocker blocked is still named by the sweep"
    )
    assert any(p is bystander for p in p1.battlefield)


def test_venomous_breath_out_of_combat_destroys_nothing(set_pool):
    """No block, no relation — and above all no board wipe."""
    game, p1, p2, first, second, blocker = _w1g2_venomous_board(set_pool, 0, 0)

    _w1g2_one_combat(game, [0, 1], {})

    assert any(p is blocker for p in p2.battlefield)
    assert any(p is first for p in p1.battlefield)
    assert any(p is second for p in p1.battlefield)
# --- end W1G2 ---
# --- W1G1: prevention and damage shields ---
def _w1g1_boon(set_pool):
    """Sacred Boon cast on its caster's own Bears."""
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(
        name="P0", battlefield=[bears], hand=[pool["Sacred Boon"]], life=20
    )
    game = Game(players=[p0, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = False
    result = game.cast_from_hand(
        0, "Sacred Boon", target_player_index=0, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()
    return game, bears


def test_sacred_boon_shields_three_and_counts_what_it_prevented(set_pool):
    """"Prevent the next 3 damage that would be dealt to target creature this
    turn. At the beginning of the next end step, put a +0/+1 counter on that
    creature for each 1 damage prevented this way."

    Two sentences and one shield: the counters are placed at the end step
    because the number does not exist before then — CR 615.5's "prevented this
    way" goes on accumulating for the rest of the turn.
    """
    game, bears = _w1g1_boon(set_pool)
    assert bears.damage_prevention_pool == 3

    game._mark_damage_on_permanent(bears, 2)
    assert bears.damage_marked == 0
    assert bears.damage_prevention_pool == 1

    game.resolve_end_step(0)
    game._settle()

    assert bears.toughness_bonus == 2
    assert bears.power_bonus == 0, "a +0/+1 counter is not a +1/+1 counter"


def test_sacred_boon_counts_every_event_not_just_the_first(set_pool):
    """The total is the shield's, so two damage events this turn add up — and a
    shield spent to nothing still carries the number it absorbed."""
    game, bears = _w1g1_boon(set_pool)

    game._mark_damage_on_permanent(bears, 1)
    game._mark_damage_on_permanent(bears, 3)

    assert bears.damage_marked == 1, "one point got through once the pool ran out"
    game.resolve_end_step(0)
    game._settle()

    assert bears.toughness_bonus == 3, "one point then two"


def test_sacred_boon_places_nothing_when_nothing_was_prevented(set_pool):
    """"For each 1 damage prevented" over zero points is zero counters, which is
    the card rather than a failure."""
    game, bears = _w1g1_boon(set_pool)

    game.resolve_end_step(0)
    game._settle()

    assert bears.toughness_bonus == 0
# --- end W1G1 ---


# --- W1G4: library, hand and graveyard ---
def test_whiteout_strips_flying_from_every_creature_on_both_boards(set_pool):
    """"All creatures lose flying until end of turn."

    The subject names no controller, so it is every seat's board — the team
    *grant* beside it refuses that reading, and a removal scoped to the caster
    would leave the half of the board the card names still flying.
    """
    pool = set_pool("ICE")
    mine = Permanent(card=pool["Sabretooth Tiger"])
    theirs = Permanent(card=pool["Kjeldoran Skyknight"])
    assert theirs.has_keyword("flying"), "the fixture creature flies to begin with"
    p1 = PlayerState(name="P1", battlefield=[mine], hand=[pool["Whiteout"]], life=20)
    p2 = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Whiteout")
    game._settle()

    assert not theirs.has_keyword("flying"), "the opponent's flier is in the set"


def test_whiteout_returns_itself_from_the_graveyard_for_a_snow_land(set_pool):
    """"Sacrifice a snow land: Return this card from your graveyard to your
    hand." — CR 113.6m: the ability functions only from the graveyard, so the
    cost is paid and the card comes back to hand.
    """
    pool = set_pool("ICE")
    snow = Permanent(card=pool["Snow-Covered Forest"])
    p1 = PlayerState(name="P1", battlefield=[snow], graveyard=[pool["Whiteout"]], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()

    result = game.activate_from_graveyard(0, "Whiteout")
    assert result.supported, result.details
    game._settle()

    assert [card.name for card in p1.hand] == ["Whiteout"]
    assert p1.graveyard[-1].name == "Snow-Covered Forest", "the land paid the cost"
    assert not any(perm.card.name == "Snow-Covered Forest" for perm in p1.battlefield)


def test_whiteouts_graveyard_ability_needs_a_snow_land_to_sacrifice(set_pool):
    """CR 602.5c: an unpayable cost makes the ability unactivatable, and
    nothing is spent trying. An ordinary Forest is not a snow land."""
    pool = set_pool("ICE")
    plain_forest = Permanent(card=pool["Forest"])
    p1 = PlayerState(
        name="P1", battlefield=[plain_forest], graveyard=[pool["Whiteout"]], life=20
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game._sync_control()

    result = game.activate_from_graveyard(0, "Whiteout")

    assert not result.supported
    assert p1.hand == []
    assert any(perm.card.name == "Forest" for perm in p1.battlefield)
# --- end W1G4 ---


# --- W2G3: combat restrictions and requirements ---
def test_battle_cry_arms_a_delayed_block_trigger(set_pool):
    """"Whenever a creature blocks this turn, it gets +0/+1 until end of turn."

    The card was already `supported` on its *first* line, so this sentence was
    claimed by nothing and did nothing — the failure `parse_coverage.py`
    reports and a promotion gates on. It is the same printed shape Basri Ket's
    "whenever one or more creatures attack this turn" prints, so it is a word in
    that table rather than a second reader.
    """
    program = compile_card_oracle(set_pool("ICE")["Battle Cry"])

    assert program.supported
    kinds = [i.kind for i in program.instructions]
    assert "create_delayed_trigger" in kinds
    delayed = next(
        i for i in program.instructions if i.kind == "create_delayed_trigger"
    )
    assert delayed.payload["event"] == "creature_blocks"
    # CR 603.7b: "whenever ... this turn" keeps triggering for the turn.
    assert delayed.payload["once"] is False
    assert delayed.payload["duration"] == "end_of_turn"
    assert delayed.payload["instruction"].kind == "pump_self"


def _w2g3_battle_cry_board(set_pool):
    """Seat 0 attacking with two bears; seat 1 holding two and the spell."""
    pool = set_pool("ICE")
    attackers = [_nosick(Permanent(card=pool["Balduvian Bears"])) for _ in range(2)]
    blockers = [_nosick(Permanent(card=pool["Balduvian Bears"])) for _ in range(2)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=attackers, life=20),
        PlayerState(
            name="P2", battlefield=blockers, hand=[pool["Battle Cry"]], life=20
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, attackers, blockers


def test_battle_cry_toughens_each_creature_that_blocks_after_it_resolves(set_pool):
    """The ability fires per blocker (CR 509.1i) and keeps firing for the turn,
    so both blockers are 2/3 — and it reaches the *defender's* creatures even
    though a spell's own source is in a graveyard by then."""
    game, _attackers, blockers = _w2g3_battle_cry_board(set_pool)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], 1)[0]

    assert game.cast_from_hand(1, "Battle Cry").supported
    game._settle()

    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: 0, 1: 1})[0]
    game._settle()

    assert [b.effective_toughness for b in blockers] == [3, 3]
    assert [b.effective_power for b in blockers] == [2, 2]


def test_battle_cry_does_nothing_to_a_creature_that_did_not_block(set_pool):
    """The trigger is per blocking creature, not a board-wide anthem — a
    defender kept back is untouched."""
    game, attackers, blockers = _w2g3_battle_cry_board(set_pool)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], 1)[0]

    assert game.cast_from_hand(1, "Battle Cry").supported
    game._settle()

    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: 0})[0]
    game._settle()

    assert blockers[0].effective_toughness == 3
    assert blockers[1].effective_toughness == 2
    # Nor does it reach the attackers, which blocked nothing.
    assert [a.effective_toughness for a in attackers] == [2, 2]


def test_battle_cry_stops_at_the_end_of_its_turn(set_pool):
    """"This turn" is CR 603.7b's stated duration: the ability is swept with
    the turn, so a block in the *next* combat gets nothing."""
    game, _attackers, blockers = _w2g3_battle_cry_board(set_pool)
    game.active_player_index = 0
    assert game.cast_from_hand(1, "Battle Cry").supported
    game._settle()
    assert len(game.delayed_triggers) == 1

    game.resolve_cleanup_step(0)

    assert game.delayed_triggers == []
# --- end W2G3 ---


# --- W2G5: mass effects and X-spells ---
def _w2g5_covenant_game(set_pool, *, life=20):
    """Seat 0 holds Fire Covenant; seat 1 has two creatures out."""
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    giant = Permanent(card=pool["Tor Giant"])
    p1 = PlayerState(name="P1", hand=[pool["Fire Covenant"]], life=life)
    p2 = PlayerState(name="P2", battlefield=[bears, giant], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    return pool, p1, p2, bears, giant, game


def test_w2g5_fire_covenant_charges_the_announced_x_in_life(set_pool):
    """"As an additional cost to cast this spell, pay X life."

    The clause was unread until this round: the card is `supported` on its
    damage line alone, so the cost was not deferred, it was never charged at
    all — X=2 dealt two damage and cost nothing. CR 601.2b announces X, CR
    601.2h charges the cost, in that order.
    """
    pool, p1, p2, bears, giant, game = _w2g5_covenant_game(set_pool)

    result = game.cast_from_hand(
        0, "Fire Covenant", x_value=2, divided_targets=[(1, 0), (1, 1)]
    )
    game._settle()

    assert result.supported, result.details
    assert p1.life == 18, "X life, not the printed 0"
    assert bears.damage_marked == 1
    assert giant.damage_marked == 1


def test_w2g5_fire_covenant_cannot_be_cast_for_more_life_than_you_have(set_pool):
    """CR 118.4 with CR 601.2h: an unpayable cost is an uncastable spell, not a
    free one. Nothing is spent finding out, and the card stays in hand."""
    pool, p1, p2, bears, giant, game = _w2g5_covenant_game(set_pool, life=3)

    result = game.cast_from_hand(
        0, "Fire Covenant", x_value=5, divided_targets=[(1, 0)]
    )
    game._settle()

    assert not result.supported
    assert p1.life == 3
    assert [card.name for card in p1.hand] == ["Fire Covenant"]
    assert bears.damage_marked == 0
# --- end W2G5 ---


# --- W2G4: Auras and attachments ---
def _undoing_game(pool, battlefield, second_seat=None):
    p1 = PlayerState(
        name="P1", battlefield=battlefield, life=20,
        hand=[pool["Word of Undoing"]],
    )
    p2 = PlayerState(name="P2", battlefield=second_seat or [], life=20)
    game = Game(players=[p1, p2])
    return game, p1, p2


def _cast_undoing(game, host):
    game.players[0].mana_pool["W"] = 1
    result = game.cast_from_hand(
        0, "Word of Undoing",
        target_player_index=game.controller_index_of(host),
        target_permanent_index=game.battlefield_index_of(host),
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return result


def test_word_of_undoing_returns_the_creature_and_only_the_white_auras(set_pool):
    """"Return target creature and all white Auras you own attached to it to
    their owners' hands."

    Three narrowings at once: *white* Auras, ones **you own**, and the ones on
    that creature. Regeneration is green, so it is left behind and CR 704.5m
    puts it in the graveyard — which is the trade the card is printed for.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    white = Permanent(card=pool["Armor of Faith"])
    green = Permanent(card=pool["Regeneration"])
    game, p1, _ = _undoing_game(pool, [bear, white, green])
    attach_aura(white, bear)
    attach_aura(green, bear)
    game._settle()

    assert _cast_undoing(game, bear).supported
    assert sorted(card.name for card in p1.hand) == [
        "Armor of Faith", "Balduvian Bears",
    ]
    assert [card.name for card in p1.graveyard] == [
        "Word of Undoing", "Regeneration",
    ]


def test_word_of_undoing_leaves_a_white_aura_on_another_creature_alone(set_pool):
    """"Attached to **it**" is the whole narrowing, and a sweep's dropped rider
    does not do less — it takes the board."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    other = Permanent(card=pool["Balduvian Bears"])
    on_bear = Permanent(card=pool["Armor of Faith"])
    elsewhere = Permanent(card=pool["Armor of Faith"])
    game, p1, _ = _undoing_game(pool, [bear, other, on_bear, elsewhere])
    attach_aura(on_bear, bear)
    attach_aura(elsewhere, other)
    game._settle()

    _cast_undoing(game, bear)

    assert elsewhere in list(game.controlled_by(game.players[0]))
    assert other in list(game.controlled_by(game.players[0]))
    assert sorted(card.name for card in p1.hand) == [
        "Armor of Faith", "Balduvian Bears",
    ]


def test_word_of_undoing_spares_an_aura_you_do_not_own(set_pool):
    """"Auras **you own**" — CR 108.3 ownership, not control. An opponent's
    white Aura on your creature is not yours to take back."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    theirs = Permanent(card=pool["Armor of Faith"])
    game, p1, p2 = _undoing_game(pool, [bear], second_seat=[theirs])
    attach_aura(theirs, bear)
    game._settle()

    _cast_undoing(game, bear)

    assert [card.name for card in p1.hand] == ["Balduvian Bears"]
    assert [card.name for card in p2.hand] == []
    assert [card.name for card in p2.graveyard] == ["Armor of Faith"]
# --- end W2G4 ---


# --- W3G3: X spells, multiple targets, damage sources ---
def _covenant_board(set_pool):
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])      # 2/2
    giant = Permanent(card=pool["Tor Giant"])            # 3/3
    p0 = PlayerState(name="P0", hand=[pool["Fire Covenant"]], life=20)
    p1 = PlayerState(name="P1", battlefield=[bears, giant], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p0, p1, bears, giant


def test_fire_covenant_divides_as_the_caster_chooses(set_pool):
    """"Fire Covenant deals X damage divided **as you choose** among any number
    of target creatures."

    ``DamageRiders.divided_evenly`` was set by the parser and read by nothing,
    so this and three other cards were played as ``damage // n`` — a 5-damage
    Covenant over two creatures dealt 2 and 2 where the card lets the caster
    deal 4 and 1.
    """
    game, _p0, _p1, bears, giant = _covenant_board(set_pool)

    result = game.cast_from_hand(
        0, "Fire Covenant", x_value=5,
        divided_targets=[(1, 0, 1), (1, 1, 4)],
    )
    assert result.supported, result.details
    game._settle()

    assert game.is_on_battlefield(bears), "1 damage on a 2/2"
    assert not game.is_on_battlefield(giant), "4 damage on a 3/3"


def test_the_even_split_would_have_answered_differently(set_pool):
    """The boundary the test above needs. The same X over the same two
    creatures, with no division announced, is 2 and 2 — the 3/3 lives and the
    2/2 dies, which is the opposite pair. Without this the assertion above
    would pass on an engine that ignored the announcement.
    """
    game, _p0, _p1, bears, giant = _covenant_board(set_pool)

    game.cast_from_hand(0, "Fire Covenant", x_value=5, divided_targets=[(1, 0), (1, 1)])
    game._settle()

    assert not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(giant)


def test_fire_covenant_offers_only_creatures(set_pool):
    """"…among any number of **target creatures**". The divided lowering
    returned before it ever read the printed noun, so the picker's seat loop
    offered both players' faces as legal Fire Covenant targets."""
    from engine.targeting import derive_cast_spec

    game, _p0, _p1, _bears, _giant = _covenant_board(set_pool)
    pool = set_pool("ICE")
    covenant = pool["Fire Covenant"]

    spec = derive_cast_spec(covenant, compile_card_oracle(covenant))
    assert spec["division"] == "chosen" and spec["creatures_only"]

    offered = game.cast_target_spec(0, covenant)["valid_targets"]
    assert all(option["kind"] == "permanent" for option in offered), offered
    assert sorted(option["name"] for option in offered) == [
        "Balduvian Bears", "Tor Giant",
    ]


def test_a_division_must_total_the_damage_and_give_each_target_one(set_pool):
    """CR 601.2d, checked at announcement (CR 601.2e) rather than at
    resolution — by resolution the mana is spent and the only answer left is to
    deal the wrong amount."""
    game, _p0, _p1, _bears, _giant = _covenant_board(set_pool)
    short = game.cast_from_hand(
        0, "Fire Covenant", x_value=5, divided_targets=[(1, 0, 1), (1, 1, 1)],
    )
    assert not short.supported and "601.2d" in short.details

    game, _p0, _p1, _bears, _giant = _covenant_board(set_pool)
    starved = game.cast_from_hand(
        0, "Fire Covenant", x_value=5, divided_targets=[(1, 0, 0), (1, 1, 5)],
    )
    assert not starved.supported and "at least 1" in starved.details


def test_meteor_shower_divides_x_plus_one(set_pool):
    """"X **plus 1** damage divided as you choose." The announcement is checked
    against what the spell will really deal, bonus included — a gate reading
    only ``amount`` would refuse the division the card allows."""
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", hand=[pool["Meteor Shower"]], life=20)
    p1 = PlayerState(name="P1", battlefield=[bears], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.cast_from_hand(
        0, "Meteor Shower", x_value=2, divided_targets=[(1, 0, 1), (1, None, 2)],
    )
    assert result.supported, result.details
    game._settle()

    assert p1.life == 18, "X=2 plus 1 is three points to divide, not two"
    assert game.is_on_battlefield(bears), "one of them went to the 2/2"

    # And the total really is the bonus: a division summing to X alone refuses.
    p0 = PlayerState(name="P0", hand=[pool["Meteor Shower"]], life=20)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool["Balduvian Bears"])])
    short = Game(players=[p0, p1])
    short.enforce_mana_costs = False
    short.start_turn(0)
    refused = short.cast_from_hand(
        0, "Meteor Shower", x_value=2, divided_targets=[(1, 0, 1), (1, None, 1)],
    )
    assert not refused.supported and "total 3" in refused.details
# --- end W3G3 ---


# --- W3G1: granted abilities in quotes ---
def _vitae_game(pool):
    """Seat 0 holding Touch of Vitae with a tapped Balduvian Bears in play."""
    bear = _nosick(Permanent(card=pool["Balduvian Bears"]))
    bear.tapped = True
    p1 = PlayerState(
        name="P1", battlefield=[bear], life=20,
        hand=[pool["Touch of Vitae"]],
    )
    p2 = PlayerState(name="P2", battlefield=[], life=20)
    game = Game(players=[p1, p2])
    game._settle()
    return game, p1, bear


def _cast_vitae(game, host):
    game.players[0].mana_pool["G"] = 1
    result = game.cast_from_hand(
        0, "Touch of Vitae",
        target_player_index=game.controller_index_of(host),
        target_permanent_index=game.battlefield_index_of(host),
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return result


def test_touch_of_vitae_grants_haste_and_the_quoted_untap_ability(set_pool):
    """"Until end of turn, target creature gains haste and "{0}: Untap this
    creature. Activate only once.""

    One "gains" over two kinds of thing (CR 113.3): a word layer 6 holds, and a
    whole printed ability the compiler has to read. The grant is only done when
    the granted ability *fires*, so the assertion is the untap, not the text.
    """
    pool = set_pool("ICE")
    game, _, bear = _vitae_game(pool)

    assert _cast_vitae(game, bear).supported
    assert bear.has_keyword("haste")
    assert '{0}: Untap this creature' in bear.effective_card.oracle_text

    result = game.activate_permanent_ability(0, "Balduvian Bears")
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result.details
    assert not bear.tapped


def test_touch_of_vitae_grants_an_ability_that_may_be_activated_only_once(set_pool):
    """"Activate only once" is a restriction with no turn in it (CR 602.5b).

    A parsed-and-dropped rider here would be an untapper the card never
    printed, so the second activation has to be refused inside the same turn
    the first one happened.
    """
    pool = set_pool("ICE")
    game, _, bear = _vitae_game(pool)
    _cast_vitae(game, bear)

    game.activate_permanent_ability(0, "Balduvian Bears")
    while game.stack:
        game.resolve_top_of_stack()
    bear.tapped = True

    again = game.activate_permanent_ability(0, "Balduvian Bears")
    assert not again.supported
    assert bear.tapped


def test_touch_of_vitae_takes_both_halves_away_at_end_of_turn(set_pool):
    """The printed duration is one prefix over both effects. A leading
    "Until end of turn," dropped on the quoted half would be a permanent
    untap engine nobody printed."""
    pool = set_pool("ICE")
    game, _, bear = _vitae_game(pool)
    _cast_vitae(game, bear)
    assert bear.has_keyword("haste")

    game.resolve_cleanup_step(0)
    game._settle()

    assert not bear.has_keyword("haste")
    assert '{0}: Untap this creature' not in bear.effective_card.oracle_text
# --- end W3G1 ---


# --- W4G5: retargeting, and a turn-scoped board mood ---


def _deflection_board(set_pool, spell_name, spell_set="LEA"):
    """Deflection in seat 0's hand and *spell_name* in seat 1's."""
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].hand = [set_pool("ICE")["Deflection"]]
    players[1].hand = [set_pool(spell_set)[spell_name]]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._sync_control()
    return game, players


def test_deflection_sends_a_spell_aimed_at_you_back_at_its_caster(set_pool):
    """The whole card. CR 115.7a changes what the spell points at and nothing
    else, so the Bolt still deals its own damage from its own source — and with
    only one other legal target the choice is forced and nobody is asked."""
    game, players = _deflection_board(set_pool, "Lightning Bolt")
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)

    result = game.queue_from_hand(0, "Deflection", target_stack_index=0)
    game._settle()

    assert result.supported, result.details
    assert players[0].life == 20, game.log
    assert players[1].life == 17, game.log


def test_deflection_moves_a_spell_from_one_permanent_to_another(set_pool):
    """The half Reflecting Mirror cannot do. Deflection prints no "the new
    target must be a player", so the replacement is whatever that spell could
    legally have chosen — for Terror, another creature."""
    game, players = _deflection_board(set_pool, "Terror")
    mine = _nosick(Permanent(card=_mk_creature_card("Mine", 2, 2)))
    theirs = _nosick(Permanent(card=_mk_creature_card("Theirs", 3, 3)))
    players[0].battlefield = [mine]
    players[1].battlefield = [theirs]
    game._sync_control()
    game.queue_from_hand(
        1, "Terror", target_player_index=0, target_permanent_index=0
    )

    game.queue_from_hand(0, "Deflection", target_stack_index=0)
    game._settle()

    assert [perm.card.name for perm in players[0].battlefield] == ["Mine"], game.log
    assert players[1].battlefield == [], game.log


def test_deflection_leaves_a_spell_with_nowhere_else_to_go_alone(set_pool):
    """CR 115.7a: "if a target can't be changed to another legal target, the
    original target is unchanged". Terror is the only creature's only threat —
    with nothing else on either battlefield the spell keeps what it named, and
    Deflection resolves having done nothing."""
    game, players = _deflection_board(set_pool, "Terror")
    only = _nosick(Permanent(card=_mk_creature_card("Only", 2, 2)))
    players[0].battlefield = [only]
    game._sync_control()
    game.queue_from_hand(
        1, "Terror", target_player_index=0, target_permanent_index=0
    )

    game.queue_from_hand(0, "Deflection", target_stack_index=0)
    game.resolve_top_of_stack()

    assert game.stack[0].target_permanent_id == only.permanent_id, game.log
    assert any("no other legal target" in line for line in game.log), game.log


def test_deflection_counts_the_targets_a_spell_chose_before_offering_it(set_pool):
    """CR 115.9a: "target spell with **a single target**". A sweeper chose
    none and a divided Fireball chose two, so neither is offered — the count is
    the whole of what this card's noun phrase narrows, and a picker that
    skipped it would offer every spell on the stack."""
    deflection = set_pool("ICE")["Deflection"]

    game, _players = _deflection_board(set_pool, "Wrath of God")
    game.queue_from_hand(1, "Wrath of God")
    assert game.cast_target_spec(0, deflection)["valid_targets"] == [], game.log

    game, _players = _deflection_board(set_pool, "Fireball")
    game.queue_from_hand(
        1, "Fireball", x_value=4, divided_targets=[(0, None), (1, None)]
    )
    assert game.cast_target_spec(0, deflection)["valid_targets"] == [], game.log

    game, _players = _deflection_board(set_pool, "Lightning Bolt")
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert len(game.cast_target_spec(0, deflection)["valid_targets"]) == 1, game.log


def test_deflection_asks_nothing_about_who_the_spell_points_at_now(set_pool):
    """Reflecting Mirror prints "if that target is you" and Deflection does
    not, so a spell its caster aimed at their **own** creature is offered all
    the same — the clause is a printed narrowing, not a property of retargets."""
    game, players = _deflection_board(set_pool, "Terror")
    theirs = _nosick(Permanent(card=_mk_creature_card("Theirs", 3, 3)))
    mine = _nosick(Permanent(card=_mk_creature_card("Mine", 2, 2)))
    players[1].battlefield = [theirs]
    players[0].battlefield = [mine]
    game._sync_control()
    game.queue_from_hand(
        1, "Terror", target_player_index=1, target_permanent_index=0
    )

    game.queue_from_hand(0, "Deflection", target_stack_index=0)
    game.resolve_top_of_stack()

    assert game.stack[0].target_permanent_id == mine.permanent_id, game.log


def test_deflection_asks_its_caster_which_of_several_targets(set_pool):
    """A Bolt is "any target", so re-aiming it offers both faces and every
    creature. More than one candidate is a decision, and an interactive seat is
    asked for it — the resolution waiting on the answer (CR 608.2)."""
    game, players = _deflection_board(set_pool, "Lightning Bolt")
    mine = _nosick(Permanent(card=_mk_creature_card("Mine", 2, 2)))
    theirs = _nosick(Permanent(card=_mk_creature_card("Theirs", 3, 3)))
    players[0].battlefield = [mine]
    players[1].battlefield = [theirs]
    game.interactive_seats = {0}
    game._sync_control()
    game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_index=0
    )

    game.queue_from_hand(0, "Deflection", target_stack_index=0)
    game.resolve_top_of_stack()
    pending = game.pending_choice_of("retarget_choice")

    assert pending is not None, game.log
    offered = [option["name"] for option in pending.data["options"]]
    assert offered == ["P1", "P2", "Theirs"], offered
    assert game.confirm_retarget_choice(0, offered.index("Theirs")) is True
    game._settle()
    assert players[1].battlefield == [], game.log
    assert (players[0].life, players[1].life) == (20, 20), game.log
# --- end W4G5 ---


# --- W4G4: an X ceiling, and a three-outcome toll ---
def _chill_game(
    pool, *, snow_lands: int = 2, payer_lands: int = 4,
    attackers: tuple[str, ...] = ("Balduvian Bears",), blocker: bool = False,
):
    """Seat 0 attacking with *attackers*, seat 1 holding Winter's Chill.

    Both seats are interactive so the offer queues rather than taking its
    non-interactive default: the whole point of the card is which option the
    payer picks, and a default answers that question before the test can.
    """
    attacking = [Permanent(card=pool[name]) for name in attackers]
    p0 = PlayerState(
        name="P0", life=20,
        battlefield=attacking + [
            Permanent(card=pool["Snow-Covered Island"]) for _ in range(payer_lands)
        ],
    )
    defence = [Permanent(card=pool["Snow-Covered Island"]) for _ in range(snow_lands)]
    if blocker:
        defence.insert(0, Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(
        name="P1", life=20, battlefield=defence, hand=[pool["Winter's Chill"]],
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, message = game.declare_attackers(0, list(range(len(attacking))))
    assert ok, message
    return game, p0, p1, attacking


def _cast_chill(game, targets, x_value):
    """Cast Winter's Chill at *targets* (indices on seat 0's battlefield).

    Before blockers are declared, which the card's own timing line requires --
    the `_combat` helper the earlier rounds use advances one step further than
    this card may be cast in.
    """
    result = game.cast_from_hand(
        1, "Winter's Chill", target_permanent_index=list(targets),
        target_player_index=0, x_value=x_value,
    )
    game._settle()
    return result


def _finish_combat(game):
    game.advance_combat_phase()  # declare_blockers
    game.advance_combat_phase()  # combat_damage
    game.advance_combat_phase()  # end_of_combat
    game._settle()


def test_winters_chill_refuses_an_x_above_the_snow_lands_you_control(set_pool):
    """"X can't be greater than the number of snow lands you control."

    A printed restriction is only done when something enforces it. Parsed and
    dropped, this line lets the caster announce any X the mana pool covers --
    silent, and in their favour. The bound is counted at the announcement
    (CR 601.2b), before any cost is paid.
    """
    pool = set_pool("ICE")
    game, _, p1, _ = _chill_game(pool, snow_lands=1)

    refused = _cast_chill(game, [0], 2)
    assert not refused.supported
    assert "X can't be greater than 1" in refused.details
    assert [card.name for card in p1.hand] == ["Winter's Chill"], "nothing was spent"

    assert _cast_chill(game, [0], 1).supported, "the bound itself is legal"


def test_winters_chill_destroys_the_creature_nobody_paid_for(set_pool):
    """Pay nothing: "destroy that creature at end of combat."

    The delayed ability is about the creature the loop was on, and it fires at
    end of combat (CR 603.7) -- after the creature has already dealt its combat
    damage, which is what separates this branch from the shield one.
    """
    pool = set_pool("ICE")
    game, p0, p1, attacking = _chill_game(pool)
    assert _cast_chill(game, [0], 1).supported

    game.confirm_optional_pay(0, accept=False)
    game._settle()
    _finish_combat(game)

    assert p1.life == 18, "the damage was dealt; only the creature was bought"
    assert not any(perm is attacking[0] for perm in game.all_permanents())
    assert [card.name for card in p0.graveyard] == ["Balduvian Bears"]


def test_winters_chill_paying_only_one_prevents_both_ends_of_the_combat(set_pool):
    """Pay {1}: "prevent all combat damage that would be dealt **to and dealt
    by** that creature this combat."

    Both ends, so the attacker neither hurts the blocker nor is hurt by it --
    and the creature survives, because the destroy branch is the one that was
    not taken.
    """
    pool = set_pool("ICE")
    game, p0, p1, attacking = _chill_game(pool, blocker=True)
    assert _cast_chill(game, [0], 1).supported

    game.confirm_optional_pay(0, accept=True, option=0)
    game._settle()
    paid = sum(
        1 for perm in p0.battlefield
        if perm.card.name == "Snow-Covered Island" and perm.tapped
    )
    assert paid == 1, "the option the payer named, not the other one"

    game.advance_combat_phase()  # declare_blockers
    ok, message = game.declare_blockers(1, {0: [0]})
    assert ok, message
    game.advance_combat_phase()  # combat_damage
    game._settle()

    assert attacking[0].damage_marked == 0, "dealt to it"
    assert p1.battlefield[0].damage_marked == 0, "and dealt by it"
    assert p1.life == 20


def test_winters_chill_paying_two_buys_off_both_consequences(set_pool):
    """Pay {2}: neither the shield nor the destruction. The third outcome is a
    real one -- an engine that read "{1} or {2}" as one offer with one
    consequence would either prevent the damage of a creature whose controller
    paid full price, or destroy it."""
    pool = set_pool("ICE")
    game, p0, p1, attacking = _chill_game(pool)
    assert _cast_chill(game, [0], 1).supported

    game.confirm_optional_pay(0, accept=True, option=1)
    game._settle()
    paid = sum(
        1 for perm in p0.battlefield
        if perm.card.name == "Snow-Covered Island" and perm.tapped
    )
    assert paid == 2

    _finish_combat(game)
    assert p1.life == 18, "the damage was dealt"
    assert any(perm is attacking[0] for perm in game.all_permanents())


def test_winters_chill_binds_each_outcome_to_its_own_creature(set_pool):
    """One offer per chosen creature, and each answer acts on the creature its
    offer was about.

    The failure this pins is the one the loop makes easy: the resolution's own
    target list is *every* chosen creature, so a shield or a delayed destroy
    that read it would land on the first one twice.
    """
    pool = set_pool("ICE")
    game, p0, p1, attacking = _chill_game(
        pool, attackers=("Balduvian Bears", "Balduvian Barbarians"),
    )
    assert _cast_chill(game, [0, 1], 2).supported
    assert len(game.pending_choices_of("optional_pay", 0)) == 2

    game.confirm_optional_pay(0, accept=False)           # the Bears' controller
    game._settle()
    game.confirm_optional_pay(0, accept=True, option=0)  # the Barbarians'
    game._settle()
    _finish_combat(game)

    assert p1.life == 18, "the Bears' 2 damage; the shielded Barbarians dealt none"
    alive = {
        perm.card.name for perm in game.all_permanents()
        if perm.card.name.startswith("Balduvian")
    }
    assert alive == {"Balduvian Barbarians"}


def test_winters_chill_offers_nothing_a_controller_cannot_afford(set_pool):
    """CR 601.2h: an offer nobody can pay is not made, and the decline branch
    applies. With no untapped land the creature is simply destroyed at end of
    combat rather than sitting behind a prompt nobody can answer."""
    pool = set_pool("ICE")
    game, p0, p1, attacking = _chill_game(pool, payer_lands=0)
    assert _cast_chill(game, [0], 1).supported

    assert not game.pending_choices_of("optional_pay", 0)
    _finish_combat(game)
    assert [card.name for card in p0.graveyard] == ["Balduvian Bears"]


def test_winters_chill_shield_ends_with_the_combat_it_names(set_pool):
    """"...this combat", not "this turn". The window is data on the shield, so
    the end-of-combat sweep ends it -- read and dropped, the creature would go
    on being unable to deal or take damage for the rest of the turn."""
    pool = set_pool("ICE")
    game, p0, p1, attacking = _chill_game(pool)
    assert _cast_chill(game, [0], 1).supported
    game.confirm_optional_pay(0, accept=True, option=0)
    game._settle()
    assert attacking[0].metadata.get("prevent_combat_damage_direction_until_eot")

    _finish_combat(game)
    assert not attacking[0].metadata.get(
        "prevent_combat_damage_direction_until_eot"
    ), "the shield expired with the combat phase, not with the turn"
def test_winters_chill_refuses_an_option_the_payer_cannot_cover(set_pool):
    """CR 601.2b: a player chooses among the options they are **able** to take.

    With one untapped land the {2} half is not one of them, and naming it is not
    an answer -- the offer is still owed. Consuming it would leave the creature
    neither shielded nor destroyed, which is the one outcome the card does not
    have.
    """
    pool = set_pool("ICE")
    game, p0, _, attacking = _chill_game(pool, payer_lands=1)
    assert _cast_chill(game, [0], 1).supported

    assert not game.confirm_optional_pay(0, accept=True, option=1)
    assert len(game.pending_choices_of("optional_pay", 0)) == 1

    assert game.confirm_optional_pay(0, accept=True, option=0)
    game._settle()
    assert attacking[0].metadata.get("prevent_combat_damage_direction_until_eot")
# --- end W4G4 ---


# --- W4G2: blocker control ---
def _melee_board(pool, defender_creatures=("Brown Ouphe",)):
    """Seat 0 with two attackers and Melee in hand; seat 1 with blockers."""
    attackers = [
        _nosick(Permanent(card=pool["Balduvian Bears"])),
        _nosick(Permanent(card=pool["Tor Giant"])),
    ]
    blockers = [_nosick(Permanent(card=pool[name])) for name in defender_creatures]
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(attackers), life=20,
                    hand=[pool["Melee"]]),
        PlayerState(name="P2", battlefield=list(blockers), life=20),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.active_player_index = 0
    return game, attackers, blockers


def _cast_melee(game):
    game._set_phase_and_step("combat", "beginning_of_combat")
    result = game.cast_from_hand(0, "Melee")
    assert result.supported, result.details
    game.resolve_stack()


def test_melee_compiles_all_three_of_its_lines(set_pool):
    """Its cast restriction is a table row, its second line the block-chooser
    substitution and its third a delayed triggered ability scoped to the
    combat. A card supported on one of the three would be the hollow line the
    promotion gate counts."""
    program = compile_card_oracle(set_pool("ICE")["Melee"])

    assert program.supported
    kinds = [instruction.kind for instruction in program.instructions]
    assert "choose_blocks_for_defenders" in kinds
    delayed = next(
        i for i in program.instructions if i.kind == "create_delayed_trigger"
    )
    assert delayed.payload["event"] == "creature_attacks_unblocked"
    # CR 603.7b: "this combat" is a stated duration, and a shorter one than the
    # "this turn" every other delayed attack trigger in the pool prints.
    assert delayed.payload["duration"] == "end_of_combat"
    assert delayed.payload["once"] is False


def test_melee_can_only_be_cast_in_your_own_combat_before_blockers(set_pool):
    """"…during combat **on your turn** before blockers are declared." The
    seat is the whole difference from Blaze of Glory's row, which the table
    already had."""
    pool = set_pool("ICE")
    game, _attackers, _blockers = _melee_board(pool)
    game.players[1].hand.append(pool["Melee"])
    game.enforce_mana_costs = False

    game._set_phase_and_step("combat", "beginning_of_combat")
    # The defending player's own combat window is somebody else's turn.
    refused = game.cast_from_hand(1, "Melee")
    assert not refused.supported
    assert "on your turn" in refused.details

    game._set_phase_and_step("combat", "declare_blockers")
    too_late = game.cast_from_hand(0, "Melee")
    assert not too_late.supported

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.cast_from_hand(0, "Melee").supported


def test_melee_moves_the_block_declaration_to_its_caster(set_pool):
    """CR 509.1a's chooser, substituted. The declaration is still the defending
    player's — their creature blocks — but they may no longer make it, and the
    caster may."""
    pool = set_pool("ICE")
    game, attackers, blockers = _melee_board(pool)
    _cast_melee(game)

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], 1)[0]
    game._set_phase_and_step("combat", "declare_blockers")

    refused, message = game.declare_blockers(1, {0: 0})
    assert not refused
    assert "P1 chooses which creatures block" in message

    ok, _ = game.declare_blockers(1, {0: 0}, acting_index=0)
    assert ok
    # The defender's creature is the one blocking, on the defender's own entry.
    assert game.combat_blockers[1] == {0: [0]}
    assert attackers[0].blocked
    assert blockers[0].blocking_attacker_index == 0


def test_melee_untaps_and_removes_each_unblocked_attacker(set_pool):
    """The third line, a delayed ability the spell creates (CR 603.7): it fires
    per unblocked attacker once blocks are known (CR 509.1h)."""
    pool = set_pool("ICE")
    game, attackers, _blockers = _melee_board(pool)
    _cast_melee(game)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], 1)[0]
    assert attackers[1].tapped
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: 0}, acting_index=0)[0]

    game.advance_combat_phase()
    game.resolve_stack()

    # The blocked attacker is untouched; the unblocked one is untapped and out
    # of combat, which is what makes Melee a fog rather than a removal spell.
    assert attackers[0].attacking and attackers[0].tapped
    assert not attackers[1].attacking
    assert not attackers[1].tapped
    assert 1 not in game.combat_attackers


def test_melees_delayed_ability_does_not_survive_its_combat(set_pool):
    """CR 603.7b's stated duration is "this combat", not the turn: a second
    combat phase in the same turn is a declaration the card never saw."""
    pool = set_pool("ICE")
    game, _attackers, _blockers = _melee_board(pool)
    _cast_melee(game)
    assert len(game.delayed_triggers) == 1

    game._set_phase_and_step("combat", "end_of_combat")
    game.end_combat(step_already_started=True)

    assert game.delayed_triggers == []
    # The substitution is combat-scoped too, and ends in the same sweep.
    assert game.block_chooser_index(1) == 1


def test_melee_refuses_the_turn_scoped_printing_of_its_sentence(set_pool):
    """Master Warcraft prints "this turn". The substitution is combat-scoped
    state, so a turn-scoped one would stop applying at the second combat of a
    turn while the card still read as if it applied — the lowering refuses
    rather than working for one combat out of two."""
    from engine.grammar import parse_line
    from engine.grammar.lower import lower_ability
    from engine.grammar.errors import LoweringError

    node = parse_line(
        "You choose which creatures block this turn and how those creatures block."
    )
    with pytest.raises(LoweringError):
        lower_ability(node)
# --- end W4G2 ---


# --- FixC: a sweep names a class, not a target ---
def test_battle_cry_untaps_the_class_and_asks_for_no_creature(set_pool):
    """"Untap all white creatures you control." CR 115.1a — no "target".

    Its filter carried a colour *and* a seat, and both reached the picker as
    narrowings on a target the card never names: the browser raised a creature
    prompt and abandoned the cast when nothing was in play. The colour was
    ignored by the enumerator on top of that, so on a populated board it
    offered every creature for a spell that untaps only the white ones a
    player controls.
    """
    lea = set_pool("LEA")
    mine = [Permanent(card=lea["Savannah Lions"], tapped=True),
            Permanent(card=lea["Scathe Zombies"], tapped=True)]
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("ICE")["Battle Cry"]],
                    battlefield=mine),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game._sync_control()

    assert game.cast_target_spec(0, set_pool("ICE")["Battle Cry"]) == {
        "kind": "none", "requires_target": False, "valid_targets": [],
    }

    result = game.cast_from_hand(0, "Battle Cry")
    game._settle()

    assert result.supported, result.details
    assert [(p.card.name, p.tapped) for p in mine] == [
        ("Savannah Lions", False), ("Scathe Zombies", True),
    ]


def test_battle_cry_is_castable_for_its_blocking_rider_alone(set_pool):
    """The reason the empty board matters here rather than being a curiosity:
    the card's second sentence — "whenever a creature blocks this turn, it gets
    +0/+1" — is worth casting for on its own, and the phantom creature prompt
    made that impossible with no white creature untapped."""
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("ICE")["Battle Cry"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(0, "Battle Cry")
    game._settle()

    assert result.supported, result.details
    assert game.stack == []
# --- end FixC ---
