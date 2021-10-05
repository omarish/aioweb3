from web3 import eth
from typing import Any, Union, Optional, Type
from eth_typing import (Address, BlockNumber, ChecksumAddress, HexStr,)
from web3.types import (ENS)

from aioweb3.exceptions import SyncCallDetectedError
from aioweb3.contract import AsyncContract


class AsyncEth(eth.AsyncEth):
    defaultContractFactory = AsyncContract

    def contract(
        self,
        address: Optional[Union[Address,
                                ChecksumAddress,
                                ENS]] = None,
        **kwargs: Any
    ) -> Union[Type[AsyncContract],
               AsyncContract]:

        if 'ContractFactoryClass' in kwargs:
            raise SyncCallDetectedError("only supports AsyncContract for now")
        # ContractFactoryClass = kwargs.pop('ContractFactoryClass', self.defaultContractFactory)
        ContractFactory = AsyncContract.factory(self.web3, **kwargs)

        if address:
            return ContractFactory(address)
        else:
            return ContractFactory