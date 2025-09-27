import asyncio
import grpc
import streamlit as st
from typing import AsyncGenerator

import stockstream_pb2
import stockstream_pb2_grpc

API_SERVER = "localhost:50051"

"""
Connect to gRPC server and receive stock price update
"""
async def grpc_stock_stream(
    symbols: list[str]
) -> AsyncGenerator[stockstream_pb2.StockPriceUpdate, None]:
    async with grpc.aio.insecure_channel(API_SERVER) as channel:
        stub = stockstream_pb2_grpc.StockDataStreamerStub(channel)
        req = stockstream_pb2.SubscribeRequest(symbols=symbols)
        async for update in stub.SubscribeSymbols(req):
            yield update


"""
Continuously update streamlit with incoming stock price updates
"""
async def update_ui(
    symbols: list[str]
) -> None:
    async for update in grpc_stock_stream(symbols):
        st.write(f"{update.symbol} Price: {update.price:.2f} @ {update.timestamp}")


def start_stream() -> None:
    st.title("Live Stock Price")

    symbols = st.text_input("Enter stock symbols (comma separated): ", "AAPL, MSFT, TSLA")
    symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    if st.button("Start Streaming"):
        asyncio.create_task(update_ui(symbols))

if __name__ == "__main__":
    start_stream()