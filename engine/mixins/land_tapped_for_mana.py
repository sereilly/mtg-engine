"""A land was tapped for mana (CR 106.12) - the one event, and what watches it.

``_land_tapped_for_mana`` is reached by all three roads to it: the player's
tap and a cost an effect collects (both through ``tap_land_for_mana``, in
``land_mana_taps.py``), and a land whose mana ability costs more than the
tap, which the activation path resolves inline
(``mixins/stack/activation.py``). It writes the seat's per-turn record
(Desolation), asks the CR 106.12b replacements over the production
(``land_mana_produced``), runs the production, and then - only if mana was
made (CR 106.12a) - adds an attached Aura's additional mana (Wild Growth) and
resolves the "whenever ... is tapped for mana" triggers, printed and delayed
(CR 603.7).

Those triggers resolve inline, never on the stack: the mana ones are
triggered mana abilities (CR 605.4a), and the rest share their moment
because the land is tapped part-way through paying a cost (CR 601.2g).
``_land_tap_trigger_fires`` is the printed narrowing, asked by the fire site
and by ``land_tap_mana_adders`` (the same walk with nothing performed, for
``engine/board_payment.py``); ``_resolve_tapped_land_trigger_step`` runs one
clause, over the kinds ``TAP_TRIGGER_KINDS`` names.
"""

from __future__ import annotations

from ..auras import AURA_ANY_COLOR_MANA, aura_additional_mana_now
from ..delayed_triggers import matching_delayed_triggers
from ..land_mana_swaps import (production_snapshot, source_wide_swap,
                               substitute_production)
from ..game_types import OracleExecutionContext
from ..replacements import apply_replacements
from ..trigger_utils import iter_triggered_abilities


#: Every instruction kind ``_resolve_tapped_land_trigger_step`` has an arm for.
#:
#: Beside the dispatch rather than in the test that checks it. The guard used to
#: keep its own list, which is the second-copy class SET_PLAYBOOK.md's promotion
#: step calls the most expensive kind of guard — this one went stale the moment
#: the site learned Storm Cauldron's return and Winter's Night's untap marker,
#: and then reported two working cards as undispatched at the promotion gate.
#: The arms read it as their own precondition, so a kind added to one and not
#: the other is inert rather than silently mis-run, and the card's own test says
#: so.
TAP_TRIGGER_KINDS = frozenset({
    "add_mana_for_tapped_land",   # Mana Flare, Gauntlet of Might
    "return_tapped_land_to_hand", # Storm Cauldron
    "skip_next_untap",            # Winter's Night
    "deal_damage",                # Manabarbs
    "tap_lands_sharing_produced_mana",  # Mana Web
    # "…**you may gain 1 life**." (Sanctimony.) An *optional* effect under this
    # condition, which every kind above it is not — and the first one whose
    # answer belongs to a player rather than to this site.
    #
    # It reaches the ordinary dispatcher rather than an arm of its own, and that
    # is the point: `may` arms a prompt on the generic pending-choice queue,
    # which is the machinery built for a decision owed part-way through
    # something. What this site cannot give a trigger is a *priority window*;
    # a queued question needs none, so the reason the docstring below gives for
    # refusing control flow ("no priority window to run its branches") is a
    # reason about `if_then`'s branches and not about an offer.
    #
    # Without it, Sanctimony parsed, lowered, was announced by this very loop
    # and then gained nothing at all — the exact shape
    # `tests/engine/test_trigger_dispatchers.py` cannot see, because the
    # condition *is* dispatched and it is the effect that falls off the end.
    "may",
    "target_gains_life",
    # "Whenever you tap a land for mana, **remove a +1/+1 counter from this
    # creature**." (Savage Firecat.) "…if it's not that player's turn,
    # **destroy that land**." (Price of Glory.) Two more effects that are not
    # mana abilities, run through the ordinary dispatcher like the two above
    # them, with the event's seat and the event's land stamped in the context.
    "remove_counter_from_self",
    "destroy_event_subject",
})


#: The kinds above that reach ``EFFECT_HANDLERS`` through the engine's own
#: dispatcher rather than through an arm written out at the fire site.
_TAP_TRIGGER_HANDLER_KINDS = frozenset({
    "may", "target_gains_life", "remove_counter_from_self",
    "destroy_event_subject",
})


def _tap_trigger_steps(instruction) -> tuple:
    """A tap-for-mana trigger's effect as the clauses that make it up.

    One sentence is one instruction; two sentences are a ``sequence`` whose
    steps are those instructions (Winter's Night). Flattened one level only,
    because that is the shape the compiler produces for a printed paragraph —
    a deeper nesting is a control-flow instruction (`may`, `if_then`) whose
    branches this inline site has no priority window to run, and the arms below
    report it rather than guessing.
    """
    if instruction.kind == "sequence":
        return tuple(instruction.payload.get("steps") or ())
    return (instruction,)


def _mana_made_since(player, before: dict) -> dict[str, int]:
    """What *player*'s pool gained since *before* (a
    ``land_mana_swaps.production_snapshot``), per symbol and summed across
    every bucket — the open pool and each CR 106.6 "spend this mana only…"
    bucket beside it, because restricted mana is still mana a land produced.

    The answer to two questions the tap-for-mana event asks of a production it
    did not perform itself: *did this make mana at all* (CR 106.12a) and
    *which type* (Mana Flare's "any type that land produced"). Insertion order
    is the pool's own symbol order, so "the first type it made" is stable.
    """
    made: dict[str, int] = {}
    buckets = [(None, player.mana_pool)]
    buckets.extend((getattr(player, "restricted_mana", None) or {}).items())
    for key, bucket in buckets:
        prior = before.get(key, {})
        for symbol, amount in bucket.items():
            gained = int(amount or 0) - int(prior.get(symbol, 0) or 0)
            if gained > 0:
                made[symbol] = made.get(symbol, 0) + gained
    return made


class LandTappedForManaMixin:
    def _land_tapped_for_mana(
        self, player_index: int, land, chosen_color: str | None, produce,
    ) -> bool:
        """**A land was tapped for mana** (CR 106.12) — the one event.

        "To 'tap [a permanent] for mana' is to activate a mana ability of that
        permanent that includes the {T} symbol in its activation cost." Three
        roads do that, and until Odyssey's wave 2 only the first told anybody:

        * the player's own tap (:meth:`tap_land_for_mana`);
        * **a cost an effect collects** — "counter target spell unless its
          controller pays {1}", an upkeep price, an attack toll. The payer
          gets no priority window, so the engine plans the payment and taps
          the lands itself, which is the player activating mana abilities
          while an effect asks for mana (CR 605.3a). It tapped them with
          ``become_tapped``: no mana was produced, no ability ran, and
          nothing here was announced. Each planned land is tapped through
          :meth:`tap_land_for_mana` now (``Game._pay_planned_cost``), so this
          road *is* the first one;
        * **a land whose mana ability costs more than the tap** — "{1}, {T}:
          Add {U}{B}" (Darkwater Catacombs), a sacrifice land, a depletion
          land — which :meth:`tap_land_for_mana` refuses by design
          (CR 602.2b) and the activation path resolves inline (CR 605.3b).
          That branch calls this method around the ability it runs.

        *produce* runs the land's own production and returns the symbol the
        seat asked it for; what it actually made is read off the pool, so
        "one mana of any type **that land produced**" (Mana Flare) is the
        type that came out. The land is already tapped: {T} is a cost, and
        every road pays it before it gets here.

        Returns whether mana was produced. CR 106.12a: an ability that
        triggers whenever a permanent is tapped for mana "triggers whenever
        such a mana ability resolves **and produces mana**" — a land whose
        ability made none this time (a Tolarian Academy beside no artifact)
        was tapped, and nothing watching for mana saw any.
        """
        player = self.players[player_index]
        # What the land is named, which for a copy is what it copies (CR
        # 707.2): Sculpting Steel copying an artifact land is tapped as that
        # land, as the board shows it.
        land_name = land.effective_card.name

        # "…each player who **tapped a land for mana this turn**" (Desolation).
        # The seat's own per-turn record, written at the one tap-for-mana seam
        # — the same site that announces `land_tapped_for_mana` below, so what
        # a trigger fires on and what the record remembers cannot disagree.
        # A fact about the seat rather than about the land, for
        # `attacked_this_turn`'s reason: the land may untap, leave, or be
        # tapped again for something that is not mana, and the player still
        # tapped one for mana this turn.
        player.tapped_land_for_mana_this_turn = True
        # "Until end of turn, if you tap a land you control for mana, it
        # produces {U} instead of any other type." (Deep Water.) "If a land is
        # tapped for mana, it produces {B} instead…" (Infernal Darkness.)
        # CR 106.12b makes these replacement effects over the mana production
        # event, so they are asked through the CR 614 registry — one event kind
        # with its own contention set, and nothing consumed: mana is still
        # produced and the land is still tapped for mana (CR 106.12a).
        #
        # Read here, and applied to whatever the production below actually puts
        # in the pool, because this is the one place the two production paths
        # meet: a land with a compiled mana ability runs it and writes into the
        # pool itself, where a basic falls through to the `produced_mana`
        # summary. Quarum Trench Gnomes' per-permanent record is one of these
        # substitutions too (``land_mana_swaps.permanent_substitutions_on``):
        # read off the summary, it was applied ahead of every other one and on
        # no land whose compiled ability made the white mana. Snapshotting the
        # pool is what makes "instead of any **other** type" mean what it says:
        # whatever came out, this is what it is instead.
        #
        # No `restart` thunk: a land is tapped for mana part-way through paying
        # a cost (CR 601.2g), before the spell it pays for is on the stack, so
        # there is no moment at which a CR 616.1e prompt could be answered and
        # nothing to re-run it against. The choice is made **before the tap**
        # instead: the symbol the seat asked for picks the order the
        # substitutions apply in (``land_mana_swaps.ordered_substitutions``) —
        # Infernal Darkness beside a Deep Water record is {B} or {U}, as asked.
        _, mana_event = apply_replacements(
            self, "land_mana_produced",
            {
                "land": land, "player": player, "substitutions": [],
                # The colour the seat asked this land for. "…it produces one
                # mana of **a color of your choice** instead…" (Harvest Mage)
                # is chosen per tap, and this request is that choice — the
                # same channel a dual land's "{R} or {G}" is answered through.
                "requested": chosen_color,
            },
        )
        # Each applied substitution, in the order CR 616.1 applied them.
        substitutions = tuple(mana_event.get("substitutions") or ())
        # Every bucket, not only the open pool: mana a "spend this mana only…"
        # clause narrowed is written into its own bucket (CR 106.6), and a
        # snapshot of the pool alone let it escape every swap — Mishra's
        # Workshop under Contamination made {C}{C}{C}, not one {B}.
        pool_before = production_snapshot(player)
        # The tap first, then what it made: the tap is the mana ability's cost
        # (CR 106.12, 602.2b's payment) and its production comes after it, so
        # the log says so in that order. "Temple of the False God produced
        # {C}{C}" was written by the ability as it ran, before this line, and
        # read as mana that came before the tap (SCG Phase 5).
        self.log.append(f"{player.name} tapped {land_name} for mana")
        mana_symbol = produce()

        shown = None
        for substitution in substitutions:
            # One effect after another, each on what the one before it left
            # (CR 616.1f). Whatever the land already put in under the swapped
            # symbol itself counts toward the replaced amount: a Swamp under
            # Contamination made its own {B}, and "…instead of any other type
            # **and amount**" says the whole production is one {B} rather than
            # one more — where Infernal Darkness leaves the count alone, so an
            # Ancient Tomb makes {B}{B}. Each bucket keeps its own mana, so a
            # restricted production stays restricted (CR 106.6).
            moved = substitute_production(
                player, pool_before, substitution.produced,
                1 if substitution.replaces_amount else None,
                colors_only=substitution.colors_only,
                replaces=substitution.replaces,
            )
            if moved:
                shown = substitution.produced
            # "One mana of any type **that land produced**" is what came out,
            # not what would have: a Mana Flare over a Ritual of Subdual board
            # matches the colourless the land really made. Except where a
            # colours-only swap moved nothing — Hall of Gemstone over a land
            # that made {C} changed nothing, and the {C} is what it made — or
            # a record of one symbol did (Quarum Trench Gnomes over a Tundra's
            # {U}).
            if moved or not (substitution.colors_only or substitution.replaces is not None):
                mana_symbol = substitution.produced
        if shown is not None:
            self.log.append(f"{land_name} produced {{{shown}}} instead")


        # What the land really made, across every bucket (CR 106.6: restricted
        # mana is still mana). Nothing made, nothing to announce — CR 106.12a.
        made = _mana_made_since(player, pool_before)
        if not made:
            return False
        # "One mana of any type **that land produced**" (Mana Flare) is a type
        # that came out. The seat's request stands when the land made it — a
        # dual asked for {R} — and otherwise the answer is read off the pool:
        # an Ancient Tomb asked for the route's default {G} made {C}{C}, and
        # the adder used to hand back the {G} it was asked for.
        if mana_symbol not in made:
            asked = (chosen_color or "").strip().upper()
            mana_symbol = asked if asked in made else next(iter(made))

        # Kudzu's "when enchanted land becomes tapped" used to be dispatched
        # here, from inside the *mana* path — so it was the one attached trigger
        # that could not see a land tapped any other way (CR 701.26a). It is an
        # ordinary compiled trigger now, announced by `become_tapped` in
        # `tap_land_for_mana` like City of Brass's and Psychic Venom's, and
        # nothing about it belongs in this method.
        attached_aura = land.metadata.get("attached_aura")
        if attached_aura is not None:
            # Wild Growth: "Whenever enchanted land is tapped for mana, its controller
            # adds an additional {G}." The "for mana" phrasing isn't compiled as a
            # generic trigger, so the mana is read from the Aura's text here.
            #
            # The pattern is `auras.aura_additional_mana_now`'s, not a regex of
            # this method's own. It used to be written out here alone, so the
            # support gate had no way to ask whether this line was implemented
            # and claimed every attached trigger with a wildcard instead — which
            # is how an Aura whose trigger nothing reads reported supported. One
            # pattern, two readers: this dispatcher and `attached_trigger_claim`.
            #
            # A *run* of symbols, because Overgrowth prints "{G}{G}" where Wild
            # Growth prints "{G}" — the count is data, and adding one symbol for
            # a card that says two is the quiet direction of wrong.
            for extra in aura_additional_mana_now(self, attached_aura):
                if extra == AURA_ANY_COLOR_MANA:
                    # "…adds an additional **one mana of any color**" (Fertile
                    # Ground) rather than a printed pip. CR 106.6 leaves the
                    # colour to the controller, and CR 605.4a gives a triggered
                    # mana ability no window to be asked in — this is running
                    # inline, inside the cost payment that tapped the land, so
                    # there is no priority for a prompt. The seat's answer is
                    # already in hand: `chosen_color` is the colour this very
                    # call asked the land for, which is the same player making
                    # the same kind of choice at the same moment. It is
                    # normalized rather than trusted, because it arrives off the
                    # wire.
                    #
                    # **A land asked for {C} has named no colour for the Aura.**
                    # "Any color" is one of the five (CR 105.1), never
                    # colourless, so `{C}` is the land's own answer and says
                    # nothing here - the same case as a call that named no
                    # colour at all, and it takes the same default. Handed to
                    # the normalizer it raised: a Mishra's Factory or an
                    # Archaeological Dig under a Fertile Ground, tapped for the
                    # `{C}` the AI's plan counted, ended the game with a
                    # ValueError. Anything else that is not a colour is still
                    # refused.
                    asked = (chosen_color or "").strip().upper()
                    extra = (
                        None if asked == "C"
                        else self._normalize_mana_color(chosen_color)
                    ) or "G"
                # "…spells and abilities **you control** that would add colored
                # mana instead add that much white mana." (False Dawn.) This
                # triggered mana ability is the *Aura's* controller's, and it is
                # the one production here that is written inline rather than
                # through an instruction — so the seat's source-wide swap is
                # asked for it by name, where every other ability meets it at
                # the dispatch seam (``Game._execute_oracle_instruction``).
                aura_seat = self.controller_index_of(attached_aura)
                wide = (
                    source_wide_swap(self.players[aura_seat])
                    if aura_seat is not None else None
                )
                if wide is not None and (extra != "C" or not wide.colors_only):
                    extra = wide.symbol()
                player.mana_pool[extra] = player.mana_pool.get(extra, 0) + 1
                self.log.append(f"{attached_aura.card.name}: {player.name} added an additional {{{extra}}}")

        # "Whenever a player taps a land for mana" triggers (Manabarbs,
        # Mana Flare, Gauntlet of Might). The last two were name-keyed
        # MANA_PRODUCTION_MODIFIERS hooks fired further up this method; their
        # triggers now compile like any other, so they arrive here.
        #
        # The mana ones are triggered *mana* abilities (CR 605.1b: no target,
        # triggered by an activated mana ability, and they could add mana), so
        # CR 605.4a says they never use the stack — inline is what the rules
        # require, not a shortcut.
        #
        # Manabarbs' damage is not a mana ability and by the rules would use the
        # stack; it resolves inline because a land is tapped for mana
        # mid-cost-payment, before the spell being paid for is even on the
        # stack, so enqueuing here would order the trigger *under* that spell.
        # Stack routing would require deferring these across the
        # cost-payment/cast boundary.
        for _idx, perm, trig in iter_triggered_abilities(
            self, condition_kinds={"land_tapped_for_mana"}, first_match_only=False
        ):
            if not self._land_tap_trigger_fires(trig, perm, player_index, land):
                continue
            # "…that player adds one mana of any type that land produced.
            # **That land doesn't untap during its controller's next untap
            # step.**" (Winter's Night.) One trigger whose effect is two
            # sentences, so the compiler hands it a `sequence` — and this site
            # dispatched on `trig.instruction.kind` alone, which made every
            # clause of such a trigger unreachable. Flattened here rather than
            # by teaching each arm about sequences: what the arms answer is
            # "which effect is this", and how many sentences the ability was
            # printed in is not part of that question.
            # "…**if it's not that player's turn**, destroy that land." (Price
            # of Glory.) CR 603.4's intervening-if. This site triggers and
            # resolves in one motion, so the rule's two checks are one check:
            # false, the ability does not trigger and nothing below runs.
            gate = (trig.instruction.payload or {}).get("intervening_if")
            if gate is not None:
                from ..handlers.control_flow import evaluate_condition

                watcher = self.controller_index_of(perm)
                if watcher is None or not evaluate_condition(
                    self,
                    OracleExecutionContext(
                        caster=self.players[watcher], target=player,
                        card=perm.card, source_permanent=perm,
                        trigger_context={"event_subject_player": player_index},
                    ),
                    gate,
                ):
                    continue
            for step in _tap_trigger_steps(trig.instruction):
                self._resolve_tapped_land_trigger_step(
                    step, player_index, player, land, mana_symbol, perm
                )
            continue
        # The same ability created for a turn instead of printed on a permanent
        # (CR 603.7): "Until end of turn, … whenever a player taps a Mountain
        # for mana, that player adds an additional {R}." (Chaos Moon's odd
        # branch.) It belongs to no permanent, so the scan above cannot see it —
        # it waits on `game.delayed_triggers` and is announced here.
        #
        # **Resolved inline, not enqueued**, and that is CR 605.4a rather than a
        # convenience: a triggered mana ability does not use the stack, and the
        # rule's own example is this clause. `fire_delayed_triggers` always
        # enqueues, so this site asks `matching_delayed_triggers` for the
        # entries and performs them where the permanent-borne ones above are
        # performed — the same instruction, the same dispatcher, the same
        # cost-payment moment.
        for entry in matching_delayed_triggers(
            self, "land_tapped_for_mana", subject=land
        ):
            # The grammar admits no other effect under this event (it refuses
            # the sentence), so anything else here is an entry built by hand;
            # skipping it is the safe reading, because this site has no way to
            # give a non-mana effect the priority window the stack would.
            if entry.instruction.kind != "add_mana_for_tapped_land":
                continue
            self._add_triggered_land_mana(
                entry.instruction, player_index, land, mana_symbol,
                # CR 603.7d: the source is the object whose ability created the
                # delayed one — the enchantment, not the land being tapped. It
                # may have left by now, in which case the log falls back to the
                # name the entry froze when it was armed.
                self.permanent_by_id(entry.source_permanent_id),
                source_name=entry.source_name,
            )

        return True

    def _land_tap_trigger_fires(self, trig, perm, player_index: int, land) -> bool:
        """Whether *perm*'s "whenever … is tapped for mana" ability *trig*
        triggers for *player_index* tapping *land* — the printed narrowing,
        which rides the condition's payload.

        One predicate for the tap seam, which resolves the trigger, and for
        ``land_tap_mana_adders``, which says beforehand what the mana ones
        will add: a preview with a reading of its own would count a
        Gauntlet of Might's {R} over a Forest.
        """
        # "Whenever a **Mountain** is tapped for mana" — the narrowing rides
        # the condition's payload, so the land type is data rather than a
        # per-card hook. has_type, so a land made a Mountain by a layer-4
        # effect counts.
        subtype = trig.condition.payload.get("tapped_land_subtype")
        if subtype and not land.has_type(str(subtype)):
            return False
        # "Whenever a player taps a **snow** land for mana" (Winter's
        # Night). A supertype (CR 205.4a), not a type, so it is asked of
        # `has_supertype` — the accessor the type test above would answer
        # False for on every land, which is a trigger that never fires
        # rather than one that fires too often. Layer 4 either way: a land
        # an effect *made* snow counts and one that stopped being snow does
        # not.
        supertype = trig.condition.payload.get("tapped_land_supertype")
        if supertype and not land.has_supertype(str(supertype)):
            return False
        # "Whenever **a land an opponent controls** is tapped for mana"
        # (Mana Web). A whole noun phrase where the two rows above carry a
        # single word, so it is tested through the one matcher every other
        # narrowed subject in this engine goes through — and the seat it
        # carries is relative to *this ability's* controller (CR 109.5),
        # never to whoever tapped the land. Dropped, the trigger would fire
        # on its own controller's lands too, which on Mana Web is a card
        # that taps out the player who cast it.
        # "Whenever **an opponent** taps a Mountain for mana" (Sanctimony).
        # CR 109.5's seat, asked of whoever tapped the land against the seat
        # that controls the *watching permanent* — read through the control
        # seam, so a Sanctimony somebody has taken control of watches
        # **their** opponents from the moment they take it (CR 613 layer 2).
        #
        # This is the narrowing the two rows above are not: they describe
        # the *land*, and this describes the player who tapped it. Dropped,
        # the enchantment would gain its controller life for their own
        # Mountains — a trigger firing on a strictly larger set, which reads
        # to every census in this repo as an implemented card.
        if trig.condition.payload.get("tapped_by_opponent") is not None:
            watcher = self.controller_index_of(perm)
            if watcher is None or player_index == watcher:
                return False
        # "Whenever **you** tap a land for mana" (Savage Firecat). The
        # same seat test the other way round: only the watching
        # permanent's own controller's taps count.
        if trig.condition.payload.get("tapped_by_you") is not None:
            watcher = self.controller_index_of(perm)
            if watcher is None or player_index != watcher:
                return False
        described = trig.condition.payload.get("tapped_land_filter")
        if described:
            from ..subject_filters import subject_matches

            watcher = self.controller_index_of(perm)
            if not self.is_on_battlefield(land):
                # **A land its own cost sacrificed** ("{T}, Sacrifice this
                # land: Add {B}{B}", Ebon Stronghold). It was tapped for
                # mana and the ability has now resolved (CR 106.12a), but
                # the land is a card in a graveyard, which CR 109.4 gives
                # no controller — so "a land **an opponent controls**"
                # asked of the control seam answers no, and Mana Web
                # slept through every sacrifice land. Whose it was is the
                # seat that tapped it; the rest of the phrase is asked of
                # the object as it last was.
                described = dict(described)
                whose = described.pop("controller", None)
                if whose == "opponent" and (
                    watcher is None or watcher == player_index
                ):
                    return False
                if whose == "you" and watcher != player_index:
                    return False
                if whose not in (None, "opponent", "you"):
                    return False
            if not subject_matches(
                self, land, described, observer=watcher, source=perm,
            ):
                return False
        return True

    def land_tap_mana_adders(self, player_index: int, land) -> list:
        """The ``add_mana_for_tapped_land`` instructions that will resolve
        when *player_index* taps *land* for mana — Mana Flare's "one
        additional mana of any type that land produced", Gauntlet of
        Might's "an additional {R}", a Chaos Moon's turn-long one.

        Triggered mana abilities (CR 605.1b), so they resolve inside the
        tap (CR 605.4a) and what they add is mana the tap makes. The seam
        below performs them; this is the same walk with nothing performed,
        for the reader that has to know before anything is tapped
        (``engine/board_payment.py``).
        """
        found = []
        for _idx, perm, trig in iter_triggered_abilities(
            self, condition_kinds={"land_tapped_for_mana"}, first_match_only=False
        ):
            if not self._land_tap_trigger_fires(trig, perm, player_index, land):
                continue
            found.extend(
                step for step in _tap_trigger_steps(trig.instruction)
                if step.kind == "add_mana_for_tapped_land"
            )
        found.extend(
            entry.instruction
            for entry in matching_delayed_triggers(
                self, "land_tapped_for_mana", subject=land
            )
            if entry.instruction.kind == "add_mana_for_tapped_land"
        )
        return found

    def _resolve_tapped_land_trigger_step(
        self, instruction, player_index: int, player, land, mana_symbol, perm
    ) -> None:
        """One clause of a ``land_tapped_for_mana`` trigger, resolved inline.

        Inline rather than on the stack for Manabarbs' reason rather than
        CR 605.4a's, everywhere but the mana: none of these is a mana ability
        and by the rules they would use the stack, but the land is tapped
        part-way through paying a cost (CR 601.2g) and enqueuing here would
        order the trigger *under* the spell being paid for.

        **Every kind is named.** The damage arm used to be this loop's ``else``:
        any instruction kind it did not recognize was read for an ``amount`` and
        dealt as damage, defaulting to 1 when the payload had none — so a draw
        under this condition dealt a point of damage on a card reporting itself
        supported. A kind nobody has taught this site is skipped with a line in
        the log, which is the safe reading: this resolution cannot give a
        non-mana effect the priority window the stack would, and doing *nothing*
        visible beats doing something the card never said.
        """
        kind = instruction.kind
        if kind not in TAP_TRIGGER_KINDS:
            self.log.append(
                f"{perm.card.name}: nothing here resolves "
                f"{kind!r} inside a cost payment"
            )
            return
        # "Whenever an opponent taps a Mountain for mana, **you may gain 1
        # life**." (Sanctimony.) Run through the engine's own dispatcher, with
        # the ability's controller as the caster (CR 109.5) — never the seat
        # that tapped the land, which on this card is the opponent whose
        # Mountain it was.
        #
        # The tapping seat is frozen into the trigger's context under the key
        # every "that player" reader already asks for, because this site is the
        # fire site and holds it: an effect printed under this condition that
        # names the event's player has one place to read it, and it is here.
        if kind in _TAP_TRIGGER_HANDLER_KINDS:
            watcher = self.controller_index_of(perm)
            if watcher is None:
                self.log.append(
                    f"{perm.card.name}: its controller has left, so nothing is offered"
                )
                return
            self._execute_oracle_instruction(
                instruction,
                OracleExecutionContext(
                    caster=self.players[watcher],
                    target=player,
                    card=perm.card,
                    source_permanent=perm,
                    trigger_context={
                        "event_subject_player": player_index,
                        "event_subject_controller": player_index,
                        # The land the event was about, by id (CR 400.7) —
                        # what "destroy **that land**" reads (Price of Glory).
                        "event_subject_permanent_id": land.permanent_id,
                    },
                ),
            )
            return
        if kind == "add_mana_for_tapped_land":
            self._add_triggered_land_mana(
                instruction, player_index, land, mana_symbol, perm
            )
            return
        # "Whenever a land is tapped for mana, return it to its owner's hand."
        # (Storm Cauldron.) The mana has already been added, which is what the
        # rules say happens: the mana ability resolved (CR 605.3b) and the land
        # leaving afterwards takes nothing back.
        if kind == "return_tapped_land_to_hand":
            self._return_tapped_land_to_hand(land, perm)
            return
        # "…tap all lands that player controls that could produce any type of
        # mana that land could produce." (Mana Web.) The sweep whose set is
        # named by a comparison against the land this event was about — which
        # is why it is resolved here and by no ``@effect_handler``: this site
        # is the only one holding both lands at once.
        if kind == "tap_lands_sharing_produced_mana":
            self._tap_lands_sharing_produced_mana(
                instruction, player_index, land, perm
            )
            return
        # "**That land** doesn't untap during its controller's next untap
        # step." (Winter's Night.) CR 502.3's restriction on the land the event
        # was about — which only this site knows, so the marker is written here
        # through the same function the ordinary handler writes it with rather
        # than through a second copy of the merge rule.
        if kind == "skip_next_untap":
            if instruction.payload.get("subject") != "tapped_land":
                self.log.append(
                    f"{perm.card.name}: nothing here resolves an untap "
                    "restriction that does not name the tapped land"
                )
                return
            from ..handlers.tapping import mark_skip_next_untap

            mark_skip_next_untap(
                self, (land,),
                steps=max(1, int(instruction.payload.get("untap_steps") or 1)),
                # "…its controller's next untap step" names no seat, which the
                # untap step reads as "whichever controller's step reaches it".
                # The seated spelling would be "your", and no card prints it
                # under this condition.
                seat=None,
            )
            return
        # The compiled payload names its victim ``event_subject_player`` —
        # `land_tapped_for_mana` is in `_EVENT_SUBJECT_PLAYERS` on the strength
        # of this site — and the seat the event is about is ``player``, the one
        # tapping. This inline resolution *is* the fire site, still holding that
        # seat, so it executes the instruction against the seat it froze rather
        # than reading it back out of a context it never built.
        amount = int(instruction.payload.get("amount", 1))
        # Asks CR 616.1e's question (``asks``): the damaged seat is the one
        # tapping, and a person tapping a land is at the table to answer. What
        # carries on before the answer — the rest of the cost payment, the
        # spell it pays for going on the stack — is what by the rules happens
        # before this trigger resolves anyway (it is not a mana ability and
        # would use the stack, CR 605.4a); a resolution that tapped the land to
        # pay an offer (CR 605.3a) waits behind the question, because the
        # offer's steps are a resumable loop (``engine/resumption.py``).
        self._deal_damage_to_player(
            player, amount, source=perm, asks=True,
            then=lambda damage: self.log.append(
                f"{perm.effective_card.name} triggered: {player.name} took {damage} damage"
            ),
        )

    def _tap_lands_sharing_produced_mana(
        self, instruction, tapping_seat: int, land, source
    ) -> None:
        """Mana Web: "tap all lands that player controls that **could
        produce** any type of mana that land could produce."

        **CR 106.7's sets** — "which types of mana … that land could produce
        using any of its mana abilities, not merely the one the player just
        used" (its ruling, 2008-04-01) — read off the fixpoint
        (``mana_could_produce.lands_could_produce``), which takes a land whose
        types were replaced (Evil Presence), whose production was swapped
        (Quarum Trench Gnomes; a substitution in any order) or which is a copy
        of another land by what it could make now. **Types, not colours** (CR
        106.1b): a land that taps for {C} answers "any type of mana". They came
        off each land's ``effective_produced_mana``, so an opponent's
        Reflecting Pool — five colours by its summary — shared a type with
        every land its controller had, whatever those lands made.

        The land that was tapped is in the set it describes, and is skipped
        rather than tapped again — it is already tapped, so nothing changes
        either way, and skipping keeps the log honest about what this ability
        did.

        The seat is the one that tapped the land, which is what the payload's
        ``controller: that_player`` names and what the lowering refuses any
        other value of.
        """
        from ..mana_could_produce import (lands_could_produce,
                                          types_that_land_could_produce)

        could = lands_could_produce(self)
        produced = set(types_that_land_could_produce(
            self, land, seat=tapping_seat, could=could,
        ))
        if not produced:
            return
        described = {
            key: value for key, value in instruction.payload.items()
            if key != "controller"
        }
        from ..subject_filters import subject_matches

        tapped: list[str] = []
        for candidate in self.controlled_by(self.players[tapping_seat]):
            if candidate is land or candidate.tapped:
                continue
            if not subject_matches(
                self, candidate, described,
                observer=tapping_seat, source=source,
            ):
                continue
            if not produced & could.get(candidate.permanent_id, frozenset()):
                continue
            self.become_tapped(candidate)
            tapped.append(candidate.card.name)
        if tapped:
            self.log.append(
                f"{source.card.name} tapped {', '.join(tapped)}"
            )

    def _return_tapped_land_to_hand(self, land, source) -> None:
        """Storm Cauldron: the land that was just tapped for mana goes home.

        Guarded on the land still being on the battlefield, because two copies
        of this card are two triggers over one event: the second one finds a
        permanent that has already left, and bouncing it again would put a
        second copy of the card into its owner's hand out of nowhere.

        Through the two seams rather than a list rebuild:
        ``remove_from_battlefield`` is the one leave-the-battlefield transition,
        and ``put_card_into_hand`` is CR 903.9b's fire site as well as this one.
        """
        if not self.is_on_battlefield(land):
            return
        owner_index = self.owner_index_of(land)
        if owner_index is None:
            return
        owner = self.players[owner_index]
        self.remove_from_battlefield(land)
        self.put_card_into_hand(owner, land.card, from_battlefield=land)
        self.log.append(
            f"{land.card.name} was returned to {owner.name}'s hand "
            f"({source.card.name})"
        )

    def _add_triggered_land_mana(
        self,
        instruction,
        tapping_player_index: int,
        land,
        produced_symbol: str,
        source,
        *,
        source_name: str | None = None,
    ) -> None:
        """Resolve an ``add_mana_for_tapped_land`` instruction (Mana Flare,
        Gauntlet of Might).

        ``recipient`` names the clause's own subject. "That player" (the player
        who tapped the land) and "its controller" (the land's controller) are
        the same seat here, because a player may only tap lands they control —
        but they are resolved separately rather than assumed equal, so a future
        card that separates them does not silently pay the wrong player.

        **``optional`` is recorded and taken.** "…its controller **may** add an
        additional {U}" (Snowfall) is an offer, and CR 605.4a gives it no
        window in which to be answered: a triggered mana ability resolves
        without using the stack, here, inside the cost payment that tapped the
        land, before the spell being paid for is even announced. Nothing is
        lost by taking it in this engine — there is no mana burn (CR 500.5
        empties the pool at every step boundary and CR 106.4 makes that a loss
        with no penalty), and Snowfall's mana is restricted to cumulative
        upkeep costs, so unspent mana costs its controller nothing. A seat that
        could be asked would be asked here.
        """
        recipient = str(instruction.payload.get("recipient", "that_player"))
        if recipient == "land_controller":
            seat = self.controller_index_of(land)
            if seat is None:
                seat = tapping_player_index
        elif recipient == "source_controller":
            # "Whenever you tap a land for mana, **add** one mana of any type
            # that land produced." (Mirari's Wake.) The imperative's subject is
            # the watching permanent's controller (CR 109.5), read through the
            # control seam. With no permanent to ask there is no "you", and
            # nothing is added rather than paying whoever tapped.
            seat = (
                self.controller_index_of(source) if source is not None else None
            )
            if seat is None:
                self.log.append(
                    f"{source_name or 'a triggered mana ability'}: no controller "
                    "to add the mana for"
                )
                return
        else:
            seat = tapping_player_index
        player = self.players[seat]

        # "**If that Island is snow**, its controller may add an additional
        # {U}{U} **instead**." (Snowfall.) The alternative *replaces* the base
        # production, so it is chosen here rather than added to it, and the
        # supertype is asked of `has_supertype` — computed through the layers,
        # so an Arcum's Weathervane that thawed the Island stops the upgrade.
        pips = tuple(instruction.payload.get("pips", ()))
        alt_supertype = instruction.payload.get("alt_supertype")
        if alt_supertype and land.has_supertype(str(alt_supertype)):
            pips = tuple(instruction.payload.get("alt_pips", ()))
        # "Spend this mana only to pay cumulative upkeep costs." The bucket is
        # `engine/restricted_mana.py`'s, the same one an activated mana ability
        # writes to, so the three payment paths already ask what it may pay for.
        spend_only = instruction.payload.get("spend_only")
        bucket = (
            player.restricted_mana.setdefault(str(spend_only), {})
            if spend_only else player.mana_pool
        )

        added: list[str] = []
        for symbol, count in pips:  # "an additional {R}"
            bucket[symbol] = bucket.get(symbol, 0) + int(count)
            added.append(f"{{{symbol}}}" * int(count))
        # "One mana of any type that land produced" — the type is whatever the
        # land just made, which is why it cannot be written as pips.
        produced = int(instruction.payload.get("of_type_produced", 0))
        if produced:
            player.mana_pool[produced_symbol] = (
                player.mana_pool.get(produced_symbol, 0) + produced
            )
            added.append(f"{{{produced_symbol}}}" * produced)
        if added:
            extra = " an additional" if instruction.payload.get("additional") else ""
            # A delayed ability's source may have left the battlefield since it
            # was created (CR 603.7d freezes the object, not its zone), so the
            # name the entry froze is what the log falls back to.
            name = source.card.name if source is not None else (
                source_name or "a delayed ability"
            )
            self.log.append(
                f"{name}: {player.name} added{extra} {''.join(added)}"
            )
