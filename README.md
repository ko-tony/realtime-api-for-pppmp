# PPPMP Data API

PPPMP 廣告使用的公開附屬資料 API，提供天氣、空氣品質及台灣股市大盤資料。

## API

對外資料 endpoints：

- `GET /api/v1/environment`
- `GET /api/v1/finance`：台灣加權指數與當日累計成交金額（億元），回傳單一物件。
  擷取程式、建表與每 3 分鐘排程設定見 [Finance 部署說明](cloudrun/README-finance.md)。

回傳各縣市的空氣品質與天氣即時值，由 `moenv_live` 與 `cwa_uv_live` 依縣市 JOIN 而成：

| 欄位 | 來源 | 說明 |
| --- | --- | --- |
| `cityName` | moenv | 縣市名，含「市」 |
| `aqi`、`pm25`、`o3` | moenv | 測站維修時為 `null` |
| `aqiDate` | moenv | 環境部發布時間 |
| `airTemperature`、`humidity`、`uvIndex`、`weather` | cwa | |
| `maxTemperature`、`minTemperature` | cwa | 測站當日截至觀測時間的最高／最低溫（攝氏），缺測為 `null` |
| `weatherDate` | cwa | 測站觀測時間 |

兩個時間欄位都是 `timestamptz`，回傳帶 `+08:00` 偏移。兩表縣市名格式不同（`臺北市` / `臺北`），JOIN 時以 `replace(cityName, '市', '')` 對齊。

舊路徑 `/cwa_uv_live`、`/moenv_live`、`/env_live_1` 與 `/api/v1/cwa-uv-live`、`/api/v1/air-quality` 已移除。`/weather`、帳號、OAuth 測試與 Excel 轉 Word 功能亦已移除。

## 資料擷取

`cloudrun/` 的寫入端各自由 Cloud Scheduler 定時觸發，把來源 API 的資料 upsert 進 PostgreSQL：

| 服務 | 資料來源 | 寫入 |
| --- | --- | --- |
| `get-cwa-uv-live` | 中央氣象署 O-A0003-001 | `cwa_uv_live` |
| `get-moenv-aqi-live-1` | 環境部 aqx_p_432 | `moenv_live` |
| `get-twse-finance-live` | 證交所 getChartOhlcStatis | `finance_live` |

`config.py` 負責環境變數，`db.py` 提供共用的 `upsert_rows()`。新增第三個資料源時，準備好表名與欄位順序即可直接呼叫，不需再寫一次 SQL。

最高／最低溫取自 CWA `WeatherElement.DailyExtreme.DailyHigh/DailyLow.TemperatureInfo.AirTemperature`，是當日觀測極值。部署擷取程式與公開 API 前，先以資料表擁有者執行 [`cloudrun/cwa-uv-live.sql`](cloudrun/cwa-uv-live.sql) 新增兩個欄位；既有資料等下次擷取成功後補值。欄位與缺測代碼見 [CWA 資料標準](https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0003-001.pdf)。

### 環境變數

| 變數 | 來源 | 值 |
| --- | --- | --- |
| `DB_HOST` | env var | `/cloudsql/PROJECT:REGION:INSTANCE` |
| `DB_USER` | env var | `ingest_user` |
| `DB_PASSWORD` | Secret Manager | `INGEST_DB_PASSWORD:latest` |
| `CWA_API_TOKEN` / `MOENV_API_KEY` | env var | 各自的政府 API 金鑰 |
| `DB_NAME` | 可省略 | 預設 `postgres` |
| `HTTP_TIMEOUT_SECONDS` | 可省略 | 預設 `15` |

缺少必填變數時會在請求當下拋 `RuntimeError` 並寫進 Cloud Logging，不會帶著空值連線。

### 部署

```bash
CONN=PROJECT:REGION:INSTANCE

gcloud run services update get-cwa-uv-live --region=asia-east1 \
  --add-cloudsql-instances=$CONN \
  --update-env-vars="^@^DB_HOST=/cloudsql/$CONN@DB_USER=ingest_user@CWA_API_TOKEN=<金鑰>" \
  --set-secrets=DB_PASSWORD=INGEST_DB_PASSWORD:latest
```

三個容易踩到的點：

- `--add-cloudsql-instances` 沒下，容器裡就不會有 `/cloudsql/` socket，錯誤是 `No such file or directory`。runtime service account 少了 `roles/cloudsql.client` 也是同樣症狀。
- `--set-env-vars` 是整組覆蓋，追加要用 `--update-env-vars`。
- 這兩支是 gen2 function，用 `gcloud functions deploy` 重新部署可能會蓋掉 Cloud SQL 掛載設定，部署後要補跑一次 `gcloud run services update`。

### 權限

- 寫入端使用 `ingest_user`，只有這兩張表的 `SELECT, INSERT, UPDATE`。
- Cloud Scheduler 以專屬 service account 帶 OIDC token 呼叫，該 SA 只有 `roles/run.invoker`。
- 兩支服務均為「需要驗證」且已移除 `allUsers` binding。

## 本機執行

環境變數：

```dotenv
SQLALCHEMY_DATABASE_URL=postgresql://user:password@host:5432/database
DB_SSLMODE=require
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=2
DB_CONNECT_TIMEOUT_SECONDS=5
BROWSER_CACHE_SECONDS=30
SHARED_CACHE_SECONDS=300
STALE_WHILE_REVALIDATE_SECONDS=600
```

直接 TCP 連線使用 `require`、`verify-ca` 或 `verify-full`。Cloud Run 透過 Cloud SQL Unix Socket 連線時，URL 使用 `?host=/cloudsql/PROJECT:REGION:INSTANCE`，並設定 `DB_SSLMODE=disable`；此處的 `disable` 只關閉 container 到本機 socket 的 libpq TLS，Cloud SQL 整合仍負責 socket 後端連線的加密與授權。程式會拒絕一般 TCP URL 使用 `disable`。

啟動與測試：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload
# 執行包含 Cloud Run 擷取程式的測試時，另安裝擷取依賴
.venv/bin/pip install -r requirements.txt -r cloudrun/requirements.txt
.venv/bin/python -m unittest discover
```

```bash
env/bin/python -m uvicorn main:app --reload
```

- API 文件：`http://127.0.0.1:8000/docs`
- Liveness：`GET /health`
- Database readiness：`GET /ready`

## 部署方向

現有網域與 External Application Load Balancer 可繼續沿用。短期可部署在既有 Managed Instance Group，但應改用固定版本 artifact、systemd 與 MIG rolling update，不再於 VM 開機時直接 `git pull`。較省維運的目標是把 Load Balancer backend 換成 Cloud Run serverless NEG；Cloud Run ingress 設為 `internal-and-cloud-load-balancing`，避免直接繞過 CDN/Armor。

資料庫密碼已改由 Secret Manager 提供（見上方「資料擷取」）。完整研究與遷移清單見 [`docs/deployment-security-research.md`](docs/deployment-security-research.md)。


## 素材確認轉發（預設關閉）

兩個獨立入口：

- 正式：`POST /api/v1/creative/view` → `CREATIVE_RELAY_PRIVATE_IP` / `CREATIVE_RELAY_HOSTNAME`。
- beta：`POST /api/v1/beta/creative/view` → `CREATIVE_RELAY_BETA_PRIVATE_IP` / `CREATIVE_RELAY_BETA_HOSTNAME`。

兩邊轉交至各自 CMS 的 `/api/v1/creative/view`，不依素材 URL 或客戶端參數選擇目的地，不互相 fallback。

選用的轉發入口僅轉交確認紀錄；不會讀取或下載 `url` 指向的素材。既有 environment/finance GET 與 CORS 契約維持原樣。此入口不依賴 PostgreSQL，且不列入目前公開 GET API 的 OpenAPI 清單。

| 環境變數 | 設定 |
| --- | --- |
| `CREATIVE_RELAY_ENABLED` | 共用開關，預設 `false`；僅 `true` 啟用 |
| `CREATIVE_RELAY_PRIVATE_IP` | 啟用時必填：正式 cms VM 的 RFC1918 IPv4，勿填公網 IP |
| `CREATIVE_RELAY_HOSTNAME` | 啟用時必填：正式站台及憑證對應的裸網域，例如 `cms-api.me-pppmp.com`，不含 scheme/path |
| `CREATIVE_RELAY_BETA_PRIVATE_IP` | 選用：beta cms VM 的 RFC1918 IPv4，須與 beta hostname 一起設定 |
| `CREATIVE_RELAY_BETA_HOSTNAME` | 選用：beta 站台及憑證對應的裸網域，例如 `beta-cms-api.me-pppmp.com`，須與 beta IP 一起設定 |
| `CREATIVE_RELAY_ALLOWED_ORIGINS` | 必填：預覽頁的 HTTPS origin，以逗號分隔，不含路徑或結尾斜線；不可用 `*` |

啟用時正式設定維持必填；beta 兩個變數皆省略時，只有 beta 路徑回覆 404。只填其中一個或設定無效會中止啟動，絕不改送正式 VM。共用開關停用時設定可省略，兩個路徑（含 OPTIONS）均回覆 404。兩個環境共用 `CREATIVE_RELAY_ALLOWED_ORIGINS`。

若先前將 beta IP/hostname 填在原本兩個變數，升級前需把它們移至 `CREATIVE_RELAY_BETA_*`，原本兩個變數改填正式目的地，並將 beta template base 改成 `/api/v1/beta`。不要沿用 beta 目的地作為正式設定。

Template 設定：

```dotenv
NEXT_PUBLIC_CMS_API_BASE_URL=https://realtime-api.me-pppmp.com/api/v1
NEXT_PUBLIC_CMS_BETA_API_BASE_URL=https://realtime-api.me-pppmp.com/api/v1/beta
```

本次只修改轉發服務；template 設定需另外更新並重新建置部署。

請求 JSON：`{"url":"https://素材網址", "role":"design7"}`。role 僅接受 `design7`、`it8` 或 null；省略/null 沿用 CMS 的業務確認。其他欄位拒絕；url 不超過 8192 字元，請求 body 上限 16 KiB。只接受 application/json。

轉發固定使用 TCP 443 與 `/api/v1/creative/view`，私網 IP 負責 TCP 連線，設定的 hostname 同時用於 TLS SNI、憑證驗證及 Host，因此不需要修改 DNS。不讀取環境代理、不轉送客戶端 Cookie/Authorization/X-Forwarded-For、不跟隨重新導向、不自動重試寫入。TLS/連線逾時 5 秒，連線後讀寫閒置逾時 10 秒，上游 JSON 上限 256 KiB。正常 JSON 與 HTTP 狀態原樣回傳（包含 CMS 404/409/422/429）；網路或格式錯誤回覆 502、逾時回覆 504。此路徑所有回覆皆 `Cache-Control: no-store`，不轉發上游 cookies/redirect headers，不記錄完整素材 URL/body。

### 部署前確認

1. Cloud Run 使用同區域 VPC Direct egress，並僅將私人 IP 流量送至 VPC；確認子網有足夠可用 IP。
2. Firewall 僅允許該 Cloud Run 子網來源至各環境目標 cms VM TCP 443，允許規則優先於匹配的 deny；不要將整台 VM 或全部 Port 公開。
3. 沿用既有公開 Load Balancer/網域；目前 Cloud Run ingress 限 internal + load balancing，瀏覽器不能直接使用停用的 run.app URL。確認負載平衡器/Armor允許兩個新路徑 POST、OPTIONS，且此路徑不快取。
4. 將實際預覽頁 origin 納入允許清單。預覽頁確認 API base：正式為轉發服務的公開網域 `/api/v1`，beta 為 `/api/v1/beta`；本次不修改預覽頁。
5. 先部署 beta 修訂版本再測試。從相同 Cloud Run 網路設定執行唯讀 HTTPS GET 至 CMS 已知路徑，使用內網 IP、正確 hostname/SNI 並驗證憑證，確認回覆的是正確 CMS。唯讀 GET 不可當成實際 POST 成功證據。
6. 經授權才以隔離素材測 POST，確認成功與過期素材/錯誤角色/CORS/重複確認等結果。逾時可能代表 CMS 已完成寫入，使用者重試前應先確認狀態。

這是匿名確認 API 的轉接；CORS 不是授權，知道連結者仍可能提交或轉傳不同角色的確認。需要身分/角色保證時須另行實作簽名 Token 或登入；此功能不宣稱解決該問題。公開入口應沿用既有流量限制/監控，不在程式中加入只對單一 instance 生效的假性限流。

回復方式：將 `CREATIVE_RELAY_ENABLED=false` 並部署新修訂，或切回前一版；預覽頁同時切回原 API base。確認沒有其他用途後再移除新增的 Firewall 規則與 VPC 設定。不要移除共用現有設定。

本機測試：`env/bin/python -m unittest tests.test_creative_relay`。mock 測試不證明線上 VPC、Firewall、TLS、Load Balancer 或真實素材資料可用；需依上述步驟分別驗證。本次未部署、未提交任何素材確認、未更動 GCP。
