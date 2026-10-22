"""What an activation checks before it collects a single cost (CR 602.2a–b,
CR 602.5).

``_activate_onto_stack`` is arranged as CR 601.2h (through CR 602.2b) asks
and CR 733.1 makes cheap: every refusal first, then every payment, so a
refused activation has nothing to give back. These are its refusing steps
before the cost's own: the source and whether this seat may activate it
(``_activation_source``), which ability (``_chosen_activated_ability``), the
keyword a cost clause has the activator choose (``_announce_chosen_ability``
— the one record an activation writes before it is known to be legal, taken
back on a refusal), the division settled once the targets are named
(``_settled_activation_division``), and the window
(``_activation_window``): CR 602.5's prohibitions and caps, the {T} symbol's
refusals, and the gate over every part of the cost that is not mana.

Split out of ``activation.py`` at the 2,000-line cap, and composed onto
``Game`` with the other parts of ``AbilityActivationMixin``; each step is
moved out of ``_activate_onto_stack`` whole and called from it in its order.
"""

from __future__ import annotations

from ...activation_permissions import card_widens_activation
from ...activation_prohibitions import activation_prohibition
from ...activation_restrictions import x_zero_restriction_line
from ...activation_tallies import (
    activations_allowed_each_turn, at_activation_limit,
    printed_activation_caps,
)
from ...activation_zones import ability_functions_from
from ...cost_pickers import spec_is_a_cost
from ...divided_damage import (
    EVENLY, divided_description, divided_entry, division_refusal,
    stamped_entry,
)
from ...game_types import SimulationResult
from ...handlers._amounts import evaluate_count
from ...handlers._chosen import CHOSEN_ABILITY
from ...line_classification import LOYALTY_ANY_TIME_STATIC
from ...oracle import compile_card_oracle
from ...targeting import derive_activation_spec, usable_activated_abilities


def _stamped_divided_targets(game, entries):
    """CR 601.2d's announcement, with each chosen permanent resolved to its id.

    The cast path's cleaning step, for an ability. Both stamp the id **now**
    because an index is not an address: the battlefield renumbers the moment
    anything leaves it, so a slot carried from the announcement to the
    resolution can name a different permanent — and the bounds check downstream
    is satisfied by it, so the effect lands on the wrong object rather than
    fizzling (CR 400.7 is what gives the id its meaning).

    ``None`` for an announcement nobody made, which is what every ability but
    Serra's Hymn sends and what the handler reads as "no division".
    """
    if not entries:
        return None
    cleaned = []
    for entry in entries:
        seat, index, share = divided_entry(entry)
        if not (isinstance(seat, int) and 0 <= seat < len(game.players)):
            continue
        chosen = (
            game.permanent_at(game.players[seat], index)
            if index is not None else None
        )
        cleaned.append(stamped_entry(
            seat, index, share, None if chosen is None else chosen.permanent_id,
        ))
    return cleaned or None


class ActivationChecksMixin:
    def _activation_source(
        self, *, ability_index, controller_index, permanent_index,
        permanent_name, source_controller_index,
    ):
        """CR 602.1a/602.2a: the permanent whose ability is being activated,
        and whether this seat may activate it at all.

        Found on its controller's battlefield (``source_controller_index``
        names it when a permission lets another seat activate it — Ifh-Bíff
        Efreet), refused when the activator may not reach it
        (``activation_permissions``), when it has lost its abilities
        (``lost_abilities_refusal``: Titania's Song, CR 305.7), or when an
        ability it prints wants control since the turn began (Rocket Launcher).
        Its program is compiled through ``playable_card_of``, so a granted
        ability is in it.

        A step of ``_activate_onto_stack``, moved out of it whole and called
        from it in its place: "above" and "below" in its comments are places in
        the activation as that method runs it.

        Returns the refusal, or ``(controller, permanent, program)``.
        """
        controller = self.players[controller_index]
        # Ifh-Bíff Efreet: "Any player may activate this ability." The activator
        # (controller of the ability, payer of its cost) may differ from the
        # permanent's controller; source_controller_index names whose
        # battlefield holds the permanent.
        source_owner = (
            controller
            if source_controller_index is None
            else self.players[source_controller_index]
        )
        resolved = self._find_controlled_permanent(source_owner, permanent_name, permanent_index)
        if resolved is None:
            raise ValueError(f"Permanent not found: {permanent_name}")
        _, permanent = resolved
        # CR 602.1a: a permanent's abilities are its controller's to activate,
        # unless the card prints a permission that says otherwise. This is the
        # *reachability* half — may this seat touch this permanent at all —
        # asked of `engine/activation_permissions.py` rather than of two
        # substrings written out here, which is what it was. Which of the
        # permanent's abilities the seat may then activate is the per-ability
        # question below, read off that ability's own printed line.
        if source_owner is not controller and not card_widens_activation(
            permanent.effective_card
        ):
            details = f"{permanent.card.name}'s abilities can only be activated by its controller"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Loses all abilities" (Titania's Song) means the activated ones too.
        # Layer 6 removes keyword abilities, but an activated ability is read
        # from the compiled program rather than the ability channel, so removal
        # has to be enforced where activation is authorised. Without this the
        # card would be half-implemented: a Jayemdae Tome under Titania's Song
        # would lose nothing it visibly had and keep drawing cards.
        #
        # CR 305.7 at the same place, for the reason a player is owed: a land
        # whose subtype an effect *set* to basic land types loses the abilities
        # its rules text generated, and one with nothing left is refused here
        # by name ("…lost its abilities when its land type was set") rather
        # than by an index that names nothing. The rule itself is not enforced
        # here any more — the program compiled below is the land's *effective*
        # card, with its own text struck (``Permanent.effective_card``) — and
        # that is what lets an ability another effect **granted** the land
        # through, which this refusal used to take with the rest.
        #
        # It does not touch tapping for mana: that path is `tap_land_for_mana`,
        # which reads `effective_produced_mana` and already gives the land the
        # mana ability of its new type, which is 305.7's other half.
        #
        # Both asked of ``lost_abilities_refusal``, one predicate: the same one
        # every *list* of a permanent's abilities asks (``usable_abilities_of``),
        # so what is offered and what is refused here cannot differ. They were
        # two inline checks, and each list asked a different one or neither.
        details = self.lost_abilities_refusal(permanent, ability_index)
        if details is not None:
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # Through the seam rather than off the card directly: Conspicuous Snoop
        # has the activated abilities of whatever is on top of its controller's
        # library, and that is a grant no read of the permanent alone can see.
        program = compile_card_oracle(self.playable_card_of(permanent))

        # "Activate only if you've controlled this artifact continuously since
        # the beginning of your most recent turn" (Rocket Launcher). CR 302.6's
        # clause applied to an artifact, so it reuses the same marker rather
        # than inventing a second notion of "arrived too recently".
        for ability in program.activated_abilities:
            if ability.instruction is None:
                continue
            if not ability.instruction.payload.get("requires_control_since_turn_start"):
                continue
            if not self._controlled_since_turn_start(permanent):
                details = (
                    f"{permanent.card.name} has not been controlled continuously "
                    "since the beginning of your most recent turn"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
        return controller, permanent, program

    def _chosen_activated_ability(
        self, *, ability_index, permanent, program,
    ):
        """Which of the source's abilities is being activated (CR 602.2a).

        The one ``ability_index`` names among the abilities that function from
        the battlefield (CR 113.6), or else the first the permanent can begin
        to pay for in its current state. A permanent whose only implemented
        ability functions from another zone is refused naming that zone.

        A step of ``_activate_onto_stack``, moved out of it whole and called
        from it in its place: "above" and "below" in its comments are places in
        the activation as that method runs it.

        Returns the refusal, or ``ability``.
        """
        # Which of the card's abilities is being activated. An explicit
        # ability_index names one (Rock Hydra's {R} prevention vs its {R}{R}{R}
        # pump); otherwise the default is the first ability this permanent can
        # actually pay for *in its current state*, not simply the first printed.
        #
        # CR 107.5: "A permanent that's already tapped can't be tapped again to
        # pay the cost", so an ability costing {T} is simply not among the ones
        # a tapped permanent can begin to activate (CR 602.5). A card with both a {T}
        # ability and an untap ability — Basalt Monolith's "{T}: Add {C}{C}{C}"
        # plus "{3}: Untap this artifact" — therefore has exactly one payable
        # ability in each state, and choosing it needs no knowledge of which
        # card it is. This was `permanent.card.name == "Basalt Monolith"`, and
        # an identically-worded card under any other name tapped for mana once
        # and was then stuck tapped for good, its untap ability unreachable.
        # Through the shared reader, not a second copy of its predicate: this
        # list *is* the index the web layer and the AI address an ability by
        # (`activation_target_spec` narrows the same list), and it carries
        # CR 113.6's zone read — an ability that functions only from a hand
        # (cycling, Waker of Waves) is not among a permanent's, or a permanent
        # could pay a "Discard this card" cost it is in no position to pay.
        usable = usable_activated_abilities(program)
        if ability_index is not None:
            ability = usable[ability_index] if 0 <= ability_index < len(usable) else None
        else:
            # The fallback to the first usable ability keeps refusals specific:
            # a permanent whose only ability costs {T} still reports "already
            # tapped" from the cost check below, rather than the vaguer "no
            # implemented activated ability" a None here would produce.
            ability = next(
                (
                    item
                    for item in usable
                    if not (item.cost.requires_tap and permanent.tapped)
                ),
                None,
            ) or next(iter(usable), None)

        if ability is None or ability.instruction is None:
            # A lord's quoted grant used to arrive *here*, as a metadata flag
            # this branch turned back into a hand-written {B} payment and a
            # regeneration shield — reachable only when the permanent had no
            # ability of its own, so a Zombie with a printed activated ability
            # could never use the one Zombie Master gave it. It is now a line on
            # the derived grant channel, folded into `effective_card` by
            # `playable_card_of` above, so it is in `usable` like any other.
            #
            # A permanent whose only implemented ability functions from another
            # zone (CR 113.6) is refused *naming that zone*, because the generic
            # message is the one a missing feature gives — and this one is a
            # rule being enforced. Cycling is the shape: a Sandbar Merfolk on
            # the battlefield has a compiled, supported, entirely correct
            # "{2}, Discard this card: Draw a card." that it may not activate
            # from where it is standing.
            elsewhere = next(
                (
                    item for item in program.activated_abilities
                    if item.supported and item.instruction is not None
                ),
                None,
            ) if not usable else None
            if elsewhere is not None:
                zone = ability_functions_from(elsewhere)
                details = (
                    f"{permanent.card.name}'s ability functions only "
                    f"from a {zone} (CR 113.6)"
                )
                self.log.append(details)
                return SimulationResult(
                    permanent.card.name, False, "unsupported", details
                )
            self.log.append(f"No implemented activated ability for {permanent.card.name}")
            return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")
        return ability

    def _announce_chosen_ability(
        self, permanent, ability, chosen_keyword, reversal_ledger=None
    ):
        """Record the keyword a "Choose A, B, or C" cost clause names, or refuse.

        Returns None when there is nothing to choose — every ability but
        Phyrexian Splicer's — so the activation path pays no attention to a card
        that prints no such clause.

        A word outside the printed list is **refused with nothing paid**
        (CR 602.2b): the options are the sentence's, not a catalog's, and
        quietly substituting one would move an ability the card never offered.
        A seat that names none takes the deterministic default below, which is
        what keeps AI and headless play unblocked — the same arrangement
        ``cost_permanent_index`` has for the other choice made at announcement.

        **And the record itself is registered for reversal**, because it is the
        one thing an activation writes before the activation is known to be
        legal. Every cost below checks its payability where it is announced and
        pays further down, so a refused activation has nothing to give back —
        except this, which has to be written *first*: the target gate
        enumerates "target creature with the chosen ability", and a word chosen
        after it would narrow nothing. CR 733.1, reached through CR 601.2 and
        CR 602.2b, reverses the entire action ("any payments already made are
        canceled"), so ``queue_permanent_ability`` takes the record back when
        the activation is refused.

        The reader that would see a leftover is
        ``handlers/_chosen._resolve_chosen_keyword``, which turns "with the
        chosen ability" into a keyword filter off exactly this key. That it is
        reached today only from a resolution — which always follows a fresh
        announcement — is a fact about which cards the pool prints, not a
        guarantee; a word nobody chose is state a reversed action left behind
        either way. The note that used to sit at the call site argued the record
        could not go stale because the ability costs {T}, so a second
        announcement needs an untap step in between. That is true of an
        activation that happened. A refusal pays no {T}.
        """
        options = tuple(getattr(ability.cost, "chosen_keyword_options", ()) or ())
        if not options:
            return None
        if chosen_keyword:
            word = str(chosen_keyword).strip().lower()
            if word not in options:
                return (
                    f"{permanent.card.name} offers "
                    + ", ".join(options)
                    + f", not {word!r}"
                )
        else:
            word = self._default_chosen_ability(permanent, options)
        if reversal_ledger is not None:
            reversal_ledger.append((
                permanent,
                CHOSEN_ABILITY in permanent.metadata,
                permanent.metadata.get(CHOSEN_ABILITY),
            ))
        permanent.metadata[CHOSEN_ABILITY] = word
        self.log.append(f"{permanent.card.name}: chose {word}")
        return None

    def _default_chosen_ability(self, permanent, options: tuple[str, ...]) -> str:
        """The stated policy for a seat that names no ability: the first printed
        option some creature on the battlefield actually has.

        A real answer rather than the first word, because the first word is a
        choice no player would make when the ability it names is on nobody's
        board — the move would then have no legal first target at all. The
        printed order breaks ties, which keeps it deterministic: the property
        the AI-simulation regressions depend on.
        """
        for option in options:
            if any(
                self._has_keyword(other, option)
                for other in self.all_permanents()
                if other.is_creature
            ):
                return option
        return options[0]

    def _settled_activation_division(
        self, *, ability, controller_index, divided_targets, permanent,
        target_permanent_ids, target_permanent_index, target_player_index,
        target_role_refs, x_value,
    ):
        """The announcement settled once its targets are named (CR 601.2d
        through CR 602.2b): the division resolved to ids before a cost can
        renumber a battlefield, an opponent's Flagbearer requirement asked of
        the whole announcement (Standard Bearer), and the division checked
        against the total the ability's own X defines.

        A step of ``_activate_onto_stack``, moved out of it whole and called
        from it in its place: "above" and "below" in its comments are places in
        the activation as that method runs it.

        Returns the refusal, or ``divided_targets``.
        """
        # CR 601.2d's announced division, resolved to ids **here** — which is
        # where CR 601.2c/601.2d put it, before a single cost is paid at
        # CR 601.2h.
        #
        # Not at the stack push below, which is the obvious place and the wrong
        # one: Serra's Hymn sacrifices itself to pay for this ability, so by the
        # time the item is built the announcement's battlefield indices name a
        # board one permanent shorter and every slot after the source has
        # shifted. The creature announced at index 1 was resolved to whatever
        # slid into it — which is nothing at all when it was the last — and the
        # shield went to the player alone with the card reporting success.
        divided_targets = _stamped_divided_targets(self, divided_targets)

        # CR 602.2b under a requirement an *opponent's permanent* prints about
        # this announcement: "While an opponent is choosing targets as part of
        # … activating an ability they control, that player must choose at
        # least one Flagbearer on the battlefield if able." (Standard Bearer.)
        # The whole announcement — ids, roles and the division together — after
        # the gate above has said each named target is legal and after the
        # one-legal-target default has named what it can, and before any cost
        # is paid. Free on every board with no such permanent on it.
        required_refusal = self.activation_target_requirement_refusal(
            controller_index, permanent, ability,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            target_role_refs=target_role_refs,
            divided_targets=divided_targets,
            x_value=int(x_value or 0),
        )
        if required_refusal is not None:
            self.log.append(required_refusal)
            return SimulationResult(
                permanent.card.name, False, "unsupported", required_refusal
            )

        # CR 601.2d itself, asked of an **ability** — the twin of the gate
        # ``queue_from_hand`` makes one file over, and it was missing here
        # entirely because Serra's Hymn is the pool's first ability to print a
        # division. Beside the target check above and before any cost is paid,
        # for that gate's stated reason: CR 601.2e returns the game to the
        # moment before an illegal proposal, and a division judged at
        # resolution would already have eaten the enchantment.
        #
        # The total is the ability's own X, which for these cards the *text*
        # defines rather than the activation announcing — the same number
        # ``legality._size_activation_x_targets`` gives the picker, read through
        # the same evaluator so what the browser offers and what this accepts
        # cannot disagree.
        ability_instruction = getattr(ability, "instruction", None)
        divided = divided_description(
            (ability_instruction,) if ability_instruction is not None else ()
        )
        if divided is not None:
            spec = dict(divided[1])
            payload_amount = divided[0].get("amount")
            total = payload_amount if isinstance(payload_amount, int) else 0
            counted = divided[0].get("x_from_count")
            if payload_amount == "x" and isinstance(counted, dict):
                total = max(0, evaluate_count(
                    self, self.players[controller_index], counted,
                    source=permanent,
                ))
            elif payload_amount == "x":
                total = int(x_value or 0)
            refusal = division_refusal(
                total, divided_targets or (),
                division=spec.get("division", EVENLY),
                max_targets=spec.get("max_targets"),
            )
            if refusal is not None:
                self.log.append(f"{permanent.card.name}: {refusal}")
                return SimulationResult(
                    permanent.card.name, False, "unsupported", refusal
                )
        return divided_targets

    def _activation_window(
        self, *, ability, controller_index, permanent, program, x_value,
    ):
        """CR 602.5, and the costs counted before any is collected (CR 601.2f
        through CR 602.2b).

        How many counters a removal cost takes (counted here, removed with the
        other costs), the loyalty window (CR 606.3, 606.6), the
        activation-prohibition table, a targeting ban, an owner-only line, "X
        can't be 0", the per-turn caps, the {T} symbol's two refusals (CR
        602.5a, 107.5), and ``unpayable_activation_cost`` — the one gate over
        every part of the cost that is not mana. Nothing is paid here.

        A step of ``_activate_onto_stack``, moved out of it whole and called
        from it in its place: "above" and "below" in its comments are places in
        the activation as that method runs it.

        Returns the refusal, or ``(ability_lower, activation_caps,
        counters_removed_for_cost, loyalty_delta)``.
        """
        # "Remove a <kind> counter from this creature" (Scavenging Ghoul; the
        # ability Life Matrix grants) - CR 602.1a: a counter removal is an
        # activation cost, so it is checked and charged before the ability goes
        # on the stack, and an ability whose source has none may not be
        # activated at all.
        #
        # This was a substring test for the words "remove a **corpse** counter
        # from this creature" beside a check that the ability regenerated. Both
        # halves were the first card that reached it: the counter's kind is
        # payload (CR 122.1's kinds are open), and what the ability *does* is
        # not the cost's business. An ability granted with any other counter's
        # word paid nothing and could be activated for ever.
        # **Counted here, charged with the other costs below.** This block used
        # to take the counters off at this point, which is *above* CR 602.5's
        # timing gate -- so Trade Caravan, activated outside an opponent's
        # upkeep, was refused with two currency counters already gone. CR 602.2b
        # reverses an activation that turns out to be illegal, and the rest of
        # this function is arranged that way already: every other cost checks
        # its payability here and pays further down.
        counters_removed_for_cost = 0
        # "{2}, Remove a +1/+1 counter from **a creature you control**" (Spike
        # Rogue). The same cost off a permanent the payer picks, collected
        # further down with the other chosen costs — where `cost_permanent_ids`
        # is read — rather than here, because the candidate list is a board
        # scan and not a look at the source. This branch stays the
        # self-referring reading and nothing else.
        if ability.cost.remove_counter and ability.cost.remove_counter_filter is None:
            from ...named_counters import counters_on

            kind = ability.cost.remove_counter
            held = counters_on(permanent, kind)
            wanted = ability.cost.remove_counter_count
            if wanted == "any":
                # "Remove **any number of** charge counters from this artifact"
                # (the Mana Batteries). The payer announces how many as the
                # ability is activated (CR 601.2b), through the same channel
                # every other announced number travels on; a seat that announces
                # nothing removes every counter, which is deterministic and the
                # only answer that is never worse on a card whose effect scales
                # with the count. Zero is a legal payment — "any number"
                # includes none — so this half can never make the ability
                # unactivatable.
                counters_removed_for_cost = (
                    held if x_value is None else max(0, min(held, int(x_value)))
                )
            elif wanted == "x":
                # "Remove **X** charge counters from this artifact" (Kyren Toy,
                # Mercadian Lift). CR 107.3a: an X in an activation cost that
                # the card does not define is announced by the activator, as
                # part of activating. The counters are the cost that X sizes --
                # so unlike "any number of" above, an X larger than the
                # permanent holds is an announcement that **cannot be paid**
                # (CR 601.2h, reached through CR 602.2b) and the activation is
                # refused with nothing spent rather than clamped down to what is
                # there. Clamping would let a player announce five on a
                # two-counter artifact and be charged two, which is a cheaper
                # card than the one printed.
                #
                # A caller that named no X gets **zero**, which is this engine's
                # stated default for a headless or AI seat rather than a rule:
                # CR 107.3a makes announcing mandatory, and no rule turns an
                # omission into a number. Zero is a legal announcement here
                # because removing zero counters is always payable (CR 601.2h
                # forbids only what cannot be done) -- and it is the whole
                # difference from the branch above, where naming nothing removes
                # every counter.
                # An X the permanent cannot cover is refused by the cost gate
                # below (``unpayable_activation_cost``), with nothing spent.
                counters_removed_for_cost = max(0, int(x_value or 0))
            elif wanted == "all":
                # "Remove **all** elixir counters from this artifact" (Essence
                # Bottle, Torture Chamber). Every one of them and no choice to
                # make, which is what separates it from "any number" above: an
                # announced X narrows that and must not narrow this. Payable
                # with none on the permanent — removing all of zero counters
                # removes zero, and CR 601.2h only forbids what cannot be done
                # — so this half never makes the ability unactivatable, and the
                # effect behind it reads the zero it really removed.
                counters_removed_for_cost = held
            else:
                # Too few on the source is the cost gate's refusal below.
                counters_removed_for_cost = int(wanted)

        # Per-ability timing restrictions are scoped to the *selected* ability's
        # own clause, not the whole card. Rock Hydra's "Activate only during your
        # upkeep" sits on its {R}{R}{R} pump line only, so its {R} prevention
        # ability (ability_index 0) must stay usable at any time.
        ability_lower = (ability.source_line or permanent.effective_card.oracle_text).lower()

        # CR 606.3: a loyalty ability may be activated only during a main phase
        # of its controller's own turn with the stack empty — unless the
        # permanent itself widens the window ("You may activate loyalty
        # abilities of ~ on any player's turn any time you could cast an
        # instant", Teferi, Master of Time). The once-per-permanent-per-turn
        # half of the rule is not part of that static and is never widened.
        # CR 606.6: a negative cost needs at least that many counters on it.
        loyalty_delta = 0
        if ability.cost.is_loyalty:
            any_time = LOYALTY_ANY_TIME_STATIC in program.static_lines
            if not any_time and not (
                self.active_player_index == controller_index
                and self.current_turn_phase in ("precombat_main", "postcombat_main")
                and not self.stack
            ):
                details = (
                    f"{permanent.card.name}'s loyalty abilities can only be activated "
                    "during a main phase of your turn with the stack empty (CR 606.3)"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            if permanent.metadata.get("loyalty_ability_used_turn") == self.turn:
                details = (
                    f"a loyalty ability of {permanent.card.name} has already been "
                    "activated this turn (CR 606.3)"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            loyalty_delta = (
                ability.cost.loyalty_x_sign * int(x_value or 0)
                if ability.cost.loyalty_x_sign is not None
                else ability.cost.loyalty
            )
            if loyalty_delta < 0 and int(permanent.metadata.get("loyalty_counters", 0)) < -loyalty_delta:
                details = (
                    f"{permanent.card.name} does not have enough loyalty counters "
                    "to pay that cost (CR 606.6)"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        # **One question, asked of one table** (``engine/activation_
        # prohibitions.py``, CR 602.5): the board-wide bans (Cursed Totem,
        # Null Rod, City of Solitude, Hand to Hand, Katabatic Winds), the
        # turn-long records (Interdict, Abeyance), the Aura clauses (Faith's
        # Fetters, Volrath's Curse), and the printed "Activate only …" and
        # "…may activate this ability" on this line
        # (``engine/activation_restrictions.py``, ``activation_permissions.py``).
        # They were ten inline checks from here down, each logging its own
        # sentence. They are the table's rows now, in the order they stood
        # here and with the words they logged, because this door was the only
        # reader that asked all ten: the AI's chooser asked three, the wire
        # none, and an ability activated from a hand or a graveyard — which
        # never comes down this road — asked one at most.
        prohibited = activation_prohibition(
            self, controller_index, permanent, ability
        )
        if prohibited is not None:
            self.log.append(prohibited.details)
            return SimulationResult(
                permanent.card.name, False, "unsupported", prohibited.details
            )

        # "…players and permanents can't be the targets of spells or activated
        # abilities." (Peace Talks.) CR 602.2b sends an activation through
        # CR 601.2c, so an ability that must choose a target and has none legal
        # cannot be begun — the refusal lands here, with nothing paid.
        #
        # Asked of the *spec* rather than left to ``activation_target_refusal``
        # for the reason the cast gate is: that one goes through
        # ``_enumerate_targets`` and so already refuses an ability with a
        # mandatory **object** target, but an ability that may aim at a face
        # ("deals 1 damage to any target", Rod of Ruin) names no permanent and
        # walked straight through.
        if self.targeting_bans:
            ban_spec = derive_activation_spec(ability)
            # A cost picker is not a target (CR 601.2b vs 601.2c): Atog eating
            # an artifact under Peace Talks targets nothing, and neither does
            # a creature tapped to pay Llanowar Behemoth.
            if ban_spec is not None and not spec_is_a_cost(ban_spec) and ban_spec.get(
                "kind"
            ) not in (
                "none", "modal", "hand_card", "stack", "spell_or_permanent",
            ):
                source_name = self.targeting_bans[-1].get("source_name", "an effect")
                details = (
                    f"{permanent.card.name} has no legal target: nothing can be "
                    f"targeted ({source_name})"
                )
                self.log.append(details)
                return SimulationResult(
                    permanent.card.name, False, "unsupported", details
                )

        # "Only this creatures owner may activate this ability." (Personal
        # Incarnation.) The owner — not whoever controls it — is the only legal
        # activator, so a thief who stole it with Control Magic can't use it.
        if (
            "only this creatures owner may activate this ability" in ability_lower
            and self.owner_index_of(permanent) != controller_index
        ):
            details = f"only {permanent.card.name}'s owner may activate this ability"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "X can't be 0." (Aladdin's Lamp, Helm of Obedience.) Through the
        # module that owns the sentence rather than spelled here: the grammar
        # consumes the clause on that module's say-so, so a reading here of its
        # own would be the second copy that lets the claim and the enforcement
        # disagree about the same words.
        if any(
            x_zero_restriction_line(sentence)
            for sentence in ability_lower.split(".")
        ) and not x_value:
            details = f"{permanent.card.name}: X can't be 0"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # The timing half of "Activate only during your turn and only once each
        # turn" is in the restriction table above; the *count* half is
        # per-permanent state rather than a property of the game, so the tally
        # stays here with the state it reads. **How limited a line is, is the
        # table's answer**, not a substring test beside it: the bare clause
        # (Dream Coat), the tails, and Vampire Bats' "no more than twice" all
        # come back from one reader, and a reader here spelling the words itself
        # is the second representation that lets a refusal and a tally disagree
        # about the same sentence.
        # **Whether** the line is capped is a fact about the sentence;
        # **how much** it is capped by can be a fact about the board (Withering
        # Wisps counts snow Swamps), so the tally below asks the first question
        # and the refusal here asks the second. One text-only reader answering
        # both would have to call a counted cap "no cap", which is the value
        # that stops the tally.
        activation_caps = printed_activation_caps(ability_lower)
        if at_activation_limit(self, controller_index, permanent, ability_lower):
            details = (
                f"{permanent.card.name}'s ability can only be activated "
                f"{activations_allowed_each_turn(ability_lower, self, controller_index, permanent)}"
                f" time(s) each turn"
            )
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # The {T} symbol's two refusals, asked **here, before a single cost is
        # collected** — CR 602.5a (a creature's {T} ability can't be activated
        # unless it has been controlled since its controller's most recent turn
        # began) and CR 107.5 (a tapped permanent can't be tapped again to pay
        # the cost). Both are questions about the board as the activation is
        # proposed, and neither depends on anything a cost below decides.
        #
        # They sat underneath the mana payment, so an activation they refused
        # had already spent its mana: Time Elemental, summoning sick, went
        # 30 → 26 in the pool and stayed un-activated. CR 733.1 (reached through
        # CR 601.2e and CR 602.2b) reverses an illegal activation outright —
        # "any payments already made are canceled" — and this engine's whole
        # arrangement is the cheaper equivalent: every check first, then every
        # payment, so a refusal has nothing to give back. Measured over the
        # pool before the move: 174 abilities paid mana into a summoning-sick
        # refusal and 361 into an already-tapped one (one of them, City of
        # Shadows, exiled a creature as well).
        if ability.cost.requires_tap:
            if self._is_summoning_sick(permanent):
                details = f"{permanent.card.name} has summoning sickness"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            if permanent.tapped:
                details = f"{permanent.card.name} is already tapped"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        # **Can the cost be paid at all** (CR 601.2h via 602.2b; CR 118.3) —
        # one question over every resource a cost spends that is not mana,
        # asked of one gate (``unpayable_activation_cost``) before a single
        # cost is collected. The blocks below used to each refuse their own
        # shortfall as they were reached; they now pick and pay, and refuse
        # only what a *named* payment makes illegal. The AI's chooser asks the
        # same gate before it proposes an activation, so what it proposes and
        # what this door accepts cannot be two answers.
        unpayable = self.unpayable_activation_cost(
            controller_index, permanent, ability, x_value=x_value,
        )
        if unpayable is not None:
            self.log.append(unpayable)
            return SimulationResult(permanent.card.name, False, "unsupported", unpayable)
        return (
            ability_lower, activation_caps, counters_removed_for_cost,
            loyalty_delta,
        )
