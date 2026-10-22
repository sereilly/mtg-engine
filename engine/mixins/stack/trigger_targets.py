"""The choices a triggered ability makes as it is put on the stack: its mode
and its targets (CR 603.3c–d, through CR 601.2b–c).

``_choose_trigger_mode`` and ``_choose_trigger_targets`` are asked by
``_stack_push`` for every triggered object. What a trigger may target is
``_trigger_target_candidates`` — the picker's own list, narrowed by a printed
controller word (``_CONTROLLER_SPEC_FLAGS``) and announced by the seat the
card names (``_trigger_chooser_seat``) — and an interactive seat is asked
through ``_arm_trigger_target_choice``. A permanent's entry trigger whose
target was named as the permanent was cast is held to what the trigger itself
could choose (``cast_announcement_fault``, CR 603.3d).

Split out of ``resolution.py`` at the 2,000-line cap, and composed onto
``Game`` with the other parts of ``StackResolutionMixin``, directly after it.
"""

from __future__ import annotations

from ...game_types import StackItem
from ...oracle import OracleInstruction
from ...modal_triggers import modal_trigger_modes
# Both owned by ``engine/targeting.py``: two callers ask whether a compiled
# program announced a target — this picker (CR 603.3d) and the ``may``
# handler deciding whether an offer may rebind the target its own trigger
# announced — and a second copy of the word list is how the two would come
# to disagree about what counts as an announcement.
from ...targeting import ANNOUNCED_PLAYER_WORDS, announces_a_target


#: How a printed controller narrowing reaches the target spec. A key here is a
#: narrowing `legality._enumerate_targets` performs; a controller word absent
#: from it is one the enumerator cannot answer, and
#: `_choose_trigger_targets` declines rather than offering a wider list than
#: the card prints.
_CONTROLLER_SPEC_FLAGS = {
    "you": "own_only",
    "opponent": "opponent_only",
    "defending_player": "defending_player_only",
    # "...target creature or planeswalker **that player** controls" (Chandra's
    # Incinerator); "destroy up to one target artifact or enchantment **that
    # player** controls" (Feline Sovereign). A seat the *event* picked, which
    # `_enumerate_targets` narrows on exactly as it narrows the defending
    # player's — given the seat, which the fire site froze into the trigger's
    # context (CR 603.10) and `_that_player_seat` below reads back.
    #
    # Absent from this table the picker declined the ability entirely, so the
    # target was never announced and the handler fell through to "the first
    # permanent on the default opponent's battlefield that matches". At two
    # seats that is a legal permanent nobody chose; at three it is the wrong
    # board, where the printed narrowing then matches nothing and the ability
    # silently does nothing at all.
    "that_player": "that_player_only",
}


def _target_filter_controller(payload) -> str | None:
    """The ``controller`` word of an instruction's printed target phrase.

    Walked rather than read off one key because the phrase is carried in two
    shapes: a destroy lifts it to the payload's top level, while a damage
    instruction keeps it under ``targets.filter`` — and a ``may`` or a
    ``sequence`` wraps either of them. One walk rather than a list of the
    kinds, for the reason every registry in this engine gives.
    """
    if isinstance(payload, dict):
        described = payload.get("filter")
        if isinstance(described, dict) and described.get("controller"):
            return described["controller"]
        if payload.get("controller"):
            return payload["controller"]
        for value in payload.values():
            found = _target_filter_controller(value)
            if found is not None:
                return found
        return None
    if isinstance(payload, (list, tuple)):
        for entry in payload:
            found = _target_filter_controller(entry)
            if found is not None:
                return found
        return None
    inner = getattr(payload, "payload", None)
    return None if inner is None else _target_filter_controller(inner)


def _controller_narrowing_is_in(spec: dict, instruction) -> bool:
    """Whether *spec* carries the controller narrowing *instruction* prints."""
    controller = _target_filter_controller(getattr(instruction, "payload", None))
    if controller is None:
        return True
    # "...put a rust counter on each artifact **target opponent** controls."
    # (Corrosion.) Here the controller word *is* the announcement rather than a
    # narrowing of a list of objects: the spec picks a seat, the enumerator
    # offers seats, and the sweep over that seat's permanents is the
    # resolution's own work (CR 611.2c fixes the set as the ability resolves).
    # Read as a narrowing it looked for a spec flag no seat picker carries, and
    # so declined the one card the pronoun is printed on.
    if controller in ANNOUNCED_PLAYER_WORDS and spec.get("kind") == "player":
        return True
    flag = _CONTROLLER_SPEC_FLAGS.get(controller)
    return bool(flag and spec.get(flag))


def _names_a_graveyard_target(spec: dict | None, ability_text: str | None) -> bool:
    """Whether a triggered ability with this *spec* and printed line chooses a
    **card in a graveyard** as its target (CR 115.1d, CR 603.3d).

    Two pieces of evidence, the pair ``engine/stack_targets.py`` reads every
    announcement by: the compiled program says the choice is a graveyard card,
    and the printed words say "target" about it. The second is what separates
    Gravedigger ("you may return **target** creature card from your graveyard
    to your hand") from Harvest Wurm ("sacrifice it unless you return a basic
    land card from your graveyard to your hand") and from Animate Dead's entry
    sentence: those derive the same spec and choose nothing as they are put on
    the stack — the card is found while the effect is applied (CR 608.2d), and
    with none to find the ability must still resolve, where CR 603.3d would
    have taken a targeted one off the stack.
    """
    from ...stack_targets import names_a_target
    from ...targeting import GRAVEYARD_TARGET_KIND

    return bool(
        spec and spec.get("kind") == GRAVEYARD_TARGET_KIND
        and names_a_target(ability_text)
    )


def _target_is_up_to(payload) -> bool:
    """Whether an instruction's printed target is "**up to** one target …".

    Walked for :func:`_target_filter_controller`'s reason: the ``targets``
    description sits under a ``sequence``'s steps or a ``may``'s body as often
    as at the top. CR 601.2c lets such an announcement name **zero** targets,
    so "no legal target" is a choice that can be made rather than CR 603.3d's
    "no legal choices can be made" — Gilded Drake's "exchange control of this
    creature and up to one target creature an opponent controls" against an
    empty board still resolves, and its "if you don't or can't make an
    exchange, sacrifice this creature" is the whole point of that.
    """
    if isinstance(payload, dict):
        targets = payload.get("targets")
        if isinstance(targets, dict) and targets.get("quantifier") == "up_to":
            return True
        return any(_target_is_up_to(value) for value in payload.values())
    if isinstance(payload, (list, tuple)):
        return any(_target_is_up_to(entry) for entry in payload)
    inner = getattr(payload, "payload", None)
    return False if inner is None else _target_is_up_to(inner)


class TriggerTargetsMixin:
    def _choose_trigger_mode(
        self, item: StackItem, *, targets_already_chosen: bool = False
    ) -> None:
        """Choose *item*'s mode and that mode's targets, as it goes on the
        stack (CR 700.2b / CR 603.3c-d).

        The rule is explicit about **when**: the modes of a modal triggered
        ability are chosen "as part of putting that ability on the stack", and
        CR 603.3d then routes the rest through CR 601.2c, which is where the
        targets are chosen. So the two decisions are one decision, made here,
        at the one moment they are allowed — and not, as this engine did until
        now, at resolution, where nothing collects a target and a targeted mode
        would run against a target nobody picked.

        CR 700.2b's other half is the empty case: "If no mode is chosen, the
        ability is removed from the stack." A mode with no legal target can't
        be chosen, so an ability whose every mode is in that state never
        resolves — it is taken back off the stack here rather than resolving
        into a no-op, which is a different observable game state (nothing
        responds to it, and nothing counts it as having resolved).

        The offered list is ``legality.trigger_mode_options``, which is also
        what decides the empty case one line above: the gate and the picker are
        one call, not two tables.
        """
        instruction = item.ability_instruction
        if not modal_trigger_modes(instruction):
            return
        options = self.trigger_mode_options(
            item.caster_index, item.card, instruction, item.source_permanent,
        )
        if not options:
            self.stack = [existing for existing in self.stack if existing is not item]
            self.log.append(
                f"{item.card.name}'s triggered ability was removed from the stack: "
                "no mode could be chosen (700.2b)"
            )
            return
        self.arm_pending_choice(
            "mode_choice", item.caster_index,
            card_name=item.card.name,
            labels=[option["label"] for option in options],
            _options=tuple(options),
            _trigger_item=item,
            # An object announced with its targets already made — a copy
            # (CR 707.10), or an activated modal ability (CR 602.2b) — keeps
            # them, so the mode picker must not ask again. Same rule as the twin
            # flag one method up: asking again replaces a choice a player has
            # made with one they have not.
            #
            # Dwarven Armorer used to be the card that showed why, and no longer
            # reaches here at all: "a +0/+1 counter **or** a +1/+0 counter" is
            # not modal (CR 700.2 needs a bulleted list), so it is chosen while
            # the effect is applied (CR 608.2d) — see
            # ``modal_triggers.MODAL_HEAD_KEY``. A printed modal *activated*
            # ability is rewritten one ability per bullet before it compiles,
            # so the flag's live reader today is the copy.
            _keep_targets=targets_already_chosen,
        )

    #: Object target kinds :meth:`_choose_trigger_targets` picks for.
    #: Permanents on the battlefield: the kinds whose printed noun phrase can
    #: *narrow* ("target artifact defending player controls"), so a fire site
    #: that names one by position rather than by choice is naming something the
    #: card may not permit. A spell on the stack reaches the resolution through
    #: its own path and is left exactly as it was.
    #:
    #: **A card in a graveyard is chosen too**, and is not in this set because
    #: its kind alone does not say it is a target: ``_names_a_graveyard_target``
    #: asks the printed line as well (Harvest Wurm derives the same spec and
    #: targets nothing). This note said such a card was "left exactly as it
    #: was", which was eighteen triggered abilities (fourteen of them entry
    #: triggers) nobody was ever asked about — Gravedigger took the first
    #: creature card in the pile for a player who could see three — and no
    #: list to hold the cast's announcement to.
    _CHOOSABLE_TRIGGER_TARGET_KINDS = frozenset({
        "permanent", "creature", "artifact", "enchantment", "land",
        "planeswalker",
    })

    #: ...and the kinds whose candidates include a **player's face**. The note
    #: above used to say a player "is left exactly as it was", and that was the
    #: whole gap: a trigger printing "target opponent" announced nothing, so the
    #: resolution fell through to ``_default_opposing_seat`` — the first living
    #: opponent. Right in a two-player game by coincidence, because there is
    #: only one of those; unchosen at three seats, where CR 601.2c says the
    #: ability's controller picks and the engine picked for them.
    #:
    #: ``divided`` is not here, because it is not a player kind: see
    #: :attr:`_CHOOSABLE_TRIGGER_DIVIDED_KINDS` below.
    _CHOOSABLE_TRIGGER_PLAYER_KINDS = frozenset({
        "player", "player_or_planeswalker", "any",
    })

    #: ...and a **spell on the stack**. "When this creature enters, counter
    #: target spell" (Mystic Snake) is the pool's first trigger to print one,
    #: and the note two sets above — "a spell on the stack … reach[es] the
    #: resolution through [its] own path" — was true of every *counterspell*
    #: and of no trigger: this one reached the stack naming nothing, and its
    #: handler countered whatever was on top, the Snake's own controller's
    #: spell included. Chosen as it is put on the stack like every other
    #: target (CR 603.3d), out of ``_enumerate_stack_targets``, the list the
    #: cast picker and ``cast_stack_target_refusal`` read; with no spell to
    #: name, the ability is removed.
    _CHOOSABLE_TRIGGER_STACK_KINDS = frozenset({"stack"})

    #: ...and a **division** (CR 601.2d, which CR 603.3d applies to a
    #: triggered ability as it is put on the stack): "When this creature dies,
    #: distribute three -1/-1 counters among one, two, or three target
    #: creatures" (Shambling Swarm, the pool's first trigger to print one). A
    #: set of targets with an assignment attached, so it is this prompt with a
    #: ``division_total`` beside the ``max_targets`` a several-target trigger
    #: already carries, and the answer is ``permanent_ids`` with ``amounts``.
    #:
    #: Only what that answer can say (:meth:`_trigger_division_is_announceable`):
    #: permanents, a printed total, and a division the announcer chooses or the
    #: game splits evenly. A player's face, a card-dictated share or an X the
    #: announcement would have to choose declines — and an ability that
    #: declines announces nothing, which
    #: ``tests/engine/test_stack_targets.py``'s census then names.
    _CHOOSABLE_TRIGGER_DIVIDED_KINDS = frozenset({"divided"})

    @staticmethod
    def _trigger_division_is_announceable(spec: dict) -> bool:
        """Whether a ``divided`` *spec* is one the ``trigger_target`` prompt
        can announce (see :attr:`_CHOOSABLE_TRIGGER_DIVIDED_KINDS`)."""
        from ...divided_damage import CHOSEN, EVENLY
        from ...targeting import spec_offers_a_player

        return (
            spec.get("division", EVENLY) in (CHOSEN, EVENLY)
            and not spec_offers_a_player(spec)
            and isinstance(spec.get("division_total"), int)
            and not isinstance(spec.get("division_total"), bool)
        )

    def _choose_trigger_targets(self, item: StackItem) -> None:
        """Choose *item*'s target as it goes on the stack (CR 603.3d/601.2c).

        The non-modal twin of :meth:`_choose_trigger_mode`, and it exists for
        the same reason at the same moment: a triggered ability chooses its
        targets as it is put on the stack, not when it resolves.

        Most fire sites in this engine already name the object their event was
        about — "destroy **that Wall**" (Battering Ram) is bound by the block
        that fired it, and CR 603.3d has nothing to choose. This is for the
        ability whose printed noun phrase is a *choice* the event does not
        make: Floral Spuzzem's "target artifact defending player controls" is
        any of the defender's artifacts, and the fire site had been stamping
        the attacking creature's own slot into the target field — so the
        ability resolved against whatever permanent sat at that index on the
        *controller's* battlefield.

        Three ways out, all of them the safe direction:

        * the ability names no target — nothing to choose;
        * the fire site already bound one (``target_permanent_id`` for an
          object, ``target_player_index`` for a seat) — the event made
          the choice and CR 603.3d has none left to make;
        * no legal target exists — CR 603.3d removes the ability from the
          stack rather than resolving it into a no-op, which is the same rule
          :meth:`_choose_trigger_mode` applies to a mode that cannot be chosen.

        The candidates come from ``_enumerate_targets``, the one list the web
        picker is handed and the one list the answer is checked against.

        A **player** is chosen here on the same rule and through the same list,
        and it is the half this method did not have. What gates it is
        :func:`announces_a_target` rather than the spec alone: the spec comes from
        a kind table that answers "player" for a whole family of instructions,
        including the ones whose seat the firing event already fixed.
        """
        offer = self._trigger_target_candidates(item)
        if offer is None:
            # A target this picker does not choose — and one of those is a
            # card in a graveyard, which a trigger's handler finds for itself
            # as it resolves. Under "Cards in graveyards can't be the targets
            # of spells or abilities" (Ground Seal) such a trigger has no
            # legal target to be put on the stack with, which is CR 603.3d's
            # removal exactly as the arm below applies it to an empty list.
            # ``legality.sealed_graveyard_target_refusal`` is the one
            # predicate, asked again as the ability resolves (CR 608.2b).
            if self.sealed_graveyard_target_refusal(item) is not None:
                self.stack = [existing for existing in self.stack if existing is not item]
                self.log.append(
                    f"{item.card.name}'s triggered ability was removed from the stack: "
                    "it has no legal target (603.3d)"
                )
            return
        spec, chooser_index, candidates = offer
        self._arm_trigger_target_choice(item, spec, chooser_index, candidates)

    def cast_announcement_fault(self, item: StackItem) -> str | None:
        """Why the target *item* carries from its permanent spell's cast is
        **not** one this trigger could have chosen for itself (CR 603.3d), or
        None when the announcement stands.

        This engine names an entry trigger's target as the permanent is cast —
        a standing convention, measured and kept (ROADMAP, "Entry triggers are
        stack objects"). The rule chooses it here, as the trigger is put on the
        stack, so the honest reading of the convention is that the cast's
        announcement is a **pre-answer** to this choice: it has to be an answer
        the choice would have accepted. Nothing asked. The cast picker offered
        every permanent of the right type and no gate stood behind it (a
        permanent spell does not target, so CR 601.2c has nothing to refuse),
        which left the trigger's own legality — the one
        :meth:`_trigger_target_candidates` applies to a target it chooses
        itself — unasked of a target it was handed: Nekrataal destroyed a White
        Knight, sixteen shipped permanents acted on a creature with protection
        from their own colour or from creatures, and Hunting Drake ("target red
        or green creature") took any creature at all.

        Asked **now**, of the board as it is when the trigger is put on the
        stack, so it also answers everything that happened while the permanent
        spell waited to resolve: the named creature left, gained protection or
        changed sides, the named player gained shroud (Ivory Mask).

        It stands where the trigger has no choice this picker could make (a
        spell, a phrase the enumerator cannot narrow, a graveyard card its
        line does not call a target): there is no list to hold the
        announcement to, and it rides the object as it always has. A **target
        card in a graveyard** is held to its list like a permanent is.

        Two faults, told apart because only one of them is news to a player:

        * ``"illegal"`` — a target was named and the trigger cannot choose it;
        * ``"unnamed"`` — a seat was named alone for a trigger that can only
          target an **object** (``spec_offers_a_player`` says no). That announces nothing the trigger could choose (it is
          what the web route sends for a cast no picker ran in front of), so
          the trigger chooses rather than leaving its handler to scan that
          seat's board for a target nobody picked.
        """
        offer = self._trigger_target_candidates(item, announced=True)
        if offer is None:
            return None
        spec, _chooser, candidates = offer
        if _names_a_graveyard_target(spec, item.ability_text):
            # **A card in a graveyard**, named by pile and slot — the two
            # fields a battlefield target reads as a seat and a slot there.
            # The slot is the one the permanent spell's own stamp re-located
            # as it resolved (``_run_stack_item_resolution``), so a card that
            # left the pile while the spell waited arrives here as no slot at
            # all: nothing is named any more, and the trigger chooses.
            #
            # There was no arm here, because there was no list: a graveyard
            # kind answered None above and the announcement "rode the object as
            # it always has" — onto a handler that reads a missing slot as
            # leave to scan, which is how Gravedigger returned the Ornithopter
            # when the Hill Giant it had named was exiled in response.
            #
            # …and **several** of them out of one pile (Gravegouger's "up to
            # two target cards from a single graveyard"): a list of slots, each
            # held to the same list, and no more of them than the trigger
            # prints. The pile is one seat, so "a single graveyard" holds by
            # construction.
            slot = item.target_permanent_index
            slots = slot if isinstance(slot, list) else [slot]
            if not slots or not all(isinstance(each, int) for each in slots):
                return "unnamed"
            pile = self.graveyard_target_seat(item, spec)
            legal = {
                (candidate.get("seat"), candidate.get("index"))
                for candidate in candidates if candidate.get("kind") == "graveyard"
            }
            ceiling = spec.get("max_targets")
            if isinstance(ceiling, int) and len(set(slots)) > ceiling:
                return "illegal"
            return None if all((pile, each) in legal for each in slots) else "illegal"
        if spec.get("kind") in self._CHOOSABLE_TRIGGER_STACK_KINDS:
            # A spell, named by identity. Still one the trigger could choose —
            # it may have been countered, or have stopped answering the printed
            # phrase, while the permanent spell waited above it.
            if item.target_stack_item is None:
                return "unnamed"
            if any(
                offered is item.target_stack_item
                for offered in self._stack_objects_offered(candidates)
            ):
                return None
            return "illegal"
        ids = item.target_permanent_id
        named = [
            permanent_id
            for permanent_id in (ids if isinstance(ids, (list, tuple)) else [ids])
            if isinstance(permanent_id, int)
        ]
        # "…exile **two** target lands" (Petradon) named with one land: a
        # printed count the trigger could not have announced short (CR 601.2c),
        # so it chooses again — and is removed there if the board cannot meet
        # the count (CR 603.3d).
        if (
            named and spec.get("exact_targets")
            and isinstance(spec.get("max_targets"), int)
            and len(set(named)) != spec["max_targets"]
            and not _target_is_up_to(getattr(item.ability_instruction, "payload", None))
        ):
            return "illegal"
        # A spec that is a player and nothing else never reads an id
        # (``stack_targets._read``): the seat is the announcement.
        if named and spec.get("kind") != "player":
            legal = set()
            for candidate in candidates:
                if candidate.get("kind") != "permanent":
                    continue
                permanent = self.permanent_at(candidate["seat"], candidate["index"])
                if permanent is not None:
                    legal.add(permanent.permanent_id)
            if all(permanent_id in legal for permanent_id in named):
                return None
            return "illegal"
        seats = {
            candidate.get("seat") for candidate in candidates
            if candidate.get("kind") == "player"
        }
        if item.target_player_index in seats:
            return None
        from ...targeting import spec_offers_a_player

        return "illegal" if spec_offers_a_player(spec) else "unnamed"

    def _trigger_target_candidates(
        self, item: StackItem, *, announced: bool = False,
    ) -> "tuple[dict, int, list] | None":
        """``(spec, chooser seat, candidates)`` — what CR 603.3d lets *item*
        choose its target from, or None when this picker makes no choice for it.

        The whole of :meth:`_choose_trigger_targets`' decision, split from the
        prompt it arms because the list has a second and a third reader:

        * :meth:`cast_announcement_fault` — an entry trigger carrying the
          target its permanent spell named is asked whether that target is one
          it could have chosen itself;
        * ``legality.entry_trigger_cast_targets`` — the cast picker that names
          it, which has to offer this list and not a wider one.

        *announced* is those two readers' question: the item's target fields
        hold (or will hold) a **cast's announcement** rather than something the
        firing event bound, so the two early-outs that read them as "the event
        made the choice" are skipped. Every other way out stands — a phrase this
        picker cannot narrow is one it cannot judge either.

        The candidates are ``_enumerate_targets``' own entries (the picker's
        vocabulary: a ``permanent`` by seat and slot, a ``player`` by seat).
        """
        from ...targeting import derive_instruction_spec

        instruction = item.ability_instruction
        if instruction is None or modal_trigger_modes(instruction):
            return
        if not announced and item.target_stack_item is not None:
            return
        # A stamped target means the event made the choice — **unless what the
        # fire site stamped is the ability's own source**. The two combat fire
        # sites that announce a permanent's trigger about itself thread the
        # permanent's own controller and slot through ``target_player_index`` /
        # ``target_permanent_index`` so that ``resolve_own_combatant`` can find
        # it again (Mijae Djinn removes *itself* from combat, Ydwen Efreet
        # *itself* from the block). That is a reference, not a choice, and this
        # method could not tell the two apart: three shipped cards printing
        # "target" had CR 603.3d's choice skipped and resolved against the
        # attacker or blocker instead. Sidar Jabari found nothing to tap
        # (its "defending player controls" narrowing correctly refused itself),
        # Seasoned Marshal tapped **itself**, and Elite Javelineer dealt its 1
        # damage to **itself**.
        #
        # ``announces_a_target`` is the second half and the safe direction: it
        # is the lowering's own record that the printed line said the word, so
        # a trigger the same fire site announces about an object the *event*
        # named — Mindbender Spores' "put four fungus counters on **that
        # creature**" — keeps the reference it has always had. Asked only in
        # this branch, never as a general gate: for an unstamped trigger the
        # record is evidence rather than proof, and a False there would take a
        # real target away (Man-o'-War's bounce answers False today).
        if not announced and item.target_permanent_id is not None and not (
            item.source_permanent is not None
            and item.target_permanent_id == item.source_permanent.permanent_id
            and announces_a_target(instruction)
        ):
            return
        spec = derive_instruction_spec([instruction])
        if spec is None:
            return
        picks_a_player = spec.get("kind") in self._CHOOSABLE_TRIGGER_PLAYER_KINDS
        picks_a_card = _names_a_graveyard_target(spec, item.ability_text)
        picks_a_spell = spec.get("kind") in self._CHOOSABLE_TRIGGER_STACK_KINDS
        picks_a_division = spec.get("kind") in self._CHOOSABLE_TRIGGER_DIVIDED_KINDS
        if picks_a_division and not self._trigger_division_is_announceable(spec):
            return
        if (
            not picks_a_player
            and not picks_a_card
            and not picks_a_spell
            and not picks_a_division
            and spec.get("kind") not in self._CHOOSABLE_TRIGGER_TARGET_KINDS
        ):
            return
        if picks_a_card and not announced and (
            item.target_permanent_index is not None
            or item.target_graveyard_card is not None
        ):
            # The graveyard half of the stamped-target early-out above: a slot
            # the fire site handed in is the event's, not a choice left to
            # make. (A graveyard target has no ``permanent_id`` for that
            # early-out to see.)
            return
        if picks_a_spell:
            # The printed line has to have said "target", for the player
            # half's reason below: "Whenever a player casts a spell, counter
            # **it**" (Nether Void) derives the same stack spec for a spell the
            # *event* named, and that is bound, not chosen.
            if not announces_a_target(instruction):
                return
            # A printed controller reaches a stack spec as ``stack_controller``
            # ("…spell an opponent controls"); one that did not is a phrase the
            # stack enumerator would ignore, and this declines for the reason
            # the board half does a few lines down.
            if (
                _target_filter_controller(getattr(instruction, "payload", None))
                is not None
                and spec.get("stack_controller") is None
            ):
                return
            candidates = self._enumerate_targets(
                item.caster_index, item.card, dict(spec), for_cast=False,
                ability_instruction=instruction,
                source_permanent=item.source_permanent,
                ability_source=item.source_permanent,
                triggered=True,
            )
            return dict(spec), item.caster_index, candidates
        if picks_a_player:
            # The printed line has to have said "target". See
            # :func:`announces_a_target`: the spec's "player" may be a kind
            # table's default over a sentence whose seat the event already
            # named, and offering that is a prompt whose answer nothing reads
            # — or, for a phrase the default does not narrow, a prompt
            # offering a seat the card excludes.
            if not announces_a_target(instruction):
                return
            # ...and the fire site must not have bound the seat already, which
            # is the player half of the ``target_permanent_id`` early-out above:
            # a fire site that stamps the seat its event was about has made the
            # choice, and asking again would replace it with one nobody made.
            if not announced and item.target_player_index is not None:
                return
        # **Only pick what the enumerator can narrow.** A printed noun phrase's
        # controller reaches the spec as a flag ("you control" → `own_only`,
        # "an opponent controls" → `opponent_only`, "defending player controls"
        # → `defending_player_only`); one that did not is one the enumerator
        # would ignore, and offering a wider list than the card prints is the
        # single thing a picker must never do.
        #
        # "…that **that player** controls" (Chandra's Incinerator) is that
        # case, and deliberately so: the seat is one the *event* picked, known
        # only to the handler holding the trigger's context, which does the
        # narrowing itself as it resolves. Left to this picker it would offer
        # every permanent on the board and stamp the first.
        if not _controller_narrowing_is_in(spec, instruction):
            return
        spec = dict(spec)
        # "Defending player controls" is a seat the *combat* knows and the
        # enumerator does not, so it travels with the spec. The fire site froze
        # it into the trigger's context when the ability triggered (CR 603.10),
        # which is the same key the attack triggers already use.
        defending = (item.trigger_context or {}).get("trigger_defending_player_index")
        if isinstance(defending, int):
            spec["defending_player_index"] = defending
        # "That player" travels the same way and for the same rule, read
        # through the *same key list* the resolution reads it through
        # (`handlers/_targets._THAT_PLAYER_CONTEXT_KEYS`). One list, because the
        # picker and the handler must agree about which seat the words name:
        # a second copy here would be a picker offering one board while
        # `subject_matches` tested another, and the difference would show as an
        # ability that resolves against nothing.
        that_player = self._that_player_seat(item)
        if that_player is not None:
            spec["that_player_index"] = that_player
        elif spec.get("that_player_only"):
            # Nothing froze the seat, so there is no board to offer. Declining
            # is the safe direction the three early-outs above take: an
            # unnarrowed list would offer every permanent in the game for a
            # phrase that names one player's.
            return
        # "**That player** chooses target player who…" (the Exodus Oaths).
        # CR 601.2c gives the choice to the ability's controller unless the
        # card says otherwise, and these say otherwise: the seat that picks is
        # the one whose upkeep it is. Only the prompt moves — the candidate
        # list is enumerated from the announcing seat exactly as before,
        # because every narrowing these cards print carries its own reference
        # (`compared.than`) and the lowering refuses a printed chooser beside
        # one that does not.
        #
        # A chooser the fire site never froze cannot be asked, and the ability
        # then announces nothing rather than falling back to the controller —
        # the same safe direction the three early-outs above take.
        chooser_index = item.caster_index
        if spec.get("chooser") is not None:
            chooser_index = self._trigger_chooser_seat(item, spec["chooser"])
            if chooser_index is None:
                return
        candidates = self._enumerate_targets(
            item.caster_index, item.card, spec, for_cast=False,
            ability_instruction=instruction,
            source_permanent=item.source_permanent,
            ability_source=item.source_permanent,
            triggered=True,
        )
        return spec, chooser_index, candidates

    def _arm_trigger_target_choice(
        self, item: StackItem, spec: dict, chooser_index: int, candidates: list,
    ) -> None:
        """Ask *chooser_index* for *item*'s target out of *candidates*, or take
        the ability off the stack when there is none to ask about (CR 603.3d).

        The prompt half of :meth:`_choose_trigger_targets`.
        """
        instruction = item.ability_instruction
        if spec.get("kind") in self._CHOOSABLE_TRIGGER_STACK_KINDS:
            self._choose_trigger_stack_target(item, chooser_index, candidates)
            return
        offered = []
        stamps: dict = {}
        for candidate in candidates:
            if candidate.get("kind") == "player":
                seat = candidate.get("seat")
                if not isinstance(seat, int) or not 0 <= seat < len(self.players):
                    continue
                offered.append({
                    "kind": "player",
                    "seat": seat,
                    "name": self.players[seat].name,
                })
                continue
            if candidate.get("kind") == "graveyard":
                # A **card in a graveyard** (Gravedigger, Karmic Guide): the
                # third shape, addressed by pile and slot because that is all a
                # graveyard has. The stamp those two name *now* is kept beside
                # the list, so the answer is checked against the card that was
                # offered rather than against whatever sits in that slot when
                # it arrives. Two copies of one card in one pile are one
                # object; the stamp's ordinal is what tells the offers apart.
                # (Beside the list, under a private key: an offer is what the
                # client is sent, and a stamp holds a live card.)
                stamp = self.graveyard_target_at(
                    candidate.get("seat"), candidate.get("index")
                )
                if stamp is None:
                    continue
                stamps[(stamp.seat, candidate["index"])] = stamp
                offered.append({
                    "kind": "graveyard",
                    "seat": stamp.seat,
                    "graveyard_index": candidate["index"],
                    "name": stamp.card.name,
                })
                continue
            if candidate.get("kind") != "permanent":
                continue
            perm = self.permanent_at(candidate["seat"], candidate["index"])
            if perm is None:
                continue
            offered.append({
                # Stamped on every entry, not only the new ones: the prompt
                # carries two shapes now, and a reader telling them apart by
                # which keys happen to be missing would be guessing.
                "kind": "permanent",
                "seat": candidate["seat"],
                "permanent_index": candidate["index"],
                "permanent_id": perm.permanent_id,
                "name": perm.card.name,
            })
        up_to = _target_is_up_to(getattr(instruction, "payload", None))
        division = spec.get("kind") in self._CHOOSABLE_TRIGGER_DIVIDED_KINDS
        if division and self.departing:
            # A dies-trigger is announced while its dying permanent is still
            # listed (``Game.departing``), and CR 603.3d puts the ability on
            # the stack *after* the event: Shambling Swarm cannot distribute
            # its counters onto itself. Asked only of a division, the one shape
            # that had no prompt before — the general decline for every other
            # dies-trigger is ROADMAP's (a), and its fix is a different seam.
            gone = {permanent.permanent_id for permanent in self.departing}
            offered = [
                entry for entry in offered
                if entry["kind"] != "permanent" or entry["permanent_id"] not in gone
            ]
        if not offered:
            # "Up to one" with nothing to name is an announcement of zero
            # targets (CR 601.2c), not a choice that cannot be made — the
            # ability stays on the stack with no target and resolves.
            #
            # **And it says so on the object.** Left as an ability with empty
            # target fields it was indistinguishable from one whose handler is
            # expected to find its own target, and the scan under every
            # single-target handler found one: with nothing but a shrouded
            # creature across the table, Barrin, Tolarian Archmage and Roaming
            # Ghostlight returned it to its owner's hand and Feline Sovereign
            # destroyed it — the picker had offered nothing and the resolution
            # acted on what the picker refused.
            if up_to:
                self.record_no_target_named(item)
                return
            self.stack = [existing for existing in self.stack if existing is not item]
            self.log.append(
                f"{item.card.name}'s triggered ability was removed from the stack: "
                "it has no legal target (603.3d)"
            )
            return
        # "…each of **up to two** other target creatures you control" (Basri's
        # Acolyte); "you may tap **up to two** target creatures" (Cho-Arrim
        # Bruiser). CR 601.2c chooses *every* target the ability prints, and
        # the count is the printed one — it rode the spec to here and stopped,
        # so the prompt asked for one target and the second was never anybody's
        # to name. Absent for every ability that prints one, which is what
        # keeps the prompt those raise byte-identical.
        several = {}
        printed = spec.get("max_targets")
        if isinstance(printed, int) and printed > 1:
            on_offer = sum(1 for entry in offered if entry["kind"] == "permanent")
            if stamps:
                # "…exile **up to two** target cards **from a single
                # graveyard**" (Gravegouger). Several cards in a graveyard are
                # one announcement too (CR 601.2c), all out of one pile where
                # the spec says so (``targeting.SINGLE_GRAVEYARD``) — so what is
                # on offer is the most any one pile holds, and the answer names
                # a pile and its slots (``_resolve_trigger_graveyard_targets``).
                from collections import Counter

                from ...targeting import SINGLE_GRAVEYARD

                piles = Counter(
                    entry["seat"] for entry in offered if entry["kind"] == "graveyard"
                )
                on_offer = (
                    max(piles.values(), default=0) if spec.get(SINGLE_GRAVEYARD)
                    else sum(piles.values())
                )
                if spec.get(SINGLE_GRAVEYARD):
                    several["single_graveyard"] = True
            if spec.get("exact_targets") and not up_to:
                # "When this creature enters, exile **two** target lands."
                # (Petradon.) A printed count with no "up to" is owed whole
                # (CR 601.2c: two different targets for two instances of
                # "target"), so a board with one land offers no legal
                # announcement and CR 603.3d takes the ability off the stack —
                # it is not asked for the one it can have. Where the count can
                # be met the prompt says the answer must meet it.
                if on_offer < printed:
                    self.stack = [
                        existing for existing in self.stack if existing is not item
                    ]
                    self.log.append(
                        f"{item.card.name}'s triggered ability was removed from "
                        f"the stack: it needs {printed} targets and has "
                        f"{on_offer} (603.3d)"
                    )
                    return
                several["exact_targets"] = True
            several["max_targets"] = min(printed, on_offer)
        if division:
            # CR 601.2d: the total to divide and who divides it, beside the
            # ceiling. A chosen division gives every target at least one, so a
            # total smaller than the printed ceiling is a ceiling too ("among
            # one, two, or three" with two counters is two targets at most);
            # "any number of" prints no ceiling, and the board is one.
            from ...divided_damage import CHOSEN, EVENLY

            total = int(spec["division_total"]) + int(spec.get("division_x_bonus") or 0)
            ceiling = sum(1 for entry in offered if entry["kind"] == "permanent")
            if isinstance(printed, int):
                ceiling = min(ceiling, printed)
            if spec.get("division", EVENLY) == CHOSEN:
                ceiling = min(ceiling, total)
            several["max_targets"] = max(1, ceiling)
            several["division_total"] = total
            several["division"] = spec.get("division", EVENLY)
        # "Up to": naming **nobody** is one of the answers (CR 601.2c), and
        # the prompt has to say so or the seat it asks cannot give it. It did
        # not, so a player whose Barrin entered beside nothing but their own
        # creatures was made to return one of them. Absent for every ability
        # that owes its target, which keeps that prompt byte-identical.
        if up_to:
            several["up_to"] = True
        if stamps:
            several["_graveyard_stamps"] = stamps
        self.arm_pending_choice(
            "trigger_target", chooser_index,
            card_name=item.card.name,
            targets=offered,
            _trigger_item=item,
            **several,
        )

    def _stack_objects_offered(self, candidates) -> list:
        """The stack objects a list of ``_enumerate_stack_targets`` entries
        names. The entries count from the **top** (the picker's convention);
        the engine's list is bottom-first."""
        depth = len(self.stack)
        found = []
        for candidate in candidates or ():
            index = candidate.get("stack_index")
            if candidate.get("kind") != "stack" or not isinstance(index, int):
                continue
            position = depth - 1 - index
            if 0 <= position < depth:
                found.append(self.stack[position])
        return found

    def _choose_trigger_stack_target(
        self, item: StackItem, chooser_index: int, candidates: list,
    ) -> None:
        """CR 603.3d for a trigger whose target is a **spell**: name one of
        *candidates* on *item*, or take the ability off the stack when there is
        none.

        **It is the ``trigger_target`` prompt, with a third kind of candidate.**
        Every seat took a stated default here while that prompt carried only
        permanents and players and the client rendered nothing for a stack
        object — a prompt a human seat could not answer is a soft-lock, the
        failure ``ENTRY_CHOICES`` cost 28 cards. The client reads a ``stack``
        candidate now, so an interactive seat is asked like any other trigger
        (CR 603.3d): a Snake put onto the battlefield by an effect, a cast that
        named nothing, a named spell that has since left. A human who *casts*
        it still names the spell the ordinary way, as the permanent is cast
        (the cast picker is a stack picker, and the announcement rides to
        here without this being reached).

        The candidates carry the stack objects themselves, topmost first: a
        spell has no stable id, and its position is only true until the stack
        next moves. The default for a seat nobody asks
        (``_default_trigger_target``) is what it was: the topmost spell on the
        side the effect wants (``_default_trigger_target_side``: a counter is
        aimed at an opponent's spell), and the topmost offered when that side
        has none — the target is mandatory, so a Snake entering over nothing
        but its controller's own spell counters it.
        """
        offered = self._stack_objects_offered(candidates)
        if not offered:
            if _target_is_up_to(getattr(item.ability_instruction, "payload", None)):
                return
            self.stack = [existing for existing in self.stack if existing is not item]
            self.log.append(
                f"{item.card.name}'s triggered ability was removed from the stack: "
                "it has no legal target (603.3d)"
            )
            return
        order = {id(existing): position for position, existing in enumerate(self.stack)}
        offered.sort(key=lambda existing: order[id(existing)], reverse=True)
        self.arm_pending_choice(
            "trigger_target", chooser_index,
            card_name=item.card.name,
            targets=[
                {
                    "kind": "stack",
                    "stack_item": existing,
                    "seat": existing.caster_index,
                    "name": existing.card.name,
                }
                for existing in offered
            ],
            _trigger_item=item,
        )

    def _trigger_chooser_seat(self, item: StackItem, chooser: str) -> int | None:
        """Which seat announces *item*'s target when the card names one, or
        None when nothing froze that seat.

        Two printed words reach here and each reads its own frozen key, because
        they are two different facts about one event:

        * ``that_player`` — the seat the event *was about* (the Exodus Oaths'
          "**that player** chooses target player who…"), through
          :meth:`_that_player_seat` and so through the same key list the
          resolution reads it through;
        * ``event_subject_controller`` — the seat that controlled the *object*
          the event was about ("**that creature's controller** may have it deal
          damage … to any target **of their choice**", Pandemonium). One step
          further out, and a different key: ``matching_permanent_enters``
          freezes the entering permanent's controller and freezes no
          ``event_subject_player`` at all, so reading one for the other would
          announce nothing on every card that prints this.

        A word with no row is declined rather than defaulted, which is the safe
        direction every early-out in :meth:`_choose_trigger_targets` takes: the
        ability announces no target and never reaches the stack's target field,
        where falling back to the controller would hand the pick to precisely
        the seat the card says must not make it.
        """
        if chooser == "event_subject_controller":
            seat = (item.trigger_context or {}).get("event_subject_controller")
            if isinstance(seat, int) and 0 <= seat < len(self.players):
                return seat
            return None
        if chooser == "that_player":
            return self._that_player_seat(item)
        return None

    def _that_player_seat(self, item: StackItem) -> int | None:
        """The seat *item*'s printed "that player" names, or None if the firing
        event froze none.

        The picker's half of ``handlers/_targets.frozen_that_player_seat``, and
        deliberately reading that module's key tuple rather than a list of its
        own: the two answer the same question at two moments, and a phrase the
        picker resolved differently from the resolution is an ability offered
        one board and applied to another.
        """
        from ...handlers._targets import _THAT_PLAYER_CONTEXT_KEYS

        frozen = item.trigger_context or {}
        for key in _THAT_PLAYER_CONTEXT_KEYS:
            seat = frozen.get(key)
            if isinstance(seat, int) and 0 <= seat < len(self.players):
                return seat
        return None

    def _default_trigger_mode_target(self, option: dict, controller_index: int) -> dict | None:
        """Which candidate a non-interactive seat takes for *option*.

        A stated policy, like the "first printed mode" beside it, and derived
        rather than named: ``ai_valuation.activation_target_side`` reads the
        mode's own instruction kind through ``INSTRUCTION_CATEGORIES`` and says
        whether an effect of that family wants an opponent's side or its own.
        A family with no answer falls back to the first candidate offered,
        which is what every prompt in this engine does when nothing
        distinguishes the options.
        """
        from ...ai_valuation import activation_target_side

        candidates = option.get("valid_targets") or []
        if not candidates:
            return None
        side = activation_target_side(option["instruction"])
        if side is not None:
            opponents = set(self.opponents_of(controller_index))
            wanted = opponents if side == "opponent" else {controller_index}
            for candidate in candidates:
                if candidate.get("seat") in wanted:
                    return candidate
        return candidates[0]

    def _entry_trigger_chooses_a_target(
        self, instruction: OracleInstruction, ability_text: str | None = None,
    ) -> bool:
        """Whether CR 603.3d has a target for :meth:`_choose_trigger_targets`
        to choose on this entry trigger.

        The picker's own gate, asked before the push rather than after it: the
        same spec derivation, the same two kind sets, the same
        :func:`announces_a_target` requirement on a player and the same
        printed-word requirement on a graveyard card. A trigger it would
        decline — a spell, a seat nobody prints "target" for, a graveyard card
        its line does not call a target — has no choice that picker could
        make, so it goes on the stack carrying whatever the cast announced,
        exactly as it was handed it inline.
        """
        from ...targeting import derive_instruction_spec

        if modal_trigger_modes(instruction):
            return False
        spec = derive_instruction_spec([instruction])
        if spec is None:
            return False
        kind = spec.get("kind")
        if kind in self._CHOOSABLE_TRIGGER_TARGET_KINDS:
            return True
        if _names_a_graveyard_target(spec, ability_text):
            return True
        return (
            kind in self._CHOOSABLE_TRIGGER_PLAYER_KINDS
            or kind in self._CHOOSABLE_TRIGGER_STACK_KINDS
        ) and announces_a_target(instruction)
