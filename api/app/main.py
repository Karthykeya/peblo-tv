from fastapi import FastAPI

app = FastAPI(title="Peblo TV API")

@app.get("/health")
def health():
    return {"status": "ok"}
