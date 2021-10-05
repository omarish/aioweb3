from web3.providers import async_rpc


class AsyncHTTPProvider(async_rpc.AsyncHTTPProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
