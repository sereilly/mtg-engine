"""The measure: what a seat's position is worth.

**"Larger" is said here, once** (the comment over the worth constants says
why). A position is :func:`seat_standing` — life, priced in tiers, cards in
hand, and :func:`permanent_worth` read through the layers — and what a cast
does is the swing between two standings, what lasts counted in full and
what ends this turn at ``TEMPORARY_SHARE`` (:func:`swing_worth`).

Two readers ask the measure, and that is why it is in the valuation family
and not beside the policy's weights: the policy, which predicts with it —
carrying a cast out on a scratch copy (``ai_rehearsal.rehearse``) and
pricing what that changed — and the mode census
(``tests/ai/test_ai_mode_chooser_census.py``), which makes the cast for real
on a board of its own and measures with it. Two prices from two functions
would be a census asking the scorer whether the scorer is right. The
choosers price one thing on the same scale where nothing is carried out: a
blocker against the damage it saves (:func:`permanent_worth`,
:func:`life_worth`), the permanent a price is best paid with
(:func:`permanent_loss`), a land a search would find that the seat does not
need (:func:`spare_land_find_price`).

It reads the board it is handed and nothing else: no copy of the game is
taken here, and nothing is cast.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from .game_result_bans import player_cant_lose
from .phasing_locks import waits_for_its_source


# --- The measure: what a seat's position is worth -----------------------------
#
# **"Larger" is said here, once.** Which of two castable bullets takes the
# larger thing off the opposing board or adds the larger thing to its caster's
# own, which of two legal targets is the better one, whether a cast does
# anything at all — each is a comparison of two positions, and a comparison
# needs one unit. The unit is the life-equivalent the toll prices already use
# (``ai_prompts._toll_loss_price``): a point of life near twenty is worth one.
# (Those prices are an older list in the same unit and put a card at two; the
# two lists answer different questions and nothing here reconciles them.)
#
# Two readers ask it, and that is why it lives in this module rather than
# beside the weights in ``ai_policy``: the policy, which *rehearses* a cast
# (``ai_rehearsal.rehearse``) and prices what it changed; and the mode census
# (``tests/ai/test_ai_mode_chooser_census.py``), which makes the cast for real
# on a board of its own and prices what that changed. Two prices from two
# functions would be a census asking the scorer whether the scorer is right.
#
# What it reads is the board as the layers compute it — never a card's text.

#: A card in hand: about four life. The old cast weight said the same thing in
#: another place ("worth exactly 4.0 per net card", `ai_scoring._score_cast`).
CARD_WORTH = 4.0
#: What any permanent is worth just by being one, before its stats and its
#: cost are added: the card it is. **Never less than that card in a hand**,
#: or returning a permanent to its owner's hand would measure as a gift to
#: its owner — which is what a floor of two and a half made of every bounce
#: aimed at something that had cost nothing. A Mox is worth a card.
PERMANENT_WORTH = CARD_WORTH
#: The same floor for a token, which is not a card: nothing was spent from a
#: hand to make it and nothing comes back if it leaves (CR 111.7). So a 2/2
#: destroyed outweighs a 2/2 token made, by the card that was under it.
TOKEN_WORTH = 1.5
#: A land on top of that: the card and the land drop it took.
LAND_WORTH = 1.5
#: How many lands a seat is counted as needing, and what one beyond them is
#: worth: half a life. The same six ``ai_casts.BUYBACK_PERMANENTS_KEPT``
#: keeps before a seat pays a buyback in lands — a seventh land is the one a
#: seat gives up for a card, and the one a Stone Rain is wasted on.
LANDS_WORTH_KEEPING = 6
SPARE_LAND_WORTH = 0.5
#: A creature's body, per point.
POWER_WORTH = 1.4
TOUGHNESS_WORTH = 1.1
#: An evasion ability, per point of the power it carries past a blocker.
EVASION_WORTH = 0.5
#: Any other combat keyword, flat.
COMBAT_KEYWORD_WORTH = 1.0
#: How much of a creature's body is missing while it is tapped: all of it —
#: it neither attacks nor blocks until it untaps, which is what a body is
#: for. A reading of the board **now** only; the card under it is still
#: there, and so is whatever it does without tapping.
TAPPED_SHARE = 1.0
#: How much a change that is gone by the end of the turn counts for against
#: one that is still there: a +3/+3 until end of turn is a quarter of a
#: +3/+3 counter, a creature phased out a quarter of a creature destroyed.
TEMPORARY_SHARE = 0.25
#: A seat that has lost, or will at its next draw.
LOST = 1000.0

_EVASION_KEYWORDS = frozenset({
    "flying", "fear", "shadow", "horsemanship", "menace", "landwalk",
    "swampwalk", "forestwalk", "islandwalk", "mountainwalk", "plainswalk",
    "desertwalk",
})
_COMBAT_KEYWORDS = frozenset({
    "first strike", "double strike", "trample", "vigilance", "lifelink",
    "deathtouch", "indestructible", "reach", "protection", "hexproof",
    "shroud", "banding", "flanking", "rampage",
})

#: Life is worth more the less of it there is: ``(up to this total, each
#: point)``, and the last rate for everything above the last tier. Three
#: damage is three at twenty life and six at five; five life gained at twenty
#: is two and a half, which is why it loses to a dead creature.
_LIFE_TIERS = ((5, 2.0), (10, 1.5), (20, 1.0))
_LIFE_ABOVE = 0.5


def life_worth(life: int) -> float:
    """What a life total is worth: concave, and ``-LOST`` at zero or less."""
    if life <= 0:
        return -LOST
    worth, floor = 0.0, 0
    for ceiling, rate in _LIFE_TIERS:
        if life <= floor:
            break
        worth += (min(life, ceiling) - floor) * rate
        floor = ceiling
    if life > floor:
        worth += (life - floor) * _LIFE_ABOVE
    return worth


#: The permanents (by id, CR 400.7) a reading prices **at their blank's
#: cost** — mana value 0, face up or down — for the length of
#: :func:`priced_as_their_blanks`.
_PRICED_AS_THEIR_BLANKS: ContextVar[frozenset] = ContextVar(
    "ai_priced_as_their_blanks", default=frozenset(),
)


@contextmanager
def priced_as_their_blanks(permanent_ids):
    """Price the permanents *permanent_ids* name at the face-down blank's
    cost (mana value 0, CR 708.2a) in every :func:`permanent_worth` read
    inside the block — for a rehearsal of **turning one face up**.

    A face-down permanent's cost is the blank's and a face-up one's is its
    card's, so every turn-up read as the whole of its card's mana value
    gained: Scornful Egotist, a 1/1 for {7}{U}, turned up for its {U} morph
    cost and rated +4.5 for a body smaller than the 2/2 it had been (SCG
    W1G5). The card was there all along; what turning it up buys is the
    face-up body, its abilities and its "when turned face up" trigger, each
    of which a standing reads without the cost. Held for both copies of the
    rehearsal and for every chooser asked on them (the attack the copy
    declares weighs the same body the standing does)."""
    token = _PRICED_AS_THEIR_BLANKS.set(frozenset(permanent_ids))
    try:
        yield
    finally:
        _PRICED_AS_THEIR_BLANKS.reset(token)


def permanent_worth(permanent, *, now: bool = True) -> float:
    """What *permanent* is worth to whoever controls it.

    The floor every permanent has, what it cost, and for a creature its body
    and its keywords — all read through CR 613's accessors, so a creature
    under a +3/+3 is worth the 5/5 it currently is and one that lost flying
    is worth what is left.

    *now* is the board as it stands this instant: a tapped creature counts
    for less (``TAPPED_SHARE``). ``now=False`` is the reading for what will
    still be true once the turn's temporary effects are over, where a tap is
    not a difference.
    """
    from .layer_bridge import computed_abilities

    # What it cost, read as CR 613 reads it: a Clone is worth the mana value
    # of what it copies (CR 707.2) — unless a turn-up is being weighed
    # (:func:`priced_as_their_blanks`).
    cost = (
        0.0 if permanent.permanent_id in _PRICED_AS_THEIR_BLANKS.get()
        else float(permanent.effective_card.cmc or 0)
    )
    worth = (
        TOKEN_WORTH if permanent.metadata.get("is_token") else PERMANENT_WORTH
    ) + cost
    if permanent.has_type("land"):
        worth += LAND_WORTH
    if not permanent.is_creature:
        return worth
    power = max(0, permanent.effective_power)
    body = power * POWER_WORTH + max(0, permanent.effective_toughness) * TOUGHNESS_WORTH
    abilities = computed_abilities(permanent)
    body += power * EVASION_WORTH * len(_EVASION_KEYWORDS & abilities)
    body += COMBAT_KEYWORD_WORTH * len(_COMBAT_KEYWORDS & abilities)
    if now and permanent.tapped and not permanent.attacking:
        # An attacker is tapped because it is fighting: its body is in use,
        # not missing.
        body *= 1.0 - TAPPED_SHARE
    return worth + body


def seat_standing(game, seat: int, *, now: bool = True) -> float:
    """What *seat*'s position is worth: its life, the cards in its hand and
    the permanents it controls (:func:`permanent_worth`).

    A seat that has lost is ``-LOST``, and so — less by half, so that a real
    loss still ranks below it — is one with no library left to draw from
    (CR 704.5b on its next draw). ``now=False`` also counts what has phased
    out: CR 702.26 brings it back.
    """
    player = game.players[seat]
    if player.lost:
        return -LOST
    if player.life <= 0:
        # "You can't lose the game …" (Platinum Angel): a seat at 0 life
        # behind the ban is still playing (CR 104.3b answered by a static), so
        # its position is its cards and board with nothing left for its life —
        # not a loss every line of play reads as already decided.
        if not player_cant_lose(game, seat):
            return -LOST
        worth = CARD_WORTH * len(player.hand)
    else:
        worth = life_worth(player.life) + CARD_WORTH * len(player.hand)
    if not player.library:
        worth -= LOST / 2
    lands = 0
    for permanent in game.controlled_by(seat):
        worth += permanent_worth(permanent, now=now)
        lands += bool(permanent.has_type("land"))
    if not now:
        for permanent in player.phased_out:
            # …except what is held out until a source leaves (Oubliette):
            # it does not phase in at the untap step, so it is not coming
            # back by itself.
            if waits_for_its_source(game, permanent):
                continue
            worth += permanent_worth(permanent, now=False)
    # Each land beyond the ones a seat needs is worth `SPARE_LAND_WORTH`, not
    # a card and a land drop.
    worth -= max(0, lands - LANDS_WORTH_KEEPING) * (
        PERMANENT_WORTH + LAND_WORTH - SPARE_LAND_WORTH
    )
    return worth


def spare_land_find_price(game, seat: int, searches) -> float:
    """What a search that can find **only land cards** in *seat*'s library
    (*searches*: the payloads of its ``search_library`` steps,
    ``ai_valuation.land_searches``) costs *seat* beyond what a standing reads,
    when the land it finds is one the seat does not need: ``CARD_WORTH`` less
    ``SPARE_LAND_WORTH``, or 0.

    A standing prices a card in hand at a card whatever it is, and a land on
    the battlefield beyond the ``LANDS_WORTH_KEEPING`` a seat needs at a
    spare. So a landcycle — "Plainscycling {2}", a held card traded for a
    land card — reads as a card out and a card in: nothing. A seat with ten
    lands paid {3}{W}{W} in its upkeep to return Eternal Dragon from its
    graveyard and plainscycled it for a Plains with what was left, three
    turns running (SCG W2, seed 11; kg4). The find is a land drop nobody
    needs when the lands the seat controls and holds, the find among them,
    are more than it needs.

    Priced here, on the one road that chooses a land, and not in the
    standing for every land card in a hand: there it priced every draw a
    rehearsal makes by the one card its reshuffled library happened to give
    up, and a cycle for a random card at six lands became a coin flip."""
    from .search_filters import search_matches

    if not searches:
        return 0.0
    library = game.players[seat].library
    finds = [
        card for card in library
        if any(search_matches(card, payload, game=game, owner=seat) for payload in searches)
    ]
    if not finds or any(card.primary_type != "land" for card in finds):
        return 0.0
    lands = sum(1 for permanent in game.controlled_by(seat) if permanent.has_type("land"))
    lands += sum(1 for card in game.players[seat].hand if card.primary_type == "land")
    if lands + 1 <= LANDS_WORTH_KEEPING:
        return 0.0
    return CARD_WORTH - SPARE_LAND_WORTH


def permanent_loss(game, seat: int, permanent) -> float:
    """What *seat*'s standing (:func:`seat_standing`, read now) loses if
    *permanent*, which it controls, leaves the battlefield: the permanent's
    worth, less what the standing had already marked a land beyond the ones a
    seat needs down by — the spare land a price is best paid with.

    For a seat choosing **which** of its permanents pays a price ("sacrifice a
    permanent of their choice", CR 116.2d), asked before anything is carried
    out; what the payment then does to the board is the rehearsal's to read.
    """
    loss = permanent_worth(permanent)
    if permanent.has_type("land"):
        lands = sum(1 for other in game.controlled_by(seat) if other.has_type("land"))
        if lands > LANDS_WORTH_KEEPING:
            loss -= PERMANENT_WORTH + LAND_WORTH - SPARE_LAND_WORTH
    return loss


def standing_swing(before: tuple, after: tuple, seat: int) -> float:
    """How far *seat* moved against the rest of the table between two
    readings (one standing per seat): its own change less every other
    seat's."""
    return sum(
        (after[index] - before[index]) * (1.0 if index == seat else -1.0)
        for index in range(len(before))
    )


def swing_worth(now: float, lasting: float) -> float:
    """One number for a change measured twice — as the board stood right
    after it (*now*) and with the turn's temporary effects over (*lasting*).

    What lasts counts in full; what is there now and gone by then counts for
    ``TEMPORARY_SHARE`` of itself. **This is what "larger" means**, for the
    policy choosing between two casts and for the census judging the choice.
    """
    return lasting + TEMPORARY_SHARE * (now - lasting)


def standings(game, *, now: bool = True) -> tuple:
    """:func:`seat_standing` for every seat, in seat order."""
    return tuple(
        seat_standing(game, seat, now=now) for seat in range(len(game.players))
    )


__all__ = [
    "CARD_WORTH",
    "LANDS_WORTH_KEEPING",
    "LAND_WORTH",
    "LOST",
    "PERMANENT_WORTH",
    "SPARE_LAND_WORTH",
    "TEMPORARY_SHARE",
    "TOKEN_WORTH",
    "life_worth",
    "permanent_loss",
    "permanent_worth",
    "priced_as_their_blanks",
    "seat_standing",
    "spare_land_find_price",
    "standing_swing",
    "standings",
    "swing_worth",
]
