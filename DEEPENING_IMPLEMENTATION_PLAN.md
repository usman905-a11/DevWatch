# DevWatch Deepening Implementation Plan

**Date:** 2026-08-12  
**Status:** In Progress  
**Scope:** Implement all findings from CODEBASE_AUDIT.md

---

## Phase 1: Core Operations Module (Highest Priority)

### Task 1.1: Create review_operations.py
**File:** `devwatch/operations/review_operations.py`

**Goal:** Extract validation, rate-limiting, and audit logging from routers into a reusable domain module.

**Interface:**
```python
class ReviewOperations:
    async def audit_repository(
        target_path: str,
        client_identity: str,
        client_ip: str,
    ) -> ReviewReport
    
    async def audit_uploaded_files(
        files: List[Dict],
        client_identity: str,
        client_ip: str,
    ) -> ReviewReport
    
    async def apply_file_fix(
        root_path: str,
        file_path: str,
        finding_id: str,
        replacement_code: str,
        client_identity: str,
    ) -> Dict
    
    async def propose_fix(
        root_path: str,
        file_path: str,
        finding_id: str,
        replacement_code: str,
        reason: str,
        client_identity: str,
    ) -> RemediationProposal
```

**Implementation Details:**
- Each method orchestrates: validation → rate-limit check → execute pipeline → audit log
- Reusable by HTTP routers, CLI, and future adapters
- Centralizes cross-cutting concerns (validation, rate-limiting, audit logging)

**Tests:**
- Unit tests for each operation (mock pipeline, verify rate-limiting, audit logging)
- Integration tests with real pipeline

---

### Task 1.2: Refactor routers/review.py
**File:** `devwatch/routers/review.py`

**Goal:** Thin adapter layer using ReviewOperations.

**Before:**
```python
@review_router.post("/review")
async def trigger_repository_audit(request: ReviewRequest, ...):
    # Validation, rate-limiting, pipeline call, audit logging scattered here
    pass
```

**After:**
```python
@review_router.post("/review")
async def trigger_repository_audit(request: ReviewRequest, client_identity: str = Depends(...), request_obj: Request = ...):
    return await review_ops.audit_repository(
        request.target_path,
        client_identity,
        request_obj.client.host,
    )
```

---

## Phase 2: Frontend Hook Extraction (Medium Priority)

### Task 2.1: Extract useCodeReview hook
**File:** `frontend/src/hooks/useCodeReview.ts`

**Goal:** Move state management and business logic out of App.tsx into a custom hook.

**Interface:**
```typescript
export function useCodeReview() {
  const [tree, setTree] = useState<FileNode[]>([])
  const [findings, setFindings] = useState<Finding[]>([])
  const [status, setStatus] = useState<'idle' | 'running'>('idle')
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null)
  
  const loadFolder: (files: FileList) => Promise<void>
  const runReview: (projectPath: string) => Promise<void>
  const applyFix: (finding_id: string, replacement: string) => Promise<void>
  
  return { tree, findings, status, selectedFile, loadFolder, runReview, applyFix, setSelectedFile }
}
```

**Implementation Details:**
- Encapsulates folder tree building logic
- Manages review execution lifecycle
- Coordinates WebSocket subscription
- Maps backend issues to frontend findings
- Handles error states

**Tests:**
- Mock API calls
- Verify tree building logic
- Test review lifecycle (pending → results → display)

---

### Task 2.2: Refactor App.tsx
**File:** `frontend/src/App.tsx`

**Goal:** Simplify App to purely presentational; move logic to hook.

**Before:** ~400+ lines (state, handlers, transforms, render mixed)

**After:** ~150 lines (only render + hook call)

```typescript
export function App() {
  const { tree, findings, status, selectedFile, loadFolder, runReview, applyFix, setSelectedFile } = useCodeReview()
  
  return (
    <div className="workspace">
      <header>...</header>
      <div className="body">
        <FileExplorer tree={tree} onOpenFolder={loadFolder} onSelectFile={setSelectedFile} />
        <CodeEditor file={selectedFile} />
        <AgentPanel findings={findings} status={status} onApplyFix={applyFix} />
      </div>
    </div>
  )
}
```

---

## Phase 3: Verification Strategy Module (Low Priority, High Locality)

### Task 3.1: Create verification_strategy.py
**File:** `devwatch/verification/strategy.py`

**Goal:** Unify verification logic currently spread across verifier.py and models.py.

**Interface:**
```python
class VerificationStrategy(ABC):
    @abstractmethod
    async def verify(self, issues: List[CodeIssue], context: ReviewContext) -> List[VerificationItem]

class DefaultVerificationStrategy(VerificationStrategy):
    """Existing verification logic unified here."""
    pass
```

**Benefits:**
- Centralized verification decision-making
- Easy to swap strategies (A/B testing, custom rules)
- Tests don't need to mock across multiple modules

---

## Phase 4: RemediationPatcher Deepening (Lower Priority)

### Task 4.1: Plan AST-aware matching
**File:** `devwatch/patcher.py` (enhanced)

**Current (shallow):**
```python
patcher.apply_fix(
    file_path="src/app.py",
    target_snippet="if x:\n  pass",           # Caller must provide exact snippet
    replacement="if x:\n  print('fixed')"
)
```

**Proposed (deeper):**
```python
patcher.apply_fix(
    file_path="src/app.py",
    finding_id="SEC-1042",
    suggested_replacement="if x:\n  print('fixed')",
    auto_match=True  # AST-aware matching finds the snippet
)
```

**Implementation (defer to Phase 4 if time):**
- Use AST parsing to locate the exact target
- Fuzzy matching if AST doesn't find exact match
- Reduces caller burden; centralizes matching logic

---

## Implementation Order

**Priority A (Do first, highest impact):**
1. ✅ Task 1.1: Create review_operations.py
2. ✅ Task 1.2: Refactor routers/review.py
3. ✅ Task 2.1: Extract useCodeReview hook
4. ✅ Task 2.2: Refactor App.tsx

**Priority B (Medium impact, if time permits):**
5. Task 3.1: Create verification_strategy.py
6. Refactor verifier.py to use it

**Priority C (Defer or plan separately):**
7. Task 4.1: Deepen RemediationPatcher

---

## Testing Strategy

**For each refactored module:**
- ✅ Unit tests at the new interface (no mocking HTTP, React components)
- ✅ Integration tests with real dependencies
- ✅ Regression tests (existing tests should still pass)

**Commands:**
```bash
# Unit tests for new modules
pytest tests/test_operations.py -v
pytest tests/test_verification_strategy.py -v

# Frontend tests (if Jest configured)
npm test

# Full suite
pytest tests/
```

---

## Rollback Strategy

Each phase is independent:
- Phase 1 is safe; old routers can coexist with new operations module
- Phase 2 is safe; App.tsx refactoring doesn't break existing components
- Phase 3 is safe; new strategy module can be adopted incrementally

If issues arise, revert the phase and keep previous work.

---

## Expected Outcomes

**After Phase 1+2:**
- ReviewOperations is testable, CLI-reusable, and decoupled from HTTP
- App.tsx is 150 lines and purely presentational
- Validation/rate-limiting/audit logging are centralized and easier to test
- **Leverage:** Callers (HTTP, CLI, tests) all use the same deep interface
- **Locality:** Concerns (validation, rate-limiting, audit) live in one place

**After Phase 3:**
- Verification logic is unified in one module
- Easy to A/B test or swap verification strategies
- Verifier.py is cleaner; models.py is purely DTO namespace

**After Phase 4 (future):**
- RemediationPatcher is deeper; AST-aware matching is centralized
- Callers don't need to provide exact snippet; patcher finds it

---

## Success Criteria

✅ All existing tests pass  
✅ No behavioral changes (purely structural refactoring)  
✅ New modules are testable through their interfaces  
✅ Code complexity metrics improve (operations, hook layer are tested independently)  
✅ No new dependencies introduced  

