"""One shared view of the crafting graph: which recipe builds what, from what, how many.

Every screen that reasons about parts (sell list, farm planner, relic flags, blueprint
cards, build cost, exports) asks this module instead of walking ``recipe`` and
``recipe_ingredient`` on its own. Doing that walk in several places is how the answers
drifted apart: a part a recipe needs twice counted once, a base weapon used twice by a
dual-weapon recipe satisfied by one copy, parts credited to the wrong item, and items
with several recipes picking whichever row came first.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict


def is_component(unique_name: str) -> bool:
    """Parts such as 'Rhino Prime Chassis' live under /Recipes/; farmable resources do not."""
    return "/Recipes/" in unique_name


class RecipeGraph:
    def __init__(self, conn: sqlite3.Connection) -> None:
        from ..account.summary import MASTERY_CATEGORIES  # account imports the codex: import late

        self.result: dict[str, str] = {}
        self.build_price: dict[str, int] = {}
        self.by_result: dict[str, list[str]] = defaultdict(list)
        self._ingredients: dict[str, dict[str, int]] = defaultdict(dict)
        self.used_in: dict[str, list[str]] = defaultdict(list)
        for uid, result, price in conn.execute(
            "SELECT unique_name, result_item, build_price FROM recipe ORDER BY unique_name"
        ):
            self.result[uid] = result
            self.build_price[uid] = price or 0
            self.by_result[result].append(uid)
        # the export can list one ingredient on two lines (dual weapons list the base weapon
        # twice); what the recipe consumes is the sum
        for recipe, item, count in conn.execute(
            "SELECT recipe, item, count FROM recipe_ingredient ORDER BY recipe, item"
        ):
            ings = self._ingredients[recipe]
            ings[item] = ings.get(item, 0) + int(count or 0)
        for recipe, ings in self._ingredients.items():
            for item in ings:
                self.used_in[item].append(recipe)
        self.category: dict[str, str] = dict(conn.execute("SELECT unique_name, category FROM item"))
        self.masterable = {uid for uid, cat in self.category.items() if cat in MASTERY_CATEGORIES}
        self._final: dict[str, str] = {}
        self._preferred: dict[str, str | None] = {}

    # -- lookups ------------------------------------------------------------------------

    def ingredients(self, recipe: str | None) -> dict[str, int]:
        """Ingredient -> total count for one recipe."""
        return dict(self._ingredients.get(recipe, {})) if recipe else {}

    def blueprints_for(self, item: str) -> list[str]:
        return list(self.by_result.get(item, []))

    def recipe_for(self, item: str) -> str | None:
        """The recipe a player normally builds ``item`` with.

        Several items have more than one recipe: a dojo or research version made from
        resources next to the one built from parts, or a "convert" recipe that turns
        another weapon into this one. Prefer the one built from parts, never a convert
        recipe when there is another, and break ties by name so the answer never changes
        from one run to the next.
        """
        if item not in self._preferred:
            options = self.by_result.get(item, [])
            self._preferred[item] = min(options, key=self._rank) if options else None
        return self._preferred[item]

    def _rank(self, recipe: str) -> tuple:
        ings = self._ingredients.get(recipe, {})
        from_parts = any(is_component(i) or i in self.masterable for i in ings)
        convert = "convert" in recipe.rsplit("/", 1)[-1].lower()
        return (convert, not from_parts, recipe)

    # -- what a part is for -------------------------------------------------------------

    def final_item(self, uid: str) -> str:
        """What a part or blueprint ends up building.

        A blueprint stands for the item it makes; a part stands for the item its recipe
        makes, climbing until a masterable item (a frame, a weapon) or a plain resource is
        reached. The climb stops at the first masterable item, so Bronco Prime parts belong
        to Bronco Prime, not to the Akbronco Prime that is built from two Bronco Primes.
        """
        if uid in self._final:
            return self._final[uid]
        cur = self.result.get(uid, uid)
        for _ in range(6):
            if cur in self.masterable or (self.category.get(cur) == "Resource" and not is_component(cur)):
                break
            parents = sorted({self.result[r] for r in self.used_in.get(cur, ())})
            if not parents:
                break
            # prefer what a player builds: a masterable result, then the result whose
            # preferred recipe actually uses this part
            cur = min(
                parents,
                key=lambda p: (p not in self.masterable, cur not in self.ingredients(self.recipe_for(p)), p),
            )
        self._final[uid] = cur
        return cur

    def needed_count(self, uid: str, target: str | None = None) -> int:
        """How many of ``uid`` building ``target`` takes (default: what uid ends up building).

        A part blueprint counts as the part it makes: the Akstiletto Prime recipe needs two
        barrels, so two barrels, or barrel blueprints, are needed.
        """
        target = target or self.final_item(uid)
        recipe = self.recipe_for(target)
        if recipe is None or uid in self.by_result.get(target, ()):
            return 1  # the item's own blueprint
        ings = self.ingredients(recipe)
        part = self.result.get(uid, uid)
        return ings.get(part) or ings.get(uid) or 1
