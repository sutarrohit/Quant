from fastapi import FastAPI

app = FastAPI(
    title="Supervisor",
    description="Reserved Phase 5 supervisor surface for per-tenant LiveNode processes.",
    version="0.1.0",
)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
