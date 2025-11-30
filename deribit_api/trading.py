"""
A token-aware, HTTP-only Deribit trading client suitable for use from a Telegram command handler.

This client manages the Deribit authentication lifecycle, including token acquisition and transparent refresh.
It provides helper methods for common trading operations and is designed to be used as an async context manager.
"""
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, Optional

import httpx

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DeribitError(Exception):
    """Base exception for Deribit client errors."""
    pass


class AuthenticationError(DeribitError):
    """Raised when authentication fails."""
    pass


class DeribitHTTPError(DeribitError):
    """Raised for non-2xx HTTP responses."""
    def __init__(self, message: str, status_code: int, url: str):
        super().__init__(f"{message} (Status: {status_code}, URL: {url})")
        self.status_code = status_code
        self.url = url


class DeribitRPCError(DeribitError):
    """Raised when the Deribit API returns a JSON-RPC error."""
    def __init__(self, error_details: Dict[str, Any]):
        super().__init__(f"Deribit API Error: {error_details.get('message')} (Code: {error_details.get('code')})")
        self.error_details = error_details


class DeribitTrading:
    """
    An asynchronous, HTTP-only client for the Deribit trading API.
    """
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = "https://www.deribit.com/api/v2",
        client: Optional[httpx.AsyncClient] = None,
        base_timeout: float = 10.0
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(base_timeout, connect=5.0, read=15.0, write=10.0)
        )
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at: float = 0
        self.connected: bool = False
        self._request_id_counter: int = 1

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()

    async def connect(self):
        """
        Authenticate with the Deribit API and obtain an access token.
        """
        if self.connected and time.time() < self.expires_at:
            return

        auth_params = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        try:
            response = await self.client.get(
                f"{self.base_url}/public/auth", params=auth_params
            )
            response.raise_for_status()
            res = response.json()
            self._process_auth_response(res["result"])
            self.connected = True
            logger.info("Successfully connected to Deribit API.")
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to connect to Deribit API: {e.response.text}")
            raise DeribitHTTPError("Failed to connect", e.response.status_code, str(e.request.url)) from e
        except (httpx.RequestError, asyncio.TimeoutError) as e:
            logger.error(f"Network error while connecting to Deribit: {e}")
            raise DeribitHTTPError("Network error during connection", 0, f"{self.base_url}/public/auth") from e

    async def disconnect(self):
        """
        Clear credentials and state without closing the client.
        Note: Deribit's private/logout is not necessary for stateless HTTP connections.
        """
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0
        self.connected = False
        logger.info("Client disconnected, credentials cleared.")

    async def aclose(self):
        """
        Cleanly close the underlying httpx.AsyncClient.
        """
        await self.disconnect()
        await self.client.aclose()
        logger.info("HTTP client closed.")

    def _get_request_id(self) -> int:
        """Generate a unique request ID."""
        request_id = self._request_id_counter
        self._request_id_counter += 1
        return request_id

    def _process_auth_response(self, result: Dict[str, Any]):
        """
        Process a successful authentication or refresh response.
        """
        self.access_token = result["access_token"]
        self.refresh_token = result["refresh_token"]
        # Safety margin of 60 seconds
        self.expires_at = time.time() + result["expires_in"] - 60
        logger.info(f"Token acquired/refreshed. Valid until {time.ctime(self.expires_at)}.")

    async def _refresh_token(self):
        """
        Refresh the access token using the refresh token.
        """
        if not self.refresh_.token:
            raise AuthenticationError("No refresh token available. Please connect first.")

        refresh_params = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        try:
            response = await self.client.get(
                f"{self.base_url}/public/auth", params=refresh_params
            )
            response.raise_for_status()
            res = response.json()
            self._process_auth_response(res["result"])
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to refresh token: {e.response.text}")
            await self.disconnect()  # Invalidate session on refresh failure
            raise AuthenticationError("Failed to refresh token, session invalidated.") from e

    async def _ensure_token(self):
        """
        Ensure a valid access token is available, connecting or refreshing if necessary.
        """
        if not self.connected:
            await self.connect()
        elif time.time() >= self.expires_at:
            await self._refresh_token()

    async def request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        retry_on_auth_error: bool = True
    ) -> Dict[str, Any]:
        """
        Make a request to a private Deribit API endpoint with token management.
        """
        await self._ensure_token()

        if not params:
            params = {}

        json_payload = {
            "jsonrpc": "2.0",
            "id": self._get_request_id(),
            "method": method,
            "params": params,
        }
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"{self.base_url}" 

        try:
            response = await self.client.post(
                url,
                headers=headers,
                json=json_payload,
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                error = data["error"]
                # 13009: "token_invalid_or_expired"
                if error.get("code") == 13009 and retry_on_auth_error:
                    logger.warning("Authentication error detected, forcing token refresh and retrying.")
                    await self._refresh_token()
                    return await self.request(method, params, retry_on_auth_error=False)
                raise DeribitRPCError(error)
            
            return data.get("result", {})

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for method {method}: {e.response.status_code} - {e.response.text}")
            if e.response.status_code == 401 and retry_on_auth_error:
                logger.warning("HTTP 401 Unauthorized, forcing token refresh and retrying.")
                await self._refresh_token()
                return await self.request(method, params, retry_on_auth_error=False)
            raise DeribitHTTPError("HTTP error", e.response.status_code, str(e.request.url)) from e
        except (httpx.RequestError, asyncio.TimeoutError) as e:
            logger.error(f"Network error for method {method}: {e}")
            raise DeribitHTTPError("Network error", 0, url) from e
        except ValueError: # JSON decode error
            logger.error(f"Failed to decode JSON response for method {method}")
            raise DeribitError(f"Invalid JSON response for method {method}")

    async def buy(self, instrument_name: str, amount: float, **kwargs: Any) -> Dict[str, Any]:
        """
        Place a buy order.
        :param instrument_name: The name of the instrument to buy.
        :param amount: Amount of contracts to buy.
        :param kwargs: Optional order parameters (e.g., price, type, time_in_force).
        """
        params = {"instrument_name": instrument_name, "amount": amount}
        params.update(kwargs)
        if "price" not in params:
            params.setdefault("type", "market")
        else:
            params.setdefault("type", "limit")
            
        return await self.request("private/buy", params)

    async def sell(self, instrument_name: str, amount: float, **kwargs: Any) -> Dict[str, Any]:
        """
        Place a sell order.
        :param instrument_name: The name of the instrument to sell.
        :param amount: Amount of contracts to sell.
        :param kwargs: Optional order parameters (e.g., price, type, time_in_force).
        """
        params = {"instrument_name": instrument_name, "amount": amount}
        params.update(kwargs)
        if "price" not in params:
            params.setdefault("type", "market")
        else:
            params.setdefault("type", "limit")

        return await self.request("private/sell", params)

    async def get_account_summary(self, currency: str, extended: bool = True) -> Dict[str, Any]:
        """
        Get account summary.
        """
        return await self.request("private/get_account_summary", {"currency": currency, "extended": extended})

    async def get_positions(self, currency: str, kind: str = "option") -> Dict[str, Any]:
        """
        Get positions for a currency.
        """
        return await self.request("private/get_positions", {"currency": currency, "kind": kind})

    async def get_open_orders_by_instrument(self, instrument_name: str) -> Dict[str, Any]:
        """
        Get open orders for a specific instrument.
        """
        return await self.request("private/get_open_orders_by_instrument", {"instrument_name": instrument_name})

    async def get_open_orders_by_currency(self, currency: str, kind: str = "option") -> Dict[str, Any]:
        """
        Get open orders for a currency.
        """
        return await self.request("private/get_open_orders_by_currency", {"currency": currency, "kind": kind})

    async def cancel(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel an order by its ID.
        """
        return await self.request("private/cancel", {"order_id": order_id})

    async def cancel_all_by_instrument(self, instrument_name: str, type: str = "all") -> Dict[str, Any]:
        """
        Cancel all orders for a specific instrument.
        """
        return await self.request("private/cancel_all_by_instrument", {"instrument_name": instrument_name, "type": type})

    async def get_order_state(self, order_id: str) -> Dict[str, Any]:
        """
        Get the state of an order.
        """
        return await self.request("private/get_order_state", {"order_id": order_id})
