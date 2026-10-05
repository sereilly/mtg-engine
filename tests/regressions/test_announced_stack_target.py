"""CR 601.2c for a spell that targets a spell: the announcement gate and the
picker are one list.

Found on Invasion's Spite ("Counter target noncreature spell."), the pool's
first *spell* to print that phrase — every earlier printing is an activated
ability, whose gate already asked. A spell's named stack target was checked by
the counter arm of ``_validate_cast_targets`` and that arm asks one question,
the colour. Every other narrowing a counterspell prints was enforced by the
picker (never offered) and by the handler (declined at resolution) and by
nothing in between, so the engine accepted the announcement:

    Remove Soul ("Counter target creature spell.") at a Lightning Bolt
      -> cast accepted, {1}{U} spent, Remove Soul in the graveyard,
         the Bolt resolves for 3.

Not wrong in the caster's favour — nothing illegal is ever countered — but
CR 601.2c makes that cast illegal, and an AI or a client that names the wrong
spell pays for a card that does nothing. ``legality.cast_stack_target_refusal``
is the gate; this sweep holds it to every stack-targeting spell in the pool.

**Validated backwards**, as a census has to be: with the gate switched off the
sweep must find the Remove Soul case above, and it carries a floor on how many
announcements it examined — a sweep that examined none passes on any tree.
"""

from __future__ import annotations

import pytest

from engine.faces import compilation_units, whole_card
from engine import Game
from engine.card_loader import load_catalog
from engine.models import PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec

#: One spell of each kind a printed narrowing can tell apart: a creature, an
#: artifact, an enchantment, an instant and a sorcery, over three colours.
_VICTIMS = (
    "Grizzly Bears", "Sol Ring", "Crusade", "Lightning Bolt", "Mind Twist",
    "Ancestral Recall",
    # …and one spell with **two** card types (CR 205.2), added at the W1G5
    # integration. Every victim above has one, so a picker that read a spell's
    # type off ``primary_type`` agreed with the gate on all of them — and the
    # gate, which is that picker's list, refused Annul aimed at this.
    "Ornithopter",
)


def _stack_targeting_spells(catalog):
    """Every non-modal instant or sorcery whose cast spec points at the stack."""
    for card in compilation_units(catalog):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        spec = derive_cast_spec(card, program)
        if spec is not None and spec.get("kind") == "stack":
            yield card, spec


def _announce(card, spec, victim, by_name):
    """Seat 1 answers seat 0's *victim* with *card*. Returns ``(offered,
    accepted)``: whether the picker lists the victim, and whether the engine
    took the announcement."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.players[0].hand.append(by_name[victim])
    # The hand holds the card; the cast below names the spell — a half of a
    # split card by its own name (CR 709.3).
    game.players[1].hand.append(whole_card(card))
    queued = game.queue_from_hand(0, victim, target_player_index=1)
    if not queued.supported or len(game.stack) != 1:
        return None
    offered = any(
        entry.get("stack_index") == 0
        for entry in game._enumerate_stack_targets(1, card, spec)
    )
    try:
        result = game.queue_from_hand(1, card.name, target_stack_index=0)
    except Exception:  # noqa: BLE001 - a card needing more than a target is not this sweep's
        return None
    return offered, result.supported


def _sweep(catalog):
    by_name = {card.name: card for card in catalog}
    examined = 0
    accepted_unoffered: list[tuple[str, str]] = []
    for card, spec in _stack_targeting_spells(catalog):
        for victim in _VICTIMS:
            outcome = _announce(card, spec, victim, by_name)
            if outcome is None:
                continue
            examined += 1
            offered, accepted = outcome
            if accepted and not offered:
                accepted_unoffered.append((card.name, victim))
    return examined, accepted_unoffered


@pytest.fixture(scope="module")
def _catalog():
    return load_catalog()


def test_no_spell_can_be_announced_at_a_spell_its_picker_would_not_offer(_catalog):
    examined, accepted_unoffered = _sweep(_catalog)

    assert examined >= 200, f"the sweep examined only {examined} announcements"
    assert accepted_unoffered == [], (
        "CR 601.2c: these spells were announced, and paid for, at a spell their "
        f"printed target phrase does not admit: {accepted_unoffered}"
    )


def test_the_sweep_finds_the_defect_on_a_tree_that_has_it(_catalog, monkeypatch):
    """The backwards half. Without the gate, Remove Soul at a Lightning Bolt is
    accepted — the known defect, by name — so the sweep above is not passing
    because it looks at nothing."""
    monkeypatch.setattr(
        Game, "cast_stack_target_refusal", lambda self, *args, **kwargs: None,
    )
    _examined, accepted_unoffered = _sweep(_catalog)

    assert ("Remove Soul", "Lightning Bolt") in accepted_unoffered
    assert len({name for name, _victim in accepted_unoffered}) >= 10


def test_remove_soul_aimed_at_an_instant_is_refused_with_nothing_spent(_catalog):
    by_name = {card.name: card for card in _catalog}
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = True
    p0, p1 = game.players
    p0.hand.append(by_name["Lightning Bolt"])
    p1.hand.append(by_name["Remove Soul"])
    p0.mana_pool["R"] = 1
    p1.mana_pool["U"] = 2
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported

    refused = game.queue_from_hand(1, "Remove Soul", target_stack_index=0)

    assert not refused.supported
    assert refused.details == "no valid target for Remove Soul"
    assert [card.name for card in p1.hand] == ["Remove Soul"]
    assert p1.mana_pool["U"] == 2 and len(game.stack) == 1


def _handler_acts_where_the_picker_does_not_offer(catalog):
    """``(examined, findings)``: with the announcement gate off, every stack
    spell is cast at every victim and resolved, and a victim that **left the
    stack** although the picker did not offer it is a finding.

    The other half of the sweep above. That one holds the gate to the picker;
    this holds the picker to the handler, which is the reading CR 601.2c is
    actually about — and the half the gate cannot check, because it *is* the
    picker's list. A spell that does not remove its target (Fork, Deflection)
    never produces a finding here and is not a claim either way.
    """
    by_name = {card.name: card for card in catalog}
    examined = 0
    findings: list[tuple[str, str]] = []
    for card, spec in _stack_targeting_spells(catalog):
        for victim in _VICTIMS:
            game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
            game.enforce_mana_costs = False
            game.players[0].hand.append(by_name[victim])
            game.players[1].hand.append(card)
            queued = game.queue_from_hand(0, victim, target_player_index=1)
            if not queued.supported or len(game.stack) != 1:
                continue
            victim_item = game.stack[0]
            offered = any(
                entry.get("stack_index") == 0
                for entry in game._enumerate_stack_targets(1, card, spec)
            )
            try:
                result = game.queue_from_hand(1, card.name, target_stack_index=0)
                if not result.supported:
                    continue
                game.resolve_top_of_stack()
            except Exception:  # noqa: BLE001 - needs more than a target; not this sweep's
                continue
            examined += 1
            removed = not any(item is victim_item for item in game.stack)
            if removed and not offered:
                findings.append((card.name, victim))
    return examined, findings


def test_the_picker_offers_every_spell_the_handler_would_act_on(_catalog, monkeypatch):
    monkeypatch.setattr(
        Game, "cast_stack_target_refusal", lambda self, *args, **kwargs: None,
    )
    examined, findings = _handler_acts_where_the_picker_does_not_offer(_catalog)

    assert examined >= 200, f"the sweep examined only {examined} resolutions"
    assert findings == [], (
        "CR 601.2c / CR 205.2: the handler acts on these spells and the picker "
        f"- which is the announcement gate - does not offer them: {findings}"
    )


def test_annul_counters_an_artifact_creature_spell(_catalog):
    """The case by name: an artifact creature spell is an artifact spell."""
    by_name = {card.name: card for card in _catalog}
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    p0, p1 = game.players
    p0.hand.append(by_name["Ornithopter"])
    p1.hand.append(by_name["Annul"])
    assert game.queue_from_hand(0, "Ornithopter").supported

    cast = game.queue_from_hand(1, "Annul", target_stack_index=0)
    assert cast.supported, cast.details
    game.resolve_top_of_stack()

    assert game.stack == []
    assert [card.name for card in p0.graveyard] == ["Ornithopter"]
    assert not any(perm.card.name == "Ornithopter" for perm in game.all_permanents())


# --- INV W2G3: one gate - the bare announcement, its default, the resolution ---
#
# Invasion's first wave left two CR 601.2c gates for a spell that targets an
# object on the stack: the one above (W1G2, a *named* spell, every spec key)
# and a second beside it (W1G8, four spec keys, which also refused a bare cast
# with nothing to name and was re-asked at resolution). They are one now -
# ``cast_stack_target_refusal`` over ``_offered_stack_targets`` - and the
# sweeps below hold the two behaviours the second gate had to **every** key.

from engine.models import Permanent as _W2G3Permanent
from tests.helpers import _mk_card as _w2g3_mk_card

#: Seat 0's lone object on the stack: the spells above, and one **ability** -
#: which is not a spell (CR 113.7a), so "target spell" admits none of it.
_W2G3_ABILITY = "Prodigal Sorcerer's ability"
_W2G3_LONE_OBJECTS = _VICTIMS + (_W2G3_ABILITY,)


def _w2g3_table(card, by_name, victim=None):
    """Seat 1 holds *card*; seat 0 has put *victim* on the stack (or nothing).
    Returns ``(game, victim_item)``, or None when the victim could not be
    queued."""
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 6)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.players[1].hand.append(card)
    if victim is None:
        return game, None
    if victim == _W2G3_ABILITY:
        sorcerer = _W2G3Permanent(card=by_name["Prodigal Sorcerer"])
        game._put_permanent_onto_battlefield(0, sorcerer, None)
        sorcerer.metadata["summoning_sickness_turn"] = -99
        queued = game.queue_permanent_ability(
            0, "Prodigal Sorcerer", target_player_index=1,
        )
    else:
        game.players[0].hand.append(by_name[victim])
        queued = game.queue_from_hand(0, victim, target_player_index=1)
    if not queued.supported or len(game.stack) != 1:
        return None
    return game, game.stack[0]


def _w2g3_bare_sweep(catalog):
    """``(empties, lone, accepted_empty, accepted_lone)``: every stack spell
    cast **naming nothing**, onto an empty stack and over each lone object its
    picker does not offer. An accepted cast is a finding - CR 601.2c has no
    legal target to choose."""
    by_name = {card.name: card for card in catalog}
    empties = lone = 0
    accepted_empty: list[str] = []
    accepted_lone: list[tuple[str, str]] = []
    for card, spec in _stack_targeting_spells(catalog):
        game, _item = _w2g3_table(card, by_name)
        try:
            result = game.queue_from_hand(1, card.name)
        except Exception:  # noqa: BLE001 - needs more than a target; not this sweep's
            result = None
        if result is not None:
            empties += 1
            if result.supported:
                accepted_empty.append(card.name)
        for victim in _W2G3_LONE_OBJECTS:
            seated = _w2g3_table(card, by_name, victim)
            if seated is None:
                continue
            game, _item = seated
            if game._enumerate_stack_targets(1, card, spec):
                continue
            try:
                result = game.queue_from_hand(1, card.name)
            except Exception:  # noqa: BLE001 - as above
                continue
            lone += 1
            if result.supported:
                accepted_lone.append((card.name, victim))
    return empties, lone, accepted_empty, accepted_lone


def test_no_stack_spell_can_be_cast_bare_with_nothing_to_name(_catalog):
    empties, lone, accepted_empty, accepted_lone = _w2g3_bare_sweep(_catalog)

    assert empties >= 40, f"only {empties} empty-stack casts examined"
    assert lone >= 120, f"only {lone} lone-object casts examined"
    assert accepted_empty == [], (
        "CR 601.2c: cast onto an empty stack, with no object to target: "
        f"{accepted_empty}"
    )
    assert accepted_lone == [], (
        "CR 601.2c: cast bare over a lone object the printed target phrase "
        f"does not admit: {accepted_lone}"
    )


def test_the_bare_sweep_finds_the_defect_on_a_tree_that_has_it(_catalog, monkeypatch):
    """Backwards. Without the gate the counter arm's "is the stack empty" is
    all that is asked, and only of a spell whose *first* instruction is the
    counter: Rewind (a ``sequence``) goes onto an empty stack, Remove Soul over
    a lone instant, and Counterspell over a lone activated ability."""
    monkeypatch.setattr(
        Game, "cast_stack_target_refusal", lambda self, *args, **kwargs: None,
    )
    _empties, _lone, accepted_empty, accepted_lone = _w2g3_bare_sweep(_catalog)

    assert "Rewind" in accepted_empty and len(accepted_empty) >= 10
    assert ("Remove Soul", "Lightning Bolt") in accepted_lone
    assert ("Counterspell", _W2G3_ABILITY) in accepted_lone
    assert len({name for name, _victim in accepted_lone}) >= 30


def test_rewind_cannot_be_cast_onto_an_empty_stack_to_untap_four_lands(_catalog):
    """The case by name, and the one that paid: "Counter target spell. Untap up
    to four lands." compiles to a ``sequence``, which no per-kind arm reads -
    so it was castable with nothing to counter and its second sentence resolved
    on its own."""
    by_name = {card.name: card for card in _catalog}
    game, _item = _w2g3_table(by_name["Rewind"], by_name)
    lands = []
    for _ in range(4):
        land = _W2G3Permanent(card=by_name["Island"])
        game._put_permanent_onto_battlefield(1, land, None)
        land.tapped = True
        lands.append(land)

    refused = game.queue_from_hand(1, "Rewind")

    assert not refused.supported
    assert refused.details == "no valid target for Rewind"
    assert [card.name for card in game.players[1].hand] == ["Rewind"]
    assert all(land.tapped for land in lands) and game.stack == []


def test_a_bare_counter_is_aimed_at_the_topmost_spell_its_phrase_admits(_catalog):
    """A caller that names nothing is given a *legal* target. The default was a
    regex over the oracle text that read the colour word and nothing else, so a
    bare Remove Soul over a creature spell and an instant took the instant on
    top and countered nothing; it is the gate's own enumeration now."""
    by_name = {card.name: card for card in _catalog}
    game, bears = _w2g3_table(by_name["Remove Soul"], by_name, "Grizzly Bears")
    game.players[0].hand.append(by_name["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    bolt = game.stack[-1]

    assert game.queue_from_hand(1, "Remove Soul").supported
    assert game.stack[-1].target_stack_item is bears
    game.resolve_top_of_stack()

    assert game.stack == [bolt]
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears"]


def test_unsubstantiate_cannot_name_an_ability(_catalog):
    """"Return target **spell** or creature to its owner's hand." An ability is
    not a spell (CR 113.7a) and has no card to return - named at one, the spell
    put the *source permanent's card* into its owner's hand while the permanent
    stayed on the battlefield: a card made out of nothing. The stack half of a
    ``spell_or_permanent`` spec goes through the same gate."""
    by_name = {card.name: card for card in _catalog}
    game, ability = _w2g3_table(by_name["Unsubstantiate"], by_name, _W2G3_ABILITY)

    refused = game.queue_from_hand(1, "Unsubstantiate", target_stack_index=0)

    assert not refused.supported
    assert refused.details == "no valid target for Unsubstantiate"
    assert game.players[0].hand == [] and len(game.stack) == 1
    assert game.stack[0] is ability
    assert [card.name for card in game.players[1].hand] == ["Unsubstantiate"]


def test_unsubstantiate_still_returns_a_spell(_catalog):
    by_name = {card.name: card for card in _catalog}
    game, _bolt = _w2g3_table(by_name["Unsubstantiate"], by_name, "Lightning Bolt")

    assert game.queue_from_hand(1, "Unsubstantiate", target_stack_index=0).supported
    game.resolve_top_of_stack()

    assert game.stack == []
    assert [card.name for card in game.players[0].hand] == ["Lightning Bolt"]


def _w2g3_red_counter():
    """An invented card - no shipped non-modal spell prints a colour-keyed
    counter with a second sentence, which is why the resolution re-check below
    could be missing for every key but four without a card showing it."""
    return _w2g3_mk_card(
        "Douse the Embers", "{1}{U}", "Instant",
        "Counter target red spell.\nDraw a card.", colors=("U",),
    )


def _w2g3_recoloured_in_response(by_name):
    """Lightning Bolt, the invented counter aimed at it, and Purelace turning
    the Bolt white in response - resolved, so the counter is next."""
    counter = _w2g3_red_counter()
    game, bolt = _w2g3_table(counter, by_name, "Lightning Bolt")
    assert game.queue_from_hand(1, counter.name, target_stack_index=0).supported
    game.players[0].hand.append(by_name["Purelace"])
    assert game.queue_from_hand(
        0, "Purelace", target_stack_index=0, new_color="W",
    ).supported
    game.resolve_top_of_stack()
    return game, bolt


def test_a_stack_target_that_stopped_answering_its_description_is_illegal(_catalog):
    """CR 608.2b: "its characteristics may have changed". The Bolt is white by
    the time the counter resolves, so the counter's only target is illegal and
    it does not resolve at all - the card is **not** drawn."""
    by_name = {card.name: card for card in _catalog}
    counter = _w2g3_red_counter()
    assert derive_cast_spec(counter, compile_card_oracle(counter)) == {
        "kind": "stack", "stack_color_filter": "R",
    }
    game, bolt = _w2g3_recoloured_in_response(by_name)
    hand = len(game.players[1].hand)

    game.resolve_top_of_stack()

    assert len(game.stack) == 1 and game.stack[0] is bolt
    assert len(game.players[1].hand) == hand
    assert any("608.2b" in line for line in game.log)


def test_without_the_re_check_the_sentence_behind_the_counter_still_ran(
    _catalog, monkeypatch
):
    """Backwards: the handler re-read the colour for itself and declined, and
    "Draw a card." resolved anyway. That is 608.2b's last sentence standing in
    for its first."""
    by_name = {card.name: card for card in _catalog}
    game, bolt = _w2g3_recoloured_in_response(by_name)
    hand = len(game.players[1].hand)
    monkeypatch.setattr(
        Game, "_offered_stack_targets", lambda self, *args, **kwargs: None,
    )

    game.resolve_top_of_stack()

    assert len(game.stack) == 1 and game.stack[0] is bolt
    assert len(game.players[1].hand) == hand + 1
