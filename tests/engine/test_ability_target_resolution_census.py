"""CR 608.2b over the pool: an ability's target, asked again as it resolves.

    "If the spell or ability specifies targets, it checks whether the targets
    are still legal. … If all its targets, for every instance of the word
    'target,' are now illegal, the spell or ability doesn't resolve. …
    Otherwise, the spell or ability will resolve normally. Illegal targets, if
    any, won't be affected by parts of a resolving spell's effect for which
    they're illegal."

The engine asked that of instants and sorceries only
(``legality.illegal_targets_refusal``). An **activated** ability was left to its
handlers, each of which re-checked what it happened to re-check — whether the
permanent was still there, sometimes the printed noun, never whether it could
still be *targeted* — and then ran everything printed behind the targeted
sentence regardless. Three wave-1 groups of the Apocalypse round each measured
a piece of it and left it, correctly, for being the whole pool:

* **the tail.** Savage Gorilla ("Target creature gets -3/-3 until end of turn.
  Draw a card.") drew with its lone target gone;
* **the bystander.** A target that left was replaced by whatever slid into its
  battlefield slot (``Game.chosen_permanent``'s index fallback) or by a
  handler's scan;
* **the description.** A target that stopped answering the printed phrase was
  acted on anyway.

So every activated ability in both manifest roles that announces a target is
driven here. It is announced at a target its own picker offers — through the
*queue* form, because ``activate_permanent_ability`` settles what it queues and
leaves nothing to respond to — the target is made illegal while the ability
waits, and the stack is drained. What is asserted is the whole game: the
ability is removed by the rule (the log says so) and **nothing else moved** —
not the target, not a bystander, not a hand, a library or a life total.

A second arm is the control: the same announcement with nothing done in
response must *not* be removed. A gate that re-asked a narrower question than
the announcement did would counter abilities that are perfectly legal, and that
arm is the only thing that would see it.

The same file holds the rule's other half and its two neighbours:

* **per target** — a spell or ability with several targets still resolves
  while one is legal, and the illegal ones are blanked out of the announcement
  first (``legality.blank_illegal_resolution_targets``). Driven over every
  multi-target instant and sorcery, where 42 of 48 acted on a target given
  shroud in response (Reckless Spite destroyed the creature given protection
  from black);
* **a triggered ability whose target was *chosen*** (CR 603.3d, the
  ``trigger_target`` prompt and its default; ``StackItem.targets_chosen``) is
  asked the same question. One whose target a fire site *stamped* is not, and
  that is the bound: an id a fire site threads through the target fields is
  not a choice anybody made. Driven over every trigger in the pool that prints
  a target and chooses it for itself, and over every entry trigger that carries
  the target its permanent spell named;
* **the printed relation**, over one invented sentence per target handler, so
  the description half is held kind by kind and not only by the cards the pool
  happens to print.

Each census is **validated backwards** (the gate switched off, the census has
to go red and name its known cards) and carries a floor on how much it
examined: "no wrong resolutions" over a sweep that reached none is a true
statement about nothing.
"""

from __future__ import annotations

import copy

import pytest

from engine import Game, PlayerState, faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.keywords import grant_keyword
from engine.layer_bridge import SET_CARD_TYPES
from engine.legality import _activation_spec, targeting_instruction
from engine.mana_payment import is_mana_ability
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import _target_instances, chosen_targets
from engine.targeting import spec_is_a_cost, usable_activated_abilities
from tests.helpers import _mk_card, _nosick, resolve_stack

#: What the gate logs for an ability (``legality.ability_targets_refusal``),
#: for a graveyard target (``vanished_graveyard_target_refusal``) and for a
#: printed comparison (``stale_comparison_refusal``): the object "was removed
#: from the stack" by CR 608.2b.
_REMOVED = "removed from the stack"

_POOL: dict = {}
# `compilation_units`: a split card is its halves, each with a program of its
# own. Read whole it compiles to nothing and is never swept.
for _card in faces.compilation_units(load_cards(manifest_set_paths(include_measured=True))):
    _POOL.setdefault(_card.name, _card)

_MASK = CardDefinition(
    name="Census Mask", mana_cost="", cmc=0.0, type_line="Enchantment",
    oracle_text="You have shroud.",
    colors=(), color_identity=(), keywords=(), produced_mana=(),
    raw={"name": "Census Mask", "type_line": "Enchantment"},
)


def _without_the_rule(monkeypatch) -> None:
    """Switch off what this round added — the base tree's behaviour, for the
    backwards validations: no ability is asked CR 608.2b and no illegal slot
    is blanked."""
    monkeypatch.setattr(Game, "ability_targets_refusal", lambda self, item: None)
    monkeypatch.setattr(Game, "blank_illegal_resolution_targets", lambda self, item: 0)


# ---------------------------------------------------------------------------
# The rig
# ---------------------------------------------------------------------------


#: One plain permanent of each printed type, a tapped creature, a flier, a Wall
#: and each basic land — so most printed noun phrases find a target, and none
#: of them has an ability to put between the announcement and the answer. The
#: first creature is all five colours, which is what gives "target black
#: creature" and "target green creature" something to name; a phrase that
#: excludes a colour is answered by the colourless creatures beside it.
_BAIT = (
    _mk_card(
        name="Bait Creature", type_line="Creature - Human Soldier", power=2, toughness=2,
        colors=("W", "U", "B", "R", "G"),
    ),
    _mk_card(name="Bait Artifact", type_line="Artifact"),
    _mk_card(name="Bait Enchantment", type_line="Enchantment"),
    _mk_card(name="Bait Land", type_line="Land"),
    _mk_card(name="Bait Artifact Creature", type_line="Artifact Creature - Golem", power=3, toughness=3),
    _mk_card(name="Bait Other Creature", type_line="Creature - Elf Druid", power=1, toughness=4),
    _mk_card(name="Bait Tapped Creature", type_line="Creature - Ogre", power=3, toughness=3),
    _mk_card(name="Bait Flier", type_line="Creature - Bird", power=1, toughness=1, oracle_text="Flying"),
    _mk_card(name="Bait Wall", type_line="Creature - Wall", power=0, toughness=5, oracle_text="Defender"),
) + tuple(_POOL[name] for name in ("Forest", "Island", "Swamp", "Mountain", "Plains"))

#: Every card this rig can put into a game, by identity. :func:`_fork` hands
#: it to ``copy.deepcopy`` as the memo, so a forked game shares its
#: ``CardDefinition`` objects with the game it was forked from — which is what
#: every game does anyway (a deck repeats one immutable definition per copy).
_SHARED = {id(card): card for card in (*_POOL.values(), *_BAIT, _MASK)}


def _fork(game: Game) -> Game:
    """An independent copy of *game*, to resolve one arm on.

    The announcement is the expensive half of every arm and the same in all of
    them, so it is made once and the game forked from there — the copy the web
    layer already takes of a whole game for its undo history
    (``engine/game_history.py``). Permanents keep their ids across the fork, so
    an object is found again in the copy by ``permanent_by_id``.
    """
    return copy.deepcopy(game, dict(_SHARED))


def _board(source_card) -> tuple[Game, Permanent]:
    """A mirrored two-seat board in seat 0's main phase, the source on seat 0.

    The mirror is the point: with one side empty, a resolution that lost its
    target and scanned for another would find nothing to act on and the census
    would call that right. Each graveyard holds one card of each type and each
    library is twelve Forests, so a tail that draws, mills or reanimates is
    visible in the zones.
    """
    yard = [_POOL[name] for name in ("Grizzly Bears", "Sol Ring", "Lightning Bolt", "Forest", "Crusade")]
    source = _nosick(Permanent(card=source_card))
    game = Game(players=[
        PlayerState(
            name="P1", life=20, graveyard=list(yard), library=[_POOL["Forest"]] * 12,
            hand=[_POOL["Forest"], _POOL["Grizzly Bears"]],
            battlefield=[source] + [_nosick(Permanent(card=card)) for card in _BAIT],
        ),
        PlayerState(
            name="P2", life=20, graveyard=list(yard), library=[_POOL["Forest"]] * 12,
            hand=[_POOL["Forest"], _POOL["Grizzly Bears"]],
            battlefield=[_nosick(Permanent(card=card)) for card in _BAIT],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    for permanent in game.all_permanents():
        if permanent.card.name == "Bait Tapped Creature":
            permanent.tapped = True
    # CR 704.5f before anything is announced: a */* that counts a type this
    # board has none of is 0/0, and has to be gone before it is asked to
    # activate rather than die inside the call being measured.
    game.check_state_based_actions()
    return game, source


def _fingerprint(game) -> dict:
    """Everything a resolution could have moved, in a form two boards can be
    compared by: each seat's life and zones (and every other field of its
    state), every permanent's controller, tapped state, damage, computed P/T
    and colours and its whole metadata, and how many delayed triggers wait."""
    players = []
    for player in game.players:
        players.append((
            player.life, tuple(sorted(card.name for card in player.hand)),
            len(player.library), tuple(card.name for card in player.graveyard),
            tuple(card.name for card in player.exile),
            repr(sorted(
                (key, repr(value)) for key, value in vars(player).items()
                if key not in ("hand", "library", "graveyard", "exile", "battlefield", "life", "name")
            )),
        ))
    permanents = {
        permanent.permanent_id: (
            game.controller_index_of(permanent), permanent.tapped, permanent.damage_marked,
            permanent.effective_power if permanent.is_creature else None,
            permanent.effective_toughness if permanent.is_creature else None,
            tuple(sorted(game._effective_colors(permanent))),
            tuple(sorted((key, repr(value)) for key, value in permanent.metadata.items())),
        )
        for permanent in game.all_permanents()
    }
    return {"players": players, "permanents": permanents, "delayed": len(game.delayed_triggers)}


def _moved(before: dict, after: dict, *, target_id=None, source_id=None, named=()) -> set:
    """Which parts of the game differ between two fingerprints: the
    ``illegal target`` itself, ``another target`` the same object named, the
    ``source``, a ``bystander`` (any other permanent), or ``elsewhere`` (a
    player's life or zones, a delayed trigger)."""
    moved = set()
    for permanent_id in set(before["permanents"]) | set(after["permanents"]):
        if before["permanents"].get(permanent_id) == after["permanents"].get(permanent_id):
            continue
        if permanent_id == target_id:
            moved.add("illegal target")
        elif permanent_id in named:
            moved.add("another target")
        elif permanent_id == source_id:
            moved.add("source")
        else:
            moved.add("bystander")
    if before["players"] != after["players"] or before["delayed"] != after["delayed"]:
        moved.add("elsewhere")
    return moved


def _offered(game, entries) -> set:
    """A picker's entries as identities."""
    keys = set()
    for entry in entries:
        kind = entry.get("kind")
        if kind == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            if permanent is not None:
                keys.add(("permanent", permanent.permanent_id))
        elif kind == "player":
            keys.add(("player", entry["seat"]))
        elif kind == "graveyard":
            stamp = game.graveyard_target_at(entry["seat"], entry["index"])
            if stamp is not None:
                keys.add(("graveyard", stamp.seat, id(stamp.card), stamp.ordinal))
        elif kind == "stack" and isinstance(entry.get("stack_index"), int):
            keys.add(("stack", id(game.stack[len(game.stack) - 1 - entry["stack_index"]])))
    return keys


def _leave(game, permanent) -> None:
    """*permanent* goes to its controller's graveyard."""
    seat = game.controller_index_of(permanent)
    game.remove_from_battlefield(permanent)
    game.players[seat].graveyard.append(permanent.card)


def _stop_being_its_type(permanent) -> None:
    """Layer 4: *permanent* is an enchantment and nothing else (an artifact,
    if an enchantment is what it was)."""
    new = ["artifact"] if permanent.has_type("enchantment") else ["enchantment"]
    permanent.metadata[SET_CARD_TYPES] = {
        "card_types": new, "timestamp": 10**6, "source": "census",
    }


# ---------------------------------------------------------------------------
# Every activated ability that announces a target
# ---------------------------------------------------------------------------

#: How many pieces the pool is driven in. One test each, so a parallel run
#: spreads them; every piece builds its own boards.
_SHARDS = 6

#: Floors, per piece. Measured October 2026 over both roles: 673 announcements
#: (106 to 115 a piece), of which the removal arm reaches 648, the
#: targetability arm every permanent target (552) and the description arm
#: every target a type change takes out of its picker (528) — 84 a piece at
#: the least. Set well under that so an ordinary ingest does not move them and
#: well over zero so a rig that stopped announcing cannot read green.
_MIN_ANNOUNCED = 80
_MIN_REMOVALS = 80
_MIN_UNTARGETABLE = 60
_MIN_UNDESCRIBED = 55

#: Abilities this rig announces a target for that the gate **declines to
#: judge**, across the whole pool — each for a reason ``legality.
#: ability_target_verdicts`` names: more than one printed instance of "target"
#: with a single derived slot (Keeper of the Dead), or a roles announcement
#: with a slot that is not a permanent (Goblin Welder). A ceiling: a decline
#: nobody decided on shows up as this number moving. Four across the pool on
#: the day (Cuombajj Witches, Mogg Assassin, Planeswalker's Scorn and Favor),
#: two in one piece at the most.
_MAX_DECLINED_PER_SHARD = 5


def _targeted_activations() -> list:
    """``(card, ability index)`` for every supported, non-mana activated
    ability of both manifest roles whose derived picker is a **target** —
    sorted, so every worker of a parallel run cuts the same pieces."""
    found = []
    for name in sorted(_POOL):
        card = _POOL[name]
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None or is_mana_ability(ability):
                continue
            spec, _ = _activation_spec([ability])
            if spec.get("kind") in (None, "none", "modal", "hand_card"):
                continue
            # A payment (CR 601.2b) and a chosen source (CR 609.7a) are
            # pickers too, and neither is a target.
            if spec_is_a_cost(spec) or any(
                spec.get(flag) for flag in ("source_of_choice", "optional", "also_stack")
            ):
                continue
            found.append((card, index))
    return found


def _pick(game, spec, source):
    """The announcement this census makes: an opposing permanent the picker
    offers (the plain creature first), else one of the activator's own that is
    not the source, else a player, a card in a graveyard, a spell.

    Returns ``(keywords, kind, what)`` or None when nothing is offered.
    """
    entries = spec.get("valid_targets") or []
    permanents = []
    for entry in entries:
        if entry.get("kind") != "permanent":
            continue
        permanent = game.permanent_at(entry["seat"], entry["index"])
        if permanent is None or permanent is source:
            continue
        permanents.append((
            entry["seat"] != 1, permanent.card.name != "Bait Creature",
            len(permanents), permanent,
        ))
    if permanents:
        permanents.sort(key=lambda row: row[:3])
        chosen = permanents[0][3]
        return {"target_permanent_ids": [chosen.permanent_id]}, "permanent", chosen
    seats = [entry["seat"] for entry in entries if entry.get("kind") == "player"]
    if seats:
        seat = 1 if 1 in seats else seats[0]
        return {"target_player_index": seat}, "player", seat
    for entry in entries:
        if entry.get("kind") == "graveyard":
            return (
                {"target_player_index": entry["seat"], "target_permanent_index": entry["index"]},
                "graveyard", (entry["seat"], entry["index"]),
            )
    for entry in entries:
        if entry.get("kind") == "stack" and isinstance(entry.get("stack_index"), int):
            position = len(game.stack) - 1 - entry["stack_index"]
            return {"target_stack_index": position}, "stack", game.stack[position]
    return None


def _announce(card, index):
    """Put ability *index* of *card* on the stack of a fresh board, aimed at
    what :func:`_pick` names. Returns ``(game, depth, kind, address, ability)``
    — *depth* is where the ability sits on the stack and *address* names the
    target in a form :func:`_arm` can find again in a fork — or None when this
    rig has no announcement to make (nothing offered, a cost or a timing the
    board does not meet).
    """
    game, source = _board(card)
    if game.controller_index_of(source) != 0:
        return None
    slot = game.battlefield_index_of(source)
    spec = game.activation_target_spec(0, slot, ability_index=index)
    if spec.get("kind") in ("stack", "spell_or_permanent"):
        # Something for "target spell" to name: seat 1 pumps its own creature.
        game.players[1].hand.append(_POOL["Giant Growth"])
        creature = next(p for p in game.controlled_by(1) if p.card.name == "Bait Creature")
        game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[creature.permanent_id])
        spec = game.activation_target_spec(0, slot, ability_index=index)
    picked = _pick(game, spec, source)
    if picked is None:
        return None
    keywords, kind, what = picked
    ability = usable_activated_abilities(compile_card_oracle(card))[index]
    if "{X}" in (ability.source_line or ""):
        keywords["x_value"] = 1
    depth = len(game.stack)
    try:
        result = game.queue_permanent_ability(0, card.name, ability_index=index, **keywords)
    except Exception:  # an activation that raises is another census's
        return None
    if not result.supported or result.details != "queued" or len(game.stack) <= depth:
        return None
    item = game.stack[depth]
    if not item.activated or len(chosen_targets(game, item) or ()) != 1:
        return None
    if kind == "permanent":
        address = what.permanent_id
    elif kind == "stack":
        address = next(position for position, other in enumerate(game.stack) if other is what)
    else:
        address = what
    return game, depth, kind, address, ability


def _arm(announced):
    """A fork of an announced game with its own objects: ``(game, source,
    item, target)``. The target is a permanent, a seat, a ``(seat, slot)`` in a
    graveyard or a stack object, by *kind*."""
    game0, depth, kind, address, _ability = announced
    game = _fork(game0)
    item = game.stack[depth]
    if kind == "permanent":
        what = game.permanent_by_id(address)
    elif kind == "stack":
        what = game.stack[address]
    else:
        what = address
    return game, item.source_permanent, item, what


def _still_offered(game, card, ability, source, kind, what) -> bool:
    """Whether the announced target is one this ability's picker would offer
    **now** — the opinion this census forms for itself, through the same call
    the announcement gate makes."""
    if what is None:
        return False
    spec, _ = _activation_spec([ability])
    entries = game._enumerate_targets(
        0, card, dict(spec), for_cast=False,
        ability_instruction=targeting_instruction(ability.instruction),
        source_permanent=source, ability_source=source,
    )
    offered = _offered(game, entries)
    if kind == "permanent":
        return ("permanent", what.permanent_id) in offered
    if kind == "player":
        return ("player", what) in offered
    if kind == "stack":
        return ("stack", id(what)) in offered
    return True


#: The ways a target is made illegal, by the kind of target named. Each is
#: the name of an arm and what it does to the game.
def _changes(kind) -> list:
    if kind == "permanent":
        return [
            ("left", lambda game, what: _leave(game, what)),
            ("untargetable", lambda game, what: grant_keyword(what, "shroud")),
            ("undescribed", lambda game, what: _stop_being_its_type(what)),
        ]
    if kind == "player":
        return [("left", lambda game, what: game._put_permanent_onto_battlefield(
            what, _nosick(Permanent(card=_MASK)), what,
        ))]
    if kind == "stack":
        return [("left", lambda game, what: game.stack.remove(what))]
    return [("left", _exile_from_graveyard)]


def _exile_from_graveyard(game, what) -> None:
    seat, index = what
    card = game.players[seat].graveyard[index]
    game.players[seat].graveyard = [c for c in game.players[seat].graveyard if c is not card]
    game.players[seat].exile.append(card)


def _judged(item) -> bool:
    """Whether CR 608.2b's "every target" is something this object records:
    its own line prints the word **once**. An ability printing it twice with
    one derived slot announces its second target as it resolves (Keeper of the
    Dead), and the gate declines it by that rule — read here off the printed
    line, not by asking the gate."""
    return _target_instances(item.ability_text or "") == 1


def _drive_activations(shard: int, only=None) -> dict:
    """One piece of the pool, every arm. Returns the counts and the findings.

    *only* narrows it to named cards, for the backwards validation.
    """
    counts = {"announced": 0, "left": 0, "untargetable": 0, "undescribed": 0, "declined": 0}
    findings: list[str] = []
    for position, (card, index) in enumerate(_targeted_activations()):
        if only is not None:
            if card.name not in only:
                continue
        elif position % _SHARDS != shard:
            continue
        label = f"{card.name}#{index}"
        announced = _announce(card, index)
        if announced is None:
            continue
        kind, ability = announced[2], announced[4]
        # The control: nothing happens in response, so nothing is removed.
        game, source, item, what = _arm(announced)
        if not _judged(item):
            counts["declined"] += 1
            continue
        if not _still_offered(game, card, ability, source, kind, what):
            # The cost itself took the target out of the picker's list (a
            # creature sacrificed to pay for the ability aimed at it): a real
            # fizzle, and not this arm's.
            continue
        counts["announced"] += 1
        mark = len(game.log)
        resolve_stack(game)
        if any(_REMOVED in line for line in game.log[mark:]):
            findings.append(f"{label}: removed with its target still legal — {game.log[mark:][-2:]}")
            continue
        for arm, change in _changes(kind):
            game, source, item, what = _arm(announced)
            change(game, what)
            if _still_offered(game, card, ability, source, kind, what):
                continue  # this change does not make this target illegal
            counts[arm] += 1
            before = _fingerprint(game)
            mark = len(game.log)
            resolve_stack(game)
            said = game.log[mark:]
            if not any(_REMOVED in line for line in said):
                findings.append(f"{label} [{arm}]: not removed by the rule — {said[-3:]}")
                continue
            moved = _moved(
                before, _fingerprint(game),
                target_id=what.permanent_id if kind == "permanent" else None,
                source_id=source.permanent_id if source is not None else None,
            )
            if moved or game.stack:
                findings.append(f"{label} [{arm}]: removed, but {sorted(moved)} moved — {said[-3:]}")
    return {"counts": counts, "findings": findings}


@pytest.mark.parametrize("shard", list(range(_SHARDS)))
def test_an_activated_ability_whose_target_became_illegal_does_nothing_at_all(shard):
    """CR 608.2b over every activated ability that announces one target: with
    the target gone, untargetable or no longer what the ability prints, the
    ability is removed from the stack and the game is exactly as it was — and
    with nothing done in response it is not removed."""
    result = _drive_activations(shard)
    counts = result["counts"]
    assert not result["findings"], (
        f"{len(result['findings'])} wrong resolution(s):\n" + "\n".join(result["findings"])
    )
    assert counts["announced"] >= _MIN_ANNOUNCED, counts
    assert counts["left"] >= _MIN_REMOVALS, counts
    assert counts["untargetable"] >= _MIN_UNTARGETABLE, counts
    assert counts["undescribed"] >= _MIN_UNDESCRIBED, counts
    assert counts["declined"] <= _MAX_DECLINED_PER_SHARD, counts


#: Cards the backwards validation drives, and what each showed on the base
#: tree. Not an allow-list of anything: with the rule in place every one of
#: them is clean in the census above, and here they are what it must *name*
#: when the rule is taken away.
_KNOWN = ("Savage Gorilla", "Orcish Artillery", "Prodigal Sorcerer", "Royal Assassin")


def test_the_activation_census_goes_red_without_the_rule(monkeypatch):
    """Validated backwards: with the gate switched off the census reports the
    defects it was written against, by name.

    * **Savage Gorilla** draws its card with its target gone (the tail);
    * **Orcish Artillery** deals its 3 damage to its controller for a 2 damage
      it never dealt;
    * **Prodigal Sorcerer** pings a creature that gained shroud in response
      (the target acted on although illegal);
    * **Royal Assassin** destroys a creature that stopped being a creature and
      so stopped being what it prints.
    """
    assert not _drive_activations(0, only=set(_KNOWN))["findings"]

    _without_the_rule(monkeypatch)
    findings = _drive_activations(0, only=set(_KNOWN))["findings"]
    said = "\n".join(findings)
    assert "Savage Gorilla#0 [left]: not removed by the rule" in said, said
    assert "Savage Gorilla drew 1 card" in said, said
    assert "Orcish Artillery#0 [left]" in said and "dealt 3 damage to P1" in said, said
    assert "Prodigal Sorcerer#0 [untargetable]" in said, said
    assert "Royal Assassin#0 [un" in said, said


# ---------------------------------------------------------------------------
# The printed relation, one invented sentence per target handler
# ---------------------------------------------------------------------------

#: "…target creature blocking or blocked by this creature": a description no
#: change of characteristics can fake, on one sentence per handler family. The
#: pool prints the relation on a handful of cards; the handlers behind these
#: sentences serve hundreds.
_RELATION_SENTENCES = (
    "{1}: Destroy target creature blocking or blocked by this creature.",
    "{1}: Tap target creature blocking or blocked by this creature.",
    "{1}: This creature deals 2 damage to target creature blocking or blocked by this creature.",
    "{1}: Target creature blocking or blocked by this creature gets -2/-2 until end of turn.",
    "{1}: Exile target creature blocking or blocked by this creature.",
    "{1}: Return target creature blocking or blocked by this creature to its owner's hand.",
    "{1}: Target creature blocking or blocked by this creature gains first strike until end of turn.",
    "{1}: Untap target creature blocking or blocked by this creature.",
    "{1}: Put a -1/-1 counter on target creature blocking or blocked by this creature.",
    "{1}: Prevent all combat damage that would be dealt by target creature blocking or blocked by this creature this turn.",
)

#: The three handlers that did not re-ask the printed phrase for themselves
#: (seven did): what the backwards validation has to name.
_UNCHECKED_HANDLERS = frozenset({
    "deal_damage", "grant_target_keyword_until_eot", "prevent_damage_by_target_until_eot",
})


def _blocked_and_aimed(text: str):
    """A creature printing *text* attacks, is blocked, and aims its ability at
    the blocker; the blocker is then taken out of combat in response. Returns
    the game, the blocker, the bystander beside it and the ability's kind."""
    from engine.handlers.combat import _take_permanent_out_of_combat

    card = _mk_card(name="Relation Probe", type_line="Creature - Test", power=3, toughness=3, oracle_text=text)
    kind = compile_card_oracle(card).activated_abilities[0].instruction.kind
    source = _nosick(Permanent(card=card))
    blocker = _nosick(Permanent(card=_mk_card(name="Blocker", type_line="Creature - Test", power=3, toughness=6)))
    bystander = _nosick(Permanent(card=_mk_card(name="Bystander", type_line="Creature - Test", power=3, toughness=6)))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[source], library=[_POOL["Forest"]] * 4),
        PlayerState(name="P2", battlefield=[blocker, bystander], library=[_POOL["Forest"]] * 4),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    # "Untap target creature" needs something to show for itself.
    blocker.tapped = kind == "untap_target_permanent"
    queued = game.queue_permanent_ability(
        0, card.name, permanent_index=0, target_permanent_ids=[blocker.permanent_id],
    )
    assert queued.supported and queued.details == "queued", (text, queued)
    _take_permanent_out_of_combat(game, blocker, frees_blocked_attackers=False)
    return game, blocker, bystander, kind


@pytest.mark.parametrize("text", _RELATION_SENTENCES)
def test_a_target_taken_out_of_the_printed_relation_is_not_acted_on(text):
    """CR 608.2b: "its characteristics may have changed" is one way a target
    stops being legal; ceasing to be *in the relation the phrase prints* is
    another. Whatever the effect is, the ability is removed and neither the
    creature it named nor the one beside it is touched."""
    game, blocker, bystander, _kind = _blocked_and_aimed(text)
    before = _fingerprint(game)
    mark = len(game.log)
    resolve_stack(game)

    assert any(_REMOVED in line for line in game.log[mark:]), game.log[mark:]
    assert not _moved(before, _fingerprint(game)), game.log[mark:]
    assert game.is_on_battlefield(blocker) and game.is_on_battlefield(bystander)


def test_the_relation_census_names_the_three_handlers_without_the_rule(monkeypatch):
    """Validated backwards: with the gate off, the handlers that never
    re-asked the printed phrase act on the creature that left the combat."""
    _without_the_rule(monkeypatch)
    acted = set()
    for text in _RELATION_SENTENCES:
        game, blocker, _bystander, kind = _blocked_and_aimed(text)
        before = _fingerprint(game)
        resolve_stack(game)
        if "illegal target" in _moved(before, _fingerprint(game), target_id=blocker.permanent_id):
            acted.add(kind)
    assert _UNCHECKED_HANDLERS <= acted, acted


# ---------------------------------------------------------------------------
# Several targets, one of them illegal: every multi-target instant and sorcery
# ---------------------------------------------------------------------------

_SPELL_BOARD = (
    "Grizzly Bears", "Hill Giant", "Savannah Lions", "Pearled Unicorn", "Juggernaut",
    "Forest", "Island", "Sol Ring", "Crusade", "Air Elemental", "Wall of Stone",
)

#: Floors for the spell census. Measured October 2026: 48 multi-target spells
#: cast, 34 of which still act on another target once the first is illegal
#: (the rest need the first to do anything — Deadshot's "it deals damage", an
#: exchange — or show nothing a fingerprint reads). Without the rule 42 of the
#: 48 acted on a first target given shroud in response.
_MIN_SPELLS = 40
_MIN_STILL_ACTING = 28

#: What the backwards validation drives: a destruction, a land destruction, a
#: pump and a two-role spell — one per handler family W1G2's census named.
_KNOWN_SPELLS = ("Reckless Spite", "Rain of Salt", "Hope and Glory", "Fumarole")


def _multi_target_spells() -> list:
    """Every supported, non-modal instant and sorcery whose derived picker
    can name more than one object: a printed count of two or more, an X of
    them, any number of them, a division, or one object per role. Read off
    the spec so that only those are cast — the board is what then says whether
    two permanents were offered."""
    from engine.targeting import derive_cast_spec

    found = []
    for _name, card in sorted(_POOL.items()):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        spec = derive_cast_spec(card, program) or {}
        ceiling = spec.get("max_targets")
        if (
            spec.get("kind") in ("roles", "divided") or spec.get("division")
            or spec.get("x_targets") or spec.get("unbounded_targets")
            or (isinstance(ceiling, int) and ceiling >= 2)
        ):
            found.append(card)
    return found


def _cast_at_several(card):
    """Cast *card* from seat 0's hand at the first permanents its picker
    offers. Returns the game and the permanents named, or None when the spell
    does not name at least two."""
    game = Game(players=[
        PlayerState("A", library=[_POOL["Forest"]] * 10, hand=[faces.whole_card(card)]),
        PlayerState("B", library=[_POOL["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for seat in (0, 1):
        for name in _SPELL_BOARD:
            permanent = Permanent(card=_POOL[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    try:
        spec = game.cast_target_spec(0, card)
    except Exception:  # a picker that raises is another census's
        return None
    entries = spec.get("valid_targets") or []
    chosen = []
    if spec.get("kind") == "roles":
        # One object per role, down the walk the picker was built from.
        node = entries
        while node:
            step = ([entry for entry in node if entry.get("index") is not None] or node)[0]
            chosen.append(step)
            node = step.get("next") or []
    else:
        want = spec.get("max_targets") or 1
        chosen = [entry for entry in entries if entry.get("index") is not None][:want]
    named, seat_named = [], None
    for entry in chosen:
        if entry.get("index") is None:
            named.append(None)
            seat_named = entry.get("seat")
        else:
            named.append(game.permanent_at(entry["seat"], entry["index"]))
    real = [permanent for permanent in named if permanent is not None]
    if len(real) < 2:
        return None
    try:
        result = game.queue_from_hand(
            0, card.name,
            target_player_index=(
                seat_named if seat_named is not None else game.controller_index_of(real[0])
            ),
            target_permanent_ids=[p.permanent_id if p is not None else None for p in named],
            x_value=2,
        )
    except Exception:
        return None
    if not result.supported:
        return None
    return game, real


def _resolve_after(card, change):
    """Cast *card* at several targets, apply *change* to the first, resolve.
    Returns what moved, or None when the spell is not multi-target here."""
    cast = _cast_at_several(card)
    if cast is None:
        return None
    game, real = cast
    first = real[0]
    if change is not None:
        change(game, first)
    before = _fingerprint(game)
    resolve_stack(game)
    game.check_state_based_actions()
    return _moved(
        before, _fingerprint(game), target_id=first.permanent_id,
        named={permanent.permanent_id for permanent in real[1:]},
    )


def _drive_spells(only=None) -> dict:
    """*only* narrows it to named spells, for the backwards validation."""
    examined, still_acting, acted_on_illegal = 0, 0, []
    differs = []
    for card in _multi_target_spells():
        if only is not None and card.name not in only:
            continue
        shrouded = _resolve_after(card, lambda game, first: grant_keyword(first, "shroud"))
        if shrouded is None:
            continue
        examined += 1
        if "illegal target" in shrouded:
            acted_on_illegal.append(card.name)
            continue
        gone = _resolve_after(card, lambda game, first: _leave(game, first))
        # An illegal target is treated exactly as a departed one: what the
        # rest of the board does must not depend on which of the two it was.
        if (shrouded & {"another target", "bystander"}) != (gone & {"another target", "bystander"}):
            differs.append(f"{card.name}: shroud {sorted(shrouded)} / left {sorted(gone)}")
        still_acting += "another target" in shrouded
    return {
        "examined": examined, "still_acting": still_acting,
        "acted_on_illegal": acted_on_illegal, "differs": differs,
    }


def test_a_spell_with_several_targets_leaves_its_illegal_one_alone():
    """CR 608.2b's last sentences over every multi-target instant and
    sorcery: the first target gains shroud in response, the spell still
    resolves for the others — and the shrouded one is not touched, while the
    rest of the board ends up exactly as it does when that target simply left.

    The floor on ``still_acting`` is what stops the blanking from passing by
    blanking too much: most of these spells must still do their work on the
    targets that stayed legal.
    """
    result = _drive_spells()
    assert not result["acted_on_illegal"], result["acted_on_illegal"]
    assert not result["differs"], "\n".join(result["differs"])
    assert result["examined"] >= _MIN_SPELLS, result
    assert result["still_acting"] >= _MIN_STILL_ACTING, result


def test_the_spell_census_goes_red_without_the_rule(monkeypatch):
    """Validated backwards: without the blanking, each handler is left to
    re-check its own slot, and none re-checks targetability — so the creature
    given shroud in response is acted on beside the others. Reckless Spite
    ("Destroy two target nonblack creatures") is the card it was reported on.
    """
    assert not _drive_spells(only=set(_KNOWN_SPELLS))["acted_on_illegal"]

    _without_the_rule(monkeypatch)
    named = _drive_spells(only=set(_KNOWN_SPELLS))["acted_on_illegal"]
    assert sorted(named) == sorted(_KNOWN_SPELLS), named


# ---------------------------------------------------------------------------
# A triggered ability whose target was chosen (CR 603.3d): every entry trigger
# ---------------------------------------------------------------------------

#: Floors for the entry-trigger census. Measured October 2026: 53 entry
#: triggers carry a target their permanent spell named and their own list
#: accepted (12 more carry one that list has nothing to say about, and are
#: not judged), and each is made illegal up to three ways — it leaves, gains
#: shroud, stops being its type; a player gains shroud — 134 arms on the day.
#: The same triggers choosing for themselves, when their permanent is put
#: onto the battlefield, are in the census below with every other trigger.
_MIN_CHOSEN_WHEN_CAST = 40
_MIN_ARMS_WHEN_CAST = 100

#: What the backwards validation drives on this road.
_KNOWN_ENTRY_TRIGGERS = ("Nekrataal", "Gilded Drake", "Man-o'-War")


def _entered_with_a_chosen_target(card, road):
    """*card* enters by *road* and its entry trigger is on the stack with a
    single target that was **chosen** for it (``StackItem.targets_chosen``).
    Returns ``(game, item, target)`` or None."""
    from .test_entry_trigger_stack_census import _enter

    try:
        entered = _enter(card, road)
    except Exception:  # an entry that raises is that census's finding
        return None
    if entered is None:
        return None
    game, _executed, source = entered
    if source is None or not game.stack:
        return None
    # CR 603.3d's prompt, answered with its default — a human sits at each
    # seat of that rig, so the choice is still owed.
    if game.pending_choices:
        game.auto_resolve_pending_choices()
    for item in game.stack:
        if item.source_permanent is not source or item.ability_instruction is None:
            continue
        targets = chosen_targets(game, item) or ()
        if len(targets) == 1 and item.targets_chosen:
            return game, item, targets[0]
    return None


def _listed_for_the_trigger(game, item, target) -> bool | None:
    """Whether *target* is in the list the trigger itself would choose from
    now (``_trigger_target_candidates``, the list its prompt offers) — this
    census's own opinion of "still legal". None when that picker has no list."""
    offer = game._trigger_target_candidates(item, announced=True)
    if offer is None:
        return None
    for entry in offer[2]:
        if target.kind == "player":
            if entry.get("kind") == "player" and entry.get("seat") == target.seat:
                return True
        elif entry.get("kind") == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            if permanent is not None and permanent.permanent_id == target.permanent_id:
                return True
    return False


def _where(game, target) -> tuple:
    """A chosen target as something two separately built games can agree on:
    a seat, or a battlefield and a slot. Permanent ids are one counter for the
    whole process, so the same choice on a fresh board has a different id."""
    if target.kind == "player":
        return ("player", target.seat)
    permanent = game.permanent_by_id(target.permanent_id)
    if permanent is None:
        return ("gone",)
    return ("permanent", game.controller_index_of(permanent), game.battlefield_index_of(permanent))


def _trigger_changes(target) -> list:
    if target.kind == "player":
        return [("untargetable", lambda game: game._put_permanent_onto_battlefield(
            target.seat, Permanent(card=_MASK), None,
        ))]
    if target.kind != "permanent":
        return []
    return [
        ("left", lambda game: _leave(game, game.permanent_by_id(target.permanent_id))),
        ("untargetable", lambda game: grant_keyword(
            game.permanent_by_id(target.permanent_id), "shroud",
        )),
        ("undescribed", lambda game: _stop_being_its_type(
            game.permanent_by_id(target.permanent_id),
        )),
    ]


def _drive_entry_triggers(only=None, roads=("cast",)) -> dict:
    """Every entry trigger carrying a chosen target, by *roads*; *only*
    narrows it to named cards for the backwards validation."""
    from engine.resolution_overrides import resolves_with_illegal_targets

    from .test_entry_trigger_stack_census import _entry_trigger_cards

    chosen = {"put": 0, "cast": 0}
    arms = {"put": 0, "cast": 0}
    findings: list[str] = []
    for card, _triggers in _entry_trigger_cards():
        if only is not None and card.name not in only:
            continue
        for road in roads:
            entered = _entered_with_a_chosen_target(card, road)
            if entered is None:
                continue
            game, item, target = entered
            if _listed_for_the_trigger(game, item, target) is not True:
                continue
            chosen[road] += 1
            label = f"{card.name} [{road}]"
            where = _where(game, target)
            names = [name for name, _change in _trigger_changes(target)]
            # The control: nothing in response, so the trigger is not removed.
            mark = len(game.log)
            resolve_stack(game)
            if any(_REMOVED in line for line in game.log[mark:]):
                findings.append(f"{label}: removed with its target still legal")
                continue
            for position, arm in enumerate(names):
                entered = _entered_with_a_chosen_target(card, road)
                if entered is None:
                    break
                game, item, target = entered
                if _where(game, target) != where:
                    break  # a fresh board on which the default chose differently
                _trigger_changes(target)[position][1](game)
                if _listed_for_the_trigger(game, item, target) is not False:
                    continue  # still one the trigger could choose
                arms[road] += 1
                source = item.source_permanent
                alone = len(game.stack) == 1
                before = _fingerprint(game)
                mark = len(game.log)
                resolve_stack(game)
                said = game.log[mark:]
                moved = _moved(
                    before, _fingerprint(game), source_id=source.permanent_id,
                    target_id=target.permanent_id if target.kind == "permanent" else None,
                )
                if resolves_with_illegal_targets(card, item.ability_text):
                    # "This ability still resolves if its target becomes
                    # illegal" (Gilded Drake): not removed — and the illegal
                    # target still not acted on, nor anything in its place.
                    if moved & {"illegal target", "bystander"}:
                        findings.append(f"{label} [{arm}]: resolved onto {sorted(moved)} — {said[-3:]}")
                    continue
                if not any(_REMOVED in line for line in said):
                    findings.append(f"{label} [{arm}]: not removed by the rule — {said[-3:]}")
                elif "illegal target" in moved or (alone and moved):
                    findings.append(f"{label} [{arm}]: removed, but {sorted(moved)} moved — {said[-3:]}")
    return {"chosen": chosen, "arms": arms, "findings": findings}


def test_an_entry_trigger_is_held_to_the_target_its_permanent_spell_named():
    """CR 608.2b over every entry trigger that carries a target its permanent
    spell named and its own list accepted (CR 603.3d; this engine names an
    entry trigger's target as the permanent is cast). With that target gone,
    untargetable or no longer what the trigger prints, the trigger is removed
    from the stack; where it was the only object there, the game is exactly as
    it was."""
    result = _drive_entry_triggers()
    assert not result["findings"], "\n".join(result["findings"])
    assert result["chosen"]["cast"] >= _MIN_CHOSEN_WHEN_CAST, result["chosen"]
    # …and how many times a named target was actually made illegal and the
    # trigger resolved against it. Without this floor the census passed while
    # every arm about a permanent was being skipped (a fresh board has fresh
    # ids, and the arm compared them).
    assert result["arms"]["cast"] >= _MIN_ARMS_WHEN_CAST, result["arms"]


def test_the_entry_trigger_census_goes_red_without_the_rule(monkeypatch):
    """Validated backwards, on both roads onto the battlefield. Nekrataal
    ("…destroy target nonblack creature…") is the card
    the announcement half of this was measured on; without the rule it
    destroys a creature given shroud in response. Gilded Drake swapped itself
    for the creature beside a target that had left."""
    known = set(_KNOWN_ENTRY_TRIGGERS)
    assert not _drive_entry_triggers(only=known, roads=("put", "cast"))["findings"]

    _without_the_rule(monkeypatch)
    findings = _drive_entry_triggers(only=known, roads=("put", "cast"))["findings"]
    said = "\n".join(findings)
    for road in ("put", "cast"):
        for name in _KNOWN_ENTRY_TRIGGERS:
            assert f"{name} [{road}] [untargetable]" in said, said
    # …and the bystander: put onto the battlefield, the Drake's trigger also
    # holds the slot its picker chose from, and with the target gone the slot
    # named the creature beside it.
    assert "Gilded Drake [put] [left]: resolved onto ['bystander'" in said, said


# ---------------------------------------------------------------------------
# …and every other trigger that prints a target, wherever it fires
# ---------------------------------------------------------------------------

#: Floor for the context-free trigger census. Measured October 2026: 111
#: non-modal triggered abilities print a target and choose it for themselves
#: when enqueued from their source with nothing stamped, and their chosen
#: target is then made illegal 232 times.
_MIN_PRINTED_TRIGGER_TARGETS = 80


def _drive_printed_trigger_targets(only=None) -> dict:
    """Every supported, non-modal triggered ability whose line prints a
    target, enqueued from its source **with nothing stamped** — the drive
    ``test_stack_targets`` already makes — so CR 603.3d's own picker chooses
    (the seat's default) and marks the choice. Then the chosen target is made
    illegal on a fork of that game and the stack is drained.

    Context-free on purpose: an attack trigger, a dies trigger and an upkeep
    trigger are all reached without building the event that fires each, and
    the gate's answer does not depend on the event — an ability removed for
    its targets never runs the handler that would have read one.
    """
    from engine.modal_triggers import modal_trigger_modes
    from engine.resolution_overrides import resolves_with_illegal_targets
    from engine.stack_targets import names_a_target

    examined, arms = 0, 0
    findings: list[str] = []
    for name in sorted(_POOL):
        if only is not None and name not in only:
            continue
        card = _POOL[name]
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, trig in enumerate(program.triggered_abilities):
            if not trig.supported or trig.instruction is None:
                continue
            if modal_trigger_modes(trig.instruction) or not names_a_target(trig.source_line):
                continue
            game0, source = _board(card)
            if not game0.is_on_battlefield(source):
                continue
            depth = len(game0.stack)
            game0._enqueue_triggered_ability(
                controller_index=game0.controller_index_of(source),
                source_permanent=source, instruction=trig.instruction,
                effect_kind=trig.effect_kind, ability_text=trig.source_line,
            )
            if len(game0.stack) <= depth:
                continue  # CR 603.3d: no legal target, never on the stack
            item0 = game0.stack[depth]
            targets = chosen_targets(game0, item0) or ()
            if len(targets) != 1 or not item0.targets_chosen:
                continue
            target = targets[0]
            if _listed_for_the_trigger(game0, item0, target) is not True:
                continue
            examined += 1
            label = f"{card.name}#{index}"
            for arm, change in [("control", None), *_trigger_changes(target)]:
                game = _fork(game0)
                item = game.stack[depth]
                if change is not None:
                    change(game)
                    if _listed_for_the_trigger(game, item, target) is not False:
                        continue  # still one the trigger could choose
                alone = len(game.stack) == 1
                before = _fingerprint(game)
                mark = len(game.log)
                try:
                    resolve_stack(game)
                except Exception:  # a handler that wanted the event it was not given
                    continue
                said = game.log[mark:]
                removed = any(_REMOVED in line for line in said)
                if change is None:
                    if removed:
                        findings.append(f"{label}: removed with its target still legal — {said[-2:]}")
                    continue
                arms += 1
                moved = _moved(
                    before, _fingerprint(game),
                    source_id=item.source_permanent.permanent_id,
                    target_id=target.permanent_id if target.kind == "permanent" else None,
                )
                if resolves_with_illegal_targets(card, item.ability_text):
                    if moved & {"illegal target", "bystander"}:
                        findings.append(f"{label} [{arm}]: resolved onto {sorted(moved)} — {said[-3:]}")
                elif not removed:
                    findings.append(f"{label} [{arm}]: not removed by the rule — {said[-3:]}")
                elif "illegal target" in moved or (alone and moved):
                    findings.append(f"{label} [{arm}]: removed, but {sorted(moved)} moved — {said[-3:]}")
    return {"examined": examined, "arms": arms, "findings": findings}


def test_every_trigger_that_chose_its_own_target_is_held_to_it():
    """CR 608.2b over every triggered ability in the pool that prints a
    target and chooses it for itself as it is put on the stack — an upkeep
    trigger, an attack trigger, a dies trigger alike. With the chosen target
    gone, untargetable or no longer what the line prints, the ability is
    removed; with nothing done in response it is not."""
    result = _drive_printed_trigger_targets()
    assert not result["findings"], "\n".join(result["findings"])
    assert result["examined"] >= _MIN_PRINTED_TRIGGER_TARGETS, result
    assert result["arms"] >= 2 * _MIN_PRINTED_TRIGGER_TARGETS, result


def test_the_printed_trigger_census_goes_red_without_the_rule(monkeypatch):
    """Validated backwards. Blazing Effigy is the card ROADMAP declined the
    whole rule for triggered abilities over; its dies-trigger chooses a target
    now, and without the rule it burns a creature given shroud in response."""
    known = {"Blazing Effigy", "Erhnam Djinn", "Nekrataal"}
    assert not _drive_printed_trigger_targets(only=known)["findings"]

    _without_the_rule(monkeypatch)
    findings = _drive_printed_trigger_targets(only=known)["findings"]
    said = "\n".join(findings)
    for name in sorted(known):
        assert f"{name}#0 [untargetable]" in said, said
