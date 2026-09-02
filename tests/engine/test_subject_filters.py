"""One noun phrase, one matcher (engine/subject_filters.py).

``TESTABLE_SUBJECT_FILTER_KEYS`` is a promise: a compiler that finds every key
of a filter payload inside it admits the line, and the dispatcher then applies
the restriction. A key listed there but not actually tested is therefore worse
than a missing key — the card is admitted and its narrowing silently ignored,
which is a trigger firing on more than it prints and a sacrifice eating more
than it should.

So the promise is checked by *behaviour*, one key at a time: for each key, a
permanent that should fail it. Comparing the set against a list of key names is
something a second copy of the list would also pass.
"""

from __future__ import annotations

import dataclasses
import pytest

from engine import Game
from engine.card_loader import load_cards, manifest_set_paths
from engine.keywords import grant_keyword
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.subject_filters import (
    OBJECT_ONLY_FILTER_KEYS,
    TESTABLE_SUBJECT_FILTER_KEYS,
    object_only_filter,
    subject_matches,
    untestable_filter_keys,
)


@pytest.fixture(scope="module")
def pool():
    return {c.name: c for c in load_cards(manifest_set_paths(include_measured=True))}


# (key, a payload using it, the name of a card the payload must reject). Every
# rejection is by the *one* restriction under test: each card matches the bare
# "creature" filter, so a False can only come from the key.
_REJECTIONS: tuple[tuple[str, dict, str], ...] = (
    ("type_filter", {"type_filter": "artifact"}, "Grizzly Bears"),
    ("subtype_filter", {"subtype_filter": "wall"}, "Grizzly Bears"),
    # The conjunction spelling. Grizzly Bears is a Bear and not a Wall, so an
    # OR'd implementation would *accept* it on the first alternative — which is
    # what makes this row a demonstration of AND rather than a second copy of
    # the row above.
    ("subtype_filter_all", {"subtype_filter_all": ["bear", "wall"]}, "Grizzly Bears"),
    # "target **artifact creature**" — one permanent that is both. Grizzly
    # Bears is a creature and not an artifact, so a union would accept it on
    # the "creature" alternative, exactly as with the subtype row above.
    ("type_filter_all", {"type_filter_all": ["artifact", "creature"]}, "Grizzly Bears"),
    ("color_filter", {"color_filter": "W"}, "Grizzly Bears"),
    # "a green **or** white creature" (Abomination). Grizzly Bears is neither
    # blue nor white, so a matcher ignoring the key would admit it — and the
    # positive half, that *either* colour is enough, is demonstrated below,
    # because a matcher reading the list as AND also passes this row.
    ("any_colors", {"any_colors": ["W", "U"]}, "Grizzly Bears"),
    ("exclude_colors", {"exclude_colors": ["G"]}, "Grizzly Bears"),
    ("exclude_types", {"exclude_types": ["creature"]}, "Grizzly Bears"),
    ("exclude_subtypes", {"exclude_subtypes": ["bear"]}, "Grizzly Bears"),
    ("tapped_only", {"tapped_only": True}, "Grizzly Bears"),
    ("mana_value", {"mana_value": {"op": "le", "value": 1}}, "Grizzly Bears"),
    ("power", {"power": {"op": "ge", "value": 4}}, "Grizzly Bears"),
    ("toughness", {"toughness": {"op": "ge", "value": 4}}, "Grizzly Bears"),
    ("with_plus1_counter", {"with_plus1_counter": True}, "Grizzly Bears"),
    ("with_keywords", {"with_keywords": ["flying"]}, "Grizzly Bears"),
    # The negative twin (Moat's "creatures without flying"). Air Elemental
    # prints the keyword, so a matcher that ignored the key — or one that read
    # it as its positive sibling — would let the flyer through.
    ("without_keywords", {"without_keywords": ["flying"]}, "Air Elemental"),
    ("named", {"named": "Hill Giant"}, "Grizzly Bears"),
    # CR 205.4a. Read off the type line, which for a supertype is the whole of
    # what there is — nothing in layers 4-6 computes one.
    ("supertypes", {"supertypes": ["legendary"]}, "Grizzly Bears"),
    # "target **nonsnow** land" (Hallowed Ground). The negative of the row
    # above, off the same type line. The rejected permanent has to *carry* the
    # excluded supertype and still answer this table's creature control, so it
    # is a legendary creature — "nonlegendary" is the same sentence one
    # supertype over from the one Ice Age prints.
    ("exclude_supertypes", {"exclude_supertypes": ["legendary"]}, "Adun Oakenshield"),
    # CR 508.1a: attacking is a state of the permanent itself, stamped at
    # declaration — a bear standing outside combat is not attacking, and a
    # matcher that ignored the key would untap it anyway (Disharmony).
    ("attacking_only", {"attacking_only": True}, "Grizzly Bears"),
    # "a creature that has been dealt damage this turn" (Giant Shark). A record
    # the damage seam stamps; a bear nothing has hit does not carry it, and a
    # matcher ignoring the key would fire the Shark's trigger on every block.
    ("dealt_damage_this_turn", {"dealt_damage_this_turn": True}, "Grizzly Bears"),
    # CR 509.1g: blocking is a state of the permanent itself, stamped when
    # blockers are declared — a bear standing outside combat is not blocking,
    # and a matcher that ignored the key would let Righteousness pump it and
    # Sorrow's Path name it as one of its two blockers.
    ("blocking_only", {"blocking_only": True}, "Grizzly Bears"),
)


@pytest.mark.parametrize("key,payload,card_name", _REJECTIONS, ids=[r[0] for r in _REJECTIONS])
def test_every_promised_key_actually_narrows(pool, key, payload, card_name):
    perm = Permanent(card=pool[card_name])
    game = Game(players=[PlayerState(name="P1", battlefield=[perm]), PlayerState(name="P2")])

    assert subject_matches(game, perm, {"type_filter": "creature"}), (
        "the control: the bare noun phrase must match, or the rejection below "
        "proves nothing about the key"
    )
    assert not subject_matches(game, perm, {"type_filter": "creature", **payload})


def test_untapped_only_rejects_a_tapped_permanent(pool):
    """The other half of a tri-state, and the reason it needed its own key:
    ``tapped`` is None / True / False, only the True half had one, and False is
    falsy — so "an untapped creature" emitted exactly the payload of "a
    creature" and the restriction vanished between the two gates.

    Its own demonstration rather than a row in ``_REJECTIONS`` because the table
    builds an untapped permanent, and the permanent this key rejects is a tapped
    one."""
    perm = Permanent(card=pool["Grizzly Bears"], tapped=True)
    untapped = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm, untapped]), PlayerState(name="P2"),
    ])

    assert subject_matches(game, perm, {"type_filter": "creature"}), (
        "the control: the bare noun phrase must match, or the rejection below "
        "proves nothing about the key"
    )
    assert not subject_matches(game, perm, {"untapped_only": True})
    assert subject_matches(game, untapped, {"untapped_only": True})


def test_nontoken_rejects_a_token(pool):
    """The one key with no card type of its own (CR 111.1), and the restriction
    Lich's sacrifice has always carried."""
    token = Permanent(card=pool["Grizzly Bears"], metadata={"is_token": True})
    game = Game(players=[PlayerState(name="P1", battlefield=[token]), PlayerState(name="P2")])

    assert subject_matches(game, token, {"type_filter": "creature"})
    assert not subject_matches(game, token, {"nontoken": True})


def test_token_only_rejects_a_nontoken(pool):
    """The positive twin of ``nontoken`` (CR 111.1), and the narrowing Caribou
    Range's sacrifice cost carries: a Caribou *token*, not a Caribou."""
    token = Permanent(card=pool["Grizzly Bears"], metadata={"is_token": True})
    printed = Permanent(card=pool["Grizzly Bears"])
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[token, printed]),
            PlayerState(name="P2"),
        ]
    )

    assert subject_matches(game, token, {"token_only": True})
    assert not subject_matches(game, printed, {"token_only": True})


def test_chosen_color_is_read_off_the_ability_s_source(pool):
    """"nontoken permanents **of the chosen color**" (Psychic Allergy).

    A relative key like ``exclude_self``: the colour is not in the sentence and
    not on the permanent being tested — it was chosen as the *source* entered
    (CR 614.1c) and lives in that permanent's metadata. So the key needs the
    source, and without one it must refuse every permanent rather than admit
    every permanent, which is the direction that cannot widen an effect.
    """
    bears = Permanent(card=pool["Grizzly Bears"])          # green
    knight = Permanent(card=pool["White Knight"])          # white
    allergy = Permanent(card=pool["Grizzly Bears"], metadata={"chosen_color": "G"})
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[bears, knight, allergy]),
            PlayerState(name="P2"),
        ]
    )

    assert subject_matches(game, bears, {"type_filter": "creature"}), (
        "the control: the bare noun phrase must match, or the rows below "
        "prove nothing about the key"
    )
    assert subject_matches(game, bears, {"chosen_color": True}, source=allergy)
    assert not subject_matches(game, knight, {"chosen_color": True}, source=allergy)
    # No source to read the choice off: the narrowing is unanswerable, so
    # nothing matches rather than everything.
    assert not subject_matches(game, bears, {"chosen_color": True})


def test_chosen_creature_type_is_read_off_the_ability_s_source(pool):
    """"Creatures **of the chosen type**" (An-Zerrin Ruins).

    The sibling of the colour above, one characteristic over and relative for
    the same reason: the type is not in the sentence and not on the permanent
    being tested -- it was chosen as the *source* entered (CR 614.1c,
    CR 205.3m) and lives in that permanent's metadata.

    Without a source it must refuse every permanent rather than admit every
    permanent, which for the card that prints it is the difference between
    holding one tribe down and holding the whole board down.
    """
    bears = Permanent(card=pool["Grizzly Bears"])          # a Bear
    knight = Permanent(card=pool["White Knight"])          # a Human Knight
    ruins = Permanent(
        card=pool["Grizzly Bears"], metadata={"chosen_creature_type": "bear"}
    )
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[bears, knight, ruins]),
            PlayerState(name="P2"),
        ]
    )

    assert subject_matches(game, bears, {"type_filter": "creature"}), (
        "the control: the bare noun phrase must match, or the rows below "
        "prove nothing about the key"
    )
    assert subject_matches(game, bears, {"chosen_creature_type": True}, source=ruins)
    assert not subject_matches(
        game, knight, {"chosen_creature_type": True}, source=ruins
    )
    assert not subject_matches(game, bears, {"chosen_creature_type": True})


def test_the_combat_records_are_read_off_the_permanent(pool):
    """"…creatures **that didn't attack this turn**, except for creatures
    **that couldn't attack**." (Season of the Witch.)

    Two questions about one combat, and neither can be re-derived at the sweep:
    by the end step a creature may have untapped or had its restriction end. So
    both are per-turn records the permanent carries, and both are answerable
    from the object alone — which is what puts them in this set rather than
    among the relative keys below.
    """
    attacked = Permanent(
        card=pool["Grizzly Bears"],
        metadata={"attacked_this_turn": True, "could_attack_this_turn": True},
    )
    idle = Permanent(
        card=pool["Grizzly Bears"], metadata={"could_attack_this_turn": True}
    )
    grounded = Permanent(card=pool["Grizzly Bears"])
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[attacked, idle, grounded]),
            PlayerState(name="P2"),
        ]
    )

    assert subject_matches(game, idle, {"type_filter": "creature"}), (
        "the control: the bare noun phrase must match, or the rows below "
        "prove nothing about the keys"
    )
    assert subject_matches(game, attacked, {"attacked_this_turn": True})
    assert not subject_matches(game, idle, {"attacked_this_turn": True})
    assert subject_matches(game, idle, {"not_attacked_this_turn": True})
    assert not subject_matches(game, attacked, {"not_attacked_this_turn": True})
    # The exemption: a creature that never could have attacked is out of the
    # set however untapped and idle it is.
    assert subject_matches(game, idle, {"could_attack_this_turn": True})
    assert not subject_matches(game, grounded, {"could_attack_this_turn": True})


def test_ownership_is_asked_separately_from_control(pool):
    """"target permanent you both **own** and control" (Obelisk of Undoing).

    Ownership (CR 108.3) never changes; control (CR 613 layer 2) does, and a
    card printed with both is printed for the case where they differ. Reading
    one as the other is how a stolen permanent gets returned to the thief's
    hand — so the two are separate keys, and the demonstration is a permanent
    whose control has moved.
    """
    from engine.control import change_control

    stolen = Permanent(card=pool["Grizzly Bears"])
    thief = Permanent(card=pool["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[thief])
    p2 = PlayerState(name="P2", battlefield=[stolen])
    game = Game(players=[p1, p2])
    # Stolen the way the engine steals: a layer-2 contribution, which leaves
    # `base_controller` — and so ownership — pointing at the seat it entered
    # under. Setting the field by hand would be a fixture asserting its own
    # premise.
    game._put_permanent_onto_battlefield(1, stolen, None)
    change_control(stolen, 0, source=thief)
    game._sync_control()

    assert subject_matches(game, stolen, {"controller": "you"}, observer=0)
    assert not subject_matches(game, stolen, {"owner": "you"}, observer=0)
    assert not subject_matches(
        game, stolen, {"controller": "you", "owner": "you"}, observer=0
    )


def test_the_relative_keys_refuse_without_the_context_they_need(pool):
    """"You control" and "another" are relative, which is why they are outside
    ``OBJECT_ONLY_FILTER_KEYS``. A caller with no observer and no source must
    get a refusal rather than a match — a match is the narrowing being dropped.
    """
    perm = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[PlayerState(name="P1", battlefield=[perm]), PlayerState(name="P2")])

    assert not subject_matches(game, perm, {"controller": "you"})
    assert subject_matches(game, perm, {"controller": "you"}, observer=0)
    assert not subject_matches(game, perm, {"controller": "you"}, observer=1)

    assert subject_matches(game, perm, {"exclude_self": True})
    assert not subject_matches(game, perm, {"exclude_self": True}, source=perm)


def test_a_keyword_narrowing_is_asked_of_layer_six(pool):
    """The reason the matcher needs the game at all. A creature *granted*
    defender is a creature with defender (CR 613.1f), so it answers a
    defender-narrowed sacrifice exactly as a printed one does — and reading
    ``card.keywords`` instead would have said no."""
    perm = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[PlayerState(name="P1", battlefield=[perm]), PlayerState(name="P2")])
    described = {"type_filter": "creature", "with_keywords": ["defender"]}

    assert not subject_matches(game, perm, described)
    grant_keyword(perm, "defender", duration="end_of_turn")
    assert subject_matches(game, perm, described)
    assert "defender" not in (perm.card.keywords or ()), (
        "the printed card still has no defender — a matcher reading it would "
        "have answered no"
    )


def test_a_without_keyword_narrowing_is_asked_of_layer_six_too(pool):
    """The negative twin, and the same layer: a creature *granted* flying is a
    creature with flying (CR 613.1f), so it escapes Moat's "creatures without
    flying" the moment the grant lands — a matcher reading the printed keyword
    list would have kept it grounded."""
    perm = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[PlayerState(name="P1", battlefield=[perm]), PlayerState(name="P2")])
    described = {"type_filter": "creature", "without_keywords": ["flying"]}

    assert subject_matches(game, perm, described)
    grant_keyword(perm, "flying", duration="end_of_turn")
    assert not subject_matches(game, perm, described)


def test_every_sacrifice_filter_in_the_pool_is_one_the_prompt_can_test():
    """The ratchet on both halves of this round. A sacrifice's victim is named
    by a printed noun phrase on three sides — the activation cost, the cast
    additional cost, and the effect — and each hands its payload to a path with
    no observer and no source. A key outside ``OBJECT_ONLY_FILTER_KEYS``
    reaching one of them would be a restriction quietly not applied.
    """
    escaped: list[str] = []
    for card in load_cards(manifest_set_paths(include_measured=True)):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        payloads = [
            (f"{card.name} cost", ability.cost.sacrifice_filter)
            for ability in program.activated_abilities
            if ability.cost.sacrifice_filter is not None
        ]
        payloads += [
            (f"{card.name} effect", instruction.payload.get("filter"))
            for instruction in program.instructions
            if instruction.kind == "sacrifice_matching_permanent"
        ]
        for label, described in payloads:
            # `exclude_self` is the one key both paths carry out themselves, by
            # identity, from an argument of their own.
            extra = set(described or {}) - OBJECT_ONLY_FILTER_KEYS - {"exclude_self"}
            if extra:
                escaped.append(f"{label}: {sorted(extra)}")
    assert not escaped, "sacrifice filters nothing tests: " + "; ".join(escaped)


# The three keys the table above cannot express as "one payload, one card":
# tokens have no card of their own, and the last two need a context argument
# rather than a different permanent. Each names the test that exercises it, so
# a key can only be listed here by someone who wrote one.
_COVERED_ELSEWHERE = {
    "original_expansion":
        "test_original_expansion_reads_the_first_printing_not_every_printing",
    "nontoken": "test_nontoken_rejects_a_token",
    "token_only": "test_token_only_rejects_a_nontoken",
    "untapped_only": "test_untapped_only_rejects_a_tapped_permanent",
    "controller": "test_the_relative_keys_refuse_without_the_context_they_need",
    "owner": "test_ownership_is_asked_separately_from_control",
    "exclude_self": "test_the_relative_keys_refuse_without_the_context_they_need",
    "not_enchanted": "test_not_enchanted_rejects_a_permanent_carrying_an_aura",
    "enchanted_only": "test_enchanted_only_rejects_a_permanent_with_no_aura",
    "attached_to_filter": "test_a_host_phrase_is_asked_of_the_host",
    "chosen_color": "test_chosen_color_is_read_off_the_ability_s_source",
    "chosen_creature_type":
        "test_chosen_creature_type_is_read_off_the_ability_s_source",
    "attacked_this_turn": "test_the_combat_records_are_read_off_the_permanent",
    "not_attacked_this_turn": "test_the_combat_records_are_read_off_the_permanent",
    "could_attack_this_turn": "test_the_combat_records_are_read_off_the_permanent",
    "blocked_by_source": "test_blocked_by_source_names_only_what_the_source_blocks",
    "blocked_source_this_turn":
        "test_blocked_source_this_turn_outlives_the_combat_it_names",
    "attacking_you": "test_attacking_you_is_two_questions_not_one",
    "unblocked_only": "test_the_blocked_pair_is_read_off_a_real_combat",
    "blocked_only": "test_the_blocked_pair_is_read_off_a_real_combat",
    "not_attacking": "test_the_nonattacking_nonblocking_pair_names_a_creature_in_neither_role",
    "not_blocking": "test_the_nonattacking_nonblocking_pair_names_a_creature_in_neither_role",
    "controlled_since_turn_start":
        "test_controlled_since_turn_start_rejects_a_creature_that_just_arrived",
    "tapped_to_pay_for_source_this_turn":
        "test_tapped_to_pay_names_only_what_paid_for_this_source",
    "other_than_attached_host":
        "test_other_than_attached_host_excludes_one_permanent_by_identity",
    "controller_controls":
        "test_controller_controls_asks_about_the_candidate_s_own_seat",
    "banded_with_source": "test_banded_with_source_names_only_the_band",
    "characteristic_vs_source":
        "test_a_source_relative_bound_is_read_through_the_layers",
}


def _r30_attach(aura, host):
    from engine.auras import attach_aura

    attach_aura(aura, host)


def test_not_enchanted_rejects_a_permanent_carrying_an_aura(pool):
    """"target permanent **that isn't enchanted**" (Time Elemental) — CR 303.4a.

    Its own demonstration rather than a row in ``_REJECTIONS``: that table
    builds a bare permanent, and a bare permanent is exactly what this key
    *accepts*. The rejected one has to be given an Aura first.

    The equipped creature is the second half, and the half a matcher reading the
    shared attachment record would fail: this engine attaches an Equipment
    through the very same list (CR 301.5f), so "isn't enchanted" has to ask for
    the Aura subtype or Time Elemental would refuse to bounce an equipped
    creature it is allowed to bounce.
    """
    bare = Permanent(card=pool["Grizzly Bears"])
    enchanted = Permanent(card=pool["Grizzly Bears"])
    equipped = Permanent(card=pool["Grizzly Bears"])
    aura = Permanent(card=pool["Holy Strength"])
    gear = Permanent(card=pool["Short Sword"])
    game = Game(players=[
        PlayerState(
            name="P1",
            battlefield=[bare, enchanted, equipped, aura, gear],
        ),
        PlayerState(name="P2"),
    ])
    _r30_attach(aura, enchanted)
    _r30_attach(gear, equipped)

    assert subject_matches(game, bare, {"not_enchanted": True})
    assert subject_matches(game, equipped, {"not_enchanted": True})
    assert not subject_matches(game, enchanted, {"not_enchanted": True})


def test_original_expansion_reads_the_first_printing_not_every_printing(pool):
    """"…with **a name originally printed in the Homelands expansion**"
    (Apocalypse Chime; Golgothian Sylex prints it about Antiquities).

    Its own demonstration rather than a row in ``_REJECTIONS``, because a
    rejection alone would pass for a matcher that answered False to everything.
    The load-bearing half is the word **originally**: Grizzly Bears was printed
    in Revised, and a matcher reading the printing *list* — or the set a copy
    happened to be loaded from — would hand it to a Revised sweep. CR 201.5's
    answer is ``printings[0]``, and only that.

    The Antiquities/Revised overlap is the case the Sylex exists for and the
    reason this is not a hypothetical: nineteen of its cards were reprinted, and
    Ornithopter is one of them.
    """
    bears = Permanent(card=pool["Grizzly Bears"])
    thopter = Permanent(card=pool["Ornithopter"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears, thopter]),
        PlayerState(name="P2"),
    ])

    assert subject_matches(game, bears, {"type_filter": "creature"}), (
        "the control: the bare noun phrase must match, or the rejections below "
        "prove nothing about the key"
    )
    assert subject_matches(game, bears, {"original_expansion": "lea"})
    assert not subject_matches(game, bears, {"original_expansion": "hml"})
    # Printed in Revised and originally printed in Alpha — the whole content of
    # the word this key is named for.
    assert "3ed" in pool["Grizzly Bears"].printings
    assert not subject_matches(game, bears, {"original_expansion": "3ed"})
    # …and the same for the card the Sylex was actually printed to catch.
    assert "3ed" in pool["Ornithopter"].printings
    assert subject_matches(game, thopter, {"original_expansion": "atq"})
    assert not subject_matches(game, thopter, {"original_expansion": "3ed"})


def test_enchanted_only_rejects_a_permanent_with_no_aura(pool):
    """"Destroy **target enchanted creature**." (Ramses Overdark.)

    The positive twin of the test above, and here for the same reason: the
    ``_REJECTIONS`` table builds a bare permanent, which is what this key
    rejects rather than what it accepts, so the accepted one has to be given an
    Aura first.

    The equipped creature is again the half a matcher reading the bare
    attachment record would get wrong — CR 301.5f attaches an Equipment through
    the same list — and getting it wrong here points Ramses at a creature the
    handler would then refuse.
    """
    bare = Permanent(card=pool["Grizzly Bears"])
    enchanted = Permanent(card=pool["Grizzly Bears"])
    equipped = Permanent(card=pool["Grizzly Bears"])
    aura = Permanent(card=pool["Holy Strength"])
    gear = Permanent(card=pool["Short Sword"])
    game = Game(players=[
        PlayerState(
            name="P1",
            battlefield=[bare, enchanted, equipped, aura, gear],
        ),
        PlayerState(name="P2"),
    ])
    _r30_attach(aura, enchanted)
    _r30_attach(gear, equipped)

    assert subject_matches(game, enchanted, {"enchanted_only": True})
    assert not subject_matches(game, bare, {"enchanted_only": True})
    assert not subject_matches(game, equipped, {"enchanted_only": True})


def test_a_conjunction_of_types_matches_only_a_permanent_that_is_both(pool):
    """The positive half. An artifact creature answers "artifact creature";
    neither of its halves does on its own."""
    thopter = Permanent(card=pool["Ornithopter"])
    bears = Permanent(card=pool["Grizzly Bears"])
    lotus = Permanent(card=pool["Black Lotus"])
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[thopter, bears, lotus]),
            PlayerState(name="P2"),
        ]
    )
    both = {"type_filter_all": ["artifact", "creature"]}

    assert subject_matches(game, thopter, both)
    assert not subject_matches(game, bears, both)
    assert not subject_matches(game, lotus, both)


def test_a_conjunction_of_subtypes_matches_a_permanent_carrying_both(pool):
    """The positive half, on the cards the key was added for.

    "Urza's Mine" is two land types, not one name (CR 205.3i): `urza's` and
    `mine`. So "if you control an Urza's Power-Plant and an Urza's Tower" asks
    for two permanents each carrying two subtypes, and an OR would let a single
    Urza's Mine satisfy the whole assembly.
    """
    mine = Permanent(card=pool["Urza's Mine"])
    tower = Permanent(card=pool["Urza's Tower"])
    game = Game(
        players=[PlayerState(name="P1", battlefield=[mine, tower]), PlayerState(name="P2")]
    )

    assert subject_matches(game, mine, {"subtype_filter_all": ["urza's", "mine"]})
    assert subject_matches(game, tower, {"subtype_filter_all": ["urza's", "tower"]})
    # The whole point: the Mine is an Urza's, and it is not a Tower.
    assert not subject_matches(game, mine, {"subtype_filter_all": ["urza's", "tower"]})


def test_any_colors_admits_an_object_answering_either_colour(pool):
    """The positive half of the row above, and the half that says "or".

    Grizzly Bears is mono-green, so a matcher that read ``any_colors`` as a
    conjunction — the way ``subtype_filter_all`` beside it legitimately is —
    would reject it here while still passing the rejection row, which names no
    colour the Bears have. Abomination destroys a green creature and a white
    one; requiring both would make it destroy neither.
    """
    bears = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[PlayerState(name="P1", battlefield=[bears]), PlayerState(name="P2")])

    assert subject_matches(game, bears, {"any_colors": ["G", "W"]})
    assert subject_matches(game, bears, {"any_colors": ["G"]})
    assert not subject_matches(game, bears, {"any_colors": ["W"]})


def test_blocked_by_source_names_only_what_the_source_blocks(pool):
    """"target creature **it's blocking**" (Goblin Snowman, Tinder Wall).

    A relation rather than a characteristic, so it is demonstrated in a real
    combat rather than by a row in ``_REJECTIONS``: the rejected creature is an
    ordinary attacker that this blocker simply is not blocking, and no property
    of the creature itself tells the two apart.

    With no source there is no relation, and the answer must be **no** — a
    matcher that shrugged and returned True would turn "it's blocking" into
    "any creature", which is the whole board.
    """
    attacker = Permanent(card=pool["Grizzly Bears"])
    other = Permanent(card=pool["Grizzly Bears"])
    blocker = Permanent(card=pool["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[attacker, other])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]

    described = {"blocked_by_source": True}
    assert subject_matches(game, attacker, described, source=blocker)
    assert not subject_matches(game, other, described, source=blocker)
    assert not subject_matches(game, attacker, described)


def test_blocked_source_this_turn_outlives_the_combat_it_names(pool):
    """"all creatures **that blocked this creature this turn**" (Joven's
    Ferrets).

    The history twin of the relation above, and the difference is the whole
    reason it is a second key: ``blocked_by_source`` reads the live combat maps
    and this reads the record the declare-blockers step stamps on each blocker.
    So it still answers after the combat is over -- which is when the card that
    prints it asks, and what a matcher reading the maps would get wrong.

    Two rejections beside it. A creature that was in the combat but blocked
    nothing is not in the set, or the phrase would read "creatures in combat";
    and with no source the answer is **no**, because a matcher that shrugged
    would name every creature that has ever blocked, which for a tap sweep is a
    strictly larger board than the card prints.
    """
    attacker = Permanent(card=pool["Grizzly Bears"])
    blocker = Permanent(card=pool["Grizzly Bears"])
    bystander = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[blocker, bystander]),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    # The combat is over: the maps have let go and only the record is left,
    # which is exactly the moment "at end of combat" asks.
    game.end_combat()

    described = {"blocked_source_this_turn": True}
    assert subject_matches(game, blocker, described, source=attacker)
    assert not subject_matches(game, bystander, described, source=attacker)
    assert not subject_matches(game, blocker, described)


def test_tapped_to_pay_names_only_what_paid_for_this_source(pool):
    """"…all Merfolk **tapped this turn to pay for its abilities**" (Vodalian
    War Machine).

    A history rather than a characteristic, and demonstrated with a record
    rather than by a row in ``_REJECTIONS``: the rejected creature is an
    ordinary tapped permanent, and nothing about either one tells them apart —
    which is precisely why the payment path has to write it down.

    Two rejections, and both matter. A permanent tapped for *another*
    permanent's ability is not in the set, or the phrase would read "tapped
    this turn"; and with no source at all the answer is **no**, because a
    matcher that shrugged would turn the clause into "every tapped permanent",
    which is the whole board.
    """
    from engine.cost_tap_records import record_tapped_to_pay

    paid_for_me = Permanent(card=pool["Grizzly Bears"])
    paid_for_someone_else = Permanent(card=pool["Grizzly Bears"])
    just_tapped = Permanent(card=pool["Grizzly Bears"])
    source = Permanent(card=pool["Grizzly Bears"])
    other_source = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[
        PlayerState(
            name="P1",
            battlefield=[
                paid_for_me, paid_for_someone_else, just_tapped, source,
                other_source,
            ],
        ),
        PlayerState(name="P2"),
    ])
    game.become_tapped(paid_for_me)
    game.become_tapped(paid_for_someone_else)
    game.become_tapped(just_tapped)
    record_tapped_to_pay(source, paid_for_me)
    record_tapped_to_pay(other_source, paid_for_someone_else)

    described = {"tapped_to_pay_for_source_this_turn": True}
    assert subject_matches(game, paid_for_me, described, source=source)
    assert not subject_matches(game, paid_for_someone_else, described, source=source)
    assert not subject_matches(game, just_tapped, described, source=source)
    assert not subject_matches(game, paid_for_me, described)


def test_other_than_attached_host_excludes_one_permanent_by_identity(pool):
    """"target creature **other than enchanted creature**" (Kjeldoran Pride),
    and the same referent under Veteran's Voice's "other than the creature
    tapped this way".

    An exclusion, so it is demonstrated by what it *keeps* as much as by what it
    drops: a filter rejecting everything would pass a one-sided check, and so
    would one rejecting nothing on a board of a single creature.

    Its own demonstration rather than a row in ``_REJECTIONS``, because that
    table asks each key to reject with no source in hand — and with no source
    this excludes nothing, which is the correct answer for an exclusion and the
    wrong shape for that table. Excluding on a missing source is the direction
    that would silently *narrow* a set the caller could not describe.

    Identity is the point: a look-alike on the same battlefield is a different
    permanent and stays a legal target. ``other_than_source`` could not have
    said any of this — the source is the Aura, and no creature is ever it, so
    that key would have excluded nothing at all.
    """
    from engine.auras import attach_aura

    host = Permanent(card=pool["Grizzly Bears"])
    look_alike = Permanent(card=pool["Grizzly Bears"])
    aura = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[host, look_alike, aura]),
        PlayerState(name="P2"),
    ])
    attach_aura(aura, host)

    described = {"other_than_attached_host": True}
    assert not subject_matches(game, host, described, source=aura)
    assert subject_matches(game, look_alike, described, source=aura)
    # A source attached to nothing excludes nothing.
    assert subject_matches(game, host, described, source=look_alike)
    assert subject_matches(game, host, described)


def test_attacking_you_is_two_questions_not_one(pool):
    """"target creature **that's attacking you**" (Ice Floe, Snow Fortress).

    Attacking is a state of the creature (CR 508.1a); *whom* it attacks is the
    defending player it was declared against. Answering only the first would
    offer every attacker in a multiplayer game, including the ones aimed at
    somebody else — so the seat is asserted with three players, where the two
    readings actually differ.
    """
    attacker = Permanent(card=pool["Grizzly Bears"])
    idle = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker, idle]),
        PlayerState(name="P2"),
        PlayerState(name="P3"),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]

    described = {"attacking_you": True}
    assert subject_matches(game, attacker, described, observer=1)
    assert not subject_matches(game, attacker, described, observer=2), (
        "attacking somebody else is not attacking you"
    )
    assert not subject_matches(game, idle, described, observer=1)
    assert not subject_matches(game, attacker, described)


def test_controlled_since_turn_start_rejects_a_creature_that_just_arrived(pool):
    """"…except for creatures the player hasn't controlled continuously since
    the beginning of the turn." (Total War.)

    Its own demonstration rather than a row in ``_REJECTIONS``: the answer is a
    *comparison* against the game's turn, so the rejected permanent is told
    apart from the accepted one by a stamp rather than by anything printed on
    either — which is also why the pure matcher cannot answer it and why this
    is asked through ``subject_matches``.

    The same predicate CR 302.6's summoning sickness reads, so a creature that
    changed hands this turn is exempt here for the same reason it cannot
    attack.
    """
    settled = Permanent(card=pool["Grizzly Bears"])
    arrived = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[settled, arrived]),
        PlayerState(name="P2"),
    ])
    settled.metadata["summoning_sickness_turn"] = game.turn - 1
    arrived.metadata["summoning_sickness_turn"] = game.turn

    assert subject_matches(game, arrived, {"type_filter": "creature"}), (
        "the control: the bare noun phrase must match, or the rejection below "
        "proves nothing about the key"
    )
    assert subject_matches(game, settled, {"controlled_since_turn_start": True})
    assert not subject_matches(game, arrived, {"controlled_since_turn_start": True})


def test_banded_with_source_names_only_the_band(pool):
    """"all creatures **banded with it**" (Icatian Skirmishers) — CR 702.22e.

    Its own demonstration rather than a row in ``_REJECTIONS``: the answer is a
    *declaration*, so telling the accepted creature from the rejected one needs
    a real attack with a real band. A third attacker outside the band is what
    the test is for — it answers every other part of the phrase and must still
    be rejected, which a matcher shrugging at the key would not do.
    """
    bander = Permanent(card=pool["Icatian Skirmishers"])
    mate = Permanent(card=pool["Camel"])
    outsider = Permanent(card=pool["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bander, mate, outsider]),
        PlayerState(name="P2"),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1, 2], bands=[[0, 1]])[0]

    described = {"banded_with_source": True}
    assert subject_matches(game, mate, described, source=bander)
    assert not subject_matches(game, outsider, described, source=bander), (
        "attacking beside a band is not being in it"
    )
    assert not subject_matches(game, bander, described, source=bander), (
        "a creature is not banded with itself"
    )
    assert not subject_matches(game, mate, described), (
        "with no source there is no band, and the answer must be no"
    )


def test_a_source_relative_bound_is_read_through_the_layers(pool):
    """"…creatures with power **equal to or greater than the enchanted
    creature's toughness**" (Ironclaw Curse).

    Its own demonstration rather than a row in ``_REJECTIONS``: the bound is not
    in the payload at all, so the accepted and rejected creatures are told apart
    by a number read off a *third* permanent — which is exactly why the pure
    matcher cannot answer it.

    Both halves are read through CR 613's accessors, and the pump is what
    proves it: nothing about either printed card changes, and the answer does.
    """
    from engine.pt import add_pt_modifier

    source = Permanent(card=pool["Grizzly Bears"])          # 2/2
    two_power = Permanent(card=pool["Grizzly Bears"])       # power 2
    one_power = Permanent(card=pool["Scryb Sprites"])       # power 1
    game = Game(players=[
        PlayerState(name="P1", battlefield=[source]),
        PlayerState(name="P2", battlefield=[two_power, one_power]),
    ])

    described = {
        "characteristic_vs_source": {
            "characteristic": "power", "op": "ge",
            "source_characteristic": "toughness",
        },
    }
    assert subject_matches(game, two_power, described, source=source)
    assert not subject_matches(game, one_power, described, source=source)
    assert not subject_matches(game, two_power, described), (
        "with no source there is no bound, and the answer must be no"
    )

    # The source's toughness falls to 1: the one-power creature is now over the
    # bound although nothing printed on it changed.
    add_pt_modifier(source, 0, -1)
    assert subject_matches(game, one_power, described, source=source)


def test_no_key_is_promised_without_a_matcher_behind_it():
    """The guard the whole file exists for. Adding a key to
    ``TESTABLE_SUBJECT_FILTER_KEYS`` and forgetting the matcher behind it admits
    every card printing that phrase and then ignores the phrase — silently, and
    in the one direction an effect must never go. So the set is held equal to
    what is *demonstrated* above rather than merely listed."""
    demonstrated = {key for key, _, _ in _REJECTIONS} | set(_COVERED_ELSEWHERE)

    assert demonstrated == TESTABLE_SUBJECT_FILTER_KEYS
    assert OBJECT_ONLY_FILTER_KEYS < TESTABLE_SUBJECT_FILTER_KEYS


# ---------------------------------------------------------------------------
# What a printed noun phrase means when the object is a *card*
# ---------------------------------------------------------------------------


def test_a_card_filter_answers_only_what_is_printed_on_the_face():
    """CR 613.1 applies the layer system to permanents, so a card in a hand or a
    graveyard has no computed characteristics at all. The key set is small for
    that reason rather than for want of code, and a phrase reaching outside it
    refuses — charging a wider cost is the direction a cost must never drift."""
    from engine.grammar import card_filter_payload

    assert card_filter_payload("a land card") == {"type_filter": "land"}
    assert card_filter_payload("a Shrine card") == {"subtype_filter": "shrine"}
    assert card_filter_payload("a card") == {}

    # A supertype is printed on the face and nothing can have changed it
    # (CR 205.4b), so it is one of the four things a card *can* answer — since
    # round 108, when it grew a payload key and a matcher. Until then it had
    # neither and "a legendary card" reduced to "a card", which is why the
    # phrase was refused outright rather than charged.
    assert card_filter_payload("a legendary card") == {"supertypes": ["legendary"]}
    # A key the card matcher cannot answer.
    assert card_filter_payload("a tapped creature card") is None
    # The word "card" has to be printed — "a land" is a phrase about permanents,
    # and the card matcher answers a different question about a different object.
    assert card_filter_payload("a land") is None


def test_a_card_matches_every_type_printed_on_it(catalog_by_name):
    """CR 205.2a: a card has all the types on its line. The matcher used to ask
    ``primary_type``, which collapses "Artifact Creature — Construct" to one
    word and would have refused it as an artifact card."""
    from engine.handlers._common import _card_matches_filter

    juggernaut = catalog_by_name["Juggernaut"]
    assert _card_matches_filter(juggernaut, {"type_filter": "artifact"})
    assert _card_matches_filter(juggernaut, {"type_filter": "creature"})
    assert not _card_matches_filter(juggernaut, {"type_filter": "land"})


def test_alternatives_are_ord_not_anded(catalog_by_name, set_pool):
    """"A land card or Shrine card" holds across two characteristics no single
    filter can combine — AND'd, they name a card that is both."""
    from engine.subject_filters import card_matches_any

    printed = ({"type_filter": "land"}, {"subtype_filter": "shrine"})
    assert card_matches_any(catalog_by_name["Mountain"], printed)
    assert card_matches_any(set_pool("M21")["Sanctum of Calm Waters"], printed)
    assert not card_matches_any(catalog_by_name["Juggernaut"], printed)
    # No alternatives is no narrowing — the honest reading of "Discard a card".
    assert card_matches_any(catalog_by_name["Juggernaut"], ())


# --- a supertype is a restriction, not a decoration (round 108) -------------


def test_a_supertype_narrows_a_permanent(catalog_by_name, set_pool):
    """CR 205.4a: a supertype sits on the type line, ahead of the card types.
    Nothing in layers 4-6 computes one here, so the answer is read off the line
    the permanent effectively has."""
    from engine.grammar import subject_filter_payload
    from engine.handlers._common import permanent_matches_filter
    from engine.models import Permanent

    described = subject_filter_payload("a legendary creature")
    assert described == {"type_filter": "creature", "supertypes": ["legendary"]}

    legend = Permanent(card=set_pool("M21")["Niambi, Esteemed Speaker"])
    plain = Permanent(card=set_pool("M21")["Alpine Watchdog"])
    assert permanent_matches_filter(legend, described)
    assert not permanent_matches_filter(plain, described)


def test_a_supertype_no_matcher_tests_refuses_the_line():
    """Scryfall reports "token" as a supertype, because a token object's printed
    line reads "Token Creature - Goblin". This engine prints no such word and
    answers "is this a token?" from the permanent's identity, so a type-line test
    would match *no* token at all — a restriction silently matching nothing,
    which is the same failure as one silently matching everything.

    So the field stays set on the AST with no key emitted, and the gate refuses
    the line rather than charging the half it could read."""
    from engine.grammar import compile_line, subject_filter_payload

    assert subject_filter_payload("a token creature") is None
    compiled = compile_line("Destroy target token creature.")
    assert compiled.instructions == ()
    assert "supertypes" in (compiled.lowering_error or "")


def test_a_narrowing_that_emits_no_key_is_refused_rather_than_dropped():
    """The bug class this round closed, stated directly.

    ``_restrictions_beyond`` asks "is this field honoured at all?" and answers
    yes for every conditionally-emitted field, because each is honoured
    *sometimes*; the key check downstream asks "is every key testable?" and sees
    nothing, because a field that emitted nothing left no key to inspect. A
    narrowing falls between the two questions.

    ``mana_value`` had a hand-written line guarding exactly this. ``power`` and
    ``toughness`` emit under the identical condition and had none, so a variable
    bound was dropped and the effect reached every creature."""
    from engine.grammar import compile_line
    from engine.grammar.lowering._common import CONDITIONALLY_EMITTED_FIELDS

    for line in (
        "Destroy target creature with power X or greater.",
        "Destroy target creature with mana value X or less.",
    ):
        compiled = compile_line(line)
        assert compiled.instructions == (), line
    # Every field in the table is a real ``ObjectFilter`` field, so a rename
    # cannot leave a silent hole where a guard used to be.
    from engine.grammar import ast

    fields = {f.name for f in dataclasses.fields(ast.ObjectFilter())}
    assert set(CONDITIONALLY_EMITTED_FIELDS) <= fields


def test_a_supertype_rides_the_payload_all_the_way_to_the_dispatcher():
    """"Destroy target legendary creature." lowered byte-identically to
    "Destroy target creature." — the word consumed, recorded on the AST, and
    dropped on the way out. Both the filter the handler applies and the
    description the picker offers from now carry it."""
    from engine.grammar import compile_line

    narrowed = compile_line("Destroy target legendary creature.").instructions[0]
    plain = compile_line("Destroy target creature.").instructions[0]
    assert narrowed.payload != plain.payload
    assert narrowed.payload["supertypes"] == ["legendary"]
    assert narrowed.payload["targets"]["filter"]["supertypes"] == ["legendary"]


def test_a_host_phrase_is_asked_of_the_host(pool):
    """"Auras you own **attached to permanents you control**" (Remove
    Enchantments). The narrowing is not about the Aura at all — it is the same
    question asked one object along — so the key carries a whole nested payload
    and the matcher recurses into it.

    Its own demonstration rather than a row in ``_REJECTIONS``: every row there
    rejects a *bare* permanent, and a bare permanent is not attached to
    anything, so it would fail the key for the wrong reason. The three
    permanents below separate the three answers — attached to a matching host,
    attached to a host that does not match, attached to nothing.
    """
    mine = Permanent(card=pool["Grizzly Bears"])
    theirs = Permanent(card=pool["Grizzly Bears"])
    on_mine = Permanent(card=pool["Holy Strength"])
    on_theirs = Permanent(card=pool["Holy Strength"])
    loose = Permanent(card=pool["Holy Strength"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[mine, on_mine, on_theirs, loose]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    _r30_attach(on_mine, mine)
    _r30_attach(on_theirs, theirs)
    host_you_control = {"attached_to_filter": {"controller": "you"}}

    assert subject_matches(game, on_mine, host_you_control, observer=0)
    assert not subject_matches(game, on_theirs, host_you_control, observer=0)
    assert not subject_matches(game, loose, host_you_control, observer=0)
    # And the seat really is the observer's, not "whoever controls the Aura":
    # seat 1 owns neither Aura but controls the other host.
    assert subject_matches(game, on_theirs, host_you_control, observer=1)


def test_a_nested_host_phrase_is_gated_by_the_same_key_set():
    """The recursion is in the *gate* as well as in the matcher.

    A flat set difference over the outer payload answers "testable" for
    ``attached_to_filter`` whatever the phrase inside says, which would admit a
    sweep with no observer, drop the seat, and take every Aura on the table.
    ``untestable_filter_keys`` names the outer key, because that is the phrase
    the refusal has to point at.
    """
    plain = {"subtype_filter": "aura", "attached_to_filter": {"type_filter": "creature"}}
    seated = {"subtype_filter": "aura", "attached_to_filter": {"controller": "you"}}
    invented = {"subtype_filter": "aura", "attached_to_filter": {"no_such_key": True}}

    assert not untestable_filter_keys(plain)
    assert not untestable_filter_keys(seated)
    assert untestable_filter_keys(invented) == {"attached_to_filter"}
    # An observerless caller may take the first and not the second: a seat one
    # level down is still a seat.
    assert object_only_filter(plain) == plain
    assert object_only_filter(seated) is None


# --- W1G1: prevention and damage shields ---
def test_the_blocked_pair_is_read_off_a_real_combat(pool):
    """CR 509.1h's pair — "…by **unblocked** creatures" (Kjeldoran Royal Guard,
    Veteran Bodyguard) and "**blocked** creature".

    Demonstrated in a real combat rather than by a row in ``_REJECTIONS``,
    because the reading that matters is the one a bare ``not perm.blocked``
    gets wrong: a bear standing outside combat has ``blocked`` False and would
    be admitted as "unblocked" by it, which on the Guard is every ping ability
    on the board redirecting onto a 3/5. CR 509.1h makes both words states of
    an *attacking* creature, so a creature outside combat answers neither.
    """
    unblocked = Permanent(card=pool["Grizzly Bears"])
    blocked = Permanent(card=pool["Grizzly Bears"])
    idle = Permanent(card=pool["Grizzly Bears"])
    blocker = Permanent(card=pool["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[unblocked, blocked, idle])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 1})[0]

    assert subject_matches(game, unblocked, {"unblocked_only": True})
    assert not subject_matches(game, blocked, {"unblocked_only": True})
    # The half a bare ``not blocked`` gets wrong.
    assert not subject_matches(game, idle, {"unblocked_only": True})

    assert subject_matches(game, blocked, {"blocked_only": True})
    assert not subject_matches(game, unblocked, {"blocked_only": True})
    assert not subject_matches(game, idle, {"blocked_only": True})
# --- end W1G1 ---


# --- FEM G5: prices offered to a player, prevention and control ---
def test_controller_controls_asks_about_the_candidate_s_own_seat(pool):
    """"target creature **whose controller controls an Island**" (Seasinger).

    Its own demonstration rather than a row in ``_REJECTIONS``: that table
    builds one bare permanent on one battlefield, and the question here is
    about a *second* permanent on the same seat's board — so the rejection has
    to be staged with two seats and three permanents.

    The half a reader could plausibly get wrong is the last assertion. The
    phrase does not say "an Island **you** control": the seat it asks about is
    the candidate's controller, not the ability's, and passing the observer
    straight down would read the wrong board every time the two differ — which
    on Seasinger is every time it is worth activating.
    """
    theirs = Permanent(card=pool["Grizzly Bears"])
    their_island = Permanent(card=pool["Island"])
    mine = Permanent(card=pool["Grizzly Bears"])
    my_island = Permanent(card=pool["Island"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[mine, my_island]),
        PlayerState(name="P2", battlefield=[theirs, their_island]),
    ])
    islander = {"type_filter": "creature", "controller_controls": {"subtype_filter": "island"}}

    assert subject_matches(game, theirs, islander, observer=0)
    assert subject_matches(game, mine, islander, observer=0)

    game.players[1].battlefield = [theirs]
    game._sync_control()
    assert not subject_matches(game, theirs, islander, observer=0)
    # …and the seat asked really is the candidate's own: seat 0 still has an
    # Island, so a reader that passed the observer down would say yes here.
    assert subject_matches(game, mine, islander, observer=0)


def test_a_controller_controls_phrase_is_gated_by_the_same_key_set():
    """The nested gate, for the second nested key.

    ``untestable_filter_keys`` recurses into this phrase exactly as it does
    into a host phrase, and names the *outer* key — that is the clause a
    refusal has to point at. And an observerless, gameless caller may not take
    it at all: reading a seat's whole board is not something a payload handed
    to a bare object matcher can do, so the key is outside
    ``OBJECT_ONLY_FILTER_KEYS`` and the phrase refuses rather than being
    dropped, which here would offer every creature on the table.
    """
    plain = {"type_filter": "creature", "controller_controls": {"subtype_filter": "island"}}
    invented = {"type_filter": "creature", "controller_controls": {"no_such_key": True}}

    assert not untestable_filter_keys(plain)
    assert untestable_filter_keys(invented) == {"controller_controls"}
    assert object_only_filter(plain) is None
# --- end FEM G5 ---


# --- W2G1: combat triggers and restrictions ---
def test_the_nonattacking_nonblocking_pair_names_a_creature_in_neither_role(pool):
    """"target **nonattacking, nonblocking** creature" (Unlikely Alliance).

    Their own demonstration rather than rows in ``_REJECTIONS``, for
    ``untapped_only``'s reason: that table builds a permanent outside combat,
    which is exactly what these two keys *admit*, so a row there would prove
    nothing. The rejection has to come out of a real combat.

    Both fields have been ``bool | None`` since the state adjectives were read
    and only the True half had a payload form, so a card printing the negative
    emitted the payload of a bare "creature" and the narrowing vanished between
    the two gates — the same silent drop ``blocked``/``unblocked`` recorded one
    field over.
    """
    attacker = Permanent(card=pool["Grizzly Bears"])
    blocker = Permanent(card=pool["Grizzly Bears"])
    idle = Permanent(card=pool["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[attacker, idle])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]

    assert subject_matches(game, idle, {"not_attacking": True})
    assert subject_matches(game, idle, {"not_blocking": True})
    assert not subject_matches(game, attacker, {"not_attacking": True})
    assert not subject_matches(game, blocker, {"not_blocking": True})
    # Each key answers its own axis: an attacker is not blocking, and a blocker
    # is not attacking. Folding them into one would make the card's two printed
    # words one, and pump the wrong half of the combat.
    assert subject_matches(game, attacker, {"not_blocking": True})
    assert subject_matches(game, blocker, {"not_attacking": True})
# --- end W2G1 ---
