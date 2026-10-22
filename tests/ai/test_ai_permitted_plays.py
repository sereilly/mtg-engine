"""An AI seat casts what an effect lets it cast from outside its hand.

CR 601.3: a player may begin to cast a spell only if a rule or an effect
allows it. The rule is the hand; everything else is an effect — "you may play
cards exiled this way", "you may cast spells from your graveyard", "you may
cast it without paying its mana cost for as long as it remains exiled" — and
eighteen shipped cards print one. The engine has offered those cards to a
human seat since each shipped (`cast_permissions.playable_from_zones`, the
browser's zone badge). The AI's chooser walked its hand and its command zone,
so a seat paid for the permission and never used it: in a seeded Planeshift
run with Planeswalker's Mischief pinned, 87 activations bought no cast.

The census below is over **the grants the pool prints**, each read off the
compiled card (`grant_cast_permission`'s payload) and granted over a card it
admits — in the seat's own pile and, for an exile, in the opponent's
(CR 400.3: Psychic Theft's card stays in its owner's exile). For each: the
engine offers it, the policy proposes it, the simulator's executor casts it
from that pile, a free one taps nothing, and a land goes through the
land-drop pass. The three permissions that are read off a permanent's or the
card's own text rather than granted (Aluren, Yawgmoth's Agenda, Demonic
Embrace) and one real grant (Planeswalker's Mischief) are driven whole.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_policy import choose_cast_action, choose_land_drop
from engine.ai_simulator import (SimulationReport, _play_activations,
                                 _play_land_drops, _play_one_cast)
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_permissions import grant_permission, playable_from_zones
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_POOL: dict = {}
for _card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
    _POOL.setdefault(_card.name, _card)


def _report() -> SimulationReport:
    return SimulationReport(games_requested=1, games_completed=0, interaction_count=0)


def _table(mine=(), theirs=()) -> Game:
    forest = _POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", library=[forest] * 20),
        PlayerState(name="Opp", library=[forest] * 20),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_POOL[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            permanent.tapped = False
    game.auto_resolve_pending_choices()
    return game


def _deep(value):
    """Every instruction reachable from *value*, delayed triggers included."""
    if hasattr(value, "kind") and hasattr(value, "payload"):
        yield value
        for inner in (value.payload or {}).values():
            yield from _deep(inner)
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _deep(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _deep(inner)


def _printed_grants() -> list[tuple[str, dict]]:
    """``(card name, payload)`` for every distinct `grant_cast_permission` a
    shipped card compiles to."""
    found: dict = {}
    for name, card in sorted(_POOL.items()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        roots = [
            *program.instructions,
            *(a.instruction for a in program.activated_abilities),
            *(a.instruction for a in program.triggered_abilities),
        ]
        for step in (step for root in roots for step in _deep(root)):
            if step.kind != "grant_cast_permission":
                continue
            payload = dict(step.payload or {})
            key = (name, payload.get("zone"), payload.get("mode"), bool(payload.get("free")))
            found.setdefault(key, payload)
    return [(key[0], payload) for key, payload in found.items()]


def _subject(payload: dict):
    """A card the grant admits and the seat can aim: a red instant where it
    names instants, sorceries or a colour; a vanilla creature otherwise."""
    if payload.get("card_types") or payload.get("colors"):
        return _POOL["Lightning Bolt"]
    return _POOL["Grizzly Bears"]


def _grant(game: Game, payload: dict, card, owner_seat: int):
    """The permission *payload* describes, over *card* in *owner_seat*'s pile."""
    zone = payload["zone"]
    pile = getattr(game.players[owner_seat], zone)
    if zone == "library":
        pile.insert(0, card)
    else:
        pile.append(card)
    return grant_permission(
        game,
        player_index=0,
        zone=zone,
        mode=payload.get("mode", "cast"),
        cards=None if payload.get("blanket") else [card],
        card_types=tuple(payload.get("card_types") or ()),
        free=bool(payload.get("free")),
        exile_instead=bool(payload.get("exile_instead")),
        duration=payload.get("duration"),
        position=payload.get("position"),
        zone_player_index=None if owner_seat == 0 else owner_seat,
    )


def test_every_grant_the_pool_prints_is_one_the_ai_takes():
    """**Permitted cards proposed of permitted cards castable.** Before: none
    — the chooser never looked outside the hand."""
    grants = _printed_grants()
    assert len({name for name, _ in grants}) >= 15, sorted({n for n, _ in grants})
    castable = proposed = cast = lands = 0
    for name, payload in grants:
        zone = payload["zone"]
        if zone == "hand":
            continue  # a waiver over the hand: the Aluren test below
        if payload.get("flashback"):
            # A granted flashback (Recoup): its price is the chosen card's
            # mana cost, built as the grant resolves — a cast under a required
            # alternative cost, which is `tests/ai/test_ai_zone_casts.py`'s.
            continue
        seats = (0, 1) if zone == "exile" else (0,)
        for owner_seat in seats:
            card = _subject(payload)
            game = _table(mine=["Mountain", "Forest", "Forest"], theirs=["Hill Giant"])
            _grant(game, payload, card, owner_seat)
            label = (name, zone, "own" if owner_seat == 0 else "theirs")
            offered = [
                entry for entry in playable_from_zones(game, 0)
                if entry["zone"] == zone and entry["name"] == card.name
            ]
            assert offered and offered[0]["owner_seat"] == owner_seat, label
            castable += 1

            action = choose_cast_action(game, 0)
            assert action is not None and action.card_name == card.name, (label, action)
            assert action.from_zone == zone, label
            assert (action.zone_seat or 0) == owner_seat, label
            proposed += 1
            free = bool(payload.get("free"))
            assert bool(action.land_tap_indices) != free, (label, action.land_tap_indices)

            report = _report()
            life = game.players[1].life
            assert _play_one_cast(game, 0, report, 1, 1), (label, game.log[-4:])
            resolve_stack(game)
            assert not report.refused_casts and not report.issues, (label, report.refused_casts)
            assert not any(
                held is card for held in getattr(game.players[owner_seat], zone)
            ), label
            assert f"[from {zone}]" in report.log_lines[-1], report.log_lines
            tapped = sum(1 for p in game.controlled_by(0) if p.tapped)
            assert tapped == (0 if free else int(card.cmc)), (label, tapped)
            if card.primary_type == "creature":
                assert any(p.card is card for p in game.controlled_by(0)), label
            else:
                assert life - game.players[1].life == 3 or any(
                    c.name == "Hill Giant" for c in game.players[1].graveyard
                ), (label, game.log[-4:])
            cast += 1

        # "You may **play**…" covers a land (CR 305.1), through the land-drop
        # pass and at the price of the turn's land drop.
        if payload.get("mode") == "play" and not payload.get("card_types"):
            land = _POOL["Swamp"]
            game = _table(mine=["Forest"])
            _grant(game, payload, land, 0)
            action = choose_land_drop(game, 0)
            assert action is not None and action.from_zone == zone, (name, action)
            report = _report()
            _play_land_drops(game, 0, report, 1, 1)
            assert report.lands_played == 1 and not report.refused_casts, (name, report.refused_casts)
            assert any(p.card is land for p in game.controlled_by(0)), name
            assert choose_land_drop(game, 0) is None, "the turn's one land drop is spent"
            lands += 1

    assert proposed == castable == cast, (castable, proposed, cast)
    assert castable >= 20 and lands >= 6, (castable, lands)


def test_aluren_makes_a_cheap_creature_free_and_no_land_is_tapped_for_it():
    """"Any player may cast creature spells with mana value 3 or less without
    paying their mana costs." With no land at all the seat held the creature
    all game; with lands it tapped them for a cast that spent none of it."""
    game = _table(mine=["Aluren"])
    game.players[0].hand = [_POOL["Grizzly Bears"]]
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Grizzly Bears"

    game = _table(mine=["Aluren", "Forest", "Forest"])
    game.players[0].hand = [_POOL["Grizzly Bears"], _POOL["Craw Wurm"]]
    report = _report()
    assert _play_one_cast(game, 0, report, 1, 1), game.log[-4:]
    resolve_stack(game)
    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0))
    assert not any(p.tapped for p in game.controlled_by(0)), "no land was tapped for a free spell"
    assert any("without paying its mana cost" in line for line in game.log)
    # …and the six-drop the waiver does not reach is still judged by its cost.
    assert choose_cast_action(game, 0) is None


def test_yawgmoths_agenda_opens_the_graveyard_to_a_land_and_then_a_spell():
    """"You may play lands and cast spells from your graveyard." A land through
    the land-drop pass, then a creature paid for with it."""
    game = _table(mine=["Yawgmoth's Agenda", "Forest"])
    seat = game.players[0]
    seat.graveyard.extend([_POOL["Forest"], _POOL["Grizzly Bears"]])
    report = _report()
    _play_land_drops(game, 0, report, 1, 1)
    assert report.lands_played == 1, report.refused_casts
    assert [c.name for c in seat.graveyard] == ["Grizzly Bears"]

    assert _play_one_cast(game, 0, report, 1, 1), game.log[-4:]
    resolve_stack(game)
    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0))
    assert seat.graveyard == [] and not report.refused_casts
    assert sum(1 for p in game.controlled_by(0) if p.tapped) == 2


def test_demonic_embrace_is_cast_from_the_graveyard_but_never_with_the_last_life():
    """"You may cast this card from your graveyard by paying 3 life and
    discarding a card in addition to paying its other costs." Proposed with
    life to spare; never at a life total the price would take to zero
    (`ai_cast_gates._cast_life_price`: a cost paid in life is not paid with the
    seat's last point)."""
    embrace = _POOL["Demonic Embrace"]

    def board(life: int) -> Game:
        game = _table(mine=["Swamp", "Swamp", "Swamp", "Grizzly Bears"])
        game.players[0].graveyard.append(embrace)
        game.players[0].hand = [_POOL["Swamp"], _POOL["Swamp"]]
        game.players[0].life = life
        # The turn's land drop is spent, so the lands in hand are only cards.
        game.players[0].lands_played_this_turn = 1
        return game

    game = board(20)
    if choose_land_drop(game, 0) is not None:
        _play_land_drops(game, 0, _report(), 1, 1)
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Demonic Embrace", action
    assert action.from_zone == "graveyard"
    report = _report()
    hand = len(game.players[0].hand)
    assert _play_one_cast(game, 0, report, 1, 1), game.log[-4:]
    resolve_stack(game)
    assert game.players[0].life == 17 and len(game.players[0].hand) == hand - 1
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert bears.effective_power == 5 and game._has_keyword(bears, "flying")

    game = board(3)
    if choose_land_drop(game, 0) is not None:
        _play_land_drops(game, 0, _report(), 1, 1)
    assert choose_cast_action(game, 0) is None


def test_planeswalkers_mischief_buys_the_cast_it_pays_for():
    """"{3}{U}: Target opponent reveals a card at random from their hand. If
    it's an instant or sorcery card, exile it. You may cast it without paying
    its mana cost for as long as it remains exiled." The activation, then the
    opponent's own Lightning Bolt cast at them out of their exile, for
    nothing."""
    game = _table(mine=["Planeswalker's Mischief", "Island", "Island", "Island", "Island"])
    bolt = _POOL["Lightning Bolt"]
    game.players[1].hand = [bolt]
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Planeswalker's Mischief"
    report = _report()
    _play_activations(game, 0, report, 1, 1)
    resolve_stack(game)
    assert not report.refused_activations, report.refused_activations
    assert any(held is bolt for held in game.players[1].exile), game.log[-6:]

    cast = choose_cast_action(game, 0)
    assert cast is not None and cast.card_name == "Lightning Bolt", cast
    assert (cast.from_zone, cast.zone_seat, cast.land_tap_indices) == ("exile", 1, ())
    assert _play_one_cast(game, 0, report, 1, 1), game.log[-4:]
    resolve_stack(game)
    assert game.players[1].life == 17, game.log[-6:]
    assert not any(held is bolt for held in game.players[1].exile)
    assert not report.refused_casts


def test_a_card_mischief_took_is_cast_rather_than_handed_back():
    """The same activation at an opposing Shriek of Dread, "target creature
    gains fear until end of turn", with nothing on the other side to block:
    fear does nothing — and "at the beginning of the next end step, if you
    haven't cast it, return it to its owner's hand" makes the cast a card
    the opponent does not get back. A rehearsal that ran its copy straight
    to the cleanup step never saw that end step (CR 513.1), and with the
    card's own trip out of exile taken out of what it did, held it."""
    game = _table(mine=[
        "Planeswalker's Mischief", "Grizzly Bears", "Island", "Island", "Island", "Island",
    ])
    shriek = _POOL["Shriek of Dread"]
    game.players[1].hand = [shriek]
    report = _report()
    _play_activations(game, 0, report, 1, 1)
    resolve_stack(game)
    assert any(held is shriek for held in game.players[1].exile), game.log[-6:]

    cast = choose_cast_action(game, 0)
    assert cast is not None and cast.card_name == "Shriek of Dread", cast
    assert (cast.from_zone, cast.zone_seat) == ("exile", 1)
    assert _play_one_cast(game, 0, report, 1, 1), game.log[-4:]
    resolve_stack(game)
    game.resolve_end_step(0)
    resolve_stack(game)
    assert not any(held is shriek for held in game.players[1].hand), game.log[-6:]
