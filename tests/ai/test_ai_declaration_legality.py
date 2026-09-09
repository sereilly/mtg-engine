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
