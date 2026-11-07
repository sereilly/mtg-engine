"""What a seat nobody asks picks, where the pick was the first thing offered.

kg3's census (``test_kg3_choosers_unasked_defaults.py::_DEFAULTS``) left
sixteen prompt kinds whose default took the first card, seat, mode or
permanent offered with nothing weighed. Each is answered now by a reader in
``engine/ai_prompt_picks.py``, and each board here drives a shipped card that
arms its prompt for a seat nobody asks, on a table where the first thing
offered is **not** the best answer — so each one failed on the tree before
(validated backwards: every board below fails on ``313bd09d``, the defaults
taking the first offered).

* ``put_from_hand_choice`` — Metamorphose's opponent put the first eligible
  card (a Forest) onto the battlefield holding a Craw Wurm. The playbook
  said it always declined; it never did once the four-type union parsed
  (SCG W2G5) — it took the first card.
* ``hand_to_library`` — Brainstorm put back the first two cards in hand.
* ``cast_choice`` — Backdraft named the first sorcery cast this turn,
  whatever it dealt and whoever cast it.
* ``player_choice`` — "which opponent" at three seats named the first.
* ``face_down_cast`` — Illusionary Mask put the first creature down.
* ``opponent_mode_choice`` / ``modal_mode_targets`` — Fatal Lore's opponent
  always gave the caster three cards, and the caster's "up to two target
  creatures" were the first two on the board.
* ``library_pile_split`` / ``pile_search`` — Phyrexian Portal's divider
  split in library order, and the searcher took the pile's first card.
* ``linked_exile_return`` — Gustha's Scepter returned the first card exiled.
* ``reflexive_target`` — Tolarian Kraken paid {1} to tap itself.
* ``untap_up_to`` — Snap untapped two Plains and left the Tundra tapped.
* ``word_of_command`` — Word of Command forced the first card in hand.
* ``balance`` — Balance gave up the last slots the round counted.
* ``text_change_vocabulary`` — Mind Bend rewrote the colour word whether or
  not the land type was the rewrite that mattered.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(*, hands=((), ()), libraries=None, seats=2, interactive=()) -> Game:
    libraries = libraries or [()] * seats
    game = Game(players=[
        PlayerState(name=f"P{seat}", hand=list(hands[seat]) if seat < len(hands) else [],
                    library=list(libraries[seat]) if seat < len(libraries) else [])
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game, seat, card, *, tapped=False) -> Permanent:
    permanent = Permanent(card=card, tapped=tapped)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _drain(game) -> None:
    for _ in range(6):
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def _board(game, seat) -> list[str]:
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


# -- put_from_hand_choice: Metamorphose ---------------------------------------


def test_metamorphose_s_opponent_puts_its_dearest_permanent_card(set_pool):
    lea, scg = set_pool("LEA"), set_pool("SCG")
    game = _table(
        hands=([scg["Metamorphose"]], [lea["Forest"], lea["Craw Wurm"], lea["Llanowar Elves"]]),
        libraries=([lea["Island"]] * 8, [lea["Forest"]] * 8),
    )
    victim = _put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(
        0, "Metamorphose", target_permanent_ids=[victim.permanent_id],
    ).supported
    _drain(game)
    assert game.players[1].library[0].name == "Grizzly Bears"
    assert _board(game, 1) == ["Craw Wurm"], game.log[-6:]
    assert sorted(_names(game.players[1].hand)) == ["Forest", "Llanowar Elves"]


# -- hand_to_library: Brainstorm ----------------------------------------------


def test_brainstorm_puts_back_the_cards_it_least_wants(set_pool):
    lea, ice = set_pool("LEA"), set_pool("ICE")
    game = _table(
        hands=([lea["Shivan Dragon"], lea["Llanowar Elves"], ice["Brainstorm"]], ()),
        libraries=([lea["Forest"], lea["Island"], lea["Swamp"]] + [lea["Plains"]] * 6,
                   [lea["Forest"]] * 8),
    )
    for land in ("Mountain", "Mountain", "Forest"):
        _put(game, 0, lea[land])
    assert game.cast_from_hand(0, "Brainstorm").supported
    _drain(game)
    hand = _names(game.players[0].hand)
    assert "Shivan Dragon" in hand and "Llanowar Elves" in hand, game.log[-6:]
    assert len(hand) == 3
    top = _names(game.players[0].library[:2])
    assert all(lea[name].primary_type == "land" for name in top), top


# -- cast_choice: Backdraft ---------------------------------------------------


def _backdraft(set_pool, *, backdraft_seat: int, x_values) -> Game:
    lea, leg = set_pool("LEA"), set_pool("LEG")
    hands = [[lea["Fireball"]] * len(x_values), []]
    hands[backdraft_seat] = hands[backdraft_seat] + [leg["Backdraft"]]
    game = _table(hands=hands, libraries=([lea["Island"]] * 8, [lea["Island"]] * 8))
    for x in x_values:
        assert game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=x).supported
        _drain(game)
    assert game.cast_from_hand(backdraft_seat, "Backdraft").supported
    _drain(game)
    return game


def test_backdraft_names_the_opponent_s_cast_that_dealt_most(set_pool):
    game = _backdraft(set_pool, backdraft_seat=1, x_values=(2, 4))
    # Fireballs of 2 and 4 at P1; P1's Backdraft names the 4: half is 2.
    assert game.players[0].life == 18, game.log[-6:]


def test_backdraft_cast_at_its_own_seat_names_its_smallest_cast(set_pool):
    game = _backdraft(set_pool, backdraft_seat=0, x_values=(4, 2))
    # The only seat that cast a sorcery is the Backdraft's own: it names the
    # Fireball that dealt 2 and takes 1, not the 4 and 2.
    assert game.players[0].life == 19, game.log[-6:]


# -- player_choice: which opponent --------------------------------------------


def test_which_opponent_names_the_opponent_least_ahead(set_pool):
    """"An opponent chooses from among them a creature card, a land card, and
    a noncreature, nonland card." (Guided Passage, three seats.) The caster
    names which opponent: the one least ahead, not the first."""
    lea, apc = set_pool("LEA"), set_pool("APC")
    game = _table(
        hands=([apc["Guided Passage"]], (), ()),
        libraries=([lea["Grizzly Bears"], lea["Forest"], lea["Lightning Bolt"]],
                   [lea["Island"]] * 8, [lea["Island"]] * 8),
        seats=3,
    )
    # P1, the first opponent offered, is the one ahead.
    for _ in range(3):
        _put(game, 1, lea["Craw Wurm"])
    assert game.cast_from_hand(0, "Guided Passage").supported
    _drain(game)
    chose = [line for line in game.log if line.startswith("Guided Passage: chose")]
    assert chose == ["Guided Passage: chose P2"], game.log[-10:]


# -- face_down_cast: Illusionary Mask ----------------------------------------


def test_illusionary_mask_puts_down_the_dearest_creature(set_pool):
    lea = set_pool("LEA")
    game = _table(hands=([lea["Llanowar Elves"], lea["Craw Wurm"]], ()))
    _put(game, 0, lea["Illusionary Mask"])
    game.activate_permanent_ability(0, "Illusionary Mask", permanent_index=0, x_value=6)
    _drain(game)
    hidden = [
        permanent.card.face_down_of.name for permanent in game.controlled_by(0)
        if getattr(permanent.card, "face_down_of", None) is not None
    ]
    assert hidden == ["Craw Wurm"], game.log[-6:]
    assert _names(game.players[0].hand) == ["Llanowar Elves"]


# -- opponent_mode_choice and modal_mode_targets: Fatal Lore ------------------


def _fatal_lore(set_pool, theirs, *, interactive=()) -> Game:
    lea, all_ = set_pool("LEA"), set_pool("ALL")
    game = _table(
        hands=([all_["Fatal Lore"]], ()),
        libraries=([lea["Island"]] * 8, [lea["Forest"]] * 8),
        interactive=interactive,
    )
    for name in theirs:
        _put(game, 1, lea[name])
    assert game.cast_from_hand(0, "Fatal Lore").supported
    return game


def test_fatal_lore_s_opponent_takes_the_cards_when_it_has_nothing_to_lose(set_pool):
    game = _fatal_lore(set_pool, ())
    _drain(game)
    assert len(game.players[0].hand) == 0, game.log[-6:]
    assert len(game.players[1].hand) == 3


def test_fatal_lore_s_opponent_keeps_its_creatures_when_they_are_worth_more(set_pool):
    game = _fatal_lore(set_pool, ("Craw Wurm", "Craw Wurm"))
    _drain(game)
    assert _board(game, 1) == ["Craw Wurm", "Craw Wurm"], game.log[-6:]
    assert len(game.players[0].hand) == 3


def test_fatal_lore_s_caster_destroys_the_two_dearest(set_pool):
    game = _fatal_lore(
        set_pool, ("Llanowar Elves", "Grizzly Bears", "Craw Wurm"), interactive=(1,),
    )
    (owed,) = game.pending_choices_of("opponent_mode_choice", 1)
    assert game.confirm_opponent_mode_choice(1, 1)
    game.interactive_seats = set()
    _drain(game)
    assert _board(game, 1) == ["Llanowar Elves"], game.log[-8:]


# -- library_pile_split and pile_search: Phyrexian Portal ---------------------


_PORTAL_TOP = (
    "Forest", "Shivan Dragon", "Island", "Craw Wurm", "Swamp",
    "Serra Angel", "Mountain", "Air Elemental", "Plains", "Sengir Vampire",
)


def _portal(set_pool, *, interactive) -> Game:
    lea, all_ = set_pool("LEA"), set_pool("ALL")
    game = _table(
        libraries=([lea[name] for name in _PORTAL_TOP] + [lea["Island"]] * 4,
                   [lea["Island"]] * 8),
        interactive=interactive,
    )
    for land in ("Mountain", "Mountain", "Forest"):
        _put(game, 0, lea[land])
    _put(game, 0, all_["Phyrexian Portal"])
    portal = next(p for p in game.controlled_by(0) if p.card.name == "Phyrexian Portal")
    result = game.activate_permanent_ability(
        0, "Phyrexian Portal", target_player_index=1,
        permanent_index=game.battlefield_index_of(portal),
    )
    assert result.supported, result.details
    # Once: the activation stops at its first decision, which stays owed.
    game.resolve_top_of_stack()
    return game


def test_phyrexian_portal_s_divider_puts_the_dearer_half_together(set_pool):
    game = _portal(set_pool, interactive=(0,))
    game.auto_resolve_pending_choices(only_player_index=1)
    (exile_choice,) = game.pending_choices_of("pile_exile_choice", 0)
    first, second = exile_choice.data["_piles"]
    assert sorted(_names(first)) == sorted(
        ["Shivan Dragon", "Craw Wurm", "Serra Angel", "Air Elemental", "Sengir Vampire"]
    ), game.log[-6:]
    assert len(second) == 5


def test_phyrexian_portal_s_searcher_takes_the_best_card_of_its_pile(set_pool):
    game = _portal(set_pool, interactive=(1,))
    (split,) = game.pending_choices_of("library_pile_split", 1)
    cards = _names(split.data["_cards"])
    assert cards == list(_PORTAL_TOP)
    # The Dragon, the Wurm and the Angel in a pile of three: the searcher
    # exiles the smaller and searches the seven left, whose first card is a
    # Forest.
    assert game.confirm_library_pile_split(1, [1, 3, 5])
    game.interactive_seats = set()
    _drain(game)
    hand = _names(game.players[0].hand)
    assert len(hand) == 1 and hand[0] in ("Air Elemental", "Sengir Vampire"), game.log[-6:]


# -- linked_exile_return: Gustha's Scepter -------------------------------------


def test_gusthas_scepter_returns_the_card_it_most_wants(set_pool):
    lea, all_ = set_pool("LEA"), set_pool("ALL")
    game = _table(hands=([lea["Forest"]], ()))
    for land in ("Mountain", "Mountain", "Forest"):
        _put(game, 0, lea[land])
    scepter = _put(game, 0, all_["Gustha's Scepter"])

    def activate(index: int) -> None:
        scepter.tapped = False
        assert game.activate_permanent_ability(
            0, "Gustha's Scepter", permanent_index=game.battlefield_index_of(scepter),
            ability_index=index,
        ).supported
        _drain(game)

    activate(0)
    game.players[0].hand.append(lea["Shivan Dragon"])
    activate(0)
    assert game.players[0].hand == []
    activate(1)
    assert _names(game.players[0].hand) == ["Shivan Dragon"], game.log[-6:]


# -- reflexive_target: Tolarian Kraken ----------------------------------------


def test_tolarian_kraken_taps_the_opponent_s_creature(set_pool):
    lea, m21 = set_pool("LEA"), set_pool("M21")
    game = _table(libraries=([lea["Island"]] * 8, [lea["Island"]] * 8))
    kraken = _put(game, 0, m21["Tolarian Kraken"])
    wurm = _put(game, 1, lea["Craw Wurm"])
    game.players[0].mana_pool["U"] = game.players[0].mana_pool.get("U", 0) + 1
    game._draw_with_replacements(game.players[0], 1)
    game.check_state_based_actions()
    _drain(game)
    assert wurm.tapped and not kraken.tapped, game.log[-8:]


# -- untap_up_to: Snap ---------------------------------------------------------


def test_snap_untaps_the_dual_land_first(set_pool):
    lea, ulg = set_pool("LEA"), set_pool("ULG")
    game = _table(hands=([ulg["Snap"]], ()))
    plains = [_put(game, 0, lea["Plains"], tapped=True) for _ in range(2)]
    tundra = _put(game, 0, lea["Tundra"], tapped=True)
    bears = _put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Snap", target_permanent_ids=[bears.permanent_id]).supported
    _drain(game)
    assert not tundra.tapped, game.log[-6:]
    assert sum(not land.tapped for land in plains) == 1


# -- word_of_command ----------------------------------------------------------


def test_word_of_command_turns_the_target_s_burn_on_itself(set_pool):
    lea = set_pool("LEA")
    game = _table(hands=([lea["Word of Command"]], [lea["Grizzly Bears"], lea["Lightning Bolt"]]))
    assert game.cast_from_hand(0, "Word of Command", target_player_index=1).supported
    _drain(game)
    assert game.players[1].life == 17, game.log[-8:]
    assert _board(game, 1) == []
    assert _names(game.players[1].hand) == ["Grizzly Bears"]


# -- balance ------------------------------------------------------------------


def test_balance_gives_up_what_its_seat_loses_least_by(set_pool):
    lea = set_pool("LEA")
    game = _table(
        hands=([lea["Forest"], lea["Forest"], lea["Shivan Dragon"], lea["Balance"]],
               [lea["Island"]]),
    )
    for seat in (0, 1):
        for land in ("Mountain", "Mountain", "Forest"):
            _put(game, seat, lea[land])
    for name in ("Llanowar Elves", "Grizzly Bears", "Craw Wurm"):
        _put(game, 0, lea[name])
    _put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Balance").supported
    _drain(game)
    assert _board(game, 0) == ["Craw Wurm", "Forest", "Mountain", "Mountain"], game.log[-8:]
    assert _names(game.players[0].hand) == ["Shivan Dragon"]


# -- text_change_vocabulary: Mind Bend ----------------------------------------


def test_mind_bend_rewrites_the_vocabulary_that_matters(set_pool):
    """"All Swamps are 1/1 black creatures that are still lands." (Kormus
    Bell.) Mind Bend with black → green can rewrite the colour word (the
    Swamps stay 1/1 creatures, now green) or the land type (the caster's
    Forests become the 1/1s and its opponent's Swamps stop being creatures).
    Only the second moves the board, and the colour word was the answer."""
    lea, mir = set_pool("LEA"), set_pool("MIR")
    game = _table(hands=([mir["Mind Bend"]], ()))
    bell = _put(game, 1, lea["Kormus Bell"])
    for _ in range(2):
        _put(game, 0, lea["Forest"])
        _put(game, 1, lea["Swamp"])
    game._recompute_continuous_effects()
    assert sum(p.is_creature for p in game.controlled_by(1)) == 2
    assert game.cast_from_hand(
        0, "Mind Bend", target_permanent_ids=[bell.permanent_id],
        old_color="B", new_color="G",
    ).supported
    _drain(game)
    game._recompute_continuous_effects()
    assert "Forests" in bell.effective_card.oracle_text, game.log[-6:]
    assert [p.card.name for p in game.controlled_by(0) if p.is_creature] == ["Forest", "Forest"]


# -- effect_order: a defaulted CR 616.1e prompt --------------------------------


def test_a_defaulted_effect_order_prompt_doubles_before_it_caps(set_pool, catalog_by_name):
    """Lightning Bolt under Furnace of Rath at Forethought Amulet's controller,
    who is asked (CR 616.1e) and then answered for: the answer every seat
    nobody asks takes (doubled to 6, capped at 2), not the first option (the
    cap, then the doubling: 4)."""
    amulet = set_pool("LEG")["Forethought Amulet"]
    furnace = set_pool("TMP")["Furnace of Rath"]
    game = _table(hands=([catalog_by_name["Lightning Bolt"]], ()), interactive=(1,))
    _put(game, 0, furnace)
    _put(game, 1, amulet)
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    game.resolve_top_of_stack()
    (owed,) = game.pending_choices_of("effect_order", 1)
    assert owed.data["_keys"][0] != owed.data["_default_key"]
    game.take_choice_default(owed)
    _drain(game)
    assert game.players[1].life == 18, game.log[-6:]


# -- look_top_pick: Impulse, Sealed Fate --------------------------------------


def test_impulse_keeps_the_card_it_most_wants(set_pool):
    lea, vis = set_pool("LEA"), set_pool("VIS")
    game = _table(
        hands=([vis["Impulse"]], ()),
        libraries=([lea[n] for n in ("Forest", "Island", "Shivan Dragon", "Swamp")]
                   + [lea["Plains"]] * 4, [lea["Island"]] * 8),
    )
    for land in ("Mountain", "Mountain", "Mountain"):
        _put(game, 0, lea[land])
    assert game.cast_from_hand(0, "Impulse").supported
    _drain(game)
    assert _names(game.players[0].hand) == ["Shivan Dragon"], game.log[-6:]


def test_sealed_fate_exiles_the_opponent_s_dearest_card(set_pool):
    lea, mir = set_pool("LEA"), set_pool("MIR")
    game = _table(
        hands=([mir["Sealed Fate"]], ()),
        libraries=([lea["Island"]] * 8,
                   [lea[n] for n in ("Forest", "Craw Wurm", "Island")] + [lea["Forest"]] * 5),
    )
    assert game.cast_from_hand(0, "Sealed Fate", target_player_index=1, x_value=3).supported
    _drain(game)
    assert _names(game.players[1].exile) == ["Craw Wurm"], game.log[-6:]


# -- the cleanup discard (CR 514.1), outside the registry ---------------------


def test_the_cleanup_discard_gives_up_the_cards_least_worth_holding(set_pool):
    """Nine cards in hand at cleanup, four lands on the battlefield and no
    creature: the two discarded are what the hand holds least — a fifth land,
    and a pump with nothing to pump (``ai_scoring._score_tutor_choice``) —
    not the first two cards in hand, the Dragon and the Wurm."""
    lea = set_pool("LEA")
    hand = [lea[n] for n in ("Shivan Dragon", "Craw Wurm", "Serra Angel", "Forest",
                             "Forest", "Llanowar Elves", "Grizzly Bears", "Giant Growth",
                             "Lightning Bolt")]
    game = _table(hands=(hand, ()), libraries=([lea["Island"]] * 8, [lea["Island"]] * 8))
    for land in ("Mountain", "Mountain", "Mountain", "Forest"):
        _put(game, 0, lea[land])
    game.resolve_cleanup_step(0)
    assert sorted(_names(game.players[0].graveyard)) == ["Forest", "Giant Growth"], game.log[-4:]
    assert len(game.players[0].hand) == 7
    assert {"Shivan Dragon", "Craw Wurm"} <= set(_names(game.players[0].hand))
