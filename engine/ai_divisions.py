"""How the AI divides: a divided spell's targets and shares (CR 601.2d), and
counters divided among creatures.

:func:`choose_divided_targets` is the announcement for a spell that divides
an amount among its targets — which targets, one pick per printed slot from
the board that slot names, and each one's share — or None for a card that
divides nothing. :func:`divided_shrink_shares` and
:func:`least_harmed_permanent` are the two halves of a toughness-lowering
division a seat nobody asks makes: counters spread where a share kills
first, or the creature they would hurt least.

What a divided spell divides — its shape — is the compiled program's
(``ai_target_sides.divided_shape``).
"""

from __future__ import annotations

from .ai_target_sides import divided_shape
from .divided_damage import EACH, spread_shares
from .game import Game
from .models import CardDefinition
from .oracle import compile_card_oracle
from .targeting import instructions_as_announced
from .ai_actions import _OFFERS_ANNOUNCED, _announced_mode, _cast_zone


def _even_shares(total: int, count: int) -> list[int]:
    """*total* split *count* ways, remainder to the earliest.

    CR 601.2d wants every target to receive at least one, so the remainder is
    spread rather than dropped — the same starting division
    ``evenStartingDivision`` offers a human in the browser, which is where this
    arithmetic already lived. One arithmetic with a divided trigger's default
    (``divided_damage.spread_shares``).
    """
    return spread_shares(total, count)


def choose_divided_targets(
    game: Game, caster_index: int, card: CardDefinition, x_value: int | None = None
):
    """CR 601.2d's announcement for a divided spell: which targets, and each
    one's share.

    Returns None when *card* divides nothing — every other card in the pool —
    and ``()`` when it divides and no legal announcement exists, which is a
    refusal rather than an absence, the same way ``ai_targets._choose_role_targets``
    answers: CR 601.2d needs one target or more, and the cast gate refuses a
    spell announced with none, so proposing it would be a turn spent on an
    action the game then rejects.

    **Which board the shares land on is derived, never named**:
    ``ai_target_sides.divided_shape`` reads the sign of the counter the compiled
    program places, so Bounty of the Hunt's ``+1/+1`` goes on the caster's own
    creatures and Contagion's ``-2/-1`` on the opponent's, and a card printed
    tomorrow with either template is aimed correctly the day it is ingested.

    Three stated policies sit on top of that, and only the first is forced:

    * **Damage concentrates.** A share is measured against a toughness, so four
      damage split one apiece kills nothing; the whole total goes on the first
      candidate the enumeration offers, which is a player's face where the
      printed noun admits one. That is exactly what the engine's older
      single-target path already did for Fireball, so the four "any target"
      burn spells keep the play they had and gain only a lawful announcement.
    * **Counters spread**, as far as the total and the printed target count
      allow — every counter placed is a counter either way, and Contagion and
      Bounty of the Hunt print a target count precisely because spreading is
      the point of them.
    * **A whole-board division takes the whole board** — "…among all creatures
      target opponent controls" (Dwarven Catapult) chooses nothing, so every
      candidate on the named side is announced and the even split does the rest.

    And one that is not a policy at all: **an "each of up to N targets" list
    is filled** (Shower of Coals). Nothing there is divided — every target
    takes the whole printed amount (``divided_damage.EACH``) — so the reason
    damage concentrates does not apply to it, and a slot left unnamed is
    damage the card printed and nobody received.
    """
    program = compile_card_oracle(card)
    # The candidate being built's own answer to CR 601.2b (`_OFFERS_ANNOUNCED`):
    # which step divides, and over how many targets, may turn on it. A kicked
    # Magma Burst divides over two where the unkicked one names a single target
    # the ordinary way, and Pollen Remedy's shares total 3 or 6 (CR 702.33g).
    # Read off the card's every arm, neither has a divided step this could find
    # — both keep it under a `was_kicked` arm — so both were proposed with one
    # bare target and refused.
    offers = _OFFERS_ANNOUNCED.get()
    # ...and its mode (`_announced_mode`): a division printed in one bullet is
    # a division only of a cast that chose it, and the game's spec for a modal
    # card asked with no mode is "modal" — no division to read at all.
    mode_index = _announced_mode(card)
    shape = divided_shape(
        program,
        instructions_as_announced(card, program, offers or {}, mode_index=mode_index),
    )
    if shape is None:
        return None
    spec = game.cast_target_spec(
        caster_index, card, optional_cost_payments=offers, mode_index=mode_index,
        from_zone=_cast_zone(card),
    )
    if spec.get("kind") != "divided":
        # A modal or otherwise re-derived spec that does not describe the
        # division. Nothing to announce, and the cast gate reads the same spec.
        return None
    total = _divided_announcement_total(spec, x_value)
    candidates = [
        entry for entry in (spec.get("valid_targets") or ())
        if _divided_candidate_seat(entry) is not None
    ]
    wanted = [
        entry for entry in candidates
        if shape.side is None
        or (_divided_candidate_seat(entry) == caster_index) == (shape.side == "you")
    ] or candidates
    if not wanted or total <= 0:
        # No legal target, or nothing to divide (Spoils of War with an empty
        # opponent graveyard defines X as 0). Either way there is no lawful
        # announcement, and CR 601.2e would return the game to before the cast.
        return ()
    # "…to **each of X targets**" (Firestorm) / "…and 3 damage to **a third
    # target**" (Cone of Flame). The card prints how many, so an announcement of
    # any other length is refused at the cast (CR 601.2c) — and a policy that
    # proposed one anyway would spend every turn on a cast the engine rejects,
    # which is exactly what ``refused_casts`` is the honesty check for. A board
    # too small to fill the count is no legal announcement at all, which is what
    # `()` means here.
    exact = _card_divided_target_count(spec, x_value)
    if exact is not None and len(shape.slot_sides) == exact:
        # The targets are not interchangeable (Captain's Maneuver: the first is
        # spared, the second takes the damage), so each is taken from the board
        # its own slot names — `ai_target_sides.DividedShape.slot_sides`. Which
        # candidate on that board is this module's weight, and it is the one
        # every divided spell has: the first the enumeration offers, a player's
        # face where the printed noun admits one. So the caster's own face is
        # what is spared and an opponent's is where the damage goes.
        picked = _divided_slot_picks(candidates, shape.slot_sides, caster_index)
        return [] if picked is None else [
            (entry["seat"], entry.get("index")) for entry in picked
        ]
    if exact is not None:
        return (
            [] if len(wanted) < exact
            else [(entry["seat"], entry.get("index")) for entry in wanted[:exact]]
        )
    ceiling = spec.get("max_targets")
    if spec.get("division") == EACH and isinstance(ceiling, int):
        # "…deals 2 damage to **each of up to three targets**" (Shower of
        # Coals, the pool's first EACH list under a ceiling rather than a
        # printed count — Firestorm and Magma Burst print how many, and are
        # answered by `exact` above). It reached the threshold arm below and
        # named one target of its three, which is a third of the card: a share
        # is measured against a toughness only where there is a share.
        return [
            (entry["seat"], entry.get("index")) for entry in wanted[:max(1, ceiling)]
        ]
    if shape.whole_board:
        chosen = wanted
    elif shape.thresholded:
        chosen = wanted[:1]
    else:
        maximum = spec.get("max_targets")
        room = total if not isinstance(maximum, int) else min(maximum, total)
        chosen = wanted[:max(1, room)]
    shares = _even_shares(total, len(chosen))
    announced = spec.get("division") == "chosen"
    return [
        # A two-tuple where the card divides *evenly*: CR 601.2d asks for an
        # announcement only from a caster who chooses the division, and
        # `division_refusal` refuses shares announced for a spell that does not.
        (entry["seat"], entry.get("index")) if not announced
        else (entry["seat"], entry.get("index"), share)
        for entry, share in zip(chosen, shares)
    ]


def _divided_slot_picks(candidates, slot_sides, caster_index: int):
    """One enumerated target per printed slot, each from the board its slot
    names ("you" the caster's, "opponent" anybody else's, None either), no
    target twice — or None when some slot has nothing to name, which is no
    legal announcement (CR 601.2c) rather than one to fill from the wrong
    board."""
    picked: list = []
    for side in slot_sides:
        offered = [
            entry for entry in candidates
            if not any(entry is taken for taken in picked)
            and (
                side is None
                or (_divided_candidate_seat(entry) == caster_index) == (side == "you")
            )
        ]
        if not offered:
            return None
        picked.append(offered[0])
    return picked


def _card_divided_target_count(spec: dict, x_value: int | None) -> int | None:
    """How many targets a card-dictated division prints, or None.

    None for every divided spell whose count the caster chooses, which is every
    one in the pool before Weatherlight — so the caller may ask unconditionally.

    The two spellings the description carries: a printed number, and the string
    ``"x"`` for a count announced under CR 107.3a. The policy has just chosen
    that X, so it is the value passed in — the same number
    ``casting._card_divided_target_count`` will read off the announcement, which
    is what keeps the proposal and the gate counting the same thing.
    """
    printed = spec.get("divided_target_count")
    if isinstance(printed, bool) or printed is None:
        return None
    if isinstance(printed, int):
        return printed
    return max(0, int(x_value or 0)) if printed == "x" else None


def _divided_candidate_seat(entry) -> int | None:
    """The seat one enumerated divided target sits on, or None if the entry is
    neither a permanent nor a player's face."""
    if not isinstance(entry, dict) or entry.get("kind") not in ("permanent", "player"):
        return None
    seat = entry.get("seat")
    return seat if isinstance(seat, int) else None


def _divided_announcement_total(spec: dict, x_value: int | None) -> int:
    """How much a divided spell has to divide, once X is known.

    The browser's ``dividedDivisionTotal`` in the terms this side speaks: the
    printed amount where the card prints one, the game's number where the card
    defines its own X (CR 107.3c — Spoils of War counts a graveyard, and the
    caster never announces it), and otherwise whatever X the policy picked.
    """
    bonus = int(spec.get("division_x_bonus") or 0)
    if isinstance(spec.get("division_total"), int):
        return spec["division_total"] + bonus
    if isinstance(spec.get("defined_x"), int):
        return spec["defined_x"] + bonus
    return int(x_value or 0) + bonus


def _counters_to_kill(game: Game, permanent, step: int) -> int:
    """How many counters lowering toughness by *step* apiece leave *permanent*
    with lethal damage or no toughness (CR 704.5f/g), read through the layers."""
    left = max(1, int(permanent.effective_toughness) - int(permanent.damage_marked or 0))
    return -(-left // step)


def divided_shrink_shares(
    game: Game, permanent_ids, total: int, ceiling: int, counter: str,
) -> "list[tuple[int, int]] | None":
    """A division of *total* counters that **lower toughness** among the
    creatures *permanent_ids* names — the ones a share can kill first — as
    ``(permanent_id, share)`` pairs, or None where the counter lowers no
    toughness or no share would kill anything.

    "When this creature dies, distribute three -1/-1 counters among one, two,
    or three target creatures. For each -1/-1 counter you put on a creature
    this way, remove a -1/-1 counter from that creature at the beginning of
    the next end step." (Shambling Swarm). Its counters come back off, so a
    share is worth what it kills, which is CR 601.2d's split measured against
    a toughness — the reason a divided spell's *damage* is concentrated. The
    spread a seat nobody asks gave it (one apiece over the first three
    creatures the offer listed) killed a Llanowar Elves where 1 + 2 kills the
    Elves and a Grizzly Bears, and over a Hill Giant, a Craw Wurm, the Bears
    and the Elves — in that order — it killed nothing at all.

    So: fewest counters to kill first (the one worth more, then the offer's
    order, breaking ties), each given exactly its lethal share while the total
    and the printed ceiling allow; what is left goes one apiece on creatures
    not yet named while the ceiling has room — each still shrinks — and the
    rest on the last named. Every share is at least one and the shares total
    *total* (CR 601.2d).
    """
    step = _toughness_step(counter)
    if step <= 0 or total <= 0 or ceiling <= 0:
        return None
    ranked = sorted(_shrink_ranking(game, permanent_ids, step))
    shares: list[list[int]] = []
    left = int(total)
    for needed, _worth, _position, permanent_id in ranked:
        if len(shares) >= ceiling:
            break
        if needed <= left:
            shares.append([permanent_id, needed])
            left -= needed
    if not shares:
        return None
    named = {permanent_id for permanent_id, _share in shares}
    for _needed, _worth, _position, permanent_id in ranked:
        if left <= 0 or len(shares) >= ceiling:
            break
        if permanent_id not in named:
            shares.append([permanent_id, 1])
            named.add(permanent_id)
            left -= 1
    shares[-1][1] += left
    return [(permanent_id, share) for permanent_id, share in shares]


def least_harmed_permanent(
    game: Game, permanent_ids, total: int, counter: str,
) -> "int | None":
    """Of *permanent_ids*, the one *total* counters of kind *counter* would
    hurt least, or None where the counter lowers no toughness.

    The other half of :func:`divided_shrink_shares`: a toughness-lowering
    division with nothing on the side it wants still owes its target
    (CR 603.3d), on its controller's own board, and there the whole total
    goes on one creature. One that survives it if there is one (the
    sturdiest); otherwise the one worth least
    (``ai_rehearsal.permanent_worth``). The offer's first was a Savannah
    Lions, killed beside a Hill Giant that would have lived through it.
    """
    step = _toughness_step(counter)
    if step <= 0:
        return None
    ranked = list(_shrink_ranking(game, permanent_ids, step))
    if not ranked:
        return None
    survivors = [entry for entry in ranked if entry[0] > total]
    if survivors:
        return max(survivors, key=lambda entry: (entry[0], -entry[2]))[3]
    return min(ranked, key=lambda entry: (-entry[1], entry[2]))[3]


def _toughness_step(counter: str) -> int:
    """How much toughness one *counter* takes away (CR 122.1a), 0 for none."""
    from .pt import pt_counter_deltas

    deltas = pt_counter_deltas(str(counter or ""))
    return -deltas[1] if deltas is not None else 0


def _shrink_ranking(game: Game, permanent_ids, step: int):
    """``(counters to kill, -worth, offer position, permanent_id)`` for each
    of *permanent_ids* still on the battlefield."""
    from .ai_rehearsal import permanent_worth

    for position, permanent_id in enumerate(permanent_ids):
        permanent = game.permanent_by_id(permanent_id)
        if permanent is not None:
            yield (
                _counters_to_kill(game, permanent, step),
                -permanent_worth(permanent, now=False),
                position,
                permanent_id,
            )
