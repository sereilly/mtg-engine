"""Protection (CR 702.16), and whether an object may be targeted (CR 115).

``_protection_qualities`` is the one answer to "what is this permanent
protected from?": a printed line, an attached Aura's grant, a lord's grant,
a granted flag, each with its timestamp so a later "loses protection from"
takes only what is older than it (CR 613.7). ``_permanent_has_quality`` /
``_card_has_quality`` / ``_source_has_quality`` are the other side of the
question - whether a source has the quality - for a permanent, for a spell
on the stack (which has no layers applied, CR 613.1) and for either.

``_is_protected_from`` is protection's damage and blocking halves (CR
702.16d-f) and ``_can_be_targeted`` its targeting half (CR 702.16b), with
shroud and hexproof beside it (CR 702.18, 702.11).
"""

from __future__ import annotations

import re

from ..entry_choices import own_chosen_protection_color
from ..aura_grants import (AMONG_CONTROLLED_PROTECTION_COLORS,
                           CHOSEN_PROTECTION_COLOR, aura_protection_colors)
from ..aura_attachment import auras_attached_to
from ..keywords import abilities_lost_at, protection_flag_granted_after
from ..lord_buffs import LORD_BUFF_KIND, lord_buff_from_payload
from ..handlers._targets import attached_host
from ..models import CardDefinition, Permanent
from ..oracle import compile_card_oracle
from ..oracle_types import _COLOR_WORD_TO_SYMBOL
from ..static_bonuses import conditional_static_holds


class ProtectionMixin:
    @staticmethod
    def _protection_quality_of(word: str) -> tuple[str, str] | None:
        """The canonical quality one word of a protection clause names, or None.

        ``engine/keywords.py``'s reader, reached through this name because five
        call sites in this file already ask it. It moved there when Righteous
        War's board-wide grant needed the *same* vocabulary at the gate: a word
        the shield reader cannot answer has to refuse the anthem rather than
        admit it and protect nobody, and a second copy of the four families is
        how those two answers come to differ.
        """
        from ..keywords import protection_quality

        return protection_quality(word)

    def _protection_qualities(
        self, permanent: Permanent, *, ignoring_aura: Permanent | None = None,
    ) -> set[tuple[str, str]]:
        """The qualities this permanent has protection from (CR 702.16).

        Sourced from a printed "protection from [quality]" line (static or
        comma-joined keyword form), from an attached Aura (the Ward cycle), or
        from a ``protection_from_<color>`` metadata flag. A word naming no
        modelled quality contributes nothing — but such a line never compiles
        in the first place: the keyword gate refuses it with the clause named.

        *ignoring_aura* leaves one attached Aura's own grant out of the
        answer. It exists for CR 702.16n, and its caller is the state-based
        sweep: "this effect doesn't remove this Aura" exempts the Aura from
        the protection **it** grants and from no other instance, so the sweep
        asks what the creature is protected from without it. The host
        predicate (``auras.enchant_card_refusal``) passes it too, for the one
        host whose protection an Aura's own grant can be: the one it is on.
        """
        qualities: set[tuple[str, str]] = set()
        program = compile_card_oracle(permanent.effective_card)
        from ..keywords import (EACH_OF_ITS_COLORS, PROTECTION_GRANT_STAMPS,
                                protection_qualities_named,
                                protection_removals)

        # "Target creature **loses protection from black** until end of
        # turn." (Cephalid Snitch.) A layer-6 removal takes every instance of
        # the quality older than it and none newer (CR 613.7), so each source
        # below adds what it grants *with its timestamp* and a removed quality
        # is kept only where something granted it after the removal. A printed
        # line is the oldest thing a permanent has (stamp 0). This reader asked
        # nothing, so the Snitch logged the loss and the White Knight kept
        # protection from black.
        removed_at = protection_removals(permanent)

        def _add(quality: tuple[str, str], stamp: int = 0) -> None:
            removal = removed_at.get(quality)
            if removal is None or stamp > removal:
                qualities.add(quality)

        def _named(word: str, stamp: int = 0) -> None:
            # One member of a clause, which may itself be shorthand for
            # several abilities: "each color" (CR 702.16h, Iridescent Angel)
            # is five, and "each of its colors" (CR 702.16i, Earnest
            # Fellowship) is one per colour **this** permanent has — read
            # through layer 5 now, so a creature a Lace turned red has
            # protection from red and no longer from what it was.
            #
            # The colours are computed only for the member that asks: every
            # other word is answered without touching the layers.
            held = None
            if " ".join(str(word).lower().split()) == EACH_OF_ITS_COLORS:
                held = self._effective_colors(permanent)
            for quality in protection_qualities_named(word, holder_colors=held) or ():
                _add(quality, stamp)

        def _absorb(clause: str) -> None:
            # CR 702.16g/h/i: "protection from [A] and from [B]" (and comma
            # separated variants) is shorthand for several separate protection
            # abilities.
            for word in re.split(r",|\band from\b|\band\b", clause):
                _named(word)

        for instr in program.instructions:
            if instr.kind == "static_line" and instr.value.startswith("protection from "):
                _absorb(instr.value[len("protection from "):].strip())
            elif instr.kind == "keyword_line":
                # Protection also rides comma-joined keyword lines ("Flying,
                # first strike, lifelink, protection from Demons and from
                # Dragons"), and a standalone protection line is admitted as a
                # keyword line too — same shorthand, same reading as the
                # static form above.
                for part in instr.value.split(","):
                    part = part.strip()
                    if part.startswith("protection from "):
                        _absorb(part[len("protection from "):].strip())
        # "This creature has protection from **the chosen color**." (Voice of
        # All.) The permanent's own static, spending the choice it made as it
        # entered (CR 614.1c). **Derived**, like every grant below: read off the
        # entry record on each ask, so a late answer to the prompt is the colour
        # it then has, and nothing has to remove it when the ability goes.
        own_chosen = own_chosen_protection_color(permanent)
        if own_chosen is not None:
            _add(("color", own_chosen))
        # **Every grant below is asked its age** where the permanent has lost
        # all abilities (CR 613.1f, CR 613.7): the loss takes the protection an
        # older effect gave and leaves a newer one's, which is the rule
        # ``Permanent.effective_card`` and layer 6 apply to every other kind of
        # granted ability (``keywords.abilities_lost_at``). The printed ones
        # above are already gone — they were read off the effective card. This
        # reader asked nothing, so a Ward attached before a Humility went on
        # protecting.
        lost_at = abilities_lost_at(permanent)

        def _kept(stamp: int) -> bool:
            return lost_at is None or stamp > lost_at

        # Two sources with different lifetimes, which is why both exist.
        #
        # An Aura's protection lasts exactly as long as it is attached, so it is
        # read off the Aura (the Ward cycle) and ends when the Aura leaves with
        # nothing having to remove it. That grant used to be stamped into the
        # metadata channel below and cleaned up by name on removal.
        for aura in auras_attached_to(permanent):
            if aura is ignoring_aura:
                # CR 702.16n's question — "does this creature have **other**
                # instances of protection from the same quality?" — asked by
                # the state-based sweep of the one Aura whose own grant says
                # it doesn't remove that Aura.
                continue
            # CR 613.7e: stamped when it became attached.
            aura_stamp = int(aura.metadata.get("aura_timestamp", aura.timestamp))
            if not _kept(aura_stamp):
                continue
            for word in aura_protection_colors(aura.effective_card.oracle_text):
                if word == AMONG_CONTROLLED_PROTECTION_COLORS:
                    # "…protection from **each color among permanents you
                    # control**." (Pledge of Loyalty.) CR 702.16i: one
                    # protection ability per colour in the set, and the set is
                    # the *Aura's* controller's board (CR 109.5) read now —
                    # through the layer-aware reader, so a gold permanent
                    # counts for each of its colours and a colourless one for
                    # none. The Aura itself is one of those permanents, which
                    # is why the card goes on to say the effect doesn't remove
                    # it (CR 702.16n, honoured by the state-based sweep).
                    #
                    # An Aura nobody controls contributes nothing rather than
                    # every colour: the widest reading of a set that could not
                    # be read is a creature no coloured thing can touch.
                    from ..object_colors import colors_among

                    aura_seat = self.controller_index_of(aura)
                    if aura_seat is not None:
                        for symbol in colors_among(
                            self, self.controlled_by(aura_seat)
                        ):
                            _add(("color", symbol), aura_stamp)
                    continue
                if word == CHOSEN_PROTECTION_COLOR:
                    # "…protection from **the chosen color**." (Ward of
                    # Lights.) The choice was made as the Aura entered
                    # (CR 614.12) and is recorded on the Aura as a *symbol*,
                    # so it skips the word table below. An Aura with no
                    # choice on it grants nothing rather than a guessed
                    # colour — protection from a colour nobody named is a
                    # shield the card never gave.
                    symbol = aura.metadata.get("chosen_color")
                else:
                    symbol = _COLOR_WORD_TO_SYMBOL.get(word)
                    if symbol is None:
                        # "…protection from **enchantments**" (Tattoo Ward):
                        # a quality that is not a colour, through the reader
                        # every printed clause goes through.
                        _named(word, aura_stamp)
                if symbol:
                    _add(("color", symbol), aura_stamp)
        # A lord's grant ("Other Cats you control … have protection from Dogs",
        # Feline Sovereign). **Derived**, exactly as the Aura grant above is: a
        # lord buff is cleared and rebuilt on every recompute, so a grant stamped
        # into metadata would be one nothing clears — and reading it off the
        # lord means it ends when the lord leaves with nothing having to remove
        # it.
        for lord_seat, lord in self.permanents_with_controller():
            for instr in compile_card_oracle(lord.effective_card).instructions:
                if instr.kind != LORD_BUFF_KIND:
                    continue
                buff = lord_buff_from_payload(instr.payload)
                if not buff.protection_from:
                    continue
                # A conditional lord grants nothing while its condition fails.
                # Asked here as well as at the P/T recompute, because this
                # reader derives from the compiled program directly — a buff
                # read past its own condition would grant protection on a board
                # the card says it does not.
                if buff.condition and not self._lord_buff_condition(
                    lord_seat, lord, buff.condition
                ):
                    continue
                if not self._lord_buff_matches(permanent, lord, buff):
                    continue
                if not _kept(lord.timestamp):
                    continue
                for word in buff.protection_from:
                    # Through the shorthand reader, so "Each creature has
                    # protection from each of its colors." (Earnest
                    # Fellowship) is computed per creature reached — *its*
                    # colours, not the lord's.
                    _named(word, lord.timestamp)
        # A **conditional** self-grant: "As long as an opponent controls a
        # creature with protection from white …, this creature has protection
        # from white." (Escaped Shapeshifter.) Derived, exactly as the Aura and
        # lord grants above are, and for the same reason — the condition can
        # stop holding between recomputes and a grant stamped into the metadata
        # channel below would be one nothing clears.
        #
        # It cannot ride ``add_derived_grant``, which the keyword half of
        # ``conditional_static`` uses, because that channel is one *word* per
        # grant and protection carries a quality (CR 702.16). So the payload key
        # is read here instead, by the one function that gathers every source of
        # a quality.
        #
        # ``_protection_grants_in_progress`` is what keeps this from recursing
        # without end: the condition may itself ask whether some creature has
        # protection (this card's does), and two such creatures facing each
        # other across the table would ask about each other for ever. A
        # permanent already being asked about contributes nothing to the
        # question about itself, which is the same fixed point the board
        # actually has.
        in_progress = getattr(self, "_protection_grants_in_progress", None)
        if in_progress is None:
            in_progress = self._protection_grants_in_progress = set()
        if permanent.permanent_id not in in_progress:
            in_progress.add(permanent.permanent_id)
            try:
                for grant_seat, granter in self.permanents_with_controller():
                    for instr in compile_card_oracle(
                        granter.effective_card
                    ).instructions:
                        if instr.kind != "conditional_static":
                            continue
                        words = instr.payload.get("protection_from") or ()
                        if not words:
                            continue
                        recipient = granter
                        if instr.payload.get("subject") == "attached":
                            recipient = attached_host(
                                self, granter, last_known=False
                            )
                        if recipient is not permanent:
                            continue
                        if not _kept(granter.timestamp):
                            continue
                        if not conditional_static_holds(
                            self, grant_seat, granter,
                            instr.payload.get("condition") or {},
                        ):
                            continue
                        for word in words:
                            quality = self._protection_quality_of(word)
                            if quality is not None:
                                _add(quality, granter.timestamp)
            finally:
                in_progress.discard(permanent.permanent_id)
        # The metadata channel, for protection granted with a lifetime of its own
        # (Feat of Resistance, until end of turn). Any quality, not just a
        # colour: the key is written from the same reader that parses a printed
        # clause, so a granted "protection from Demons" reads the same as a
        # printed one.
        for key in permanent.metadata:
            if key.startswith("protection_from_"):
                word = key[len("protection_from_"):]
                if lost_at is not None and not protection_flag_granted_after(
                    permanent, word, lost_at
                ):
                    continue
                _named(
                    word,
                    int((permanent.metadata.get(PROTECTION_GRANT_STAMPS) or {}).get(word, 0)),
                )
        # No Sleight of Mind step here: the clause above was read off
        # ``effective_card``, whose text layer 3 has already rewritten, so
        # "protection from blue" already reads "protection from red". Remapping
        # again applied the change twice — invisible for the one-effect case
        # only because the second application had nothing left to match.
        return qualities

    def _protection_colors(self, permanent: Permanent) -> set[str]:
        """The colour slice of :meth:`_protection_qualities`, kept for the
        consumers whose question genuinely is a colour (the Aura-attach checks,
        the Circle prompts)."""
        return {
            value
            for kind, value in self._protection_qualities(permanent)
            if kind == "color"
        }

    def _permanent_has_quality(
        self, source: Permanent, quality: tuple[str, str], *,
        as_damage_source: bool = False,
    ) -> bool:
        """Whether *source* has *quality* (CR 702.16e/f).

        *as_damage_source* asks the colour half of the question about the source
        **as a source of damage** (CR 609.7b) rather than about the object:
        Ghostly Flame makes a red creature a colorless source of damage and
        leaves the creature red, so its combat damage is not prevented by
        protection from red while the creature is still an illegal target for
        "enchant red creature". Only the damage paths pass it.
        """
        kind, value = quality
        if kind == "color":
            if as_damage_source:
                from ..damage_source_colors import damage_source_colors

                return value in damage_source_colors(self, source)
            return value in self._effective_colors(source)
        if kind == "multicolored":
            # Deliberately not rewritten by a damage-source static: "colorless
            # sources of damage" says what colour the source is, and a
            # colourless object is not multicoloured either — but no card in
            # this pool prints protection from multicoloured *and* meets one, so
            # widening the rewrite to a quality nothing exercises would be a
            # claim with nothing behind it.
            return len(self._effective_colors(source)) >= 2
        if kind == "spell_type":
            # "protection from **instant spells**" (Devoted Caretaker). A
            # permanent is not a spell (CR 111.1 / CR 110.1: a spell is a card
            # on the stack), so nothing on the battlefield has this quality —
            # no blocker, no Aura, no Equipment, and no ability's source.
            return False
        if kind in ("card_type", "subtype"):
            # has_type resolves through the layer system, so a granted or
            # layer-4 type counts exactly as a printed one.
            return source.has_type(value)
        if kind == "typed":
            # "protection from **legendary creatures**" (Tsabo Tavoc): a
            # conjunction, every word of it. A supertype is not a type —
            # ``has_type`` answers about card types and subtypes and would say
            # no to every legend — so the supertype words go through the
            # layer-4 supertype accessor, the same split
            # ``_lord_buff_matches`` makes for "legendary creatures you
            # control".
            from ..grammar.vocabulary import TYPE_LINE_SUPERTYPES

            held = source.effective_supertypes
            return all(
                (word in held) if word in TYPE_LINE_SUPERTYPES
                else source.has_type(word)
                for word in value.split()
            )
        return False

    def _card_has_quality(
        self, card: CardDefinition, quality: tuple[str, str], *,
        as_damage_source: bool = False, seat: int | None = None,
    ) -> bool:
        """The same question of a *card* — a spell on the stack, which has no
        permanent to ask the layers about.

        *as_damage_source* means the same thing here as it does one method up,
        and it is not decoration: a spell is a damage source as readily as a
        permanent is (CR 109.5), so Ghostly Flame rewrites a red *burn spell*
        into a colorless source exactly as it rewrites a red creature. Reading
        ``card.colors`` for a damage question would have left protection from
        red stopping a Lightning Bolt the board had made colorless.

        *seat* is **whose** spell or card this is, and it is what makes the
        colour half of CR 702.16a a live reading rather than a printed one.
        "No permanent to ask the layers about" is true and does not mean the
        layers say nothing: CR 613.1 applies layer 5 to an *object*, and
        Celestial Dawn's second sentence puts every spell its controller
        controls in scope. Without the seat a Terror the Dawn had made white
        was still a black spell here, and a White Knight went on reporting it
        an illegal target. A caller that cannot say gets the printed answer,
        which is what every caller gave before the argument existed.
        """
        kind, value = quality
        if kind == "color":
            if as_damage_source:
                from ..damage_source_colors import damage_source_colors

                return value in damage_source_colors(self, card, seat=seat)
            from ..object_colors import card_colors

            return value in card_colors(self, card, seat)
        if kind == "multicolored":
            # Not rewritten by a damage-source static, mirroring
            # :meth:`_permanent_has_quality` exactly -- see the reason written
            # out there. It *is* read through the layers, because that is a
            # different question and the one this method was getting wrong.
            from ..object_colors import card_colors

            return len(set(card_colors(self, card, seat))) >= 2
        if kind == "spell_type":
            # "protection from **instant spells**" (Devoted Caretaker): the
            # card type of a **spell**. Every caller hands this method a card
            # for one of two reasons — a spell choosing a target
            # (``_can_be_targeted``, which asks only when no ability is
            # choosing) or a spell as a damage source (CR 109.5) — so the type
            # is the whole question here. The printed line, as for the
            # card-type arm below: a spell has no layer-4 effect in this pool.
            return value in (card.type_line or "").lower().split()
        if kind in ("card_type", "subtype"):
            return value in (card.type_line or "").lower().split()
        if kind == "typed":
            # The conjunction, off the printed line — a spell has no layers to
            # ask about its types, and a supertype and a type are both words
            # of that one line (CR 205.1).
            printed = (card.type_line or "").lower().split()
            return all(word in printed for word in value.split())
        return False

    def _source_has_quality(
        self, source, quality: tuple[str, str], *, as_damage_source: bool = False,
        seat: int | None = None,
    ) -> bool:
        """Whether a damage source of **either** shape has *quality*.

        CR 109.5 gives a damage event two kinds of source: a ``Permanent`` for a
        permanent's combat damage or ability, and the printed
        ``CardDefinition`` for a spell. The two answer different methods — a
        permanent's type resolves through the layer system, a card's is read off
        its printed line — and until CR 702.16e reached the damage seam only the
        permanent half was ever asked, because the four combat call sites can
        only ever hand over a creature.

        Dispatched on ``has_type``, which is what a ``Permanent`` has and a
        ``CardDefinition`` does not, rather than on an ``isinstance``: a token,
        an animated land and a copy are all permanents by that question and the
        import stays out.
        """
        if source is None:
            return False
        if hasattr(source, "has_type"):
            return self._permanent_has_quality(
                source, quality, as_damage_source=as_damage_source
            )
        card = getattr(source, "card", source)
        if not hasattr(card, "colors"):
            return False
        # *seat* only ever reaches the card half: a permanent's layers already
        # know whose it is, so passing it there would be a second opinion.
        return self._card_has_quality(
            card, quality, as_damage_source=as_damage_source,
            seat=seat if seat is not None else getattr(source, "caster_index", None),
        )

    def _is_protected_from(
        self, victim: Permanent, source, *, as_damage_source: bool = False,
        seat: int | None = None, ignoring_aura: Permanent | None = None,
    ) -> bool:
        """True if *victim* has protection from a quality *source* has
        (CR 702.16e/f).

        *as_damage_source* is passed by the damage half of protection
        (CR 702.16e, ``engine/prevention.py``'s interceptor) and **not** by the
        blocking half (CR 702.16d/509.1b, the declare-blockers step): a static
        that rewrites a source's colour *for damage* changes which damage is
        prevented and not which creatures may block, and reading it at both
        would be a strictly different card.

        *source* is whatever a damage event carries (CR 109.5) — a permanent or
        a spell's printed card — because the damage half is now asked of every
        damage event rather than only of the four combat sites, and those were
        the only callers that could guarantee a permanent.

        *seat* is that source's controller, and only the card half reads it —
        see :meth:`_card_has_quality`. The damage callers have it already:
        ``damage_events`` derives ``source_seat`` once per event for exactly
        this class of question, so the caller passes it rather than deriving a
        second answer here.
        """
        return any(
            self._source_has_quality(
                source, quality, as_damage_source=as_damage_source, seat=seat,
            )
            for quality in self._protection_qualities(
                victim, ignoring_aura=ignoring_aura
            )
        )

    def _can_be_targeted(
        self,
        target: Permanent,
        source_card: CardDefinition | None,
        *,
        caster_index: int | None = None,
        ability_source=None,
        source_spec: dict | None = None,
    ) -> bool:
        """Whether *target* is a legal target for *source_card*
        (CR 702.16b/702.18/702.11).

        Shroud forbids any targeting; protection forbids targeting by sources of
        the protected color. A ``None`` source is treated as colorless.

        *ability_source* is the object whose **ability** is choosing this target,
        and passing it is what says the choice belongs to an ability rather than
        to a spell. Its presence is the flag rather than a separate boolean: an
        immunity narrowed to a class of source ("can't be the target of
        abilities from artifact sources", Artifact Ward; "…or abilities from
        white sources", Raiding Party) needs the source object itself, because
        an animated artifact land is an artifact source and its printed type
        line says otherwise, and because a colour is a layer question. Every
        caller that leaves it out is aiming a spell, where the immunity does
        not apply.

        Hexproof (CR 702.11b/d) forbids targeting by spells and abilities an
        *opponent* of the target's controller controls, so it is asked only when
        the caller says who is casting — a probe with no seat keeps the
        seat-blind answer. "Hexproof from <colour>" narrows the same rule to
        sources of that colour; it is a different keyword from bare hexproof
        (a colour word in the abilities set, seeded from the ingested keywords
        field), which is why both spellings are consulted.

        *source_spec* is the **target description** the chooser announced, for
        the one restriction that is about the description rather than about the
        source: "can't be the target of spells that can target only Walls"
        (Wall of Shadows). A spell's is derived here from its own card, so the
        three casting callers need pass nothing; an ability's cannot be — a
        permanent may carry several abilities that target differently, and
        ``ability_source`` names the object, not which of its abilities is
        choosing — so the enumerator, which is holding the spec it is
        enumerating, hands it over.
        """
        if self._has_keyword(target, "shroud"):
            from ..target_immunity import shroud_waived_for

            # "Until end of turn, Autumn Willow can be the target of spells and
            # abilities controlled by **target player** as though it didn't
            # have shroud." (CR 702.18 with CR 609.4's hole in it.) The waiver
            # is per seat, so it is asked with the seat whose spell or ability
            # is choosing: the caster for a spell, and the *controller of the
            # source* for an ability, which is CR 109.5's answer and not
            # necessarily the same seat.
            #
            # A caller that names neither gets the shroud, which is the
            # direction that cannot let an illegal targeting through — the same
            # answer every other seat-relative immunity here gives a seat-blind
            # probe.
            chooser = caster_index
            if chooser is None and ability_source is not None:
                chooser = self.controller_index_of(ability_source)
            if not shroud_waived_for(target, chooser):
                return False
        # "…can't be the target of Aura spells" (Bartel Runeaxe, Tetsuo
        # Umezawa), "…can't be the target of spells" (Anti-Magic Aura). Asked
        # only when the chooser is a *spell*, which `ability_source is None`
        # says: these clauses narrow shroud to spells, and Artifact Ward's
        # sibling below narrows it to abilities. A spell and an ability are
        # separately targeted (CR 115.1a, CR 115.1c/d) and a card may print
        # either without the other, so neither may answer for both.
        if ability_source is None and source_card is not None:
            from ..target_immunity import (
                board_target_immunity_classes,
                spell_is_in_class,
                spell_target_immunity_classes,
            )

            # The board-wide subject beside the two relational ones, and asked
            # of the same `spell_is_in_class` reader so a class string means one
            # thing here however the clause reached this permanent. "Creatures
            # can't be the targets of spells." (Dense Foliage) is printed on
            # some other permanent entirely — there is no relation from this
            # creature back to the line — so it takes the game and scans, which
            # `printed_about` structurally cannot do.
            if any(
                spell_is_in_class(
                    source_card, spell_class, game=self, seat=caster_index,
                )
                for spell_class in (
                    spell_target_immunity_classes(target)
                    | board_target_immunity_classes(self, target)
                )
            ):
                return False
        if ability_source is not None:
            from ..target_immunity import (
                ABILITY_SOURCE,
                ability_source_immunity_classes,
                board_target_immunity_classes,
                source_is_in_class,
            )

            # The board-wide subject beside the relational ones, exactly as the
            # spell branch above unions them: "Creatures you control can't be
            # the targets of blue spells **or abilities from blue sources**."
            # (Spellbane Centaur) is printed on some other permanent entirely.
            if any(
                source_is_in_class(self, ability_source, source_class)
                for source_class in (
                    ability_source_immunity_classes(target)
                    | board_target_immunity_classes(self, target, ABILITY_SOURCE)
                )
            ):
                return False
        # "…can't be the target of spells that can target only Walls or of
        # abilities that can target only Walls" (Wall of Shadows). A narrowed
        # shroud again, but narrowed along the *other* axis: the two clauses
        # above ask what the source **is**, this one asks what the source's own
        # target description **admits**. Tunnel ("Destroy target Wall") is
        # stopped; Terror ("Destroy target creature") is not, however plainly it
        # could kill the same Wall.
        #
        # Asked per source kind, because a spell and an ability are separately
        # targeted (CR 115.1a, CR 115.1c/d) so a card can stop one and not the
        # other, and the two answers come from different places: a spell's
        # description is derived from its card right here, while an ability's
        # must be handed in — ``ability_source`` names the permanent, and a
        # permanent may carry several abilities that target differently.
        if source_card is not None or source_spec is not None:
            from ..target_immunity import (
                ABILITY_SOURCE,
                SPELL_SOURCE,
                narrow_source_immunity_subtypes,
            )

            forbidden = narrow_source_immunity_subtypes(
                target, ABILITY_SOURCE if ability_source is not None else SPELL_SOURCE
            )
            if forbidden:
                from ..targeting import derive_cast_spec, spec_only_subtype

                spec = source_spec
                if spec is None and ability_source is None:
                    from ..oracle import compile_card_oracle

                    spec = derive_cast_spec(
                        source_card, compile_card_oracle(source_card)
                    )
                only = spec_only_subtype(spec)
                if only is not None and only in forbidden:
                    return False
        # CR 702.16b. **An ability's source is the object, and the object is
        # what the layers answer about** (CR 702.16a's exception to CR 109.2:
        # "sources that are permanents with that card type"). A card read gives
        # the printed line, so an animated artifact land aiming an ability would
        # be a non-artifact source and a laced permanent the wrong colour —
        # exactly the split ``prevention.source_has_type`` writes out one module
        # over. The card read stays for a *spell*, which has no permanent.
        qualities = self._protection_qualities(target)
        if (
            qualities
            and ability_source is not None
            and any(
                self._permanent_has_quality(ability_source, quality)
                for quality in qualities
            )
        ):
            return False
        if source_card is not None and any(
            self._card_has_quality(source_card, quality, seat=caster_index)
            for quality in qualities
            # "…from instant **spells**" is asked of a spell alone: when an
            # ability is choosing, *source_card* is the card of the object
            # whose ability it is, and an ability is not a spell (CR 113.1)
            # whatever its source's type line says.
            if not (quality[0] == "spell_type" and ability_source is not None)
        ):
            return False
        if caster_index is not None and caster_index != self.controller_index_of(target):
            if self._has_keyword(target, "hexproof"):
                return False
            if source_card is not None:
                # The same layer-5 reading the protection block above makes,
                # and for the same reason: "hexproof from black" asks what
                # colour the spell **is** (CR 702.11d), which is not the field
                # printed on the card.
                from ..object_colors import card_colors

                source_colors = set(card_colors(self, source_card, caster_index))
                for word, symbol in _COLOR_WORD_TO_SYMBOL.items():
                    if symbol in source_colors and self._has_keyword(
                        target, f"hexproof from {word}"
                    ):
                        return False
        return True
