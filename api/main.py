from fastapi import FastAPI, status, Depends
import uvicorn

from auth import verify_access


app = FastAPI()


@app.get("/get_proxy", status_code=status.HTTP_200_OK)
async def get_proxy(source: str, password: str = Depends(verify_access)):
    # request scheduler to get proxy for source
    return {"source": source}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
