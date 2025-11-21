# CRY_CLI Modular Architecture

## Design Philosophy

**Primary Goal:** Run CRYSTAL23 calculations efficiently with minimal friction
**Secondary Goal:** Provide documentation support when students need it

The system is designed so that:
- Running a calculation requires ZERO interaction with documentation
- Documentation is available but never blocks the workflow
- Both tools share common UI components (gum/glow styling)

## Directory Structure

```
CRY_CLI/
├── bin/
│   ├── runcrystal              # Main execution script (thin wrapper)
│   └── cry-docs                # Documentation browser (standalone)
├── lib/
│   ├── cry-config.sh           # Configuration & environment
│   ├── cry-ui.sh               # Visual components (gum wrappers)
│   ├── cry-parallel.sh         # Parallelism logic & resource allocation
│   ├── cry-scratch.sh          # Scratch space management
│   ├── cry-stage.sh            # File staging utilities
│   └── cry-help.sh             # Help system & integration point
├── docs-src/                   # Documentation scraper & converter
│   ├── mirror.sh               # Phase 1: wget downloader
│   ├── convert.sh              # Phase 2: Pandoc transformer
│   └── build-index.sh          # Generate search index
└── share/
    └── tutorials/              # Converted markdown docs (generated)
```

## Component Responsibilities

### bin/runcrystal (Main Script)
- Argument parsing
- Coordinate lib/ modules
- Execute calculation
- Exit fast

**Key principle:** Keep it under 100 lines by delegating to libraries.

### bin/cry-docs (Documentation Browser)
- **Standalone tool** - works independently of runcrystal
- Searches and displays tutorial content
- Multiple modes:
  - `cry-docs search [keyword]` - Quick lookup
  - `cry-docs tree [path]` - Show hierarchy
  - `cry-docs browse` - Interactive TUI mode
  - `cry-docs --related basis` - Show related concepts

### lib/cry-ui.sh (Visual Components)
Shared UI functions used by BOTH runcrystal and cry-docs:
- `print_banner()`
- `print_card()`
- `print_status_line()`
- `ensure_gum_installed()`

**Benefit:** Consistent look and feel across all tools.

### lib/cry-help.sh (Help System)
The integration point where runcrystal help menu can launch cry-docs:
```bash
case "$CHOICE" in
    "5. External Knowledge Base"*)
        # Option 1: Direct integration (fast)
        cry-docs browse --path="$TOPIC"

        # Option 2: Hand off (clean separation)
        exec cry-docs browse
        ;;
esac
```

## Workflow Integration

### Fast Path (No Documentation)
```bash
$ runcrystal my_calc 14
[Calculation runs immediately - 0 documentation overhead]
```

### Learning Path (With Documentation)
```bash
# Option A: Separate terminal
Terminal 1: $ vim my_calc.d12
Terminal 2: $ cry-docs browse    # TUI stays open

# Option B: Quick lookup during editing
Terminal 1: $ vim my_calc.d12
Terminal 1: :!cry-docs search "basis sets 2D"
[reads, then back to vim]

# Option C: From runcrystal help
$ runcrystal --help
> Select "5. External Knowledge Base"
> [cry-docs launches in browse mode]
```

## Documentation System Design

### Phase 1: Minimal CLI (Week 1 Implementation)

**cry-docs commands:**
```bash
cry-docs tree                    # Show full hierarchy
cry-docs search "basis"          # Fuzzy search with context
cry-docs read 3D/basis/sto3g    # Direct path access
cry-docs browse [--path=...]    # Interactive tree navigator
```

**Integration with runcrystal:**
- Line 214-219 in current script calls `cry-docs browse`
- If `share/tutorials/` is empty, shows installation hint

### Phase 2: Enhanced Features (Month 2)

**Add to cry-docs:**
```bash
cry-docs --related "kpoints"     # Show related topics
cry-docs --bookmark              # Save current position
cry-docs --history               # Recently viewed
```

**Optional TUI mode:**
- Launch with `cry-docs browse --tui`
- Split pane: tree | document viewer
- Only loads when explicitly requested
- Does NOT interfere with quick search workflow

## Why This Architecture?

### Modularity Benefits
1. **Independent Testing:** Each lib/ module can be tested separately
2. **Reusability:** cry-ui.sh components shared across tools
3. **Maintainability:** Bug in documentation? Fix cry-docs, runcrystal untouched
4. **Performance:** Fast path (calculation) loads minimal code

### Documentation Strategy
1. **Non-blocking:** Documentation is invoked explicitly, never automatically
2. **Progressive:** Start with search (minimal), add TUI later if needed
3. **Integrated but Separate:** cry-docs works standalone OR from runcrystal menu

### Student-Friendly Workflow
```
Student workflow:
1. Launch calculation: runcrystal input 14
2. While running (hours), research next step: cry-docs browse
3. Edit next input file with knowledge from docs
4. Repeat

The documentation tool is AVAILABLE but OPTIONAL at every step.
```

## Implementation Priority

**Week 1:**
1. Refactor runcrystal → lib/ modules
2. Create cry-docs with search + tree commands
3. Implement docs-src/ scraper scripts

**Week 2:**
4. Add cry-docs browse (interactive tree navigator with gum)
5. Integrate with runcrystal help menu (line 214)

**Month 2:**
6. Add --related, --bookmark, --history features
7. Optional: Full TUI mode with split panes (if students request it)

## Key Decision: Documentation UX

Given that runcrystal is the PRIMARY tool and documentation is SUPPORT:

**Recommended approach:**
- **Primary mode:** `cry-docs search` - Fast, keyword-based lookup
- **Secondary mode:** `cry-docs browse` - Interactive tree navigator (uses gum filter)
- **Advanced mode:** `cry-docs browse --tui` - Full split-pane TUI (optional, future)

**Rationale:**
- Most lookups are quick ("What's the syntax for KPOINTS?")
- Tree browsing helps when learning new domain areas
- Full TUI is overkill unless students specifically request always-on reference panel

Start minimal, add features based on actual usage patterns.
