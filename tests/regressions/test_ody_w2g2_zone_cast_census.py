"""Census: does an AI seat cast a card an **effect** lets it cast from outside
its hand (CR 601.3) — and does the cast it proposes go through?

Until Odyssey's wave 2 ``ai_policy.choose_cast_action`` walked the hand and the
command zone and nothing else. So no AI seat, in a simulated game or as a
human's opponent in the web app, had ever cast a spell from a graveyard, an
exile or a library: the second half of every flashback card (CR 702.34a —
Odyssey's headline mechanic, 28 cards), a graveyard under Yawgmoth's Will, the
card an Elkin Bottle exiled, the top of a library under a Temporal Aperture.
W1G3 pinned eight flashback cards into eighteen seeded games and counted the
casts of them: every one from hand, none from a graveyard. Nothing was refused
and no issue was raised — each card was cast once, it resolved, and the run
read clean.

Two sweeps, both over **both manifest roles** and both carrying a floor.

**The flashback sweep** is the round's subject: every card that prints a
flashback cost, in its caster's graveyard on a board that offers it a target
and the lands to pay. The seat must propose it *from the graveyard*, the
proposal must be accepted by the cast path, the lands it tapped must be exactly
the flashback cost (no mana left floating, none short), and the card must end
in exile. Then again under "Flashback costs you pay cost {2} less" on each
side of the table (Catalyst Stone) and under a tax on every spell (Sphere of
Resistance) — the price is CR 601.2f's total over the alternative cost
(CR 118.9d), and a plan that read the printed mana cost would be refused for
insufficient mana, the same card every turn.

**The twin sweep** is the generalisation: a supported card, as each spell it
can be cast as, is put on one board in the seat's hand and then, on the same
board, in a zone under each *kind* of permission the pool grants —

* ``graveyard_open``  — "you may play lands and cast spells from your
  graveyard" (Yawgmoth's Will, Yawgmoth's Agenda): the card's own mana cost;
* ``exile_lent``      — "you may play that card" (Elkin Bottle, Three Wishes):
  its own mana cost, a named card, a duration;
* ``exile_free``      — "you may cast them this turn … without paying"
  (Chandra, Heart of Fire's kin): no mana at all, so the seat is given none;
* ``library_top_free``— "for as long as that card remains on top of your
  library … you may play that card without paying its mana cost" (Temporal
  Aperture);
* ``opponents_exile`` — "Search target opponent's library for a card and exile
  it. … you may play that card" (Grinning Totem): the pile is the *other*
  seat's.

— and the claim is: **what a seat announces from its hand it announces from
the zone.** Proposed from hand means proposed from the zone; the same target,
mode, X, division and optional costs; the same mana spent (none, where the
permission waives it); accepted; and the card gone from the pile it was cast
from. Each card takes ``graveyard_open`` and one of the other four in
rotation.

The twin sweep runs over **every Nth card** in the suite (``STRIDE``) — a
proposal on a populated board is the engine's whole target enumeration, and
the pool is five thousand cards — and over the whole pool when run as a
module. The whole pool, at the round's end: 9,990 rows over 5,023 spells, and
three rows that differ, each for a reason the card prints —

* *Demonic Embrace* is not proposed from an opened graveyard: its "by paying
  3 life and discarding a card" is a price for a cast **from the graveyard**,
  whichever permission opens it, and the rig's hand is empty;
* *Forgotten Lore* leaves one mana more or less, because how often its own
  "you may pay {G}" repeats depends on what is in the graveyard it was just
  cast out of;
* *Aether Burst* names one target more: its X counts the cards named Aether
  Burst "in all graveyards as you cast this spell", and the engine counts the
  one being cast (`legality.announced_cast_x` is not told the zone — CR 601.2a
  has already moved it to the stack). Reachable only with a graveyard opened
  by another effect; left as measured.

Validated backwards: on the tree before the change every flashback row and
every twin row reads "never proposed" — the whole population.

    python -m tests.regressions.test_ody_w2g2_zone_cast_census            # the sample
    python -m tests.regressions.test_ody_w2g2_zone_cast_census --stride 1 # the pool
"""
from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement, spell_being_cast
from engine.ai_policy import choose_cast_action
from engine.ai_payment import tap_planned_lands
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_permissions import grant_permission
from engine.faces import castable_faces
from engine.flashback import printed_flashback_cost
from engine.mana_payment import mana_cost_from_symbols
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, _nosick, resolve_stack

ME, OPP = 0, 1

POOL = load_cards(manifest_set_paths(include_measured=True))
BY_NAME: dict = {}
for _card in POOL:
    BY_NAME.setdefault(_card.name, _card)

#: The twin sweep's sample in the suite: every STRIDE-th supported spell.
STRIDE = 10


def _creature(name, colors=(), power=2, toughness=2, text="", type_line=None):
    return _mk_card(
        name=name, type_line=type_line or "Creature - Beast", colors=colors,
        power=power, toughness=toughness, oracle_text=text,
    )


#: What each side of the board holds: something for a printed target phrase to
#: land on, on whichever side its effect wants. Small on purpose — a proposal
#: enumerates every legal target and judges each against every permanent.
ZOO = (
    _creature("Bait White", ("W",)),
    _creature("Bait Blue Flyer", ("U",), 1, 1, "Flying"),
    _creature("Bait Black", ("B",), 3, 3),
    _creature("Bait Golem", (), 3, 3, "", "Artifact Creature - Golem"),
    _mk_card(name="Bait Artifact", type_line="Artifact"),
    _mk_card(name="Bait Enchantment", type_line="Enchantment", colors=("W",)),
    _mk_card(name="Bait Nonbasic", type_line="Land"),
)
#: …and what each graveyard holds, for a spell that names a card in one. Each
#: costs more mana than any rig here holds: a graveyard opened whole
#: (``graveyard_open``) makes these castable too, and the sweep is asking about
#: the card under test, not about which of four cards the seat likes best.
_UNAFFORDABLE = "{50}"
YARD = (
    _mk_card(name="Buried Beast", mana_cost=_UNAFFORDABLE,
             type_line="Creature - Beast", colors=("G",), power=3, toughness=3),
    _mk_card(name="Buried Sorcery", mana_cost=_UNAFFORDABLE, type_line="Sorcery",
             oracle_text="Draw a card.", colors=("R",)),
    _mk_card(name="Buried Instant", mana_cost=_UNAFFORDABLE, type_line="Instant",
             oracle_text="Draw a card.", colors=("U",)),
)
_BASIC_FOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}

#: The permission kinds of the twin sweep — see the module docstring.
KINDS = (
    "graveyard_open", "exile_lent", "exile_free", "library_top_free",
    "opponents_exile",
)
#: Which of them waive the mana cost (CR 118.9).
FREE_KINDS = frozenset({"exile_free", "library_top_free"})
#: Which of them cover a land (``mode="play"``, CR 305.1).
PLAY_KINDS = frozenset({
    "graveyard_open", "exile_lent", "library_top_free", "opponents_exile",
})
#: The zone each kind's cast leaves, as `CastAction.from_zone` names it.
KIND_ZONE = {
    "flashback": "graveyard", "graveyard_open": "graveyard",
    "exile_lent": "exile", "exile_free": "exile",
    "library_top_free": "library", "opponents_exile": "exile",
}


def rig(held, kind: str | None, *, lands=(), floating: int = 0, mine=(), theirs=()):
    """One game: the census board, with *held* in the seat's hand (*kind*
    None) or in the zone *kind* names, under that kind's permission.

    The seat pays from *lands* (basic land names, untapped) and from
    *floating* mana of each colour already in its pool. *mine* / *theirs* are
    extra permanents by pool name (a Catalyst Stone, a Sphere of Resistance).
    """
    forest = BY_NAME["Forest"]

    def board(extra):
        cards = list(ZOO) + [BY_NAME[name] for name in extra]
        return [_nosick(Permanent(card=card)) for card in cards]

    me = PlayerState(
        name="AI", library=[forest] * 10, graveyard=list(YARD),
        battlefield=board(list(mine) + list(lands)),
    )
    opp = PlayerState(
        name="Opp", library=[forest] * 10, graveyard=list(YARD),
        battlefield=board(theirs),
    )
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = ME
    game._sync_control()
    if floating:
        me.mana_pool.update({symbol: floating for symbol in "WUBRG"})
    if kind is None:
        me.hand.append(held)
    elif kind == "flashback":
        me.graveyard.append(held)
    elif kind == "graveyard_open":
        me.graveyard.append(held)
        grant_permission(
            game, player_index=ME, zone="graveyard", mode="play", cards=None,
            exile_instead=True, duration="end_of_turn", source_name="census",
        )
    elif kind == "exile_lent":
        me.exile.append(held)
        grant_permission(
            game, player_index=ME, zone="exile", mode="play", cards=[held],
            duration="your_next_upkeep", source_name="census",
        )
    elif kind == "exile_free":
        me.exile.append(held)
        grant_permission(
            game, player_index=ME, zone="exile", mode="cast", cards=[held],
            free=True, duration="end_of_turn", source_name="census",
        )
    elif kind == "library_top_free":
        me.library.insert(0, held)
        grant_permission(
            game, player_index=ME, zone="library", mode="play", cards=[held],
            position="top", free=True, duration="end_of_turn",
            source_name="census",
        )
    elif kind == "opponents_exile":
        opp.exile.append(held)
        grant_permission(
            game, player_index=ME, zone="exile", mode="play", cards=[held],
            duration="your_next_upkeep", source_name="census",
            zone_player_index=OPP,
        )
    else:  # pragma: no cover - a typo in this file
        raise ValueError(kind)
    return game


def proposal(game, spell):
    """The seat's proposal when it is a cast of *spell*, else None."""
    action = choose_cast_action(game, ME)
    return action if action is not None and action.card_name == spell.name else None


def announced(game, action) -> tuple:
    """What *action* announces besides where the card is and how it is paid
    for: the seat, the objects **by name** (a permanent's id is its own
    game's), the mode, X, the division and the optional costs."""
    said = cast_announcement(action)
    ids = said.get("target_permanent_ids") or []
    names = tuple(
        getattr(getattr(game.permanent_by_id(pid), "card", None), "name", None)
        for pid in ids if isinstance(pid, int)
    )
    return (
        said["target_player_index"], repr(said["target_permanent_index"]), names,
        said["x_value"], said["mode_index"], repr(said["mode_choices"]),
        repr(said["divided_targets"]), repr(said["optional_cost_payments"]),
        said["target_stack_index"],
    )


def execute(game, action):
    """Carry *action* out the way every executor does: read the card off the
    zone it names, tap the plan, make the announcement — and answer what the
    resolution asks (a search, a discard) with the seat's defaults, as the
    simulator does after every cast, so the spell has left the stack."""
    from engine import ai_actions

    # Looked up rather than imported so this sweep still runs on the tree
    # before the change, where every executor read the hand — which is how it
    # was validated backwards.
    finder = getattr(ai_actions, "zone_being_cast_from", None)
    zone = game.players[ME].hand if finder is None else finder(game, ME, action)
    spell = spell_being_cast(zone, action)
    tap_planned_lands(game, ME, action)
    result = game.cast_from_hand(ME, spell.name, **cast_announcement(action))
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return result


def _count(cards, card) -> int:
    return sum(1 for entry in cards if entry is card)


def _floating(game) -> int:
    return sum(int(v or 0) for v in game.players[ME].mana_pool.values())


# --- the flashback sweep ------------------------------------------------------

#: Each board the flashback sweep casts on: the plain one, a Catalyst Stone on
#: each side ("Flashback costs you pay cost {2} less. Flashback costs your
#: opponents pay cost {2} more."), and a tax on every spell — with the generic
#: mana each adds to and takes off the flashback cost.
FLASHBACK_BOARDS = (
    ("plain", (), (), 0, 0),
    ("my Catalyst Stone", ("Catalyst Stone",), (), 0, 2),
    ("their Catalyst Stone", (), ("Catalyst Stone",), 2, 0),
    ("Sphere of Resistance", (), ("Sphere of Resistance",), 1, 0),
)


def flashback_cards() -> list:
    found = []
    for card in POOL:
        for spell in castable_faces(card):
            if printed_flashback_cost(spell) is None:
                continue
            if not compile_card_oracle(spell).supported:
                continue
            found.append((card, spell))
    return found


def _lands_for(symbols: dict) -> list[str]:
    """Basic lands that pay *symbols* with room to spare: one per coloured pip
    and, in the cost's first colour, its generic mana plus four."""
    lands: list[str] = []
    first = "G"
    for symbol in "WUBRG":
        pips = int(symbols.get(symbol, 0) or 0)
        if pips and not lands:
            first = symbol
        lands += [_BASIC_FOR[symbol]] * pips
    lands += [_BASIC_FOR[first]] * (int(symbols.get("generic", 0) or 0) + 4)
    return lands


def flashback_census() -> list[dict]:
    rows = []
    for held, spell in flashback_cards():
        cost = printed_flashback_cost(spell)
        symbols = mana_cost_from_symbols(cost.mana or "") or {}
        generic = int(symbols.get("generic", 0) or 0)
        pips = sum(int(v or 0) for v in symbols.values()) - generic
        lands = _lands_for(symbols)
        hand_game = rig(held, None, lands=lands)
        from_hand = proposal(hand_game, spell)
        hand_said = None if from_hand is None else announced(hand_game, from_hand)
        for label, mine, theirs, more, less in FLASHBACK_BOARDS:
            row = {
                "card": spell.name, "board": label, "from_hand": from_hand is not None,
                "proposed": False, "finding": None,
            }
            rows.append(row)
            game = rig(held, "flashback", lands=lands, mine=mine, theirs=theirs)
            try:
                action = proposal(game, spell)
            except Exception as exc:  # a crash is a finding, not a skip
                row["finding"] = f"EXC {type(exc).__name__}: {exc}"
                continue
            if action is None:
                if from_hand is not None:
                    row["finding"] = "never proposed"
                continue
            row["proposed"] = True
            if action.from_zone != "graveyard" or not action.alternative_cost:
                row["finding"] = (
                    f"proposed from {action.from_zone!r} "
                    f"(alternative_cost={action.alternative_cost})"
                )
                continue
            before = _count(game.players[ME].graveyard, held)
            said = announced(game, action)
            tapped = len(action.land_tap_indices)
            result = execute(game, action)
            # CR 601.2f over the flashback cost: increases, then reductions,
            # and a reduction takes only generic mana and stops at zero.
            owed = pips + max(0, generic + more - less)
            if not result.supported:
                row["finding"] = f"refused: {result.details}"
            elif tapped != owed:
                row["finding"] = f"tapped {tapped} lands for a cost of {owed}"
            elif _floating(game):
                row["finding"] = f"{_floating(game)} mana left floating"
            elif _count(game.players[ME].graveyard, held) != before - 1:
                row["finding"] = "still in the graveyard"
            elif _count(game.players[ME].exile, held) != 1:
                row["finding"] = "not exiled (CR 702.34a)"
            elif hand_said is not None and label == "plain" and said != hand_said:
                row["finding"] = "announces something else than from hand"
    return rows


# --- the twin sweep -----------------------------------------------------------

#: Floating mana of each colour the twin sweep's paying rigs start with — and
#: the free kinds start with none, which is the test of a waiver.
FLOATING = 8


def twin_census(stride: int = STRIDE) -> list[dict]:
    rows = []
    ordinal = -1
    for held in POOL:
        for spell in castable_faces(held):
            if not compile_card_oracle(spell).supported:
                continue
            ordinal += 1
            if ordinal % stride:
                continue
            hand_game = rig(held, None, floating=FLOATING)
            try:
                from_hand = proposal(hand_game, spell)
            except Exception as exc:
                rows.append({
                    "card": spell.name, "kind": "hand", "proposed": False,
                    "finding": f"EXC {type(exc).__name__}: {exc}",
                })
                continue
            if from_hand is None:
                continue  # not a card this seat casts on this board at all
            said = announced(hand_game, from_hand)
            execute(hand_game, from_hand)
            hand_left = _floating(hand_game)
            is_land = spell.primary_type == "land"
            asks_x = "{X}" in (spell.mana_cost or "").upper()
            rotating = KINDS[1 + (ordinal // stride) % (len(KINDS) - 1)]
            for kind in ("graveyard_open", rotating):
                if is_land and kind not in PLAY_KINDS:
                    continue  # "cast" covers no land (CR 305.1)
                free = kind in FREE_KINDS
                row = {"card": spell.name, "kind": kind, "proposed": False, "finding": None}
                rows.append(row)
                game = rig(held, kind, floating=0 if free else FLOATING)
                try:
                    action = proposal(game, spell)
                except Exception as exc:
                    row["finding"] = f"EXC {type(exc).__name__}: {exc}"
                    continue
                if action is None:
                    # CR 107.3b: a waived {X} is 0, and an X of nothing is a
                    # cast this policy does not make from hand either.
                    if not (free and asks_x):
                        row["finding"] = "never proposed"
                    continue
                row["proposed"] = True
                wanted_seat = OPP if kind == "opponents_exile" else None
                zone_seat = getattr(action, "zone_seat", None)
                if action.from_zone != KIND_ZONE[kind] or zone_seat != wanted_seat:
                    row["finding"] = (
                        f"proposed from {action.from_zone!r}, seat {zone_seat!r}"
                    )
                    continue
                # A seat with no mana buys no kicker and no buyback, so where
                # the hand's cast took an offer the waived one is a different
                # announcement by construction (and CR 702.33g may give it
                # different targets). Held to "proposed and accepted" there.
                comparable = not (free and from_hand.optional_cost_payments)
                if comparable and announced(game, action) != said:
                    row["finding"] = "announces something else than from hand"
                    continue
                result = execute(game, action)
                owner = game.players[OPP if kind == "opponents_exile" else ME]
                if not result.supported:
                    row["finding"] = f"refused: {result.details}"
                elif not free and _floating(game) != hand_left:
                    row["finding"] = (
                        f"left {_floating(game)} mana floating, {hand_left} from hand"
                    )
                elif free and action.land_tap_indices:
                    row["finding"] = "tapped a land for a cast that costs nothing"
                elif (
                    f"{spell.name} cast from {owner.name}'s {KIND_ZONE[kind]}"
                    not in game.log
                ):
                    # The cast path's own statement of which pile the card
                    # left. (Counting the pile afterwards would not do: a
                    # creature that dies as it enters is back in it.)
                    row["finding"] = "not cast from the pile the permission opened"
    return rows


# --- the tests ----------------------------------------------------------------

@pytest.fixture(scope="module")
def flashback_rows() -> list:
    return flashback_census()


@pytest.fixture(scope="module")
def twin_rows() -> list:
    return twin_census()


def test_the_flashback_sweep_examined_every_flashback_card(flashback_rows):
    """The floor: Odyssey prints 28, and a sweep that reaches none passes."""
    cards = {row["card"] for row in flashback_rows}
    assert len(cards) >= 28
    assert {"Firebolt", "Call of the Herd", "Roar of the Wurm", "Moment's Peace"} <= cards
    assert len(flashback_rows) == len(cards) * len(FLASHBACK_BOARDS)
    # ...and the comparison it stands on is not vacuous: nearly every one of
    # them is a card this seat casts from its hand on this board. Not Fervent
    # Denial, nor Skull Fracture at an empty opposing hand, and — since a
    # precombat cast is weighed through the turn's fight — not three whose
    # good is this turn's only and which do nothing on this board in the
    # caster's own main phase: Moment's Peace (a Fog over its caster's own
    # attack), Embolden (a shield with no damage coming) and Seize the Day
    # (an added combat its creatures, tapped by the first, cannot use).
    assert sum(1 for row in flashback_rows if row["from_hand"]) >= 23 * len(FLASHBACK_BOARDS)


def test_a_flashback_card_in_the_graveyard_is_cast_from_it(flashback_rows):
    """Proposed from the graveyard wherever it is proposed from hand, accepted,
    paid for exactly — at the printed flashback cost, under Catalyst Stone on
    either side and under a tax — and exiled."""
    findings = [
        f"{row['card']} [{row['board']}]: {row['finding']}"
        for row in flashback_rows if row["finding"]
    ]
    assert findings == []
    proposed = {row["card"] for row in flashback_rows if row["proposed"]}
    # The five above, held from the graveyard too: Skull Fracture's cast out
    # of it was a change only by its own trip to exile, which a rehearsal now
    # takes out as it takes out a hand card's (`ai_rehearsal.same_position`).
    assert len(proposed) >= 23


def test_the_twin_sweep_examined_the_pool(twin_rows):
    """The floor, per kind: each is a different road through the cast path."""
    by_kind = Counter(row["kind"] for row in twin_rows)
    assert by_kind["graveyard_open"] >= 300, by_kind
    for kind in KINDS[1:]:
        assert by_kind[kind] >= 60, (kind, by_kind)
    proposed = Counter(row["kind"] for row in twin_rows if row["proposed"])
    for kind in KINDS:
        assert proposed[kind] >= 50, (kind, proposed)


def test_what_a_seat_casts_from_its_hand_it_casts_from_an_opened_zone(twin_rows):
    named = sorted(
        f"{row['card']} [{row['kind']}]: {row['finding']}"
        for row in twin_rows if row["finding"]
    )
    assert named == []


if __name__ == "__main__":
    import sys
    import time

    started = time.time()
    rows = flashback_census()
    bad = [row for row in rows if row["finding"]]
    print(
        f"flashback: {len({row['card'] for row in rows})} cards x "
        f"{len(FLASHBACK_BOARDS)} boards = {len(rows)} rows; "
        f"cast from hand on this board: "
        f"{sum(1 for r in rows if r['from_hand']) // len(FLASHBACK_BOARDS)}; "
        f"proposed from the graveyard: {sum(1 for r in rows if r['proposed'])}; "
        f"findings: {len(bad)}  ({time.time() - started:.0f}s)"
    )
    for row in bad:
        print(f"   {row['card']} [{row['board']}]: {row['finding']}")
    not_from_hand = sorted({row["card"] for row in rows if not row["from_hand"]})
    print("   not cast from hand on this board either:", ", ".join(not_from_hand) or "-")
    if "--flashback-only" in sys.argv:
        raise SystemExit(0)
    stride = int(sys.argv[sys.argv.index("--stride") + 1]) if "--stride" in sys.argv else STRIDE
    started = time.time()
    rows = twin_census(stride)
    bad = [row for row in rows if row["finding"]]
    print(
        f"twins (every {stride}): {len(rows)} rows over "
        f"{len({row['card'] for row in rows})} cards "
        f"{dict(Counter(row['kind'] for row in rows))}; "
        f"proposed: {dict(Counter(r['kind'] for r in rows if r['proposed']))}; "
        f"findings: {len(bad)}  ({time.time() - started:.0f}s)"
    )
    print("   by kind and finding:", dict(Counter(
        (row["kind"], row["finding"].split(":")[0]) for row in bad
    ).most_common()))
    bad.sort(key=lambda row: (row["finding"].split(":")[0] == "never proposed", row["card"]))
    for row in bad[:300]:
        print(f"   {row['card']} [{row['kind']}]: {row['finding']}")
