"""全局配置 — 从环境变量 / .env 读取。"""
from __future__ import annotations

import sys
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── 运行环境检测 ──────────────────────────────────────────
# PyInstaller 打包后: __file__ 指向临时解压目录 _MEIPASS, 不能作为路径基准。
# 此时:
#   - 只读资源 (tiers.yaml / 前端 dist) 放在 _MEIPASS 内
#   - 可写用户数据 (data_dir) 放在可执行文件旁的用户目录
# 非 frozen 模式 (开发/Docker): 保持原有 __file__ 推导, 行为完全不变。
_IS_FROZEN = getattr(sys, "frozen", False)


def _user_data_root() -> Path:
    """桌面版用户数据根目录。

    定位策略 (按优先级):
      1. 环境变量 DATA_DIR (pydantic-settings 自动注入到 settings.data_dir, 不在此处理)
      2. 打包桌面版: exe 同级的 data/ 子目录 (<安装目录>/data/)
         —— 与程序同处一个总目录 (用户选择的安装目录), 视觉直观, 便于备份/迁移。
      3. 非 frozen (开发模式): 项目根 data/

    为什么不用 platformdirs 默认 (%LOCALAPPDATA%) 作为主路径:
      - 落在 C 盘系统目录, 用户不易察觉, 占系统盘空间
      - 用户期望「数据跟随程序」(便于备份/迁移)
    为什么放 {app}/data (exe 旁的 data/) 而非 {app} 外的兄弟目录:
      - 用户体验: 用户选了安装目录, 自然期望「程序和数据都在这」, 单一总目录更直观。
      - 数据安全: Inno Setup 覆盖安装(升级)时只往 {app} 写新程序文件, 不会清空
        目录里不在安装清单上的运行时文件 (data/ 即此类), 故覆盖安装不丢数据。
        (注意: 卸载时需在 .iss 中豁免 data/, 见 packaging/tickflow.iss 的 [UninstallDelete]。)
    旧版本数据迁移: 见 DataStore._migrate_legacy_data_dir(), 老用户首次启动自动搬迁。
    """
    # 打包桌面版: macOS 用 Application Support, Windows/Linux 用 exe 同级 data/
    if _IS_FROZEN:
        if sys.platform == "darwin":
            app_support = Path.home() / "Library" / "Application Support" / "YunZhiXinQuant" / "data"
            dev_data = Path("/Users/stwenmc/Desktop/漫剧/tickflow-stock-panel/data")
            if dev_data.exists() and not (app_support / "user_data").exists():
                try:
                    import shutil
                    app_support.parent.mkdir(parents=True, exist_ok=True)
                    if not app_support.exists():
                        shutil.copytree(dev_data, app_support)
                    else:
                        for item in dev_data.iterdir():
                            dst = app_support / item.name
                            if not dst.exists():
                                if item.is_dir():
                                    shutil.copytree(item, dst)
                                else:
                                    shutil.copy2(item, dst)
                except Exception:
                    pass
            app_support.mkdir(parents=True, exist_ok=True)
            return app_support

        exe_dir = Path(sys.executable).resolve().parent
        return exe_dir / "data"

    # 开发模式: 项目根 data/
    return _PROJECT_ROOT / "data"


def _resource_root() -> Path:
    """只读资源根目录。

    frozen: PyInstaller 解压目录 (_MEIPASS)
    非 frozen: 项目根目录 (源码树)
    """
    if _IS_FROZEN:
        # sys._MEIPASS 是 PyInstaller 注入的解压根
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent.parent


def _project_root() -> Path:
    """项目根目录 (非 frozen 用)。"""
    return Path(__file__).resolve().parent.parent.parent


_PROJECT_ROOT = _project_root()
_RESOURCE_ROOT = _resource_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_RESOURCE_ROOT / ".env") if not _IS_FROZEN else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # TickFlow
    tickflow_api_key: str = Field(default="", description="留空启用 free 模式")

    # Zhitu
    zhitu_api_token: str = Field(default="B9B718D3-3FDD-461B-B4C2-A261A3B01702", description="智兔 API Token 证书")
    zhitu_base_url: str = Field(default="https://api.zhituapi.com", description="智兔 API Base URL")

    # TradingView
    tradingview_proxy: str = Field(default="", description="TradingView HTTP/SOCKS5 代理地址，如 http://127.0.0.1:7890")
    tradingview_session_id: str = Field(default="", description="TradingView 登录 Session Cookie，可选")

    # AI
    ai_provider: str = "openai_compat"
    ai_base_url: str = "https://api.zhaji.dev/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-5.5"
    ai_codex_command: str = "codex"
    ai_codex_reasoning_effort: str = ""
    # 默认浏览器风格 UA,绕过 Cloudflare 等 CDN/WAF 的 Bot 拦截(Issue #8)。
    # 用户可在 AI 设置页按需修改。
    ai_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    # 资讯: 7x24 快讯实时抓取节奏(秒)。服务端按此节奏持续抓取并累积到滚动池,
    # 有新快讯就经 SSE 推 news_updated。设 0 关闭自动抓取(退化为按需拉取)。
    news_poll_interval_seconds: float = Field(
        default=15.0, description="7x24 快讯抓取间隔(秒), 0 = 关闭自动抓取"
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 3018
    log_level: str = "INFO"
    backtest_range_guard: bool = False
    backtest_matrix_disk_cache_enabled: bool = True
    backtest_matrix_cache_max_mb: int = 512
    backtest_matrix_cache_prewarm: bool = True
    backtest_matrix_cache_prewarm_years: int = 5

    # Auth — 首次启动时预置访问密码(明文, 仅用于初始化, 详见 services/auth.bootstrap_from_env)
    # 公网服务器部署时免去 SSH 端口转发设密码的麻烦。写入 auth.json(哈希)后即不再读取。
    auth_password: str = ""

    # Data — frozen: exe 同级 data/ 子目录; 非 frozen: 项目根 data/
    # (均可被环境变量 DATA_DIR 覆盖, pydantic-settings 自动注入)
    data_dir: Path = _user_data_root()

    # tiers.yaml 路径 — frozen: 资源目录内; 非 frozen: 项目根目录
    tiers_yaml: Path = _RESOURCE_ROOT / "tiers.yaml" if _IS_FROZEN else _PROJECT_ROOT / "tiers.yaml"

    # 静态文件(前端 dist) — frozen: 资源目录的 static/; 非 frozen: frontend/dist
    static_dir: Path = _RESOURCE_ROOT / "static" if _IS_FROZEN else (_PROJECT_ROOT / "frontend" / "dist")

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        """确保 data_dir 是绝对路径（环境变量传入的相对路径基于项目根目录解析）。"""
        if not self.data_dir.is_absolute():
            # 相对路径基于项目根目录解析，而非 CWD
            self.data_dir = (_PROJECT_ROOT / self.data_dir).resolve()
        if self.backtest_matrix_cache_max_mb <= 0:
            raise ValueError("backtest_matrix_cache_max_mb must be positive")
        if self.backtest_matrix_cache_prewarm_years <= 0:
            raise ValueError("backtest_matrix_cache_prewarm_years must be positive")
        return self

    @property
    def use_free_mode(self) -> bool:
        """是否走 Free 模式。优先看 secrets.json,其次看 .env。"""
        from app import secrets_store
        return not secrets_store.get_tickflow_key()


settings = Settings()
