"""Black-box regression for one identity capture during first account open."""

import importlib.util
import pathlib
import sys
import unittest


ROOT_MODULE = pathlib.Path(__file__).resolve().parents[1] / "bin" / "_control_codex_auth_authority.py"


def reference(account):
    return {
        "schema": 2,
        "provider_id": "codex",
        "account_id": account,
        "profile_instance_id": "123e4567-e89b-42d3-a456-426614174000",
        "adapter_revision": "codex-chatgpt-external-auth-host-v2",
        "registration_snapshot": {
            "dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "a" * 64,
        },
    }


def principal():
    return {
        "kind": "openid_subject_workspace",
        "issuer": "https://auth.openai.com",
        "subject": "auth0|alice",
        "workspace_id": "workspace_1",
    }


class SingleCaptureRed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert ROOT_MODULE.is_file(), "frozen authority module unavailable"
        module_name = "_control_codex_auth_authority_single_capture_red"
        spec = importlib.util.spec_from_file_location(module_name, ROOT_MODULE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        cls.auth = module
        cls.module_name = module_name

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop(cls.module_name, None)

    def require_success(self, call, message):
        try:
            return call()
        except Exception as exc:
            self.fail(f"{message}: {type(exc).__name__}")

    def is_current(self, call):
        try:
            call()
        except self.auth.AuthError as exc:
            self.assertEqual(exc.code, "authority_stale")
            return False
        except Exception as exc:
            self.fail(f"unexpected authority error: {type(exc).__name__}")
        return True

    def test_first_open_uses_one_identity_snapshot_for_key_account_and_lease(self):
        auth = self.auth
        scope = auth.AuthScope(reference("alpha"), principal())
        fresh_alpha = auth.AuthScope(reference("alpha"), principal())
        fresh_beta = auth.AuthScope(reference("beta"), principal())
        coordinator = auth.AuthCoordinator(clock=lambda: 100.0)
        hook_fired = False
        hook_error = None
        old_profile = sys.getprofile()

        def mutate_at_account_construction(frame, event, arg):
            nonlocal hook_fired, hook_error
            if hook_fired or event != "call":
                return
            if frame.f_code.co_qualname != "_Account.__init__":
                return
            if pathlib.Path(frame.f_code.co_filename).resolve() != ROOT_MODULE.resolve():
                return
            hook_fired = True
            try:
                object.__setattr__(
                    scope,
                    "_reference",
                    object.__getattribute__(fresh_beta, "_reference"),
                )
            except Exception as exc:
                hook_error = exc

        lease_alpha = None
        lease_beta = None
        outcome = None
        try:
            sys.setprofile(mutate_at_account_construction)
            try:
                lease_alpha = coordinator.open(scope, deadline=110.0)
            except Exception as exc:
                outcome = exc
            finally:
                sys.setprofile(old_profile)

            self.assertTrue(hook_fired, "constructor-entry fault injection did not run")
            self.assertIsNone(hook_error, f"fixture mutation failed: {type(hook_error).__name__}")
            if outcome is not None:
                self.assertIsInstance(outcome, auth.AuthError)
                self.assertEqual(outcome.code, "authority_stale")
                lease_beta = self.require_success(
                    lambda: coordinator.open(fresh_beta, deadline=110.0),
                    "beta cannot open after rejected drift",
                )
                self.require_success(
                    lambda: coordinator.check(lease_beta, fresh_beta, deadline=110.0),
                    "beta lease invalid after rejected drift",
                )
                return

            # Probe both identities before asserting so the fault also demonstrates
            # simultaneous beta authority under two registry entries.
            alpha_current = self.is_current(
                lambda: coordinator.check(lease_alpha, fresh_alpha, deadline=110.0)
            )
            beta_current_on_alpha_lease = self.is_current(
                lambda: coordinator.check(lease_alpha, fresh_beta, deadline=110.0)
            )
            lease_beta = self.require_success(
                lambda: coordinator.open(fresh_beta, deadline=110.0),
                "independent beta cannot open while alpha held",
            )
            self.require_success(
                lambda: coordinator.check(lease_beta, fresh_beta, deadline=110.0),
                "independent beta lease invalid",
            )
            self.assertFalse(
                beta_current_on_alpha_lease,
                "alpha registry lease and independent beta lease both accept beta",
            )
            self.assertTrue(alpha_current, "returned lease did not retain alpha capture")
        finally:
            sys.setprofile(old_profile)
            if lease_beta is not None:
                coordinator.release(lease_beta)
            if lease_alpha is not None:
                coordinator.release(lease_alpha)


if __name__ == "__main__":
    unittest.main()
