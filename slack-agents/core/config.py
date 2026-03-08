"""
Central configuration for the agent system.
All tunable parameters in one place.

Usage:
    from core.config import config
    interval = config.intervals.collector   # 600
    channel  = config.channels.general      # "ai-agents-general"

This module is importable but NOT required -- existing code continues to
work with its own hardcoded defaults until it is gradually migrated.
"""
from dataclasses import dataclass, field


@dataclass
class AgentIntervals:
    """Loop intervals for each agent (seconds)."""
    collector: int = 600       # 10 minutes
    curator: int = 900         # 15 minutes
    proactive: int = 90        # 1.5 minutes
    quote: int = 60            # 1 minute (checks, fires on the hour)
    invest: int = 3600         # 1 hour (genetic-algo evolution)
    investment: int = 600      # 10 minutes (market monitoring)


@dataclass
class SlackChannels:
    """Default Slack channel names used across the system."""
    general: str = "ai-agents-general"
    collector: str = "ai-collector"
    curator: str = "ai-curator"
    logs: str = "ai-agent-logs"
    quote: str = "\uba85\uc5b8"       # "명언"
    invest: str = "ai-invest"


@dataclass
class WatchdogConfig:
    """Master watchdog / health-check parameters."""
    health_check_interval: int = 3600   # 1 hour
    heartbeat_timeout: int = 900       # 15 minutes -- no heartbeat => warning
    max_restarts: int = 50             # overnight crash-restart budget


@dataclass
class DevRunnerConfig:
    """Parameters for the Claude Code CLI dev-runner."""
    timeout: int = 300                 # 5 minutes
    max_output_length: int = 3000      # truncate stdout beyond this
    summary_max_length: int = 1500     # AI summary target length


@dataclass
class CuratorConfig:
    """Curator agent tuning knobs."""
    max_articles: int = 20             # articles considered per cycle
    score_threshold: float = 0.6       # minimum relevance score
    max_selected: int = 3              # max articles per briefing


@dataclass
class InvestmentConfig:
    """Investment agent parameters."""
    alert_threshold: float = 5.0       # 24h change % to trigger alert
    briefing_hours: tuple = (8, 21)    # KST hours for scheduled briefings


@dataclass
class SelfMemoryLimits:
    """Retention limits for SelfMemory categories."""
    insights: int = 200
    evaluations: int = 200
    failure_lessons: int = 100
    action_items: int = 50
    hourly_checks: int = 48            # ~2 days
    daily_logs: int = 30               # ~1 month


@dataclass
class SecurityConfig:
    """Security settings for the dev-runner and CLI invocations."""
    allowed_cwd: str = "/home/user/yhmemo"
    max_prompt_length: int = 10000
    blocked_patterns: list = field(default_factory=lambda: [
        "rm -rf /", "sudo ", "chmod 777", "curl | bash",
        "wget | sh", "eval(", "exec(", "__import__",
        "os.system", "subprocess.call", "DROP TABLE",
        "DELETE FROM", "; rm ", "&&rm ", "| rm ",
    ])


@dataclass
class SlackPollingConfig:
    """Slack client polling parameters."""
    poll_interval: float = 30.0        # seconds between poll cycles
    thread_poll_interval: float = 10.0 # seconds between thread polls
    max_tracked_threads: int = 20      # per channel


@dataclass
class Config:
    """Top-level configuration aggregating all sub-configs."""
    intervals: AgentIntervals = field(default_factory=AgentIntervals)
    channels: SlackChannels = field(default_factory=SlackChannels)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    dev_runner: DevRunnerConfig = field(default_factory=DevRunnerConfig)
    curator: CuratorConfig = field(default_factory=CuratorConfig)
    investment: InvestmentConfig = field(default_factory=InvestmentConfig)
    self_memory_limits: SelfMemoryLimits = field(default_factory=SelfMemoryLimits)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    slack_polling: SlackPollingConfig = field(default_factory=SlackPollingConfig)


# Singleton -- import and use directly:
#   from core.config import config
config = Config()
