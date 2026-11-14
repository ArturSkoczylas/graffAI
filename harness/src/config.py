from __future__ import annotations

from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict, model_validator

_VALID_PROVIDERS = {"claude", "openai"}
_VALID_DETECTION = {"idle", "poll"}
_TRUE_VALUES = {"1", "true", "yes", "tak"}


class ConfigError(ValueError):
    pass


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    imap_use_ssl: bool
    inbox_folder: str
    drafts_folder: str
    detection_mode: str
    poll_interval_seconds: int
    use_skill: bool
    ai_provider: str
    ai_model: str
    ai_api_key: str
    ai_max_tokens: int
    state_file: str
    from_address: str

    @model_validator(mode="after")
    def _check_provider_requirements(self) -> "Config":
        if self.ai_provider not in _VALID_PROVIDERS:
            raise ConfigError(
                f"AI_PROVIDER musi być 'claude' albo 'openai', dostałem: {self.ai_provider!r}"
            )
        if self.detection_mode not in _VALID_DETECTION:
            raise ConfigError(
                f"DETECTION_MODE musi być 'idle' albo 'poll', dostałem: {self.detection_mode!r}"
            )
        return self

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Config":
        def require(key: str) -> str:
            value = (env.get(key) or "").strip()
            if not value:
                raise ConfigError(f"Brak wymaganej zmiennej środowiskowej: {key}")
            return value

        def to_int(key: str, default: int) -> int:
            raw = env.get(key)
            if raw is None or str(raw).strip() == "":
                return default
            try:
                value = int(str(raw).strip())
            except ValueError:
                raise ConfigError(f"{key} musi być liczbą całkowitą, dostałem: {raw!r}")
            if value <= 0:
                raise ConfigError(f"{key} musi być większe od zera, dostałem: {value}")
            return value

        def to_bool(key: str, default: bool) -> bool:
            raw = env.get(key)
            if raw is None or str(raw).strip() == "":
                return default
            return str(raw).strip().lower() in _TRUE_VALUES

        imap_host = require("IMAP_HOST")
        imap_user = require("IMAP_USER")
        imap_password = require("IMAP_PASSWORD")

        ai_provider = (env.get("AI_PROVIDER") or "claude").strip().lower()
        ai_api_key = require("AI_API_KEY")
        ai_model = (env.get("AI_MODEL") or "").strip()
        if ai_provider == "claude" and not ai_model:
            ai_model = "claude-sonnet-5-5"
        if not ai_model:
            raise ConfigError("AI_MODEL wymagany dla AI_PROVIDER={ai_provider!r} (brak sensownej wartości domyślnej)".format(ai_provider=ai_provider))

        try:
            return cls(
                imap_host=imap_host,
                imap_port=to_int("IMAP_PORT", 993),
                imap_user=imap_user,
                imap_password=imap_password,
                imap_use_ssl=to_bool("IMAP_USE_SSL", True),
                inbox_folder=(env.get("IMAP_INBOX_FOLDER") or "INBOX").strip(),
                drafts_folder=(env.get("IMAP_DRAFTS_FOLDER") or "Drafts").strip(),
                detection_mode=(env.get("DETECTION_MODE") or "idle").strip().lower(),
                poll_interval_seconds=to_int("POLL_INTERVAL_SECONDS", 60),
                use_skill=to_bool("USE_ODPOWIEDZI_SKILL", True),
                ai_provider=ai_provider,
                ai_model=ai_model,
                ai_api_key=ai_api_key,
                ai_max_tokens=to_int("AI_MAX_TOKENS", 3000),
                state_file=(env.get("STATE_FILE") or "/data/state.json").strip(),
                from_address=(env.get("FROM_ADDRESS") or imap_user).strip(),
            )
        except ConfigError:
            raise
        except Exception as exc:  # pydantic ValidationError from the model_validator path
            raise ConfigError(str(exc)) from exc
