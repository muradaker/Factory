"""
config.py — Loads .env and exposes a typed singleton `cfg`.
All settings validated via pydantic-settings.
"""

import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env from project root (two levels up from this file)
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_env_path, override=False)


class Settings(BaseSettings):
    # LLM
    model_base_url: str = Field("http://localhost:11434/v1", env="MODEL_BASE_URL")
    model_name: str = Field("qwen2.5-coder:32b", env="MODEL_NAME")
    model_timeout_seconds: int = Field(300, env="MODEL_TIMEOUT_SECONDS")

    # Build flags
    build_with_unreal: bool = Field(True, env="BUILD_WITH_UNREAL")
    allow_build_skip: bool = Field(False, env="ALLOW_BUILD_SKIP")

    # Unreal paths (Windows)
    unreal_run_uat: str = Field(
        r"C:/Program Files/Epic Games/UE_5.5/Engine/Build/BatchFiles/RunUAT.bat",
        env="UNREAL_RUN_UAT",
    )
    ue_editor_cmd: str = Field(
        r"C:/Program Files/Epic Games/UE_5.5/Engine/Binaries/Win64/UnrealEditor-Cmd.exe",
        env="UE_EDITOR_CMD",
    )
    ue_project_path: str = Field(
        r"C:/FactoryProject/FactoryProject/FactoryProject.uproject",
        env="UE_PROJECT_PATH",
    )
    ue_server_map: str = Field(
        "/Game/PluginDemos/{PackName}/Maps/Demo_{PackName}?listen",
        env="UE_SERVER_MAP",
    )
    ue_client_map: str = Field(
        "/Game/PluginDemos/{PackName}/Maps/Demo_{PackName}",
        env="UE_CLIENT_MAP",
    )

    # Directories
    workspace_dir: str = Field("./workspace", env="WORKSPACE_DIR")
    log_dir: str = Field("./logs", env="LOG_DIR")
    state_dir: str = Field("./state", env="STATE_DIR")

    # Factory loop
    factory_loop_sleep_seconds: int = Field(30, env="FACTORY_LOOP_SLEEP_SECONDS")
    factory_max_job_retries: int = Field(3, env="FACTORY_MAX_JOB_RETRIES")
    factory_fail_cooldown_seconds: int = Field(120, env="FACTORY_FAIL_COOLDOWN_SECONDS")
    factory_success_cooldown_seconds: int = Field(10, env="FACTORY_SUCCESS_COOLDOWN_SECONDS")

    # Multiplayer
    multiplayer_test_timeout_seconds: int = Field(90, env="MULTIPLAYER_TEST_TIMEOUT_SECONDS")

    # Self-heal
    self_heal_enabled: bool = Field(True, env="SELF_HEAL_ENABLED")
    self_heal_max_passes_per_run: int = Field(3, env="SELF_HEAL_MAX_PASSES_PER_RUN")

    # Feature flags
    memory_enabled: bool = Field(True, env="MEMORY_ENABLED")
    dataset_writing_enabled: bool = Field(True, env="DATASET_WRITING_ENABLED")
    retrieval_enabled: bool = Field(True, env="RETRIEVAL_ENABLED")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    # --- helpers ---

    def workspace_for(self, pack_name: str) -> Path:
        """Return the workspace dir for a given pack."""
        return Path(self.workspace_dir) / pack_name

    def reports_dir(self, pack_name: str) -> Path:
        """Return the Reports subdirectory inside a pack workspace."""
        return self.workspace_for(pack_name) / "Reports"

    def workspace_path(self) -> Path:
        return Path(self.workspace_dir)

    def log_path(self) -> Path:
        return Path(self.log_dir)

    def state_path(self) -> Path:
        return Path(self.state_dir)


# Singleton — import and use `cfg` everywhere
cfg = Settings()
