class AsyncWeb3Error(Exception):
    pass


class SyncCallDetectedError(AsyncWeb3Error):
    """Use these liberally in development to catch any cases where sync web3 calls are happening"""
    pass