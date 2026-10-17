from app.agents.base import StructuredAgent
from app.schemas import BusinessPlan, PlanRequest


class BusinessPlanAgent(StructuredAgent[PlanRequest, BusinessPlan]):
    name = "business_plan"
    result_type = BusinessPlan

    def user_content(self, request: PlanRequest) -> str:
        return request.instruction
