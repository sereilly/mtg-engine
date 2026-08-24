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
    subject_matches,
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
    ("exclude_colors", {"exclude_colors": ["G"]}, "Grizzly Bears"),
    ("exclude_types", {"exclude_types": ["creature"]}, "Grizzly Bears"),
    ("exclude_subtypes", {"exclude_subtypes": ["bear"]}, "Grizzly Bears"),
    ("tapped_only", {"tapped_only": True}, "Grizzly Bears"),
    ("mana_value", {"mana_value": {"op": "le", "value": 1}}, "Grizzly Bears"),
    ("power", {"power": {"op": "ge", "value": 4}}, "Grizzly Bears"),
    ("toughness", {"toughness": {"op": "ge", "value": 4}}, "Grizzly Bears"),
    ("with_plus1_counter", {"with_plus1_counter": True}, "Grizzly Bears"),
    ("with_keywords", {"with_keywords": ["flying"]}, "Grizzly Bears"),
    ("named", {"named": "Hill Giant"}, "Grizzly Bears"),
    # CR 205.4a. Read off the type line, which for a supertype is the whole of
    # what there is — nothing in layers 4-6 computes one.
    ("supertypes", {"supertypes": ["legendary"]}, "Grizzly Bears"),
    # CR 508.1a: attacking is a state of the permanent itself, stamped at
    # declaration — a bear standing outside combat is not attacking, and a
    # matcher that ignored the key would untap it anyway (Disharmony).
    ("attacking_only", {"attacking_only": True}, "Grizzly Bears"),
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
    grant_keyword(perm, "defender", until_eot=True)
    assert subject_matches(game, perm, described)
    assert "defender" not in (perm.card.keywords or ()), (
        "the printed card still has no defender — a matcher reading it would "
        "have answered no"
    )


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
    "nontoken": "test_nontoken_rejects_a_token",
    "untapped_only": "test_untapped_only_rejects_a_tapped_permanent",
    "controller": "test_the_relative_keys_refuse_without_the_context_they_need",
    "owner": "test_ownership_is_asked_separately_from_control",
    "exclude_self": "test_the_relative_keys_refuse_without_the_context_they_need",
}


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
