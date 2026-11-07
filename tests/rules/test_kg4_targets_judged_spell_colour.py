"""A spell's legal targets, asked while another object resolves, are judged
by the colour the spell *is* (CR 115.7a, 707.10c, 702.16b, 702.11d, 105.3).

    115.7a If an effect allows a player to "change the target(s)" of a spell
    or ability, each target can be changed only to another legal target.

A target is legal for a spell by what the spell is now — a Lace's recolour
on the stack object (CR 105.3), a copy's own colour (Fork: "except that the
copy is red"; CR 707.2: a Lace on the original is not a copiable value). The
legality predicate (``_can_be_targeted`` and the CR 702.16b / 702.11d /
"can't be the target of white spells" questions under it) is handed the
spell's *card*, and ``object_colors.spell_colors`` could name the stack
object behind a card only while that object was the one resolving. Every
road that enumerates a spell's targets from inside **another** object's
resolution therefore read the printed colour:

* a retarget — Deflection, Meddle, Silver Wyvern (``_legal_new_targets``);
* CR 115.7's change by an event — Psychic Battle (``stack_targets.change_slots``,
  which Grip of Chaos's reselect reads too);
* a copy that may choose new targets — Fork's red copy
  (``arm_copy_spell_target``).

And hexproof from a colour read the printed colour even of the spell that
was resolving (``object_colors.card_colors``, not ``spell_colors``); and the
resolving spell was found by its printed card alone, where CR 608.2b's
re-check hands over what a text change made it (``spell_text_card``).

Two copies are controls, right on the base and held here because the fix
names the copy as the object judged: Chain Lightning's copy (it shares its
Laced original's card, and is offered only after the original's resolution
has popped — a copy asked *during* it would have read the original's Lace),
and a storm copy (made by a trigger, an ability).

The board for each: a spell made one colour, candidates with protection (or
hexproof, or a "can't be the target of … spells") from the new colour and
from the old, and the offer the road makes read off the prompt an
interactive seat is asked — so the offer, not an internal list, is what is
asserted. Each road's own control (the colour it would have had) is in the
same assertion: the creature guarded against the *old* colour must be
offered.

Measured backwards on 313bd09d: nine of the eleven fail — every road but the
two copy controls offered the creature guarded against the spell's new
colour and withheld the one guarded against its old (Meddle and Silver
Wyvern moved a white Bolt onto Black Knight), the Thoughtlaced Bolt was
refused at Sporeweb Weaver, and the text-changed Terror passed the CR 608.2b
gate to be caught a step late. With only the hexproof seed of
``test_kg4_targets_hexproof_from.py`` applied, the same nine fail.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.text_changes import spell_text_card
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}

def _table(*, mine=(), theirs=(), hand0=(), hand1=(), library0=None, library1=None,
           interactive=(0,)) -> Game:
    game = Game(players=[
        PlayerState("P0", hand=[_POOL[name] for name in hand0],
                    library=[_POOL[name] for name in (library0 or ["Island"] * 10)]),
        PlayerState("P1", hand=[_POOL[name] for name in hand1],
                    library=[_POOL[name] for name in (library1 or ["Island"] * 10)]),
    ])
    game.enforce_mana_costs = False
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_POOL[name])
            permanent.metadata["summoning_sickness_turn"] = -99
            game._put_permanent_onto_battlefield(seat, permanent, None)
    game.start_turn(0)
    game._close_current_priority_step()
    game.interactive_seats = set(interactive)
    return game


def _on(game: Game, name: str) -> Permanent:
    found = [perm for perm in game.all_permanents() if perm.card.name == name]
    assert len(found) == 1, (name, [perm.card.name for perm in game.all_permanents()])
    return found[0]


def _lace(game: Game, seat: int, lace: str) -> None:
    """Cast *lace* (in *seat*'s hand) at the top spell and resolve it alone."""
    depth = len(game.stack)
    assert game.queue_from_hand(seat, lace, target_stack_index=0).supported, game.log[-4:]
    game.resolve_top_of_stack()
    assert len(game.stack) == depth, game.log[-4:]


def _offer(game: Game, kind: str, seat: int) -> list[str]:
    choice = next(
        (c for c in game.pending_choices if c.kind == kind and c.player_index == seat),
        None,
    )
    assert choice is not None, (kind, [c.kind for c in game.pending_choices], game.log[-6:])
    key = "targets" if kind == "copy_spell_target" else "options"
    return [str(option.get("name", "")) for option in choice.data.get(key) or ()]


def _guards(names, *, offered, withheld, road):
    """The road's offer, both ways. *offered* being present is the floor: a
    road that offered nothing fails here rather than passing on an empty
    list."""
    # A label may name the controller ("P1's Repentant Blacksmith",
    # ``stack_targets.target_label``).
    def named(card_name):
        return any(name == card_name or name.endswith("'s " + card_name) for name in names)

    assert named(offered), (road, names)
    assert not named(withheld), (road, names)


# --- the retargets (``handlers/retargeting._legal_new_targets``) -------------


@pytest.mark.cr("115.7a", "702.16b", "105.3")
def test_deflection_judges_a_laced_bolts_new_target_by_its_new_colour():
    """The entry's own board. Purelace made the Bolt white: Black Knight
    (protection from white) is no longer a legal target for it, and Repentant
    Blacksmith (protection from red) now is."""
    game = _table(
        theirs=["Grizzly Bears", "Black Knight", "Repentant Blacksmith"],
        hand0=["Purelace", "Deflection"], hand1=["Lightning Bolt"],
    )
    bears = _on(game, "Grizzly Bears")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _lace(game, 0, "Purelace")
    assert game.queue_from_hand(0, "Deflection", target_stack_index=0).supported
    game.resolve_top_of_stack()
    _guards(_offer(game, "retarget_choice", 0),
            offered="Repentant Blacksmith", withheld="Black Knight", road="Deflection")


@pytest.mark.cr("115.7a", "702.16b", "105.3")
def test_meddle_judges_the_new_creature_by_the_spells_new_colour():
    game = _table(
        theirs=["Grizzly Bears", "Hill Giant", "Black Knight", "Repentant Blacksmith"],
        hand0=["Purelace", "Meddle"], hand1=["Lightning Bolt"],
    )
    bears = _on(game, "Grizzly Bears")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _lace(game, 0, "Purelace")
    assert game.queue_from_hand(0, "Meddle", target_stack_index=0).supported
    game.resolve_top_of_stack()
    _guards(_offer(game, "retarget_choice", 0),
            offered="Repentant Blacksmith", withheld="Black Knight", road="Meddle")


@pytest.mark.cr("115.7a", "702.16b", "105.3")
def test_silver_wyverns_ability_judges_the_new_creature_by_the_spells_new_colour():
    """An ability doing the retargeting: the spell still answers for itself."""
    game = _table(
        mine=["Silver Wyvern", "Hill Giant", "Black Knight", "Repentant Blacksmith"],
        hand0=["Purelace"], hand1=["Lightning Bolt"],
    )
    wyvern = _on(game, "Silver Wyvern")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[wyvern.permanent_id],
    ).supported
    _lace(game, 0, "Purelace")
    assert game.queue_permanent_ability(
        0, "Silver Wyvern", target_stack_index=0, ability_index=0,
    ).supported, game.log[-4:]
    game.resolve_top_of_stack()
    _guards(_offer(game, "retarget_choice", 0),
            offered="Repentant Blacksmith", withheld="Black Knight", road="Silver Wyvern")


@pytest.mark.cr("115.7a", "702.11d", "105.3")
def test_hexproof_from_blue_refuses_a_thoughtlaced_bolt_as_a_new_target():
    """CR 702.11d asks what colour the spell is: Thoughtlace made the Bolt
    blue, so Sporeweb Weaver (hexproof from blue) cannot be its new target —
    and a Bolt left red could be."""
    game = _table(
        mine=["Grizzly Bears", "Sporeweb Weaver", "Garruk's Harbinger"],
        hand0=["Thoughtlace", "Deflection"], hand1=["Lightning Bolt"],
    )
    bears = _on(game, "Grizzly Bears")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _lace(game, 0, "Thoughtlace")
    assert game.queue_from_hand(0, "Deflection", target_stack_index=0).supported
    game.resolve_top_of_stack()
    # Garruk's Harbinger (hexproof from black) is the control: hexproof
    # from a colour is that colour's alone.
    _guards(_offer(game, "retarget_choice", 0),
            offered="Garruk's Harbinger", withheld="Sporeweb Weaver",
            road="hexproof from blue")


@pytest.mark.cr("115.7a", "105.3")
def test_cant_be_the_target_of_white_spells_refuses_a_purelaced_bolt():
    """"This creature can't be the target of white spells …" (Rebel
    Informer): a white Bolt may not be moved onto it, a red one may."""
    game = _table(
        theirs=["Grizzly Bears", "Rebel Informer", "Suq'Ata Firewalker"],
        hand0=["Purelace", "Deflection"], hand1=["Lightning Bolt"],
    )
    bears = _on(game, "Grizzly Bears")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _lace(game, 0, "Purelace")
    assert game.queue_from_hand(0, "Deflection", target_stack_index=0).supported
    game.resolve_top_of_stack()
    # Suq'Ata Firewalker "can't be the target of red spells": the control.
    _guards(_offer(game, "retarget_choice", 0),
            offered="Suq'Ata Firewalker", withheld="Rebel Informer",
            road="can't be the target of white spells")


# --- CR 115.7 by an event (``stack_targets.change_slots``) -------------------


@pytest.mark.cr("115.7a", "702.16b", "105.3")
def test_psychic_battle_offers_the_laced_bolts_targets_by_its_new_colour():
    """Psychic Battle's change reads ``change_slots`` — the reader Grip of
    Chaos's reselect reads too. The Bolt's own trigger resolves after the
    Lace has made it white; seat 0 reveals the greater mana value each time."""
    game = _table(
        mine=["Psychic Battle"],
        theirs=["Grizzly Bears", "Black Knight", "Repentant Blacksmith"],
        hand0=["Purelace"], hand1=["Lightning Bolt"],
        library0=["Shivan Dragon"] * 10, library1=["Island"] * 10,
    )
    bears = _on(game, "Grizzly Bears")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert len(game.stack) == 2, [item.card.name for item in game.stack]  # the Bolt's trigger
    # ``target_stack_index`` counts from the bottom on the cast path.
    assert game.queue_from_hand(0, "Purelace", target_stack_index=0).supported, game.log[-4:]
    # The Lace's own trigger: seat 0 keeps the Lace on the Bolt.
    game.resolve_top_of_stack()
    keep = _offer(game, "retarget_choice", 0)
    assert game.confirm_retarget_choice(0, 0), keep
    game.resolve_top_of_stack()  # the Lace (and its held trigger, if any)
    while game.stack and game.stack[-1].card.name == "Purelace":
        game.resolve_top_of_stack()
    assert game._stack_item_colors(game.stack[0]) == ("W",), game.log[-6:]
    game.resolve_top_of_stack()  # the Bolt's trigger
    _guards(_offer(game, "retarget_choice", 0),
            offered="Repentant Blacksmith", withheld="Black Knight", road="Psychic Battle")


# --- copies that may choose new targets (CR 707.10c) -------------------------


@pytest.mark.cr("707.10c", "707.2", "702.16b")
def test_forks_red_copy_is_offered_targets_as_a_red_spell():
    """"Copy target instant or sorcery spell, except that the copy is red."
    A copied Terror is a red spell: Repentant Blacksmith (protection from red)
    is no target for it, and White Knight (protection from black) is."""
    game = _table(
        theirs=["Grizzly Bears", "White Knight", "Repentant Blacksmith"],
        hand0=["Terror", "Fork"],
    )
    bears = _on(game, "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Terror", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported
    game.resolve_top_of_stack()  # Fork
    _guards(_offer(game, "copy_spell_target", 0),
            offered="White Knight", withheld="Repentant Blacksmith", road="Fork")


@pytest.mark.cr("707.10c", "707.2", "702.16b")
def test_chain_lightnings_copy_is_not_the_laced_original():
    """A control: a Lace on the original is not copied (CR 707.2: "other
    effects … are not copied"), so the copy is red though it shares the
    white original's card — named as the object judged, it is not taken for
    the original."""
    game = _table(
        mine=["Black Knight", "Repentant Blacksmith"],
        theirs=["Mountain", "Mountain", "Grizzly Bears"],
        hand0=["Chain Lightning", "Purelace"], interactive=(1,),
    )
    bears = _on(game, "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Chain Lightning", target_permanent_ids=[bears.permanent_id],
    ).supported
    _lace(game, 0, "Purelace")
    game.resolve_top_of_stack()  # Chain Lightning
    assert game.confirm_optional_pay(1, accept=True), game.log[-4:]   # the {R}{R}
    assert game.confirm_optional_pay(1, accept=True), game.log[-4:]   # "may copy this spell"
    _guards(_offer(game, "copy_spell_target", 1),
            offered="Black Knight", withheld="Repentant Blacksmith", road="Chain Lightning")


@pytest.mark.cr("702.40a", "707.2", "702.16b")
def test_a_storm_copy_of_a_laced_spell_is_its_printed_colour():
    """The control on the copy side: a storm copy is made by a trigger (an
    ability resolving), and a Lace on the original is not copied, so the
    copy is red — offered the white-guarded Black Knight, not the Blacksmith."""
    game = _table(
        theirs=["Grizzly Bears", "Black Knight", "Repentant Blacksmith"],
        hand0=["Dark Ritual", "Scattershot", "Purelace"],
    )
    assert game.queue_from_hand(0, "Dark Ritual").supported
    resolve_stack(game)
    bears = _on(game, "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[bears.permanent_id],
    ).supported
    # Under the storm trigger: the Lace goes on the Scattershot, below it.
    assert game.queue_from_hand(0, "Purelace", target_stack_index=0).supported, game.log[-4:]
    game.resolve_top_of_stack()  # the Lace
    game.resolve_top_of_stack()  # storm
    _guards(_offer(game, "copy_spell_target", 0),
            offered="Black Knight", withheld="Repentant Blacksmith", road="storm")


# --- CR 608.2b at the spell's own resolution ---------------------------------


@pytest.mark.cr("608.2b", "702.11d", "105.3")
def test_a_thoughtlaced_bolt_at_sporeweb_weaver_is_countered_on_resolution():
    """Hexproof from blue is asked of the spell resolving, by its colour now."""
    game = _table(mine=["Sporeweb Weaver"], hand0=["Thoughtlace"], hand1=["Lightning Bolt"])
    weaver = _on(game, "Sporeweb Weaver")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[weaver.permanent_id],
    ).supported
    _lace(game, 0, "Thoughtlace")
    resolve_stack(game)
    assert game.is_on_battlefield(weaver) and weaver.damage_marked == 0, game.log[-6:]
    assert any("Lightning Bolt" in line and "608.2b" in line for line in game.log), game.log[-6:]


@pytest.mark.cr("608.2b", "612.1", "702.16b", "105.3")
def test_a_text_changed_and_laced_terror_is_judged_by_its_lace():
    """A spell whose text was changed is asked as the card it now says
    (``spell_text_card``), which is not the printed card object — and the
    resolving spell was found by the printed one. Sleight of Mind made
    Terror's "nonblack" "nongreen", Chaoslace made it red: Repentant
    Blacksmith (protection from red) is an illegal target on resolution."""
    game = _table(
        theirs=["Repentant Blacksmith"],
        hand0=["Terror", "Sleight of Mind", "Chaoslace"],
    )
    smith = _on(game, "Repentant Blacksmith")
    assert game.queue_from_hand(
        0, "Terror", target_permanent_ids=[smith.permanent_id],
    ).supported
    assert game.queue_from_hand(
        0, "Sleight of Mind", target_stack_index=0, old_color="B", new_color="G",
    ).supported, game.log[-4:]
    game.resolve_top_of_stack()
    assert "nongreen" in spell_text_card(game.stack[0]).oracle_text, game.log[-4:]
    _lace(game, 0, "Chaoslace")
    assert game._stack_item_colors(game.stack[0]) == ("R",), game.log[-6:]
    resolve_stack(game)
    assert game.is_on_battlefield(smith), game.log[-6:]
    # CR 608.2b's own answer, the one that removes the spell — not the
    # handler's later "does nothing", which caught it one step behind.
    assert any("Terror" in line and "608.2b" in line for line in game.log), game.log[-6:]
