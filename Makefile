.PHONY: bootstrap lint typecheck test ci eval optimize kappa dashboard capture-fixtures submit-check

# ── Configuration ────────────────────────────────────────────────────────────
ROUTES       ?= all
SURFACE      ?= planning
ITERS        ?= 20
CASE_SET     ?= both
VARIANT      ?= baseline
GCP_PROJECT  ?= adk-quality-lab-tung
REGION       ?= us-central1
BQ_DATASET   ?= adk_quality_lab

# ── Dev tooling ──────────────────────────────────────────────────────────────

bootstrap:
	uv sync --extra dev
	@echo "Bootstrap complete. Run 'source .venv/bin/activate' or prefix commands with 'uv run'."

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy adk_quality_lab tests

test:
	uv run pytest

ci: lint typecheck test

# ── Fixture capture (Day 1 PM) ────────────────────────────────────────────────
# Pulls SerpAPI ground truth into datasets/fixtures/flights/<sha256>.json
# Only call with SERP_API_KEY set. Subsequent evals use cached fixtures.

capture-fixtures:
	@echo "Capturing SerpAPI fixtures for routes=$(ROUTES)..."
	uv run python -m adk_quality_lab.tools.capture_fixtures --routes=$(ROUTES)

# ── Eval harness ─────────────────────────────────────────────────────────────
# CASE_SET: f1 | f2 | both | smoke | gold
# VARIANT:  One of the five improvement phases — each is independently reproducible:
#   baseline          vanilla vendored planning agent (upstream prompt, no changes)
#   prompt_tuning_v1  Optimizer-tuned instruction: verbatim-citation + truncation disclosure
#   structured_output FlightsSelection JSON schema output enforcement
#   prompt_tuning_v2  Optimizer-tuned tool descriptions (flight_search, hotel_search)
#   arch_fix          CashFlightSummary + lean planning_agent_v2 (final architecture)
#
# Judges can replicate any phase:
#   make eval CASE_SET=both VARIANT=baseline
#   make eval CASE_SET=both VARIANT=prompt_tuning_v1
#   make eval CASE_SET=both VARIANT=structured_output
#   make eval CASE_SET=both VARIANT=prompt_tuning_v2
#   make eval CASE_SET=both VARIANT=arch_fix

eval:
	@echo "Running eval CASE_SET=$(CASE_SET) VARIANT=$(VARIANT)..."
	@mkdir -p .cache
	TRAVEL_CONCIERGE_SCENARIO=$(PWD)/examples/travel-concierge/travel_concierge/profiles/itinerary_empty_default.json \
	uv run python -m adk_quality_lab.cli.eval \
		--case-set=$(CASE_SET) \
		--variant=$(VARIANT) \
		--example-dir=examples/travel-concierge \
		$(if $(filter gold,$(CASE_SET)),--output .cache/gold_run.json,)

# ── Optimizer ────────────────────────────────────────────────────────────────
# SURFACE: root | planning | tools
# ITERS:   max optimizer iterations (default 20)

optimize:
	@echo "Running optimizer SURFACE=$(SURFACE) ITERS=$(ITERS)..."
	uv run python -m adk_quality_lab.cli.optimize \
		--surface=$(SURFACE) \
		--max-iters=$(ITERS) \
		--example-dir=examples/travel-concierge

# ── Calibration ──────────────────────────────────────────────────────────────

kappa:
	@echo "Computing Cohen's kappa from gold labels..."
	uv run python -m adk_quality_lab.cli.kappa

# ── Infrastructure ────────────────────────────────────────────────────────────

gcp-setup:
	@echo "=== Step 1: Create project (no-op if it already exists) ==="
	gcloud projects create $(GCP_PROJECT) --name="ADK Quality Lab" || true
	gcloud config set project $(GCP_PROJECT)
	gcloud config set compute/region $(REGION)
	@echo ""
	@echo "=== Step 2: MANUAL — enable billing ==="
	@echo "  Open https://console.cloud.google.com/billing/projects"
	@echo "  Link project '$(GCP_PROJECT)' to your billing account, then press Enter."
	@read _
	@echo ""
	@echo "=== Step 3: Enable APIs ==="
	gcloud services enable \
		aiplatform.googleapis.com \
		run.googleapis.com \
		firestore.googleapis.com \
		bigquery.googleapis.com \
		cloudscheduler.googleapis.com \
		secretmanager.googleapis.com
	@echo ""
	@echo "=== Step 4: Create Firestore Native database ==="
	gcloud firestore databases create --location=$(REGION) --type=firestore-native || true
	@echo ""
	@echo "=== Step 5: Create BigQuery dataset ==="
	bq mk --location=$(REGION) $(GCP_PROJECT):$(BQ_DATASET) || true
	@echo ""
	@echo "GCP setup complete for project $(GCP_PROJECT)."

dashboard:
	@echo "Refreshing Looker Studio backing BigQuery view..."
	uv run python -m adk_quality_lab.cli.dashboard

# ── Demo video ────────────────────────────────────────────────────────────────

video:
	@echo "Assembling demo video (requires OBS recordings in /tmp/obs/)..."
	ffmpeg -f concat -safe 0 -i docs/video_manifest.txt \
		-c:v libx264 -crf 20 -c:a aac \
		docs/demo_90s.mp4
	@echo "Video: docs/demo_90s.mp4"

# ── Pre-submission check ──────────────────────────────────────────────────────

submit-check:
	@echo "=== Pre-submission check ==="
	@echo "1. Checking for AwardWise references..."
	@! grep -ri "awardwise" . --include="*.py" --include="*.md" --include="*.txt" --include="*.yaml" --include="*.json" \
		--exclude-dir=".git" --exclude-dir=".venv" --exclude-dir="__pycache__" \
		&& echo "   PASS: No AwardWise references found." || (echo "   FAIL: AwardWise reference found!" && exit 1)
	@echo "2. Checking video length..."
	@[ -f docs/demo_90s.mp4 ] && \
		python3 -c "import subprocess, sys; r=subprocess.run(['ffprobe','-v','quiet','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1','docs/demo_90s.mp4'],capture_output=True,text=True); d=float(r.stdout.strip()); sys.exit(0 if d<=90 else 1)" \
		&& echo "   PASS: Video ≤ 90s." || echo "   WARN: Video missing or > 90s."
	@echo "3. Checking run-ids.md is populated..."
	@grep -q "run_id" docs/run-ids.md && echo "   PASS: run-ids.md has run IDs." || echo "   WARN: docs/run-ids.md missing run IDs."
	@echo "4. Checking datasets exist..."
	@[ -f datasets/f1_count_hallucination.jsonl ] && [ -f datasets/f2_groundedness.jsonl ] \
		&& echo "   PASS: Dataset files present." || echo "   FAIL: Dataset files missing!"
	@echo "=== Submit-check complete ==="
