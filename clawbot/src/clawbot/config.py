from pydantic import Field
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
    # Llama 4 Maverick: 128-expert MoE, currently best available on NIM (Nemotron removed May 2026)
    nim_model_executive: str = "meta/llama-4-maverick-17b-128e-instruct"
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

    # Cerebras — llama3.3-70b removed May 2026; qwen-3-235b is the current top model (22B active, MoE)
    cerebras_api_key: str = ""
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_model_executive: str = "qwen-3-235b-a22b-instruct-2507"
    cerebras_model_worker: str = "llama3.1-8b"
    cerebras_rpm: int = 30
    cerebras_rpd: int = 14_400

    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql://clawbot:clawbot@localhost:5432/clawbot"
    max_daily_spend_usd: float = 5.00
    kill_file_path: str = "/tmp/clawbot.KILL"
    pause_file_path: str = "/tmp/clawbot.PAUSE"

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

    # PayPal — order create/capture + transactions reporting (Phase H Task 25).
    # Without these, _LiveRevenue's paypal_* methods return stub data so the
    # revenue_aggregate_today_gbp skill still works (counts only what is set).
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_environment: str = "live"  # "live" or "sandbox"

    # Coinbase Commerce — fixed-price charges for crypto receive addresses.
    # Optional; absent key makes crypto_* skills return empty stubs.
    coinbase_commerce_api_key: str = ""

    # Search & extraction — both free-tier, both optional.
    # tavily: LLM-graded web search (1k/mo free). Used by SearchClient.search.
    # firecrawl: URL → clean markdown (500 pages/mo free). Used by web_researcher
    # and SearchClient.extract_url when present; falls back to local regex strip.
    tavily_api_key: str = ""
    firecrawl_api_key: str = ""

    # Account-management infrastructure — all optional.
    # Without these, _LiveAccounts falls back to _NoopAccounts so existing
    # behaviour is unchanged. Operator setup:
    #   1. Buy a domain (~$10/yr) and enable Cloudflare Email Routing free tier
    #   2. Generate vault key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    #   3. Create a company-type Issuing cardholder once in Stripe dashboard;
    #      copy the ich_... id into STRIPE_ISSUING_CARDHOLDER_ID
    # Portfolio operator: hard cap on concurrent active hypotheses.
    # 3 is the realistic ceiling at free-tier LLM scale; raise to 5-10 on paid
    # tier. Setting to 1 reverts to single-hypothesis behaviour.
    max_active_hypotheses: int = Field(default=3, ge=1, le=20)

    # Swarm Phase Z1 — `business` is the unit of selection. Hard cap on
    # concurrent active businesses. 8 is the realistic ceiling at free-tier
    # LLM scale (NIM 240 RPM / 6 keys, bursty cycles); raise to 30+ on paid
    # tier. Selection pressure compounds via template inheritance.
    max_active_businesses: int = Field(default=8, ge=1, le=50)

    # Seed budget per spawned business (£). Low default — the swarm should
    # earn its way to bigger budgets via fitness, not be born rich.
    business_seed_budget_gbp: float = Field(default=1.0, ge=0.0, le=100.0)

    # Genome graduation threshold: a business's genome enters the template
    # pool once it cumulatively earns this much. Templates seed future spawns.
    business_template_graduation_gbp: float = Field(default=50.0, ge=1.0, le=10_000.0)

    # Swarm Phase Z2 — SwarmController loop intervals + kill thresholds.
    # Spawn at ~5/week (33h interval). Cull every 6h — needs higher cadence
    # than spawn so dying businesses free slots before the next spawn tick.
    swarm_spawn_interval_s: float = Field(default=33 * 3600, ge=60.0, le=604_800.0)
    swarm_cull_interval_s: float = Field(default=6 * 3600, ge=60.0, le=86_400.0)
    # Emergency stop — halts spawn loop without container restart.
    swarm_freeze: bool = False

    # Z2.5b — per-business LLM cycle cadence. With cap=8 and 30min interval,
    # each business cycles every ~4h on round-robin. Adjust down for
    # higher iteration speed (watch NIM rate limits).
    business_cycle_interval_s: float = Field(default=1800.0, ge=60.0, le=86_400.0)
    # Cycles without an artifact before kill clock shortens
    business_artifact_stall_threshold: int = Field(default=3, ge=1, le=20)
    # Probation: zero £ past this age → kill. Hard kill: <£5 past this age.
    swarm_probation_days: float = Field(default=14.0, ge=1.0, le=365.0)
    swarm_hard_kill_days: float = Field(default=21.0, ge=1.0, le=365.0)
    # 0.7 = 70% of spawns sampled from templates (when available), 30% fresh seeds.
    swarm_template_sample_weight: float = Field(default=0.7, ge=0.0, le=1.0)

    # Capital integration — operator-gated graduation from Stripe test mode.
    # Until stripe_live_mode_enabled is True AND both caps > 0, _LivePayments
    # refuses any live-mode spend. Test-mode keys bypass these gates entirely.
    stripe_live_mode_enabled: bool = False
    capital_daily_cap_gbp: float = Field(default=0.0, ge=0.0, le=10000.0)
    capital_weekly_cap_gbp: float = Field(default=0.0, ge=0.0, le=50000.0)
    capital_freeze: bool = False  # emergency kill — halts ALL authorizations when True

    accounts_vault_key: str = ""
    accounts_db_path: str = "data/accounts.db"
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    email_domain: str = ""
    stripe_issuing_cardholder_id: str = ""

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
