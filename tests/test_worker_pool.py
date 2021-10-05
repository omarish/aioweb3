import asyncio
from asyncio import Queue

from aioweb3 import AsyncWeb3


async def producer(queue: Queue, jobs: int):
    print(f"Enqueue {jobs} jobs")
    for index in range(jobs):
        await queue.put(index)


async def consumer(queue: Queue, index: int):
    def log(*args, **kwargs):
        print(f"Worker {index}: ", *args, **kwargs)

    log("Boot")
    web3 = AsyncWeb3()
    while 1:
        await queue.get()
        block = await web3.eth.get_block("latest")
        log("latest block: ", block.number)
        queue.task_done()


async def entrypoint(jobs: int = 5_000, workers: int = 50):
    queue = Queue()
    producers = [asyncio.create_task(producer(queue, jobs))]
    consumers = [
        asyncio.create_task(consumer(queue, i)) for i in range(workers)
    ]

    await asyncio.gather(*producers)
    await queue.join()


def test_workers():
    """Simple test cast to run a bunch of workers in parallel."""
    asyncio.run(entrypoint())
