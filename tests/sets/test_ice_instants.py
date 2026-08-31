"""Ice Age (ICE) instant cards.

ICE is a *measured* set, mid-implementation: cards land here with the round
that buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool
resolves through ``set_pool("ICE")`` even though the set is not shipped —
reading a card file is not shipping it. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


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


# --- W1G3 (cont.): the one declined instant, with its pieces named ---
def test_w1g3_spoils_of_evil_is_declined_and_says_which_pieces_are_missing(set_pool):
    """"For each artifact or creature card in target opponent's graveyard, add
    {C} and you gain 1 life."

    Five pieces. The refusal site says "expected a subject", which is the
    generic no-production message and names none of them:

    1. There is no leading ``For each <noun phrase>, <effect>`` production at
       all. The two that exist are a counter placement
       (``effects/counters``) and the "for each creature that died this way"
       back-reference (``statements``); a bare sentence opening with "for" has
       no reading.
    2. The *trailing* spelling that does exist ("Add {C} for each …") reads only
       the caster's own zone: "in **target opponent's** graveyard" leaves
       unconsumed text where "in your graveyard" parses.
    3. ``lowering/mana._lower_add_mana``'s per-each branch refuses any owner but
       "you" — "the mana multiplier counts the producer's own board".
    4. The loop body is two effects joined by "and", and
       ``handlers/control_flow.for_each`` iterates battlefield permanents or a
       set an earlier step recorded. Cards in a graveyard are neither, so even a
       parsed loop would have nothing to walk.
    5. The spell targets a **player**, and with no instruction describing one
       ``targeting.derive_cast_spec`` gives the picker nothing to ask for.
    """
    from engine.grammar import compile_line

    assert not compile_card_oracle(set_pool("ICE")["Spoils of Evil"]).supported

    # Piece 1: the leading form has no production.
    leading = compile_line(
        "For each artifact or creature card in target opponent's graveyard, "
        "add {C} and you gain 1 life."
    )
    assert not leading.parsed

    # Piece 2: the trailing form reads the caster's zone and only that one.
    assert compile_line("Add {C} for each creature card in your graveyard.").lowered
    theirs = compile_line(
        "Add {C} for each artifact or creature card in target opponent's graveyard."
    )
    assert not theirs.parsed
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
