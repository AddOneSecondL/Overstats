# queryCard

This file documents the upstream Dashen basic player card endpoint captured in `421_Full.txt`.

Sensitive values in examples are masked:

- `GL-Bigdata-Auth-Token` -> `<TOKEN>`
- `GL-Bigdata-Role-Id` -> `<ROLE_ID>`
- `token` query param -> `<CUSTOMER_TOKEN>`
- `bnetId` -> `<BNET_ID>`
- `customerToken` -> `<CUSTOMER_TOKEN>`
- `Cookie` / `GL-Uid` / `GL-DeviceId` / `traceId` -> `<MASKED>`

## Endpoint

`GET https://datamsapi.ds.163.com/v1/a19ld5tool/customer/queryCard`

Current `overstats` client method:

- `DashenAPIClient.query_card(customer_token)`

## Purpose

Query the player's basic card information.

This endpoint returns the lightweight identity card used as the base layer for:

- player name
- avatar
- title
- title icon
- level
- game time
- `customerToken`

Compared with `queryCountInfo`, this endpoint is much smaller and focuses on the base player card instead of competitive statistics.

## Request

### Query parameters

Masked example:

```text
season=
token=<CUSTOMER_TOKEN>
```

Field notes:

- `season`: optional season parameter; empty in the capture
- `token`: customer token resolved from `searchBnetAccount`

### Important headers

The captured request includes:

- `Accept: application/json, text/plain, */*`
- `GL-Bigdata-Auth-Token: <TOKEN>`
- `GL-Bigdata-Dts: 2026`
- `GL-Bigdata-Role-Id: <ROLE_ID>`
- `GL-Bigdata-Server: 1`
- `GL-ClientType: 60`
- `Origin: https://act.ds.163.com`
- `Referer: https://act.ds.163.com/`
- `User-Agent: Mozilla/5.0 ... app/df_client ...`

Sensitive or session-bound headers should be masked in docs:

- `Cookie`
- `GL-DeviceId`
- `GL-Uid`
- `GL-X-XSRF-TOKEN`

## Response

### Success example

```json
{
  "code": 0,
  "data": {
    "bnetId": "<BNET_ID>",
    "name": "GrowlR#5632",
    "icon": "https://ld5picproxy.ds.163.com/overwatch/<MASKED>.png",
    "title": "string",
    "titleIcon": "https://ld5picproxy.ds.163.com/overwatch/<MASKED>.png",
    "level": 4,
    "gameTime": "1063.29",
    "customerToken": "<CUSTOMER_TOKEN>",
    "riskStatus": {
      "expireTime": 1787127797000,
      "status": "SUSPENDED"
    }
  },
  "success": true,
  "traceId": "<MASKED>"
}
```

### Response field notes

- `code == 0`: request succeeded
- `success == true`: request succeeded
- `data.bnetId`: numeric Battle.net id
- `data.name`: normalized BattleTag / player display name
- `data.icon`: avatar URL
- `data.title`: title text
- `data.titleIcon`: title icon URL
- `data.level`: player display level
- `data.gameTime`: total playtime string
- `data.customerToken`: customer token returned again in the card payload
- `data.riskStatus`: optional restriction entry; it is present only while the player is suspended
- `data.riskStatus.expireTime`: suspension expiry as a Unix timestamp in milliseconds
- `data.riskStatus.status`: reserved upstream status value; Overstats currently treats every present `riskStatus` entry as “suspended” and does not assign meaning to individual values
- `traceId`: upstream trace id

## Raw Capture Mapping

The request in `421_Full.txt` is:

```text
GET /v1/a19ld5tool/customer/queryCard?season=&token=<CUSTOMER_TOKEN>
```

with Bigdata auth headers:

```text
GL-Bigdata-Auth-Token: <TOKEN>
GL-Bigdata-Dts: 2026
GL-Bigdata-Role-Id: <ROLE_ID>
GL-Bigdata-Server: 1
```

and returns:

```json
{
  "code": 0,
  "data": {
    "bnetId": "<BNET_ID>",
    "name": "GrowlR#5632",
    "icon": "https://ld5picproxy.ds.163.com/overwatch/<MASKED>.png",
    "title": "string",
    "titleIcon": "https://ld5picproxy.ds.163.com/overwatch/<MASKED>.png",
    "level": 4,
    "gameTime": "1063.29",
    "customerToken": "<CUSTOMER_TOKEN>",
    "riskStatus": {
      "expireTime": 1787127797000,
      "status": "SUSPENDED"
    }
  },
  "success": true,
  "traceId": "<MASKED>"
}
```

## Notes

- The raw `title` text in `421_Full.txt` looks garbled because the capture text encoding is not fully normalized.
- This endpoint is the basic player card endpoint.
- The more detailed competitive card / stat payload is documented separately in `queryCountInfo.md`.
