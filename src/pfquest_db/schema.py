"""SQLite schema definitions, tables, indexes, and views for pfQuest DB."""

SCHEMA_SQL = """
-- Zones
CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY,
    name TEXT,
    map_id INTEGER,
    x_min REAL,
    x_max REAL,
    y_min REAL,
    y_max REAL
);

-- Units / NPCs
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY,
    name TEXT,
    min_level INTEGER,
    max_level INTEGER,
    rank INTEGER DEFAULT 0,
    faction TEXT,
    sub_name TEXT,
    npc_flags INTEGER DEFAULT 0
);

-- Unit coordinate spawns
CREATE TABLE IF NOT EXISTS unit_spawns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    zone_id INTEGER NOT NULL REFERENCES zones(id),
    x REAL NOT NULL,
    y REAL NOT NULL,
    respawn_time INTEGER DEFAULT 0,
    UNIQUE(unit_id, zone_id, x, y)
);

-- Game Objects
CREATE TABLE IF NOT EXISTS objects (
    id INTEGER PRIMARY KEY,
    name TEXT,
    faction TEXT,
    faction_id INTEGER
);

-- Object coordinate spawns
CREATE TABLE IF NOT EXISTS object_spawns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    zone_id INTEGER NOT NULL REFERENCES zones(id),
    x REAL NOT NULL,
    y REAL NOT NULL,
    respawn_time INTEGER DEFAULT 0,
    UNIQUE(object_id, zone_id, x, y)
);

-- Items
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT,
    item_level INTEGER,
    required_level INTEGER,
    class_id INTEGER,
    subclass_id INTEGER,
    food_type INTEGER,
    ammo_type INTEGER,
    flags INTEGER,
    teaches_spell INTEGER
);

-- Item drop sources
CREATE TABLE IF NOT EXISTS item_drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK(source_type IN ('unit', 'object')),
    source_id INTEGER NOT NULL,
    drop_chance REAL NOT NULL,
    UNIQUE(item_id, source_type, source_id)
);

-- Item vendor sources
CREATE TABLE IF NOT EXISTS item_vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    unit_id INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    stock INTEGER DEFAULT 0,
    UNIQUE(item_id, unit_id)
);

-- Quests
CREATE TABLE IF NOT EXISTS quests (
    id INTEGER PRIMARY KEY,
    title TEXT,
    min_level INTEGER,
    quest_level INTEGER,
    required_races INTEGER,
    required_classes INTEGER,
    objective_text TEXT,
    description TEXT,
    next_quest_id INTEGER,
    required_skill_id INTEGER,
    required_skill_value INTEGER,
    required_min_rep_faction INTEGER,
    required_min_rep_value INTEGER,
    required_max_rep_faction INTEGER,
    required_max_rep_value INTEGER,
    event_id INTEGER,
    source_item_id INTEGER,
    special_flags INTEGER,
    quest_flags INTEGER
);

-- Quest Starters
CREATE TABLE IF NOT EXISTS quest_starters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_id INTEGER NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    starter_type TEXT NOT NULL CHECK(starter_type IN ('unit', 'object', 'item')),
    starter_id INTEGER NOT NULL,
    UNIQUE(quest_id, starter_type, starter_id)
);

-- Quest Finishers
CREATE TABLE IF NOT EXISTS quest_finishers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_id INTEGER NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    finisher_type TEXT NOT NULL CHECK(finisher_type IN ('unit', 'object')),
    finisher_id INTEGER NOT NULL,
    UNIQUE(quest_id, finisher_type, finisher_id)
);

-- Quest Objectives
CREATE TABLE IF NOT EXISTS quest_objectives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_id INTEGER NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    objective_type TEXT NOT NULL CHECK(objective_type IN ('unit', 'object', 'item', 'itemreq', 'reputation', 'spell')),
    target_id INTEGER,
    amount INTEGER DEFAULT 0,
    text TEXT,
    icon TEXT,
    UNIQUE(quest_id, objective_type, target_id)
);

-- Quest Prerequisites
CREATE TABLE IF NOT EXISTS quest_prerequisites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_id INTEGER NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    pre_quest_id INTEGER NOT NULL,
    is_group INTEGER DEFAULT 0,
    UNIQUE(quest_id, pre_quest_id, is_group)
);

-- Mutually Exclusive / Conflicting Quests
CREATE TABLE IF NOT EXISTS quest_exclusive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_id INTEGER NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    exclusive_quest_id INTEGER NOT NULL,
    UNIQUE(quest_id, exclusive_quest_id)
);

-- Area Triggers
CREATE TABLE IF NOT EXISTS areatriggers (
    id INTEGER PRIMARY KEY,
    name TEXT,
    zone_id INTEGER REFERENCES zones(id),
    x REAL NOT NULL,
    y REAL NOT NULL
);

-- Meta relations (chests, rares, flight, auctioneers, bankers, etc.)
CREATE TABLE IF NOT EXISTS meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    value TEXT,
    UNIQUE(category, entity_id)
);

-- Minimap area scaling
CREATE TABLE IF NOT EXISTS minimap (
    zone_id INTEGER PRIMARY KEY,
    x_scale REAL NOT NULL,
    y_scale REAL NOT NULL
);

-- Professions
CREATE TABLE IF NOT EXISTS professions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_unit_spawns_unit ON unit_spawns(unit_id);
CREATE INDEX IF NOT EXISTS idx_unit_spawns_zone ON unit_spawns(zone_id);
CREATE INDEX IF NOT EXISTS idx_object_spawns_object ON object_spawns(object_id);
CREATE INDEX IF NOT EXISTS idx_object_spawns_zone ON object_spawns(zone_id);
CREATE INDEX IF NOT EXISTS idx_item_drops_item ON item_drops(item_id);
CREATE INDEX IF NOT EXISTS idx_item_drops_source ON item_drops(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_item_vendors_item ON item_vendors(item_id);
CREATE INDEX IF NOT EXISTS idx_item_vendors_unit ON item_vendors(unit_id);
CREATE INDEX IF NOT EXISTS idx_quest_starters_quest ON quest_starters(quest_id);
CREATE INDEX IF NOT EXISTS idx_quest_finishers_quest ON quest_finishers(quest_id);
CREATE INDEX IF NOT EXISTS idx_quest_objectives_quest ON quest_objectives(quest_id);
CREATE INDEX IF NOT EXISTS idx_quest_prereq_quest ON quest_prerequisites(quest_id);
CREATE INDEX IF NOT EXISTS idx_quest_exclusive_quest ON quest_exclusive(quest_id);
CREATE INDEX IF NOT EXISTS idx_meta_category ON meta(category, entity_id);
CREATE INDEX IF NOT EXISTS idx_units_name ON units(name);
CREATE INDEX IF NOT EXISTS idx_objects_name ON objects(name);
CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
CREATE INDEX IF NOT EXISTS idx_quests_title ON quests(title);
CREATE INDEX IF NOT EXISTS idx_quests_lvl ON quests(quest_level, min_level);

-- Human-Friendly Views
DROP VIEW IF EXISTS v_quests;
CREATE VIEW v_quests AS
SELECT 
    q.id,
    q.title,
    q.min_level,
    q.quest_level,
    (SELECT GROUP_CONCAT(COALESCE(u.name, 'Unit ' || qs.starter_id), ', ') 
     FROM quest_starters qs 
     LEFT JOIN units u ON qs.starter_id = u.id AND qs.starter_type = 'unit'
     WHERE qs.quest_id = q.id) AS starter_names,
    (SELECT GROUP_CONCAT(COALESCE(u.name, 'Unit ' || qf.finisher_id), ', ') 
     FROM quest_finishers qf 
     LEFT JOIN units u ON qf.finisher_id = u.id AND qf.finisher_type = 'unit'
     WHERE qf.quest_id = q.id) AS finisher_names,
    q.objective_text,
    q.description
FROM quests q;

DROP VIEW IF EXISTS v_quest_details;
CREATE VIEW v_quest_details AS
SELECT 
    q.id AS quest_id,
    q.title,
    q.min_level,
    q.quest_level,
    q.required_races,
    q.required_classes,
    (SELECT GROUP_CONCAT(COALESCE(u.name, 'Unit #' || qs.starter_id) || ' (' || qs.starter_type || ')', '; ')
     FROM quest_starters qs
     LEFT JOIN units u ON qs.starter_type = 'unit' AND qs.starter_id = u.id
     WHERE qs.quest_id = q.id) AS starters,
    (SELECT GROUP_CONCAT(COALESCE(u.name, 'Unit #' || qf.finisher_id) || ' (' || qf.finisher_type || ')', '; ')
     FROM quest_finishers qf
     LEFT JOIN units u ON qf.finisher_type = 'unit' AND qf.finisher_id = u.id
     WHERE qf.quest_id = q.id) AS finishers,
    (SELECT GROUP_CONCAT(
        CASE qo.objective_type
            WHEN 'unit' THEN 'Kill: ' || COALESCE(u.name, 'Unit #' || qo.target_id) || ' x' || qo.amount
            WHEN 'item' THEN 'Collect: ' || COALESCE(i.name, 'Item #' || qo.target_id) || ' x' || qo.amount
            WHEN 'object' THEN 'Interact: ' || COALESCE(o.name, 'Object #' || qo.target_id) || ' x' || qo.amount
            WHEN 'itemreq' THEN 'Require Item: ' || COALESCE(i.name, 'Item #' || qo.target_id)
            WHEN 'reputation' THEN 'Reputation: ' || qo.target_id || ' >= ' || qo.amount
            ELSE COALESCE(qo.text, qo.objective_type)
        END, ' | ')
     FROM quest_objectives qo
     LEFT JOIN units u ON qo.objective_type = 'unit' AND qo.target_id = u.id
     LEFT JOIN items i ON qo.objective_type IN ('item', 'itemreq') AND qo.target_id = i.id
     LEFT JOIN objects o ON qo.objective_type = 'object' AND qo.target_id = o.id
     WHERE qo.quest_id = q.id) AS objectives,
    (SELECT GROUP_CONCAT(qp.pre_quest_id || ' (' || COALESCE(pq.title, 'Unknown') || ')', ', ')
     FROM quest_prerequisites qp
     LEFT JOIN quests pq ON qp.pre_quest_id = pq.id
     WHERE qp.quest_id = q.id) AS prerequisites,
    q.next_quest_id,
    (SELECT title FROM quests WHERE id = q.next_quest_id) AS next_quest_title,
    (SELECT GROUP_CONCAT(qe.exclusive_quest_id || ' (' || COALESCE(eq.title, 'Unknown') || ')', ', ')
     FROM quest_exclusive qe
     LEFT JOIN quests eq ON qe.exclusive_quest_id = eq.id
     WHERE qe.quest_id = q.id) AS exclusive_with,
    q.objective_text,
    q.description
FROM quests q;

DROP VIEW IF EXISTS v_quest_objectives;
CREATE VIEW v_quest_objectives AS
SELECT 
    qo.quest_id,
    q.title AS quest_title,
    qo.objective_type,
    qo.target_id,
    CASE qo.objective_type
        WHEN 'unit' THEN u.name
        WHEN 'item' THEN i.name
        WHEN 'itemreq' THEN i.name
        WHEN 'object' THEN o.name
        ELSE NULL
    END AS target_name,
    qo.amount,
    qo.text AS custom_text,
    qo.icon
FROM quest_objectives qo
JOIN quests q ON qo.quest_id = q.id
LEFT JOIN units u ON qo.objective_type = 'unit' AND qo.target_id = u.id
LEFT JOIN items i ON qo.objective_type IN ('item', 'itemreq') AND qo.target_id = i.id
LEFT JOIN objects o ON qo.objective_type = 'object' AND qo.target_id = o.id;

DROP VIEW IF EXISTS v_npc_details;
CREATE VIEW v_npc_details AS
SELECT 
    u.id,
    u.name,
    u.sub_name,
    u.min_level,
    u.max_level,
    u.rank,
    u.faction,
    (SELECT GROUP_CONCAT(DISTINCT z.name)
     FROM unit_spawns s
     JOIN zones z ON s.zone_id = z.id
     WHERE s.unit_id = u.id) AS zones,
    (SELECT count(*) FROM unit_spawns WHERE unit_id = u.id) AS spawn_count,
    (SELECT GROUP_CONCAT(qs.quest_id || ': ' || q.title, '; ')
     FROM quest_starters qs
     JOIN quests q ON qs.quest_id = q.id
     WHERE qs.starter_type = 'unit' AND qs.starter_id = u.id) AS quests_started,
    (SELECT GROUP_CONCAT(qf.quest_id || ': ' || q.title, '; ')
     FROM quest_finishers qf
     JOIN quests q ON qf.quest_id = q.id
     WHERE qf.finisher_type = 'unit' AND qf.finisher_id = u.id) AS quests_ended
FROM units u;

DROP VIEW IF EXISTS v_item_sources;
CREATE VIEW v_item_sources AS
SELECT 
    i.id AS item_id,
    i.name AS item_name,
    i.item_level,
    i.required_level,
    d.source_type,
    d.source_id,
    CASE d.source_type
        WHEN 'unit' THEN u.name
        WHEN 'object' THEN o.name
        ELSE 'Unknown'
    END AS source_name,
    d.drop_chance,
    (SELECT GROUP_CONCAT(DISTINCT z.name)
     FROM unit_spawns s JOIN zones z ON s.zone_id = z.id
     WHERE d.source_type = 'unit' AND s.unit_id = d.source_id) AS drop_zones,
    (SELECT qs.quest_id FROM quest_starters qs WHERE qs.starter_type = 'item' AND qs.starter_id = i.id LIMIT 1) AS starts_quest_id
FROM items i
JOIN item_drops d ON i.id = d.item_id
LEFT JOIN units u ON d.source_type = 'unit' AND d.source_id = u.id
LEFT JOIN objects o ON d.source_type = 'object' AND d.source_id = o.id;

DROP VIEW IF EXISTS v_zone_summary;
CREATE VIEW v_zone_summary AS
SELECT 
    z.id AS zone_id,
    z.name AS zone_name,
    z.map_id,
    (SELECT count(DISTINCT s.unit_id) FROM unit_spawns s WHERE s.zone_id = z.id) AS unique_units,
    (SELECT count(*) FROM unit_spawns s WHERE s.zone_id = z.id) AS unit_spawns,
    (SELECT count(DISTINCT s.object_id) FROM object_spawns s WHERE s.zone_id = z.id) AS unique_objects,
    (SELECT count(*) FROM object_spawns s WHERE s.zone_id = z.id) AS object_spawns
FROM zones z
WHERE z.id IN (SELECT DISTINCT zone_id FROM unit_spawns UNION SELECT DISTINCT zone_id FROM object_spawns);

DROP VIEW IF EXISTS v_spawns;
CREATE VIEW v_spawns AS
SELECT 'unit' AS entity_type, s.unit_id AS entity_id, u.name, s.zone_id, z.name AS zone_name, s.x, s.y, s.respawn_time
FROM unit_spawns s
LEFT JOIN units u ON s.unit_id = u.id
LEFT JOIN zones z ON s.zone_id = z.id
UNION ALL
SELECT 'object' AS entity_type, s.object_id AS entity_id, o.name, s.zone_id, z.name AS zone_name, s.x, s.y, s.respawn_time
FROM object_spawns s
LEFT JOIN objects o ON s.object_id = o.id
LEFT JOIN zones z ON s.zone_id = z.id;

DROP VIEW IF EXISTS v_drops;
CREATE VIEW v_drops AS
SELECT 
    d.item_id,
    i.name AS item_name,
    d.source_type,
    d.source_id,
    CASE d.source_type
        WHEN 'unit' THEN COALESCE(u.name, 'Unit ' || d.source_id)
        WHEN 'object' THEN COALESCE(o.name, 'Object ' || d.source_id)
        ELSE 'Unknown'
    END AS source_name,
    d.drop_chance
FROM item_drops d
LEFT JOIN items i ON d.item_id = i.id
LEFT JOIN units u ON d.source_type = 'unit' AND d.source_id = u.id
LEFT JOIN objects o ON d.source_type = 'object' AND d.source_id = o.id;

DROP VIEW IF EXISTS v_vendors;
CREATE VIEW v_vendors AS
SELECT 
    v.item_id,
    i.name AS item_name,
    v.unit_id,
    u.name AS vendor_name,
    v.stock
FROM item_vendors v
LEFT JOIN items i ON v.item_id = i.id
LEFT JOIN units u ON v.unit_id = u.id;
"""

FTS_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    entity_type UNINDEXED,
    entity_id UNINDEXED,
    name,
    extra_text,
    tokenize = 'porter unicode61'
);
"""


def init_database(conn) -> None:
    """Initialize the schema, tables, indexes, and views on the given connection."""
    conn.executescript(SCHEMA_SQL)
    conn.executescript(FTS_SCHEMA_SQL)
    conn.commit()


def rebuild_search_index(conn) -> int:
    """Rebuild the FTS5 search index from all core tables."""
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
            entity_type UNINDEXED,
            entity_id UNINDEXED,
            name,
            extra_text,
            tokenize = 'porter unicode61'
        );
        DELETE FROM search_index;

        INSERT INTO search_index(entity_type, entity_id, name, extra_text)
        SELECT 'quest', id, title, COALESCE(objective_text, '') || ' ' || COALESCE(description, '')
        FROM quests WHERE title IS NOT NULL;

        INSERT INTO search_index(entity_type, entity_id, name, extra_text)
        SELECT 'unit', id, name, COALESCE(sub_name, '')
        FROM units WHERE name IS NOT NULL;

        INSERT INTO search_index(entity_type, entity_id, name, extra_text)
        SELECT 'item', id, name, ''
        FROM items WHERE name IS NOT NULL;

        INSERT INTO search_index(entity_type, entity_id, name, extra_text)
        SELECT 'object', id, name, ''
        FROM objects WHERE name IS NOT NULL;
    """)
    conn.commit()
    cur = conn.execute("SELECT count(*) FROM search_index")
    return cur.fetchone()[0]
