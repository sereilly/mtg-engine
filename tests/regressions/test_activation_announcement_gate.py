"""CR 602.2b / 601.2c: what an **activated ability** may announce.

``Game.activation_target_refusal`` is the gate and
``Game.activation_target_spec(...)["valid_targets"]`` the picker, and they are
supposed to be one list: a named target is legal iff the picker offers it, and
an ability that owes a target is unactivatable while the picker offers none.

They were one list only for an ability whose *mandatory-target walk* found a
``targets`` description with the bare quantifier. For every other ability the
gate returned before it looked at what was named. Measured on the tree before
this file (30 shipped sets, 818 abilities whose spec names something to
choose, a mirrored board of ten permanents a side):

* **1,771 of 16,562 named announcements** were accepted naming something the
  picker does not offer, on **151 abilities** — an "any target" ping aimed at
  a Sol Ring (93 abilities carry ``any_target``, which the walk did not read
  as owing anything), a bounce / a base-P/T set / "you may tap or untap target
  creature" aimed at an opponent's Island, "target opponent gains control of
  this artifact" naming the activator;
* **24 of 378 abilities** printing a mandatory "target" could be activated with
  no legal target anywhere, and paid for;
* driven through ``queue_permanent_ability``, **59 of 689** activations naming
  an unoffered permanent went on the stack.

All three are 0 here. The gate asks one question of every ability now —
``legality.activation_target_obligation``, the picker's own slot and its
printed quantifier — instead of a walk a lowering could be left out of.

**Validated backwards** (the last tests): with the gate's old opening restored
the sweeps name the cards the census named, and each has a floor on what it
examined, because a sweep that reaches nothing passes on any tree.
"""

from __future__ import annotations

import copy
import re

import pytest

import engine.legality as legality
from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.legality import activation_target_obligation
from engine.models import Permanent
from engine.oracle import compile_card_oracle, compiled_units
from engine.shields import shields_on
from engine.targeting import (
    ROLES_TARGET_KIND, derive_activation_spec, spec_is_a_cost,
    usable_activated_abilities,
)
from tests.helpers import _nosick, resolve_stack

#: One of most things a printed target phrase can ask for, the same on both
#: sides — with one seat empty a gate that ignored the seat would still be
#: right for want of anywhere else to go.
_BAIT = (
    "Grizzly Bears", "Black Knight", "Air Elemental", "Ornithopter",
    "Sol Ring", "Crusade", "Island", "Mishra's Factory",
)
_TAPPED_BAIT = "Wall of Stone"
_GRAVEYARD_BAIT = ("Grizzly Bears", "Lightning Bolt", "Sol Ring", "Island", "Crusade")

#: Spec kinds the battlefield sweeps leave to their own files: a **roles**
#: announcement is checked whole by the walk it was built from, a **stack**
#: target by ``test_activated_stack_target.py``, a **divided** one by CR 601.2d's
#: gate.
_OTHER_SWEEPS = frozenset({ROLES_TARGET_KIND, "stack", "divided"})

_REMINDER = re.compile(r"\([^)]*\)")
_QUOTED = re.compile('["“][^"”]*["”]')
_MAY_NAME_NOBODY = re.compile(
    r"\bup to (?:\w+) (?:other )?target|any number of (?:other )?target"
    r"|\bx (?:other )?target"
)


@pytest.fixture(scope="module")
def _catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def _by_name(_catalog):
    return {card.name: card for card in _catalog}


def _choosing_abilities(catalog, only=None):
    """Every supported activated ability whose spec names something to choose
    that is not a cost and not a chosen source — ``(card, index, ability,
    spec)``. ``compiled_units``: an ability of a multi-face card is on its
    faces (CR 709.3a)."""
    for card, program in compiled_units(catalog):
        if not program.supported or (only is not None and card.name not in only):
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            spec = derive_activation_spec(ability)
            if spec is None or spec.get("kind") in ("none", "modal", "hand_card"):
                continue
            if spec_is_a_cost(spec) or spec.get("also_stack"):
                continue
            yield card, index, ability, spec


def _enter(game, seat, card) -> Permanent:
    """Put *card* onto *seat*'s battlefield, past its summoning sickness — set
    after it enters, because entering is what stamps the turn it arrived."""
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return _nosick(permanent)


def _prints_a_mandatory_target(ability) -> bool:
    """The control: the ability's own printed effect says "target" and does not
    say the announcement may be empty. Read off the card, never off the code
    under test."""
    line = _QUOTED.sub("", _REMINDER.sub("", ability.source_line or "")).lower()
    effect = line.split(":", 1)[-1]
    return bool(re.search(r"\btarget\b", effect)) and not _MAY_NAME_NOBODY.search(effect)


def _board(card, by_name, *, bait=True):
    """Seat 0 controls *card*, ready to activate. Returns ``(game, source)``."""
    island = by_name["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[island] * 8) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    source = _enter(game, 0, card)
    for seat in (0, 1):
        game.players[seat].hand.extend([island, by_name["Grizzly Bears"]])
        if not bait:
            continue
        for name in _BAIT:
            _enter(game, seat, by_name[name])
        _enter(game, seat, by_name[_TAPPED_BAIT]).tapped = True
        game.players[seat].graveyard.extend(by_name[name] for name in _GRAVEYARD_BAIT)
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game, source


def _offer(game, source, index) -> dict:
    """The picker's answer for *source*'s ability, as the client is handed it."""
    spec = game.activation_target_spec(
        game.controller_index_of(source), game.battlefield_index_of(source),
        ability_index=index,
    )
    valid = spec.get("valid_targets") or []
    if spec.get("max_targets") == 0:
        # "up to X target …" where the card's own X is zero (a verse
        # enchantment with no counters): a list, and a ceiling of none.
        valid = []
    return {
        "permanent": {(t["seat"], t["index"]) for t in valid if t.get("kind") == "permanent"},
        "graveyard": {(t["seat"], t["index"]) for t in valid if t.get("kind") == "graveyard"},
        "player": {t["seat"] for t in valid if t.get("kind") == "player"},
        "any": bool(valid),
    }


def _gate(game, source, ability, **named):
    # X = 1, so "X target lands" (Candelabra of Tawnos) admits one named land;
    # an ability with no X ignores it.
    return game.activation_target_refusal(0, source, ability, x_value=1, **named)


def _unpaid(game, source) -> tuple:
    return (
        game.is_on_battlefield(source), source.tapped, len(game.stack),
        [len(player.hand) for player in game.players],
        [len(player.graveyard) for player in game.players],
        [player.life for player in game.players],
        copy.deepcopy({k: v for k, v in source.metadata.items() if "counter" in k}),
    )


def _named_sweep(catalog, by_name, only=None):
    """``(abilities, announcements, driven, accepted_unoffered,
    refused_offered, driven_accepted)``.

    For each ability every permanent, graveyard card and player on the table is
    named in turn and the gate's answer compared with the picker's. Then one
    permanent the picker does **not** offer is named through
    ``queue_permanent_ability``, which must refuse it with nothing paid.
    """
    abilities = announcements = driven = 0
    accepted_unoffered: list[tuple] = []
    refused_offered: list[tuple] = []
    driven_accepted: list[tuple] = []
    for card, index, ability, spec in _choosing_abilities(catalog, only):
        kind = spec.get("kind")
        if kind in _OTHER_SWEEPS:
            continue
        game, source = _board(card, by_name)
        if not game.is_on_battlefield(source):
            continue    # a state trigger took it as the board was built
        abilities += 1
        offered = _offer(game, source, index)
        label = f"{card.name}[{index}]"

        def judge(refusal, is_offered, what):
            nonlocal announcements
            announcements += 1
            if refusal is None and not is_offered:
                accepted_unoffered.append((label, kind, what))
            if refusal is not None and is_offered:
                refused_offered.append((label, kind, what, refusal))

        if kind == "graveyard_creature":
            for seat, player in enumerate(game.players):
                for slot, held in enumerate(player.graveyard):
                    judge(
                        _gate(game, source, ability, target_player_index=seat,
                              target_permanent_index=slot),
                        (seat, slot) in offered["graveyard"],
                        f"graveyard {seat}: {held.name}",
                    )
            continue
        if kind in ("player", "player_or_planeswalker", "any"):
            for seat in range(len(game.players)):
                judge(
                    _gate(game, source, ability, target_player_index=seat),
                    seat in offered["player"], f"seat {seat}",
                )
            if kind == "player":
                continue
        unoffered = None
        for permanent in list(game.all_permanents()):
            seat = game.controller_index_of(permanent)
            slot = game.battlefield_index_of(permanent)
            is_offered = (seat, slot) in offered["permanent"]
            judge(
                _gate(game, source, ability,
                      target_permanent_ids=[permanent.permanent_id]),
                is_offered, f"seat {seat}: {permanent.card.name}",
            )
            if not is_offered and permanent is not source and unoffered is None:
                unoffered = permanent
        if unoffered is None:
            continue
        before = _unpaid(game, source)
        result = game.queue_permanent_ability(
            0, card.name, permanent_index=game.battlefield_index_of(source),
            ability_index=index, target_permanent_ids=[unoffered.permanent_id],
        )
        driven += 1
        if result.supported or _unpaid(game, source) != before:
            driven_accepted.append((label, kind, unoffered.card.name))
    return (
        abilities, announcements, driven,
        accepted_unoffered, refused_offered, driven_accepted,
    )


def _empty_sweep(catalog, by_name, only=None):
    """``(examined, accepted)``: every ability printing a mandatory "target",
    alone on the battlefield with nothing its picker offers, activated naming
    nothing. Accepted, or anything paid, is a finding."""
    examined = 0
    accepted: list[tuple] = []
    for card, index, ability, spec in _choosing_abilities(catalog, only):
        kind = spec.get("kind")
        if kind in _OTHER_SWEEPS or not _prints_a_mandatory_target(ability):
            continue
        game, source = _board(card, by_name, bait=False)
        if not game.is_on_battlefield(source):
            continue
        if _offer(game, source, index)["any"]:
            continue    # it may target itself, or a player
        examined += 1
        before = _unpaid(game, source)
        result = game.queue_permanent_ability(
            0, card.name, permanent_index=game.battlefield_index_of(source),
            ability_index=index, x_value=1,
        )
        if result.supported or _unpaid(game, source) != before:
            accepted.append((f"{card.name}[{index}]", kind, result.details))
    return examined, accepted


# ---------------------------------------------------------------------------
# The censuses
# ---------------------------------------------------------------------------


def test_the_gate_and_the_picker_are_one_list_for_every_ability(_catalog, _by_name):
    (
        abilities, announcements, driven,
        accepted_unoffered, refused_offered, driven_accepted,
    ) = _named_sweep(_catalog, _by_name)

    assert abilities >= 700, f"only {abilities} abilities examined"
    assert announcements >= 11000, f"only {announcements} announcements examined"
    assert driven >= 600, f"only {driven} activations driven"
    assert accepted_unoffered == [], (
        "CR 602.2b / 601.2c: the gate accepts a named target the ability's "
        f"own picker does not offer: {accepted_unoffered[:20]}"
    )
    assert refused_offered == [], (
        f"the picker offers these and the gate refuses them: {refused_offered[:20]}"
    )
    assert driven_accepted == [], (
        "activated, or paid for, naming a permanent the picker does not "
        f"offer: {driven_accepted[:20]}"
    )


def test_no_ability_printing_a_target_is_activated_with_nothing_to_name(
    _catalog, _by_name
):
    examined, accepted = _empty_sweep(_catalog, _by_name)

    assert examined >= 330, f"only {examined} abilities examined"
    assert accepted == [], (
        "CR 602.2b: activated, or paid for, with no legal target anywhere: "
        f"{accepted}"
    )


#: Cards the census named on the tree before this file, one per way the old
#: walk missed a target: a kind whose row carries no ``targets`` description
#: (a bounce, a land-type change, a control gift), "any target", an offer
#: (``may``) around the targeting step, and a toll (``unless_player_pays``).
_KNOWN = frozenset({
    "Seal of Removal", "Gaea's Liege", "Jinxed Idol", "Prodigal Sorcerer",
    "Puppet Strings", "Scarwood Bandits",
})


def _the_gate_as_it_was(monkeypatch):
    """Restore the gate's old opening: no bare ``target`` quantifier in the
    ability's unconditional steps, so nothing is checked at all."""
    real = Game.activation_target_refusal

    def gate(self, controller_index, source, ability, **named):
        spec, _ = legality._activation_spec([ability])
        walked = "target" in legality._ability_target_quantifiers(ability.instruction)
        on_the_stack = (
            spec.get("kind") in legality._STACK_TARGET_KINDS
            and named.get("target_stack_item") is not None
        )
        if not walked and not on_the_stack and spec.get("kind") != ROLES_TARGET_KIND:
            return None
        return real(self, controller_index, source, ability, **named)

    monkeypatch.setattr(Game, "activation_target_refusal", gate)


def test_the_named_sweep_finds_the_defect_on_the_gate_as_it_was(
    _catalog, _by_name, monkeypatch
):
    assert _named_sweep(_catalog, _by_name, only=_KNOWN)[3:] == ([], [], [])

    _the_gate_as_it_was(monkeypatch)
    _abilities, _announced, _driven, accepted, _refused, driven_accepted = (
        _named_sweep(_catalog, _by_name, only=_KNOWN)
    )

    assert {label.split("[")[0] for label, _kind, _what in accepted} == _KNOWN
    assert ("Seal of Removal[0]", "creature", "seat 1: Island") in accepted
    assert ("Prodigal Sorcerer[0]", "any", "seat 1: Sol Ring") in accepted
    assert ("Jinxed Idol[0]", "player", "seat 0") in accepted
    assert {label for label, _kind, _what in driven_accepted} >= {
        "Seal of Removal[0]", "Prodigal Sorcerer[0]", "Puppet Strings[0]",
    }


def test_the_empty_sweep_finds_the_defect_on_the_gate_as_it_was(
    _catalog, _by_name, monkeypatch
):
    assert _empty_sweep(_catalog, _by_name, only=_KNOWN)[1] == []

    _the_gate_as_it_was(monkeypatch)
    _examined, accepted = _empty_sweep(_catalog, _by_name, only=_KNOWN)

    assert {label for label, _kind, _details in accepted} >= {
        "Seal of Removal[0]", "Gaea's Liege[0]", "Puppet Strings[0]",
        "Scarwood Bandits[0]",
    }


# ---------------------------------------------------------------------------
# The cards
# ---------------------------------------------------------------------------


def _table(by_name, mine=(), theirs=()):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 8)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    rows = []
    for seat, names in enumerate((mine, theirs)):
        row = []
        for name in names:
            row.append(_enter(game, seat, by_name[name]))
        rows.append(row)
    return game, rows[0], rows[1]


def test_seal_of_removal_is_not_sacrificed_at_an_opponents_island(_by_name):
    """"Sacrifice this enchantment: Return **target creature** to its owner's
    hand." The bounce's noun phrase is lowered into the payload, not into a
    ``targets`` description, so the walk found nothing to enforce: the Seal
    was sacrificed aimed at a land, and logged "No creature to return"."""
    game, (seal,), (island,) = _table(_by_name, ["Seal of Removal"], ["Island"])

    named = game.queue_permanent_ability(
        0, "Seal of Removal", target_permanent_ids=[island.permanent_id],
    )
    bare = game.queue_permanent_ability(0, "Seal of Removal")

    for refused in (named, bare):
        assert not refused.supported
        assert refused.details == "no valid target for Seal of Removal"
    assert game.is_on_battlefield(seal) and game.is_on_battlefield(island)
    assert game.stack == [] and game.players[0].graveyard == []


def test_any_target_does_not_admit_an_artifact(_by_name):
    """"{T}: This creature deals 1 damage to **any target**." CR 115.4: a
    creature, a player, a planeswalker or a battle — not a Sol Ring. The
    quantifier is ``any_target``, which the walk did not read as a target owed,
    so a named one was never compared with anything."""
    game, (tim,), (ring, bears) = _table(
        _by_name, ["Prodigal Sorcerer"], ["Sol Ring", "Grizzly Bears"],
    )

    refused = game.queue_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[ring.permanent_id],
    )

    assert not refused.supported and not tim.tapped and game.stack == []

    accepted = game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[bears.permanent_id],
    )
    resolve_stack(game)

    assert accepted.supported and tim.tapped
    assert bears.damage_marked == 1 and game.players[1].life == 20


def test_target_opponent_cannot_be_the_activator(_by_name):
    """"{3}, Sacrifice a creature: **Target opponent** gains control of this
    artifact." (Jinxed Idol.) Naming yourself is not an announcement the card
    allows (CR 102.2), and the creature is not sacrificed for it."""
    game, (idol, bears), _ = _table(_by_name, ["Jinxed Idol", "Grizzly Bears"])

    refused = game.queue_permanent_ability(0, "Jinxed Idol", target_player_index=0)

    assert not refused.supported
    assert refused.details == "no valid target for Jinxed Idol"
    assert game.is_on_battlefield(bears) and game.controls(0, idol)


def test_up_to_one_target_may_name_nobody_and_may_not_name_a_land(_by_name):
    """"+1: Put a +1/+1 counter on **up to one** target creature." (Basri Ket.)
    Zero is a legal announcement (CR 601.2c); an Island is not a creature."""
    game, (basri,), (island,) = _table(_by_name, ["Basri Ket"], ["Island"])
    basri.metadata["loyalty_counters"] = 3

    refused = game.queue_permanent_ability(
        0, "Basri Ket", ability_index=0, target_permanent_ids=[island.permanent_id],
    )

    assert not refused.supported
    assert basri.metadata["loyalty_counters"] == 3 and game.stack == []

    accepted = game.queue_permanent_ability(0, "Basri Ket", ability_index=0)

    assert accepted.supported and basri.metadata["loyalty_counters"] == 4


def test_a_target_in_a_conditional_sentence_is_announced_too(_by_name):
    """"{0}: **If this creature is tapped**, exile target creature card from a
    graveyard and untap this creature." (Eater of the Dead.) CR 601.2c makes a
    target conditional on a cost or a mode and on nothing else, so the card is
    owed as the ability is activated — and with every graveyard empty there is
    none."""
    game, (eater,), _ = _table(_by_name, ["Eater of the Dead"])
    eater.tapped = True

    refused = game.queue_permanent_ability(0, "Eater of the Dead")

    assert not refused.supported
    assert refused.details == "no valid target for Eater of the Dead"
    assert eater.tapped and game.stack == []

    game.players[1].graveyard.append(_by_name["Grizzly Bears"])
    accepted = game.activate_permanent_ability(
        0, "Eater of the Dead", target_player_index=1, target_permanent_index=0,
    )
    resolve_stack(game)

    assert accepted.supported and not eater.tapped
    assert game.players[1].graveyard == []
    assert [card.name for card in game.players[1].exile] == ["Grizzly Bears"]


def test_a_chosen_source_is_not_a_target_the_gate_asks_for(_by_name):
    """"The next time an unblocked creature **of your choice** would deal
    combat damage to you…" (Forcefield); "…an artifact source of your
    choice…" (Circle of Protection: Artifacts). Both derive a picker and
    neither line prints "target" (CR 609.7a: a source is chosen), so neither
    owes one: each is still activatable with nothing to pick."""
    for name in ("Forcefield", "Circle of Protection: Artifacts"):
        game, (source,), _ = _table(_by_name, [name])
        program_ability = usable_activated_abilities(
            compile_card_oracle(source.card)
        )[0]

        assert activation_target_obligation(program_ability) is None
        assert game.queue_permanent_ability(0, name).supported, name


def test_a_target_beside_a_chosen_source_is_still_a_target(_by_name):
    """"The next time a source of your choice would deal damage to **target
    creature** this turn, prevent that damage." (Charm Peddler.) The spec's
    ``requires_source`` says a source is chosen *as well*; the gate used to
    read it as "not a target" and never looked at the creature."""
    game, (peddler,), (island,) = _table(_by_name, ["Charm Peddler"], ["Island"])
    game.players[0].hand.append(_by_name["Island"])

    refused = game.queue_permanent_ability(
        0, "Charm Peddler", target_permanent_ids=[island.permanent_id],
    )

    assert not refused.supported
    assert refused.details == "no valid target for Charm Peddler"
    assert not peddler.tapped and len(game.players[0].hand) == 1


# ---------------------------------------------------------------------------
# An announcement that named nobody
# ---------------------------------------------------------------------------


def test_the_only_legal_target_is_the_one_a_bare_activation_names(_by_name):
    """"{1}{R}, {T}: Tahngarth deals damage equal to its power to target
    creature. That creature deals damage equal to its power to Tahngarth."
    Alone on the battlefield Tahngarth is its own only legal target. The
    handler's own pick looks at the other side of the table, so the ability
    used to tap Tahngarth and do nothing; with one legal announcement there is
    nothing to choose between, and the engine makes it."""
    game, (tahngarth,), _ = _table(_by_name, ["Tahngarth, Talruum Hero"])

    result = game.activate_permanent_ability(0, "Tahngarth, Talruum Hero")
    resolve_stack(game)

    assert result.supported
    assert any(
        line == "Tahngarth, Talruum Hero deals 4 damage to Tahngarth, Talruum Hero"
        for line in game.log
    ), game.log
    assert not game.is_on_battlefield(tahngarth)    # 8 damage on a 4/4


def test_several_legal_targets_leave_a_bare_activation_to_the_handler(_by_name):
    """…and only then. With two creatures to choose between the announcement
    is not the engine's to make, and the handler's standing pick — the
    opposing creature — is what resolves, as it always has."""
    game, (tahngarth,), (bears,) = _table(
        _by_name, ["Tahngarth, Talruum Hero"], ["Grizzly Bears"],
    )

    result = game.activate_permanent_ability(0, "Tahngarth, Talruum Hero")
    resolve_stack(game)

    assert result.supported and not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(tahngarth) and tahngarth.damage_marked == 2


@pytest.mark.parametrize(
    "name", ["Oasis", "Samite Sanctuary", "Squee's Toy", "Samite Pilgrim"],
)
def test_a_creature_only_shield_announced_bare_never_arms_a_player(_by_name, name):
    """"Prevent the next 1 damage that would be dealt to **target creature**
    this turn." The shield handler's last branch was "no creature, so the
    player" — "any target"'s answer — and the default seat is the opponent:
    eight of the pool's ten such abilities shielded the *opponent* when
    announced bare. A player is not a creature; the bare announcement takes
    the first creature the picker offers, the controller's own first."""
    game, mine, (theirs,) = _table(
        _by_name, [name, "Plains", "Grizzly Bears"], ["Grizzly Bears"],
    )

    result = game.activate_permanent_ability(0, name)
    resolve_stack(game)

    assert result.supported, result.details
    assert not shields_on(game.players[0]) and not shields_on(game.players[1])
    assert not shields_on(theirs)
    shielded = [permanent for permanent in mine if shields_on(permanent)]
    assert len(shielded) == 1 and shielded[0].is_creature


def test_the_bare_shield_default_is_a_legal_target(_by_name):
    """The default is the picker's, so it is a creature the ability could have
    targeted: a Black Knight has protection from white and Samite Sanctuary is
    white, so the Knight in front of the Bears is passed over."""
    game, (_sanctuary, knight, bears), _ = _table(
        _by_name, ["Samite Sanctuary", "Black Knight", "Grizzly Bears"],
    )

    result = game.activate_permanent_ability(0, "Samite Sanctuary")
    resolve_stack(game)

    assert result.supported
    assert shields_on(bears) and not shields_on(knight)
    assert not shields_on(game.players[0]) and not shields_on(game.players[1])


def test_a_creature_only_shield_whose_target_left_shields_nobody(_by_name):
    """CR 608.2b's last sentence, for the same sentence: the named creature is
    gone at resolution, so nothing is shielded — not its controller."""
    game, (oasis, bears), _ = _table(_by_name, ["Oasis", "Grizzly Bears"])

    queued = game.queue_permanent_ability(
        0, "Oasis", target_permanent_ids=[bears.permanent_id],
    )
    assert queued.supported
    game.remove_from_battlefield(bears)
    resolve_stack(game)

    assert oasis.tapped
    assert not shields_on(game.players[0]) and not shields_on(game.players[1])
