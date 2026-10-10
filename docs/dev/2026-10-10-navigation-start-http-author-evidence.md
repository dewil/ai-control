# PIN/QSTART HTTP and broker checkpoint

Fixed owner APIs mirror public core methods through RegistryBackend, owner Unix dispatcher and SocketBackend. PIN principal comes from the verified server session; public spoofing/extra/duplicate keys are rejected and non-owner broker principal is forbidden before core. Responses use closed PIN/support/start validators. POST unknown remains503, status GET200; r12 Queue DTO is unchanged. No arbitrary RPC/actor/path surface added.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_navigation_start_module_blind test_control_web_navigation_start_http_broker_blind
```
27PASS1.953s, `/var/tmp/control-participation-nav-http-green.log` (19module/wire+8HTTP/broker). An initial misplaced optional read guard caused5auth-fixture setup errors; it was removed from the unrelated session route and localized to chat_read's new owner-only option, then all27 passed. Auth issuance/TTL/TOTP/grants/native state unchanged.

Browser NAV11 remains next slice. PART runtime not started; independent packets will be integrated at this clean boundary. Frozen tests unchanged. No fullCI, production/native RPC, service/restart/deploy or paid calls. Usage unknown; root owns ledger/gates.
