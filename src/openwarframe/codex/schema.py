"""SQLite schema for the codex. Rebuilt from sources; safe to delete."""

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE source_version (
    source      TEXT PRIMARY KEY,
    version     TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    meta        TEXT
);

CREATE TABLE item (
    unique_name TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,      -- Warframe, Archwing, Primary, ..., Resource, Mod, Relic, Arcane, Quest, Gear, ...
    type        TEXT,               -- productCategory from the export (Suits, LongGuns, MiscItems, ...)
    mastery_req INTEGER,
    image       TEXT,
    description TEXT,
    data        TEXT                -- raw JSON record from the export
);
CREATE INDEX item_name ON item(name);
CREATE INDEX item_category ON item(category);

CREATE TABLE recipe (
    unique_name   TEXT PRIMARY KEY,
    result_item   TEXT NOT NULL,
    build_price   INTEGER,
    build_time_s  INTEGER,
    rush_price    INTEGER,
    num           INTEGER,
    consume_on_use INTEGER
);
CREATE INDEX recipe_result ON recipe(result_item);

CREATE TABLE recipe_ingredient (
    recipe  TEXT NOT NULL,
    item    TEXT NOT NULL,
    count   INTEGER NOT NULL
);
CREATE INDEX recipe_ingredient_item ON recipe_ingredient(item);
CREATE INDEX recipe_ingredient_recipe ON recipe_ingredient(recipe);

CREATE TABLE relic (
    unique_name TEXT PRIMARY KEY,
    name        TEXT NOT NULL,      -- "Lith R2"
    tier        TEXT NOT NULL,      -- Lith, Meso, Neo, Axi, Requiem, Omnia
    category    TEXT,               -- from export-plus (e.g. Eterna)
    quality     TEXT                -- VPQ_BRONZE etc. (export-plus)
);
CREATE INDEX relic_name ON relic(name);

CREATE TABLE relic_reward (
    relic             TEXT NOT NULL,
    item              TEXT NOT NULL, -- item or recipe uniqueName
    rarity            TEXT NOT NULL, -- COMMON / UNCOMMON / RARE
    item_count        INTEGER,
    chance_intact     REAL,
    chance_exceptional REAL,
    chance_flawless   REAL,
    chance_radiant    REAL
);
CREATE INDEX relic_reward_item ON relic_reward(item);
CREATE INDEX relic_reward_relic ON relic_reward(relic);

CREATE TABLE node (
    id           TEXT PRIMARY KEY,  -- SolNode94
    name         TEXT NOT NULL,
    planet       TEXT NOT NULL,
    system_index INTEGER,
    mission_type TEXT,
    faction      TEXT,
    level_min    INTEGER,
    level_max    INTEGER,
    mastery_req  INTEGER,
    node_type    INTEGER,
    data         TEXT
);
CREATE INDEX node_name ON node(name);

CREATE TABLE node_reward (
    node       TEXT,                -- resolved node id, or NULL
    planet     TEXT NOT NULL,
    place      TEXT NOT NULL,
    game_mode  TEXT,
    rotation   TEXT NOT NULL,
    item_name  TEXT NOT NULL,
    item       TEXT,                -- resolved uniqueName, or NULL
    rarity     TEXT,
    chance     REAL,
    is_event   INTEGER
);
CREATE INDEX node_reward_item ON node_reward(item);
CREATE INDEX node_reward_node ON node_reward(node);

CREATE TABLE enemy_drop (
    enemy_name       TEXT NOT NULL,
    item_name        TEXT NOT NULL,
    item             TEXT,
    kind             TEXT NOT NULL, -- mod, blueprint, resource, sigil, item
    rarity           TEXT,
    chance           REAL,          -- chance of this item once the enemy drops something
    enemy_drop_chance REAL          -- chance the enemy drops anything of this kind
);
CREATE INDEX enemy_drop_item ON enemy_drop(item);
CREATE INDEX enemy_drop_enemy ON enemy_drop(enemy_name);

CREATE TABLE bounty_reward (
    region      TEXT NOT NULL,      -- Cetus, Orb Vallis, Cambion Drift, Zariman, Entrati Lab, Hollvania
    bounty      TEXT NOT NULL,      -- "Level 5 - 15 Cetus Bounty"
    rotation    TEXT NOT NULL,
    stage       TEXT,
    item_name   TEXT NOT NULL,
    item        TEXT,
    rarity      TEXT,
    chance      REAL
);
CREATE INDEX bounty_reward_item ON bounty_reward(item);

CREATE TABLE transient_reward (
    objective   TEXT NOT NULL,      -- Arbitrations, Sortie, Nightmare Mode, key names...
    rotation    TEXT,
    item_name   TEXT NOT NULL,
    item        TEXT,
    rarity      TEXT,
    chance      REAL
);
CREATE INDEX transient_reward_item ON transient_reward(item);

CREATE TABLE vendor_offer (
    vendor      TEXT NOT NULL,      -- manifest path
    vendor_name TEXT NOT NULL,
    item        TEXT NOT NULL,      -- uniqueName (StoreItems prefix stripped)
    quantity    INTEGER,
    prices      TEXT,               -- JSON [{"item": uniqueName, "count": n}] and/or credits/standing
    always_offered INTEGER
);
CREATE INDEX vendor_offer_item ON vendor_offer(item);

CREATE TABLE syndicate (
    tag         TEXT PRIMARY KEY,   -- ArbitersSyndicate
    unique_name TEXT,
    name        TEXT NOT NULL,
    data        TEXT
);

CREATE TABLE syndicate_offer (
    syndicate      TEXT NOT NULL,
    item           TEXT NOT NULL,
    standing_cost  INTEGER,
    credits_cost   INTEGER,
    required_level INTEGER,
    rank_up_reward INTEGER
);
CREATE INDEX syndicate_offer_item ON syndicate_offer(item);

CREATE TABLE syndicate_drop (
    syndicate  TEXT NOT NULL,       -- WFCD syndicate table (names)
    item_name  TEXT NOT NULL,
    item       TEXT,
    place      TEXT,
    standing   INTEGER,
    cost       INTEGER,
    chance     REAL,
    rarity     TEXT
);
CREATE INDEX syndicate_drop_item ON syndicate_drop(item);

CREATE TABLE challenge (
    unique_name TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    rewards     TEXT
);

CREATE TABLE market_item (
    unique_name TEXT PRIMARY KEY,
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    tags        TEXT
);

CREATE TABLE name_map (
    name        TEXT PRIMARY KEY,   -- normalized display name
    unique_name TEXT NOT NULL,
    kind        TEXT NOT NULL       -- item | recipe | relic
);

CREATE TABLE unresolved_name (
    name    TEXT PRIMARY KEY,
    count   INTEGER NOT NULL,
    sample_source TEXT
);
"""
