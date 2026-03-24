"""
Prompts for code analysis operations.
"""

# General code analysis prompt
CODE_ANALYSIS_PROMPT = """You are a code analysis expert. Analyze the following code and provide:

1. **Structure Overview**: What does this code do? What are its main components?
2. **Code Quality**: Assess readability, maintainability, and adherence to best practices
3. **Issues Identified**: List any bugs, anti-patterns, or potential problems
4. **Improvements**: Suggest specific, actionable improvements

Code to analyze:
```{language}
{code}
```

File: {file_path}
Focus areas: {focus_areas}

Please provide detailed analysis with specific examples and code snippets where applicable.
"""

# Security analysis prompt
SECURITY_ANALYSIS_PROMPT = """You are a security expert. Analyze the following code for security vulnerabilities:

1. **Injection Vulnerabilities**: SQL injection, command injection, etc.
2. **Authentication/Authorization**: Missing or weak auth checks
3. **Data Exposure**: Sensitive data handling issues
4. **Cryptography**: Weak crypto practices
5. **Input Validation**: Missing or insufficient validation
6. **Dependencies**: Known vulnerable dependencies

Code to analyze:
```{language}
{code}
```

File: {file_path}

Please provide:
- Severity rating (Critical/High/Medium/Low) for each issue
- Specific code locations
- Recommended fixes with code examples
"""

# Performance analysis prompt
PERFORMANCE_ANALYSIS_PROMPT = """You are a performance optimization expert. Analyze the following code for performance issues:

1. **Algorithmic Complexity**: Big-O analysis of key functions
2. **I/O Operations**: Inefficient file/network operations
3. **Memory Usage**: Memory leaks, unnecessary allocations
4. **Concurrency**: Missing parallelization opportunities
5. **Database**: N+1 queries, missing indexes
6. **Caching**: Missing caching opportunities

Code to analyze:
```{language}
{code}
```

File: {file_path}

Please provide:
- Performance impact rating (Critical/High/Medium/Low)
- Specific optimization suggestions
- Before/after code examples
- Expected performance improvements
"""
