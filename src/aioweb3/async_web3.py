import logging
from typing import Any, Dict, Optional, Sequence, cast

from ens import ENS
from eth_abi.codec import ABICodec
from web3 import Web3
from web3._utils.abi import (build_default_registry, build_strict_registry,
                             map_abi_data)
from web3._utils.empty import empty
from web3._utils.module import attach_modules
from web3.eth import AsyncEth
from web3.main import get_default_modules as get_default_sync_modules
from web3.net import AsyncNet
from web3.providers import BaseProvider
from web3.version import AsyncVersion

from aioweb3.exceptions import SyncCallDetectedError
from aioweb3.manager import AsyncRequestManager

from .provider import AsyncHTTPProvider

MODULES = {'eth': (AsyncEth,), 'net': (AsyncNet,)}


def get_default_async_modules() -> Dict[str, Sequence[Any]]:
    # TODO: comapre this with the result of get_default_sync_modules
    modules = get_default_sync_modules()
    modules["eth"] = (AsyncEth,)
    modules["net"] = (AsyncNet,)
    # modules["version"] = (AsyncVersion,)
    # TODO: parity.personal, geth.{admin,miner,personal,txpool}, testing
    return modules


class AsyncWeb3(Web3):
    logger = logging.getLogger('aioweb3.AsyncWeb3')
    RequestManager = AsyncRequestManager

    # TODO: check ENS to see if it's doing anything network-related
    def __init__(
        self,
        provider: Optional[BaseProvider] = None,
        # provider: BaseProvider,
        middlewares: Optional[Sequence[Any]] = None,
        modules: Optional[Dict[str,
                               Sequence[Any]]] = None,
        ens: ENS = cast(ENS,
                        empty)
    ) -> None:
        # TODO: debugging
        assert self.RequestManager.__name__ == 'AsyncRequestManager'
        if provider:
            assert provider.__class__.__name__ == 'AsyncHTTPProvider'
        else:
            provider = AsyncHTTPProvider()

        if middlewares:
            breakpoint()
        else:
            middlewares = []

        self.manager = self.RequestManager(self, provider, middlewares)
        self.codec = ABICodec(build_default_registry())
        if modules:
            self.logger.debug("received modules", modules)
        modules = {**get_default_async_modules(), **(modules or {})}
        attach_modules(self, modules)
        self.ens = ens

    def _make_request(self, *args, **kwargs):
        raise SyncCallDetectedError()


class ContractFunction:
    async def call(self):
        pass


class Contract:
    def __new__():
        pass

    def call(self):
        pass
