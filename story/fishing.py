import copy
import random
import time

# Ordered, table-driven loot definition. Each entry is one distinct catch:
# unique story items (unique=True) are removed from the available pool the
# first time they are caught, so the same piece of equipment can never be
# granted twice. Repeatable fish/trash stay in the pool forever.
LOOT_TABLE = [
    {"item": "Dragon Ring", "weight": 2, "unique": True},
    {"item": "potion", "weight": 3, "unique": True},
    {"item": "trash", "weight": 2, "unique": False},
    {"item": "trout", "weight": 2, "unique": False},
    {"item": "bass", "weight": 3, "unique": False},
]

# A failed cast ("the fish got away") has its own weight. Failure never
# mutates any player state.
FAILURE_KEY = "__failure__"
FAILURE_WEIGHT = 4
FAILURE_MESSAGES = (
    "The fish got away...",
    "Nothing is biting...",
)

# Table-driven effect application: the story-progress field for each unique
# item lives here instead of in branching code.
UNIQUE_EFFECTS = {
    "Dragon Ring": "has_dragon_ring",
    "potion": "potions",
}

CATCH_MESSAGES = {
    "Dragon Ring": "You found {item}!",
    "potion": "You found {item} that restores half of your health and mana.",
    "trash": "You caught {item}.",
    "trout": "You caught {item}.",
    "bass": "You caught {item}.",
}

# Fields that make up the player's story-progress snapshot.
SNAPSHOT_FIELDS = ("health", "mana", "potions", "has_dragon_ring", "is_alive")


def fishing(player, rng=None):
    session = FishingSession(player, rng=rng)
    print_instructions(player)
    while not session.is_complete():
        get_fishing_choice()
        result = session.cast()
        print_cast_result(result)


def print_instructions(player):
    print(f"\n{player.name}, you have completed your training and must now find the Dragon Ring.")
    time.sleep(1)
    print("You can only fight the dragon once you have the ring.")
    time.sleep(1)
    print("\nThere are stories of an old fisherman once spotting it in the nearby river. You will have to try and fish it up.")
    time.sleep(1)
    print("The Dragon Ring has a very low chance to be caught, so don't give up until you catch it!")


def get_fishing_choice():
    while True:
        time.sleep(1)
        choice = input("\nGo fishing? [y/n] ")
        if choice == "n":
            print("You must fish until you find the Dragon Ring and one potion.")
        elif choice == "y":
            return
        else:
            print("Enter y or n.")


def snapshot_player(player):
    """Deep copy of every progress-bearing field, used for full rollback."""
    return {field: copy.deepcopy(getattr(player, field)) for field in SNAPSHOT_FIELDS}


def restore_player(player, snapshot):
    for field, value in snapshot.items():
        setattr(player, field, copy.deepcopy(value))


def available_table(caught_unique):
    """The loot pool minus unique items already obtained by this player."""
    return [
        copy.deepcopy(entry)
        for entry in LOOT_TABLE
        if not (entry["unique"] and entry["item"] in caught_unique)
    ]


def weighted_draw(table, rng, cast_number=0, failure_weight=FAILURE_WEIGHT):
    """Pick one outcome deterministically.

    Entries are sorted by item name before weights are accumulated, so the
    outcome depends only on the rng roll and the weights - never on the
    table's traversal/insertion order.
    """
    ordered = sorted(table, key=lambda entry: entry["item"])
    outcomes = [entry["item"] for entry in ordered]
    weights = [entry["weight"] for entry in ordered]
    outcomes.append(FAILURE_KEY)
    weights.append(failure_weight)

    total = sum(weights)
    roll = rng.randrange(total)
    upto = 0
    for outcome, weight in zip(outcomes, weights):
        upto += weight
        if roll < upto:
            if outcome == FAILURE_KEY:
                return FAILURE_KEY, FAILURE_MESSAGES[cast_number % len(FAILURE_MESSAGES)]
            return outcome, None
    raise RuntimeError("weighted draw exceeded total weight")


def apply_catch(player, item):
    effect_field = UNIQUE_EFFECTS.get(item)
    if effect_field == "has_dragon_ring":
        player.has_dragon_ring = True
    elif effect_field == "potions":
        player.potions += 1


def print_cast_result(result):
    print("Fishing...")
    time.sleep(2)
    if result.failure:
        print(result.message)
    else:
        article = "the " if result.item == "Dragon Ring" else "a " if result.item == "potion" else ""
        print(CATCH_MESSAGES[result.item].format(item=article + result.item))


class CastResult:
    def __init__(self, item=None, failure=False, message=""):
        self.item = item
        self.failure = failure
        self.message = message


class FishingSession:
    """One fishing trip.

    - Unique story items are caught at most once.
    - Every cast runs against a deep-copied snapshot; a failed cast and any
      error during a cast fully roll the player back, so a failure never
      pollutes later casts or story progress.
    - Randomness comes from a private RNG, never the global random state.
    """

    def __init__(self, player, rng=None):
        self.player = player
        self.rng = rng if rng is not None else random.Random()
        self.caught_unique = []
        self.cast_number = 0

    def is_complete(self):
        return self.player.has_dragon_ring and self.player.potions >= 1

    def cast(self):
        snapshot = snapshot_player(self.player)
        try:
            table = available_table(self.caught_unique)
            outcome, failure_message = weighted_draw(
                table, self.rng, cast_number=self.cast_number
            )
            self.cast_number += 1
            if outcome == FAILURE_KEY:
                restore_player(self.player, snapshot)
                return CastResult(failure=True, message=failure_message)

            apply_catch(self.player, outcome)
            entry = next(entry for entry in LOOT_TABLE if entry["item"] == outcome)
            if entry["unique"] and outcome not in self.caught_unique:
                self.caught_unique.append(outcome)
            return CastResult(item=outcome)
        except Exception:
            restore_player(self.player, snapshot)
            raise
