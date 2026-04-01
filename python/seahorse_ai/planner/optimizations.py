"""Optimizations for FastPath to reduce token usage and improve performance.

This module provides:
1. SimpleTaskDetector - Bypass multi-agent for simple requests
2. SchemaCache - Cache database schemas to avoid repeated dumps
3. TokenBudgeting - Prevent runaway LLM calls
4. OptimizedExecutor - Execute simple tasks directly
"""

import re
import logging
from typing import Any, Callable, Coroutine, Optional, Dict, List
from functools import lru_cache

from seahorse_ai.core.schemas import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


# ============================================================================
# OPTIMIZATION 1: Simple Task Detector
# ============================================================================

class SimpleTaskDetector:
    """Detects if a request should use the fast path instead of full orchestration.

    Simple tasks include:
    - Simple SQL queries (SELECT, SHOW)
    - Chart generation requests
    - Basic calculations
    - Single API calls

    For these tasks, we bypass the heavy multi-agent decomposition.
    """

    # Patterns that indicate simple tasks
    SIMPLE_PATTERNS = [
        r"^select\s+",  # SQL SELECT
        r"^show\s+",  # SQL SHOW
        r"^explain\s+",  # SQL EXPLAIN
        r"ทำกราฟ|สร้างกราฟ|กราฟ",  # Chart requests
        r"make.*chart|generate.*chart|plot|graph",  # English chart
        r"คำนวณ|calculate\b",  # Calculate
    ]

    # Keywords that indicate COMPLEX tasks (NOT fast path)
    COMPLEX_KEYWORDS = [
        "วิเคราะห์", "analyze", "analysis",
        "วางแผน", "plan", "strategy",
        "เปรียบเทียบ", "compare", "comparison",
        "สรุป", "summarize", "summary",
        "รายงาน", "report",
        "decompose", "breakdown",
        "multi", "multiple", "several",
    ]

    def __init__(self):
        self._simple_regex = re.compile("|".join(self.SIMPLE_PATTERNS), re.IGNORECASE)
        self._complex_regex = re.compile("|".join(self.COMPLEX_KEYWORDS), re.IGNORECASE)

    def is_simple_request(self, request: AgentRequest) -> bool:
        """Check if the request is simple enough for fast path."""
        prompt = request.prompt.strip().lower()

        # Fast reject: Check for complex keywords first
        if self._complex_regex.search(prompt):
            logger.debug(f"SimpleTaskDetector: REJECT (complex keyword) in: {prompt[:100]}")
            return False

        # Check for simple patterns
        if self._simple_regex.search(prompt):
            logger.debug(f"SimpleTaskDetector: ACCEPT (simple pattern) in: {prompt[:100]}")
            return True

        # Very short prompts (< 50 chars) are likely simple
        if len(prompt) < 50:
            logger.debug(f"SimpleTaskDetector: ACCEPT (short prompt {len(prompt)} chars): {prompt}")
            return True

        logger.debug(f"SimpleTaskDetector: REJECT (no pattern matched) for: {prompt[:100]}")
        return False


# ============================================================================
# OPTIMIZATION 2: Schema Cache
# ============================================================================

class SchemaCache:
    """Cache database schemas to avoid repeated dumps.

    Prevents the 689-token schema dump on every subtask.
    Uses LRU cache with TTL for automatic eviction.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 3600):
        self._cache: Dict[str, tuple[dict, float]] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def get_schema(self, db_name: str, current_time: float) -> Optional[dict]:
        """Get cached schema for a database if not expired."""
        if db_name in self._cache:
            schema, timestamp = self._cache[db_name]
            if current_time - timestamp < self._ttl:
                self._hits += 1
                logger.debug(f"SchemaCache: HIT for {db_name} (hits={self._hits}, misses={self._misses})")
                return schema
            else:
                # Expired, remove it
                del self._cache[db_name]
                logger.debug(f"SchemaCache: EXPIRED for {db_name}")

        self._misses += 1
        logger.debug(f"SchemaCache: MISS for {db_name} (hits={self._hits}, misses={self._misses})")
        return None

    def set_schema(self, db_name: str, schema: dict, current_time: float) -> None:
        """Cache schema for a database."""
        if len(self._cache) >= self._max_size:
            # Remove oldest entry (simple FIFO)
            oldest_db = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_db]
            logger.debug(f"SchemaCache: EVICTED oldest {oldest_db}")

        self._cache[db_name] = (schema, current_time)
        logger.debug(f"SchemaCache: CACHED schema for {db_name}")

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        logger.debug("SchemaCache: CLEARED")


# ============================================================================
# OPTIMIZATION 3: Token Budget Manager
# ============================================================================

class TokenBudget:
    """Token budget manager to prevent runaway LLM calls.

    Ensures we don't burn 65k+ tokens for simple requests.
    """

    # Default token budget per request
    DEFAULT_BUDGET = 2000  # tokens
    MAX_BUDGET = 10000  # tokens

    def __init__(self, budget: int = DEFAULT_BUDGET):
        self._budget = min(budget, self.MAX_BUDGET)
        self._spent = 0
        self._request_count = 0

    def can_spend(self, tokens: int) -> bool:
        """Check if we can spend this many tokens."""
        return (self._spent + tokens) <= self._budget

    def spend(self, tokens: int) -> bool:
        """Spend tokens from budget. Returns False if over budget."""
        if not self.can_spend(tokens):
            logger.warning(f"TokenBudget: OVER BUDGET! spent={self._spent} + {tokens} > budget={self._budget}")
            return False

        self._spent += tokens
        self._request_count += 1
        logger.debug(f"TokenBudget: spent {self._spent}/{self._budget} tokens (request #{self._request_count})")
        return True

    def remaining(self) -> int:
        """Get remaining budget."""
        return max(0, self._budget - self._spent)

    def reset(self) -> None:
        """Reset budget for new request."""
        self._spent = 0
        self._request_count = 0
        logger.debug("TokenBudget: RESET")


# ============================================================================
# OPTIMIZATION 4: SQL Aggregation Helper
# ============================================================================

class SQLAggregator:
    """Helper to auto-aggregate large SQL query results.

    If a query returns > 1000 rows, automatically add aggregation.
    """

    MAX_ROWS_THRESHOLD = 1000

    @staticmethod
    def should_aggregate(row_count: int) -> bool:
        """Check if query results should be aggregated."""
        return row_count > SQLAggregator.MAX_ROWS_THRESHOLD

    @staticmethod
    def aggregate_query(sql: str, group_by_columns: List[str] = None) -> str:
        """Wrap a query with aggregation to reduce result size.

        Example:
            SELECT * FROM sales WHERE date > '2024-01-01'
            → SELECT date, SUM(amount) as total FROM sales WHERE date > '2024-01-01' GROUP BY date
        """
        # Detect if query already has aggregation
        has_group_by = re.search(r"\bgroup\s+by\b", sql, re.IGNORECASE)
        has_agg_func = re.search(r"\b(sum|count|avg|min|max)\s*\(", sql, re.IGNORECASE)

        if has_group_by or has_agg_func:
            logger.debug("SQLAggregator: Query already has aggregation, skipping")
            return sql

        # Parse SELECT clause to find columns
        select_match = re.search(r"select\s+(.*?)\s+from", sql, re.IGNORECASE)
        if not select_match:
            return sql

        select_clause = select_match.group(1)
        if select_clause == "*":
            # Can't aggregate SELECT *, ask for columns
            logger.warning("SQLAggregator: SELECT * with > 1000 rows, please specify columns")
            return sql

        # Extract columns
        columns = [col.strip() for col in select_clause.split(",")]
        numeric_columns = SQLAggregator._guess_numeric_columns(columns)

        if not numeric_columns:
            return sql

        # Build aggregated query
        agg_columns = [f"SUM({col}) as {col}" for col in numeric_columns]
        group_cols = group_by_columns or SQLAggregator._guess_group_by_columns(columns)

        if not group_cols:
            # No good group by columns, just return total
            agg_select = ", ".join(agg_columns)
            return f"SELECT {agg_select} FROM ({sql}) as subquery"

        # Build GROUP BY query
        agg_select = ", ".join([f"{col}" for col in group_cols] + agg_columns)
        from_clause = re.sub(r"^select\s+.*?\s+from", "", sql, count=1, flags=re.IGNORECASE)
        from_clause = from_clause.split(" limit ")[0]  # Remove LIMIT if exists

        aggregated_sql = f"SELECT {agg_select} FROM {from_clause} GROUP BY {', '.join(group_cols)}"
        logger.debug(f"SQLAggregator: Aggregated query: {aggregated_sql[:200]}")
        return aggregated_sql

    @staticmethod
    def _guess_numeric_columns(columns: List[str]) -> List[str]:
        """Guess which columns are numeric based on name patterns."""
        numeric_patterns = [
            r"amount", "total", "sum", "count", "price", "cost", "value",
            "quantity", "qty", "volume", "balance", "ยอด", "จำนวน",
            "ราคา", "มูลค่า", r"\$_",  # ends with _
        ]
        numeric_columns = []
        for col in columns:
            if any(re.search(pattern, col, re.IGNORECASE) for pattern in numeric_patterns):
                numeric_columns.append(col)
        return numeric_columns

    @staticmethod
    def _guess_group_by_columns(columns: List[str]) -> List[str]:
        """Guess which columns to group by (date, category, etc.)."""
        group_patterns = [
            r"date", "time", "day", "month", "year", "วัน", "เดือน", "ปี",
            r"category", "type", "status", "ประเภท", "สถานะ",
        ]
        group_columns = []
        for col in columns:
            if any(re.search(pattern, col, re.IGNORECASE) for pattern in group_patterns):
                group_columns.append(col)
        return group_columns


# ============================================================================
# OPTIMIZATION 5: Optimized Fast Path Executor
# ============================================================================

class OptimizedFastPathExecutor:
    """Optimized executor for fast path requests with all optimizations enabled.

    This routes simple tasks to direct execution paths with:
    - Simple task detection
    - Schema caching
    - Token budgeting
    - SQL aggregation
    """

    def __init__(
        self,
        db_executor: Optional[Callable[[str], Coroutine[Any, Any, AgentResponse]]] = None,
        chart_executor: Optional[Callable[[dict], Coroutine[Any, Any, AgentResponse]]] = None,
        simple_detector: Optional[SimpleTaskDetector] = None,
        schema_cache: Optional[SchemaCache] = None,
        token_budget: Optional[TokenBudget] = None,
        sql_aggregator: Optional[SQLAggregator] = None,
    ):
        self._db_executor = db_executor
        self._chart_executor = chart_executor
        self._simple_detector = simple_detector or SimpleTaskDetector()
        self._schema_cache = schema_cache or SchemaCache()
        self._token_budget = token_budget or TokenBudget()
        self._sql_aggregator = sql_aggregator or SQLAggregator()

    async def execute_fast_path(self, request: AgentRequest) -> AgentResponse:
        """Execute a fast path request with optimizations."""
        import time
        current_time = time.time()

        prompt = request.prompt.strip().lower()

        # Check if this is a simple request
        if not self._simple_detector.is_simple_request(request):
            logger.info(f"OptimizedFastPath: NOT SIMPLE, falling back to full orchestration: {prompt[:100]}")
            return AgentResponse(
                content="Request is too complex for fast path, using full orchestration",
                metadata={"fast_path": False, "reason": "not_simple"},
            )

        logger.info(f"OptimizedFastPath: Executing fast path for: {prompt[:100]}")

        # Check token budget
        if not self._token_budget.can_spend(100):  # Estimate 100 tokens
            return AgentResponse(
                content="Token budget exceeded, please simplify your request",
                metadata={"fast_path": False, "error": "token_budget_exceeded"},
            )

        # Route to appropriate executor
        if self._is_sql_query(prompt):
            return await self._execute_sql(request, current_time)
        elif self._is_chart_request(prompt):
            return await self._execute_chart(request)
        else:
            # Fallback to simple response
            return AgentResponse(
                content=f"Processed: {request.prompt}",
                metadata={"fast_path": True},
            )

    async def _execute_sql(self, request: AgentRequest, current_time: float) -> AgentResponse:
        """Execute SQL query with optimizations."""
        if not self._db_executor:
            return AgentResponse(
                content="SQL executor not configured",
                metadata={"fast_path": False, "error": "no_db_executor"},
            )

        # Check schema cache first
        schema = self._schema_cache.get_schema("default", current_time)
        if schema:
            logger.debug(f"OptimizedFastPath: Using cached schema (saved ~{len(str(schema))} tokens)")
            # Add schema to request metadata
            request.metadata = request.metadata or {}
            request.metadata["cached_schema"] = True

        # Execute the query
        result = await self._db_executor(request.prompt)

        # Check if we should aggregate results
        if hasattr(result, "row_count") and self._sql_aggregator.should_aggregate(result.row_count):
            logger.info(f"OptimizedFastPath: Aggregating {result.row_count} rows to save tokens")
            aggregated_query = self._sql_aggregator.aggregate_query(request.prompt)
            result = await self._db_executor(aggregated_query)

        return result

    def _is_sql_query(self, prompt: str) -> bool:
        """Check if prompt is a SQL query."""
        return bool(re.match(r"^select|^show|^explain", prompt, re.IGNORECASE))

    def _is_chart_request(self, prompt: str) -> bool:
        """Check if prompt is a chart request."""
        chart_keywords = ["chart", "กราฟ", "plot", "graph", "visuali"]
        return any(keyword in prompt for keyword in chart_keywords)

    async def _execute_chart(self, request: AgentRequest) -> AgentResponse:
        """Execute chart request."""
        if not self._chart_executor:
            return AgentResponse(
                content="Chart executor not configured",
                metadata={"fast_path": False, "error": "no_chart_executor"},
            )

        # Execute chart generation
        return await self._chart_executor({"prompt": request.prompt, "params": request.params})
