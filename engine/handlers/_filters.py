"""Whether a card, a permanent or a seat **answers a filter payload**.

The handler half of what a printed noun phrase means: the payload the grammar
writes (``engine.grammar.ast.ObjectFilter.to_payload``), asked of one object.
Two matchers, because the object is two kinds of thing. A permanent has
computed characteristics, so :func:`permanent_matches_filter` reads its types,
colours, P/T and keywords through the layer system; a card in a zone has none,
so :func:`_card_matches_filter` and :func:`graveyard_card_matches` read what is
printed on it. The printed state words ("tapped", "attacking", "enchanted")
are one table, :data:`_STATE_TESTS`, with its readers beside it, and the two
seat narrowings — "each player who controls a white creature", "each player
who sacrificed a Plains this way" — are the same question asked of a player.

These are the pure halves: ``engine/subject_filters.py`` builds the one answer
a caller holding a game asks (``subject_matches``) on top of them.

A floor, split out of ``_common`` at the 2,000-line cap's split round. It reads
``_chosen``'s keys — a filter still carrying a chosen-word narrowing is refused
— and nothing else of the handler package.
"""

from __future__ import annotations

from ..layer_bridge import printed_shape, printed_supertypes
from ..oracle_types import SACRIFICED_CARDS_BY_SEAT
from ..models import Permanent
from ..object_colors import is_multicolored
from ..counted_names import card_answers_to_name
from ..search_filters import card_has_type, name_key
from ._chosen import (CHOSEN_CARD_TYPE, COLOR_CHOSEN_THIS_WAY_KEY,
                      NAMED_FROM_KEY, _CHOSEN_SUBTYPE_KEYS)


def _zone_card_colors(card, *, game=None, owner=None) -> tuple[str, ...]:
    """The colours of a card in a zone, for the three keys below.

    One call rather than three, because the three keys are three readings of
    one fact and the version of this matcher that spelled it three times had
    already drifted once -- ``exclude_colors`` re-fetched the attribute where
    its two neighbours had cached it.
    """
    from ..object_colors import card_colors

    return tuple(card_colors(game, card, owner))


def _zone_card_creature_types(
    card, *, printed=(), game=None, owner=None
) -> frozenset[str]:
    """The creature types of a card in a zone, for the two subtype keys.

    ``printed`` is what the caller already read off the type line, returned
    unchanged whenever nothing is rewriting it -- so the common path costs one
    board scan and the answer for every card in the pool but one is byte the
    same as before this existed.
    """
    from ..object_creature_types import creature_type_override_for_seat

    if "creature" not in (getattr(card, "type_line", "") or "").lower():
        return frozenset(printed)
    override = creature_type_override_for_seat(game, owner)
    return frozenset({override}) if override is not None else frozenset(printed)


def _card_matches_filter(
    card, filt: dict, *, game=None, owner=None, zone: str | None = None,
    effect_spell: str | None = None,
) -> bool:
    """Whether a *card* — not a permanent — answers a filter payload.

    A card in a zone has no computed characteristics, so the shared matcher
    (which asks ``has_type`` of a battlefield object) cannot answer here. Only
    what is printed on the card is testable — its type line and its name — and
    ``engine/subject_filters.py``'s ``CARD_ONLY_FILTER_KEYS`` is the list of
    exactly which keys that comes to. The lowerings refuse anything else rather
    than counting it as if it were not there.

    Types and subtypes both come off the printed line through the *same* reader
    the layer seed uses. The type test used to ask ``primary_type``, which
    collapses a multi-type line to one word — so "Artifact Creature — Construct"
    is a creature there but not an artifact, and "discard an artifact card"
    would have refused a card printed as one. CR 205.2a: a card has **every**
    type printed on it. No card in the pool asks the question the difference
    changes, which is why this is a widening of the reader rather than a fix
    with a card behind it.
    """
    # "…a creature card **of the chosen type**" (Belbe's Portal). The record is
    # on the ability's *source* (CR 614.1c), which this pure half does not
    # have; a resolver holding it turns the key into ``subtype_filter`` first
    # (``_resolve_chosen_subtype``). Surviving to here means nobody could, and
    # ignoring it would offer every creature card in the hand — so it refuses,
    # exactly as ``permanent_matches_filter`` does for the same two keys.
    if any(filt.get(key) for key in _CHOSEN_SUBTYPE_KEYS):
        return False
    # "…cards **of that color**" with nothing behind the pronoun: the colour is
    # in a resolution's scratchpad and a reader holding one resolves it into
    # ``color_filter`` first. Refused for the reason above.
    if filt.get(COLOR_CHOSEN_THIS_WAY_KEY) or filt.get("color_of_your_choice"):
        return False
    types, subtypes = printed_shape(card)
    wanted = filt.get("type_filter")
    if wanted == "artifact_or_enchantment":
        # "an **artifact or enchantment** card" (Charmed Griffin). The one
        # ``type_filter`` value that is not a printed type: the permanent
        # matcher has special-cased it since it was introduced and this reader
        # never did, so the same two printed words matched every permanent on a
        # battlefield and **no card in any zone**. A filter key one matcher
        # honours and the other silently drops is the asymmetric-gate class,
        # and it fails in the quiet direction — the effect reports "nothing
        # qualifies" over a hand that is full of qualifying cards.
        #
        # Rewritten into the union spelling below rather than answered here, so
        # the exclusions and the rest of the filter still run.
        wanted = ("artifact", "enchantment")
    wanted_types = tuple(wanted) if isinstance(wanted, (list, tuple)) else ((wanted,) if wanted else ())
    if wanted_types and not any(t in types for t in wanted_types):
        return False
    # "Discard a **Shrine** card" (Sanctum of Shattered Heights). A subtype is
    # its own key, OR'd across alternatives exactly as the permanent matcher
    # OR's them, because "Djinn or Efreet" is one phrase either way.
    wanted_sub = filt.get("subtype_filter")
    wanted_subtypes = (
        tuple(wanted_sub) if isinstance(wanted_sub, (list, tuple))
        else ((wanted_sub,) if wanted_sub else ())
    )
    # The printed subtypes unless a board-wide static says otherwise -- "the
    # same is true for … creature cards you own that aren't on the battlefield"
    # (Conspiracy) is what makes an off-battlefield creature type more than what
    # is printed, and it is a property of a *seat*, so a caller that cannot say
    # whose card this is gets the printed answer it always got. Exactly the
    # arrangement `_zone_card_colors` already has for CR 202.2 further down this
    # function, and asked here rather than at the top because only the two
    # subtype tests want the computed answer -- a card's *card types* are not
    # something anything in the pool rewrites off the battlefield.
    if wanted_subtypes or filt.get("subtype_filter_all"):
        subtypes = _zone_card_creature_types(
            card, printed=subtypes, game=game, owner=owner
        )
    if wanted_subtypes and not any(s in subtypes for s in wanted_subtypes):
        return False
    # The conjunction spelling, AND'd — see `subtype_filter_all` in
    # permanent_matches_filter.
    wanted_all_subtypes = filt.get("subtype_filter_all") or ()
    if wanted_all_subtypes and not all(s in subtypes for s in wanted_all_subtypes):
        return False
    # "**nonland** card" (Amnesia). The negative of the test above, off the same
    # printed line and OR'd the same way: a card naming *any* excluded type is
    # out, which is what "noncreature, nonland" means when both are printed.
    excluded = filt.get("exclude_types") or ()
    if excluded and any(name in types for name in excluded):
        return False
    # The card-level twin of `type_filter_all`: "an **artifact creature** card".
    # Off the printed type line, which for a card in a zone is the whole of
    # what there is (CR 613.1).
    wanted_all_types = filt.get("type_filter_all") or ()
    if wanted_all_types:
        printed = (card.type_line or "").lower()
        if not all(name in printed for name in wanted_all_types):
            return False
    # "Discard a **legendary** card" (Niambi, Esteemed Speaker). Off the printed
    # line, which for a card in a zone is the whole of what there is (CR 613.1).
    wanted_supertypes = filt.get("supertypes") or ()
    excluded_supertypes = filt.get("exclude_supertypes") or ()
    if wanted_supertypes or excluded_supertypes:
        held = printed_supertypes(card.type_line)
        if not all(word in held for word in wanted_supertypes):
            return False
        if any(word in held for word in excluded_supertypes):
            return False
    # "…**except for basic lands**" / "…**other than a basic land**" (Eye of
    # Singularity prints both). The *pair* — CR 205.4a's Basic supertype and
    # the land card type — rather than the supertype alone: an exclusion by
    # supertype would be a different sentence, and the only reason it happens
    # to name the same cards today is that no printed non-land carries Basic.
    # Read off the printed line, which is what every other type read in this
    # pure matcher does.
    if filt.get("exclude_basic_lands"):
        printed_line = (card.type_line or "").lower()
        if "land" in printed_line and "basic" in printed_supertypes(card.type_line):
            return False
    # "creature cards **with mana value 3 or less**" (Idol of Endurance). Mana
    # value is one of the few characteristics a card has *everywhere* — CR 202.3
    # computes it from the printed mana cost, so unlike power or a keyword it
    # needs no battlefield object to be asked of. Same bound reader the permanent
    # matcher uses, so "3 or less" means one thing in both zones.
    if not _comparison_holds(filt.get("mana_value"), int(getattr(card, "cmc", 0) or 0)):
        return False
    # "the number of **white** cards in their hand" (Inquisition); "**white**
    # cards in their graveyards" (Nameless Race). The printed colours
    # (CR 202.2, derived from the mana cost) unless a board-wide static says
    # otherwise -- "the same is true for ... nonland cards you own that aren't
    # on the battlefield" (Celestial Dawn) is the one thing in the pool that
    # makes an off-battlefield colour more than what is printed, and it is a
    # property of a *seat*, so a caller that cannot say whose card this is gets
    # the printed answer it always got.
    colors = _zone_card_colors(card, game=game, owner=owner)
    color_filter = filt.get("color_filter")
    if color_filter and color_filter not in colors:
        return False
    # "…discard a **red or green** card" (Surge of Strength). The union
    # spelling of the key above — one filter carrying several colours, which is
    # how the noun parser reads a shared-head disjunction ("red or green card"
    # is one noun phrase, not two) — OR'd exactly as the permanent matcher OR's
    # it. Off the same printed colours and for the same reason (CR 202.2).
    any_colors = filt.get("any_colors")
    if any_colors and not any(color in colors for color in any_colors):
        return False
    # "a **nonblack** card" (Krovikan Sorcerer). The negative of the test above,
    # off the same printed colours, and OR'd the same way a type exclusion is: a
    # card carrying *any* excluded colour is out, which is what "nonblack,
    # nonred" would mean printed together.
    excluded_colors = filt.get("exclude_colors") or ()
    if excluded_colors and any(color in colors for color in excluded_colors):
        return False
    # "a **multicolored** creature card" (Dragon Arch). CR 105.2b: two or more
    # colours, off the same colours every test above reads — the printed ones
    # (CR 202.2) unless a seat-wide static says otherwise — and through the one
    # definition of the word, so a card in a hand and a permanent on the
    # battlefield cannot be multicoloured by two different counts.
    if filt.get("multicolored") and not is_multicolored(colors):
        return False
    # "…for each **Mountain and red** card in it" (Baleful Stare). A union
    # across two *axes* — CR 205.3 subtype against CR 105 colour — which the
    # keys above cannot say because they are AND'd: ``subtype_filter`` plus
    # ``color_filter`` names a red Mountain, a card nothing prints. The card
    # twin of the permanent matcher's reading of the same key, alternative for
    # alternative, off what is printed where that one asks the layers: a card
    # answering two of the alternatives is still one card, because the union is
    # a test of each card and never a tally of qualities.
    any_classes = filt.get("any_classes")
    if any_classes:
        # Idempotent over the read the two subtype keys above may already have
        # made, so the three subtype tests cannot disagree about a card.
        class_subtypes = _zone_card_creature_types(
            card, printed=subtypes, game=game, owner=owner
        )

        def _class_holds(entry) -> bool:
            axis, name = entry[0], entry[1]
            if axis == "color":
                return name in colors
            if axis == "card_type":
                # The third element is a colour negation on this one member
                # ("land or **nonblack** creature"), as it is on a permanent.
                excluded = entry[2] if len(entry) > 2 else ()
                return name in types and not any(c in colors for c in excluded)
            if axis == "subtype":
                return name in class_subtypes
            # An axis nothing here reads refuses rather than being ignored: a
            # dropped alternative widens the union to every card.
            return False

        if not any(_class_holds(entry) for entry in any_classes):
            return False
    # "…with the same name as **that spell**" with no resolution behind it: the
    # name is in a trigger's context, and a reader holding one turns the key
    # into ``named`` first (``count_spec_in_resolution``). Refused for the
    # chosen-subtype keys' reason at the top — ignoring it counts every card.
    if filt.get(NAMED_FROM_KEY):
        return False
    named = filt.get("named")
    # Through `name_key`, so the parser's rendering of a legendary name
    # ("chandra , flame 's catalyst") and Oracle's spelling of it compare equal —
    # the same reduction a search's named restriction already uses. And through
    # the one reader of "is this card named N?": CR 709.4a gives a split card
    # both halves' names, and a card in a graveyard may *count as* a card of a
    # name it does not have to the spell that is asking (``counted_names``).
    return not named or card_answers_to_name(
        card, str(named), zone=zone, effect_spell=effect_spell,
    )


def permanent_effective_colors(perm: Permanent) -> set[str]:
    """The color symbols a permanent currently has.

    Computed through the layer system, so a colour override (the laces) is an
    ordinary layer-5 continuous effect rather than a step in a precedence chain
    written out by hand — and a copy's colours arrive in layer 1 before it, as
    the copiable value CR 707.2a says they are.
    """
    return perm.effective_colors


def graveyard_card_matches(spec: dict, card) -> bool:
    """Whether *card* is a legal choice for a graveyard target described by
    *spec* — or by an instruction payload, which carries the same key names
    because the spec is derived from it.

    ``permanent_matches_filter``'s sibling one zone over, and here for the same
    reason: **one predicate, three readers.** The picker that offers the card,
    the cast-time re-check that admits it (idiom #9) and the handler that takes
    it were three copies, and they disagreed. The re-check asked only "is it a
    creature card?", so Reconstruction — "Return target **artifact** card from
    your graveyard to your hand" — refused every artifact its own picker
    offered, and with no creature in the pile could not be cast at all.

    The narrowed type is containment in the printed type line rather than
    ``primary_type``, because CR 205.2 makes an Ornithopter an artifact card
    *and* a creature card. The bare case keeps ``primary_type``, which is what
    the reanimation handlers ask of the card they put onto the battlefield.
    """
    card_types = tuple(spec.get("card_types") or ())
    # Through ``card_has_type``, not ``primary_type``: a card has **every** type
    # its line names (CR 205.2, idiom 15), so an Artifact Creature answers "an
    # artifact card" and "a creature card" both. ``primary_type`` picks one of
    # them by the order of a list, which is the reading the singular branch
    # below already stopped making - and the union was the last reader in this
    # function still making it. No shipped card exercises the difference today
    # (every union in the pool is instant/sorcery), which is exactly why it
    # would have gone on being wrong.
    if card_types and not any(card_has_type(card, name) for name in card_types):
        return False
    # "target **white or black** creature card" (Dreams of the Dead). A union:
    # the card answers when it is any one of the printed colours. It was a
    # single symbol read as ``colors[0]`` off a phrase that could name several,
    # so a two-colour phrase offered one colour and silently refused the other —
    # the narrowing this predicate exists to keep honest, in the direction that
    # takes cards away from the player.
    colors = spec.get("graveyard_colors")
    if colors and not any(color in card.colors for color in colors):
        return False
    # "target **Griffin** card" (Mtenda Griffin). Off the printed type line,
    # which for a card outside the battlefield is the whole of what there is
    # (CR 613.1) -- the same reader ``card_matches_filter`` uses for the
    # identical phrase in a hand. OR'd across alternatives, because "Djinn or
    # Efreet" is one phrase wherever it is printed.
    wanted_subtypes = tuple(spec.get("graveyard_subtypes") or ())
    if wanted_subtypes:
        held = printed_shape(card)[1]
        if not any(word in held for word in wanted_subtypes):
            return False
    # "up to four target **basic** land cards from a player's graveyard"
    # (Lodestone Bauble). Read off the printed type line, which for a card in a
    # graveyard is the whole of what there is (CR 613.1) — the same reader and
    # the same rule ``card_matches_filter`` above uses for the identical phrase
    # in a hand. Asked *after* the type and colour tests and before the
    # any-card exit, because a supertype narrows a phrase that already names a
    # type ("basic **land** cards") and is not an alternative to naming one.
    wanted_supertypes = tuple(spec.get("supertypes") or ())
    if wanted_supertypes:
        held = printed_supertypes(card.type_line)
        if not all(word in held for word in wanted_supertypes):
            return False
    # "target creature card **with mana value 3 or less**" (Unearth). Mana value
    # is one of the few characteristics a card has in *every* zone — CR 202.3
    # computes it from the printed mana cost, so unlike power or a keyword it
    # needs no battlefield object to be asked of, which is what makes it
    # answerable here at all. Same bound reader ``card_matches_filter`` uses one
    # zone over, so "3 or less" means one thing wherever it is printed. Asked
    # before the any-card exit for the supertype's reason: it narrows a phrase
    # that already names a type rather than replacing one.
    if not _comparison_holds(
        spec.get("graveyard_mana_value"), int(getattr(card, "cmc", 0) or 0)
    ):
        return False
    if card_types or spec.get("any_card"):
        return True
    card_type = spec.get("card_type")
    if card_type is not None:
        return card_has_type(card, card_type)
    # The unnarrowed default — the reanimation Auras, whose enchant clause says
    # "creature card in a graveyard" and carries no type of its own. Through
    # ``card_has_type`` like every branch above it, so the last spelling of
    # "is this a creature card" in this function is the same as the first: no
    # card in the pool is a land creature, so nothing moves today, and the
    # reading that would have moved it is the one CR 205.2a rules out.
    return card_has_type(card, "creature")


def excluded_graveyard_slot(spec: dict, graveyard, source_card) -> int | None:
    """The graveyard slot a printed "**another**" takes out of the choice, or None.

    :func:`graveyard_card_matches`'s companion, and separate from it because the
    two answer different questions. That predicate is asked about a *card* —
    "may a card like this be chosen?" — and the printed word excludes **one
    object**, not one kind of card: "return another target artifact card from
    your graveyard to your hand" (Junk Diver) rules out the ability's own
    source and nothing else, and CR 113.7 is what says which object that is —
    "the source of a triggered ability … is the object whose ability
    triggered". Not CR 109.5, which several comments in this engine cite for
    the word and which is about "you" and "your".

    So the answer is a **slot**, not a predicate over cards. ``load_cards``
    dedupes by ``oracle_id``, so two copies of one card in one graveyard are
    literally one ``CardDefinition`` object — the residual
    :class:`engine.game_types.GraveyardTarget` documents — and a per-card
    exclusion would take *both* copies away where the sentence takes one. The
    first matching slot is the same reading ``handlers/exile.exile_self``
    already gives "exile **it**" for a dies-trigger whose source is in the pile.

    One reader for both callers, for the reason ``graveyard_card_matches`` is
    one: ``legality._enumerate_graveyard_creatures`` offers the choice and the
    handler performs it, and a second copy of "which slot is the source's" is
    how a picker comes to offer what resolution then refuses. The announcement
    gates (CR 601.2c for a spell, CR 602.2b for an ability) need no third call
    — they check what was named against that same enumeration.

    None whenever the sentence printed no such word, whenever the caller has no
    source card to compare against, and whenever no copy of that card is in the
    pile — three ways of saying "nothing is excluded", which is the honest
    answer rather than a guess at a slot.
    """
    if not (spec or {}).get("exclude_source_card") or source_card is None:
        return None
    return next(
        (index for index, held in enumerate(graveyard) if held is source_card),
        None,
    )


def graveyard_slots_matching(spec: dict, graveyard, source_card=None) -> list[int]:
    """The slots of *graveyard* an unannounced pick described by *spec* may
    take: every card :func:`graveyard_card_matches` admits, less the one slot
    :func:`excluded_graveyard_slot` takes out for a printed "other than this
    card" (Ichorid).

    The pick prompt and the takeability gate in front of its offer both ask
    this, so a pile the offer says can pay is the pile the prompt then offers
    — the gate counting the source's own slot would offer Ichorid's exile over
    a graveyard holding nothing but Ichorid, and the pick would then have
    nothing to take while "if you do" returned it anyway.
    """
    excluded = excluded_graveyard_slot(spec, graveyard, source_card)
    return [
        index for index, card in enumerate(graveyard)
        if index != excluded and graveyard_card_matches(spec, card)
    ]


#: What each printed state adjective asks of a permanent. One table, because
#: the union above and the singular narrowings below it are the same words —
#: two readers would be two answers to "is this creature blocking?".
_STATE_TESTS = {
    "tapped": lambda perm: bool(perm.tapped),
    "untapped": lambda perm: not perm.tapped,
    "attacking": lambda perm: bool(perm.attacking),
    "blocking": lambda perm: perm.blocking_attacker_index is not None,
    "blocked": lambda perm: bool(perm.blocked),
    "unblocked": lambda perm: not perm.blocked,
    # "…as long as it's **enchanted**" (Fledgling Osprey, Metathran Elite,
    # Thran Golem) and "…**if Rayne is enchanted**" (Rayne, Academy
    # Chancellor). CR 303.4: a permanent is enchanted while an *Aura* is
    # attached to it — so this is not "has anything attached". Equipment
    # attaches through the same record (``engine/equipment.py`` keeps
    # ``attached_auras`` as the one attachment list, and CR 301.5f gives the
    # host the word "equipped" instead), so a bare truthiness test on that list
    # would make a Bone Saw grant Fledgling Osprey flying.
    #
    # The type is asked through ``has_type``, not off ``card.type_line``: an
    # Aura the layers have turned into something else is still an Aura by
    # subtype, and a Licid — an enchantment creature that becomes an Aura —
    # answers the question the layers give rather than the one it was printed
    # with.
    #
    # The ``enchanted_only`` filter key in ``permanent_matches_filter`` below
    # is routed through this same test rather than spelled beside it: "destroy
    # target **enchanted** creature" (Ramses Overdark), "as long as it's
    # enchanted" and "if this creature is enchanted" are one question asked of
    # one permanent, and two spellings of it is how a card ends up disagreeing
    # with a sweep about what "enchanted" means. Two branches of one wave wrote
    # this entry independently and agreed on the reading; the helper is the one
    # copy.
    "enchanted": lambda perm: _is_enchanted(perm),
}


def _is_enchanted(perm) -> bool:
    """Whether an Aura is attached to *perm* (CR 303.4).

    Beside the table it answers rather than inside the lambda so the Equipment
    exclusion has somewhere to be written down.
    """
    from ..aura_attachment import auras_attached_to

    return any(
        attachment.has_type("aura") for attachment in auras_attached_to(perm)
    )


def permanent_state_holds(perm, state: str) -> bool:
    """Whether the printed state word *state* is true of *perm* right now.

    The one reader of :data:`_STATE_TESTS` for callers holding a **state name**
    rather than a filter payload — a condition's "as long as it's blocking"
    (Snow Devil) and an intervening-if's "if it's tapped". Those used to read
    ``getattr(perm, state)``, which is right for ``tapped`` and ``attacking``
    and silently False forever for ``blocking``: a permanent has no such field,
    it has ``blocking_attacker_index``. A condition that can only be false is a
    static that never applies and a card that reports supported.

    ``attacked_this_turn`` is here too, and for the same reason — it is a mark
    in metadata, not a field — routed to the reader beside the stamp so this
    does not become a second place that knows the key.
    """
    from ..turn_state import BLOCKED_BY_BLOCKER_IDS_KEY, attacked_this_turn

    if state == "attacked_this_turn":
        return attacked_this_turn(perm)
    if state == "was_blocked_this_turn":
        # "When this creature dies, **if it was blocked this turn**, you gain 4
        # life." (Fyndhorn Druid.) A window of one turn, so it cannot be the
        # present-tense ``blocked`` above: that flag is the current combat's,
        # cleared when combat ends, and a creature killed in the second main
        # phase was still blocked this turn. The record is the pair list the
        # declare-blockers step writes and the cleanup step sweeps — the same
        # one "blocked or was blocked by" reads, so one block is one fact.
        #
        # Only the blockers' side. "Was blocked" is CR 509.1a from the
        # attacker's end, and the other list on the same permanent is the
        # attackers it blocked — reading both would make every Wall that
        # blocked answer yes to a sentence about being blocked.
        return bool(perm.metadata.get(BLOCKED_BY_BLOCKER_IDS_KEY))
    if state == "regenerated_this_turn":
        # "…**if this creature regenerated this turn**" (Spiny Starfish). The
        # record is a count, and this reading is the presence half of it — the
        # same key the token count reads, so "did it?" and "how many times?"
        # cannot come apart.
        from ..regeneration import REGENERATED_THIS_TURN

        return int(perm.metadata.get(REGENERATED_THIS_TURN, 0)) > 0
    if state == "was_dealt_damage_this_turn":
        # "At the beginning of each end step, **if this creature was dealt
        # damage this turn**, put a +0/+1 counter on it." (Wall of Resistance.)
        # The same key ``dealt_damage_this_turn`` reads as a *filter* on a
        # candidate (Giant Shark), read here as a question about one named
        # permanent — one record, so a Wall that was pinged and a Shark's
        # blocker cannot disagree about what "was dealt damage" means.
        #
        # Not ``damage_marked``: regeneration (CR 701.19a) and a toughness
        # rewrite each wipe that while the damage stays dealt, and the Wall's
        # counter is owed either way.
        return bool(perm.metadata.get("was_dealt_damage_this_turn"))
    test = _STATE_TESTS.get(state)
    # A word with no test behind it must not read as False: that is a condition
    # nobody answered wearing the answer "no". Every producer of a state name is
    # held to this table, so an unknown word is a bug, not a board state.
    if test is None:
        raise KeyError(f"no permanent-state test for {state!r}")
    return bool(test(perm))


def unblocked_attacker(perm) -> bool:
    """CR 509.1h — *perm* is an attacking creature nothing was declared to block.

    The one reading of the printed word, shared by the filter key below and by
    ``engine/replacements/damage.py``'s source classes. An attacker with a blocker
    declared for it **is** a blocked creature and stays one even if every
    blocker leaves combat, so a trampler's excess damage to the player is not
    dealt "by an unblocked creature" — which is why this reads the permanent's
    own combat state rather than which loop the combat step is in. A creature
    not attacking at all is neither blocked nor unblocked, so it answers False
    here and to ``blocked_only`` alike.
    """
    return bool(getattr(perm, "attacking", False)) and not bool(
        getattr(perm, "blocked", False)
    )


def state_holds(perm: Permanent, word: str) -> bool:
    """Whether the printed state adjective *word* is true of *perm*.

    An unknown word answers False rather than True: a union nobody can test
    must narrow to nothing rather than admit everything, which for a *target*
    restriction is the direction that offers an illegal choice.
    """
    test = _STATE_TESTS.get(word)
    return bool(test and test(perm))


def permanent_matches_filter(perm: Permanent, payload: dict) -> bool:
    """Whether *perm* satisfies a target-filter payload (the key vocabulary
    produced by ``engine.grammar.ast.ObjectFilter.to_payload``:
    type/subtype/color filters, tapped_only, exclusions).

    Uses has_type/is_creature/effective colors so copies keep all their types
    (a Copy Artifact copy is an Artifact Enchantment), animated lands count as
    creatures, and color overrides are honored. Shared by destroy-target
    resolution, cast validation, and the legality enumerator so they can never
    disagree about what a filter means.
    """
    # "of the chosen color" (Psychic Allergy) names a colour recorded on the
    # *source* permanent (CR 614.1c), which this function does not have — it is
    # the pure half, about one permanent alone. Refusing rather than ignoring is
    # the direction that cannot widen an effect: `evaluate_count` and
    # `subject_filters.subject_matches` both hold a source and resolve the key
    # into `color_filter` before asking, so the key only survives to here when
    # nobody could answer it.
    if payload.get("chosen_color"):
        return False
    # "…of **that** color" (Rith, the Awakener) — the same narrowing with the
    # colour chosen by an earlier step of the resolution (CR 608.2d) instead of
    # recorded on a permanent, and refused here for the identical reason: only a
    # reader holding the resolution can answer it
    # (`resolve_color_chosen_in_resolution`), and the key surviving to here
    # means nobody did. Ignored, it counted every permanent on the seat.
    #
    # "…of the color **of your choice**" (Wash Out) is the same word before
    # anyone has chosen: only a lowering that puts the choosing step in front
    # may carry it (``split_color_choice``), and it lifts the key off when it
    # does — so here it is a phrase no step answers.
    if payload.get(COLOR_CHOSEN_THIS_WAY_KEY) or payload.get("color_of_your_choice"):
        return False
    # "…**with the chosen ability**" (Phyrexian Splicer). The same recorded
    # choice one characteristic over — the word is on the ability's source and
    # this function is the pure half — refused for the identical reason:
    # ignoring the key would widen "target creature with the chosen ability" to
    # every creature.
    if payload.get("chosen_keyword"):
        return False
    # "…**not named this creature**" (Escaped Shapeshifter) and "…**with
    # protection from white**". Both need something this function does not
    # have — the first the ability's source, whose *name* is the exclusion, the
    # second the game, because a quality can come from an Aura, a lord or a
    # granted metadata key and none of those is readable off the candidate.
    # Refused rather than ignored, the direction every relative key here takes:
    # ignoring the first would exclude nobody and ignoring the second would
    # admit every creature on the board.
    if payload.get("not_named_source") or payload.get("with_protection_from"):
        return False
    # "…that share a color with **it**" (Spreading Plague). A relation to the
    # object a firing event was about, which only a handler holding the
    # trigger's context can resolve — the sweep lifts the key out before it
    # asks here. One that arrives unresolved matches nothing, the direction
    # every relative key above takes: ignored, it would be every creature.
    if payload.get("shares_color_with_it"):
        return False
    # "of the chosen type" (An-Zerrin Ruins) — the same recorded choice one
    # characteristic over, refused here for the identical reason: the record
    # lives on the *source*, this function is the pure half, and ignoring the
    # key would widen "creatures of the chosen type" to every creature.
    if payload.get("chosen_creature_type") or payload.get("chosen_land_type"):
        return False
    # "All nontoken permanents **of that type**" (Teferi's Realm) — the same
    # recorded choice on the other half of the type line, refused here for the
    # identical reason. Ignoring it would phase out *every* nontoken permanent
    # on the board rather than one type's.
    if payload.get(CHOSEN_CARD_TYPE):
        return False
    # "…creature **that attacked you this turn**" (Jabari's Influence). The
    # record names a *seat*, and this function has no observer — it is the pure
    # half, about one permanent alone. Refused rather than ignored for the
    # reason above it: ignoring would offer every creature that attacked
    # anybody, which in a duel is right by coincidence and wrong the moment a
    # third seat is at the table. ``subject_matches`` holds the observer and
    # answers it.
    if payload.get("attacked_you_this_turn"):
        return False
    # "…with the greatest power **among creatures on the battlefield**"
    # (Topple). The answer is about the rest of the board, which this pure half
    # cannot see; ignored, it would offer every creature for a spell that names
    # the biggest. ``subject_matches`` holds the game and answers it.
    if payload.get("superlative_among"):
        return False
    # "target creature **blocking or blocked by** Cromat". A relation to the
    # ability's own source, which this pure half does not have; ignored, it
    # would offer every creature on the table for a destroy that names the
    # ones in one fight. ``subject_matches`` holds the source, answers it off
    # the combat maps and strips the key before asking here.
    if payload.get("in_combat_with_source"):
        return False
    # "…with power **less than the number of cards in your graveyard**"
    # (Temporary Insanity). A count of the *observer's* pile, which this pure
    # half is handed no seat to read; ``subject_matches`` holds the observer,
    # answers it and strips the key before asking here.
    if payload.get("power_vs_count"):
        return False
    # "creatures that didn't attack this turn" / "…except for creatures that
    # couldn't attack" (Season of the Witch). Both are per-turn records stamped
    # on the permanent itself — the first by the declaration, the second by the
    # declare-attackers step's turn-based action (CR 508.1) — so the pure
    # matcher answers them. Read at the sweep rather than re-derived: by the
    # end step a creature may have untapped or lost its restriction, and the
    # question is about the combat, not about now.
    if payload.get("attacked_this_turn") and not perm.metadata.get("attacked_this_turn"):
        return False
    if payload.get("not_attacked_this_turn") and perm.metadata.get("attacked_this_turn"):
        return False
    if payload.get("could_attack_this_turn") and not perm.metadata.get(
        "could_attack_this_turn"
    ):
        return False
    # "each creature **that blocked or was blocked this turn**" (Heat
    # Stroke). Both sides of CR 509.1a from the pair records the
    # declare-blockers step writes, which is what makes this the *pure*
    # half: neither list needs another object resolved, only the presence
    # of an entry — and a creature whose partner has since left still
    # blocked. Read here rather than through ``block_partners_this_turn``
    # for exactly that reason: that reader drops ids it cannot resolve,
    # which would let a creature whose blocker died escape the sweep.
    if payload.get("blocked_or_was_blocked_this_turn"):
        from ..turn_state import (BLOCKED_ATTACKER_IDS_KEY,
                                  BLOCKED_BY_BLOCKER_IDS_KEY)

        if not any(
            perm.metadata.get(key)
            for key in (BLOCKED_ATTACKER_IDS_KEY, BLOCKED_BY_BLOCKER_IDS_KEY)
        ):
            return False
    type_filter = payload.get("type_filter")
    subtype_filter = payload.get("subtype_filter")
    color_filter = payload.get("color_filter")
    tapped_only = payload.get("tapped_only", False)
    exclude_colors = payload.get("exclude_colors") or []
    exclude_types = payload.get("exclude_types") or []

    # "target **attacking or blocking** creature" (the four Legends pingers),
    # "**tapped or blocking**" (Tetsuo Umezawa). Answerable purely: "attacking"
    # is a field and CR 509.1a makes "blocking" one too — a creature is blocking
    # once it has been *declared* as a blocker, which is exactly what
    # `blocking_attacker_index` records. `state_holds` is the same test
    # `layer_bridge._QUALIFIER_HOLDS` uses, so a conditional buff and a target
    # restriction cannot disagree about what a state word means.
    any_states = payload.get("any_states")
    if any_states and not any(state_holds(perm, word) for word in any_states):
        return False

    # "target **attacking** creature" (Disharmony). The narrower half of the
    # union above, asked of the same field so a target restriction and the
    # picker cannot disagree about what "attacking" means.
    if payload.get("attacking_only") and not perm.attacking:
        return False

    # "target **blocking** creature" (Righteousness), "two target blocking
    # creatures …" (Sorrow's Path). The other half of the union above, asked of
    # the same ``state_holds`` table — the noun parser has produced this key
    # since the state adjectives were read, and until it was answered here the
    # narrowing was carried by the payload and tested by nothing that reads a
    # filter: ``subject_matches`` dropped it, so a role's re-check at CR 608.2b
    # and the picker both admitted a creature that is not blocking at all.
    if payload.get("blocking_only") and not state_holds(perm, "blocking"):
        return False

    # "target **nonattacking, nonblocking** creature" (Unlikely Alliance). The
    # same two readings negated, and asked through the same accessors so the
    # positive and negative halves of one word cannot come to disagree. A
    # creature in neither role is what the card names — not "any creature",
    # which is what these keys being unanswered would have meant.
    if payload.get("not_attacking") and perm.attacking:
        return False
    if payload.get("not_blocking") and state_holds(perm, "blocking"):
        return False

    # "…by **unblocked** creatures" / "**blocked** creature". CR 509.1h's pair,
    # asked through the one reading above so a redirect's source class, a
    # target restriction and the picker cannot disagree about the word.
    if payload.get("unblocked_only") and not unblocked_attacker(perm):
        return False
    if payload.get("blocked_only") and not (
        getattr(perm, "attacking", False) and getattr(perm, "blocked", False)
    ):
        return False

    # "a creature **that has been dealt damage this turn**" (Giant Shark). A
    # record stamped by `damage_events.deal_damage`, not a read of
    # ``damage_marked``: marked damage is what is *left* on the creature, and
    # regeneration (CR 701.19a) and a toughness rewrite both wipe it while the
    # damage stays dealt. Swept with the turn.
    if payload.get("dealt_damage_this_turn") and not perm.metadata.get(
        "was_dealt_damage_this_turn"
    ):
        return False

    # "target Aura attached to a **land**" (Pyramids) / "…to a **creature or
    # land**" (Enchantment Alteration). *What* the host is, as a nested noun
    # phrase rather than the tuple of card types this was: the printed host is
    # payload data, and a card narrowing its host any other way would otherwise
    # have needed a second key. Recursion, not a second rule — a host is a
    # permanent, so the question asked of it is this same question.
    #
    # The pure half answers only what a host can answer alone; a nested phrase
    # with a seat in it ("permanents **you control**") is
    # ``subject_filters.subject_matches``'s, which recurses with the observer it
    # has. This function never sees one, because the lowering that admits such a
    # phrase routes its sweep through the observed matcher.
    attached_host = payload.get("attached_to_filter")
    if attached_host:
        attached = perm.metadata.get("attached_to")
        if attached is None or not permanent_matches_filter(attached, attached_host):
            return False
    # "target Aura **that's attached to a permanent**" (Aura Graft). The host
    # phrase with nothing to test the host against: it has to be there.
    if payload.get("attached_to_permanent") and perm.metadata.get("attached_to") is None:
        return False

    # "target permanent **that isn't enchanted**" (Time Elemental) — CR 303.4a.
    # The attachment record this engine keeps is shared with Equipment
    # (CR 301.5f attaches both the same way), so the *Aura subtype* is what is
    # asked: an equipped creature is not an enchanted one, and answering off the
    # bare list would have made Time Elemental refuse to bounce it.
    if payload.get("not_enchanted"):
        if any(
            attached.has_type("aura")
            for attached in (perm.metadata.get("attached_auras") or [])
        ):
            return False

    # "destroy **target enchanted** creature" (Ramses Overdark) — the positive
    # half, asked exactly as its negation above is: an Aura attached, not merely
    # something attached, because this engine shares the attachment record with
    # Equipment (CR 301.5f) and an equipped creature is not an enchanted one.
    if payload.get("enchanted_only"):
        # Through the state table above, so the filter key and the printed
        # condition "if this creature is enchanted" cannot come apart.
        if not _STATE_TESTS["enchanted"](perm):
            return False

    def _has_type(name: str) -> bool:
        # is_creature (not the printed line) so animated lands count.
        return perm.is_creature if name == "creature" else perm.has_type(name)

    # "a **black or artifact** creature" (Soldevi Adnate). A union across two
    # *axes* — CR 105 colour against CR 205.2 card type — which the keys below
    # cannot express because the engine ANDs them: `colors` plus `card_types`
    # describes a black creature that is *also* an artifact, which is not what
    # any of these cards print. Each alternative carries the axis it was read
    # on, so nothing here has to guess which vocabulary a bare word came from.
    #
    # ANDed against the head noun rather than replacing it: the phrase is "a
    # creature that is black or an artifact", so `card_types` above still has
    # to hold. The stack half of this key (`handlers/stack._spell_is_one_of
    # _classes`, "instant or Aura spell") empties `card_types` instead, which
    # is the same AND with nothing on the left.
    any_classes = payload.get("any_classes")
    if any_classes:
        def _class_holds(entry) -> bool:
            axis, name = entry[0], entry[1]
            if axis == "color":
                # CR 613 layer 5's answer, not the printed one — the same
                # accessor `color_filter` below is answered with, so a
                # recoloured permanent cannot match one key and miss the other.
                return name in permanent_effective_colors(perm)
            if axis == "card_type":
                if not _has_type(name):
                    return False
                # "target land or **nonblack** creature" (Befoul). A colour
                # negation on **one member** of the union, carried as a third
                # element rather than on the filter's own `exclude_colors`:
                # that key is ANDed across the whole phrase, so it would
                # exclude black from the *land* half too and the spell would
                # stop destroying a black opponent's Swamp. Read through the
                # same layer-5 accessor the colour axis above uses.
                excluded = entry[2] if len(entry) > 2 else ()
                if not excluded:
                    return True
                colors = permanent_effective_colors(perm)
                return not any(colour in colors for colour in excluded)
            if axis == "subtype":
                return perm.has_type(name)
            # An axis nothing here reads must refuse rather than be ignored:
            # a dropped alternative widens the union to everything.
            return False

        if not any(_class_holds(entry) for entry in any_classes):
            return False

    if type_filter:
        if type_filter == "artifact_or_enchantment":
            if not (perm.has_type("artifact") or perm.has_type("enchantment")):
                return False
        elif isinstance(type_filter, (list, tuple)):
            # A type union ("target artifact, creature, or land") — any match
            # qualifies.
            if not any(_has_type(name) for name in type_filter):
                return False
        elif not _has_type(type_filter):
            return False
    if subtype_filter:
        # A single subtype string, or several OR'd alternatives ("Djinn or
        # Efreet") as a list — any one matching is enough.
        #
        # has_type, not the printed type line: a land turned into a Swamp by
        # Magical Hack / Phantasmal Terrain / Evil Presence IS a Swamp under CR
        # 613 layer 4, and this function promises destroy-target resolution,
        # cast validation and the legality enumerator can never disagree about
        # what a filter means. Reading the printed line made it disagree with
        # layer 4 — the divergence is unreachable in the current pool (no card
        # here filters on a basic land subtype) but reachable the moment one
        # ships.
        subtypes = [subtype_filter] if isinstance(subtype_filter, str) else subtype_filter
        if not any(perm.has_type(s) for s in subtypes):
            return False
    # "an **Urza's Power-Plant**" — a conjunction of subtypes, the same
    # distinction `type_filter_all` draws for card types and for the same
    # reason. "Urza's Mine", "Urza's Power-Plant" and "Urza's Tower" are each
    # two land types (CR 205.3i), so OR'ing them would make any one of the three
    # satisfy all three and the assembly would complete on a single land.
    subtype_filter_all = payload.get("subtype_filter_all")
    if subtype_filter_all:
        if not all(perm.has_type(s) for s in subtype_filter_all):
            return False
    # "target **artifact creature**" — one permanent that is both types, as
    # against "target artifact, creature, or land", which is a union. The
    # grammar has drawn this distinction since it had a `type_match` field; it
    # emitted `type_filter_all` and lowering refused the line, because no
    # matcher answered it. This is that matcher.
    type_filter_all = payload.get("type_filter_all")
    if type_filter_all:
        if not all(_has_type(name) for name in type_filter_all):
            return False
    if tapped_only and not perm.tapped:
        return False
    colors = permanent_effective_colors(perm)
    if color_filter and color_filter not in colors:
        return False
    # "a green or white creature": any one of them is enough, and a gold
    # green-and-white creature answers both — CR 105.2b, a colour is a property
    # an object has rather than a category it is sorted into.
    any_colors = payload.get("any_colors")
    if any_colors and not any(color in colors for color in any_colors):
        return False
    if exclude_colors and any(c in colors for c in exclude_colors):
        return False
    # "a **multicolored** creature" (Dragon Arch's phrase, asked of a
    # permanent). CR 105.2b: two or more colours, counted off the *computed*
    # set like every colour test above — a Lace-painted creature is exactly as
    # multicoloured as layer 5 says it is. Through the one definition
    # (``object_colors.is_multicolored``) the cost tax, the cast trigger and
    # protection already ask.
    if payload.get("multicolored") and not is_multicolored(colors):
        return False
    if exclude_types and any(perm.has_type(t) for t in exclude_types):
        return False
    # "non-Spirit creature" (Roaming Ghostlight). has_type, like the positive
    # subtype test above, so a granted or layer-4 subtype excludes too.
    exclude_subtypes = payload.get("exclude_subtypes") or []
    if exclude_subtypes and any(perm.has_type(s) for s in exclude_subtypes):
        return False
    # "with mana value 3 or less" (Eliminate). CR 202.3: a permanent's mana
    # value comes from its mana cost — the ingested cmc; a token's is 0.
    if not _comparison_holds(payload.get("mana_value"),
                             int(getattr(perm.effective_card, "cmc", 0) or 0)):
        return False
    # "…each artifact **with mana value less than or equal to the number of rust
    # counters on it**" (Corrosion). Both halves come off the permanent in hand,
    # which is what makes this a filter key rather than an amount: an amount is
    # answered from the resolving effect's context, and the number here is
    # different for every object the sweep looks at.
    at_most_counters = payload.get("mana_value_at_most_counters")
    if at_most_counters is not None:
        from ..named_counters import counters_on

        if int(getattr(perm.effective_card, "cmc", 0) or 0) > counters_on(
            perm, str(at_most_counters)
        ):
            return False
    # "with power 4 or greater" (Turret Ogre's intervening-if): the
    # layer-computed stats, so a pumped 2/2 qualifies while it is pumped.
    if not _comparison_holds(payload.get("power"), perm.effective_power):
        return False
    if not _comparison_holds(payload.get("toughness"), perm.effective_toughness):
        return False
    # "with a +1/+1 counter on it" (Tempered Veteran). Asks the counter
    # *record*, not the P/T bonus — a Giant Growth also writes power_bonus, and
    # reading the bonus as the counter would let it qualify.
    if payload.get("with_plus1_counter") and int(perm.metadata.get("plus_counters", 0)) <= 0:
        return False
    # "with a **bounty** counter on it" (Bounty Hunter). CR 122.1's open kind
    # space, asked of ``named_counters``' store — the one place an invented
    # counter kind is recorded, and deliberately *not* the ``plus_counters``
    # record above it: a card that puts bounty counters on a creature someone
    # else has been pumping must not find them there.
    named_counter = payload.get("with_named_counter")
    if named_counter:
        from ..named_counters import counters_on

        if counters_on(perm, str(named_counter)) <= 0:
            return False
    # "each land **with an activated ability that isn't a mana ability**"
    # (Tsabo's Web). What the permanent can do *now*: ``effective_card`` is the
    # card as it reads after a copy, a text change and any granted ability, so
    # a Forest handed Maze of Ith's ability stops untapping and a Strip Mine
    # that has lost its abilities starts.
    if payload.get("with_nonmana_activated_ability"):
        from ..mana_payment import has_nonmana_activated_ability

        if not has_nonmana_activated_ability(perm.effective_card):
            return False
    # "an **untapped** creature" (Enthralling Hold). The twin of ``tapped_only``
    # and a separate key for the reason stated on ``to_payload``.
    if payload.get("untapped_only") and perm.tapped:
        return False
    # "target **legendary** creature". CR 205.4: a supertype sits on the type
    # line, and nothing in layers 4-6 computes one here — so the answer is the
    # line the permanent *effectively* has, which folds in a copy (layer 1) and
    # a text change (layer 3). ``perm.card`` would be the printed face and would
    # miss both.
    wanted_supertypes = payload.get("supertypes") or ()
    excluded_supertypes = payload.get("exclude_supertypes") or ()
    if wanted_supertypes or excluded_supertypes:
        # Through ``has_supertype``, which computes layer 4 — not off the
        # effective type line. The line is the *seed*: Arcum's Weathervane makes
        # a Plains snow and unmakes a snow land, so "a snow land" has to be the
        # computed answer for the same reason "a creature" is.
        held = perm.effective_supertypes
        if not all(word in held for word in wanted_supertypes):
            return False
        # "target **nonsnow** land" (Hallowed Ground). The negative of the key
        # above, off the same answer and for the same reason.
        if any(word in held for word in excluded_supertypes):
            return False
    # "…**except for basic lands**" / "…**other than a basic land**" (Eye of
    # Singularity prints both). The *pair* — CR 205.4a's Basic supertype and
    # the land card type — rather than the supertype alone: excluding the
    # supertype is a different sentence, and the only reason it names the same
    # cards today is that no printed non-land carries Basic. Both halves are
    # computed (layer 4) for the reason the block above computes its supertype:
    # Kormus Bell's animated Swamp is still a basic land, and a land whose type
    # an effect rewrote is whatever the layers say it is.
    if payload.get("exclude_basic_lands"):
        if perm.has_type("land") and "basic" in perm.effective_supertypes:
            return False
    # "nontoken permanent" (Lich). CR 111.1: not a card type, so it is its own
    # key rather than an ``exclude_types`` entry.
    # "…any number of **tokens**" (Tetravus). The positive of the restriction
    # below, read off the same record.
    if payload.get("token_only") and not perm.metadata.get("is_token", False):
        return False
    if payload.get("nontoken") and perm.metadata.get("is_token", False):
        return False
    # "named <card>" — through `name_key`, so the parser's rendering of the name
    # and Oracle's spelling of it compare equal. The *effective* card, because a
    # Clone's name is the name it copied (CR 707.2).
    named = payload.get("named")
    if named and name_key(perm.effective_card.name) != name_key(str(named)):
        return False
    # "…**not named <card>**" — the same comparison negated, read the same way
    # and off the same effective card. The self-referential spelling
    # ("not named this creature") is ``not_named_source`` and lives in
    # ``subject_filters``: it needs the ability's source to have a name at all.
    not_named = payload.get("not_named")
    if not_named and name_key(perm.effective_card.name) == name_key(str(not_named)):
        return False
    # "…with a name originally printed in the <Set> expansion" (Apocalypse
    # Chime, Golgothian Sylex). ``original_printing`` is ``printings[0]`` -- the
    # first set the card appeared in -- and not whichever set happened to load
    # first; that distinction is the whole content of the word "originally".
    #
    # ``effective_card``, because CR 206.3 spells each of these three cards out
    # as a list of **names** ("those names are Abbey Gargoyles; Abbey Matron;
    # …"). So the question is whether *this object's* name is one of them, and a
    # copy's name is the name it copied (CR 707.2, layer 1). Reading the printed
    # face asks where the physical card came from, which is a different question
    # — and the one Golgothian Sylex was answering when it left a Copy Artifact
    # named Su-Chi standing.
    expansion = payload.get("original_expansion")
    if expansion and str(perm.effective_card.original_printing or "").lower() != str(
        expansion
    ).lower():
        return False
    return True


def _comparison_holds(comparison: dict | None, actual: int) -> bool:
    """Whether *actual* satisfies a lowered ``{op, value}`` bound (absent means
    unrestricted)."""
    if not comparison:
        return True
    bound = int(comparison.get("value", 0))
    op = comparison.get("op")
    if op == "le":
        return actual <= bound
    if op == "lt":
        return actual < bound
    if op == "ge":
        return actual >= bound
    if op == "gt":
        return actual > bound
    if op == "eq":
        return actual == bound
    return False


def seats_controlling(game, seats, described) -> list:
    """*seats*, narrowed to the ones controlling something *described* names.

    "…deals 2 damage to each white creature and **each player who controls a
    white creature**." (Disorder.) The board twin of
    :func:`seats_matching_deed` below, and beside it because both answer the
    same question — which of a loop's seats does the printed relative clause
    name — off two different kinds of evidence: a record for that one, a
    battlefield for this one.

    Through the control seam, so a permanent somebody has taken control of
    counts for the seat that controls it now (CR 613 layer 2) rather than for
    its owner. The observer handed to the matcher is the **candidate seat**:
    the phrase is about what *that* player controls, not about the ability's
    controller, so "a creature you control" inside such a clause would mean the
    candidate's own — which is what the words say.

    ``None`` is no clause printed, which leaves the list exactly as it was.
    """
    from ..subject_filters import subject_matches

    if not described:
        return list(seats)
    return [
        seat for seat in seats
        if any(
            subject_matches(game, perm, described, observer=seat)
            for perm in game.controlled_by(seat)
        )
    ]


def seats_matching_deed(game, context, seats, deed) -> list:
    """*seats*, narrowed to the ones a ``who <did …>`` clause names.

    "…each player **who tapped a land for mana this turn** sacrifices a land of
    their choice. … deals 2 damage to each player **who sacrificed a Plains
    this way**." (Desolation.) One reader for both sentences, so the two halves
    of that card cannot disagree about which seats "who" introduced — and the
    same reader the lowering's ``player_deed_payload`` is the parse-side half
    of.

    ``None`` is no clause printed, which leaves the list exactly as it was.

    A kind this cannot answer returns **no seats** rather than all of them. It
    is not reachable — the lowering refuses an unknown kind, so nothing
    compiles one — but a narrowing that fails open is a sentence acting on
    every player at the table, and the direction to fail in is the one where a
    bug does nothing rather than everything.
    """
    if not deed:
        return list(seats)
    kind = deed.get("kind")
    if kind == "tapped_land_for_mana_this_turn":
        # The seat's own per-turn record, written at the one tap-for-mana seam
        # (``mixins/turn_management.tap_land_for_mana``) and cleared with the
        # rest of the turn histories. Never a read of the board: a land that
        # untapped, left, or was tapped again for something that is not mana
        # would answer the wrong question, and CR 106.4's mana is long gone by
        # the end step this asks in.
        return [
            seat for seat in seats
            if getattr(game.players[seat], "tapped_land_for_mana_this_turn", False)
        ]
    if kind == "sacrificed_this_way":
        # The seat-keyed record an earlier step of this same resolution wrote
        # (``SACRIFICED_CARDS_BY_SEAT``). Never a read of a graveyard: the pile
        # holds whatever else has gone there, and the words say "this way".
        # Compared against each card's *printed* characteristics, because a card
        # in a graveyard has no computed ones (CR 613.1) — the same restriction
        # ``card_only_filter`` puts on the lowering that built this payload.
        by_seat = (context.results or {}).get(SACRIFICED_CARDS_BY_SEAT) or {}
        described = deed.get("filter") or {}
        return [
            seat for seat in seats
            if any(
                _card_matches_filter(card, described)
                for card in (by_seat.get(seat) or ())
            )
        ]
    return []
