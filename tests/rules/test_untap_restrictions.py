"""Tests for Magic: The Gathering Comprehensive Rules Section 502.

Covers:
  502.3 — Normally all of a player's permanents untap, but effects can keep
          one or more of them from untapping

These pin the *derivation* of untap restrictions from oracle text
(engine/untap_restrictions.py), which replaced a name-keyed table. The point of
that change is that a card the engine has never seen behaves correctly as long
as it uses a printed template, so most of these use invented card names — a
test naming Winter Orb could pass against a lookup table keyed by "Winter Orb".
The real cards are covered by the set suites.
"""

import pytest

from engine.untap_restrictions import untap_restriction_for


def _restriction(text: str):
    return untap_restriction_for(text)


@pytest.mark.cr("502.3")
def test_502_3_skip_the_untap_step_entirely():
    """"Players skip their untap steps." (Stasis)"""
    r = _restriction("Players skip their untap steps.")

    assert r is not None
    assert (r.scope, r.limit) == ("all", 0)


@pytest.mark.cr("502.3")
def test_502_3_per_type_untap_limit():
    """"Players can't untap more than one land during their untap steps."
    (Winter Orb) and the creature-scoped variant (Smoke)."""
    lands = _restriction("Players can't untap more than one land during their untap steps.")
    creatures = _restriction(
        "Players can't untap more than one creature during their untap steps."
    )

    assert (lands.scope, lands.limit) == ("land", 1)
    assert (creatures.scope, creatures.limit) == ("creature", 1)


@pytest.mark.cr("502.3")
def test_502_3_untap_limit_reads_the_printed_count():
    """The count is read from the text, not assumed to be one — a card
    printed with "more than two lands" gets a limit of 2."""
    r = _restriction("Players can't untap more than two lands during their untap steps.")

    assert (r.scope, r.limit) == ("land", 2)


@pytest.mark.cr("502.3")
def test_502_3_power_gated_untap_block():
    """"Creatures with power 3 or greater don't untap during their
    controllers' untap steps." (Meekstone)"""
    r = _restriction(
        "Creatures with power 3 or greater don't untap during their controllers' untap steps."
    )

    assert r.blocked == {"type_filter": "creature", "power": {"op": "ge", "value": 3}}


@pytest.mark.cr("502.3")
def test_502_3_power_threshold_reads_the_printed_number():
    """A hypothetical Meekstone variant at a different threshold needs no
    registration — the number comes from the text."""
    r = _restriction(
        "Creatures with power 5 or greater don't untap during their controllers' untap steps."
    )

    assert r.blocked["power"] == {"op": "ge", "value": 5}


@pytest.mark.cr("502.3")
def test_502_3_color_gated_untap_block():
    """"Blue creatures don't untap during their controllers' untap steps."
    (Magnetic Mountain), and the same template in another color."""
    blue = _restriction("Blue creatures don't untap during their controllers' untap steps.")
    green = _restriction("Green creatures don't untap during their controllers' untap steps.")

    assert blue.blocked == {"type_filter": "creature", "color_filter": "U"}
    assert green.blocked == {"type_filter": "creature", "color_filter": "G"}


@pytest.mark.cr("502.3")
def test_502_3_as_long_as_untapped_qualifier_applies_to_any_restriction():
    """"As long as this artifact is untapped, ..." (Winter Orb) qualifies the
    restriction that follows it rather than being part of one wording, so it
    composes with the others."""
    orb = _restriction(
        "As long as this artifact is untapped, players can't untap more than "
        "one land during their untap steps."
    )
    composed = _restriction(
        "As long as this enchantment is untapped, creatures with power 2 or "
        "greater don't untap during their controllers' untap steps."
    )

    assert (orb.scope, orb.limit, orb.only_while_source_untapped) == ("land", 1, True)
    assert composed.blocked["power"] == {"op": "ge", "value": 2}
    assert composed.only_while_source_untapped is True


@pytest.mark.cr("502.3")
def test_502_3_the_restriction_may_sit_on_any_line_of_the_card():
    """Stasis carries an upkeep clause after its restriction; Magnetic Mountain
    carries one too. The restriction is found wherever it is printed."""
    r = _restriction(
        "Players skip their untap steps.\n"
        "At the beginning of your upkeep, sacrifice this enchantment unless you pay {U}."
    )

    assert (r.scope, r.limit) == ("all", 0)


@pytest.mark.cr("502.3")
def test_502_3_unrelated_untap_text_imposes_no_restriction():
    """Plenty of cards mention untapping without restricting the untap step.
    A loose keyword scan would claim these; the templates must not."""
    for text in (
        "{T}: Add {C}. This artifact doesn't untap during your untap step.",
        "You may choose not to untap this creature during your untap step.",
        "Untap target creature.",
        "Enchanted creature doesn't untap during its controller's untap step.",
        "At the beginning of your upkeep, untap all creatures you control.",
        "",
    ):
        assert _restriction(text) is None, text


@pytest.mark.cr("502.3")
def test_502_3_supertype_gated_untap_block():
    """"Legendary creatures don't untap during their controllers' untap
    steps." (Arena of the Ancients) — the supertype is payload, so the card
    needs no registration; and the plural-possessive spelling is the one the
    card prints."""
    r = _restriction(
        "Legendary creatures don't untap during their controllers' untap steps."
    )

    assert r is not None
    assert r.blocked == {"type_filter": "creature", "supertypes": ["legendary"]}


@pytest.mark.cr("502.3")
def test_502_3_any_supertype_is_read_now_that_the_matcher_answers_the_phrase():
    """This assertion used to be the opposite, and the refusal it guarded
    expired rather than being wrong.

    The supertype was a hand-written ``(?P<supertype>legendary)`` alternation,
    so "snow creatures" was unclaimed because the *pattern* did not name the
    word — not because anything could not enforce it. The subject is a noun
    phrase read by the grammar's noun parser now, and `subject_matches` tests a
    supertype through layer 4, so the phrase is both claimed and enforced. The
    playbook's rule: when a round builds machinery near an old decline,
    re-probe the decline.
    """
    r = _restriction(
        "Snow creatures don't untap during their controllers' untap steps."
    )

    assert r is not None
    assert r.blocked == {"type_filter": "creature", "supertypes": ["snow"]}


@pytest.mark.cr("502.3")
def test_502_3_a_subject_the_matcher_cannot_test_is_still_unclaimed():
    """The widening guard, pointed at phrases that really are outside the
    engine. A narrowing parsed and then dropped would turn a block on some
    creatures into a block on every permanent, which is the one direction this
    must never take — so an unreadable noun phrase leaves the line unclaimed
    and its card unsupported."""
    for subject in (
        "Creatures with three heads",
        "Creatures that attacked last turn",
        "Creatures enchanted by an Aura you don't control",
    ):
        assert _restriction(
            f"{subject} don't untap during their controllers' untap steps."
        ) is None, subject


# ---------------------------------------------------------------------------
# 502.3 enforcement — the block is a noun phrase, and the untap step tests it
# ---------------------------------------------------------------------------

def _blocked_board(restriction_text: str, subject):
    """*subject* tapped on P1's battlefield, under a permanent printing
    *restriction_text*."""
    from engine import Game
    from engine.models import CardDefinition, Permanent, PlayerState

    source = Permanent(card=CardDefinition(
        name="Source", mana_cost="", cmc=0.0, type_line="Enchantment",
        oracle_text=restriction_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Source", "type_line": "Enchantment"},
    ))
    subject.tapped = True
    p1 = PlayerState(name="P1", battlefield=[source, subject])
    game = Game(players=[p1, PlayerState(name="P2")])
    return game, subject


def _tapped_creature(name: str, power: int = 2, keywords: tuple[str, ...] = ()):
    from engine.models import CardDefinition, Permanent

    return Permanent(card=CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=keywords,
        produced_mana=(), power=str(power), toughness='2',
        raw={"name": name, "type_line": "Creature - Test"},
    ))


@pytest.mark.cr("502.3")
def test_502_3_a_block_narrowed_by_a_keyword_is_enforced():
    """"Creatures with flying don't untap during their controllers' untap
    steps." (Energy Storm, Blizzard.)

    The regression this round exists for. The block used to be three hand-cut
    fields — a power cap, a colour and a supertype — and this phrase matched
    none of them, so both cards reported **supported** with the line doing
    nothing at all. It is a noun phrase now, tested by the matcher that answers
    every other printed noun phrase.
    """
    flier = _tapped_creature("Flier", keywords=("Flying",))
    game, flier = _blocked_board(
        "Creatures with flying don't untap during their controllers' untap steps.",
        flier,
    )

    game.resolve_untap_step(0)

    assert flier.tapped


@pytest.mark.cr("502.3")
def test_502_3_the_same_block_leaves_everything_else_untapping():
    """The other half: the narrowing must narrow. A dropped one would freeze
    the whole board, which is the direction an untap block must never widen
    in."""
    ground = _tapped_creature("Ground")
    game, ground = _blocked_board(
        "Creatures with flying don't untap during their controllers' untap steps.",
        ground,
    )

    game.resolve_untap_step(0)

    assert not ground.tapped


@pytest.mark.cr("502.3")
def test_502_3_a_negated_keyword_reads_as_the_complement():
    """"Creatures **without** flying don't untap…" (Mudslide) — the same
    sentence with the polarity printed into the noun phrase, so it needs no
    row of its own."""
    ground = _tapped_creature("Ground")
    flier = _tapped_creature("Flier", keywords=("Flying",))
    game, ground = _blocked_board(
        "Creatures without flying don't untap during their controllers' untap steps.",
        ground,
    )
    flier.tapped = True
    game.players[0].battlefield.append(flier)

    game.resolve_untap_step(0)

    assert ground.tapped
    assert not flier.tapped


@pytest.mark.cr("502.3")
def test_502_3_a_block_need_not_name_creatures_at_all():
    """"Islands don't untap during their controllers' untap steps." (Curse of
    Marit Lage.)

    The three fields this replaced were read inside a ``primary_type ==
    "creature"`` branch, which was the assumption the three cards behind them
    happened to share. A land is what the fourth card names.
    """
    from engine.models import CardDefinition, Permanent

    island = Permanent(card=CardDefinition(
        name="Island", mana_cost="", cmc=0.0, type_line="Basic Land - Island",
        oracle_text="({T}: Add {U}.)", colors=(), color_identity=(), keywords=(),
        produced_mana=("U",), raw={"name": "Island", "type_line": "Basic Land - Island"},
    ))
    game, island = _blocked_board(
        "Islands don't untap during their controllers' untap steps.", island,
    )

    game.resolve_untap_step(0)

    assert island.tapped


# ---------------------------------------------------------------------------
# A restriction whose duration is a *state*: "...for as long as this creature
# remains tapped" (CR 611.2a/611.2b), the half CR 502.3 only says is possible.
# ---------------------------------------------------------------------------


def _lock_board():
    """A holder tapped and holding one permanent down, built through the
    handler's own record so the untap step reads exactly what a resolution
    would have written."""
    from engine import Game, PlayerState
    from engine.handlers.tapping import UNTAP_LOCK_WHILE_TAPPED_KEY
    from engine.models import CardDefinition, Permanent

    def _card(name, type_line, **raw):
        return CardDefinition(
            name=name, mana_cost="", cmc=0.0, type_line=type_line,
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=(),
            raw={"name": name, "type_line": type_line, **raw},
        )

    holder = Permanent(
        card=_card("Holder", "Creature - Gremlin", power="1", toughness="1")
    )
    held = Permanent(card=_card("Held", "Artifact"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[holder]),
        PlayerState(name="P2", battlefield=[held]),
    ])
    game._settle()
    holder.tapped = True
    held.tapped = True
    holder.metadata[UNTAP_LOCK_WHILE_TAPPED_KEY] = held.permanent_id
    return game, holder, held


@pytest.mark.cr("502.3", "611.2a")
def test_502_3_a_lock_holds_for_as_long_as_its_holder_stays_tapped():
    """The restriction is a state rather than a count of steps: it survives
    every untap step for as long as the holder is tapped."""
    game, _holder, held = _lock_board()

    game.resolve_untap_step(1)
    assert held.tapped
    game.resolve_untap_step(1)
    assert held.tapped


@pytest.mark.cr("611.2a", "611.2b")
def test_611_2_a_lock_ends_when_its_holder_untaps_and_does_not_resume():
    """"A continuous effect ... lasts as long as stated by the spell or ability
    creating it", and CR 611.2b's "it doesn't start and immediately stop again"
    settles the other direction: once the holder has untapped, the effect is
    over. Tapping that permanent again — an attack, another card's tap effect —
    does not put the restriction back, because nothing created a second one.

    Read back conditionally and never cleared, the record did exactly that for
    four sets: Phyrexian Gremlins re-locked its artifact every time it tapped.
    """
    game, holder, held = _lock_board()

    game.become_untapped(holder)
    game.resolve_untap_step(1)
    assert not held.tapped

    held.tapped = True
    game.become_tapped(holder)
    game.resolve_untap_step(1)

    assert not held.tapped, "an ended duration started again"


@pytest.mark.cr("611.2a")
def test_611_2_a_lock_ends_when_its_holder_leaves_the_battlefield():
    """The other way the condition stops holding. What comes back is a new
    object with none of the old one's records (CR 400.7), so there is nothing
    for a return to restart."""
    game, holder, held = _lock_board()

    game.remove_from_battlefield(holder)
    game._settle()
    game.resolve_untap_step(1)

    assert not held.tapped


# ---------------------------------------------------------------------------
# 614.1a over 502.3 — a replacement can take a permanent *out* of the untap
# ---------------------------------------------------------------------------


@pytest.mark.cr("614.1a")
@pytest.mark.cr("502.3")
def test_614_1a_a_replaced_untap_may_remove_the_permanent_from_the_battlefield():
    """A ``would_untap`` replacement that moves the permanent to a hand leaves
    the rest of the untap intact.

    Every other effect over this turn-based action keeps the permanent where it
    is: 502.3's own restrictions leave it tapped, and Freyalise's Winds spends a
    counter instead. This one is the first that makes the permanent *leave* -
    "During your next untap step, as you untap your permanents, return this land
    to its owner's hand" (Undiscovered Paradise) - and 502.3 says the active
    player untaps their permanents *simultaneously*, so one of them going has to
    leave the others untapping.

    Written with the marker stamped by hand rather than by activating the card:
    the claim is about the untap step, and a test that had to play a land first
    would pass or fail on that land instead.
    """
    from engine import Game, PlayerState
    from engine.card_loader import load_cards, manifest_set_path
    from engine.handlers.zones import RETURN_AT_NEXT_UNTAP_SEAT
    from engine.models import Permanent

    basics = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False

    kept = []
    for name in ("Forest", "Island", "Mountain"):
        permanent = Permanent(card=basics[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        game.become_tapped(permanent)
        kept.append(permanent)
    leaving = kept.pop(1)
    leaving.metadata[RETURN_AT_NEXT_UNTAP_SEAT] = 0

    game.turn = 3
    game.resolve_untap_step(0)

    assert [permanent.card.name for permanent in alice.battlefield] == [
        "Forest", "Mountain",
    ]
    assert all(not permanent.tapped for permanent in alice.battlefield), (
        "a permanent leaving mid-step must not stop the ones behind it untapping"
    )
    assert [card.name for card in alice.hand] == ["Island"]


@pytest.mark.cr("614.1a")
def test_614_1a_the_replaced_untap_marker_names_one_players_step():
    """"During **your** next untap step": the step the ability's controller
    takes, which is not automatically the one this permanent's current
    controller takes. An opponent's untap step is not the one the card named,
    so the marker waits."""
    from engine import Game, PlayerState
    from engine.card_loader import load_cards, manifest_set_path
    from engine.handlers.zones import RETURN_AT_NEXT_UNTAP_SEAT
    from engine.models import Permanent

    basics = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False

    theirs = Permanent(card=basics["Island"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    game.become_tapped(theirs)
    theirs.metadata[RETURN_AT_NEXT_UNTAP_SEAT] = 0

    game.turn = 3
    game.resolve_untap_step(1)

    assert [permanent.card.name for permanent in bob.battlefield] == ["Island"]
    assert theirs.tapped is False
    assert bob.hand == []
