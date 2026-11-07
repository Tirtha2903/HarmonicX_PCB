# Roadmap to a production-grade AI PCB engineering system

## Current capability boundary

The current codebase is an AI-assisted circuit-analysis workbench. It produces
structured JSON, BOM CSV and connection CSV; performs structural checks and
deterministic Red-Team review; generates deterministic Virtual Lab procedures;
and stores append-only Circuit DNA versions, fingerprints and change reports
in SQLite. Optional AI additions to Red-Team and Virtual Lab output are
controlled by `ENABLE_AI_RED_TEAM` and `ENABLE_AI_VIRTUAL_LAB`. It can run
KiCad ERC on a supplied native schematic.

It does not synthesize native KiCad schematic/PCB files from the AI result.
It does not run SPICE simulation, PCB DRC on generated designs, thermal or
signal-integrity analysis, and it does not establish electrical correctness or
manufacturing readiness. Red-Team results are heuristics over declared data;
Virtual Lab output is a proposed test procedure, not measured evidence. Circuit
DNA is a local SQLite history configured with `DNA_DB_PATH`, not a collaborative
or multi-user store.

## Engineering work required

### 1. Evidence-backed component catalog
- Import trusted manufacturer/library data.
- Store manufacturer part number, datasheet revision, package and pin map.
- Record source, retrieval date and verification status.
- Reject unsupported or ambiguous parts.

### 2. Deterministic circuit intermediate representation
- Define typed components and electrical pins.
- Define nets, pin electrical types and power domains.
- Validate reference designators, pin existence and net constraints.
- Separate model-proposed values from engineer-approved values.

### 3. Native schematic generation
- Select a tested KiCad generation method.
- Generate native `.kicad_sch` files from the validated intermediate representation.
- Open generated files in KiCad CLI and GUI.
- Run ERC on generated files, not on unrelated reference files.
- Compare exported netlists against intended connections.

### 4. PCB generation
- Validate footprint existence and pad mapping.
- Define board outline, layers, clearances, track widths and copper rules.
- Place components with constraints.
- Route only with a controlled routing engine or explicit user interaction.
- Run KiCad PCB DRC on generated `.kicad_pcb`.
- Produce fabrication files only after human review.

### 5. Electrical verification
- Add SPICE models and simulation for supported circuit classes.
- Add voltage/current/power and derating rules.
- Add thermal and protection checks where applicable.
- Treat each supported circuit family as a tested engineering workflow.

### 6. Agent autonomy and audit
- Use typed tool calls with bounded permissions.
- Record every tool invocation, input artifact, output artifact and validation result.
- Add retry limits and loop detection.
- Require user approval for high-impact design changes.
- Never let an LLM mark its own output as electrically verified.

### 7. Production operations
- Authentication, authorization and project isolation.
- Rate limits, usage budgets and abuse protection.
- Secret manager, TLS, backups and monitoring.
- Dependency scanning and patch cadence.
- Versioned schemas, artifacts and migrations.
- Incident response, rollback and support procedures.

## Suggested acceptance criteria

A circuit family is considered supported only when:
1. Its component catalog and pin maps are curated.
2. Its intermediate representation is deterministic.
3. A native KiCad schematic is generated.
4. The generated schematic passes the expected ERC rules or has documented waivers.
5. The exported netlist matches the intended connectivity.
6. Simulation or bench testing is completed where applicable.
7. A human reviewer signs off the design and known limitations.
