from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-only-secret-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""

    rescore_interval_minutes: int = 5

    audit_log_path: str = "audit.log"

    # --- Traffic Correlation Engine (Technical Architecture §3.5) ---
    # Capture. Live tshark is opt-in; with it disabled and no PCAP path the
    # engine seeds deterministic demo fixtures so /traffic/* works out of the box.
    traffic_capture_enabled: bool = False
    tshark_path: str = "tshark"
    tshark_interface: str = ""
    tshark_capture_filter: str = "tcp port 8333"
    pcap_replay_path: str = ""

    # Correlation window + memory bound.
    traffic_window_seconds: int = 60
    traffic_max_events: int = 50_000

    # Burst detection: score ramps from 0 at `baseline` events/sec to 1 at
    # `baseline * threshold_ratio`.
    traffic_burst_baseline_rate: float = 2.0
    traffic_burst_threshold_ratio: float = 3.0

    # Peers closer together than this are treated as "near-simultaneous"
    # observations for broadcast-timing / propagation analysis.
    traffic_near_simultaneous_ms: float = 60.0
    # Typical honest fan-out; observed peer counts above this raise irregularity.
    traffic_expected_fanout: int = 8

    # Explainable anomaly score = weighted sum of the four features.
    traffic_weight_broadcast_timing: float = 0.20
    traffic_weight_burst: float = 0.30
    traffic_weight_peer_concentration: float = 0.25
    traffic_weight_propagation_irregularity: float = 0.25

    # --- SentriX AI assistant ---
    # `mock` (default) needs no key and routes over the real SentriX tools.
    # `openai` calls an OpenAI-compatible chat-completions API (set AI_BASE_URL
    # for Azure / local / other gateways). AI_API_KEY never leaves the backend.
    ai_enabled: bool = True
    ai_provider: str = "mock"
    ai_model: str = "gpt-4o-mini"
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_temperature: float = 0.2
    ai_max_tokens: int = 1200
    ai_timeout_seconds: float = 30.0
    ai_max_tool_calls: int = 5
    ai_max_context_items: int = 20
    ai_history_limit: int = 12
    # Gemini only: extended-thinking token budget. 0 disables it (fastest);
    # -1 leaves the model's dynamic default on.
    ai_thinking_budget: int = 0

    # --- CoinGecko market data (powers the assistant's live-price tools) ---
    # Free "Demo" plan by default (https://api.coingecko.com/api/v3, the
    # x-cg-demo-api-key header). Set COINGECKO_PRO=true for a paid key.
    # The key lives only in backend/.env; blank => the market-data tools report
    # "not configured" and the rest of the assistant is unaffected.
    coingecko_api_key: str = ""
    coingecko_pro: bool = False
    coingecko_timeout_seconds: float = 6.0


settings = Settings()
