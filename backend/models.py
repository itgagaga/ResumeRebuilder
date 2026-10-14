import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Style(Model):
    fontFamily: str = "Arial, Microsoft YaHei, sans-serif"
    fontSize: float = Field(default=12, ge=1, le=500)
    fontScaleX: float = Field(default=1, ge=0.4, le=2)
    fontWeight: int = Field(default=400, ge=100, le=900)
    fontStyle: Literal["normal", "italic"] = "normal"
    color: str = "#222222"
    background: str = "transparent"
    borderColor: str = "#b8c2cc"
    borderWidth: float = Field(default=0, ge=0, le=100)
    borderRadius: float = Field(default=0, ge=0, le=10000)
    lineHeight: float = Field(default=1.15, ge=0.5, le=5)
    textAlign: Literal["left", "center", "right", "justify"] = "left"

    @field_validator("color", "background", "borderColor")
    @classmethod
    def color_safe(cls, value):
        if value != "transparent" and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("颜色必须为十六进制颜色或 transparent")
        return value

    @field_validator("fontFamily")
    @classmethod
    def font_safe(cls, value):
        if len(value) > 200 or not re.fullmatch(r"[\w\s,\-]+", value):
            raise ValueError("字体名称含非法字符")
        return value


class Crop(Model):
    scale: float = Field(default=1, ge=1, le=5)
    offsetX: float = Field(default=0, ge=-100, le=100)
    offsetY: float = Field(default=0, ge=-100, le=100)


class SourceRegion(Model):
    detectedFrom: str = Field(max_length=60)
    page: int = Field(ge=1, le=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    sourceFont: str | None = Field(default=None, max_length=200)


class TextRun(Model):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    fontWeight: int = Field(default=700,ge=100,le=900)


class Element(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    type: Literal["text", "line", "rect", "image_placeholder"]
    x: float = Field(ge=-10000, le=10000)
    y: float = Field(ge=-10000, le=10000)
    width: float = Field(gt=0, le=10000)
    height: float = Field(gt=0, le=10000)
    rotation: float = Field(default=0, ge=-360, le=360)
    zIndex: int = Field(default=1, ge=-10000, le=10000)
    text: str = Field(default="", max_length=100000)
    textRuns: list[TextRun] = Field(default_factory=list,max_length=2000)
    textLayout: Literal["auto", "wrap", "fixed", "paragraph"] = "auto"
    flowBelow: bool = True
    style: Style = Field(default_factory=Style)
    shape: Literal["rect", "circle", "rounded", "polygon"] = "rect"
    shapePoints: list[tuple[float, float]] = Field(default_factory=list, max_length=128)
    assetId: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    fit: Literal["cover", "contain"] = "cover"
    crop: Crop = Field(default_factory=Crop)
    sourceRegion: SourceRegion | None = None

    @model_validator(mode="after")
    def check_runs(self):
        if self.shape == "polygon":
            if self.type != "rect" or len(self.shapePoints) < 3 or any(not math.isfinite(v) or not 0 <= v <= 1 for point in self.shapePoints for v in point):
                raise ValueError("轮廓须为归一化坐标的闭合多边形")
        elif self.shapePoints:
            raise ValueError("只有多边形可包含轮廓坐标")
        last = 0
        for run in self.textRuns:
            if self.type != "text" or run.start < last or run.end <= run.start or run.end > len(self.text):
                raise ValueError("局部文字样式范围不合法")
            last = run.end
        return self


class Page(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    width: float = Field(gt=0, le=3000)
    height: float = Field(gt=0, le=5000)
    unit: Literal["pt", "px"] = "pt"
    background: str = "#ffffff"
    elements: list[Element] = Field(default_factory=list, max_length=5000)
    sourceType: Literal["native-pdf", "scan-pdf", "image", "blank"] = "blank"

    @field_validator("background")
    @classmethod
    def valid_color(cls, value):
        return Style.color_safe(value)


class Asset(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    filename: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}\.png$")
    width: int = Field(gt=0, le=30000)
    height: int = Field(gt=0, le=30000)
    mime: Literal["image/png"] = "image/png"


class Project(Model):
    schemaVersion: Literal["1.0.0"] = "1.0.0"
    projectId: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(max_length=150)
    pages: list[Page] = Field(min_length=1, max_length=20)
    assets: dict[str, Asset] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, max_length=200)
    referenceAvailable: bool = False

    @model_validator(mode="after")
    def valid_references(self):
        ids = [p.id for p in self.pages]
        ids += [e.id for p in self.pages for e in p.elements]
        if len(ids) != len(set(ids)):
            raise ValueError("页面或元素 ID 重复")
        if len(self.assets) > 100 or len({asset.filename for asset in self.assets.values()}) != len(self.assets):
            raise ValueError("资源数量过多或文件名重复")
        for key, asset in self.assets.items():
            if key != asset.id:
                raise ValueError("资源 ID 不匹配")
        for page in self.pages:
            for element in page.elements:
                if element.assetId and (element.type != "image_placeholder" or element.assetId not in self.assets):
                    raise ValueError("非法图片资源引用")
        return self
