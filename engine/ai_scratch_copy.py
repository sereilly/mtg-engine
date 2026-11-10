"""The scratch copy a rehearsal is carried out on: a copy of the game that
nothing done on it reaches the original from, taken only where one can be
taken, and showing the seat it is taken for only what that seat could see.

* :func:`scratch_copy` — ``copy.deepcopy`` with the card objects shared
  (:func:`_every_card`) and every seat non-interactive, so each prompt takes
  its kind's default; :func:`scratch_copy_with` carries an object into the
  copy with it.
* :func:`mid_resolution` / :func:`held_for_an_answer` — a table owing the
  rest of a resolution is not copied as it stands: what it owes is closures
  over the original. :func:`_detach` cuts a copy loose where the question
  allows it.
* :func:`conceal_from` (CR 400.2, 708.5) — what the seat cannot see, dealt
  again on the rehearsal's own seed (:func:`_rehearsal_seed`, a function of
  :func:`public_counts` and never of the log).
* :func:`_scratch` — the three together: the copy ``ai_rehearsal``
  rehearses a cast on, and the table with nothing cast it is measured
  against.

Asked beyond the rehearsal too: the web's auto-tap tries a payment on a
scratch copy (``web/payment_plan.py``), a provoke's compelled block is asked
on a detached one (``ai_compelled_blocks``), and every reader that must not
weigh a table part-way through a resolution asks :func:`mid_resolution`.
"""

from __future__ import annotations

import zlib

from .entry_awaiting import ENTRY_EVENT, awaited_entries


def _every_card(game):
    """Every card object a zone of *game* holds. A `CardDefinition` is
    immutable and shared — a deck is one object per printing, repeated — so a
    scratch copy shares them too rather than copying a library card by card."""
    for player in game.players:
        for zone in (
            player.hand, player.library, player.graveyard, player.exile,
            getattr(player, "command_zone", ()) or (),
            # Outside the game (CR 400.11a), and the largest pile a seat
            # holds: a simulated seat's sideboard is the rest of its set.
            player.sideboard,
        ):
            yield from zone
        for permanent in player.phased_out:
            yield permanent.card
    for permanent in game.all_permanents():
        yield permanent.card
    for item in game.stack:
        card = getattr(item, "card", None)
        if card is not None:
            yield card


def mid_resolution(game) -> bool:
    """Whether *game* is part-way through carrying something out — an object
    resolving, a loop with steps still owed (``resume_stack``), a resolution
    held for an answer, a CR 616.1 choice outstanding.

    Such a table is not copied as it stands. What it owes is recorded as
    continuations — closures over the game they were made on — and a copy of
    one would run its remaining steps on the **original**. A policy asked in
    that moment gets no rehearsal and falls back to its stated default,
    unless what it is asking can be answered on a copy cut loose from the
    resolution (:func:`_detach`).
    """
    return bool(
        game.resume_stack
        or game.resolving_stack_item is not None
        or game.resolving_seats
        or held_for_an_answer(game)
    )


def held_for_an_answer(game) -> bool:
    """The part of :func:`mid_resolution` no copy can be cut loose from: a
    resolution **waiting on somebody** — a CR 616.1 choice outstanding, an
    object held on the stack for an interactive seat, a queued prompt that
    carries its own continuation. Each of those is a closure the copy would
    still be holding."""
    return bool(
        game.pending_replacement_choices
        or any(
            getattr(item, "finish_resolution", None) is not None
            or getattr(item, "resolution_held", False)
            for item in game.stack
        )
        or any(
            callable(value)
            for choice in game.pending_choices
            for value in choice.data.values()
        )
        # A permanent waiting on its way for its "as it enters" choice (CR
        # 614.12a): the rest of its entry is a closure over this game
        # (``engine/entry_awaiting.py``).
        or bool(awaited_entries(game))
        # …and one handed to an event still waiting on another seat's answer
        # (CR 603.6a): it enters with the others when the original's last
        # answer closes the event, and what its caller does to it then is a
        # closure over this game (``DeferredEntry.then``).
        or any(event.puts for event in getattr(game, "open_entry_events", ()))
    )


def _detach(game, *, owing_nothing: bool = False) -> None:
    """Cut a scratch copy loose from the resolution its original is in the
    middle of: nothing is resolving on the copy and no loop has steps owed.

    For a question whose answer is its own stack object — the mode of a
    triggered ability, chosen as the ability is put on the stack (CR 603.3c)
    while the spell that caused it is still resolving. The copy never finishes
    that spell; what it carries out is the ability, in each mode, and the
    modes are compared with each other.

    *owing_nothing* goes further, for a question about **a card in the
    abstract** — what is this one worth to hold, asked by a search part-way
    through its own resolution: every prompt the copy was owed and every
    object held on its stack for an answer is dropped unanswered. Those are
    the continuations :func:`held_for_an_answer` refuses a copy over, and
    with nothing left to invoke them they are never run.
    """
    game.resolving_stack_item = None
    game.resolving_seats = []
    game.resume_stack = []
    if owing_nothing:
        game.pending_choices = []
        game.pending_replacement_choices = []
        # …and the entries those prompts kept waiting: never finished on the
        # copy, so their permanents never arrive there (they were on no
        # battlefield on the original either).
        game.entries_in_progress = []
        dropped = [
            item for item in game.stack
            if getattr(item, "finish_resolution", None) is not None
            or getattr(item, "resolution_held", False)
        ]
        game.stack = [
            item for item in game.stack
            if not any(item is gone for gone in dropped)
        ]
        # What a dropped object's resolution set off was waiting for it to
        # finish (``StackItem.held_triggers``); with nothing left to finish
        # it, those abilities choose as the next resolution begins, as any
        # trigger still waiting does (``resolve_top_of_stack``).
        for item in dropped:
            held = getattr(item, "held_triggers", None)
            if held:
                game.unannounced_triggers.extend(held[1])
                item.held_triggers = None


def scratch_copy(game):
    """A copy of *game* a cast can be carried out on with nothing reaching
    the original: every seat non-interactive, so each prompt takes its kind's
    default, as it does for a seat the engine plays.

    **When** a prompt is answered is the game's own arrangement and is left
    as it is: a table with a `prompt_driver` (the simulator's) answers each
    one as it is armed, a table without (a web game) once the stack has
    emptied — and a spell whose steps ask two things in a row comes out
    differently under the two. A copy that answered on a schedule of its own
    rehearsed a different cast from the one the executor then made.

    Mana is enforced on the copy exactly as it is on the game. What the
    rehearsed cast itself costs is the planner's question and whoever
    rehearses it supplies that mana (``ai_scoring._rehearse_announcement``);
    everything else that is paid for on the way — "counter that spell unless
    its controller pays {3}", "that player may pay {2}{U}" — is paid out of
    what each seat really has, or the tax every such spell levies would be
    one anybody could afford and the spell would measure as nothing.

    The copy is `copy.deepcopy`, the one `engine/game_history.py` already
    takes for the web app's undo, with the card objects shared
    (:func:`_every_card`).
    """
    return scratch_copy_with(game, None)[0]


def scratch_copy_with(game, carried):
    """:func:`scratch_copy`, and *carried* copied **with** it: an object that
    refers into the game (a prompt holding its stack object) comes back
    referring into the copy."""
    import copy

    memo = {id(card): card for card in _every_card(game)}
    clone, carried = copy.deepcopy((game, carried), memo)
    clone.interactive_seats = set()
    # An event the original is still handing its newcomers (CR 603.6a,
    # ``ZoneFunnelsMixin.entering_together``) is no event on the copy: the
    # block that closes it is the original's, so a permanent the copy entered
    # would join it and never arrive. The same for one waiting across the
    # original's decisions ("each player may put …"): what closes it is the
    # original's loop, and an answer on the copy re-joining the copied event
    # would hand it a permanent nothing on the copy will ever enter — so the
    # copy's prompts carry no event, and its answers enter what they put.
    clone.entry_batch = None
    clone.open_entry_events = []
    for choice in (*clone.pending_choices, *clone.pending_replacement_choices):
        choice.data.pop(ENTRY_EVENT, None)
    return clone, carried


def public_counts(game) -> tuple:
    """The position as every seat can count it: the turn, the step, whose
    turn it is and how many objects are on the stack, and for each seat its
    life, how many cards are in its hand, library, graveyard and exile
    (CR 401.3, 402.3: a library and a hand may be counted at any time), and
    how many permanents it controls and how many of those are tapped.

    Counts and nothing else, so it is the same for every arrangement of what
    a seat cannot see, the same on a game and on every copy of it, and
    nothing a log line, a process-wide counter (``models.next_permanent_id``,
    ``continuous.next_timestamp``) or an object's address can move."""
    seats = []
    for seat, player in enumerate(game.players):
        controlled = list(game.controlled_by(seat))
        seats.append((
            int(getattr(player, "life", 0) or 0),
            len(player.hand), len(player.library), len(player.graveyard),
            len(player.exile),
            len(controlled), sum(1 for permanent in controlled if permanent.tapped),
        ))
    return (
        int(getattr(game, "turn", 0) or 0), str(getattr(game, "current_step", "")),
        getattr(game, "active_player_index", 0), len(game.stack), tuple(seats),
    )


def _rehearsal_seed(game) -> int:
    """The seed a rehearsal's own randomness runs on: a function of the
    position (:func:`public_counts`), so a seed still reproduces a run, and
    nothing to do with the game's real sequence — a coin flipped in a
    rehearsal is a sample, never a look at the flip to come.

    **Never the log.** It was ``7919 * turn + len(game.log)``, so a log line
    added, removed or merged reseeded every later rehearsal's concealment
    (:func:`conceal_from`) and moved AI decisions with no AI code touched:
    Scourge's engine pile merged Carbonize's two lines into one, and a
    Natural Selection, whose worth is a sample over a hidden library, was not
    proposed at T8 (``tests/ai/test_kg4_determinism_rehearsal_seed.py``).
    Nor a process-wide counter: a rehearsal's copy advances those as the
    real game does not, and they carry over from whatever ran before in the
    process. Hashed by ``zlib.crc32``, which no process's hash seed moves."""
    return zlib.crc32(repr(public_counts(game)).encode("utf-8"))


def _card_order(card) -> tuple:
    """Where a card sorts among the cards of a hidden zone: by what it is,
    never by where it was. Two cards that sort alike are the same card to
    anything a rehearsal reads (a deck is one object per printing, repeated)."""
    return (card.name, str(getattr(card, "oracle_id", "") or ""))


def conceal_from(game, seat: int) -> None:
    """Replace what *seat* cannot see on *game* — a scratch copy — with
    something it **could** be (CR 400.2: a library and a hand are hidden
    zones).

    A rehearsal carries a cast out, and a copy of the game is a copy of
    everything in it: the next card of every library, and every card in every
    other player's hand. Read as they stand, a rehearsed Duress knows whether
    there is a card for it to take and a rehearsed Brainstorm knows what it
    will draw — a decision made on what the seat was never shown.

    So, on the copy and before anything is cast on it:

    * **every library is put in a random order** — the seat's own included,
      since it knows what is in it and not where;
    * **each other player's hand is dealt again**, out of that player's hand
      and library pooled: the same number of cards, drawn from everything the
      seat cannot tell apart.

    Each pool is sorted by what the cards are (:func:`_card_order`) before it
    is shuffled, and the shuffle runs on the rehearsal's own seed
    (:func:`_rehearsal_seed`). That is what makes this **exactly** blind
    rather than roughly so: the redeal is a function of *which* cards are
    hidden and of nothing about *where* they are, so two games that differ
    only in which of them an opponent is holding rehearse the same cast the
    same way (``tests/ai/test_ai_hidden_information_census.py``). Shuffled
    from the order they stood in, a fixed permutation of the real hand and
    library would still have dealt the real hand back some of the time.

    **What the seat may see is left where it is**, through the two seams that
    say so for a viewer in the browser: a hand a standing effect reveals to
    it (``revealed_hands.hand_revealed_to`` — Telepathy, Revelation), and the
    top card of a library that is played revealed or that its owner may look
    at (``library_top.top_is_public`` / ``top_is_visible``) — and the top card
    of its own library an effect lets it **play** (CR 601.3: Conspicuous
    Snoop, Radha, Temporal Aperture), which the permission names to it; dealt
    away, a rehearsed cast of it was refused on every copy and a free cast off
    the top was never proposed.

    * **each other player's face-down permanents and spells are dealt again
      too** (CR 708.5: "You can't look at … face-down spells or permanents
      controlled by another player"): what each one hides is pooled with that
      player's library (and hand, when it is dealt) and dealt back onto the
      same objects. A face-down creature is a 2/2 to every reader, but not to
      every *outcome* — one Illusionary Mask put face down is turned up by the
      damage a rehearsed Lightning Bolt would deal it, and what survives is
      the card it hid (``tests/ai/test_ons_w1g1_face_down_concealment.py``).
      The seat's own face-down objects are its own to look at and stay.
    * **and every exiled card face down to the seat** (CR 406.3,
      ``linked_exile.face_down_exiled_cards``) is pooled with its owner's
      hidden cards and dealt back into its place, the records that speak for
      it following the card dealt (:func:`_deal_into_exile`) — the seat's own
      cards included: what an opponent's Shared Fate exiled off its library
      it may not look at, and a copy that kept them knew which of its cards
      that opponent could cast. A card the seat may look at (Shared Fate's
      exiler, Gustha's Scepter's controller) stays.

    What this does not know is what the seat has *been shown and remembers*:
    a card it looked at with a Duress of its own two turns ago, one it
    bounced to that hand, the three it put back with a Brainstorm. Nothing in
    the engine keeps that record — a reveal is an event (``record_reveal``),
    not a standing fact about a card — so every such card is dealt back into
    the unknown. A seat holding a prompt keeps its hand as it is: the prompt
    may name cards in it by position.
    """
    import random

    from .library_top import top_is_public, top_is_visible
    from .revealed_hands import hand_revealed_to

    from .cast_permissions import playable_from_zones

    def playable_on_top(index) -> bool:
        return any(
            entry.get("zone") == "library" and entry.get("index") == 0
            for entry in playable_from_zones(game, index)
        )

    from .face_down import face_down_card, hidden_card_of

    owing = {choice.player_index for choice in game.pending_choices}
    for index, player in enumerate(game.players):
        library = player.library
        seen_on_top = library[:1] if (
            (top_is_visible(game, index) or playable_on_top(index))
            if index == seat else top_is_public(game, index)
        ) else []
        hidden = library[len(seen_on_top):]
        deals_hand = (
            index != seat
            and index not in owing
            and not hand_revealed_to(game, index, seat)
        )
        if deals_hand:
            hidden = [*player.hand, *hidden]
        # CR 708.5: this player's face-down objects, in a fixed order (by id,
        # then stack position) so that the deal is a function of *which*
        # cards are hidden and of nothing about where.
        face_down = [] if index == seat else _face_down_objects(game, index)
        hidden = [*hidden, *(hidden_card_of(obj) for obj in face_down)]
        # CR 406.3: the cards in this player's exile that are face down to the
        # seat — its own included, exiled off its library by an opponent's
        # Shared Fate, which it may not look at — pooled the same way.
        exiled = _face_down_exile_slots(game, index, seat)
        hidden = [*hidden, *(card for _slot, card in exiled)]
        hidden.sort(key=_card_order)
        random.shuffle(hidden)
        if deals_hand:
            held = len(player.hand)
            player.hand[:] = hidden[:held]
            hidden = hidden[held:]
        for obj in face_down:
            obj.card = face_down_card(hidden.pop(_could_be_hidden_by(hidden, obj)))
        for slot, card in exiled:
            _deal_into_exile(game, index, slot, card, hidden.pop())
        library[:] = [*seen_on_top, *hidden]


def _face_down_exile_slots(game, index: int, seat: int) -> "list[tuple[int, object]]":
    """``(position, card)`` for each card in *index*'s exile that is face down
    to *seat* (``linked_exile.face_down_exiled_cards``, which knows who may
    look: Shared Fate's exiler, Gustha's Scepter's controller), in exile
    order — a function of where the cards are in a zone everyone can count,
    never of what they are."""
    from .linked_exile import face_down_exiled_cards

    hidden = face_down_exiled_cards(game, index, viewer_index=seat)
    return [
        (slot, card) for slot, card in enumerate(game.players[index].exile)
        if any(card is each for each in hidden)
    ]


def _deal_into_exile(game, index: int, slot: int, old, dealt) -> None:
    """Put *dealt* in *old*'s place in *index*'s exile, as a new object
    (``exiled_records.distinct_exile_object``: every record of an exiled card
    is keyed by the object), and point every record of *old* at it — the
    exiling permanents' linked entries and the game's register — so what the
    records grant (Shared Fate's play, a look) follows the card dealt."""
    from .exiled_records import RECORDS_ATTR, distinct_exile_object
    from .linked_exile import linked_entries

    new = distinct_exile_object(dealt)
    game.players[index].exile[slot] = new
    for permanent in game.all_permanents():
        for entry in linked_entries(permanent):
            if entry.get("card") is old:
                entry["card"] = new
    for record in getattr(game, RECORDS_ATTR, ()) or ():
        if record.card is old:
            record.card = new


def _could_be_hidden_by(pool: list, obj) -> int:
    """Which card of the shuffled *pool* a face-down *obj* is dealt: the last
    one it **could** be hiding, from what the table saw of how it went face
    down — a creature card under Illusionary Mask (its marker,
    ``face_down.MASK_FACE_DOWN``), a card with a morph cost otherwise (it was
    announced as a morph, CR 702.37c) — and the last card at all when the
    pool holds none such. The pool always holds at least the card *obj* hid.
    """
    from .face_down import MASK_FACE_DOWN, morph_cost

    if getattr(obj, "metadata", {}).get(MASK_FACE_DOWN):
        def could(card):
            return "creature" in (card.type_line or "").lower()
    else:
        def could(card):
            return morph_cost(card) is not None
    for position in range(len(pool) - 1, -1, -1):
        if could(pool[position]):
            return position
    return len(pool) - 1


def _face_down_objects(game, index: int) -> list:
    """Every face-down permanent *index* controls (phased out too, CR 708.5)
    and every face-down spell it controls on the stack, in a fixed order."""
    from .face_down import is_face_down

    permanents = sorted(
        (
            permanent
            for permanent in (
                *game.controlled_by(index), *game.players[index].phased_out,
            )
            if is_face_down(permanent)
        ),
        key=lambda permanent: permanent.permanent_id,
    )
    spells = [
        item for item in game.stack
        if getattr(item, "caster_index", None) == index and is_face_down(item)
    ]
    return [*permanents, *spells]


def _scratch(game, carried, detach, seat):
    """One scratch copy set up for *seat*'s rehearsal: detached if asked
    (``True``, or ``"abstract"`` for :func:`_detach`'s *owing_nothing*), its
    randomness on the rehearsal's own seed and everything *seat* cannot see
    dealt again (:func:`conceal_from`)."""
    import random

    clone, carried = scratch_copy_with(game, carried)
    if detach:
        _detach(clone, owing_nothing=detach == "abstract")
    random.seed(_rehearsal_seed(game))
    conceal_from(clone, seat)
    return clone, carried


__all__ = [
    "conceal_from",
    "held_for_an_answer",
    "mid_resolution",
    "public_counts",
    "scratch_copy",
    "scratch_copy_with",
]
