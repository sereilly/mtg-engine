"""The cards behind ``test_bare_announcement_census.py``: what a cast or an
activation that owes a target and **names none** does now.

Each is one way a handler's own scan was not the picker. The announcement is
answered as it is made (``engine/bare_announcements.py``): the first target
the picker offers, in standing order — the opposing seat first — stamped on
the stack object like a named one.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.shields import shields_on
from engine.stack_targets import chosen_targets
from tests.helpers import _nosick, resolve_stack


def _table(catalog_by_name, mine=(), theirs=(), hand=()):
    island = catalog_by_name["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[island] * 8) for seat in range(2)
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
            permanent = Permanent(card=catalog_by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_nosick(permanent))
        rows.append(row)
    game.players[0].hand.extend(catalog_by_name[name] for name in hand)
    return game, rows[0], rows[1]


# ---------------------------------------------------------------------------
# A scan is not the picker
# ---------------------------------------------------------------------------


def test_burning_palm_efreet_takes_flying_from_the_creature_it_burned(catalog_by_name):
    """"{1}{R}{R}: This creature deals 2 damage to target creature **with
    flying** and that creature loses flying until end of turn." Announced
    bare with a flyer on each side of the table — two legal targets, so
    nothing was announced — each half found its own first match: the damage
    scanned for a flyer and the flying-loss took the first creature across
    the table, a Grizzly Bears the ability could never have targeted."""
    game, (_efreet, mine), (bears, air) = _table(
        catalog_by_name,
        ["Burning Palm Efreet", "Air Elemental"], ["Grizzly Bears", "Air Elemental"],
    )

    result = game.activate_permanent_ability(0, "Burning Palm Efreet")
    resolve_stack(game)

    assert result.supported
    assert air.damage_marked == 2 and not game._has_keyword(air, "flying")
    assert bears.damage_marked == 0
    assert mine.damage_marked == 0 and game._has_keyword(mine, "flying")
    assert "Grizzly Bears loses flying" not in " ".join(game.log)
    assert "Air Elemental loses flying until end of turn (Burning Palm Efreet)" in game.log


def test_soul_sculptor_passes_over_the_creature_with_protection(catalog_by_name):
    """"{1}{W}, {T}: Target creature becomes an enchantment and loses all
    abilities…" Soul Sculptor is white and a Black Knight has protection from
    white (CR 702.16b): the picker never offers it, and the handler's scan
    took it for being the first creature on the opposing battlefield."""
    game, _, (knight, bears) = _table(
        catalog_by_name, ["Soul Sculptor"], ["Black Knight", "Grizzly Bears"],
    )

    result = game.activate_permanent_ability(0, "Soul Sculptor")
    resolve_stack(game)

    assert result.supported
    assert knight.has_type("creature") and not knight.has_type("enchantment")
    assert bears.has_type("enchantment")


def test_a_bare_any_target_is_not_a_player_behind_a_shroud(catalog_by_name):
    """"{T}: This creature deals 1 damage to **any target**." The unnamed
    target of an activation was the opposing seat, stamped whatever the picker
    said — so with the opponent behind an Ivory Mask ("You have shroud",
    CR 702.18a) a bare Prodigal Sorcerer pinged a player nobody may target: 83
    activations in the pool did. The default is the picker's first entry in
    standing order, which behind a Mask is that seat's first creature."""
    game, _, (bears, _mask) = _table(
        catalog_by_name, ["Prodigal Sorcerer"], ["Grizzly Bears", "Ivory Mask"],
    )

    result = game.activate_permanent_ability(0, "Prodigal Sorcerer")
    resolve_stack(game)

    assert result.supported
    assert game.players[1].life == 20 and bears.damage_marked == 1

    plain, _, (other,) = _table(catalog_by_name, ["Prodigal Sorcerer"], ["Grizzly Bears"])
    plain.activate_permanent_ability(0, "Prodigal Sorcerer")
    resolve_stack(plain)

    # …and with nothing in the way it is the opposing player, as it always was.
    assert plain.players[1].life == 19 and other.damage_marked == 0


# ---------------------------------------------------------------------------
# One announcement, not one scan per sentence
# ---------------------------------------------------------------------------


def test_vendetta_costs_the_life_of_the_creature_it_destroyed(catalog_by_name):
    """"Destroy target nonblack creature. … You lose life equal to **that
    creature's** toughness." Cast bare, the destroy scanned and found the
    creature, and the sentence behind it had no target to read: the spell
    killed a 2/2 for one mana and no life."""
    game, _, (bears,) = _table(catalog_by_name, [], ["Grizzly Bears"], hand=["Vendetta"])

    result = game.cast_from_hand(0, "Vendetta")
    resolve_stack(game)

    assert result.supported
    assert not game.is_on_battlefield(bears)
    assert game.players[0].life == 18


def test_amber_prison_holds_the_permanent_it_tapped(catalog_by_name):
    """"{4}, {T}: Tap target artifact, creature, or land. That permanent
    doesn't untap … for as long as this artifact remains tapped." Bare, the
    tap landed and the lock recorded nothing — the second sentence resolved
    its "that permanent" against an announcement that named none."""
    game, (prison,), (bears,) = _table(catalog_by_name, ["Amber Prison"], ["Grizzly Bears"])

    result = game.activate_permanent_ability(0, "Amber Prison")
    resolve_stack(game)

    assert result.supported and bears.tapped
    assert prison.metadata.get("untap_lock_while_tapped") == bears.permanent_id


# ---------------------------------------------------------------------------
# The default is on the stack object
# ---------------------------------------------------------------------------


def test_the_default_is_a_target_the_stack_object_carries(catalog_by_name):
    """The announcement is made as the object is announced, so the object has
    a target like one whose caster named it — which is what "becomes the
    target", a response and CR 608.2b all read."""
    game, _, (bears, giant) = _table(
        catalog_by_name, [], ["Grizzly Bears", "Hill Giant"], hand=["Terror"],
    )

    assert game.queue_from_hand(0, "Terror").supported
    item = game.stack[-1]

    assert [(t.kind, t.permanent_id) for t in chosen_targets(game, item)] == [
        ("permanent", bears.permanent_id)
    ]
    assert item.target_player_index == 1


def test_a_creature_named_by_default_becomes_the_target(catalog_by_name):
    """"Whenever a creature becomes the target of a spell or ability, return
    that creature to its owner's hand." (Cowardice.) A bare Giant Growth chose
    its creature at resolution, so nothing ever became the target and the
    spell pumped a creature Cowardice should have sent home first."""
    game, _, (bears,) = _table(
        catalog_by_name, ["Cowardice"], ["Grizzly Bears"], hand=["Giant Growth"],
    )

    assert game.queue_from_hand(0, "Giant Growth").supported
    resolve_stack(game)

    assert not game.is_on_battlefield(bears)
    assert [card.name for card in game.players[1].hand] == ["Grizzly Bears"]
    assert any("every target is illegal (608.2b)" in line for line in game.log)


def test_a_defaulted_target_that_leaves_in_response_is_not_replaced(catalog_by_name):
    """CR 608.2b for the announcement nobody spelled out: the Terror's target
    is the creature it was announced at, and when that creature is gone the
    spell does not resolve. The handler used to look again as it resolved and
    destroy the creature beside it."""
    game, _, (bears, giant) = _table(
        catalog_by_name, [], ["Grizzly Bears", "Hill Giant"], hand=["Terror"],
    )

    assert game.queue_from_hand(0, "Terror").supported
    game.remove_from_battlefield(bears)    # in response
    resolve_stack(game)

    assert game.is_on_battlefield(giant)
    assert "Terror was removed from the stack: every target is illegal (608.2b)" in game.log
    assert [card.name for card in game.players[0].graveyard] == ["Terror"]


def test_a_defaulted_target_is_charged_what_targeting_it_costs(catalog_by_name):
    """"Spells your opponents cast that target this creature cost an
    additional 3 life to cast." (Terror of the Peaks.) CR 601.2c chooses the
    target before CR 601.2f determines the cost, so a target the engine named
    for the caster is taxed like one the caster named — a bare Terror used to
    reach the Dragon at resolution, past the tax."""
    game, _, (peaks,) = _table(
        catalog_by_name, [], ["Terror of the Peaks"], hand=["Terror"],
    )

    result = game.cast_from_hand(0, "Terror")
    resolve_stack(game)

    assert result.supported and not game.is_on_battlefield(peaks)
    assert game.players[0].life == 17
    assert "P0 paid 3 life to cast Terror (Terror of the Peaks)" in game.log


# ---------------------------------------------------------------------------
# Standing order
# ---------------------------------------------------------------------------


def test_the_default_is_looked_for_on_the_opposing_seat_first(catalog_by_name):
    game, (mine,), (theirs,) = _table(
        catalog_by_name, ["Grizzly Bears"], ["Hill Giant"], hand=["Giant Growth"],
    )

    game.cast_from_hand(0, "Giant Growth")
    resolve_stack(game)

    # Where an unnamed target is looked for, not what is good for the caster.
    assert (theirs.effective_power, theirs.effective_toughness) == (6, 6)
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)


def test_a_seat_named_beside_no_object_is_where_the_default_is_looked_for(
    catalog_by_name
):
    game, (mine,), (theirs,) = _table(
        catalog_by_name, ["Grizzly Bears"], ["Hill Giant"], hand=["Giant Growth"],
    )

    game.cast_from_hand(0, "Giant Growth", target_player_index=0)
    resolve_stack(game)

    assert (mine.effective_power, mine.effective_toughness) == (5, 5)
    assert (theirs.effective_power, theirs.effective_toughness) == (3, 3)


def test_with_nothing_legal_on_the_standing_seat_the_default_is_the_next_entry(
    catalog_by_name
):
    """A black creature is no target for Terror, so with only one across the
    table the picker's list is the caster's own Bears — and that is the
    announcement. (It used to be a spell that resolved doing nothing.)"""
    game, (mine,), (knight,) = _table(
        catalog_by_name, ["Grizzly Bears"], ["Black Knight"], hand=["Terror"],
    )

    result = game.cast_from_hand(0, "Terror")
    resolve_stack(game)

    assert result.supported
    assert not game.is_on_battlefield(mine) and game.is_on_battlefield(knight)


# ---------------------------------------------------------------------------
# What is not owed is not supplied
# ---------------------------------------------------------------------------


def test_up_to_one_target_announced_with_none_touches_nobody(catalog_by_name):
    """"+1: Put a +1/+1 counter on **up to one** target creature." Zero is a
    legal announcement (CR 601.2c) and it used to be answered anyway: the
    handler's scan put the counter on the first creature across the table."""
    game, (basri,), (bears,) = _table(catalog_by_name, ["Basri Ket"], ["Grizzly Bears"])
    basri.metadata["loyalty_counters"] = 3

    result = game.activate_permanent_ability(0, "Basri Ket", ability_index=0)
    resolve_stack(game)

    assert result.supported and basri.metadata["loyalty_counters"] == 4
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert not game._has_keyword(bears, "indestructible")


# ---------------------------------------------------------------------------
# An announced X
# ---------------------------------------------------------------------------


def test_the_default_answers_the_x_the_cast_announced(catalog_by_name):
    """"Destroy target artifact **with mana value X**." The picker enumerates
    before X exists; with an X announced the default is the first entry the
    cast gate accepts for that X, not the first artifact on the table."""
    game, _, (thopter, ring) = _table(
        catalog_by_name, [], ["Ornithopter", "Sol Ring"], hand=["Detonate"],
    )

    result = game.cast_from_hand(0, "Detonate", x_value=1)
    resolve_stack(game)

    assert result.supported
    assert game.is_on_battlefield(thopter) and not game.is_on_battlefield(ring)
    assert game.players[1].life == 19


def test_an_x_no_target_answers_is_an_announcement_that_cannot_be_made(catalog_by_name):
    """…and with no artifact of that mana value the cast is refused with
    nothing spent (CR 601.2c). It was accepted, paid for and resolved onto
    nothing."""
    game, _, (thopter, ring) = _table(
        catalog_by_name, [], ["Ornithopter", "Sol Ring"], hand=["Detonate"],
    )

    result = game.cast_from_hand(0, "Detonate", x_value=5)

    assert not result.supported
    assert result.details == "no valid target for Detonate"
    assert [card.name for card in game.players[0].hand] == ["Detonate"]
    assert game.stack == []


# ---------------------------------------------------------------------------
# A target named by id alone
# ---------------------------------------------------------------------------


def test_swords_to_plowshares_named_by_id_exiles_the_creature_it_named(catalog_by_name):
    """An id is a whole announcement (CR 400.7), and the handler behind this
    spell read the *slot* beside it — which a caller naming by id leaves out —
    and then scanned: Swords aimed by id at the second creature exiled the
    first. The slot is re-read off the id as the spell resolves
    (``bare_announcements.resolving_slots``)."""
    game, _, (bears, giant) = _table(
        catalog_by_name, [], ["Grizzly Bears", "Hill Giant"],
        hand=["Swords to Plowshares"],
    )

    result = game.cast_from_hand(
        0, "Swords to Plowshares", target_permanent_ids=[giant.permanent_id],
    )
    resolve_stack(game)

    assert result.supported
    assert game.is_on_battlefield(bears) and not game.is_on_battlefield(giant)
    assert game.players[1].life == 23
    assert [card.name for card in game.players[1].exile] == ["Hill Giant"]


def test_a_slot_recorded_at_announcement_follows_its_permanent(catalog_by_name):
    """…and a slot that was sent is read the same way, so a battlefield that
    renumbered while the spell waited does not hand it a neighbour."""
    game, _, (wall, bears, giant) = _table(
        catalog_by_name, [], ["Wall of Stone", "Grizzly Bears", "Hill Giant"],
        hand=["Swords to Plowshares"],
    )

    assert game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=1, target_permanent_index=1,
    ).supported
    game.remove_from_battlefield(wall)    # in response: every later slot moves down
    resolve_stack(game)

    assert not game.is_on_battlefield(bears) and game.is_on_battlefield(giant)
    assert game.players[1].life == 22


def test_a_shield_announced_bare_is_a_creature_the_picker_offers(catalog_by_name):
    """"{T}: Prevent the next 1 damage that would be dealt to target creature
    this turn." (Oasis.) One default, drawn from one list: the opposing seat's
    first creature the ability may target, never a player."""
    game, (_oasis, mine), (theirs,) = _table(
        catalog_by_name, ["Oasis", "Grizzly Bears"], ["Hill Giant"],
    )

    result = game.activate_permanent_ability(0, "Oasis")
    resolve_stack(game)

    assert result.supported
    assert shields_on(theirs) and not shields_on(mine)
    assert not shields_on(game.players[0]) and not shields_on(game.players[1])


# ---------------------------------------------------------------------------
# A back-reference in a several-role sentence
# ---------------------------------------------------------------------------


def test_glyph_of_delusion_grants_to_the_creature_it_named(set_pool):
    """"Put X glyph counters on target creature that target Wall blocked this
    turn… **The creature** gains "This creature doesn't untap…"" The second
    sentence carries no target of its own, and its handler read slot 0 of the
    announcement — the *Wall*. The resolver declined a Wall on the other
    battlefield and its scan then took the first creature across the table,
    which is the right creature only when the caster happened to name the
    first one. With no scan for an announced object the antecedent is said
    where the sentence is run (``control_flow._antecedent_scoped``): the
    creature the first sentence acted on."""
    from tests.sets.test_legends_instants import _r34_blocked_board

    game, attackers, walls = _r34_blocked_board(set_pool)

    # Wall B blocked Attacker Two — the *second* creature on its battlefield.
    result = game.cast_from_hand(
        1, "Glyph of Delusion",
        target_permanent_ids=[walls[1].permanent_id, attackers[1].permanent_id],
    )
    resolve_stack(game)

    assert result.supported
    granted = "doesn't untap during your untap step"
    assert granted in attackers[1].effective_card.oracle_text
    assert granted not in attackers[0].effective_card.oracle_text
    assert granted not in walls[1].effective_card.oracle_text


# ---------------------------------------------------------------------------
# An ability activated from a graveyard
# ---------------------------------------------------------------------------


def test_carrionette_activated_bare_from_the_graveyard_names_a_legal_creature(
    catalog_by_name
):
    """"{2}{B}{B}: Exile this card and **target creature** unless that
    creature's controller pays {2}." The graveyard path builds its own stack
    object, so it makes the same announcement: Carrionette is black, a White
    Knight has protection from black, and the default passes over it."""
    game, _, (knight, bears) = _table(
        catalog_by_name, [], ["White Knight", "Grizzly Bears"],
    )
    game.players[0].graveyard.append(catalog_by_name["Carrionette"])

    result = game.activate_from_graveyard(0, "Carrionette")
    assert result.supported
    assert [(t.kind, t.permanent_id) for t in chosen_targets(game, game.stack[-1])] == [
        ("permanent", bears.permanent_id)
    ]
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert game.is_on_battlefield(knight) and not game.is_on_battlefield(bears)
    assert [card.name for card in game.players[1].exile] == ["Grizzly Bears"]
    assert [card.name for card in game.players[0].exile] == ["Carrionette"]
