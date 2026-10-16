"""Read-side API over the codex database."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .names import normalize


@dataclass
class Source:
    kind: str  # relic | node | enemy | bounty | transient | vendor | syndicate | market
    where: str
    detail: str
    chance: float | None = None
    rarity: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class TreeNode:
    item: str
    name: str
    count: int
    recipe: str | None = None
    children: list[TreeNode] = field(default_factory=list)


class Codex:
    def __init__(self, path: Path) -> None:
        if not Path(path).exists():
            raise FileNotFoundError(f"codex not found at {path}; run `openwarframe codex update`")
        self.conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    # -- meta --------------------------------------------------------------------------
    def versions(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute("SELECT source, version, fetched_at, meta FROM source_version ORDER BY source")
        )

    def counts(self) -> dict[str, int]:
        tables = [
            "item",
            "recipe",
            "recipe_ingredient",
            "relic",
            "relic_reward",
            "node",
            "node_reward",
            "enemy_drop",
            "bounty_reward",
            "transient_reward",
            "vendor_offer",
            "syndicate",
            "syndicate_offer",
            "syndicate_drop",
            "challenge",
            "market_item",
            "name_map",
            "unresolved_name",
        ]
        return {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

    def unresolved(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT name, count, sample_source FROM unresolved_name ORDER BY count DESC, name LIMIT ?",
                (limit,),
            )
        )

    # -- lookup --------------------------------------------------------------------------
    def search(self, text: str, limit: int = 25) -> list[sqlite3.Row]:
        like = f"%{text.strip()}%"
        return list(
            self.conn.execute(
                """SELECT unique_name, name, category, mastery_req FROM item
                   WHERE name LIKE ? OR unique_name LIKE ?
                   ORDER BY CASE WHEN lower(name) = lower(?) THEN 0 ELSE 1 END, length(name), name
                   LIMIT ?""",
                (like, like, text.strip(), limit),
            )
        )

    def resolve(self, query: str) -> str | None:
        """Accept a uniqueName, an exact display name, or a unique partial match."""
        q = query.strip()
        if q.startswith("/Lotus/"):
            row = self.conn.execute("SELECT unique_name FROM item WHERE unique_name = ?", (q,)).fetchone()
            if row:
                return row[0]
            row = self.conn.execute("SELECT unique_name FROM recipe WHERE unique_name = ?", (q,)).fetchone()
            return row[0] if row else None
        row = self.conn.execute("SELECT unique_name FROM name_map WHERE name = ?", (normalize(q),)).fetchone()
        if row:
            return row[0]
        rows = self.search(q, limit=2)
        if len(rows) == 1 or (rows and rows[0]["name"].lower() == q.lower()):
            return rows[0]["unique_name"]
        return None

    def item(self, unique_name: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM item WHERE unique_name = ?", (unique_name,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["data"] = json.loads(d["data"]) if d.get("data") else {}
        d["market"] = self._market(unique_name)
        return d

    def name_of(self, unique_name: str) -> str:
        row = self.conn.execute("SELECT name FROM item WHERE unique_name = ?", (unique_name,)).fetchone()
        if row:
            return row[0]
        row = self.conn.execute(
            "SELECT i.name FROM recipe r JOIN item i ON i.unique_name = r.result_item WHERE r.unique_name = ?",
            (unique_name,),
        ).fetchone()
        if row:
            return f"{row[0]} Blueprint"
        return unique_name.rsplit("/", 1)[-1]

    def _market(self, unique_name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT slug, name FROM market_item WHERE unique_name = ?", (unique_name,)
        ).fetchone()
        return dict(row) if row else None

    # -- recipes -------------------------------------------------------------------------
    def recipes_for(self, result_item: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM recipe WHERE result_item = ?", (result_item,)))

    def ingredients(self, recipe: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT ri.item, ri.count, COALESCE(i.name, ri.item) AS name
                   FROM recipe_ingredient ri LEFT JOIN item i ON i.unique_name = ri.item
                   WHERE ri.recipe = ? ORDER BY ri.count DESC""",
                (recipe,),
            )
        )

    def is_component(self, unique_name: str) -> bool:
        """Parts such as 'Rhino Prime Chassis' live under /Recipes/; farmable resources do not."""
        return "/Recipes/" in unique_name

    def crafting_tree(
        self, unique_name: str, *, count: int = 1, depth: int = 6, expand_resources: bool = False
    ) -> TreeNode:
        """Recursive recipe expansion.

        Plain resources (Orokin Cells, Morphics, ...) have dojo/market recipes that nobody
        uses to build a frame; they are leaves unless ``expand_resources`` is set. The
        root is always expanded.
        """
        return self._tree(unique_name, count, depth, expand_resources, root=True)

    def _tree(
        self, unique_name: str, count: int, depth: int, expand_resources: bool, *, root: bool
    ) -> TreeNode:
        node = TreeNode(item=unique_name, name=self.name_of(unique_name), count=count)
        if depth <= 0:
            return node
        recipes = self.recipes_for(unique_name)
        if not recipes:
            return node
        if not root and not expand_resources:
            row = self.conn.execute(
                "SELECT category FROM item WHERE unique_name = ?", (unique_name,)
            ).fetchone()
            if row and row[0] == "Resource" and not self.is_component(unique_name):
                return node
        recipe = recipes[0]
        node.recipe = recipe["unique_name"]
        per_craft = recipe["num"] or 1
        crafts = -(-count // per_craft)  # ceil
        for ing in self.ingredients(recipe["unique_name"]):
            node.children.append(
                self._tree(ing["item"], ing["count"] * crafts, depth - 1, expand_resources, root=False)
            )
        return node

    def tree_totals(self, tree: TreeNode) -> dict[str, tuple[str, int]]:
        """Leaf totals: uniqueName -> (name, count)."""
        totals: dict[str, tuple[str, int]] = {}

        def walk(n: TreeNode) -> None:
            if not n.children:
                name, c = totals.get(n.item, (n.name, 0))
                totals[n.item] = (name, c + n.count)
            for ch in n.children:
                walk(ch)

        walk(tree)
        return totals

    def what_needs(self, unique_name: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT r.unique_name AS recipe, r.result_item, COALESCE(i.name, r.result_item) AS result_name, ri.count
                   FROM recipe_ingredient ri JOIN recipe r ON r.unique_name = ri.recipe
                   LEFT JOIN item i ON i.unique_name = r.result_item
                   WHERE ri.item = ? ORDER BY result_name""",
                (unique_name,),
            )
        )

    # -- sources -------------------------------------------------------------------------
    def sources_for(self, unique_name: str) -> list[Source]:
        """Every known way to obtain an item or its blueprint, unranked."""
        targets = [unique_name] + [r["unique_name"] for r in self.recipes_for(unique_name)]
        out: list[Source] = []
        q = ",".join("?" * len(targets))

        for r in self.conn.execute(
            f"""SELECT rr.*, rl.name AS relic_name, rl.tier FROM relic_reward rr JOIN relic rl ON rl.unique_name = rr.relic
                WHERE rr.item IN ({q}) ORDER BY rl.tier, rl.name""",
            targets,
        ):
            out.append(
                Source(
                    "relic",
                    f"{r['relic_name']} relic",
                    f"{r['rarity'].title()} - Intact {r['chance_intact']}% -> Radiant {r['chance_radiant']}%",
                    r["chance_radiant"],
                    r["rarity"],
                    {
                        "relic": r["relic"],
                        "tier": r["tier"],
                        "intact": r["chance_intact"],
                        "radiant": r["chance_radiant"],
                    },
                )
            )
        for r in self.conn.execute(
            f"""SELECT nr.*, n.mission_type, n.faction, n.level_min, n.level_max FROM node_reward nr
                LEFT JOIN node n ON n.id = nr.node WHERE nr.item IN ({q}) ORDER BY nr.chance DESC""",
            targets,
        ):
            mode = r["mission_type"] or r["game_mode"] or ""
            out.append(
                Source(
                    "node",
                    f"{r['place']} ({r['planet']})",
                    f"{mode} - rotation {r['rotation']} - {r['chance']}%",
                    r["chance"],
                    r["rarity"],
                    {"node": r["node"], "rotation": r["rotation"], "level": (r["level_min"], r["level_max"])},
                )
            )
        for r in self.conn.execute(
            f"SELECT * FROM enemy_drop WHERE item IN ({q}) ORDER BY chance DESC", targets
        ):
            dc = f" - drops {r['kind']} {r['enemy_drop_chance']}%" if r["enemy_drop_chance"] else ""
            out.append(
                Source(
                    "enemy", r["enemy_name"], f"{r['kind']} - {r['chance']}%{dc}", r["chance"], r["rarity"]
                )
            )
        for r in self.conn.execute(
            f"SELECT * FROM bounty_reward WHERE item IN ({q}) ORDER BY chance DESC", targets
        ):
            stage = f" - {r['stage']}" if r["stage"] else ""
            out.append(
                Source(
                    "bounty",
                    f"{r['bounty']} ({r['region']})",
                    f"rotation {r['rotation']}{stage} - {r['chance']}%",
                    r["chance"],
                    r["rarity"],
                )
            )
        for r in self.conn.execute(
            f"SELECT * FROM transient_reward WHERE item IN ({q}) ORDER BY chance DESC", targets
        ):
            rot = f" - rotation {r['rotation']}" if r["rotation"] else ""
            out.append(Source("transient", r["objective"], f"{r['chance']}%{rot}", r["chance"], r["rarity"]))
        for r in self.conn.execute(f"SELECT * FROM vendor_offer WHERE item IN ({q})", targets):
            prices = json.loads(r["prices"] or "{}")
            parts = [
                f"{p['count']}x {self.name_of(p['item'])}" for p in prices.get("items", []) if p.get("item")
            ]
            for k in ("credits", "standing", "regularPrice", "premiumPrice"):
                if prices.get(k):
                    parts.append(f"{prices[k]} {k}")
            out.append(
                Source(
                    "vendor",
                    r["vendor_name"],
                    ", ".join(parts) or "price unknown",
                    None,
                    None,
                    {"vendor": r["vendor"]},
                )
            )
        for r in self.conn.execute(
            f"""SELECT so.*, s.name AS syndicate_name FROM syndicate_offer so JOIN syndicate s ON s.tag = so.syndicate
                WHERE so.item IN ({q})""",
            targets,
        ):
            out.append(
                Source(
                    "syndicate",
                    r["syndicate_name"],
                    f"{r['standing_cost']} standing - rank {r['required_level']}"
                    + (f" - {r['credits_cost']} credits" if r["credits_cost"] else ""),
                    None,
                    None,
                )
            )
        for r in self.conn.execute(f"SELECT * FROM syndicate_drop WHERE item IN ({q})", targets):
            out.append(
                Source(
                    "syndicate",
                    r["syndicate"],
                    f"{r['place']} - {r['standing']} standing - {r['cost']} credits",
                    r["chance"],
                    r["rarity"],
                )
            )
        m = self._market(unique_name)
        if m:
            out.append(
                Source(
                    "market",
                    "warframe.market",
                    f"tradeable as '{m['slug']}'",
                    None,
                    None,
                    {"slug": m["slug"]},
                )
            )
        return out
