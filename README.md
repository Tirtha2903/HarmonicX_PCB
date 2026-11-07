# CircuitPilot AI

**An AI-assisted electronics design workbench** that interprets text and circuit images, produces a structured circuit specification, reviews it for engineering risks, builds a physical test procedure, and keeps an auditable design history.

## What this version does

- Accepts written requirements with up to four optional circuit photos or schematic images per analysis.
- Calls an OpenAI-compatible Chat Completions API and validates the response with strict Pydantic models.
- Flags unverified components, assumptions, and missing information.
- Runs a deterministic **Circuit Red-Team** review across power, protection, connectivity, compatibility, and requirement consistency.
- Generates a circuit-specific **Virtual Lab Assistant** test procedure with equipment, pre-power checks, measurement points, test sequence, troubleshooting, and safety notes.
- Stores design versions in **Circuit DNA**, an append-only SQLite history with change detection and validation invalidation.
- Exports `circuit_design.json`, `bom.csv`, and `connections.csv`, plus additive Red-Team artifacts.
- Can run KiCad ERC on a user-supplied `.kicad_sch` file when KiCad CLI is installed.

## Important engineering boundary

CircuitPilot AI is a design review and documentation assistant, **not** an electrical safety certification, simulator, ERC/DRC replacement, or manufacturing approval system.

- A Red-Team `PASS` means no implemented check produced a finding for the declared design snapshot. It does **not** mean the circuit is safe.
- Deterministic checks use only declared component data. Missing ratings, forward voltages, or currents are reported as incomplete data, never guessed.
- AI-suggested findings and lab steps remain labelled unverified and require independent engineering review.
- The Virtual Lab Assistant produces a procedure, not simulation results or measured values.
- KiCad ERC applies only to the uploaded KiCad schematic, not to the AI-generated JSON specification.
- This release does not generate a native KiCad schematic or PCB layout.

See `docs/ROADMAP_TO_PRODUCTION.md` for the controlled path to native schematic generation, PCB layout, DRC, simulation, and manufacturing release.

## Quick start

Python 3.11 is recommended.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

### Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

The defaults target OpenAI. Put an authorized OpenAI API key in `.env`; the app can start without a key, but AI analysis and optional AI additions need a valid key and project access. Never commit `.env`.

Run the app:

```bash
streamlit run app.py
```

Run the tests and linter:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
```

## Features

### Circuit analysis

Written requirements and up to four PNG, JPEG, or WEBP images (maximum `MAX_IMAGE_MB` each) are interpreted together into a validated `CircuitDesign` containing components, REF.PIN connections, board specifications, assumptions, missing information, and confidence metadata. Include the circuit's purpose, supply, known component values, constraints, and questions in the requirements field. Use clear, well-lit photos with readable labels and visible connections. Outputs are available as `circuit_design.json`, `bom.csv`, and `connections.csv`.

### Circuit Red-Team

Deterministic rules run first. They cover:

- Power and supply integrity
- Component voltage/current/power ratings
- LED current limiting and resistor ratings
- Protection and reverse-polarity risks
- Connectivity, ground continuity, duplicate nets, and undeclared pins
- Component compatibility and incomplete requirement data

Each finding includes a stable ID, rule code, severity, evidence, engineering reason, recommended action, verification status, data provenance, and affected pins. AI contextual suggestions are optional and can never be relabelled as deterministic or used to declare a circuit safe.

Artifacts written next to the existing exports:

- `red_team_review.json`
- `red_team_review.md`
- `analysis_manifest.json`

The manifest explicitly records `simulation_performed: false`, `erc_performed: false`, and `safety_certified: false`.

### Virtual Lab Assistant

The generator builds a deterministic procedure first:

- Required and optional test equipment
- Pre-power continuity, short, polarity, and insulation checks
- Measurement points with expected results and their basis
- Ordered power-up and functional test sequence
- Symptom-based troubleshooting
- Safety notes and a printable Markdown report

Expected values are labelled `calculated`, `design_target`, `requires_verification`, or `unknown`. Calculated values are produced only when the necessary declared inputs exist. AI additions are merged as optional, labelled suggestions and cannot overwrite deterministic values.

### Circuit DNA

Each saved design receives a stable ID such as `CP-NE555-0001` and an append-only version (`1.0`, `1.1`, ...). Every version stores the full design snapshot, design fingerprint, structural-check snapshot, Red-Team snapshot, and a change report against the previous version.

Change detection covers:

- Components added, removed, or modified
- Connection/net pin changes
- Supply voltage, frequency, project metadata, assumptions, and missing information
- Board specification changes
- Design fingerprint changes
- Red-Team findings added or resolved

A design-content change marks validation as invalid and lists the checks that must be re-run. A confidence-only re-analysis does not create a false design change. Previous versions and reviews are never overwritten. Only engineering data is stored; provider keys and other secrets are not written to the database.

## Configuration

| Variable | Required | Meaning | Default |
|---|---:|---|---|
| `AI_BASE_URL` | No | OpenAI API base URL | `https://api.openai.com/v1` |
| `OPENAI_API_KEY` | For AI | Secret OpenAI API key (`AI_API_KEY` is accepted as a legacy alias) | (None) |
| `AI_MODEL` | No | Exact model identifier available to your API project | `gpt-4o-mini` |
| `KICAD_CLI_PATH` | No | Absolute path to `kicad-cli`, if not on PATH | (Auto-detected) |
| `MAX_IMAGE_MB` | No | Maximum accepted image size | `8` |
| `MAX_PROMPT_CHARS` | No | Maximum prompt length | `12000` |
| `OUTPUT_DIR` | No | Artifact output directory | `projects` |
| `LOG_LEVEL` | No | Python logging level | `INFO` |
| `DNA_DB_PATH` | No | Circuit DNA SQLite path; relative paths use the project root | `circuitpilot_dna.db` |
| `ENABLE_AI_RED_TEAM` | No | Allow optional AI Red-Team suggestions; deterministic rules still run when disabled | `true` |
| `ENABLE_AI_VIRTUAL_LAB` | No | Allow optional AI lab additions; deterministic procedures still run when disabled | `true` |

Boolean values accept `true/false`, `1/0`, `yes/no`, and `on/off`.

### Setting up OpenAI (default)

1. Create an API key in the [OpenAI platform](https://platform.openai.com/api-keys) or obtain an authorized key from your account owner.
2. Keep the real key in your ignored local `.env` as `OPENAI_API_KEY`. Never put it in `.env.example` or commit it. The older `AI_API_KEY` variable is still accepted.
3. Use `AI_BASE_URL=https://api.openai.com/v1` and `AI_MODEL=gpt-4o-mini`, or select a model enabled for that API project that supports Chat Completions. This client uses Chat Completions, not the Responses API.
4. OpenAI API billing is separate from a ChatGPT subscription. Confirm the key owner's permission and usage budget before making requests.

## KiCad ERC

Install KiCad 10 and verify:

```bash
kicad-cli version
kicad-cli sch erc --help
```

If the executable is not on PATH, set `KICAD_CLI_PATH` in `.env`.

Upload a real `.kicad_sch` file in the app and run ERC. The resulting report belongs to that uploaded schematic; it is not a validation report for the AI-generated JSON specification. A clean ERC is not proof that a design is functionally or physically correct.

## Project structure

```text
app.py                     Streamlit entry point
config.py                  Environment configuration
ui/                        Streamlit tabs and shared UI helpers
agents/                    Design-agent prompt and orchestration
schemas/                   Pydantic circuit model and design fingerprint
electronics/
  checks.py                Structural checks
  values.py                Engineering value parsing/formatting
  netinfo.py               Net indexing and series/parallel topology helpers
  calculations.py          Deterministic calculations
  exports.py               Artifact export contract
  kicad.py                 KiCad CLI ERC integration
  red_team/                Rules, engine, models, severity and Markdown report
services/
  llm_client.py            OpenAI-compatible client
  dna/                     Identity, diff, models and append-only SQLite storage
  virtual_lab/             Generator, safety rules, models and printable report
tests/                     Deterministic unit tests (no live LLM calls)
docs/                      Production roadmap and deployment guidance
projects/                  Generated artifacts (git-ignored)
```

## Security

- `.env` is ignored by Git.
- Never put secrets in source code, prompts, screenshots, or chat.
- Uploaded images are size-limited and decoded before use.
- Output filenames are generated by the application.
- Circuit DNA stores engineering snapshots only. Back up the SQLite file to preserve history.
- Do not upload confidential or proprietary circuit designs to a third-party AI provider without authorization.
- For public deployment, configure provider secrets in the hosting platform, not in the repository.
- The current Streamlit config sets `server.enableCORS=false`; Streamlit warns that this permits cross-origin WebSocket connections. Review the setting and restrict trusted origins/hosts before public deployment.
- Add authentication, quotas, and abuse controls before exposing the service to unrestricted public traffic.

## Known limitations

- No native KiCad schematic or PCB generation.
- No SPICE simulation, thermal analysis, EMI analysis, or DRC.
- Red-Team rules are conservative heuristics over declared data, not a substitute for datasheet review.
- Pin functions are not inferred from part numbers; REF.PIN topology must come from the source or the user.
- Component ratings and LED forward voltages must be declared to enable the corresponding calculations.
- AI output can be wrong; every AI-suggested item requires independent verification.
- The SQLite DNA database is local to the deployment and is not a multi-user collaborative store.
- KiCad ERC requires KiCad CLI to be installed and available to the process.
