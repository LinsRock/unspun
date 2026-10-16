from fastapi import APIRouter, Depends

from unspun.api.admin.auth import require_admin_identity
from unspun.api.admin.configuration import router as configuration_router
from unspun.api.admin.content import router as content_router
from unspun.api.admin.costs import router as costs_router
from unspun.api.admin.expenses import router as expenses_router
from unspun.api.admin.exports import router as exports_router
from unspun.api.admin.overview import router as overview_router
from unspun.api.admin.r1 import router as r1_router
from unspun.api.admin.ranges import router as ranges_router
from unspun.api.admin.runs import router as runs_router
from unspun.api.admin.sources import router as sources_router

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin_identity)]
)
router.include_router(ranges_router)
router.include_router(exports_router)
router.include_router(sources_router)
router.include_router(content_router)
router.include_router(runs_router)
router.include_router(configuration_router)
router.include_router(expenses_router)
router.include_router(costs_router)
router.include_router(overview_router)
router.include_router(r1_router)
