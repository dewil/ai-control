"""INV-NODE-AUTH-03: per-role source inbox for restricted bridge identity.

Synthetic accepted bridge fixture only; no nats/server/config/credential I/O.
Stop the fake session at bind, before fetch/publish/ACK. Production status
writer and INFO helpers are replaced before the session begins.
"""
import asyncio
import importlib
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from test_control_web_nats_sidecar_blind import FakeNatsFactory, bridge_config


class BridgeSourceIdentityRED(unittest.IsolatedAsyncioTestCase):
    async def session_at_bind(self, auth):
        module=importlib.import_module('_control_web_devbus_nats')
        config=bridge_config();config['source']['auth']=auth
        bound=[]

        class StopAtBindFactory(FakeNatsFactory):
            async def __call__(self, **kwargs):
                connection=await super().__call__(**kwargs)
                if connection.role=='source':
                    async def bind(*args, **options):
                        bound.append((args,options))
                        raise asyncio.CancelledError('synthetic stop before fetch')
                    connection._js.pull_subscribe_bind=bind
                return connection

        factory=StopAtBindFactory(config)
        consumer=NS(ack_floor=NS(stream_seq=0),num_pending=0,num_ack_pending=0)
        with patch.object(module,'_write_bridge_status') as status, \
             patch.object(module,'_bridge_stream_info',new=AsyncMock(return_value=NS(state=NS(first_seq=1)))), \
             patch.object(module,'_bridge_consumer_info',new=AsyncMock(return_value=consumer)):
            with self.assertRaises(asyncio.CancelledError):
                await module._bridge_session(config,factory)
        self.assertEqual(len(factory.connections),2)
        self.assertTrue(all(c.closed for c in factory.connections))
        self.assertEqual(len(bound),1,'must reach exactly one synthetic bind')
        self.assertTrue(status.called,'all status writes intercepted')
        return factory,bound[0][1]

    def user_auth(self):
        return {'mode':'user_password','user':'control_event_bridge','password':'synthetic-source-password'}

    async def test_source_user_password_connection_uses_role_inbox(self):
        factory,_=await self.session_at_bind(self.user_auth())
        source=factory.connections[0].kwargs
        self.assertEqual(source.get('inbox_prefix'),b'_INBOX.control_event_bridge')
        self.assertEqual((source.get('user'),source.get('password')),('control_event_bridge','synthetic-source-password'))
        self.assertNotIn('token',source);self.assertNotIn('user_credentials',source)

    async def test_source_user_password_pull_bind_uses_role_inbox(self):
        _,options=await self.session_at_bind(self.user_auth())
        self.assertEqual(options.get('inbox_prefix'),b'_INBOX.control_event_bridge.')

    async def test_legacy_source_token_and_creds_keep_default_inboxes(self):
        for auth,key,value in [({'mode':'token','token':'synthetic-token'},'token','synthetic-token'),
                               ({'mode':'creds','creds':'/synthetic/creds'},'user_credentials','/synthetic/creds')]:
            with self.subTest(mode=auth['mode']):
                factory,bind=await self.session_at_bind(auth)
                source=factory.connections[0].kwargs
                self.assertEqual(source.get(key),value)
                self.assertNotIn('inbox_prefix',source)
                self.assertNotIn('inbox_prefix',bind)

    async def test_destination_writer_connection_keeps_existing_inbox_for_all_source_modes(self):
        for auth in [self.user_auth(),{'mode':'token','token':'synthetic-token'},{'mode':'creds','creds':'/synthetic/creds'}]:
            with self.subTest(mode=auth['mode']):
                factory,_=await self.session_at_bind(auth)
                destination=factory.connections[1].kwargs
                self.assertNotIn('inbox_prefix',destination)
                self.assertEqual(destination.get('user'),'obs_bridge_writer')
                self.assertNotIn('token',destination);self.assertNotIn('user_credentials',destination)


if __name__=='__main__':unittest.main()
