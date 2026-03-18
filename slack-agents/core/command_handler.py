"""
명령어 핸들러 레지스트리

슬랙 명령어(!)를 등록하고 디스패치하는 중앙 관리 모듈.
orchestrator.py에서 명령어 관련 로직을 분리하기 위한 기반.

현재는 명령어 등록/조회 유틸리티로, 점진적 마이그레이션에 사용.
"""
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Any

logger = logging.getLogger("command_handler")


@dataclass
class CommandInfo:
    """명령어 메타데이터"""
    name: str
    handler: Callable[..., Awaitable[Any]]
    description: str = ""
    usage: str = ""
    aliases: list[str] = field(default_factory=list)
    category: str = "일반"  # 일반, 투자, 관리, 개발


class CommandRegistry:
    """명령어 등록소 - 모든 슬랙 명령어를 한 곳에서 관리

    Usage:
        registry = CommandRegistry()
        registry.register("수집", cmd_collect, description="뉴스 수집", usage="!수집 키워드")

        # 명령어 실행
        handler = registry.get("수집")
        if handler:
            await handler(args, user, channel, thread_ts)

        # 도움말 생성
        help_text = registry.get_help()
    """

    def __init__(self):
        self._commands: dict[str, CommandInfo] = {}
        self._aliases: dict[str, str] = {}  # 별칭 → 원래 이름

    def register(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
        description: str = "",
        usage: str = "",
        aliases: list[str] = None,
        category: str = "일반",
    ):
        """명령어 등록"""
        info = CommandInfo(
            name=name,
            handler=handler,
            description=description,
            usage=usage or f"!{name}",
            aliases=aliases or [],
            category=category,
        )
        self._commands[name] = info

        # 별칭 등록
        for alias in info.aliases:
            self._aliases[alias] = name

        logger.debug(f"명령어 등록: !{name} ({category})")

    def get(self, name: str) -> Callable[..., Awaitable[Any]] | None:
        """이름 또는 별칭으로 핸들러 조회"""
        # 직접 이름
        if name in self._commands:
            return self._commands[name].handler
        # 별칭
        if name in self._aliases:
            original = self._aliases[name]
            return self._commands[original].handler
        return None

    def get_info(self, name: str) -> CommandInfo | None:
        """명령어 메타데이터 조회"""
        if name in self._commands:
            return self._commands[name]
        if name in self._aliases:
            return self._commands[self._aliases[name]]
        return None

    def list_commands(self, category: str = None) -> list[CommandInfo]:
        """등록된 명령어 목록 (카테고리별 필터 가능)"""
        commands = list(self._commands.values())
        if category:
            commands = [c for c in commands if c.category == category]
        return sorted(commands, key=lambda c: c.name)

    def get_help(self) -> str:
        """전체 도움말 텍스트 생성"""
        lines = ["*📋 사용 가능한 명령어*\n"]
        categories = {}
        for cmd in self._commands.values():
            categories.setdefault(cmd.category, []).append(cmd)

        for cat, cmds in sorted(categories.items()):
            lines.append(f"*[{cat}]*")
            for cmd in sorted(cmds, key=lambda c: c.name):
                alias_str = f" (별칭: {', '.join('!' + a for a in cmd.aliases)})" if cmd.aliases else ""
                lines.append(f"  `{cmd.usage}` — {cmd.description}{alias_str}")
            lines.append("")

        return "\n".join(lines)

    @property
    def count(self) -> int:
        return len(self._commands)
