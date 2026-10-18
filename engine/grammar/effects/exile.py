"""Cards moving **into exile** (CR 406).

Split out of ``effects/cards.py`` at Alliances' third wave, when two branches
each grew that module under the 1,000-line guard and the sum crossed it — the
case SET_PLAYBOOK.md tells the integrator to split at rather than carry,
because no single branch is at fault and so no single branch would have split
it.

The name is ``lowering/exile.py``'s, which has been a lowering-only family
since before this file existed: the mirror re-forms rather than forking, which
is the rule ``effects/prevention.py`` and ``effects/counters.py`` were both
written under. What stayed in ``cards`` is what the module's own docstring
claims — a card *moving* between hand, library and graveyard; what came here
names the exile zone, and the two shared no production.

**Its other half left at the Phase 0 before Odyssey**, for
``effects/linked_exile.py``. The first line above used to read "Cards moving
**into and out of exile** (CR 406), and back again", and that "and" was the
seam: the lowering side had cut along it at Tempest's Phase 0 —
``lowering/exile.py`` is "the half that *moves an object into* the zone", where
every production in ``lowering/linked_exile.py`` "starts from a pile that is
already there" — and the parse halves had stayed in one file. Every node the
productions that left build lowers in that second module, and none of the five
built here does (``Exile``, ``ExileCostSacrifices`` and
``ExileGraveyardArrivalsThisTurn`` lower in ``lowering/exile.py``,
``ExileGraveyard`` in ``lowering/library.py``, ``ExileBoundCard`` inline in
``statement_dispatch_naming``). The call graph agreed: all five edges inside
this module were inside the half that left, so neither file imports the other.

What is left is an object **going** to exile, by a sentence the ordinary
"Exile <noun phrase>" cannot read — a card the firing event named, a cost's
sacrifices, a whole graveyard, a seat emptying its own graveyard or hand, a
spell taken off the stack, and CR 614's "exile that card instead" for a turn.
The ordinary production itself is not here: it is the tail of the ``exile`` arm
in ``imperative_verbs``, which tries the three imperatives below in front of
it. The two with a printed subject are reached from ``player_verbs`` and the
replacement from ``if_openings``.

``ast/exile.py`` holds the nodes of both halves, cut by subject rather than by
reader for the reason its docstring argues. (This paragraph said "``ast/`` has
no ``exile``" from Tempest's third wave, which gave it one, until this split.)
"""

from dataclasses import replace

from .. import ast
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..phrases import _accept_number, _parse_zone
from ..readers import _parse_entering_counters
from ..references import parse_player_ref, parse_recipient
from ..stream import TokenStream


def _parse_counted_graveyard_cards(stream: TokenStream) -> "ast.TargetSpec | None":
    """``…two cards from your graveyard`` behind "exile" — a printed number of
    cards out of **your** graveyard with no "target", or None with nothing
    consumed.

    "At the beginning of your end step, exile two cards from your graveyard."
    (The ability Bloodcurdler has with threshold.) The plural of "exile **a**
    card from your graveyard" (Decaying Soil, Forgotten Harvest), which the
    recipient parser reads through its article: nothing is announced, the
    controller picks as the effect resolves, and the only difference is how
    many. That parser has no untargeted count — "two <noun>" is a target
    quantifier everywhere else it is printed — so the number is read here and
    the phrase comes back as the same untargeted reference with a count on it.

    Your graveyard only. Another player's pile is a choice made *against*
    somebody, and every printing of that is a target or a seat's own action
    (``_parse_player_exiles_pile``).
    """
    mark = stream.mark()
    count = _accept_number(stream)
    if count is None or count < 2 or stream.at_word("target"):
        stream.reset(mark)
        return None
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not (
        described.zone == "graveyard"
        and described.is_card
        and described.zone_owner is not None
        and described.zone_owner.kind == "you"
    ):
        stream.reset(mark)
        return None
    return ast.TargetSpec("a", described, count=count)


def _parse_exile_bound_card(stream: TokenStream) -> "ast.ExileBoundCard | None":
    """``Exile that card from your graveyard.`` (Necropotence.) /
    ``…exile that card.`` (Purgatory.)

    Refuses without consuming, like the other exile productions beside it, so
    an ordinary exile keeps its own refusal.

    The zone is **optional**, and the lowering is where the difference lands:
    with a zone the sentence names the pile it expects, without one it names
    the pile the firing event already said the card went to. Reading the
    zone-less form here rather than refusing it is safe because "that card" has
    no other referent — the recipient parser one production down reads
    permanents and chosen cards, so an unclaimed "exile that card" fails the
    whole line rather than matching something else.
    """
    mark = stream.mark()
    stream.expect_word("exile")
    if not stream.accept_phrase("that", "card"):
        stream.reset(mark)
        return None
    if not stream.accept_word("from"):
        return ast.ExileBoundCard(None)
    zone = _parse_zone(stream)
    return ast.ExileBoundCard(zone)


def _parse_exile_cost_sacrifices(stream: TokenStream) -> ast.Statement | None:
    """``Exile this <noun> and those <noun> cards.`` (Sword of the Ages.)

    Returns None quietly on anything else, like the two exile productions
    beside it, so an ordinary exile keeps its own refusal.

    Both halves are required. "Exile this artifact" alone is the source leaving
    the battlefield — a sentence the ordinary production already reads, and a
    different effect from this one, which reaches into a graveyard for a set the
    cost put there. Reading only the first half and stopping is what the
    ordinary production would do, so this is tried in front of it.
    """
    mark = stream.mark()
    stream.expect_word("exile")
    if not stream.accept_word("this"):
        stream.reset(mark)
        return None
    if stream.peek_word() is None:
        stream.reset(mark)
        return None
    stream.advance()   # the source's own noun ("artifact")
    if not stream.accept_phrase("and", "those"):
        stream.reset(mark)
        return None
    if stream.peek_word() is None:
        stream.reset(mark)
        return None
    stream.advance()   # the sacrificed set's noun ("creature")
    if not stream.accept_word("cards", "card"):
        stream.reset(mark)
        return None
    return ast.ExileCostSacrifices()


def _parse_exile_graveyard(stream: TokenStream) -> ast.Statement | None:
    """``Exile target player's graveyard.`` (Tormod's Crypt.)

    Returns None quietly on anything else, so the ordinary permanent exile keeps
    its own errors. The possessive and the zone noun are both expected: "exile
    target player" is not a sentence, and consuming the player and stopping
    would leave a production that exiles whatever the next reader assumes.
    """
    mark = stream.mark()
    stream.expect_word("exile")
    # "Exile **all graveyards**." (Bazaar of Wonders.) Every pile at once, and
    # read before the possessive because "all" is not a player reference: the
    # reader below would refuse it and the sentence would die at a phrase this
    # production does read.
    if stream.accept_phrase("all", "graveyards"):
        return ast.ExileGraveyard(None)
    player = parse_player_ref(stream)
    if (
        isinstance(player, ast.PlayerRef)
        and player.kind in ("target_player", "target_opponent")
        and stream.accept_word("'s")
        and stream.accept_word("graveyard")
    ):
        return ast.ExileGraveyard(player)
    stream.reset(mark)
    return None


def _parse_player_exiles_pile(
    stream: TokenStream, player: "ast.PlayerRef"
) -> "ast.Exile | None":
    """``exiles all creature cards from their graveyard`` (Living Death),
    ``exiles all cards from their hand face down`` (Memory Jar) — the verb and
    everything after it, with the subject already read by the caller.

    The bare imperative ("Exile all creature cards from your graveyard", Zombie
    Mob) has had a production since Mirage and lowers to the same instruction;
    what this adds is the **printed subject**, which CR 608.2c makes the same
    sentence read from the other end. It is not decoration on this shape: the
    subject says whose graveyard is emptied, and — through the per-seat record
    the step writes — whose cards the sentence behind it hands back.

    Narrow on purpose, and the narrowness is the safety. Only a *graveyard card
    sweep* builds an :class:`ast.Exile` carrying an actor, so every other exile
    in the pool keeps a node whose actor is ``None`` and cannot have one
    dropped. The lowering refuses a non-``None`` actor anywhere else in any
    case, which is the second lock on the same door.

    Returns None with the cursor unmoved for anything else, so the two exile
    productions beside it in ``subject_verb`` keep their own sentences and the
    line keeps its own refusal site.
    """
    mark = stream.mark()
    if not stream.accept_word("exiles", "exile"):
        stream.reset(mark)
        return None
    subject = parse_recipient(stream)
    if not isinstance(subject, ast.TargetSpec):
        stream.reset(mark)
        return None
    filt = subject.filter
    # A pile of *cards* in a graveyard or a hand and nothing else. The noun
    # parser reads "from their graveyard" onto the filter as
    # ``zone``/``zone_owner``, so a phrase that named the battlefield — or a
    # library — comes back here as a different zone and is put back rather than
    # lowered onto a sweep that would read the wrong pile. The two admitted
    # zones lower to two different handlers; which one is the lowering's
    # question, and it refuses anything it has no sweep for.
    if not (filt.is_card and filt.zone in ("graveyard", "hand")):
        stream.reset(mark)
        return None
    # The possessive agrees with the subject, exactly as the library exile one
    # module over demands. "each player … from **their** graveyard" is one
    # claim said twice; the lowering checks the pair against each other rather
    # than trusting either half alone, and this is where the half it checks is
    # read.
    owner = filt.zone_owner
    if owner is None:
        stream.reset(mark)
        return None
    if not subject.quantifier in ("all", "each"):
        stream.reset(mark)
        return None
    if subject.targeted:
        stream.reset(mark)
        return None
    # "…from their hand **face down**." (Memory Jar.) CR 406.3 makes a
    # face-down card in exile hidden from every player, its owner included, so
    # the words are a real difference and not decoration — read here rather
    # than left unconsumed, which is what refused this whole sentence before.
    # The bare imperative one production over reads the same two words onto the
    # same field.
    face_down = bool(stream.accept_phrase("face", "down"))
    # "**Target player** exiles all cards with flashback from **their**
    # graveyard." (Tombfire; Mudhole prints "all land cards".) One chosen seat
    # emptying its own pile — which is "Exile all … from **target player's**
    # graveyard" (Haunting Echoes) read from the other end: the same pile, the
    # same cards, and CR 400.3 sends each to its owner's exile whoever is said
    # to do the exiling. So it is built as *that* sentence's node — the pile
    # named by the player, no actor — and the lowering, the target description
    # and the handler arm that sentence already has are the only ones there
    # are. A second spelling of the pile would be a second arm in each of them
    # for one sweep.
    #
    # Only where the two halves agree: the possessive behind a singular chosen
    # subject is the noun parser's "owner" ("their graveyard"). "Target player
    # exiles all cards from *your* graveyard" keeps its actor and is refused by
    # the lowering, as one player and somebody else's pile always was.
    if (
        player.kind in ("target_player", "target_opponent")
        and filt.zone == "graveyard" and owner.kind == "owner"
        and not face_down
    ):
        return ast.Exile(
            replace(subject, filter=replace(filt, zone_owner=player)), actor=None,
        )
    return ast.Exile(subject, actor=player, face_down=face_down)


def _parse_player_exiles_target_spell(
    stream: TokenStream, player: "ast.PlayerRef"
) -> "ast.Exile | None":
    """``exiles it with X delay counters on it`` (Ertai's Meddling) — the verb
    and everything after it, with ``Target spell's controller`` already read by
    the caller.

    The **object** of the verb is the sentence's target and it was printed in
    front of the verb: "target" modifies *spell*, so the announcement chooses an
    object on the stack (CR 115.1) and the seat performing the exile is read off
    it (CR 109.5). That is why "it" is not resolved through ``parse_recipient``
    here — the shared reader answers a bare pronoun with the ability's own
    source, which for this sentence is the spell doing the exiling rather than
    the spell being exiled. The subject phrase already said which object the
    pronoun means, so the spec is built from it.

    Gated on that one referent, which is the same narrowness
    :func:`_parse_player_exiles_pile` states about its own: only the
    ``target_spells_controller`` seat carries an object for "it" to name, and
    every other player-subject exile keeps its own reading and its own refusal.

    The counters rider is optional and read through the shared
    ``_parse_entering_counters``, so "…with X delay counters on it" and All
    Hallow's Eve's "…with two scream counters on it" are one printed phrase read
    once (CR 121.2 puts them on as part of the move either way).

    Returns None with the cursor unmoved for anything else.
    """
    if player.kind != "target_spells_controller":
        return None
    mark = stream.mark()
    if not stream.accept_word("exiles", "exile"):
        stream.reset(mark)
        return None
    if not stream.accept_word("it"):
        stream.reset(mark)
        return None
    counters = _parse_entering_counters(stream)
    return ast.Exile(
        # The zone is what says this is a spell rather than a permanent, and it
        # is the same word ``nouns`` writes for "target instant or sorcery
        # **spell**" — so the lowering and the picker read one answer to "what
        # may be chosen here", not two.
        ast.TargetSpec("target", ast.ObjectFilter(zone="stack")),
        actor=player,
        counters=counters,
    )


def parse_exile_graveyard_arrivals_this_turn(
    stream: TokenStream,
) -> "ast.ExileGraveyardArrivalsThisTurn | None":
    """``If a card would be put into <whose> graveyard from anywhere this turn,
    exile that card instead.`` (Yawgmoth's Will.)

    CR 614 created by a **spell**. The unbounded spelling of the same sentence
    is a static ability of a permanent and `engine/replacements.py` reads it
    off that permanent's text; this one names a window, so the effect has to
    leave a record behind and the sentence needs a production.

    Read whole or not at all, and non-consuming on refusal, exactly as every
    other replacement-shaped "If …" reader in `statements.py` is: the words up
    to "this turn" are a prefix of the static sentence the registry claims, and
    a half-read line would take that claim away from it.

    The three printed scopes are read in the same vocabulary
    `replacements.graveyard_exile_scope` uses, so one phrase has one meaning
    across the two readings. Which of them an *effect* can arm is the
    lowering's answer.
    """
    mark = stream.mark()
    if not stream.accept_phrase("if", "a", "card", "would", "be", "put", "into"):
        stream.reset(mark)
        return None
    if stream.accept_word("your"):
        whose = "you"
    elif stream.accept_phrase("an", "opponent", "'s"):
        whose = "opponent"
    elif stream.accept_word("a"):
        whose = "any"
    else:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "graveyard", "from", "anywhere", "this", "turn",
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_word("exile"):
        stream.reset(mark)
        return None
    # "…exile **that card** instead" and "…exile **it** instead" are one
    # referent, which is what the static reading's own regex already says.
    if not (stream.accept_phrase("that", "card") or stream.accept_word("it")):
        stream.reset(mark)
        return None
    if not stream.accept_word("instead"):
        stream.reset(mark)
        return None
    return ast.ExileGraveyardArrivalsThisTurn(whose)
