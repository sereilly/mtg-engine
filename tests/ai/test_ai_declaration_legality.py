"""Can the AI build a legal attack declaration under every restriction the pool
prints? (CR 508.1c.)

A census rather than a handful of cases, and the reason is the failure it was
written for. ``engine/legality.attack_declaration_refusal`` is the predicate
``ai_policy._legal_declaration`` prunes against, and until W2G4 it did not
include either attack **cap**: those were checked inline in
``declare_attackers`` and nowhere else. So the AI proposed an over-cap set, the
declaration refused it *whole*, and ``web/combat_prompts._ai_declare_attackers``
fell through its superset fallback — also over the cap — to ``[]``. The seat
attacked with nobody, for the rest of the game.

Nothing caught that, and nothing could have: the failure is **conservative**.
No rule is broken, no cost is paid, no exception is raised, the log says
"declared attackers", and every existing test of Caverns of Despair and
Crawlspace asserts that an over-cap declaration is *refused* — which it was, and
still is. The only observable is a seat quietly doing nothing, which is the same
shape ``simulate_ai_games.py`` grew ``refused_casts`` for on the casting side.
There is no equivalent counter here and adding one to that report would have
found nothing, because **the AI simulator has no combat phase at all** — its
turn loop is bookkeeping, untap, upkeep, draw, main phase, cast, activate, and
then the next seat. It never declares an attacker. So the instrument goes here,
in a test, where a declaration actually happens.

The invariant is one sentence: *whatever ``choose_attackers`` proposes, the
declaration accepts.* Parametrised over the cards the pool actually prints
rather than over a list, so a set ingested tomorrow that prints another
declaration-level restriction is covered on arrival.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_attackers
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_creature_card, _nosick

#: The instruction kinds that refuse a *declaration* rather than a creature
#: (CR 508.1c). Each is a restriction ``can_attack`` structurally cannot answer,
#: because each is about who else was declared.
_W2G4_DECLARATION_KINDS = (
    "max_attackers_each_combat",                 # Caverns of Despair
    "max_attackers_on_you_each_combat",          # Crawlspace
    "cant_attack_unless_others_attack",          # Orcish Conscripts, Mogg Flunkies
    "cant_attack_unless_greater_power_attacks",  # Okk
    "can_only_attack_alone",                     # Errantry's grant, and any printing
)


def _w2g4_restriction_cards():
    """Every card in the pool — both manifest roles — printing one of those.

    Both roles deliberately: a measured set is exactly where a new printing of
    one of these arrives, and Crawlspace was in ``measured`` when this failure
    was found.
    """
    seen: dict[str, object] = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            seen.setdefault(card.oracle_id or card.name, card)
    found = []
    for card in seen.values():
        kinds = {
            instruction.kind
            for instruction in compile_card_oracle(card).instructions
            if instruction.kind in _W2G4_DECLARATION_KINDS
        }
        for kind in sorted(kinds):
            found.append((card.name, kind, card))
    return sorted(found, key=lambda entry: (entry[1], entry[0]))


_W2G4_CARDS = _w2g4_restriction_cards()


def _w2g4_board(card, kind):
    """A board where the AI has plenty to attack with and *card* is in play.

    Three attackers of different value, so a cap has something to choose
    between and a wrong prune is visible in which creatures survive it. The
    restriction's own permanent goes on the side its sentence is about: "can
    attack **you**" (Crawlspace) protects the defender, everything else sits
    with the attacker — and a creature carrying one is itself an attacker.
    """
    attacker_seat = PlayerState(name="P1")
    defender_seat = PlayerState(name="P2")
    game = Game(players=[attacker_seat, defender_seat])
    game.enforce_mana_costs = False
    for name, power, toughness in (("Runt", 1, 1), ("Middling", 2, 2), ("Fatty", 4, 4)):
        attacker_seat.battlefield.append(
            Permanent(card=_mk_creature_card(name, power, toughness))
        )
    home = (
        defender_seat
        if kind == "max_attackers_on_you_each_combat"
        else attacker_seat
    )
    home.battlefield.append(Permanent(card=card))
    game.start_turn(0)
    for permanent in attacker_seat.battlefield:
        _nosick(permanent)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    assert game.current_step == "declare_attackers"
    return game


@pytest.mark.parametrize(
    "card_name,kind,card",
    _W2G4_CARDS,
    ids=[f"{name}-{kind}" for name, kind, _card in _W2G4_CARDS],
)
def test_the_ai_can_declare_a_legal_attack_under_every_printed_restriction(
    card_name, kind, card
):
    """The AI's proposal is accepted, whatever the restriction.

    ``declare_attackers`` returning False here is the whole defect: the web
    layer's fallback is a *superset* of this set, so a refusal there is a seat
    that attacks with nobody rather than one that attacks with fewer.
    """
    game = _w2g4_board(card, kind)
    proposed = choose_attackers(game, 0)
    ok, why = game.declare_attackers(0, proposed, defending_player_index=1)
    assert ok, f"{card_name} ({kind}): the AI proposed {proposed} and got {why!r}"


def test_the_census_is_not_empty():
    """A census that finds nothing reports zero and means nothing.

    Both caps are in the pool today — one shipped since Legends, one arriving
    with Urza's Legacy — so an empty parametrisation means the derivation broke,
    not that the pool got simpler.
    """
    kinds = {kind for _name, kind, _card in _W2G4_CARDS}
    assert "max_attackers_each_combat" in kinds
    assert "max_attackers_on_you_each_combat" in kinds


def test_the_ai_keeps_its_best_attackers_under_a_cap(set_pool):
    """A cap is disobeyed by the *set*, so the engine can only name an arbitrary
    member — and it names the last one it was handed.

    ``_legal_declaration`` therefore hands the list over weakest-last, which is
    what turns "the AI attacks with two creatures" into "the AI attacks with its
    two best". Asserted because it is a choice, not a consequence: the engine
    naming ``declared_attackers[-1]`` would otherwise leave the Fatty home
    whenever it happened to be last in battlefield order.
    """
    game = _w2g4_board(set_pool("LEG")["Caverns of Despair"], "max_attackers_each_combat")
    proposed = choose_attackers(game, 0)
    names = [game.players[0].battlefield[i].card.name for i in proposed]

    assert len(proposed) == 2, "Caverns of Despair caps the declaration at two"
    assert set(names) == {"Middling", "Fatty"}, names
    assert game.declare_attackers(0, proposed, defending_player_index=1)[0]


def test_a_lethal_swing_is_pruned_to_a_legal_one(set_pool):
    """``choose_attackers`` short-circuits to the whole legal set when the board
    can kill — and that path used to skip the prune entirely.

    Under either cap the lethal declaration was refused whole, so the seat
    attacked with nobody on the one turn it could have won.
    """
    game = _w2g4_board(set_pool("LEG")["Caverns of Despair"], "max_attackers_each_combat")
    game.players[1].life = 3

    proposed = choose_attackers(game, 0)
    ok, why = game.declare_attackers(0, proposed, defending_player_index=1)
    assert ok, why
    assert proposed, "attacking with nobody is not a lethal swing"


def test_the_ai_can_declare_at_one_seat_of_three_under_a_per_defender_cap(set_pool):
    """A free-for-all is the one table where the engine cannot fill the map in.

    `choose_attackers` sends every attacker at one chosen opponent even with
    three seats, so a Crawlspace at *that* seat caps the declaration — and
    `attack_declaration_refusal` asked with no `defenders` map and more than one
    living opponent declines to guess which seat is being attacked, because
    guessing would refuse legal declarations. So the AI has to say. Without
    that, the prune sees only the global cap, the declaration is refused whole
    for the per-defender one, and the seat is back to attacking with nobody.
    """
    seats = [PlayerState(name="P1"), PlayerState(name="P2"), PlayerState(name="P3")]
    attackers = [
        Permanent(card=_mk_creature_card(name, power, power))
        for name, power in (("Runt", 1), ("Middling", 2), ("Fatty", 4))
    ]
    seats[0].battlefield.extend(attackers)
    # On both defenders, so whichever the AI picks is capped.
    for seat in seats[1:]:
        seat.battlefield.append(Permanent(card=set_pool("ULG")["Crawlspace"]))
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.start_turn(0)
    for permanent in attackers:
        _nosick(permanent)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"

    from engine.ai_policy import choose_attack_target

    target = choose_attack_target(game, 0)
    proposed = choose_attackers(game, 0)
    ok, why = game.declare_attackers(0, proposed, defending_player_index=target)

    assert ok, f"proposed {proposed} at seat {target}: {why!r}"
    assert len(proposed) == 2, proposed


# --- W1G1: the same census on the blocking side (CR 509.1b) ---
#
# The entry above was fixed at W2G4 and its blocking twin was declined there
# with its parts named. This is that twin, and the failure was identical: the
# three declaration-wide block restrictions lived inline in `declare_blockers`
# and nowhere else, so `ai_policy.choose_combat_blockers` pruned against
# nothing at all. It proposed a map the gate refused **whole**,
# `ai_combat.declare_ai_blockers` fell through to `{}` and `web/game_flow` to a
# safety valve that wipes *every* seat's blocks — so the defender blocked with
# nobody, this combat and every later one, with nothing spent, no rule broken
# and nothing logged.
#
# Unlike the attack side, this one **is** reproducible end to end now: the AI
# simulator grew a combat phase, so a run pinned to one of these cards shows
# the refusal in `SimulationReport.refused_blocks` and shows the blocker count
# rise once the prune lands. The census still goes here, because a test is
# where a declaration is guaranteed to happen.

from engine.ai_policy import choose_combat_blockers  # noqa: E402

#: The instruction kinds that refuse a *block declaration* rather than a pairing
#: (CR 509.1b). Each is a restriction `_can_block_attacker` structurally cannot
#: answer, because each is about who else was declared.
_W1G1_BLOCK_DECLARATION_KINDS = (
    "max_blockers_each_combat",                 # Caverns of Despair
    "cant_block_unless_others_block",           # Orcish Conscripts, Mogg Flunkies
    "cant_block_unless_greater_power_blocks",   # Okk
)


def _w1g1_restriction_cards():
    """Every card in the pool — both manifest roles — printing one of those."""
    seen: dict[str, object] = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            seen.setdefault(card.oracle_id or card.name, card)
    found = []
    for card in seen.values():
        kinds = {
            instruction.kind
            for instruction in compile_card_oracle(card).instructions
            if instruction.kind in _W1G1_BLOCK_DECLARATION_KINDS
        }
        for kind in sorted(kinds):
            found.append((card.name, kind, card))
    return sorted(found, key=lambda entry: (entry[1], entry[0]))


_W1G1_CARDS = _w1g1_restriction_cards()


#: Filler blockers, weakest first, so a cap has something to choose between and
#: a wrong prune is visible in which creatures survive it. None of them outpowers
#: Okk (4/4), which is what makes the comparison restriction bite.
_W1G1_FILLERS = (("Runt", 1, 1), ("Middling", 2, 2), ("Fatty", 4, 4), ("Bulk", 3, 3))


def _w1g1_shape(card, kind: str) -> tuple[int, int]:
    """How many filler blockers and attackers make *kind* actually bite.

    Derived from the printed payload rather than hardcoded, because the number
    is data: Orcish Conscripts' floor is two and Mogg Flunkies' printed "alone"
    is the same restriction with the number one, so a board that satisfies one
    silently satisfies the other and the census reports a pass it never earned.
    That is not hypothetical — the first draft of this census used one board for
    every card, and both company cards passed against the **unpruned** chooser.
    """
    payloads = [
        instruction.payload
        for instruction in compile_card_oracle(card).instructions
        if instruction.kind == kind
    ]
    if kind == "max_blockers_each_combat":
        # One over the cap, and two attackers because Caverns of Despair caps
        # attacks at the same number — the board has to be one its own other
        # half admits.
        cap = min(int(payload.get("count", 0)) for payload in payloads)
        return cap + 1, 2
    if kind == "cant_block_unless_others_block":
        # One short of the floor, so the creature printing it is the offender.
        needed = max(int(payload.get("count", 0)) for payload in payloads)
        return max(needed - 1, 0), 1
    # The comparison (Okk): one smaller creature beside it is enough.
    return 1, 1


def _w1g1_board(card, fillers: int, attackers: int):
    """A board where the AI defender has *fillers* creatures to block with and
    *card* is in play on its side.

    The restriction's permanent always sits with the **defender**: every
    sentence in this census is about blocking, and a creature carrying one is
    itself a blocker.
    """
    attacker_seat = PlayerState(name="P1")
    defender_seat = PlayerState(name="P2")
    game = Game(players=[attacker_seat, defender_seat])
    game.enforce_mana_costs = False
    for index in range(attackers):
        attacker_seat.battlefield.append(
            Permanent(card=_mk_creature_card(f"W1G1-A{index}", 3, 3))
        )
    for index in range(fillers):
        name, power, toughness = _W1G1_FILLERS[index % len(_W1G1_FILLERS)]
        defender_seat.battlefield.append(
            Permanent(card=_mk_creature_card(name, power, toughness))
        )
    defender_seat.battlefield.append(Permanent(card=card))
    game.start_turn(0)
    for permanent in attacker_seat.battlefield:
        _nosick(permanent)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    assert game.current_step == "declare_attackers"
    ok, why = game.declare_attackers(
        0, list(range(attackers)), defending_player_index=1
    )
    assert ok, why
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"
    return game


@pytest.mark.parametrize(
    "card_name,kind,card",
    _W1G1_CARDS,
    ids=[f"{name}-{kind}" for name, kind, _card in _W1G1_CARDS],
)
def test_the_ai_can_declare_a_legal_block_under_every_printed_restriction(
    card_name, kind, card
):
    """The AI's proposal is accepted, whatever the restriction.

    `declare_blockers` returning False here is the whole defect: the fallback
    below it is the **empty** declaration, so a refusal is a defender that
    blocks with nobody rather than one that blocks with fewer.
    """
    fillers, attackers = _w1g1_shape(card, kind)
    game = _w1g1_board(card, fillers, attackers)
    proposed = choose_combat_blockers(game, 1)
    ok, why = game.declare_blockers(1, proposed, acting_index=1)
    assert ok, f"{card_name} ({kind}): the AI proposed {proposed} and got {why!r}"


def test_the_block_census_is_not_empty():
    """A census that finds nothing reports zero and means nothing.

    All three kinds are in the pool today — the cap since Legends, the company
    floor since Ice Age (and again, spelled "alone", since Stronghold), the
    comparison since Urza's Saga — so an empty parametrisation means the
    derivation broke, not that the pool got simpler.
    """
    kinds = {kind for _name, kind, _card in _W1G1_CARDS}
    assert kinds == set(_W1G1_BLOCK_DECLARATION_KINDS), sorted(kinds)


def test_the_ai_keeps_its_best_blocks_under_a_cap(set_pool):
    """A cap is disobeyed by the *set*, so the engine can only name an arbitrary
    member — and it names the last one it was handed.

    `_legal_block_declaration` therefore hands the list over worst-block-last,
    scored by the same `_score_block_pair` that chose the blocks. Asserted
    because it is a choice, not a consequence: the engine naming
    `declared_blockers[-1]` would otherwise drop whichever creature happened to
    be last in battlefield order.
    """
    game = _w1g1_board(set_pool("LEG")["Caverns of Despair"], 3, 2)
    proposed = choose_combat_blockers(game, 1)
    names = {game.players[1].battlefield[i].card.name for i in proposed}

    assert len(proposed) == 2, "Caverns of Despair caps the declaration at two"
    assert "Middling" not in names, names
    assert game.declare_blockers(1, proposed, acting_index=1)[0]


def test_a_blocker_that_cannot_be_legal_is_dropped_rather_than_grounding_the_rest(
    set_pool,
):
    """Okk on a board with nothing bigger cannot block at all — and the prune
    has to drop *it*, not give up on the declaration.

    This is the shape that cost the whole seat: one creature the declaration
    cannot legally contain used to refuse every other block beside it.
    """
    game = _w1g1_board(set_pool("USG")["Okk"], 3, 1)
    proposed = choose_combat_blockers(game, 1)
    blocked = {game.players[1].battlefield[i].card.name for i in proposed}

    assert "Okk" not in blocked, blocked
    assert blocked, "dropping Okk must not drop everybody"
    assert game.declare_blockers(1, proposed, acting_index=1)[0]


# --- end W1G1 ---
