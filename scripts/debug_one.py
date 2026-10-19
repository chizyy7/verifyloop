import sys
sys.path.insert(0, 'src')
from verifyloop.benchmark.manifest import load_benchmark
from verifyloop.config import BudgetConfig
from verifyloop.controller import ControllerConfig, RepairController
from verifyloop.model_providers.mock import MockProvider, MockResponse
from verifyloop.strategies import get_strategy

_, tasks = load_benchmark('benchmarks/synthetic', version='v1', task_ids=['boundary_paginate_001'])
t = tasks[0]
patch = '''--- a/paging.py
+++ b/paging.py
@@ -10,5 +10,5 @@
         raise ValueError("page must be >= 1")
     if per_page < 1:
         raise ValueError("per_page must be >= 1")
     start = (page - 1) * per_page
-    end = start + per_page - 1
+    end = start + per_page
     return list(items[start:end])
'''
c = RepairController(
    provider=MockProvider(responses=[MockResponse(text=patch)]),
    strategy=get_strategy('oneshot'),
    config=ControllerConfig(
        budgets=BudgetConfig(max_attempts=1, test_timeout_seconds=60),
        allowed_commands=['python', 'py', 'pytest'],
        patch_format='diff',
    ),
    task=t,
)
r = c.run()
print('OUTCOME', r.outcome.value)
print('REASON', r.attempts[0].rejected_reason)
print('VALIDATION', r.attempts[0].validation)
print('REPORT', r.attempts[0].test_report.summary_line() if r.attempts[0].test_report else None)
