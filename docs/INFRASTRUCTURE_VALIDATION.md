# Infrastructure Validation

Last checked: Supabase on 2026-10-21; CCDS-TC2 on 2026-10-20. A fresh SSH reachability probe to TC2 on 2026-10-21 timed out before authentication. This record does not claim an Isaac Sim run or a Slurm job submission.

## Supabase

- Project reference in the database URLs, project URL, and OIDC issuer: `ypytykmpfxvmrgeujsop`.
- Both owner and runtime connections use the Singapore session pooler with TLS `verify-full` and the repository's configured root certificate. Credentials remain in the ignored `.env` file and are intentionally omitted here.
- The earlier baseline validation reached `20261020_0003`. On 2026-10-20, migrations `20261020_0004` and `20261020_0005` were applied to the same verified project. On 2026-10-21, `20261021_0006` added the `(missions.status, missions.updated_at)` retry-queue index; `alembic current` reports `20261021_0006` and `alembic check` reports no new upgrade operations.
- Migration `20261020_0005` created `service_heartbeats` with RLS and minimum runtime-role grants. The schema is deployed, but no worker instance has written a heartbeat; runtime status remains `not_seen`.
- `scripts/validate_supabase_storage.py` read-only verification confirmed the `inspection-artifacts` bucket is private, has a 209715200-byte limit, and allows only the expected authenticated SELECT/INSERT/UPDATE service policies scoped to `app_metadata.inspection_storage=service`.
- The API on `127.0.0.1:8010/readyz` returned HTTP 200 against Supabase during this validation. This is database readiness only; no Storage object upload/download was run because Storage Auth secrets are not provisioned in the ignored `secrets/` directory.
- The runtime URL connects as `inspection_app`. The role is neither a superuser nor `BYPASSRLS`.
- RLS is enabled on `missions`, `work_orders`, `artifacts`, and `audit_events`; each has the expected `inspection_app_access` policy. The runtime role has the required table grants.
- The deployed `missions.submission_attempts` column is non-null and has no default after backfill, matching migration `20261020_0002`.
- The deployed nullable `missions.cancellation_target` column and allowed-value check constraint match migration `20261020_0003`; existing `CANCELLING` rows were backfilled to target `CANCELLED`.
- Supabase Auth JWKS returned HTTP 200 with one key. This verifies the configured issuer endpoint only; no user sign-in or authenticated API request has yet been verified against this project.

## CCDS-TC2

- Key-based SSH reached the configured `10.96.189.12` login host using strict host-key checking against the existing `known_hosts` entry. No password was used. Commands were read-only; no cluster files were created, and shared-folder inspection was limited to the published user guide.
- Login node reported `CCDS-TC2`, Rocky Linux 9.5, kernel `5.14.0-503.14.1.el9_5.x86_64`.
- The account reports partition `MGPU-TC2`, QOS `normal`, limits of 10 CPUs, 1 GPU, 30 GiB memory, 2 jobs, and 6 hours wall time.
- Slurm advertises generic `gpu:nvidia` resources: 8 GPUs on `TC2N01-02` and 4 GPUs on `TC2N03-08`. This does not establish that a node has an A40.
- `cuda/12.8.0` is listed among the relevant modules. `cm-image/11.0` exposes Enroot `3.5.0`; Slurm `srun --help` exposes `--container`. No Isaac Sim or ROS 2 module, Docker, Podman, Apptainer, or Singularity was found. The user guide says GPU cards are on compute nodes, not the login node, and forbids running computation on the login node; the login-node absence of `nvidia-smi` therefore says nothing about the compute-node GPU/driver.
- The shared user guide does not document Enroot GPU execution or the site's container hooks. No Enroot image is staged in the user account. Container image compatibility and Slurm-to-GPU passthrough remain untested.
- The published user guide states that GPU computation must run as a Slurm job on compute nodes, not on the login node, and that user work is confined to home/shared folders. The user quota command did not report a numeric quota in this session.
- One user GPU job was already running during the check. No job was submitted, cancelled, or modified. GPU model and compute-node driver remain unverified.
- The login banner restricts compute use to academic purposes and file access to the user's home/shared folders. Any smoke job must comply with those restrictions and the account's allocation.
- On 2026-10-21, a non-interactive SSH probe using the TC2-specific key, strict host-key checking, and public-key authentication only timed out while connecting to port 22. Route lookup selected the ordinary gateway `192.168.50.1` on `en0`, with no 10/8 or tunnel-interface route, so the host was not reachable through a campus-VPN route at that time. No password authentication was attempted and no cluster-side command ran; cluster details below remain based on the 2026-10-20 read-only session.

## Isaac Sim Compatibility Gate

- NVIDIA's Isaac Sim 6.2.0 system requirements list Ubuntu 22.04/24.04 for native Linux installation and a Linux driver baseline of `595.58.03`. NVIDIA's container path is Linux-only and documents Docker plus NVIDIA Container Toolkit; this cluster instead exposes Enroot, so the vendor-documented path is not yet proven here.
- NVIDIA's official Isaac Sim repository lists A40 in its minimum datacenter/server configuration. TC2 currently reports only generic `gpu:nvidia`; the actual model has not been independently confirmed.
- Do not select or report an Isaac Sim runtime version as cluster-compatible until an authorized compute-node allocation verifies its GPU model, driver, Enroot GPU hooks, and ROS 2 bridge.
- References: [Isaac Sim 6.2.0 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html), [Isaac Sim 6.2.0 container installation](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_container.html), [official Isaac Sim repository](https://github.com/isaac-sim/IsaacSim).

## Remaining Verification Gates

1. Use an actual Supabase Auth user to verify login, role claims, and an authenticated dashboard API request.
2. Confirm the specific GPU model, driver, Enroot GPU hooks/container path, Isaac Sim version, and ROS 2 Bridge on an allocated compute node or through cluster support.
3. Only after those checks and available GPU quota, run one authorized headless multi-waypoint Slurm job and verify its returned result bundle.
4. The existing Slurm runner remains `synthetic_simulation` only. This infrastructure check does not upgrade that status to Isaac Sim or field validation.
