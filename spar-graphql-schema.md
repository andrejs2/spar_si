# SPAR Online (online.spar.si) - GraphQL Schema Discovery

## API Endpoints

- **v3 (primary for cart):** `https://deadpool.unified-jennet.instaleap.io/api/v3`
- **v2 (secondary):** `https://deadpool.unified-jennet.instaleap.io/api/v2`
- Platform: **Instaleap Deadpool** e-commerce engine
- Client ID: `SPAR_SLOVENIA`
- Authentication: `token` header + `dpl-api-key` header
- Introspection: **Disabled** (Apollo Server production mode)

---

## Queries

### getActiveEcommerceCart

```graphql
query GetActiveEcommerceCart($input: GetActiveEcommerceCartInput!) {
  getActiveEcommerceCart(getActiveCartInput: $input) {
    # returns CartModel
    id
    status
    operationalModel
    store { ... }
    customer { ... }
    coupon { ... }
    address { ... }
    deliverySlot { ... }
    products { ... }
  }
}
```

### getEcommerceCart

```graphql
query GetEcommerceCart($cartId: ID!) {
  getEcommerceCart(cartId: $cartId) {
    # returns CartModel (same fields as above)
  }
}
```

### getExtraFieldsEcommerceCart

```graphql
query GetExtraFieldsEcommerceCart($input: ExtraFieldInput!) {
  getExtraFieldsEcommerceCart(extraFieldInput: $input) {
    # returns [ExtraFieldModel]
  }
}
```

---

## Mutations

### createEcommerceCart

```graphql
mutation CreateEcommerceCart($input: CreateEcommerceCartInput!) {
  createEcommerceCart(createCartInput: $input) {
    # returns CartModel
  }
}
```

### addProductToEcommerceCart

```graphql
mutation AddProductToEcommerceCart($input: AddProductToCartInput!) {
  addProductToEcommerceCart(addProductToCartInput: $input) {
    # returns CartModel
  }
}
```

### updateProductInEcommerceCart

```graphql
mutation UpdateProductInEcommerceCart($input: UpdateProductInCartInput!) {
  updateProductInEcommerceCart(updateProductInCartInput: $input) {
    # returns CartModel
  }
}
```

### deleteProductInEcommerceCart

```graphql
mutation DeleteProductInEcommerceCart($input: DeleteProductInCartInput!) {
  deleteProductInEcommerceCart(deleteProductInCartInput: $input) {
    # returns CartModel
  }
}
```

### deleteEcommerceCart

```graphql
mutation DeleteEcommerceCart($cartId: ID!) {
  deleteEcommerceCart(cartId: $cartId) {
    # returns CartModel
  }
}
```

---

## Input Types

### GetActiveEcommerceCartInput

| Field             | Type               | Required |
|-------------------|--------------------|----------|
| storeReference    | ID!                | YES      |
| operationalModel  | OperationalModel!  | YES      |

### CreateEcommerceCartInput

| Field             | Type               | Required |
|-------------------|--------------------|----------|
| storeReference    | ID!                | YES      |
| operationalModel  | OperationalModel!  | YES      |
| addressId         | String             | no       |

### AddProductToCartInput

| Field         | Type     | Required |
|---------------|----------|----------|
| cartId        | ID!      | YES      |
| reference     | String!  | YES      |
| unit          | String!  | YES      |
| unitQuantity  | Float!   | YES      |

- `reference` = the product SKU/reference (e.g. "560075")
- `unit` = unit type (e.g. "KOS" for pieces)
- `unitQuantity` = quantity in the given unit

### UpdateProductInCartInput

| Field         | Type     | Required |
|---------------|----------|----------|
| cartId        | ID!      | YES      |
| productId     | ID!      | YES      |
| unit          | String   | no       |
| unitQuantity  | Float    | no       |

### DeleteProductInCartInput

| Field      | Type | Required |
|------------|------|----------|
| cartId     | ID!  | YES      |
| productId  | ID!  | YES      |

### OperationalModel (enum)

```
DELIVERY
PICK_AND_COLLECT
PICK_UP
```

---

## Return Types

### CartModel

| Field            | Type                | Notes                  |
|------------------|---------------------|------------------------|
| id               | ID                  |                        |
| status           | String/Enum         |                        |
| operationalModel | OperationalModel    |                        |
| store            | StoreModel!         | requires subselection  |
| customer         | CustomerModel       | requires subselection  |
| coupon           | CouponModel         | requires subselection  |
| address          | AddressModel        | requires subselection  |
| deliverySlot     | DeliverySlotModel   | requires subselection  |
| products         | [CartProductModel]! | requires subselection  |

### CartProductModel

| Field         | Type           | Notes                 |
|---------------|----------------|-----------------------|
| id            | ID             |                       |
| name          | String         |                       |
| reference     | String         | product SKU           |
| unit          | String         | e.g. "KOS"            |
| unitQuantity  | Float          |                       |
| price         | ProductPrice!  | requires subselection |
| status        | String/Enum    |                       |
| availability  | String/Enum    |                       |
| imageUrl      | String         |                       |
| createdAt     | DateTime       |                       |
| updatedAt     | DateTime       |                       |
| promotion     | Promotion      | requires subselection |
| promotions    | [PromotionV2]  | requires subselection |

### ProductPrice

| Field            | Type   |
|------------------|--------|
| total            | Float  |
| subtotal         | Float  |
| taxes            | Float  |
| discount         | Float  |
| totalBeforeTaxes | Float  |

### StoreModel

| Field      | Type   |
|------------|--------|
| id         | ID     |
| name       | String |
| reference  | String |
| state      | String |
| country    | String |
| address    | String |
| latitude   | Float  |
| longitude  | Float  |

### CustomerModel

| Field                  | Type               | Notes                 |
|------------------------|--------------------|-----------------------|
| id                     | ID                 |                       |
| name                   | String             |                       |
| email                  | String             |                       |
| phoneNumber            | String             |                       |
| documentId             | String             |                       |
| uid                    | String             |                       |
| terms                  | Boolean            |                       |
| notifications          | Boolean            |                       |
| phoneNumberValidated   | Boolean            |                       |
| shoppingCartVersion    | String/Int         |                       |
| customData             | CustomerCustomData | requires subselection |

### AddressModel

| Field       | Type           | Notes                 |
|-------------|----------------|-----------------------|
| id          | ID             |                       |
| description | String         |                       |
| address     | AddressFormat! | requires subselection |
| addressTwo  | String         |                       |
| city        | String         |                       |
| state       | String         |                       |
| zipCode     | String         |                       |
| latitude    | Float          |                       |
| longitude   | Float          |                       |

### AddressFormat

| Field     | Type   |
|-----------|--------|
| structure | String |
| other     | String |

### CouponModel

| Field      | Type                     | Notes                 |
|------------|--------------------------|------------------------|
| id         | ID                       |                        |
| code       | String                   |                        |
| conditions | [CouponConditionModel!]! | requires subselection  |
| startDate  | DateTime                 |                        |
| endDate    | DateTime                 |                        |

### CouponConditionModel

| Field    | Type   |
|----------|--------|
| field    | String |
| operator | String |
| value    | String |

### DeliverySlotModel

| Field | Type   |
|-------|--------|
| id    | ID     |
| type  | String |
| from  | String |
| to    | String |

### Promotion

| Field       | Type                    | Notes                 |
|-------------|-------------------------|-----------------------|
| type        | String                  |                       |
| description | String                  |                       |
| isActive    | Boolean                 |                       |
| conditions  | [PromotionCondition!]!  | requires subselection |

### PromotionCondition

| Field    | Type  |
|----------|-------|
| quantity | Float |

### PromotionV2

| Field       | Type           | Notes                 |
|-------------|----------------|-----------------------|
| type        | String         |                       |
| description | String         |                       |
| isActive    | Boolean        |                       |
| conditions  | [Condition!]!  | requires subselection |

### Condition

| Field    | Type     |
|----------|----------|
| field    | String   |
| operator | String   |
| value    | String   |
| values   | [String] |

---

## Complete Example Queries

### Get active cart

```graphql
query GetActiveEcommerceCart($input: GetActiveEcommerceCartInput!) {
  getActiveEcommerceCart(getActiveCartInput: $input) {
    id
    status
    operationalModel
    store {
      id
      name
      reference
    }
    products {
      id
      name
      reference
      unit
      unitQuantity
      availability
      imageUrl
      status
      price {
        total
        subtotal
        taxes
        discount
        totalBeforeTaxes
      }
      promotion {
        type
        description
        isActive
        conditions {
          quantity
        }
      }
      promotions {
        type
        description
        isActive
        conditions {
          field
          operator
          value
          values
        }
      }
    }
    address {
      id
      description
      address {
        structure
        other
      }
      addressTwo
      city
      state
      zipCode
      latitude
      longitude
    }
    deliverySlot {
      id
      type
      from
      to
    }
    coupon {
      id
      code
      startDate
      endDate
      conditions {
        field
        operator
        value
      }
    }
  }
}

# Variables:
# { "input": { "storeReference": "81701", "operationalModel": "DELIVERY" } }
```

### Add product to cart

```graphql
mutation AddProductToEcommerceCart($input: AddProductToCartInput!) {
  addProductToEcommerceCart(addProductToCartInput: $input) {
    id
    status
    products {
      id
      name
      reference
      unit
      unitQuantity
      price {
        total
        subtotal
        taxes
        discount
        totalBeforeTaxes
      }
    }
  }
}

# Variables:
# {
#   "input": {
#     "cartId": "<cart-id>",
#     "reference": "560075",
#     "unit": "KOS",
#     "unitQuantity": 1.0
#   }
# }
```

### Update product in cart

```graphql
mutation UpdateProductInEcommerceCart($input: UpdateProductInCartInput!) {
  updateProductInEcommerceCart(updateProductInCartInput: $input) {
    id
    status
    products {
      id
      name
      reference
      unit
      unitQuantity
      price {
        total
        subtotal
        taxes
        discount
        totalBeforeTaxes
      }
    }
  }
}

# Variables:
# {
#   "input": {
#     "cartId": "<cart-id>",
#     "productId": "<product-id>",
#     "unit": "KOS",
#     "unitQuantity": 3.0
#   }
# }
```

### Delete product from cart

```graphql
mutation DeleteProductInEcommerceCart($input: DeleteProductInCartInput!) {
  deleteProductInEcommerceCart(deleteProductInCartInput: $input) {
    id
    status
    products {
      id
      name
      reference
      unit
      unitQuantity
    }
  }
}

# Variables:
# {
#   "input": {
#     "cartId": "<cart-id>",
#     "productId": "<product-id>"
#   }
# }
```

### Create new cart

```graphql
mutation CreateEcommerceCart($input: CreateEcommerceCartInput!) {
  createEcommerceCart(createCartInput: $input) {
    id
    status
    operationalModel
    store {
      id
      name
      reference
    }
  }
}

# Variables:
# {
#   "input": {
#     "storeReference": "81701",
#     "operationalModel": "DELIVERY",
#     "addressId": "<optional-address-id>"
#   }
# }
```

---

## Notes

- The SPAR Online frontend is built with Next.js App Router using React Server Components
- The GraphQL client is Apollo Client, configured in the app layout chunk
- The Apollo client splits requests between v2 and v3 endpoints based on context (`version: "v3"` goes to v3)
- Cart operations are on the **v3** endpoint
- Authentication uses Firebase (project: `spar-slovenia`)
- The `reference` field in AddProductToCartInput corresponds to the product `sku` (e.g., "560075", "542406")
- The `unit` field uses Slovenian abbreviations: "KOS" (piece/unit)
- Store reference for Ljubljana Interspar is "81701"
- The `CreateEcommerceCartInput` uses `storeReference` (NOT `storeId`)
