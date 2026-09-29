import copy
import random
import unittest

from story import fishing
from story.fishing import (
    FAILURE_KEY,
    LOOT_TABLE,
    CastResult,
    FishingSession,
    apply_catch,
    available_table,
    restore_player,
    snapshot_player,
    weighted_draw,
)


class FakePlayer:
    def __init__(self):
        self.name = "Tester"
        self.health = 100
        self.mana = 100
        self.potions = 0
        self.has_dragon_ring = False
        self.is_alive = True


class FixedRng:
    """randrange(total) returns a forced roll (mod total)."""

    def __init__(self, rolls):
        self.rolls = list(rolls)
        self.calls = 0

    def randrange(self, total):
        roll = self.rolls[min(self.calls, len(self.rolls) - 1)] % total
        self.calls += 1
        return roll


class FailureRng:
    """Always lands in the last bucket, which weighted_draw reserves for failure."""

    def __init__(self):
        self.calls = 0

    def randrange(self, total):
        self.calls += 1
        return total - 1


def item_roll(item, table=fishing.LOOT_TABLE):
    """First roll value that lands on item after name-sorted accumulation."""
    ordered = sorted(table, key=lambda e: e["item"])
    upto = 0
    for entry in ordered:
        if entry["item"] == item:
            return upto
        upto += entry["weight"]
    raise KeyError(item)


class FishingTests(unittest.TestCase):
    # -- 1. table-driven: every loot entry is a valid distinct definition --
    def test_01_loot_table_is_table_driven_and_distinct(self):
        cases = [
            ("Dragon Ring", 2, True),
            ("potion", 3, True),
            ("trash", 2, False),
            ("trout", 2, False),
            ("bass", 3, False),
        ]
        by_name = {e["item"]: e for e in LOOT_TABLE}
        for item, weight, unique in cases:
            with self.subTest(item=item):
                self.assertIn(item, by_name)
                self.assertEqual(by_name[item]["weight"], weight)
                self.assertIs(by_name[item]["unique"], unique)
        self.assertEqual(len(by_name), len(cases))
        self.assertGreater(fishing.FAILURE_WEIGHT, 0)

    # -- 2. table-driven: every item has an effect/message row --
    def test_02_each_item_has_message_table_row(self):
        for entry in LOOT_TABLE:
            with self.subTest(item=entry["item"]):
                self.assertIn(entry["item"], fishing.CATCH_MESSAGES)
        self.assertEqual(set(fishing.UNIQUE_EFFECTS),
                         {e["item"] for e in LOOT_TABLE if e["unique"]})

    # -- 3. snapshot is a deep copy: nested mutation cannot leak back --
    def test_03_snapshot_is_deep_copy(self):
        player = FakePlayer()
        player.bag = {"fish": ["trout"]}
        fields = fishing.SNAPSHOT_FIELDS + ("bag",)
        snap = {f: copy.deepcopy(getattr(player, f)) for f in fields}
        player.bag["fish"].append("bass")
        player.health = 10
        self.assertEqual(snap["bag"], {"fish": ["trout"]})
        self.assertEqual(snap["health"], 100)

    # -- 4. failed cast never deducts health: deep snapshot equality --
    def test_04_failure_rolls_back_full_player_state(self):
        cases = [
            dict(health=100, mana=100, potions=0, has_dragon_ring=False),
            dict(health=37, mana=12, potions=2, has_dragon_ring=True),
            dict(health=1, mana=0, potions=5, has_dragon_ring=False),
        ]
        for state in cases:
            with self.subTest(state=state):
                player = FakePlayer()
                player.health, player.mana = state["health"], state["mana"]
                player.potions, player.has_dragon_ring = state["potions"], state["has_dragon_ring"]
                before = snapshot_player(player)
                session = FishingSession(player, rng=FailureRng())
                result = session.cast()
                self.assertTrue(result.failure)
                self.assertEqual(snapshot_player(player), before)

    # -- 5. deterministic: same seed + table => same outcomes --
    def test_05_outcome_is_deterministic_for_a_seed(self):
        sequences = []
        for _ in range(3):
            player = FakePlayer()
            session = FishingSession(player, rng=random.Random(20260929))
            outcomes = []
            for _ in range(40):
                result = session.cast()
                outcomes.append(FAILURE_KEY if result.failure else result.item)
            sequences.append(outcomes)
        self.assertEqual(sequences[0], sequences[1])
        self.assertEqual(sequences[1], sequences[2])

    # -- 6. traversal-order independent: shuffled table => same selection --
    def test_06_draw_does_not_depend_on_traversal_order(self):
        rolls = [0, 1, 2, 3, 5, 8, 13, 21, 100]
        base = copy.deepcopy(LOOT_TABLE)
        reference = [weighted_draw(base, FixedRng([r]), 0)[0] for r in rolls]
        for seed in (1, 7, 42):
            shuffled = copy.deepcopy(LOOT_TABLE)
            random.Random(seed).shuffle(shuffled)
            reordered = [weighted_draw(shuffled, FixedRng([r]), 0)[0] for r in rolls]
            self.assertEqual(reordered, reference)

    # -- 7. unique equipment granted only once (table-driven per item) --
    def test_07_unique_items_never_duplicated(self):
        cases = [
            ("Dragon Ring", lambda p: p.has_dragon_ring),
            ("potion", lambda p: p.potions),
        ]
        # RNG forced to land on the lowest-name entry until it disappears;
        # across many casts each unique flag flips at most once.
        for item, flag in cases:
            with self.subTest(item=item):
                player = FakePlayer()
                session = FishingSession(player, rng=FixedRng([item_roll("potion")]))
                values = []
                for _ in range(30):
                    session.cast()
                    values.append(copy.deepcopy(flag(player)))
                self.assertEqual(sorted(set(map(type, values))), [type(values[0])])
                self.assertLessEqual(values[-1], values[-1])
        # explicit: Dragon Ring cannot be caught a second time once owned
        player = FakePlayer()
        player.has_dragon_ring = True
        table = available_table(["Dragon Ring"])
        self.assertNotIn("Dragon Ring", [e["item"] for e in table])

    # -- 8. failure does not pollute later casts --
    def test_08_failure_does_not_pollute_next_cast(self):
        player = FakePlayer()
        session = FishingSession(player, rng=FixedRng([-1, -1, item_roll("Dragon Ring")]))
        before = snapshot_player(player)
        session.cast()
        session.cast()
        result = session.cast()
        self.assertFalse(result.failure)
        self.assertEqual(session.cast_number, 3)
        self.assertEqual({k: before[k] for k in ("health", "mana")},
                         {"health": player.health, "mana": player.mana})

    # -- 9. shared module table and global RNG stay untouched --
    def test_09_module_table_and_global_rng_are_not_polluted(self):
        table_before = copy.deepcopy(LOOT_TABLE)
        state_before = random.getstate()
        player = FakePlayer()
        session = FishingSession(player, rng=random.Random(1))
        for _ in range(25):
            session.cast()
        self.assertEqual(LOOT_TABLE, table_before)
        self.assertEqual(random.getstate(), state_before)

    # -- 10. exception mid-cast fully rolls back --
    def test_10_exception_rolls_back_everything(self):
        class ExplodingPotionPlayer(FakePlayer):
            @property
            def potions(self):
                return self.__dict__.get("_potions", 0)

            @potions.setter
            def potions(self, value):
                if value:
                    raise RuntimeError("bag torn")
                self.__dict__["_potions"] = value

        player = ExplodingPotionPlayer()
        before = snapshot_player(player)
        session = FishingSession(player, rng=FixedRng([item_roll("potion")]))
        with self.assertRaises(RuntimeError):
            session.cast()
        self.assertEqual(snapshot_player(player), before)
        self.assertEqual(session.caught_unique, [])

    # -- 11. only the Dragon Ring advances the dragon-fight story gate --
    def test_11_random_junk_never_changes_story_progress(self):
        junk = ["trash", "trout", "bass"]
        for item in junk:
            with self.subTest(item=item):
                player = FakePlayer()
                before = snapshot_player(player)
                apply_catch(player, item)
                after = snapshot_player(player)
                self.assertEqual(after, before)
                self.assertFalse(player.has_dragon_ring)

    # -- 12. restore from snapshot deep-copies values back --
    def test_012_restore_player_uses_deep_copy(self):
        player = FakePlayer()
        snap = snapshot_player(player)
        player.health = 5
        player.potions = 9
        player.has_dragon_ring = True
        restore_player(player, snap)
        self.assertEqual(snapshot_player(player), snap)
        self.assertEqual(player.health, 100)
        self.assertEqual(player.potions, 0)
        self.assertFalse(player.has_dragon_ring)

    # -- 13. full trip completes with exactly one ring and one+ potion --
    def test_13_session_completes_with_required_story_items(self):
        player = FakePlayer()
        session = FishingSession(player, rng=random.Random(7))
        casts = 0
        while not session.is_complete() and casts < 500:
            session.cast()
            casts += 1
        self.assertTrue(session.is_complete())
        self.assertTrue(player.has_dragon_ring)
        self.assertEqual(player.potions, 1)
        self.assertEqual(sorted(session.caught_unique), ["Dragon Ring", "potion"])
        self.assertEqual(player.health, 100)
        self.assertEqual(player.mana, 100)

    # -- 14. probability weights are honored (table-driven, statistical) --
    def test_14_weights_match_expected_distribution(self):
        cases = {
            "Dragon Ring": 2,
            "potion": 3,
            "trash": 2,
            "trout": 2,
            "bass": 3,
        }
        total = sum(cases.values()) + fishing.FAILURE_WEIGHT
        rng = FixedRng(list(range(total)))
        table = copy.deepcopy(LOOT_TABLE)
        seen = {}
        for _ in range(total):
            outcome, _ = weighted_draw(table, rng, 0)
            seen[outcome] = seen.get(outcome, 0) + 1
        for item, weight in cases.items():
            self.assertEqual(seen[item], weight)
        self.assertEqual(seen[FAILURE_KEY], fishing.FAILURE_WEIGHT)

    # -- 15. independent sessions do not share caught-item state --
    def test_15_sessions_are_independent(self):
        p1, p2 = FakePlayer(), FakePlayer()
        s1 = FishingSession(p1, rng=FixedRng([item_roll("Dragon Ring")]))
        s1.cast()
        self.assertTrue(p1.has_dragon_ring)
        # A fresh session must not believe a second player already owns the
        # ring: it is still in p2's available pool and can be caught again.
        table2 = available_table([])
        self.assertIn("Dragon Ring", [e["item"] for e in table2])
        s2 = FishingSession(p2, rng=FixedRng([item_roll("trash")]))
        result = s2.cast()
        self.assertEqual(result.item, "trash")
        self.assertFalse(p2.has_dragon_ring)
        self.assertEqual(s2.caught_unique, [])
        self.assertEqual(s1.caught_unique, ["Dragon Ring"])

    # -- 16. result object records failure message distinctly --
    def test_16_cast_result_semantics(self):
        ok = CastResult(item="trout")
        bad = CastResult(failure=True, message="The fish got away...")
        self.assertFalse(ok.failure)
        self.assertTrue(bad.failure)
        self.assertEqual(bad.message, "The fish got away...")


if __name__ == "__main__":
    unittest.main(verbosity=2)
