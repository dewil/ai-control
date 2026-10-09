"""Record semantic RED separately from interface prerequisites; no optional skips."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
import live_devbus_blind_support as s

SUITES = ["test_control_web_devbus_bridge_red", "test_control_web_devbus_loader_red",
          "test_control_web_devbus_dto_red", "test_control_web_devbus_http_integration_red",
          "test_control_web_devbus_main_browser_red", "test_control_web_devbus_shutdown_red",
          "test_control_web_live_bus_shared_gate_blind"]


class Classified(unittest.TestResult):
    def __init__(self): super().__init__(); self.rows = {}

    def record(self, test, outcome, message=""):
        parent = getattr(test, "test_case", test)
        key = parent.id()
        row = self.rows.setdefault(key, {"test":key,"outcome":outcome,"messages":[]})
        if outcome == "harness_error" or row["outcome"] == "pass": row["outcome"] = outcome
        if message: row["messages"].append(message[:400])

    def addSuccess(self, test): super().addSuccess(test); self.record(test, "pass")
    def addFailure(self, test, err):
        super().addFailure(test, err); message = str(err[1])
        category = "interface_prerequisite" if "PUBLIC-SEAM PREREQUISITE:" in message else "semantic_red"
        if "HARNESS PREREQUISITE:" in message: category = "harness_error"
        self.record(test, category, message)
    def addError(self, test, err): super().addError(test, err); self.record(test,"harness_error",type(err[1]).__name__+": "+str(err[1]))
    def addSkip(self, test, reason): super().addSkip(test,reason); self.record(test,"skip",reason)
    def addSubTest(self, test, subtest, err):
        if err is None: return
        super().addSubTest(test,subtest,err)
        category = "interface_prerequisite" if "PUBLIC-SEAM PREREQUISITE:" in str(err[1]) else "semantic_red"
        self.record(test,category,str(err[1]))


if __name__ == "__main__":
    result = Classified(); unittest.defaultTestLoader.loadTestsFromNames(SUITES).run(result)
    counts = {kind:sum(row["outcome"]==kind for row in result.rows.values())
              for kind in ("pass","semantic_red","interface_prerequisite","harness_error","skip")}
    report = dict(runtime_sha=subprocess.check_output(["git","-C",str(s.ROOT),"rev-parse","HEAD"],text=True).strip(),
        tests_run=result.testsRun, counts=counts, cases=list(result.rows.values()),
        observer_pin=s.OBSERVER_COMMIT, usage=dict(tokens="unknown",money="unknown",coverage="partial"))
    target=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name("live_devbus_blind_red_provenance.json")
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(dict(tests_run=result.testsRun,counts=counts,report=str(target)),ensure_ascii=False))
    sys.exit(not result.wasSuccessful())
