"""
GreenCode AI
============

AI-powered code efficiency and eco-refactoring backend.

Pipeline:

    Source Code
        ->
    Language-aware Static / Structural Analysis
        ->
    Efficiency Analysis (heuristic supporting signals)
        ->
    Complexity / Resource Impact Estimation (heuristic)
        ->
    AI Code Analysis
        ->
    AI Eco-Refactoring
        ->
    Explanation of Improvements
        ->
    Frontend

IMPORTANT:
The heuristic detectors are supporting signals only.
They are NOT intended to become a giant "if X -> warning" rule engine.

The AI layer is responsible for broader code reasoning.

Currently:
    - Python has real AST-based structural analysis.
    - JavaScript / TypeScript / Java / C++ are accepted as supported
      target languages and prepared for language-specific analyzers.
    - For languages without a dedicated parser installed, the backend
      performs safe generic source-level analysis and clearly labels it
      as heuristic.

User code is NEVER executed.

Run:

    python -m uvicorn main:app --reload
"""


import ast
import os
import re
import json

from google import genai
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sandbox.benchmark_runner import validate_refactor, benchmark_original_vs_refactored
from diff_engine import generate_diff
from tree_sitter import Language, Parser
import tree_sitter_python
import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_cpp


# =========================================================================
# FastAPI application
# =========================================================================

app = FastAPI(
    title="GreenCode AI",
    description=(
        "AI-powered multi-language code efficiency "
        "and eco-refactoring analysis API"
    ),
    version="0.3.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================================
# Supported languages
# =========================================================================

SUPPORTED_LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "java",
    "cpp",
}

LANGUAGE_ALIASES = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "c++": "cpp",
}


def normalize_language(language: str) -> str:
    """
    Normalize common language aliases.

    Example:
        js -> javascript
        py -> python
        c++ -> cpp
    """
    normalized = language.strip().lower()

    return LANGUAGE_ALIASES.get(normalized, normalized)


# =========================================================================
# 1. Request / Core Models
# =========================================================================

class CodeSubmission(BaseModel):
    code: str = Field(
        ...,
        description="Source code to analyze",
    )

    language: str = Field(
        default="python",
        description=(
            "Programming language. Supported targets currently include "
            "Python, JavaScript, TypeScript, Java, and C++."
        ),
    )
class DiffRequest(BaseModel):
    original_code: str
    refactored_code: str

class Finding(BaseModel):
    """
    A heuristic supporting signal.

    These findings are NOT a complete list of all possible code problems.
    They provide additional structured context to the AI layer.
    """

    detector: str

    message: str

    severity: str = "info"

    line: Optional[int] = None


class ComplexityEstimate(BaseModel):
    """
    Heuristic complexity estimate.

    This is NOT a mathematically exact complexity proof.
    """

    category: str = Field(
        ...,
        description=(
            "Examples: constant, linear, quadratic, cubic, "
            "high-order-polynomial-or-worse, unknown"
        ),
    )

    notation: str = Field(
        ...,
        description="Examples: O(1), O(n), O(n^2)",
    )

    confidence: str = Field(
        ...,
        description="low | medium | high",
    )

    max_loop_nesting_depth: int = 0

    notes: List[str] = Field(
        default_factory=list
    )


class AnalysisResult(BaseModel):
    syntax_valid: bool

    language: str

    line_count: int

    function_count: int

    loop_count: int

    nested_loop_count: int

    list_comprehension_count: int

    imported_modules: List[str]

    findings: List[Finding]

    complexity: Optional[ComplexityEstimate] = None

    syntax_error: Optional[str] = None

    parser_type: str = Field(
        default="generic",
        description=(
            "Parser/analyzer used for the submitted language. "
            "Examples: python_ast, generic_source"
        ),
    )


class AnalyzeResponse(BaseModel):
    result: AnalysisResult


# =========================================================================
# 2. AI-ready models
# =========================================================================

class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class AIProblem(BaseModel):
    type: str = Field(
        ...,
        description="Short category label for the issue",
    )

    severity: Severity

    explanation: str

    suggestion: str

    line: Optional[int] = None


class AIAnalysis(BaseModel):
    problems: List[AIProblem]

    overall_assessment: str

    refactored_code: str

    explanation: str

    improvements: List[str] = Field(
        default_factory=list
    )

    estimated_impact: str = Field(
        ...,
        description=(
            "Heuristic qualitative resource-impact statement. "
            "Never claim exact energy savings without real measurement."
        ),
    )

    is_mock: bool = Field(
        ...,
        description=(
            "True when this response comes from the development mock "
            "provider rather than a real AI model."
        ),
    )


class StructuredDiff(BaseModel):
    type: str
    line: str

class EnergyMeasurement(BaseModel):
    execution_time_seconds: float
    average_cpu_usage_percent: float
    memory_usage_mib: float
    estimated_power_watts: float
    estimated_energy_joules: float


class EnergyResponse(BaseModel):
    energy: EnergyMeasurement
class EnergyCarbonSide(BaseModel):
    execution_time_seconds: float
    cpu_time_seconds: float
    estimated_power_watts: float
    estimated_energy_joules: float
    estimated_carbon_grams_co2e: float

class CarbonComparison(BaseModel):
    carbon_saved_grams_co2e: float
    carbon_saved_percent: float

class EnergyCarbonComparison(BaseModel):
    original: EnergyCarbonSide
    refactored: EnergyCarbonSide
    carbon_comparison: CarbonComparison
class RefactorResponse(BaseModel):
    analysis: AnalysisResult
    ai_analysis: AIAnalysis
    validation: bool
    diff: List[StructuredDiff]
    energy: Optional[EnergyCarbonComparison] = None
def load_energy_measurement() -> EnergyMeasurement:
    results_path = os.path.join(
        os.path.dirname(__file__),
        "sandbox",
        "results",
        "benchmark.json",
    )

    if not os.path.exists(results_path):
        raise HTTPException(
            status_code=404,
            detail="Energy benchmark results were not found.",
        )

    try:
        with open(results_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        return EnergyMeasurement(
            execution_time_seconds=float(
                data["execution_time_seconds"]
            ),
            average_cpu_usage_percent=float(
                data["average_cpu_usage_percent"]
            ),
            memory_usage_mib=float(
                data["memory_usage_mib"]
            ),
            estimated_power_watts=float(
                data["estimated_power_watts"]
            ),
            estimated_energy_joules=float(
                data["estimated_energy_joules"]
            ),
        )

    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid energy benchmark result: {exc}",
        )
class DiffRequest(BaseModel):
    original_code: str
    refactored_code: str


class DiffResponse(BaseModel):
    diff: List[StructuredDiff]

# =========================================================================
# 3. Language-independent analysis context
# =========================================================================

class AnalysisContext:
    """
    Shared context for the entire pipeline.

    The downstream AI layer should NOT depend directly on Python AST.

    Language-specific analyzers can populate:

        metrics
        syntax_valid
        syntax_error
        parser_type
        complexity
        findings

    The AI layer can then consume the structured context regardless of
    the programming language.
    """

    def __init__(
        self,
        source: str,
        language: str = "python",
    ):
        self.source = source

        self.language = normalize_language(language)

        self.tree: Optional[ast.AST] = None

        self.syntax_valid: bool = True

        self.syntax_error: Optional[str] = None

        self.metrics: Dict[str, Any] = {}

        self.findings: List[Finding] = []

        self.complexity: Optional[ComplexityEstimate] = None

        self.parser_type: str = "generic"

    @property
    def is_python(self) -> bool:
        return self.language == "python"


# =========================================================================
# 4. Language Analyzer abstraction
# =========================================================================

class LanguageAnalyzer(ABC):
    """
    Interface for language-specific static analysis.

    This keeps language parsing separate from the AI layer.

    Future analyzers can be added without rewriting:

        EfficiencyAnalyzer
        ComplexityEstimator
        AIProvider
        AIRefactoringService
    """

    language: str = "unknown"

    parser_type: str = "generic"

    @abstractmethod
    def analyze(
        self,
        ctx: AnalysisContext,
    ) -> None:
        """
        Populate the AnalysisContext.

        IMPORTANT:
        This method must NEVER execute submitted source code.
        """
        raise NotImplementedError


# =========================================================================
# 5. Python AST Analyzer
# =========================================================================

def _count_loop_nesting(node: ast.AST) -> int:
    """
    Return the maximum nested loop depth underneath a node.

    If node itself is a loop, its own level is NOT included.
    """

    loop_types = (ast.For, ast.While)

    def depth(current: ast.AST) -> int:
        best = 0

        for child in ast.iter_child_nodes(current):
            child_depth = depth(child)

            if isinstance(child, loop_types):
                child_depth += 1

            best = max(best, child_depth)

        return best

    return depth(node)


def compute_python_metrics(
    tree: ast.AST,
    source: str,
) -> Dict[str, Any]:

    function_count = 0

    loop_count = 0

    list_comprehension_count = 0

    imported_modules: List[str] = []

    nested_loop_count = 0

    max_nesting = 0

    loop_types = (ast.For, ast.While)

    comprehension_types = (
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
    )

    for node in ast.walk(tree):

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            function_count += 1

        elif isinstance(node, loop_types):

            loop_count += 1

            local_depth = 1 + _count_loop_nesting(node)

            max_nesting = max(
                max_nesting,
                local_depth,
            )

            if local_depth > 1:
                nested_loop_count += 1

        elif isinstance(node, comprehension_types):

            list_comprehension_count += 1

        elif isinstance(node, ast.Import):

            for alias in node.names:
                imported_modules.append(alias.name)

        elif isinstance(node, ast.ImportFrom):

            if node.module:
                imported_modules.append(node.module)

    return {
        "line_count": len(source.splitlines()),

        "function_count": function_count,

        "loop_count": loop_count,

        "nested_loop_count": nested_loop_count,

        "list_comprehension_count": (
            list_comprehension_count
        ),

        "imported_modules": sorted(
            set(imported_modules)
        ),

        "max_loop_nesting_depth": max_nesting,
    }


class PythonAnalyzer(LanguageAnalyzer):

    language = "python"

    parser_type = "tree_sitter" 

    def analyze(
        self,
        ctx: AnalysisContext,
    ) -> None:
        parser = Parser()
        parser.language = Language(tree_sitter_python.language())
        tree_sitter_tree = parser.parse(ctx.source.encode("utf-8"))
        try:

            tree = ast.parse(ctx.source)

            ctx.tree = tree

            ctx.syntax_valid = True

            ctx.syntax_error = None

            ctx.parser_type = self.parser_type

            ctx.metrics = compute_python_metrics(
                tree,
                ctx.source,
            )

        except SyntaxError as exc:

            ctx.tree = None

            ctx.syntax_valid = False

            ctx.syntax_error = str(exc)

            ctx.parser_type = self.parser_type

            ctx.metrics = {
                "line_count": len(
                    ctx.source.splitlines()
                ),
                "function_count": 0,
                "loop_count": 0,
                "nested_loop_count": 0,
                "list_comprehension_count": 0,
                "imported_modules": [],
                "max_loop_nesting_depth": 0,
            }


# =========================================================================
# 6. Generic multi-language analyzer
# =========================================================================

def generic_source_metrics(
    source: str,
    language: str,
) -> Dict[str, Any]:
    """
    Safe source-level heuristic metrics.

    This does NOT pretend to be a real parser.

    It gives the AI basic structural information for languages where
    a dedicated parser is not installed yet.
    """

    lines = source.splitlines()

    line_count = len(lines)

    function_count = 0

    loop_count = 0

    max_nesting = 0

    imported_modules: List[str] = []

    # ---------------------------------------------------------------------
    # Function patterns
    # ---------------------------------------------------------------------

    if language in {
        "javascript",
        "typescript",
    }:

        function_patterns = [
            r"\bfunction\s+\w+\s*\(",
            r"\b(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\(",
            r"=>\s*\{",
        ]

    elif language == "java":

        function_patterns = [
            r"\b(?:public|private|protected|static|\s)+"
            r"[\w<>\[\]]+\s+\w+\s*\([^;{}]*\)\s*\{"
        ]

    elif language == "cpp":

        function_patterns = [
            r"\b[\w:*&<>\[\]]+\s+\w+\s*\([^;{}]*\)\s*\{"
        ]

    else:

        function_patterns = []

    for pattern in function_patterns:

        function_count += len(
            re.findall(
                pattern,
                source,
            )
        )

    # ---------------------------------------------------------------------
    # Loop patterns
    # ---------------------------------------------------------------------

    loop_patterns = []

    if language in {
        "javascript",
        "typescript",
        "java",
        "cpp",
    }:

        loop_patterns = [
            r"\bfor\s*\(",
            r"\bwhile\s*\(",
            r"\bdo\s*\{",
        ]

    for pattern in loop_patterns:

        loop_count += len(
            re.findall(
                pattern,
                source,
            )
        )

    # ---------------------------------------------------------------------
    # Very conservative nesting signal
    # ---------------------------------------------------------------------

    if loop_count > 0:

        brace_depth = 0

        loop_depths: List[int] = []

        for line in lines:

            stripped = line.strip()

            if re.search(
                r"\b(for|while)\s*\(",
                stripped,
            ):
                loop_depths.append(
                    brace_depth + 1
                )

            brace_depth += (
                stripped.count("{")
                - stripped.count("}")
            )

        if loop_depths:

            max_nesting = max(
                loop_depths
            )

    # ---------------------------------------------------------------------
    # Imports
    # ---------------------------------------------------------------------

    if language in {
        "javascript",
        "typescript",
    }:

        for match in re.finditer(
            r'import\s+.*?\s+from\s+[\'"]([^\'"]+)',
            source,
        ):
            imported_modules.append(
                match.group(1)
            )

        for match in re.finditer(
            r'require\s*\(\s*[\'"]([^\'"]+)',
            source,
        ):
            imported_modules.append(
                match.group(1)
            )

    elif language == "java":

        for match in re.finditer(
            r'import\s+([\w.]+);',
            source,
        ):
            imported_modules.append(
                match.group(1)
            )

    elif language == "cpp":

        for match in re.finditer(
            r'#include\s*[<"]([^>"]+)',
            source,
        ):
            imported_modules.append(
                match.group(1)
            )

    return {
        "line_count": line_count,

        "function_count": function_count,

        "loop_count": loop_count,

        "nested_loop_count": (
            max(0, loop_count - 1)
            if max_nesting > 1
            else 0
        ),

        "list_comprehension_count": 0,

        "imported_modules": sorted(
            set(imported_modules)
        ),

        "max_loop_nesting_depth": max_nesting,

    }

class JavaAnalyzer(LanguageAnalyzer):
    language = "java"
    parser_type = "tree_sitter_java"

    def analyze(
        self,
        ctx: AnalysisContext,
    ) -> None:

        parser = Parser()
        parser.language = Language(
            tree_sitter_java.language()
        )

        tree = parser.parse(
            ctx.source.encode("utf-8")
        )

        ctx.tree = tree
        ctx.parser_type = self.parser_type

        if tree.root_node.has_error:
            ctx.syntax_valid = False
            ctx.syntax_error = (
                "Java syntax error detected by Tree-sitter."
            )
        else:
            ctx.syntax_valid = True
            ctx.syntax_error = None

        ctx.metrics = generic_source_metrics(
            ctx.source,
            ctx.language,
        )
class JavaScriptAnalyzer(LanguageAnalyzer):
    language = "javascript"
    parser_type = "tree_sitter_javascript"

    def analyze(
        self,
        ctx: AnalysisContext,
    ) -> None:

        parser = Parser()
        parser.language = Language(
            tree_sitter_javascript.language()
        )

        tree = parser.parse(
            ctx.source.encode("utf-8")
        )

        ctx.tree = tree
        ctx.parser_type = self.parser_type

        if tree.root_node.has_error:
            ctx.syntax_valid = False
            ctx.syntax_error = (
                "JavaScript syntax error detected by Tree-sitter."
            )
        else:
            ctx.syntax_valid = True
            ctx.syntax_error = None

        ctx.metrics = generic_source_metrics(
            ctx.source,
            ctx.language,
        )
class CppAnalyzer(LanguageAnalyzer):
    language = "cpp"
    parser_type = "tree_sitter_cpp"

    def analyze(
        self,
        ctx: AnalysisContext,
    ) -> None:

        parser = Parser()
        parser.language = Language(
            tree_sitter_cpp.language()
        )

        tree = parser.parse(
            ctx.source.encode("utf-8")
        )

        ctx.tree = tree
        ctx.parser_type = self.parser_type

        if tree.root_node.has_error:
            ctx.syntax_valid = False
            ctx.syntax_error = (
                "C++ syntax error detected by Tree-sitter."
            )
        else:
            ctx.syntax_valid = True
            ctx.syntax_error = None

        ctx.metrics = generic_source_metrics(
            ctx.source,
            ctx.language,
        )
class GenericLanguageAnalyzer(LanguageAnalyzer):
    """
    Generic source analyzer for supported non-Python languages.

    This is intentionally conservative.

    It does NOT claim to provide a complete language parser.

    Its job is to provide safe baseline information until a dedicated
    parser is added.
    """

    def __init__(
        self,
        language: str,
    ):
        self.language = language

        self.parser_type = "generic_source"

    def analyze(
        self,
        ctx: AnalysisContext,
    ) -> None:

        ctx.syntax_valid = True

        ctx.syntax_error = None

        ctx.tree = None

        ctx.parser_type = self.parser_type

        ctx.metrics = generic_source_metrics(
            ctx.source,
            ctx.language,
        )


# =========================================================================
# 7. Language analyzer registry
# =========================================================================

LANGUAGE_ANALYZERS: Dict[
    str,
    LanguageAnalyzer,
] = {
    "python": PythonAnalyzer(),

    "javascript": JavaScriptAnalyzer(),

    "typescript": GenericLanguageAnalyzer(
        "typescript"
    ),

    "java": JavaAnalyzer(),

    "cpp": CppAnalyzer(),

}


def get_language_analyzer(
    language: str,
) -> LanguageAnalyzer:

    normalized = normalize_language(
        language
    )

    analyzer = LANGUAGE_ANALYZERS.get(
        normalized
    )

    if analyzer is None:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported language: {language}. "
                f"Supported languages are: "
                f"{', '.join(sorted(SUPPORTED_LANGUAGES))}."
            ),
        )

    return analyzer


# =========================================================================
# 8. Complexity estimation
# =========================================================================

class ComplexityEstimator:
    """
    Heuristic complexity estimator.

    It is intentionally conservative and clearly labeled as heuristic.

    It must not claim exact runtime complexity for arbitrary programs.
    """

    CATEGORY_BY_DEPTH = {
        0: (
            "constant",
            "O(1)",
        ),

        1: (
            "linear",
            "O(n)",
        ),

        2: (
            "quadratic",
            "O(n^2)",
        ),

        3: (
            "cubic",
            "O(n^3)",
        ),
    }

    def estimate(
        self,
        ctx: AnalysisContext,
    ) -> ComplexityEstimate:

        depth = int(
            ctx.metrics.get(
                "max_loop_nesting_depth",
                0,
            )
        )

        notes: List[str] = []

        if ctx.parser_type == "generic_source":

            notes.append(
                "This language currently uses generic source-level "
                "analysis rather than a dedicated parser."
            )

        if depth in self.CATEGORY_BY_DEPTH:

            category, notation = (
                self.CATEGORY_BY_DEPTH[depth]
            )

            confidence = (
                "medium"
                if ctx.parser_type == "python_ast"
                else "low"
            )

        elif depth > 3:

            category = (
                "high-order-polynomial-or-worse"
            )

            notation = f"O(n^{depth})"

            confidence = "low"

            notes.append(
                f"Loop nesting depth {depth} detected. "
                "This is only a rough structural estimate."
            )

        else:

            category = "unknown"

            notation = "unknown"

            confidence = "low"

        if ctx.metrics.get(
            "loop_count",
            0,
        ) == 0:

            notes.append(
                "No loop patterns were detected."
            )

        notes.append(
            "This is a static heuristic estimate. "
            "It does not measure runtime, memory usage, "
            "electricity consumption, carbon emissions, "
            "input size, recursion, or called-function complexity."
        )

        return ComplexityEstimate(
            category=category,

            notation=notation,

            confidence=confidence,

            max_loop_nesting_depth=depth,

            notes=notes,
        )


# =========================================================================
# 9. Detector architecture
# =========================================================================

class Detector(ABC):
    """
    Base interface for heuristic supporting signals.

    These detectors are intentionally minimal.

    The AI layer is responsible for broader reasoning.
    """

    name: str = "base_detector"

    @abstractmethod
    def run(
        self,
        ctx: AnalysisContext,
    ) -> List[Finding]:

        raise NotImplementedError


class NestedLoopDetector(Detector):

    name = "nested_loop_detector"

    def run(
        self,
        ctx: AnalysisContext,
    ) -> List[Finding]:

        findings: List[Finding] = []

        # Python AST-specific detector.
        if (
            ctx.language != "python"
            or ctx.tree is None
        ):
            return findings

        for node in ast.walk(ctx.tree):

            if isinstance(
                node,
                (
                    ast.For,
                    ast.While,
                ),
            ):

                depth = (
                    1
                    + _count_loop_nesting(node)
                )

                if depth > 1:

                    findings.append(
                        Finding(
                            detector=self.name,

                            message=(
                                f"Nested loop with depth "
                                f"{depth} detected. This is "
                                "a supporting signal only; "
                                "it does not automatically "
                                "mean the code is inefficient."
                            ),

                            severity=(
                                "medium"
                                if depth == 2
                                else "high"
                            ),

                            line=getattr(
                                node,
                                "lineno",
                                None,
                            ),
                        )
                    )

        return findings


DETECTORS: List[Detector] = [
    NestedLoopDetector(),
]


class EfficiencyAnalyzer:

    def __init__(
        self,
        detectors: Optional[
            List[Detector]
        ] = None,
    ):

        self.detectors = (
            detectors
            if detectors is not None
            else DETECTORS
        )

    def analyze(
        self,
        ctx: AnalysisContext,
    ) -> List[Finding]:

        findings: List[Finding] = []

        for detector in self.detectors:

            findings.extend(
                detector.run(ctx)
            )

        ctx.findings = findings

        return findings


# =========================================================================
# 10. Static analysis pipeline
# =========================================================================

complexity_estimator = ComplexityEstimator()

efficiency_analyzer = EfficiencyAnalyzer()


def run_static_analysis(
    submission: CodeSubmission,
) -> AnalysisContext:

    language = normalize_language(
        submission.language
    )

    # Validate language first.
    analyzer = get_language_analyzer(
        language
    )

    ctx = AnalysisContext(
        source=submission.code,
        language=language,
    )

    # Language-specific analysis.
    analyzer.analyze(ctx)

    # Heuristic detectors.
    if ctx.syntax_valid:

        efficiency_analyzer.analyze(
            ctx
        )

        ctx.complexity = (
            complexity_estimator.estimate(
                ctx
            )
        )

    return ctx


def build_analysis_result(
    ctx: AnalysisContext,
) -> AnalysisResult:

    return AnalysisResult(
        syntax_valid=ctx.syntax_valid,

        language=ctx.language,

        line_count=ctx.metrics.get(
            "line_count",
            0,
        ),

        function_count=ctx.metrics.get(
            "function_count",
            0,
        ),

        loop_count=ctx.metrics.get(
            "loop_count",
            0,
        ),

        nested_loop_count=ctx.metrics.get(
            "nested_loop_count",
            0,
        ),

        list_comprehension_count=ctx.metrics.get(
            "list_comprehension_count",
            0,
        ),

        imported_modules=ctx.metrics.get(
            "imported_modules",
            [],
        ),

        findings=ctx.findings,

        complexity=ctx.complexity,

        syntax_error=ctx.syntax_error,

        parser_type=ctx.parser_type,
    )


# =========================================================================
# 11. AI Provider abstraction
# =========================================================================

class AIProvider(ABC):
    """
    Provider-agnostic AI interface.

    A future real provider can be plugged in without changing:

        /analyze
        /refactor
        LanguageAnalyzers
        EfficiencyAnalyzer
        ComplexityEstimator
    """

    @abstractmethod
    def analyze_code(
        self,
        ctx: AnalysisContext,
    ) -> AIAnalysis:

        raise NotImplementedError


class MockAIProvider(AIProvider):
    """
    Safe local development provider.

    This is NOT real AI.

    It exists only so /refactor can be tested before connecting
    an actual AI API.
    """

    def analyze_code(
        self,
        ctx: AnalysisContext,
    ) -> AIAnalysis:

        problems: List[AIProblem] = []

        for finding in ctx.findings:

            if finding.severity == "high":

                severity = Severity.high

            elif finding.severity == "medium":

                severity = Severity.medium

            else:

                severity = Severity.low

            problems.append(
                AIProblem(
                    type=finding.detector,

                    severity=severity,

                    explanation=(
                        "[MOCK] Supporting heuristic signal: "
                        f"{finding.message}"
                    ),

                    suggestion=(
                        "[MOCK] A real AI provider would "
                        "inspect the complete source code "
                        "and propose a concrete improvement."
                    ),

                    line=finding.line,
                )
            )

        if problems:

            overall = (
                f"[MOCK] {len(problems)} heuristic "
                "supporting signal(s) were found. "
                "This is not real AI reasoning."
            )

        else:

            overall = (
                "[MOCK] No heuristic signals were found. "
                "A real AI provider may still identify "
                "inefficiencies not covered by the "
                "current static heuristics."
            )

        return AIAnalysis(
            problems=problems,

            overall_assessment=overall,

            refactored_code=ctx.source,

            explanation=(
                "[MOCK MODE] No real AI provider is "
                "configured. The submitted code was "
                "not modified and was never executed."
            ),

            improvements=[],

            estimated_impact=(
                "[MOCK] No real resource or energy "
                "impact estimate is available."
            ),

            is_mock=True,
        )
class GeminiAIProvider(AIProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)
        self.model = os.environ.get(
            "GEMINI_MODEL",
            "gemini-3.6-flash",
        )

    def analyze_code(
        self,
        ctx: AnalysisContext,
    ) -> AIAnalysis:
        fence = "```"

        prompt = (
            "You are an expert software engineer specializing in code efficiency, "
            "performance, and sustainable/green computing practices.\n\n"
            "Analyze the following source code for:\n"
            "- efficiency\n"
            "- unnecessary computation\n"
            "- algorithmic inefficiencies\n"
            "- resource usage\n"
            "- possible optimization opportunities\n"
            "- safe refactoring opportunities\n\n"
            "You are given structured static-analysis context in addition to the raw "
            "source code. Use all of it to inform your analysis.\n\n"
            f"LANGUAGE:\n{ctx.language}\n\n"
            f"PARSER TYPE:\n{ctx.parser_type}\n\n"
            f"SYNTAX VALID:\n{ctx.syntax_valid}\n\n"
            f"METRICS:\n{ctx.metrics}\n\n"
            f"EXISTING FINDINGS:\n{ctx.findings}\n\n"
            f"COMPLEXITY:\n{ctx.complexity}\n\n"
            "SOURCE CODE:\n\n"
            f"{fence}{ctx.language}\n"
            f"{ctx.source}\n"
            f"{fence}\n\n"
            "Analyze the source code and return the result according to the required "
            "AIAnalysis structure.\n\n"
            "Requirements for your response:\n"
            "- Identify concrete detected problems, each with a severity, explanation, "
            "and suggestion.\n"
            "- Provide an overall assessment of the code's efficiency and resource "
            "usage.\n"
            "- Provide refactored_code containing a safe, behavior-preserving "
            "optimization of the source code. If no safe optimization is justified, "
            "refactored_code must be the original, unmodified source code.\n"
            "- Provide a clear explanation of the refactoring performed (or state that "
            "no changes were made and why).\n"
            "- Provide a list of concrete improvements made (empty if none).\n"
            "- Provide a qualitative (not numeric, not exact) estimated "
            "resource/energy impact assessment. Never claim exact electricity, "
            "energy, carbon, or performance savings, since no real measurements "
            "are performed.\n"
            "- Do not execute the submitted source code under any circumstances; "
            "only perform static analysis and reasoning.\n"
            "- Set is_mock to false.\n"
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": (
                    AIAnalysis.model_json_schema()
                ),
            },
        )

        if not response or not response.text:
            raise RuntimeError(
                "Gemini returned an empty response while analyzing the source code."
            )

        result = AIAnalysis.model_validate_json(
            response.text
        )

        result.is_mock = False

        return result

def get_ai_provider() -> AIProvider:
    """
    Provider selection point.

    Currently returns MockAIProvider.

    A real provider can later be selected through environment
    configuration without changing the rest of the backend.
    """

    provider_name = os.environ.get(
        "AI_PROVIDER",
        ""
    ).strip().lower()

    api_key = os.environ.get(
        "AI_PROVIDER_API_KEY"
    )

    # Real provider wiring intentionally comes later.
    #
    # Example future architecture:
    #
    # if provider_name == "anthropic" and api_key:
    #     return AnthropicAIProvider(api_key)
    #
    # if provider_name == "openai" and api_key:
    #     return OpenAIProvider(api_key)

    if provider_name == "gemini" and api_key:
        return GeminiAIProvider(api_key)

    return MockAIProvider()


class AIRefactoringService:

    def __init__(
        self,
        provider: Optional[
            AIProvider
        ] = None,
    ):

        self.provider = (
            provider
            if provider is not None
            else get_ai_provider()
        )

    def analyze_and_refactor(
        self,
        ctx: AnalysisContext,
    ) -> AIAnalysis:

        return self.provider.analyze_code(
            ctx
        )


# =========================================================================
# 12. API endpoints
# =========================================================================

@app.post(
    "/analyze",
    response_model=AnalyzeResponse,
)
def analyze(
    submission: CodeSubmission,
) -> AnalyzeResponse:

    """
    Static + heuristic + complexity analysis.

    No AI call is made here.
    """

    ctx = run_static_analysis(
        submission
    )

    result = build_analysis_result(
        ctx
    )

    return AnalyzeResponse(
        result=result
    )

@app.post("/diff")
def diff(submission: DiffRequest):
    return {
        "diff": generate_diff(
            submission.original_code,
            submission.refactored_code,
        )
    }

@app.post(
    "/refactor",
    response_model=RefactorResponse,
)
def refactor(
    submission: CodeSubmission,
) -> RefactorResponse:

    """
    Full pipeline:

        Language analysis
            ->
        Efficiency signals
            ->
        Complexity estimate
            ->
        AI refactoring service
    """

    ctx = run_static_analysis(
        submission
    )

    if not ctx.syntax_valid:

        raise HTTPException(
            status_code=422,

            detail=(
                "Cannot refactor because the submitted "
                f"{ctx.language} source could not be parsed: "
                f"{ctx.syntax_error}"
            ),
        )

    result = build_analysis_result(
        ctx
    )

    service = AIRefactoringService()

    ai_analysis = (
        service.analyze_and_refactor(ctx)
    )
    validation = validate_refactor(
    submission.code,
    ai_analysis.refactored_code,
)
    diff_result = generate_diff(
        submission.code,
        ai_analysis.refactored_code,
    )
    energy = benchmark_original_vs_refactored(
        submission.code,
        ai_analysis.refactored_code,
    )
    return RefactorResponse(
    analysis=result,
    ai_analysis=ai_analysis,
    validation=validation["valid"],
    diff=diff_result,
    energy=energy,
)

@app.get(
    "/energy",
    response_model=EnergyResponse,
)
def get_energy() -> EnergyResponse:
    """
    Return the latest measured energy result
    from the sandbox benchmark.
    """

    energy = load_energy_measurement()

    return EnergyResponse(
        energy=energy
    )
@app.get("/health")
def health() -> Dict[str, str]:

    return {
        "status": "ok",
        "service": "GreenCode AI",
    }