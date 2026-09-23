from abc import ABC,abstractmethod


class DistributionChannel(ABC):
    @abstractmethod
    def push_property(self,property_id:str): ...
    @abstractmethod
    def push_rates(self,property_id:str): ...
    @abstractmethod
    def push_inventory(self,property_id:str): ...
    @abstractmethod
    def pull_reservations(self,property_id:str): ...
    @abstractmethod
    def acknowledge_reservation(self,reservation_id:str): ...
    @abstractmethod
    def health_check(self): ...


class RoyaMarketplaceChannel(DistributionChannel):
    def push_property(self,property_id): return {"local":True,"property_id":property_id}
    def push_rates(self,property_id): return {"local":True,"property_id":property_id}
    def push_inventory(self,property_id): return {"local":True,"property_id":property_id}
    def pull_reservations(self,property_id): return []
    def acknowledge_reservation(self,reservation_id): return {"acknowledged":True,"reservation_id":reservation_id}
    def health_check(self): return {"status":"ok"}


class DirectBookingChannel(RoyaMarketplaceChannel):
    pass
