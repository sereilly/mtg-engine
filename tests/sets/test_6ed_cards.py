"""Classic Sixth Edition — the reprint set that is not quite one.

4ED and 5ED shipped without implementing a card: every one of their cards was
already in the pool, so `test_4ed_cards.py` has no per-card tests and says so.
6ED is the third set of that shape and the first where the shape is *almost*
true rather than true: 335 unique cards, of which **two** — Blaze and Regal
Unicorn — have no earlier printing here, because their earlier printing was in
Portal, a set `cards/manifest.json` does not carry.

"Almost" is the whole reason this file exists. Every conclusion drawn from a
reprint set's shape — no backlog, no new origins, an insert position no guard
can see — is silently wrong the day the premise moves, and the premise lives in
a Scryfall fetch nobody re-reads. So the premise is asserted here by name, in
both directions: exactly these two cards are new, and exactly these two
originate in 6ED.

The two new cards get per-card tests for the ordinary reason (SET_PLAYBOOK.md
Phase 3: every card lands with a focused test). Nothing else here does — a test
asserting that Air Elemental flies would be a sixth copy of one written for
Alpha, which is what `tests/sets/README.md` exists to prevent.
"""

from __future__ import annotations

import collections
import json

from engine import Game, PlayerState
from engine.card_loader import manifest_set_path, manifest_sets
from engine.cast_costs import cast_announces_x
from engine.models import Permanent
from engine.oracle import compile_card_oracle, simple_card_keywords
from engine.targeting import derive_cast_spec

from tests.helpers import resolve_stack

# The two cards 6ED brings to this pool. Named rather than derived, because a
# derived list would agree with whatever the card file happens to say and the
# point of the assertions below is to disagree with it when it changes.
NEW_TO_THE_POOL = ["Blaze", "Regal Unicorn"]


def _codes_before(code: str) -> list[str]:
    """The manifest is printing-ordered, so "earlier" is "further left"."""
    codes = [entry["code"] for entry in manifest_sets()]
    return codes[: codes.index(code)]


def _game(*players: PlayerState) -> Game:
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


# --- the set's relationship to the pool ---


def test_sixth_edition_brings_exactly_two_cards_the_pool_did_not_have(set_cards):
    """The premise everything else about this set rests on.

    A re-fetch that adds a third new card fails here rather than quietly making
    "6ED is a reprint set" false — and the reasoning that followed from it (no
    Phase 3 rounds, two verification rows, an insert position no card's origin
    depends on) would have to be redone rather than inherited.
    """
    earlier = {
        card.oracle_id
        for code in _codes_before("6ED")
        for card in set_cards(code)
        if card.oracle_id
    }
    novel = sorted(
        card.name for card in set_cards("6ED") if card.oracle_id not in earlier
    )
    assert novel == NEW_TO_THE_POOL, f"6ED cards with no earlier printing here: {novel}"


def test_the_set_is_335_unique_cards_from_351_printings(set_cards, catalog_by_name):
    """The census's two numbers differ, and the gap is the basic lands: five
    names printed with several arts each dedupe to five cards.

    Worth pinning for the reason 4ED's twin is: "351 vs 335" otherwise reads as
    sixteen cards going missing, and the dedupe happens in the loader, so the
    raw file is the only place the printing count is still visible.
    """
    raw = json.loads(manifest_set_path("6ED").read_text(encoding="utf-8"))
    assert len(raw) == 351
    assert len(set_cards("6ED")) == 335

    counts = collections.Counter(entry["name"] for entry in raw)
    repeated = sorted(name for name, n in counts.items() if n > 1)
    assert repeated == [
        "Drudge Skeletons", "Forest", "Island", "Mountain", "Plains", "Swamp",
    ]
    for name in repeated:
        assert catalog_by_name[name].original_printing != "6ed", (
            "a card printed twice inside 6ED is still a reprint of an earlier set"
        )


def test_only_the_two_new_cards_are_originally_printed_in_sixth_edition(
    set_cards, catalog_by_name
):
    """CR-visible consequence: "originally printed in" effects (City in a
    Bottle, Golgothian Sylex) read `printings[0]`, so which cards call 6ED home
    is not cosmetic.

    This does **not** check that 6ED sits at the right manifest index, and the
    difference is the one Stronghold paid for. Probed at the promotion by
    appending 6ED after M21 instead: this file, `test_card_format.py` and
    `test_appending_a_set_never_changes_an_existing_original_printing` all stay
    green, because no 6ED card has M21 as its only other printing and the two
    new ones read `6ed` from every position. Manifest order is asserted
    directly instead, in
    `test_manifest_roles.test_the_shipped_sets_are_in_printing_order`, which is
    where that probe did fail.
    """
    origins = {
        card.name: catalog_by_name[card.name].original_printing
        for card in set_cards("6ED")
    }
    assert sorted(name for name, o in origins.items() if o == "6ed") == NEW_TO_THE_POOL


def test_no_card_here_depends_on_the_manifest_index_for_its_origin(set_cards):
    """The measurement that makes the test above's self-check true, kept rather
    than inferred.

    A 6ED card whose *only* other printing were M21 would read `6ed` at index 22
    and `m21` appended after it — Mirage's Volcanic Geyser exactly, and
    Stronghold's Shock, where a set that looked immune had one card that was
    not. Today there are none, and every other 6ED card was printed in a set
    this manifest already carries, all of which are earlier. When that stops
    being true this fails, and the wrong-insert rehearsal stops being a
    formality for this set.
    """
    six = {card.oracle_id for card in set_cards("6ED")}
    elsewhere: dict[str, set[str]] = collections.defaultdict(set)
    for entry in manifest_sets():
        if entry["code"] == "6ED":
            continue
        for card in set_cards(entry["code"]):
            if card.oracle_id in six:
                elsewhere[card.oracle_id].add(entry["code"])

    position_dependent = sorted(
        card.name for card in set_cards("6ED") if elsewhere.get(card.oracle_id) == {"M21"}
    )
    assert not position_dependent, position_dependent


def test_promoting_the_set_actually_recorded_its_printings(set_cards, catalog_by_name):
    """The positive half, and the reason the origin test above means anything:
    "only two cards originate in 6ED" also passes if the set was never loaded.
    Every 6ED card must carry `6ed` in `printings` — that, and not its origin,
    is what promotion added for the other 333.
    """
    missing = sorted(
        card.name
        for card in set_cards("6ED")
        if "6ed" not in catalog_by_name[card.name].printings
    )
    assert not missing, f"6ED cards the catalog records no 6ed printing for: {missing}"


def test_every_card_ships_supported(set_cards, catalog_by_name):
    """What promotion claims. The pool-wide guards assert it of the catalog;
    this asserts it of the set, by name, so a card dropped from the catalog
    fails here rather than passing by absence.
    """
    unsupported = sorted(
        card.name
        for card in set_cards("6ED")
        if not compile_card_oracle(catalog_by_name[card.name]).supported
    )
    assert not unsupported, f"unsupported 6ED cards: {unsupported}"


# --- Blaze ---


def test_blaze_announces_x_and_asks_for_any_target(set_pool):
    """`{X}{R}` with "deals X damage to any target" is two announcements, and
    only one of them is a target.

    `cast_announces_x` is the single reader of "does this cast need an X?" — it
    exists because `web/static/app.js` used to answer by substring-probing the
    printed mana cost, which is one of the four places CR 107.3a names, so a
    card announcing X anywhere else was cast at the 0 an unmade CR 107.3a
    announcement reads as. Blaze
    announces it in the mana cost, which is the case that always worked; it is
    pinned here beside the picker because the two answers together are what the
    client needs to offer the cast at all.
    """
    blaze = set_pool("6ED")["Blaze"]
    program = compile_card_oracle(blaze)

    assert cast_announces_x(blaze)
    assert derive_cast_spec(blaze, program) == {"kind": "any"}
    assert [i.kind for i in program.instructions] == ["deal_damage"]
    assert program.instructions[0].payload["amount"] == "x"


def test_blaze_deals_the_announced_x_to_a_creature(set_pool):
    """X is the announced value, not the printed one — there is no printed one.

    Aimed at a creature rather than a face because the two travel different
    paths through `deal_damage`, and the creature path is the one where the
    damage has to be marked rather than subtracted.
    """
    pool = set_pool("6ED")
    caster, victim = PlayerState(name="A"), PlayerState(name="B")
    game = _game(caster, victim)
    bear = Permanent(card=pool["Grizzly Bears"])
    victim.battlefield.append(bear)
    caster.hand.append(pool["Blaze"])

    assert game.cast_from_hand(
        0, "Blaze", x_value=3, target_player_index=1, target_permanent_index=0
    ).supported
    resolve_stack(game)

    assert bear not in victim.battlefield, "a 2/2 taking 3 damage dies"


def test_blaze_deals_the_announced_x_to_a_player(set_pool):
    """The other half of "any target" (CR 115.4). Cast for X=0 as well, because
    The 0 an unmade CR 107.3a announcement reads as is the value a client that
    never asked would send, and
    "deals 0 damage" must not be a damage event that heals or crashes.
    """
    pool = set_pool("6ED")
    caster, victim = PlayerState(name="A"), PlayerState(name="B")
    game = _game(caster, victim)
    caster.hand.append(pool["Blaze"])
    caster.hand.append(pool["Blaze"])

    assert game.cast_from_hand(0, "Blaze", x_value=5, target_player_index=1).supported
    resolve_stack(game)
    assert victim.life == 15

    assert game.cast_from_hand(0, "Blaze", x_value=0, target_player_index=1).supported
    resolve_stack(game)
    assert victim.life == 15, "X=0 is a legal announcement that deals nothing"


# --- Regal Unicorn ---


def test_regal_unicorn_is_a_vanilla_two_three(set_pool):
    """A vanilla creature's test is that it *is* vanilla.

    This is not padding: `simple_card_keywords` is what decides a card is
    auto-passed in `CARD_VERIFICATION.md` — no abilities means the only paths it
    exercises are the generic combat code plus its printed numbers, so a manual
    check would exercise nothing card-specific. That claim is exactly as strong
    as the emptiness of its text, and this is the card that makes the claim for
    it. If a re-fetch ever gives Regal Unicorn an ability, its verification row
    silently becomes a pass nobody performed.
    """
    unicorn = set_pool("6ED")["Regal Unicorn"]
    program = compile_card_oracle(unicorn)

    assert unicorn.oracle_text.strip() == ""
    assert list(simple_card_keywords(unicorn)) == []
    assert program.supported
    assert not program.instructions
    assert not program.activated_abilities
    assert not program.triggered_abilities
    assert (unicorn.power, unicorn.toughness) == ("2", "3")


def test_regal_unicorn_fights_as_its_printed_numbers(set_pool):
    """And the generic damage code the auto-pass defers to, run once for this
    card, so "no abilities" is a statement about a creature that has been in a
    game rather than one that has only been compiled.

    Through `_mark_damage_on_permanent` rather than `damage_events.deal_damage`,
    because that seam deliberately does **not** apply the result — CR 120.4's
    two halves are separate and "apply" means life loss for a player and marked
    damage for a permanent, so a test calling the shared half alone reads
    `dealt == 2` beside `damage_marked == 0` and proves nothing about lethality.
    """
    pool = set_pool("6ED")
    unicorn = Permanent(card=pool["Regal Unicorn"])
    bear = Permanent(card=pool["Grizzly Bears"])
    game = _game(
        PlayerState(name="A", battlefield=[bear]),
        PlayerState(name="B", battlefield=[unicorn]),
    )

    assert game._mark_damage_on_permanent(unicorn, 2, source=bear) == 2
    game.check_state_based_actions()
    assert unicorn in game.players[1].battlefield, "a 2/3 survives 2 damage"

    assert game._mark_damage_on_permanent(unicorn, 1, source=bear) == 1
    game.check_state_based_actions()
    assert unicorn not in game.players[1].battlefield, (
        "3 marked damage on a 2/3 is lethal (CR 704.5g)"
    )
