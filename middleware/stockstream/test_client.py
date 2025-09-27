import asyncio
import grpc
import stockstream_pb2
import stockstream_pb2_grpc

API_SERVER = "localhost:50051"

async def main():
    async with grpc.aio.insecure_channel(API_SERVER) as channel:
        stub = stockstream_pb2_grpc.StockDataStreamerStub(channel)
        req = stockstream_pb2.SubscribeRequest(symbols=["AAPL"])
        async for update in stub.SubscribeSymbols(req):
            print(f"Got update: {update.symbol} {update.price} @ {update.timestamp}")

asyncio.run(main())
