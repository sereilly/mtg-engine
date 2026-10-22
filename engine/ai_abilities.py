"""Which ability an AI seat activates: on its own permanents, on another
seat's (CR 602.1b), and on a card in its hand (CR 113.6j).

:func:`choose_activation_action` walks the seat's own board for the best
ability it may activate and can pay for, asking the engine's gates first —
the activation prohibitions and restrictions (CR 602.5), a target
requirement, a cost no board can pay — and aiming each target on the side
its effect wants (:func:`_activation_target_side`, read step by step off the
program). :func:`choose_foreign_activation_action` asks the same of an
opponent's permanent, where a drawback printed for an opponent to pay for
(Volrath's Dungeon, Ribbon Snake) is the reason to pay
(``ai_valuation.foreign_activation_use``). :func:`choose_hand_activation_action`
is cycling and whatever else is payable only from a hand.

Instant speed is ``ai_policy``'s: it rehearses this chooser's proposals in a
priority window and sets aside the ones it turned down
(``_ACTIVATIONS_SET_ASIDE``, read here).
"""

from __future__ import annotations

from contextvars import ContextVar

from .ai_target_sides import (
    ability_denies_its_target,
    ability_role_target_sides,
    ability_seat_side,
    ability_target_side,
    named_counter_marks_for_harm,
    instruction_target_side,
)
from .ai_valuation import (
    foreign_activation_use,
    hand_entry_steps,
    harms_its_own_source,
    is_mana_ability,
    source_becomes_an_aura,
    source_toughness_change,
)
from .activation_permissions import activation_permission_denial
from .activation_prohibitions import activation_prohibition
from .activation_restrictions import activation_denial, global_activation_ban
from .cost_modifiers import sacrifice_taxes
from .game import Game
from .models import Permanent, PlayerState
from .oracle import OracleInstruction, compile_card_oracle
from .activation_zones import HAND
from .targeting import (
    SINGLE_GRAVEYARD,
    derive_activation_spec,
    role_is_seat,
    spec_is_a_cost,
    spec_roles,
    usable_activated_abilities,
)
from .ai_payment import _plan_land_taps
from .ai_actions import ActivationAction, HandActivationAction
from .ai_scoring import (
    choose_attack_target,
    _permanent_value,
    _score_activation,
)
from .ai_declarations import legal_attackers
from .ai_targets import (
    _graveyard_denial_target,
    _one_graveyard_card_is_denied,
    _aura_harms_its_host,
    _choose_damage_source,
)


def _required_activation_target(
    game: Game, player_index: int, permanent_index: int, target
) -> int | None:
    """The slot on seat *target* a one-target ability must be aimed at for
    its activation to obey a target requirement in force, or None when there
    is none there. `ai_cast_gates._aimed_under_target_requirements` for an activation: the
    picker's own ``required_targets``, on the board the policy already chose.
    """
    from .target_requirements import one_slot

    spec = game.activation_target_spec(player_index, permanent_index, ability_index=0)
    if not one_slot(spec):
        return None
    return next(
        (
            entry["index"] for entry in spec.get("required_targets") or ()
            if entry.get("seat") == target
        ),
        None,
    )


def choose_activation_action(game: Game, player_index: int) -> ActivationAction | None:
    from .targeting import GRAVEYARD_TARGET_KIND

    player = game.players[player_index]

    best: ActivationAction | None = None
    set_aside = _ACTIVATIONS_SET_ASIDE.get()
    for permanent_index, permanent in enumerate(player.battlefield):
        if permanent.tapped or permanent.card.primary_type == "land":
            continue
        if game._is_summoning_sick(permanent):
            continue
        # One the instant-speed chooser has rehearsed and turned down this
        # time it was asked (`ai_policy.choose_instant_speed_activation`), so the
        # next-best is the one proposed.
        if permanent.permanent_id in set_aside:
            continue

        # A permanent an effect stripped of its abilities ("loses all
        # abilities", CR 305.7) has none to propose: the engine refuses every
        # one, so naming one is a turn spent on a refusal, every turn.
        if game.lost_abilities_refusal(permanent) is not None:
            continue
        # **What the permanent has, not what its card prints** — the engine's
        # own list (`Game.usable_abilities_of`), which is the one the
        # activation path indexes into and the browser shows a person. It
        # compiles the permanent's *effective* card: CR 613's layer 1 gives a
        # copy the copied object's abilities and layer 6 gives an enchanted
        # permanent the ones its Aura quotes. This compiled ``permanent.card``,
        # so a Clone of a Prodigal Sorcerer never pinged in an AI's hands and
        # a creature wearing Hermetic Study was a creature wearing nothing
        # (`tests/ai/test_ai_activation_effective_card_census.py`: of 931
        # cards whose printed self the seat activates, a copy of none).
        #
        # The shared reader, not a third copy of its predicate: it carries
        # CR 113.6's zone read, so a cycling creature's "{2}, Discard this card:
        # Draw a card." is not on this list at all. Open-coded, the policy
        # proposed it every main phase and the engine ran it — a free repeatable
        # draw for a card that was never discarded, on eight of Urza's Saga's
        # creatures. It is also the list `activation_target_spec` narrows by,
        # which the `ability_index=0` below already assumes.
        ability = next(iter(game.usable_abilities_of(permanent)), None)
        if ability is None or ability.instruction is None:
            continue

        # A mana ability is activated to *pay* for something (_plan_land_taps
        # arranges that), never for its own sake: mana added here empties at the
        # end of the step, and Black Lotus sacrifices itself to add it. The set
        # this replaced named two instruction kinds that no longer exist, so the
        # skip had silently stopped happening — see MANA_ABILITY_KINDS.
        if is_mana_ability(ability.instruction):
            continue

        # "Return this creature to its owner's hand" (Quicksilver Wall),
        # "This creature loses flying until end of turn" (Ribbon Snake),
        # "Destroy this enchantment" (Volrath's Dungeon): an effect that removes
        # or hampers **its own source**. Mostly a drawback printed for an
        # opponent to pay for (CR 602.1b), otherwise a rescue that needs a
        # response window this main-phase chooser never has — and the score
        # below rates it 2.5 like anything else, so the AI bounced its own wall
        # for {4} and paid 5 life to destroy its own Dungeon. Read off the
        # compiled program (`ai_valuation.harms_its_own_source`), the reading
        # `choose_foreign_activation_action` takes the other way.
        if harms_its_own_source(ability.instruction):
            continue

        # A cost paid in permanents or cards is a trade this policy cannot
        # price: Atog's "+2/+2 until end of turn" is worth an artifact only
        # sometimes, and the score below reads the *effect* alone. Skipping is
        # the honest floor — the alternative is an AI that eats its own board
        # every main phase for a pump that wears off. Derived from the compiled
        # cost, so it reaches every card printed this way and names none.
        #
        # **Except a discard that takes a card with madness** (CR 702.35a)
        # whose madness cost the board can pay beside the ability: that card
        # is not spent but offered for less (`_madness_discard_index`), so the
        # trade is priced — by the offer's own rehearsal when it is made.
        madness_discard = (
            _madness_discard_index(
                game, player_index, ability, dict(ability.cost.mana),
                paying_for=permanent,
            )
            if ability.cost.discard_cards and ability.cost.sacrifice_filter is None
            else None
        )
        if ability.cost.sacrifice_filter is not None or (
            ability.cost.discard_cards and madness_discard is None
        ):
            # A conjoined sacrifice ("a creature **and a Swamp**", Viscerid
            # Drone) is covered by the clause above rather than by a second
            # test: the charger never fills `sacrifice_also_filter` without
            # `sacrifice_filter`, so a second condition would be unreachable
            # and would read as a claim that it is not.
            continue
        # …and the same trade imposed from outside: "Activated abilities of
        # nontoken Rebels cost an additional "Sacrifice a land"" (Brutal
        # Suppression), Drought's per-{B} Swamp. Asked of the reader the charger
        # uses, so a tax the engine would collect is a tax this policy sees.
        if sacrifice_taxes(
            game, player_index, ability.cost.mana, "activate", source=permanent,
        ):
            continue
        # "…+X/+0 until end of turn, where X is **the power of the creature
        # tapped this way**" (Keldon Battlewagon). The effect is as large as the
        # creature the cost taps, which the score below cannot see — and the
        # payment's default is the first untapped creature, which for the
        # Battlewagon is itself: +0/+0 and its own attack spent, every main
        # phase. Derived from the payload, so it names no card.
        if "cost_tap_characteristic" in (
            ability.instruction.payload.get("x_from_count") or {}
        ):
            continue

        # "Put a -1/-1 counter on a creature you control" (Wandering Mage). The
        # same trade one resource over, and the same reason the policy cannot
        # price it: the score below reads the *effect*, so a shield bought by
        # permanently shrinking a creature reads as free — and the AI would pay
        # it every main phase until its own board is gone. Derived from the
        # compiled cost, so it names no card.
        if ability.cost.put_counter_filter is not None:
            continue

        # "{1}{B}, Pay 2 life: …" (Phyrexian Reclamation). Life is the one cost
        # here the score below never weighed, so the seat paid it every main
        # phase down to 1 — and then proposed it once more, which the engine
        # refuses (CR 119.4: a player can pay life only up to their total) and
        # the simulator counts as a seat doing nothing. The reserve is the one
        # `FOREIGN_ACTIVATION_LIFE_RESERVE`, `ai_casts.BUYBACK_LIFE_RESERVE` and
        # `ai_scoring.X_LIFE_RESERVE` already keep, for their reason: the last points of
        # life are the ones that lose the game.
        life_cost = int(ability.cost.pay_life or 0)
        if life_cost and player.life - life_cost < ACTIVATION_LIFE_RESERVE:
            continue

        # "Remove a +1/+1 counter from a creature you control" (Spike Rogue).
        # The same trade in the opposite direction and the same reason the
        # policy cannot price it: the score below reads the *effect*, so moving
        # a counter from one creature to another reads as a free +1/+1 — and
        # the AI would shuttle its board's counters onto the Spike every main
        # phase for no net gain. Derived from the compiled cost, so it names no
        # card. The self-referring spelling is left alone: that one is priced by
        # the source's own counters, which the score does read.
        if ability.cost.remove_counter_filter is not None:
            continue
        # …and every cost the score does price still has to be **payable**
        # (CR 601.2h via CR 602.2b; CR 118.3): "{T}, Remove a javelin counter
        # from this creature" with none left (Icatian Javelineers), "Exile two
        # cards from your graveyard" over an empty one (Grim Lavamancer),
        # "Tap two untapped Spirits you control" with one (Shacklegeist),
        # "Return a Forest you control" with none (Quirion Ranger). The
        # activation path refuses each with nothing paid, and this proposed it
        # again every main phase, the seat's one activation of the turn.
        #
        # **Asked of the engine's own gate** (`Game.unpayable_activation_cost`,
        # the one the activation path refuses with), not of a reading here.
        # This chooser asked the costs it knew one at a time — the counter
        # above was the last it learned — and none it did not: on a board that
        # could pay nothing, 26 abilities in the pool were proposed and
        # refused for their cost (`tests/ai/test_ai_activation_cost_census.py`).
        if game.unpayable_activation_cost(player_index, permanent, ability) is not None:
            continue

        # "Exile the top card of your library" (Royal Herbalist, Phyrexian
        # Devourer). The same floor one zone over, and the sharper case for it:
        # the resource spent is the seat's remaining turns (CR 704.5b — a player
        # who would draw from an empty library loses), which this policy has no
        # term for at all. Left in, a seat with two mana gains 1 life every turn
        # until it decks itself, which is a loss traded for nothing.
        if ability.cost.exile_top_of_library:
            continue

        # "Exile the top creature card of your graveyard" (Necratog, Zombie
        # Scavengers), "…the top card…" (Alms, Nature's Kiss). The same floor
        # one zone over, with a second reason the library cost does not have:
        # the cost **scans** the pile, so an activation the policy proposes
        # against a graveyard holding no matching card is refused with nothing
        # spent — and the policy would propose it again next turn, and every
        # turn after, which is the "a seat doing nothing all game" shape a
        # refused action makes. Derived from the compiled cost, so it names no
        # card.
        if ability.cost.exile_graveyard_position is not None:
            continue

        # CR 602.1a and its exceptions: a permanent whose printed permission
        # closes its ability to *its own controller* — "Only your opponents may
        # activate this ability" (Clergy of the Holy Nimbus), "Only the
        # controller of the enchanted creature…" (Merseine) — is an ability
        # this seat may not activate at all. Asked of the module that enforces
        # it rather than scored, so the answer is the engine's own; without it
        # the policy proposed the same refused activation every turn for the
        # whole game, which is the "a seat doing nothing all game" shape a
        # refused action makes.
        if activation_permission_denial(
            game, player_index, permanent, ability.source_line or ""
        ):
            continue
        # CR 602.5 as **one question** (``engine/activation_prohibitions.py``):
        # the table the activation path refuses with. The two checks around
        # this one are three of its ten rows; the other seven this chooser
        # never asked — City of Solitude's "…activate abilities only during
        # their own turns", Hand to Hand's "during combat", an Abeyance, an
        # Interdict, Faith's Fetters, Volrath's Curse, Katabatic Winds — so it
        # proposed the ability and the engine refused it, the seat's only
        # activation of the turn, every turn.
        if activation_prohibition(game, player_index, permanent, ability) is not None:
            continue
        # CR 602.5: the printed timing ("Activate only during your upkeep",
        # Svyelunite Priest; "…only during combat", Arcum's Sleigh) and a
        # board-wide ban ("Activated abilities of artifacts can't be
        # activated", Null Rod). This chooser runs in a main phase and asked
        # neither, so it proposed them and the engine refused them, every
        # turn, each one the seat's only activation of the turn. The default
        # seeded runs (every shipped set plus PCY) logged 184 refused
        # activations at PCY's wave 2 and 47 with this asked; what is left is
        # costs the board cannot pay (a counter, an exile). Asked of the
        # tables the engine enforces, so the answer is the engine's.
        if activation_denial(
            game, player_index, permanent, ability.source_line or ""
        ) or global_activation_ban(game, permanent):
            continue

        # "Pay enchanted creature's mana cost" (Merseine). A cost the compiled
        # program cannot state — it is whatever the attached permanent's
        # printed cost is right now — so the tap planner below has nothing to
        # plan against. Skipping is the same honest floor the cost skips above
        # take, and it is derived from the compiled cost, so it names no card.
        if ability.cost.mana_from_attached:
            continue

        target = _choose_target_for_instruction(ability.instruction, player_index, game)
        # An equip ability (CR 702.6a): the creature is chosen here, because the
        # handler declines a target it was not given rather than scanning for
        # one (a misplaced Equipment is wrong in a way a fizzled pump is not).
        # Skipped entirely when nothing is worth equipping, so the AI does not
        # pay {1} every main phase to move a sword onto the creature it is
        # already on.
        target_permanent_index: int | list[int] | None = None
        if ability.instruction.kind == "attach_source_to_target":
            target_permanent_index = _choose_equip_target(game, player_index, permanent)
            if target_permanent_index is None:
                continue
        if ability.instruction.kind == "grant_banding_to_target":
            # Banding grants go to the controller's own creatures.
            target = player_index
            target_creatures = [
                perm for perm in game.controlled_by(player_index) if perm.is_creature
            ]
            if not target_creatures:
                continue

        # An object-targeted ability (Silent Dart's "deal 3 to target creature",
        # a "destroy target …") must name a legal permanent, or the activation
        # is refused with nothing paid (CR 602.2b). Derive the target the way the
        # picker does and aim it by the effect's category; skip when nothing is
        # worth (or legal) to target, so the AI does not burn a turn on an
        # ability it cannot resolve.
        spec = derive_activation_spec(ability)
        # "{X}, {T}: Untap **X target** lands." (Candelabra of Tawnos, Alexi,
        # Orcish Settlers.) CR 601.2c sizes the target list from the X the
        # activator announces, and this policy announces none — so the engine
        # reads X as zero and refuses any named target. Proposing the ability
        # anyway is a refused activation every turn; skipping it is the honest
        # floor until the policy prices an X. Read off the cost clause the way
        # the activation path counts its ``{X}`` symbols, so a *defined* X (the
        # verse cycle's "where X is …") is left to the sizing that answers it.
        #
        # And the same floor for **every** ``{X}`` in a cost, not only one that
        # sizes a target list: "{X}, {T}: This creature deals X damage to target
        # creature" (Crimson Hellkite) is an X its controller announces
        # (CR 107.3a), this policy announces none, and the engine reads that as
        # zero — a tap and a turn spent dealing nothing. It reached the score
        # below only to crash there on the payload's "x".
        if "{x}" in (ability.source_line or "").lower().split(":", 1)[0]:
            continue
        # An ability naming several targets of *different* kinds, chosen in
        # dependency order (CR 602.2b reaches CR 601.2c). Asked before the
        # single-target block below, which has no arm for it: the kind is
        # "roles", so that block leaves the announcement empty and the ability
        # goes on the stack with no targets — an activation that resolves and
        # does nothing, which is the shape `refused_casts` exists to make
        # visible one step later.
        target_role_refs: list[dict] | None = None
        if spec_roles(spec):
            target_role_refs = _choose_activation_role_targets(
                game, player_index, permanent_index,
                # A side only for a chain that announces a **seat** — the three
                # abilities this walk could not answer at all until it grew an
                # arm for one (see the function). Every other roles ability
                # keeps the first-option walk it has always had: giving those a
                # side too is the right policy and a different change, one that
                # moves what the AI does with every card already activating.
                side=(
                    _activation_target_side(permanent, ability.instruction)
                    if any(role_is_seat(role) for role in spec_roles(spec))
                    else None
                ),
            )
            if target_role_refs is None:
                # No legal chain. Skipped rather than proposed: CR 602.2b fills
                # every role or the activation is refused with nothing paid,
                # and the gate would refuse it.
                continue
        object_kinds = {"creature", "artifact", "land", "permanent", "planeswalker"}
        if (
            target_permanent_index is None
            and spec is not None
            and spec.get("kind") in object_kinds
            and not spec.get("sacrifice_cost")
            and not spec.get("discard_cost")
            # A tap-cost picker (Llanowar Behemoth) names no target either: the
            # payment is the engine's default for a seat that names nothing.
            and not spec.get("tap_cost")
            and not spec.get("return_cost")
            # …nor an untap picker over an opponent's tapped lands (Benthic
            # Explorers, PCY W3G5): read as a target, the AI would aim at the
            # land it untaps and announce a target the ability does not have.
            # The counter-cost pickers are skipped above, before this block.
            and not spec.get("untap_cost")
        ):
            # The AI activates the first usable ability (selected above), which
            # is usable_activated_abilities()[0] — the index activation_target_spec
            # narrows by.
            legal = game.activation_target_spec(
                player_index, permanent_index, ability_index=0,
            ).get("valid_targets") or []
            perms = [t for t in legal if t.get("kind") == "permanent"]
            if not perms:
                continue
            # Which board, from what the effect does to its target
            # (`_activation_target_side`) — and **only** that
            # board. This fell back to "any legal permanent" when the wanted
            # side had none, which is how a destroy, a tap or a "can't block"
            # with no opposing target landed on the activator's own creature,
            # and a pump with no friendly one landed on an opponent's: an
            # activation that resolves and harms the seat that paid for it.
            side = _activation_target_side(permanent, ability.instruction)
            if spec.get("source_of_choice"):
                # "…a source of your choice…" (CR 609.7a) is not a target, so
                # no side describes it — and a shield's own category reads
                # "you", which named the activator's own largest creature as
                # the thing to be shielded *from* (Bone Mask, Dark Sphere,
                # Kithkin Armor, Pentagram of the Ages, Protective Sphere,
                # Righteous Aura). The cast side's answer, for the same phrase.
                named = _choose_damage_source(game, player_index, perms)
                if not named:
                    continue
                perms = [
                    t for t in perms if (t["seat"], t["index"]) == (named[0], named[1])
                ]
                side = None
            if side == "you" and ability_denies_its_target(ability.instruction):
                # "Destroy target … you control" (Rats of Rath), "Return target
                # land you control to its owner's hand" (Trade Routes): the
                # printed seat is the activator's and the effect is a denial,
                # so activating it for its own sake only costs the seat a
                # permanent. Before this the fallback above aimed Rats of
                # Rath at whatever it found.
                continue
            if side == "you":
                perms = [t for t in perms if t["seat"] == player_index]
            elif side == "opponent":
                perms = [t for t in perms if t["seat"] != player_index]
            if not perms:
                continue
            def _power(t):
                perm = game.permanent_at(t["seat"], t["index"])
                return perm.effective_power if perm is not None else 0

            chosen = max(perms, key=_power)
            target = chosen["seat"]
            target_permanent_index = chosen["index"]
            # "{T}: Untap **two** target lands" (Argothian Elder), "Choose two
            # target blocked attacking creatures" (General Jarkeld): a printed
            # count names that many (CR 601.2c), and the engine refuses an
            # activation naming fewer. All on the chosen permanent's seat,
            # because this action carries one seat beside its slots — the
            # strongest there first, the order the single pick takes.
            wanted = spec.get("max_targets")
            if spec.get("exact_targets") and isinstance(wanted, int) and wanted > 1:
                beside = sorted(
                    (t for t in perms if t["seat"] == target),
                    key=_power, reverse=True,
                )
                if len(beside) < wanted:
                    continue
                target_permanent_index = [t["index"] for t in beside[:wanted]]

        # "{G}: Exile target card from a graveyard." (Scavenging Ooze.) A card
        # in a graveyard is a target like any other (CR 115.1c), and this
        # chooser named none: the block above reads battlefield kinds, so the
        # announcement went out bare and the engine's default answered it —
        # the picker's first card, which is a stated default for a script and
        # not a choice. The seat's own pick instead: the pile the effect's
        # side wants (`_activation_target_side`), and within it the card with
        # the greatest mana value. Where the effect reads as neither side's —
        # the Ooze's exile is one — an opposing pile is taken before the
        # seat's own, which is the order an unnamed target is looked for in
        # everywhere else. Skipped when nothing on the wanted side is legal,
        # for the battlefield block's reason — and for the two shapes a block
        # below names: several cards out of a single pile (``SINGLE_GRAVEYARD``)
        # and a card exiled to deny it (`_graveyard_denial_target`: an
        # opponent's pile, the cards its owner could still cast first).
        if (
            target_permanent_index is None
            and spec is not None
            and spec.get("kind") == GRAVEYARD_TARGET_KIND
            and not spec_is_a_cost(spec)
            and not spec.get("source_of_choice")
            and not spec.get(SINGLE_GRAVEYARD)
            and not _one_graveyard_card_is_denied(spec, (ability.instruction,))
        ):
            cards = [
                t for t in game.activation_target_spec(
                    player_index, permanent_index, ability_index=0,
                ).get("valid_targets") or []
                if t.get("kind") == "graveyard"
            ]
            side = _activation_target_side(permanent, ability.instruction)
            if side == "you":
                cards = [t for t in cards if t["seat"] == player_index]
            elif side == "opponent":
                cards = [t for t in cards if t["seat"] != player_index]
            if not cards:
                continue

            def _mana_value(t):
                pile = game.players[t["seat"]].graveyard
                held = pile[t["index"]] if 0 <= t["index"] < len(pile) else None
                return float(getattr(held, "cmc", 0) or 0)

            if side is None and any(t["seat"] != player_index for t in cards):
                cards = [t for t in cards if t["seat"] != player_index]
            chosen = max(cards, key=_mana_value)
            target = chosen["seat"]
            target_permanent_index = chosen["index"]

        # "{2}{B}, {T}: Exile up to three target cards from a single
        # graveyard." (Carrion Beetles, Famished Ghoul.) The cards are announced
        # (CR 602.2b), so an activation that names none is the legal "up to"
        # announcement and exiles nothing — a cost paid for no effect, which is
        # what this seat did with every one of them once the handler stopped
        # picking for it. Named here the way the cast side names them
        # (`ai_targets._choose_several_targets`): the maximum, out of one opponent's pile,
        # and skipped when no opponent has a card to take.
        if (
            spec is not None
            and spec.get(SINGLE_GRAVEYARD)
            and target_permanent_index is None
            and not target_role_refs
        ):
            piles: dict[int, list[int]] = {}
            for entry in game.activation_target_spec(
                player_index, permanent_index, ability_index=0,
            ).get("valid_targets") or []:
                if entry.get("kind") == "graveyard" and entry.get("seat") != player_index:
                    piles.setdefault(int(entry["seat"]), []).append(int(entry["index"]))
            if not piles:
                continue
            target = min(piles)
            target_permanent_index = piles[target][: int(spec.get("max_targets") or 1)]
        # "{3}, {T}: Exile target card from a graveyard." (Steamclaw; Crypt
        # Creeper, Grave Robbers, Scavenging Ooze.) Whose graveyard, named —
        # the cast side's answer (`_graveyard_denial_target`) over this
        # ability's own picker. Named nothing, the handler took the first pile
        # in seat order: the activator's own, from chair 0.
        if (
            target_permanent_index is None
            and not target_role_refs
            and _one_graveyard_card_is_denied(spec, (ability.instruction,))
        ):
            buried = _graveyard_denial_target(
                game, player_index,
                game.activation_target_spec(
                    player_index, permanent_index, ability_index=0,
                ).get("valid_targets") or [],
            )
            if buried is not None:
                target, target_permanent_index = buried

        # CR 601.2d asked of an ability: a divided announcement ("…divided as
        # you choose", Serra's Hymn) is one this chooser never makes, and the
        # engine refuses an activation announced without it — so proposing one
        # is a turn spent on a refusal, every turn. Then the engine's own
        # announcement gate (CR 602.2b/601.2c) over exactly what this policy is
        # about to announce: an ability whose only legal targets are cards in
        # an empty graveyard (Rootwater Diver, Groundskeeper) passed every
        # check above, because they look only at battlefield targets, and was
        # refused with nothing paid. Neither shows in `refused_casts`, which
        # counts casts; one ten-game run each of USG, TMP and MMQ logged 44
        # refused Serra's Hymn, 21 Rootwater Diver and 15 Groundskeeper
        # activations.
        if spec is not None and spec.get("kind") == "divided":
            continue
        # "{3}, {T}: You may put a creature card of the chosen type from your
        # hand onto the battlefield." With no such card in hand the ability's
        # whole effect is nothing, and the cost is still paid: Belbe's Portal
        # spent {3} every turn of NEM's simulation to log that it had no card.
        if not _hand_entry_has_a_card(game, player_index, permanent, ability.instruction):
            continue
        if game.activation_target_refusal(
            player_index, permanent, ability,
            target_player_index=target,
            target_permanent_index=target_permanent_index,
            target_role_refs=target_role_refs,
        ) is not None:
            continue
        # …and what an opponent's Flagbearer demands of that announcement
        # (`Game.activation_target_requirement_refusal`): a seat named alone
        # for an "any target" ability is re-aimed at the Flagbearer on that
        # seat, and anything else the gate would refuse is not proposed.
        if game.activation_target_requirement_refusal(
            player_index, permanent, ability,
            target_player_index=target,
            target_permanent_index=target_permanent_index,
            target_role_refs=target_role_refs,
        ) is not None:
            required_slot = (
                _required_activation_target(game, player_index, permanent_index, target)
                if target_permanent_index is None and not target_role_refs
                else None
            )
            if required_slot is None:
                continue
            target_permanent_index = required_slot

        land_taps: tuple[int, ...] = ()
        tap_colors: tuple[str, ...] = ()
        required = dict(ability.cost.mana)
        if game.enforce_mana_costs and any(required.values()):
            plan = _plan_land_taps(game, player, required, paying_for=permanent)
            if plan is None:
                continue
            land_taps, tap_colors = plan

        score = _score_activation(game, player_index, ability.instruction, target)
        if score <= 0.0:
            continue
        candidate = ActivationAction(
            permanent_name=permanent.card.name,
            permanent_index=permanent_index,
            target_player_index=target,
            land_tap_indices=land_taps,
            score=score,
            target_permanent_index=target_permanent_index,
            target_role_refs=target_role_refs,
            land_tap_colors=tap_colors,
            cost_hand_index=madness_discard,
        )
        if best is None or candidate.score > best.score:
            best = candidate

    return best


#: Permanents `choose_activation_action` passes over, by ``permanent_id``:
#: the ones `ai_policy.choose_instant_speed_activation` has rehearsed and turned down in
#: the one decision it is making.
_ACTIVATIONS_SET_ASIDE: ContextVar[frozenset] = ContextVar(
    "ai_activations_set_aside", default=frozenset(),
)


def _madness_discard_index(
    game: Game, seat: int, ability, required: dict[str, int], *,
    paying_for: "Permanent | None" = None,
) -> int | None:
    """The hand position a "Discard a card" cost should take: a card with
    **madness** (CR 702.35a) whose madness cost the seat's board can pay on
    top of the ability's own *required* mana — or None, the engine's default.

    The weight the madness offer's other half needs. Discarding such a card
    exiles it and offers it for its madness cost, so it is the card the cost
    costs least; whether the cast is then *worth* making is the offer's own
    rehearsed question (`ai_policy.choose_madness_cast`), asked when it is made. Only a
    chosen single discard: a discard at random is nobody's choice, and a cost
    of several cards is the engine's to fill in hand order.
    """
    from .madness import printed_madness_cost
    from .mana_payment import mana_cost_from_symbols
    from .subject_filters import card_matches_any

    cost = ability.cost
    if (
        cost.discard_cards != 1 or cost.discard_at_random
        or cost.discard_whole_hand
    ):
        return None
    player = game.players[seat]
    for index, card in enumerate(player.hand):
        madness = printed_madness_cost(card)
        if madness is None or not card_matches_any(card, cost.discard_filters):
            continue
        if game.enforce_mana_costs:
            combined = dict(required)
            for symbol, amount in (mana_cost_from_symbols(madness) or {}).items():
                combined[symbol] = combined.get(symbol, 0) + amount
            if any(combined.values()) and _plan_land_taps(
                game, player, combined, paying_for=paying_for,
            ) is None:
                continue
        return index
    return None


def _activation_target_side(permanent: Permanent, instruction) -> str | None:
    """Whose permanent an own-seat ability's object target should be — "you",
    "opponent", or None for no preference.

    **Read step by step** (`ai_target_sides.ability_target_side`), the reading the
    foreign chooser already took. This asked `instruction_target_side` of the
    top-level instruction, and a ``sequence`` / ``may`` wrapper has no side, so
    an ability whose effect is two steps fell back to "the biggest creature on
    either board": Bullwhip pinged and Serrated Biskelion shrank the AI's own
    biggest creature, Power Matrix and Ivy Seer pumped the opponent's, and
    Wishmonger gave the opponent's protection. Measured over both manifest
    roles with a creature of each size on each board: 47 abilities aimed at
    the wrong seat in one board or the other. The top-level reading stays as
    the fallback for a leaf whose target is not a ``targets`` payload.

    An ability that turns its source into an Aura (the Licids) is aimed as
    that Aura would be cast (`_aura_harms_its_host`): its attach step reads
    "you" for an Equipment's reason, and Calming Licid's "can't attack" or
    Dominating Licid's "you control enchanted creature" belong on an
    opponent's creature.
    """
    if source_becomes_an_aura(instruction):
        return "opponent" if _aura_harms_its_host(permanent.effective_card) else "you"
    # "{T}: Put a fuse counter on target creature." (Bomb Squad.) A named
    # counter reads as a gift by category, and the card's own state trigger
    # says this one is a death sentence — the Licids' case again: which board
    # the target belongs on is what the card's *other* text does with it.
    if named_counter_marks_for_harm(permanent.effective_card, instruction):
        return "opponent"
    return ability_target_side(instruction) or instruction_target_side(instruction)


def _choose_activation_role_targets(
    game: Game, player_index: int, permanent_index: int,
    side: str | None = None,
) -> "list[dict] | None":
    """One object per **role** for an activated ability, or None when no legal
    chain exists.

    ``ai_targets._choose_role_targets``' twin on the activation side, and it is a twin
    rather than a shared body for the reason the two specs are derived
    separately: a spell's roles come from the card and an ability's from *that
    ability* (CR 602.2b), so the walks start from different calls. What they
    share is the policy — take the first option at each level — and it is safe
    for that function's stated reason: a first choice that leaves a later role
    with nothing is not in the list ``_role_target_walk`` returns.

    The answer is in the wire's own shape (``target_role_refs``) because a role
    here may be a card in a graveyard, which has no permanent id to send.

    **A role may also be a seat**, and this walk had no arm for one: "Target
    **opponent** reveals a card at random from their hand. **Target creature**
    gets +X/+X …" (Planeswalker's Favor, Scorn), "Prevent the next 2 damage …
    to target creature. **Target opponent** may draw a card." (Soldevi
    Heretic). A pick of kind ``"player"`` is neither a permanent nor a card, so
    it fell to the permanent branch, found nothing at that seat's slot ``None``
    and answered "no legal chain" — three abilities, the only three in the pool
    that announce a seat in a roles chain, that no AI seat ever activated.

    *side* is which board the ability's object role is aimed at
    (``_activation_target_side``), and with a seat role in the chain it is no
    longer optional: the first option at the permanent level is the first
    board in seat order, so without it Scorn's -X/-X would land on the
    activator's own creature whenever the activator sits first. A level with
    no pick on the wanted side is "no legal chain", the single-target block's
    rule above and for its reason.
    """
    options = game.activation_target_spec(
        player_index, permanent_index, ability_index=0,
    ).get("valid_targets") or []
    # **One side per role, not one for the chain** — the derivation the cast
    # side asks (`ai_target_sides.role_target_sides`), over this ability's own
    # roles. "Target creature with the chosen ability loses it and **another
    # target creature** gains it" (Phyrexian Splicer) is two roles on two
    # boards, and a single side — or none, the first option at each level —
    # named two of the activator's own creatures: the seat paid {2} to move
    # its own flying from one of its creatures to another. *side* stays the
    # answer for a role the derivation gives none (the three seat-role
    # chains it was written for).
    #
    # The permanent as it **is** (``effective_card``), which is the card the
    # picker three lines up compiled: read off the printed one, a Clone of a
    # Splicer was offered the Splicer's two roles and given a side for neither.
    source = game.permanent_at(player_index, permanent_index)
    said = source.effective_card if source is not None else None
    ability = (
        next(iter(usable_activated_abilities(compile_card_oracle(said))), None)
        if said is not None else None
    )
    sides = ability_role_target_sides(said, ability) if ability is not None else ()

    def ref_of(pick: dict) -> "dict | None":
        if pick.get("kind") == "player":
            return {"seat": pick.get("seat")}
        if pick.get("kind") == "graveyard":
            return {
                "graveyard_seat": pick.get("seat"),
                "graveyard_index": pick.get("index"),
            }
        permanent_id = game.permanent_id_of(
            game.permanent_at(pick.get("seat"), pick.get("index"))
        )
        return {"permanent_id": permanent_id} if isinstance(permanent_id, int) else None

    def chain(level: list[dict], position: int) -> "list[dict] | None":
        """The first chain from *level* on whose every role is on the board
        its step wants. Backtracks, because a side makes a first pick able to
        strand a later role the unfiltered walk had an answer for."""
        wanted = (sides[position] if position < len(sides) else None) or side
        if wanted in ("you", "opponent") and any(
            option.get("kind") == "permanent" for option in level
        ):
            level = [
                option for option in level
                if option.get("kind") != "permanent"
                or (option.get("seat") == player_index) == (wanted == "you")
            ]
        for pick in level:
            ref = ref_of(pick)
            if ref is None:
                continue
            rest = pick.get("next") or []
            if not rest:
                return [ref]
            tail = chain(rest, position + 1)
            if tail is not None:
                return [ref, *tail]
        return None

    return chain(options, 0) if options else None


# --- Abilities on a permanent another seat controls ---------------------------
#
# CR 602.1b: "Any player may activate this ability." Every activation chooser
# above walks the seat's own board, so for the life of this engine no AI seat
# ever paid to use an opponent's Volrath's Dungeon, Ribbon Snake or Task Mage
# Assembly — 23 shipped and 11 PCY cards printing a permission that admits
# a seat other than the controller (W1G5's census). The engine has let any
# player activate them since `activation_permissions` existed; this is the
# policy half. Which of them a seat *wants* is
# `ai_valuation.foreign_activation_use`, read off the compiled program.

#: Life a seat keeps back when it pays life to use an opponent's ability.
#: "Pay 5 life: Destroy this enchantment" (Volrath's Dungeon) is removal
#: bought with life, and a seat this low spends its life staying alive.
FOREIGN_ACTIVATION_LIFE_RESERVE = 10
#: …and when it pays life for an ability of its own (`choose_activation_action`).
#: The same number for the same reason; a separate name because it is a
#: separate weight, and tuning one should not move the other.
ACTIVATION_LIFE_RESERVE = 10
#: Taking an opponent's permanent off the battlefield, before what the
#: permanent itself is worth (`_permanent_value`).
FOREIGN_REMOVAL_SCORE = 3.0
#: Killing an opponent's creature with its own printed drawback.
FOREIGN_KILL_SCORE = 5.0

#: The board-target kinds a foreign "aimed" ability is chosen for. A graveyard
#: or stack target is left alone: "Return target creature card from a
#: graveyard to its owner's hand" (Endbringer's Revel) needs a pick of *whose*
#: card this policy does not make for its own copy either, and a stack target
#: has nothing to aim at in the main phase this runs in.
_FOREIGN_OBJECT_KINDS = frozenset({"creature", "artifact", "land", "permanent", "planeswalker"})


def _plain_activation_cost(cost) -> bool:
    """Whether *cost* is mana and a fixed amount of life, and nothing else.

    Every other cost a foreign ability could print — a tap, a sacrifice, a
    discard, a counter, an alternative ("Pay 2 life or {2}", Tidal Control) —
    is a trade or a choice this chooser cannot price. Asked as "equal to a
    bare cost with the same mana" rather than field by field, so a cost field
    added later is declined until someone decides otherwise.
    """
    from dataclasses import replace

    from .oracle_types import ActivatedAbilityCost

    try:
        return replace(cost, pay_life=0) == ActivatedAbilityCost(mana=dict(cost.mana))
    except (TypeError, ValueError):
        return False


def choose_foreign_activation_action(
    game: Game, player_index: int
) -> ActivationAction | None:
    """The best ability this seat may activate on a permanent **another seat
    controls** (CR 602.1b), or None.

    A separate chooser from :func:`choose_activation_action` because the two
    read one program in opposite directions: an effect that removes or hampers
    its own source is a loss to the source's controller (which that chooser now
    skips) and the whole point to anyone else. What the effect is for is
    `ai_valuation.foreign_activation_use`:

    * **removes_source** is wanted whenever it is affordable — mana from the
      board, life only above :data:`FOREIGN_ACTIVATION_LIFE_RESERVE`;
    * **shrinks_source** is wanted only when the shrink kills the creature
      outright, the one hamper that needs nothing lined up behind it;
    * **aimed** is the activator's own ability in every respect but where it
      is printed (CR 113.8), so it is targeted and scored exactly as
      :func:`choose_activation_action` would score it on this seat's board.

    Every gate the engine will ask is asked first, so a proposal is not a
    refused activation every turn: the permission (`activation_permission_
    denial`), the printed timing ("only as a sorcery", "only during their
    turn", `activation_restrictions.activation_denial`), a board-wide ban, and
    CR 602.2b's target gate.
    """
    from .activation_permissions import card_widens_activation

    player = game.players[player_index]
    best: ActivationAction | None = None
    for source_seat, permanent in game.permanents_with_controller():
        if source_seat == player_index or game.players[source_seat].lost:
            continue
        if not card_widens_activation(permanent.effective_card):
            continue
        permanent_index = game.battlefield_index_of(permanent)
        if permanent_index is None:
            continue
        if global_activation_ban(game, permanent):
            continue
        # ``usable_abilities_of``: empty for a permanent that lost its
        # abilities — "loses all abilities", which this asked inline, and a
        # land whose type was set (CR 305.7), which it did not.
        for ability_index, ability in enumerate(game.usable_abilities_of(permanent)):
            candidate = _foreign_activation_candidate(
                game, player_index, player, source_seat, permanent,
                permanent_index, ability_index, ability,
            )
            if candidate is not None and (best is None or candidate.score > best.score):
                best = candidate
    return best


def _foreign_activation_candidate(
    game: Game, player_index: int, player: PlayerState, source_seat: int,
    permanent: Permanent, permanent_index: int, ability_index: int, ability,
) -> ActivationAction | None:
    """One ability on another seat's *permanent*, as an action — or None."""
    instruction = ability.instruction
    if instruction is None or not ability.supported or is_mana_ability(instruction):
        return None
    line = ability.source_line or ""
    if activation_permission_denial(game, player_index, permanent, line):
        return None
    if activation_denial(game, player_index, permanent, line):
        return None
    if not _plain_activation_cost(ability.cost):
        return None
    life_cost = int(ability.cost.pay_life or 0)
    if life_cost and player.life - life_cost < FOREIGN_ACTIVATION_LIFE_RESERVE:
        return None

    use = foreign_activation_use(ability)
    target = source_seat
    target_permanent_index: int | None = None
    if use == "removes_source":
        score = FOREIGN_REMOVAL_SCORE + _permanent_value(permanent)
    elif use == "returns_source":
        # The owner plays it again, so this is tempo rather than removal:
        # worth it when recasting costs them at least what bouncing cost us,
        # or when the permanent is an untapped creature standing in front of
        # an attack this seat can make this turn. Without the second clause a
        # {4} bounce of a three-mana wall is never worth it; without the
        # first, a seat with nobody to attack with bounced it every turn and
        # its owner recast it every turn (PCY's Quicksilver Wall, measured).
        paid = sum(int(value or 0) for value in ability.cost.mana.values())
        clears_a_blocker = (
            permanent.is_creature and not permanent.tapped
            and bool(legal_attackers(game, player_index, against=source_seat))
        )
        if float(permanent.card.cmc or 0) < paid and not clears_a_blocker:
            return None
        score = FOREIGN_REMOVAL_SCORE + float(permanent.card.cmc or 0)
    elif use == "shrinks_source":
        change = source_toughness_change(instruction) or 0
        if not permanent.is_creature or (
            permanent.effective_toughness + change > permanent.damage_marked
        ):
            return None
        score = FOREIGN_KILL_SCORE + _permanent_value(permanent)
    elif use == "aimed":
        spec = derive_activation_spec(ability) or {}
        described = ((instruction.payload or {}).get("targets") or {}).get("filter") or {}
        if described.get("controller") is not None:
            # "Target creature **you control**": the enumeration below runs
            # from the source's seat, so a printed seat would be read as the
            # wrong player's. Declined rather than mis-aimed.
            return None
        if spec.get("kind") == "player":
            target = _choose_target_for_instruction(instruction, player_index, game)
        elif spec.get("kind") in _FOREIGN_OBJECT_KINDS:
            legal = game.activation_target_spec(
                source_seat, permanent_index, ability_index=ability_index,
            ).get("valid_targets") or []
            perms = [t for t in legal if t.get("kind") == "permanent"]
            # Read step by step, so a sequence's grant is aimed by the grant
            # (`ai_target_sides.ability_target_side`), and **only** a side the
            # program states: an object effect with none is a coin flip
            # between the two boards, and on another seat's ability the wrong
            # board is a gift paid for.
            side = ability_target_side(instruction)
            if side == "you":
                # Asked of the step that names the target, for the reason
                # the side is: a wrapper denies nothing.
                if ability_denies_its_target(instruction):
                    return None
                perms = [t for t in perms if t["seat"] == player_index]
            elif side == "opponent":
                perms = [t for t in perms if t["seat"] != player_index]
            else:
                return None
            if not perms:
                return None

            def _power(t):
                perm = game.permanent_at(t["seat"], t["index"])
                return perm.effective_power if perm is not None else 0

            chosen = max(perms, key=_power)
            target = chosen["seat"]
            target_permanent_index = chosen["index"]
        else:
            return None
        score = _score_activation(game, player_index, instruction, target)
    else:
        return None

    if game.activation_target_refusal(
        player_index, permanent, ability,
        target_player_index=target,
        target_permanent_index=target_permanent_index,
    ) is not None:
        return None
    if game.activation_target_requirement_refusal(
        player_index, permanent, ability,
        target_player_index=target,
        target_permanent_index=target_permanent_index,
    ) is not None:
        # An opponent's Flagbearer demands a target this announcement does not
        # name. Not proposed: the gate would refuse it with nothing paid.
        return None

    land_taps: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()
    required = dict(ability.cost.mana)
    if game.enforce_mana_costs and any(required.values()):
        plan = _plan_land_taps(game, player, required)
        if plan is None:
            return None
        land_taps, tap_colors = plan
    if score <= 0.0:
        return None
    return ActivationAction(
        permanent_name=permanent.card.name,
        permanent_index=permanent_index,
        target_player_index=target,
        land_tap_indices=land_taps,
        score=score,
        target_permanent_index=target_permanent_index,
        land_tap_colors=tap_colors,
        source_controller_index=source_seat,
        ability_index=ability_index,
    )


def choose_hand_activation_action(
    game: Game, player_index: int
) -> HandActivationAction | None:
    """The best ability this seat can activate from its **hand**, or None.

    Cycling, and whatever else prints a cost payable only from a hand
    (CR 113.6j). Which abilities those are is not decided here — it is
    ``usable_activated_abilities(program, zone=HAND)``, the same reader
    ``Game.activate_from_hand`` gates on and the same one that keeps the ability
    off a permanent's list — so this policy names no card and no keyword.

    Called **after** the seat's cast for the turn, so the untapped lands the
    payment is planned against are the mana the cast did not want: a seat
    cycles with what is left over rather than instead of playing its spell.

    One action per call, like :func:`choose_activation_action`, and the tie-break
    is hand order — the seat cycles once a priority pass rather than emptying
    its hand in a loop, and a seeded run reproduces exactly.
    """
    player = game.players[player_index]
    best: HandActivationAction | None = None
    for hand_index, card in enumerate(player.hand):
        program = compile_card_oracle(card)
        from_hand = usable_activated_abilities(program, zone=HAND)
        if not from_hand:
            continue
        ability = from_hand[0]
        if ability.instruction is None:
            continue

        # A mana ability activated for its own sake empties at the end of the
        # step; the same floor `choose_activation_action` keeps one zone over.
        if is_mana_ability(ability.instruction):
            continue

        # Any cost beyond mana and the discard the zone read is derived from is
        # a trade this policy cannot price — the same honest floor the
        # battlefield loop takes, and derived from the compiled cost so it
        # names no card.
        cost = ability.cost
        if (
            cost.sacrifice_filter is not None
            or cost.discard_cards
            or cost.pay_life
            or cost.exile_top_of_library
        ):
            continue

        land_taps: tuple[int, ...] = ()
        # The cost as CR 601.2f computes it, through the same reader
        # ``Game.activate_from_hand`` charges: a Fluctuator on the board makes
        # a Cycling {2} free, and a policy pricing the printed cost would pass
        # over an ability the engine would let it take for nothing.
        from .mixins.stack.activation import hand_activation_cost

        tap_colors: tuple[str, ...] = ()
        required = hand_activation_cost(game, player_index, card, ability)[0]
        if game.enforce_mana_costs and any(required.values()):
            plan = _plan_land_taps(game, player, required)
            if plan is None:
                continue
            land_taps, tap_colors = plan

        # The seat is the target: nothing activatable from a hand in the pool
        # aims anywhere else, and an ability that did would be refused at
        # announcement rather than aimed by this policy.
        score = _score_activation(game, player_index, ability.instruction, player_index)
        if score <= 0.0:
            continue
        candidate = HandActivationAction(
            card_name=card.name,
            hand_index=hand_index,
            ability_index=0,
            land_tap_indices=land_taps,
            score=score,
            land_tap_colors=tap_colors,
        )
        if best is None or candidate.score > best.score:
            best = candidate
    return best


def _hand_entry_has_a_card(
    game: Game, player_index: int, source: Permanent, instruction
) -> bool:
    """Whether every "put a … card from your hand onto the battlefield" step of
    an ability (``ai_valuation.hand_entry_steps``) has a card to put.

    The candidates are the engine's own (``put_from_hand_candidates``), with
    "of the chosen type" resolved off the source the way the handler resolves
    it (``_resolve_chosen_subtype``), so the policy and the resolution cannot
    disagree about which cards the step admits.
    """
    from .handlers._common import _resolve_chosen_subtype
    from .handlers.zones import put_from_hand_candidates

    player = game.players[player_index]
    for payload in hand_entry_steps(instruction):
        described = _resolve_chosen_subtype(
            dict(payload.get("card_filter") or {}), source
        )
        if not put_from_hand_candidates(
            game, {**payload, "card_filter": described}, player
        ):
            return False
    return True


def _choose_equip_target(game: Game, player_index: int, equipment) -> int | None:
    """The battlefield index of the creature *equipment* should be moved onto,
    or None when it is already on the best one (or there is none).

    The biggest creature that can attack — power first, then toughness — among
    the ones the Equipment may legally equip, asked of the same legality the
    engine enforces (``engine/equipment.py``) so the AI never activates an
    equip the engine then refuses. Summoning-sick creatures are not excluded:
    an Equipment moved onto one now is on it when it can attack next turn, and
    the +1/+1 blocks just as well meanwhile.
    """
    from .equipment import equip_refusal, equipped_creature

    player = game.players[player_index]
    candidates = [
        (idx, perm)
        for idx, perm in enumerate(player.battlefield)
        if perm.is_creature and equip_refusal(game, equipment, perm) is None
    ]
    if not candidates:
        return None
    best_index, best = max(
        candidates,
        key=lambda pair: (pair[1].effective_power, pair[1].effective_toughness, -pair[0]),
    )
    if equipped_creature(equipment) is best:
        return None
    return best_index


def _choose_target_for_instruction(instruction: OracleInstruction, caster_index: int, game: Game) -> int:
    if is_mana_ability(instruction):
        # Mana goes to its controller's pool; the ability has no other target.
        return caster_index
    if instruction.kind == "attach_source_to_target":
        # "Target creature you control" — the equip's creature is the
        # activator's own (CR 702.6a).
        return caster_index
    # A gift names its own seat: "target player gains 3 life", "target player
    # draws a card", "prevent the next 1 damage that would be dealt to any
    # target". *Which* effects those are is `ai_target_sides.ability_seat_side`'s
    # reading of the compiled program — this line used to name three kinds, two
    # of which nothing compiles, so a life gain and every shield went to an
    # opponent.
    if ability_seat_side(instruction) == "you":
        return caster_index
    # "deal_damage"/"destroy_target"/etc., and the fallback for any other
    # proactive effect: target an opponent (MVP heuristic, see
    # choose_attack_target — lowest life among living opponents).
    return choose_attack_target(game, caster_index)
