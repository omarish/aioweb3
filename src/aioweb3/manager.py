from typing import (TYPE_CHECKING, Any, Callable, Dict, List,  # noqa: F401
                    NoReturn, Optional, Sequence, Tuple, Union)
from uuid import UUID

from web3._utils.threads import ThreadWithReturn, spawn  # noqa: F401
from web3.datastructures import NamedElementOnion
from web3.manager import RequestManager
from web3.providers.async_base import AsyncBaseProvider
from web3.types import (Middleware, MiddlewareOnion, RPCEndpoint,  # noqa: F401
                        RPCResponse)

from aioweb3.provider import AsyncHTTPProvider

from .exceptions import SyncCallDetectedError
from .middleware import (
    abi_middleware,
    async_buffered_gas_estimate_middleware,
    async_gas_price_strategy_middleware,
    attrdict_middleware,
    name_to_address_middleware,
    pythonic_middleware,
    request_parameter_normalizer,
    validation_middleware
)


class AsyncRequestManager(RequestManager):
    def __init__(
        self,
        web3: 'AsyncWeb3',
        provider: Optional[AsyncBaseProvider] = None,
        middlewares: Optional[Sequence[Tuple[Middleware,
                                             str]]] = None
    ) -> None:
        self.web3 = web3
        self.pending_requests: Dict[UUID, ThreadWithReturn[RPCResponse]] = {}

        if middlewares is None:
            middlewares = self.default_middlewares(web3)
        self.middleware_onion: MiddlewareOnion = NamedElementOnion(middlewares)

        if provider is None:
            self.provider = AsyncHTTPProvider()
        else:
            if not isinstance(provider, (AsyncBaseProvider,)):
                raise SyncCallDetectedError(f"are you sure {provider} is async")
            self.provider = provider

    async def _coro_make_request(
        self,
        method: Union[RPCEndpoint,
                      Callable[...,
                               RPCEndpoint]],
        params: Any
    ) -> RPCResponse:
        # type ignored b/c request_func is an awaitable in async model
        request_func = await self.provider.request_func(  # type: ignore
            self.web3,
            self.middleware_onion)
        self.logger.debug("Making request. Method: %s", method)
        return await request_func(method, params)

    @staticmethod
    def default_middlewares(web3: 'AsyncWeb3') -> List[Tuple[Middleware, str]]:
        """
        List the default middlewares for the request manager.
        Leaving ens unspecified will prevent the middleware from resolving names.
        """
        return [
            (request_parameter_normalizer, 'request_param_normalizer'),
            (async_gas_price_strategy_middleware, 'gas_price_strategy'),
            # (name_to_address_middleware(web3), 'name_to_address'),  Currently is async
            (attrdict_middleware, 'attrdict'),  # No blocking calls
            (pythonic_middleware, 'pythonic'),  # No blocking calls
            (validation_middleware, 'validation'),
            (abi_middleware, 'abi'),
            (async_buffered_gas_estimate_middleware, 'gas_estimate'),
        ]