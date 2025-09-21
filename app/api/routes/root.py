from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/")
def read_root():
    return {"message": "Hello, World"}

@router.get("/routes")
def list_routes(request: Request):
    return [route.path for route in request.app.routes]
