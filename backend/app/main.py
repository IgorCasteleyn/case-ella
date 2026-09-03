from fastapi import FastAPI

app = FastAPI(title="Ella Weather API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
