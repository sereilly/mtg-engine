"""What an "Activate only if …" clause asks of the game (CR 602.5).

The predicates behind the rows of ``activation_restrictions.ACTIVATION_RESTRICTIONS``
that are about **the state of things** rather than a moment of the turn: what
a seat controls ("…only if you control a snow Mountain"), what the source is
doing or carrying ("…only if this creature is attacking", "…only if there are
two or more hatchling counters on this artifact"), a hand's size, a
graveyard's contents ("…only if three or more creature cards are above this
card"), a life total, a creature having died this turn. Each row's *noun
phrase* is payload, read by the grammar's own noun parser or condition reader
and answered by ``subject_matches`` / ``evaluate_condition``, so a card printing
the same clause about another noun is the same row.

The table itself stays one table in ``engine/activation_restrictions.py``, in
its order, beside the moment-of-turn predicates ("…only during your upkeep",
"…only before blockers are declared") its other rows call; this module is the
other family of what those rows call, and the noun-phrase readers the
activation caps in ``engine/activation_tallies.py`` count with
(:func:`_counted_board_phrase`, :func:`_board_count`).

Every predicate here takes ``(game, controller_index, source[, match])`` — the
signature ``ActivationRestriction.is_legal`` declares — and every reader of a
row's payload refuses rather than guessing, for the table's standing reason:
an unenforced restriction is an ability that works more often than the card
allows.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game


def _a_creature_died_this_turn(game: "Game", controller_index: int, source) -> bool:
    """"Activate only if a creature died this turn." (Caged Zombie.)

    Any creature, anyone's -- the printed phrase says "a creature", where the
    per-seat tally beside it says "under your control". Reading the narrower one
    would refuse an activation the card allows.
    """
    return int(getattr(game, "creatures_died_this_turn", 0) or 0) > 0


@lru_cache(maxsize=None)
def _controlled_board_phrase(phrase: str) -> "tuple[dict, bool] | None":
    """"a creature with flying" / "no snow lands" as ``(filter, present)``.

    The noun phrase is read by **the grammar's noun parser**, exactly as
    `static_bonuses._controls_noun_condition` reads the identical phrase after
    "as long as you control": `subject_matches` is what answers this clause at
    every activation, and a second reader of "a snow land" would be free to
    disagree with it about what a snow land is.

    The article is the quantifier and it is what the clause means: "**a** snow
    land" is a presence test and "**no** snow lands" its negation. Anything else
    -- "two or more", "three" -- is a threshold this does not read, and it
    refuses rather than answering as presence, because a threshold silently read
    as "at least one" is a restriction lifted on a board the card does not name.

    All of which is ``subject_filters.quantified_board_phrase``, which this now
    calls rather than spells out: CR 118.9's conditional alternative cost ("If
    you control a Plains, you may tap an untapped creature you control rather
    than pay this spell's mana cost") asks these same two questions of these
    same words, and the copy it would otherwise have made is the one that
    drifts. The name stays here because the *clause* is this table's -- what
    moved is the reading of its noun phrase, next to the matcher that answers
    it.
    """
    from .subject_filters import quantified_board_phrase

    return quantified_board_phrase(phrase)


def _readable_controlled_board(match: "re.Match[str]") -> bool:
    """Whether the noun phrase in a "controls …" clause is one this can test."""
    return _controlled_board_phrase(match.group("board")) is not None


@lru_cache(maxsize=None)
def _block_partner_phrase(phrase: str) -> "dict | None":
    """"a blue creature" in a block-history clause, as a filter payload.

    The same reader :func:`_controlled_board_phrase` is, for the reason it gives
    about its own phrase: `subject_matches` answers this clause at every
    activation, and a second reader of "a blue creature" would be free to
    disagree with it. The *negative* article that reader also admits is refused
    here -- "blocked or was blocked by **no** blue creature" is a sentence Magic
    does not print, and reading it as presence would be a restriction lifted on
    exactly the board the card forbids.
    """
    read = _controlled_board_phrase(phrase)
    if read is None:
        return None
    described, present = read
    return described if present else None


def _readable_block_partner(match: "re.Match[str]") -> bool:
    """Whether the creature a block-history clause names is one this can test."""
    return _block_partner_phrase(match.group("partner")) is not None


def _blocked_or_was_blocked_by_this_turn(
    game: "Game", controller_index: int, source, match: "re.Match[str]"
) -> bool:
    """"Activate only if this creature blocked or was blocked by a blue creature
    this turn." (Sea Troll.)

    CR 509.1a's relation read in both directions -- one printed clause, one
    question -- off the pair records the declare blockers step keeps.
    `turn_state.block_partners_this_turn` is the one reader of both lists, so
    "blocked" and "was blocked by" cannot come to mean two different windows,
    and a creature an *effect* made block counts exactly as a declared one does.

    The noun phrase is payload, exactly as the board clause's is: a card
    printing "…by a green creature" or "…by a Wall" is this rule and needs no
    row here. CR 109.5's observer is the seat whose ability this is.
    """
    from .subject_filters import subject_matches
    from .turn_state import block_partners_this_turn

    described = _block_partner_phrase(match.group("partner"))
    if described is None or source is None:
        return False
    return any(
        subject_matches(
            game, other, described, observer=controller_index, source=source
        )
        for other in block_partners_this_turn(game, source)
    )


@lru_cache(maxsize=None)
def _counted_board_phrase(phrase: str) -> "dict | None":
    """"snow Swamps" as a filter payload, for a clause that *counts* them.

    The plural twin of :func:`_controlled_board_phrase` and the same noun
    parser, because "a snow Swamp" and "snow Swamps" name the same set and a
    second reader of either would be free to disagree about what a snow Swamp
    is. What differs is only the quantifier: that one reads an article and
    answers presence, this one reads a bare plural and answers how many.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    stream = TokenStream(tokenize(phrase.strip()).tokens)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = described.to_payload()
    if not payload or untestable_filter_keys(payload):
        return None
    return payload


def _readable_counted_board(match: "re.Match[str]") -> bool:
    """Whether the noun phrase a counted cap is measured against is testable."""
    return _counted_board_phrase(match.group("board")) is not None


def _board_count(game: "Game", seat: int, source, phrase: str) -> int | None:
    """How many permanents *seat* controls that *phrase* names, or None.

    `subject_matches` answers the phrase, so a text-changed land type counts
    here as it counts everywhere, and CR 109.5's observer is the seat whose
    ability this is.
    """
    described = _counted_board_phrase(phrase)
    if described is None:
        return None
    from .subject_filters import subject_matches

    return sum(
        1
        for perm in game.controlled_by(seat)
        if subject_matches(
            game, perm, described, observer=seat, source=source
        )
    )


def _defending_seat(game: "Game") -> int | None:
    """The seat "defending player" names right now, or None when nothing does.

    CR 506.2 defines the defending player *during the combat phase*, so outside
    combat the clause has nothing to ask about and is unanswerable rather than
    vacuously true. ``_resolve_defending_player_index`` is the engine's one
    answer to "which single seat is defending": the other player in a duel, and
    in a CR 802 multi-defender combat only once exactly one opponent is under
    attack. A clause printed in the singular that no single seat answers refuses
    the activation -- the same direction `legality_enumeration._enumerate_targets` takes for
    ``defending_player_only`` with no seat beside it, because a narrowing nobody
    can answer must never widen.
    """
    if getattr(game, "current_turn_phase", None) != "combat":
        return None
    return game._resolve_defending_player_index()


def _controls_the_printed_noun(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate only if you control a snow Mountain." (Goblin Ski Patrol.)
    "…only if defending player controls a snow land." (Arcum's Sleigh.)
    "…only if defending player controls no snow lands." (Kjeldoran Guard.)

    One row: the seat and the noun phrase are both payload, which is the same
    choice `combat_restrictions.py` makes about its land type and for the same
    reason -- a card printed with another seat, another noun or the other
    polarity is this clause, not a new one, and baking any of the three into the
    pattern made every variation a row, a predicate and a gate entry.

    `subject_matches` answers the phrase, so a text-changed land type (Magical
    Hack) counts here as it counts everywhere, and CR 109.5's observer is the
    *activating* seat even when the board being scanned is the defender's: "you"
    inside the noun phrase would mean the ability's controller.
    """
    read = _controlled_board_phrase(match.group("board"))
    if read is None:
        return False
    described, present = read
    if match.group("who") == "you":
        seat: int | None = controller_index
    else:
        seat = _defending_seat(game)
    if seat is None:
        return False
    from .subject_filters import subject_matches

    held = any(
        subject_matches(
            game, perm, described, observer=controller_index, source=source
        )
        for perm in game.controlled_by(seat)
    )
    return held is present


def _blocked_by_at_least(game: "Game", controller_index: int, source, match) -> bool:
    """"Activate only if at least one creature is blocking this creature."
    (Grizzled Wolverine.)

    ``creatures_blocking`` is the engine's one reader of that relation, so a
    band-propagated block (CR 702.22h) counts here exactly as it counts in the
    damage step. The number is payload; a source that has left the battlefield
    is blocked by nothing.
    """
    from .grammar.vocabulary import NUMBER_WORDS

    if source is None:
        return False
    needed = NUMBER_WORDS.get(match.group("count"))
    if needed is None:
        return False
    return len(game.creatures_blocking(source)) >= needed


def _seven_life_above_starting(game: "Game", controller_index: int, source) -> bool:
    """"Activate only if you have at least 7 life more than your starting life
    total…" (Speaker of the Heavens.)

    The life half alone. The card prints "…and only as a sorcery" after it, and
    this used to read both halves because the clause arrived here whole; a
    conjoined clause is now split into the restrictions it conjoins, so the
    sorcery half is the sorcery row's business and this one stops being two
    rules with one name.
    """
    player = game.players[controller_index]
    starting = int(getattr(game, "starting_life_total", 20) or 20)
    return player.life >= starting + 7


def _source_in_combat(game: "Game", controller_index: int, source, match) -> bool:
    """"Activate only if this creature is **attacking or blocking**." (Sawback
    Manticore.)

    A state of the ability's own *source*, which is what separates it from
    ``activation_restrictions._during_combat``: Jade Statue's clause is
    satisfied by the phase,
    and this one is not — a Manticore sitting at home during somebody else's
    combat is in the combat phase and is neither attacking nor blocking.

    Read through the same two accessors ``permanent_matches_filter`` uses for
    the printed adjectives ("target **attacking** creature"), so the role this
    asks about and the role a noun phrase names are one answer. CR 508.1a and
    CR 509.1g both make the role a state of the permanent, stamped by the
    declaration step and cleared when it leaves combat, so nothing here needs
    the combat maps.

    The two words are payload rather than two rows, because a card printing
    only one half ("Activate only if this creature is attacking", which Magic
    prints often) is this rule with one conjunct, not a different rule. With no
    source there is no permanent to be in a role, and the answer is no — the
    direction that refuses an activation rather than allowing one the card
    forbids.

    **"blocked" is a third word in the same payload** (Cinder Crawler:
    "Activate only if this creature is blocked"), not a row of its own. CR
    509.1h makes it the same kind of fact as the other two — a state stamped on
    the permanent by the declaration step and cleared when it leaves combat —
    and ``state_holds`` already answers it off ``Permanent.blocked``, which is
    the same accessor the printed adjective "target **blocked** creature" is
    matched through. A row of its own would be a second reading of one
    question, free to disagree with this one about what the word means.
    """
    if source is None:
        return False
    from .handlers._filters import state_holds

    words = [word for word in match.group("roles").split(" or ")]
    return any(state_holds(source, word) for word in words)


def _readable_source_roles(match: "re.Match[str]") -> bool:
    """Whether every printed role in the clause is one ``state_holds`` answers.

    ``state_holds`` answers False for a word it has never heard of, which for a
    *restriction* is the safe direction per activation but the wrong one for the
    support gate: a clause naming an unknown role would read as understood and
    then forbid the ability outright. So the gate refuses the clause instead and
    the card is reported unsupported naming it.
    """
    return all(
        word in ("attacking", "blocking", "blocked")
        for word in match.group("roles").split(" or ")
    )


def _source_not_enchanted(game: "Game", controller_index: int, source) -> bool:
    """"Activate only if Hakim isn't enchanted." (Hakim, Loreweaver.)

    CR 303.4a's relation asked of the ability's own source, and the mirror of
    ``_attached_permanent_state`` below, which asks about the *host* of an Aura.
    The list is the authority (``attached_auras``), not the single ``attached_aura``
    slot: an Aura that left leaves the slot pointing at it, and a Hakim that has
    lost his only Aura is a Hakim who may use this again.

    With no source there is no permanent to be enchanted, and the answer is no —
    the direction that refuses an activation rather than allowing one the card
    forbids.
    """
    if source is None:
        return False
    attached = [
        aura for aura in (source.metadata.get("attached_auras") or [])
        if game.is_on_battlefield(aura)
    ]
    return not attached


def _attached_permanent_state(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate only if enchanted land is untapped." (Earthlore.)

    Read off the attachment record, which is the only thing that can answer it:
    "enchanted land" is not a description of any permanent, it is *this* Aura's
    host. An Aura that is not attached to anything satisfies no state, so the
    ability cannot be activated — which is also what CR 704.5m would already
    have done to the Aura.

    "Activate only if enchanted creature is **white and** untapped." (Nature's
    Chosen.) The colour is a second conjunct of the same clause, not a second
    clause — ``_conjuncts`` splits on "and only", which this "and" is not — so
    it is read here or it is dropped, and dropped it would be an ability usable
    off a green creature the card never allows. Asked through
    ``effective_colors`` so layer 5 answers: an Aura on a creature a Painter's
    Servant has made white can be activated, and one whose host stops being
    white cannot.
    """
    host = getattr(source, "metadata", {}).get("attached_to") if source else None
    if host is None or not game.is_on_battlefield(host):
        return False
    colour = match.groupdict().get("colour")
    if colour and _COLOR_LETTERS[colour] not in host.effective_colors:
        return False
    return host.tapped if match.group("state") == "tapped" else not host.tapped


#: The printed colour words this file reads, as the single letters the engine's
#: colour channel uses. Its own map rather than an import, because
#: ``activation_restrictions`` is imported by the compiler and the grammar's
#: word tables import back the other way.
_COLOR_LETTERS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}


def _printed_hand_count(match: "re.Match[str]") -> int | None:
    """The hand size the clause names, or None when the word is not a number.

    "**no** cards in hand" (Fool's Tome) and "exactly **seven** cards in hand"
    (Library of Alexandria) are one sentence with the number changed, so they
    are one row and the number is payload — the shape every other parameterised
    row in this table has. Written as its own reader because both the predicate
    and :attr:`ActivationRestriction.payload_readable` ask it, and a row that
    admitted a count word it could not turn into a number would refuse every
    activation, silently.
    """
    from .oracle_types import _NUMBER_WORDS

    word = match.group("count")
    if word == "no":
        return 0
    word = word.split(" ", 1)[1] if " " in word else word
    return int(word) if word.isdigit() else _NUMBER_WORDS.get(word)


def _readable_hand_count(match: "re.Match[str]") -> bool:
    return _printed_hand_count(match) is not None


def _exact_cards_in_hand(
    game: "Game", controller_index: int, source, match: "re.Match[str]"
) -> bool:
    """"Activate only if you have <N> cards in hand." (Fool's Tome, Library of
    Alexandria.)

    Both printed spellings state an **exact** size rather than a bound, so one
    comparison answers both. A card printing "or more" / "or fewer" would be a
    different sentence and would want its own row; this pattern does not admit
    one, which is what keeps that from being read as this.
    """
    wanted = _printed_hand_count(match)
    return wanted is not None and len(game.players[controller_index].hand) == wanted


def _controlled_since_your_last_turn(game: "Game", controller_index: int, source) -> bool:
    """Rocket Launcher. "Continuously since the beginning of your most recent
    turn" is a property of the *permanent*, so the source is what answers -- and
    a source that is gone answers no."""
    if source is None:
        return False
    return bool(game._controlled_since_turn_start(source))


def _source_entered_this_turn(game: "Game", controller_index: int, source) -> bool:
    """Fungus Elemental. "Activate only if this creature entered this turn."

    A property of the *permanent*, so the source is what answers and a source
    that is gone answers no — :func:`_controlled_since_your_last_turn`'s shape
    one record over. It has to be the **arrival** record rather than the
    summoning-sickness one those two share: CR 302.6's stamp is rewritten by a
    control change and carried forward by a passing turn, so a creature handed
    over this turn would answer "entered this turn" for the control change
    rather than for entering. ``Game.entered_this_turn`` is the fact itself.
    """
    if source is None:
        return False
    return bool(game.entered_this_turn(source))


def _at_least_that_many_counters(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate only if there are two or more hatchling counters on this
    artifact." (Triassic Egg.)

    Number and counter word are both payload, read off the match: the sentence
    is the same sentence with any other word in it, and `named_counters` already
    stores an invented kind without knowing which. Asked of the *source*,
    because "on this artifact" names the permanent carrying the ability -- and a
    source that has left answers no, a permanent that is gone having no counters
    (CR 400.7).
    """
    from .grammar.vocabulary import NUMBER_WORDS
    from .named_counters import counters_on

    if source is None:
        return False
    needed = NUMBER_WORDS.get(match.group("count"))
    if needed is None:
        return False
    return counters_on(source, match.group("counter")) >= needed


def _no_counters_of_that_kind(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate only if there are no charge counters on this artifact."
    (Jeweled Amulet, Ice Cauldron.)

    :func:`_at_least_that_many_counters` with the bound at zero and the printed
    word "no" in place of a number. Asked of the *source* for that function's
    reason, and a source that has left answers **False**: a permanent that is
    gone has no counters, which would read as "the restriction is satisfied" —
    but it also has no ability to activate, and the honest answer to "may this
    be activated?" for a permanent that is not there is no.
    """
    from .named_counters import counters_on

    if source is None:
        return False
    return counters_on(source, match.group("counter")) == 0


def _readable_cards_above(match) -> bool:
    """Whether the noun phrase in "…N or more <phrase> cards are above this
    card" is one this file can count.

    The same pairing every `.+` row here makes: the pattern matches more
    sentences than the predicate implements, so a phrase the card matcher
    cannot test leaves the clause unmatched and the card unsupported, rather
    than admitted with a restriction that answers "no" to every board.
    """
    from .grammar.vocabulary import NUMBER_WORDS

    if NUMBER_WORDS.get(match.group("count")) is None:
        return False
    return _cards_above_filter(match.group("kind")) is not None


@lru_cache(maxsize=None)
def _cards_above_filter(phrase: str) -> "dict | None":
    """"creature" / "creature card" as the search-filter payload that tests one
    card in a graveyard.

    Read by `search_filters.search_matches`, which is the engine's one answer to
    "may this card be found", and the only reader that works on a card in a
    hidden or open zone at all: CR 613.1 gives a card outside the battlefield no
    computed characteristics, so the printed type line is the whole of what
    there is to ask. A phrase it cannot test returns None and the clause goes
    unmatched.
    """
    word = " ".join((phrase or "").strip().lower().split())
    # One card type and nothing else, spelled the way `search_matches` takes it.
    # Widening this means widening what that predicate can answer, and the two
    # are one change.
    if word in ("creature", "artifact", "enchantment", "instant", "sorcery", "land"):
        return {"card_type": word}
    return None


def _enough_cards_above_in_graveyard(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate only if three or more creature cards are above this card."
    (Ashen Ghoul.)

    CR 404.1 makes a graveyard an ordered pile and puts each arriving card *on
    top* of it, so "above this card" names the cards that got there later. The
    engine appends, so those are the entries at a higher index -- and the index
    is found by **identity**, because two copies of one card in a graveyard are
    literally the same immutable ``CardDefinition`` and a name or value match
    finds whichever copy is first.

    *source* is the card itself rather than a permanent: this clause only ever
    appears on an ability that functions from a graveyard (CR 113.6m), where
    there is no permanent to be the source. A permanent reaching here answers
    False, which is the honest reading -- a card on the battlefield has nothing
    above it in any graveyard.
    """
    from .grammar.vocabulary import NUMBER_WORDS
    from .search_filters import search_matches

    needed = NUMBER_WORDS.get(match.group("count"))
    described = _cards_above_filter(match.group("kind"))
    if source is None or needed is None or described is None:
        return False
    graveyard = game.players[controller_index].graveyard
    for index, held in enumerate(graveyard):
        if held is source:
            above = graveyard[index + 1:]
            return sum(1 for card in above if search_matches(card, described)) >= needed
    return False


def _source_card_is_in_your_graveyard(
    game: "Game", controller_index: int, source
) -> bool:
    """"Activate only if this card is in your graveyard." (Carrionette.)

    CR 113.6m's statement made explicit by the card: the ability functions only
    from the graveyard, so the clause is both a restriction and — through
    :attr:`ActivationRestriction.functions_from` — the thing that tells the
    activation path which zone to look in.

    *source* is the card itself, as it is for the "cards above this card" row
    beside this one: there is no permanent, and CR 400.3 makes "your graveyard"
    the pile of the player activating. A permanent reaching here answers False,
    which is the honest reading — a card on the battlefield is not in anybody's
    graveyard.

    By **identity**, never by name or value: two copies of one card in a
    graveyard are the same immutable ``CardDefinition``, and a name match would
    say yes for a copy the activator does not hold.
    """
    if source is None or hasattr(source, "permanent_id"):
        return False
    if not 0 <= controller_index < len(game.players):
        return False
    return any(
        held is source for held in game.players[controller_index].graveyard
    )


@lru_cache(maxsize=None)
def _counted_pile_condition(phrase: str) -> "dict | None":
    """"there are seven or more cards in your graveyard" as the lowered
    condition payload that answers it, or None when this cannot read it.

    The phrase is read by **the grammar's own condition reader**
    (``grammar.condition_payload_for``), for the reason
    :func:`_controlled_board_phrase` reads its noun phrase through the noun
    parser: the identical words stand behind an "if" on a spell ("If there are
    seven or more cards in your graveyard, draw a card") and behind "as long
    as" on a static ability, and a regex of its own here would be a third
    answer to how many cards that is. What comes back is the ``cards_in_zones``
    payload those sentences lower to, so the number, the pile's owner and any
    narrowing on the cards ("seven or more **creature** cards") are all
    payload — threshold's seven is not special-cased anywhere.

    Held to that one kind. The reader admits every condition the grammar knows,
    and most of them ask about something an activation does not have — a
    target, an event's player, a record a resolution wrote. A count of cards in
    piles is a fact about the game as it stands, which is what CR 602.5 needs a
    restriction to be.
    """
    from .grammar import condition_payload_for

    payload = condition_payload_for(phrase)
    if payload is None or payload.get("kind") != "cards_in_zones":
        return None
    return payload


def _readable_counted_pile(match: "re.Match[str]") -> bool:
    """Whether the pile count in a "there are … in your graveyard" clause is
    one the condition evaluator can answer."""
    return _counted_pile_condition(match.group("pile")) is not None


def _counted_pile_holds(
    game: "Game", controller_index: int, source, match: "re.Match[str]"
) -> bool:
    """"Activate only if there are seven or more cards in your graveyard."
    (Threshold — Barbarian Ring, Nomad Decoy, Cabal Inquisitor.)

    Answered by ``handlers/control_flow.evaluate_condition``, the one evaluator
    every printed "if" goes through, so this clause and a spell's "If there are
    seven or more cards in your graveyard, …" cannot count differently. "Your"
    is the *activating* seat (CR 602.1a's controller of the ability), which is
    what ``controller_index`` is here.

    **Asked before any cost is paid**, because that is when CR 602.5 asks it:
    "a player can't *begin* to activate an ability that's prohibited from being
    activated", and costs are paid at the end of the process (CR 601.2h by way
    of CR 602.2b). So a land sacrificed to pay for its own threshold ability is
    not in the graveyard yet and does not count toward the seven, and a cost
    that exiles cards from that graveyard (Cabal Inquisitor) may leave fewer
    than seven behind without undoing an activation that was legal when it
    began. Nothing re-asks the clause as the ability resolves.
    """
    payload = _counted_pile_condition(match.group("pile"))
    if payload is None or not 0 <= controller_index < len(game.players):
        return False
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition

    activator = game.players[controller_index]
    # ``target`` is the activator only because the context needs one: the one
    # kind :func:`_counted_pile_condition` admits never reads it.
    return evaluate_condition(
        game,
        OracleExecutionContext(
            caster=activator, target=activator, card=getattr(source, "card", None),
        ),
        payload,
    )
