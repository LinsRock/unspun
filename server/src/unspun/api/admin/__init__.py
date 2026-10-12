from fastapi import APIRouter, Depends

from unspun.api.admin.auth import require_admin_identity
from unspun.api.admin.ranges import router as ranges_router

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin_identity)]
)
router.include_router(ranges_router)
