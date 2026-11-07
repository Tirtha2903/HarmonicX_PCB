# CircuitPilot AI — Complete procedure after unzipping

This is the team's operating guide, from placing the extracted project in the
GitHub repository and opening it in Antigravity through testing, deployment,
release hardening and a production-readiness review.

The instructions assume a four-person team, mixed Windows/Linux machines,
Python 3.11, KiCad 10 and an OpenAI-compatible model endpoint.

---

# Part 0 — Understand what is in this release

This codebase is a functional **AI-assisted circuit analysis and review MVP**.

It can:
1. Accept text requirements and an optional circuit image.
2. Call a configured OpenAI-compatible Chat Completions endpoint.
3. Parse the response into a strict Pydantic circuit schema.
4. Flag missing information, assumptions and low-confidence selections.
5. Run deterministic schema/reference checks.
6. Export a JSON design specification, BOM CSV and connection CSV.
7. Run KiCad ERC on a user-uploaded native `.kicad_sch` file.

It does not yet create a native KiCad schematic or PCB from the AI-generated
specification. It does not run SPICE simulation, PCB DRC on generated designs,
thermal analysis, signal-integrity analysis or manufacturing sign-off.

Do not claim those capabilities in the event demo until they are implemented
and tested on actual artifacts.

---

# Part 1 — Unzip and place the project

1. Download and extract `CircuitPilot_Production_Starter.zip`.
2. Rename the extracted folder to `CircuitPilot` if desired.
3. Put it in a normal development location, not inside a temporary Downloads
   subfolder. Example:
   - Windows: `C:\\Users\\<you>\\Documents\\CircuitPilot`
   - Linux: `~/projects/CircuitPilot`
4. Confirm that `app.py`, `requirements.txt`, `agents/`, `schemas/`,
   `electronics/`, `services/`, `tests/` and `docs/` are at the project root.
5. Do not unzip the project inside another folder with the same name if that
   creates `CircuitPilot/CircuitPilot/app.py`.

---

# Part 2 — Push the new codebase to GitHub

Your existing repository is:

`https://github.com/Tirtha2903/HarmonicX_PCB`

## Option A — Replace the repository contents with this new baseline

Use this option only if the team has agreed that the existing repository
contents can be replaced. Make a backup or create a Git tag first.

1. Open a terminal in the extracted `CircuitPilot` folder.
2. Initialize Git if the extracted folder is not already a Git repository:

```bash
git init
git branch -M main
git remote add origin https://github.com/Tirtha2903/HarmonicX_PCB.git
```

If `origin` already exists, inspect it:

```bash
git remote -v
```

If it points elsewhere, update it:

```bash
git remote set-url origin https://github.com/Tirtha2903/HarmonicX_PCB.git
```

3. Check that `.env` is not present. Only `.env.example` belongs in Git.
4. Stage and commit:

```bash
git add .
git status
git commit -m "feat: establish CircuitPilot AI engineering workbench"
```

5. Push:

```bash
git push -u origin main
```

If GitHub rejects the push because the remote already has commits, do not
force-push blindly. First inspect and reconcile:

```bash
git fetch origin
git log --oneline --graph --decorate --all -20
```

Choose one:
- Preserve remote history and merge/rebase the new baseline into it.
- Create a new branch and open a pull request.
- Back up the old repository and deliberately replace it after team approval.

Avoid `git push --force` unless the repository owner explicitly approves the
history replacement and a recoverable backup exists.

## Option B — Add the new codebase on a feature branch

This is safer when the current repository already contains useful work.

1. Clone the repository:

```bash
git clone https://github.com/Tirtha2903/HarmonicX_PCB.git
cd HarmonicX_PCB
git switch -c feature/new-circuitpilot-foundation
```

2. Copy the extracted starter files into this clone. Review collisions before
   overwriting any existing file.
3. Run `git status`, inspect the diff, then:

```bash
git add .
git commit -m "feat: add consolidated CircuitPilot foundation"
git push -u origin feature/new-circuitpilot-foundation
```

4. Open GitHub in a browser, create a pull request into `main`, review the
   changed files and merge only after tests pass.

**Recommendation:** Use Option B for the team project. It preserves the
existing implementation and lets you compare before merging.

---

# Part 3 — Open the project in Antigravity

1. Install and open Antigravity.
2. Choose **Open Folder**.
3. Select the repository root folder (the folder containing `app.py`).
4. Wait for indexing to finish.
5. Open the integrated terminal.
6. Confirm the terminal's current directory is the project root:

```bash
pwd
```

On PowerShell:

```powershell
Get-Location
```

7. Ask Antigravity to inspect before changing anything. Use this prompt:

> Inspect this repository as a senior Python, AI-agent and electronics-software
> engineer. First map the architecture, identify entry points, schemas,
> provider integration, artifact generation and validation boundaries. Do not
> edit files yet. Report missing functionality, security risks, dependency
> issues and tests that should be run. Do not claim KiCad generation or
> electrical validation exists unless you can point to working code and tests.

8. Review the report. Do not approve a broad rewrite just because an agent
   suggests it. Make small, reviewable changes.

## Antigravity implementation prompt

After inspection, give it this bounded task:

> Implement only the next agreed issue. Preserve the existing Pydantic schema
> contract unless the issue explicitly requires a versioned schema change.
> Add or update automated tests. Do not fabricate component pinouts,
> datasheets, ERC/DRC results or successful file generation. Do not put
> credentials in source files. Show the diff and explain how to test it.
> Do not modify unrelated files.

Use one Git branch per task. Review the diff before accepting edits.

---

# Part 4 — Set up Python on Windows and Linux

Use Python 3.11 on all team machines.

## Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

If activation is blocked for the current terminal session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Verify:

```bash
python --version
python -m pip --version
```

All team members should report Python 3.11.x in Discord.

---

# Part 5 — Configure the AI provider

1. Copy `.env.example` to `.env`.

Windows:

```powershell
Copy-Item .env.example .env
```

Linux:

```bash
cp .env.example .env
```

2. Obtain the provider's documented OpenAI-compatible **Chat Completions**
   base URL and exact model identifier.
3. Edit `.env`:

```env
AI_BASE_URL=https://provider-documented-host/v1
AI_API_KEY=your_secret_key
AI_MODEL=exact_model_identifier

KICAD_CLI_PATH=
MAX_IMAGE_MB=8
MAX_PROMPT_CHARS=12000
OUTPUT_DIR=projects
LOG_LEVEL=INFO
```

4. Do not paste the API key into Antigravity chat, GitHub issues, commits,
   screenshots, source files or Discord.
5. Do not assume that every OpenAI-compatible provider supports image input.
   Confirm that the chosen model supports image content in Chat Completions.
6. Test with a simple text-only prompt first, then test image input.

If the provider uses a different endpoint shape, authentication convention,
vision format or response structure, update `services/llm_client.py` in a
dedicated branch and add tests.

---

# Part 6 — Run the application locally

From the activated virtual environment:

```bash
streamlit run app.py
```

Open the local URL printed in the terminal (normally
`http://localhost:8501`).

## First smoke test

Prompt:

> Analyze a 5 V LED flasher concept using an NE555 timer. Target an approximate
> 2 Hz blink rate. Identify components and connections only when the pin
> mapping is supported. List missing information and assumptions.

Check:
- The model responds.
- The response passes the Pydantic schema.
- Components and connections render.
- Missing information is visible.
- `circuit_design.json`, `bom.csv` and `connections.csv` download.
- Output files are created under `projects/`.

Do not accept a plausible-looking answer as proof that the circuit is correct.
Compare the output with a known reference circuit and component datasheets.

## Image smoke test

1. Upload a clear circuit schematic image in PNG, JPEG or WEBP.
2. Ask the model to identify visible components and explicit connections.
3. Check that uncertain labels and ambiguous junctions are reported as missing
   information rather than guessed.
4. Test a blurry or partially cropped image. The agent should lower confidence
   and request clarification.

---

# Part 7 — KiCad 10 setup and validation

Install KiCad 10 on the EDA developer's machine. Verify the CLI:

```bash
kicad-cli version
kicad-cli sch erc --help
kicad-cli sch export netlist --help
```

Windows: if `kicad-cli` is not on PATH, set its full executable path in
`KICAD_CLI_PATH`. Example path (verify your actual installation directory):

`C:\\Program Files\\KiCad\\10.0\\bin\\kicad-cli.exe`

Linux: use the path returned by:

```bash
which kicad-cli
```

Open a known-good reference schematic in KiCad and save it as a `.kicad_sch`.
In CircuitPilot, open the **KiCad ERC** tab, upload that file and run ERC.

Record:
- KiCad version.
- Exact input schematic.
- CLI return code.
- ERC JSON report.
- Violations and warnings.
- Any exclusions or waivers.

The current app checks a user-supplied schematic. It does not check the
AI-generated JSON as if that JSON were a KiCad schematic.

---

# Part 8 — Four-person team execution

## Member 1 — Technical lead and integration

Own:
- Shared schema and versioning.
- Orchestration.
- GitHub branch policy and pull-request review.
- Integration tests.
- Release checklist and demo narrative.

Deliverables:
- Architecture diagram.
- Versioned schema contract.
- Integrated application.
- Test evidence and release notes.

## Member 2 — AI and multimodal engineering

Own:
- Provider/model compatibility.
- Prompt and response quality.
- Text and image analysis.
- Missing-information behavior.
- Model failure and malformed-response handling.

Deliverables:
- Provider smoke-test results.
- Prompt evaluation set.
- Text and image test cases.
- Model limitations and cost/latency notes.

## Member 3 — Electronics and EDA

Own:
- Reference circuit and component datasheets.
- Pin mapping and connection evidence.
- SKiDL evaluation.
- Native KiCad schematic generation investigation.
- KiCad ERC and PCB DRC pipeline.

Deliverables:
- Verified reference schematic.
- Component source/evidence table.
- Netlist and ERC test evidence.
- Native design generation plan and implementation.

## Member 4 — Frontend, usability and testing

Own:
- Streamlit user experience.
- Error, warning and uncertainty presentation.
- Artifact download experience.
- Usability and regression tests.
- Demo scenarios and backup recordings/screenshots.

Deliverables:
- Working interface.
- Valid and invalid workflow tests.
- Demo script.
- Known-limitations panel.

## Team integration rule

- Commit small changes.
- Pull from `main` before starting a new task.
- Use feature branches.
- Do not change the schema without informing M1 and all consumers.
- Merge only after tests pass.
- Never commit `.env`, API keys, generated private circuit files or large
  binary outputs.

---

# Part 9 — Test and quality gate

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

Run:

```bash
python -m pytest -q
ruff check .
python -m compileall agents electronics schemas services
```

Required manual tests:

1. Empty prompt and no image.
2. Text-only circuit request.
3. Image-only circuit request.
4. Text plus image.
5. Unsupported image format.
6. Oversized image.
7. Invalid API key.
8. Invalid base URL.
9. Unsupported model.
10. Model returns malformed JSON.
11. Duplicate component reference.
12. Connection references an unknown component.
13. Missing supply voltage/current.
14. Ambiguous pin or wire junction.
15. KiCad CLI missing.
16. ERC passes on a known-good schematic.
17. ERC reports violations on a deliberately faulty schematic.

Acceptance rule:
- Failures must be visible and explainable.
- No failed validation may be displayed as success.
- A model's confidence score must not be described as electrical correctness.
- All downloaded files must match the displayed design.

---

# Part 10 — Add CI on GitHub

Create `.github/workflows/tests.yml` with:

```yaml
name: Python tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt

      - name: Run tests
        run: python -m pytest -q

      - name: Lint
        run: ruff check .
```

Commit and push this workflow. Confirm that the Actions check passes on a pull
request before merging.

Do not put the AI API key in CI unless a specific integration test needs it.
Unit tests should run without paid API access.

---

# Part 11 — Deploy a public demo

## Recommended first deployment: Streamlit Community Cloud

1. Push the stable application to GitHub.
2. Sign in to Streamlit Community Cloud.
3. Create a new app.
4. Select the GitHub repository:
   `Tirtha2903/HarmonicX_PCB`
5. Select the production branch (normally `main`).
6. Set the entrypoint to `app.py`.
7. Configure Python 3.11 if the platform offers a Python version setting.
8. Add secrets in the platform's app settings, not in GitHub:

```toml
AI_BASE_URL = "https://provider-documented-host/v1"
AI_API_KEY = "your-secret"
AI_MODEL = "exact-model-id"
MAX_IMAGE_MB = "8"
MAX_PROMPT_CHARS = "12000"
OUTPUT_DIR = "projects"
LOG_LEVEL = "INFO"
```

9. Deploy and inspect application logs.
10. Test the live URL from a clean browser session.

### Important deployment limitation

Streamlit Community Cloud will not automatically have your local KiCad 10
installation. The local KiCad CLI ERC feature may therefore be unavailable
in the hosted demo.

For a hosted version that needs KiCad CLI, use a container or server where
KiCad is installed and maintained. Do not assume that the Community Cloud
runtime can execute local EDA software.

For a public demo, clearly disable or label unavailable KiCad functionality
rather than showing a misleading success state.

---

# Part 12 — Docker deployment option

Build locally:

```bash
docker build -t circuitpilot:latest .
```

Run:

```bash
docker run --rm -p 8501:8501 --env-file .env circuitpilot:latest
```

Open `http://localhost:8501`.

The included Dockerfile runs as a non-root user. It does not install KiCad.
For a KiCad-enabled deployment, create a separately tested image that installs
the exact KiCad CLI version and required symbol libraries, and verify its
license and distribution obligations.

For production, use a managed secret store, persistent storage for artifacts,
TLS termination, monitoring and an explicit update process.

---

# Part 13 — Production hardening checklist

A public prototype is not automatically production-ready. Complete these
before offering the service to external users.

## Identity and access
- Add authentication.
- Add per-user authorization and project isolation.
- Restrict access to private design artifacts.
- Define retention and deletion behavior.

## API and cost controls
- Rate-limit requests per user/IP.
- Set provider request timeouts and bounded retries.
- Enforce prompt and upload size limits.
- Track token usage, latency and provider errors.
- Add spending alerts and a hard budget ceiling.
- Handle provider outages and model changes.

## Application security
- Keep secrets in a secret manager.
- Scan and validate uploaded files.
- Avoid executing user-supplied files or arbitrary shell commands.
- Restrict KiCad CLI inputs to controlled temporary directories.
- Keep dependencies updated and scan them for vulnerabilities.
- Add security headers and TLS at the hosting layer.
- Review logging to avoid storing API keys or confidential circuit content.

## Engineering correctness
- Maintain a curated component library with source documents.
- Validate footprints and exact manufacturer part numbers.
- Add explicit pin maps for supported parts.
- Use deterministic electrical constraints.
- Add SPICE simulation where appropriate.
- Generate native KiCad schematics from tested templates or a validated
  netlist-to-schematic pipeline.
- Run KiCad ERC on generated schematics.
- Generate PCB layouts only from validated connectivity.
- Run PCB DRC on generated boards.
- Review thermal, current, clearance, creepage, EMI and manufacturability.
- Require a qualified human review before fabrication.

## Operations
- Add structured logs and error monitoring.
- Add health checks and uptime monitoring.
- Back up persistent project artifacts.
- Define recovery and rollback procedures.
- Pin tested dependency versions.
- Maintain a staging environment separate from production.
- Version API schemas and generated artifact formats.
- Document incident response and support ownership.

---

# Part 14 — Production roadmap and release gates

## Release 0.1 — Current starter
- Multimodal input.
- Structured design analysis.
- Missing-information handling.
- BOM and connection exports.
- Structural checks.
- ERC for uploaded reference schematics.

## Release 0.2 — Native circuit generation
- Curated component and symbol library.
- Exact pin maps.
- SKiDL or equivalent deterministic circuit generation.
- Native KiCad schematic export.
- ERC against generated schematic.
- Netlist comparison against intended connectivity.

## Release 0.3 — PCB layout
- Footprint assignment and validation.
- Board outline and design constraints.
- Placement proposal.
- Routing strategy or controlled autorouting.
- PCB DRC and manufacturing outputs.
- Human review of generated layouts.

## Release 0.4 — Engineering verification
- SPICE simulation for supported circuit classes.
- Component rating and derating checks.
- Power and thermal calculations.
- Failure-case analysis.
- Evidence-backed component sourcing.

## Release 1.0 — Controlled production
- Authentication and project permissions.
- Auditable design history.
- Versioned artifacts.
- Monitoring and quotas.
- Security review.
- Engineering validation suite.
- Fabrication sign-off workflow.
- Documented limitations and support policy.

A release gate is passed only when the feature has working implementation,
automated tests and evidence from actual engineering tools. A roadmap entry
or a successful AI response is not a release gate.

---

# Part 15 — Event demonstration checklist

Before presenting:

1. Use one known reference circuit.
2. Show a text-only design request.
3. Show an image-based circuit interpretation.
4. Show the structured component and connection output.
5. Highlight missing or uncertain information.
6. Download and open the BOM and connection report.
7. Run KiCad ERC on a real schematic and show its report.
8. Demonstrate a deliberately ambiguous or faulty input and show that the
   system requests confirmation rather than fabricating certainty.
9. Explain which functions are implemented and which are planned.

The strongest demonstration is one where the system refuses to invent an
uncertain pin connection and explains what evidence is needed to proceed.

---

# Final release rule

Do not label CircuitPilot "production-ready" merely because it is deployed.

Use these labels accurately:

- **Prototype:** core workflow demonstrated.
- **MVP:** repeatable workflow, tests and documented limitations.
- **Production candidate:** security, operations, reliability and engineering
  verification gates completed.
- **Production:** approved release with ongoing monitoring and ownership.

The team lead owns the release decision. The EDA owner signs off the engineering
validation evidence. The AI owner documents model limitations. The product
owner verifies the user-facing behavior.
