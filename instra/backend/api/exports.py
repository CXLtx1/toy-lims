"""导出 API：XRF 定量/UniQuant xlsx、UniQuant PDF。"""

import io
from typing import Literal, Optional

from flask import Blueprint, g, jsonify, request, send_file
from pydantic import BaseModel, Field, ValidationError

from api.xrf import load_uq_detail
from export import uq_pdf, xlsx_export

bp = Blueprint("exports", __name__)


Unit = Literal["%", "ppm", "ppb"]
OrderMode = Literal["template", "content"]


class ExportSettings(BaseModel):
    units: dict[str, Unit] = Field(default_factory=dict)
    significant_digits: int = Field(default=5, ge=1, le=8)


class XlsxParams(ExportSettings):
    ids: list[int] = Field(min_length=1, max_length=200)
    order_template_id: Optional[int] = None
    order_mode: OrderMode = "template"


class UqXlsxParams(XlsxParams):
    basis: Literal["element", "oxide"] = "element"
    order_mode: OrderMode = "content"


class UqPdfParams(ExportSettings):
    id: int
    order_template_id: Optional[int] = None
    order_mode: OrderMode = "content"


class UnitFieldsParams(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    kind: Literal["quant", "uq"]
    order_template_id: Optional[int] = None
    order_mode: Optional[OrderMode] = None


def _parse(model):
    try:
        return model(**(request.get_json(silent=True) or {})), None
    except ValidationError as exc:
        return None, (jsonify(ok=False, error="导出参数无效",
                              detail=exc.errors(include_url=False)), 400)


def _send(data, filename, mimetype):
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True,
                     download_name=filename)


@bp.post("/export/xrf/quant.xlsx")
def export_quant_xlsx():
    params, error = _parse(XlsxParams)
    if error:
        return error
    try:
        data = xlsx_export.build_quant_xlsx(
            g.db, params.ids, params.order_template_id,
            params.units, params.significant_digits, params.order_mode)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 404
    return _send(data, xlsx_export.quant_filename(),
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.post("/export/xrf/uq.xlsx")
def export_uq_xlsx():
    params, error = _parse(UqXlsxParams)
    if error:
        return error
    try:
        data = xlsx_export.build_uq_xlsx(
            g.db, params.ids, params.basis, params.order_template_id,
            params.units, params.significant_digits, params.order_mode)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 404
    return _send(data, xlsx_export.uq_filename(params.basis),
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.post("/export/xrf/uq.pdf")
def export_uq_pdf():
    params, error = _parse(UqPdfParams)
    if error:
        return error
    item = load_uq_detail(g.db, params.id)
    if item is None:
        return jsonify(ok=False, error="UniQuant 分析不存在"), 404
    try:
        data = uq_pdf.build_uq_pdf(
            g.db, item, params.order_template_id,
            params.units, params.significant_digits, params.order_mode)
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 500
    return _send(data, uq_pdf.uq_pdf_filename(item), "application/pdf")


@bp.post("/export/xrf/unit-fields")
def export_unit_fields():
    params, error = _parse(UnitFieldsParams)
    if error:
        return error
    items = xlsx_export.load_unit_fields(
        g.db, params.ids, params.kind, params.order_template_id,
        params.order_mode or ("content" if params.kind == "uq" else "template"))
    return jsonify(ok=True, items=items)
