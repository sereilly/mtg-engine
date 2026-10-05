"""Lowering a **look** (CR 701.20e), the private half of a reveal, and the
library's top.

Every shape here pivots on a pile of cards one player is shown, or nobody is: a
hand looked at; the top cards of a library looked at and then picked from, put
back in an order, cycled or split into piles; a card moved onto the top or off
it with nobody choosing.
A narrowing the flow cannot test must refuse rather than be dropped, and the
reason is sharper here than anywhere: the pile is hidden, so a pick offered
from a wider set than the card prints is one nobody at the table sees happen.

**The first line of this docstring read "search, reveal and look-at" until
Invasion — two families after both had left.** ``search`` went to
``lowering/search.py`` at Visions' first wave and the reveals of a library's
top to ``lowering/reveal.py`` at Tempest's second; "and exile linkage" was a
fourth conjunct before either, and is ``lowering/linked_exile.py``'s now by way
of ``lowering/exile.py``. What the Tempest cut left behind was every reveal of
a **hand** — the bare reveal, the card at random, the two "discards it unless
they pay life" offers, Duress's reveal-and-choose and Stromgald Spy's standing
reveal — a third of this file, filed under a library, reading two records
(``revealed_card``, ``REVEALED_HAND_CARDS``) that ``reveal`` already read and
wrote. They followed at the Phase 0 between Invasion's two waves, with this
module thirty lines under the guard on two growth centres: the revealed hand,
and ``_lower_look_top_pick``. The first is ``reveal``'s. The second is the half
of this module that grows with the pool, so when the guard comes near again,
cut *inside* that function's family rather than along another zone.

The line is the CR's, drawn inside one rule: a reveal (CR 701.20a) shows a card
to every player, and a look shows it "only to the specified player". It is
drawn per **node**, so each side carries one flagged form of the other and says
so. ``_lower_look_top_pick`` takes "**Reveal** a number of cards …" (Eye of
Yawgmoth) as a ``revealed`` key on the look-and-pick procedure the sentence
otherwise is, and ``reveal``'s ``_lower_reveal_hand_and_choose`` takes Mind
Warp's "Look at target player's hand and choose …" as ``looked_at``. Neither
module calls the other.

**Three lodgers, named so the next cut can find them.** None looks at anything
and none touches a library. ``_lower_exile_graveyard`` empties a zone wholesale,
and its node and its production are ``exile``'s.
``_lower_graveyard_pick_onto_battlefield`` emits ``search_library`` and was
filed here when that kind's lowering was — it has been ``search``'s since
Visions — and ``_lower_put_graveyard_position_onto_battlefield`` arrived beside
it, for the reason its own docstring records rather than dresses up. They stay
because a lodger's home has to have room for it, and each of those homes
(``exile``, ``search``, ``zones``) sits nearer the guard than this module now
does.
"""

from ...oracle_types import (PER_OBJECT_SEAT_RECORDS, OracleInstruction,
                             X_FROM_COUNT)
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ._cost_records import cost_record_spec
from ._common import (
    chargeable_card_filter,
    graveyard_position_payload,
    _amount_payload,
    _describe_targets,
    _is_target,
    _restrictions_beyond,
    _targets_only,
)
from ._events import (
    _DEFENDING_PLAYER_EVENTS,
    _back_reference_payload,
)


def _lower_exile_graveyard(node: ast.ExileGraveyard) -> tuple[OracleInstruction, ...]:
    """"Exile target player's graveyard." (Tormod's Crypt.)

    The whole zone, so there is no filter to carry and no card to resolve —
    only which player's graveyard, which is the target description.

    "Exile **all graveyards**" (Bazaar of Wonders) is the same move over every
    seat, and it is the *absence* of a target description that says so: the
    handler sweeps every player when nothing named one, and the picker asks for
    nothing because ``targets`` is not there to be read. One kind rather than
    two, because what happens to each pile is identical — only how many piles
    differs.
    """
    if node.player is None:
        return (OracleInstruction("exile_target_graveyard", "", {"every": True}),)
    return (
        OracleInstruction("exile_target_graveyard", "", _targets_only(node.player)),
    )


def _lower_look_at_hand(
    node: ast.LookAtHand, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Look at target player's hand." (Glasses of Urza.)

    ``look_at_target_hand`` reads one chosen player off the resolution context
    and builds a single reveal from their hand. "Each opponent's hand" would
    need a loop it does not have and "your hand" is not an effect at all, so
    only the targeted form has a contract to lower onto.

    **"Look at target opponent's hand." (Telepathic Spies.)** The same effect
    with the opponent narrowing (CR 102.2/102.3), admitted because the narrowing is
    *carried* rather than dropped: ``_targets_only`` reads ``target_opponent``
    into the same ``opponents_only`` flag ``discard_target_cards`` and
    ``target_loses_life`` already emit, and ``targeting.py``'s player picker
    turns that flag into the seat loop that refuses the caster's own face. A
    lowering that accepted the word and lost the flag would offer the caster
    their own hand, which is the failure this refusal was written to prevent —
    so the fix is the flag reaching the picker, not the word reaching the kind.

    **"Whenever this creature becomes blocked, you may look at defending
    player's hand." (Port Inspector.)** CR 506.2's seat rather than a target, so
    it carries no target description at all and no picker offers it — the
    handler reads the seat the combat fire site froze into the trigger's context
    (CR 603.10). Admitted only under an event that stamped one
    (``_DEFENDING_PLAYER_EVENTS``): with nothing frozen the phrase names nobody,
    and a look falling through to ``context.target`` would show the caster
    whichever hand the resolution happened to be carrying — their own on a
    trigger that chose no target.
    """
    if node.player.kind == "defending_player":
        if event not in _DEFENDING_PLAYER_EVENTS:
            raise LoweringError(
                '"defending player" names a seat this event did not record',
                node=node,
            )
        payload: dict[str, object] = {"who": "defending_player"}
        if node.random_card:
            payload["random_card"] = True
        return (OracleInstruction("look_at_target_hand", "", payload),)
    if node.player.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"no handler for looking at {node.player.kind!r}'s hand", node=node
        )
    payload = dict(_targets_only(node.player))
    if node.random_card:
        # "…**a card at random** in target player's hand" (Urza's Bauble). How
        # much of the hand is shown, emitted only when the card narrows it, so
        # Glasses of Urza's payload stays byte-identical.
        payload["random_card"] = True
    return (OracleInstruction("look_at_target_hand", "", payload),)


def _lower_separate_library_top_into_piles(
    node: "ast.SeparateLibraryTopIntoPiles",
) -> tuple[OracleInstruction, ...]:
    """Phyrexian Portal's whole procedure, one instruction.

    The splitter travels as a *targets* description rather than as a bare seat
    word, because "target opponent" is a choice made at announcement (CR
    601.2c) and the picker reads that payload - a card whose splitter was a
    literal would offer no picker and let the client send a bare activation.

    The count is payload; the shape is not. Two piles, face down, one exiled
    and the other searched is what the card *is*, and a wording that differed
    refuses at the production rather than arriving here as another key.
    """
    if node.splitter.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"no pile split names {node.splitter.kind!r} as its divider",
            node=node,
        )
    payload: dict[str, object] = {"count": _amount_payload(node.count)}
    _describe_targets(payload, node.splitter)
    return (
        OracleInstruction("separate_library_top_into_piles", "", payload),
    )


def _lower_look_top_cycle_for_life(
    node: "ast.LookTopCycleForLife",
) -> tuple[OracleInstruction, ...]:
    """Lim-Dul's Vault's whole procedure, one instruction (CR 701.24).

    Both numbers travel as payload for the reason every parameter in this
    pipeline does: a card cycling three cards for 2 life needs no code. What
    does *not* travel is the shape - the bottom, the shuffle and the stack on
    top are the effect itself, so a wording that sorted them elsewhere refuses
    at the production rather than arriving here as a fourth key.
    """
    return (
        OracleInstruction(
            "look_top_cycle_and_stack", "",
            {
                "count": _amount_payload(node.count),
                "life_cost": _amount_payload(node.life_cost),
            },
        ),
    )


def _lower_put_library_top_into_hand(
    node: "ast.PutLibraryTopIntoHand", produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"Put **that many** cards from the top of your library into your hand."
    (Scroll Rack.)

    Not a draw, which is the whole reason there is an instruction here rather
    than a ``Draw`` — see the node. What the lowering has to settle is the
    count, and on the one card printing this sentence it is a back-reference to
    the exile in front of it: ``_back_reference_payload`` decides where it is
    read from, once, so a card printing a number instead needs no code.
    """
    if isinstance(node.count, ast.ThatMuch):
        payload: dict[str, object] = {
            "amount": 0, **_back_reference_payload(node.count, produced, None),
        }
    else:
        payload = {"amount": _amount_payload(node.count)}
    return (OracleInstruction("put_library_top_into_hand", "", payload),)


def _lower_graveyard_top_to_library(
    node: ast.GraveyardTopToLibrary,
) -> tuple[OracleInstruction, ...]:
    """"If the top card of target player's graveyard is a creature card, put
    that card on top of that player's library." (Guiding Spirit.)

    Only a chosen player has a flow, for :func:`_lower_look_at_library_top`'s
    reason one function down: the handler reads one seat off the resolution
    context, and a phrase naming several would need a loop it does not have.

    The filter is tested against a **card**, not a permanent — a graveyard holds
    cards (CR 400.1) — so it goes through the card matcher's own gate, which
    refuses a narrowing that matcher cannot answer rather than dropping it. A
    dropped narrowing here is a card moved when the printed sentence said it
    should stay.
    """
    if node.player.kind != "target_player":
        raise LoweringError(
            f"no flow reads the top of {node.player.kind!r}'s graveyard",
            node=node,
        )
    described = card_only_filter(node.filter.to_payload())
    if described is None:
        raise LoweringError(
            "the graveyard's top card cannot be tested for this", node=node
        )
    return (
        OracleInstruction(
            "graveyard_top_to_library", "",
            {"filter": described, **_targets_only(node.player)},
        ),
    )


def _lower_look_at_library_top(
    node: ast.LookAtLibraryTop,
) -> tuple[OracleInstruction, ...]:
    """"Look at the top five cards of target player's library. You may then
    have that player shuffle that library." (Visions.)

    Only a chosen player has a contract to lower onto, for the reason
    :func:`_lower_look_at_hand` gives: the handler reads one player off the
    resolution context, and "each opponent" would need a loop it does not have.

    How many cards and whether the shuffle is offered are both payload. The
    number is obvious; the offer is the one that matters, because the handler
    that reads it today derived the same fact for Natural Selection by matching
    a substring of the card's oracle text — a card printing the offer in any
    other words would have been given a prompt with the option missing.
    """
    # "…of **defending player's** library" (Coral Fighters). CR 506.2's seat,
    # which the combat fire site froze into the trigger's context — not a
    # target, so no picker offers it and nothing here describes one. Admitted
    # only for the bottoming offer below, which is the one card in the pool
    # printing it: a *targeted* look is a spell's choice and this one is a fact
    # about a combat, and the handler reads them from different places.
    defending = node.player.kind == "defending_player"
    # "Look at the top four cards of **your** library, then put them back in
    # any order." (Sage Owl.) The looker's own pile, which is its own kind and
    # not this one with a seat swapped: `reorder_target_library_top` is
    # registered in `engine/targeting.py` as targeting a player, so lowering
    # Sage Owl's trigger onto it would put an ability on the stack asking for a
    # target its printed line never offers. Nothing is looked at *and* nothing
    # is chosen, so the rearrange is the whole effect and the other two offers
    # refuse.
    if node.player.kind == "you":
        if not node.may_reorder or node.may_shuffle or node.may_bottom:
            raise LoweringError(
                "the own-library look only rearranges what it saw", node=node
            )
        # "{X}: Look at the top **X** cards of your library, then put them back
        # in any order." (Soothsaying.) The announced X (CR 601.2b via
        # CR 602.2b), which is not a number until the ability is on the stack —
        # so it travels as the string every amount in this engine travels as
        # and ``handlers/_common.resolve_amount`` turns it into one at
        # resolution, which the handler already asks it to do.
        #
        # This refused outright before, and the refusal was invisible: the
        # *line* still classified as an activated ability, so the card compiled
        # supported carrying an ability part with no instruction behind it. It
        # activated, charged X mana and did nothing at all —
        # ``support_report --hollow-lines`` and ``parse_coverage`` were the only
        # two instruments that could see it.
        return (
            OracleInstruction(
                "reorder_own_library_top", "",
                {"amount": _amount_payload(node.count)},
            ),
        )
    # "…of **target opponent's** library" (Precognition). The same targeted
    # look, narrowed to which seats the picker may offer (CR 102.2/102.3) — that
    # narrowing rides on the targets description ``_targets_only`` builds, and
    # the handler reads ``context.target`` either way. It was refused because
    # the one card printing a targeted look happened to say "player"; reading it
    # as a plain target player instead would have let the caster look at their
    # own library, which is a card that does nothing.
    if node.player.kind not in (
        "target_player", "target_opponent",
    ) and not (defending and node.may_bottom):
        raise LoweringError(
            f"no handler looks at the top of {node.player.kind!r}'s library", node=node
        )
    if not isinstance(node.count, ast.Fixed):
        raise LoweringError("the library look needs a printed number", node=node)
    payload: dict[str, object] = {
        "amount": node.count.value,
        "may_shuffle": node.may_shuffle,
    }
    if defending:
        payload["who"] = "defending_player"
    else:
        payload.update(_targets_only(node.player))
    # "**You may put that card on the bottom of that player's library.**"
    # (Coral Fighters.) Its own kind rather than a flag on the look, for
    # `may_reorder`'s stated reason one field over: the permission is enforced
    # where the prompt is answered, so a card that only looks can never be
    # handed the offer.
    if node.may_bottom:
        if node.may_shuffle or node.may_reorder:
            raise LoweringError(
                "one look offers one thing to do with what it saw", node=node
            )
        return (
            OracleInstruction("look_at_library_top_then_bottom", "", payload),
        )
    # "…then put them back in any order" is the *other* handler, not a flag on
    # this one: `may_reorder` is enforced where the prompt is answered, so a
    # card that only looks can never be handed a rearrangement.
    kind = (
        "reorder_target_library_top" if node.may_reorder
        else "look_at_target_library_top"
    )
    return (OracleInstruction(kind, "", payload),)


def _lower_look_top_pick(
    node: ast.LookTopPickToHand, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Look at the top three cards of your library. Put one of those cards
    into your hand and the rest on the bottom of your library in any order.
    …" (See the Truth.) The handler asks its controller through the
    pending-choice queue when cast from the hand, and skips the choice
    entirely when the cast came from anywhere else — the conditional reads
    ``OracleExecutionContext.cast_from_zone``."""
    payload: dict[str, object] = {}
    # "Reveal a number of cards … equal to **the sacrificed creature's
    # power**." (Eye of Yawgmoth.) A quantity the ability's own cost recorded,
    # on the ``x_from_count`` channel the dispatcher resolves into the X this
    # handler already reads for Sealed Fate's "the top X cards" — so the count
    # is the one the payment path kept (CR 608.2h), read by the evaluator every
    # other cost-paid amount goes through.
    paid = cost_record_spec(node.count, node)
    if paid is not None:
        payload["amount"] = "x"
        payload[X_FROM_COUNT] = paid
    # "Look at **that many** cards" (Garruk's Harbinger): the count is the
    # firing event's number, read out of the trigger's captured context by the
    # same channel every other back-reference uses. Demanded of the event rather
    # than assumed: under a trigger that records no quantity the words name
    # nothing, and a silent zero would look at no cards at all.
    elif isinstance(node.count, ast.ThatMuch):
        payload.update(_back_reference_payload(node.count, frozenset(), event))
    else:
        amount = _amount_payload(node.count)
        # "…the top **X** cards" (Sealed Fate). The announced value (CR 601.2b),
        # which the handler resolves against ``context.x_value`` — the same
        # channel every other counted zone effect reads. Admitted beside a
        # printed number rather than instead of it: what is refused is a count
        # this handler has no way to take at all, which is what "the pick takes
        # a fixed count" was really saying.
        if amount != "x" and (not isinstance(amount, int) or amount <= 0):
            raise LoweringError("the look-top pick takes a fixed count", node=node)
        payload["amount"] = amount
    # "Put **two** of them into your hand" (Ancestral Memories). Emitted only
    # when the card prints a number other than one, so every payload written
    # before this is byte-identical.
    picks = _amount_payload(node.pick_count)
    if not isinstance(picks, int) or picks <= 0:
        raise LoweringError("the look-top pick takes a fixed pick count", node=node)
    if picks > 1:
        # Several picks are a *chain* of one-card prompts (see
        # ``_resolve_look_top_pick``), and each link looks at what is left of
        # the same pile. So a destination that puts the card **back** in that
        # pile refuses: "puts one of them back on top of their library"
        # (Ashnod's Cylix) names a single card by construction, and a chain
        # spelled that way would re-offer the card it just placed. The two
        # destinations that take the card out of the library entirely — a hand
        # (Ancestral Memories) and exile (Ancestral Knowledge) — are the chain's
        # whole vocabulary, and ``optional`` rides along because "exile **any
        # number of** them" is a chain the looker may stop at any link.
        if node.pick_destination not in ("hand", "exile"):
            raise LoweringError(
                "several picks leave the library, and this destination puts one "
                "back in it",
                node=node,
            )
        payload["pick_count"] = picks
    if node.filters:
        described = [chargeable_card_filter(filt) for filt in node.filters]
        if any(entry is None for entry in described):
            raise LoweringError(
                "the pick cannot test this restriction on a card", node=node
            )
        payload["filters"] = tuple(described)
    if node.optional:
        payload["optional"] = True
    if node.rest_order != "any":
        payload["rest_order"] = node.rest_order
    if node.rest_destination != "library_bottom":
        payload["rest_destination"] = node.rest_destination
    if node.pick_destination != "hand":
        payload["pick_destination"] = node.pick_destination
    if node.all_to_hand_if_cast_elsewhere:
        payload["all_to_hand_if_cast_elsewhere"] = True
    # "**Reveal** a number of cards …" (Eye of Yawgmoth): CR 701.20a's public
    # look, which the handler records. Emitted only when printed, so every
    # payload in the family stays byte-identical.
    if node.revealed:
        payload["revealed"] = True
    # "…You gain life equal to **that card's mana value**." (Reviving Vapors.)
    # The record the pick is asked to write, named by the key the sentence
    # behind it reads — see ``_records._PRODUCES_FOR_PAYLOAD``.
    if node.records_pick_mana_value:
        if picks != 1 or node.pick_destination != "hand":
            raise LoweringError(
                "only a single card taken into a hand has one mana value to record",
                node=node,
            )
        payload["record_pick"] = "its_mana_value"
    # Who looks, when the sentence names them. Only the one seat this handler
    # can find without a second question: "target player" is chosen as the
    # ability is activated (CR 602.2b) and arrives as ``context.target``.
    # Anything else refuses rather than defaulting to the controller — a look
    # at the wrong library is a card doing something it never said, and the
    # pile is hidden, so nobody would see it happen.
    if node.looker is not None:
        if node.looker.kind != "target_player":
            raise LoweringError(
                "the look-top pick reads the library of the player the ability "
                "chose",
                node=node,
            )
        payload["looker"] = "target_player"
    # "…the top X cards of **target opponent's** library" (Sealed Fate). The
    # pile is the chosen player's and the decisions are the caster's, which is
    # the other half of the seat question ``looker`` answers with one word.
    # Only a chosen seat, for ``looker``'s reason: an unchosen one would send
    # the look at whichever library the resolution happened to be carrying, and
    # the pile is hidden, so nobody would see it happen.
    if node.pile_owner is not None:
        if node.pile_owner.kind not in ("target_player", "target_opponent"):
            raise LoweringError(
                "the look-top pick reads the library of the player the spell "
                "chose",
                node=node,
            )
        payload["pile_owner"] = node.pile_owner.kind
        _describe_targets(payload, node.pile_owner)
    return (OracleInstruction("look_top_pick_to_hand", "", payload),)


def _lower_look_top_exile_random(
    node: ast.LookTopExileRandom,
) -> tuple[OracleInstruction, ...]:
    """"Look at the top eight cards of your library. Exile four of them at
    random, then put the rest on top of your library in any order." (Orcish
    Librarian.)

    Both counts are fixed numbers the card prints. A back-reference would have
    to name an event this statement has no access to, and an X would have to
    survive to a resolution that happens after the cost is paid — neither is a
    shape any printing of this sentence has, so both refuse rather than
    resolving to a silent zero.
    """
    looked = _amount_payload(node.count)
    exiled = _amount_payload(node.exile_count)
    if not isinstance(looked, int) or looked <= 0:
        raise LoweringError("the look-and-exile takes a fixed count", node=node)
    if not isinstance(exiled, int) or exiled <= 0:
        raise LoweringError("the random exile takes a fixed count", node=node)
    if exiled > looked:
        raise LoweringError(
            "more cards are exiled than are looked at", node=node
        )
    return (
        OracleInstruction(
            "look_top_exile_random", "",
            {"amount": looked, "exile_count": exiled},
        ),
    )


def _lower_graveyard_pick_onto_battlefield(
    node: ast.PutOntoBattlefield,
) -> tuple[OracleInstruction, ...] | None:
    """"Put **a** creature card from the graveyard of <player> onto the
    battlefield **under its owner's control**." (Glyph of Reincarnation.)

    Here rather than beside the rest of the "put … onto the battlefield" family
    in ``lowering/zones``, because what it emits decides the family: no
    ``target`` is printed, so the card is not chosen until the effect resolves
    (CR 115.1b), and a pick made during resolution out of a named zone is a
    *search prompt* — the same instruction ``search._lower_search_library``
    emits, narrowed to a graveyard. Sending it to the reanimation handler
    instead would have made it a cast-time target, which is a different card:
    the graveyard it comes out of is named by a referent nobody can evaluate
    until the earlier sentence has run.

    Returns None for every other "put onto the battlefield", so ``lower.py``
    falls through to that family and a line this is not keeps the refusal it
    already had.
    """
    target = node.target
    if not isinstance(target, ast.TargetSpec) or _is_target(target):
        return None
    filt = target.filter
    if filt.zone != "graveyard" or filt.zone_owner is None:
        return None
    record = PER_OBJECT_SEAT_RECORDS.get(filt.zone_owner.kind)
    if record is None:
        # Every *other* graveyard referent — "your graveyard", "that player's"
        # — is a seat the resolving player knows without any earlier step
        # having recorded it, and none of them is this shape. Handing them back
        # rather than refusing keeps this production additive.
        return None
    if not filt.is_card or filt.card_types != ("creature",):
        raise LoweringError(
            "this graveyard pick only moves creature cards", node=node
        )
    if _restrictions_beyond(
        filt, frozenset({"card_types", "is_card", "zone", "zone_owner"})
    ):
        raise LoweringError(
            "no graveyard pick reads a card narrowed this way", node=node
        )
    if not node.under_owners_control or node.tapped:
        # The card enters under whoever owns the graveyard it left, and that is
        # what the printed rider says. A sentence naming some *other* seat would
        # need a second reference here rather than this one standing in for it;
        # one naming "tapped" an entry state the search prompt does not carry.
        raise LoweringError(
            "this graveyard pick only puts the card back, untapped, under its "
            "owner's control", node=node,
        )
    return (
        OracleInstruction(
            "search_library",
            "",
            {
                "count": 1,
                "card_type": "creature",
                # A graveyard is an open zone, so nothing is revealed and
                # nothing is shuffled — the prompt is a pick, and the resolver
                # already tells the two apart by the zone it was armed with.
                "zones": ["graveyard"],
                "restrictions": {},
                "destination": "battlefield",
                # Whose graveyard, and whose battlefield. The same seat by
                # CR 404.1 — a card in a graveyard is in its owner's — but
                # written twice because the card prints both halves, and a
                # reader that inferred the second would be inferring it for
                # every card that names only the first.
                "zone_owner": record,
                "battlefield_owner": record,
            },
        ),
    )


def _lower_put_graveyard_position_onto_battlefield(
    node: "ast.PutGraveyardPositionOntoBattlefield", event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Put **the top creature card of defending player's graveyard** onto the
    battlefield under your control." (Bone Dancer.)

    Here beside ``_lower_graveyard_pick_onto_battlefield`` because the two
    answer one question — which card leaves a graveyard for the battlefield
    when the sentence names no target — and differ in the one way that decides
    the instruction: that one is a *pick* made as the effect resolves
    (CR 115.1b), and this one names the card by its **position** in an ordered
    pile (CR 404.2), so nobody chooses and no prompt is armed.

    That pair is not in ``lowering/zones``, where the *targeted* reanimation
    lives, and the honest reason is worth recording rather than dressing up:
    the sibling arrived here because of the instruction it emits, this one
    arrived beside the sibling, and ``zones`` is at its thousand-line guard with
    no seam this round found. A later round that splits that module should take
    the three readings of "put a card onto the battlefield" with it.

    Three refusals, each in the direction that cannot widen the effect.

    The **seat** must be one the firing event froze. "Defending player" is
    CR 506.2's, stamped by the combat fire sites, and under any other event the
    words name nobody — the handler would find no pile while the card compiled
    supported. ``graveyard_position_payload`` is the shared gate every reader of
    the phrase runs through; the seat set is *passed* rather than added to its
    default, because a cost paid out of the defending player's graveyard is a
    shape the payment path has no seat for.

    The **count** must be one: a position naming several cards is a sentence
    this handler does not move.

    ``under your control`` is **required**, and it is the whole of the card at a
    table. CR 404.1 puts the card in its owner's graveyard, so the default
    arrival (CR 400.3) is under the seat being attacked — a sentence that shed
    the rider would hand the defending player a creature.
    """
    payload = graveyard_position_payload(
        node.position, seats=frozenset({"defending_player"})
    )
    if payload is None:
        raise LoweringError(
            "no handler reads that graveyard position onto the battlefield",
            node=node,
        )
    if event not in _DEFENDING_PLAYER_EVENTS:
        raise LoweringError(
            "'defending player's graveyard' names the seat the combat "
            "froze, and this event records none",
            node=node,
        )
    if payload.get("count") != 1:
        raise LoweringError(
            "the graveyard-position reanimation moves one card", node=node
        )
    if not node.under_your_control:
        raise LoweringError(
            "the graveyard-position reanimation only puts the card under your "
            "control", node=node,
        )
    payload["graveyard_owner"] = payload.pop("owner")
    return (
        OracleInstruction("reanimate_graveyard_position", "", payload),
    )
