"""Whose is it — the seat and ownership half of a noun phrase.

"creature **you control**", "permanent **an opponent owns**", "creatures **your
opponents control**", "artifact **defending player controls**", and the two
CR 614.1c choices a source records as it enters ("of the chosen color", "of the
chosen type"). Every reading here writes a seat or an ownership onto the filter
and nothing else, and the distinctions are load-bearing in the direction a
dropped word fails: "you both own and control" read as "you control" compiles
Obelisk of Undoing as returning the stolen permanent it is printed to exclude,
and "own or control" read as either half alone is the strictly smaller set.

Split off `postmodifiers.py` at Weatherlight's Phase 0, when that module sat one
line from the thousand-line guard with a wave about to open on it. The block was
the head of `_parse_postmodifiers`' loop and asks one question; what stays
behind asks the others — combat relations, zones, records, nested phrases. A
floor rather than a family: `postmodifiers` reads it and it reads nothing back.
"""

from .stream import TokenStream


def accept_seat_relation(stream: TokenStream, d) -> bool:
    """Read one seat or ownership postmodifier onto *d*.

    True when a branch consumed its phrase — the caller's loop continues, as
    its own ``continue`` did — and False, having consumed nothing, when none
    opens at the cursor. Order inside is the order the loop always tried them
    in, which matters: three of these are prefixes of others.
    """
    # "you both own and control" (Obelisk of Undoing). Read before the bare
    # "you control", which is its suffix: matching that first would consume
    # "control" and strand "own", and — worse — would compile the card as
    # though it read "any permanent you control", which is exactly the
    # stolen permanent it is printed to exclude.
    if stream.accept_phrase("you", "both", "own", "and", "control"):
        d.controller = "you"
        d.owned_by = "you"
        return True
    # "you **own or control**" (Telim'Tor's Edict). Read beside the "both
    # own and control" branch above and before the bare "you control",
    # whose prefix it also is: matched there, "or control" would strand
    # "own" — and, worse, would compile the card as the strictly *smaller*
    # set, dropping the permanent an opponent has taken from you, which is
    # half of what this card is for.
    if stream.accept_phrase("you", "own", "or", "control"):
        d.owner_or_controller = "you"
        return True
    if stream.accept_phrase("you", "control"):
        d.controller = "you"
        return True
    # "all Auras **you own** attached to permanents you control" (Remove
    # Enchantments). Ownership alone, with no word about control: the card
    # is deliberately naming a different seat for the Aura than for its
    # host, so reading this as "you control" would return an Aura you own
    # that an opponent has taken — and dropping it would return theirs.
    # Read *after* the "both own and control" branch above, which this is a
    # suffix of.
    if stream.accept_phrase("you", "own"):
        d.owned_by = "you"
        return True
    # "you don't control" (Teferi, Master of Time's −3). The lexer keeps
    # "don't" as one word.
    if stream.accept_phrase("you", "don't", "control"):
        d.controller = "not_you"
        return True
    # "target artifact **a player controls**" (Goblin Welder). The *indefinite*
    # seat, and the one reading here that narrows nothing: every permanent on
    # the battlefield is controlled by somebody (CR 110.2a), so the set the
    # phrase leaves behind is the set the noun already named.
    #
    # It is still recorded rather than consumed and dropped, because the phrase
    # is the sentence's **binding site**: the words behind it point back at the
    # seat it named ("…and target artifact card in **that player's**
    # graveyard"). Dropping the phrase and dropping the binding are the same
    # edit, and only the second one is wrong — the card would then let the
    # returned card come out of anybody's graveyard.
    #
    # Read before "an opponent controls" only for tidiness; the two share no
    # prefix. It is emphatically *not* "you control" — a value this key has no
    # branch for falls through to that comparison below, which is the reading
    # that would take the opponent's artifacts away from the picker.
    if stream.accept_phrase("a", "player", "controls"):
        d.controller = "any_player"
        return True
    # "Basic lands **each player controls** have shroud as long as **that
    # player** controls three or fewer lands." (Sheltering Prayers.) The
    # distributive spelling of the row above, in the relation "each opponent
    # controls" bears to "your opponents control" below: a quantifier over the
    # seats narrows none of the objects, so it is the same key — and the same
    # binding site, which is the half that matters here. "That player" behind
    # it is each land's own controller, and the lowering that reads the
    # condition finds its referent by this key.
    if stream.accept_phrase("each", "player", "controls"):
        d.controller = "any_player"
        return True
    if stream.accept_phrase("an", "opponent", "controls"):
        d.controller = "opponent"
        return True
    # "target nontoken permanent an opponent **owns**" (Bronze Tablet).
    # Ownership, not control (CR 108.3 against CR 613 layer 2) — a card
    # printed with "owns" excludes the permanent it stole from that
    # opponent, and reading one as the other is exactly the mistake round
    # 13 recorded about Obelisk of Undoing.
    if stream.accept_phrase("an", "opponent", "owns"):
        d.owned_by = "opponent"
        return True
    # "creatures **your opponents** control" (Massacre Wurm, Waker of
    # Waves) — the plural spelling of the same scope: every opponent's
    # creatures, and none of the controller's own.
    if stream.accept_phrase("your", "opponents", "control"):
        d.controller = "opponent"
        return True
    # "each creature **each opponent** controls" (Aku Djinn) — the
    # distributive spelling of the two above. CR 109.5 reads "opponent"
    # against the ability's controller, and "each opponent" names exactly
    # the set "your opponents" does, so it is the same filter key rather
    # than a third one: a quantifier over the seats is not a narrowing of
    # the objects. Kept beside its siblings so the three spellings of one
    # scope are read in one place.
    if stream.accept_phrase("each", "opponent", "controls"):
        d.controller = "opponent"
        return True
    # "each creature target opponent controls" (Teferi, Timeless Voyager's
    # −8): the controller is a chosen player — the spell targets the
    # opponent, not the creatures.
    if stream.accept_phrase("target", "opponent", "controls"):
        d.controller = "target_opponent"
        return True
    # "Destroy all creatures **target player** controls." (Mogg Infestation.)
    # The row above with CR 102's wider noun: the spell chooses a seat and the
    # objects are described relative to it, so it is a targeted-seat key rather
    # than a relative one — `subject_matches` already answers both under the
    # same branch, and `targeting.py` already offers a player picker for it.
    #
    # Not folded into "target opponent": a player may be their own target
    # (Mogg Infestation is printed to be aimed either way), and reading the
    # narrower word would take a legal announcement away from the caster.
    if stream.accept_phrase("target", "player", "controls"):
        d.controller = "target_player"
        return True

    # "Non-Wall creatures **the active player controls**" (Maddening Imp),
    # "Creatures **the active player controls**" (Siren's Call). CR 102.1: the
    # player whose turn it is — a seat the *game* always knows, which is what
    # separates it from the three relative seats below and above. It needs no
    # observer, no target and no combat: `subject_matches` reads
    # ``active_player_index`` directly, so a caller with a game can answer it
    # and one without refuses like every other seat word.
    #
    # Read before "defending player controls" only for tidiness; the two share
    # no prefix. It is *not* "an opponent controls": on a turn with three seats
    # the active player is one opponent out of two, and on your own turn — which
    # is when Maddening Imp's restriction forbids the activation and Siren's
    # Call's forbids the cast, rather than making the phrase impossible — it is
    # you.
    if stream.accept_phrase("the", "active", "player", "controls"):
        d.controller = "active_player"
        return True
    # "target artifact **defending player controls**" (Floral Spuzzem).
    # A seat only the combat that fired the trigger knows, so it is carried
    # like `that_player` beside it — refused by the pure matcher and
    # resolved by whoever holds the event's context. Reading it as
    # "opponent" would be right in a duel by coincidence and wrong the
    # moment a third seat is not the one being attacked.
    if stream.accept_phrase("defending", "player", "controls"):
        d.controller = "defending_player"
        return True
    # "nontoken permanents **of the chosen color** they control" (Psychic
    # Allergy). CR 614.1c's choice, made as the source entered and stored on
    # it — so the phrase narrows by a colour the sentence never names and
    # only a reader holding the *source* can answer. That is why it is its
    # own filter key rather than a colour: `permanent_matches_filter` is the
    # pure half and refuses the key outright, and the two readers that do
    # have a source (`subject_matches`, `evaluate_count`) resolve it before
    # matching.
    if stream.accept_phrase("of", "the", "chosen", "color"):
        d.chosen_color = True
        return True
    # "Choose a color. Target player reveals their hand and discards all cards
    # **of that color**." (Persecute.) The same narrowing with the choice made
    # at a different time — CR 608.2d, while this spell resolves, rather than
    # CR 614.1c as a permanent entered — which is precisely the distinction the
    # creature-type pair below already draws. Its own key for that pair's
    # reason: there is no permanent here to have recorded a word, so the
    # readers that answer the row above cannot answer this one.
    #
    # Read after that row and before the type readings; the four phrases share
    # only the word "of" and each consumes or resets whole.
    if stream.accept_phrase("of", "that", "color"):
        d.color_chosen_this_way = True
        return True
    # "Return all permanents **of the color of your choice** to their owners'
    # hands." (Wash Out.) The row above with nobody having chosen yet: the
    # choice is made while this very sentence is applied (CR 608.2d), so the
    # lowering puts the choosing step in front and the sweep spends it — the
    # arrangement the creature-type row below has had since Extinction.
    if stream.accept_phrase("of", "the", "color", "of", "your", "choice"):
        d.color_of_your_choice = True
        return True
    # "Creatures **of the chosen type**" (An-Zerrin Ruins). The same
    # CR 614.1c choice one characteristic over — a creature type recorded
    # on the source as it entered — so it is its own filter key for the
    # colour's reason: the pure matcher has no source and refuses the key
    # outright, and the readers that do hold one resolve it into the
    # ordinary subtype key before matching.
    # "Destroy all creatures **of the creature type of your choice**."
    # (Extinction.) The same narrowing as "of the chosen type" below with the
    # choice made at a different time — CR 608.2d, while the spell resolves,
    # rather than CR 614.1c, as a permanent entered. That difference is the
    # whole of it: there is no source permanent to have recorded a word, so the
    # phrase cannot share the key below, whose readers all resolve it off one.
    #
    # The catalog is named in the phrase itself here rather than inferred from
    # the head noun, so nothing has to be guessed; a land-type spelling would be
    # its own branch when a card prints one.
    if stream.accept_phrase(
        "of", "the", "creature", "type", "of", "your", "choice"
    ):
        d.creature_type_of_your_choice = True
        return True
    if stream.accept_phrase("of", "the", "chosen", "type"):
        # Which catalog the chosen word came from is spelled once, in the
        # **head noun**: "Each *land* of the chosen type" (Shimmer) is a
        # land type (CR 205.3i) and "*Creatures* of the chosen type"
        # (An-Zerrin Ruins) a creature type (CR 205.3m). The phrase itself
        # is identical, so reading it as one key would store Shimmer's
        # Desert under a creature type's name — and the two choices are
        # recorded separately on the source, which is what the reader
        # holding that source resolves them from.
        #
        # A noun that names **no** card type at all has no catalog for the
        # phrase to draw a subtype from, and that is the third reading:
        # "Tap all untapped **permanents** of the chosen type target player
        # controls" (Turnabout) is CR 205.2's card types, chosen by the
        # sentence in front of it out of a printed list. It lands on the same
        # field "of **that** type" does (Teferi's Realm) because it is the same
        # relation — a type an earlier sentence of this ability recorded — and
        # a fourth key would be a second name for one question.
        if "land" in d.card_types:
            d.chosen_land_type = True
        elif "creature" in d.card_types:
            d.chosen_creature_type = True
        else:
            d.of_bound_type = True
        return True
    return False
