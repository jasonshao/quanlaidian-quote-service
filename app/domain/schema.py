from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class QuoteForm(BaseModel):
    """Input: quotation request form from OpenClaw"""
    客户品牌名称: str
    餐饮类型: str  # "轻餐" or "正餐"
    门店数量: int = Field(ge=1, le=30)
    门店套餐: str
    门店增值模块: list[str] = Field(default_factory=list)
    总部模块: list[str] = Field(default_factory=list)
    配送中心数量: int = Field(default=0, ge=0)
    生产加工中心数量: int = Field(default=0, ge=0)
    成交价系数: Optional[float] = Field(default=None, ge=0.01, le=1.0)
    人工改价原因: Optional[str] = None
    是否启用阶梯报价: bool = False
    实施服务类型: Optional[str] = None
    实施服务人天: int = Field(default=0, ge=0)

    @field_validator("实施服务类型", "人工改价原因", mode="before")
    @classmethod
    def normalize_empty_string_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v


class QuoteItemPreview(BaseModel):
    """Single line item in quote preview"""
    name: str
    qty: int
    list: int       # list price
    final: int      # discounted price


class QuoteTotals(BaseModel):
    list: int
    final: int


class QuotePreview(BaseModel):
    brand: str
    meal_type: str
    stores: int
    package: str
    discount: float
    totals: QuoteTotals
    items: list[QuoteItemPreview]


class FileRef(BaseModel):
    url: str
    filename: str
    expires_at: datetime


class QuoteResponse(BaseModel):
    request_id: str
    preview: QuotePreview
    files: dict[str, FileRef]
    pricing_version: str


class ApprovalState(BaseModel):
    required: bool
    state: str  # not_required | pending | approved | rejected
    reasons: list[str] = Field(default_factory=list)
    decided_by: Optional[str] = None
    decision_reason: Optional[str] = None
    decided_at: Optional[str] = None


class QuoteCreated(BaseModel):
    """Response of POST /v1/quotes — pricing only, no files."""
    request_id: str
    quote_id: str
    preview: QuotePreview
    approval: ApprovalState
    pricing_version: str


class QuoteDetail(BaseModel):
    """Response of GET /v1/quotes/{id}."""
    quote_id: str
    org: str
    preview: QuotePreview
    approval: ApprovalState
    renders: dict[str, FileRef] = Field(default_factory=dict)
    pricing_version: str
    created_at: str


class QuoteItemBreakdown(BaseModel):
    name: str
    category: str
    module_category: str
    unit: str
    qty: int
    list_price: int
    unit_price: int
    subtotal: int
    cost_unit_price: int
    cost_subtotal: int
    profit: int
    margin_pct: float
    protected: bool
    factor: float


class QuoteExplain(BaseModel):
    """Response of POST /v1/quotes/{id}/explain — per-item cost/profit breakdown."""
    quote_id: str
    items: list[QuoteItemBreakdown]
    totals: QuoteTotals
    pricing_info: dict
    internal_financials: dict


class ErrorDetail(BaseModel):
    code: str
    field: Optional[str] = None
    message: str
    hint: Optional[str] = None
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
