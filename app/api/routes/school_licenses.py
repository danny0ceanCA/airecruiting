from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import ADMIN_ROLES
from app.core.security import get_current_user
from app.db.redis_client import redis_client
from app.services.core_utils import all_licenses, all_school_codes

router = APIRouter()

class SchoolCodeRequest(BaseModel):
    code: str
    label: str
class UpdateSchoolCodeRequest(BaseModel):
    label: str
class LicenseRequest(BaseModel):
    code: str
    label: str
class UpdateLicenseRequest(BaseModel):
    label: str

@router.get("/school-codes")
def school_codes():
    """Return available institutional codes."""
    codes = [{"code": c, "label": l} for c, l in all_school_codes().items()]
    return {"codes": codes}

@router.post("/admin/school-codes")
def add_school_code(
    req: SchoolCodeRequest, current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"school_code:{req.code}"
    if redis_client.exists(key):
        raise HTTPException(status_code=400, detail="Code already exists")
    redis_client.set(key, req.label)
    return {"message": "School code added"}

@router.put("/admin/school-codes/{code}")
def update_school_code(
    code: str, req: UpdateSchoolCodeRequest, current_user: dict = Depends(get_current_user)
):
    """Update the label for an existing school code."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"school_code:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Code not found")
    redis_client.set(key, req.label)
    return {"message": "School code updated"}

@router.delete("/admin/school-codes/{code}")
def delete_school_code(code: str, current_user: dict = Depends(get_current_user)):
    """Delete a school code."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"school_code:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Code not found")
    redis_client.delete(key)
    return {"message": "School code deleted"}

@router.get("/licenses")
def list_licenses():
    licenses = [{"code": c, "label": l} for c, l in all_licenses().items()]
    return {"licenses": licenses}

@router.post("/admin/licenses")
def add_license(req: LicenseRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"license:{req.code}"
    if redis_client.exists(key):
        raise HTTPException(status_code=400, detail="License already exists")
    redis_client.set(key, req.label)
    return {"message": "License added"}

@router.put("/admin/licenses/{code}")
def update_license(code: str, req: UpdateLicenseRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"license:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="License not found")
    redis_client.set(key, req.label)
    return {"message": "License updated"}

@router.delete("/admin/licenses/{code}")
def delete_license(code: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"license:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="License not found")
    redis_client.delete(key)
    return {"message": "License deleted"}

