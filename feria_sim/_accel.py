# -*- coding: utf-8 -*-
"""Опціональний шар прискорення й валідації (orjson, numpy, lxml, shapely, pydantic).

Усі функції мають 100% еквівалентний stdlib-фолбек, тому проєкт працює
як із додатковими бібліотеками (`pip install .[all]`), так і на голому Python 3.12+.
"""
import json
import math

try:
    import orjson as _orjson
    HAS_ORJSON = True
except ImportError:
    _orjson = None
    HAS_ORJSON = False

try:
    import numpy as _np
    HAS_NUMPY = True
except ImportError:
    _np = None
    HAS_NUMPY = False

try:
    from lxml import etree as _lxml_etree
    HAS_LXML = True
except ImportError:
    _lxml_etree = None
    HAS_LXML = False

try:
    import shapely as _shapely
    from shapely.geometry import LineString as _LineString, Point as _Point, Polygon as _Polygon
    from shapely.ops import polygonize as _polygonize, unary_union as _unary_union
    HAS_SHAPELY = True
except ImportError:
    _shapely = None
    _LineString = _Point = _Polygon = _polygonize = _unary_union = None
    HAS_SHAPELY = False

try:
    import pydantic as _pydantic
    HAS_PYDANTIC = True
except ImportError:
    _pydantic = None
    HAS_PYDANTIC = False


def capabilities():
    """Статус підключених опціональних бібліотек."""
    return dict(
        orjson=HAS_ORJSON,
        numpy=HAS_NUMPY,
        lxml=HAS_LXML,
        shapely=HAS_SHAPELY,
        pydantic=HAS_PYDANTIC,
    )


def assert_finite(obj):
    """Швидка ітеративна перевірка, що у структурі немає NaN або +/-Inf (еквівалент allow_nan=False)."""
    _float = float
    _dict = dict
    _list = list
    _tuple = tuple
    _isfinite = math.isfinite
    stack = [obj]
    while stack:
        cur = stack.pop()
        t = type(cur)
        if t is _float:
            if not _isfinite(cur):
                raise ValueError(f"Out of range float values are not JSON compliant: {cur!r}")
        elif t is _dict:
            stack.extend(cur.values())
        elif t is _list or t is _tuple:
            stack.extend(cur)


def json_loads(raw, use_orjson=True):
    """Десеріалізація JSON із байтів або рядка через orjson (за наявності) чи stdlib json."""
    if use_orjson and HAS_ORJSON:
        return _orjson.loads(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def json_dumps_bytes(obj, *, allow_nan=False, compact=True, non_str_keys=True, use_orjson=True):
    """Швидка серіалізація JSON у байти зі збереженням суворої заборони NaN/Inf."""
    if use_orjson and HAS_ORJSON:
        if not allow_nan:
            assert_finite(obj)
        opts = 0
        if non_str_keys:
            opts |= _orjson.OPT_NON_STR_KEYS
        if not compact:
            opts |= _orjson.OPT_INDENT_2
        return _orjson.dumps(obj, option=opts)
    seps = (",", ":") if compact else None
    indent = None if compact else 2
    return json.dumps(obj, ensure_ascii=False, separators=seps, indent=indent, allow_nan=allow_nan).encode("utf-8")


def np_weighted_ratio_mean(ratios, weights, use_numpy=True):
    """Зважене середнє цінового індексу; при великих масивах прискорюється через numpy."""
    n = len(ratios)
    if n == 0:
        return 1.0
    if use_numpy and HAS_NUMPY and n >= 16:
        r_arr = _np.asarray(ratios, dtype=_np.float64)
        w_arr = _np.asarray(weights, dtype=_np.float64)
        wtot = float(_np.sum(w_arr))
        if wtot > 0.0:
            return float(_np.dot(r_arr, w_arr) / wtot)
        return 1.0
    wsum = 0.0
    wtot = 0.0
    for r, w in zip(ratios, weights, strict=True):
        wsum += r * w
        wtot += w
    return wsum / wtot if wtot > 0.0 else 1.0


def pydantic_coerce_scalar(key, value, *, is_bool=False, bounds=None):
    """Опціональна типізована валідація конфігураційних полів через Pydantic v2."""
    if not HAS_PYDANTIC:
        return None
    if is_bool:
        adapter = _pydantic.TypeAdapter(bool)
        try:
            return True, adapter.validate_python(value)
        except _pydantic.ValidationError:
            return False, None
    if isinstance(value, bool):
        return False, None
    try:
        num = _pydantic.TypeAdapter(float).validate_python(value)
    except _pydantic.ValidationError:
        return False, None
    if not math.isfinite(num):
        return False, None
    if bounds is not None:
        lo, hi, step = bounds
        if num < lo or num > hi:
            return False, None
        if step is not None and float(step).is_integer() and float(num).is_integer():
            return True, int(num)
    return True, num
