import importlib.util, os, sys, time, unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('contracts', 'tests/test-codex-task-runtime.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=os.fsync
count=0
failures=[]
latency=float(sys.argv[1])
def slow_fsync(fd):
 global count
 count += 1
 time.sleep(latency)
 return original(fd)
def trace(frame, event, arg):
 if event=='exception' and frame.f_code.co_name=='execute' and frame.f_code.co_filename.endswith('_codex_task_runtime.py'):
  failures.append((frame.f_lineno, type(arg[1]).__name__, str(arg[1])))
 return trace
start=time.monotonic()
sys.settrace(trace)
with patch.object(os,'fsync',slow_fsync):
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([m.RuntimeContract('test_archived_finished_operation_remains_historical_after_later_owned_task_commit')]))
sys.settrace(None)
print('elapsed', round(time.monotonic()-start,2), 'fsync_count', count, 'runtime_exceptions', failures)
sys.exit(not result.wasSuccessful())
