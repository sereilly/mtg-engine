"""**Sacrifice** as an effect (CR 701.21), and the keeps whose complement is a
sacrifice.

To sacrifice is the controller's own act, so what each handler settles is
*who* owes it, *how many* and *which of theirs*: the source itself (Cocoon's
hatch), a permanent a phrase names ("sacrifice a creature", through the
standing forced-sacrifice prompt), a set whose power adds up to a total
(Phyrexian Dreadnought). Every sacrifice goes through
``Game.sacrifice_permanent``, CR 701.21a's one transition. Beside them, the
paragraphs where the sacrifice is "the rest" — what a player keeps is chosen
and everything else goes: Cataclysm and Limited Resources
(``keep_chosen_sacrifice_rest``), Natural Balance's five lands, and Balance's
lands, creatures and hand, each brought down to the fewest any player has.

The handler twin of the sacrifice half of ``engine/grammar/lowering/board.py``.
Split out of ``board_misc.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..oracle_types import X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT
from ._amounts import evaluate_count
from ._filters import seats_matching_deed
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("balance_resources")
def balance_resources(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    def _count(player, kind):
        # What each permanent **is** (CR 613 layer 4) — the same two
        # questions the prompt that takes the answer asks of each slot
        # (``_resolve_balance``): a Mishra's Factory that is animated is a
        # land *and* a creature, an Opalescence's enchantment is a creature.
        return sum(
            1 for perm in game.controlled_by(player)
            if (perm.has_type("land") if kind == "land" else perm.is_creature)
        )

    min_lands = min(_count(p, "land") for p in game.players)
    min_creatures = min(_count(p, "creature") for p in game.players)
    min_hand = min(len(p.hand) for p in game.players)

    # Build the per-player reduction plan. Each player chooses which of their own
    # lands/creatures to sacrifice and which cards to discard down to these counts;
    # defer to a pending choice (human is prompted, AI/headless auto-resolves).
    plans: dict[int, dict] = {}
    for idx, player in enumerate(game.players):
        plan = {
            "lands": max(0, _count(player, "land") - min_lands),
            "creatures": max(0, _count(player, "creature") - min_creatures),
            "hand": max(0, len(player.hand) - min_hand),
        }
        if plan["lands"] or plan["creatures"] or plan["hand"]:
            plans[idx] = plan

    if not plans:
        game.log.append("Balance: nothing to normalize")
        return True, "resolved"

    # Each player owes their own removals, so each gets their own queued choice.
    for idx, plan in plans.items():
        game.arm_pending_choice("balance", idx, plan=plan)
    game.log.append("Balance: each player chooses what to sacrifice and discard")
    return True, "pending_balance"


@effect_handler("sacrifice_self")
def sacrifice_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…sacrifice it." where "it" is the ability's own source (Cocoon's
    hatch).

    Through ``Game.sacrifice_permanent`` — CR 701.21a's one transition — so the
    owner lookup, token cessation, would-die replacements, Aura teardown and
    death counts all happen. A source already gone is nothing to sacrifice
    (CR 608.2b does as much as possible), not a failure: the rest of the
    resolution still runs.

    Whether it happened is recorded under ``sacrificed_self``, the same shape
    ``exile_self`` uses and for the same reason: "Sacrifice this artifact. **If
    you do**, …" (Knowledge Vault) asks about the step before it, and a step
    that records nothing gives the branch nothing to test — the whole ability
    refuses to lower rather than guessing that it always happened.

    This kind used to have **no handler at all**: every card compiling it was
    a "when you control no Islands/lands" state trigger the CR 603.8 sweep in
    ``mixins/game_ending.py`` performs itself, and the generic dispatch
    reported "resolved without state mutation". That sweep still owns those
    triggers — it never executes instructions, so nothing fires twice.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: nothing left to sacrifice")
        return True, "resolved"
    if game.sacrifice_permanent(source) is not None:
        context.results["sacrificed_self"] = True
        game.log.append(f"{context.card.name} was sacrificed")
    return True, "resolved"




@effect_handler("sacrifice_permanents_totalling")
def sacrifice_permanents_totalling(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…sacrifice **any number of creatures with total power 12 or greater**."
    (Phyrexian Dreadnought.)

    Its own handler rather than a count on the forced-sacrifice prompt beside
    it, because the seat is being asked a different question: not "give up N of
    these" but "give up any set of these whose power adds up", which no number
    expresses — a set of five may pay where a set of six does not.

    The controller alone is asked (CR 109.5's bare imperative), and the price is
    checked against the *aggregate* rather than the count, through the same
    accessor every other reader of a creature's power uses so a pumped creature
    counts for what CR 613 says it is.
    """
    seat = game.players.index(context.caster)
    payload = dict(instruction.payload)
    payload["_source"] = context.source_permanent
    game.arm_aggregate_sacrifice(seat, payload, context)
    return True, "resolved"


@effect_handler("sacrifice_matching_permanent")
def sacrifice_matching_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Sacrifice a creature" / "sacrifice another creature" as an effect a
    player performs (Dire Fleet Warmonger's accepted cost; Goremand's entry
    trigger; Run Afoul's "a creature of their choice with flying"). Routed
    through ``arm_forced_sacrifice``: a human seat picks which through the
    standing prompt, everyone else takes the deterministic heuristic.

    ``who`` names the payers — absent means the effect's own controller, which
    is what a bare imperative means (CR 109.5). "Each opponent" arms the same
    prompt for each of them, still living, in seat order so the AI simulation
    stays seed-reproducible. The two targeted forms are the seat the spell
    already chose; they stay apart in the payload because CR 102.2/102.3 makes "target
    opponent" and "target player" different spells, and only the picker cares.
    ``event_subject_player`` is the seat a trigger's own condition named
    (Mana Vortex's "each player's upkeep, **that player** sacrifices"), read
    off the context the fire site froze; ``event_subject_controller`` is the
    seat that controlled the *object* the event was about (Earthlink's "that
    creature's controller"), off the same context.

    An unrecognized ``who`` fails the instruction rather than defaulting to the
    controller: silently sacrificing the caster's own creature instead of the
    named player's is the wrong direction to guess in.
    """
    caster_index = game.players.index(context.caster)
    exclude = context.source_permanent if instruction.payload.get("exclude_self") else None
    if instruction.payload.get("exclude_attached_host"):
        # "…unless they sacrifice **another** creature of their choice."
        # (Unnatural Hunger.) On an Aura's own trigger the antecedent of
        # "another" is the *enchanted* permanent, not the ability's source: an
        # Aura is not a creature, so excluding it rules out nothing and the
        # enchanted creature is offered as its own way out of the damage.
        #
        # The same ``exclude`` channel the source spelling above uses, so the
        # takeability gate, the inline resolution and the queued prompt all get
        # it for free — and through ``attached_host``, which answers the
        # last-known-information case (CR 603.10) the Aura may already be in.
        from ._targets import attached_host

        exclude = attached_host(game, context.source_permanent)
    who = instruction.payload.get("who")
    if who is None:
        payers = [caster_index]
    elif who == "each_opponent":
        payers = list(game.opponents_of(caster_index))
    elif who == "each_player":
        # "Each player sacrifices a third of the creatures they control of
        # their choice." (Pox.) `each_opponent` plus the caster, in seat order
        # so the AI simulation stays seed-reproducible — the same list the
        # branch above builds, over one more seat.
        payers = [
            seat for seat, player in enumerate(game.players) if not player.lost
        ]
    elif who in ("target_opponent", "target_player"):
        payers = [game.players.index(context.target)]
    elif who == "that_player":
        # "Target opponent loses 2 life unless **that player** sacrifices a
        # permanent of their choice." (Forbidden Ritual.) A back-reference to a
        # player the same *sentence* named, on a line no event fired — so the
        # seat is the resolution's own chosen player, which is the read
        # ``discard_target_cards`` gives the identical pronoun and the read
        # ``offers._offered_seats`` gives it when it decides who is being
        # offered this very price. Three readers, one seat.
        #
        # Verified rather than trusted: a resolution that chose nobody leaves
        # ``context.target`` empty or holding a permanent, and indexing it would
        # raise. Nobody chosen is nobody asked, which is the honest outcome the
        # frozen-seat branches below already give.
        chosen = context.target
        if chosen not in game.players:
            return False, "no player was chosen for 'that player'"
        payers = [game.players.index(chosen)]
    elif who == "controller":
        # "For each creature, **its controller** sacrifices a permanent of
        # their choice unless they pay {1}." (Fade Away.) The seat that
        # controls the object the sentence is about, read through the seam
        # whose whole contract is "the innermost binding wins" — inside a loop
        # that is the iteration's own object, and outside one it is the
        # permanent this resolution targeted. The same reader
        # ``offers._offered_seats`` uses for the identical printed word,
        # so the seat offered the payment and the seat charged for declining
        # are one answer rather than two that can disagree.
        #
        # Nobody to ask is nobody charged, which is the honest outcome the
        # frozen-seat branches below already give: a permanent that has left
        # by the time this runs has no controller to name.
        from ._targets import bound_permanent

        perm = bound_permanent(game, context, predicate=lambda _p: True)
        seat = game.controller_index_of(perm) if perm is not None else None
        if seat is None:
            return False, "no permanent was bound for 'its controller'"
        payers = [seat]
    elif who == "event_subject_player":
        # "At the beginning of each player's upkeep, **that player** sacrifices
        # a land of their choice." (Mana Vortex.) The seat the trigger's own
        # condition named, frozen into the trigger's context by the fire site
        # (CR 603.10) — not the source's controller, which is the wrong seat on
        # every upkeep but their own. An absent key is a trigger nobody froze a
        # seat for, and guessing one is the failure the lowering's gate exists
        # to prevent, so the instruction fails rather than falling back.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False, "no seat was frozen for 'that player'"
        payers = [seat]
    elif who == "event_subject_controller":
        # "Whenever a creature dies, **that creature's controller** sacrifices
        # a land of their choice." (Earthlink.) The branch above one question
        # over: the seat that *controlled* what the event was about, frozen by
        # the same fire site and read the same way — a graveyard card cannot
        # say who controlled it, and under a control-change effect that is not
        # its owner. An absent key fails for the reason it fails above.
        seat = (context.trigger_context or {}).get("event_subject_controller")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False, "no seat was frozen for 'that creature's controller'"
        payers = [seat]
    elif who == "defending_player":
        # "Whenever this creature becomes blocked, **defending player**
        # sacrifices a land of their choice." (Thresher Beast.) CR 506.2's
        # seat, through the one reader of it; None is nobody asked.
        from ._targets import defending_player_seat

        seat = defending_player_seat(game, context)
        if seat is None:
            return False, "no defending player was recorded"
        payers = [seat]
    elif who == "damaged_player":
        # "…deals combat damage to a player, **that player** sacrifices a land
        # of their choice." (Destructive Urge.) The seat the damage went to,
        # frozen by the damage seam under the key the discard's identical
        # ``who`` reads.
        seat = (context.trigger_context or {}).get("defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False, "no damaged player was recorded"
        payers = [seat]
    else:
        return False, f"unsupported sacrifice payer {who!r}"
    # "…**each player who tapped a land for mana this turn** sacrifices a land
    # of their choice." (Desolation.) The printed relative clause, applied to
    # the list the branches above built rather than inside each of them: what
    # the clause narrows is *which of the payers*, and which payers there are
    # is the only thing those branches disagree about.
    payers = seats_matching_deed(
        game, context, payers, instruction.payload.get("who_did")
    )
    # "…a third of the creatures **they** control" (Pox): one number per payer,
    # so it cannot be the printed count — a fraction of a board has a different
    # answer for every seat asked. Evaluated against each payer through the same
    # evaluator every other computed count uses, so the fraction and its
    # rounding are applied in one place (CR 107.2/107.3).
    per_seat = instruction.payload.get(X_FROM_COUNT_PER_RECIPIENT)
    # "…sacrifices a creature of their choice **for each creature put into your
    # graveyard from the battlefield this turn**." (Urborg Justice.) One number
    # for every payer, counted once when the effect happens (CR 608.2h) and
    # counted for the *caster* — "your graveyard" is CR 400.3's owner and the
    # payer is somebody else. Its own channel beside the per-seat one above
    # because they answer for different seats; folded together, Urborg Justice
    # would read the sacrificing opponent's tally and ask for nothing whenever
    # they had lost nothing.
    shared = instruction.payload.get(X_FROM_COUNT)
    # A printed ``"x"`` is CR 107.3's announced X — "Each player sacrifices **X**
    # lands of their choice" (Tectonic Break) — resolved through the one channel
    # every other announced X reads. It used to read **zero** here, which was
    # right only because no payload reached this line carrying ``"x"`` alone:
    # every producer paired it with one of the count specs below, each of which
    # overwrites this. A bare one would have sacrificed nothing and logged
    # itself resolved.
    count = int(instruction.payload.get("count", 1)) if instruction.payload.get(
        "count"
    ) != "x" else max(0, int(context.x_value or 0))
    if shared is not None:
        # The source travels with the spec, because one of the shapes it can
        # carry is a pile of counters sitting on the ability's own permanent —
        # "…sacrifices a permanent of their choice **for each soot counter on
        # this artifact**" (Smokestack). ``evaluate_count`` answers that key
        # off the source it is handed and reads zero off the ``None`` it used
        # to get here, which for Smokestack is a card that has never asked for
        # anything.
        count = evaluate_count(
            game, context.caster, shared, source=context.source_permanent
        )
    # "Whenever this creature is dealt damage, sacrifice **that many**
    # permanents." (Phyrexian Negator.) The number the firing event carried,
    # frozen into the trigger's context by the fire site — read here under the
    # two keys the lowering chose between, which are the same two
    # ``target_loses_life`` and ``look_at_target_library_top`` already read for
    # the identical printed phrase. The trigger channel first, for that
    # handler's reason: an event's number and a scratchpad's are different
    # numbers, and a lowering emits exactly one of them.
    #
    # An absent record sacrifices **nothing** rather than falling back to the
    # count of 1 the default above supplies — a Negator dealt no damage owes no
    # permanents, and guessing one here would destroy a permanent on an event
    # that never happened.
    from_trigger = instruction.payload.get("amount_from_trigger")
    from_results = instruction.payload.get("amount_from")
    if from_trigger is not None:
        count = max(0, int((context.trigger_context or {}).get(from_trigger, 0)))
    elif from_results is not None:
        count = max(0, int(context.results.get(from_results, 0)))
    # "Sacrifice two Swamps. **If you can't**, …" (Infernal Denizen.) Whether
    # the sacrifice could be performed at all, recorded here rather than after
    # the prompt: an interactive seat answers a queued choice long after this
    # instruction has returned, so the only moment at which the answer exists
    # synchronously is before the prompt is armed. What it records is the
    # question CR 701.21a asks — does the payer control the printed number of
    # permanents the phrase describes — which is the same predicate
    # ``_action_is_takeable`` puts in front of an *optional* sacrifice, so an
    # offer and a mandatory action cannot disagree about what "can't" means.
    #
    # True when nobody owed anything, because a step that asked for nothing is
    # not a step that failed.
    # "Sacrifice **any number of** artifacts, creatures, and/or lands."
    # (Reprocess.) A ceiling rather than an amount, and one only the resolution
    # can size: the bound is however many of the seat's own permanents answer
    # the phrase. ``up_to`` is what makes none a legal answer, which is what the
    # word says — and it is why an "any number" sacrifice never fails to be
    # paid, so ``could_pay`` below is untouched by it.
    any_number = bool(instruction.payload.get("any_number"))
    if instruction.payload.get("all"):
        # "…sacrifices **all** creatures they control" (Living Death). Nothing
        # is chosen (CR 701.21a): every match each payer controls is taken,
        # gathered before any leaves.
        described = dict(instruction.payload.get("filter") or {})
        for seat in payers:
            payer = game.players[seat]
            doomed = [
                game.permanent_at(payer, index)
                for index in game._sacrifice_candidate_indices(payer, described, exclude)
            ]
            gone = [p.card.name for p in doomed if game.sacrifice_permanent(p) is not None]
            game.log.append(
                f"{payer.name} sacrificed {', '.join(gone) or 'nothing'} "
                f"({context.card.name})"
            )
        context.results["sacrificed_this_way"] = True
        return True, "resolved"
    could_pay = True
    for seat in payers:
        described = dict(instruction.payload.get("filter") or {})
        if any_number:
            offered = game._sacrifice_candidate_indices(
                game.players[seat], described, exclude
            )
            if not offered:
                continue
            game.arm_forced_sacrifice(
                seat, len(offered),
                filter=described,
                exclude=exclude,
                reason=context.card.name,
                record=context.results,
                up_to=True,
            )
            continue
        owed = (
            evaluate_count(game, game.players[seat], per_seat)
            if per_seat is not None else count
        )
        if owed <= 0:
            # CR 608.2's "as much as possible": a seat that owes none is not
            # asked, rather than being handed a prompt with no answer.
            continue
        if len(game._sacrifice_candidate_indices(
            game.players[seat], described, exclude
        )) < owed:
            # The printed count is indivisible: a player with one of the two
            # Swamps sacrifices neither, and the "if you can't" branch behind
            # this step is what the card says happens instead.
            could_pay = False
            continue
        game.arm_forced_sacrifice(
            seat, owed,
            filter=described,
            exclude=exclude,
            reason=context.card.name,
            # "If you sacrifice a **snow** Forest this way, …" (Gargantuan
            # Gorilla). What went, recorded as it goes — the branch that reads
            # it runs after this, and by then the permanent is a card in a
            # graveyard and a different object (CR 400.7, CR 608.2h). The
            # scratchpad is the resolution's own, so a step of some other
            # effect cannot see it, and `_run`'s `run_resumable` is what carries
            # the reading step across an interactive seat's prompt.
            record=context.results,
        )
    context.results["sacrificed_this_way"] = could_pay
    return True, "resolved"


@effect_handler("rebalance_lands")
def rebalance_lands(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Natural Balance's whole paragraph.

    "Each player who controls six or more lands chooses five lands they control
    and sacrifices the rest. Each player who controls four or fewer lands may
    search their library for up to X basic land cards and put them onto the
    battlefield, where X is five minus the number of lands they control. Then
    each player who searched their library this way shuffles."

    Two halves and one number. A seat over the target sacrifices down to it; a
    seat under it may tutor up towards it; a seat *on* it is in neither
    sentence, which is why the memberships are read rather than a difference
    being taken.

    **Both memberships are read off the same board, before anything moves**, and
    that is a rules answer rather than a convenience. The sets are disjoint —
    a seat that sacrifices down to the target has five lands and can never be in
    the "four or fewer" half — and one player's sacrifices change nobody else's
    count, so a board read after the first sentence would give the same answer.
    Reading it once says so; reading it twice would leave the question of what
    an intervening replacement effect did, which the card does not ask.

    Every decision is a prompt of the seat that owes it, queued through the
    standing machinery: `arm_forced_sacrifice` for the removals, the ordinary
    library search for the tutor. Nothing here is a new mechanism — which is the
    point, because "chooses N and sacrifices the rest" and "search for up to N
    basic land cards" are what those two prompts already are.
    """
    keep = int(instruction.payload.get("keep", 5))
    counts = [
        sum(
            1 for perm in game.controlled_by(seat)
            if perm.has_type("land")
        )
        for seat in range(len(game.players))
    ]
    over = [(seat, held) for seat, held in enumerate(counts) if held > keep]
    under = [(seat, held) for seat, held in enumerate(counts) if held < keep]
    if not over and not under:
        game.log.append(
            f"{context.card.name}: every player already controls {keep} lands"
        )
        return True, "resolved"
    for seat, held in over:
        game.arm_forced_sacrifice(
            seat, held - keep,
            filter={"card_types": ("land",)},
            reason=context.card.name if context.card is not None else "Rebalance",
        )
    for seat, held in under:
        # "**may** search their library for **up to** X basic land cards": an
        # offer with a ceiling, which is what `up_to` on the search prompt means
        # — a seat may find fewer, none included (CR 701.23b), and declining is
        # the fail-to-find every search already answers.
        #
        # The searching seat is its own chooser and its own zone owner, so no
        # seat key rides the prompt; that is the ordinary case the flow
        # defaults to, and it is what makes "their library" every player's own.
        game.arm_pending_choice(
            "search_library", seat,
            count=keep - held,
            card_type="land",
            zones=("library",),
            restrictions={"supertypes": ("basic",)},
            destination="battlefield",
            # One slot per find, all to the same place — the shape a counted
            # search whose finds share a destination already takes.
            destinations=["battlefield"] * (keep - held),
            tapped=[False] * (keep - held),
            card_name=context.card.name if context.card is not None else "",
            enters_tapped=False,
            untap_found_if=None,
            up_to=True,
            reveal=False,
            # **No record.** Every other search hands over the resolution's
            # scratchpad so a later sentence can name what it found; this
            # paragraph has no later sentence, and the scratchpad is one dict
            # shared by every seat this instruction armed — so a record here
            # would be several players' finds in one channel, which is the
            # two-value-shapes hazard rather than a feature.
        )
    if over:
        game.log.append(
            f"{context.card.name}: "
            + ", ".join(
                f"{game.players[seat].name} sacrifices {held - keep} land(s)"
                for seat, held in over
            )
        )
    if under:
        game.log.append(
            f"{context.card.name}: "
            + ", ".join(
                f"{game.players[seat].name} may search for {keep - held} basic land(s)"
                for seat, held in under
            )
        )
    return True, "pending_rebalance_lands"


def keep_slots_sized(slots, fewest: int) -> list[dict]:
    """*slots* with every keep that is sized by the table's minimum given that
    number.

    "…a number of permanents they control equal to the number of permanents
    controlled by the player who controls the fewest" (Balancing Act) prints
    no count: the lowering writes the word ``"fewest"`` where a printed keep
    writes its number, and this is the one place the word becomes one — the
    handler below with the minimum it measured, and the census of keep prompts
    with a minimum it states, so both arm the prompt the same way.
    """
    return [
        {**slot, "count": int(fewest)} if slot.get("count") == "fewest" else slot
        for slot in (slots or ())
    ]


@effect_handler("keep_chosen_sacrifice_rest")
def keep_chosen_sacrifice_rest(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player chooses from among the permanents they control an artifact,
    a creature, an enchantment, and a land, then sacrifices the rest."
    (Cataclysm.) "Each player chooses five lands they control and sacrifices the
    rest." (Limited Resources' entry trigger.)

    One prompt per seat, over that seat's own board, armed through the standing
    ``keep_permanents`` machinery: the answer is the keeps and the prompt's own
    resolver takes the complement, because "the rest" is not a set anything can
    name until the keeps are known.

    ``who`` is the same vocabulary ``sacrifice_matching_permanent`` reads and it
    is read the same way — absent means the effect's own controller (CR 109.5),
    "each player" is every living seat in seat order so the AI simulation stays
    seed-reproducible, and an unrecognized value **fails the instruction** rather
    than defaulting to the caster. Taking somebody else's board apart is the
    wrong direction to guess in, which is the reason that handler gives and the
    reason this one repeats it.

    **Nothing moves until the last seat has answered.** Cataclysm's ruling
    (2004-10-04): "After both players make choices, all the sacrifices are done
    simultaneously." The prompts share one batch (``Game.new_keep_batch``) and
    its last answer performs all of them as one event.

    This paragraph used to say "one player's sacrifices cannot change another's
    board, so re-reading per seat would give the same answer", and each prompt
    sacrificed as it was answered on the strength of it. Both halves were
    wrong. A seat that gives up the Aura it stole a creature with has changed
    which creatures the other seat chooses among, and a seat that gives up
    Kormus Bell has changed whether the other's Swamps are creatures at all;
    and a permanent that watches things leave (Dingus Egg) is one event's
    witness, not one seat's.
    """
    payload = instruction.payload
    who = payload.get("who")
    caster_index = game.players.index(context.caster)
    if who is None:
        seats = [caster_index]
    elif who == "each_player":
        seats = [
            seat for seat, player in enumerate(game.players) if not player.lost
        ]
    elif who == "each_opponent":
        seats = list(game.opponents_of(caster_index))
    else:
        return False, f"no seat named {who!r} keeps and sacrifices"
    pool = dict(payload.get("pool") or {})
    slots = list(payload.get("slots") or ())
    if not slots:
        # A keep list the lowering refuses to build is a sentence that would
        # sacrifice the whole pool. Refused here too rather than performed,
        # because a handler improvising the card's most destructive reading is
        # exactly the silent failure this repo keeps finding.
        return False, "a keep-and-sacrifice keeps something"
    card_name = getattr(context.card, "name", "") or "Effect"
    # "…Return those lands to their owners' hands." (Planar Overlay.) Which
    # half of the choice moves, carried through to the prompt whose resolver
    # performs it; absent is this handler's own name, the chosen kept and the
    # rest sacrificed. The same per-seat arming either way, and the same batch:
    # "Return those lands to their owners' hands" is one sentence about every
    # player's choice, read once they have all made it.
    fate = payload.get("fate")
    if any(slot.get("count") == "fewest" for slot in slots):
        # "…a number of permanents they control equal to the number of
        # permanents controlled by **the player who controls the fewest**"
        # (Balancing Act). One number for the whole table, taken here before
        # any seat answers (CR 608.2h) and over the same candidates the prompt
        # offers, so "how many may I keep" and "which may I keep" are one
        # reading of the noun.
        held = {seat: game.keep_choice_candidates(seat, pool) for seat in seats}
        fewest = min((len(found) for found in held.values()), default=0)
        if fewest <= 0:
            # Somebody controls none, so nobody keeps any: the rest is the
            # whole pool, and with one legal answer nobody is asked. Gathered
            # before any leaves, and sacrificed in one event (CR 701.21a), as
            # the batch below sacrifices every seat's rest together.
            gone_ids = {
                permanent.permanent_id
                for permanent in game.sacrifice_permanents(
                    [permanent for seat in seats for permanent in held[seat]]
                )
            }
            for seat in seats:
                gone = [
                    permanent.card.name for permanent in held[seat]
                    if permanent.permanent_id in gone_ids
                ]
                if gone:
                    game.log.append(
                        f"{game.players[seat].name} sacrificed {', '.join(gone)} "
                        f"({card_name})"
                    )
            return True, "resolved"
        slots = keep_slots_sized(slots, fewest)
        # A seat already at the minimum keeps everything it has — no rest, no
        # decision, no prompt.
        seats = [seat for seat in seats if len(held[seat]) > fewest]
    batch = game.new_keep_batch()
    for seat in seats:
        game.arm_keep_permanents(
            seat, pool=pool, slots=slots, reason=card_name, fate=fate,
            batch=batch,
        )
    # Only now can a batch be complete: a seat nobody asks may have answered as
    # it was armed, with seats still to come behind it.
    batch["armed"] = True
    game.finish_keep_batch(batch)
    return True, "resolved"
