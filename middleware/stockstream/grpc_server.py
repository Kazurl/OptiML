import asyncio
import grpc
import time
import os
from dotenv import load_dotenv
from typing import AsyncGenerator, List

import stockstream_pb2
import stockstream_pb2_grpc

from alpaca.data.live import StockDataStream

# load .env vars
load_dotenv()


"""
Implementation of Data streaming service from Alpaca API
"""
class StockDataStreamerService(stockstream_pb2_grpc.StockDataStreamerServicer):
    def __init__(self) -> None:
        super().__init__()
        self.clients: List[str] = []  # to track connected clients
        self.latest_prices: dict[str, float] = {}  # latest snapshot(s)

    
    """
    Connect to Alpaca's live streaming websocket and yield StockPriceUpdate msgs
    """
    async def alpaca_stream(
        self,
        symbols: list[str]
    ) -> AsyncGenerator[stockstream_pb2.StockPriceUpdate, None]:
        stream = StockDataStream(
            os.getenv("ALPACA_API_KEY"),
            os.getenv("ALPACA_API_SECRET")
        )
        queue = asyncio.Queue()

        async def trade_handler(data):
            # Put data for processing and send to clients
            await queue.put(data)

        for symbol in symbols:
            stream.subscribe_trades(trade_handler, symbol)

        asyncio.create_task(stream.run())

        while True:
            trade_update = await queue.get()
            symbol = trade_update.symbol
            price = trade_update.price
            timestamp = int(time.time() * 1000)
            self.latest_prices[symbol] = price

            yield stockstream_pb2.StockPriceUpdate(
                symbol=symbol,
                price=price,
                timestamp=timestamp
            )

    
    """
    Client sub to specific symbols and receive price updates
    """
    async def SubscribeSymbols(
        self,
        req: stockstream_pb2.SubscribeRequest,
        context: grpc.aio.ServicerContext
    ) -> AsyncGenerator[stockstream_pb2.StockPriceUpdate, None]:
        # stream data
        async for update in self.alpaca_stream(req.symbols):
            yield update


"""
Run StockDataStreamerService class implementation
    - starts network server and use StockDataStreamerService to handle req
"""
async def serve() -> None:
    # create async gRPC server for concurrency and high perf
    server = grpc.aio.server()

    # adding our StockDataStreamerService as a handler for req
    stockstream_pb2_grpc.add_StockDataStreamerServicer_to_server(
        StockDataStreamerService(), server
    )
    PORT = "[::]:50051"  # std port for gRPC
    server.add_insecure_port(PORT)
    print(f"Starting gRPC server on {PORT}")
    await server.start()  # start server
    await server.wait_for_termination()  # listen for termination and terminate server


if __name__ == "__main__":
    asyncio.run(serve())