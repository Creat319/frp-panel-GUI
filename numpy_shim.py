"""给组件库用的极简 numpy 替身。

为什么要它：组件库只拿 numpy 做「两三个元素的向量小算术」（颜色分量、动画步长、
按钮偏移），但 numpy 在 Windows 上会连带加载 20 MB 的 OpenBLAS
（``libscipy_openblas64_*.dll``）和 3.5 MB 的 ``_multiarray_umath``，
对一个挂后台的托盘程序来说太奢侈了。

这个替身实现了组件库真正用到的那部分接口（见 ``_dev/test_numpy_shim.py``
里的差分测试：同一批随机输入，替身和真 numpy 的运算结果必须一致）：

* ``array`` / ``ndarray`` / ``clip`` / ``pi`` / ``sin`` / ``int8`` ``int16`` ``float64``
* 元素级 ``+ - * / // ** %``、一元 ``-`` ``abs``、比较运算
* ``.all()`` ``.any()`` ``.tolist()`` ``len()`` 迭代 / 下标 / 切片
* 长度 1 时支持 ``float()`` / ``int()`` / ``bool()``（组件库常这么取值）

只有一维、小数组，够用就行；真要复杂的数值计算请设 ``FRP_GUI_REAL_NUMPY=1``
用回真正的 numpy。
"""

from __future__ import annotations

import math

__version__ = "0.0-shim"


def _number(value):
    """尽量保留原本的数值类型（int 还是 int，和 numpy 一致）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


class ndarray:
    """一维小数组。"""

    __slots__ = ("_data", "dtype")

    def __init__(self, data=(), dtype=None) -> None:
        if isinstance(data, ndarray):
            values = list(data._data)
        elif isinstance(data, (list, tuple)):
            values = [_number(v) for v in data]
        elif data is None:
            values = []
        else:  # 标量 -> 长度 1 的数组（对应 numpy 的 0 维）
            values = [_number(data)]
        self._data = values
        self.dtype = dtype or ("int" if all(isinstance(v, int) or isinstance(v, bool)
                                            for v in values) else "float")

    # ------------------------------------------------------------ 容器接口

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return ndarray(self._data[index])
        if isinstance(index, ndarray):  # 布尔掩码
            return ndarray([v for v, keep in zip(self._data, index._data) if keep])
        return self._data[index]

    def __setitem__(self, index, value) -> None:
        if isinstance(index, ndarray):
            for position, keep in enumerate(index._data):
                if keep:
                    self._data[position] = _number(value)
            return
        self._data[index] = _number(value)

    def __contains__(self, value) -> bool:
        return _number(value) in self._data

    def __float__(self) -> float:
        if len(self._data) != 1:
            raise TypeError("只有长度为 1 的数组能转成 float")
        return float(self._data[0])

    def __int__(self) -> int:
        if len(self._data) != 1:
            raise TypeError("只有长度为 1 的数组能转成 int")
        return int(self._data[0])

    def __index__(self) -> int:
        return int(self)

    def __round__(self, digits: int = 0):
        if len(self._data) == 1:
            return round(self._data[0], digits)
        return ndarray([round(v, digits) for v in self._data])

    def __ceil__(self):
        return math.ceil(float(self))

    def __floor__(self):
        return math.floor(float(self))

    def __bool__(self) -> bool:
        if len(self._data) == 1:
            return bool(self._data[0])
        return any(self._data)

    def __repr__(self) -> str:
        return "array([" + ", ".join(f"{v:g}" for v in self._data) + "])"

    def __hash__(self):
        return hash(tuple(self._data))

    # ------------------------------------------------------------ 归约

    def all(self) -> bool:
        return all(self._data)

    def any(self) -> bool:
        return any(self._data)

    def sum(self) -> float:
        return sum(self._data)

    def tolist(self) -> list[float]:
        return list(self._data)

    def copy(self) -> "ndarray":
        return ndarray(self._data, self.dtype)

    def astype(self, dtype) -> "ndarray":
        if str(dtype).endswith("int8") or str(dtype).endswith("int16") or str(dtype) == "int":
            return ndarray([int(v) for v in self._data], dtype)
        return ndarray(self._data, dtype)

    # ------------------------------------------------------------ 运算

    def _broadcast(self, other):
        if isinstance(other, ndarray):
            if len(other._data) == len(self._data):
                return other._data
            if len(other._data) == 1:
                return other._data * len(self._data)
            if len(self._data) == 1:
                return self._data * len(other._data)
            raise ValueError("形状不一致，替身不支持广播")
        return [_number(other)] * len(self._data)

    def _apply(self, other, op):
        others = self._broadcast(other)
        return ndarray([op(a, b) for a, b in zip(self._data, others)])

    def __add__(self, other):
        return self._apply(other, lambda a, b: a + b)

    __radd__ = __add__

    def __sub__(self, other):
        return self._apply(other, lambda a, b: a - b)

    def __rsub__(self, other):
        others = self._broadcast(other)
        return ndarray([b - a for a, b in zip(self._data, others)])

    def __mul__(self, other):
        return self._apply(other, lambda a, b: a * b)

    __rmul__ = __mul__

    def __truediv__(self, other):
        return self._apply(other, lambda a, b: a / b)

    def __rtruediv__(self, other):
        others = self._broadcast(other)
        return ndarray([b / a for a, b in zip(self._data, others)])

    def __floordiv__(self, other):
        return self._apply(other, lambda a, b: a // b)

    def __rfloordiv__(self, other):
        others = self._broadcast(other)
        return ndarray([b // a for a, b in zip(self._data, others)])

    def __mod__(self, other):
        return self._apply(other, lambda a, b: a % b)

    def __pow__(self, other):
        return self._apply(other, lambda a, b: a ** b)

    def __rpow__(self, other):
        others = self._broadcast(other)
        return ndarray([b ** a for a, b in zip(self._data, others)])

    def __neg__(self):
        return ndarray([-v for v in self._data])

    def __pos__(self):
        return self.copy()

    def __abs__(self):
        return ndarray([abs(v) for v in self._data])

    # ------------------------------------------------------------ 比较

    def __lt__(self, other):
        return self._apply(other, lambda a, b: a < b)

    def __le__(self, other):
        return self._apply(other, lambda a, b: a <= b)

    def __gt__(self, other):
        return self._apply(other, lambda a, b: a > b)

    def __ge__(self, other):
        return self._apply(other, lambda a, b: a >= b)

    def __eq__(self, other):
        return self._apply(other, lambda a, b: a == b)

    def __ne__(self, other):
        return self._apply(other, lambda a, b: a != b)


def array(data=(), dtype=None) -> ndarray:
    return ndarray(data, dtype)


def asarray(data=(), dtype=None) -> ndarray:
    return ndarray(data, dtype)


def clip(values, low=None, high=None):
    """逐元素夹紧。"""
    result = []
    for value in (values if isinstance(values, ndarray) else [values]):
        value = _number(value)
        if low is not None:
            value = max(float(low), value)
        if high is not None:
            value = min(float(high), value)
        result.append(value)
    return ndarray(result)


def sin(values):
    if isinstance(values, ndarray):
        return ndarray([math.sin(v) for v in values])
    return math.sin(values)


def cos(values):
    if isinstance(values, ndarray):
        return ndarray([math.cos(v) for v in values])
    return math.cos(values)


def sqrt(values):
    if isinstance(values, ndarray):
        return ndarray([math.sqrt(v) for v in values])
    return math.sqrt(values)


def abs_(values):  # numpy.abs 的别名
    return abs(values)


pi = math.pi
e = math.e


# dtype 占位（组件库只会把它们当标记传进来）
int8 = "int8"
int16 = "int16"
int32 = "int32"
float32 = "float32"
float64 = "float64"
bool_ = "bool"
