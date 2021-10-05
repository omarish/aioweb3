import asyncio

from aioweb3 import AsyncWeb3


async def request():
    async_web3 = AsyncWeb3()
    return await async_web3.eth.get_block('latest')


if __name__ == '__main__':
    asyncio.run(request())
