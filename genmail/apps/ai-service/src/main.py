from fastapi import FastAPI

app = FastAPI(
    title="GenMail AI Service",
    description="Backend API for GenMail",
    version="1.0.0"
)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "GenMail AI Service"}
