"""CR 601.2c / 602.2b: an announcement that owes a target and names none.

A headless caller — a test, a scripted duel, the AI simulator — may cast a
spell or activate an ability naming no target. That omission used to be
answered at *resolution*, by whichever handler ran and whatever its own scan
of a battlefield met first. A scan is not the picker: it knows the noun and
nothing of protection, shroud or "with flying". The census, run over the
whole shipped pool on the tree before ``engine/bare_announcements.py`` (two
mirrored seats, a creature with shroud and one with protection from each
colour **first** on each battlefield, which is where a scan looks; where the
target may be a player, the same table with the opposing seat behind an Ivory
Mask):

* **961 of 1,293** bare announcements that owed a target put an object on the
  stack carrying **no target at all** (459 of 791 activations, 502 of 502
  casts) — nothing "became the target", nothing could respond to the choice,
  and CR 608.2b had nothing to re-check. 87 more activations carried a seat
  their picker does not offer;
* **497** resolved through a handler's fall-through scan
  (``handlers/_targets.pick_target_permanent``'s last step);
* **528** changed a permanent or a player their own picker does not offer and
  that the same announcement *naming* the picker's first entry leaves alone —
  341 activations and 187 casts. Giant Growth, Disenchant and Shatter landed
  on a creature with shroud; Prodigal Sorcerer pinged a player behind a Mask;
* **622** ended on a different table from that named announcement at all —
  which adds the two-sentence cards whose sentences each found their own
  first match (Burning Palm Efreet dealt its damage to one creature and took
  flying from another; "Destroy target creature. Its controller loses 2 life"
  charged nobody).

All of them are 0 here, over the whole pool (1,073 announcements; the sweep
below with its sampling switched off). The announcement is answered once, as
the object is announced: the first entry of the picker's own list in standing
order (``bare_announcements.default_activation_target`` /
``default_cast_target``), stamped like a named target, and the resolver has no
scan for an announced object. Road (b) — refusing the bare announcement
outright — was measured first: 105 tests red in 29 files on the cast side and
43 in 23 on the activation side.

**The control is the same announcement made by name**, and it found a second
defect on its own side: 14 announcements naming their target **by id alone**
resolved on a different permanent, because the handler behind them read the
slot beside the id (Swords to Plowshares exiled the first creature it met;
Magical Hack rewrote the first permanent on the battlefield). The slot is read
off the id as the object resolves now (``bare_announcements.resolving_slots``).

**Sampled**: a deterministic sixth of the pool's announcements, by a hash of
the announcement's label, because a row is two tables built and resolved. The
statement a run makes is "no announcement in the sample", and the floors are
what stop a filter from making it pass by examining nothing. **Validated
backwards** (the last test): with the default switched off and the scan
restored, the same sweep names the cards the census named.
"""

from __future__ import annotations

import random
import re
import zlib

import pytest

import engine.handlers._targets as handler_targets
import engine.mixins.stack.activation as activation_path
import engine.mixins.stack.card_activation as card_activation_path
import engine.mixins.stack.casting as casting_path
from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.legality import activation_target_obligation, cast_target_obligation
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, compiled_units
from engine.shields import shields_on
from engine.stack_targets import chosen_targets
from engine.targeting import (
    ROLES_TARGET_KIND, derive_activation_spec, derive_cast_spec, spec_is_a_cost,
    usable_activated_abilities,
)
from tests.helpers import _nosick, resolve_stack

#: The share of the pool each run examines (one announcement in this many).
_SAMPLE = 6

_BAIT = ("Grizzly Bears", "Air Elemental", "Ornithopter", "Sol Ring", "Crusade", "Island")
_TAPPED_BAIT = "Wall of Stone"
_YARD = ("Grizzly Bears", "Lightning Bolt", "Sol Ring", "Island", "Crusade")
_PLAYERISH = frozenset({"player", "any", "player_or_planeswalker"})


def _guard(label: str, text: str) -> CardDefinition:
    kind = "Artifact Creature — Golem"
    return CardDefinition(
        name=f"Census {label}", mana_cost="{3}", cmc=3.0, type_line=kind,
        oracle_text=text, colors=(), color_identity=(),
        # ``keywords`` is what layer 6 reads a printed keyword off; the
        # protections are read off the text.
        keywords=("Shroud",) if text == "Shroud" else (), produced_mana=(),
        raw={"name": f"Census {label}", "type_line": kind, "power": "3", "toughness": "3"},
    )


#: What a scan must not land on, **first** on each battlefield — a scan takes
#: the first permanent its predicate admits, so this is where it looks.
_GUARDED = tuple(
    _guard(label, text) for label, text in (
        ("Shroud", "Shroud"),
        ("Pro White", "Protection from white"),
        ("Pro Blue", "Protection from blue"),
        ("Pro Black", "Protection from black"),
        ("Pro Red", "Protection from red"),
        ("Pro Green", "Protection from green"),
    )
)


@pytest.fixture(scope="module")
def _catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def _by_name(_catalog):
    return {card.name: card for card in _catalog}


def _sampled(label: str) -> bool:
    return zlib.crc32(label.encode("utf-8")) % _SAMPLE == 0


def _enter(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return _nosick(permanent)


def _table(card, by_name, *, as_source: bool, masked: bool):
    """Two mirrored seats; *card* is seat 0's permanent (an activation) or in
    seat 0's hand (a cast). *masked* puts an Ivory Mask on seat 1.

    The bait is on the battlefield as the game is built rather than entered a
    permanent at a time — it is vanilla, a table is built twice per row, and
    twenty-six entries were most of what a row cost. *card* itself enters the
    ordinary way, so whatever it does as it enters has happened.
    """
    random.seed(1337)
    island = by_name["Island"]

    def bait() -> list:
        row = [_nosick(Permanent(card=guard)) for guard in _GUARDED]
        row += [_nosick(Permanent(card=by_name[name])) for name in _BAIT]
        tapped = _nosick(Permanent(card=by_name[_TAPPED_BAIT]))
        tapped.tapped = True
        return row + [tapped]

    game = Game(players=[
        PlayerState(
            name=f"P{seat}", library=[island] * 12, battlefield=bait(),
            hand=[island, by_name["Grizzly Bears"]],
            graveyard=[by_name[name] for name in _YARD],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game._sync_control()
    source = _enter(game, 0, card) if as_source else None
    if not as_source:
        game.players[0].hand.insert(0, card)
    if masked:
        _enter(game, 1, by_name["Ivory Mask"])
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game, source


def _labels(game) -> dict:
    seen: dict = {}
    found: dict = {}
    for seat, player in enumerate(game.players):
        for permanent in game.controlled_by(seat):
            key = (seat, permanent.card.name)
            seen[key] = seen.get(key, 0) + 1
            found[f"{seat}:{permanent.card.name}#{seen[key]}"] = permanent
    return found


#: A permanent id is a process-wide counter. The sweep pushes it past this
#: before it builds a table, so an integer at least this large in a metadata
#: record is an id and never a count a card printed — which is what lets a
#: record that names a permanent be compared across two tables built alike.
_ID_FLOOR = 1_000_000

#: A layer timestamp (CR 613.7) is a second counter, recorded beside an effect
#: and inside the name of the duration that ends it ("until_end_of_turn:55").
#: Two tables built alike apply the same effects in the same order and are
#: handed different numbers, so the number is not part of what is compared.
_TIMESTAMP = re.compile(r"((?:'timestamp': |\buntil_\w+:))\d+")


def _past_the_id_floor() -> None:
    from engine.models import next_permanent_id

    while next_permanent_id() < _ID_FLOOR:
        pass


def _state(game, labelled) -> tuple:
    """Everything an announcement can change about the table. A permanent id
    inside a record is spelled as that permanent's label and a timestamp is
    dropped, so two tables built alike compare equal.

    A timestamp is dropped **wherever it is kept**: a key naming a
    ``timestamp`` (the base P/T slots' ``absolute_pt_timestamp_until_eot``
    carries its duration after the word), and the three ``…_stamps`` records
    ``engine/keywords.py``
    keeps of when a grant began to apply (``{'red': 29}`` beside
    ``{'red': 58}`` is one grant on two tables whose clocks differ, and was
    this census's only finding the day those records and it first met).
    Which grant is *there* is still compared - by the flag the stamp is
    beside, and by what the permanent then is."""
    names = {str(perm.permanent_id): key for key, perm in labelled.items()}

    def spell(text: str) -> str:
        text = _TIMESTAMP.sub(lambda found: found.group(1) + "#", text)
        return re.sub(
            r"\b\d{7,}\b",
            lambda found: f"<{names.get(found.group(0), 'other')}>",
            text,
        )

    def one(perm) -> tuple | str:
        if not game.is_on_battlefield(perm):
            return "gone"
        return (
            game.controller_index_of(perm), perm.tapped, perm.damage_marked,
            perm.effective_power if perm.is_creature else None,
            perm.effective_toughness if perm.is_creature else None,
            perm.regeneration_shield, len(shields_on(perm)),
            tuple(sorted(perm.effective_card.type_line.split())),
            tuple(sorted(
                (key, spell(repr(value))[:160]) for key, value in perm.metadata.items()
                if key != "tapped_to_pay_for_ability_ids"
                and "timestamp" not in key and not key.endswith("_stamps")
            )),
        )

    return (
        {key: one(perm) for key, perm in labelled.items()},
        [
            (player.life, len(player.hand), len(player.library), len(shields_on(player)))
            for player in game.players
        ],
        [[held.name for held in player.graveyard] for player in game.players],
    )


def _rows(catalog, only=None):
    """``(side, label, card, index_or_mode, kind)`` for every announcement in
    the pool that **owes one target**: an activated ability, or one mode of an
    instant or sorcery."""
    for card, program in compiled_units(catalog):
        if not program.supported or (only is not None and card.name not in only):
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            spec = derive_activation_spec(ability)
            if spec is None or spec_is_a_cost(spec) or spec.get("also_stack"):
                continue
            if spec.get("kind") in ("none", "modal", "hand_card", ROLES_TARGET_KIND):
                continue
            if activation_target_obligation(ability, x_value=None) is None:
                continue
            yield "act", f"{card.name}[{index}]", card, index, spec.get("kind")
        if card.primary_type not in ("instant", "sorcery"):
            continue
        if program.modes and program.mode_chooser is not None:
            continue
        for mode in (range(len(program.modes)) if program.modes else (None,)):
            spec = derive_cast_spec(card, program, mode_index=mode)
            if spec is None or spec_is_a_cost(spec):
                continue
            if cast_target_obligation(
                card, program, optional_cost_payments={}, mode_index=mode,
            ) is None:
                continue
            label = card.name if mode is None else f"{card.name} #{mode}"
            yield "cast", label, card, mode, spec.get("kind")


def _picker(game, side, card, source, which) -> list:
    if side == "act":
        spec = game.activation_target_spec(
            0, game.battlefield_index_of(source), ability_index=which,
        )
    else:
        spec = game.cast_target_spec(0, card, mode_index=which)
    return [] if spec.get("max_targets") == 0 else list(spec.get("valid_targets") or [])


def _announce(game, side, card, source, which, **named):
    if side == "act":
        return game.queue_permanent_ability(
            0, card.name, permanent_index=game.battlefield_index_of(source),
            ability_index=which, **named,
        )
    keywords = dict(named)
    if which is not None:
        keywords["mode_index"] = which
    return game.queue_from_hand(0, card.name, **keywords)


def _naming(game, entry) -> dict | None:
    kind = entry.get("kind")
    if kind == "player":
        return {"target_player_index": entry["seat"]}
    if kind == "permanent":
        named = game.permanent_at(game.players[entry["seat"]], entry["index"])
        return {"target_permanent_ids": [named.permanent_id]}
    if kind == "graveyard":
        return {
            "target_player_index": entry["seat"],
            "target_permanent_index": entry["index"],
        }
    return None


def _finish(game) -> None:
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def _sweep(catalog, by_name, only=None) -> dict:
    """Announce every sampled row bare, and again naming the picker's first
    entry in standing order (the opposing seat's first). Returns the counts
    and the four finding lists."""
    found = {
        "examined": 0, "controlled": 0, "sides": {"act": 0, "cast": 0},
        "unstamped": [], "unoffered": [], "residue": [], "differs": [],
    }
    _past_the_id_floor()
    for side, label, card, which, kind in _rows(catalog, only):
        if only is None and not _sampled(label):
            continue
        masked = kind in _PLAYERISH
        build = lambda: _table(  # noqa: E731 - one board, built twice
            card, by_name, as_source=side == "act", masked=masked,
        )
        game, source = build()
        if side == "act" and not game.is_on_battlefield(source):
            continue
        offered = _picker(game, side, card, source, which)
        labelled = _labels(game)
        ids = {perm.permanent_id: key for key, perm in labelled.items()}
        offered_perms = {
            key for key, perm in labelled.items()
            if any(
                entry.get("kind") == "permanent"
                and game.permanent_at(game.players[entry["seat"]], entry["index"]) is perm
                for entry in offered
            )
        }
        offered_seats = {e["seat"] for e in offered if e.get("kind") == "player"}
        before = _state(game, labelled)
        depth = len(game.stack)
        result = _announce(game, side, card, source, which)
        if not result.supported:
            continue    # nothing legal, a timing gate, a cost the table cannot pay
        found["examined"] += 1
        found["sides"][side] += 1
        ours = [
            item for item in game.stack[depth:]
            if (item.activated if side == "act" else item.ability_instruction is None)
        ]
        chosen = chosen_targets(game, ours[0]) if ours else None
        if not chosen:
            found["unstamped"].append((label, kind))
        for target in chosen or ():
            if target.kind == "permanent" and ids.get(target.permanent_id) not in offered_perms:
                found["unoffered"].append((label, kind, ids.get(target.permanent_id)))
            if target.kind == "player" and target.seat not in offered_seats:
                found["unoffered"].append((label, kind, f"seat {target.seat}"))
        _finish(game)
        after = _state(game, labelled)

        # The control: the same announcement, naming the picker's first entry.
        standing = sorted(offered, key=lambda entry: entry.get("seat") != 1)
        control, control_source = build()
        naming = _naming(control, standing[0]) if standing else None
        if naming is None:
            continue
        control_labels = _labels(control)
        control_before = _state(control, control_labels)
        named = _announce(control, side, card, control_source, which, **naming)
        assert named.supported, (
            f"{label}: the picker's own first entry was refused: {named.details}"
        )
        _finish(control)
        control_after = _state(control, control_labels)
        found["controlled"] += 1
        changed = {key for key in before[0] if before[0][key] != after[0][key]}
        control_changed = {
            key for key in control_before[0]
            if control_before[0][key] != control_after[0][key]
        }
        strays = sorted((changed - offered_perms) - control_changed)
        seats = [
            seat for seat in range(len(game.players))
            if kind in _PLAYERISH and seat not in offered_seats
            and after[1][seat] != before[1][seat]
            and control_after[1][seat] == control_before[1][seat]
        ]
        if strays or seats:
            found["residue"].append((label, kind, strays[:3], seats))
        if after != control_after:
            found["differs"].append((label, kind))
    return found


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------


def test_a_bare_announcement_is_the_announcement_of_its_pickers_first_target(
    _catalog, _by_name
):
    found = _sweep(_catalog, _by_name)

    # 111 activations and 84 casts: a sixth of the 605 and 468 the whole pool
    # announces on this table (October 2026).
    assert found["sides"]["act"] >= 95, found["sides"]
    assert found["sides"]["cast"] >= 70, found["sides"]
    assert found["controlled"] >= 170, found["controlled"]
    assert found["unstamped"] == [], (
        "CR 601.2c: accepted owing a target, with none on the stack object: "
        f"{found['unstamped'][:20]}"
    )
    assert found["unoffered"] == [], (
        f"the announced default is not one the picker offers: {found['unoffered'][:20]}"
    )
    assert found["residue"] == [], (
        "resolved on a permanent or a player the picker does not offer: "
        f"{found['residue'][:20]}"
    )
    assert found["differs"] == [], (
        "a bare announcement and the same one naming the picker's first "
        f"entry ended on different tables: {found['differs'][:20]}"
    )


#: Cards the census named on the tree before the default, one per way a scan
#: is not the picker: a narrowing the scan does not read (Burning Palm Efreet's
#: "with flying"), protection from the source's colour (Soul Sculptor), a
#: second sentence that could not find the first one's target (Vendetta's life
#: loss, Amber Prison's untap lock), and a player behind a shroud the default
#: seat ignored (Prodigal Sorcerer's "any target").
_KNOWN = frozenset({
    "Burning Palm Efreet", "Soul Sculptor", "Vendetta", "Amber Prison",
    "Prodigal Sorcerer",
})


def _the_tree_as_it_was(monkeypatch) -> None:
    """Switch the announcement default off and give the resolver its scan
    back: every owed target left unnamed is the handler's to find again."""
    # The graveyard road (``activate_from_graveyard``) asks the default from
    # its own module, so it is switched off there too.
    for path in (activation_path, card_activation_path):
        monkeypatch.setattr(
            path, "default_activation_target", lambda *a, **k: None
        )
    monkeypatch.setattr(
        casting_path, "default_cast_target", lambda *a, **k: (None, False)
    )
    real = handler_targets.pick_target_permanent

    def scanning(*args, announced=False, **kwargs):
        return real(*args, **kwargs)

    monkeypatch.setattr(handler_targets, "pick_target_permanent", scanning)


def test_the_sweep_finds_the_defect_on_the_tree_as_it_was(
    _catalog, _by_name, monkeypatch
):
    clean = _sweep(_catalog, _by_name, only=_KNOWN)
    assert clean["examined"] == len(_KNOWN), clean["examined"]
    for key in ("unstamped", "unoffered", "residue", "differs"):
        assert clean[key] == [], (key, clean[key])

    _the_tree_as_it_was(monkeypatch)
    found = _sweep(_catalog, _by_name, only=_KNOWN)

    unstamped = {label.split("[")[0] for label, _kind in found["unstamped"]}
    # An activation's player default was always stamped — the seat field is
    # filled for every ability — so "any target" is not among the unstamped;
    # it is among the ones stamped with a seat the picker does not offer.
    assert unstamped >= {
        "Burning Palm Efreet", "Soul Sculptor", "Vendetta", "Amber Prison",
    }, found["unstamped"]
    assert ("Prodigal Sorcerer[0]", "any", "seat 1") in found["unoffered"]
    differs = {label.split("[")[0] for label, _kind in found["differs"]}
    assert differs >= {"Burning Palm Efreet", "Vendetta", "Amber Prison"}, found["differs"]
    residue = {label.split("[")[0] for label, *_rest in found["residue"]}
    # Prodigal Sorcerer's stray seat no longer reaches its handler even here:
    # an activation's targets are asked again as it resolves (CR 608.2b,
    # ``legality_resolution.ability_target_verdicts``), and a seat behind an Ivory Mask
    # is removed there. The announcement half above still names it.
    assert residue >= {"Soul Sculptor"}, found["residue"]
