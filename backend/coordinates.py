def pt_to_css(value: float) -> float:
    return value * 96 / 72


def css_to_pt(value: float) -> float:
    return value * 72 / 96


def normalize_bbox(bbox, origin_x=0, origin_y=0):
    x0, y0, x1, y1 = bbox
    return dict(x=x0-origin_x, y=y0-origin_y, width=max(1, x1-x0), height=max(1, y1-y0))
