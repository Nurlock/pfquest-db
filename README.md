# pfQuest DB

A toolkit and SQLite database for World of Warcraft databases, based on **pfQuest-epoch**, with bidirectional importers and exporters for **pfQuest** and **Questie** data formats.

---

## Features

- **Relational SQLite Database (`epoch.db`)**:
  - Full relational schema covering Quests, Units (NPCs), GameObjects, Items, Spawns, Drop tables, Vendors, Zones, Minimap scales, and Area triggers.
  - Foreign key integrity and query indexes.
  - Pre-built views for easy interactive querying:
    - `v_quests`: Quests with resolved quest-giver and turn-in NPC names.
    - `v_spawns`: Unified view of unit and object spawn coordinates with resolved zone names.
    - `v_drops`: Item drops with source NPC/object names and drop rates.
    - `v_vendors`: Items sold by vendors with NPC names and stock counts.
- **Bidirectional Converters**:
  - **pfQuest**: Import and export pfQuest Lua formats (`db/*-epoch.lua`, `db/enUS/*-epoch.lua`, and standard/Reforged flavors).
  - **Questie**: Import and export Questie database formats (`wotlkQuestDB.lua`, `wotlkNpcDB.lua`, etc.).
- **High Performance**:
  - Lua subprocess bridge parses 30,000+ entries in under 0.2 seconds.
  - Built-in transaction batching and WAL mode.

---

## Setup & Requirements

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/)
- `lua` (PUC Lua 5.1+ or LuaJIT)

Setup the environment with `uv`:
```bash
cd pfquest-db
uv sync
```

Run test suite:
```bash
uv run pytest
```

---

## Usage Guide

The CLI is available via `uv run pfquest-db` (or `pfquest-db` within the activated virtual environment):

```
pfquest-db [-h] {init,import-pfquest,export-pfquest,import-questie,export-questie,stats,query,dump-schema} ...
```

### 1. Initialize a Database
```bash
uv run pfquest-db init --db epoch.db
```

### 2. Import pfQuest Data
Import the pfQuest-epoch database into SQLite:
```bash
uv run pfquest-db import-pfquest --src ../pfQuest-epoch --db epoch.db --flavor epoch
```

### 3. Check Statistics
```bash
uv run pfquest-db stats --db epoch.db
```

Output:
```
Database statistics for: epoch.db
  quests          :    2,806
  units           :    3,014
  unit_spawns     :   18,916
  objects         :    1,008
  object_spawns   :   37,465
  items           :    6,027
  item_drops      :    2,083
  item_vendors    :    1,116
  zones           :    2,364
  areatriggers    :       20
  meta            :    2,370
  minimap         :      100
  professions     :        0
----------------------------
  Total records   :   77,289
```

### 4. Interactive Queries
Execute arbitrary SQL queries directly against the database:

```bash
# Query quest with resolved starter NPC
uv run pfquest-db query --db epoch.db \
  "SELECT id, title, min_level, starter_names FROM v_quests WHERE id = 11"

# Query spawn coordinates for an NPC
uv run pfquest-db query --db epoch.db \
  "SELECT entity_type, name, zone_name, x, y FROM v_spawns WHERE name = 'Deputy Rainer'"

# Query drop sources for an item
uv run pfquest-db query --db epoch.db \
  "SELECT item_name, source_type, source_name, drop_chance FROM v_drops WHERE item_id = 782"
```

### 5. Export Back to pfQuest Lua Format
```bash
uv run pfquest-db export-pfquest --db epoch.db --dest ./out-pfquest --flavor epoch
```

### 6. Convert to Questie Database Format
Export the database into Questie's format (`wotlkQuestDB.lua`, `wotlkNpcDB.lua`, etc.):
```bash
uv run pfquest-db export-questie --db epoch.db --dest ./out-questie --flavor wotlk
```

### 7. Import from Questie
You can also import directly from Questie into SQLite:
```bash
uv run pfquest-db import-questie --src ../Questie/Database/Wotlk --db questie.db --flavor wotlk
```

---

## Schema Overview

- **`quests`**: ID, title, min/recommended levels, race/class masks, descriptions, prerequisites, next quests.
- **`quest_starters` / `quest_finishers`**: Junctions linking quests to units, game objects, or items.
- **`quest_objectives`**: Mob slay, object interaction, item collection, and item requirement goals.
- **`units`**: Creatures and NPCs with min/max level, rank, faction, titles, and flags.
- **`unit_spawns`**: Map coordinates (x, y, zone, respawn time) for units.
- **`objects`**: Game objects (chests, nodes, quest turn-in objects) and their factions.
- **`object_spawns`**: Map coordinates for game objects.
- **`items`**: Item records with equipment stats, levels, and classes.
- **`item_drops`**: Drop chances mapped to units or objects.
- **`item_vendors`**: Vendor stock and selling NPCs.
- **`zones`**: AreaTable ID, names, and map dimensions.
- **`areatriggers`**: Exploration coordinates for quest completion triggers.
- **`meta`**: Rares, flight masters, bankers, auctioneers, gathering nodes.
- **`minimap`**: Zone scaling ratios for map pinpoint accuracy.
