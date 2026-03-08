#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能文件选择器 - 使用LLM辅助判断核心业务模块
通用、自适应的文件优先级算法
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
import logging

logger = logging.getLogger(__name__)


@dataclass
class FileFeatures:
    """文件特征"""
    path: str
    name: str
    lines: int

    # 代码特征
    api_count: int = 0  # API注解数量
    class_count: int = 0  # 类定义数量
    method_count: int = 0  # 方法数量
    import_count: int = 0  # 导入语句数量

    # 架构特征
    is_controller: bool = False
    is_service: bool = False
    is_model: bool = False
    is_config: bool = False
    is_util: bool = False

    # 复杂度指标
    cyclomatic_complexity: int = 0  # 循环复杂度估算
    dependency_score: int = 0  # 被依赖程度

    # 模块信息
    module_path: str = ""  # 所属模块路径
    depth: int = 0  # 目录深度


class FileAnalyzer:
    """文件特征分析器"""

    # API注解模式 (通用)
    API_PATTERNS = [
        # Spring
        r'@(Request|Get|Post|Put|Delete|Patch)Mapping',
        r'@RestController',
        r'@Controller',
        # Django
        r'@api_view',
        r'@action',
        # Express/Node
        r'(router|app)\.(get|post|put|delete|patch)',
        # FastAPI/Python
        r'@app\.(get|post|put|delete|patch)',
        r'@router\.(get|post|put|delete|patch)',
    ]

    # 架构层识别模式
    LAYER_PATTERNS = {
        'controller': [r'controller', r'route', r'api', r'handler', r'endpoint', r'view'],
        'service': [r'service', r'business', r'logic', r'manager', r'facade'],
        'model': [r'model', r'entity', r'schema', r'dto', r'dao', r'repository'],
        'config': [r'config', r'setting', r'properties'],
        'util': [r'util', r'helper', r'tool', r'common'],
    }

    @classmethod
    def analyze_file(cls, file_path: Path, content: str = None) -> FileFeatures:
        """分析单个文件特征"""

        # 读取内容
        if content is None:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception as e:
                logger.warning(f"无法读取文件 {file_path}: {e}")
                content = ""

        # 基本信息
        path_str = str(file_path)
        name = file_path.name
        lines = content.count('\n') + 1
        path_lower = path_str.lower()

        # 提取特征
        features = FileFeatures(
            path=path_str,
            name=name,
            lines=lines,
            depth=len(file_path.parts)
        )

        # === 1. 代码特征统计 ===

        # API注解数量
        for pattern in cls.API_PATTERNS:
            features.api_count += len(re.findall(pattern, content, re.IGNORECASE))

        # 类定义
        features.class_count = len(re.findall(r'\b(class|interface|enum)\s+\w+', content, re.IGNORECASE))

        # 方法定义 (简化估算)
        features.method_count = len(re.findall(r'\b(public|private|protected)\s+\w+\s+\w+\s*\(', content))

        # 导入语句
        features.import_count = len(re.findall(r'^(import|from|require|use)\s+', content, re.MULTILINE))

        # === 2. 架构层判断 ===

        for layer, patterns in cls.LAYER_PATTERNS.items():
            if any(re.search(pattern, path_lower) for pattern in patterns):
                setattr(features, f'is_{layer}', True)

        # === 3. 复杂度估算 ===

        # 循环复杂度 (简化: 统计控制流语句)
        control_flow = ['if', 'else', 'for', 'while', 'switch', 'case', 'catch', 'try']
        for keyword in control_flow:
            features.cyclomatic_complexity += len(re.findall(rf'\b{keyword}\b', content, re.IGNORECASE))

        # === 4. 模块路径提取 ===

        # 尝试识别主模块 (如 Unipus-SSO, license-gen 等)
        parts = Path(path_str).parts
        for i, part in enumerate(parts):
            # 通常模块名包含大写字母或连字符
            if re.match(r'^[A-Z]', part) or '-' in part:
                features.module_path = '/'.join(parts[:i+1])
                break

        return features

    @classmethod
    def analyze_project_batch(cls, file_paths: List[Path], max_files: int = 200) -> List[FileFeatures]:
        """批量分析项目文件 (只分析前N个,避免过慢)"""
        features_list = []

        for i, file_path in enumerate(file_paths[:max_files]):
            if i % 100 == 0:
                logger.info(f"预扫描进度: {i}/{min(len(file_paths), max_files)}")

            features = cls.analyze_file(file_path)
            features_list.append(features)

        return features_list


class SmartFileSelector:
    """智能文件选择器 (LLM辅助)"""

    def __init__(self, claude_client=None):
        """
        Args:
            claude_client: Anthropic client实例 (可选, 用于LLM决策)
        """
        self.claude_client = claude_client

    def select_files(
        self,
        all_files: List,  # FileInfo对象列表
        repo_path: Path,
        tech_stack,
        max_files: int = 100,
        use_llm: bool = True
    ) -> List:
        """
        智能选择文件进行深度分析

        Args:
            all_files: 所有文件列表 (FileInfo对象)
            repo_path: 仓库路径
            tech_stack: 技术栈信息
            max_files: 最多选择文件数
            use_llm: 是否使用LLM辅助决策

        Returns:
            优先级排序后的文件列表
        """

        logger.info(f"智能文件选择: 从 {len(all_files)} 个文件中选择 {max_files} 个")

        # === 阶段1: 预扫描,收集特征 ===
        logger.info("阶段1: 预扫描文件特征 (前200个Controller文件)...")

        # 优先扫描Controller文件
        controller_files = [f for f in all_files if 'controller' in f.path.lower()]
        other_files = [f for f in all_files if 'controller' not in f.path.lower()]

        # 选择前200个最有可能包含API的文件
        priority_files = (controller_files[:150] + other_files[:50])[:200]

        # 转换为Path列表并读取
        file_paths = [repo_path / f.path for f in priority_files]

        # 分析文件特征
        features_list = FileAnalyzer.analyze_project_batch(file_paths, max_files=len(file_paths))

        # 统计项目特征
        project_stats = self._analyze_project_stats(features_list)

        logger.info(f"项目特征统计: {json.dumps(project_stats, indent=2, ensure_ascii=False)}")

        # === 阶段2: LLM智能决策 (可选) ===
        if use_llm and self.claude_client and project_stats['total_apis'] > 0:
            logger.info("阶段2: LLM辅助决策...")

            try:
                llm_rankings = self._llm_assisted_ranking(
                    features_list,
                    project_stats,
                    tech_stack,
                    max_files
                )

                if llm_rankings:
                    # 使用LLM的排序结果
                    return self._apply_llm_rankings(all_files, llm_rankings)

            except Exception as e:
                logger.warning(f"LLM辅助决策失败,使用规则排序: {e}")

        # === 回退: 基于规则的排序 ===
        logger.info("使用增强规则排序...")
        return self._rule_based_ranking(all_files, features_list, project_stats, max_files)

    def _analyze_project_stats(self, features_list: List[FileFeatures]) -> Dict:
        """分析项目整体特征"""

        stats = {
            'total_files': len(features_list),
            'total_lines': sum(f.lines for f in features_list),
            'total_apis': sum(f.api_count for f in features_list),
            'architecture_layers': {
                'controller': sum(1 for f in features_list if f.is_controller),
                'service': sum(1 for f in features_list if f.is_service),
                'model': sum(1 for f in features_list if f.is_model),
            },
            'modules': {},  # 各模块统计
            'top_api_files': [],  # API最多的文件
        }

        # 按模块统计
        module_counter = Counter(f.module_path for f in features_list if f.module_path)
        stats['modules'] = dict(module_counter.most_common(10))

        # API最多的文件
        api_files = sorted(features_list, key=lambda f: f.api_count, reverse=True)
        stats['top_api_files'] = [
            {'path': f.path, 'apis': f.api_count, 'lines': f.lines}
            for f in api_files[:10] if f.api_count > 0
        ]

        return stats

    def _llm_assisted_ranking(
        self,
        features_list: List[FileFeatures],
        project_stats: Dict,
        tech_stack,
        max_files: int
    ) -> Optional[List[str]]:
        """使用LLM进行智能排序"""

        # 构建提示词
        prompt = self._build_llm_ranking_prompt(features_list, project_stats, tech_stack, max_files)

        # 调用Claude
        try:
            message = self.claude_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
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

            logger.info(f"LLM识别的核心模块: {result.get('core_modules', [])}")
            logger.info(f"LLM推荐文件数: {len(result.get('ranked_files', []))}")

            return result.get('ranked_files', [])

        except Exception as e:
            logger.error(f"LLM排序失败: {e}")
            return None

    def _build_llm_ranking_prompt(
        self,
        features_list: List[FileFeatures],
        project_stats: Dict,
        tech_stack,
        max_files: int
    ) -> str:
        """构建LLM排序提示词"""

        # 精简文件列表 (只发送前100个有意义的文件)
        significant_files = sorted(
            features_list,
            key=lambda f: (f.api_count * 10 + f.lines / 100),
            reverse=True
        )[:100]

        files_summary = []
        for f in significant_files:
            files_summary.append({
                'path': f.path,
                'lines': f.lines,
                'api_count': f.api_count,
                'is_controller': f.is_controller,
                'is_service': f.is_service,
                'module': f.module_path
            })

        prompt = f"""你是一个资深的软件架构师。请分析以下项目,识别核心业务模块和对外接口层。

## 项目技术栈
- 语言: {', '.join(tech_stack.languages)}
- 框架: {', '.join(tech_stack.frameworks) if tech_stack.frameworks else '未知'}

## 项目统计
- 总文件数: {project_stats['total_files']}
- 总代码行: {project_stats['total_lines']}
- 检测到的API端点: {project_stats['total_apis']}
- Controller层文件: {project_stats['architecture_layers']['controller']}
- Service层文件: {project_stats['architecture_layers']['service']}

## 主要模块
{json.dumps(project_stats['modules'], indent=2, ensure_ascii=False)}

## 候选文件列表 (前100个有意义的文件)
{json.dumps(files_summary, indent=2, ensure_ascii=False)}

## 你的任务

1. **识别核心业务模块**: 哪些模块是对外提供服务的核心业务?
2. **识别对外接口层**: 哪些文件包含REST API、RPC接口等对外接口?
3. **排序文件优先级**: 按重要性对文件排序,选出最重要的{max_files}个文件

## 判断标准

1. **对外接口层** (最高优先级):
   - 包含大量API注解的Controller文件
   - 对外暴露的服务入口
   - 大型Controller (>1000行, 通常包含很多API)

2. **核心业务逻辑层** (高优先级):
   - 实现核心业务功能的Service类
   - 包含重要业务算法的类
   - 被多处引用的核心类

3. **数据模型层** (中优先级):
   - 定义核心数据结构
   - ORM实体类
   - DTO/VO类

4. **配置和工具类** (低优先级):
   - 配置文件
   - 工具类
   - 基础设施代码

## 输出格式

请以JSON格式返回:

```json
{{
  "core_modules": ["模块1", "模块2"],
  "ranking_rationale": "简短说明判断依据",
  "ranked_files": [
    "最重要文件路径1",
    "最重要文件路径2",
    ...
    "文件路径{max_files}"
  ]
}}
```

**要求**:
- ranked_files 必须包含 {max_files} 个文件路径
- 路径必须来自候选文件列表
- 优先选择API数量多、代码行数大的Controller文件
- 只返回JSON,不要额外解释
"""

        return prompt

    def _apply_llm_rankings(self, all_files: List, llm_rankings: List[str]) -> List:
        """应用LLM的排序结果"""

        # 创建路径到FileInfo的映射
        file_map = {f.path: f for f in all_files}

        # 按LLM排序返回
        selected = []
        for path in llm_rankings:
            if path in file_map:
                selected.append(file_map[path])

        logger.info(f"LLM选择了 {len(selected)} 个文件")

        return selected

    def _rule_based_ranking(
        self,
        all_files: List,
        features_list: List[FileFeatures],
        project_stats: Dict,
        max_files: int
    ) -> List:
        """基于规则的增强排序 (无LLM时的回退方案)"""

        # 创建特征映射 - 使用文件名作为key (因为features_list中的path是绝对路径,而all_files中的path是相对路径)
        features_map = {Path(f.path).name: f for f in features_list}

        scored_files = []

        for file in all_files:
            score = 0
            # 使用文件名匹配特征
            features = features_map.get(Path(file.path).name)

            if not features:
                # 没有特征信息的文件,使用基础评分
                score = 1
            else:
                # === 增强评分规则 ===

                # 1. API数量 (最重要)
                score += features.api_count * 20

                # 2. 大文件奖励 (>1000行可能是核心文件)
                if features.lines > 2000:
                    score += 50
                elif features.lines > 1000:
                    score += 30
                elif features.lines > 500:
                    score += 15

                # 3. Controller层高优先级
                if features.is_controller:
                    score += 40

                # 4. Service层次优先级
                if features.is_service:
                    score += 25

                # 5. 复杂度奖励
                score += min(features.cyclomatic_complexity / 10, 20)

                # 6. 类和方法数量
                score += features.class_count * 5
                score += features.method_count * 2

            scored_files.append((score, file))

        # 排序
        scored_files.sort(key=lambda x: x[0], reverse=True)

        # 输出Top 10用于调试
        logger.info("增强规则排序 Top 10:")
        for i, (score, file) in enumerate(scored_files[:10], 1):
            features = features_map.get(Path(file.path).name)
            api_info = f", APIs: {features.api_count}" if features else ""
            logger.info(f"  {i}. [{score:.0f}分] {file.path} ({file.lines}行{api_info})")

        return [file for score, file in scored_files[:max_files]]
