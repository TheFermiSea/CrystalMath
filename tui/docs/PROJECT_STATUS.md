# CRYSTAL-TUI Project Status

## ✅ Completed (MVP Foundation)

### Project Structure
- ✅ Complete directory layout
- ✅ Python package configuration (pyproject.toml)
- ✅ Development dependencies setup
- ✅ Entry point script configuration

### Core Components
- ✅ SQLite database schema and ORM
- ✅ Job data model with full lifecycle
- ✅ Database CRUD operations
- ✅ JSON storage for structured results

### TUI Application
- ✅ Main Textual app with async support
- ✅ Three-panel layout (Jobs, Log, Results)
- ✅ DataTable for job list with cursor navigation
- ✅ Real-time log streaming
- ✅ Tabbed content panes
- ✅ Message-based architecture
- ✅ Worker system for async job execution
- ✅ Keyboard shortcuts (n, r, s, q)

### Documentation
- ✅ README with feature roadmap
- ✅ Installation guide
- ✅ Architecture documentation
- ✅ Code documentation

## 🔨 In Progress (Ready for Implementation)

### Job Runner
- Mock runner implemented in app.py
- Real CRYSTAL runner needs:
  - Integration with existing CrystalRun script
  - CRYSTALpytools integration for output parsing
  - Error detection and handling
  - File staging from database input

### Input Management
- New job action (keyboard shortcut exists)
- Needs modal screen for input entry
- Template system (Phase 2)

## 📋 Next Steps (Priority Order)

### Immediate (Complete MVP)

1. **Implement Real Job Runner** (`src/runners/local.py`)
   ```python
   - Use asyncio.create_subprocess_exec
   - Run crystalOMP from CRY23_EXEDIR
   - Stream stdout/stderr
   - Handle process lifecycle
   ```

2. **Integrate CRYSTALpytools** (`src/core/crystal_io.py`)
   ```python
   - Parse output files
   - Extract final energy
   - Detect errors/warnings
   - Store structured results
   ```

3. **New Job Modal** (`src/tui/screens/new_job.py`)
   ```python
   - TextArea for input content
   - Input field for job name
   - Validation before creation
   - Write input.d12 to work directory
   ```

4. **Connect to Existing Environment**
   - Source cry23.bashrc for env vars
   - Use CRY23_EXEDIR for executable path
   - Respect CRY23_SCRDIR for calculations/

### Short Term (Phase 1 Complete)

5. **Enhanced UI**
   - Syntax highlighting in input preview
   - Better error display
   - Progress indicators during calculation
   - Result summary cards

6. **Testing**
   - Unit tests for database
   - Integration tests for job runner
   - TUI snapshot tests

7. **Configuration**
   - Optional config.toml
   - Override executable paths
   - Customize thread counts

### Medium Term (Phase 2)

8. **Remote Execution**
   - SSH runner implementation
   - SLURM integration
   - File transfer optimization
   - Remote monitoring

9. **Visualization**
   - Band structure plots
   - DOS visualization
   - Geometry viewer

10. **Batch Management**
    - Multi-select in job list
    - Batch submit
    - Queue management

### Long Term (Phase 3)

11. **Workflows**
    - Job chaining (GEO_OPT → BANDS)
    - Conditional execution
    - Parameter sweeps
    - AiiDA-style provenance

12. **Advanced Features**
    - Template library
    - Job comparisons
    - Export to other formats
    - Integration with analysis tools

## 📊 Technical Decisions Made

### Why Python?
- Entire CRYSTAL ecosystem (CRYSTALpytools, Pymatgen, ASE) is Python
- Avoid rewriting existing tools
- Rich library ecosystem

### Why Textual?
- Modern, actively maintained
- Excellent async support (critical for job monitoring)
- CSS-based styling
- Rich widget library
- Built on asyncio (perfect for subprocess management)

### Why SQLite?
- Serverless, zero-config
- File-based (portable projects)
- Full SQL support
- JSON storage via TEXT columns
- Perfect for desktop applications

### Why Not AiiDA Directly?
- AiiDA requires PostgreSQL + daemon (heavyweight)
- Designed for clusters, not local workstations
- CRYSTAL-TUI captures the spirit (provenance, automation)
- Could integrate with AiiDA in future (export workflows)

## 🎯 Success Criteria

### MVP Success (Phase 1)
- [ ] User can create a new job with custom input
- [ ] Job runs locally with CRYSTAL executable
- [ ] Output streams to log in real-time
- [ ] Final energy extracted and displayed
- [ ] Job can be stopped mid-execution
- [ ] Job history persists across sessions

### Full Release (Phase 2-3)
- [ ] Remote cluster submission works
- [ ] Batch jobs can be submitted
- [ ] Basic visualization available
- [ ] Workflows can be chained
- [ ] Template library exists
- [ ] Used by at least 3 researchers

## 📝 Notes from Research (Gemini)

### CRYSTALpytools Insights
- `Crystal_input` for programmatic input generation
- `Crystal_output` for parsing with error detection
- Integration with ASE/Pymatgen for structures
- Matplotlib-based plotting (static, but works)

### AiiDA Pattern Learnings
- Provenance via DAG of calculations
- Remote execution abstraction
- Automatic file staging
- Database-backed history
- WorkChain for multi-step workflows

### Similar Tools Inspiration
- `verdi` CLI for reference
- `lazygit`/`k9s` for TUI design patterns
- ASE GUI for structure workflows

## 🚀 Quick Start for Contributors

```bash
cd /Users/briansquires/CRYSTAL23/bin/crystal-tui

# Setup
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run
crystal-tui

# Test (when implemented)
pytest

# Format
black src/ tests/
ruff check src/ tests/
```

## 📞 Integration Points

### With Existing CrystalRun
- Reuse cry23.bashrc for environment
- Share executable discovery logic
- Could call CrystalRun as subprocess
- Or integrate its logic into LocalRunner

### With CRYSTALpytools
- Use for all file I/O
- Leverage existing parsers
- Benefit from community updates
- Contribute improvements back

### Future: With aiida-crystal-dft
- Export workflows to AiiDA format
- Import AiiDA calculations for visualization
- Bridge between local and cluster workflows
