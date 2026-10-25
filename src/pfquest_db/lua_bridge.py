"""Bridge to execute Lua code and stream/serialize Lua tables as JSON."""

import json
import subprocess
from pathlib import Path
from typing import Any, Generator, Tuple, Optional


LUA_JSON_SERIALIZER = r"""
local function escape_str(s)
    s = s:gsub("\\", "\\\\"):gsub("\"", "\\\""):gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t")
    s = s:gsub("[%z\1-\31]", function(c)
        return string.format("\\u%04x", string.byte(c))
    end)
    return "\"" .. s .. "\""
end

local function to_json(val)
    local t = type(val)
    if t == "number" then
        if val ~= val or val == math.huge or val == -math.huge then return "null" end
        return tostring(val)
    elseif t == "boolean" then
        return val and "true" or "false"
    elseif t == "string" then
        return escape_str(val)
    elseif t == "table" then
        local count = 0
        for _ in pairs(val) do count = count + 1 end
        local is_arr = (count > 0)
        if is_arr then
            for i = 1, count do
                if val[i] == nil then
                    is_arr = false
                    break
                end
            end
        end
        if is_arr then
            local buf = {}
            for i = 1, count do buf[i] = to_json(val[i]) end
            return "[" .. table.concat(buf, ",") .. "]"
        else
            local buf = {}
            for k, v in pairs(val) do
                table.insert(buf, escape_str(tostring(k)) .. ":" .. to_json(v))
            end
            return "{" .. table.concat(buf, ",") .. "}"
        end
    end
    return "null"
end
"""


def iter_lua_table_entries(
    lua_file_or_files: list[Path] | Path,
    table_accessor_expr: str,
    pre_code: str = "",
    lua_bin: str = "lua",
) -> Generator[Tuple[Any, Any], None, None]:
    """Execute Lua scripts and yield (key, value) pairs from the target table expression."""
    if isinstance(lua_file_or_files, (str, Path)):
        files = [Path(lua_file_or_files)]
    else:
        files = [Path(f) for f in lua_file_or_files]

    load_statements = "\n".join(
        f'dofile({json.dumps(str(f.resolve()))})' for f in files if f.exists()
    )

    lua_script = f"""
loadstring = loadstring or load
{LUA_JSON_SERIALIZER}

{pre_code}

{load_statements}

local target = {table_accessor_expr}
if type(target) == "table" then
    for k, v in pairs(target) do
        io.write("[" .. to_json(k) .. "," .. to_json(v) .. "]")
        io.write(string.char(10))
    end
end
"""

    proc = subprocess.Popen(
        [lua_bin, "-e", lua_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                k, v = json.loads(line)
                yield k, v
            except json.JSONDecodeError:
                continue

        _, stderr = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Lua execution failed ({proc.returncode}): {stderr}")
    finally:
        if proc.stdout and not proc.stdout.closed:
            proc.stdout.close()
        if proc.stderr and not proc.stderr.closed:
            proc.stderr.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def load_lua_table(
    lua_file_or_files: list[Path] | Path,
    table_accessor_expr: str,
    pre_code: str = "",
    lua_bin: str = "lua",
) -> dict:
    """Load an entire Lua table into a Python dictionary."""
    result = {}
    for k, v in iter_lua_table_entries(
        lua_file_or_files, table_accessor_expr, pre_code, lua_bin
    ):
        result[k] = v
    return result
