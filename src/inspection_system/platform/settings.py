from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
from urllib.parse import urlparse
from sqlalchemy.engine import URL, make_url


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    database_url: str = ""
    environment: str = "production"
    site_config_path: Path = PROJECT_ROOT / "configs" / "site.json"
    industrial_site_config_path: Path = PROJECT_ROOT / "configs" / "industrial_site_v12.json"
    artifact_dir: Path = PROJECT_ROOT / "artifacts"
    artifact_storage_backend: str = "local"
    supabase_url: str | None = None
    supabase_anon_key: str | None = field(default=None, repr=False)
    storage_endpoint: str | None = None
    storage_region: str | None = None
    storage_bucket: str = "inspection-artifacts"
    storage_user_email: str | None = None
    storage_user_password: str | None = field(default=None, repr=False)
    storage_auth_timeout_seconds: float = 10.0
    eam_enabled: bool = False
    eam_base_url: str | None = None
    eam_submit_path: str = "/api/v1/work-orders"
    eam_api_key: str | None = field(default=None, repr=False)
    eam_timeout_seconds: float = 10.0
    executor_mode: str = "offline"
    auth_mode: str = "oidc"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    slurm_host: str | None = None
    slurm_user: str | None = None
    slurm_identity_file: Path | None = None
    slurm_known_hosts_file: Path | None = None
    slurm_remote_root: str | None = None
    slurm_port: int = 22
    slurm_partition: str | None = None
    slurm_account: str | None = None
    slurm_source: str = "synthetic_simulation"
    isaac_sim_version: str | None = None
    isaac_robot_usd_path: str | None = None
    isaac_sim_python: str | None = None
    isaac_sim_adapter: str | None = None
    isaac_model_manifest_path: str | None = None
    isaac_model_manifest_sha256: str | None = None
    isaac_model_artifact_sha256: str | None = None
    isaac_model_id: str | None = None
    isaac_model_version: str | None = None
    isaac_slurm_gres: str | None = None
    isaac_slurm_cpus: int = 4
    isaac_slurm_memory: str = "16G"
    isaac_slurm_time_limit: str = "02:00:00"
    slurm_poll_seconds: float = 15.0
    slurm_command_timeout_seconds: float = 30.0
    submission_recovery_seconds: int = 180
    submission_attempt_limit: int = 3
    result_import_retry_seconds: int = 60
    mission_timeout_seconds: int = 7200
    max_upload_bytes: int = 200 * 1024 * 1024
    worker_heartbeat_stale_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "Settings":
        def optional_path(name: str) -> Path | None:
            value = os.getenv(name)
            return Path(value).expanduser().resolve() if value else None

        def secret_value(name: str) -> str | None:
            value = os.getenv(name)
            file_path = os.getenv(f"{name}_FILE")
            if value and file_path:
                raise ValueError(f"Set either {name} or {name}_FILE, not both.")
            if file_path:
                try:
                    value = Path(file_path).expanduser().read_text(encoding="utf-8").strip()
                except OSError as exc:
                    raise ValueError(f"{name}_FILE could not be read.") from exc
            return value or None

        def boolean_value(name: str, default: bool = False) -> bool:
            value = os.getenv(name)
            if value is None:
                return default
            normalized = value.strip().lower()
            if normalized not in {"1", "0", "true", "false", "yes", "no"}:
                raise ValueError(f"{name} must be a boolean value.")
            return normalized in {"1", "true", "yes"}

        environment = os.getenv("APP_ENV", "production").lower()
        database_url = os.getenv("SUPABASE_APP_DB_URL", "")
        slurm_poll_seconds = float(os.getenv("SLURM_POLL_SECONDS", "15"))
        heartbeat_stale_seconds = float(os.getenv(
            "WORKER_HEARTBEAT_STALE_SECONDS", str(max(60.0, slurm_poll_seconds * 3))))
        if environment == "test":
            database_url = database_url or os.getenv("DATABASE_URL", "")
        elif environment == "local_demo":
            database_url = os.getenv("LOCAL_DATABASE_URL", "") or os.getenv("DATABASE_URL", "")

        return cls(
            database_url=database_url,
            environment=environment,
            site_config_path=Path(os.getenv(
                "SITE_CONFIG_PATH", str(cls.site_config_path))).expanduser().resolve(),
            industrial_site_config_path=Path(os.getenv(
                "INDUSTRIAL_SITE_CONFIG_PATH", str(cls.industrial_site_config_path)
            )).expanduser().resolve(),
            artifact_dir=Path(os.getenv(
                "ARTIFACT_DIR", str(cls.artifact_dir))).expanduser().resolve(),
            artifact_storage_backend=os.getenv("ARTIFACT_STORAGE_BACKEND", "local").lower(),
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_anon_key=secret_value("SUPABASE_ANON_KEY"),
            storage_endpoint=os.getenv("SUPABASE_STORAGE_ENDPOINT"),
            storage_region=os.getenv("SUPABASE_STORAGE_REGION"),
            storage_bucket=os.getenv("SUPABASE_STORAGE_BUCKET", "inspection-artifacts"),
            storage_user_email=secret_value("SUPABASE_STORAGE_EMAIL"),
            storage_user_password=secret_value("SUPABASE_STORAGE_PASSWORD"),
            storage_auth_timeout_seconds=float(os.getenv(
                "SUPABASE_STORAGE_AUTH_TIMEOUT_SECONDS", "10")),
            eam_enabled=boolean_value("EAM_ENABLED"),
            eam_base_url=os.getenv("EAM_BASE_URL"),
            eam_submit_path=os.getenv("EAM_SUBMIT_PATH", "/api/v1/work-orders"),
            eam_api_key=secret_value("EAM_API_KEY"),
            eam_timeout_seconds=float(os.getenv("EAM_TIMEOUT_SECONDS", "10")),
            executor_mode=os.getenv("INSPECTION_EXECUTOR", cls.executor_mode).lower(),
            auth_mode=os.getenv("INSPECTION_AUTH_MODE", cls.auth_mode).lower(),
            oidc_issuer=os.getenv("OIDC_ISSUER"),
            oidc_audience=os.getenv("OIDC_AUDIENCE"),
            slurm_host=os.getenv("SLURM_HOST"),
            slurm_user=os.getenv("SLURM_USER"),
            slurm_identity_file=optional_path("SLURM_IDENTITY_FILE"),
            slurm_known_hosts_file=optional_path("SLURM_KNOWN_HOSTS_FILE"),
            slurm_remote_root=os.getenv("SLURM_REMOTE_ROOT"),
            slurm_port=int(os.getenv("SLURM_PORT", "22")),
            slurm_partition=os.getenv("SLURM_PARTITION"),
            slurm_account=os.getenv("SLURM_ACCOUNT"),
            slurm_source=os.getenv("SLURM_RESULT_SOURCE", "synthetic_simulation"),
            isaac_sim_version=os.getenv("ISAAC_SIM_VERSION"),
            isaac_robot_usd_path=os.getenv("ISAAC_ROBOT_USD_PATH"),
            isaac_sim_python=os.getenv("ISAAC_SIM_PYTHON"),
            isaac_sim_adapter=os.getenv("ISAAC_SIM_ADAPTER"),
            isaac_model_manifest_path=os.getenv("ISAAC_MODEL_MANIFEST_PATH"),
            isaac_model_manifest_sha256=os.getenv("ISAAC_MODEL_MANIFEST_SHA256"),
            isaac_model_artifact_sha256=os.getenv("ISAAC_MODEL_ARTIFACT_SHA256"),
            isaac_model_id=os.getenv("ISAAC_MODEL_ID"),
            isaac_model_version=os.getenv("ISAAC_MODEL_VERSION"),
            isaac_slurm_gres=os.getenv("SLURM_ISAAC_GPU_GRES"),
            isaac_slurm_cpus=int(os.getenv("SLURM_ISAAC_CPUS", "4")),
            isaac_slurm_memory=os.getenv("SLURM_ISAAC_MEMORY", "16G"),
            isaac_slurm_time_limit=os.getenv("SLURM_ISAAC_TIME_LIMIT", "02:00:00"),
            slurm_poll_seconds=slurm_poll_seconds,
            slurm_command_timeout_seconds=float(os.getenv(
                "SLURM_COMMAND_TIMEOUT_SECONDS", "30")),
            submission_recovery_seconds=int(os.getenv("SUBMISSION_RECOVERY_SECONDS", "180")),
            submission_attempt_limit=int(os.getenv("SUBMISSION_ATTEMPT_LIMIT", "3")),
            result_import_retry_seconds=int(os.getenv("RESULT_IMPORT_RETRY_SECONDS", "60")),
            mission_timeout_seconds=int(os.getenv("MISSION_TIMEOUT_SECONDS", "7200")),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(200 * 1024 * 1024))),
            worker_heartbeat_stale_seconds=heartbeat_stale_seconds,
        )

    def validate_database(self) -> None:
        if not self.database_url:
            if self.environment == "local_demo":
                raise ValueError("LOCAL_DATABASE_URL is required for local_demo.")
            raise ValueError("A Supabase PostgreSQL connection URL is required; local databases are disabled.")
        try:
            url = make_url(self.database_url)
        except Exception as exc:
            raise ValueError("SUPABASE_DB_URL is not a valid SQLAlchemy URL.") from exc

        if self.environment == "test":
            if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
                raise ValueError("Tests must use an ephemeral in-memory SQLite database.")
            if url.database not in {None, "", ":memory:"}:
                raise ValueError("File-backed SQLite databases are disabled, including in tests.")
            return

        if self.environment == "local_demo":
            if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
                raise ValueError("local_demo requires a SQLite database.")
            if url.database in {None, "", ":memory:"}:
                raise ValueError("local_demo requires a file-backed SQLite database.")
            return

        if url.drivername not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("Production and development require Supabase PostgreSQL; SQLite is test-only.")
        host = (url.host or "").lower()
        if not (host.endswith(".supabase.co") or host.endswith(".supabase.com")):
            raise ValueError("Database host must be a Supabase-managed PostgreSQL endpoint.")

    @staticmethod
    def _supabase_project_ref(value: str) -> str | None:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        suffix = ".supabase.co"
        if parsed.scheme != "https" or not host.endswith(suffix):
            return None
        project_ref = host[:-len(suffix)]
        if not project_ref or "." in project_ref:
            return None
        return project_ref

    @staticmethod
    def _database_project_ref(database_url: str) -> str | None:
        url = make_url(database_url)
        host = (url.host or "").lower()
        direct_suffix = ".supabase.co"
        if host.endswith(direct_suffix):
            prefix = host[:-len(direct_suffix)].split(".")
            if len(prefix) == 2 and prefix[0] == "db" and prefix[1]:
                return prefix[1]
        if host.endswith(".pooler.supabase.com") and url.username:
            username_parts = url.username.rsplit(".", maxsplit=1)
            if len(username_parts) == 2 and all(username_parts):
                return username_parts[1].lower()
        return None

    def validate_supabase_project_binding(
        self,
        *,
        database_url: str | None = None,
        required: bool = False,
    ) -> None:
        if self.environment == "test" and not required:
            return
        project_ref = (
            self._supabase_project_ref(self.supabase_url)
            if self.supabase_url else None
        )
        if not project_ref and self.oidc_issuer:
            project_ref = self._supabase_project_ref(self.oidc_issuer)
        if not project_ref:
            if required:
                raise ValueError(
                    "SUPABASE_URL is required to verify the database project target.")
            return

        target_url = database_url or self.database_url
        database_ref = self._database_project_ref(target_url)
        if not database_ref:
            raise ValueError(
                "Cannot verify the Supabase database project ref; use a direct project host "
                "or a pooler username ending with the project ref.")
        if database_ref != project_ref:
            raise ValueError(
                "Supabase database URL must target the project identified by SUPABASE_URL.")

        if self.auth_mode == "oidc" and self.oidc_issuer:
            issuer = urlparse(self.oidc_issuer)
            expected_host = f"{project_ref}.supabase.co"
            if (issuer.hostname != expected_host
                    or issuer.path.rstrip("/") != "/auth/v1"
                    or issuer.query or issuer.fragment):
                raise ValueError(
                    "OIDC_ISSUER must be the Auth issuer for the configured Supabase project.")

    def sqlalchemy_database_url(self) -> URL:
        self.validate_database()
        url = make_url(self.database_url)
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        if url.drivername.startswith("postgresql"):
            query = dict(url.query)
            query["sslmode"] = "verify-full"
            url = url.set(query=query)
        return url

    @staticmethod
    def _positive_number(value: object, name: str) -> None:
        try:
            valid = (not isinstance(value, bool)
                     and isinstance(value, (int, float))
                     and math.isfinite(value) and value > 0)
        except (OverflowError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError(f"{name} must be a finite positive number.")

    @staticmethod
    def _positive_integer(value: object, name: str) -> None:
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be positive; an integer is required.")

    def validate(self, *, require_slurm_credentials: bool = True) -> None:
        self.validate_database()
        if self.environment not in {"production", "development", "local_demo", "test"}:
            raise ValueError("APP_ENV must be production, development, local_demo, or test.")
        if self.executor_mode not in {"offline", "slurm"}:
            raise ValueError("INSPECTION_EXECUTOR must be 'offline' or 'slurm'.")
        if self.slurm_source not in {"synthetic_simulation", "isaac_sim"}:
            raise ValueError(
                "SLURM_RESULT_SOURCE must be 'synthetic_simulation' or 'isaac_sim'.")
        if self.environment == "production":
            if self.executor_mode != "slurm":
                raise ValueError(
                    "Production requires INSPECTION_EXECUTOR=slurm; offline execution is development/test only.")
            if self.slurm_source != "isaac_sim":
                raise ValueError(
                    "Production requires SLURM_RESULT_SOURCE=isaac_sim; synthetic results are non-production only.")
        if self.environment == "local_demo":
            if self.executor_mode != "offline":
                raise ValueError("local_demo requires INSPECTION_EXECUTOR=offline.")
            if self.slurm_source != "synthetic_simulation":
                raise ValueError("local_demo requires SLURM_RESULT_SOURCE=synthetic_simulation.")
            if self.auth_mode != "development":
                raise ValueError("local_demo requires INSPECTION_AUTH_MODE=development.")
            if self.artifact_storage_backend != "local":
                raise ValueError("local_demo requires ARTIFACT_STORAGE_BACKEND=local.")
        if self.auth_mode not in {"development", "oidc"}:
            raise ValueError("INSPECTION_AUTH_MODE must be 'development' or 'oidc'.")
        if self.environment == "production" and self.auth_mode != "oidc":
            raise ValueError("Production requires OIDC authentication.")
        if self.auth_mode == "development" and self.environment == "production":
            raise ValueError("Development header authentication is forbidden in production.")
        if self.auth_mode == "oidc":
            if not (self.oidc_issuer and self.oidc_audience):
                raise ValueError("OIDC_ISSUER and OIDC_AUDIENCE are required in OIDC mode.")
            if not self.oidc_issuer.startswith("https://"):
                raise ValueError("OIDC_ISSUER must use HTTPS.")
        if self.artifact_storage_backend not in {"local", "supabase_s3"}:
            raise ValueError("ARTIFACT_STORAGE_BACKEND must be 'local' or 'supabase_s3'.")
        if self.environment == "production" and self.artifact_storage_backend != "supabase_s3":
            raise ValueError("Production requires Supabase object storage for artifacts.")
        if self.artifact_storage_backend == "supabase_s3":
            self.validate_artifact_storage()
        self._validate_eam_settings()
        self._positive_integer(self.max_upload_bytes, "MAX_UPLOAD_BYTES")
        self._positive_number(self.slurm_poll_seconds, "SLURM_POLL_SECONDS")
        self._positive_number(
            self.worker_heartbeat_stale_seconds, "WORKER_HEARTBEAT_STALE_SECONDS")
        self._positive_number(
            self.slurm_command_timeout_seconds, "SLURM_COMMAND_TIMEOUT_SECONDS")
        self._positive_integer(self.mission_timeout_seconds, "MISSION_TIMEOUT_SECONDS")
        if self.worker_heartbeat_stale_seconds < self.slurm_poll_seconds * 2:
            raise ValueError(
                "WORKER_HEARTBEAT_STALE_SECONDS must be at least twice SLURM_POLL_SECONDS.")
        self._positive_integer(self.submission_recovery_seconds, "SUBMISSION_RECOVERY_SECONDS")
        self._positive_integer(self.submission_attempt_limit, "SUBMISSION_ATTEMPT_LIMIT")
        self._positive_integer(self.result_import_retry_seconds, "RESULT_IMPORT_RETRY_SECONDS")
        if self.executor_mode == "slurm":
            if type(self.slurm_port) is not int or not 1 <= self.slurm_port <= 65535:
                raise ValueError("SLURM_PORT must be an integer between 1 and 65535.")
            required = {
                "SLURM_HOST": self.slurm_host,
                "SLURM_USER": self.slurm_user,
                "SLURM_REMOTE_ROOT": self.slurm_remote_root,
            }
            if require_slurm_credentials:
                required.update({
                    "SLURM_IDENTITY_FILE": self.slurm_identity_file,
                    "SLURM_KNOWN_HOSTS_FILE": self.slurm_known_hosts_file,
                })
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError("Missing Slurm settings: " + ", ".join(missing))
            if require_slurm_credentials:
                if not self.slurm_identity_file.is_file():
                    raise ValueError("SLURM_IDENTITY_FILE must point to an existing SSH key.")
                if not self.slurm_known_hosts_file.is_file():
                    raise ValueError("SLURM_KNOWN_HOSTS_FILE must point to a pinned known_hosts file.")
            if self.slurm_source == "isaac_sim":
                self._validate_isaac_slurm_settings()
        self.validate_supabase_project_binding(required=self.environment == "production")

    def _validate_eam_settings(self) -> None:
        if type(self.eam_enabled) is not bool:
            raise ValueError("EAM_ENABLED must be a boolean.")
        self._positive_number(self.eam_timeout_seconds, "EAM_TIMEOUT_SECONDS")
        if (not re.fullmatch(r"/[A-Za-z0-9_./-]+", self.eam_submit_path or "")
                or ".." in PurePosixPath(self.eam_submit_path).parts):
            raise ValueError("EAM_SUBMIT_PATH must be a safe absolute URL path.")
        if not self.eam_enabled:
            return
        if not self.eam_base_url:
            raise ValueError("EAM_BASE_URL is required when EAM_ENABLED=true.")
        parsed = urlparse(self.eam_base_url)
        local_http = (self.environment != "production"
                      and parsed.scheme == "http"
                      and parsed.hostname in {"127.0.0.1", "localhost"})
        if parsed.scheme != "https" and not local_http:
            raise ValueError("EAM_BASE_URL must use HTTPS outside local test endpoints.")
        if not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("EAM_BASE_URL must be an origin without query or fragment.")
        if not self.eam_api_key:
            raise ValueError("EAM_API_KEY is required when EAM_ENABLED=true.")

    def _validate_isaac_slurm_settings(self) -> None:
        required = {
            "ISAAC_SIM_VERSION": self.isaac_sim_version,
            "ISAAC_ROBOT_USD_PATH": self.isaac_robot_usd_path,
            "ISAAC_SIM_PYTHON": self.isaac_sim_python,
            "ISAAC_SIM_ADAPTER": self.isaac_sim_adapter,
            "SLURM_ISAAC_GPU_GRES": self.isaac_slurm_gres,
        }
        model_settings = {
            "ISAAC_MODEL_MANIFEST_PATH": self.isaac_model_manifest_path,
            "ISAAC_MODEL_MANIFEST_SHA256": self.isaac_model_manifest_sha256,
            "ISAAC_MODEL_ARTIFACT_SHA256": self.isaac_model_artifact_sha256,
            "ISAAC_MODEL_ID": self.isaac_model_id,
            "ISAAC_MODEL_VERSION": self.isaac_model_version,
        }
        model_present = [name for name, value in model_settings.items() if value]
        if model_present and len(model_present) != len(model_settings):
            missing_model = [name for name, value in model_settings.items() if not value]
            raise ValueError(
                "Isaac model configuration is incomplete: " + ", ".join(missing_model)
            )
        if self.environment == "production":
            required.update(model_settings)
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError("Isaac Sim Slurm execution requires: " + ", ".join(missing))
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?",
                            self.isaac_sim_version or ""):
            raise ValueError("ISAAC_SIM_VERSION must be an exact semantic version.")
        for name, value in (("ISAAC_ROBOT_USD_PATH", self.isaac_robot_usd_path),
                            ("ISAAC_SIM_PYTHON", self.isaac_sim_python)):
            if (not value or not value.startswith("/")
                    or ".." in PurePosixPath(value).parts
                    or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value)):
                raise ValueError(f"{name} must be a safe absolute cluster path.")
        if self.isaac_model_manifest_path:
            if (not self.isaac_model_manifest_path.startswith("/")
                    or ".." in PurePosixPath(self.isaac_model_manifest_path).parts
                    or not re.fullmatch(r"/[A-Za-z0-9_./-]+", self.isaac_model_manifest_path)):
                raise ValueError(
                    "ISAAC_MODEL_MANIFEST_PATH must be a safe absolute cluster path."
                )
        if model_present:
            for name, value in (("ISAAC_MODEL_MANIFEST_SHA256", self.isaac_model_manifest_sha256),
                                ("ISAAC_MODEL_ARTIFACT_SHA256", self.isaac_model_artifact_sha256)):
                if not re.fullmatch(r"[0-9a-f]{64}", value or ""):
                    raise ValueError(f"{name} must be a lowercase SHA-256 digest.")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.isaac_model_id or ""):
                raise ValueError("ISAAC_MODEL_ID must be a safe model identifier.")
            if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?",
                                self.isaac_model_version or ""):
                raise ValueError("ISAAC_MODEL_VERSION must be an exact semantic version.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*",
                            self.isaac_sim_adapter or ""):
            raise ValueError("ISAAC_SIM_ADAPTER must use module:function notation.")
        if not re.fullmatch(r"gpu:(?:[1-9][0-9]*|[A-Za-z0-9_-]+:[1-9][0-9]*)",
                            self.isaac_slurm_gres or ""):
            raise ValueError("SLURM_ISAAC_GPU_GRES must be a GPU generic resource request.")
        if type(self.isaac_slurm_cpus) is not int or not 1 <= self.isaac_slurm_cpus <= 256:
            raise ValueError("SLURM_ISAAC_CPUS must be between 1 and 256.")
        if not re.fullmatch(r"[1-9][0-9]*[KMG]", self.isaac_slurm_memory):
            raise ValueError("SLURM_ISAAC_MEMORY must be a positive Slurm memory value.")
        if not re.fullmatch(r"(?:(?:[0-9]+)-)?[0-9]{1,3}:[0-5][0-9]:[0-5][0-9]",
                            self.isaac_slurm_time_limit):
            raise ValueError("SLURM_ISAAC_TIME_LIMIT must use Slurm's [days-]hours:minutes:seconds format.")

    def _validate_storage_settings(self) -> None:
        required = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_ANON_KEY": self.supabase_anon_key,
            "SUPABASE_STORAGE_ENDPOINT": self.storage_endpoint,
            "SUPABASE_STORAGE_REGION": self.storage_region,
            "SUPABASE_STORAGE_EMAIL": self.storage_user_email,
            "SUPABASE_STORAGE_PASSWORD": self.storage_user_password,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError("Supabase artifact storage requires: " + ", ".join(missing))
        project = urlparse(self.supabase_url or "")
        endpoint = urlparse(self.storage_endpoint or "")
        expected_storage_host = f"{(project.hostname or '').split('.')[0]}.storage.supabase.co"
        if (project.scheme != "https" or not project.hostname
                or not project.hostname.endswith(".supabase.co")):
            raise ValueError("SUPABASE_URL must identify the project's HTTPS Supabase domain.")
        if (endpoint.scheme != "https" or endpoint.hostname != expected_storage_host
                or endpoint.path.rstrip("/") != "/storage/v1/s3"
                or endpoint.query or endpoint.fragment):
            raise ValueError(
                "SUPABASE_STORAGE_ENDPOINT must be the project's HTTPS S3 endpoint "
                "at /storage/v1/s3.")
        if not re.fullmatch(r"[a-z0-9-]{1,63}", self.storage_region or ""):
            raise ValueError("SUPABASE_STORAGE_REGION must be a valid S3 region identifier.")
        if self.storage_bucket != "inspection-artifacts":
            raise ValueError(
                "SUPABASE_STORAGE_BUCKET must match the migration-managed bucket "
                "'inspection-artifacts'.")
        if self.max_upload_bytes > 200 * 1024 * 1024:
            raise ValueError(
                "MAX_UPLOAD_BYTES cannot exceed the migration-managed bucket limit "
                "of 200 MiB.")
        if not self.storage_user_email or "@" not in self.storage_user_email:
            raise ValueError("SUPABASE_STORAGE_EMAIL must be a valid service-account email.")
        self._positive_number(
            self.storage_auth_timeout_seconds, "SUPABASE_STORAGE_AUTH_TIMEOUT_SECONDS")

    def validate_artifact_storage(self) -> None:
        if self.artifact_storage_backend != "supabase_s3":
            raise ValueError("Storage I/O smoke requires ARTIFACT_STORAGE_BACKEND=supabase_s3.")
        self._validate_storage_settings()
