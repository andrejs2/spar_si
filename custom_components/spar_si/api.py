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
    DEFAULT_STORE_REFERENCE,
    DPL_API_KEY,
    FIREBASE_API_KEY,
    FIREBASE_AUTH_URL,
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
    reference: str
    name: str
    unit: str
    unit_quantity: float
    price_total: float
    price_subtotal: float
    image_url: str | None = None


CART_MODIFIABLE_STATUSES = {"CREATED", "ACTIVE", "PROCESSING"}


@dataclass
class SparCart:
    """The SPAR Online shopping cart."""

    cart_id: str
    status: str = ""
    items: list[SparCartItem] = field(default_factory=list)
    item_count: int = 0

    @property
    def is_modifiable(self) -> bool:
        """Check if the cart can be modified (add/remove items)."""
        return self.status in CART_MODIFIABLE_STATUSES or not self.status


@dataclass
class SparCustomer:
    """Authenticated customer info."""

    id: str
    name: str
    email: str
    uid: str


# ─── GraphQL fragments ────────────────────────────────────────────

CART_PRODUCT_FIELDS = """
    id
    name
    reference
    unit
    unitQuantity
    imageUrl
    price {
        total
        subtotal
    }
"""

CART_FIELDS = f"""
    id
    status
    products {{
        {CART_PRODUCT_FIELDS}
    }}
"""


class SparApiClient:
    """Async API client for SPAR Online."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        store_reference: str = DEFAULT_STORE_REFERENCE,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._email = email
        self._password = password
        self._store_reference = store_reference
        self._token: str | None = None
        self._customer: SparCustomer | None = None
        self._cart_id: str | None = None
        self._cart_status: str | None = None

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

    async def _firebase_sign_in(self) -> str:
        """Sign in via Firebase Auth REST API, return idToken."""
        url = f"{FIREBASE_AUTH_URL}?key={FIREBASE_API_KEY}"
        payload = {
            "email": self._email,
            "password": self._password,
            "returnSecureToken": True,
        }
        headers = {
            "Content-Type": "application/json",
            "Referer": "https://online.spar.si/",
            "Origin": "https://online.spar.si",
        }

        try:
            async with async_timeout.timeout(API_TIMEOUT):
                async with self._session.post(
                    url, json=payload, headers=headers
                ) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        error_msg = data.get("error", {}).get(
                            "message", "Unknown Firebase error"
                        )
                        raise SparAuthError(
                            f"Firebase auth failed: {error_msg}"
                        )
                    return data["idToken"]
        except TimeoutError as err:
            raise SparConnectionError(
                "Firebase auth request timed out"
            ) from err
        except aiohttp.ClientError as err:
            raise SparConnectionError(
                f"Firebase connection error: {err}"
            ) from err

    async def async_authenticate(self) -> SparCustomer:
        """Authenticate: Firebase Auth -> Instaleap JWT (v2 signIn)."""
        # Step 1: Firebase sign in
        firebase_token = await self._firebase_sign_in()

        # Step 2: Exchange for Instaleap JWT
        query = """
        mutation SignIn($clientId: String!, $accessToken: String!) {
            signIn(clientId: $clientId, accessToken: $accessToken) {
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
            "clientId": CLIENT_ID,
            "accessToken": firebase_token,
        }

        try:
            data = await self._request_v2(query, variables, "SignIn")
        except SparApiError as err:
            raise SparAuthError(f"Instaleap auth failed: {err}") from err

        sign_in = data.get("signIn", {})
        self._token = sign_in.get("token")
        if not self._token:
            raise SparAuthError("No token received from Instaleap")

        customer_data = sign_in.get("customer", {})
        self._customer = SparCustomer(
            id=customer_data.get("id", ""),
            name=customer_data.get("name", ""),
            email=customer_data.get("email", ""),
            uid=customer_data.get("uid", ""),
        )
        _LOGGER.debug("Authenticated as %s", self._customer.email)
        return self._customer

    async def _ensure_authenticated(self) -> None:
        """Ensure we have a valid token, re-authenticate if needed."""
        if not self._token:
            await self.async_authenticate()

    # ─── Product Search ────────────────────────────────────────────

    async def async_search_products(
        self,
        query: str,
        store_reference: str | None = None,
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
                        name
                    }
                }
            }
        }
        """
        variables = {
            "input": {
                "storeReference": store_reference or self._store_reference,
                "pageSize": page_size,
                "currentPage": page,
                "search": [{"query": query}],
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

        # Try to get active cart first
        gql_get = f"""
        query GetActiveEcommerceCart($input: GetActiveEcommerceCartInput!) {{
            getActiveEcommerceCart(getActiveCartInput: $input) {{
                {CART_FIELDS}
            }}
        }}
        """
        variables_get = {
            "input": {
                "storeReference": self._store_reference,
                "operationalModel": "DELIVERY",
            }
        }

        try:
            data = await self._request_v3(
                gql_get, variables_get, "GetActiveEcommerceCart"
            )
            cart_data = data.get("getActiveEcommerceCart")
            if cart_data:
                return self._parse_cart(cart_data)
        except SparApiError:
            _LOGGER.debug("No active cart found, creating new one")

        # Create new cart
        gql_create = f"""
        mutation CreateEcommerceCart($input: CreateEcommerceCartInput!) {{
            createEcommerceCart(createCartInput: $input) {{
                {CART_FIELDS}
            }}
        }}
        """
        variables_create = {
            "input": {
                "storeReference": self._store_reference,
                "operationalModel": "DELIVERY",
            }
        }

        try:
            data = await self._request_v3(
                gql_create, variables_create, "CreateEcommerceCart"
            )
        except SparAuthError:
            await self.async_authenticate()
            data = await self._request_v3(
                gql_create, variables_create, "CreateEcommerceCart"
            )

        cart_data = data.get("createEcommerceCart", {})
        return self._parse_cart(cart_data)

    async def async_get_cart(self) -> SparCart:
        """Get the current cart."""
        await self._ensure_authenticated()

        if not self._cart_id:
            return await self.async_get_or_create_cart()

        gql = f"""
        query GetEcommerceCart($cartId: ID!) {{
            getEcommerceCart(cartId: $cartId) {{
                {CART_FIELDS}
            }}
        }}
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
        self,
        reference: str,
        unit: str = "KOS",
        unit_quantity: float = 1.0,
    ) -> SparCart:
        """Add a product to the cart by reference (SKU)."""
        await self._ensure_authenticated()

        if not self._cart_id:
            await self.async_get_or_create_cart()

        if self._cart_status and self._cart_status not in CART_MODIFIABLE_STATUSES:
            raise SparApiError(
                f"Košarica je v statusu '{self._cart_status}' in je ni mogoče spreminjati. "
                "Odpri online.spar.si in dodaj artikel da ustvariš novo košarico."
            )

        gql = f"""
        mutation AddProductToEcommerceCart($input: AddProductToCartInput!) {{
            addProductToEcommerceCart(addProductToCartInput: $input) {{
                {CART_FIELDS}
            }}
        }}
        """
        variables = {
            "input": {
                "cartId": self._cart_id,
                "reference": reference,
                "unit": unit,
                "unitQuantity": unit_quantity,
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
        self,
        product_id: str,
        unit_quantity: float | None = None,
        unit: str | None = None,
    ) -> SparCart:
        """Update a product in the cart by its cart product ID."""
        await self._ensure_authenticated()

        if not self._cart_id:
            raise SparApiError("No active cart")

        gql = f"""
        mutation UpdateProductInEcommerceCart($input: UpdateProductInCartInput!) {{
            updateProductInEcommerceCart(updateProductInCartInput: $input) {{
                {CART_FIELDS}
            }}
        }}
        """
        input_data: dict[str, Any] = {
            "cartId": self._cart_id,
            "productId": product_id,
        }
        if unit_quantity is not None:
            input_data["unitQuantity"] = unit_quantity
        if unit is not None:
            input_data["unit"] = unit

        try:
            data = await self._request_v3(
                gql, {"input": input_data}, "UpdateProductInEcommerceCart"
            )
        except SparAuthError:
            await self.async_authenticate()
            data = await self._request_v3(
                gql, {"input": input_data}, "UpdateProductInEcommerceCart"
            )

        cart_data = data.get("updateProductInEcommerceCart", {})
        return self._parse_cart(cart_data)

    async def async_remove_from_cart(self, product_id: str) -> SparCart:
        """Remove a product from the cart by its cart product ID."""
        await self._ensure_authenticated()

        if not self._cart_id:
            raise SparApiError("No active cart")

        gql = f"""
        mutation DeleteProductInEcommerceCart($input: DeleteProductInCartInput!) {{
            deleteProductInEcommerceCart(deleteProductInCartInput: $input) {{
                {CART_FIELDS}
            }}
        }}
        """
        variables = {
            "input": {
                "cartId": self._cart_id,
                "productId": product_id,
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
        self._cart_status = data.get("status", "")

        items = []
        for item_data in data.get("products", []):
            price_data = item_data.get("price", {})
            items.append(
                SparCartItem(
                    product_id=item_data.get("id", ""),
                    reference=item_data.get("reference", ""),
                    name=item_data.get("name", ""),
                    unit=item_data.get("unit", "KOS"),
                    unit_quantity=float(
                        item_data.get("unitQuantity", 1)
                    ),
                    price_total=float(price_data.get("total", 0)),
                    price_subtotal=float(price_data.get("subtotal", 0)),
                    image_url=item_data.get("imageUrl"),
                )
            )

        return SparCart(
            cart_id=cart_id,
            status=data.get("status", ""),
            items=items,
            item_count=len(items),
        )
