from fastapi import FastAPI

app = FastAPI(title="wyb-detect")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
