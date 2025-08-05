from abc import ABC, abstractmethod

from .enums_option import OPTION_TYPE

class OptionValuationModel(ABC):
    def __init__(
            self,
            option_type: OPTION_TYPE,
            parameters: dict
    ):
        self.option_type = option_type
        self.parameters = parameters
    
    def calculate_price(self) -> float:
        if self.option_type == OPTION_TYPE.CALL.value:
            return self.calculate_call_price()
        elif self.option_type == OPTION_TYPE.PUT.value:
            return self.calculate_put_price()
        
    @abstractmethod
    def calculate_call_price(self) -> float:
        pass

    @abstractmethod
    def calculate_put_price(self) -> float:
        pass