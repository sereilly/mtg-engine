"""A host being chosen for an Aura asks protection (CR 702.16c).

"A permanent or player with protection can't be enchanted by Auras that have
the stated quality." ``auras.enchant_card_refusal`` — the one predicate every
door that attaches an Aura, enters one attached or offers it a host asks —
read the enchant ability and CR 303.4's "can't be enchanted" effects and never
this sentence. So a black Aura card against a White Knight came back legal:
Takklemaggot's pick offered the Knight, Hakim, Iridescent Drake and Academy
Researchers each put an Aura onto a creature protected from it, and the
CR 702.16c state-based action then put the card into a graveyard the rules
say it never left (CR 303.4i: it "remains in its current zone"; CR 701.3b: an
attach to a host it can't be attached to "doesn't move" it). Measured by
Torment's wave 1 (W1G2) on Takklemaggot and the attach-to-source reanimation;
fixed in wave 2 (W2G2).

**What the predicate is not.** CR 702.16c's second sentence — an Aura already
attached is put into its owner's graveyard — is a state-based action with an
exemption, CR 702.16n ("this effect doesn't remove this Aura", Floating
Shield, White Ward), and it lives in ``check_state_based_actions``, which does
not call this predicate. The exemption is from the *sweep*: a second Aura with
the quality still can't become attached. Both halves are held below.

Validated backwards: on the base without the fix all five fail — Takklemaggot
offered the White Knight, Hakim and the Drake logged the CR 702.16c sweep,
the Researchers put Holy Strength from the hand into the graveyard, and the
CR 702.16n row passed its sweep half and failed its predicate half.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura, auras_attached_to
from engine.models import Permanent
from tests.helpers import resolve_stack

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def by_name(catalog_by_name):
    return catalog_by_name


def _game(*seats):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[]) for seat in range(len(seats))
    ])
    game.enforce_mana_costs = False
    for seat, permanents in enumerate(seats):
        for permanent in permanents:
            permanent.metadata["summoning_sickness_turn"] = -99
            game._put_permanent_onto_battlefield(seat, permanent, None)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return game


def _swept_by_protection(game) -> bool:
    return any("702.16c" in line for line in game.log)


# --- Takklemaggot: "chooses a creature that this card could enchant" --------


def test_takklemaggot_is_not_offered_a_creature_protected_from_it(by_name):
    """The pick is the choosing question, and a White Knight is protected from
    the black Takklemaggot: it is not offered and not accepted."""
    aura = Permanent(card=by_name["Takklemaggot"])
    host = Permanent(card=by_name["Grizzly Bears"])
    knight = Permanent(card=by_name["White Knight"])
    giant = Permanent(card=by_name["Hill Giant"])
    game = _game([], [host, knight, giant])
    game._put_permanent_onto_battlefield(0, aura, None)
    attach_aura(aura, host)
    game.interactive_seats = {1}

    host.damage_marked = 99
    game.check_state_based_actions()
    game.resolve_top_of_stack(pause_for_choices=True)

    choice = game.pending_choices_of("permanent_choice")[0]
    offered = [perm.card.name for perm in game.live_permanent_choices(choice)]
    assert offered == ["Hill Giant"]
    assert not game.confirm_permanent_choice(1, knight.permanent_id)
    assert game.confirm_permanent_choice(1, giant.permanent_id)
    returned = next(
        perm for perm in game.all_permanents() if perm.card.name == "Takklemaggot"
    )
    assert returned.metadata.get("attached_to") is giant


# --- the attach-to-source reanimations and the hand's -----------------------


def test_hakim_leaves_an_aura_he_is_protected_from_in_the_graveyard(by_name):
    """"Return target Aura card from your graveyard to the battlefield attached
    to Hakim." With Hakim protected from white, Holy Strength can't enchant
    him, so it stays where it is (CR 303.4i) — it does not enter, attach and
    get swept."""
    hakim = Permanent(card=by_name["Hakim, Loreweaver"])
    hakim.metadata["protection_from_white"] = True
    game = _game([hakim], [])
    game.players[0].graveyard.append(by_name["Holy Strength"])
    game.interactive_seats = set()
    game.start_turn(0)
    game.current_step = "upkeep"

    result = game.activate_permanent_ability(
        0, "Hakim, Loreweaver", permanent_index=game.battlefield_index_of(hakim),
        ability_index=0, target_permanent_index=0,
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert [card.name for card in game.players[0].graveyard] == ["Holy Strength"]
    assert auras_attached_to(hakim) == []
    assert not _swept_by_protection(game), game.log
    assert any("cannot enchant" in line for line in game.log), game.log


def test_iridescent_drake_leaves_an_aura_it_is_protected_from(by_name):
    """"…put target Aura card from a graveyard onto the battlefield under your
    control attached to this creature." The Drake wears a White Ward by the
    time its trigger resolves, so a white Aura card can't enchant it."""
    drake = Permanent(card=by_name["Iridescent Drake"])
    game = _game([], [])
    game.players[1].graveyard.append(by_name["Holy Strength"])
    game._put_permanent_onto_battlefield(0, drake, None)
    ward = Permanent(card=by_name["White Ward"])
    game._put_permanent_onto_battlefield(0, ward, None)
    attach_aura(ward, drake)

    resolve_stack(game)
    game.check_state_based_actions()

    assert [card.name for card in game.players[1].graveyard] == ["Holy Strength"]
    assert [aura.card.name for aura in auras_attached_to(drake)] == ["White Ward"]
    assert not _swept_by_protection(game), game.log


def test_academy_researchers_does_not_offer_an_aura_it_is_protected_from(by_name):
    """"…you may put an Aura card from your hand onto the battlefield attached
    to this creature." Protected from white, the Researchers carry no white
    Aura: the card stays in the hand rather than going to the graveyard by way
    of the battlefield."""
    researchers = Permanent(card=by_name["Academy Researchers"])
    researchers.metadata["protection_from_white"] = True
    game = _game([], [])
    game.players[0].hand = [by_name["Holy Strength"], by_name["Unholy Strength"]]
    game._put_permanent_onto_battlefield(0, researchers, None)

    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()

    assert [card.name for card in game.players[0].hand] == ["Holy Strength"]
    assert [aura.card.name for aura in auras_attached_to(researchers)] == [
        "Unholy Strength"
    ]
    assert game.players[0].graveyard == []
    assert not _swept_by_protection(game), game.log


# --- CR 702.16n: the exemption is the sweep's, not the host's ----------------


def test_an_aura_exempt_from_its_own_protection_stays_but_another_cannot_join(by_name):
    """White Ward gives protection from white and "doesn't remove this Aura":
    the sweep leaves it on. That is all the exemption says — a second white
    Aura still can't become attached (CR 702.16c's first sentence), which is
    the predicate's question; and asked of the Ward on its own host, the
    predicate does not call the Ward illegal there."""
    from engine.auras import aura_attach_refusal, enchant_card_refusal

    bears = Permanent(card=by_name["Grizzly Bears"])
    game = _game([bears], [])
    ward = Permanent(card=by_name["White Ward"])
    game._put_permanent_onto_battlefield(0, ward, None)
    attach_aura(ward, bears)
    game.check_state_based_actions()

    assert auras_attached_to(bears) == [ward], game.log
    assert aura_attach_refusal(game, ward, bears) is None
    assert enchant_card_refusal(game, by_name["Holy Strength"], 0, bears) is not None
    assert enchant_card_refusal(game, by_name["Unholy Strength"], 0, bears) is None


# --- the census: every caller is one of the doors above ---------------------

#: Every function in ``engine/`` that asks the host predicate, with the door it
#: is. A new caller fails here until it is read and added — and it is held to
#: the same question (a host being chosen), because no other question may ask
#: it: the state-based sweep's is CR 702.16n's, and it has its own.
_CALLERS = {
    # the predicate's own two halves
    ("engine/auras.py", "aura_attach_refusal"),
    # an Aura with an attach ability, or a Licid becoming one (CR 701.3)
    ("engine/equipment.py", "attachment_refusal"),
    # Enchantment Alteration's attach
    ("engine/handlers/attachments.py", "_attach_chosen_to_chosen"),
    # Enchantment Alteration's and Takklemaggot's picks
    ("engine/handlers/permanent_choices.py", "permanent_choice_candidates"),
    # Iridescent Drake (the filter is nested in the reanimation, and a nested
    # call is found under both names)
    ("engine/handlers/reanimation.py", "card_filter"),
    ("engine/handlers/reanimation.py", "reanimate_creature"),
    # Hakim, Loreweaver
    ("engine/handlers/reanimation.py", "reanimate_aura_onto_source"),
    # Takklemaggot's return attached
    ("engine/handlers/reanimation.py", "return_source_card_to_battlefield"),
    # Academy Researchers
    ("engine/handlers/hand.py", "put_from_hand_candidates"),
    # Replenish, Cleansing Meditation: the hosts offered, and asked once more
    # as each Aura enters
    ("engine/handlers/reanimation.py", "_legal_returning_aura_hosts"),
    ("engine/handlers/reanimation.py", "_return_planned_cards"),
}


def _callers() -> set:
    found = set()
    for path in sorted((ROOT / "engine").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(ROOT).as_posix()
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"enchant_card_refusal", "aura_attach_refusal"}
                ):
                    found.add((relative, function.name))
    return found


def test_every_caller_of_the_host_predicate_is_a_door_above():
    found = _callers()
    assert found == _CALLERS, (
        f"new: {sorted(found - _CALLERS)}; gone: {sorted(_CALLERS - found)}"
    )
    assert not any(
        path.startswith("engine/mixins/") for path, _name in found
    ), "no state-based sweep asks this: an attached Aura is CR 702.16n's question"
