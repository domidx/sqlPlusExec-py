# sqlPlusExec

A Windows command-line tool for executing SQL queries and scripts against an Oracle database via `sqlplus`, using a client/server architecture over a Windows Named Pipe.

## How It Works

The tool runs in two modes:

**Server mode** starts a persistent `sqlplus` process in the background and listens for incoming commands on a named pipe (`\\.\pipe\sqlPlusExec`). It handles reconnections automatically when a different connection string is provided.

**Client mode** connects to the running server and sends a SQL command or script to execute. If no server is running, the client starts one automatically before retrying.

This design means `sqlplus` is started only once and reused across multiple client calls, avoiding the overhead of launching a new session every time.

## Requirements

- Windows (Named Pipes are Windows-only)
- Python 3.x
- Oracle `sqlplus` installed and available in `PATH`
- Python packages:
  - `pywin32`
  - `pandas`
  - `tabulate`

Install dependencies with:
```
pip install pywin32 pandas tabulate
```

## Usage

### Run a query (client mode)
```
python sqlPlusExec.py -conn username/password@tnsname -sqlcmd "select * from my_table"
```

### Run a multi-line script
```
python sqlPlusExec.py -conn username/password@tnsname -sqlcmd "select col1" ", col2" "from my_table" "where rownum < 10"
```

### Start the server manually
```
python sqlPlusExec.py -start
```

### Stop the server
```
python sqlPlusExec.py -stop
```

## Arguments

| Argument | Description |
|---|---|
| `-conn` | Oracle connection string in the format `username/password@tnsname` |
| `-sqlcmd` | One or more lines of SQL to execute |
| `-outputformat` | Output format: `csv` (default), `align`, `simple`, `psql`, `presto`, `fancy_grid` |
| `-start` | Start the server process |
| `-stop` | Stop the server process |
| `-debug` | Enable debug logging (client mode) |
| `-nodebug` | Disable debug logging (server mode) |

## Configuration

An optional `sqlPlusExec.config` JSON file can be placed in the same directory as the script to define additional `sqlplus` login commands that run after every connection. Example:

```json
{
  "sqlplus_login": [
    "alter session set nls_date_format = 'YYYY-MM-DD'"
  ]
}
```

The following commands are always applied by default regardless of config:
- `set linesize 512`
- `col error for a220`
- `set timing off`
- `set serveroutput on`

## SELECT Output Formats

When running a SELECT (or WITH) query, the tool automatically detects it and retrieves results in CSV format internally. You can then control how those results are displayed using the `-outputformat` argument.

### `csv` (default)
Returns raw CSV output as produced by `sqlplus`. Useful for piping into other tools or saving to a file.
```
"ID","NAME","STATUS"
"1","Alice","Active"
"2","Bob","Inactive"
```

### `align`
Displays results as a plain aligned table using pandas' default DataFrame formatting. Clean and simple, good for quick inspection.
```
   ID   NAME    STATUS
0   1  Alice    Active
1   2    Bob  Inactive
```

### `simple`
A minimalist plain-text table with no border characters, just spacing and a header separator.
```
  rn    ID  NAME      STATUS
----  ----  --------  --------
   1     1  Alice     Active
   2     2  Bob       Inactive
```

### `psql`
A table styled like the PostgreSQL `psql` client output, with `|` column separators and `+---+` borders.
```
+----+----+--------+----------+
| rn | ID | NAME   | STATUS   |
|----+----+--------+----------|
|  1 |  1 | Alice  | Active   |
|  2 |  2 | Bob    | Inactive |
+----+----+--------+----------+
```

### `presto`
Similar to `psql` but with a slightly different border style, modelled after the Presto query engine CLI.
```
 rn | ID | NAME   | STATUS
----+----+--------+----------
  1 |  1 | Alice  | Active
  2 |  2 | Bob    | Inactive
```

### `fancy_grid`
A fully bordered table with grid lines between every row. The most visually detailed option.
```
+----+----+--------+----------+
| rn | ID | NAME   | STATUS   |
+====+====+========+==========+
|  1 |  1 | Alice  | Active   |
+----+----+--------+----------+
|  2 |  2 | Bob    | Inactive |
+----+----+--------+----------+
```

> **Note:** All tabular formats (`simple`, `psql`, `presto`, `fancy_grid`) include a row number column (`rn`) starting at 1. The `align` format uses 0-based index from pandas. For non-SELECT statements (INSERT, UPDATE, DDL, etc.), output is always printed as-is regardless of the `-outputformat` setting.

## Notes

- The server runs in debug mode by default (logs to console). Use `-nodebug` to suppress output.
- The client runs silently by default. Use `-debug` to enable logging.
- The server must be running on the same machine as the client (named pipes are local only).
