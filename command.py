"""启动命令解析。

用户在 frp-panel 网页上拿到的启动命令形如::

    frp-panel client -s b5757dac-9114-4466-9043-b98d25347bc4 -i admin.c.mc \
        --api-url http://119.29.227.224:9000 --rpc-url grpc://119.29.227.224:9001

本模块负责把它解析成可以直接运行的参数列表，并把开头的 ``frp-panel``
替换成本机的 ``./frp-panel-windows-amd64.exe``。
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

from frp_client import paths

# 去掉终端颜色控制符等 ANSI 转义序列
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")

# 命令行里可能出现的 frp-panel 可执行文件名（用于识别「哪一段是程序名」）
EXE_BASENAMES = {
    "frp-panel",
    "frp-panel.exe",
    "frp-panel-windows-amd64",
    "frp-panel-windows-amd64.exe",
    "frp-panel-windows-386",
    "frp-panel-windows-386.exe",
    "frp-panel-linux-amd64",
    "frp-panel-linux-arm64",
    "frp-panel-darwin-amd64",
    "frpp",
}

# frp-panel 支持的子命令
SUBCOMMANDS = {
    "client",
    "completion",
    "help",
    "install",
    "join",
    "master",
    "restart",
    "server",
    "start",
    "stop",
    "uninstall",
    "upgrade",
    "version",
}


class CommandParseError(ValueError):
    """启动命令无法解析时抛出，message 会直接展示给用户。"""


def clean_text(text: str) -> str:
    """清理用户粘贴的文本：去掉 ANSI 控制符、换行、续行符。"""
    text = ANSI_ESCAPE_RE.sub("", text or "")
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # Windows 命令提示符里用 ^ 续行，Linux 用 \ 续行，粘贴过来都会变成多余字符
    text = re.sub(r"[\^\\]\s*$", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokenize(text: str) -> list[str]:
    """把命令行切成参数列表，尽量兼容各种引号写法。"""
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = shlex.split(text, posix=False)
        tokens = [token.strip("\"'") for token in tokens]

    # 去掉误粘进来的多余符号
    cleaned = []
    for token in tokens:
        token = token.strip()
        if token in {"\\", "^", "`"}:
            continue
        if token:
            cleaned.append(token)
    return cleaned


def _basename(token: str) -> str:
    return token.replace("\\", "/").rstrip("/").split("/")[-1].lower()


def _is_exe_token(token: str) -> bool:
    base = _basename(token)
    if base in EXE_BASENAMES:
        return True
    # 兜底：任意路径下的 frp-panel* 可执行文件
    return base.startswith("frp-panel") or base.startswith("frpp")


def _option_value(args: list[str], names: tuple[str, ...]) -> str | None:
    """从参数列表里取出某个选项的值，同时支持 ``--opt value`` 与 ``--opt=value``。"""
    for index, arg in enumerate(args):
        for name in names:
            if arg == name and index + 1 < len(args):
                return args[index + 1]
            if arg.startswith(name + "="):
                return arg[len(name) + 1:]
    return None


def _quote(arg: str) -> str:
    if arg == "" or re.search(r"[\s\"'&|<>^]", arg):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg


@dataclass
class ClientCommand:
    """解析完成的启动命令。"""

    exe_path: str
    display_exe: str
    args: list[str]
    raw: str = ""
    client_id: str | None = None
    secret: str | None = None
    api_url: str | None = None
    rpc_url: str | None = None
    join_token: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def argv(self) -> list[str]:
        """真正交给 subprocess 的参数列表。"""
        return [self.exe_path, *self.args]

    @property
    def display(self) -> str:
        """界面上展示的命令行（与用户给出的写法保持一致）。"""
        return " ".join([self.display_exe, *[_quote(arg) for arg in self.args]])

    @property
    def panel_url(self) -> str | None:
        """由 api-url 推出网页上「客户端」列表页的地址。"""
        if not self.api_url:
            return None
        base = self.api_url.rstrip("/")
        if base.endswith("/api"):
            base = base[: -len("/api")]
        return f"{base}/clients"

    def summary(self) -> str:
        if self.client_id:
            return f"客户端 {self.client_id}"
        return "客户端命令已就绪"


def parse_command(text: str,
                  exe_path: str | None = None,
                  display_exe: str | None = None) -> ClientCommand:
    """把网页上复制的启动命令转换成可以执行的命令对象。

    :raises CommandParseError: 命令为空、缺少关键参数或无法识别时
    """
    exe_path = exe_path or str(paths.FRP_EXE)
    display_exe = display_exe or paths.FRP_EXE_DISPLAY

    cleaned = clean_text(text)
    if not cleaned:
        raise CommandParseError("请先粘贴从 frp-panel 网页复制的启动命令。")

    tokens = _tokenize(cleaned)
    if not tokens:
        raise CommandParseError("没有解析出任何命令内容，请重新复制启动命令。")

    # 1. 找到程序名那一段
    exe_index = next((i for i, token in enumerate(tokens) if _is_exe_token(token)), None)

    if exe_index is not None:
        args = tokens[exe_index + 1:]
    else:
        args = list(tokens)

    if not args:
        raise CommandParseError(
            "命令里只有程序名，缺少 client 等参数，请到网页重新复制完整的「启动命令」。")

    # 2. 规范化子命令，保证是 `... client <参数>`
    if args[0] not in SUBCOMMANDS:
        if "client" in args:
            args = args[args.index("client"):]
        else:
            args = ["client", *args]

    if args[0] != "client":
        raise CommandParseError(
            f"这条命令的子命令是 {args[0]!r}，本工具只负责启动内网穿透客户端（client）。")

    # 3. 关键参数校验
    secret = _option_value(args, ("-s", "--secret"))
    join_token = _option_value(args, ("-j", "--join-token"))
    if not secret and not join_token:
        raise CommandParseError(
            "命令里找不到 -s/--secret（客户端密钥），请到网页重新复制完整的启动命令。")

    command = ClientCommand(
        exe_path=exe_path,
        display_exe=display_exe,
        args=args,
        raw=cleaned,
        client_id=_option_value(args, ("-i", "--id")),
        secret=secret,
        api_url=_option_value(args, ("--api-url",)),
        rpc_url=_option_value(args, ("--rpc-url",)),
        join_token=join_token,
    )

    if command.api_url is None:
        command.notes.append("命令里没有 --api-url，程序会使用默认的面板地址。")
    if command.rpc_url is None:
        command.notes.append("命令里没有 --rpc-url，若无法连接请在网页重新复制命令。")

    return command


def masked_display(command: ClientCommand) -> str:
    """把密钥打码后的命令，用于日志展示。"""
    display = command.display
    for value in (command.secret, command.join_token):
        if value:
            display = display.replace(value, value[:8] + "…" if len(value) > 8 else "…")
    return display
