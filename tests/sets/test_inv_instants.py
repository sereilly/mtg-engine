"""Invasion instants.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G8: odd ones ---
from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import derive_cast_spec as _w1g8_cast_spec
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_instant_duel(set_pool, *, active: int = 0, library: int = 10):
    """Two seats, costs off, each with *library* Islands to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", life=20, library=[island] * library)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = active
    return game


def _w1g8_instant_put(game, set_pool, seat: int, name: str, code: str = "LEA"):
    """*name* on *seat*'s battlefield, free of summoning sickness."""
    permanent = _W1G8Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g8_instant_names(game, seat: int) -> list[str]:
    """The names on *seat*'s battlefield, through the control seam."""
    return sorted(
        permanent.effective_card.name
        for permanent in game.controlled_by(game.players[seat])
    )


def test_winnow_destroys_a_permanent_with_a_namesake_and_draws(set_pool):
    """"Destroy target nonland permanent if another permanent with the same
    name is on the battlefield. / Draw a card." Two Grizzly Bears: the targeted
    one dies, the other stays, and the caster draws."""
    game = _w1g8_instant_duel(set_pool)
    target = _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    twin = _w1g8_instant_put(game, set_pool, 0, "Grizzly Bears")
    game.players[0].hand.append(set_pool("INV")["Winnow"])

    assert game.cast_from_hand(
        0, "Winnow", target_permanent_ids=[target.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert not game.is_on_battlefield(target)
    assert game.is_on_battlefield(twin)
    assert [card.name for card in game.players[0].hand] == ["Island"]


def test_winnow_spares_a_permanent_with_no_namesake_and_still_draws(set_pool):
    """The condition is checked on resolution (CR 608.2c) and guards the
    destroy alone: a lone Grizzly Bears survives, the card is still drawn."""
    game = _w1g8_instant_duel(set_pool)
    target = _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    _w1g8_instant_put(game, set_pool, 1, "Hill Giant")
    game.players[0].hand.append(set_pool("INV")["Winnow"])

    assert game.cast_from_hand(
        0, "Winnow", target_permanent_ids=[target.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert game.is_on_battlefield(target)
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert not any("Destroyed" in line for line in game.log)


def test_winnow_offers_nonland_permanents_and_refuses_a_land(set_pool):
    """"target **nonland** permanent" reaches the picker and the announcement
    gate: two Forests share a name and neither can be named."""
    winnow = set_pool("INV")["Winnow"]
    assert _w1g8_cast_spec(winnow, _w1g8_compile(winnow)) == {
        "kind": "permanent", "filter": {"exclude_types": ["land"]},
    }
    game = _w1g8_instant_duel(set_pool)
    forest = _w1g8_instant_put(game, set_pool, 1, "Forest")
    _w1g8_instant_put(game, set_pool, 1, "Forest")
    game.players[0].hand.append(winnow)

    assert not game.cast_from_hand(
        0, "Winnow", target_permanent_ids=[forest.permanent_id],
    ).supported
    assert game.is_on_battlefield(forest)
    assert game.players[0].hand == [winnow]


def _w1g8_response_table(set_pool):
    """Seat 0 holds Teferi's Response and an Island; seat 1 has a Forest and
    an Icy Manipulator to aim at either land."""
    game = _w1g8_instant_duel(set_pool)
    mine = _w1g8_instant_put(game, set_pool, 0, "Island")
    theirs = _w1g8_instant_put(game, set_pool, 1, "Forest")
    icy = _w1g8_instant_put(game, set_pool, 1, "Icy Manipulator")
    game.players[0].hand.append(set_pool("INV")["Teferi's Response"])
    return game, mine, theirs, icy


def _w1g8_response_offers(game, set_pool) -> list[str]:
    """What Teferi's Response's cast picker shows seat 0 right now."""
    card = set_pool("INV")["Teferi's Response"]
    spec = _w1g8_cast_spec(card, _w1g8_compile(card))
    return [
        entry["name"]
        for entry in game._enumerate_targets(0, card, spec, for_cast=True)
    ]


def test_teferis_response_counters_an_ability_and_destroys_its_source(set_pool):
    """"Counter target spell or ability an opponent controls that targets a
    land you control. If a permanent's ability is countered this way, destroy
    that permanent. / Draw two cards." The Icy Manipulator's ability is
    countered (the Island stays untapped), the Manipulator is destroyed, and
    two cards are drawn."""
    game, mine, _theirs, icy = _w1g8_response_table(set_pool)
    assert game.queue_permanent_ability(
        1, "Icy Manipulator", target_permanent_ids=[mine.permanent_id],
    ).supported
    assert _w1g8_response_offers(game, set_pool) == [
        "Icy Manipulator's activated ability"
    ]

    assert game.cast_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported
    _w1g8_resolve_stack(game)

    assert not mine.tapped
    assert not game.is_on_battlefield(icy)
    assert [card.name for card in game.players[1].graveyard] == ["Icy Manipulator"]
    assert len(game.players[0].hand) == 2


def test_teferis_response_counters_a_spell_and_destroys_nothing(set_pool):
    """The spell half: Stone Rain aimed at the Island is countered and binned,
    and "a permanent's ability" was not what was countered — nothing on either
    battlefield is destroyed."""
    game, mine, theirs, icy = _w1g8_response_table(set_pool)
    game.active_player_index = 1
    game.players[1].hand.append(set_pool("LEA")["Stone Rain"])
    assert game.queue_from_hand(
        1, "Stone Rain", target_permanent_ids=[mine.permanent_id],
    ).supported

    assert game.cast_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported
    _w1g8_resolve_stack(game)

    assert game.is_on_battlefield(mine)
    assert game.is_on_battlefield(theirs) and game.is_on_battlefield(icy)
    assert [card.name for card in game.players[1].graveyard] == ["Stone Rain"]
    assert len(game.players[0].hand) == 2


def test_teferis_response_cannot_name_an_object_aimed_at_another_land(set_pool):
    """"…that targets a land **you control**": an ability aimed at the
    opponent's own Forest is not offered, and naming it is refused at
    announcement (CR 601.2c) — so the spell is not two cards for {1}{U}."""
    game, _mine, theirs, _icy = _w1g8_response_table(set_pool)
    assert game.queue_permanent_ability(
        1, "Icy Manipulator", target_permanent_ids=[theirs.permanent_id],
    ).supported
    assert _w1g8_response_offers(game, set_pool) == []

    assert not game.cast_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported
    assert [card.name for card in game.players[0].hand] == ["Teferi's Response"]
    assert len(game.stack) == 1


def test_teferis_response_cannot_name_its_casters_own_ability(set_pool):
    """"…an **opponent** controls": the caster's own Icy Manipulator aimed at
    the caster's own Island answers the second clause and fails the first."""
    game, mine, _theirs, _icy = _w1g8_response_table(set_pool)
    _w1g8_instant_put(game, set_pool, 0, "Icy Manipulator")
    assert game.queue_permanent_ability(
        0, "Icy Manipulator", target_permanent_ids=[mine.permanent_id],
    ).supported
    assert _w1g8_response_offers(game, set_pool) == []

    assert not game.cast_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported
    assert [card.name for card in game.players[0].hand] == ["Teferi's Response"]


def test_teferis_response_is_uncastable_with_nothing_to_counter(set_pool):
    """A bare cast with an empty stack has no legal target (CR 601.2c) — the
    draw cannot be bought on its own."""
    game, _mine, _theirs, _icy = _w1g8_response_table(set_pool)

    assert not game.cast_from_hand(0, "Teferi's Response").supported
    assert [card.name for card in game.players[0].hand] == ["Teferi's Response"]


def test_teferis_response_does_not_resolve_once_its_target_is_illegal(set_pool):
    """CR 608.2b: the Island leaves in response, so the Stone Rain no longer
    "targets a land you control". Teferi's Response has no legal target left
    and is removed from the stack — no counter, and no cards drawn."""
    game, mine, _theirs, _icy = _w1g8_response_table(set_pool)
    game.active_player_index = 1
    game.players[1].hand.append(set_pool("LEA")["Stone Rain"])
    assert game.queue_from_hand(
        1, "Stone Rain", target_permanent_ids=[mine.permanent_id],
    ).supported
    assert game.queue_from_hand(
        0, "Teferi's Response", target_stack_index=0,
    ).supported

    game.remove_from_battlefield(mine)
    assert game.resolve_top_of_stack()

    assert game.players[0].hand == []
    assert [item.card.name for item in game.stack] == ["Stone Rain"]
    assert any("608.2b" in line for line in game.log)


def _w1g8_dance_table(set_pool, *, in_hand=("Serra Angel",)):
    """Seat 0 in its own combat with Cauldron Dance in hand, Hill Giant and
    Craw Wurm in the graveyard, and *in_hand* beside the spell."""
    game = _w1g8_instant_duel(set_pool)
    game.interactive_seats = set()
    game.start_turn(0)
    pool = set_pool("LEA")
    _w1g8_instant_put(game, set_pool, 0, "Scryb Sprites")
    _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    game.players[0].graveyard.extend([pool["Hill Giant"], pool["Craw Wurm"]])
    game.players[0].hand = [set_pool("INV")["Cauldron Dance"]]
    game.players[0].hand.extend(pool[name] for name in in_hand)
    game._set_phase_and_step("combat", "beginning_of_combat")
    return game


def _w1g8_dance_cast(game, graveyard_slot: int):
    """Cast Cauldron Dance at *graveyard_slot* and settle everything it asks."""
    result = game.cast_from_hand(
        0, "Cauldron Dance", target_permanent_index=graveyard_slot,
    )
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return result


def test_cauldron_dance_is_cast_only_during_combat(set_pool):
    """"Cast this spell only during combat." Refused in a main phase with the
    card still in hand; its picker is the caster's own graveyard."""
    dance = set_pool("INV")["Cauldron Dance"]
    assert _w1g8_cast_spec(dance, _w1g8_compile(dance)) == {
        "kind": "graveyard_creature", "own_graveyard_only": True,
    }
    game = _w1g8_dance_table(set_pool)
    game._set_phase_and_step("precombat_main", "precombat_main")

    assert not game.cast_from_hand(
        0, "Cauldron Dance", target_permanent_index=0,
    ).supported
    assert dance in game.players[0].hand
    assert [card.name for card in game.players[0].graveyard] == [
        "Hill Giant", "Craw Wurm",
    ]


def test_cauldron_dance_returns_one_creature_and_puts_in_another_with_haste(set_pool):
    """Both paragraphs: the targeted Hill Giant comes back from the graveyard,
    the Serra Angel comes in from the hand, and both have haste."""
    game = _w1g8_dance_table(set_pool)

    assert _w1g8_dance_cast(game, 0).supported

    assert _w1g8_instant_names(game, 0) == [
        "Hill Giant", "Scryb Sprites", "Serra Angel",
    ]
    arrived = {
        permanent.card.name: permanent
        for permanent in game.controlled_by(game.players[0])
    }
    assert game._has_keyword(arrived["Hill Giant"], "haste")
    assert game._has_keyword(arrived["Serra Angel"], "haste")
    assert not game._has_keyword(arrived["Scryb Sprites"], "haste")
    assert [card.name for card in game.players[0].graveyard] == [
        "Craw Wurm", "Cauldron Dance",
    ]


def test_cauldron_dance_bounces_the_first_and_sacrifices_the_second_at_end_step(set_pool):
    """"Return it to your hand at the beginning of the next end step." / "Its
    controller sacrifices it at the beginning of the next end step." Each
    pronoun names the creature its own paragraph made: the Hill Giant goes to
    hand, the Serra Angel to the graveyard, and neither bystander is touched."""
    game = _w1g8_dance_table(set_pool)
    _w1g8_dance_cast(game, 0)

    game.resolve_end_step(0)
    _w1g8_resolve_stack(game)

    assert _w1g8_instant_names(game, 0) == ["Scryb Sprites"]
    assert _w1g8_instant_names(game, 1) == ["Grizzly Bears"]
    assert [card.name for card in game.players[0].hand] == ["Hill Giant"]
    assert [card.name for card in game.players[0].graveyard] == [
        "Craw Wurm", "Cauldron Dance", "Serra Angel",
    ]


def test_cauldron_dance_with_an_empty_hand_sacrifices_nothing(set_pool):
    """"You **may** put a creature card from your hand…" With none to put, the
    second paragraph's delayed sacrifice is about no object and arms nothing —
    it must not fall back to the reanimated creature or to a bystander. The
    target here is graveyard slot 1, the number that used to be read as a
    battlefield slot."""
    game = _w1g8_dance_table(set_pool, in_hand=())

    assert _w1g8_dance_cast(game, 1).supported
    assert _w1g8_instant_names(game, 0) == ["Craw Wurm", "Scryb Sprites"]
    assert len(
        [entry for entry in game.delayed_triggers if entry.event == "next_end_step"]
    ) == 1

    game.resolve_end_step(0)
    _w1g8_resolve_stack(game)

    assert _w1g8_instant_names(game, 0) == ["Scryb Sprites"]
    assert _w1g8_instant_names(game, 1) == ["Grizzly Bears"]
    assert [card.name for card in game.players[0].hand] == ["Craw Wurm"]
    assert "Craw Wurm" not in [card.name for card in game.players[0].graveyard]


def test_backlash_taps_a_creature_and_has_it_hit_its_own_controller(set_pool):
    """"Tap target untapped creature. That creature deals damage equal to its
    power to its controller." The Hill Giant is tapped and deals 3 to the seat
    that controls it — and the creature is the source of that damage
    (CR 120.7), not the spell."""
    game = _w1g8_instant_duel(set_pool)
    giant = _w1g8_instant_put(game, set_pool, 1, "Hill Giant")
    game.players[0].hand.append(set_pool("INV")["Backlash"])

    assert game.cast_from_hand(
        0, "Backlash", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert giant.tapped
    assert [player.life for player in game.players] == [20, 17]
    assert "Hill Giant deals 3 damage to P1" in game.log


def test_backlash_aimed_at_its_casters_own_creature_hits_the_caster(set_pool):
    """"**its** controller" is the creature's, whoever cast the spell."""
    game = _w1g8_instant_duel(set_pool)
    wurm = _w1g8_instant_put(game, set_pool, 0, "Craw Wurm")
    game.players[0].hand.append(set_pool("INV")["Backlash"])

    assert game.cast_from_hand(
        0, "Backlash", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert wurm.tapped
    assert [player.life for player in game.players] == [14, 20]


def test_backlash_cannot_target_a_tapped_creature(set_pool):
    """"target **untapped** creature" narrows the picker and the announcement:
    a creature already tapped is not offered and cannot be named."""
    backlash = set_pool("INV")["Backlash"]
    assert _w1g8_cast_spec(backlash, _w1g8_compile(backlash)) == {
        "kind": "creature", "filter": {"untapped_only": True},
    }
    game = _w1g8_instant_duel(set_pool)
    bears = _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    bears.tapped = True
    game.players[0].hand.append(backlash)

    assert not game.cast_from_hand(
        0, "Backlash", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.players[1].life == 20
    assert game.players[0].hand == [backlash]
