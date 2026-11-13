# Delivery Readiness

## Reproducible local gate

From the project root:

```bash
uv sync --python 3.12 --extra test
make release-audit
```

The command writes `outputs/release_audit.json`. The report is intentionally split into:

- `local` checks: backend regression, configuration validation, frontend production build, desktop browser regression, dependency audits and manifest syntax;
- `synthetic` checks: the offline mission demo and deterministic rule acceptance;
- `external` checks: live Auth, Storage I/O, Compose runtime, Slurm/Isaac Sim/ROS 2 and field/EAM acceptance.

`PASSED` only means the command completed successfully. Synthetic checks are software-contract evidence, not sensor accuracy or field evidence. The audit never starts Docker services, submits a Slurm job, signs in to Supabase, uploads an object, or connects to a robot.

## Status meanings

| Status | Meaning |
|---|---|
| `READY_FOR_RELEASE` | All checks in the report, including external acceptance evidence, are `PASSED`. |
| `LOCAL_VERIFIED_EXTERNAL_VALIDATION_REQUIRED` | Local checks passed, but one or more target-environment gates remain open. |
| `LOCAL_CHECKS_FAILED` | At least one local check failed; do not proceed to external acceptance. |

## Required target-environment evidence

1. A dedicated non-production Supabase user with trusted application roles can sign in and read the protected API.
2. Storage smoke upload, idempotent replay, download and SHA-256 verification succeed with the restricted service identity.
3. Compose services start from a clean host, become healthy, and expose only the intended TLS entry point.
4. An authorized Slurm smoke job verifies the target GPU/driver/container path, Isaac Sim/ROS 2 execution and result-bundle import.
5. Field acceptance covers robot safety, calibration, human review and any EAM adapter before real equipment is connected.

Each item must retain its command, environment/version information, timestamps, logs and output hashes. Do not replace a missing item with a screenshot, mock response or synthetic result.
