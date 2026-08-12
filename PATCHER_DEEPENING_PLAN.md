# RemediationPatcher Deepening Plan

**Priority:** Lower (defer to future work)  
**Rationale:** Requires architectural integration with AST tools; current interface works but has shallow leverage

---

## Current Interface (Shallow)

```python
patcher.propose_fix(
    file_path="src/app.py",
    finding_id="SEC-1042",
    start_line=24,
    end_line=24,
    target_snippet="if x:\n  pass",        # ← Caller must provide exact snippet (burden)
    replacement_code="if x:\n  print('fixed')",
    reason="Fix SQL injection",
    author="agent",
)
```

**Issues:**
- Caller must know exact target snippet (fragile regex matching)
- If code has been reformatted, snippet might not match
- Duplicated snippet-matching logic if multiple callers implement it
- Low leverage for CLI and other interfaces

---

## Proposed Deepened Interface

```python
patcher.propose_fix(
    file_path="src/app.py",
    finding_id="SEC-1042",
    replacement_code="if x:\n  print('fixed')",
    auto_match=True,  # ← Patcher finds snippet itself
    reason="Fix SQL injection",
    author="agent",
)
```

**Benefits:**
- Patcher owns snippet matching logic (centralized, testable)
- Callers just provide replacement code
- AST-aware matching can handle code reformatting
- Easier to use for CLI and other frontends
- High leverage: same interface works for all callers

---

## Implementation Strategy (Phase 2)

### Step 1: AST-Aware Snippet Matching
Enhance `_locate_target_snippet()` to use AST analysis:
- Parse finding metadata to identify code patterns (function, class, assignment, etc.)
- Use AST to locate the exact node in the file
- Fall back to line-based matching if AST lookup fails
- Handle multi-line expressions gracefully

**Requires:**
- Extend VerificationItem in models.py to store AST context (node_type, symbol_name, line_range)
- Update SecurityAuditorAgent and QualityAuditorAgent to capture AST context in findings
- Use existing tools/static_analyzer.py and tools/dependency_map.py for AST lookup

### Step 2: New Interface
Modify patcher.py:
```python
def propose_fix(
    self,
    file_path: str,
    finding_id: str,
    replacement_code: str,
    reason: str,
    author: str = "agent",
    # Optional: AST context from finding
    ast_context: Optional[ASTContext] = None,
    auto_match: bool = True,
) -> RemediationProposal:
    """Propose fix with automatic snippet matching."""
    # If ast_context provided, use AST-aware lookup
    # Otherwise, use line-based matching as fallback
    # Return proposal with detected start/end lines
```

### Step 3: Update Callers
- Update review_operations.py to pass finding's AST context
- CLI adapters (future) will benefit automatically
- Existing tests should still pass

---

## Dependencies & Integration Points

**Already Available:**
- `ASTStaticAnalyzerTool` in tools/static_analyzer.py (used in patcher.py)
- `DependencyMapTool` in tools/dependency_map.py (can enhance it)
- AST parsing logic in patcher.py (post-validation)

**New Dependencies:**
- ASTContext model in models.py (lightweight DTO for AST metadata)
- Enhancement to CodeIssue to store ast_context (optional field)

**Testing Strategy:**
- Unit tests for AST-aware matching with various code patterns
- Integration tests for edge cases (formatted code, multi-line expressions)
- Regression tests to ensure existing line-based matching still works

---

## Risk Assessment

**Low Risk:** Backward compatible (new params are optional)
**Medium Effort:** ~2-3 hours of focused development
**High Payoff:** Cleaner interface, reusable across CLI and other adapters

---

## Rollout Plan (If Implemented)

1. **Phase 2a (Optional):** Add ASTContext model; enhance AST lookup
2. **Phase 2b (Optional):** Update patcher interface with auto_match parameter
3. **Phase 2c (Optional):** Update agents to capture AST context
4. **Phase 2d (Optional):** Refactor review_operations to use new interface
5. **Phase 2e (Optional):** Full regression testing

---

## Backlog Decision

**Current Status:** Documented in this plan; deferred to backlog.

**Trigger for Implementation:**
- When CLI interface is built and needs patcher integration
- When multiple frontends (web, IDE, CLI) need consistent patcher interface
- Performance analysis shows snippet matching is a bottleneck

---

## Alternative: Simpler Approach (Minimal)

If full AST integration is too complex, consider minimal deepening:

```python
def propose_fix_with_context(
    self,
    file_path: str,
    finding_id: str,
    finding_line: int,           # ← Use this instead of target_snippet
    replacement_code: str,
    reason: str,
    author: str = "agent",
):
    """Simplified: just use line number + smart matching in context window."""
    # Read +/- 10 lines around finding_line
    # Use diff matching (sequence matching) instead of exact snippet
    # Higher leverage than current approach, 50% of full deepening benefit
```

This is a good middle ground: less AST complexity, still centralizes matching logic.

---

## Conclusion

RemediationPatcher deepening should be deferred until:
1. CLI interface is built and needs it
2. Performance data shows matching is a bottleneck
3. Multiple frontends need consistent behavior

Current implementation is safe and working; refactoring should not be priority.
