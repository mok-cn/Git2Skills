#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规则引擎 - 基于规则的API提取器
支持自学习和规则迭代更新
"""

import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ExtractedAPI:
    """提取的API信息"""
    method: str
    path: str
    description: str = ""
    file: str = ""
    line_number: int = 0
    method_name: str = ""
    parameters: List[Dict] = None
    error_codes: List[Dict] = None
    confidence: float = 0.0
    extraction_source: str = "rule"  # rule | llm | hybrid

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = []
        if self.error_codes is None:
            self.error_codes = []


class RuleEngine:
    """规则引擎 - 负责基于规则提取API"""

    def __init__(self, rules_file: Path):
        """
        初始化规则引擎

        Args:
            rules_file: 规则配置文件路径
        """
        self.rules_file = rules_file
        self.rules = self._load_rules()

    def _load_rules(self) -> Dict:
        """加载规则配置"""
        try:
            with open(self.rules_file, 'r', encoding='utf-8') as f:
                rules = json.load(f)
            logger.info(f"✓ 加载规则配置: {self.rules_file}")
            logger.info(f"  版本: {rules.get('version', 'unknown')}")
            logger.info(f"  总模式数: {rules.get('statistics', {}).get('total_patterns', 0)}")
            return rules
        except FileNotFoundError:
            logger.warning(f"规则文件不存在: {self.rules_file}, 使用默认规则")
            return self._create_default_rules()
        except json.JSONDecodeError as e:
            logger.error(f"规则文件解析失败: {e}")
            return self._create_default_rules()

    def _create_default_rules(self) -> Dict:
        """创建默认规则"""
        return {
            "version": "1.0",
            "annotation_patterns": {
                "class_level": [],
                "method_level": [],
                "description_patterns": [],
                "parameter_patterns": []
            },
            "error_code_patterns": [],
            "learning_config": {"enable_auto_learning": True}
        }

    def extract_apis(
        self,
        file_content: str,
        file_path: str,
        max_confidence_threshold: float = 0.80,
        repo_path: Path = None
    ) -> Tuple[List[ExtractedAPI], float]:
        """
        从代码中提取API

        Args:
            file_content: 文件内容
            file_path: 文件路径
            max_confidence_threshold: 最大置信度阈值(超过则认为规则已足够好)
            repo_path: 仓库根路径(用于解析Request类)

        Returns:
            (提取的API列表, 平均置信度)
        """
        apis = []

        # 1. 提取类级别的RequestMapping路径
        class_path = self._extract_class_path(file_content)
        logger.debug(f"类路径: {class_path}")

        # 2. 提取所有方法级别的API
        method_apis = self._extract_method_apis(file_content, class_path, file_path)

        # 3. 为每个API补充描述
        for api in method_apis:
            self._enrich_api_description(api, file_content)
            self._extract_parameters(api, file_content, repo_path)  # 传递repo_path
            self._extract_error_codes(api, file_content)
            apis.append(api)

        # 4. 计算平均置信度
        avg_confidence = sum(api.confidence for api in apis) / len(apis) if apis else 0.0

        logger.info(f"规则提取: {len(apis)} 个API, 平均置信度: {avg_confidence:.2f}")

        return apis, avg_confidence

    def _extract_class_path(self, content: str) -> str:
        """提取类级别的路径"""
        patterns = self.rules.get('annotation_patterns', {}).get('class_level', [])

        for pattern_config in patterns:
            pattern = pattern_config.get('pattern')
            group_index = pattern_config.get('group_index', 1)

            match = re.search(pattern, content)
            if match:
                path = match.group(group_index)
                logger.debug(f"匹配类路径模式: {pattern_config['id']} -> {path}")
                return path

        return ""

    def _extract_method_apis(
        self,
        content: str,
        class_path: str,
        file_path: str
    ) -> List[ExtractedAPI]:
        """提取方法级别的API"""
        apis = []
        patterns = self.rules.get('annotation_patterns', {}).get('method_level', [])

        for pattern_config in patterns:
            pattern = pattern_config.get('pattern')
            confidence = pattern_config.get('confidence', 0.5)

            # 查找所有匹配
            for match in re.finditer(pattern, content, re.MULTILINE):
                try:
                    # 提取路径
                    path_group = pattern_config.get('path_group', 1)
                    method_path = match.group(path_group)

                    # 提取HTTP方法
                    if 'method_group' in pattern_config:
                        http_method = match.group(pattern_config['method_group'])
                    else:
                        http_method = pattern_config.get('method', 'UNKNOWN')

                    # 组装完整路径
                    full_path = class_path + method_path

                    # 尝试找到方法名
                    method_name = self._find_method_name(content, match.end())

                    # 计算行号
                    line_number = content[:match.start()].count('\n') + 1

                    api = ExtractedAPI(
                        method=http_method,
                        path=full_path,
                        file=file_path,
                        line_number=line_number,
                        method_name=method_name,
                        confidence=confidence,
                        extraction_source="rule"
                    )

                    apis.append(api)
                    logger.debug(f"提取API: {http_method} {full_path}")

                except Exception as e:
                    logger.warning(f"提取API失败: {e}")
                    continue

        return apis

    def _find_method_name(self, content: str, start_pos: int) -> str:
        """在注解后查找方法名"""
        # 向后查找200个字符内的方法定义
        snippet = content[start_pos:start_pos+200]

        patterns = self.rules.get('annotation_patterns', {}).get('method_signature_patterns', [])
        for pattern_config in patterns:
            pattern = pattern_config.get('pattern')
            name_group = pattern_config.get('method_name_group', 2)

            match = re.search(pattern, snippet)
            if match:
                return match.group(name_group)

        return "unknown"

    def _enrich_api_description(self, api: ExtractedAPI, content: str):
        """为API补充描述"""
        patterns = self.rules.get('annotation_patterns', {}).get('description_patterns', [])

        # 在API注解前200个字符内查找描述
        start_pos = max(0, content.find(api.path) - 200)
        snippet = content[start_pos:start_pos+400]

        for pattern_config in patterns:
            pattern = pattern_config.get('pattern')
            group_index = pattern_config.get('group_index', 1)

            match = re.search(pattern, snippet)
            if match:
                api.description = match.group(group_index)
                logger.debug(f"找到描述: {api.description}")
                break

    def _extract_parameters(self, api: ExtractedAPI, content: str, repo_path: Path = None):
        """提取API参数（包括 @RequestBody 引用的 Request 类）"""
        # 在方法定义附近查找参数注解
        patterns = self.rules.get('annotation_patterns', {}).get('parameter_patterns', [])

        # 找到方法定义位置（使用正则）
        method_pattern = rf'public\s+.*?\s+{re.escape(api.method_name)}\s*\([^)]*\)'
        method_match = re.search(method_pattern, content)

        if not method_match:
            return

        method_signature = method_match.group(0)

        # 1. 查找 @RequestParam 参数（原有逻辑）
        for pattern_config in patterns:
            pattern = pattern_config.get('pattern')

            for match in re.finditer(pattern, method_signature):
                try:
                    param_name = match.group(pattern_config.get('name_group', 1))
                    required = match.group(pattern_config.get('required_group', 2)) if pattern_config.get('required_group') else None

                    api.parameters.append({
                        'name': param_name,
                        'required': required == 'true' if required else None,
                        'in': 'query' if 'RequestParam' in pattern else 'query'
                    })
                except Exception as e:
                    logger.debug(f"提取参数失败: {e}")

        # 2. 查找 @RequestBody 引用的 Request 类
        request_body_pattern = r'@RequestBody\s+(\w+)'
        body_match = re.search(request_body_pattern, method_signature)

        if body_match and repo_path:
            request_class_name = body_match.group(1)
            logger.debug(f"检测到 @RequestBody {request_class_name}")

            # 解析 Request 类
            request_params = self._parse_request_class(request_class_name, repo_path)

            if request_params:
                # 将 Request 类的字段添加到 parameters
                for param in request_params:
                    param['in'] = 'body'
                api.parameters.extend(request_params)
                logger.debug(f"从 {request_class_name} 提取了 {len(request_params)} 个字段")

    def _parse_request_class(self, class_name: str, repo_path: Path) -> List[Dict]:
        """
        解析 Java Request/DTO 类，提取字段信息

        Args:
            class_name: 类名（如 AppUserInfoRequest）
            repo_path: 仓库根路径

        Returns:
            字段列表，每个字段包含 name, type, description, required
        """
        # 1. 搜索类文件
        class_file = self._find_request_class_file(class_name, repo_path)
        if not class_file:
            logger.debug(f"未找到 Request 类文件: {class_name}.java")
            return []

        logger.debug(f"找到 Request 类: {class_file}")

        # 2. 读取类文件内容
        try:
            content = class_file.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.warning(f"无法读取 Request 类文件: {e}")
            return []

        # 3. 提取字段信息
        fields = []

        # 正则模式：匹配字段定义
        # 支持格式：private Type fieldName;
        field_pattern = r'private\s+(\w+(?:<[\w,\s]+>)?)\s+(\w+)\s*;'

        # 正则模式：匹配 @ApiModelProperty 注解
        api_model_property_pattern = r'@ApiModelProperty\s*\(\s*value\s*=\s*"([^"]+)"'

        # 正则模式：匹配必填校验注解
        validation_pattern = r'@(NotNull|NotBlank|NotEmpty)\s*(?:\([^)]*\))?'

        # 按行处理，收集字段信息
        lines = content.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 检查是否是字段定义
            field_match = re.search(field_pattern, line)

            if field_match:
                field_type = field_match.group(1)
                field_name = field_match.group(2)

                # 向上查找注解（最多往前看10行）
                description = ""
                required = False

                for j in range(max(0, i-10), i):
                    prev_line = lines[j].strip()

                    # 查找 @ApiModelProperty
                    prop_match = re.search(api_model_property_pattern, prev_line)
                    if prop_match:
                        description = prop_match.group(1)

                    # 查找验证注解
                    if re.search(validation_pattern, prev_line):
                        required = True

                # 添加字段
                fields.append({
                    'name': field_name,
                    'type': self._map_java_type_to_generic(field_type),
                    'description': description,
                    'required': required
                })

                logger.debug(f"  字段: {field_name} ({field_type}) - {description}")

            i += 1

        logger.info(f"从 {class_name} 解析了 {len(fields)} 个字段")
        return fields

    def _find_request_class_file(self, class_name: str, repo_path: Path) -> Optional[Path]:
        """
        在仓库中搜索 Request 类文件

        优先查找路径：
        - **/dto/**/{class_name}.java
        - **/web/**/{class_name}.java
        - **/{class_name}.java
        """
        # 常见的 DTO 路径模式
        search_patterns = [
            f'**/dto/**/{class_name}.java',
            f'**/web/**/{class_name}.java',
            f'**/request/**/{class_name}.java',
            f'**/entity/**/{class_name}.java',
            f'**/{class_name}.java'
        ]

        for pattern in search_patterns:
            matches = list(repo_path.glob(pattern))
            if matches:
                return matches[0]  # 返回第一个匹配

        return None

    def _map_java_type_to_generic(self, java_type: str) -> str:
        """
        将 Java 类型映射为通用类型

        Args:
            java_type: Java 类型（如 Long, String, Integer）

        Returns:
            通用类型（如 number, string）
        """
        type_mapping = {
            'Long': 'number',
            'long': 'number',
            'Integer': 'number',
            'int': 'number',
            'Double': 'number',
            'double': 'number',
            'Float': 'number',
            'float': 'number',
            'String': 'string',
            'Boolean': 'boolean',
            'boolean': 'boolean',
            'Date': 'string',  # ISO date string
            'LocalDate': 'string',
            'LocalDateTime': 'string',
            'BigDecimal': 'number'
        }

        # 处理泛型类型（如 List<String>）
        base_type = java_type.split('<')[0]

        return type_mapping.get(base_type, 'string')  # 默认为 string

    def _extract_error_codes(self, api: ExtractedAPI, content: str):
        """提取错误码"""
        patterns = self.rules.get('error_code_patterns', [])

        # 在方法定义后2000字符内查找错误码
        method_pos = content.find(api.method_name)
        if method_pos == -1:
            return

        snippet = content[method_pos:method_pos+2000]

        for pattern_config in patterns:
            pattern = pattern_config.get('pattern')
            code_group = pattern_config.get('code_group', 1)
            message_group = pattern_config.get('message_group', 2)

            for match in re.finditer(pattern, snippet):
                try:
                    code = match.group(code_group)
                    message = match.group(message_group)

                    api.error_codes.append({
                        'code': code,
                        'message': message.strip()
                    })
                except Exception as e:
                    logger.debug(f"提取错误码失败: {e}")


class RuleLearner:
    """规则学习器 - 从LLM分析结果中学习新规则"""

    def __init__(self, rules_file: Path):
        """
        初始化规则学习器

        Args:
            rules_file: 规则配置文件路径
        """
        self.rules_file = rules_file
        self.rule_engine = RuleEngine(rules_file)

    def learn_from_llm_results(
        self,
        rule_extracted: List[ExtractedAPI],
        llm_extracted: List[Dict],
        file_content: str
    ) -> Dict:
        """
        从LLM结果中学习新规则

        Args:
            rule_extracted: 规则引擎提取的API
            llm_extracted: LLM提取的API
            file_content: 原始文件内容

        Returns:
            学到的新规则
        """
        logger.info("开始规则学习...")

        # 1. 找到LLM发现但规则没发现的API (新模式)
        rule_paths = {f"{api.method}:{api.path}" for api in rule_extracted}
        llm_paths = {f"{api['method']}:{api['path']}" for api in llm_extracted}

        new_patterns = llm_paths - rule_paths
        logger.info(f"发现 {len(new_patterns)} 个新API模式")

        # 2. 分析这些新API,尝试提炼规则
        learned_rules = {
            'annotation_patterns': [],
            'parameter_patterns': [],
            'error_code_patterns': []
        }

        for pattern_key in new_patterns:
            method, path = pattern_key.split(':', 1)

            # 在代码中找到这个API的定义
            api_context = self._find_api_context(file_content, path)
            if not api_context:
                continue

            # 尝试提炼注解模式
            new_annotation_pattern = self._extract_annotation_pattern(api_context, method, path)
            if new_annotation_pattern:
                learned_rules['annotation_patterns'].append(new_annotation_pattern)

        logger.info(f"学到 {len(learned_rules['annotation_patterns'])} 个新注解模式")

        return learned_rules

    def _find_api_context(self, content: str, path: str) -> Optional[str]:
        """在代码中找到API定义的上下文"""
        # 查找包含路径的位置
        pos = content.find(f'"{path}"')
        if pos == -1:
            pos = content.find(f"'{path}'")

        if pos == -1:
            return None

        # 提取前后各300字符
        start = max(0, pos - 300)
        end = min(len(content), pos + 300)
        return content[start:end]

    def _extract_annotation_pattern(
        self,
        context: str,
        method: str,
        path: str
    ) -> Optional[Dict]:
        """从上下文中提炼注解模式"""
        # 查找注解
        # 这里简化处理,实际需要更智能的分析
        annotation_match = re.search(r'@(\w+Mapping)', context)
        if not annotation_match:
            return None

        annotation_name = annotation_match.group(1)

        # 生成新的正则模式
        new_pattern = {
            'id': f'learned_{annotation_name.lower()}_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
            'pattern': f'@{annotation_name}\\s*\\(\\s*(?:value\\s*=\\s*)?["\']([^"\']+)["\']',
            'description': f'学习到的{annotation_name}模式',
            'path_group': 1,
            'method': method,
            'confidence': 0.70,  # 初始置信度较低
            'learned_from': 'llm',
            'learned_at': datetime.now().isoformat()
        }

        return new_pattern

    def update_rules(self, learned_rules: Dict) -> bool:
        """
        更新规则配置文件

        Args:
            learned_rules: 学到的新规则

        Returns:
            是否成功更新
        """
        try:
            # 1. 加载当前规则
            current_rules = self.rule_engine.rules

            # 2. 合并新规则
            for category, new_patterns in learned_rules.items():
                if category == 'annotation_patterns':
                    current_rules['annotation_patterns']['method_level'].extend(new_patterns)
                elif category == 'parameter_patterns':
                    current_rules['annotation_patterns']['parameter_patterns'].extend(new_patterns)
                elif category == 'error_code_patterns':
                    current_rules['error_code_patterns'].extend(new_patterns)

            # 3. 更新统计信息
            stats = current_rules.get('statistics', {})
            stats['learning_rounds'] = stats.get('learning_rounds', 0) + 1
            stats['last_updated'] = datetime.now().isoformat()
            current_rules['statistics'] = stats

            # 4. 保存更新后的规则 (带版本备份)
            backup_file = self.rules_file.with_suffix(f'.{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(current_rules, f, indent=2, ensure_ascii=False)
            logger.info(f"备份规则文件: {backup_file}")

            # 5. 保存新版本
            with open(self.rules_file, 'w', encoding='utf-8') as f:
                json.dump(current_rules, f, indent=2, ensure_ascii=False)

            logger.info(f"✓ 规则更新成功: {self.rules_file}")
            logger.info(f"  新增模式: {sum(len(v) for v in learned_rules.values())}")
            logger.info(f"  学习轮次: {stats['learning_rounds']}")

            return True

        except Exception as e:
            logger.error(f"更新规则失败: {e}")
            return False


def merge_rule_and_llm_results(
    rule_apis: List[ExtractedAPI],
    llm_apis: List[Dict]
) -> List[Dict]:
    """
    合并规则提取和LLM提取的结果

    策略:
    1. 规则提取的API为基础
    2. LLM提取的API补充细节(描述、参数、错误码)
    3. LLM发现的新API添加进来
    """
    merged = {}

    # 1. 添加规则提取的结果
    for api in rule_apis:
        key = f"{api.method}:{api.path}"
        merged[key] = asdict(api)

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
                merged[key]['error_codes'] = api['error_codes']

            # 标记为混合来源
            merged[key]['extraction_source'] = 'hybrid'
            merged[key]['confidence'] = max(merged[key]['confidence'], 0.85)
        else:
            # 新API
            api['extraction_source'] = 'llm'
            api['confidence'] = 0.80
            merged[key] = api

    logger.info(f"合并结果: {len(merged)} 个API")

    return list(merged.values())


# 使用示例
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # 测试规则引擎
    rules_file = Path('config/api_extraction_rules.json')
    engine = RuleEngine(rules_file)

    # 测试代码片段
    test_code = '''
@RestController
@RequestMapping(value = "/0.1/sso", produces = "application/json")
public class SsoV2Controller {

    @MethodInvokeWithInfoLoggable(description = "用户登录")
    @RequestMapping(value = "/login", method = RequestMethod.POST)
    public ResponseEntity<SsoRestAPIResponse> login(
        @RequestParam(name = "username", required = true) String username,
        @RequestParam(name = "password", required = true) String password
    ) {
        // code=1001 用户名为空
        // code=1201 密码为空
    }
}
'''

    apis, confidence = engine.extract_apis(test_code, "SsoV2Controller.java")

    print(f"\n提取到 {len(apis)} 个API:")
    for api in apis:
        print(f"  {api.method} {api.path} - {api.description}")
        print(f"    置信度: {api.confidence}")
        print(f"    参数: {len(api.parameters)}")
        print(f"    错误码: {len(api.error_codes)}")
