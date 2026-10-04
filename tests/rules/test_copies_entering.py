"""CR 707.5 — a permanent that enters as a copy enters *as* the copy.

    707.5. An object that enters the battlefield "as a copy" or "that's a copy"
    of another object becomes a copy as it enters the battlefield. It doesn't
    enter the battlefield, and then become a copy of that permanent. If the text
    that's being copied includes any abilities that replace the
    enters-the-battlefield event (such as "enters with" or "as [this] enters"
    abilities), those abilities will take effect. Also, any
    enters-the-battlefield triggered abilities of the copy will have a chance to
    trigger.

Both halves were missing for every copy in the pool. The entry trigger was read
off the printed card (Clone prints none; a token copy's own card carries nothing
but a name), and the entry replacements were read off the printed card before
Clone's copy was even made — so a Clone of Spike Feeder entered as a 0/0 and
died, and a token copy of anything was never summoning sick.

And a copied entry trigger that **targets** has nobody's announcement behind it:
Clone's cast announced the creature to copy. CR 603.3d chooses the trigger's
target as it goes on the stack, which is what these tests hold it to.

The permanents being copied are placed on the board directly rather than through
the entry seam, so their own entry triggers do not run before the test starts.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(set_pool, *, hand0=(), hand1=(), board0=(), board1=()) -> Game:
    """Two seats with libraries to draw from, seat 0 in its main phase.

    *board0* / *board1* are already on the battlefield when the game starts —
    placed, not entered, so nothing about their arrival runs."""
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(
            name="P0", hand=list(hand0), library=[island] * 10,
            battlefield=[Permanent(card=card) for card in board0],
        ),
        PlayerState(
            name="P1", hand=list(hand1), library=[island] * 10,
            battlefield=[Permanent(card=card) for card in board1],
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _on(game: Game, seat: int, name: str) -> Permanent:
    """The permanent named *name* on *seat*'s battlefield."""
    return next(perm for perm in game.controlled_by(seat) if perm.card.name == name)


def _enter(game: Game, seat: int, card) -> Permanent:
    """An entry nothing cast — the seam every non-cast entry goes through."""
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    return permanent


def _cast_copying(game: Game, copier: str, original: Permanent) -> Permanent:
    """Cast *copier* from seat 0's hand choosing *original* to copy."""
    result = game.cast_from_hand(
        0, copier,
        target_player_index=game.controller_index_of(original),
        target_permanent_index=game.battlefield_index_of(original),
    )
    assert result.supported, result.details
    return _on(game, 0, copier)


# ---------------------------------------------------------------------------
# The copied entry trigger fires (CR 707.5's last sentence, CR 603.6a)
# ---------------------------------------------------------------------------


@pytest.mark.cr("707.5", "603.6a")
def test_707_5_a_clone_of_wall_of_blossoms_draws_its_controller_a_card(set_pool):
    """"When this creature enters, draw a card." The Clone is the Wall as it
    enters, so the Wall's trigger is the Clone's — and it draws for the Clone's
    controller, not for the Wall's."""
    game = _table(
        set_pool, hand0=[set_pool("LEA")["Clone"]],
        board1=[set_pool("STH")["Wall of Blossoms"]],
    )
    libraries = [len(p.library) for p in game.players]

    clone = _cast_copying(game, "Clone", _on(game, 1, "Wall of Blossoms"))
    resolve_stack(game)

    assert clone.effective_card.name == "Wall of Blossoms"
    assert [len(p.library) for p in game.players] == [libraries[0] - 1, libraries[1]]


@pytest.mark.cr("707.5", "603.6a")
def test_707_5_a_creature_entering_uncopied_fires_its_trigger_once(set_pool):
    """Reading the effective card must not double anything: a Wall of Blossoms
    that is not a copy has the one card either way, and draws one card."""
    game = _table(set_pool, hand0=[set_pool("STH")["Wall of Blossoms"]])
    library = len(game.players[0].library)

    game.cast_from_hand(0, "Wall of Blossoms")
    resolve_stack(game)

    assert len(game.players[0].library) == library - 1
    assert game.log.count("Wall of Blossoms drew 1 card") == 1


@pytest.mark.cr("707.5", "603.6a", "111.1")
def test_707_5_dance_of_manys_token_fires_the_copied_trigger_for_the_token_controller(set_pool):
    """Dance of Many's token is a copy of an opponent's Wall of Blossoms, and it
    is Dance of Many's controller's token: that is who draws."""
    game = _table(
        set_pool, hand0=[set_pool("DRK")["Dance of Many"]],
        board1=[set_pool("STH")["Wall of Blossoms"]],
    )
    libraries = [len(p.library) for p in game.players]

    result = game.cast_from_hand(
        0, "Dance of Many", target_player_index=1,
        target_permanent_index=game.battlefield_index_of(_on(game, 1, "Wall of Blossoms")),
    )
    assert result.supported, result.details
    resolve_stack(game)

    tokens = [p for p in game.controlled_by(0) if p.metadata.get("is_token")]
    assert [t.effective_card.name for t in tokens] == ["Wall of Blossoms"]
    assert [len(p.library) for p in game.players] == [libraries[0] - 1, libraries[1]]


@pytest.mark.cr("707.5", "603.6a")
def test_707_5_vesuvan_doppelganger_copying_ravenous_rats_makes_the_opponent_discard(set_pool):
    """"When this creature enters, target opponent discards a card." Copied by
    the Doppelganger, the target is chosen as the trigger goes on the stack
    (CR 603.3d) — and a seat that is not asked takes the opponent, the only
    seat the line allows."""
    game = _table(
        set_pool,
        hand0=[set_pool("LEA")["Vesuvan Doppelganger"]],
        hand1=[set_pool("LEA")["Island"]],
        board1=[set_pool("UDS")["Ravenous Rats"]],
    )

    doppelganger = _cast_copying(game, "Vesuvan Doppelganger", _on(game, 1, "Ravenous Rats"))
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert doppelganger.effective_card.name == "Ravenous Rats"
    assert game.players[1].hand == []
    assert [c.name for c in game.players[1].graveyard] == ["Island"]


@pytest.mark.cr("707.5", "707.9b", "603.6a", "302.6")
def test_707_5_copy_artifact_copying_skyscanner_is_a_summoning_sick_creature_that_draws(set_pool):
    """Skyscanner is an *artifact creature*. Copy Artifact asked the chosen
    permanent's printed primary type, which answers "creature", refused the
    choice, and then found no "artifact" to fall back to — so it entered as a
    plain blue enchantment. It is the Thopter now, an enchantment too
    (CR 707.9b), draws a card on arrival, and cannot attack this turn."""
    game = _table(
        set_pool, hand0=[set_pool("LEA")["Copy Artifact"]],
        board1=[set_pool("M21")["Skyscanner"]],
    )
    library = len(game.players[0].library)

    copy = _cast_copying(game, "Copy Artifact", _on(game, 1, "Skyscanner"))
    resolve_stack(game)

    assert copy.effective_card.name == "Skyscanner"
    assert copy.is_creature and copy.has_type("artifact") and copy.has_type("enchantment")
    assert len(game.players[0].library) == library - 1, "the copy drew nothing"
    assert game._is_summoning_sick(copy)


@pytest.mark.cr("603.6a", "707.5")
def test_603_6a_a_clone_prints_no_trigger_of_its_own(set_pool):
    """"You may have this creature enter as a copy of any creature" is a
    CR 614.1c replacement. Copying a creature with no entry trigger, the Clone
    announces nothing and draws nothing."""
    game = _table(
        set_pool, hand0=[set_pool("LEA")["Clone"]],
        board1=[set_pool("LEA")["Grizzly Bears"]],
    )
    libraries = [len(p.library) for p in game.players]

    clone = _cast_copying(game, "Clone", _on(game, 1, "Grizzly Bears"))
    resolve_stack(game)

    assert clone.effective_card.name == "Grizzly Bears"
    assert [len(p.library) for p in game.players] == libraries
    assert not game.stack and not game.pending_choices


# ---------------------------------------------------------------------------
# A copied trigger that targets chooses its own target (CR 603.3d)
# ---------------------------------------------------------------------------


@pytest.mark.cr("603.3d", "707.5")
def test_603_3d_a_clone_of_man_o_war_asks_for_the_bounce_target(set_pool):
    """Clone's cast announced the Man-o'-War *to copy*. Handed to the copied
    trigger, that announcement would bounce the Man-o'-War itself — a target
    nobody chose. The trigger asks its controller as it goes on the stack, and
    bounces what they name."""
    game = _table(
        set_pool, hand0=[set_pool("LEA")["Clone"]],
        board1=[set_pool("LEA")["Grizzly Bears"], set_pool("VIS")["Man-o'-War"]],
    )
    bears = _on(game, 1, "Grizzly Bears")
    man_o_war = _on(game, 1, "Man-o'-War")
    game.interactive_seats = {0}

    _cast_copying(game, "Clone", man_o_war)

    (owed,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    offered = {t["permanent_id"] for t in owed.data["targets"]}
    assert {bears.permanent_id, man_o_war.permanent_id} <= offered
    assert game.confirm_trigger_target(0, permanent_id=bears.permanent_id)
    resolve_stack(game)

    assert not game.is_on_battlefield(bears)
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert game.is_on_battlefield(man_o_war), "the copied creature was bounced"
    assert "Clone finished resolving" in game.log


@pytest.mark.cr("603.3d")
def test_603_3d_a_returned_nekrataal_asks_for_its_target(set_pool):
    """An entry nothing cast has no cast-time announcement either, and the
    trigger used to resolve against the fallback scan over its *controller's*
    board: a Nekrataal put onto the battlefield destroyed its controller's own
    Savannah Lions. It asks now, and destroys what it is told to."""
    game = _table(
        set_pool,
        board0=[set_pool("LEA")["Savannah Lions"]],
        board1=[set_pool("LEA")["Grizzly Bears"]],
    )
    lions = _on(game, 0, "Savannah Lions")
    bears = _on(game, 1, "Grizzly Bears")
    game.interactive_seats = {0}

    nekrataal = Permanent(card=set_pool("VIS")["Nekrataal"])
    game._put_permanent_onto_battlefield(0, nekrataal, None)
    (owed,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert {t["permanent_id"] for t in owed.data["targets"]} == {
        lions.permanent_id, bears.permanent_id,
    }
    assert game.confirm_trigger_target(0, permanent_id=bears.permanent_id)
    resolve_stack(game)

    assert not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(lions)


@pytest.mark.cr("603.3d")
def test_603_3d_a_seat_that_is_not_asked_aims_a_removal_trigger_at_an_opponent(set_pool):
    """The stated default for a non-interactive seat reads the effect's side,
    as a modal trigger's mode target and an activated ability already do: a
    destroy aims at an opponent's creature, even when the controller's own
    comes first in seat order."""
    game = _table(
        set_pool,
        board0=[set_pool("LEA")["Savannah Lions"]],
        board1=[set_pool("LEA")["Grizzly Bears"]],
    )
    lions = _on(game, 0, "Savannah Lions")
    bears = _on(game, 1, "Grizzly Bears")

    _enter(game, 0, set_pool("VIS")["Nekrataal"])

    assert game.is_on_battlefield(lions)
    assert not game.is_on_battlefield(bears)


@pytest.mark.cr("603.3d")
def test_603_3d_a_cast_that_announced_no_target_chooses_one_as_the_trigger_goes_on_the_stack(set_pool):
    """A scripted cast with no picker in front of it announces nothing, which
    is the same "nobody chose" as an entry nothing cast. Read as an
    announcement, the inline path scanned the *caster's* side: a bare Ravenous
    Rats made its own caster discard. It chooses as it goes on the stack, and
    "target opponent" can only be the opponent."""
    island = set_pool("LEA")["Island"]
    game = _table(
        set_pool, hand0=[set_pool("UDS")["Ravenous Rats"], island], hand1=[island],
    )

    result = game.cast_from_hand(0, "Ravenous Rats")
    assert result.supported, result.details
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert game.players[1].hand == []
    assert [c.name for c in game.players[1].graveyard] == ["Island"]


@pytest.mark.cr("603.3d", "601.2c")
def test_601_2c_an_up_to_one_entry_trigger_with_nothing_to_name_still_resolves(set_pool):
    """"Exchange control of this creature and **up to one** target creature an
    opponent controls. If you don't or can't make an exchange, sacrifice this
    creature." Zero targets is a legal announcement for "up to one", so an
    empty opposing board is not CR 603.3c's "no legal choices" — the trigger
    stays on the stack, resolves, and the Drake is sacrificed. Removed as
    targetless, it would have left its controller a 3/3 flier for {1}{U}."""
    game = _table(set_pool, board0=[set_pool("LEA")["Savannah Lions"]])

    drake = Permanent(card=set_pool("USG")["Gilded Drake"])
    game._put_permanent_onto_battlefield(0, drake, None)
    resolve_stack(game)

    assert not game.is_on_battlefield(drake)
    assert [c.name for c in game.players[0].graveyard] == ["Gilded Drake"]
    assert game.is_on_battlefield(_on(game, 0, "Savannah Lions"))


# ---------------------------------------------------------------------------
# The copied entry replacements apply (CR 707.5's middle sentence, CR 614.12)
# ---------------------------------------------------------------------------


@pytest.mark.cr("707.5", "614.12")
def test_614_12_a_clone_of_spike_feeder_enters_with_its_counters(set_pool):
    """"This creature enters with two +1/+1 counters on it." Clone's copy is
    the replacement that decides which others apply, so it is made first; the
    Clone is a 2/2 Spike Feeder, not a 0/0 in the graveyard."""
    game = _table(set_pool, hand0=[set_pool("LEA")["Clone"]])
    # Entered rather than placed: a Spike Feeder is a 0/0 without its counters.
    spike = _enter(game, 1, set_pool("STH")["Spike Feeder"])

    clone = _cast_copying(game, "Clone", spike)
    resolve_stack(game)
    game.check_state_based_actions()

    assert game.is_on_battlefield(clone)
    assert (clone.effective_power, clone.effective_toughness) == (2, 2)
    assert "Clone" not in [c.name for c in game.players[0].graveyard]


@pytest.mark.cr("707.5", "614.1c")
def test_707_5_a_token_copy_of_leviathan_enters_tapped(set_pool):
    """"Leviathan enters tapped" is copied text that replaces the entry, and a
    token copy's own card carries nothing but a name — so the line has to be
    read off what the token *is*."""
    game = _table(set_pool, board1=[set_pool("DRK")["Leviathan"]])

    token = game.create_token_copy(0, _on(game, 1, "Leviathan"))

    assert token.effective_card.name == "Leviathan"
    assert token.tapped


@pytest.mark.cr("302.6", "707.5")
def test_302_6_a_token_copy_is_summoning_sick(set_pool):
    """The summoning-sickness stamp was keyed on the printed type, and a token
    copy's printed type is "Token": every Dance of Many, Dual Nature and Sublime
    Epiphany token could attack the turn it was made."""
    game = _table(set_pool, board1=[set_pool("LEA")["Grizzly Bears"]])

    token = game.create_token_copy(0, _on(game, 1, "Grizzly Bears"))

    assert token.is_creature
    assert game._is_summoning_sick(token)
