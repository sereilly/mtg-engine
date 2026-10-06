"""CR 614.12: a permanent enters as it would exist on the battlefield.

"To determine which replacement effects apply and how they apply, check the
characteristics of the permanent as it would exist on the battlefield, taking
into account … continuous effects that already exist and would apply to the
permanent."

The engine judged an entry by the permanent as *printed*, because what the
board's statics make of a permanent is written by a pass that runs as the last
thing an entry does. The round before this one folded one family of static in
ahead of the entry (land types: a Karoo under Blood Moon). This is the rule for
the rest — ``Game.fold_board_statics_onto_entering``, which runs the pass
itself with the entering permanent in its list.

**Two censuses, both over the pool.**

*What it will have.* Humility and Titania's Song take every ability, so a
permanent they will reach has none as it enters: it does not enter tapped,
enters with no counters and makes no "as this enters" choice, whatever it
prints. Every creature (noncreature artifact) in the pool whose entry differs
from a vanilla one is entered under Humility (the Song): 133 creatures and 30
artifacts. On the tree before the fix 68 of the creatures and 28 of the
artifacts entered as printed (the other creatures differ by an entry
*trigger*, which already read the board; a Mox Diamond, which is a 0/0 under
the Song and does not stay to be read, is left out of the 30).

*What it will be.* Titania's Song, Opalescence and the five land animators
make a permanent a creature; Containment Priest, Uphill Battle and Kismet read
"creature" off the entering permanent. Each maker against each reader, with a
permanent the maker reaches: 52 meetings, 14 of them judged by the printed
type before the fix (every Containment Priest one, and Kismet under
Opalescence).

No card behind them: an entry effect that reads the entering permanent's
*colour* or *creature type* (Darkest Hour, Celestial Dawn, Conspiracy and
Dralnu's Crusade are folded and nothing in the pool asks), and a static that
makes a permanent a *land* (Worms of the Earth and Land Equilibrium read
"land", and nothing makes one).
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.enter_tapped_statics import ENTER_TAPPED_STATIC_KIND
from engine.faces import compilation_units
from engine.land_animation import LAND_ANIMATION_KIND
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


@pytest.fixture(scope="module")
def _by_name():
    return {card.name: card for card in load_catalog()}


def _new_game(by_name):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 12)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game


def _put(game, by_name, name, seat=0):
    """Onto the battlefield without being cast, and settled."""
    permanent = Permanent(card=by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _nosick(permanent)
    game._recompute_continuous_effects()
    return permanent


def _cast(game, by_name, name, seat=0, **kwargs) -> bool:
    game.players[seat].hand.append(by_name[name])
    game.active_player_index = seat
    result = game.cast_from_hand(seat, name, **kwargs)
    if not result.supported:
        return False
    resolve_stack(game)
    game._recompute_continuous_effects()
    return True


def _find(game, name):
    return next((p for p in game.all_permanents() if p.card.name == name), None)


# ---------------------------------------------------------------------------
# What it will have
# ---------------------------------------------------------------------------

#: Metadata an entry writes for every permanent, whatever it prints.
_EVERY_ENTRY = None


def _entry_state(game, permanent):
    """What entering did to *permanent* beyond arriving: tapped, counters, a
    copy, a choice — everything but the stamps every entry leaves."""
    if permanent is None or not game.is_on_battlefield(permanent):
        return ("did not enter",)
    return (
        permanent.tapped,
        tuple(sorted(
            (key, value) for key, value in permanent.metadata.items()
            if key.endswith("counters") and value
        )),
        permanent.copied_from,
        tuple(sorted(
            key for key in permanent.metadata
            if key.startswith("chosen") or key in ("body_options", "entry_choices")
        )),
        tuple(sorted(choice.kind for choice in game.pending_choices)),
    )


_PLAIN_ENTRY = (False, (), None, (), ())


def _enters_with_something(by_name, remover, wanted):
    """Every pool card *wanted* admits whose entry, with nothing else on the
    board, is not a vanilla one — paired with how it enters once *remover* is
    out."""
    examined = 0
    as_printed = []
    for card in sorted(compilation_units(by_name.values()), key=lambda card: card.name):
        if not wanted(card) or "enter" not in (card.oracle_text or "").lower():
            continue
        if not compile_card_oracle(card).supported:
            continue
        game = _new_game(by_name)
        # Something to copy, to choose and to sacrifice, so an entry that asks
        # for one is not vanilla for want of it.
        _put(game, by_name, "Grizzly Bears")
        _put(game, by_name, "Forest")
        if not _cast(game, by_name, card.name, x_value=2):
            continue
        if _entry_state(game, _find(game, card.name)) == _PLAIN_ENTRY:
            continue
        game = _new_game(by_name)
        _put(game, by_name, "Grizzly Bears")
        _put(game, by_name, "Forest")
        _put(game, by_name, remover)
        if not _cast(game, by_name, card.name, x_value=2):
            continue
        examined += 1
        state = _entry_state(game, _find(game, card.name))
        if state != _PLAIN_ENTRY:
            as_printed.append((card.name, state))
    return examined, as_printed


def _is_creature_card(card) -> bool:
    return "creature" in card.type_line.lower().split("—")[0]


def _is_noncreature_artifact_card(card) -> bool:
    types = card.type_line.lower().split("—")[0]
    # (Mana value 0 is a 0/0 under the Song and does not stay to be read.)
    return (
        "artifact" in types and "creature" not in types and "land" not in types
        and card.cmc > 0
    )


@pytest.mark.cr("614.12", "613.1f")
def test_a_creature_entering_under_humility_enters_with_nothing_it_prints(_by_name):
    examined, as_printed = _enters_with_something(_by_name, "Humility", _is_creature_card)

    assert examined >= 110, f"only {examined} creatures with an entry of their own"
    assert as_printed == [], (
        f"entered as printed under Humility ({len(as_printed)}): {as_printed[:12]}"
    )


@pytest.mark.cr("614.12", "613.1f")
def test_an_artifact_entering_under_titanias_song_enters_with_nothing_it_prints(
    _by_name,
):
    examined, as_printed = _enters_with_something(
        _by_name, "Titania's Song", _is_noncreature_artifact_card
    )

    assert examined >= 25, f"only {examined} artifacts with an entry of their own"
    assert as_printed == [], (
        f"entered as printed under Titania's Song ({len(as_printed)}): {as_printed[:12]}"
    )


@pytest.mark.cr("614.12")
def test_the_census_names_an_entry_judged_by_the_printed_card(_by_name, monkeypatch):
    """Backwards: no fold, which is the entry as it was — the board's statics
    asked only after the permanent had arrived."""
    monkeypatch.setattr(
        Game, "fold_board_statics_onto_entering",
        lambda self, permanent, controller_index: False,
    )
    examined, as_printed = _enters_with_something(_by_name, "Humility", _is_creature_card)

    named = {name for name, _state in as_printed}
    assert {"Spike Feeder", "Clone", "Clockwork Beast"} <= named
    assert len(as_printed) >= 60 and examined >= 110

    _examined, as_printed = _enters_with_something(
        _by_name, "Titania's Song", _is_noncreature_artifact_card
    )
    assert {"Serrated Arrows", "Black Vise", "Time Vault"} <= {
        name for name, _state in as_printed
    }

    _examined, wrong = _meetings_judged_as_printed(_by_name)
    assert ("Living Lands", "Containment Priest", "Forest") in wrong
    assert ("Opalescence", "Kismet", "Crusade") in wrong
    assert len(wrong) >= 12


# ---------------------------------------------------------------------------
# What it will be
# ---------------------------------------------------------------------------

#: A permanent each maker reaches, to enter under it.
_ENTERING = ("Forest", "Swamp", "Island", "Rod of Ruin", "Crusade")

_EXILES_UNCAST_CREATURES = "Containment Priest"


def _makers(by_name):
    """Every pool card that makes other permanents creatures (CR 613.1d)."""
    found = ["Titania's Song", "Opalescence"]
    found.extend(sorted(
        card.name for card in compilation_units(by_name.values())
        if any(
            instr.kind == LAND_ANIMATION_KIND
            for instr in compile_card_oracle(card).instructions
        )
    ))
    return found


def _tappers(by_name):
    """Every pool card saying how somebody else's permanents enter tapped."""
    return sorted(
        card.name for card in compilation_units(by_name.values())
        if any(
            instr.kind == ENTER_TAPPED_STATIC_KIND
            for instr in compile_card_oracle(card).instructions
        )
    )


def _meetings_judged_as_printed(by_name):
    """Each maker against each reader of "creature", with each permanent the
    maker turns into one. ``(examined, wrong)``.

    The expectation is the engine's own answer asked *afterwards*: an entry
    must have been judged by what the permanent turned out to be.
    """
    examined = 0
    wrong = []
    for maker in _makers(by_name):
        for entering in _ENTERING:
            # Does the maker reach it? Settled, with no reader out.
            game = _new_game(by_name)
            _put(game, by_name, maker)
            settled = _put(game, by_name, entering)
            printed_creature = "creature" in by_name[entering].type_line.lower()
            if not settled.is_creature or printed_creature:
                continue

            # Containment Priest: a creature that was not cast is exiled.
            game = _new_game(by_name)
            _put(game, by_name, maker)
            _put(game, by_name, _EXILES_UNCAST_CREATURES, seat=1)
            permanent = Permanent(card=by_name[entering])
            game._put_permanent_onto_battlefield(0, permanent, None)
            examined += 1
            if game.is_on_battlefield(permanent) or (
                [card.name for card in game.players[0].exile] != [entering]
            ):
                wrong.append((maker, _EXILES_UNCAST_CREATURES, entering))

            # "…enter tapped": tapped exactly when the static's own filter
            # answers yes for the permanent once it is there.
            for tapper in _tappers(by_name):
                game = _new_game(by_name)
                _put(game, by_name, maker)
                _put(game, by_name, tapper, seat=1)
                permanent = Permanent(card=by_name[entering])
                game._put_permanent_onto_battlefield(0, permanent, None)
                game._recompute_continuous_effects()
                if not game.is_on_battlefield(permanent):
                    continue
                examined += 1
                if permanent.tapped != game._enters_tapped_by_a_static(permanent):
                    wrong.append((maker, tapper, entering))
    return examined, wrong


@pytest.mark.cr("614.12", "613.1d")
def test_an_entry_is_judged_by_the_type_the_board_will_give_it(_by_name):
    examined, wrong = _meetings_judged_as_printed(_by_name)

    assert examined >= 40, f"only {examined} meetings examined"
    assert wrong == [], f"judged by the printed type ({len(wrong)}): {wrong[:12]}"


# --- the cards, one board each -------------------------------------------


@pytest.mark.cr("614.12")
def test_spike_feeder_enters_under_humility_with_no_counters_and_lives(_by_name):
    """A 0/0 that "enters with two +1/+1 counters": under Humility it has no
    such ability as it would exist on the battlefield, so it enters with none
    — and is a 1/1, because Humility also says so (CR 613.4b)."""
    game = _new_game(_by_name)
    _put(game, _by_name, "Humility")
    assert _cast(game, _by_name, "Spike Feeder")
    feeder = _find(game, "Spike Feeder")
    assert feeder is not None and game.is_on_battlefield(feeder)
    assert int(feeder.metadata.get("plus_counters", 0)) == 0
    assert (feeder.effective_power, feeder.effective_toughness) == (1, 1)

    # With no Humility it is the card as printed.
    game = _new_game(_by_name)
    assert _cast(game, _by_name, "Spike Feeder")
    feeder = _find(game, "Spike Feeder")
    assert int(feeder.metadata.get("plus_counters", 0)) == 2
    assert (feeder.effective_power, feeder.effective_toughness) == (2, 2)


@pytest.mark.cr("614.12", "614.12a")
def test_a_clone_entering_under_humility_copies_nothing(_by_name):
    """"You may have this creature enter as a copy of …" is the Clone's own
    replacement effect, and under Humility the Clone would have no such
    ability on the battlefield."""
    game = _new_game(_by_name)
    _put(game, _by_name, "Serra Angel")
    _put(game, _by_name, "Humility")
    assert _cast(game, _by_name, "Clone")
    clone = _find(game, "Clone")
    assert clone is not None and clone.copied_from is None
    assert (clone.effective_power, clone.effective_toughness) == (1, 1)
    assert game.pending_choices == []

    game = _new_game(_by_name)
    _put(game, _by_name, "Serra Angel")
    assert _cast(game, _by_name, "Clone")
    assert _find(game, "Clone").copied_from == "Serra Angel"


@pytest.mark.cr("614.12")
def test_frankensteins_monster_enters_under_humility_with_an_empty_graveyard(_by_name):
    """"As this creature enters, exile X creature cards from your graveyard.
    If you can't, put this creature into its owner's graveyard instead." Not
    under Humility, where it prints nothing: the reader of that toll asked the
    printed card."""
    game = _new_game(_by_name)
    _put(game, _by_name, "Humility")
    assert _cast(game, _by_name, "Frankenstein's Monster", x_value=2)
    monster = _find(game, "Frankenstein's Monster")
    assert monster is not None and game.is_on_battlefield(monster)
    assert game.players[0].graveyard == []
    assert (monster.effective_power, monster.effective_toughness) == (1, 1)

    game = _new_game(_by_name)
    assert _cast(game, _by_name, "Frankenstein's Monster", x_value=2)
    assert _find(game, "Frankenstein's Monster") is None
    assert [card.name for card in game.players[0].graveyard] == ["Frankenstein's Monster"]


@pytest.mark.cr("614.12")
def test_serrated_arrows_enters_under_titanias_song_with_no_arrowheads(_by_name):
    game = _new_game(_by_name)
    _put(game, _by_name, "Titania's Song")
    assert _cast(game, _by_name, "Serrated Arrows")
    arrows = _find(game, "Serrated Arrows")
    assert int(arrows.metadata.get("arrowhead_counters", 0)) == 0
    assert arrows.is_creature
    assert (arrows.effective_power, arrows.effective_toughness) == (4, 4)


@pytest.mark.cr("614.12")
def test_containment_priest_exiles_a_forest_living_lands_will_animate(_by_name):
    """A land that was not cast and *will be* a creature. Played from the hand
    is the same thing: a land play is not a cast (CR 305.1)."""
    game = _new_game(_by_name)
    _put(game, _by_name, "Living Lands")
    _put(game, _by_name, "Containment Priest", seat=1)
    game.players[0].hand.append(_by_name["Forest"])
    game.cast_from_hand(0, "Forest")
    resolve_stack(game)
    assert _find(game, "Forest") is None
    assert [card.name for card in game.players[0].exile] == ["Forest"]
    assert any("exiled instead of entering" in line for line in game.log)

    # An Island is not a Forest, and is not a creature there.
    game = _new_game(_by_name)
    _put(game, _by_name, "Living Lands")
    _put(game, _by_name, "Containment Priest", seat=1)
    island = Permanent(card=_by_name["Island"])
    game._put_permanent_onto_battlefield(0, island, None)
    assert game.is_on_battlefield(island) and game.players[0].exile == []


@pytest.mark.cr("614.12")
def test_an_entry_that_is_replaced_leaves_nothing_of_itself_on_the_board(_by_name):
    """The fold asks the board about a permanent that may then never arrive —
    a Titania's Song exiled by a Containment Priest under an Opalescence. What
    it wrote on the other permanents is rebuilt, and the Song does not linger
    as though it had left."""
    game = _new_game(_by_name)
    rod = _put(game, _by_name, "Rod of Ruin")
    _put(game, _by_name, "Opalescence")
    _put(game, _by_name, "Containment Priest", seat=1)
    song = Permanent(card=_by_name["Titania's Song"])
    game._put_permanent_onto_battlefield(0, song, None)

    assert not game.is_on_battlefield(song)
    assert [card.name for card in game.players[0].exile] == ["Titania's Song"]
    assert not rod.is_creature
    assert "deals 1 damage" in rod.effective_card.oracle_text
    assert game.lingering_global_statics == []
    game._recompute_continuous_effects()
    assert not rod.is_creature


@pytest.mark.cr("614.12")
def test_kismet_taps_an_enchantment_opalescence_will_make_a_creature(_by_name):
    game = _new_game(_by_name)
    _put(game, _by_name, "Opalescence")
    _put(game, _by_name, "Kismet", seat=1)
    assert _cast(game, _by_name, "Crusade")
    crusade = _find(game, "Crusade")
    assert crusade.is_creature and crusade.tapped

    # No Opalescence: an enchantment is none of Kismet's three nouns.
    game = _new_game(_by_name)
    _put(game, _by_name, "Kismet", seat=1)
    assert _cast(game, _by_name, "Crusade")
    assert not _find(game, "Crusade").tapped


# --- readers of the printed card (the same shape, on the battlefield) -----


def _dies_having_been_damaged_by(game, by_name, killer):
    victim = _put(game, by_name, "Grizzly Bears", seat=1)
    victim.metadata["damaged_by_sources_this_turn"] = [killer]
    game.players[0].hand.append(by_name["Terror"])
    result = game.cast_from_hand(0, "Terror", target_permanent_ids=[victim.permanent_id])
    assert result.supported, result.details
    resolve_stack(game)
    assert not game.is_on_battlefield(victim)


@pytest.mark.cr("613.1f", "707.2")
def test_the_death_observer_reads_what_the_observer_says_now(_by_name):
    """"Whenever a creature dealt damage by this creature this turn dies, put
    a +1/+1 counter on this creature." The scan compiled the observer's
    printed card: a Sengir Vampire under Humility took its counter for an
    ability it had lost, and a Clone of one — which has the ability — never
    did."""
    game = _new_game(_by_name)
    vampire = _put(game, _by_name, "Sengir Vampire")
    _dies_having_been_damaged_by(game, _by_name, vampire)
    assert int(vampire.metadata.get("plus_counters", 0)) == 1

    game = _new_game(_by_name)
    vampire = _put(game, _by_name, "Sengir Vampire")
    _put(game, _by_name, "Humility")
    _dies_having_been_damaged_by(game, _by_name, vampire)
    assert int(vampire.metadata.get("plus_counters", 0)) == 0

    game = _new_game(_by_name)
    _put(game, _by_name, "Sengir Vampire")
    assert _cast(game, _by_name, "Clone")
    clone = _find(game, "Clone")
    assert clone.copied_from == "Sengir Vampire"
    _dies_having_been_damaged_by(game, _by_name, clone)
    assert int(clone.metadata.get("plus_counters", 0)) == 1


@pytest.mark.cr("707.2", "305.6")
def test_a_clone_of_an_animated_forest_is_a_land_and_taps_for_mana(_by_name):
    """Living Lands makes a Forest a creature, and a Clone may copy it: the
    Clone is then a Forest (the copiable values are the land's). The tap seam
    and the payment planner's list each asked the Clone's *printed* type and
    found a creature, so it could not be tapped for mana at all."""
    from engine.board_payment import board_can_pay
    from engine.mana_payment import untapped_mana_lands

    game = _new_game(_by_name)
    _put(game, _by_name, "Living Lands")
    forest = _put(game, _by_name, "Forest")
    game.players[0].hand.append(_by_name["Clone"])
    result = game.cast_from_hand(0, "Clone", target_permanent_ids=[forest.permanent_id])
    assert result.supported, result.details
    resolve_stack(game)
    clone = _find(game, "Clone")
    _nosick(clone)
    game._recompute_continuous_effects()
    assert clone.copied_from == "Forest" and clone.has_type("forest")
    assert clone.is_creature

    forest.tapped = True
    game.enforce_mana_costs = True
    assert game.land_mana_tap_refusal(clone) is None
    assert [p.card.name for p in untapped_mana_lands(game.controlled_by(0))] == ["Clone"]
    assert board_can_pay(game, 0, {"G": 1})
    assert game.tap_land_for_mana(0, "Clone", "G", permanent_id=clone.permanent_id)
    assert game.players[0].mana_pool.get("G", 0) == 1 and clone.tapped


@pytest.mark.cr("202.3", "707.2")
def test_a_copys_mana_value_is_the_copied_objects(_by_name):
    """"…power and toughness each equal to its mana value" (Titania's Song).
    The mana cost is a copiable value, so a Copy Artifact of a Rod of Ruin is
    a 4/4 there — it read the copier's own printed cost and was a 2/2."""
    game = _new_game(_by_name)
    rod = _put(game, _by_name, "Rod of Ruin")
    game.players[0].hand.append(_by_name["Copy Artifact"])
    result = game.cast_from_hand(
        0, "Copy Artifact", target_permanent_ids=[rod.permanent_id]
    )
    assert result.supported, result.details
    resolve_stack(game)
    copy = _find(game, "Copy Artifact")
    assert copy.copied_from == "Rod of Ruin"
    _put(game, _by_name, "Titania's Song")
    assert (copy.effective_power, copy.effective_toughness) == (4, 4)
    assert (rod.effective_power, rod.effective_toughness) == (4, 4)
