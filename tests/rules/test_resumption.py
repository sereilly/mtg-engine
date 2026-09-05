"""Loops that survive a step stopping to ask a question — the rules half.

CR 616.1e's choice interrupts a damage event part-way, and answering re-runs it.
An event is usually one step of something larger: a divided Fireball's targets,
a spell's remaining resolution, one attacker of several in the combat damage
step. What these pin is that the rest of that larger thing still happens, and
happens in the right order.

The loop bookkeeping underneath is tests/engine/test_resumption.py.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from tests.helpers import CARDS_BY_NAME, _mk_creature_card, _nosick


def _shielded_player(life: int = 20, pool: int = 5, name: str = "P1"):
    """A seat holding two shields that both apply to one red damage event — a
    Circle of Protection and a prevention pool, which is the CR 616.1e
    contention this pool reaches most easily."""
    player = PlayerState(name=name, life=life)
    player.color_prevention_shields = ["R"]
    player.damage_prevention_pool = pool
    return player


def _attacker(name: str, power: int, toughness: int, *, red: bool = True, first_strike: bool = False):
    card = replace(
        _mk_creature_card(name, power, toughness),
        colors=("R",) if red else (),
        keywords=("First strike",) if first_strike else (),
        oracle_text="First strike" if first_strike else "",
    )
    return _nosick(Permanent(card=card))


def _combat(attackers: list[Permanent], defenders: list[PlayerState], targets=None) -> Game:
    """Seat 0 attacking with *attackers*, stopped at the combat damage step with
    nothing resolved yet. ``targets`` names each attacker's own defending player
    (CR 802.5); without it everything attacks seat 1."""
    seat0 = PlayerState(
        name="P0", battlefield=attackers, library=[_mk_creature_card("Filler", 1, 1)]
    )
    game = Game(players=[seat0, *defenders])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, message = game.declare_attackers(
        0, list(range(len(attackers))), attacker_targets=targets
    )
    assert ok, message
    game.resolve_stack()
    game._set_phase_and_step("combat", "combat_damage")
    return game


def _pick(game, seat: int, key: str) -> None:
    """Answer the CR 616.1e prompt with a named effect."""
    prompt = game.pending_choices_of("effect_order", seat)[0]
    game.resolve_pending_choice(
        "effect_order", seat, option_index=prompt.data["_keys"].index(key)
    )


# ---------------------------------------------------------------------------
# A prompt in the middle of a spell's own instructions
# ---------------------------------------------------------------------------
#
# CR 616.1e is not the only decision that interrupts a resolution. Any prompt
# whose answer *is* the effect — a scry, a search, a reorder — stops the spell
# in the same place and for the same reason, and the steps written behind it
# must not run first (CR 608.2c). ``ChoiceSpec.suspends`` is what says so.


def _probe_spell(text: str, name: str = "Probe"):
    """An instant printing *text* as one line, so its clauses compile to a
    ``sequence`` rather than to independent top-level instructions."""
    return CardDefinition(
        name=name, mana_cost="{U}", cmc=1.0, type_line="Instant",
        oracle_text=text, colors=("U",), color_identity=("U",),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Instant"},
    )


def _library(*names: str) -> list:
    return [_mk_creature_card(n, 1, 1) for n in names]


@pytest.mark.cr("608.2c", "701.22a")
def test_608_2c_a_draw_written_after_a_scry_waits_for_the_scry():
    """The Opt shape. "Scry N. Draw a card." is two steps in the order written,
    and the second reads the library the first arranged — so arming the scry has
    to stop the draw behind it. It did not: the card was drawn off the top the
    scry had not touched yet, and the scry then rearranged the *next* one."""
    card = _probe_spell("Scry 2. Draw a card.")
    caster = PlayerState(name="P0", hand=[card], library=_library("A", "B", "C", "D"))
    game = Game(players=[caster, PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}

    game.cast_from_hand(0, card.name, target_player_index=1)

    assert game.pending_choices_of("scry", 0), "the caster was asked"
    assert caster.hand == [], "the draw written behind the scry has not happened"
    assert card not in caster.graveyard, "the spell is still resolving (CR 608.2n)"

    # Bottom A, keep B on top: the draw must see B.
    assert game.confirm_scry(0, card_order=[1, 0], bottom_count=1) is True

    assert [c.name for c in caster.hand] == ["B"], (
        "the draw took the card the scry put on top, not the one it moved"
    )
    assert [c.name for c in caster.library] == ["C", "D", "A"]
    assert card in caster.graveyard, "and the resolution finished"
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("704.3", "603.2")
def test_704_3_state_is_checked_once_a_resumed_resolution_finishes():
    """The Opt shape again, watched from the other side: what happens *after*
    the draw behind the scry. CR 704.3 checks state before a player would get
    priority after a resolution, and the priority pass does that for a
    resolution that runs straight through. One that suspended ran the check at
    the suspension point; the steps behind the answer had nowhere to be
    checked, so a "whenever you draw a card" permanent (Tolarian Kraken) saw
    the draw recorded and never announced."""
    kraken = CARDS_BY_NAME.get("Tolarian Kraken")
    if kraken is None:  # pragma: no cover - pool-dependent
        from engine.card_loader import load_catalog
        kraken = next(c for c in load_catalog() if c.name == "Tolarian Kraken")
    card = _probe_spell("Scry 1. Draw a card.")
    caster = PlayerState(
        name="P0", hand=[card], library=_library("A", "B", "C"),
        battlefield=[Permanent(card=kraken)],
    )
    game = Game(players=[caster, PlayerState(name="P1")])
    game.enforce_mana_costs = True
    game.interactive_seats = {0}
    game._sync_control()
    # {U} for the probe spell, {1} left for the Kraken's "you may pay {1}".
    caster.mana_pool = {"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 1, "generic": 0}

    result = game.cast_from_hand(0, card.name, target_player_index=1)
    assert result.supported, result.details
    assert game.pending_choices_of("scry", 0)
    assert not game.pending_choices_of("optional_pay", 0), "nothing drawn yet"

    assert game.confirm_scry(0, card_order=[0], bottom_count=0) is True

    assert [c.name for c in caster.hand] == ["A"], "the draw behind the scry happened"
    assert game.draws_announced_this_turn.get(0) == 1, (
        "and the Kraken's draw trigger was announced without waiting for the "
        "next thing that happens to check state"
    )
    assert game.stack and "Tolarian Kraken" in str(game.stack[-1]), (
        "the trigger is on the stack (CR 704.3 puts waiting triggers there)"
    )
    game._settle()
    assert game.pending_choices_of("optional_pay", 0), "and resolves into its 'you may pay {1}'"


@pytest.mark.cr("608.2c", "701.23a")
def test_608_2c_a_draw_written_after_a_search_waits_for_the_search():
    """The same rule with the other library-shaping prompt. A search removes a
    card and shuffles what is left, so a draw behind it cannot be resolved
    against the pre-search library."""
    card = _probe_spell(
        "Search your library for a card, put that card into your hand, then shuffle. "
        "Draw a card.",
        name="Probe Tutor",
    )
    caster = PlayerState(name="P0", hand=[card], library=_library("A", "B", "C"))
    game = Game(players=[caster, PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}

    game.cast_from_hand(0, card.name, target_player_index=1)

    assert game.pending_choices_of("search_library", 0), "the caster was asked"
    assert caster.hand == [], "the draw has not happened"

    assert game.confirm_search_library(0, 0) is True

    assert len(caster.hand) == 2, "the found card, then the drawn one"
    assert "A" in [c.name for c in caster.hand]
    assert card in caster.graveyard
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("608.2n", "701.23a")
def test_608_2n_a_searching_spell_reaches_the_graveyard_only_when_answered():
    """A shipped card, not a probe: Demonic Tutor. The graveyard placement is
    the last part of the resolution, and the search is in front of it."""
    tutor = CARDS_BY_NAME["Demonic Tutor"]
    caster = PlayerState(name="P0", hand=[tutor], library=_library("A", "B"))
    game = Game(players=[caster, PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}

    game.cast_from_hand(0, tutor.name, target_player_index=1)

    assert game.pending_search_library is not None
    assert tutor not in caster.graveyard, "still resolving"

    game.confirm_search_library(0, 0)

    assert tutor in caster.graveyard
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("608.2c", "701.22a")
def test_608_2c_a_non_interactive_caster_finishes_the_whole_resolution_at_once():
    """AI and headless play must stay synchronous: the prompt is queued, the
    auto-resolver answers it, and nothing is left owed or suspended — which is
    what keeps a seeded simulation reproducible."""
    card = _probe_spell("Scry 2. Draw a card.")
    caster = PlayerState(name="P0", hand=[card], library=_library("A", "B", "C", "D"))
    game = Game(players=[caster, PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.cast_from_hand(0, card.name, target_player_index=1)
    game.auto_resolve_pending_choices()

    assert len(caster.hand) == 1, "the draw happened"
    assert game.pending_choices == []
    assert card in caster.graveyard
    assert game.resume_stack == [] and not game.effect_suspended


# ---------------------------------------------------------------------------
# End to end: a spell whose damage stops to ask
# ---------------------------------------------------------------------------

@pytest.mark.cr("616.1e", "608.2n")
def test_616_1e_a_spell_whose_damage_asks_finishes_when_answered():
    """A red damage spell into a player holding two applicable shields. The
    event stops, and because it stops *before* applying anything the rest of the
    resolution has to stop with it — including CR 608.2n's "as the final part of
    an instant or sorcery spell's resolution, the spell is put into its owner's
    graveyard", which would otherwise bin a spell whose damage had not
    happened."""
    bolt = replace(CARDS_BY_NAME["Lightning Bolt"], colors=("R",))
    caster = PlayerState(name="P0", hand=[bolt])
    victim = _shielded_player()
    game = Game(players=[caster, victim])
    game.interactive_seats = {1}

    game.cast_from_hand(0, bolt.name, target_player_index=1)

    assert game.pending_choices_of("effect_order", 1), "the affected player was asked"
    assert victim.damage_prevention_pool == 5 and victim.color_prevention_shields == ["R"], (
        "nothing was spent while the question was open"
    )
    assert bolt not in caster.graveyard, "the spell is still resolving (CR 608.2n)"

    pool = game.pending_choices_of("effect_order", 1)[0].data["_keys"].index("_prevention_pool")
    game.resolve_pending_choice("effect_order", 1, option_index=pool)

    assert victim.damage_prevention_pool == 2, "the chosen shield absorbed the 3"
    assert victim.color_prevention_shields == ["R"], "the Circle was not spent"
    assert victim.life == 20
    assert bolt in caster.graveyard, "and the resolution finished"
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("616.1e")
def test_616_1e_a_divided_spell_resumes_the_targets_behind_the_one_that_asked():
    """The case the loop machinery exists for. Fireball divided over two
    players: the first stops to ask, and the second must still be dealt to when
    the answer arrives rather than being dropped."""
    fireball = replace(CARDS_BY_NAME["Fireball"], colors=("R",))
    caster = PlayerState(name="P0", hand=[fireball])
    victim = _shielded_player()
    third = PlayerState(name="P2", life=20)
    game = Game(players=[caster, victim, third])
    game.interactive_seats = {1}

    game.cast_from_hand(
        0, fireball.name, target_player_index=1, x_value=6,
        divided_targets=[(1, None), (2, None)],
    )

    assert game.pending_choices_of("effect_order", 1), "the shielded seat was asked"
    assert third.life == 20, "the other target has not been dealt to yet"

    keys = game.pending_choices_of("effect_order", 1)[0].data["_keys"]
    game.resolve_pending_choice(
        "effect_order", 1, option_index=keys.index("_prevention_pool")
    )

    assert victim.damage_prevention_pool == 2, "3 of the pool absorbed the shielded seat's share"
    assert third.life == 17, "the target behind the question was not lost"
    assert game.resume_stack == [] and not game.effect_suspended


# ---------------------------------------------------------------------------
# The combat damage step
# ---------------------------------------------------------------------------
#
# The largest loop in the engine, and the last damage path to reach CR 616.1e.
# It is three nested loops (blockers by defender, by blocker, by band member),
# two flat ones (attackers onto blockers, attackers onto players) and a tail
# that owns the step's own progress flags. Every one of those is work that a
# naive conversion drops on the floor the moment one event stops to ask.

@pytest.mark.cr("616.1e", "510.2")
def test_616_1e_combat_damage_asks_the_defending_player():
    """One red attacker into a seat holding two applicable shields. Combat used
    to be the one damage path that could not suspend, so every seat took the
    default; it asks now, and the non-default answer is what happens."""
    game = _combat([_attacker("Red Ogre", 3, 3)], [_shielded_player()])
    game.interactive_seats = {1}
    defender = game.players[1]

    game.resolve_all_combat_damage(0)

    assert game.pending_choices_of("effect_order", 1), "the defending player was asked"
    assert defender.damage_prevention_pool == 5 and defender.color_prevention_shields == ["R"], (
        "nothing was spent while the question was open"
    )
    assert not game.combat_damage_resolved, "and the step is not over"

    _pick(game, 1, "_prevention_pool")

    assert defender.damage_prevention_pool == 2, "the chosen shield absorbed the 3"
    assert defender.color_prevention_shields == ["R"], (
        "the Circle is the default and was not spent"
    )
    assert defender.life == 20
    assert game.combat_damage_resolved, "the step finished once answered"
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("616.1e", "510.2")
def test_616_1e_a_non_interactive_defender_takes_the_default_synchronously():
    """The same combat with nobody at the keyboard. AI and headless play must
    stay entirely synchronous — nothing queued, nothing left owed — which is
    what keeps scripts/simulate_ai_games.py deterministic per seed."""
    game = _combat([_attacker("Red Ogre", 3, 3)], [_shielded_player()])
    defender = game.players[1]

    game.resolve_all_combat_damage(0)

    assert not game.pending_choices_of("effect_order", 1), "no seat is interactive"
    assert defender.color_prevention_shields == [], "the default (the Circle) applied"
    assert defender.damage_prevention_pool == 5, "so the pool was not touched"
    assert game.combat_damage_resolved
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("616.1e", "802.5")
def test_616_1e_a_suspended_attacker_does_not_take_the_rest_of_combat_with_it():
    """The case a naive conversion silently drops, and the combat twin of the
    second Fireball target. Two attackers, each with its own defending player
    (CR 802.5): the first stops to ask, and the second must still deal its
    damage when the answer arrives rather than being lost with the loop."""
    game = _combat(
        [_attacker("Red One", 2, 2), _attacker("Red Two", 3, 3)],
        [_shielded_player(), PlayerState(name="P2", life=20)],
        targets={0: 1, 1: 2},
    )
    game.interactive_seats = {1}
    shielded, other = game.players[1], game.players[2]

    game.resolve_all_combat_damage(0)

    assert game.pending_choices_of("effect_order", 1), "the shielded seat was asked"
    assert other.life == 20, "the other defender has not been dealt to yet"

    _pick(game, 1, "_prevention_pool")

    assert shielded.damage_prevention_pool == 3, "2 of the pool absorbed the first attacker"
    assert shielded.life == 20
    assert other.life == 17, "the attacker behind the question was not lost"
    assert game.combat_damage_resolved
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("616.1e", "510.4")
def test_616_1e_a_suspended_first_strike_pass_still_gets_its_second_pass_once():
    """The sharpest risk in making the step suspendable. CR 510.4 gives this
    combat two damage steps, and the step's own ``combat_first_strike_done`` is
    how it knows which one it is in. A first-strike pass that stops to ask
    leaves that flag unset, so a caller that re-called on "not resolved yet"
    would re-run the *first* strike; the second pass has to be recorded behind
    the first instead, and run exactly once when the answer arrives.

    The Red Lancer is red and first-striking, so its 2 contends with both
    shields; the Grey Ogre is colourless and ordinary, so its 3 in the second
    pass meets a pool the answer has already emptied and lands whole."""
    game = _combat(
        [
            _attacker("Red Lancer", 2, 2, first_strike=True),
            _attacker("Grey Ogre", 3, 3, red=False),
        ],
        [_shielded_player(pool=2)],
    )
    game.interactive_seats = {1}
    defender = game.players[1]

    game.resolve_all_combat_damage(0)

    assert game.pending_choices_of("effect_order", 1), "the first-strike pass asked"
    assert not game.combat_first_strike_done, "and did not finish while it waited"
    assert defender.life == 20, "no combat damage has landed at all"

    _pick(game, 1, "_prevention_pool")

    assert defender.damage_prevention_pool == 0, "the pool absorbed the first striker's 2"
    assert defender.color_prevention_shields == ["R"], "the Circle was not spent"
    assert defender.life == 17, (
        "the second pass dealt the Grey Ogre's 3 against an empty pool — 14 would "
        "mean it ran twice, 19 that the first striker struck again"
    )
    assert game.log.count("Resolved first strike combat damage") == 1
    assert game.log.count("Resolved combat damage") == 1
    assert game.combat_first_strike_done and game.combat_damage_resolved
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("616.1e", "510.1c")
def test_616_1e_a_suspended_blocker_resumes_the_loops_it_was_nested_in():
    """The deepest of the step's loops. Blockers deal by defender, by blocker,
    by band member, and only then do the attackers deal — so a blocker's damage
    stopping to ask has the rest of its own loop, both attacker loops and the
    step's tail behind it, and every one of them has to be waiting rather than
    already spent.

    The contention is Jade Monolith's redirect against a prevention pool on one
    attacker (CR 616.1g's pairing), whose controller is the seat asked."""
    attacked, spared = _attacker("Attacker One", 2, 2), _attacker("Attacker Two", 2, 2)
    attacked.damage_prevention_pool = 5
    attacked.metadata["redirect_damage_to_player"] = 0
    first, second = _attacker("Blocker One", 2, 3), _attacker("Blocker Two", 2, 3)
    game = _combat([attacked, spared], [PlayerState(name="P1", battlefield=[first, second])])
    game.interactive_seats = {0}
    game._set_phase_and_step("combat", "declare_blockers")
    ok, message = game.declare_blockers(1, {0: 0, 1: 1})
    assert ok, message
    game._set_phase_and_step("combat", "combat_damage")

    game.resolve_all_combat_damage(0)

    assert game.pending_choices_of("effect_order", 0), "the attacker's controller was asked"
    assert (attacked.damage_marked, spared.damage_marked) == (0, 0)
    assert (first.damage_marked, second.damage_marked) == (0, 0), (
        "the attackers deal after the blockers, so none of that has happened either"
    )

    _pick(game, 0, "_prevention_pool")

    assert attacked.damage_prevention_pool == 3, "the chosen shield absorbed the 2"
    assert attacked.metadata.get("redirect_damage_to_player") == 0, (
        "the redirect is the default and is still armed"
    )
    assert attacked.damage_marked == 0
    assert spared.damage_marked == 2, "the blocker behind the question still dealt"
    assert (first.damage_marked, second.damage_marked) == (2, 2), (
        "and both attacker loops queued behind that one ran too"
    )
    assert game.combat_damage_resolved
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("616.1e", "511.1")
def test_616_1e_a_suspended_combat_does_not_advance_to_end_of_combat():
    """One level further out than the step itself. The phase driver deals the
    damage and *then* closes the step and enters end of combat (CR 511.1) — work
    after a loop, which is exactly what does not run when a step suspends and is
    not recorded. Leaving the step is the loop's last step now, so a combat
    waiting on an answer stays in the combat damage step and finishes the whole
    way through when it gets one."""
    attacker = _attacker("Red Ogre", 3, 3)
    seat0 = PlayerState(
        name="P0", battlefield=[attacker], library=[_mk_creature_card("Filler", 1, 1)]
    )
    defender = _shielded_player()
    defender.library = [_mk_creature_card("Filler", 1, 1)]
    game = Game(players=[seat0, defender])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    ok, message = game.declare_attackers(0, [0])
    assert ok, message
    game._close_current_priority_step()
    game.advance_combat_phase()  # declare blockers (auto-skipped: no blockers)
    game._close_current_priority_step()

    game.advance_combat_phase()  # combat damage, auto-resolved

    assert game.pending_choices_of("effect_order", 1), "the defending player was asked"
    assert game.current_step == "combat_damage", (
        "the phase must not have left the step whose damage is still owed"
    )
    assert not game.combat_damage_resolved

    _pick(game, 1, "_prevention_pool")

    assert defender.damage_prevention_pool == 2 and defender.life == 20
    assert game.combat_damage_resolved
    assert game.current_step == "end_of_combat", "and the step closed once it was done"
    assert game.resume_stack == [] and not game.effect_suspended


# ---------------------------------------------------------------------------
# A discard suspends the resolution it is a step of (round 29)
# ---------------------------------------------------------------------------
#
# CR 608.2 makes a resolution a sequence of steps and CR 117.3b hands priority
# back only when it is over. A prompt part-way through it therefore stops the
# steps *behind* it as well: a discard's answer is what the next step of the
# same sentence works from ("…for each card discarded this way"), and running
# that step against the hand as it stood when the prompt was armed reads a
# number the player has not given yet.
#
# The `discard` ChoiceSpec used to be `suspends=False`, which is exactly that
# bug with nothing pointing at it — the step behind the prompt ran, saw nothing
# had been discarded, and did nothing.


@pytest.mark.cr("608.2", "117.3b")
def test_a_discard_stops_the_steps_queued_behind_it(set_pool):
    """Recall's return runs only once the discard has been answered."""
    pool = set_pool("LEG")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Recall"], CARDS_BY_NAME["Giant Growth"]],
        graveyard=[CARDS_BY_NAME["Black Lotus"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"

    assert game._cast_onto_stack(0, "Recall", x_value=1).supported
    game.priority_player_index = 0
    game.pass_priority(0)
    game.pass_priority(1)

    # Step one asked; steps two and three are recorded, not run.
    assert [c.kind for c in game.pending_choices] == ["discard"]
    assert game.effect_suspended is True
    assert game.resume_stack, "the rest of the sequence is owed"
    assert [c.name for c in p1.hand] == ["Giant Growth"]
    assert p1.exile == [], "the third step has not run either"

    game.resolve_pending_choice("discard", 0, hand_indices=[0], to_library=False)

    # Answering resumed them, innermost first, and the return saw the graveyard
    # the discard had just filled.
    assert [c.kind for c in game.pending_choices] == ["search_library"]
    assert sorted(c.name for c in p1.graveyard) == ["Black Lotus", "Giant Growth"]


# ---------------------------------------------------------------------------
# Several seats can owe a decision at once (round 31)
# ---------------------------------------------------------------------------
#
# CR 608.2 and CR 117.3b are about the whole resolution, not about one prompt of
# it. "Each opponent discards two cards" arms one prompt per opponent, and every
# one of them is a step of the same resolution that has not happened yet — so
# the steps behind them wait for the *last* answer, not the first.
#
# The suspension used to be a single boolean on ``Game``, which cannot say that.
# The first opponent's answer cleared it, the resolution resumed, and "each
# player loses 2 life" was applied while the second opponent still had their
# hand. It is derived from the queue now (``PendingChoicesMixin`` —
# every queued choice of a ``suspends`` kind holds it), so the last answer is
# what lifts it.


@pytest.mark.cr("608.2", "117.3b")
def test_two_seats_owing_a_discard_both_hold_the_resolution(catalog_by_name):
    """Bad Deal's life loss waits for both opponents, not just the first."""
    filler = [_mk_creature_card(f"Filler{i}", 1, 1) for i in range(6)]
    caster = PlayerState(name="P0", hand=[catalog_by_name["Bad Deal"]],
                         library=list(filler))
    left = PlayerState(name="P1", hand=[CARDS_BY_NAME["Giant Growth"],
                                        CARDS_BY_NAME["Black Lotus"]])
    right = PlayerState(name="P2", hand=[CARDS_BY_NAME["Giant Growth"],
                                         CARDS_BY_NAME["Black Lotus"]])
    game = Game(players=[caster, left, right])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1, 2}
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"

    assert game._cast_onto_stack(0, "Bad Deal").supported
    game.priority_player_index = 0
    for seat in (0, 1, 2):
        game.pass_priority(seat)

    owed = [c.player_index for c in game.pending_choices if c.kind == "discard"]
    assert owed == [1, 2], "each opponent was asked in turn order"
    assert game.effect_suspended is True
    assert [p.life for p in game.players] == [20, 20, 20]

    game.resolve_pending_choice("discard", 1, hand_indices=[0, 1], to_library=False)

    assert game.effect_suspended is True, (
        "seat 2 still owes a discard, so the resolution is still suspended"
    )
    assert [p.life for p in game.players] == [20, 20, 20], (
        "the sentence behind the discards must not run while one is still owed"
    )
    assert game.waiting_prompt() is not None

    game.resolve_pending_choice("discard", 2, hand_indices=[0, 1], to_library=False)

    assert not game.effect_suspended and game.resume_stack == []
    assert [p.life for p in game.players] == [18, 18, 18]
    assert len(caster.hand) == 2 and left.hand == [] and right.hand == []


# ---------------------------------------------------------------------------
# A round of offers, repeated
# ---------------------------------------------------------------------------
#
# "Starting with you, each player may put a permanent card from their hand onto
# the battlefield. Repeat this process until no one puts a card onto the
# battlefield." (Eureka.) Each seat's offer is a decision, so the round is a
# loop of them — and the *round* is a loop too. What these pin is that a seat
# stopping to think costs neither the seats behind it nor the rounds behind
# those.


def _r33_eureka_game(set_pool, catalog_by_name, hands: list[list[str]], interactive=()) -> Game:
    players = []
    for index, names in enumerate(hands):
        hand = [catalog_by_name[name] for name in names]
        if index == 0:
            hand = [set_pool("LEG")["Eureka"], *hand]
        players.append(
            PlayerState(
                name=f"P{index + 1}",
                hand=hand,
                library=[_mk_creature_card("Filler", 1, 1)],
            )
        )
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game


@pytest.mark.cr("101.4", "608.2c")
def test_101_4_every_seat_is_offered_the_round_in_turn_order(set_pool, catalog_by_name):
    """One decision per player, asked in turn order, before the process repeats.

    A loop that finished one seat's whole hand before asking the next would
    empty the hands just as thoroughly and be a different card.
    """
    game = _r33_eureka_game(
        set_pool, catalog_by_name, [["Shivan Dragon", "Black Lotus"], ["Serra Angel", "Wall of Stone"]]
    )

    assert game.cast_from_hand(0, "Eureka").supported

    puts = [line.split()[0] for line in game.log if line.endswith("(Eureka)")]
    assert puts == ["P1", "P2", "P1", "P2"], game.log


@pytest.mark.cr("117.3b", "608.2c")
def test_117_3b_the_rounds_behind_an_unanswered_offer_still_happen(set_pool, catalog_by_name):
    """The spell waits on the seat that has not answered, and picks up the rest
    of the round — and the round after it — once the answer arrives.

    The loop that carries this is nested: seats inside a round, rounds inside
    the process. Re-running only the step that asked would leave the second seat
    unasked and the second round never begun.
    """
    game = _r33_eureka_game(
        set_pool, catalog_by_name,
        [["Shivan Dragon", "Black Lotus"], ["Serra Angel"]],
        interactive={0},
    )

    assert game.cast_from_hand(0, "Eureka").supported
    game.resolve_stack()

    # Seat 1 is not interactive and has already taken its default, but seat 0
    # is still owed the first offer of the first round.
    owed = game.waiting_prompt()
    assert owed is not None and owed.player_index == 0
    assert [p.card.name for p in game.players[1].battlefield] == []

    while game.pending_choices:
        choice = game.pending_choices[0]
        live = game.live_put_from_hand_choices(choice)
        assert game.confirm_put_from_hand_choice(choice.player_index, live[0] if live else None)

    assert game.waiting_prompt() is None
    assert [p.card.name for p in game.players[0].battlefield] == [
        "Shivan Dragon", "Black Lotus",
    ], "the second round never ran"
    assert [p.card.name for p in game.players[1].battlefield] == [
        "Serra Angel"
    ], "the seat behind the one that asked was skipped"


# -- CR 608.2c/608.2d: what a resolution offers, and when (round 34) ----------


def _r34_offer_program(steps):
    """A ``Game`` and an execution context to run *steps* against, with seat 0
    interactive so an offer queues rather than answering itself."""
    from engine.game_types import OracleExecutionContext

    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    context = OracleExecutionContext(
        caster=game.players[0],
        target=game.players[0],
        card=CardDefinition(
            name="Test Effect", mana_cost="", cmc=0.0, type_line="Sorcery",
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=(), raw={"name": "Test Effect", "type_line": "Sorcery"},
        ),
    )
    return game, context


@pytest.mark.cr("608.2d", "119.4")
def test_an_alternative_a_player_cannot_take_is_not_offered():
    """"The player can't choose an option that's illegal or impossible."

    "Pay 4 life or …" at 3 life is one alternative, not two: CR 119.4 lets a
    player pay life only with a life total at least the amount. The gate is
    ``_action_is_takeable``, which the optional-offer path already ran and the
    bare choice mid-resolution did not — so the mode was offered and then
    refused, which is a decision a player makes and does not get.
    """
    from engine.handlers.registry import EFFECT_HANDLERS
    from engine.oracle_types import OracleInstruction

    modes = (
        {"label": "pay 4 life",
         "instruction": OracleInstruction("pay_life", "", {"amount": 4})},
        {"label": "gain 1 life",
         "instruction": OracleInstruction(
             "target_gains_life", "", {"amount": 1, "recipient": "caster"}
         )},
    )
    for life, expected in ((20, ["pay 4 life", "gain 1 life"]), (3, ["gain 1 life"])):
        game, context = _r34_offer_program(())
        game.players[0].life = life

        EFFECT_HANDLERS["choose_one"](
            game, OracleInstruction("choose_one", "", {"modes": modes}), context
        )

        assert game.pending_choice_of("mode_choice").data["labels"] == expected


@pytest.mark.cr("608.2c", "608.2d")
def test_a_choice_inside_a_repetition_stops_it_until_it_is_answered():
    """"…in the order written." One iteration's decision is applied before the
    next iteration starts.

    A mode picked inside a "for each" acts on the object the loop is currently
    on, so arming every iteration's prompt at once would leave every answer to
    land on whichever object the loop had ended on. The prompt suspends, and
    the loop it is a step of stops with it (``engine/resumption.py``).
    """
    from engine.handlers.registry import EFFECT_HANDLERS
    from engine.oracle_types import OracleInstruction

    game, context = _r34_offer_program(())
    context.results["chosen"] = ["first", "second"]
    seen: list[str] = []
    modes = (
        {"label": "note it",
         "instruction": OracleInstruction("sequence", "", {"steps": ()})},
        {"label": "or not",
         "instruction": OracleInstruction("sequence", "", {"steps": ()})},
    )
    loop = OracleInstruction(
        "for_each", "",
        {
            "iterator": {"produced_by": "chosen"},
            "effect": (OracleInstruction("choose_one", "", {"modes": modes}),),
        },
    )

    EFFECT_HANDLERS["for_each"](game, loop, context)

    assert len(game.pending_choices) == 1, "the second iteration has not started"
    assert game.effect_suspended is True
    seen.append(context.iteration_target)

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=0, target=None)
    seen.append(context.iteration_target)

    assert seen == ["first", "second"], "each answer landed on its own object"
    assert len(game.pending_choices) == 1, "the second iteration's own prompt"

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=0, target=None)
    assert game.pending_choices == []
    assert game.effect_suspended is False
    assert context.iteration_target is None, "the loop restored what it borrowed"


# --- W3G3: a printed process its controller may run again ---


@pytest.mark.cr("608.2h", "117.3b")
def test_a_repeated_process_holds_its_spell_on_the_stack_until_the_last_answer():
    """"Sacrifice a nontoken permanent… **You may repeat this process any
    number of times.**" (Forbidden Ritual.)

    The decision is a step of the loop rather than a line after it — a round
    that stopped to ask its controller which permanent to sacrifice would never
    reach work written after the loop (``engine/resumption.py``). What that buys
    is CR 608.2h's ordering: the sacrifice prompt suspends the resolution, the
    spell stays on the stack, and the "again?" question is armed only once the
    round it belongs to has finished.
    """
    from engine.card_loader import load_cards, manifest_set_path

    vis = {c.name: c for c in load_cards(manifest_set_path("VIS", include_measured=True))}
    game = Game(players=[
        PlayerState(name="P1", battlefield=[]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.players[0].hand = [vis["Forbidden Ritual"]]
    for _ in range(2):
        game.players[0].battlefield.append(Permanent(card=vis["Panther Warriors"]))
    game._sync_control()

    game.cast_from_hand(0, "Forbidden Ritual", target_player_index=1)
    game.resolve_stack()

    # The round stopped on its first step, and the rest of it is recorded rather
    # than lost.
    assert game.effect_suspended is True
    assert game.pending_choice_of("sacrifice") is not None
    assert game.pending_choice_of("repeat_process") is None
    assert game.resume_stack, "the rest of the round is still owed"

    assert game.confirm_sacrifice(0, [0]) is True
    game.auto_resolve_pending_choices(only_player_index=1)

    # Answering resumed the round, which then asked its own last question.
    assert game.pending_choice_of("repeat_process") is not None
    assert game.confirm_repeat_process(0, False) is True
    game.auto_resolve_pending_choices()
    assert game.effect_suspended is False
    assert game.resume_stack == []
