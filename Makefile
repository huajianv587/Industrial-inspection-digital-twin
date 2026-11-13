UV ?= uv
PYTHON ?= $(UV) run --extra test python
export PYTHONPATH := src

.PHONY: test test-web demo virtual-demo industrial-validate industrial-demo local-demo local-demo-v16 local-demo-v17 local-demo-v18 local-demo-v19 local-demo-v20 local-demo-v21 local-demo-v22 local-demo-v23 local-demo-v24 local-demo-v25 local-demo-v26 local-demo-v27 local-demo-v28 local-demo-v29 local-demo-v30 local-demo-v31 local-demo-v37 local-demo-v38 validate-local-demo-v31 validate-local-demo-v38 data evaluate validate release-audit audit-python preflight validate-auth migrate validate-storage smoke-storage dev-api smoke-api smoke-auth-api up up-tls up-eam down down-tls down-eam
test:
	$(PYTHON) -m unittest discover -s tests -v

test-web:
	cd web && npm run test:e2e

demo:
	$(PYTHON) -m inspection_system.cli demo --config configs/site.json --output-dir outputs/demo

virtual-demo:
	$(PYTHON) -m inspection_system.cli virtual-demo --config configs/site.json --output-dir outputs/virtual-demo --render-backend auto

industrial-validate:
	$(PYTHON) -m inspection_system.cli validate-industrial-site --config configs/industrial_site_v12.json

industrial-demo:
	$(PYTHON) -m inspection_system.cli virtual-demo --config configs/industrial_site_v12.json --output-dir outputs/industrial-v12 --render-backend blender

local-demo:
	bash scripts/local_demo.sh

local-demo-v16:
	bash scripts/local_demo_v16.sh

local-demo-v17:
	bash scripts/local_demo_v17.sh

local-demo-v18:
	bash scripts/local_demo_v18.sh

local-demo-v19:
	bash scripts/local_demo_v19.sh

local-demo-v20:
	bash scripts/local_demo_v20.sh

local-demo-v21:
	bash scripts/local_demo_v21.sh

local-demo-v22:
	bash scripts/local_demo_v22.sh

local-demo-v23:
	bash scripts/local_demo_v23.sh

local-demo-v24:
	bash scripts/local_demo_v24.sh

local-demo-v25:
	bash scripts/local_demo_v25.sh

local-demo-v26:
	bash scripts/local_demo_v26.sh

local-demo-v27:
	bash scripts/local_demo_v27.sh

local-demo-v28:
	bash scripts/local_demo_v28.sh

local-demo-v29:
	bash scripts/local_demo_v29.sh

local-demo-v30:
	bash scripts/local_demo_v30.sh

local-demo-v31:
	bash scripts/local_demo_v31.sh

local-demo-v37:
	bash scripts/local_demo_v37.sh

local-demo-v38:
	bash scripts/local_demo_v38.sh

validate-local-demo-v31:
	uv run python scripts/validate_local_demo_v31.py

validate-local-demo-v38:
	uv run python scripts/validate_local_demo_v38.py

data:
	$(PYTHON) -m inspection_system.cli generate-data --count 200 --seed 42 --output outputs/synthetic_dataset.jsonl

evaluate:
	$(PYTHON) -m inspection_system.cli evaluate --output outputs/acceptance_report.json

validate:
	$(PYTHON) -m inspection_system.cli validate-config --config configs/site.json

release-audit:
	$(PYTHON) scripts/release_audit.py

audit-python:
	$(UV) audit --locked

preflight:
	uv run --env-file .env inspection-system validate-runtime

validate-auth:
	uv run --env-file .env inspection-system validate-auth-policy

migrate:
	uv run --env-file .env alembic upgrade head

validate-storage:
	uv run --env-file .env python scripts/validate_supabase_storage.py

smoke-storage:
	uv run --env-file .env python scripts/smoke_supabase_storage.py

dev-api:
	APP_ENV=development INSPECTION_EXECUTOR=offline SLURM_RESULT_SOURCE=synthetic_simulation SITE_CONFIG_PATH=configs/site.json ARTIFACT_DIR=artifacts ARTIFACT_STORAGE_BACKEND=local uv run --env-file .env uvicorn inspection_system.platform.api:create_app --factory --host 127.0.0.1 --port 8010 --log-config configs/logging.json

smoke-api:
	bash scripts/smoke_api.sh

smoke-auth-api:
	SMOKE_AUTH_E2E=1 bash scripts/smoke_api.sh

up:
	docker compose up --build -d

up-tls:
	docker compose -f docker-compose.yml -f docker-compose.tls.yml up --build -d

up-eam:
	docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.eam.yml up --build -d

down:
	docker compose down

down-tls:
	docker compose -f docker-compose.yml -f docker-compose.tls.yml down

down-eam:
	docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.eam.yml down
