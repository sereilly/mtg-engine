"""Census: the game log does not tell the table which card a private look or
a private search put into a hand (CR 701.20e, CR 400.2).

"Look at the top four cards of your library. Put one of them into your hand
and the rest on the bottom of your library in any order." (Impulse.) To look
is not to reveal: the hand and the library are hidden zones, and nobody but
the player looking learns which card was kept. ``game.log`` is one list, sent
to every seat and every spectator — and the look's resolver wrote "Host put
<card name> into their hand and the rest away" into it. So did the search's:
Demonic Tutor's find was in the log by name.

The two lines of ``_resolve_look_top_pick`` and the search lines beside them
name a card now only when the table may know it: the card's sentence revealed
it (``revealed``; a pick narrowed to a type, which is always printed "reveal";
a search printed "reveal it"), or it went somewhere public.

The census drives **every** card in both manifest roles whose compiled program
runs one of the two, through the entry point its own text gives it (a cast, an
activation, an entry or upkeep trigger, an ability activated from the hand),
over a library of cards with names nothing else on the table says — and reads
the whole log for the name of any card that ended in a hidden zone.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from tests.helpers import _nosick, resolve_stack

#: The library every probe looks through or searches, top first: one card of
#: each type a printed narrowing in the pool could ask for, each with a name
#: no rule text, prompt or other log line on the census board mentions.
_LIBRARY = (
    "Serra Angel", "Black Lotus", "Crusade", "Savannah Lions", "Juggernaut",
    "Tundra", "Swords to Plowshares", "Wrath of God", "Shivan Dragon", "Glasses of Urza",
)

_LOOK = "look_top_pick_to_hand"
_SEARCH = "search_library"


def _pool() -> list:
    return list(compilation_units(load_cards(manifest_set_paths(include_measured=True))))


@pytest.fixture(scope="module")
def pool():
    return _pool()


@pytest.fixture(scope="module")
def by_name(pool):
    names: dict = {}
    for card in pool:
        names.setdefault(card.name, card)
    return names


def _walk(value):
    if isinstance(value, OracleInstruction):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _walk(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _walk(inner)


def _where(card, program, kind):
    """``(shape, index, step)`` for the first *kind* step in *program*: where
    it is printed, which is what says how the card is driven. A permanent's
    ``instructions`` mirror its abilities, so only a spell is read as one."""
    if card.primary_type in ("instant", "sorcery"):
        for step in _walk(list(program.instructions)):
            if step.kind == kind:
                return "spell", None, step
    for index, ability in enumerate(program.activated_abilities):
        for step in _walk(ability.instruction):
            if step.kind == kind:
                return "activated", index, step
    for index, trigger in enumerate(program.triggered_abilities):
        for step in _walk(trigger.instruction):
            if step.kind == kind:
                return f"trigger:{trigger.condition.kind}", index, step
    return None


def finders(pool, kind) -> list[tuple]:
    """``(card, shape, ability index, step)`` for every supported card whose
    program runs *kind*."""
    found = []
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        where = _where(card, program, kind)
        if where is not None:
            found.append((card, *where))
    return found


def _drive(by_name, card, shape, index=None) -> Game | None:
    """Run *card*'s look or search for seat 0 with every answer defaulted, on
    the entry point *shape* names. None when the card could not be driven."""
    library = [by_name[name] for name in _LIBRARY]
    lands = [_nosick(Permanent(card=by_name[name]))
             for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]
    creature = _nosick(Permanent(card=by_name["Grizzly Bears"]))
    is_spell = card.primary_type in ("instant", "sorcery")
    hand_ability = shape == "activated" and "discard this card" in (card.oracle_text or "").lower()
    on_board = not is_spell and not hand_ability and (
        shape == "activated" or shape.startswith("trigger:upkeep")
    )
    board = lands + [creature] + ([_nosick(Permanent(card=card))] if on_board else [])
    game = Game(players=[
        PlayerState(name="Looker", battlefield=board, library=list(library),
                    hand=[] if on_board else [card],
                    graveyard=[by_name["Hill Giant"]]),
        PlayerState(name="Other", library=[by_name["Forest"]] * 6,
                    battlefield=[_nosick(Permanent(card=by_name["Hill Giant"]))]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)

    def settle() -> None:
        for _ in range(12):
            resolve_stack(game)
            if not game.pending_choices:
                return
            game.auto_resolve_pending_choices()

    settle()
    if on_board and shape == "activated":
        result = game.activate_permanent_ability(0, card.name, ability_index=index)
        if not result.supported:
            result = game.activate_permanent_ability(
                0, card.name, ability_index=index, target_player_index=0,
                cost_permanent_ids=[creature.permanent_id],
            )
        if not result.supported:
            return None
    elif on_board:
        # An upkeep trigger: the turn after next is this seat's again.
        game.start_next_turn()
        settle()
        game.start_next_turn()
    elif shape == "activated":
        # An ability activated from the hand ("{1}{U}, Discard this card:").
        if not game.activate_from_hand(0, card.name).supported:
            return None
    else:
        spec = game.cast_target_spec(0, card)
        aimed = {}
        entries = spec.get("valid_targets") or []
        if spec.get("requires_target") and entries:
            first = next((e for e in entries if e.get("kind") == "player" and e["seat"] == 1), entries[0])
            if first.get("kind") == "player":
                aimed = {"target_player_index": first["seat"]}
            elif first.get("kind") == "permanent":
                aimed = {"target_permanent_ids": [
                    game.permanent_at(first["seat"], first["index"]).permanent_id
                ]}
        if not game.queue_from_hand(0, card.name, **aimed).supported:
            return None
    settle()
    return game


def _hidden_names(game) -> set[str]:
    """The census library's cards that are now in seat 0's hand or library —
    the zones nobody else may read."""
    player = game.players[0]
    return {
        held.name for held in (*player.hand, *player.library) if held.name in _LIBRARY
    }


def _taken_into_hand(game) -> set[str]:
    return {held.name for held in game.players[0].hand if held.name in _LIBRARY}


def _named_in_log(game, names) -> list[str]:
    return sorted(name for name in names if any(name in line for line in game.log))


def run_census(pool, by_name, kind) -> dict:
    """``{card name: (hidden names the log gives away, names taken into hand)}``
    for every card driven, plus the ones that could not be."""
    result = {"driven": {}, "undriven": []}
    for card, shape, _index, step in finders(pool, kind):
        payload = step.payload or {}
        if payload.get("zone_owner_target") or payload.get("pile_owner") or payload.get("looker"):
            # Another seat's library: whose hidden zone it is, and who may
            # know, is a different question with its own tests.
            continue
        game = _drive(by_name, card, shape, _index)
        if game is None:
            result["undriven"].append(f"{card.name} ({shape})")
            continue
        taken = _taken_into_hand(game)
        result["driven"][card.name] = (_named_in_log(game, _hidden_names(game)), sorted(taken))
    return result


def test_a_private_look_does_not_put_the_kept_card_in_the_log(pool, by_name):
    """Every look-and-pick card: no card that ended in the looker's hand or
    library is named anywhere in the log, unless the card's own text showed it.

    Before — measured by handing ``Game.find_is_public`` back the answer the
    old strings gave, "always" — ten cards named a kept card their text never
    reveals: Ancestral Memories, Browse, Diabolic Vision, Impulse, Prophetic
    Bolt, Raven Familiar, See the Truth, Sleight of Hand, Waker of Waves and
    Worldly Counsel. (Preferred Selection is the eleventh printing of the
    line; with every answer defaulted it buries a card instead of taking one.)
    Eye of Yawgmoth and Reviving Vapors named theirs then and name it now:
    they say "reveal".
    """
    census = run_census(pool, by_name, _LOOK)
    driven = census["driven"]
    shows_its_pick = {
        name for name, (leaked, _taken) in driven.items() if leaked
    }
    took_a_card = {name for name, (_leaked, taken) in driven.items() if taken}

    assert len(driven) >= 13, (sorted(driven), census["undriven"])
    assert len(took_a_card) >= 11, sorted(took_a_card)
    # The only looks that name what they took are the ones printed "reveal".
    for name in shows_its_pick:
        text = (by_name[name].oracle_text or "").lower()
        assert "reveal" in text, (name, driven[name])


def test_a_private_search_does_not_put_the_find_in_the_log(pool, by_name):
    """Every search of the searcher's own library: a find that ended in a
    hand or back in the library is named only where the card says "reveal".

    Before, measured the same way, seven searches named a find their text
    never reveals: Demonic Tutor, Diabolic Intent, Doomsday (all five of its
    cards, twice over), Grim Tutor, Planar Portal, Rhystic Tutor and Vampiric
    Tutor. The nine that still name theirs all print "reveal".
    """
    census = run_census(pool, by_name, _SEARCH)
    driven = census["driven"]
    leaking = {name: leaked for name, (leaked, _taken) in driven.items() if leaked}

    assert len(driven) >= 100, (len(driven), census["undriven"][:10])
    for name, leaked in leaking.items():
        text = (by_name[name].oracle_text or "").lower()
        assert "reveal" in text, (name, leaked)
    hidden_finds = {name for name, (_leaked, taken) in driven.items() if taken}
    assert len(hidden_finds) >= 12, len(hidden_finds)
    assert len(leaking) >= 8, "the searches printed 'reveal' still name their find"
