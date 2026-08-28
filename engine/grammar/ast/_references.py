"""What a printed noun phrase *points at*: objects, players, and targets.

Split out of ``_core`` when that module crossed the 1,000-line guard. The cut
is the one ``_core``'s own docstring already drew — quantities, then "object and
player references (``grammar/nouns.py``)", then the durations and costs that
hang off an effect — and it is the same boundary Antiquities used when
``nouns.py`` split into ``references.py``: what a noun phrase *describes*
against what it points at.

:class:`ObjectFilter` is 428 of those lines on its own, which is why this half
was the one to move. ``_core`` re-exports everything defined here, so no
importer outside this package changes: ``from ._core import ObjectFilter``
still resolves, and the AST package's flat ``__init__`` is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from ._primitives import Fixed
from ..vocabulary import TYPE_LINE_SUPERTYPES


@dataclass(frozen=True)
class Comparison:
    """A numeric restriction: "with power 2 or less"."""
    op: str    # "eq" | "le" | "ge" | "lt" | "gt"
    value: Amount


@dataclass(frozen=True)
class ObjectFilter:
    """A noun phrase describing a set of objects.

    ``to_payload`` emits the exact key set the deleted
    ``engine.parsing.common.TargetFilter`` produced, so instructions lowered
    from the grammar stayed byte-compatible with the 121 existing effect
    handlers across the migration; the newer restriction keys are additive and
    read with ``payload.get`` defaults on the handler side.
    """

    card_types: tuple[str, ...] = ()          # "creature", "artifact", ...
    # How multiple card types combine. "artifact or enchantment" is a union
    # ("any"); "artifact creature" is a single permanent that is both ("all").
    # Collapsing the two would make "destroy target artifact creature" hit every
    # artifact and every creature.
    type_match: str = "any"
    supertypes: tuple[str, ...] = ()          # "legendary", "basic", ...
    subtypes: tuple[str, ...] = ()            # "wall", "djinn", ... (from data)
    # How multiple subtypes combine, exactly as `type_match` does for card
    # types. "Djinn or Efreet" is a union ("any"); "Urza's Power-Plant" is a
    # single permanent carrying both land types ("all", CR 205.3i). Collapsing
    # them would let one Urza's Mine satisfy "an Urza's Mine and an Urza's
    # Tower" on its own.
    subtype_match: str = "any"
    # "target **instant or Aura** spell" (Avoid Fate, Ring of Immortals). A
    # union whose alternatives do not all live on one axis: "instant" is a card
    # type (CR 205.2) and "Aura" a subtype (CR 205.3), and every matcher in this
    # engine ANDs `card_types` against `subtypes` — so recording the phrase in
    # those two fields would describe an instant that is also an Aura, a set no
    # card can ever be in. Its own field for the reason `any_states` is one: a
    # union spelled into the fields it happens to straddle is a union the next
    # printed pair cannot use.
    #
    # Each alternative carries the axis it was read on ("card_type" / "subtype")
    # rather than the bare word, because the two vocabularies are not disjoint
    # in principle and a matcher guessing which one it was handed is a matcher
    # that can guess wrong.
    any_classes: tuple[tuple[str, str], ...] = ()
    colors: tuple[str, ...] = ()              # mana symbols: "W", "U", ...
    excluded_colors: tuple[str, ...] = ()     # "nonblack"
    excluded_types: tuple[str, ...] = ()      # "nonartifact"
    excluded_subtypes: tuple[str, ...] = ()   # "non-Wall"
    with_keywords: tuple[str, ...] = ()       # "with flying"
    without_keywords: tuple[str, ...] = ()    # "without flying"
    controller: str | None = None             # "you" | "opponent" | "that_player"
    # "target permanent you both **own** and control" (Obelisk of Undoing).
    # Ownership (CR 108.3) is a different question from control (CR 613 layer
    # 2) and the two come apart the moment anything is stolen — which is
    # precisely the case this card is printed to exclude. Its own field, so a
    # phrase naming only one of them cannot be read as naming both.
    owner: str | None = None                  # "you"
    tapped: bool | None = None
    attacking: bool | None = None
    blocking: bool | None = None
    blocked: bool | None = None
    # "target **attacking or blocking** creature" (the Legends pinger cycle).
    # Its own field rather than both booleans set at once: every matcher ANDs
    # the payload keys, so `attacking=True, blocking=True` would describe a
    # creature that is somehow doing both — a set that is always empty.
    #: A union of printed state adjectives — "attacking or blocking",
    #: "tapped or blocking". The words as printed, because what each one
    #: *means* is one answer the matcher owns; a pair spelled into a
    #: boolean here made every other pair a non-match.
    any_states: tuple[str, ...] = ()
    power: Comparison | None = None
    toughness: Comparison | None = None
    mana_value: Comparison | None = None
    named: str | None = None
    zone: str = "battlefield"
    # "target **activated or triggered ability**" (Sublime Epiphany). An ability
    # on the stack is an object (CR 113.7a/608.2) but not a spell, so it is not
    # ``zone == "stack"`` with a type line — it has no card at all. The printed
    # kinds are carried rather than collapsed to "an ability", because "counter
    # target activated ability" and "counter target triggered ability" are
    # different cards and the difference is exactly this tuple.
    ability_kinds: tuple[str, ...] = ()
    # "…activated ability **from an artifact source**" (Rust, Ayesha Tanaka).
    # A narrowing on the *permanent the ability came from*, which is the only
    # thing about an ability on the stack there is to narrow by — it has no card
    # and no type line of its own (CR 113.7a). Beside `ability_kinds` because it
    # is the same object's other adjective, and a tuple because "an artifact or
    # enchantment source" is the same sentence with one more word.
    ability_source_types: tuple[str, ...] = ()
    # Whose zone, when *zone* names one ("from **your** graveyard"). "Return
    # target creature card from your graveyard" and "…from a graveyard" are
    # different cards, and the handlers only ever look in the caster's own
    # graveyard — so the owner is recorded and checked rather than assumed.
    zone_owner: PlayerRef | None = None
    # The head noun was "card" ("target creature **card** from your graveyard").
    # CR 400.1: an object outside the battlefield is a card, not a permanent.
    # Without this the word is droppable, and "target creature card from your
    # graveyard" would lower identically to the untemplatable "target creature
    # from your graveyard" — the dropped-rider bug class.
    is_card: bool = False
    # "with a +1/+1 counter on it" (Tempered Veteran) — the object carries at
    # least one +1/+1 counter, read off the ``plus_counters`` record the
    # placing handlers keep (CR 122).
    with_plus1_counter: bool = False
    # "nontoken" (Lich's sacrifice). CR 111.1: a token is not a card, so this is
    # neither an excluded card type nor an excluded subtype.
    nontoken: bool = False
    # "permanents **of the chosen color**" (Psychic Allergy). Not a member of
    # ``colors``: the colour was decided as the *source* entered (CR 614.1c)
    # and is stored on that permanent, so folding it in would need a sentinel
    # colour word every ``color_filter`` reader would then compare against.
    chosen_color: bool = False
    # "creatures **that didn't attack this turn**" / "…**that couldn't
    # attack**" (Season of the Witch): two questions about one combat, both
    # answered off the permanent's own per-turn record.
    attacked_this_turn: bool | None = None
    could_attack_this_turn: bool | None = None
    # "exile any number of **tokens** created with this creature" (Tetravus) —
    # the positive of ``nontoken``. Its own field rather than a tri-state,
    # because every lowering written before it exists refuses an unknown field
    # by default and would silently ignore a third value of an old one.
    token_only: bool = False
    # "…**created with this creature**" (Tetravus). Which permanent made the
    # token, and therefore *relative*: no read of the token alone can answer it,
    # exactly like ``other_than_source`` and ``attached_to``. The handler that
    # has the ability's source tests it; ``permanent_matches_filter`` is
    # deliberately not told about it.
    created_with_source: bool = False
    # "a creature **of their choice**" (Run Afoul) — the player performing the
    # action picks. Recorded rather than dropped, because "of *your* choice" is a
    # different sentence; a lowering accepts it only where the rule it lowers to
    # already puts the choice there (CR 701.21a for a sacrifice).
    their_choice: bool = False
    # "other than this creature" / "other Zombies" — excludes the source.
    other_than_source: bool = False
    # "this creature" / "this artifact" — the ability's own source.
    is_source: bool = False
    # "**that token**" — the token an earlier sentence of this same effect
    # created (Stangg). A referent, like ``is_source`` beside it, and not a
    # restriction: no read of a permanent alone can say whether *this*
    # resolution made it, so the id is written to the resolution scratchpad by
    # the token maker and read back by whatever sentence names it. The lowering
    # refuses the phrase when no token maker precedes it, exactly as "its
    # controller creates" refuses with no exile in front of it.
    is_created_token: bool = False
    # "enchanted creature" — the permanent this Aura is attached to.
    is_enchanted: bool = False
    # "target permanent **that isn't enchanted**" (Time Elemental) — a permanent
    # with no Aura attached to it (CR 303.4a defines "enchanted" as exactly
    # that). Not the negation of ``is_enchanted`` above, which is a different
    # question entirely: that field is a *referent* ("the permanent this Aura is
    # on"), this one is a restriction on any candidate. Two fields because two
    # phrases, and collapsing them into a tri-state would make "enchanted
    # creature" and "a creature that is enchanted" the same words to every
    # reader downstream.
    not_enchanted: bool = False
    # "destroy **target enchanted** creature" (Ramses Overdark) — a creature
    # with an Aura attached, chosen from the whole board. The third of the
    # three, and the one the printed word "target" separates from
    # ``is_enchanted`` above: on an Aura, "enchanted creature" *names* the
    # permanent that Aura is on, while a card that asks its controller to pick
    # one is describing every creature that is enchanted. `references.py`
    # rewrites the referent into this restriction at the one place the
    # quantifier is known, because the noun parser reading "enchanted creature"
    # has not seen the word in front of it yet.
    enchanted_only: bool = False
    # "all Equipment **attached to that creature**" (Turn to Slag). Which object
    # it is attached to, as a referent rather than a filter: "that creature" is
    # the spell's own target, and no read of the Equipment alone can say so.
    # ``permanent_matches_filter`` is therefore not told about it — the handler
    # that has the context resolves it, the split the ``controls`` condition
    # already makes for "another".
    attached_to: str | None = None
    # "attached to a creature or land" (Enchantment Alteration) / "Auras you own
    # **attached to permanents you control**" (Remove Enchantments) — the host
    # as a noun phrase of its own, which a read of the attachment *can* answer
    # by asking the same question of the host that is being asked of this
    # object. A nested filter rather than the tuple of card types this was:
    # "permanents you control" is a host phrase with a seat in it, and a tuple
    # of types had nowhere to put the seat, so a card printing one would have
    # had it dropped — an Aura-sweep reaching every Aura on the board.
    #
    # The nesting is what keeps that from being a new rule: the host is tested
    # through the very matcher testing the attachment, so whatever a noun phrase
    # can say about a permanent it can say about a host, once.
    attached_to_filter: "ObjectFilter | None" = None
    # "another permanent **of that type**" — shares a card type with what the
    # sentence's other clause named. Only a lowering knowing that object can
    # resolve it; one that does not must refuse.
    of_bound_type: bool = False
    # "that's one or more colors" (Ugin, the Spirit Dragon's −X): the object
    # has at least one color, read off its effective colors.
    colored: bool = False
    # "…that isn't the target of an ability from another creature named ~"
    # (Goblin Artisans). A restriction on the object's *situation* rather than
    # on the object: it asks what else on the stack is pointing at it. The
    # source class is not carried because the printed clause names the ability's
    # source by the asking card's own name, which the lexer has already
    # collapsed to a SELF token — so the question is "another copy of me",
    # whatever the copy is called.
    not_ability_targeted_by_same_name: bool = False
    # "…**that targets a permanent you control**" (Avoid Fate, Ring of
    # Immortals). A restriction on what the *spell* chose, not on what the spell
    # is — so it is a nested noun phrase rather than more adjectives, and it is
    # relative twice over: it needs the stack object's recorded targets and the
    # seat "you control" is measured against. Never emitted by ``to_payload``
    # and never reaches ``permanent_matches_filter``; the one lowering written
    # for it carries the inner phrase as its own payload key and the handler
    # that has the stack item asks ``subject_matches`` of each target.
    targets_object: "ObjectFilter | None" = None
    # "…**with a single target**" (Reflecting Mirror; Deflection and Divert
    # print the same words). CR 115.9a: how many times any object or player was
    # chosen as the target of that spell when it was put on the stack — a
    # question only a *spell or ability on the stack* can be asked, and one
    # that no read of a permanent can answer. So, like ``targets_object`` above
    # it, ``to_payload`` never emits it and ``permanent_matches_filter`` is
    # never told about it: the one lowering written for it carries the count as
    # its own payload key, and every other lowering refuses the phrase by name.
    #
    # A count rather than a "single" flag, because CR 115.9a's template is
    # "[spell or ability] with [a number of] targets" — the number is the
    # parameter, exactly as a colour or a card type is elsewhere here.
    target_count: int | None = None
    # "blocking or blocked by this creature" (Sentinel) — the object is in
    # combat with the ability's own source (CR 509). Relative, like
    # ``other_than_source``: no read of the object alone can answer it, so
    # ``to_payload`` never emits it and ``permanent_matches_filter`` is never
    # told about it — the one lowering that accepts it carries the relation as
    # its own payload key and the handler that has the source tests it.
    in_combat_with_source: bool = False
    # "creatures that dealt damage to it this turn" (Brine Hag) — a *history*
    # relative to the source, read off the damage record the victim carries
    # (``damaged_by_sources_this_turn``). Same discipline as the field above:
    # never emitted, so every lowering not written for it refuses the phrase
    # instead of quietly widening to every creature.
    dealt_damage_to_source_this_turn: bool = False
    # "all creatures **blocking this creature**" (The Wretched). The set of
    # creatures currently declared as blockers of the ability's own source
    # (CR 509.1a). *Relative* like ``created_with_source``: no read of the
    # blocker alone can answer it, so it emits no payload key and never
    # reaches ``permanent_matches_filter`` — the one lowering that admits it
    # resolves the set from the fire-time combat record instead, and any
    # other lowering that meets it refuses by name.
    blocking_source: bool = False
    # "creatures blocking **target attacking creature**" (Feint) and "each
    # creature blocking **it**" (Feint's second sentence). The same relation as
    # ``blocking_source`` above with the other end moved: the creature being
    # blocked is not the ability's source but an object *this same sentence*
    # names — declared here as a nested noun phrase (``blocking_target``), or
    # referred back to as the pronoun the earlier sentence already targeted
    # (``blocking_bound_target``).
    #
    # A nested phrase rather than more adjectives, for the reason
    # ``targets_object`` above is one: the restriction is not a question about
    # the blocker at all, it is a question about *another object*, and the only
    # honest way to carry it is to carry that object's description. Both are
    # relative, so neither is emitted by ``to_payload`` and neither reaches
    # ``permanent_matches_filter`` — the lowerings written for them resolve the
    # blocked object first and read the combat maps from there, and every other
    # lowering refuses them by name.
    blocking_target: "ObjectFilter | None" = None
    blocking_bound_target: bool = False
    # "…all creatures that were **blocked by that creature this turn**"
    # (Glyph of Doom). A history relative to the object a delayed triggered
    # ability was bound to, answered from the block record that creature
    # carries rather than from any characteristic of the creatures swept — so,
    # like `dealt_damage_to_source_this_turn` above it, it is a flag the one
    # lowering written for it reads and every other lowering refuses by name.
    # "This turn" is required and "that creature" is required: a turn holds
    # several combats, and without a bound object the phrase names a blocker
    # nobody recorded.
    blocked_by_bound_object: bool = False
    # "…all creatures that were blocked by **target Wall** this turn" (Glyph of
    # Reincarnation). The same history read against a different referent: the
    # blocker is the *spell's own target* rather than the object a delayed
    # ability was bound to, so the relation carries the filter that target had
    # to satisfy and the lowering hoists it into the instruction's `targets`
    # description. A sibling of `blocked_by_bound_object` rather than a
    # widening of it — which object the record is read off decides which seam
    # the handler asks, and one field meaning either would leave it guessing.
    blocked_by_target_object: "ObjectFilter | None" = None
    # "a creature **that has been dealt damage this turn**" (Giant Shark) — a
    # fact about the candidate alone, so it rides an ordinary payload key. Its
    # own field rather than a reading of `damage_marked`: damage marked is what
    # is *left* on the creature, and regeneration and a toughness rewrite both
    # erase it while the damage stays dealt (CR 120.3).
    was_dealt_damage_this_turn: bool = False
    # "target creature **of an opponent's choice** they control" (Preacher) —
    # who *picks* the object, which is not a property of any candidate. Never
    # emitted, so a lowering not written for it refuses the phrase instead of
    # quietly letting the ability's controller choose — which is the seat the
    # card says must not.
    chosen_by_opponent: bool = False

    def to_payload(self) -> dict[str, object]:
        """Instruction-payload dict, emitting only keys that are set.

        The first six keys reproduce ``TargetFilter.to_payload`` exactly.
        """
        payload: dict[str, object] = {}
        if self.card_types:
            if len(self.card_types) == 1:
                payload["type_filter"] = self.card_types[0]
            elif self.type_match == "all":
                # No handler matches "is all of these types at once" yet;
                # lowering refuses rather than emitting a union that would
                # quietly widen the effect.
                payload["type_filter_all"] = list(self.card_types)
            elif set(self.card_types) == {"artifact", "enchantment"}:
                # The one union spelling the handlers already understand;
                # emitting it keeps Disenchant byte-compatible with the rule it
                # replaces.
                payload["type_filter"] = "artifact_or_enchantment"
            else:
                payload["type_filter"] = list(self.card_types)
        if self.subtypes:
            if len(self.subtypes) > 1 and self.subtype_match == "all":
                payload["subtype_filter_all"] = list(self.subtypes)
            else:
                payload["subtype_filter"] = (
                    self.subtypes[0] if len(self.subtypes) == 1 else list(self.subtypes)
                )
        if self.tapped:
            payload["tapped_only"] = True
        # "an **untapped** creature" (Enthralling Hold). ``tapped`` is tri-state
        # and only the True half had a key, so the False half was falsy all the
        # way down and "untapped creature" emitted exactly the payload of
        # "creature" — the round-108 dropped-narrowing shape, wearing a boolean
        # instead of a missing key. Its own key rather than ``tapped_only:
        # False``, because absent already means "no restriction" and a matcher
        # reading a three-valued key with ``.get()`` would answer the wrong one
        # of the two.
        elif self.tapped is False:
            payload["untapped_only"] = True
        if len(self.colors) == 1:
            payload["color_filter"] = self.colors[0]
        elif self.colors:
            # "a green **or** white creature" — an object answering *any* of
            # them, which is what the printed "or" says. Its own key rather than
            # a list-valued `color_filter`, because that key means "has this
            # colour" to every matcher already reading it and a second type
            # under one name is how two readers come to disagree.
            #
            # This branch used to be `colors[0]`, silently dropping the rest:
            # no noun phrase could produce two colours, so nothing exercised it
            # — a dropped rider waiting for the parser to grow the union above.
            payload["any_colors"] = list(self.colors)
        if self.excluded_colors:
            payload["exclude_colors"] = list(self.excluded_colors)
        if self.excluded_types:
            payload["exclude_types"] = list(self.excluded_types)
        if self.attached_to_filter is not None:
            payload["attached_to_filter"] = self.attached_to_filter.to_payload()
        # Additive keys — handlers read these with .get() defaults.
        if self.with_keywords:
            payload["with_keywords"] = list(self.with_keywords)
        if self.without_keywords:
            payload["without_keywords"] = list(self.without_keywords)
        if self.controller:
            payload["controller"] = self.controller
        # Emitted on its own, not only beside a controller. It used to hang off
        # the branch above because the one card printing ownership printed both
        # words ("you both own and control", Obelisk of Undoing) — but "all
        # Auras **you own** attached to permanents you control" (Remove
        # Enchantments) narrows by ownership and by the *host's* controller,
        # which is a different seat question about a different object. Nested
        # under the controller test, that Aura's ownership was dropped and the
        # sweep took the opponent's Auras too.
        if self.owner is not None:
            payload["owner"] = self.owner
        if self.attacking:
            payload["attacking_only"] = True
        if self.was_dealt_damage_this_turn:
            payload["dealt_damage_this_turn"] = True
        if self.blocking:
            payload["blocking_only"] = True
        if self.any_states:
            payload["any_states"] = list(self.any_states)
        if self.other_than_source:
            payload["exclude_self"] = True
        if self.not_ability_targeted_by_same_name:
            payload["not_ability_targeted_by_same_name"] = True
        if self.not_enchanted:
            payload["not_enchanted"] = True
        if self.enchanted_only:
            payload["enchanted_only"] = True
        if self.nontoken:
            payload["nontoken"] = True
        if self.chosen_color:
            payload["chosen_color"] = True
        if self.attacked_this_turn is True:
            payload["attacked_this_turn"] = True
        elif self.attacked_this_turn is False:
            payload["not_attacked_this_turn"] = True
        if self.could_attack_this_turn is True:
            payload["could_attack_this_turn"] = True
        if self.token_only:
            payload["token_only"] = True
        if self.created_with_source:
            payload["created_with_source"] = True
        # "a card **named** Frantic Inventory". Emitted like every other
        # restriction, and tested like one — a key a matcher dropped would be a
        # count over every card in the graveyard.
        if self.named:
            payload["named"] = self.named
        # "of their choice" says *who picks*, which is not a property of the
        # objects picked from — no matcher can test it, and it is deliberately
        # absent from ``TESTABLE_SUBJECT_FILTER_KEYS`` for that reason. Emitting
        # it anyway is what makes the absence load-bearing: every gate that asks
        # "are all this payload's keys testable?" refuses the phrase, so the only
        # way through is a lowering that reads the word and says why its rule
        # already puts the choice there (``_lower_sacrifice``, CR 701.21a).
        if self.their_choice:
            payload["their_choice"] = True
        # "non-Spirit creature" (Roaming Ghostlight). Emitted only when set, so
        # every payload written before this key existed is byte-identical.
        if self.excluded_subtypes:
            payload["exclude_subtypes"] = list(self.excluded_subtypes)
        # "with mana value 3 or less" (Eliminate). Only a literal bound has a
        # payload form; a variable one ("mana value X") is left unemitted so
        # _filter_payload refuses the line rather than dropping the bound.
        if self.mana_value is not None and isinstance(self.mana_value.value, Fixed):
            payload["mana_value"] = {
                "op": self.mana_value.op,
                "value": self.mana_value.value.value,
            }
        # "with power 4 or greater" (Turret Ogre's intervening-if). Same rule
        # as mana_value: a literal bound rides the payload and the matcher
        # tests it against the layer-computed stat; a variable bound stays
        # unemitted. Both stats, because emitting one and dropping the other
        # would let a toughness restriction vanish silently.
        if self.power is not None and isinstance(self.power.value, Fixed):
            payload["power"] = {"op": self.power.op, "value": self.power.value.value}
        if self.toughness is not None and isinstance(self.toughness.value, Fixed):
            payload["toughness"] = {
                "op": self.toughness.op,
                "value": self.toughness.value.value,
            }
        if self.colored:
            payload["colored_only"] = True
        # "with a +1/+1 counter on it" (Tempered Veteran). Emitted only when
        # set, so every payload written before this key existed is
        # byte-identical.
        if self.with_plus1_counter:
            payload["with_plus1_counter"] = True
        # "a **legendary** card" (Niambi), "target **legendary** creature". A
        # supertype is a restriction like any other and rides the payload like
        # any other; until this key existed it rode nothing at all, and
        # "Destroy target legendary creature." lowered byte-identically to
        # "Destroy target creature." — the printed word consumed, recorded on
        # the AST, and then dropped on the way to the dispatcher.
        #
        # All or nothing. A phrase naming a supertype no matcher can test emits
        # no key rather than a narrowed one, so the field stays visibly set with
        # nothing behind it and the three gates below refuse the line. Emitting
        # the testable half would drop the other half silently, which is the
        # thing being fixed.
        if self.supertypes and set(self.supertypes) <= TYPE_LINE_SUPERTYPES:
            payload["supertypes"] = list(self.supertypes)
        return payload


@dataclass(frozen=True)
class PlayerRef:
    """A player or set of players."""
    kind: str  # you | each_player | each_opponent | target_player | target_opponent
               # | that_player | controller | owner | defending_player | chosen_player
    # "target player or planeswalker" (Chandra's Magmutt) — one chosen target
    # that may be a player face or a planeswalker permanent (CR 115.4 without
    # the creature half). Set only by the production that read the union, so a
    # lowering that never sees the phrase never sees the flag.
    or_planeswalker: bool = False
    # "target player **who attacked this turn**" (Fire and Brimstone). A printed
    # restriction on which seats may be chosen, not a different kind of player —
    # so it rides here rather than minting a `target_player_who_attacked`, for
    # the reason every other narrowing is payload: a card printing the same
    # clause on "target opponent" needs no new kind.
    attacked_this_turn: bool = False


@dataclass(frozen=True)
class TargetSpec:
    """A quantified object reference: "target creature", "each creature with
    flying", "up to two creatures", "any target"."""
    quantifier: str            # target | each | all | up_to | any_target | this | it | a
    filter: ObjectFilter = field(default_factory=ObjectFilter)
    count: int = 1
    # "**X** target lands" (Candelabra of Tawnos). The count is the announced X
    # (CR 601.2b), so it is not a number until the ability is activated —
    # recorded as a fact rather than baked into `count`, because a count of 0
    # and a count that is *not yet known* are different things and a picker
    # shown 0 would offer nothing.
    count_from_x: bool = False
    # "another target creature" (Garruk, Savage Herald's −2): a second chosen
    # object that must differ from the sentence's earlier choice — not from the
    # ability's source, which is what the filter's other_than_source says.
    distinct_from_prior: bool = False
    # Whether the word "target" was printed. The quantifier alone cannot say:
    # "up to two target creatures" (Read the Tides — chosen at cast, CR 601.2c)
    # and "up to four lands" (Rewind — chosen on resolution, no targets at all)
    # both read as ``up_to``, and the two reach entirely different machinery.
    # The parser used to consume the word and discard the fact, which is the
    # round-15 finding this field closes.
    targeted: bool = False
