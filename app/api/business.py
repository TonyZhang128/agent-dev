from fastapi import APIRouter, Request

from app.schemas import BusinessPlan, PlanRequest

router = APIRouter(prefix="/api/business", tags=["业务规划"])


@router.post("/plan", response_model=BusinessPlan, summary="生成业务步骤")
async def plan(payload: PlanRequest, request: Request):
    return await request.app.state.business_plan_agent.run(payload)
