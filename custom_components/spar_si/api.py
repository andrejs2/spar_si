"""API client for SPAR Online (online.spar.si) via Instaleap GraphQL."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import async_timeout

from .const import (
    API_TIMEOUT,
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_VERSION,
    DPL_API_KEY,
    GRAPHQL_V2_URL,
    GRAPHQL_V3_URL,
)

_LOGGER = logging.getLogger(__name__)


class SparAuthError(Exception):
    """Authentication failed."""


class SparApiError(Exception):
    """API request failed."""


class SparConnectionError(Exception):
    """Connection to API failed."""


@dataclass
class SparProduct:
    """A product from SPAR Online."""

    sku: str
    name: str
    price: float
    unit: str
    image_url: str | None = None
    ean: list[str] = field(default_factory=list)
    brand: str | None = None
    stock: int = 0
    is_available: bool = True
    slug: str | None = None
    max_qty: int = 30
    min_qty: int = 1
    category: str | None = None


@dataclass
class SparCartItem:
    """An item in the SPAR Online cart."""

    product_id: str
    sku: str
    name: str
    quantity: int
    unit: str
    price: float
    total: float
    image_url: str | None = None


@dataclass
class SparCart:
    """The SPAR Online shopping cart."""

    cart_id: str
    items: list[SparCartItem] = field(default_factory=list)
    total: float = 0.0
    item_count: int = 0


@dataclass
class SparCustomer:
    """Authenticated customer info."""

    id: str
    name: str
    email: str
    uid: str


class SparApiClient:
    """Async API client for SPAR Online."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        store_id: str = "4",
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._email = email
        self._password = password
        self._store_id = store_id
        self._token: str | None = None
        self._customer: SparCustomer | None = None
        self._cart_id: str | None = None

    @property
    def customer(self) -> SparCustomer | None:
        """Return the authenticated customer."""
        return self._customer

    def _base_headers(self) -> dict[str, str]:
        """Return base headers for all requests."""
        headers = {
            "Content-Type": "application/json",
            "dpl-api-key": DPL_API_KEY,
            "client-name": CLIENT_NAME,
            "client-version": CLIENT_VERSION,
        }
        if self._token:
            headers["token"] = self._token
        return headers

    async def _graphql_request(
        self,
        url: str,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL request."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        if operation_name:
            payload["operationName"] = operation_name

        try:
            async with async_timeout.timeout(API_TIMEOUT):
                async with self._session.post(
                    url, json=payload, headers=self._base_headers()
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise SparApiError(
                            f"HTTP {resp.status}: {text[:200]}"
                        )
                    data = await resp.json()
        except TimeoutError as err:
            raise SparConnectionError("Request timed out") from err
        except aiohttp.ClientError as err:
            raise SparConnectionError(f"Connection error: {err}") from err

        if "errors" in data:
            errors = data["errors"]
            # Check for auth errors
            for error in errors:
                code = error.get("extensions", {}).get("code", "")
                if code == "UNAUTHENTICATED":
                    raise SparAuthError("Token expired or invalid")
            msg = errors[0].get("message", str(errors))
            raise SparApiError(f"GraphQL error: {msg}")

        return data.get("data", {})

    async def _request_v2(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Execute a v2 GraphQL request."""
        return await self._graphql_request(
            GRAPHQL_V2_URL, query, variables, operation_name
        )

    async def _request_v3(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Execute a v3 GraphQL request."""
        return await self._graphql_request(
            GRAPHQL_V3_URL, query, variables, operation_name
        )

    # ─── Authentication ────────────────────────────────────────────

    async def async_authenticate(self) -> SparCustomer:
        """Authenticate with SPAR Online using email/password (v3)."""
        query = """
        mutation SignIn($signInInput: SignInInput!) {
            signIn(signInInput: $signInInput) {
                customer {
                    id
                    name
                    email
                    uid
                }
                token
            }
        }
        """
        variables = {
            "signInInput": {
                "clientId": CLIENT_ID,
                "email": self._email,
                "password": self._password,
            }
        }

        try:
            data = await self._request_v3(query, variables, "SignIn")
        except SparApiError as err:
            raise SparAuthError(f"Authentication failed: {err}") from err

        sign_in = data.get("signIn", {})
        self._token = sign_in.get("token")
        if not self._token:
            raise SparAuthError("No token received")

        customer_data = sign_in.get("customer", {})
        self._customer = SparCustomer(
            id=customer_data.get("id", ""),
            name=customer_data.get("name", ""),
            email=customer_data.get("email", ""),
            uid=customer_data.get("uid", ""),
        )
        _LOGGER.debug("Authenticated as %s", self._customer.email)
        return self._customer

    async def async_validate_credentials(self) -> bool:
        """Validate credentials by attempting authentication."""
        await self.async_authenticate()
        return True

    async def _ensure_authenticated(self) -> None:
        """Ensure we have a valid token, re-authenticate if needed."""
        if not self._token:
            await self.async_authenticate()

    # ─── Product Search ────────────────────────────────────────────

    async def async_search_products(
        self,
        query: str,
        store_reference: str = "81701",
        page_size: int = 20,
        page: int = 1,
    ) -> list[SparProduct]:
        """Search for products by name."""
        await self._ensure_authenticated()

        gql = """
        query SearchProducts($input: SearchProductsInput!) {
            searchProducts(searchProductsInput: $input) {
                products {
                    sku
                    name
                    price
                    unit
                    photosUrl
                    ean
                    brand
                    stock
                    isAvailable
                    slug
                    maxQty
                    minQty
                    categories {
                        id
                        name
                    }
                }
                totalCount
            }
        }
        """
        variables = {
            "input": {
                "storeReference": store_reference,
                "pageSize": page_size,
                "currentPage": page,
                "search": [{"query": query, "fields": ["name"]}],
            }
        }

        try:
            data = await self._request_v3(gql, variables, "SearchProducts")
        except SparAuthError:
            await self.async_authenticate()
            data = await self._request_v3(gql, variables, "SearchProducts")

        products_data = (
            data.get("searchProducts", {}).get("products", [])
        )
        return [self._parse_product(p) for p in products_data]

    def _parse_product(self, data: dict[str, Any]) -> SparProduct:
        """Parse a product from API response."""
        photos = data.get("photosUrl", [])
        categories = data.get("categories", [])
        return SparProduct(
            sku=data.get("sku", ""),
            name=data.get("name", ""),
            price=float(data.get("price", 0)),
            unit=data.get("unit", "KOS"),
            image_url=photos[0] if photos else None,
            ean=data.get("ean", []),
            brand=data.get("brand"),
            stock=int(data.get("stock", 0)),
            is_available=data.get("isAvailable", True),
            slug=data.get("slug"),
            max_qty=int(data.get("maxQty", 30)),
            min_qty=int(data.get("minQty", 1)),
            category=categories[0].get("name") if categories else None,
        )

    # ─── Cart Management ───────────────────────────────────────────

    async def async_get_or_create_cart(self) -> SparCart:
        """Get the active cart or create a new one."""
        await self._ensure_authenticated()

        gql = """
        mutation GetActiveOrCreateEcommerceCart($input: CreateEcommerceCartInput!) {
            getActiveOrCreateEcommerceCart(createCartInput: $input) {
                id
                products {
                    product {
                        sku
                        name
                        price
                        unit
                        photosUrl
                    }
                    quantity
                    total
                }
                total
            }
        }
        """
        variables = {
            "input": {
                "storeId": self._store_id,
            }
        }

        try:
            data = await self._request_v3(
                gql, variables, "GetActiveOrCreateEcommerceCart"
            )
        except SparAuthError:
            await self.async_authenticate()
            data = await self._request_v3(
                gql, variables, "GetActiveOrCreateEcommerceCart"
            )

        cart_data = data.get("getActiveOrCreateEcommerceCart", {})
        return self._parse_cart(cart_data)

    async def async_get_cart(self) -> SparCart:
        """Get the current cart."""
        await self._ensure_authenticated()

        if not self._cart_id:
            return await self.async_get_or_create_cart()

        gql = """
        query GetEcommerceCart($cartId: ID!) {
            getEcommerceCart(cartId: $cartId) {
                id
                products {
                    product {
                        sku
                        name
                        price
                        unit
                        photosUrl
                    }
                    quantity
                    total
                }
                total
            }
        }
        """
        try:
            data = await self._request_v3(
                gql, {"cartId": self._cart_id}, "GetEcommerceCart"
            )
        except SparAuthError:
            await self.async_authenticate()
            data = await self._request_v3(
                gql, {"cartId": self._cart_id}, "GetEcommerceCart"
            )

        cart_data = data.get("getEcommerceCart", {})
        return self._parse_cart(cart_data)

    async def async_add_to_cart(
        self, sku: str, quantity: int = 1
    ) -> SparCart:
        """Add a product to the cart."""
        await self._ensure_authenticated()

        if not self._cart_id:
            await self.async_get_or_create_cart()

        gql = """
        mutation AddProductToEcommerceCart($input: AddProductToCartInput!) {
            addProductToEcommerceCart(addProductToCartInput: $input) {
                id
                products {
                    product {
                        sku
                        name
                        price
                        unit
                        photosUrl
                    }
                    quantity
                    total
                }
                total
            }
        }
        """
        variables = {
            "input": {
                "cartId": self._cart_id,
                "sku": sku,
                "quantity": quantity,
            }
        }

        try:
            data = await self._request_v3(
                gql, variables, "AddProductToEcommerceCart"
            )
        except SparAuthError:
            await self.async_authenticate()
            data = await self._request_v3(
                gql, variables, "AddProductToEcommerceCart"
            )

        cart_data = data.get("addProductToEcommerceCart", {})
        return self._parse_cart(cart_data)

    async def async_update_cart_item(
        self, sku: str, quantity: int
    ) -> SparCart:
        """Update quantity of a product in the cart."""
        await self._ensure_authenticated()

        if not self._cart_id:
            raise SparApiError("No active cart")

        gql = """
        mutation UpdateProductInEcommerceCart($input: UpdateProductInCartInput!) {
            updateProductInEcommerceCart(updateProductInCartInput: $input) {
                id
                products {
                    product {
                        sku
                        name
                        price
                        unit
                        photosUrl
                    }
                    quantity
                    total
                }
                total
            }
        }
        """
        variables = {
            "input": {
                "cartId": self._cart_id,
                "sku": sku,
                "quantity": quantity,
            }
        }

        try:
            data = await self._request_v3(
                gql, variables, "UpdateProductInEcommerceCart"
            )
        except SparAuthError:
            await self.async_authenticate()
            data = await self._request_v3(
                gql, variables, "UpdateProductInEcommerceCart"
            )

        cart_data = data.get("updateProductInEcommerceCart", {})
        return self._parse_cart(cart_data)

    async def async_remove_from_cart(self, sku: str) -> SparCart:
        """Remove a product from the cart."""
        await self._ensure_authenticated()

        if not self._cart_id:
            raise SparApiError("No active cart")

        gql = """
        mutation DeleteProductInEcommerceCart($input: DeleteProductInCartInput!) {
            deleteProductInEcommerceCart(deleteProductInCartInput: $input) {
                id
                products {
                    product {
                        sku
                        name
                        price
                        unit
                        photosUrl
                    }
                    quantity
                    total
                }
                total
            }
        }
        """
        variables = {
            "input": {
                "cartId": self._cart_id,
                "sku": sku,
            }
        }

        try:
            data = await self._request_v3(
                gql, variables, "DeleteProductInEcommerceCart"
            )
        except SparAuthError:
            await self.async_authenticate()
            data = await self._request_v3(
                gql, variables, "DeleteProductInEcommerceCart"
            )

        cart_data = data.get("deleteProductInEcommerceCart", {})
        return self._parse_cart(cart_data)

    def _parse_cart(self, data: dict[str, Any]) -> SparCart:
        """Parse cart data from API response."""
        cart_id = data.get("id", "")
        self._cart_id = cart_id

        items = []
        for item_data in data.get("products", []):
            product = item_data.get("product", {})
            photos = product.get("photosUrl", [])
            items.append(
                SparCartItem(
                    product_id=product.get("id", product.get("sku", "")),
                    sku=product.get("sku", ""),
                    name=product.get("name", ""),
                    quantity=int(item_data.get("quantity", 1)),
                    unit=product.get("unit", "KOS"),
                    price=float(product.get("price", 0)),
                    total=float(item_data.get("total", 0)),
                    image_url=photos[0] if photos else None,
                )
            )

        return SparCart(
            cart_id=cart_id,
            items=items,
            total=float(data.get("total", 0)),
            item_count=len(items),
        )
