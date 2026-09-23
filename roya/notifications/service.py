from abc import ABC,abstractmethod


class NotificationAdapter(ABC):
    @abstractmethod
    def send(self,*,recipient:str,subject:str,body:str): ...


class NotificationService:
    def __init__(self,adapter:NotificationAdapter|None=None):
        self.adapter=adapter

    def send(self,*,recipient,subject,body):
        if not self.adapter:
            return {"sent":False,"reason":"notification_adapter_not_configured"}
        return self.adapter.send(recipient=recipient,subject=subject,body=body)
