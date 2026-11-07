"""Sacrifices a player chooses, and the keeps that decide them.

"Choose N and sacrifice the rest" (Cataclysm, Limited Resources): a keep is an
assignment of permanents to printed slots, so the most a card allows is a
maximum matching and every seat's answer is applied together once the last one
is in. Balance's removals; a sacrifice priced by an aggregate rather than a
count ("…with total power N or greater"); and the forced sacrifice of the player's
choice that every "sacrifice a <noun>" effect goes through, with what it
records for the sentences behind it.
"""

from __future__ import annotations

from ....pending_choices import ChoiceSpec, PendingChoice
from ....oracle_types import (SACRIFICED_CARDS_BY_SEAT, SACRIFICED_COUNT,
                              KEEP_FATES, RETURN_CHOSEN_TO_HAND)
from ....subject_filters import subject_matches


#: Balance's rounds, in the order the card and its ruling give them: lands,
#: then cards in hand, then creatures — each counted as it starts.
BALANCE_ROUNDS = ("lands", "hand", "creatures")

_BALANCE_ROUND_WORDS = {
    "lands": "which lands to keep",
    "hand": "which cards to keep",
    "creatures": "which creatures to keep",
}


def _record_sacrificed_card(record, player_index: int, perm) -> None:
    """Write one given-up card into a resolution's scratchpad, twice over.

    ``sacrificed_cards`` is the flat list Gargantuan Gorilla's "if you
    sacrifice a snow Forest **this way**" has read since it landed — one payer,
    asking about its own answer. :data:`SACRIFICED_CARDS_BY_SEAT` is the same
    event keyed by who gave it up, which is the only thing that can answer
    Desolation's "each player who sacrificed a Plains this way": the flat list
    says a Plains went and not whose it was, so a sentence reading it would
    damage every seat the moment any one of them lost one.

    One function because the sacrifice has **two** write sites — the inline
    resolution a non-interactive seat takes and the prompt an interactive one
    answers — and a record written at one of them is a card that behaves
    differently depending on who was playing it.
    """
    if record is None:
        return
    card = perm.card
    # "Sacrifice a creature. Rupture deals damage equal to **that creature's
    # power** …" The permanent's computed P/T, read *before* it leaves (the
    # caller records ahead of the sacrifice): a moment later it is a card in a
    # graveyard with no computed characteristics at all (CR 613.1), so this is
    # CR 608.2h's last-known information. The keys the destroy step writes for
    # the identical back-reference, so one reader answers both verbs; the
    # lowering admits the reading only behind a step that gives up exactly one
    # object (``_records._PRODUCES_FOR_ONE_OBJECT``).
    record["its_power"] = max(0, int(perm.effective_power))
    record["its_toughness"] = max(0, int(perm.effective_toughness))
    record.setdefault("sacrificed_cards", []).append(card)
    record.setdefault(SACRIFICED_CARDS_BY_SEAT, {}).setdefault(
        player_index, []
    ).append(card)
    # …and the *number*, which is what a bare "that much" reads (Last-Ditch
    # Effort). Kept in step with the list here rather than measured at the
    # reader, for the reason :data:`SACRIFICED_COUNT` gives — and written at
    # this one function because that is what makes the interactive and the
    # inline path record the same thing.
    record[SACRIFICED_COUNT] = len(record["sacrificed_cards"])


class SacrificeChoicesMixin:
    # -- A sacrifice priced by an aggregate rather than by a count -----------

    def aggregate_sacrifice_candidates(self, seat: int, payload: dict) -> list:
        """The permanents *seat* controls that the printed noun phrase names.

        Through ``subject_matches``, the one predicate the picker, the
        takeability gate and the answer's re-check all ask — three readings of
        "which creatures may be given up" is three chances to offer one the
        resolution then refuses.
        """
        from ....subject_filters import subject_matches

        described = dict(payload.get("filter") or {})
        source = payload.get("_source")
        return [
            perm for perm in self.controlled_by(seat)
            if subject_matches(self, perm, described, observer=seat, source=source)
            and not (payload.get("exclude_self") and perm is source)
        ]

    def aggregate_sacrifice_total(self, permanents, characteristic: str) -> int:
        """What a chosen set totals, through CR 613's layers.

        ``effective_power`` rather than the printed number, so a pumped creature
        counts for what it is now — the same accessor every other reader of a
        creature's power in this engine goes through.
        """
        return sum(
            int(
                (perm.effective_power if characteristic == "power"
                 else perm.effective_toughness) or 0
            )
            for perm in permanents
        )

    def arm_aggregate_sacrifice(self, player_index: int, payload: dict, context) -> None:
        """Queue "sacrifice any number of <noun> with total <X> N or greater".

        The whole payload travels rather than the candidate list, for
        ``arm_choose_cards_in_hand``'s reason: it is the *rule* the candidates
        came from, and re-running it is what keeps the list offered and the list
        an answer is checked against from being two lists.
        """
        self.arm_pending_choice(
            "aggregate_sacrifice", player_index,
            card_name=context.card.name,
            characteristic=str(payload.get("characteristic") or "power"),
            at_least=int(payload.get("at_least", 0)),
            _payload=dict(payload),
            _context=context,
        )

    def confirm_aggregate_sacrifice(self, player_index: int, permanent_ids) -> bool:
        return self.resolve_pending_choice(
            "aggregate_sacrifice", player_index, permanent_ids=permanent_ids
        )

    def _resolve_aggregate_sacrifice(self, choice: PendingChoice, permanent_ids) -> bool:
        """Sacrifice exactly the set named, once it clears the printed floor.

        Validated whole before anything is sacrificed, the shape every
        list-shaped picker here takes: one bad id rejects the answer and leaves
        the prompt queued, so a malformed request cannot sacrifice half a
        selection. **The floor is the whole of the price** — an answer under it
        is not a cheaper payment, it is no payment at all, so it is refused
        rather than applied.
        """
        payload = dict(choice.data.get("_payload") or {})
        live = self.aggregate_sacrifice_candidates(choice.player_index, payload)
        ids = [pid for pid in (permanent_ids or []) if isinstance(pid, int)]
        if len(ids) != len(permanent_ids or []) or len(set(ids)) != len(ids):
            return False
        chosen = []
        for pid in ids:
            perm = self.permanent_by_id(pid)
            if perm is None or not any(perm is candidate for candidate in live):
                return False
            chosen.append(perm)
        characteristic = str(choice.data.get("characteristic") or "power")
        if self.aggregate_sacrifice_total(chosen, characteristic) < int(
            choice.data.get("at_least", 0)
        ):
            return False
        self.discard_pending_choice(choice)
        # "Sacrifice any number of …" is one action, so one event: each
        # sacrifice looks back at the rest (CR 603.10a, ``leaving_together``).
        with self.leaving_together():
            for perm in chosen:
                self.sacrifice_permanent(perm)
        self.log.append(
            f"{choice.data.get('card_name', 'An effect')}: "
            + (", ".join(perm.card.name for perm in chosen) or "nothing")
            + " sacrificed"
        )
        return True

    def _default_aggregate_sacrifice(self, choice: PendingChoice) -> None:
        """The stated policy: the **fewest** permanents that clear the floor,
        taking the largest first.

        A toll rather than a gift — "take gifts, pay tolls, make no trades" —
        and the cheapest way to pay a toll counted in power is to spend as few
        bodies as possible. Ties break by battlefield order, which is
        seed-deterministic; a seat that should value the creatures themselves
        needs a weight in ``engine/ai_valuation.py``, not a branch here.

        **The ability's own source is a candidate** unless the sentence printed
        "another": nothing in CR 701.21a excludes it, and Phyrexian Dreadnought
        really can be sacrificed to its own trigger. So the largest-first rule
        usually pays with the source — which is the *same board state* as
        declining, and therefore the "make no trades" answer rather than an
        accident of the ordering.
        """
        payload = dict(choice.data.get("_payload") or {})
        characteristic = str(choice.data.get("characteristic") or "power")
        wanted = int(choice.data.get("at_least", 0))
        live = self.aggregate_sacrifice_candidates(choice.player_index, payload)
        ordered = sorted(
            live,
            key=lambda perm: -int(
                (perm.effective_power if characteristic == "power"
                 else perm.effective_toughness) or 0
            ),
        )
        taken, total = [], 0
        for perm in ordered:
            if total >= wanted:
                break
            taken.append(perm)
            total = self.aggregate_sacrifice_total(taken, characteristic)
        if total < wanted or not self._resolve_aggregate_sacrifice(
            choice, [perm.permanent_id for perm in taken]
        ):
            # Nothing the seat controls can cover the price. The offer should
            # never have been made — ``_action_is_takeable`` asks the same
            # question first — so this is the defensive half, and it declines
            # rather than sacrificing a set that does not pay.
            self.discard_pending_choice(choice)

    # -- Keep a described set, sacrifice the rest ----------------------------
    #
    # "Each player chooses from among the permanents they control an artifact, a
    # creature, an enchantment, and a land, then sacrifices the rest."
    # (Cataclysm.) "...chooses five lands they control and sacrifices the rest."
    # (Limited Resources.) One prompt per seat over that seat's own board, whose
    # *answer* is what the sacrifice takes the complement of - which is why the
    # sacrificing lives in the resolver rather than in a step behind it: "the
    # rest" is not a set anything can name until the keeps are known.
    #
    # Not ``arm_forced_sacrifice`` with a count, and that is the whole reason
    # this is its own kind. A count works while the keeps are one noun (Natural
    # Balance's five lands is "sacrifice held minus five lands"), and it stops
    # working the moment two slots can want the same permanent: a player whose
    # only permanents are two artifact creatures keeps *both* - one as the
    # artifact and one as the creature - where "sacrifice all but one artifact"
    # and "sacrifice all but one creature" would take one each and leave
    # nothing. So the keeps are an assignment, and the *most* the card allows is
    # the size of a **maximum matching** between the permanents and the slots.
    #
    # The most, not the number. The printed slots are separate choices, and
    # nothing in the sentence says each must be answered with a different
    # permanent: "If you control a permanent with more than one type, you can
    # choose that same permanent for more than one of the choices if you want
    # to" (Cataclysm's ruling), "a dual land could be chosen as two of your
    # land types" (Planar Overlay's), "you can choose it for either or for
    # both" (Global Ruin's). So a legal answer is any set in which every chosen
    # permanent answers a slot of its own **and** every printed slot the seat
    # can answer is answered — and the largest such set is the matching, while
    # the smallest is a cover. Which end a seat wants depends on which half of
    # the partition moves, so the *default* reads the fate; the validation does
    # not.

    def keep_choice_candidates(self, player_index: int, pool: dict) -> list:
        """The seat's own permanents the pool phrase describes.

        Its own battlefield and no other, and that is CR 701.21a rather than a
        convenience: a player cannot sacrifice a permanent they do not control,
        so a pool reaching another board would offer keeps whose complement
        could not be taken.
        """
        return [
            perm for perm in self.controlled_by(player_index)
            if subject_matches(self, perm, pool or {})
        ]

    @staticmethod
    def _keep_slot_filters(slots) -> list[dict]:
        """The printed slots expanded to one filter per keep.

        "Five lands" is one printed slot and five keeps; the matching below
        works over keeps, because what it answers is which *permanent* fills
        which, and a count is not a thing a permanent can be assigned to.
        """
        expanded: list[dict] = []
        for slot in slots or ():
            described = dict(slot.get("filter") or {})
            expanded.extend([described] * max(0, int(slot.get("count", 0))))
        return expanded

    def _match_keeps(
        self, candidates: list, slot_filters: list[dict], matches=None,
    ) -> dict:
        """Assign as many of *candidates* to distinct slots as possible.

        Kuhn's augmenting-path matching, for ``mana_payment.plan_payment``'s
        stated reason one module over: a greedy pass under-reports, and CR 609.3
        makes the answer "as much as possible" rather than "as much as the first
        pass happened to find". A player controlling an artifact creature and a
        plain artifact keeps both - the plain one as the artifact, the creature
        one as the creature - where a greedy walk that spent the artifact slot
        on the artifact creature would report one keep and sacrifice the other.

        Returns ``{slot index: permanent}``; its *size* is how many the card
        lets that seat keep, which is what the answer below is checked against.

        *matches* is ``(candidate, slot filter) -> bool`` for a caller whose
        candidates are not permanents — the cards of a hand (Noxious Vapors,
        ``match_hand_slots``), which no read of the battlefield can describe.
        Absent, a candidate is a permanent and the question is the one
        ``subject_matches`` answers.
        """
        taken: dict[int, object] = {}
        if matches is None:
            def matches(perm, described):
                return subject_matches(self, perm, described)

        def assign(perm, seen: set[int]) -> bool:
            for index, described in enumerate(slot_filters):
                if index in seen or not matches(perm, described):
                    continue
                seen.add(index)
                if index not in taken or assign(taken[index], seen):
                    taken[index] = perm
                    return True
            return False

        for perm in candidates:
            assign(perm, set())
        return taken

    def keep_slot_needs(self, live: list, slots) -> list[tuple[dict, int]]:
        """Each printed slot with how many of *live* must be chosen for it.

        The printed count, or every permanent that fits when the seat holds
        fewer (CR 609.3: as much as possible) — so zero for a slot the seat
        cannot answer at all. Per **printed** slot rather than per keep:
        "five lands" is one choice of five different lands, where "an artifact,
        a creature" is two choices that one artifact creature may answer both
        of.
        """
        needs: list[tuple[dict, int]] = []
        for slot in slots or ():
            described = dict(slot.get("filter") or {})
            held = sum(1 for perm in live if subject_matches(self, perm, described))
            needs.append((described, min(max(0, int(slot.get("count", 0))), held)))
        return needs

    def keep_slots_answered_by(self, perm, slots) -> list[int]:
        """Which printed slots *perm* may be chosen for, by position.

        More than one for a dual land or an artifact creature, which is the
        whole of what the prompt has to show a player: this Tropical Island is
        a Forest **and** an Island, and may be named as either or as both.
        """
        return [
            index for index, slot in enumerate(slots or ())
            if subject_matches(self, perm, dict(slot.get("filter") or {}))
        ]

    def keeps_answer_every_slot(self, live: list, kept: list, slots) -> bool:
        """Whether *kept* leaves no printed slot short of what the seat holds.

        The half of a legal answer the matching cannot ask. A seat holding a
        Forest must choose a land for Forest; which land — and whether it is
        also the Island — is the player's.
        """
        return all(
            sum(1 for perm in kept if subject_matches(self, perm, described)) >= need
            for described, need in self.keep_slot_needs(live, slots)
        )

    def fewest_keeps(self, live: list, slots) -> list:
        """The smallest legal answer, the first in board order among equals.

        A minimum cover of the printed slots by the seat's permanents, found by
        size: the slots are a printed handful (five basic land types, four card
        types), and a permanent beyond the first few sharing one *signature* —
        the set of slots it answers — can never be in a smallest answer, so the
        search is over a board's worth of distinct signatures rather than its
        permanents. Each candidate set is held to both halves of the
        validation, so what this returns is an answer the resolver accepts.
        """
        from itertools import combinations

        needs = self.keep_slot_needs(live, slots)
        slot_filters = self._keep_slot_filters(slots)
        by_signature: dict[frozenset, int] = {}
        candidates: list = []
        for perm in live:
            signature = frozenset(
                index for index, (described, need) in enumerate(needs)
                if need and subject_matches(self, perm, described)
            )
            if not signature:
                continue
            most = max(needs[index][1] for index in signature)
            if by_signature.get(signature, 0) >= most:
                continue
            by_signature[signature] = by_signature.get(signature, 0) + 1
            candidates.append(perm)
        floor = max((need for _described, need in needs), default=0)
        for size in range(floor, len(candidates) + 1):
            for picked in combinations(candidates, size):
                chosen = list(picked)
                if not self.keeps_answer_every_slot(live, chosen, slots):
                    continue
                if len(self._match_keeps(chosen, slot_filters)) == len(chosen):
                    return chosen
        return []

    def arm_keep_permanents(
        self, player_index: int, *, pool: dict, slots: list, reason: str,
        fate: str | None = None, batch: dict | None = None,
    ) -> None:
        """Ask *player_index* which of their permanents to keep, then take the
        rest (Cataclysm, Limited Resources).

        A seat with nothing in the pool is not prompted and nothing is logged as
        happening to them: an empty pool has an empty complement, so there is no
        decision and no sacrifice. CR 101.3 rather than a shortcut.

        *fate* is which half of the choice moves (``KEEP_FATES``). None is the
        sentence this prompt was built for — the chosen stay and the rest are
        sacrificed — and is not written into the prompt at all, so every prompt
        armed before a second fate existed is unchanged. Under
        ``RETURN_CHOSEN_TO_HAND`` (Planar Overlay) the chosen are what moves,
        so a seat none of whose permanents fills any slot has nothing to choose
        and nothing to return, and is not asked either.

        *batch* is one resolution's set of these prompts — "**each player**
        chooses …" — see :meth:`new_keep_batch`. With one, an answer is *held*
        and nothing moves until the last of them is in.
        """
        candidates = self.keep_choice_candidates(player_index, pool)
        if not candidates:
            return
        described = [
            {"count": int(s.get("count", 0)), "filter": dict(s.get("filter") or {})}
            for s in (slots or ())
        ]
        extra: dict = {}
        if batch is not None:
            extra["_batch"] = batch
        if fate is not None:
            if fate not in KEEP_FATES:
                raise ValueError(f"no keep prompt performs {fate!r}")
            if not self._match_keeps(candidates, self._keep_slot_filters(described)):
                return
            extra["fate"] = fate
        self.arm_pending_choice(
            "keep_permanents", player_index,
            pool=dict(pool or {}),
            slots=described,
            reason=reason,
            **extra,
        )

    def confirm_keep_permanents(self, player_index: int, permanent_ids: list) -> bool:
        """*permanent_ids* names the permanents to **keep**, by stable id."""
        return self.resolve_pending_choice(
            "keep_permanents", player_index, permanent_ids=permanent_ids
        )

    def _resolve_keep_permanents(
        self, choice: PendingChoice, permanent_ids: list
    ) -> bool:
        """Validated whole before anything is sacrificed.

        Three things are checked and the third is the one a client cannot be
        trusted with: the ids name permanents still in the pool, each can be
        given a slot of its own, and **no printed slot the seat can answer is
        left unanswered**. CR 608.2d lets a player choose only what is legal
        and CR 609.3 makes the effect do as much as it can, so a seat holding a
        creature chooses a creature — a prompt that accepted a list with none
        would let a seat skip a choice the card makes it take.

        What is *not* checked is that the list is as long as the board allows.
        One permanent may answer several slots — the three cards' rulings say
        so in as many words (the section comment above quotes them) — so an
        artifact creature named alone answers Cataclysm's artifact and its
        creature, and a Tropical Island named alone is Planar Overlay's Forest
        and its Island. A shorter list is a legal answer wherever the chosen
        permanents cover every slot; it used to be refused, which for Planar
        Overlay made a player return a land the card let them keep.
        """
        ids = [pid for pid in (permanent_ids or []) if isinstance(pid, int)]
        if len(ids) != len(permanent_ids or []) or len(set(ids)) != len(ids):
            return False
        pool = choice.data.get("pool") or {}
        slot_filters = self._keep_slot_filters(choice.data.get("slots"))
        live = self.keep_choice_candidates(choice.player_index, pool)
        kept = []
        for pid in ids:
            perm = self.permanent_by_id(pid)
            if perm is None or not any(perm is candidate for candidate in live):
                return False
            kept.append(perm)
        if len(self._match_keeps(kept, slot_filters)) != len(kept):
            # Not *assignable*: two keeps wanting the same single slot ("an
            # artifact, a creature" answered with two plain artifacts) is a
            # pair the card never offered, and so is a third land for two
            # types. Every chosen permanent is the choice for some slot.
            return False
        if not self.keeps_answer_every_slot(
            live, kept, choice.data.get("slots")
        ):
            return False
        # Which half of the partition moves is the sentence's, carried on the
        # prompt. Everything above is the same question either way — who may
        # be chosen, for which slots, and that no slot goes unanswered — so
        # the two fates share one validation and cannot disagree about whether
        # a dual land may stand for one type or for two.
        batch = choice.data.get("_batch")
        self.discard_pending_choice(choice)
        if batch is None:
            self._apply_keeps([(choice, kept)])
            return True
        # "**Each player** chooses …, then sacrifices the rest." The answer is
        # held: nothing moves until the last seat's is in — see
        # :meth:`new_keep_batch`. The choice itself is public the moment it is
        # made (the next player chooses knowing it), so it is said now.
        batch["answers"].append((choice, kept))
        self.log.append(
            f"{self.players[choice.player_index].name} chose "
            + (", ".join(perm.card.name for perm in kept) if kept else "nothing")
            + f" ({choice.data.get('reason', 'Effect')})"
        )
        self.finish_keep_batch(batch)
        return True

    @staticmethod
    def new_keep_batch() -> dict:
        """One resolution's set of ``keep_permanents`` prompts, for a sentence
        that asks **each player** (Cataclysm, Global Ruin, Planar Overlay).

        Cataclysm's ruling (2004-10-04): "The current player makes their
        choices before the other player. After both players make choices, **all
        the sacrifices are done simultaneously**." Each prompt used to perform
        its own seat's half as it was answered, so the first seat's permanents
        were gone while the second was still choosing — and that is visible:
        an Aura or an anthem the first seat gave up had already stopped
        applying to what the second chose among, and a permanent watching
        things leave (Dingus Egg) saw only its own controller's.

        So the answers are collected here and applied by
        :meth:`finish_keep_batch` after the last one — ``engine/piles.py``'s
        rule, "nothing moves until the last answer", for the same reason.
        """
        return {"answers": [], "armed": False, "applied": False}

    def finish_keep_batch(self, batch: dict) -> None:
        """Apply every held answer of *batch*, once none of its prompts is
        still owed. Safe to call at any time: it does nothing until the handler
        has armed every seat (a non-interactive seat answers *as* it is armed,
        with seats still to come) and nothing twice.

        Whether a prompt is still owed is read off the queue rather than
        counted, so a prompt that left the queue unanswered — its default
        refused, its seat gone — cannot strand the answers that were given.
        """
        if not batch.get("armed") or batch.get("applied"):
            return
        if any(
            owed.kind == "keep_permanents" and owed.data.get("_batch") is batch
            for owed in self.pending_choices
        ):
            return
        batch["applied"] = True
        self._apply_keeps(batch["answers"])

    def _apply_keeps(self, answers: list) -> None:
        """Perform every ``(choice, kept)`` answer **together**.

        Every seat's half is worked out before any permanent moves — the rule
        ``_resolve_balance`` states beside this one, across seats as well as
        within one: a sacrifice can trigger something, and end something, that
        changes what another permanent is. Then every sacrifice is one event
        (:meth:`sacrifice_permanents`), then the returns, then the log lines in
        the order the seats answered.
        """
        plans: list[tuple[PendingChoice, list, list | None]] = []
        doomed: list = []
        for choice, kept in answers:
            if choice.data.get("fate") == RETURN_CHOSEN_TO_HAND:
                plans.append((choice, kept, None))
                continue
            live = self.keep_choice_candidates(
                choice.player_index, choice.data.get("pool") or {}
            )
            rest = [
                perm for perm in live
                if not any(perm is keeper for keeper in kept)
            ]
            plans.append((choice, kept, rest))
            doomed.extend(rest)
        # Every seat's half of the one sentence is one event (CR 603.10a,
        # ``leaving_together``): the sacrifices, and "return those lands" for
        # every seat at once.
        with self.entering_together(), self.leaving_together():
            self.sacrifice_permanents(doomed)
            for choice, kept, rest in plans:
                if rest is None:
                    self._return_the_chosen(choice, kept)
                else:
                    self._log_the_rest_sacrificed(choice, kept, rest)

    def _return_the_chosen(self, choice: PendingChoice, chosen: list) -> None:
        """What was chosen goes to its owner's hand; the rest stays.

        "Each player chooses a land they control of each basic land type.
        Return those lands to their owners' hands." (Planar Overlay.) The
        mirror of the sacrifice half of :meth:`_apply_keeps`: the same
        partition, with the other half moving. Through
        ``return_permanent_to_owners_hand`` — the one spelling of that move —
        so each land goes to its **owner's** hand (CR 400.3) whoever chose it,
        a token ceases to exist, and the per-turn ledger is kept.

        Every permanent was resolved by the validation above before any of
        them leaves, which is that method's rule and for its reason.
        """
        from ....handlers._common import return_permanent_to_owners_hand

        player = self.players[choice.player_index]
        reason = choice.data.get("reason", "Effect")
        with self.entering_together(), self.leaving_together():
            for perm in chosen:
                return_permanent_to_owners_hand(self, perm, fallback_owner=player)
        where = "its owner's hand" if len(chosen) == 1 else "their owners' hands"
        self.log.append(
            f"{player.name} returned "
            + (", ".join(perm.card.name for perm in chosen) if chosen else "nothing")
            + f" to {where} ({reason})"
        )

    def _log_the_rest_sacrificed(
        self, choice: PendingChoice, kept: list, doomed: list
    ) -> None:
        """One seat's line of a keep: what it kept and how much it gave up.

        The sacrifices themselves are :meth:`_apply_keeps`' — every seat's in
        one event — so this only says what happened.
        """
        player = self.players[choice.player_index]
        reason = choice.data.get("reason", "Effect")
        self.log.append(
            f"{player.name} kept "
            + (", ".join(perm.card.name for perm in kept) if kept else "nothing")
            + f" and sacrificed {len(doomed)} permanent(s) ({reason})"
        )

    def _default_keep_permanents(self, choice: PendingChoice) -> None:
        """The stated policy: **the end of the legal range that leaves the
        seat the most permanents, in board order.**

        The card does offer a choice about *how many* — one permanent may
        answer several slots — and which end is the seat's best play is the
        fate's. Where the chosen stay and the rest are sacrificed (Cataclysm,
        Global Ruin, Limited Resources) that is the **maximum** keep: the
        matching, not a greedy walk. Where the chosen are what leaves (Planar
        Overlay) it is the **fewest** permanents that answer every slot — a
        Tropical Island for Forest and Island, and the Forest stays.

        Board order rather than a valuation, which is every other permanent
        prompt's rule here and for its reason - seed-determinism is what AI and
        headless play need, and a seat that should keep its best permanents
        wants a weight in ``engine/ai_valuation.py`` rather than a branch here.
        """
        pool = choice.data.get("pool") or {}
        live = self.keep_choice_candidates(choice.player_index, pool)
        slot_filters = self._keep_slot_filters(choice.data.get("slots"))
        if choice.data.get("fate") == RETURN_CHOSEN_TO_HAND:
            picks = self.fewest_keeps(live, choice.data.get("slots"))
        else:
            picks = list(self._match_keeps(live, slot_filters).values())
        ordered = [perm for perm in live if any(perm is pick for pick in picks)]
        chosen = [
            pid for pid in (self.permanent_id_of(perm) for perm in ordered)
            if pid is not None
        ]
        if not self._resolve_keep_permanents(choice, chosen):
            self.discard_pending_choice(choice)
            # A default that could not be given is still the last answer
            # some batch was waiting on.
            if choice.data.get("_batch") is not None:
                self.finish_keep_batch(choice.data["_batch"])

    # -- Balance -------------------------------------------------------------
    #
    # "Each player chooses a number of lands they control equal to the number
    # of lands controlled by the player who controls the fewest, then
    # sacrifices the rest. Players discard cards and sacrifice creatures the
    # same way."
    #
    # **Three rounds, each counted as it starts.** The card's ruling
    # (2016-06-08): "First the player whose turn it is chooses which lands (if
    # any) to keep, then each other player in turn order does the same. ... All
    # of the unchosen lands are then sacrificed simultaneously. Then the
    # process is repeated for cards in hand ... Lastly, the process is repeated
    # for creatures" — and "Each type of object is counted during the
    # corresponding part of the process ... a land creature sacrificed to the
    # first part of the spell would not be counted when determining how many
    # creatures are on the battlefield for the last part."
    #
    # It was one prompt per seat with all three counts taken up front, so a
    # Mishra's Factory sacrificed as a land was still owed as a creature, and a
    # seat whose creatures the *other* seat's land choice had evened up was
    # still made to sacrifice one. Now each round is a batch of ``balance``
    # prompts — one per seat that owes, asked in turn order from the active
    # player, the same prompt with the other two counts at zero — and nothing
    # moves until the round's last answer is in (the keep batch's rule above,
    # for the same reason). Then the next round is counted on the board that
    # one left.
    #
    # What each round counts is :meth:`balance_candidates`: layer 4's answer
    # (CR 613.1d), so a land animated into a creature is a land in the first
    # round and a creature in the last, and the prompt's lists are this same
    # function's answer rather than a mirror of it.

    def balance_candidates(self, seat: int, stage: str) -> list:
        """``(battlefield slot, permanent)`` for each of *seat*'s permanents
        Balance's *stage* (``"lands"`` / ``"creatures"``) counts — what that
        round offers and the only permanents its answer may name."""
        if stage == "lands":
            def counted(perm):
                return perm.has_type("land")
        elif stage == "creatures":
            def counted(perm):
                return perm.is_creature
        else:
            raise ValueError(f"Balance has no {stage!r} round on the battlefield")
        return [
            (slot, perm)
            for slot, perm in enumerate(self.controlled_by(seat))
            if counted(perm)
        ]

    def _balance_count(self, seat: int, stage: str) -> int:
        if stage == "hand":
            return len(self.players[seat].hand)
        return len(self.balance_candidates(seat, stage))

    def begin_balance(self, card_name: str = "Balance") -> bool:
        """Open Balance's first round that owes anything (lands, then cards
        in hand, then creatures). False when no round does. *card_name* is
        the resolving card, which every line of the rounds names — the card
        that prints the sentence rather than the one it was written for."""
        return self._open_balance_round(0, card_name)

    def _open_balance_round(self, start: int, card_name: str = "Balance") -> bool:
        """Count each round from *start* on and arm the first that owes."""
        seats = self.apnap_seats()
        for stage in BALANCE_ROUNDS[start:]:
            counts = {seat: self._balance_count(seat, stage) for seat in seats}
            if not counts:
                return False
            fewest = min(counts.values())
            owed = {seat: count - fewest for seat, count in counts.items() if count > fewest}
            if not owed:
                continue
            batch = {
                "stage": stage, "answers": [], "armed": False, "applied": False,
                # Who still has to be asked, in turn order from the active
                # player: "First the player whose turn it is chooses ..., then
                # each other player in turn order does the same. Each player
                # will know the choices made by the players who chose before
                # them." So one seat is asked at a time, and the next only once
                # the one before has chosen.
                "waiting": [(seat, owed[seat]) for seat in seats if seat in owed],
                "card_name": card_name,
            }
            self.log.append(
                f"{card_name}: each player chooses {_BALANCE_ROUND_WORDS[stage]}"
            )
            self._ask_next_balance_seat(batch)
            batch["armed"] = True
            self._finish_balance_round(batch)
            return True
        return False

    def _ask_next_balance_seat(self, batch: dict) -> None:
        """Arm the round's prompt for the next seat in turn order, if any."""
        if not batch["waiting"]:
            return
        seat, count = batch["waiting"].pop(0)
        plan = {"lands": 0, "creatures": 0, "hand": 0}
        plan[batch["stage"]] = count
        self.arm_pending_choice(
            "balance", seat, plan=plan, stage=batch["stage"], _balance=batch,
        )

    def _finish_balance_round(self, batch: dict) -> None:
        """Perform a round once none of its prompts is still owed, then count
        the next one on the board it leaves.

        Read off the queue, as :meth:`finish_keep_batch` is, so a prompt that
        left the queue unanswered cannot strand the answers that were given.
        """
        if not batch.get("armed") or batch.get("applied") or batch.get("waiting"):
            return
        if any(
            owed.kind == "balance" and owed.data.get("_balance") is batch
            for owed in self.pending_choices
        ):
            return
        batch["applied"] = True
        stage = batch["stage"]
        if stage == "hand":
            # One event: a discard an opponent causes can put the card onto the
            # battlefield instead (Dodecapod), and every such card enters together
            # (CR 603.6a).
            with self.entering_together():
                for choice, chosen in batch["answers"]:
                    player = self.players[choice.player_index]
                    for index, card in chosen:
                        # By slot, checked by identity — every copy of a card in a
                        # hand is the same object, so the slot is what keeps the
                        # hand's order — and through the hand seam if it moved.
                        if 0 <= index < len(player.hand) and player.hand[index] is card:
                            player.hand.pop(index)
                        elif not self.take_card_from_hand(player, card):
                            continue
                        # "…Players **discard** cards … the same way." Through the
                        # discard seam, never straight to the graveyard: it is
                        # CR 701.9a's event, so "whenever a player discards a
                        # card" (Megrim) hears it. The cause is the seat that cast
                        # it, off the prompt.
                        self._discard_card(
                            player, card, cause_seat=choice.data.get("_cause_seat"),
                        )
                    self.log.append(
                        f"{player.name} discarded {len(chosen)} card(s) "
                        f"({batch.get('card_name', 'Balance')})"
                    )
        else:
            # Every seat's unchosen permanents in one event (CR 701.21a), the
            # ruling's "sacrificed simultaneously".
            doomed = [perm for _choice, chosen in batch["answers"] for perm in chosen]
            self.sacrifice_permanents(doomed)
            for choice, chosen in batch["answers"]:
                self.log.append(
                    f"{self.players[choice.player_index].name} sacrificed "
                    + (", ".join(perm.card.name for perm in chosen) or "nothing")
                    + f" ({batch.get('card_name', 'Balance')})"
                )
        self._open_balance_round(
            BALANCE_ROUNDS.index(stage) + 1, batch.get("card_name", "Balance")
        )

    def _resolve_balance(self, choice: PendingChoice, land_indices, creature_indices, hand_indices) -> bool:
        """One seat's answer to one round, validated whole and then *held*
        until the round's last answer is in."""
        seat = choice.player_index
        plan = choice.data["plan"]
        stage = choice.data.get("stage")
        lands = list(dict.fromkeys(land_indices or []))
        creatures = list(dict.fromkeys(creature_indices or []))
        hand = list(dict.fromkeys(hand_indices or []))
        if len(lands) != plan["lands"] or len(creatures) != plan["creatures"] or len(hand) != plan["hand"]:
            return False
        player = self.players[seat]
        if stage == "hand":
            if not all(isinstance(i, int) and 0 <= i < len(player.hand) for i in hand):
                return False
            # Highest slot first, the order the discards are made in.
            chosen: list = [(i, player.hand[i]) for i in sorted(hand, reverse=True)]
            said = f"{player.name} chose {len(chosen)} card(s) to discard"
        elif stage in ("lands", "creatures"):
            offered = dict(self.balance_candidates(seat, stage))
            picked = lands if stage == "lands" else creatures
            if not all(i in offered for i in picked):
                return False
            chosen = [offered[i] for i in picked]
            said = (
                f"{player.name} chose "
                + (", ".join(perm.card.name for perm in chosen) or "nothing")
                + " to sacrifice"
            )
        else:
            return False
        batch = choice.data["_balance"]
        self.discard_pending_choice(choice)
        # The choice of permanents is public as it is made (the next seat
        # chooses knowing it); which cards a hand gives up is not, until every
        # seat has chosen (the ruling: "no cards are revealed until all
        # players have chosen what to discard").
        batch["answers"].append((choice, chosen))
        self.log.append(said + f" ({batch.get('card_name', 'Balance')})")
        self._ask_next_balance_seat(batch)
        self._finish_balance_round(batch)
        return True

    def _default_balance(self, choice: PendingChoice) -> None:
        """Keep the lowest-slot permanents and cards: give up the last ones
        the round counts."""
        plan = choice.data["plan"]
        stage = choice.data.get("stage")
        owed = int(plan.get(stage, 0)) if stage else 0
        player = self.players[choice.player_index]
        picks: dict = {"lands": [], "creatures": [], "hand": []}
        if owed and stage == "hand":
            picks["hand"] = list(range(len(player.hand)))[-owed:]
        elif owed and stage in ("lands", "creatures"):
            slots = [slot for slot, _perm in self.balance_candidates(choice.player_index, stage)]
            picks[stage] = slots[-owed:]
        if not self._resolve_balance(choice, picks["lands"], picks["creatures"], picks["hand"]):
            self.discard_pending_choice(choice)
            # A default that could not be given is still an answer the round
            # was waiting on.
            batch = choice.data.get("_balance")
            if batch is not None:
                self._ask_next_balance_seat(batch)
                self._finish_balance_round(batch)

    def confirm_balance(self, player_index: int, land_indices=None, creature_indices=None, hand_indices=None) -> bool:
        """Answer one player's Balance round with their chosen sacrifices or discards."""
        return self.resolve_pending_choice(
            "balance", player_index,
            land_indices=land_indices, creature_indices=creature_indices, hand_indices=hand_indices,
        )

    def auto_resolve_pending_balance(self, only_player_index: int | None = None) -> None:
        """Resolve Balance plans with a default choice (keep the lowest-index
        permanents/cards). Used for AI players and headless simulation. When
        ``only_player_index`` is given, resolve just that player's plan."""
        self.auto_resolve_pending_choices(only_player_index=only_player_index, kinds=("balance",))

    # -- Forced sacrifice of the player's choice (Lich, Lord of the Pit) ---------
    #
    # A single mechanism drives every "sacrifice a permanent you choose" effect so
    # they behave uniformly. ``arm_forced_sacrifice`` either arms an interactive
    # prompt (human seat) or resolves the sacrifice inline with a deterministic
    # heuristic (AI / headless). The choice's payload is
    #   {"count", "filter", "exclude", "reason"}
    # where ``filter`` is the printed noun phrase as a filter payload
    # (``{"nontoken": True}`` for Lich, ``{"type_filter": "creature"}`` for Lord of
    # the Pit, ``{"type_filter": "creature", "with_keywords": ["flying"]}`` for Run
    # Afoul), and ``exclude`` is a Permanent that can't be chosen (Lord of the Pit
    # excludes itself).
    #
    # **What happens when a player cannot sacrifice what they owe is not this
    # mechanism's.** A printed "If you can't, ..." is decided before anything is
    # armed, by the step that knows the sentence: the sacrifice handler records
    # whether the payer controls the printed number (``sacrificed_this_way``,
    # read by the compiled branch behind it -- Lich's loss, Infernal Denizen's
    # control change), and Lord of the Pit's upkeep arms the sacrifice only
    # when a creature can be given up and deals its 7 damage otherwise. A
    # consequence riding the prompt (``on_short``) was offered here and no
    # caller ever passed one; it went in round ``kg3``
    # (``tests/regressions/test_kg3_leftovers_sacrifice_shortfall.py``).
    #
    # It used to be one of two words, "nontoken" or "creature", tested by two
    # hand-written lines here. That is why a narrowed sacrifice had to be refused
    # at compile time rather than charged: the noun phrase the card prints is a
    # filter, and this was the one reader of it that could not read one.

    def _sacrifice_candidate_indices(
        self, player, filter: dict | None, exclude=None, *, held: dict | None = None,
    ) -> list[int]:
        """Battlefield indices of ``player``'s permanents eligible for a forced
        sacrifice under the filter payload ``filter`` (excluding ``exclude`` if
        given).

        **Not one already held** in *held*, a sacrifice batch
        (:meth:`new_sacrifice_batch`): a permanent a loop's earlier repetition
        chose is given up once, by the loop's last step, and a later
        repetition — or an offer whose price is a sacrifice — may not count it
        again. Fade Away's ruling: "you can't sacrifice one creature in order
        to pay for another"."""
        held = self._held_ids(held)
        out: list[int] = []
        for i, perm in enumerate(player.battlefield):
            if exclude is not None and perm is exclude:
                continue
            if held and id(perm) in held:
                continue
            if not subject_matches(self, perm, filter):
                continue
            out.append(i)
        return out

    def _resolve_sacrifice_inline(self, player_index: int, count: int, filter: dict | None, exclude, reason: str, record: dict | None = None, up_to: bool = False, count_onto=None) -> None:
        """Sacrifice ``count`` of the player's permanents with the deterministic
        heuristic (permanents whose death loses the game are kept for last).

        ``up_to`` is a **stated policy**, not a heuristic: a seat merely
        *offered* the chance to give permanents up gives up none. Sacrificing is
        a cost, and a non-interactive seat paying an optional cost nobody asked
        it for is the engine playing that seat's game. Wood Elemental therefore
        enters as a 0/0 and dies to CR 704.5f, which is what the card does when
        its controller declines."""
        player = self.players[player_index]
        if up_to:
            self._record_sacrifice_count(count_onto, 0)
            return
        # "Sacrifice two creatures" is one action, so one event (CR 603.10a,
        # ``leaving_together``): picked one at a time on the board each pick
        # leaves, and each sacrifice looks back at the rest.
        with self.leaving_together():
            for _ in range(count):
                valid = self._sacrifice_candidate_indices(player, filter, exclude)
                if not valid:
                    return
                # `default_sacrifice_pick`'s docstring already named this as one of
                # the three callers of the one rule; it was in fact a fourth copy,
                # carrying the "keep the game-loser for last" half and neither the
                # smallest-first half nor the id tiebreak. Two seats owing the same
                # sacrifice through different paths would have given it up
                # differently, which is what the shared rule exists to stop.
                perm = self.default_sacrifice_pick(
                    [self.permanent_at(player, i) for i in valid]
                )
                _record_sacrificed_card(record, player_index, perm)
                self.sacrifice_permanent(perm)
                self.log.append(f"{player.name} sacrificed {perm.card.name} ({reason})")

    def arm_forced_sacrifice(
        self,
        player_index: int,
        count: int,
        *,
        filter: dict,
        exclude=None,
        reason: str = "Sacrifice",
        record: dict | None = None,
        up_to: bool = False,
        count_onto=None,
        batch: dict | None = None,
    ) -> None:
        """Force a player to sacrifice ``count`` permanents matching the filter
        payload ``filter``. A human seat is prompted to choose which; AI /
        headless play resolves it inline. Multiple calls to the same player
        during one step accumulate onto the existing prompt (e.g. two
        combat-damage events feeding Lich).

        *batch* is one resolution's "**each player** sacrifices …"
        (:meth:`new_sacrifice_batch`): the seat's answer — asked or defaulted
        — is *held*, and nothing is sacrificed until
        :meth:`finish_sacrifice_batch` performs every seat's together (CR
        101.4). A batched prompt never folds into one already owed: it is one
        seat's turn in a round, not a second debt of the same shape.

        ``filter`` has no default. An empty payload is a legal value meaning "any
        permanent", but it has to be written down: a caller that simply forgot
        the noun phrase would otherwise sacrifice more widely than the card
        prints, and defaulting is how that stays invisible.

        ``record`` is a resolution scratchpad the sacrificed *cards* are appended
        to under ``sacrificed_cards``. A later step of the same effect may be
        about what went (Transmute Artifact reads its mana value), and by then
        the permanent is in a graveyard and is a different object (CR 400.7) —
        so it is recorded as it happens, which is CR 608.2h's rule.

        ``up_to`` makes ``count`` a **ceiling** rather than an amount: "sacrifice
        any number of untapped Forests" (Wood Elemental) is answered by any
        subset, none included. A flag on the same prompt rather than a second
        kind for the reason ``discard``'s ``up_to`` is one: what differs is how
        many answers are legal, not what the answer means.

        ``count_onto`` is a permanent that wants to know **how many** were given
        up: the number goes in its ``sacrificed_as_entered`` metadata, which is
        what a characteristic-defining P/T reading "equal to the number of
        <things> sacrificed as it entered" counts (CR 604.3). It is recorded
        where the sacrifice happens because nothing downstream can recover it —
        the permanents are gone, and are different objects (CR 400.7).

        *batch* is also a loop's hold (:meth:`sacrificing_together_through`),
        handed in by the body's sacrifice: this repetition's answer is held
        with the others'."""
        player = self.players[player_index]
        if not self._sacrifice_candidate_indices(player, filter, exclude, held=batch):
            # Nothing matches, so nothing can be given up. An "any number"
            # sacrifice is *answered* by that — zero is a legal answer — so the
            # count it owes is recorded rather than left unset.
            self._record_sacrifice_count(count_onto, 0)
            return
        queued = None if batch is not None else self.pending_choice_of(
            "sacrifice", player_index
        )
        if queued is not None:
            if (
                queued.data["filter"] == filter
                and queued.data["exclude"] is exclude
                # A ceiling and an amount are different questions, so they do not
                # add up: folding "any number of Forests" into "sacrifice two
                # Forests" would let one answer discharge both, at whichever of
                # the two readings the merged prompt happened to keep.
                and bool(queued.data.get("up_to")) == bool(up_to)
                and queued.data.get("_count_onto") is count_onto
            ):
                queued.data["count"] += count
            else:
                # A differently-shaped sacrifice is already owed; this one can't be
                # folded into that prompt, so it resolves inline.
                self._resolve_sacrifice_inline(
                    player_index, count, filter, exclude, reason, record,
                    up_to=up_to, count_onto=count_onto,
                )
            return
        extra = {"_batch": batch} if batch is not None else {}
        self.arm_pending_choice(
            "sacrifice", player_index,
            count=count, filter=filter, exclude=exclude, reason=reason,
            record=record, up_to=up_to, _count_onto=count_onto,
            **extra,
        )

    # -- "Each player sacrifices …": chosen in turn order, done together -----
    #
    # CR 101.4's own example: "A card reads 'Each player sacrifices a
    # creature.' First, the active player chooses a creature they control.
    # Then each of the nonactive players, in turn order, chooses a creature
    # they control. Then all creatures chosen this way are sacrificed
    # simultaneously." The handler asks one seat at a time
    # (``resumption.ask_in_turn_order``) and arms each seat's ``sacrifice``
    # prompt with a batch; the answers are held here and performed by the
    # round's last step. Every prompt of a round used to be armed at once, in
    # seat order, and each answer sacrificed on the spot: the nonactive player
    # was asked first whenever seat 0 was not the active player, a later
    # chooser saw nothing of an earlier one's choice, and an anthem given up
    # by the first seat had stopped applying to what the second chose among.

    @staticmethod
    def new_sacrifice_batch() -> dict:
        """One resolution's round of ``sacrifice`` prompts — the keep batch's
        shape (:meth:`new_keep_batch`), finished by the round's own last step
        rather than by reading the queue, because the round is a
        ``run_resumable`` loop that already knows when its last seat has
        answered.

        Each answer is ``(seat, permanents, data)``: who gives them up, what,
        and the prompt's own data (its ``reason``, its ``record``, its
        ``_count_onto``) — :meth:`hold_sacrifice`'s shape."""
        return {"answers": [], "applied": False}

    @staticmethod
    def hold_sacrifice(batch: dict, seat: int, permanents, data: dict) -> None:
        """Hold *permanents* for *seat* in *batch*, to be sacrificed by
        :meth:`finish_sacrifice_batch` with the rest. *data* carries the
        ``reason`` its log line names, and optionally ``record`` and
        ``_count_onto``."""
        batch["answers"].append((seat, list(permanents), data))

    @staticmethod
    def _held_ids(batch: dict | None) -> set[int]:
        """The permanents (by identity) *batch* holds and has not yet
        sacrificed — empty for no batch."""
        if not batch or batch.get("applied"):
            return set()
        return {
            id(perm) for _seat, chosen, _data in batch["answers"] for perm in chosen
        }

    def sacrificing_together_through(self, context, run) -> None:
        """One event for every sacrifice a **resumable loop** makes
        (``engine/resumption.py``): ``run(then)`` runs the loop, and *then* is
        its last step, which performs what the repetitions chose.

        "For each creature, its controller sacrifices a permanent of their
        choice unless they pay {1}." (Fade Away.) Its ruling (2004-10-04):
        "each player counts up the number of creatures they control, then they
        make the required number of payments and/or sacrifices. The active
        player announces their choices first followed by the other players,
        but all the sacrifices are done at the same time. Because of this, you
        can't sacrifice one creature in order to pay for another and thereby
        avoid payment for the first." Each repetition sacrificed at its own
        answer, so an observer sacrificed by the first (Havoc Jester, Moonlit
        Wake) saw none of the rest go (CR 603.10a), and a creature sacrificed
        for another's repetition was gone before its own was asked.

        The hold rides the loop's own *context*
        (``OracleExecutionContext.sacrifice_batch``), so it reaches exactly the
        sacrifices the loop's body makes — at once, or at the answer of a
        prompt that carries that context (an offer's decline) — and nothing
        else the table does meanwhile: the forced sacrifice a phrase names
        (``sacrifice_matching_permanent``) and a recorded one
        (``sacrifice_recorded_permanent``) are held, and a held permanent is
        no candidate for another (:meth:`_sacrifice_candidate_indices`). The
        last step clears it and sacrifices everything held in one event
        (:meth:`finish_sacrifice_batch`). Inside a loop already holding, the
        loop is part of that one, and *then* is None. The departure twin of
        ``entering_together_through``.
        """
        if context.sacrifice_batch is not None:
            run(None)
            return
        batch = self.new_sacrifice_batch()
        context.sacrifice_batch = batch

        def last_step() -> None:
            if context.sacrifice_batch is batch:
                context.sacrifice_batch = None
            self.finish_sacrifice_batch(batch)

        try:
            run(last_step)
        except BaseException:
            if context.sacrifice_batch is batch:
                context.sacrifice_batch = None
            raise

    def _default_sacrifice_slots(self, player, data: dict) -> list[int]:
        """The battlefield slots a seat nobody asks gives up: the shared
        default rule (:meth:`default_sacrifice_pick`) applied *count* times
        over the board as it stands — nothing leaves before the round's last
        answer, so every pick is made on one board. A ceiling ("any number")
        is answered with none, the inline default's stated policy."""
        if data.get("up_to"):
            return []
        valid = self._sacrifice_candidate_indices(
            player, data["filter"], data["exclude"], held=data.get("_batch"),
        )
        remaining = {index: self.permanent_at(player, index) for index in valid}
        picks: list[int] = []
        for _ in range(min(int(data["count"]), len(remaining))):
            perm = self.default_sacrifice_pick(list(remaining.values()))
            slot = next(i for i, p in remaining.items() if p is perm)
            picks.append(slot)
            del remaining[slot]
        return picks

    def finish_sacrifice_batch(self, batch: dict) -> list:
        """Sacrifice every held answer of *batch* in **one event**, then say
        what each seat gave up, in the order the seats chose.

        Every seat's P/T totals and records are read before anything moves
        (CR 608.2h's last-known information, the rule
        :meth:`_resolve_sacrifice` follows for one seat), then
        :meth:`sacrifice_permanents` — so a watcher going in the same event
        sees the rest go (CR 603.10a). Returns the permanents sacrificed. Runs
        once.
        """
        if batch.get("applied"):
            return []
        batch["applied"] = True
        plans: list = []
        doomed: list = []
        for seat, chosen, data in batch["answers"]:
            live = [perm for perm in chosen if self.is_on_battlefield(perm)]
            totals = (
                sum(int(perm.effective_power) for perm in live),
                sum(int(perm.effective_toughness) for perm in live),
            )
            for perm in live:
                _record_sacrificed_card(data.get("record"), seat, perm)
            plans.append((seat, data, live, totals))
            doomed.extend(live)
        gone = self.sacrifice_permanents(doomed)
        for seat, data, live, totals in plans:
            player = self.players[seat]
            went = [perm for perm in live if any(perm is g for g in gone)]
            for perm in went:
                self.log.append(f"{player.name} sacrificed {perm.card.name} ({data['reason']})")
            self._record_sacrifice_count(data.get("_count_onto"), len(went), totals)
        return gone

    def _record_sacrifice_count(
        self, count_onto, given_up: int, totals: tuple[int, int] = (0, 0)
    ) -> None:
        """Stamp what was sacrificed onto the permanent that asked for it
        (CR 604.3's "…sacrificed as it entered").

        Three numbers, not one: how many (Wood Elemental) and the **totals** of
        their power and toughness (Dracoplasm, "this creature's power becomes
        the total power of those creatures"). All three unconditionally, because
        a no-op for every sacrifice nobody is counting is what lets the three
        answer paths record without each remembering to ask.

        *totals* arrives already summed, and it has to: by the time this runs
        the creatures are cards in a graveyard and have no power or toughness at
        all (CR 613.1), so the numbers are CR 608.2g's last known information,
        read at the removal site."""
        if count_onto is None:
            return
        count_onto.metadata["sacrificed_as_entered"] = int(given_up)
        count_onto.metadata["sacrificed_total_power"] = int(totals[0])
        count_onto.metadata["sacrificed_total_toughness"] = int(totals[1])
        self._refresh_dynamic_creatures()

    def pending_sacrifice_state(self) -> dict | None:
        """The active sacrifice prompt as valid battlefield indices + count, or
        None. Used by the web layer to render/highlight the choice."""
        choice = self.pending_choice_of("sacrifice")
        if choice is None:
            return None
        return self._sacrifice_prompt(choice)

    def _sacrifice_prompt(self, choice: PendingChoice) -> dict:
        player = self.players[choice.player_index]
        valid = self._sacrifice_candidate_indices(
            player, choice.data["filter"], choice.data["exclude"],
            held=choice.data.get("_batch"),
        )
        return {
            "player_index": choice.player_index,
            "valid_indices": valid,
            "count": min(int(choice.data["count"]), len(valid)),
            # Whether that count is an amount owed or a ceiling offered. The
            # picker needs the difference: one enables its confirm at exactly
            # that many, the other at any number up to it, none included.
            "up_to": bool(choice.data.get("up_to")),
            "reason": choice.data["reason"],
        }

    def confirm_sacrifice(
        self, player_index: int, indices: list[int] | None = None,
        *, permanent_ids: list[int] | None = None,
    ) -> bool:
        """Resolve the pending forced sacrifice with the player's chosen
        permanents — by stable id (*permanent_ids*, authoritative when given)
        or by battlefield slot. Requires exactly ``min(count, eligible
        permanents)`` distinct eligible permanents (CR 609.3: as much as
        possible)."""
        return self.resolve_pending_choice(
            "sacrifice", player_index, indices=indices, permanent_ids=permanent_ids,
        )

    def _sacrifice_slots_for_ids(self, player, permanent_ids) -> list[int] | None:
        """*permanent_ids* as the seat's battlefield slots, or None when any id
        names no permanent of theirs (a stale id is a refusal, never a
        guess). The prompt's own id form (CR 400.7: an id names one object,
        where a slot renumbers the moment anything leaves)."""
        seat = self.players.index(player)
        slots: list[int] = []
        for pid in permanent_ids:
            found = self.find_permanent_by_id(pid) if isinstance(pid, int) else None
            if found is None or found[0] != seat:
                return None
            slot = self.battlefield_index_of(found[1])
            if slot is None:
                return None
            slots.append(slot)
        return slots

    def _resolve_sacrifice(
        self, choice: PendingChoice, indices: list[int] | None,
        permanent_ids: list[int] | None = None,
    ) -> bool:
        player_index = choice.player_index
        player = self.players[player_index]
        data = choice.data
        if permanent_ids is not None:
            indices = self._sacrifice_slots_for_ids(player, permanent_ids)
            if indices is None or len(set(permanent_ids)) != len(permanent_ids):
                return False
        valid = self._sacrifice_candidate_indices(
            player, data["filter"], data["exclude"], held=data.get("_batch"),
        )
        count = int(data["count"])
        need = min(count, len(valid))
        chosen = list(dict.fromkeys(indices or []))
        # "Sacrifice **any number** of untapped Forests" (Wood Elemental): the
        # printed count is a ceiling, and none is a legal answer. Reading a
        # ceiling as an exact count would force a player to give up permanents
        # the card offered them the choice of keeping — the mirror of the same
        # word on `discard`.
        enough = len(chosen) <= need if data.get("up_to") else len(chosen) == need
        if not enough or any(i not in valid for i in chosen):
            return False
        reason = data["reason"]
        batch = data.get("_batch")
        if batch is not None:
            # One seat's turn in "each player sacrifices …" — or one
            # repetition of a loop whose sacrifices are made together
            # (:meth:`sacrificing_together_through`): the choice is held and
            # said now — public the moment it is made, because the next player
            # chooses knowing it (CR 101.4b) — and nothing leaves until the
            # round's last answer (:meth:`finish_sacrifice_batch`).
            held = [self.permanent_at(player, i) for i in sorted(chosen)]
            self.discard_pending_choice(choice)
            self.hold_sacrifice(batch, player_index, held, data)
            self.log.append(
                f"{player.name} chose "
                + (", ".join(perm.card.name for perm in held) or "nothing")
                + f" to sacrifice ({reason})"
            )
            return True
        # Resolved before any removal, so no index is held across one.
        removed: list[str] = []
        record = data.get("record")
        # CR 608.2g: read the P/T *before* the removal. A moment later these are
        # cards in a graveyard with no computed characteristics at all
        # (CR 613.1), and Dracoplasm's whole size is their sum.
        total_power = total_toughness = 0
        # One answer, one event (CR 603.10a, ``leaving_together``); the
        # state-based check below is the next event, outside it.
        with self.leaving_together():
            for perm in [
                self.permanent_at(player, i) for i in sorted(chosen, reverse=True)
            ]:
                total_power += int(perm.effective_power)
                total_toughness += int(perm.effective_toughness)
                _record_sacrificed_card(record, player_index, perm)
                self.sacrifice_permanent(perm)
                removed.append(perm.card.name)
        for name in reversed(removed):
            self.log.append(f"{player.name} sacrificed {name} ({reason})")
        self.discard_pending_choice(choice)
        self._record_sacrifice_count(
            data.get("_count_onto"), len(chosen), (total_power, total_toughness)
        )
        self.check_state_based_actions()
        return True

    def _default_sacrifice(self, choice: PendingChoice) -> None:
        self.discard_pending_choice(choice)
        data = choice.data
        if data.get("_batch") is not None:
            # Held like an asked answer, picked by the same rule the inline
            # default uses — on the board as it stands, since nothing in the
            # round has moved yet.
            slots = self._default_sacrifice_slots(self.players[choice.player_index], data)
            self._resolve_sacrifice(choice, slots)
            return
        self._resolve_sacrifice_inline(
            choice.player_index, int(data["count"]), data["filter"],
            data["exclude"], data["reason"], data.get("record"),
            up_to=bool(data.get("up_to")), count_onto=data.get("_count_onto"),
        )


# ---------------------------------------------------------------------------
# This family's rows of the prompt table
# ---------------------------------------------------------------------------
#
# One ``ChoiceSpec`` per prompt kind of this family, in the table's order
# (``engine/pending_choices.py`` says what each field means). ``table.py``
# registers them, in the one list ``Game.iter_pending_prompts`` reads.

BALANCE_SPEC = ChoiceSpec(
    "balance",
    resolve=lambda game, choice, r: game._resolve_balance(
        choice, r["land_indices"], r["creature_indices"], r["hand_indices"]
    ),
    default=lambda game, choice: game._default_balance(choice),
    action="balance_confirm",
    prompt_key="balance_select",
    blocked_detail="complete Balance sacrifices before other actions",
)

SACRIFICE_SPEC = ChoiceSpec(
    "sacrifice",
    resolve=lambda game, choice, r: game._resolve_sacrifice(
        choice, r.get("indices"), r.get("permanent_ids"),
    ),
    default=lambda game, choice: game._default_sacrifice(choice),
    action="sacrifice_confirm",
    prompt_key="sacrifice_select",
    blocked_detail="complete forced sacrifice before other actions",
    default_at_arm=True,
    spectator_visible=True,
    # "Sacrifice an artifact. **If you do**, search your library…" (Transmute
    # Artifact): what the player gives up decides what the rest of the same
    # resolution may find, so the rest has to wait for the answer. Only an
    # interactive seat ever queues this — `default_at_arm` takes the
    # deterministic answer before the flag is set — so headless and AI play run
    # exactly as they did.
    suspends=True,
)

AGGREGATE_SACRIFICE_SPEC = ChoiceSpec(
    "aggregate_sacrifice",
    resolve=lambda game, choice, r: game._resolve_aggregate_sacrifice(
        choice, r.get("permanent_ids") or []
    ),
    default=lambda game, choice: game._default_aggregate_sacrifice(choice),
    action="aggregate_sacrifice_confirm",
    prompt_key="aggregate_sacrifice",
    blocked_detail="choose what to sacrifice before other actions",
    # **Not** ``suspends``: the sacrifice *is* the answer and it is the last
    # step of the offer's accept branch, so nothing behind it reads a record.
    # ``blocked_detail`` is what makes the game wait (CR 608.2), which it must —
    # the creatures are still on the battlefield until the answer arrives.
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    spectator_visible=True,
)

KEEP_PERMANENTS_SPEC = ChoiceSpec(
    "keep_permanents",
    resolve=lambda game, choice, r: game._resolve_keep_permanents(
        choice, r.get("permanent_ids") or []
    ),
    default=lambda game, choice: game._default_keep_permanents(choice),
    action="keep_permanents_confirm",
    prompt_key="keep_permanents",
    blocked_detail="choose which permanents to keep before other actions",
    # The sacrifice is this prompt's own resolver rather than a step behind it,
    # so nothing inside the resolution is waiting on the answer - but the
    # *other* seats' prompts are armed by the same instruction and the object
    # stays on the stack until the last of them is answered (CR 608.2), which is
    # what the gate above buys.
    #
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated maximum keep is taken where the effect stands.
    default_at_arm=True,
    spectator_visible=True,
    # "…then sacrifices the rest. **Each player discards cards the same
    # way.**" (Balancing Act.) The first card with a step *behind* the keep,
    # and that step arms a prompt of its own for the same seat. Left running,
    # one seat owed a keep and a discard at once and each answer was refused
    # naming the other — every blocking prompt refuses every action but its
    # own. So the keep holds the resolution the way a forced sacrifice does,
    # and the step behind it runs when the last keep is answered. Nothing
    # changes for the four cards printed before it: none has a step behind
    # the keep, and a seat nobody asks never queues one.
    suspends=True,
)
