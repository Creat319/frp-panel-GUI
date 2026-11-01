"""惰性图标包：替换组件库自带的那份实现。

组件库的 ``GlobalIconPack`` 在导入时会把三个图标包文件（共 7 MB 的 SVG 文本、
5410 个图标）一次性读进内存并常驻。本程序只用其中二三十个图标，非常浪费。

这里的实现：

* 启动时只扫一遍文件，记下「图标名 → (文件, 字节偏移, 长度)」的索引（约 0.6 MB）；
* 真正用到某个图标时，才按偏移 seek 读那一行，并缓存下来；
* 对外接口（``get`` / ``toPixmap`` / ``toIcon`` / ``icons`` / ``getDict`` …）与原版一致。

用法见 ``bootstrap.install_lazy_iconpack()``：在 ``import siui`` 之前把这个模块
塞进 ``sys.modules["siui.gui.icons.parser"]``，组件库就会直接用这里的类。
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

COLOR_PLACEHOLDER = "<<<COLOR_CODE>>>"


class LazyIconDict(Mapping):
    """看起来像一个 ``{名字: SVG 文本}`` 的字典，实际按需读文件。"""

    def __init__(self, pack: "GlobalIconPack", names: set[str] | None = None) -> None:
        self._pack = pack
        self._names = names  # None 表示全部图标

    def _keys(self) -> Iterator[str]:
        if self._names is None:
            return iter(self._pack.index)
        return iter(self._names)

    def __iter__(self) -> Iterator[str]:
        return self._keys()

    def __len__(self) -> int:
        return len(self._pack.index) if self._names is None else len(self._names)

    def __contains__(self, name: object) -> bool:
        if self._names is not None and name not in self._names:
            return False
        return name in self._pack.index

    def __getitem__(self, name: str) -> str:
        if name not in self:
            raise KeyError(name)
        return self._pack.svgSource(name)


class GlobalIconPack:
    """与组件库同名同接口的惰性实现。"""

    current_module_path = os.path.dirname(os.path.abspath(__file__))

    def __init__(self) -> None:
        self.default_color = None
        self.index: dict[str, tuple[str, int, int]] = {}
        self.classified: dict[str, set[str]] = {"__unclassified__": set()}
        self._cache: dict[str, str] = {}
        self._package_folder = self._find_package_folder()
        self.reload_internals()

        self.icons: Mapping = LazyIconDict(self)
        self.icons_classified: dict[str, Mapping] = {
            "__unclassified__": LazyIconDict(self, self.classified["__unclassified__"])
        }

    # ------------------------------------------------------------ 路径与索引

    def _find_package_folder(self) -> str:
        """找到图标包目录：优先组件库自带的位置，找不到就退回到本模块目录。"""
        candidates = []
        try:
            import siui

            candidates.append(os.path.join(os.path.dirname(os.path.abspath(siui.__file__)),
                                           "gui", "icons", "packages"))
        except Exception:  # noqa: BLE001
            pass
        candidates.append(os.path.join(self.current_module_path, "gui", "icons", "packages"))
        candidates.append(os.path.join(self.current_module_path, "siui", "gui", "icons", "packages"))
        for path in candidates:
            if os.path.isdir(path):
                return path
        return candidates[0]

    def packageFolderPath(self) -> str:
        return self._package_folder

    def reload_internals(self) -> None:
        """扫一遍图标包目录，建立「名字 → 位置」索引（不读内容）。"""
        self.index.clear()
        for name in list(self.classified):
            if name != "__unclassified__":
                self.classified[name] = set()

        folder = self._package_folder
        if not os.path.isdir(folder):
            return
        for filename in sorted(os.listdir(folder)):
            path = os.path.join(folder, filename)
            if os.path.isfile(path):
                self._index_file(path, filename)

    def _index_file(self, path: str, class_name: str) -> None:
        self.classified.setdefault(class_name, set())
        with open(path, "rb") as handle:
            while True:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if line.startswith(b"##") or not line.strip():
                    continue
                head, _, _tail = line.partition(b"////")
                try:
                    name = head.decode("utf-8").strip()
                except UnicodeDecodeError:
                    continue
                if not name:
                    continue
                self.index[name] = (path, offset, len(line))
                self.classified[class_name].add(name)

    def load_from_file(self, path: str) -> None:
        self._index_file(path, os.path.basename(path))

    def append_class(self, class_name: str, force: bool = False) -> None:
        if class_name in self.classified and not force:
            raise ValueError(f"Class name {class_name} is already exist.")
        self.classified[class_name] = set()

    def append(self, name: str, data: str, class_name: str = "__unclassified__") -> None:
        """直接塞入一份图标数据（正常流程用不到，保持接口兼容）。"""
        self._cache[name] = data
        self.classified.setdefault(class_name, set()).add(name)
        self.index.setdefault(name, ("", 0, 0))

    # ------------------------------------------------------------ 读取

    def svgSource(self, name: str) -> str:
        """取图标的原始 SVG 文本（带颜色占位符），带缓存。"""
        cached = self._cache.get(name)
        if cached is not None:
            return cached

        entry = self.index.get(name)
        if entry is None:
            raise KeyError(name)

        path, offset, length = entry
        try:
            with open(path, "rb") as handle:
                handle.seek(offset)
                line = handle.read(length).decode("utf-8", errors="replace")
            _head, _sep, data = line.partition("////")
            data = data.rstrip("\r\n")
        except OSError:
            data = ""

        self._cache[name] = data
        return data

    # ------------------------------------------------------------ 对外接口

    def setDefaultColor(self, code: str) -> None:
        self.default_color = code

    @property
    def defaultColor(self) -> str | None:
        return self.default_color

    def get(self, name: str, color_code: str | None = None) -> bytes:
        color_code = self.default_color if color_code is None else color_code
        return self.svgSource(name).replace(COLOR_PLACEHOLDER, str(color_code)).encode()

    def getFromData(self, data: str, color_code: str | None = None) -> bytes:
        color_code = self.default_color if color_code is None else color_code
        return data.replace(COLOR_PLACEHOLDER, str(color_code)).encode()

    def getByteArray(self, name: str, color_code: str | None = None):
        from PyQt5.QtCore import QByteArray

        return QByteArray(self.get(name, color_code))

    def getDict(self, class_name: str | None = None) -> Mapping:
        if class_name is None:
            return self.icons
        return self.icons_classified[class_name]

    def getClassNames(self):
        return self.icons_classified.keys()

    def toPixmap(self, name: str, size=None, color_code: str | None = None) -> QPixmap:
        from PyQt5.QtCore import QSize

        size = size or QSize(64, 64)
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        renderer = QSvgRenderer(self.get(name, color_code))
        renderer.render(painter)
        painter.end()
        return pixmap

    def toIcon(self, name: str, size=None, color_code: str | None = None) -> QIcon:
        return QIcon(self.toPixmap(name, size, color_code))
