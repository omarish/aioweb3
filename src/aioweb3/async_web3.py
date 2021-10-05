from web3.eth import AsyncEth
from web3.net import AsyncNet
from web3 import Web3
from .provider import AsyncHTTPProvider


class AsyncWeb3(Web3):
    pass


class ContractFunction:
    async def call(self):
        pass


class Contract:
    def __new__():
        pass

    def call(self):
        pass


MODULES = {'eth': (AsyncEth,), 'net': (AsyncNet,)}

async_web3 = AsyncWeb3(AsyncHTTPProvider(), modules=MODULES)