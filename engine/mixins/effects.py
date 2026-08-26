from __future__ import annotations

import random
import re

from ..ante import is_ante_card
from ..card_hooks import UNTAPPED_ARTIFACT_PROTECTORS
from ..handlers._common import permanent_matches_filter, pick_target_permanent
from ..auras import aura_restriction_active
from ..auras import aura_enchants
from ..damage_events import damage_source_seat, deal_damage, lifelink_life_gained
from ..events import Event, collect, emit
from ..land_play_allowance import LandPlayAllowance, land_play_allowance_for
from ..models import CardDefinition, Permanent, PlayerState
from ..pt import add_plus1_counters, add_pt_counters
from ..regeneration import regeneration_replaces_destruction
from ..replacement_choices import pending_choices_for, resolve_choice
from ..replacements import TOP_OF_LIBRARY_DISCARD_TEXT, apply_replacements
from ..oracle import OracleInstruction, compile_card_oracle, lex_oracle_text
from ..auras import aura_death_damage_line
from ..trigger_utils import iter_triggered_abilities, make_trigger_event, matching_triggers

class EffectsMixin:
    def _trigger_aura_death_effects(self, dead_permanent: Permanent, controller: PlayerState) -> None:
        """Put an Aura's death-trigger effect onto the stack when the creature it
        enchants leaves the battlefield (e.g. an Aura that deals damage equal to the
        creature's toughness). The toughness is captured now (the creature is gone by
        resolution); the trigger resolves off the stack (CR 603.3)."""
        aura = dead_permanent.metadata.get("attached_aura")
        if aura is None:
            return
        prog = compile_card_oracle(aura.card)
        text = prog.normalized_text
        if not aura_enchants(aura.effective_card.oracle_text, "creature"):
            return
        controller_index = self.players.index(controller)
        for trig in prog.triggered_abilities:
            # `attached_creature_dies` — the condition this always meant. It read
            # the generic `dies` because that was the only kind the trigger
            # table produced for the phrase, and "when enchanted creature dies"
            # is not the Aura's own death.
            #
            # And the condition alone is **not** what this dispatcher
            # implements. It implements one printed sentence — "…this Aura
            # deals damage equal to that creature's toughness to the creature's
            # controller" — and firing on the kind gave that damage to every
            # other Aura printing the same trigger word: Puppet Master returned
            # nothing to its owner's hand and dealt its controller damage
            # instead, and Takklemaggot would have done the same. The line is
            # asked through `auras.aura_death_damage_line`, the same reader the
            # support gate uses, so what fires and what is claimed cannot
            # disagree.
            if (
                trig.condition.kind == "attached_creature_dies"
                and aura_death_damage_line(trig.source_line or "")
            ):
                toughness = dead_permanent.effective_toughness
                self._enqueue_triggered_ability(
                    controller_index=controller_index,
                    card=aura.card,
                    instruction=OracleInstruction("deal_damage_to_player", None, {}),
                    effect_kind="triggered_damage",
                    ability_text=trig.source_line,
                    trigger_context={"victim_player_index": controller_index, "amount": toughness},
                )
                break

    def _fire_delayed_combat_damage_triggers(
        self, attacker: "Permanent", defending_player: "PlayerState", amount: int
    ) -> None:
        """Delayed triggers armed on "whenever <subject> deals combat damage to
        a player" (CR 603.7) — Subira, Tulzidi Caravanner.

        Its own fire site beside the permanent-ability one rather than a branch
        inside it: a delayed trigger has no source permanent to scan from, which
        is exactly why the entry list exists, and the ability scan cannot reach
        an entry that belongs to no permanent. Round 93 and round 105 both found
        a trigger with nowhere to be announced; arming one whose event no site
        reads is the same defect, so the compiler refuses an event that is not
        in ``delayed_triggers.DELAYED_EVENTS`` and this is the site that makes
        the combat-damage entry true.
        """
        from ..delayed_triggers import fire_delayed_triggers

        if amount <= 0:
            return
        fire_delayed_triggers(
            self, "creature_deals_combat_damage_to_player",
            subject=attacker,
            # Named rather than defaulted: this event's effects act on the
            # creature that dealt the damage ("…, <do something to **it**>"),
            # which is the one shape where the watched object is also the
            # ability's stack source.
            source_permanent=attacker,
            trigger_context={
                "defending_player_index": self.players.index(defending_player),
                "amount": amount,
            },
        )

    def _fire_batched_combat_damage_triggers(self, damagers_by_defender: dict) -> None:
        """"Whenever **one or more** <subject> deal combat damage to a player."
        (Feline Sovereign.)

        One trigger per player damaged, however many creatures dealt it — which
        is why this cannot ride the per-attacker fire site: that one is called
        once per attacker, and calling it for a batched condition would fire the
        ability once per Cat.

        The subject is the trigger's own parsed noun phrase, tested against each
        creature that actually dealt damage to that player — so a Cat that was
        blocked and dealt none does not count, and neither does a creature the
        phrase does not name. The damaged player rides the trigger context as
        `defending_player_index`, which is what the effect's "that player" reads.
        """

        from ..subject_filters import subject_matches
        from ..trigger_utils import iter_triggered_abilities, make_trigger_event

        events = []
        for defender_index, damagers in sorted(damagers_by_defender.items()):
            for controller_index, permanent, trig in iter_triggered_abilities(
                self, condition_kinds={"one_or_more_deal_combat_damage"}
            ):
                described = trig.condition.payload.get("damagers_filter") or {}
                if not any(
                    subject_matches(
                        self, damager, described,
                        observer=controller_index, source=permanent,
                    )
                    for damager in damagers
                ):
                    continue
                events.append(make_trigger_event(
                    controller_index, permanent, trig,
                    trigger_context={"defending_player_index": defender_index},
                ))
        self._enqueue_triggered_batch(events)

    def _fire_dealt_damage_triggers(self, permanent: Permanent, amount: int = 0) -> None:
        """Put 'whenever this creature is dealt damage' triggers (Fungusaur,
        Brash Taunter) onto the stack; they resolve off the stack (CR 603.3)
        rather than inline.

        *amount* is how much was dealt, frozen into the trigger's context
        because "it deals **that much** damage" (Brash Taunter) has nowhere else
        to read it: by the time the trigger resolves, the marked damage may have
        been added to by something else or wiped by a cleanup.

        The instruction-kind filter is gone. It named `add_counter_to_self` —
        Fungusaur's one shape — so every other card written with this condition
        parsed it and then never fired, which is the failure `engine/events.py`
        exists to describe.
        """
        controller_index = self._controller_index_of(permanent)
        events = [
            make_trigger_event(
                controller_index, permanent, trig,
                trigger_context={"damage_dealt": max(0, int(amount))},
            )
            for trig in matching_triggers(
                permanent.effective_card,
                condition_kinds={"creature_dealt_damage"},
            )
        ]
        self._enqueue_triggered_batch(events)

    def _controller_index_of(self, permanent: Permanent) -> int:
        """Index of the player who currently controls *permanent* (0 if not found —
        e.g. a permanent already removed from the battlefield)."""
        index = self.controller_index_of(permanent)
        return 0 if index is None else index

    def _is_indestructible(self, permanent: Permanent) -> bool:
        """CR 700.4: a permanent with indestructible can't be destroyed by 'destroy'
        effects or lethal damage. In LEA, Consecrate Land grants this to a land."""
        # Indestructible from an attached Aura (Consecrate Land) arrives through
        # layer 6 like any other keyword, so it ends when the Aura does. The
        # metadata flag stays for a grant with a lifetime of its own.
        return (
            bool(permanent.metadata.get("is_indestructible"))
            or self._has_keyword(permanent, "indestructible")
            or self._untapped_artifact_protector_active(permanent)
        )

    def _cant_be_enchanted(self, permanent: Permanent) -> bool:
        """Whether an Aura can't be attached to *permanent* — either a per-permanent
        flag set by an effect, or Guardian Beast's continuous grant to the
        noncreature artifacts its controller controls while it's untapped."""
        from ..auras import cant_be_enchanted_by_own_text

        return (
            bool(permanent.metadata.get("cant_be_enchanted_by_auras"))
            or aura_restriction_active(permanent, "cant_be_enchanted_by_auras")
            # "This token can't be enchanted." — the restriction printed on the
            # permanent itself rather than granted to it.
            or cant_be_enchanted_by_own_text(permanent)
            or self._untapped_artifact_protector_active(permanent)
        )

    def _untapped_artifact_protector_active(self, permanent: Permanent) -> bool:
        """Guardian Beast-style: "As long as this creature is untapped,
        noncreature artifacts you control can't be enchanted, have
        indestructible, and other players can't gain control of them."
        Checked inline (mirrors Veteran Bodyguard's "as long as untapped"
        redirect) rather than precomputed, since it tracks the protector's
        tapped state continuously. Auras already attached when it enters
        aren't removed — callers that check "already attached" separately
        are unaffected. Protector names live in
        card_hooks.UNTAPPED_ARTIFACT_PROTECTORS, not here (CLAUDE.md: no
        card names outside card_hooks.py)."""
        if not permanent.has_type("artifact") or permanent.is_creature:
            return False
        # Identity, not ``in``: Permanent is a plain dataclass, so ``in`` compares
        # field-by-field and would match an opponent's identically-stated copy of
        # the same artifact — protecting artifacts its controller doesn't control.
        controller_seat = self.controller_index_of(permanent)
        if controller_seat is None:
            return False
        controller = self.players[controller_seat]
        return any(
            perm.card.name in UNTAPPED_ARTIFACT_PROTECTORS and not perm.tapped
            for perm in self.controlled_by(controller)
        )

    def _controls_top_of_library_discard(self, player: PlayerState) -> bool:
        """Whether *player* controls a Library of Leng-style permanent that lets
        them redirect a discard to the top of their library (CR 701.9c).

        Used by the *chosen*-discard flow, where the player picks which card to
        discard and where it goes in one prompt, so the offer has to be known
        before the discard happens. A forced discard instead routes through the
        ``discard`` replacement in engine/replacements.py, which reads the same
        text."""
        return self._player_controls_text(player, TOP_OF_LIBRARY_DISCARD_TEXT)

    def _set_lockout_banning_card(self, card: CardDefinition) -> str | None:
        """City in a Bottle: whether some permanent's compiled
        ``ban_and_sacrifice_set_permanents`` instruction bans *card*. Returns
        the banning permanent's name, or None if unbanned. Shared by the
        cast/land-play gate (queue_from_hand) and the battlefield-sacrifice
        state check (game_ending.py).

        The card's *original* printing decides, not whichever set happened to
        load first: "a name originally printed in Arabian Nights" still names
        an Arabian Nights card once Revised reprints it.
        """
        card_set = card.original_printing.lower()
        if not card_set:
            return None
        for perm in self.all_permanents():
            for instr in compile_card_oracle(perm.effective_card).instructions:
                if (
                    instr.kind == "ban_and_sacrifice_set_permanents"
                    and str(instr.payload.get("set_code", "")).lower() == card_set
                ):
                    return perm.card.name
        return None

    def _destroy_target_permanent(
        self,
        target: PlayerState,
        type_filter: str | None = None,
        color_filter: str | None = None,
        target_permanent_index: int | None = None,
        exclude_colors: list[str] | None = None,
        exclude_types: list[str] | None = None,
        bypass_regeneration: bool = False,
        subtype_filter: str | None = None,
        tapped_only: bool = False,
        attached_to_filter: dict | None = None,
    ) -> CardDefinition | None:
        target_player_index = next(
            (i for i, p in enumerate(self.players) if p is target), None
        )

        # Shared filter evaluation (handlers/_common.py) so resolution can
        # never disagree with cast validation / legality enumeration about
        # what a target filter means.
        filter_payload = {
            "type_filter": type_filter,
            "subtype_filter": subtype_filter,
            "tapped_only": tapped_only,
            "color_filter": color_filter,
            "exclude_colors": exclude_colors,
            "exclude_types": exclude_types,
            "attached_to_filter": attached_to_filter,
        }

        def _is_legal_target(perm) -> bool:
            return permanent_matches_filter(perm, filter_payload)

        def _do_destroy(perm: "Permanent", idx: int) -> "CardDefinition":
            # Pyramids: a shielded land's destruction is replaced — remove all
            # damage marked on it instead.
            if self._consume_land_destruction_shield(perm):
                return None  # type: ignore[return-value]
            if self._is_indestructible(perm):
                self.log.append(f"{perm.card.name} can't be destroyed (indestructible)")
                return None  # type: ignore[return-value]
            # One decision, in `engine/regeneration.py`: the shield (CR 701.19a),
            # the static form (CR 701.19b) and the "can't be regenerated" rider
            # (CR 701.19c) are the same question asked at the same moment, and
            # this was one of the two places asking half of it.
            if not bypass_regeneration and regeneration_replaces_destruction(self, perm):
                return None  # type: ignore[return-value]
            self.remove_from_battlefield(perm)
            self._permanent_to_graveyard(target, perm)
            self._trigger_aura_death_effects(perm, target)
            if perm.card.primary_type == "land" and target_player_index is not None:
                self._process_land_dies(target_player_index)
            # 611.3b: a destroyed permanent's static buffs / dynamic P/T (Castle,
            # Gauntlet of Might, Lord of Atlantis, Nightmare's swamp count) must be
            # recomputed now that it has left the battlefield.
            self._recompute_continuous_effects()
            return perm.card

        if target_permanent_index is not None:
            if 0 <= target_permanent_index < len(target.battlefield):
                permanent = target.battlefield[target_permanent_index]
                if not _is_legal_target(permanent):
                    return None
                return _do_destroy(permanent, target_permanent_index)
            return None

        for idx, permanent in enumerate(target.battlefield):
            if not _is_legal_target(permanent):
                continue
            return _do_destroy(permanent, idx)

        return None

    def _tap_or_untap_target(
        self, target: PlayerState, make_tapped: bool, target_permanent_index: int | None = None
    ) -> "Permanent | None":
        """The permanent this tapped or untapped, or None if there was none.

        The object rather than a bare success flag, because the sentence after
        this one may be about it ("Tap target creature. **It** doesn't untap
        …", Telekinesis) and the caller has no other way to name what was
        chosen — reconstructing it would be a second copy of the choice, free
        to disagree with the first.
        """
        # Honor an explicitly chosen permanent (Twiddle: "tap or untap target
        # artifact, creature, or land" — the player picks which one, on either
        # battlefield). Fall back to the first permanent only when no explicit
        # choice was supplied (AI/headless).
        chosen = pick_target_permanent(target, target_permanent_index, predicate=lambda p: True)
        if chosen is None:
            return None
        chosen.tapped = make_tapped
        if make_tapped:
            # Illusionary Mask: a face-down creature that becomes tapped is
            # turned face up (no-op for everything else).
            self._turn_face_up(chosen)
        return chosen

    def _match_chosen_damage_source(self, chosen_sources, source):
        """The entry of *chosen_sources* matching this damage's source, or None.
        A chosen permanent matches the dealing Permanent by identity; a chosen spell
        matches by its CardDefinition (the same object the spell deals damage with)."""
        if source is None or not chosen_sources:
            return None
        source_card = getattr(source, "card", source)
        for chosen in chosen_sources:
            chosen_card = getattr(chosen, "card", chosen)
            if chosen is source or chosen is source_card or chosen_card is source_card:
                return chosen
        return None

    def _damage_source_matches(self, chosen, source) -> bool:
        """Whether an incoming damage *source* is the *chosen* one (Jade Monolith's
        "a source of your choice"). No recorded choice matches anything (legacy /
        AI activations); an unknown incoming source never consumes a specific
        choice — the shield keeps waiting for its source."""
        if chosen is None:
            return True
        if source is None:
            return False
        if chosen is source:
            return True
        chosen_card = getattr(chosen, "card", chosen)
        source_card = getattr(source, "card", source)
        return chosen_card is source_card

    def _turn_face_up(self, permanent) -> None:
        """Illusionary Mask: a face-down creature is turned face up any time it
        would deal damage, damage would be dealt to it, or it becomes tapped.
        Restores the real card stashed at cast time (P/T, types, abilities)."""
        metadata = getattr(permanent, "metadata", None)
        if not metadata or not metadata.get("face_down"):
            return
        real = metadata.pop("face_down_real_card", None)
        metadata.pop("face_down", None)
        if real is not None:
            permanent.card = real
            self.log.append(f"{real.name} was turned face up")
            self._recalculate_lord_buffs()

    def _mark_damage_on_permanent(
        self, permanent, amount: int, source=None, combat: bool = False, *, then=None,
        restart=None, asks: bool = False,
    ) -> int:
        """Mark *amount* damage on a creature after applying its prevention
        shields. Returns the damage actually marked (0 if fully prevented).
        *combat* marks the event as combat damage so the blanket combat shields
        (Fog, Ebony Horse) can see it.

        ``then`` is what the caller would otherwise do with the returned number
        — see ``_deal_damage_to_player`` for why it is a callback and not a
        return value."""
        # Illusionary Mask: turn a face-down creature face up when damage would
        # be dealt to it or it would deal damage (before prevention, CR 613/614).
        if amount > 0:
            self._turn_face_up(permanent)
            self._turn_face_up(source)
        # The whole CR 120.4 sequence in one place: the redirects (Jade Monolith,
        # Personal Incarnation) and the shields protecting this creature contend
        # as one set for what is dealt, and the result — damage marked — is
        # processed after. engine/damage_events.py runs both halves.
        if asks and restart is None:
            def restart():
                self._mark_damage_on_permanent(
                    permanent, amount, source=source, combat=combat, then=then, asks=True
                )

        outcome = deal_damage(
            self,
            {"recipient": permanent, "amount": amount, "source": source, "combat": combat},
            restart=restart,
        )
        if outcome.suspended:
            return 0
        if outcome.result > 0:
            # CR 120.3: the result depends on what the recipient is. A
            # planeswalker loses that many loyalty counters (120.3c); a
            # creature has the damage marked on it (120.3e); a permanent that
            # is both gets both results.
            is_planeswalker = permanent.has_type("planeswalker")
            if is_planeswalker:
                loyalty = permanent.metadata.get("loyalty_counters", 0)
                permanent.metadata["loyalty_counters"] = max(0, loyalty - outcome.result)
            if permanent.is_creature or not is_planeswalker:
                permanent.damage_marked += outcome.result
        # CR 702.15b. Combat is excluded because the combat damage step tallies
        # its own lifelink across the step and gains once in its tail — this is
        # the same call, and running it here too would gain twice for every
        # blocked creature. `combat` is the flag that tells the two apart.
        if not combat:
            self._apply_lifelink(source, outcome.dealt)
        # CR 702.2b / 704.5h: nonzero damage from a source with deathtouch marks
        # the victim for destruction at the next state-based check — any damage,
        # not only combat damage. Lifelink directly above is the precedent: the
        # rule lives on the one path every creature-damage caller runs through,
        # so a ping ability destroys exactly as a blocker does. The getattr
        # mirrors lifelink_life_gained's guard — a spell or bare card has no
        # keyword to read.
        if (
            outcome.dealt > 0
            and source is not None
            and getattr(source, "has_keyword", None) is not None
            and self._has_keyword(source, "deathtouch")
        ):
            permanent.metadata["received_deathtouch"] = True
        # The dealt-damage record (Sengir Vampire, Brine Hag) lives on this
        # same path and for the same reason as the two rules above: any damage
        # a permanent deals belongs in it, not only the combat step's. Only a
        # Permanent is recorded — a spell's source is the card as printed and
        # is not a creature that could be found on a battlefield later.
        if outcome.dealt > 0 and isinstance(source, Permanent):
            self._record_damage_source(permanent, source)
        if then is not None:
            then(outcome.dealt)
        return outcome.dealt

    def _apply_lifelink(self, source, dealt: int) -> None:
        """CR 702.15b for damage dealt outside the combat damage step.

        The seat is the source's controller *now*, falling back to the seat it
        entered under when it is no longer on a battlefield — a creature can
        deal damage on its way out (a dies-trigger ping, a sacrifice cost paid
        mid-resolution), and `controller_index_of` answers None for a permanent
        on no battlefield. `base_controller_index` is never rewritten, so it is
        the right answer rather than a guess.
        """
        gained = lifelink_life_gained(source, dealt)
        if gained <= 0:
            return
        seat = self.controller_index_of(source)
        if seat is None:
            seat = getattr(source, "base_controller_index", None)
        if seat is None or not (0 <= seat < len(self.players)):
            return
        self._gain_life(self.players[seat], gained, source_name="lifelink")

    def _consume_land_destruction_shield(self, perm: Permanent) -> bool:
        """Pyramids: "The next time target land would be destroyed this turn,
        remove all damage marked on it instead." Consumes the one-shot shield
        and reports True when the destruction was replaced."""
        if (
            perm.card.primary_type == "land"
            and perm.metadata.pop("land_destruction_shield_this_turn", None)
        ):
            perm.damage_marked = 0
            self.log.append(
                f"{perm.card.name}'s destruction was replaced: all damage marked on it was removed"
            )
            return True
        return False

    def _apply_opponent_damage_choice(
        self, pending: dict, target_seat: int, target_permanent_index: int | None
    ) -> None:
        """Deal a pending opponent-chosen damage packet (Cuombajj Witches) to the
        chosen player face (index None) or creature."""
        from ..handlers._common import apply_damage_to_creature

        amount = int(pending["amount"])
        source = pending.get("_source_permanent") or pending.get("card_name")
        card_name = pending["card_name"]
        victim_player = self.players[target_seat]
        if target_permanent_index is None:
            self._deal_damage_to_player(
                victim_player, amount, source=source,
                then=lambda dealt: self.log.append(
                    f"{card_name} dealt {dealt} damage to {victim_player.name} (opponent's choice)"
                ),
            )
            return
        if not (0 <= target_permanent_index < len(victim_player.battlefield)):
            self.log.append(f"{card_name}: chosen target is gone, no effect")
            return
        perm = victim_player.battlefield[target_permanent_index]
        if not perm.is_creature:
            self.log.append(f"{card_name}: '{perm.card.name}' is not a valid 'any target' target (115.4)")
            return
        apply_damage_to_creature(
            self, perm, amount, source,
            log_message=lambda dealt: f"{card_name} dealt {dealt} damage to {perm.card.name} (opponent's choice)",
        )

    def confirm_opponent_damage_choice(
        self, chooser_index: int, target_seat: int, target_permanent_index: int | None = None
    ) -> bool:
        """Resolve the pending opponent-chosen damage (Cuombajj Witches) with the
        chooser's pick. Returns False when no such choice is pending for them."""
        return self.resolve_pending_choice(
            "opponent_damage", chooser_index,
            target_seat=target_seat, target_permanent_index=target_permanent_index,
        )

    def _resolve_opponent_damage_choice(
        self, choice, target_seat: int, target_permanent_index: int | None
    ) -> bool:
        if not (0 <= target_seat < len(self.players)):
            return False
        self.discard_pending_choice(choice)
        self._apply_opponent_damage_choice(choice.data, target_seat, target_permanent_index)
        return True

    def _default_opponent_damage_choice(self, choice) -> None:
        """Deterministic chooser policy for AI/headless play: kill one of the
        activator's creatures if the damage is lethal to it (largest power
        first), otherwise hit the activator's face."""
        self.discard_pending_choice(choice)
        pending = choice.data
        chooser_index = choice.player_index
        amount = int(pending["amount"])
        target_seat = pending.get("caster_index")
        if not (isinstance(target_seat, int) and 0 <= target_seat < len(self.players)):
            target_seat = next(
                (i for i, p in enumerate(self.players) if i != chooser_index and not p.lost),
                None,
            )
        if target_seat is None:
            return
        victim = self.players[target_seat]
        best_index: int | None = None
        best_power = -1
        for idx, perm in enumerate(victim.battlefield):
            if not perm.is_creature:
                continue
            if perm.effective_toughness - perm.damage_marked <= amount and perm.effective_power > best_power:
                best_index = idx
                best_power = perm.effective_power
        self._apply_opponent_damage_choice(pending, target_seat, best_index)

    def _record_damage_source(self, victim: Permanent, source: Permanent) -> None:
        """Remember that *source* dealt damage to *victim* this turn — the
        record behind "a creature dealt damage by this creature this turn"
        (Sengir Vampire) and "all creatures that dealt damage to it this turn"
        (Brine Hag). References are cleared at cleanup.

        Fed from ``_mark_damage_on_permanent`` — the one path every
        creature-damage event runs through, combat or not — for the reason
        deathtouch and lifelink live there: recorded only at the combat step,
        a Prodigal Sorcerer ping was damage the record never saw. Deduped by
        identity, not equality: ``in`` compares ``Permanent`` by value, so a
        second copy of the same creature damaging the same victim was silently
        merged with the first (the look-alike bug class)."""
        sources = victim.metadata.setdefault("damaged_by_sources_this_turn", [])
        if not any(entry is source for entry in sources):
            sources.append(source)

    def _player_controls_text(self, player: PlayerState, phrase: str) -> bool:
        return any(
            phrase in perm.effective_card.oracle_text.lower() for perm in self.controlled_by(player)
        )

    def place_plus1_counters(self, permanent: Permanent, count: int = 1) -> int:
        """Put *count* +1/+1 counters on *permanent*, as a replaceable event.

        The counters are an **event**, not just a write: CR 614 lets an effect
        change how many arrive (Conclave Mentor's "that many plus one"), and
        CR 603 lets one trigger on their arrival (Wildwood Scourge). This is
        the one place that happens, and every counter-placing handler calls
        it.

        ``engine/pt.py``'s ``add_plus1_counters`` is the library operation
        underneath — it writes the two channels and knows nothing about the
        game — exactly as ``player.draw`` sits under
        :meth:`_draw_with_replacements`. Reaching for it directly is how a
        replacement gets skipped, which is why
        ``tests/engine/test_counter_placement.py`` bans it outside this seam.

        Returns how many counters actually arrived.
        """
        if count <= 0:
            return 0
        seat = self.controller_index_of(permanent)
        consumed, payload = apply_replacements(
            self,
            "plus1_counters",
            {
                "permanent": permanent,
                "count": count,
                # The affected player is the counters' recipient's controller,
                # which is who CR 616.1 asks when several effects contend.
                "player": self.players[seat] if seat is not None else None,
            },
        )
        # No interceptor *consumes* this event — a replacement that removed the
        # counters entirely would be a different card — so `consumed` staying
        # False is the normal path and a True is honoured rather than assumed
        # impossible.
        if consumed:
            return 0
        placed = max(0, int(payload.get("count", count)))
        if placed <= 0:
            return 0
        add_plus1_counters(permanent, placed)
        if seat is not None:
            emit(
                self, "counters_put_on_creature",
                subject=permanent, seat=seat, count=placed,
            )
        return placed

    def place_pt_counters(self, permanent: Permanent, kind: str, count: int = 1) -> int:
        """Put *count* CR 122.1a counters of *kind* on *permanent*; returns how
        many arrived.

        The general seam beside :meth:`place_plus1_counters`, which it hands
        the one kind that has an *event*. The CR 614 replacements the pool
        prints ("that many plus one", Conclave Mentor) and the trigger that
        watches for them (Wildwood Scourge) are written about +1/+1 counters
        by name, so putting a -0/-2 counter through that event would ask a
        replacement about a counter its card does not mention. The day a card
        prints either for another kind, the event moves here and the +1/+1
        path becomes a narrowing of it — which is why this is the seam every
        placement calls rather than a second one beside it.
        """
        if kind == "+1/+1":
            return self.place_plus1_counters(permanent, count)
        if count <= 0:
            return 0
        add_pt_counters(permanent, kind, count)
        return count

    def _draw_with_replacements(
        self,
        player: PlayerState,
        count: int,
        *,
        turn_based: bool = False,
        exclude_sources: tuple[int, ...] = (),
    ) -> int:
        """Draw ``count`` cards for *player*, letting an armed draw replacement
        take the first of them (CR 614) — Aladdin's Lamp, Ring of Ma'rûf — or
        change how many there are (Teferi's Ageless Insight).

        A replacement that needs the player to choose suspends the draw and
        reports 0 drawn; the cards arrive when the choice is answered, along
        with any draws queued behind it. Which replacements exist lives in
        engine/replacements.py.

        This is the *only* way an effect should draw. CR 121.2 makes a
        multi-card instruction that many individual draws, each replaceable on
        its own, so the draws queued behind a replaced one come back through
        here rather than being taken off the library — and a draw an effect
        *creates* (Lich turning a life gain into one, CR 616.2) is a draw like
        any other. `player.draw` is the library operation underneath; reaching
        for it directly is how a second armed replacement gets skipped.

        ``turn_based`` marks CR 504.1's draw-step draw. Only the draw step
        passes it, and it exists for the rider on every draw-doubler ever
        printed — "except the first one you draw in each of your draw steps".
        The engine cannot derive it: any later draw in the same step is also
        made by the active player during their draw step, and it is not the
        first one.

        ``exclude_sources`` is CR 614.5 — "a replacement effect gets only one
        opportunity to affect an event or any modified events resulting from
        that event". A replacement that *creates* a draw (Chains of
        Mephistopheles' "if the player discards a card this way, they draw a
        card") passes the ``permanent_id`` of the source that created it, so
        that source does not replace its own replacement into a loop. It is a
        set of ids rather than a boolean because a *second* copy of the same
        card is a different effect and does apply (CR 614.5 is about one
        effect, not one wording), and it is carried on the payload so the
        exclusion survives the restart CR 616.1e's prompt re-runs.
        """
        if count <= 0:
            return player.draw(count)
        consumed, payload = apply_replacements(
            self,
            "draw",
            {
                "player": player,
                "count": count,
                "drawn": 0,
                "turn_based": turn_based,
                "exclude_sources": tuple(exclude_sources),
            },
            # A draw can suspend: "the replacement took it, the cards arrive
            # when you answer" is already this method's contract, so CR 616.1e's
            # choice can be put to the player here. Re-running this call is what
            # the answer resumes, which is why the thunk is the call itself.
            restart=lambda: self._draw_with_replacements(
                player, count, turn_based=turn_based, exclude_sources=exclude_sources
            ),
        )
        if consumed:
            return int(payload["drawn"])
        # `payload["count"]`, not `count`: a replacement may have changed how
        # many draws this event is (Teferi's Ageless Insight) without consuming
        # it, exactly as `place_plus1_counters` reads back a raised counter
        # count. Reading the local instead is why a *modifying* draw
        # replacement could not be written at all — the interceptor would run,
        # the number would change, and the draw would take the old one.
        drawn = player.draw(max(0, int(payload.get("count", count))))
        self._divert_drawn_commanders(player)
        return drawn

    def _divert_drawn_commanders(self, player) -> None:
        """CR 903.9b over a draw: drawing a commander puts it into its owner's
        hand from their library, so its owner may put it into the command zone
        instead.

        Applied just after ``PlayerState.draw`` rather than inside it, which is
        the one place the two halves of a draw can be told apart: ``draw`` is
        the library operation (it must move the card to know a card was there
        at all), and this is the replacement over its destination. The card
        never becomes castable or discardable in between, since nothing gets
        priority between the two lines.
        """
        if not self.is_commander_game:
            return
        seat = self.players.index(player)
        for card in [c for c in player.hand if self.is_commander_card(seat, c)]:
            index = next((i for i, held in enumerate(player.hand) if held is card), None)
            if index is None:  # pragma: no cover - the list was just read
                continue
            player.hand.pop(index)
            if not self.commander_zone_change(seat, card, "hand"):  # pragma: no cover
                player.hand.insert(index, card)

    def _finish_lamp_draw(self, player_index: int, chosen_index: int, x: int) -> int:
        """Complete a lamp-replaced draw: the chosen card of the top ``x`` goes
        to hand, the rest go to the bottom of the library in a random order."""
        player = self.players[player_index]
        top = list(player.library[:x])
        chosen = top.pop(chosen_index)
        del player.library[:x]
        random.shuffle(top)
        player.library.extend(top)
        self.put_card_into_hand(player, chosen)
        # The replacement still ends in "then draw a card", so the chosen card is
        # the last card drawn this turn (Jandor's Ring's cost can discard it).
        player.cards_drawn_this_turn.append(chosen)
        self.log.append(
            f"{player.name} drew 1 card (Aladdin's Lamp) and put {len(top)} card(s) "
            "on the bottom of their library in a random order"
        )
        return 1

    def _outside_game_choices(self, player_index: int) -> list[int]:
        """Sideboard indices this player may bring into the game (CR 100.4).
        Ante cards are excluded unless the game is played for ante (CR 407.3);
        in a Commander game CR 903.11a's name and colour-identity bars apply
        on top (`outside_the_game_problem` is None outside one)."""
        player = self.players[player_index]
        return [
            i for i, card in enumerate(player.sideboard)
            if (self.playing_for_ante or not is_ante_card(card))
            and self.outside_the_game_problem(player_index, card) is None
        ]

    def _finish_outside_game_draw(self, player_index: int, chosen_index: int) -> None:
        """Move the chosen sideboard card into hand."""
        player = self.players[player_index]
        if not (0 <= chosen_index < len(player.sideboard)):
            return
        card = player.sideboard.pop(chosen_index)
        if self.put_card_into_hand(player, card):
            self.log.append(
                f"{player.name} put {card.name} into their hand from outside the game (Ring of Ma'rûf)"
            )

    # ------------------------------------------------------------------
    # Suspended replacement choices (engine/replacement_choices.py)
    # ------------------------------------------------------------------

    def resolve_replacement_choice(
        self, player_index: int, option_index: int, kind: str | None = None
    ) -> bool:
        """Answer the oldest replacement choice queued for *player_index*
        (optionally of one *kind*) with the chosen option.

        Returns False when there is no such choice or the option is out of
        range, so a stale or malformed client answer is rejected rather than
        applied to whatever happens to be queued.
        """
        entry = next(
            (
                (i, choice)
                for i, choice in enumerate(self.pending_replacement_choices)
                if choice.player_index == player_index
                and (kind is None or choice.kind == kind)
            ),
            None,
        )
        if entry is None:
            return False
        index, choice = entry
        if not (0 <= option_index < len(choice.options)):
            return False
        self.pending_replacement_choices.pop(index)
        resolve_choice(self, choice, option_index)
        return True

    def auto_resolve_pending_replacement_choices(self) -> None:
        """Take the default on every queued choice (safety net for a seat that
        stops being interactive, e.g. a human seat handed to the AI)."""
        while self.pending_replacement_choices:
            choice = self.pending_replacement_choices[0]
            self.resolve_replacement_choice(
                choice.player_index, choice.default_option, kind=choice.kind
            )

    # Compatibility views over the queue, in the shapes the web layer and its
    # tests already read. The state itself is generic; these only name the three
    # prompts it currently carries.

    @property
    def pending_lamp_draw(self) -> dict | None:
        choices = pending_choices_for(self, "lamp_draw")
        if not choices:
            return None
        choice = choices[0]
        return {
            "player_index": choice.player_index,
            "card_names": list(choice.options),
            "remaining_draws": choice.data.get("remaining_draws", 0),
        }

    @property
    def pending_outside_game_draw(self) -> dict | None:
        choices = pending_choices_for(self, "outside_game_draw")
        if not choices:
            return None
        choice = choices[0]
        return {
            "player_index": choice.player_index,
            "card_names": list(choice.options),
            "sideboard_indices": choice.data.get("sideboard_indices"),
            "remaining_draws": choice.data.get("remaining_draws", 0),
        }

    @property
    def pending_commander_zone_changes(self) -> list[dict]:
        """CR 903.9's outstanding offers, oldest first — one per commander
        waiting on its owner's "command zone or not?"."""
        return [
            {
                "player_index": choice.player_index,
                "card": choice.data["card"],
                "destination": choice.data["destination"],
                "rule": choice.data["rule"],
            }
            for choice in pending_choices_for(self, "commander_zone_change")
        ]

    @property
    def pending_leng_discards(self) -> list[dict]:
        return [
            {"player_index": choice.player_index, "card": choice.data["card"]}
            for choice in pending_choices_for(self, "leng_discard")
        ]

    def confirm_outside_game_draw(self, player_index: int, chosen_index: int) -> bool:
        """Resolve a pending Ring of Ma'rûf choice with the player's chosen card,
        then make any draws that were queued behind the replaced one."""
        return self.resolve_replacement_choice(
            player_index, chosen_index, kind="outside_game_draw"
        )

    def confirm_lamp_draw(self, player_index: int, chosen_index: int) -> bool:
        """Resolve a pending Aladdin's Lamp draw with the player's chosen card,
        then make any draws that were queued behind the replaced one."""
        return self.resolve_replacement_choice(player_index, chosen_index, kind="lamp_draw")

    def _discard_card(self, player: PlayerState, card) -> None:
        """Move a discarded card to the graveyard, or let a discard replacement
        take it instead (Library of Leng, CR 701.9c).

        Use for random/forced discards (combat damage, "discards X cards at
        random", cleanup) where the player can't pick the card but a
        replacement may still redirect it.
        """
        consumed, _ = apply_replacements(
            self, "discard", {"player": player, "card": card}
        )
        if not consumed:
            player.graveyard.append(card)

    def _gain_life(self, target: PlayerState, amount: int, source_name: str | None = None) -> None:
        """Apply a life gain, honoring 'If you would gain life, draw that many cards
        instead' replacement effects (e.g. Lich, CR 614), then announce it.

        The one seam every life gain passes through, so "Whenever you gain life"
        (Vito, Thorn of the Dusk Rose) is one ``emit`` here rather than a fire
        site per source — lifelink, a drain spell, an upkeep trigger and a
        planeswalker ultimate all arrive at this line. The event is emitted
        *after* the replacements and after the record, because CR 614 can change
        the number or take the gain away entirely: a life gain that was replaced
        never happened, and one whose amount was raised is that larger event.
        """
        if amount <= 0:
            return
        consumed, payload = apply_replacements(
            self, "life_gain",
            {"player": target, "amount": amount, "source_name": source_name},
        )
        if consumed:
            return
        amount = payload["amount"]
        source = f" from {source_name}" if source_name else ""
        before = target.life
        target.life += amount
        # After the replacements, and after any amount they changed: what "you
        # gained N life this turn" asks about is the life that actually
        # arrived, not the life the effect set out to give.
        target.life_gained_this_turn += amount
        self.log.append(f"{target.name} gained {amount} life{source} ({before} -> {target.life})")
        if amount > 0:
            # By identity, not `players.index`: PlayerState is a value-compared
            # dataclass, so two seats holding the same cards match each other —
            # the look-alike problem the battlefield reads already guard against.
            seat = next(i for i, p in enumerate(self.players) if p is target)
            emit(self, "you_gain_life", seat=seat, life_gained=amount)

    def _deal_damage_to_player(
        self, target: PlayerState, amount: int, source=None, *, then=None, restart=None,
        asks: bool = False,
    ) -> int:
        """Deal damage to a player and fire 'whenever you're dealt damage'
        triggers (e.g. Lich). ``source`` (a Permanent or spell CardDefinition)
        lets color-scoped prevention (Circle of Protection) match the source's
        color.

        A player with protection from the source's *name* (Runed Halo, CR
        702.16i) is dealt none of it — checked here, at the one path every
        non-combat player-damage event runs through, rather than as a shield,
        because protection is not prevention and produces no shield to consume.

        Returns the damage actually **dealt** (CR 120.4b), which is what a
        caller reporting "N damage" or gaining life equal to it wants. How much
        of that reduced the life total is a separate number (CR 120.4c) and does
        not leave this method — only Ali from Cairo makes the two differ.

        **Pass what you would do with that number as ``then``, do not read the
        return value.** A damage event can stop part-way to ask the affected
        player which of several effects applies first (CR 616.1e), and when it
        does, *nothing has happened*: no shield spent, no life lost, no trigger
        fired, and 0 comes back. The answer re-runs this call — which is why the
        consequences have to be inside it. A caller that logs "dealt {n}" or
        gains life equal to it from outside would report the suspension as a
        0-damage event and never correct itself.
        ``tests/engine/test_damage_continuations.py`` holds engine code to that.

        ``restart`` is what re-runs the event, and supplying it is what allows
        the question to be asked at all. ``asks=True`` builds the obvious one —
        "re-run exactly this call" — and is only honest from inside a resumable
        loop (``engine/resumption.py``), which is what records the work behind
        the event. Pass ``restart`` yourself when the re-run has to be wider
        than this call: the combat damage step does, because it applies the life
        loss and tallies lifelink from the same outcome.
        """
        # Protection from the source's *name* (Runed Halo, CR 702.16i): the
        # player is dealt none of it. Before the face-up flip and before any
        # shield, because protection is not prevention — nothing is consumed and
        # no replacement contends; the damage simply is not dealt.
        from ..named_protection import protected_from

        if amount > 0 and protected_from(self, self.players.index(target), source):
            self.log.append(
                f"{target.name} has protection from "
                f"{getattr(getattr(source, 'card', source), 'name', 'that source')}"
            )
            if then is not None:
                then(0)
            return 0
        # Illusionary Mask: a face-down creature that would deal damage (e.g.
        # unblocked combat damage to a player) is turned face up first.
        if amount > 0:
            self._turn_face_up(source)
        if asks and restart is None:
            # "Re-run exactly this call" — which is what the answer needs, since
            # `then` carries the consequences and the enclosing loop records the
            # work behind it. Only pass asks=True from inside a resumable loop
            # (engine/resumption.py); otherwise the work behind this event is
            # not recorded anywhere and would be lost.
            def restart():
                self._deal_damage_to_player(
                    target, amount, source, then=then, asks=True
                )

        outcome = deal_damage(
            self,
            {"recipient": target, "amount": amount, "source": source, "combat": False},
            restart=restart,
        )
        if outcome.suspended:
            return 0
        if outcome.dealt > 0:
            target.life -= outcome.result
            self._on_player_dealt_damage(target, outcome.dealt, source)
            self._record_noncombat_damage_to_opponent(target, outcome.dealt, source)
            self._apply_mirror_damage(target, outcome.dealt, source)
            # CR 702.15b. No combat guard here, unlike the creature seam: the
            # combat damage step deals to players directly rather than through
            # this method (it applies prevention where the event is recorded, so
            # routing back would double-prevent), and this call always passes
            # combat=False.
            self._apply_lifelink(source, outcome.dealt)
        if then is not None:
            then(outcome.dealt)
        return outcome.dealt

    def _record_noncombat_damage_to_opponent(
        self, target: PlayerState, dealt: int, source
    ) -> None:
        """The running total Chandra's Incinerator's cost reduction reads.

        Every damage event this method runs is noncombat by construction — the
        combat damage step reaches players by its own path, because it applies
        prevention where the event is recorded — so "noncombat" is a property of
        the fire site and not a flag anything has to remember to set. Kept here
        for that reason: this is the one site that knows the damage was
        noncombat *and* whose source it was, and a tally kept anywhere else
        would have to re-derive both.

        The *announcement* that used to sit beside it is gone. "Whenever a
        source you control deals noncombat damage to an opponent" is
        `damage_dealt` narrowed on both axes now, announced with every other
        damage event from `damage_events._announce` — and the seat this
        function derived by hand is the one `deal_damage` fills in for every
        event, from the same `damage_source_seat`.
        """
        seat = damage_source_seat(self, source)
        if seat is None or self.players[seat] is target:
            return
        self.players[seat].noncombat_damage_dealt_to_opponents_this_turn += dealt

    def _apply_mirror_damage(self, target: PlayerState, damage: int, source) -> None:
        """Eye for an Eye: the damage still happens, and its source's controller
        is dealt the same amount.

        The caster picks "a source of your choice", so only damage from a
        matching source mirrors; a generic charge (no source picked) mirrors the
        next event from any source. One entry per damage event, and entries are
        finite, so a mirrored mirror can't loop forever.

        Called from every path that reduces a player's life: _deal_damage_to_player
        for spells and abilities, and the combat damage step directly (combat
        damage applies prevention when the event is recorded, so it can't route
        back through _deal_damage_to_player without double-preventing)."""
        if damage <= 0:
            return
        matched_mirror = self._match_chosen_damage_source(target.mirror_damage_sources, source)
        if matched_mirror is None and target.mirror_damage_charges <= 0:
            return
        if matched_mirror is not None:
            target.mirror_damage_sources.remove(matched_mirror)
        else:
            target.mirror_damage_charges -= 1
        mirror_index = (
            self.controller_index_of(source)
            if isinstance(source, Permanent)
            else None
        )
        if mirror_index is None:
            # A spell (or unknown) source: fall back to the first living
            # opponent — its caster in every two-player game.
            target_index = self.players.index(target)
            mirror_index = next(
                (i for i, p in enumerate(self.players) if i != target_index and not p.lost),
                None,
            )
        if mirror_index is None:
            return
        victim = self.players[mirror_index]
        self._deal_damage_to_player(
            victim, damage, source=None,
            then=lambda dealt: self.log.append(
                f"Eye for an Eye dealt {dealt} damage to {victim.name} "
                f"(mirroring the damage dealt to {target.name})"
            ),
        )

    def _on_player_dealt_damage(self, target: PlayerState, damage: int, source=None) -> None:
        # Track total damage dealt to each player this turn (Simulacrum, etc.).
        if damage > 0:
            target.damage_taken_this_turn += damage
            # Reverse Polarity counts only what artifact sources dealt. Tracked
            # as it happens because the sources are gone by the time the spell
            # resolves — CR 603.10's last-known-information problem, avoided by
            # not needing to look back.
            source_perm = getattr(source, "card", source)
            type_line = getattr(source_perm, "type_line", "") or ""
            if "artifact" in str(type_line).lower():
                target.artifact_damage_taken_this_turn += damage
        # Living Artifact: "Whenever you're dealt damage, put that many vitality
        # counters on this Aura." Counters accumulate on the enchantment so its
        # upkeep ability can later trade them for life (and the UI can show them).
        if damage > 0:
            for perm in self.controlled_by(target):
                if "put that many vitality counters" in perm.effective_card.oracle_text.lower():
                    perm.metadata["vitality_counters"] = int(perm.metadata.get("vitality_counters", 0)) + damage
                    self.log.append(
                        f"{perm.card.name} got {damage} vitality counter(s) "
                        f"(now {perm.metadata['vitality_counters']})"
                    )
        if not self._player_controls_text(
            target, "whenever you're dealt damage, sacrifice that many nontoken permanents"
        ):
            return
        # CR 701.21a: the sacrificing player chooses which nontoken permanents to
        # give up (a human is prompted; AI/headless resolves inline). "If you can't,
        # you lose the game." Multiple damage events this step accumulate the count.
        self.arm_forced_sacrifice(
            self.players.index(target),
            damage,
            filter={"nontoken": True},
            reason="Lich",
            on_short={"kind": "lose"},
        )

    def _add_mana_from_text(self, controller: PlayerState, text: str, preferred_color: str | None = None) -> None:
        # Prefer lexing the oracle text for mana symbols
        try:
            tokens = lex_oracle_text(text)
        except Exception:
            tokens = ()

        mana_tokens = [t.value for t in tokens if t.kind == "mana"]
        if mana_tokens:
            for raw in mana_tokens:
                sym = raw.strip("{}")
                if sym in {"W", "U", "B", "R", "G", "C"}:
                    controller.mana_pool[sym] += 1
            return

        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if "one mana of any color" in normalized:
            selected_color = self._normalize_mana_color(preferred_color) or "G"
            controller.mana_pool[selected_color] += 1

    def _return_creature_from_graveyard(self, caster: PlayerState) -> bool:
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                self.put_card_into_hand(caster, caster.graveyard.pop(idx))
                return True
        return False

    def _reanimate_creature_to_battlefield(
        self,
        caster: PlayerState,
        target: PlayerState | None = None,
        target_permanent_index: int | None = None,
    ) -> bool:
        controller_index = self.players.index(caster)
        # "Return target creature card from your graveyard" (Resurrection): honor the
        # creature the caster chose (Rule 601.2c) instead of always grabbing the
        # first one. target is the graveyard's owner; for Resurrection that is the
        # caster, but a chosen index is respected for any reanimation source.
        source = target if target is not None else caster
        if (
            isinstance(target_permanent_index, int)
            and 0 <= target_permanent_index < len(source.graveyard)
            and source.graveyard[target_permanent_index].primary_type == "creature"
        ):
            revived = source.graveyard.pop(target_permanent_index)
            self._put_permanent_onto_battlefield(controller_index, Permanent(card=revived), None)
            return True
        # Fallback (AI / legacy callers with no explicit choice): first creature.
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                revived = caster.graveyard.pop(idx)
                self._put_permanent_onto_battlefield(controller_index, Permanent(card=revived), None)
                return True
        return False

    def _bounce_target_creature(
        self, target: PlayerState, target_permanent_index: int | None = None
    ) -> bool:
        # Respect the chosen target when one was declared; otherwise fall back to
        # the first creature so AI / legacy callers still resolve.
        chosen = pick_target_permanent(target, target_permanent_index)
        if chosen is None:
            return False
        # CR 400.3: the card returns to its owner's hand, not its controller's
        # (they differ when the creature was stolen, e.g. by Control Magic).
        owner_idx = self.owner_index_of(chosen)
        owner = self.players[owner_idx] if owner_idx is not None else target
        self.put_card_into_hand(owner, chosen.card)
        if owner_idx is not None:
            self.permanents_to_hand_this_turn[owner_idx] = (
                self.permanents_to_hand_this_turn.get(owner_idx, 0) + 1
            )
        # Identity: ``remove`` would bounce a look-alike instead of the chosen one.
        self.remove_from_battlefield(chosen)
        return True

    def _sacrifice_creature_for_mana(self, caster: PlayerState, chosen_index: int | None = None) -> Permanent | None:
        """Sacrifice one of *caster*'s creatures for a cost/effect, returning the
        sacrificed **Permanent** (not its card) so callers can still read the
        characteristics it had on the battlefield — CR 608.2h last-known
        information, which Diamond Valley's "equal to the sacrificed creature's
        toughness" depends on."""
        # The caster chooses which creature to sacrifice; honor an explicit
        # choice, otherwise sacrifice the first creature.
        chosen = pick_target_permanent(caster, chosen_index)
        if chosen is None:
            return None
        # CR 400.3 (the stolen creature's card goes to its *owner's* graveyard)
        # used to be resolved here, by hand; it is one of the six things
        # ``sacrifice_permanent`` does, and the only one this site remembered.
        return self.sacrifice_permanent(chosen)

    def _apply_color_override(
        self,
        target: PlayerState,
        symbol: str,
        target_permanent_index: int | None = None,
    ) -> bool:
        if not symbol:
            return False
        chosen = pick_target_permanent(target, target_permanent_index, predicate=lambda p: True)
        if chosen is None:
            return False
        chosen.metadata["color_override"] = symbol
        return True

    def _process_land_enters(self, land_controller_index: int) -> None:
        """Put "whenever a land enters the battlefield, deal 2 damage" triggers onto
        the stack; they resolve off the stack (CR 603.3)."""
        events = [
            make_trigger_event(
                controller_index, permanent, trig,
                instruction=OracleInstruction("deal_damage_to_player", None, {}),
                effect_kind="triggered_damage",
                ability_text=None,
                trigger_context={"victim_player_index": land_controller_index, "amount": 2},
            )
            for controller_index, permanent, trig in iter_triggered_abilities(
                self, condition_kinds={"land_enters"}
            )
        ]
        self._enqueue_triggered_batch(events)

    def _process_land_dies(self, land_controller_index: int) -> None:
        """Put land_dies triggered abilities (e.g. Dingus Egg) onto the stack when a
        land is put into a graveyard; they resolve off the stack (CR 603.3)."""
        events = [
            make_trigger_event(
                controller_index, permanent, trig,
                instruction=OracleInstruction("deal_damage_to_player", None, {}),
                effect_kind="triggered_damage",
                trigger_context={
                    "victim_player_index": land_controller_index,
                    "amount": int(trig.instruction.payload.get("amount", 2)),
                },
            )
            for controller_index, permanent, trig in iter_triggered_abilities(
                self, condition_kinds={"land_dies"}, first_match_only=False
            )
        ]
        self._enqueue_triggered_batch(events)

    def _land_play_allowances(self, player_index: int) -> list[tuple[Permanent, LandPlayAllowance]]:
        """Permanents granting *player_index* extra land plays, with what each grants.

        Derived from each permanent's own printed text
        (engine/land_play_allowance.py), not from its name. The single
        ``card.name == "Fastbond"`` count this replaced was consulted from four
        places, so a second printing of the template was wrong in four ways at
        once.
        """
        if not (0 <= player_index < len(self.players)):
            return []
        found = []
        for permanent in self.controlled_by(player_index):
            allowance = land_play_allowance_for(permanent.effective_card.oracle_text)
            if allowance is not None:
                found.append((permanent, allowance))
        return found

    def _may_play_another_land(self, player_index: int) -> bool:
        """Whether the seat may still play a land this turn (CR 305.2).

        One per turn, plus whatever the allowances on their battlefield add.
        Every land-drop gate — cast validation, the AI's land policy, the web
        layer's playable list — asks this one question, so they cannot disagree
        about what a card grants.
        """
        allowed = 1
        for _, allowance in self._land_play_allowances(player_index):
            if allowance.extra is None:
                return True
            allowed += allowance.extra
        return self.lands_played_this_turn.get(player_index, 0) < allowed
