"""External agent-infra clients. Each module is a thin httpx-based wrapper
so we don't take an SDK lock-in. All clients fail loudly when the API key
is missing — callers decide whether to fall back."""
