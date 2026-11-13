# 系统架构与模块边界

## 业务与数据流

```text
React 运维控制台
  | Supabase Auth access token (production) / local demo identity (local_demo)
  v
Nginx -> FastAPI -> Supabase PostgreSQL (production/development)
                    | missions / work_orders / eam_submissions / artifacts metadata / audit_events
                    | Alembic migrations only; no startup create_all
  |
  +-> worker -> offline adapter (synthetic) OR SSH/SCP -> Slurm
                                          | immutable mission manifest
                                          | result bundle + SHA-256
                                          v
                                   schema/source/hash validation
                                          |
                                          +-> work order -> human review -> audit trail
                                                               |
                                                               +-> admin ACK -> EAM adapter (optional)
```

本机演示分支：

```text
React/Vite -> FastAPI -> file-backed SQLite + local artifact directory
                         |
                         +-> offline worker -> local kinematic virtual world -> SVG/optional Blender artifacts
```

## Runtime boundaries

- PostgreSQL is remotely hosted by the project's Supabase instance for production and ordinary development. Only the explicit `APP_ENV=local_demo` path accepts a file-backed SQLite database; `APP_ENV=test` accepts only ephemeral in-memory SQLite. No production/development path silently falls back to a local file database.
- Supabase Auth signs users in; FastAPI validates access tokens against the project's HTTPS issuer/JWKS. Privileged application roles come only from trusted `app_metadata` claims.
- Supabase business tables enable RLS; only a dedicated non-owner `inspection_app` database role receives a service policy and per-table minimum grants. Audit rows are append-only for the runtime role. API role checks remain in FastAPI, while the `anon` and `authenticated` database roles receive no policy from this migration.
- API and worker share SQLAlchemy entities and use Alembic for production/development schema changes. The explicit `local_demo` API initializes its self-contained SQLite schema because it has no migration service; production and ordinary development never auto-create tables.
- Mission cancellation is recorded by the API as an audited `CANCELLING` transition, including while `sbatch` is still in flight. Only the worker holds Slurm SSH credentials, retries `scancel`, and marks a job `CANCELLED` after Slurm reports that terminal state. Result import stays closed during cancellation; if Slurm reports `COMPLETED` first, the worker records the race and imports the validated result instead of discarding a completed run.
- A pending Slurm cancellation stores its intended terminal state (`CANCELLED`, `FAILED`, or `TIMED_OUT`) separately, so timeout and scheduler-recovery actions remain retryable without being misreported as user cancellations.
- Docker Compose has no local database service or local artifact volume. Production API/worker store binaries in a private Supabase Storage bucket; test/development can explicitly use the local adapter.
- Base Compose binds the web container's HTTP port to `127.0.0.1` only. The production `docker-compose.tls.yml` overlay removes that host publication and adds a Caddy edge service that is the only public service, publishing `80/tcp`, `443/tcp` and `443/udp`; Caddy forces HTTPS, manages certificates and emits HSTS. Nginx forwards the proxy's `X-Forwarded-Proto` to the API.
- Nginx emits a restrictive Content Security Policy and browser security headers. Hashed Vite assets receive long-lived caching, while the SPA entry point is revalidated so releases do not leave users on a stale bundle.
- Compose file secrets are copied during a short root entrypoint phase into a tmpfs directory with `appuser` ownership; API and worker then run unprivileged. Slurm SSH secrets are only mounted by `docker-compose.slurm.yml`.
- Compose applies Docker `json-file` log rotation to every service (`10 MiB` per file, five files retained); this bounds container-local logs, not application audit history or Supabase retention.
- Caddy certificate state is kept in named Docker volumes `caddy_data` and `caddy_config`; deleting them forces certificate state recovery and must be treated as an operational change.
- Slurm jobs receive a frozen manifest and source bundle over key-only SSH/SCP with pinned host keys. Result bundles are size-limited and path-restricted; the worker checks the remote archive size, stages ZIP members in chunks, validates hashes/schema, and streams binary files into artifact storage before idempotent import.
- Sensor files returned by an Isaac adapter are namespaced by waypoint and linked from that waypoint's observation provenance with sensor ID, media type and capture timestamp; import rejects missing, duplicate or unreferenced files.
- Model execution is a separate fail-closed boundary: a versioned model manifest pins the runtime entrypoint, input/output schema, artifact size and SHA-256. A model runtime error is terminal for that inference and must not silently fall back to the deterministic rule engine.
- The Slurm job runner dispatches `synthetic_simulation` to the offline adapter and `isaac_sim` to `IsaacRunner`; the latter now loads the frozen model runtime and emits model provenance. No real Isaac Sim, ROS 2 bridge, cluster result return, or robot acceptance has been externally validated.
- The ROS 2 boundary is lazy-loaded and uses Nav2 `NavigateToPose`; the bridge service defaults to `allow_motion=false`, and no raw `/cmd_vel` path is exposed by this adapter. Contract tests cover bounded retry, cancellation, observation provenance, and source identity; a target ROS 2 distribution and robot have not been run.
- EAM submission is a separate, opt-in boundary. The API persists `eam_submissions`, requires `REVIEWED` + `ACKNOWLEDGED`, grants submission to `admin` only, sends a stable `Idempotency-Key`, and records success/failure/replay audit events. The vendor endpoint remains outside local validation.

## Adapter boundaries

| Boundary | Current implementation | Not yet validated |
|---|---|---|
| Execution | Offline simulator and Slurm client | School cluster SSH, scheduler policy, smoke job |
| Database | SQLAlchemy + Alembic + Supabase Postgres URL enforcement | Current project was validated through migration `20261021_0006`; local migration head is `20261026_0007`; applying it to the project and backup/restore remain pending |
| Identity | Supabase-compatible OIDC/JWKS validation | Project Auth settings, real roles, refresh behavior |
| Robot | Structural `RobotAdapter` protocol; synthetic implementation declares its source and captured identity is checked | Unitree SDK, Nav2, safety interlocks, E-stop |
| Perception | Deterministic rules plus a versioned model-runtime contract, IsaacRunner integration, and artifact verifier | Trained model, real Isaac/ROS 2 sensor path, sensor calibration, holdout evaluation |
| Artifacts | Supabase S3-compatible adapter + content-addressed keys + streamed SHA-256 verification; private bucket and scoped policies verified in project | Storage Auth object read/write smoke, retention policy, backup/restore |
| EAM | Durable `eam_submissions` state, HTTPS Bearer adapter, stable `Idempotency-Key`, admin-only API, human ACK gate, retry and replay audit events | Vendor endpoint/credentials, approval mapping, external idempotency replay and field acceptance |

## Data and safety rules

- Every result links to `run_id`, site, robot, waypoint/device, source, seed, configuration hash, timestamps and artifact digests.
- Missing measurements remain unknown/null; they are not converted to normal readings.
- Result source must match the immutable submitted manifest. Artifact names, sizes and SHA-256 values are checked before import.
- Work-order recommendations do not command a robot. Human review records actor, decision, comment and time; only an explicit admin action can submit an acknowledged work order through the optional EAM adapter.
- No benchmark or production claim may be based on synthetic-only data.
