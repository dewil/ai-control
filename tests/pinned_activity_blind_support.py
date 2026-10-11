"""Synthetic public fixtures for spec945664f; no implementation oracle."""
from copy import deepcopy
import time
import navigation_start_blind_support as nav
import native_queue_blind_support as q

NOW=1800000000
FIELDS={'status','waits','last_activity','observed_at','activity_state'}


def item(pin_id=q.MID,project='demo',sid=q.SID,title='Pinned synthetic A',available=True,
         status='idle',waits=None,last_activity=NOW-300,observed_at=NOW,activity_state='fresh'):
    row=nav.pin_item(pin_id,project,sid,title,available)
    row.update(status=status,waits=waits or [],last_activity=last_activity,observed_at=observed_at,activity_state=activity_state)
    return row


def unknown(pin_id=q.MID,available=True,title='Pinned synthetic A'):
    return item(pin_id=pin_id,title=title,available=available,status='unknown',last_activity=None,observed_at=None,activity_state='unavailable')


def dto(rows=None,now=NOW):return dict(schema=2,server_now=now,items=deepcopy([item()] if rows is None else rows))


class ActivityRPC(nav.StartRPC):
    def __init__(self,root):
        super().__init__(root);self.metadata={};self.after_read=None;self.timeouts=[];self.reading=False
    def __call__(self,method,params):
        result=super().__call__(method,params)
        if method=='thread/read' and self.reading:
            sid=params['threadId'];value=self.metadata.get(sid,{})
            if isinstance(value,BaseException):raise value
            result['thread'].update(deepcopy(value))
            result['thread']['id']=value.get('id',sid)
            if self.after_read:self.after_read(sid)
        return result
    def call_in_generation(self,method,params,*,transport_generation,context_generation,timeout=None):
        if method=='thread/read' and self.reading:self.timeouts.append(timeout)
        return super().call_in_generation(method,params,transport_generation=transport_generation,context_generation=context_generation,timeout=timeout)
