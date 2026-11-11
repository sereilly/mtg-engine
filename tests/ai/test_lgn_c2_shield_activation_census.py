"""Over seeded games, every shield an AI seat puts up has something it could
stop: a census of where shield-only abilities are activated.

The population is every activation an AI seat makes, outside a rehearsal, of
an ability whose whole effect is a prevention or regeneration shield
(``ai_valuation.shields_only``). Each is read at the moment it is made:

* **in response** — something is on the stack;
* **in a fight** — the combat phase, with attackers declared and the combat
  not yet over;
* **before the fight** — the active seat's precombat main phase with a combat
  still to come. A shield there is the policy's to justify, so each is
  carried out again on a copy (``ai_abilities._land_ability_worth``, the
  gate the main-phase chooser asks) and must leave the seat ahead;
* **where it cannot matter** — everything else with an empty stack: a main
  phase with no combat to come (main phase 2), another step outside combat,
  a combat with nobody attacking or one already over.

``test_the_flat_score_put_shields_up_where_they_could_not_matter`` runs it
backwards — the shield scored flat as it was on a501c6c5 — and must find the
activations Phase 5 saw. Measured on that tree over these runs: 110 activations,
every one in a main phase with nothing on the stack (Urborg Phantom 32, Circle
of Protection: Red 30, Deftblade Elite 22, Crypt Sliver's granted
regeneration 12, Living Wall 8, Urborg Skeleton 4, Drudge Skeletons 2); after
it, none.
"""
from __future__ import annotations

import collections
from contextlib import ExitStack
from unittest import mock

import pytest

from engine import ai_abilities, ai_rehearsal, ai_simulator
from engine.ai_actions import ActivationAction
from engine.ai_rehearsal import combat_is_still_to_come
from engine.ai_valuation import shields_only
from engine.card_loader import manifest_set_path
from engine.game import Game

#: (set, seed, games, pinned): Deftblade Elite's own set; the regenerating
#: walls and a Circle of Protection in the base set; Urborg Phantom's.
RUNS = (
    ("LGN", 7, 4, ("Deftblade Elite",)),
    ("LGN", 11, 4, ("Deftblade Elite",)),
    ("LEA", 7, 3, ("Drudge Skeletons", "Living Wall", "Circle of Protection: Red")),
    ("INV", 7, 3, ("Urborg Phantom",)),
)


def _moment(game: Game, seat: int) -> str:
    if game.stack:
        return "in response"
    if game.current_turn_phase == "combat":
        attackers = game.get_combat_state().get("attackers") or []
        if attackers and game.current_step != "end_of_combat":
            return "in a fight"
        return "cannot matter"
    if game.current_turn_phase == "precombat_main" and combat_is_still_to_come(game, seat):
        return "before the fight"
    return "cannot matter"


def _shield_of(game: Game, seat: int, kwargs):
    index = kwargs.get("permanent_index")
    permanent = game.permanent_at(seat, index) if index is not None else None
    if permanent is None:
        return None
    usable = game.usable_abilities_of(permanent)
    which = kwargs.get("ability_index")
    ability = usable[which] if which is not None else (usable[0] if usable else None)
    if ability is None or not shields_only(ability.instruction):
        return None
    return permanent


def _census(*, flat: bool = False) -> dict:
    """The census; *flat* scores the shield as on a501c6c5 (backwards)."""
    found = {"moments": collections.Counter(), "unjustified": [], "weighed": 0, "rows": []}

    def spy(original):
        def wrapped(self, seat, name, *args, **kwargs):
            row = None
            if not ai_rehearsal.rehearsing() and _shield_of(self, seat, kwargs) is not None:
                moment = _moment(self, seat)
                justified = True
                if moment == "before the fight":
                    # The lands are already tapped; the mana is in the pool.
                    again = ActivationAction(
                        permanent_name=name, permanent_index=kwargs.get("permanent_index"),
                        target_player_index=kwargs.get("target_player_index"),
                        land_tap_indices=(), score=0.0,
                        target_permanent_ids=kwargs.get("target_permanent_ids"),
                        target_graveyard_indices=kwargs.get("target_graveyard_indices"),
                        target_role_refs=kwargs.get("target_role_refs"),
                        ability_index=kwargs.get("ability_index"),
                    )
                    justified = ai_abilities._land_ability_worth(self, seat, again) is not None
                row = (name, moment, justified)
            result = original(self, seat, name, *args, **kwargs)
            if row is not None and getattr(result, "supported", False):
                found["moments"][row[1]] += 1
                found["rows"].append(row)
                if not row[2]:
                    found["unjustified"].append(row)
            return result
        return wrapped

    def weighed(instruction):
        answer = shields_only(instruction)
        found["weighed"] += bool(answer)
        return answer

    with ExitStack() as stack:
        for method in ("activate_permanent_ability", "queue_permanent_ability"):
            stack.enter_context(mock.patch.object(Game, method, spy(getattr(Game, method))))
        stack.enter_context(mock.patch.object(
            ai_abilities, "shields_only", (lambda instruction: False) if flat else weighed,
        ))
        if flat:
            # Backwards means the flat score, so the rehearsed "moves
            # nothing" gate every other ability meets since kg4
            # (`ai_abilities._moves_something`) — a second layer that also
            # passes over an idle shield — is off too.
            stack.enter_context(mock.patch.object(
                ai_abilities, "_moves_something", lambda *args, **kwargs: True,
            ))
        for code, seed, games, pinned in RUNS:
            report = ai_simulator.run_ai_simulation(
                manifest_set_path(code), games=games, seed=seed, max_turns=14,
                required_cards=pinned,
            )
            assert report.games_completed == games, code
            assert report.rehearsals_raised == {}, (code, report.rehearsals_raised)
    return found


@pytest.mark.full
def test_every_shield_an_ai_seat_puts_up_has_something_to_stop():
    found = _census()
    assert found["moments"]["cannot matter"] == 0, found["rows"]
    assert found["unjustified"] == [], found["unjustified"]
    # The floor: the main-phase chooser weighed a shield this many times.
    assert found["weighed"] >= 50, found["weighed"]


@pytest.mark.full
def test_the_flat_score_put_shields_up_where_they_could_not_matter():
    """Backwards: the shield scored flat, as on a501c6c5."""
    found = _census(flat=True)
    idle = len(found["unjustified"]) + found["moments"]["cannot matter"]
    assert idle >= 50, found["moments"]
    names = {row[0] for row in found["rows"]}
    assert {"Deftblade Elite", "Circle of Protection: Red"} <= names, names
