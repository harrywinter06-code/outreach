from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # NIM — supports multiple keys (NIM_API_KEY_1 … NIM_API_KEY_5)
    # Each key is one independent account with its own rate limit.
    # If an account gets banned, the pool drops it silently; others continue.
    # 40 RPM / 38K RPD per account (daily quota not published — estimate).
    nim_api_key_1: str = ""
    nim_api_key_2: str = ""
    nim_api_key_3: str = ""
    nim_api_key_4: str = ""
    nim_api_key_5: str = ""
    nim_api_key_6: str = ""
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    # Nemotron-70B: NVIDIA's instruction-tuned reasoning variant, outperforms vanilla Llama-3.1-70B
    nim_model_executive: str = "nvidia/llama-3.1-nemotron-70b-instruct"
    nim_model_worker: str = "meta/llama-3.1-8b-instruct"
    nim_rpm: int = 40
    nim_rpd: int = 38_000

    @property
    def nim_api_keys(self) -> list[str]:
        return [
            k for k in [
                self.nim_api_key_1, self.nim_api_key_2, self.nim_api_key_3,
                self.nim_api_key_4, self.nim_api_key_5, self.nim_api_key_6,
            ] if k
        ]

    # Groq — llama-3.1-70b-versatile was deprecated; 3.3-70b is current and better
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model_executive: str = "llama-3.3-70b-versatile"
    groq_model_worker: str = "llama-3.1-8b-instant"
    groq_rpm: int = 30
    groq_rpd: int = 1_000

    # Gemini 2.0 Flash: significantly better than 1.5 Flash, same free-tier limits
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model_executive: str = "gemini-2.0-flash"
    gemini_model_worker: str = "gemini-2.0-flash"
    gemini_rpm: int = 15
    gemini_rpd: int = 1_500

    # Cerebras — llama3.1-70b deprecated; 3.3-70b is current (same ultra-fast inference)
    cerebras_api_key: str = ""
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_model_executive: str = "llama3.3-70b"
    cerebras_model_worker: str = "llama3.1-8b"
    cerebras_rpm: int = 30
    cerebras_rpd: int = 14_400

    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql://clawbot:clawbot@localhost:5432/clawbot"
    max_daily_spend_usd: float = 5.00
    kill_file_path: str = "/tmp/clawbot.KILL"

    # Operator escalation — agents reach the human via the bus → JSONL + optional
    # ntfy.sh push and/or Telegram bot. Persistence to disk always happens; the
    # push channels are independent and either/both can be enabled.
    ntfy_topic: str = ""
    ntfy_base_url: str = "https://ntfy.sh"

    # Telegram bot (recommended for two-way): create a bot via @BotFather to get
    # the token, then message your bot once and use @userinfobot to get your chat_id.
    # Setting BOTH enables: outbound escalations as Telegram messages + inbound
    # replies via `/reply <id> <text>` OR Telegram's reply-to-message UI.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Revenue infrastructure (set before first run; system halts if missing)
    gumroad_api_key: str = ""
    stripe_secret_key: str = ""

    @property
    def active_provider_names(self) -> list[str]:
        names = [f"nim-{i+1}" for i in range(len(self.nim_api_keys))]
        if self.groq_api_key:
            names.append("groq")
        if self.gemini_api_key:
            names.append("gemini")
        if self.cerebras_api_key:
            names.append("cerebras")
        return names


settings = Settings()
