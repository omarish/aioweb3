import functools
from typing import TYPE_CHECKING, Any, Callable, Sequence

from web3.middleware.abi import abi_middleware  # noqa: F401
from web3.middleware.attrdict import attrdict_middleware  # noqa: F401
from web3.middleware.buffered_gas_estimate import (  # noqa: F401
    async_buffered_gas_estimate_middleware, buffered_gas_estimate_middleware)
from web3.middleware.cache import \
    _latest_block_based_cache_middleware as \
    latest_block_based_cache_middleware  # noqa: F401
from web3.middleware.cache import \
    _simple_cache_middleware as simple_cache_middleware
from web3.middleware.cache import \
    _time_based_cache_middleware as time_based_cache_middleware
from web3.middleware.cache import (
    construct_latest_block_based_cache_middleware,
    construct_simple_cache_middleware,
    construct_time_based_cache_middleware
)
from web3.middleware.exception_handling import \
    construct_exception_handler_middleware  # noqa: F401
from web3.middleware.exception_retry_request import \
    http_retry_request_middleware  # noqa: F401
from web3.middleware.filter import local_filter_middleware  # noqa: F401
from web3.middleware.fixture import (  # noqa: F401
    construct_error_generator_middleware, construct_fixture_middleware,
    construct_result_generator_middleware)
from web3.middleware.formatting import \
    construct_formatting_middleware  # noqa: F401
from web3.middleware.gas_price_strategy import (  # noqa: F401
    async_gas_price_strategy_middleware, gas_price_strategy_middleware)
from web3.middleware.geth_poa import geth_poa_middleware  # noqa: F401
from web3.middleware.names import name_to_address_middleware  # noqa: F401
from web3.middleware.normalize_request_parameters import \
    request_parameter_normalizer  # noqa: F401
from web3.middleware.pythonic import pythonic_middleware  # noqa: F401
from web3.middleware.signing import \
    construct_sign_and_send_raw_middleware  # noqa: F401
from web3.middleware.stalecheck import make_stalecheck_middleware  # noqa: F401
from web3.middleware.validation import validation_middleware  # noqa: F401
from web3.types import Middleware, RPCEndpoint, RPCResponse

if TYPE_CHECKING:
    from web3 import Web3  # noqa: F401


async def async_combine_middlewares(
    middlewares: Sequence[Middleware],
    web3: 'Web3',
    provider_request_fn: Callable[[RPCEndpoint,
                                   Any],
                                  Any]
) -> Callable[...,
              RPCResponse]:
    """
    Returns a callable function which will call the provider.provider_request
    function wrapped with all of the middlewares.
    """
    accumulator_fn = provider_request_fn
    for middleware in reversed(middlewares):
        accumulator_fn = await construct_middleware(middleware, accumulator_fn, web3)
    return accumulator_fn


async def construct_middleware(middleware: Middleware,
                               fn: Callable[...,
                                            RPCResponse],
                               w3: 'Web3') -> Callable[[RPCEndpoint,
                                                        Any],
                                                       Any]:
    return await middleware(fn, w3)
