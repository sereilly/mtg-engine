"""Census: a record about one exiled card names that card and no copy of it
(CR 400.7, 406.3, 406.7).

A deck repeats one immutable ``CardDefinition`` per copy and the catalog is
shared between seats, so before ``Game.put_card_into_exile`` an exile could
hold one Python object at two positions — and every record about an exiled
card (a linked-exile entry, an ``ExiledRecord``, a while-exiled grant, a cast
permission, a delayed ability's "those cards") names its object, while every
reader maps the object back to the *first* position holding it. Which copy is
face down, which copy leaves, whose permission plays it, whose counters and
lookers it carries and whether "as long as any of those cards remain exiled"
ends were all answered for whichever copy came first.

**The population is every road in the pool that puts a card into exile**: each
card (both manifest roles, every face) whose text says "exile", cast by the
catalog sweep's generic recipe and, if it is a permanent, each of its
activated abilities activated once. Before the road runs, **both** seats'
exiles are seeded with one copy of every object in the game — the cards in
both libraries, hands, graveyards and on the battlefield, the card itself
among them — and seat 0's seeded copies are recorded the way Three Wishes
records its cards: face down, seat 0 the one seat that may look, castable by
seat 0 for as long as they remain exiled. So whatever the road exiles meets a
copy of itself, in its own exile and in the other seat's, from another exiling
effect that kept a record. Then each reader is asked which copy it means:

* **no exile holds one object twice** — across both seats;
* **every record the road wrote names its own card**: no live linked-exile
  entry, exile record, exile cast permission or delayed "those cards" record
  written during the road names a seeded object;
* **the seeded records still mean the seeded cards**: the face-down register
  hides exactly the seeded copies still there from seat 1 (and none from seat
  0, who may look), and the seeded permission covers no card the road exiled.

A road that raises is the catalog sweep's to report (it asserts no card
raises) and is left out here, with a floor on how many roads were examined.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_permissions import grant_permission, permission_for

from engine.exiled_records import ExiledRecord, live_records, record_exiled_card
from engine.faces import compilation_units
from engine.linked_exile import face_down_exiled_cards, linked_entries
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _pool():
    return load_cards(manifest_set_paths(include_measured=True))


def _by_name(pool):
    return {card.name: card for card in pool}


def _population():
    seen = set()
    rows = []
    for card in compilation_units(_pool()):
        if card.name in seen or "exile" not in (card.oracle_text or "").lower():
            continue
        seen.add(card.name)
        rows.append(card)
    return rows


def _is_permanent_card(card) -> bool:
    line = (card.type_line or "").lower()
    return not ("instant" in line or "sorcery" in line)


def _table(by_name, card):
    """The catalog sweep's board, with the card under test in seat 0's hand."""
    basics = [by_name[name] for name in ("Island", "Plains", "Swamp", "Mountain", "Forest")]
    bear = by_name["Grizzly Bears"]
    lotus = by_name["Black Lotus"]
    bad_moon = by_name["Bad Moon"]
    me = PlayerState(
        name="P1", hand=[card], library=basics * 4,
        battlefield=[Permanent(card=bear), Permanent(card=basics[1]),
                     Permanent(card=lotus), Permanent(card=bad_moon)],
        graveyard=[bear],
    )
    opp = PlayerState(
        name="P2", hand=[basics[0], basics[1], bear], library=basics * 4,
        battlefield=[Permanent(card=bear, tapped=True), Permanent(card=basics[0]),
                     Permanent(card=lotus), Permanent(card=bad_moon)],
        graveyard=[bear],
    )
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    return game


def _seed(game):
    """One copy of every object in the game into both seats' exiles, seat 0's
    recorded as Three Wishes records its cards. Returns the seeded objects and
    the seeded permission."""
    objects: list = []
    for player in game.players:
        for zone in (player.library, player.hand, player.graveyard):
            for card in zone:
                if not any(card is held for held in objects):
                    objects.append(card)
        for permanent in player.battlefield:
            if not any(permanent.card is held for held in objects):
                objects.append(permanent.card)
    for player in game.players:
        player.exile.extend(objects)
    for card in objects:
        record_exiled_card(game, card, 0, face_down=True, looker_index=0)
    permission = grant_permission(
        game, player_index=0, zone="exile", mode="play", cards=list(objects),
        duration="while_exiled", source_name="seeded record",
    )
    return objects, permission


def _drive(game, card) -> None:
    game.start_turn(0)
    game._close_current_priority_step()
    game.cast_from_hand(0, card.name, target_player_index=1, x_value=2)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    if not _is_permanent_card(card):
        return
    for index, _ability in enumerate(compile_card_oracle(card).activated_abilities):
        if not any(perm.card is card for perm in game.all_permanents()):
            break
        game.activate_permanent_ability(
            0, card.name, ability_index=index, target_player_index=1,
        )
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        resolve_stack(game)


def _record_objects(game, seeded_permission, before_records):
    """``(what, object)`` for every record of an exiled card the road may have
    written: linked entries, exile records, exile permissions and delayed
    "those cards" records."""
    named = []
    for permanent in [*game.all_permanents(), *(p for pl in game.players for p in pl.phased_out)]:
        for entry in linked_entries(permanent):
            named.append(("linked entry", entry.get("card")))
    for record in live_records(game):
        if not any(record is held for held in before_records):
            named.append(("exile record", record.card))
    for permission in game.cast_permissions:
        if permission is seeded_permission or permission.zone != "exile":
            continue
        for card in permission.cards or ():
            named.append(("cast permission", card))
    for entry in game.delayed_triggers:
        for value in (getattr(entry, "captured", None) or {}).values():
            for item in value if isinstance(value, (list, tuple)) else (value,):
                if isinstance(item, ExiledRecord):
                    named.append(("delayed record", item.card))
    return named


def _ask(game, card, seeded, seeded_permission, before_records):
    problems = []
    positions = [held for player in game.players for held in player.exile]
    # The seeding itself put each seeded object once into each seat's exile —
    # the shared-object state a table starts from — so a seeded object may be
    # held twice and anything else once. One more is a road's arrival that
    # did not become a new object.
    doubled = sorted({
        held.name for held in positions
        if sum(1 for other in positions if other is held)
        > (len(game.players) if any(held is s for s in seeded) else 1)
    })
    if doubled:
        problems.append(f"an arrival is an object exile already held: {doubled}")
    for what, named in _record_objects(game, seeded_permission, before_records):
        if named is None or not any(named is held for held in positions):
            continue
        if any(named is held for held in seeded):
            problems.append(f"a {what} names the seeded copy of {named.name}")
    still = [held for held in game.players[0].exile if any(held is s for s in seeded)]
    hidden_from_opponent = face_down_exiled_cards(game, 0, 1)
    if sum(
        1 for held in hidden_from_opponent if any(held is s for s in seeded)
    ) != len(still):
        problems.append("the seeded face-down copies are no longer what is hidden")
    if any(any(held is s for s in seeded) for held in face_down_exiled_cards(game, 0, 0)):
        problems.append("a seeded copy is hidden from the seat that may look at it")
    for held in game.players[0].exile:
        if any(held is s for s in seeded):
            continue
        granted = permission_for(game, 0, held, "exile", as_land=held.primary_type == "land")
        if granted is seeded_permission:
            problems.append(f"the seeded permission covers the road's {held.name}")
    return problems


def test_the_population_is_every_road_that_exiles():
    rows = _population()
    assert len(rows) >= 300, len(rows)


def test_every_record_names_its_own_exiled_card():
    _census(_population())


def _census(rows):
    by_name = _by_name(_pool())
    failures = []
    examined = 0
    exiled_something = 0
    for card in rows:
        game = _table(by_name, card)
        seeded, permission = _seed(game)
        before_records = list(live_records(game))
        before = sum(len(player.exile) for player in game.players)
        try:
            _drive(game, card)
        except Exception:  # the catalog sweep's to report
            continue
        examined += 1
        if sum(len(player.exile) for player in game.players) > before:
            exiled_something += 1
        problems = _ask(game, card, seeded, permission, before_records)
        if problems:
            failures.append((card.name, problems))
    assert examined >= len(rows) * 0.9, (examined, len(rows))
    assert exiled_something >= max(1, len(rows) // 10), exiled_something
    assert not failures, (
        f"{len(failures)} of {examined} exiling roads ({exiled_something} of which "
        f"exiled something) wrote or read a record of the wrong copy:\n"
        + "\n".join(f"  {name}: {problems}" for name, problems in failures[:40])
    )
