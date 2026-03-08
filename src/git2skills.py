#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git2Skills https://github.com/mok_cn/Git2Skills 代码库分析脚本 (增强版)
增加Git分支分析、提交历史、开发人员统计、完善的Skills和API生成

使用方法:
    python analyze_repo_enhanced.py --repo-path=/path/to/repo --claude-api-key=sk-xxx

依赖:
    pip install anthropic gitpython
"""

import os
import sys
import json
import argparse
import logging
import tempfile
import shutil
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from datetime import datetime, timedelta

# 设置Windows控制台编码为UTF-8
if sys.platform == 'win32':
    try:
        import codecs
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except Exception:
        pass  # 如果失败，继续运行，可能会有编码问题但不影响核心功能

try:
    from anthropic import Anthropic
    import git
except ImportError:
    print("错误: 缺少必要的依赖库")
    print("请运行: pip install anthropic gitpython")
    sys.exit(1)


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_smart_api_config() -> Tuple[Optional[str], Optional[str]]:
    """
    智能检测并返回最佳的API配置（跨平台兼容）

    优先级:
    1. Windows: 注册表用户环境变量 (避免被Claude Code覆盖)
    2. Linux/Mac: ~/.bashrc, ~/.profile 等配置文件中的环境变量
    3. 进程环境变量
    4. None

    Returns:
        (api_key, base_url)
    """
    api_key = None
    base_url = None

    # 在Windows上，优先从注册表读取
    if sys.platform == 'win32':
        try:
            import winreg

            # 读取用户环境变量
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment')

                # 尝试读取API密钥
                for var_name in ['ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY', 'CLAUDE_API_KEY']:
                    try:
                        value, _ = winreg.QueryValueEx(key, var_name)
                        if value and value != 'PROXY_MANAGED' and len(value) > 20:
                            api_key = value
                            logger.info(f"✓ 从Windows注册表读取API密钥 ({var_name})")
                            break
                    except FileNotFoundError:
                        continue

                # 尝试读取BASE_URL
                try:
                    value, _ = winreg.QueryValueEx(key, 'ANTHROPIC_BASE_URL')
                    if value and value != 'http://127.0.0.1:15721':
                        base_url = value
                        logger.info(f"✓ 从Windows注册表读取BASE_URL: {base_url}")
                except FileNotFoundError:
                    pass

                winreg.CloseKey(key)
            except Exception as e:
                logger.debug(f"无法读取Windows注册表: {e}")
        except ImportError:
            pass

    # 如果没有找到（或不是Windows），使用环境变量
    if not api_key:
        api_key = (
            os.getenv('CLAUDE_API_KEY') or
            os.getenv('ANTHROPIC_API_KEY') or
            os.getenv('ANTHROPIC_AUTH_TOKEN')
        )
        if api_key:
            # 检查是否是Claude Code的占位符
            if api_key == 'PROXY_MANAGED':
                logger.warning("⚠️  检测到Claude Code占位符密钥 (PROXY_MANAGED)")
                if sys.platform == 'win32':
                    logger.warning("    建议在独立终端运行，或在Windows注册表中设置真实密钥")
                else:
                    logger.warning("    建议在独立终端运行，或在 ~/.bashrc 中设置真实密钥")
            else:
                logger.info(f"✓ 从环境变量读取API密钥")

    if not base_url:
        base_url = os.getenv('ANTHROPIC_BASE_URL')
        if base_url:
            # 检查是否是Claude Code的本地代理
            if base_url == 'http://127.0.0.1:15721':
                logger.warning("⚠️  检测到Claude Code本地代理 (127.0.0.1:15721)")
                if sys.platform == 'win32':
                    logger.warning("    如果遇到连接问题，建议在Windows注册表中设置正确的BASE_URL")
                else:
                    logger.warning("    如果遇到连接问题，建议在 ~/.bashrc 中设置正确的BASE_URL")
            else:
                logger.info(f"✓ 从环境变量读取BASE_URL: {base_url}")

    return api_key, base_url


class GitCloner:
    """Git仓库克隆器"""

    @staticmethod
    def is_git_url(url: str) -> bool:
        """判断是否是Git URL"""
        patterns = [
            r'^https?://.*\.git$',
            r'^git@.*:.*\.git$',
            r'^https?://github\.com/[\w-]+/[\w-]+/?$',
            r'^https?://gitlab\.com/[\w-]+/[\w-]+/?$',
            r'^https?://gitee\.com/[\w-]+/[\w-]+/?$',
        ]
        return any(re.match(pattern, url) for pattern in patterns)

    @staticmethod
    def clone_repository(
        git_url: str,
        target_dir: Optional[str] = None,
        branch: Optional[str] = None,
        depth: int = 0,
        reuse_existing: bool = True
    ) -> Tuple[str, bool]:
        """
        克隆Git仓库到本地

        Args:
            git_url: Git仓库URL
            target_dir: 目标目录(None则使用临时目录)
            branch: 指定分支(None则使用默认分支)
            depth: 克隆深度(0=完整历史, 1=浅克隆)
            reuse_existing: 如果目录已存在是否复用 (默认True)

        Returns:
            (本地仓库路径, 是否为已存在的目录)
        """
        logger.info(f"正在克隆Git仓库: {git_url}")

        # 如果没有指定目标目录,使用固定的缓存目录(而不是带时间戳)
        if target_dir is None:
            temp_base = tempfile.gettempdir()
            repo_name = GitCloner._extract_repo_name(git_url)
            # 使用固定名称以便复用
            target_dir = os.path.join(temp_base, f'aisdlc-clone-{repo_name}')

        target_path = Path(target_dir)
        is_reused = False

        # 检查目录是否已存在
        if target_path.exists():
            if reuse_existing:
                # 验证是否是有效的Git仓库
                try:
                    test_repo = git.Repo(target_path)
                    # 检查远程URL是否匹配
                    if test_repo.remotes.origin.url == git_url or test_repo.remotes.origin.url == git_url.rstrip('/'):
                        logger.info(f"✓ 复用已存在的克隆: {target_path}")
                        print(f"📦 复用已存在的仓库克隆（节省时间）")
                        sys.stdout.flush()
                        is_reused = True
                        return str(target_path), is_reused
                    else:
                        logger.warning(f"目录存在但远程URL不匹配，将重新克隆")
                        print(f"⚠️  目录存在但URL不匹配，重新克隆...")
                        sys.stdout.flush()
                except (git.InvalidGitRepositoryError, Exception) as e:
                    logger.warning(f"目录存在但不是有效Git仓库: {e}，将重新克隆")
                    print(f"⚠️  目录存在但无效，重新克隆...")
                    sys.stdout.flush()

                # 删除无效目录
                def handle_remove_readonly(func, path, exc):
                    import stat
                    if not os.access(path, os.W_OK):
                        os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)
                        func(path)
                    else:
                        raise
                shutil.rmtree(target_path, onerror=handle_remove_readonly)
            else:
                logger.warning(f"目标目录已存在，将被删除: {target_path}")
                def handle_remove_readonly(func, path, exc):
                    import stat
                    if not os.access(path, os.W_OK):
                        os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)
                        func(path)
                    else:
                        raise
                shutil.rmtree(target_path, onerror=handle_remove_readonly)

        try:
            # 准备克隆参数
            clone_kwargs = {}
            if depth > 0:
                clone_kwargs['depth'] = depth
                logger.info(f"使用浅克隆,深度: {depth}")

            if branch:
                clone_kwargs['branch'] = branch
                logger.info(f"指定分支: {branch}")

            logger.info(f"克隆到: {target_path}")

            # 克隆仓库
            repo = git.Repo.clone_from(git_url, target_path, **clone_kwargs)

            logger.info(f"✓ 克隆成功")

            # 如果使用了浅克隆但需要完整历史,取消浅克隆
            if depth > 0:
                try:
                    logger.info("获取完整提交历史...")
                    repo.git.fetch('--unshallow')
                    logger.info("✓ 完整历史已获取")
                except Exception as e:
                    logger.warning(f"获取完整历史失败(可能已是完整仓库): {e}")

            # 获取所有远程分支
            try:
                logger.info("获取所有远程分支...")
                repo.git.fetch('--all')
                logger.info("✓ 所有远程分支已获取")
            except Exception as e:
                logger.warning(f"获取远程分支失败: {e}")

            return str(target_path), is_reused

        except git.GitCommandError as e:
            logger.error(f"Git克隆失败: {e}")
            raise RuntimeError(f"无法克隆仓库 {git_url}: {e}")
        except Exception as e:
            logger.error(f"克隆过程出错: {e}")
            raise

    @staticmethod
    def _extract_repo_name(git_url: str) -> str:
        """从Git URL提取仓库名称"""
        # 移除.git后缀
        url = git_url.rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]

        # 提取最后一部分作为仓库名
        parts = url.split('/')
        if len(parts) >= 2:
            return f"{parts[-2]}-{parts[-1]}"
        return parts[-1] if parts else 'repo'

    @staticmethod
    def cleanup(repo_path: str):
        """清理克隆的临时目录"""
        try:
            if os.path.exists(repo_path) and 'aisdlc-clone-' in repo_path:
                logger.info(f"清理临时目录: {repo_path}")

                # Windows下需要处理只读文件
                def handle_remove_readonly(func, path, exc):
                    """处理只读文件删除错误"""
                    import stat
                    if not os.access(path, os.W_OK):
                        # 如果是只读文件，修改权限后重试
                        os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)
                        func(path)
                    else:
                        raise

                shutil.rmtree(repo_path, onerror=handle_remove_readonly)
                logger.info("✓ 清理完成")
        except Exception as e:
            logger.warning(f"清理失败: {e}")
            logger.warning(f"临时目录未删除，请手动清理: {repo_path}")


@dataclass
class FileInfo:
    """文件信息"""
    path: str
    name: str
    ext: str
    size: int
    lines: int
    last_modified: Optional[str] = None
    last_author: Optional[str] = None


@dataclass
class TechStack:
    """技术栈信息"""
    languages: List[str]
    frameworks: List[str]
    libraries: List[str]
    build_tools: List[str]


@dataclass
class GitBranchInfo:
    """Git分支信息"""
    name: str
    is_current: bool
    commit_count: int
    last_commit: str
    last_commit_date: str
    last_author: str


@dataclass
class DeveloperStats:
    """开发人员统计"""
    name: str
    email: str
    commits: int
    lines_added: int
    lines_deleted: int
    files_changed: int
    first_commit: str
    last_commit: str
    active_days: int


@dataclass
class CommitInfo:
    """提交信息"""
    sha: str
    author: str
    email: str
    date: str
    message: str
    files_changed: int
    insertions: int
    deletions: int


@dataclass
class GitAnalysis:
    """Git分析结果"""
    branches: List[GitBranchInfo]
    total_commits: int
    total_contributors: int
    recent_commits: List[CommitInfo]
    developers: List[DeveloperStats]
    commit_frequency: Dict[str, int]  # 按日期统计
    most_active_files: List[Tuple[str, int]]


@dataclass
class APIEndpoint:
    """API端点信息"""
    method: str
    path: str
    description: str
    file: str
    line_number: Optional[int] = None
    parameters: List[Dict] = None
    request_body: Optional[Dict] = None
    response: Optional[Dict] = None
    authentication: Optional[str] = None
    examples: List[Dict] = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = []
        if self.examples is None:
            self.examples = []


@dataclass
class Skill:
    """Skill信息"""
    id: str
    name: str
    type: str  # function, api, component, pattern, techstack
    description: str
    category: str  # backend, frontend, mobile, data, devops
    file: str
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    usage_example: Optional[str] = None
    parameters: List[Dict] = None
    dependencies: List[str] = None
    tags: List[str] = None
    complexity: str = 'medium'  # low, medium, high
    reuse_potential: str = 'medium'  # low, medium, high

    # 新增字段
    business_context: Optional[str] = None  # 业务背景
    use_cases: List[str] = None  # 适用场景列表
    related_skills: List[str] = None  # 相关Skills
    best_practices: Optional[str] = None  # 最佳实践
    common_issues: List[str] = None  # 常见问题

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = []
        if self.dependencies is None:
            self.dependencies = []
        if self.tags is None:
            self.tags = []
        if self.use_cases is None:
            self.use_cases = []
        if self.related_skills is None:
            self.related_skills = []
        if self.common_issues is None:
            self.common_issues = []


@dataclass
class BusinessLogic:
    """业务逻辑信息"""
    name: str
    description: str
    file: str
    importance: str
    code_snippet: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class DataModel:
    """数据模型信息"""
    name: str
    fields: List[Dict]
    file: str
    line_number: Optional[int] = None
    description: Optional[str] = None
    relations: Optional[List[str]] = None
    indexes: Optional[List[str]] = None
    validation: Optional[List[str]] = None

    def __post_init__(self):
        if self.relations is None:
            self.relations = []
        if self.indexes is None:
            self.indexes = []
        if self.validation is None:
            self.validation = []


@dataclass
class Component:
    """组件信息"""
    name: str
    type: str
    props: List[Dict]
    usage: str
    file: str
    line_number: Optional[int] = None


@dataclass
class AnalysisResult:
    """分析结果"""
    apis: List[APIEndpoint]
    business_logic: List[BusinessLogic]
    data_models: List[DataModel]
    components: List[Component]
    skills: List[Skill]


class GitAnalyzer:
    """Git仓库分析器"""

    def __init__(self, repo_path: str):
        try:
            self.repo = git.Repo(repo_path)
        except git.InvalidGitRepositoryError:
            logger.warning(f"路径不是Git仓库: {repo_path}")
            self.repo = None

    def analyze(self, days: int = 90) -> Optional[GitAnalysis]:
        """分析Git仓库"""
        if not self.repo:
            return None

        logger.info("开始Git仓库分析...")

        # 分析分支
        branches = self._analyze_branches()

        # 分析提交历史
        commits = self._analyze_commits(days)
        recent_commits = commits[:20]  # 最近20次提交

        # 分析开发人员
        developers = self._analyze_developers(commits)

        # 提交频率统计
        commit_frequency = self._calculate_commit_frequency(commits)

        # 最活跃的文件
        most_active_files = self._find_most_active_files(commits)

        logger.info(f"Git分析完成: {len(branches)} 个分支, {len(commits)} 次提交, {len(developers)} 位开发者")

        return GitAnalysis(
            branches=branches,
            total_commits=len(commits),
            total_contributors=len(developers),
            recent_commits=recent_commits,
            developers=developers,
            commit_frequency=commit_frequency,
            most_active_files=most_active_files
        )

    def _analyze_branches(self) -> List[GitBranchInfo]:
        """分析分支"""
        branches = []
        seen_branches = set()  # 避免重复

        # 1. 分析本地分支
        for branch in self.repo.branches:
            try:
                if branch.name in seen_branches:
                    continue
                seen_branches.add(branch.name)

                commit = branch.commit
                commit_count = sum(1 for _ in self.repo.iter_commits(branch.name))

                branches.append(GitBranchInfo(
                    name=branch.name,
                    is_current=branch == self.repo.active_branch,
                    commit_count=commit_count,
                    last_commit=commit.hexsha[:8],
                    last_commit_date=datetime.fromtimestamp(commit.committed_date).isoformat(),
                    last_author=commit.author.name
                ))
            except Exception as e:
                logger.warning(f"分析本地分支 {branch.name} 失败: {e}")

        # 2. 分析远程分支
        try:
            for remote in self.repo.remotes:
                for ref in remote.refs:
                    # 跳过HEAD引用
                    if ref.name.endswith('/HEAD'):
                        continue

                    # 提取分支名 (去除remote前缀, 如 origin/master -> master)
                    branch_name = ref.name.split('/', 1)[1] if '/' in ref.name else ref.name

                    # 如果本地已有同名分支，跳过
                    if branch_name in seen_branches:
                        continue
                    seen_branches.add(branch_name)

                    try:
                        commit = ref.commit
                        commit_count = sum(1 for _ in self.repo.iter_commits(ref.name))

                        branches.append(GitBranchInfo(
                            name=f"{remote.name}/{branch_name}",  # 显示为 origin/branch_name
                            is_current=False,
                            commit_count=commit_count,
                            last_commit=commit.hexsha[:8],
                            last_commit_date=datetime.fromtimestamp(commit.committed_date).isoformat(),
                            last_author=commit.author.name
                        ))
                    except Exception as e:
                        logger.warning(f"分析远程分支 {ref.name} 失败: {e}")
        except Exception as e:
            logger.warning(f"分析远程分支失败: {e}")

        logger.info(f"共发现 {len(branches)} 个分支")
        return sorted(branches, key=lambda b: b.commit_count, reverse=True)

    def _analyze_commits(self, days: int) -> List[CommitInfo]:
        """分析提交历史"""
        commits = []

        try:
            # 如果指定天数为0，获取所有提交
            if days == 0:
                commit_iter = self.repo.iter_commits()
            else:
                since = datetime.now() - timedelta(days=days)
                commit_iter = self.repo.iter_commits(since=since)

            for commit in commit_iter:
                # 统计文件变更
                files_changed = len(commit.stats.files)
                insertions = commit.stats.total['insertions']
                deletions = commit.stats.total['deletions']

                commits.append(CommitInfo(
                    sha=commit.hexsha[:8],
                    author=commit.author.name,
                    email=commit.author.email,
                    date=datetime.fromtimestamp(commit.committed_date).isoformat(),
                    message=commit.message.split('\n')[0][:100],  # 第一行,最多100字符
                    files_changed=files_changed,
                    insertions=insertions,
                    deletions=deletions
                ))
        except Exception as e:
            logger.warning(f"分析提交历史失败: {e}")

        # 如果按时间过滤没找到提交，尝试获取所有提交
        if len(commits) == 0 and days > 0:
            logger.warning(f"最近{days}天内没有提交，尝试获取所有提交历史...")
            try:
                for commit in self.repo.iter_commits():
                    files_changed = len(commit.stats.files)
                    insertions = commit.stats.total['insertions']
                    deletions = commit.stats.total['deletions']

                    commits.append(CommitInfo(
                        sha=commit.hexsha[:8],
                        author=commit.author.name,
                        email=commit.author.email,
                        date=datetime.fromtimestamp(commit.committed_date).isoformat(),
                        message=commit.message.split('\n')[0][:100],
                        files_changed=files_changed,
                        insertions=insertions,
                        deletions=deletions
                    ))
            except Exception as e:
                logger.warning(f"获取所有提交失败: {e}")

        logger.info(f"共发现 {len(commits)} 次提交")
        return commits

    def _analyze_developers(self, commits: List[CommitInfo]) -> List[DeveloperStats]:
        """分析开发人员统计"""
        dev_stats = defaultdict(lambda: {
            'commits': 0,
            'lines_added': 0,
            'lines_deleted': 0,
            'files_changed': 0,
            'first_commit': None,
            'last_commit': None,
            'dates': set(),
            'email': ''
        })

        for commit in commits:
            key = commit.author
            stats = dev_stats[key]

            stats['commits'] += 1
            stats['lines_added'] += commit.insertions
            stats['lines_deleted'] += commit.deletions
            stats['files_changed'] += commit.files_changed
            stats['email'] = commit.email
            stats['dates'].add(commit.date[:10])

            if not stats['first_commit']:
                stats['first_commit'] = commit.date
            stats['last_commit'] = commit.date

        # 转换为列表
        developers = []
        for name, stats in dev_stats.items():
            developers.append(DeveloperStats(
                name=name,
                email=stats['email'],
                commits=stats['commits'],
                lines_added=stats['lines_added'],
                lines_deleted=stats['lines_deleted'],
                files_changed=stats['files_changed'],
                first_commit=stats['first_commit'],
                last_commit=stats['last_commit'],
                active_days=len(stats['dates'])
            ))

        return sorted(developers, key=lambda d: d.commits, reverse=True)

    def _calculate_commit_frequency(self, commits: List[CommitInfo]) -> Dict[str, int]:
        """计算提交频率(按天)"""
        frequency = defaultdict(int)
        for commit in commits:
            date = commit.date[:10]  # YYYY-MM-DD
            frequency[date] += 1
        return dict(sorted(frequency.items()))

    def _find_most_active_files(self, commits: List[CommitInfo], top_n: int = 20) -> List[Tuple[str, int]]:
        """找出最活跃的文件"""
        # 注意: 这需要遍历每个commit的文件列表,比较耗时
        # 简化实现: 返回空列表或基于统计
        return []


class ProjectAnalyzer:
    """项目分析器"""

    # 需要排除的目录
    EXCLUDE_DIRS = {
        'node_modules', 'vendor', 'venv', '.venv', 'env',
        'dist', 'build', 'out', '.next', '.nuxt',
        '.git', '.svn', '.hg',
        'coverage', '.pytest_cache', '__pycache__',
        'target', 'bin', 'obj'
    }

    # 需要排除的文件扩展名
    EXCLUDE_EXTS = {
        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
        '.woff', '.woff2', '.ttf', '.eot',
        '.mp4', '.mp3', '.wav',
        '.zip', '.tar', '.gz', '.rar',
        '.pdf', '.doc', '.docx',
        '.lock', '.min.js', '.min.css'
    }

    # 编程语言检测
    LANGUAGE_EXTENSIONS = {
        '.js': 'JavaScript',
        '.jsx': 'JavaScript',
        '.ts': 'TypeScript',
        '.tsx': 'TypeScript',
        '.py': 'Python',
        '.java': 'Java',
        '.go': 'Go',
        '.rs': 'Rust',
        '.php': 'PHP',
        '.rb': 'Ruby',
        '.cs': 'C#',
        '.cpp': 'C++',
        '.c': 'C',
        '.vue': 'Vue',
        '.kt': 'Kotlin',
        '.swift': 'Swift',
    }

    # 框架检测文件
    FRAMEWORK_FILES = {
        'package.json': ['next', 'react', 'vue', 'angular', 'express', 'nestjs', 'koa', 'nuxt'],
        'requirements.txt': ['django', 'flask', 'fastapi', 'tornado'],
        'go.mod': ['gin', 'echo', 'fiber', 'beego'],
        'pom.xml': ['spring', 'springboot'],
        'Cargo.toml': ['actix', 'rocket', 'axum'],
    }

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        if not self.repo_path.exists():
            raise ValueError(f"路径不存在: {repo_path}")

        self.files: List[FileInfo] = []
        self.tech_stack: Optional[TechStack] = None
        self.git_repo = None

        # 初始化Git
        try:
            self.git_repo = git.Repo(repo_path)
        except:
            pass

    def analyze(self) -> Tuple[List[FileInfo], TechStack]:
        """分析项目结构"""
        logger.info(f"开始分析项目: {self.repo_path}")

        # 遍历文件
        self._scan_files()
        logger.info(f"发现 {len(self.files)} 个源代码文件")

        # 检测技术栈
        self.tech_stack = self._detect_tech_stack()
        logger.info(f"检测到技术栈: {', '.join(self.tech_stack.languages)}")

        return self.files, self.tech_stack

    def _scan_files(self):
        """扫描文件"""
        for root, dirs, files in os.walk(self.repo_path):
            # 排除目录
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]

            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(self.repo_path)
                ext = file_path.suffix.lower()

                # 排除文件
                if ext in self.EXCLUDE_EXTS:
                    continue

                # 只处理源代码文件
                if ext not in self.LANGUAGE_EXTENSIONS:
                    continue

                try:
                    size = file_path.stat().st_size
                    # 跳过过大的文件 (>1MB)
                    if size > 1024 * 1024:
                        continue

                    # 计算行数
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = sum(1 for _ in f)

                    # 获取Git信息
                    last_modified = None
                    last_author = None
                    if self.git_repo:
                        try:
                            commits = list(self.git_repo.iter_commits(paths=str(rel_path), max_count=1))
                            if commits:
                                last_commit = commits[0]
                                last_modified = datetime.fromtimestamp(last_commit.committed_date).isoformat()
                                last_author = last_commit.author.name
                        except:
                            pass

                    self.files.append(FileInfo(
                        path=str(rel_path),
                        name=file,
                        ext=ext,
                        size=size,
                        lines=lines,
                        last_modified=last_modified,
                        last_author=last_author
                    ))
                except Exception as e:
                    logger.warning(f"无法读取文件 {rel_path}: {e}")

    def _detect_tech_stack(self) -> TechStack:
        """检测技术栈"""
        languages = set()
        frameworks = set()
        libraries = []
        build_tools = set()

        # 检测语言
        for file in self.files:
            if file.ext in self.LANGUAGE_EXTENSIONS:
                languages.add(self.LANGUAGE_EXTENSIONS[file.ext])

        # 检测框架和库
        for config_file, framework_keywords in self.FRAMEWORK_FILES.items():
            config_path = self.repo_path / config_file
            if config_path.exists():
                try:
                    content = config_path.read_text(encoding='utf-8', errors='ignore').lower()
                    for keyword in framework_keywords:
                        if keyword in content:
                            frameworks.add(keyword.capitalize())

                    # 提取库依赖
                    if config_file == 'package.json':
                        try:
                            pkg = json.loads(config_path.read_text())
                            deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
                            libraries = list(deps.keys())[:20]  # 只取前20个
                        except:
                            pass
                except Exception as e:
                    logger.warning(f"无法读取配置文件 {config_file}: {e}")

        # 检测构建工具
        if (self.repo_path / 'package.json').exists():
            build_tools.add('npm')
        if (self.repo_path / 'yarn.lock').exists():
            build_tools.add('yarn')
        if (self.repo_path / 'pnpm-lock.yaml').exists():
            build_tools.add('pnpm')
        if (self.repo_path / 'pom.xml').exists():
            build_tools.add('Maven')
        if (self.repo_path / 'build.gradle').exists():
            build_tools.add('Gradle')
        if (self.repo_path / 'go.mod').exists():
            build_tools.add('Go Modules')
        if (self.repo_path / 'Cargo.toml').exists():
            build_tools.add('Cargo')
        if (self.repo_path / 'Makefile').exists():
            build_tools.add('Make')

        return TechStack(
            languages=sorted(list(languages)),
            frameworks=sorted(list(frameworks)),
            libraries=libraries,
            build_tools=sorted(list(build_tools))
        )

    def filter_by_modification_time(self, since_days: int) -> List[FileInfo]:
        """根据修改时间过滤文件（增量分析）"""
        if since_days <= 0:
            return self.files  # 0表示不过滤

        cutoff_date = datetime.now() - timedelta(days=since_days)
        filtered_files = []

        for file in self.files:
            if file.last_modified:
                try:
                    last_mod = datetime.fromisoformat(file.last_modified)
                    if last_mod >= cutoff_date:
                        filtered_files.append(file)
                except:
                    # 如果解析失败，保留文件（保守策略）
                    filtered_files.append(file)
            else:
                # 如果没有修改时间信息，保留文件
                filtered_files.append(file)

        logger.info(f"增量过滤: {len(self.files)} 个文件 -> {len(filtered_files)} 个文件 (最近{since_days}天)")
        return filtered_files

    def prioritize_files(self, focus_areas: List[str], max_files: int = 100) -> List[FileInfo]:
        """优先级排序文件"""
        scored_files = []

        for file in self.files:
            score = 0
            path_lower = file.path.lower()

            # 根据关注点评分
            if 'api' in focus_areas:
                if any(keyword in path_lower for keyword in ['controller', 'route', 'api', 'handler', 'endpoint']):
                    score += 10

            if 'business' in focus_areas:
                if any(keyword in path_lower for keyword in ['service', 'business', 'logic', 'core', 'manager']):
                    score += 10

            if 'model' in focus_areas:
                if any(keyword in path_lower for keyword in ['model', 'entity', 'schema', 'dto', 'type']):
                    score += 10

            if 'component' in focus_areas:
                if any(keyword in path_lower for keyword in ['component', 'view', 'page', 'widget']):
                    score += 10

            # 文件大小评分 (中等大小优先)
            if 100 < file.lines < 500:
                score += 5
            elif 50 < file.lines < 1000:
                score += 3

            # 文件深度评分 (不要太深的目录)
            depth = len(Path(file.path).parts)
            if depth <= 3:
                score += 2

            # 最近修改的文件优先
            if file.last_modified:
                try:
                    last_mod = datetime.fromisoformat(file.last_modified)
                    days_ago = (datetime.now() - last_mod).days
                    if days_ago < 30:
                        score += 3
                    elif days_ago < 90:
                        score += 1
                except:
                    pass

            scored_files.append((score, file))

        # 按分数排序
        scored_files.sort(key=lambda x: x[0], reverse=True)

        # 返回前N个文件
        return [file for score, file in scored_files[:max_files]]


class ClaudeAnalyzer:
    """Claude代码分析器 (集成规则引擎)"""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        """
        初始化Claude分析器

        Args:
            api_key: Claude API密钥
            base_url: 可选的API基础URL (用于自定义端点)
        """
        client_kwargs = {'api_key': api_key}
        if base_url:
            client_kwargs['base_url'] = base_url

        self.client = Anthropic(**client_kwargs)
        self.model = "claude-3-5-sonnet-20241022"

        # 初始化规则引擎
        try:
            rules_file = Path(__file__).parent.parent / 'config' / 'api_extraction_rules.json'

            # 如果规则文件不存在，创建它
            if not rules_file.exists():
                rules_file.parent.mkdir(parents=True, exist_ok=True)
                logger.info("规则文件不存在，将在首次分析后创建")
                self.rule_engine = None
                self.rule_learner = None
            else:
                from rule_engine import RuleEngine, RuleLearner
                self.rule_engine = RuleEngine(rules_file)
                self.rule_learner = RuleLearner(rules_file)
                logger.info(f"✓ 规则引擎已加载: {rules_file}")
        except Exception as e:
            logger.warning(f"规则引擎初始化失败，将仅使用LLM分析: {e}")
            self.rule_engine = None
            self.rule_learner = None

    def analyze_code(
        self,
        files: List[FileInfo],
        tech_stack: TechStack,
        focus_areas: List[str],
        repo_path: Path
    ) -> AnalysisResult:
        """分析代码 (规则引擎+LLM双轨道)"""

        # === Step 1: 规则引擎快速提取 ===
        rule_extracted_apis = []
        if self.rule_engine and 'api' in focus_areas:
            print("   → 步骤1/4: 规则引擎快速提取API...", flush=True)
            rule_extracted_apis = self._extract_with_rules(files, repo_path, tech_stack)
            if rule_extracted_apis:
                avg_conf = sum(api.get('confidence', 0) for api in rule_extracted_apis) / len(rule_extracted_apis)
                print(f"      规则提取: {len(rule_extracted_apis)} 个API, 平均置信度: {avg_conf:.2f}")
                sys.stdout.flush()

        # === Step 2: 确定LLM分析策略 ===
        avg_confidence = (sum(api.get('confidence', 0) for api in rule_extracted_apis) / len(rule_extracted_apis)) if rule_extracted_apis else 0.0

        if avg_confidence >= 0.80:
            print(f"      规则覆盖良好({avg_confidence:.2f}≥0.80), LLM将只做补充验证")
            llm_mode = "supplement"
        else:
            print(f"      规则覆盖不足({avg_confidence:.2f}<0.80), LLM将全面分析")
            llm_mode = "full"
        sys.stdout.flush()

        # === Step 3: LLM分析 ===
        # 批量处理
        batch_size = 30
        total_batches = (len(files) + batch_size - 1) // batch_size

        print(f"   → 步骤2/4: LLM深度分析 - 分 {total_batches} 批处理 {len(files)} 个文件")
        sys.stdout.flush()

        all_results = {
            'apis': [],
            'business_logic': [],
            'data_models': [],
            'components': []
        }

        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]
            batch_num = i // batch_size + 1

            print(f"   → 正在处理批次 {batch_num}/{total_batches}...", end='', flush=True)

            try:
                # 筛选出当前批次相关的规则引擎提取的API
                batch_files = {f.path for f in batch}
                batch_rule_apis = [api for api in rule_extracted_apis if api['file'] in batch_files] if rule_extracted_apis else None

                batch_result = self._analyze_batch(batch, tech_stack, focus_areas, repo_path, batch_rule_apis)

                # 合并结果
                for key in all_results.keys():
                    all_results[key].extend(batch_result.get(key, []))

                print(" ✓")
                sys.stdout.flush()

            except Exception as e:
                print(f" ✗ (失败: {str(e)[:50]})")
                logger.error(f"分析批次失败: {e}")
                continue

        # === Step 4: 合并规则和LLM结果 ===
        if rule_extracted_apis:
            print("   → 步骤3/4: 合并规则和LLM结果...", end='', flush=True)
            all_results['apis'] = self._merge_rule_and_llm_apis(rule_extracted_apis, all_results['apis'])
            print(f" ✓ (最终: {len(all_results['apis'])} 个API)")
            sys.stdout.flush()

        # === Step 5: 规则学习 ===
        if self.rule_learner and self.rule_engine and rule_extracted_apis and all_results['apis']:
            enable_learning = self.rule_engine.rules.get('learning_config', {}).get('enable_auto_learning', True)
            if enable_learning:
                print("   → 步骤4/4: 规则自动学习...", end='', flush=True)
                try:
                    # 只使用第一个文件进行学习（避免过度学习）
                    if files:
                        sample_file = repo_path / files[0].path
                        sample_content = sample_file.read_text(encoding='utf-8', errors='ignore')[:15000]

                        # 转换 rule_extracted_apis 为正确的格式
                        from rule_engine import ExtractedAPI
                        rule_apis_objs = []
                        for api_dict in rule_extracted_apis:
                            rule_apis_objs.append(ExtractedAPI(
                                method=api_dict['method'],
                                path=api_dict['path'],
                                description=api_dict.get('description', ''),
                                file=api_dict.get('file', ''),
                                confidence=api_dict.get('confidence', 0.0)
                            ))

                        learned_rules = self.rule_learner.learn_from_llm_results(
                            rule_apis_objs,
                            all_results['apis'],
                            sample_content
                        )

                        if learned_rules and any(len(v) > 0 for v in learned_rules.values()):
                            self.rule_learner.update_rules(learned_rules)
                            new_patterns = sum(len(v) for v in learned_rules.values())
                            print(f" ✓ (学习{new_patterns}个新模式)")
                        else:
                            print(" ✓ (无新模式)")
                    else:
                        print(" - (跳过)")
                except Exception as e:
                    print(f" ✗ ({str(e)[:30]})")
                    logger.warning(f"规则学习失败: {e}")
                sys.stdout.flush()

        # 生成Skills
        print("   → 生成Skills...", end='', flush=True)
        skills = self._generate_skills(all_results, tech_stack)
        print(" ✓")
        sys.stdout.flush()

        # 转换为数据类
        return AnalysisResult(
            apis=[self._dict_to_api(api) for api in all_results['apis']],
            business_logic=[BusinessLogic(**logic) for logic in all_results['business_logic']],
            data_models=[DataModel(**model) for model in all_results['data_models']],
            components=[Component(**comp) for comp in all_results['components']],
            skills=skills
        )

    def _dict_to_api(self, api_dict: Dict) -> APIEndpoint:
        """字典转API对象"""
        return APIEndpoint(
            method=api_dict.get('method', 'GET'),
            path=api_dict.get('path', ''),
            description=api_dict.get('description', ''),
            file=api_dict.get('file', ''),
            line_number=api_dict.get('line_number'),
            parameters=api_dict.get('parameters', []),
            request_body=api_dict.get('request_body'),
            response=api_dict.get('response'),
            authentication=api_dict.get('authentication'),
            examples=api_dict.get('examples', [])
        )

    def _generate_skills(self, analysis_results: Dict, tech_stack: TechStack) -> List[Skill]:
        """从分析结果生成Skills (使用LLM丰富业务背景和适用场景)"""
        logger.info("生成Skills...")
        skills = []

        # 从API生成Skills
        for api in analysis_results['apis']:
            skill_id = f"api_{api['method'].lower()}_{self._normalize_path(api['path'])}"

            # 提取路径参数作为tags
            tags = ['api', api['method'].lower()]
            if '{' in api['path']:
                tags.append('dynamic-route')

            skills.append(Skill(
                id=skill_id,
                name=f"{api['method']} {api['path']}",
                type='api',
                description=api.get('description', f"API端点: {api['path']}"),
                category=self._infer_category(api['file']),
                file=api['file'],
                line_number=api.get('line_number'),
                code_snippet=None,
                usage_example=self._generate_api_usage_example(api, tech_stack),
                parameters=api.get('parameters', []),
                tags=tags,
                complexity='low',
                reuse_potential='high',
                # 暂时为空，后续用LLM批量填充
                business_context=None,
                use_cases=[],
                related_skills=[],
                best_practices=None,
                common_issues=[]
            ))

        # 从业务逻辑生成Skills (只选择重要的)
        for logic in analysis_results['business_logic']:
            if logic.get('importance') in ['high', 'medium']:
                skill_id = f"logic_{self._normalize_name(logic['name'])}"

                tags = ['business-logic', logic.get('importance', 'medium')]

                skills.append(Skill(
                    id=skill_id,
                    name=logic['name'],
                    type='function',
                    description=logic['description'],
                    category=self._infer_category(logic['file']),
                    file=logic['file'],
                    line_number=logic.get('line_number'),
                    code_snippet=logic.get('code_snippet'),
                    tags=tags,
                    complexity=self._estimate_complexity(logic),
                    reuse_potential='medium'
                ))

        # 从组件生成Skills
        for comp in analysis_results['components']:
            skill_id = f"component_{self._normalize_name(comp['name'])}"

            tags = ['component', comp.get('type', 'component').lower()]

            skills.append(Skill(
                id=skill_id,
                name=comp['name'],
                type='component',
                description=comp.get('usage', ''),
                category='frontend',
                file=comp['file'],
                line_number=comp.get('line_number'),
                parameters=comp.get('props', []),
                tags=tags,
                complexity='medium',
                reuse_potential='high'
            ))

        logger.info(f"生成 {len(skills)} 个基础Skills")

        # 使用LLM批量丰富Skills (只处理前20个重要的API Skills)
        api_skills = [s for s in skills if s.type == 'api'][:20]
        if api_skills:
            logger.info(f"使用LLM丰富前 {len(api_skills)} 个API Skills的业务背景...")
            enriched_skills = self._enrich_skills_with_llm(api_skills, tech_stack, analysis_results)

            # 更新skills列表
            enriched_map = {s.id: s for s in enriched_skills}
            for i, skill in enumerate(skills):
                if skill.id in enriched_map:
                    skills[i] = enriched_map[skill.id]

        logger.info(f"最终生成 {len(skills)} 个Skills")
        return skills

    def _enrich_skills_with_llm(
        self,
        skills: List[Skill],
        tech_stack: TechStack,
        analysis_results: Dict
    ) -> List[Skill]:
        """使用LLM丰富Skills的业务背景和适用场景"""

        # 构建prompt
        skills_summary = []
        for skill in skills:
            skills_summary.append({
                'id': skill.id,
                'name': skill.name,
                'description': skill.description,
                'file': skill.file,
                'parameters': skill.parameters
            })

        # 读取 Skills 质量要求文档
        skills_requirements = ""
        try:
            skills_doc_path = Path(__file__).parent.parent / 'docs' / 'prompt_skills.txt'
            if skills_doc_path.exists():
                skills_requirements = skills_doc_path.read_text(encoding='utf-8', errors='ignore')
                logger.debug("已加载 Skills 质量要求文档")
        except Exception as e:
            logger.warning(f"无法加载 Skills 质量要求文档: {e}")

        prompt = f"""你是一个资深的软件架构师和技术文档专家。请为以下API Skills生成高质量的、AI友好的技能描述。

# 高质量 Skills 的核心要求

你的目标是生成**给 AI 看的**技能文档，而不是给人看的普通 API 文档。请遵循以下原则：

## 一、大模型友好度（AI-Friendly）

### 1. 指令化描述
- ✅ 明确告诉 AI **何时使用**这个技能
- ✅ 明确告诉 AI **何时绝对不要使用**（边界条件）
- ❌ 避免简单的"获取XX数据"这样的描述

### 2. 消歧义参数说明
- 为每个参数提供清晰的格式要求和示例
- 如果参数有固定的可选值，必须使用枚举（enum）限制 AI 的输出

### 3. 业务背景说明
- 说明这个 API 在整个业务系统中的作用和价值
- 让 AI 理解为什么这个接口存在

## 二、工程健壮性（Robustness）

### 1. 原子化设计（单一职责）
- 确认每个技能只做一件事
- 避免复杂的多功能接口导致 AI 产生幻觉

### 2. 明确必填与非必填
- 清楚标注哪些参数是必需的
- 让 AI 知道缺少必填项时应该主动向用户询问

### 3. 最佳实践建议
- 提供性能优化、安全性、可维护性方面的实用建议
- 帮助 AI 更好地使用这个接口

## 三、安全与边界规范

### 1. 常见问题预警
- 列出调用此接口时可能遇到的常见错误
- 帮助 AI 避免这些陷阱

### 2. 读写分离意识
- 对于写操作（创建、更新、删除），要特别注意安全性
- 明确哪些操作需要谨慎处理

## 项目技术栈
- 语言: {', '.join(tech_stack.languages)}
- 框架: {', '.join(tech_stack.frameworks) if tech_stack.frameworks else '未知'}

## API Skills列表
{json.dumps(skills_summary, indent=2, ensure_ascii=False)}

## 你的任务

为每个Skill补充以下信息（注意：这些信息是为 AI Agent 设计的，不是为开发者设计的）:

1. **business_context**: 业务背景（1-2句话）
   - 说明这个 API 在业务系统中的作用和价值
   - 让 AI 理解这个接口为什么存在
   - 例如："区域管理的核心接口，用于获取系统中所有可用的地理区域列表，为学校、教师、学生等资源的区域划分提供数据基础。"

2. **use_cases**: 适用场景列表（3-5个）
   - 具体场景要能帮助 AI 判断何时调用此技能
   - 避免模糊的描述，要具体实际
   - 例如："用户注册时选择所在地区"、"管理后台按地区筛选学校和用户"

3. **best_practices**: 最佳实践（1-2句话）
   - 提供性能、安全、可维护性方面的实用建议
   - 要有可操作性，不要泛泛而谈
   - 例如："建议实现分页和缓存机制，区域数据变化不频繁，可缓存减少数据库查询。"

4. **common_issues**: 常见问题列表（2-3个）
   - 列出 AI 调用时可能遇到的问题和注意事项
   - 帮助 AI 避免常见错误
   - 例如："数据量过大时未分页导致性能问题"、"未考虑区域层级关系"

## 输出格式

请以JSON格式返回，只返回JSON不要其他解释:

```json
{{
  "enriched_skills": [
    {{
      "id": "api_post__list",
      "business_context": "区域管理的核心接口，用于获取系统中所有可用的地理区域列表，为学校、教师、学生等资源的区域划分提供数据基础。",
      "use_cases": [
        "用户注册时选择所在地区",
        "管理后台按地区筛选学校和用户",
        "数据统计时按区域维度分组",
        "权限控制中限制用户访问特定区域数据"
      ],
      "best_practices": "建议实现分页和缓存机制，区域数据变化不频繁，可缓存减少数据库查询。",
      "common_issues": [
        "数据量过大时未分页导致性能问题",
        "未考虑区域层级关系（省市区）",
        "缺少按上级区域筛选的功能"
      ]
    }}
  ]
}}
```

**质量检查清单**（确保每个 Skill 都符合以下要求）:
✅ business_context 是否清晰说明了业务价值？
✅ use_cases 是否具体实际，能帮助 AI 判断何时使用？
✅ best_practices 是否有可操作性，不是空话？
✅ common_issues 是否基于实际开发经验，有预警价值？
✅ 整体描述是否"AI 友好"（指令化、消歧义、有边界）？
"""

        try:
            # 调用Claude
            message = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            response_text = message.content[0].text

            # 解析JSON
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
            else:
                json_text = response_text

            result = json.loads(json_text)

            # 更新Skills
            enriched_map = {item['id']: item for item in result.get('enriched_skills', [])}

            enriched_skills = []
            for skill in skills:
                if skill.id in enriched_map:
                    enrichment = enriched_map[skill.id]
                    # 创建新的Skill对象，包含丰富的信息
                    enriched_skills.append(Skill(
                        id=skill.id,
                        name=skill.name,
                        type=skill.type,
                        description=skill.description,
                        category=skill.category,
                        file=skill.file,
                        line_number=skill.line_number,
                        code_snippet=skill.code_snippet,
                        usage_example=skill.usage_example,
                        parameters=skill.parameters,
                        dependencies=skill.dependencies,
                        tags=skill.tags,
                        complexity=skill.complexity,
                        reuse_potential=skill.reuse_potential,
                        # 新增的丰富信息
                        business_context=enrichment.get('business_context'),
                        use_cases=enrichment.get('use_cases', []),
                        related_skills=enrichment.get('related_skills', []),
                        best_practices=enrichment.get('best_practices'),
                        common_issues=enrichment.get('common_issues', [])
                    ))
                else:
                    enriched_skills.append(skill)

            logger.info(f"成功丰富 {len(enriched_map)} 个Skills")
            return enriched_skills

        except Exception as e:
            logger.warning(f"LLM丰富Skills失败: {e}，返回原始Skills")
            return skills


    def _extract_with_rules(
        self,
        files: List[FileInfo],
        repo_path: Path,
        tech_stack: TechStack
    ) -> List[Dict]:
        """使用规则引擎提取API"""
        all_apis = []

        # 只处理Java Controller文件
        for file_info in files:
            if file_info.ext != '.java':
                continue
            if 'controller' not in file_info.path.lower():
                continue

            try:
                file_path = repo_path / file_info.path
                content = file_path.read_text(encoding='utf-8', errors='ignore')

                # 规则引擎提取 (本地执行,处理完整文件, 传递repo_path用于解析Request类)
                apis, confidence = self.rule_engine.extract_apis(
                    content,  # 不截断,处理完整内容
                    file_info.path,
                    repo_path=repo_path  # 传递repo_path以支持Request类解析
                )

                # 转换为字典格式
                for api in apis:
                    all_apis.append({
                        'method': api.method,
                        'path': api.path,
                        'description': api.description,
                        'file': api.file,
                        'line_number': api.line_number,
                        'method_name': api.method_name,
                        'parameters': api.parameters,
                        'error_codes': api.error_codes,
                        'confidence': api.confidence,
                        'extraction_source': 'rule'
                    })

                logger.debug(f"规则提取 {file_info.name}: {len(apis)} APIs")

            except Exception as e:
                logger.warning(f"规则提取失败 {file_info.path}: {e}")
                continue

        return all_apis

    def _merge_rule_and_llm_apis(
        self,
        rule_apis: List[Dict],
        llm_apis: List[Dict]
    ) -> List[Dict]:
        """合并规则和LLM提取的API"""
        merged = {}

        # 1. 添加规则提取的结果
        for api in rule_apis:
            key = f"{api['method']}:{api['path']}"
            merged[key] = api.copy()

        # 2. 用LLM结果补充或新增
        for api in llm_apis:
            key = f"{api['method']}:{api['path']}"

            if key in merged:
                # 补充细节
                if not merged[key].get('description') and api.get('description'):
                    merged[key]['description'] = api['description']

                if not merged[key].get('parameters') and api.get('parameters'):
                    merged[key]['parameters'] = api['parameters']

                if not merged[key].get('error_codes') and api.get('error_codes'):
                    merged[key]['error_codes'] = api.get('error_codes', [])

                # 标记为混合来源
                merged[key]['extraction_source'] = 'hybrid'
                merged[key]['confidence'] = max(merged[key].get('confidence', 0), 0.85)
            else:
                # 新API
                api_copy = api.copy()
                api_copy['extraction_source'] = 'llm'
                api_copy['confidence'] = 0.80
                merged[key] = api_copy

        logger.info(f"合并完成: 规则{len(rule_apis)} + LLM{len(llm_apis)} = {len(merged)}个API")

        return list(merged.values())

    def _normalize_path(self, path: str) -> str:
        """规范化路径用于ID"""
        return path.replace('/', '_').replace('{', '').replace('}', '').replace(':', '').lower()

    def _normalize_name(self, name: str) -> str:
        """规范化名称用于ID"""
        return name.lower().replace(' ', '_').replace('-', '_')

    def _infer_category(self, file_path: str) -> str:
        """推断分类"""
        path_lower = file_path.lower()

        if any(kw in path_lower for kw in ['controller', 'route', 'api', 'server', 'backend']):
            return 'backend'
        elif any(kw in path_lower for kw in ['component', 'view', 'page', 'frontend', 'ui']):
            return 'frontend'
        elif any(kw in path_lower for kw in ['mobile', 'ios', 'android']):
            return 'mobile'
        elif any(kw in path_lower for kw in ['data', 'model', 'entity', 'schema']):
            return 'data'
        elif any(kw in path_lower for kw in ['test', 'spec']):
            return 'test'
        else:
            return 'general'

    def _estimate_complexity(self, logic: Dict) -> str:
        """估算复杂度"""
        if logic.get('code_snippet'):
            lines = logic['code_snippet'].count('\n')
            if lines > 100:
                return 'high'
            elif lines > 30:
                return 'medium'
        return 'low'

    def _generate_api_usage_example(self, api: Dict, tech_stack: TechStack) -> str:
        """生成API使用示例"""
        method = api['method']
        path = api['path']
        parameters = api.get('parameters', [])
        request_body = api.get('request_body')

        if 'TypeScript' in tech_stack.languages or 'JavaScript' in tech_stack.languages:
            example = f"""// TypeScript/JavaScript
const response = await fetch('{path}', {{
  method: '{method}',
  headers: {{ 'Content-Type': 'application/json' }},"""

            # 如果有request_body或parameters，生成示例数据
            if request_body or parameters:
                example += "\n  body: JSON.stringify({"

                # 从parameters生成示例字段
                body_fields = []
                for param in parameters:
                    if param.get('in') == 'body' or not param.get('in'):
                        param_name = param.get('name', 'field')
                        param_type = param.get('type', 'string')

                        # 根据类型生成示例值
                        if param_type in ['string', 'String']:
                            example_value = f'"{param_name}_example"'
                        elif param_type in ['number', 'int', 'integer', 'Integer', 'Long', 'long']:
                            example_value = '123'
                        elif param_type in ['boolean', 'Boolean']:
                            example_value = 'true'
                        else:
                            example_value = f'"{param_name}_value"'

                        body_fields.append(f"\n    {param_name}: {example_value}")

                if body_fields:
                    example += ','.join(body_fields) + "\n  }),"
                else:
                    example += "\n    // 请根据API文档填充请求参数\n  }),"

            example += "\n});\nconst result = await response.json();"
            return example

        elif 'Python' in tech_stack.languages:
            example = f"""# Python
import requests"""

            # 如果有参数，生成data字典
            if request_body or parameters:
                example += "\n\ndata = {"
                body_fields = []
                for param in parameters:
                    if param.get('in') == 'body' or not param.get('in'):
                        param_name = param.get('name', 'field')
                        param_type = param.get('type', 'string')

                        if param_type in ['string', 'String']:
                            example_value = f'"{param_name}_example"'
                        elif param_type in ['number', 'int', 'integer', 'Integer', 'Long', 'long']:
                            example_value = '123'
                        elif param_type in ['boolean', 'Boolean']:
                            example_value = 'True'
                        else:
                            example_value = f'"{param_name}_value"'

                        body_fields.append(f"\n    '{param_name}': {example_value}")

                if body_fields:
                    example += ','.join(body_fields) + "\n}"
                else:
                    example += "\n    # 请根据API文档填充请求参数\n}"

                example += f"\nresponse = requests.{method.lower()}('{path}', json=data)"
            else:
                example += f"\nresponse = requests.{method.lower()}('{path}')"

            example += "\ndata = response.json()"
            return example
        else:
            # Java示例
            if parameters:
                example = f"""// Java
// 构造请求参数"""
                for param in parameters[:3]:  # 只显示前3个参数
                    param_name = param.get('name', 'field')
                    example += f"\n// {param_name}: {param.get('description', param_name)}"
                example += f"\n\n// 调用API: {method} {path}"
            else:
                example = f"// Java\n// 调用API: {method} {path}"
            return example

    def _analyze_batch(
        self,
        files: List[FileInfo],
        tech_stack: TechStack,
        focus_areas: List[str],
        repo_path: Path,
        rule_extracted_apis: List[Dict] = None
    ) -> Dict:
        """
        分析一批文件

        Args:
            files: 文件列表
            tech_stack: 技术栈信息
            focus_areas: 关注领域
            repo_path: 仓库路径
            rule_extracted_apis: 规则引擎提取的API信息(可选,用于LLM补充判断)
        """
        # 读取文件内容
        files_content = []
        for file in files:
            try:
                file_path = repo_path / file.path
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                    # LLM分析: 智能截取以节省token
                    # 1. 小文件(<10000字符): 完整发送
                    # 2. 大文件(>10000字符): 截取前8000字符 (通常包含imports, class定义, 前面的方法)
                    if len(content) > 10000:
                        content = content[:8000] + "\n... (truncated for LLM analysis, but full file processed by rule engine)"

                    files_content.append({
                        'path': file.path,
                        'content': content,
                        'last_author': file.last_author
                    })
            except Exception as e:
                logger.warning(f"读取文件失败 {file.path}: {e}")

        # 构建提示词(传递规则引擎提取的API信息)
        prompt = self._build_enhanced_prompt(files_content, tech_stack, focus_areas, rule_extracted_apis)

        # 调用Claude
        message = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # 解析响应
        response_text = message.content[0].text

        # 尝试提取JSON
        try:
            # 查找JSON代码块
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
            else:
                json_text = response_text

            result = json.loads(json_text)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            logger.debug(f"响应内容: {response_text[:500]}")
            return {'apis': [], 'business_logic': [], 'data_models': [], 'components': []}

    def _build_enhanced_prompt(
        self,
        files_content: List[Dict],
        tech_stack: TechStack,
        focus_areas: List[str],
        rule_extracted_apis: List[Dict] = None
    ) -> str:
        """
        构建增强的分析提示词

        Args:
            files_content: 文件内容列表
            tech_stack: 技术栈信息
            focus_areas: 关注领域
            rule_extracted_apis: 规则引擎提取的API信息(可选)
        """
        focus_text = []
        if 'api' in focus_areas:
            focus_text.append('- API端点定义、路由、请求参数、响应格式、认证方式')
        if 'business' in focus_areas:
            focus_text.append('- 业务逻辑、核心算法、数据处理流程')
        if 'model' in focus_areas:
            focus_text.append('- 数据模型、数据库Schema、字段类型、关联关系')
        if 'component' in focus_areas:
            focus_text.append('- 前端组件、Props定义、使用方式')

        files_text = []
        for file in files_content:
            author_info = f" (最后修改: {file['last_author']})" if file.get('last_author') else ""
            files_text.append(f"文件：{file['path']}{author_info}\n```\n{file['content']}\n```\n")

        # 构建规则引擎提取的参数信息提示
        rule_engine_context = ""
        if rule_extracted_apis:
            rule_engine_context = """

## 规则引擎已提取的参数信息

我们的规则引擎已经从代码中提取了以下API参数信息：

"""
            for api in rule_extracted_apis[:20]:  # 只显示前20个API
                if api.get('parameters'):
                    rule_engine_context += f"""
### {api['method']} {api['path']}
**已识别参数**:
"""
                    for param in api['parameters']:
                        rule_engine_context += f"""- `{param['name']}` ({param.get('type', 'unknown')}): {param.get('description', 'N/A')}
  - 必填: {'是' if param.get('required') else '否'}
  - 位置: {param.get('in', 'body')}
"""

            rule_engine_context += """

**你的任务是**:
1. **验证和补充**: 检查规则引擎提取的参数是否准确、完整
2. **智能判断**: 如果发现参数信息不完整或有错误,请补充或纠正
3. **添加示例值**: 为每个参数提供合理的示例值
4. **完善描述**: 如果参数描述不清晰,请改进描述
5. **识别遗漏**: 如果发现代码中有其他参数但规则引擎未提取,请补充

**重要**: 请基于代码实际内容和规则引擎提供的信息做出判断,不要凭空猜测。
"""

        prompt = f"""你是一个资深的代码架构师和API设计专家，请深入分析以下代码文件。

技术栈信息：
- 语言：{', '.join(tech_stack.languages)}
- 框架：{', '.join(tech_stack.frameworks)}
- 构建工具：{', '.join(tech_stack.build_tools)}

请重点关注：
{chr(10).join(focus_text)}
{rule_engine_context}

代码文件：

{chr(10).join(files_text)}

请以JSON格式返回详细的分析结果，结构如下：
{{
  "apis": [
    {{
      "method": "GET|POST|PUT|DELETE|PATCH",
      "path": "/api/users/{{id}}",
      "description": "详细描述这个API的功能",
      "file": "文件路径",
      "line_number": 行号(数字),
      "parameters": [
        {{
          "name": "id",
          "type": "string|number|boolean|object|array",
          "description": "用户ID",
          "required": true,
          "in": "path|query|body",
          "example": "示例值"
        }}
      ],
      "request_body": {{
        "type": "object",
        "properties": {{}},
        "example": {{}}
      }},
      "response": {{
        "200": {{
          "description": "成功",
          "example": {{}}
        }},
        "404": {{
          "description": "未找到"
        }}
      }},
      "authentication": "JWT|Basic|None",
      "examples": [
        {{
          "language": "typescript",
          "code": "示例代码"
        }}
      ]
    }}
  ],
  "business_logic": [
    {{
      "name": "功能名称",
      "description": "详细描述功能的业务价值和实现逻辑",
      "file": "文件路径",
      "line_number": 行号(数字),
      "importance": "high|medium|low",
      "code_snippet": "关键代码片段（精简到20-30行）"
    }}
  ],
  "data_models": [
    {{
      "name": "模型名称",
      "file": "文件路径",
      "line_number": 行号(数字),
      "fields": [
        {{
          "name": "id",
          "type": "number|string|boolean|Date",
          "description": "字段描述",
          "required": true,
          "default": null
        }}
      ],
      "relations": ["关联的其他模型名称"],
      "indexes": ["索引字段"],
      "validation": ["验证规则"]
    }}
  ],
  "components": [
    {{
      "name": "组件名称",
      "type": "页面|组件|布局|HOC",
      "file": "文件路径",
      "line_number": 行号(数字),
      "props": [
        {{
          "name": "title",
          "type": "string",
          "required": true,
          "description": "标题"
        }}
      ],
      "usage": "使用说明和示例",
      "dependencies": ["依赖的其他组件"]
    }}
  ]
}}

重要要求：
1. API路径要完整准确，包括路径参数
2. 每个元素都要包含line_number字段（代码所在行号）
3. 描述要详细具体，突出业务价值
4. request_body和response要包含example
5. code_snippet要选择最核心的代码片段
6. 只返回JSON，不要其他解释
7. 如果某个类别没有发现内容，返回空数组
8. **参数信息**: 为每个参数添加example字段，提供合理的示例值
9. **基于规则引擎信息**: 如果规则引擎已提取参数，请验证、补充和完善这些信息
"""
        return prompt


class DocumentGenerator:
    """文档生成器（增强版）"""

    def __init__(self, repo_path: Path, output_dir: Path, claude_client=None):
        self.repo_path = repo_path
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.claude_client = claude_client  # 用于LLM增强

    def generate_all(
        self,
        tech_stack: TechStack,
        analysis: AnalysisResult,
        git_analysis: Optional[GitAnalysis] = None
    ):
        """生成所有文档"""
        logger.info(f"生成文档到: {self.output_dir}")

        # 1. 项目概述（包含项目级别LLM分析）
        self._generate_context(tech_stack, git_analysis, analysis)

        # 2. API完整清单
        self._generate_api_inventory(analysis.apis, tech_stack)

        # 3. 架构文档
        self._generate_architecture(analysis, tech_stack)

        # 4. 数据模型
        self._generate_data_models(analysis.data_models)

        # 5. 集成指南
        self._generate_integration_guide(analysis.apis, tech_stack)

        # 6. Skills文件
        self._generate_skills(analysis.skills, tech_stack)

        # 7. 开发团队信息
        if git_analysis:
            self._generate_team_info(git_analysis)

        # 8. Git分支信息
        if git_analysis:
            self._generate_branch_info(git_analysis)

        # 9. 配置文件
        self._generate_config(tech_stack, analysis, git_analysis)

        logger.info("✅ 文档生成完成！")

    def _generate_project_overview_with_llm(self, analysis: AnalysisResult, tech_stack: TechStack) -> Optional[Dict]:
        """使用LLM生成项目级别概述"""
        if not self.claude_client:
            return None

        # 准备API摘要（用于LLM分析）
        api_summary = []
        for api in analysis.apis[:30]:  # 只分析前30个API作为样本
            api_summary.append({
                'method': api.method,
                'path': api.path,
                'description': api.description
            })

        # 准备业务逻辑摘要
        business_summary = []
        for logic in analysis.business_logic[:10]:
            business_summary.append({
                'name': logic.name,
                'description': logic.description,
                'importance': logic.importance
            })

        prompt = f"""你是一个资深的软件架构师和技术文档专家。请基于以下API和业务逻辑分析，生成这个项目的整体概述。

## 项目技术栈
- **语言**: {', '.join(tech_stack.languages)}
- **框架**: {', '.join(tech_stack.frameworks) if tech_stack.frameworks else '未知'}
- **总API数**: {len(analysis.apis)}
- **业务逻辑模块数**: {len(analysis.business_logic)}

## API样本 (前30个)
{json.dumps(api_summary, indent=2, ensure_ascii=False)}

## 业务逻辑样本
{json.dumps(business_summary, indent=2, ensure_ascii=False)}

## 你的任务

请分析这个项目并生成以下内容：

1. **项目简介** (2-3句话): 这个项目是做什么的？
2. **核心功能模块** (3-5个): 主要的业务模块有哪些？
3. **适用场景** (3-5个): 这个系统适用于哪些场景？
4. **业务价值** (2-3句话): 这个系统为什么存在？解决什么问题？

## 输出格式

请以JSON格式返回，只返回JSON不要其他解释:

```json
{{
  "project_intro": "项目简介文字...",
  "core_modules": [
    {{
      "name": "用户管理",
      "description": "负责用户注册、认证、权限管理等功能"
    }}
  ],
  "use_cases": [
    "教育机构的学生和教师管理",
    "企业内部的组织架构管理"
  ],
  "business_value": "业务价值描述..."
}}
```

**重要要求**:
- 项目简介要简洁准确，突出核心功能
- 核心功能模块要基于实际的API分布归纳
- 适用场景要具体实际
- 业务价值要体现系统的必要性
"""

        try:
            logger.info("使用LLM生成项目概述...")
            message = self.claude_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text

            # 解析JSON
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
            else:
                json_text = response_text

            result = json.loads(json_text)
            logger.info("✓ 项目概述生成成功")
            return result

        except Exception as e:
            logger.warning(f"LLM生成项目概述失败: {e}")
            return None

    def _generate_context(self, tech_stack: TechStack, git_analysis: Optional[GitAnalysis], analysis: Optional[AnalysisResult] = None):
        """生成项目概述"""
        content = f"""# 项目概述

## 基本信息

- **项目路径**: `{self.repo_path}`
- **分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        if git_analysis:
            current_branch = next((b for b in git_analysis.branches if b.is_current), None)
            content += f"""
## Git信息

- **当前分支**: {current_branch.name if current_branch else 'N/A'}
- **总提交数**: {git_analysis.total_commits}
- **贡献者数**: {git_analysis.total_contributors}
- **最近提交**: {git_analysis.recent_commits[0].message if git_analysis.recent_commits else 'N/A'}
"""

        # 使用LLM生成项目概述（如果有分析结果）
        project_overview = None
        if analysis and self.claude_client:
            project_overview = self._generate_project_overview_with_llm(analysis, tech_stack)

        if project_overview:
            content += f"""
## 项目简介

{project_overview.get('project_intro', '暂无项目简介')}

## 核心功能模块

"""
            for module in project_overview.get('core_modules', []):
                content += f"### {module.get('name', '未知模块')}\n\n{module.get('description', '暂无描述')}\n\n"

            content += """
## 适用场景

"""
            for i, use_case in enumerate(project_overview.get('use_cases', []), 1):
                content += f"{i}. {use_case}\n"

            content += f"""

## 业务价值

{project_overview.get('business_value', '暂无业务价值描述')}
"""

        content += f"""

## 技术栈

### 编程语言
{chr(10).join(f'- **{lang}**' for lang in tech_stack.languages)}

### 框架
{chr(10).join(f'- {fw}' for fw in tech_stack.frameworks) if tech_stack.frameworks else '- 未检测到特定框架'}

### 主要依赖库
{chr(10).join(f'- {lib}' for lib in tech_stack.libraries[:15]) if tech_stack.libraries else '- 未检测到'}

### 构建工具
{chr(10).join(f'- {tool}' for tool in tech_stack.build_tools) if tech_stack.build_tools else '- 未检测到构建工具'}

## 项目特点

"""
        # 根据技术栈推断项目类型
        if 'React' in tech_stack.frameworks or 'Next' in tech_stack.frameworks:
            content += "- 🎨 现代化前端项目\n"
        if 'Express' in tech_stack.frameworks or 'Nestjs' in tech_stack.frameworks:
            content += "- 🔧 Node.js后端服务\n"
        if 'Spring' in tech_stack.frameworks or 'Springboot' in tech_stack.frameworks:
            content += "- ☕ Java企业级应用\n"
        if 'Python' in tech_stack.languages:
            content += "- 🐍 Python项目\n"

        content += """
---

*本文档由 Git2Skills https://github.com/mok_cn/Git2Skills 自动生成*
"""

        self._write_file('context.md', content)

    def _generate_api_inventory(self, apis: List[APIEndpoint], tech_stack: TechStack):
        """生成API完整清单"""
        if not apis:
            logger.warning("未发现API端点")
            return

        content = f"""# API完整清单

项目共有 **{len(apis)}** 个API端点。

## 目录

"""

        # 生成目录
        by_method = defaultdict(list)
        for api in apis:
            by_method[api.method].append(api)

        for method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']:
            if method in by_method:
                content += f"- [{method} 请求 ({len(by_method[method])}个)](#{ method.lower()}-请求)\n"

        content += "\n---\n\n"

        # 详细列表
        for method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']:
            if method not in by_method:
                continue

            content += f"## {method} 请求\n\n"

            for i, api in enumerate(by_method[method], 1):
                content += f"""### {i}. {api.description or api.path}

**端点**: `{method} {api.path}`

**文件**: `{api.file}`{f" (行 {api.line_number})" if api.line_number else ""}

"""
                # 认证
                if api.authentication:
                    content += f"**认证**: {api.authentication}\n\n"

                # 参数
                if api.parameters:
                    content += "**参数**:\n\n"
                    content += "| 名称 | 类型 | 位置 | 必需 | 描述 |\n"
                    content += "|------|------|------|------|------|\n"
                    for param in api.parameters:
                        required = "✅" if param.get('required') else "❌"
                        param_in = param.get('in', 'query')
                        content += f"| `{param['name']}` | {param.get('type', 'any')} | {param_in} | {required} | {param.get('description', '')} |\n"
                    content += "\n"

                # 请求体
                if api.request_body:
                    content += f"""**请求体**:

```json
{json.dumps(api.request_body, indent=2, ensure_ascii=False)}
```

"""

                # 响应
                if api.response:
                    content += f"""**响应**:

```json
{json.dumps(api.response, indent=2, ensure_ascii=False)}
```

"""

                # 调用示例
                content += self._generate_detailed_api_example(api, tech_stack)
                content += "\n---\n\n"

        self._write_file('api-inventory.md', content)

    def _generate_detailed_api_example(self, api: APIEndpoint, tech_stack: TechStack) -> str:
        """生成详细的API调用示例"""
        examples = "**调用示例**:\n\n"

        # JavaScript/TypeScript示例
        if any(lang in tech_stack.languages for lang in ['JavaScript', 'TypeScript']):
            examples += f"""<details>
<summary>JavaScript/TypeScript</summary>

```typescript
// 使用fetch API
const response = await fetch('{api.path}', {{
  method: '{api.method}',
  headers: {{
    'Content-Type': 'application/json',"""

            if api.authentication == 'JWT':
                examples += "\n    'Authorization': `Bearer ${token}`,"""

            examples += "\n  },"

            if api.request_body:
                examples += f"\n  body: JSON.stringify({json.dumps(api.request_body, ensure_ascii=False)}),"

            examples += """
});

if (!response.ok) {
  throw new Error(`API Error: ${response.statusText}`);
}

const data = await response.json();
console.log(data);
```

</details>

"""

        # Python示例
        if 'Python' in tech_stack.languages:
            examples += f"""<details>
<summary>Python</summary>

```python
import requests

headers = {{
    'Content-Type': 'application/json',"""

            if api.authentication == 'JWT':
                examples += "\n    'Authorization': f'Bearer {token}',"

            examples += "\n}\n"

            if api.request_body:
                examples += f"\ndata = {json.dumps(api.request_body, ensure_ascii=False)}\n"

            examples += f"""
response = requests.{api.method.lower()}(
    '{api.path}',
    headers=headers,"""

            if api.request_body:
                examples += "\n    json=data,"

            examples += """
)

response.raise_for_status()
result = response.json()
print(result)
```

</details>

"""

        # cURL示例
        curl_cmd = f"curl -X {api.method} '{api.path}' \\\n  -H 'Content-Type: application/json'"

        if api.authentication == 'JWT':
            curl_cmd += " \\\n  -H 'Authorization: Bearer YOUR_TOKEN'"

        if api.request_body:
            curl_cmd += f" \\\n  -d '{json.dumps(api.request_body, ensure_ascii=False)}'"

        examples += f"""<details>
<summary>cURL</summary>

```bash
{curl_cmd}
```

</details>

"""

        return examples

    def _generate_architecture(self, analysis: AnalysisResult, tech_stack: TechStack):
        """生成架构文档"""
        content = f"""# 系统架构

## 技术架构

### 技术栈
- **语言**: {', '.join(tech_stack.languages)}
- **框架**: {', '.join(tech_stack.frameworks) if tech_stack.frameworks else '无'}
- **构建工具**: {', '.join(tech_stack.build_tools) if tech_stack.build_tools else '无'}

## 核心模块统计

| 模块 | 数量 |
|------|------|
| API端点 | {len(analysis.apis)} |
| 业务逻辑 | {len(analysis.business_logic)} |
| 数据模型 | {len(analysis.data_models)} |
| 组件 | {len(analysis.components)} |
| Skills | {len(analysis.skills)} |

## API层

共 **{len(analysis.apis)}** 个API端点

### 按HTTP方法分布
"""
        # 统计API方法
        method_count = Counter(api.method for api in analysis.apis)
        for method, count in method_count.most_common():
            content += f"- **{method}**: {count} 个\n"

        content += f"""
## 业务逻辑层

### 重要业务逻辑

"""
        high_importance = [l for l in analysis.business_logic if l.importance == 'high']
        for logic in high_importance[:10]:
            content += f"- **{logic.name}** ({logic.file})\n  {logic.description}\n\n"

        if len(analysis.business_logic) > 10:
            content += f"*... 还有 {len(analysis.business_logic) - 10} 个业务逻辑*\n\n"

        content += f"""
## 数据模型层

共 **{len(analysis.data_models)}** 个数据模型

"""
        for model in analysis.data_models[:15]:
            content += f"- **{model.name}**: {len(model.fields)} 个字段"
            if model.relations:
                content += f", 关联 {len(model.relations)} 个模型"
            content += "\n"

        if len(analysis.data_models) > 15:
            content += f"\n*... 还有 {len(analysis.data_models) - 15} 个数据模型*\n"

        content += f"""
## 组件结构

共 **{len(analysis.components)}** 个组件

"""
        comp_by_type = defaultdict(list)
        for comp in analysis.components:
            comp_by_type[comp.type].append(comp)

        for comp_type, comps in comp_by_type.items():
            content += f"\n### {comp_type}\n\n"
            for comp in comps[:10]:
                content += f"- **{comp.name}**: {comp.usage}\n"

        content += """
---

*本文档由 Git2Skills https://github.com/mok_cn/Git2Skills 自动生成*
"""

        self._write_file('architecture.md', content)

    def _generate_data_models(self, models: List[DataModel]):
        """生成数据模型文档"""
        if not models:
            logger.warning("未发现数据模型")
            return

        content = f"""# 数据模型

项目共有 **{len(models)}** 个数据模型。

"""

        for model in models:
            content += f"""## {model.name}

**文件**: `{model.file}`{f" (行 {model.line_number})" if model.line_number else ""}

### 字段

| 字段名 | 类型 | 必需 | 描述 |
|-------|------|------|------|
"""
            for field in model.fields:
                required = "✅" if field.get('required') else "❌"
                default = f" (默认: {field['default']})" if field.get('default') else ""
                content += f"| {field.get('name', '')} | {field.get('type', '')} | {required} | {field.get('description', '')}{default} |\n"

            if model.relations:
                content += f"\n### 关联\n\n"
                for rel in model.relations:
                    content += f"- {rel}\n"

            content += "\n---\n\n"

        self._write_file('data-models.md', content)

    def _generate_integration_guide(self, apis: List[APIEndpoint], tech_stack: TechStack):
        """生成集成指南"""
        content = f"""# 集成指南

本指南说明如何在其他项目中集成和调用本项目的API。

## 快速开始

### 1. 配置服务地址

```bash
# .env
API_BASE_URL=http://localhost:3000  # 开发环境
# API_BASE_URL=https://api.example.com  # 生产环境
```

### 2. 安装依赖

"""

        if 'TypeScript' in tech_stack.languages or 'JavaScript' in tech_stack.languages:
            content += """```bash
npm install axios
# 或
npm install @tanstack/react-query  # 如果使用React
```

"""

        if 'Python' in tech_stack.languages:
            content += """```bash
pip install requests
# 或
pip install httpx  # 异步HTTP客户端
```

"""

        content += """### 3. 创建API客户端

"""

        # TypeScript客户端
        if 'TypeScript' in tech_stack.languages or 'JavaScript' in tech_stack.languages:
            content += """#### TypeScript/JavaScript 客户端

```typescript
// api-client.ts
import axios, { AxiosInstance } from 'axios';

export class APIClient {
  private client: AxiosInstance;

  constructor(baseURL: string, token?: string) {
    this.client = axios.create({
      baseURL,
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` }),
      },
    });
  }

  // 通用请求方法
  async request<T>(method: string, path: string, data?: any): Promise<T> {
    const response = await this.client.request<T>({
      method,
      url: path,
      data,
    });
    return response.data;
  }

"""
            # 为前5个API生成方法
            for api in apis[:5]:
                method_name = self._generate_method_name(api.path)
                params_list = self._extract_path_params(api.path)

                content += f"  // {api.description}\n"
                content += f"  async {method_name}("

                if params_list:
                    content += ', '.join(f"{p}: string" for p in params_list)

                if api.request_body:
                    if params_list:
                        content += ', '
                    content += 'data: any'

                content += ") {\n"

                path_with_template = api.path
                for param in params_list:
                    path_with_template = path_with_template.replace(f'{{{param}}}', f'${{{param}}}')

                content += f"    return this.request('{api.method}', `{path_with_template}`"

                if api.request_body:
                    content += ", data"

                content += ");\n  }\n\n"

            content += """
}

// 使用示例
const client = new APIClient(
  process.env.API_BASE_URL || 'http://localhost:3000',
  'your-jwt-token'  // 可选
);

export default client;
```

"""

        # Python客户端
        if 'Python' in tech_stack.languages:
            content += """#### Python 客户端

```python
# api_client.py
import requests
from typing import Optional, Dict, Any

class APIClient:
    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

        if token:
            self.session.headers.update({'Authorization': f'Bearer {token}'})

    def request(self, method: str, path: str, data: Optional[Dict] = None) -> Any:
        url = f"{self.base_url}{path}"
        response = self.session.request(method, url, json=data)
        response.raise_for_status()
        return response.json()

"""
            for api in apis[:3]:
                method_name = self._generate_method_name(api.path).replace('_', '_')
                content += f"    def {method_name}(self"

                params_list = self._extract_path_params(api.path)
                if params_list:
                    content += ', ' + ', '.join(f"{p}: str" for p in params_list)

                if api.request_body:
                    content += ', data: Dict'

                content += f"):\n"
                content += f"        \"\"\"{ api.description}\"\"\"\n"

                path_with_format = api.path
                for param in params_list:
                    path_with_format = path_with_format.replace(f'{{{param}}}', f'{{{param}}}')

                content += f"        return self.request('{api.method}', f'{path_with_format}'"

                if api.request_body:
                    content += ", data"

                content += ")\n\n"

            content += """

# 使用示例
client = APIClient('http://localhost:3000', token='your-jwt-token')
```

"""

        content += """## API认证

"""
        # 检查是否有认证
        auth_types = set(api.authentication for api in apis if api.authentication)
        if auth_types:
            content += "本项目使用以下认证方式:\n\n"
            for auth in auth_types:
                content += f"- **{auth}**\n"
            content += "\n请联系API管理员获取访问令牌。\n\n"
        else:
            content += "本项目暂未检测到统一的认证机制，请查看具体API文档。\n\n"

        content += """## 错误处理

API使用标准HTTP状态码：

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 201 | 资源创建成功 |
| 400 | 请求参数错误 |
| 401 | 未授权 / 令牌无效 |
| 403 | 禁止访问 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

### 错误响应格式

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述",
    "details": {}
  }
}
```

## 完整API列表

详细的API文档请参考 [API清单](./api-inventory.md)。

---

*本文档由 Git2Skills https://github.com/mok_cn/Git2Skills 自动生成*
"""

        self._write_file('integration-guide.md', content)

    def _generate_method_name(self, path: str) -> str:
        """从API路径生成方法名"""
        parts = path.split('/')
        parts = [p for p in parts if p and not p.startswith('{')]

        if len(parts) < 2:
            return 'request'

        # 转换为驼峰命名
        method_name = parts[-1]
        if len(parts) >= 2:
            method_name = parts[-2] + method_name.capitalize()

        return method_name.replace('-', '_')

    def _extract_path_params(self, path: str) -> List[str]:
        """提取路径参数"""
        import re
        return re.findall(r'\{(\w+)\}', path)

    def _generate_skills(self, skills: List[Skill], tech_stack: TechStack):
        """生成Skills文件"""
        skills_dir = self.output_dir / 'skills'
        skills_dir.mkdir(exist_ok=True)

        # 按类型分组
        skills_by_type = defaultdict(list)
        for skill in skills:
            skills_by_type[skill.type].append(skill)

        # 生成JSON格式
        skills_json = []
        for skill in skills:
            skill_dict = {
                'id': skill.id,
                'name': skill.name,
                'type': skill.type,
                'description': skill.description,
                'category': skill.category,
                'file': skill.file,
                'line_number': skill.line_number,
                'code_snippet': skill.code_snippet,
                'usage_example': skill.usage_example,
                'parameters': skill.parameters,
                'dependencies': skill.dependencies,
                'tags': skill.tags,
                'complexity': skill.complexity,
                'reuse_potential': skill.reuse_potential,
                # 新增字段
                'business_context': skill.business_context,
                'use_cases': skill.use_cases,
                'related_skills': skill.related_skills,
                'best_practices': skill.best_practices,
                'common_issues': skill.common_issues
            }
            skills_json.append(skill_dict)

        with open(skills_dir / 'skills.json', 'w', encoding='utf-8') as f:
            json.dump(skills_json, f, indent=2, ensure_ascii=False)

        # 生成Markdown文档
        md_content = f"""# Skills集合

本项目共有 **{len(skills)}** 个可复用的Skills。

## 统计

"""
        for skill_type, type_skills in skills_by_type.items():
            md_content += f"- **{skill_type}**: {len(type_skills)} 个\n"

        md_content += "\n## Skills列表\n\n"

        # 按类型列出
        for skill_type, type_skills in sorted(skills_by_type.items()):
            md_content += f"\n### {skill_type.upper()}\n\n"

            for skill in type_skills:
                md_content += f"#### {skill.name}\n\n"
                md_content += f"**描述**: {skill.description}\n\n"

                # 业务背景
                if skill.business_context:
                    md_content += f"**业务背景**: {skill.business_context}\n\n"

                md_content += f"**文件**: `{skill.file}`{f' (行 {skill.line_number})' if skill.line_number else ''}\n\n"
                md_content += f"**分类**: {skill.category} | **复杂度**: {skill.complexity} | **复用潜力**: {skill.reuse_potential}\n\n"

                if skill.tags:
                    md_content += f"**标签**: {', '.join(f'`{tag}`' for tag in skill.tags)}\n\n"

                # 适用场景
                if skill.use_cases:
                    md_content += "**适用场景**:\n"
                    for use_case in skill.use_cases:
                        md_content += f"- {use_case}\n"
                    md_content += "\n"

                if skill.parameters:
                    md_content += "**参数**:\n"
                    for param in skill.parameters:
                        md_content += f"- `{param.get('name')}` ({param.get('type', 'any')}): {param.get('description', '')}\n"
                    md_content += "\n"

                # 最佳实践
                if skill.best_practices:
                    md_content += f"**最佳实践**: {skill.best_practices}\n\n"

                # 常见问题
                if skill.common_issues:
                    md_content += "**常见问题**:\n"
                    for issue in skill.common_issues:
                        md_content += f"- ⚠️ {issue}\n"
                    md_content += "\n"

                # 相关Skills
                if skill.related_skills:
                    md_content += f"**相关Skills**: {', '.join(f'`{rs}`' for rs in skill.related_skills)}\n\n"

                if skill.usage_example:
                    md_content += f"**使用示例**:\n\n```{tech_stack.languages[0].lower() if tech_stack.languages else 'text'}\n{skill.usage_example}\n```\n\n"

                md_content += "---\n\n"

        with open(skills_dir / 'skills.md', 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"生成 {len(skills)} 个Skills (JSON + Markdown)")

    def _generate_team_info(self, git_analysis: GitAnalysis):
        """生成开发团队信息"""
        content = f"""# 开发团队信息

## 统计概览

- **总贡献者**: {len(git_analysis.developers)}
- **总提交数**: {git_analysis.total_commits}
- **活跃开发者**: {len([d for d in git_analysis.developers if d.commits >= 10])}

## 开发人员列表

### Top 贡献者

"""
        for i, dev in enumerate(git_analysis.developers[:10], 1):
            content += f"""#### {i}. {dev.name}

- **邮箱**: {dev.email}
- **提交数**: {dev.commits} 次
- **代码变更**:
  - 新增: {dev.lines_added} 行
  - 删除: {dev.lines_deleted} 行
  - 文件数: {dev.files_changed}
- **活跃天数**: {dev.active_days} 天
- **首次提交**: {dev.first_commit[:10]}
- **最后提交**: {dev.last_commit[:10]}

---

"""

        if len(git_analysis.developers) > 10:
            content += f"\n### 其他贡献者 ({len(git_analysis.developers) - 10}人)\n\n"
            content += "| 姓名 | 提交数 | 代码行数 |\n"
            content += "|------|--------|----------|\n"
            for dev in git_analysis.developers[10:]:
                content += f"| {dev.name} | {dev.commits} | +{dev.lines_added}/-{dev.lines_deleted} |\n"

        content += """
---

*本文档由 Git2Skills https://github.com/mok_cn/Git2Skills 自动生成*
"""

        self._write_file('team-info.md', content)

    def _generate_branch_info(self, git_analysis: GitAnalysis):
        """生成Git分支信息"""
        content = f"""# Git分支信息

## 分支列表

共 **{len(git_analysis.branches)}** 个分支。

"""
        for branch in git_analysis.branches:
            status = "✅ 当前" if branch.is_current else ""
            content += f"""### {branch.name} {status}

- **提交数**: {branch.commit_count}
- **最后提交**: {branch.last_commit}
- **提交时间**: {branch.last_commit_date}
- **提交者**: {branch.last_author}

---

"""

        content += f"""
## 最近提交 (最新20条)

"""
        for i, commit in enumerate(git_analysis.recent_commits, 1):
            content += f"""### {i}. {commit.message}

- **SHA**: {commit.sha}
- **作者**: {commit.author} ({commit.email})
- **时间**: {commit.date}
- **变更**: {commit.files_changed} 个文件, +{commit.insertions}/-{commit.deletions} 行

---

"""

        # 提交频率图表
        if git_analysis.commit_frequency:
            content += "\n## 提交频率\n\n"
            content += "| 日期 | 提交数 |\n"
            content += "|------|--------|\n"

            # 只显示最近30天
            recent_dates = sorted(git_analysis.commit_frequency.keys(), reverse=True)[:30]
            for date in reversed(recent_dates):
                count = git_analysis.commit_frequency[date]
                bar = "█" * min(count, 20)
                content += f"| {date} | {bar} {count} |\n"

        content += """
---

*本文档由 Git2Skills https://github.com/mok_cn/Git2Skills 自动生成*
"""

        self._write_file('git-branches.md', content)

    def _generate_config(self, tech_stack: TechStack, analysis: AnalysisResult, git_analysis: Optional[GitAnalysis]):
        """生成配置文件"""
        config = {
            'version': '2.0.0',
            'generated_at': datetime.now().isoformat(),
            'project_info': {
                'path': str(self.repo_path),
                'tech_stack': {
                    'languages': tech_stack.languages,
                    'frameworks': tech_stack.frameworks,
                    'libraries': tech_stack.libraries[:20],  # 限制数量
                    'build_tools': tech_stack.build_tools
                }
            },
            'statistics': {
                'apis': len(analysis.apis),
                'business_logic': len(analysis.business_logic),
                'data_models': len(analysis.data_models),
                'components': len(analysis.components),
                'skills': len(analysis.skills)
            },
            'documents': [
                'context.md',
                'api-inventory.md',
                'architecture.md',
                'data-models.md',
                'integration-guide.md',
                'skills/skills.json',
                'skills/skills.md'
            ]
        }

        if git_analysis:
            config['git_info'] = {
                'total_commits': git_analysis.total_commits,
                'total_contributors': git_analysis.total_contributors,
                'branches': len(git_analysis.branches)
            }
            config['documents'].extend(['team-info.md', 'git-branches.md'])

        with open(self.output_dir / 'aisdlc.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def _write_file(self, filename: str, content: str):
        """写入文件"""
        file_path = self.output_dir / filename
        file_path.parent.mkdir(exist_ok=True, parents=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"✓ {filename}")


def main():
    parser = argparse.ArgumentParser(
        description='Git2Skills https://github.com/mok_cn/Git2Skills 代码库分析脚本 (增强版)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 分析本地仓库
  python analyze_repo_enhanced.py --repo-path=/path/to/repo --claude-api-key=sk-xxx
  python analyze_repo_enhanced.py --repo-path=. --output-dir=./output --depth=deep

  # 分析远程Git仓库
  python analyze_repo_enhanced.py --git-url=https://github.com/user/repo.git --claude-api-key=sk-xxx
  python analyze_repo_enhanced.py --git-url=https://github.com/user/repo.git --branch=develop --keep-clone
        """
    )

    parser.add_argument(
        '--repo-path',
        default=None,
        help='本地代码库路径'
    )

    parser.add_argument(
        '--git-url',
        default=None,
        help='Git仓库URL (支持GitHub/GitLab/Gitee)'
    )

    parser.add_argument(
        '--branch',
        default=None,
        help='指定Git分支 (配合--git-url使用)'
    )

    parser.add_argument(
        '--clone-depth',
        type=int,
        default=1,
        help='克隆深度 (默认: 1=浅克隆, 0=完整历史)'
    )

    parser.add_argument(
        '--keep-clone',
        action='store_true',
        help='保留克隆的临时目录 (默认: 分析后删除)'
    )

    parser.add_argument(
        '--claude-api-key',
        default=None,
        help='Claude API密钥 (也可以通过环境变量 CLAUDE_API_KEY 设置)'
    )

    parser.add_argument(
        '--output-dir',
        default=None,
        help='输出目录 (默认: 脚本所在目录/aisdlc-output)'
    )

    parser.add_argument(
        '--depth',
        choices=['shallow', 'medium', 'deep'],
        default='medium',
        help='分析深度 (默认: medium)'
    )

    parser.add_argument(
        '--focus',
        default='api,business,model,component',
        help='关注领域，逗号分隔 (默认: api,business,model,component)'
    )

    parser.add_argument(
        '--git-days',
        type=int,
        default=90,
        help='Git历史分析天数 (默认: 90天, 0=全部历史)'
    )

    parser.add_argument(
        '--code-since-days',
        type=int,
        default=0,
        help='只分析最近N天修改的代码 (默认: 0=全量分析, 365=最近1年)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='详细输出'
    )

    args = parser.parse_args()

    # ========== 立即输出，让用户知道程序已启动 ==========
    print("=" * 70)
    print("🚀 Git2Skills https://github.com/mok_cn/Git2Skills 代码库分析工具 (增强版 v2.3)")
    print("=" * 70)
    print("⏳ 正在初始化...")
    sys.stdout.flush()  # 强制刷新输出

    # 验证参数: 必须提供 repo-path 或 git-url 之一
    if not args.repo_path and not args.git_url:
        parser.error("必须提供 --repo-path 或 --git-url 之一")
    if args.repo_path and args.git_url:
        parser.error("--repo-path 和 --git-url 不能同时使用")

    # 设置日志级别
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # 确定输出目录 (默认为当前目录/aisdlc-output)
    if args.output_dir is None:
        args.output_dir = Path.cwd() / 'aisdlc-output'

    print(f"📂 输出目录: {args.output_dir}")
    sys.stdout.flush()

    # 使用智能API配置检测
    smart_api_key, smart_base_url = get_smart_api_config()

    # 获取Claude API密钥 (优先级: 命令行参数 > 智能检测 > 环境变量)
    claude_api_key = args.claude_api_key or smart_api_key

    if not claude_api_key:
        print("\n❌ 错误: 未提供Claude API密钥")
        print("\n请通过以下方式之一提供:")
        print("  1. 命令行参数: --claude-api-key=sk-ant-xxx")
        print("  2. Windows用户环境变量 (推荐)")
        print("  3. 环境变量: export CLAUDE_API_KEY=sk-ant-xxx")
        print("  4. 环境变量: export ANTHROPIC_API_KEY=sk-ant-xxx")
        print("  5. 环境变量: export ANTHROPIC_AUTH_TOKEN=sk-ant-xxx")
        sys.exit(1)

    print("✓ API密钥已配置")
    sys.stdout.flush()

    # 获取BASE_URL (优先级: 智能检测 > 环境变量)
    anthropic_base_url = smart_base_url or os.getenv('ANTHROPIC_BASE_URL')
    if anthropic_base_url:
        print(f"🌐 使用自定义API端点: {anthropic_base_url}")
        sys.stdout.flush()

    # 确定仓库路径
    repo_path = None
    is_temp_clone = False

    try:
        print("\n" + "=" * 70)
        print("开始分析...")
        print("=" * 70)
        sys.stdout.flush()

        # 如果提供了Git URL, 先克隆到本地
        if args.git_url:
            print(f"\n🔗 检测到Git URL: {args.git_url}")
            sys.stdout.flush()

            if not GitCloner.is_git_url(args.git_url):
                print("⚠️  URL格式可能不正确,但仍会尝试克隆...")
                sys.stdout.flush()

            print("📥 正在检查并克隆仓库...")
            sys.stdout.flush()

            repo_path, is_reused = GitCloner.clone_repository(
                git_url=args.git_url,
                target_dir=None,  # 使用临时目录
                branch=args.branch,
                depth=args.clone_depth,
                reuse_existing=True  # 默认复用已存在的克隆
            )
            is_temp_clone = True

            if not is_reused:
                print(f"✓ 仓库已克隆到: {repo_path}")
            else:
                print(f"✓ 使用已存在的克隆: {repo_path}")
            sys.stdout.flush()
        else:
            repo_path = args.repo_path
            print(f"\n📁 使用本地仓库: {repo_path}")
            sys.stdout.flush()

        # 1. Git分析
        print("\n🔍 步骤1/5: 分析Git仓库...")
        sys.stdout.flush()
        git_analyzer = GitAnalyzer(repo_path)
        git_analysis = git_analyzer.analyze(days=args.git_days)

        # 2. 项目结构分析
        print("🔍 步骤2/5: 扫描项目文件...")
        sys.stdout.flush()
        project_analyzer = ProjectAnalyzer(repo_path)
        all_files, tech_stack = project_analyzer.analyze()

        # 2.5 增量过滤（如果启用）
        if args.code_since_days > 0:
            print(f"🔍 步骤2.5/5: 应用增量过滤 (最近{args.code_since_days}天)...")
            sys.stdout.flush()
            project_analyzer.files = project_analyzer.filter_by_modification_time(args.code_since_days)
            print(f"   → 过滤后剩余 {len(project_analyzer.files)} 个文件")
            sys.stdout.flush()

        # 3. 智能文件选择 (LLM辅助)
        print("🔍 步骤3/5: 智能筛选核心业务文件 (LLM辅助)...")
        sys.stdout.flush()
        focus_areas = args.focus.split(',')
        max_files = {
            'shallow': 50,
            'medium': 100,
            'deep': 300
        }[args.depth]

        # 使用智能选择器
        from smart_file_selector import SmartFileSelector
        selector = SmartFileSelector(claude_client=claude.client if 'claude' in locals() else None)

        # 如果Claude还未初始化,先初始化
        if 'claude' not in locals():
            if anthropic_base_url:
                claude = ClaudeAnalyzer(claude_api_key, base_url=anthropic_base_url)
            else:
                claude = ClaudeAnalyzer(claude_api_key)

        selected_files = selector.select_files(
            project_analyzer.files,
            Path(repo_path),
            tech_stack,
            max_files=max_files,
            use_llm=True  # 启用LLM辅助决策
        )
        print(f"   → 已选择 {len(selected_files)} 个核心业务文件")
        sys.stdout.flush()

        # 4. Claude代码分析
        print("🔍 步骤4/5: Claude AI代码分析 (这可能需要几分钟)...")
        sys.stdout.flush()

        # 如果设置了自定义base_url, 传递给ClaudeAnalyzer
        if anthropic_base_url:
            claude = ClaudeAnalyzer(claude_api_key, base_url=anthropic_base_url)
        else:
            claude = ClaudeAnalyzer(claude_api_key)
        analysis = claude.analyze_code(
            selected_files,
            tech_stack,
            focus_areas,
            Path(repo_path)
        )

        print("\n" + "=" * 70)
        print("✅ 代码分析完成!")
        print("=" * 70)
        print(f"📊 分析结果统计:")
        print(f"  • API端点: {len(analysis.apis)} 个")
        print(f"  • 业务逻辑: {len(analysis.business_logic)} 个")
        print(f"  • 数据模型: {len(analysis.data_models)} 个")
        print(f"  • 组件: {len(analysis.components)} 个")
        print(f"  • Skills: {len(analysis.skills)} 个")

        if git_analysis:
            print(f"\n📈 Git统计:")
            print(f"  • 总提交数: {git_analysis.total_commits}")
            print(f"  • 贡献者: {git_analysis.total_contributors} 人")
            print(f"  • 分支数: {len(git_analysis.branches)}")

        print("=" * 70)
        sys.stdout.flush()

        # 5. 生成文档
        print("\n🔍 步骤5/5: 生成文档...")
        sys.stdout.flush()

        generator = DocumentGenerator(
            Path(repo_path),
            Path(args.output_dir),
            claude_client=claude.client  # Pass Claude client for project-level LLM
        )
        generator.generate_all(tech_stack, analysis, git_analysis)

        print("\n" + "=" * 70)
        print("🎉 分析完成!")
        print("=" * 70)
        print(f"\n📂 分析结果已保存到: {Path(args.output_dir).absolute()}")
        print("\n📄 生成的文档:")
        docs = [
            'context.md              # 项目概述',
            'api-inventory.md        # API完整清单 ⭐',
            'architecture.md         # 架构文档',
            'data-models.md          # 数据模型',
            'integration-guide.md    # 集成指南 ⭐',
            'skills/skills.json      # Skills集合(JSON)',
            'skills/skills.md        # Skills文档(MD)',
            'aisdlc.json            # 配置文件'
        ]
        if git_analysis:
            docs.extend([
                'team-info.md           # 开发团队信息',
                'git-branches.md        # Git分支历史'
            ])

        for doc in docs:
            print(f"  ✓ {doc}")

        print(f"\n💡 下一步:")
        print(f"  1. 查看文档: cd {args.output_dir}")
        print(f"  2. 集成到Claude Code: cp -r {args.output_dir}/* .claude/")
        print(f"  3. 上传到中心知识库 (需要Git2Skills https://github.com/mok_cn/Git2Skills平台)")

        if is_temp_clone and args.keep_clone:
            print(f"\n📦 克隆的仓库已保留在: {repo_path}")

        sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 分析失败: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        # 清理临时克隆的仓库
        if is_temp_clone and not args.keep_clone:
            GitCloner.cleanup(repo_path)


if __name__ == '__main__':
    main()
