# CRY Logging Library

Structured logging infrastructure for CRY_CLI with log levels, timestamps, and color output.

## Features

- **4 Log Levels**: debug, info, warn, error (priority ordered)
- **ISO 8601 Timestamps**: UTC format (YYYY-MM-DDTHH:MM:SSZ)
- **Log Level Filtering**: Control verbosity via `CRY_LOG_LEVEL` environment variable
- **Color Output**: Automatic color detection for terminal output
- **Fatal Error Handling**: `cry_fatal()` returns exit codes without calling `exit()`
- **Bash 3.2+ Compatible**: Works on macOS and modern Linux systems

## Usage

### Basic Logging

```bash
# Source the library
source lib/cry-logging.sh

# Log at different levels
cry_debug "Verbose debugging information"
cry_info "Informational message"
cry_warn "Warning: something might be wrong"
cry_log error "Error: something went wrong"
```

### Log Level Filtering

```bash
# Set log level (default: info)
export CRY_LOG_LEVEL=warn

cry_debug "Not shown"     # Filtered
cry_info "Not shown"      # Filtered
cry_warn "Shown"          # Displayed
cry_log error "Shown"     # Displayed
```

### Fatal Errors

```bash
# cry_fatal logs at ERROR level and returns exit code
cry_fatal "Critical error" 42
exit_code=$?  # Returns 42, doesn't exit

# Default exit code is 1
cry_fatal "Error without code"
exit_code=$?  # Returns 1
```

### Error Handling Pattern

```bash
process_file() {
    local filename="$1"

    if [[ ! -f "$filename" ]]; then
        cry_fatal "File not found: $filename" 2
        return $?
    fi

    cry_info "Processing: $filename"
    # ... processing logic ...
    cry_info "Success!"
    return 0
}

# Usage
if ! process_file "data.txt"; then
    echo "Processing failed"
    exit 1
fi
```

## API Reference

### Core Functions

#### `cry_log LEVEL MESSAGE...`
Main logging function with level filtering and formatting.

- **Parameters:**
  - `LEVEL`: debug, info, warn, or error
  - `MESSAGE...`: Log message (multiple arguments concatenated)
- **Returns:** 0 on success, 1 on invalid level

#### `cry_fatal MESSAGE [EXIT_CODE]`
Log fatal error and return exit code without calling `exit()`.

- **Parameters:**
  - `MESSAGE`: Error message
  - `EXIT_CODE`: Exit code to return (default: 1)
- **Returns:** Specified exit code

#### `cry_warn MESSAGE...`
Convenience function for warning level logging.

#### `cry_info MESSAGE...`
Convenience function for info level logging.

#### `cry_debug MESSAGE...`
Convenience function for debug level logging.

### Environment Variables

#### `CRY_LOG_LEVEL`
Controls minimum log level to display.

- **Valid values:** debug, info, warn, error
- **Default:** info
- **Example:** `export CRY_LOG_LEVEL=debug`

## Log Levels

| Level | Priority | Color | Use Case |
|-------|----------|-------|----------|
| debug | 0 | Cyan | Verbose debugging information |
| info  | 1 | Green | Informational messages |
| warn  | 2 | Yellow | Warning messages |
| error | 3 | Red | Error messages |

Messages are only displayed if their priority is >= `CRY_LOG_LEVEL` priority.

## Output Format

```
[TIMESTAMP] [LEVEL] message
```

Example:
```
[2025-11-20T02:50:10Z] [INFO] Processing file: config.yaml
[2025-11-20T02:50:10Z] [WARN] Deprecated option used
[2025-11-20T02:50:11Z] [ERROR] File not found: data.txt
```

## Color Output

Colors are automatically enabled when:
- stderr is a terminal (`-t 2`)
- Terminal type is not "dumb"
- `tput` command is available

To disable colors:
```bash
export TERM=dumb
```

## Testing

Run the comprehensive test suite:

```bash
./tests/test-cry-logging.sh
```

Tests cover:
- All log levels (debug, info, warn, error)
- Invalid log level handling
- `cry_fatal()` return behavior
- Log level filtering
- ISO 8601 timestamp format
- Convenience functions
- Multi-argument messages

## Examples

See `examples/logging-example.sh` for complete usage examples.

## Implementation Details

- **Compatibility:** Bash 3.2+ (uses case statements instead of associative arrays)
- **Output Stream:** All logs written to stderr (fd 2)
- **Function Export:** Functions exported for use in subshells and sourced scripts
- **Timestamp:** UTC timezone (Z suffix)

## Integration with CRY_CLI

The logging library is used throughout CRY_CLI:

```bash
# In CLI scripts
source "$(dirname "$0")/lib/cry-logging.sh"

cry_info "Starting CRY operation"
if ! run_command; then
    cry_fatal "Operation failed" 1
    exit $?
fi
cry_info "Operation complete"
```
