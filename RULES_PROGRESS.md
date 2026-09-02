# Comprehensive Rules Test Coverage

Coverage of `tests/rules/` against the Comprehensive Rules (April 17, 2026).
Tests cite rules with `@pytest.mark.cr(...)`; regenerate this file with
`python scripts/rules_progress.py`. Tracked scope is defined in that
script — rules for mechanics outside the Alpha-era pool are omitted.

**342 / 612 tracked rules covered (55%)** — 1790 tests, 0 unannotated.

| Section | Covered | % |
| --- | --- | --- |
| [100. General](#100-general) | 0/7 | 0% |
| [101. The Magic Golden Rules](#101-the-magic-golden-rules) | 3/4 | 75% |
| [102. Players](#102-players) | 1/4 | 25% |
| [103. Starting the Game](#103-starting-the-game) | 4/8 | 50% |
| [104. Ending the Game](#104-ending-the-game) | 5/5 | 100% |
| [105. Colors](#105-colors) | 2/5 | 40% |
| [106. Mana](#106-mana) | 5/13 | 38% |
| [107. Numbers and Symbols](#107-numbers-and-symbols) | 5/18 | 27% |
| [108. Cards](#108-cards) | 1/6 | 16% |
| [109. Objects](#109-objects) | 1/5 | 20% |
| [110. Permanents](#110-permanents) | 0/5 | 0% |
| [111. Tokens](#111-tokens) | 5/13 | 38% |
| [112. Spells](#112-spells) | 0/4 | 0% |
| [113. Abilities](#113-abilities) | 2/12 | 16% |
| [114. Emblems](#114-emblems) | 5/5 | 100% |
| [115. Targets](#115-targets) | 8/10 | 80% |
| [116. Special Actions](#116-special-actions) | 3/3 | 100% |
| [117. Timing and Priority](#117-timing-and-priority) | 6/6 | 100% |
| [118. Costs](#118-costs) | 9/14 | 64% |
| [119. Life](#119-life) | 3/10 | 30% |
| [120. Damage](#120-damage) | 5/10 | 50% |
| [121. Drawing a Card](#121-drawing-a-card) | 3/9 | 33% |
| [122. Counters](#122-counters) | 4/9 | 44% |
| [200. General](#200-general) | 0/3 | 0% |
| [201. Name](#201-name) | 1/6 | 16% |
| [202. Mana Cost and Color](#202-mana-cost-and-color) | 2/4 | 50% |
| [205. Type Line](#205-type-line) | 4/4 | 100% |
| [207. Text Box](#207-text-box) | 0/5 | 0% |
| [208. Power/Toughness](#208-powertoughness) | 1/5 | 20% |
| [300. General](#300-general) | 0/2 | 0% |
| [301. Artifacts](#301-artifacts) | 1/7 | 14% |
| [302. Creatures](#302-creatures) | 1/7 | 14% |
| [303. Enchantments](#303-enchantments) | 7/7 | 100% |
| [304. Instants](#304-instants) | 0/5 | 0% |
| [305. Lands](#305-lands) | 3/9 | 33% |
| [306. Planeswalkers](#306-planeswalkers) | 9/9 | 100% |
| [307. Sorceries](#307-sorceries) | 1/5 | 20% |
| [400. General](#400-general) | 5/12 | 41% |
| [401. Library](#401-library) | 4/7 | 57% |
| [402. Hand](#402-hand) | 3/3 | 100% |
| [403. Battlefield](#403-battlefield) | 3/5 | 60% |
| [404. Graveyard](#404-graveyard) | 1/3 | 33% |
| [405. Stack](#405-stack) | 6/6 | 100% |
| [406. Exile](#406-exile) | 2/8 | 25% |
| [407. Ante](#407-ante) | 4/4 | 100% |
| [408. Command](#408-command) | 3/3 | 100% |
| [500. General](#500-general) | 6/12 | 50% |
| [501. Beginning Phase](#501-beginning-phase) | 1/1 | 100% |
| [502. Untap Step](#502-untap-step) | 3/4 | 75% |
| [503. Upkeep Step](#503-upkeep-step) | 1/2 | 50% |
| [504. Draw Step](#504-draw-step) | 2/2 | 100% |
| [505. Main Phase](#505-main-phase) | 3/6 | 50% |
| [506. Combat Phase](#506-combat-phase) | 7/7 | 100% |
| [507. Beginning of Combat Step](#507-beginning-of-combat-step) | 1/2 | 50% |
| [508. Declare Attackers Step](#508-declare-attackers-step) | 4/8 | 50% |
| [509. Declare Blockers Step](#509-declare-blockers-step) | 4/4 | 100% |
| [510. Combat Damage Step](#510-combat-damage-step) | 4/4 | 100% |
| [511. End of Combat Step](#511-end-of-combat-step) | 3/3 | 100% |
| [512. Ending Phase](#512-ending-phase) | 1/1 | 100% |
| [513. End Step](#513-end-step) | 1/2 | 50% |
| [514. Cleanup Step](#514-cleanup-step) | 3/3 | 100% |
| [601. Casting Spells](#601-casting-spells) | 4/7 | 57% |
| [602. Activating Activated Abilities](#602-activating-activated-abilities) | 3/5 | 60% |
| [603. Handling Triggered Abilities](#603-handling-triggered-abilities) | 10/12 | 83% |
| [604. Handling Static Abilities](#604-handling-static-abilities) | 3/7 | 42% |
| [605. Mana Abilities](#605-mana-abilities) | 5/5 | 100% |
| [606. Loyalty Abilities](#606-loyalty-abilities) | 5/6 | 83% |
| [607. Linked Abilities](#607-linked-abilities) | 2/5 | 40% |
| [608. Resolving Spells and Abilities](#608-resolving-spells-and-abilities) | 3/3 | 100% |
| [609. Effects](#609-effects) | 5/7 | 71% |
| [610. One-Shot Effects](#610-one-shot-effects) | 2/5 | 40% |
| [611. Continuous Effects](#611-continuous-effects) | 3/3 | 100% |
| [612. Text-Changing Effects](#612-text-changing-effects) | 3/10 | 30% |
| [613. Interaction of Continuous Effects](#613-interaction-of-continuous-effects) | 8/11 | 72% |
| [614. Replacement Effects](#614-replacement-effects) | 9/17 | 52% |
| [615. Prevention Effects](#615-prevention-effects) | 7/13 | 53% |
| [616. Interaction of Replacement and/or Prevention Effects](#616-interaction-of-replacement-andor-prevention-effects) | 2/2 | 100% |
| [700. General](#700-general) | 2/15 | 13% |
| [701. Keyword Actions](#701-keyword-actions) | 19/19 | 100% |
| [702. Keyword Abilities](#702-keyword-abilities) | 27/27 | 100% |
| [703. Turn-Based Actions](#703-turn-based-actions) | 0/4 | 0% |
| [704. State-Based Actions](#704-state-based-actions) | 5/8 | 62% |
| [705. Flipping a Coin](#705-flipping-a-coin) | 2/3 | 66% |
| [707. Copying Objects](#707-copying-objects) | 6/14 | 42% |
| [724. Ending Turns and Phases](#724-ending-turns-and-phases) | 1/2 | 50% |
| [800. General](#800-general) | 2/7 | 28% |
| [802. Attack Multiple Players Option](#802-attack-multiple-players-option) | 5/5 | 100% |
| [806. Free-for-All Variant](#806-free-for-all-variant) | 2/3 | 66% |
| [903. Commander](#903-commander) | 12/12 | 100% |

## Rule detail

### 100. General

- [ ] **100.1** These Magic rules apply to any Magic game with two or more players, including two-player games an...
- [ ] **100.2** To play, each player needs their own deck of traditional Magic cards, small items to represent an...
- [ ] **100.3** Some cards require coins or traditional dice. Some casual variants require additional items, such...
- [ ] **100.4** Each player may also have a sideboard, which is a group of additional cards the player may use to...
- [ ] **100.5** If a deck must contain at least a certain number of cards, that number is referred to as a minimu...
- [ ] **100.6** Most Magic tournaments (organized play activities where players compete against other players to ...
- [ ] **100.7** Certain cards are intended for casual play and may have features and text that aren’t covered by ...

### 101. The Magic Golden Rules

- [x] **101.1** Whenever a card’s text directly contradicts these rules, the card takes precedence. The card over... *(1 tests)*
- [x] **101.2** When a rule or effect allows or directs something to happen, and another effect states that it ca... *(1 tests)*
- [ ] **101.3** Any part of an instruction that’s impossible to perform is ignored. (In many cases the card will ...
- [x] **101.4** If multiple players would make choices and/or take actions at the same time, the active player (t... *(2 tests)*

### 102. Players

- [ ] **102.1** A player is one of the people in the game. The active player is the player whose turn it is. The ...
- [ ] **102.2** In a two-player game, a player’s opponent is the other player.
- [x] **102.3** In a multiplayer game between teams, a player’s teammates are the other players on their team, an... *(1 tests)*
- [ ] **102.4** A spell or ability may use the term “your team” as shorthand for “you and/or your teammates.” In ...

### 103. Starting the Game

- [x] **103.1** At the start of a game, the players determine which one of them will choose who takes the first t... *(6 tests)*
- [ ] **103.2** Some games require additional steps that are taken after the starting player has been determined....
- [x] **103.3** After the starting player has been determined and any additional steps performed, each player shu... *(1 tests)*
- [ ] **103.4** Each player begins the game with a starting life total of 20. Some variant games have different s...
- [x] **103.5** Each player draws a number of cards equal to their starting hand size, which is normally seven. (... *(23 tests, subrules c)*
- [ ] **103.6** Some cards allow a player to take actions with them from their opening hand. Once the mulligan pr...
- [ ] **103.7** In a Planechase game, the starting player moves the top card of their planar deck off that planar...
- [x] **103.8** The starting player takes their first turn. *(2 tests, subrules ac)*

### 104. Ending the Game

- [x] **104.1** A game ends immediately when a player wins, when the game is a draw, or when the game is restarted. *(6 tests)*
- [x] **104.2** There are several ways to win the game. *(13 tests, subrules ab)*
- [x] **104.3** There are several ways to lose the game. *(24 tests, subrules abcdefj)*
- [x] **104.4** There are several ways for the game to be a draw. *(9 tests, subrules ac)*
- [x] **104.5** If a player loses the game, that player leaves the game. If the game is a draw for a player, that... *(2 tests)*

### 105. Colors

- [x] **105.1** There are five colors in the Magic game: white, blue, black, red, and green. *(3 tests)*
- [x] **105.2** An object can be one or more of the five colors, or it can be no color at all. An object is the c... *(8 tests, subrules abc)*
- [ ] **105.3** Effects may change an object’s color or give a color to a colorless object. If an effect gives an...
- [ ] **105.4** If a player is asked to choose a color, they must choose one of the five colors. “Multicolored” i...
- [ ] **105.5** If an effect refers to a color pair, it means exactly two of the five colors. There are ten color...

### 106. Mana

- [x] **106.1** Mana is the primary resource in the game. Players spend mana to pay costs, usually when casting s... *(3 tests, subrules b)*
- [ ] **106.2** Mana is represented by mana symbols (see rule 107.4). Mana symbols also represent mana costs (see...
- [x] **106.3** Mana is produced by the effects of mana abilities (see rule 605). It may also be produced by the ... *(2 tests)*
- [x] **106.4** When an effect instructs a player to add mana, that mana goes into a player’s mana pool. From the... *(4 tests)*
- [ ] **106.5** If an ability would produce one or more mana of an undefined type, it produces no mana instead.
- [x] **106.6** Some spells or abilities that produce mana restrict how that mana can be spent, have an additiona... *(5 tests)*
- [ ] **106.7** Some abilities produce mana based on the type of mana another permanent or permanents “could prod...
- [ ] **106.8** If an effect would add mana represented by a hybrid mana symbol to a player’s mana pool, that pla...
- [ ] **106.9** If an effect would add mana represented by a Phyrexian mana symbol to a player’s mana pool, one m...
- [ ] **106.10** If an effect would add mana represented by a generic mana symbol to a player’s mana pool, that mu...
- [ ] **106.11** If an effect would add mana represented by one or more snow mana symbols to a player’s mana pool,...
- [x] **106.12** To “tap [a permanent] for mana” is to activate a mana ability of that permanent that includes the... *(2 tests, subrules a)*
- [ ] **106.13** One card (Drain Power) causes one player to lose unspent mana and another to add “the mana lost t...

### 107. Numbers and Symbols

- [x] **107.1** The only numbers the Magic game uses are integers. *(1 tests, subrules a)*
- [x] **107.2** If anything needs to use a number that can’t be determined, either as a result or in a calculatio... *(1 tests)*
- [x] **107.3** Many objects use the letter X as a placeholder for a number that needs to be determined. Some obj... *(5 tests, subrules ab)*
- [x] **107.4** The mana symbols are {W}, {U}, {B}, {R}, {G}, and {C}; the numerical symbols {0}, {1}, {2}, {3}, ... *(4 tests)*
- [x] **107.5** The tap symbol is {T}. The tap symbol in an activation cost means “Tap this permanent.” A permane... *(2 tests)*
- [ ] **107.6** The untap symbol is {Q}. The untap symbol in an activation cost means “Untap this permanent.” A p...
- [ ] **107.7** Each activated ability of a planeswalker has a loyalty symbol in its cost. Positive loyalty symbo...
- [ ] **107.8** The text box of a leveler card contains two level symbols, each of which is a keyword ability tha...
- [ ] **107.9** A tombstone icon appears to the left of the name of many Odyssey™ block cards with abilities that...
- [ ] **107.10** A type icon appears in the upper left corner of each card from the Future Sight™ set printed with...
- [ ] **107.11** The Planeswalker symbol is {PW}. It appears on one face of the planar die used in the Planechase ...
- [ ] **107.12** The chaos symbol is {CHAOS}. It appears on one face of the planar die used in the Planechase casu...
- [ ] **107.13** A color indicator is a circular symbol that appears to the left of the type line on some cards. T...
- [ ] **107.14** The energy symbol is {E}. It represents one energy counter. To pay {E}, a player removes one ener...
- [ ] **107.15** The text box of a Saga card contains chapter symbols, each of which is a keyword ability that rep...
- [ ] **107.16** The text box of a Class card contains class level bars, each of which is a keyword ability that r...
- [ ] **107.17** The ticket symbol is {TK}. It represents one ticket counter.
- [ ] **107.18** The pawprint symbol is {P}. This symbol is used to indicate the modes on some modal spells, and d...

### 108. Cards

- [ ] **108.1** Use the Oracle card reference when determining a card’s wording. A card’s Oracle text can be foun...
- [ ] **108.2** When a rule or text on a card refers to a “card,” it means only a Magic card or an object represe...
- [x] **108.3** The owner of a card in the game is the player who started the game with it in their deck. If a ca... *(8 tests)*
- [ ] **108.4** A card doesn’t have a controller unless that card represents a permanent or spell; in those cases...
- [ ] **108.5** Nontraditional Magic cards can’t start the game in any zone other than the command zone (see rule...
- [ ] **108.6** For more information about cards, see section 2, “Parts of a Card.”

### 109. Objects

- [ ] **109.1** An object is an ability on the stack, a card, a copy of a card, a token, a spell, a permanent, or...
- [ ] **109.2** If a spell or ability uses a description of an object that includes a card type or subtype, but d...
- [ ] **109.3** An object’s characteristics are name, mana cost, color, color indicator, card type, subtype, supe...
- [ ] **109.4** Only objects on the stack or on the battlefield have a controller. Objects that are neither on th...
- [x] **109.5** The words “you” and “your” on an object refer to the object’s controller, its would-be controller... *(10 tests)*

### 110. Permanents

- [ ] **110.1** A permanent is a card or token on the battlefield. A permanent remains on the battlefield indefin...
- [ ] **110.2** A permanent’s owner is the same as the owner of the card that represents it (unless it’s a token;...
- [ ] **110.3** A nontoken permanent’s characteristics are the same as those printed on its card, as modified by ...
- [ ] **110.4** There are six permanent types: artifact, battle, creature, enchantment, land, and planeswalker. I...
- [ ] **110.5** A permanent’s status is its physical state. There are four status categories, each of which has t...

### 111. Tokens

- [x] **111.1** Some effects put tokens onto the battlefield. A token is a marker used to represent any permanent... *(2 tests)*
- [x] **111.2** The player who creates a token is its owner. The token enters the battlefield under that player’s... *(1 tests)*
- [ ] **111.3** The spell or ability that creates a token may define the values of any number of characteristics ...
- [x] **111.4** A spell or ability that creates a token sets both its name and its subtype(s). If the spell or ab... *(2 tests)*
- [ ] **111.5** If a spell or ability would create a token, but a rule or effect states that a permanent with one...
- [ ] **111.6** A token is subject to anything that affects permanents in general or that affects the token’s car...
- [x] **111.7** A token that’s in a zone other than the battlefield ceases to exist. This is a state-based action... *(6 tests)*
- [ ] **111.8** A token that has left the battlefield can’t move to another zone or come back onto the battlefiel...
- [ ] **111.9** Some effects instruct a player to create a legendary token. These may be written “create [name], ...
- [x] **111.10** Some effects instruct a player to create a predefined token. These effects use the definition bel... *(2 tests)*
- [ ] **111.11** If an effect instructs a player to create a token by name, doesn’t define any other characteristi...
- [ ] **111.12** If an effect instructs a player to create a token that is a copy of a nonexistent object, no toke...
- [ ] **111.13** A copy of a permanent spell becomes a token as it resolves. The token has the characteristics of ...

### 112. Spells

- [ ] **112.1** A spell is a card on the stack. As the first step of being cast (see rule 601, “Casting Spells”),...
- [ ] **112.2** A spell’s owner is the same as the owner of the card that represents it, unless it’s a copy. In t...
- [ ] **112.3** A noncopy spell’s characteristics are the same as those printed on its card, as modified by any c...
- [ ] **112.4** If an effect of a resolving spell or ability changes any characteristics of a permanent spell, th...

### 113. Abilities

- [ ] **113.1** An ability can be one of three things:
- [ ] **113.2** Abilities can affect the objects they’re on. They can also affect other objects and/or players.
- [ ] **113.3** There are four general categories of abilities:
- [ ] **113.4** Some activated abilities and some triggered abilities are mana abilities. Mana abilities follow s...
- [ ] **113.5** Some activated abilities are loyalty abilities. Loyalty abilities follow special rules: A player ...
- [x] **113.6** Abilities of an instant or sorcery spell usually function only while that object is on the stack.... *(5 tests, subrules m)*
- [x] **113.7** The source of an ability is the object that generated it. The source of an activated ability on t... *(4 tests, subrules a)*
- [ ] **113.8** The controller of an activated ability on the stack is the player who activated it. The controlle...
- [ ] **113.9** Activated and triggered abilities on the stack aren’t spells, and therefore can’t be countered by...
- [ ] **113.10** Effects can add or remove abilities of objects. An effect that adds an ability will state that th...
- [ ] **113.11** Effects can stop an object from having a specified ability. These effects say that the object “ca...
- [ ] **113.12** An effect that sets an object’s characteristic, or simply states a quality of that object, is dif...

### 114. Emblems

- [x] **114.1** Some effects put emblems into the command zone. An emblem is a marker used to represent an object... *(2 tests)*
- [x] **114.2** An effect that creates an emblem is written “[Player] gets an emblem with [ability].” This means ... *(2 tests)*
- [x] **114.3** An emblem has no characteristics other than the abilities defined by the effect that created it. ... *(2 tests)*
- [x] **114.4** Abilities of emblems function in the command zone. *(1 tests)*
- [x] **114.5** An emblem is neither a card nor a permanent. Emblem isn’t a card type. *(1 tests)*

### 115. Targets

- [x] **115.1** Some spells and abilities require their controller to choose one or more targets for them. The ta... *(16 tests, subrules abcd)*
- [x] **115.2** Only permanents are legal targets for spells and abilities, unless a spell or ability (a) specifi... *(3 tests)*
- [ ] **115.3** The same target can’t be chosen multiple times for any one instance of the word “target” on a spe...
- [x] **115.4** Some spells and abilities that refer to damage require “any target,” “another target,” “two targe... *(2 tests)*
- [ ] **115.5** A spell or ability on the stack is an illegal target for itself.
- [x] **115.6** A spell or ability that requires targets may allow zero targets to be chosen. Such a spell or abi... *(4 tests)*
- [x] **115.7** Some effects allow a player to change the target(s) of a spell or ability, and other effects allo... *(3 tests, subrules a)*
- [x] **115.8** Modal spells and abilities may have different targeting requirements for each mode. An effect tha... *(1 tests)*
- [x] **115.9** Some objects check what another spell or ability is targeting. Depending on the wording, these ma... *(1 tests, subrules a)*
- [x] **115.10** Spells and abilities can affect objects and players they don’t target. In general, those objects ... *(2 tests, subrules a)*

### 116. Special Actions

- [x] **116.1** Special actions are actions a player may take when they have priority that don’t use the stack. T... *(4 tests)*
- [x] **116.2** There are twelve special actions: *(7 tests, subrules a)*
- [x] **116.3** If a player takes a special action, that player receives priority afterward. *(2 tests)*

### 117. Timing and Priority

- [x] **117.1** Unless a spell or ability is instructing a player to take an action, which player can take action... *(2 tests)*
- [x] **117.2** Other kinds of abilities and actions are automatically generated or performed by the game rules, ... *(1 tests, subrules c)*
- [x] **117.3** Which player has priority is determined by the following rules: *(14 tests, subrules abcd)*
- [x] **117.4** If all players pass in succession (that is, if all players pass without taking any actions in bet... *(3 tests)*
- [x] **117.5** Each time a player would get priority, the game first performs all applicable state-based actions... *(1 tests)*
- [x] **117.7** If a player with priority casts a spell or activates an activated ability while another spell or ... *(1 tests)*

### 118. Costs

- [x] **118.1** A cost is an action or payment necessary to take another action or to stop another action from ta... *(1 tests)*
- [x] **118.2** If a cost includes a mana payment, the player paying the cost has a chance to activate mana abili... *(1 tests)*
- [x] **118.3** A player can’t pay a cost without having the necessary resources to pay it fully. For example, a ... *(10 tests, subrules ab)*
- [x] **118.4** Some costs include an {X} or an X. See rule 107.3. *(1 tests)*
- [x] **118.5** Some costs are represented by {0}, or are reduced to {0}. The action necessary for a player to pa... *(3 tests, subrules a)*
- [x] **118.6** Some objects have no mana cost. This represents an unpayable cost. An ability can also have an un... *(1 tests)*
- [x] **118.7** What a player actually needs to do to pay a cost may be changed or reduced by effects. If the man... *(6 tests, subrules abc)*
- [x] **118.8** Some spells and abilities have additional costs. An additional cost is a cost listed in a spell’s... *(5 tests)*
- [x] **118.9** Some spells have alternative costs. An alternative cost is a cost listed in a spell’s text, or ap... *(1 tests)*
- [ ] **118.10** Each payment of a cost applies to only one spell, ability, or effect. For example, a player can’t...
- [ ] **118.11** The actions performed when paying a cost may be modified by effects. Even if they are, meaning th...
- [ ] **118.12** Some spells, activated abilities, and triggered abilities read, “[Do something]. If [a player] [d...
- [ ] **118.13** Some costs contain mana symbols that can be paid in multiple ways. These include hybrid mana symb...
- [ ] **118.14** Some effects say that “mana of any type can be spent” to pay a cost. This means that players may ...

### 119. Life

- [ ] **119.1** Each player begins the game with a starting life total of 20. Some variant games have different s...
- [ ] **119.2** Damage dealt to a player normally causes that player to lose that much life. See rule 120.3.
- [ ] **119.3** If an effect causes a player to gain life or lose life, that player’s life total is adjusted acco...
- [x] **119.4** If a cost or effect allows a player to pay an amount of life greater than 0, the player may do so... *(6 tests, subrules b)*
- [x] **119.5** If an effect sets a player’s life total to a specific number, the player gains or loses the neces... *(4 tests)*
- [ ] **119.6** If a player has 0 or less life, that player loses the game as a state-based action. See rule 704.
- [ ] **119.7** If an effect says that a player can’t gain life, that player can’t make an exchange such that the...
- [ ] **119.8** If an effect says that a player can’t lose life, that player can’t make an exchange such that the...
- [x] **119.9** Some triggered abilities are written, “Whenever [a player] gains life, . . . .” Such abilities ar... *(3 tests)*
- [ ] **119.10** Some replacement effects are written, “If [a player] would gain life, . . . .” Such abilities are...

### 120. Damage

- [x] **120.1** Objects can deal damage to battles, creatures, planeswalkers, and players. This is generally detr... *(1 tests, subrules a)*
- [ ] **120.2** Any object can deal damage.
- [x] **120.3** Damage may have one or more of the following results, depending on whether the recipient of the d... *(7 tests, subrules acf)*
- [x] **120.4** Damage is processed in a four-part sequence. *(12 tests, subrules bc)*
- [ ] **120.5** Damage dealt to a creature, planeswalker, or battle doesn’t destroy it. Likewise, the source of t...
- [ ] **120.6** Damage marked on a creature remains until the cleanup step, even if that permanent stops being a ...
- [x] **120.7** The source of damage is the object that dealt it. If an effect requires a player to choose a sour... *(1 tests)*
- [x] **120.8** If a source would deal 0 damage, it does not deal damage at all. That means abilities that trigge... *(2 tests)*
- [ ] **120.9** If an ability triggers on damage being dealt by a specific source or sources, and the effect refe...
- [ ] **120.10** Some triggered abilities check whether a permanent has been dealt excess damage. These abilities ...

### 121. Drawing a Card

- [x] **121.1** A player draws a card by putting the top card of their library into their hand. This is done as a... *(3 tests)*
- [x] **121.2** Cards may only be drawn one at a time. If a player is instructed to draw multiple cards, that pla... *(2 tests)*
- [ ] **121.3** If there are no cards in a player’s library and an effect offers that player the choice to draw a...
- [x] **121.4** A player who attempts to draw a card from a library with no cards in it loses the game the next t... *(3 tests)*
- [ ] **121.5** If an effect moves cards from a player’s library to that player’s hand without using the word “dr...
- [ ] **121.6** Some effects replace card draws.
- [ ] **121.7** Some replacement effects and prevention effects result in one or more card draws. In such a case,...
- [ ] **121.8** If a spell or ability causes a card to be drawn while another spell is being cast, the drawn card...
- [ ] **121.9** If an effect gives a player the option to reveal a card as they draw it, that player may look at ...

### 122. Counters

- [x] **122.1** A counter is a marker placed on an object or player that modifies its characteristics and/or inte... *(20 tests, subrules af)*
- [x] **122.2** Counters on an object are not retained if that object moves from one zone to another. The counter... *(1 tests)*
- [x] **122.3** If a permanent has both a +1/+1 counter and a -1/-1 counter on it, N +1/+1 and N -1/-1 counters a... *(2 tests)*
- [ ] **122.4** If a permanent with an ability that says it can’t have more than N counters of a certain kind on ...
- [ ] **122.5** If an effect says to “move” a counter, it means to remove that counter from the object it’s curre...
- [x] **122.6** Some spells and abilities refer to counters being put on an object. This refers to putting counte... *(2 tests)*
- [ ] **122.7** An ability that triggers “When/Whenever the Nth [kind] counter” is put on an object triggers when...
- [ ] **122.8** If a triggered ability instructs a player to put one object’s counters on another object and that...
- [ ] **122.9** If an activated ability of an object instructs a player to put its counters on another object and...

### 200. General

- [ ] **200.1** The parts of a card are name, mana cost, illustration, color indicator, type line, expansion symb...
- [ ] **200.2** Some parts of a card are also characteristics of the object that has them. See rule 109.3.
- [ ] **200.3** Some objects that aren’t cards (tokens, copies of cards, and copies of spells) have some of the p...

### 201. Name

- [ ] **201.1** The name of a card is printed on its upper left corner.
- [x] **201.2** A card’s name is always considered to be the English version of its name, regardless of printed l... *(1 tests, subrules a)*
- [ ] **201.3** Some cards with different English names are treated as though they had the same English name. Pai...
- [ ] **201.4** If an effect instructs a player to choose a card name, the player must choose the name of a card ...
- [ ] **201.5** Text that refers to the object it’s on by name means just that particular object and not any othe...
- [ ] **201.6** Promotional or alternate-art versions of some cards feature a secondary title bar below the name ...

### 202. Mana Cost and Color

- [x] **202.1** A card’s mana cost is indicated by mana symbols near the top of the card. (See rule 107.4.) On mo... *(3 tests, subrules ab)*
- [ ] **202.2** An object is the color or colors of the mana symbols in its mana cost, regardless of the color of...
- [x] **202.3** The mana value of an object is a number equal to the total amount of mana in its mana cost, regar... *(9 tests, subrules a)*
- [ ] **202.4** Any additional cost listed in an object’s rules text or imposed by an effect isn’t part of the ma...

### 205. Type Line

- [x] **205.1** The type line is printed directly below the illustration. It contains the card’s card type(s). It... *(5 tests, subrules ab)*
- [x] **205.2** Card Types *(8 tests, subrules ab)*
- [x] **205.3** Subtypes *(3 tests, subrules bi)*
- [x] **205.4** Supertypes *(10 tests, subrules abcd)*

### 207. Text Box

- [ ] **207.1** The text box is printed on the lower half of the card. It usually contains rules text defining th...
- [ ] **207.2** The text box may also contain italicized text that has no game function.
- [ ] **207.3** Some cards have decorative icons in the background of their text boxes. For example, a guild icon...
- [ ] **207.4** The chaos symbol appears in the text box of each plane card to the left of a triggered ability th...
- [ ] **207.5** One card (Cryptic Spires) has a set of symbols below the text box that represent each color and a...

### 208. Power/Toughness

- [x] **208.1** A creature card has two numbers separated by a slash printed in its lower right corner. The first... *(1 tests)*
- [ ] **208.2** Rather than a fixed number, some creature cards have power and/or toughness that includes a star ...
- [ ] **208.3** A noncreature permanent has no power or toughness, even if it’s a card with a power and toughness...
- [ ] **208.4** Some effects refer to a creature’s “base power,” “base toughness,” or “base power and toughness.”
- [ ] **208.5** If a creature somehow has no value for its power, its power is 0. The same is true for toughness.

### 300. General

- [ ] **300.1** The card types are artifact, battle, conspiracy, creature, dungeon, enchantment, instant, kindred...
- [ ] **300.2** Some objects have more than one card type (for example, an artifact creature). Such objects combi...

### 301. Artifacts

- [ ] **301.1** A player who has priority may cast an artifact card from their hand during a main phase of their ...
- [ ] **301.2** When an artifact spell resolves, its controller puts it onto the battlefield under their control.
- [ ] **301.3** Artifact subtypes are always a single word and are listed after a long dash: “Artifact — Equipmen...
- [ ] **301.4** Artifacts have no characteristics specific to their card type. Most artifacts have no colored man...
- [x] **301.5** Some artifacts have the subtype “Equipment.” An Equipment can be attached to a creature. It can’t... *(13 tests, subrules abcdf)*
- [ ] **301.6** Some artifacts have the subtype “Fortification.” A Fortification can be attached to a land. It ca...
- [ ] **301.7** Some artifacts have the subtype “Vehicle.” Most Vehicles have a crew ability which allows them to...

### 302. Creatures

- [ ] **302.1** A player who has priority may cast a creature card from their hand during a main phase of their t...
- [ ] **302.2** When a creature spell resolves, its controller puts it onto the battlefield under their control.
- [ ] **302.3** Creature subtypes are usually a single word long and are listed after a long dash: “Creature — Hu...
- [ ] **302.4** Power and toughness are characteristics only creatures have.
- [ ] **302.5** Creatures can attack and block. (See rule 508, “Declare Attackers Step,” and rule 509, “Declare B...
- [x] **302.6** A creature’s activated ability with the tap symbol or the untap symbol in its activation cost can... *(5 tests)*
- [ ] **302.7** Damage dealt to a creature by a source with neither wither nor infect is marked on that creature ...

### 303. Enchantments

- [x] **303.1** A player who has priority may cast an enchantment card from their hand during a main phase of the... *(2 tests)*
- [x] **303.2** When an enchantment spell resolves, its controller puts it onto the battlefield under their control. *(4 tests)*
- [x] **303.3** Enchantment subtypes are always a single word and are listed after a long dash: “Enchantment — Sh... *(3 tests)*
- [x] **303.4** Some enchantments have the subtype “Aura.” An Aura enters the battlefield attached to an object o... *(39 tests, subrules abcdefghijm)*
- [x] **303.5** Some enchantments have the subtype “Saga.” See rule 714 for more information about Saga cards. *(2 tests)*
- [x] **303.6** Some enchantments have the subtype “Class.” See rule 716 for more information about Class cards. *(2 tests)*
- [x] **303.7** Some Aura enchantments also have the subtype “Role.” *(3 tests, subrules a)*

### 304. Instants

- [ ] **304.1** A player who has priority may cast an instant card from their hand. Casting an instant as a spell...
- [ ] **304.2** When an instant spell resolves, the actions stated in its rules text are followed. Then it’s put ...
- [ ] **304.3** Instant subtypes are always a single word and are listed after a long dash: “Instant — Arcane.” E...
- [ ] **304.4** Instants can’t enter the battlefield. If an instant would enter the battlefield, it remains in it...
- [ ] **304.5** If text states that a player may do something “any time they could cast an instant” or “only as a...

### 305. Lands

- [x] **305.1** A player who has priority may play a land card from their hand during a main phase of their turn ... *(3 tests)*
- [x] **305.2** A player can normally play one land during their turn; however, continuous effects may increase t... *(20 tests, subrules ab)*
- [ ] **305.3** A player can’t play a land, for any reason, if it isn’t their turn. Ignore any part of an effect ...
- [ ] **305.4** Effects may also allow players to “put” lands onto the battlefield. This isn’t the same as “playi...
- [ ] **305.5** Land subtypes are always a single word and are listed after a long dash. Land subtypes are also c...
- [ ] **305.6** The basic land types are Plains, Island, Swamp, Mountain, and Forest. If an object uses the words...
- [x] **305.7** If an effect sets a land’s subtype to one or more of the basic land types, the land no longer has... *(16 tests)*
- [ ] **305.8** Any land with the supertype “basic” is a basic land. Any land that doesn’t have this supertype is...
- [ ] **305.9** If an object is both a land and another card type, it can be played only as a land. It can’t be c...

### 306. Planeswalkers

- [x] **306.1** A player who has priority may cast a planeswalker card from their hand during a main phase of the... *(1 tests)*
- [x] **306.2** When a planeswalker spell resolves, its controller puts it onto the battlefield under their control. *(1 tests)*
- [x] **306.3** Planeswalker subtypes are always a single word and are listed after a long dash: “Planeswalker — ... *(1 tests)*
- [x] **306.4** Previously, planeswalkers were subject to a “planeswalker uniqueness rule” that stopped a player ... *(2 tests)*
- [x] **306.5** Loyalty is a characteristic only planeswalkers have. *(6 tests, subrules abcd)*
- [x] **306.6** Planeswalkers can be attacked. (See rule 508, “Declare Attackers Step.”) *(1 tests)*
- [x] **306.7** Previously, planeswalkers were subject to a redirection effect that allowed a player to have nonc... *(1 tests)*
- [x] **306.8** Damage dealt to a planeswalker results in that many loyalty counters being removed from it. *(1 tests)*
- [x] **306.9** If a planeswalker’s loyalty is 0, it’s put into its owner’s graveyard. (This is a state-based act... *(1 tests)*

### 307. Sorceries

- [x] **307.1** A player who has priority may cast a sorcery card from their hand during a main phase of their tu... *(1 tests)*
- [ ] **307.2** When a sorcery spell resolves, the actions stated in its rules text are followed. Then it’s put i...
- [ ] **307.3** Sorcery subtypes are always a single word and are listed after a long dash: “Sorcery — Arcane.” E...
- [ ] **307.4** Sorceries can’t enter the battlefield. If a sorcery would enter the battlefield, it remains in it...
- [ ] **307.5** If a spell, ability, or effect states that a player can do something only “any time they could ca...

### 400. General

- [x] **400.1** A zone is a place where objects can be during a game. There are normally seven zones: library, ha... *(4 tests)*
- [x] **400.2** Public zones are zones in which all players can see the cards’ faces, except for those cards that... *(4 tests)*
- [x] **400.3** If an object would go to any library, graveyard, or hand other than its owner’s, it goes to its o... *(6 tests)*
- [ ] **400.4** Cards with certain card types can’t enter certain zones.
- [x] **400.5** The order of objects in a library, in a graveyard, or on the stack can’t be changed except when e... *(1 tests)*
- [ ] **400.6** If an object would move from one zone to another, determine what event is moving the object. If t...
- [x] **400.7** An object that moves from one zone to another becomes a new object with no memory of, or relation... *(10 tests)*
- [ ] **400.8** If an object in the exile zone is exiled, it doesn’t change zones, but it becomes a new object th...
- [ ] **400.9** If a face-up object in the command zone is turned face down, it becomes a new object.
- [ ] **400.10** If an object in the command zone is put into the command zone, it doesn’t change zones, but it be...
- [ ] **400.11** An object is outside the game if it isn’t in any of the game’s zones. Outside the game is not a z...
- [ ] **400.12** Some effects instruct a player to do something to a zone (such as “Shuffle your hand into your li...

### 401. Library

- [x] **401.1** When a game begins, each player’s deck becomes their library. *(1 tests)*
- [x] **401.2** Each library must be kept in a single face-down pile. Players can’t look at or change the order o... *(1 tests)*
- [ ] **401.3** Any player may count the number of cards remaining in any player’s library at any time.
- [x] **401.4** If an effect puts two or more cards in a specific position in a library at the same time, the own... *(3 tests)*
- [x] **401.5** Some effects tell a player to play with the top card of their library revealed, or say that a pla... *(1 tests)*
- [ ] **401.6** If an effect causes a player to play with the top card of their library revealed, and that partic...
- [ ] **401.7** If an effect causes a player to put a card into a library “Nth from the top,” and that library ha...

### 402. Hand

- [x] **402.1** The hand is where a player holds cards that have been drawn. Cards can be put into a player’s han... *(4 tests)*
- [x] **402.2** Each player has a maximum hand size, which is normally seven cards. A player may have any number ... *(5 tests)*
- [x] **402.3** A player may arrange their hand in any convenient fashion and look at it at any time. A player ca... *(3 tests)*

### 403. Battlefield

- [x] **403.1** Most of the area between the players represents the battlefield. The battlefield starts out empty... *(3 tests)*
- [ ] **403.2** A spell or ability affects and checks only the battlefield unless it specifically mentions a play...
- [x] **403.3** Permanents exist only on the battlefield. Every object on the battlefield is a permanent. See rul... *(2 tests)*
- [x] **403.4** Whenever a permanent enters the battlefield, it becomes a new object and has no relationship to a... *(2 tests)*
- [ ] **403.5** Previously, the battlefield was called the “in-play zone.” Cards that were printed with text that...

### 404. Graveyard

- [x] **404.1** A player’s graveyard is their discard pile. Any object that’s countered, discarded, destroyed, or... *(4 tests)*
- [ ] **404.2** Each graveyard is kept in a single face-up pile. A player can examine the cards in any graveyard ...
- [ ] **404.3** If an effect or rule puts two or more cards into the same graveyard at the same time, the owner o...

### 405. Stack

- [x] **405.1** When a spell is cast, the physical card is put on the stack (see rule 601.2a). When an ability is... *(2 tests)*
- [x] **405.2** The stack keeps track of the order that spells and/or abilities were added to it. Each time an ob... *(1 tests)*
- [x] **405.3** If an effect puts two or more objects on the stack at the same time, those controlled by the acti... *(3 tests)*
- [x] **405.4** Each spell has all the characteristics of the card associated with it. Each activated or triggere... *(2 tests)*
- [x] **405.5** When all players pass in succession, the top (last-added) spell or ability on the stack resolves.... *(2 tests)*
- [x] **405.6** Some things that happen during the game don’t use the stack. *(3 tests, subrules ce)*

### 406. Exile

- [x] **406.1** The exile zone is essentially a holding area for objects. Some spells and abilities exile an obje... *(1 tests)*
- [x] **406.2** To exile an object is to put it into the exile zone from whatever zone it’s currently in. An exil... *(1 tests)*
- [ ] **406.3** Exiled cards are, by default, kept face up and may be examined by any player at any time. Cards “...
- [ ] **406.4** Face-down cards in exile should be kept in separate piles based on when they were exiled and how ...
- [ ] **406.5** Exiled cards that might return to the battlefield or any other zone should be kept in separate pi...
- [ ] **406.6** An object may have one ability printed on it that causes one or more cards to be exiled, and anot...
- [ ] **406.7** If an object in the exile zone becomes exiled, it doesn’t change zones, but it becomes a new obje...
- [ ] **406.8** Previously, the exile zone was called the “removed-from-the-game zone.” Cards that were printed w...

### 407. Ante

- [x] **407.1** Earlier versions of the Magic rules included an ante rule as a way of playing “for keeps.” Playin... *(5 tests)*
- [x] **407.2** When playing for ante, each player puts one random card from their deck into the ante zone after ... *(17 tests)*
- [x] **407.3** A few cards have the text “Remove this card from your deck before playing if you’re not playing f... *(17 tests)*
- [x] **407.4** To ante an object is to put that object into the ante zone from whichever zone it’s currently in.... *(10 tests)*

### 408. Command

- [x] **408.1** The command zone is a game area reserved for certain specialized objects that have an overarching... *(1 tests)*
- [x] **408.2** Emblems may be created in the command zone. See rule 114, “Emblems.” *(1 tests)*
- [x] **408.3** In the Planechase, Vanguard, Commander, Archenemy, and Conspiracy Draft casual variants, nontradi... *(1 tests)*

### 500. General

- [x] **500.1** A turn consists of five phases, in this order: beginning, precombat main, combat, postcombat main... *(2 tests)*
- [ ] **500.2** A phase or step in which players receive priority ends when the stack is empty and all players pa...
- [x] **500.3** A step in which no players receive priority ends when all specified actions that take place durin... *(2 tests)*
- [ ] **500.4** As a step or phase begins, if there are effects that last until that step or phase, those effects...
- [x] **500.5** As a step or phase ends, if there are effects that last until the end of that step or phase, thos... *(1 tests)*
- [x] **500.6** When a phase or step begins, any abilities that trigger “at the beginning of” that phase or step ... *(1 tests)*
- [x] **500.7** Some effects can give a player extra turns. They do this by adding the turns directly after the s... *(3 tests)*
- [ ] **500.8** Some effects can add phases to a turn. They do this by adding the phases directly after the speci...
- [ ] **500.9** Some effects can add steps to a phase. They do this by adding the steps directly after a specifie...
- [x] **500.10** Some effects add a step after a particular phase. In that case, that effect first creates the pha... *(1 tests)*
- [ ] **500.11** Some effects can cause a step, phase, or turn to be skipped. To skip a step, phase, or turn is to...
- [ ] **500.12** No game events can occur between steps, phases, or turns.

### 501. Beginning Phase

- [x] **501.1** The beginning phase consists of three steps, in this order: untap, upkeep, and draw. *(1 tests)*

### 502. Untap Step

- [x] **502.1** First, all phased-in permanents with phasing that the active player controls phase out, and all p... *(1 tests)*
- [ ] **502.2** Second, if it’s day and the previous turn’s active player didn’t cast any spells during that turn...
- [x] **502.3** Third, the active player determines which permanents they control will untap. Then they untap the... *(22 tests)*
- [x] **502.4** No player receives priority during the untap step, so no spells can be cast or resolve and no abi... *(1 tests)*

### 503. Upkeep Step

- [x] **503.1** The upkeep step has no turn-based actions. Once it begins, the active player gets priority. (See ... *(5 tests, subrules a)*
- [ ] **503.2** If a spell states that it may be cast only “after [a player’s] upkeep step,” and the turn has mul...

### 504. Draw Step

- [x] **504.1** First, the active player draws a card. This turn-based action doesn’t use the stack. *(7 tests)*
- [x] **504.2** Second, the active player gets priority. (See rule 117, “Timing and Priority.”) *(4 tests)*

### 505. Main Phase

- [x] **505.1** There are two main phases in a turn. In each turn, the first main phase (also known as the precom... *(1 tests)*
- [x] **505.2** The main phase has no steps, so a main phase ends when all players pass in succession while the s... *(1 tests)*
- [ ] **505.3** First, but only if the players are playing an Archenemy game (see rule 904), the active player is...
- [ ] **505.4** Second, if the active player controls one or more Saga enchantments and it’s the active player’s ...
- [ ] **505.5** Third, if the active player controls one or more Attractions and it’s the active player’s precomb...
- [x] **505.6** Fourth, the active player gets priority. (See rule 117, “Timing and Priority.”) *(2 tests, subrules b)*

### 506. Combat Phase

- [x] **506.1** The combat phase has five steps, which proceed in order: beginning of combat, declare attackers, ... *(6 tests)*
- [x] **506.2** During the combat phase, the active player is the attacking player; creatures that player control... *(5 tests)*
- [x] **506.3** Only a creature can attack or block. Only a player, a planeswalker, or a battle can be attacked. *(13 tests, subrules ab)*
- [x] **506.4** A permanent is removed from combat if it leaves the battlefield, if its controller changes, if it... *(10 tests, subrules bc)*
- [x] **506.5** A creature attacks alone if it’s the only creature declared as an attacker during the declare att... *(5 tests)*
- [x] **506.6** Some abilities check to see whether or not a creature “had to attack” during a particular combat ... *(2 tests)*
- [x] **506.7** Some spells state that they may be cast “only [before/after] [a particular point in the combat ph... *(8 tests)*

### 507. Beginning of Combat Step

- [ ] **507.1** First, if the game being played is a multiplayer game in which the active player’s opponents don’...
- [x] **507.2** Second, the active player gets priority. (See rule 117, “Timing and Priority.”) *(1 tests)*

### 508. Declare Attackers Step

- [x] **508.1** First, the active player declares attackers. This turn-based action doesn’t use the stack. To dec... *(25 tests, subrules abcdfgk)*
- [x] **508.2** Second, the active player gets priority. (See rule 117, “Timing and Priority.”) *(2 tests)*
- [ ] **508.3** Triggered abilities that trigger on attackers being declared may have different trigger conditions.
- [ ] **508.4** If a creature is put onto the battlefield attacking, its controller chooses which defending playe...
- [x] **508.5** If an ability of an attacking creature refers to a defending player, or a spell or ability refers... *(3 tests, subrules a)*
- [ ] **508.6** A player is “attacking [a player]” if the first player controls a creature that is attacking the ...
- [ ] **508.7** Some cards allow a player to reselect which player, planeswalker, or battle a creature is attacking.
- [x] **508.8** If no creatures are declared as attackers or put onto the battlefield attacking, skip the declare... *(2 tests)*

### 509. Declare Blockers Step

- [x] **509.1** First, the defending player declares blockers. This turn-based action doesn’t use the stack. To d... *(51 tests, subrules abcghi)*
- [x] **509.2** Second, the active player gets priority. (See rule 117, “Timing and Priority.”) *(4 tests, subrules a)*
- [x] **509.3** Triggered abilities that trigger on blockers being declared may have different trigger conditions. *(9 tests, subrules acdg)*
- [x] **509.4** If a creature is put onto the battlefield blocking, its controller chooses which attacking creatu... *(1 tests)*

### 510. Combat Damage Step

- [x] **510.1** First, the active player announces how each attacking creature assigns its combat damage, then th... *(18 tests, subrules abcde)*
- [x] **510.2** Second, all combat damage that’s been assigned is dealt simultaneously. This turn-based action do... *(7 tests)*
- [x] **510.3** Third, the active player gets priority. (See rule 117, “Timing and Priority.”) *(4 tests, subrules a)*
- [x] **510.4** If at least one attacking or blocking creature has first strike (see rule 702.7) or double strike... *(2 tests)*

### 511. End of Combat Step

- [x] **511.1** The end of combat step has no turn-based actions. Once it begins, the active player gets priority... *(4 tests)*
- [x] **511.2** Abilities that trigger “at end of combat” trigger as the end of combat step begins. Effects that ... *(2 tests)*
- [x] **511.3** As soon as the end of combat step ends, all creatures, battles, and planeswalkers are removed fro... *(1 tests)*

### 512. Ending Phase

- [x] **512.1** The ending phase consists of two steps: end and cleanup. *(1 tests)*

### 513. End Step

- [x] **513.1** The end step has no turn-based actions. Once it begins, the active player gets priority. (See rul... *(1 tests)*
- [ ] **513.2** If a permanent with an ability that triggers “at the beginning of the end step” enters the battle...

### 514. Cleanup Step

- [x] **514.1** First, if the active player’s hand contains more cards than their maximum hand size (normally sev... *(6 tests)*
- [x] **514.2** Second, the following actions happen simultaneously: all damage marked on permanents (including p... *(4 tests)*
- [x] **514.3** Normally, no player receives priority during the cleanup step, so no spells can be cast and no ab... *(1 tests)*

### 601. Casting Spells

- [ ] **601.1** Previously, the action of casting a spell, or casting a card as a spell, was referred to on cards...
- [x] **601.2** To cast a spell is to take it from where it is (usually the hand), put it on the stack, and pay i... *(130 tests, subrules abcdefghi)*
- [x] **601.3** A player can begin to cast a spell only if a rule or effect allows that player to cast it and no ... *(10 tests)*
- [ ] **601.4** While announcing the choices of any modes, alternative costs, and/or additional costs as describe...
- [x] **601.5** If a player is no longer allowed to cast a spell after completing its proposal (see rules 601.2a–... *(4 tests)*
- [ ] **601.6** Some spells specify that one of their controller’s opponents does something the controller would ...
- [x] **601.7** Casting a spell that alters costs won’t affect spells and abilities that are already on the stack. *(1 tests)*

### 602. Activating Activated Abilities

- [x] **602.1** Activated abilities have a cost and an effect. They are written as “[Cost]: [Effect.] [Activation... *(14 tests, subrules ab)*
- [x] **602.2** To activate an ability is to put it onto the stack and pay its costs, so that it will eventually ... *(22 tests, subrules ab)*
- [ ] **602.3** Some abilities specify that one of their controller’s opponents does something the controller wou...
- [ ] **602.4** Activating an ability that alters costs won’t affect spells and abilities that are already on the...
- [x] **602.5** A player can’t begin to activate an ability that’s prohibited from being activated. *(31 tests, subrules ac)*

### 603. Handling Triggered Abilities

- [x] **603.1** Triggered abilities have a trigger condition and an effect. They are written as “[When/Whenever/A... *(1 tests)*
- [x] **603.2** Whenever a game event or game state matches a triggered ability’s trigger event, that ability aut... *(16 tests, subrules bd)*
- [x] **603.3** Once an ability has triggered, its controller puts it on the stack as an object that’s not a card... *(28 tests, subrules bcd)*
- [x] **603.4** A triggered ability may read “When/Whenever/At [trigger event], if [condition], [effect].” When t... *(4 tests)*
- [x] **603.5** Some triggered abilities’ effects are optional (they contain “may,” as in “At the beginning of yo... *(6 tests)*
- [x] **603.6** Trigger events that involve objects changing zones are called “zone-change triggers.” Many abilit... *(2 tests, subrules c)*
- [x] **603.7** An effect may create a delayed triggered ability that can do something at a later time. A delayed... *(26 tests, subrules bcde)*
- [x] **603.8** Some triggered abilities trigger when a game state (such as a player controlling no permanents of... *(3 tests)*
- [ ] **603.9** Some triggered abilities trigger specifically when a player loses the game. These abilities trigg...
- [x] **603.10** Normally, objects that exist immediately after an event are checked to see if the event matched a... *(5 tests, subrules a)*
- [ ] **603.11** Some objects have a static ability that’s linked to one or more triggered abilities. (See rule 60...
- [x] **603.12** A resolving spell or ability may allow or instruct a player to take an action and create a trigge... *(2 tests)*

### 604. Handling Static Abilities

- [x] **604.1** Static abilities do something all the time rather than being activated or triggered. They are wri... *(2 tests)*
- [x] **604.2** Static abilities create continuous effects, some of which are prevention effects or replacement e... *(2 tests)*
- [x] **604.3** Some static abilities are characteristic-defining abilities. A characteristic-defining ability co... *(15 tests)*
- [ ] **604.4** Many Auras, Equipment, and Fortifications have static abilities that modify the object they’re at...
- [ ] **604.5** Some static abilities apply while a spell is on the stack. These are often abilities that refer t...
- [ ] **604.6** Some static abilities apply while a card is in any zone that you could cast or play it from (usua...
- [ ] **604.7** Unlike spells and other kinds of abilities, static abilities can’t use an object’s last known inf...

### 605. Mana Abilities

- [x] **605.1** Some activated abilities and some triggered abilities are mana abilities, which are subject to sp... *(3 tests, subrules ab)*
- [x] **605.2** A mana ability remains a mana ability even if the game state doesn’t allow it to produce mana. *(1 tests)*
- [x] **605.3** Activating an activated mana ability follows the rules for activating any other activated ability... *(11 tests, subrules abc)*
- [x] **605.4** Triggered mana abilities follow all the rules for other triggered abilities (see rule 603, “Handl... *(4 tests, subrules a)*
- [x] **605.5** Abilities that don’t meet the criteria specified in rules 605.1a–b and spells aren’t mana abilities. *(3 tests, subrules ab)*

### 606. Loyalty Abilities

- [x] **606.1** Some activated abilities are loyalty abilities, which are subject to special rules. *(1 tests)*
- [x] **606.2** An activated ability with a loyalty symbol in its cost is a loyalty ability. Normally, only plane... *(3 tests)*
- [x] **606.3** A player may activate a loyalty ability of a permanent they control any time they have priority a... *(7 tests)*
- [x] **606.4** The cost to activate a loyalty ability of a permanent is to put on or remove from that permanent ... *(4 tests)*
- [ ] **606.5** If the total cost to activate a loyalty ability contains multiple costs to add or remove loyalty ...
- [x] **606.6** A loyalty ability with a negative loyalty cost, taking into account any additional costs, can’t b... *(2 tests)*

### 607. Linked Abilities

- [x] **607.1** An object may have two abilities printed on it such that one of them causes actions to be taken o... *(2 tests)*
- [x] **607.2** There are different kinds of linked abilities. *(2 tests, subrules ac)*
- [ ] **607.3** If, within a pair of linked abilities, one ability refers to a single object as “the exiled card,...
- [ ] **607.4** An ability may be part of more than one pair of linked abilities.
- [ ] **607.5** If an object acquires a pair of linked abilities as part of the same effect, the abilities will b...

### 608. Resolving Spells and Abilities

- [x] **608.1** Each time all players pass in succession, the spell or ability on top of the stack resolves. (See... *(1 tests)*
- [x] **608.2** If the object that’s resolving is an instant spell, a sorcery spell, or an ability, its resolutio... *(44 tests, subrules bcdhn)*
- [x] **608.3** If the object that’s resolving is a permanent spell, its resolution may involve several steps. Th... *(3 tests, subrules ab)*

### 609. Effects

- [x] **609.1** An effect is something that happens in the game as a result of a spell or ability. When a spell, ... *(3 tests)*
- [x] **609.2** Effects apply only to permanents unless the instruction’s text states otherwise or they clearly c... *(3 tests)*
- [x] **609.3** If an effect attempts to do something impossible, it does only as much as possible. *(4 tests)*
- [x] **609.4** Some effects state that a player may do something “as though” some condition were true or a creat... *(5 tests)*
- [ ] **609.5** If an effect could result in a tie, the text of the spell or ability that created the effect will...
- [ ] **609.6** Some continuous effects are replacement effects or prevention effects. See rules 614 and 615.
- [x] **609.7** Some effects apply to damage from a source—for example, “The next time a red source of your choic... *(3 tests, subrules bc)*

### 610. One-Shot Effects

- [x] **610.1** A one-shot effect does something just once and doesn’t have a duration. Examples include dealing ... *(10 tests)*
- [ ] **610.2** Some one-shot effects create a delayed triggered ability, which instructs a player to do somethin...
- [x] **610.3** Some one-shot effects cause an object to change zones “until” a specified event occurs. A second ... *(6 tests, subrules cd)*
- [ ] **610.4** Some one-shot effects cause a permanent to phase out “until” a specified event occurs. A second o...
- [ ] **610.5** Some static abilities create one-shot effects that cause spells a player casts to gain an ability...

### 611. Continuous Effects

- [x] **611.1** A continuous effect modifies characteristics of objects, modifies control of objects, or affects ... *(2 tests)*
- [x] **611.2** A continuous effect may be generated by the resolution of a spell or ability. *(29 tests, subrules abc)*
- [x] **611.3** A continuous effect may be generated by the static ability of an object. *(49 tests, subrules abc)*

### 612. Text-Changing Effects

- [x] **612.1** Some continuous effects change an object’s text. This can apply to any words or symbols printed o... *(8 tests)*
- [x] **612.2** A text-changing effect changes only those words that are used in the correct way (for example, a ... *(1 tests)*
- [x] **612.3** Effects that add or remove abilities don’t change the text of the objects they affect, so any abi... *(1 tests)*
- [ ] **612.4** A token’s subtypes and rules text are defined by the spell or ability that created the token. A t...
- [ ] **612.5** One card (Exchange of Words) instructs a player to exchange the text boxes of two objects. This r...
- [ ] **612.6** One card (Volrath’s Shapeshifter) states that an object has the “full text” of another object. Th...
- [ ] **612.7** One card (Spy Kit) states that an object has “all names of nonlegendary creature cards.” This cha...
- [ ] **612.8** Some cards create a continuous effect that sets the name of an object. This changes the text that...
- [ ] **612.9** A name sticker on a permanent or on a card not on the battlefield creates a continuous effect tha...
- [ ] **612.10** A splice ability changes a spell’s text by adding the rules text of the card with splice to the s...

### 613. Interaction of Continuous Effects

- [x] **613.1** The values of an object’s characteristics are determined by starting with the actual object. For ... *(78 tests, subrules bcdefg)*
- [x] **613.2** Within layer 1, apply effects in a series of sublayers in the order described below. Within each ... *(13 tests, subrules ac)*
- [ ] **613.3** Within layers 2–6, apply effects from characteristic-defining abilities first (see rule 604.3), t...
- [x] **613.4** Within layer 7, apply effects in a series of sublayers in the order described below. Within each ... *(72 tests, subrules abcd)*
- [x] **613.5** The application of continuous effects as described by the layer system is continually and automat... *(2 tests)*
- [ ] **613.6** If an effect should be applied in different layers and/or sublayers, the parts of the effect each...
- [x] **613.7** Within a layer or sublayer, determining which order effects are applied in is usually done using ... *(17 tests, subrules be)*
- [x] **613.8** Within a layer or sublayer, determining which order effects are applied in is sometimes done usin... *(8 tests, subrules abc)*
- [x] **613.9** One continuous effect can override another. Sometimes the results of one effect determine whether... *(6 tests)*
- [x] **613.10** Some continuous effects affect players rather than objects. For example, an effect might give a p... *(1 tests)*
- [ ] **613.11** Some continuous effects affect game rules rather than objects. For example, effects may modify a ...

### 614. Replacement Effects

- [x] **614.1** Some continuous effects are replacement effects. Like prevention effects (see rule 615), replacem... *(33 tests, subrules abcd)*
- [ ] **614.2** Some replacement effects apply to damage from a source. See rule 609.7.
- [ ] **614.3** There are no special restrictions on casting a spell or activating an ability that generates a re...
- [x] **614.4** Replacement effects must exist before the appropriate event occurs—they can’t “go back in time” a... *(2 tests)*
- [x] **614.5** A replacement effect doesn’t invoke itself repeatedly; it gets only one opportunity to affect an ... *(5 tests)*
- [x] **614.6** If an event is replaced, it never happens. A modified event occurs instead, which may in turn tri... *(9 tests)*
- [x] **614.7** If a replacement effect would replace an event, but that event never happens, the replacement eff... *(5 tests, subrules a)*
- [x] **614.8** Regeneration is a destruction-replacement effect. The word “instead” doesn’t appear on the card b... *(9 tests)*
- [x] **614.9** Some effects replace damage dealt to one battle, creature, planeswalker, or player with the same ... *(11 tests)*
- [x] **614.10** An effect that causes a player to skip an event, step, phase, or turn is a replacement effect. “S... *(4 tests, subrules a)*
- [ ] **614.11** Some effects replace card draws. These effects are applied even if no cards could be drawn becaus...
- [x] **614.12** Some replacement effects modify how a permanent enters the battlefield. (See rules 614.1c–d.) Suc... *(3 tests)*
- [ ] **614.13** An effect that modifies how a permanent enters the battlefield may cause other objects to change ...
- [ ] **614.14** An object may have one ability printed on it that generates a replacement effect which causes one...
- [ ] **614.15** Some replacement effects are not continuous effects. Rather, they are an effect of a resolving sp...
- [ ] **614.16** Some replacement effects apply “if an effect would create one or more tokens” or “if an effect wo...
- [ ] **614.17** Some effects state that something can’t happen. These effects aren’t replacement effects, but fol...

### 615. Prevention Effects

- [x] **615.1** Some continuous effects are prevention effects. Like replacement effects (see rule 614), preventi... *(15 tests, subrules a)*
- [ ] **615.2** Many prevention effects apply to damage from a source. See rule 609.7.
- [x] **615.3** There are no special restrictions on casting a spell or activating an ability that generates a pr... *(5 tests)*
- [ ] **615.4** Prevention effects must exist before the appropriate damage event occurs—they can’t “go back in t...
- [x] **615.5** Some prevention effects also include an additional effect, which may refer to the amount of damag... *(1 tests)*
- [x] **615.6** If damage that would be dealt is prevented, it never happens. A modified event may occur instead,... *(1 tests)*
- [x] **615.7** Some prevention effects generated by the resolution of a spell or ability refer to a specific amo... *(12 tests)*
- [x] **615.8** Some prevention effects generated by the resolution of a spell or ability refer to the next time ... *(7 tests)*
- [x] **615.9** Some effects generated by the resolution of a spell or ability prevent damage from a source of a ... *(4 tests)*
- [ ] **615.10** Some prevention effects generated by static abilities refer to a specific amount of damage—for ex...
- [ ] **615.11** Some prevention effects prevent the next N damage that would be dealt to each of a number of unta...
- [ ] **615.12** Some effects state that damage “can’t be prevented.” If unpreventable damage would be dealt, any ...
- [ ] **615.13** Some triggered abilities trigger when damage that would be dealt is prevented. Such an ability tr...

### 616. Interaction of Replacement and/or Prevention Effects

- [x] **616.1** If two or more replacement and/or prevention effects are attempting to modify the way an event af... *(34 tests, subrules efg)*
- [x] **616.2** A replacement or prevention effect can become applicable to an event as the result of another rep... *(1 tests)*

### 700. General

- [ ] **700.1** Anything that happens in a game is an event. Multiple events may take place during the resolution...
- [x] **700.2** A spell or ability is modal if it has two or more options in a bulleted list preceded by instruct... *(15 tests, subrules abd)*
- [ ] **700.3** Some effects cause objects to be temporarily grouped into piles.
- [x] **700.4** The term dies means “is put into a graveyard from the battlefield.” *(4 tests)*
- [ ] **700.5** A player’s devotion to [color] is equal to the number of mana symbols of that color among the man...
- [ ] **700.6** The term historic refers to an object that has the legendary supertype, the artifact card type, o...
- [ ] **700.7** If an ability uses a phrase such as “this [something]” to identify an object, where [something] i...
- [ ] **700.8** Some cards refer to a player’s party. A player’s party consists of up to one Cleric creature that...
- [ ] **700.9** Some cards refer to modified permanents. A permanent is modified if it has one or more counters o...
- [ ] **700.10** Some cards refer to a permanent “that was activated this turn.” This means that the permanent was...
- [ ] **700.11** Some cards refer to whether a player has “descended this turn.” This means that a permanent card ...
- [ ] **700.12** The term outlaw refers to an object that has the Assassin, Mercenary, Pirate, Rogue, and/or Warlo...
- [ ] **700.13** Some cards refer to committing a crime. A player commits a crime as that player casts a spell, ac...
- [ ] **700.14** Some abilities trigger “Whenever you expend N.” A player expends N if they pay a cost to cast a s...
- [ ] **700.15** The term enter[s] is short for “enter[s] the battlefield.”

### 701. Keyword Actions

- [x] **701.2** Activate *(4 tests, subrules a)*
- [x] **701.3** Attach *(10 tests, subrules abcd)*
- [x] **701.5** Cast *(4 tests, subrules a)*
- [x] **701.6** Counter *(3 tests, subrules ab)*
- [x] **701.7** Create *(3 tests, subrules a)*
- [x] **701.8** Destroy *(4 tests, subrules ab)*
- [x] **701.9** Discard *(4 tests, subrules ac)*
- [x] **701.12** Exchange *(6 tests, subrules ab)*
- [x] **701.13** Exile *(7 tests, subrules a)*
- [x] **701.14** Fight *(4 tests, subrules abd)*
- [x] **701.17** Mill *(5 tests, subrules a)*
- [x] **701.18** Play *(4 tests, subrules a)*
- [x] **701.19** Regenerate *(26 tests, subrules abc)*
- [x] **701.20** Reveal *(2 tests, subrules a)*
- [x] **701.21** Sacrifice *(10 tests, subrules a)*
- [x] **701.22** Scry *(8 tests, subrules ab)*
- [x] **701.23** Search *(2 tests, subrules a)*
- [x] **701.24** Shuffle *(2 tests, subrules a)*
- [x] **701.26** Tap and Untap *(3 tests, subrules ab)*

### 702. Keyword Abilities

- [x] **702.1** Most abilities describe exactly what they do in the card’s rules text. Some, though, are very com... *(1 tests)*
- [x] **702.2** Deathtouch *(4 tests, subrules bc)*
- [x] **702.3** Defender *(6 tests, subrules b)*
- [x] **702.4** Double Strike *(3 tests, subrules b)*
- [x] **702.5** Enchant *(7 tests, subrules a)*
- [x] **702.6** Equip *(15 tests, subrules ace)*
- [x] **702.7** First Strike *(5 tests, subrules b)*
- [x] **702.8** Flash *(2 tests, subrules ab)*
- [x] **702.9** Flying *(7 tests, subrules ab)*
- [x] **702.10** Haste *(3 tests, subrules bc)*
- [x] **702.11** Hexproof *(2 tests, subrules bd)*
- [x] **702.12** Indestructible *(2 tests, subrules b)*
- [x] **702.14** Landwalk *(17 tests, subrules abc)*
- [x] **702.15** Lifelink *(8 tests, subrules b)*
- [x] **702.16** Protection *(41 tests, subrules abcdefgmn)*
- [x] **702.17** Reach *(3 tests, subrules b)*
- [x] **702.18** Shroud *(4 tests, subrules a)*
- [x] **702.19** Trample *(9 tests, subrules bf)*
- [x] **702.20** Vigilance *(2 tests, subrules b)*
- [x] **702.22** Banding *(35 tests, subrules abcdefghjk)*
- [x] **702.23** Rampage *(6 tests, subrules abc)*
- [x] **702.24** Cumulative Upkeep *(17 tests, subrules ab)*
- [x] **702.25** Flanking *(3 tests, subrules a)*
- [x] **702.26** Phasing *(5 tests, subrules ad)*
- [x] **702.36** Fear *(5 tests, subrules ab)*
- [x] **702.108** Prowess *(3 tests, subrules a)*
- [x] **702.111** Menace *(3 tests, subrules b)*

### 703. Turn-Based Actions

- [ ] **703.1** Turn-based actions are game actions that happen automatically when certain steps or phases begin,...
- [ ] **703.2** Turn-based actions are not controlled by any player.
- [ ] **703.3** Whenever a step or phase begins, if it’s a step or phase that has any turn-based action associate...
- [ ] **703.4** The turn-based actions are as follows:

### 704. State-Based Actions

- [ ] **704.1** State-based actions are game actions that happen automatically whenever certain conditions (liste...
- [ ] **704.2** State-based actions are checked throughout the game and are not controlled by any player.
- [x] **704.3** Whenever a player would get priority (see rule 117, “Timing and Priority”), the game checks for a... *(3 tests)*
- [ ] **704.4** Unlike triggered abilities, state-based actions pay no attention to what happens during the resol...
- [x] **704.5** The state-based actions are as follows: *(88 tests, subrules abcdefghijkmnpqrsy)*
- [x] **704.6** Some variant games include additional state-based actions that aren’t normally applicable: *(3 tests, subrules cd)*
- [x] **704.7** If multiple state-based actions would have the same result at the same time, a single replacement... *(1 tests)*
- [x] **704.8** If a state-based action results in a permanent leaving the battlefield at the same time other sta... *(1 tests)*

### 705. Flipping a Coin

- [x] **705.1** Some cards refer to flipping a coin. A coin used in a flip must be a two-sided object with easily... *(1 tests)*
- [x] **705.2** Some effects that instruct a player to flip a coin care only about whether the coin comes up head... *(2 tests)*
- [ ] **705.3** An effect may state that a coin flip has a certain result and/or that a certain player wins a coi...

### 707. Copying Objects

- [ ] **707.1** Some objects become or turn another object into a “copy” of a spell, permanent, or card. Some eff...
- [x] **707.2** When copying an object, the copy acquires the copiable values of the original object’s characteri... *(24 tests, subrules ab)*
- [x] **707.3** The copy’s copiable values become the copied information, as modified by the copy’s status (see r... *(2 tests)*
- [x] **707.4** Some effects cause a permanent that’s copying a permanent to copy a different object while remain... *(2 tests)*
- [x] **707.5** An object that enters the battlefield “as a copy” or “that’s a copy” of another object becomes a ... *(2 tests)*
- [ ] **707.6** When copying a permanent, any choices that have been made for that permanent aren’t copied. Inste...
- [ ] **707.7** If a pair of linked abilities are copied, those abilities will be similarly linked to one another...
- [ ] **707.8** When copying a melded permanent or other double-faced permanent, use the copiable values of the f...
- [x] **707.9** Copy effects may include modifications or exceptions to the copying process. *(12 tests, subrules abc)*
- [x] **707.10** To copy a spell, activated ability, or triggered ability means to put a copy of it onto the stack... *(6 tests, subrules ac)*
- [ ] **707.11** If an effect refers to a permanent by name, the effect still tracks that permanent even if it cha...
- [ ] **707.12** An effect that instructs a player to cast a copy of an object (and not just copy a spell) follows...
- [ ] **707.13** One card (Garth One-Eye) instructs a player to create a copy of a card defined by name rather tha...
- [ ] **707.14** One card (Magar of the Magic Strings) instructs a player to note the name of a particular card in...

### 724. Ending Turns and Phases

- [x] **724.1** Some cards end the turn. When an effect ends the turn, follow these steps in order, as they diffe... *(6 tests, subrules bcde)*
- [ ] **724.2** One card (Mandate of Peace) ends the combat phase. When an effect ends the combat phase, follow t...

### 800. General

- [ ] **800.1** A multiplayer game is a game that begins with more than two players. This section contains additi...
- [ ] **800.2** These rules consist of a series of options that can be added to a multiplayer game and a number o...
- [ ] **800.3** Many multiplayer Magic tournaments have additional rules not included here, including rules for d...
- [x] **800.4** Unlike two-player games, multiplayer games can continue after one or more players have left the g... *(7 tests, subrules an)*
- [ ] **800.5** Unless a chosen variant or option prescribes otherwise, seating order is determined by any mutual...
- [x] **800.6** In a multiplayer game, the first mulligan a player takes doesn’t count toward the number of cards... *(3 tests)*
- [ ] **800.7** In a multiplayer game other than a Two-Headed Giant game, the starting player doesn’t skip the dr...

### 802. Attack Multiple Players Option

- [x] **802.1** Some multiplayer games allow the active player to attack multiple other players. If this option i... *(2 tests)*
- [x] **802.2** As the combat phase starts, the attacking player doesn’t choose an opponent to become the defendi... *(2 tests)*
- [x] **802.3** As the attacking player declares each attacking creature, they choose a defending player, a plane... *(3 tests, subrules a)*
- [x] **802.4** If more than one player is being attacked, controls a planeswalker that’s being attacked, or prot... *(2 tests, subrules a)*
- [x] **802.5** Combat damage is assigned in APNAP order. Other than that, the combat damage step proceeds just a... *(2 tests)*

### 806. Free-for-All Variant

- [x] **806.1** In Free-for-All multiplayer games, a group of players compete as individuals against each other. *(2 tests)*
- [x] **806.2** Any multiplayer options used are determined before play begins. The Free-for-All variant uses the... *(3 tests, subrules bc)*
- [ ] **806.3** The players are randomly seated around the table.

### 903. Commander

- [x] **903.1** In the Commander variant, a variant created and popularized by fans, each deck is led by a legend... *(3 tests)*
- [x] **903.2** A Commander game may be a two-player game or a multiplayer game. The default multiplayer setup is... *(1 tests)*
- [x] **903.3** Each deck has a legendary card designated as its commander. That card must be either (a) a creatu... *(14 tests, subrules ad)*
- [x] **903.4** The Commander variant uses color identity to determine what cards can be in a deck with a certain... *(8 tests, subrules acdf)*
- [x] **903.5** Each Commander deck is subject to the following deck construction rules. *(10 tests, subrules abcde)*
- [x] **903.6** At the start of the game, each player puts their commander from their deck face up into the comma... *(3 tests)*
- [x] **903.7** Once the starting player has been determined, each player sets their life total to 40 and draws a... *(4 tests)*
- [x] **903.8** A player may cast a commander they own from the command zone. A commander cast from the command z... *(9 tests)*
- [x] **903.9** A commander may return to the command zone during a Commander game. *(19 tests, subrules ab)*
- [x] **903.10** The Commander variant includes the following specification for winning and losing the game. All o... *(6 tests, subrules a)*
- [x] **903.11** Except via rules, special actions, and effects that specifically bring cards into Commander games... *(8 tests, subrules a)*
- [x] **903.12** Brawl Option *(26 tests, subrules abcdefgh)*

## Excluded from the denominator (mechanic not in this engine)

Listed rather than dropped — see `EXCLUDED` in `scripts/rules_progress.py`. A rule the engine *does* implement that no card exercises is not here; it stays above, untested.

- **104.6** Ending the Game: restarting the game (CR 727) — Karn Liberated is not in the pool
- **117.6** Timing and Priority: shared team turns option (CR 805) — the engine has no teams
- **903.13** Commander: Commander Draft — a draft variant, no in-game behaviour
