"""Force actual wrong-UID Unix peer EOF before client sendall; no runtime edits."""
import io,json,socket,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_control_web_participation_http_broker_blind import ParticipationBrokerBlind
case=ParticipationBrokerBlind('test_INV_PART_01_wrong_peer_UID_and_arbitrary_callback_no_backend')
original=socket.socket.sendall
proof=[]
def after_peer_EOF(sock,data,*args,**kwargs):
 if sock.family==socket.AF_UNIX and sock.getpeername()==case.socket_path:
  # Drain the actual rejection then wait for kernel EOF; wire() sets2s timeout.
  # This barrier exposes close-before-send independent of client scheduling.
  rejection=b''
  while True:
   chunk=sock.recv(4096)
   if not chunk:break
   rejection+=chunk
   if len(rejection)>65536:raise AssertionError('Unbounded wrong-UID rejection')
  if rejection and 'error' not in json.loads(rejection):raise AssertionError('Expected broker rejection')
  proof.append('actual_peer_EOF_before_sendall')
  try:return original(sock,data,*args,**kwargs)
  except BrokenPipeError:
   proof.append('real_kernel_BrokenPipeError');raise
 return original(sock,data,*args,**kwargs)
with patch.object(socket.socket,'sendall',after_peer_EOF):
 result=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(unittest.TestSuite([case]))
output={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),'proof':proof,'error_last_lines':[trace.splitlines()[-1] for _,trace in result.errors],'backend_calls':case.backend.part_calls,'failure_last_lines':[trace.splitlines()[-1] for _,trace in result.failures]}
print(json.dumps(output))
expected=sys.argv[1]
if expected=='before':
 assert len(result.errors)==1 and 'BrokenPipeError' in result.errors[0][1] and not case.backend.part_calls
else:
 assert result.wasSuccessful() and len(proof)==6 and not case.backend.part_calls
