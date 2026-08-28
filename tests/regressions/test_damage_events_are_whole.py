"""Two bugs that made a damage event less than a whole one.

Both were found by implementing The Dark and both live in the *shipped* pool,
which is the point worth keeping: `support_report.py` counts cards, and neither
of these cards was ever anything but "supported". A sweep that marks damage and
fires nothing, and a shield that answers for a card it was not pointed at, are
invisible to every count the repo keeps.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on


def _board(pool, *, mine, theirs=(), hand=(), lands=0, land="Mountain", life=20):
    my_lands = [Permanent(card=pool[land]) for _ in range(lands)]
    p1 = PlayerState(
        name="P1",
        battlefield=[*mine, *my_lands],
        hand=[pool[name] for name in hand],
        library=[pool[land]] * 10,
        life=life,
    )
    p2 = PlayerState(
        name="P2", battlefield=list(theirs), library=[pool[land]] * 10, life=life
    )
    game = Game(players=[p1, p2])
    game.start_turn(0)
    return game, p1, p2, my_lands


def _tap_all(game, player, lands):
    for land in lands:
        game.tap_land_for_mana(0, next(
            i for i, perm in enumerate(player.battlefield) if perm is land))


def test_a_mass_damage_sweep_fires_the_triggers_of_what_it_damages(catalog_by_name):
    """"Whenever this creature is dealt damage, put a +1/+1 counter on it."

    Fungusaur took its point from Earthquake and grew nothing, across five
    shipped sets. Marking damage is half a damage event; the other half is
    `_fire_dealt_damage_triggers`, and every sweep in `handlers/damage.py`
    reached for the lower call. CR 603.2 puts one trigger on the stack per
    creature dealt to, so the sweep fires per creature and the state-based
    kill still batches after it.
    """
    fungusaur = Permanent(card=catalog_by_name["Fungusaur"])
    game, p1, _, lands = _board(
        catalog_by_name, mine=[fungusaur], hand=["Earthquake"], lands=6)
    _tap_all(game, p1, lands)

    game.cast_from_hand(0, "Earthquake", x_value=1)
    game._settle()

    assert fungusaur.damage_marked == 1, game.log
    assert counters_on(fungusaur, "+1/+1") == 1, (
        "Earthquake dealt the damage but nothing triggered on it — the sweep "
        f"marked without firing. log: {game.log}"
    )


def test_a_named_source_shield_ignores_a_second_copy_of_that_card(catalog_by_name):
    """CR 615.8: the shield answers for the source that was *named*.

    `_match_chosen_damage_source` ended by comparing the two permanents' shared
    `CardDefinition`, so a Reverse Damage named on one Rod of Ruin also
    prevented — and gained life from — the other one's damage: 23 life where
    the card says 17. Its own docstring claimed identity matching the whole
    time. Same look-alike bug the control seam bans `list.index` for.
    """
    rod_named = Permanent(card=catalog_by_name["Rod of Ruin"])
    rod_other = Permanent(card=catalog_by_name["Rod of Ruin"])
    game, p1, _, lands = _board(
        catalog_by_name, mine=[], theirs=[rod_named, rod_other],
        hand=["Reverse Damage"], lands=3, land="Plains")
    _tap_all(game, p1, lands)

    game.cast_from_hand(
        0, "Reverse Damage", target_permanent_ids=[rod_named.permanent_id])
    game._settle()
    life_before = p1.life

    game._deal_damage_to_player(p1, 2, source=rod_other)
    game._settle()

    assert p1.life == life_before - 2, (
        "the shield was pointed at one Rod of Ruin and answered for the other "
        f"— it matched on the shared card rather than on identity. log: {game.log}"
    )


def test_the_shield_still_answers_for_the_source_it_was_pointed_at(catalog_by_name):
    """The other direction, so the fix above cannot be "match nothing".

    Written because the negative test alone passes for a shield that never
    fires at all, which is the failure a narrowing invites.
    """
    rod_named = Permanent(card=catalog_by_name["Rod of Ruin"])
    rod_other = Permanent(card=catalog_by_name["Rod of Ruin"])
    game, p1, _, lands = _board(
        catalog_by_name, mine=[], theirs=[rod_named, rod_other],
        hand=["Reverse Damage"], lands=3, land="Plains")
    _tap_all(game, p1, lands)

    game.cast_from_hand(
        0, "Reverse Damage", target_permanent_ids=[rod_named.permanent_id])
    game._settle()
    life_before = p1.life

    game._deal_damage_to_player(p1, 2, source=rod_named)
    game._settle()

    assert p1.life > life_before, (
        "the named Rod's damage should have been prevented and gained as life "
        f"(CR 615.8). log: {game.log}"
    )
