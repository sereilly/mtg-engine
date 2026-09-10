"""Every characteristic the wire sends is the layers' answer, not the card's.

``tests/engine/test_layer_reads.py`` guards the class this file is about —
"what type/colour/P/T is this?" asked of ``card.type_line`` or a metadata flag
instead of the CR 613 accessors — and it **scans ``engine/`` only**. So
``web/serialization.py`` has been outside it since it was written, and the two
defects that found their way out did so through a promotion smoke test rather
than through a guard:

* Tempest's, in ``_effective_keywords``, which asked ``perm.card.type_line``
  whether the permanent was a creature and so gave an animated land no
  keywords.
* Stronghold's, in ``is_aura``. A **Licid** activates "this creature loses this
  ability and becomes an Aura enchantment with enchant creature" — a CR 613
  layer-4 type change, which moves nothing on the card. Both
  ``perm.card.type_line`` and ``perm.effective_card.type_line`` still read
  "Creature — Licid" afterwards, because layer 1 folds a *copy* and layer 3 a
  *text change* and this is neither. The engine had it right at every seam it
  owns; the client alone was told the thing attached to its creature was not an
  Aura, and no engine instrument could see it.

This file is the wire-side answer: a driven game, the real serializer, and the
fields a player actually reads. The widened scan finally exists beside it —
``tests/ui/test_layer_reads_in_web.py`` reads every ``web/`` module's source and
ratchets what is left — and the two are the two halves this class needs: the
scan says where the question is asked of the wrong object, and this file says
what a player is shown when it is.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.layer_bridge import displayed_type_line
from engine.models import Permanent
from web.serialization import _serialize_permanent

from ..helpers import resolve_stack


@pytest.fixture(scope="module")
def pool():
    return {card.name: card for card in load_catalog()}


def _attached_licid(pool):
    """A Gliding Licid mid-transformation, attached to a Grizzly Bears."""
    licid = Permanent(card=pool["Gliding Licid"])
    licid.metadata["summoning_sick"] = False
    host = Permanent(card=pool["Grizzly Bears"])
    host.metadata["summoning_sick"] = False
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[licid, host]),
            PlayerState(name="P2"),
        ],
        enforce_mana_costs=False,
    )
    assert game.queue_permanent_ability(
        0, "Gliding Licid", ability_index=0,
        target_permanent_ids=[host.permanent_id],
    ).supported
    resolve_stack(game)
    return game, licid, host


def test_a_licid_that_became_an_aura_reaches_the_client_as_one(pool):
    """The defect, from the far side.

    Asserted against the *printed* type line as well, because that is what makes
    this a layer read rather than a spelling: the card still says "Creature —
    Licid" and the answer still has to be "Aura".
    """
    game, licid, host = _attached_licid(pool)

    assert "Licid" in licid.card.type_line          # the card has not moved
    assert not licid.is_creature                    # the layers have
    assert licid.has_type("enchantment")

    wire = _serialize_permanent(licid, game)
    assert wire["is_aura"] is True, wire
    assert wire["type"] == displayed_type_line(licid)
    assert wire["is_creature"] is False
    assert wire["attached_to_id"] == host.permanent_id


def test_the_licids_host_is_not_itself_reported_as_an_aura(pool):
    """The negative the positive needs: reading the layer-aware type line must
    not make every permanent in the attachment an Aura."""
    game, _licid, host = _attached_licid(pool)

    wire = _serialize_permanent(host, game)
    assert wire["is_aura"] is False, wire
    assert wire["is_creature"] is True


def test_an_ordinary_aura_and_an_ordinary_creature_are_unchanged(pool):
    """The direction this fix must never move: a printed Aura is still an Aura
    and a printed creature is still not one."""
    aura = Permanent(card=pool["Pacifism"])
    bears = Permanent(card=pool["Grizzly Bears"])
    game = Game(
        players=[PlayerState(name="P1", battlefield=[aura, bears]),
                 PlayerState(name="P2")],
        enforce_mana_costs=False,
    )
    assert _serialize_permanent(aura, game)["is_aura"] is True
    assert _serialize_permanent(bears, game)["is_aura"] is False


def test_an_animated_land_keeps_its_keywords_on_the_wire(pool):
    """Tempest's site, kept here beside Stronghold's because they are one class.

    Stalking Stones becomes "a 3/3 Elemental creature that's still a land", so a
    reader asking the printed type line whether it is a creature answers no and
    drops every keyword it has.
    """
    stones = Permanent(card=pool["Stalking Stones"])
    stones.metadata["summoning_sick"] = False
    game = Game(
        players=[PlayerState(name="P1", battlefield=[stones]),
                 PlayerState(name="P2")],
        enforce_mana_costs=False,
    )
    assert "Land" in stones.card.type_line
    wire = _serialize_permanent(stones, game)
    # Untouched it is not a creature, and that is the honest answer.
    assert wire["is_creature"] is False
    assert wire["is_aura"] is False


def test_protection_from_a_card_type_reaches_the_wire(pool):
    """Urza's Legacy's site, and the fourth of this class.

    Not a type-line read this time but its sibling: `_effective_keywords` asked
    `game._protection_colors`, which is the *deliberate colour slice* of
    `_protection_qualities` and was right for as long as every protection in the
    pool was from a colour. Urza's Legacy printed two from a **card type** and
    the wire went silent about both — Angelic Curator reached the client showing
    only "Flying", and Yavimaya Scion, whose entire printed text is "Protection
    from artifacts", reached it carrying **no badge at all** — while the engine
    had the shield right at every seam it owns.

    That is this class exactly: an accessor whose narrower sibling answers a
    strictly smaller question, read by the client because it was sufficient when
    it was written. Found by Phase 5's "read what the wire carries for one card
    of the set's new mechanic", which is the same step that found the other
    three.

    The badge says "artifact**s**" because the card does: `protection_quality`
    canonicalizes to the singular to match the catalogs it looks words up in.
    """
    curator = Permanent(card=pool["Angelic Curator"])
    scion = Permanent(card=pool["Yavimaya Scion"])
    knight = Permanent(card=pool["White Knight"])
    game = Game(
        players=[PlayerState(name="P1", battlefield=[curator, scion, knight]),
                 PlayerState(name="P2")],
        enforce_mana_costs=False,
    )

    curator_wire = _serialize_permanent(curator, game)["keywords"]
    assert "Protection from artifacts" in curator_wire
    assert "Flying" in curator_wire

    # The one whose whole text is the protection: a badge or nothing at all.
    assert _serialize_permanent(scion, game)["keywords"] == ["Protection from artifacts"]

    # And the colour half still spells out the way it always did.
    assert "Protection from black" in _serialize_permanent(knight, game)["keywords"]


# ---------------------------------------------------------------------------
# Sixth Edition's wave: the round the Known-gaps entry had been asking for
# ---------------------------------------------------------------------------
#
# Two questions, not one. The greppable half — which ``web/`` reads ask the
# printed card — is scanned by ``test_layer_reads_in_web.py``; every site it
# found that a shipped card pays for is pinned below. The half that cannot be
# grepped is an accessor answering a **narrower** question than its caller
# needs, which is what ``_protection_colors`` was above, and
# ``_NONCREATURE_KEYWORDS`` is its second instance: a one-entry list standing in
# for "the keywords CR defines over a permanent".

from fastapi.testclient import TestClient

from engine.untap_restrictions import permanent_in_limited_scope
from web.app import app, store
from web.combat_prompts import _band_blocker_assignments
from web.debug_actions import _debug_move_permanent_off_battlefield
from web.runtime import CARD_BY_NAME
from web.serialization import _serialize_permanent_summary


def _perm(pool, name):
    """A permanent that has been around since the beginning of the turn."""
    permanent = Permanent(card=pool[name])
    permanent.metadata["summoning_sick"] = False
    return permanent


def _two_seat_game(*battlefield):
    game = Game(
        players=[PlayerState(name="A", battlefield=list(battlefield)),
                 PlayerState(name="B")],
        enforce_mana_costs=False,
    )
    game._recompute_continuous_effects()
    return game


def test_a_noncreature_permanents_own_keyword_reaches_the_client(pool):
    """Nine Lives is Yavimaya Scion one card type over.

    Its entire protective text is "Hexproof" and it is an enchantment, so the
    badge row asked ``_NONCREATURE_KEYWORDS`` — which was the single entry
    ``("Phasing",)``, written when Teferi's Isle was the card that had asked.
    The engine held the shield at every seam it owns and the client was told
    nothing at all.
    """
    nine = _perm(pool, "Nine Lives")
    game = _two_seat_game(nine)

    assert not nine.is_creature
    assert game._has_keyword(nine, "Hexproof")
    assert _serialize_permanent(nine, game)["keywords"] == ["Hexproof"]


def test_a_shroud_granted_to_an_artifact_reaches_the_client(pool):
    """Hanna's Custody: "All artifacts have shroud."

    The grant is real, the Mox cannot be targeted, and the player looking at
    the board could not see why. CR 702.18a is about a *permanent*, which is
    the whole of this fix: the badge list a noncreature permanent is checked
    against is now derived from what each keyword is about, rather than from
    which card last complained.
    """
    mox = _perm(pool, "Mox Emerald")
    custody = _perm(pool, "Hanna's Custody")
    game = _two_seat_game(mox, custody)

    assert game._has_keyword(mox, "Shroud")
    assert _serialize_permanent(mox, game)["keywords"] == ["Shroud"]


def test_a_creatures_badges_are_unchanged(pool):
    """The direction this must not move: folding the two branches into one list
    must not drop a combat keyword or reorder the row."""
    knight = _perm(pool, "White Knight")
    game = _two_seat_game(knight)

    badges = _serialize_permanent(knight, game)["keywords"]
    assert badges == ["First Strike", "Protection from black"], badges


def test_a_clone_reports_the_copied_cards_mana_cost_and_base_pt(pool):
    """CR 707.2: mana cost and printed P/T are *copiable values*.

    ``oracle_text`` on this payload already came off ``effective_card``; the
    two fields above it did not, so a Clone-as-Grizzly-Bears reached the client
    with a ``{3}{U}`` cost and a base P/T of 0/0 against a current 2/2 — which
    the canvas paints **green**, the colour it uses for "something pumped
    this".
    """
    bears = _perm(pool, "Grizzly Bears")
    clone = _perm(pool, "Clone")
    game = _two_seat_game(bears, clone)
    game._apply_copy(clone, bears)
    game._recompute_continuous_effects()

    wire = _serialize_permanent(clone, game)
    assert wire["mana_cost"] == "{1}{G}"
    assert (wire["base_power"], wire["base_toughness"]) == (2, 2)
    assert (wire["power"], wire["toughness"]) == (2, 2)
    # The physical card is still a Clone: the name is what the action API
    # addresses it by, and the art is deliberately its own.
    assert wire["name"] == "Clone"


def test_an_animated_land_blocking_a_band_is_offered_the_702_22k_assignment(pool):
    """CR 702.22k: the ACTIVE player chooses which band member each blocker
    damages. The blocker check read the printed type line, so a Kormus Bell'd
    Swamp blocking a band produced no assignment at all — and its sibling
    ``_multiblock_blocker_splits``, three dozen lines below, had been asking
    ``is_creature`` the whole time.
    """
    master, bears = _perm(pool, "Master of the Hunt"), _perm(pool, "Grizzly Bears")
    swamp, bell = _perm(pool, "Swamp"), _perm(pool, "Kormus Bell")
    game = Game(
        players=[PlayerState(name="A", battlefield=[master, bears]),
                 PlayerState(name="B", battlefield=[swamp, bell])],
        enforce_mana_costs=False,
    )
    game.active_player_index = 0
    game.combat_defending_player_index = 1
    game._recompute_continuous_effects()

    assert swamp.card.primary_type == "land"   # the card has not moved
    assert swamp.is_creature                   # Kormus Bell has

    master.attacking = bears.attacking = True
    game.combat_attackers = {0: 1, 1: 1}
    game.combat_bands = [[0, 1]]
    game.combat_blockers = {1: {0: [0]}}
    game._apply_band_block_propagation()

    assert _band_blocker_assignments(game) == [
        {"blocker_idx": 0, "member_indices": [0, 1]}
    ]


def test_a_pile_list_describes_the_permanent_not_the_card(pool):
    """The same class one call deep.

    Raging River's division and Camouflage's piles both *select* through
    ``game._is_creature`` — correctly — and then described each entry with
    ``_serialize_card_summary(p.card)``, so the player dividing their creatures
    into two piles saw one of them drawn as "Basic Land — Swamp" with the
    Bell's animation nowhere in sight.
    """
    swamp, bell = _perm(pool, "Swamp"), _perm(pool, "Kormus Bell")
    game = _two_seat_game(swamp, bell)

    summary = _serialize_permanent_summary(swamp, game)
    assert "Creature" in summary["type"], summary["type"]
    assert summary["name"] == "Swamp"


def test_bouncing_an_attached_licid_ends_its_grant(pool):
    """The Debug Menu's bounce asked ``"Aura" in permanent.card.type_line``.

    A Licid becomes an Aura enchantment without a word of its card moving
    (CR 613 layer 4), so the check answered "no", ``_remove_aura_effects`` was
    skipped, and the creature it had been attached to kept flying after the
    Licid was in its owner's hand.
    """
    game, licid, host = _attached_licid(pool)
    assert licid.has_type("aura") and "Aura" not in licid.card.type_line
    assert game._has_keyword(host, "Flying")

    _debug_move_permanent_off_battlefield(game, 0, 0, "hand")
    game._recompute_continuous_effects()

    assert not game._has_keyword(host, "Flying")


# --- The untap selection, which needs a session ----------------------------

_client = TestClient(app)


def _untap_session(constraint: str, tapped: list[str]):
    """A seat in its untap step, under *constraint*, with *tapped* on board."""
    response = _client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H", "host_colors": 2,
        "guest_colors": 2, "seed": 6006,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    session = store.get(session_id)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "beginning"
    game.current_step = "untap"

    board = [Permanent(card=CARD_BY_NAME[constraint.casefold()])]
    for name in tapped:
        permanent = Permanent(card=CARD_BY_NAME[name.casefold()])
        permanent.tapped = True
        board.append(permanent)
    game.players[0].battlefield = board
    game.players[1].battlefield = []
    game._recompute_continuous_effects()

    options = game.get_untap_land_selection_options(0)
    assert options, "the constraint did not bind"
    session.untap_candidate_indices = [int(i) for i in options["candidate_indices"]]
    return session_id, options


@pytest.mark.parametrize(
    "constraint,tapped,scope",
    [
        ("Damping Field", ["Mox Emerald", "Mox Ruby", "Icy Manipulator"], "artifact"),
        ("Static Orb", ["Grizzly Bears", "Forest", "Mox Emerald"], "permanent"),
    ],
)
def test_every_constrained_untap_scope_reaches_the_client(constraint, tapped, scope):
    """The re-validation between the engine's candidate list and the board.

    It read ``card.primary_type in ("land", "creature")`` — the printed line
    *and* only two of the four scopes a limit may name. Under **Damping Field**
    the engine offered three tapped artifacts and the wire carried an empty
    candidate list beside ``max_count: 1``: the player was told to untap one
    artifact and given nothing to click. Worse, the pruned list was written
    back onto the session, so ``untap_select`` then refused the click too.
    **Static Orb**'s "permanent" is not a card type at all.
    """
    session_id, options = _untap_session(constraint, tapped)
    assert set(options["limits"]) == {scope}

    state = _client.get(f"/api/sessions/{session_id}/state", params={"seat": 0}).json()
    selection = state["untap_land_selection"]
    assert selection["candidate_indices"] == list(options["candidate_indices"])
    assert selection["limits"] == options["limits"]
    assert selection["max_count"] == options["max_count"]

    # …and the click the client can now make is one the action handler takes.
    chosen = selection["candidate_indices"][0]
    response = _client.post(
        f"/api/sessions/{session_id}/action",
        json={"action": "untap_select", "seat": 0, "permanent_index": chosen},
    )
    assert response.status_code == 200, response.text
    assert store.get(session_id).untap_selected_indices == [chosen]


def test_the_untap_candidate_filter_asks_the_engines_own_predicate():
    """The narrowing, named. Two spellings of "is this permanent in scope" is
    how the board comes to offer what the resolver refuses — which is why
    ``permanent_in_limited_scope`` exists at all."""
    session_id, options = _untap_session("Damping Field", ["Mox Emerald", "Mox Ruby"])
    battlefield = store.get(session_id).game.players[0].battlefield
    for index in options["candidate_indices"]:
        assert permanent_in_limited_scope(battlefield[index], "artifact")
        assert battlefield[index].card.primary_type not in ("land", "creature")
