# Prompting Guide: Querying `pfquest-db` with SQL & LLMs

The `pfquest-db` SQLite database is intentionally designed to be **simple to prompt** for AI coding assistants, data analysts, and developers. It flattens complex World of Warcraft / Project Epoch game relations into human-readable views, supports full-text search (FTS5), and outputs query results in **JSON**, **Markdown**, **CSV**, or formatted ASCII tables.

---

## 1. Quick CLI Querying & Search

The CLI provides two primary commands for prompt interaction: `query` and `search`.

### Output Formats (`--format`)
- `json`: Returns a clean JSON array of objects. Ideal for piping into LLM prompts or Python scripts.
- `markdown`: Returns a GitHub-flavored Markdown table. Ideal for generating reports.
- `table`: Standard ASCII table for terminal inspection (default).
- `csv`: Comma-separated values.

### Full-Text Search (FTS5)
Search across all quests, NPCs, items, and objects by natural language keywords:
```bash
# Search for Mankrik's quest chain or wife
uv run pfquest-db search --db epoch.db "Mankrik" --limit 5 --format markdown

# Search for custom Project Epoch content (e.g. Gilneas)
uv run pfquest-db search --db epoch.db "Gilneas" --type quest --format json
```

### Direct SQL Queries
```bash
# Query quest details with JSON output
uv run pfquest-db query --db epoch.db \
  "SELECT quest_id, title, starters, finishers, objectives, prerequisites FROM v_quest_details WHERE title = 'Consumed by Hatred'" \
  --format json
```

---

## 2. Pre-Built Prompt-Friendly Views

| View Name | Description | Key Columns |
|---|---|---|
| `v_quest_details` | Complete quest card with resolved starters, finishers, formatted objectives, prerequisites, next quests, and descriptions. | `quest_id`, `title`, `quest_level`, `min_level`, `starters`, `finishers`, `objectives`, `prerequisites`, `next_quest_title` |
| `v_quests` | Fast quest overview with quest-giver and turn-in names. | `id`, `title`, `min_level`, `quest_level`, `starter_names`, `finisher_names`, `objective_text` |
| `v_quest_objectives` | Individual objective lines with resolved unit/item/object names and counts. | `quest_id`, `quest_title`, `objective_type`, `target_name`, `amount`, `custom_text` |
| `v_npc_details` | NPC summary with level range, faction, zones found in, spawn count, and all quests started or ended. | `id`, `name`, `sub_name`, `min_level`, `max_level`, `faction`, `zones`, `quests_started`, `quests_ended` |
| `v_item_sources` | Where items drop (with mob names, drop rates, and zones), or if they start a quest. | `item_id`, `item_name`, `source_name`, `drop_chance`, `drop_zones`, `starts_quest_id` |
| `v_spawns` | Coordinate map for units and objects with zone names. | `entity_type`, `entity_id`, `name`, `zone_name`, `x`, `y` |
| `v_zone_summary` | Summary of active zones with unit, object, and spawn densities. | `zone_id`, `zone_name`, `unique_units`, `unit_spawns`, `unique_objects` |
| `v_drops` | Raw drop source table with resolved names. | `item_id`, `item_name`, `source_name`, `drop_chance` |
| `v_vendors` | Raw vendor stock table with NPC names. | `item_id`, `item_name`, `vendor_name`, `stock` |

---

## 3. SQL Prompt Recipes & Examples

### Recipe 1: Inspect a Full Quest Chain
Find a quest, its prerequisites, who gives it, who turns it in, and what comes next:
```sql
SELECT 
    quest_id,
    title,
    min_level,
    quest_level,
    starters,
    finishers,
    objectives,
    prerequisites,
    next_quest_title
FROM v_quest_details 
WHERE title LIKE '%Missing Diplomat%';
```

### Recipe 2: Explore Project Epoch Custom Quests
Project Epoch custom quests have IDs >= 20,000 or custom zone locations:
```sql
SELECT 
    quest_id,
    title,
    quest_level,
    starters,
    objectives
FROM v_quest_details
WHERE quest_id >= 20000
ORDER BY quest_level, quest_id
LIMIT 20;
```

### Recipe 3: Find Where to Farm a Specific Quest Item
Find which mobs drop an item and in what zone:
```sql
SELECT 
    item_id,
    item_name,
    source_name AS mob_name,
    drop_chance || '%' AS drop_rate,
    drop_zones
FROM v_item_sources
WHERE item_name = 'Kolkar Head'
ORDER BY drop_chance DESC;
```

### Recipe 4: NPC Lookup with Coordinates and Quests
Find where an NPC spawns and what quests they offer:
```sql
SELECT 
    n.id,
    n.name,
    n.faction,
    n.zones,
    n.quests_started,
    s.x,
    s.y
FROM v_npc_details n
LEFT JOIN v_spawns s ON s.entity_type = 'unit' AND s.entity_id = n.id
WHERE n.name = 'Marshal Dughan'
LIMIT 5;
```

### Recipe 5: Leveling Guide Query (Quests for Level 15-20)
Find all available quests for a specific level bracket:
```sql
SELECT 
    id,
    title,
    min_level,
    quest_level,
    starter_names
FROM v_quests
WHERE min_level <= 18 AND quest_level BETWEEN 15 AND 20
ORDER BY quest_level ASC;
```

### Recipe 6: Full-Text Search with Match Scoring
Rank results across dialogues and descriptions:
```sql
SELECT 
    entity_type,
    entity_id,
    name,
    substr(extra_text, 1, 100) AS snippet
FROM search_index
WHERE search_index MATCH 'Defias AND Docket'
ORDER BY rank;
```

---

## 4. Using with LLMs

To prompt an LLM using the database:
1. Run the query with `--format json` or `--format markdown`.
2. Feed the structured output directly into the context window.
Because column names are explicit and identifiers are resolved into names (e.g. `starters`, `objectives`, `drop_zones`), models can reason about quests, items, and NPC locations without needing multi-table joins.
